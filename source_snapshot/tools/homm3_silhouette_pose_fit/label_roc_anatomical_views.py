#!/usr/bin/env python3
"""Add readable anatomical names to the already-rendered Roc bind views."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--views", type=Path, required=True)
    ap.add_argument("--roles", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    roles = json.loads(args.roles.read_text(encoding="utf-8"))["bones"]
    args.out.mkdir(parents=True, exist_ok=True)
    font = ImageFont.load_default()
    colors = {
        "left": (255, 40, 190),
        "right": (80, 235, 80),
        "body": (40, 220, 240),
        "tail": (255, 175, 20),
        "leg": (255, 220, 40),
    }
    for view in ("profile", "front", "top"):
        projection = json.loads((args.views / f"anat_proj_{view}.json").read_text(encoding="utf-8"))
        image = Image.open(args.views / f"labeled_anat_{view}.png").convert("RGB")
        draw = ImageDraw.Draw(image)
        for bone, point in projection["bones"].items():
            role = roles[bone]
            name = role["name"].replace("_", " ")
            short = name[:22]
            if "left_" in name:
                color = colors["left"]
            elif "right_" in name:
                color = colors["right"]
            elif "tail" in name:
                color = colors["tail"]
            elif "leg" in name or "knee" in name or "tars" in name or "talon" in name:
                color = colors["leg"]
            else:
                color = colors["body"]
            x, y = int(round(point["px"])), int(round(point["py"]))
            draw.ellipse((x - 3, y - 3, x + 3, y + 3), fill=color, outline=(0, 0, 0))
            label = f"{bone.replace('Bone_', '')} {short}"
            tx, ty = x + 5, y - 6
            draw.rectangle((tx - 1, ty - 1, tx + 7 * len(label), ty + 10), fill=(8, 8, 10))
            draw.text((tx, ty), label, fill=color, font=font)
        image.save(args.out / f"named_{view}.png")
    print(json.dumps({"ok": True, "out": str(args.out), "views": 3}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
