#!/usr/bin/env python3
"""Check a downloaded release set against the run and the tagged commit; write the release notes.

  check-release-set.py --dir D --checkout DIR --commit SHA --repository OWNER/NAME --ref REF
                       --run-id N --run-attempt N --run-url URL --tag NAME --notes FILE
                       [--reports FILE]

Used by draft-release.sh after it has verified the run, the tag and GitHub's digest of the
artifact. Checks, each fatal (exit 1):
  files     D holds only regular files: exactly SHA256SUMS, four archives, four manifests
            (one per platform) and the source tarballs the manifests name, plain names;
            SHA256SUMS lists every other file once, never itself, and every hash matches;
  manifest  each zephyrd-<version>-<platform>.manifest.json is strict JSON, valid against
            release-target.schema.json next to this script; its commit is --commit, its run
            is --run-id and --run-attempt, event push on --ref of --repository; its version
            string is v<number>-<first 9 hex digits of the commit> ("release" never); its
            archive name, size and hash match the file and SHA256SUMS; the licence list is
            "complete" (an incomplete list is refused with its reasons);
  archive   each archive unpacks to exactly one top directory zephyrd-<version>-<platform>/
            with the binary (mode 0755, the manifest's and the build manifest's hash),
            LICENSE, README.txt and THIRD-PARTY-LICENSES/INDEX.txt, and no link or path
            outside it;
  sources   a manifest whose licence list names a package of SOURCE_WITH_RELEASE (owner
            decisions: depends:readline, depends:libusb, depends:zeromq) must name its
            source tarball in "source_tarballs"; that file must be in D and in SHA256SUMS with
            the manifest's hash, and the hash must equal the pin in --checkout (the verified checkout of the
            tagged commit) contrib/depends/packages/<package>.mk. A manifest that does not
            name such a package needs no tarball of it; a tarball no manifest names is
            refused.
Prints the flat file list (one name per line, SHA256SUMS last) and writes Markdown notes to
--notes: what the release is, base, own commits with the upstream report each was sent as
(--reports: lines "<commit> <text>"; otherwise "not yet reported"), platforms and what the
hosted runners tested, the licence lists, verification steps and the run.
"""
import argparse
import hashlib
import importlib.util
import json
import os
import re
import stat
import sys
import tarfile
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.dont_write_bytecode = True
_spec = importlib.util.spec_from_file_location("verify_artifact", os.path.join(os.path.dirname(HERE), "verify-artifact.py"))
va = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(va)
PLATFORMS = {"linux-x86_64": ("zephyrd", "tar.gz"), "linux-aarch64": ("zephyrd", "tar.gz"),
             "macos-x86_64": ("zephyrd", "tar.gz"), "windows-x86_64": ("zephyrd.exe", "zip")}
SAFE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
SOURCE_WITH_RELEASE = ("readline", "libusb", "zeromq")


def pinned_hash(checkout, pkg):
    """The source SHA256 pinned in <checkout>/contrib/depends/packages/<pkg>.mk, or None."""
    p = os.path.join(checkout, "contrib", "depends", "packages", f"{pkg}.mk")
    if not os.path.isfile(p):
        return None
    m = re.search(r"^\$\(package\)_sha256_hash=([0-9a-f]{64})\s*$", open(p, encoding="utf-8").read(), re.M)
    return m.group(1) if m else None


class Refused(Exception):
    pass


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def members(path, fmt):
    """[(name, kind, mode, sha256 or None)] of an archive; kind f, d or x (anything else)."""
    out = []
    if fmt == "tar.gz":
        with tarfile.open(path, "r:gz") as t:
            for m in t.getmembers():
                kind = "f" if m.isfile() else "d" if m.isdir() else "x"
                data = t.extractfile(m).read() if m.isfile() else None
                out.append((m.name.rstrip("/"), kind, m.mode & 0o7777, hashlib.sha256(data).hexdigest() if data is not None else None))
    else:
        with zipfile.ZipFile(path) as z:
            for i in z.infolist():
                mode = (i.external_attr >> 16)
                isdir = i.filename.endswith("/")
                if not isdir and mode and not stat.S_ISREG(mode):
                    kind = "x"
                else:
                    kind = "d" if isdir else "f"
                data = None if isdir else z.read(i)
                out.append((i.filename.rstrip("/"), kind, mode & 0o7777, hashlib.sha256(data).hexdigest() if data is not None else None))
    return out


