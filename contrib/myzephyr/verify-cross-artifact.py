#!/usr/bin/env python3
"""Verify a downloaded cross-built zephyrd artifact against trusted, independently obtained facts.

  verify-cross-artifact.py --target T --artifact DIR --expected-commit SHA --expected-version V
      --repository OWNER/NAME --ref REF --workflow-ref REF --run-id N --run-attempt N
      --event-name E --github-sha SHA --pull-request none|JSON
      [--server-url URL] [--producer-job ID]
      --base-repository URL --base-tag NAME --base-tag-object SHA --base-commit SHA
      --base-fingerprint FPR --maintainer-fingerprint FPR
      --source-identity FILE --static-report FILE --embedded-report FILE --recipe-dir DIR [--report FILE]

T: aarch64-linux-gnu, x86_64-apple-darwin or x86_64-w64-mingw32. The same rule as
verify-artifact.py: every value after --artifact comes from the verifier. --static-report is
the verifier's own check-elf.sh --arch aarch64 / check-macho.py / check-pe.py report of the
downloaded binary, --embedded-report its own check-embedded.py report, --recipe-dir
contrib/myzephyr/cross of its own checkout. The workflow, source and base checks are
verify-artifact.py's own code (imported), including the run-identity table and the
refusal of "release" versions. Target-specific checks:
  files     SHA256SUMS lists exactly the binary (zephyrd or zephyrd.exe), manifest.json,
            expected-version.txt and source-identity.txt; static-report.txt,
            embedded-report.txt and the build-logs records are present;
  schema    manifest-cross.schema.json (myzephyr/daemon-cross-build-manifest/2);
  version   expected version as in verify-artifact.py; the binary embeds exactly it;
  binary    name, target and format of T, actual size and hash;
  static    the verifier's report passed and describes this binary; the manifest and the
            artifact's static-report.txt equal it (except elf_file: file(1) wording depends
            on the host); the fixed values of T hold in it;
  embedded  the verifier's embedded report passed; the artifact's report and the manifest equal it;
  build     recipe, base image, snapshot, builder target and build-logs records as in
            verify-artifact.py, for the cross builder;
  checks    every manifest consistency check is exactly true.
A checksum is not a signature. Exit 1 if any check fails, 2 on a usage error.
"""
import argparse
import hashlib
import importlib.util
import json
import os
import re
import sys

here = os.path.dirname(os.path.abspath(__file__))
# no __pycache__ in the checkout: verify-source.sh counts ignored files as unclean
sys.dont_write_bytecode = True
spec = importlib.util.spec_from_file_location("verify_artifact", os.path.join(here, "verify-artifact.py"))
va = importlib.util.module_from_spec(spec)
spec.loader.exec_module(va)

TARGETS = {"aarch64-linux-gnu": ("elf", "zephyrd"), "x86_64-apple-darwin": ("macho", "zephyrd"),
           "x86_64-w64-mingw32": ("pe", "zephyrd.exe")}
SEEDS = ["142.93.255.216:17766", "142.93.98.116:17766", "24.199.101.125:17766", "85.215.93.176:17766"]
# fixed values each target's own static report must show (the checkers fail otherwise too)
FIXED = {
    "elf": {"elf_interpreter": "/lib/ld-linux-aarch64.so.1", "elf_rpath_runpath": "none",
            "elf_needed": "ld-linux-aarch64.so.1 libc.so.6 libm.so.6 libpthread.so.0",
            "elf_max_glibc_allowed": "GLIBC_2.29", "elf_cxx_version_needs": "none"},
    "macho": {"macho_cputype": "0x1000007", "macho_filetype": "2", "macho_rpath": "none",
              "macho_dylinker": "/usr/lib/dyld"},
    "pe": {"pe_magic": "0x20b", "pe_machine": "0x8664", "pe_subsystem": "3"},
}
REPORT_KEYS = {"elf": ("elf_sha256", "elf_size", "elf_checks"), "macho": ("macho_sha256", "macho_size", "macho_checks"),
               "pe": ("pe_sha256", "pe_size", "pe_checks")}
# report values whose wording depends on the host's tools; Mach-O and PE reports come from
# pure-Python readers and have none
HOST_DEPENDENT = {"elf": {"elf_file"}, "macho": set(), "pe": set()}


