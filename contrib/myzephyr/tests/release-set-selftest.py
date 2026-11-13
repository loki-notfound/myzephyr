#!/usr/bin/env python3
"""Self-test of release/make-release-set.py with synthetic artifacts (placeholder binaries,
invented licence texts and a small git checkout made here). Not a real release set.

  release-set-selftest.py <work-dir>      (<work-dir> must not exist)

Valid set: five archives and five manifests, SHA256SUMS over exactly the five archives,
named after contrib/myzephyr/RELEASE of the checkout; fixed layout
zephyrd-<release>-<platform>/ with the binary (0755), LICENSE,
THIRD-PARTY-LICENSES/ and README.txt; tar members with time SOURCE_DATE_EPOCH, owner 0:0;
gzip without name and time; zip entries with fixed time and modes; every manifest valid
against release-target.schema.json; licences complete; two runs give byte-identical sets.
Then one change per case: an unresolved inventory line, no inventory, a used owner without a
text, a depends source hash other than the pin, a re-link that was not identical (each:
written but "incomplete"); a version "release", a target disagreeing on the commit or the
run, a binary not matching its manifest, an inventory not matching the manifest, a licence
text not matching its inventory hash (each: refused, exit 1). A licence text taken from a
source header (kind tree-header) is accepted, "complete", and marked in INDEX.txt.
Round 16: inputs made in the build tree ("build:<dir>") need no text, the owners of linked
objects' sources ("compiled" rows) do; a source-header statement naming LICENSE_1_0.txt gets
an INDEX.txt note pointing at the text of that name. Copyleft packages: the artifacts link
synthetic readline (Linux and macOS), libusb (Linux) and zeromq (all five); the manifest and
README.txt of each platform name exactly the linked ones with version, licence (as its text
names it), URL and pinned hash from the checkout's recipe. Refused: RELEASE missing or not one
line v<x.y.z>-sec.<n>-my.<n>; a linked copyleft package whose recipe names no URL.
Round 17 (owner decision: a compiled-in file without a licence statement is shipped as upstream
ships it): "statement ... none" rows, for a directory where no file states anything and for one
where another file does, leave the set "complete" and are not named in INDEX.txt, README.txt or
the manifest; a directory with a statement row but no text, and the blockers above, still make
it "incomplete".
"""
import copy
import gzip
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import zipfile

here = os.path.dirname(os.path.abspath(__file__))
tool = os.path.join(os.path.dirname(here), "release", "make-release-set.py")
work = os.path.abspath(sys.argv[1]) if len(sys.argv) == 2 else sys.exit(__doc__)
if os.path.lexists(work):
    sys.exit(f"{work} exists")
os.makedirs(work)
results = []
PLAT = {"linux-x86_64": ("x86_64-unknown-linux-gnu", "zephyrd"), "linux-aarch64": ("aarch64-linux-gnu", "zephyrd"),
        "macos-x86_64": ("x86_64-apple-darwin", "zephyrd"), "macos-arm64": ("aarch64-apple-darwin", "zephyrd"),
        "windows-x86_64": ("x86_64-w64-mingw32", "zephyrd.exe")}


def record(name, ok, detail=""):
    results.append({"case": name, "ok": bool(ok), "detail": detail})
    print(f"{'ok  ' if ok else 'FAIL'} {name}" + ("" if ok else f" -- {detail}"))


