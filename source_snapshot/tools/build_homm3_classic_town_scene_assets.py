#!/usr/bin/env python3
"""Build HoMM3 classic town-screen layers and build-tree icons.

Builders keep source placements in native HoMM3/VCMI top-left coordinates.
tools/prebake_homm3_town_scene_coordinates.py adds runtime reference rects
and the 1920x1080 black-plate mockup used by the town renderer.
"""

from __future__ import annotations

import argparse
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
TOWN_REFS = PLUGIN_ROOT / "homm3_runtime_assets" / "town_scene_refs"
H3SPRITE_LOD = ROOT / "vcmi" / "Data" / "H3sprite.lod"
LOD_EXTRACT = ROOT / "tools" / "lod_extract_entry_py3.py"
DEF_EXTRACT = ROOT / "tools" / "defextract_py3.py"
THIRD_ROOT = ROOT / "vcmi" / "Mods" / "third-upgrades" / "content"

SOURCE_SIZE = (800, 374)
FRAME_RATE_MS = 100

COMMON_ICON_FRAME_ID_BY_SLOT = {
    "mageGuild1": 0,
    "mageGuild2": 1,
    "mageGuild3": 2,
    "mageGuild4": 3,
    "mageGuild5": 4,
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
    "special1": 17,
    "horde1": 18,
    "horde1Upgr": 19,
    "ship": 20,
    "special2": 21,
    "special3": 22,
    "special4": 23,
    "horde2": 24,
    "horde2Upgr": 25,
    "grail": 26,
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
    "dwellingUp2Lvl1": 44,
    "dwellingUp2Lvl2": 45,
    "dwellingUp2Lvl3": 46,
    "dwellingUp2Lvl4": 47,
    "dwellingUp2Lvl5": 48,
    "dwellingUp2Lvl6": 49,
    "dwellingUp2Lvl7": 50,
}


