#!/usr/bin/env python3
"""Collapse-authentic HR as an inverse problem (Stage A).

Goal: recover a high-res candidate that
  1) nearest-collapses to the TwCrPort portrait (hard), and
  2) is a smooth field through those known sample sites (no hidden-dot lattice).

This does NOT invent late-90s CGI detail yet. It builds a collapse-valid master
surface that later inventiveness (diffusion / residual) can decorate without
breaking the measurement model.

Method:
  - Plant portrait RGB at Pillow-NEAREST sample sites (integer scale S: offset S//2).
  - Default fill: interpolate free pixels through that regular sample lattice
    (bilinear/cubic) so anchors stay exact and free pixels are smooth — no dots.
  - Optional: discrete harmonic (Laplace) relaxation, or TV polish with hard re-lock.

Proof: source/static + nearest metrics. CGI look is a later stage.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from nearest_collapse import (
    integer_scales,
    nearest_collapse_metrics,
    nn_src_coord,
    sample_coords_for_frame,
)


def _as_rgb_f32(img: Image.Image) -> np.ndarray:
    return np.asarray(img.convert("RGB"), dtype=np.float32)


def plant_nn_samples(
    lr_rgb: np.ndarray,
    *,
    scale_x: int,
    scale_y: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return (hr_rgb, fixed_mask_bool HW, coords lr_h,lr_w,2)."""
    lr_h, lr_w = lr_rgb.shape[:2]
    hr_h, hr_w = lr_h * scale_y, lr_w * scale_x
    hr = np.zeros((hr_h, hr_w, 3), dtype=np.float32)
    fixed = np.zeros((hr_h, hr_w), dtype=bool)
    coords = sample_coords_for_frame(hr_w, hr_h, lr_w, lr_h)
    for y in range(lr_h):
        for x in range(lr_w):
            yy = int(coords[y, x, 0])
            xx = int(coords[y, x, 1])
            # Sanity: integer path must be block origin + S//2
            if yy != y * scale_y + scale_y // 2 or xx != x * scale_x + scale_x // 2:
                raise RuntimeError(
                    f"sample coord drift at ({y},{x}): got ({yy},{xx}) "
                    f"expected ({y * scale_y + scale_y // 2},{x * scale_x + scale_x // 2})"
                )
            hr[yy, xx] = lr_rgb[y, x]
            fixed[yy, xx] = True
    return hr, fixed, coords


def harmonic_fill(
    hr: np.ndarray,
    fixed: np.ndarray,
    *,
    iterations: int = 4000,
    init: np.ndarray | None = None,
    log_every: int = 0,
) -> np.ndarray:
    """Jacobi relaxation for discrete Laplace with Dirichlet samples.

    Free pixels solve mean(neighbors) = self; fixed sample sites stay planted.
    """
    out = hr.copy()
    if init is not None:
        if init.shape != out.shape:
            raise ValueError(f"init shape {init.shape} != hr {out.shape}")
        out = np.where(fixed[..., None], out, init.astype(np.float32))
    else:
        # Seed free pixels with global mean of anchors so relaxation converges faster.
        anchor_mean = out[fixed].mean(axis=0) if fixed.any() else np.array([0.5, 0.5, 0.5])
        free = ~fixed
        out[free] = anchor_mean

    free = ~fixed
    if not free.any():
        return out

    for i in range(int(iterations)):
        # 4-neighbor average; edges use available neighbors via edge pad
        padded = np.pad(out, ((1, 1), (1, 1), (0, 0)), mode="edge")
        neigh = (
            padded[0:-2, 1:-1]
            + padded[2:, 1:-1]
            + padded[1:-1, 0:-2]
            + padded[1:-1, 2:]
        ) * 0.25
        prev = out
        out = np.where(fixed[..., None], out, neigh)
        if log_every and (i + 1) % log_every == 0:
            delta = float(np.abs(out[free] - prev[free]).mean())
            print(f"  harmonic iter {i + 1}/{iterations} mean|delta|={delta:.6f}")
    return out


