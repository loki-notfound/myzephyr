#!/usr/bin/env python3
"""Check strings a zephyrd build must embed, by reading the file. Nothing is executed.

  check-embedded.py <binary> <expected-version> <report-file>

Fails (exit 1) unless the binary contains, as NUL-terminated byte strings:
  - the expected version "<number>-release" or "<number>-<sha9>" (what --version prints
    inside "(v...)"), and no other "2.3.0-<suffix>" version string of that form;
  - each mainnet seed of src/p2p/net_node.inl: 142.93.255.216:17766, 142.93.98.116:17766,
    24.199.101.125:17766.
Used where the binary cannot be executed on the build machine (cross builds); the native
runtime job then checks --version by running it.
"""
import hashlib
import re
import sys

SEEDS = ("142.93.255.216:17766", "142.93.98.116:17766", "24.199.101.125:17766")
VERSION_RE = re.compile(rb"(?<![0-9A-Za-z.])(\d+\.\d+\.\d+-(?:release|[0-9a-f]{9}))\0")


def main():
    if len(sys.argv) != 4:
        sys.exit("usage: check-embedded.py <binary> <expected-version> <report-file>")
    path, expected, report = sys.argv[1:]
    if not re.fullmatch(r"\d+\.\d+\.\d+-(release|[0-9a-f]{9})", expected):
        sys.exit(f"check-embedded: expected version {expected!r} has not the form <number>-release|<sha9>")
    d = open(path, "rb").read()
    problems = []
    versions = sorted({m.group(1).decode() for m in VERSION_RE.finditer(d)})
    if expected not in versions:
        problems.append(f"version string {expected} not embedded (found {versions})")
    others = [v for v in versions if v != expected]
    if others:
        problems.append(f"other version strings embedded: {others}")
    seeds = {s: (s.encode() + b"\0") in d for s in SEEDS}
    for s, found in seeds.items():
        if not found:
            problems.append(f"mainnet seed {s} not embedded")
    lines = [f"embedded_sha256={hashlib.sha256(d).hexdigest()}",
             f"embedded_versions={' '.join(versions) or 'none'}",
             f"embedded_expected_version={expected}",
             f"embedded_seeds={' '.join(s for s, f in seeds.items() if f)}",
             f"embedded_checks={'failed' if problems else 'passed'}"]
    with open(report, "w") as f:
        f.write("\n".join(lines) + "\n")
    print("\n".join(lines))
    for p in problems:
        print(f"check-embedded: {p}", file=sys.stderr)
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
