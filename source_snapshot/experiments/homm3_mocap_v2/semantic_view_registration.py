#!/usr/bin/env python3
"""Rank static source-view cameras with silhouette, chroma, and DINOv2.

This is a diagnostic registration pass.  It never changes a bind, a mesh, or
an animation; its output is an explicit camera candidate for visual review.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import torch
from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO / "tools/homm3_silhouette_pose_fit"))

from camera_chroma_registration import score_candidate  # noqa: E402
from dino_embed import extract_subject_from_rgba  # noqa: E402
from gpu_cascade_batch_lock import cascade_batch_lock  # noqa: E402
from hybrid_dinov2 import DinoEncoder, cosine_quality  # noqa: E402
from run_skin_weight_pilot import source_images  # noqa: E402
from skin_camera_registration import _basis_yup, _bbox_scale_offset, _camera, _target_bbox  # noqa: E402
from skin_image_objective import SkinImageRenderer  # noqa: E402


def rgba(rgb: np.ndarray, alpha: np.ndarray) -> np.ndarray:
    result = np.zeros((*rgb.shape[:2], 4), dtype=np.uint8)
    result[..., :3] = np.uint8(np.clip(rgb, 0.0, 1.0) * 255)
    result[..., 3] = np.uint8(np.clip(alpha[..., 0], 0.0, 1.0) * 255)
    return result


def window(image: np.ndarray) -> dict[str, object]:
    ys, xs = np.where(image[..., 3] > 0)
    if not len(xs):
        raise ValueError("source has no visible pixels")
    return {"policy": "static_subject_aabb", "paddingRatio": 0.1, "bg": [1.0, 1.0, 1.0],
            "bboxXyxy": [int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1],
            "canvas": [int(image.shape[1]), int(image.shape[0])]}


def encode(encoder: DinoEncoder, image: np.ndarray, crop: dict[str, object]) -> np.ndarray:
    with cascade_batch_lock(REPO), torch.no_grad():
        return encoder.encode_rgb([extract_subject_from_rgba(image, crop)])[0]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skin", required=True, type=Path)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--resolution", type=int, default=224)
    args = parser.parse_args()
    if args.out.exists():
        raise FileExistsError(args.out)
    with np.load(args.skin, allow_pickle=False) as raw:
        skin = {name: raw[name].copy() for name in raw.files}
    with Image.open(args.source) as image:
        source_size = image.size
    crop_size = max(source_size)
    source_crop = {"left": -((crop_size - source_size[0]) // 2), "top": -((crop_size - source_size[1]) // 2), "size": crop_size}
    target = source_images([args.source], source_crop, args.resolution)
    source_rgb = target[0][0].detach().cpu().numpy()
    source_alpha = target[1][0].detach().cpu().numpy()
    source_rgba = rgba(source_rgb, source_alpha)
    target_bbox = _target_bbox(source_alpha[..., 0])
    candidates: list[dict[str, object]] = []
    with cascade_batch_lock(REPO), torch.no_grad():
        renderer = None
        for yaw in range(0, 360, 15):
            for pitch in range(-30, 61, 10):
                basis = _basis_yup(yaw, pitch)
                scale, offset = _bbox_scale_offset(skin["vertices"], basis, target_bbox)
                camera = _camera(basis, scale=scale, offset=offset, vertices=skin["vertices"], source_size=source_size,
                                 source_crop=source_crop, resolution=args.resolution, yaw_deg=yaw, pitch_deg=pitch)
                if renderer is None:
                    renderer = SkinImageRenderer(skin["triangles"], skin["uvs"], skin["albedo"], camera, args.resolution)
                else:
                    renderer.set_camera(camera)
                rgb, alpha = renderer.render(skin["vertices"][None])
                rendered_rgb = rgb[0].detach().cpu().numpy()
                rendered_alpha = alpha[0].detach().cpu().numpy()
                candidates.append({"yaw": yaw, "pitch": pitch, "camera": camera, "rgb": rendered_rgb, "alpha": rendered_alpha})
    source_window = window(source_rgba)
    encoder = DinoEncoder("cuda")
    source_embedding = encode(encoder, source_rgba, source_window)
    for candidate in candidates:
        candidate_rgba = rgba(candidate["rgb"], candidate["alpha"])
        metrics = score_candidate(source_rgb, source_alpha, candidate["rgb"], candidate["alpha"])
        dino = cosine_quality(source_embedding, encode(encoder, candidate_rgba, source_window))
        candidate["silhouetteIoU"] = metrics["alphaIoU"]
        candidate["chromaError"] = metrics["chromaError"]
        candidate["normalizedDinoV2"] = float(dino)
        candidate["score"] = float((metrics["alphaIoU"] + (1.0 - metrics["chromaError"]) + dino) / 3.0)
    candidates.sort(key=lambda row: float(row["score"]), reverse=True)
    args.out.mkdir(parents=True)
    panel = Image.new("RGB", (args.resolution * 5, args.resolution + 30), (10, 10, 14))
    draw = ImageDraw.Draw(panel)
    draw.text((4, 4), "semantic static-view ranking", fill="white")
    for column, candidate in enumerate(candidates[:4], start=1):
        image = Image.fromarray(rgba(candidate["rgb"], candidate["alpha"])[..., :3])
        panel.paste(image, (column * args.resolution, 30))
        draw.text((column * args.resolution + 4, 17), f"y{candidate['yaw']} p{candidate['pitch']} {candidate['score']:.3f}", fill=(190, 190, 205))
    panel.paste(Image.fromarray(source_rgba[..., :3]), (0, 30)); draw.text((4, 17), "source", fill=(190, 190, 205))
    panel.save(args.out / "semantic_view_top4.png")
    serial = [{key: value for key, value in candidate.items() if key not in ("rgb", "alpha", "camera")} for candidate in candidates]
    best = candidates[0]
    report = {"proof": "generated-candidate static-view diagnostic; not a mesh or animation change",
              "source": str(args.source.resolve()), "skin": str(args.skin.resolve()),
              "scoring": "equal mean silhouette IoU, chroma quality, normalized DINOv2 cosine",
              "bestCamera": best["camera"], "ranked": serial}
    (args.out / "report.json").write_text(
        json.dumps(report, indent=2, default=lambda value: value.tolist() if isinstance(value, np.ndarray) else float(value)) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"best": serial[0], "preview": str(args.out / "semantic_view_top4.png")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
