#!/usr/bin/env python3
"""Self-test of the cross-target checks: check-elf.sh --arch aarch64, check-macho.py, check-pe.py,
check-embedded.py, make-cross-manifest.py and verify-cross-artifact.py.

  cross-selftest.py <work-dir>     (<work-dir> must not exist)

Fixtures: tests/cross-fixture/<target>.json hold metadata measured on real local cross builds
(macOS and Windows of 13d6352b6, Linux AArch64 of 3dea684bb: static report values and the
build-log records). From them this script makes small SYNTHETIC binaries: a Mach-O and a PE
file with the measured architecture, minimum OS and library list, and an ELF file with the
measured machine, interpreter, NEEDED set and glibc version references, each carrying the
expected version and the four mainnet IP seeds as strings. Nothing is executed; these are not
the real binaries and say nothing about them beyond the checks' logic.

Each positive case must pass; each negative case changes one variable and must fail with
the named diagnostic. Exit 0 when every case gives the intended result.
"""
import hashlib
import json
import os
import shutil
import struct
import subprocess
import sys

here = os.path.dirname(os.path.abspath(__file__))
tools = os.path.dirname(here)
fixdir = os.path.join(here, "cross-fixture")
work = os.path.abspath(sys.argv[1]) if len(sys.argv) == 2 else sys.exit("usage: cross-selftest.py <work-dir>")
if os.path.lexists(work):
    sys.exit(f"{work} exists")
os.makedirs(work)
PY = sys.executable
SEEDS = ["142.93.255.216:17766", "142.93.98.116:17766", "24.199.101.125:17766", "85.215.93.176:17766"]
results = []
n = [0]


def record(name, ok, detail=""):
    results.append({"case": name, "ok": bool(ok), "detail": detail})
    print(f"{'ok  ' if ok else 'FAIL'} {name}" + (f" -- {detail}" if detail and not ok else ""))


def newdir(tag):
    n[0] += 1
    d = os.path.join(work, f"{n[0]:03d}-{tag}")
    os.makedirs(d)
    return d


def strings_blob(version, seeds=SEEDS, extra=()):
    return b"\0" + b"".join(s.encode() + b"\0" for s in [version, *seeds, *extra]) + b"\0" * 7


# ---------------------------------------------------------------- synthetic Mach-O
def macho(meta, version, *, cputype=None, min_os=None, dylibs=None, rpath=None, fat=False, filetype=2,
          seeds=SEEDS, extra_strings=()):
    def ver(s):
        a, b, c = (int(x) for x in s.split("."))
        return (a << 16) | (b << 8) | c

    def pad(b):
        return b + b"\0" * (-len(b) % 8)
    cmds = []
    name = pad(meta["dylinker"].encode() + b"\0")
    cmds.append(struct.pack("<III", 0xE, 12 + len(name), 12) + name)
    mo = min_os or meta["min_os"]
    cmds.append(struct.pack("<IIII", 0x24, 16, ver(mo), ver(meta["sdk"])))
    for lib in (dylibs if dylibs is not None else meta["dylibs"]):
        s = pad(lib.encode() + b"\0")
        cmds.append(struct.pack("<IIIIII", 0xC, 24 + len(s), 24, 2, 0x10000, 0x10000) + s)
    if rpath:
        s = pad(rpath.encode() + b"\0")
        cmds.append(struct.pack("<III", 0x8000001C, 12 + len(s), 12) + s)
    body = b"".join(cmds)
    hdr = struct.pack("<IiiIIIII", 0xFEEDFACF, cputype if cputype is not None else int(meta["cputype"], 16),
                      3, filetype, len(cmds), len(body), int(meta["flags"], 16), 0)
    data = hdr + body + strings_blob(version, seeds, extra_strings)
    if fat:
        data = struct.pack(">II", 0xCAFEBABE, 1) + struct.pack(">iiIII", 0x01000007, 3, 4096, len(data), 12) \
            + b"\0" * (4096 - 28) + data
    return data