class CrossVerifier(va.Verifier):
    SCHEMA_FILE = "manifest-cross.schema.json"
    SCHEMA_ID = "myzephyr/daemon-cross-build-manifest/2"

    def __init__(self, a):
        super().__init__(a)
        self.fmt, self.name = TARGETS[a.target]
        self.SUMMED = (self.name, "manifest.json", "expected-version.txt", "source-identity.txt")
        self.REQUIRED_FILES = ("static-report.txt", "embedded-report.txt") + va.REQUIRED_FILES[2:]

    def semantics(self):
        a, m, d = self.a, self.m, self.d
        commit = a.expected_commit
        prov = self.provenance()
        if prov is None:
            return
        flat, groups = prov
        art = m["artifact"]
        self.version_checks(art)

        bp = os.path.join(d, self.name)
        size, digest = os.path.getsize(bp), va.sha256_file(bp)
        self.eq("binary", "artifact.name", art["name"], self.name)
        self.eq("binary", "artifact.target", art["target"], a.target)
        self.eq("binary", "artifact.format", art["format"], self.fmt)
        self.eq("binary", "artifact.size", art["size"], size)
        self.eq("binary", "artifact.sha256", art["sha256"], digest)

        sha_key, size_key, checks_key = REPORT_KEYS[self.fmt]
        mine = va.report_kv(va.read_text(a.static_report))
        theirs = va.report_kv(va.read_text(os.path.join(d, "static-report.txt")))
        self.eq("static", f"trusted report {sha_key}", mine.get(sha_key), digest)
        self.eq("static", f"trusted report {size_key}", mine.get(size_key), str(size))
        self.eq("static", f"trusted report {checks_key}", mine.get(checks_key), "passed")
        for key, want in FIXED[self.fmt].items():
            self.eq("static", f"trusted report {key} (fixed for {a.target})", mine.get(key), want)
        sr = m["static_report"]
        self.eq("static", "static_report.format", sr["format"], self.fmt)
        self.eq("static", "static_report.checks", sr["checks"], "passed")
        for key in sorted(set(mine) | set(theirs) | set(sr["values"])):
            if key in HOST_DEPENDENT[self.fmt]:
                continue
            self.eq("static", f"artifact static-report.txt {key} (trusted report)", theirs.get(key), mine.get(key))
            self.eq("static", f"static_report.values.{key} (trusted report)", sr["values"].get(key), mine.get(key))

        emine = va.report_kv(va.read_text(a.embedded_report))
        etheirs = va.report_kv(va.read_text(os.path.join(d, "embedded-report.txt")))
        self.eq("embedded", "trusted embedded report embedded_sha256", emine.get("embedded_sha256"), digest)
        self.eq("embedded", "trusted embedded report embedded_checks", emine.get("embedded_checks"), "passed")
        self.eq("embedded", "trusted embedded versions", emine.get("embedded_versions", "").split(), [a.expected_version])
        self.eq("embedded", "trusted embedded seeds", emine.get("embedded_seeds", "").split(), SEEDS)
        self.eq("embedded", "artifact embedded-report.txt (trusted report)", etheirs, emine)
        em = m["embedded"]
        self.eq("embedded", "embedded.versions", em["versions"], [a.expected_version])
        self.eq("embedded", "embedded.seeds", em["seeds"], SEEDS)
        self.eq("embedded", "embedded.checks", em["checks"], "passed")

        b, bl = m["build"], m["builder"]
        files = {n: va.sha256_file(os.path.join(a.recipe_dir, n)) for n in va.RECIPE_FILES}
        combined = hashlib.sha256("".join(f"{files[n]}  {n}\n" for n in sorted(files)).encode()).hexdigest()
        self.eq("build", "build.recipe.files (verifier's recipe)", b["recipe"]["files"], files)
        self.eq("build", "build.recipe.sha256 (verifier's recipe)", b["recipe"]["sha256"], combined)
        self.eq("build", "build.cmake_target", b["cmake_target"], "daemon")
        self.eq("build", "build.cmake_options", b["cmake_options"],
                [f"-DCMAKE_TOOLCHAIN_FILE=<src>/contrib/depends/{a.target}/share/toolchain.cmake", "-DCMAKE_SKIP_RPATH=ON"])
        self.eq("build", "builder.target", bl["target"], a.target)
        dockerfile = va.read_text(os.path.join(a.recipe_dir, "Dockerfile"))
        frm = re.search(r"^FROM\s+(\S+)", dockerfile, re.M)
        snap = re.search(r"^ARG SNAPSHOT=(\S+)$", dockerfile, re.M)
        self.eq("build", "builder.base_image (verifier's Dockerfile)", bl["base_image"], frm.group(1) if frm else None)
        self.eq("build", "builder.apt_snapshot (verifier's Dockerfile)", bl["apt_snapshot"], snap.group(1) if snap else None)
        self.eq("build", "builder.source_date_epoch (trusted identity)", bl["source_date_epoch"], int(flat["source_commit_time"]))
        logs = os.path.join(d, "build-logs")
        pk = os.path.join(logs, "builder-packages.tsv")
        self.eq("build", "builder.package_inventory_sha256", bl["package_inventory_sha256"], va.sha256_file(pk))
        self.eq("build", "builder.package_count", bl["package_count"],
                sum(1 for line in va.read_text(pk).split("\n") if line.strip()))
        self.eq("build", "builder.apt_state", bl["apt_state"], va.read_text(os.path.join(logs, "builder-apt-state.txt")).splitlines())
        image = va.read_text(os.path.join(logs, "image.txt")).split()
        self.eq("build", "builder.image_id", bl["image_id"], image[0] if image else None)
        toolchain = va.read_text(os.path.join(logs, "toolchain.txt")).splitlines()
        self.eq("build", "builder.toolchain", bl["toolchain"], toolchain)
        self.check("build", f"target={a.target}" in toolchain and f"HEAD {commit}" in toolchain,
                   f"toolchain record names target={a.target} and the expected HEAD")
        self.link_inventory_check(b, logs)
        steps = va.read_text(os.path.join(logs, "steps.txt")).splitlines()
        self.eq("build", "build.steps", b["steps"], steps)
        self.check("build", f"BUILD {a.target} ok" in steps and "container exit 0" in steps,
                   "build steps record a completed build of the target")

        for key, value in m["checks"].items():
            self.check("checks", value is True, f"checks.{key} is {json.dumps(value)}")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    for name in ("target", "artifact", "expected-commit", "expected-version", "repository", "ref", "workflow-ref",
                 "run-id", "run-attempt", "event-name", "github-sha", "pull-request",
                 "base-repository", "base-tag", "base-tag-object", "base-commit",
                 "base-fingerprint", "maintainer-fingerprint", "source-identity", "static-report",
                 "embedded-report", "recipe-dir"):
        p.add_argument(f"--{name}", required=True)
    p.add_argument("--server-url", default="https://github.com")
    p.add_argument("--producer-job", default="cross-build")
    p.add_argument("--report")
    a = p.parse_args()
    try:
        if a.target not in TARGETS:
            raise va.Usage(f"--target must be one of {sorted(TARGETS)}")
        v = CrossVerifier(a)
        va.check_common_options(a)
        for f in (a.source_identity, a.static_report, a.embedded_report):
            if not os.path.isfile(f):
                raise va.Usage(f"{f} is not a file")
        for n in va.RECIPE_FILES:
            if not os.path.isfile(os.path.join(a.recipe_dir, n)):
                raise va.Usage(f"--recipe-dir has no {n}")
        ok = v.run()
    except va.Usage as e:
        print(f"verify-cross-artifact: usage: {e}", file=sys.stderr)
        sys.exit(2)
    except (OSError, UnicodeDecodeError, KeyError, TypeError, ValueError, AttributeError, IndexError) as e:
        v.check("internal", False, f"cannot complete the checks: {type(e).__name__}: {e}")
        ok = False
    if a.report:
        with open(a.report, "w") as f:
            json.dump({"verdict": "passed" if ok else "failed", "target": a.target, "artifact": a.artifact,
                       "expected_commit": a.expected_commit, "run_id": a.run_id, "run_attempt": a.run_attempt,
                       "results": [{"area": ar, "ok": o, "check": msg} for ar, o, msg in v.results]}, f, indent=2)
            f.write("\n")
    if not ok:
        for area, good, msg in v.results:
            if not good:
                print(f"verify-cross-artifact: FAILED [{area}] {msg}", file=sys.stderr)
        print(f"verify-cross-artifact: {len(v.failed())} of {len(v.results)} checks failed", file=sys.stderr)
        sys.exit(1)
    print(f"verify-cross-artifact: all {len(v.results)} checks passed", file=sys.stderr)
    print(a.expected_version)


if __name__ == "__main__":
    main()
