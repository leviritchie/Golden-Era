#!/usr/bin/env python3
"""Build homm3_dialog_portraits AssetBundle via Unity batchmode."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

# Unity jobs go through the Unity queue (docs/unity_queue_runner.md): agents submit, not launch. --unity-direct is the
# explicit, loudly logged opt-out.
import importlib.util as _uq_ilu  # noqa: E402
_uq_spec = _uq_ilu.spec_from_file_location("unity_queue", Path(__file__).resolve().parents[1] / "unity_queue" / "unity_queue.py")
UQ = _uq_ilu.module_from_spec(_uq_spec)
_uq_spec.loader.exec_module(UQ)
UNITY_DIRECT = UQ.take_direct_flag()

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_DIR = Path(__file__).resolve().parent
UNITY = Path(os.environ.get(
    "UNITY_EDITOR",
    r"C:\Program Files\Unity\Hub\Editor\6000.0.66f2\Editor\Unity.exe",
))
PROJECT = Path(os.environ.get("OLDENERA_UNITY_PROJECT", REPO_ROOT / "oldenera_factions"))
OUT = SCRIPT_DIR / "build_out"
LOG = SCRIPT_DIR / "unity_homm3_dialog_portrait_bundle.log"
EDITOR_SRC = SCRIPT_DIR / "unity_editor" / "Homm3DialogPortraitBundleBuild.cs"
PLUGIN_SRC = (
    REPO_ROOT
    / "Heroes of Might & Magic Olden Era Playtest"
    / "OfflineUnlockMod"
    / "homm3_dialog_portraits"
)

UPSCALED = (
    REPO_ROOT
    / "Heroes of Might & Magic Olden Era Playtest"
    / "OfflineUnlockMod"
    / "homm3_hero_portraits_upscaled"
)
STANDARD = (
    REPO_ROOT
    / "Heroes of Might & Magic Olden Era Playtest"
    / "OfflineUnlockMod"
    / "homm3_hero_portraits"
)


def main() -> int:
    if not UNITY.is_file():
        print(f"Unity editor missing: {UNITY}", file=sys.stderr)
        return 1
    if not (PROJECT / "ProjectSettings" / "ProjectVersion.txt").is_file():
        print(f"Unity project missing: {PROJECT}", file=sys.stderr)
        return 1

    portrait_dir = UPSCALED if (UPSCALED / "homm3_stronghold_hero_2.png").is_file() else STANDARD
    if not (portrait_dir / "homm3_stronghold_hero_2.png").is_file():
        print(f"Portrait PNG missing under {portrait_dir}", file=sys.stderr)
        return 1

    editor_dst = PROJECT / "Assets" / "Editor"
    editor_dst.mkdir(parents=True, exist_ok=True)
    shutil.copy2(EDITOR_SRC, editor_dst / EDITOR_SRC.name)

    OUT.mkdir(parents=True, exist_ok=True)
    cmd = [
        str(UNITY),
        "-batchmode",
        "-quit",
        "-nographics",
        "-projectPath",
        str(PROJECT),
        "-buildTarget",
        "StandaloneWindows64",
        "-executeMethod",
        "OldenEra.Homm3Import.Homm3DialogPortraitBundleBuild.BuildFromBatch",
        "-portraitDir",
        str(portrait_dir),
        "-outputPath",
        str(OUT),
        "-logFile",
        str(LOG),
    ]
    print("Using Unity project:", PROJECT)
    print("Portrait source:", portrait_dir)
    print("Running:", " ".join(cmd))
    proc = UQ.run_cmd(cmd, kind="dialog_portrait_bundle", direct=UNITY_DIRECT)
    if proc.returncode != 0:
        print(f"Dialog portrait bundle build failed; see {LOG}", file=sys.stderr)
        return proc.returncode

    bundle = OUT / "homm3_dialog_portraits"
    if not bundle.is_file():
        print(f"Expected bundle missing: {bundle}", file=sys.stderr)
        return 1

    PLUGIN_SRC.mkdir(parents=True, exist_ok=True)
    staged = PLUGIN_SRC / "homm3_dialog_portraits"
    shutil.copy2(bundle, staged)
    print(f"Built and staged {staged}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
