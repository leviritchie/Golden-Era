#!/usr/bin/env python3
"""
Extract animated HoMM3 Stronghold town building DEFs from H3sprite.lod
and produce frame PNGs + an animation metadata JSON for the runtime C# player.

Output:
  layers/anims/
    metadata.json     — maps layer_id → { frames: [relative paths], frameRateMs: int }
    <layer_id>/       — one subfolder per animated building
      00_00.png, 00_01.png, ...
"""

import argparse
import glob
import json
import os
import shutil
import struct
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LOD_PATH = ROOT / "HoMM 3 Complete" / "Data" / "H3sprite.lod"
DEFAULT_OUT_DIR = ROOT / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod" / "homm3_runtime_assets" / "town_scene_refs" / "homm3_stronghold" / "layers" / "anims"
TMP_DIR = ROOT / "tools" / "_stranim_tmp"

# Map building SID → layer ID (the string used in positions.json / layer PNGs)
BUILDING_SID_TO_LAYER = {
    "Build_Main": "extraCapitol",       # Town Hall / Capitol chain (levels 1-4)
    "Build_Tier_1": "dwellingUp2Lvl1",
    "Build_Tier_2": "dwellingUp2Lvl2",
    "Build_Tier_3": "dwellingUp2Lvl3",
    "Build_Tier_4": "dwellingUp2Lvl4",
    "Build_Tier_5": "dwellingUp2Lvl5",
    "Build_Tier_6": "dwellingUp2Lvl6",
    "Build_Tier_7": "dwellingUp2Lvl7",
    "Build_Tavern": "tavern",
    "Build_Market": "market",
    "Build_Artifact_Market": "artifactMarket",
    "Build_Magic_Guild": "magicGuild",
    "Build_Bank": "bank",
    "Build_Treasury": "treasury",
    "Build_Resource_Depot": "resourceDepot",
    "Build_Resource_Depot_level_2": "resourceDepotLevel2",
    "Build_Wall": "wall",
    "Build_Gymnasium": "gymnasium",
    "Build_Lyceum": "lyceum",
    "Build_Spy_Network": "spyNetwork",
    # Horde buildings use their own layer IDs from positions.json
    "Build_Horde_1": "horde1",
    "Build_Horde_2": "horde2",
    # Upgrade buildings re-use the dwelling layer IDs with level suffix
    "Build_Tier_1_upgrade": "dwellingUp2Lvl1",
    "Build_Tier_2_upgrade": "dwellingUp2Lvl2",
    "Build_Tier_3_upgrade": "dwellingUp2Lvl3",
    "Build_Tier_4_upgrade": "dwellingUp2Lvl4",
    "Build_Tier_5_upgrade": "dwellingUp2Lvl5",
    "Build_Tier_6_upgrade": "dwellingUp2Lvl6",
    "Build_Tier_7_upgrade": "dwellingUp2Lvl7",
    # Holy/Grail building maps to treasury (closest equivalent)
    "Build_Holy": "treasury",
}

# Map HoMM3 DEF names → (building SID, level).
# Level is the HoMM3 building level, NOT the tier.
# For Hall chain: 1=Village Hall, 2=Town Hall, 3=City Hall, 4=Capitol.
TBST_DEF_TO_SID_LEVEL = {
    "TBStBlak": (None, None),             # Blacksmith — not a visible layer
    "TBStCas2": (None, None),             # Citadel — not a visible layer
    "TBStCas3": (None, None),             # Castle — not a visible layer
    "TBStCstl": (None, None),             # Capitol (fortification) — not a visible layer
    "TBStDw_0": ("Build_Tier_1", 1),
    "TBStDw_1": ("Build_Tier_2", 2),
    "TBStDw_2": ("Build_Tier_3", 3),
    "TBStDw_3": ("Build_Tier_4", 4),
    "TBStDw_4": ("Build_Tier_5", 5),
    "TBStDw_5": ("Build_Tier_6", 6),
    "TBStDw_6": ("Build_Tier_7", 7),
    "TBStExt0": (None, None),             # Exterior views — not building layers
    "TBStExt1": (None, None),
    "TBStExt2": (None, None),
    "TBStExt3": (None, None),
    "TBStHal2": ("Build_Main", 2),         # Town Hall — Build_Main level 2 (20 frames)
    "TBStHal3": ("Build_Main", 3),         # City Hall — Build_Main level 3 (20 frames)
    "TBStHal4": ("Build_Main", 4),         # Capitol — Build_Main level 4 (20 frames)
    "TBStHall": ("Build_Main", 1),         # Village Hall — Build_Main level 1 (20 frames)
    "TBStHoly": ("Build_Holy", 1),          # Hall of Valhalla (Grail building, 10 frames)
    "TBStHrd1": ("Build_Horde_1", 1),       # Horde level 1
    "TBStHrd2": ("Build_Horde_2", 1),       # Horde level 2
    "TBStMag2": ("Build_Magic_Guild", 2),
    "TBStMag3": ("Build_Magic_Guild", 3),
    "TBStMage": ("Build_Magic_Guild", 1),
    "TBStMark": ("Build_Market", 1),
    "TBStSilo": ("Build_Resource_Depot", 1),
    "TBStSpec": ("Build_Lyceum", 1),        # Escape Tunnel (20 frames)
    "TBStTvrn": ("Build_Tavern", 1),
    "TBStUp_0": ("Build_Tier_1_upgrade", 1),
    "TBStUp_1": ("Build_Tier_2_upgrade", 2),
    "TBStUp_2": ("Build_Tier_3_upgrade", 3),
    "TBStUp_3": ("Build_Tier_4_upgrade", 4),
    "TBStUp_4": ("Build_Tier_5_upgrade", 5),
    "TBStUp_5": ("Build_Tier_6_upgrade", 6),  # 10 frames
    "TBStUp_6": ("Build_Tier_7_upgrade", 7),  # 10 frames
}

