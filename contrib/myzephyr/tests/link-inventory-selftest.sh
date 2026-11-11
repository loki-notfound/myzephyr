#!/bin/bash
# Self-test of link-inventory.sh with a small synthetic tree linked by the host's gcc/GNU ld
# (Linux only; the real inventory runs in the builder images). Nothing here is zephyrd.
#
#   link-inventory-selftest.sh <work-dir>      (<work-dir> must not exist)
#
# The tree has: an own object (top-level LICENSE), an archive from external/ext (its LICENSE),
# a depends package "dep" (cached build tarball, hash-stamped source tarball with COPYING at
# its top and a LICENSE deeper down that must not be taken) with one member pulled and one
# archive nothing is pulled from, a header-only external/hdr named in a dependency file, and
# libstdc++ linked statically (owner by dpkg -S). Checks: owners, used/unused, licence rows
# and their hashes, identical re-link, zero unresolved; then single changes: an external
# archive without licence, an input from outside every known owner, a source tarball whose
# hash differs from its stamp, a link.txt without the output option, no external header.
# Source headers (R13-2): external/ext without a licence file but with licence statements in
# the leading comment blocks of its files: each distinct block copied verbatim, recorded
# "tree-header from=source-header" with file, lines and the file's hash, nothing unresolved;
# leading comments without a licence statement (or one only after code): still unresolved;
# a licence file present: the file is taken, no header row.
set -euo pipefail
export LC_ALL=C
here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
li=$here/../link-inventory.sh
[ $# = 1 ] || { echo "usage: link-inventory-selftest.sh <work-dir>" >&2; exit 2; }
[ ! -e "$1" ] || { echo "$1 exists" >&2; exit 2; }
mkdir -p "$1"; work=$(cd "$1" && pwd)
passed=0 failed=0
record() { if [ "$1" = 0 ]; then passed=$((passed + 1)); echo "ok   $2"; else failed=$((failed + 1)); echo "FAIL $2${3:+ -- $3}"; fi; }
H=x86_64-unknown-linux-gnu

make_tree() {  # make_tree <root>
  local r=$1 s=$1/src b=$1/src/build/release
  mkdir -p "$s/external/ext" "$s/external/hdr/include" "$s/contrib/depends/$H/lib" "$s/contrib/depends/built/$H/dep" \
           "$s/contrib/depends/sources/download-stamps" "$b/src/daemon/CMakeFiles/daemon.dir" "$b/external/ext/CMakeFiles/ext.dir" "$b/bin"
  echo "own licence" > "$s/LICENSE"
  echo "ext licence" > "$s/external/ext/LICENSE"
  echo "hdr licence" > "$s/external/hdr/LICENSE"
  echo 'inline int hdr() { return 3; }' > "$s/external/hdr/include/hdr.hpp"
  ( cd "$r" && printf 'extern "C" int ext(){return 1;}\n' > ext.cpp && g++ -c ext.cpp -o ext.o \
    && ar rcs "$b/external/ext/libext.a" ext.o
    printf 'int dep(void){return 2;}\n' > dep.c && printf 'int unused_dep(){return 9;}\n' > dep2.c \
    && gcc -c dep.c dep2.c && ar rcs "$s/contrib/depends/$H/lib/libdep.a" dep.o dep2.o \
    && printf 'int lonely(){return 7;}\n' > lonely.c && gcc -c lonely.c && ar rcs "$s/contrib/depends/$H/lib/liblonely.a" lonely.o )
  ( cd "$s/contrib/depends/$H" && tar czf "$s/contrib/depends/built/$H/dep/dep-1.0-abc.tar.gz" ./lib/libdep.a ./lib/liblonely.a )
  mkdir -p "$r/dep-1.0/sub"; echo "dep copying" > "$r/dep-1.0/COPYING"; echo "deeper" > "$r/dep-1.0/sub/LICENSE"
  ( cd "$r" && tar czf "$s/contrib/depends/sources/dep-1.0.tar.gz" dep-1.0 )
  echo "$(sha256sum "$s/contrib/depends/sources/dep-1.0.tar.gz" | cut -d' ' -f1)  dep-1.0.tar.gz" \
    > "$s/contrib/depends/sources/download-stamps/.stamp_fetched-dep-dep-1.0.tar.gz.hash"
  printf '#include <iostream>\n#include "hdr.hpp"\nextern "C" int ext(); extern "C" int dep();\nint main(){std::cout<<ext()+dep()+hdr();}\n' > "$r/main.cpp"
  g++ -I"$s/external/hdr/include" -c "$r/main.cpp" -o "$b/src/daemon/CMakeFiles/daemon.dir/main.cpp.o"
  echo "src/daemon/CMakeFiles/daemon.dir/main.cpp.o: ../../external/hdr/include/hdr.hpp" > "$b/src/daemon/CMakeFiles/daemon.dir/depend.make"
  echo "g++ CMakeFiles/daemon.dir/main.cpp.o -o ../../bin/zephyrd ../../external/ext/libext.a ../../../../contrib/depends/$H/lib/libdep.a ../../../../contrib/depends/$H/lib/liblonely.a -static-libstdc++ -static-libgcc" \
    > "$b/src/daemon/CMakeFiles/daemon.dir/link.txt"
  ( cd "$b/src/daemon" && sh CMakeFiles/daemon.dir/link.txt )
}
run_li() { mkdir -p "$1/logs"; bash "$li" "$1/src" build/release zephyrd "$H" "$1/logs" > "$1/li.out" 2>&1; }
has() { grep -qP -- "$2" "$1/logs/link-inventory.tsv"; }
nunres() { grep -c $'^status\tunresolved' "$1/logs/link-inventory.tsv" || true; }

w=$work/good; mkdir "$w"; make_tree "$w"; run_li "$w"
has "$w" "^input\t[^\t]*/main\.cpp\.o\ttree:src/daemon\t[0-9a-f]{64}\tused$" && record 0 "own object owned by tree:src/daemon" || record 1 "own object owned by tree:src/daemon"
has "$w" "^input\t[^\t]*/external/ext/libext\.a\ttree:external/ext\t[0-9a-f]{64}\tused members=1$" && record 0 "external archive used, owner tree:external/ext" || record 1 "external archive used, owner tree:external/ext"
has "$w" "^input\t[^\t]*/lib/libdep\.a\tdepends:dep\t[0-9a-f]{64}\tused members=1$" && record 0 "depends archive used, owner depends:dep (from the cached tarball)" || record 1 "depends archive used, owner depends:dep"
has "$w" "^input\t[^\t]*/lib/liblonely\.a\tdepends:dep\t[0-9a-f]{64}\tunused$" && record 0 "archive with nothing pulled is unused" || record 1 "archive with nothing pulled is unused"
has "$w" "^input\t[^\t]*/libstdc\+\+\.a\tdeb:libstdc\+\+-[0-9]+-dev\t" && record 0 "static libstdc++ owned by its Debian package" || record 1 "static libstdc++ owned by its Debian package"
has "$w" "^license\tlicenses/tree/LICENSE\ttree:src/daemon\t" && record 0 "own code takes the top-level LICENSE" || record 1 "own code takes the top-level LICENSE"
has "$w" "^license\tlicenses/tree/external/ext/LICENSE\ttree:external/ext\t" && record 0 "external archive takes its LICENSE" || record 1 "external archive takes its LICENSE"
has "$w" "^header\t[^\t]*/external/hdr/include\ttree:external/hdr\t" && has "$w" "^license\tlicenses/tree/external/hdr/LICENSE\t" \
  && record 0 "header-only external/hdr found in the dependency file, its LICENSE taken" || record 1 "header-only external/hdr found, LICENSE taken"
has "$w" "^license\tlicenses/depends/dep/COPYING\tdepends:dep\t[0-9a-f]{64}\tdepends source=dep-1.0.tar.gz source_sha256=[0-9a-f]{64} member=dep-1.0/COPYING$" \
  && ! has "$w" "member=dep-1.0/sub/LICENSE" && record 0 "depends licence from the top of the stamped source tarball only" || record 1 "depends licence from the top of the stamped source tarball only"
has "$w" "^license\tlicenses/deb/libstdc\+\+-[0-9]+-dev/copyright\tdeb:libstdc\+\+-[0-9]+-dev\t[0-9a-f]{64}\tdeb package=libstdc\+\+-[0-9]+-dev version=\S+ file=" \
  && record 0 "Debian copyright file copied with package version" || record 1 "Debian copyright file copied with package version"
ok=0; while IFS=$'\t' read -r k p o h d; do
  [ "$k" = license ] || continue
  [ "$(sha256sum "$w/logs/$p" | cut -d' ' -f1)" = "$h" ] || ok=1
done < "$w/logs/link-inventory.tsv"; record $ok "every licence row's hash matches the copied text"
has "$w" "^status\trelink_identical\t-\t-\tyes$" && record 0 "traced re-link output identical to bin/zephyrd" || record 1 "traced re-link output identical"
[ "$(nunres "$w")" = 0 ] && record 0 "nothing unresolved" || record 1 "nothing unresolved" "$(grep unresolved "$w/logs/link-inventory.tsv")"
[ ! -e "$w/src/build/release/bin/zephyrd.trace-link" ] && record 0 "traced output removed" || record 1 "traced output removed"

w=$work/nolicence; mkdir "$w"; make_tree "$w"; rm "$w/src/external/ext/LICENSE"; run_li "$w"
has "$w" "^status\tunresolved\ttree:external/ext\t-\tno licence file" && record 0 "external archive without licence: unresolved, not the top-level LICENSE" || record 1 "external archive without licence: unresolved"
w=$work/outside; mkdir "$w"; make_tree "$w"; mkdir "$w/elsewhere"; cp "$w/src/build/release/external/ext/libext.a" "$w/elsewhere/libext.a"
sed -i "s#../../external/ext/libext.a#$w/elsewhere/libext.a#" "$w/src/build/release/src/daemon/CMakeFiles/daemon.dir/link.txt"
( cd "$w/src/build/release/src/daemon" && sh CMakeFiles/daemon.dir/link.txt ); run_li "$w"
has "$w" "^input\t$w/elsewhere/libext\.a\tunknown\t" && has "$w" "^status\tunresolved\t$w/elsewhere/libext.a\t-\towner of a used input not found" \
  && record 0 "input outside every known owner: unknown and unresolved" || record 1 "input outside every known owner: unknown and unresolved"
w=$work/badhash; mkdir "$w"; make_tree "$w"; echo x >> "$w/src/contrib/depends/sources/dep-1.0.tar.gz"; run_li "$w"
has "$w" "^status\tunresolved\tdepends:dep\t-\tsource dep-1.0.tar.gz missing or not the stamped hash" && ! has "$w" "^license\tlicenses/depends/" \
  && record 0 "source tarball not matching its stamp: unresolved, no text taken" || record 1 "source tarball not matching its stamp"
w=$work/noout; mkdir "$w"; make_tree "$w"; sed -i 's# -o ../../bin/zephyrd # -o ../../bin/other #' "$w/src/build/release/src/daemon/CMakeFiles/daemon.dir/link.txt"; run_li "$w"
has "$w" "^status\tunresolved\t-\t-\toutput option not found" && record 0 "link.txt without the output option: unresolved" || record 1 "link.txt without the output option"
w=$work/nohdr; mkdir "$w"; make_tree "$w"; rm "$w/src/build/release/src/daemon/CMakeFiles/daemon.dir/depend.make"; run_li "$w"
has "$w" "^status\tunresolved\t-\t-\tno external/ header found" && record 0 "no external header in the dependency files: unresolved" || record 1 "no external header: unresolved"

w=$work/hdrlic; mkdir "$w"; make_tree "$w"; rm "$w/src/external/ext/LICENSE"
printf '/*\n * ext (synthetic)\n * Licensed under the MIT License; see the statement below.\n */\nint ext_h;\n' > "$w/src/external/ext/ext.h"
cp "$w/src/external/ext/ext.h" "$w/src/external/ext/ext2.h"
printf '#!/bin/sh\n\n// Copyright nobody (synthetic)\n// This file is in the Public Domain.\nint ext_c;\n' > "$w/src/external/ext/ext.c"
run_li "$w"
has "$w" "^license\tlicenses/tree-header/external/ext/ext\.h\.lines-1-4\.txt\ttree:external/ext\t[0-9a-f]{64}\ttree-header from=source-header file=external/ext/ext\.h lines=1-4 file_sha256=$(sha256sum "$w/src/external/ext/ext.h" | cut -d' ' -f1)$" \
  && record 0 "source header: block of ext.h recorded with file, lines and file hash" || record 1 "source header: block of ext.h recorded with file, lines and file hash"
has "$w" "^license\tlicenses/tree-header/external/ext/ext\.c\.lines-3-4\.txt\ttree:external/ext\t" \
  && record 0 "source header: // block after a #! line and a blank line found (lines 3-4)" || record 1 "source header: // block after #! and blank line"
! has "$w" "ext2\.h" && record 0 "source header: identical block of ext2.h not recorded twice" || record 1 "source header: identical block of ext2.h not recorded twice"
cmp -s <(sed -n 1,4p "$w/src/external/ext/ext.h") "$w/logs/licenses/tree-header/external/ext/ext.h.lines-1-4.txt" \
  && record 0 "source header: text copied verbatim" || record 1 "source header: text copied verbatim"
[ "$(nunres "$w")" = 0 ] && record 0 "source header: nothing unresolved" || record 1 "source header: nothing unresolved" "$(grep unresolved "$w/logs/link-inventory.tsv")"
w=$work/hdrnolic; mkdir "$w"; make_tree "$w"; rm "$w/src/external/ext/LICENSE"
printf '/* ext (synthetic), Copyright nobody */\nint ext_h;\n' > "$w/src/external/ext/ext.h"
printf 'int ext_c;\n/* Licensed under the MIT License, but not in the leading block */\n' > "$w/src/external/ext/ext.c"
run_li "$w"
has "$w" "^status\tunresolved\ttree:external/ext\t-\tno licence file in external/ext or above it within its boundary, and no licence statement in a source header" \
  && ! has "$w" "tree-header" && record 0 "no licence statement in a leading comment block: unresolved" || record 1 "no licence statement in a leading comment block: unresolved"
w=$work/filewins; mkdir "$w"; make_tree "$w"
printf '/* Licensed under the MIT License (synthetic) */\nint ext_h;\n' > "$w/src/external/ext/ext.h"
run_li "$w"
has "$w" "^license\tlicenses/tree/external/ext/LICENSE\ttree:external/ext\t" && ! has "$w" "tree-header" \
  && record 0 "licence file present: the file is taken, no source-header row" || record 1 "licence file present: the file is taken, no source-header row"

echo "$passed/$((passed + failed)) cases as expected"
[ "$failed" = 0 ]
