#!/usr/bin/env python3
"""Verify a downloaded zephyrd release artifact against trusted, independently obtained facts.

  verify-artifact.py --artifact DIR --expected-commit SHA --expected-version V
      --repository OWNER/NAME --ref REF --workflow-ref REF --run-id N --run-attempt N
      --event-name E --github-sha SHA --pull-request none|JSON
      [--server-url URL] [--producer-job ID]
      --base-repository URL --base-tag NAME --base-tag-object SHA --base-commit SHA
      --base-fingerprint FPR --maintainer-fingerprint FPR
      --source-identity FILE --elf-report FILE --recipe-dir DIR [--report FILE]

Every value after --artifact comes from the verifier, never from the artifact: the CI
context of the consuming job (GITHUB_REPOSITORY, GITHUB_REF, GITHUB_WORKFLOW_REF,
GITHUB_RUN_ID, GITHUB_RUN_ATTEMPT, GITHUB_EVENT_NAME, GITHUB_SHA and MYZ_PULL_REQUEST, which
run-identity.py read from that job's own event payload; --expected-commit is the built
commit, MYZ_BUILD_SHA), the pinned base policy of the workflow, and files the verifier made
itself from its own checkout and the downloaded binary:
  --source-identity  output of verify-source.sh (signatures, base, own commits, tags,
                     submodules) run on the verifier's checkout of the expected commit;
  --elf-report       output of check-elf.sh run by the verifier on the downloaded zephyrd;
  --recipe-dir       contrib/myzephyr/linux of that checkout;
  --expected-version zephyrd-check.py expected-version of that checkout.
This script does not verify signatures and does not inspect the ELF file; those stay
separate steps with their own tools. It checks that the artifact's files and its
manifest agree with them, so a checksum file or a manifest written by someone else
cannot pass on its own. A checksum is not a signature.

Checks (each failure is reported; exit 1 if any fails, 2 on a usage error):
  files     the artifact directory and everything below it are regular files and
            directories, no symlinks; SHA256SUMS has one well-formed line per file,
            plain file names only, no duplicates, exactly zephyrd, manifest.json,
            expected-version.txt and source-identity.txt, and every hash matches;
  schema    manifest.json is strict JSON (no duplicate keys, no NaN) and valid against
            manifest.schema.json next to this script (schema id
            myzephyr/daemon-build-manifest/2); unknown schema keywords are an error;
  workflow  the trusted run identity is a row of run-identity.py's table (push to
            ci/daemon-release-baseline or my/<name>, or a pull request into my/<name>
            built at its head commit); anything else fails. The manifest is from a GitHub
            Actions run (a local_build manifest is not CI provenance): repository, ref,
            workflow_ref, run_id, run_attempt, server_url, event_name, the pull request
            fields and the producing job equal the trusted values; sha and workflow_sha
            equal the trusted GITHUB_SHA (for a pull request the test merge commit, which
            is never built);
  source    the commit (the built commit), commit time, own commits with their paths and
            submodule pins equal the trusted source identity; no tag at the commit
            ("tags_at_head": "none") and none in the checkout, as the trusted identity
            says; source-identity.txt in the artifact is byte-identical to it;
  base      repository, tag, tag object, commit and signer equal the pinned policy and
            the trusted identity (including the signing subkey found by verify-source);
  version   expected-version.txt, the manifest and the trusted expected version agree;
            it is <number>-<first 9 hex digits of the commit>; "release" is refused;
            version.txt and the manifest's version output agree and end with it;
  binary    name zephyrd, target x86_64-unknown-linux-gnu, actual size and hash;
  elf       manifest runtime requirements and the artifact's elf-report.txt equal the
            verifier's own report; elf_checks passed, the pinned interpreter, only the
            permitted libraries, no RPATH/RUNPATH, no C++ runtime needs, GLIBC at most
            2.29;
  build     recipe file hashes equal the verifier's recipe directory; base image and
            apt snapshot equal its Dockerfile; build-logs records (packages, apt
            state, image, toolchain, steps) equal the manifest; release target only;
  checks    every manifest consistency check is exactly true.
On success the expected version is printed. --report writes all results as JSON.
"""
import argparse
import hashlib
import importlib.util
import json
import os
import re
import stat
import sys

