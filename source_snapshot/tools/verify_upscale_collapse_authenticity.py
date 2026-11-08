#!/usr/bin/env python3
"""Verify whether an upscaled image can realistically collapse into its low-res source.

Authenticity here means: after area/box (and optional alternate) downsampling of the
candidate back to the original pixel grid, regional RGB/A values stay close enough to
the source that the upscale could have produced that source — not inventing colors or
structures the compressor/resampler would have erased differently.

This is source/static validated only. It does not prove perceptual quality by itself.
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = ROOT / "artifacts" / "collapse_authentic_upscale"


RESAMPLE = {
    "box": Image.Resampling.BOX,
    "area": Image.Resampling.BOX,
    "lanczos": Image.Resampling.LANCZOS,
    "bicubic": Image.Resampling.BICUBIC,
    "bilinear": Image.Resampling.BILINEAR,
    "nearest": Image.Resampling.NEAREST,
}


@dataclass
class RegionScore:
    x: int
    y: int
    w: int
    h: int
    mae_rgb: float
    rmse_rgb: float
    max_abs_rgb: float
    mae_alpha: float
    opaque_frac: float
    pass_soft: bool
    pass_hard: bool


@dataclass
class CandidateScore:
    candidate: str
    original: str
    size_candidate: list[int]
    size_original: list[int]
    method: str
    global_mae_rgb: float
    global_rmse_rgb: float
    global_psnr_rgb: float
    global_mae_alpha: float
    region_pass_soft_frac: float
    region_pass_hard_frac: float
    worst_region_mae_rgb: float
    authenticity_score: float
    soft_threshold: float
    hard_threshold: float
    tile: int
    regions: list[RegionScore]


def _load_rgba(path: Path) -> Image.Image:
    return Image.open(path).convert("RGBA")


def _fit_candidate_to_original_frame(candidate: Image.Image, ow: int, oh: int) -> Image.Image:
    """Letterbox/crop candidate into the original aspect, then leave size for downsampler."""
    cw, ch = candidate.size
    target_aspect = ow / oh
    cand_aspect = cw / ch
    if abs(cand_aspect - target_aspect) < 1e-3:
        return candidate
    if cand_aspect > target_aspect:
        # too wide — crop width around center
        new_w = max(1, int(round(ch * target_aspect)))
        x0 = (cw - new_w) // 2
        return candidate.crop((x0, 0, x0 + new_w, ch))
    # too tall — crop height around center (portraits often pad vertically)
    new_h = max(1, int(round(cw / target_aspect)))
    y0 = (ch - new_h) // 2
    return candidate.crop((0, y0, cw, y0 + new_h))


def collapse_to_original(
    candidate: Image.Image,
    original: Image.Image,
    method: str = "box",
) -> Image.Image:
    ow, oh = original.size
    framed = _fit_candidate_to_original_frame(candidate, ow, oh)
    resample = RESAMPLE[method]
    return framed.resize((ow, oh), resample)


def _rgb_stats(a: np.ndarray, b: np.ndarray, weight: np.ndarray) -> tuple[float, float, float]:
    """Weighted RGB MAE / RMSE / max-abs. weight is [0,1] mask."""
    diff = a.astype(np.float64) - b.astype(np.float64)
    w = weight.astype(np.float64)
    if w.ndim == 2:
        w3 = w[:, :, None]
    else:
        w3 = w
    denom = float(w.sum()) * 3.0
    if denom <= 1e-9:
        return 0.0, 0.0, 0.0
    abs_diff = np.abs(diff) * w3
    mae = float(abs_diff.sum() / denom)
    rmse = float(math.sqrt(((diff * w3) ** 2).sum() / denom))
    # max over opaque-ish pixels only
    mask = w > 0.5
    if not mask.any():
        max_abs = 0.0
    else:
        max_abs = float(np.abs(diff[mask]).max())
    return mae, rmse, max_abs


def _psnr(rmse: float, peak: float = 255.0) -> float:
    if rmse <= 1e-9:
        return 99.0
    return float(20.0 * math.log10(peak / rmse))


def score_regions(
    collapsed: Image.Image,
    original: Image.Image,
    *,
    tile: int = 8,
    soft_threshold: float = 18.0,
    hard_threshold: float = 32.0,
) -> tuple[list[RegionScore], dict]:
    c = np.asarray(collapsed, dtype=np.float64)
    o = np.asarray(original, dtype=np.float64)
    if c.shape != o.shape:
        raise ValueError(f"shape mismatch collapsed={c.shape} original={o.shape}")

    h, w = o.shape[:2]
    # Prefer comparing where either side has meaningful coverage
    alpha_w = np.maximum(c[:, :, 3], o[:, :, 3]) / 255.0

    g_mae, g_rmse, _ = _rgb_stats(c[:, :, :3], o[:, :, :3], alpha_w)
    a_mae = float(np.mean(np.abs(c[:, :, 3] - o[:, :, 3])))

    regions: list[RegionScore] = []
    for y in range(0, h, tile):
        for x in range(0, w, tile):
            y1 = min(h, y + tile)
            x1 = min(w, x + tile)
            cw = alpha_w[y:y1, x:x1]
            mae, rmse, max_abs = _rgb_stats(
                c[y:y1, x:x1, :3],
                o[y:y1, x:x1, :3],
                cw,
            )
            mae_a = float(np.mean(np.abs(c[y:y1, x:x1, 3] - o[y:y1, x:x1, 3])))
            opaque = float(cw.mean()) if cw.size else 0.0
            regions.append(
                RegionScore(
                    x=x,
                    y=y,
                    w=x1 - x,
                    h=y1 - y,
                    mae_rgb=mae,
                    rmse_rgb=rmse,
                    max_abs_rgb=max_abs,
                    mae_alpha=mae_a,
                    opaque_frac=opaque,
                    pass_soft=mae <= soft_threshold,
                    pass_hard=mae <= hard_threshold,
                )
            )

    # Only score regions that are at least partly opaque in the original
    scored = [r for r in regions if r.opaque_frac >= 0.05]
    if not scored:
        scored = regions
    soft_frac = float(sum(1 for r in scored if r.pass_soft) / len(scored))
    hard_frac = float(sum(1 for r in scored if r.pass_hard) / len(scored))
    worst = max((r.mae_rgb for r in scored), default=0.0)

    # Authenticity: reward low global error + high regional pass rate.
    # Soft pass dominates; hard pass is a safety floor; PSNR soft-caps contribution.
    psnr = _psnr(g_rmse)
    authenticity = (
        0.45 * soft_frac
        + 0.20 * hard_frac
        + 0.25 * min(1.0, psnr / 35.0)
        + 0.10 * max(0.0, 1.0 - worst / 60.0)
    )

    summary = {
        "global_mae_rgb": g_mae,
        "global_rmse_rgb": g_rmse,
        "global_psnr_rgb": psnr,
        "global_mae_alpha": a_mae,
        "region_pass_soft_frac": soft_frac,
        "region_pass_hard_frac": hard_frac,
        "worst_region_mae_rgb": worst,
        "authenticity_score": authenticity,
    }
    return regions, summary


def score_candidate(
    candidate_path: Path,
    original_path: Path,
    *,
    method: str = "box",
    tile: int = 8,
    soft_threshold: float = 18.0,
    hard_threshold: float = 32.0,
    write_collapsed: Path | None = None,
    write_diff: Path | None = None,
) -> CandidateScore:
    original = _load_rgba(original_path)
    candidate = _load_rgba(candidate_path)
    collapsed = collapse_to_original(candidate, original, method=method)
    if write_collapsed is not None:
        write_collapsed.parent.mkdir(parents=True, exist_ok=True)
        collapsed.save(write_collapsed)

    regions, summary = score_regions(
        collapsed,
        original,
        tile=tile,
        soft_threshold=soft_threshold,
        hard_threshold=hard_threshold,
    )

    if write_diff is not None:
        write_diff.parent.mkdir(parents=True, exist_ok=True)
        _save_diff_panel(original, collapsed, regions, tile, write_diff)

    return CandidateScore(
        candidate=str(candidate_path),
        original=str(original_path),
        size_candidate=list(candidate.size),
        size_original=list(original.size),
        method=method,
        soft_threshold=soft_threshold,
        hard_threshold=hard_threshold,
        tile=tile,
        regions=regions,
        **summary,
    )


def _save_diff_panel(
    original: Image.Image,
    collapsed: Image.Image,
    regions: Iterable[RegionScore],
    tile: int,
    out_path: Path,
    scale: int = 8,
) -> None:
    o = original.convert("RGBA")
    c = collapsed.convert("RGBA")
    ow, oh = o.size
    o_big = o.resize((ow * scale, oh * scale), Image.Resampling.NEAREST)
    c_big = c.resize((ow * scale, oh * scale), Image.Resampling.NEAREST)

    o_arr = np.asarray(o, dtype=np.float64)
    c_arr = np.asarray(c, dtype=np.float64)
    err = np.mean(np.abs(o_arr[:, :, :3] - c_arr[:, :, :3]), axis=2)
    err_u8 = np.clip(err * (255.0 / 48.0), 0, 255).astype(np.uint8)
    heat = Image.fromarray(err_u8, mode="L").convert("RGBA")
    heat = heat.resize((ow * scale, oh * scale), Image.Resampling.NEAREST)

    # Region fail overlay (red = hard fail, yellow = soft fail)
    overlay = Image.new("RGBA", (ow * scale, oh * scale), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    for r in regions:
        if r.opaque_frac < 0.05:
            continue
        color = None
        if not r.pass_hard:
            color = (220, 40, 40, 110)
        elif not r.pass_soft:
            color = (220, 180, 40, 90)
        if color is None:
            continue
        draw.rectangle(
            [
                r.x * scale,
                r.y * scale,
                (r.x + r.w) * scale - 1,
                (r.y + r.h) * scale - 1,
            ],
            outline=color[:3] + (200,),
            width=max(1, scale // 4),
            fill=color,
        )

    gap = scale
    panel_w = ow * scale * 3 + gap * 2
    panel = Image.new("RGBA", (panel_w, oh * scale), (24, 24, 28, 255))
    panel.paste(o_big, (0, 0), o_big)
    panel.paste(c_big, (ow * scale + gap, 0), c_big)
    heat_panel = Image.alpha_composite(heat, overlay)
    panel.paste(heat_panel, (2 * (ow * scale + gap), 0))
    panel.save(out_path)


def write_review_strip(
    original_path: Path,
    candidate_path: Path,
    collapsed_path: Path,
    out_path: Path,
    *,
    label: str,
    score: float,
    side: int = 256,
) -> None:
    o = _load_rgba(original_path).resize((side, side), Image.Resampling.NEAREST)
    cand = _load_rgba(candidate_path)
    # Fit cand into square for strip
    framed = _fit_candidate_to_original_frame(cand, *Image.open(original_path).size)
    c = framed.resize((side, side), Image.Resampling.LANCZOS)
    col = _load_rgba(collapsed_path).resize((side, side), Image.Resampling.NEAREST)
    gap = 8
    strip = Image.new("RGBA", (side * 3 + gap * 2, side + 28), (20, 20, 24, 255))
    strip.paste(o, (0, 28), o)
    strip.paste(c, (side + gap, 28), c)
    strip.paste(col, (2 * (side + gap), 28), col)
    draw = ImageDraw.Draw(strip)
    draw.text((4, 4), f"{label}  authenticity={score:.3f}  (orig | upscale | collapse)", fill=(230, 230, 230, 255))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    strip.save(out_path)


def _baseline_lanczos(original: Image.Image, scale: int) -> Image.Image:
    w, h = original.size
    return original.resize((w * scale, h * scale), Image.Resampling.LANCZOS)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--original", type=Path, required=True, help="Low-res source PNG")
    ap.add_argument(
        "--candidate",
        type=Path,
        action="append",
        default=[],
        help="Upscale candidate PNG (repeatable)",
    )
    ap.add_argument("--candidates-dir", type=Path, default=None, help="Score every PNG in dir")
    ap.add_argument("--method", choices=sorted(RESAMPLE), default="box")
    ap.add_argument("--tile", type=int, default=8)
    ap.add_argument("--soft-threshold", type=float, default=18.0)
    ap.add_argument("--hard-threshold", type=float, default=32.0)
    ap.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    ap.add_argument(
        "--include-lanczos-baseline",
        action="store_true",
        help="Also score a pure Lanczos enlargement of the original",
    )
    ap.add_argument("--baseline-scale", type=int, default=16)
    ap.add_argument("--json-out", type=Path, default=None)
    args = ap.parse_args()

    original = args.original.resolve()
    if not original.is_file():
        raise SystemExit(f"original not found: {original}")

    out_dir = args.out_dir.resolve()
    scores_dir = out_dir / "scores"
    strips_dir = out_dir / "strips"
    scores_dir.mkdir(parents=True, exist_ok=True)
    strips_dir.mkdir(parents=True, exist_ok=True)

    candidates: list[Path] = [p.resolve() for p in args.candidate]
    if args.candidates_dir is not None:
        d = args.candidates_dir.resolve()
        candidates.extend(sorted(d.glob("*.png")))
    if args.include_lanczos_baseline:
        base_path = out_dir / "candidates" / f"_baseline_lanczos_x{args.baseline_scale}.png"
        base_path.parent.mkdir(parents=True, exist_ok=True)
        _baseline_lanczos(_load_rgba(original), args.baseline_scale).save(base_path)
        candidates.append(base_path)

    if not candidates:
        raise SystemExit("no candidates provided")

    results: list[CandidateScore] = []
    for cand in candidates:
        stem = cand.stem
        collapsed_path = scores_dir / f"{stem}__collapsed.png"
        diff_path = scores_dir / f"{stem}__diff.png"
        strip_path = strips_dir / f"{stem}__review.png"
        score = score_candidate(
            cand,
            original,
            method=args.method,
            tile=args.tile,
            soft_threshold=args.soft_threshold,
            hard_threshold=args.hard_threshold,
            write_collapsed=collapsed_path,
            write_diff=diff_path,
        )
        write_review_strip(
            original,
            cand,
            collapsed_path,
            strip_path,
            label=stem,
            score=score.authenticity_score,
        )
        results.append(score)
        print(
            f"{stem:40s}  auth={score.authenticity_score:.3f}  "
            f"mae={score.global_mae_rgb:.2f}  psnr={score.global_psnr_rgb:.2f}  "
            f"soft={score.region_pass_soft_frac:.0%}  hard={score.region_pass_hard_frac:.0%}  "
            f"worst_tile={score.worst_region_mae_rgb:.1f}"
        )

    results.sort(key=lambda r: r.authenticity_score, reverse=True)
    payload = {
        "schema": "collapse_authentic_upscale.score.v1",
        "proof": "source/static validated",
        "original": str(original),
        "method": args.method,
        "tile": args.tile,
        "soft_threshold": args.soft_threshold,
        "hard_threshold": args.hard_threshold,
        "ranked": [
            {
                **{k: v for k, v in asdict(r).items() if k != "regions"},
                "region_count": len(r.regions),
                "rank": i + 1,
            }
            for i, r in enumerate(results)
        ],
    }
    json_out = args.json_out or (out_dir / "reports" / "scoreboard.json")
    json_out.parent.mkdir(parents=True, exist_ok=True)
    json_out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"\nWrote {json_out}")
    print("Ranked:")
    for i, r in enumerate(results, 1):
        print(f"  {i}. {Path(r.candidate).name}  authenticity={r.authenticity_score:.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
