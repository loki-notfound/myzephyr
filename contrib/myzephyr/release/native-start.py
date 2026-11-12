#!/usr/bin/env python3
"""Outcome of the optional native macOS arm64 start test, for the release set.

  native-start.py wait --repository OWNER/NAME --run-id N --run-attempt N
                       --job-name NAME [--job-name NAME ...] --limit SECONDS [--poll SECONDS]
                       [--api URL] --out FILE
  native-start.py classify --job FILE [--job FILE ...] [--limit-reached] --out FILE

The macOS arm64 start test runs on hosted Apple Silicon runners that are not always available
(owner decision 2026-11-12: build and static check required, native start not required). It
runs as one leg per runner label (macos-15 and macos-26), so one free runner of either image is
enough. The package job does not depend on those jobs; it reads their state from GitHub's REST
API with the workflow token (actions: read) until every leg has completed or --limit seconds
have passed, whichever comes first: one bounded wait for all legs together.

Each leg is one of:
  passed   the job completed with success and its three start steps (version output, strict
           offline start, default discovery) succeeded: the binary was started natively;
  failed   one of those three steps failed, was cancelled or timed out: the binary was run and
           a start check did not pass;
  not-run  the binary was not started on that leg: runner not acquired (cancelled before any
           step), cancelled or failed before the first start step, skipped, or not completed
           when the wait ended (with its status).
The platform's outcome: failed if any leg failed (such a set is written but never released);
otherwise passed if at least one leg passed; otherwise not-run, with every leg's reason.
A job name missing from the run attempt is a configuration error (exit 1). API errors are
retried until the limit; a leg whose state was never read is not-run with the error.
Output: JSON with platform, status, reason, the legs (job name, status, reason, runner label
and name, job id and URL, the conclusion of each start step) and the time read. This script
never changes anything.
"""
import argparse
import datetime
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

START_STEPS = ("Version output of the verified binary",
               "Strict offline start with clean shutdown and no listener left",
               "Default discovery from an empty directory (no peer options)")
BAD = ("failure", "cancelled", "timed_out")


def utc():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def classify(job, limit_reached=False):
    """job: one entry of GET /repos/{r}/actions/runs/{id}/attempts/{n}/jobs. Returns that leg's outcome."""
    steps = {s.get("name"): s.get("conclusion") for s in job.get("steps") or []}
    checks = {n: steps.get(n) for n in START_STEPS}
    labels = job.get("labels") or []
    out = {"job_name": job.get("name"), "job_id": job.get("id"), "job_url": job.get("html_url"),
           "runner_label": labels[0] if len(labels) == 1 else None, "runner_name": job.get("runner_name") or None,
           "checks": checks}
    status, conclusion = job.get("status"), job.get("conclusion")
    if any(checks[n] in BAD for n in START_STEPS):
        bad = next(n for n in START_STEPS if checks[n] in BAD)
        return dict(out, status="failed", reason=f"start step '{bad}' ended {checks[bad]}")
    if status == "completed" and conclusion == "success" and all(checks[n] == "success" for n in START_STEPS):
        return dict(out, status="passed", reason=None)
    if status != "completed":
        why = f"job not completed when the package job's wait ended (status {status})" if limit_reached \
            else f"job not completed (status {status})"
        return dict(out, status="not-run", reason=why)
    if conclusion == "cancelled" and not steps:
        return dict(out, status="not-run", reason="runner not acquired: job cancelled before any step")
    if conclusion == "skipped":
        return dict(out, status="not-run", reason="job skipped")
    if conclusion in ("cancelled", "failure", "timed_out"):
        first = next((n for n, c in steps.items() if c in BAD), None)
        return dict(out, status="not-run", reason=f"job {conclusion} before the binary was started"
                    + (f" (step '{first}')" if first else ""))
    # completed, success, but a start step neither succeeded nor failed: not a native start
    return dict(out, status="not-run", reason=f"job {conclusion} without the start steps "
                f"({', '.join(f'{n}: {c}' for n, c in checks.items())})")


