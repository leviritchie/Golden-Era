#!/usr/bin/env python3
"""Build Tower town-screen mockup and transparent building layers.

Builders keep source placements in native HoMM3/VCMI top-left coordinates.
tools/prebake_homm3_town_scene_coordinates.py adds runtime reference rects
and the 1920x1080 black-plate mockup used by the town renderer.
"""

from __future__ import annotations

import json
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
    / "homm3_tower"
)
SOURCE_BG = TOWN_ROOT / "Tower-in-background.png"
MOCKUP = TOWN_ROOT / "mockups" / "homm3_tower_background_mock_1920x1080.png"
LAYERS_DIR = TOWN_ROOT / "layers"
ANIMS_DIR = LAYERS_DIR / "anims"
POSITIONS_JSON = LAYERS_DIR / "positions.json"
DEF_SOURCE = ROOT / "vcmi" / "Mods" / "third-upgrades" / "content" / "sprites" / "town-screen" / "tower"
H3SPRITE_LOD = ROOT / "HoMM 3 Complete" / "Data" / "H3sprite.lod"
LOD_EXTRACT = ROOT / "tools" / "lod_extract_entry_py3.py"
DEF_EXTRACT = ROOT / "tools" / "defextract_py3.py"
FRAME_RATE_MS = 100

DEF_MAP = {
    "extraCapitol": ("third", "frames/TBTWEXT5.png"),
    "horde1Upgr2": ("third", "TBTWHRD2U.def"),
    "dwellingUp2Lvl1": ("third", "TBTWUP2_0.def"),
    "dwellingUp2Lvl2": ("third", "TBTWUP2_1.def"),
    "dwellingUp2Lvl3": ("third", "TBTWUP2_2.def"),
    "dwellingUp2Lvl4": ("third", "TBTWUP2_3.def"),
    "dwellingUp2Lvl5": ("third", "TBTWUP2_4.def"),
    "dwellingUp2Lvl6": ("third", "TBTWUP2_5.def"),
    "dwellingUp2Lvl7": ("third", "TBTWUP2_6.def"),
    "main": ("lod", [("TBTWHALL.def", 1), ("TBTWHAL2.def", 2), ("TBTWHAL3.def", 3)]),
    "bank": ("lod", [("TBTWHAL4.def", 1)]),
    "wall": ("lod", [("TBTWCSTL.def", 1), ("TBTWCAS2.def", 2), ("TBTWCAS3.def", 3)]),
    "tavern": ("lod", [("TBTWTVRN.def", 1)]),
    "market": ("lod", [("TBTWMARK.def", 1)]),
    "artifactMarket": ("lod", [("TBTWSPEC.def", 1)]),
    "magicGuild": ("lod", [("TBTWMAGE.def", 1), ("TBTWMAG2.def", 2), ("TBTWMAG3.def", 3), ("TBTWMAG4.def", 4), ("TBTWMAG5.def", 5)]),
    "treasury": ("lod", [("tbtwblak.def", 1)]),
    "resourceDepot": ("lod", [("TBTWSILO.def", 1)]),
    "resourceDepotLevel2": ("lod", [("TBTWHRD2.def", 1)]),
    "trainingRange": ("lod", [("TBTWEXT0.def", 1)]),
    "intelligenceAcademy": ("lod", [("TBTWEXT1.def", 1)]),
    "goldenCalf": ("lod", [("TBTWHRD1.def", 1)]),
    "dwellingLvl1": ("lod", [("TBTWDW_0.def", 1)]),
    "dwellingUpLvl1": ("lod", [("TBTWUP_0.def", 2)]),
    "dwellingLvl2": ("lod", [("TBTWDW_1.def", 1)]),
    "dwellingUpLvl2": ("lod", [("TBTWUP_1.def", 2)]),
    "dwellingLvl3": ("lod", [("TBTWDW_2.def", 1)]),
    "dwellingUpLvl3": ("lod", [("TBTWUP_2.def", 2)]),
    "dwellingLvl4": ("lod", [("TBTWDW_3.def", 1)]),
    "dwellingUpLvl4": ("lod", [("TBTWUP_3.def", 2)]),
    "dwellingLvl5": ("lod", [("TBTWDW_4.def", 1)]),
    "dwellingUpLvl5": ("lod", [("TBTWUP_4.def", 2)]),
    "dwellingLvl6": ("lod", [("TBTWDW_5.def", 1)]),
    "dwellingUpLvl6": ("lod", [("TBTWUP_5.def", 2)]),
    "dwellingLvl7": ("lod", [("TBTWDW_6.def", 1)]),
    "dwellingUpLvl7": ("lod", [("TBTWUP_6.def", 2)]),
}

