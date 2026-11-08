#!/bin/bash
# Build zephyrd for Linux x86_64 with contrib/depends, inside the builder image
# (contrib/myzephyr/linux/Dockerfile). Runs as a non-root user.
#
#   build-in-container.sh release   depends (Release), then only CMake target "daemon"
#   build-in-container.sh tests     depends with TESTS=1 (Debug, gtest), then
#                                   targets "unit_tests" and "test_notifier"
#
# Expects the source at /src and a writable, empty log directory at /logs.
# Release and tests outputs must come from separate checkouts: both modes use the
# same depends prefix path, and the script refuses to mix them.
#
# Environment: SOURCE_DATE_EPOCH (required), JOBS (1..4, default 4),
# MYZ_HOST_CC / MYZ_HOST_CXX (default "gcc-9 -m64" / "g++-9 -m64").
# Every step records its command, UTC start/end, duration and the exit codes of
# both the command and the log writer; any nonzero code stops the build.
set -euo pipefail
umask 0022
export TZ=UTC LC_ALL=C.UTF-8

mode=${1:-}
case "$mode" in release|tests) ;; *) echo "usage: $0 release|tests" >&2; exit 2 ;; esac
: "${SOURCE_DATE_EPOCH:?SOURCE_DATE_EPOCH must be set to the source commit time}"
export SOURCE_DATE_EPOCH
JOBS=${JOBS:-4}
case "$JOBS" in [1-4]) ;; *) echo "JOBS must be 1..4" >&2; exit 2 ;; esac
host_triplet=x86_64-unknown-linux-gnu
host_cc=${MYZ_HOST_CC:-gcc-9 -m64}
host_cxx=${MYZ_HOST_CXX:-g++-9 -m64}
src=/src
logs=/logs
build_dir=build/$mode
prefix=contrib/depends/$host_triplet
marker=$prefix/.myzephyr-mode

cd "$src"
test -w "$logs" || { echo "log directory $logs is not writable" >&2; exit 2; }
if [ -e "$prefix" ] && [ "$(cat "$marker" 2>/dev/null)" != "$mode" ]; then
  echo "depends prefix $prefix exists but was not built for mode '$mode'; use a fresh checkout" >&2; exit 2
fi
if [ -e "$build_dir" ]; then echo "$build_dir exists; refusing to reuse build output" >&2; exit 2; fi

steps=$logs/steps.txt
step() {
  local name=$1; shift
  local start end
  local -a st
  start=$(date -u +%s)
  printf 'STEP %s start %s\n+ %s\n' "$name" "$(date -u -d "@$start" +%FT%TZ)" "$*" >> "$steps"
  set +e
  "$@" 2>&1 | tee "$logs/$name.log" > /dev/null
  st=("${PIPESTATUS[@]}")
  set -e
  end=$(date -u +%s)
  printf 'STEP %s end %s exit %s tee %s duration %ss\n' "$name" \
    "$(date -u -d "@$end" +%FT%TZ)" "${st[0]}" "${st[1]}" "$((end - start))" >> "$steps"
  if [ "${st[0]}" -ne 0 ] || [ "${st[1]}" -ne 0 ]; then
    echo "step $name failed: command ${st[0]}, log ${st[1]}" >&2
    tail -n 40 "$logs/$name.log" >&2 || true
    exit 1
  fi
}

{
  echo "mode=$mode"
  echo "SOURCE_DATE_EPOCH=$SOURCE_DATE_EPOCH ($(date -u -d "@$SOURCE_DATE_EPOCH" +%FT%TZ))"
  echo "JOBS=$JOBS umask=$(umask) uid=$(id -u)"
  echo "host_cc=$host_cc"; echo "host_cxx=$host_cxx"
  $host_cc --version | sed -n 1p
  $host_cxx --version | sed -n 1p
  gcc --version | sed -n 1p
  cmake --version | sed -n 1p
  make --version | sed -n 1p
  ld --version | sed -n 1p
  git --version
  echo "HEAD $(git rev-parse HEAD)"
  echo "tags at HEAD: $(git tag -l --points-at HEAD | tr '\n' ' ')"
} > "$logs/toolchain.txt"

depends_args=(-C contrib/depends HOST="$host_triplet" -j"$JOBS"
              "x86_64_linux_CC=$host_cc" "x86_64_linux_CXX=$host_cxx")
cmake_args=(-S . -B "$build_dir"
            -DCMAKE_TOOLCHAIN_FILE="$src/$prefix/share/toolchain.cmake"
            -DCMAKE_SKIP_RPATH=ON)

if [ "$mode" = release ]; then
  step depends make "${depends_args[@]}"
  echo "$mode" > "$marker"
  step configure cmake "${cmake_args[@]}"
  step build cmake --build "$build_dir" --target daemon --parallel "$JOBS"
  test -x "$build_dir/bin/zephyrd"
else
  step depends make "${depends_args[@]}" TESTS=1
  echo "$mode" > "$marker"
  step configure cmake "${cmake_args[@]}"
  step build cmake --build "$build_dir" --target unit_tests test_notifier --parallel "$JOBS"
  test -x "$build_dir/tests/unit_tests/unit_tests"
fi
echo "BUILD $mode ok" >> "$steps"
