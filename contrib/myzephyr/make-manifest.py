#!/usr/bin/env python3
"""Write the build manifest of a Linux zephyrd build (schema manifest.schema.json).

  make-manifest.py --source-identity F --expected-version F --builder-logs D
                   --elf-report F --binary F --version-output F --build-dir D
                   --recipe-dir D --out F (--checkout-record F | --local)

Inputs: the key=value files written by verify-source.sh and check-elf.sh, the
expected version (zephyrd-check.py expected-version), the log directory of
run-builder.sh (image.txt, toolchain.txt, steps.txt, builder-packages.tsv,
builder-apt-state.txt), the CMake build directory (flags.make files are scanned
for CPU-specific compiler options), the recipe directory (linux/) and the record of
ci-checkout.sh (fetch mode, no tag in the checkout).

The manifest keeps three identities apart:
  source    the commit that was compiled (the pushed commit, or the head commit of a pull
            request), "tags_at_head": "none" and how the checkout was fetched;
  base      the signed zephyr-backports tag the source descends from;
  workflow  the GitHub Actions run, read from the GITHUB_* environment and
            MYZ_PULL_REQUEST (written by run-identity.py), or {"local_build": true} with --local.
The base tag never points at the source commit unless they are the same commit.

Consistency checks, recorded under "checks"; any failure exits 1 after writing:
  expected_version_matches_source_state  no tag at the source commit and the expected
                                         version is <number>-<first 9 hex digits of it>;
                                         "release" is never accepted
  version_output_matches_expected        --version ends with "(v<expected>)"
  binary_matches_elf_report              the ELF report describes this binary
  workflow_identity_allowed              the run identity is a row of run-identity.py's
                                         table and its built commit is the source commit
                                         ("not-applicable" with --local)
"""
import argparse
import glob
import hashlib
import importlib.util
import json
import os
import re
import sys

sys.dont_write_bytecode = True
_spec = importlib.util.spec_from_file_location(
    "run_identity", os.path.join(os.path.dirname(os.path.abspath(__file__)), "run-identity.py"))
ri = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ri)

SCHEMA = "myzephyr/daemon-build-manifest/3"
FETCH_MODE = "depth-1-no-tags+unshallow-no-tags"
VERSION_RE = re.compile(r"(\d+\.\d+\.\d+)-([0-9a-f]{9})")
CPU_FLAG_RE = re.compile(r"(?<!\S)-m(arch|tune|cpu|aes|avx\w*|sse\w*|ssse3|pclmul|bmi\w*|fma|rdrnd|sha)(=\S+)?")
RECIPE_FILES = ("Dockerfile", "run-builder.sh", "build-in-container.sh")
GITHUB_ENV = {"repository": "GITHUB_REPOSITORY", "ref": "GITHUB_REF", "sha": "GITHUB_SHA",
              "workflow_ref": "GITHUB_WORKFLOW_REF", "workflow_sha": "GITHUB_WORKFLOW_SHA",
              "event_name": "GITHUB_EVENT_NAME", "run_id": "GITHUB_RUN_ID",
              "run_number": "GITHUB_RUN_NUMBER", "run_attempt": "GITHUB_RUN_ATTEMPT",
              "job": "GITHUB_JOB", "server_url": "GITHUB_SERVER_URL"}


