#!/usr/bin/env python3
"""Convert HoMM3 sprite frames into normalized silhouette targets for pose fitting."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image


def sprite_to_mask(
    path: Path, threshold: int = 8, *, cull_soft_shadows: bool = False
) -> np.ndarray:
    """Return float32 HxW mask in {0,1} from sprite alpha (or non-black RGB)."""
    im = Image.open(path).convert("RGBA")
    arr = np.asarray(im, dtype=np.uint8)
    if cull_soft_shadows:
        from def_soft_shadow import cull_def_soft_shadow_rgba

        arr, _n = cull_def_soft_shadow_rgba(arr)
    alpha = arr[..., 3]
    if int(alpha.max()) <= threshold:
        # Some extracts store opacity in RGB on black; fall back to luma.
        rgb = arr[..., :3].astype(np.int16)
        luma = (0.299 * rgb[..., 0] + 0.587 * rgb[..., 1] + 0.114 * rgb[..., 2]).astype(np.int16)
        mask = (luma > threshold).astype(np.float32)
    else:
        mask = (alpha > threshold).astype(np.float32)
    return mask


def normalize_mask(mask: np.ndarray, out_hw: tuple[int, int], pad_frac: float = 0.08) -> np.ndarray:
    """
    Center the subject by bbox, pad, and fit into out_hw while preserving aspect.
    Returns float32 HxW in {0,1}.
    """
    ys, xs = np.where(mask > 0.5)
    out_h, out_w = out_hw
    canvas = np.zeros((out_h, out_w), dtype=np.float32)
    if ys.size == 0:
        return canvas

    y0, y1 = int(ys.min()), int(ys.max()) + 1
    x0, x1 = int(xs.min()), int(xs.max()) + 1
    crop = mask[y0:y1, x0:x1]
    ch, cw = crop.shape
    pad = int(round(pad_frac * max(ch, cw)))
    padded = np.zeros((ch + 2 * pad, cw + 2 * pad), dtype=np.float32)
    padded[pad : pad + ch, pad : pad + cw] = crop

    ph, pw = padded.shape
    scale = min(out_h / ph, out_w / pw)
    new_h = max(1, int(round(ph * scale)))
    new_w = max(1, int(round(pw * scale)))
    resized = np.array(
        Image.fromarray((padded * 255.0).astype(np.uint8), mode="L").resize(
            (new_w, new_h), resample=Image.Resampling.NEAREST
        ),
        dtype=np.float32,
    ) / 255.0
    resized = (resized > 0.5).astype(np.float32)

    y_off = (out_h - new_h) // 2
    x_off = (out_w - new_w) // 2
    canvas[y_off : y_off + new_h, x_off : x_off + new_w] = resized
    return canvas


def prepare_job_targets(job: dict, *, force: bool = False) -> list[Path]:
    out_dir = Path(job["outputDir"])
    target_dir = out_dir / "targets"
    target_dir.mkdir(parents=True, exist_ok=True)
    res = job.get("render", {})
    out_hw = (int(res.get("height", 256)), int(res.get("width", 288)))
    threshold = int(job.get("spriteAlphaThreshold", 8))
    pad_frac = float(job.get("targetPadFrac", 0.08))

    written: list[Path] = []
    cull = bool(job.get("cullDefSoftShadows", False))
    for i, frame in enumerate(job["frames"]):
        src = Path(frame["path"])
        dst = target_dir / f"target_{i:02d}.png"
        meta = target_dir / f"target_{i:02d}.npy"
        if force or not dst.is_file() or not meta.is_file():
            mask = normalize_mask(
                sprite_to_mask(src, threshold=threshold, cull_soft_shadows=cull),
                out_hw,
                pad_frac=pad_frac,
            )
            Image.fromarray((mask * 255.0).astype(np.uint8), mode="L").save(dst)
            np.save(meta, mask.astype(np.float32))
        written.append(dst)
    return written


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", required=True, type=Path)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    job = json.loads(args.config.read_text(encoding="utf-8"))
    paths = prepare_job_targets(job, force=args.force)
    print(json.dumps({"targets": [str(p) for p in paths]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
