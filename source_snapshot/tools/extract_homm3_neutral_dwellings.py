#!/usr/bin/env python3
"""Extract HoMM3/HotA neutral dwelling AVG* frames and write billboard registry."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN_ROOT = ROOT / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod"
DEFEXTRACT = ROOT / "tools" / "defextract_py3.py"
LODEXTRACT = ROOT / "tools" / "lod_extract_entry_py3.py"
H3SPRITE_CANDIDATES = (
    Path(r"C:/Games/Heroes of Might and Magic III/HoMM 3 Complete/Data/H3sprite.lod"),
    ROOT / "vcmi" / "Data" / "H3sprite.lod",
)
HOTA_NEUTRAL_ZIP = ROOT / "vcmi" / "Mods" / "hota" / "mods" / "neutralCreatures" / "content.zip"
OUT_DIR = PLUGIN_ROOT / "homm3_runtime_assets" / "map_object_refs" / "homm3_neutral_dwellings"
REGISTRY_PATH = PLUGIN_ROOT / "homm3_neutral_dwellings.json"

sys.path.insert(0, str(ROOT / "tools" / "release_port"))
from homm3_neutral_catalog import catalog_dwellings, load_homm3_neutral_catalog  # noqa: E402


def find_h3sprite() -> Path:
    for path in H3SPRITE_CANDIDATES:
        if path.is_file():
            return path
    raise FileNotFoundError("H3sprite.lod not found")


def extract_lod_def(lod: Path, entry: str, dest: Path) -> Path:
    tmp = ROOT / "tools" / "build_temp_homm3" / "neutral_dwellings" / entry
    tmp.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([sys.executable, str(LODEXTRACT), str(lod), entry, str(tmp)], check=True, cwd=ROOT)
    sys.path.insert(0, str(ROOT / "tools"))
    from defextract_py3 import extract_def

    if not extract_def(str(tmp), str(dest)):
        raise RuntimeError(f"Failed to extract {entry}")
    stem = Path(entry).stem
    candidates = sorted(dest.glob(f"{stem}.dir")) + sorted(dest.glob(f"{stem.upper()}.dir")) + sorted(dest.glob(f"{stem.lower()}.dir"))
    if not candidates:
        # defextract may normalize case
        candidates = [p for p in dest.iterdir() if p.is_dir() and p.name.lower().startswith(stem.lower())]
    if not candidates:
        raise RuntimeError(f"No extracted dir for {entry} under {dest}")
    return candidates[0]


def extract_zip_def(zip_path: Path, member: str, dest: Path) -> Path:
    tmp = ROOT / "tools" / "build_temp_homm3" / "neutral_dwellings_zip" / Path(member).name
    tmp.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        tmp.write_bytes(zf.read(member))
    sys.path.insert(0, str(ROOT / "tools"))
    from defextract_py3 import extract_def

    if not extract_def(str(tmp), str(dest)):
        raise RuntimeError(f"Failed to extract zip member {member}")
    stem = Path(member).stem
    candidates = [p for p in dest.iterdir() if p.is_dir() and p.name.lower().startswith(stem.lower())]
    if not candidates:
        raise RuntimeError(f"No extracted dir for zip member {member}")
    return candidates[0]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    catalog = load_homm3_neutral_catalog()
    lod = find_h3sprite()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    registry: dict[str, str] = {}
    for dwelling in catalog_dwellings(catalog):
        barracks_sid = str(dwelling["barracksSid"])
        def_name = str(dwelling["defName"])
        creature_key = barracks_sid.removeprefix("barracks_homm3_neutral_")
        landon_sid = f"homm3_landon_barracks_neutral_{creature_key}"

        if args.dry_run:
            print(f"would extract {def_name} -> {barracks_sid} / {landon_sid}")
            continue

        if def_name.lower() in {"avgsaty0.def", "avglprch.def", "avgfngrm.def"} and HOTA_NEUTRAL_ZIP.is_file():
            member_map = {
                "avgsaty0.def": "sprites/hota/dwellings/AVGsaty0.def",
                "avglprch.def": "sprites/hota/dwellings/AVGlprch.def",
                "avgfngrm.def": "sprites/hota/dwellings/avgfngrm.def",
            }
            extracted_dir = extract_zip_def(HOTA_NEUTRAL_ZIP, member_map[def_name.lower()], OUT_DIR)
        else:
            extracted_dir = extract_lod_def(lod, def_name, OUT_DIR)

        frame = extracted_dir / "00_00.png"
        if not frame.is_file():
            pngs = sorted(extracted_dir.glob("*.png"))
            if not pngs:
                raise RuntimeError(f"No PNG frames in {extracted_dir}")
            frame = pngs[0]
            target = extracted_dir / "00_00.png"
            if frame != target:
                shutil.copy2(frame, target)
                frame = target

        rel = f"homm3_runtime_assets/map_object_refs/homm3_neutral_dwellings/{extracted_dir.name}/00_00.png"
        registry[barracks_sid] = rel
        registry[landon_sid] = rel
        print(f"extracted {def_name} -> {rel}")

    if not args.dry_run:
        sys.path.insert(0, str(ROOT / "tools"))
        from strip_crop_map_building_billboards import process_paths

        pngs = sorted(OUT_DIR.rglob("*.png"))
        report = process_paths(pngs, dry_run=False)
        print(
            "neutral dwelling strip+crop: "
            f"groups={report['groupCount']} changedFrames={report['changedFrames']} "
            f"shadowPixelsRemovedTotal={report['shadowPixelsRemovedTotal']}"
        )
        rows = [{"sid": sid, "relativePath": path} for sid, path in sorted(registry.items())]
        REGISTRY_PATH.write_text(json.dumps({"dwellings": rows}, indent=2) + "\n", encoding="utf-8")
        print(f"Wrote {REGISTRY_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
