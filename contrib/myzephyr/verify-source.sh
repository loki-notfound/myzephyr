#!/bin/bash
# Verify the source checkout a build compiles: the signed zephyr-backports base it
# descends from, every own commit above that base, the exact head, the tags at the
# head, the submodule pins and a clean tree.
#
#   verify-source.sh --checkout DIR --expected-head SHA
#                    --base-tag NAME --base-ref REF --base-commit SHA --base-tag-object SHA
#                    --base-key FILE --base-fingerprint FPR
#                    --maintainer-key FILE --maintainer-fingerprint FPR
#                    [--base-repository URL] --out FILE
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
#            either daemon source (src/) or CI/documentation files, never both.
#   tags     every tag in refs/tags that points at HEAD makes the build report a
#            "release" version; each one must be annotated and signed by the
#            maintainer key.
#   tree     every submodule is at the commit recorded in the superproject, and the
#            checkout, including submodules and ignored files, is clean.
#
# Keys: each key file is imported into its own temporary keyring (no trust
# database, no other keys). It must contain public keys only, with the pinned
# fingerprint as its only primary key; the fingerprints are passed explicitly and
# never taken from the file.
# Writes key=value identities to FILE for the build manifest.
set -euo pipefail
export LC_ALL=C

ALLOWED_PATHS='^(src/p2p/net_node\.h|src/p2p/net_node\.inl|README\.md|\.github/workflows/(daemon-release-baseline|build|depends|tests|provenance)\.yml|contrib/myzephyr/.+)$'
SOURCE_PATHS='^src/'

usage() { echo "usage: see the header of $0" >&2; exit 2; }
fail() { echo "verify-source: $*" >&2; exit 1; }

co= expected_head= base_tag= base_ref= base_commit= base_tag_object= base_key= base_fpr=
maint_key= maint_fpr= base_repo= out=
while [ $# -gt 0 ]; do
  [ $# -ge 2 ] || usage
  case "$1" in
    --checkout) co=$2 ;; --expected-head) expected_head=$2 ;;
    --base-tag) base_tag=$2 ;; --base-ref) base_ref=$2 ;; --base-commit) base_commit=$2 ;;
    --base-tag-object) base_tag_object=$2 ;; --base-key) base_key=$2 ;; --base-fingerprint) base_fpr=$2 ;;
    --maintainer-key) maint_key=$2 ;; --maintainer-fingerprint) maint_fpr=$2 ;;
    --base-repository) base_repo=$2 ;; --out) out=$2 ;;
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
for f in "$base_key" "$maint_key"; do test -r "$f" || { echo "verify-source: key file $f not readable" >&2; exit 2; }; done
git -C "$co" rev-parse --git-dir > /dev/null 2>&1 || { echo "verify-source: $co is not a git checkout" >&2; exit 2; }

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
g() { git -C "$co" "$@"; }

# keyring <name> <key-file> <fingerprint>: a temporary keyring holding only that file's keys
keyring() {
  local home=$tmp/$1 file=$2 fpr=$3 prim
  mkdir -m 700 "$home"
  gpg --batch --quiet --homedir "$home" --import "$file" 2> "$home.import.log" \
    || fail "cannot import $file"
  [ -z "$(gpg --batch --homedir "$home" --with-colons --list-secret-keys 2> /dev/null)" ] \
    || fail "$file contains secret key material"
  prim=$(gpg --batch --homedir "$home" --with-colons --list-keys \
    | awk -F: '$1=="pub"{want=1; next} want && $1=="fpr"{print $10; want=0}' | sort -u)
  [ "$prim" = "$fpr" ] || fail "$file must hold exactly the primary key $fpr; found: $(tr '\n' ' ' <<< "$prim")"
  echo "$home"
}

# check_sig <status-text> <primary-fingerprint> <what>: prints the signing key fingerprint
check_sig() {
  local st=$1 fpr=$2 what=$3 valid
  if grep -qE '^\[GNUPG:\] (BADSIG|ERRSIG|EXPSIG|EXPKEYSIG|REVKEYSIG|NO_PUBKEY) ' <<< "$st"; then
    fail "$what: signature not acceptable:"$'\n'"$(grep -E '^\[GNUPG:\] ' <<< "$st")"
  fi
  grep -q '^\[GNUPG:\] GOODSIG ' <<< "$st" || fail "$what: no good signature"
  [ "$(grep -c '^\[GNUPG:\] VALIDSIG ' <<< "$st")" = 1 ] || fail "$what: expected exactly one valid signature"
  valid=$(grep '^\[GNUPG:\] VALIDSIG ' <<< "$st")
  [ "$(awk '{print $NF}' <<< "$valid")" = "$fpr" ] || fail "$what: signed by primary key $(awk '{print $NF}' <<< "$valid"), expected $fpr"
  awk '{print $3}' <<< "$valid"
}

