#!/usr/bin/env python3
"""Meshy retexture of a def_retarget unit's source mesh, keeping its UV layout.

For a unit whose source mesh carries no texture (hota_cove_seaman: 0 materials, 0 images) or whose
Meshy texture painted a whole part flat (h3_nomad: the rider is one tan fill, no face, vest or
trousers). `enable_original_uv` keeps the mesh's own UVs, so only the image maps change and the
rig, weights and capture are untouched. Output: <out>/retexture.glb, the downloaded maps and
retexture_meta.json (task id, prompt, credits). Paid call: Meshy spend for units is approved
(2026-09-26 standing approval); the credits are recorded in the meta.

  python tools/homm3_meshy_frame_pose/retexture_unit_source_mesh.py --unit h3_nomad \
      --input-task-id <image-to-3d task> --prompt "..." --out artifacts/meshy_downloads/retexture_20261001/h3_nomad
  python tools/homm3_meshy_frame_pose/retexture_unit_source_mesh.py --unit hota_cove_seaman \
      --model-glb artifacts/meshy_downloads/hota_cove_seaman_smartrigged.glb --prompt "..." --out ...

Auth: MESHY_API_KEY from env or repo-root .env (never printed).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from meshy_client import (  # noqa: E402
    create_retexture,
    download_url,
    file_to_data_uri,
    load_api_key,
    poll_task,
    task_error_message,
)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--unit", required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--prompt", required=True, help="text style prompt (part colours)")
    ap.add_argument("--input-task-id", default="")
    ap.add_argument("--model-glb", type=Path, default=None)
    ap.add_argument("--texture-resolution", default="4k")
    ap.add_argument("--remove-lighting", action="store_true")
    ap.add_argument("--resume-task-id", default="", help="poll and download an already created task (no new spend)")
    a = ap.parse_args()
    if bool(a.input_task_id) == bool(a.model_glb):
        ap.error("give exactly one of --input-task-id / --model-glb")

    key = load_api_key()
    a.out.mkdir(parents=True, exist_ok=True)
    tid = a.resume_task_id or create_retexture(
        key,
        input_task_id=a.input_task_id or None,
        model_url=file_to_data_uri(a.model_glb) if a.model_glb else None,
        text_style_prompt=a.prompt,
        enable_original_uv=True,
        enable_pbr=True,
        remove_lighting=a.remove_lighting,
        texture_resolution=a.texture_resolution,
    )
    print(f"[retexture] {a.unit} task {tid}", flush=True)
    task = poll_task(key, "retexture", tid, timeout_s=1800.0, interval_s=10.0)
    meta = {
        "schema": "homm3_unit_source_retexture.v1",
        "unit": a.unit,
        "taskId": tid,
        "status": task.get("status"),
        "prompt": a.prompt,
        "inputTaskId": a.input_task_id or None,
        "modelGlb": str(a.model_glb).replace("\\", "/") if a.model_glb else None,
        "modelGlbSha256": hashlib.sha256(a.model_glb.read_bytes()).hexdigest() if a.model_glb else None,
        "enableOriginalUv": True,
        "removeLighting": bool(a.remove_lighting),
        "textureResolution": a.texture_resolution,
        "consumedCredits": task.get("consumed_credits"),
        "proof": "generated artifact: Meshy retexture download; not yet bound into the unit's source mesh",
    }
    if task.get("status") != "SUCCEEDED":
        meta["error"] = task_error_message(task)
        (a.out / "retexture_meta.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
        print(f"[retexture] FAILED: {meta['error']}", file=sys.stderr)
        return 2
    glb_url = (task.get("model_urls") or {}).get("glb")
    if not glb_url:
        raise RuntimeError("retexture task has no glb url")
    download_url(glb_url, a.out / "retexture.glb")
    meta["retextureGlbSha256"] = hashlib.sha256((a.out / "retexture.glb").read_bytes()).hexdigest()
    maps = {}
    for tex in task.get("texture_urls") or []:
        for name, url in tex.items():
            if isinstance(url, str) and url.startswith("http"):
                dest = a.out / f"texture_0_{name}.png"
                download_url(url, dest)
                maps[name] = dest.name
    meta["maps"] = maps
    (a.out / "retexture_meta.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    print(json.dumps({k: meta[k] for k in ("unit", "taskId", "consumedCredits", "maps")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
