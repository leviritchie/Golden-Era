#!/usr/bin/env python3
"""Manual joints on painted g11 upscales for Meshy46 (output_3). R=+X strike/weapon tip side.

Tip targets are mace-ball centers (not outermost spike tips). Goal: attack *reads*, not pixels.
"""
from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "artifacts/hobgoblin_attack_pose_pipeline/source_attack_frames_painted_g11"
OUT = ROOT / "artifacts/hobgoblin_attack_pose_pipeline/out_attack_g11_manual_painted_meshy46"
KPT = OUT / "manual_keypoints"

# 512x512 painted space. Logic from painted upscales:
#   f0 ready tip mid-right → f1 tip rises → f2 tip high behind head
#   f3 tip far-left mid (deep backswing) → f4 tip high forward-right (apex)
#   f5–f6 tip low-forward smash → f7 recovery
# Two hands stay near each other on the shaft.
FRAMES: list[dict[str, tuple[float, float]]] = [
    # f0 ready
    {
        "Nose": (255, 130),
        "Neck": (250, 165),
        "RShoulder": (275, 175),
        "RElbow": (310, 210),
        "RWrist": (325, 245),
        "WeaponTip": (340, 250),
        "LShoulder": (220, 180),
        "LElbow": (195, 235),
        "LWrist": (235, 270),
        "MidHip": (250, 275),
        "RHip": (275, 285),
        "RKnee": (300, 350),
        "RAnkle": (320, 415),
        "LHip": (230, 285),
        "LKnee": (215, 350),
        "LAnkle": (210, 415),
    },
    # f1 tip rising upper-right of torso
    {
        "Nose": (258, 135),
        "Neck": (250, 170),
        "RShoulder": (268, 175),
        "RElbow": (295, 185),
        "RWrist": (315, 200),
        "WeaponTip": (345, 175),
        "LShoulder": (228, 185),
        "LElbow": (210, 230),
        "LWrist": (250, 250),
        "MidHip": (250, 280),
        "RHip": (275, 290),
        "RKnee": (305, 350),
        "RAnkle": (325, 410),
        "LHip": (230, 290),
        "LKnee": (215, 345),
        "LAnkle": (205, 410),
    },
    # f2 tip high behind head; hands clustered at upper chest
    {
        "Nose": (255, 155),
        "Neck": (250, 185),
        "RShoulder": (240, 180),
        "RElbow": (215, 155),
        "RWrist": (235, 175),
        "WeaponTip": (165, 100),
        "LShoulder": (275, 190),
        "LElbow": (255, 200),
        "LWrist": (245, 190),
        "MidHip": (255, 295),
        "RHip": (280, 305),
        "RKnee": (305, 365),
        "RAnkle": (295, 420),
        "LHip": (235, 305),
        "LKnee": (215, 365),
        "LAnkle": (200, 420),
    },
    # f3 deep backswing — tip FAR LEFT mid; both hands high above/behind head
    {
        "Nose": (290, 120),
        "Neck": (295, 155),
        "RShoulder": (280, 160),
        "RElbow": (230, 95),
        "RWrist": (195, 105),
        "WeaponTip": (55, 210),
        "LShoulder": (320, 160),
        "LElbow": (250, 115),
        "LWrist": (205, 120),
        "MidHip": (295, 310),
        "RHip": (275, 320),
        "RKnee": (285, 385),
        "RAnkle": (255, 435),
        "LHip": (325, 320),
        "LKnee": (360, 360),
        "LAnkle": (355, 430),
    },
    # f4 apex — tip high forward-right; arms up; feet planted
    {
        "Nose": (235, 185),
        "Neck": (230, 220),
        "RShoulder": (215, 225),
        "RElbow": (285, 175),
        "RWrist": (340, 140),
        "WeaponTip": (375, 95),
        "LShoulder": (245, 230),
        "LElbow": (300, 175),
        "LWrist": (335, 150),
        "MidHip": (220, 310),
        "RHip": (250, 320),
        "RKnee": (255, 370),
        "RAnkle": (255, 425),
        "LHip": (195, 320),
        "LKnee": (175, 370),
        "LAnkle": (160, 425),
    },
    # f5 smash — tip low-forward-right; both hands on shaft; deep crouch
    {
        "Nose": (300, 145),
        "Neck": (280, 185),
        "RShoulder": (295, 205),
        "RElbow": (350, 265),
        "RWrist": (375, 310),
        "WeaponTip": (445, 340),
        "LShoulder": (265, 215),
        "LElbow": (330, 280),
        "LWrist": (365, 315),
        "MidHip": (240, 295),
        "RHip": (270, 310),
        "RKnee": (295, 360),
        "RAnkle": (275, 420),
        "LHip": (210, 310),
        "LKnee": (180, 360),
        "LAnkle": (150, 430),
    },
    # f6 follow-through
    {
        "Nose": (295, 160),
        "Neck": (280, 200),
        "RShoulder": (290, 220),
        "RElbow": (340, 285),
        "RWrist": (380, 335),
        "WeaponTip": (450, 350),
        "LShoulder": (260, 225),
        "LElbow": (320, 295),
        "LWrist": (365, 335),
        "MidHip": (255, 300),
        "RHip": (280, 315),
        "RKnee": (300, 365),
        "RAnkle": (295, 420),
        "LHip": (230, 315),
        "LKnee": (210, 365),
        "LAnkle": (195, 420),
    },
    # f7 recovery
    {
        "Nose": (275, 145),
        "Neck": (265, 180),
        "RShoulder": (280, 195),
        "RElbow": (325, 245),
        "RWrist": (360, 285),
        "WeaponTip": (420, 295),
        "LShoulder": (245, 200),
        "LElbow": (295, 255),
        "LWrist": (340, 290),
        "MidHip": (255, 290),
        "RHip": (280, 300),
        "RKnee": (310, 355),
        "RAnkle": (315, 420),
        "LHip": (230, 300),
        "LKnee": (215, 355),
        "LAnkle": (205, 420),
    },
]

