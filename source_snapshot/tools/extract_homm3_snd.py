#!/usr/bin/env python3
"""
HoMM3 Heroes3.snd / HotA_lng.snd extractor (same layout as VCMI CArchiveLoader::initSNDArchive).

Index: uint32 fileCount, then per entry: char name[40], int32 offset, int32 size.
Each extracted blob is a RIFF WAVE (often IMA ADPCM mono 22050 Hz).
"""
from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path


def read_index(snd_path: Path) -> list[tuple[str, int, int]]:
    data = snd_path.read_bytes()
    if len(data) < 48:
        raise SystemExit(f"too small: {snd_path}")
    (n,) = struct.unpack_from("<I", data, 0)
    pos = 4
    out: list[tuple[str, int, int]] = []
    for _ in range(n):
        if pos + 48 > len(data):
            raise SystemExit(f"truncated index at {pos} (declared {n} files)")
        raw = data[pos : pos + 40]
        name = raw.split(b"\x00", 1)[0].decode("ascii", "replace")
        off, size = struct.unpack_from("<ii", data, pos + 40)
        out.append((name, off, size))
        pos += 48
    return out


def cmd_list(args: argparse.Namespace) -> None:
    for name, off, sz in read_index(Path(args.snd)):
        print(f"{name}\t{off}\t{sz}")


def cmd_extract(args: argparse.Namespace) -> None:
    snd = Path(args.snd)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    data = snd.read_bytes()
    index = {name: (off, sz) for name, off, sz in read_index(snd)}
    want = args.names
    if not want:
        raise SystemExit("pass at least one NAME, or use --all")
    if args.all:
        want = sorted(index.keys())
    for name in want:
        if name not in index:
            print(f"missing: {name}", file=sys.stderr)
            continue
        off, sz = index[name]
        if off < 0 or sz <= 0 or off + sz > len(data):
            print(f"bad span: {name} off={off} sz={sz}", file=sys.stderr)
            continue
        blob = data[off : off + sz]
        if len(blob) < 12 or blob[:4] != b"RIFF":
            print(f"warn: {name} does not start with RIFF", file=sys.stderr)
        dest = out_dir / f"{name}.wav"
        dest.write_bytes(blob)
        print(dest)


def main() -> None:
    ap = argparse.ArgumentParser(description="Extract HoMM3 .snd audio archives")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser("list", help="list NAME offset size")
    p_list.add_argument("snd", type=str)
    p_list.set_defaults(func=cmd_list)

    p_ex = sub.add_parser("extract", help="extract named entries as .wav")
    p_ex.add_argument("snd", type=str)
    p_ex.add_argument("out_dir", type=str)
    p_ex.add_argument("names", nargs="*", help="logical names e.g. PIKEATTK")
    p_ex.add_argument("--all", action="store_true", help="extract every entry")
    p_ex.set_defaults(func=cmd_extract)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
