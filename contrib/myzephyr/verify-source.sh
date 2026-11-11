#!/bin/bash
# Verify the source checkout a build compiles: the signed zephyr-backports base it
# descends from, every own commit above that base, the exact head, the tags at the
# head, the submodule pins and a clean tree.
#
#   verify-source.sh --checkout DIR --expected-head SHA
#                    --base-tag NAME --base-ref REF --base-commit SHA --base-tag-object SHA
#                    --base-key FILE --base-fingerprint FPR
#                    --maintainer-key FILE --maintainer-fingerprint FPR
#                    [--base-repository URL] [--release-tag NAME] --out FILE
#
# Two modes for the tags at the head:
#   build    (default) no tag may point at HEAD. cmake/GitVersion.cmake prints
#            "release" instead of the commit when any tag points at HEAD, so a build
#            checkout must have none; the CI checkouts fetch no tags at all.
#   release  --release-tag NAME: exactly the tag NAME points at HEAD, and it is the
#            release tag of the already built commit (contrib/myzephyr/release/
#            draft-release.sh uses this mode; nothing is built from such a checkout).
#
# Checks, in this order, each one fatal (exit 1; usage errors exit 2):
#   base     REF holds exactly the annotated tag object SHA, whose header names tag
#            NAME, type commit and the base commit; its signature is good and was
#            made by the key with primary fingerprint FPR. Independent of HEAD.
#   head     HEAD equals the expected head (the pushed commit, GITHUB_SHA in CI).
#   history  the base commit is an ancestor of HEAD and at least one commit lies
#            above it. Every commit above the base: exactly one parent, the chain
#            is linear from the base, the message has the trailer
#            "Origin: myzephyr", the signature is good and was made by the key with
#            primary fingerprint maintainer-FPR, and it changes only allowed paths
#            (regular files, no symlinks or submodule pointers). A commit changes
#            either source (daemon source under src/, or the one build recipe
#            contrib/depends/packages/gtest.mk) or CI/documentation files, never both.
#   tags     build mode: no tag in refs/tags points at HEAD (the number of tags in
#            the checkout is recorded). Release mode: the only tag at HEAD is
#            refs/tags/NAME; NAME matches v*-sec.*-my.* (letters, digits, ".", "_",
#            "-" only); it is an annotated tag object whose header names tag NAME,
#            type commit and HEAD, signed by the maintainer key.
#   tree     every submodule is at the commit recorded in the superproject, and the
#            checkout, including submodules and ignored files, is clean.
#
# Keys: each key file is imported into its own temporary keyring (no trust
# database, no other keys). It must contain public keys only (gpg's own import
# count of secret keys read must be zero), with the pinned fingerprint as its only
# primary key; the fingerprints are passed explicitly and never taken from the file.
#
# Signatures: gpg is called directly, never through git's own gpg call. Import,
# listing and verification use the same gpg binary and pass the keyring as
# --homedir; nothing depends on GNUPGHOME reaching a gpg that git starts (under Git
# Bash, git.exe is a native program and the gpg it started found no keyring there,
# CI run 42782105005). The signed payload and the signature are taken from the
# object bytes as git 2.56 takes them for a SHA-1 repository: a tag is split at the
# last line that starts a signature block (gpg-interface.c parse_signed_buffer), a
# commit loses its "gpgsig" header field, which is the signature, with continuation
# lines (commit.c parse_buffer_signed_by_header). Objects outside what our objects
# use are refused, never guessed: a signature that is not OpenPGP, a tag header
# with a gpgsig field, a commit with more than one or no gpgsig field or with any
# other gpgsig* field. gpg runs as git runs it (--keyid-format=long --status-fd=1
# --verify); its exit status must be 0, and the status lines must show exactly one
# good and valid signature by the pinned primary key and nothing else that git or
# this script rejects.
# A missing or unusable gpg is fatal; verification is never skipped.
# Writes key=value identities to FILE for the build manifest; prints the gpg and git
# binaries used and the temporary directory (with its native form under Git Bash).
set -euo pipefail
export LC_ALL=C

