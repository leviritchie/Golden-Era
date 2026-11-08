#!/usr/bin/env python3
"""Build the PNGs for visual-only HoMM3 object billboards (``homm3_objbb_<def>``).

The catalog is ``experiments/campaign_port_poc/raw_translation/object_billboards.py``
(``BILLBOARD_DEFS``). For each DEF this tool:

1. extracts it from ``vcmi/Data/H3sprite.lod``;
2. decodes it with ``defextract_py3.py`` and keeps the first frame of the first group (00_00);
3. strips the baked DEF shadow and crops to opaque content
   (``strip_crop_map_building_billboards.process_frame_group``);
4. writes ``OfflineUnlockMod/homm3_runtime_assets/map_object_refs/homm3_object_billboards/<sid>/00_00.png``.

It also writes ``manifest.json`` with each SID's DEF and pixel size. The runtime
(``Homm3ArtifactMapBillboard.cs``) sizes the quad from the PNG height at the seer-hut scale.
``tools/validate_homm3_object_billboard_contract.py`` checks the catalog against these files.

``--check`` rebuilds into a temp dir and fails if any committed PNG or the manifest differ.
"""
from __future__ import annotations

import argparse
import filecmp
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "experiments" / "campaign_port_poc" / "raw_translation"))

import object_billboards  # noqa: E402
from lod_extract_entry_py3 import extract_entry  # noqa: E402
from strip_crop_map_building_billboards import process_frame_group  # noqa: E402

from PIL import Image  # noqa: E402

PLUGIN_ROOT = ROOT / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod"
DEST = PLUGIN_ROOT / "homm3_runtime_assets" / "map_object_refs" / "homm3_object_billboards"
DEFEXTRACT = ROOT / "tools" / "defextract_py3.py"
H3SPRITE_LOD = ROOT / "vcmi" / "Data" / "H3sprite.lod"
SCHEMA = "homm3_object_billboard_assets.v1"


def _lod_entry_name(stem: str) -> str:
    return stem + ".def"


def build(dest: Path, work: Path) -> dict:
    if not H3SPRITE_LOD.is_file():
        raise FileNotFoundError(H3SPRITE_LOD)
    rows = []
    for stem in object_billboards.all_billboard_defs():
        sid = object_billboards.sid_for_def(stem)
        def_path = work / f"{stem}.def"
        if not extract_entry(H3SPRITE_LOD, _lod_entry_name(stem), def_path):
            raise FileNotFoundError(f"{_lod_entry_name(stem)} not found in {H3SPRITE_LOD}")
        frames_root = work / stem
        frames_root.mkdir(parents=True, exist_ok=True)
        subprocess.run([sys.executable, str(DEFEXTRACT), str(def_path), str(frames_root)], check=True, cwd=ROOT,
                       stdout=subprocess.DEVNULL)
        firsts = sorted(frames_root.rglob("00_00.png"))
        if len(firsts) != 1:
            raise RuntimeError(f"{stem}: expected one 00_00.png from defextract, got {[str(p) for p in firsts]}")
        strip = process_frame_group(firsts, dry_run=False)
        out_dir = dest / sid
        out_dir.mkdir(parents=True, exist_ok=True)
        out_png = out_dir / "00_00.png"
        shutil.copyfile(firsts[0], out_png)
        with Image.open(out_png) as im:
            width, height = im.size
        rows.append({
            "sid": sid,
            "def": stem,
            "source": f"vcmi/Data/H3sprite.lod:{_lod_entry_name(stem)}#00_00",
            "png": f"{sid}/00_00.png",
            "pixelSize": [width, height],
            "shadowPixelsRemoved": strip["frames"][0]["shadowPixelsRemoved"],
            "sourceSize": strip["frames"][0]["sourceSize"],
        })
    manifest = {
        "schema": SCHEMA,
        "catalog": "experiments/campaign_port_poc/raw_translation/object_billboards.py",
        "builder": "tools/build_homm3_object_billboard_assets.py",
        "templateObjects": {str(k): v for k, v in sorted(object_billboards.BILLBOARD_TEMPLATE_IDS.items())},
        "billboards": rows,
    }
    (dest / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="rebuild to a temp dir and diff against the committed files")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="objbb_", dir=ROOT / "tools") as tmp:
        tmp_path = Path(tmp)
        if args.check:
            fresh = tmp_path / "out"
            fresh.mkdir()
            build(fresh, tmp_path / "work")
            diffs = []
            for path in sorted(fresh.rglob("*")):
                if path.is_file():
                    rel = path.relative_to(fresh)
                    committed = DEST / rel
                    if not committed.is_file() or not filecmp.cmp(path, committed, shallow=False):
                        diffs.append(str(rel))
            extra = [str(p.relative_to(DEST)) for p in DEST.rglob("*") if p.is_file() and not (fresh / p.relative_to(DEST)).is_file()] if DEST.is_dir() else []
            if diffs or extra:
                print(json.dumps({"ok": False, "differ": diffs, "extra": extra}, indent=2))
                return 1
            print(json.dumps({"ok": True, "checked": len(list(fresh.rglob("*.png")))}))
            return 0
        if DEST.exists():
            shutil.rmtree(DEST)
        DEST.mkdir(parents=True)
        manifest = build(DEST, tmp_path / "work")
    print(json.dumps({"dest": str(DEST.relative_to(ROOT)).replace("\\", "/"), "count": len(manifest["billboards"])}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
