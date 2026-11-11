#!/bin/bash
# Complete and check a CI checkout of the built commit, without any tag.
#
#   ci-checkout.sh <checkout-dir> <record-file>
#
# Runs right after actions/checkout with ref ${{ env.MYZ_BUILD_SHA }}, fetch-depth 1 and
# fetch-tags false (that fetch passes --no-tags; with fetch-depth 0 actions/checkout would
# fetch every tag). Environment: the GITHUB_* variables of the job, GITHUB_ENV, MYZ_BUILD_SHA
# (the built commit: the pushed commit, or the head commit of a pull request), BASE_REPOSITORY_URL
# and BASE_TAG (the pinned base policy of the workflow), PY (python command, default python3).
#
# No fetch here or after it recurses into submodules: every fetch passes
# --no-recurse-submodules, and fetch.recurseSubmodules and submodule.recurse are set to false
# in the checkout first. actions/checkout fetches the built commit without creating any ref,
# so no local ref covers the history; with git's default (on-demand) a later fetch would
# treat every commit of the history as new and fetch every submodule commit ever recorded
# in it, some of which their remotes no longer serve (CI run 43069206476: miniupnp
# 4c700e09…, recorded by 643c86a62, "upload-pack: not our ref"). The submodules stay at the
# commits actions/checkout put them on (depth 1); verify-source.sh checks those commits.
#
#  1. run-identity.py check: the event, ref and commits must be a row of the run-identity
#     table; writes MYZ_PULL_REQUEST to GITHUB_ENV.
#  2. HEAD is MYZ_BUILD_SHA. remote.origin.tagOpt is set to --no-tags, then the history of
#     the built commit is completed with "git fetch --no-tags --unshallow".
#  3. Pull request: the test merge commit GITHUB_SHA (its workflow file is the one GitHub
#     runs) is fetched without tags; its parents are exactly base.sha and head.sha and its tree
#     is the head's tree, so the workflow and scripts that run are the head's. base.sha is an
#     ancestor of the head (the pull request can land by fast-forward).
#  4. The base tag BASE_TAG is fetched from BASE_REPOSITORY_URL into refs/myzephyr-base/BASE_TAG
#     (not into refs/tags), for verify-source.sh. Every job runs this same sequence.
#  5. No tag exists in the checkout (refs/tags is empty), so none points at HEAD and
#     cmake/GitVersion.cmake prints <version>-<9 hex>, never "release".
#  6. The recursive submodule status is the same before the first fetch and after the last.
# Writes key=value lines to <record-file>. Any failure exits 1.
set -euo pipefail
export LC_ALL=C
co=${1:?checkout directory}; record=${2:?record file}
PY=${PY:-python3}
here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
fail() { echo "ci-checkout: $*" >&2; exit 1; }
g() { git -C "$co" "$@"; }

: "${MYZ_BUILD_SHA:?MYZ_BUILD_SHA must be set}" "${GITHUB_SHA:?}" "${GITHUB_EVENT_NAME:?}" "${GITHUB_ENV:?}"
: "${BASE_REPOSITORY_URL:?BASE_REPOSITORY_URL must be set}" "${BASE_TAG:?BASE_TAG must be set}"
"$PY" -I "$here/run-identity.py" check --github-env "$GITHUB_ENV" || fail "run identity not in the table"

[ "$(g rev-parse HEAD)" = "$MYZ_BUILD_SHA" ] || fail "HEAD is $(g rev-parse HEAD), expected the built commit $MYZ_BUILD_SHA"
g config remote.origin.tagOpt --no-tags
g config fetch.recurseSubmodules false
g config submodule.recurse false
sub_before=$(g submodule status --recursive)
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
  parents=$(g rev-list --parents -n 1 "$GITHUB_SHA" | cut -d' ' -f2-)
  [ "$parents" = "$base_sha $MYZ_BUILD_SHA" ] || fail "merge commit $GITHUB_SHA has parents '$parents', expected '$base_sha $MYZ_BUILD_SHA'"
  [ "$(g rev-parse "$GITHUB_SHA^{tree}")" = "$(g rev-parse "$MYZ_BUILD_SHA^{tree}")" ] \
    || fail "merge commit $GITHUB_SHA has another tree than the head $MYZ_BUILD_SHA: the workflow that runs would not be the head's"
  g merge-base --is-ancestor "$base_sha" "$MYZ_BUILD_SHA" || fail "base $base_sha is not an ancestor of the head: not a fast-forward"
  g update-ref -d refs/myzephyr/pr-merge
  pr_lines=("pr_merge_commit=$GITHUB_SHA" "pr_merge_parents=$base_sha $MYZ_BUILD_SHA" "pr_merge_tree_equals_head=yes" "pr_base_is_ancestor=yes")
fi

base_ref="refs/myzephyr-base/$BASE_TAG"
g fetch --quiet --no-tags --no-recurse-submodules "$BASE_REPOSITORY_URL" "+refs/tags/$BASE_TAG:$base_ref"
base_oid=$(g rev-parse --verify -q "$base_ref") || fail "base tag $BASE_TAG not fetched from $BASE_REPOSITORY_URL"

[ "$(g submodule status --recursive)" = "$sub_before" ] || fail "submodule status changed during the fetches"
tags=$(g for-each-ref --format='%(refname)' refs/tags)
[ -z "$tags" ] || fail "tags present in the checkout: $(tr '\n' ' ' <<< "$tags")"
[ -z "$(g tag -l --points-at HEAD)" ] || fail "a tag points at HEAD"
{
  echo "fetch_mode=depth-1-no-tags+unshallow-no-tags"
  echo "submodule_recursion=off (every fetch --no-recurse-submodules; fetch.recurseSubmodules=false; submodule.recurse=false)"
  echo "submodule_status_unchanged=yes ($(printf '%s' "$sub_before" | grep -c . || true) entries)"
  echo "base_ref=$base_ref $base_oid"
  echo "tags_in_checkout=0"
  echo "tags_at_head=none"
  echo "event_name=$GITHUB_EVENT_NAME"
  echo "built_commit=$MYZ_BUILD_SHA"
  printf '%s\n' ${pr_lines[@]+"${pr_lines[@]}"}
} > "$record"
cat "$record"
