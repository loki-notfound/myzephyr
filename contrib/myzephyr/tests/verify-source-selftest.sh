#!/bin/bash
# Self-test of verify-source.sh and split-signed.sh. Tests the verification, not a
# source tree: every repository and key here is made by this script.
#
#   verify-source-selftest.sh <work-dir> [--real CHECKOUT]   (<work-dir> must not exist)
#
# 1. Split equivalence: for signed objects made here (a tag, a commit, a merge commit
#    with a mergetag header, a tag whose message contains an earlier signature marker
#    line, a commit whose message contains a "gpgsig " line), the payload and signature
#    from split-signed.sh equal, byte for byte, what git itself hands to gpg, captured by
#    a gpg.program that copies its input and verifies nothing. With --real, the same for
#    every signed commit reachable from HEAD and every signed tag in that checkout; a
#    commit signed in another format (SSH), which git hands to ssh-keygen and never to
#    gpg, must be refused instead (status 2) and is counted apart.
# 2. Refusals: a tag or commit signed in another format, a tag header with a gpgsig
#    field, a commit with a gpgsig-sha256 field, with two gpgsig fields or with none.
# 3. verify-source.sh end to end on a repository made here, with keys generated here:
#    the good repository passes; each single change fails with its message: any tag at
#    HEAD in build mode (signed by the maintainer or lightweight), own commit signed by
#    another key, a changed commit under a valid signature, an unsigned own commit, the
#    base tag signed by the wrong key, a key file with secret key material, a
#    key file with two primary keys, a wrong pinned fingerprint, no gpg in PATH, a gpg
#    that is not GnuPG, a gpg that does not run. Release mode (--release-tag): the
#    maintainer-signed release tag passes; another key, a lightweight tag, a second tag
#    at HEAD, the tag on another commit, a missing tag, a name outside v*-sec.*-my.* and
#    a tag object whose header names another tag each fail.
# Needs bash 3.2 or later, git and gpg. Git and gpg run with their own empty
# configuration (no global or system git config, temporary gpg homes). Exit 0 when
# every case behaves as expected, 1 otherwise.
set -euo pipefail
export LC_ALL=C TZ=UTC GIT_CONFIG_NOSYSTEM=1 GIT_CONFIG_GLOBAL=/dev/null GIT_MERGE_AUTOEDIT=no
unset GNUPGHOME GIT_DIR GIT_WORK_TREE

