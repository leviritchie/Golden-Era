"""Measure unit-local source-view yaw candidates on one saved bind frame.

This is a presentation/registration diagnostic only. It does not alter a bind,
camera registration, queue review, or delivery artifact.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import torch
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
EXPERIMENT = ROOT / "experiments/homm3_mocap_v2"
SILHOUETTE = ROOT / "tools/homm3_silhouette_pose_fit"
if str(EXPERIMENT) not in sys.path:
    sys.path.insert(0, str(EXPERIMENT))
if str(SILHOUETTE) not in sys.path:
    sys.path.insert(0, str(SILHOUETTE))
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from gpu_cascade_batch_lock import cascade_batch_lock  # noqa: E402
from paths import REPO  # noqa: E402
from render_existing_bind_replay import build_camera, canonical_square_crop  # noqa: E402
from run_move_bind_t2_mocap_skin_fit import load_fixed_motion, load_skin_bundle  # noqa: E402
from run_skin_weight_pilot import shared_canvas_source_images, skin_with  # noqa: E402
from skin_image_objective import SkinImageRenderer  # noqa: E402
from static_bind_registration import accepted_mesh_alignment  # noqa: E402


def iou(left: np.ndarray, right: np.ndarray) -> float:
    overlap = np.count_nonzero(left & right)
    union = np.count_nonzero(left | right)
    return float(overlap / max(union, 1))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bind", type=Path, required=True)
    parser.add_argument("--capture", type=Path, required=True)
    parser.add_argument("--master", type=Path, required=True)
    parser.add_argument("--registration", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--preview-scale", type=int, default=4)
    parser.add_argument("--yaw", nargs="+", type=float, default=[-180, -135, -90, -45, 0, 45, 90, 135, 180])
    args = parser.parse_args()
    if args.out.exists():
        raise FileExistsError(f"choose a fresh output directory: {args.out}")
    master = json.loads(args.master.read_text(encoding="utf-8"))
    registration = json.loads(args.registration.read_text(encoding="utf-8"))
    sprite_paths = [Path(row["numberedPng"]) for row in master["frames"]]
    source_size = tuple(Image.open(sprite_paths[0]).size)
    skin = load_skin_bundle(args.bind)
    motion = load_fixed_motion(skin, args.capture, reference_frame=int(master.get("bindGlobalIndex", 0)))
    alignment = accepted_mesh_alignment(registration)
    crop = canonical_square_crop(source_size)
    output = args.out.resolve()
    output.mkdir(parents=True)
    results: list[dict[str, float]] = []
    source_rgb, source_alpha, _ = shared_canvas_source_images(sprite_paths, int(build_camera(registration, source_size, args.preview_scale)[0]["resolution"]))[0]
    source_rgb_np = source_rgb.detach().cpu().numpy()
    source_alpha_np = source_alpha.detach().cpu().numpy()[..., 0] > 0.02
    with cascade_batch_lock(REPO):
        for yaw in args.yaw:
            camera, _ = build_camera(registration, source_size, args.preview_scale, camera_yaw_offset_deg=float(yaw))
            resolution = int(camera["resolution"])
            renderer = SkinImageRenderer(skin["triangles"], skin["uvs"], skin["albedo"], camera, resolution)
            vertices = torch.as_tensor(np.column_stack((skin["vertices"], np.ones(len(skin["vertices"]))),), device="cuda", dtype=torch.float32)
            weights = torch.as_tensor(skin["weights"], device="cuda", dtype=torch.float32)
            worlds = torch.as_tensor(motion["jointWorld"][0:1] @ skin["inverseBind"][None], device="cuda", dtype=torch.float32)
            with torch.no_grad():
                candidates = torch.einsum("fjkl,vl->fvjk", worlds[:, :, :3], vertices)
                posed = skin_with(candidates, weights)
                posed_source = (posed[..., :3] - torch.as_tensor(alignment["translation"], device="cuda", dtype=torch.float32)) @ torch.as_tensor(alignment["rotation"], device="cuda", dtype=torch.float32) / float(alignment["scale"])
                _, mesh_alpha = renderer.render(posed_source)
            mesh_mask = mesh_alpha.detach().cpu().numpy()[0, ..., 0] > 0.02
            value = iou(source_alpha_np[0], mesh_mask)
            results.append({"yawOffsetDeg": float(yaw), "iou": value, "sourcePixels": int(source_alpha_np[0].sum()), "meshPixels": int(mesh_mask.sum())})
            source_panel = np.uint8(np.clip(source_rgb_np[0], 0.0, 1.0) * 255.0)
            mesh_rgb, _ = renderer.render(posed_source)
            mesh_panel = np.uint8(np.clip(mesh_rgb.detach().cpu().numpy()[0], 0.0, 1.0) * 255.0)
            image = Image.new("RGB", (resolution * 2, resolution + 32), (12, 12, 16))
            image.paste(Image.fromarray(source_panel), (0, 32))
            image.paste(Image.fromarray(mesh_panel), (resolution, 32))
            draw = ImageDraw.Draw(image)
            draw.text((4, 4), f"yaw offset {yaw:g} deg | IoU {value:.4f}", fill="white")
            image.save(output / f"yaw_{int(yaw):+04d}.png")
    report = {
        "schema": "homm3.bind-yaw-iou-diagnostic.v1",
        "proof": "generated-artifact diagnostic only; source-view yaw sweep, not registration acceptance",
        "bind": str(args.bind.resolve()).replace("\\", "/"),
        "capture": str(args.capture.resolve()).replace("\\", "/"),
        "registration": str(args.registration.resolve()).replace("\\", "/"),
        "previewScale": int(args.preview_scale),
        "results": results,
        "bestByIoU": max(results, key=lambda row: row["iou"]),
    }
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