def tv_polish(
    hr: np.ndarray,
    fixed: np.ndarray,
    *,
    steps: int = 200,
    lr: float = 0.15,
    tv_weight: float = 1.0,
) -> np.ndarray:
    """Lightweight isotropic TV descent on free pixels; hard re-lock samples."""
    try:
        import torch
    except ImportError as exc:
        raise SystemExit("tv polish requires torch") from exc

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    x = torch.tensor(hr / 255.0, device=device, dtype=torch.float32)
    fixed_t = torch.tensor(fixed, device=device)
    anchor = x[fixed_t].clone()

    for _ in range(int(steps)):
        x = x.detach().requires_grad_(True)
        dx = x[1:, :, :] - x[:-1, :, :]
        dy = x[:, 1:, :] - x[:, :-1, :]
        tv = dx.abs().mean() + dy.abs().mean()
        loss = tv_weight * tv
        loss.backward()
        with torch.no_grad():
            g = x.grad
            g = torch.where(fixed_t[..., None], torch.zeros_like(g), g)
            x = (x - lr * g).clamp(0.0, 1.0)
            x[fixed_t] = anchor
    return (x.detach().cpu().numpy() * 255.0).astype(np.float32)


def interpolate_through_nn_samples(
    lr_rgb: np.ndarray,
    *,
    scale_x: int,
    scale_y: int,
    method: str = "linear",
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Bilinear/bicubic field through Pillow-NEAREST sample sites (exact at anchors).

    This is the fast Stage-A fill: free pixels are interpolated from the regular
    sample lattice, so there is no isolated-dot lattice by construction.
    """
    try:
        from scipy.interpolate import RegularGridInterpolator
    except ImportError as exc:
        raise SystemExit("grid interpolation requires scipy") from exc

    lr_h, lr_w = lr_rgb.shape[:2]
    hr_h, hr_w = lr_h * scale_y, lr_w * scale_x
    oy, ox = scale_y // 2, scale_x // 2
    ys = np.arange(lr_h, dtype=np.float64) * scale_y + oy
    xs = np.arange(lr_w, dtype=np.float64) * scale_x + ox
    yy, xx = np.meshgrid(
        np.arange(hr_h, dtype=np.float64),
        np.arange(hr_w, dtype=np.float64),
        indexing="ij",
    )
    # Extrapolate at borders outside the outer sample ring.
    pts = np.stack([yy.ravel(), xx.ravel()], axis=-1)
    hr = np.empty((hr_h, hr_w, 3), dtype=np.float32)
    for c in range(3):
        interp = RegularGridInterpolator(
            (ys, xs),
            lr_rgb[:, :, c].astype(np.float64),
            method=method,
            bounds_error=False,
            fill_value=None,
        )
        hr[:, :, c] = interp(pts).reshape(hr_h, hr_w).astype(np.float32)

    fixed = np.zeros((hr_h, hr_w), dtype=bool)
    coords = sample_coords_for_frame(hr_w, hr_h, lr_w, lr_h)
    for y in range(lr_h):
        for x in range(lr_w):
            yyy, xxx = int(coords[y, x, 0]), int(coords[y, x, 1])
            hr[yyy, xxx] = lr_rgb[y, x]
            fixed[yyy, xxx] = True
    return hr, fixed, coords


def synthesize_collapse_authentic_hr(
    lr: Image.Image,
    *,
    scale: int,
    method: str = "grid_linear",
    harmonic_iters: int = 4000,
    init: str = "lanczos",
    tv_steps: int = 0,
) -> tuple[Image.Image, dict]:
    lr_rgb = _as_rgb_f32(lr)
    lr_h, lr_w = lr_rgb.shape[:2]
    hr_w, hr_h = lr_w * scale, lr_h * scale

    if method in ("grid_linear", "grid_cubic"):
        interp = "linear" if method == "grid_linear" else "cubic"
        filled, fixed, coords = interpolate_through_nn_samples(
            lr_rgb, scale_x=scale, scale_y=scale, method=interp
        )
        used_method = f"regular_grid_interpolator_{interp}"
    elif method == "harmonic":
        planted, fixed, coords = plant_nn_samples(lr_rgb, scale_x=scale, scale_y=scale)
        init_arr = None
        if init == "lanczos":
            init_arr = _as_rgb_f32(lr.resize((hr_w, hr_h), Image.Resampling.LANCZOS))
        elif init == "mean":
            init_arr = None
        elif init == "none":
            init_arr = np.zeros_like(planted)
        else:
            raise ValueError(f"unknown init {init!r}")
        filled = harmonic_fill(
            planted, fixed, iterations=harmonic_iters, init=init_arr
        )
        used_method = "harmonic_dirichlet_nn_samples"
    else:
        raise ValueError(f"unknown method {method!r}")

    if tv_steps > 0:
        filled = tv_polish(filled, fixed, steps=tv_steps)

    # Final hard lock (numerical safety)
    for y in range(lr_h):
        for x in range(lr_w):
            yy, xx = int(coords[y, x, 0]), int(coords[y, x, 1])
            filled[yy, xx] = lr_rgb[y, x]

    out = Image.fromarray(np.clip(filled, 0, 255).astype(np.uint8), "RGB")
    meta = {
        "schema": "local_imagegen.optimize_collapse_authentic_hr.v1",
        "method": used_method,
        "scale": scale,
        "size_lr": [lr_w, lr_h],
        "size_hr": [hr_w, hr_h],
        "harmonic_iters": harmonic_iters if method == "harmonic" else None,
        "init": init if method == "harmonic" else None,
        "tv_steps": tv_steps,
        "fixed_sample_count": int(fixed.sum()),
        "note": (
            "Stage A inverse fill: exact NN sample anchors + smooth free pixels. "
            "Not CGI inventiveness; that is a later free-pixel stage."
        ),
        "proof": "source/static",
    }
    return out, meta


def self_check() -> None:
    # Tiny LR with unique colors; fill must nearest-collapse exactly.
    lr = np.zeros((4, 4, 3), dtype=np.uint8)
    for y in range(4):
        for x in range(4):
            lr[y, x] = [(y * 40 + x * 17) % 256, (y * 9) % 256, (x * 13) % 256]
    lr_img = Image.fromarray(lr, "RGB")
    for s in (2, 4, 8):
        for method in ("grid_linear", "harmonic"):
            hr, _ = synthesize_collapse_authentic_hr(
                lr_img,
                scale=s,
                method=method,
                harmonic_iters=800,
                init="mean",
                tv_steps=0,
            )
            m = nearest_collapse_metrics(hr, lr_img)
            if m["exact_frac"] < 1.0 or m["mae_rgb"] > 0.0:
                raise AssertionError(f"self_check {method} scale={s} failed: {m}")
            arr = np.asarray(hr, dtype=np.float32)
            coords = sample_coords_for_frame(hr.size[0], hr.size[1], 4, 4)
            free_mask = np.ones(arr.shape[:2], dtype=bool)
            for y in range(4):
                for x in range(4):
                    free_mask[int(coords[y, x, 0]), int(coords[y, x, 1])] = False
            if float(arr[free_mask].std()) < 1e-6 and float(arr[free_mask].mean()) < 1.0:
                raise AssertionError(f"{method}: free pixels look empty/flat-zero")
    for s in range(2, 17):
        assert nn_src_coord(0, 2, 2 * s) == 0 * s + s // 2
    print("optimize_collapse_authentic_hr self_check OK")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--self-check", action="store_true")
    ap.add_argument("--image", type=Path, help="Low-res TwCrPort portrait")
    ap.add_argument("--out", type=Path, help="Output HR PNG")
    ap.add_argument("--scale", type=int, default=16, help="Integer upsample factor")
    ap.add_argument(
        "--method",
        choices=("grid_linear", "grid_cubic", "harmonic"),
        default="grid_linear",
        help="Stage A fill: grid_* interpolates through NN samples; harmonic=Laplace relax",
    )
    ap.add_argument("--harmonic-iters", type=int, default=5000)
    ap.add_argument(
        "--init",
        choices=("lanczos", "mean", "none"),
        default="lanczos",
        help="Free-pixel seed before harmonic relaxation (harmonic method only)",
    )
    ap.add_argument("--tv-steps", type=int, default=0, help="Optional TV polish steps")
    ap.add_argument("--metrics-out", type=Path, default=None)
    args = ap.parse_args()

    if args.self_check:
        self_check()
        return 0
    if not args.image or not args.out:
        raise SystemExit("provide --image and --out, or --self-check")
    if args.scale < 2:
        raise SystemExit("--scale must be >= 2")

    lr = Image.open(args.image)
    hr, meta = synthesize_collapse_authentic_hr(
        lr,
        scale=args.scale,
        method=args.method,
        harmonic_iters=args.harmonic_iters,
        init=args.init,
        tv_steps=args.tv_steps,
    )
    scales = integer_scales(hr.size[0], hr.size[1], lr.size[0], lr.size[1])
    if scales != (args.scale, args.scale):
        raise SystemExit(f"scale mismatch: expected {args.scale}, got {scales}")

    metrics = nearest_collapse_metrics(hr, lr)
    meta["nearest_collapse"] = metrics
    if metrics["exact_frac"] < 1.0:
        raise SystemExit(f"FAIL: nearest collapse not exact: {metrics}")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    hr.save(args.out)
    meta["out"] = str(args.out.resolve())
    text = json.dumps(meta, indent=2)
    args.out.with_suffix(".json").write_text(text, encoding="utf-8")
    if args.metrics_out:
        args.metrics_out.parent.mkdir(parents=True, exist_ok=True)
        args.metrics_out.write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
