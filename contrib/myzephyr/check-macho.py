#!/usr/bin/env python3
"""Static runtime-requirement checks for a macOS x86_64 zephyrd (Mach-O). Nothing is executed.

  check-macho.py <zephyrd> <report-file>

Fails (exit 1) unless all of these hold (upstream v2.3.0's macOS daemon has the same values):
  - a thin 64-bit Mach-O (magic feedfacf, no fat header), CPU type x86_64, MH_EXECUTE, MH_PIE;
  - the minimum macOS version is exactly 10.13.0 (LC_VERSION_MIN_MACOSX, or LC_BUILD_VERSION
    for platform macOS; exactly one of them);
  - the dynamic linker is /usr/lib/dyld;
  - every linked library is an OS one from this set: the frameworks Foundation, AppKit, IOKit,
    Security, Kerberos, ApplicationServices, CoreFoundation (as
    /System/Library/Frameworks/<Name>.framework/Versions/<letter>/<Name>), and
    /usr/lib/libc++.1.dylib, /usr/lib/libSystem.B.dylib; libSystem must be among them;
  - no LC_RPATH.
The report (key=value) lists the measured values whether or not the checks pass.
"""
import hashlib
import re
import struct
import sys

CPU_X86_64 = 0x01000007
MH_EXECUTE, MH_PIE = 2, 0x200000
LC_LOAD_DYLIB, LC_LOAD_WEAK_DYLIB, LC_REEXPORT_DYLIB, LC_LAZY_LOAD_DYLIB = 0xC, 0x80000018, 0x8000001F, 0x20
LC_LOAD_UPWARD_DYLIB = 0x80000023
DYLIB_CMDS = {LC_LOAD_DYLIB, LC_LOAD_WEAK_DYLIB, LC_REEXPORT_DYLIB, LC_LAZY_LOAD_DYLIB, LC_LOAD_UPWARD_DYLIB}
LC_ID_DYLINKER, LC_LOAD_DYLINKER = 0xF, 0xE
LC_VERSION_MIN_MACOSX, LC_BUILD_VERSION = 0x24, 0x32
LC_RPATH, LC_CODE_SIGNATURE, LC_UUID = 0x8000001C, 0x1D, 0x1B
PLATFORM_MACOS = 1
MIN_OS = "10.13.0"
FRAMEWORKS = {"Foundation", "AppKit", "IOKit", "Security", "Kerberos", "ApplicationServices",
              "CoreFoundation"}
FRAMEWORK_RE = re.compile(r"^/System/Library/Frameworks/([A-Za-z]+)\.framework/Versions/[A-Z]/\1$")
USR_LIB = {"/usr/lib/libc++.1.dylib", "/usr/lib/libSystem.B.dylib"}


def ver(x):
    return f"{x >> 16}.{(x >> 8) & 0xff}.{x & 0xff}"


def cstr(d, start, end):
    return d[start:end].split(b"\0")[0].decode("utf-8", "replace")


def allowed_dylib(path):
    if path in USR_LIB:
        return True
    m = FRAMEWORK_RE.match(path)
    return bool(m) and m.group(1) in FRAMEWORKS