LEVEL_ALIASES = {
    "dwellingUpLvl1_2.png": "dwellingLvl1_2.png",
    "dwellingUpLvl2_2.png": "dwellingLvl2_2.png",
    "dwellingUpLvl3_2.png": "dwellingLvl3_2.png",
    "dwellingUpLvl4_2.png": "dwellingLvl4_2.png",
    "dwellingUpLvl5_2.png": "dwellingLvl5_2.png",
    "dwellingUpLvl6_2.png": "dwellingLvl6_2.png",
    "dwellingUpLvl7_2.png": "dwellingLvl7_2.png",
}

ANIM_DEF_MAP = {
    "dwellingUp2Lvl1_1": "TBTWUP2_0.def",
    "dwellingUp2Lvl3_1": "TBTWUP2_2.def",
    "dwellingUp2Lvl7_1": "TBTWUP2_6.def",
}

SOURCE_SIZE = (800, 374)

def build_mockup() -> None:
    prebake_mockup(SOURCE_BG, MOCKUP)


def extract_def(def_path: Path, temp_root: Path) -> tuple[dict, Path]:
    if not DEF_EXTRACT.is_file():
        raise RuntimeError(f"missing DEF extraction helper: {DEF_EXTRACT}")
    subprocess.run([sys.executable, str(DEF_EXTRACT), str(def_path), str(temp_root)], check=True)
    manifest_path = temp_root / (def_path.stem.lower() + ".json")
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    return data, temp_root / (def_path.stem.lower() + ".dir")


def extract_lod_def(def_name: str, temp_root: Path) -> Path:
    if not H3SPRITE_LOD.is_file():
        raise RuntimeError(f"missing HoMM3 sprite LOD: {H3SPRITE_LOD}")
    if not LOD_EXTRACT.is_file():
        raise RuntimeError(f"missing LOD extraction helper: {LOD_EXTRACT}")
    out_path = temp_root / def_name
    subprocess.run([sys.executable, str(LOD_EXTRACT), str(H3SPRITE_LOD), def_name, str(out_path)], check=True)
    if not out_path.is_file():
        raise RuntimeError(f"failed to extract {def_name} from {H3SPRITE_LOD}")
    return out_path


def extract_first_frame(def_path: Path, temp_root: Path) -> Image.Image:
    data, frames_dir = extract_def(def_path, temp_root)
    for seq in data.get("sequences") or []:
        frames = seq.get("frames") or []
        if frames:
            frame = temp_root / frames[0].replace("\\", "/")
            if frame.is_file():
                return Image.open(frame).convert("RGBA")
    fallback = sorted(frames_dir.glob("*.png"))
    if fallback:
        return Image.open(fallback[0]).convert("RGBA")
    raise RuntimeError(f"{def_path}: no extracted PNG frame")


def transparent_full_canvas(src: Image.Image) -> Image.Image:
    rgba = src.convert("RGBA")
    bg = rgba.getpixel((0, 0))[:3]
    pixels = rgba.load()
    for y in range(rgba.height):
        for x in range(rgba.width):
            r, g, b, a = pixels[x, y]
            if a == 0 or (r, g, b) == bg:
                pixels[x, y] = (r, g, b, 0)
    return rgba


