#!/usr/bin/env python3
"""Self-test of run-identity.py: each row of the table, then one changed variable per case.

  run-identity-selftest.py <work-dir>      (<work-dir> must not exist)

1. errors(): a valid identity of each row (push to ci/daemon-release-baseline, push to
   my/v2.3.0, pull request into my/v2.3.0 built at its head) has no error; each case
   changes exactly one value and must be refused.
2. "check" as a workflow step runs it: the job's GITHUB_* variables, an event payload file
   and MYZ_BUILD_SHA; exit 0 and MYZ_PULL_REQUEST in the GITHUB_ENV file for the valid
   rows, exit 1 for a refused one. Synthetic values only; nothing contacts GitHub.
"""
import importlib.util
import json
import os
import subprocess
import sys

here = os.path.dirname(os.path.abspath(__file__))
tool = os.path.join(os.path.dirname(here), "run-identity.py")
sys.dont_write_bytecode = True
spec = importlib.util.spec_from_file_location("run_identity", tool)
ri = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ri)
work = os.path.abspath(sys.argv[1]) if len(sys.argv) == 2 else sys.exit(__doc__)
if os.path.lexists(work):
    sys.exit(f"{work} exists")
os.makedirs(work)
REPO = "loki-notfound/myzephyr"
WF = ".github/workflows/daemon-release-baseline.yml"
BUILT, MERGE, BASE, OTHER = "a" * 40, "b" * 40, "c" * 40, "d" * 40
results = []


def record(name, ok, detail=""):
    results.append({"case": name, "ok": bool(ok), "detail": detail})
    print(f"{'ok  ' if ok else 'FAIL'} {name}" + ("" if ok else f" -- {detail}"))


def push(ref):
    return {"event_name": "push", "ref": ref, "sha": BUILT, "workflow_sha": BUILT, "workflow_ref": f"{REPO}/{WF}@{ref}",
            "repository": REPO, "built_commit": BUILT, "pull_request": None}


def pr_ctx(**pr_over):
    pr = {"number": 7, "base_ref": "my/v2.3.0", "base_sha": BASE, "head_sha": BUILT, "head_ref": "pr/v2.3.0-sec.2-my.1",
          "head_repository": REPO, **pr_over}
    ref = "refs/pull/7/merge"
    return {"event_name": "pull_request", "ref": ref, "sha": MERGE, "workflow_sha": MERGE,
            "workflow_ref": f"{REPO}/{WF}@{ref}", "repository": REPO, "built_commit": BUILT, "pull_request": pr}


def change(ctx, **over):
    c = json.loads(json.dumps(ctx))
    c.update(over)
    return c


ROWS = {"push ci/daemon-release-baseline": push("refs/heads/ci/daemon-release-baseline"),
        "push my/v2.3.0": push("refs/heads/my/v2.3.0"),
        "push my/v2.3.0/sub": push("refs/heads/my/v2.3.0/sub"),
        "pull_request into my/v2.3.0": pr_ctx()}
for name, ctx in ROWS.items():
    e = ri.errors(ctx)
    record(f"table: valid {name}", not e, e)

ci, my, pr = ROWS["push ci/daemon-release-baseline"], ROWS["push my/v2.3.0"], ROWS["pull_request into my/v2.3.0"]
NEG = [
    ("push: event workflow_dispatch", change(ci, event_name="workflow_dispatch"), "is not in the table"),
    ("push: event pull_request_target", change(ci, event_name="pull_request_target"), "is not in the table"),
    ("push: ref refs/heads/main", change(ci, ref="refs/heads/main", workflow_ref=f"{REPO}/{WF}@refs/heads/main"), "not in the table"),
    ("push: ref a tag", change(ci, ref="refs/tags/v2.3.0-sec.2-my.1", workflow_ref=f"{REPO}/{WF}@refs/tags/v2.3.0-sec.2-my.1"), "not in the table"),
    ("push: ref refs/heads/my (no name)", change(my, ref="refs/heads/my", workflow_ref=f"{REPO}/{WF}@refs/heads/my"), "not in the table"),
    ("push: ref refs/heads/my/ (empty name)", change(my, ref="refs/heads/my/", workflow_ref=f"{REPO}/{WF}@refs/heads/my/"), "not in the table"),
    ("push: ref with a space", change(my, ref="refs/heads/my/v 2", workflow_ref=f"{REPO}/{WF}@refs/heads/my/v 2"), "not in the table"),
    ("push: built commit is not GITHUB_SHA", change(ci, built_commit=OTHER), "must be GITHUB_SHA"),
    ("push: workflow_sha differs", change(ci, workflow_sha=OTHER), "workflow_sha"),
    ("push: workflow_ref of another file", change(ci, workflow_ref=f"{REPO}/.github/workflows/build.yml@refs/heads/ci/daemon-release-baseline"), "workflow_ref"),
    ("push: workflow_ref of another repository", change(ci, workflow_ref=f"someone/myzephyr/{WF}@refs/heads/ci/daemon-release-baseline"), "workflow_ref"),
    ("push: carries a pull request", change(ci, pull_request=pr["pull_request"]), "carries no pull request"),
    ("push: sha not hex", change(ci, sha="A" * 40, workflow_sha="A" * 40, built_commit="A" * 40), "40 lowercase hex"),
    ("pull_request: built commit is the merge commit", change(pr, built_commit=MERGE), "head commit"),
    ("pull_request: GITHUB_SHA is the head (not a merge)", change(pr, sha=BUILT, workflow_sha=BUILT), "test merge commit"),
    ("pull_request: ref refs/pull/7/head", change(pr, ref="refs/pull/7/head", workflow_ref=f"{REPO}/{WF}@refs/pull/7/head"), "expected refs/pull/7/merge"),
    ("pull_request: ref of another number", change(pr, ref="refs/pull/8/merge", workflow_ref=f"{REPO}/{WF}@refs/pull/8/merge"), "expected refs/pull/7/merge"),
    ("pull_request: base master", pr_ctx(base_ref="master"), "base my/<name>"),
    ("pull_request: base security/v2.3.0", pr_ctx(base_ref="security/v2.3.0"), "base my/<name>"),
    ("pull_request: base ci/daemon-release-baseline", pr_ctx(base_ref="ci/daemon-release-baseline"), "base my/<name>"),
    ("pull_request: head branch under my/", pr_ctx(head_ref="my/v2.3.0-candidate"), "must not be under my/"),
    ("pull_request: head branch ci/daemon-release-baseline", pr_ctx(head_ref="ci/daemon-release-baseline"), "must not be under my/"),
    ("pull_request: head sha is not the built commit", pr_ctx(head_sha=OTHER), "head commit"),
    ("pull_request: number zero", change(pr_ctx(number=0), ref="refs/pull/0/merge", workflow_ref=f"{REPO}/{WF}@refs/pull/0/merge"), "positive integer"),
    ("pull_request: number as string", pr_ctx(number="7"), "positive integer"),
    ("pull_request: base sha missing", pr_ctx(base_sha=None), "base_sha"),
    ("pull_request: head repository missing", pr_ctx(head_repository=None), "head repository"),
    ("pull_request: no pull request fields", change(pr, pull_request=None), "without the pull request fields"),
]
for name, ctx, frag in NEG:
    e = ri.errors(ctx)
    record(f"table: {name} refused", e and any(frag in x for x in e), e)

