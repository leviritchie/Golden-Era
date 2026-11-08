#!/usr/bin/env python3
"""Extract/copy source-backed HoMM3 Inferno reference assets.

This script owns only the Inferno reference-pack scaffold. It intentionally does
not generate release Core rows or Unity bundles.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLUGIN_ROOT = ROOT / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod"
DEFEXTRACT = ROOT / "tools" / "defextract_py3.py"
LODEXTRACT = ROOT / "tools" / "lod_extract_entry_py3.py"
H3SPRITE_LOD = ROOT / "vcmi" / "Data" / "H3sprite.lod"

FACTION_ICON_SOURCE = ROOT / "vcmi" / "Mods" / "vcmi-extras" / "Mods" / "bonusIcons" / "mods" / "Bonus Icons" / "Content" / "data" / "zvs" / "Lib1.res" / "inferno2.png"
TEMP_TOWN_CARD_SOURCE = ROOT / "vcmi" / "Mods" / "third-upgrades" / "Mods" / "tow-comp" / "content" / "data" / "infernoHallBg.PNG"
CITY_DEF_SOURCE = ROOT / "vcmi" / "Mods" / "hota" / "mods" / "newGraphics" / "Content" / "sprites" / "hota" / "inferno" / "adventureMap" / "town" / "capitol.def"

DWELLING_DEF_ENTRIES = (
    "AVGimp0.def",
    "AVGgogs0.def",
    "AVGhell0.def",
    "AVGDEMN0.def",
    "AVGpit0.def",
    "AVGefre0.def",
    "AVGdevl0.def",
)


def require_sources() -> None:
    missing = [
        path
        for path in [FACTION_ICON_SOURCE, TEMP_TOWN_CARD_SOURCE, CITY_DEF_SOURCE, DEFEXTRACT, LODEXTRACT, H3SPRITE_LOD]
        if not path.is_file()
    ]
    if missing:
        raise FileNotFoundError("Missing Inferno source assets:\n" + "\n".join(str(path) for path in missing))


def extract_lod_def(entry: str, dest: Path) -> None:
    tmp = ROOT / "tools" / "build_temp_homm3" / "inferno_dwellings" / entry
    subprocess.run([sys.executable, str(LODEXTRACT), str(H3SPRITE_LOD), entry, str(tmp)], check=True, cwd=ROOT)
    sys.path.insert(0, str(ROOT / "tools"))
    from defextract_py3 import extract_def

    if not extract_def(str(tmp), str(dest)):
        raise RuntimeError(f"Failed to extract {entry} from {H3SPRITE_LOD}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-sources", action="store_true", help="Only verify source assets exist.")
    args = parser.parse_args()

    require_sources()
    if args.check_sources:
        print("Inferno source assets are present")
        return 0

    sys.path.insert(0, str(ROOT / "tools"))
    from defextract_py3 import extract_def

    faction_icon_dir = PLUGIN_ROOT / "homm3_runtime_assets" / "faction_icons" / "homm3_inferno"
    town_scene_dir = PLUGIN_ROOT / "homm3_runtime_assets" / "town_scene_refs" / "homm3_inferno"
    city_dir = PLUGIN_ROOT / "homm3_runtime_assets" / "map_object_refs" / "homm3_inferno_city"
    dwelling_dir = PLUGIN_ROOT / "homm3_runtime_assets" / "map_object_refs" / "homm3_inferno_dwellings"
    for directory in (faction_icon_dir, town_scene_dir, city_dir, dwelling_dir):
        directory.mkdir(parents=True, exist_ok=True)

    shutil.copy2(FACTION_ICON_SOURCE, faction_icon_dir / "Icon_Faction_Inferno.png")
    shutil.copy2(TEMP_TOWN_CARD_SOURCE, town_scene_dir / "Inferno-in-background.png")
    if not extract_def(str(CITY_DEF_SOURCE), str(city_dir)):
        raise RuntimeError(f"Failed to extract {CITY_DEF_SOURCE}")
    for entry in DWELLING_DEF_ENTRIES:
        extract_lod_def(entry, dwelling_dir)

    from strip_crop_map_building_billboards import process_paths

    report = process_paths(sorted(city_dir.rglob("*.png")) + sorted(dwelling_dir.rglob("*.png")), dry_run=False)
    print(
        "Inferno map billboard strip+crop: "
        f"groups={report['groupCount']} changedFrames={report['changedFrames']} "
        f"shadowPixelsRemovedTotal={report['shadowPixelsRemovedTotal']}"
    )
    print("Inferno reference assets deployed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
