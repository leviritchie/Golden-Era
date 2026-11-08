#!/usr/bin/env python3
"""Pin Hex.GameScenes.EScene unused cityGnome field name to cityFactory on a frozen install.

Renames the IL2CPP metadata field name (same ordinal) so Core sceneName=cityFactory
parses natively. Does not add a new enum ordinal; reuses the spare city slot.

Proof label after apply: installed/payload (metadata). Not runtime town-open proof.

Usage:
  python tools/pin_escene_city_factory.py --game-root "V:/SteamLibrary/.../Golden Era"
  python tools/pin_escene_city_factory.py --game-root ... --dry-run
"""
from __future__ import annotations

import argparse
import shutil
import struct
import sys
from pathlib import Path

SANITY = 0xFAB11BAF
VERSION = 31
OLD_NAME = b"cityGnome"
NEW_NAME = b"cityFactory"
# Il2CppGlobalMetadataHeader: index 0=sanity, 1=version, then (offset, size) uint32 pairs
# from index 2 to the end of the header. The header length is not hard-coded: the first
# section (stringLiteral) starts right after the header, so the header holds
# stringLiteralOffset / 4 uint32 values. On v31 that is 64 (pairs at 2..62).
#
# History: this used to be range(2, 60, 2), which skipped the windowsRuntimeStrings (60) and
# exportedTypeDefinitions (62) pairs. exportedTypeDefinitions is non-empty (10784 B) on both
# Golden Era and build 25061458, so a pin made by the old code left that section's offset
# 12 bytes short. The Golden Era install pinned on 2026-07-22 carries that stale offset.
MIN_HEADER_U32 = 58  # sanity + version + 28 pairs; smaller is not a v31 header


