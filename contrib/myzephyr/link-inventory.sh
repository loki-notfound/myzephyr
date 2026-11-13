#!/bin/bash
# Inventory of what the linker put into zephyrd, and the licence texts of its owners.
# Runs inside the builder image after the build (linux/ and cross/ build-in-container.sh).
#
#   link-inventory.sh <src-root> <build-dir> <exe> <host-triplet> <logs-dir>
#     e.g. link-inventory.sh /src build/release zephyrd x86_64-unknown-linux-gnu /logs
#
# 1. Re-runs the daemon's link command, the one line of CMake's <build-dir>/src/daemon/CMakeFiles/
#    daemon.dir/link.txt that writes ../../bin/<exe> (in <build-dir>/src/daemon; the other lines,
#    which delete and re-create the target's object archive on MinGW, are not re-run), with the
#    linker's trace option (GNU ld: -t -t, every input file and every archive member it pulls;
#    ld64: -t). The output goes to a new temporary directory under the same file name (ld64
#    derives the Mach-O UUID and GNU ld the PE export directory's name from it), an import
#    library (--out-implib) too, in the build's environment (SOURCE_DATE_EPOCH is GNU ld's PE
#    timestamp; recorded for MinGW). Records whether the output is byte-identical to bin/<exe>
#    and, if not, the differing byte ranges (relink-differences.txt); then removes it.
# 2. Each traced input: an object file, an archive with at least one pulled member ("used"),
#    an archive from which nothing was pulled ("unused") or a shared library or import stub
#    ("dynamic", not part of the binary). Owner of a used input, derived, never guessed:
#      depends:<package>  under contrib/depends/<host>/ and listed in that package's cached
#                         build tarball (contrib/depends/built/*/<package>/*.tar.gz);
#      deb:<package>      a file of the builder image, owner by dpkg -S;
#      build:<dir>        made in the build tree; not a licence owner: what it contributes is
#                         owned by the sources of its linked objects ("compiled" rows):
#                         link-sources.py finds the object file with the bytes of each pulled
#                         archive member (or the linked object itself) and CMake's
#                         DependInfo.cmake names its source; owner tree:<source directory>;
#                         an object without an established source is unresolved;
#      unknown            none of these (an "unresolved" line).
# 3. Headers and other files compiled in: the make dependency records of every linked object
#    of the build tree (link-sources.py). Each external/ directory with such files (headers,
#    included sources, data) is an owner, "header" row (header-only code such as rapidjson
#    does not show in a link trace).
# 4. Licence texts, copied to <logs-dir>/licenses/:
#      depends   the files at the top level of the package's source tarball (as fetched and
#                hash-checked by depends; its own stamp names file and SHA256) whose names
#                start with LICENSE, LICENCE, COPYING, COPYRIGHT or NOTICE (any case);
#      deb       /usr/share/doc/<package>/copyright of the image, with the package version;
#      tree      the first directory from the source directory upward with such files,
#                stopping at the tree root; inside external/<name> it never goes above
#                external/<name>, and the tree's own code takes the top-level LICENSE.
#      tree, no licence file within the boundary: the verbatim licence statements from the
#                head of every file of that directory that was compiled in (a linked object's
#                source, or a file in a linked object's dependency record). The head is
#                everything before the first line that is neither blank, a comment nor a
#                preprocessor line (after a #! line; a CR at a line end is ignored); in assembler files (.s, .S, .asm) lines
#                starting with # or ; are comments. Each comment block in the head (/* ... */,
#                consecutive // lines, or assembler comment lines) that contains "license",
#                "licence", "public domain", "permission is hereby granted" or "redistribution
#                and use in source and binary forms" (the BSD licence's wording; any case) is
#                copied unchanged to licenses/tree-header/<file>.lines-<first>-<last>.txt and
#                recorded per file ("statement" row) and once per distinct text ("license"
#                row "tree-header from=source-header file=<path> lines=<first>-<last>
#                file_sha256=<hash of the source file>"). A compiled-in file without such a
#                block is a "statement ... none" row, for information only: it does not make
#                the inventory unresolved and gets no text (owner decision 2026-11-12: such
#                files are shipped as upstream ships them; make-release-set.py does not count
#                an owner whose every statement row is "none" as lacking a text). Nothing is
#                paraphrased or supplied. No compiled-in file of the directory found at all is
#                unresolved.
#    Any other missing text is an "unresolved" line, never a silent omission.
# Writes <logs-dir>/link-inventory.tsv (kind, path, owner, sha256, detail), the raw trace
# <logs-dir>/link-trace.txt, <logs-dir>/daemon-link.txt, the trace items and their sources
# (link-items.txt, link-sources.items.tsv, link-sources.deps.tsv). Paths are as seen in the
# image.
set -uo pipefail
export LC_ALL=C
here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
src=${1:?src root}; bdir=${2:?build dir}; exe=${3:?exe}; host=${4:?host}; logs=${5:?logs dir}
src=$(cd "$src" && pwd)
linkdir=$src/$bdir/src/daemon
inv=$logs/link-inventory.tsv
lic=$logs/licenses
mkdir -p "$lic"
printf 'kind\tpath\towner\tsha256\tdetail\n' > "$inv"
row() { printf '%s\t%s\t%s\t%s\t%s\n' "$@" >> "$inv"; }
unresolved() { row status unresolved "$1" - "$2"; }
sha() { sha256sum "$1" | cut -d' ' -f1; }

