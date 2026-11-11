#!/usr/bin/env python3
"""Self-test of release/draft-release.sh with a stubbed gh, throwaway keys, a synthetic
repository, synthetic tags (only in that throwaway repository) and a synthetic release set
made by make-release-set.py. Nothing contacts GitHub; nothing here is a real release.

  draft-release-selftest.py <work-dir>      (<work-dir> must not exist)

World: a checkout R with this directory's scripts, throwaway public keys in
contrib/myzephyr/keys/ and a workflow file whose pins name them; a base commit with a tag
signed by the throwaway base key (refs/tags/v-selftest-base), one own commit signed by the
throwaway maintainer key ("Origin: myzephyr"), branch my/v2.3.0, the release tag
v2.3.0-sec.2-my.1 signed by the maintainer key. The stub gh answers the run, branch,
artifact and release queries from files and records every call.
Cases: --dry-run creates nothing and prints the command with the nine files; a real call
runs gh release create --draft --verify-tag with exactly those files and notes naming the
base, the own commit ("not yet reported"), the platforms, the verification and the run.
Refused, one change each: a release exists; run event pull_request; run on another branch;
run not successful; run built another commit; tag commit not on the branch; tag signed by
another key; lightweight tag; GitHub digest differs; a file of the set changed (SHA256SUMS);
manifest of another run; incomplete licences; archive binary differs from the manifest;
artifact expired. Usage: tag name outside v*-sec.*-my.*, run id not a number, no arguments.
"""
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import zipfile

here = os.path.dirname(os.path.abspath(__file__))
tools = os.path.dirname(here)
work = os.path.abspath(sys.argv[1]) if len(sys.argv) == 2 else sys.exit(__doc__)
if os.path.lexists(work):
    sys.exit(f"{work} exists")
os.makedirs(work)
results = []
REPO, RUN, TAG, BRANCH = "example/myzephyr", "7", "v2.3.0-sec.2-my.1", "my/v2.3.0"
ENV = dict(os.environ, LC_ALL="C", TZ="UTC", GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull)
ENV.pop("GNUPGHOME", None)


def record(name, ok, detail=""):
    results.append({"case": name, "ok": bool(ok), "detail": detail})
    print(f"{'ok  ' if ok else 'FAIL'} {name}" + ("" if ok else f" -- {detail}"), flush=True)


def run(*a, cwd=None, env=None, check=True, input=None):
    return subprocess.run(a, cwd=cwd, env=env or ENV, check=check, capture_output=True, text=True, input=input)