def inspect(d):
    r = {"problems": [], "dylibs": [], "rpaths": [], "min_os": [], "dylinker": [], "code_signature": False, "uuid": None}
    if len(d) < 32:
        r["problems"].append("file too short for a Mach-O header")
        return r
    magic = d[:4]
    r["magic"] = magic.hex()
    if magic in (b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca", b"\xca\xfe\xba\xbf", b"\xbf\xba\xfe\xca"):
        r["problems"].append("universal (fat) binary, expected a thin x86_64 Mach-O")
        return r
    if struct.unpack_from("<I", d, 0)[0] != 0xFEEDFACF:
        r["problems"].append(f"magic {magic.hex()}, expected cffaedfe (64-bit little-endian Mach-O)")
        return r
    cpu, sub, ft, ncmds, sizeofcmds, flags, _ = struct.unpack_from("<iiIIIII", d, 4)
    r.update(cputype=f"{cpu & 0xffffffff:#x}", filetype=ft, flags=f"{flags:#x}", ncmds=ncmds)
    if cpu & 0xffffffff != CPU_X86_64:
        r["problems"].append(f"cputype {cpu & 0xffffffff:#x}, expected {CPU_X86_64:#x} (x86_64)")
    if ft != MH_EXECUTE:
        r["problems"].append(f"filetype {ft}, expected {MH_EXECUTE} (MH_EXECUTE)")
    if not flags & MH_PIE:
        r["problems"].append("MH_PIE not set")
    o = 32
    end = 32 + sizeofcmds
    if end > len(d):
        r["problems"].append("load commands extend beyond the file")
        return r
    for _ in range(ncmds):
        if o + 8 > end:
            r["problems"].append("truncated load command")
            return r
        cmd, cs = struct.unpack_from("<II", d, o)
        if cs < 8 or o + cs > end:
            r["problems"].append(f"load command {cmd:#x} has an invalid size {cs}")
            return r
        if cmd in DYLIB_CMDS:
            r["dylibs"].append(cstr(d, o + struct.unpack_from("<I", d, o + 8)[0], o + cs))
        elif cmd == LC_LOAD_DYLINKER:
            r["dylinker"].append(cstr(d, o + struct.unpack_from("<I", d, o + 8)[0], o + cs))
        elif cmd == LC_VERSION_MIN_MACOSX:
            v, sdk = struct.unpack_from("<II", d, o + 8)
            r["min_os"].append(("LC_VERSION_MIN_MACOSX", ver(v), ver(sdk)))
        elif cmd == LC_BUILD_VERSION:
            plat, minos, sdk = struct.unpack_from("<III", d, o + 8)
            r["min_os"].append((f"LC_BUILD_VERSION platform {plat}", ver(minos) if plat == PLATFORM_MACOS else f"not-macos:{ver(minos)}", ver(sdk)))
        elif cmd == LC_RPATH:
            r["rpaths"].append(cstr(d, o + struct.unpack_from("<I", d, o + 8)[0], o + cs))
        elif cmd == LC_CODE_SIGNATURE:
            r["code_signature"] = True
        elif cmd == LC_UUID:
            r["uuid"] = d[o + 8:o + 24].hex()
        o += cs
    if len(r["min_os"]) != 1:
        r["problems"].append(f"{len(r['min_os'])} minimum-OS load commands, expected exactly one")
    elif r["min_os"][0][1] != MIN_OS:
        r["problems"].append(f"minimum macOS {r['min_os'][0][1]} ({r['min_os'][0][0]}), expected {MIN_OS}")
    if r["dylinker"] != ["/usr/lib/dyld"]:
        r["problems"].append(f"dynamic linker {r['dylinker']}, expected ['/usr/lib/dyld']")
    for lib in r["dylibs"]:
        if not allowed_dylib(lib):
            r["problems"].append(f"library outside the allowed OS set: {lib}")
    if "/usr/lib/libSystem.B.dylib" not in r["dylibs"]:
        r["problems"].append("libSystem.B.dylib not linked")
    if r["rpaths"]:
        r["problems"].append(f"LC_RPATH present: {r['rpaths']}")
    return r


def main():
    if len(sys.argv) != 3:
        sys.exit("usage: check-macho.py <zephyrd> <report-file>")
    path, report = sys.argv[1:]
    d = open(path, "rb").read()
    r = inspect(d)
    lines = [
        f"macho_size={len(d)}",
        f"macho_sha256={hashlib.sha256(d).hexdigest()}",
        f"macho_magic={r.get('magic')}",
        f"macho_cputype={r.get('cputype')}",
        f"macho_filetype={r.get('filetype')}",
        f"macho_flags={r.get('flags')}",
        f"macho_min_os={' '.join(f'{c}:{v}' for c, v, _ in r['min_os']) or 'none'}",
        f"macho_sdk={' '.join(s for _, _, s in r['min_os']) or 'none'}",
        f"macho_dylinker={' '.join(r['dylinker']) or 'none'}",
        f"macho_dylibs={' '.join(r['dylibs'])}",
        f"macho_rpath={' '.join(r['rpaths']) or 'none'}",
        f"macho_code_signature={'present' if r['code_signature'] else 'none'}",
        f"macho_uuid={r['uuid']}",
        f"macho_checks={'failed' if r['problems'] else 'passed'}",
    ]
    with open(report, "w") as f:
        f.write("\n".join(lines) + "\n")
    print("\n".join(lines))
    for p in r["problems"]:
        print(f"check-macho: {p}", file=sys.stderr)
    sys.exit(1 if r["problems"] else 0)


if __name__ == "__main__":
    main()
