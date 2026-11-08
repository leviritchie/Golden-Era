#!/usr/bin/env python3
"""Factory town backdrop Meshy: high-poly untextured mesh + meshy-6 keep-lighting PBR.

Policy for this huge scene (backdrop only):
  - Mesh: ai_model=meshy-6, model_type=standard, should_remesh=true,
    should_texture=false. Remesh target_polycount range is 100..300000
    (meshy-t2 smart-topology is capped at 15000 — too low for a full town plate).
  - Materials: meshy-6 retexture, remove_lighting=false, enable_pbr=true
  - Source: town_scene_refs Factory background plate (prefer 4K upscaled)

  python tools/homm3_town_scene_meshes/generate_factory_backdrop_pilot.py
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MESHY_DIR = ROOT / "tools" / "homm3_meshy_frame_pose"
sys.path.insert(0, str(MESHY_DIR))
from meshy_client import (  # noqa: E402
    create_image_to_3d,
    create_retexture,
    download_url,
    load_api_key,
    poll_task,
    task_error_message,
)

MOCKUPS = (
    ROOT
    / "Heroes of Might & Magic Olden Era Playtest"
    / "OfflineUnlockMod"
    / "homm3_runtime_assets"
    / "town_scene_refs"
    / "homm3_factory"
    / "mockups"
)
DEFAULT_PNG_4K = MOCKUPS / "homm3_factory_background_upscaled_3840x2160.png"
DEFAULT_PNG_1080 = MOCKUPS / "homm3_factory_background_mock_1920x1080.png"
DEFAULT_OUT = ROOT / "artifacts" / "meshy_town_scene_meshes" / "homm3_factory" / "backdrop"
LAYER_ID = "factory_backdrop"
FRACTION = "homm3_factory"


def glb_url_from_task(task: dict) -> str | None:
    urls = task.get("model_urls") or {}
    if isinstance(urls, dict) and urls.get("glb"):
        return str(urls["glb"])
    result = task.get("result")
    if isinstance(result, dict):
        nested = result.get("model_urls") or {}
        if isinstance(nested, dict) and nested.get("glb"):
            return str(nested["glb"])
        for key in ("glb_url", "model_url"):
            if isinstance(result.get(key), str) and result[key].startswith("http"):
                return str(result[key])
    for key in ("model_url", "glb_url"):
        if isinstance(task.get(key), str) and task[key].startswith("http"):
            return str(task[key])
    return None


def download_textures(task: dict, dest_dir: Path) -> dict:
    out: dict = {}
    texture_urls = task.get("texture_urls") or []
    if not isinstance(texture_urls, list):
        result = task.get("result")
        if isinstance(result, dict):
            texture_urls = result.get("texture_urls") or []
    if not isinstance(texture_urls, list):
        return out
    for i, block in enumerate(texture_urls):
        if not isinstance(block, dict):
            continue
        for key in ("base_color", "metallic", "normal", "roughness", "emission"):
            url = block.get(key)
            if not url:
                continue
            path = dest_dir / f"texture_{i}_{key}.png"
            download_url(str(url), path)
            out[key if i == 0 else f"{key}_{i}"] = str(path).replace("\\", "/")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--png", type=Path, default=None, help="Override source plate PNG")
    ap.add_argument("--prefer-1080", action="store_true", help="Use 1920 plate (smaller upload)")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument(
        "--polycount",
        type=int,
        default=150000,
        help="Remesh target faces for meshy-6 standard (100..300000; default 150000)",
    )
    ap.add_argument("--skip-existing", action="store_true")
    ap.add_argument("--texture-resolution", type=str, default="8k")
    args = ap.parse_args()
    polycount = int(args.polycount)
    if polycount < 100 or polycount > 300000:
        raise SystemExit(f"--polycount must be 100..300000 for meshy-6 standard remesh, got {polycount}")

    if args.png is not None:
        png = args.png if args.png.is_absolute() else ROOT / args.png
    elif args.prefer_1080:
        png = DEFAULT_PNG_1080
    else:
        png = DEFAULT_PNG_4K if DEFAULT_PNG_4K.is_file() else DEFAULT_PNG_1080
    out = args.out if args.out.is_absolute() else ROOT / args.out
    if not png.is_file():
        raise FileNotFoundError(png)

    out.mkdir(parents=True, exist_ok=True)
    tasks_dir = out / "tasks"
    tasks_dir.mkdir(parents=True, exist_ok=True)
    source_copy = out / "source_00_00.png"
    shutil.copy2(png, source_copy)

    mesh_t2 = out / "model_t2_untextured.glb"
    mesh_final = out / "model.glb"
    meta_path = out / "generate_meta.json"

    meta: dict = {
        "fraction": FRACTION,
        "kind": "backdrop",
        "layerId": LAYER_ID,
        "relativePng": (
            f"homm3_runtime_assets/town_scene_refs/{FRACTION}/mockups/{png.name}"
        ),
        "sourcePng": str(png).replace("\\", "/"),
        "policy": {
            "meshAiModel": "meshy-6",
            "meshModelType": "standard",
            "meshShouldRemesh": True,
            "meshShouldTexture": False,
            "targetPolycount": polycount,
            "retextureAiModel": "meshy-6",
            "removeLighting": False,
            "enablePbr": True,
            "note": (
                "Backdrop uses meshy-6 standard remesh (not t2) because t2 smart-topology "
                "caps at 15000 faces — inadequate for a full town plate."
            ),
        },
        "proof": "generated artifact validated — not OE town runtime proven",
    }

    if args.skip_existing and mesh_final.is_file() and mesh_final.stat().st_size > 1000:
        meta["skipped"] = True
        meta["glb"] = str(mesh_final).replace("\\", "/")
        meta["bytes"] = mesh_final.stat().st_size
        meta_path.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(meta, indent=2), flush=True)
        return 0

    api_key = load_api_key()
    print(
        f"[backdrop] meshy-6 standard remesh polycount={polycount} should_texture=false "
        f"src={png.name} bytes={png.stat().st_size}",
        flush=True,
    )
    tid = create_image_to_3d(
        api_key,
        image_path=png,
        should_texture=False,
        target_polycount=polycount,
        model_type="standard",
        ai_model="meshy-6",
        pose_mode=None,
        should_remesh=True,
        enable_pbr=False,
        remove_lighting=None,
    )
    meta["imageTaskId"] = tid
    (tasks_dir / "image_to_3d.json").write_text(
        json.dumps({"taskId": tid}, indent=2) + "\n", encoding="utf-8"
    )
    print(f"[backdrop] poll image-to-3d {tid[:8]}…", flush=True)
    task = poll_task(api_key, "image-to-3d", tid, timeout_s=3600, interval_s=10.0)
    (tasks_dir / "image_to_3d.json").write_text(json.dumps(task, indent=2) + "\n", encoding="utf-8")
    status = str(task.get("status") or "")
    meta["imageStatus"] = status
    meta["imageCredits"] = task.get("consumed_credits") or task.get("credits")
    if status != "SUCCEEDED":
        meta["error"] = task_error_message(task)
        meta_path.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
        raise RuntimeError(f"image-to-3d {status}: {task_error_message(task)}")

    url = glb_url_from_task(task)
    if not url:
        raise RuntimeError(f"image-to-3d SUCCEEDED but no glb url; keys={list(task.keys())}")
    download_url(url, mesh_t2)
    meta["t2Glb"] = str(mesh_t2).replace("\\", "/")
    meta["t2Bytes"] = mesh_t2.stat().st_size
    print(f"[backdrop] untextured mesh {mesh_t2.name} ({meta['t2Bytes']} bytes)", flush=True)

    print(
        "[backdrop] meshy-6 retexture remove_lighting=false enable_pbr=true",
        flush=True,
    )
    rtid = create_retexture(
        api_key,
        input_task_id=tid,
        image_style_path=png,
        ai_model="meshy-6",
        enable_original_uv=True,
        enable_pbr=True,
        remove_lighting=False,
        texture_resolution=str(args.texture_resolution),
    )
    meta["retextureTaskId"] = rtid
    (tasks_dir / "retexture.json").write_text(
        json.dumps({"taskId": rtid}, indent=2) + "\n", encoding="utf-8"
    )
    print(f"[backdrop] poll retexture {rtid[:8]}…", flush=True)
    rtask = poll_task(api_key, "retexture", rtid, timeout_s=3600, interval_s=10.0)
    (tasks_dir / "retexture.json").write_text(json.dumps(rtask, indent=2) + "\n", encoding="utf-8")
    rstatus = str(rtask.get("status") or "")
    meta["retextureStatus"] = rstatus
    meta["retextureCredits"] = rtask.get("consumed_credits") or rtask.get("credits")
    if rstatus != "SUCCEEDED":
        meta["error"] = task_error_message(rtask)
        meta_path.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
        raise RuntimeError(f"retexture {rstatus}: {task_error_message(rtask)}")

    rurl = glb_url_from_task(rtask)
    if not rurl:
        raise RuntimeError(f"retexture SUCCEEDED but no glb url; keys={list(rtask.keys())}")
    download_url(rurl, mesh_final)
    meta["glb"] = str(mesh_final).replace("\\", "/")
    meta["bytes"] = mesh_final.stat().st_size
    meta["textures"] = download_textures(rtask, out)
    if not meta["textures"].get("base_color"):
        meta["albedoNote"] = (
            "retexture task returned no base_color texture_urls; "
            "Unity build may refuse without texture_*_base_color.png"
        )
    meta_path.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    print(f"[backdrop] final {mesh_final.name} ({meta['bytes']} bytes)", flush=True)
    print(json.dumps(meta, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        raise
