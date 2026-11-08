#!/usr/bin/env python3
"""Build homm3_town_scene_meshes AssetBundle via Unity batchmode and stage into the plugin."""
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
OUT = SCRIPT_DIR / "build_out_town_scene_meshes"
LOG = SCRIPT_DIR / "unity_homm3_town_scene_meshes_bundle.log"
EDITOR_SRC = SCRIPT_DIR / "unity_editor" / "Homm3TownSceneMeshesBundleBuild.cs"
# The shared oldenera_factions project is serialized by the Unity queue (docs/unity_queue_runner.md);
# never launch Unity on it directly.

OFFLINE_UNLOCK_MOD = (
    REPO_ROOT / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod"
)
INVENTORY = REPO_ROOT / "artifacts" / "meshy_town_scene_meshes" / "inventory.json"
MESHES_ROOT = REPO_ROOT / "artifacts" / "meshy_town_scene_meshes"
PLUGIN_STAGE = OFFLINE_UNLOCK_MOD / "homm3_town_scene_meshes"
BUNDLE_NAME = "homm3_town_scene_meshes"


def main() -> int:
    if not UNITY.is_file():
        print(f"Unity editor missing: {UNITY}", file=sys.stderr)
        return 1
    if not (PROJECT / "ProjectSettings" / "ProjectVersion.txt").is_file():
        print(f"Unity project missing: {PROJECT}", file=sys.stderr)
        return 1
    if not INVENTORY.is_file():
        print(f"inventory missing: {INVENTORY}", file=sys.stderr)
        return 1
    if not MESHES_ROOT.is_dir():
        print(f"meshes root missing: {MESHES_ROOT}", file=sys.stderr)
        return 1

    inv = json.loads(INVENTORY.read_text(encoding="utf-8"))
    generate = [e for e in inv.get("entries") or [] if e.get("generate")]
    present = 0
    for e in generate:
        mesh_dir = MESHES_ROOT / e["dir"]
        glb = mesh_dir / "model.glb"
        if glb.is_file() and glb.stat().st_size > 1000:
            present += 1
    if present == 0:
        print("No Meshy GLB present for town-scene generate set.", file=sys.stderr)
        return 1
    print(f"Meshy town-scene models ready: {present}/{len(generate)}")

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
        "OldenEra.Homm3Import.Homm3TownSceneMeshesBundleBuild.BuildFromBatch",
        "-inventoryPath",
        str(INVENTORY),
        "-meshesRoot",
        str(MESHES_ROOT),
        "-outputPath",
        str(OUT),
        "-logFile",
        str(LOG),
    ]
    print("Running:", " ".join(cmd))
    proc = UQ.run_cmd(cmd, kind="town_scene_meshes_bundle", direct=UNITY_DIRECT)
    if proc.returncode != 0:
        print(f"Town scene meshes bundle build failed; see {LOG}", file=sys.stderr)
        return proc.returncode

    bundle = OUT / BUNDLE_NAME
    catalog = OUT / "catalog.json"
    manifest_path = OUT / f"{BUNDLE_NAME}.asset_manifest.json"
    for required in (bundle, catalog, manifest_path):
        if not required.is_file():
            print(f"Expected output missing: {required}", file=sys.stderr)
            return 1

    catalog_obj = json.loads(catalog.read_text(encoding="utf-8"))
    if catalog_obj.get("schema") != "homm3_town_scene_mesh_catalog.v1":
        print(f"catalog schema mismatch: {catalog_obj.get('schema')}", file=sys.stderr)
        return 1
    entries = catalog_obj.get("entries") or []
    if not entries:
        print("catalog has zero entries", file=sys.stderr)
        return 1

    # Enrich seating fields from inventory (Unity catalog only carries prefab keys).
    by_png = {
        str(e.get("relativePng") or "").replace("\\", "/").lower(): e
        for e in generate
    }
    for entry in entries:
        key = str(entry.get("relativePng") or "").replace("\\", "/").lower()
        src = by_png.get(key)
        if not src:
            print(f"catalog entry missing inventory row: {entry.get('relativePng')}", file=sys.stderr)
            return 1
        for field in (
            "fraction",
            "buildingSid",
            "layerId",
            "nativeLevel",
            "stageDepthFromBackdrop",
        ):
            if field in src:
                entry[field] = src[field]
    catalog.write_text(json.dumps(catalog_obj, indent=2) + "\n", encoding="utf-8")

    PLUGIN_STAGE.mkdir(parents=True, exist_ok=True)
    shutil.copy2(bundle, PLUGIN_STAGE / BUNDLE_NAME)
    shutil.copy2(catalog, PLUGIN_STAGE / "catalog.json")
    shutil.copy2(manifest_path, PLUGIN_STAGE / "manifest.json")
    print(
        f"Staged {PLUGIN_STAGE / BUNDLE_NAME} "
        f"({(PLUGIN_STAGE / BUNDLE_NAME).stat().st_size} bytes) catalogEntries={len(entries)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
