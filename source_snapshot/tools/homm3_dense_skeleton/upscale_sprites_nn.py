#!/usr/bin/env python3
"""
Temporally stable traditional upscale of original g11 sprites.

Shared union content crop across the clip → integer nearest-neighbor enlarge.
No GenAI. Same crop/scale for every frame so motion does not swim.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

TOOL = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOL))
from constants import OUT, SRC, SRC_UPSCALED  # noqa: E402


def _alpha_bbox(im: Image.Image, *, thresh: int = 8) -> tuple[int, int, int, int]:
    arr = np.asarray(im.convert("RGBA"))
    a = arr[:, :, 3]
    ys, xs = np.where(a > thresh)
    if len(xs) == 0:
        raise RuntimeError("empty alpha — cannot crop")
    return int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--src", type=Path, default=SRC)
    ap.add_argument("--out", type=Path, default=SRC_UPSCALED)
    ap.add_argument(
        "--scale",
        type=int,
        default=0,
        help="Integer nearest scale. 0 = choose so longest content edge ≈ --target-edge",
    )
    ap.add_argument("--target-edge", type=int, default=512, help="Used when --scale=0")
    ap.add_argument("--pad", type=int, default=6, help="Pad around union bbox in source pixels")
    args = ap.parse_args()

    frames = sorted(args.src.glob("frame_*.png"))
    if not frames:
        print(f"no frames in {args.src}", file=sys.stderr)
        return 2

    boxes = []
    sizes = []
    for p in frames:
        with Image.open(p) as im:
            sizes.append(im.size)
            boxes.append(_alpha_bbox(im))
    if len(set(sizes)) != 1:
        raise RuntimeError(f"mixed frame sizes: {set(sizes)}")
    sw, sh = sizes[0]

    ux0 = min(b[0] for b in boxes)
    uy0 = min(b[1] for b in boxes)
    ux1 = max(b[2] for b in boxes)
    uy1 = max(b[3] for b in boxes)
    ux0 = max(0, ux0 - args.pad)
    uy0 = max(0, uy0 - args.pad)
    ux1 = min(sw - 1, ux1 + args.pad)
    uy1 = min(sh - 1, uy1 + args.pad)
    cw = ux1 - ux0 + 1
    ch = uy1 - uy0 + 1

    scale = int(args.scale)
    if scale <= 0:
        scale = max(1, int(round(float(args.target_edge) / float(max(cw, ch)))))
    if scale < 2:
        # Tiny DEF sprites need a real enlarge; fail closed if math says 1x.
        scale = 2

    out_w, out_h = cw * scale, ch * scale
    args.out.mkdir(parents=True, exist_ok=True)
    written = []
    for p in frames:
        with Image.open(p) as im:
            rgba = im.convert("RGBA")
            crop = rgba.crop((ux0, uy0, ux1 + 1, uy1 + 1))
            up = crop.resize((out_w, out_h), Image.Resampling.NEAREST)
            dest = args.out / p.name
            up.save(dest)
            written.append(dest.name)

    meta = {
        "ok": True,
        "method": "shared_union_crop_nearest_neighbor",
        "generator": "traditional",
        "sourceDir": str(args.src).replace("\\", "/"),
        "outDir": str(args.out).replace("\\", "/"),
        "sourceSize": [sw, sh],
        "unionBBox": [ux0, uy0, ux1, uy1],
        "cropSize": [cw, ch],
        "pad": args.pad,
        "scale": scale,
        "outSize": [out_w, out_h],
        "frames": written,
        "proof": "generated artifact validated — temporally stable NN upscale; not GenAI",
    }
    (args.out / "upscale_meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    # Also stash under dense out for the pilot trail.
    (OUT / "source_upscaled_nn_meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(meta, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
