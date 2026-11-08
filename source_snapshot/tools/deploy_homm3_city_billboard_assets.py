#!/usr/bin/env python3
"""Extract source-backed HoMM3 custom town map billboard frames.

The runtime manifest contract uses these frames for map city billboards. Keep
them on the capitol/castle map-object source, not the smaller village/town DEFs.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLUGIN_ROOT = ROOT / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod"
DEFEXTRACT = ROOT / "tools" / "defextract_py3.py"
HOTA_NEW_GRAPHICS = ROOT / "vcmi" / "Mods" / "hota" / "mods" / "newGraphics" / "Content" / "sprites" / "hota"
COVE_CONTENT = ROOT / "vcmi" / "Mods" / "hota" / "mods" / "cove" / "Content" / "sprites" / "hota" / "cove"


CITY_BILLBOARD_SOURCES = {
    "homm3_castle": HOTA_NEW_GRAPHICS / "castle" / "adventureMap" / "town" / "capitol.def",
    "homm3_conflux": HOTA_NEW_GRAPHICS / "conflux" / "adventureMap" / "town" / "capitol.def",
    "homm3_dungeon": HOTA_NEW_GRAPHICS / "dungeon" / "adventureMap" / "town" / "capitol.def",
    "homm3_fortress": HOTA_NEW_GRAPHICS / "fortress" / "adventureMap" / "town" / "capitol.def",
    "homm3_inferno": HOTA_NEW_GRAPHICS / "inferno" / "adventureMap" / "town" / "capitol.def",
    "homm3_necropolis": HOTA_NEW_GRAPHICS / "necropolis" / "adventureMap" / "town" / "capitol.def",
    "homm3_rampart": HOTA_NEW_GRAPHICS / "rampart" / "adventureMap" / "town" / "capitol.def",
    "homm3_stronghold": HOTA_NEW_GRAPHICS / "stronghold" / "adventureMap" / "town" / "capitol.def",
    "homm3_tower": HOTA_NEW_GRAPHICS / "tower" / "adventureMap" / "town" / "capitol.def",
    "homm3_cove": COVE_CONTENT / "town" / "adventureMap" / "AVCcovz0.def",
}


def require_sources() -> None:
    missing = [path for path in [DEFEXTRACT, *CITY_BILLBOARD_SOURCES.values()] if not path.is_file()]
    if missing:
        raise FileNotFoundError("Missing HoMM3 city billboard source asset(s):\n" + "\n".join(str(path) for path in missing))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-sources", action="store_true", help="Only verify source DEFs exist.")
    args = parser.parse_args()

    require_sources()
    if args.check_sources:
        print("HoMM3 city billboard source assets are present")
        return 0

    sys.path.insert(0, str(ROOT / "tools"))
    from defextract_py3 import extract_def
    from strip_crop_map_building_billboards import process_paths

    processed: list[Path] = []
    for faction_sid, source in sorted(CITY_BILLBOARD_SOURCES.items()):
        dest = PLUGIN_ROOT / "homm3_runtime_assets" / "map_object_refs" / f"{faction_sid}_city"
        dest.mkdir(parents=True, exist_ok=True)
        if not extract_def(str(source), str(dest)):
            raise RuntimeError(f"Failed to extract {source}")
        processed.extend(sorted(dest.rglob("*.png")))
        print(f"{faction_sid}: extracted {source.relative_to(ROOT)}")
    report = process_paths(processed, dry_run=False)
    print(
        "city billboards strip+crop: "
        f"groups={report['groupCount']} changedFrames={report['changedFrames']} "
        f"shadowPixelsRemovedTotal={report['shadowPixelsRemovedTotal']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
