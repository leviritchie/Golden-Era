#!/usr/bin/env python3
"""Cheap texture-anchor review pass for DEF mocap (no full 30-frame IK)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from PIL import Image

ROOT = Path(r"V:/Games/Olden Era Playtest Tweak")
TOOL = ROOT / "tools/homm3_silhouette_pose_fit"
REVIEW_FRAMES_DEFAULT = (0, 4, 8, 12, 16, 20, 24, 28)

if str(TOOL) not in sys.path:
    sys.path.insert(0, str(TOOL))

from articulation_prop_coords import articulation_to_props_coords, run_articulation_discovery  # noqa: E402
from literature_polish_common import assert_write_path, default_bone_roles_path  # noqa: E402
from preview_timing import PREVIEW_GIF_FRAME_MS  # noqa: E402
from texture_anchor_prop_coords import draw_marker_overlay, texture_anchor_props_coords  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--unit", default="h3_roc")
    parser.add_argument("--clip", default="idle_start_move_end")
    parser.add_argument("--out-lane", default="texture_anchor_cheap")
    parser.add_argument("--search-radius", type=int, default=48)
    parser.add_argument(
        "--review-frames",
        default=",".join(str(f) for f in REVIEW_FRAMES_DEFAULT),
        help="Comma-separated frame indices for overlay GIF",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    unit = str(args.unit)
    clip = str(args.clip)
    clip_base = ROOT / "artifacts" / "pose_picker_runs" / unit / clip
    frame_dir = clip_base / f"frames_def12_nn_{clip}_shadow_culled"
    if not frame_dir.is_dir():
        raise FileNotFoundError(frame_dir)
    frame_indices = sorted(
        int(path.stem) for path in frame_dir.glob("*.png") if path.stem.isdigit()
    )
    review_frames = [int(token) for token in str(args.review_frames).split(",") if token.strip()]

    out_root = assert_write_path(clip_base / str(args.out_lane))
    out_root.mkdir(parents=True, exist_ok=True)
    bone_roles_path = default_bone_roles_path(unit)
    roles = json.loads(bone_roles_path.read_text(encoding="utf-8"))
    prop_joints = list(roles.get("propJoints") or roles.get("joints", {}).keys())

    articulation_dir = clip_base / "def_native_mocap_v2" / "articulation"
    report = run_articulation_discovery(frames_dir=frame_dir, out_dir=articulation_dir, k=8)
    from PIL import Image as PILImage

    probe = PILImage.open(next(frame_dir.glob("00.png"), next(frame_dir.glob("*.png"))))
    sprite_size = probe.size

    centroid_coords = articulation_to_props_coords(
        report,
        unit=unit,
        clip=clip,
        prop_joints=prop_joints,
        sprite_size=sprite_size,
        frame_indices=frame_indices,
        bone_roles_path=bone_roles_path,
        frame_dir=frame_dir,
    )
    texture_coords = texture_anchor_props_coords(
        centroid_coords,
        unit=unit,
        clip=clip,
        frame_dir=frame_dir,
        frame_indices=frame_indices,
        prop_joints=prop_joints,
        bone_roles_path=bone_roles_path,
        search_radius=int(args.search_radius),
    )

    (out_root / "props_coords_centroids.json").write_text(
        json.dumps(centroid_coords, indent=2) + "\n", encoding="utf-8"
    )
    (out_root / "props_coords_texture.json").write_text(
        json.dumps(texture_coords, indent=2) + "\n", encoding="utf-8"
    )

    centroid_by_frame = {int(f["frameIndex"]): f["xy"] for f in centroid_coords["frames"]}
    texture_by_frame = {int(f["frameIndex"]): f["xy"] for f in texture_coords["frames"]}

    overlay_dir = out_root / "overlays"
    panels: list[Image.Image] = []
    shifts: list[dict[str, Any]] = []
    for frame_index in review_frames:
        cxy = centroid_by_frame[int(frame_index)]
        txy = texture_by_frame[int(frame_index)]
        frame_shift: dict[str, Any] = {"frameIndex": int(frame_index), "joints": {}}
        for joint in prop_joints:
            dx = float(txy[joint][0]) - float(cxy[joint][0])
            dy = float(txy[joint][1]) - float(cxy[joint][1])
            frame_shift["joints"][joint] = {
                "centroid": cxy[joint],
                "texture": txy[joint],
                "shiftPx": round(float((dx * dx + dy * dy) ** 0.5), 1),
            }
        shifts.append(frame_shift)
        out_png = overlay_dir / f"review_{int(frame_index):02d}.png"
        draw_marker_overlay(
            frame_dir,
            int(frame_index),
            centroid_xy=cxy,
            texture_xy=txy,
            out_path=out_png,
        )
        panels.append(Image.open(out_png).convert("RGB"))

    gif_path = out_root / "centroid_vs_texture_anchor.gif"
    panels[0].save(
        gif_path,
        save_all=True,
        append_images=panels[1:],
        duration=PREVIEW_GIF_FRAME_MS,
        loop=0,
    )

    summary = {
        "ok": True,
        "unit": unit,
        "clip": clip,
        "reviewFrames": review_frames,
        "gif": str(gif_path).replace("\\", "/"),
        "textureCoords": str((out_root / "props_coords_texture.json")).replace("\\", "/"),
        "shifts": shifts,
    }
    (out_root / "texture_anchor_cheap_report.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
