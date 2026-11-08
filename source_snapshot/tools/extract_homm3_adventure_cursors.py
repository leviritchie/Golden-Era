#!/usr/bin/env python3
"""Extract HoMM3 CRADVNTR go-ship cursor frames for campaign water hover overlay."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LOD = REPO_ROOT / "HoMM 3 Complete" / "Data" / "H3sprite.lod"
PLUGIN_DIR = (
    REPO_ROOT
    / "Heroes of Might & Magic Olden Era Playtest"
    / "OfflineUnlockMod"
)
STAGING_DEF = PLUGIN_DIR / "tools" / "generated_homm3_boat_map_defs" / "CRADVNTR.def"
FULL_EXTRACT = PLUGIN_DIR / "homm3_adventure_cursors" / "_cradvntr_full"
OUT_DIR = PLUGIN_DIR / "homm3_adventure_cursors" / "cradvntr_go_ship"
GO_SHIP_FRAMES = (12, 13, 14, 15)


def run(cmd: list[str]) -> None:
    print("+", " ".join(cmd))
    subprocess.check_call(cmd, cwd=str(REPO_ROOT))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lod", type=Path, default=DEFAULT_LOD)
    args = parser.parse_args()
    lod = args.lod.resolve()
    if not lod.is_file():
        print(f"LOD not found: {lod}", file=sys.stderr)
        return 2

    STAGING_DEF.parent.mkdir(parents=True, exist_ok=True)
    FULL_EXTRACT.mkdir(parents=True, exist_ok=True)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    run(
        [
            sys.executable,
            str(REPO_ROOT / "tools" / "lod_extract_entry_py3.py"),
            str(lod),
            "CRADVNTR.def",
            str(STAGING_DEF),
        ]
    )
    run(
        [
            sys.executable,
            str(REPO_ROOT / "tools" / "defextract_py3.py"),
            str(STAGING_DEF),
            str(FULL_EXTRACT),
        ]
    )

    frame_dir = FULL_EXTRACT / "cradvntr.dir"
    copied = []
    for index in GO_SHIP_FRAMES:
        src = frame_dir / f"00_{index:02d}.png"
        if not src.is_file():
            print(f"missing frame: {src}", file=sys.stderr)
            return 3
        dst = OUT_DIR / src.name
        shutil.copy2(src, dst)
        copied.append(dst.name)

    manifest = {
        "source": "CRADVNTR.def",
        "lod": str(lod),
        "group": 0,
        "frames": list(GO_SHIP_FRAMES),
        "role": "go_ship_water_hover",
        "primaryFrame": "00_12.png",
        "copied": copied,
    }
    (OUT_DIR / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    print(f"wrote {OUT_DIR} frames={copied}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