ALLOWED_PATHS='^(src/p2p/net_node\.h|src/p2p/net_node\.inl|contrib/depends/packages/gtest\.mk|README\.md|\.github/workflows/(daemon-release-baseline|build|depends|tests|provenance)\.yml|contrib/myzephyr/.+)$'
SOURCE_PATHS='^(src/|contrib/depends/packages/gtest\.mk$)'

usage() { echo "usage: see the header of $0" >&2; exit 2; }
fail() { echo "verify-source: $*" >&2; exit 1; }

co= expected_head= base_tag= base_ref= base_commit= base_tag_object= base_key= base_fpr=
maint_key= maint_fpr= base_repo= out= release_tag=
while [ $# -gt 0 ]; do
  [ $# -ge 2 ] || usage
  case "$1" in
    --checkout) co=$2 ;; --expected-head) expected_head=$2 ;;
    --base-tag) base_tag=$2 ;; --base-ref) base_ref=$2 ;; --base-commit) base_commit=$2 ;;
    --base-tag-object) base_tag_object=$2 ;; --base-key) base_key=$2 ;; --base-fingerprint) base_fpr=$2 ;;
    --maintainer-key) maint_key=$2 ;; --maintainer-fingerprint) maint_fpr=$2 ;;
    --base-repository) base_repo=$2 ;; --out) out=$2 ;; --release-tag) release_tag=$2 ;;
    *) usage ;;
  esac
  shift 2
done
for v in co expected_head base_tag base_ref base_commit base_tag_object base_key base_fpr maint_key maint_fpr out; do
  [ -n "${!v}" ] || { echo "verify-source: missing --${v//_/-}" >&2; usage; }
done
for v in expected_head base_commit base_tag_object; do
  [[ "${!v}" =~ ^[0-9a-f]{40}$ ]] || { echo "verify-source: ${v//_/-} must be 40 lowercase hex digits" >&2; exit 2; }
done
for v in base_fpr maint_fpr; do
  [[ "${!v}" =~ ^[0-9A-F]{40}$ ]] || { echo "verify-source: ${v//_/-} must be a 40-digit uppercase fingerprint" >&2; exit 2; }
done
if [ -n "$release_tag" ]; then
  [[ "$release_tag" =~ ^[A-Za-z0-9._-]+$ && "$release_tag" == v*-sec.*-my.* ]] \
    || { echo "verify-source: --release-tag $release_tag does not match v*-sec.*-my.*" >&2; exit 2; }
fi
for f in "$base_key" "$maint_key"; do test -r "$f" || { echo "verify-source: key file $f not readable" >&2; exit 2; }; done
git -C "$co" rev-parse --git-dir > /dev/null 2>&1 || { echo "verify-source: $co is not a git checkout" >&2; exit 2; }

command -v gpg > /dev/null 2>&1 || fail "gpg not found in PATH; signatures cannot be verified"
gpg_bin=$(command -v gpg)
gpg_ver=$(gpg --version 2>&1) || fail "gpg ($gpg_bin) does not run: $gpg_ver"
gpg_ver=${gpg_ver%%$'\n'*}
[[ "$gpg_ver" == "gpg (GnuPG) "* ]] || fail "$gpg_bin is not GnuPG: $gpg_ver"
tmp=$(mktemp -d) || fail "cannot create a temporary directory"
trap 'rm -rf "$tmp"' EXIT
g() { git -C "$co" "$@"; }
# split_tag and split_commit (payload and signature from the object bytes, as git splits them)
lib=$(dirname "${BASH_SOURCE[0]}")/split-signed.sh
[ -r "$lib" ] || fail "$lib not readable"
. "$lib"
native_tmp=$tmp
if command -v cygpath > /dev/null 2>&1; then native_tmp=$(cygpath -m "$tmp" 2>&1) || native_tmp="cygpath failed: $native_tmp"; fi
echo "verify-source: gpg $gpg_bin ($gpg_ver); git $(command -v git) ($(git --version)); temporary directory $tmp (native: $native_tmp)"