BASE_STRUCTURES: dict[str, dict[str, dict[str, Any]]] = {
    "dungeon": {
        "mageGuild1": {"animation": "TBDNMAGE.def", "x": 164, "y": 119, "z": -1},
        "mageGuild2": {"animation": "TBDNMAG2.def", "x": 164, "y": 97, "z": -1},
        "mageGuild3": {"animation": "TBDNMAG3.def", "x": 164, "y": 77, "z": -1},
        "mageGuild4": {"animation": "TBDNMAG4.def", "x": 164, "y": 61, "z": -1},
        "mageGuild5": {"animation": "TBDNMAG5.def", "x": 164, "y": 15, "z": -1},
        "tavern": {"animation": "TBDNTVRN.def", "x": 211, "y": 297},
        "fort": {"animation": "TBDNCSTL.def", "x": 363, "y": 87, "z": 2},
        "citadel": {"animation": "TBDNCAS2.def", "x": 363, "y": 87, "z": 2},
        "castle": {"animation": "TBDNCAS3.def", "x": 363, "y": 87, "z": 2},
        "villageHall": {"animation": "TBDNHALL.def", "x": 0, "y": 234},
        "townHall": {"animation": "TBDNHAL2.def", "x": 0, "y": 223},
        "cityHall": {"animation": "TBDNHAL3.def", "x": 0, "y": 223},
        "capitol": {"animation": "TBDNHAL4.def", "x": 0, "y": 203},
        "marketplace": {"animation": "TBDNMARK.def", "x": 590, "y": 318, "z": -2},
        "resourceSilo": {"animation": "TBDNSILO.def", "x": 624, "y": 335, "z": 1},
        "blacksmith": {"animation": "TBDNBLAK.def", "x": 544, "y": 248, "z": -3},
        "special1": {"animation": "TBDNSPEC.def", "x": 746, "y": 294, "z": 1},
        "horde1": {"animation": "TBDNHRD1.def", "x": 0, "y": 326, "z": 2, "hidden": True},
        "horde1Upgr": {"animation": "TBDNHRD2.def", "x": 0, "y": 300, "z": 2, "hidden": True, "builds": "horde1"},
        "special2": {"animation": "TBDNEXT0.def", "x": 131, "y": 26},
        "special3": {"animation": "TBDNEXT1.def", "x": 687, "y": 177},
        "special4": {"animation": "TBDNEXT2.def", "x": 313, "y": 298},
        "grail": {"animation": "TBDNHOLY.def", "x": 562, "y": 24, "z": 1},
        "extraCapitol": {"animation": "TBDGEXT5.def", "x": 60, "y": 110, "z": 0, "third": True},
        "dwellingLvl1": {"animation": "TBDNDW_0.def", "x": 0, "y": 326, "z": 2},
        "dwellingLvl2": {"animation": "TBDNDW_1.def", "x": 0, "y": 26},
        "dwellingLvl3": {"animation": "TBDNDW_2.def", "x": 118, "y": 308, "z": 1},
        "dwellingLvl4": {"animation": "TBDNDW_3.def", "x": 300, "y": 29, "z": -1},
        "dwellingLvl5": {"animation": "TBDNDW_4.def", "x": 551, "y": 186, "z": 1},
        "dwellingLvl6": {"animation": "TBDNDW_5.def", "x": 270, "y": 253, "z": -1},
        "dwellingLvl7": {"animation": "TBDNDW_6.def", "x": 550, "y": 0, "z": -1},
        "dwellingUpLvl1": {"animation": "TBDNUP_0.def", "x": 0, "y": 300, "z": 2},
        "dwellingUpLvl2": {"animation": "TBDNUP_1.def", "x": 0, "y": 26},
        "dwellingUpLvl3": {"animation": "TBDNUP_2.def", "x": 118, "y": 256, "z": 1},
        "dwellingUpLvl4": {"animation": "TBDNUP_3.def", "x": 300, "y": 29, "z": -1},
        "dwellingUpLvl5": {"animation": "TBDNUP_4.def", "x": 519, "y": 172, "z": 1},
        "dwellingUpLvl6": {"animation": "TBDNUP_5.def", "x": 270, "y": 253, "z": -1},
        "dwellingUpLvl7": {"animation": "TBDNUP_6.def", "x": 550, "y": 0, "z": -1},
    },
    "necropolis": {
        "extraAnimation": {"animation": "TBNCEXT2.def", "x": 25, "y": 279, "z": 9},
        "mageGuild1": {"animation": "TBNCMAGE.def", "x": 341, "y": 116, "z": -1},
        "mageGuild2": {"animation": "TBNCMAG2.def", "x": 341, "y": 97, "z": -1},
        "mageGuild3": {"animation": "TBNCMAG3.def", "x": 341, "y": 78, "z": -1},
        "mageGuild4": {"animation": "TBNCMAG4.def", "x": 340, "y": 62, "z": -1},
        "mageGuild5": {"animation": "TBNCMAG5.def", "x": 343, "y": 35, "z": -1},
        "tavern": {"animation": "TBNCTVRN.def", "x": 508, "y": 189, "z": 0},
        "shipyard": {"animation": "TBNCDOCK.def", "x": 617, "y": 265, "z": -2},
        "fort": {"animation": "TBNCCSTL.def", "x": 138, "y": 66, "z": 0},
        "citadel": {"animation": "TBNCCAS2.def", "x": 139, "y": 66, "z": 0},
        "castle": {"animation": "TBNCCAS3.def", "x": 34, "y": 18, "z": 0},
        "villageHall": {"animation": "TBNCHALL.def", "x": 468, "y": 76, "z": -2},
        "townHall": {"animation": "TBNCHAL2.def", "x": 482, "y": 56, "z": -2},
        "cityHall": {"animation": "TBNCHAL3.def", "x": 478, "y": 26, "z": -2},
        "capitol": {"animation": "TBNCHAL4.def", "x": 481, "y": 26, "z": -2},
        "marketplace": {"animation": "TBNCMARK.def", "x": 347, "y": 215, "z": 2},
        "resourceSilo": {"animation": "TBNCSILO.def", "x": 276, "y": 185, "z": 1},
        "blacksmith": {"animation": "TBNCBLAK.def", "x": 382, "y": 252, "z": 7},
        "special1": {"animation": "TBNCSPEC.def", "x": 18, "y": 0, "z": -1},
        "horde1": {"animation": "TBNCHRD1.def", "x": 80, "y": 222, "z": 5, "hidden": True},
        "horde1Upgr": {"animation": "TBNCHRD2.def", "x": 64, "y": 222, "z": 5, "hidden": True},
        "ship": {"animation": "TBNCBOAT.def", "x": 617, "y": 265, "z": -2, "hidden": True},
        "special2": {"animation": "TBNCEXT0.def", "x": 307, "y": 61, "z": -2},
        "special3": {"animation": "TBNCEXT1.def", "x": 247, "y": 275, "z": 4},
        "grail": {"animation": "TBNCHOLY.def", "x": 410, "y": 88, "z": 0},
        "extraTownHall": {"animation": "TBNCEXT3.def", "x": 0, "y": 241, "z": 6},
        "extraCityHall": {"animation": "TBNCEXT4.def", "x": 321, "y": 255, "z": 6},
        "extraCapitol": {"animation": "TBNCEXT5.def", "x": 475, "y": 257, "z": 6},
        "dwellingLvl1": {"animation": "TBNCDW_0.def", "x": 80, "y": 222, "z": 5},
        "dwellingLvl2": {"animation": "TBNCDW_1.def", "x": 502, "y": 223, "z": 1},
        "dwellingLvl3": {"animation": "TBNCDW_2.def", "x": 0, "y": 187, "z": 8},
        "dwellingLvl4": {"animation": "TBNCDW_3.def", "x": 607, "y": 212, "z": 2},
        "dwellingLvl5": {"animation": "TBNCDW_4.def", "x": 206, "y": 207, "z": 3},
        "dwellingLvl6": {"animation": "TBNCDW_5.def", "x": 0, "y": 31, "z": -2},
        "dwellingLvl7": {"animation": "TBNCDW_6.def", "x": 663, "y": 25, "z": 0},
        "dwellingUpLvl1": {"animation": "TBNCUP_0.def", "x": 64, "y": 222, "z": 5},
        "dwellingUpLvl2": {"animation": "TBNCUP_1.def", "x": 498, "y": 224, "z": 1},
        "dwellingUpLvl3": {"animation": "TBNCUP_2.def", "x": 0, "y": 179, "z": 8},
        "dwellingUpLvl4": {"animation": "TBNCUP_3.def", "x": 615, "y": 193, "z": 2},
        "dwellingUpLvl5": {"animation": "TBNCUP_4.def", "x": 222, "y": 171, "z": 3},
        "dwellingUpLvl6": {"animation": "TBNCUP_5.def", "x": 0, "y": 30, "z": -2},
        "dwellingUpLvl7": {"animation": "TBNCUP_6.def", "x": 662, "y": 23, "z": 0},
    },
}

