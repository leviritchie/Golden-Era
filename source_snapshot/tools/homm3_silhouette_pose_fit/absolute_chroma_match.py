#!/usr/bin/env python3
"""
Absolute chroma / pixel match between a HoMM3 sprite and a same-size mesh render.

Success authority for the visual-match contract:
  - Same camera, same pixel grid, absolute position.
  - Optional color-palette normalize only (texture drift) — never pose/root/scale normalize.
  - Joints are not the success metric; they are only a pose tool.

Returns mean absolute RGB error and mean absolute chroma error (CIE Lab a,b) on the
union of opaque sprite/mesh pixels.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image


def _rgba(path: Path) -> np.ndarray:
    return np.asarray(Image.open(path).convert("RGBA"), dtype=np.float32)


def _srgb_to_linear(c: np.ndarray) -> np.ndarray:
    c = np.clip(c / 255.0, 0.0, 1.0)
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def _rgb_to_lab(rgb_u8: np.ndarray) -> np.ndarray:
    """rgb uint-ish float 0..255 HxWx3 → Lab HxWx3 (D65)."""
    lin = _srgb_to_linear(rgb_u8)
    r, g, b = lin[:, :, 0], lin[:, :, 1], lin[:, :, 2]
    x = r * 0.4124564 + g * 0.3575761 + b * 0.1804375
    y = r * 0.2126729 + g * 0.7151522 + b * 0.0721750
    z = r * 0.0193339 + g * 0.1191920 + b * 0.9503041
    # D65 white
    x /= 0.95047
    z /= 1.08883
    eps = 216.0 / 24389.0
    kappa = 24389.0 / 27.0

    def f(t: np.ndarray) -> np.ndarray:
        return np.where(t > eps, np.cbrt(t), (kappa * t + 16.0) / 116.0)

    fx, fy, fz = f(x), f(y), f(z)
    L = 116.0 * fy - 16.0
    a = 500.0 * (fx - fy)
    bb = 200.0 * (fy - fz)
    return np.stack([L, a, bb], axis=-1)


def _palette_normalize_mesh_to_sprite(
    mesh_rgb: np.ndarray,
    sprite_rgb: np.ndarray,
    mask: np.ndarray,
) -> np.ndarray:
    """
    Affine match mesh mean/std to sprite mean/std on masked pixels (per channel).
    Appearance-only; does not move geometry.
    """
    out = mesh_rgb.copy()
    if int(np.count_nonzero(mask)) < 32:
        return out
    for c in range(3):
        ms = mesh_rgb[:, :, c][mask]
        ss = sprite_rgb[:, :, c][mask]
        m_mean, m_std = float(ms.mean()), float(ms.std()) + 1e-6
        s_mean, s_std = float(ss.mean()), float(ss.std()) + 1e-6
        out[:, :, c] = (mesh_rgb[:, :, c] - m_mean) * (s_std / m_std) + s_mean
    return np.clip(out, 0.0, 255.0)


def compare_absolute(
    sprite_rgba: np.ndarray,
    mesh_rgba: np.ndarray,
    *,
    alpha_thr: float = 8.0,
    palette_normalize: bool = True,
    include_chroma: bool = True,
) -> dict:
    if sprite_rgba.shape != mesh_rgba.shape:
        raise RuntimeError(
            f"absolute match requires identical HxWx4 grids; "
            f"got sprite={sprite_rgba.shape} mesh={mesh_rgba.shape}"
        )
    sa = sprite_rgba[:, :, 3]
    ma = mesh_rgba[:, :, 3]
    mask = (sa >= alpha_thr) | (ma >= alpha_thr)
    n = int(np.count_nonzero(mask))
    if n < 16:
        raise RuntimeError("absolute match mask too empty — check camera framing / alpha")

    sprite_rgb = sprite_rgba[:, :, :3]
    mesh_rgb = mesh_rgba[:, :, :3]
    if palette_normalize:
        mesh_rgb = _palette_normalize_mesh_to_sprite(mesh_rgb, sprite_rgb, mask)

    # Where only one side has coverage, treat missing as black (absolute position miss).
    spr = sprite_rgb.copy()
    msh = mesh_rgb.copy()
    spr[sa < alpha_thr] = 0.0
    msh[ma < alpha_thr] = 0.0

    rgb_abs = np.abs(spr - msh)
    rgb_mae = float(rgb_abs[mask].mean())

    if include_chroma:
        lab_s = _rgb_to_lab(spr)
        lab_m = _rgb_to_lab(msh)
        chroma_abs = np.abs(lab_s[:, :, 1:3] - lab_m[:, :, 1:3])
        chroma_mae = float(chroma_abs[mask].mean())
        lab_mae = float(np.abs(lab_s - lab_m)[mask].mean())
    else:
        # Hot-loop proxy: RGB MAE stands in until the absolute-match gate runs Lab.
        chroma_mae = rgb_mae
        lab_mae = rgb_mae

    return {
        "ok": True,
        "pixelCount": n,
        "rgbMae": rgb_mae,
        "chromaMae": chroma_mae,
        "labMae": lab_mae,
        "paletteNormalize": bool(palette_normalize),
        "alphaThr": float(alpha_thr),
        "proof": (
            "generated artifact validated — absolute chroma/pixel match on shared grid; "
            "not OE runtime proven"
        ),
    }


def compare_paths(
    sprite_path: Path,
    mesh_path: Path,
    *,
    alpha_thr: float = 8.0,
    palette_normalize: bool = True,
) -> dict:
    rep = compare_absolute(
        _rgba(sprite_path),
        _rgba(mesh_path),
        alpha_thr=alpha_thr,
        palette_normalize=palette_normalize,
    )
    rep["sprite"] = str(sprite_path).replace("\\", "/")
    rep["mesh"] = str(mesh_path).replace("\\", "/")
    return rep


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sprite", type=Path, required=True)
    ap.add_argument("--mesh", type=Path, required=True)
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--alpha-thr", type=float, default=8.0)
    ap.add_argument("--no-palette-normalize", action="store_true")
    ap.add_argument("--max-chroma-mae", type=float, default=None)
    ap.add_argument("--max-rgb-mae", type=float, default=None)
    args = ap.parse_args()

    rep = compare_paths(
        args.sprite,
        args.mesh,
        alpha_thr=args.alpha_thr,
        palette_normalize=not args.no_palette_normalize,
    )
    errors = []
    if args.max_chroma_mae is not None and rep["chromaMae"] > float(args.max_chroma_mae):
        errors.append(f"chromaMae {rep['chromaMae']:.3f} > {args.max_chroma_mae}")
    if args.max_rgb_mae is not None and rep["rgbMae"] > float(args.max_rgb_mae):
        errors.append(f"rgbMae {rep['rgbMae']:.3f} > {args.max_rgb_mae}")
    rep["ok"] = len(errors) == 0
    rep["errors"] = errors
    text = json.dumps(rep, indent=2) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
    print(text, end="")
    return 0 if rep["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
