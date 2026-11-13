#!/usr/bin/env python3
"""Make the release set of one run: an archive per platform, SHA256SUMS, a manifest per platform.

  make-release-set.py --checkout DIR --out DIR --run-url URL
      --artifact linux-x86_64=DIR --artifact linux-aarch64=DIR
      --artifact macos-x86_64=DIR --artifact macos-arm64=DIR --artifact windows-x86_64=DIR

Each --artifact is a build artifact of this run that the calling job has already verified
(verify-artifact.py or verify-cross-artifact.py with the job's own trusted inputs); this
script reads its manifest.json, binary and build-logs/ and checks that they agree with each
other and with the other targets (one commit, one version string, one run, one base).
--checkout is the job's own verified checkout of that commit (LICENSE, depends recipes,
own commit subjects).

The release name is the one line of contrib/myzephyr/RELEASE in the checkout (the release
this commit line prepares, e.g. v2.3.0-sec.2-my.2); the binaries still report
v<version>-<9 hex of the commit>, since builds never see a tag.
Archive per platform, fixed layout:
  zephyrd-<release>-<platform>/
    zephyrd | zephyrd.exe          the verified binary, mode 0755
    LICENSE                        the tree's LICENSE
    THIRD-PARTY-LICENSES/          the licence texts of everything linked into that binary,
                                   from its link inventory (link-inventory.sh in the build),
                                   with INDEX.txt naming owner, source file and hashes
    README.txt                     short, first person: what it is, verification, replacing
                                   an upstream zephyrd, what this run tested, and for each
                                   copyleft library linked in (COPYLEFT) its version, licence
                                   (as its text names it), upstream URL and pinned SHA256
                                   from contrib/depends/packages/<name>.mk
  .tar.gz for Linux and macOS: GNU tar --format=gnu --sort=name --mtime=@SOURCE_DATE_EPOCH
  --owner=0 --group=0 --numeric-owner --mode=u+rwX,go+rX,go-w, then gzip -n -9 (no name, no
  time); .zip for Windows with SOURCE_DATE_EPOCH as every entry's time, sorted entries and
  fixed modes. SOURCE_DATE_EPOCH is the commit time of the built commit.
Licence completeness: "complete" only if the inventory exists and is the one the verified
manifest names, the traced re-link was identical, nothing is unresolved, every used owner
(of a used input other than a build-tree product "build:<dir>", of a linked object's source
("compiled" rows) and of compiled-in headers) has a licence text, and every depends source hash
equals the pin in the checkout's contrib/depends/packages/*.mk; otherwise "incomplete" with
the reasons, in the manifest and README. A compiled-in file without a licence statement
("statement ... none" row of the inventory) does not block, and a source directory whose
every compiled-in file is such a file does not count as an owner without a text (owner
decision 2026-11-12); the build's link-inventory.tsv keeps the fact. draft-release.sh
refuses an incomplete set; this script still writes it, so every run shows the list for
review. INDEX.txt notes, for a text from a source header that names a licence file (e.g.
"accompanying file LICENSE_1_0.txt"), where a text of that file name is in the same archive.
SHA256SUMS lists exactly the five archives: they and its signature are the release assets.
Per-platform manifest zephyrd-<release>-<platform>.manifest.json (release-target.schema.json):
the input of check-release-set.py and a run artifact, not a release asset.
After writing, every archive is unpacked again and must yield exactly the layout and the
binary whose hash the build manifest names. Exit 1 on any inconsistency.
"""
import argparse
import datetime
import importlib.util
import gzip
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import textwrap
import zipfile

SCHEMA = "myzephyr/daemon-release-target/3"
RELEASE_RE = re.compile(r"v[0-9]+\.[0-9]+\.[0-9]+-sec\.[0-9]+-my\.[0-9]+")
# depends packages under a copyleft licence: README.txt and the notes name their sources
COPYLEFT = {"readline": "GNU readline", "libusb": "libusb", "zeromq": "ZeroMQ"}
BUILD_NOTE = ("I build it without hardware-wallet support and without the wallet fast-path assembly; "
              "a daemon uses neither.")
