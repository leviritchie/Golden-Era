#!/usr/bin/env python3
"""Estimate monocular depth for the Factory town 4K plate (offline Option B spike).

Uses Depth Anything V2 via Hugging Face transformers. Writes float depth + viz
under artifacts/.../backdrop_depth_project/. Does not deploy to the game.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import torch
from PIL import Image
from transformers import AutoImageProcessor, AutoModelForDepthEstimation

REPO = Path(__file__).resolve().parents[2]
DEFAULT_IMAGE = (
    REPO
    / "Heroes of Might & Magic Olden Era Playtest"
    / "OfflineUnlockMod"
    / "homm3_runtime_assets"
    / "town_scene_refs"
    / "homm3_factory"
    / "mockups"
    / "homm3_factory_background_upscaled_3840x2160.png"
)
DEFAULT_OUT = (
    REPO
    / "artifacts"
    / "meshy_town_scene_meshes"
    / "homm3_factory"
    / "backdrop_depth_project"
)
DEFAULT_MODEL = "depth-anything/Depth-Anything-V2-Base-hf"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--image", type=Path, default=DEFAULT_IMAGE)
    ap.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--model", default=DEFAULT_MODEL)
    args = ap.parse_args()

    image_path = args.image.resolve()
    out_dir = args.out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    if not image_path.is_file():
        raise SystemExit(f"missing image: {image_path}")

    image = Image.open(image_path).convert("RGB")
    w, h = image.size
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"image={image_path} size={w}x{h} device={device} model={args.model}")

    processor = AutoImageProcessor.from_pretrained(args.model)
    model = AutoModelForDepthEstimation.from_pretrained(args.model)
    model.to(device)
    model.eval()

    inputs = processor(images=image, return_tensors="pt")
    inputs = {k: v.to(device) for k, v in inputs.items()}
    with torch.no_grad():
        outputs = model(**inputs)

    # Prefer processor post-process when available; else bicubic upsample.
    predicted = None
    if hasattr(processor, "post_process_depth_estimation"):
        post = processor.post_process_depth_estimation(
            outputs, target_sizes=[(h, w)]
        )
        predicted = post[0]["predicted_depth"]
    else:
        predicted = torch.nn.functional.interpolate(
            outputs.predicted_depth.unsqueeze(1),
            size=(h, w),
            mode="bicubic",
            align_corners=False,
        ).squeeze()

    depth = predicted.detach().float().cpu().numpy()
    if depth.ndim != 2:
        raise SystemExit(f"unexpected depth shape: {depth.shape}")

    depth_path = out_dir / "depth_float32.npy"
    np.save(depth_path, depth.astype(np.float32))

    dmin = float(depth.min())
    dmax = float(depth.max())
    norm = (depth - dmin) / (dmax - dmin + 1e-8)
    depth_u16 = (norm * 65535.0).astype(np.uint16)
    Image.fromarray(depth_u16, mode="I;16").save(out_dir / "depth_u16.png")

    # Turbo-ish grayscale for quick human read (near=bright).
    vis = (255.0 * (1.0 - norm)).astype(np.uint8)
    Image.fromarray(vis, mode="L").save(out_dir / "depth_near_bright.png")

    meta = {
        "source_image": str(image_path),
        "model": args.model,
        "width": w,
        "height": h,
        "depth_min": dmin,
        "depth_max": dmax,
        "device": device,
        "convention": "larger predicted_depth = farther; near_bright viz inverts for display",
        "proof": "offline_spike_only_not_game_deploy",
    }
    (out_dir / "depth_meta.json").write_text(
        json.dumps(meta, indent=2) + "\n", encoding="utf-8"
    )
    print(f"wrote {depth_path}")
    print(f"depth range [{dmin:.4f}, {dmax:.4f}]")


if __name__ == "__main__":
    main()