sys.dont_write_bytecode = True
_spec = importlib.util.spec_from_file_location(
    "run_identity", os.path.join(os.path.dirname(os.path.abspath(__file__)), "run-identity.py"))
ri = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ri)

SCHEMA_ID = "myzephyr/daemon-build-manifest/3"
SUMMED = ("zephyrd", "manifest.json", "expected-version.txt", "source-identity.txt")
REQUIRED_FILES = ("version.txt", "elf-report.txt", "build-logs/builder-packages.tsv",
                  "build-logs/builder-apt-state.txt", "build-logs/image.txt",
                  "build-logs/toolchain.txt", "build-logs/steps.txt")
SAFE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
TARGET = "x86_64-unknown-linux-gnu"
INTERPRETER = "/lib64/ld-linux-x86-64.so.2"
ALLOWED_NEEDED = {"libc.so.6", "libm.so.6", "libpthread.so.0", "ld-linux-x86-64.so.2"}
MAX_GLIBC = "GLIBC_2.29"
RECIPE_FILES = ("Dockerfile", "run-builder.sh", "build-in-container.sh")
CMAKE_OPTIONS = ["-DCMAKE_TOOLCHAIN_FILE=<src>/contrib/depends/x86_64-unknown-linux-gnu/share/toolchain.cmake",
                 "-DCMAKE_SKIP_RPATH=ON"]
ELF_FIELDS = {"interpreter": "elf_interpreter", "rpath_runpath": "elf_rpath_runpath",
              "max_glibc": "elf_max_glibc", "max_glibc_allowed": "elf_max_glibc_allowed",
              "cxx_version_needs": "elf_cxx_version_needs", "elf_checks": "elf_checks",
              "build_id": "elf_build_id"}
SHA1 = re.compile(r"[0-9a-f]{40}")
FPR = re.compile(r"[0-9A-F]{40}")
EXPECTED_VERSION = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+-[0-9a-f]{9}")


class Usage(Exception):
    pass


# ---------------------------------------------------------------- strict JSON and schema

def strict_json(data):
    def pairs(items):
        out = {}
        for k, v in items:
            if k in out:
                raise ValueError(f"duplicate key {k!r}")
            out[k] = v
        return out

    def no_constant(name):
        raise ValueError(f"non-standard number {name}")
    return json.loads(data, object_pairs_hook=pairs, parse_constant=no_constant)


SCHEMA_KEYWORDS = {"$schema", "$id", "title", "description", "$defs", "type", "required",
                   "properties", "additionalProperties", "const", "enum", "pattern", "minimum",
                   "minLength", "minItems", "maxItems", "minProperties", "items", "$ref",
                   "oneOf", "allOf", "if", "then", "else"}


def json_type(v):
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "boolean"
    if isinstance(v, int):
        return "integer"
    if isinstance(v, float):
        return "number"
    if isinstance(v, str):
        return "string"
    if isinstance(v, list):
        return "array"
    return "object"


def same(a, b):
    """JSON equality: true is not 1, 1 is not "1"."""
    if json_type(a) != json_type(b):
        return False
    if isinstance(a, list):
        return len(a) == len(b) and all(same(x, y) for x, y in zip(a, b))
    if isinstance(a, dict):
        return a.keys() == b.keys() and all(same(a[k], b[k]) for k in a)
    return a == b


def ecma(pattern):
    # ECMA-262 "$" without the multiline flag matches only at the end; Python's also
    # before a final newline. Patterns here use "$" only as their last character.
    return pattern[:-1] + r"\Z" if pattern.endswith("$") and not pattern.endswith(r"\$") else pattern


