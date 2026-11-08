#!/usr/bin/env python3
"""Bake HoMM3 G*_BG campaign hub maps to Olden StoryHub 1080p canvas (1920x1080).

Writes plugin-deployable PNGs under OfflineUnlockMod/homm3_storyhub_maps/.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "experiments" / "campaign_port_poc"))

from storyhub_map_background import (  # noqa: E402
    DEFAULT_HUBS,
    SOURCE_HEIGHT,
    SOURCE_WIDTH,
    TARGET_HEIGHT,
    TARGET_WIDTH,
    bake_prefix_to_path,
    fail,
    output_filename,
)

DEFAULT_VISUAL_DIR = (
    ROOT
    / "artifacts"
    / "campaign_port_poc"
    / "roe_castle_campaign"
    / "storyhub_visual"
)
DEFAULT_OUT_DIR = (
    ROOT
    / "Heroes of Might & Magic Olden Era Playtest"
    / "OfflineUnlockMod"
    / "homm3_storyhub_maps"
)
# Complete H3bitmap.lod carries RoE + Specter + AB/SoD *_BG PCX; HD Edition LOD
# only has the seven RoE stems and cannot bake SP_BG / AR_BG / ….
DEFAULT_LOD = ROOT / "HoMM 3 Complete" / "Data" / "H3bitmap.lod"
FALLBACK_LOD = ROOT / "vcmi" / "Data" / "H3bitmap.lod"
REPORT_DIR = (
    ROOT
    / "artifacts"
    / "campaign_port_poc"
    / "roe_castle_campaign"
    / "storyhub_map_background_bake"
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--prefix",
        action="append",
        dest="prefixes",
        help="Background prefix to bake (e.g. G1_BG). Repeatable. Default: all DEFAULT_HUBS values.",
    )
    parser.add_argument("--visual-dir", type=Path, default=DEFAULT_VISUAL_DIR)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--lod", type=Path, default=DEFAULT_LOD)
    parser.add_argument(
        "--no-lod",
        action="store_true",
        help="Do not fall back to H3BITMAP.LOD when a PNG is missing under --visual-dir.",
    )
    args = parser.parse_args()

    prefixes = list(args.prefixes) if args.prefixes else sorted(set(DEFAULT_HUBS.values()))
    if len(prefixes) != len(set(prefixes)):
        fail(
            "DEFAULT_HUBS / --prefix list must use distinct BG stems "
            f"(collisions: {[p for p in prefixes if prefixes.count(p) > 1]})"
        )
    lod_path = None if args.no_lod else args.lod
    if lod_path is not None and not lod_path.is_file():
        if FALLBACK_LOD.is_file():
            lod_path = FALLBACK_LOD
        else:
            # Prefer PNG-only when LOD is absent; fail later per missing prefix.
            lod_path = None

    outputs: list[dict[str, object]] = []
    for prefix in prefixes:
        prefix = str(prefix).strip().upper()
        if not prefix.endswith("_BG"):
            fail(f"prefix must look like G1_BG, got {prefix!r}")
        out_path = bake_prefix_to_path(
            prefix=prefix,
            storyhub_visual_dir=args.visual_dir,
            out_dir=args.out_dir,
            lod_path=lod_path,
        )
        outputs.append(
            {
                "prefix": prefix,
                "output": str(out_path.relative_to(ROOT)).replace("\\", "/"),
                "bytes": out_path.stat().st_size,
                "size": [TARGET_WIDTH, TARGET_HEIGHT],
            }
        )
        print(f"baked {prefix} -> {out_path}")

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report = {
        "schema": "homm3.storyhub_map_background_bake.v1",
        "generatedAtUtc": datetime.now(timezone.utc).isoformat(),
        "sourceSize": [SOURCE_WIDTH, SOURCE_HEIGHT],
        "targetSize": [TARGET_WIDTH, TARGET_HEIGHT],
        "pipeline": "crop_right_black_panel -> nearest_x2 -> center_crop_height -> center_in_middle_2_3_of_1920x1080",
        "sourceMapWidth": 456,
        "safeContentWidth": 1280,
        "safeContentLeft": 320,
        "mapPasteX": 504,
        "hubSidByPrefix": {v: k for k, v in DEFAULT_HUBS.items()},
        "outputs": outputs,
        "proofBoundary": "generated-artifact; runtime MapImage swap unvalidated until live StoryHub open",
    }
    report_path = REPORT_DIR / "bake_report.v1.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
