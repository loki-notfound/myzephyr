#!/usr/bin/env python3
"""Static runtime-requirement checks for a macOS zephyrd (Mach-O). Nothing is executed.

  check-macho.py [--arch x86_64|arm64] <zephyrd> <report-file>

--arch defaults to x86_64 (the macOS x86_64 build; its report is unchanged by --arch).
Fails (exit 1) unless all of these hold:
  - a thin 64-bit Mach-O (magic feedfacf, no fat header), CPU type x86_64 (--arch x86_64) or
    arm64 (--arch arm64), MH_EXECUTE, MH_PIE;
  - the minimum macOS version is exactly 10.13.0 (LC_VERSION_MIN_MACOSX, or LC_BUILD_VERSION
    for platform macOS; exactly one of them): upstream v2.3.0's x86_64 daemon has the same
    value, and depends' OSX_MIN_VERSION gives the arm64 build the same (measured on a local
    build of 8107755c0; Apple Silicon Macs start at macOS 11);
  - the dynamic linker is /usr/lib/dyld;
  - every linked library is an OS one from this set: the frameworks Foundation, AppKit, IOKit,
    Kerberos, ApplicationServices, CoreFoundation (as
    /System/Library/Frameworks/<Name>.framework/Versions/<letter>/<Name>), and
    /usr/lib/libc++.1.dylib, /usr/lib/libSystem.B.dylib; libSystem must be among them;
  - no LC_RPATH;
  - arm64 only (Apple Silicon does not run an unsigned arm64 binary): an LC_CODE_SIGNATURE
    whose data is the last thing in the file and holds an embedded-signature SuperBlob with
    exactly one CodeDirectory, ad-hoc (flag adhoc, no team identifier, no or an empty CMS
    blob), SHA-256 page hashes over 4096-byte pages, a code limit equal to the signature's
    offset, and every page hash equal to the hash of the file's page.
The report (key=value) lists the measured values whether or not the checks pass.
"""
import hashlib
import re
import struct
import sys

CPU_X86_64, CPU_ARM64 = 0x01000007, 0x0100000C
MH_EXECUTE, MH_PIE = 2, 0x200000
LC_LOAD_DYLIB, LC_LOAD_WEAK_DYLIB, LC_REEXPORT_DYLIB, LC_LAZY_LOAD_DYLIB = 0xC, 0x80000018, 0x8000001F, 0x20
LC_LOAD_UPWARD_DYLIB = 0x80000023
DYLIB_CMDS = {LC_LOAD_DYLIB, LC_LOAD_WEAK_DYLIB, LC_REEXPORT_DYLIB, LC_LAZY_LOAD_DYLIB, LC_LOAD_UPWARD_DYLIB}
LC_ID_DYLINKER, LC_LOAD_DYLINKER = 0xF, 0xE
LC_VERSION_MIN_MACOSX, LC_BUILD_VERSION = 0x24, 0x32
LC_RPATH, LC_CODE_SIGNATURE, LC_UUID = 0x8000001C, 0x1D, 0x1B
PLATFORM_MACOS = 1
# architecture: (CPU type, minimum macOS, ad-hoc code signature required)
ARCHES = {"x86_64": (CPU_X86_64, "10.13.0", False), "arm64": (CPU_ARM64, "10.13.0", True)}
CSMAGIC_EMBEDDED_SIGNATURE, CSMAGIC_CODEDIRECTORY = 0xFADE0CC0, 0xFADE0C02
CSSLOT_CODEDIRECTORY, CSSLOT_SIGNATURESLOT = 0, 0x10000
CS_ADHOC, CS_LINKER_SIGNED = 0x2, 0x20000
CS_HASHTYPE_SHA256 = 2
FRAMEWORKS = {"Foundation", "AppKit", "IOKit", "Kerberos", "ApplicationServices", "CoreFoundation"}
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


def code_signature(d, off, size):
    """Decode and check an embedded ad-hoc signature at d[off:off+size]; returns (kind, pages, problems)."""
    probs = []
    if off + size != len(d) or size < 12:
        return "invalid", "0/0", [f"code signature at {off}+{size} is not the end of the file ({len(d)})"]
    magic, length, count = struct.unpack_from(">III", d, off)
    if magic != CSMAGIC_EMBEDDED_SIGNATURE or length > size or 12 + 8 * count > length:
        return "invalid", "0/0", [f"code signature SuperBlob magic {magic:#x} length {length} count {count} invalid"]
    cds, cms = [], []
    for k in range(count):
        typ, boff = struct.unpack_from(">II", d, off + 12 + 8 * k)
        if boff + 8 > length:
            return "invalid", "0/0", [f"code signature blob {k} outside the SuperBlob"]
        bm, blen = struct.unpack_from(">II", d, off + boff)
        if boff + blen > length:
            return "invalid", "0/0", [f"code signature blob {k} outside the SuperBlob"]
        if typ == CSSLOT_CODEDIRECTORY or bm == CSMAGIC_CODEDIRECTORY:
            cds.append((typ, off + boff, bm, blen))
        elif typ == CSSLOT_SIGNATURESLOT:
            cms.append(blen - 8)
    if len(cds) != 1 or cds[0][0] != CSSLOT_CODEDIRECTORY or cds[0][2] != CSMAGIC_CODEDIRECTORY:
        return "invalid", "0/0", [f"{len(cds)} CodeDirectory blobs, expected exactly one in slot 0"]
    b, blen = cds[0][1], cds[0][3]
    version, flags, hashoff, identoff, nspecial, ncode, codelimit, hashsize, hashtype, _plat, pagesize = \
        struct.unpack_from(">IIIIIIIBBBB", d, b + 8)
    team = 0
    if version >= 0x20200:
        team = struct.unpack_from(">I", d, b + 48)[0]
    kinds = ["adhoc" if flags & CS_ADHOC else "not-adhoc"] + (["linker-signed"] if flags & CS_LINKER_SIGNED else [])
    if team or any(n > 0 for n in cms):
        kinds.append("identity")
    kind = ",".join(kinds)
    if not flags & CS_ADHOC or team or any(n > 0 for n in cms):
        probs.append(f"code signature is not ad-hoc ({kind})")
    if hashtype != CS_HASHTYPE_SHA256 or hashsize != 32 or pagesize != 12:
        probs.append(f"CodeDirectory hash type {hashtype}, size {hashsize}, page 2^{pagesize}; expected SHA-256 over 4096-byte pages")
        return kind, "0/0", probs
    if codelimit != off:
        probs.append(f"CodeDirectory code limit {codelimit} is not the signature offset {off}")
    if ncode != (codelimit + 4095) // 4096 or hashoff + ncode * 32 > blen:
        probs.append(f"CodeDirectory has {ncode} code slots for a code limit of {codelimit}")
        return kind, "0/0", probs
    good = sum(1 for s in range(ncode)
               if hashlib.sha256(d[s * 4096:min((s + 1) * 4096, codelimit)]).digest() == d[b + hashoff + 32 * s:b + hashoff + 32 * (s + 1)])
    if good != ncode:
        probs.append(f"code signature page hashes: {ncode - good} of {ncode} do not match the file")
    return kind, f"{good}/{ncode}", probs


