"""Render an existing capture-skeleton bind against its saved DEF frame sequence.

This is a diagnostic for the ``capture_bind`` plus ``raw_capture.npz`` contract.  It does
not refit weights, rewrite the bind, or produce an installable animation bundle.  The
camera is frozen from the accepted idle registration and the motion is reconstructed
from the saved capture with ``load_fixed_motion``.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import torch
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
EXPERIMENT = ROOT / "experiments/homm3_mocap_v2"
SILHOUETTE = ROOT / "tools/homm3_silhouette_pose_fit"
sys.path.insert(0, str(EXPERIMENT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(SILHOUETTE))

from gpu_cascade_batch_lock import cascade_batch_lock  # noqa: E402
from paths import REPO, SOURCE_FRAME_MS  # noqa: E402
from run_move_bind_t2_mocap_skin_fit import (  # noqa: E402
    assert_frame0_is_rest,
    load_fixed_motion,
    load_skin_bundle,
)
from run_skin_weight_pilot import shared_canvas_source_images, skin_with  # noqa: E402
from skin_camera_registration import _basis_yup  # noqa: E402
from skin_image_objective import SkinImageRenderer  # noqa: E402
from static_bind_registration import accepted_mesh_alignment  # noqa: E402


def canonical_square_crop(source_size: tuple[int, int]) -> dict[str, int]:
    width, height = (int(source_size[0]), int(source_size[1]))
    size = max(width, height)
    return {
        "left": -((size - width) // 2),
        "top": -((size - height) // 2),
        "size": size,
    }


def build_camera(
    registration: dict[str, Any],
    source_size: tuple[int, int],
    scale_factor: int,
    camera_yaw_offset_deg: float = 0.0,
) -> tuple[dict[str, Any], dict[str, int]]:
    if int(scale_factor) < 1:
        raise ValueError("scale_factor must be at least 1")
    candidates = registration["views"]["candidates"]
    selected = (registration.get("acceptance") or {}).get("selectedCandidateId")
    if selected:
        matches = [row for row in candidates if row.get("id") == selected]
        if len(matches) != 1:
            raise ValueError("accepted registration must select exactly one camera candidate")
        candidate = matches[0]
    else:
        candidate = candidates[0]
    registered = candidate["camera"]
    crop = canonical_square_crop(source_size)
    factor = int(scale_factor)
    base_yaw = float(registered.get("yawDeg", 0.0))
    pitch = float(registered.get("pitchDeg", 0.0))
    yaw = base_yaw + float(camera_yaw_offset_deg)
    basis = _basis_yup(yaw, pitch)
    camera = {
        "right": basis[0].tolist(),
        "down": basis[1].tolist(),
        "forward": basis[2].tolist(),
        "up": (-basis[1]).tolist(),
        "scale": float(registered["scale"]) * factor,
        "offset": [
            (float(registered["offset"][0]) - float(crop["left"])) * factor,
            (float(registered["offset"][1]) - float(crop["top"])) * factor,
        ],
        "depth_center": 0.0,
        "depth_span": 10.0,
        "resolution": int(crop["size"]) * factor,
        "sourceCrop": crop,
        "sourceSize": [int(source_size[0]), int(source_size[1])],
        "yawDeg": yaw,
        "baseRegistrationYawDeg": base_yaw,
        "cameraYawOffsetDeg": float(camera_yaw_offset_deg),
        "pitchDeg": pitch,
        "framingPolicy": "accepted_idle_registration_fixed_for_saved_bind_replay",
    }
    return camera, crop


def inverse_surface_alignment(vertices: np.ndarray, alignment: dict[str, Any]) -> np.ndarray:
    """Map capture-space vertices back into the source-mesh camera space.

    The bind GLB stores vertices after the accepted mesh-to-capture alignment,
    while the registration camera was fitted before that alignment. Replay must
    undo the accepted transform before projecting against the source sprite.
    """
    values = np.asarray(vertices, dtype=np.float64)
    rotation = np.asarray(alignment.get("rotation"), dtype=np.float64)
    scale = float(alignment.get("scale"))
    translation = np.asarray(alignment.get("translation"), dtype=np.float64)
    if values.shape[-1:] != (3,) or rotation.shape != (3, 3) or translation.shape != (3,):
        raise ValueError("surface alignment requires vertices [...,3], a 3x3 rotation, and a 3-vector translation")
    if not np.isfinite(values).all() or not np.isfinite(rotation).all() or not np.isfinite(translation).all():
        raise ValueError("surface alignment inputs must be finite")
    if not np.isfinite(scale) or scale <= 0.0:
        raise ValueError("surface alignment scale must be positive and finite")
    return (values - translation) @ rotation / scale


def _content_crop(source_alpha: np.ndarray, mesh_alpha: np.ndarray, padding: int) -> tuple[int, int, int, int]:
    mask = np.maximum(source_alpha, mesh_alpha).max(axis=0) > 0.02
    ys, xs = np.where(mask)
    if not len(xs):
        raise ValueError("source and mesh alpha are blank")
    height, width = source_alpha.shape[1:3]
    return (
        max(0, int(xs.min()) - int(padding)),
        max(0, int(ys.min()) - int(padding)),
        min(width, int(xs.max()) + 1 + int(padding)),
        min(height, int(ys.max()) + 1 + int(padding)),
    )


def _panel(source: np.ndarray, mesh: np.ndarray, label: str, resolution: int) -> Image.Image:
    row = Image.new("RGB", (resolution * 2, resolution + 30), (12, 12, 16))
    draw = ImageDraw.Draw(row)
    draw.text((4, 3), label, fill="white")
    draw.text((4, 17), "Sprite", fill=(190, 190, 210))
    draw.text((resolution + 4, 17), "Saved bind replay", fill=(190, 190, 210))
    row.paste(Image.fromarray(np.uint8(np.clip(source, 0.0, 1.0) * 255.0)), (0, 30))
    row.paste(Image.fromarray(np.uint8(np.clip(mesh, 0.0, 1.0) * 255.0)), (resolution, 30))
    return row


def validate_report(report: dict[str, Any]) -> None:
    required = {
        "schema",
        "proof",
        "unit",
        "bind",
        "capture",
        "master",
        "registration",
        "previewScale",
        "resolution",
        "frameCount",
        "restFrameMaxVertexError",
        "fullReel",
        "detailReel",
        "labels",
    }
    missing = sorted(required - set(report))
    if missing:
        raise ValueError(f"existing-bind replay report is missing fields: {missing}")
    if report["schema"] != "homm3.existing-bind-replay.v1":
        raise ValueError("unexpected existing-bind replay report schema")
    if "generated-artifact" not in str(report["proof"]):
        raise ValueError("existing-bind replay report must remain generated-artifact proof")
    if int(report["frameCount"]) != len(report["labels"]):
        raise ValueError("existing-bind replay labels do not match frameCount")
    if float(report["restFrameMaxVertexError"]) < 0.0:
        raise ValueError("rest-frame error cannot be negative")


def _write_gif(path: Path, frames: list[Image.Image], frame_ms: float) -> None:
    if not frames:
        raise ValueError("cannot write an empty reel")
    durations = [int(round((index + 1) * frame_ms / 10.0) - round(index * frame_ms / 10.0)) * 10 for index in range(len(frames))]
    frames[0].save(path, save_all=True, append_images=frames[1:], duration=durations, loop=0, optimize=False)


def run(
    *,
    bind: Path,
    capture: Path,
    master: Path,
    registration: Path,
    output: Path,
    preview_scale: int = 2,
    display_scale: int = 1,
    detail_padding: int = 24,
    batch_size: int = 4,
    camera_yaw_offset_deg: float = 0.0,
) -> dict[str, Any]:
    if output.exists():
        raise FileExistsError(f"choose a fresh output directory: {output}")
    if int(batch_size) < 1:
        raise ValueError("batch_size must be positive")
    master_payload = json.loads(master.read_text(encoding="utf-8"))
    registration_payload = json.loads(registration.read_text(encoding="utf-8"))
    frames = master_payload["frames"]
    sprite_paths = [Path(row["numberedPng"]) for row in frames]
    if not all(path.is_file() for path in sprite_paths):
        missing = [str(path) for path in sprite_paths if not path.is_file()]
        raise FileNotFoundError(f"master numbered frames are missing: {missing[:3]}")
    source_size = tuple(Image.open(sprite_paths[0]).size)
    if any(tuple(Image.open(path).size) != source_size for path in sprite_paths):
        raise ValueError("master numbered frames do not share one source canvas")
    camera, crop = build_camera(
        registration_payload,
        source_size,
        int(preview_scale),
        camera_yaw_offset_deg=float(camera_yaw_offset_deg),
    )
    surface_alignment = accepted_mesh_alignment(registration_payload)
    skin = load_skin_bundle(bind)
    motion = load_fixed_motion(skin, capture, reference_frame=int(master_payload.get("bindGlobalIndex", 0)))
    rest_error = assert_frame0_is_rest(skin, motion, reference_frame=int(master_payload.get("bindGlobalIndex", 0)))
    resolution = int(camera["resolution"])
    source_rgb, source_alpha, _ = shared_canvas_source_images(sprite_paths, resolution)[0]
    source_rgb_np = source_rgb.detach().cpu().numpy()
    source_alpha_np = source_alpha.detach().cpu().numpy()[..., 0]
    mesh_rgb_np = np.zeros_like(source_rgb_np)
    mesh_alpha_np = np.zeros_like(source_alpha_np)
    with cascade_batch_lock(REPO):
        renderer = SkinImageRenderer(skin["triangles"], skin["uvs"], skin["albedo"], camera, resolution)
        weights = torch.as_tensor(skin["weights"], device="cuda", dtype=torch.float32)
        vertices = torch.as_tensor(
            np.column_stack((skin["vertices"], np.ones(len(skin["vertices"]))),), device="cuda", dtype=torch.float32
        )
        alignment_rotation = torch.as_tensor(surface_alignment["rotation"], device="cuda", dtype=torch.float32)
        alignment_scale = float(surface_alignment["scale"])
        alignment_translation = torch.as_tensor(surface_alignment["translation"], device="cuda", dtype=torch.float32)
        with torch.no_grad():
            for start in range(0, len(frames), int(batch_size)):
                stop = min(len(frames), start + int(batch_size))
                worlds = torch.as_tensor(
                    motion["jointWorld"][start:stop] @ skin["inverseBind"][None], device="cuda", dtype=torch.float32
                )
                candidates = torch.einsum("fjkl,vl->fvjk", worlds[:, :, :3], vertices)
                posed = skin_with(candidates, weights)
                posed_source = (posed[..., :3] - alignment_translation) @ alignment_rotation / alignment_scale
                rgb, alpha = renderer.render(posed_source)
                mesh_rgb_np[start:stop] = rgb.detach().cpu().numpy()
                mesh_alpha_np[start:stop] = alpha.detach().cpu().numpy()[..., 0]
    if not np.isfinite(mesh_rgb_np).all() or not np.isfinite(mesh_alpha_np).all():
        raise ValueError("mesh replay contains nonfinite pixels")
    output.mkdir(parents=True)
    labels = [f"{row['clipKey']} / {row['localIndex']} / {row['role']}" for row in frames]
    full_frames = [_panel(source_rgb_np[i], mesh_rgb_np[i], labels[i], resolution) for i in range(len(frames))]
    display_frames = [frame.resize((frame.width * int(display_scale), frame.height * int(display_scale)), Image.Resampling.NEAREST) for frame in full_frames]
    _write_gif(output / "full_reel.gif", display_frames, float(master_payload.get("sourceFrameMs", SOURCE_FRAME_MS)))
    left, top, right, bottom = _content_crop(source_alpha_np, mesh_alpha_np, int(detail_padding) * int(preview_scale))
    detail_frames = []
    for i, label in enumerate(labels):
        source = Image.fromarray(np.uint8(np.clip(source_rgb_np[i, top:bottom, left:right], 0.0, 1.0) * 255.0))
        mesh = Image.fromarray(np.uint8(np.clip(mesh_rgb_np[i, top:bottom, left:right], 0.0, 1.0) * 255.0))
        detail_frames.append(_panel(np.asarray(source) / 255.0, np.asarray(mesh) / 255.0, label, right - left))
    detail_display = [frame.resize((frame.width * int(display_scale), frame.height * int(display_scale)), Image.Resampling.NEAREST) for frame in detail_frames]
    _write_gif(output / "detail_reel.gif", detail_display, float(master_payload.get("sourceFrameMs", SOURCE_FRAME_MS)))
    selected_indices = []
    seen_clips: set[str] = set()
    for index, row in enumerate(frames):
        if row["clipKey"] not in seen_clips:
            selected_indices.append(index)
            seen_clips.add(row["clipKey"])
    selected = [full_frames[index] for index in selected_indices]
    if selected:
        width = min(3, len(selected)) * selected[0].width
        height = ((len(selected) + 2) // 3) * selected[0].height
        contact = Image.new("RGB", (width, height), (12, 12, 16))
        for offset, image in enumerate(selected):
            contact.paste(image, ((offset % 3) * selected[0].width, (offset // 3) * selected[0].height))
        contact.save(output / "keyframes_contact.png")
    report = {
        "schema": "homm3.existing-bind-replay.v1",
        "proof": "generated-artifact fixed-camera replay; no delivery or runtime proof",
        "unit": str(master_payload.get("unit") or bind.stem),
        "bind": str(bind.resolve()).replace("\\", "/"),
        "capture": str(capture.resolve()).replace("\\", "/"),
        "master": str(master.resolve()).replace("\\", "/"),
        "registration": str(registration.resolve()).replace("\\", "/"),
        "previewScale": int(preview_scale),
        "cameraYawOffsetDeg": float(camera_yaw_offset_deg),
        "resolution": resolution,
        "sourceSize": list(source_size),
        "sourceCrop": crop,
        "camera": camera,
        "surfaceAlignment": surface_alignment,
        "meshRenderSpace": "source_mesh_camera_space_via_inverse_accepted_surface_alignment",
        "frameCount": len(frames),
        "restFrameMaxVertexError": float(rest_error),
        "fullReel": str((output / "full_reel.gif").resolve()).replace("\\", "/"),
        "detailReel": str((output / "detail_reel.gif").resolve()).replace("\\", "/"),
        "keyframes": str((output / "keyframes_contact.png").resolve()).replace("\\", "/") if selected else None,
        "labels": labels,
    }
    validate_report(report)
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bind", type=Path, required=True)
    parser.add_argument("--capture", type=Path, required=True)
    parser.add_argument("--master", type=Path, required=True)
    parser.add_argument("--registration", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--preview-scale", type=int, default=2)
    parser.add_argument("--display-scale", type=int, default=1)
    parser.add_argument("--detail-padding", type=int, default=24)
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument(
        "--camera-yaw-offset-deg",
        type=float,
        default=0.0,
        help="diagnostic camera yaw offset relative to the accepted registration; does not alter the bind",
    )
    args = parser.parse_args()
    report = run(
        bind=args.bind,
        capture=args.capture,
        master=args.master,
        registration=args.registration,
        output=args.out,
        preview_scale=args.preview_scale,
        display_scale=args.display_scale,
        detail_padding=args.detail_padding,
        batch_size=args.batch_size,
        camera_yaw_offset_deg=args.camera_yaw_offset_deg,
    )
    print(json.dumps({key: report[key] for key in ("unit", "resolution", "frameCount", "restFrameMaxVertexError", "fullReel", "detailReel", "keyframes")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