def kv(path):
    """key=value lines; keys "<prefix> <name>" are grouped per prefix."""
    out, groups = {}, {}
    for line in open(path):
        line = line.rstrip("\n")
        if not line or "=" not in line:
            continue
        k, v = line.split("=", 1)
        if " " in k:
            prefix, name = k.split(" ", 1)
            groups.setdefault(prefix, {})[name] = v
        else:
            out[k] = v
    return out, groups


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def cpu_flags(build_dir):
    """Global and per-file CPU options from CMake's flags.make files."""
    found = {}
    for fm in glob.glob(os.path.join(build_dir, "**", "flags.make"), recursive=True):
        target = os.path.relpath(os.path.dirname(fm), build_dir)
        for line in open(fm):
            if not (line.startswith("C_FLAGS") or line.startswith("CXX_FLAGS") or line.startswith("# Custom flags:")):
                continue
            where = "all sources" if not line.startswith("# Custom") else line.split(":", 1)[1].split("_FLAGS")[0].strip()
            for m in CPU_FLAG_RE.finditer(line):
                found.setdefault(m.group(0), set()).add(target if where == "all sources" else where)
    return {flag: {"count": len(places), "examples": sorted(places)[:5]} for flag, places in sorted(found.items())}


def source_state(src, record_path, local):
    """tags_at_head, tags_in_checkout and fetch_mode from the source identity and the checkout record."""
    rec = {}
    if record_path:
        rec, _ = kv(record_path)
        if rec.get("built_commit") != src["source_commit"] or rec.get("tags_in_checkout") != "0":
            sys.exit(f"make-manifest: checkout record {record_path} is not for {src['source_commit']} without tags")
    elif not local:
        sys.exit("make-manifest: --checkout-record is required outside --local")
    return {"tags_at_head": src.get("tags_at_head"),
            "tags_in_checkout": int(src["tags_in_checkout"]) if src.get("tags_in_checkout", "").isdigit() else None,
            "fetch_mode": rec.get("fetch_mode", "local") if (record_path or local) else None}


def workflow_record(commit, local):
    """(workflow, workflow_identity_allowed check) from the environment."""
    if local:
        return {"local_build": True}, "not-applicable"
    missing = [v for v in list(GITHUB_ENV.values()) + ["MYZ_PULL_REQUEST"] if not os.environ.get(v)]
    if missing:
        sys.exit(f"make-manifest: not a GitHub Actions environment (missing {missing}); use --local for a replay")
    workflow = {k: os.environ[v] for k, v in GITHUB_ENV.items()}
    workflow["pull_request"] = ri.parse_pull_request(os.environ["MYZ_PULL_REQUEST"])
    errs = ri.errors(dict(workflow, built_commit=commit))
    for e in errs:
        print(f"make-manifest: run identity: {e}", file=sys.stderr)
    return workflow, not errs


def version_state_ok(expected, commit, state):
    m = VERSION_RE.fullmatch(expected)
    return bool(m) and m.group(2) == commit[:9] and state["tags_at_head"] == "none" and state["tags_in_checkout"] == 0


