#!/usr/bin/env python3
"""Extract AB/SoD campaign-unique HoMM3 large portraits at native resolution for upscaling.

Writes PNGs (no 64x64 circular shrink) under artifacts/homm3_campaign_hero_portraits_for_upscale/
plus a manifest.json the user can follow when returning upscaled batches.
"""

from __future__ import annotations

import argparse
import json
import struct
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LOD = ROOT / "HoMM 3 Complete" / "Data" / "H3bitmap.lod"
DEFAULT_AB_LOD = ROOT / "HoMM 3 Complete" / "Data" / "H3ab_bmp.lod"
OUT_DIR = ROOT / "artifacts" / "homm3_campaign_hero_portraits_for_upscale"

# Campaign / special portraits not covered by the standard town-roster extract map.
# Planned OE SIDs are the intended wiring targets (18-cap: free 17-18 or HotA-slot replace).
CAMPAIGN_PORTRAITS: list[dict] = [
    {
        "key": "catherine",
        "name": "Catherine",
        "pcx": "hpl128qc.pcx",
        "plannedSid": "homm3_castle_hero_17",
        "faction": "castle",
        "slotPolicy": "replace_hota",
        "replaces": "Sir Mullich",
        "notes": "AB/RoE campaign queen; replaces HotA Sir Mullich in custom-game slot 17.",
    },
    {
        "key": "roland",
        "name": "Roland",
        "pcx": "hpl009sh.pcx",
        "plannedSid": "homm3_castle_hero_18",
        "faction": "castle",
        "slotPolicy": "replace_hota",
        "replaces": "Beatrice",
        "notes": "AB campaign; replaces HotA Beatrice in slot 18.",
    },
    {
        "key": "general_kendal",
        "name": "General Kendal",
        "pcx": "hpl129mk.pcx",
        "plannedSid": None,
        "faction": "castle",
        "slotPolicy": "portrait_only_no_slot",
        "replaces": None,
        "notes": "Castle is full after Catherine/Roland; portrait extracted for dialogs / future slot.",
    },
    {
        "key": "gelu",
        "name": "Gelu",
        "pcx": "hpl004sh.pcx",
        "plannedSid": "homm3_rampart_hero_17",
        "faction": "rampart",
        "slotPolicy": "add_slot",
        "replaces": None,
        "notes": "Rampart has room; custom-game slot 17.",
    },
    {
        "key": "ordwald",
        "name": "Ordwald",
        "pcx": "hpl132wl.pcx",
        "plannedSid": "homm3_rampart_hero_18",
        "faction": "rampart",
        "slotPolicy": "add_slot",
        "replaces": None,
        "notes": "Pairs with Gelu so Rampart can move 16→18 (validator requires 16 or 18).",
    },
    {
        "key": "dracon",
        "name": "Dracon",
        "pcx": "hpl003sh.pcx",
        "plannedSid": "homm3_tower_hero_17",
        "faction": "tower",
        "slotPolicy": "add_slot",
        "replaces": None,
        "notes": "Tower has room; custom-game slot 17.",
    },
    {
        "key": "xeron",
        "name": "Xeron",
        "pcx": "hpl131dm.pcx",
        "plannedSid": "homm3_inferno_hero_17",
        "faction": "inferno",
        "slotPolicy": "replace_hota",
        "replaces": "Athe",
        "notes": "AB campaign; replaces HotA Athe in slot 17. Keep Miseria as 18 unless a second campaign inferno lead is needed.",
    },
    {
        "key": "adrienne",
        "name": "Adrienne",
        "pcx": "hpl000sh.pcx",
        "plannedSid": "homm3_fortress_hero_17",
        "faction": "fortress",
        "slotPolicy": "add_slot",
        "replaces": None,
        "notes": "Fortress has room; custom-game slot 17.",
    },
    {
        "key": "kilgor",
        "name": "Kilgor",
        "pcx": "hpl005sh.pcx",
        "plannedSid": "homm3_stronghold_hero_17",
        "faction": "stronghold",
        "slotPolicy": "replace_hota",
        "replaces": "Gruezak",
        "notes": "Festival of Life; replaces HotA Gruezak in slot 17.",
    },
    {
        "key": "finneas",
        "name": "Finneas",
        "pcx": "hpl133nc.pcx",
        "plannedSid": "homm3_necropolis_hero_17",
        "faction": "necropolis",
        "slotPolicy": "replace_hota",
        "replaces": "Boyd",
        "notes": "Sandro campaign; replaces HotA Boyd in slot 17.",
    },
    {
        "key": "haart_lich",
        "name": "Haart Lich",
        "pcx": "hpl006sh.pcx",
        "plannedSid": "homm3_necropolis_hero_18",
        "faction": "necropolis",
        "slotPolicy": "replace_hota",
        "replaces": "Ranloo",
        "notes": "Campaign death knight; replaces HotA Ranloo in slot 18.",
    },
    {
        "key": "mutare",
        "name": "Mutare",
        "pcx": "hpl007sh.pcx",
        "plannedSid": "homm3_dungeon_hero_17",
        "faction": "dungeon",
        "slotPolicy": "already_wired",
        "replaces": None,
        "notes": "Already dungeon slot 17; re-extract for upscale folder consistency.",
    },
    {
        "key": "mutare_drake",
        "name": "Mutare Drake",
        "pcx": "hpl008sh.pcx",
        "plannedSid": "homm3_dungeon_hero_18",
        "faction": "dungeon",
        "slotPolicy": "already_wired",
        "replaces": None,
        "notes": "Already dungeon slot 18; re-extract for upscale folder consistency.",
    },
    {
        "key": "christian_campaign",
        "name": "Christian (campaign)",
        "pcx": "hpl002sh.pcx",
        "plannedSid": None,
        "faction": "castle",
        "slotPolicy": "portrait_only_no_slot",
        "replaces": None,
        "notes": "Campaign variant portrait; roster Christian already uses hpl006kn.",
    },
    {
        "key": "boragus_campaign",
        "name": "Boragus (campaign)",
        "pcx": "hpl001sh.pcx",
        "plannedSid": None,
        "faction": "stronghold",
        "slotPolicy": "portrait_only_no_slot",
        "replaces": None,
        "notes": "Campaign variant; roster Boragus already uses hpl100br.",
    },
    {
        "key": "gem_campaign",
        "name": "Gem (campaign)",
        "pcx": "hpl134nc.pcx",
        "plannedSid": None,
        "faction": "necropolis",
        "slotPolicy": "portrait_only_no_slot",
        "replaces": None,
        "notes": "SoD campaign Gem-as-necromancer portrait; roster Gem remains rampart.",
    },
    {
        "key": "sandro_campaign",
        "name": "Sandro (campaign)",
        "pcx": "hpl135wi.pcx",
        "plannedSid": None,
        "faction": "necropolis",
        "slotPolicy": "portrait_only_no_slot",
        "replaces": None,
        "notes": "Campaign Sandro variant; roster Sandro remains necropolis_hero_11.",
    },
    {
        "key": "yog_wizard",
        "name": "Yog the Wizard",
        "pcx": "hpl136wi.pcx",
        "plannedSid": None,
        "faction": "tower",
        "slotPolicy": "portrait_only_add_with_dracon",
        "replaces": None,
        "notes": "Pairs with Dracon so Tower can move 16→18; plannedSid assigned at extract if wiring.",
        "plannedSidIfPairing": "homm3_tower_hero_18",
    },
]


