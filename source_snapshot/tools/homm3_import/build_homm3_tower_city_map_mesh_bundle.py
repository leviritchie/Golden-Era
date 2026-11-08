#!/usr/bin/env python3
"""Build homm3_tower_city_map_mesh AssetBundle via Unity batchmode.

Sources Meshy FBX + PBR textures from:
  artifacts/meshy_tower_castle/Meshy_AI_Blue_Topped_Snow_Cast_0803234740_texture_fbx/

Stages the built bundle beside OfflineUnlockMod as:
  OfflineUnlockMod/homm3_tower_city_map_mesh/homm3_tower_city_map_mesh
  OfflineUnlockMod/homm3_tower_city_map_mesh/manifest.json
"""

from __future__ import annotations

import json
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
UNITY = Path(
    os.environ.get(
        "UNITY_EDITOR",
        r"C:\Program Files\Unity\Hub\Editor\6000.0.66f2\Editor\Unity.exe",
    )
)
PROJECT = Path(os.environ.get("OLDENERA_UNITY_PROJECT", REPO_ROOT / "oldenera_factions"))
OUT = SCRIPT_DIR / "build_out"
LOG = SCRIPT_DIR / "unity_homm3_tower_city_map_mesh_bundle.log"
EDITOR_SRC = SCRIPT_DIR / "unity_editor" / "Homm3TowerCityMapMeshBundleBuild.cs"

OFFLINE_UNLOCK_MOD = (
    REPO_ROOT / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod"
)
SOURCE_DIR = (
    REPO_ROOT
    / "artifacts"
    / "meshy_tower_castle"
    / "Meshy_AI_Blue_Topped_Snow_Cast_0803234740_texture_fbx"
)
PLUGIN_STAGE = OFFLINE_UNLOCK_MOD / "homm3_tower_city_map_mesh"

BUNDLE_NAME = "homm3_tower_city_map_mesh"
PREFAB_ASSET_NAME = "tower_city_map_mesh"


def main() -> int:
    if not UNITY.is_file():
        print(f"Unity editor missing: {UNITY}", file=sys.stderr)
        return 1
    if not (PROJECT / "ProjectSettings" / "ProjectVersion.txt").is_file():
        print(f"Unity project missing: {PROJECT}", file=sys.stderr)
        return 1
    if not SOURCE_DIR.is_dir():
        print(f"Meshy Tower FBX source missing: {SOURCE_DIR}", file=sys.stderr)
        return 1
    fbx_files = list(SOURCE_DIR.glob("*.fbx"))
    albedo_files = list(SOURCE_DIR.glob("*_texture.png"))
    if not fbx_files or not albedo_files:
        print(
            f"Expected FBX + albedo PNG under {SOURCE_DIR}; "
            f"fbx={len(fbx_files)} albedo={len(albedo_files)}",
            file=sys.stderr,
        )
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
        "OldenEra.Homm3Import.Homm3TowerCityMapMeshBundleBuild.BuildFromBatch",
        "-sourceDir",
        str(SOURCE_DIR),
        "-outputPath",
        str(OUT),
        "-logFile",
        str(LOG),
    ]
    print("Using Unity project:", PROJECT)
    print("Meshy source:", SOURCE_DIR)
    print("Running:", " ".join(cmd))
    proc = UQ.run_cmd(cmd, kind="tower_city_map_mesh_bundle", direct=UNITY_DIRECT)
    if proc.returncode != 0:
        print(f"Tower city map mesh bundle build failed; see {LOG}", file=sys.stderr)
        return proc.returncode

    bundle = OUT / BUNDLE_NAME
    if not bundle.is_file():
        print(f"Expected bundle missing: {bundle}", file=sys.stderr)
        return 1

    manifest_path = OUT / f"{BUNDLE_NAME}.asset_manifest.json"
    if not manifest_path.is_file():
        print(f"Expected asset manifest missing: {manifest_path}", file=sys.stderr)
        return 1
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("bundle") != BUNDLE_NAME:
        print(f"Asset manifest bundle mismatch: {manifest.get('bundle')}", file=sys.stderr)
        return 1
    assets = set(manifest.get("assets", []))
    if assets != {PREFAB_ASSET_NAME}:
        print(
            f"Asset manifest membership mismatch: expected [{PREFAB_ASSET_NAME}] got {sorted(assets)}",
            file=sys.stderr,
        )
        return 1
    print(f"Asset manifest lists prefab '{PREFAB_ASSET_NAME}'.")

    PLUGIN_STAGE.mkdir(parents=True, exist_ok=True)
    staged = PLUGIN_STAGE / BUNDLE_NAME
    shutil.copy2(bundle, staged)
    staged_manifest = PLUGIN_STAGE / "manifest.json"
    shutil.copy2(manifest_path, staged_manifest)
    print(f"Built and staged {staged} ({staged.stat().st_size} bytes)")
    print(f"Staged asset manifest {staged_manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
