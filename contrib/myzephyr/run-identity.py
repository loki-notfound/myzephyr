#!/usr/bin/env python3
"""The run identities this pipeline accepts: which event and ref may run it and which commit is built.

  run-identity.py check [--github-env FILE]   in a workflow job: read the run's own context
                                              (GITHUB_* variables, the event payload at
                                              GITHUB_EVENT_PATH and MYZ_BUILD_SHA), fail unless it
                                              is a row of the table, and write
                                              MYZ_PULL_REQUEST=<JSON or none> to FILE
                                              (normally $GITHUB_ENV)
  run-identity.py table                       print the table

Used as a module by make-manifest.py, make-cross-manifest.py, verify-artifact.py and
verify-cross-artifact.py, so the producers and every consumer apply the same table.

The table (anything else fails):

  event         ref (GITHUB_REF)                        built commit           GITHUB_SHA
  push          refs/heads/ci/daemon-release-baseline   GITHUB_SHA             = built commit
  push          refs/heads/my/<name>                    GITHUB_SHA             = built commit
  pull_request  refs/pull/<number>/merge, base my/<name> pull_request.head.sha  the test merge commit, != built

In every row GITHUB_WORKFLOW_SHA equals GITHUB_SHA and GITHUB_WORKFLOW_REF is
<repository>/.github/workflows/daemon-release-baseline.yml@<ref>. For a pull request the
merge commit is never built; the checkout is the head commit, and contrib/myzephyr/
ci-checkout.sh proves that the merge commit (whose workflow file GitHub runs) has the head's
tree and exactly the parents base.sha and head.sha, so the workflow that runs is the head's.
A pull-request head branch must not be under my/ and must not be ci/daemon-release-baseline:
those get their own push runs, and one push must start one run.
<name> is one or more path segments of letters, digits, ".", "_" and "-".
"""
import json
import os
import re
import sys

WORKFLOW_FILE = ".github/workflows/daemon-release-baseline.yml"
SHA1 = re.compile(r"[0-9a-f]{40}")
NAME = r"[A-Za-z0-9._-]+(?:/[A-Za-z0-9._-]+)*"
PUSH_REFS = (re.compile(r"refs/heads/ci/daemon-release-baseline"), re.compile(rf"refs/heads/my/{NAME}"))
PR_BASE = re.compile(rf"my/{NAME}")
PR_HEAD_FORBIDDEN = re.compile(rf"(?:my/{NAME}|ci/daemon-release-baseline)")
TABLE = [
    {"event": "push", "ref": "refs/heads/ci/daemon-release-baseline", "built_commit": "GITHUB_SHA",
     "github_sha": "= built commit", "pull_request": "none"},
    {"event": "push", "ref": "refs/heads/my/<name>", "built_commit": "GITHUB_SHA",
     "github_sha": "= built commit", "pull_request": "none"},
    {"event": "pull_request", "ref": "refs/pull/<number>/merge (base my/<name>)",
     "built_commit": "pull_request.head.sha", "github_sha": "test merge commit, != built commit",
     "pull_request": "number, base_ref, base_sha, head_sha, head_ref, head_repository"},
]
PR_KEYS = ("number", "base_ref", "base_sha", "head_sha", "head_ref", "head_repository")


def pull_request_from_payload(payload):
    """The pull-request fields the table uses, from an event payload (dict)."""
    pr = payload.get("pull_request")
    if not isinstance(pr, dict):
        return None
    base, head = pr.get("base") or {}, pr.get("head") or {}
    return {"number": pr.get("number"), "base_ref": base.get("ref"), "base_sha": base.get("sha"),
            "head_sha": head.get("sha"), "head_ref": head.get("ref"),
            "head_repository": (head.get("repo") or {}).get("full_name")}


def parse_pull_request(text):
    """--pull-request / MYZ_PULL_REQUEST: "none" or a JSON object with exactly PR_KEYS."""
    if text == "none":
        return None
    try:
        v = json.loads(text)
    except ValueError as e:
        raise ValueError(f"pull request is neither 'none' nor JSON: {e}")
    if not isinstance(v, dict) or sorted(v) != sorted(PR_KEYS):
        raise ValueError(f"pull request must be an object with exactly {list(PR_KEYS)}")
    return v