def inspect(d, arch="x86_64"):
    cpu_want, min_os, need_sig = ARCHES[arch]
    r = {"problems": [], "dylibs": [], "rpaths": [], "min_os": [], "dylinker": [], "code_signature": False, "uuid": None,
         "signature": None}
    if len(d) < 32:
        r["problems"].append("file too short for a Mach-O header")
        return r
    magic = d[:4]
    r["magic"] = magic.hex()
    if magic in (b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca", b"\xca\xfe\xba\xbf", b"\xbf\xba\xfe\xca"):
        r["problems"].append(f"universal (fat) binary, expected a thin {arch} Mach-O")
        return r
    if struct.unpack_from("<I", d, 0)[0] != 0xFEEDFACF:
        r["problems"].append(f"magic {magic.hex()}, expected cffaedfe (64-bit little-endian Mach-O)")
        return r
    cpu, sub, ft, ncmds, sizeofcmds, flags, _ = struct.unpack_from("<iiIIIII", d, 4)
    r.update(cputype=f"{cpu & 0xffffffff:#x}", filetype=ft, flags=f"{flags:#x}", ncmds=ncmds)
    if cpu & 0xffffffff != cpu_want:
        r["problems"].append(f"cputype {cpu & 0xffffffff:#x}, expected {cpu_want:#x} ({arch})")
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
            r["signature"] = struct.unpack_from("<II", d, o + 8)
        elif cmd == LC_UUID:
            r["uuid"] = d[o + 8:o + 24].hex()
        o += cs
    if len(r["min_os"]) != 1:
        r["problems"].append(f"{len(r['min_os'])} minimum-OS load commands, expected exactly one")
    elif r["min_os"][0][1] != min_os:
        r["problems"].append(f"minimum macOS {r['min_os'][0][1]} ({r['min_os'][0][0]}), expected {min_os}")
    if r["dylinker"] != ["/usr/lib/dyld"]:
        r["problems"].append(f"dynamic linker {r['dylinker']}, expected ['/usr/lib/dyld']")
    for lib in r["dylibs"]:
        if not allowed_dylib(lib):
            r["problems"].append(f"library outside the allowed OS set: {lib}")
    if "/usr/lib/libSystem.B.dylib" not in r["dylibs"]:
        r["problems"].append("libSystem.B.dylib not linked")
    if r["rpaths"]:
        r["problems"].append(f"LC_RPATH present: {r['rpaths']}")
    if need_sig:
        if r["signature"] is None:
            r["sig_kind"], r["sig_pages"] = "none", "0/0"
            r["problems"].append(f"no code signature (LC_CODE_SIGNATURE); macOS does not run an unsigned {arch} binary")
        else:
            r["sig_kind"], r["sig_pages"], probs = code_signature(d, *r["signature"])
            r["problems"] += probs
    return r


def main():
    args = sys.argv[1:]
    arch = "x86_64"
    if args[:1] == ["--arch"]:
        arch, args = (args[1] if len(args) > 1 else ""), args[2:]
    if arch not in ARCHES or len(args) != 2:
        sys.exit("usage: check-macho.py [--arch x86_64|arm64] <zephyrd> <report-file>")
    path, report = args
    d = open(path, "rb").read()
    r = inspect(d, arch)
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
    ]
    if ARCHES[arch][2]:
        lines += [f"macho_code_signature_kind={r.get('sig_kind', 'none')}",
                  f"macho_code_signature_pages={r.get('sig_pages', '0/0')}"]
    lines.append(f"macho_checks={'failed' if r['problems'] else 'passed'}")
    with open(report, "w") as f:
        f.write("\n".join(lines) + "\n")
    print("\n".join(lines))
    for p in r["problems"]:
        print(f"check-macho: {p}", file=sys.stderr)
    sys.exit(1 if r["problems"] else 0)


if __name__ == "__main__":
    main()
