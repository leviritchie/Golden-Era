#!/usr/bin/env python3
"""Compare legacy vs animation-repaired mesh on existing fused-push poses.

Rasters the same gpu_clip_result keyframes on two GLBs, then writes a 3-panel GIF:
  sprite | legacy mesh | animation-repaired mesh

Example:
  python tools/homm3_silhouette_pose_fit/compare_mesh_repair_gifs.py \\
    --lab-sid h3_archer --clips idle_start_move_end,idle_attack_front,idle_hitted
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
TOOL = Path(__file__).resolve().parent
MESHY = ROOT / "artifacts/meshy_downloads"
POSE_RUNS = ROOT / "artifacts/pose_picker_runs"
DEFAULT_OUT = MESHY / "mesh_repair_compare"
GPU_RUN = "fused_push_v24_pipeline"

if str(TOOL) not in sys.path:
    sys.path.insert(0, str(TOOL))

from cascade_clip_pose_tweak import load_clip_result, raster_tweak_preview  # noqa: E402
from compose_method_compare_gif import main as compose_gif_main  # noqa: E402
from preview_timing import PREVIEW_GIF_FRAME_MS  # noqa: E402
from tweak_gpu_clip_poses import _with_cascade_lock  # noqa: E402


def _parse() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--lab-sid", required=True)
    ap.add_argument(
        "--clips",
        default="idle_start_move_end,idle_attack_front,idle_hitted",
        help="Comma-separated animation names",
    )
    ap.add_argument(
        "--legacy-mesh",
        type=Path,
        default=None,
        help="Default: artifacts/meshy_downloads/<sid>_smartrigged_rigidized.glb",
    )
    ap.add_argument(
        "--repair-mesh",
        type=Path,
        default=None,
        help="Default: artifacts/meshy_downloads/<sid>_smartrigged_anim_bridgefix.glb",
    )
    ap.add_argument("--out-root", type=Path, default=DEFAULT_OUT)
    return ap.parse_args()


def _sprite_dir(lab_sid: str, animation: str) -> Path:
    return POSE_RUNS / lab_sid / animation / f"frames_def12_nn_{animation}_shadow_culled"


def _clip_result_path(lab_sid: str, animation: str) -> Path:
    return POSE_RUNS / lab_sid / animation / GPU_RUN / "gpu_clip_result.json"


def _compose_compare_gif(
    *,
    out_path: Path,
    sprite_dir: Path,
    legacy_rgb: Path,
    repair_rgb: Path,
    frame_count: int,
) -> Path:
    argv = [
        "--out",
        str(out_path),
        "--cols",
        "3",
        "--cell-w",
        "280",
        "--cell-h",
        "320",
        "--hold",
        "2",
        "--duration-ms",
        str(int(PREVIEW_GIF_FRAME_MS)),
        "--frame-count",
        str(int(frame_count)),
        "--panel",
        "sprite",
        str(sprite_dir),
        "--panel",
        "legacy_rigidized",
        str(legacy_rgb),
        "--panel",
        "anim_bridgefix",
        str(repair_rgb),
    ]
    old = sys.argv
    try:
        sys.argv = ["compose_method_compare_gif.py", *argv]
        code = compose_gif_main()
    finally:
        sys.argv = old
    if int(code) != 0:
        raise RuntimeError(f"GIF compose failed for {out_path}")
    return out_path


def _raster_lane(*, payload: dict[str, Any], mesh: Path, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    report = _with_cascade_lock(
        lambda: raster_tweak_preview(
            payload=payload,
            mesh_glb=mesh,
            output_dir=out_dir,
        )
    )
    rgb_dir = Path(str(report["rgbDir"]))
    if not rgb_dir.is_dir():
        raise RuntimeError(f"raster missing rgbDir: {rgb_dir}")
    return rgb_dir


def compare_clip(
    *,
    lab_sid: str,
    animation: str,
    legacy_mesh: Path,
    repair_mesh: Path,
    out_root: Path,
) -> dict[str, Any]:
    clip_path = _clip_result_path(lab_sid, animation)
    if not clip_path.is_file():
        raise FileNotFoundError(f"missing clip result: {clip_path}")
    sprite_dir = _sprite_dir(lab_sid, animation)
    if not sprite_dir.is_dir():
        raise FileNotFoundError(f"missing sprite lane: {sprite_dir}")
    payload = load_clip_result(clip_path)
    frame_count = len(payload.get("frameIndices") or [])
    if frame_count < 1:
        raise ValueError(f"{clip_path} has no frameIndices")

    clip_out = out_root / lab_sid / animation
    legacy_dir = clip_out / "legacy_raster"
    repair_dir = clip_out / "anim_bridgefix_raster"
    legacy_rgb = _raster_lane(payload=payload, mesh=legacy_mesh, out_dir=legacy_dir)
    repair_rgb = _raster_lane(payload=payload, mesh=repair_mesh, out_dir=repair_dir)
    gif_path = clip_out / "mesh_repair_compare.gif"
    _compose_compare_gif(
        out_path=gif_path,
        sprite_dir=sprite_dir,
        legacy_rgb=legacy_rgb,
        repair_rgb=repair_rgb,
        frame_count=frame_count,
    )
    return {
        "labSid": lab_sid,
        "animation": animation,
        "clipResult": str(clip_path).replace("\\", "/"),
        "legacyMesh": str(legacy_mesh).replace("\\", "/"),
        "repairMesh": str(repair_mesh).replace("\\", "/"),
        "frameCount": frame_count,
        "clipScore": payload.get("score"),
        "compareGif": str(gif_path).replace("\\", "/"),
        "panels": ["sprite", "legacy_rigidized", "anim_bridgefix"],
    }


def main() -> int:
    args = _parse()
    sid = str(args.lab_sid).strip()
    legacy = args.legacy_mesh or (MESHY / f"{sid}_smartrigged_rigidized.glb")
    repair = args.repair_mesh or (MESHY / f"{sid}_smartrigged_anim_bridgefix.glb")
    if not legacy.is_file():
        raise FileNotFoundError(f"legacy mesh missing: {legacy}")
    if not repair.is_file():
        raise FileNotFoundError(f"repair mesh missing: {repair}")
    out_root = args.out_root if args.out_root.is_absolute() else (ROOT / args.out_root)
    clips = [part.strip() for part in str(args.clips).split(",") if part.strip()]
    rows: list[dict[str, Any]] = []
    for animation in clips:
        print(f"[mesh-repair-compare] {sid} {animation}...", flush=True)
        rows.append(
            compare_clip(
                lab_sid=sid,
                animation=animation,
                legacy_mesh=legacy.resolve(),
                repair_mesh=repair.resolve(),
                out_root=out_root.resolve(),
            )
        )
    summary = {
        "ok": True,
        "labSid": sid,
        "legacyMesh": str(legacy).replace("\\", "/"),
        "repairMesh": str(repair).replace("\\", "/"),
        "clips": rows,
        "proof": "generated artifact validated — same poses, two meshes; not OE runtime proven",
    }
    summary_path = out_root / sid / "mesh_repair_compare_index.json"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
