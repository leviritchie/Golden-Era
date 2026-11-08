"""Render a SmartRig idle clip against its exact DEF plates at review resolution.

This is the non-biped counterpart to ``render_existing_bind_replay.py``.  It
reads the SmartRig clip's local rotations, reconstructs the vendor skeleton's
local FK matrices, and skins the staged mesh directly.  No regions sidecar or
production bind rewrite is synthesized; the output is diagnostic generated
artifact evidence only.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import torch
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
EXPERIMENT = ROOT / "experiments/homm3_mocap_v2"
SILHOUETTE = ROOT / "tools/homm3_silhouette_pose_fit"
sys.path.insert(0, str(EXPERIMENT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(SILHOUETTE))

from gpu_cascade_batch_lock import cascade_batch_lock  # noqa: E402
from paths import REPO, SOURCE_FRAME_MS  # noqa: E402
from oe_motion_style_v2 import _animation  # noqa: E402
from register_smartrig_idle0 import _fk_positions, _q_to_matrix  # noqa: E402
from render_existing_bind_replay import (  # noqa: E402
    _content_crop,
    _panel,
    _write_gif,
    build_camera,
)
from run_skin_weight_pilot import shared_canvas_source_images, skin_with  # noqa: E402
from skin_image_objective import SkinImageRenderer  # noqa: E402
from glb_skeleton import load_bind_skeleton, read_glb  # noqa: E402


def _dense_weights(skeleton: Any) -> np.ndarray:
    joints = np.asarray(skeleton.vertex_joints, dtype=np.int64)
    sparse = np.asarray(skeleton.vertex_weights, dtype=np.float64)
    dense = np.zeros((len(joints), len(skeleton.names)), dtype=np.float64)
    for slot in range(joints.shape[1]):
        dense[np.arange(len(dense)), joints[:, slot]] += sparse[:, slot]
    totals = dense.sum(axis=1)
    if np.any(totals <= 1e-8):
        raise ValueError("SmartRig bind contains zero-weight vertices")
    return dense / totals[:, None]


def _local_world_matrices(skeleton: Any, rotations: np.ndarray) -> np.ndarray:
    local = np.stack([np.stack([_q_to_matrix(row) for row in frame], axis=0) for frame in rotations], axis=0)
    worlds = np.zeros((len(local), len(skeleton.names), 4, 4), dtype=np.float64)
    for frame_index in range(len(local)):
        for joint_index, parent in enumerate(skeleton.parents):
            matrix = np.eye(4, dtype=np.float64)
            matrix[:3, :3] = local[frame_index, joint_index]
            matrix[:3, 3] = skeleton.rest_local_translation[joint_index]
            worlds[frame_index, joint_index] = (
                matrix if int(parent) < 0 else worlds[frame_index, int(parent)] @ matrix
            )
    return worlds


def _skinned_rest_error(skeleton: Any, worlds: np.ndarray, weights: np.ndarray) -> float:
    vertices = np.column_stack((np.asarray(skeleton.vertices, dtype=np.float64), np.ones(len(skeleton.vertices))))
    posed = np.zeros_like(vertices)
    for joint in range(len(skeleton.names)):
        posed += np.einsum(
            "ij,vj->vi",
            worlds[0, joint] @ np.asarray(skeleton.inverse_bind[joint]),
            vertices,
        ) * weights[:, joint, None]
    return float(np.max(np.abs(posed[:, :3] - vertices[:, :3])))


def run(*, bind: Path, clip: Path, master: Path, registration: Path, output: Path, preview_scale: int = 8) -> dict[str, Any]:
    if output.exists():
        raise FileExistsError(f"choose a fresh output directory: {output}")
    skeleton = load_bind_skeleton(bind)
    if skeleton.vertices is None or skeleton.triangles is None or skeleton.uvs is None or skeleton.albedo is None:
        raise ValueError("SmartRig bind is missing renderable mesh attributes")
    if skeleton.inverse_bind is None or skeleton.vertex_joints is None or skeleton.vertex_weights is None:
        raise ValueError("SmartRig bind is missing skin data")
    clip_doc = read_glb(clip)
    _animation_doc, times, rotations, _outputs = _animation(clip_doc, clip_doc["bin"], skeleton)
    frame_count = len(times) - 1
    rotations = np.asarray(rotations[:frame_count], dtype=np.float64)
    worlds = _local_world_matrices(skeleton, rotations)
    weights = _dense_weights(skeleton)
    rest_error = _skinned_rest_error(skeleton, worlds, weights)
    master_payload = json.loads(master.read_text(encoding="utf-8"))
    frames = master_payload["frames"]
    if len(frames) != frame_count:
        raise ValueError("SmartRig clip and idle master frame counts disagree")
    sprite_paths = [Path(row["numberedPng"]) for row in frames]
    if not all(path.is_file() for path in sprite_paths):
        raise FileNotFoundError(next(str(path) for path in sprite_paths if not path.is_file()))
    source_size = tuple(Image.open(sprite_paths[0]).size)
    camera, crop = build_camera(
        json.loads(registration.read_text(encoding="utf-8")),
        source_size,
        int(preview_scale),
    )
    resolution = int(camera["resolution"])
    source_rgb, source_alpha, _ = shared_canvas_source_images(sprite_paths, resolution)[0]
    source_rgb_np = source_rgb.detach().cpu().numpy()
    source_alpha_np = source_alpha.detach().cpu().numpy()[..., 0]
    mesh_rgb_np = np.zeros_like(source_rgb_np)
    mesh_alpha_np = np.zeros_like(source_alpha_np)
    with cascade_batch_lock(REPO):
        renderer = SkinImageRenderer(skeleton.triangles, skeleton.uvs, skeleton.albedo, camera, resolution)
        torch_weights = torch.as_tensor(weights, device="cuda", dtype=torch.float32)
        vertices = torch.as_tensor(
            np.column_stack((np.asarray(skeleton.vertices), np.ones(len(skeleton.vertices)))),
            device="cuda",
            dtype=torch.float32,
        )
        with torch.no_grad():
            for start in range(0, frame_count, 4):
                stop = min(frame_count, start + 4)
                torch_worlds = torch.as_tensor(worlds[start:stop], device="cuda", dtype=torch.float32)
                candidates = torch.einsum(
                    "fjkl,vl->fvjk",
                    torch_worlds[:, :, :3],
                    vertices,
                )
                posed = skin_with(candidates, torch_weights)
                rgb, alpha = renderer.render(posed[..., :3])
                mesh_rgb_np[start:stop] = rgb.detach().cpu().numpy()
                mesh_alpha_np[start:stop] = alpha.detach().cpu().numpy()[..., 0]
    output.mkdir(parents=True)
    labels = [f"{row['clipKey']} / {row['localIndex']} / {row['role']}" for row in frames]
    full_frames = [_panel(source_rgb_np[i], mesh_rgb_np[i], labels[i], resolution) for i in range(frame_count)]
    _write_gif(output / "full_reel.gif", full_frames, float(master_payload.get("sourceFrameMs", SOURCE_FRAME_MS)))
    left, top, right, bottom = _content_crop(source_alpha_np, mesh_alpha_np, 24 * int(preview_scale))
    detail_frames = []
    for i, label in enumerate(labels):
        source = Image.fromarray(np.uint8(np.clip(source_rgb_np[i, top:bottom, left:right], 0.0, 1.0) * 255.0))
        mesh = Image.fromarray(np.uint8(np.clip(mesh_rgb_np[i, top:bottom, left:right], 0.0, 1.0) * 255.0))
        detail_frames.append(_panel(np.asarray(source) / 255.0, np.asarray(mesh) / 255.0, label, right - left))
    _write_gif(output / "detail_reel.gif", detail_frames, float(master_payload.get("sourceFrameMs", SOURCE_FRAME_MS)))
    contact_cell = min(1800, full_frames[0].width)
    contact_rows = (len(full_frames) + 2) // 3
    contact = Image.new("RGB", (3 * contact_cell, contact_rows * contact_cell), (12, 12, 16))
    for index, image in enumerate(full_frames):
        thumb = image.resize((contact_cell, contact_cell), Image.Resampling.LANCZOS)
        contact.paste(thumb, ((index % 3) * contact_cell, (index // 3) * contact_cell))
    contact.save(output / "keyframes_contact.png")
    report = {
        "schema": "homm3.smartrig-idle-replay.v1",
        "proof": "generated-artifact fixed-camera SmartRig replay; no delivery or runtime proof",
        "unit": str(master_payload.get("unit") or bind.stem),
        "bind": str(bind.resolve()).replace("\\", "/"),
        "clip": str(clip.resolve()).replace("\\", "/"),
        "master": str(master.resolve()).replace("\\", "/"),
        "registration": str(registration.resolve()).replace("\\", "/"),
        "previewScale": int(preview_scale),
        "resolution": resolution,
        "frameCount": frame_count,
        "restFrameMaxVertexError": rest_error,
        "surfaceAlignment": "none_bind_vertices_are_registration_mesh_frame",
        "fullReel": str((output / "full_reel.gif").resolve()).replace("\\", "/"),
        "detailReel": str((output / "detail_reel.gif").resolve()).replace("\\", "/"),
        "keyframes": str((output / "keyframes_contact.png").resolve()).replace("\\", "/"),
        "labels": labels,
    }
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bind", type=Path, required=True)
    parser.add_argument("--clip", type=Path, required=True)
    parser.add_argument("--master", type=Path, required=True)
    parser.add_argument("--registration", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--preview-scale", type=int, default=8)
    args = parser.parse_args()
    print(json.dumps(run(
        bind=args.bind,
        clip=args.clip,
        master=args.master,
        registration=args.registration,
        output=args.out,
        preview_scale=args.preview_scale,
    ), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
