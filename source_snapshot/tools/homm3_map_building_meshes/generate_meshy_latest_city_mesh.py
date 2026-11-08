#!/usr/bin/env python3
"""Regenerate ONE adventure-map city mesh with Meshy's latest standard model at a fixed polycount.

User-approved explicit redo (2026-10-03, Cove first). Input is the painted-upscale master of the wired city
plate (``artifacts/static_asset_painted_upscale/final``), else the extract; never town-screen art. ``--source-image``
overrides that with an explicit image: use it when the painted master is unfaithful (the Cove master was an AI
repaint that hallucinated a thatched palisade; the 2026-10-03 second redo fed a Lanczos-only upscale of the
original sprite instead).

Policy (locked here, recorded in generate_meta.json):
  - ai_model=meshy-7.1 (docs.meshy.ai image-to-3d: ``latest`` aliases Meshy 7.1; meshy-7 is deprecated),
    model_type=standard
  - should_remesh=true + target_polycount (default 12000; the API needs remesh for a standard polycount)
  - should_texture=true, enable_pbr=true, texture_resolution=4k
  - image_enhancement=false (keep HoMM3 paint), remove_lighting=false (as generate_meshy7_city_meshes.py)

The live model.glb is backed up once to ``model.pre_meshy7.glb`` (same name as the meshy7 generator) and only
replaced after a GLB and a base_color texture downloaded. ``--backup-as NAME`` also keeps the current live model
under NAME (once) before replacing it, e.g. ``model.pre_original_src.glb``; the previous generate_meta.json is kept
inside the new one as ``previousGenerate``. A regenerated model must be re-inspected for its front
axis (map_building_facing.json records glbBytes, and the mesh contract fails until it is updated).

    python tools/homm3_map_building_meshes/generate_meshy_latest_city_mesh.py --faction cove
    python tools/homm3_map_building_meshes/generate_meshy_latest_city_mesh.py --faction cove         --source-image V:/olden_port_work/cove_map_town_v2/input_a.png --backup-as model.pre_original_src.glb
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "homm3_meshy_frame_pose"))
from meshy_client import create_image_to_3d, download_url, load_api_key, poll_task, task_error_message  # noqa: E402

INVENTORY = ROOT / "artifacts" / "meshy_map_buildings" / "inventory.json"
OUT = ROOT / "artifacts" / "meshy_map_buildings"
PAINTED = ROOT / "artifacts" / "static_asset_painted_upscale" / "final"
PLUGIN = ROOT / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod"
AI_MODEL = "meshy-7.1"
BACKUP_NAME = "model.pre_meshy7.glb"


def city_entry(faction: str) -> dict:
    inv = json.loads(INVENTORY.read_text(encoding="utf-8"))
    rows = [e for e in inv.get("entries") or []
            if e.get("kind") == "city" and e.get("factionSid") == f"homm3_{faction}" and e.get("generate")]
    if len(rows) != 1:
        raise RuntimeError(f"expected one generate city row for homm3_{faction}, found {len(rows)}")
    return rows[0]


def source_png(entry: dict) -> Path:
    painted = PAINTED / entry["relativePng"].replace("\\", "/").replace("/", "__")
    if painted.is_file():
        return painted
    extract = PLUGIN / entry["relativePng"]
    if not extract.is_file():
        raise FileNotFoundError(f"no painted master or extract for {entry['relativePng']}")
    return extract


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--faction", required=True, help="city faction slug without homm3_, e.g. cove")
    ap.add_argument("--target-polycount", type=int, default=12000)
    ap.add_argument("--texture-resolution", default="4k", choices=("2k", "4k"))
    ap.add_argument("--source-image", type=Path, help="explicit input image (overrides the painted master)")
    ap.add_argument("--backup-as", help="also keep the current live model.glb under this name (once)")
    a = ap.parse_args()
    if a.backup_as and (Path(a.backup_as).name != a.backup_as or not a.backup_as.endswith(".glb")
                        or a.backup_as in ("model.glb", BACKUP_NAME)):
        ap.error("--backup-as must be a plain *.glb file name other than model.glb / " + BACKUP_NAME)
    entry = city_entry(a.faction.strip().lower())
    if a.source_image is not None:
        src = a.source_image.resolve()
        if not src.is_file():
            ap.error(f"--source-image not found: {src}")
    else:
        src = source_png(entry)
    dest = OUT / "meshes" / entry["dir"]
    tasks = dest / "tasks"
    tasks.mkdir(parents=True, exist_ok=True)
    prev_meta_path = dest / "generate_meta.json"
    prev_meta = json.loads(prev_meta_path.read_text(encoding="utf-8")) if prev_meta_path.is_file() else None
    shutil.copy2(src, dest / "source_00_00.png")
    policy = {"meshAiModel": AI_MODEL, "modelType": "standard", "meshShouldTexture": True, "enablePbr": True,
              "removeLighting": False, "shouldRemesh": True, "targetPolycount": a.target_polycount,
              "imageEnhancement": False, "textureResolution": a.texture_resolution}
    meta = {"relativePng": entry["relativePng"], "prefabKey": entry["prefabKey"], "kind": entry["kind"],
            "targetHeight": entry["targetHeight"], "sourcePng": str(src).replace("\\", "/"),
            "sourceKind": "explicit" if a.source_image is not None else "painted_master_or_extract", "policy": policy}
    if prev_meta is not None:
        meta["previousGenerate"] = prev_meta
    api_key = load_api_key()
    print(f"[gen] {AI_MODEL} remesh {a.target_polycount} {entry['relativePng']} <- {src.name}", flush=True)
    tid = create_image_to_3d(api_key, image_path=src, should_texture=True, target_polycount=a.target_polycount,
                             model_type="standard", ai_model=AI_MODEL, should_remesh=True, enable_pbr=True,
                             remove_lighting=False, texture_resolution=a.texture_resolution,
                             image_enhancement=False)
    meta["imageTaskId"] = tid
    task_file = tasks / f"image_to_3d_meshy71_{tid[:8]}.json"
    task_file.write_text(json.dumps({"taskId": tid}, indent=2) + "\n", encoding="utf-8")
    task = poll_task(api_key, "image-to-3d", tid, timeout_s=3600, interval_s=15.0)
    task_file.write_text(json.dumps(task, indent=2) + "\n", encoding="utf-8")
    meta["imageStatus"] = str(task.get("status") or "")
    meta["imageCredits"] = task.get("consumed_credits") or task.get("credits")

    def fail(msg: str) -> int:
        meta["error"] = msg
        (dest / "generate_meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
        print(f"[gen] FAILED: {msg}", file=sys.stderr)
        return 2

    if meta["imageStatus"] != "SUCCEEDED":
        return fail(task_error_message(task))
    url = (task.get("model_urls") or {}).get("glb")
    if not url:
        return fail(f"no glb url; keys={sorted(task)}")
    staging = dest / "model.meshy71_new.glb"
    download_url(str(url), staging)
    if staging.stat().st_size <= 1000:
        staging.unlink(missing_ok=True)
        return fail("glb too small")
    textures: dict[str, str] = {}
    for i, block in enumerate(task.get("texture_urls") or []):
        for key in ("base_color", "metallic", "normal", "roughness", "emission"):
            if isinstance(block, dict) and block.get(key):
                path = dest / f"texture_{i}_{key}.png.new"
                download_url(str(block[key]), path)
                textures[key if i == 0 else f"{key}_{i}"] = path.name[:-4]
    if "base_color" not in textures:
        staging.unlink(missing_ok=True)
        for p in dest.glob("texture_*.png.new"):
            p.unlink()
        return fail("no base_color texture; refuse to replace live GLB")
    for stale in dest.glob("texture_*.png"):
        stale.unlink()
    for p in dest.glob("texture_*.png.new"):
        p.replace(p.with_suffix(""))
    live = dest / "model.glb"
    backup = dest / BACKUP_NAME
    if live.is_file() and live.stat().st_size > 1000 and not backup.is_file():
        shutil.copy2(live, backup)
        meta["backupGlb"] = str(backup).replace("\\", "/")
    if a.backup_as and live.is_file() and live.stat().st_size > 1000:
        extra = dest / a.backup_as
        if not extra.is_file():
            shutil.copy2(live, extra)
        meta["extraBackupGlb"] = str(extra).replace("\\", "/")
    staging.replace(live)
    meta["glb"] = str(live).replace("\\", "/")
    meta["bytes"] = live.stat().st_size
    meta["textures"] = {k: str(dest / v).replace("\\", "/") for k, v in textures.items()}
    (dest / "generate_meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "glb": meta["glb"], "bytes": meta["bytes"], "credits": meta["imageCredits"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