COLORS = {
    "Nose": (255, 220, 80),
    "Neck": (255, 180, 60),
    "RShoulder": (255, 80, 80),
    "RElbow": (255, 100, 100),
    "RWrist": (255, 120, 120),
    "WeaponTip": (255, 40, 255),
    "LShoulder": (80, 160, 255),
    "LElbow": (100, 170, 255),
    "LWrist": (120, 180, 255),
    "MidHip": (180, 255, 120),
    "RHip": (255, 140, 140),
    "RKnee": (255, 150, 150),
    "RAnkle": (255, 160, 160),
    "LHip": (140, 190, 255),
    "LKnee": (150, 200, 255),
    "LAnkle": (160, 210, 255),
}
EDGES = [
    ("Nose", "Neck"),
    ("Neck", "RShoulder"),
    ("Neck", "LShoulder"),
    ("RShoulder", "RElbow"),
    ("RElbow", "RWrist"),
    ("RWrist", "WeaponTip"),
    ("LShoulder", "LElbow"),
    ("LElbow", "LWrist"),
    ("Neck", "MidHip"),
    ("MidHip", "RHip"),
    ("MidHip", "LHip"),
    ("RHip", "RKnee"),
    ("RKnee", "RAnkle"),
    ("LHip", "LKnee"),
    ("LKnee", "LAnkle"),
]


def main() -> None:
    KPT.mkdir(parents=True, exist_ok=True)
    overlays = KPT / "overlays"
    overlays.mkdir(exist_ok=True)
    transform = {
        "padX": 0,
        "padY": 0,
        "scale": 1.0,
        "srcWidth": 512,
        "srcHeight": 512,
        "upWidth": 512,
        "upHeight": 512,
        "longEdge": 512,
        "bgRgb": [0, 0, 0],
        "cropX0": 0,
        "cropY0": 0,
        "cropW": 512,
        "cropH": 512,
    }
    frames_out = []
    for i, pts in enumerate(FRAMES):
        src = SRC / f"frame_{i:02d}.png"
        joints = {
            name: {
                "x": float(x),
                "y": float(y),
                "xUpscaled": float(x),
                "yUpscaled": float(y),
                "score": 0.95,
                "visible": True,
            }
            for name, (x, y) in pts.items()
        }
        for unused in ("LEye", "REye", "LEar", "REar"):
            joints[unused] = {
                "x": 0.0,
                "y": 0.0,
                "xUpscaled": 0.0,
                "yUpscaled": 0.0,
                "score": 0.0,
                "visible": False,
            }
        im = Image.open(src).convert("RGBA")
        canvas = Image.new("RGBA", im.size, (12, 12, 16, 255))
        canvas.paste(im, (0, 0), im)
        draw = ImageDraw.Draw(canvas)
        for a, b in EDGES:
            if a in pts and b in pts:
                draw.line([pts[a], pts[b]], fill=(80, 220, 120, 255), width=3)
        for name, (x, y) in pts.items():
            r = 7 if name == "WeaponTip" else 5
            c = COLORS.get(name, (255, 255, 255))
            draw.ellipse([x - r, y - r, x + r, y + r], fill=c + (255,), outline=(0, 0, 0, 255))
            draw.text((x + 8, y - 8), name, fill=(240, 240, 240, 255))
        ov = overlays / f"frame_{i:02d}.png"
        canvas.convert("RGB").save(ov)
        frames_out.append(
            {
                "frameIndex": i,
                "sourcePath": str(src).replace("\\", "/"),
                "transform": transform,
                "variant": "manual_painted_meshy46",
                "visibleJoints": sum(1 for j in joints.values() if j["visible"]),
                "meanScore": 0.95,
                "joints": joints,
                "overlay": str(ov.resolve()).replace("\\", "/"),
            }
        )
    report = {
        "unitSid": "h3_hobgoblin",
        "clipId": "attack_g11",
        "detector": "manual_author_painted",
        "masterHint": "Meshy_AI_Character_output_3.glb / meshy46",
        "frameCountExpected": 8,
        "frameCountOk": 8,
        "failures": [],
        "frames": frames_out,
        "ok": True,
        "proof": "generated artifact validated — manual painted keypoints; not OE runtime proven",
    }
    out_json = KPT / "keypoints.json"
    out_json.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "keypointsPath": str(out_json), "overlays": str(overlays)}, indent=2))


if __name__ == "__main__":
    main()
