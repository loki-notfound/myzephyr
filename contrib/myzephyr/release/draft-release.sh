#!/bin/bash
# Make a draft GitHub release from the release set of an already finished run. Run locally by
# the owner (or by the reviewer on the owner's word); never in CI. It never publishes and
# never signs anything.
#
#   draft-release.sh [--dry-run] [--repo OWNER/NAME] [--branch BRANCH] [--reports FILE]
#                    [--workdir DIR] <tag> <run-id>
#   defaults: --repo loki-notfound/myzephyr, --branch my/v2.3.0, --workdir a new temporary
#   directory (must not exist when given). Needs gh (authenticated), git, gpg, python3.
#
# Pinned values (base repository, tag, tag object, commit, fingerprints) are read from the
# workflow file of the checkout this script lives in; keys and verify-source.sh are that
# checkout's, never the downloaded ones.
#  1. <tag> matches v*-sec.*-my.*; <run-id> is a number.
#  2. The run (gh api): workflow .github/workflows/daemon-release-baseline.yml, event push,
#     branch <branch>, completed with conclusion success; its attempt is recorded. Refuses if a
#     release for <tag> exists.
#  3. A fresh clone without tags (--workdir) fetches <tag>, the branch head and the base tag:
#     the tag's commit is the run's head commit, and that commit is the branch head or an
#     ancestor of it (and the branch head equals what the API says). verify-source.sh
#     --release-tag <tag> on the clean checkout of that commit: base tag and signature, every
#     own commit, exactly this annotated tag at HEAD, signed by the pinned maintainer key.
#  4. The artifact release-set-<commit> of that run: not expired; its zip is downloaded and
#     must have GitHub's recorded digest; then check-release-set.py: SHA256SUMS, every
#     manifest (commit, run and attempt, version string without "release", complete
#     licences), every archive unpacks to the named binary. It writes the release notes.
#  5. gh release create <tag> --draft --verify-tag with exactly the flat files of the set
#     (a quoted array) and the notes. With --dry-run everything except this step runs, and the
#     exact command and file list are printed.
# Exit 1 on any refusal, 2 on a usage error. MYZ_ORIGIN_URL replaces the clone source
# https://github.com/<repo>.git (the self-test points it at a local repository).
set -euo pipefail
export LC_ALL=C
here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
tools=$(dirname "$here")
top=$(dirname "$(dirname "$tools")")
usage() { echo "usage: draft-release.sh [--dry-run] [--repo OWNER/NAME] [--branch BRANCH] [--reports FILE] [--workdir DIR] <tag> <run-id>" >&2; exit 2; }
refuse() { echo "draft-release: refused: $*" >&2; exit 1; }

dry=0 repo=loki-notfound/myzephyr branch=my/v2.3.0 reports= workdir= pos=()
while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) dry=1; shift ;;
    --repo|--branch|--reports|--workdir) [ $# -ge 2 ] || usage; v=$2
      case "$1" in --repo) repo=$v ;; --branch) branch=$v ;; --reports) reports=$v ;; --workdir) workdir=$v ;; esac; shift 2 ;;
    -*) usage ;;
    *) pos+=("$1"); shift ;;
  esac
done
[ "${#pos[@]}" = 2 ] || usage
tag=${pos[0]} run=${pos[1]}
[[ "$tag" =~ ^[A-Za-z0-9._-]+$ && "$tag" == v*-sec.*-my.* ]] || { echo "draft-release: tag $tag does not match v*-sec.*-my.*" >&2; exit 2; }
[[ "$run" =~ ^[1-9][0-9]*$ ]] || { echo "draft-release: run id $run is not a number" >&2; exit 2; }
[[ "$repo" =~ ^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$ ]] || { echo "draft-release: --repo $repo is not OWNER/NAME" >&2; exit 2; }
[[ "$branch" =~ ^my/[A-Za-z0-9._/-]+$ ]] || { echo "draft-release: --branch $branch is not under my/" >&2; exit 2; }
[ -z "$reports" ] || [ -r "$reports" ] || { echo "draft-release: --reports $reports not readable" >&2; exit 2; }
for t in gh git gpg python3; do command -v "$t" > /dev/null || refuse "$t not found"; done
PY=python3

