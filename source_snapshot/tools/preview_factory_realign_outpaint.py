#!/usr/bin/env python3
"""Fresh MAD translation align for new AI outpaint art, then gradual-blur compose.

Does not reuse v5 shift constants. Preview only — does not install.
"""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parents[1]
PILOT = ROOT / "artifacts" / "factory_town_upscale_pilot"
OUT = PILOT / "final" / "preview_align_v5"
AUTH = (0, 0, 1440, 673)
TARGET = (3840, 2160)
MAX_BLUR_R = 32.0
BLUR_FALLOFF_PX = 1100.0
BLUR_INSET_PX = 72.0
SEAM_BLUR_R = 5.0
SEAM_FEATHER = 256
RADII = [0, 1, 2, 4, 7, 11, 16, 22, 28, 32]
STALE_TX, STALE_TY = 179, 165


def find_mad_shift(auth_img: Image.Image, auth_g: np.ndarray, ai_img: Image.Image, iw: int, ih: int) -> dict:
    """Return paste (tx, ty) that best aligns ai plate content to authentic plate."""
    ss = 4
    a_s = np.asarray(
        auth_img.resize((iw // ss, ih // ss), Image.Resampling.BILINEAR).convert("L"), np.float32
    )
    p_s = np.asarray(
        ai_img.crop((0, 0, iw, ih)).resize((iw // ss, ih // ss), Image.Resampling.BILINEAR).convert("L"),
        np.float32,
    )
    cy0, cy1 = a_s.shape[0] // 8, a_s.shape[0] * 7 // 8
    cx0, cx1 = a_s.shape[1] // 8, a_s.shape[1] * 7 // 8
    tpl = a_s[cy0:cy1, cx0:cx1]
    best = (1e9, 0, 0)
    for dy in range(-55, 56):
        for dx in range(-75, 76):
            y0s, y1s = cy0 + dy, cy1 + dy
            x0s, x1s = cx0 + dx, cx1 + dx
            if y0s < 0 or x0s < 0 or y1s > p_s.shape[0] or x1s > p_s.shape[1]:
                continue
            score = float(np.mean(np.abs(tpl - p_s[y0s:y1s, x0s:x1s])))
            if score < best[0]:
                best = (score, dx, dy)

    dx, dy = best[1] * ss, best[2] * ss
    plate = np.asarray(ai_img.crop((0, 0, iw, ih)).convert("L"), np.float32)
    cy0, cy1 = ih // 8, ih * 7 // 8
    cx0, cx1 = iw // 8, iw * 7 // 8
    tpl = auth_g[cy0:cy1:2, cx0:cx1:2]
    bestf = (1e9, dx, dy)
    for dyy in range(dy - 12, dy + 13):
        for dxx in range(dx - 12, dx + 13):
            y0s, y1s = cy0 + dyy, cy1 + dyy
            x0s, x1s = cx0 + dxx, cx1 + dxx
            if y0s < 0 or x0s < 0 or y1s > ih or x1s > iw:
                continue
            score = float(np.mean(np.abs(tpl - plate[y0s:y1s:2, x0s:x1s:2])))
            if score < bestf[0]:
                bestf = (score, dxx, dyy)

    dx, dy = bestf[1], bestf[2]
    # auth[y,x] ~= ai[y+dy, x+dx] ; paste(ai,(tx,ty)) => canvas[y,x]=ai[y-ty,x-tx]
    # want -ty=dy, -tx=dx => tx=-dx, ty=-dy
    tx, ty = -dx, -dy
    zero = float(np.mean(np.abs(tpl - plate[cy0:cy1:2, cx0:cx1:2])))
    return {"mad": bestf[0], "zero_mad": zero, "dx": dx, "dy": dy, "tx": tx, "ty": ty}


def progressive_blur(rgb: np.ndarray, blur_dist: np.ndarray, apply_mask: np.ndarray) -> np.ndarray:
    blurred = [rgb]
    for radius in RADII[1:]:
        image = Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8), "RGB")
        blurred.append(np.asarray(image.filter(ImageFilter.GaussianBlur(radius))).astype(np.float32))

    inside = blur_dist <= BLUR_INSET_PX
    desired_r = np.empty_like(blur_dist)
    t_in = np.clip(blur_dist[inside] / max(BLUR_INSET_PX, 1e-6), 0.0, 1.0)
    t_in = t_in * t_in * (3.0 - 2.0 * t_in)
    desired_r[inside] = t_in * SEAM_BLUR_R
    t_out = np.clip((blur_dist[~inside] - BLUR_INSET_PX) / max(BLUR_FALLOFF_PX, 1e-6), 0.0, 1.0)
    t_out = t_out * t_out * (3.0 - 2.0 * t_out)
    desired_r[~inside] = SEAM_BLUR_R + t_out * (MAX_BLUR_R - SEAM_BLUR_R)
    desired_r = np.clip(desired_r, 0.0, MAX_BLUR_R)

    out = rgb.copy()
    for index in range(len(RADII) - 1):
        radius0 = RADII[index]
        radius1 = RADII[index + 1]
        if index == len(RADII) - 2:
            band = apply_mask & (desired_r >= radius0)
        else:
            band = apply_mask & (desired_r >= radius0) & (desired_r < radius1)
        if not np.any(band):
            continue
        t = np.clip((desired_r - radius0) / max(radius1 - radius0, 1e-6), 0.0, 1.0)[:, :, None]
        mixed = blurred[index] * (1.0 - t) + blurred[index + 1] * t
        out[band] = mixed[band]
    return out


def compose(
    ai_path: Path,
    auth: np.ndarray,
    iw: int,
    ih: int,
    tx: int,
    ty: int,
    label: str,
) -> Image.Image:
    ai = Image.open(ai_path).convert("RGBA").resize(TARGET, Image.Resampling.LANCZOS)
    shifted = Image.new("RGBA", TARGET, (0, 0, 0, 0))
    shifted.paste(ai, (tx, ty))
    arr = np.asarray(shifted).astype(np.float32)
    empty = (arr[:, :, 3] < 8) | ((arr[:, :, :3].sum(axis=2) < 12) & (arr[:, :, 3] < 200))
    valid = ~empty
    rgb = np.clip(arr[:, :, :3], 0, 255).astype(np.uint8)
    inpainted = cv2.inpaint(rgb, empty.astype(np.uint8) * 255, 8, cv2.INPAINT_TELEA).astype(np.float32)
    base = inpainted.copy()
    for y in range(TARGET[1]):
        cols = np.where(valid[y])[0]
        if cols.size and int(cols[0]) > 0:
            first = int(cols[0])
            base[y, :first] = base[y, first : first + 1]
    for x in range(TARGET[0]):
        rows = np.where(valid[:, x])[0]
        if rows.size and int(rows[0]) > 0:
            first = int(rows[0])
            base[:first, x] = base[first : first + 1, x]
    dist_empty = cv2.distanceTransform(empty.astype(np.uint8), cv2.DIST_L2, 5)
    near = np.clip(1.0 - dist_empty / 24.0, 0.0, 1.0)[:, :, None]
    filled = inpainted * near + base * (1.0 - near)
    filled = np.where(valid[:, :, None], arr[:, :, :3], filled)

    ys = np.arange(TARGET[1])[:, None]
    xs = np.arange(TARGET[0])[None, :]
    dist_signed = np.maximum((xs - (iw - 1)).astype(np.float32), (ys - (ih - 1)).astype(np.float32))
    blur_dist = np.maximum(dist_signed + BLUR_INSET_PX, 0.0)
    apply_blur = blur_dist > 0.0

    composed = filled.copy()
    mask = np.zeros((TARGET[1], TARGET[0]), np.uint8)
    mask[:ih, :iw] = 255
    mask = (
        np.asarray(Image.fromarray(mask, "L").filter(ImageFilter.GaussianBlur(SEAM_FEATHER))).astype(
            np.float32
        )
        / 255.0
    )
    base_c = composed.copy()
    base_c[:ih, :iw] = auth[:, :, :3]
    composed = base_c * mask[:, :, None] + composed * (1.0 - mask[:, :, None])
    inset_i = int(round(BLUR_INSET_PX))
    deep_h, deep_w = max(0, ih - inset_i), max(0, iw - inset_i)
    composed[:deep_h, :deep_w] = auth[:deep_h, :deep_w, :3]

    blurred = progressive_blur(composed, blur_dist, apply_blur)
    blurred[:deep_h, :deep_w] = auth[:deep_h, :deep_w, :3]
    final = Image.fromarray(
        np.clip(np.dstack([blurred, np.full((TARGET[1], TARGET[0]), 255)]), 0, 255).astype(np.uint8),
        "RGBA",
    )
    final.save(OUT / f"compose_{label}.png")

    half = final.convert("RGB").resize((1920, 1080), Image.Resampling.LANCZOS)
    draw = ImageDraw.Draw(half)
    draw.rectangle([0, 0, iw // 2 - 1, ih // 2 - 1], outline=(255, 0, 0), width=2)
    draw.rectangle([0, 0, 1200, 34], fill=(0, 0, 0))
    draw.text((8, 8), f"{label}  shift=({tx},{ty})", fill=(255, 255, 0))
    half.save(OUT / f"{label}_1080.png")

    right = final.convert("RGB").crop((iw - 220, 160, min(TARGET[0], iw + 420), ih - 20))
    draw = ImageDraw.Draw(right)
    draw.line([(220, 0), (220, right.height)], fill=(255, 0, 0), width=2)
    draw.text((8, 8), f"{label} RIGHT", fill=(255, 255, 0))
    right.save(OUT / f"{label}_seam_right.png")

    bottom = final.convert("RGB").crop((180, ih - 180, iw - 80, min(TARGET[1], ih + 400)))
    draw = ImageDraw.Draw(bottom)
    draw.line([(0, 180), (bottom.width, 180)], fill=(255, 0, 0), width=2)
    draw.text((8, 8), f"{label} BOTTOM", fill=(255, 255, 0))
    bottom.save(OUT / f"{label}_seam_bottom.png")
    return final


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    source = Image.open(PILOT / "original" / "background_mock_1920x1080.png").convert("RGBA")
    x0, y0, x1, y1 = AUTH
    iw = TARGET[0] * (x1 - x0) // 1920
    ih = TARGET[1] * (y1 - y0) // 1080
    auth_img = source.crop((x0, y0, x1, y1)).resize((iw, ih), Image.Resampling.LANCZOS)
    auth = np.asarray(auth_img).astype(np.float32)
    auth_g = np.asarray(auth_img.convert("L"), np.float32)

    results = []
    for filename in (
        "factory_background_outpaint_terrain_v6.png",
        "factory_background_outpaint_terrain_v6b.png",
    ):
        path = PILOT / "ai" / filename
        if not path.is_file():
            print(f"missing {path}")
            continue
        ai = Image.open(path).convert("RGBA").resize(TARGET, Image.Resampling.LANCZOS)
        align = find_mad_shift(auth_img, auth_g, ai, iw, ih)
        tag = path.stem.replace("factory_background_outpaint_", "")
        print(filename, align)
        label = f"realigned_{tag}_tx{align['tx']}_ty{align['ty']}"
        compose(path, auth, iw, ih, align["tx"], align["ty"], label)
        compose(path, auth, iw, ih, STALE_TX, STALE_TY, f"stale_shift_{tag}")
        results.append((filename, align, label))

    if results:
        stale_name = "stale_shift_terrain_v6b_1080.png"
        fresh_name = f"{results[-1][2]}_1080.png"
        thumbs = []
        for name in (stale_name, fresh_name):
            path = OUT / name
            if path.is_file():
                thumbs.append(Image.open(path).resize((960, 540)))
        if len(thumbs) == 2:
            sheet = Image.new("RGB", (1920, 540))
            sheet.paste(thumbs[0], (0, 0))
            sheet.paste(thumbs[1], (960, 0))
            sheet.save(OUT / "contact_stale_vs_realigned_v6b.png")

    lines = ["fresh MAD alignment (not reused from v5)\n"]
    for filename, align, label in results:
        lines.append(
            f"{filename}: mad={align['mad']:.3f} zero={align['zero_mad']:.3f} "
            f"dx={align['dx']} dy={align['dy']} paste=({align['tx']},{align['ty']}) "
            f"preview={label}\n"
        )
    (OUT / "align_params_fresh.txt").write_text("".join(lines), encoding="utf-8")
    print("PREVIEW ONLY")
    print("".join(lines))


if __name__ == "__main__":
    main()
