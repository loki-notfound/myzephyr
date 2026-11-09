#!/usr/bin/env python3
"""Self-test of the preflight of linux/run-unit-tests.sh with stub commands.

  unit-preflight-selftest.py <work-dir> [--runner <script>]

<work-dir> must not exist. Each case builds its own fixture: a source tree whose
build/tests/tests/unit_tests/unit_tests and test_notifier are small stub scripts
(not the daemon's tests; the stub records every invocation and reports one invented
passing test), and a directory of stub commands put first in PATH: id, stat (only
"stat -c %d /"), cat (only paths under /sys/dev/block; the fixture device is 259:77),
readelf, ldd and, for the diagnostic container mode, an engine stub that runs the
command on this host with the /src and /logs mounts translated. Every other command
is the real one. The cases test the script's own checks only; they are not results
of the unit tests and say nothing about any host's sysfs.

Each failing prerequisite must make run-unit-tests.sh exit 2 before the test
executable is invoked (no inventory, no run). The valid cases must reach the stub
and pass the judge with EXPECTED_PASSED=1. --runner selects another copy of the
script (used for a negative control against an older version).
Exit 0 when every case gives the intended result, 1 otherwise.
"""
import json
import os
import shutil
import subprocess
import sys

here = os.path.dirname(os.path.abspath(__file__))
args = sys.argv[1:]
runner = os.path.join(os.path.dirname(here), "linux", "run-unit-tests.sh")
if len(args) == 3 and args[1] == "--runner":
    runner = os.path.abspath(args[2])
    args = args[:1]
if len(args) != 1:
    sys.exit("usage: unit-preflight-selftest.py <work-dir> [--runner <script>]")
work = os.path.abspath(args[0])
if os.path.lexists(work):
    sys.exit(f"{work} exists")
os.makedirs(work)

REAL = {}
for tool in ("bash", "cat", "stat", "id", "git"):
    REAL[tool] = shutil.which(tool) or sys.exit(f"{tool} not found")
MAJOR, MINOR = 259, 77
DEV = (MINOR & 0xff) | ((MAJOR & 0xfff) << 8) | ((MINOR & ~0xff) << 12) | ((MAJOR & ~0xfff) << 32)
SYS = f"/sys/dev/block/{MAJOR}:{MINOR}"
SELF_ATTR, PARENT_ATTR = f"{SYS}/queue/rotational", f"{SYS}/../queue/rotational"

# defaults: a native host with a readable attribute, a present interpreter, libraries found
BASE = {"engine": "native", "uid": "1000", "stat_root": "ok", "self": "0", "parent": "absent",
        "readelf_l": "ok", "readelf_d": "ok", "ldd": "ok"}

