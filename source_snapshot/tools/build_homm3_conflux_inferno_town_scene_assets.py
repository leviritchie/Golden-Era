#!/usr/bin/env python3
"""Build HoMM3 Conflux and Inferno town-screen assets.

Builders keep source placements in native HoMM3/VCMI top-left coordinates.
tools/prebake_homm3_town_scene_coordinates.py adds runtime reference rects
and the 1920x1080 black-plate mockup used by the town renderer.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import struct
import subprocess
import zlib
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image

from prebake_homm3_town_scene_coordinates import prebake_mockup, prebake_positions_file


ROOT = Path(__file__).resolve().parents[1]
PLUGIN_ROOT = ROOT / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod"
TOWN_REFS_ROOT = PLUGIN_ROOT / "homm3_runtime_assets" / "town_scene_refs"
H3SPRITE_LOD = ROOT / "vcmi" / "Data" / "H3sprite.lod"
H3BITMAP_LOD = ROOT / "vcmi" / "Data" / "H3bitmap.lod"
H3AB_SPR_LOD = ROOT / "HoMM 3 Complete" / "Data" / "H3ab_spr.lod"
VCMI_H3AB_SPR_LOD = ROOT / "vcmi" / "Data" / "H3ab_spr.lod"
THIRD_UPGRADES = ROOT / "vcmi" / "Mods" / "third-upgrades"
LOD_EXTRACT = ROOT / "tools" / "lod_extract_entry_py3.py"
DEF_EXTRACT = ROOT / "tools" / "defextract_py3.py"

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


@dataclass(frozen=True)
class LayerSpec:
    layer_id: str
    structure: str
    source: str
    level: int
    x: int
    y: int
    z: int = 0
    source_kind: str = "lod"
    root: str = "content"


@dataclass(frozen=True)
class FactionSpec:
    sid: str
    source_bg: str
    mockup_name: str
    town_config: str
    third_sprite_dir: str
    icon_def: str
    icon_folder: str
    base_layers: tuple[LayerSpec, ...]
    third_layers: tuple[LayerSpec, ...]
    building_layer_ids: dict[str, str]
    hall_slot_to_olden: dict[str, tuple[str, int]]
    explicit_icon_reuse: dict[tuple[str, int], tuple[str, str]]


COMMON_HALL_SLOT_TO_OLDEN = {
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


CONFLUX_BASE = (
    LayerSpec("tbelhall", "villageHall", "TBELhall.def", 1, 0, 142, 3),
    LayerSpec("tbelhall_2", "townHall", "TBELhal2.def", 2, 0, 112, 3),
    LayerSpec("tbelhall_3", "cityHall", "TBELhal3.def", 3, 0, 82, 3),
    LayerSpec("tbelhall_4", "capitol", "TBELhal4.def", 4, 0, 43, 3),
    LayerSpec("tbelcstl", "fort", "TBELcstl.def", 1, 340, 72, -10),
    LayerSpec("tbelcstl_2", "citadel", "TBELcas2.def", 2, 340, 47, -10),
    LayerSpec("tbelcstl_3", "castle", "TBELcas3.def", 3, 340, 18, -10),
    LayerSpec("tbeltvrn", "tavern", "TBELtvrn.def", 1, 207, 206, 4),
    LayerSpec("tbelblak", "blacksmith", "TBELblak.def", 1, 132, 224, 12),
    LayerSpec("tbelmark", "marketplace", "TBELmark.def", 1, 276, 237, 5),
    LayerSpec("tbelsilo", "resourceSilo", "TBELsilo.def", 1, 348, 235, 5),
    LayerSpec("tbelmage", "mageGuild1", "TBELmage.def", 1, 612, 124, -2),
    LayerSpec("tbelmage_2", "mageGuild2", "TBELmag2.def", 2, 612, 98, -2),
    LayerSpec("tbelmage_3", "mageGuild3", "TBELmag3.def", 3, 612, 71, -2),
    LayerSpec("tbelmage_4", "mageGuild4", "TBELmag4.def", 4, 612, 46, -2),
    LayerSpec("tbelmage_5", "mageGuild5", "TBELmag5.def", 5, 612, 20, -2),
    LayerSpec("tbeldock", "shipyard", "TBELdock.def", 1, 537, 270, 3),
    LayerSpec("tbelspec", "special1", "TBELSpec.def", 1, 504, 153, 5),
    LayerSpec("tbelext2", "special2", "TBELExt2.def", 1, 206, 123, -1),
    LayerSpec("tbelhrd1", "horde1", "TBELHrd1.def", 1, 689, 250, 7),
    LayerSpec("tbelhrd2", "horde1Upgr", "TBELHrd2.def", 2, 689, 250, 7),
    LayerSpec("tbelholy", "grail", "TBELHoly.def", 1, 388, 66, -3),
    LayerSpec("tbeldw_0", "dwellingLvl1", "TBELdw_0.def", 1, 689, 250, 7),
    LayerSpec("tbeldw_0_2", "dwellingUpLvl1", "TBELup_0.def", 2, 689, 250, 7),
    LayerSpec("tbeldw_1", "dwellingLvl2", "TBELdw_1.def", 1, 630, 50, 2),
    LayerSpec("tbeldw_1_2", "dwellingUpLvl2", "TBELup_1.def", 2, 630, 50, 2),
    LayerSpec("tbeldw_2", "dwellingLvl3", "TBELdw_2.def", 1, 709, 210, 5),
    LayerSpec("tbeldw_2_2", "dwellingUpLvl3", "TBELup_2.def", 2, 709, 210, 5),
    LayerSpec("tbeldw_3", "dwellingLvl4", "TBELdw_3.def", 1, 108, 131, -1),
    LayerSpec("tbeldw_3_2", "dwellingUpLvl4", "TBELup_3.def", 2, 108, 131, -1),
    LayerSpec("tbeldw_4", "dwellingLvl5", "TBELdw_4.def", 1, 264, 168, -1),
    LayerSpec("tbeldw_4_2", "dwellingUpLvl5", "TBELup_4.def", 2, 264, 168, -1),
    LayerSpec("tbeldw_5", "dwellingLvl6", "TBELdw_5.def", 1, 394, 283, 5),
    LayerSpec("tbeldw_5_2", "dwellingUpLvl6", "TBELup_5.def", 2, 394, 283, 5),
    LayerSpec("tbeldw_6", "dwellingLvl7", "TBELdw_6.def", 1, 34, 0, -2),
    LayerSpec("tbeldw_6_2", "dwellingUpLvl7", "TBELup_6.def", 2, 34, 0, -2),
)

CONFLUX_THIRD = (
    LayerSpec("tbelext4", "extraCapitol", "TBELEXT4.def", 1, 0, 247, 15, "third"),
    LayerSpec("tbel2hrd2", "horde2", "TBEL2HRD2.def", 1, 689, 250, 7, "third"),
    LayerSpec("tbeldw_0_3", "dwellingUp2Lvl1", "TBELUP2_0.def", 3, 689, 250, 7, "third"),
    LayerSpec("tbeldw_1_3", "dwellingUp2Lvl2", "TBELUP2_1.def", 3, 630, 50, 2, "third"),
    LayerSpec("tbeldw_2_3", "dwellingUp2Lvl3", "TBELUP2_2.def", 3, 709, 210, 5, "third"),
    LayerSpec("tbeldw_3_3", "dwellingUp2Lvl4", "TBELUP2_3.def", 3, 108, 131, -1, "third"),
    LayerSpec("tbeldw_4_3", "dwellingUp2Lvl5", "TBELUP2_4.def", 3, 264, 168, -1, "third"),
    LayerSpec("tbeldw_5_3", "dwellingUp2Lvl6", "TBELUP2_5.def", 3, 394, 283, 10, "third"),
    LayerSpec("tbeldw_6_3", "dwellingUp2Lvl7", "TBELUP2_6.def", 3, 34, 0, -2, "third"),
)

INFERNO_BASE = (
    LayerSpec("tbinhall", "villageHall", "TBINHALL.def", 1, 0, 174, 3),
    LayerSpec("tbinhall_2", "townHall", "TBINHAL2.def", 2, 0, 174, 3),
    LayerSpec("tbinhall_3", "cityHall", "TBINHAL3.def", 3, 0, 174, 3),
    LayerSpec("tbinhall_4", "capitol", "TBINHAL4.def", 4, 0, 131, 3),
    LayerSpec("tbincstl", "fort", "TBINCSTL.def", 1, 222, 44, -2),
    LayerSpec("tbincstl_2", "citadel", "TBINCAS2.def", 2, 222, 44, -2),
    LayerSpec("tbincstl_3", "castle", "TBINCAS3.def", 3, 222, 18, -2),
    LayerSpec("tbintvrn", "tavern", "TBINTVRN.def", 1, 105, 219, 1),
    LayerSpec("tbinblak", "blacksmith", "TBINBLAK.def", 1, 684, 253, 1),
    LayerSpec("tbinmark", "marketplace", "TBINMARK.def", 1, 511, 301, 4),
    LayerSpec("tbinsilo", "resourceSilo", "TBINSILO.def", 1, 497, 337, 5),
    LayerSpec("tbinmage", "mageGuild1", "TBINMAGE.def", 1, 667, 127, -1),
    LayerSpec("tbinmage_2", "mageGuild2", "TBINMAG2.def", 2, 667, 101, -1),
    LayerSpec("tbinmage_3", "mageGuild3", "TBINMAG3.def", 3, 667, 83, -1),
    LayerSpec("tbinmage_4", "mageGuild4", "TBINMAG4.def", 4, 667, 56, -1),
    LayerSpec("tbinmage_5", "mageGuild5", "TBINMAG5.def", 5, 667, 35, -1),
    LayerSpec("tbinext0", "special2", "TBINEXT0.def", 1, 297, 0, -4),
    LayerSpec("tbinext1", "special3", "TBINEXT1.def", 1, 227, 174, -1),
    LayerSpec("tbinext2", "special4", "TBINEXT2.def", 1, 593, 104, -1),
    LayerSpec("tbinhrd1", "horde1", "TBINHRD1.def", 1, 614, 256, 6),
    LayerSpec("tbinhrd2", "horde1Upgr", "TBINHRD2.def", 2, 614, 221, 6),
    LayerSpec("tbinhrd3", "horde2", "TBINHRD3.def", 1, 10, 301, 6),
    LayerSpec("tbinhrd4", "horde2Upgr", "TBINHRD4.def", 2, 9, 273, 6),
    LayerSpec("tbinholy", "grail", "TBINHOLY.def", 1, 24, 10, -1),
    LayerSpec("tbindw_0", "dwellingLvl1", "TBINDW_0.def", 1, 614, 256, 6),
    LayerSpec("tbindw_0_2", "dwellingUpLvl1", "TBINUP_0.def", 2, 614, 221, 6),
    LayerSpec("tbindw_1", "dwellingLvl2", "TBINDW_1.def", 1, 187, 248, 4),
    LayerSpec("tbindw_1_2", "dwellingUpLvl2", "TBINUP_1.def", 2, 187, 212, 4),
    LayerSpec("tbindw_2", "dwellingLvl3", "TBINDW_2.def", 1, 9, 325, 6),
    LayerSpec("tbindw_2_2", "dwellingUpLvl3", "TBINUP_2.def", 2, 9, 273, 6),
    LayerSpec("tbindw_3", "dwellingLvl4", "TBINDW_3.def", 1, 414, 204, 2),
    LayerSpec("tbindw_3_2", "dwellingUpLvl4", "TBINUP_3.def", 2, 412, 197, 2),
    LayerSpec("tbindw_4", "dwellingLvl5", "TBINDW_4.def", 1, 359, 296, 3),
    LayerSpec("tbindw_4_2", "dwellingUpLvl5", "TBINUP_4.def", 2, 359, 244, 3),
    LayerSpec("tbindw_5", "dwellingLvl6", "TBINDW_5.def", 1, 220, 350, 5),
    LayerSpec("tbindw_5_2", "dwellingUpLvl6", "TBINUP_5.def", 2, 220, 282, 5),
    LayerSpec("tbindw_6", "dwellingLvl7", "TBINDW_6.def", 1, 420, 153, -3),
    LayerSpec("tbindw_6_2", "dwellingUpLvl7", "TBINUP_6.def", 2, 420, 105, -3),
)

INFERNO_THIRD = (
    LayerSpec("tbifext5", "extraCapitol", "TBIFEXT5.def", 1, 378, 91, -1, "third"),
    LayerSpec("tbinhrd2_2", "horde4", "TBINHRD2_2.def", 1, 614, 221, 6, "third"),
    LayerSpec("tbinhrd2_4", "horde3", "TBINHRD2_4.def", 1, 9, 273, 6, "third"),
    LayerSpec("tbindw_0_3", "dwellingUp2Lvl1", "TBINUP2_0.def", 3, 614, 221, 6, "third"),
    LayerSpec("tbindw_1_3", "dwellingUp2Lvl2", "TBINUP2_1.def", 3, 187, 212, 4, "third"),
    LayerSpec("tbindw_2_3", "dwellingUp2Lvl3", "TBINUP2_2.def", 3, 9, 273, 6, "third"),
    LayerSpec("tbindw_3_3", "dwellingUp2Lvl4", "TBINUP2_3.def", 3, 412, 197, 2, "third"),
    LayerSpec("tbindw_4_3", "dwellingUp2Lvl5", "TBINUP2_4.def", 3, 359, 223, 3, "third"),
    LayerSpec("tbindw_5_3", "dwellingUp2Lvl6", "TBINUP2_5.def", 3, 220, 282, 5, "third"),
    LayerSpec("tbindw_6_3", "dwellingUp2Lvl7", "TBINUP2_6.def", 3, 420, 72, -1, "third"),
)

CONFLUX_BUILDING_LAYER_IDS = {
    "Build_Main": "tbelhall",
    "Build_Wall": "tbelcstl",
    "Build_Tavern": "tbeltvrn",
    "Build_Treasury": "tbelblak",
    "Build_Market": "tbelmark",
    "Build_Resource_Depot": "tbelsilo",
    "Build_Magic_Guild": "tbelmage",
    "Build_Bank": "tbelspec",
    "Build_Artifact_Market": "tbeldock",
    "Build_Mother_Nature": "tbelext2",
    "Build_Resource_Depot_level_2": "tbelhrd2",
    "Build_Tier_1": "tbeldw_0",
    "Build_Tier_2": "tbeldw_1",
    "Build_Tier_3": "tbeldw_2",
    "Build_Tier_4": "tbeldw_3",
    "Build_Tier_5": "tbeldw_4",
    "Build_Tier_6": "tbeldw_5",
    "Build_Tier_7": "tbeldw_6",
}

INFERNO_BUILDING_LAYER_IDS = {
    "Build_Main": "tbinhall",
    "Build_Wall": "tbincstl",
    "Build_Tavern": "tbintvrn",
    "Build_Treasury": "tbinblak",
    "Build_Market": "tbinmark",
    "Build_Resource_Depot": "tbinsilo",
    "Build_Magic_Guild": "tbinmage",
    "Build_Bank": "tbinext1",
    "Build_Artifact_Market": "tbinext2",
    "Build_Mother_Nature": "tbinext0",
    "Build_Resource_Depot_level_2": "tbinhrd2",
    "Build_Tier_1": "tbindw_0",
    "Build_Tier_2": "tbindw_1",
    "Build_Tier_3": "tbindw_2",
    "Build_Tier_4": "tbindw_3",
    "Build_Tier_5": "tbindw_4",
    "Build_Tier_6": "tbindw_5",
    "Build_Tier_7": "tbindw_6",
}

CONFLUX_HALL_SLOTS = {
    **COMMON_HALL_SLOT_TO_OLDEN,
    "shipyard": ("Build_Artifact_Market", 1),
    "special1": ("Build_Bank", 1),
    "special2": ("Build_Mother_Nature", 1),
    "horde1Upgr": ("Build_Resource_Depot_level_2", 1),
}

INFERNO_HALL_SLOTS = {
    **COMMON_HALL_SLOT_TO_OLDEN,
    "special4": ("Build_Artifact_Market", 1),
    "special2": ("Build_Mother_Nature", 1),
    "special3": ("Build_Bank", 1),
    "horde1Upgr": ("Build_Resource_Depot_level_2", 1),
    "horde2Upgr": ("Build_Resource_Depot_level_2", 1),
}

FACTIONS = {
    "conflux": FactionSpec(
        sid="homm3_conflux",
        source_bg="Conflux-in-background.png",
        mockup_name="homm3_conflux_background_mock_1920x1080.png",
        town_config="content/config/town-screen/conflux/factions.json",
        third_sprite_dir="content/sprites/town-screen/conflux",
        icon_def="AltHallElem.def",
        icon_folder="althallelem.dir",
        base_layers=CONFLUX_BASE,
        third_layers=CONFLUX_THIRD,
        building_layer_ids=CONFLUX_BUILDING_LAYER_IDS,
        hall_slot_to_olden=CONFLUX_HALL_SLOTS,
        explicit_icon_reuse={},
    ),
    "inferno": FactionSpec(
        sid="homm3_inferno",
        source_bg="Inferno-in-background.png",
        mockup_name="homm3_inferno_background_mock_1920x1080.png",
        town_config="content/config/town-screen/inferno/factions.json",
        third_sprite_dir="content/sprites/town-screen/inferno",
        icon_def="ALTHALLINFR.def",
        icon_folder="althallinfr.dir",
        base_layers=INFERNO_BASE,
        third_layers=INFERNO_THIRD,
        building_layer_ids=INFERNO_BUILDING_LAYER_IDS,
        hall_slot_to_olden=INFERNO_HALL_SLOTS,
        explicit_icon_reuse={},
    ),
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


def find_case_insensitive_file(path: Path) -> Path:
    if path.is_file():
        return path
    if not path.parent.is_dir():
        raise FileNotFoundError(path)
    wanted = path.name.lower()
    for candidate in path.parent.iterdir():
        if candidate.name.lower() == wanted:
            return candidate
    raise FileNotFoundError(path)


def extract_lod_def(def_name: str, temp_root: Path) -> Path:
    for lod in (H3SPRITE_LOD, H3AB_SPR_LOD, VCMI_H3AB_SPR_LOD):
        if not lod.is_file():
            continue
        out_path = temp_root / def_name
        result = subprocess.run(
            [sys.executable, str(LOD_EXTRACT), str(lod), def_name, str(out_path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        if result.returncode == 0 and out_path.is_file():
            return out_path
    raise FileNotFoundError(f"could not extract {def_name} from local HoMM3/VCMI LOD archives")


def extract_def(def_path: Path, temp_root: Path) -> tuple[dict[str, Any], list[Path]]:
    temp_root.mkdir(parents=True, exist_ok=True)
    subprocess.run([sys.executable, str(DEF_EXTRACT), str(def_path), str(temp_root)], check=True)
    manifest_path = temp_root / (def_path.stem.lower() + ".json")
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    frames: list[Path] = []
    for seq in data.get("sequences") or []:
        for frame in seq.get("frames") or []:
            path = temp_root / frame.replace("\\", "/")
            if path.is_file():
                frames.append(path)
    if not frames:
        frames = sorted((temp_root / (def_path.stem.lower() + ".dir")).glob("*.png"))
    if not frames:
        raise RuntimeError(f"{def_path}: no extracted PNG frames")
    return data, frames


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


def icon_frame_index_by_slot(town: dict[str, Any], hall_slots: list[str]) -> dict[str, int]:
    """Map VCMI hall slot names to the frame id used by the hall icon DEF."""
    result = {name: index for index, name in enumerate(hall_slots)}
    result.update(COMMON_ICON_FRAME_ID_BY_SLOT)
    for structure, data in (town.get("buildings") or {}).items():
        if not isinstance(data, dict):
            continue
        frame_id = data.get("id")
        if isinstance(frame_id, int) and frame_id >= 0:
            result[structure] = frame_id
    return result


BACKGROUND_LOD_ENTRY_BY_SID = {
    "homm3_conflux": "TBELBack.pcx",
    "homm3_inferno": "tbinback.pcx",
}


def read_heroes_bitmap_from_lod(lod_path: Path, entry_name: str) -> Image.Image:
    want = entry_name.lower().encode("ascii")
    data = lod_path.read_bytes()
    if data[:4] != b"LOD\0":
        raise RuntimeError(f"{lod_path}: not a Heroes LOD archive")
    total = struct.unpack_from("<I", data, 8)[0]
    offset = 92
    for _ in range(total):
        raw_name = data[offset : offset + 16]
        offset += 16
        nul = raw_name.find(b"\0")
        name = (raw_name[:nul] if nul >= 0 else raw_name).lower()
        blob_offset, size, _unknown, compressed_size = struct.unpack_from("<IIII", data, offset)
        offset += 16
        if name != want:
            continue
        blob = data[blob_offset : blob_offset + (compressed_size or size)]
        if compressed_size:
            blob = zlib.decompress(blob)
        byte_len, width, height = struct.unpack_from("<III", blob, 0)
        if byte_len != width * height * 3:
            raise RuntimeError(f"{lod_path}:{entry_name}: invalid Heroes bitmap byte count {byte_len} for {width}x{height}")
        return Image.frombytes("RGB", (width, height), blob[12:], "raw", "RGB").convert("RGBA")
    raise FileNotFoundError(f"{lod_path}: missing exact background entry {entry_name}")


def write_source_background(spec: FactionSpec) -> None:
    entry_name = BACKGROUND_LOD_ENTRY_BY_SID[spec.sid]
    image = read_heroes_bitmap_from_lod(H3BITMAP_LOD, entry_name)
    if spec.sid == "homm3_inferno":
        r, g, b, a = image.split()
        image = Image.merge("RGBA", (b, g, r, a))
    if image.size != SOURCE_SIZE:
        raise RuntimeError(f"{entry_name}: expected {SOURCE_SIZE}, got {image.size}")
    town_root = TOWN_REFS_ROOT / spec.sid
    image.save(town_root / spec.source_bg, optimize=True)


def spec_paths(spec: FactionSpec) -> tuple[Path, Path, Path, Path, Path]:
    town_root = TOWN_REFS_ROOT / spec.sid
    layers_dir = town_root / "layers"
    anims_dir = layers_dir / "anims"
    icons_dir = town_root / "building_icons" / spec.icon_folder
    icon_source_map = town_root / "building_icons" / f"{Path(spec.icon_folder).stem}_source_map.json"
    return town_root, layers_dir, anims_dir, icons_dir, icon_source_map


def build_mockup(spec: FactionSpec) -> None:
    town_root, _layers_dir, _anims_dir, _icons_dir, _source_map = spec_paths(spec)
    source_path = town_root / spec.source_bg
    out_path = town_root / "mockups" / spec.mockup_name
    prebake_mockup(source_path, out_path)
    print(f"{spec.sid}: wrote {relative(out_path)}")


def build_layers(spec: FactionSpec) -> None:
    _town_root, layers_dir, anims_dir, _icons_dir, _source_map = spec_paths(spec)
    if layers_dir.exists():
        shutil.rmtree(layers_dir)
    layers_dir.mkdir(parents=True, exist_ok=True)
    anims_dir.mkdir(parents=True, exist_ok=True)

    positions: list[dict[str, Any]] = []
    anim_metadata: list[dict[str, Any]] = []
    all_layers = [*spec.base_layers, *spec.third_layers]
    third_dir = THIRD_UPGRADES / spec.third_sprite_dir

    with tempfile.TemporaryDirectory(prefix=f"{spec.sid}-town-defs-", ignore_cleanup_errors=True) as tmp:
        temp_root = Path(tmp)
        for order, layer in enumerate(all_layers):
            if layer.source_kind == "third":
                source = find_case_insensitive_file(third_dir / layer.source)
            else:
                source = extract_lod_def(layer.source, temp_root / "lod")
            _manifest, frame_paths = extract_def(source, temp_root / layer.layer_id)
            frames: list[Image.Image] = []
            for frame_path in frame_paths:
                with Image.open(frame_path) as image:
                    frames.append(transparent_sprite(image))

            out_name = f"{layer.layer_id}.png"
            frames[0].save(layers_dir / out_name, optimize=True)
            if len(frames) > 1:
                anim_dir = anims_dir / layer.layer_id
                anim_dir.mkdir(parents=True, exist_ok=True)
                frame_names: list[str] = []
                for index, frame in enumerate(frames):
                    frame_name = f"frame_{index:02d}.png"
                    frame.save(anim_dir / frame_name, optimize=True)
                    frame_names.append(frame_name)
                anim_metadata.append(
                    {
                        "id": layer.layer_id,
                        "frameRateMs": FRAME_RATE_MS,
                        "frames": frame_names,
                    }
                )
            for frame in frames:
                frame.close()

            positions.append(
                {
                    "id": layer.layer_id,
                    "x": layer.x,
                    "y": layer.y,
                    "z": layer.z,
                    "order": order,
                    "sprite": out_name,
                    "source": layer.source,
                    "structure": layer.structure,
                }
            )
            print(f"{spec.sid}: {layer.source} -> {out_name}")

    positions_path = layers_dir / "positions.json"
    positions_path.write_text(
        json.dumps(
            {
                "_comment": (
                    f"{spec.sid} town layer placements. Coordinates are original 800x374 "
                    "HoMM3 town-screen pixels and are scaled by Homm3StrongholdTownLayers."
                ),
                "layers": positions,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    prebake_positions_file(positions_path)
    (anims_dir / "metadata.json").write_text(json.dumps(anim_metadata, indent=2) + "\n", encoding="utf-8")
    write_building_layer_map(spec, layers_dir, positions)


def write_building_layer_map(spec: FactionSpec, layers_dir: Path, positions: list[dict[str, Any]]) -> None:
    layers_by_structure = {entry["structure"]: entry["id"] for entry in positions}
    levels: dict[str, dict[str, str]] = {}
    for hall_slot, mapped in spec.hall_slot_to_olden.items():
        building_sid, level = mapped
        layer_id = layers_by_structure.get(hall_slot)
        if layer_id:
            levels.setdefault(building_sid, {})[str(level)] = layer_id
    data = {
        "_comment": (
            f"{spec.sid} visual mapping. Keys are Olden Era building SIDs; values are "
            "HoMM3 layer roots from positions.json. Runtime can append constructed levels."
        ),
        "buildingLayerIds": spec.building_layer_ids,
        "levels": levels,
    }
    (layers_dir / "building_layer_map.json").write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def build_icons(spec: FactionSpec) -> None:
    town_config_path = THIRD_UPGRADES / spec.town_config
    town = load_jsonc(town_config_path)[f"core:{spec.sid.removeprefix('homm3_')}"]["town"]
    hall_slots = flatten_hall_slots(town["hallSlots"])
    icon_def = find_case_insensitive_file(THIRD_UPGRADES / spec.third_sprite_dir / spec.icon_def)
    _town_root, _layers_dir, _anims_dir, icons_dir, icon_source_map = spec_paths(spec)
    if icons_dir.exists():
        shutil.rmtree(icons_dir)
    icons_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix=f"{spec.sid}-hall-icons-", ignore_cleanup_errors=True) as tmp:
        _manifest, frames = extract_def(icon_def, Path(tmp))
        for index, frame_path in enumerate(frames):
            shutil.copy2(frame_path, icons_dir / f"00_{index:02d}.png")
    copy_icon_json_overrides(spec, icon_def, icons_dir)

    slot_by_name = icon_frame_index_by_slot(town, hall_slots)
    icon_map: dict[str, dict[str, Any]] = {}
    for hall_slot, (building_sid, level) in spec.hall_slot_to_olden.items():
        if hall_slot not in slot_by_name:
            continue
        icon_map.setdefault(building_sid, {})[str(level)] = f"00_{slot_by_name[hall_slot]:02d}.png"
    explicit_reuse: dict[str, dict[str, str]] = {}
    for (building_sid, level), (source_slot, reason) in spec.explicit_icon_reuse.items():
        if source_slot not in slot_by_name:
            raise RuntimeError(f"{spec.sid}: explicit icon source slot not found: {source_slot}")
        icon_map.setdefault(building_sid, {})[str(level)] = f"00_{slot_by_name[source_slot]:02d}.png"
        explicit_reuse[f"{building_sid}:{level}"] = {"sourceSlot": source_slot, "reason": reason}
    mapped_slots = set(spec.hall_slot_to_olden)
    source_map = {
        "_comment": f"{spec.sid} build-tree icon indices follow VCMI/HoMM3 building frame IDs, not hallSlots index order.",
        "vcmiTownConfig": relative(town_config_path),
        "folder": spec.icon_folder,
        "explicitReuse": explicit_reuse,
        "unmappedHallSlots": [slot for slot in hall_slots if slot not in mapped_slots],
        "map": icon_map,
    }
    icon_source_map.write_text(json.dumps(source_map, indent=2) + "\n", encoding="utf-8")
    print(f"{spec.sid}: wrote {len(list(icons_dir.glob('*.png')))} hall icon frames")


def copy_icon_json_overrides(spec: FactionSpec, icon_def: Path, icons_dir: Path) -> None:
    sidecar = icon_def.with_suffix(".json")
    if not sidecar.is_file():
        return
    data = load_jsonc(sidecar)
    basepath = str(data.get("basepath") or "").replace("\\", "/").strip("/")
    if not basepath:
        return
    if basepath.startswith("town-screen/"):
        source_root = THIRD_UPGRADES / "content" / "sprites" / basepath
    else:
        source_root = icon_def.parent / basepath
    for entry in data.get("images") or []:
        frame = int(entry["frame"])
        file_stem = str(entry["file"])
        source = find_case_insensitive_file(source_root / (file_stem + ".png"))
        shutil.copy2(source, icons_dir / f"00_{frame:02d}.png")


def check_sources(spec: FactionSpec) -> None:
    town_root, _layers_dir, _anims_dir, _icons_dir, _source_map = spec_paths(spec)
    required = [
        town_root / spec.source_bg,
        THIRD_UPGRADES / spec.town_config,
        THIRD_UPGRADES / spec.third_sprite_dir / spec.icon_def,
        LOD_EXTRACT,
        DEF_EXTRACT,
    ]
    missing = [path for path in required if not path.exists()]
    if missing:
        raise FileNotFoundError("missing source(s):\n" + "\n".join(str(path) for path in missing))
    for layer in spec.third_layers:
        find_case_insensitive_file(THIRD_UPGRADES / spec.third_sprite_dir / layer.source)
    with tempfile.TemporaryDirectory(prefix=f"{spec.sid}-source-check-", ignore_cleanup_errors=True) as tmp:
        temp_root = Path(tmp)
        for layer in spec.base_layers:
            extract_lod_def(layer.source, temp_root)


def build_faction(spec: FactionSpec, check_only: bool = False) -> None:
    check_sources(spec)
    if check_only:
        print(f"{spec.sid}: sources present")
        return
    write_source_background(spec)
    build_mockup(spec)
    build_layers(spec)
    build_icons(spec)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "factions",
        nargs="*",
        choices=sorted(FACTIONS),
        help="Faction(s) to build. Defaults to both.",
    )
    parser.add_argument("--check-sources", action="store_true", help="Only verify declared source assets exist.")
    args = parser.parse_args()

    for name in args.factions or sorted(FACTIONS):
        build_faction(FACTIONS[name], check_only=args.check_sources)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