def validate(inst, sch, root, path, errs):
    """The subset of JSON Schema 2020-12 that manifest.schema.json uses; anything else is an error."""
    if isinstance(sch, bool):
        if not sch:
            errs.append(f"{path}: not allowed")
        return
    unknown = set(sch) - SCHEMA_KEYWORDS
    if unknown:
        raise Usage(f"schema keyword(s) not supported by this verifier: {sorted(unknown)}")
    if "$ref" in sch:
        ref = sch["$ref"]
        if not ref.startswith("#/$defs/"):
            raise Usage(f"unsupported $ref {ref}")
        validate(inst, root["$defs"][ref[len("#/$defs/"):]], root, path, errs)
    t = json_type(inst)
    if "type" in sch:
        allowed = sch["type"] if isinstance(sch["type"], list) else [sch["type"]]
        if t not in allowed:
            errs.append(f"{path}: type {t}, expected {'/'.join(allowed)}")
            return
    if "const" in sch and not same(inst, sch["const"]):
        errs.append(f"{path}: {json.dumps(inst)[:80]} is not {json.dumps(sch['const'])}")
    if "enum" in sch and not any(same(inst, e) for e in sch["enum"]):
        errs.append(f"{path}: {json.dumps(inst)[:80]} not in {json.dumps(sch['enum'])}")
    if t == "string":
        if "pattern" in sch and not re.search(ecma(sch["pattern"]), inst):
            errs.append(f"{path}: {inst[:80]!r} does not match {sch['pattern']}")
        if "minLength" in sch and len(inst) < sch["minLength"]:
            errs.append(f"{path}: shorter than {sch['minLength']}")
    if t in ("integer", "number") and "minimum" in sch and inst < sch["minimum"]:
        errs.append(f"{path}: {inst} below {sch['minimum']}")
    if t == "array":
        if "minItems" in sch and len(inst) < sch["minItems"]:
            errs.append(f"{path}: fewer than {sch['minItems']} items")
        if "maxItems" in sch and len(inst) > sch["maxItems"]:
            errs.append(f"{path}: more than {sch['maxItems']} items")
        if "items" in sch:
            for i, v in enumerate(inst):
                validate(v, sch["items"], root, f"{path}[{i}]", errs)
    if t == "object":
        for k in sch.get("required", []):
            if k not in inst:
                errs.append(f"{path}: missing {k}")
        if "minProperties" in sch and len(inst) < sch["minProperties"]:
            errs.append(f"{path}: fewer than {sch['minProperties']} properties")
        props = sch.get("properties", {})
        for k, v in inst.items():
            if k in props:
                validate(v, props[k], root, f"{path}.{k}", errs)
            elif "additionalProperties" in sch:
                validate(v, sch["additionalProperties"], root, f"{path}.{k}", errs)
    if "allOf" in sch:
        for s in sch["allOf"]:
            validate(inst, s, root, path, errs)
    if "oneOf" in sch:
        results = []
        for s in sch["oneOf"]:
            e = []
            validate(inst, s, root, path, e)
            results.append(e)
        ok = [e for e in results if not e]
        if len(ok) != 1:
            detail = "; ".join(x for e in results for x in e[:2])
            errs.append(f"{path}: matches {len(ok)} of the oneOf alternatives, expected 1 ({detail})")
    if "if" in sch:
        e = []
        validate(inst, sch["if"], root, path, e)
        branch = sch.get("then") if not e else sch.get("else")
        if branch is not None:
            validate(inst, branch, root, path, errs)


# ---------------------------------------------------------------- helpers

def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def read_text(path):
    with open(path, "rb") as f:
        return f.read().decode("utf-8")


