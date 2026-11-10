#!/bin/bash
# Runtime-requirement checks for a Linux x86_64 or Linux AArch64 zephyrd.
#
#   check-elf.sh [--arch x86_64|aarch64] <zephyrd> <report-file>
#
# The caller names the architecture (default x86_64); the binary never selects its own
# expectations. Fails (exit 1) unless all of these hold:
#   - ELF64 position-independent executable of that machine with its interpreter:
#     x86_64  Advanced Micro Devices X86-64, /lib64/ld-linux-x86-64.so.2
#     aarch64 AArch64, /lib/ld-linux-aarch64.so.1
#   - no DT_RPATH and no DT_RUNPATH entry at all (an empty component would search the
#     current directory);
#   - DT_NEEDED only from the set upstream v2.3.0's Linux daemon uses:
#     libc.so.6, libm.so.6, libpthread.so.0 and that architecture's loader,
#     ld-linux-x86-64.so.2 or ld-linux-aarch64.so.1 (no C++ runtime or third-party
#     shared library); upstream's AArch64 daemon uses the same set;
#   - no GLIBCXX_/CXXABI_/GCC_ symbol version needs;
#   - the highest GLIBC_ symbol version needed is at most MAX_GLIBC (default 2.29).
# The report (key=value) lists the measured values and the symbols needing more
# than GLIBC_2.17, whether or not the checks pass.
set -euo pipefail
export LC_ALL=C

arch=x86_64
if [ "${1:-}" = --arch ]; then arch=${2:-}; shift 2 || true; fi
case "$arch" in
  x86_64) machine='Advanced Micro Devices X86-64' machine_name=x86-64
          want_interp=/lib64/ld-linux-x86-64.so.2 loader=ld-linux-x86-64.so.2 ;;
  aarch64) machine=AArch64 machine_name=AArch64
           want_interp=/lib/ld-linux-aarch64.so.1 loader=ld-linux-aarch64.so.1 ;;
  *) echo "usage: $0 [--arch x86_64|aarch64] <zephyrd> <report-file>" >&2; exit 2 ;;
esac
if [ $# -ne 2 ]; then echo "usage: $0 [--arch x86_64|aarch64] <zephyrd> <report-file>" >&2; exit 2; fi
bin=$1 report=$2
max_allowed=${MAX_GLIBC:-2.29}
test -f "$bin" || { echo "$bin not found" >&2; exit 2; }

fail=0
bad() { echo "check-elf: $*" >&2; fail=1; }

header=$(readelf -hW "$bin")
grep -q 'Class:[[:space:]]*ELF64' <<< "$header" || bad "not ELF64"
grep -qx "[[:space:]]*Machine:[[:space:]]*$machine" <<< "$header" || bad "not $machine_name"
grep -q 'Type:[[:space:]]*DYN' <<< "$header" || bad "not a position-independent executable"
interp=$(readelf -lW "$bin" | sed -n 's/.*\[Requesting program interpreter: \(.*\)\]/\1/p')
[ "$interp" = "$want_interp" ] || bad "interpreter '$interp'"

dyn=$(readelf -dW "$bin")
rpath=$(grep -E '\((RPATH|RUNPATH)\)' <<< "$dyn" | sed 's/^ *//; s/  */ /g' || true)
[ -z "$rpath" ] || bad "has RPATH/RUNPATH: $rpath"
needed=$(sed -n 's/.*(NEEDED).*\[\(.*\)\]/\1/p' <<< "$dyn" | sort | tr '\n' ' ')
for lib in $needed; do
  case "$lib" in libc.so.6|libm.so.6|libpthread.so.0|"$loader") ;;
    *) bad "unexpected NEEDED $lib" ;; esac
done

vers=$(readelf -VW "$bin")
cxx=$(grep -oE '(GLIBCXX|CXXABI|GCC)_[0-9.]+' <<< "$vers" | sort -uV | tr '\n' ' ' || true)
[ -z "$cxx" ] || bad "C++ runtime/libgcc version needs: $cxx"
max_glibc=$(grep -oE 'GLIBC_[0-9.]+' <<< "$vers" | sed 's/GLIBC_//' | sort -uV | tail -n 1)
[ -n "$max_glibc" ] || bad "no GLIBC version needs found"
highest=$(printf '%s\n%s\n' "$max_glibc" "$max_allowed" | sort -V | tail -n 1)
[ "$highest" = "$max_allowed" ] || bad "needs GLIBC_$max_glibc, more than GLIBC_$max_allowed"
newer=$(objdump -T "$bin" | awk '{for (i = 1; i <= NF; i++) if ($i ~ /^\(?GLIBC_[0-9.]+\)?$/) {v = $i; gsub(/[()]/, "", v); print v, $NF}}' \
  | awk '{split($1, a, "_"); split(a[2], b, "."); if (b[1] > 2 || (b[1] == 2 && b[2] > 17)) print $1 ":" $2}' | sort -uV | tr '\n' ' ')

{
  echo "elf_file=$(file -b "$bin")"
  echo "elf_size=$(stat -c %s "$bin")"
  echo "elf_sha256=$(sha256sum "$bin" | cut -d' ' -f1)"
  echo "elf_build_id=$(readelf -nW "$bin" | sed -n 's/.*Build ID: //p')"
  echo "elf_interpreter=$interp"
  echo "elf_needed=${needed% }"
  echo "elf_rpath_runpath=${rpath:-none}"
  echo "elf_max_glibc=GLIBC_$max_glibc"
  echo "elf_max_glibc_allowed=GLIBC_$max_allowed"
  echo "elf_cxx_version_needs=${cxx:-none}"
  echo "elf_symbols_above_glibc_2_17=${newer% }"
  echo "elf_checks=$([ "$fail" = 0 ] && echo passed || echo failed)"
} > "$report"
cat "$report"
exit "$fail"