# ---------------------------------------------------------------- synthetic ELF
def elf(meta, version, *, machine=None, needed=None, runpath=None, version_needs=None, seeds=SEEDS,
        extra_strings=()):
    """A minimal ELF64 little-endian ET_DYN file: PT_INTERP, PT_DYNAMIC (DT_NEEDED, optional
    DT_RUNPATH, version references), a GNU build-ID note and undefined versioned dynamic symbols,
    with section headers so that readelf -V and objdump -T read them."""
    def elf_hash(name):
        h = 0
        for c in name.encode():
            h = ((h << 4) + c) & 0xFFFFFFFF
            g = h & 0xF0000000
            if g:
                h ^= g >> 24
            h &= ~g & 0xFFFFFFFF
        return h

    needed = list(needed if needed is not None else meta["needed"])
    vneeds = version_needs if version_needs is not None else meta["version_needs"]
    dynstr = bytearray(b"\0")
    stroff = {}

    def s(x):
        if x not in stroff:
            stroff[x] = len(dynstr)
            dynstr.extend(x.encode() + b"\0")
        return stroff[x]
    for lib in needed:
        s(lib)
    syms, vers = [], []          # (name offset), version index
    verneed = []                 # (lib, [(version, index)])
    idx = 2
    for lib in sorted(vneeds):
        aux = []
        for ver in sorted(vneeds[lib]):
            aux.append((ver, idx))
            for sym in vneeds[lib][ver]:
                syms.append(s(sym))
                vers.append(idx)
            idx += 1
        verneed.append((lib, aux))
    for lib, aux in verneed:
        s(lib)
        for ver, _ in aux:
            s(ver)
    if runpath is not None:
        s(runpath)
    interp = meta["interpreter"].encode() + b"\0"
    build_id = bytes.fromhex(meta["build_id"])
    note = struct.pack("<III", 4, len(build_id), 3) + b"GNU\0" + build_id

    dynsym = b"\0" * 24 + b"".join(struct.pack("<IBBHQQ", o, 0x12, 0, 0, 0, 0) for o in syms)
    versym = struct.pack("<H", 0) + b"".join(struct.pack("<H", v) for v in vers)
    vr = bytearray()
    for i, (lib, aux) in enumerate(verneed):
        last = i == len(verneed) - 1
        vr += struct.pack("<HHIII", 1, len(aux), stroff[lib], 16, 0 if last else 16 + 16 * len(aux))
        for j, (ver, vidx) in enumerate(aux):
            vr += struct.pack("<IHHII", elf_hash(ver), 0, vidx, stroff[ver], 0 if j == len(aux) - 1 else 16)
    rodata = strings_blob(version, seeds, extra_strings)
    shstr = bytearray(b"\0")

    def sh(name):
        o = len(shstr)
        shstr.extend(name.encode() + b"\0")
        return o

    # layout: header, 4 program headers, then sections at aligned offsets (vaddr = offset)
    nph = 4
    off = 64 + 56 * nph
    blobs = {}

    def place(name, data, align):
        nonlocal off
        off += -off % align
        blobs[name] = (off, data)
        off += len(data)
    place(".interp", interp, 1)
    place(".note.gnu.build-id", note, 4)
    place(".dynsym", dynsym, 8)
    place(".dynstr", bytes(dynstr), 1)
    place(".gnu.version", versym, 2)
    place(".gnu.version_r", bytes(vr), 4)
    dyn_entries = [(1, stroff[lib]) for lib in needed]
    if runpath is not None:
        dyn_entries.append((29, stroff[runpath]))
    dyn_entries += [(5, blobs[".dynstr"][0]), (6, blobs[".dynsym"][0]), (10, len(dynstr)), (11, 24),
                    (0x6FFFFFF0, blobs[".gnu.version"][0]), (0x6FFFFFFE, blobs[".gnu.version_r"][0]),
                    (0x6FFFFFFF, len(verneed)), (0x6FFFFFFB, int(meta["flags_1"], 16)), (0, 0)]
    dynamic = b"".join(struct.pack("<qQ", t, v) for t, v in dyn_entries)
    place(".dynamic", dynamic, 8)
    place(".rodata", rodata, 1)
    names = [".interp", ".note.gnu.build-id", ".dynsym", ".dynstr", ".gnu.version", ".gnu.version_r", ".dynamic",
             ".rodata"]
    shname = {n: sh(n) for n in names}
    shname[".shstrtab"] = sh(".shstrtab")
    place(".shstrtab", bytes(shstr), 1)
    off += -off % 8
    shoff = off
    sec_index = {n: i + 1 for i, n in enumerate(names + [".shstrtab"])}
    # type, flags, link, info, align, entsize
    spec = {".interp": (1, 2, 0, 0, 1, 0), ".note.gnu.build-id": (7, 2, 0, 0, 4, 0),
            ".dynsym": (11, 2, sec_index[".dynstr"], 1, 8, 24), ".dynstr": (3, 2, 0, 0, 1, 0),
            ".gnu.version": (0x6FFFFFFF, 2, sec_index[".dynsym"], 0, 2, 2),
            ".gnu.version_r": (0x6FFFFFFE, 2, sec_index[".dynstr"], len(verneed), 4, 0),
            ".dynamic": (6, 3, sec_index[".dynstr"], 0, 8, 16), ".rodata": (1, 2, 0, 0, 1, 0),
            ".shstrtab": (3, 0, 0, 0, 1, 0)}
    shdrs = b"\0" * 64
    for n in names + [".shstrtab"]:
        t, fl, link, info, al, es = spec[n]
        o, data = blobs[n]
        addr = o if fl & 2 else 0
        shdrs += struct.pack("<IIQQQQIIQQ", shname[n], t, fl, addr, o, len(data), link, info, al, es)
    total = shoff + len(shdrs)
    phdrs = struct.pack("<IIQQQQQQ", 3, 4, blobs[".interp"][0], blobs[".interp"][0], blobs[".interp"][0],
                        len(interp), len(interp), 1)
    phdrs += struct.pack("<IIQQQQQQ", 1, 4, 0, 0, 0, total, total, 0x10000)
    phdrs += struct.pack("<IIQQQQQQ", 2, 6, blobs[".dynamic"][0], blobs[".dynamic"][0], blobs[".dynamic"][0],
                         len(dynamic), len(dynamic), 8)
    phdrs += struct.pack("<IIQQQQQQ", 4, 4, blobs[".note.gnu.build-id"][0], blobs[".note.gnu.build-id"][0],
                         blobs[".note.gnu.build-id"][0], len(note), len(note), 4)
    ident = b"\x7fELF" + bytes([2, 1, 1, 0]) + b"\0" * 8
    hdr = ident + struct.pack("<HHIQQQIHHHHHH", 3, machine if machine is not None else meta["machine"], 1, 0, 64,
                              shoff, 0, 64, 56, nph, 64, len(names) + 2, sec_index[".shstrtab"])
    out = bytearray(total)
    out[0:64] = hdr
    out[64:64 + len(phdrs)] = phdrs
    for n, (o, data) in blobs.items():
        out[o:o + len(data)] = data
    out[shoff:shoff + len(shdrs)] = shdrs
    return bytes(out)