def sha(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


# ---------------------------------------------------------------- throwaway keys
gh_home = tempfile.mkdtemp(prefix="drst.", dir=os.environ.get("TMPDIR", "/tmp"))
os.chmod(gh_home, 0o700)


def gen(name):
    run("gpg", "--batch", "--homedir", gh_home, "--pinentry-mode", "loopback", "--passphrase", "",
        "--quick-gen-key", f"selftest {name} <{name}@example.invalid>", "ed25519", "sign", "never")
    out = run("gpg", "--batch", "--homedir", gh_home, "--with-colons", "--list-keys", f"{name}@example.invalid").stdout
    return next(l.split(":")[9] for l in out.splitlines() if l.startswith("fpr"))


try:
    BASE, MAINT, OTHER = gen("base"), gen("maintainer"), gen("other")

    # ------------------------------------------------------------ the synthetic repository R
    R = os.path.join(work, "R")
    shutil.copytree(tools, os.path.join(R, "contrib", "myzephyr"), ignore=shutil.ignore_patterns("__pycache__", "tests"))
    keys = os.path.join(R, "contrib", "myzephyr", "keys")
    for f, fpr in (("zephyr-backports-release.asc", BASE), ("myzephyr-maintainer.asc", MAINT)):
        open(os.path.join(keys, f), "w").write(run("gpg", "--batch", "--homedir", gh_home, "--armor", "--export", fpr).stdout)
    os.makedirs(os.path.join(R, ".github", "workflows"))
    open(os.path.join(R, "LICENSE"), "w").write("synthetic tree licence\n")

    def G(*a, check=True):
        return run("git", "-C", R, "-c", "core.hooksPath=/dev/null", "-c", "gpg.program=gpg", "-c", "user.name=selftest",
                   "-c", "user.email=selftest@example.invalid", *a, env=dict(ENV, GNUPGHOME=gh_home), check=check).stdout.strip()

    run("git", "init", "-q", R)
    G("checkout", "-q", "-b", "main")
    open(os.path.join(R, ".github", "workflows", "daemon-release-baseline.yml"), "w").write("placeholder\n")
    G("add", "-A")
    G("-c", "commit.gpgsign=false", "commit", "-q", "-m", "base")
    base_commit = G("rev-parse", "HEAD")
    G("tag", "-s", "-u", BASE, "-m", "base tag", "v-selftest-base")
    base_tag_object = G("rev-parse", "refs/tags/v-selftest-base")
    origin = os.path.join(work, "origin.git")
    wf = (f"env:\n  BASE_REPOSITORY_URL: file://{origin}\n  BASE_TAG: v-selftest-base\n  BASE_COMMIT: {base_commit}\n"
          f"  BASE_TAG_OBJECT: {base_tag_object}\n  BASE_FINGERPRINT: {BASE}\n  MAINTAINER_FINGERPRINT: {MAINT}\n")
    # the pins live in the working tree the script runs from (not committed: the base commit cannot know its own id)
    open(os.path.join(R, ".github", "workflows", "daemon-release-baseline.yml"), "w").write(wf)
    G("update-index", "--assume-unchanged", ".github/workflows/daemon-release-baseline.yml")

    def own_commit(subject, key=MAINT):
        open(os.path.join(R, "contrib", "myzephyr", "own.txt"), "a").write(subject + "\n")
        G("add", "contrib/myzephyr/own.txt")
        G("commit", "-q", f"-S{key}", "-m", subject, "-m", "Origin: myzephyr")
        return G("rev-parse", "HEAD")

    C = own_commit("Add the own change")
    G("branch", BRANCH, C)
    G("tag", "-s", "-u", MAINT, "-m", f"{TAG}", TAG, C)
    side = G("commit-tree", "-p", base_commit, "-m", "side", G("rev-parse", f"{base_commit}^{{tree}}"))
    run("git", "clone", "-q", "--bare", R, origin)

    # ------------------------------------------------------------ the release set of run 7
    co = os.path.join(work, "co")
    run("git", "clone", "-q", "--no-tags", R, co)
    run("git", "-C", co, "checkout", "-q", "--detach", C)
    ctime = int(run("git", "-C", co, "log", "-1", "--format=%ct").stdout)
    version = f"2.3.0-{C[:9]}"
    PLAT = {"linux-x86_64": ("x86_64-unknown-linux-gnu", "zephyrd"), "linux-aarch64": ("aarch64-linux-gnu", "zephyrd"),
            "macos-x86_64": ("x86_64-apple-darwin", "zephyrd"), "windows-x86_64": ("x86_64-w64-mingw32", "zephyrd.exe")}
    RUN_URL = f"https://github.com/{REPO}/actions/runs/{RUN}/attempts/1"

    def make_set(name, mutate=None):
        arts = os.path.join(work, name + "-arts")
        for plat, (target, binary) in PLAT.items():
            d = os.path.join(arts, plat)
            os.makedirs(os.path.join(d, "build-logs", "licenses", "tree"))
            open(os.path.join(d, binary), "wb").write(f"placeholder {plat}\n".encode())
            open(os.path.join(d, "build-logs", "licenses", "tree", "LICENSE"), "w").write("synthetic tree licence\n")
            inv = ("kind\tpath\towner\tsha256\tdetail\nstatus\trelink_identical\t-\t-\tyes\n"
                   f"input\t/src/build/release/src/daemon/CMakeFiles/daemon.dir/main.cpp.o\ttree:src/daemon\t{'0' * 64}\tused\n"
                   f"license\tlicenses/tree/LICENSE\ttree:src/daemon\t{sha(os.path.join(d, 'build-logs', 'licenses', 'tree', 'LICENSE'))}\ttree path=LICENSE\n")
            open(os.path.join(d, "build-logs", "link-inventory.tsv"), "w").write(inv)
            m = {"artifact": {"name": binary, "target": target, "expected_version": version,
                              "sha256": sha(os.path.join(d, binary)), "size": os.path.getsize(os.path.join(d, binary))},
                 "source": {"commit": C, "commit_time": ctime, "own_commits": [{"commit": C, "paths": ["contrib/myzephyr/own.txt"]}]},
                 "base": {"tag": "v-selftest-base", "commit": base_commit, "signer_primary_fingerprint": BASE},
                 "own_commit_signer_primary_fingerprint": MAINT,
                 "workflow": {"repository": REPO, "ref": f"refs/heads/{BRANCH}", "sha": C, "event_name": "push", "run_id": RUN,
                              "run_attempt": "1", "server_url": "https://github.com", "pull_request": None},
                 "build": {"link_inventory_sha256": sha(os.path.join(d, "build-logs", "link-inventory.tsv"))}}
            if mutate:
                mutate(plat, d, m)
            json.dump(m, open(os.path.join(d, "manifest.json"), "w"))
        out = os.path.join(work, name + "-set")
        p = run(sys.executable, "-I", os.path.join(tools, "release", "make-release-set.py"), "--checkout", co, "--out", out,
                "--run-url", RUN_URL, *[f"--artifact={pl}={os.path.join(arts, pl)}" for pl in PLAT], check=False)
        if p.returncode != 0:
            raise SystemExit(f"make-release-set failed for {name}: {p.stderr}")
        return out

    def zip_set(setdir, zpath):
        with zipfile.ZipFile(zpath, "w") as z:
            for n in sorted(os.listdir(setdir)):
                z.write(os.path.join(setdir, n), n)
        return sha(zpath)

    good_set = make_set("good")

    # ------------------------------------------------------------ stub gh
    stub_bin = os.path.join(work, "bin")
    os.makedirs(stub_bin)
    open(os.path.join(stub_bin, "gh"), "w").write(f"""#!{sys.executable}
import json, os, sys
cfg = json.load(open(os.environ["GH_STUB"]))
with open(cfg["log"], "a") as f:
    f.write(json.dumps(sys.argv[1:]) + "\\n")
a = sys.argv[1:]
if a[:1] == ["api"]:
    path = a[1]
    if path not in cfg["api"]:
        sys.stderr.write("stub gh: no answer for " + path + "\\n"); sys.exit(1)
    body = open(cfg["api"][path], "rb").read()
    if "--jq" in a:
        obj = json.loads(body)
        for k in a[a.index("--jq") + 1].lstrip(".").split("."):
            obj = obj[k]
        print(obj)
    else:
        sys.stdout.buffer.write(body)
    sys.exit(0)
if a[:2] == ["release", "view"]:
    sys.exit(0 if cfg.get("release_exists") else 1)
if a[:2] == ["release", "create"]:
    if "--notes-file" in a:
        import shutil
        shutil.copyfile(a[a.index("--notes-file") + 1], cfg["log"] + ".notes")
    sys.exit(0)
sys.stderr.write("stub gh: unexpected call\\n"); sys.exit(1)
""")
    os.chmod(os.path.join(stub_bin, "gh"), 0o755)

    def scenario(name, *, run_over=None, set_dir=None, digest=None, expired=False, release_exists=False, args=None, setup=None,
                 want_exit=0, frag=""):
        d = os.path.join(work, "case-" + name)
        os.makedirs(d)
        runj = {"id": int(RUN), "path": ".github/workflows/daemon-release-baseline.yml", "event": "push", "head_branch": BRANCH,
                "status": "completed", "conclusion": "success", "run_attempt": 1, "head_sha": C,
                "html_url": f"https://github.com/{REPO}/actions/runs/{RUN}", **(run_over or {})}
        json.dump(runj, open(os.path.join(d, "run.json"), "w"))
        zdig = zip_set(set_dir or good_set, os.path.join(d, "set.zip"))
        json.dump({"artifacts": [{"id": 99, "name": f"release-set-{C}", "digest": "sha256:" + (digest or zdig), "expired": expired},
                                 {"id": 98, "name": f"zephyrd-linux-x86_64-{C}", "digest": "sha256:" + "0" * 64, "expired": False}]},
                  open(os.path.join(d, "artifacts.json"), "w"))
        cfg = {"log": os.path.join(d, "gh.log"), "release_exists": release_exists,
               "api": {f"repos/{REPO}/actions/runs/{RUN}": os.path.join(d, "run.json"),
                       f"repos/{REPO}/branches/my%2Fv2.3.0": os.path.join(d, "branch.json"),
                       f"repos/{REPO}/actions/runs/{RUN}/artifacts?per_page=100": os.path.join(d, "artifacts.json"),
                       f"repos/{REPO}/actions/artifacts/99/zip": os.path.join(d, "set.zip")}}
        json.dump(cfg, open(os.path.join(d, "gh.json"), "w"))
        if setup:
            setup()
        json.dump({"commit": {"sha": G("rev-parse", BRANCH)}}, open(os.path.join(d, "branch.json"), "w"))
        env = dict(ENV, PATH=stub_bin + os.pathsep + ENV["PATH"], GH_STUB=os.path.join(d, "gh.json"), MYZ_ORIGIN_URL=f"file://{origin}")
        p = run("bash", os.path.join(R, "contrib", "myzephyr", "release", "draft-release.sh"), "--repo", REPO,
                "--workdir", os.path.join(d, "w"), *(args if args is not None else [TAG, RUN]), env=env, check=False)
        out = p.stdout + p.stderr
        calls = [json.loads(l) for l in open(cfg["log"])] if os.path.exists(cfg["log"]) else []
        creates = [c for c in calls if c[:2] == ["release", "create"]]
        ok = p.returncode == want_exit and frag in out
        if want_exit != 0:
            ok = ok and not creates
        record(f"{name} -> exit {want_exit}", ok, out[-500:])
        return p, out, creates, cfg["log"]

    # positive
    p, out, creates, log = scenario("dry run prints the command, creates nothing", args=["--dry-run", TAG, RUN], frag="dry run, nothing created")
    files = [l.strip() for l in out.splitlines() if l.startswith("  ")]
    record("dry run lists nine flat files (4 archives, 4 manifests, SHA256SUMS last)", len(files) == 9 and files[-1] == "SHA256SUMS"
           and sum(f.endswith(".manifest.json") for f in files) == 4 and not creates, files)
    record("dry run prints gh release create --draft --verify-tag", "gh release create" in out and "--draft --verify-tag" in out)
    p, out, creates, log = scenario("real call creates the draft", frag="draft created")
    c = creates[0] if creates else []
    record("gh release create with --draft --verify-tag and exactly the nine files", len(creates) == 1 and "--draft" in c
           and "--verify-tag" in c and "--title" in c and sum(1 for x in c if os.path.isfile(x) and not x.endswith("notes.md")) == 9, c)
    notes = open(log + ".notes").read() if os.path.exists(log + ".notes") else ""
    record("notes: base, own commit not yet reported, platforms, verification, run, owner statement placeholder",
           all(x in notes for x in ("v-selftest-base", "Add the own change (upstream report: not yet reported)", "windows-x86_64",
                                    "gpg --verify SHA256SUMS.asc", RUN_URL, "TO BE STATED BY THE OWNER")), notes[:400])
    record("never publishes and never signs", not any("--draft=false" in x or x == "edit" for cc in creates for x in cc))

    # refusals
    scenario("release already exists", release_exists=True, want_exit=1, frag="already exists")
    scenario("run of a pull request", run_over={"event": "pull_request"}, want_exit=1, frag="event is 'pull_request'")
    scenario("run on another branch", run_over={"head_branch": "ci/daemon-release-baseline"}, want_exit=1, frag="branch is")
    scenario("run not successful", run_over={"conclusion": "failure"}, want_exit=1, frag="conclusion is 'failure'")
    scenario("run built another commit", run_over={"head_sha": base_commit}, want_exit=1, frag=f"the run built {base_commit}")

    def move_branch_away():
        G("update-ref", f"refs/heads/{BRANCH}", side)
        run("git", "-C", origin, "update-ref", f"refs/heads/{BRANCH}", side)
    scenario("tag commit not on the branch", setup=move_branch_away, want_exit=1, frag="is not my/v2.3.0's head or an ancestor")
    G("update-ref", f"refs/heads/{BRANCH}", C)
    run("git", "-C", origin, "update-ref", f"refs/heads/{BRANCH}", C)

    def retag(*args):
        def f():
            run("git", "-C", origin, "tag", "-d", TAG)
            G("tag", "-d", TAG)
            G(*args)
            run("git", "-C", origin, "fetch", "-q", R, f"+refs/tags/{TAG}:refs/tags/{TAG}")
        return f
    scenario("tag signed by another key", setup=retag("tag", "-s", "-u", OTHER, "-m", TAG, TAG, C), want_exit=1, frag="signature does not verify")
    scenario("lightweight tag", setup=retag("-c", "tag.gpgsign=false", "tag", TAG, C), want_exit=1, frag="is not an annotated tag")
    retag("tag", "-s", "-u", MAINT, "-m", TAG, TAG, C)()
    scenario("artifact digest differs from GitHub's", digest="1" * 64, want_exit=1, frag="does not match GitHub's digest")
    scenario("artifact expired", expired=True, want_exit=1, frag="not available with a digest")

    tampered = os.path.join(work, "tampered-set")
    shutil.copytree(good_set, tampered)
    arch = next(n for n in os.listdir(tampered) if n.endswith("linux-aarch64.tar.gz"))
    open(os.path.join(tampered, arch), "ab").write(b"x")
    scenario("a file of the set changed (SHA256SUMS)", set_dir=tampered, want_exit=1, frag="does not match SHA256SUMS")
    other_run = make_set("other-run", lambda pl, d, m: m["workflow"].__setitem__("run_id", "8"))
    scenario("manifests of another run", set_dir=other_run, want_exit=1, frag="run id is '8'")

    def incomplete(pl, d, m):
        p = os.path.join(d, "build-logs", "link-inventory.tsv")
        open(p, "a").write("status\tunresolved\tunknown\t-\towner of a used input not found\n")
        m["build"]["link_inventory_sha256"] = sha(p)
    scenario("incomplete licences", set_dir=make_set("incomplete", incomplete), want_exit=1, frag="licence list incomplete")
    swapped = os.path.join(work, "swapped-set")
    shutil.copytree(good_set, swapped)
    mfile = next(n for n in os.listdir(swapped) if n.endswith("macos-x86_64.manifest.json"))
    m = json.load(open(os.path.join(swapped, mfile)))
    m["binary"]["sha256"] = "2" * 64
    m["build_manifest"]["artifact"]["sha256"] = "2" * 64
    json.dump(m, open(os.path.join(swapped, mfile), "w"), indent=2, sort_keys=True)
    lines = [l for l in open(os.path.join(swapped, "SHA256SUMS")).read().splitlines() if not l.endswith(mfile)]
    lines.append(f"{sha(os.path.join(swapped, mfile))}  {mfile}")
    open(os.path.join(swapped, "SHA256SUMS"), "w").write("\n".join(sorted(lines, key=lambda l: l.split('  ')[1])) + "\n")
    scenario("archive binary differs from the manifest", set_dir=swapped, want_exit=1, frag="does not unpack to the named binary")

    # usage
    scenario("tag name outside v*-sec.*-my.*", args=["v2.3.0-sec.2", RUN], want_exit=2, frag="does not match")
    scenario("run id not a number", args=[TAG, "latest"], want_exit=2, frag="is not a number")
    scenario("no arguments", args=[], want_exit=2, frag="usage:")
finally:
    subprocess.run(["gpgconf", "--homedir", gh_home, "--kill", "all"], capture_output=True)
    shutil.rmtree(gh_home, ignore_errors=True)

json.dump(results, open(os.path.join(work, "results.json"), "w"), indent=2)
bad = [r for r in results if not r["ok"]]
print(f"{len(results) - len(bad)}/{len(results)} cases as intended (stub gh, throwaway keys and tags; no real release)")
sys.exit(1 if bad else 0)
