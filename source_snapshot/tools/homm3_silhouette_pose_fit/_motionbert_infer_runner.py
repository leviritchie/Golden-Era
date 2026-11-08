#!/usr/bin/env python3
"""
Windows-safe MotionBERT wild pose3d runner (no render_and_save / smplx / ipdb).

Invoked from motionbert_lift_clip.py with cwd = tools/third_party/MotionBERT.
"""
from __future__ import annotations

import argparse
import os
import sys

import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import DataLoader

# Ensure repo root on path when launched by absolute script path.
HERE = os.path.dirname(os.path.abspath(__file__))
MB_ROOT = os.path.abspath(os.path.join(HERE, "..", "third_party", "MotionBERT"))
if MB_ROOT not in sys.path:
    sys.path.insert(0, MB_ROOT)
os.chdir(MB_ROOT)

from lib.data.dataset_wild import WildDetDataset  # noqa: E402
from lib.utils.learning import load_backbone  # noqa: E402
from lib.utils.tools import get_config  # noqa: E402
from lib.utils.utils_data import flip_data  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--evaluate", required=True)
    ap.add_argument("--json_path", required=True)
    ap.add_argument("--vid_path", required=True)
    ap.add_argument("--out_path", required=True)
    ap.add_argument("--clip_len", type=int, default=243)
    ap.add_argument("--pixel", action="store_true")
    ap.add_argument("--focus", type=int, default=None)
    opts = ap.parse_args()

    args = get_config(opts.config)
    model_backbone = load_backbone(args)
    if torch.cuda.is_available():
        model_backbone = nn.DataParallel(model_backbone)
        model_backbone = model_backbone.cuda()

    print("Loading checkpoint", opts.evaluate, flush=True)
    checkpoint = torch.load(opts.evaluate, map_location=lambda storage, loc: storage, weights_only=False)
    model_backbone.load_state_dict(checkpoint["model_pos"], strict=True)
    model_pos = model_backbone
    model_pos.eval()

    import imageio

    vid = imageio.get_reader(opts.vid_path, "ffmpeg")
    vid_size = vid.get_meta_data()["size"]  # (w, h)
    vid.close()
    os.makedirs(opts.out_path, exist_ok=True)

    if opts.pixel:
        wild_dataset = WildDetDataset(
            opts.json_path,
            clip_len=opts.clip_len,
            vid_size=vid_size,
            scale_range=None,
            focus=opts.focus,
        )
    else:
        wild_dataset = WildDetDataset(
            opts.json_path,
            clip_len=opts.clip_len,
            scale_range=[1, 1],
            focus=opts.focus,
        )

    loader = DataLoader(
        wild_dataset,
        batch_size=1,
        shuffle=False,
        num_workers=0,
        pin_memory=torch.cuda.is_available(),
        drop_last=False,
    )

    results_all = []
    with torch.no_grad():
        for batch_input in loader:
            if torch.cuda.is_available():
                batch_input = batch_input.cuda()
            if args.no_conf:
                batch_input = batch_input[:, :, :, :2]
            if args.flip:
                batch_input_flip = flip_data(batch_input)
                predicted_3d_pos_1 = model_pos(batch_input)
                predicted_3d_pos_flip = model_pos(batch_input_flip)
                predicted_3d_pos_2 = flip_data(predicted_3d_pos_flip)
                predicted_3d_pos = (predicted_3d_pos_1 + predicted_3d_pos_2) / 2.0
            else:
                predicted_3d_pos = model_pos(batch_input)
            if args.rootrel:
                predicted_3d_pos[:, :, 0, :] = 0
            else:
                predicted_3d_pos[:, 0, 0, 2] = 0
            if args.gt_2d:
                predicted_3d_pos[..., :2] = batch_input[..., :2]
            results_all.append(predicted_3d_pos.cpu().numpy())

    results_all = np.hstack(results_all)
    results_all = np.concatenate(results_all)
    if opts.pixel:
        results_all = results_all * (min(vid_size) / 2.0)
        results_all[:, :, :2] = results_all[:, :, :2] + np.array(vid_size) / 2.0
    out_npy = os.path.join(opts.out_path, "X3D.npy")
    np.save(out_npy, results_all)
    print(f"[motionbert-runner] saved {out_npy} shape={results_all.shape}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