# ---------------------------------------------------------------- synthetic PE
def pe(meta, version, *, machine=0x8664, magic=0x20B, subsystem=None, imports=None, delay=(), seeds=SEEDS,
       extra_strings=()):
    imports = list(imports if imports is not None else meta["imports"])
    sect_rva, sect_raw = 0x1000, 0x400
    desc = 20 * (len(imports) + 1)
    ddesc = 32 * (len(delay) + 1) if delay else 0
    names = b""
    name_rva = []
    for dll in imports + list(delay):
        name_rva.append(sect_rva + desc + ddesc + len(names))
        names += dll.encode() + b"\0"
    idata = b"".join(struct.pack("<IIIII", 0, 0, 0, name_rva[i], sect_rva) for i in range(len(imports))) + b"\0" * 20
    if delay:
        idata += b"".join(struct.pack("<IIIIIIII", 1, name_rva[len(imports) + i], 0, 0, 0, 0, 0, 0)
                          for i in range(len(delay))) + b"\0" * 32
    section = idata + names + strings_blob(version, seeds, extra_strings)
    section += b"\0" * (-len(section) % 0x200)
    opt = bytearray(240)
    struct.pack_into("<H", opt, 0, magic)
    sv = meta["subsystem_version"].split(".")
    ov = meta["os_version"].split(".")
    struct.pack_into("<HH", opt, 40, int(ov[0]), int(ov[1]))
    struct.pack_into("<HH", opt, 48, int(sv[0]), int(sv[1]))
    struct.pack_into("<H", opt, 68, subsystem if subsystem is not None else int(meta["subsystem"]))
    struct.pack_into("<I", opt, 108, 16)
    struct.pack_into("<II", opt, 112 + 8, sect_rva, desc)
    if delay:
        struct.pack_into("<II", opt, 112 + 8 * 13, sect_rva + desc, ddesc)
    dos = bytearray(0x80)
    dos[0:2] = b"MZ"
    struct.pack_into("<I", dos, 0x3C, 0x80)
    coff = b"PE\0\0" + struct.pack("<HHIIIHH", machine, 1, 0, 0, 0, 240, int(meta["characteristics"], 16))
    sect = b".idata\0\0" + struct.pack("<IIIIIIHHI", len(section), sect_rva, len(section), sect_raw, 0, 0, 0, 0, 0xC0000040)
    head = bytes(dos) + coff + bytes(opt) + sect
    return head + b"\0" * (sect_raw - len(head)) + section


