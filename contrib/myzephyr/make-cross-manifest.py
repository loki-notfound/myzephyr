#!/usr/bin/env python3
"""Write the build manifest of a cross-built zephyrd (schema manifest-cross.schema.json).

  make-cross-manifest.py --target T --source-identity F --expected-version F --builder-logs D
                         --static-report F --embedded-report F --binary F --build-dir D
                         --recipe-dir D --out F (--checkout-record F | --local)

T is aarch64-linux-gnu (ELF, check-elf.sh --arch aarch64), x86_64-apple-darwin (Mach-O,
check-macho.py), aarch64-apple-darwin (Mach-O, check-macho.py --arch arm64) or
x86_64-w64-mingw32 (PE, check-pe.py). --embedded-report is
check-embedded.py's. Source, base, workflow, builder and recipe records are made as by
make-manifest.py (whose helpers are reused). The binary is never executed here: its version
is the embedded string; the native runtime job runs it.

Consistency checks, recorded under "checks"; any failure exits 1 after writing:
  expected_version_matches_source_state  as in make-manifest.py
  embedded_version_matches_expected      the only embedded version string is the expected one
  binary_matches_static_report           the static report describes this binary and passed
  binary_matches_embedded_report         the embedded report describes this binary and passed
  workflow_identity_allowed              as in make-manifest.py
"""
import argparse
import importlib.util
import json
import os
import re
import sys

here = os.path.dirname(os.path.abspath(__file__))
# no __pycache__ in the checkout: verify-source.sh counts ignored files as unclean
sys.dont_write_bytecode = True
spec = importlib.util.spec_from_file_location("make_manifest", os.path.join(here, "make-manifest.py"))
mm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mm)

SCHEMA = "myzephyr/daemon-cross-build-manifest/2"
TARGETS = {"aarch64-linux-gnu": ("elf", "zephyrd"), "x86_64-apple-darwin": ("macho", "zephyrd"),
           "aarch64-apple-darwin": ("macho", "zephyrd"), "x86_64-w64-mingw32": ("pe", "zephyrd.exe")}
REPORT_KEYS = {"elf": ("elf_sha256", "elf_checks"), "macho": ("macho_sha256", "macho_checks"),
               "pe": ("pe_sha256", "pe_checks")}


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    for name in ("target", "source-identity", "expected-version", "builder-logs", "static-report",
                 "embedded-report", "binary", "build-dir", "recipe-dir", "out"):
        p.add_argument(f"--{name}", required=True)
    p.add_argument("--local", action="store_true", help="a local replay, not a GitHub Actions run")
    p.add_argument("--checkout-record", help="ci-checkout.sh's record (required outside --local)")
    a = p.parse_args()
    if a.target not in TARGETS:
        sys.exit(f"make-cross-manifest: unknown target {a.target}")
    fmt, name = TARGETS[a.target]
    if os.path.basename(a.binary) != name:
        sys.exit(f"make-cross-manifest: {a.target} binary must be named {name}")

    src, groups = mm.kv(a.source_identity)
    static, _ = mm.kv(a.static_report)
    emb, _ = mm.kv(a.embedded_report)
    logs = a.builder_logs
    image = open(os.path.join(logs, "image.txt")).read().split()
    apt_state = open(os.path.join(logs, "builder-apt-state.txt")).read().splitlines()
    dockerfile = open(os.path.join(a.recipe_dir, "Dockerfile")).read()
    packages = [l for l in open(os.path.join(logs, "builder-packages.tsv")) if l.strip()]
    expected = open(a.expected_version).read().strip()
    commit = src["source_commit"]
    state = mm.source_state(src, a.checkout_record, a.local)
    own = [{"commit": c, "paths": paths.split()} for c, paths in groups.get("own_commit", {}).items()]
    if len(own) != int(src["own_commit_count"]):
        sys.exit("make-cross-manifest: own_commit lines do not match own_commit_count")
    workflow, wf_check = mm.workflow_record(commit, a.local)
    version_state_ok = mm.version_state_ok(expected, commit, state)
    digest = mm.sha256(a.binary)
    sha_key, checks_key = REPORT_KEYS[fmt]
    versions = emb.get("embedded_versions", "").split()
    checks = {
        "expected_version_matches_source_state": version_state_ok,
        "embedded_version_matches_expected": versions == [expected] and emb.get("embedded_expected_version") == expected,
        "binary_matches_static_report": static.get(sha_key) == digest and static.get(checks_key) == "passed",
        "binary_matches_embedded_report": emb.get("embedded_sha256") == digest and emb.get("embedded_checks") == "passed",
        "workflow_identity_allowed": wf_check,
    }
    manifest = {
        "schema": SCHEMA,
        "artifact": {"name": name, "size": os.path.getsize(a.binary), "sha256": digest,
                     "expected_version": expected, "target": a.target, "format": fmt},
        "source": {"commit": commit, "commit_time": int(src["source_commit_time"]), **state,
                   "own_commits": own, "submodules": groups.get("submodule", {})},
        "base": {"repository": src.get("base_repository") or None, "tag": src["base_tag"],
                 "tag_object": src["base_tag_object"], "commit": src["base_commit"],
                 "signer_primary_fingerprint": src["base_signer_primary"], "signing_key": src["base_signing_key"]},
        "own_commit_signer_primary_fingerprint": src["maintainer_primary"],
        "workflow": workflow,
        "builder": {
            "target": a.target,
            "base_image": re.search(r"^FROM\s+(\S+)", dockerfile, re.M).group(1),
            "apt_snapshot": next((l.split()[1] for l in apt_state if l.startswith("snapshot ")), None),
            "apt_state": apt_state,
            "image_id": image[0] if image else None,
            "toolchain": open(os.path.join(logs, "toolchain.txt")).read().splitlines(),
            "package_inventory_sha256": mm.sha256(os.path.join(logs, "builder-packages.tsv")),
            "package_count": len(packages),
            "source_date_epoch": int(src["source_commit_time"]),
        },
        "build": {
            "recipe": mm.recipe(a.recipe_dir),
            "steps": open(os.path.join(logs, "steps.txt")).read().splitlines(),
            "cmake_options": [f"-DCMAKE_TOOLCHAIN_FILE=<src>/contrib/depends/{a.target}/share/toolchain.cmake",
                              "-DCMAKE_SKIP_RPATH=ON"],
            "cmake_target": "daemon",
            "cpu_flags": mm.cpu_flags(a.build_dir),
            "link_inventory_sha256": mm.link_inventory(logs),
        },
        "static_report": {"format": fmt, "values": static, "checks": static.get(checks_key)},
        "embedded": {"versions": versions, "seeds": emb.get("embedded_seeds", "").split(),
                     "checks": emb.get("embedded_checks")},
        "checks": checks,
    }
    with open(a.out, "w") as f:
        json.dump(manifest, f, indent=2, sort_keys=True)
        f.write("\n")
    bad = [k for k, v in checks.items() if v is not True and v != "not-applicable"]
    if bad:
        print(f"make-cross-manifest: written {a.out}, but checks failed: {bad}", file=sys.stderr)
        sys.exit(1)
    print(f"manifest written: {a.out}")


if __name__ == "__main__":
    main()