def header_offset_indices(raw: bytes | bytearray) -> list[int]:
    first_section = read_u32(raw, 2 * 4)
    if first_section % 8 or first_section // 4 < MIN_HEADER_U32 or first_section > 4096:
        raise SystemExit(f"implausible metadata header length {first_section} bytes")
    return list(range(2, first_section // 4, 2))


def header_sections(raw: bytes | bytearray) -> list[tuple[int, int, int]]:
    return [(i, read_u32(raw, i * 4), read_u32(raw, i * 4 + 4)) for i in header_offset_indices(raw)]


def verify_section_layout(
    old: bytes, new: bytes, *, string_idx: int, fields_idx: int, field_rel: int, insert_len: int
) -> None:
    """Every header section must hold the same bytes after the pin, except the two it edits."""
    olds = header_sections(old)
    news = header_sections(new)
    if [s[0] for s in olds] != [s[0] for s in news]:
        raise SystemExit("header layout changed length; refuse write")
    for (idx, o_off, o_size), (_, n_off, n_size) in zip(olds, news):
        if idx == string_idx:
            if n_off != o_off or n_size != o_size + insert_len:
                raise SystemExit("string heap header wrong after pin; refuse write")
            if new[n_off : n_off + o_size] != old[o_off : o_off + o_size]:
                raise SystemExit("string heap prefix changed; refuse write")
            continue
        if n_size != o_size:
            raise SystemExit(f"header pair {idx} size changed; refuse write")
        if o_size == 0:
            continue
        a = old[o_off : o_off + o_size]
        b = new[n_off : n_off + n_size]
        if idx == fields_idx:
            a = a[:field_rel] + a[field_rel + 4 :]
            b = b[:field_rel] + b[field_rel + 4 :]
        if a != b:
            raise SystemExit(f"header pair {idx} section bytes moved or changed after pin; refuse write")


def read_u32(buf: bytes | bytearray, off: int) -> int:
    return struct.unpack_from("<I", buf, off)[0]


def write_u32(buf: bytearray, off: int, value: int) -> None:
    struct.pack_into("<I", buf, off, value)


def pin_metadata(meta_path: Path, dry_run: bool) -> dict:
    original = meta_path.read_bytes()
    raw = bytearray(original)
    if read_u32(raw, 0) != SANITY:
        raise SystemExit(f"bad metadata sanity at {meta_path}")
    if read_u32(raw, 4) != VERSION:
        raise SystemExit(f"unsupported metadata version {read_u32(raw, 4)} (want {VERSION})")

    string_offset = read_u32(raw, 6 * 4)
    string_size = read_u32(raw, 7 * 4)
    fields_offset = read_u32(raw, 24 * 4)
    fields_size = read_u32(raw, 25 * 4)

    heap = original[string_offset : string_offset + string_size]

    def heap_hits(name: bytes) -> list[int]:
        # Whole NUL-terminated heap entries only; a suffix of a longer name does not count.
        hits, start = [], 0
        while (i := heap.find(name + b"\x00", start)) >= 0:
            if i == 0 or heap[i - 1] == 0:
                hits.append(i)
            start = i + 1
        return hits

    old_hits = heap_hits(OLD_NAME)
    if not old_hits:
        # Already pinned?
        if heap_hits(NEW_NAME):
            return {"status": "already_pinned", "meta": str(meta_path)}
        raise SystemExit(f"{OLD_NAME.decode()} string not found in metadata string heap")
    if len(old_hits) != 1:
        raise SystemExit(f"expected 1 heap string {OLD_NAME.decode()}, found {len(old_hits)}")
    old_name_index = old_hits[0]

    field_size = 12
    if fields_size % field_size:
        raise SystemExit(f"fieldsSize {fields_size} not divisible by {field_size}")

    field_hits: list[int] = []
    for i in range(fields_size // field_size):
        off = fields_offset + i * field_size
        if read_u32(raw, off) == old_name_index:
            field_hits.append(off)
    if len(field_hits) != 1:
        raise SystemExit(f"expected 1 FieldDefinition named cityGnome, found {len(field_hits)}")

    insert_at = string_offset + string_size  # == eventsOffset on this build
    insert_blob = NEW_NAME + b"\x00"
    insert_len = len(insert_blob)
    new_name_index = string_size  # offset within string heap after append

    report = {
        "status": "would_pin" if dry_run else "pinned",
        "meta": str(meta_path),
        "old_name_index": old_name_index,
        "new_name_index": new_name_index,
        "field_def_offset": field_hits[0],
        "insert_at": insert_at,
        "insert_len": insert_len,
        "ordinal_unchanged": True,
        "note": "EScene ordinal for former cityGnome stays the same; only the name becomes cityFactory.",
    }
    if dry_run:
        return report

    backup = meta_path.with_suffix(meta_path.suffix + ".bak_escene_cityFactory")
    if not backup.exists():
        shutil.copy2(meta_path, backup)
        report["backup"] = str(backup)

    # Grow string heap: insert at end of string section, shift the rest of the file.
    raw[insert_at:insert_at] = insert_blob
    write_u32(raw, 7 * 4, string_size + insert_len)

    # Bump every header offset that points at or after the insertion point.
    for idx in header_offset_indices(raw):
        # stringOffset (idx 6) is unchanged (its size was grown above); stringLiteral* (2, 4)
        # sit before the string heap.
        if idx in (2, 4, 6):
            continue
        off = idx * 4
        value = read_u32(raw, off)
        if value >= insert_at:
            write_u32(raw, off, value + insert_len)

    # Field table shifted; relocate hit.
    new_fields_offset = read_u32(raw, 24 * 4)
    delta = new_fields_offset - fields_offset
    field_off = field_hits[0] + delta
    if read_u32(raw, field_off) != old_name_index:
        raise SystemExit("field nameIndex mismatch after shift; refuse write")
    write_u32(raw, field_off, new_name_index)

    # Verify new string
    verify_off = read_u32(raw, 6 * 4) + new_name_index
    if raw[verify_off : verify_off + len(insert_blob)] != insert_blob:
        raise SystemExit("post-pin string verify failed")
    verify_section_layout(
        original,
        bytes(raw),
        string_idx=6,
        fields_idx=24,
        field_rel=field_hits[0] - fields_offset,
        insert_len=insert_len,
    )
    report["layout_verified"] = (
        "every header section byte-identical except the string heap tail and one field nameIndex"
    )

    tmp = meta_path.with_suffix(meta_path.suffix + ".cityFactory_new")
    tmp.write_bytes(raw)
    try:
        tmp.replace(meta_path)
    except OSError:
        # Windows may lock the live file while the game is open; leave the pinned file beside it.
        report["status"] = "pinned_pending_replace"
        report["pending_path"] = str(tmp)
        report["error"] = (
            f"could not replace live metadata (is the game running?). "
            f"Quit the game, then: move /Y \"{tmp}\" \"{meta_path}\""
        )
        print("WARN", report["error"], file=sys.stderr)
        return report

    report["field_def_offset_after"] = field_off
    report["meta_size"] = len(raw)
    return report


def pin_interop_hex(hex_dll: Path, dry_run: bool) -> dict:
    """Rename managed enum field UTF-8 literal cityGnome -> cityFactory via equal-table PE #Strings expand.

    Interop Hex.dll stores the name as a single UTF-8 ECMA string. Length differs, so we
    replace the 9-char name with an 11-char name only if we find a dedicated padded slot;
    otherwise we leave interop as cityGnome and rely on ordinal cast in the mod
    (native metadata is authoritative for game Enum.Parse).
    """
    if not hex_dll.is_file():
        return {"status": "skip", "reason": "missing Hex.dll", "path": str(hex_dll)}
    data = hex_dll.read_bytes()
    if data.count(OLD_NAME) == 0 and data.count(NEW_NAME) >= 1:
        return {"status": "already_pinned", "path": str(hex_dll)}
    if data.count(OLD_NAME) != 1:
        return {
            "status": "skip_interop_rename",
            "reason": f"utf8 cityGnome count={data.count(OLD_NAME)} (want 1); mod must use ordinal",
            "path": str(hex_dll),
        }
    # Length mismatch: do not corrupt PE heaps with a naive replace.
    return {
        "status": "skip_interop_rename",
        "reason": "cityFactory is longer than cityGnome; native metadata pin is enough; mod uses EScene ordinal",
        "path": str(hex_dll),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--game-root", type=Path, required=True)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    root = args.game_root
    meta = root / "HeroesOldenEra_Data" / "il2cpp_data" / "Metadata" / "global-metadata.dat"
    if not meta.is_file():
        print(f"FAIL missing {meta}", file=sys.stderr)
        return 1
    hex_dll = root / "BepInEx" / "interop" / "Hex.dll"
    report = pin_metadata(meta, args.dry_run)
    interop = pin_interop_hex(hex_dll, args.dry_run)
    print("metadata:", report)
    print("interop:", interop)
    if report.get("status") in {"pinned", "already_pinned", "would_pin", "pinned_pending_replace"}:
        print("OK EScene name pin path ready (ordinal preserved).")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
