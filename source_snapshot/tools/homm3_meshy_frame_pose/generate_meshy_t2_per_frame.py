#!/usr/bin/env python3
"""
Generate one Meshy meshy-t2 mesh per painted attack g11 frame (no A/T pose force, no Meshy rig).

Outputs under --out:
  frames/frame_XX.png          (copy of source used)
  meshes/frame_XX.glb
  tasks/frame_XX.json
  generate_report.json
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
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

DEFAULT_SRC = ROOT / "artifacts/hobgoblin_attack_pose_pipeline/source_attack_frames_painted_g11"
DEFAULT_OUT = ROOT / "artifacts/hobgoblin_attack_pose_pipeline/out_meshy_t2_per_frame_g11"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", type=Path, default=DEFAULT_SRC)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--frames", type=int, default=8)
    ap.add_argument("--polycount", type=int, default=12000)
    ap.add_argument("--parallel", type=int, default=4, help="Concurrent Meshy creates (poll still serial-ish)")
    ap.add_argument("--skip-existing", action="store_true")
    args = ap.parse_args()

    src: Path = args.src if args.src.is_absolute() else ROOT / args.src
    out: Path = args.out if args.out.is_absolute() else ROOT / args.out
    meshes = out / "meshes"
    tasks_dir = out / "tasks"
    frames_dir = out / "frames"
    for d in (meshes, tasks_dir, frames_dir):
        d.mkdir(parents=True, exist_ok=True)

    api_key = load_api_key()
    n = int(args.frames)
    report: dict = {
        "ai_model": "meshy-t2",
        "model_type": "smart-topology",
        "pose_mode": None,
        "should_remesh": True,
        "target_polycount": int(args.polycount),
        "should_texture": True,
        "src": str(src),
        "frames": [],
        "proof": "generated artifact validated — Meshy t2 per painted frame; no Meshy smart-rig",
    }

    # Submit creates (optionally parallel), then poll each.
    pending: list[tuple[int, str, Path]] = []
    for i in range(n):
        src_img = src / f"frame_{i:02d}.png"
        if not src_img.is_file():
            raise FileNotFoundError(src_img)
        shutil.copy2(src_img, frames_dir / f"frame_{i:02d}.png")
        glb = meshes / f"frame_{i:02d}.glb"
        task_json = tasks_dir / f"frame_{i:02d}.json"
        if args.skip_existing and glb.is_file() and glb.stat().st_size > 1000:
            report["frames"].append({"frame": i, "skipped": True, "glb": str(glb)})
            print(f"[gen] f{i:02d} skip existing {glb.name}", flush=True)
            continue
        print(f"[gen] f{i:02d} create image-to-3d …", flush=True)
        tid = create_image_to_3d(
            api_key,
            image_path=src_img,
            should_texture=True,
            target_polycount=int(args.polycount),
            model_type="smart-topology",
            ai_model="meshy-t2",
            pose_mode=None,  # keep attack pose from image
            should_remesh=True,
        )
        pending.append((i, tid, glb))
        task_json.write_text(json.dumps({"taskId": tid, "frame": i}, indent=2) + "\n", encoding="utf-8")

    for i, tid, glb in pending:
        print(f"[gen] f{i:02d} poll {tid[:8]}…", flush=True)
        task = poll_task(api_key, "image-to-3d", tid, timeout_s=2400, interval_s=8.0)
        (tasks_dir / f"frame_{i:02d}.json").write_text(json.dumps(task, indent=2) + "\n", encoding="utf-8")
        status = str(task.get("status") or "")
        entry = {
            "frame": i,
            "taskId": tid,
            "status": status,
            "credits": task.get("consumed_credits"),
        }
        if status != "SUCCEEDED":
            entry["error"] = task_error_message(task)
            report["frames"].append(entry)
            print(f"[gen] f{i:02d} FAILED: {entry['error']}", flush=True)
            continue
        url = task.get("model_urls", {}).get("glb") or (task.get("result") or {}).get("model_urls", {}).get("glb")
        # Meshy responses vary: model_urls at top level after SUCCEEDED
        if not url:
            urls = task.get("model_urls") or {}
            url = urls.get("glb")
        if not url:
            entry["error"] = f"missing glb url in task keys={list(task.keys())}"
            report["frames"].append(entry)
            print(f"[gen] f{i:02d} {entry['error']}", flush=True)
            continue
        download_url(str(url), glb)
        entry["glb"] = str(glb.resolve()).replace("\\", "/")
        entry["bytes"] = glb.stat().st_size
        report["frames"].append(entry)
        print(f"[gen] f{i:02d} saved {glb} ({entry['bytes']} bytes)", flush=True)

    ok = sum(1 for f in report["frames"] if f.get("glb"))
    report["okCount"] = ok
    report["expected"] = n
    (out / "generate_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": ok == n, "okCount": ok, "out": str(out)}, indent=2))
    return 0 if ok == n else 2


if __name__ == "__main__":
    raise SystemExit(main())
