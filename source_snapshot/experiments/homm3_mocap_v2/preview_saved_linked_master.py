"""Replay an explicitly selected saved candidate; never bind, fit, or accept it."""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np
import torch
from PIL import Image, ImageDraw

from run_linked_master_pipeline import load_candidate_weights, pose_master
from run_move_bind_t2_mocap_skin_fit import load_fixed_motion, load_skin_bundle
from run_skin_weight_pilot import shared_canvas_source_images
from skin_image_objective import SkinImageRenderer
from gpu_cascade_batch_lock import cascade_batch_lock
from paths import REPO
from pin import sha256_file


def _tight_detail_crop(source: np.ndarray, mesh: np.ndarray, *, padding: int) -> tuple[int, int, int, int]:
    """Return one stable content crop for both panels across the whole reel."""
    pixels = np.concatenate((source, mesh), axis=0)
    mask = np.max(pixels, axis=-1).any(axis=0) > (8.0 / 255.0)
    ys, xs = np.where(mask)
    if len(xs) == 0 or len(ys) == 0:
        raise ValueError("source and candidate are blank; cannot make detail crop")
    height, width = source.shape[1:3]
    left = max(0, int(xs.min()) - int(padding))
    top = max(0, int(ys.min()) - int(padding))
    right = min(width, int(xs.max()) + 1 + int(padding))
    bottom = min(height, int(ys.max()) + 1 + int(padding))
    return left, top, right, bottom


def _rotate_candidate_y(vertices: np.ndarray, yaw_deg: float) -> np.ndarray:
    """Rotate only the rendered candidate for an explicit facing diagnostic."""
    yaw = float(yaw_deg)
    if abs(yaw) < 1e-9:
        return vertices
    angle = np.radians(yaw)
    cosine = float(np.cos(angle))
    sine = float(np.sin(angle))
    rotation = np.array(
        [[cosine, 0.0, sine], [0.0, 1.0, 0.0], [-sine, 0.0, cosine]],
        dtype=vertices.dtype,
    )
    return np.asarray(vertices @ rotation.T)


