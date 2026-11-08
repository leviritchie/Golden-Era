#!/usr/bin/env python3
"""Extract a single named file from a Heroes III / VCMI .lod archive (binary mode)."""

from __future__ import annotations

import struct
import sys
import zlib
from pathlib import Path


def extract_entry(lod_path: Path, want_name: str, out_path: Path) -> bool:
    want = want_name.lower().encode("ascii")
    data = lod_path.read_bytes()
    if data[:4] != b"LOD\0":
        print("not an LOD file", file=sys.stderr)
        return False
    total, = struct.unpack_from("<I", data, 8)
    off = 92
    files: list[tuple[bytes, int, int, int]] = []
    for _ in range(total):
        raw = data[off : off + 16]
        off += 16
        nul = raw.find(b"\0")
        name = (raw[:nul] if nul >= 0 else raw).lower()
        o, size, _u, csize = struct.unpack_from("<IIII", data, off)
        off += 16
        files.append((name, o, size, csize))

    for name, o, size, csize in files:
        if name != want:
            continue
        blob = data[o : o + csize] if csize else data[o : o + size]
        if csize:
            blob = zlib.decompress(blob)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(blob)
        return True
    print("entry not found:", want_name, file=sys.stderr)
    return False


def main() -> int:
    if len(sys.argv) != 4:
        print(
            "usage: lod_extract_entry_py3.py <file.lod> <entry.def> <outfile.def>",
            file=sys.stderr,
        )
        return 1
    ok = extract_entry(Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3]))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
