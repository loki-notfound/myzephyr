#!/usr/bin/env python3
"""Helpers of link-inventory.sh (Python 3.9, standard library only; runs inside the builder images).

  link-sources.py map <src-root> <build-dir> <items> <out-prefix>
      <items>: lines "member<TAB><archive>(<TAB>)<member name>" or "object<TAB><object>", absolute
      paths, as the link trace named them. For every item inside <build-dir> it establishes which
      source file the linked object was compiled from:
        member  each member of that name in the archive (GNU, BSD and Mach-O ar formats) is read
                and hashed; the object file in <build-dir> with the same bytes (BSD archivers add
                up to 7 newline or NUL bytes of padding, which are not part of the object; when
                several objects have those bytes, the one with the member's base name) is the
                member;
        object  the object file itself;
      then the CMake dependency information of the build (every DependInfo.cmake:
      CMAKE_DEPENDS_CHECK_<LANG> pairs "source" "object", or CMAKE_DEPENDS_DEPENDENCY_FILES
      groups "source" "object" "compiler" "depfile") names the object's source.
      Writes <out-prefix>.items.tsv:
        item  archive-or-"-"  member-or-"-"  sha256  object-or-"-"  source-or-"-"  status
      status: matched, no-object (no object file in the build with those bytes), no-source (no
      DependInfo entry for the object), ambiguous (several objects with those bytes and name,
      compiled from different sources). Items outside <build-dir> are not written.
      Writes <out-prefix>.deps.tsv: "object<TAB>dependency" for every matched object, from the
      make dependency files of the object's target directory (depend.make, compiler_depend.make,
      <object>.d), dependencies as absolute normalised paths.
  link-sources.py pe-timestamp <file>
      prints the COFF header TimeDateStamp of a PE image (decimal); exit 1 if not a PE image.
  link-sources.py diff-ranges <a> <b>
      prints the byte ranges in which two files differ ("<first offset>+<length>", decimal, one
      per line; a size difference is the last range), each with the Mach-O load command, PE
      header field or ELF header that contains it when it lies in one ("-" otherwise).
"""
import hashlib
import os
import re
import struct
import sys

sys.dont_write_bytecode = True


def sha256_bytes(b):
    return hashlib.sha256(b).hexdigest()


def ar_members(path):
    """[(name, bytes)] of a static archive (System V/GNU and BSD/Mach-O formats); symbol tables skipped."""
    with open(path, "rb") as f:
        data = f.read()
    if not data.startswith(b"!<arch>\n"):
        raise ValueError(f"{path}: not an ar archive (or a thin archive)")
    pos, longnames, out = 8, b"", []
    while pos + 60 <= len(data):
        hdr = data[pos:pos + 60]
        if hdr[58:60] != b"`\n":
            raise ValueError(f"{path}: bad member header at {pos}")
        raw = hdr[0:16].decode("ascii", "replace").rstrip(" ")
        size = int(hdr[48:58].decode("ascii").strip())
        body = data[pos + 60:pos + 60 + size]
        pos += 60 + size + (size & 1)
        if raw.startswith("#1/"):                       # BSD: name follows the header
            n = int(raw[3:])
            name, body = body[:n].rstrip(b"\0").decode("utf-8", "replace"), body[n:]
        elif raw == "//":                               # GNU long-name table
            longnames = body
            continue
        elif raw in ("/", "/SYM64/"):                   # GNU symbol tables
            continue
        elif re.fullmatch(r"/[0-9]+", raw):             # GNU long name reference
            off = int(raw[1:])
            end = longnames.find(b"\n", off)
            name = longnames[off:end if end >= 0 else None].decode("utf-8", "replace").rstrip("/")
        else:
            name = raw[:-1] if raw.endswith("/") else raw
        if name.startswith("__.SYMDEF"):
            continue
        out.append((name, body))
    return out


def dependinfo_sources(bdir):
    """{absolute object path: absolute source path} from every DependInfo.cmake under bdir."""
    obj2src = {}
    q = re.compile(r'"((?:[^"\\]|\\.)*)"')
    for root, dirs, files in os.walk(bdir):
        if "DependInfo.cmake" not in files:
            continue
        text = open(os.path.join(root, "DependInfo.cmake"), encoding="utf-8", errors="replace").read()
        for m in re.finditer(r"set\(CMAKE_DEPENDS_CHECK_[A-Za-z0-9_]+\s(.*?)\)", text, re.S):
            vals = q.findall(m.group(1))
            for s, o in zip(vals[0::2], vals[1::2]):
                obj2src[os.path.normpath(o)] = os.path.normpath(s)
        for m in re.finditer(r"set\(CMAKE_DEPENDS_DEPENDENCY_FILES\s(.*?)\)", text, re.S):
            vals = q.findall(m.group(1))
            for i in range(0, len(vals) - 3, 4):
                s, o = vals[i], vals[i + 1]
                o = o if os.path.isabs(o) else os.path.join(bdir, o)
                obj2src[os.path.normpath(o)] = os.path.normpath(s)
    return obj2src