CASES = [
    # name, overrides, exit, test executable invoked, fragments in stderr
    ("valid prerequisites (own attribute)", {}, 0, True, []),
    ("valid prerequisites (parent attribute only)", {"self": "absent", "parent": "1"}, 0, True, []),
    ("loader exits nonzero without 'not found'", {"ldd": "fail-plain"}, 2, False,
     ["'ldd tests/unit_tests/unit_tests' failed (exit 1)", "simulated loader failure"]),
    ("loader exits nonzero with 'not found'", {"ldd": "fail-notfound"}, 2, False,
     ["'ldd tests/unit_tests/unit_tests' failed (exit 1)", "libfixture.so.1 => not found"]),
    ("loader exits zero but reports a missing library", {"ldd": "zero-notfound"}, 2, False,
     ["shared libraries of unit_tests not found here", "libfixture.so.1 => not found"]),
    ("loader command missing", {"ldd": "missing"}, 2, False,
     ["'ldd tests/unit_tests/unit_tests' failed (exit 127)"]),
    ("readelf -lW fails", {"readelf_l": "fail"}, 2, False, ["'readelf -lW tests/unit_tests/unit_tests' failed (exit 1"]),
    ("readelf -dW fails", {"readelf_d": "fail"}, 2, False, ["'readelf -dW tests/unit_tests/unit_tests' failed (exit 1)"]),
    ("no program interpreter reported", {"readelf_l": "nointerp"}, 2, False, ["no program interpreter for unit_tests"]),
    ("interpreter missing", {"readelf_l": "missinginterp"}, 2, False, ["of unit_tests not present"]),
    ("stat of / fails", {"stat_root": "fail"}, 2, False, ["'stat -c %d /' failed (exit 1"]),
    ("native: both rotational attributes absent", {"self": "absent", "parent": "absent"}, 2, False,
     [f"device {MAJOR}:{MINOR}) has no readable queue/rotational attribute", "no test was started"]),
    ("native: own attribute absent, parent unreadable", {"self": "absent", "parent": "unreadable"}, 2, False,
     ["has no readable queue/rotational attribute"]),
    ("native: first readable attribute not a number", {"self": "x", "parent": "1"}, 2, False,
     [f"attribute at {SELF_ATTR} that is not a number"]),
    ("root user rejected", {"uid": "0"}, 2, False, ["running as root"]),
    ("diagnostic container mode: attributes absent, suite still runs",
     {"engine": "docker", "self": "absent", "parent": "absent"}, 0, True,
     ["PRECONDITION:", "Diagnostic mode runs the full suite anyway"]),
    ("diagnostic container mode: loader failure still stops", {"engine": "docker", "ldd": "fail-plain"}, 2, False,
     ["'ldd tests/unit_tests/unit_tests' failed (exit 1)"]),
]


def write(path, text, mode=0o644):
    with open(path, "w") as f:
        f.write(text)
    os.chmod(path, mode)


def sh_value(behaviour):
    if behaviour == "absent":
        return 'echo "cat: $1: No such file or directory" >&2; exit 1'
    if behaviour == "unreadable":
        return 'echo "cat: $1: Permission denied" >&2; exit 1'
    return f"printf '%s\\n' '{behaviour}'; exit 0"


