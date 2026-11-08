#!/usr/bin/env python3
"""Draw consensus 2D joints on target sprites for visual proof."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "artifacts/hobgoblin_attack_pose_pipeline/out_dense_skeleton_g11"
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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--keypoints", type=Path, default=OUT / "consensus" / "keypoints.json")
    ap.add_argument("--out-dir", type=Path, default=OUT / "preview")
    args = ap.parse_args()
    kpt = json.loads(args.keypoints.read_text(encoding="utf-8"))
    args.out_dir.mkdir(parents=True, exist_ok=True)
    for fr in kpt["frames"]:
        fi = int(fr["frameIndex"])
        src = Path(fr["path"])
        im = Image.open(src).convert("RGBA")
        draw = ImageDraw.Draw(im)
        joints = fr["joints"]
        stroke = max(2, min(im.size) // 120)
        r_joint = max(3, stroke + 1)
        r_tip = r_joint + 2
        for a, b in EDGES:
            if a in joints and b in joints:
                pa = (joints[a]["x"], joints[a]["y"])
                pb = (joints[b]["x"], joints[b]["y"])
                draw.line([pa, pb], fill=(0, 255, 255, 255), width=stroke)
        for name, j in joints.items():
            r = r_tip if name == "WeaponTip" else r_joint
            x, y = j["x"], j["y"]
            col = (255, 140, 0, 255) if name == "WeaponTip" else (255, 255, 0, 255)
            draw.ellipse([x - r, y - r, x + r, y + r], fill=col)
        out = args.out_dir / f"consensus_overlay_{fi:02d}.png"
        im.save(out)
        print("wrote", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
