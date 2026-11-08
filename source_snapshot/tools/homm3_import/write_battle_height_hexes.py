#!/usr/bin/env python3
"""Write HoMM3-proportional battle heights into ``OfflineUnlockMod/homm3_import.json``.

Why
---
``Homm3ImportVisuals`` used to size every owned skinned battle mesh to the renderer height
of its stock donor prefab. Donor bounds are arbitrary (the troglodyte donor made the goblin
3.8 world units tall while the orc's blade-dancer donor gave 2.6), so units were both too
big and wrongly proportioned against each other. The runtime now reads, per entry,
``battleHeightHexes`` and, per table, ``battleWorldHeightPerHex`` and fits the mesh to their
product (``FitSkinnedBattleMesh``).

What this writes
----------------
* ``battleHeightHexes`` for every entry whose unit has a lab DEF (``extracted_battle_source_12fps``
  under the installed ``homm3_lab``): median opaque-pixel body height (alpha > 128 -- HoMM3 shadow
  is alpha 64/128) of the DEF idle group (2) plates divided by the HoMM3 battlefield hex height
  (42 px). Entries without a lab DEF are left without the field (donor fit stays in force for
  them) and listed in the report.
* ``battleWorldHeightPerHex`` (top level), the single tuning knob. ``--per-hex`` sets it
  directly. ``--anchor-lab-sid`` plus ``--anchor-world-height`` sets it so that unit's
  HoMM3 idle-sprite hex height lands on a vanilla Olden Era mesh of known world height.
  The table knob is calibrated by ``measure_native_battle_height.py --write`` (median over
  stock/HoMM3 pairs of the same creature; the manifest validator pins it to that artifact),
  so the single-anchor and ``--per-hex`` options are diagnostics only. Without
  ``--anchor-world-height`` the script writes per-unit hexes from idle plates and keeps the
  existing table knob.

Proof: static/generated. The runtime fit logs one ``source=hex`` line per battle spawn so the
installed value can be read back from ``BepInEx/LogOutput.log``.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
IMPORT_TABLE = ROOT / "Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/homm3_import.json"
GOLDEN_LAB = Path(r"V:/SteamLibrary/steamapps/common/Heroes of Might and Magic Olden Era - Golden Era/BepInEx/plugins/OfflineUnlockMod/homm3_lab")
UNITS_INVENTORY = ROOT / "tools/homm3_import/units_inventory.json"
HOMM3_HEX_HEIGHT_PX = 42.0
IDLE_GROUP = 2
BODY_ALPHA_MIN = 128
HOMM3_FIRST_BODY_INDEX = 8
DEFAULT_PER_HEX = 1.3
DEFAULT_ANCHOR_LAB_SID = "h3_skeleton"


def per_hex_from_anchor(anchor_hexes: float, anchor_world_height: float) -> float:
    """World units per HoMM3 hex-height so the anchor unit matches a vanilla mesh."""
    hexes = float(anchor_hexes)
    height = float(anchor_world_height)
    if not (hexes > 0 and height > 0):
        raise ValueError(f"anchor hexes and world height must be positive, got {hexes} / {height}")
    return round(height / hexes, 6)


def sequence_json_for_unit(source: Path, unit_sid: str) -> Path:
    """Pick the HoMM3 battle DEF json for this lab SID. Extra materialized/ dirs are ignored."""
    jsons = sorted(path for path in source.glob("*.json") if path.is_file())
    if not jsons:
        raise FileNotFoundError(f"{unit_sid}: no lab DEF json under {source}")
    if len(jsons) == 1:
        return jsons[0]
    inventory = json.loads(UNITS_INVENTORY.read_text(encoding="utf-8-sig"))
    basename = None
    for row in inventory.get("units") or []:
        if row.get("unitSid") == unit_sid:
            basename = str(row.get("battleExtractBasename") or "").strip()
            break
    if not basename:
        raise ValueError(
            f"{unit_sid}: multiple DEF jsons {[path.name for path in jsons]} and units_inventory has no battleExtractBasename"
        )
    matches = [path for path in jsons if path.stem.lower() == basename.lower()]
    if len(matches) != 1:
        raise ValueError(
            f"{unit_sid}: expected one {basename}.json among {[path.name for path in jsons]}, found {[path.name for path in matches]}"
        )
    return matches[0]


def idle_frame_paths(lab_root: Path, unit_sid: str) -> tuple[list[Path], Path]:
    """Idle group-2 plates from the installed 12 fps lab DEF. Missing plates fail closed."""
    source = lab_root / unit_sid / "extracted_battle_source_12fps"
    if not source.is_dir():
        raise FileNotFoundError(f"{unit_sid}: no lab DEF under {source}")
    sequence_path = sequence_json_for_unit(source, unit_sid)
    doc = json.loads(sequence_path.read_text(encoding="utf-8-sig"))
    idle = [row for row in doc.get("sequences") or [] if int(row.get("group", -1)) == IDLE_GROUP]
    if not idle or not idle[0].get("frames"):
        raise ValueError(f"{unit_sid}: DEF {sequence_path.name} has no idle group {IDLE_GROUP}")
    frames: list[Path] = []
    for rel in idle[0]["frames"]:
        frame = source / Path(str(rel).replace("\\", "/"))
        if not frame.is_file():
            raise ValueError(f"{unit_sid}: idle plate missing {frame}")
        frames.append(frame)
    return frames, sequence_path


def body_mask(frame: Path) -> np.ndarray:
    """Opaque creature body pixels of one DEF plate.

    RGBA plates: alpha > BODY_ALPHA_MIN (HoMM3 shadow is alpha 64/128). Palette plates (raw DEF export, no
    alpha channel): palette index >= HOMM3_FIRST_BODY_INDEX, since indices 0-7 of a creature DEF palette are
    the special slots (0 transparent cyan, shadow ramps, selection outline). Reading a palette plate through
    RGBA made every pixel opaque (alpha 255 everywhere) and measured the whole 400 px canvas as the body.
    Any other mode fails closed."""
    im = Image.open(frame)
    if im.mode == "P" and "transparency" not in im.info:
        return np.asarray(im) >= HOMM3_FIRST_BODY_INDEX
    if im.mode in ("RGBA", "LA", "P", "PA"):
        return np.asarray(im.convert("RGBA"))[..., 3] > BODY_ALPHA_MIN
    raise ValueError(f"{frame}: unsupported plate mode {im.mode} (need RGBA or a HoMM3 palette plate)")


def idle_body_height_px(lab_root: Path, unit_sid: str) -> tuple[int, dict[str, Any]]:
    frames, sequence_path = idle_frame_paths(lab_root, unit_sid)
    heights: list[int] = []
    for frame in frames:
        rows = np.where(body_mask(frame).any(axis=1))[0]
        if rows.size == 0:
            raise ValueError(f"{unit_sid}: idle plate {frame.name} has no opaque body pixels")
        heights.append(int(rows.max() - rows.min() + 1))
    return int(statistics.median(heights)), {"def": sequence_path.name, "idleFrames": len(heights), "heightsPx": heights}


def lab_sid_from_prefab(prefab_asset_path: str) -> str | None:
    parts = prefab_asset_path.replace("\\", "/").split("/")
    if "homm3_lab" not in parts:
        return None
    index = parts.index("homm3_lab")
    return parts[index + 1] if index + 1 < len(parts) and parts[index + 1] else None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--table", type=Path, default=IMPORT_TABLE)
    parser.add_argument("--lab-root", type=Path, default=GOLDEN_LAB)
    parser.add_argument("--per-hex", type=float, default=None, help=f"battleWorldHeightPerHex to write (default: keep existing, else {DEFAULT_PER_HEX}).")
    parser.add_argument(
        "--anchor-lab-sid",
        default=DEFAULT_ANCHOR_LAB_SID,
        help="Lab SID whose HoMM3 idle-sprite hex height is the relative size origin (default: h3_skeleton).",
    )
    parser.add_argument(
        "--anchor-world-height",
        type=float,
        default=None,
        help="Vanilla Olden Era world height for --anchor-lab-sid. Sets battleWorldHeightPerHex = height / hexes.",
    )
    parser.add_argument("--only-prefix", default=None, help="Only entries whose battleResPath contains this (e.g. /stronghold/).")
    parser.add_argument("--report", type=Path, default=ROOT / "tools/homm3_import/battle_height_hexes_report.json")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.per_hex is not None and args.anchor_world_height is not None:
        raise ValueError("choose either --per-hex or --anchor-world-height, not both")

    table = json.loads(args.table.read_text(encoding="utf-8-sig"))
    existing = table.get("battleWorldHeightPerHex")
    per_hex = float(args.per_hex) if args.per_hex is not None else (float(existing) if existing is not None else DEFAULT_PER_HEX)
    if not per_hex > 0:
        raise ValueError(f"battleWorldHeightPerHex must be positive, got {per_hex}")
    table["battleWorldHeightPerHex"] = per_hex

    written: dict[str, Any] = {}
    skipped: dict[str, str] = {}
    for entry in table["entries"]:
        path = str(entry.get("battleResPath") or "")
        if args.only_prefix and args.only_prefix not in path:
            continue
        sid = lab_sid_from_prefab(str(entry.get("battlePrefabAssetPath") or ""))
        if sid is None:
            skipped[path] = "battlePrefabAssetPath is not a homm3_lab/<sid>/ prefab"
            entry.pop("battleHeightHexes", None)
            continue
        try:
            px, detail = idle_body_height_px(args.lab_root, sid)
        except (FileNotFoundError, ValueError) as exc:
            skipped[path] = f"{type(exc).__name__}: {exc}"
            entry.pop("battleHeightHexes", None)
            continue
        measured = round(px / HOMM3_HEX_HEIGHT_PX, 3)
        hexes = measured
        scale = entry.get("battleHeightScale")
        if scale is not None:
            # A reviewed per-line size verdict (validate_custom_faction_manifests pins the reason and the product):
            # the runtime, stride match and presentation lanes read the effective battleHeightHexes; the DEF-measured
            # value stays beside it for calibration (measure_native_battle_height reads battleHeightHexesMeasured).
            hexes = round(measured * float(scale), 3)
            entry["battleHeightHexesMeasured"] = measured
        entry["battleHeightHexes"] = hexes
        written[path] = {"labSid": sid, "idleBodyHeightPx": px, "battleHeightHexes": hexes,
                         **({"battleHeightHexesMeasured": measured, "battleHeightScale": scale} if scale is not None else {}),
                         "targetWorldHeight": round(hexes * per_hex, 3), **detail}

    anchor_sid = str(args.anchor_lab_sid or "").strip()
    anchor_rows = [row for row in written.values() if row.get("labSid") == anchor_sid] if anchor_sid else []
    if args.anchor_world_height is not None:
        if not anchor_sid:
            raise ValueError("--anchor-world-height requires --anchor-lab-sid")
        if not anchor_rows:
            raise ValueError(f"anchor {anchor_sid} has no written battleHeightHexes; cannot calibrate per-hex")
        per_hex = per_hex_from_anchor(anchor_rows[0]["battleHeightHexes"], args.anchor_world_height)
        table["battleWorldHeightPerHex"] = per_hex
        for row in written.values():
            row["targetWorldHeight"] = round(row["battleHeightHexes"] * per_hex, 3)

    report = {
        "proof": "static/generated; runtime fit logged per spawn as 'skinned fit source=hex'",
        "table": str(args.table),
        "battleWorldHeightPerHex": per_hex,
        "homm3HexHeightPx": HOMM3_HEX_HEIGHT_PX,
        "bodyAlphaMin": BODY_ALPHA_MIN,
        "anchorLabSid": anchor_sid or None,
        "anchorHexes": anchor_rows[0]["battleHeightHexes"] if anchor_rows else None,
        "anchorWorldHeight": args.anchor_world_height,
        "written": written,
        "leftOnDonorFit": skipped,
    }
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if not args.dry_run:
        args.table.write_text(json.dumps(table, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"written": len(written), "leftOnDonorFit": len(skipped), "battleWorldHeightPerHex": per_hex, "report": str(args.report), "dryRun": args.dry_run}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
