#!/usr/bin/env python3
"""Build a simultaneous Roc sprite reference sheet for landmark correction.

The existing keypoints are shown only as a diagnostic overlay.  The sheet is
not an authority: its purpose is to expose which pixels move together across
the clip before new visible anchors are authored.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--frames", type=Path, required=True)
    ap.add_argument("--keypoints", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--indices", default="0,3,6,9,12,15,18,21,24,27,29")
    args = ap.parse_args()

    data = json.loads(args.keypoints.read_text(encoding="utf-8"))
    by_frame = {int(f["frame"]): f for f in data["frames"]}
    indices = [int(v) for v in args.indices.split(",") if v.strip()]
    tile_w, tile_h = 450, 400
    cols = 3
    rows = (len(indices) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * tile_w, rows * tile_h), (12, 12, 16))
    font = ImageFont.load_default()

    colors = {
        "Bone_028": (255, 230, 60),  # beak tip
        "Bone_017": (40, 230, 240),  # occiput
        "Bone_002": (40, 230, 240),  # shoulder pivot
        "Bone_004": (255, 160, 40),  # tail tip candidate
        "Bone_020": (255, 50, 200),  # near wing elbow
        "Bone_023": (80, 240, 90),  # far wing elbow
        "Bone_007": (255, 235, 50),  # near talon
        "Bone_012": (255, 150, 40),  # far talon
    }

    for tile, index in enumerate(indices):
        source = args.frames / f"{index:02d}.png"
        rgba = Image.open(source).convert("RGBA")
        bg = Image.new("RGBA", rgba.size, (32, 32, 32, 255))
        image = Image.alpha_composite(bg, rgba).convert("RGB")
        image.thumbnail((tile_w - 12, tile_h - 36), Image.Resampling.NEAREST)
        x0 = (tile % cols) * tile_w
        y0 = (tile // cols) * tile_h
        px = x0 + (tile_w - image.width) // 2
        py = y0 + 28 + (tile_h - 28 - image.height) // 2
        sheet.paste(image, (px, py))
        draw = ImageDraw.Draw(sheet)
        draw.rectangle((x0, y0, x0 + tile_w - 1, y0 + tile_h - 1), outline=(70, 70, 80))
        draw.text((x0 + 8, y0 + 8), f"frame {index:02d}  multi-frame reference", fill=(245, 245, 245), font=font)

        frame = by_frame[index]
        sx = image.width / 1350.0
        sy = image.height / 1200.0
        for edge in data["edges"]:
            a = frame["joints"].get(edge["parentName"])
            b = frame["joints"].get(edge["childName"])
            if not a or not b:
                continue
            p1 = (px + a["x"] * sx, py + a["y"] * sy)
            p2 = (px + b["x"] * sx, py + b["y"] * sy)
            draw.line((p1, p2), fill=(100, 100, 110), width=1)
        for name, point in frame["joints"].items():
            x = px + point["x"] * sx
            y = py + point["y"] * sy
            color = colors.get(name, (120, 120, 130))
            radius = 3 if name in colors else 2
            draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=color, outline=(0, 0, 0))

    args.out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(args.out)
    print(json.dumps({"ok": True, "out": str(args.out), "frames": indices}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