def recipe(recipe_dir):
    files = {name: sha256(os.path.join(recipe_dir, name)) for name in RECIPE_FILES}
    combined = hashlib.sha256("".join(f"{files[n]}  {n}\n" for n in sorted(files)).encode()).hexdigest()
    return {"files": files, "sha256": combined}


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    for a in ("source-identity", "expected-version", "builder-logs", "elf-report", "binary",
              "version-output", "build-dir", "recipe-dir", "out"):
        p.add_argument(f"--{a}", required=True)
    p.add_argument("--local", action="store_true", help="a local replay, not a GitHub Actions run")
    p.add_argument("--checkout-record", help="ci-checkout.sh's record (required outside --local)")
    a = p.parse_args()

    src, groups = kv(a.source_identity)
    elf, _ = kv(a.elf_report)
    logs = a.builder_logs
    image = open(os.path.join(logs, "image.txt")).read().split()
    toolchain = open(os.path.join(logs, "toolchain.txt")).read().splitlines()
    steps = open(os.path.join(logs, "steps.txt")).read().splitlines()
    apt_state = open(os.path.join(logs, "builder-apt-state.txt")).read().splitlines()
    dockerfile = open(os.path.join(a.recipe_dir, "Dockerfile")).read()
    base_image = re.search(r"^FROM\s+(\S+)", dockerfile, re.M).group(1)
    snapshot = next((l.split()[1] for l in apt_state if l.startswith("snapshot ")), None)
    packages = [l.split("\t") for l in open(os.path.join(logs, "builder-packages.tsv")) if l.strip()]
    expected = open(a.expected_version).read().strip()
    version_output = open(a.version_output).read().strip()

    commit = src["source_commit"]
    state = source_state(src, a.checkout_record, a.local)
    own = [{"commit": c, "paths": paths.split()} for c, paths in groups.get("own_commit", {}).items()]
    if len(own) != int(src["own_commit_count"]):
        sys.exit("make-manifest: own_commit lines do not match own_commit_count")

    workflow, wf_check = workflow_record(commit, a.local)
    binary_sha = sha256(a.binary)
    checks = {
        "expected_version_matches_source_state": version_state_ok(expected, commit, state),
        "version_output_matches_expected": len(version_output.splitlines()) == 1 and version_output.endswith(f"(v{expected})"),
        "binary_matches_elf_report": elf.get("elf_sha256") == binary_sha,
        "workflow_identity_allowed": wf_check,
    }

    manifest = {
        "schema": SCHEMA,
        "artifact": {
            "name": os.path.basename(a.binary),
            "size": os.path.getsize(a.binary),
            "sha256": binary_sha,
            "version_output": version_output,
            "expected_version": expected,
            "target": "x86_64-unknown-linux-gnu",
        },
        "source": {
            "commit": commit,
            "commit_time": int(src["source_commit_time"]),
            **state,
            "own_commits": own,
            "submodules": groups.get("submodule", {}),
        },
        "base": {
            "repository": src.get("base_repository") or None,
            "tag": src["base_tag"],
            "tag_object": src["base_tag_object"],
            "commit": src["base_commit"],
            "signer_primary_fingerprint": src["base_signer_primary"],
            "signing_key": src["base_signing_key"],
        },
        "own_commit_signer_primary_fingerprint": src["maintainer_primary"],
        "workflow": workflow,
        "builder": {
            "base_image": base_image,
            "apt_snapshot": snapshot,
            "apt_state": apt_state,
            "image_id": image[0] if image else None,
            "toolchain": toolchain,
            "package_inventory_sha256": sha256(os.path.join(logs, "builder-packages.tsv")),
            "package_count": len(packages),
            "source_date_epoch": int(src["source_commit_time"]),
        },
        "build": {
            "recipe": recipe(a.recipe_dir),
            "steps": steps,
            "cmake_options": ["-DCMAKE_TOOLCHAIN_FILE=<src>/contrib/depends/x86_64-unknown-linux-gnu/share/toolchain.cmake",
                              "-DCMAKE_SKIP_RPATH=ON"],
            "cmake_target": "daemon",
            "cpu_flags": cpu_flags(a.build_dir),
        },
        "runtime_requirements": {
            "interpreter": elf.get("elf_interpreter"),
            "needed": elf.get("elf_needed", "").split(),
            "rpath_runpath": elf.get("elf_rpath_runpath"),
            "max_glibc": elf.get("elf_max_glibc"),
            "max_glibc_allowed": elf.get("elf_max_glibc_allowed"),
            "cxx_version_needs": elf.get("elf_cxx_version_needs"),
            "symbols_above_glibc_2_17": elf.get("elf_symbols_above_glibc_2_17", "").split(),
            "elf_checks": elf.get("elf_checks"),
            "build_id": elf.get("elf_build_id"),
        },
        "checks": checks,
    }
    with open(a.out, "w") as f:
        json.dump(manifest, f, indent=2, sort_keys=True)
        f.write("\n")
    bad = [k for k, v in checks.items() if v is not True and v != "not-applicable"]
    if bad:
        print(f"make-manifest: written {a.out}, but checks failed: {bad}", file=sys.stderr)
        sys.exit(1)
    print(f"manifest written: {a.out}")


if __name__ == "__main__":
    main()
