#!/usr/bin/env python3
"""Shared helpers for LLM eye-authored crusader sprite landmarks."""
from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(r"V:/Games/Olden Era Playtest Tweak")
ART = ROOT / "artifacts/crusader_pose_pipeline"

JOINT_NAMES = [
    "Nose",
    "Neck",
    "RShoulder",
    "RElbow",
    "RWrist",
    "WeaponTip",
    "LShoulder",
    "LElbow",
    "LWrist",
    "MidHip",
    "RHip",
    "RKnee",
    "RAnkle",
    "LHip",
    "LKnee",
    "LAnkle",
]

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

COLORS = {
    "Nose": (255, 80, 80),
    "Neck": (255, 160, 80),
    "MidHip": (255, 255, 80),
    "RShoulder": (80, 255, 120),
    "RElbow": (80, 220, 180),
    "RWrist": (80, 200, 255),
    "WeaponTip": (255, 40, 255),
    "LShoulder": (180, 120, 255),
    "LElbow": (200, 150, 255),
    "LWrist": (220, 180, 255),
    "RHip": (120, 200, 120),
    "RKnee": (100, 180, 100),
    "RAnkle": (80, 160, 80),
    "LHip": (120, 160, 220),
    "LKnee": (100, 140, 200),
    "LAnkle": (80, 120, 180),
}


def joint_dict(xy: dict[str, tuple[int, int]]) -> dict:
    missing = [n for n in JOINT_NAMES if n not in xy]
    if missing:
        raise ValueError(f"missing joints: {missing}")
    extra = [n for n in xy if n not in JOINT_NAMES]
    if extra:
        raise ValueError(f"unknown joints: {extra}")
    return {
        name: {
            "x": float(xy[name][0]),
            "y": float(xy[name][1]),
            "visible": True,
            "score": 1.0,
            "source": "human_eye",
        }
        for name in JOINT_NAMES
    }


def draw_overlay(sprite: Path, joints: dict[str, tuple[int, int]], label: str) -> Image.Image:
    sp = Image.open(sprite).convert("RGBA")
    pad = 24
    canvas = Image.new("RGBA", (sp.width + pad * 2, sp.height + pad * 2), (0, 0, 0, 255))
    canvas.paste(sp, (pad, pad), sp)
    d = ImageDraw.Draw(canvas)

    def pt(n: str) -> tuple[int, int]:
        x, y = joints[n]
        return int(x + pad), int(y + pad)

    for a, b in EDGES:
        pa, pb = pt(a), pt(b)
        d.line([pa, pb], fill=(0, 0, 0), width=5)
        d.line([pa, pb], fill=(0, 255, 90), width=3)
    for name, (x, y) in joints.items():
        p = (int(x + pad), int(y + pad))
        rgb = COLORS.get(name, (255, 255, 255))
        r = 7 if name == "WeaponTip" else 5
        d.ellipse([p[0] - r - 1, p[1] - r - 1, p[0] + r + 1, p[1] + r + 1], fill=(0, 0, 0))
        d.ellipse([p[0] - r, p[1] - r, p[0] + r, p[1] + r], fill=rgb)
        d.text((p[0] + r + 2, p[1] - 6), name, fill=rgb)
    d.text((8, 8), label, fill=(255, 255, 0))
    d.text((8, 24), "human eye-authored landmarks on sprite", fill=(220, 220, 80))
    return canvas.convert("RGB")


def write_authored_clip(
    *,
    clip_id: str,
    frames_dir: Path,
    out_dir: Path,
    frames_xy: list[dict[str, tuple[int, int]]],
    notes: str,
) -> dict:
    sprites = sorted(frames_dir.glob("frame_*.png"))
    if len(sprites) != len(frames_xy):
        raise RuntimeError(
            f"{clip_id}: frame count mismatch sprites={len(sprites)} authored={len(frames_xy)}"
        )
    out_dir.mkdir(parents=True, exist_ok=True)
    overlays = out_dir / "overlays"
    overlays.mkdir(parents=True, exist_ok=True)
    lm = out_dir / "sprite_landmarks"
    lm.mkdir(parents=True, exist_ok=True)

    frames_out = []
    gif_frames = []
    for i, (sp, xy) in enumerate(zip(sprites, frames_xy)):
        im = Image.open(sp)
        w, h = im.size
        frames_out.append(
            {
                "frameIndex": i,
                "ok": True,
                "path": str(sp).replace("\\", "/"),
                "transform": {"srcWidth": int(w), "srcHeight": int(h), "pad": 0},
                "joints": joint_dict(xy),
            }
        )
        overlay = draw_overlay(sp, xy, f"{clip_id} eye-mapped f{i:02d}")
        overlay.save(overlays / f"authored_{i:02d}.png")
        gif_frames.append(overlay)

    gif = out_dir / f"{clip_id}_authored_skeleton.gif"
    gif_frames[0].save(
        gif,
        save_all=True,
        append_images=gif_frames[1:],
        duration=180,
        loop=0,
        optimize=False,
    )
    doc = {
        "ok": True,
        "unitSid": "h3_crusader",
        "clipId": clip_id,
        "method": "human_eye_landmark_authoring",
        "proof": (
            f"authored by inspecting each NN sprite for {clip_id}; "
            "not OE runtime; not mesh projection"
        ),
        "notes": notes,
        "errors": [],
        "frames": frames_out,
    }
    kpt = lm / "keypoints.json"
    kpt.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    return {
        "ok": True,
        "clipId": clip_id,
        "keypoints": str(kpt).replace("\\", "/"),
        "gif": str(gif).replace("\\", "/"),
        "frames": len(frames_out),
    }
