#!/usr/bin/env python3
"""Render a conservative frame-00 Roc placement after multi-frame review.

Visible chains are drawn as solid.  The proximal legs are deliberately drawn
as dashed, low-confidence occluded chains: the flight feathers do not prove
that those pixels are talons, and the old overlay incorrectly presented them
as visible anatomy.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def dashed(draw, a, b, fill, width=4, dash=10, gap=6):
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    length = max((dx * dx + dy * dy) ** 0.5, 1.0)
    ux, uy = dx / length, dy / length
    pos = 0.0
    while pos < length:
        end = min(pos + dash, length)
        draw.line((ax + ux * pos, ay + uy * pos, ax + ux * end, ay + uy * end), fill=fill, width=width)
        pos += dash + gap


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--frame", type=Path, required=True)
    ap.add_argument("--keypoints", type=Path, required=True)
    ap.add_argument("--roles", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    rgba = Image.open(args.frame).convert("RGBA")
    bg = Image.new("RGBA", rgba.size, (32, 32, 32, 255))
    image = Image.alpha_composite(bg, rgba).convert("RGB")
    data = json.loads(args.keypoints.read_text(encoding="utf-8"))
    roles = json.loads(args.roles.read_text(encoding="utf-8"))["bones"]
    frame = data["frames"][0]
    points = {name: (int(round(p["x"])), int(round(p["y"]))) for name, p in frame["joints"].items()}
    font = ImageFont.load_default()

    solid_prefixes = ("body_", "thorax_", "pectoral_", "shoulder_", "cervical_", "occiput", "upper_beak", "lower_beak", "beak_tip", "tail_")
    solid_wings = ("wing_", "primary_fan_")
    colors = {
        "tail": (255, 170, 25),
        "wing_near": (255, 45, 195),
        "wing_far": (80, 235, 90),
        "body": (40, 220, 240),
        "legs": (255, 205, 45),
    }

    def kind(name: str) -> str:
        role = roles[name]["name"]
        if "tail" in role:
            return "tail"
        if role.startswith("left_"):
            return "wing_near" if "wing" in role or "primary" in role else "legs"
        if role.startswith("right_"):
            return "wing_far" if "wing" in role or "primary" in role else "legs"
        return "body"

    def is_solid(name: str) -> bool:
        role = roles[name]["name"]
        return role.startswith(solid_prefixes) or role.startswith(solid_wings)

    def label(canvas, xy, text, color, anchor="la"):
        draw = ImageDraw.Draw(canvas)
        x, y = xy
        bbox = draw.textbbox((x, y), text, font=font, anchor=anchor)
        draw.rectangle((bbox[0] - 2, bbox[1] - 1, bbox[2] + 2, bbox[3] + 1), fill=(7, 7, 10))
        draw.text((x, y), text, fill=color, font=font, anchor=anchor)

    draw = ImageDraw.Draw(image)
    for edge in data["edges"]:
        parent, child = edge["parentName"], edge["childName"]
        if parent not in points or child not in points:
            continue
        color = colors[kind(child)]
        if is_solid(parent) and is_solid(child):
            draw.line((*points[parent], *points[child]), fill=color, width=5)
        else:
            dashed(draw, points[parent], points[child], (190, 170, 55), width=4)

    # Keep the visible placement readable.  The small labels identify anchors;
    # the full numbered/anatomical audit remains in the separate named sheet.
    anchors = [
        ("Bone_028", "beak tip"),
        ("Bone_017", "occiput"),
        ("Bone_002", "shoulder pivot"),
        ("Bone_004", "tail tip"),
        ("Bone_020", "near wing elbow"),
        ("Bone_023", "far wing elbow"),
    ]
    for name, text in anchors:
        color = colors[kind(name)]
        x, y = points[name]
        draw.ellipse((x - 7, y - 7, x + 7, y + 7), fill=color, outline=(0, 0, 0), width=2)
        label(image, (x + 11, y - 10), text, color)

    for name, p in points.items():
        if "femur" in roles[name]["name"] or "knee" in roles[name]["name"] or "tibiotarsus" in roles[name]["name"] or "tarsometatarsus" in roles[name]["name"] or "talon" in roles[name]["name"]:
            draw.ellipse((p[0] - 4, p[1] - 4, p[0] + 4, p[1] + 4), fill=(255, 205, 45), outline=(0, 0, 0))
    label(image, (16, 18), "Roc frame 00 - multi-frame corrected placement", (245, 245, 245))
    label(image, (16, 38), "solid = visible correspondence; dashed = occluded/inferred, not a talon claim", (220, 200, 110))

    args.out.parent.mkdir(parents=True, exist_ok=True)
    image.save(args.out)
    crop_box = (430, 540, 960, 850)
    crop = image.crop(crop_box).resize((1060, 620), Image.Resampling.NEAREST)
    crop_path = args.out.with_name(args.out.stem + "_crop.png")
    crop.save(crop_path)
    report = {
        "frame": 0,
        "solidChains": "body/head/beak/tail and near/far wing chains",
        "occludedChains": "both leg chains",
        "basis": "simultaneous reference frames 00,03,06,09,12,15,18,21,24,27,29",
        "proof": "generated placement preview; not yet a 3D transfer or runtime proof",
    }
    report_path = args.out.with_suffix(".json")
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "out": str(args.out), "crop": str(crop_path), "report": str(report_path)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