def run_checker(target, meta, data, d):
    """Run the static checker of target on synthetic data; returns (exit, stderr, report path, binary path)."""
    name = "zephyrd.exe" if target == "x86_64-w64-mingw32" else "zephyrd"
    b = os.path.join(d, name)
    with open(b, "wb") as f:
        f.write(data)
    rep = os.path.join(d, "static-report.txt")
    if target == "aarch64-linux-gnu":
        cmd = ["bash", os.path.join(tools, "check-elf.sh"), "--arch", "aarch64", b, rep]
    elif target == "x86_64-apple-darwin":
        cmd = [PY, "-I", os.path.join(tools, "check-macho.py"), b, rep]
    else:
        cmd = [PY, "-I", os.path.join(tools, "check-pe.py"), b, rep]
    p = subprocess.run(cmd, capture_output=True, text=True)
    return p.returncode, p.stderr, rep, b


def expect_checker(name, target, meta, data, want_exit, frag=""):
    d = newdir(name.replace(" ", "-"))
    rc, err, _, _ = run_checker(target, meta, data, d)
    record(f"{target}: {name}", rc == want_exit and frag in err, f"exit {rc} (want {want_exit}) stderr {err.strip()[:300]!r}")


# ---------------------------------------------------------------- checker cases
TARGETS = ("aarch64-linux-gnu", "x86_64-apple-darwin", "x86_64-w64-mingw32")
fx = {t: json.load(open(os.path.join(fixdir, f"{t}.json"))) for t in TARGETS}
V = fx["x86_64-apple-darwin"]["expected_version"]
VA = fx["aarch64-linux-gnu"]["expected_version"]

e = fx["aarch64-linux-gnu"]["elf"]
expect_checker("positive (measured metadata)", "aarch64-linux-gnu", e, elf(e, VA), 0)
d_ = newdir("aarch64-measured-values")
rc_, err_, rep_, _ = run_checker("aarch64-linux-gnu", e, elf(e, VA), d_)
got_ = dict(l.rstrip("\n").split("=", 1) for l in open(rep_) if "=" in l)
want_ = fx["aarch64-linux-gnu"]["measured"]["report"]
keys_ = ("elf_interpreter", "elf_needed", "elf_rpath_runpath", "elf_max_glibc", "elf_max_glibc_allowed",
         "elf_cxx_version_needs", "elf_symbols_above_glibc_2_17", "elf_build_id", "elf_checks")
record("aarch64-linux-gnu: synthetic report equals the real build's report in every format value",
       rc_ == 0 and all(got_.get(k) == want_.get(k) for k in keys_),
       str({k: (got_.get(k), want_.get(k)) for k in keys_ if got_.get(k) != want_.get(k)}))
expect_checker("wrong machine (x86-64)", "aarch64-linux-gnu", e, elf(e, VA, machine=62), 1, "not AArch64")
vn_ = json.loads(json.dumps(e["version_needs"]))
vn_.setdefault("libpthread.so.0", {})["GLIBC_2.30"] = ["pthread_cond_clockwait"]
expect_checker("glibc version above 2.29 (GLIBC_2.30)", "aarch64-linux-gnu", e, elf(e, VA, version_needs=vn_), 1,
               "needs GLIBC_2.30, more than GLIBC_2.29")
expect_checker("RUNPATH present", "aarch64-linux-gnu", e, elf(e, VA, runpath="/src/contrib/depends/aarch64-linux-gnu/lib:"),
               1, "has RPATH/RUNPATH")
expect_checker("extra NEEDED (shared C++ runtime)", "aarch64-linux-gnu", e,
               elf(e, VA, needed=e["needed"] + ["libstdc++.so.6"]), 1, "unexpected NEEDED libstdc++.so.6")

