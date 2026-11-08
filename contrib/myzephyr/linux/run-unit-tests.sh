#!/bin/bash
# Run the unit tests of a "tests" build (build-in-container.sh tests) inside the
# builder image, as the invoking non-root user, and judge the run with
# ../unit-test-summary.py.
#
#   run-unit-tests.sh <docker|podman> <source-dir> <log-dir>
#
# Records the enabled-test inventory (--gtest_list_tests), the console log and the
# gtest XML report. Pass only if every enabled test ran, none failed or was
# skipped, and exactly EXPECTED_PASSED tests passed (default 1006, the reference
# count for this source). A different count with zero failures exits 3
# ("review-required"): it fails the gate until the difference is reviewed. There
# is no allowlist.
set -euo pipefail
umask 0022
export TZ=UTC

engine=${1:-} srcdir=${2:-} logdir=${3:-}
case "$engine" in docker|podman) ;; *) echo "usage: $0 <docker|podman> <source-dir> <log-dir>" >&2; exit 2 ;; esac
expected=${EXPECTED_PASSED:-1006}
case "$expected" in ''|*[!0-9]*) echo "EXPECTED_PASSED must be a number" >&2; exit 2 ;; esac
here=$(cd "$(dirname "$0")" && pwd)
srcdir=$(cd "$srcdir" && pwd)
test -x "$srcdir/build/tests/tests/unit_tests/unit_tests" || { echo "unit_tests not built" >&2; exit 2; }
test -x "$srcdir/build/tests/tests/unit_tests/test_notifier" || { echo "test_notifier not built" >&2; exit 2; }
if [ -e "$logdir" ]; then echo "$logdir exists; refusing to overwrite" >&2; exit 2; fi
mkdir -p "$logdir"
logdir=$(cd "$logdir" && pwd)
image=myzephyr-linux-builder:local
if [ "$engine" = podman ]; then
  user_args=(--userns=keep-id --user "$(id -u):$(id -g)")
else
  user_args=(--user "$(id -u):$(id -g)")
fi
run() {
  "$engine" run --rm "${user_args[@]}" -e HOME=/tmp -e TZ=UTC \
    -v "$srcdir:/src" -v "$logdir:/logs" -w /src/build/tests "$image" "$@"
}

run ./tests/unit_tests/unit_tests --gtest_list_tests > "$logdir/unit-tests-inventory.txt" 2> "$logdir/unit-tests-inventory.err" \
  || { echo "listing the tests failed" >&2; cat "$logdir/unit-tests-inventory.err" >&2; exit 1; }
start=$(date -u +%FT%TZ)
set +e
run ./tests/unit_tests/unit_tests --data-dir /src/tests/data \
  --gtest_output=xml:/logs/unit-tests.xml > "$logdir/unit-tests.log" 2>&1
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
( cd "$logdir" && sha256sum unit-tests-inventory.txt unit-tests.log unit-tests-summary.json \
    $(test -f unit-tests.xml && echo unit-tests.xml) > SHA256SUMS )
exit "$verdict"
