#!/usr/bin/env python3
"""Extract classic HoMM3/VCMI adventure-map boat DEFs into runtime sprite folders."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod"
OUT_ROOT = PLUGIN / "homm3_boat_map_sprites"
EXTRACTED_DEF = PLUGIN / "tools" / "generated_homm3_boat_map_defs"
LOD = ROOT / "HoMM 3 Complete" / "Data" / "H3sprite.lod"
LOD_EXTRACT = ROOT / "tools" / "lod_extract_entry_py3.py"
DEF_EXTRACT = ROOT / "tools" / "defextract_py3.py"
VCMI_COVE_BOATS = ROOT / "vcmi" / "Mods" / "hota" / "mods" / "cove" / "Content" / "sprites" / "hota" / "cove" / "mapObjects" / "boats"
EXPECTED_IDLE_FRAMES = 1
EXPECTED_WALK_FRAMES = 8


@dataclass(frozen=True)
class BoatSpec:
    key: str
    def_name: str
    source: str


SPECS: tuple[BoatSpec, ...] = (
    BoatSpec("homm3_boat_1", "AB01_.def", "lod"),
    BoatSpec("homm3_boat_2", "AB02_.def", "lod"),
    BoatSpec("homm3_boat_3", "AB03_.def", "lod"),
    BoatSpec("homm3_boat_cove", "AB04_.DEF", "vcmi_cove"),
)


def run(args: list[str]) -> None:
    subprocess.run(args, check=True)


def expected_frame_names() -> set[str]:
    names = {f"{group:02d}_00.png" for group in range(0, 5)}
    for group in range(5, 10):
        for frame in range(EXPECTED_WALK_FRAMES):
            names.add(f"{group:02d}_{frame:02d}.png")
    return names


def source_def(spec: BoatSpec) -> Path:
    EXTRACTED_DEF.mkdir(parents=True, exist_ok=True)
    if spec.source == "lod":
        if not LOD.exists():
            raise FileNotFoundError(LOD)
        out = EXTRACTED_DEF / spec.def_name
        run([sys.executable, str(LOD_EXTRACT), str(LOD), spec.def_name, str(out)])
        return out
    if spec.source == "vcmi_cove":
        path = VCMI_COVE_BOATS / spec.def_name
        if not path.exists():
            raise FileNotFoundError(path)
        return path
    raise ValueError(f"{spec.key}: unsupported source {spec.source!r}")


def extract_spec(spec: BoatSpec) -> None:
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
    print(f"Extracted {len(SPECS)} boat map sprite folder(s) under {OUT_ROOT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
