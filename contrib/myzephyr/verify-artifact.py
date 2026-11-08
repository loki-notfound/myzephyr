#!/usr/bin/env python3
"""Check that a downloaded release artifact belongs to the commit under test.

  verify-artifact.py <artifact-dir> <expected-commit>

Fails (exit 1) unless every file listed in SHA256SUMS matches, SHA256SUMS covers
zephyrd, manifest.json and expected-version.txt, the manifest's source commit and
workflow commit equal <expected-commit>, the manifest's binary hash equals
zephyrd's, and expected-version.txt equals the manifest's expected version.
Prints the expected version on success.
"""
import hashlib
import json
import os
import re
import sys


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    if len(sys.argv) != 3 or not re.fullmatch(r"[0-9a-f]{40}", sys.argv[2]):
        sys.exit("usage: verify-artifact.py <artifact-dir> <expected-commit (40 hex)>")
    d, commit = sys.argv[1], sys.argv[2]
    problems = []
    sums = {}
    for line in open(os.path.join(d, "SHA256SUMS")):
        m = re.fullmatch(r"([0-9a-f]{64}) [ *](\S+)\n?", line)
        if not m:
            problems.append(f"malformed SHA256SUMS line: {line!r}")
            continue
        sums[m.group(2)] = m.group(1)
    for name in ("zephyrd", "manifest.json", "expected-version.txt"):
        if name not in sums:
            problems.append(f"SHA256SUMS does not cover {name}")
    for name, want in sums.items():
        path = os.path.join(d, name)
        if os.path.basename(name) != name or not os.path.isfile(path):
            problems.append(f"{name}: listed but not a file in the artifact")
        elif sha256(path) != want:
            problems.append(f"{name}: hash mismatch")
    if problems:
        sys.exit("verify-artifact: " + "; ".join(problems))
    m = json.load(open(os.path.join(d, "manifest.json")))
    expected = open(os.path.join(d, "expected-version.txt")).read().strip()
    if m.get("source", {}).get("commit") != commit:
        problems.append(f"manifest source commit {m.get('source', {}).get('commit')}, expected {commit}")
    if m.get("workflow", {}).get("sha") != commit:
        problems.append(f"manifest workflow commit {m.get('workflow', {}).get('sha')}, expected {commit}")
    if m.get("artifact", {}).get("sha256") != sums["zephyrd"]:
        problems.append("manifest binary hash differs from zephyrd")
    if m.get("artifact", {}).get("expected_version") != expected:
        problems.append("expected-version.txt differs from the manifest")
    if problems:
        sys.exit("verify-artifact: " + "; ".join(problems))
    print(expected)


if __name__ == "__main__":
    main()
