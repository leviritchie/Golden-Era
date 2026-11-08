"""Render a Meshy candidate bind against a route's saved DEF plates.

Unlike the exact-reference preview for an unchanged bind, this diagnostic intentionally allows
the candidate surface to have a different vertex count from the registration mesh.  The saved
registration supplies the authored plates and camera; the bind report supplies the candidate's
own capture-to-mesh similarity.  This is generated-artifact evidence only.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from owned_rerig.glb_io import load_render_surface  # noqa: E402
from owned_rerig.pose_source import load_registered_pose_source  # noqa: E402
from preview_exact_reference_bind import (  # noqa: E402
    _dilate,
    draw_caption,
    evidence_caption,
    fit_camera,
    load_bind_evidence,
    load_delivered_skeleton,
    render_view,
    replay_deformed_vertices,
)

GUTTER = 6
PANEL_MARGIN = 0.06


def apply_similarity(points: np.ndarray, similarity: dict[str, Any]) -> np.ndarray:
    values = np.asarray(points, dtype=np.float64)
    rotation = np.asarray(similarity["rotation"], dtype=np.float64)
    scale = float(similarity["scale"])
    translation = np.asarray(similarity["translation"], dtype=np.float64)
    if rotation.shape != (3, 3) or translation.shape != (3,) or not np.isfinite(scale) or scale <= 0.0:
        raise ValueError("bind-report similarity is malformed")
    if not np.isfinite(values).all() or not np.isfinite(rotation).all() or not np.isfinite(translation).all():
        raise ValueError("bind-report similarity is nonfinite")
    return (scale * (values.reshape(-1, 3) @ rotation.T) + translation).reshape(values.shape)


def write_gif(path: Path, frames: list[Image.Image], frame_ms: float) -> None:
    if not frames:
        raise ValueError("cannot write an empty replay")
    durations = [
        (int(round((index + 1) * frame_ms / 10.0)) - int(round(index * frame_ms / 10.0))) * 10
        for index in range(len(frames))
    ]
    frames[0].save(path, save_all=True, append_images=frames[1:], duration=durations, loop=0, optimize=False)


def run(
    *,
    run_dir: Path,
    registration: Path,
    bind: Path,
    bind_report: Path,
    output: Path,
    clip: str,
    max_frames: int | None,
    panel_height: int,
    camera_yaw_offset_deg: float = 0.0,
) -> dict[str, Any]:
    if output.exists():
        raise FileExistsError(f"choose a fresh output directory: {output}")
    if int(panel_height) < 256:
        raise ValueError("panel_height must be at least 256")
    report = json.loads(bind_report.read_text(encoding="utf-8"))
    pose = load_registered_pose_source(
        capture=run_dir / "linked_master/capture/capture/raw_capture.npz",
        registration=registration,
        master_sequence=run_dir / "linked_master/master_sequence/master_sequence.json",
        segment_index=None,
        clip_key=clip,
        max_frames=max_frames,
        source_view_yaw_offset_deg=float(camera_yaw_offset_deg),
    )
    delivered = load_delivered_skeleton(bind)
    surface = load_render_surface(bind)
    if len(surface["positions"]) != len(delivered["positions"]):
        raise ValueError("candidate bind render and skin vertex counts disagree")
    if np.abs(surface["positions"] - delivered["positions"]).max() > 1e-6:
        raise ValueError("candidate bind render and skin POSITION data disagree")
    for key in ("uvs", "normals", "baseColor"):
        if surface.get(key) is None:
            raise ValueError(f"candidate bind has no {key}; refusing an unfaithful shaded replay")
    evidence = load_bind_evidence(
        bind_report,
        bind_glb=bind,
        capture=run_dir / "linked_master/capture/capture/raw_capture.npz",
        registration=registration,
        mesh=Path(str(report["mesh"])),
        vertex_count=len(delivered["positions"]),
        bind_frame=pose.bind_index(),
        frame_count=pose.frame_count,
        fitted_scale=float(report["scaleFit"]["fittedScale"]),
    )
    frame_joints = apply_similarity(pose.capture_positions[pose.capture_indices], report["similarity"])
    rest_joints = apply_similarity(pose.capture_positions[pose.bind_index()], report["similarity"])
    rest_joint_error = float(np.abs(delivered["heads"] - rest_joints).max())
    if rest_joint_error > 1e-4:
        raise ValueError(
            f"candidate bind rest skeleton disagrees with its report (worst {rest_joint_error:.5f})"
        )
    rest_vertices = replay_deformed_vertices(
        positions=surface["positions"],
        heads=delivered["heads"],
        parents=delivered["parents"],
        joints=delivered["joints"],
        weights=delivered["weights"],
        frame_joints=rest_joints,
    )
    rest_vertex_error = float(np.abs(rest_vertices - surface["positions"]).max())
    if rest_vertex_error > 1e-4:
        raise ValueError(
            f"candidate bind rest vertices do not reproduce their authored positions "
            f"(worst {rest_vertex_error:.5f})"
        )
    deformations = [
        replay_deformed_vertices(
            positions=surface["positions"],
            heads=delivered["heads"],
            parents=delivered["parents"],
            joints=delivered["joints"],
            weights=delivered["weights"],
            frame_joints=frame_joints[index],
        )
        for index in range(pose.frame_count)
    ]
    cam = pose.camera
    native_h, native_w = (int(pose.alpha.shape[1]), int(pose.alpha.shape[2]))
    projected = cam.project(np.concatenate(deformations, axis=0))
    rows, cols = np.nonzero(pose.alpha.any(axis=0))
    crop_x0 = max(0.0, float(min(projected[:, 0].min(), cols.min())))
    crop_x1 = min(float(native_w), float(max(projected[:, 0].max(), cols.max()) + 1.0))
    crop_y0 = max(0.0, float(min(projected[:, 1].min(), rows.min())))
    crop_y1 = min(float(native_h), float(max(projected[:, 1].max(), rows.max()) + 1.0))
    margin = PANEL_MARGIN
    zoom = (int(panel_height) * (1.0 - 2.0 * margin)) / max(crop_y1 - crop_y0, 1e-9)
    panel_w = int(round((crop_x1 - crop_x0) * zoom / (1.0 - 2.0 * margin)))
    slack = np.array(
        [
            max(0.0, (panel_w - (crop_x1 - crop_x0) * zoom) * 0.5),
            max(0.0, (int(panel_height) - (crop_y1 - crop_y0) * zoom) * 0.5),
        ]
    )
    plate_k = cam.px_per_world * zoom
    plate_off = (cam.offset_px - np.array([crop_x0, crop_y0])) * zoom + slack
    affine = (
        1.0 / zoom,
        0.0,
        crop_x0 - slack[0] / zoom,
        0.0,
        1.0 / zoom,
        crop_y0 - slack[1] / zoom,
    )
    plate_backgrounds = [
        np.asarray(
            Image.open(frame.source_png).convert("RGBA").transform(
                (panel_w, int(panel_height)), Image.AFFINE, affine, resample=Image.Resampling.NEAREST
            ),
            dtype=np.float64,
        )
        for frame in pose.frames
    ]
    yaw = np.radians(35.0)
    pitch = np.radians(12.0)
    turn_right = np.array([np.cos(yaw), 0.0, np.sin(yaw)])
    turn_down = np.array([-np.sin(pitch) * np.sin(yaw), -np.cos(pitch), np.sin(pitch) * np.cos(yaw)])
    turn_forward = np.cross(turn_right, turn_down)
    turn_forward /= max(float(np.linalg.norm(turn_forward)), 1e-12)
    turn_k, turn_off = fit_camera(surface["positions"], right=turn_right, down=turn_down, width=panel_w, height=int(panel_height))
    light_turn = turn_forward * 0.7 + (-np.array([0.0, 1.0, 0.0])) * 0.5 + turn_right * 0.4
    light_turn /= np.linalg.norm(light_turn)
    plate_alpha = [_dilate(background[:, :, 3] > 0, 3) for background in plate_backgrounds]
    frames: list[Image.Image] = []
    frame_paths: list[str] = []
    output.mkdir(parents=True, exist_ok=True)
    state = evidence_caption(evidence)
    for index, deformed in enumerate(deformations):
        right_panel, right_mask = render_view(
            indices=surface["indices"], deformed=deformed, normals=surface["normals"], uvs=surface["uvs"],
            texture=surface["baseColor"], right=turn_right, down=turn_down, k=turn_k, off=turn_off,
            depth_dir=turn_forward, light=light_turn, width=panel_w, height=int(panel_height),
        )
        left_panel, left_mask = render_view(
            indices=surface["indices"], deformed=deformed, normals=surface["normals"], uvs=surface["uvs"],
            texture=surface["baseColor"], right=cam.right, down=cam.down, k=plate_k, off=plate_off,
            depth_dir=cam.forward, light=cam.forward, width=panel_w, height=int(panel_height),
            background=plate_backgrounds[index],
        )
        merged = np.concatenate([left_panel, np.full((int(panel_height), GUTTER, 3), 16.0), right_panel], axis=1)
        draw_caption(merged, f"{clip} / {index} | {state} | Meshy candidate")
        image = Image.fromarray(np.uint8(np.clip(merged, 0.0, 255.0)), mode="RGB")
        frame_path = output / f"frame-{index:03d}.png"
        image.save(frame_path)
        frame_paths.append(str(frame_path.resolve()).replace("\\", "/"))
        frames.append(image)
    full_reel = output / "full_reel.gif"
    write_gif(full_reel, frames, 1000.0 / 12.0)
    report_out = {
        "schema": "homm3.meshy-candidate-replay.v1",
        "proof": "generated-artifact; candidate replay against saved plates, not delivery proof",
        "unit": report.get("unit"),
        "clip": clip,
        "bind": str(bind.resolve()).replace("\\", "/"),
        "bindReport": str(bind_report.resolve()).replace("\\", "/"),
        "runDir": str(run_dir.resolve()).replace("\\", "/"),
        "registration": str(registration.resolve()).replace("\\", "/"),
        "frameCount": pose.frame_count,
        "panelHeight": int(panel_height),
        "sourceView": {
            "baseRegistration": "accepted registration camera",
            "yawOffsetDeg": float(camera_yaw_offset_deg),
            "policy": "diagnostic unit-local source-view correction; does not alter bind joints or weights",
        },
        "restFrameMaxVertexError": rest_vertex_error,
        "restFrameMaxJointHeadError": rest_joint_error,
        "auditOk": bool(report.get("auditOk")),
        "fullReel": str(full_reel.resolve()).replace("\\", "/"),
        "frames": frame_paths,
    }
    (output / "report.json").write_text(json.dumps(report_out, indent=2) + "\n", encoding="utf-8")
    return report_out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--registration", type=Path, required=True)
    parser.add_argument("--bind", type=Path, required=True)
    parser.add_argument("--bind-report", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--clip", default="g02_idle")
    parser.add_argument("--max-frames", type=int, default=8)
    parser.add_argument("--panel-height", type=int, default=1800)
    parser.add_argument(
        "--camera-yaw-offset-deg",
        type=float,
        default=0.0,
        help="unit-local source-view yaw offset relative to the accepted registration; diagnostic only",
    )
    args = parser.parse_args()
    print(json.dumps(run(run_dir=args.run_dir, registration=args.registration, bind=args.bind, bind_report=args.bind_report, output=args.out, clip=args.clip, max_frames=args.max_frames, panel_height=args.panel_height, camera_yaw_offset_deg=args.camera_yaw_offset_deg), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
