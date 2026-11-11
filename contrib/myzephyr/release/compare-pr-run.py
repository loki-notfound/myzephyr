#!/usr/bin/env python3
"""Compare this push run's binary hashes with those of the pull-request run of the same commit.

  compare-pr-run.py --repository OWNER/NAME --commit SHA --run-id N --sums SHA256SUMS-LINES...
                    [--summary FILE] [--api URL]

A reproducibility measurement, reported and never a gate: this script always exits 0. Every
build job uploads a marker artifact named binary-sha256-<platform>-<sha256 of its binary>
next to its build artifact, so another run's hashes can be read from the artifact names
alone. The workflow's token has contents: read only and cannot download another run's
artifacts; the names are read from GitHub's public REST API without a token (public
repository; rate-limited per address, so "not available" is a possible outcome). Runs:
pull_request runs of daemon-release-baseline.yml whose head_sha is --commit.
--sums: "<platform>=<sha256>" for this run. Writes a Markdown table to --summary
(GITHUB_STEP_SUMMARY) and to stdout.
"""
import argparse
import json
import re
import sys
import urllib.error
import urllib.request

MARKER = re.compile(r"binary-sha256-([a-z0-9_-]+)-([0-9a-f]{64})")
WORKFLOW_PATH = ".github/workflows/daemon-release-baseline.yml"


def get(api, path):
    req = urllib.request.Request(f"{api}{path}", headers={"Accept": "application/vnd.github+json",
                                                          "User-Agent": "myzephyr-compare-pr-run"})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=20) as r:
        return json.loads(r.read().decode("utf-8"))


def compare(api, repo, commit):
    """{run id: {platform: sha256}} of the pull-request runs of commit, or raises."""
    runs = get(api, f"/repos/{repo}/actions/runs?event=pull_request&head_sha={commit}&per_page=20")
    out = {}
    for run in runs.get("workflow_runs", []):
        if run.get("path") != WORKFLOW_PATH or run.get("head_sha") != commit:
            continue
        arts = get(api, f"/repos/{repo}/actions/runs/{run['id']}/artifacts?per_page=100")
        hashes = {}
        for a in arts.get("artifacts", []):
            m = MARKER.fullmatch(a.get("name", ""))
            if m and not a.get("expired"):
                hashes[m.group(1)] = m.group(2)
        out[run["id"]] = {"attempt": run.get("run_attempt"), "conclusion": run.get("conclusion"), "hashes": hashes}
    return out


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--repository", required=True)
    p.add_argument("--commit", required=True)
    p.add_argument("--run-id", required=True)
    p.add_argument("--sums", nargs="+", required=True)
    p.add_argument("--summary")
    p.add_argument("--api", default="https://api.github.com")
    a = p.parse_args()
    mine = dict(s.split("=", 1) for s in a.sums)
    lines = ["### Reproducibility: this push run against the pull-request run of the same commit (not a gate)", ""]
    try:
        runs = compare(a.api, a.repository, a.commit)
    except (urllib.error.URLError, OSError, ValueError, KeyError, TypeError) as e:
        runs = None
        lines.append(f"Not available: {type(e).__name__}: {e}")
    if runs is not None and not runs:
        lines.append(f"Not available: no pull-request run of {a.commit} found (none, or its artifacts expired).")
    for rid, info in sorted((runs or {}).items()):
        lines += [f"Pull-request run {rid} (attempt {info['attempt']}, {info['conclusion']}) against push run {a.run_id}:", "",
                  "| platform | push run | pull-request run | equal |", "|---|---|---|---|"]
        for plat in sorted(mine):
            other = info["hashes"].get(plat)
            eq = "not available" if other is None else ("yes" if other == mine[plat] else "**no**")
            lines.append(f"| {plat} | `{mine[plat]}` | `{other or '-'}` | {eq} |")
        lines.append("")
    text = "\n".join(lines) + "\n"
    print(text)
    if a.summary:
        with open(a.summary, "a", encoding="utf-8") as f:
            f.write(text)
    return 0


if __name__ == "__main__":
    try:
        main()
    except Exception as e:   # never a gate
        print(f"compare-pr-run: not available: {type(e).__name__}: {e}")
    sys.exit(0)