wf=$top/.github/workflows/daemon-release-baseline.yml
pin() { local v; v=$(sed -n "s/^  $1: //p" "$wf" | tr -d '"'); [ -n "$v" ] || refuse "pin $1 not found in $wf"; echo "$v"; }
BASE_REPOSITORY_URL=$(pin BASE_REPOSITORY_URL) BASE_TAG=$(pin BASE_TAG) BASE_COMMIT=$(pin BASE_COMMIT)
BASE_TAG_OBJECT=$(pin BASE_TAG_OBJECT) BASE_FINGERPRINT=$(pin BASE_FINGERPRINT) MAINTAINER_FINGERPRINT=$(pin MAINTAINER_FINGERPRINT)
origin=${MYZ_ORIGIN_URL:-https://github.com/$repo.git}

if [ -n "$workdir" ]; then [ ! -e "$workdir" ] || usage; mkdir -p "$workdir"; else workdir=$(mktemp -d); fi
workdir=$(cd "$workdir" && pwd)
echo "draft-release: working in $workdir"

# 2. the run
gh api "repos/$repo/actions/runs/$run" > "$workdir/run.json" || refuse "cannot read run $run of $repo"
read -r head_sha attempt run_url < <("$PY" -I - "$workdir/run.json" "$branch" <<'EOF'
import json, sys
r = json.load(open(sys.argv[1])); branch = sys.argv[2]
for what, got, want in (("workflow", r.get("path"), ".github/workflows/daemon-release-baseline.yml"), ("event", r.get("event"), "push"),
                        ("branch", r.get("head_branch"), branch), ("status", r.get("status"), "completed"),
                        ("conclusion", r.get("conclusion"), "success")):
    if got != want:
        print(f"run {r.get('id')}: {what} is {got!r}, expected {want!r}", file=sys.stderr); sys.exit(1)
a = r.get("run_attempt")
if not isinstance(a, int) or a < 1 or not isinstance(r.get("head_sha"), str) or len(r["head_sha"]) != 40:
    print("run: attempt or head commit missing", file=sys.stderr); sys.exit(1)
print(r["head_sha"], a, f"{r['html_url']}/attempts/{a}")
EOF
) || refuse "run $run is not a successful daemon-release-baseline push run on $branch"
echo "draft-release: run $run attempt $attempt, head $head_sha"
if gh release view "$tag" -R "$repo" > /dev/null 2>&1; then refuse "a release for $tag already exists"; fi
branch_head=$(gh api "repos/$repo/branches/${branch//\//%2F}" --jq .commit.sha) || refuse "cannot read branch $branch"

# 3. clone, tag and source verification
clone=$workdir/clone
git clone -q --no-checkout --no-tags "$origin" "$clone"
g() { git -C "$clone" "$@"; }
g config remote.origin.tagOpt --no-tags
g fetch -q --no-tags origin "refs/tags/$tag:refs/tags/$tag" || refuse "tag $tag not on $origin"
g fetch -q --no-tags origin "+refs/heads/$branch:refs/myzephyr/branch-head" || refuse "branch $branch not on $origin"
g fetch -q --no-tags "$BASE_REPOSITORY_URL" "+refs/tags/$BASE_TAG:refs/myzephyr-base/$BASE_TAG"
tag_commit=$(g rev-parse --verify --quiet "refs/tags/$tag^{commit}") || refuse "tag $tag does not name a commit"
[ "$tag_commit" = "$head_sha" ] || refuse "tag $tag points at $tag_commit, the run built $head_sha"
[ "$(g rev-parse refs/myzephyr/branch-head)" = "$branch_head" ] || refuse "branch $branch moved while checking"
g merge-base --is-ancestor "$tag_commit" "$branch_head" || refuse "$tag_commit is not $branch's head or an ancestor of it"
g checkout -q --detach "$tag_commit"
g submodule update -q --init --recursive
g update-ref -d refs/myzephyr/branch-head
bash "$tools/verify-source.sh" --checkout "$clone" --expected-head "$tag_commit" \
  --base-tag "$BASE_TAG" --base-ref "refs/myzephyr-base/$BASE_TAG" --base-commit "$BASE_COMMIT" \
  --base-tag-object "$BASE_TAG_OBJECT" --base-repository "$BASE_REPOSITORY_URL" \
  --base-key "$tools/keys/zephyr-backports-release.asc" --base-fingerprint "$BASE_FINGERPRINT" \
  --maintainer-key "$tools/keys/myzephyr-maintainer.asc" --maintainer-fingerprint "$MAINTAINER_FINGERPRINT" \
  --release-tag "$tag" --out "$workdir/source-identity.txt" || refuse "source or tag verification failed"

# 4. the release set
gh api "repos/$repo/actions/runs/$run/artifacts?per_page=100" > "$workdir/artifacts.json" || refuse "cannot list the run's artifacts"
read -r art_id art_digest < <("$PY" -I - "$workdir/artifacts.json" "release-set-$tag_commit" <<'EOF'
import json, re, sys
arts = [x for x in json.load(open(sys.argv[1])).get("artifacts", []) if x.get("name") == sys.argv[2]]
if len(arts) != 1:
    print(f"{len(arts)} artifacts named {sys.argv[2]}", file=sys.stderr); sys.exit(1)
a = arts[0]
d = a.get("digest") or ""
if a.get("expired") or not re.fullmatch(r"sha256:[0-9a-f]{64}", d):
    print(f"artifact {a.get('id')}: expired {a.get('expired')}, digest {d!r}", file=sys.stderr); sys.exit(1)
print(a["id"], d[len("sha256:"):])
EOF
) || refuse "release-set-$tag_commit not available with a digest in run $run"
gh api "repos/$repo/actions/artifacts/$art_id/zip" > "$workdir/release-set.zip" || refuse "cannot download artifact $art_id"
[ "$(sha256sum "$workdir/release-set.zip" | cut -d' ' -f1)" = "$art_digest" ] || refuse "artifact $art_id does not match GitHub's digest"
mkdir "$workdir/set"
"$PY" -I -c 'import sys, zipfile
z = zipfile.ZipFile(sys.argv[1])
for n in z.namelist():
    if "/" in n or n.startswith(".") or n == "":
        sys.exit(f"artifact member {n!r} is not a flat file name")
z.extractall(sys.argv[2])' "$workdir/release-set.zip" "$workdir/set" || refuse "release set is not a flat set of files"
files_list=$("$PY" -I "$here/check-release-set.py" --dir "$workdir/set" --commit "$tag_commit" --repository "$repo" \
  --ref "refs/heads/$branch" --run-id "$run" --run-attempt "$attempt" --run-url "$run_url" --tag "$tag" \
  --notes "$workdir/notes.md" ${reports:+--reports "$reports"}) || refuse "release set check failed"
files=()
while IFS= read -r f; do files+=("$workdir/set/$f"); done <<< "$files_list"

# 5. the draft release
cmd=(gh release create "$tag" -R "$repo" --draft --verify-tag --title "$tag" --notes-file "$workdir/notes.md" "${files[@]}")
echo "draft-release: ${#files[@]} files:"; printf '  %s\n' "${files[@]##*/}"
printf 'draft-release: command:'; printf ' %q' "${cmd[@]}"; echo
if [ "$dry" = 1 ]; then echo "draft-release: dry run, nothing created; notes in $workdir/notes.md"; exit 0; fi
"${cmd[@]}"
echo "draft-release: draft created; check it, sign SHA256SUMS, upload the signature, then publish by hand"