for text, want in (("none", None), ('{"number": 7}', ValueError), ("[]", ValueError), ("x", ValueError),
                   (json.dumps(pr["pull_request"]), pr["pull_request"])):
    try:
        got = ri.parse_pull_request(text)
        ok = got == want
    except ValueError:
        ok = want is ValueError
    record(f"parse_pull_request({text[:20]!r})", ok)


# 2. the CLI as a workflow step runs it
def cli(name, ctx, payload, want_exit, want_env=None):
    d = os.path.join(work, name.replace(" ", "-").replace("/", "-"))
    os.makedirs(d)
    ev = os.path.join(d, "event.json")
    json.dump(payload, open(ev, "w"))
    genv = os.path.join(d, "github-env")
    env = {"PATH": os.environ.get("PATH", ""), "GITHUB_EVENT_NAME": ctx["event_name"], "GITHUB_REF": ctx["ref"],
           "GITHUB_SHA": ctx["sha"], "GITHUB_WORKFLOW_SHA": ctx["workflow_sha"], "GITHUB_WORKFLOW_REF": ctx["workflow_ref"],
           "GITHUB_REPOSITORY": ctx["repository"], "GITHUB_EVENT_PATH": ev, "MYZ_BUILD_SHA": ctx["built_commit"]}
    p = subprocess.run([sys.executable, "-I", tool, "check", "--github-env", genv], env=env, capture_output=True, text=True)
    got_env = open(genv).read() if os.path.exists(genv) else ""
    ok = p.returncode == want_exit and (want_env is None or got_env == want_env)
    record(f"check: {name} -> exit {want_exit}", ok, f"exit {p.returncode}, env {got_env!r}, {p.stderr.strip()[-200:]}")


payload_pr = {"pull_request": {"number": 7, "base": {"ref": "my/v2.3.0", "sha": BASE},
                               "head": {"ref": "pr/v2.3.0-sec.2-my.1", "sha": BUILT, "repo": {"full_name": REPO}}}}
cli("push to ci/daemon-release-baseline", ci, {"ref": ci["ref"]}, 0, "MYZ_PULL_REQUEST=none\n")
cli("push to my/v2.3.0", my, {"ref": my["ref"]}, 0, "MYZ_PULL_REQUEST=none\n")
cli("pull request into my/v2.3.0", pr, payload_pr, 0,
    "MYZ_PULL_REQUEST=" + json.dumps(pr["pull_request"], sort_keys=True, separators=(",", ":")) + "\n")
cli("pull request with MYZ_BUILD_SHA set to the merge commit", change(pr, built_commit=MERGE), payload_pr, 1, "")
bad_payload = json.loads(json.dumps(payload_pr))
bad_payload["pull_request"]["base"]["ref"] = "master"
cli("pull request into master (payload)", pr, bad_payload, 1, "")
cli("push to main", change(ci, ref="refs/heads/main", workflow_ref=f"{REPO}/{WF}@refs/heads/main"), {}, 1, "")

json.dump(results, open(os.path.join(work, "results.json"), "w"), indent=2)
bad = [r for r in results if not r["ok"]]
print(f"{len(results) - len(bad)}/{len(results)} cases as intended (synthetic run identities)")
sys.exit(1 if bad else 0)
