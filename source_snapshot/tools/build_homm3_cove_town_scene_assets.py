#!/usr/bin/env python3
"""Build Cove town-screen layers and build-tree icons from local HotA sources.

Cove is HotA-owned content, so this script deliberately uses
vcmi/Mods/hota/mods/cove/Content instead of HoMM3 Complete LOD fallbacks.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from PIL import Image

from prebake_homm3_town_scene_coordinates import prebake_mockup, prebake_positions_file


ROOT = Path(__file__).resolve().parents[1]
PLUGIN_ROOT = ROOT / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod"
TOWN_ROOT = PLUGIN_ROOT / "homm3_runtime_assets" / "town_scene_refs" / "homm3_cove"
SOURCE_BG = ROOT / "vcmi" / "Mods" / "hota" / "mods" / "cove" / "Content" / "data" / "hota" / "cove" / "town" / "background.png"
COVE_CONTENT = ROOT / "vcmi" / "Mods" / "hota" / "mods" / "cove" / "Content"
STRUCTURES_JSON = COVE_CONTENT / "config" / "hota" / "cove" / "town" / "structures.json"
TOWN_JSON = COVE_CONTENT / "config" / "hota" / "cove" / "town" / "town.json"
BUILDING_DEF_ROOT = COVE_CONTENT / "sprites" / "hota" / "cove" / "town" / "buildings"
TOWNHALL_ICON_ROOT = COVE_CONTENT / "sprites" / "hota" / "cove" / "town" / "townhall"
TOWNHALL_ICON_JSON = COVE_CONTENT / "sprites" / "hota" / "cove" / "town" / "townhall.json"
DEF_EXTRACT = ROOT / "tools" / "defextract_py3.py"

MOCKUP = TOWN_ROOT / "mockups" / "homm3_cove_background_mock_1920x1080.png"
LAYERS_DIR = TOWN_ROOT / "layers"
ANIMS_DIR = LAYERS_DIR / "anims"
POSITIONS_JSON = LAYERS_DIR / "positions.json"
BUILDING_LAYER_MAP_JSON = LAYERS_DIR / "building_layer_map.json"
BUILDING_ICONS_DIR = TOWN_ROOT / "building_icons" / "townhall.dir"
BUILDING_ICON_SOURCE_MAP = TOWN_ROOT / "building_icons" / "townhall_source_map.json"

SOURCE_SIZE = (800, 374)
FRAME_RATE_MS = 100

HALL_SLOT_TO_OLDEN: dict[str, tuple[str, int]] = {
    "villageHall": ("Build_Main", 1),
    "townHall": ("Build_Main", 2),
    "cityHall": ("Build_Main", 3),
    "capitol": ("Build_Main", 4),
    "fort": ("Build_Wall", 1),
    "citadel": ("Build_Wall", 2),
    "castle": ("Build_Wall", 3),
    "tavern": ("Build_Tavern", 1),
    "blacksmith": ("Build_Treasury", 1),
    "marketplace": ("Build_Market", 1),
    "resourceSilo": ("Build_Resource_Depot", 1),
    "mageGuild1": ("Build_Magic_Guild", 1),
    "mageGuild2": ("Build_Magic_Guild", 2),
    "mageGuild3": ("Build_Magic_Guild", 3),
    "mageGuild4": ("Build_Magic_Guild", 4),
    "special3": ("Build_Bank", 1),
    "shipyard": ("Build_Artifact_Market", 1),
    "horde1Upgr": ("Build_Resource_Depot_level_2", 1),
    "special4": ("Build_Mother_Nature", 1),
    "dwellingLvl1": ("Build_Tier_1", 1),
    "dwellingUpLvl1": ("Build_Tier_1", 2),
    "dwellingLvl2": ("Build_Tier_2", 1),
    "dwellingUpLvl2": ("Build_Tier_2", 2),
    "dwellingLvl3": ("Build_Tier_3", 1),
    "dwellingUpLvl3": ("Build_Tier_3", 2),
    "dwellingUp2Lvl3": ("Build_Tier_3", 3),
    "dwellingLvl4": ("Build_Tier_4", 1),
    "dwellingUpLvl4": ("Build_Tier_4", 2),
    "dwellingLvl5": ("Build_Tier_5", 1),
    "dwellingUpLvl5": ("Build_Tier_5", 2),
    "dwellingLvl6": ("Build_Tier_6", 1),
    "dwellingUpLvl6": ("Build_Tier_6", 2),
    "dwellingLvl7": ("Build_Tier_7", 1),
    "dwellingUpLvl7": ("Build_Tier_7", 2),
}

HALL_SLOT_ICON_FRAME_ID: dict[str, int] = {
    # Cove's HotA townhall.json stores files as 1.png, 2.png, ... but the
    # semantic building ids follow the same frame ids VCMI registers.
    "mageGuild1": 0,
    "mageGuild2": 1,
    "mageGuild3": 2,
    "mageGuild4": 3,
    "tavern": 5,
    "shipyard": 6,
    "fort": 7,
    "citadel": 8,
    "castle": 9,
    "villageHall": 10,
    "townHall": 11,
    "cityHall": 12,
    "capitol": 13,
    "marketplace": 14,
    "resourceSilo": 15,
    "blacksmith": 16,
    "horde1": 18,
    "horde1Upgr": 19,
    "special3": 22,
    "special4": 23,
    "horde2": 24,
    "horde2Upgr": 25,
    "dwellingLvl1": 30,
    "dwellingLvl2": 31,
    "dwellingLvl3": 32,
    "dwellingLvl4": 33,
    "dwellingLvl5": 34,
    "dwellingLvl6": 35,
    "dwellingLvl7": 36,
    "dwellingUpLvl1": 37,
    "dwellingUpLvl2": 38,
    "dwellingUpLvl3": 39,
    "dwellingUpLvl4": 40,
    "dwellingUpLvl5": 41,
    "dwellingUpLvl6": 42,
    "dwellingUpLvl7": 43,
    "dwellingUp2Lvl3": 46,
}

LAYER_SOURCE_CROSSWALK = {
    "Build_Treasury": "Cove Blacksmith/Cannon Yard visual from blacksmith; retained donor economy SID.",
    "Build_Bank": "Cove Thieves' Guild visual from special3; retained donor special-building SID.",
    "Build_Artifact_Market": "Cove Shipyard visual from shipyard; retained donor artifact-market SID.",
    "Build_Mother_Nature": "Cove Grotto visual from special4; retained donor special-building SID.",
    "Build_Resource_Depot_level_2": "Cove Pub horde-upgrade visual from horde1Upgr; retained donor resource-upgrade SID.",
}


def strip_json_comments(text: str) -> str:
    text = re.sub(r"//.*", "", text)
    return re.sub(r"/\*.*?\*/", "", text, flags=re.S)


def load_jsonc(path: Path) -> Any:
    return json.loads(strip_json_comments(path.read_text(encoding="utf-8-sig")))


def relative(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT)).replace("\\", "/")
    except ValueError:
        return str(path)


def write_text_if_changed(path: Path, text: str) -> bool:
    if path.is_file() and path.read_text(encoding="utf-8") == text:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return True


def find_case_insensitive_file(path: Path) -> Path:
    if path.is_file():
        return path
    parent = path.parent
    if not parent.is_dir():
        raise FileNotFoundError(path)
    wanted = path.name.lower()
    for candidate in parent.iterdir():
        if candidate.is_file() and candidate.name.lower() == wanted:
            return candidate
    raise FileNotFoundError(path)


def source_def_path(animation: str) -> Path:
    normalized = animation.replace("\\", "/")
    name = Path(normalized).name
    if not Path(name).suffix:
        name += ".DEF"
    return find_case_insensitive_file(BUILDING_DEF_ROOT / name)


def extract_def(def_path: Path, temp_root: Path) -> tuple[dict[str, Any], list[Path]]:
    if not DEF_EXTRACT.is_file():
        raise RuntimeError(f"missing DEF extraction helper: {DEF_EXTRACT}")
    temp_root.mkdir(parents=True, exist_ok=True)
    subprocess.run([sys.executable, str(DEF_EXTRACT), str(def_path), str(temp_root)], check=True)
    manifest_path = temp_root / (def_path.stem.lower() + ".json")
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    frame_paths: list[Path] = []
    for seq in data.get("sequences") or []:
        for frame in seq.get("frames") or []:
            path = temp_root / frame.replace("\\", "/")
            if path.is_file():
                frame_paths.append(path)
    if not frame_paths:
        frames_dir = temp_root / (def_path.stem.lower() + ".dir")
        frame_paths = sorted(frames_dir.glob("*.png"))
    if not frame_paths:
        raise RuntimeError(f"{def_path}: no extracted PNG frames")
    return data, frame_paths


def transparent_sprite(src: Image.Image) -> Image.Image:
    rgba = src.convert("RGBA")
    bg = rgba.getpixel((0, 0))[:3]
    pixels = rgba.load()
    for y in range(rgba.height):
        for x in range(rgba.width):
            r, g, b, a = pixels[x, y]
            if a == 0 or (r, g, b) == bg:
                pixels[x, y] = (r, g, b, 0)
    return rgba


def layer_id_from_animation(animation: str) -> str:
    return Path(animation.replace("\\", "/")).name.lower()


def flatten_hall_slots(hall_slots: Any) -> list[str]:
    result: list[str] = []

    def walk(value: Any) -> None:
        if isinstance(value, str):
            result.append(value)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(hall_slots)
    return result


def load_townhall_icon_frame_files() -> dict[int, str]:
    doc = load_jsonc(TOWNHALL_ICON_JSON)
    frames: dict[int, str] = {}
    for row in doc.get("images") or []:
        if not isinstance(row, dict):
            continue
        frame = row.get("frame")
        file_name = row.get("file")
        if isinstance(frame, int) and isinstance(file_name, str):
            frames[frame] = file_name
    if not frames:
        raise RuntimeError(f"{TOWNHALL_ICON_JSON}: no frame image entries")
    return frames


def load_town_sources() -> tuple[dict[str, Any], dict[str, Any]]:
    structures_doc = load_jsonc(STRUCTURES_JSON)
    town_doc = load_jsonc(TOWN_JSON)
    structures = structures_doc["cove"]["town"]["structures"]
    town = town_doc["cove"]["town"]
    return structures, town


def check_sources() -> None:
    for path in (SOURCE_BG, STRUCTURES_JSON, TOWN_JSON, DEF_EXTRACT, BUILDING_DEF_ROOT, TOWNHALL_ICON_ROOT, TOWNHALL_ICON_JSON):
        if not path.exists():
            raise FileNotFoundError(path)
    structures, town = load_town_sources()
    missing: list[str] = []
    for key, entry in structures.items():
        animation = entry.get("animation")
        if isinstance(animation, str) and animation.startswith("hota/cove/town/buildings/"):
            try:
                source_def_path(animation)
            except FileNotFoundError as ex:
                missing.append(f"{key}: {ex}")
    icon_frame_files = load_townhall_icon_frame_files()
    for slot in flatten_hall_slots(town.get("hallSlots")):
        frame_id = HALL_SLOT_ICON_FRAME_ID.get(slot)
        if frame_id is None:
            continue
        file_name = icon_frame_files.get(frame_id)
        if not file_name:
            missing.append(f"townhall icon frame {frame_id} missing for {slot}")
            continue
        if not (TOWNHALL_ICON_ROOT / file_name).is_file():
            missing.append(f"townhall icon file {file_name} missing for {slot} frame {frame_id}")
    if missing:
        raise RuntimeError("missing Cove town source(s): " + "; ".join(missing))


def build_mockup() -> None:
    prebake_mockup(SOURCE_BG, MOCKUP)


def build_layers() -> None:
    structures, _town = load_town_sources()
    LAYERS_DIR.mkdir(parents=True, exist_ok=True)
    if ANIMS_DIR.exists():
        shutil.rmtree(ANIMS_DIR)
    ANIMS_DIR.mkdir(parents=True, exist_ok=True)

    layers: list[dict[str, Any]] = []
    anim_metadata: list[dict[str, Any]] = []
    order = 0
    with tempfile.TemporaryDirectory(prefix="homm3-cove-town-defs-") as tmp:
        for structure, entry in structures.items():
            animation = entry.get("animation")
            if not isinstance(animation, str) or not animation.startswith("hota/cove/town/buildings/"):
                continue
            def_path = source_def_path(animation)
            layer_id = layer_id_from_animation(animation)
            _manifest, frame_paths = extract_def(def_path, Path(tmp) / layer_id)
            frames = [transparent_sprite(Image.open(path)) for path in frame_paths]
            sprite_name = f"{layer_id}.png"
            frames[0].save(LAYERS_DIR / sprite_name, optimize=True)
            if len(frames) > 1:
                anim_dir = ANIMS_DIR / layer_id
                anim_dir.mkdir(parents=True, exist_ok=True)
                frame_names = []
                for index, frame in enumerate(frames):
                    frame_name = f"frame_{index:02d}.png"
                    frame.save(anim_dir / frame_name, optimize=True)
                    frame_names.append(frame_name)
                anim_metadata.append(
                    {
                        "id": layer_id,
                        "frameRateMs": FRAME_RATE_MS,
                        "frames": frame_names,
                    }
                )

            layers.append(
                {
                    "id": layer_id,
                    "structure": structure,
                    "x": int(entry.get("x", 0)),
                    "y": int(entry.get("y", 0)),
                    "z": int(entry.get("z", 0)),
                    "order": order,
                    "sprite": sprite_name,
                    "source": relative(def_path),
                    "hidden": bool(entry.get("hidden", False)),
                }
            )
            order += 1

    positions = {
        "_comment": "Cove top-left layer positions on the native 800x374 HotA town canvas, sourced from vcmi/Mods/hota/mods/cove/Content/config/hota/cove/town/structures.json.",
        "source": relative(STRUCTURES_JSON),
        "canvas_w": SOURCE_SIZE[0],
        "canvas_h": SOURCE_SIZE[1],
        "layers": sorted(layers, key=lambda row: (row["z"], row["order"])),
    }
    write_text_if_changed(POSITIONS_JSON, json.dumps(positions, indent=2) + "\n")
    prebake_positions_file(POSITIONS_JSON)
    write_text_if_changed(ANIMS_DIR / "metadata.json", json.dumps(anim_metadata, indent=2) + "\n")


def build_building_layer_map() -> None:
    structures, _town = load_town_sources()
    mapping: dict[str, str] = {}
    level_entries: dict[str, dict[int, str]] = {}
    for source_slot, (building_sid, level) in HALL_SLOT_TO_OLDEN.items():
        entry = structures.get(source_slot)
        if not isinstance(entry, dict):
            continue
        animation = entry.get("animation")
        if not isinstance(animation, str):
            continue
        layer_id = layer_id_from_animation(animation)
        level_entries.setdefault(building_sid, {})[level] = layer_id

    for building_sid, levels in level_entries.items():
        first_level = min(levels)
        mapping[building_sid] = levels[first_level]

    doc = {
        "_comment": "Cove visual mapping. Keys are this worktree's Olden Era building SIDs; values are HotA Cove layer roots from positions.json. Runtime can append the constructed level when matching level-specific files.",
        "buildingLayerIds": mapping,
        "levels": {key: {str(level): value for level, value in sorted(levels.items())} for key, levels in sorted(level_entries.items())},
        "sourceCrosswalk": LAYER_SOURCE_CROSSWALK,
    }
    write_text_if_changed(BUILDING_LAYER_MAP_JSON, json.dumps(doc, indent=2) + "\n")


def build_icons() -> None:
    _structures, town = load_town_sources()
    hall_slots = flatten_hall_slots(town.get("hallSlots"))
    icon_frame_files = load_townhall_icon_frame_files()
    BUILDING_ICONS_DIR.mkdir(parents=True, exist_ok=True)
    for frame_id, file_name in sorted(icon_frame_files.items()):
        source = TOWNHALL_ICON_ROOT / file_name
        if not source.is_file():
            raise FileNotFoundError(source)
        dest_name = f"00_{frame_id:02d}.png"
        shutil.copy2(source, BUILDING_ICONS_DIR / dest_name)

    icon_source_map: dict[str, dict[str, str]] = {}
    for slot in hall_slots:
        if slot not in HALL_SLOT_TO_OLDEN:
            continue
        frame_id = HALL_SLOT_ICON_FRAME_ID.get(slot)
        if frame_id is None:
            continue
        if frame_id not in icon_frame_files:
            raise RuntimeError(f"Cove townhall icon frame {frame_id} missing for {slot}")
        building_sid, level = HALL_SLOT_TO_OLDEN[slot]
        icon_source_map.setdefault(building_sid, {})[str(level)] = f"00_{frame_id:02d}.png"

    if "Build_Magic_Guild" in icon_source_map and "4" in icon_source_map["Build_Magic_Guild"]:
        icon_source_map["Build_Magic_Guild"]["5"] = icon_source_map["Build_Magic_Guild"]["4"]

    mapped_slots = set(HALL_SLOT_TO_OLDEN)
    source_map = {
        "_comment": "Cove build-tree icon indices follow VCMI/HotA building frame IDs from townhall.json, not hallSlots index order.",
        "vcmiTownConfig": relative(TOWN_JSON),
        "vcmiTownhallIcons": relative(TOWNHALL_ICON_JSON),
        "folder": "townhall.dir",
        "unmappedHallSlots": [slot for slot in hall_slots if slot not in mapped_slots],
        "map": icon_source_map,
    }
    write_text_if_changed(BUILDING_ICON_SOURCE_MAP, json.dumps(source_map, indent=2) + "\n")


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-sources", action="store_true", help="Validate source paths without writing assets.")
    args = parser.parse_args()

    check_sources()
    if args.check_sources:
        print("HoMM3 Cove town scene sources are present.")
        return 0
    build_mockup()
    build_layers()
    build_building_layer_map()
    build_icons()
    print(f"HoMM3 Cove town scene assets generated under {TOWN_ROOT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
