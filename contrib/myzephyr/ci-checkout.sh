#!/bin/bash
# Complete and check a CI checkout of the built commit, without any tag.
#
#   ci-checkout.sh <checkout-dir> <record-file>
#
# Runs right after actions/checkout with ref ${{ env.MYZ_BUILD_SHA }}, fetch-depth 1 and
# fetch-tags false (that fetch passes --no-tags; with fetch-depth 0 actions/checkout would
# fetch every tag). Environment: the GITHUB_* variables of the job, GITHUB_ENV, MYZ_BUILD_SHA
# (the built commit: the pushed commit, or the head commit of a pull request), PY (python
# command, default python3).
#
#  1. run-identity.py check: the event, ref and commits must be a row of the run-identity
#     table; writes MYZ_PULL_REQUEST to GITHUB_ENV.
#  2. HEAD is MYZ_BUILD_SHA. remote.origin.tagOpt is set to --no-tags, then the history of
#     the built commit is completed with "git fetch --no-tags --unshallow".
#  3. Pull request: the test merge commit GITHUB_SHA (its workflow file is the one GitHub
#     runs) is fetched without tags; its parents are exactly base.sha and head.sha and its tree
#     is the head's tree, so the workflow and scripts that run are the head's. base.sha is an
#     ancestor of the head (the pull request can land by fast-forward).
#  4. No tag exists in the checkout (refs/tags is empty), so none points at HEAD and
#     cmake/GitVersion.cmake prints <version>-<9 hex>, never "release".
# Writes key=value lines to <record-file>. Any failure exits 1.
set -euo pipefail
export LC_ALL=C
co=${1:?checkout directory}; record=${2:?record file}
PY=${PY:-python3}
here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
fail() { echo "ci-checkout: $*" >&2; exit 1; }
g() { git -C "$co" "$@"; }

: "${MYZ_BUILD_SHA:?MYZ_BUILD_SHA must be set}" "${GITHUB_SHA:?}" "${GITHUB_EVENT_NAME:?}" "${GITHUB_ENV:?}"
"$PY" -I "$here/run-identity.py" check --github-env "$GITHUB_ENV" || fail "run identity not in the table"

[ "$(g rev-parse HEAD)" = "$MYZ_BUILD_SHA" ] || fail "HEAD is $(g rev-parse HEAD), expected the built commit $MYZ_BUILD_SHA"
g config remote.origin.tagOpt --no-tags
if [ "$(g rev-parse --is-shallow-repository)" = true ]; then
  g fetch --quiet --no-tags --no-recurse-submodules --unshallow origin "+$MYZ_BUILD_SHA:refs/myzephyr/build-head"
  g update-ref -d refs/myzephyr/build-head
fi
[ "$(g rev-parse --is-shallow-repository)" = false ] || fail "history still shallow after --unshallow"

pr_lines=()
if [ "$GITHUB_EVENT_NAME" = pull_request ]; then
  base_sha=$("$PY" -I -c 'import json,sys; print(json.load(open(sys.argv[1]))["pull_request"]["base"]["sha"])' \
    "$GITHUB_EVENT_PATH" | tr -d '\r')
  [[ "$base_sha" =~ ^[0-9a-f]{40}$ ]] || fail "pull request base sha '$base_sha' not readable"
  g fetch --quiet --no-tags --no-recurse-submodules origin "+$GITHUB_SHA:refs/myzephyr/pr-merge"
  [ "$(g rev-parse refs/myzephyr/pr-merge)" = "$GITHUB_SHA" ] || fail "fetched merge commit differs from GITHUB_SHA"
  parents=$(g cat-file commit "$GITHUB_SHA" | sed -n '/^$/q;s/^parent //p' | tr '\n' ' ')
  [ "$parents" = "$base_sha $MYZ_BUILD_SHA " ] || fail "merge commit $GITHUB_SHA has parents '$parents', expected '$base_sha $MYZ_BUILD_SHA'"
  [ "$(g rev-parse "$GITHUB_SHA^{tree}")" = "$(g rev-parse "$MYZ_BUILD_SHA^{tree}")" ] \
    || fail "merge commit $GITHUB_SHA has another tree than the head $MYZ_BUILD_SHA: the workflow that runs would not be the head's"
  g merge-base --is-ancestor "$base_sha" "$MYZ_BUILD_SHA" || fail "base $base_sha is not an ancestor of the head: not a fast-forward"
  g update-ref -d refs/myzephyr/pr-merge
  pr_lines=("pr_merge_commit=$GITHUB_SHA" "pr_merge_parents=$base_sha $MYZ_BUILD_SHA" "pr_merge_tree_equals_head=yes" "pr_base_is_ancestor=yes")
fi

tags=$(g for-each-ref --format='%(refname)' refs/tags)
[ -z "$tags" ] || fail "tags present in the checkout: $(tr '\n' ' ' <<< "$tags")"
[ -z "$(g tag -l --points-at HEAD)" ] || fail "a tag points at HEAD"
{
  echo "fetch_mode=depth-1-no-tags+unshallow-no-tags"
  echo "tags_in_checkout=0"
  echo "tags_at_head=none"
  echo "event_name=$GITHUB_EVENT_NAME"
  echo "built_commit=$MYZ_BUILD_SHA"
  printf '%s\n' ${pr_lines[@]+"${pr_lines[@]}"}
} > "$record"
cat "$record"