m = fx["x86_64-apple-darwin"]["macho"]
expect_checker("positive (measured metadata)", "x86_64-apple-darwin", m, macho(m, V), 0)
expect_checker("wrong architecture (arm64)", "x86_64-apple-darwin", m, macho(m, V, cputype=0x0100000C), 1, "cputype")
expect_checker("wrong minimum OS (10.15)", "x86_64-apple-darwin", m, macho(m, V, min_os="10.15.0"), 1, "minimum macOS")
expect_checker("extra library", "x86_64-apple-darwin", m, macho(m, V, dylibs=m["dylibs"] + ["/usr/local/lib/libssl.3.dylib"]), 1,
               "outside the allowed OS set")
expect_checker("extra non-allowed framework", "x86_64-apple-darwin", m,
               macho(m, V, dylibs=m["dylibs"] + ["/System/Library/Frameworks/Metal.framework/Versions/A/Metal"]), 1,
               "outside the allowed OS set")
expect_checker("libSystem missing", "x86_64-apple-darwin", m,
               macho(m, V, dylibs=[x for x in m["dylibs"] if "libSystem" not in x]), 1, "libSystem")
expect_checker("universal binary", "x86_64-apple-darwin", m, macho(m, V, fat=True), 1, "universal")
expect_checker("LC_RPATH present", "x86_64-apple-darwin", m, macho(m, V, rpath="@loader_path/../lib"), 1, "LC_RPATH")
expect_checker("not MH_EXECUTE", "x86_64-apple-darwin", m, macho(m, V, filetype=6), 1, "filetype")

p_ = fx["x86_64-w64-mingw32"]["pe"]
expect_checker("positive (measured metadata)", "x86_64-w64-mingw32", p_, pe(p_, V), 0)
expect_checker("wrong architecture (i386)", "x86_64-w64-mingw32", p_, pe(p_, V, machine=0x14C), 1, "machine")
expect_checker("PE32 instead of PE32+", "x86_64-w64-mingw32", p_, pe(p_, V, magic=0x10B), 1, "PE32+")
expect_checker("GUI subsystem", "x86_64-w64-mingw32", p_, pe(p_, V, subsystem=2), 1, "subsystem")
expect_checker("extra library (MinGW runtime DLL)", "x86_64-w64-mingw32", p_, pe(p_, V, imports=p_["imports"] + ["libwinpthread-1.dll"]),
               1, "MinGW runtime")
expect_checker("extra library (third-party DLL)", "x86_64-w64-mingw32", p_, pe(p_, V, imports=p_["imports"] + ["libcrypto-3-x64.dll"]),
               1, "outside the allowed system set")
expect_checker("extra delay-load library", "x86_64-w64-mingw32", p_, pe(p_, V, delay=["libstdc++-6.dll"]), 1, "MinGW runtime")
expect_checker("KERNEL32 missing", "x86_64-w64-mingw32", p_,
               pe(p_, V, imports=[x for x in p_["imports"] if x.lower() != "kernel32.dll"]), 1, "KERNEL32")


# ---------------------------------------------------------------- embedded strings
def expect_embedded(name, data, want_exit, frag=""):
    d = newdir("embedded-" + name.replace(" ", "-"))
    b = os.path.join(d, "bin")
    open(b, "wb").write(data)
    p = subprocess.run([PY, "-I", os.path.join(tools, "check-embedded.py"), b, V, os.path.join(d, "r.txt")],
                       capture_output=True, text=True)
    record(f"embedded: {name}", p.returncode == want_exit and frag in p.stderr, f"exit {p.returncode} {p.stderr.strip()[:200]!r}")


expect_embedded("version and four seeds", b"x" * 64 + strings_blob(V), 0)
expect_embedded("wrong version", strings_blob("2.3.0-0123abcde"), 1, "not embedded")
expect_embedded("second version string", strings_blob(V, extra=["2.3.0-release"]), 1, "other version strings")
expect_embedded("seed missing", strings_blob(V, seeds=SEEDS[:2] + SEEDS[3:]), 1, "24.199.101.125:17766 not embedded")
expect_embedded("fourth seed missing (three seeds only)", strings_blob(V, seeds=SEEDS[:3]), 1, "85.215.93.176:17766 not embedded")
d_ = newdir("embedded-aarch64-wrong-version")
open(os.path.join(d_, "zephyrd"), "wb").write(elf(e, "2.3.0-0123abcde"))
p_e = subprocess.run([PY, "-I", os.path.join(tools, "check-embedded.py"), os.path.join(d_, "zephyrd"), VA,
                      os.path.join(d_, "r.txt")], capture_output=True, text=True)