def unread(name, why):
    return {"job_name": name, "job_id": None, "job_url": None, "runner_label": None, "runner_name": None,
            "checks": {n: None for n in START_STEPS}, "status": "not-run", "reason": why}


def leg_label(leg):
    return leg["runner_label"] or leg["job_name"]


def combine(legs):
    """The platform's outcome from its legs (failed > passed > not-run)."""
    failed = [l for l in legs if l["status"] == "failed"]
    passed = [l for l in legs if l["status"] == "passed"]
    if failed:
        status = "failed"
        reason = "; ".join(f"{leg_label(l)}: {l['reason']}" for l in failed)
    elif passed:
        status, reason = "passed", None
    else:
        status = "not-run"
        reason = "; ".join(f"{leg_label(l)}: {l['reason']}" for l in legs)
    return {"platform": "macos-arm64", "status": status, "reason": reason, "legs": legs}


def get(api, path, token):
    h = {"Accept": "application/vnd.github+json", "User-Agent": "myzephyr-native-start"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(urllib.request.Request(f"{api}{path}", headers=h), timeout=20) as r:
        return json.loads(r.read().decode("utf-8"))


def wait(a):
    token = os.environ.get("GITHUB_TOKEN", "")
    path = (f"/repos/{a.repository}/actions/runs/{urllib.parse.quote(str(a.run_id))}/attempts/"
            f"{urllib.parse.quote(str(a.run_attempt))}/jobs?per_page=100")
    end = time.monotonic() + a.limit
    last_err, jobs, polls = None, {}, 0
    while True:
        polls += 1
        try:
            listed = get(a.api, path, token).get("jobs", [])
            for name in a.job_name:
                found = [j for j in listed if j.get("name") == name]
                if len(found) != 1:
                    raise SystemExit(f"native-start: {len(found)} jobs named {name!r} in run {a.run_id} "
                                     f"attempt {a.run_attempt}; expected exactly one")
                jobs[name] = found[0]
            last_err = None
            if all(j.get("status") == "completed" for j in jobs.values()):
                return combine([classify(jobs[n]) for n in a.job_name]), polls
        except (urllib.error.URLError, OSError, ValueError) as e:
            last_err = f"{type(e).__name__}: {e}"
        if time.monotonic() >= end:
            break
        time.sleep(min(a.poll, max(0.0, end - time.monotonic())))
    legs = [classify(jobs[n], limit_reached=True) if n in jobs
            else unread(n, f"job state not readable within {int(a.limit)} s: {last_err}") for n in a.job_name]
    return combine(legs), polls


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    w = sub.add_parser("wait")
    w.add_argument("--repository", required=True)
    w.add_argument("--run-id", required=True)
    w.add_argument("--run-attempt", required=True)
    w.add_argument("--job-name", action="append", required=True, help="one per leg, in the order to report")
    w.add_argument("--limit", type=float, required=True, help="seconds for all legs together; the wait never exceeds this")
    w.add_argument("--poll", type=float, default=30)
    w.add_argument("--api", default="https://api.github.com")
    w.add_argument("--out", required=True)
    c = sub.add_parser("classify")
    c.add_argument("--job", action="append", required=True, help="one job record (JSON) per leg, as the jobs API returns it")
    c.add_argument("--limit-reached", action="store_true")
    c.add_argument("--out", required=True)
    a = p.parse_args()
    if a.cmd == "wait":
        if len(set(a.job_name)) != len(a.job_name):
            raise SystemExit("native-start: each --job-name once")
        t0 = time.monotonic()
        res, polls = wait(a)
        res.update(read_at=utc(), waited_seconds=round(time.monotonic() - t0, 1), polls=polls, limit_seconds=a.limit)
    else:
        legs = [classify(json.load(open(f, encoding="utf-8")), a.limit_reached) for f in a.job]
        res = dict(combine(legs), read_at=utc())
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(res, f, indent=2, sort_keys=True)
        f.write("\n")
    print(f"native start macos-arm64: {res['status']}" + (f" ({res['reason']})" if res["reason"] else "") + "; "
          + "; ".join(f"{leg_label(l)} {l['status']}" for l in res["legs"]))


if __name__ == "__main__":
    main()