def make_case(d, c):
    bindir, src, home = os.path.join(d, "bin"), os.path.join(d, "src"), os.path.join(d, "engine-home")
    for p in (bindir, os.path.join(src, "build/tests/tests/unit_tests"), os.path.join(src, "tests/data"),
              os.path.join(d, "tmp"), home):
        os.makedirs(p)
    calls = os.path.join(d, "invocations.log")
    interp = os.path.join(d, "fixture-ld.so")
    write(interp, "fixture interpreter placeholder\n")
    if c["readelf_l"] == "missinginterp":
        interp = os.path.join(d, "absent-ld.so")
    ut = os.path.join(src, "build/tests/tests/unit_tests")
    write(os.path.join(ut, "unit_tests"), f"""#!{REAL['bash']}
# stub test executable of the preflight self-test: one invented passing test
printf '%s\\n' "$*" >> '{calls}'
for a in "$@"; do
  case "$a" in
    --gtest_list_tests) printf 'Fixture.\\n  one\\n'; exit 0 ;;
    --gtest_output=xml:*) xml=${{a#--gtest_output=xml:}} ;;
  esac
done
cat > "$xml" <<'X'
<?xml version="1.0" encoding="UTF-8"?>
<testsuites tests="1" failures="0" disabled="0" errors="0" name="AllTests">
  <testsuite name="Fixture">
    <testcase name="one" status="run" result="completed" time="0" classname="Fixture"></testcase>
  </testsuite>
</testsuites>
X
printf '[==========] 1 test ran.\\n[  PASSED  ] 1 test.\\n'
""", 0o755)
    write(os.path.join(ut, "test_notifier"), f"""#!{REAL['bash']}
printf 'test_notifier %s\\n' "$*" >> '{calls}'
exit 1
""", 0o755)
    write(os.path.join(bindir, "id"), f"""#!{REAL['bash']}
case "$*" in -u) echo {c['uid']} ;; -g) echo 1000 ;; *) exec {REAL['id']} "$@" ;; esac
""", 0o755)
    stat_root = (f'echo "stat: cannot statx \'/\': fixture failure" >&2; exit 1' if c["stat_root"] == "fail"
                 else f"echo {DEV}; exit 0")
    write(os.path.join(bindir, "stat"), f"""#!{REAL['bash']}
if [ "$*" = "-c %d /" ]; then {stat_root}; fi
exec {REAL['stat']} "$@"
""", 0o755)
    write(os.path.join(bindir, "cat"), f"""#!{REAL['bash']}
case "$*" in
  {SELF_ATTR}) {sh_value(c['self'])} ;;
  {PARENT_ATTR}) {sh_value(c['parent'])} ;;
  /sys/dev/block/*) echo "cat: $1: not part of the fixture" >&2; exit 1 ;;
esac
exec {REAL['cat']} "$@"
""", 0o755)
    prog = ("Program Headers:\n  Type Offset VirtAddr PhysAddr FileSiz MemSiz Flg Align\n"
            "  PHDR 0x000040 0x0000000000000040 0x0000000000000040 0x0002d8 0x0002d8 R 0x8\n")
    if c["readelf_l"] != "nointerp":
        prog += ("  INTERP 0x000318 0x0000000000000318 0x0000000000000318 0x00001c 0x00001c R 0x1\n"
                 f"      [Requesting program interpreter: {interp}]\n")
    dyn = (" 0x0000000000000001 (NEEDED)             Shared library: [libfixture.so.1]\n"
           " 0x0000000000000001 (NEEDED)             Shared library: [libc.so.6]\n")
    fail = 'echo "readelf: Error: fixture failure" >&2; exit 1'
    write(os.path.join(bindir, "readelf"), f"""#!{REAL['bash']}
case "$1" in
  -lW) {fail if c['readelf_l'] == 'fail' else 'cat <<' + "'P'" + chr(10) + prog + 'P' + chr(10) + '   exit 0'} ;;
  -dW) {fail if c['readelf_d'] == 'fail' else 'cat <<' + "'P'" + chr(10) + dyn + 'P' + chr(10) + '   exit 0'} ;;
esac
echo "readelf fixture: unexpected $*" >&2; exit 64
""", 0o755)
    ok_out = "\tlinux-vdso.so.1 (0x00007ffd00000000)\n\tlibfixture.so.1 => /fixture/libfixture.so.1 (0x00007f0000000000)\n"
    nf_out = "\tlinux-vdso.so.1 (0x00007ffd00000000)\n\tlibfixture.so.1 => not found\n"
    ldd = {"ok": f"printf '{ok_out}'; exit 0",
           "fail-plain": 'echo "simulated loader failure" >&2; exit 1',
           "fail-notfound": f"printf '{nf_out}'; exit 1",
           "zero-notfound": f"printf '{nf_out}'; exit 0",
           "missing": 'echo "bash: line 1: ldd: command not found" >&2; exit 127'}[c["ldd"]]
    write(os.path.join(bindir, "ldd"), f"#!{REAL['bash']}\n{ldd}\n", 0o755)
    # container engine stub: "docker run [options] IMAGE CMD..." runs CMD here, with the
    # mounted container paths replaced by the host paths and HOME in the case directory
    write(os.path.join(bindir, "docker"), f"""#!{sys.executable} -I
import os, sys
a = sys.argv[1:]
with open({os.path.join(d, 'engine-invocations.log')!r}, "a") as f:
    f.write(" ".join(a) + "\\n")
assert a[0] == "run", a
i, env, vols, wd = 1, {{}}, [], None
while a[i].startswith("-"):
    if a[i] == "--rm" or a[i].startswith("--userns="):
        i += 1
        continue
    opt, val = a[i], a[i + 1]
    i += 2
    if opt == "-e":
        k, v = val.split("=", 1)
        env[k] = v
    elif opt == "-v":
        host, ctr = val.split(":", 1)
        vols.append((host, ctr))
    elif opt == "-w":
        wd = val
    elif opt != "--user":
        sys.exit("engine fixture: unexpected option " + opt)
cmd = a[i + 1:]
def m(s):
    for host, ctr in vols:
        s = s.replace(ctr + "/", host + "/")
        if s == ctr:
            s = host
    return s
env["HOME"] = {home!r}
os.chdir(m(wd))
os.execve({REAL['bash']!r} if cmd[0] == "bash" else m(cmd[0]), [m(x) for x in cmd], dict(os.environ, **env))
""", 0o755)
    g = dict(os.environ, GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_NOSYSTEM="1", TZ="UTC",
             GIT_AUTHOR_NAME="fixture", GIT_AUTHOR_EMAIL="fixture@example.invalid",
             GIT_COMMITTER_NAME="fixture", GIT_COMMITTER_EMAIL="fixture@example.invalid")
    for cmd in (["init", "-q"], ["commit", "-q", "--allow-empty", "-m", "fixture"]):
        subprocess.run([REAL["git"], "-C", src] + cmd, env=g, check=True)
    return bindir, src, calls


