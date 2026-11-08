#!/usr/bin/env python3
"""Draw labeled seed/track joint overlays on NN-upscaled sprites."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "artifacts/hobgoblin_attack_pose_pipeline/out_sprite_motion_track_g11"
SRC = ROOT / "artifacts/hobgoblin_attack_pose_pipeline/source_attack_frames/canonical_group_11_nn_upscale"

EDGES = [
    ("Nose", "Neck"),
    ("Neck", "MidHip"),
    ("Neck", "RShoulder"),
    ("RShoulder", "RElbow"),
    ("RElbow", "RWrist"),
    ("RWrist", "WeaponTip"),
    ("Neck", "LShoulder"),
    ("LShoulder", "LElbow"),
    ("LElbow", "LWrist"),
    ("MidHip", "RHip"),
    ("RHip", "RKnee"),
    ("RKnee", "RAnkle"),
    ("MidHip", "LHip"),
    ("LHip", "LKnee"),
    ("LKnee", "LAnkle"),
]


def _font(size: int):
    try:
        return ImageFont.truetype("arial.ttf", size)
    except OSError:
        return ImageFont.load_default()


def draw_joints(im: Image.Image, joints: dict, *, label: bool = True) -> Image.Image:
    out = im.convert("RGBA").copy()
    draw = ImageDraw.Draw(out)
    stroke = max(2, min(out.size) // 180)
    font = _font(max(10, min(out.size) // 55))
    for a, b in EDGES:
        if a in joints and b in joints:
            pa = (float(joints[a]["x"]), float(joints[a]["y"]))
            pb = (float(joints[b]["x"]), float(joints[b]["y"]))
            draw.line([pa, pb], fill=(0, 255, 255, 255), width=stroke)
    for name, j in joints.items():
        x, y = float(j["x"]), float(j["y"])
        r = stroke + (3 if name == "WeaponTip" else 2)
        col = (255, 140, 0, 255) if name == "WeaponTip" else (255, 255, 0, 255)
        draw.ellipse([x - r, y - r, x + r, y + r], fill=col)
        if label:
            draw.text((x + r + 2, y - r - 2), name, fill=(255, 255, 255, 255), font=font, stroke_width=1, stroke_fill=(0, 0, 0, 255))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--seed", type=Path, default=OUT / "seed" / "seed_joints_f00.json")
    ap.add_argument("--sprite", type=Path, default=SRC / "frame_00.png")
    ap.add_argument("--out", type=Path, default=OUT / "seed" / "seed_overlay_00.png")
    args = ap.parse_args()
    seed = json.loads(args.seed.read_text(encoding="utf-8"))
    joints = seed["joints"] if "joints" in seed else seed
    im = Image.open(args.sprite)
    out = draw_joints(im, joints)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    out.save(args.out)
    print(json.dumps({"ok": True, "out": str(args.out)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
