#!/usr/bin/env python3
"""Check a downloaded release set against the run and the tagged commit; write the release notes.

  check-release-set.py --dir D --checkout DIR --commit SHA --repository OWNER/NAME --ref REF
                       --run-id N --run-attempt N --run-url URL --tag NAME --gate-note FILE
                       --notes FILE

Used by draft-release.sh after it has verified the run, the tag and GitHub's digest of the
artifact. Checks, each fatal (exit 1):
  files     D holds only regular files with plain names: SHA256SUMS, five archives and five
            manifests (one per platform); SHA256SUMS lists exactly the five archives, each
            once, and every hash matches;
  manifest  each zephyrd-<tag>-<platform>.manifest.json is strict JSON, valid against
            release-target.schema.json next to this script; its release is --tag; its commit
            is --commit, its run is --run-id and --run-attempt, event push on --ref of
            --repository; its version string is v<number>-<first 9 hex digits of the commit>
            ("release" never); its archive name, size and hash match the file and SHA256SUMS;
            the licence list is "complete" (an incomplete list is refused with its reasons);
  archive   each archive unpacks to exactly one top directory zephyrd-<tag>-<platform>/
            with the binary (mode 0755, the manifest's and the build manifest's hash),
            LICENSE, README.txt and THIRD-PARTY-LICENSES/INDEX.txt, and no link or path
            outside it;
  copyleft  every package of COPYLEFT (make-release-set.py) in a manifest's licence list is
            in its "copyleft" list, and each entry's version, URL and hash are those of
            --checkout (the verified checkout of the tagged commit)
            contrib/depends/packages/<package>.mk;
  texts     contrib/myzephyr/release/WHATSNEW.md of --checkout and the --gate-note file are
            not empty and hold no placeholder (TODO, TBD, XXX, "TO BE ").
Prints the files to upload (the five archives, then SHA256SUMS) and writes Markdown notes to
--notes: what it is (WHATSNEW.md), downloads with the binary hashes, verification, what the
hosted runners tested and the gate note, and the copyleft sources.
"""
import argparse
import hashlib
import importlib.util
import os
import re
import stat
import sys
import tarfile
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.dont_write_bytecode = True
_spec = importlib.util.spec_from_file_location("make_release_set", os.path.join(HERE, "make-release-set.py"))
mrs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mrs)
va = mrs.va
PLATFORMS = {plat: (binary, fmt) for plat, (_, binary, fmt) in mrs.PLATFORMS.items()}
SAFE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
PLACEHOLDER = re.compile(r"TODO|TBD|XXX|TO BE ")


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
    if sorted(sums) != sorted(n for n in names if n.endswith((".tar.gz", ".zip"))) or len(sums) != len(PLATFORMS):
        raise Refused(f"SHA256SUMS lists {sorted(sums)}, expected exactly the five archives of {names}")
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
        for what, got, want in (("platform", m["platform"], plat), ("release", m["release"], a.tag),
                                ("commit", m["source"]["commit"], a.commit),
                                ("build manifest commit", m["build_manifest"].get("source", {}).get("commit"), a.commit),
                                ("version string", m["version_string"], want_vs), ("run id", wf["run_id"], a.run_id),
                                ("run attempt", wf["run_attempt"], a.run_attempt), ("event", wf["event_name"], "push"),
                                ("ref", wf["ref"], a.ref), ("repository", wf["repository"], a.repository),
                                ("workflow sha", wf["sha"], a.commit), ("run url", m["run_url"], a.run_url),
                                ("binary name", m["binary"]["name"], binary), ("archive format", m["archive"]["format"], fmt),
                                ("manifest name", m["manifest_name"], cand[0]),
                                ("archive name", m["archive"]["name"], f"zephyrd-{a.tag}-{plat}.{fmt}"),
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
        if top != f"zephyrd-{a.tag}-{plat}":
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
    for plat, m in mans.items():
        owners = {e["owner"] for e in m["third_party_licenses"]["entries"]}
        listed = {c["package"]: c for c in m["copyleft"]}
        if sorted(listed) != sorted(p for p in mrs.COPYLEFT if f"depends:{p}" in owners):
            raise Refused(f"{plat}: copyleft list {sorted(listed)} does not match the linked packages of {sorted(mrs.COPYLEFT)}")
        for pkg, c in listed.items():
            src = mrs.depends_source(a.checkout, pkg)
            if src is None or (c["version"], c["url"], c["pinned_sha256"]) != src:
                raise Refused(f"{plat}: {pkg} named as {c['version']} {c['url']} {c['pinned_sha256']}, the checkout pins {src}")
    expected = {"SHA256SUMS"} | {m["archive"]["name"] for m in mans.values()} | {m["manifest_name"] for m in mans.values()}
    if set(names) != expected:
        raise Refused(f"the set holds {sorted(set(names) - expected)} beyond, or lacks {sorted(expected - set(names))} of, "
                      "SHA256SUMS, five archives and five manifests")
    return names, mans, vs


def text(path, what):
    t = open(path, encoding="utf-8").read().strip()
    if not t or PLACEHOLDER.search(t):
        raise Refused(f"{what} is empty or holds a placeholder")
    return t


def notes(a, mans, vs, whatsnew, gate):
    m0 = mans["linux-x86_64"]
    lines = ["My personal build of the Zephyr daemon, `zephyrd`. Not part of zephyr-backports, not an official Zephyr "
             "release; I am not affiliated with ZephyrProtocol.", "", "## What it is", "",
             f"The signed zephyr-backports tag `{m0['base']['tag']}` plus my own commits, up to `{a.commit}`. "
             f"Every binary reports `{vs}`. {mrs.BUILD_NOTE}", "", whatsnew, "", "## Downloads", "",
             "| Platform | Archive | SHA256 of the binary inside |", "|---|---|---|"]
    lines += [f"| {mrs.LABEL[p]} | `{m['archive']['name']}` | `{m['binary']['sha256']}` |" for p, m in mans.items()]
    lines += ["", "Linux needs glibc 2.29 or newer. The macOS and Windows binaries are not notarized or Authenticode-signed.",
              "", "## Verify", "",
              f"1. `gpg --verify SHA256SUMS.asc` (my key: `{m0['own_commit_signer_primary_fingerprint']}`)",
              "2. `sha256sum -c SHA256SUMS`", f"3. `git verify-tag {a.tag}`", "",
              f"Built before the tag existed by [this run]({a.run_url}); nothing was rebuilt for the release.",
              "", "## Tested", "", "On GitHub's hosted runners, from this build:", ""]
    lines += [f"- {mrs.LABEL[p]}: " + "; ".join(m["tested"][1:]) + f". Not tested: {m['not_tested']}." for p, m in mans.items()]
    lines += ["", gate, "", "## Licences and sources", "",
              "Each archive holds `LICENSE` and `THIRD-PARTY-LICENSES/`. Sources of the statically linked copyleft "
              "libraries, as pinned in `contrib/depends/packages/`:", "",
              "| Library | Linked into | Source | SHA256 |", "|---|---|---|---|"]
    by_pkg = {}
    for p, m in mans.items():
        for c in m["copyleft"]:
            by_pkg.setdefault(c["package"], (c, []))[1].append(p)
    family = {"linux": "Linux", "macos": "macOS", "windows": "Windows"}
    for pkg in sorted(by_pkg):
        c, plats = by_pkg[pkg]
        names = [family[f] if all(q in plats for q in mans if q.startswith(f)) else ", ".join(mrs.LABEL[q] for q in plats if q.startswith(f))
                 for f in family if any(q.startswith(f) for q in plats)]
        where = "all" if len(plats) == len(mans) else ", ".join(names)
        lines.append(f"| {c['name']} {c['version']} ({c['licence']}) | {where} | {c['url']} | `{c['pinned_sha256']}` |")
    return "\n".join(lines) + "\n"


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    for n in ("dir", "checkout", "commit", "repository", "ref", "run-id", "run-attempt", "run-url", "tag", "gate-note", "notes"):
        p.add_argument(f"--{n}", required=True)
    a = p.parse_args()
    try:
        names, mans, vs = check(a)
        whatsnew = text(os.path.join(a.checkout, "contrib", "myzephyr", "release", "WHATSNEW.md"), "WHATSNEW.md")
        gate = text(a.gate_note, "the gate note")
    except Refused as e:
        print(f"check-release-set: refused: {e}", file=sys.stderr)
        sys.exit(1)
    except (OSError, ValueError, KeyError, TypeError, tarfile.TarError, zipfile.BadZipFile) as e:
        print(f"check-release-set: refused: cannot read the set: {type(e).__name__}: {e}", file=sys.stderr)
        sys.exit(1)
    with open(a.notes, "w", encoding="utf-8") as f:
        f.write(notes(a, mans, vs, whatsnew, gate))
    for n in sorted(n for n in names if n.endswith((".tar.gz", ".zip"))) + ["SHA256SUMS"]:
        print(n)


if __name__ == "__main__":
    main()
