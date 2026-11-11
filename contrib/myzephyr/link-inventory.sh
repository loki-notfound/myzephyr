#!/bin/bash
# Inventory of what the linker put into zephyrd, and the licence texts of its owners.
# Runs inside the builder image after the build (linux/ and cross/ build-in-container.sh).
#
#   link-inventory.sh <src-root> <build-dir> <exe> <host-triplet> <logs-dir>
#     e.g. link-inventory.sh /src build/release zephyrd x86_64-unknown-linux-gnu /logs
#
# 1. Re-runs the daemon's link command (CMake's <build-dir>/src/daemon/CMakeFiles/daemon.dir/
#    link.txt, in <build-dir>/src/daemon) with the linker's trace option (GNU ld: -t -t,
#    every input file and every archive member it pulls; ld64: -t) and its output renamed;
#    records whether that output is byte-identical to bin/<exe>, then removes it.
# 2. Each traced input: an object file, an archive with at least one pulled member ("used"),
#    an archive from which nothing was pulled ("unused") or a shared library or import stub
#    ("dynamic", not part of the binary). Owner of a used input, derived, never guessed:
#      depends:<package>  under contrib/depends/<host>/ and listed in that package's cached
#                         build tarball (contrib/depends/built/*/<package>/*.tar.gz);
#      tree:<dir>         built from the source tree (the archive's source directory);
#      deb:<package>      a file of the builder image, owner by dpkg -S;
#      unknown            none of these (an "unresolved" line).
# 3. Headers: the CMake dependency files of the daemon target and of every used tree archive
#    name the headers compiled in; each external/<name> directory among them is a header
#    owner tree:external/<name> (header-only code such as rapidjson does not show in a
#    link trace).
# 4. Licence texts, copied to <logs-dir>/licenses/:
#      depends   the files at the top level of the package's source tarball (as fetched and
#                hash-checked by depends; its own stamp names file and SHA256) whose names
#                start with LICENSE, LICENCE, COPYING, COPYRIGHT or NOTICE (any case);
#      deb       /usr/share/doc/<package>/copyright of the image, with the package version;
#      tree      the first directory from the source directory upward with such files,
#                stopping at the tree root; inside external/<name> it never goes above
#                external/<name>, and the tree's own code takes the top-level LICENSE.
#      tree, no licence file within the boundary: the verbatim licence statement from the
#                source headers of the owner directory itself: the leading comment block
#                (/* ... */ or consecutive // lines, after blank lines and a #! line) of each
#                C/C++ source and header file directly in it, if that block contains
#                "license", "licence", "public domain" or "permission is hereby granted"
#                (any case); every distinct block is copied unchanged to
#                licenses/tree-header/<file>.lines-<first>-<last>.txt and recorded as
#                "tree-header from=source-header file=<path> lines=<first>-<last>
#                file_sha256=<hash of the source file>". Nothing is paraphrased or supplied.
#    No text found is an "unresolved" line, never a silent omission.
# Writes <logs-dir>/link-inventory.tsv (kind, path, owner, sha256, detail), the raw trace
# <logs-dir>/link-trace.txt and <logs-dir>/daemon-link.txt. Paths are as seen in the image.
set -uo pipefail
export LC_ALL=C
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
cmd=$(tr '\n' ' ' < "$logs/daemon-link.txt")
traced="../../bin/$exe.trace-link"
cmd=$(sed "s# -o \.\./\.\./bin/$exe # -o $traced #" <<< " $cmd ")
grep -qF -- " -o $traced " <<< "$cmd" || { unresolved - "output option not found in link.txt"; exit 0; }
case "$host" in *-apple-darwin*) flag=-Wl,-t ;; *) flag=-Wl,-t,-t ;; esac
( cd "$linkdir" && eval "$cmd $flag" ) > "$logs/link-trace.txt" 2>&1
rc=$?
row status relink_exit - - "$rc"
if [ "$rc" = 0 ] && cmp -s "$linkdir/$traced" "$src/$bdir/bin/$exe"; then row status relink_identical - - yes
else row status relink_identical - - no; unresolved - "traced link exit $rc or output differs from bin/$exe"; fi
rm -f "$linkdir/$traced"

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

declare -A kind_of member_count
order=()
unparsed=0
while IFS= read -r line; do
  line=${line%$'\r'}
  if [[ "$line" =~ ^\((.+)\)([^/]+)$ ]]; then a=${BASH_REMATCH[1]}            # GNU ld: (archive)member
  elif [[ "$line" =~ ^(.+\.(a|lib))\(([^/]+)\)$ ]]; then a=${BASH_REMATCH[1]}  # ld64: archive(member)
  else a=; fi
  if [ -n "$a" ]; then
    abs=$(cd "$linkdir" && realpath -e "$a" 2> /dev/null) || { unparsed=$((unparsed + 1)); continue; }
    [ -n "${kind_of[$abs]:-}" ] || { kind_of[$abs]=archive; order+=("$abs"); }
    member_count[$abs]=$(( ${member_count[$abs]:-0} + 1 ))
    continue
  fi
  abs=$(cd "$linkdir" && realpath -e "$line" 2> /dev/null) || { unparsed=$((unparsed + 1)); continue; }
  [ -f "$abs" ] || { unparsed=$((unparsed + 1)); continue; }
  [ -z "${kind_of[$abs]:-}" ] || continue
  case "$abs" in
    *.a|*.lib) kind_of[$abs]=archive ;;
    *.o|*.obj) kind_of[$abs]=object ;;
    *.so|*.so.*|*.dylib|*.tbd|*.dll) kind_of[$abs]=dynamic ;;
    *) kind_of[$abs]=other ;;
  esac
  order+=("$abs")
