#!/usr/bin/env python3
"""Extract HoMM3 adventure-map hero DEFs into runtime sprite folders."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod"
OUT_ROOT = PLUGIN / "homm3_hero_map_sprites"
EXTRACTED_DEF = PLUGIN / "tools" / "generated_homm3_hero_map_defs"
LOD = ROOT / "HoMM 3 Complete" / "Data" / "H3sprite.lod"
LOD_EXTRACT = ROOT / "tools" / "lod_extract_entry_py3.py"
DEF_EXTRACT = ROOT / "tools" / "defextract_py3.py"
HOTA_NEW_GRAPHICS = ROOT / "vcmi" / "Mods" / "hota" / "mods" / "newGraphics" / "Content" / "sprites" / "hota"
HOTA_COVE = ROOT / "vcmi" / "Mods" / "hota" / "mods" / "cove" / "Content" / "sprites" / "hota" / "cove" / "heroClasses"
EXPECTED_IDLE_FRAMES = 1
EXPECTED_WALK_FRAMES = 8


@dataclass(frozen=True)
class HeroClassSpec:
    key: str
    lod_def: str
    hota_rel: str | None = None
    cove_rel: str | None = None


SPECS: tuple[HeroClassSpec, ...] = (
    HeroClassSpec("homm3_castle_might", "AH00_.def", "castle/heroClasses/knight/AH00b_.def"),
    HeroClassSpec("homm3_castle_magic", "AH01_.def", "castle/heroClasses/cleric/AH01b_.def"),
    HeroClassSpec("homm3_rampart_might", "AH02_.def", "rampart/heroClasses/ranger/AH02b_.def"),
    HeroClassSpec("homm3_rampart_magic", "AH03_.def", "rampart/heroClasses/druid/AH03b_.def"),
    HeroClassSpec("homm3_tower_might", "AH04_.def", "tower/heroClasses/alchemist/AH04b_.def"),
    HeroClassSpec("homm3_tower_magic", "AH05_.def", "tower/heroClasses/wizard/AH05b_.def"),
    HeroClassSpec("homm3_inferno_might", "AH06_.def", "inferno/heroClasses/demoniac/AH06b_.def"),
    HeroClassSpec("homm3_inferno_magic", "AH07_.def", "inferno/heroClasses/heretic/AH07b_.def"),
    HeroClassSpec("homm3_necropolis_might", "AH08_.def", "necropolis/heroClasses/deathknight/AH08b_.def"),
    HeroClassSpec("homm3_necropolis_magic", "AH09_.def", "necropolis/heroClasses/necromancer/AH09b_.def"),
    # VCMI's HotA Dungeon hero-class folders are gendered in a misleading way.
    # Follow genderedHeroGraphics.json default templates: Overlord keeps AH10,
    # Warlock uses the enhanced AH11b.
    HeroClassSpec("homm3_dungeon_might", "AH10_.def", None),
    HeroClassSpec("homm3_dungeon_magic", "AH11_.def", "dungeon/heroClasses/overlord/AH11b_.def"),
    # VCMI genderedHeroGraphics.json default templates use male/default map art:
    # Barbarian -> AH13_, Battle Mage -> HotA battlemage/AH13b_.
    HeroClassSpec("homm3_stronghold_might", "AH13_.def", None),
    HeroClassSpec("homm3_stronghold_magic", "AH12_.def", "stronghold/heroClasses/battlemage/AH13b_.def"),
    HeroClassSpec("homm3_fortress_might", "AH14_.def", None),
    HeroClassSpec("homm3_fortress_magic", "AH15_.def", None),
    HeroClassSpec("homm3_conflux_might", "AH16_.DEF", "conflux/heroClasses/planeswalker/ah16b_.def"),
    HeroClassSpec("homm3_conflux_magic", "AH17_.DEF", "conflux/heroClasses/elementalist/AH17b_.def"),
    HeroClassSpec("homm3_cove_might", "AH18_.def", None, "captain/adventureMap/AH18b_.def"),
    HeroClassSpec("homm3_cove_magic", "AH19_.def", None, "navigator/adventureMap/AH19b_.def"),
)


def run(args: list[str]) -> None:
    subprocess.run(args, check=True)


def expected_frame_names() -> set[str]:
    names = {f"{group:02d}_00.png" for group in range(0, 5)}
    for group in range(5, 10):
        for frame in range(EXPECTED_WALK_FRAMES):
            names.add(f"{group:02d}_{frame:02d}.png")
    return names


def source_def(spec: HeroClassSpec) -> Path:
    EXTRACTED_DEF.mkdir(parents=True, exist_ok=True)
    if spec.cove_rel:
        path = HOTA_COVE / spec.cove_rel
        if path.exists():
            return path
        raise FileNotFoundError(path)
    if spec.hota_rel:
        path = HOTA_NEW_GRAPHICS / spec.hota_rel
        if path.exists():
            return path
        raise FileNotFoundError(path)
    if not LOD.exists():
        raise FileNotFoundError(LOD)
    out = EXTRACTED_DEF / spec.lod_def
    run([sys.executable, str(LOD_EXTRACT), str(LOD), spec.lod_def, str(out)])
    return out


def extract_spec(spec: HeroClassSpec) -> None:
    src = source_def(spec)
    copied_def = EXTRACTED_DEF / src.name
    if src.resolve() != copied_def.resolve():
        shutil.copy2(src, copied_def)

    dest = OUT_ROOT / spec.key
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True, exist_ok=True)
    run([sys.executable, str(DEF_EXTRACT), str(copied_def), str(dest)])

    jsons = sorted(dest.glob("*.json"))
    if not jsons:
        raise RuntimeError(f"{spec.key}: defextract produced no json")
    summary = json.loads(jsons[0].read_text(encoding="utf-8"))
    groups = {int(seq["group"]): len(seq.get("frames", [])) for seq in summary.get("sequences", [])}
    missing = [g for g in range(0, 5) if groups.get(g, 0) != EXPECTED_IDLE_FRAMES]
    missing += [g for g in range(5, 10) if groups.get(g, 0) != EXPECTED_WALK_FRAMES]
    if missing:
        raise RuntimeError(f"{spec.key}: incomplete idle/walk groups {missing} from {copied_def}")
    expected_pngs = sorted(expected_frame_names())
    actual_pngs = sorted(path.name for path in dest.rglob("*.png"))
    if actual_pngs != expected_pngs:
        raise RuntimeError(
            f"{spec.key}: unexpected PNG frame set missing={sorted(set(expected_pngs) - set(actual_pngs))} "
            f"extra={sorted(set(actual_pngs) - set(expected_pngs))} actual_count={len(actual_pngs)} expected_count={len(expected_pngs)}"
        )
    print(f"{spec.key}: {copied_def.name} groups 0..9 ok")


def main() -> int:
    if not LOD_EXTRACT.exists() or not DEF_EXTRACT.exists():
        raise FileNotFoundError("Missing lod/def extraction helper")
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    expected = {spec.key for spec in SPECS}
    for child in OUT_ROOT.iterdir():
        if child.is_dir() and child.name not in expected:
            shutil.rmtree(child)
    for spec in SPECS:
        extract_spec(spec)
    generated = {child.name for child in OUT_ROOT.iterdir() if child.is_dir()}
    if generated != expected:
        raise RuntimeError(f"Unexpected generated folder set: missing={sorted(expected - generated)} extra={sorted(generated - expected)}")
    print(f"Extracted {len(SPECS)} hero map sprite class folder(s) under {OUT_ROOT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
