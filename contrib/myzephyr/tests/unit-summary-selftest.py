#!/usr/bin/env python3
"""Self-test of unit-test-summary.py with small fixed fixtures.

  unit-summary-selftest.py <work-dir>     (<work-dir> must not exist)

The fixtures are invented three-test gtest records written by this script. They
test the judging logic only; they are not results of the daemon's unit tests.
Exit 0 when every case gives the intended verdict, 1 otherwise.
"""
import json
import os
import subprocess
import sys

here = os.path.dirname(os.path.abspath(__file__))
summary_py = os.path.join(os.path.dirname(here), "unit-test-summary.py")
work = sys.argv[1] if len(sys.argv) == 2 else sys.exit("usage: unit-summary-selftest.py <work-dir>")
if os.path.lexists(work):
    sys.exit(f"{work} exists")
os.makedirs(work)
COMMIT = "0" * 40

LIST = "Alpha.\n  one\n  two\nBeta/Typed/0.  # TypeParam = int\n  three\n"
LIST_DISABLED = LIST + "Gamma.\n  DISABLED_four\n"
LIST_EXTRA = LIST + "Gamma.\n  four\n"


def case(name, status="run", result="completed", child=""):
    suite, test = name.rsplit(".", 1)
    return (f'    <testcase name="{test}" status="{status}" result="{result}" time="0" classname="{suite}">'
            f"{child}</testcase>\n")


def xml(cases, errors=0):
    body = "".join(cases)
    return (f'<?xml version="1.0" encoding="UTF-8"?>\n<testsuites tests="{len(cases)}" failures="0" '
            f'disabled="0" errors="{errors}" name="AllTests">\n  <testsuite name="all">\n{body}  </testsuite>\n</testsuites>\n')


def log(passed):
    return f"[==========] {passed} tests ran.\n[  PASSED  ] {passed} tests.\n"


THREE = [case("Alpha.one"), case("Alpha.two"), case("Beta/Typed/0.three")]
FAIL_ONE = [case("Alpha.one"), case("Alpha.two", child='<failure message="x"/>'), case("Beta/Typed/0.three")]
SKIP_ONE = [case("Alpha.one"), case("Alpha.two", result="skipped", child="<skipped/>"), case("Beta/Typed/0.three")]
DISABLED_NOT_RUN = THREE + [case("Gamma.DISABLED_four", status="notrun", result="suppressed")]

cases = [
    # name, list, xml text (None: no file), log, exit code, expected count, verdict
    ("all pass, count equals reference", LIST, xml(THREE), log(3), 0, 3, "passed"),
    ("all pass, count differs from reference", LIST, xml(THREE), log(3), 0, 1006, "review-required"),
    ("one failure", LIST, xml(FAIL_ONE), log(2), 1, 3, "failed"),
    ("one failure even with exit 0", LIST, xml(FAIL_ONE), log(2), 0, 2, "failed"),
    ("one skipped test", LIST, xml(SKIP_ONE), log(2), 0, 2, "failed"),
    ("nothing executed", "", xml([]), log(0), 0, 0, "failed"),
    ("missing XML report", LIST, None, log(3), 0, 3, "failed"),
    ("truncated XML report", LIST, xml(THREE)[:120], log(3), 0, 3, "failed"),
    ("nonzero exit with a clean report", LIST, xml(THREE), log(3), 134, 3, "failed"),
    ("enabled test in inventory not executed", LIST_EXTRA, xml(THREE), log(3), 0, 3, "failed"),
    ("executed test not in inventory", "Alpha.\n  one\n  two\n", xml(THREE), log(3), 0, 3, "failed"),
    ("log count disagrees with report", LIST, xml(THREE), log(4), 0, 3, "failed"),
    ("report counts errors", LIST, xml(THREE, errors=1), log(3), 0, 3, "failed"),
    ("disabled test listed and not run", LIST_DISABLED, xml(DISABLED_NOT_RUN), log(3), 0, 3, "passed"),
]

failures = []
for i, (name, lst, x, lg, rc, expected, want) in enumerate(cases):
    d = os.path.join(work, f"case-{i:02d}")
    os.makedirs(d)
    for fn, text in (("list.txt", lst), ("unit-tests.log", lg)):
        with open(os.path.join(d, fn), "w") as f:
            f.write(text)
    if x is not None:
        with open(os.path.join(d, "unit-tests.xml"), "w") as f:
            f.write(x)
    out = os.path.join(d, "summary.json")
    p = subprocess.run([sys.executable, "-I", summary_py, "--list", os.path.join(d, "list.txt"),
                        "--xml", os.path.join(d, "unit-tests.xml"), "--log", os.path.join(d, "unit-tests.log"),
                        "--exit-code", str(rc), "--expected", str(expected), "--source-commit", COMMIT,
                        "--out", out], capture_output=True, text=True)
    got = json.load(open(out))["verdict"] if os.path.exists(out) else None
    want_exit = {"passed": 0, "failed": 1, "review-required": 3}[want]
    ok = got == want and p.returncode == want_exit
    print(f"{'ok  ' if ok else 'FAIL'} {name}: verdict {got} exit {p.returncode} (want {want}, {want_exit})")
    if not ok:
        failures.append(name)
print(f"{len(cases) - len(failures)}/{len(cases)} cases as expected")
sys.exit(1 if failures else 0)
