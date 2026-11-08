#!/usr/bin/env python3
"""Textured GIF: sprite | skeleton-only pose | skeleton pose + non-bone offsets.

The mask overlays ``def_nonbone_deform`` writes are for judging coverage, not for
watching motion. This renders the same three states as unlit base-color RGB at
the stick-GIF wall clock so the added surface motion can actually be seen.

Frames where the rig-sufficiency probe found no unreachable area carry no offsets,
so the second and third panels are identical there by construction. That is the
channel being dormant, not a rendering bug.

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

ALPHA_THRESHOLD = 8


def _render_rgb(
    experiment: Any,
    bones: torch.Tensor,
    root_translation: torch.Tensor,
    root_rotation: torch.Tensor,
    *,
    vertex_offsets: torch.Tensor | None,
) -> np.ndarray:
    with torch.no_grad():
        rgb, alpha, _depth = experiment.exact_triangle_rgb(
            experiment._bounded_bone_vectors(bones),
            root_translation,
            root_rotation,
            bone_mask=experiment.active_node_mask,
            vertex_offsets=vertex_offsets,
        )
    composited = rgb * alpha.unsqueeze(-1)
    return (composited.clamp(0.0, 1.0).detach().cpu().numpy() * 255.0).astype(np.uint8)


def _sprite_panel(frame_dir: Path, frame_index: int, size: tuple[int, int]) -> np.ndarray:
    """Sprite resampled onto the raster canvas so all panels share one pixel space.

    Without this the panels are not comparable: sprite plates are ~1023x657 while
    the score raster is 288x258, so fitting each to a common panel height puts the
    bird at a different size in the sprite column than in the mesh columns and no
    fit judgement can be made from the image.
    """
    rgba = np.asarray(
        Image.open(frame_dir / f"{int(frame_index):02d}.png")
        .convert("RGBA")
        .resize(size, Image.Resampling.LANCZOS)
    )
    sprite = rgba[..., :3].copy()
    sprite[rgba[..., 3] < ALPHA_THRESHOLD] = 0
    return sprite


def _content_bbox(stacks: Sequence[np.ndarray], *, margin: int) -> tuple[int, int, int, int]:
    """One crop window covering every panel on every frame, so nothing jitters."""
    occupied = np.zeros(stacks[0].shape[1:3], dtype=bool)
    for stack in stacks:
        occupied |= stack.max(axis=-1).max(axis=0) > 8
    rows = np.nonzero(occupied.any(axis=1))[0]
    columns = np.nonzero(occupied.any(axis=0))[0]
    if rows.size == 0 or columns.size == 0:
        return 0, 0, occupied.shape[1], occupied.shape[0]
    height, width = occupied.shape
    return (
        max(0, int(columns[0]) - margin),
        max(0, int(rows[0]) - margin),
        min(width, int(columns[-1]) + 1 + margin),
        min(height, int(rows[-1]) + 1 + margin),
    )


def _fit_height(image: np.ndarray, height: int) -> Image.Image:
    scale = height / image.shape[0]
    width = max(1, int(round(image.shape[1] * scale)))
    return Image.fromarray(image).resize((width, height), Image.Resampling.NEAREST)


def compose(
    *,
    frame_dir: Path,
    frame_indices: Sequence[int],
    bones_rgb: np.ndarray,
    deform_rgb: np.ndarray,
    captions: dict[int, tuple[str, str]],
    out: Path,
    panel_height: int = 320,
) -> Path:
    raster_size = (int(bones_rgb.shape[2]), int(bones_rgb.shape[1]))
    sprite_stack = np.stack(
        [_sprite_panel(frame_dir, int(index), raster_size) for index in frame_indices]
    )
    left, top, right, bottom = _content_bbox(
        (sprite_stack, bones_rgb, deform_rgb), margin=4
    )

    panels: list[Image.Image] = []
    for position, frame_index in enumerate(frame_indices):
        sprite = _fit_height(sprite_stack[position, top:bottom, left:right], panel_height)
        bones = _fit_height(bones_rgb[position, top:bottom, left:right], panel_height)
        deform = _fit_height(deform_rgb[position, top:bottom, left:right], panel_height)
        row = Image.new(
            "RGB",
            (sprite.width + bones.width + deform.width, panel_height + 20),
            (8, 8, 12),
        )
        row.paste(sprite, (0, 20))
        row.paste(bones, (sprite.width, 20))
        row.paste(deform, (sprite.width + bones.width, 20))
        draw = ImageDraw.Draw(row)
        bone_caption, deform_caption = captions.get(
            int(position), ("skeleton only", "no offsets needed")
        )
        draw.text((4, 5), f"f{int(frame_index):02d} sprite", fill=(235, 235, 235))
        draw.text((sprite.width + 4, 5), bone_caption, fill=(235, 235, 235))
        draw.text(
            (sprite.width + bones.width + 4, 5), deform_caption, fill=(150, 230, 160)
        )
        panels.append(row)
    panels[0].save(
        out, save_all=True, append_images=panels[1:], duration=PREVIEW_GIF_FRAME_MS, loop=0
    )
    return out


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--unit", default="h3_roc")
    parser.add_argument("--clip", default="idle_start_move_end")
    parser.add_argument("--lane", required=True)
    parser.add_argument("--tag", default="")
    parser.add_argument("--out", default="")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    unit = str(args.unit)
    clip = str(args.clip)
    tag = f"_{args.tag}" if str(args.tag) else ""
    lane_root = ROOT / "artifacts" / "pose_picker_runs" / unit / clip / str(args.lane)
    clip_path = lane_root / "solve" / "gpu_clip_result.json"
    offsets_path = lane_root / f"nonbone_deform_offsets{tag}.npz"
    report_path = lane_root / f"{unit}_nonbone_deform_report{tag}.json"
    for path in (clip_path, offsets_path, report_path):
        if not path.is_file():
            raise FileNotFoundError(path)

    payload = json.loads(clip_path.read_text(encoding="utf-8"))
    report = json.loads(report_path.read_text(encoding="utf-8"))
    frames = clip_frame_indices(payload)
    frame_dir = target_frame_dir_from_clip(payload)

    from nvdiffrast_local import ensure_local_nvdiffrast
    from roc_gpu_cascade_experiment import GpuCascadeExperiment

    ensure_local_nvdiffrast(required=True)
    experiment = GpuCascadeExperiment(
        src_glb=unit_mesh(unit, clip).resolve(),
        camera_fit=Path(str(payload["cameraFitPath"])).resolve(),
        target_frame_dir=frame_dir,
        frame_indices=frames,
        config=gpu_config_for_preview(payload["config"]),
    )
    poses = {int(key): value for key, value in payload["poses"].items()}
    bones, root_t, root_r = experiment._initial_pose_tensors(poses)

    vertex_count = sum(
        int(primitive.positions.shape[0]) for primitive in experiment.primitives
    )
    offsets = torch.zeros(
        (len(frames), vertex_count, 3), dtype=torch.float32, device=experiment.device
    )
    stored = np.load(offsets_path)
    applied = 0
    for key in stored.files:
        position = int(str(key).split("_")[-1])
        array = np.asarray(stored[key], dtype=np.float32)
        if array.shape != (vertex_count, 3):
            raise ValueError(
                f"{key} has shape {array.shape}, expected {(vertex_count, 3)} -- "
                "offsets were solved against a different mesh"
            )
        offsets[position] = torch.as_tensor(array, device=experiment.device)
        applied += 1

    captions: dict[int, tuple[str, str]] = {}
    for row in report["frames"]:
        position = int(row["framePosition"])
        if bool(row["kept"]):
            captions[position] = (
                f"skeleton only {float(row['baselineScore']):.3f}",
                f"+ non-bone {float(row['offsetScore']):.3f} "
                f"({float(row['scoreGain']):+.3f})",
            )
        else:
            captions[position] = (
                f"skeleton only {float(row['baselineScore']):.3f}",
                "offsets rejected, none applied",
            )

    bones_rgb = _render_rgb(experiment, bones, root_t, root_r, vertex_offsets=None)
    deform_rgb = _render_rgb(experiment, bones, root_t, root_r, vertex_offsets=offsets)

    out = (
        Path(str(args.out)).resolve()
        if str(args.out)
        else lane_root / f"sprite_vs_skeleton_vs_nonbone{tag}.gif"
    )
    compose(
        frame_dir=frame_dir,
        frame_indices=frames,
        bones_rgb=bones_rgb,
        deform_rgb=deform_rgb,
        captions=captions,
        out=out,
    )
    print(
        json.dumps(
            {
                "ok": True,
                "frames": len(frames),
                "framesWithOffsets": applied,
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