LAYER_ALIASES: dict[str, dict[str, str]] = {
    "villageHall": "main_1 townHall_2 cityHall_3 capitol_4".split(),
}

STRUCTURE_TO_LAYER: dict[str, str] = {
    "villageHall": "hall",
    "townHall": "hall_2",
    "cityHall": "hall_3",
    "capitol": "hall_4",
    "fort": "cstl",
    "citadel": "cstl_2",
    "castle": "cstl_3",
    "mageGuild1": "mage",
    "mageGuild2": "mage_2",
    "mageGuild3": "mage_3",
    "mageGuild4": "mage_4",
    "mageGuild5": "mage_5",
    "dwellingLvl1": "dw_0",
    "dwellingUpLvl1": "dw_0_2",
    "dwellingUp2Lvl1": "dw_0_3",
    "dwellingLvl2": "dw_1",
    "dwellingUpLvl2": "dw_1_2",
    "dwellingUp2Lvl2": "dw_1_3",
    "dwellingLvl3": "dw_2",
    "dwellingUpLvl3": "dw_2_2",
    "dwellingUp2Lvl3": "dw_2_3",
    "dwellingLvl4": "dw_3",
    "dwellingUpLvl4": "dw_3_2",
    "dwellingUp2Lvl4": "dw_3_3",
    "dwellingLvl5": "dw_4",
    "dwellingUpLvl5": "dw_4_2",
    "dwellingUp2Lvl5": "dw_4_3",
    "dwellingLvl6": "dw_5",
    "dwellingUpLvl6": "dw_5_2",
    "dwellingUp2Lvl6": "dw_5_3",
    "dwellingLvl7": "dw_6",
    "dwellingUpLvl7": "dw_6_2",
    "dwellingUp2Lvl7": "dw_6_3",
}

