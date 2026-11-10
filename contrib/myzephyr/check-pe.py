#!/usr/bin/env python3
"""Static runtime-requirement checks for a Windows x86_64 zephyrd.exe (PE). Nothing is executed.

  check-pe.py <zephyrd.exe> <report-file>

Fails (exit 1) unless all of these hold:
  - PE32+ (optional header magic 0x20b), machine x86-64 (0x8664), an executable image,
    subsystem Windows console (3);
  - every imported DLL (normal and delay-load imports, names compared case-insensitively)
    is a Windows system DLL from the set upstream v2.3.0's daemon imports: ADVAPI32, bcrypt,
    CRYPT32, IPHLPAPI, KERNEL32, msvcrt, MSWSOCK, SHELL32, USER32, WS2_32; in particular no
    MinGW runtime DLL (libstdc++, libgcc_s, libwinpthread) and no third-party DLL;
  - KERNEL32 is imported.
The report (key=value) lists the measured values whether or not the checks pass.
"""
import hashlib
import struct
import sys

ALLOWED = {"advapi32.dll", "bcrypt.dll", "crypt32.dll", "iphlpapi.dll", "kernel32.dll", "msvcrt.dll",
           "mswsock.dll", "shell32.dll", "user32.dll", "ws2_32.dll"}
RUNTIME_DLLS = ("libstdc++", "libgcc", "libwinpthread")


def inspect(d):
    r = {"problems": [], "imports": [], "delay_imports": []}

    def u(fmt, off):
        if off < 0 or off + struct.calcsize(fmt) > len(d):
            raise ValueError(f"read beyond the file at {off:#x}")
        return struct.unpack_from(fmt, d, off)

    try:
        if d[:2] != b"MZ":
            r["problems"].append("no MZ header")
            return r
        pe = u("<I", 0x3C)[0]
        if d[pe:pe + 4] != b"PE\0\0":
            r["problems"].append("no PE signature")
            return r
        machine, nsect, timestamp, _, _, opt_size, chars = u("<HHIIIHH", pe + 4)
        opt = pe + 24
        magic = u("<H", opt)[0]
        r.update(machine=f"{machine:#x}", sections=nsect, timestamp=timestamp, characteristics=f"{chars:#x}",
                 magic=f"{magic:#x}")
        if machine != 0x8664:
            r["problems"].append(f"machine {machine:#x}, expected 0x8664 (x86-64)")
        if magic != 0x20B:
            r["problems"].append(f"optional header magic {magic:#x}, expected 0x20b (PE32+)")
            return r
        if not chars & 0x2:
            r["problems"].append("IMAGE_FILE_EXECUTABLE_IMAGE not set")
        if chars & 0x2000:
            r["problems"].append("image is a DLL")
        os_major, os_minor = u("<HH", opt + 40)
        sub_major, sub_minor = u("<HH", opt + 48)
        subsystem = u("<H", opt + 68)[0]
        r.update(os_version=f"{os_major}.{os_minor}", subsystem_version=f"{sub_major}.{sub_minor}", subsystem=subsystem)
        if subsystem != 3:
            r["problems"].append(f"subsystem {subsystem}, expected 3 (Windows console)")
        ndirs = u("<I", opt + 108)[0]
        dirs = [u("<II", opt + 112 + 8 * i) for i in range(min(ndirs, 16))]
        sects = []
        so = opt + opt_size
        for i in range(nsect):
            name = d[so + 40 * i:so + 40 * i + 8].rstrip(b"\0").decode("ascii", "replace")
            vsize, va, rawsize, rawptr = u("<IIII", so + 40 * i + 8)
            sects.append((name, va, max(vsize, rawsize), rawptr))

        def off(rva):
            for _, va, size, raw in sects:
                if va <= rva < va + size:
                    return raw + rva - va
            raise ValueError(f"RVA {rva:#x} in no section")

        def cname(rva):
            o = off(rva)
            e = d.index(b"\0", o)
            return d[o:e].decode("ascii", "replace")

        if len(dirs) > 1 and dirs[1][0]:
            o = off(dirs[1][0])
            while True:
                ilt, _, _, name_rva, iat = u("<IIIII", o)
                if not (ilt or name_rva or iat):
                    break
                r["imports"].append(cname(name_rva))
                o += 20
        if len(dirs) > 13 and dirs[13][0]:
            o = off(dirs[13][0])
            while True:
                attrs, name_rva = u("<II", o)
                if not name_rva:
                    break
                r["delay_imports"].append(cname(name_rva))
                o += 32
    except ValueError as e:
        r["problems"].append(f"malformed PE: {e}")
        return r
    for dll in r["imports"] + r["delay_imports"]:
        low = dll.lower()
        if low.startswith(RUNTIME_DLLS):
            r["problems"].append(f"MinGW runtime DLL imported: {dll}")
        elif low not in ALLOWED:
            r["problems"].append(f"DLL outside the allowed system set: {dll}")
    if "kernel32.dll" not in {x.lower() for x in r["imports"]}:
        r["problems"].append("KERNEL32.dll not imported")
    return r


def main():
    if len(sys.argv) != 3:
        sys.exit("usage: check-pe.py <zephyrd.exe> <report-file>")
    path, report = sys.argv[1:]
    d = open(path, "rb").read()
    r = inspect(d)
    lines = [
        f"pe_size={len(d)}",
        f"pe_sha256={hashlib.sha256(d).hexdigest()}",
        f"pe_magic={r.get('magic')}",
        f"pe_machine={r.get('machine')}",
        f"pe_characteristics={r.get('characteristics')}",
        f"pe_subsystem={r.get('subsystem')}",
        f"pe_subsystem_version={r.get('subsystem_version')}",
        f"pe_os_version={r.get('os_version')}",
        f"pe_timestamp={r.get('timestamp')}",
        f"pe_imports={' '.join(sorted(r['imports'], key=str.lower))}",
        f"pe_delay_imports={' '.join(sorted(r['delay_imports'], key=str.lower)) or 'none'}",
        f"pe_checks={'failed' if r['problems'] else 'passed'}",
    ]
    with open(report, "w") as f:
        f.write("\n".join(lines) + "\n")
    print("\n".join(lines))
    for p in r["problems"]:
        print(f"check-pe: {p}", file=sys.stderr)
    sys.exit(1 if r["problems"] else 0)


if __name__ == "__main__":
    main()