def check(a):
    d = a.dir
    names = sorted(os.listdir(d))
    for n in names:
        p = os.path.join(d, n)
        if not SAFE.fullmatch(n) or os.path.islink(p) or not os.path.isfile(p):
            raise Refused(f"{n!r} is not a plain regular file")
    if "SHA256SUMS" not in names:
        raise Refused("SHA256SUMS missing")
    sums = {}
    text = open(os.path.join(d, "SHA256SUMS"), encoding="utf-8").read()
    if not text.endswith("\n"):
        raise Refused("SHA256SUMS does not end with a newline")
    for line in text.splitlines():
        m = re.fullmatch(r"([0-9a-f]{64})  ([A-Za-z0-9][A-Za-z0-9._-]*)", line)
        if not m or m.group(2) in sums or m.group(2) == "SHA256SUMS":
            raise Refused(f"SHA256SUMS line {line!r} malformed, repeated or listing itself")
        sums[m.group(2)] = m.group(1)
    if sorted(sums) != sorted(n for n in names if n != "SHA256SUMS"):
        raise Refused(f"SHA256SUMS lists {sorted(sums)}, the set holds {names}")
    for n, h in sums.items():
        if sha256(os.path.join(d, n)) != h:
            raise Refused(f"{n} does not match SHA256SUMS")
    vs = None
    sch = va.strict_json(open(os.path.join(HERE, "release-target.schema.json"), encoding="utf-8").read())
    mans = {}
    for plat, (binary, fmt) in PLATFORMS.items():
        cand = [n for n in names if n.endswith(f"-{plat}.manifest.json")]
        if len(cand) != 1:
            raise Refused(f"{plat}: {len(cand)} manifests")
        try:
            m = va.strict_json(open(os.path.join(d, cand[0]), encoding="utf-8").read())
        except ValueError as e:
            raise Refused(f"{cand[0]} is not strict JSON: {e}")
        errs = []
        va.validate(m, sch, sch, "manifest", errs)
        if errs:
            raise Refused(f"{cand[0]} not valid against {sch['$id']}: {errs[:3]}")
        wf = m["workflow"]
        want_vs = None
        bm = m["build_manifest"].get("artifact", {})
        ev = bm.get("expected_version", "")
        if re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+-[0-9a-f]{9}", ev) and ev.endswith("-" + a.commit[:9]):
            want_vs = "v" + ev
        for what, got, want in (("platform", m["platform"], plat), ("commit", m["source"]["commit"], a.commit),
                                ("build manifest commit", m["build_manifest"].get("source", {}).get("commit"), a.commit),
                                ("version string", m["version_string"], want_vs), ("run id", wf["run_id"], a.run_id),
                                ("run attempt", wf["run_attempt"], a.run_attempt), ("event", wf["event_name"], "push"),
                                ("ref", wf["ref"], a.ref), ("repository", wf["repository"], a.repository),
                                ("workflow sha", wf["sha"], a.commit), ("run url", m["run_url"], a.run_url),
                                ("binary name", m["binary"]["name"], binary), ("archive format", m["archive"]["format"], fmt),
                                ("manifest name", m["manifest_name"], cand[0]),
                                ("archive name", m["archive"]["name"], f"zephyrd-{m['version_string']}-{plat}.{fmt}"),
                                ("binary hash (build manifest)", m["binary"]["sha256"], bm.get("sha256"))):
            if got != want or want is None:
                raise Refused(f"{plat}: {what} is {got!r}, expected {want!r}")
        if vs is not None and m["version_string"] != vs:
            raise Refused(f"{plat}: version string differs between platforms")
        vs = m["version_string"]
        lic = m["third_party_licenses"]
        if lic["status"] != "complete":
            raise Refused(f"{plat}: licence list incomplete: {lic['reasons']}")
        arch = os.path.join(d, m["archive"]["name"])
        if not os.path.isfile(arch) or sha256(arch) != m["archive"]["sha256"] or os.path.getsize(arch) != m["archive"]["size"] \
                or sums.get(m["archive"]["name"]) != m["archive"]["sha256"]:
            raise Refused(f"{plat}: archive {m['archive']['name']} does not match its manifest")
        top = m["archive"]["top_directory"]
        if top != f"zephyrd-{vs}-{plat}":
            raise Refused(f"{plat}: top directory {top!r}")
        got = members(arch, fmt)
        by_name = {}
        for name, kind, mode, h in got:
            if kind == "x" or name.startswith("/") or ".." in name.split("/") or not (name == top or name.startswith(top + "/")):
                raise Refused(f"{plat}: archive member {name!r} is a link, special file or outside {top}/")
            by_name[name] = (kind, mode, h)
        b = by_name.get(f"{top}/{binary}")
        if not b or b[0] != "f" or b[1] & 0o777 != 0o755 or b[2] != m["binary"]["sha256"] or b[2] != m["archive"]["unpacked_binary_sha256"]:
            raise Refused(f"{plat}: the archive does not unpack to the named binary (mode 0755, hash {m['binary']['sha256']})")
        for need in ("LICENSE", "README.txt", "THIRD-PARTY-LICENSES/INDEX.txt"):
            if by_name.get(f"{top}/{need}", ("",))[0] != "f":
                raise Refused(f"{plat}: {need} missing from the archive")
        mans[plat] = m
    # source tarballs (owner decision): required where the licence list names the package
    named = {}
    for plat, m in mans.items():
        owners = {e["owner"] for e in m["third_party_licenses"]["entries"]}
        listed = {t["package"]: t for t in m["source_tarballs"]}
        for pkg in SOURCE_WITH_RELEASE:
            if f"depends:{pkg}" in owners and pkg not in listed:
                raise Refused(f"{plat}: the licence list names depends:{pkg} but the manifest names no source tarball of it")
        for pkg, t in listed.items():
            pin = pinned_hash(a.checkout, pkg)
            if pkg not in SOURCE_WITH_RELEASE or f"depends:{pkg}" not in owners:
                raise Refused(f"{plat}: source tarball of {pkg} named, but {pkg} is not a linked package whose source goes with the release")
            if t["file"] not in names or sums.get(t["file"]) != t["sha256"]:
                raise Refused(f"{plat}: source tarball {t['file']} missing from the set or not in SHA256SUMS with the manifest's hash")
            if pin is None or t["sha256"] != pin or t["pinned_sha256"] != pin:
                raise Refused(f"{plat}: source tarball {t['file']} has {t['sha256']}, the pin in the checkout is {pin}")
            if os.path.getsize(os.path.join(d, t["file"])) != t["size"]:
                raise Refused(f"{plat}: source tarball {t['file']} size differs from the manifest")
            if named.setdefault(t["file"], t["sha256"]) != t["sha256"]:
                raise Refused(f"source tarball {t['file']} named with different hashes")
    expected = {"SHA256SUMS"} | {m["archive"]["name"] for m in mans.values()} | {m["manifest_name"] for m in mans.values()} | set(named)
    if set(names) != expected:
        raise Refused(f"the set holds {sorted(set(names) - expected)} beyond, or lacks {sorted(expected - set(names))} of, "
                      "SHA256SUMS, four archives, four manifests and the named source tarballs")
    return names, mans, vs


