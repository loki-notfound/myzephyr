#!/bin/bash
# Self-test of link-inventory.sh (and link-sources.py) with a small synthetic tree linked by the
# host's gcc/GNU ld (Linux only; the real inventory runs in the builder images). Nothing here is
# zephyrd.
#
#   link-inventory-selftest.sh <work-dir>      (<work-dir> must not exist)
#
# The tree has: an own object compiled from src/daemon/main.cpp (top-level LICENSE), an archive
# built in external/ext from external/ext/ext.cpp (its LICENSE), a depends package "dep" (cached
# build tarball, hash-stamped source tarball with COPYING at its top and a LICENSE deeper down
# that must not be taken) with one member pulled and one archive nothing is pulled from, a
# header-only external/hdr named in a dependency record, libstdc++ linked statically (owner by
# dpkg -S), and CMake DependInfo.cmake files naming each object's source. Checks: inputs made in
# the build tree owned by build:<dir>, their linked objects traced to sources ("compiled" rows)
# and owned by the source directories, used/unused, licence rows and their hashes, identical
# re-link into a temporary directory under the same file name, zero unresolved; then single
# changes: an external source without licence, an input from outside every known owner, a
# source tarball whose hash differs from its stamp, a link.txt without the output option, no
# dependency record of an object, an object without a DependInfo source, a member whose object
# is gone.
# Re-link (round 16): a three-line link.txt (delete and re-create the target's object archive,
# then link, as CMake writes it for MinGW) re-runs only the link line, leaves the archive as it
# was and is identical; a stand-in linker that writes its output file's name into the output
# shows that the re-link keeps the name (identical) and moves --out-implib into the temporary
# directory (the build's import library untouched); a re-link that differs records its ranges.
# Source headers: files of external/ext compiled in (the source, headers in its dependency
# record, a file in a subdirectory) without a licence file: every licence block in the head
# (after preprocessor lines; CRLF; // and /* */; assembler # comments; BSD wording) copied
# verbatim, one "statement" row per file, identical texts once; a compiled-in file without a
# statement is a "statement ... none" row and unresolved; a statement after code does not count;
# a licence file present: the file is taken, no statement rows. Source tarballs: a used depends
# package named readline has its stamped source tarball copied to depends-sources/ with a
# "source-tarball" row; "dep" does not. link-sources.py: BSD archive members padded with
# newlines match their objects; pe-timestamp and diff-ranges on crafted headers.
set -euo pipefail
export LC_ALL=C
here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
li=$here/../link-inventory.sh
ls_py=$here/../link-sources.py
[ $# = 1 ] || { echo "usage: link-inventory-selftest.sh <work-dir>" >&2; exit 2; }
[ ! -e "$1" ] || { echo "$1 exists" >&2; exit 2; }
mkdir -p "$1"; work=$(cd "$1" && pwd)
passed=0 failed=0
record() { if [ "$1" = 0 ]; then passed=$((passed + 1)); echo "ok   $2"; else failed=$((failed + 1)); echo "FAIL $2${3:+ -- $3}"; fi; }
H=x86_64-unknown-linux-gnu

dependinfo() {  # dependinfo <file> <lang> <source> <object> ...
  local f=$1 lang=$2; shift 2
  { echo "set(CMAKE_DEPENDS_LANGUAGES \"$lang\")"; echo "set(CMAKE_DEPENDS_CHECK_$lang"
    while [ $# -ge 2 ]; do echo "  \"$1\" \"$2\""; shift 2; done; echo "  )"; } > "$f"
}
make_tree() {  # make_tree <root> [depends package name]
  local r=$1 P=${2:-dep} s=$1/src b=$1/src/build/release
  local od=$b/src/daemon/CMakeFiles/daemon.dir ed=$b/external/ext/CMakeFiles/ext.dir
  mkdir -p "$s/src/daemon" "$s/external/ext" "$s/external/hdr/include" "$s/contrib/depends/$H/lib" "$s/contrib/depends/built/$H/$P" \
           "$s/contrib/depends/sources/download-stamps" "$od" "$ed" "$b/bin"
  echo "own licence" > "$s/LICENSE"
  echo "ext licence" > "$s/external/ext/LICENSE"
  echo "hdr licence" > "$s/external/hdr/LICENSE"
  echo 'inline int hdr() { return 3; }' > "$s/external/hdr/include/hdr.hpp"
  printf 'extern "C" int ext(){return 1;}\n' > "$s/external/ext/ext.cpp"
  g++ -c "$s/external/ext/ext.cpp" -o "$ed/ext.cpp.o"
  ( cd "$ed" && ar rcs "$b/external/ext/libext.a" ext.cpp.o )
  dependinfo "$ed/DependInfo.cmake" CXX "$s/external/ext/ext.cpp" "$ed/ext.cpp.o"
  echo "external/ext/CMakeFiles/ext.dir/ext.cpp.o: ../../external/ext/ext.cpp" > "$ed/depend.make"
  ( cd "$r" && printf 'int dep(void){return 2;}\n' > dep.c && printf 'int unused_dep(){return 9;}\n' > dep2.c \
    && gcc -c dep.c dep2.c && ar rcs "$s/contrib/depends/$H/lib/lib$P.a" dep.o dep2.o \
    && printf 'int lonely(){return 7;}\n' > lonely.c && gcc -c lonely.c && ar rcs "$s/contrib/depends/$H/lib/liblonely.a" lonely.o )
  ( cd "$s/contrib/depends/$H" && tar czf "$s/contrib/depends/built/$H/$P/$P-1.0-abc.tar.gz" "./lib/lib$P.a" ./lib/liblonely.a )
  mkdir -p "$r/$P-1.0/sub"; echo "$P copying" > "$r/$P-1.0/COPYING"; echo "deeper" > "$r/$P-1.0/sub/LICENSE"
  ( cd "$r" && tar czf "$s/contrib/depends/sources/$P-1.0.tar.gz" "$P-1.0" )
  echo "$(sha256sum "$s/contrib/depends/sources/$P-1.0.tar.gz" | cut -d' ' -f1)  $P-1.0.tar.gz" \
    > "$s/contrib/depends/sources/download-stamps/.stamp_fetched-$P-$P-1.0.tar.gz.hash"
  printf '#include <iostream>\n#include "hdr.hpp"\nextern "C" int ext(); extern "C" int dep();\nint main(){std::cout<<ext()+dep()+hdr();}\n' > "$s/src/daemon/main.cpp"
  g++ -I"$s/external/hdr/include" -c "$s/src/daemon/main.cpp" -o "$od/main.cpp.o"
  dependinfo "$od/DependInfo.cmake" CXX "$s/src/daemon/main.cpp" "$od/main.cpp.o"
  printf 'src/daemon/CMakeFiles/daemon.dir/main.cpp.o: ../../src/daemon/main.cpp\nsrc/daemon/CMakeFiles/daemon.dir/main.cpp.o: ../../external/hdr/include/hdr.hpp\n' > "$od/depend.make"
  echo "g++ CMakeFiles/daemon.dir/main.cpp.o -o ../../bin/zephyrd ../../external/ext/libext.a ../../../../contrib/depends/$H/lib/lib$P.a ../../../../contrib/depends/$H/lib/liblonely.a -static-libstdc++ -static-libgcc" \
    > "$od/link.txt"
  ( cd "$b/src/daemon" && sh CMakeFiles/daemon.dir/link.txt )
}
run_li() { mkdir -p "$1/logs"; TMPDIR=$work/tmp bash "$li" "$1/src" build/release zephyrd "$H" "$1/logs" > "$1/li.out" 2>&1; }
has() { grep -qP -- "$2" "$1/logs/link-inventory.tsv"; }
nunres() { grep -c $'^status\tunresolved' "$1/logs/link-inventory.tsv" || true; }
fsha() { sha256sum "$1" | cut -d' ' -f1; }
B=build/release
mkdir "$work/tmp"

w=$work/good; mkdir "$w"; make_tree "$w"; binsha=$(fsha "$w/src/$B/bin/zephyrd"); run_li "$w"
has "$w" "^input\t[^\t]*/main\.cpp\.o\tbuild:src/daemon\t[0-9a-f]{64}\tused$" \
  && has "$w" "^compiled\t[^\t]*/main\.cpp\.o\ttree:src/daemon\t[0-9a-f]{64}\tsource=src/daemon/main\.cpp object=$B/src/daemon/CMakeFiles/daemon\.dir/main\.cpp\.o$" \
  && record 0 "own object: input owned by build:src/daemon, traced to src/daemon/main.cpp, owner tree:src/daemon" || record 1 "own object traced to its source"
has "$w" "^input\t[^\t]*/external/ext/libext\.a\tbuild:external/ext\t[0-9a-f]{64}\tused members=1$" \
  && has "$w" "^compiled\t[^\t]*/libext\.a\(ext\.cpp\.o\)\ttree:external/ext\t[0-9a-f]{64}\tsource=external/ext/ext\.cpp " \
  && record 0 "external archive: build:external/ext, its member traced to external/ext/ext.cpp, owner tree:external/ext" || record 1 "external archive member traced to its source"
has "$w" "^input\t[^\t]*/lib/libdep\.a\tdepends:dep\t[0-9a-f]{64}\tused members=1$" && record 0 "depends archive used, owner depends:dep (from the cached tarball)" || record 1 "depends archive used, owner depends:dep"
has "$w" "^input\t[^\t]*/lib/liblonely\.a\tdepends:dep\t[0-9a-f]{64}\tunused$" && record 0 "archive with nothing pulled is unused" || record 1 "archive with nothing pulled is unused"
has "$w" "^input\t[^\t]*/libstdc\+\+\.a\tdeb:libstdc\+\+-[0-9]+-dev\t" && record 0 "static libstdc++ owned by its Debian package" || record 1 "static libstdc++ owned by its Debian package"
has "$w" "^license\tlicenses/tree/LICENSE\ttree:src/daemon\t" && record 0 "own code takes the top-level LICENSE" || record 1 "own code takes the top-level LICENSE"
has "$w" "^license\tlicenses/tree/external/ext/LICENSE\ttree:external/ext\t" && record 0 "external source takes its LICENSE" || record 1 "external source takes its LICENSE"
! has "$w" "^license\t[^\t]*\tbuild:" && record 0 "no licence row for a build:<dir> owner" || record 1 "no licence row for a build:<dir> owner"
has "$w" "^header\t[^\t]*/external/hdr/include\ttree:external/hdr\t" && has "$w" "^license\tlicenses/tree/external/hdr/LICENSE\t" \
  && record 0 "header-only external/hdr found in the object's dependency record, its LICENSE taken" || record 1 "header-only external/hdr found, LICENSE taken"
has "$w" "^license\tlicenses/depends/dep/COPYING\tdepends:dep\t[0-9a-f]{64}\tdepends source=dep-1\.0\.tar\.gz source_sha256=[0-9a-f]{64} member=dep-1\.0/COPYING$" \
  && ! has "$w" "member=dep-1.0/sub/LICENSE" && record 0 "depends licence from the top of the stamped source tarball only" || record 1 "depends licence from the top of the stamped source tarball only"
has "$w" "^license\tlicenses/deb/libstdc\+\+-[0-9]+-dev/copyright\tdeb:libstdc\+\+-[0-9]+-dev\t[0-9a-f]{64}\tdeb package=libstdc\+\+-[0-9]+-dev version=\S+ file=" \
  && record 0 "Debian copyright file copied with package version" || record 1 "Debian copyright file copied with package version"
ok=0; while IFS=$'\t' read -r k p o h d; do
  [ "$k" = license ] || continue
  [ "$(fsha "$w/logs/$p")" = "$h" ] || ok=1
done < "$w/logs/link-inventory.tsv"; record $ok "every licence row's hash matches the copied text"
has "$w" "^status\trelink_identical\t-\t-\tyes$" && has "$w" "^status\trelink_preparation_lines_not_rerun\t-\t-\t0$" \
  && record 0 "traced re-link output identical to bin/zephyrd (one-line link.txt)" || record 1 "traced re-link output identical"
[ "$(nunres "$w")" = 0 ] && record 0 "nothing unresolved" || record 1 "nothing unresolved" "$(grep unresolved "$w/logs/link-inventory.tsv")"
[ "$(fsha "$w/src/$B/bin/zephyrd")" = "$binsha" ] && [ -z "$(ls "$w/src/$B/bin" | grep -v '^zephyrd$')" ] && [ -z "$(ls -A "$work/tmp")" ] \
  && record 0 "bin/zephyrd untouched, no traced output left in bin/ or the temporary directory" || record 1 "bin/zephyrd untouched, no traced output left"
! has "$w" "^source-tarball" && [ ! -e "$w/logs/depends-sources" ] && record 0 "no source tarball for a package other than readline" || record 1 "no source tarball for dep"

# re-link: a three-line link.txt (delete and re-create the object archive, then link)
w=$work/mingwform; mkdir "$w"; make_tree "$w"; od=$w/src/$B/src/daemon/CMakeFiles/daemon.dir
( cd "$w/src/$B/src/daemon" && ar cr CMakeFiles/daemon.dir/objects.a CMakeFiles/daemon.dir/main.cpp.o )
{ echo "rm -f CMakeFiles/daemon.dir/objects.a"; echo "ar cr CMakeFiles/daemon.dir/objects.a CMakeFiles/daemon.dir/main.cpp.o"
  echo "g++ -Wl,--whole-archive CMakeFiles/daemon.dir/objects.a -Wl,--no-whole-archive -o ../../bin/zephyrd ../../external/ext/libext.a ../../../../contrib/depends/$H/lib/libdep.a -static-libstdc++ -static-libgcc"; } > "$od/link.txt"
( cd "$w/src/$B/src/daemon" && sh CMakeFiles/daemon.dir/link.txt )
touch -d @1000000000 "$od/objects.a"; arsha=$(fsha "$od/objects.a")
run_li "$w"
has "$w" "^status\trelink_exit\t-\t-\t0$" && has "$w" "^status\trelink_identical\t-\t-\tyes$" && has "$w" "^status\trelink_preparation_lines_not_rerun\t-\t-\t2$" \
  && record 0 "three-line link.txt: only the link line re-run, exit 0, identical" || record 1 "three-line link.txt re-link" "$(grep '^status' "$w/logs/link-inventory.tsv" | head -5)"
[ "$(fsha "$od/objects.a")" = "$arsha" ] && [ "$(stat -c %Y "$od/objects.a")" = 1000000000 ] \
  && record 0 "three-line link.txt: the object archive left as the build made it" || record 1 "object archive left as it was"
has "$w" "^compiled\t[^\t]*/objects\.a\(main\.cpp\.o\)\ttree:src/daemon\t" && [ "$(nunres "$w")" = 0 ] \
  && record 0 "three-line link.txt: the archive's member traced to src/daemon/main.cpp, nothing unresolved" || record 1 "objects.a member traced" "$(grep unresolved "$w/logs/link-inventory.tsv")"

# re-link: a stand-in linker that writes its output's file name into the output (as ld64's UUID
# and the PE export name depend on it) and an import library
w=$work/outname; mkdir "$w"; make_tree "$w"; od=$w/src/$B/src/daemon/CMakeFiles/daemon.dir
cat > "$w/src/$B/src/daemon/fakeld.sh" <<'EOF'
#!/bin/sh
# stand-in linker: real link with g++, then appends the output's base name; --out-implib written
out= implib= args= prev=
for a in "$@"; do
  case "$prev" in -o) out=$a ;; esac
  case "$a" in -Wl,--out-implib,*) implib=${a#-Wl,--out-implib,} ;; *) args="$args $a" ;; esac
  prev=$a
done
g++ $args || exit 1
basename "$out" >> "$out"
[ -z "$implib" ] || echo "implib for $(basename "$out")" > "$implib"
EOF
echo "sh fakeld.sh CMakeFiles/daemon.dir/main.cpp.o -o ../../bin/zephyrd -Wl,--out-implib,libzephyrd.dll.a ../../external/ext/libext.a ../../../../contrib/depends/$H/lib/libdep.a -static-libstdc++ -static-libgcc" > "$od/link.txt"
( cd "$w/src/$B/src/daemon" && sh CMakeFiles/daemon.dir/link.txt )
touch -d @1000000000 "$w/src/$B/src/daemon/libzephyrd.dll.a"; implsha=$(fsha "$w/src/$B/src/daemon/libzephyrd.dll.a")
run_li "$w"
has "$w" "^status\trelink_identical\t-\t-\tyes$" && record 0 "output written under the same file name: a name-dependent output is identical" || record 1 "name-dependent output identical" "$(grep '^status' "$w/logs/link-inventory.tsv" | head -6)"
[ "$(fsha "$w/src/$B/src/daemon/libzephyrd.dll.a")" = "$implsha" ] && [ "$(stat -c %Y "$w/src/$B/src/daemon/libzephyrd.dll.a")" = 1000000000 ] \
  && record 0 "--out-implib moved into the temporary directory; the build's import library untouched" || record 1 "--out-implib redirected"
sed -i 's#^basename "$out" >> "$out"#date +%s%N >> "$out"#' "$w/src/$B/src/daemon/fakeld.sh"
mv "$w/logs" "$w/logs-1"; run_li "$w"
has "$w" "^status\trelink_identical\t-\t-\tno$" && has "$w" "^status\trelink_differences\t-\t-\t[1-9][0-9]* ranges in relink-differences\.txt$" \
  && grep -qE '^[0-9]+\+[0-9]+ ' "$w/logs/relink-differences.txt" && has "$w" "^status\tunresolved\t-\t-\ttraced link exit 0 or output differs" \
  && record 0 "a re-link that differs: not identical, ranges recorded, unresolved" || record 1 "differing re-link recorded" "$(head -3 "$w/logs/relink-differences.txt" 2> /dev/null)"

w=$work/nolicence; mkdir "$w"; make_tree "$w"; rm "$w/src/external/ext/LICENSE"; run_li "$w"
has "$w" "^statement\texternal/ext/ext\.cpp\ttree:external/ext\t[0-9a-f]{64}\tnone$" && has "$w" "^status\tunresolved\ttree:external/ext\t-\tno licence statement in the head of the compiled-in file external/ext/ext\.cpp$" \
  && ! has "$w" "^license\t[^\t]*\ttree:external/ext\t" && record 0 "external source without licence: unresolved, not the top-level LICENSE" || record 1 "external source without licence: unresolved"
w=$work/outside; mkdir "$w"; make_tree "$w"; mkdir "$w/elsewhere"; cp "$w/src/$B/external/ext/libext.a" "$w/elsewhere/libext.a"
sed -i "s#../../external/ext/libext.a#$w/elsewhere/libext.a#" "$w/src/$B/src/daemon/CMakeFiles/daemon.dir/link.txt"
( cd "$w/src/$B/src/daemon" && sh CMakeFiles/daemon.dir/link.txt ); run_li "$w"
has "$w" "^input\t$w/elsewhere/libext\.a\tunknown\t" && has "$w" "^status\tunresolved\t$w/elsewhere/libext.a\t-\towner of a used input not found" \
  && record 0 "input outside every known owner: unknown and unresolved" || record 1 "input outside every known owner: unknown and unresolved"
w=$work/badhash; mkdir "$w"; make_tree "$w"; echo x >> "$w/src/contrib/depends/sources/dep-1.0.tar.gz"; run_li "$w"
has "$w" "^status\tunresolved\tdepends:dep\t-\tsource dep-1.0.tar.gz missing or not the stamped hash" && ! has "$w" "^license\tlicenses/depends/" \
  && record 0 "source tarball not matching its stamp: unresolved, no text taken" || record 1 "source tarball not matching its stamp"
w=$work/noout; mkdir "$w"; make_tree "$w"; sed -i 's# -o ../../bin/zephyrd # -o ../../bin/other #' "$w/src/$B/src/daemon/CMakeFiles/daemon.dir/link.txt"; run_li "$w"
has "$w" "^status\tunresolved\t-\t-\toutput option not found" && record 0 "link.txt without the output option: unresolved" || record 1 "link.txt without the output option"
w=$work/nohdr; mkdir "$w"; make_tree "$w"; rm "$w/src/$B/src/daemon/CMakeFiles/daemon.dir/depend.make"; run_li "$w"
has "$w" "^status\tunresolved\t[^\t]*/main\.cpp\.o\t-\tno dependency record for this linked object" && ! has "$w" "^header\t[^\t]*/external/hdr/" \
  && record 0 "C++ object without a dependency record: unresolved (its headers cannot be established)" || record 1 "object without a dependency record: unresolved"
w=$work/nosource; mkdir "$w"; make_tree "$w"; rm "$w/src/$B/external/ext/CMakeFiles/ext.dir/DependInfo.cmake"; run_li "$w"
has "$w" "^compiled\t[^\t]*/libext\.a\(ext\.cpp\.o\)\tunknown\t[0-9a-f]{64}\tstatus=no-source$" \
  && has "$w" "^status\tunresolved\t[^\t]*/libext\.a\(ext\.cpp\.o\)\t-\tsource of a linked object not established \(no-source\)$" \
  && record 0 "object without a DependInfo source: unresolved, not attributed to the archive's directory" || record 1 "object without a DependInfo source: unresolved"
w=$work/noobject; mkdir "$w"; make_tree "$w"; rm "$w/src/$B/external/ext/CMakeFiles/ext.dir/ext.cpp.o"; run_li "$w"
has "$w" "^status\tunresolved\t[^\t]*/libext\.a\(ext\.cpp\.o\)\t-\tsource of a linked object not established \(no-object\)$" \
  && record 0 "member whose object file is gone: unresolved (no-object)" || record 1 "member whose object file is gone: unresolved"

# statements from the head of compiled-in files (no licence file in external/ext)
w=$work/hdrlic; mkdir "$w"; make_tree "$w"; rm "$w/src/external/ext/LICENSE"; e=$w/src/external/ext
printf '#ifndef EXT_H\r\n#define EXT_H\r\n\r\n// (C) Copyright nobody (synthetic)\r\n// Use is subject to the Synthetic Software\r\n// License, Version 0.\r\n\r\nint ext_h;\r\n#endif\r\n' > "$e/ext.h"
cp "$e/ext.h" "$e/ext2.h"
mkdir -p "$e/sub"; printf '#!/bin/sh\n\n/*\n * Copyright nobody (synthetic)\n * This file is in the Public Domain.\n */\n#include "x"\n// MIT License\nint sub;\n// Apache License, after code\n' > "$e/sub/x.c"
printf '\n# qhasm: int64 rp\n\n# synthetic assembler, placed in the public domain\n# by nobody\n\n.text\n' > "$e/sub/y.s"
printf '// Copyright (c) nobody\n//\n// Redistribution and use in source and binary forms, with or without modification, are\n// permitted (synthetic).\n\nint ext_c;\n' > "$e/ext.cpp"
printf 'int late;\n/* Licensed under the MIT License, but after code */\n' > "$e/late.h"
printf 'external/ext/CMakeFiles/ext.dir/ext.cpp.o: ../../external/ext/ext.h\nexternal/ext/CMakeFiles/ext.dir/ext.cpp.o: ../../external/ext/ext2.h\nexternal/ext/CMakeFiles/ext.dir/ext.cpp.o: ../../external/ext/sub/x.c\nexternal/ext/CMakeFiles/ext.dir/ext.cpp.o: ../../external/ext/sub/y.s\n' \
  >> "$w/src/$B/external/ext/CMakeFiles/ext.dir/depend.make"
run_li "$w"
has "$w" "^statement\texternal/ext/ext\.h\ttree:external/ext\t$(fsha "$e/ext.h")\tlines=4-6 text_sha256=[0-9a-f]{64}$" \
  && has "$w" "^license\tlicenses/tree-header/external/ext/ext\.h\.lines-4-6\.txt\ttree:external/ext\t[0-9a-f]{64}\ttree-header from=source-header file=external/ext/ext\.h lines=4-6 file_sha256=$(fsha "$e/ext.h")$" \
  && record 0 "head statement after preprocessor lines, CRLF file: lines 4-6 recorded with file hash" || record 1 "head statement after preprocessor lines (CRLF)"
cmp -s <(sed -n 4,6p "$e/ext.h") "$w/logs/licenses/tree-header/external/ext/ext.h.lines-4-6.txt" && record 0 "statement copied verbatim (CR kept)" || record 1 "statement copied verbatim"
has "$w" "^statement\texternal/ext/ext2\.h\ttree:external/ext\t" && ! has "$w" "^license\t[^\t]*ext2\.h" \
  && record 0 "identical text of ext2.h: its own statement row, the text once" || record 1 "identical text recorded once"
has "$w" "^statement\texternal/ext/sub/x\.c\ttree:external/ext/sub\t[0-9a-f]{64}\tlines=3-6 " && has "$w" "^statement\texternal/ext/sub/x\.c\t[^\t]*\t[0-9a-f]{64}\tlines=8-8 " \
  && ! has "$w" "x\.c\.lines-10-10" && record 0 "compiled-in file in a subdirectory: /* */ block after #! and // block after #include found, the one after code not" || record 1 "subdirectory file statement"
has "$w" "^statement\texternal/ext/sub/y\.s\ttree:external/ext/sub\t[0-9a-f]{64}\tlines=4-5 " && record 0 "assembler file: # comment block with public domain found (lines 4-5)" || record 1 "assembler statement"
has "$w" "^statement\texternal/ext/ext\.cpp\ttree:external/ext\t[0-9a-f]{64}\tlines=1-4 " && record 0 "BSD wording (redistribution and use) recognised" || record 1 "BSD wording recognised"
! has "$w" "late\.h" && record 0 "a file not compiled in is not read" || record 1 "a file not compiled in is not read"
[ "$(nunres "$w")" = 0 ] && record 0 "statements in every compiled-in file: nothing unresolved" || record 1 "statements: nothing unresolved" "$(grep unresolved "$w/logs/link-inventory.tsv")"
w=$work/hdrnolic; mkdir "$w"; make_tree "$w"; rm "$w/src/external/ext/LICENSE"; e=$w/src/external/ext
printf '/* ext (synthetic), Copyright nobody */\nint ext_h;\n' > "$e/ext.h"
printf 'int ext_c;\n/* Licensed under the MIT License, but not in the head */\n' > "$e/ext.cpp"
echo "external/ext/CMakeFiles/ext.dir/ext.cpp.o: ../../external/ext/ext.h" >> "$w/src/$B/external/ext/CMakeFiles/ext.dir/depend.make"
run_li "$w"
has "$w" "^statement\texternal/ext/ext\.h\ttree:external/ext\t[0-9a-f]{64}\tnone$" && has "$w" "^statement\texternal/ext/ext\.cpp\ttree:external/ext\t[0-9a-f]{64}\tnone$" \
  && has "$w" "^status\tunresolved\ttree:external/ext\t-\tno licence statement in the head of the compiled-in file external/ext/ext\.h$" \
  && has "$w" "^status\tunresolved\ttree:external/ext\t-\tno licence file in external/ext or above it within its boundary, and no licence statement in the head of a compiled-in file" \
  && ! has "$w" "tree-header" && record 0 "no licence statement in the head: each file listed, unresolved" || record 1 "no licence statement in the head: unresolved"
w=$work/filewins; mkdir "$w"; make_tree "$w"
printf '/* Licensed under the MIT License (synthetic) */\nint ext_c;\n' > "$w/src/external/ext/ext.cpp"
run_li "$w"
has "$w" "^license\tlicenses/tree/external/ext/LICENSE\ttree:external/ext\t" && ! has "$w" "tree-header" && ! has "$w" "^statement" \
  && record 0 "licence file present: the file is taken, no statement rows" || record 1 "licence file present: the file is taken"

# readline: its stamped source tarball goes with the release
w=$work/readline; mkdir "$w"; make_tree "$w" readline; run_li "$w"
t=$w/src/contrib/depends/sources/readline-1.0.tar.gz
has "$w" "^source-tarball\tdepends-sources/readline-1\.0\.tar\.gz\tdepends:readline\t$(fsha "$t")\tdepends source=readline-1\.0\.tar\.gz source_sha256=$(fsha "$t") stamp=\.stamp_fetched-readline-readline-1\.0\.tar\.gz\.hash$" \
  && cmp -s "$t" "$w/logs/depends-sources/readline-1.0.tar.gz" && [ "$(nunres "$w")" = 0 ] \
  && record 0 "used depends:readline: its stamped source tarball copied unchanged, source-tarball row" || record 1 "readline source tarball copied" "$(grep -E 'source-tarball|unresolved' "$w/logs/link-inventory.tsv")"
w=$work/readline-bad; mkdir "$w"; make_tree "$w" readline; echo x >> "$w/src/contrib/depends/sources/readline-1.0.tar.gz"; run_li "$w"
! has "$w" "^source-tarball" && has "$w" "^status\tunresolved\tdepends:readline\t-\tsource readline-1.0.tar.gz missing or not the stamped hash" \
  && record 0 "readline tarball not matching its stamp: not copied, unresolved" || record 1 "readline tarball not matching its stamp"

# link-sources.py on crafted inputs: a BSD archive with a padded member; PE timestamp; ranges
w=$work/helpers; mkdir -p "$w/b/x/CMakeFiles/t.dir"
printf 'objectbytes-13' > "$w/b/x/CMakeFiles/t.dir/m.c.o"
dependinfo "$w/b/x/CMakeFiles/t.dir/DependInfo.cmake" C "$w/src/m.c" "$w/b/x/CMakeFiles/t.dir/m.c.o"
python3 -I - "$w/b/x/libt.a" <<'EOF'
import sys
name, body = b"m.c.o", b"objectbytes-13"
nm = name + b"\0" * 3                       # BSD long name, padded
data = nm + body + b"\n\n\n"                # member padded to a multiple of 8 with newlines
hdr = (b"#1/" + str(len(nm)).encode()).ljust(16) + b"0".ljust(12) + b"0".ljust(6) + b"0".ljust(6) + b"100644".ljust(8) \
      + str(len(data)).encode().ljust(10) + b"`\n"
open(sys.argv[1], "wb").write(b"!<arch>\n" + hdr + data)
EOF
printf 'member\t%s\tm.c.o\n' "$w/b/x/libt.a" > "$w/items"
python3 -I "$ls_py" map "$w/src" "$w/b" "$w/items" "$w/out" && grep -qP "^member\t$w/b/x/libt\.a\tm\.c\.o\t[0-9a-f]{64}\t$w/b/x/CMakeFiles/t\.dir/m\.c\.o\t$w/src/m\.c\tmatched$" "$w/out.items.tsv" \
  && record 0 "link-sources.py: BSD archive member with newline padding matched to its object and source" || record 1 "BSD padded member matched" "$(cat "$w/out.items.tsv" 2> /dev/null)"
python3 -I - "$w/pe1" "$w/pe2" <<'EOF'
import struct, sys
for path, ts in ((sys.argv[1], 1794430082), (sys.argv[2], 1794430083)):
    b = bytearray(512); b[0:2] = b"MZ"; struct.pack_into("<I", b, 0x3C, 0x80); b[0x80:0x84] = b"PE\0\0"
    struct.pack_into("<I", b, 0x88, ts); open(path, "wb").write(bytes(b))
EOF
[ "$(python3 -I "$ls_py" pe-timestamp "$w/pe1")" = 1794430082 ] && ! python3 -I "$ls_py" pe-timestamp "$w/items" 2> /dev/null \
  && record 0 "link-sources.py pe-timestamp: COFF TimeDateStamp read; not a PE image: exit 1" || record 1 "pe-timestamp"
[ "$(python3 -I "$ls_py" diff-ranges "$w/pe1" "$w/pe2")" = "136+1 PE COFF TimeDateStamp" ] && record 0 "link-sources.py diff-ranges: range and PE field named" || record 1 "diff-ranges" "$(python3 -I "$ls_py" diff-ranges "$w/pe1" "$w/pe2")"

echo "$passed/$((passed + failed)) cases as expected"
[ "$failed" = 0 ]