results, failures = [], []
for i, (name, over, want_exit, want_invoked, frags) in enumerate(CASES):
    c = dict(BASE, **over)
    d = os.path.join(work, f"case-{i:02d}")
    os.makedirs(d)
    bindir, src, calls = make_case(d, c)
    env = {k: v for k, v in os.environ.items() if k not in ("RUNNER_TEMP", "EXPECTED_PASSED")}
    env.update(PATH=bindir + os.pathsep + os.environ.get("PATH", ""), TMPDIR=os.path.join(d, "tmp"),
               EXPECTED_PASSED="1", GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_NOSYSTEM="1")
    logs = os.path.join(d, "logs")
    p = subprocess.run([REAL["bash"], runner, c["engine"], src, logs], env=env, capture_output=True,
                       text=True, timeout=120)
    write(os.path.join(d, "stdout.txt"), p.stdout)
    write(os.path.join(d, "stderr.txt"), p.stderr)
    invoked = os.path.exists(calls) and open(calls).read() or ""
    inventory = os.path.exists(os.path.join(logs, "unit-tests-inventory.txt"))
    problems = []
    if p.returncode != want_exit:
        problems.append(f"exit {p.returncode}, want {want_exit}")
    if bool(invoked) != want_invoked or inventory != want_invoked:
        problems.append(f"test executable invoked: {bool(invoked)}, inventory: {inventory}, want {want_invoked}")
    for fr in frags:
        if fr not in p.stderr:
            problems.append(f"stderr lacks {fr!r}")
    if want_exit == 0 and "PREREQUISITE" in p.stderr:
        problems.append("PREREQUISITE reported in a valid case")
    if want_exit == 2 and "no test was run" not in p.stderr:
        problems.append("no 'no test was run' diagnostic")
    if c["engine"] == "native" and not os.listdir(os.path.join(d, "tmp")) == []:
        problems.append("temporary HOME directory left behind")
    ok = not problems
    print(f"{'ok  ' if ok else 'FAIL'} {name}: exit {p.returncode}, test executable invoked {bool(invoked)}"
          + ("" if ok else " -- " + "; ".join(problems)))
    results.append({"case": name, "fixture": c, "exit": p.returncode, "want_exit": want_exit,
                    "invoked": bool(invoked), "want_invoked": want_invoked, "ok": ok, "problems": problems})
    if not ok:
        failures.append(name)
with open(os.path.join(work, "results.json"), "w") as f:
    json.dump({"runner": runner, "cases": results}, f, indent=2)
    f.write("\n")
print(f"{len(CASES) - len(failures)}/{len(CASES)} cases as expected")
sys.exit(1 if failures else 0)
