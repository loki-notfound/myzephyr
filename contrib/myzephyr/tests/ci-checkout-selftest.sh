#!/bin/bash
# Self-test of ci-checkout.sh against a local origin repository made here (file:// URL, so
# shallow fetches behave as over the network; uploadpack.allowAnySHA1InWant on, as GitHub
# allows fetching a reachable commit by its id). Synthetic repositories only.
#
#   ci-checkout-selftest.sh <work-dir>      (<work-dir> must not exist)
#
# The origin has tags (on the base and on the head) and a pull-request merge ref. Each
# case makes a fresh checkout the way actions/checkout does with fetch-depth 1 and
# fetch-tags false (git fetch --no-tags --depth=1 origin +<sha>:...), then runs
# ci-checkout.sh with the job's environment:
#   push to ci/daemon-release-baseline: passes, history complete, no tag fetched although
#     the origin has tags (also one at the built commit);
#   pull request into my/v2.3.0 at its head: passes, merge commit checked;
#   one change each, refused: merge commit with another tree, merge parents swapped, base not
#   an ancestor of the head, a tag in the checkout, HEAD not the built commit, a ref outside
#   the run-identity table.
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

# checkout <dir> <sha>: what actions/checkout does with fetch-depth 1 and fetch-tags false
checkout() {
  git init -q "$1"
  git -C "$1" remote add origin "file://$origin"
  git -C "$1" -c protocol.file.allow=always fetch -q --no-tags --depth=1 origin "+$2:refs/remotes/origin/HEAD"
  git -C "$1" checkout -q --detach "$2"
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

echo "$passed/$((passed + failed)) cases as expected"
[ "$failed" = 0 ]
