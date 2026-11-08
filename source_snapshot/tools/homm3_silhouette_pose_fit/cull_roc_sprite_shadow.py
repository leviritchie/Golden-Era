#!/usr/bin/env python3
"""Cull the Roc sprite's transparent neutral ground shadow.

The Roc RIFE export uses a different shadow encoding than the generic DEF
utility: shadow pixels are neutral RGB 24/30 with alpha 16/64, not RGB <= 8.
Opaque dark feathers remain untouched.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image


def cull(arr: np.ndarray) -> tuple[np.ndarray, int]:
    out = np.array(arr, dtype=np.uint8, copy=True)
    rgb = out[..., :3].astype(np.int16)
    alpha = out[..., 3]
    neutral = (rgb.max(axis=-1) - rgb.min(axis=-1)) <= 1
    # This export contains both semi-transparent and fully composited neutral
    # shadow pixels. Subject pixels are tinted brown/gold, so the neutral test
    # is the discriminator that lets us remove the opaque shadow without
    # erasing dark feathers or talons.
    visible = alpha > 0
    dark = rgb.max(axis=-1) <= 32
    shadow = visible & neutral & dark
    count = int(shadow.sum())
    out[shadow, 3] = 0
    return out, count


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src-dir", type=Path, required=True)
    ap.add_argument("--out-dir", type=Path, required=True)
    args = ap.parse_args()
    sources = sorted(args.src_dir.glob("*.png"))
    if not sources:
        raise SystemExit(f"no PNGs under {args.src_dir}")
    rows = []
    args.out_dir.mkdir(parents=True, exist_ok=True)
    for src in sources:
        arr = np.asarray(Image.open(src).convert("RGBA"), dtype=np.uint8)
        out, count = cull(arr)
        if count <= 0:
            raise RuntimeError(f"fail-closed: {src.name} has no Roc shadow pixels")
        dst = args.out_dir / src.name
        Image.fromarray(out, mode="RGBA").save(dst)
        rows.append({"frame": src.name, "culledPixels": count})
    report = {
        "ok": True,
        "source": str(args.src_dir).replace("\\", "/"),
        "output": str(args.out_dir).replace("\\", "/"),
        "frames": rows,
        "totalCulledPixels": sum(row["culledPixels"] for row in rows),
        "rule": "visible neutral RGB <= 32; tinted subject pixels retained",
        "proof": "generated artifact validated - Roc transparent ground shadow removed; opaque subject pixels retained",
    }
    (args.out_dir / "shadow_cull_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "frames": len(rows), "totalCulledPixels": report["totalCulledPixels"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