# Frame rate: HoMM3 town building animations typically run at ~10 FPS.
FRAME_RATE_MS = 100


def list_lod_entries(lod_path):
    """Return {upper_name: (offset, size)} for all entries in a LOD file."""
    data = lod_path.read_bytes()
    total, = struct.unpack_from("<I", data, 8)
    off = 92
    entries = {}
    for i in range(total):
        entry_off = off + i * 32
        raw = data[entry_off : entry_off + 16]
        nul = raw.find(b"\0")
        name = (raw[:nul] if nul >= 0 else raw).decode("ascii", "ignore")
        entry_offset, entry_size, _u, csize = struct.unpack_from("<IIII", data, entry_off + 16)
        entries[name.upper()] = (entry_offset, entry_size)
    return entries


def extract_def(lod_path, def_name, out_def_path):
    """Use lod_extract_entry_py3.py to pull a single DEF from the LOD."""
    script = ROOT / "tools" / "lod_extract_entry_py3.py"
    result = subprocess.run(
        [sys.executable, str(script), str(lod_path), def_name, str(out_def_path)],
        capture_output=True, text=True, cwd=str(ROOT),
    )
    if result.returncode != 0:
        print(f"  ERROR extracting {def_name}: {result.stderr.strip()}")
        return False
    return True


def defextract(def_path, out_dir):
    """Use defextract_py3.py to extract frames from a DEF into a directory."""
    script = ROOT / "tools" / "defextract_py3.py"
    out_dir.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [sys.executable, str(script), str(def_path), str(out_dir)],
        capture_output=True, text=True, cwd=str(ROOT),
    )
    if result.returncode != 0:
        print(f"  ERROR def-extracting {def_path.name}: {result.stderr.strip()}")
        return False
    return True


