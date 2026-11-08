#!/usr/bin/env python3
"""Render fixed pipeline motion through an explicitly selected source profile."""
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

from asset_profiles import get_profile  # noqa: E402
from corpus_motion import load_motion  # noqa: E402
from gpu_cascade_batch_lock import cascade_batch_lock  # noqa: E402
from run_skin_weight_pilot import _load_frozen_prep, skin_with, source_images  # noqa: E402
from skin_camera_registration import _basis_yup, _bbox_scale_offset, _camera, _target_bbox  # noqa: E402
from skin_image_objective import SkinImageRenderer  # noqa: E402


def render(skin, worlds, camera, resolution):
    with cascade_batch_lock(REPO), torch.no_grad():
        transforms = torch.as_tensor(worlds @ skin["inverseBind"][None], dtype=torch.float32, device="cuda")
        rest = torch.as_tensor(np.column_stack((skin["vertices"], np.ones(len(skin["vertices"]))),), dtype=torch.float32, device="cuda")
        candidates = torch.einsum("fjkl,vl->fvjk", transforms[:, :, :3], rest)
        posed = skin_with(candidates, torch.as_tensor(skin["weights"], dtype=torch.float32, device="cuda"))
        renderer = SkinImageRenderer(skin["triangles"], skin["uvs"], skin["albedo"], camera, resolution)
        rgb, _ = renderer.render(posed)
        return rgb.detach().cpu().numpy()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--asset", required=True)
    parser.add_argument("--corpus", required=True, type=Path)
    parser.add_argument("--calibration", required=True, type=Path)
    parser.add_argument("--candidate", required=True, type=Path)
    parser.add_argument("--yaw", required=True, type=float)
    parser.add_argument("--pitch", required=True, type=float)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--resolution", type=int, default=224)
    args = parser.parse_args()
    if args.out.exists():
        raise FileExistsError(args.out)
    _, skin = _load_frozen_prep(args.asset)
    candidate = np.load(args.candidate, allow_pickle=False)
    names = [x.decode("utf-8") if isinstance(x, bytes) else str(x) for x in candidate["names"]]
    if names != list(skin["names"]):
        raise ValueError("candidate joint ordering differs from frozen skin")
    skin["vertices"] = np.asarray(candidate["vertices"], dtype=np.float64)
    skin["weights"] = np.asarray(candidate["weights"], dtype=np.float64)
    corpus = json.loads(args.corpus.read_text(encoding="utf-8"))
    reference = np.asarray(json.loads(args.calibration.read_text(encoding="utf-8"))["referencePositions"], dtype=np.float64)
    entries = [entry for entry in corpus["captures"] if entry["key"] in ("g00_move", "g02_idle")]
    if len(entries) != 2:
        raise ValueError("expected g00_move and g02_idle")
    first = Path(entries[0]["frames"][0])
    with Image.open(first) as image:
        source_size = image.size
    side = max(source_size)
    source_crop = {"left": -((side - source_size[0]) // 2), "top": -((side - source_size[1]) // 2), "size": side}
    first_target = source_images([first], source_crop, args.resolution)
    target_alpha = first_target[1][0].detach().cpu().numpy()
    basis = _basis_yup(args.yaw, args.pitch)
    scale, offset = _bbox_scale_offset(skin["vertices"], basis, _target_bbox(target_alpha[..., 0]))
    camera = _camera(basis, scale=scale, offset=offset, vertices=skin["vertices"], source_size=source_size,
                     source_crop=source_crop, resolution=args.resolution, yaw_deg=args.yaw, pitch_deg=args.pitch)
    profile = get_profile(args.asset)
    frames = []
    for entry in entries:
        with np.load(entry["capture"], allow_pickle=False) as raw:
            motion = load_motion(raw, entry, corpus, skin, reference, profile["wholeBodyHubs"])
        mesh = render(skin, np.asarray(motion["jointWorld"], dtype=np.float64), camera, args.resolution)
        target = source_images([Path(path) for path in entry["frames"]], source_crop, args.resolution)[0].detach().cpu().numpy()
        for index, (source, predicted) in enumerate(zip(target, mesh)):
            panel = Image.new("RGB", (args.resolution * 2, args.resolution + 28), (10, 10, 14))
            draw = ImageDraw.Draw(panel)
            draw.text((4, 4), f"{args.asset} {entry['key']} f{index:02d} y{args.yaw:g} p{args.pitch:g}", fill="white")
            panel.paste(Image.fromarray(np.uint8(np.clip(source, 0, 1) * 255)), (0, 28))
            panel.paste(Image.fromarray(np.uint8(np.clip(predicted, 0, 1) * 255)), (args.resolution, 28))
            draw.text((4, 17), "source", fill=(190, 190, 205)); draw.text((args.resolution + 4, 17), "fixed-profile mesh", fill=(190, 190, 205))
            frames.append(panel)
    args.out.mkdir(parents=True)
    gif = args.out / "preview.gif"; frames[0].save(gif, save_all=True, append_images=frames[1:], duration=85, loop=0)
    sheet = Image.new("RGB", (frames[0].width, frames[0].height * min(8, len(frames))))
    for index, frame in enumerate(frames[:8]): sheet.paste(frame, (0, index * frame.height))
    sheet.save(args.out / "contact.png")
    (args.out / "report.json").write_text(json.dumps({"proof": "generated candidate fixed-profile motion preview", "camera": camera, "clips": [e["key"] for e in entries]}, indent=2, default=lambda v: v.tolist() if isinstance(v, np.ndarray) else float(v)) + "\n", encoding="utf-8")
    print(gif)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