def sha(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def sh(*a, cwd=None):
    return subprocess.run(a, cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


# a checkout: LICENSE, a depends recipe with a pinned hash, a base commit and two own commits
co = os.path.join(work, "checkout")
os.makedirs(os.path.join(co, "contrib", "depends", "packages"))
genv = ["-c", "core.hooksPath=/dev/null", "-c", "commit.gpgsign=false", "-c", "user.name=selftest", "-c", "user.email=selftest@example.invalid"]
open(os.path.join(co, "LICENSE"), "w").write("tree licence (synthetic)\n")
src_tarball = b"synthetic dep source"
open(os.path.join(co, "contrib", "depends", "packages", "dep.mk"), "w").write(
    f"$(package)_version=1.0\n$(package)_sha256_hash={hashlib.sha256(src_tarball).hexdigest()}\n")
# packages whose source goes with the release: file, licence file, platforms linking it (as in the real builds)
SRC = {"readline": ("readline-8.0.tar.gz", "COPYING", ("linux-x86_64", "linux-aarch64", "macos-x86_64", "macos-arm64"), "GNU readline"),
       "libusb": ("libusb-1.0.27.tar.bz2", "COPYING", ("linux-x86_64", "linux-aarch64"), "libusb"),
       "zeromq": ("zeromq-4.3.5.tar.gz", "LICENSE", ("linux-x86_64", "linux-aarch64", "macos-x86_64", "macos-arm64", "windows-x86_64"),
                  "ZeroMQ")}
TB = {pkg: f"synthetic {pkg} source tarball, not the real one\n".encode() for pkg in SRC}
PIN = {pkg: hashlib.sha256(b).hexdigest() for pkg, b in TB.items()}
RL_PIN = PIN["readline"]
for pkg in SRC:
    open(os.path.join(co, "contrib", "depends", "packages", f"{pkg}.mk"), "w").write(
        f"package={pkg}\n$(package)_version=1.0\n$(package)_download_path=https://example.invalid/{pkg}/v$($(package)_version)/\n"
        f"$(package)_file_name=$(package)-$($(package)_version).tar.gz\n$(package)_sha256_hash={PIN[pkg]}\n")
RELEASE = "v2.3.0-sec.2-my.9"
os.makedirs(os.path.join(co, "contrib", "myzephyr"))
open(os.path.join(co, "contrib", "myzephyr", "RELEASE"), "w").write(RELEASE + "\n")
sh("git", "init", "-q", co)
sh("git", "-C", co, *genv, "add", "-A"); sh("git", "-C", co, *genv, "commit", "-q", "-m", "base")
own = []
for subj in ("Add the first own change", "Add the second own change"):
    open(os.path.join(co, "own.txt"), "a").write(subj + "\n")
    sh("git", "-C", co, *genv, "add", "own.txt"); sh("git", "-C", co, *genv, "commit", "-q", "-m", subj)
    own.append({"commit": sh("git", "-C", co, "rev-parse", "HEAD"), "paths": ["own.txt"]})
commit = own[-1]["commit"]
ctime = int(sh("git", "-C", co, "log", "-1", "--format=%ct"))
version = f"2.3.0-{commit[:9]}"


def make_artifact(d, plat):
    target, binary = PLAT[plat]
    logs = os.path.join(d, "build-logs")
    os.makedirs(os.path.join(logs, "licenses", "depends", "dep"))
    os.makedirs(os.path.join(logs, "licenses", "tree", "external", "ext"))
    open(os.path.join(d, binary), "wb").write(f"placeholder {plat} binary, not a program\n".encode())
    texts = {"licenses/depends/dep/COPYING": "dep licence (synthetic)\n", "licenses/tree/LICENSE": "tree licence (synthetic)\n",
             "licenses/tree/external/ext/LICENSE": "ext licence (synthetic)\n"}
    for rel, t in texts.items():
        open(os.path.join(logs, rel), "w").write(t)
    h = {rel: sha(os.path.join(logs, rel)) for rel in texts}
    rows = [("status", "relink_exit", "-", "-", "0"), ("status", "relink_identical", "-", "-", "yes"),
            ("input", "/src/build/release/src/daemon/CMakeFiles/daemon.dir/main.cpp.o", "tree:src/daemon", "0" * 64, "used"),
            ("input", "/src/build/release/external/ext/libext.a", "tree:external/ext", "1" * 64, "used members=3"),
            ("input", f"/src/contrib/depends/{target}/lib/libdep.a", "depends:dep", "2" * 64, "used members=1"),
            ("input", "/usr/lib/libunused.a", "deb:unused", "3" * 64, "unused"),
            ("license", "licenses/tree/LICENSE", "tree:src/daemon", h["licenses/tree/LICENSE"], "tree path=LICENSE"),
            ("license", "licenses/tree/external/ext/LICENSE", "tree:external/ext", h["licenses/tree/external/ext/LICENSE"], "tree path=external/ext/LICENSE"),
            ("license", "licenses/depends/dep/COPYING", "depends:dep", h["licenses/depends/dep/COPYING"],
             f"depends source=dep-1.0.tar.gz source_sha256={hashlib.sha256(src_tarball).hexdigest()} member=dep-1.0/COPYING"),
            ("input", "/src/build/release/src/crypto/wallet/libwallet-crypto.a", "build:src/crypto/wallet", "6" * 64, "used members=1"),
            ("compiled", "/src/build/release/src/crypto/wallet/libwallet-crypto.a(x.c.o)", "tree:external/ext", "7" * 64,
             "source=external/ext/x.c object=build/release/x/CMakeFiles/x.dir/x.c.o")]
    for pkg, (fname, lname, plats, _) in SRC.items():
        if plat not in plats:
            continue
        os.makedirs(os.path.join(logs, "licenses", "depends", pkg))
        open(os.path.join(logs, "licenses", "depends", pkg, lname), "w").write(f"\n   {pkg.upper()} LICENCE (synthetic)\n   Version 9\ntext\n")
        top = fname.split(".tar.")[0]
        rows += [("input", f"/src/contrib/depends/{target}/lib/lib{pkg}.a", f"depends:{pkg}", "8" * 64, "used members=2"),
                 ("license", f"licenses/depends/{pkg}/{lname}", f"depends:{pkg}", sha(os.path.join(logs, "licenses", "depends", pkg, lname)),
                  f"depends source={fname} source_sha256={PIN[pkg]} member={top}/{lname}")]
    write_inventory(d, rows)
    m = {"schema": "synthetic", "artifact": {"name": binary, "target": target, "expected_version": version,
                                              "sha256": sha(os.path.join(d, binary)), "size": os.path.getsize(os.path.join(d, binary))},
         "source": {"commit": commit, "commit_time": ctime, "own_commits": own},
         "base": {"tag": "v2.3.0-sec.2", "commit": "8c6a120256b4bd887d6e7167d929d76e3507e0e5",
                  "signer_primary_fingerprint": "FB3994F0997CA6F043D724919EFF03F527D240A1"},
         "own_commit_signer_primary_fingerprint": "31DA39AB43E0CA67F1F3A661BA2AFF22DF8A4A13",
         "workflow": {"repository": "example/myzephyr", "ref": "refs/heads/my/v2.3.0", "sha": commit, "event_name": "push",
                      "run_id": "5", "run_attempt": "1", "server_url": "https://github.com", "pull_request": None},
         "build": {"link_inventory_sha256": sha(os.path.join(logs, "link-inventory.tsv"))}}
    save_manifest(d, m)


def write_inventory(d, rows):
    p = os.path.join(d, "build-logs", "link-inventory.tsv")
    open(p, "w").write("kind\tpath\towner\tsha256\tdetail\n" + "".join("\t".join(r) + "\n" for r in rows))


def save_manifest(d, m):
    json.dump(m, open(os.path.join(d, "manifest.json"), "w"), indent=2)


def load_manifest(d):
    return json.load(open(os.path.join(d, "manifest.json")))


def base_set(name):
    d = os.path.join(work, name)
    for plat in PLAT:
        os.makedirs(os.path.join(d, plat))
        make_artifact(os.path.join(d, plat), plat)
    return d


def run(name, d, checkout=co):
    out = os.path.join(work, name + "-out")
    p = subprocess.run([sys.executable, "-I", tool, "--checkout", checkout, "--out", out,
                        "--run-url", "https://github.com/example/myzephyr/actions/runs/5/attempts/1",
                        *[f"--artifact={plat}={os.path.join(d, plat)}" for plat in PLAT]], capture_output=True, text=True)
    return p, out


vs = "v" + version
d = base_set("valid")
p, out = run("valid", d)
record("valid set written", p.returncode == 0, p.stderr[-400:])
names = sorted(os.listdir(out)) if os.path.isdir(out) else []
archives = sorted(f"zephyrd-{RELEASE}-{pl}.{'zip' if pl.startswith('windows') else 'tar.gz'}" for pl in PLAT)
want = sorted(archives + [f"zephyrd-{RELEASE}-{pl}.manifest.json" for pl in PLAT] + ["SHA256SUMS"])
record("exactly five archives named after RELEASE, five manifests and SHA256SUMS", names == want, names)
if names == want:
    sums = [l.split("  ") for l in open(os.path.join(out, "SHA256SUMS")).read().splitlines()]
    record("SHA256SUMS lists exactly the five archives, hashes match",
           sorted(n for _, n in sums) == archives and all(sha(os.path.join(out, n)) == h for h, n in sums))
    for pl, (target, binary) in PLAT.items():
        top = f"zephyrd-{RELEASE}-{pl}"
        man = json.load(open(os.path.join(out, top + ".manifest.json")))
        if pl.startswith("windows"):
            z = zipfile.ZipFile(os.path.join(out, top + ".zip"))
            members = sorted(i.filename.rstrip("/") for i in z.infolist())
            times = {i.date_time for i in z.infolist()}
            binfo = z.getinfo(f"{top}/{binary}")
            bin_ok = hashlib.sha256(z.read(binfo)).hexdigest() == man["binary"]["sha256"] and (binfo.external_attr >> 16) & 0o777 == 0o755
            meta_ok = len(times) == 1
            rd = z.read(f"{top}/README.txt").decode()
        else:
            raw = open(os.path.join(out, top + ".tar.gz"), "rb").read()
            gz_ok = raw[4:8] == b"\0\0\0\0" and not (raw[3] & 0x08)   # MTIME 0, no FNAME
            t = tarfile.open(os.path.join(out, top + ".tar.gz"))
            members = sorted(m.name for m in t.getmembers())
            bm = t.getmember(f"{top}/{binary}")
            bin_ok = hashlib.sha256(t.extractfile(bm).read()).hexdigest() == man["binary"]["sha256"] and bm.mode & 0o777 == 0o755
            meta_ok = gz_ok and all(m.mtime == ctime and m.uid == 0 and m.gid == 0 and m.uname == "" for m in t.getmembers())
            rd = t.extractfile(f"{top}/README.txt").read().decode()
        layout = {top, f"{top}/{binary}", f"{top}/LICENSE", f"{top}/README.txt", f"{top}/THIRD-PARTY-LICENSES",
                  f"{top}/THIRD-PARTY-LICENSES/INDEX.txt"}
        record(f"{pl}: fixed layout with binary, LICENSE, THIRD-PARTY-LICENSES, README.txt", layout <= set(members), members)
        record(f"{pl}: unpacked binary is the manifest's, mode 0755", bin_ok)
        record(f"{pl}: fixed archive metadata (time, owner, no gzip name or time)", meta_ok)
        linked = [pkg for pkg, v in SRC.items() if pl in v[2]]
        record(f"{pl}: licences complete, {3 + len(linked)} texts (build:<dir> needs none, compiled owner covered)",
               man["third_party_licenses"]["status"] == "complete"
               and len(man["third_party_licenses"]["entries"]) == 3 + len(linked), man["third_party_licenses"])
        cl = {c["package"]: c for c in man["copyleft"]}
        record(f"{pl}: manifest names exactly the copyleft packages {', '.join(linked)}", sorted(cl) == sorted(linked), cl)
        for pkg in linked:
            c, url = cl.get(pkg, {}), f"https://example.invalid/{pkg}/v1.0/{pkg}-1.0.tar.gz"
            record(f"{pl}: manifest and README name {pkg}'s version, licence, URL and pin", c.get("version") == "1.0"
                   and c.get("licence") == f"{pkg.upper()} LICENCE (synthetic) Version 9" and c.get("url") == url
                   and c.get("pinned_sha256") == PIN[pkg]
                   and f"{SRC[pkg][3]} 1.0, {pkg.upper()} LICENCE (synthetic) Version 9\n      {url}\n      SHA256 {PIN[pkg]}" in rd,
                   (c, rd[-700:]))
        for pkg in set(SRC) - set(linked):
            record(f"{pl}: {pkg} not linked, README does not name it", f"/{pkg}-1.0.tar.gz" not in rd)
        record(f"{pl}: manifest names release, commit, run, version and own commit subjects",
               man["release"] == RELEASE and man["source"]["commit"] == commit and man["workflow"]["run_id"] == "5"
               and man["version_string"] == vs
               and [c["subject"] for c in man["source"]["own_commits"]] == ["Add the first own change", "Add the second own change"])
        record(f"{pl}: README names the release, the commit, the version string and the binary hash, not the manifest or the run",
               rd.startswith(f"zephyrd {RELEASE} for ") and commit in rd and f"reports {vs}." in rd and man["binary"]["sha256"] in rd
               and "manifest" not in rd and "runs/5" not in rd, rd[:400])
    readme = tarfile.open(os.path.join(out, f"zephyrd-{RELEASE}-macos-x86_64.tar.gz")).extractfile(f"zephyrd-{RELEASE}-macos-x86_64/README.txt").read().decode()
    record("README: first person, not zephyr-backports, verify, replace, build note, quarantine note",
           all(x in readme for x in ("My personal build", "not part of zephyr-backports", "gpg --verify SHA256SUMS.asc",
                                     "sha256sum -c SHA256SUMS", "keep its data directory", "without hardware-wallet support",
                                     "com.apple.quarantine", "Status: complete")), readme[:300])
    p2, out2 = run("valid-again", d)
    record("a second run gives a byte-identical set", p2.returncode == 0 and all(
        sha(os.path.join(out, n)) == sha(os.path.join(out2, n)) for n in want), p2.stderr[-300:])


def variant(name, fn, want_exit, frag, want_status=None):
    dv = base_set(name)
    fn(dv)
    p, outv = run(name, dv)
    ok = p.returncode == want_exit and frag in (p.stdout + p.stderr)
    if want_status:
        m = json.load(open(os.path.join(outv, f"zephyrd-{RELEASE}-linux-x86_64.manifest.json"))) if p.returncode == 0 else {}
        lic = m.get("third_party_licenses", {})
        ok = ok and lic.get("status") == want_status and any(frag in r for r in lic.get("reasons", []))
    record(f"{name}: exit {want_exit}" + (f", licences {want_status}" if want_status else ""), ok, (p.stdout + p.stderr)[-300:])


def edit_inv(dv, plat, fn):
    pd = os.path.join(dv, plat)
    path = os.path.join(pd, "build-logs", "link-inventory.tsv")
    rows = [l.split("\t") for l in open(path).read().splitlines()[1:]]
    write_inventory(pd, fn(rows))
    m = load_manifest(pd)
    m["build"]["link_inventory_sha256"] = sha(path)
    save_manifest(pd, m)


variant("unresolved-line", lambda dv: edit_inv(dv, "linux-x86_64", lambda r: r + [["status", "unresolved", "unknown", "-", "owner not found"]]),
        0, "unresolved: unknown: owner not found", "incomplete")
variant("no-inventory", lambda dv: (os.remove(os.path.join(dv, "linux-x86_64", "build-logs", "link-inventory.tsv")),
                                    save_manifest(os.path.join(dv, "linux-x86_64"), dict(load_manifest(os.path.join(dv, "linux-x86_64")), build={"link_inventory_sha256": None}))),
        0, "no link inventory", "incomplete")
variant("used-owner-without-text", lambda dv: edit_inv(dv, "linux-x86_64", lambda r: r + [["input", "/src/x/libnew.a", "tree:external/new", "4" * 64, "used members=1"]]),
        0, "no licence text for tree:external/new", "incomplete")
variant("depends-hash-not-pinned", lambda dv: edit_inv(dv, "linux-x86_64", lambda r: [x if x[0] != "license" or x[2] != "depends:dep" else x[:4] + [x[4].replace("source_sha256=", "source_sha256=0")[:-1]] for x in r]),
        0, "is not the pinned", "incomplete")
variant("relink-not-identical", lambda dv: edit_inv(dv, "linux-x86_64", lambda r: [x if x[1] != "relink_identical" else x[:4] + ["no"] for x in r]),
        0, "traced re-link not identical", "incomplete")


def all_manifests(fn):
    def run_(dv):
        for plat in PLAT:
            m = load_manifest(os.path.join(dv, plat))
            fn(m)
            save_manifest(os.path.join(dv, plat), m)
    return run_


variant("release-version", all_manifests(lambda m: m["artifact"].__setitem__("expected_version", "2.3.0-release")), 1, "never packaged")


def one(plat, fn):
    def run_(dv):
        m = load_manifest(os.path.join(dv, plat))
        fn(m)
        save_manifest(os.path.join(dv, plat), m)
    return run_


variant("other-commit", one("macos-x86_64", lambda m: m["source"].__setitem__("commit", "f" * 40)), 1, "macos-x86_64: commit")
variant("other-run", one("windows-x86_64", lambda m: m["workflow"].__setitem__("run_id", "6")), 1, "windows-x86_64: run")
variant("binary-changed", lambda dv: open(os.path.join(dv, "linux-aarch64", "zephyrd"), "ab").write(b"x"), 1, "binary does not match its manifest")
variant("inventory-not-in-manifest", lambda dv: open(os.path.join(dv, "linux-x86_64", "build-logs", "link-inventory.tsv"), "a").write("status\tx\t-\t-\ty\n"),
        1, "does not match the verified manifest")
def set_file(rel, content):
    def f(dv):
        p = os.path.join(co, rel)
        old = open(p).read() if os.path.exists(p) else None
        if content is None:
            os.remove(p)
        else:
            open(p, "w").write(content)
        RESTORE.append((p, old))
    return f


RESTORE = []


def variant_co(name, rel, content, frag):
    variant(name, set_file(rel, content), 1, frag)
    for p, old in RESTORE:
        open(p, "w").write(old)
    RESTORE.clear()


variant_co("release-file-missing", "contrib/myzephyr/RELEASE", None, "has no contrib/myzephyr/RELEASE")
variant_co("release-file-two-lines", "contrib/myzephyr/RELEASE", RELEASE + "\n" + RELEASE + "\n", "expected one line")
variant_co("release-file-not-a-release-name", "contrib/myzephyr/RELEASE", "v2.3.0-sec.2\n", "expected one line")
variant_co("copyleft-recipe-without-url", "contrib/depends/packages/zeromq.mk",
           f"package=zeromq\n$(package)_version=1.0\n$(package)_sha256_hash={PIN['zeromq']}\n", "names no version, URL and hash")

variant("licence-text-changed", lambda dv: open(os.path.join(dv, "linux-x86_64", "build-logs", "licenses", "depends", "dep", "COPYING"), "a").write("x"),
        1, "does not match its inventory hash")

# a licence text from a source header (R13-2): accepted, kind tree-header, marked in INDEX.txt
def header_text(dv):
    pd = os.path.join(dv, "linux-x86_64")
    rel = "licenses/tree-header/external/ext/ext.h.lines-1-3.txt"
    os.makedirs(os.path.join(pd, "build-logs", os.path.dirname(rel)))
    open(os.path.join(pd, "build-logs", rel), "w").write("/*\n * Licensed under the MIT License (synthetic)\n */\n")
    h = sha(os.path.join(pd, "build-logs", rel))
    edit_inv(dv, "linux-x86_64", lambda r: [x for x in r if not (x[0] == "license" and x[2] == "tree:external/ext")]
             + [["license", rel, "tree:external/ext", h,
                 "tree-header from=source-header file=external/ext/ext.h lines=1-3 file_sha256=" + "5" * 64]])


dv = base_set("tree-header")
header_text(dv)
p, outv = run("tree-header", dv)
mh = json.load(open(os.path.join(outv, f"zephyrd-{RELEASE}-linux-x86_64.manifest.json"))) if p.returncode == 0 else {}
lic = mh.get("third_party_licenses", {})
eh = [e for e in lic.get("entries", []) if e.get("owner") == "tree:external/ext"]
idx = ""
if p.returncode == 0:
    with tarfile.open(os.path.join(outv, f"zephyrd-{RELEASE}-linux-x86_64.tar.gz")) as tf:
        idx = tf.extractfile(f"zephyrd-{RELEASE}-linux-x86_64/THIRD-PARTY-LICENSES/INDEX.txt").read().decode()
record("licence text from a source header: accepted, kind tree-header, status complete, marked in INDEX.txt",
       p.returncode == 0 and lic.get("status") == "complete" and len(eh) == 1 and eh[0]["kind"] == "tree-header"
       and eh[0]["source"].get("from") == "source-header" and eh[0]["source"].get("lines") == "1-3"
       and "FROM SOURCE HEADER" in idx and "file=external/ext/ext.h lines=1-3" in idx, (p.stdout + p.stderr)[-300:])

# a source-header statement naming LICENSE_1_0.txt: INDEX.txt points at the depends text of that name
def boost_case(dv):
    pd = os.path.join(dv, "windows-x86_64")
    logs = os.path.join(pd, "build-logs")
    os.makedirs(os.path.join(logs, "licenses", "depends", "boost"))
    os.makedirs(os.path.join(logs, "licenses", "tree-header", "external", "boost", "archive"))
    open(os.path.join(logs, "licenses", "depends", "boost", "LICENSE_1_0.txt"), "w").write("Boost Software License (synthetic)\n")
    st = "licenses/tree-header/external/boost/archive/a.hpp.lines-4-7.txt"
    open(os.path.join(logs, st), "w").write("// Use, modification and distribution is subject to the Boost Software\n"
                                           "// License, Version 1.0. (See accompanying file LICENSE_1_0.txt or copy at\n")
    open(os.path.join(co, "contrib", "depends", "packages", "boost.mk"), "a").close()
    edit_inv(dv, "windows-x86_64", lambda r: r + [
        ["header", "/src/external/boost/archive", "tree:external/boost/archive", "-", "headers compiled into the linked objects"],
        ["license", st, "tree:external/boost/archive", sha(os.path.join(logs, st)),
         "tree-header from=source-header file=external/boost/archive/a.hpp lines=4-7 file_sha256=" + "9" * 64],
        ["license", "licenses/depends/boost/LICENSE_1_0.txt", "depends:boost", sha(os.path.join(logs, "licenses", "depends", "boost", "LICENSE_1_0.txt")),
         f"depends source=boost.tar.gz source_sha256={hashlib.sha256(src_tarball).hexdigest()} member=boost/LICENSE_1_0.txt"]])


dv = base_set("boost-note")
boost_case(dv)
open(os.path.join(co, "contrib", "depends", "packages", "boost.mk"), "w").write(
    f"$(package)_version=1\n$(package)_sha256_hash={hashlib.sha256(src_tarball).hexdigest()}\n")
p, outv = run("boost-note", dv)
idx = ""
if p.returncode == 0:
    with zipfile.ZipFile(os.path.join(outv, f"zephyrd-{RELEASE}-windows-x86_64.zip")) as zf:
        idx = zf.read(f"zephyrd-{RELEASE}-windows-x86_64/THIRD-PARTY-LICENSES/INDEX.txt").decode()
record("statement naming LICENSE_1_0.txt: INDEX.txt points at the text of that name (depends:boost)",
       p.returncode == 0 and "The statement names LICENSE_1_0.txt; a text of that name is in this archive:" in idx
       and "THIRD-PARTY-LICENSES/depends/boost/LICENSE_1_0.txt (owner depends:boost)" in idx, (p.stdout + p.stderr)[-300:] + idx[-600:])
os.remove(os.path.join(co, "contrib", "depends", "packages", "boost.mk"))

# compiled-in files without a licence statement (round 17): informational, not in the archive
NOSTAT = ("external/nostat/a.s", "external/mixed/config.h")


def no_statement(dv):
    pd = os.path.join(dv, "linux-x86_64")
    rel = "licenses/tree-header/external/mixed/mixed.cc.lines-1-3.txt"
    os.makedirs(os.path.join(pd, "build-logs", os.path.dirname(rel)))
    open(os.path.join(pd, "build-logs", rel), "w").write("/*\n * Licensed under the MIT License (synthetic)\n */\n")
    h = sha(os.path.join(pd, "build-logs", rel))
    edit_inv(dv, "linux-x86_64", lambda r: r + [
        ["compiled", "/src/build/release/x/libnostat.a(a.s.o)", "tree:external/nostat", "a" * 64, "source=external/nostat/a.s object=build/release/x/a.s.o"],
        ["statement", "external/nostat/a.s", "tree:external/nostat", "b" * 64, "none"],
        ["statement", "external/nostat/b.s", "tree:external/nostat", "c" * 64, "none"],
        ["header", "/src/external/mixed", "tree:external/mixed", "-", "files compiled into the linked objects"],
        ["statement", "external/mixed/mixed.cc", "tree:external/mixed", "d" * 64, f"lines=1-3 text_sha256={h}"],
        ["license", rel, "tree:external/mixed", h, "tree-header from=source-header file=external/mixed/mixed.cc lines=1-3 file_sha256=" + "d" * 64],
        ["statement", "external/mixed/config.h", "tree:external/mixed", "e" * 64, "none"]])


dv = base_set("no-statement")
no_statement(dv)
p, outv = run("no-statement", dv)
texts = ""
mlin = {}
if p.returncode == 0:
    top = f"zephyrd-{RELEASE}-linux-x86_64"
    with tarfile.open(os.path.join(outv, top + ".tar.gz")) as tf:
        texts = "".join(tf.extractfile(m).read().decode("utf-8", "replace") for m in tf.getmembers()
                        if m.isfile() and not m.name.endswith("/zephyrd"))
        names_ = [m.name for m in tf.getmembers()]
    mtext = open(os.path.join(outv, top + ".manifest.json")).read()
    mlin = json.loads(mtext)
record("files without a licence statement (a directory with none, one beside a stated file): exit 0, licences complete",
       p.returncode == 0 and mlin.get("third_party_licenses", {}).get("status") == "complete"
       and mlin["third_party_licenses"]["reasons"] == [], (p.stdout + p.stderr)[-300:])
record("files without a licence statement: not named in INDEX.txt, README.txt or the manifest; the stated file's text is",
       p.returncode == 0 and not any(x in texts or x in mtext for x in NOSTAT + ("nostat", "config.h"))
       and "Licensed under the MIT License (synthetic)" in texts and "external/mixed/mixed.cc" in texts,
       [x for x in NOSTAT if x in texts or x in mtext])
variant("statement-row-without-text", lambda dv: edit_inv(dv, "linux-x86_64", lambda r: r + [
            ["header", "/src/external/half", "tree:external/half", "-", "files compiled into the linked objects"],
            ["statement", "external/half/h.h", "tree:external/half", "f" * 64, "lines=1-2 text_sha256=" + "f" * 64],
            ["statement", "external/half/g.h", "tree:external/half", "f" * 64, "none"]]),
        0, "no licence text for tree:external/half", "incomplete")
variant("no-statement-but-unresolved-line", lambda dv: (no_statement(dv), edit_inv(dv, "linux-x86_64", lambda r: r + [
            ["status", "unresolved", "tree:external/nostat", "-", "no licence file in external/nostat or above it within its boundary, and no compiled-in file of external/nostat whose head could be read"]])),
        0, "unresolved: tree:external/nostat", "incomplete")

# compare-pr-run.py against a loopback stub of the REST API (synthetic runs and artifact names)
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
H1, H2 = "a" * 64, "b" * 64
API = {"mode": "ok"}


class Api(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        if API["mode"] == "error":
            self.send_response(403); self.end_headers(); return
        if self.path.startswith("/repos/example/myzephyr/actions/runs?"):
            body = {"workflow_runs": [
                {"id": 41, "path": ".github/workflows/daemon-release-baseline.yml", "head_sha": commit, "run_attempt": 1, "conclusion": "success"},
                {"id": 42, "path": ".github/workflows/build.yml", "head_sha": commit, "run_attempt": 1, "conclusion": "success"}]}
        elif self.path.startswith("/repos/example/myzephyr/actions/runs/41/artifacts"):
            body = {"artifacts": [{"name": f"binary-sha256-linux-x86_64-{H1}", "expired": False},
                                  {"name": f"binary-sha256-macos-x86_64-{H1}", "expired": False},
                                  {"name": f"zephyrd-linux-x86_64-{commit}", "expired": False}]}
        else:
            self.send_response(404); self.end_headers(); return
        b = json.dumps(body).encode()
        self.send_response(200); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)


srv = ThreadingHTTPServer(("127.0.0.1", 0), Api)
threading.Thread(target=srv.serve_forever, daemon=True).start()
cmp_tool = os.path.join(os.path.dirname(here), "release", "compare-pr-run.py")


def compare_run(name):
    summ = os.path.join(work, name + ".md")
    p = subprocess.run([sys.executable, "-I", cmp_tool, "--repository", "example/myzephyr", "--commit", commit, "--run-id", "50",
                        "--sums", f"linux-x86_64={H1}", f"macos-x86_64={H2}", f"windows-x86_64={H1}", "--summary", summ,
                        "--api", f"http://127.0.0.1:{srv.server_address[1]}"], capture_output=True, text=True)
    return p, open(summ).read() if os.path.exists(summ) else ""


p, md = compare_run("compare-ok")
record("compare: equal, different and missing hashes reported; other workflows ignored; exit 0",
       p.returncode == 0 and f"| linux-x86_64 | `{H1}` | `{H1}` | yes |" in md and f"| macos-x86_64 | `{H2}` | `{H1}` | **no** |" in md
       and "| windows-x86_64 |" in md and "not available |" in md and "run 42" not in md, md)
API["mode"] = "error"
p, md = compare_run("compare-error")
record("compare: API refusal is 'not available', still exit 0", p.returncode == 0 and "Not available: HTTPError" in md, md)
srv.shutdown()

json.dump(results, open(os.path.join(work, "results.json"), "w"), indent=2)
bad = [r for r in results if not r["ok"]]
print(f"{len(results) - len(bad)}/{len(results)} cases as intended (synthetic artifacts; not a real release set)")
sys.exit(1 if bad else 0)