record("embedded: aarch64-linux-gnu ELF with the wrong version", p_e.returncode == 1 and "not embedded" in p_e.stderr,
       f"exit {p_e.returncode} {p_e.stderr.strip()[:200]!r}")
expect_embedded("version only as a substring", b"v" + V.encode() + b"x\0" + strings_blob("2.3.0-0123abcde")[1:], 1, "not embedded")


# ---------------------------------------------------------------- manifest and verifier, end to end
CTX = {"GITHUB_REPOSITORY": "example/fixture", "GITHUB_REF": "refs/heads/ci/daemon-release-baseline",
       "GITHUB_WORKFLOW_REF": "example/fixture/.github/workflows/daemon-release-baseline.yml@refs/heads/ci/daemon-release-baseline",
       "GITHUB_RUN_ID": "1", "GITHUB_RUN_NUMBER": "1", "GITHUB_RUN_ATTEMPT": "1", "GITHUB_JOB": "cross-build",
       "GITHUB_EVENT_NAME": "push", "GITHUB_SERVER_URL": "https://github.com"}
POLICY = ["--base-repository", "https://github.com/zephyr-backports/zephyr.git", "--base-tag", "v2.3.0-sec.2",
          "--base-tag-object", "b84129b0d914c60d4dea506ca01f30091c31e9e1",
          "--base-commit", "8c6a120256b4bd887d6e7167d929d76e3507e0e5",
          "--base-fingerprint", "FB3994F0997CA6F043D724919EFF03F527D240A1",
          "--maintainer-fingerprint", "31DA39AB43E0CA67F1F3A661BA2AFF22DF8A4A13"]


def synth(target, version=None, **kw):
    f = fx[target]
    version = version or f["expected_version"]
    if target == "aarch64-linux-gnu":
        return elf(f["elf"], version, **kw)
    if target == "x86_64-apple-darwin":
        return macho(f["macho"], version, **kw)
    return pe(f["pe"], version, **kw)


def make_artifact(target, data=None):
    """A complete artifact directory as the cross-build job stages it, from synthetic data."""
    f = fx[target]
    d = newdir("artifact-" + target)
    commit = f["source_commit"]
    work_d = os.path.join(d, "make")
    os.makedirs(work_d)
    rc, err, rep, b = run_checker(target, f.get("elf") or f.get("macho") or f.get("pe"), data or synth(target), work_d)
    if rc != 0:
        raise SystemExit(f"fixture binary for {target} does not pass its checker: {err}")
    emb = os.path.join(work_d, "embedded-report.txt")
    subprocess.run([PY, "-I", os.path.join(tools, "check-embedded.py"), b, f["expected_version"], emb], check=True,
                   capture_output=True)
    logs = os.path.join(work_d, "build-logs")
    os.makedirs(logs)
    for name, lines in f["build_logs"].items():
        with open(os.path.join(logs, name), "w") as fh:
            fh.write("".join(l + "\n" for l in lines))
    # the fixture's source identity predates the two lines verify-source.sh now writes after the commit time
    ident = f["source_identity"].splitlines()
    at = next(i for i, l in enumerate(ident) if l.startswith("source_commit_time=")) + 1
    ident[at:at] = ["tags_at_head=none", "tags_in_checkout=0"]
    open(os.path.join(work_d, "source-identity.txt"), "w").write("\n".join(ident) + "\n")
    record_file = os.path.join(work_d, "checkout.txt")
    open(record_file, "w").write(f"fetch_mode=depth-1-no-tags+unshallow-no-tags\ntags_in_checkout=0\ntags_at_head=none\n"
                                 f"event_name=push\nbuilt_commit={commit}\n")
    open(os.path.join(work_d, "expected-version.txt"), "w").write(f["expected_version"] + "\n")
    os.makedirs(os.path.join(work_d, "build"))
    art = os.path.join(d, "art")
    os.makedirs(art)
    env = dict(os.environ, **CTX, GITHUB_SHA=commit, GITHUB_WORKFLOW_SHA=commit, MYZ_PULL_REQUEST="none")
    p = subprocess.run([PY, "-I", os.path.join(tools, "make-cross-manifest.py"), "--target", target,
                        "--source-identity", os.path.join(work_d, "source-identity.txt"),
                        "--expected-version", os.path.join(work_d, "expected-version.txt"), "--builder-logs", logs,
                        "--static-report", rep, "--embedded-report", emb, "--binary", b,
                        "--build-dir", os.path.join(work_d, "build"), "--recipe-dir", os.path.join(tools, "cross"),
                        "--checkout-record", record_file,
                        "--out", os.path.join(art, "manifest.json")], env=env, capture_output=True, text=True)
    if p.returncode != 0:
        raise SystemExit(f"make-cross-manifest failed for {target}: {p.stderr}")
    for x in (b, rep, emb, os.path.join(work_d, "source-identity.txt"), os.path.join(work_d, "expected-version.txt")):
        shutil.copy(x, art)
    shutil.copytree(logs, os.path.join(art, "build-logs"))
    name = os.path.basename(b)
    write_sums(art, name)
    trusted = os.path.join(d, "trusted")
    os.makedirs(trusted)
    for x in (rep, emb, os.path.join(work_d, "source-identity.txt")):
        shutil.copy(x, trusted)
    return d, art, trusted, name


