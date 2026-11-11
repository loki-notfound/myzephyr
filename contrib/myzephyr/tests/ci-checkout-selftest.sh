#!/bin/bash
# Self-test of ci-checkout.sh against a local origin repository made here (file:// URL, so
# shallow fetches behave as over the network; uploadpack.allowAnySHA1InWant on, as GitHub
# allows fetching a reachable commit by its id). Synthetic repositories only.
#
#   ci-checkout-selftest.sh <work-dir>      (<work-dir> must not exist)
#
# The origin has tags (on the base and on the head) and a pull-request merge ref. Each
# case makes a fresh checkout the way actions/checkout v7.0.1 does with a commit as ref,
# fetch-depth 1 and fetch-tags false (the commands of the job logs of CI run 43069206476:
# "git fetch --no-tags --prune --no-recurse-submodules --depth=1 origin <sha>", no
# destination ref, then a detached checkout), then runs ci-checkout.sh with the job's
# environment, the base tag v-base of the origin standing in for the backports base tag:
#   push to ci/daemon-release-baseline: passes, history complete, no tag fetched although
#     the origin has tags (also one at the built commit);
#   pull request into my/v2.3.0 at its head: passes, merge commit checked;
#   one change each, refused: merge commit with another tree, merge parents swapped, base not
#   an ancestor of the head, a tag in the checkout, HEAD not the built commit, a ref outside
#   the run-identity table.
# Submodules (the failure of CI run 43069206476): a base repository whose history first
# records a submodule commit that the submodule's remote no longer has, then the current one;
# the built commit on top. Checked out like actions/checkout with submodules: recursive
# (submodule update --init --force --depth=1 --recursive). The round-13 sequence (unshallow,
# then a base-tag fetch with git's default submodule recursion) fails there with "Errors
# during submodule fetch"; the same sequence after the round-13 test emulation (a ref kept on
# the built commit) does not, which is why the old self-test missed it; ci-checkout.sh
# passes, leaves the submodule on its recorded commit at depth 1, records it, and a later
# plain fetch does not recurse either.
set -euo pipefail
export LC_ALL=C TZ=UTC GIT_CONFIG_NOSYSTEM=1 GIT_CONFIG_GLOBAL=/dev/null
unset GIT_DIR GIT_WORK_TREE
here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
cc=$here/../ci-checkout.sh
PY=${PY:-python3}
[ $# = 1 ] || { echo "usage: ci-checkout-selftest.sh <work-dir>" >&2; exit 2; }
[ ! -e "$1" ] || { echo "$1 exists" >&2; exit 2; }
mkdir -p "$1"; work=$(cd "$1" && pwd)
passed=0 failed=0
record() { if [ "$1" = 0 ]; then passed=$((passed + 1)); echo "ok   $2"; else failed=$((failed + 1)); echo "FAIL $2${3:+ -- $3}"; fi; }

G() { git -C "$src" -c core.hooksPath=/dev/null -c commit.gpgsign=false -c tag.gpgsign=false \
        -c user.name=selftest -c user.email=selftest@example.invalid "$@"; }
src=$work/src; origin=$work/origin.git
git init -q "$src"; G checkout -q -b main
c() { echo "$1" > "$src/f.txt"; G add f.txt; G commit -q -m "$1"; G rev-parse HEAD; }
base=$(c base); G tag v-base "$base"
c1=$(c one); built=$(c two)
G tag v-at-head "$built"
G branch ci/daemon-release-baseline "$built"
G branch my/v2.3.0 "$base"
side=$(G commit-tree -p "$base" -m side "$(G rev-parse "$c1^{tree}")")
tree=$(G rev-parse "$built^{tree}")
merge=$(G commit-tree -p "$base" -p "$built" -m "Merge" "$tree")
merge_tree=$(G commit-tree -p "$base" -p "$built" -m "Merge" "$(G rev-parse "$c1^{tree}")")
merge_swapped=$(G commit-tree -p "$built" -p "$base" -m "Merge" "$tree")
merge_side=$(G commit-tree -p "$side" -p "$built" -m "Merge" "$tree")
i=0; for m in "$merge" "$merge_tree" "$merge_swapped" "$merge_side"; do i=$((i + 1)); G update-ref "refs/pull/$i/merge" "$m"; done
git clone -q --bare "$src" "$origin"
git -C "$origin" config uploadpack.allowAnySHA1InWant true
for i in 1 2 3 4; do git -C "$origin" update-ref "refs/pull/$i/merge" "$(G rev-parse "refs/pull/$i/merge")"; done

# checkout <dir> <sha> [origin]: what actions/checkout does with a commit as ref, fetch-depth 1
# and fetch-tags false: the fetch names the commit without a destination, so no ref is made
checkout() {
  git init -q "$1"
  git -C "$1" remote add origin "file://${3:-$origin}"
  git -C "$1" -c protocol.file.allow=always fetch -q --no-tags --prune --no-recurse-submodules --depth=1 origin "$2"
  git -C "$1" checkout -q --force --detach "$2"
}
REPO=example/myzephyr WF=.github/workflows/daemon-release-baseline.yml
run_cc() {  # run_cc <name> <want-exit> <want-text> <event> <ref> <github-sha> <build-sha> <payload-json> [setup-command]
  local name=$1 want=$2 text=$3 ev=$4 ref=$5 gsha=$6 bsha=$7 payload=$8 setup=${9:-} d rc=0
  d=$work/case-$((passed + failed)); mkdir "$d"
  checkout "$d/co" "$bsha"
  [ -z "$setup" ] || eval "$setup"
  printf '%s' "$payload" > "$d/event.json"; : > "$d/github-env"
  env GITHUB_EVENT_NAME="$ev" GITHUB_REF="$ref" GITHUB_SHA="$gsha" GITHUB_WORKFLOW_SHA="$gsha" \
    GITHUB_WORKFLOW_REF="$REPO/$WF@$ref" GITHUB_REPOSITORY="$REPO" GITHUB_EVENT_PATH="$d/event.json" \
    GITHUB_ENV="$d/github-env" MYZ_BUILD_SHA="$bsha" PY="$PY" GIT_CONFIG_PARAMETERS="'protocol.file.allow=always'" \
    BASE_REPOSITORY_URL="file://$origin" BASE_TAG=v-base \
    bash "$cc" "$d/co" "$d/record.txt" > "$d/out.txt" 2>&1 || rc=$?
  if [ "$rc" = "$want" ] && grep -qF -- "$text" "$d/out.txt"; then record 0 "$name"
  else record 1 "$name" "exit $rc (want $want), text '$text'; see $d/out.txt"; fi
  last=$d
}
pr_payload() {  # pr_payload <number> <base-sha>
  printf '{"pull_request": {"number": %s, "base": {"ref": "my/v2.3.0", "sha": "%s"}, "head": {"ref": "pr/x", "sha": "%s", "repo": {"full_name": "%s"}}}}' \
    "$1" "$2" "$built" "$REPO"
}

run_cc "push to ci/daemon-release-baseline passes" 0 "fetch_mode=depth-1-no-tags+unshallow-no-tags" \
  push refs/heads/ci/daemon-release-baseline "$built" "$built" '{}'
co=$last/co
[ "$(git -C "$co" rev-parse --is-shallow-repository)" = false ] && [ "$(git -C "$co" rev-list --count HEAD)" = 3 ] \
  && record 0 "history complete after the unshallow fetch" || record 1 "history complete after the unshallow fetch"
[ -z "$(git -C "$co" for-each-ref refs/tags)" ] && git -C "$origin" rev-parse -q --verify refs/tags/v-at-head > /dev/null \
  && record 0 "no tag fetched although the origin has one at the built commit" || record 1 "no tag fetched although the origin has one at the built commit"
[ "$(git -C "$co" config remote.origin.tagOpt)" = --no-tags ] && record 0 "remote.origin.tagOpt is --no-tags" || record 1 "remote.origin.tagOpt is --no-tags"
[ "$(git -C "$co" rev-parse refs/myzephyr-base/v-base)" = "$base" ] && grep -qx "base_ref=refs/myzephyr-base/v-base $base" "$last/record.txt" \
  && record 0 "base tag fetched into refs/myzephyr-base and recorded" || record 1 "base tag fetched into refs/myzephyr-base and recorded"
[ "$(git -C "$co" config fetch.recurseSubmodules)" = false ] && [ "$(git -C "$co" config submodule.recurse)" = false ] \
  && record 0 "fetch.recurseSubmodules and submodule.recurse are false" || record 1 "fetch.recurseSubmodules and submodule.recurse are false"
grep -qx "MYZ_PULL_REQUEST=none" "$last/github-env" && record 0 "push run writes MYZ_PULL_REQUEST=none" || record 1 "push run writes MYZ_PULL_REQUEST=none"
[ -z "$(git -C "$co" status --porcelain --ignored)" ] && record 0 "checkout clean afterwards" || record 1 "checkout clean afterwards"

run_cc "pull request into my/v2.3.0 at its head passes" 0 "pr_merge_tree_equals_head=yes" \
  pull_request refs/pull/1/merge "$merge" "$built" "$(pr_payload 1 "$base")"
[ -z "$(git -C "$last/co" for-each-ref refs/myzephyr)" ] && record 0 "helper refs removed" || record 1 "helper refs removed"
run_cc "merge commit with another tree refused" 1 "has another tree than the head" \
  pull_request refs/pull/2/merge "$merge_tree" "$built" "$(pr_payload 2 "$base")"
run_cc "merge commit with swapped parents refused" 1 "has parents" \
  pull_request refs/pull/3/merge "$merge_swapped" "$built" "$(pr_payload 3 "$base")"
run_cc "base not an ancestor of the head refused" 1 "not a fast-forward" \
  pull_request refs/pull/4/merge "$merge_side" "$built" "$(pr_payload 4 "$side")"
run_cc "a tag in the checkout refused" 1 "tags present in the checkout" \
  push refs/heads/ci/daemon-release-baseline "$built" "$built" '{}' 'git -C "$d/co" -c tag.gpgsign=false tag v-local'
run_cc "HEAD other than the built commit refused" 1 "expected the built commit" \
  push refs/heads/ci/daemon-release-baseline "$built" "$built" '{}' 'git -C "$d/co" -c protocol.file.allow=always fetch -q --no-tags --depth=1 origin "$c1" && git -C "$d/co" checkout -q --detach "$c1"'
run_cc "ref outside the run-identity table refused" 1 "run identity not in the table" \
  push refs/heads/main "$built" "$built" '{}'

# ------------------------------------------------------------ submodules (CI run 43069206476)
S() { git -C "$1" -c core.hooksPath=/dev/null -c commit.gpgsign=false -c tag.gpgsign=false -c protocol.file.allow=always \
        -c user.name=selftest -c user.email=selftest@example.invalid "${@:2}"; }
subsrc=$work/sub-src; subremote=$work/sub.git; bsrc=$work/base-src; borigin=$work/base.git
git init -q "$subsrc"; S "$subsrc" checkout -q -b main
echo old > "$subsrc/s.txt"; S "$subsrc" add s.txt; S "$subsrc" commit -q -m "sub old"
S "$subsrc" checkout -q -b gone; echo gone > "$subsrc/s.txt"; S "$subsrc" commit -q -am "sub gone"; s_gone=$(S "$subsrc" rev-parse HEAD)
S "$subsrc" checkout -q main; echo new > "$subsrc/s.txt"; S "$subsrc" commit -q -am "sub new"; s_new=$(S "$subsrc" rev-parse HEAD)
git clone -q --bare "$subsrc" "$subremote"
git -C "$subremote" config uploadpack.allowAnySHA1InWant true
git -C "$subremote" branch -q -D gone
git -C "$subremote" reflog expire --expire=now --all; git -C "$subremote" gc -q --prune=now
git -C "$subremote" cat-file -e "$s_gone" 2> /dev/null && record 1 "fixture: old submodule commit absent from its remote" \
  || record 0 "fixture: old submodule commit absent from its remote"
git init -q "$bsrc"; S "$bsrc" checkout -q -b main
printf '[submodule "ext/sub"]\n\tpath = ext/sub\n\turl = file://%s\n' "$subremote" > "$bsrc/.gitmodules"
echo a > "$bsrc/f.txt"; S "$bsrc" add f.txt; S "$bsrc" commit -q -m "root"   # the gitlink must change in a non-root commit
S "$bsrc" add .gitmodules
S "$bsrc" update-index --add --cacheinfo "160000,$s_gone,ext/sub"; S "$bsrc" commit -q -m "record the gone submodule commit"
S "$bsrc" update-index --cacheinfo "160000,$s_new,ext/sub"; S "$bsrc" commit -q -m "record the current submodule commit"
sbase=$(S "$bsrc" rev-parse HEAD); S "$bsrc" tag -a -m "base" b-base
echo b > "$bsrc/f.txt"; S "$bsrc" add f.txt; S "$bsrc" commit -q -m "own commit"; sbuilt=$(S "$bsrc" rev-parse HEAD)   # not -a: ext/sub has no work tree here
S "$bsrc" branch ci/daemon-release-baseline "$sbuilt"
git clone -q --bare "$bsrc" "$borigin"; git -C "$borigin" config uploadpack.allowAnySHA1InWant true
sub_checkout() {  # sub_checkout <dir>: actions/checkout with submodules: recursive and fetch-depth 1
  checkout "$1" "$sbuilt" "$borigin"
  S "$1" submodule sync -q --recursive
  S "$1" submodule update -q --init --force --depth=1 --recursive
}
old_sequence() {  # the round-13 sequence: ci-checkout.sh's unshallow, then the workflow's base-tag fetch
  S "$1" config remote.origin.tagOpt --no-tags
  S "$1" fetch --quiet --no-tags --no-recurse-submodules --unshallow origin "+$sbuilt:refs/myzephyr/build-head"
  S "$1" update-ref -d refs/myzephyr/build-head
  S "$1" fetch --no-tags "file://$borigin" "+refs/tags/b-base:refs/myzephyr-base/b-base"
}
d=$work/sub-old; mkdir "$d"; sub_checkout "$d/co"
[ -z "$(git -C "$d/co" for-each-ref)" ] && [ "$(git -C "$d/co/ext/sub" rev-parse --is-shallow-repository)" = true ] \
  && record 0 "submodule checkout: no ref in the superproject, shallow submodule (as on the runner)" \
  || record 1 "submodule checkout: no ref in the superproject, shallow submodule (as on the runner)"
rc=0; old_sequence "$d/co" > "$d/out.txt" 2>&1 || rc=$?
[ "$rc" != 0 ] && grep -q "Errors during submodule fetch" "$d/out.txt" && grep -q "Fetching submodule ext/sub" "$d/out.txt" \
  && record 0 "round-13 sequence fails: base-tag fetch recurses into the submodule for the gone commit" \
  || record 1 "round-13 sequence fails: base-tag fetch recurses into the submodule for the gone commit" "exit $rc; see $d/out.txt"
d=$work/sub-old-ref; mkdir "$d"; sub_checkout "$d/co"; S "$d/co" update-ref refs/remotes/origin/HEAD "$sbuilt"
rc=0; old_sequence "$d/co" > "$d/out.txt" 2>&1 || rc=$?
[ "$rc" = 0 ] && ! grep -q "Fetching submodule" "$d/out.txt" \
  && record 0 "same sequence with a ref on the built commit (the round-13 emulation) does not fail: the old test's gap" \
  || record 1 "same sequence with a ref on the built commit (the round-13 emulation) does not fail: the old test's gap" "exit $rc"
d=$work/sub-new; mkdir "$d"; sub_checkout "$d/co"
printf '{}' > "$d/event.json"; : > "$d/github-env"; rc=0
env GITHUB_EVENT_NAME=push GITHUB_REF=refs/heads/ci/daemon-release-baseline GITHUB_SHA="$sbuilt" GITHUB_WORKFLOW_SHA="$sbuilt" \
  GITHUB_WORKFLOW_REF="$REPO/$WF@refs/heads/ci/daemon-release-baseline" GITHUB_REPOSITORY="$REPO" GITHUB_EVENT_PATH="$d/event.json" \
  GITHUB_ENV="$d/github-env" MYZ_BUILD_SHA="$sbuilt" PY="$PY" GIT_CONFIG_PARAMETERS="'protocol.file.allow=always'" \
  BASE_REPOSITORY_URL="file://$borigin" BASE_TAG=b-base bash "$cc" "$d/co" "$d/record.txt" > "$d/out.txt" 2>&1 || rc=$?
[ "$rc" = 0 ] && ! grep -q "Fetching submodule" "$d/out.txt" && grep -qx "base_ref=refs/myzephyr-base/b-base $(S "$bsrc" rev-parse b-base)" "$d/record.txt" \
  && record 0 "ci-checkout.sh passes on the same checkout, base tag fetched, no submodule fetch" \
  || record 1 "ci-checkout.sh passes on the same checkout, base tag fetched, no submodule fetch" "exit $rc; see $d/out.txt"
[ "$(git -C "$d/co/ext/sub" rev-parse HEAD)" = "$s_new" ] && [ "$(git -C "$d/co" submodule status --recursive | cut -c1)" = " " ] \
  && [ "$(git -C "$d/co/ext/sub" rev-parse --is-shallow-repository)" = true ] && grep -q "^submodule_status_unchanged=yes (1 entries)" "$d/record.txt" \
  && record 0 "submodule stays on its recorded commit at depth 1, recorded unchanged" \
  || record 1 "submodule stays on its recorded commit at depth 1, recorded unchanged"
rc=0; S "$d/co" fetch --no-tags "file://$borigin" "+refs/tags/b-base:refs/myzephyr-base/again" > "$d/later.txt" 2>&1 || rc=$?
[ "$rc" = 0 ] && ! grep -q "Fetching submodule" "$d/later.txt" \
  && record 0 "a later fetch without --no-recurse-submodules does not recurse (fetch.recurseSubmodules=false)" \
  || record 1 "a later fetch without --no-recurse-submodules does not recurse (fetch.recurseSubmodules=false)" "exit $rc"

echo "$passed/$((passed + failed)) cases as expected"
[ "$failed" = 0 ]
