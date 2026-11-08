#!/usr/bin/env python3
"""Fit downsample kernel from hobgoblin HI render -> TwCrPort 58x64 portrait.

Proof: source/static fit only.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
SM = ROOT / "artifacts/collapse_authentic_upscale/surviving_masters"
ORIG = ROOT / "artifacts/collapse_authentic_upscale/original/h3_hobgoblin.png"

METHODS = {
    "nearest": Image.Resampling.NEAREST,
    "box": Image.Resampling.BOX,
    "bilinear": Image.Resampling.BILINEAR,
    "bicubic": Image.Resampling.BICUBIC,
    "lanczos": Image.Resampling.LANCZOS,
}


def fg_bbox(im: Image.Image, thr: float = 12) -> tuple[int, int, int, int]:
    a = np.asarray(im.convert("RGB"))
    m = a.mean(2) > thr
    ys, xs = np.where(m)
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


def char_mask(low: np.ndarray) -> np.ndarray:
    sky = (low[:, :, 2] > low[:, :, 0] + 8) & (low[:, :, 2] > low[:, :, 1] + 5) & (low.mean(2) > 110)
    pale = low.mean(2) > 155
    return ~(sky | pale)


def remap_palette(img_rgb: np.ndarray, colors: np.ndarray) -> np.ndarray:
    a = img_rgb.astype(np.float32)
    h, w, _ = a.shape
    flat = a.reshape(-1, 3)
    out = np.empty_like(flat)
    step = 400
    for i in range(0, len(flat), step):
        chunk = flat[i : i + step, None, :]
        d = np.sum((chunk - colors[None, :, :]) ** 2, axis=2)
        out[i : i + step] = colors[np.argmin(d, axis=1)]
    return out.reshape(h, w, 3)


def metrics(down: np.ndarray, low: np.ndarray, char: np.ndarray) -> tuple[float, float, float, float]:
    down = down.astype(np.float32)
    mae_full = float(np.mean(np.abs(down - low)))
    mae_char = float(np.mean(np.abs(down[char] - low[char])))
    a = down.mean(2)[char]
    b = low.mean(2)[char]
    a = (a - a.mean()) / (a.std() + 1e-6)
    b = (b - b.mean()) / (b.std() + 1e-6)
    corr = float((a * b).mean())
    exact = float(np.mean(np.all(np.abs(down[char] - low[char]) < 0.5, axis=1)))
    return mae_full, mae_char, corr, exact


def main() -> int:
    hi = Image.open(SM / "h3_hobgoblin_hi_render.png").convert("RGBA")
    tw = Image.open(ORIG).convert("RGB")
    low = np.asarray(tw, dtype=np.float32)
    lw, lh = tw.size
    char = char_mask(low)
    palette = np.unique(low.reshape(-1, 3).astype(np.uint8), axis=0).astype(np.float32)
    print(f"tw={tw.size} hi={hi.size} char_frac={float(char.mean()):.3f} palette={len(palette)}")

    results: list[dict] = []

    # Pass 1: integer scales (strong 90s signal for box/nearest)
    for mirror in (False, True):
        src = hi.transpose(Image.Transpose.FLIP_LEFT_RIGHT) if mirror else hi
        bx0, by0, bx1, by1 = fg_bbox(src)
        fg = src.crop((bx0, by0, bx1, by1)).convert("RGB")
        fw, fh = fg.size
        print(f"mirror={mirror} fg={fw}x{fh}")
        for s in range(2, 8):
            tw_w, tw_h = lw * s, lh * s
            if tw_w > fw or tw_h > fh:
                continue
            # coarse stride first; refined later
            for y in range(0, fh - tw_h + 1, 2):
                for x in range(0, fw - tw_w + 1, 2):
                    crop = fg.crop((x, y, x + tw_w, y + tw_h))
                    for mname, rs in METHODS.items():
                        down = np.asarray(crop.resize((lw, lh), rs).convert("RGB"), dtype=np.float32)
                        mae_f, mae_c, corr, exact = metrics(down, low, char)
                        results.append(
                            {
                                "kind": "integer",
                                "mirror": mirror,
                                "scale": s,
                                "method": mname,
                                "xy": [x, y],
                                "wh": [tw_w, tw_h],
                                "mae_full": mae_f,
                                "mae_char": mae_c,
                                "corr": corr,
                                "exact": exact,
                                "palette": False,
                            }
                        )

    results.sort(key=lambda r: (r["mae_char"], -r["corr"]))
    print("\nTOP 12 integer (no palette):")
    for r in results[:12]:
        print(
            f"  mae_c={r['mae_char']:6.2f} corr={r['corr']:.3f} "
            f"mir={r['mirror']} s={r['scale']} {r['method']:8} xy={r['xy']}"
        )

    # Pass 2: refine top geometries with ±3 and palette remap
    refined: list[dict] = []
    seen: set[tuple] = set()
    seeds = []
    for r in results[:60]:
        key = (r["mirror"], r["scale"], tuple(r["xy"]))
        if key in seen:
            continue
        seen.add(key)
        seeds.append(r)
        if len(seeds) >= 12:
            break

    for seed in seeds:
        mirror = seed["mirror"]
        s = seed["scale"]
        x0, y0 = seed["xy"]
        src = hi.transpose(Image.Transpose.FLIP_LEFT_RIGHT) if mirror else hi
        bx0, by0, bx1, by1 = fg_bbox(src)
        fg = src.crop((bx0, by0, bx1, by1)).convert("RGB")
        tw_w, tw_h = lw * s, lh * s
        for dy in range(-3, 4):
            for dx in range(-3, 4):
                x, y = x0 + dx, y0 + dy
                if x < 0 or y < 0 or x + tw_w > fg.size[0] or y + tw_h > fg.size[1]:
                    continue
                crop = fg.crop((x, y, x + tw_w, y + tw_h))
                for mname, rs in METHODS.items():
                    down_img = crop.resize((lw, lh), rs).convert("RGB")
                    down = np.asarray(down_img, dtype=np.float32)
                    mae_f, mae_c, corr, exact = metrics(down, low, char)
                    refined.append(
                        {
                            "kind": "integer",
                            "mirror": mirror,
                            "scale": s,
                            "method": mname,
                            "xy": [x, y],
                            "wh": [tw_w, tw_h],
                            "mae_full": mae_f,
                            "mae_char": mae_c,
                            "corr": corr,
                            "exact": exact,
                            "palette": False,
                        }
                    )
                    rem = remap_palette(np.asarray(down_img), palette)
                    mae_f, mae_c, corr, exact = metrics(rem, low, char)
                    refined.append(
                        {
                            "kind": "integer",
                            "mirror": mirror,
                            "scale": s,
                            "method": mname + "+palette",
                            "xy": [x, y],
                            "wh": [tw_w, tw_h],
                            "mae_full": mae_f,
                            "mae_char": mae_c,
                            "corr": corr,
                            "exact": exact,
                            "palette": True,
                            "base_method": mname,
                        }
                    )

    refined.sort(key=lambda r: (r["mae_char"], -r["corr"]))
    print("\nTOP 15 refined±3 / palette:")
    for r in refined[:15]:
        print(
            f"  mae_c={r['mae_char']:6.2f} corr={r['corr']:.3f} "
            f"mir={r['mirror']} s={r['scale']} {r['method']:16} xy={r['xy']}"
        )

    # Pass 3: free-scale around best mirror (stride 1 near top of body)
    best_mirror = refined[0]["mirror"] if refined else True
    src = hi.transpose(Image.Transpose.FLIP_LEFT_RIGHT) if best_mirror else hi
    bx0, by0, bx1, by1 = fg_bbox(src)
    fg = src.crop((bx0, by0, bx1, by1)).convert("RGB")
    fw, fh = fg.size
    aspect = lw / lh
    free: list[dict] = []
    for h_frac in np.linspace(0.60, 0.95, 36):
        win_h = int(round(fh * h_frac))
        win_w = int(round(win_h * aspect))
        if win_w > fw or win_h > fh:
            continue
        # head must stay near top
        y_max = min(fh - win_h, int(0.12 * fh))
        for y in range(0, y_max + 1, 2):
            for x in range(0, fw - win_w + 1, 2):
                crop = fg.crop((x, y, x + win_w, y + win_h))
                # box-only coarse rank; other methods on top seeds
                down = np.asarray(crop.resize((lw, lh), Image.Resampling.BOX).convert("RGB"), dtype=np.float32)
                mae_f, mae_c, corr, exact = metrics(down, low, char)
                free.append(
                    {
                        "kind": "free",
                        "mirror": best_mirror,
                        "method": "box",
                        "xy": [x, y],
                        "wh": [win_w, win_h],
                        "h_frac": float(h_frac),
                        "mae_full": mae_f,
                        "mae_char": mae_c,
                        "corr": corr,
                        "exact": exact,
                        "palette": False,
                    }
                )
    free.sort(key=lambda r: (r["mae_char"], -r["corr"]))
    print("\nTOP 10 free-scale (box coarse):")
    for r in free[:10]:
        print(
            f"  mae_c={r['mae_char']:6.2f} corr={r['corr']:.3f} {r['method']:8} "
            f"xy={r['xy']} wh={r['wh']} hfrac={r['h_frac']:.3f}"
        )

    # expand top free seeds across methods + palette + ±2 refine
    expanded: list[dict] = []
    for seed in free[:8]:
        sx, sy = seed["xy"]
        w, h = seed["wh"]
        for dy in range(-2, 3):
            for dx in range(-2, 3):
                x, y = sx + dx, sy + dy
                if x < 0 or y < 0 or x + w > fw or y + h > fh:
                    continue
                crop = fg.crop((x, y, x + w, y + h))
                for mname, rs in METHODS.items():
                    down_img = crop.resize((lw, lh), rs).convert("RGB")
                    down = np.asarray(down_img, dtype=np.float32)
                    mae_f, mae_c, corr, exact = metrics(down, low, char)
                    expanded.append(
                        {
                            "kind": "free",
                            "mirror": best_mirror,
                            "method": mname,
                            "xy": [x, y],
                            "wh": [w, h],
                            "h_frac": seed["h_frac"],
                            "mae_full": mae_f,
                            "mae_char": mae_c,
                            "corr": corr,
                            "exact": exact,
                            "palette": False,
                        }
                    )
                    rem = remap_palette(np.asarray(down_img), palette)
                    mae_f, mae_c, corr, exact = metrics(rem, low, char)
                    expanded.append(
                        {
                            "kind": "free",
                            "mirror": best_mirror,
                            "method": mname + "+palette",
                            "base_method": mname,
                            "xy": [x, y],
                            "wh": [w, h],
                            "h_frac": seed["h_frac"],
                            "mae_full": mae_f,
                            "mae_char": mae_c,
                            "corr": corr,
                            "exact": exact,
                            "palette": True,
                        }
                    )
    free = expanded
    free.sort(key=lambda r: (r["mae_char"], -r["corr"]))
    print("\nTOP 10 free expanded:")
    for r in free[:10]:
        print(
            f"  mae_c={r['mae_char']:6.2f} corr={r['corr']:.3f} {r['method']:16} "
            f"xy={r['xy']} wh={r['wh']}"
        )

    all_best = sorted(refined + free, key=lambda r: (r["mae_char"], -r["corr"]))
    best = all_best[0]
    print("\nBEST:", json.dumps(best, indent=2))

    # Rebuild best crop/down for artifacts
    mirror = best["mirror"]
    src = hi.transpose(Image.Transpose.FLIP_LEFT_RIGHT) if mirror else hi
    bx0, by0, bx1, by1 = fg_bbox(src)
    fg = src.crop((bx0, by0, bx1, by1)).convert("RGB")
    x, y = best["xy"]
    if best["kind"] == "integer":
        w, h = lw * best["scale"], lh * best["scale"]
    else:
        w, h = best["wh"]
    crop = fg.crop((x, y, x + w, y + h))
    base = best.get("base_method") or best["method"].replace("+palette", "")
    down_img = crop.resize((lw, lh), METHODS[base]).convert("RGB")
    if best.get("palette"):
        down_img = Image.fromarray(remap_palette(np.asarray(down_img), palette).astype(np.uint8))

    crop.save(SM / "h3_hobgoblin_pin_crop.png")
    down_img.save(SM / "h3_hobgoblin_pin_down.png")
    tw.save(SM / "h3_hobgoblin_pin_target.png")

    # leaderboard at this geometry
    leaderboard = []
    for mname, rs in METHODS.items():
        d_img = crop.resize((lw, lh), rs).convert("RGB")
        d = np.asarray(d_img, dtype=np.float32)
        mae_f, mae_c, corr, exact = metrics(d, low, char)
        leaderboard.append(
            {"mae_char": mae_c, "corr": corr, "method": mname, "palette": False, "mae_full": mae_f, "exact": exact}
        )
        rem = remap_palette(np.asarray(d_img), palette)
        mae_f, mae_c, corr, exact = metrics(rem, low, char)
        leaderboard.append(
            {
                "mae_char": mae_c,
                "corr": corr,
                "method": mname + "+palette",
                "palette": True,
                "mae_full": mae_f,
                "exact": exact,
            }
        )
    leaderboard.sort(key=lambda r: (r["mae_char"], -r["corr"]))
    print("\nLeaderboard at best geometry:")
    for row in leaderboard:
        print(
            f"  mae_c={row['mae_char']:6.2f} corr={row['corr']:.3f} "
            f"{row['method']:16} exact={row['exact']:.3f}"
        )

    side = Image.new("RGB", (lw * 8 * 3 + 16, lh * 8 + 44), (15, 15, 15))
    side.paste(tw.resize((lw * 8, lh * 8), Image.Resampling.NEAREST), (4, 40))
    side.paste(down_img.resize((lw * 8, lh * 8), Image.Resampling.NEAREST), (lw * 8 + 8, 40))
    diff = np.abs(np.asarray(down_img, dtype=np.float32) - low)
    side.paste(
        Image.fromarray(np.clip(diff * 3, 0, 255).astype(np.uint8)).resize(
            (lw * 8, lh * 8), Image.Resampling.NEAREST
        ),
        (lw * 8 * 2 + 12, 40),
    )
    draw = ImageDraw.Draw(side)
    draw.text((4, 4), f"TwCrPort | {best['method']} | |diff|x3", fill=(220, 220, 220))
    draw.text(
        (4, 20),
        f"mae_char={best['mae_char']:.2f} corr={best['corr']:.3f} mirror={mirror}",
        fill=(180, 180, 180),
    )
    side.save(SM / "h3_hobgoblin_pin_compare.png")

    report = {
        "target": str(ORIG.relative_to(ROOT)),
        "hi": "surviving_masters/h3_hobgoblin_hi_render.png",
        "best": best,
        "leaderboard_at_best_geom": leaderboard,
        "top_integer": results[:10],
        "top_refined": refined[:10],
        "top_free": free[:10],
        "proof": "source/static fit only",
    }
    (SM / "h3_hobgoblin_downsample_pin.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\nwrote {SM / 'h3_hobgoblin_downsample_pin.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
