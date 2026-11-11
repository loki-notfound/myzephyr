#!/usr/bin/env python3
"""Make the release set of one run: an archive per platform, a manifest per platform, SHA256SUMS.

  make-release-set.py --checkout DIR --out DIR --run-url URL
      --artifact linux-x86_64=DIR --artifact linux-aarch64=DIR
      --artifact macos-x86_64=DIR --artifact windows-x86_64=DIR

Each --artifact is a build artifact of this run that the calling job has already verified
(verify-artifact.py or verify-cross-artifact.py with the job's own trusted inputs); this
script reads its manifest.json, binary and build-logs/ and checks that they agree with each
other and with the other targets (one commit, one version string, one run, one base).
--checkout is the job's own verified checkout of that commit (LICENSE, depends recipes,
own commit subjects).

Archive per platform, fixed layout, named by the version string (the tag does not exist yet):
  zephyrd-<version string>-<platform>/
    zephyrd | zephyrd.exe          the verified binary, mode 0755
    LICENSE                        the tree's LICENSE
    THIRD-PARTY-LICENSES/          the licence texts of everything linked into that binary,
                                   from its link inventory (link-inventory.sh in the build),
                                   with INDEX.txt naming owner, source file and hashes
    README.txt                     generated from the per-platform manifest
  .tar.gz for Linux and macOS: GNU tar --format=gnu --sort=name --mtime=@SOURCE_DATE_EPOCH
  --owner=0 --group=0 --numeric-owner --mode=u+rwX,go+rX,go-w, then gzip -n -9 (no name, no
  time); .zip for Windows with SOURCE_DATE_EPOCH as every entry's time, sorted entries and
  fixed modes. SOURCE_DATE_EPOCH is the commit time of the built commit.
Licence completeness: "complete" only if the inventory exists and is the one the verified
manifest names, the traced re-link was identical, nothing is unresolved, every used input's
owner has a licence text, and every depends source hash equals the pin in the checkout's
contrib/depends/packages/*.mk; otherwise "incomplete" with the reasons, in the manifest and
README. draft-release.sh refuses an incomplete set; this script still writes it, so every run
shows the list for review.
Per-platform manifest zephyrd-<version string>-<platform>.manifest.json
(release-target.schema.json). SHA256SUMS lists the archives and the manifests, never itself.
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
import zipfile

SCHEMA = "myzephyr/daemon-release-target/1"
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
    "windows-x86_64": ("x86_64-w64-mingw32", "zephyrd.exe", "zip"),
}
# what this run proved per platform: the jobs the package job needs, all of which succeeded
TESTED = {
    "linux-x86_64": [
        "built in the pinned Debian 11 builder (GCC 9; glibc symbol versions at most 2.29, no RPATH, no shared C++ runtime)",
        "unit tests built from the same commit: all enabled tests passed (reference count) on ubuntu-24.04",
        "--version and a strict offline start with clean shutdown on ubuntu-24.04 and in the Debian 11 builder userland (glibc 2.31)",
        "default public peer discovery from an empty data directory on ubuntu-24.04 (handshake and validated height increase)",
    ],
    "linux-aarch64": [
        "cross-built in the pinned builder (GCC 9; glibc symbol versions at most 2.29)",
        "on ubuntu-24.04-arm: --version, a strict offline start with clean shutdown and default public peer discovery",
        "a strict offline start in a runtime-only Debian 11 arm64 userland (glibc 2.31)",
    ],
    "macos-x86_64": [
        "cross-built in the pinned builder (minimum macOS 10.13, thin x86_64)",
        "on macos-15-intel: --version, a strict offline start with clean shutdown and default public peer discovery",
    ],
    "windows-x86_64": [
        "cross-built in the pinned builder (MinGW-w64, no MinGW runtime DLL)",
        "on windows-2022: --version, a strict offline start with clean shutdown and default public peer discovery",
    ],
}
NOT_TESTED = {
    "linux-x86_64": "other Linux distributions than the two userlands above",
    "linux-aarch64": "other AArch64 distributions",
    "macos-x86_64": "macOS 10.13 to 14 and Apple Silicon (Rosetta)",
    "windows-x86_64": "Windows 10 and other Windows Server versions",
}
REPLACE_NOTE = {
    "linux-x86_64": None, "linux-aarch64": None,
    "macos-x86_64": ("macOS: the binary is not notarized by Apple. After checking the hashes, remove the quarantine "
                     "attribute that a browser download sets: xattr -d com.apple.quarantine zephyrd"),
    "windows-x86_64": ("Windows: zephyrd.exe is not Authenticode-signed, like upstream's own builds; SmartScreen may "
                       "warn. After checking the hashes, unblock it (file Properties, Unblock) or choose More info, Run anyway."),
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
    used = sorted({r["owner"] for r in rows if (r["kind"] == "input" and r["detail"].startswith("used")) or r["kind"] == "header"})
    covered = {r["owner"] for r in rows if r["kind"] in ("license", "license-ref")}
    for o in used:
        if o not in covered:
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
        index.append(f"{rel}\n    owner {r['owner']}\n    from {r['detail']}\n    sha256 {r['sha256']}")
    status = "complete" if not reasons else "incomplete"
    head = [f"Licence texts of everything linked into {PLATFORMS[platform][1]} ({platform}), from the link inventory",
            "of its build (link-inventory.sh). Status: " + status + "."]
    if reasons:
        head += ["NOT ESTABLISHED (this archive must not be released until these are resolved):"] + [f"  - {x}" for x in reasons]
    with open(os.path.join(tdir, "INDEX.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(head) + "\n\n" + "\n\n".join(index) + "\n")
    return status, entries, reasons


def readme(tm):
    p = tm["platform"]
    b = tm["binary"]
    own = "\n".join(f"    {c['commit'][:12]} {c['subject']}" for c in tm["source"]["own_commits"])
    lic = tm["third_party_licenses"]
    lines = [
        f"zephyrd {tm['version_string']} for {p} (personal build)",
        "",
        "This is a personal build of the Zephyr daemon (zephyrd) by the maintainer of",
        f"{tm['workflow']['server_url']}/{tm['workflow']['repository']}. It is not part of zephyr-backports and not an",
        "official Zephyr release.",
        "",
        "SOURCE",
        f"  Commit {tm['source']['commit']}; the binary reports {tm['version_string']}.",
        f"  Base: the signed zephyr-backports tag {tm['base']['tag']} = {tm['base']['commit']}",
        f"  (tag signer {tm['base']['signer_primary_fingerprint']}).",
        f"  Own commits above the base, each signed by {tm['own_commit_signer_primary_fingerprint']}:",
        own,
        f"  Built by {tm['run_url']}",
        f"  ({tm['workflow']['event_name']} on {tm['workflow']['ref']}, run {tm['workflow']['run_id']} attempt {tm['workflow']['run_attempt']}).",
        "",
        "VERIFY",
        "  1. gpg --verify SHA256SUMS.asc SHA256SUMS",
        f"     (maintainer key, primary fingerprint {tm['own_commit_signer_primary_fingerprint']}; see the repository README)",
        "  2. sha256sum -c --ignore-missing SHA256SUMS",
        f"  3. The binary in this archive has SHA256 {b['sha256']} ({tm['archive']['name']}",
        f"     names it in {tm['manifest_name']}); {b['name']} --version prints a line ending in ({tm['version_string']}).",
        "",
        "REPLACE AN UPSTREAM ZEPHYRD",
        "  1. Stop the running daemon (its exit command or its service) and wait until it has exited.",
        "  2. Keep the data directory as it is.",
        f"  3. Replace the {b['name']} binary with this one; keep the old one.",
        "  4. Start it with the same paths, ports and options as before.",
        "  The RPC interface, the P2P protocol and the database format are upstream's; the version number stays 2.3.0.",
        "",
        "WHAT THE HOSTED RUNNERS OF THIS RUN TESTED",
    ] + [f"  - {t}" for t in tm["tested"]] + [
        f"  Not tested by this run: {tm['not_tested']}. A full mainnet sync and a database resume",
        "  test of the Linux x86_64 binary are separate steps before a release (see the release notes).",
    ]
    if REPLACE_NOTE[p]:
        lines += ["", "NOTE", "  " + REPLACE_NOTE[p]]
    lines += ["", "LICENCES",
              "  LICENSE is the source tree's licence; THIRD-PARTY-LICENSES/ holds the texts of everything linked",
              f"  into {b['name']}, listed in THIRD-PARTY-LICENSES/INDEX.txt. Status: {lic['status']}."]
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
        fail(f"need all four platforms, got {sorted(arts)}")
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
    own = [{"commit": c["commit"], "subject": git(checkout, "log", "-1", "--format=%s", c["commit"]), "paths": c["paths"]}
           for c in first["source"]["own_commits"]]

    os.makedirs(a.out)
    work = tempfile.mkdtemp(prefix="release-set-")
    old_umask = os.umask(0o022)
    try:
        sums = {}
        for plat in sorted(PLATFORMS):
            target, binary, fmt = PLATFORMS[plat]
            m, art = mans[plat], arts[plat]
            top = f"zephyrd-{vs}-{plat}"
            stage = os.path.join(work, plat, top)
            os.makedirs(stage)
            shutil.copyfile(os.path.join(art, binary), os.path.join(stage, binary))
            os.chmod(os.path.join(stage, binary), 0o755)
            shutil.copyfile(os.path.join(checkout, "LICENSE"), os.path.join(stage, "LICENSE"))
            status, entries, reasons = licences(plat, art, m, checkout, stage)
            archive = f"{top}.{fmt}"
            mname = f"{top}.manifest.json"
            tm = {
                "schema": SCHEMA, "platform": plat, "target": target, "version_string": vs,
                "archive": {"name": archive, "format": fmt, "top_directory": top, "sha256": None, "size": None},
                "binary": {"name": binary, "path": f"{top}/{binary}", "sha256": m["artifact"]["sha256"], "size": m["artifact"]["size"]},
                "build_manifest_sha256": sha256(os.path.join(art, "manifest.json")), "build_manifest": m,
                "source": {"commit": commit, "commit_time": epoch, "own_commits": own},
                "base": m["base"], "own_commit_signer_primary_fingerprint": m["own_commit_signer_primary_fingerprint"],
                "workflow": m["workflow"], "run_url": a.run_url,
                "tested": TESTED[plat], "not_tested": NOT_TESTED[plat],
                "third_party_licenses": {"status": status, "reasons": reasons, "entries": entries},
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
            sums[archive], sums[mname] = tm["archive"]["sha256"], sha256(os.path.join(a.out, mname))
            print(f"{archive}  {tm['archive']['sha256']}  licences {status}" + (f" ({len(reasons)} open)" if reasons else ""))
            for r in reasons:
                print(f"::warning title=licences {plat}::not established: {r}")
        listed = sorted(n for n in os.listdir(a.out))
        if listed != sorted(sums):
            fail(f"unexpected files in {a.out}: {listed}")
        with open(os.path.join(a.out, "SHA256SUMS"), "w", encoding="utf-8") as f:
            f.write("".join(f"{sums[n]}  {n}\n" for n in sorted(sums)))
    finally:
        os.umask(old_umask)
        shutil.rmtree(work, ignore_errors=True)
    print(open(os.path.join(a.out, "SHA256SUMS")).read(), end="")


if __name__ == "__main__":
    main()