def errors(ctx):
    """Errors of a run identity: dict with event_name, ref, sha, workflow_sha, workflow_ref,
    repository, built_commit and pull_request (None or a PR_KEYS dict). Empty list = allowed."""
    e = []
    ev, ref, sha, built = ctx.get("event_name"), ctx.get("ref"), ctx.get("sha"), ctx.get("built_commit")
    pr = ctx.get("pull_request")
    for k in ("sha", "workflow_sha", "built_commit"):
        if not isinstance(ctx.get(k), str) or not SHA1.fullmatch(ctx[k]):
            e.append(f"{k} {ctx.get(k)!r} is not 40 lowercase hex digits")
    if ctx.get("workflow_sha") != sha:
        e.append(f"workflow_sha {ctx.get('workflow_sha')} differs from GITHUB_SHA {sha}")
    want_wref = f"{ctx.get('repository')}/{WORKFLOW_FILE}@{ref}"
    if ctx.get("workflow_ref") != want_wref:
        e.append(f"workflow_ref {ctx.get('workflow_ref')!r}, expected {want_wref!r}")
    if ev == "push":
        if not isinstance(ref, str) or not any(r.fullmatch(ref) for r in PUSH_REFS):
            e.append(f"push to {ref!r} is not in the table (refs/heads/ci/daemon-release-baseline, refs/heads/my/<name>)")
        if pr is not None:
            e.append("a push run carries no pull request")
        if built != sha:
            e.append(f"push run: built commit {built} must be GITHUB_SHA {sha}")
    elif ev == "pull_request":
        if not isinstance(pr, dict) or sorted(pr) != sorted(PR_KEYS):
            e.append("pull_request run without the pull request fields")
            return e
        n = pr["number"]
        if not (isinstance(n, int) and not isinstance(n, bool) and n > 0):
            e.append(f"pull request number {n!r} is not a positive integer")
        if ref != f"refs/pull/{n}/merge":
            e.append(f"pull_request run on {ref!r}, expected refs/pull/{n}/merge")
        if not isinstance(pr["base_ref"], str) or not PR_BASE.fullmatch(pr["base_ref"]):
            e.append(f"pull request into {pr['base_ref']!r} is not in the table (base my/<name>)")
        if not isinstance(pr["head_ref"], str) or not pr["head_ref"] or PR_HEAD_FORBIDDEN.fullmatch(pr["head_ref"]):
            e.append(f"pull request head branch {pr['head_ref']!r} must not be under my/ or be "
                     "ci/daemon-release-baseline (that branch has its own push run)")
        if not isinstance(pr["head_repository"], str) or not pr["head_repository"]:
            e.append("pull request head repository missing")
        for k in ("base_sha", "head_sha"):
            if not isinstance(pr[k], str) or not SHA1.fullmatch(pr[k]):
                e.append(f"pull request {k} {pr[k]!r} is not 40 lowercase hex digits")
        if pr["head_sha"] != built:
            e.append(f"pull_request run: built commit {built} must be the head commit {pr['head_sha']}")
        if sha == built:
            e.append("pull_request run: GITHUB_SHA must be the test merge commit, not the built head commit")
    else:
        e.append(f"event {ev!r} is not in the table (push, pull_request)")
    return e


def context_from_env(env):
    """The run identity of the current job, from its own environment and event payload."""
    payload = {}
    path = env.get("GITHUB_EVENT_PATH")
    if path:
        with open(path, encoding="utf-8") as f:
            payload = json.load(f)
    pr = pull_request_from_payload(payload) if env.get("GITHUB_EVENT_NAME") == "pull_request" else None
    return {"event_name": env.get("GITHUB_EVENT_NAME"), "ref": env.get("GITHUB_REF"), "sha": env.get("GITHUB_SHA"),
            "workflow_sha": env.get("GITHUB_WORKFLOW_SHA"), "workflow_ref": env.get("GITHUB_WORKFLOW_REF"),
            "repository": env.get("GITHUB_REPOSITORY"), "built_commit": env.get("MYZ_BUILD_SHA"),
            "pull_request": pr}


def main():
    argv = sys.argv[1:]
    if argv == ["table"]:
        for row in TABLE:
            print(json.dumps(row, sort_keys=True))
        return
    if not argv or argv[0] != "check" or len(argv) not in (1, 3) or (len(argv) == 3 and argv[1] != "--github-env"):
        sys.exit(__doc__)
    ctx = context_from_env(os.environ)
    errs = errors(ctx)
    print(json.dumps({k: ctx[k] for k in sorted(ctx)}, sort_keys=True))
    if errs:
        for x in errs:
            print(f"run-identity: {x}", file=sys.stderr)
        sys.exit(1)
    pr = ctx["pull_request"]
    if len(argv) == 3:
        with open(argv[2], "a", encoding="utf-8") as f:
            f.write(f"MYZ_PULL_REQUEST={'none' if pr is None else json.dumps(pr, sort_keys=True, separators=(',', ':'))}\n")
    print(f"run-identity: {ctx['event_name']} on {ctx['ref']}, built commit {ctx['built_commit']}", file=sys.stderr)


if __name__ == "__main__":
    main()