LABEL = {"linux-x86_64": "Linux x86_64", "linux-aarch64": "Linux AArch64", "macos-x86_64": "macOS x86_64 (Intel)",
         "macos-arm64": "macOS arm64 (Apple Silicon)", "windows-x86_64": "Windows x86_64"}
HERE = os.path.dirname(os.path.abspath(__file__))
sys.dont_write_bytecode = True
_spec = importlib.util.spec_from_file_location("verify_artifact", os.path.join(os.path.dirname(HERE), "verify-artifact.py"))
va = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(va)


def schema_errors(obj):
    sch = va.strict_json(open(os.path.join(HERE, "release-target.schema.json"), encoding="utf-8").read())
    errs = []
    va.validate(obj, sch, sch, "manifest", errs)
    return errs
PLATFORMS = {  # platform: (target, binary, archive format)
    "linux-x86_64": ("x86_64-unknown-linux-gnu", "zephyrd", "tar.gz"),
    "linux-aarch64": ("aarch64-linux-gnu", "zephyrd", "tar.gz"),
    "macos-x86_64": ("x86_64-apple-darwin", "zephyrd", "tar.gz"),
    "macos-arm64": ("aarch64-apple-darwin", "zephyrd", "tar.gz"),
    "windows-x86_64": ("x86_64-w64-mingw32", "zephyrd.exe", "zip"),
}
# what this run proved per platform: the jobs the package job needs, all of which succeeded
TESTED = {
    "linux-x86_64": [
        "built in the pinned Debian 11 builder (GCC 9, glibc symbols at most 2.29, no RPATH)",
        "unit tests of the same commit: all passed, on Ubuntu 24.04",
        "--version and an offline start with clean shutdown on Ubuntu 24.04 and in Debian 11 (glibc 2.31)",
        "finding peers from an empty data directory on Ubuntu 24.04",
    ],
    "linux-aarch64": [
        "cross-built in the pinned builder (GCC 9, glibc symbols at most 2.29)",
        "--version, an offline start with clean shutdown and finding peers on Ubuntu 24.04 (ARM)",
        "an offline start in Debian 11 arm64 (glibc 2.31)",
    ],
    "macos-x86_64": [
        "cross-built in the pinned builder (thin x86_64, minimum macOS 10.13)",
        "--version, an offline start with clean shutdown and finding peers on macOS 15 (Intel)",
    ],
    "macos-arm64": [
        "cross-built in the pinned builder (thin arm64, ad-hoc signature by the linker)",
        "--version, an offline start with clean shutdown and finding peers on macOS 26 (Apple Silicon)",
    ],
    "windows-x86_64": [
        "cross-built in the pinned builder (MinGW-w64, no MinGW runtime DLL)",
        "--version, an offline start with clean shutdown and finding peers on Windows Server 2022",
    ],
}
NOT_TESTED = {
    "linux-x86_64": "other Linux distributions",
    "linux-aarch64": "other AArch64 distributions",
    "macos-x86_64": "macOS 10.13 to 14, and Rosetta on Apple Silicon",
    "macos-arm64": "macOS 11 to 15",
    "windows-x86_64": "Windows 10 and 11, other Windows Server versions",
}
QUARANTINE = "After checking the hashes, remove the quarantine flag a browser download sets: xattr -d com.apple.quarantine zephyrd"
REPLACE_NOTE = {
    "linux-x86_64": None, "linux-aarch64": None,
    "macos-x86_64": "The binary is not notarized by Apple. " + QUARANTINE,
    "macos-arm64": "The binary carries only the linker's ad-hoc signature and is not notarized by Apple. " + QUARANTINE,
    "windows-x86_64": ("zephyrd.exe is not Authenticode-signed, like upstream's builds, so SmartScreen may warn. "
                       "After checking the hashes, unblock it (Properties, Unblock)."),
}


def fail(msg):
    sys.exit(f"make-release-set: {msg}")


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def git(checkout, *args):
    return subprocess.run(["git", "-C", checkout, *args], check=True, capture_output=True, text=True).stdout.strip()


