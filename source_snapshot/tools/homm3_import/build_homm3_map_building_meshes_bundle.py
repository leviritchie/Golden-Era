#!/usr/bin/env python3
"""Build homm3_map_building_meshes AssetBundle via Unity batchmode and stage into the plugin."""
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
# Register before exec: unity_queue declares dataclasses, which look their module up in sys.modules.
sys.modules.setdefault("unity_queue", UQ)
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
LOG = SCRIPT_DIR / "unity_homm3_map_building_meshes_bundle.log"
EDITOR_SRC = SCRIPT_DIR / "unity_editor" / "Homm3MapBuildingMeshesBundleBuild.cs"

OFFLINE_UNLOCK_MOD = (
    REPO_ROOT / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod"
)
INVENTORY = REPO_ROOT / "artifacts" / "meshy_map_buildings" / "inventory.json"
MESHES_ROOT = REPO_ROOT / "artifacts" / "meshy_map_buildings" / "meshes"
PLUGIN_STAGE = OFFLINE_UNLOCK_MOD / "homm3_map_building_meshes"
BUNDLE_NAME = "homm3_map_building_meshes"
sys.path.insert(0, str(REPO_ROOT / "tools" / "homm3_map_building_meshes"))
import map_building_facing  # noqa: E402
# The Unity project lives on V: (junction); the editor script re-checks this before every model and stops
# between models, never mid-import. Override with HOMM3_BUNDLE_MIN_FREE_GB.
MIN_FREE_GB = float(os.environ.get("HOMM3_BUNDLE_MIN_FREE_GB", "8"))


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
        fbx = mesh_dir / "model.fbx"
        if (glb.is_file() and glb.stat().st_size > 1000) or (
            fbx.is_file() and fbx.stat().st_size > 1000
        ):
            present += 1
    if present == 0:
        print("No Meshy GLB/FBX present for generate set.", file=sys.stderr)
        return 1
    print(f"Meshy models ready: {present}/{len(generate)}")

    free_gb = shutil.disk_usage(PROJECT.resolve()).free / 1e9
    print(f"Project drive free: {free_gb:.1f} GB (minimum {MIN_FREE_GB:.1f} GB)")
    if free_gb < MIN_FREE_GB:
        print(f"Refusing to launch Unity: {PROJECT.resolve()} drive has {free_gb:.1f} GB free, below {MIN_FREE_GB:.1f} GB",
              file=sys.stderr)
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
        "OldenEra.Homm3Import.Homm3MapBuildingMeshesBundleBuild.BuildFromBatch",
        "-inventoryPath",
        str(INVENTORY),
        "-meshesRoot",
        str(MESHES_ROOT),
        "-outputPath",
        str(OUT),
        "-minFreeGb",
        f"{MIN_FREE_GB:g}",
        "-logFile",
        str(LOG),
    ]
    print("Running:", " ".join(cmd))
    proc = UQ.run_cmd(cmd, kind="map_building_meshes_bundle", direct=UNITY_DIRECT)
    if proc.returncode != 0:
        print(f"Map building meshes bundle build failed; see {LOG}", file=sys.stderr)
        return proc.returncode

    bundle = OUT / BUNDLE_NAME
    catalog = OUT / "catalog.json"
    manifest_path = OUT / f"{BUNDLE_NAME}.asset_manifest.json"
    for required in (bundle, catalog, manifest_path):
        if not required.is_file():
            print(f"Expected output missing: {required}", file=sys.stderr)
            return 1

    catalog_obj = json.loads(catalog.read_text(encoding="utf-8"))
    if catalog_obj.get("schema") != "homm3_map_building_mesh_catalog.v1":
        print(f"catalog schema mismatch: {catalog_obj.get('schema')}", file=sys.stderr)
        return 1
    entries = catalog_obj.get("entries") or []
    if not entries:
        print("catalog has zero entries", file=sys.stderr)
        return 1

    # Per-model front axis (map_building_facing.json): the bundle carries no yaw; the catalog does.
    try:
        turned = map_building_facing.stamp_catalog(catalog_obj, map_building_facing.load_facing())
    except map_building_facing.FacingError as ex:
        print(f"map-building-facing: {ex}", file=sys.stderr)
        return 1
    print(f"Facing: {turned} model(s) with a non-+Z front get a nonzero artYawDegrees")

    PLUGIN_STAGE.mkdir(parents=True, exist_ok=True)
    shutil.copy2(bundle, PLUGIN_STAGE / BUNDLE_NAME)
    (PLUGIN_STAGE / "catalog.json").write_text(json.dumps(catalog_obj, indent=4) + "\n", encoding="utf-8")
    shutil.copy2(manifest_path, PLUGIN_STAGE / "manifest.json")
    print(
        f"Staged {PLUGIN_STAGE / BUNDLE_NAME} "
        f"({(PLUGIN_STAGE / BUNDLE_NAME).stat().st_size} bytes) catalogEntries={len(entries)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
