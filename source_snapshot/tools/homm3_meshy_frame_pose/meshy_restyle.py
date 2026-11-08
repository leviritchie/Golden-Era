#!/usr/bin/env python3
"""Paid Meshy restyle steps for one unit: concept edit (image-to-image) and retexture of an existing mesh.

    python tools/homm3_meshy_frame_pose/meshy_restyle.py concept-edit --start --unit U --attempt 1 --prompt "..." --ref a.png [--ref b.png]
    python tools/homm3_meshy_frame_pose/meshy_restyle.py retexture    --start --unit U --attempt 1 (--prompt "..." | --style-image p.png) [--input-task-id ID]
    python tools/homm3_meshy_frame_pose/meshy_restyle.py <step> --poll --unit U --attempt 1
    python tools/homm3_meshy_frame_pose/meshy_restyle.py ledger --unit U

Writes artifacts/meshy_downloads/restyle/<unit>/<step>_a<attempt>/ (request.json, tasks/task.json, outputs).
A queued or finished attempt is never re-created, so a rerun of --start cannot be charged twice.
retexture defaults its input to the unit's identity_regen image-to-3d task and keeps the original UVs,
so the geometry (and a retarget config fitted to it) is unchanged. `ledger` (also run after every poll)
writes restyle/<unit>/meshy_spend.json: every Meshy task id and consumed credits for the unit across
this lane and identity_regen. Proof tier: generated artifact.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from meshy_client import (create_image_to_image, create_retexture, download_url, load_api_key,  # noqa: E402
                          poll_task, task_error_message)

OUT = ROOT / "artifacts/meshy_downloads/restyle"
REGEN = ROOT / "artifacts/meshy_downloads/identity_regen"
KIND = {"concept-edit": "image-to-image", "retexture": "retexture"}


def attempt_dir(unit, step, attempt):
    return OUT / unit / f"{step.replace('-', '_')}_a{attempt}"


def start(key, a):
    d = attempt_dir(a.unit, a.step, a.attempt)
    tf = d / "tasks/task.json"
    if tf.is_file():
        meta = json.loads(tf.read_text(encoding="utf-8"))
        return {"unit": a.unit, "status": "already_queued", "taskId": meta.get("taskId") or meta.get("id")}
    (d / "tasks").mkdir(parents=True, exist_ok=True)
    req = {"step": a.step, "unit": a.unit, "attempt": a.attempt, "prompt": a.prompt}
    if a.step == "concept-edit":
        refs = [Path(r) for r in a.ref]
        for i, r in enumerate(refs):
            shutil.copy2(r, d / f"ref{i}{r.suffix}")
        req.update({"refs": [r.as_posix() for r in refs], "aiModel": a.ai_model or "nano-banana-2"})
        task_id = create_image_to_image(key, prompt=a.prompt, reference_paths=refs, ai_model=req["aiModel"],
                                        aspect_ratio="1:1")
    else:
        src_task = a.input_task_id
        if not src_task:
            regen = json.loads((REGEN / a.unit / "tasks/image_to_3d.json").read_text(encoding="utf-8"))
            src_task = regen.get("taskId") or regen.get("id")
        style = Path(a.style_image) if a.style_image else None
        if style:
            shutil.copy2(style, d / f"style{style.suffix}")
        req.update({"inputTaskId": src_task, "styleImage": style.as_posix() if style else None,
                    "aiModel": a.ai_model or "meshy-6", "enableOriginalUv": True, "removeLighting": False})
        task_id = create_retexture(key, input_task_id=src_task, image_style_path=style,
                                   text_style_prompt=None if style else a.prompt, ai_model=req["aiModel"],
                                   enable_original_uv=True, enable_pbr=True, remove_lighting=False,
                                   texture_resolution="4k")
    (d / "request.json").write_text(json.dumps(req, indent=2) + "\n", encoding="utf-8")
    tf.write_text(json.dumps({"taskId": task_id, "kind": KIND[a.step]}, indent=2) + "\n", encoding="utf-8")
    return {"unit": a.unit, "status": "queued", "taskId": task_id}


def poll(key, a):
    d = attempt_dir(a.unit, a.step, a.attempt)
    tf = d / "tasks/task.json"
    if not tf.is_file():
        return {"unit": a.unit, "status": "not_queued"}
    meta = json.loads(tf.read_text(encoding="utf-8"))
    task_id = meta.get("taskId") or meta.get("id")
    task = poll_task(key, KIND[a.step], task_id, timeout_s=3600, interval_s=10)
    tf.write_text(json.dumps({**task, "taskId": task_id, "kind": KIND[a.step]}, indent=2) + "\n", encoding="utf-8")
    res = {"unit": a.unit, "status": task.get("status"), "taskId": task_id, "credits": task.get("consumed_credits")}
    if task.get("status") != "SUCCEEDED":
        res["error"] = task_error_message(task)
        return res
    files = []
    if a.step == "concept-edit":
        for i, url in enumerate(task.get("image_urls") or []):
            files.append(download_url(url, d / f"edited_{i}.png"))
    else:
        url = (task.get("model_urls") or {}).get("glb")
        if not url:
            res.update({"status": "FAILED", "error": "retexture succeeded without a GLB URL"})
            return res
        files.append(download_url(url, d / "mesh.glb"))
        for tex in task.get("texture_urls") or []:
            for name, u in tex.items():
                if u:
                    files.append(download_url(u, d / f"texture_{name}.png"))
    res["files"] = [p.relative_to(ROOT).as_posix() for p in files]
    (d / "result.json").write_text(json.dumps(res, indent=2) + "\n", encoding="utf-8")
    return res


def ledger(unit):
    rows = []
    for tf in sorted(list((OUT / unit).glob("*/tasks/task.json")) + list((REGEN / unit).glob("tasks/*.json"))):
        t = json.loads(tf.read_text(encoding="utf-8"))
        rows.append({"file": tf.relative_to(ROOT).as_posix(), "taskId": t.get("taskId") or t.get("id"),
                     "kind": t.get("kind") or t.get("type") or "image-to-3d", "status": t.get("status"),
                     "credits": t.get("consumed_credits")})
    out = {"unit": unit, "tasks": rows, "totalCredits": sum(r["credits"] or 0 for r in rows),
           "note": "credits are Meshy's consumed_credits; a task not yet polled to completion shows null"}
    (OUT / unit).mkdir(parents=True, exist_ok=True)
    (OUT / unit / "meshy_spend.json").write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("step", choices=["concept-edit", "retexture", "ledger"])
    ap.add_argument("--unit", required=True)
    ap.add_argument("--start", action="store_true")
    ap.add_argument("--poll", action="store_true")
    ap.add_argument("--attempt", type=int, default=1)
    ap.add_argument("--prompt")
    ap.add_argument("--ref", action="append", default=[])
    ap.add_argument("--style-image")
    ap.add_argument("--input-task-id")
    ap.add_argument("--ai-model")
    a = ap.parse_args()
    if a.step == "ledger":
        print(json.dumps(ledger(a.unit), indent=1))
        return
    if a.start == a.poll:
        ap.error("select exactly one of --start or --poll")
    if a.start and a.step == "concept-edit" and not (a.prompt and a.ref):
        ap.error("concept-edit needs --prompt and --ref")
    if a.start and a.step == "retexture" and not (a.prompt or a.style_image):
        ap.error("retexture needs --prompt or --style-image")
    key = load_api_key()
    r = start(key, a) if a.start else poll(key, a)
    print(json.dumps(r, sort_keys=True), flush=True)
    ledger(a.unit)


if __name__ == "__main__":
    main()
