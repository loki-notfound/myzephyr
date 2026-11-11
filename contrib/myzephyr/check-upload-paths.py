#!/usr/bin/env python3
"""Check every path below a directory before actions/upload-artifact uploads it.

  check-upload-paths.py [--strict] [--allow-missing] DIR [DIR ...]

Fails (exit 1) on any file or directory path, relative to DIR, that contains a character the
upload refuses, or a path component that ends with a space or a dot.

The refused characters are those of validateFilePath in the upload action this workflow pins,
actions/upload-artifact cf430e030ddbb5b0abf93d22962f4752f3646cd9 (v7.0.2), dist/upload/index.js,
"invalidArtifactFilePathCharacters": double quote, colon, less than, greater than, vertical bar,
asterisk, question mark, carriage return, line feed. The action checks every file path it
uploads and stops with "The path for one of the files in artifact is not valid" (CI run
43069206476). A trailing space or dot is not refused by the action but cannot be created on
Windows (NTFS naming rules: "Do not end a file or directory name with a space or a period"), so
such an artifact could not be downloaded there.

--strict additionally allows only A-Za-z0-9._- in every component (the naming rule for
self-test results). Symbolic links are reported as errors (the upload would follow them).
--allow-missing reports a DIR that does not exist and goes on (for steps that run after an
earlier failure, like the upload with if-no-files-found: warn); without it, exit 2. Exit 2 on a
usage error or when DIR exists but is not a directory.
"""
import os
import re
import sys

REFUSED = {'"': "double quote", ":": "colon", "<": "less than", ">": "greater than", "|": "vertical bar",
           "*": "asterisk", "?": "question mark", "\r": "carriage return", "\n": "line feed"}
STRICT = re.compile(r"[A-Za-z0-9._-]+")


def problems(rel, strict):
    out = []
    for ch, name in REFUSED.items():
        if ch in rel:
            out.append(f"contains a {name}")
    for comp in rel.split("/"):
        if comp.endswith(" ") or comp.endswith("."):
            out.append(f"component {comp!r} ends with a space or a dot")
        if strict and not STRICT.fullmatch(comp):
            out.append(f"component {comp!r} has characters outside A-Za-z0-9._-")
    return out


def main(argv):
    strict = allow_missing = False
    while argv and argv[0] in ("--strict", "--allow-missing"):
        strict = strict or argv[0] == "--strict"
        allow_missing = allow_missing or argv[0] == "--allow-missing"
        argv = argv[1:]
    if not argv:
        print("usage:" + __doc__.strip().splitlines()[2], file=sys.stderr)
        return 2
    bad = n = 0
    for top in argv:
        if allow_missing and not os.path.lexists(top):
            print(f"check-upload-paths: {top!r} does not exist (nothing to upload there)")
            continue
        if not os.path.isdir(top) or os.path.islink(top):
            print(f"check-upload-paths: {top!r} is not a directory", file=sys.stderr)
            return 2
        for root, dirs, files in os.walk(top):
            dirs.sort()
            for name in sorted(dirs) + sorted(files):
                p = os.path.join(root, name)
                rel = os.path.relpath(p, top).replace(os.sep, "/")
                n += 1
                errs = problems(rel, strict)
                if os.path.islink(p):
                    errs.append("is a symbolic link")
                for e in errs:
                    bad += 1
                    print(f"check-upload-paths: {top}: {rel!r} {e}")
    mode = "strict" if strict else "upload"
    print(f"check-upload-paths: {n} paths checked ({mode} rules), {bad} problems")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