cp "$linkdir/CMakeFiles/daemon.dir/link.txt" "$logs/daemon-link.txt" || { unresolved - "no link.txt"; exit 0; }
# link.txt holds one command per line; with an archive of the target's objects (MinGW) the lines
# before the link line delete and re-create CMakeFiles/daemon.dir/objects.a. Only the link line
# is re-run; the archive is used as the build left it.
mapfile -t link_lines < <(tr -d '\r' < "$logs/daemon-link.txt")
link_line= nlink=0 nprep=0
for l in "${link_lines[@]+"${link_lines[@]}"}"; do
  [ -n "${l//[[:space:]]/}" ] || continue
  if grep -qF -- " -o ../../bin/$exe " <<< " $l "; then link_line=$l; nlink=$((nlink + 1)); else nprep=$((nprep + 1)); fi
done
[ "$nlink" = 1 ] || { unresolved - "output option not found in link.txt (or on $nlink lines)"; exit 0; }
row status relink_preparation_lines_not_rerun - - "$nprep"
# The output goes to a new directory under the same file name: ld64 derives the Mach-O UUID and
# GNU ld writes the PE export directory's name from the output file name. An import library
# (--out-implib) goes there too. SOURCE_DATE_EPOCH is the build's (GNU ld writes it as the PE
# timestamp).
tdir=$(mktemp -d "${TMPDIR:-/tmp}/link-trace.XXXXXX")
cmd=$(sed "s# -o \.\./\.\./bin/$exe # -o $tdir/$exe #; s#--out-implib,\([^ ,]*/\)\{0,1\}\([^ ,/]*\)#--out-implib,$tdir/\2#g" <<< " $link_line ")
case "$host" in *-apple-darwin*) flag=-Wl,-t ;; *) flag=-Wl,-t,-t ;; esac
case "$host" in *-mingw32*)
  pets=$(python3 -I "$here/link-sources.py" pe-timestamp "$src/$bdir/bin/$exe" 2> /dev/null || echo none)
  row status relink_pe_timestamp - - "bin=$pets source_date_epoch=${SOURCE_DATE_EPOCH:-unset}" ;;
esac
( cd "$linkdir" && eval "$cmd $flag" ) > "$logs/link-trace.txt" 2>&1
rc=$?
row status relink_exit - - "$rc"
if [ "$rc" = 0 ] && cmp -s "$tdir/$exe" "$src/$bdir/bin/$exe"; then row status relink_identical - - yes
else
  row status relink_identical - - no
  if [ -f "$tdir/$exe" ]; then
    python3 -I "$here/link-sources.py" diff-ranges "$src/$bdir/bin/$exe" "$tdir/$exe" > "$logs/relink-differences.txt" 2>&1
    row status relink_differences - - "$(wc -l < "$logs/relink-differences.txt") ranges in relink-differences.txt"
  fi
  unresolved - "traced link exit $rc or output differs from bin/$exe"
fi
rm -rf "$tdir"

