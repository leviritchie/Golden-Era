#!/usr/bin/env python3
"""
Prepare v1 pseudo-rig targets: clip-shared framing + alpha masks + edge maps.

Unlike per-frame bbox normalize (v0), every frame in a clip shares one scale/center
derived from the union bbox so limb swings occupy different canvas regions.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image

# Reuse sprite→mask from silhouette tool.
import sys

ROOT = Path(__file__).resolve().parents[2]
SILHOUETTE = Path(__file__).resolve().parents[1] / "homm3_silhouette_pose_fit"
if str(SILHOUETTE) not in sys.path:
    sys.path.insert(0, str(SILHOUETTE))

from prepare_targets import sprite_to_mask  # noqa: E402


def _clip_groups(frames: list[dict]) -> dict[str, list[int]]:
    groups: dict[str, list[int]] = {}
    for i, fr in enumerate(frames):
        cid = str(fr.get("clipId") or fr.get("actionName") or "clip")
        groups.setdefault(cid, []).append(i)
    return groups


def _bbox(mask: np.ndarray) -> tuple[int, int, int, int] | None:
    ys, xs = np.where(mask > 0.5)
    if ys.size == 0:
        return None
    return int(ys.min()), int(ys.max()) + 1, int(xs.min()), int(xs.max()) + 1


def _union_bbox(masks: list[np.ndarray]) -> tuple[int, int, int, int]:
    boxes = [_bbox(m) for m in masks]
    boxes = [b for b in boxes if b is not None]
    if not boxes:
        raise RuntimeError("no non-empty masks for union bbox")
    y0 = min(b[0] for b in boxes)
    y1 = max(b[1] for b in boxes)
    x0 = min(b[2] for b in boxes)
    x1 = max(b[3] for b in boxes)
    return y0, y1, x0, x1


def place_with_framing(
    mask: np.ndarray,
    *,
    out_hw: tuple[int, int],
    y0: int,
    y1: int,
    x0: int,
    x1: int,
    pad_frac: float,
) -> np.ndarray:
    """Place mask into out_hw using a fixed crop window (shared framing)."""
    from PIL import Image as _Image

    out_h, out_w = out_hw
    canvas = np.zeros((out_h, out_w), dtype=np.float32)
    ch = max(1, y1 - y0)
    cw = max(1, x1 - x0)
    pad = int(round(pad_frac * max(ch, cw)))
    # Crop from source with padding (clip to image).
    sy0 = max(0, y0 - pad)
    sy1 = min(mask.shape[0], y1 + pad)
    sx0 = max(0, x0 - pad)
    sx1 = min(mask.shape[1], x1 + pad)
    crop = mask[sy0:sy1, sx0:sx1]
    ph, pw = crop.shape
    if ph < 1 or pw < 1:
        return canvas
    scale = min(out_h / ph, out_w / pw)
    new_h = max(1, int(round(ph * scale)))
    new_w = max(1, int(round(pw * scale)))
    resized = np.array(
        _Image.fromarray((crop * 255.0).astype(np.uint8), mode="L").resize(
            (new_w, new_h), resample=_Image.Resampling.NEAREST
        ),
        dtype=np.float32,
    ) / 255.0
    resized = (resized > 0.5).astype(np.float32)
    y_off = (out_h - new_h) // 2
    x_off = (out_w - new_w) // 2
    canvas[y_off : y_off + new_h, x_off : x_off + new_w] = resized
    return canvas


def sobel_edges(mask: np.ndarray) -> np.ndarray:
    """Soft silhouette edges in [0,1] via Sobel on binary mask."""
    m = mask.astype(np.float32)
    # Simple 3x3 Sobel via scipy if available, else numpy conv.
    try:
        from scipy.ndimage import sobel

        gx = sobel(m, axis=1)
        gy = sobel(m, axis=0)
    except Exception:
        kx = np.array([[-1, 0, 1], [-2, 0, 2], [-1, 0, 1]], dtype=np.float32)
        ky = np.array([[-1, -2, -1], [0, 0, 0], [1, 2, 1]], dtype=np.float32)

        def conv2(img: np.ndarray, k: np.ndarray) -> np.ndarray:
            from numpy.lib.stride_tricks import sliding_window_view

            pad = 1
            p = np.pad(img, pad, mode="edge")
            win = sliding_window_view(p, (3, 3))
            return (win * k).sum(axis=(-2, -1))

        gx = conv2(m, kx)
        gy = conv2(m, ky)
    mag = np.sqrt(gx * gx + gy * gy)
    if float(mag.max()) > 1e-8:
        mag = mag / float(mag.max())
    return mag.astype(np.float32)


def prepare_job_targets_v1(job: dict, *, force: bool = False) -> dict:
    out_dir = Path(job["outputDir"])
    target_dir = out_dir / "targets"
    target_dir.mkdir(parents=True, exist_ok=True)
    res = job.get("render", {})
    out_hw = (int(res.get("height", 256)), int(res.get("width", 288)))
    threshold = int(job.get("spriteAlphaThreshold", 8))
    pad_frac = float(job.get("targetPadFrac", 0.08))
    cull = bool(job.get("cullDefSoftShadows", False))
    frames = list(job["frames"])

    # Load native sprite masks (pre-framing).
    native: list[np.ndarray] = []
    for fr in frames:
        native.append(
            sprite_to_mask(Path(fr["path"]), threshold=threshold, cull_soft_shadows=cull)
        )

    groups = _clip_groups(frames)
    framing: dict[str, dict] = {}
    for clip_id, indices in groups.items():
        y0, y1, x0, x1 = _union_bbox([native[i] for i in indices])
        framing[clip_id] = {
            "y0": y0,
            "y1": y1,
            "x0": x0,
            "x1": x1,
            "padFrac": pad_frac,
            "outHW": [out_hw[0], out_hw[1]],
            "frameIndices": indices,
        }

    written = []
    for i, fr in enumerate(frames):
        clip_id = str(fr.get("clipId") or "clip")
        fmeta = framing[clip_id]
        dst = target_dir / f"target_{i:02d}.png"
        meta = target_dir / f"target_{i:02d}.npy"
        edge_path = target_dir / f"edge_{i:02d}.npy"
        edge_png = target_dir / f"edge_{i:02d}.png"
        if force or not meta.is_file() or not edge_path.is_file():
            placed = place_with_framing(
                native[i],
                out_hw=out_hw,
                y0=int(fmeta["y0"]),
                y1=int(fmeta["y1"]),
                x0=int(fmeta["x0"]),
                x1=int(fmeta["x1"]),
                pad_frac=float(fmeta["padFrac"]),
            )
            edges = sobel_edges(placed)
            Image.fromarray((placed * 255.0).astype(np.uint8), mode="L").save(dst)
            np.save(meta, placed.astype(np.float32))
            np.save(edge_path, edges.astype(np.float32))
            Image.fromarray((edges * 255.0).astype(np.uint8), mode="L").save(edge_png)
        written.append(str(dst))

    framing_path = target_dir / "framing.json"
    framing_path.write_text(
        json.dumps(
            {
                "schema": "homm3_pseudo_rig_framing.v1",
                "mode": "clip_shared_union_bbox",
                "clips": framing,
                "proof": "generated-artifact — v1 clip-shared framing; not OE runtime",
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return {"targets": written, "framing": str(framing_path)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", required=True, type=Path)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    job = json.loads(args.config.read_text(encoding="utf-8"))
    # Resolve relative paths like the host launcher does for frames only if absolute needed.
    root = ROOT
    for fr in job["frames"]:
        p = Path(fr["path"])
        if not p.is_file():
            fr["path"] = str((root / p).resolve())
    if "outputDir" in job and not Path(job["outputDir"]).is_absolute():
        job["outputDir"] = str((root / job["outputDir"]).resolve())
    out = prepare_job_targets_v1(job, force=args.force)
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