def build_layers() -> None:
    with tempfile.TemporaryDirectory(prefix="homm3-tower-town-defs-") as tmp:
        temp_root = Path(tmp)
        for layer_id, spec in DEF_MAP.items():
            source_kind, source_spec = spec
            if source_kind == "third":
                source = DEF_SOURCE / source_spec
                if not source.is_file():
                    raise RuntimeError(f"missing Tower layer source: {source}")
                image = Image.open(source).convert("RGBA") if source.suffix.lower() == ".png" else extract_first_frame(source, temp_root)
                out_path = LAYERS_DIR / f"{layer_id}.png"
                image.save(out_path, optimize=True)
                level_path = LAYERS_DIR / f"{layer_id}_1.png"
                shutil.copy2(out_path, level_path)
                print(f"{layer_id}: {source_spec} -> {out_path.name}, {level_path.name}")
                continue

            for def_name, level in source_spec:
                def_path = extract_lod_def(def_name, temp_root)
                image = transparent_full_canvas(extract_first_frame(def_path, temp_root))
                out_path = LAYERS_DIR / f"{layer_id}_{level}.png"
                image.save(out_path, optimize=True)
                if level == 1:
                    image.save(LAYERS_DIR / f"{layer_id}.png", optimize=True)
                print(f"{layer_id}: {def_name} -> {out_path.name}")

    for source_name, alias_name in LEVEL_ALIASES.items():
        source = LAYERS_DIR / source_name
        if source.is_file():
            shutil.copy2(source, LAYERS_DIR / alias_name)
            print(f"alias: {source_name} -> {alias_name}")

    write_positions()


def write_positions() -> None:
    layers = []
    order = 0
    for layer_id in DEF_MAP:
        layers.append({"id": layer_id, "x": 0, "y": 0, "z": 0, "order": order})
        order += 1
    POSITIONS_JSON.write_text(
        json.dumps(
            {
                "_comment": "Runtime Tower town visual placements. Original HoMM3 DEF layers are saved as full 800x374 transparent canvases, so x/y stay 0. Third-upgrade overlays also remain in this coordinate basis.",
                "layers": layers,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    prebake_positions_file(POSITIONS_JSON)


def build_anims() -> None:
    if ANIMS_DIR.exists():
        shutil.rmtree(ANIMS_DIR)
    ANIMS_DIR.mkdir(parents=True, exist_ok=True)

    metadata = []
    with tempfile.TemporaryDirectory(prefix="homm3-tower-town-anims-") as tmp:
        temp_root = Path(tmp)
        for anim_id, def_name in ANIM_DEF_MAP.items():
            source = DEF_SOURCE / def_name
            if not source.is_file():
                raise RuntimeError(f"missing Tower animation source: {source}")

            data, frames_dir = extract_def(source, temp_root)
            sequences = data.get("sequences") or []
            frames = sequences[0].get("frames") if sequences else []
            if not frames or len(frames) <= 1:
                print(f"{anim_id}: {def_name} has no animation frames, skipping")
                continue

            dest_dir = ANIMS_DIR / anim_id
            dest_dir.mkdir(parents=True, exist_ok=True)
            frame_names = []
            for index, rel_path in enumerate(frames):
                src_name = Path(rel_path.replace("\\", "/")).name
                src = frames_dir / src_name
                if not src.is_file():
                    raise RuntimeError(f"missing extracted Tower animation frame: {src}")
                dest_name = f"frame_{index:02d}.png"
                shutil.copy2(src, dest_dir / dest_name)
                frame_names.append(dest_name)

            metadata.append({"id": anim_id, "frameRateMs": FRAME_RATE_MS, "frames": frame_names})
            print(f"{anim_id}: {def_name} -> {len(frame_names)} animation frames")

    (ANIMS_DIR / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(metadata)} Tower town animation entries to {ANIMS_DIR / 'metadata.json'}")


def main() -> int:
    build_mockup()
    build_layers()
    build_anims()
    print(f"Wrote {MOCKUP}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