def pinned_hash(checkout, pkg):
    """The source SHA256 pinned in contrib/depends/packages/<pkg>.mk (following native_<pkg> indirection)."""
    for name in (pkg, f"native_{pkg}"):
        p = os.path.join(checkout, "contrib", "depends", "packages", f"{name}.mk")
        if not os.path.isfile(p):
            continue
        m = re.search(r"^\$\(package\)_sha256_hash=(\S+)\s*$", open(p, encoding="utf-8").read(), re.M)
        if m and re.fullmatch(r"[0-9a-f]{64}", m.group(1)):
            return m.group(1)
        if m and m.group(1) != f"$(native_$(package)_sha256_hash)":
            return None
    return None


def read_inventory(path):
    rows = []
    with open(path, encoding="utf-8") as f:
        header = f.readline().rstrip("\n").split("\t")
        if header != ["kind", "path", "owner", "sha256", "detail"]:
            raise ValueError("unexpected inventory header")
        for line in f:
            parts = line.rstrip("\n").split("\t")
            if len(parts) != 5:
                raise ValueError(f"inventory line with {len(parts)} fields")
            rows.append(dict(zip(header, parts)))
    return rows


def licences(platform, art, manifest, checkout, stage):
    """Copy the licence texts into stage/THIRD-PARTY-LICENSES; return (status, entries, reasons)."""
    logs = os.path.join(art, "build-logs")
    inv_path = os.path.join(logs, "link-inventory.tsv")
    reasons, entries = [], []
    tdir = os.path.join(stage, "THIRD-PARTY-LICENSES")
    os.makedirs(tdir)
    want = manifest["build"].get("link_inventory_sha256")
    if not os.path.isfile(inv_path) or want is None:
        reasons.append("the build wrote no link inventory")
        rows = []
    elif sha256(inv_path) != want:
        fail(f"{platform}: link-inventory.tsv does not match the verified manifest")
    else:
        rows = read_inventory(inv_path)
    status_rows = {r["path"]: r["detail"] for r in rows if r["kind"] == "status" and r["path"] != "unresolved"}
    if rows and status_rows.get("relink_identical") != "yes":
        reasons.append(f"traced re-link not identical ({status_rows.get('relink_identical')})")
    for r in rows:
        if r["kind"] == "status" and r["path"] == "unresolved":
            reasons.append(f"unresolved: {r['owner']}: {r['detail']}")
    used = sorted({r["owner"] for r in rows if (r["kind"] == "input" and r["detail"].startswith("used") and not r["owner"].startswith("build:"))
                   or r["kind"] == "header" or (r["kind"] == "compiled" and r["owner"] != "unknown")})
    covered = {r["owner"] for r in rows if r["kind"] in ("license", "license-ref")}
    # a source directory whose every compiled-in file states nothing: shipped as upstream ships it
    stated = {}
    for r in rows:
        if r["kind"] == "statement" and r["owner"].startswith("tree:"):
            stated.setdefault(r["owner"], set()).add(r["detail"] != "none")
    nothing_stated = {o for o, v in stated.items() if v == {False}}
    for o in used:
        if o not in covered and o not in nothing_stated:
            reasons.append(f"no licence text for {o}")
    index = []
    for r in rows:
        if r["kind"] != "license":
            continue
        src = os.path.normpath(os.path.join(logs, r["path"]))
        if not src.startswith(os.path.join(logs, "licenses") + os.sep) or not os.path.isfile(src) or os.path.islink(src):
            fail(f"{platform}: licence text {r['path']} missing or outside build-logs/licenses")
        if sha256(src) != r["sha256"]:
            fail(f"{platform}: licence text {r['path']} does not match its inventory hash")
        rel = os.path.relpath(src, os.path.join(logs, "licenses"))
        dst = os.path.join(tdir, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copyfile(src, dst)
        detail = dict(kv.split("=", 1) for kv in r["detail"].split(" ")[1:] if "=" in kv)
        e = {"owner": r["owner"], "text": f"THIRD-PARTY-LICENSES/{rel}", "text_sha256": r["sha256"],
             "kind": r["detail"].split(" ", 1)[0], "source": detail}
        if e["kind"] == "depends":
            pin = pinned_hash(checkout, r["owner"].split(":", 1)[1])
            e["pinned_sha256"] = pin
            if pin is None or pin != detail.get("source_sha256"):
                reasons.append(f"{r['owner']}: source hash {detail.get('source_sha256')} is not the pinned {pin}")
        entries.append(e)
        note = ("\n    FROM SOURCE HEADER: a verbatim comment block from the head of the file named below; its"
                "\n    directory ships no licence file") if e["kind"] == "tree-header" else ""
        index.append([rel, r, note, src if e["kind"] == "tree-header" else None])
    by_base = {}
    for rel, r, _, _ in index:
        by_base.setdefault(os.path.basename(rel), []).append((rel, r["owner"]))
    lines_out = []
    for rel, r, note, hsrc in index:
        if hsrc:
            text = open(hsrc, encoding="utf-8", errors="replace").read()
            for name in sorted(set(re.findall(r"[A-Za-z0-9_.-]*(?:LICEN[CS]E|COPYING)[A-Za-z0-9_.-]*", text))):
                for orel, oown in by_base.get(name, []):
                    if orel != rel:
                        note += (f"\n    The statement names {name}; a text of that name is in this archive:"
                                 f"\n    THIRD-PARTY-LICENSES/{orel} (owner {oown})")
        lines_out.append(f"{rel}\n    owner {r['owner']}{note}\n    from {r['detail']}\n    sha256 {r['sha256']}")
    index = lines_out
    status = "complete" if not reasons else "incomplete"
    head = [f"Licence texts of everything linked into {PLATFORMS[platform][1]} ({platform}), from the link inventory",
            "of its build (link-inventory.sh). Status: " + status + "."]
    if reasons:
        head += ["NOT ESTABLISHED (this archive must not be released until these are resolved):"] + [f"  - {x}" for x in reasons]
    with open(os.path.join(tdir, "INDEX.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(head) + "\n\n" + "\n\n".join(index) + "\n")
    return status, entries, reasons


def depends_source(checkout, pkg):
    """(version, URL, pinned SHA256) of contrib/depends/packages/<pkg>.mk, or None if not all three are found."""
    p = os.path.join(checkout, "contrib", "depends", "packages", f"{pkg}.mk")
    if not os.path.isfile(p):
        return None
    var = dict(re.findall(r"^\$\(package\)_(version|download_path|file_name|sha256_hash)=(\S+)\s*$", open(p, encoding="utf-8").read(), re.M))
    if sorted(var) != ["download_path", "file_name", "sha256_hash", "version"] or not re.fullmatch(r"[0-9a-f]{64}", var["sha256_hash"]):
        return None
    expand = lambda v: v.replace("$($(package)_version)", var["version"]).replace("$(package)", pkg)
    url = expand(var["download_path"]).rstrip("/") + "/" + expand(var["file_name"])
    return None if "$" in url + var["version"] else (var["version"], url, var["sha256_hash"])


def licence_name(path):
    """The licence as its text names it: the first non-empty line, with a following "Version ..." line."""
    lines = [l.strip() for l in open(path, encoding="utf-8", errors="replace").read().splitlines() if l.strip()]
    if not lines:
        return None
    return lines[0] + (" " + lines[1] if len(lines) > 1 and lines[1].startswith("Version") else "")


def copyleft(platform, entries, checkout, stage):
    """[{package, name, version, licence, url, pinned_sha256}] of the copyleft depends packages linked in."""
    out = []
    for pkg in sorted(COPYLEFT):
        texts = sorted(e["text"] for e in entries if e["owner"] == f"depends:{pkg}" and e["kind"] == "depends")
        if not texts:
            continue
        src = depends_source(checkout, pkg)
        if src is None:
            fail(f"{platform}: depends:{pkg} is linked but contrib/depends/packages/{pkg}.mk names no version, URL and hash")
        out.append({"package": pkg, "name": COPYLEFT[pkg], "version": src[0], "licence": licence_name(os.path.join(stage, texts[0])),
                    "url": src[1], "pinned_sha256": src[2]})
    return out


def readme(tm):
    p, b = tm["platform"], tm["binary"]
    lic = tm["third_party_licenses"]
    wrap = lambda t, ind="": textwrap.wrap(t, 90, initial_indent=ind, subsequent_indent=ind)
    lines = [f"zephyrd {tm['release']} for {LABEL[p]}", ""] + wrap(
        "My personal build of the Zephyr daemon. It is not part of zephyr-backports and not an official Zephyr "
        f"release. Source: {tm['workflow']['server_url']}/{tm['workflow']['repository']}") + [""] + wrap(
        f"It is the signed zephyr-backports tag {tm['base']['tag']} plus my own commits, up to commit "
        f"{tm['source']['commit']}. The binary reports {tm['version_string']}. {BUILD_NOTE}") + [
        "",
        "VERIFY",
        f"  gpg --verify SHA256SUMS.asc   (my key: {tm['own_commit_signer_primary_fingerprint']})",
        "  sha256sum -c SHA256SUMS",
        f"  {b['name']} in this archive has SHA256 {b['sha256']}.",
        "",
        "REPLACE AN UPSTREAM ZEPHYRD",
        "  Stop it, keep its data directory, put this binary in its place and start it with the",
        "  same options. RPC, P2P protocol and database format are upstream's.",
    ]
    if REPLACE_NOTE[p]:
        lines += wrap(REPLACE_NOTE[p], "  ")
    lines += ["", "TESTED FOR THIS PLATFORM, ON GITHUB'S HOSTED RUNNERS"] + [f"  - {t}" for t in tm["tested"]]
    lines += wrap(f"Not tested: {tm['not_tested']}. The release notes say what else I tested.", "  ") + [
        "", "LICENCES",
        f"  LICENSE is the source tree's licence. THIRD-PARTY-LICENSES/ holds the texts of everything",
        f"  linked into {b['name']}, listed in INDEX.txt. Status: {lic['status']}."]
    if tm["copyleft"]:
        lines += [f"  Copyleft libraries linked into {b['name']}, built from these sources:"]
        for c in tm["copyleft"]:
            lines += [f"    {c['name']} {c['version']}, {c['licence']}", f"      {c['url']}", f"      SHA256 {c['pinned_sha256']}"]
    if lic["status"] != "complete":
        lines += ["  NOT ESTABLISHED: this archive must not be released until these are resolved:"] + \
                 [f"    - {r}" for r in lic["reasons"]]
    return "\n".join(lines) + "\n"


def write_tar_gz(stage_parent, top, out, epoch):
    tar = subprocess.run(["tar", "--format=gnu", "--sort=name", f"--mtime=@{epoch}", "--owner=0", "--group=0",
                          "--numeric-owner", "--mode=u+rwX,go+rX,go-w", "-cf", "-", "-C", stage_parent, top],
                         check=True, capture_output=True).stdout
    with open(out, "wb") as f:
        f.write(gzip.compress(tar, compresslevel=9, mtime=0))   # same bytes as gzip -n -9: no name, time 0


def write_zip(stage_parent, top, out, epoch):
    t = datetime.datetime.fromtimestamp(max(epoch, 315532800), datetime.timezone.utc).timetuple()[:6]
    entries = []
    for root, dirs, files in os.walk(os.path.join(stage_parent, top)):
        dirs.sort()
        rel = os.path.relpath(root, stage_parent).replace(os.sep, "/")
        entries.append((rel + "/", None))
        for n in sorted(files):
            entries.append((f"{rel}/{n}", os.path.join(root, n)))
    with zipfile.ZipFile(out, "w") as z:
        for name, path in sorted(entries):
            zi = zipfile.ZipInfo(name, date_time=t)
            zi.create_system = 3
            if path is None:
                zi.external_attr = (stat.S_IFDIR | 0o755) << 16 | 0x10
                z.writestr(zi, b"")
            else:
                mode = 0o755 if os.access(path, os.X_OK) else 0o644
                zi.external_attr = (stat.S_IFREG | mode) << 16
                zi.compress_type = zipfile.ZIP_DEFLATED
                with open(path, "rb") as f:
                    z.writestr(zi, f.read(), compresslevel=9)


def archive_listing(path, fmt):
    """{member name: (type, mode, mtime, uid, gid, sha256 or None)} of an archive, read back."""
    out = {}
    if fmt == "tar.gz":
        with tarfile.open(path, "r:gz") as t:
            for m in t.getmembers():
                data = t.extractfile(m).read() if m.isfile() else None
                out[m.name.rstrip("/")] = ("f" if m.isfile() else "d" if m.isdir() else "x", m.mode, m.mtime, m.uid, m.gid,
                                           hashlib.sha256(data).hexdigest() if data is not None else None)
    else:
        with zipfile.ZipFile(path) as z:
            for i in z.infolist():
                isdir = i.filename.endswith("/")
                data = None if isdir else z.read(i)
                out[i.filename.rstrip("/")] = ("d" if isdir else "f", (i.external_attr >> 16) & 0o7777, i.date_time, None, None,
                                               hashlib.sha256(data).hexdigest() if data is not None else None)
    return out


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--checkout", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--run-url", required=True)
    p.add_argument("--artifact", action="append", required=True, help="platform=DIR")
    a = p.parse_args()
    arts = {}
    for spec in a.artifact:
        plat, _, d = spec.partition("=")
        if plat not in PLATFORMS or not d or plat in arts:
            fail(f"--artifact {spec!r}: expected one of {sorted(PLATFORMS)}=DIR, each once")
        arts[plat] = os.path.abspath(d)
    if sorted(arts) != sorted(PLATFORMS):
        fail(f"need all {len(PLATFORMS)} platforms, got {sorted(arts)}")
    if os.path.lexists(a.out):
        fail(f"{a.out} exists")
    checkout = os.path.abspath(a.checkout)

    mans = {plat: load_json(os.path.join(d, "manifest.json")) for plat, d in arts.items()}
    first = mans["linux-x86_64"]
    commit, version = first["source"]["commit"], first["artifact"]["expected_version"]
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+-[0-9a-f]{9}", version) or not version.endswith("-" + commit[:9]):
        fail(f"version {version!r} is not <number>-{commit[:9]} (\"release\" is never packaged)")
    if git(checkout, "rev-parse", "HEAD") != commit:
        fail("the checkout is not the built commit")
    for plat, m in mans.items():
        target, binary, _ = PLATFORMS[plat]
        for what, got, want in (("target", m["artifact"]["target"], target), ("binary name", m["artifact"]["name"], binary),
                                ("commit", m["source"]["commit"], commit), ("version", m["artifact"]["expected_version"], version),
                                ("run", (m["workflow"].get("run_id"), m["workflow"].get("run_attempt")),
                                 (first["workflow"].get("run_id"), first["workflow"].get("run_attempt"))),
                                ("event and ref", (m["workflow"].get("event_name"), m["workflow"].get("ref")),
                                 (first["workflow"].get("event_name"), first["workflow"].get("ref"))),
                                ("base", m["base"], first["base"]), ("own commits", m["source"]["own_commits"], first["source"]["own_commits"]),
                                ("commit time", m["source"]["commit_time"], first["source"]["commit_time"])):
            if got != want:
                fail(f"{plat}: {what} {got!r} differs from {want!r}")
        bp = os.path.join(arts[plat], binary)
        if sha256(bp) != m["artifact"]["sha256"] or os.path.getsize(bp) != m["artifact"]["size"]:
            fail(f"{plat}: binary does not match its manifest")
    if "local_build" in first["workflow"]:
        fail("a local build is never packaged")
    epoch = first["source"]["commit_time"]
    vs = "v" + version
    try:
        release = open(os.path.join(checkout, "contrib", "myzephyr", "RELEASE"), encoding="utf-8").read()
    except OSError:
        fail("the checkout has no contrib/myzephyr/RELEASE")
    if not RELEASE_RE.fullmatch(release.rstrip("\n")) or release.count("\n") != 1 or not release.endswith("\n"):
        fail(f"contrib/myzephyr/RELEASE is {release!r}, expected one line v<x.y.z>-sec.<n>-my.<n>")
    release = release.rstrip("\n")
    own = [{"commit": c["commit"], "subject": git(checkout, "log", "-1", "--format=%s", c["commit"]), "paths": c["paths"]}
           for c in first["source"]["own_commits"]]

    os.makedirs(a.out)
    work = tempfile.mkdtemp(prefix="release-set-")
    old_umask = os.umask(0o022)
    try:
        sums, manifests = {}, []
        for plat in sorted(PLATFORMS):
            target, binary, fmt = PLATFORMS[plat]
            m, art = mans[plat], arts[plat]
            top = f"zephyrd-{release}-{plat}"
            stage = os.path.join(work, plat, top)
            os.makedirs(stage)
            shutil.copyfile(os.path.join(art, binary), os.path.join(stage, binary))
            os.chmod(os.path.join(stage, binary), 0o755)
            shutil.copyfile(os.path.join(checkout, "LICENSE"), os.path.join(stage, "LICENSE"))
            status, entries, reasons = licences(plat, art, m, checkout, stage)
            archive = f"{top}.{fmt}"
            mname = f"{top}.manifest.json"
            tm = {
                "schema": SCHEMA, "platform": plat, "target": target, "release": release, "version_string": vs,
                "archive": {"name": archive, "format": fmt, "top_directory": top, "sha256": None, "size": None},
                "binary": {"name": binary, "path": f"{top}/{binary}", "sha256": m["artifact"]["sha256"], "size": m["artifact"]["size"]},
                "build_manifest_sha256": sha256(os.path.join(art, "manifest.json")), "build_manifest": m,
                "source": {"commit": commit, "commit_time": epoch, "own_commits": own},
                "base": m["base"], "own_commit_signer_primary_fingerprint": m["own_commit_signer_primary_fingerprint"],
                "workflow": m["workflow"], "run_url": a.run_url,
                "tested": TESTED[plat], "not_tested": NOT_TESTED[plat],
                "third_party_licenses": {"status": status, "reasons": reasons, "entries": entries},
                "copyleft": copyleft(plat, entries, checkout, stage),
                "manifest_name": mname, "source_date_epoch": epoch,
            }
            with open(os.path.join(stage, "README.txt"), "w", encoding="utf-8") as f:
                f.write(readme(tm))
            out = os.path.join(a.out, archive)
            (write_tar_gz if fmt == "tar.gz" else write_zip)(os.path.join(work, plat), top, out, epoch)
            # read it back: exactly the staged layout, the verified binary, fixed metadata
            got = archive_listing(out, fmt)
            staged = {}
            for root, dirs, files in os.walk(stage):
                rel = os.path.relpath(root, os.path.join(work, plat)).replace(os.sep, "/")
                staged[rel] = None
                for n in files:
                    staged[f"{rel}/{n}"] = sha256(os.path.join(root, n))
            if sorted(got) != sorted(staged):
                fail(f"{plat}: archive members {sorted(set(got) ^ set(staged))} differ from the staged layout")
            for name, h in staged.items():
                if got[name][5] != h:
                    fail(f"{plat}: {name} in the archive differs from the staged file")
            if got[f"{top}/{binary}"][5] != m["artifact"]["sha256"] or got[f"{top}/{binary}"][1] & 0o777 != 0o755:
                fail(f"{plat}: unpacked binary is not the verified one with mode 0755")
            if fmt == "tar.gz" and any((x[2], x[3], x[4]) != (epoch, 0, 0) for x in got.values()):
                fail(f"{plat}: tar members without the fixed time and owner")
            tm["archive"]["sha256"], tm["archive"]["size"] = sha256(out), os.path.getsize(out)
            tm["archive"]["unpacked_binary_sha256"] = got[f"{top}/{binary}"][5]
            errs = schema_errors(tm)
            if errs:
                fail(f"{plat}: manifest not valid against {SCHEMA}: {errs[:3]}")
            with open(os.path.join(a.out, mname), "w", encoding="utf-8") as f:
                json.dump(tm, f, indent=2, sort_keys=True)
                f.write("\n")
            sums[archive] = tm["archive"]["sha256"]
            manifests.append(mname)
            print(f"{archive}  {tm['archive']['sha256']}  licences {status}" + (f" ({len(reasons)} open)" if reasons else ""))
            for r in reasons:
                print(f"::warning title=licences {plat}::not established: {r}")
        listed = sorted(n for n in os.listdir(a.out))
        if listed != sorted(list(sums) + manifests):
            fail(f"unexpected files in {a.out}: {listed}")
        with open(os.path.join(a.out, "SHA256SUMS"), "w", encoding="utf-8") as f:
            f.write("".join(f"{sums[n]}  {n}\n" for n in sorted(sums)))
    finally:
        os.umask(old_umask)
        shutil.rmtree(work, ignore_errors=True)
    print(open(os.path.join(a.out, "SHA256SUMS")).read(), end="")


if __name__ == "__main__":
    main()