def object_index(bdir):
    """{sha256: [object paths]} of every .o/.obj file under bdir."""
    idx = {}
    for root, dirs, files in os.walk(bdir):
        for n in files:
            if n.endswith((".o", ".obj")):
                p = os.path.join(root, n)
                if os.path.islink(p) or not os.path.isfile(p):
                    continue
                with open(p, "rb") as f:
                    idx.setdefault(sha256_bytes(f.read()), []).append(os.path.normpath(p))
    return idx


def make_deps(path, bdir, base_dir):
    """{absolute object: set(absolute deps)} from a make-format dependency file."""
    out = {}
    try:
        text = open(path, encoding="utf-8", errors="replace").read()
    except OSError:
        return out
    text = text.replace("\\\n", " ")
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        m = re.match(r"^(.*?[^\\ ]):(?:\s|$)(.*)$", line)
        if not m:
            continue
        deps = [d.replace("\\ ", " ") for d in re.findall(r"(?:\\ |\S)+", m.group(2))]
        for t in re.findall(r"(?:\\ |\S)+", m.group(1)):
            t = t.replace("\\ ", " ")
            ta = os.path.normpath(t if os.path.isabs(t) else os.path.join(base_dir, t))
            s = out.setdefault(ta, set())
            for d in deps:
                s.add(os.path.normpath(d if os.path.isabs(d) else os.path.join(base_dir, d)))
    return out


def target_dir(obj):
    """The CMakeFiles/<target>.dir directory an object belongs to, or its own directory."""
    parts = obj.split(os.sep)
    for i in range(len(parts) - 1, 0, -1):
        if parts[i - 1] == "CMakeFiles" and parts[i].endswith(".dir"):
            return os.sep.join(parts[:i + 1])
    return os.path.dirname(obj)


def cmd_map(src, bdir, items_path, prefix):
    src, bdir = os.path.normpath(src), os.path.normpath(bdir)
    inside = lambda p: p == bdir or p.startswith(bdir + os.sep)
    idx = object_index(bdir)
    obj2src = dependinfo_sources(bdir)
    rows, matched = [], set()
    cache = {}
    with open(items_path, encoding="utf-8") as f:
        items = [line.rstrip("\n").split("\t") for line in f if line.strip()]
    for it in items:
        if it[0] == "member":
            arch, name = os.path.normpath(it[1]), it[2]
            if not inside(arch):
                continue
            if arch not in cache:
                cache[arch] = ar_members(arch)
            found = [b for n, b in cache[arch] if n == name]
            if not found:
                rows.append(("member", arch, name, "-", "-", "-", "no-member"))
                continue
            for body in found:
                # BSD/Mach-O archivers pad a member to a multiple of 8 bytes with newlines (or NULs):
                # the object is the member without up to 7 trailing padding bytes
                h, cands = sha256_bytes(body), []
                for k in range(0, min(8, len(body))):
                    if k and body[-k] not in (0x0A, 0x00):
                        break
                    hk = sha256_bytes(body[:len(body) - k])
                    if hk in idx:
                        h, cands = hk, idx[hk]
                        break
                if len(cands) > 1:
                    named = [c for c in cands if os.path.basename(c) == name]
                    cands = named or cands
                srcs = sorted({obj2src.get(c) for c in cands})
                if not cands:
                    rows.append(("member", arch, name, h, "-", "-", "no-object"))
                elif None in srcs:
                    rows.append(("member", arch, name, h, cands[0], "-", "no-source"))
                elif len(srcs) > 1:
                    rows.append(("member", arch, name, h, ";".join(cands), ";".join(srcs), "ambiguous"))
                else:
                    o = sorted(cands)[0]
                    rows.append(("member", arch, name, h, o, srcs[0], "matched"))
                    matched.add(o)
        elif it[0] == "object":
            o = os.path.normpath(it[1])
            if not inside(o):
                continue
            with open(o, "rb") as fo:
                h = sha256_bytes(fo.read())
            s = obj2src.get(o)
            rows.append(("object", "-", "-", h, o, s or "-", "matched" if s else "no-source"))
            if s:
                matched.add(o)
    with open(prefix + ".items.tsv", "w", encoding="utf-8") as f:
        for r in rows:
            f.write("\t".join(r) + "\n")
    # dependencies of the matched objects, from their target's make dependency files
    deps, seen_dirs = {}, set()
    for o in sorted(matched):
        td = target_dir(o)
        if td not in seen_dirs:
            seen_dirs.add(td)
            for n in ("depend.make", "compiler_depend.make"):
                for k, v in make_deps(os.path.join(td, n), bdir, bdir).items():
                    deps.setdefault(k, set()).update(v)
        d = o + ".d"
        if os.path.isfile(d):
            for k, v in make_deps(d, bdir, bdir).items():
                deps.setdefault(k, set()).update(v)
    with open(prefix + ".deps.tsv", "w", encoding="utf-8") as f:
        for o in sorted(matched):
            for d in sorted(deps.get(o, ())):
                f.write(f"{o}\t{d}\n")
    return 0