def write_sums(art, name):
    lines = []
    for x in (name, "manifest.json", "expected-version.txt", "source-identity.txt"):
        lines.append(f"{hashlib.sha256(open(os.path.join(art, x), 'rb').read()).hexdigest()}  {x}\n")
    open(os.path.join(art, "SHA256SUMS"), "w").write("".join(lines))


def verify(target, art, trusted, *, version=None, target_arg=None, extra=(), static=None, run_id="1", ref=None,
           event="push", github_sha=None):
    f = fx[target]
    ref = ref or CTX["GITHUB_REF"]
    cmd = [PY, "-I", os.path.join(tools, "verify-cross-artifact.py"), "--target", target_arg or target, "--artifact", art,
           "--expected-commit", f["source_commit"], "--expected-version", version or f["expected_version"],
           "--repository", CTX["GITHUB_REPOSITORY"], "--ref", ref,
           "--workflow-ref", CTX["GITHUB_WORKFLOW_REF"].rsplit("@", 1)[0] + "@" + ref,
           "--event-name", event, "--github-sha", github_sha or f["source_commit"], "--pull-request", "none",
           "--run-id", run_id, "--run-attempt", "1", *POLICY,
           "--source-identity", os.path.join(trusted, "source-identity.txt"),
           "--static-report", static or os.path.join(trusted, "static-report.txt"),
           "--embedded-report", os.path.join(trusted, "embedded-report.txt"),
           "--recipe-dir", os.path.join(tools, "cross"), *extra]
    return subprocess.run(cmd, capture_output=True, text=True)


def expect_verify(name, target, p, want_exit, frag=""):
    record(f"verify {target}: {name}", p.returncode == want_exit and frag in p.stderr,
           f"exit {p.returncode} (want {want_exit}) {p.stderr.strip()[-300:]!r}")


def edit_manifest(art, fn, name):
    mp = os.path.join(art, "manifest.json")
    m = json.load(open(mp))
    fn(m)
    json.dump(m, open(mp, "w"), indent=2, sort_keys=True)
    write_sums(art, name)