# file -> depends package, from the cached build tarballs (entries relative to the host prefix)
declare -A dep_owner
for t in "$src"/contrib/depends/built/*/*/*.tar.gz; do
  [ -f "$t" ] || continue
  pkg=$(basename "$(dirname "$t")")
  while IFS= read -r e; do
    e=${e#./}; [ -n "$e" ] && dep_owner[$e]=$pkg
  done < <(tar tzf "$t")
done

owner_of() {  # owner_of <absolute path>
  local p=$1 rel o
  case "$p" in
    "$src/contrib/depends/$host/"*)
      rel=${p#"$src/contrib/depends/$host/"}
      o=${dep_owner[$rel]:-}; [ -n "$o" ] && echo "depends:$o" || echo unknown ;;
    "$src/$bdir/"*)
      rel=${p#"$src/$bdir/"}; echo "tree:$(dirname "$rel" | sed 's#/CMakeFiles/.*##; s#/CMakeFiles$##')" ;;
    "$src/"*) rel=${p#"$src/"}; echo "tree:$(dirname "$rel")" ;;
    *) o=$(dpkg -S "$p" 2> /dev/null | head -n 1 | cut -d: -f1)
       [ -n "$o" ] && echo "deb:$o" || echo unknown ;;
  esac
}


declare -A kind_of member_count seen_item
order=()
unparsed=0
items=$logs/link-items.txt
: > "$items"
while IFS= read -r line; do
  line=${line%$'\r'}
  if [[ "$line" =~ ^\((.+)\)([^/]+)$ ]]; then a=${BASH_REMATCH[1]} m=${BASH_REMATCH[2]}            # GNU ld: (archive)member
  elif [[ "$line" =~ ^(.+\.(a|lib))\(([^/]+)\)$ ]]; then a=${BASH_REMATCH[1]} m=${BASH_REMATCH[3]}  # ld64: archive(member)
  else a=; fi
  if [ -n "$a" ]; then
    abs=$(cd "$linkdir" && realpath -e "$a" 2> /dev/null) || { unparsed=$((unparsed + 1)); continue; }
    [ -n "${kind_of[$abs]:-}" ] || { kind_of[$abs]=archive; order+=("$abs"); }
    if [ -z "${seen_item[$abs/$m]:-}" ]; then
      seen_item[$abs/$m]=1
      member_count[$abs]=$(( ${member_count[$abs]:-0} + 1 ))
      printf 'member\t%s\t%s\n' "$abs" "$m" >> "$items"
    fi
    continue
  fi
  abs=$(cd "$linkdir" && realpath -e "$line" 2> /dev/null) || { unparsed=$((unparsed + 1)); continue; }
  [ -f "$abs" ] || { unparsed=$((unparsed + 1)); continue; }
  [ -z "${kind_of[$abs]:-}" ] || continue
  case "$abs" in
    *.a|*.lib) kind_of[$abs]=archive ;;
    *.o|*.obj) kind_of[$abs]=object; printf 'object\t%s\n' "$abs" >> "$items" ;;
    *.so|*.so.*|*.dylib|*.tbd|*.dll) kind_of[$abs]=dynamic ;;
    *) kind_of[$abs]=other ;;
  esac
  order+=("$abs")
done < "$logs/link-trace.txt"
row status unparsed_trace_lines - - "$unparsed"

# Inputs. An archive or object made in the build tree is owned by "build:<directory>" (where it
# was made, not a licence owner); what it contributes is owned by the source files its linked
# objects were compiled from ("compiled" rows below).
declare -A used_owner
for abs in "${order[@]+"${order[@]}"}"; do
  k=${kind_of[$abs]}
  case "$abs" in "$src/$bdir/"*) o="build:$(owner_of "$abs" | sed 's#^tree:##')" ;; *) o=$(owner_of "$abs") ;; esac
  case $k in
    archive) if [ "${member_count[$abs]:-0}" -gt 0 ]; then use="used members=${member_count[$abs]}"; else use=unused; fi ;;
    object) use=used ;;
    dynamic) use=dynamic ;;
    *) use="used kind=other" ;;
  esac
  row input "$abs" "$o" "$(sha "$abs")" "$use"
  [[ "$use" == used* ]] || continue
  [[ "$o" == build:* ]] && continue
  used_owner[$o]=1
  [ "$o" != unknown ] || unresolved "$abs" "owner of a used input not found"
done

# Source of every linked object made in the build tree (link-sources.py: archive member bytes =
# object file bytes; the object's source from CMake's DependInfo.cmake), and the files each
# such object was compiled from (its make dependency records).
declare -A compiled_in   # directory relative to $src -> newline-separated relative files
add_compiled() {  # add_compiled <absolute file>
  local f=$1 rel d
  case "$f" in "$src/$bdir/"*|"$src/contrib/depends/"*) return ;; "$src/"*) ;; *) return ;; esac
  rel=${f#"$src/"}; d=$(dirname "$rel")
  case $'\n'"${compiled_in[$d]:-}"$'\n' in *$'\n'"$rel"$'\n'*) return ;; esac
  compiled_in[$d]+="$rel"$'\n'
}
python3 -I "$here/link-sources.py" map "$src" "$src/$bdir" "$items" "$logs/link-sources" \
  || unresolved - "link-sources.py map failed"