PREFIX_BY_FACTION = {"dungeon": "tbdn", "necropolis": "tbnc"}

COMMON_HALL_SLOT_TO_OLDEN: dict[str, tuple[str, int]] = {
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
    "mageGuild5": ("Build_Magic_Guild", 5),
    "horde1Upgr": ("Build_Resource_Depot_level_2", 1),
    "dwellingLvl1": ("Build_Tier_1", 1),
    "dwellingUpLvl1": ("Build_Tier_1", 2),
    "dwellingUp2Lvl1": ("Build_Tier_1", 3),
    "dwellingLvl2": ("Build_Tier_2", 1),
    "dwellingUpLvl2": ("Build_Tier_2", 2),
    "dwellingUp2Lvl2": ("Build_Tier_2", 3),
    "dwellingLvl3": ("Build_Tier_3", 1),
    "dwellingUpLvl3": ("Build_Tier_3", 2),
    "dwellingUp2Lvl3": ("Build_Tier_3", 3),
    "dwellingLvl4": ("Build_Tier_4", 1),
    "dwellingUpLvl4": ("Build_Tier_4", 2),
    "dwellingUp2Lvl4": ("Build_Tier_4", 3),
    "dwellingLvl5": ("Build_Tier_5", 1),
    "dwellingUpLvl5": ("Build_Tier_5", 2),
    "dwellingUp2Lvl5": ("Build_Tier_5", 3),
    "dwellingLvl6": ("Build_Tier_6", 1),
    "dwellingUpLvl6": ("Build_Tier_6", 2),
    "dwellingUp2Lvl6": ("Build_Tier_6", 3),
    "dwellingLvl7": ("Build_Tier_7", 1),
    "dwellingUpLvl7": ("Build_Tier_7", 2),
    "dwellingUp2Lvl7": ("Build_Tier_7", 3),
}

FACTION_EXTRA_HALL_SLOT_TO_OLDEN: dict[str, dict[str, tuple[str, int]]] = {
    "dungeon": {
        "special1": ("Build_Artifact_Market", 1),
        "special2": ("Build_Bank", 1),
        "special3": ("Build_Mother_Nature", 1),
        "special4": ("Build_Mycelium_Roots", 1),
    },
    "necropolis": {
        "shipyard": ("Build_Artifact_Market", 1),
        "special1": ("Build_Bank", 1),
        "special2": ("Build_Mother_Nature", 1),
        "special3": ("Build_Mycelium_Roots", 1),
    },
}

BUILDING_LAYER_OVERRIDES: dict[str, dict[str, str]] = {
    "dungeon": {
        "Build_Artifact_Market": "tbdnspec",
        "Build_Bank": "tbdnext0",
        "Build_Mother_Nature": "tbdnext1",
        "Build_Mycelium_Roots": "tbdnext2",
        "Build_Gymnasium": "tbdnext2",
        "Build_Lyceum": "tbdnext1",
        "Build_Spy_Network": "tbdnext0",
        "Build_Spring_of_Life": "tbdnholy",
    },
    "necropolis": {
        "Build_Artifact_Market": "tbncdock",
        "Build_Bank": "tbncspec",
        "Build_Mother_Nature": "tbncext0",
        "Build_Mycelium_Roots": "tbncext1",
        "Build_Gymnasium": "tbncspec",
        "Build_Lyceum": "tbncext1",
        "Build_Spy_Network": "tbncext0",
        "Build_Spring_of_Life": "tbncholy",
    },
}