base_home=$(keyring base "$base_key" "$base_fpr")
maint_home=$(keyring maintainer "$maint_key" "$maint_fpr")

# base: the signed tag, independent of HEAD
obj=$(g rev-parse --verify --quiet "$base_ref") || fail "base ref $base_ref not present"
[ "$obj" = "$base_tag_object" ] || fail "base ref $base_ref holds $obj, expected tag object $base_tag_object"
[ "$(g cat-file -t "$obj")" = tag ] || fail "$obj is not an annotated tag object"
hdr=$(g cat-file tag "$obj" | sed '/^$/q')
[ "$(sed -n 's/^object //p' <<< "$hdr")" = "$base_commit" ] || fail "tag object points at $(sed -n 's/^object //p' <<< "$hdr"), expected $base_commit"
[ "$(sed -n 's/^type //p' <<< "$hdr")" = commit ] || fail "tag object does not point at a commit"
[ "$(sed -n 's/^tag //p' <<< "$hdr")" = "$base_tag" ] || fail "tag object is named $(sed -n 's/^tag //p' <<< "$hdr"), expected $base_tag"
st=$(GNUPGHOME=$base_home g verify-tag --raw "$obj" 2>&1) || fail "base tag signature does not verify:"$'\n'"$st"
base_signing_key=$(check_sig "$st" "$base_fpr" "base tag $base_tag")

# head
head=$(g rev-parse HEAD)
[ "$head" = "$expected_head" ] || fail "HEAD is $head, expected $expected_head"

# history above the base
g merge-base --is-ancestor "$base_commit" HEAD || fail "base $base_commit is not an ancestor of HEAD"
mapfile -t commits < <(g rev-list --reverse --topo-order "$base_commit..HEAD")
[ "${#commits[@]}" -ge 1 ] || fail "no own commit above the base"
prev=$base_commit
own_lines=()
for c in "${commits[@]}"; do
  read -r -a parents <<< "$(g rev-list --parents -n 1 "$c")"
  [ "${#parents[@]}" = 2 ] || fail "$c has $(( ${#parents[@]} - 1 )) parents; merges are not allowed"
  [ "${parents[1]}" = "$prev" ] || fail "$c has parent ${parents[1]}, expected $prev (linear history from the base)"
  origin=$(g log -1 --format='%(trailers:key=Origin,valueonly,separator=%x2C)' "$c")
  [ "$origin" = myzephyr ] || fail "$c: trailer Origin is '${origin}', expected exactly 'myzephyr'"
  st=$(GNUPGHOME=$maint_home g verify-commit --raw "$c" 2>&1) || fail "$c: signature does not verify:"$'\n'"$st"
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
  if [[ "$kinds" == *source* && "$kinds" == *ci* ]]; then fail "$c mixes daemon source and CI/documentation paths"; fi
  own_lines+=("own_commit $c=${paths[*]}")
  prev=$c
done

# tags at HEAD (they turn the version into "release")
tag_lines=()
while read -r t; do
  [ -n "$t" ] || continue
  tobj=$(g rev-parse "refs/tags/$t")
  [ "$(g cat-file -t "$tobj")" = tag ] || fail "tag $t at HEAD is not an annotated tag"
  st=$(GNUPGHOME=$maint_home g verify-tag --raw "$tobj" 2>&1) || fail "tag $t at HEAD: signature does not verify:"$'\n'"$st"
  check_sig "$st" "$maint_fpr" "tag $t" > /dev/null
  tag_lines+=("source_tag $t=$tobj $maint_fpr")
done < <(g tag -l --points-at HEAD)

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
  while read -r sha path _; do [ -n "$path" ] && echo "submodule $path=${sha#[ ]}"; done <<< "$subs"
} | sed '/^$/d' > "$out"
echo "verify-source: ok (HEAD $head, ${#commits[@]} own commit(s) above $base_tag = $base_commit, tags at HEAD: ${#tag_lines[@]})"