def resolve_output_key(def_basename):
    """
    Given a DEF basename like 'TBStHal2', return the output key for the metadata.
    Format: layerId[_level] — e.g. 'extraCapitol_2' for level 2 Capitol.
    Uses the layer-level key so the C# runtime can look up animations per-building-per-level.
    """
    # Try exact match first, then case-insensitive
    info = TBST_DEF_TO_SID_LEVEL.get(def_basename)
    if info is None:
        # Case-insensitive fallback
        upper = def_basename.upper()
        for k, v in TBST_DEF_TO_SID_LEVEL.items():
            if k.upper() == upper:
                info = v
                break
    if info is None or info[0] is None:
        return None
    sid, lvl = info
    layer_id = BUILDING_SID_TO_LAYER.get(sid)
    if layer_id is None:
        return None
    # Always include level if present, so animations are per-level.
    # The C# runtime will look up {layer_id}_{level} first, then fall back to just {layer_id}.
    return f"{layer_id}_{lvl}" if lvl is not None else layer_id


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lod", type=Path, default=DEFAULT_LOD_PATH, help="Path to H3sprite.lod")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT_DIR, help="Output layers/anims directory")
    args = parser.parse_args()
    lod_path = args.lod
    out_dir = args.out

    print("=== Stronghold Town Building Animation Extractor ===")
    print(f"LOD: {lod_path}")
    print(f"Output: {out_dir}")

    if not lod_path.exists():
        print(f"ERROR: LOD not found at {lod_path}", file=sys.stderr)
        sys.exit(1)

    # 1. List all TBSt* entries
    print("\n[1/4] Listing LOD entries...")
    entries = list_lod_entries(lod_path)
    tbst_names = sorted([n for n in entries if n.upper().startswith("TBST")])
    print(f"  Found {len(tbst_names)} TBSt entries")

    # 2. Extract each DEF
    print("\n[2/4] Extracting DEFs from LOD...")
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    extracted_defs = []
    for name in tbst_names:
        def_basename = name.replace(".DEF", "")
        def_out = TMP_DIR / f"{def_basename}.def"
        if not def_out.exists():
            print(f"  Extracting {name}...")
            if not extract_def(lod_path, name, def_out):
                continue
        else:
            print(f"  {name} already extracted (cached)")
        extracted_defs.append(def_basename)

    # 3. Def-extract each to PNGs
    print("\n[3/4] Extracting frames from DEFs...")
    metadata = {}
    for def_basename in sorted(extracted_defs):
        def_path = TMP_DIR / f"{def_basename}.def"
        def_out_dir = TMP_DIR / f"{def_basename}_out"

        json_path = def_out_dir / f"{def_basename}.json"
        if json_path.exists():
            print(f"  {def_basename}: already extracted (cached)")
        else:
            print(f"  {def_basename}: extracting...")
            if not defextract(def_path, def_out_dir):
                continue

        try:
            with open(json_path) as f:
                meta = json.load(f)
        except Exception as e:
            print(f"  WARNING: could not read JSON for {def_basename}: {e}")
            continue

        seqs = meta.get("sequences", [])
        if not seqs:
            print(f"  {def_basename}: no sequences, skipping")
            continue

        frame_count = len(seqs[0]["frames"])
        print(f"  {def_basename}: {frame_count} frames (type={meta.get('type')})")

        if frame_count <= 1:
            print(f"    -> single frame, no animation needed (skipping metadata entry)")
            # Still copy to output for reference but don't add to anim metadata
            continue

        output_key = resolve_output_key(def_basename)
        if output_key is None:
            print(f"    -> no layer mapping for {def_basename}, skipping")
            continue

        # Copy frame PNGs to output directory
        dest_dir = out_dir / output_key
        dest_dir.mkdir(parents=True, exist_ok=True)

        # Clear existing frames
        for old in glob.glob(str(dest_dir / "frame_*.png")):
            os.remove(old)

        # Determine output directory for DEF frames
        frames_dir = def_out_dir / f"{def_basename}.dir"
        frame_list = []
        # Find all PNG files in the frames dir and sort them
        png_files = sorted(frames_dir.glob("*.png"))
        # Map original frame paths → output filenames
        seq_frames = seqs[0]["frames"]
        for i, rel_path in enumerate(seq_frames):
            # rel_path is like "TBStHal2.dir\\00_00.png"
            src_name = Path(rel_path).name  # "00_00.png"
            dest_name = f"frame_{i:02d}.png"
            src = frames_dir / src_name
            dest = dest_dir / dest_name
            if src.exists():
                shutil.copy2(src, dest)
                frame_list.append(dest_name)
            else:
                print(f"    WARNING: frame missing: {src}")

        metadata[output_key] = {
            "frameCount": len(frame_list),
            "frames": frame_list,
            "frameRateMs": FRAME_RATE_MS,
        }
        print(f"    -> output: {output_key}/ ({len(frame_list)} frames)")

    # 4. Write metadata JSON (JArray format for IL2CPP-safe C# parsing).
    print("\n[4/4] Writing metadata.json...")
    out_dir.mkdir(parents=True, exist_ok=True)
    meta_path = out_dir / "metadata.json"
    meta_array = []
    for key, info in sorted(metadata.items()):
        entry = {"id": key, "frameRateMs": info["frameRateMs"], "frames": info["frames"]}
        meta_array.append(entry)
    with open(meta_path, "w") as f:
        json.dump(meta_array, f, indent=2)

    print(f"\nDone! Wrote {len(meta_array)} animated entries to {meta_path}")
    for entry in meta_array:
        print(f"  {entry['id']}: {len(entry['frames'])} frames @ {entry['frameRateMs']}ms")


if __name__ == "__main__":
    main()
