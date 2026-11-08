#!/usr/bin/env python3
"""Build homm3_artifact_meshes AssetBundle(s) via Unity batchmode and stage into the plugin.

Unity OOMs importing all 155 Meshy GLBs+textures in one session, so this builds
chunked AssetBundles (default 32 prefabs each) and stages them beside one merged
catalog.json / manifest.json. Meshy originals under meshes/ are never mutated.
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
# Dedicated slim project — crusader/pose jobs contend on homm3_unity_work and
# oldenera_factions (~220k assets) OOMs during Meshy imports.
PROJECT = Path(
    os.environ.get(
        "OLDENERA_UNITY_PROJECT",
        os.environ.get("HOMM3_UNITY_PROJECT", r"V:\homm3_artifact_mesh_build"),
    )
)
OUT = SCRIPT_DIR / "build_out" / "artifact_meshes_chunks"
LOG = SCRIPT_DIR / "unity_homm3_artifact_meshes_bundle.log"
EDITOR_SRC = SCRIPT_DIR / "unity_editor" / "Homm3ArtifactMeshesBundleBuild.cs"

OFFLINE_UNLOCK_MOD = (
    REPO_ROOT / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod"
)
INVENTORY = REPO_ROOT / "artifacts" / "meshy_artifacts" / "inventory.json"
MESHES_ROOT = REPO_ROOT / "artifacts" / "meshy_artifacts" / "meshes"
UNITY_STAGE = REPO_ROOT / "artifacts" / "meshy_artifacts" / "unity_import_stage"
PLUGIN_STAGE = OFFLINE_UNLOCK_MOD / "homm3_artifact_meshes"
BUNDLE_PREFIX = "homm3_artifact_meshes"
# Keep chunks small: oldenera_factions has ~220k assets; large per-session
# imports still OOM / abort even with albedo-only 512px staging.
CHUNK_SIZE = 8
UNITY_TEXTURE_MAX_SIDE = 512


def _downsample_png(src: Path, dest: Path, max_side: int) -> None:
    from PIL import Image

    dest.parent.mkdir(parents=True, exist_ok=True)
    im = Image.open(src)
    w, h = im.size
    m = max(w, h)
    if m > max_side:
        scale = max_side / float(m)
        im = im.resize(
            (max(1, int(round(w * scale))), max(1, int(round(h * scale)))),
            Image.Resampling.LANCZOS,
        )
    im.save(dest)


def prepare_unity_stage(generate: list[dict]) -> Path:
    if UNITY_STAGE.exists():
        shutil.rmtree(UNITY_STAGE)
    UNITY_STAGE.mkdir(parents=True, exist_ok=True)
    staged = 0
    for e in generate:
        src_dir = MESHES_ROOT / e["dir"]
        dst_dir = UNITY_STAGE / e["dir"]
        dst_dir.mkdir(parents=True, exist_ok=True)
        model = None
        for name in ("model.glb", "model.fbx"):
            cand = src_dir / name
            if cand.is_file() and cand.stat().st_size > 1000:
                model = cand
                break
        if model is None:
            continue
        dest_model = dst_dir / model.name
        try:
            if dest_model.exists():
                dest_model.unlink()
            os.link(model, dest_model)
        except OSError:
            shutil.copy2(model, dest_model)
        # Albedo only for Unity import (matches editor albedo-only material).
        for png in sorted(src_dir.glob("texture_*_base_color.png")):
            _downsample_png(png, dst_dir / png.name, UNITY_TEXTURE_MAX_SIDE)
        src_fallback = src_dir / "source_00_00.png"
        if src_fallback.is_file():
            _downsample_png(src_fallback, dst_dir / src_fallback.name, UNITY_TEXTURE_MAX_SIDE)
        staged += 1
    if staged == 0:
        raise SystemExit("unity stage empty — no Meshy models to import")
    print(
        f"Unity import stage: {staged} models, albedo maxSide={UNITY_TEXTURE_MAX_SIDE} "
        f"under {UNITY_STAGE}"
    )
    return UNITY_STAGE


def chunked(items: list[dict], size: int) -> list[list[dict]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def wait_for_project_free(timeout_sec: int = 1800) -> None:
    """Block until no Unity.exe has this project open and the lockfile is free."""
    import time

    lock = PROJECT / "Temp" / "UnityLockfile"
    project_norm = str(PROJECT.resolve()).replace("/", "\\").lower()
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        holders = []
        try:
            ps = subprocess.run(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-Command",
                    (
                        "Get-CimInstance Win32_Process -Filter \"name='Unity.exe'\" "
                        "| ForEach-Object { $_.CommandLine }"
                    ),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            for line in (ps.stdout or "").splitlines():
                if project_norm in line.replace("/", "\\").lower():
                    holders.append(line.strip())
        except OSError:
            pass
        lock_held = False
        if lock.is_file():
            try:
                with open(lock, "r+b"):
                    pass
            except OSError:
                lock_held = True
        if not holders and not lock_held:
            if lock.is_file():
                try:
                    lock.unlink()
                except OSError:
                    pass
            print(f"Unity project free: {PROJECT}", flush=True)
            return
        print(
            f"Waiting for Unity project free ({PROJECT.name}); "
            f"holders={len(holders)} lockHeld={lock_held}",
            flush=True,
        )
        time.sleep(15)
    raise SystemExit(f"Timed out waiting for Unity project free: {PROJECT}")


def run_unity_chunk(
    *,
    inventory_path: Path,
    meshes_root: Path,
    output_path: Path,
    bundle_name: str,
    log_path: Path,
) -> None:
    output_path.mkdir(parents=True, exist_ok=True)
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
        "OldenEra.Homm3Import.Homm3ArtifactMeshesBundleBuild.BuildFromBatch",
        "-inventoryPath",
        str(inventory_path),
        "-meshesRoot",
        str(meshes_root),
        "-outputPath",
        str(output_path),
        "-bundleName",
        bundle_name,
        "-logFile",
        str(log_path),
    ]
    print("Running:", " ".join(cmd), flush=True)
    proc = UQ.run_cmd(cmd, kind="artifact_meshes_bundle", direct=UNITY_DIRECT)
    if proc.returncode != 0:
        raise SystemExit(
            f"Artifact meshes chunk '{bundle_name}' failed (exit {proc.returncode}); see {log_path}"
        )
    bundle = output_path / bundle_name
    catalog = output_path / "catalog.json"
    manifest = output_path / f"{bundle_name}.asset_manifest.json"
    for required in (bundle, catalog, manifest):
        if not required.is_file():
            raise SystemExit(f"Expected chunk output missing: {required}")


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
    present = []
    for e in generate:
        mesh_dir = MESHES_ROOT / e["dir"]
        glb = mesh_dir / "model.glb"
        fbx = mesh_dir / "model.fbx"
        if (glb.is_file() and glb.stat().st_size > 1000) or (
            fbx.is_file() and fbx.stat().st_size > 1000
        ):
            present.append(e)
    if not present:
        print("No Meshy GLB/FBX present for generate set.", file=sys.stderr)
        return 1
    print(f"Meshy models ready: {len(present)}/{len(generate)}")

    stage_root = prepare_unity_stage(present)

    editor_dst = PROJECT / "Assets" / "Editor"
    editor_dst.mkdir(parents=True, exist_ok=True)
    shutil.copy2(EDITOR_SRC, editor_dst / EDITOR_SRC.name)

    # Clear leftover Unity import tree from prior OOM runs.
    stale = PROJECT / "Assets" / "Homm3ArtifactMeshes"
    if stale.exists():
        shutil.rmtree(stale, ignore_errors=True)

    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True, exist_ok=True)

    chunks = chunked(present, CHUNK_SIZE)
    merged_entries: list[dict] = []
    merged_assets: list[str] = []
    bundle_names: list[str] = []

    for i, chunk in enumerate(chunks):
        bundle_name = f"{BUNDLE_PREFIX}_{i:02d}"
        chunk_inv = {
            "schema": inv.get("schema"),
            "proof": "chunked unity import",
            "entries": chunk,
        }
        chunk_dir = OUT / bundle_name
        chunk_dir.mkdir(parents=True, exist_ok=True)
        inv_path = chunk_dir / "inventory_chunk.json"
        inv_path.write_text(json.dumps(chunk_inv, indent=2) + "\n", encoding="utf-8")
        # Unity names the folder-level manifest AssetBundle after the output
        # directory — never use the bundle name as the output folder name.
        unity_out = chunk_dir / "out"
        log_path = SCRIPT_DIR / f"unity_homm3_artifact_meshes_bundle_{i:02d}.log"
        print(f"=== chunk {i + 1}/{len(chunks)} bundle={bundle_name} entries={len(chunk)} ===", flush=True)
        run_unity_chunk(
            inventory_path=inv_path,
            meshes_root=stage_root,
            output_path=unity_out,
            bundle_name=bundle_name,
            log_path=log_path,
        )
        cat = json.loads((unity_out / "catalog.json").read_text(encoding="utf-8"))
        man = json.loads(
            (unity_out / f"{bundle_name}.asset_manifest.json").read_text(encoding="utf-8")
        )
        for e in cat.get("entries") or []:
            e = dict(e)
            e["bundle"] = bundle_name
            merged_entries.append(e)
        merged_assets.extend(man.get("assets") or [])
        bundle_names.append(bundle_name)

    merged_catalog = {
        "schema": "homm3_artifact_mesh_catalog.v1",
        "bundle": BUNDLE_PREFIX,
        "bundles": bundle_names,
        "entryCount": len(merged_entries),
        "entries": merged_entries,
    }
    merged_manifest = {
        "schema": "homm3_ui_bundle_asset_manifest.v1",
        "bundle": BUNDLE_PREFIX,
        "bundles": bundle_names,
        "assetCount": len(merged_assets),
        "assets": merged_assets,
    }

    PLUGIN_STAGE.mkdir(parents=True, exist_ok=True)
    # Clear prior staged bundles
    for old in PLUGIN_STAGE.iterdir():
        if old.is_file():
            old.unlink()
    for name in bundle_names:
        src = OUT / name / "out" / name
        shutil.copy2(src, PLUGIN_STAGE / name)
    (PLUGIN_STAGE / "catalog.json").write_text(
        json.dumps(merged_catalog, indent=2) + "\n", encoding="utf-8"
    )
    (PLUGIN_STAGE / "manifest.json").write_text(
        json.dumps(merged_manifest, indent=2) + "\n", encoding="utf-8"
    )
    print(
        f"Staged {len(bundle_names)} chunk bundles under {PLUGIN_STAGE} "
        f"catalogEntries={len(merged_entries)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
