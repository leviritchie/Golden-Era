#!/usr/bin/env python3
"""Meshy adventure-map artifact meshes from AVA map frames.

Policy (same as buildings):
  - Topology: meshy-t2 smart-topology, should_texture=false
  - Materials: meshy-6 retexture at 4k, enable_pbr=true, remove_lighting=false
  - Default polycount 500 (near vanilla OE artifact density)
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOL = Path(__file__).resolve().parent
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

DEFAULT_INVENTORY = ROOT / "artifacts" / "meshy_artifacts" / "inventory.json"
DEFAULT_OUT = ROOT / "artifacts" / "meshy_artifacts"
# AVA map frames are ~22–38px; Meshy rejects many under ~34px. Nearest-neighbor upscale for upload only.
MESHY_MIN_SIDE = 256


def prepare_meshy_input(src_png: Path, dest_png: Path, *, min_side: int = MESHY_MIN_SIDE) -> dict:
    """Copy or nearest-upscale sprite so Meshy accepts dimensions. Preserves alpha."""
    from PIL import Image

    im = Image.open(src_png)
    w, h = im.size
    max_side = max(w, h)
    scale = 1
    if max_side < min_side:
        scale = (min_side + max_side - 1) // max_side
        im = im.resize((w * scale, h * scale), Image.Resampling.NEAREST)
    dest_png.parent.mkdir(parents=True, exist_ok=True)
    im.save(dest_png)
    return {
        "sourceSize": [w, h],
        "uploadSize": [im.size[0], im.size[1]],
        "nearestScale": int(scale),
        "path": str(dest_png).replace("\\", "/"),
    }


def glb_url_from_task(task: dict) -> str | None:
    urls = task.get("model_urls") or {}
    if isinstance(urls, dict) and urls.get("glb"):
        return str(urls["glb"])
    result = task.get("result")
    if isinstance(result, dict):
        nested = result.get("model_urls") or {}
        if isinstance(nested, dict) and nested.get("glb"):
            return str(nested["glb"])
    return None


def download_textures(task: dict, dest_dir: Path) -> dict:
    out: dict = {}
    texture_urls = task.get("texture_urls") or []
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


def process_one(
    api_key: str,
    entry: dict,
    out_root: Path,
    *,
    polycount: int,
    texture_resolution: str,
    skip_existing: bool,
) -> dict:
    rel = entry["mapObjectRel"]
    dest = out_root / "meshes" / entry["dir"]
    dest.mkdir(parents=True, exist_ok=True)
    tasks_dir = dest / "tasks"
    tasks_dir.mkdir(parents=True, exist_ok=True)
    src_png = Path(entry["absolutePng"])
    if not src_png.is_file():
        raise FileNotFoundError(f"missing source PNG: {src_png}")
    copied = dest / "source_00_00.png"
    shutil.copy2(src_png, copied)
    meshy_input = dest / "meshy_input.png"
    upload_meta = prepare_meshy_input(src_png, meshy_input)

    glb = dest / "model.glb"
    mesh_t2 = dest / "model_t2_untextured.glb"
    meta: dict = {
        "relativePng": entry["relativePng"],
        "prefabKey": entry["prefabKey"],
        "kind": entry["kind"],
        "targetHeight": entry["targetHeight"],
        "animatedSource": bool(entry.get("animated")),
        "firstFrameOnly": bool(entry.get("firstFrameOnly")),
        "frameCount": entry.get("frameCount"),
        "meshyInput": upload_meta,
        "policy": {
            "meshAiModel": "meshy-t2",
            "meshShouldTexture": False,
            "retextureAiModel": "meshy-6",
            "textureResolution": str(texture_resolution),
            "removeLighting": False,
            "enablePbr": True,
            "meshyMinSide": MESHY_MIN_SIDE,
        },
    }

    if skip_existing and glb.is_file() and glb.stat().st_size > 1000:
        meta.update(
            {
                "skipped": True,
                "glb": str(glb).replace("\\", "/"),
                "bytes": glb.stat().st_size,
            }
        )
        (dest / "generate_meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
        return meta

    print(
        f"[gen] t2 topology {rel} upload={upload_meta['uploadSize']} "
        f"(src={upload_meta['sourceSize']} x{upload_meta['nearestScale']})",
        flush=True,
    )
    # remove_lighting is rejected for smart-topology / meshy-t2 — omit on mesh create.
    tid = create_image_to_3d(
        api_key,
        image_path=meshy_input,
        should_texture=False,
        target_polycount=polycount,
        model_type="smart-topology",
        ai_model="meshy-t2",
        pose_mode=None,
        should_remesh=True,
        enable_pbr=False,
        remove_lighting=None,
    )
    meta["imageTaskId"] = tid
    (tasks_dir / "image_to_3d.json").write_text(
        json.dumps({"taskId": tid, "relativePng": entry["relativePng"]}, indent=2) + "\n",
        encoding="utf-8",
    )
    task = poll_task(api_key, "image-to-3d", tid, timeout_s=2400, interval_s=8.0)
    (tasks_dir / "image_to_3d.json").write_text(json.dumps(task, indent=2) + "\n", encoding="utf-8")
    status = str(task.get("status") or "")
    meta["imageStatus"] = status
    meta["imageCredits"] = task.get("consumed_credits") or task.get("credits")
    if status != "SUCCEEDED":
        meta["error"] = task_error_message(task)
        (dest / "generate_meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
        return meta

    url = glb_url_from_task(task)
    if not url:
        meta["error"] = f"missing t2 glb url; keys={list(task.keys())}"
        (dest / "generate_meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
        return meta
    download_url(url, mesh_t2)
    meta["t2Glb"] = str(mesh_t2).replace("\\", "/")
    meta["t2Bytes"] = mesh_t2.stat().st_size
    print(f"[gen] t2 saved {rel} ({meta['t2Bytes']} bytes)", flush=True)

    print(f"[gen] meshy-6 retexture {rel} res={texture_resolution}", flush=True)
    rtid = create_retexture(
        api_key,
        input_task_id=tid,
        image_style_path=meshy_input,
        ai_model="meshy-6",
        enable_original_uv=True,
        enable_pbr=True,
        remove_lighting=False,
        texture_resolution=str(texture_resolution),
    )
    meta["retextureTaskId"] = rtid
    (tasks_dir / "retexture.json").write_text(
        json.dumps({"taskId": rtid, "relativePng": entry["relativePng"]}, indent=2) + "\n",
        encoding="utf-8",
    )
    rtask = poll_task(api_key, "retexture", rtid, timeout_s=3600, interval_s=10.0)
    (tasks_dir / "retexture.json").write_text(json.dumps(rtask, indent=2) + "\n", encoding="utf-8")
    rstatus = str(rtask.get("status") or "")
    meta["retextureStatus"] = rstatus
    meta["retextureCredits"] = rtask.get("consumed_credits") or rtask.get("credits")
    if rstatus != "SUCCEEDED":
        meta["error"] = task_error_message(rtask)
        (dest / "generate_meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
        return meta

    rurl = glb_url_from_task(rtask)
    if not rurl:
        meta["error"] = f"missing retexture glb url; keys={list(rtask.keys())}"
        (dest / "generate_meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
        return meta
    download_url(rurl, glb)
    meta["glb"] = str(glb).replace("\\", "/")
    meta["bytes"] = glb.stat().st_size
    meta["textures"] = download_textures(rtask, dest)
    if not meta["textures"].get("base_color"):
        meta["error"] = (
            "retexture SUCCEEDED but no base_color texture_urls; refuse to treat as complete"
        )
        (dest / "generate_meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
        return meta

    (dest / "generate_meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    print(f"[gen] saved {rel} ({meta['bytes']} bytes, textures={len(meta['textures'])})", flush=True)
    return meta


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--polycount", type=int, default=500)
    ap.add_argument("--texture-resolution", default="4k", choices=("2k", "4k", "8k"))
    ap.add_argument("--parallel", type=int, default=3)
    ap.add_argument("--skip-existing", action="store_true")
    ap.add_argument(
        "--first-frame-only",
        action="store_true",
        help="Only process inventory rows marked firstFrameOnly (animated sources).",
    )
    ap.add_argument("--missing-only", action="store_true", help="Skip rows that already have model.glb.")
    ap.add_argument("--limit", type=int, default=0, help="optional cap for smoke runs")
    ap.add_argument("--continue-on-error", action="store_true")
    args = ap.parse_args()

    inv_path: Path = args.inventory if args.inventory.is_absolute() else ROOT / args.inventory
    out_root: Path = args.out if args.out.is_absolute() else ROOT / args.out
    if not inv_path.is_file():
        print(f"missing inventory: {inv_path}", file=sys.stderr)
        return 1
    inv = json.loads(inv_path.read_text(encoding="utf-8"))
    entries = [e for e in inv.get("entries") or [] if e.get("generate")]
    if args.first_frame_only:
        entries = [e for e in entries if e.get("firstFrameOnly")]
    if args.missing_only:
        kept: list[dict] = []
        for e in entries:
            glb = out_root / "meshes" / e["dir"] / "model.glb"
            if not (glb.is_file() and glb.stat().st_size > 1000):
                kept.append(e)
        entries = kept
    if args.limit and args.limit > 0:
        entries = entries[: int(args.limit)]

    if not entries:
        print(json.dumps({"ok": True, "okCount": 0, "expected": 0, "note": "no entries to process"}, indent=2))
        return 0

    api_key = load_api_key()
    out_root.mkdir(parents=True, exist_ok=True)
    report = {
        "policy": {
            "meshAiModel": "meshy-t2",
            "meshShouldTexture": False,
            "retextureAiModel": "meshy-6",
            "textureResolution": str(args.texture_resolution),
            "removeLighting": False,
            "enablePbr": True,
            "targetPolycount": int(args.polycount),
        },
        "inventory": str(inv_path).replace("\\", "/"),
        "filters": {
            "firstFrameOnly": bool(args.first_frame_only),
            "missingOnly": bool(args.missing_only),
            "skipExisting": bool(args.skip_existing),
        },
        "proof": (
            "generated artifact validated — t2 topology + meshy-6 4k retexture "
            "for adventure-map artifact AVA frames"
        ),
        "results": [],
    }

    results: list[dict] = []
    errors: list[str] = []

    def work(entry: dict) -> dict:
        return process_one(
            api_key,
            entry,
            out_root,
            polycount=int(args.polycount),
            texture_resolution=str(args.texture_resolution),
            skip_existing=bool(args.skip_existing),
        )

    with ThreadPoolExecutor(max_workers=max(1, int(args.parallel))) as pool:
        futs = {pool.submit(work, e): e for e in entries}
        for fut in as_completed(futs):
            entry = futs[fut]
            try:
                meta = fut.result()
                results.append(meta)
                if not meta.get("glb") and not meta.get("skipped"):
                    errors.append(f"{entry['relativePng']}: {meta.get('error') or meta.get('status')}")
            except Exception as ex:  # noqa: BLE001 — report per-asset; fail closed below
                err = f"{entry['relativePng']}: {ex}"
                errors.append(err)
                results.append({"relativePng": entry["relativePng"], "error": str(ex)})
                if not args.continue_on_error:
                    for other in futs:
                        other.cancel()
                    break

    report["results"] = sorted(results, key=lambda r: str(r.get("relativePng") or r.get("glb") or ""))
    ok = sum(1 for r in results if r.get("glb") or r.get("skipped"))
    report["okCount"] = ok
    report["expected"] = len(entries)
    report["errors"] = errors
    (out_root / "generate_report.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "ok": ok == len(entries) and not errors,
                "okCount": ok,
                "expected": len(entries),
                "errors": len(errors),
            },
            indent=2,
        )
    )
    return 0 if ok == len(entries) and not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
