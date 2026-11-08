#!/usr/bin/env python3
"""Build Castle and Rampart town-screen layers and build-tree icons.

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
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image

from prebake_homm3_town_scene_coordinates import prebake_mockup, prebake_positions_file


ROOT = Path(__file__).resolve().parents[1]
PLUGIN_ROOT = ROOT / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod"
TOWN_SCENE_ROOT = PLUGIN_ROOT / "homm3_runtime_assets" / "town_scene_refs"
H3SPRITE_LOD = ROOT / "vcmi" / "Data" / "H3sprite.lod"
DEF_EXTRACT = ROOT / "tools" / "defextract_py3.py"
LOD_EXTRACT = ROOT / "tools" / "lod_extract_entry_py3.py"
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


@dataclass(frozen=True)
class LayerSpec:
    layer_id: str
    structure: str
    source: str
    x: int
    y: int
    z: int = 0
    level: int = 1
    third: bool = False


@dataclass(frozen=True)
class FactionSpec:
    sid: str
    display: str
    background_name: str
    third_dir: str
    town_config: Path
    icon_def: str
    icon_folder: str
    icon_source_map: str
    base_layers: tuple[LayerSpec, ...]
    third_layers: tuple[LayerSpec, ...]
    building_layer_ids: dict[str, str]
    building_levels: dict[str, dict[int, str]]
    hall_slot_to_olden: dict[str, tuple[str, int]]
    explicit_icon_reuse: dict[tuple[str, int], tuple[str, str]]
    explicit_icon_files: dict[tuple[str, int], tuple[str, str, str]]
    source_crosswalk: dict[str, str]


def strip_json_comments(text: str) -> str:
    text = re.sub(r"//.*", "", text)
    return re.sub(r"/\*.*?\*/", "", text, flags=re.S)


def load_jsonc(path: Path) -> Any:
    return json.loads(strip_json_comments(path.read_text(encoding="utf-8-sig")))


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


def icon_frame_index_by_slot(town_config: dict[str, Any], slots: list[str]) -> dict[str, int]:
    result = {name: index for index, name in enumerate(slots)}
    result.update(COMMON_ICON_FRAME_ID_BY_SLOT)
    for structure, data in (town_config.get("buildings") or {}).items():
        if not isinstance(data, dict):
            continue
        frame_id = data.get("id")
        if isinstance(frame_id, int) and frame_id >= 0:
            result[structure] = frame_id
    return result


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT)).replace("\\", "/")


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
    out_path = temp_root / def_name
    subprocess.run([sys.executable, str(LOD_EXTRACT), str(H3SPRITE_LOD), def_name, str(out_path)], check=True)
    if not out_path.is_file():
        raise RuntimeError(f"failed to extract {def_name} from {H3SPRITE_LOD}")
    return out_path


def extract_def(def_path: Path, temp_root: Path) -> tuple[dict[str, Any], list[Path]]:
    temp_root.mkdir(parents=True, exist_ok=True)
    subprocess.run([sys.executable, str(DEF_EXTRACT), str(def_path), str(temp_root)], check=True)
    manifest_path = temp_root / (def_path.stem.lower() + ".json")
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    frames: list[Path] = []
    for seq in data.get("sequences") or []:
        for rel_path in seq.get("frames") or []:
            candidate = temp_root / rel_path.replace("\\", "/")
            if candidate.is_file():
                frames.append(candidate)
    if not frames:
        frames = sorted((temp_root / (def_path.stem.lower() + ".dir")).glob("*.png"))
    if not frames:
        raise RuntimeError(f"{def_path}: no extracted PNG frames")
    return data, frames


def build_mockup(spec: FactionSpec) -> None:
    town_root = TOWN_SCENE_ROOT / spec.sid
    mockup = town_root / "mockups" / f"{spec.sid}_background_mock_1920x1080.png"
    prebake_mockup(town_root / spec.background_name, mockup)


def source_def_path(spec: FactionSpec, layer: LayerSpec, temp_root: Path) -> Path:
    if layer.third:
        source = THIRD_ROOT / "sprites" / "town-screen" / spec.third_dir / layer.source
        if not source.is_file():
            raise RuntimeError(f"missing {spec.display} third-upgrade source: {source}")
        return source
    return extract_lod_def(layer.source, temp_root)


def save_layer_frames(
    spec: FactionSpec,
    layer: LayerSpec,
    def_path: Path,
    temp_root: Path,
    layers_dir: Path,
    anims_dir: Path,
    anim_metadata: list[dict[str, Any]],
) -> None:
    _manifest, frames = extract_def(def_path, temp_root / layer.layer_id)
    sprite = Image.open(frames[0]).convert("RGBA")
    sprite.save(layers_dir / f"{layer.layer_id}.png", optimize=True)

    if len(frames) > 1:
        anim_dir = anims_dir / layer.layer_id
        anim_dir.mkdir(parents=True, exist_ok=True)
        frame_names: list[str] = []
        for index, frame_path in enumerate(frames):
            frame_name = f"frame_{index:02d}.png"
            Image.open(frame_path).convert("RGBA").save(anim_dir / frame_name, optimize=True)
            frame_names.append(frame_name)
        anim_metadata.append({"id": layer.layer_id, "frameRateMs": FRAME_RATE_MS, "frames": frame_names})

    print(f"{spec.sid}: {layer.layer_id}: {layer.source} -> {layer.layer_id}.png")


def build_layers(spec: FactionSpec) -> None:
    town_root = TOWN_SCENE_ROOT / spec.sid
    layers_dir = town_root / "layers"
    anims_dir = layers_dir / "anims"
    if layers_dir.exists():
        shutil.rmtree(layers_dir)
    layers_dir.mkdir(parents=True, exist_ok=True)
    anims_dir.mkdir(parents=True, exist_ok=True)

    placements: list[dict[str, Any]] = []
    anim_metadata: list[dict[str, Any]] = []
    order = 0
    with tempfile.TemporaryDirectory(prefix=f"{spec.sid}-town-defs-", ignore_cleanup_errors=True) as tmp:
        temp_root = Path(tmp)
        for layer in (*spec.base_layers, *spec.third_layers):
            source = source_def_path(spec, layer, temp_root)
            save_layer_frames(spec, layer, source, temp_root, layers_dir, anims_dir, anim_metadata)
            placements.append(
                {
                    "id": layer.layer_id,
                    "structure": layer.structure,
                    "x": layer.x,
                    "y": layer.y,
                    "z": layer.z,
                    "order": order,
                    "sprite": f"{layer.layer_id}.png",
                }
            )
            order += 1

    (anims_dir / "metadata.json").write_text(json.dumps(anim_metadata, indent=2) + "\n", encoding="utf-8")
    positions_path = layers_dir / "positions.json"
    positions_path.write_text(
        json.dumps(
            {
                "_comment": (
                    f"{spec.display} top-left layer positions on the native 800x374 HoMM3 town canvas. "
                    "Base layer coordinates mirror VCMI core faction configs and base art comes from vcmi/Data/H3sprite.lod; "
                    "third-upgrade overlays come from local VCMI third-upgrades."
                ),
                "source": f"VCMI core config/factions plus {rel(spec.town_config)} and vcmi/Data/H3sprite.lod",
                "canvas_w": SOURCE_SIZE[0],
                "canvas_h": SOURCE_SIZE[1],
                "layers": placements,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    prebake_positions_file(positions_path)
    (layers_dir / "building_layer_map.json").write_text(
        json.dumps(
            {
                "_comment": (
                    f"{spec.display} visual mapping. Keys are Olden Era building SIDs; values are HoMM3 layer roots. "
                    "Runtime appends the constructed level when a matching level-specific layer exists."
                ),
                "buildingLayerIds": spec.building_layer_ids,
                "levels": {key: {str(level): value for level, value in levels.items()} for key, levels in spec.building_levels.items()},
                "sourceCrosswalk": spec.source_crosswalk,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def expected_hall_icon_map(spec: FactionSpec, town_config: dict[str, Any]) -> dict[str, dict[int, Any]]:
    result: dict[str, dict[int, Any]] = {}
    slots = flatten_hall_slots(town_config["hallSlots"])
    slot_by_name = icon_frame_index_by_slot(town_config, slots)
    for hall_slot, (building_sid, level) in spec.hall_slot_to_olden.items():
        if hall_slot not in slot_by_name:
            raise RuntimeError(f"{spec.display} hallSlots missing expected slot {hall_slot}")
        result.setdefault(building_sid, {})[level] = f"00_{slot_by_name[hall_slot]:02d}.png"
    for (building_sid, level), (source_slot, _reason) in spec.explicit_icon_reuse.items():
        if source_slot not in slot_by_name:
            raise RuntimeError(f"{spec.display} hallSlots missing explicit reuse source {source_slot}")
        result.setdefault(building_sid, {})[level] = f"00_{slot_by_name[source_slot]:02d}.png"
    for (building_sid, level), (folder, file_name, _reason) in spec.explicit_icon_files.items():
        result.setdefault(building_sid, {})[level] = {"folder": folder, "file": file_name}
    return result


def build_icons(spec: FactionSpec, town_config: dict[str, Any]) -> None:
    town_root = TOWN_SCENE_ROOT / spec.sid
    icons_root = town_root / "building_icons"
    icons_dir = icons_root / spec.icon_folder
    source_map = icons_root / spec.icon_source_map
    if icons_dir.exists():
        shutil.rmtree(icons_dir)
    icons_dir.mkdir(parents=True, exist_ok=True)

    icon_def_path = THIRD_ROOT / "sprites" / "town-screen" / spec.third_dir / spec.icon_def
    with tempfile.TemporaryDirectory(prefix=f"{spec.sid}-icons-", ignore_cleanup_errors=True) as tmp:
        _manifest, frames = extract_def(icon_def_path, Path(tmp))
        for frame in frames:
            shutil.copy2(frame, icons_dir / frame.name)
    copy_icon_json_overrides(icon_def_path, icons_dir)

    frames_dir = THIRD_ROOT / "sprites" / "town-screen" / spec.third_dir / "frames"
    if frames_dir.is_dir():
        dest_frames = icons_root / "frames"
        if dest_frames.exists():
            shutil.rmtree(dest_frames)
        shutil.copytree(frames_dir, dest_frames)

    slots = flatten_hall_slots(town_config["hallSlots"])
    source_map.write_text(
        json.dumps(
            {
                "_comment": f"{spec.display} build-tree icon indices follow VCMI/HoMM3 building frame IDs, not hallSlots index order.",
                "vcmiTownConfig": rel(spec.town_config),
                "folder": spec.icon_folder,
                "explicitReuse": {
                    f"{building_sid}:{level}": {"sourceSlot": source_slot, "reason": reason}
                    for (building_sid, level), (source_slot, reason) in spec.explicit_icon_reuse.items()
                },
                "explicitFiles": {
                    f"{building_sid}:{level}": {"folder": folder, "file": file_name, "reason": reason}
                    for (building_sid, level), (folder, file_name, reason) in spec.explicit_icon_files.items()
                },
                "unmappedHallSlots": [
                    slot
                    for slot in slots
                    if slot not in spec.hall_slot_to_olden
                    and slot not in {source_slot for source_slot, _reason in spec.explicit_icon_reuse.values()}
                ],
                "map": expected_hall_icon_map(spec, town_config),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def copy_icon_json_overrides(icon_def_path: Path, icons_dir: Path) -> None:
    sidecar = icon_def_path.with_suffix(".json")
    if not sidecar.is_file():
        return
    data = load_jsonc(sidecar)
    basepath = str(data.get("basepath") or "").replace("\\", "/").strip("/")
    if not basepath:
        return
    if basepath.startswith("town-screen/"):
        source_root = THIRD_ROOT / "sprites" / basepath
    else:
        source_root = icon_def_path.parent / basepath
    for entry in data.get("images") or []:
        frame = int(entry["frame"])
        file_stem = str(entry["file"])
        source = find_case_insensitive_file(source_root / (file_stem + ".png"))
        shutil.copy2(source, icons_dir / f"00_{frame:02d}.png")


def load_town_config(spec: FactionSpec) -> dict[str, Any]:
    data = load_jsonc(spec.town_config)
    return data[f"core:{spec.sid.removeprefix('homm3_')}"]["town"]


def build_faction(spec: FactionSpec) -> None:
    town_config = load_town_config(spec)
    build_mockup(spec)
    build_layers(spec)
    build_icons(spec, town_config)
    print(f"{spec.display}: generated town scene assets under {TOWN_SCENE_ROOT / spec.sid}")


CASTLE_HALL_TO_OLDEN = {
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
    "shipyard": ("Build_Artifact_Market", 1),
    "special1": ("Build_Bank", 1),
    "special2": ("Build_Mother_Nature", 1),
    "special3": ("Build_Mycelium_Roots", 1),
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

RAMPART_HALL_TO_OLDEN = {
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
    "special1": ("Build_Bank", 1),
    "special2": ("Build_Artifact_Market", 1),
    "special3": ("Build_Mother_Nature", 1),
    "horde1Upgr": ("Build_Resource_Depot_level_2", 1),
    "horde1Upgr2": ("Build_Resource_Depot_level_2", 2),
    "horde2Upgr": ("Build_Mycelium_Roots", 1),
    "horde2Upgr2": ("Build_Mycelium_Roots", 2),
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


SPECS = {
    "castle": FactionSpec(
        sid="homm3_castle",
        display="Castle",
        background_name="Castle-in-background.png",
        third_dir="castle",
        town_config=THIRD_ROOT / "config" / "town-screen" / "castle" / "factions.json",
        icon_def="HALLCSTL.def",
        icon_folder="hallcstl.dir",
        icon_source_map="hallcstl_source_map.json",
        # Castle base placements mirror VCMI core config/factions/castle.json.
        # The local third-upgrades config contains only override deltas, so do not
        # treat it as the complete coordinate source for HoMM3 base structures.
        base_layers=(
            LayerSpec("tbcsext2", "extraAnimation", "TBCSEXT2.def", 46, 119),
            LayerSpec("tbcshall", "villageHall", "TBCSHALL.def", 0, 218, 1),
            LayerSpec("tbcshal2", "townHall", "TBCSHAL2.def", 0, 176, 1, 2),
            LayerSpec("tbcshal3", "cityHall", "TBCSHAL3.def", 0, 164, 1, 3),
            LayerSpec("tbcshal4", "capitol", "TBCSHAL4.def", 0, 154, 1, 4),
            LayerSpec("tbcscstl", "fort", "TBCSCSTL.def", 595, 66, -5),
            LayerSpec("tbcscas2", "citadel", "TBCSCAS2.def", 478, 66, -2, 2),
            LayerSpec("tbcscas3", "castle", "TBCSCAS3.def", 478, 37, -2, 3),
            LayerSpec("tbcstvrn", "tavern", "TBCSTVRN.def", 0, 230, 2),
            LayerSpec("tbcmark", "marketplace", "TBCSMARK.def", 413, 264),
            LayerSpec("tbcssilo", "resourceSilo", "TBCSSILO.def", 488, 228, 1),
            LayerSpec("tbcsmage", "mageGuild1", "TBCSMAGE.def", 707, 166, 1),
            LayerSpec("tbcsmag2", "mageGuild2", "TBCSMAG2.def", 706, 135, 1, 2),
            LayerSpec("tbcsmag3", "mageGuild3", "TBCSMAG3.def", 704, 107, 1, 3),
            LayerSpec("tbcsmag4", "mageGuild4", "TBCSMAG4.def", 704, 76, 1, 4),
            LayerSpec("tbcsblak", "blacksmith", "TBCSBLAK.def", 213, 251),
            LayerSpec("tbcsspec", "special1", "TBCSSPEC.def", 533, 71, -4),
            LayerSpec("tbcsext0", "special2", "TBCSEXT0.def", 384, 193, -2),
            LayerSpec("tbcsext1", "special3", "TBCSEXT1.def", 0, 198, 2),
            LayerSpec("tbcshrd2", "horde1Upgr", "TBCSHRD2.def", 76, 35, -2),
            LayerSpec("tbcsholy", "grail", "TBCSHOLY.def", 456, 109, -6),
            LayerSpec("tbcsdock", "shipyard", "TBCSDOCK.def", 478, 134, -1),
            LayerSpec("tbcsdw_0", "dwellingLvl1", "TBCSDW_0.def", 304, 92, -1),
            LayerSpec("tbcsdw_1", "dwellingLvl2", "TBCSDW_1.def", 360, 130),
            LayerSpec("tbcsdw_2", "dwellingLvl3", "TBCSDW_2.def", 76, 57, -2),
            LayerSpec("tbcsdw_3", "dwellingLvl4", "TBCSDW_3.def", 176, 101),
            LayerSpec("tbcsdw_4", "dwellingLvl5", "TBCSDW_4.def", 563, 211, 1),
            LayerSpec("tbcsdw_5", "dwellingLvl6", "TBCSDW_5.def", 174, 190, -1),
            LayerSpec("tbcsdw_6", "dwellingLvl7", "TBCSDW_6.def", 303, 0, -2),
            LayerSpec("tbcsdw_0_2", "dwellingUpLvl1", "TBCSUP_0.def", 304, 65, -2, 2),
            LayerSpec("tbcsdw_1_2", "dwellingUpLvl2", "TBCSUP_1.def", 360, 115, 0, 2),
            LayerSpec("tbcsdw_2_2", "dwellingUpLvl3", "TBCSUP_2.def", 76, 35, -2, 2),
            LayerSpec("tbcsdw_3_2", "dwellingUpLvl4", "TBCSUP_3.def", 176, 85, 0, 2),
            LayerSpec("tbcsdw_4_2", "dwellingUpLvl5", "TBCSUP_4.def", 563, 173, 1, 2),
            LayerSpec("tbcsdw_5_2", "dwellingUpLvl6", "TBCSUP_5.def", 160, 190, -1, 2),
            LayerSpec("tbcsdw_6_2", "dwellingUpLvl7", "TBCSUP_6.def", 303, 0, -2, 2),
        ),
        third_layers=(
            LayerSpec("tbcstext5", "extraCapitol", "TBCTEXT5.def", 580, 0, -5, third=True),
            LayerSpec("tbcshrd3", "horde2", "TBCSHRD3.def", 76, 1, -1, third=True),
            LayerSpec("tbcsdw_0_3", "dwellingUp2Lvl1", "TBCSUP2_0.def", 304, 51, 0, 3, True),
            LayerSpec("tbcsdw_1_3", "dwellingUp2Lvl2", "TBCSUP2_1.def", 360, 102, 0, 3, True),
            LayerSpec("tbcsdw_2_3", "dwellingUp2Lvl3", "TBCSUP2_2.def", 76, 1, 0, 3, True),
            LayerSpec("tbcsdw_3_3", "dwellingUp2Lvl4", "TBCSUP2_3.def", 176, 72, 0, 3, True),
            LayerSpec("tbcsdw_4_3", "dwellingUp2Lvl5", "TBCSUP2_4.def", 563, 149, 1, 3, True),
            LayerSpec("tbcsdw_5_3", "dwellingUp2Lvl6", "TBCSUP2_5.def", 160, 184, -1, 3, True),
            LayerSpec("tbcsdw_6_3", "dwellingUp2Lvl7", "TBCSUP2_6.def", 303, 0, -1, 3, True),
        ),
        building_layer_ids={
            "Build_Main": "tbcshall",
            "Build_Wall": "tbcscstl",
            "Build_Tavern": "tbcstvrn",
            "Build_Treasury": "tbcsblak",
            "Build_Market": "tbcmark",
            "Build_Resource_Depot": "tbcssilo",
            "Build_Magic_Guild": "tbcsmage",
            "Build_Bank": "tbcsspec",
            "Build_Artifact_Market": "tbcsdock",
            "Build_Mother_Nature": "tbcsext0",
            "Build_Mycelium_Roots": "tbcsext1",
            "Build_Resource_Depot_level_2": "tbcshrd2",
            "Build_Tier_1": "tbcsdw_0",
            "Build_Tier_2": "tbcsdw_1",
            "Build_Tier_3": "tbcsdw_2",
            "Build_Tier_4": "tbcsdw_3",
            "Build_Tier_5": "tbcsdw_4",
            "Build_Tier_6": "tbcsdw_5",
            "Build_Tier_7": "tbcsdw_6",
        },
        building_levels={
            "Build_Main": {1: "tbcshall", 2: "tbcshal2", 3: "tbcshal3", 4: "tbcshal4"},
            "Build_Wall": {1: "tbcscstl", 2: "tbcscas2", 3: "tbcscas3"},
            "Build_Magic_Guild": {1: "tbcsmage", 2: "tbcsmag2", 3: "tbcsmag3", 4: "tbcsmag4"},
            "Build_Tier_1": {1: "tbcsdw_0", 2: "tbcsdw_0_2", 3: "tbcsdw_0_3"},
            "Build_Tier_2": {1: "tbcsdw_1", 2: "tbcsdw_1_2", 3: "tbcsdw_1_3"},
            "Build_Tier_3": {1: "tbcsdw_2", 2: "tbcsdw_2_2", 3: "tbcsdw_2_3"},
            "Build_Tier_4": {1: "tbcsdw_3", 2: "tbcsdw_3_2", 3: "tbcsdw_3_3"},
            "Build_Tier_5": {1: "tbcsdw_4", 2: "tbcsdw_4_2", 3: "tbcsdw_4_3"},
            "Build_Tier_6": {1: "tbcsdw_5", 2: "tbcsdw_5_2", 3: "tbcsdw_5_3"},
            "Build_Tier_7": {1: "tbcsdw_6", 2: "tbcsdw_6_2", 3: "tbcsdw_6_3"},
        },
        hall_slot_to_olden=CASTLE_HALL_TO_OLDEN,
        explicit_icon_reuse={("Build_Magic_Guild", 5): ("mageGuild4", "Castle has no HoMM3 mageGuild5; reuse mageGuild4 explicitly.")},
        explicit_icon_files={},
        source_crosswalk={
            "Build_Treasury": "Castle blacksmith visual from tbcsblak; retained donor economy SID.",
            "Build_Bank": "Castle Brotherhood of the Sword visual from tbcsspec; retained donor economy/special SID.",
            "Build_Artifact_Market": "Castle shipyard visual from tbcsdock; retained donor artifact-market SID.",
            "Build_Mother_Nature": "Castle lighthouse/stables-adjacent visual from tbcsext0; retained donor special-building SID.",
            "Build_Mycelium_Roots": "Castle Brotherhood support visual from tbcsext1; retained donor special-building SID.",
            "Build_Resource_Depot_level_2": "Castle griffin horde visual from tbcshrd2; retained donor resource-upgrade SID.",
        },
    ),
    "rampart": FactionSpec(
        sid="homm3_rampart",
        display="Rampart",
        background_name="Rampart-in-background.png",
        third_dir="rampart",
        town_config=THIRD_ROOT / "config" / "town-screen" / "rampart" / "factions.json",
        icon_def="ALTHALLRMT.def",
        icon_folder="althallrmt.dir",
        icon_source_map="althallrmt_source_map.json",
        base_layers=(
            LayerSpec("tbrmhall", "villageHall", "TBRMHALL.def", 190, 208),
            LayerSpec("tbrmhal2", "townHall", "TBRMHAL2.def", 190, 183, 0, 2),
            LayerSpec("tbrmhal3", "cityHall", "TBRMHAL3.def", 190, 152, 0, 3),
            LayerSpec("tbrmhal4", "capitol", "TBRMHAL4.def", 190, 152, 0, 4),
            LayerSpec("tbrmcstl", "fort", "TBRMCSTL.def", 472, 66),
            LayerSpec("tbrmcas2", "citadel", "TBRMCAS2.def", 472, 53, 0, 2),
            LayerSpec("tbrmcas3", "castle", "TBRMCAS3.def", 472, 53, 0, 3),
            LayerSpec("tbrmtvrn", "tavern", "TBRMTVRN.def", 624, 244),
            LayerSpec("tbrmmark", "marketplace", "TBRMMARK.def", 0, 281),
            LayerSpec("tbrmsilo", "resourceSilo", "TBRMSILO.def", 90, 269),
            LayerSpec("tbrmmage", "mageGuild1", "TBRMMAGE.def", 548, 175),
            LayerSpec("tbrmmag2", "mageGuild2", "TBRMMAG2.def", 548, 153, 0, 2),
            LayerSpec("tbrmmag3", "mageGuild3", "TBRMMAG3.def", 548, 128, 0, 3),
            LayerSpec("tbrmmag4", "mageGuild4", "TBRMMAG4.def", 548, 104, 0, 4),
            LayerSpec("tbrmmag5", "mageGuild5", "TBRMMAG5.def", 548, 79, 0, 5),
            LayerSpec("tbrmblak", "blacksmith", "TBRMBLAK.def", 311, 232),
            LayerSpec("tbrmspec", "special1", "TBRMSPEC.def", 39, 198),
            LayerSpec("tbrmext0", "special2", "TBRMEXT0.def", 39, 198),
            LayerSpec("tbrmext1", "special3", "TBRMEXT1.def", 708, 243),
            LayerSpec("tbrmext2", "extraAnimation", "TBRMEXT2.def", 267, 115),
            LayerSpec("tbrmext3", "extraAnimation2", "TBRMEXT3.def", 160, 69),
            LayerSpec("tbrmext4", "extraAnimation3", "TBRMEXT4.def", 500, 241),
            LayerSpec("tbrmholy", "grail", "TBRMHOLY.def", 381, 205, -2),
            LayerSpec("tbrmhrd1", "horde1", "TBRMHRD1.def", 0, 143, -1),
            LayerSpec("tbrmhrd2", "horde2", "TBRMHRD2.def", 47, 142, -2),
            LayerSpec("tbrmdw_0", "dwellingLvl1", "TBRMDW_0.def", 0, 216, 2),
            LayerSpec("tbrmdw_1", "dwellingLvl2", "TBRMDW_1.def", 0, 143, -1),
            LayerSpec("tbrmdw_2", "dwellingLvl3", "TBRMDW_2.def", 665, 101, -1),
            LayerSpec("tbrmdw_3", "dwellingLvl4", "TBRMDW_3.def", 287, 68, -1),
            LayerSpec("tbrmdw_4", "dwellingLvl5", "TBRMDW_4.def", 63, 146, -1),
            LayerSpec("tbrmdw_5", "dwellingLvl6", "TBRMDW_5.def", 362, 90, -2),
            LayerSpec("tbrmdw_6", "dwellingLvl7", "TBRMDW_6.def", 502, 26, -5),
            LayerSpec("tbrmdw_0_2", "dwellingUpLvl1", "TBRMUP_0.def", 0, 216, 2, 2),
            LayerSpec("tbrmdw_1_2", "dwellingUpLvl2", "TBRMUP_1.def", 0, 143, -1, 2),
            LayerSpec("tbrmdw_2_2", "dwellingUpLvl3", "TBRMUP_2.def", 665, 101, -1, 2),
            LayerSpec("tbrmdw_3_2", "dwellingUpLvl4", "TBRMUP_3.def", 287, 23, -1, 2),
            LayerSpec("tbrmdw_4_2", "dwellingUpLvl5", "TBRMUP_4.def", 63, 146, -1, 2),
            LayerSpec("tbrmdw_5_2", "dwellingUpLvl6", "TBRMUP_5.def", 362, 90, -2, 2),
            LayerSpec("tbrmdw_6_2", "dwellingUpLvl7", "TBRMUP_6.def", 502, 5, -5, 2),
        ),
        third_layers=(
            LayerSpec("tbrmext5", "extraCapitol", "TBRMEXT5.def", 436, 55, -1, third=True),
            LayerSpec("tbrmhrd1u", "horde1Upgr2", "TBRMHRD1U.def", 0, 143, -2, 2, True),
            LayerSpec("tbrmhrd2u", "horde2Upgr2", "TBRMHRD2U.def", 47, 142, -2, 2, True),
            LayerSpec("tbrmdw_0_3", "dwellingUp2Lvl1", "TBRMUP2_0.def", 0, 216, 2, 3, True),
            LayerSpec("tbrmdw_1_3", "dwellingUp2Lvl2", "TBRMUP2_1.def", 0, 143, 0, 3, True),
            LayerSpec("tbrmdw_2_3", "dwellingUp2Lvl3", "TBRMUP2_2.def", 665, 101, -1, 3, True),
            LayerSpec("tbrmdw_3_3", "dwellingUp2Lvl4", "TBRMUP2_3.def", 287, 23, -1, 3, True),
            LayerSpec("tbrmdw_4_3", "dwellingUp2Lvl5", "TBRMUP2_4.def", 63, 146, -1, 3, True),
            LayerSpec("tbrmdw_5_3", "dwellingUp2Lvl6", "TBRMUP2_5.def", 362, 90, -2, 3, True),
            LayerSpec("tbrmdw_6_3", "dwellingUp2Lvl7", "TBRMUP2_6.def", 502, 5, -5, 3, True),
        ),
        building_layer_ids={
            "Build_Main": "tbrmhall",
            "Build_Wall": "tbrmcstl",
            "Build_Tavern": "tbrmtvrn",
            "Build_Treasury": "tbrmblak",
            "Build_Market": "tbrmmark",
            "Build_Resource_Depot": "tbrmsilo",
            "Build_Magic_Guild": "tbrmmage",
            "Build_Bank": "tbrmspec",
            "Build_Artifact_Market": "tbrmext0",
            "Build_Mother_Nature": "tbrmext1",
            "Build_Mycelium_Roots": "tbrmhrd2",
            "Build_Resource_Depot_level_2": "tbrmhrd1",
            "Build_Tier_1": "tbrmdw_0",
            "Build_Tier_2": "tbrmdw_1",
            "Build_Tier_3": "tbrmdw_2",
            "Build_Tier_4": "tbrmdw_3",
            "Build_Tier_5": "tbrmdw_4",
            "Build_Tier_6": "tbrmdw_5",
            "Build_Tier_7": "tbrmdw_6",
        },
        building_levels={
            "Build_Main": {1: "tbrmhall", 2: "tbrmhal2", 3: "tbrmhal3", 4: "tbrmhal4"},
            "Build_Wall": {1: "tbrmcstl", 2: "tbrmcas2", 3: "tbrmcas3"},
            "Build_Magic_Guild": {1: "tbrmmage", 2: "tbrmmag2", 3: "tbrmmag3", 4: "tbrmmag4", 5: "tbrmmag5"},
            "Build_Resource_Depot_level_2": {1: "tbrmhrd1", 2: "tbrmhrd1u"},
            "Build_Mycelium_Roots": {1: "tbrmhrd2", 2: "tbrmhrd2u"},
            "Build_Tier_1": {1: "tbrmdw_0", 2: "tbrmdw_0_2", 3: "tbrmdw_0_3"},
            "Build_Tier_2": {1: "tbrmdw_1", 2: "tbrmdw_1_2", 3: "tbrmdw_1_3"},
            "Build_Tier_3": {1: "tbrmdw_2", 2: "tbrmdw_2_2", 3: "tbrmdw_2_3"},
            "Build_Tier_4": {1: "tbrmdw_3", 2: "tbrmdw_3_2", 3: "tbrmdw_3_3"},
            "Build_Tier_5": {1: "tbrmdw_4", 2: "tbrmdw_4_2", 3: "tbrmdw_4_3"},
            "Build_Tier_6": {1: "tbrmdw_5", 2: "tbrmdw_5_2", 3: "tbrmdw_5_3"},
            "Build_Tier_7": {1: "tbrmdw_6", 2: "tbrmdw_6_2", 3: "tbrmdw_6_3"},
        },
        hall_slot_to_olden=RAMPART_HALL_TO_OLDEN,
        explicit_icon_reuse={},
        explicit_icon_files={},
        source_crosswalk={
            "Build_Treasury": "Rampart blacksmith visual from tbrmblak; retained donor economy SID.",
            "Build_Bank": "Rampart special1 visual from tbrmspec; retained donor economy/special SID.",
            "Build_Artifact_Market": "Rampart special2 visual from tbrmext0; retained donor artifact-market SID.",
            "Build_Mother_Nature": "Rampart special3 visual from tbrmext1; retained donor special-building SID.",
            "Build_Mycelium_Roots": "Rampart dendroid horde visual from tbrmhrd2/tbrmhrd2u; retained donor special-building SID.",
            "Build_Resource_Depot_level_2": "Rampart dwarf horde visual from tbrmhrd1/tbrmhrd1u; retained donor resource-upgrade SID.",
        },
    ),
}


def check_sources(spec: FactionSpec) -> None:
    for path in (H3SPRITE_LOD, DEF_EXTRACT, LOD_EXTRACT, spec.town_config, TOWN_SCENE_ROOT / spec.sid / spec.background_name):
        if not path.exists():
            raise FileNotFoundError(path)
    third_dir = THIRD_ROOT / "sprites" / "town-screen" / spec.third_dir
    for layer in spec.third_layers:
        path = third_dir / layer.source
        if not path.is_file():
            raise FileNotFoundError(path)
    icon_def = third_dir / spec.icon_def
    if not icon_def.is_file():
        raise FileNotFoundError(icon_def)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--faction", choices=["castle", "rampart", "all"], default="all")
    parser.add_argument("--check-sources", action="store_true")
    args = parser.parse_args()

    selected = [SPECS[name] for name in ("castle", "rampart") if args.faction in ("all", name)]
    for spec in selected:
        check_sources(spec)
    if args.check_sources:
        print("Castle/Rampart town scene sources are present.")
        return 0
    for spec in selected:
        build_faction(spec)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