done < "$logs/link-trace.txt"
row status unparsed_trace_lines - - "$unparsed"

declare -A used_owner tree_archive_dirs
for abs in "${order[@]+"${order[@]}"}"; do
  k=${kind_of[$abs]} o=$(owner_of "$abs")
  case $k in
    archive) if [ "${member_count[$abs]:-0}" -gt 0 ]; then use="used members=${member_count[$abs]}"; else use=unused; fi ;;
    object) use=used ;;
    dynamic) use=dynamic ;;
    *) use="used kind=other" ;;
  esac
  row input "$abs" "$o" "$(sha "$abs")" "$use"
  [[ "$use" == used* ]] || continue
  used_owner[$o]=1
  [ "$o" != unknown ] || unresolved "$abs" "owner of a used input not found"
  case "$abs" in "$src/$bdir/"*) tree_archive_dirs[$(dirname "$abs")]=1 ;; esac
done

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

header_block() {  # header_block <file>: "<first> <last>" of its leading comment block if it states a licence
  awk 'NR == 1 && /^#!/ { next }
       state == 0 && /^[ \t]*$/ { next }
       state == 0 { if ($0 ~ /^[ \t]*\/\*/) { state = 1; s = NR } else if ($0 ~ /^[ \t]*\/\//) { state = 2; s = NR } else exit }
       state == 1 { txt = txt $0 "\n"; e = NR; if ($0 ~ /\*\//) exit; next }
       state == 2 { if ($0 ~ /^[ \t]*\/\//) { txt = txt $0 "\n"; e = NR; next } else exit }
       END { if (e && tolower(txt) ~ /licen[cs]e|public domain|permission is hereby granted/) print s, e }' "$1"
}
header_licence() {  # header_licence <owner> <relative dir>: licence rows from source headers; fails if none
  local o=$1 d=$2 f rel a b out h n=0
  local -A seen=()
  while IFS= read -r f; do
    read -r a b < <(header_block "$f") || continue
    [ -n "${a:-}" ] || continue
    rel=${f#"$src/"}; out=$lic/tree-header/$rel.lines-$a-$b.txt
    mkdir -p "$(dirname "$out")"; sed -n "${a},${b}p" "$f" > "$out"
    h=$(sha "$out")
    if [ -n "${seen[$h]:-}" ]; then rm -f "$out"; continue; fi
    seen[$h]=1
    row license "${out#"$logs/"}" "$o" "$h" "tree-header from=source-header file=$rel lines=$a-$b file_sha256=$(sha "$f")"
    n=$((n + 1))
  done < <(find "$src/$d" -maxdepth 1 -type f \( -name '*.c' -o -name '*.cc' -o -name '*.cpp' -o -name '*.cxx' \
             -o -name '*.h' -o -name '*.hh' -o -name '*.hpp' -o -name '*.hxx' -o -name '*.inl' -o -name '*.ipp' \) 2> /dev/null | sort)
  [ "$n" -gt 0 ]
}

# headers from external/ compiled into the daemon and the used tree archives: every header
# path in their CMake dependency files (absolute, or relative to the top build directory)
hdr_dirs=$(for d in "$linkdir" "${!tree_archive_dirs[@]}"; do
  find "$d/CMakeFiles" -maxdepth 2 \( -name depend.make -o -name compiler_depend.make -o -name '*.d' \) -print0 2> /dev/null \
    | xargs -0 -r grep -ohE "[^ :]*external/[^ :]+\.(h|hpp|hh|inl|ipp)" 2> /dev/null
done | sort -u | while IFS= read -r h; do
  case "$h" in /*) a=$h ;; *) a=$src/$bdir/$h ;; esac
  a=$(realpath -m "$a")
  case "$a" in "$src/external/"*) dirname "${a#"$src/"}" ;; esac
done | sort -u)
nhdr=0
declare -A hdr_owner
for hd in $hdr_dirs; do
  nhdr=$((nhdr + 1))
  if ld=$(tree_licence_dir "$hd"); then o=tree:$ld; else o=tree:$hd; fi
  [ -n "${hdr_owner[$o]:-}" ] && continue
  hdr_owner[$o]=1
  row header "$src/$hd" "$o" - "headers compiled into the daemon or a used tree archive"
  used_owner[$o]=1
done
row status header_dirs_from_external - - "$nhdr"
[ "$nhdr" -gt 0 ] || unresolved - "no external/ header found in the dependency files; header-only code cannot be established"

declare -A done_licence
for o in "${!used_owner[@]}"; do
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
      ld=$(tree_licence_dir "$d") || { header_licence "$o" "$d" \
        || unresolved "$o" "no licence file in $d or above it within its boundary, and no licence statement in a source header in $d"; continue; }
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
echo "link-inventory: $(grep -c '^input' "$inv") inputs, $(grep -c '^license' "$inv") licence texts, $(grep -c $'^status\tunresolved' "$inv") unresolved"
exit 0
