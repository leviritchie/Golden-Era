#!/usr/bin/env python3
"""Nearest-neighbor collapse helpers for TwCrPort-authentic upscales.

User-validated signal: the HI sheet -> portrait path behaves like nearest
downscaling (not box/area). Under Pillow NEAREST with integer scale S,
each low-res pixel samples exactly one high-res pixel at offset (S//2, S//2)
inside its SxS block.

Active contract (diffusion): apply the constraint BETWEEN sampler steps via
ComfyUI ``KSamplerNearestCollapse`` (decode → block_pull + optional exact
sample → encode). See ``comfy_custom_nodes/nearest_collapse_constrain/``.

``project_nearest_collapse`` (sample-site stamp only) is a diagnostic / optional
post path. Alone after SaveImage it produces the "hidden dots" cheat — do not
treat that as the authenticity solution.

Proof: source/static + user visual kernel ID. Runtime inter-step proof separate.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]


def nn_src_coord(out_i: int, out_size: int, in_size: int) -> int:
    """Map output index -> source index the way Pillow NEAREST does for reduce.

    Empirically matches Pillow for integer scales: block offset S//2.
    """
    if out_size <= 0 or in_size <= 0:
        raise ValueError("sizes must be positive")
    # (out + 0.5) * in/out, truncated toward 0 for positive values.
    return int((out_i + 0.5) * in_size / out_size)


def integer_scales(hr_w: int, hr_h: int, lr_w: int, lr_h: int) -> tuple[int, int] | None:
    if hr_w % lr_w or hr_h % lr_h:
        return None
    sx, sy = hr_w // lr_w, hr_h // lr_h
    if sx < 1 or sy < 1:
        return None
    return sx, sy


def nearest_collapse(hr: Image.Image, lr_w: int, lr_h: int) -> Image.Image:
    return hr.convert("RGBA").resize((lr_w, lr_h), Image.Resampling.NEAREST)


def sample_coords_for_frame(hr_w: int, hr_h: int, lr_w: int, lr_h: int) -> np.ndarray:
    """Return (lr_h, lr_w, 2) array of (y, x) sample coords in HR."""
    coords = np.empty((lr_h, lr_w, 2), dtype=np.int32)
    for y in range(lr_h):
        yy = nn_src_coord(y, lr_h, hr_h)
        for x in range(lr_w):
            xx = nn_src_coord(x, lr_w, hr_w)
            coords[y, x, 0] = yy
            coords[y, x, 1] = xx
    return coords


def project_nearest_collapse(
    hr: Image.Image,
    lr: Image.Image,
    *,
    strength: float = 1.0,
) -> Image.Image:
    """Stamp ONLY Pillow-NEAREST sample pixels toward LR (diagnostic / post path).

    strength=1 hard-stamps LR RGBA onto sample sites; (0,1) blends.
    Non-sample pixels are unchanged — alone this is the "hidden dots" cheat.
    Prefer ``project_block_pull`` + inter-step Comfy sampler for generation.
    """
    if not (0.0 < strength <= 1.0):
        raise ValueError("strength must be in (0, 1]")
    hr_rgba = np.asarray(hr.convert("RGBA"), dtype=np.float32).copy()
    lr_rgba = np.asarray(lr.convert("RGBA"), dtype=np.float32)
    hr_h, hr_w = hr_rgba.shape[:2]
    lr_h, lr_w = lr_rgba.shape[:2]
    coords = sample_coords_for_frame(hr_w, hr_h, lr_w, lr_h)
    for y in range(lr_h):
        for x in range(lr_w):
            yy = int(coords[y, x, 0])
            xx = int(coords[y, x, 1])
            if strength >= 1.0:
                hr_rgba[yy, xx] = lr_rgba[y, x]
            else:
                hr_rgba[yy, xx] = (1.0 - strength) * hr_rgba[yy, xx] + strength * lr_rgba[y, x]
    return Image.fromarray(np.clip(hr_rgba, 0, 255).astype(np.uint8), "RGBA")


def project_block_pull(
    hr: Image.Image,
    lr: Image.Image,
    *,
    block_pull: float = 0.35,
    exact_sample: bool = True,
) -> Image.Image:
    """Pull every pixel in each integer SxS block toward the matching LR color.

    Mirrors the Comfy inter-step projector (pixel domain). ``block_pull=0`` +
    ``exact_sample=True`` degenerates to sample-site stamp; ``block_pull=1`` is a
    flat mosaic. Middle values keep within-block detail while biasing the block.
    """
    if not (0.0 <= block_pull <= 1.0):
        raise ValueError("block_pull must be in [0, 1]")
    hr_rgba = np.asarray(hr.convert("RGBA"), dtype=np.float32).copy()
    lr_rgba = np.asarray(lr.convert("RGBA"), dtype=np.float32)
    hr_h, hr_w = hr_rgba.shape[:2]
    lr_h, lr_w = lr_rgba.shape[:2]
    scales = integer_scales(hr_w, hr_h, lr_w, lr_h)
    if scales is None:
        raise ValueError(f"HR {hr_w}x{hr_h} is not an integer multiple of LR {lr_w}x{lr_h}")
    sx, sy = scales
    # reshape to (lr_h, sy, lr_w, sx, C)
    blocks = hr_rgba.reshape(lr_h, sy, lr_w, sx, 4)
    target = lr_rgba.reshape(lr_h, 1, lr_w, 1, 4)
    if block_pull > 0.0:
        blocks = blocks * (1.0 - block_pull) + target * block_pull
    if exact_sample:
        oy, ox = sy // 2, sx // 2
        blocks = np.array(blocks, copy=True)
        blocks[:, oy, :, ox, :] = lr_rgba
    return Image.fromarray(np.clip(blocks.reshape(hr_h, hr_w, 4), 0, 255).astype(np.uint8), "RGBA")


def nearest_collapse_metrics(
    hr: Image.Image,
    lr: Image.Image,
    *,
    soft_threshold: float = 2.0,
    hard_threshold: float = 8.0,
) -> dict:
    """Score how well HR nearest-collapses to LR (exact grid)."""
    lr = lr.convert("RGBA")
    lr_w, lr_h = lr.size
    collapsed = nearest_collapse(hr, lr_w, lr_h)
    a = np.asarray(collapsed, dtype=np.float32)
    b = np.asarray(lr, dtype=np.float32)
    diff = np.abs(a[:, :, :3] - b[:, :, :3])
    mae = float(diff.mean())
    rmse = float(np.sqrt((diff ** 2).mean()))
    max_abs = float(diff.max())
    exact = float(np.mean(np.all(diff < 0.5, axis=2)))
    soft = float(np.mean(np.all(diff <= soft_threshold, axis=2)))
    hard = float(np.mean(np.all(diff <= hard_threshold, axis=2)))
    scales = integer_scales(hr.size[0], hr.size[1], lr_w, lr_h)
    return {
        "mae_rgb": mae,
        "rmse_rgb": rmse,
        "max_abs_rgb": max_abs,
        "exact_frac": exact,
        "soft_frac": soft,
        "hard_frac": hard,
        "soft_threshold": soft_threshold,
        "hard_threshold": hard_threshold,
        "integer_scale": list(scales) if scales else None,
        "size_hr": list(hr.size),
        "size_lr": [lr_w, lr_h],
    }


def stamp_nn_samples_into_soft_init(
    soft_hr: Image.Image,
    lr: Image.Image,
) -> Image.Image:
    """Start from a soft (lanczos) upscale but lock NN sample sites to the portrait.

    Gives diffusion an init that is already nearest-collapse-valid without
    painting the whole frame as NN mosaic blocks.
    """
    return project_nearest_collapse(soft_hr, lr, strength=1.0)


def sample_neighbor_discontinuity(hr: Image.Image, lr: Image.Image) -> dict:
    """Mean |sample - 4-neighbor mean| at NN sites (lattice detector).

    Stage-A continuous fills score ~0.5; hard sample stamps after invent score ~10+.
    """
    hr_rgb = np.asarray(hr.convert("RGB"), dtype=np.float32)
    lr_rgba = lr.convert("RGBA")
    hr_h, hr_w = hr_rgb.shape[:2]
    lr_w, lr_h = lr_rgba.size
    coords = sample_coords_for_frame(hr_w, hr_h, lr_w, lr_h)
    jumps: list[float] = []
    for y in range(lr_h):
        for x in range(lr_w):
            yy = int(coords[y, x, 0])
            xx = int(coords[y, x, 1])
            c = hr_rgb[yy, xx]
            neigh = []
            for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                ny, nx = yy + dy, xx + dx
                if 0 <= ny < hr_h and 0 <= nx < hr_w:
                    neigh.append(hr_rgb[ny, nx])
            if not neigh:
                continue
            jumps.append(float(np.mean(np.abs(c - np.mean(neigh, axis=0)))))
    arr = np.asarray(jumps, dtype=np.float64) if jumps else np.zeros(1)
    return {
        "mean": float(arr.mean()),
        "p95": float(np.percentile(arr, 95)),
        "max": float(arr.max()),
        "n_samples": int(arr.size),
    }


def project_continuous_through_nn_samples(
    hr: Image.Image,
    lr: Image.Image,
    *,
    method: str = "cubic",
) -> Image.Image:
    """Exact NN collapse without isolated center-dot lattice.

    Hard-stamping sample sites after invent creates a visible lattice: free
    pixels drift while anchors snap back. Instead, form the residual
    ``LR - HR[sample]`` on the portrait grid, interpolate that residual through
    the NN lattice (same Stage-A fill), and add it to HR. Anchors become exact;
    free pixels get a smooth correction so the surface still passes through them.

    ``method``: ``linear`` or ``cubic`` (scipy RegularGridInterpolator).
    """
    if method not in ("linear", "cubic"):
        raise ValueError(f"method must be linear|cubic, got {method!r}")
    hr_rgb = np.asarray(hr.convert("RGB"), dtype=np.float32)
    lr_rgb = np.asarray(lr.convert("RGB"), dtype=np.float32)
    out = _add_nn_residual_field(hr_rgb, lr_rgb, method=method)
    return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8), "RGB")


def project_detail_preserving_nn_collapse(
    hr: Image.Image,
    lr: Image.Image,
    *,
    method: str = "cubic",
) -> Image.Image:
    """Exact collapse: continuous(LR) + invent high-pass detail.

    Plain residual add still leaves lattice when invent fights anchors in the
    low frequencies. Split invent into continuous-through-its-own-samples plus
    high-pass detail, then rebuild as continuous(LR) + detail. Sample sites stay
    exact; free pixels keep invented texture without center-dot pops.
    """
    if method not in ("linear", "cubic"):
        raise ValueError(f"method must be linear|cubic, got {method!r}")
    hr_rgb = np.asarray(hr.convert("RGB"), dtype=np.float32)
    lr_rgb = np.asarray(lr.convert("RGB"), dtype=np.float32)
    hr_h, hr_w = hr_rgb.shape[:2]
    lr_h, lr_w = lr_rgb.shape[:2]
    scales = integer_scales(hr_w, hr_h, lr_w, lr_h)
    if scales is None:
        raise ValueError(f"HR {hr_w}x{hr_h} is not an integer multiple of LR {lr_w}x{lr_h}")

    invent_lr = np.asarray(
        nearest_collapse(
            Image.fromarray(np.clip(hr_rgb, 0, 255).astype(np.uint8)), lr_w, lr_h
        ).convert("RGB"),
        dtype=np.float32,
    )
    invent_cont = _interpolate_nn_lattice(
        invent_lr, scale_x=scales[0], scale_y=scales[1], method=method
    )
    detail = hr_rgb - invent_cont
    target_cont = _interpolate_nn_lattice(
        lr_rgb, scale_x=scales[0], scale_y=scales[1], method=method
    )
    out = target_cont + detail
    coords = sample_coords_for_frame(hr_w, hr_h, lr_w, lr_h)
    for y in range(lr_h):
        for x in range(lr_w):
            yy = int(coords[y, x, 0])
            xx = int(coords[y, x, 1])
            out[yy, xx] = lr_rgb[y, x]
    return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8), "RGB")


def _interpolate_nn_lattice(
    lr_rgb: np.ndarray,
    *,
    scale_x: int,
    scale_y: int,
    method: str,
) -> np.ndarray:
    try:
        from scipy.interpolate import RegularGridInterpolator
    except ImportError as exc:
        raise SystemExit("NN lattice interpolate requires scipy") from exc

    lr_h, lr_w = lr_rgb.shape[:2]
    hr_h, hr_w = lr_h * scale_y, lr_w * scale_x
    oy, ox = scale_y // 2, scale_x // 2
    ys = np.arange(lr_h, dtype=np.float64) * scale_y + oy
    xs = np.arange(lr_w, dtype=np.float64) * scale_x + ox
    yy_grid, xx_grid = np.meshgrid(
        np.arange(hr_h, dtype=np.float64),
        np.arange(hr_w, dtype=np.float64),
        indexing="ij",
    )
    pts = np.stack([yy_grid.ravel(), xx_grid.ravel()], axis=-1)
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
    coords = sample_coords_for_frame(hr_w, hr_h, lr_w, lr_h)
    for y in range(lr_h):
        for x in range(lr_w):
            yy = int(coords[y, x, 0])
            xx = int(coords[y, x, 1])
            hr[yy, xx] = lr_rgb[y, x]
    return hr


def _add_nn_residual_field(
    hr_rgb: np.ndarray,
    lr_rgb: np.ndarray,
    *,
    method: str,
) -> np.ndarray:
    hr_h, hr_w = hr_rgb.shape[:2]
    lr_h, lr_w = lr_rgb.shape[:2]
    scales = integer_scales(hr_w, hr_h, lr_w, lr_h)
    if scales is None:
        raise ValueError(f"HR {hr_w}x{hr_h} is not an integer multiple of LR {lr_w}x{lr_h}")
    coords = sample_coords_for_frame(hr_w, hr_h, lr_w, lr_h)
    residual_lr = np.empty_like(lr_rgb)
    for y in range(lr_h):
        for x in range(lr_w):
            yy = int(coords[y, x, 0])
            xx = int(coords[y, x, 1])
            residual_lr[y, x] = lr_rgb[y, x] - hr_rgb[yy, xx]
    delta = _interpolate_nn_lattice(
        residual_lr, scale_x=scales[0], scale_y=scales[1], method=method
    )
    out = hr_rgb + delta
    for y in range(lr_h):
        for x in range(lr_w):
            yy = int(coords[y, x, 0])
            xx = int(coords[y, x, 1])
            out[yy, xx] = lr_rgb[y, x]
    return out


def seed_free_pixel_hf(
    stage_a: Image.Image,
    lr: Image.Image,
    *,
    noise_sigma: float = 12.0,
    edge_amount: float = 0.55,
    band_lo: float = 0.7,
    band_hi: float = 2.8,
    rng_seed: int = 7,
) -> Image.Image:
    """Stage A + free-pixel high-frequency seed (exact NN samples preserved).

    Soft img2img from Stage A alone invents mostly low frequencies that fight the
    anchors. Seeding free pixels with band-limited noise + Stage-A edge residual
    gives the denoiser high-frequency energy to shape into CGI texture while
    sample sites stay portrait-exact.
    """
    if noise_sigma < 0 or edge_amount < 0:
        raise ValueError("noise_sigma and edge_amount must be >= 0")
    if band_lo <= 0 or band_hi <= band_lo:
        raise ValueError("need 0 < band_lo < band_hi")
    try:
        from scipy.ndimage import gaussian_filter
    except ImportError as exc:
        raise SystemExit("seed_free_pixel_hf requires scipy") from exc

    base = np.asarray(stage_a.convert("RGB"), dtype=np.float32)
    lr_rgb = np.asarray(lr.convert("RGB"), dtype=np.float32)
    hr_h, hr_w = base.shape[:2]
    lr_h, lr_w = lr_rgb.shape[:2]
    coords = sample_coords_for_frame(hr_w, hr_h, lr_w, lr_h)
    mask = np.zeros((hr_h, hr_w), dtype=bool)
    for y in range(lr_h):
        for x in range(lr_w):
            mask[int(coords[y, x, 0]), int(coords[y, x, 1])] = True

    blur = np.stack(
        [gaussian_filter(base[:, :, c], sigma=1.25) for c in range(3)], axis=-1
    )
    edges = base - blur

    rng = np.random.default_rng(int(rng_seed) & 0x7FFFFFFF)
    noise = rng.standard_normal(base.shape).astype(np.float32)
    noise_lo = np.stack(
        [gaussian_filter(noise[:, :, c], sigma=float(band_lo)) for c in range(3)],
        axis=-1,
    )
    noise_hi = np.stack(
        [gaussian_filter(noise[:, :, c], sigma=float(band_hi)) for c in range(3)],
        axis=-1,
    )
    band = noise_lo - noise_hi
    std = float(band.std()) or 1.0
    band = band * (float(noise_sigma) / std)

    out = base + float(edge_amount) * edges + band
    out[mask] = base[mask]
    for y in range(lr_h):
        for x in range(lr_w):
            out[int(coords[y, x, 0]), int(coords[y, x, 1])] = lr_rgb[y, x]
    return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8), "RGB")


def project_stage_a_highpass_invent(
    invent: Image.Image,
    stage_a: Image.Image,
    lr: Image.Image,
    *,
    sigma: float = 1.5,
    amplify: float = 1.5,
) -> Image.Image:
    """Exact collapse: Stage A continuous surface + high-pass invent residual.

    Diffusion img2img from Stage A mostly moves low frequencies, which fight the
    NN anchors and recreate a lattice when samples are stamped. Keep Stage A as
    the collapse-valid base; add only high-pass invent detail (zero at sample
    sites). ``amplify`` boosts that residual so inventiveness stays visible.
    """
    if sigma <= 0:
        raise ValueError("sigma must be > 0")
    if amplify < 0:
        raise ValueError("amplify must be >= 0")
    try:
        from scipy.ndimage import gaussian_filter
    except ImportError as exc:
        raise SystemExit("stage_a_highpass invent lock requires scipy") from exc

    inv = np.asarray(invent.convert("RGB"), dtype=np.float32)
    base = np.asarray(stage_a.convert("RGB").resize(invent.size, Image.Resampling.LANCZOS), dtype=np.float32)
    lr_rgb = np.asarray(lr.convert("RGB"), dtype=np.float32)
    if inv.shape != base.shape:
        raise ValueError(f"invent shape {inv.shape} != stage_a {base.shape}")
    hr_h, hr_w = inv.shape[:2]
    lr_h, lr_w = lr_rgb.shape[:2]
    coords = sample_coords_for_frame(hr_w, hr_h, lr_w, lr_h)
    mask = np.zeros((hr_h, hr_w), dtype=bool)
    for y in range(lr_h):
        for x in range(lr_w):
            mask[int(coords[y, x, 0]), int(coords[y, x, 1])] = True

    diff = inv - base
    low = np.stack([gaussian_filter(diff[:, :, c], sigma=float(sigma)) for c in range(3)], axis=-1)
    high = (diff - low) * float(amplify)
    high[mask] = 0.0
    out = base + high
    for y in range(lr_h):
        for x in range(lr_w):
            out[int(coords[y, x, 0]), int(coords[y, x, 1])] = lr_rgb[y, x]
    return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8), "RGB")


def self_check() -> None:
    """Pin Pillow NEAREST sample sites for integer scales."""
    for s in range(2, 17):
        lr_w = lr_h = 2
        hr_w = hr_h = s * 2
        # Unique color per HR pixel
        hr = np.zeros((hr_h, hr_w, 3), dtype=np.uint8)
        for y in range(hr_h):
            for x in range(hr_w):
                hr[y, x] = [(y * 17 + x) % 256, (y * 3) % 256, (x * 5) % 256]
        down = np.asarray(Image.fromarray(hr).resize((lr_w, lr_h), Image.Resampling.NEAREST))
        coords = sample_coords_for_frame(hr_w, hr_h, lr_w, lr_h)
        for y in range(lr_h):
            for x in range(lr_w):
                yy, xx = int(coords[y, x, 0]), int(coords[y, x, 1])
                got = down[y, x]
                exp = hr[yy, xx]
                if not np.array_equal(got, exp):
                    raise AssertionError(
                        f"S={s} mismatch at ({y},{x}): down={got.tolist()} "
                        f"sample[{yy},{xx}]={exp.tolist()} (Pillow NEAREST drift)"
                    )
                # Integer path must be block_origin + S//2
                if yy != y * s + s // 2 or xx != x * s + s // 2:
                    raise AssertionError(
                        f"S={s} coord formula drift: got ({yy},{xx}) "
                        f"expected ({y * s + s // 2},{x * s + s // 2})"
                    )
    # Project round-trip (sample-site stamp)
    lr = Image.fromarray(np.random.randint(0, 255, (8, 8, 3), dtype=np.uint8))
    soft = lr.resize((8 * 4, 8 * 4), Image.Resampling.LANCZOS)
    projected = project_nearest_collapse(soft, lr)
    m = nearest_collapse_metrics(projected, lr)
    if m["exact_frac"] < 1.0:
        raise AssertionError(f"project did not yield exact NN collapse: {m}")
    # Block-pull with exact_sample also exact-collapses
    pulled = project_block_pull(soft, lr, block_pull=0.35, exact_sample=True)
    m2 = nearest_collapse_metrics(pulled, lr)
    if m2["exact_frac"] < 1.0:
        raise AssertionError(f"block_pull did not yield exact NN collapse: {m2}")
    # Continuous residual project: exact collapse without stamp lattice.
    cont = project_continuous_through_nn_samples(soft, lr, method="cubic")
    m3 = nearest_collapse_metrics(cont, lr)
    if m3["exact_frac"] < 1.0:
        raise AssertionError(f"continuous project did not yield exact NN collapse: {m3}")
    disc_stamp = sample_neighbor_discontinuity(projected, lr)["mean"]
    disc_cont = sample_neighbor_discontinuity(cont, lr)["mean"]
    if disc_cont > disc_stamp:
        raise AssertionError(
            f"continuous project more discontinuous than stamp: "
            f"cont={disc_cont:.3f} stamp={disc_stamp:.3f}"
        )
    detail = project_detail_preserving_nn_collapse(soft, lr, method="cubic")
    m4 = nearest_collapse_metrics(detail, lr)
    if m4["exact_frac"] < 1.0:
        raise AssertionError(f"detail-preserving project failed exact collapse: {m4}")
    # Stage-A + highpass invent residual also exact-collapses.
    soft_a = project_continuous_through_nn_samples(soft, lr, method="cubic")
    hp = project_stage_a_highpass_invent(soft, soft_a, lr, sigma=1.5, amplify=1.0)
    m5 = nearest_collapse_metrics(hp, lr)
    if m5["exact_frac"] < 1.0:
        raise AssertionError(f"stage_a_highpass lock failed exact collapse: {m5}")
    # Lattice should stay well below hard-stamp levels on soft starts.
    if sample_neighbor_discontinuity(hp, lr)["mean"] > disc_stamp:
        raise AssertionError("stage_a_highpass lattice worse than hard stamp")
    seeded = seed_free_pixel_hf(soft_a, lr, noise_sigma=8.0, edge_amount=0.4, rng_seed=1)
    m6 = nearest_collapse_metrics(seeded, lr)
    if m6["exact_frac"] < 1.0:
        raise AssertionError(f"HF free-pixel seed must exact-collapse: {m6}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--self-check", action="store_true")
    ap.add_argument("--hr", type=Path, help="High-res candidate")
    ap.add_argument("--lr", type=Path, help="Low-res portrait / TwCrPort")
    ap.add_argument("--project-out", type=Path, help="Write projected HR PNG")
    ap.add_argument("--strength", type=float, default=1.0)
    ap.add_argument("--metrics-out", type=Path, help="Write metrics JSON")
    args = ap.parse_args()

    if args.self_check:
        self_check()
        print("nearest_collapse self_check OK")
        return 0

    if not args.hr or not args.lr:
        raise SystemExit("provide --hr and --lr, or --self-check")
    hr = Image.open(args.hr)
    lr = Image.open(args.lr)
    before = nearest_collapse_metrics(hr, lr)
    projected = project_nearest_collapse(hr, lr, strength=args.strength)
    after = nearest_collapse_metrics(projected, lr)
    if args.project_out:
        args.project_out.parent.mkdir(parents=True, exist_ok=True)
        projected.save(args.project_out)
    report = {
        "schema": "nearest_collapse.v1",
        "before": before,
        "after": after,
        "strength": args.strength,
        "project_out": str(args.project_out) if args.project_out else None,
        "note": (
            "Only NN sample pixels are constrained; other HR pixels may differ. "
            "That is the correct inverse of nearest downscale."
        ),
        "proof": "source/static",
    }
    text = json.dumps(report, indent=2)
    if args.metrics_out:
        args.metrics_out.parent.mkdir(parents=True, exist_ok=True)
        args.metrics_out.write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
