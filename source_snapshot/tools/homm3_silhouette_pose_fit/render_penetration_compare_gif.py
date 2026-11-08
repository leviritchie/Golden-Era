#!/usr/bin/env python3
"""Textured GIF comparing two solved lanes against the sprite, captioned with penetration.

Built for one specific question: did a change stop the mesh from passing through
itself, and at what cost to the silhouette fit? Reading that off numbers alone is
unsatisfying, because "penetration 0.4" does not communicate "the head is inside
the wing" the way one frame of the animation does.

Each lane is rendered with **its own** camera fit, taken from its own clip payload,
so each column is that lane's actual result rather than one lane's poses shown
through another lane's camera.

Captions carry the head-chain penetration sum from each lane's self-intersection
audit, so the picture and the measurement cannot drift apart.

Proof tier: generated artifact preview. Not OE runtime.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

import numpy as np
import torch
from PIL import Image, ImageDraw

ROOT = Path(r"V:/Games/Olden Era Playtest Tweak")
TOOL = ROOT / "tools/homm3_silhouette_pose_fit"

if str(TOOL) not in sys.path:
    sys.path.insert(0, str(TOOL))

from cascade_clip_pose_tweak import (  # noqa: E402
    clip_frame_indices,
    gpu_config_for_preview,
    target_frame_dir_from_clip,
)
from literature_polish_common import unit_mesh  # noqa: E402
from preview_timing import PREVIEW_GIF_FRAME_MS  # noqa: E402
from render_nonbone_deform_gif import (  # noqa: E402
    _content_bbox,
    _fit_height,
    _render_rgb,
    _sprite_panel,
)


def lane_render(
    *,
    unit: str,
    clip: str,
    lane: str,
) -> tuple[np.ndarray, list[int], Path, dict[str, Any]]:
    """Render one lane's solved clip as unlit base-color RGB."""
    from nvdiffrast_local import ensure_local_nvdiffrast
    from roc_gpu_cascade_experiment import GpuCascadeExperiment

    ensure_local_nvdiffrast(required=True)
    lane_root = ROOT / "artifacts" / "pose_picker_runs" / unit / clip / lane
    clip_path = lane_root / "solve" / "gpu_clip_result.json"
    if not clip_path.is_file():
        raise FileNotFoundError(clip_path)
    payload = json.loads(clip_path.read_text(encoding="utf-8"))
    frames = clip_frame_indices(payload)
    experiment = GpuCascadeExperiment(
        src_glb=unit_mesh(unit, clip).resolve(),
        camera_fit=Path(str(payload["cameraFitPath"])).resolve(),
        target_frame_dir=target_frame_dir_from_clip(payload),
        frame_indices=frames,
        config=gpu_config_for_preview(payload["config"]),
    )
    poses = {int(key): value for key, value in payload["poses"].items()}
    bones, root_t, root_r = experiment._initial_pose_tensors(poses)
    rgb = _render_rgb(experiment, bones, root_t, root_r, vertex_offsets=None)
    return rgb, frames, target_frame_dir_from_clip(payload), payload


def audit_rows(unit: str, clip: str, lane: str) -> dict[int, dict[str, Any]]:
    path = (
        ROOT
        / "artifacts/pose_picker_runs"
        / unit
        / clip
        / lane
        / f"{unit}_self_intersection_audit.json"
    )
    if not path.is_file():
        raise FileNotFoundError(
            f"{path} is missing; run def_self_intersection_audit for this lane so the "
            "captions report measured penetration instead of nothing"
        )
    report = json.loads(path.read_text(encoding="utf-8"))
    return {int(row["framePosition"]): row for row in report["frames"]}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--unit", default="h3_roc")
    parser.add_argument("--clip", default="idle_start_move_end")
    parser.add_argument("--lane-before", required=True)
    parser.add_argument("--lane-after", required=True)
    parser.add_argument("--label-before", default="before")
    parser.add_argument("--label-after", default="after")
    parser.add_argument("--out", required=True)
    parser.add_argument("--panel-height", type=int, default=320)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    unit = str(args.unit)
    clip = str(args.clip)

    before_rgb, frames, frame_dir, _payload = lane_render(
        unit=unit, clip=clip, lane=str(args.lane_before)
    )
    after_rgb, after_frames, _after_dir, _after_payload = lane_render(
        unit=unit, clip=clip, lane=str(args.lane_after)
    )
    if list(after_frames) != list(frames):
        raise ValueError(
            "the two lanes solved different frame sets; a side-by-side would compare "
            f"different frames: {frames} vs {after_frames}"
        )

    before_audit = audit_rows(unit, clip, str(args.lane_before))
    after_audit = audit_rows(unit, clip, str(args.lane_after))

    raster_size = (int(before_rgb.shape[2]), int(before_rgb.shape[1]))
    sprite_stack = np.stack(
        [_sprite_panel(frame_dir, int(index), raster_size) for index in frames]
    )
    left, top, right, bottom = _content_bbox(
        (sprite_stack, before_rgb, after_rgb), margin=4
    )

    panel_height = int(args.panel_height)
    panels: list[Image.Image] = []
    for position, frame_index in enumerate(frames):
        sprite = _fit_height(sprite_stack[position, top:bottom, left:right], panel_height)
        before = _fit_height(before_rgb[position, top:bottom, left:right], panel_height)
        after = _fit_height(after_rgb[position, top:bottom, left:right], panel_height)
        row = Image.new(
            "RGB", (sprite.width + before.width + after.width, panel_height + 20), (8, 8, 12)
        )
        row.paste(sprite, (0, 20))
        row.paste(before, (sprite.width, 20))
        row.paste(after, (sprite.width + before.width, 20))

        before_head = float(before_audit[position]["headChainPenetrationSum"])
        after_head = float(after_audit[position]["headChainPenetrationSum"])
        draw = ImageDraw.Draw(row)
        draw.text((4, 5), f"f{int(frame_index):02d} sprite", fill=(235, 235, 235))
        draw.text(
            (sprite.width + 4, 5),
            f"{args.label_before}  head {before_head:.2f}",
            fill=(255, 150, 150) if before_head > 0.0 else (235, 235, 235),
        )
        draw.text(
            (sprite.width + before.width + 4, 5),
            f"{args.label_after}  head {after_head:.2f}",
            fill=(255, 150, 150) if after_head > 0.0 else (150, 230, 160),
        )
        panels.append(row)

    out = Path(str(args.out))
    out.parent.mkdir(parents=True, exist_ok=True)
    panels[0].save(
        out, save_all=True, append_images=panels[1:], duration=PREVIEW_GIF_FRAME_MS, loop=0
    )
    print(
        json.dumps(
            {
                "ok": True,
                "frames": len(frames),
                "framesWithHeadPenetrationBefore": sum(
                    1
                    for row in before_audit.values()
                    if float(row["headChainPenetrationSum"]) > 0.0
                ),
                "framesWithHeadPenetrationAfter": sum(
                    1
                    for row in after_audit.values()
                    if float(row["headChainPenetrationSum"]) > 0.0
                ),
                "gif": str(out).replace("\\", "/"),
                "frameMs": PREVIEW_GIF_FRAME_MS,
            },
            indent=2,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
