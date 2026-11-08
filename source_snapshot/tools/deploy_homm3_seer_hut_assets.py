#!/usr/bin/env python3
"""Deploy classic HoMM3 Seer's Hut adventure billboard into OfflineUnlockMod refs.

Source: vcmi/Data/H3sprite.lod entry AVXseer0.def
Pipeline: LOD extract → defextract → DEF soft-shadow strip/crop → map_object_refs/homm3_seer_hut/
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN_ROOT = ROOT / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod"
DEFEXTRACT = ROOT / "tools" / "defextract_py3.py"
LODEXTRACT = ROOT / "tools" / "lod_extract_entry_py3.py"
H3SPRITE_LOD = ROOT / "vcmi" / "Data" / "H3sprite.lod"
DEF_ENTRY = "AVXseer0.def"
DEST = PLUGIN_ROOT / "homm3_runtime_assets" / "map_object_refs" / "homm3_seer_hut"
TMP = ROOT / "tools" / "build_temp_homm3" / "seer_hut"


def main() -> int:
    if not H3SPRITE_LOD.is_file():
        raise FileNotFoundError(H3SPRITE_LOD)
    TMP.mkdir(parents=True, exist_ok=True)
    def_path = TMP / DEF_ENTRY
    subprocess.run(
        [sys.executable, str(LODEXTRACT), str(H3SPRITE_LOD), DEF_ENTRY, str(def_path)],
        check=True,
        cwd=ROOT,
    )
    if DEST.exists():
        shutil.rmtree(DEST)
    DEST.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [sys.executable, str(DEFEXTRACT), str(def_path), str(DEST)],
        check=True,
        cwd=ROOT,
    )
    sys.path.insert(0, str(ROOT / "tools"))
    from strip_crop_map_building_billboards import process_frame_group

    frame_dirs = sorted(DEST.rglob("*.dir"))
    if not frame_dirs:
        raise FileNotFoundError(f"no *.dir frames under {DEST}")
    strip_rows = []
    for frame_dir in frame_dirs:
        pngs = sorted(frame_dir.glob("*.png"))
        if not pngs:
            raise FileNotFoundError(f"no PNGs in {frame_dir}")
        strip_rows.append(process_frame_group(pngs, dry_run=False))
    manifest = {
        "sid": "homm3_seer_hut",
        "source": f"vcmi/Data/H3sprite.lod:{DEF_ENTRY}",
        "dest": str(DEST.relative_to(ROOT)).replace("\\", "/"),
        "strip": strip_rows,
    }
    (DEST / "deploy_manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