for t in TARGETS:
    d, art, trusted, name = make_artifact(t)
    expect_verify("positive (synthetic binary, measured metadata)", t, verify(t, art, trusted), 0)
    other = {"aarch64-linux-gnu": "x86_64-apple-darwin", "x86_64-apple-darwin": "x86_64-w64-mingw32",
             "x86_64-w64-mingw32": "x86_64-apple-darwin"}[t]
    expect_verify("wrong target", t, verify(t, art, trusted, target_arg=other), 1, "FAILED")
    expect_verify("wrong version", t, verify(t, art, trusted, version="2.3.0-0123abcde"), 1, "expected-version.txt")
    expect_verify("wrong run id", t, verify(t, art, trusted, run_id="2"), 1, "workflow.run_id")
    expect_verify("trusted ref outside the table", t, verify(t, art, trusted, ref="refs/heads/main"), 1,
                  "trusted run identity not in the table")
    expect_verify("trusted pull_request event without pull request fields", t, verify(t, art, trusted, event="pull_request"), 1,
                  "trusted run identity not in the table")
    expect_verify("trusted push to my/v2.3.0 against a ci-branch manifest", t,
                  verify(t, art, trusted, ref="refs/heads/my/v2.3.0"), 1, "workflow.ref")
    expect_verify("expected version release refused", t, verify(t, art, trusted, version="2.3.0-release"), 2, "never accepted")
    d8, art8, trusted8, _ = make_artifact(t)
    edit_manifest(art8, lambda m: m["artifact"].__setitem__("expected_version", "2.3.0-release"), name)
    expect_verify("manifest claims a release version (schema)", t, verify(t, art8, trusted8), 1, "artifact.expected_version")
    d9, art9, trusted9, _ = make_artifact(t)
    edit_manifest(art9, lambda m: m["source"].__setitem__("tags_at_head", "v2.3.0-sec.2-my.1"), name)
    expect_verify("manifest claims a tag at the commit", t, verify(t, art9, trusted9), 1, "source.tags_at_head")
    # binary replaced after the manifest: SHA256SUMS rewritten too, the hashes still disagree with the manifest
    d2, art2, trusted2, _ = make_artifact(t)
    open(os.path.join(art2, name), "ab").write(b"\0")
    write_sums(art2, name)
    expect_verify("binary changed after the manifest", t, verify(t, art2, trusted2), 1, "artifact.sha256")
    # the artifact's static report claims a value the verifier's own report does not show
    d3, art3, trusted3, _ = make_artifact(t)
    rp = os.path.join(art3, "static-report.txt")
    key = {"aarch64-linux-gnu": "elf_needed", "x86_64-apple-darwin": "macho_dylibs", "x86_64-w64-mingw32": "pe_imports"}[t]
    txt = open(rp).read().replace(f"{key}=", f"{key}=extra.lib ", 1)
    open(rp, "w").write(txt)
    expect_verify("artifact static report differs (extra library)", t, verify(t, art3, trusted3), 1, key)
    d4, art4, trusted4, _ = make_artifact(t)
    edit_manifest(art4, lambda m: m["embedded"].__setitem__("seeds", SEEDS[:3] + ["1.2.3.4:17766"]), name)
    expect_verify("manifest seeds altered", t, verify(t, art4, trusted4), 1, "embedded.seeds")
    d5, art5, trusted5, _ = make_artifact(t)
    edit_manifest(art5, lambda m: m["workflow"].__setitem__("local_build", True), name)
    expect_verify("local build manifest", t, verify(t, art5, trusted5), 1, "")
    d6, art6, trusted6, _ = make_artifact(t)
    wrong_fmt = {"aarch64-linux-gnu": "macho", "x86_64-apple-darwin": "pe", "x86_64-w64-mingw32": "macho"}[t]
    edit_manifest(art6, lambda m: m["artifact"].__setitem__("format", wrong_fmt), name)
    expect_verify("format does not match the target (schema)", t, verify(t, art6, trusted6), 1, "oneOf")
    d7, art7, trusted7, _ = make_artifact(t)
    open(os.path.join(art7, "manifest.json"), "a").write(" ")
    expect_verify("SHA256SUMS mismatch", t, verify(t, art7, trusted7), 1, "manifest.json matches SHA256SUMS")

# the verifier's own report of a binary with GLIBC_2.30 / the wrong minimum OS / an extra library fails it
for t, kw, frag in (("aarch64-linux-gnu", {"version_needs": vn_}, "elf_checks"),
                    ("x86_64-apple-darwin", {"min_os": "10.15.0"}, "macho_checks"),
                    ("x86_64-w64-mingw32", {"imports": fx["x86_64-w64-mingw32"]["pe"]["imports"] + ["libwinpthread-1.dll"]}, "pe_checks")):
    d, art, trusted, name = make_artifact(t)
    bad_d = newdir("bad-binary-" + t)
    rc, _, rep, _ = run_checker(t, fx[t].get("elf") or fx[t].get("macho") or fx[t].get("pe"), synth(t, **kw), bad_d)
    expect_verify(f"verifier's own report of a non-conforming binary ({frag})", t,
                  verify(t, art, trusted, static=rep), 1, frag)

with open(os.path.join(work, "results.json"), "w") as f:
    json.dump(results, f, indent=2)
bad = [r for r in results if not r["ok"]]
print(f"{len(results) - len(bad)}/{len(results)} cases as intended (synthetic binaries; not the real cross builds)")
sys.exit(1 if bad else 0)