def pe_timestamp(path):
    with open(path, "rb") as f:
        b = f.read(4096)
    if len(b) < 0x40 or b[:2] != b"MZ":
        return None
    o = struct.unpack_from("<I", b, 0x3C)[0]
    if o + 24 > len(b) or b[o:o + 4] != b"PE\0\0":
        return None
    return struct.unpack_from("<I", b, o + 8)[0]


def regions(b):
    """[(start, end, label)] of header structures for labelling differing ranges."""
    out = []
    if b[:4] in (b"\xcf\xfa\xed\xfe", b"\xce\xfa\xed\xfe"):
        is64 = b[:4] == b"\xcf\xfa\xed\xfe"
        ncmds = struct.unpack_from("<I", b, 16)[0]
        o = 32 if is64 else 28
        out.append((0, o, "Mach-O header"))
        names = {0x19: "LC_SEGMENT_64", 0x1b: "LC_UUID", 0x22: "LC_DYLD_INFO", 0x80000022: "LC_DYLD_INFO_ONLY",
                 0x2: "LC_SYMTAB", 0xb: "LC_DYSYMTAB", 0x1d: "LC_CODE_SIGNATURE", 0x26: "LC_FUNCTION_STARTS",
                 0x29: "LC_DATA_IN_CODE", 0x24: "LC_VERSION_MIN_MACOSX", 0x32: "LC_BUILD_VERSION",
                 0x2a: "LC_SOURCE_VERSION", 0x80000028: "LC_MAIN", 0xc: "LC_LOAD_DYLIB", 0xe: "LC_LOAD_DYLINKER"}
        for _ in range(ncmds):
            if o + 8 > len(b):
                break
            cmd, sz = struct.unpack_from("<II", b, o)
            out.append((o, o + sz, names.get(cmd, f"load command 0x{cmd:x}")))
            o += max(sz, 8)
    elif b[:2] == b"MZ" and len(b) >= 0x40:
        o = struct.unpack_from("<I", b, 0x3C)[0]
        if b[o:o + 4] == b"PE\0\0":
            out += [(o + 8, o + 12, "PE COFF TimeDateStamp"), (o + 24 + 64, o + 24 + 68, "PE optional header CheckSum"),
                    (0, o + 24, "PE headers")]
    elif b[:4] == b"\x7fELF":
        out.append((0, 64, "ELF header"))
    return out


def diff_ranges(a, b):
    with open(a, "rb") as f:
        x = f.read()
    with open(b, "rb") as f:
        y = f.read()
    regs = regions(x)
    n, i, res = min(len(x), len(y)), 0, []
    while i < n:
        if x[i] != y[i]:
            j = i
            while j < n and x[j] != y[j]:
                j += 1
            lab = next((l for s, e, l in regs if s <= i and j <= e), "-")
            res.append(f"{i}+{j - i} {lab}")
            i = j
        else:
            i += 1
    if len(x) != len(y):
        res.append(f"{n}+{abs(len(x) - len(y))} size differs ({len(x)} vs {len(y)})")
    return res


def main(argv):
    if len(argv) == 5 and argv[0] == "map":
        return cmd_map(*argv[1:])
    if len(argv) == 2 and argv[0] == "pe-timestamp":
        t = pe_timestamp(argv[1])
        if t is None:
            print(f"{argv[1]}: not a PE image", file=sys.stderr)
            return 1
        print(t)
        return 0
    if len(argv) == 3 and argv[0] == "diff-ranges":
        for r in diff_ranges(argv[1], argv[2]):
            print(r)
        return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
