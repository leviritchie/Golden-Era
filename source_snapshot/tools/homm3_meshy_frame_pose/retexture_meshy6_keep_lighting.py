#!/usr/bin/env python3
"""Retexture an existing Meshy t2 mesh with meshy-6 (keep baked lighting + PBR).

Does not regenerate topology. Default: crusader idle_f0 image-to-3d task + painted sprite.

  python tools/homm3_meshy_frame_pose/retexture_meshy6_keep_lighting.py

Auth: MESHY_API_KEY from env or repo-root .env (never printed).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from meshy_client import (  # noqa: E402
    create_retexture,
    download_url,
    load_api_key,
    poll_task,
    task_error_message,
)

DEFAULT_META = ROOT / "artifacts/crusader_pose_pipeline/out_meshy_t2_idle_f0/generate_meta.json"
DEFAULT_IMAGE = (
    ROOT / "artifacts/crusader_pose_pipeline/idle_f0_painted/meshy_ready/frame_00.png"
)
DEFAULT_OUT = ROOT / "artifacts/crusader_pose_pipeline/out_meshy_t2_idle_f0"


def _extract_glb_url(task: dict) -> str | None:
    candidates = []
    mu = task.get("model_urls")
    if isinstance(mu, dict):
        candidates.append(mu.get("glb"))
    result = task.get("result")
    if isinstance(result, dict):
        rmu = result.get("model_urls")
        if isinstance(rmu, dict):
            candidates.append(rmu.get("glb"))
        candidates.append(result.get("glb_url"))
        candidates.append(result.get("model_url"))
    candidates.append(task.get("model_url"))
    candidates.append(task.get("glb_url"))
    for c in candidates:
        if isinstance(c, str) and c.startswith("http"):
            return c
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--meta", type=Path, default=DEFAULT_META)
    ap.add_argument("--image", type=Path, default=DEFAULT_IMAGE)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--input-task-id", type=str, default="")
    ap.add_argument("--model-glb", type=Path, default=None, help="Fallback local GLB via data URI")
    ap.add_argument("--ai-model", type=str, default="meshy-6")
    ap.add_argument("--texture-resolution", type=str, default="8k")
    ap.add_argument(
        "--remove-lighting",
        action="store_true",
        help="Strip baked lighting (default: keep lighting, remove_lighting=false)",
    )
    ap.add_argument("--no-pbr", action="store_true")
    args = ap.parse_args()

    meta_path = args.meta if args.meta.is_absolute() else ROOT / args.meta
    image = args.image if args.image.is_absolute() else ROOT / args.image
    out = args.out if args.out.is_absolute() else ROOT / args.out
    if not image.is_file():
        raise FileNotFoundError(image)

    input_task_id = (args.input_task_id or "").strip()
    model_url = None
    if not input_task_id and meta_path.is_file():
        prev = json.loads(meta_path.read_text(encoding="utf-8"))
        input_task_id = str(prev.get("imageTaskId") or "").strip()
    if not input_task_id:
        glb = args.model_glb
        if glb is None:
            glb = out / "meshes" / "idle_f0.glb"
        glb = glb if glb.is_absolute() else ROOT / glb
        if not glb.is_file():
            raise RuntimeError("need --input-task-id or an existing mesh GLB")
        from meshy_client import file_to_data_uri

        model_url = file_to_data_uri(glb)
        print(f"[retexture] using local model_url from {glb}", flush=True)
    else:
        print(f"[retexture] input_task_id={input_task_id}", flush=True)

    meshes = out / "meshes"
    tasks_dir = out / "tasks"
    meshes.mkdir(parents=True, exist_ok=True)
    tasks_dir.mkdir(parents=True, exist_ok=True)

    api_key = load_api_key()
    remove_lighting = bool(args.remove_lighting)
    enable_pbr = not bool(args.no_pbr)
    print(
        f"[retexture] ai_model={args.ai_model} remove_lighting={remove_lighting} "
        f"enable_pbr={enable_pbr} res={args.texture_resolution}",
        flush=True,
    )
    tid = create_retexture(
        api_key,
        input_task_id=input_task_id or None,
        model_url=model_url,
        image_style_path=image,
        ai_model=args.ai_model,
        enable_original_uv=True,
        enable_pbr=enable_pbr,
        remove_lighting=remove_lighting,
        texture_resolution=args.texture_resolution,
    )
    (tasks_dir / "retexture.json").write_text(
        json.dumps({"taskId": tid}, indent=2) + "\n", encoding="utf-8"
    )
    print(f"[retexture] poll {tid[:8]}…", flush=True)
    task = poll_task(api_key, "retexture", tid, timeout_s=2400, interval_s=8.0)
    (tasks_dir / "retexture.json").write_text(
        json.dumps(task, indent=2) + "\n", encoding="utf-8"
    )
    status = str(task.get("status") or "")
    if status != "SUCCEEDED":
        raise RuntimeError(f"retexture {status}: {task_error_message(task)}")

    glb_url = _extract_glb_url(task)
    if not glb_url:
        raise RuntimeError(f"retexture SUCCEEDED but no glb url; keys={list(task.keys())}")
    dest = meshes / "idle_f0_meshy6_retexture.glb"
    download_url(glb_url, dest)
    print(f"[retexture] wrote {dest} ({dest.stat().st_size} bytes)", flush=True)

    report = {
        "ok": True,
        "retextureTaskId": tid,
        "inputTaskId": input_task_id or None,
        "ai_model": args.ai_model,
        "remove_lighting": remove_lighting,
        "enable_pbr": enable_pbr,
        "enable_original_uv": True,
        "texture_resolution": args.texture_resolution,
        "image": str(image.resolve()).replace("\\", "/"),
        "meshGlb": str(dest.resolve()).replace("\\", "/"),
        "meshBytes": int(dest.stat().st_size),
        "credits": task.get("credits"),
        "proof": (
            "generated artifact validated — meshy-6 retexture on existing t2 mesh; "
            "topology not regenerated; not OE runtime proven"
        ),
    }
    report_path = out / "retexture_meshy6_meta.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if meta_path.is_file():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        meta["retextureMeshy6"] = report
        meta_path.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        raise
