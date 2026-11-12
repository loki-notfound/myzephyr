#!/usr/bin/env python3
"""Self-test of release/make-release-set.py with synthetic artifacts (placeholder binaries,
invented licence texts and a small git checkout made here). Not a real release set.

  release-set-selftest.py <work-dir>      (<work-dir> must not exist)

Valid set: five archives and five manifests, SHA256SUMS over exactly those ten files,
fixed layout zephyrd-<version>-<platform>/ with the binary (0755), LICENSE,
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
an INDEX.txt note pointing at the text of that name. Source tarballs (owner decisions: GNU
readline, libusb, ZeroMQ): the artifacts link synthetic depends packages as the real builds do
(readline on Linux and macOS, libusb on Linux, zeromq on all five) and carry their synthetic
source tarballs; the set holds each once as a flat file, in SHA256SUMS, in the manifests and
README.txt files of the platforms that link it, not in the others'. Per package: present;
linked without the tarball, a tarball whose hash is not the pin, no source-tarball row (each
refused); linked nowhere (no tarball in the set, accepted).
Round 17 (owner decision: a compiled-in file without a licence statement is shipped as upstream
ships it): "statement ... none" rows, for a directory where no file states anything and for one
where another file does, leave the set "complete" and are not named in INDEX.txt, README.txt or
the manifest; a directory with a statement row but no text, and the blockers above, still make
it "incomplete".
Round 21 (owner decision 2026-11-12: the macOS arm64 start test is optional, two legs on
macos-15 and macos-26): native-start.py classify on the real job record of run 43297105618
attempt 1 (runner not acquired) and on records derived from that run's real macOS x86_64 record
(renamed to an arm64 leg): passed; a start step failed or cancelled (failed); a failure before
the first start step, skipped, not completed at the end of the wait (not-run). Two legs: neither
ran (not-run with both reasons), one passed with the other not run (passed, either order), both
passed, one passed and one failed (failed). native-start.py wait against a loopback API stub,
one limit for both legs: both stay queued (not-run within the limit), one passes and the other
stays queued (passed at the limit), both complete (before the limit), an API that always refuses
(not-run), a missing leg (exit 1). make-release-set.py: each passed leg listed as tested with its
runner and job, a leg that did not run beside a passed one gets a line with its reason, neither
ran says "not started natively in this run" with both reasons, a failed leg is written as
"NATIVE START FAILED ... must not be released" with a warning; no other platform carries
native_start; a malformed outcome or none is refused.
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
                  "ZeroMQ (libzmq)")}
TB = {pkg: f"synthetic {pkg} source tarball, not the real one\n".encode() for pkg in SRC}
PIN = {pkg: hashlib.sha256(b).hexdigest() for pkg, b in TB.items()}
RL_PIN = PIN["readline"]
for pkg in SRC:
    open(os.path.join(co, "contrib", "depends", "packages", f"{pkg}.mk"), "w").write(
        f"package={pkg}\n$(package)_version=1\n$(package)_sha256_hash={PIN[pkg]}\n")
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
        os.makedirs(os.path.join(logs, "depends-sources"), exist_ok=True)
        open(os.path.join(logs, "licenses", "depends", pkg, lname), "w").write(f"{pkg} licence (synthetic)\n")
        open(os.path.join(logs, "depends-sources", fname), "wb").write(TB[pkg])
        top = fname.split(".tar.")[0]
        rows += [("input", f"/src/contrib/depends/{target}/lib/lib{pkg}.a", f"depends:{pkg}", "8" * 64, "used members=2"),
                 ("license", f"licenses/depends/{pkg}/{lname}", f"depends:{pkg}", sha(os.path.join(logs, "licenses", "depends", pkg, lname)),
                  f"depends source={fname} source_sha256={PIN[pkg]} member={top}/{lname}"),
                 ("source-tarball", f"depends-sources/{fname}", f"depends:{pkg}", PIN[pkg],
                  f"depends source={fname} source_sha256={PIN[pkg]} stamp=.stamp_fetched-{pkg}-{fname}.hash")]
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


# round 21: outcomes of the optional macOS arm64 start test (two legs), made by native-start.py classify
ns_tool = os.path.join(os.path.dirname(here), "release", "native-start.py")
fx = os.path.join(here, "native-start-fixture")
LEG = {"macos-15": "native runtime (aarch64-apple-darwin on macos-15)", "macos-26": "native runtime (aarch64-apple-darwin on macos-26)"}
START = ("Version output of the verified binary", "Strict offline start with clean shutdown and no listener left",
         "Default discovery from an empty directory (no peer options)")
REAL = json.load(open(os.path.join(fx, "run-43297105618-attempt-1-macos-arm64.json")))


def not_acquired(label, **over):
    """The real record of run 43297105618 attempt 1 (runner not acquired), for the leg of label."""
    return dict(REAL, name=LEG[label], labels=[label], **over)


def arm_job(label="macos-15", **over):
    """The real macOS x86_64 job record of run 43297105618 attempt 1, renamed to the arm64 leg of label."""
    j = json.load(open(os.path.join(fx, "run-43297105618-attempt-1-macos-x86_64.json")))
    j.update(name=LEG[label], labels=[label], id=j["id"] + (0 if label == "macos-15" else 1))
    steps = over.pop("steps", {})
    for st in j["steps"]:
        if st["name"] in steps:
            st["conclusion"] = steps[st["name"]]
    j.update(over)
    return j


def classify(name, jobs, limit_reached=False):
    of = os.path.join(work, f"native-{name}.json")
    args = [sys.executable, "-I", ns_tool, "classify", "--out", of] + (["--limit-reached"] if limit_reached else [])
    for i, job in enumerate(jobs):
        jf = os.path.join(work, f"job-{name}-{i}.json")
        json.dump(job, open(jf, "w"))
        args += ["--job", jf]
    p = subprocess.run(args, capture_output=True, text=True)
    return (json.load(open(of)) if p.returncode == 0 else {"status": f"exit {p.returncode}", "reason": p.stderr, "legs": []}), of


NS_PASSED = classify("passed", [arm_job("macos-15"), not_acquired("macos-26")])[1]


def run(name, d, checkout=co, native=None):
    out = os.path.join(work, name + "-out")
    nat = [] if native == "none" else [f"--native-start=macos-arm64={native or NS_PASSED}"]
    p = subprocess.run([sys.executable, "-I", tool, "--checkout", checkout, "--out", out,
                        "--run-url", "https://github.com/example/myzephyr/actions/runs/5/attempts/1",
                        *[f"--artifact={plat}={os.path.join(d, plat)}" for plat in PLAT], *nat], capture_output=True, text=True)
    return p, out


vs = "v" + version
d = base_set("valid")
p, out = run("valid", d)
record("valid set written", p.returncode == 0, p.stderr[-400:])
names = sorted(os.listdir(out)) if os.path.isdir(out) else []
want = sorted([f"zephyrd-{vs}-{pl}.{'zip' if pl.startswith('windows') else 'tar.gz'}" for pl in PLAT] +
              [f"zephyrd-{vs}-{pl}.manifest.json" for pl in PLAT] + ["SHA256SUMS"] + [v[0] for v in SRC.values()])
record("exactly five archives, five manifests, the three source tarballs and SHA256SUMS", names == want, names)
if names == want:
    sums = [l.split("  ") for l in open(os.path.join(out, "SHA256SUMS")).read().splitlines()]
    for pkg, (fname, _, _, _) in SRC.items():
        record(f"{pkg} source tarball: the same bytes as the build carried (= the pin), once", sha(os.path.join(out, fname)) == PIN[pkg])
    record("SHA256SUMS lists the eleven files, not itself, hashes match",
           sorted(n for _, n in sums) == sorted(n for n in want if n != "SHA256SUMS")
           and all(sha(os.path.join(out, n)) == h for h, n in sums))
    for pl, (target, binary) in PLAT.items():
        top = f"zephyrd-{vs}-{pl}"
        man = json.load(open(os.path.join(out, top + ".manifest.json")))
        if pl.startswith("windows"):
            z = zipfile.ZipFile(os.path.join(out, top + ".zip"))
            members = sorted(i.filename.rstrip("/") for i in z.infolist())
            times = {i.date_time for i in z.infolist()}
            binfo = z.getinfo(f"{top}/{binary}")
            bin_ok = hashlib.sha256(z.read(binfo)).hexdigest() == man["binary"]["sha256"] and (binfo.external_attr >> 16) & 0o777 == 0o755
            meta_ok = len(times) == 1
        else:
            raw = open(os.path.join(out, top + ".tar.gz"), "rb").read()
            gz_ok = raw[4:8] == b"\0\0\0\0" and not (raw[3] & 0x08)   # MTIME 0, no FNAME
            t = tarfile.open(os.path.join(out, top + ".tar.gz"))
            members = sorted(m.name for m in t.getmembers())
            bm = t.getmember(f"{top}/{binary}")
            bin_ok = hashlib.sha256(t.extractfile(bm).read()).hexdigest() == man["binary"]["sha256"] and bm.mode & 0o777 == 0o755
            meta_ok = gz_ok and all(m.mtime == ctime and m.uid == 0 and m.gid == 0 and m.uname == "" for m in t.getmembers())
        layout = {top, f"{top}/{binary}", f"{top}/LICENSE", f"{top}/README.txt", f"{top}/THIRD-PARTY-LICENSES",
                  f"{top}/THIRD-PARTY-LICENSES/INDEX.txt"}
        record(f"{pl}: fixed layout with binary, LICENSE, THIRD-PARTY-LICENSES, README.txt", layout <= set(members), members)
        record(f"{pl}: unpacked binary is the manifest's, mode 0755", bin_ok)
        record(f"{pl}: fixed archive metadata (time, owner, no gzip name or time)", meta_ok)
        linked = [pkg for pkg, v in SRC.items() if pl in v[2]]
        record(f"{pl}: licences complete, {3 + len(linked)} texts (build:<dir> needs none, compiled owner covered)",
               man["third_party_licenses"]["status"] == "complete"
               and len(man["third_party_licenses"]["entries"]) == 3 + len(linked), man["third_party_licenses"])
        st = {t["package"]: t for t in man["source_tarballs"]}
        if pl.startswith("windows"):
            rd = zipfile.ZipFile(os.path.join(out, top + ".zip")).read(f"{top}/README.txt").decode()
        else:
            rd = tarfile.open(os.path.join(out, top + ".tar.gz")).extractfile(f"{top}/README.txt").read().decode()
        record(f"{pl}: manifest names exactly the source tarballs of {', '.join(linked)}", sorted(st) == sorted(linked), st)
        for pkg in linked:
            fname, lname, _, name = SRC[pkg]
            t = st.get(pkg, {})
            record(f"{pl}: manifest and README name the {pkg} source tarball", t.get("file") == fname
                   and t.get("sha256") == PIN[pkg] == t.get("pinned_sha256") and t.get("licence_text") == f"THIRD-PARTY-LICENSES/depends/{pkg}/{lname}"
                   and f"{fname}, published next to this archive" in rd and f"source code of\n  {name} exactly" in rd, (t, rd[-900:]))
        for pkg in set(SRC) - set(linked):
            record(f"{pl}: {pkg} not linked, README does not name its tarball", SRC[pkg][0] not in rd)
        record(f"{pl}: manifest names commit, run, version and own commit subjects",
               man["source"]["commit"] == commit and man["workflow"]["run_id"] == "5" and man["version_string"] == vs
               and [c["subject"] for c in man["source"]["own_commits"]] == ["Add the first own change", "Add the second own change"])
    readme = tarfile.open(os.path.join(out, f"zephyrd-{vs}-macos-x86_64.tar.gz")).extractfile(f"zephyrd-{vs}-macos-x86_64/README.txt").read().decode()
    record("README: personal build, not zephyr-backports, verify, replace, quarantine note",
           all(x in readme for x in ("personal build", "not part of zephyr-backports", "gpg --verify SHA256SUMS.asc   (SHA256SUMS.asc is the clear-signed",
                                     "Keep the data directory", "com.apple.quarantine", "Status: complete")), readme[:300])
    p2, out2 = run("valid-again", d)
    record("a second run gives a byte-identical set", p2.returncode == 0 and all(
        sha(os.path.join(out, n)) == sha(os.path.join(out2, n)) for n in want), p2.stderr[-300:])


def variant(name, fn, want_exit, frag, want_status=None):
    dv = base_set(name)
    fn(dv)
    p, outv = run(name, dv)
    ok = p.returncode == want_exit and frag in (p.stdout + p.stderr)
    if want_status:
        m = json.load(open(os.path.join(outv, f"zephyrd-{vs}-linux-x86_64.manifest.json"))) if p.returncode == 0 else {}
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
def no_tarball(pkg, plat):
    def f(dv):
        os.remove(os.path.join(dv, plat, "build-logs", "depends-sources", SRC[pkg][0]))
    return f


def tarball_not_pin(pkg, plat):
    def f(dv):
        bad = b"other bytes"
        hb = hashlib.sha256(bad).hexdigest()
        open(os.path.join(dv, plat, "build-logs", "depends-sources", SRC[pkg][0]), "wb").write(bad)
        edit_inv(dv, plat, lambda r: [x if x[2] != f"depends:{pkg}" or x[0] == "input" else
                                      x[:3] + ([hb] if x[0] == "source-tarball" else [x[3]]) + [x[4].replace(PIN[pkg], hb)] for x in r])
    return f


def no_row(pkg, plat):
    def f(dv):
        edit_inv(dv, plat, lambda r: [x for x in r if not (x[0] == "source-tarball" and x[2] == f"depends:{pkg}")])
    return f


def unlinked(pkg):
    def f(dv):
        for plat in SRC[pkg][2]:
            os.remove(os.path.join(dv, plat, "build-logs", "depends-sources", SRC[pkg][0]))
            edit_inv(dv, plat, lambda r: [x for x in r if x[2] != f"depends:{pkg}"])
    return f


for pkg, (fname, _, plats, _) in SRC.items():
    plat = plats[-1]
    variant(f"{pkg}-linked-tarball-missing", no_tarball(pkg, plat), 1, f"{plat}: source tarball depends-sources/{fname} of depends:{pkg} missing from the build artifact")
    variant(f"{pkg}-tarball-not-the-pin", tarball_not_pin(pkg, plats[0]), 1, f"pin {PIN[pkg]}")
    variant(f"{pkg}-linked-no-tarball-row", no_row(pkg, plat), 1, f"depends:{pkg} is linked but the build carries 0 source tarballs")
    dv = base_set(f"{pkg}-not-linked")
    unlinked(pkg)(dv)
    p, outv = run(f"{pkg}-not-linked", dv)
    ms = [json.load(open(os.path.join(outv, f"zephyrd-{vs}-{pl}.manifest.json"))) for pl in PLAT] if p.returncode == 0 else []
    record(f"{pkg}-not-linked: exit 0, no tarball of it in the set or any manifest, licences complete",
           p.returncode == 0 and fname not in os.listdir(outv) and len(ms) == len(PLAT)
           and all(pkg not in [t["package"] for t in m["source_tarballs"]] and m["third_party_licenses"]["status"] == "complete" for m in ms),
           (p.stdout + p.stderr)[-300:])

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
mh = json.load(open(os.path.join(outv, f"zephyrd-{vs}-linux-x86_64.manifest.json"))) if p.returncode == 0 else {}
lic = mh.get("third_party_licenses", {})
eh = [e for e in lic.get("entries", []) if e.get("owner") == "tree:external/ext"]
idx = ""
if p.returncode == 0:
    with tarfile.open(os.path.join(outv, f"zephyrd-{vs}-linux-x86_64.tar.gz")) as tf:
        idx = tf.extractfile(f"zephyrd-{vs}-linux-x86_64/THIRD-PARTY-LICENSES/INDEX.txt").read().decode()
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
    with zipfile.ZipFile(os.path.join(outv, f"zephyrd-{vs}-windows-x86_64.zip")) as zf:
        idx = zf.read(f"zephyrd-{vs}-windows-x86_64/THIRD-PARTY-LICENSES/INDEX.txt").decode()
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
    top = f"zephyrd-{vs}-linux-x86_64"
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

# round 21: classification of one leg (the first leg of a one-leg call)
leg_cases = [
    ("real record of run 43297105618 attempt 1 (runner not acquired)", REAL, False, "not-run", "runner not acquired"),
    ("all three start steps succeeded", arm_job(), False, "passed", None),
    ("strict offline start failed", arm_job(conclusion="failure", steps={START[1]: "failure", START[2]: "skipped"}), False, "failed",
     f"start step '{START[1]}' ended failure"),
    ("version step cancelled (job timeout)", arm_job(conclusion="cancelled", steps={START[0]: "cancelled", START[1]: "skipped",
                                                                                    START[2]: "skipped"}), False, "failed", "ended cancelled"),
    ("failure before the first start step (artifact download)", arm_job(conclusion="failure", steps={
        "Download the cross-built artifact": "failure", **{n: "skipped" for n in START}}), False, "not-run",
     "job failure before the binary was started (step 'Download the cross-built artifact')"),
    ("job skipped", dict(REAL, conclusion="skipped"), False, "not-run", "job skipped"),
    ("still queued when the wait ended", dict(REAL, status="queued", conclusion=None), True, "not-run",
     "job not completed when the package job's wait ended (status queued)"),
    ("in progress after the version step when the wait ended", arm_job(status="in_progress", conclusion=None, steps={
        START[0]: "success", START[1]: None, START[2]: None}), True, "not-run", "status in_progress"),
]
for i, (name, job, lr, want, frag) in enumerate(leg_cases):
    got, _ = classify(f"leg{i}", [job], lr)
    leg = (got.get("legs") or [{}])[0]
    ok = leg.get("status") == want and ((frag is None and leg.get("reason") is None) or (frag and frag in (leg.get("reason") or "")))
    if want == "passed":
        ok = ok and leg["runner_label"] == "macos-15" and leg["job_id"] == job["id"] and all(v == "success" for v in leg["checks"].values())
    record(f"native start leg: {name} -> {want}", ok, got)

# round 21: two legs (macos-15, macos-26) -> the platform's outcome
FAILED_JOB = leg_cases[2][1]
combo = [
    ("neither leg acquired a runner", [not_acquired("macos-15"), not_acquired("macos-26")], "not-run",
     ["not-run", "not-run"], "macos-15: runner not acquired: job cancelled before any step; macos-26: runner not acquired"),
    ("macos-15 passed, macos-26 not acquired", [arm_job("macos-15"), not_acquired("macos-26")], "passed", ["passed", "not-run"], None),
    ("macos-15 not acquired, macos-26 passed", [not_acquired("macos-15"), arm_job("macos-26")], "passed", ["not-run", "passed"], None),
    ("both legs passed", [arm_job("macos-15"), arm_job("macos-26")], "passed", ["passed", "passed"], None),
    ("macos-15 passed, macos-26 failed with the binary run", [arm_job("macos-15"), dict(FAILED_JOB, name=LEG["macos-26"], labels=["macos-26"])],
     "failed", ["passed", "failed"], "macos-26: start step"),
]
for i, (name, jobs, want, legs, frag) in enumerate(combo):
    got, _ = classify(f"combo{i}", jobs)
    ok = got["status"] == want and [l["status"] for l in got["legs"]] == legs and \
        [l["runner_label"] for l in got["legs"]] == [j["labels"][0] for j in jobs] and \
        ((frag is None and got["reason"] is None) or (frag and frag in (got["reason"] or "")))
    record(f"native start, two legs: {name} -> {want}", ok, got)

# round 21: make-release-set.py with each outcome
NS_BOTH = classify("both", combo[3][1])[1]
NS_NOTRUN = classify("not-run", combo[0][1])[1]
NS_FAILED = classify("failed", combo[4][1])[1]
arm = f"zephyrd-{vs}-macos-arm64"


def arm_view(out):
    man = json.load(open(os.path.join(out, arm + ".manifest.json")))
    rd = tarfile.open(os.path.join(out, arm + ".tar.gz")).extractfile(f"{arm}/README.txt").read().decode()
    others = [json.load(open(os.path.join(out, f"zephyrd-{vs}-{pl}.manifest.json"))) for pl in PLAT if pl != "macos-arm64"]
    return man, rd, others


def tested_part(rd):
    return rd.split("WHAT THE HOSTED RUNNERS")[1].split("NOTE")[0]


j15, j26 = combo[3][1]
line15 = f"on macos-15 (Apple Silicon, job {j15['id']}): --version, a strict offline start"
line26 = f"on macos-26 (Apple Silicon, job {j26['id']}): --version, a strict offline start"
for i, (name, nsf, check) in enumerate([
    ("macos-15 passed, macos-26 not acquired: the macos-15 start listed as tested, one line for macos-26 with its reason",
     NS_PASSED, lambda man, rd: man["native_start"]["status"] == "passed" and len(man["tested"]) == 2 and line15 in man["tested"][1]
     and line15 in rd and "No start on macos-26 in this run: runner not acquired" in rd and "Not started natively" not in rd),
    ("both legs passed: both starts listed as tested with runner and job",
     NS_BOTH, lambda man, rd: man["native_start"]["status"] == "passed" and len(man["tested"]) == 3 and line15 in rd and line26 in rd
     and "No start on" not in rd and "Not started natively" not in rd),
    ("neither leg ran: only the build listed; README says not started natively in this run with both reasons",
     NS_NOTRUN, lambda man, rd: man["native_start"]["status"] == "not-run" and len(man["tested"]) == 1
     and "strict offline start" not in tested_part(rd)
     and "Not started natively in this run: macos-15: runner not acquired: job cancelled before any step; macos-26: runner not acquired" in rd
     and "not a required check" in rd),
    ("a leg failed with the binary run: written, README says NATIVE START FAILED on macos-26 and must not be released",
     NS_FAILED, lambda man, rd: man["native_start"]["status"] == "failed" and "NATIVE START FAILED in this run on macos-26" in rd
     and "must not be released" in rd),
]):
    tag = f"native-set{i}"
    p, outn = run(tag, base_set(tag), native=nsf)
    if p.returncode == 0:
        man, rd, others = arm_view(outn)
        ok = check(man, rd) and all("native_start" not in o for o in others)
        if "FAILED" in name:
            ok = ok and "::warning title=native start macos-arm64::NATIVE START FAILED" in p.stdout
        record(f"release set: {name}", ok, (man.get("native_start"), tested_part(rd)[-700:]))
    else:
        record(f"release set: {name}", False, p.stderr[-300:])
p, _ = run("native-none", base_set("native-none"), native="none")
record("no --native-start: refused", p.returncode != 0 and "--native-start" in p.stderr, p.stderr[-300:])
bad = json.load(open(NS_PASSED)); bad["status"] = "not-run"; bad["reason"] = "invented"
badf = os.path.join(work, "native-malformed.json"); json.dump(bad, open(badf, "w"))
p, _ = run("native-malformed", base_set("native-malformed"), native=badf)
record("malformed outcome (not-run although a leg passed): refused", p.returncode == 1 and "not a native-start.py outcome" in p.stderr,
       p.stderr[-300:])

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

# round 21: native-start.py wait (two legs, one bounded wait) against a loopback stub of the jobs API
NS_API = {"mode": "queued", "calls": 0}


class JobsApi(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        NS_API["calls"] += 1
        if NS_API["mode"] == "error" or not self.path.startswith("/repos/example/myzephyr/actions/runs/5/attempts/2/jobs"):
            self.send_response(403); self.end_headers(); return
        late = NS_API["calls"] >= 3
        queued = lambda label: not_acquired(label, status="queued", conclusion=None)
        jobs = {"queued": [queued("macos-15"), queued("macos-26")],
                "one-passes": [arm_job("macos-15") if late else queued("macos-15"), queued("macos-26")],
                "both-complete": [arm_job("macos-15") if late else queued("macos-15"), not_acquired("macos-26") if late else queued("macos-26")],
                "missing": [queued("macos-15")]}[NS_API["mode"]]
        b = json.dumps({"total_count": len(jobs), "jobs": jobs}).encode()
        self.send_response(200); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)


srv2 = ThreadingHTTPServer(("127.0.0.1", 0), JobsApi)
threading.Thread(target=srv2.serve_forever, daemon=True).start()


def wait(name, mode, limit=3):
    NS_API.update(mode=mode, calls=0)
    of = os.path.join(work, f"wait-{name}.json")
    p = subprocess.run([sys.executable, "-I", ns_tool, "wait", "--repository", "example/myzephyr", "--run-id", "5", "--run-attempt", "2",
                        "--job-name", LEG["macos-15"], "--job-name", LEG["macos-26"], "--limit", str(limit), "--poll", "0.5",
                        "--api", f"http://127.0.0.1:{srv2.server_address[1]}", "--out", of], capture_output=True, text=True)
    return p, (json.load(open(of)) if os.path.exists(of) else {})


p, w = wait("queued", "queued")
record("wait: both legs stay queued -> not-run with both reasons within the one limit (3 s here, 2700 s in the workflow)",
       p.returncode == 0 and w.get("status") == "not-run" and w.get("reason", "").count("status queued") == 2
       and w.get("waited_seconds", 99) <= 4.5, w)
p, w = wait("one-passes", "one-passes")
record("wait: macos-15 passes, macos-26 stays queued -> passed, macos-26 not completed, still within the one limit",
       p.returncode == 0 and w.get("status") == "passed" and [l["status"] for l in w.get("legs", [])] == ["passed", "not-run"]
       and "status queued" in w["legs"][1]["reason"] and 2.5 <= w.get("waited_seconds", 0) <= 4.5, w)
p, w = wait("both-complete", "both-complete", limit=20)
record("wait: both legs complete (macos-15 passed, macos-26 not acquired) -> passed, before the limit",
       p.returncode == 0 and w.get("status") == "passed" and [l["status"] for l in w.get("legs", [])] == ["passed", "not-run"]
       and "runner not acquired" in w["legs"][1]["reason"] and w.get("waited_seconds", 99) < 10, w)
p, w = wait("error", "error")
record("wait: an API that always refuses -> not-run (state not readable) for both legs within the limit",
       p.returncode == 0 and w.get("status") == "not-run" and w.get("reason", "").count("not readable") == 2
       and w.get("waited_seconds", 99) <= 4.5, w)
p, w = wait("missing", "missing")
record("wait: a leg's job missing from the run attempt -> exit 1 (configuration error)",
       p.returncode == 1 and "expected exactly one" in p.stderr, p.stderr[-300:])
srv2.shutdown()

json.dump(results, open(os.path.join(work, "results.json"), "w"), indent=2)
bad = [r for r in results if not r["ok"]]
print(f"{len(results) - len(bad)}/{len(results)} cases as intended (synthetic artifacts; not a real release set)")
sys.exit(1 if bad else 0)