# keyring <name> <key-file> <fingerprint>: a temporary keyring holding only that file's keys
keyring() {
  local home=$tmp/$1 file=$2 fpr=$3 st res prim
  # Owner-only through the umask, with no chmod afterwards: "mkdir -m 700" changes the
  # mode after creating the directory, and that call fails under Git Bash on the
  # Windows runner (CI run 42782105005). Creating the directory must succeed; its mode
  # is not checked afterwards, because Git Bash does not carry POSIX modes onto NTFS.
  # The keyring holds public keys only and lies inside the mktemp -d directory.
  ( umask 077 && mkdir "$home" ) || fail "cannot create the keyring directory $home"
  st=$(gpg --batch --quiet --homedir "$home" --status-fd=1 --import "$file" 2> "$home.import.log") \
    || fail "cannot import $file:"$'\n'"$(cat "$home.import.log")"
  res=$(grep '^\[GNUPG:\] IMPORT_RES ' <<< "$st") || fail "gpg reported no import result for $file"
  [ "$(wc -l <<< "$res" | tr -d ' ')" = 1 ] || fail "gpg reported more than one import result for $file"
  # IMPORT_RES fields 10 to 12: secret keys read, imported, unchanged (GnuPG doc/DETAILS)
  [ "$(awk '{print $12 "," $13 "," $14}' <<< "$res")" = "0,0,0" ] || fail "$file contains secret key material"
  prim=$(gpg --batch --homedir "$home" --with-colons --list-keys 2> "$home.list.log") \
    || fail "cannot list the keys imported from $file:"$'\n'"$(cat "$home.list.log")"
  prim=$(awk -F: '$1=="pub"{want=1; next} want && $1=="fpr"{print $10; want=0}' <<< "$prim" | sort -u)
  [ "$prim" = "$fpr" ] || fail "$file must hold exactly the primary key $fpr; found: $(tr '\n' ' ' <<< "$prim")"
}

# verify_object <tag|commit> <sha> <keyring> <what>: gpg's status lines in $tmp/v.<sha>/status
verify_object() {
  local kind=$1 obj=$2 home=$3 what=$4 d=$tmp/v.$2 rc=0
  mkdir "$d" || fail "cannot create $d"
  g cat-file "$kind" "$obj" > "$d/raw" || fail "$what: cannot read the $kind object $obj"
  "split_$kind" "$d" || rc=$?
  case $rc in
    0) ;;
    1|5) fail "$what: no signature found" ;;
    2) fail "$what: the signature is not an OpenPGP signature" ;;
    3) fail "$what: carries a gpgsig header field this verification does not accept" ;;
    4) fail "$what: no blank line after the header" ;;
    *) fail "$what: cannot split the signed object (status $rc)" ;;
  esac
  gpg --batch --homedir "$home" --keyid-format=long --status-fd=1 --verify "$d/sig" "$d/payload" \
    > "$d/status" 2> "$d/stderr" || rc=$?
  [ "$rc" = 0 ] || fail "$what: signature does not verify (gpg exit $rc):"$'\n'"$(cat "$d/status" "$d/stderr")"
  vstatus=$d/status
}

# check_sig <status-text> <primary-fingerprint> <what>: prints the signing key fingerprint
check_sig() {
  local st=$1 fpr=$2 what=$3 valid
  if grep -qE '^\[GNUPG:\] (BADSIG|ERRSIG|EXPSIG|EXPKEYSIG|REVKEYSIG|NO_PUBKEY) ' <<< "$st"; then
    fail "$what: signature not acceptable:"$'\n'"$(grep -E '^\[GNUPG:\] ' <<< "$st")"
  fi
  [ "$(grep -c '^\[GNUPG:\] GOODSIG ' <<< "$st")" = 1 ] || fail "$what: expected exactly one good signature"
  [ "$(grep -c '^\[GNUPG:\] VALIDSIG ' <<< "$st")" = 1 ] || fail "$what: expected exactly one valid signature"
  valid=$(grep '^\[GNUPG:\] VALIDSIG ' <<< "$st")
  [ "$(awk '{print $NF}' <<< "$valid")" = "$fpr" ] || fail "$what: signed by primary key $(awk '{print $NF}' <<< "$valid"), expected $fpr"
  awk '{print $3}' <<< "$valid"
}

