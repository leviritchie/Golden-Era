#!/usr/bin/env python3
"""Build Fortress town-screen assets from local HoMM3 and VCMI sources.

Base Fortress building layers come from the local VCMI game root's
Data/H3sprite.lod. Their placement data follows the VCMI core Fortress town
structure config. Third-upgrade overlays and build-tree icons continue to come
from the checked-in VCMI third-upgrades mod.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image

from prebake_homm3_town_scene_coordinates import prebake_mockup, prebake_positions_file


ROOT = Path(__file__).resolve().parents[1]
TOWN_ROOT = (
    ROOT
    / "Heroes of Might & Magic Olden Era Playtest"
    / "OfflineUnlockMod"
    / "homm3_runtime_assets"
    / "town_scene_refs"
    / "homm3_fortress"
)
SOURCE_BG = TOWN_ROOT / "Fortress-in-background.png"
MOCKUP = TOWN_ROOT / "mockups" / "homm3_fortress_background_mock_1920x1080.png"
LAYERS_DIR = TOWN_ROOT / "layers"
ANIMS_DIR = LAYERS_DIR / "anims"
POSITIONS_JSON = LAYERS_DIR / "positions.json"
BUILDING_LAYER_MAP_JSON = LAYERS_DIR / "building_layer_map.json"
BUILDING_ICONS_DIR = TOWN_ROOT / "building_icons" / "hallfortalt.dir"
BUILDING_ICON_SOURCE_MAP = TOWN_ROOT / "building_icons" / "hallfortalt_source_map.json"

H3SPRITE_LOD = ROOT / "vcmi" / "Data" / "H3sprite.lod"
THIRD_DEF_SOURCE = ROOT / "vcmi" / "Mods" / "third-upgrades" / "content" / "sprites" / "town-screen" / "fortress"
VCMI_THIRD_TOWN_CONFIG = (
    ROOT
    / "vcmi"
    / "Mods"
    / "third-upgrades"
    / "content"
    / "config"
    / "town-screen"
    / "fortress"
    / "factions.json"
)
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

# id, structure key, DEF, level, x, y, z
BASE_LAYER_SPECS = [
    ("tbfrext2", "extraAnimation", "TBFREXT2.def", 1, 372, 227, -1),
    ("tbfrmage", "mageGuild1", "TBFRMAGE.def", 1, 0, 200, -1),
    ("tbfrmage_2", "mageGuild2", "TBFRMAG2.def", 2, 0, 177, -1),
    ("tbfrmage_3", "mageGuild3", "TBFRMAG3.def", 3, 0, 135, -1),
    ("tbfrtvrn", "tavern", "TBFRTVRN.def", 1, 634, 219, 3),
    ("tbfrdock", "shipyard", "TBFRDOCK.def", 1, 197, 294, 1),
    ("tbfrcstl", "fort", "TBFRCSTL.def", 1, 368, 118, -2),
    ("tbfrcstl_2", "citadel", "TBFRCAS2.def", 2, 368, 98, -2),
    ("tbfrcstl_3", "castle", "TBFRCAS3.def", 3, 368, 55, -2),
    ("tbfrhall", "villageHall", "TBFRHALL.def", 1, 166, 128, 3),
    ("tbfrhall_2", "townHall", "TBFRHAL2.def", 2, 166, 97, 3),
    ("tbfrhall_3", "cityHall", "TBFRHAL3.def", 3, 166, 51, 3),
    ("tbfrhall_4", "capitol", "TBFRHAL4.def", 4, 166, 2, 3),
    ("tbfrmark", "marketplace", "TBFRMARK.def", 1, 382, 219, 4),
    ("tbfrsilo", "resourceSilo", "TBFRSILO.def", 1, 448, 210, 2),
    ("tbfrblak", "blacksmith", "TBFRBLAK.def", 1, 360, 160, 1),
    ("tbfrspec", "special1", "TBFRSPEC.def", 1, 703, 36, 0),
    ("tbfrhrd1", "horde1", "TBFRHRD1.def", 1, 641, 121, 1),
    ("tbfrhrd2", "horde1Upgr", "TBFRHRD2.def", 2, 641, 68, 1),
    ("tbfrboat", "ship", "TBFRBOAT.def", 1, 197, 294, 1),
    ("tbfrext0", "special2", "TBFREXT0.def", 1, 341, 174, 0),
    ("tbfrext1", "special3", "TBFREXT1.def", 1, 349, 79, -3),
    ("tbfrholy", "grail", "TBFRHOLY.def", 1, 468, 260, 5),
    ("tbfrdw_0", "dwellingLvl1", "TBFRDW_0.def", 1, 641, 168, 1),
    ("tbfrdw_1", "dwellingLvl2", "TBFRDW_1.def", 1, 141, 178, 0),
    ("tbfrdw_3", "dwellingLvl3", "TBFRDW_3.def", 1, 194, 86, 0),
    ("tbfrdw_4", "dwellingLvl4", "TBFRDW_4.def", 1, 0, 292, 1),
    ("tbfrdw_2", "dwellingLvl5", "TBFRDW_2.def", 1, 15, 127, -2),
    ("tbfrdw_5", "dwellingLvl6", "TBFRDW_5.def", 1, 0, 4, 0),
    ("tbfrdw_6", "dwellingLvl7", "TBFRDW_6.def", 1, 612, 291, 5),
    ("tbfrdw_0_2", "dwellingUpLvl1", "TBFRUP_0.def", 2, 641, 107, 1),
    ("tbfrdw_1_2", "dwellingUpLvl2", "TBFRUP_1.def", 2, 125, 163, 0),
    ("tbfrdw_3_2", "dwellingUpLvl3", "TBFRUP_3.def", 2, 159, 18, 0),
    ("tbfrdw_4_2", "dwellingUpLvl4", "TBFRUP_4.def", 2, 0, 257, 1),
    ("tbfrdw_2_2", "dwellingUpLvl5", "TBFRUP_2.def", 2, 15, 69, -2),
    ("tbfrdw_5_2", "dwellingUpLvl6", "TBFRUP_5.def", 2, 0, 4, 0),
    ("tbfrdw_6_2", "dwellingUpLvl7", "TBFRUP_6.def", 2, 587, 263, 5),
]

# layer id, VCMI structure key, source DEF, x, y, z
THIRD_UPGRADE_LAYER_SPECS = [
    ("tbfrtext5", "extraCapitol", "TBFTEXT5.def", 415, 0, -6),
    ("tbfrhrd3", "horde2", "TBFrHrd3.def", 641, 68, 1),
    ("tbfrdw_0_3", "dwellingUp2Lvl1", "TBFRUP2_0.def", 641, 107, 1),
    ("tbfrdw_1_3", "dwellingUp2Lvl2", "TBFRUP2_1.def", 125, 163, 0),
    ("tbfrdw_3_3", "dwellingUp2Lvl3", "TBFRUP2_2.def", 159, 19, 0),
    ("tbfrdw_4_3", "dwellingUp2Lvl4", "TBFRUP2_3.def", 0, 257, 0),
    ("tbfrdw_2_3", "dwellingUp2Lvl5", "TBFRUP2_5.def", 15, -12, -2),
    ("tbfrdw_5_3", "dwellingUp2Lvl6", "TBFRUP2_4.def", 0, 4, 0),
    ("tbfrdw_6_3", "dwellingUp2Lvl7", "TBFRUP2_6.def", 587, 263, 5),
]

BUILDING_LAYER_IDS = {
    "Build_Main": "tbfrhall",
    "Build_Wall": "tbfrcstl",
    "Build_Tavern": "tbfrtvrn",
    "Build_Treasury": "tbfrblak",
    "Build_Market": "tbfrmark",
    "Build_Resource_Depot": "tbfrsilo",
    "Build_Magic_Guild": "tbfrmage",
    "Build_Bank": "tbfrspec",
    "Build_Artifact_Market": "tbfrdock",
    "Build_Mother_Nature": "tbfrext0",
    "Build_Mycelium_Roots": "tbfrext1",
    "Build_Resource_Depot_level_2": "tbfrhrd2",
    "Build_Spring_of_Life": "tbfrholy",
    "Build_Tier_1": "tbfrdw_0",
    "Build_Tier_2": "tbfrdw_1",
    "Build_Tier_3": "tbfrdw_3",
    "Build_Tier_4": "tbfrdw_4",
    "Build_Tier_5": "tbfrdw_2",
    "Build_Tier_6": "tbfrdw_5",
    "Build_Tier_7": "tbfrdw_6",
}

HALL_SLOT_TO_OLDEN = {
    "villageHall": ("Build_Main", 1),
    "townHall": ("Build_Main", 2),
    "cityHall": ("Build_Main", 3),
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
    "special1": ("Build_Bank", 1),
    "shipyard": ("Build_Artifact_Market", 1),
    "special2": ("Build_Mother_Nature", 1),
    "special3": ("Build_Mycelium_Roots", 1),
    "horde1Upgr": ("Build_Resource_Depot_level_2", 1),
    "dwellingLvl1": ("Build_Tier_1", 1),
    "dwellingUpLvl1": ("Build_Tier_1", 2),
    "dwellingLvl2": ("Build_Tier_2", 1),
    "dwellingUpLvl2": ("Build_Tier_2", 2),
    "dwellingLvl3": ("Build_Tier_3", 1),
    "dwellingUpLvl3": ("Build_Tier_3", 2),
    "dwellingLvl4": ("Build_Tier_4", 1),
    "dwellingUpLvl4": ("Build_Tier_4", 2),
    "dwellingLvl5": ("Build_Tier_5", 1),
    "dwellingUpLvl5": ("Build_Tier_5", 2),
    "dwellingLvl6": ("Build_Tier_6", 1),
    "dwellingUpLvl6": ("Build_Tier_6", 2),
    "dwellingLvl7": ("Build_Tier_7", 1),
    "dwellingUpLvl7": ("Build_Tier_7", 2),
}

EXPLICIT_ICON_REUSE = {
    ("Build_Magic_Guild", 4): (
        "mageGuild3",
        "VCMI third-upgrades Fortress source has no mageGuild4 frame; reuse mageGuild3 explicitly.",
    ),
    ("Build_Magic_Guild", 5): (
        "mageGuild3",
        "VCMI third-upgrades Fortress source has no mageGuild5 frame; reuse mageGuild3 explicitly.",
    ),
}

EXPLICIT_ICON_FILES = {
    ("Build_Spring_of_Life", 1): (
        "../layers",
        "tbfrholy.png",
        "VCMI hallSlots do not include the Fortress grail; use the generated grail town layer as its build-tree icon.",
    ),
}

THIRD_STRUCTURE_TO_OLDEN = {
    "dwellingUp2Lvl1": ("Build_Tier_1", 3),
    "dwellingUp2Lvl2": ("Build_Tier_2", 3),
    "dwellingUp2Lvl3": ("Build_Tier_3", 3),
    "dwellingUp2Lvl4": ("Build_Tier_4", 3),
    "dwellingUp2Lvl5": ("Build_Tier_5", 3),
    "dwellingUp2Lvl6": ("Build_Tier_6", 3),
    "dwellingUp2Lvl7": ("Build_Tier_7", 3),
}


def strip_json_comments(text: str) -> str:
    text = re.sub(r"//.*", "", text)
    return re.sub(r"/\*.*?\*/", "", text, flags=re.S)


def load_vcmi_third_town_config() -> dict:
    if not VCMI_THIRD_TOWN_CONFIG.is_file():
        raise RuntimeError(f"missing Fortress VCMI town config: {VCMI_THIRD_TOWN_CONFIG}")
    data = json.loads(strip_json_comments(VCMI_THIRD_TOWN_CONFIG.read_text(encoding="utf-8-sig")))
    return data["core:fortress"]["town"]


def flatten_hall_slots(hall_slots: list) -> list[str]:
    result: list[str] = []

    def walk(value: object) -> None:
        if isinstance(value, str):
            result.append(value)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(hall_slots)
    return result


def icon_frame_index_by_slot(town_config: dict, hall_slots: list[str]) -> dict[str, int]:
    result = {name: index for index, name in enumerate(hall_slots)}
    result.update(COMMON_ICON_FRAME_ID_BY_SLOT)
    for structure, data in (town_config.get("buildings") or {}).items():
        if not isinstance(data, dict):
            continue
        frame_id = data.get("id")
        if isinstance(frame_id, int) and frame_id >= 0:
            result[structure] = frame_id
    return result


def expected_hall_icon_map(town_config: dict) -> dict[str, dict[int, object]]:
    result: dict[str, dict[int, object]] = {}
    slots = flatten_hall_slots(town_config["hallSlots"])
    slot_by_name = icon_frame_index_by_slot(town_config, slots)
    for hall_slot, (building_sid, level) in HALL_SLOT_TO_OLDEN.items():
        if hall_slot not in slot_by_name:
            raise RuntimeError(f"VCMI Fortress hallSlots missing expected slot {hall_slot}")
        result.setdefault(building_sid, {})[level] = f"00_{slot_by_name[hall_slot]:02d}.png"
    for (building_sid, level), (source_slot, _reason) in EXPLICIT_ICON_REUSE.items():
        if source_slot not in slot_by_name:
            raise RuntimeError(f"VCMI Fortress hallSlots missing explicit reuse source {source_slot}")
        result.setdefault(building_sid, {})[level] = f"00_{slot_by_name[source_slot]:02d}.png"
    for (building_sid, level), (folder, file_name, _reason) in EXPLICIT_ICON_FILES.items():
        result.setdefault(building_sid, {})[level] = {"folder": folder, "file": file_name}
    return result


def validate_source_contract(town_config: dict) -> None:
    if not H3SPRITE_LOD.is_file():
        raise RuntimeError(f"missing local VCMI H3sprite.lod: {H3SPRITE_LOD}")
    if not LOD_EXTRACT.is_file():
        raise RuntimeError(f"missing LOD extraction helper: {LOD_EXTRACT}")
    if not DEF_EXTRACT.is_file():
        raise RuntimeError(f"missing DEF extraction helper: {DEF_EXTRACT}")

    structures = town_config.get("structures") or {}
    for _layer_id, structure, source_name, expected_x, expected_y, expected_z in THIRD_UPGRADE_LAYER_SPECS:
        source_spec = structures.get(structure)
        if not isinstance(source_spec, dict):
            raise RuntimeError(f"VCMI third-upgrades Fortress structures missing {structure}")
        actual_source = Path(source_spec.get("animation", "")).name
        if actual_source.lower() != source_name.lower():
            raise RuntimeError(f"{structure}: source mismatch {source_name} != {actual_source}")
        if int(source_spec.get("x", 0)) != expected_x:
            raise RuntimeError(f"{structure}: x mismatch {expected_x} != {source_spec.get('x')}")
        if int(source_spec.get("y", 0)) != expected_y:
            raise RuntimeError(f"{structure}: y mismatch {expected_y} != {source_spec.get('y')}")
        if int(source_spec.get("z", 0)) != expected_z:
            raise RuntimeError(f"{structure}: z mismatch {expected_z} != {source_spec.get('z', 0)}")


def build_mockup() -> None:
    prebake_mockup(SOURCE_BG, MOCKUP)


def extract_def(def_path: Path, temp_root: Path) -> tuple[dict, Path]:
    subprocess.run([sys.executable, str(DEF_EXTRACT), str(def_path), str(temp_root)], check=True)
    manifest_path = temp_root / (def_path.stem.lower() + ".json")
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    return data, temp_root / (def_path.stem.lower() + ".dir")


def extract_lod_def(def_name: str, temp_root: Path) -> Path:
    out_path = temp_root / def_name
    subprocess.run([sys.executable, str(LOD_EXTRACT), str(H3SPRITE_LOD), def_name, str(out_path)], check=True)
    if not out_path.is_file():
        raise RuntimeError(f"failed to extract {def_name} from {H3SPRITE_LOD}")
    return out_path


def extract_frames(def_path: Path, temp_root: Path) -> tuple[list[Path], Path]:
    data, frames_dir = extract_def(def_path, temp_root)
    frames: list[Path] = []
    for seq in data.get("sequences") or []:
        for rel_path in seq.get("frames") or []:
            candidate = temp_root / rel_path.replace("\\", "/")
            if candidate.is_file():
                frames.append(candidate)
    if not frames:
        frames = sorted(frames_dir.glob("*.png"))
    if not frames:
        raise RuntimeError(f"{def_path}: no extracted PNG frames")
    return frames, frames_dir


def save_layer_image(src: Path, layer_id: str, level: int) -> None:
    image = Image.open(src).convert("RGBA")
    image.save(LAYERS_DIR / f"{layer_id}.png", optimize=True)
    image.close()


def anim_key_for_structure(layer_id: str, structure: str) -> str:
    mapped = HALL_SLOT_TO_OLDEN.get(structure) or THIRD_STRUCTURE_TO_OLDEN.get(structure)
    if mapped == ("Build_Resource_Depot_level_2", 1):
        return "tbfrhrd2_1"
    if mapped:
        building_sid, level = mapped
        root_id = BUILDING_LAYER_IDS.get(building_sid)
        if root_id:
            return f"{root_id}_{level}"
    return f"{layer_id}_1"


def write_positions(placements: list[dict]) -> None:
    POSITIONS_JSON.write_text(
        json.dumps(
            {
                "_comment": (
                    "Fortress top-left layer positions on the native 800x374 HoMM3 town canvas. "
                    "Base TBFR*.def layers come from local vcmi/Data/H3sprite.lod; third-upgrade "
                    "overlays are validated against local VCMI third-upgrades town-screen config."
                ),
                "source": "VCMI core config/factions/fortress.json plus local third-upgrades config",
                "canvas_w": SOURCE_SIZE[0],
                "canvas_h": SOURCE_SIZE[1],
                "layers": placements,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    prebake_positions_file(POSITIONS_JSON)


def write_building_layer_map() -> None:
    BUILDING_LAYER_MAP_JSON.write_text(
        json.dumps(
            {
                "_comment": (
                    "Fortress visual mapping. Keys are this worktree's Olden Era building SIDs; "
                    "values are HoMM3 Fortress DEF-name layer roots. Runtime appends the building "
                    "level, so tbfrdw_0 resolves to tbfrdw_0, tbfrdw_0_2, or tbfrdw_0_3."
                ),
                "buildingLayerIds": BUILDING_LAYER_IDS,
                "sourceCrosswalk": {
                    "Build_Treasury": "Fortress Blacksmith/First Aid Tent visual from tbfrblak; retained donor economy SID.",
                    "Build_Bank": "Fortress Cage of Warlords visual from tbfrspec; retained donor economy SID.",
                    "Build_Artifact_Market": "Fortress Shipyard visual from tbfrdock; retained donor artifact-market SID.",
                    "Build_Mother_Nature": "Fortress Glyphs of Fear visual from tbfrext0; retained donor hero-bonus SID.",
                    "Build_Mycelium_Roots": "Fortress Blood Obelisk visual from tbfrext1; retained donor special-building SID.",
                    "Build_Resource_Depot_level_2": "Fortress Captain's Quarters horde-upgrade visual from tbfrhrd2; retained donor resource-upgrade SID.",
                    "Build_Spring_of_Life": "Fortress Carnivorous Plant grail visual from tbfrholy; retained donor grail SID.",
                },
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def build_layers() -> list[dict]:
    if LAYERS_DIR.exists():
        shutil.rmtree(LAYERS_DIR)
    LAYERS_DIR.mkdir(parents=True, exist_ok=True)

    placements: list[dict] = []
    order = 0
    with tempfile.TemporaryDirectory(prefix="homm3-fortress-town-defs-", ignore_cleanup_errors=True) as tmp:
        temp_root = Path(tmp)
        for layer_id, structure, def_name, level, x, y, z in BASE_LAYER_SPECS:
            def_path = extract_lod_def(def_name, temp_root)
            frames, _ = extract_frames(def_path, temp_root)
            save_layer_image(frames[0], layer_id, level)
            placements.append(
                {"id": layer_id, "structure": structure, "x": x, "y": y, "z": z, "order": order, "sprite": f"{layer_id}.png"}
            )
            order += 1
            print(f"{layer_id}: {def_name} -> {layer_id}.png")

        for layer_id, structure, def_name, x, y, z in THIRD_UPGRADE_LAYER_SPECS:
            source = THIRD_DEF_SOURCE / def_name
            if not source.is_file():
                raise RuntimeError(f"missing Fortress third-upgrade layer source: {source}")
            frames, _ = extract_frames(source, temp_root)
            save_layer_image(frames[0], layer_id, 1)
            placements.append(
                {"id": layer_id, "structure": structure, "x": x, "y": y, "z": z, "order": order, "sprite": f"{layer_id}.png"}
            )
            order += 1
            print(f"{layer_id}: {def_name} -> {layer_id}.png")

    write_positions(placements)
    write_building_layer_map()
    return placements


def build_anims() -> None:
    ANIMS_DIR.mkdir(parents=True, exist_ok=True)
    metadata = []
    with tempfile.TemporaryDirectory(prefix="homm3-fortress-town-anims-", ignore_cleanup_errors=True) as tmp:
        temp_root = Path(tmp)
        all_specs = [
            ("lod", anim_key_for_structure(layer_id, structure), def_name)
            for layer_id, structure, def_name, _level, _x, _y, _z in BASE_LAYER_SPECS
        ] + [
            ("third", anim_key_for_structure(layer_id, structure), def_name)
            for layer_id, structure, def_name, _x, _y, _z in THIRD_UPGRADE_LAYER_SPECS
        ]
        for source_kind, anim_id, def_name in all_specs:
            source = extract_lod_def(def_name, temp_root) if source_kind == "lod" else THIRD_DEF_SOURCE / def_name
            if not source.is_file():
                raise RuntimeError(f"missing Fortress animation source: {source}")
            frames, _ = extract_frames(source, temp_root)
            if len(frames) <= 1:
                continue
            dest_dir = ANIMS_DIR / anim_id
            dest_dir.mkdir(parents=True, exist_ok=True)
            frame_names = []
            for index, frame in enumerate(frames):
                dest_name = f"frame_{index:02d}.png"
                shutil.copy2(frame, dest_dir / dest_name)
                frame_names.append(dest_name)
            metadata.append({"id": anim_id, "frameRateMs": FRAME_RATE_MS, "frames": frame_names})
            print(f"{anim_id}: {def_name} -> {len(frame_names)} animation frames")
    (ANIMS_DIR / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(metadata)} Fortress town animation entries to {ANIMS_DIR / 'metadata.json'}")


def build_building_icons(town_config: dict) -> None:
    if BUILDING_ICONS_DIR.exists():
        shutil.rmtree(BUILDING_ICONS_DIR)
    BUILDING_ICONS_DIR.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="homm3-fortress-icons-", ignore_cleanup_errors=True) as tmp:
        temp_root = Path(tmp)
        _, frames_dir = extract_def(THIRD_DEF_SOURCE / "hallfortAlt.def", temp_root)
        for frame in sorted(frames_dir.glob("*.png")):
            shutil.copy2(frame, BUILDING_ICONS_DIR / frame.name)

    source_frames = THIRD_DEF_SOURCE / "frames"
    if source_frames.is_dir():
        dest_frames = BUILDING_ICONS_DIR.parent / "frames"
        if dest_frames.exists():
            shutil.rmtree(dest_frames)
        shutil.copytree(source_frames, dest_frames)

    BUILDING_ICON_SOURCE_MAP.write_text(
        json.dumps(
            {
                "_comment": (
                    "Fortress build-tree icon indices follow local VCMI third-upgrades "
                    "VCMI/HoMM3 building frame IDs, not hallSlots index order."
                ),
                "vcmiTownConfig": str(VCMI_THIRD_TOWN_CONFIG.relative_to(ROOT)).replace("\\", "/"),
                "folder": "hallfortalt.dir",
                "explicitReuse": {
                    f"{building_sid}:{level}": {"sourceSlot": source_slot, "reason": reason}
                    for (building_sid, level), (source_slot, reason) in EXPLICIT_ICON_REUSE.items()
                },
                "explicitFiles": {
                    f"{building_sid}:{level}": {"folder": folder, "file": file_name, "reason": reason}
                    for (building_sid, level), (folder, file_name, reason) in EXPLICIT_ICON_FILES.items()
                },
                "unmappedHallSlots": [
                    name
                    for name in flatten_hall_slots(town_config["hallSlots"])
                    if name not in HALL_SLOT_TO_OLDEN
                    and name not in {source_slot for source_slot, _reason in EXPLICIT_ICON_REUSE.values()}
                ],
                "map": expected_hall_icon_map(town_config),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"Wrote Fortress building icons to {BUILDING_ICONS_DIR}")


def main() -> int:
    town_config = load_vcmi_third_town_config()
    validate_source_contract(town_config)
    build_mockup()
    build_layers()
    build_anims()
    build_building_icons(town_config)
    print(f"Wrote {MOCKUP}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
