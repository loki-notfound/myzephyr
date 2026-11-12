#!/bin/bash
# Host side: build the cross builder image for one target and run
# build-in-container.sh in it.
#
#   run-builder.sh <docker|podman> <target> <source-dir> <log-dir>
#
# <target>: aarch64-linux-gnu, x86_64-w64-mingw32, x86_64-apple-darwin or aarch64-apple-darwin.
# <source-dir> is a clean, verified checkout (see ../verify-source.sh); it is mounted
# at /src. <log-dir> must not exist yet. The container runs as the invoking non-root
# user (Docker: --user uid:gid; rootless Podman: --userns=keep-id). Writes
# <log-dir>/image.txt, builder-packages.tsv and builder-apt-state.txt.
set -euo pipefail
umask 0022
export TZ=UTC

engine=${1:-} target=${2:-} srcdir=${3:-} logdir=${4:-}
case "$engine" in docker|podman) ;; *) echo "usage: $0 <docker|podman> <target> <source-dir> <log-dir>" >&2; exit 2 ;; esac
case "$target" in aarch64-linux-gnu|x86_64-w64-mingw32|x86_64-apple-darwin|aarch64-apple-darwin) ;;
  *) echo "target must be aarch64-linux-gnu, x86_64-w64-mingw32, x86_64-apple-darwin or aarch64-apple-darwin" >&2; exit 2 ;; esac
test -d "$srcdir/.git" || test -f "$srcdir/.git" || { echo "$srcdir is not a git checkout" >&2; exit 2; }
if [ -e "$logdir" ]; then echo "$logdir exists; refusing to overwrite" >&2; exit 2; fi
here=$(cd "$(dirname "$0")" && pwd)
srcdir=$(cd "$srcdir" && pwd)
mkdir -p "$logdir"
logdir=$(cd "$logdir" && pwd)
image=myzephyr-cross-builder:$target

if [ -n "$(git -C "$srcdir" status --porcelain --ignore-submodules=none)" ]; then
  echo "source checkout is not clean" >&2; exit 2
fi
sde=$(git -C "$srcdir" log -1 --format=%ct HEAD)

"$engine" build -t "$image" --build-arg TARGET="$target" -f "$here/Dockerfile" "$here" > "$logdir/image-build.log" 2>&1 \
  || { echo "image build failed" >&2; tail -n 30 "$logdir/image-build.log" >&2; exit 1; }
"$engine" image inspect "$image" --format '{{.Id}} {{.Architecture}} {{.Os}} {{.Created}}' > "$logdir/image.txt"
"$engine" run --rm --network=none "$image" cat /builder-packages.tsv > "$logdir/builder-packages.tsv"
"$engine" run --rm --network=none "$image" cat /builder-apt-state.txt > "$logdir/builder-apt-state.txt"

if [ "$engine" = podman ]; then
  user_args=(--userns=keep-id --user "$(id -u):$(id -g)")
else
  user_args=(--user "$(id -u):$(id -g)")
fi
set +e
"$engine" run --rm "${user_args[@]}" -e HOME=/tmp \
  -e SOURCE_DATE_EPOCH="$sde" -e JOBS="${JOBS:-4}" \
  -v "$srcdir:/src" -v "$logdir:/logs" \
  -v "$here/build-in-container.sh:/usr/local/bin/build-in-container.sh:ro" \
  "$image" /bin/bash /usr/local/bin/build-in-container.sh "$target"
rc=$?
set -e
echo "container exit $rc" >> "$logdir/steps.txt"
exit "$rc"
