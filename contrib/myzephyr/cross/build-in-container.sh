#!/bin/bash
# Cross-build zephyrd (CMake target "daemon", Release) with contrib/depends inside the
# cross builder image (contrib/myzephyr/cross/Dockerfile). Runs as a non-root user.
#
#   build-in-container.sh <aarch64-linux-gnu|x86_64-w64-mingw32|x86_64-apple-darwin|aarch64-apple-darwin>
#
# Expects the source at /src and a writable, empty log directory at /logs. One target
# per checkout: the depends prefix is per host triplet, and an existing build
# directory is never reused.
#
# Compilers: aarch64 uses aarch64-linux-gnu-gcc-9/g++-9; Windows uses the posix
# thread model (x86_64-w64-mingw32-gcc-posix/g++-posix); macOS (x86_64 and arm64) uses
# depends' native_clang with the darwin SDK (hosts/darwin.mk). They are passed to depends as
# make variables, so no depends file is changed.
#
# Environment: SOURCE_DATE_EPOCH (required), JOBS (1..4, default 4). Every step
# records its command, UTC start/end, duration and both exit codes.
set -euo pipefail
umask 0022
export TZ=UTC LC_ALL=C.UTF-8

target=${1:-}
case "$target" in
  aarch64-linux-gnu)
    tool_args=("aarch64_linux_CC=aarch64-linux-gnu-gcc-9" "aarch64_linux_CXX=aarch64-linux-gnu-g++-9")
    cc_id=(aarch64-linux-gnu-gcc-9 aarch64-linux-gnu-g++-9) exe=zephyrd ;;
  x86_64-w64-mingw32)
    tool_args=("x86_64_mingw32_CC=x86_64-w64-mingw32-gcc-posix" "x86_64_mingw32_CXX=x86_64-w64-mingw32-g++-posix")
    cc_id=(x86_64-w64-mingw32-gcc-posix x86_64-w64-mingw32-g++-posix) exe=zephyrd.exe ;;
  x86_64-apple-darwin|aarch64-apple-darwin)
    tool_args=()
    cc_id=() exe=zephyrd ;;
  *) echo "usage: $0 aarch64-linux-gnu|x86_64-w64-mingw32|x86_64-apple-darwin|aarch64-apple-darwin" >&2; exit 2 ;;
esac
: "${SOURCE_DATE_EPOCH:?SOURCE_DATE_EPOCH must be set to the source commit time}"
export SOURCE_DATE_EPOCH
JOBS=${JOBS:-4}
case "$JOBS" in [1-4]) ;; *) echo "JOBS must be 1..4" >&2; exit 2 ;; esac
src=/src
logs=/logs
build_dir=build/release-$target
prefix=contrib/depends/$target

cd "$src"
test -w "$logs" || { echo "log directory $logs is not writable" >&2; exit 2; }
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
  echo "target=$target"
  echo "SOURCE_DATE_EPOCH=$SOURCE_DATE_EPOCH ($(date -u -d "@$SOURCE_DATE_EPOCH" +%FT%TZ))"
  echo "JOBS=$JOBS umask=$(umask) uid=$(id -u)"
  for c in "${cc_id[@]}"; do echo "$c: $($c --version | sed -n 1p)"; done
  gcc --version | sed -n 1p
  cmake --version | sed -n 1p
  make --version | sed -n 1p
  git --version
  echo "HEAD $(git rev-parse HEAD)"
  echo "tags at HEAD: $(git tag -l --points-at HEAD | tr '\n' ' ')"
} > "$logs/toolchain.txt"

step depends make -C contrib/depends HOST="$target" -j"$JOBS" "${tool_args[@]}"
case "$target" in *-apple-darwin)
  echo "native clang: $("$prefix/native/bin/clang" --version | sed -n 1p)" >> "$logs/toolchain.txt" ;;
esac
step configure cmake -S . -B "$build_dir" \
  -DCMAKE_TOOLCHAIN_FILE="$src/$prefix/share/toolchain.cmake" -DCMAKE_SKIP_RPATH=ON
step build cmake --build "$build_dir" --target daemon --parallel "$JOBS"
test -f "$build_dir/bin/$exe"
sha256sum "$build_dir/bin/$exe" >> "$steps"
# what the linker put into the binary and the licence texts of its owners (link-inventory.sh);
# never fails the build: an incomplete inventory makes the release set's licences incomplete
bash contrib/myzephyr/link-inventory.sh "$src" "$build_dir" "$exe" "$target" "$logs" \
  > "$logs/link-inventory.log" 2>&1 || echo "link-inventory.sh exit $?" >> "$logs/link-inventory.log"
echo "BUILD $target ok" >> "$steps"
