#!/bin/bash
# Run the unit tests of a "tests" build (build-in-container.sh tests) and judge the run
# with ../unit-test-summary.py.
#
#   run-unit-tests.sh <native|docker|podman> <source-dir> <log-dir>
#
#   native          on this host, as the invoking non-root user, with HOME set to an empty
#                   temporary directory: the CI and acceptance mode. The binaries are the
#                   ones the builder image compiled; nothing is rebuilt. Some tests read the
#                   host itself (is_hdd.linux_os_root needs the root filesystem's block
#                   device to expose queue/rotational in sysfs, which a container root such
#                   as overlayfs does not).
#   docker|podman   inside the builder image, as the invoking non-root user, HOME=/tmp
#                   (the earlier CI mode; kept for diagnosis).
#
# Both modes run tests/unit_tests/unit_tests from <source-dir>/build/tests, with
# test_notifier next to it and the explicit data directory <source-dir>/tests/data.
# Before the run, unit-tests-environment.txt records the execution environment, the
# root filesystem (mount, device major:minor, both rotational attribute paths that
# tools::is_hdd reads) and the SHA256, interpreter and NEEDED libraries of both test
# binaries. A missing prerequisite stops before any test is listed or run, with an
# explanation (exit 2): binary or data directory, a failing id/stat/sha256sum/readelf/ldd
# (judged by exit status and complete output, not by empty output), interpreter, a shared
# library, a root user. In native mode a root filesystem without a readable numeric
# rotational attribute is such a prerequisite too: is_hdd.linux_os_root cannot pass there.
# The container modes are diagnostic: they report it as a PRECONDITION and still run and
# judge the suite in full, to reproduce that failure.
#
# Records the enabled-test inventory (--gtest_list_tests), the console log and the
# gtest XML report. Pass only if every enabled test ran, none failed or was
# skipped, and exactly EXPECTED_PASSED tests passed (default 1006, the reference
# count for this source). A different count with zero failures exits 3
# ("review-required"): it fails the gate until the difference is reviewed. There
# is no allowlist, filter or skip.
set -euo pipefail
umask 0022
export TZ=UTC

engine=${1:-} srcdir=${2:-} logdir=${3:-}
case "$engine" in native|docker|podman) ;; *) echo "usage: $0 <native|docker|podman> <source-dir> <log-dir>" >&2; exit 2 ;; esac
expected=${EXPECTED_PASSED:-1006}
case "$expected" in ''|*[!0-9]*) echo "EXPECTED_PASSED must be a number" >&2; exit 2 ;; esac
here=$(cd "$(dirname "$0")" && pwd)
srcdir=$(cd "$srcdir" && pwd)
test -x "$srcdir/build/tests/tests/unit_tests/unit_tests" || { echo "unit_tests not built" >&2; exit 2; }
test -x "$srcdir/build/tests/tests/unit_tests/test_notifier" || { echo "test_notifier not built" >&2; exit 2; }
test -d "$srcdir/tests/data" || { echo "test data directory $srcdir/tests/data missing" >&2; exit 2; }
if [ -e "$logdir" ]; then echo "$logdir exists; refusing to overwrite" >&2; exit 2; fi
mkdir -p "$logdir"
logdir=$(cd "$logdir" && pwd)

# pf_cmd <command...>: run a command whose output preflight relies on. Its standard output
# is left in pf_out and its exit status in pf_rc; standard error goes to the diagnostics.
# Works with and without errexit; no pipeline is involved, so no status is lost.
pf_cmd() {
  if pf_out=$("$@"); then pf_rc=0; else pf_rc=$?; fi
}

