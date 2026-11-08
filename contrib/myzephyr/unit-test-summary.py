#!/usr/bin/env python3
"""Judge one gtest run of unit_tests from its own records.

  unit-test-summary.py --list F --xml F --log F --exit-code N --expected N
                       --source-commit SHA --out F

  --list   output of "unit_tests --gtest_list_tests" (the test inventory)
  --xml    the --gtest_output=xml report of the run
  --log    the console log of the run
Writes a JSON summary (counts, names of failed/skipped/missing tests, verdict).

Verdict and exit status:
  passed           0  exit code 0, a parseable report with at least one executed
                      test, no failure, no error, no skipped test, every enabled
                      test of the inventory executed and nothing else, the log's
                      PASSED count equal to the report's, and exactly --expected
                      passed tests
  failed           1  any of the conditions above except the expected count
  review-required  3  everything passed, but the number of passed tests differs
                      from --expected (the reference count for this source); the
                      difference needs an explicit review of the inventory and is
                      never accepted automatically
Disabled tests (DISABLED_ prefix) are listed and counted, not executed.
"""
import argparse
import json
import re
import sys
import xml.etree.ElementTree as ET

EXIT = {"passed": 0, "failed": 1, "review-required": 3}


def disabled(name):
    return any(part.startswith("DISABLED_") for part in re.split(r"[./]", name))


def inventory(path):
    tests, suite = [], None
    for raw in open(path, errors="replace"):
        line = raw.rstrip("\n")
        if not line.strip():
            continue
        if not line.startswith(" "):
            word = line.split()[0]
            suite = word[:-1] if word.endswith(".") else None
            continue
        if suite is not None:
            tests.append(f"{suite}.{line.split()[0]}")
    return tests


def report(path):
    root = ET.parse(path).getroot()
    cases = []
    for tc in root.iter("testcase"):
        name = f"{tc.get('classname')}.{tc.get('name')}"
        status, result = tc.get("status"), tc.get("result")
        skipped = result == "skipped" or tc.find("skipped") is not None
        not_run = status == "notrun" or result == "suppressed"
        failed = tc.find("failure") is not None or tc.find("error") is not None
        cases.append({"name": name, "skipped": skipped, "not_run": not_run, "failed": failed})
    errors = int(root.get("errors", "0") or 0)
    return cases, errors


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    for a in ("list", "xml", "log", "source-commit", "out"):
        p.add_argument(f"--{a}", required=True)
    p.add_argument("--exit-code", type=int, required=True)
    p.add_argument("--expected", type=int, required=True)
    a = p.parse_args()

    problems = []
    inv = inventory(a.list)
    enabled = sorted(t for t in inv if not disabled(t))
    try:
        cases, errors = report(a.xml)
    except (OSError, ET.ParseError) as e:
        cases, errors = [], 0
        problems.append(f"no parseable XML report: {type(e).__name__}: {e}")
    executed = [c for c in cases if not c["not_run"] and not c["skipped"]]
    failed = sorted(c["name"] for c in executed if c["failed"])
    skipped = sorted(c["name"] for c in cases if c["skipped"])
    passed = len(executed) - len(failed)
    log = open(a.log, errors="replace").read()
    m = re.findall(r"^\[  PASSED  \] (\d+) tests?\.", log, re.M)
    log_passed = int(m[-1]) if m else None
    exe_names = sorted(c["name"] for c in executed)
    missing = sorted(set(enabled) - set(exe_names))
    unexpected = sorted(set(exe_names) - set(enabled))

    if a.exit_code != 0:
        problems.append(f"unit_tests exited {a.exit_code}")
    if not executed:
        problems.append("no test was executed")
    if failed:
        problems.append(f"{len(failed)} failed test(s)")
    if errors:
        problems.append(f"report counts {errors} error(s)")
    if skipped:
        problems.append(f"{len(skipped)} skipped test(s)")
    if not enabled:
        problems.append("the test inventory lists no enabled test")
    if missing:
        problems.append(f"{len(missing)} enabled test(s) of the inventory not executed")
    if unexpected:
        problems.append(f"{len(unexpected)} executed test(s) not in the inventory")
    if log_passed != passed:
        problems.append(f"log reports {log_passed} passed, report {passed}")
    if problems:
        verdict = "failed"
    elif passed != a.expected:
        verdict = "review-required"
        problems.append(f"{passed} passed, reference count {a.expected}: review the inventory")
    else:
        verdict = "passed"

    summary = {
        "verdict": verdict,
        "source_commit": a.source_commit,
        "exit_code": a.exit_code,
        "expected_passed": a.expected,
        "passed": passed,
        "executed": len(executed),
        "failed": failed,
        "skipped": skipped,
        "errors": errors,
        "log_passed": log_passed,
        "inventory_total": len(inv),
        "inventory_enabled": len(enabled),
        "inventory_disabled": sorted(t for t in inv if disabled(t)),
        "enabled_not_executed": missing,
        "executed_not_in_inventory": unexpected,
        "problems": problems,
    }
    with open(a.out, "w") as f:
        json.dump(summary, f, indent=2, sort_keys=True)
        f.write("\n")
    print(f"unit tests: {verdict}; passed {passed} of reference {a.expected}, executed {len(executed)}, "
          f"failed {len(failed)}, skipped {len(skipped)}, enabled in inventory {len(enabled)}")
    for t in problems:
        print(f"unit tests: {t}", file=sys.stderr)
    sys.exit(EXIT[verdict])


if __name__ == "__main__":
    main()