COMMON_BUILDING_LAYER_IDS = {
    "Build_Tier_1": "{prefix}dw_0",
    "Build_Tier_2": "{prefix}dw_1",
    "Build_Tier_3": "{prefix}dw_2",
    "Build_Tier_4": "{prefix}dw_3",
    "Build_Tier_5": "{prefix}dw_4",
    "Build_Tier_6": "{prefix}dw_5",
    "Build_Tier_7": "{prefix}dw_6",
    "Build_Main": "{prefix}hall",
    "Build_Wall": "{prefix}cstl",
    "Build_Tavern": "{prefix}tvrn",
    "Build_Market": "{prefix}mark",
    "Build_Treasury": "{prefix}blak",
    "Build_Resource_Depot": "{prefix}silo",
    "Build_Resource_Depot_level_2": "{prefix}hrd2",
    "Build_Magic_Guild": "{prefix}mage",
}


def strip_json_comments(text: str) -> str:
    text = re.sub(r"//.*", "", text)
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return re.sub(r",(\s*[}\]])", r"\1", text)


def load_jsonc(path: Path) -> Any:
    return json.loads(strip_json_comments(path.read_text(encoding="utf-8-sig")))


def relative(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT)).replace("\\", "/")
    except ValueError:
        return str(path)


def source_stem_name(animation: str) -> str:
    return Path(animation.replace("\\", "/")).stem.lower()


def layer_id_for_structure(faction: str, structure: str, animation: str) -> str:
    prefix = PREFIX_BY_FACTION[faction]
    mapped = STRUCTURE_TO_LAYER.get(structure)
    if mapped:
        return prefix + mapped
    return source_stem_name(animation)


def third_config_path(faction: str) -> Path:
    return THIRD_ROOT / "config" / "town-screen" / faction / "factions.json"


def third_sprite_root(faction: str) -> Path:
    return THIRD_ROOT / "sprites" / "town-screen" / faction


def town_root(faction: str) -> Path:
    return TOWN_REFS / f"homm3_{faction}"


def source_bg_path(faction: str) -> Path:
    display = "Dungeon" if faction == "dungeon" else "Necropolis"
    return town_root(faction) / f"{display}-in-background.png"


def extract_lod_def(def_name: str, temp_root: Path) -> Path:
    out_path = temp_root / def_name
    subprocess.run([sys.executable, str(LOD_EXTRACT), str(H3SPRITE_LOD), def_name, str(out_path)], check=True)
    if not out_path.is_file():
        raise RuntimeError(f"failed to extract {def_name} from {H3SPRITE_LOD}")
    return out_path


def find_case_insensitive_file(path: Path) -> Path:
    if path.is_file():
        return path
    wanted = path.name.lower()
    for candidate in path.parent.iterdir():
        if candidate.is_file() and candidate.name.lower() == wanted:
            return candidate
    raise FileNotFoundError(path)


def third_def_path(faction: str, animation: str) -> Path:
    name = Path(animation.replace("\\", "/")).name
    return find_case_insensitive_file(third_sprite_root(faction) / name)


def extract_def(def_path: Path, temp_root: Path) -> list[Path]:
    temp_root.mkdir(parents=True, exist_ok=True)
    subprocess.run([sys.executable, str(DEF_EXTRACT), str(def_path), str(temp_root)], check=True)
    manifest_path = temp_root / (def_path.stem.lower() + ".json")
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    frames: list[Path] = []
    for seq in data.get("sequences") or []:
        for frame in seq.get("frames") or []:
            candidate = temp_root / frame.replace("\\", "/")
            if candidate.is_file():
                frames.append(candidate)
    if not frames:
        frames = sorted((temp_root / (def_path.stem.lower() + ".dir")).glob("*.png"))
    if not frames:
        raise RuntimeError(f"{def_path}: no extracted PNG frames")
    return frames


def build_mockup(faction: str) -> None:
    output = town_root(faction) / "mockups" / f"homm3_{faction}_background_mock_1920x1080.png"
    prebake_mockup(source_bg_path(faction), output)


def merged_structures(faction: str) -> dict[str, dict[str, Any]]:
    merged = dict(BASE_STRUCTURES[faction])
    third_doc = load_jsonc(third_config_path(faction))
    third_town = third_doc[f"core:{faction}"]["town"]
    for key, value in (third_town.get("structures") or {}).items():
        if isinstance(value, dict) and isinstance(value.get("animation"), str):
            merged[key] = dict(value, third=True)
    return merged


