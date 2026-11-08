#!/usr/bin/env python3
"""Render the named Roc bind placement over authored RIFE frame 00."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def color_for(name: str):
    if name.startswith("left_wing") or name.startswith("left_primary"):
        return (255, 35, 190)
    if name.startswith("right_wing") or name.startswith("right_primary"):
        return (70, 235, 80)
    if name.startswith("left_") and ("femur" in name or "knee" in name or "tars" in name or "talon" in name):
        return (255, 230, 35)
    if name.startswith("right_") and ("femur" in name or "knee" in name or "tars" in name or "talon" in name):
        return (255, 150, 30)
    if "tail" in name:
        return (255, 170, 25)
    return (40, 220, 240)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--frame", type=Path, required=True)
    ap.add_argument("--keypoints", type=Path, required=True)
    ap.add_argument("--roles", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    # Do not convert RGBA directly to RGB: that preserves the old RGB payload
    # of alpha-zero shadow pixels and makes a correctly culled shadow visible
    # again. Composite against the intended battle-sprite background first.
    rgba = Image.open(args.frame).convert("RGBA")
    background = Image.new("RGBA", rgba.size, (32, 32, 32, 255))
    image = Image.alpha_composite(background, rgba).convert("RGB")
    keypoints = json.loads(args.keypoints.read_text(encoding="utf-8"))
    roles = json.loads(args.roles.read_text(encoding="utf-8"))["bones"]
    frame = keypoints["frames"][0]
    joints = {name: (int(round(point["x"])), int(round(point["y"]))) for name, point in frame["joints"].items()}
    edges = keypoints["edges"]
    font = ImageFont.load_default()

    def draw_sheet(canvas, scale=1.0, origin=(0, 0), crop_box=None):
        draw = ImageDraw.Draw(canvas)
        ox, oy = origin

        def pos(name):
            x, y = joints[name]
            return int(round((x - ox) * scale)), int(round((y - oy) * scale))

        for edge in edges:
            parent, child = edge["parentName"], edge["childName"]
            if parent not in joints or child not in joints:
                continue
            p1, p2 = pos(parent), pos(child)
            role = roles[child]
            draw.line((p1, p2), fill=color_for(role["name"]), width=max(2, int(round(3 * scale)))
                      )

        for number, name in enumerate(joints):
            x, y = pos(name)
            role = roles[name]
            color = color_for(role["name"])
            draw.ellipse((x - 5, y - 5, x + 5, y + 5), fill=color, outline=(0, 0, 0), width=2)
            label = f"{name.replace('Bone_', '')} {role['name'].replace('_', ' ')}"
            # Put labels mostly outward from the body center so the named view
            # stays readable without changing the joint positions.
            dx = 9 if x < canvas.width * 0.52 else -9 - max(65, int(len(label) * 6.1))
            dy = -8 if y > canvas.height * 0.55 else 5
            tx, ty = x + dx, y + dy
            bbox = draw.textbbox((tx, ty), label, font=font)
            draw.rectangle((bbox[0] - 2, bbox[1] - 1, bbox[2] + 2, bbox[3] + 1), fill=(8, 8, 12))
            draw.text((tx, ty), label, fill=color, font=font)

        title = "Roc frame 00 - named bind placement (authored 2D joint locations)"
        draw.rectangle((8, 8, 650, 25), fill=(8, 8, 12))
        draw.text((12, 12), title, fill=(245, 245, 245), font=font)

    full = image.copy()
    draw_sheet(full)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    full.save(args.out)

    bbox = [462, 567, 938, 830]
    margin = 55
    crop = image.crop((bbox[0] - margin, bbox[1] - margin, bbox[2] + margin, bbox[3] + margin))
    scale = 2.2
    crop = crop.resize((int(crop.width * scale), int(crop.height * scale)), Image.Resampling.NEAREST)
    crop_path = args.out.with_name(args.out.stem + "_crop.png")
    draw_sheet(crop, scale=scale, origin=(bbox[0] - margin, bbox[1] - margin))
    crop.save(crop_path)
    print(json.dumps({"ok": True, "full": str(args.out), "crop": str(crop_path), "joints": len(joints)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