def identity(text):
    """verify-source.sh output: key=value, grouped keys "<prefix> <name>=value" in file order."""
    flat, groups = {}, {}
    for n, line in enumerate(text.split("\n"), 1):
        if not line:
            continue
        if "=" not in line:
            raise ValueError(f"line {n} is not key=value")
        k, v = line.split("=", 1)
        if " " in k:
            prefix, name = k.split(" ", 1)
            g = groups.setdefault(prefix, {})
            if name in g:
                raise ValueError(f"duplicate {k}")
            g[name] = v
        else:
            if k in flat:
                raise ValueError(f"duplicate {k}")
            flat[k] = v
    for k in ("source_commit", "source_commit_time", "own_commit_count", "base_repository", "base_tag",
              "base_tag_object", "base_commit", "base_signer_primary", "base_signing_key", "maintainer_primary"):
        if k not in flat:
            raise ValueError(f"missing {k}")
    return flat, groups


def report_kv(text):
    out = {}
    for line in text.splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            out[k] = v
    return out


def glibc_key(v):
    m = re.fullmatch(r"GLIBC_([0-9]+(?:\.[0-9]+)*)", v or "")
    return tuple(int(x) for x in m.group(1).split(".")) if m else None


class Verifier:
    # what the artifact must contain; the cross-target verifier (verify-cross-artifact.py) overrides these
    SUMMED = SUMMED
    REQUIRED_FILES = REQUIRED_FILES
    SCHEMA_FILE = "manifest.schema.json"
    SCHEMA_ID = SCHEMA_ID

    def __init__(self, a):
        self.a = a
        self.results = []   # (area, ok, message)
        self.d = a.artifact

    def check(self, area, ok, message):
        self.results.append((area, bool(ok), message))
        return bool(ok)

    def eq(self, area, what, got, want):
        good = same(got, want)
        return self.check(area, good, f"{what}: {json.dumps(got)[:120]}"
                          + ("" if good else f", expected {json.dumps(want)[:120]}"))

    def failed(self):
        return [m for _, ok, m in self.results if not ok]

    def files(self):
        d = self.d
        try:
            st = os.lstat(d)
        except OSError as e:
            return self.check("files", False, f"artifact directory: {e}")
        if not self.check("files", stat.S_ISDIR(st.st_mode), f"artifact directory {d} is a real directory"):
            return False
        bad = []
        for top, dirs, names in os.walk(d, followlinks=False):
            for n in dirs + names:
                p = os.path.join(top, n)
                mode = os.lstat(p).st_mode
                if stat.S_ISLNK(mode) or not (stat.S_ISDIR(mode) or stat.S_ISREG(mode)):
                    bad.append(os.path.relpath(p, d))
        self.check("files", not bad, "no symlinks or special files" + (f": {sorted(bad)}" if bad else ""))
        for rel in self.REQUIRED_FILES:
            p = os.path.join(d, rel)
            self.check("files", os.path.isfile(p) and not os.path.islink(p), f"{rel} present")
        sums_path = os.path.join(d, "SHA256SUMS")
        if not self.check("files", os.path.isfile(sums_path) and not os.path.islink(sums_path), "SHA256SUMS present"):
            return False
        try:
            text = read_text(sums_path)
        except (OSError, UnicodeDecodeError) as e:
            return self.check("files", False, f"SHA256SUMS unreadable: {e}")
        sums, lines = {}, text.split("\n")
        if not self.check("files", text.endswith("\n"), "SHA256SUMS ends with a newline"):
            return False
        for line in lines[:-1]:
            m = re.fullmatch(r"([0-9a-f]{64}) ([ *])(.+)", line)
            if not self.check("files", m, f"SHA256SUMS line well-formed: {line[:100]!r}"):
                continue
            name = m.group(3)
            if not self.check("files", SAFE_NAME.fullmatch(name), f"SHA256SUMS entry {name!r} is a plain file name"):
                continue
            if not self.check("files", name not in sums, f"SHA256SUMS entry {name} listed once"):
                continue
            sums[name] = m.group(1)
        self.eq("files", "SHA256SUMS entries", sorted(sums), sorted(self.SUMMED))
        for name in self.SUMMED:
            p = os.path.join(d, name)
            if name in sums and self.check("files", os.path.isfile(p) and not os.path.islink(p), f"{name} is a regular file"):
                self.check("files", sha256_file(p) == sums[name], f"{name} matches SHA256SUMS")
        return not self.failed()

    def schema(self):
        here = os.path.dirname(os.path.abspath(__file__))
        sch = strict_json(read_text(os.path.join(here, self.SCHEMA_FILE)))
        if sch.get("$id") != self.SCHEMA_ID:
            raise Usage(f"{self.SCHEMA_FILE} next to this script is {sch.get('$id')}, expected {self.SCHEMA_ID}")
        try:
            self.m = strict_json(read_text(os.path.join(self.d, "manifest.json")))
        except (ValueError, UnicodeDecodeError) as e:
            return self.check("schema", False, f"manifest.json is not strict JSON: {e}")
        errs = []
        validate(self.m, sch, sch, "manifest", errs)
        for e in errs:
            self.check("schema", False, e)
        return self.check("schema", not errs, f"manifest valid against {self.SCHEMA_ID}")

    def provenance(self):
        """workflow, source and base checks, shared by every target. Returns (flat, groups)
        of the trusted source identity, or None when the manifest is not CI provenance."""
        a, m, d = self.a, self.m, self.d
        commit = a.expected_commit
        trusted_ctx = {"event_name": a.event_name, "ref": a.ref, "sha": a.github_sha, "workflow_sha": a.github_sha,
                       "workflow_ref": a.workflow_ref, "repository": a.repository, "built_commit": commit,
                       "pull_request": a.pull_request_obj}
        ctx_errs = ri.errors(trusted_ctx)
        for e in ctx_errs:
            self.check("workflow", False, f"trusted run identity not in the table: {e}")
        self.check("workflow", not ctx_errs, f"trusted run identity is a row of the table ({a.event_name} on {a.ref})")
        wf = m["workflow"]
        if not self.check("workflow", "local_build" not in wf,
                          "manifest is from a CI run (local_build is not public CI provenance)"):
            return None
        for key, want in (("repository", a.repository), ("ref", a.ref), ("workflow_ref", a.workflow_ref),
                          ("run_id", a.run_id), ("run_attempt", a.run_attempt), ("server_url", a.server_url),
                          ("job", a.producer_job), ("event_name", a.event_name), ("sha", a.github_sha),
                          ("workflow_sha", a.github_sha), ("pull_request", a.pull_request_obj)):
            self.eq("workflow", f"workflow.{key}", wf[key], want)
        self.check("workflow", not ri.errors(dict(wf, built_commit=m["source"]["commit"])),
                   "manifest run identity with its source commit is a row of the table")

        trusted_text = read_text(a.source_identity)
        try:
            flat, groups = identity(trusted_text)
        except ValueError as e:
            raise Usage(f"--source-identity: {e}")
        if flat["source_commit"] != commit:
            raise Usage(f"--source-identity is for {flat['source_commit']}, not the expected commit {commit}")
        self.check("source", read_text(os.path.join(d, "source-identity.txt")) == trusted_text,
                   "source-identity.txt in the artifact is identical to the trusted source identity")
        src = m["source"]
        self.eq("source", "source.commit", src["commit"], commit)
        self.eq("source", "source.commit_time", src["commit_time"], int(flat["source_commit_time"]))
        self.eq("source", "trusted identity tags_at_head", flat.get("tags_at_head"), "none")
        self.eq("source", "source.tags_at_head (trusted identity)", src["tags_at_head"], flat.get("tags_at_head"))
        self.eq("source", "trusted identity tags_in_checkout", flat.get("tags_in_checkout"), "0")
        self.eq("source", "source.tags_in_checkout (trusted identity)", src["tags_in_checkout"],
                int(flat["tags_in_checkout"]) if flat.get("tags_in_checkout", "").isdigit() else None)
        self.check("source", "release_tag" not in groups, "trusted identity is a build checkout (no release tag)")
        own = [{"commit": c, "paths": p.split()} for c, p in groups.get("own_commit", {}).items()]
        self.check("source", len(own) == int(flat["own_commit_count"]), "trusted own_commit lines match own_commit_count")
        self.eq("source", "source.own_commits", src["own_commits"], own)
        self.eq("source", "source.submodules", src["submodules"], groups.get("submodule", {}))

        base = m["base"]
        for key, pinned, idkey in (("repository", a.base_repository, "base_repository"), ("tag", a.base_tag, "base_tag"),
                                   ("tag_object", a.base_tag_object, "base_tag_object"), ("commit", a.base_commit, "base_commit"),
                                   ("signer_primary_fingerprint", a.base_fingerprint, "base_signer_primary")):
            self.eq("base", f"base.{key} (pinned)", base[key], pinned)
            self.eq("base", f"trusted identity {idkey} (pinned)", flat[idkey], pinned)
        self.eq("base", "base.signing_key (trusted identity)", base["signing_key"], flat["base_signing_key"])
        self.eq("base", "own_commit_signer_primary_fingerprint (pinned)", m["own_commit_signer_primary_fingerprint"],
                a.maintainer_fingerprint)
        self.eq("base", "trusted identity maintainer_primary (pinned)", flat["maintainer_primary"], a.maintainer_fingerprint)
        return flat, groups

    def version_checks(self, art):
        a, d, commit = self.a, self.d, self.a.expected_commit
        ev_text = read_text(os.path.join(d, "expected-version.txt"))
        self.check("version", re.fullmatch(r"\S+\n?", ev_text), "expected-version.txt holds one value")
        self.eq("version", "expected-version.txt", ev_text.strip(), a.expected_version)
        self.eq("version", "artifact.expected_version", art["expected_version"], a.expected_version)
        self.check("version", EXPECTED_VERSION.fullmatch(a.expected_version) and a.expected_version.endswith("-" + commit[:9]),
                   f"expected version {a.expected_version} is <number>-{commit[:9]} (never release)")

    def link_inventory_check(self, b, logs):
        p = os.path.join(logs, "link-inventory.tsv")
        have = sha256_file(p) if os.path.isfile(p) and not os.path.islink(p) else None
        self.eq("build", "build.link_inventory_sha256 (build-logs/link-inventory.tsv)", b["link_inventory_sha256"], have)

    def semantics(self):
        a, m, d = self.a, self.m, self.d
        commit = a.expected_commit
        prov = self.provenance()
        if prov is None:
            return
        flat, groups = prov

        art = m["artifact"]
        self.version_checks(art)
        vo = art["version_output"]
        self.check("version", "\n" not in vo and vo.startswith("Zephyr '") and vo.endswith(f"(v{a.expected_version})"),
                   f"artifact.version_output {vo!r} reports v{a.expected_version}")
        self.eq("version", "version.txt", read_text(os.path.join(d, "version.txt")).rstrip("\n"), vo)

        zp = os.path.join(d, "zephyrd")
        size, digest = os.path.getsize(zp), sha256_file(zp)
        self.eq("binary", "artifact.name", art["name"], "zephyrd")
        self.eq("binary", "artifact.target", art["target"], TARGET)
        self.eq("binary", "artifact.size", art["size"], size)
        self.eq("binary", "artifact.sha256", art["sha256"], digest)

        rr = m["runtime_requirements"]
        mine = report_kv(read_text(a.elf_report))
        theirs = report_kv(read_text(os.path.join(d, "elf-report.txt")))
        self.eq("elf", "trusted ELF report elf_sha256", mine.get("elf_sha256"), digest)
        self.eq("elf", "trusted ELF report elf_size", mine.get("elf_size"), str(size))
        self.eq("elf", "trusted ELF report elf_checks", mine.get("elf_checks"), "passed")
        for field, key in ELF_FIELDS.items():
            self.eq("elf", f"runtime_requirements.{field} (trusted ELF report)", rr[field], mine.get(key))
        self.eq("elf", "runtime_requirements.needed (trusted ELF report)", rr["needed"], mine.get("elf_needed", "").split())
        self.eq("elf", "runtime_requirements.symbols_above_glibc_2_17 (trusted ELF report)",
                rr["symbols_above_glibc_2_17"], mine.get("elf_symbols_above_glibc_2_17", "").split())
        for key in sorted(set(mine) | set(theirs)):
            if key != "elf_file":   # file(1) wording depends on the verifier's host
                self.eq("elf", f"artifact elf-report.txt {key} (trusted ELF report)", theirs.get(key), mine.get(key))
        self.eq("elf", "runtime_requirements.elf_checks", rr["elf_checks"], "passed")
        self.eq("elf", "runtime_requirements.interpreter", rr["interpreter"], INTERPRETER)
        self.check("elf", set(rr["needed"]) <= ALLOWED_NEEDED,
                   f"runtime_requirements.needed {rr['needed']} only from {sorted(ALLOWED_NEEDED)}")
        self.eq("elf", "runtime_requirements.rpath_runpath", rr["rpath_runpath"], "none")
        self.eq("elf", "runtime_requirements.cxx_version_needs", rr["cxx_version_needs"], "none")
        self.eq("elf", "runtime_requirements.max_glibc_allowed", rr["max_glibc_allowed"], MAX_GLIBC)
        mg = glibc_key(rr["max_glibc"])
        self.check("elf", mg is not None and mg <= glibc_key(MAX_GLIBC),
                   f"runtime_requirements.max_glibc {rr['max_glibc']} at most {MAX_GLIBC}")

        b, bl = m["build"], m["builder"]
        files = {n: sha256_file(os.path.join(a.recipe_dir, n)) for n in RECIPE_FILES}
        combined = hashlib.sha256("".join(f"{files[n]}  {n}\n" for n in sorted(files)).encode()).hexdigest()
        self.eq("build", "build.recipe.files (verifier's recipe)", b["recipe"]["files"], files)
        self.eq("build", "build.recipe.sha256 (verifier's recipe)", b["recipe"]["sha256"], combined)
        self.eq("build", "build.cmake_target", b["cmake_target"], "daemon")
        self.eq("build", "build.cmake_options", b["cmake_options"], CMAKE_OPTIONS)
        dockerfile = read_text(os.path.join(a.recipe_dir, "Dockerfile"))
        frm = re.search(r"^FROM\s+(\S+)", dockerfile, re.M)
        snap = re.search(r"^ARG SNAPSHOT=(\S+)$", dockerfile, re.M)
        self.eq("build", "builder.base_image (verifier's Dockerfile)", bl["base_image"], frm.group(1) if frm else None)
        self.eq("build", "builder.apt_snapshot (verifier's Dockerfile)", bl["apt_snapshot"], snap.group(1) if snap else None)
        self.eq("build", "builder.source_date_epoch (trusted identity)", bl["source_date_epoch"], int(flat["source_commit_time"]))
        logs = os.path.join(d, "build-logs")
        pk = os.path.join(logs, "builder-packages.tsv")
        self.eq("build", "builder.package_inventory_sha256 (build-logs/builder-packages.tsv)",
                bl["package_inventory_sha256"], sha256_file(pk))
        self.eq("build", "builder.package_count (build-logs/builder-packages.tsv)", bl["package_count"],
                sum(1 for line in read_text(pk).split("\n") if line.strip()))
        self.eq("build", "builder.apt_state (build-logs/builder-apt-state.txt)", bl["apt_state"],
                read_text(os.path.join(logs, "builder-apt-state.txt")).splitlines())
        image = read_text(os.path.join(logs, "image.txt")).split()
        self.eq("build", "builder.image_id (build-logs/image.txt)", bl["image_id"], image[0] if image else None)
        toolchain = read_text(os.path.join(logs, "toolchain.txt")).splitlines()
        self.eq("build", "builder.toolchain (build-logs/toolchain.txt)", bl["toolchain"], toolchain)
        self.check("build", "mode=release" in toolchain and f"HEAD {commit}" in toolchain,
                   "toolchain record names mode=release and the expected HEAD")
        self.link_inventory_check(b, logs)
        steps = read_text(os.path.join(logs, "steps.txt")).splitlines()
        self.eq("build", "build.steps (build-logs/steps.txt)", b["steps"], steps)
        self.check("build", "BUILD release ok" in steps and "container exit 0" in steps,
                   "build steps record a completed release build")

        for key, value in m["checks"].items():
            self.check("checks", value is True, f"checks.{key} is {json.dumps(value)}")

    def run(self):
        if self.files() and self.schema():
            self.semantics()
        return not self.failed()