def extract_from_lod(lod_path: Path, want_name_lower: str) -> bytes | None:
    data = lod_path.read_bytes()
    if data[:4] != b"LOD\0":
        return None
    total = struct.unpack_from("<I", data, 8)[0]
    off = 92
    for _ in range(total):
        raw = data[off : off + 16]
        off += 16
        nul = raw.find(b"\x00")
        name = (raw[:nul] if nul >= 0 else raw).decode("ascii", errors="replace").lower()
        file_off, file_size, _u, file_csize = struct.unpack_from("<IIII", data, off)
        off += 16
        if name != want_name_lower:
            continue
        if file_csize and file_csize != file_size:
            blob = data[file_off : file_off + file_csize]
            try:
                blob = zlib.decompress(blob)
            except zlib.error:
                blob = data[file_off : file_off + file_size]
        else:
            blob = data[file_off : file_off + file_size]
        return blob
    return None


def decode_h3_portrait_payload(data: bytes):
    from PIL import Image

    if len(data) < 12:
        return None
    payload_len, width, height = struct.unpack_from("<III", data, 0)
    if width < 1 or width > 256 or height < 1 or height > 256:
        return None
    pixel_len = width * height
    expected = 12 + pixel_len + 768
    if payload_len != pixel_len or len(data) < expected:
        return None
    pixels = data[12 : 12 + pixel_len]
    palette = data[12 + pixel_len : 12 + pixel_len + 768]
    rgba = bytearray(pixel_len * 4)
    for i, idx in enumerate(pixels):
        po = idx * 3
        ro = i * 4
        rgba[ro] = palette[po]
        rgba[ro + 1] = palette[po + 1]
        rgba[ro + 2] = palette[po + 2]
        rgba[ro + 3] = 255
    return Image.frombytes("RGBA", (width, height), bytes(rgba))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lod", type=Path, default=DEFAULT_LOD)
    parser.add_argument("--ab-lod", type=Path, default=DEFAULT_AB_LOD)
    parser.add_argument("--out-dir", type=Path, default=OUT_DIR)
    args = parser.parse_args()
    out_dir: Path = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    lods = [p for p in (args.lod, args.ab_lod) if p.is_file()]
    if not lods:
        raise SystemExit(f"no LOD found at {args.lod} or {args.ab_lod}")

    entries = []
    for row in CAMPAIGN_PORTRAITS:
        pcx = str(row["pcx"]).lower()
        blob = None
        used = None
        for lod in lods:
            blob = extract_from_lod(lod, pcx)
            if blob is not None:
                used = lod
                break
        if blob is None:
            entries.append({**row, "ok": False, "error": f"pcx not found: {pcx}"})
            print(f"MISS {row['key']} {pcx}")
            continue
        img = decode_h3_portrait_payload(blob)
        if img is None:
            entries.append({**row, "ok": False, "error": "decode failed"})
            print(f"FAIL decode {row['key']}")
            continue
        planned = row.get("plannedSid") or row.get("plannedSidIfPairing")
        filename = f"{row['key']}__{pcx.replace('.pcx', '')}.png"
        if planned:
            filename = f"{planned}__{row['key']}.png"
        out_path = out_dir / filename
        img.save(out_path, "PNG")
        entries.append(
            {
                **row,
                "ok": True,
                "png": str(out_path.relative_to(ROOT)).replace("\\", "/"),
                "sourceSize": list(img.size),
                "lod": str(used.relative_to(ROOT)).replace("\\", "/") if used else None,
                "plannedSid": planned,
            }
        )
        print(f"OK {row['key']} {img.size} -> {out_path.name}")

    readme = out_dir / "README.txt"
    readme.write_text(
        "\n".join(
            [
                "HoMM3 campaign hero portraits for upscaling",
                "==========================================",
                "",
                "These are native-resolution decodes from H3bitmap.lod / H3ab_bmp.lod.",
                "They are NOT the 64x64 circular plugin portraits.",
                "",
                "When returning upscales, keep the filename stem (before extension) stable",
                "or map via manifest.json plannedSid / key fields.",
                "",
                "Target import path after upscale:",
                "  Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/homm3_hero_portraits_upscaled/",
                "via tools/import_homm3_upscaled_hero_portraits.py (or a campaign-batch follow-up).",
                "",
            ]
        ),
        encoding="utf-8",
    )
    manifest = {
        "schema": "homm3.campaign_hero_portraits_for_upscale.v1",
        "outDir": str(out_dir.relative_to(ROOT)).replace("\\", "/"),
        "entries": entries,
        "ok": sum(1 for e in entries if e.get("ok")),
        "failed": sum(1 for e in entries if not e.get("ok")),
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": manifest["ok"], "failed": manifest["failed"], "out": str(out_dir)}, indent=2))
    return 0 if manifest["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
