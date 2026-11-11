#!/usr/bin/env python3
"""Self-test of release/make-release-set.py with synthetic artifacts (placeholder binaries,
invented licence texts and a small git checkout made here). Not a real release set.

  release-set-selftest.py <work-dir>      (<work-dir> must not exist)

Valid set: four archives and four manifests, SHA256SUMS over exactly those eight files,
fixed layout zephyrd-<version>-<platform>/ with the binary (0755), LICENSE,
THIRD-PARTY-LICENSES/ and README.txt; tar members with time SOURCE_DATE_EPOCH, owner 0:0;
gzip without name and time; zip entries with fixed time and modes; every manifest valid
against release-target.schema.json; licences complete; two runs give byte-identical sets.
Then one change per case: an unresolved inventory line, no inventory, a used owner without a
text, a depends source hash other than the pin, a re-link that was not identical (each:
written but "incomplete"); a version "release", a target disagreeing on the commit or the
run, a binary not matching its manifest, an inventory not matching the manifest, a licence
text not matching its inventory hash (each: refused, exit 1).
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
        "macos-x86_64": ("x86_64-apple-darwin", "zephyrd"), "windows-x86_64": ("x86_64-w64-mingw32", "zephyrd.exe")}


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
             f"depends source=dep-1.0.tar.gz source_sha256={hashlib.sha256(src_tarball).hexdigest()} member=dep-1.0/COPYING")]
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
want = sorted([f"zephyrd-{vs}-{pl}.{'zip' if pl.startswith('windows') else 'tar.gz'}" for pl in PLAT] +
              [f"zephyrd-{vs}-{pl}.manifest.json" for pl in PLAT] + ["SHA256SUMS"])
record("exactly four archives, four manifests and SHA256SUMS", names == want, names)
if names == want:
    sums = [l.split("  ") for l in open(os.path.join(out, "SHA256SUMS")).read().splitlines()]
    record("SHA256SUMS lists the eight files, not itself, hashes match",
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
        record(f"{pl}: licences complete, three texts", man["third_party_licenses"]["status"] == "complete"
               and len(man["third_party_licenses"]["entries"]) == 3, man["third_party_licenses"])
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
variant("depends-hash-not-pinned", lambda dv: edit_inv(dv, "linux-x86_64", lambda r: [x if x[0] != "license" or "depends" not in x[4] else x[:4] + [x[4].replace("source_sha256=", "source_sha256=0")[:-1]] for x in r]),
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
variant("licence-text-changed", lambda dv: open(os.path.join(dv, "linux-x86_64", "build-logs", "licenses", "depends", "dep", "COPYING"), "a").write("x"),
        1, "does not match its inventory hash")

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