def build_layers(faction: str) -> None:
    root = town_root(faction)
    layers_dir = root / "layers"
    anims_dir = layers_dir / "anims"
    if layers_dir.exists():
        shutil.rmtree(layers_dir)
    anims_dir.mkdir(parents=True, exist_ok=True)

    structures = merged_structures(faction)
    placements: list[dict[str, Any]] = []
    anim_metadata: list[dict[str, Any]] = []
    order = 0

    with tempfile.TemporaryDirectory(prefix=f"homm3-{faction}-town-defs-", ignore_cleanup_errors=True) as tmp:
        temp_root = Path(tmp)
        for structure, entry in structures.items():
            animation = entry.get("animation")
            if not isinstance(animation, str):
                continue
            def_path = third_def_path(faction, animation) if entry.get("third") else extract_lod_def(animation, temp_root)
            layer_id = layer_id_for_structure(faction, structure, animation)
            frames = extract_def(def_path, temp_root / layer_id)

            image = Image.open(frames[0]).convert("RGBA")
            sprite_name = f"{layer_id}.png"
            image.save(layers_dir / sprite_name, optimize=True)
            placements.append(
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

            if len(frames) > 1:
                anim_dir = anims_dir / layer_id
                anim_dir.mkdir(parents=True, exist_ok=True)
                frame_names = []
                for index, frame in enumerate(frames):
                    dest_name = f"frame_{index:02d}.png"
                    shutil.copy2(frame, anim_dir / dest_name)
                    frame_names.append(dest_name)
                anim_metadata.append({"id": layer_id, "frameRateMs": FRAME_RATE_MS, "frames": frame_names})

    positions = {
        "_comment": f"{faction.title()} top-left layer positions on the native 800x374 HoMM3 town canvas. Base structures use VCMI core faction coordinates; third upgrades use local VCMI third-upgrades config.",
        "canvas_w": SOURCE_SIZE[0],
        "canvas_h": SOURCE_SIZE[1],
        "thirdUpgradeConfig": relative(third_config_path(faction)),
        "layers": sorted(placements, key=lambda row: (row["z"], row["order"])),
    }
    positions_path = layers_dir / "positions.json"
    positions_path.write_text(json.dumps(positions, indent=2) + "\n", encoding="utf-8")
    prebake_positions_file(positions_path)
    (anims_dir / "metadata.json").write_text(json.dumps(anim_metadata, indent=2) + "\n", encoding="utf-8")


def flatten_hall_slots(value: Any) -> list[str]:
    result: list[str] = []

    def walk(item: Any) -> None:
        if isinstance(item, str):
            result.append(item)
        elif isinstance(item, list):
            for child in item:
                walk(child)

    walk(value)
    return result


def icon_frame_index_by_slot(town: dict[str, Any], hall_slots: list[str]) -> dict[str, int]:
    result = {name: index for index, name in enumerate(hall_slots)}
    result.update(COMMON_ICON_FRAME_ID_BY_SLOT)
    for structure, data in (town.get("buildings") or {}).items():
        if not isinstance(data, dict):
            continue
        frame_id = data.get("id")
        if isinstance(frame_id, int) and frame_id >= 0:
            result[structure] = frame_id
    return result


def building_layer_ids(faction: str) -> dict[str, str]:
    prefix = PREFIX_BY_FACTION[faction]
    result = {sid: layer.format(prefix=prefix) for sid, layer in COMMON_BUILDING_LAYER_IDS.items()}
    result.update(BUILDING_LAYER_OVERRIDES[faction])
    return result


def build_building_layer_map(faction: str) -> None:
    path = town_root(faction) / "layers" / "building_layer_map.json"
    doc = {
        "_comment": f"{faction.title()} visual mapping. Keys are Olden Era Build_* SIDs; values are HoMM3 DEF-name layer roots. Runtime appends the constructed level before falling back to the root.",
        "buildingLayerIds": building_layer_ids(faction),
        "sourceCrosswalk": {
            "Build_Resource_Depot_level_2": "Mapped to the HoMM3 horde-upgrade visual for this faction.",
            "Build_Artifact_Market": "Mapped to the closest HoMM3 artifact/shipyard/special visual carried by the donor city schema.",
            "Build_Bank": "Mapped to the first HoMM3 special-building visual carried by the donor city schema.",
        },
    }
    path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")


def build_icons(faction: str) -> None:
    third_doc = load_jsonc(third_config_path(faction))
    town = third_doc[f"core:{faction}"]["town"]
    hall_slots = flatten_hall_slots(town["hallSlots"])
    slot_to_olden = dict(COMMON_HALL_SLOT_TO_OLDEN)
    slot_to_olden.update(FACTION_EXTRA_HALL_SLOT_TO_OLDEN[faction])

    source_def_name = Path(town["buildingsIcons"]).name
    source_def = find_case_insensitive_file(third_sprite_root(faction) / source_def_name)
    icons_root = town_root(faction) / "building_icons"
    frame_folder = source_def.stem.lower() + ".dir"
    dest_dir = icons_root / frame_folder
    icons_root.mkdir(parents=True, exist_ok=True)
    if dest_dir.exists():
        shutil.rmtree(dest_dir)
    for old_map in icons_root.glob("*_source_map.json"):
        old_map.unlink()
    dest_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix=f"homm3-{faction}-icons-", ignore_cleanup_errors=True) as tmp:
        frames = extract_def(source_def, Path(tmp))
        for frame in frames:
            shutil.copy2(frame, dest_dir / frame.name)

    source_json = source_def.with_suffix(".json")
    if source_json.is_file():
        shutil.copy2(source_json, icons_root / source_json.name)

    slot_to_frame = icon_frame_index_by_slot(town, hall_slots)
    source_map: dict[str, dict[str, str]] = {}
    for slot in hall_slots:
        mapped = slot_to_olden.get(slot)
        if not mapped:
            continue
        building_sid, level = mapped
        source_map.setdefault(building_sid, {})[str(level)] = f"00_{slot_to_frame[slot]:02d}.png"

    map_doc = {
        "_comment": f"{faction.title()} build-tree icon indices follow VCMI/HoMM3 building frame IDs, not hallSlots index order.",
        "vcmiTownConfig": relative(third_config_path(faction)),
        "folder": frame_folder,
        "unmappedHallSlots": [slot for slot in hall_slots if slot not in slot_to_olden],
        "map": source_map,
    }
    (icons_root / f"{source_def.stem.lower()}_source_map.json").write_text(
        json.dumps(map_doc, indent=2) + "\n",
        encoding="utf-8",
    )


