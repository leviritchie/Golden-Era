#!/usr/bin/env python3
"""Measure whether a solved clip wraps cleanly from its last frame back to its first.

A sequential tracker solves frame N from frame N-1 and never revisits the seam, so
nothing in the fit constrains the last frame to agree with the first. For a cycle
clip that is exactly the join the player sees on every repeat: if the pose jumps
there, the animation visibly pops once per loop while every interior frame looks
smooth.

HoMM3 DEF idle sections make this checkable rather than subjective, because they
repeat plates exactly. When the first and last plates are pixel-identical the seam
pose change *should* be near zero, and any large value is a defect rather than
genuine motion.

Use on any lane, before and after a change, to show the seam moved in the right
direction. Reports the same fields the tracker embeds in its own summary, so a lane
solved by an older build can still be compared.

Proof tier: generated artifact measurement.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(r"V:/Games/Olden Era Playtest Tweak")
TOOL = ROOT / "tools/homm3_silhouette_pose_fit"

if str(TOOL) not in sys.path:
    sys.path.insert(0, str(TOOL))

from cascade_clip_pose_tweak import (  # noqa: E402
    _gpu_config_from_saved,
    clip_frame_indices,
    target_frame_dir_from_clip,
)
from def_plate_identity import loop_seam_report  # noqa: E402
from literature_polish_common import unit_mesh  # noqa: E402


def load_plates(frame_dir: Path, frame_indices: list[int]) -> tuple[list, list]:
    """Full-resolution DEF plates in 0..255, the convention plate_distance requires."""
    rgbs = []
    alphas = []
    for index in frame_indices:
        path = frame_dir / f"{int(index):02d}.png"
        if not path.is_file():
            raise FileNotFoundError(path)
        rgba = np.asarray(Image.open(path).convert("RGBA"))
        rgbs.append(np.ascontiguousarray(rgba[..., :3]))
        alphas.append(np.ascontiguousarray(rgba[..., 3]))
    return rgbs, alphas


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--unit", default="h3_roc")
    parser.add_argument("--clip", default="idle_start_move_end")
    parser.add_argument("--lane", required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    unit = str(args.unit)
    clip = str(args.clip)
    lane_root = ROOT / "artifacts" / "pose_picker_runs" / unit / clip / str(args.lane)
    clip_path = lane_root / "solve" / "gpu_clip_result.json"
    if not clip_path.is_file():
        raise FileNotFoundError(clip_path)

    from nvdiffrast_local import ensure_local_nvdiffrast
    from roc_gpu_cascade_experiment import GpuCascadeExperiment

    ensure_local_nvdiffrast(required=True)
    payload = json.loads(clip_path.read_text(encoding="utf-8"))
    frames = clip_frame_indices(payload)
    frame_dir = target_frame_dir_from_clip(payload)
    experiment = GpuCascadeExperiment(
        src_glb=unit_mesh(unit, clip).resolve(),
        camera_fit=Path(str(payload["cameraFitPath"])).resolve(),
        target_frame_dir=frame_dir,
        frame_indices=frames,
        config=_gpu_config_from_saved(payload["config"], overrides={"return_masks": False}),
    )
    poses = {int(key): value for key, value in payload["poses"].items()}
    bones, root_t, root_r = experiment._initial_pose_tensors(poses)

    rgbs, alphas = load_plates(frame_dir, frames)
    report = loop_seam_report(
        rgbs=rgbs,
        alphas=alphas,
        bones=bones.detach().cpu(),
        root_translation=root_t.detach().cpu(),
        root_rotation=root_r.detach().cpu(),
    )
    report.update(
        {
            "proof": "generated-artifact",
            "unit": unit,
            "clip": clip,
            "lane": str(args.lane),
            "frames": len(frames),
        }
    )
    out = lane_root / f"{unit}_loop_seam_audit.json"
    out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    verdict = (
        "plates differ at the seam; a pose change there may be genuine motion"
        if not bool(report["plateIdentical"])
        else (
            "seam closes"
            if float(report["seamPopRatio"] or 0.0) <= 1.0
            else "SEAM POPS: identical plates but the pose jumps more than an interior frame"
        )
    )
    print(json.dumps({**report, "verdict": verdict}, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
