#!/usr/bin/env python3
"""Stronghold full-3D town: monocular depth of the ORIGINAL HoMM3 Stronghold art (no Meshy, no outpaint).

    python tools/homm3_town_scene_meshes/stronghold_full3d_depth.py

Runs three local monocular estimators on
  * the HoMM3 town background (Stronghold-in-background.png, 800x374, resized to the 1440x673 frame rect only as
    model input), and
  * every building sprite composited over that background at its positions.json place (a context crop, so the model
    sees the building standing on its own ground),
and writes their raw outputs to artifacts/homm3_stronghold_full3d/depth/:
  da_base.npy / da_large.npy   Depth Anything V2 (relative, disparity-like: larger = nearer)
  depthpro.npy                 Apple Depth Pro (metric depth in m + its own focal estimate; scale is NOT trusted,
                               the calibration in stronghold_full3d_scene.py uses its shape only)
  layers/<layer>_{da_large,depthpro}.npy   per-sprite context crops (crop box in layers/index.json)
Model weights live in artifacts/homm3_stronghold_full3d/hf_cache (V:), never C:.
Proof tier: generated artifact (depth estimates). Nothing here is geometry yet.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
import stronghold_full3d_common as SC  # noqa: E402

DEPTH = SC.DATA / "depth"
CACHE = SC.HF_CACHE
CROP_MARGIN = 40   # HoMM3 px of context around each sprite


def load_models():
    import torch
    from transformers import (AutoImageProcessor, AutoModelForDepthEstimation, DepthProForDepthEstimation,
                              DepthProImageProcessorFast)
    ms = {}
    for tag, name, cache in (("da_base", "depth-anything/Depth-Anything-V2-Base-hf", None),
                             ("da_large", "depth-anything/Depth-Anything-V2-Large-hf", str(CACHE))):
        proc = AutoImageProcessor.from_pretrained(name, cache_dir=cache)
        model = AutoModelForDepthEstimation.from_pretrained(name, cache_dir=cache).to("cuda").eval()
        ms[tag] = ("da", proc, model)
    proc = DepthProImageProcessorFast.from_pretrained("apple/DepthPro-hf", cache_dir=str(CACHE))
    model = DepthProForDepthEstimation.from_pretrained("apple/DepthPro-hf", cache_dir=str(CACHE),
                                                       torch_dtype=torch.float16).to("cuda").eval()
    ms["depthpro"] = ("dp", proc, model)
    return ms


def run(ms, tag: str, img: Image.Image, size: tuple[int, int]) -> np.ndarray:
    import torch
    kind, proc, model = ms[tag]
    w, h = size
    with torch.no_grad():
        inp = proc(images=img, return_tensors="pt")
        inp = {k: v.to("cuda") for k, v in inp.items()}
        if kind == "dp":
            inp = {k: (v.half() if v.is_floating_point() else v) for k, v in inp.items()}
            out = model(**inp)
            post = proc.post_process_depth_estimation(out, target_sizes=[(h, w)])[0]
            return post["predicted_depth"].float().cpu().numpy()
        out = model(**inp)
        pred = torch.nn.functional.interpolate(out.predicted_depth.unsqueeze(1).float(), size=(h, w),
                                               mode="bicubic", align_corners=False)[0, 0]
        return pred.cpu().numpy()


NEED_VRAM_GB = 6.0   # Depth Anything V2 base + large and Depth Pro fp16 held together


def main() -> int:
    import town_full3d_gpu   # the lane's one GPU gate (gpuslot + town single-flight lock + memgate VRAM check)
    with town_full3d_gpu.gate(f"depth {SC.FACTION}", need_vram_gb=NEED_VRAM_GB):
        return _main()


def _main() -> int:
    DEPTH.mkdir(parents=True, exist_ok=True)
    (DEPTH / "layers").mkdir(exist_ok=True)
    ms = load_models()
    bg = SC.background_rgb()                        # 800x374 original
    frame_in = bg.resize((SC.TW, SC.TH), Image.LANCZOS)  # model input only
    for tag in ms:
        d = run(ms, tag, frame_in, (SC.TW, SC.TH))
        np.save(DEPTH / f"{tag}.npy", d.astype(np.float32))
        print(tag, d.shape, float(d.min()), float(d.max()))
    index = {}
    bg_rgba = SC.background_rgba()
    for lid, L in SC.layers().items():
        spr = SC.sprite(L)
        comp = bg_rgba.copy()
        comp.alpha_composite(spr, (L["x"], L["y"]))
        x0 = max(0, L["x"] - CROP_MARGIN)
        y0 = max(0, L["y"] - CROP_MARGIN)
        x1 = min(800, L["x"] + spr.width + CROP_MARGIN)
        y1 = min(374, L["y"] + spr.height + CROP_MARGIN)
        crop = comp.crop((x0, y0, x1, y1)).convert("RGB")
        k = 4  # model input at 4x (it resizes to ~518 anyway; output returned at 4x the HoMM3 crop)
        big = crop.resize((crop.width * k, crop.height * k), Image.LANCZOS)
        for tag in ("da_large", "depthpro"):
            d = run(ms, tag, big, big.size)
            np.save(DEPTH / "layers" / f"{lid}_{tag}.npy", d.astype(np.float32))
        index[lid] = {"box": [x0, y0, x1, y1], "k": k}
        print(lid, index[lid])
    (DEPTH / "layers" / "index.json").write_text(json.dumps(index, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