def check_sources(faction: str) -> None:
    for path in (H3SPRITE_LOD, LOD_EXTRACT, DEF_EXTRACT, source_bg_path(faction), third_config_path(faction), third_sprite_root(faction)):
        if not path.exists():
            raise FileNotFoundError(path)
    third_doc = load_jsonc(third_config_path(faction))
    town = third_doc[f"core:{faction}"]["town"]
    find_case_insensitive_file(third_sprite_root(faction) / Path(town["buildingsIcons"]).name)
    for entry in (town.get("structures") or {}).values():
        if isinstance(entry, dict) and isinstance(entry.get("animation"), str):
            third_def_path(faction, entry["animation"])


def build_faction(faction: str, check_only: bool = False) -> None:
    if faction not in BASE_STRUCTURES:
        raise ValueError(f"unsupported faction: {faction}")
    check_sources(faction)
    if check_only:
        print(f"HoMM3 {faction} town scene sources are present.")
        return
    build_mockup(faction)
    build_layers(faction)
    build_building_layer_map(faction)
    build_icons(faction)
    print(f"HoMM3 {faction} town scene assets generated under {town_root(faction)}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("factions", nargs="+", choices=sorted(BASE_STRUCTURES), help="Faction(s) to generate.")
    parser.add_argument("--check-sources", action="store_true", help="Validate source paths without writing assets.")
    args = parser.parse_args()
    for faction in args.factions:
        build_faction(faction, check_only=args.check_sources)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
