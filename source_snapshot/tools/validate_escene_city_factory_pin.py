#!/usr/bin/env python3
"""Validate frozen-install EScene cityFactory metadata pin.

Fails if global-metadata.dat does not bind the former cityGnome FieldDefinition
name index to the string cityFactory (same ordinal ownership).
"""
from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path

SANITY = 0xFAB11BAF


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--game-root", type=Path, required=True)
    ap.add_argument(
        "--strict-layout",
        action="store_true",
        help="Also require the header sections to tile the file without overlap and end at EOF. "
        "A pin made by the pre-2026-09-29 tool fails this (it left the exportedTypeDefinitions "
        "offset 12 bytes short). Golden Era was re-pinned on 2026-09-29 and passes; the build "
        "passes this flag.",
    )
    args = ap.parse_args()
    meta = args.game_root / "HeroesOldenEra_Data" / "il2cpp_data" / "Metadata" / "global-metadata.dat"
    if not meta.is_file():
        print(f"FAIL missing {meta}")
        return 1
    b = meta.read_bytes()
    if struct.unpack_from("<I", b, 0)[0] != SANITY:
        print("FAIL bad metadata sanity")
        return 1
    string_offset = struct.unpack_from("<I", b, 6 * 4)[0]
    string_size = struct.unpack_from("<I", b, 7 * 4)[0]
    fields_offset = struct.unpack_from("<I", b, 24 * 4)[0]
    fields_size = struct.unpack_from("<I", b, 25 * 4)[0]
    factory_off = b.find(b"cityFactory\x00", string_offset, string_offset + string_size)
    if factory_off < 0:
        print("FAIL cityFactory string missing from metadata string heap (run tools/pin_escene_city_factory.py)")
        return 1
    name_index = factory_off - string_offset
    hits = 0
    for i in range(fields_size // 12):
        off = fields_offset + i * 12
        if struct.unpack_from("<I", b, off)[0] == name_index:
            hits += 1
    if hits != 1:
        print(f"FAIL expected 1 FieldDefinition named cityFactory, found {hits}")
        return 1
    if args.strict_layout:
        # Header pairs run from u32 index 2 to the first section (the header's own length).
        header_u32 = struct.unpack_from("<I", b, 2 * 4)[0] // 4
        sections = sorted(
            (struct.unpack_from("<I", b, i * 4)[0], struct.unpack_from("<I", b, i * 4 + 4)[0], i)
            for i in range(2, header_u32, 2)
        )
        cursor = header_u32 * 4
        for off, size, idx in sections:
            if off < cursor and size:
                print(f"FAIL header pair {idx} section at {off} overlaps previous section end {cursor}")
                return 1
            cursor = max(cursor, off + size)
        if cursor != len(b):
            print(
                f"FAIL metadata sections end at {cursor} but the file is {len(b)} bytes; a header offset "
                "was not moved by the pin (the pre-2026-09-29 pin tool skipped pairs 60 and 62)"
            )
            return 1
        print(f"OK strict layout: {len(sections)} header sections tile the file without overlap")
    print(
        "OK EScene cityFactory metadata pin: string heap + exactly one FieldDefinition nameIndex "
        f"(ordinal ownership of former cityGnome slot)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