# preflight <build-dir> <native|diagnostic>: environment record on stdout, diagnostics on
# stderr; returns 2 on a missing prerequisite. Every command whose result is used (id, stat,
# sha256sum, readelf, ldd, reading the sysfs attributes) is judged by its exit status and
# its complete output; empty output is never taken to mean "nothing missing".
#   native      the acceptance mode: a root filesystem without a readable numeric
#               queue/rotational attribute is a missing prerequisite, because
#               is_hdd.linux_os_root cannot pass there; no test is started.
#   diagnostic  the container mode: the same finding is reported as a PRECONDITION and the
#               suite still runs in full, to reproduce that failure.
# It runs where the tests run, so it is passed by source (with pf_cmd).
preflight() {
  local build=$1 mode=$2 uid dev major minor line mp fs src b rel f v ok=1 attr=missing value= hash size
  local interp needed runpath missing out rc
  local re_interp='\[Requesting program interpreter: (.*)\]' re_needed='\(NEEDED\).*\[(.*)\]'
  local re_runpath='\((RPATH|RUNPATH)\).*\[(.*)\]'
  case "$mode" in native|diagnostic) ;; *) echo "PREREQUISITE: unknown preflight mode '$mode'" >&2; return 2 ;; esac
  echo "preflight_mode=$mode"
  pf_cmd id -u
  if [ "$pf_rc" != 0 ] || ! [[ $pf_out =~ ^[0-9]+$ ]]; then
    echo "PREREQUISITE: 'id -u' failed (exit $pf_rc, output '$pf_out')" >&2
    return 2
  fi
  uid=$pf_out
  pf_cmd id -g
  echo "uid=$uid gid=$pf_out"
  if [ "$uid" = 0 ]; then echo "PREREQUISITE: running as root; run the tests as a non-root user" >&2; ok=0; fi
  echo "kernel=$(uname -srm)"
  echo "os=$( (. /etc/os-release && echo "$PRETTY_NAME") 2> /dev/null || echo unknown)"
  echo "glibc=$(getconf GNU_LIBC_VERSION 2> /dev/null || echo unknown)"
  echo "cwd=$build"
  echo "home=$HOME"
  # the root filesystem as tools::is_hdd sees it: stat("/") -> /sys/dev/block/<major>:<minor>
  pf_cmd stat -c %d /
  if [ "$pf_rc" != 0 ] || ! [[ $pf_out =~ ^[0-9]+$ ]]; then
    echo "PREREQUISITE: 'stat -c %d /' failed (exit $pf_rc, output '$pf_out'); the root device is unknown" >&2
    return 2
  fi
  dev=$pf_out
  major=$(( ((dev >> 8) & 0xfff) | ((dev >> 32) & ~0xfff) ))
  minor=$(( (dev & 0xff) | ((dev >> 12) & ~0xff) ))
  echo "root_st_dev=$dev"
  echo "root_device=$major:$minor"
  line=$(awk '$5 == "/" { l = $0 } END { print l }' /proc/self/mountinfo)
  mp=${line#* - }
  read -r fs src _ <<< "$mp"
  echo "root_mount=$(awk '{ print $3 }' <<< "$line") fstype=$fs source=$src"
  # tools::is_hdd opens the first path, and only if that cannot be opened the second; it then
  # needs a number. Mirror that: the first readable path decides.
  for f in "/sys/dev/block/$major:$minor/queue/rotational" "/sys/dev/block/$major:$minor/../queue/rotational"; do
    pf_cmd cat "$f" 2> /dev/null
    if [ "$pf_rc" = 0 ]; then
      echo "rotational $f=$pf_out"
      if [ "$attr" = missing ]; then attr=$f; value=$pf_out; fi
    else
      echo "rotational $f=unreadable (exit $pf_rc)"
    fi
  done
  echo "root_rotational_attribute=$attr"
  if [ "$attr" = missing ] || ! [[ $value =~ ^[0-9]+$ ]]; then
    if [ "$attr" = missing ]; then
      v="has no readable queue/rotational attribute in /sys/dev/block"
    else
      v="has a queue/rotational attribute at $attr that is not a number ('$value')"
    fi
    if [ "$mode" = native ]; then
      echo "PREREQUISITE: the root filesystem ($fs, device $major:$minor) $v; tools::is_hdd(\"/\")" \
        "returns none and is_hdd.linux_os_root cannot pass here. Native acceptance needs a host whose" \
        "root filesystem is a block device exposing that attribute; no test was started." >&2
      ok=0
    else
      echo "PRECONDITION: the root filesystem ($fs, device $major:$minor) $v; is_hdd.linux_os_root" \
        "cannot pass in this environment. Diagnostic mode runs the full suite anyway; acceptance" \
        "needs run-unit-tests.sh native on a host whose root filesystem is a block device." >&2
    fi
  fi
  for b in "$build/tests/unit_tests/unit_tests" "$build/tests/unit_tests/test_notifier"; do
    rel=${b#"$build/"}
    pf_cmd sha256sum "$b"
    hash=${pf_out%% *}
    if [ "$pf_rc" != 0 ] || ! [[ $hash =~ ^[0-9a-f]{64}$ ]]; then
      echo "PREREQUISITE: 'sha256sum $rel' failed (exit $pf_rc)" >&2; ok=0; continue
    fi
    pf_cmd stat -c %s "$b"
    size=$pf_out
    if [ "$pf_rc" != 0 ] || ! [[ $size =~ ^[0-9]+$ ]]; then
      echo "PREREQUISITE: 'stat -c %s $rel' failed (exit $pf_rc)" >&2; ok=0; continue
    fi
    echo "binary $rel=$hash size=$size"
    pf_cmd readelf -lW "$b"
    if [ "$pf_rc" != 0 ]; then
      echo "PREREQUISITE: 'readelf -lW $rel' failed (exit $pf_rc; is binutils installed?)" >&2; ok=0; continue
    fi
    interp=
    while IFS= read -r line; do
      if [[ $line =~ $re_interp ]]; then interp=${BASH_REMATCH[1]}; fi
    done <<< "$pf_out"
    echo "interpreter $rel=$interp"
    if [ -z "$interp" ]; then
      echo "PREREQUISITE: readelf reports no program interpreter for ${b##*/}" >&2; ok=0
    elif [ ! -e "$interp" ]; then
      echo "PREREQUISITE: interpreter $interp of ${b##*/} not present" >&2; ok=0
    fi
    pf_cmd readelf -dW "$b"
    if [ "$pf_rc" != 0 ]; then
      echo "PREREQUISITE: 'readelf -dW $rel' failed (exit $pf_rc)" >&2; ok=0; continue
    fi
    needed= runpath=
    while IFS= read -r line; do
      if [[ $line =~ $re_needed ]]; then needed+="${needed:+ }${BASH_REMATCH[1]}"; fi
      if [[ $line =~ $re_runpath ]]; then runpath+="${runpath:+ }${BASH_REMATCH[1]}:${BASH_REMATCH[2]}"; fi
    done <<< "$pf_out"
    echo "needed $rel=$needed"
    echo "runpath $rel=$runpath"
    # the loader's verdict: its exit status and its complete output, both checked
    if out=$(ldd "$b" 2>&1); then rc=0; else rc=$?; fi
    echo "ldd $rel exit=$rc"
    missing=
    while IFS= read -r line; do
      case "$line" in *'not found'*) missing+="${missing:+$'\n'}  $line" ;; esac
    done <<< "$out"
    if [ "$rc" != 0 ]; then
      echo "PREREQUISITE: 'ldd $rel' failed (exit $rc); the loader cannot resolve ${b##*/} here:" >&2
      while IFS= read -r line; do printf '  %s\n' "$line"; done <<< "$out" >&2
      ok=0
    elif [ -n "$missing" ]; then
      echo "PREREQUISITE: shared libraries of ${b##*/} not found here:" >&2
      printf '%s\n' "$missing" >&2
      ok=0
    fi
  done
  [ "$ok" = 1 ] || return 2
}