def run(
    linked: Path,
    output: Path,
    *,
    preview_scale: int = 1,
    display_scale: int = 2,
    detail_padding: int = 24,
    candidate_yaw_deg: float = 0.0,
) -> dict:
    if int(preview_scale) < 1:
        raise ValueError("preview_scale must be at least 1")
    if int(display_scale) < 1:
        raise ValueError("display_scale must be at least 1")
    if int(detail_padding) < 0:
        raise ValueError("detail_padding must be nonnegative")
    started = time.perf_counter()
    if output.exists():
        raise FileExistsError(f"choose a fresh preview directory: {output}")
    report_path = linked / "report.json"
    saved = json.loads(report_path.read_text(encoding="utf-8"))
    master_path = linked / "master_sequence/master_sequence.json"
    master = json.loads(master_path.read_text(encoding="utf-8"))
    if saved["unit"] != master["unit"]:
        raise ValueError("saved report and master unit differ")
    for key in ("capture", "bindGlb"):
        hash_key = "captureSha256" if key == "capture" else "bindSha256"
        if sha256_file(Path(saved[key])) != saved[hash_key]:
            raise ValueError(f"saved {key} hash drifted")
    sprites = [Path(row["numberedPng"]) for row in master["frames"]]
    for path, row in zip(sprites, master["frames"]):
        if sha256_file(path) != row["sourceSha256"]:
            raise ValueError(f"source frame hash drifted: {path}")
    weights_path = linked / "skin_fit/candidate_weights.npz"
    camera_path = linked / "skin_fit/camera.json"
    camera = json.loads(camera_path.read_text(encoding="utf-8"))
    base_resolution = int(camera["resolution"])
    resolution = base_resolution * int(preview_scale)
    camera = dict(camera)
    if preview_scale != 1:
        # Re-rasterize at the larger canvas. Scaling only the saved PNG would
        # preserve the old information loss and hide ownership defects.
        for key in ("scale", "pxPerWorld"):
            if key in camera:
                camera[key] = float(camera[key]) * int(preview_scale)
        for key in ("offset", "screenOffsetPx"):
            if key in camera:
                camera[key] = [float(value) * int(preview_scale) for value in camera[key]]
        camera["resolution"] = resolution
    skin = load_skin_bundle(Path(saved["bindGlb"]))
    weights = load_candidate_weights(weights_path, skin)
    motion = load_fixed_motion(skin, Path(saved["capture"]), reference_frame=int(master["bindGlobalIndex"]))
    posed = pose_master(skin, motion, weights)
    posed = _rotate_candidate_y(posed, candidate_yaw_deg)
    if len(posed) != len(sprites):
        raise ValueError("motion and source frame counts differ")
    with cascade_batch_lock(REPO), torch.no_grad():
        targets, crop, size = shared_canvas_source_images(sprites, resolution)
        if any(crop[k] != camera["sourceCrop"][k] for k in ("left", "top", "size")) or list(size) != camera["sourceSize"]:
            raise ValueError("saved camera and source canvas differ")
        renderer = SkinImageRenderer(skin["triangles"], skin["uvs"], skin["albedo"], camera, resolution)
        rgb, alpha = renderer.render(torch.as_tensor(posed, device="cuda", dtype=torch.float32))
        # Renderer RGB is already alpha-premultiplied.
        mesh = rgb.cpu().numpy()
        source = targets[0].cpu().numpy()
        coverage = alpha.sum((1, 2, 3)).cpu().numpy()
    if not np.isfinite(mesh).all() or np.any(coverage <= 1):
        raise ValueError("nonfinite or blank mesh render")
    rows = []
    for i, frame in enumerate(master["frames"]):
        row = Image.new("RGB", (resolution * 2, resolution + 30), (12, 12, 16))
        draw = ImageDraw.Draw(row)
        draw.text((4, 3), f"{frame['clipKey']} / {frame['localIndex']} / {frame['role']}", fill="white")
        draw.text((4, 17), "Source", fill="white")
        draw.text((resolution + 4, 17), "Saved candidate - unaccepted", fill="white")
        for column, pixels in enumerate((source[i], mesh[i])):
            row.paste(Image.fromarray(np.uint8(np.clip(pixels, 0, 1) * 255)), (column * resolution, 30))
        rows.append(row.resize((row.width * int(display_scale), row.height * int(display_scale)), Image.Resampling.NEAREST))
    crop_left, crop_top, crop_right, crop_bottom = _tight_detail_crop(
        source, mesh, padding=int(detail_padding) * int(preview_scale)
    )
    detail_rows = []
    detail_size = (crop_right - crop_left, crop_bottom - crop_top)
    for i, frame in enumerate(master["frames"]):
        row = Image.new("RGB", (detail_size[0] * 2, detail_size[1] + 30), (12, 12, 16))
        draw = ImageDraw.Draw(row)
        draw.text((4, 3), f"{frame['clipKey']} / {frame['localIndex']} / {frame['role']}", fill="white")
        draw.text((4, 17), "Source", fill="white")
        draw.text((detail_size[0] + 4, 17), "Saved candidate - unaccepted", fill="white")
        for column, pixels in enumerate((source[i], mesh[i])):
            panel = Image.fromarray(np.uint8(np.clip(pixels, 0, 1) * 255))
            row.paste(panel.crop((crop_left, crop_top, crop_right, crop_bottom)), (column * detail_size[0], 30))
        detail_rows.append(
            row.resize((row.width * int(display_scale), row.height * int(display_scale)), Image.Resampling.NEAREST)
        )
    output.mkdir(parents=True)
    frame_ms = float(master["sourceFrameMs"])

    def save(name: str, frames: list[Image.Image]) -> str:
        # GIF stores centiseconds. Distribute rounding rather than speeding up 12fps to 12.5fps.
        durations = [int(round((i + 1) * frame_ms / 10) - round(i * frame_ms / 10)) * 10 for i in range(len(frames))]
        path = output / name
        frames[0].save(path, save_all=True, append_images=frames[1:], duration=durations, loop=0)
        return str(path.resolve())

    full = save("full_reel.gif", rows)
    detail = save("detail_reel.gif", detail_rows)
    clips = {}
    for segment in master["segments"]:
        if segment["exportsClip"]:
            name = str(segment["contractSuffix"])
            clips[name] = save(name + ".gif", rows[segment["globalStart"]:segment["globalEnd"]])
            save(name + "_detail.gif", detail_rows[segment["globalStart"]:segment["globalEnd"]])
    rows[0].save(output / "first_frame.png")
    result = {"proof": "diagnostic replay of saved generated candidate", "visualAcceptance": "unaccepted",
              "unit": master["unit"], "sourceRun": str(linked.resolve()), "sourceReportSha256": sha256_file(report_path),
              "masterSha256": sha256_file(master_path), "weightsSha256": sha256_file(weights_path),
              "cameraSha256": sha256_file(camera_path), "frameCount": len(rows), "sourceFrameMs": frame_ms,
              "cameraPolicy": "saved_camera_supersampled_exact_shared_source_canvas" if preview_scale != 1 else "unchanged_saved_camera_exact_shared_source_canvas",
              "candidateYawDeg": float(candidate_yaw_deg),
              "baseResolution": base_resolution, "renderResolution": resolution,
              "previewScale": int(preview_scale), "displayScale": int(display_scale),
              "fullReel": full, "detailReel": detail,
              "detailCrop": {"left": crop_left, "top": crop_top, "right": crop_right, "bottom": crop_bottom,
                             "padding": int(detail_padding) * int(preview_scale)},
              "clips": clips,
              "meshPixelChangeMax": float(np.max(np.abs(np.diff(mesh, axis=0)))),
              "minCoveragePixels": float(coverage.min()), "elapsedSeconds": time.perf_counter() - started}
    (output / "preview_report.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--linked", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--preview-scale", type=int, default=1)
    parser.add_argument("--display-scale", type=int, default=2)
    parser.add_argument("--detail-padding", type=int, default=24)
    parser.add_argument(
        "--candidate-yaw-deg",
        type=float,
        default=0.0,
        help="rotate only the candidate mesh for an explicit facing diagnostic; does not alter saved inputs",
    )
    args = parser.parse_args()
    run(
        args.linked.resolve(),
        args.output.resolve(),
        preview_scale=args.preview_scale,
        display_scale=args.display_scale,
        detail_padding=args.detail_padding,
        candidate_yaw_deg=float(args.candidate_yaw_deg),
    )
