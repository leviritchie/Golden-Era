#!/usr/bin/env python3
"""Materialize source-owned Necropolis reference assets for manifest validation.

This is not a Unity bundle builder. It only prepares the faction icon/card and
map-object reference frames that the manifest and registry can resolve before
the full Necropolis payload exists.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLUGIN_ROOT = ROOT / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod"
DEFEXTRACT = ROOT / "tools" / "defextract_py3.py"
LODEXTRACT = ROOT / "tools" / "lod_extract_entry_py3.py"
H3SPRITE_LOD = ROOT / "vcmi" / "Data" / "H3sprite.lod"

HOTA_NEW_GRAPHICS = ROOT / "vcmi" / "Mods" / "hota" / "mods" / "newGraphics" / "Content" / "sprites" / "hota" / "necropolis"
HOTA_HEROES = ROOT / "vcmi" / "Mods" / "hota" / "mods" / "heroes" / "Content" / "sprites" / "hota" / "necropolis"
THIRD_UPGRADES_TOWN = ROOT / "vcmi" / "Mods" / "third-upgrades" / "content" / "sprites" / "town-screen" / "necropolis"
THIRD_UPGRADES_TOWN_CONFIG = ROOT / "vcmi" / "Mods" / "third-upgrades" / "content" / "config" / "town-screen" / "necropolis" / "factions.json"

FACTION_ICON_SOURCE = HOTA_HEROES / "heroes" / "boyd" / "icons" / "portraitLarge.png"
CITY_SOURCE = HOTA_NEW_GRAPHICS / "adventureMap" / "town" / "capitol.def"
DWELLING_SOURCE_ENTRIES = (
    "AVGskel0.def",
    "AVGzomb0.def",
    "AVGwght0.def",
    "AVGvamp0.def",
    "AVGlich0.def",
    "AVGBKNI0.def",
    "AVGbone0.def",
)

FACTION_ICON_DEST = PLUGIN_ROOT / "homm3_runtime_assets" / "faction_icons" / "homm3_necropolis"
CITY_DEST = PLUGIN_ROOT / "homm3_runtime_assets" / "map_object_refs" / "homm3_necropolis_city"
DWELLING_DEST = PLUGIN_ROOT / "homm3_runtime_assets" / "map_object_refs" / "homm3_necropolis_dwellings"
TOWN_DEST = PLUGIN_ROOT / "homm3_runtime_assets" / "town_scene_refs" / "homm3_necropolis"
BUILDING_ICON_DEST = TOWN_DEST / "building_icons"


def require_file(path: Path) -> None:
    if not path.is_file():
        raise FileNotFoundError(path)


def extract_def(source: Path, dest: Path) -> None:
    require_file(source)
    dest.mkdir(parents=True, exist_ok=True)
    subprocess.run([sys.executable, str(DEFEXTRACT), str(source), str(dest)], check=True, cwd=ROOT)


def extract_lod_def(entry: str, dest: Path) -> None:
    require_file(H3SPRITE_LOD)
    require_file(LODEXTRACT)
    tmp = ROOT / "tools" / "build_temp_homm3" / "necropolis_dwellings" / entry
    subprocess.run([sys.executable, str(LODEXTRACT), str(H3SPRITE_LOD), entry, str(tmp)], check=True, cwd=ROOT)
    extract_def(tmp, dest)


def copy_file(source: Path, dest: Path) -> None:
    require_file(source)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, dest)


def write_manifest() -> None:
    manifest = {
        "factionSid": "homm3_necropolis",
        "purpose": "Source-owned reference assets for manifest/registry validation before full Necropolis payload deployment.",
        "sources": {
            "factionIcon": str(FACTION_ICON_SOURCE.relative_to(ROOT)).replace("\\", "/"),
            "cityMapObject": str(CITY_SOURCE.relative_to(ROOT)).replace("\\", "/"),
            "dwellingMapObjects": [f"vcmi/Data/H3sprite.lod:{entry}" for entry in DWELLING_SOURCE_ENTRIES],
            "townThirdUpgradeConfig": str(THIRD_UPGRADES_TOWN_CONFIG.relative_to(ROOT)).replace("\\", "/"),
            "townThirdUpgradeSprites": str(THIRD_UPGRADES_TOWN.relative_to(ROOT)).replace("\\", "/"),
        },
        "debt": [
            "This script does not build Unity bundles, unit portraits, hero portraits, town layers, or Core.zip rows.",
            "The true HoMM3 Necropolis town backdrop still needs the same by-eye source validation performed for Tower and Fortress.",
            "Third-upgrades town-screen data is recorded for later layer/build-tree work but is not treated as a complete base-town scene.",
        ],
    }
    TOWN_DEST.mkdir(parents=True, exist_ok=True)
    (TOWN_DEST / "asset_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    require_file(DEFEXTRACT)
    require_file(LODEXTRACT)
    copy_file(FACTION_ICON_SOURCE, FACTION_ICON_DEST / "portraitLarge.png")
    extract_def(CITY_SOURCE, CITY_DEST)
    extract_def(CITY_SOURCE, TOWN_DEST)
    for entry in DWELLING_SOURCE_ENTRIES:
        extract_lod_def(entry, DWELLING_DEST)
    BUILDING_ICON_DEST.mkdir(parents=True, exist_ok=True)
    copy_file(THIRD_UPGRADES_TOWN / "ALTHALLNECR.json", BUILDING_ICON_DEST / "ALTHALLNECR.json")
    sys.path.insert(0, str(ROOT / "tools"))
    from strip_crop_map_building_billboards import process_paths

    report = process_paths(
        sorted(CITY_DEST.rglob("*.png")) + sorted(DWELLING_DEST.rglob("*.png")),
        dry_run=False,
    )
    print(
        "Necropolis map billboard strip+crop: "
        f"groups={report['groupCount']} changedFrames={report['changedFrames']} "
        f"shadowPixelsRemovedTotal={report['shadowPixelsRemovedTotal']}"
    )
    write_manifest()
    print("deployed Necropolis reference faction icon, city billboard, dwelling billboards, and town-source manifest")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