here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
vs=$here/../verify-source.sh
[ $# -ge 1 ] || { echo "usage: verify-source-selftest.sh <work-dir> [--real CHECKOUT]" >&2; exit 2; }
work=$1; shift
real=
if [ $# -gt 0 ]; then
  [ $# = 2 ] && [ "$1" = --real ] || { echo "usage: verify-source-selftest.sh <work-dir> [--real CHECKOUT]" >&2; exit 2; }
  real=$(cd "$2" && pwd)
fi
[ ! -e "$work" ] || { echo "$work exists" >&2; exit 2; }
mkdir -p "$work"
work=$(cd "$work" && pwd)
fail() { echo "selftest: $*" >&2; exit 1; }
. "$here/../split-signed.sh"

passed=0 failed=0
record() {  # record <ok 0|1> <name> [detail]
  if [ "$1" = 0 ]; then passed=$((passed + 1)); echo "ok   $2"; else failed=$((failed + 1)); echo "FAIL $2${3:+ -- $3}"; fi
}

# ---------------------------------------------------------------- keys
# a short gpg home outside the work dir: the agent's socket path has a length limit
gh=$(mktemp -d "${TMPDIR:-/tmp}/vsst.XXXXXX")
trap 'gpgconf --homedir "$gh" --kill all > /dev/null 2>&1 || true; rm -rf "$gh"' EXIT
chmod 700 "$gh"
gen() {  # gen <name>: prints the new key's primary fingerprint
  gpg --batch --homedir "$gh" --pinentry-mode loopback --passphrase '' \
    --quick-gen-key "selftest $1 <$1@example.invalid>" ed25519 sign never > /dev/null 2>&1
  gpg --batch --homedir "$gh" --with-colons --list-keys "$1@example.invalid" 2> /dev/null | awk -F: '$1=="fpr" && !n {print $10; n=1}'
}
BASE=$(gen base) MAINT=$(gen maintainer) OTHER=$(gen other)
keys=$work/keys; mkdir "$keys"
for k in BASE MAINT OTHER; do gpg --batch --homedir "$gh" --armor --export "${!k}" > "$keys/$k.asc"; done
gpg --batch --homedir "$gh" --pinentry-mode loopback --passphrase '' --armor --export-secret-keys "$MAINT" > "$keys/MAINT-secret.asc"
cat "$keys/MAINT.asc" "$keys/OTHER.asc" > "$keys/two-primaries.asc"

# ---------------------------------------------------------------- repository
repo=$work/repo
G() { GNUPGHOME=$gh git -C "$repo" -c core.hooksPath=/dev/null -c commit.gpgsign=false -c tag.gpgsign=false \
        -c gpg.format=openpgp -c gpg.program=gpg -c user.name=selftest -c user.email=selftest@example.invalid "$@"; }
git init -q "$repo"
G checkout -q -b main
echo base > "$repo/README.md"; G add README.md; G commit -q -m "base"
base_commit=$(G rev-parse HEAD)
G tag -s -u "$BASE" -m "base tag" v-selftest-base
base_tag_object=$(G rev-parse refs/tags/v-selftest-base)
G update-ref refs/myzephyr-base/v-selftest-base "$base_tag_object"
G tag -d v-selftest-base > /dev/null
own() {  # own <file> <subject> [commit options]: an own commit on the current branch
  local f=$1 subj=$2; shift 2
  mkdir -p "$repo/contrib/myzephyr"; echo "$subj" > "$repo/contrib/myzephyr/$f"
  G add "contrib/myzephyr/$f"
  printf '%s\n\n- what and why\n\nOrigin: myzephyr\n' "$subj" | G commit -q -F - "$@"
}
own a.txt "Add a" -S"$MAINT"
good_head=$(G rev-parse HEAD)

# ---------------------------------------------------------------- 1. split equivalence
cap=$work/capture; mkdir "$cap"
cat > "$cap/gpg" <<'EOF'
#!/bin/sh
# stand-in for gpg: copies the signature file and the payload git passes, verifies nothing
while [ $# -gt 0 ]; do case $1 in --verify) cp "$2" "$CAPTURE/sig"; shift ;; esac; shift; done
cat > "$CAPTURE/payload"
exit 1
EOF
chmod 755 "$cap/gpg"
equiv() {  # equiv <repo> <tag|commit> <object> <label>
  local r=$1 kind=$2 obj=$3 label=$4 d=$work/eq.$3 rc=0
  rm -rf "$d"; mkdir -p "$d/git"
  git -C "$r" cat-file "$kind" "$obj" > "$d/raw"
  CAPTURE=$d/git git -C "$r" -c gpg.program="$cap/gpg" -c gpg.format=openpgp "verify-$kind" "$obj" > /dev/null 2>&1 || true
  "split_$kind" "$d" || rc=$?
  if [ "$rc" = 0 ] && [ -f "$d/git/payload" ] && cmp -s "$d/payload" "$d/git/payload" && cmp -s "$d/sig" "$d/git/sig"; then
    record 0 "split equals git's: $label"; rm -rf "$d"
  elif [ "$rc" = 2 ] && [ ! -e "$d/git/payload" ] && ! grep -q '^-----BEGIN PGP ' "$d/sig" 2> /dev/null \
       && [ "${EQUIV_ALLOW_OTHER_FORMAT:-}" = 1 ]; then
    other_format=$((other_format + 1)); record 0 "not OpenPGP, refused; git did not call gpg: $label"; rm -rf "$d"
  else
    record 1 "split equals git's: $label" "split status $rc; see $d"
  fi
}
equiv "$repo" tag "$base_tag_object" "signed tag"
equiv "$repo" commit "$good_head" "signed commit"
G checkout -q -b side "$base_commit"; own side.txt "Add side" -S"$MAINT"
G tag -s -u "$MAINT" -m "side tag" side-tag; G checkout -q main
G merge -q --no-ff -S"$MAINT" -m "Merge side" side-tag
merge=$(G rev-parse HEAD)
if G cat-file commit "$merge" | grep -q '^mergetag '; then record 0 "merge commit carries a mergetag header"; else record 1 "merge commit carries a mergetag header"; fi
equiv "$repo" commit "$merge" "signed merge commit with a mergetag header (embedded signature in continuation lines)"
printf 'marker inside the message\n-----BEGIN PGP SIGNATURE-----\nnot a signature\n' > "$work/marker-msg"
G tag -s -u "$MAINT" -F "$work/marker-msg" marker-tag "$good_head"
equiv "$repo" tag "$(G rev-parse refs/tags/marker-tag)" "tag whose message has an earlier signature marker line"
G checkout -q -b body "$good_head"
echo b > "$repo/contrib/myzephyr/b.txt"; G add contrib/myzephyr/b.txt
printf 'Add b\n\ngpgsig in the body is message text\n\nOrigin: myzephyr\n' | G commit -q -F - -S"$MAINT"
equiv "$repo" commit "$(G rev-parse HEAD)" "commit whose message has a gpgsig line"
G checkout -q main; G reset -q --hard "$good_head"; G tag -d marker-tag side-tag > /dev/null; G branch -q -D side body

other_format=0
if [ -n "$real" ]; then
  export EQUIV_ALLOW_OTHER_FORMAT=1
  n=0 bad=0
  while read -r c; do
    if git -C "$real" cat-file commit "$c" | awk '$0 == "" { exit } /^gpgsig / { f = 1 } END { exit !f }'; then
      before=$failed; equiv "$real" commit "$c" "real commit $c" > /dev/null; n=$((n + 1))
      [ "$failed" = "$before" ] || { bad=$((bad + 1)); echo "FAIL real commit $c"; }
    fi
  done < <(git -C "$real" rev-list HEAD)
  passed=$((passed - n + bad)); failed=$((failed - bad))
  record "$([ "$bad" = 0 ] && [ "$n" -gt 0 ] && echo 0 || echo 1)" "split equals git's for every signed commit reachable from HEAD in --real ($n commits: $((n - bad - other_format)) equal, $other_format not OpenPGP and refused, $bad different)"
  n=0 bad=0
  while read -r t; do
    before=$failed; equiv "$real" tag "$t" "real tag $t" > /dev/null; n=$((n + 1))
    [ "$failed" = "$before" ] || { bad=$((bad + 1)); echo "FAIL real tag $t"; }
  done < <(git -C "$real" for-each-ref --format='%(objectname) %(objecttype)' | awk '$2 == "tag" { print $1 }' | sort -u)
  passed=$((passed - n + bad)); failed=$((failed - bad))
  record "$([ "$bad" = 0 ] && [ "$n" -gt 0 ] && echo 0 || echo 1)" "split equals git's for every annotated tag in --real ($n tags, $bad different)"
  unset EQUIV_ALLOW_OTHER_FORMAT
fi

# ---------------------------------------------------------------- 2. refusals
refuse() {  # refuse <tag|commit> <want-status> <label> < object-bytes
  local kind=$1 want=$2 label=$3 d obj rc=0
  obj=$(G hash-object -t "$kind" -w --literally --stdin)
  d=$work/rf.$obj; rm -rf "$d"; mkdir "$d"; G cat-file "$kind" "$obj" > "$d/raw"
  "split_$kind" "$d" || rc=$?
  record "$([ "$rc" = "$want" ] && echo 0 || echo 1)" "refused: $label (status $rc, want $want)"
}
good_tag_raw=$(G cat-file tag "$base_tag_object")
good_commit_raw=$(G cat-file commit "$good_head")
o=$work/object   # objects go through a file: refuse must run in this shell (its counters), not in a pipe
printf '%s\n-----BEGIN SSH SIGNATURE-----\nU1NIU0lH\n-----END SSH SIGNATURE-----\n' "$good_tag_raw" > "$o"
refuse tag 2 "tag whose last signature block is SSH" < "$o"
printf '%s\n' "$good_tag_raw" | sed '1a\
gpgsig-sha256 x' > "$o"
refuse tag 3 "tag header with a gpgsig-sha256 field" < "$o"
printf '%s\n' "$good_commit_raw" | sed '/^committer /a\
gpgsig-sha256 x' > "$o"
refuse commit 3 "commit with a gpgsig-sha256 field" < "$o"
printf '%s\n' "$good_commit_raw" | awk '{ print } /^ -----END PGP SIGNATURE-----$/ && !d { print "gpgsig x"; d = 1 }' > "$o"
refuse commit 5 "commit with two gpgsig fields" < "$o"
G cat-file commit "$base_commit" > "$o"
refuse commit 5 "commit without a gpgsig field" < "$o"
printf '%s\n' "$good_commit_raw" | sed 's/^gpgsig -----BEGIN PGP SIGNATURE-----$/gpgsig -----BEGIN SSH SIGNATURE-----/' > "$o"
refuse commit 2 "commit with an SSH signature in its gpgsig field" < "$o"
printf 'object %s\ntype commit\ntag t\ntagger x <x@example.invalid> 0 +0000\n\nunsigned\n' "$base_commit" > "$o"
refuse tag 1 "tag without a signature" < "$o"

# ---------------------------------------------------------------- 3. verify-source.sh end to end
run_vs() {  # run_vs <name> <want-exit> <want-text> [env NAME=VALUE ...] -- [option overrides]
  local name=$1 want=$2 text=$3 rc=0 out=$work/vs-$((passed + failed)).txt envs=() bk=$keys/BASE.asc bf=$BASE mk=$keys/MAINT.asc mf=$MAINT bto=$base_tag_object
  local extra=()
  shift 3
  while [ $# -gt 0 ] && [ "$1" != -- ]; do envs+=("$1"); shift; done
  [ $# -gt 0 ] && shift
  while [ $# -gt 0 ]; do
    case $1 in --base-key) bk=$2 ;; --base-fingerprint) bf=$2 ;; --maintainer-key) mk=$2 ;;
      --maintainer-fingerprint) mf=$2 ;; --base-tag-object) bto=$2 ;; *) extra+=("$1" "$2") ;; esac
    shift 2
  done
  env ${envs[@]+"${envs[@]}"} bash "$vs" --checkout "$repo" --expected-head "$(G rev-parse HEAD)" \
    --base-tag v-selftest-base --base-ref refs/myzephyr-base/v-selftest-base --base-commit "$base_commit" \
    --base-tag-object "$bto" --base-key "$bk" --base-fingerprint "$bf" \
    --maintainer-key "$mk" --maintainer-fingerprint "$mf" --base-repository selftest ${extra[@]+"${extra[@]}"} --out "$out.identity" \
    > "$out" 2>&1 || rc=$?
  if [ "$rc" = "$want" ] && grep -qF -- "$text" "$out"; then record 0 "verify-source: $name"
  else record 1 "verify-source: $name" "exit $rc (want $want), text '$text' $(grep -qF -- "$text" "$out" && echo found || echo missing); see $out"; fi
}
at() { G checkout -q --detach "$1"; }   # every case starts from a clean detached HEAD

at "$good_head"
run_vs "good repository passes" 0 "verify-source: ok (HEAD $good_head, 1 own commit(s)"
last=$work/vs-$((passed + failed - 1)).txt.identity
if grep -qx "base_signing_key=$BASE" "$last" && grep -qx "own_commit $good_head=contrib/myzephyr/a.txt" "$last"; then
  record 0 "identity names the base signing key and the own commit"; else record 1 "identity names the base signing key and the own commit" "see $last"; fi

if grep -qx "tags_at_head=none" "$last" && grep -qx "tags_in_checkout=0" "$last"; then
  record 0 "identity records no tag at HEAD and no tag in the checkout"; else record 1 "identity records no tag at HEAD and no tag in the checkout" "see $last"; fi

# build mode: no tag at HEAD, whoever signed it
G tag -s -u "$MAINT" -m "release" v2.3.0-sec.9-my.9
run_vs "build mode: maintainer-signed tag at HEAD fails" 1 "a build checkout must have no tag at HEAD"
G tag -d v2.3.0-sec.9-my.9 > /dev/null
G tag v-lightweight
run_vs "build mode: lightweight tag at HEAD fails" 1 "a build checkout must have no tag at HEAD"
G tag -d v-lightweight > /dev/null
G tag v-elsewhere "$base_commit"
run_vs "build mode: a tag on another commit is counted, not refused" 0 "tags at HEAD: none"
last=$work/vs-$((passed + failed - 1)).txt.identity
if grep -qx "tags_in_checkout=1" "$last"; then record 0 "identity counts the tag in the checkout"; else record 1 "identity counts the tag in the checkout" "see $last"; fi
G tag -d v-elsewhere > /dev/null

# release mode
R=v2.3.0-sec.9-my.9
G tag -s -u "$MAINT" -m "release" "$R"
run_vs "release mode: maintainer-signed release tag passes" 0 "tags at HEAD: $R" -- --release-tag "$R"
last=$work/vs-$((passed + failed - 1)).txt.identity
if grep -qx "tags_at_head=$R" "$last" && grep -qx "release_tag $R=$(G rev-parse "refs/tags/$R") $MAINT" "$last"; then
  record 0 "identity names the release tag object and signer"; else record 1 "identity names the release tag object and signer" "see $last"; fi
G tag v-second
run_vs "release mode: a second tag at HEAD fails" 1 "expected exactly $R" -- --release-tag "$R"
G tag -d v-second > /dev/null
run_vs "release mode: name outside v*-sec.*-my.* refused" 2 "does not match v*-sec.*-my.*" -- --release-tag v2.3.0-sec.9
run_vs "release mode: tag absent at HEAD fails" 1 "expected exactly v2.3.0-sec.9-my.8" -- --release-tag v2.3.0-sec.9-my.8
G tag -d "$R" > /dev/null
G tag -s -u "$OTHER" -m "release" "$R"
run_vs "release mode: release tag signed by another key fails" 1 "release tag $R: signature does not verify" -- --release-tag "$R"
G tag -d "$R" > /dev/null
G tag "$R"
run_vs "release mode: lightweight release tag fails" 1 "is not an annotated tag" -- --release-tag "$R"
G tag -d "$R" > /dev/null
# a signed tag object named v2.3.0-sec.9-my.7, stored under refs/tags/$R
G tag -s -u "$MAINT" -m "release" v2.3.0-sec.9-my.7
G update-ref "refs/tags/$R" "$(G rev-parse refs/tags/v2.3.0-sec.9-my.7)"
G tag -d v2.3.0-sec.9-my.7 > /dev/null
run_vs "release mode: tag object named differently fails" 1 "expected $R" -- --release-tag "$R"
G tag -d "$R" > /dev/null
G tag -s -u "$MAINT" -m "release" "$R" "$base_commit"
run_vs "release mode: release tag on another commit fails" 1 "expected exactly $R" -- --release-tag "$R"
G tag -d "$R" > /dev/null

at "$base_commit"; own a.txt "Add a" -S"$OTHER"
run_vs "own commit signed by another key fails" 1 "signature does not verify"

at "$base_commit"
forged=$(G cat-file commit "$good_head" | sed 's/^Add a$/Add A/' | G hash-object -t commit -w --stdin)
at "$forged"   # same tree as the good commit, one changed message line, the good commit's signature
run_vs "changed commit message under a valid signature fails (BADSIG)" 1 "BADSIG"

at "$base_commit"; own a.txt "Add a"
run_vs "unsigned own commit fails" 1 "no signature found"

at "$good_head"
# the base tag's payload, signed by the maintainer key instead of the base key
G cat-file tag "$base_tag_object" | awk '/^-----BEGIN PGP SIGNATURE-----$/ { exit } { print }' > "$work/base-payload"
gpg --batch --quiet --homedir "$gh" -u "$MAINT" --pinentry-mode loopback --passphrase '' --armor --detach-sign \
  -o "$work/wrong.sig" "$work/base-payload"
wrong_tag=$(cat "$work/base-payload" "$work/wrong.sig" | G hash-object -t tag -w --stdin)
G update-ref refs/myzephyr-base/v-selftest-base "$wrong_tag"
run_vs "base tag signed by the maintainer key instead of the base key fails" 1 "base tag v-selftest-base: signature does not verify" -- --base-tag-object "$wrong_tag"
G update-ref refs/myzephyr-base/v-selftest-base "$base_tag_object"

run_vs "maintainer key file with secret key material fails" 1 "contains secret key material" -- --maintainer-key "$keys/MAINT-secret.asc"
run_vs "maintainer key file with two primary keys fails" 1 "must hold exactly the primary key" -- --maintainer-key "$keys/two-primaries.asc"
run_vs "wrong pinned maintainer fingerprint fails" 1 "must hold exactly the primary key" -- --maintainer-fingerprint "$OTHER"

bin=$work/bin-nogpg; mkdir "$bin"
for t in bash git awk sed grep head tail sort tr wc mktemp rm mkdir cat dirname env cmp; do ln -s "$(command -v "$t")" "$bin/$t"; done
run_vs "no gpg in PATH fails" 1 "gpg not found in PATH" "PATH=$bin" --
fake=$work/bin-fakegpg; mkdir "$fake"; cp -P "$bin"/* "$fake"/
printf '#!/bin/sh\necho "not GnuPG 1.0"\n' > "$fake/gpg"; chmod 755 "$fake/gpg"
run_vs "a gpg that is not GnuPG fails" 1 "is not GnuPG" "PATH=$fake" --
broken=$work/bin-brokengpg; mkdir "$broken"; cp -P "$bin"/* "$broken"/
printf '#!/bin/sh\necho "cannot start" >&2\nexit 127\n' > "$broken/gpg"; chmod 755 "$broken/gpg"
run_vs "a gpg that does not run fails" 1 "does not run" "PATH=$broken" --

at "$good_head"
run_vs "good repository still passes after the negative cases" 0 "verify-source: ok (HEAD $good_head"

echo "$passed/$((passed + failed)) cases as expected"
[ "$failed" = 0 ]