nobj=0
while IFS=$'\t' read -r it arch mem h obj source st; do
  if [ "$it" = member ]; then what="$arch($mem)"; else what=$obj; fi
  if [ "$st" != matched ]; then
    row compiled "$what" unknown "$h" "status=$st"
    unresolved "$what" "source of a linked object not established ($st)"
    continue
  fi
  nobj=$((nobj + 1))
  o=$(owner_of "$source")
  row compiled "$what" "$o" "$h" "source=${source#"$src/"} object=${obj#"$src/"}"
  used_owner[$o]=1
  [ "$o" != unknown ] || unresolved "$what" "owner of the source ${source} not found"
  add_compiled "$source"
done < "$logs/link-sources.items.tsv"
row status objects_with_source - - "$nobj"
while IFS=$'\t' read -r obj dep; do add_compiled "$dep"; done < "$logs/link-sources.deps.tsv"

licence_files() {  # licence_files <dir>: licence-like regular files directly in <dir>
  find "$1" -maxdepth 1 -type f 2> /dev/null | grep -iE '/(licen[cs]e|copying|copyright|notice)([._-][^/]*)?$' | sort
}
tree_licence_dir() {  # tree_licence_dir <relative dir>: prints the directory whose files apply
  local d=$1 stop=
  case "$d" in external/*) stop=$(cut -d/ -f1-2 <<< "$d") ;; esac
  while :; do
    [ -n "$(licence_files "$src/$d")" ] && { echo "$d"; return 0; }
    [ "$d" = "$stop" ] && return 1
    [ "$d" = . ] && return 1
    d=$(dirname "$d")
  done
}

head_blocks() {  # head_blocks <file>: "<first> <last>" of each comment block in the file's head that states a licence
  local asm=0
  case "$1" in *.s|*.S|*.asm) asm=1 ;; esac
  awk -v asm="$asm" '
    function flush() { if (s && tolower(txt) ~ /licen[cs]e|public domain|permission is hereby granted|redistribution and use in source and binary forms/) print s, e; s = 0; txt = "" }
    { sub(/\r$/, "") }
    NR == 1 && /^#!/ { next }
    inblk { txt = txt $0 "\n"; e = NR; if ($0 ~ /\*\//) inblk = 0; next }
    /^[ \t]*$/ { flush(); next }
    /^[ \t]*\/\*/ { if (!s) s = NR; txt = txt $0 "\n"; e = NR; if ($0 !~ /\*\//) inblk = 1; next }
    /^[ \t]*\/\// { if (!s) s = NR; txt = txt $0 "\n"; e = NR; next }
    asm && /^[ \t]*[#;]/ { if (!s) s = NR; txt = txt $0 "\n"; e = NR; next }
    !asm && /^[ \t]*#/ { flush(); next }
    { flush(); done = 1; exit }
    END { if (!done) flush() }' "$1"
}
header_licence() {  # header_licence <owner> <relative dir>: licence statements from the head of every compiled-in file of <dir>
  local o=$1 d=$2 rel f a b out h nfile=0
  local -A seen=()
  while IFS= read -r rel; do
    [ -n "$rel" ] || continue
    f=$src/$rel; nfile=$((nfile + 1))
    local found=0
    while read -r a b; do
      [ -n "${a:-}" ] || continue
      found=1
      out=$lic/tree-header/$rel.lines-$a-$b.txt
      mkdir -p "$(dirname "$out")"; sed -n "${a},${b}p" "$f" > "$out"
      h=$(sha "$out")
      row statement "$rel" "$o" "$(sha "$f")" "lines=$a-$b text_sha256=$h"
      if [ -n "${seen[$h]:-}" ]; then rm -f "$out"; continue; fi
      seen[$h]=1
      row license "${out#"$logs/"}" "$o" "$h" "tree-header from=source-header file=$rel lines=$a-$b file_sha256=$(sha "$f")"
    done < <(head_blocks "$f")
    # no statement: an informational row only (shipped as upstream ships it; owner decision)
    [ "$found" = 1 ] || row statement "$rel" "$o" "$(sha "$f")" none
  done < <(printf '%s' "${compiled_in[$d]:-}" | sort -u)
  [ "$nfile" -gt 0 ] || unresolved "$o" "no licence file in $d or above it within its boundary, and no compiled-in file of $d whose head could be read"
}

# files from external/ compiled into the linked objects (their make dependency records: headers,
# included sources and data): each directory is an owner (header-only code such as rapidjson
# does not show in a link trace)
hdr_dirs=$(cut -f2 "$logs/link-sources.deps.tsv" | grep -F "$src/external/" | while IFS= read -r a; do
  dirname "${a#"$src/"}"; done | sort -u)
nhdr=0
declare -A hdr_owner
for hd in $hdr_dirs; do
  nhdr=$((nhdr + 1))
  if ld=$(tree_licence_dir "$hd"); then o=tree:$ld; else o=tree:$hd; fi
  [ -n "${hdr_owner[$o]:-}" ] && continue
  hdr_owner[$o]=1
  row header "$src/$hd" "$o" - "files compiled into the linked objects"
  used_owner[$o]=1
done
row status header_dirs_from_external - - "$nhdr"
# a C/C++ object without a dependency record would hide the headers it compiled in
while IFS=$'\t' read -r it arch mem h obj source st; do
  [ "$st" = matched ] || continue
  case "$source" in *.c|*.cc|*.cpp|*.cxx|*.C) ;; *) continue ;; esac
  grep -qF -- "$obj"$'\t' "$logs/link-sources.deps.tsv" \
    || unresolved "$( [ "$it" = member ] && echo "$arch($mem)" || echo "$obj")" "no dependency record for this linked object; the headers it compiled in cannot be established"
done < "$logs/link-sources.items.tsv"

declare -A done_licence
for o in $(printf '%s\n' "${!used_owner[@]}" | sort); do
  case "$o" in
    depends:*)
      pkg=${o#depends:}
      stamp=$(ls "$src/contrib/depends/sources/download-stamps/.stamp_fetched-$pkg-"*.hash 2> /dev/null | head -n 1)
      [ -n "$stamp" ] || { unresolved "$o" "no depends download stamp"; continue; }
      while read -r h f; do
        f=$(basename "$f"); t=$src/contrib/depends/sources/$f
        [ -f "$t" ] && [ "$(sha "$t")" = "$h" ] || { unresolved "$o" "source $f missing or not the stamped hash"; continue; }
        n=0
        while IFS= read -r m; do
          [[ "$m" =~ ^[^/]+/[^/]+$ ]] || continue
          grep -qiE '^[^/]+/(licen[cs]e|copying|copyright|notice)([._-][^/]*)?$' <<< "$m" || continue
          mkdir -p "$lic/depends/$pkg"
          out=$lic/depends/$pkg/$(basename "$m")
          tar -xOf "$t" "$m" > "$out" 2> /dev/null && [ -s "$out" ] || { rm -f "$out"; continue; }
          row license "${out#"$logs/"}" "$o" "$(sha "$out")" "depends source=$f source_sha256=$h member=$m"
          n=$((n + 1))
        done < <(tar tf "$t")
        [ "$n" -gt 0 ] || unresolved "$o" "no licence file at the top of $f"
      done < "$stamp" ;;
    deb:*)
      pkg=${o#deb:}
      f=/usr/share/doc/$pkg/copyright
      [ -r "$f" ] || { unresolved "$o" "no $f"; continue; }
      mkdir -p "$lic/deb/$pkg"; cp -L "$f" "$lic/deb/$pkg/copyright"
      ver=$(dpkg-query -W -f='${Version}' "$pkg" 2> /dev/null | head -n 1)
      row license "licenses/deb/$pkg/copyright" "$o" "$(sha "$lic/deb/$pkg/copyright")" "deb package=$pkg version=$ver file=$f" ;;
    tree:*)
      d=${o#tree:}
      ld=$(tree_licence_dir "$d") || { header_licence "$o" "$d"; continue; }
      [ -z "${done_licence[$ld]:-}" ] || { row license-ref "$ld" "$o" - "same texts as $ld"; continue; }
      done_licence[$ld]=1
      while IFS= read -r f; do
        rel=${f#"$src/"}; rel=${rel#./}; out=$lic/tree/$rel
        mkdir -p "$(dirname "$out")"; cp "$f" "$out"
        row license "licenses/tree/$rel" "$o" "$(sha "$out")" "tree path=$rel"
      done < <(licence_files "$src/$ld") ;;
    unknown) ;;
  esac
done
echo "link-inventory: $(grep -c '^input' "$inv") inputs, $(grep -c '^compiled' "$inv") objects traced to sources, $(grep -c '^license' "$inv") licence texts, $(grep -c $'^status\tunresolved' "$inv") unresolved"
exit 0
