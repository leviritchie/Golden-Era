#!/usr/bin/env python3
"""Compose Factory 4K background by quilting authentic edge textures into the L-region.

Preserves the authentic upper-left plate exactly. Extends right/bottom using
patches sampled from sky/rock/sand in the authentic plate, with a light
low-frequency AI silhouette guide far from the seam.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

ROOT = Path(__file__).resolve().parents[1] / "artifacts" / "factory_town_upscale_pilot"
AUTH_RECT = (0, 0, 1440, 673)
TARGET = (3840, 2160)
RNG = np.random.default_rng(7)


def gather_patches(auth: np.ndarray, rows: np.ndarray, iw: int, patch: int, stride: int, min_x_frac: float):
    patches = []
    if rows.size == 0:
        return patches
    xs0 = int(iw * min_x_frac)
    y_min, y_max = int(rows.min()), int(rows.max())
    for y in range(y_min, max(y_min + 1, y_max - patch + 1), stride):
        if not np.any((rows >= y) & (rows < y + patch)):
            continue
        for x in range(xs0, max(xs0 + 1, iw - patch), stride):
            patches.append(auth[y : y + patch, x : x + patch, :3].copy())
        x_edge = iw - patch
        if x_edge >= 0:
            patches.append(auth[y : y + patch, x_edge : x_edge + patch, :3].copy())
    return patches


def pick_patch(bank: list[np.ndarray], overlap_region: np.ndarray) -> np.ndarray:
    best = None
    best_cost = 1e99
    idx = RNG.choice(len(bank), size=min(80, len(bank)), replace=False)
    mask = np.isfinite(overlap_region[..., 0])
    if not mask.any():
        return bank[int(RNG.integers(0, len(bank)))].copy()
    for i in idx:
        p = bank[i]
        if p.shape != overlap_region.shape:
            continue
        diff = p[mask] - overlap_region[mask]
        cost = float(np.vdot(diff, diff)) / float(mask.sum())
        cost *= float(RNG.uniform(0.92, 1.08))
        if cost < best_cost:
            best_cost = cost
            best = p
    return best.copy() if best is not None else bank[0].copy()


def quilt_region(out: np.ndarray, y0: int, y1: int, x0: int, x1: int, bank: list[np.ndarray], patch: int = 48, overlap: int = 16) -> None:
    if not bank or y1 <= y0 or x1 <= x0:
        return
    y = y0
    while y < y1:
        x = x0
        ph = min(patch, y1 - y)
        while x < x1:
            pw = min(patch, x1 - x)
            ov = np.full((ph, pw, 3), np.nan, dtype=np.float32)
            if x > x0:
                left = min(overlap, pw)
                ov[:, :left, :] = out[y : y + ph, x : x + left, :3]
            if y > y0:
                top = min(overlap, ph)
                ov[:top, :, :] = out[y : y + top, x : x + pw, :3]
            full = pick_patch(bank, ov)
            if full.shape[0] != ph or full.shape[1] != pw:
                full_img = Image.fromarray(np.clip(full, 0, 255).astype(np.uint8))
                full = np.asarray(full_img.resize((pw, ph), Image.Resampling.BICUBIC)).astype(np.float32)
            tile = full
            if x > x0:
                left = min(overlap, pw)
                ramp = np.linspace(0, 1, left, dtype=np.float32)[None, :, None]
                tile[:, :left, :] = out[y : y + ph, x : x + left, :3] * (1 - ramp) + tile[:, :left, :] * ramp
            if y > y0:
                top = min(overlap, ph)
                ramp = np.linspace(0, 1, top, dtype=np.float32)[:, None, None]
                tile[:top, :, :] = out[y : y + top, x : x + pw, :3] * (1 - ramp) + tile[:top, :, :] * ramp
            out[y : y + ph, x : x + pw, :3] = tile
            out[y : y + ph, x : x + pw, 3] = 255
            x += max(1, patch - overlap)
        y += max(1, patch - overlap)


def seam_score(img: Image.Image, iw: int, ih: int) -> float:
    a = np.asarray(img).astype(np.float32)
    band = 10
    y0s = max(0, ih // 5)
    v = float(np.mean(np.abs(a[y0s:ih, iw - band : iw, :3].mean(1) - a[y0s:ih, iw : iw + band, :3].mean(1))))
    h = float(np.mean(np.abs(a[ih - band : ih, :iw, :3].mean(1) - a[ih : ih + band, :iw, :3].mean(1))))
    return v + h


def main() -> None:
    source = Image.open(ROOT / "original" / "background_mock_1920x1080.png").convert("RGBA")
    x0, y0, x1, y1 = AUTH_RECT
    iw = TARGET[0] * (x1 - x0) // 1920
    ih = TARGET[1] * (y1 - y0) // 1080
    auth = np.asarray(source.crop((x0, y0, x1, y1)).resize((iw, ih), Image.Resampling.LANCZOS)).astype(np.float32)

    ai_path = ROOT / "ai" / "factory_background_outpaint_terrain_v5.png"
    if not ai_path.is_file():
        ai_path = ROOT / "ai" / "factory_background_outpaint_terrain_v4.png"
    ai = np.asarray(Image.open(ai_path).convert("RGBA").resize(TARGET, Image.Resampling.LANCZOS)).astype(np.float32)

    right_cols = auth[:, iw - 80 : iw, :3]
    row_mean = right_cols.mean(axis=1)
    blueness = row_mean[:, 2] - (row_mean[:, 0] + row_mean[:, 1]) / 2
    brightness = row_mean.mean(axis=1)
    sky_score = blueness * 0.6 + (brightness / 255.0) * 40
    ground_score = (row_mean[:, 0] + row_mean[:, 1]) / 2 - row_mean[:, 2]

    sky_rows = np.where(sky_score > np.percentile(sky_score, 70))[0]
    sky_rows = sky_rows[sky_rows < int(ih * 0.42)]
    if sky_rows.size == 0:
        sky_rows = np.arange(0, int(ih * 0.28))
    ground_rows = np.where((np.arange(ih) > int(ih * 0.62)) | (ground_score > np.percentile(ground_score, 65)))[0]
    ground_rows = ground_rows[ground_rows > int(ih * 0.55)]
    if ground_rows.size == 0:
        ground_rows = np.arange(int(ih * 0.70), ih)
    rock_rows = np.array([r for r in range(ih) if r not in set(sky_rows.tolist()) and r not in set(ground_rows.tolist())])

    sky_p = gather_patches(auth, sky_rows, iw, 56, 28, 0.2)
    rock_p = gather_patches(auth, rock_rows, iw, 48, 24, 0.45)
    ground_p = gather_patches(auth, ground_rows, iw, 48, 20, 0.15)
    print(f"patches sky={len(sky_p)} rock={len(rock_p)} ground={len(ground_p)}")

    canvas = np.zeros((TARGET[1], TARGET[0], 4), dtype=np.float32)
    canvas[:ih, :iw] = auth
    canvas[..., 3] = 255

    ai_low = np.asarray(
        Image.fromarray(np.clip(ai, 0, 255).astype(np.uint8), "RGBA").filter(ImageFilter.GaussianBlur(18))
    ).astype(np.float32)
    Lmask = np.zeros((TARGET[1], TARGET[0]), dtype=bool)
    Lmask[:, iw:] = True
    Lmask[ih:, :] = True
    canvas[Lmask] = ai_low[Lmask]

    sky_y1 = int(np.median(sky_rows)) + 40
    sky_y1 = min(max(sky_y1, int(ih * 0.25)), int(ih * 0.40))
    rock_y0 = sky_y1 - 20
    rock_y1 = int(np.percentile(ground_rows, 10)) if ground_rows.size else int(ih * 0.72)
    rock_y1 = max(rock_y1, rock_y0 + 80)
    ground_y0 = rock_y1 - 30
    print(f"zones sky_y1={sky_y1} rock={rock_y0}-{rock_y1} ground_y0={ground_y0}")

    if sky_p:
        quilt_region(canvas, 0, min(sky_y1 + 30, ih), iw, TARGET[0], sky_p, patch=56, overlap=20)
    if rock_p:
        quilt_region(canvas, max(0, rock_y0), min(ih, rock_y1 + 20), iw, TARGET[0], rock_p, patch=48, overlap=18)
    if ground_p:
        quilt_region(canvas, max(0, ground_y0), ih, iw, TARGET[0], ground_p, patch=48, overlap=18)
        quilt_region(canvas, ih, TARGET[1], 0, iw, ground_p, patch=48, overlap=18)
        quilt_region(canvas, ih, TARGET[1], iw, TARGET[0], ground_p, patch=48, overlap=18)

    soft = np.asarray(
        Image.fromarray(np.clip(canvas, 0, 255).astype(np.uint8), "RGBA").filter(ImageFilter.GaussianBlur(0.7))
    ).astype(np.float32)
    canvas[Lmask] = canvas[Lmask] * 0.55 + soft[Lmask] * 0.45
    grain = RNG.normal(0, 2.8, size=(TARGET[1], TARGET[0], 3))
    canvas[Lmask, :3] = np.clip(canvas[Lmask, :3] + grain[Lmask], 0, 255)

    ai_low2 = np.asarray(
        Image.fromarray(np.clip(ai, 0, 255).astype(np.uint8), "RGBA").filter(ImageFilter.GaussianBlur(28))
    ).astype(np.float32)
    xs = np.arange(TARGET[0])[None, :]
    ys = np.arange(TARGET[1])[:, None]
    dist = np.sqrt(np.maximum(xs - (iw - 1), 0) ** 2 + np.maximum(ys - (ih - 1), 0) ** 2)
    w = np.clip((dist - 40) / 500.0, 0, 0.28)
    w = np.where(Lmask, w, 0.0)
    canvas = canvas * (1 - w)[:, :, None] + ai_low2 * w[:, :, None]
    canvas[:ih, :iw] = auth
    canvas[..., 3] = 255

    result = canvas.copy()
    result[:ih, :iw] = auth
    feather = 28
    for d in range(feather):
        alpha = 1.0 - (d + 1) / feather
        if iw + d < TARGET[0]:
            edge_col = auth[:, iw - 1 : iw, :3]
            result[:ih, iw + d : iw + d + 1, :3] = (
                result[:ih, iw + d : iw + d + 1, :3] * (1 - alpha * 0.65) + edge_col * (alpha * 0.65)
            )
        if ih + d < TARGET[1]:
            edge_row = auth[ih - 1 : ih, :, :3]
            result[ih + d : ih + d + 1, :iw, :3] = (
                result[ih + d : ih + d + 1, :iw, :3] * (1 - alpha * 0.65) + edge_row * (alpha * 0.65)
            )
    for dy in range(feather):
        for dx in range(feather):
            if ih + dy < TARGET[1] and iw + dx < TARGET[0]:
                a = (1 - (dx + 1) / feather) * (1 - (dy + 1) / feather) * 0.5
                edge_px = auth[ih - 1, iw - 1, :3]
                result[ih + dy, iw + dx, :3] = result[ih + dy, iw + dx, :3] * (1 - a) + edge_px * a

    result[:ih, :iw] = auth
    result[..., 3] = 255
    out = Image.fromarray(np.clip(result, 0, 255).astype(np.uint8), "RGBA")
    final_dir = ROOT / "final"
    final_dir.mkdir(parents=True, exist_ok=True)
    preview = final_dir / "preview_quilt_v1.png"
    candidate = final_dir / "homm3_factory_background_3840x2160_outpaint_v2_candidate.png"
    out.save(preview)
    out.save(candidate)
    print(f"wrote {preview}")
    print(f"wrote {candidate}")
    print(f"seam_score={seam_score(out, iw, ih):.2f}")


if __name__ == "__main__":
    main()
