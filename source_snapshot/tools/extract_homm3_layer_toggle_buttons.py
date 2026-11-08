#!/usr/bin/env python3
"""Extract HoMM3 IAM003/IAM010 adventure surface/underground toggle button frames."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LOD = REPO_ROOT / "HoMM 3 Complete" / "Data" / "H3sprite.lod"
FALLBACK_LOD = REPO_ROOT / "vcmi" / "Data" / "H3sprite.lod"
PLUGIN_DIR = (
    REPO_ROOT
    / "Heroes of Might & Magic Olden Era Playtest"
    / "OfflineUnlockMod"
)
STAGING_DIR = PLUGIN_DIR / "tools" / "generated_homm3_layer_toggle_defs"
FULL_EXTRACT = PLUGIN_DIR / "homm3_adventure_ui" / "_iam_layer_toggle_full"
OUT_DIR = PLUGIN_DIR / "homm3_adventure_ui" / "layer_toggle"

# HoMM3 adventure map elevation buttons (type-71 button DEFs, 32x32).
# IAM003 = surface/overground (sun); IAM010 = underground (cave).
# Frame 0 = normal, 1 = pressed, 2 = disabled, 3 = hover-style.
BUTTONS = (
    ("IAM003.def", "surface", "iam003"),
    ("IAM010.def", "underground", "iam010"),
)
FRAMES = (0, 1, 2, 3)


def run(cmd: list[str]) -> None:
    print("+", " ".join(cmd))
    subprocess.check_call(cmd, cwd=str(REPO_ROOT))


def resolve_lod(explicit: Path | None) -> Path:
    if explicit is not None:
        return explicit.resolve()
    if DEFAULT_LOD.is_file():
        return DEFAULT_LOD.resolve()
    if FALLBACK_LOD.is_file():
        return FALLBACK_LOD.resolve()
    raise FileNotFoundError(f"H3sprite.lod not found at {DEFAULT_LOD} or {FALLBACK_LOD}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lod", type=Path, default=None)
    args = parser.parse_args()
    try:
        lod = resolve_lod(args.lod)
    except FileNotFoundError as ex:
        print(str(ex), file=sys.stderr)
        return 2

    STAGING_DIR.mkdir(parents=True, exist_ok=True)
    FULL_EXTRACT.mkdir(parents=True, exist_ok=True)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    copied: list[str] = []
    for def_name, role, stem in BUTTONS:
        staging_def = STAGING_DIR / def_name
        role_extract = FULL_EXTRACT / stem
        role_out = OUT_DIR / role
        role_extract.mkdir(parents=True, exist_ok=True)
        role_out.mkdir(parents=True, exist_ok=True)

        run(
            [
                sys.executable,
                str(REPO_ROOT / "tools" / "lod_extract_entry_py3.py"),
                str(lod),
                def_name,
                str(staging_def),
            ]
        )
        run(
            [
                sys.executable,
                str(REPO_ROOT / "tools" / "defextract_py3.py"),
                str(staging_def),
                str(role_extract),
            ]
        )

        frame_dir = role_extract / f"{stem}.dir"
        for index in FRAMES:
            src = frame_dir / f"00_{index:02d}.png"
            if not src.is_file():
                print(f"missing frame: {src}", file=sys.stderr)
                return 3
            dst = role_out / src.name
            shutil.copy2(src, dst)
            copied.append(f"{role}/{dst.name}")

    manifest = {
        "sourceLod": str(lod),
        "buttons": [
            {
                "def": def_name,
                "role": role,
                "frames": [f"00_{index:02d}.png" for index in FRAMES],
                "frameSemantics": {
                    "00_00.png": "normal",
                    "00_01.png": "pressed",
                    "00_02.png": "disabled",
                    "00_03.png": "hover",
                },
                "nativeSize": [32, 32],
            }
            for def_name, role, _stem in BUTTONS
        ],
        "ux": {
            "showDestinationIcon": True,
            "onSurfaceShow": "underground",
            "onUndergroundShow": "surface",
        },
        "copied": copied,
    }
    (OUT_DIR / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    print(f"wrote {OUT_DIR} frames={copied}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
