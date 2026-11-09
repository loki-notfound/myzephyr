#!/usr/bin/env python3
"""Self-test of verify-artifact.py: one valid artifact, then one changed variable per case.

  artifact-verify-selftest.py <work-dir>
      fixture mode: the metadata of run 42543200624's release artifact (artifact-fixture/;
      build-logs/toolchain.txt is rebuilt from the manifest), with placeholder bytes instead
      of the 25 MB binary, plus a tagged variant;
  artifact-verify-selftest.py <work-dir> --artifact DIR -- <verify-artifact.py trusted options>
      real mode: a downloaded artifact and the trusted options its verification uses
      (everything except --artifact and --report).

<work-dir> must not exist. Each case gets its own copy of the valid artifact (the binary is
hard-linked unless the case changes it), changes exactly one thing, re-seals SHA256SUMS
unless the case is about SHA256SUMS, and must be rejected with exit 1 and a diagnostic
naming that thing. The valid cases must pass with exit 0. Nothing in an artifact is ever
executed; the placeholder is not a program. Exit 0 when every case gives the intended verdict.
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys

here = os.path.dirname(os.path.abspath(__file__))
tooling = os.path.dirname(here)
verifier = os.path.join(tooling, "verify-artifact.py")
fixture = os.path.join(here, "artifact-fixture")
SUMMED = ("zephyrd", "manifest.json", "expected-version.txt", "source-identity.txt")
OTHER = "1111111111111111111111111111111111111111"


def sha256(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def read(path):
    with open(path) as f:
        return f.read()


def write(path, text):
    with open(path, "w") as f:
        f.write(text)


def reseal(d):
    write(os.path.join(d, "SHA256SUMS"), "".join(f"{sha256(os.path.join(d, n))}  {n}\n" for n in SUMMED))


def load(d):
    with open(os.path.join(d, "manifest.json")) as f:
        return json.load(f)


def save(d, m):
    write(os.path.join(d, "manifest.json"), json.dumps(m, indent=2, sort_keys=True) + "\n")


def kv_set(path, key, value):
    lines = read(path).splitlines()
    out = [f"{key}={value}" if l.split("=", 1)[0] == key else l for l in lines]
    assert out != lines, f"{key} not in {path}"
    write(path, "\n".join(out) + "\n")


def copy_artifact(src, dst):
    os.makedirs(dst)
    for top, dirs, names in os.walk(src):
        rel = os.path.relpath(top, src)
        for n in dirs:
            os.makedirs(os.path.join(dst, rel, n), exist_ok=True)
        for n in names:
            s, t = os.path.join(top, n), os.path.join(dst, rel, n)
            if rel == "." and n == "zephyrd":
                try:
                    os.link(s, t)
                    continue
                except OSError:
                    pass
            shutil.copyfile(s, t)


def own_copy(path):
    """Replace a hard link by a private copy before changing it."""
    tmp = path + ".copy"
    shutil.copyfile(path, tmp)
    os.replace(tmp, path)


# ------------------------------------------------------------------ the cases
# Each mutation gets (artifact dir, trusted dict) and returns the expected diagnostic fragment.
# "seal" = re-seal SHA256SUMS afterwards, so the case changes only its own variable.

def manifest_case(fn):
    def run(d, t):
        m = load(d)
        frag = fn(m, t)
        save(d, m)
        return frag
    return run


def m_set(path, value, frag):
    def fn(m, t):
        *parents, last = path
        node = m
        for p in parents:
            node = node[p]
        node[last] = value(node[last]) if callable(value) else value
        return frag
    return manifest_case(fn)


def m_del(path, frag):
    def fn(m, t):
        *parents, last = path
        node = m
        for p in parents:
            node = node[p]
        del node[last]
        return frag
    return manifest_case(fn)


def version_claim(d, t):
    m = load(d)
    m["artifact"]["expected_version"] = "2.3.1-e66283f38"
    save(d, m)
    write(os.path.join(d, "expected-version.txt"), "2.3.1-e66283f38\n")
    return "artifact.expected_version"


def version_output(d, t):
    m = load(d)
    m["artifact"]["version_output"] = m["artifact"]["version_output"].replace(t["expected-version"], "2.3.0-000000000")
    save(d, m)
    write(os.path.join(d, "version.txt"), m["artifact"]["version_output"] + "\n")
    return "artifact.version_output"


def local_build(d, t):
    m = load(d)
    m["workflow"] = {"local_build": True}
    m["checks"]["workflow_sha_is_source_commit"] = "not-applicable"
    save(d, m)
    return "local_build is not public CI provenance"


def duplicate_key(d, t):
    text = read(os.path.join(d, "manifest.json"))
    write(os.path.join(d, "manifest.json"), text.replace('"schema":', '"schema": "x",\n  "schema":', 1))
    return "duplicate key"


def nan_value(d, t):
    m = load(d)
    m["artifact"]["size"] = "@NAN@"
    save(d, m)
    p = os.path.join(d, "manifest.json")
    write(p, read(p).replace('"@NAN@"', "NaN"))
    return "non-standard number"


def binary_changed(d, t):
    p = os.path.join(d, "zephyrd")
    own_copy(p)
    with open(p, "ab") as f:
        f.write(b"\0")
    return "zephyrd matches SHA256SUMS"


def sums_edit(fn):
    def run(d, t):
        p = os.path.join(d, "SHA256SUMS")
        lines = read(p).splitlines()
        text, frag = fn(lines, d)
        write(p, text)
        return frag
    return run


def sums_drop_identity(lines, d):
    return "".join(l + "\n" for l in lines if not l.endswith("source-identity.txt")), "SHA256SUMS entries"


def sums_duplicate(lines, d):
    return "".join(l + "\n" for l in lines + [lines[0]]), "listed once"


def sums_malformed(lines, d):
    return "".join(l.replace("  ", " ", 1) + "\n" if i == 0 else l + "\n" for i, l in enumerate(lines)), "well-formed"


def sums_upper(lines, d):
    return "".join((l[:64].upper() + l[64:] if i == 0 else l) + "\n" for i, l in enumerate(lines)), "well-formed"


def sums_escape(lines, d):
    h = lines[0].split()[0]
    return "".join(l + "\n" for l in lines) + f"{h}  ../zephyrd\n", "is a plain file name"


def sums_absolute(lines, d):
    h = lines[0].split()[0]
    return "".join(l + "\n" for l in lines) + f"{h}  /etc/hostname\n", "is a plain file name"


def sums_extra(lines, d):
    return "".join(l + "\n" for l in lines) + f"{sha256(os.path.join(d, 'version.txt'))}  version.txt\n", "SHA256SUMS entries"


def sums_no_newline(lines, d):
    return "\n".join(lines), "ends with a newline"


def symlink_binary(d, t):
    p = os.path.join(d, "zephyrd")
    real = os.path.join(os.path.dirname(d), os.path.basename(d) + "-real-zephyrd")
    shutil.copyfile(p, real)
    os.remove(p)
    os.symlink(real, p)
    return "no symlinks or special files"


def symlink_log(d, t):
    p = os.path.join(d, "build-logs", "steps.txt")
    real = os.path.join(os.path.dirname(d), os.path.basename(d) + "-steps.txt")
    shutil.copyfile(p, real)
    os.remove(p)
    os.symlink(real, p)
    return "no symlinks or special files"


def identity_changed(d, t):
    p = os.path.join(d, "source-identity.txt")
    write(p, read(p).replace("src/p2p/net_node.h ", "", 1))
    return "identical to the trusted source identity"


def file_append(rel, text, frag):
    def run(d, t):
        with open(os.path.join(d, rel), "a") as f:
            f.write(text)
        return frag
    return run


def file_replace(rel, old, new, frag):
    def run(d, t):
        p = os.path.join(d, rel)
        s = read(p)
        assert old in s, f"{old!r} not in {rel}"
        write(p, s.replace(old, new, 1))
        return frag
    return run


def file_remove(rel, frag):
    def run(d, t):
        os.remove(os.path.join(d, rel))
        return frag
    return run


def trusted(key, value, frag):
    def run(d, t):
        t[key] = value
        return frag
    return run


def trusted_elf_failed(d, t):
    p = os.path.join(d + "-trusted", "elf-report.txt")
    shutil.copyfile(t["elf-report"], p)
    kv_set(p, "elf_checks", "failed")
    t["elf-report"] = p
    return "trusted ELF report elf_checks"


def trusted_recipe_changed(d, t):
    r = os.path.join(d + "-trusted", "recipe")
    shutil.copytree(t["recipe-dir"], r)
    with open(os.path.join(r, "run-builder.sh"), "a") as f:
        f.write("# changed\n")
    t["recipe-dir"] = r
    return "build.recipe.files"


def trusted_tag_at_head(d, t):
    p = os.path.join(d + "-trusted", "source-identity.txt")
    lines = read(t["source-identity"]).splitlines()
    lines.insert(2, f"source_tag v9.9.9-test={OTHER} {t['maintainer-fingerprint']}")
    write(p, "\n".join(lines) + "\n")
    t["source-identity"] = p
    return "source.tags"


NEGATIVE = [
    # schema identifier and structure
    ("schema-wrong-id", m_set(["schema"], "myzephyr/daemon-build-manifest/1", "manifest.schema"), True),
    ("schema-missing", m_del(["schema"], "missing schema"), True),
    ("extra-property", m_set(["unexpected"], 1, "manifest.unexpected: not allowed"), True),
    ("duplicate-json-key", duplicate_key, True),
    ("nan-number", nan_value, True),
    ("size-as-string", m_set(["artifact", "size"], lambda v: str(v), "manifest.artifact.size: type string"), True),
    ("check-as-integer", m_set(["checks", "version_output_matches_expected"], 1, "manifest.checks.version_output_matches_expected"), True),
    # workflow identity against the trusted CI context
    ("workflow-sha-mismatch", m_set(["workflow", "workflow_sha"], "0" * 40, "workflow.workflow_sha"), True),
    ("workflow-commit-mismatch", m_set(["workflow", "sha"], OTHER, "workflow.sha"), True),
    ("source-commit-mismatch", m_set(["source", "commit"], OTHER, "source.commit"), True),
    ("run-id-wrong", m_set(["workflow", "run_id"], "42543200625", "workflow.run_id"), True),
    ("run-attempt-wrong", m_set(["workflow", "run_attempt"], "2", "workflow.run_attempt"), True),
    ("repository-wrong", m_set(["workflow", "repository"], "someone/myzephyr", "workflow.repository"), True),
    ("workflow-ref-wrong", m_set(["workflow", "workflow_ref"], lambda v: v.replace("daemon-release-baseline.yml", "other.yml"), "workflow.workflow_ref"), True),
    ("ref-wrong", m_set(["workflow", "ref"], "refs/heads/other", "workflow.ref"), True),
    ("producer-job-wrong", m_set(["workflow", "job"], "unit-tests", "workflow.job"), True),
    ("local-build", local_build, True),
    # base and signer policy
    ("base-tag-wrong", m_set(["base", "tag"], "v2.3.0-sec.1", "base.tag (pinned)"), True),
    ("base-commit-wrong", m_set(["base", "commit"], OTHER, "base.commit (pinned)"), True),
    ("base-tag-object-wrong", m_set(["base", "tag_object"], OTHER, "base.tag_object (pinned)"), True),
    ("base-repository-wrong", m_set(["base", "repository"], "https://example.invalid/zephyr.git", "base.repository (pinned)"), True),
    ("base-signer-wrong", m_set(["base", "signer_primary_fingerprint"], "A" * 40, "base.signer_primary_fingerprint (pinned)"), True),
    ("base-signing-key-wrong", m_set(["base", "signing_key"], "B" * 40, "base.signing_key"), True),
    ("own-signer-wrong", m_set(["own_commit_signer_primary_fingerprint"], "C" * 40, "own_commit_signer_primary_fingerprint"), True),
    # recorded checks and ELF state
    ("check-version-state-false", m_set(["checks", "expected_version_matches_source_state"], False, "manifest.checks.expected_version_matches_source_state"), True),
    ("check-version-output-false", m_set(["checks", "version_output_matches_expected"], False, "manifest.checks.version_output_matches_expected"), True),
    ("check-elf-report-false", m_set(["checks", "binary_matches_elf_report"], False, "manifest.checks.binary_matches_elf_report"), True),
    ("check-workflow-sha-false", m_set(["checks", "workflow_sha_is_source_commit"], False, "manifest.checks.workflow_sha_is_source_commit"), True),
    ("elf-checks-failed", m_set(["runtime_requirements", "elf_checks"], "failed", "runtime_requirements.elf_checks"), True),
    ("rpath-present", m_set(["runtime_requirements", "rpath_runpath"], "(RUNPATH) /src/lib", "runtime_requirements.rpath_runpath"), True),
    ("needed-extra-library", m_set(["runtime_requirements", "needed"], lambda v: v + ["libstdc++.so.6"], "runtime_requirements.needed"), True),
    ("interpreter-wrong", m_set(["runtime_requirements", "interpreter"], "/lib/ld-musl-x86_64.so.1", "runtime_requirements.interpreter"), True),
    ("glibc-allowance-raised", m_set(["runtime_requirements", "max_glibc_allowed"], "GLIBC_2.36", "runtime_requirements.max_glibc_allowed"), True),
    # binary, target and version
    ("size-wrong", m_set(["artifact", "size"], lambda v: v + 1, "artifact.size"), True),
    ("sha256-wrong", m_set(["artifact", "sha256"], "0" * 64, "artifact.sha256"), True),
    ("target-wrong", m_set(["artifact", "target"], "aarch64-linux-gnu", "artifact.target"), True),
    ("name-wrong", m_set(["artifact", "name"], "zephyr-wallet-rpc", "artifact.name"), True),
    ("version-claim-wrong", version_claim, True),
    ("version-output-wrong", version_output, True),
    ("tag-claimed-without-tag", m_set(["source", "tags"], [{"name": "v9.9.9-test", "object": OTHER, "signer_primary_fingerprint": "31DA39AB43E0CA67F1F3A661BA2AFF22DF8A4A13"}], "-release$"), True),
    # source and recipe consistency
    ("own-commits-changed", m_set(["source", "own_commits"], lambda v: v[1:], "source.own_commits"), True),
    ("submodule-changed", m_set(["source", "submodules", "external/randomx"], OTHER, "source.submodules"), True),
    ("commit-time-changed", m_set(["source", "commit_time"], lambda v: v + 1, "source.commit_time"), True),
    ("recipe-hash-changed", m_set(["build", "recipe", "files", "Dockerfile"], "0" * 64, "build.recipe.files"), True),
    ("recipe-combined-changed", m_set(["build", "recipe", "sha256"], "0" * 64, "build.recipe.sha256"), True),
    ("source-date-epoch-changed", m_set(["builder", "source_date_epoch"], lambda v: v - 1, "builder.source_date_epoch"), True),
    ("base-image-changed", m_set(["builder", "base_image"], "docker.io/library/debian@sha256:" + "0" * 64, "builder.base_image"), True),
    ("cmake-options-changed", m_set(["build", "cmake_options"], lambda v: v[:1], "build.cmake_options"), True),
    ("source-identity-changed", identity_changed, True),
    ("package-record-changed", file_append("build-logs/builder-packages.tsv", "extra\t1.0\tamd64\n", "builder.package_inventory_sha256"), True),
    ("toolchain-record-changed", file_replace("build-logs/toolchain.txt", "JOBS=4", "JOBS=3", "builder.toolchain"), True),
    ("steps-record-changed", file_replace("build-logs/steps.txt", "container exit 0", "container exit 1", "build.steps"), True),
    ("artifact-elf-report-changed", file_replace("elf-report.txt", "elf_rpath_runpath=none", "elf_rpath_runpath=(RUNPATH) /src/lib", "artifact elf-report.txt elf_rpath_runpath"), True),
    ("version-file-missing", file_remove("version.txt", "version.txt present"), True),
    # checksum file and layout
    ("binary-changed-unsealed", binary_changed, False),
    ("sums-missing-source-identity", sums_edit(sums_drop_identity), False),
    ("sums-duplicate-entry", sums_edit(sums_duplicate), False),
    ("sums-malformed-line", sums_edit(sums_malformed), False),
    ("sums-uppercase-hash", sums_edit(sums_upper), False),
    ("sums-path-escape", sums_edit(sums_escape), False),
    ("sums-absolute-path", sums_edit(sums_absolute), False),
    ("sums-extra-entry", sums_edit(sums_extra), False),
    ("sums-no-final-newline", sums_edit(sums_no_newline), False),
    ("symlink-binary", symlink_binary, True),
    ("symlink-log", symlink_log, True),
    # trusted inputs differ from an unchanged artifact
    ("trusted-run-attempt-2", trusted("run-attempt", "2", "workflow.run_attempt"), False),
    ("trusted-other-repository", trusted("repository", "someone/myzephyr", "workflow.repository"), False),
    ("trusted-elf-report-failed", trusted_elf_failed, False),
    ("trusted-recipe-changed", trusted_recipe_changed, False),
    ("trusted-tag-at-head", trusted_tag_at_head, False),
]


def verify(d, t, report):
    args = [sys.executable, "-I", verifier, "--artifact", d, "--report", report]
    for k, v in t.items():
        args += [f"--{k}", v]
    r = subprocess.run(args, capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr


def fixture_base(work):
    """The fixture artifact with placeholder bytes; returns (artifact dir, trusted options)."""
    with open(os.path.join(fixture, "context.json")) as f:
        ctx = json.load(f)
    ctx.pop("about")
    base = os.path.join(work, "base")
    copy_artifact(fixture, base)
    for n in ("SHA256SUMS", "context.json"):
        os.remove(os.path.join(base, n))
    # toolchain.txt is not stored (its CI record has a trailing space); it is the manifest's
    # toolchain list, one line each, which is byte-identical to the run's record
    write(os.path.join(base, "build-logs", "toolchain.txt"), "\n".join(load(base)["builder"]["toolchain"]) + "\n")
    z = os.path.join(base, "zephyrd")
    write(z, "Placeholder for the zephyrd binary of the fixture. Not a program; never executed.\n")
    size, digest = os.path.getsize(z), sha256(z)
    m = load(base)
    m["artifact"]["size"], m["artifact"]["sha256"] = size, digest
    # the recipe in this checkout is the trusted one; follow it if it changed after the fixture run
    recipe = os.path.join(tooling, "linux")
    files = {n: sha256(os.path.join(recipe, n)) for n in ("Dockerfile", "run-builder.sh", "build-in-container.sh")}
    if files != m["build"]["recipe"]["files"]:
        print("note: recipe changed since the fixture run; the fixture's recipe record follows this checkout")
        m["build"]["recipe"] = {"files": files, "sha256": hashlib.sha256(
            "".join(f"{files[n]}  {n}\n" for n in sorted(files)).encode()).hexdigest()}
    save(base, m)
    elf = os.path.join(base, "elf-report.txt")
    kv_set(elf, "elf_size", str(size))
    kv_set(elf, "elf_sha256", digest)
    reseal(base)
    trusted_dir = os.path.join(work, "base-trusted")
    os.makedirs(trusted_dir)
    shutil.copyfile(elf, os.path.join(trusted_dir, "elf-report.txt"))
    shutil.copyfile(os.path.join(base, "source-identity.txt"), os.path.join(trusted_dir, "source-identity.txt"))
    ctx.update({"source-identity": os.path.join(trusted_dir, "source-identity.txt"),
                "elf-report": os.path.join(trusted_dir, "elf-report.txt"), "recipe-dir": recipe})
    return base, ctx


def tagged_variant(work, base, t):
    """A valid manifest for a commit with a signed tag at it (synthetic tag object, no real tag)."""
    d = os.path.join(work, "tagged")
    copy_artifact(base, d)
    tt = dict(t)
    tdir = d + "-trusted"
    os.makedirs(tdir)
    lines = read(t["source-identity"]).splitlines()
    lines.insert(2, f"source_tag v2.3.0-sec.2-my.0-fixture={OTHER} {t['maintainer-fingerprint']}")
    write(os.path.join(tdir, "source-identity.txt"), "\n".join(lines) + "\n")
    shutil.copyfile(os.path.join(tdir, "source-identity.txt"), os.path.join(d, "source-identity.txt"))
    version = t["expected-version"].rsplit("-", 1)[0] + "-release"
    m = load(d)
    m["source"]["tags"] = [{"name": "v2.3.0-sec.2-my.0-fixture", "object": OTHER,
                            "signer_primary_fingerprint": t["maintainer-fingerprint"]}]
    m["artifact"]["expected_version"] = version
    m["artifact"]["version_output"] = m["artifact"]["version_output"].replace(t["expected-version"], version)
    save(d, m)
    write(os.path.join(d, "expected-version.txt"), version + "\n")
    write(os.path.join(d, "version.txt"), m["artifact"]["version_output"] + "\n")
    reseal(d)
    tt.update({"source-identity": os.path.join(tdir, "source-identity.txt"), "expected-version": version})
    return d, tt


def main():
    argv = sys.argv[1:]
    if not argv:
        sys.exit(__doc__)
    work = os.path.abspath(argv[0])
    if os.path.lexists(work):
        sys.exit(f"{work} exists")
    real = None
    if len(argv) > 1:
        if argv[1] != "--artifact" or len(argv) < 4 or argv[3] != "--":
            sys.exit(__doc__)
        real, rest = os.path.abspath(argv[2]), argv[4:]
        if len(rest) % 2 or not all(k.startswith("--") for k in rest[::2]):
            sys.exit("trusted options must be --name value pairs")
        t0 = {k[2:]: v for k, v in zip(rest[::2], rest[1::2])}
        if "artifact" in t0 or "report" in t0:
            sys.exit("pass the trusted options without --artifact and --report")
    os.makedirs(work)
    if real:
        base = os.path.join(work, "base")
        copy_artifact(real, base)
    else:
        base, t0 = fixture_base(work)

    results, ok = [], True

    def record(name, want, rc, out, frag):
        nonlocal ok
        good = rc == want and (frag is None or frag in out)
        ok &= good
        results.append({"case": name, "expected_exit": want, "exit": rc, "fragment": frag, "ok": good})
        print(f"{'PASS' if good else 'FAIL'} {name}: exit {rc}" + ("" if good else f", expected {want} with {frag!r}"))
        if not good:
            print("    " + out.strip().replace("\n", "\n    "))

    rc, out = verify(base, dict(t0), os.path.join(work, "base.json"))
    record("valid" if real else "valid-fixture", 0, rc, out, "checks passed")
    if not real:
        d, tt = tagged_variant(work, base, t0)
        rc, out = verify(d, tt, os.path.join(work, "tagged.json"))
        record("valid-tagged-fixture", 0, rc, out, "checks passed")
    if ok:
        for name, mutate, seal in NEGATIVE:
            d = os.path.join(work, name)
            copy_artifact(base, d)
            os.makedirs(d + "-trusted")
            t = dict(t0)
            frag = mutate(d, t)
            if seal:
                reseal(d)
            rc, out = verify(d, t, os.path.join(work, name + ".json"))
            record(name, 1, rc, out, frag)
    else:
        print("the valid artifact is rejected; the single-variable cases are not meaningful and were not run")
    with open(os.path.join(work, "results.json"), "w") as f:
        json.dump({"mode": "real" if real else "fixture", "cases": results}, f, indent=2)
        f.write("\n")
    bad = sum(not r["ok"] for r in results)
    print(f"artifact verifier self-test: {len(results) - bad} of {len(results)} cases as intended")
    sys.exit(0 if ok and not bad else 1)


if __name__ == "__main__":
    main()
