#!/usr/bin/env python3
"""Generate one explicit Meshy 7.1 prop candidate without touching a body candidate.

The prop image is copied into the output directory before the task is submitted. A task
record is reused fail-closed, so polling or resuming never creates a second paid request.
This is a geometry candidate only; attachment, skinning, and motion review remain separate.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from meshy_client import (  # noqa: E402
    create_image_to_3d,
    download_url,
    load_api_key,
    poll_task,
    task_error_message,
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def glb_url(task: dict) -> str | None:
    model_urls = task.get("model_urls") or {}
    if isinstance(model_urls, dict) and model_urls.get("glb"):
        return str(model_urls["glb"])
    result = task.get("result") or {}
    if isinstance(result, dict):
        nested = result.get("model_urls") or {}
        if isinstance(nested, dict) and nested.get("glb"):
            return str(nested["glb"])
        for key in ("glb_url", "model_url"):
            if result.get(key):
                return str(result[key])
    for key in ("glb_url", "model_url"):
        if task.get(key):
            return str(task[key])
    return None


def texture_urls(task: dict, dest: Path) -> dict[str, str]:
    textures: dict[str, str] = {}
    for index, entry in enumerate(task.get("texture_urls") or []):
        if not isinstance(entry, dict):
            continue
        for kind in ("base_color", "metallic", "normal", "roughness", "emission"):
            url = entry.get(kind)
            if not url:
                continue
            path = dest / f"texture_{index}_{kind}.png"
            download_url(str(url), path)
            textures[kind if index == 0 else f"{kind}_{index}"] = str(path.resolve()).replace("\\", "/")
    return textures


def paths(out: Path) -> tuple[Path, Path, Path]:
    return out / "input.png", out / "tasks/image_to_3d.json", out / "candidate_meta.json"


def start(args: argparse.Namespace) -> int:
    source = args.input.resolve()
    if not source.is_file():
        raise SystemExit(f"fail-closed: prop input does not exist: {source}")
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    input_copy, task_path, meta_path = paths(out)
    task_path.parent.mkdir(parents=True, exist_ok=True)
    if task_path.is_file():
        raise SystemExit(f"fail-closed: task already exists; use poll: {task_path}")
    if (out / "mesh.glb").is_file():
        raise SystemExit(f"fail-closed: candidate already exists: {out / 'mesh.glb'}")
    shutil.copy2(source, input_copy)
    policy = {
        "schema": "meshy71.prop_candidate.v1",
        "unitSid": args.unit,
        "prop": args.prop,
        "sourceImage": str(input_copy).replace("\\", "/"),
        "sourceImageSha256": sha256(input_copy),
        "aiModel": "meshy-7.1",
        "modelType": "standard",
        "targetPolycount": int(args.polycount),
        "shouldTexture": True,
        "enablePbr": True,
        "shouldRemesh": True,
        "imageEnhancement": False,
        "poseMode": "",
        "autoRig": False,
        "proof": "generated prop candidate only",
    }
    task_id = create_image_to_3d(
        load_api_key(),
        image_path=input_copy,
        should_texture=True,
        target_polycount=int(args.polycount),
        model_type="standard",
        ai_model="meshy-7.1",
        should_remesh=True,
        enable_pbr=True,
        texture_resolution="4k",
        image_enhancement=False,
    )
    print(json.dumps({"status": "created", "taskId": task_id}), flush=True)
    task_path.write_text(json.dumps({"taskId": task_id, "policy": policy}, indent=2) + "\n", encoding="utf-8")
    meta_path.write_text(json.dumps({"schema": policy["schema"], "status": "QUEUED", "taskId": task_id,
                                     "policy": policy}, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "queued", "taskId": task_id, "policy": policy}, indent=2))
    return 0


def poll(args: argparse.Namespace) -> int:
    out = args.out.resolve()
    input_copy, task_path, meta_path = paths(out)
    if not task_path.is_file():
        raise SystemExit(f"fail-closed: no task record: {task_path}")
    record = json.loads(task_path.read_text(encoding="utf-8"))
    task_id = str(record.get("taskId") or "")
    if not task_id:
        raise SystemExit(f"fail-closed: task record has no taskId: {task_path}")
    task = poll_task(load_api_key(), "image-to-3d", task_id, timeout_s=args.timeout_s, interval_s=10.0)
    task_path.write_text(json.dumps(task, indent=2) + "\n", encoding="utf-8")
    status = str(task.get("status") or "")
    policy = record.get("policy") or {}
    if status != "SUCCEEDED":
        meta_path.write_text(json.dumps({"schema": policy.get("schema"), "status": status,
                                         "taskId": task_id, "policy": policy,
                                         "error": task_error_message(task)}, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"status": status, "taskId": task_id, "error": task_error_message(task)}, indent=2))
        return 2
    url = glb_url(task)
    if not url:
        raise SystemExit("fail-closed: succeeded Meshy task has no GLB URL")
    staging = out / "mesh.new.glb"
    download_url(url, staging)
    if staging.stat().st_size <= 1000:
        raise SystemExit(f"fail-closed: candidate GLB is too small: {staging.stat().st_size}")
    textures = texture_urls(task, out)
    staging.replace(out / "mesh.glb")
    result = {"schema": policy.get("schema"), "status": "SUCCEEDED", "taskId": task_id,
              "policy": policy, "mesh": str((out / "mesh.glb").resolve()).replace("\\", "/"),
              "meshBytes": (out / "mesh.glb").stat().st_size, "textures": textures,
              "proof": "generated prop candidate only; attachment and deformation audit outstanding"}
    meta_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    start_parser = sub.add_parser("start")
    start_parser.add_argument("--unit", required=True)
    start_parser.add_argument("--prop", required=True)
    start_parser.add_argument("--input", required=True, type=Path)
    start_parser.add_argument("--out", required=True, type=Path)
    start_parser.add_argument("--polycount", type=int, default=8000)
    start_parser.set_defaults(handler=start)
    poll_parser = sub.add_parser("poll")
    poll_parser.add_argument("--out", required=True, type=Path)
    poll_parser.add_argument("--timeout-s", type=float, default=1800.0)
    poll_parser.set_defaults(handler=poll)
    args = parser.parse_args()
    if getattr(args, "polycount", 1) <= 0:
        parser.error("--polycount must be positive")
    return int(args.handler(args))


if __name__ == "__main__":
    raise SystemExit(main())
