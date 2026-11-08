#!/usr/bin/env python3
"""Lock downsample pin from user-guided HI probe (hf + right-of-center bust)."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage  # sobel edges for probe ranking only

ROOT = Path(__file__).resolve().parents[2]
SM = ROOT / "artifacts/collapse_authentic_upscale/surviving_masters"
ORIG = ROOT / "artifacts/collapse_authentic_upscale/original"

METHODS = {
    "nearest": Image.Resampling.NEAREST,
    "box": Image.Resampling.BOX,
    "bilinear": Image.Resampling.BILINEAR,
    "bicubic": Image.Resampling.BICUBIC,
    "lanczos": Image.Resampling.LANCZOS,
}

# User: try hf 0.95; TwCrPort goblin sits a bit right of center.
HF = 0.95
# Shift crop window left on HI FG so the figure lands slightly right in 58x64.
RIGHT_BIAS_PX = 6


def ensure_hi_alpha(hi: Image.Image, thr: float = 8.0) -> Image.Image:
    rgba = np.asarray(hi.convert("RGBA")).copy()
    rgb = rgba[:, :, :3].astype(np.float32)
    alpha = rgba[:, :, 3]
    lum = rgb.mean(axis=2)
    pure = (lum <= thr) & (rgb.max(axis=2) <= thr)
    alpha = np.where((alpha == 0) | pure, 0, 255).astype(np.uint8)
    rgba[:, :, 3] = alpha
    rgba[alpha == 0, :3] = 0
    return Image.fromarray(rgba, "RGBA")


def sobel(gray: np.ndarray) -> np.ndarray:
    return np.hypot(ndimage.sobel(gray, axis=1), ndimage.sobel(gray, axis=0))


def score(down: np.ndarray, tw_rgb: np.ndarray, e_tw: np.ndarray) -> dict | None:
    m = down[:, :, 3] >= 128
    n = int(m.sum())
    if n < 200:
        return None
    e = sobel(down[:, :, :3].mean(axis=2))
    a = e[m]
    b = e_tw[m]
    if float(a.std()) < 1e-3 or float(b.std()) < 1e-3:
        return None
    a = (a - a.mean()) / (a.std() + 1e-6)
    b = (b - b.mean()) / (b.std() + 1e-6)
    ecorr = float((a * b).mean())
    ra = down[:, :, :3].mean(axis=2)[m]
    rb = tw_rgb.mean(axis=2)[m]
    ra = (ra - ra.mean()) / (ra.std() + 1e-6)
    rb = (rb - rb.mean()) / (rb.std() + 1e-6)
    rcorr = float((ra * rb).mean())
    mae = float(np.abs(down[:, :, :3][m] - tw_rgb[m]).mean())
    cov = n / float(down[:, :, 3].size)
    rank = -100.0 * ecorr - 25.0 * rcorr + 0.12 * mae
    return {"ecorr": ecorr, "rcorr": rcorr, "mae": mae, "n": n, "cov": cov, "rank": rank}


def main() -> int:
    tw = Image.open(ORIG / "h3_hobgoblin.png").convert("RGBA")
    tw_rgb = np.asarray(tw.convert("RGB"), dtype=np.float32)
    lw, lh = tw.size
    e_tw = sobel(tw_rgb.mean(axis=2))

    hi = ensure_hi_alpha(Image.open(SM / "h3_hobgoblin_hi_render.png"))
    hi.save(SM / "h3_hobgoblin_hi_alpha.png")
    src = hi.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
    arr = np.asarray(src)
    ys, xs = np.where(arr[:, :, 3] > 0)
    fg = src.crop((int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1))
    fw, fh = fg.size

    hh = int(round(fh * HF))
    ww = int(round(hh * (lw / float(lh))))
    sx_center = max(0, (fw - ww) // 2)
    # Smaller x => figure shifts right in the downsampled frame.
    sx = max(0, min(fw - ww, sx_center - RIGHT_BIAS_PX))
    sy = 0
    print(
        f"hf={HF} fg={fw}x{fh} wh=[{ww},{hh}] "
        f"xy_center=[{sx_center},0] xy_biased=[{sx},{sy}] "
        f"right_bias={RIGHT_BIAS_PX} scale~{ww / lw:.4f}"
    )

    # Write the probe the user can eyeball (BOX, exact seed).
    seed_crop = fg.crop((sx, sy, sx + ww, sy + hh))
    seed_box = seed_crop.resize((lw, lh), Image.Resampling.BOX)
    seed_box.convert("RGB").resize((lw * 8, lh * 8), Image.Resampling.NEAREST).save(
        SM / f"probe_down_hf{HF:.2f}_x8.png"
    )
    seed_down = np.asarray(seed_box.convert("RGBA"), dtype=np.float32)
    seed_sc = score(seed_down, tw_rgb, e_tw)
    print("SEED box:", json.dumps(seed_sc, indent=2))

    cands: list[dict] = []
    for dww in range(-4, 5, 2):
        dhh = int(round(dww * lh / lw))
        for dy in range(0, 5):  # stay near top; bust crop
            for dx in range(-8, 9):
                w, h = ww + dww, hh + dhh
                x, y = sx + dx, sy + dy
                if w < lw or h < lh or x < 0 or y < 0 or x + w > fw or y + h > fh:
                    continue
                crop = fg.crop((x, y, x + w, y + h))
                for mname, rs in METHODS.items():
                    down = np.asarray(crop.resize((lw, lh), rs), dtype=np.float32)
                    sc = score(down, tw_rgb, e_tw)
                    if sc is None:
                        continue
                    cands.append(
                        {
                            **sc,
                            "method": mname,
                            "xy": [x, y],
                            "wh": [w, h],
                            "mirror": True,
                            "kind": f"user_probe_hf{HF:.2f}_refine",
                            "h_frac": HF,
                            "seed_xy": [sx, sy],
                            "seed_wh": [ww, hh],
                            "right_bias_px": RIGHT_BIAS_PX,
                        }
                    )
    cands.sort(key=lambda r: r["rank"])
    print("TOP 8 refine:")
    for r in cands[:8]:
        print(
            f"  e={r['ecorr']:.3f} r={r['rcorr']:.3f} mae={r['mae']:.1f} "
            f"{r['method']:8} xy={r['xy']} wh={r['wh']}"
        )

    at_seed = [r for r in cands if r["xy"] == [sx, sy] and r["wh"] == [ww, hh]]
    box_seed = next((r for r in at_seed if r["method"] == "box"), None)
    best = cands[0]
    # Prefer staying on the user-directed seed unless refine clearly wins.
    if box_seed is not None and best["ecorr"] < box_seed["ecorr"] + 0.025:
        use = box_seed
    elif at_seed and best["ecorr"] < at_seed[0]["ecorr"] + 0.025:
        use = sorted(at_seed, key=lambda r: r["rank"])[0]
    else:
        use = best
    print("USING:", json.dumps(use, indent=2))

    x, y = use["xy"]
    w, h = use["wh"]
    crop = fg.crop((x, y, x + w, y + h))
    down_img = crop.resize((lw, lh), METHODS[use["method"]])

    # Alignment / framing only — do not invent portrait alpha mattes.
    crop.save(SM / "h3_hobgoblin_hi_aligned_crop.png")
    down_img.convert("RGB").save(SM / "h3_hobgoblin_hi_aligned_down.png")
    down_img.convert("RGB").resize((lw * 8, lh * 8), Image.Resampling.NEAREST).save(
        SM / "h3_hobgoblin_hi_aligned_down_x8nn.png"
    )
    src.save(SM / "h3_hobgoblin_hi_alpha_oriented.png")

    framing = Image.new("RGB", (lw * 8 * 2 + 8, lh * 8 + 28), (16, 16, 16))
    fd = ImageDraw.Draw(framing)
    fd.text((4, 4), f"TwCrPort | HI down hf={HF} biasR={RIGHT_BIAS_PX} {use['method']}", fill=(220, 220, 220))
    framing.paste(tw.convert("RGB").resize((lw * 8, lh * 8), Image.Resampling.NEAREST), (0, 24))
    framing.paste(down_img.convert("RGB").resize((lw * 8, lh * 8), Image.Resampling.NEAREST), (lw * 8 + 8, 24))
    framing.save(SM / f"h3_hobgoblin_framing_hf{HF:.2f}.png")

    pin = {
        "schema": "hobgoblin_downsample_pin_user_probe.v2",
        "source_probe": f"surviving_masters/probe_down_hf{HF:.2f}_x8.png",
        "seed": {
            "mirror": True,
            "h_frac": HF,
            "xy": [sx, sy],
            "wh": [ww, hh],
            "xy_center": [sx_center, 0],
            "right_bias_px": RIGHT_BIAS_PX,
            "method": "box",
            "scale_x": ww / lw,
            "scale_y": hh / lh,
        },
        "best": use,
        "seed_score": seed_sc,
        "note": (
            "Alignment probe only. Portrait background removal was abandoned — "
            "use original/h3_hobgoblin.png as the diffusion / nearest-collapse source."
        ),
        "outputs": {
            "hi_down": "surviving_masters/h3_hobgoblin_hi_aligned_down.png",
            "probe": f"surviving_masters/probe_down_hf{HF:.2f}_x8.png",
            "framing": f"surviving_masters/h3_hobgoblin_framing_hf{HF:.2f}.png",
        },
        "proof": "source/static + user visual guidance",
    }
    (SM / "h3_hobgoblin_downsample_pin.json").write_text(json.dumps(pin, indent=2), encoding="utf-8")
    print("wrote hf pin / framing (no nobg)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
