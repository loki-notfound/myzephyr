#!/usr/bin/env python3
"""Self-test of check-upload-paths.py with trees made here. Synthetic files only.

  upload-paths-selftest.py <work-dir>      (<work-dir> must not exist)

Each refused character (double quote, colon, less than, greater than, vertical bar, asterisk,
question mark, carriage return, line feed) in a file name and in a directory name fails; a
trailing space or dot fails; a clean tree passes; --strict refuses other characters (space,
parentheses, comma, plus, apostrophe) that the upload rules allow; a symbolic link fails;
--allow-missing accepts a missing directory, without it a missing directory is a usage error.
The case directory of CI run 43069206476 ("case-tag name outside v*-sec.*-my.*") fails both.
"""
import json
import os
import subprocess
import sys

here = os.path.dirname(os.path.abspath(__file__))
tool = os.path.join(os.path.dirname(here), "check-upload-paths.py")
work = os.path.abspath(sys.argv[1]) if len(sys.argv) == 2 else sys.exit(__doc__)
if os.path.lexists(work):
    sys.exit(f"{work} exists")
os.makedirs(work)
results = []
n = [0]


def record(name, ok, detail=""):
    results.append({"case": name, "ok": bool(ok), "detail": detail})
    print(f"{'ok  ' if ok else 'FAIL'} {name}" + (f" -- {detail}" if detail and not ok else ""))


def tree(entries):
    """entries: relative paths; a trailing '/' makes a directory. Returns the tree's top."""
    n[0] += 1
    top = os.path.join(work, f"t{n[0]:03d}")
    os.makedirs(top)
    for e in entries:
        p = os.path.join(top, e)
        if e.endswith("/"):
            os.makedirs(p, exist_ok=True)
        else:
            os.makedirs(os.path.dirname(p), exist_ok=True)
            open(p, "w").write("x\n")
    return top


def check(*args):
    p = subprocess.run([sys.executable, "-I", tool, *args], capture_output=True, text=True)
    return p.returncode, p.stdout + p.stderr


def expect(name, entries, want, *flags, frag=""):
    top = tree(entries)
    rc, out = check(*flags, top)
    record(name, rc == want and frag in out, f"exit {rc} (want {want}): {out.strip()[-300:]!r}")


expect("clean tree passes (upload rules)", ["a/b.txt", "c-d_e.1/f.json", "g/"], 0)
expect("clean tree passes (strict)", ["a/b.txt", "c-d_e.1/f.json", "g/"], 0, "--strict")
names = {'"': "double quote", ":": "colon", "<": "less than", ">": "greater than", "|": "vertical bar",
         "*": "asterisk", "?": "question mark", "\r": "carriage return", "\n": "line feed"}
for ch, label in names.items():
    expect(f"{label} in a file name fails", [f"d/x{ch}y.txt"], 1, frag=label)
    expect(f"{label} in a directory name fails", [f"d{ch}e/x.txt"], 1, frag=label)
expect("trailing space in a component fails", ["d /x.txt"], 1, frag="ends with a space or a dot")
expect("trailing dot in a component fails", ["d/x."], 1, frag="ends with a space or a dot")
expect("CI run 43069206476 case directory fails (upload rules)", ["case-tag name outside v*-sec.*-my.*/artifacts.json"], 1,
       frag="asterisk")
expect("CI run 43069206476 case directory fails (strict)", ["case-tag name outside v*-sec.*-my.*/artifacts.json"], 1,
       "--strict", frag="outside A-Za-z0-9._-")
for label, comp in (("space", "a b"), ("parentheses", "a(b)"), ("comma", "a,b"), ("plus", "a+b"), ("apostrophe", "a'b")):
    expect(f"{label}: allowed by the upload rules", [f"{comp}/x.txt"], 0)
    expect(f"{label}: refused by --strict", [f"{comp}/x.txt"], 1, "--strict", frag="outside A-Za-z0-9._-")
top = tree(["real/x.txt"])
os.symlink("real", os.path.join(top, "link"))
rc, out = check(top)
record("symbolic link fails", rc == 1 and "symbolic link" in out, out.strip()[-200:])
rc, out = check("--allow-missing", os.path.join(work, "missing"))
record("--allow-missing: missing directory reported, exit 0", rc == 0 and "does not exist" in out, out.strip())
rc, out = check(os.path.join(work, "missing"))
record("missing directory without --allow-missing -> exit 2", rc == 2, out.strip())
rc, out = check()
record("no arguments -> exit 2", rc == 2, out.strip())
json.dump(results, open(os.path.join(work, "results.json"), "w"), indent=2)
bad = [r for r in results if not r["ok"]]
print(f"{len(results) - len(bad)}/{len(results)} cases as expected")
sys.exit(1 if bad else 0)
