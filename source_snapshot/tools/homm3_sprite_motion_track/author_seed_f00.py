#!/usr/bin/env python3
"""Author editable frame-0 seed joints on the NN-upscaled g11 sprite."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "artifacts/hobgoblin_attack_pose_pipeline/source_attack_frames/canonical_group_11_nn_upscale/frame_00.png"
OUT = ROOT / "artifacts/hobgoblin_attack_pose_pipeline/out_sprite_motion_track_g11/seed/seed_joints_f00.json"

# Content-fraction anchors (ready stance, mace across body, tip screen-right).
# R* = strike side toward WeaponTip (matches bone_roles_grip_no_hip_yaw).
FRACS = {
    "Nose": (0.48, 0.06),
    "Neck": (0.50, 0.16),
    "RShoulder": (0.66, 0.22),
    "RElbow": (0.74, 0.34),
    "RWrist": (0.78, 0.42),
    "WeaponTip": (0.92, 0.30),
    "LShoulder": (0.34, 0.24),
    "LElbow": (0.42, 0.40),
    "LWrist": (0.58, 0.50),
    "MidHip": (0.50, 0.50),
    "RHip": (0.60, 0.54),
    "RKnee": (0.62, 0.72),
    "RAnkle": (0.60, 0.93),
    "LHip": (0.40, 0.54),
    "LKnee": (0.38, 0.72),
    "LAnkle": (0.40, 0.94),
}


def main() -> int:
    im = Image.open(SRC).convert("RGBA")
    arr = np.asarray(im)
    h, w = arr.shape[:2]
    ys, xs = np.where(arr[:, :, 3] > 8)
    if len(xs) == 0:
        raise SystemExit("empty alpha on seed sprite")
    x0, y0, x1, y1 = int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())
    cw, ch = x1 - x0 + 1, y1 - y0 + 1
    joints = {}
    for name, (fx, fy) in FRACS.items():
        x = float(x0 + fx * cw)
        y = float(y0 + fy * ch)
        if not (x0 - 2 <= x <= x1 + 2 and y0 - 2 <= y <= y1 + 2):
            raise SystemExit(f"{name} outside content bbox: {(x, y)}")
        joints[name] = {"x": x, "y": y, "score": 1.0, "visible": True}
    seed = {
        "ok": True,
        "frameIndex": 0,
        "spritePath": str(SRC).replace("\\", "/"),
        "srcWidth": w,
        "srcHeight": h,
        "contentBBox": [x0, y0, x1, y1],
        "joints": joints,
        "jointSet": list(joints.keys()),
        "notes": (
            "Editable frame-0 seed on NN-upscaled g11. R*=strike/mace-tip side. "
            "Edit pixel x/y then re-run track_joints_lk.py."
        ),
        "proof": "generated artifact validated — manual seed on NN sprite; not mocap",
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(seed, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "out": str(OUT), "contentBBox": [x0, y0, x1, y1]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