def check_common_options(a):
    """Usage checks shared with verify-cross-artifact.py; sets a.pull_request_obj."""
    for name in ("expected_commit", "github_sha", "base_tag_object", "base_commit"):
        if not SHA1.fullmatch(getattr(a, name)):
            raise Usage(f"--{name.replace('_', '-')} must be 40 lowercase hex digits")
    for name in ("base_fingerprint", "maintainer_fingerprint"):
        if not FPR.fullmatch(getattr(a, name)):
            raise Usage(f"--{name.replace('_', '-')} must be a 40-digit uppercase fingerprint")
    for name in ("run_id", "run_attempt"):
        if not re.fullmatch(r"[1-9][0-9]*", getattr(a, name)):
            raise Usage(f"--{name.replace('_', '-')} must be a positive number")
    if not EXPECTED_VERSION.fullmatch(a.expected_version):
        raise Usage("--expected-version must look like 2.3.0-<9 hex digits> (\"release\" is never accepted)")
    try:
        a.pull_request_obj = ri.parse_pull_request(a.pull_request)
    except ValueError as e:
        raise Usage(f"--pull-request: {e}")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    for name in ("artifact", "expected-commit", "expected-version", "repository", "ref", "workflow-ref",
                 "run-id", "run-attempt", "event-name", "github-sha", "pull-request",
                 "base-repository", "base-tag", "base-tag-object", "base-commit",
                 "base-fingerprint", "maintainer-fingerprint", "source-identity", "elf-report", "recipe-dir"):
        p.add_argument(f"--{name}", required=True)
    p.add_argument("--server-url", default="https://github.com")
    p.add_argument("--producer-job", default="release-build")
    p.add_argument("--report", help="write every result as JSON to this file")
    a = p.parse_args()
    v = Verifier(a)
    try:
        check_common_options(a)
        for f in (a.source_identity, a.elf_report):
            if not os.path.isfile(f):
                raise Usage(f"{f} is not a file")
        for n in RECIPE_FILES:
            if not os.path.isfile(os.path.join(a.recipe_dir, n)):
                raise Usage(f"--recipe-dir has no {n}")
        ok = v.run()
    except Usage as e:
        print(f"verify-artifact: usage: {e}", file=sys.stderr)
        sys.exit(2)
    except (OSError, UnicodeDecodeError, KeyError, TypeError, ValueError, AttributeError, IndexError) as e:
        v.check("internal", False, f"cannot complete the checks: {type(e).__name__}: {e}")
        ok = False
    if a.report:
        with open(a.report, "w") as f:
            json.dump({"verdict": "passed" if ok else "failed", "artifact": a.artifact,
                       "expected_commit": a.expected_commit, "run_id": a.run_id, "run_attempt": a.run_attempt,
                       "results": [{"area": ar, "ok": o, "check": msg} for ar, o, msg in v.results]},
                      f, indent=2)
            f.write("\n")
    if not ok:
        for area, good, msg in v.results:
            if not good:
                print(f"verify-artifact: FAILED [{area}] {msg}", file=sys.stderr)
        print(f"verify-artifact: {len(v.failed())} of {len(v.results)} checks failed", file=sys.stderr)
        sys.exit(1)
    print(f"verify-artifact: all {len(v.results)} checks passed", file=sys.stderr)
    print(a.expected_version)


if __name__ == "__main__":
    main()
