#!/usr/bin/env python3
"""Queue and download Meshy-7 meshes for units with no own mesh.

This lane deliberately stops at a textured, soft-lit mesh.  Rigging remains a
separate handoff to the Astra/Blender worker, so a Meshy output can never be
mistaken for a completed SmartRig.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOL_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOL_DIR))
from meshy_client import (  # noqa: E402
    create_image_to_3d,
    download_url,
    load_api_key,
    poll_task,
    task_error_message,
)

COVERAGE = ROOT / "artifacts/meshy_downloads/homm3_mesh_coverage.json"
OUT_ROOT = ROOT / "artifacts/meshy_downloads/meshy7_missing"


def _glb_url(task: dict) -> str | None:
    urls = task.get("model_urls") or {}
    if isinstance(urls, dict) and urls.get("glb"):
        return str(urls["glb"])
    result = task.get("result")
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


def _download_textures(task: dict, dest: Path) -> dict[str, str]:
    textures: dict[str, str] = {}
    rows = task.get("texture_urls") or []
    if not isinstance(rows, list):
        return textures
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        for kind in ("base_color", "metallic", "normal", "roughness", "emission"):
            url = row.get(kind)
            if not url:
                continue
            path = dest / f"texture_{index}_{kind}.png"
            download_url(str(url), path)
            textures[kind if index == 0 else f"{kind}_{index}"] = str(path.resolve()).replace("\\", "/")
    return textures


def _unit_records() -> list[dict]:
    coverage = json.loads(COVERAGE.read_text(encoding="utf-8"))
    return [
        row
        for row in coverage["records"]
        if row.get("status") == "mesh_missing" and row.get("imageInput")
    ]


def _unit_dir(sid: str) -> Path:
    path = OUT_ROOT / sid
    path.mkdir(parents=True, exist_ok=True)
    (path / "tasks").mkdir(exist_ok=True)
    return path


def _start_one(api_key: str, row: dict) -> dict:
    sid = str(row["unitSid"])
    dest = _unit_dir(sid)
    source = Path(str(row["imageInput"]))
    if not source.is_file():
        raise FileNotFoundError(source)
    source_copy = dest / "source.png"
    if not source_copy.is_file():
        shutil.copy2(source, source_copy)
    task_file = dest / "tasks/image_to_3d.json"
    existing = {}
    if task_file.is_file():
        try:
            existing = json.loads(task_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            existing = {}
    # The API response written by --poll uses ``id`` while the launch
    # envelope uses ``taskId``.  Read both forms so a completed task cannot be
    # charged a second time when --start is rerun.
    existing_task_id = str(existing.get("taskId") or existing.get("id") or "")
    if (dest / "mesh.glb").is_file() and (dest / "generate_meta.json").is_file():
        try:
            generated = json.loads((dest / "generate_meta.json").read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            generated = {}
        if generated.get("status") == "SUCCEEDED":
            return {"unitSid": sid, "status": "already_succeeded", "taskId": existing_task_id or None}
    if existing_task_id:
        return {"unitSid": sid, "status": "already_queued", "taskId": existing_task_id}
    task_id = create_image_to_3d(
        api_key,
        image_path=source_copy,
        should_texture=True,
        target_polycount=None,
        model_type="standard",
        ai_model="meshy-7",
        should_remesh=True,
        enable_pbr=True,
        remove_lighting=False,
        texture_resolution="4k",
        decimation_mode=3,
        image_enhancement=False,
    )
    task_file.write_text(
        json.dumps(
            {
                "taskId": task_id,
                "unitSid": sid,
                "source": str(source.resolve()).replace("\\", "/"),
                "policy": {
                    "aiModel": "meshy-7",
                    "modelType": "standard",
                    "shouldTexture": True,
                    "enablePbr": True,
                    "removeLighting": False,
                    "shouldRemesh": True,
                    "decimationMode": 3,
                    "textureResolution": "4k",
                    "imageEnhancement": False,
                },
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return {"unitSid": sid, "status": "queued", "taskId": task_id}


def _poll_one(api_key: str, row: dict) -> dict:
    sid = str(row["unitSid"])
    dest = _unit_dir(sid)
    task_file = dest / "tasks/image_to_3d.json"
    if not task_file.is_file():
        return {"unitSid": sid, "status": "not_queued"}
    meta = json.loads(task_file.read_text(encoding="utf-8"))
    # Preserve compatibility with the API's completed-task response, which
    # stores the identifier under ``id`` rather than ``taskId``.
    task_id = str(meta.get("taskId") or meta.get("id") or "")
    if not task_id:
        return {"unitSid": sid, "status": "missing_task_id"}
    task = poll_task(api_key, "image-to-3d", task_id, timeout_s=3600, interval_s=10)
    task_file.write_text(json.dumps(task, indent=2) + "\n", encoding="utf-8")
    status = str(task.get("status") or "")
    result = {"unitSid": sid, "status": status, "taskId": task_id}
    if status != "SUCCEEDED":
        result["error"] = task_error_message(task)
        (dest / "generate_meta.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        return result
    url = _glb_url(task)
    if not url:
        result.update({"status": "FAILED", "error": "Meshy-7 task succeeded without a GLB URL"})
        (dest / "generate_meta.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        return result
    staging = dest / "mesh.meshy7_new.glb"
    download_url(url, staging)
    if staging.stat().st_size <= 1000:
        result.update({"status": "FAILED", "error": f"GLB too small: {staging.stat().st_size}"})
        staging.unlink(missing_ok=True)
        (dest / "generate_meta.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        return result
    textures = _download_textures(task, dest)
    if "base_color" not in textures:
        result.update({"status": "FAILED", "error": "Meshy-7 returned no base_color texture"})
        staging.unlink(missing_ok=True)
        (dest / "generate_meta.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        return result
    mesh = dest / "mesh.glb"
    staging.replace(mesh)
    result.update(
        {
            "status": "SUCCEEDED",
            "mesh": str(mesh.resolve()).replace("\\", "/"),
            "meshBytes": mesh.stat().st_size,
            "textures": textures,
            "proof": "generated artifact validated - Meshy-7 textured mesh; rigging delegated to Astra/Blender",
        }
    )
    (dest / "generate_meta.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", action="store_true", help="create image-to-3d tasks")
    parser.add_argument("--poll", action="store_true", help="poll queued tasks and download meshes")
    parser.add_argument("--parallel", type=int, default=3)
    parser.add_argument("--unit", action="append", default=[])
    args = parser.parse_args()
    if args.start == args.poll:
        parser.error("select exactly one of --start or --poll")
    rows = _unit_records()
    wanted = set(args.unit)
    if wanted:
        rows = [row for row in rows if row["unitSid"] in wanted]
    if not rows:
        print(json.dumps({"ok": True, "results": [], "note": "no eligible units"}, indent=2))
        return 0
    api_key = load_api_key()
    fn = _start_one if args.start else _poll_one
    results: list[dict] = []
    with ThreadPoolExecutor(max_workers=max(1, int(args.parallel))) as pool:
        futures = {pool.submit(fn, api_key, row): row["unitSid"] for row in rows}
        for future in as_completed(futures):
            sid = futures[future]
            try:
                result = future.result()
            except Exception as exc:  # record per-unit failures without hiding sibling progress
                result = {"unitSid": sid, "status": "FAILED", "error": f"{type(exc).__name__}: {exc}"}
            results.append(result)
            print(json.dumps(result, sort_keys=True), flush=True)
    summary = {
        "ok": all(row.get("status") not in {"FAILED", "CANCELED"} for row in results),
        "mode": "start" if args.start else "poll",
        "results": sorted(results, key=lambda row: row["unitSid"]),
    }
    (OUT_ROOT / ("queue_results.json" if args.start else "poll_results.json")).write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({"ok": summary["ok"], "mode": summary["mode"], "count": len(results)}, indent=2))
    return 0 if summary["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