keyring base "$base_key" "$base_fpr"
keyring maintainer "$maint_key" "$maint_fpr"
base_home=$tmp/base maint_home=$tmp/maintainer

# base: the signed tag, independent of HEAD
obj=$(g rev-parse --verify --quiet "$base_ref") || fail "base ref $base_ref not present"
[ "$obj" = "$base_tag_object" ] || fail "base ref $base_ref holds $obj, expected tag object $base_tag_object"
[ "$(g cat-file -t "$obj")" = tag ] || fail "$obj is not an annotated tag object"
hdr=$(g cat-file tag "$obj" | sed '/^$/q')
[ "$(sed -n 's/^object //p' <<< "$hdr")" = "$base_commit" ] || fail "tag object points at $(sed -n 's/^object //p' <<< "$hdr"), expected $base_commit"
[ "$(sed -n 's/^type //p' <<< "$hdr")" = commit ] || fail "tag object does not point at a commit"
[ "$(sed -n 's/^tag //p' <<< "$hdr")" = "$base_tag" ] || fail "tag object is named $(sed -n 's/^tag //p' <<< "$hdr"), expected $base_tag"
verify_object tag "$obj" "$base_home" "base tag $base_tag"
st=$(cat "$vstatus")
base_signing_key=$(check_sig "$st" "$base_fpr" "base tag $base_tag")

# head
head=$(g rev-parse HEAD)
[ "$head" = "$expected_head" ] || fail "HEAD is $head, expected $expected_head"

# history above the base
g merge-base --is-ancestor "$base_commit" HEAD || fail "base $base_commit is not an ancestor of HEAD"
commits=()   # a read loop, not mapfile: the macOS runner's /bin/bash is 3.2
while IFS= read -r c; do commits+=("$c"); done < <(g rev-list --reverse --topo-order "$base_commit..HEAD")
[ "${#commits[@]}" -ge 1 ] || fail "no own commit above the base"
prev=$base_commit
own_lines=()
for c in "${commits[@]}"; do
  read -r -a parents <<< "$(g rev-list --parents -n 1 "$c")"
  [ "${#parents[@]}" = 2 ] || fail "$c has $(( ${#parents[@]} - 1 )) parents; merges are not allowed"
  [ "${parents[1]}" = "$prev" ] || fail "$c has parent ${parents[1]}, expected $prev (linear history from the base)"
  origin=$(g log -1 --format='%(trailers:key=Origin,valueonly,separator=%x2C)' "$c")
  [ "$origin" = myzephyr ] || fail "$c: trailer Origin is '${origin}', expected exactly 'myzephyr'"
  verify_object commit "$c" "$maint_home" "commit $c"
  st=$(cat "$vstatus")
  check_sig "$st" "$maint_fpr" "commit $c" > /dev/null
  paths=() kinds=""
  while IFS=$'\t' read -r meta path; do
    [ -n "$meta" ] || continue
    read -r _ newmode _ _ status <<< "$meta"
    [[ "$path" =~ $ALLOWED_PATHS ]] || fail "$c changes $path, outside the allowed paths"
    case "$newmode" in 100644|100755|000000) ;; *) fail "$c: $path gets mode $newmode (only regular files)" ;; esac
    case "$status" in A|M|D) ;; *) fail "$c: $path has change type $status" ;; esac
    if [[ "$path" =~ $SOURCE_PATHS ]]; then kinds="$kinds source"; else kinds="$kinds ci"; fi
    paths+=("$path")
  done < <(g diff-tree --no-commit-id --no-renames -r --raw "$c")
  [ "${#paths[@]}" -ge 1 ] || fail "$c changes no file"
  if [[ "$kinds" == *source* && "$kinds" == *ci* ]]; then fail "$c mixes source (daemon or build recipe) and CI/documentation paths"; fi
  own_lines+=("own_commit $c=${paths[*]}")
  prev=$c
