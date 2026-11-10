# Sourced by verify-source.sh and its self-test; bash 3.2 or later. Defines:
#   split_tag <dir>     <dir>/raw (a tag object) -> <dir>/payload, <dir>/sig
#   split_commit <dir>  <dir>/raw (a commit object) -> <dir>/payload, <dir>/sig
# The split is the one git 2.56 makes for a SHA-1 repository before it calls gpg:
#   tag     the signature starts at the last line that starts with one of git's
#           signature markers (gpg-interface.c parse_signed_buffer); everything
#           before it is the payload.
#   commit  the "gpgsig" header field and its continuation lines (leading space
#           removed) are the signature; every other byte, in order, is the payload
#           (commit.c parse_buffer_signed_by_header).
# What git would treat differently is refused instead of imitated. Return status:
#   0 split; 1 no signature found (tag); 2 the signature is not OpenPGP (git would
#   hand it to ssh-keygen or gpgsm, never to gpg);
#   3 a gpgsig header field in a tag, or a gpgsig* field other than "gpgsig " in a
#     commit; 4 no blank line after the commit header; 5 not exactly one gpgsig field.
# Read and write errors call fail(), which the caller defines.

# split_tag <dir>: <dir>/raw (tag object) -> <dir>/payload, <dir>/sig
split_tag() {
  local d=$1 n first
  n=$(awk 'index($0, "-----BEGIN PGP SIGNATURE-----") == 1 || index($0, "-----BEGIN PGP MESSAGE-----") == 1 ||
           index($0, "-----BEGIN SIGNED MESSAGE-----") == 1 || index($0, "-----BEGIN SSH SIGNATURE-----") == 1 { n = NR }
           END { print n + 0 }' "$d/raw") || fail "cannot read $d/raw"
  [ "$n" -gt 1 ] || return 1
  head -n "$((n - 1))" "$d/raw" > "$d/payload" || fail "cannot write $d/payload"
  tail -n "+$n" "$d/raw" > "$d/sig" || fail "cannot write $d/sig"
  first=$(head -n 1 "$d/sig")
  case "$first" in "-----BEGIN PGP SIGNATURE-----"*|"-----BEGIN PGP MESSAGE-----"*) ;; *) return 2 ;; esac
  # one awk, no pipe: under pipefail an early-exiting grep -q could fail the test
  if awk '$0 == "" { exit } /^gpgsig/ { found = 1 } END { exit !found }' "$d/payload"; then return 3; fi
}

# split_commit <dir>: <dir>/raw (commit object) -> <dir>/payload, <dir>/sig
split_commit() {
  local d=$1 hend line in_sig=0 nsig=0
  hend=$(awk '$0 == "" { print NR; exit }' "$d/raw") || fail "cannot read $d/raw"
  [ -n "$hend" ] || return 4
  : > "$d/payload"; : > "$d/sig"
  while IFS= read -r line; do
    if [ "$in_sig" = 1 ] && [ "${line:0:1}" = " " ]; then
      printf '%s\n' "${line:1}" >> "$d/sig"
      continue
    fi
    in_sig=0
    case "$line" in
      "gpgsig "*) nsig=$((nsig + 1)); printf '%s\n' "${line#gpgsig }" >> "$d/sig"; in_sig=1 ;;
      gpgsig*) return 3 ;;
      *) printf '%s\n' "$line" >> "$d/payload" ;;
    esac
  done < <(head -n "$((hend - 1))" "$d/raw")
  [ "$nsig" = 1 ] || return 5
  case "$(head -n 1 "$d/sig")" in "-----BEGIN PGP SIGNATURE-----"*|"-----BEGIN PGP MESSAGE-----"*) ;; *) return 2 ;; esac
  tail -n "+$hend" "$d/raw" >> "$d/payload" || fail "cannot write $d/payload"
}