if [ "$engine" = native ]; then
  unit_tests_home=$(mktemp -d "${RUNNER_TEMP:-${TMPDIR:-/tmp}}/unit-tests-home.XXXXXX")
  trap 'case "$unit_tests_home" in */unit-tests-home.*) rm -rf -- "$unit_tests_home" ;; esac' EXIT
  data=$srcdir/tests/data
  xml=$logdir/unit-tests.xml
  run() { ( cd "$srcdir/build/tests" && env HOME="$unit_tests_home" TZ=UTC "$@" ); }
  run_preflight() { ( cd "$srcdir/build/tests" && HOME=$unit_tests_home preflight "$srcdir/build/tests" native ); }
else
  image=myzephyr-linux-builder:local
  if [ "$engine" = podman ]; then
    user_args=(--userns=keep-id --user "$(id -u):$(id -g)")
  else
    user_args=(--user "$(id -u):$(id -g)")
  fi
  data=/src/tests/data
  xml=/logs/unit-tests.xml
  run() {
    "$engine" run --rm "${user_args[@]}" -e HOME=/tmp -e TZ=UTC \
      -v "$srcdir:/src" -v "$logdir:/logs" -w /src/build/tests "$image" "$@"
  }
  run_preflight() { run bash -c "$(declare -f pf_cmd preflight); preflight /src/build/tests diagnostic"; }
fi

{ echo "execution=$engine"; echo "recorded=$(date -u +%FT%TZ)"; echo "source_commit=$(git -C "$srcdir" rev-parse HEAD)"; } \
  > "$logdir/unit-tests-environment.txt"
set +e
run_preflight >> "$logdir/unit-tests-environment.txt" 2> "$logdir/unit-tests-preflight.err"
pre=$?
set -e
cat "$logdir/unit-tests-environment.txt"
cat "$logdir/unit-tests-preflight.err" >&2
if [ "$pre" != 0 ]; then
  echo "unit-tests: preflight failed (exit $pre); no test was run. See the PREREQUISITE lines above." >&2
  exit 2
fi

run ./tests/unit_tests/unit_tests --gtest_list_tests > "$logdir/unit-tests-inventory.txt" 2> "$logdir/unit-tests-inventory.err" \
  || { echo "listing the tests failed" >&2; cat "$logdir/unit-tests-inventory.err" >&2; exit 1; }
start=$(date -u +%FT%TZ)
set +e
run ./tests/unit_tests/unit_tests --data-dir "$data" \
  --gtest_output="xml:$xml" > "$logdir/unit-tests.log" 2>&1
rc=$?
set -e
end=$(date -u +%FT%TZ)
printf 'unit_tests_start=%s\nunit_tests_end=%s\nunit_tests_exit=%s\n' "$start" "$end" "$rc" > "$logdir/unit-tests-times.txt"

set +e
python3 -I "$here/../unit-test-summary.py" --list "$logdir/unit-tests-inventory.txt" \
  --xml "$logdir/unit-tests.xml" --log "$logdir/unit-tests.log" --exit-code "$rc" \
  --expected "$expected" --source-commit "$(git -C "$srcdir" rev-parse HEAD)" \
  --out "$logdir/unit-tests-summary.json"
verdict=$?
set -e
( cd "$logdir" && sha256sum unit-tests-environment.txt unit-tests-inventory.txt unit-tests.log unit-tests-summary.json \
    $(test -f unit-tests.xml && echo unit-tests.xml) > SHA256SUMS )
exit "$verdict"