done

# tags at HEAD (any of them turns the version into "release")
tags_at_head=()
while read -r t; do [ -z "$t" ] || tags_at_head+=("$t"); done < <(g tag -l --points-at HEAD)
tags_in_checkout=$(g for-each-ref --format='%(refname)' refs/tags | wc -l | tr -d ' ')
tag_lines=()
if [ -z "$release_tag" ]; then
  [ "${#tags_at_head[@]}" = 0 ] || fail "tag(s) at HEAD: ${tags_at_head[*]}; a build checkout must have no tag at HEAD (the version would read \"release\")"
  tag_lines+=("tags_at_head=none" "tags_in_checkout=$tags_in_checkout")
else
  [ "${#tags_at_head[@]}" = 1 ] && [ "${tags_at_head[0]}" = "$release_tag" ] \
    || fail "release mode: the tags at HEAD are '${tags_at_head[*]-}', expected exactly $release_tag"
  tobj=$(g rev-parse --verify --quiet "refs/tags/$release_tag") || fail "refs/tags/$release_tag not present"
  [ "$(g cat-file -t "$tobj")" = tag ] || fail "tag $release_tag is not an annotated tag"
  thdr=$(g cat-file tag "$tobj" | sed '/^$/q')
  [ "$(sed -n 's/^tag //p' <<< "$thdr")" = "$release_tag" ] || fail "tag object $tobj is named $(sed -n 's/^tag //p' <<< "$thdr"), expected $release_tag"
  [ "$(sed -n 's/^type //p' <<< "$thdr")" = commit ] || fail "tag $release_tag does not point at a commit"
  [ "$(sed -n 's/^object //p' <<< "$thdr")" = "$head" ] || fail "tag $release_tag points at $(sed -n 's/^object //p' <<< "$thdr"), expected HEAD $head"
  verify_object tag "$tobj" "$maint_home" "release tag $release_tag"
  st=$(cat "$vstatus")
  check_sig "$st" "$maint_fpr" "release tag $release_tag" > /dev/null
  tag_lines+=("tags_at_head=$release_tag" "release_tag $release_tag=$tobj $maint_fpr")
fi

# tree
subs=$(g submodule status --recursive)
if grep -qE '^[-+U]' <<< "$subs"; then fail "submodules not at recorded commits:"$'\n'"$subs"; fi
dirty=$(g status --porcelain --ignored --ignore-submodules=none)
[ -z "$dirty" ] || fail "checkout not clean:"$'\n'"$dirty"

{
  echo "source_commit=$head"
  echo "source_commit_time=$(g log -1 --format=%ct HEAD)"
  printf '%s\n' "${tag_lines[@]+"${tag_lines[@]}"}"
  echo "base_repository=$base_repo"
  echo "base_tag=$base_tag"
  echo "base_tag_object=$base_tag_object"
  echo "base_commit=$base_commit"
  echo "base_signer_primary=$base_fpr"
  echo "base_signing_key=$base_signing_key"
  echo "maintainer_primary=$maint_fpr"
  echo "own_commit_count=${#commits[@]}"
  printf '%s\n' "${own_lines[@]}"
  # "|| echo", not "&& echo": with no submodule the loop must not end with status 1 (pipefail)
  while read -r sha path _; do [ -z "$path" ] || echo "submodule $path=${sha#[ ]}"; done <<< "$subs"
} | sed '/^$/d' > "$out"
echo "verify-source: ok (HEAD $head, ${#commits[@]} own commit(s) above $base_tag = $base_commit, tags at HEAD: ${release_tag:-none})"