def notes(a, mans, vs):
    reports = {}
    if a.reports:
        for line in open(a.reports, encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith("#"):
                c, _, text = line.partition(" ")
                reports[c] = text.strip()
    m0 = mans["linux-x86_64"]
    base = m0["base"]
    lines = [f"Personal build of the Zephyr daemon, `zephyrd` {vs}, by the maintainer of this repository. "
             "Not part of zephyr-backports and not an official Zephyr release.", "",
             "## Source", "",
             f"- Commit `{a.commit}`, tagged `{a.tag}`; every binary reports `{vs}` (built before the tag existed, "
             "from a checkout without tags).",
             f"- Base: the signed zephyr-backports tag `{base['tag']}` = `{base['commit']}` "
             f"(signer `{base['signer_primary_fingerprint']}`).",
             f"- Own commits above the base, each signed by `{m0['own_commit_signer_primary_fingerprint']}`:"]
    for c in m0["source"]["own_commits"]:
        lines.append(f"  - `{c['commit'][:12]}` {c['subject']} (upstream report: {reports.get(c['commit'], 'not yet reported')})")
    lines += ["", "## Platforms and what the hosted runners of the run tested", ""]
    for plat in PLATFORMS:
        m = mans[plat]
        lines.append(f"- **{plat}** (`{m['archive']['name']}`, binary `{m['binary']['sha256']}`): " + "; ".join(m["tested"])
                     + f". Not tested: {m['not_tested']}.")
    lines += ["", f"Full mainnet sync and database resume test of exactly the Linux x86_64 binary `{mans['linux-x86_64']['binary']['sha256']}`: "
              "**TO BE STATED BY THE OWNER BEFORE PUBLISHING** (this script cannot verify them).", "",
              "## Verify", "",
              "1. `gpg --verify SHA256SUMS.asc` (the clear-signed `SHA256SUMS`; maintainer key, primary fingerprint "
              f"`{m0['own_commit_signer_primary_fingerprint']}`, see the repository README).",
              "2. `sha256sum -c SHA256SUMS`", f"3. `git verify-tag {a.tag}` in a clone; the tag points at `{a.commit}`.",
              "4. Each `*.manifest.json` names the binary's hash, the build manifest and the run.", "",
              "macOS: not notarized; Windows: not Authenticode-signed, like upstream's own builds. Each archive's "
              "`README.txt` says how to replace an upstream `zephyrd` (stop, keep the data directory, swap the binary, "
              "start with the same paths, ports and options).", "",
              "Licences: each archive holds `LICENSE` and `THIRD-PARTY-LICENSES/` (texts of everything linked into that "
              "binary, listed in `INDEX.txt`)." + "".join(
                  f" `{t['file']}` is the source of {t['name']} exactly as the build fetched and hash-checked it, published "
                  f"because {t['name']} is linked into the binaries of " + ", ".join(
                      pl for pl in PLATFORMS if any(x["file"] == t["file"] for x in mans[pl]["source_tarballs"])) + "."
                  for t in {x["file"]: x for m in mans.values() for x in m["source_tarballs"]}.values()), "",
              f"Built by {a.run_url} (push to `{a.ref}`)."]
    return "\n".join(lines) + "\n"


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    for n in ("dir", "checkout", "commit", "repository", "ref", "run-id", "run-attempt", "run-url", "tag", "notes"):
        p.add_argument(f"--{n}", required=True)
    p.add_argument("--reports")
    a = p.parse_args()
    try:
        names, mans, vs = check(a)
    except Refused as e:
        print(f"check-release-set: refused: {e}", file=sys.stderr)
        sys.exit(1)
    except (OSError, ValueError, KeyError, TypeError, tarfile.TarError, zipfile.BadZipFile) as e:
        print(f"check-release-set: refused: cannot read the set: {type(e).__name__}: {e}", file=sys.stderr)
        sys.exit(1)
    with open(a.notes, "w", encoding="utf-8") as f:
        f.write(notes(a, mans, vs))
    for n in [n for n in names if n != "SHA256SUMS"] + ["SHA256SUMS"]:
        print(n)


if __name__ == "__main__":
    main()
