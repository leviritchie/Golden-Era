#!/usr/bin/env python3
"""Preview: t7 MAD shift + simple black fill + progressive outward gaussian blur.

Does not install into the live Factory scene.
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
# Prefer v6 (allows cut-off buildings to continue); fall back to v5.
AI_OUTPAINT = PILOT / "ai" / "factory_background_outpaint_terrain_v6b.png"
AI_OUTPAINT_FALLBACK = PILOT / "ai" / "factory_background_outpaint_terrain_v6.png"
# TX/TY are measured per AI source at runtime — never reuse another generation's shift.
MAX_BLUR_R = 32.0
BLUR_FALLOFF_PX = 1100.0
# Creep blur this many px inside the authentic plate so the seam softens.
BLUR_INSET_PX = 72.0
# Blur radius reached exactly at the seam line (then grows outward to MAX_BLUR_R).
SEAM_BLUR_R = 5.0
SEAM_FEATHER = 256
RADII = [0, 1, 2, 4, 7, 11, 16, 22, 28, 32]


def progressive_blur(rgb: np.ndarray, blur_dist: np.ndarray, apply_mask: np.ndarray) -> np.ndarray:
    """Apply blur radius that grows with blur_dist. apply_mask selects editable pixels.

    blur_dist is 0 at BLUR_INSET_PX inside the seam, equals BLUR_INSET_PX at the seam,
    and increases outward. Radius hits SEAM_BLUR_R at the seam, then MAX_BLUR_R far out.
    """
    blurred = [rgb]
    for radius in RADII[1:]:
        image = Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8), "RGB")
        blurred.append(np.asarray(image.filter(ImageFilter.GaussianBlur(radius))).astype(np.float32))

    # Two-stage radius with ease-in so early growth stays soft.
    inside = blur_dist <= BLUR_INSET_PX
    desired_r = np.empty_like(blur_dist)
    t_in = np.clip(blur_dist[inside] / max(BLUR_INSET_PX, 1e-6), 0.0, 1.0)
    # smoothstep ease-in for the inset ramp
    t_in = t_in * t_in * (3.0 - 2.0 * t_in)
    desired_r[inside] = t_in * SEAM_BLUR_R
    t_out = np.clip(
        (blur_dist[~inside] - BLUR_INSET_PX) / max(BLUR_FALLOFF_PX, 1e-6), 0.0, 1.0
    )
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


def preview(image: Image.Image, name: str, iw: int, ih: int) -> None:
    half = image.convert("RGB").resize((1920, 1080), Image.Resampling.LANCZOS)
    draw = ImageDraw.Draw(half)
    draw.rectangle([0, 0, iw // 2 - 1, ih // 2 - 1], outline=(255, 0, 0), width=2)
    draw.rectangle([0, 0, 1100, 34], fill=(0, 0, 0))
    draw.text((8, 8), name, fill=(255, 255, 0))
    half.save(OUT / f"{name}_1080.png")

    right = image.convert("RGB").crop((iw - 220, 160, min(TARGET[0], iw + 420), ih - 20))
    draw = ImageDraw.Draw(right)
    draw.line([(220, 0), (220, right.height)], fill=(255, 0, 0), width=2)
    draw.text((8, 8), f"{name} RIGHT", fill=(255, 255, 0))
    right.save(OUT / f"{name}_seam_right.png")

    bottom = image.convert("RGB").crop((180, ih - 180, iw - 80, min(TARGET[1], ih + 400)))
    draw = ImageDraw.Draw(bottom)
    draw.line([(0, 180), (bottom.width, 180)], fill=(255, 0, 0), width=2)
    draw.text((8, 8), f"{name} BOTTOM", fill=(255, 255, 0))
    bottom.save(OUT / f"{name}_seam_bottom.png")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    source = Image.open(PILOT / "original" / "background_mock_1920x1080.png").convert("RGBA")
    x0, y0, x1, y1 = AUTH
    iw = TARGET[0] * (x1 - x0) // 1920
    ih = TARGET[1] * (y1 - y0) // 1080
    auth_img = source.crop((x0, y0, x1, y1)).resize((iw, ih), Image.Resampling.LANCZOS)
    auth = np.asarray(auth_img).astype(np.float32)
    auth_g = np.asarray(auth_img.convert("L"), np.float32)
    ai_path = AI_OUTPAINT if AI_OUTPAINT.is_file() else AI_OUTPAINT_FALLBACK
    if not ai_path.is_file():
        raise FileNotFoundError(f"missing Factory outpaint AI source: {AI_OUTPAINT}")
    print(f"ai_source={ai_path.name}")
    ai_full = (
        Image.open(ai_path)
        .convert("RGBA")
        .resize(TARGET, Image.Resampling.LANCZOS)
    )
    # Always remeasure shift for this AI frame (do not reuse another generation's offsets).
    import sys

    sys.path.insert(0, str(ROOT / "tools"))
    from preview_factory_realign_outpaint import find_mad_shift

    align = find_mad_shift(auth_img, auth_g, ai_full, iw, ih)
    tx, ty = int(align["tx"]), int(align["ty"])
    print(
        f"fresh_align mad={align['mad']:.3f} zero={align['zero_mad']:.3f} "
        f"dx={align['dx']} dy={align['dy']} paste=({tx},{ty})"
    )

    shifted = Image.new("RGBA", TARGET, (0, 0, 0, 0))
    shifted.paste(ai_full, (tx, ty))
    arr = np.asarray(shifted).astype(np.float32)

    empty = (arr[:, :, 3] < 8) | ((arr[:, :, :3].sum(axis=2) < 12) & (arr[:, :, 3] < 200))
    valid = ~empty
    print(f"empty_px={int(empty.sum())}")

    rgb = np.clip(arr[:, :, :3], 0, 255).astype(np.uint8)
    mask = empty.astype(np.uint8) * 255
    inpainted = cv2.inpaint(rgb, mask, inpaintRadius=8, flags=cv2.INPAINT_TELEA).astype(np.float32)

    # Simple edge replicate underpaint for large left/top voids.
    base = inpainted.copy()
    for y in range(TARGET[1]):
        row_valid = np.where(valid[y])[0]
        if row_valid.size == 0:
            continue
        first = int(row_valid[0])
        if first > 0:
            base[y, :first, :] = base[y, first : first + 1, :]
    for x in range(TARGET[0]):
        col_valid = np.where(valid[:, x])[0]
        if col_valid.size == 0:
            continue
        first = int(col_valid[0])
        if first > 0:
            base[:first, x, :] = base[first : first + 1, x, :]

    dist_empty = cv2.distanceTransform(empty.astype(np.uint8), cv2.DIST_L2, 5)
    near = np.clip(1.0 - dist_empty / 24.0, 0.0, 1.0)[:, :, None]
    filled = inpainted * near + base * (1.0 - near)
    filled = np.where(valid[:, :, None], arr[:, :, :3], filled)

    ys = np.arange(TARGET[1])[:, None]
    xs = np.arange(TARGET[0])[None, :]
    # Signed distance from right/bottom seams: negative inside plate, positive outside.
    dist_to_right_seam = (xs - (iw - 1)).astype(np.float32)
    dist_to_bottom_seam = (ys - (ih - 1)).astype(np.float32)
    dist_signed = np.maximum(dist_to_right_seam, dist_to_bottom_seam)
    # blur_dist=0 at INSET px inside the seam; grows across the seam and outward.
    blur_dist = np.maximum(dist_signed + BLUR_INSET_PX, 0.0)
    apply_blur = blur_dist > 0.0

    # Hard-preserve authentic plate. Thin feather at the boundary only.
    composed = filled.copy()
    mask = np.zeros((TARGET[1], TARGET[0]), dtype=np.uint8)
    mask[:ih, :iw] = 255
    mask = (
        np.asarray(Image.fromarray(mask, "L").filter(ImageFilter.GaussianBlur(SEAM_FEATHER))).astype(
            np.float32
        )
        / 255.0
    )
    base = composed.copy()
    base[:ih, :iw] = auth[:, :, :3]
    composed = base * mask[:, :, None] + composed * (1.0 - mask[:, :, None])
    # Keep deep interior sharp; leave an inset strip free for seam-hiding blur.
    inset_i = int(round(BLUR_INSET_PX))
    deep_h = max(0, ih - inset_i)
    deep_w = max(0, iw - inset_i)
    composed[:deep_h, :deep_w] = auth[:deep_h, :deep_w, :3]

    preblur = Image.fromarray(
        np.clip(np.dstack([composed, np.full((TARGET[1], TARGET[0]), 255)]), 0, 255).astype(np.uint8),
        "RGBA",
    )

    blurred_out = progressive_blur(composed, blur_dist, apply_blur)
    blurred_out[:deep_h, :deep_w] = auth[:deep_h, :deep_w, :3]
    final = Image.fromarray(
        np.clip(np.dstack([blurred_out, np.full((TARGET[1], TARGET[0]), 255)]), 0, 255).astype(np.uint8),
        "RGBA",
    )

    ai_tag = ai_path.stem.replace("factory_background_outpaint_", "")
    label = f"t7_{ai_tag}_tx{tx}_ty{ty}_fill_progblur"
    final.save(OUT / f"compose_{label}.png")
    preblur.save(OUT / f"compose_{label}_preblur.png")
    preview(final, label, iw, ih)
    preview(preblur, f"{label}_preblur", iw, ih)

    thumbs = []
    for name in (
        f"stale_shift_{ai_tag}_1080.png",
        f"{label}_1080.png",
    ):
        path = OUT / name
        if path.is_file():
            thumbs.append(Image.open(path).resize((640, 360)))
    # Also include prior realigned preview if present
    realigned = OUT / f"realigned_{ai_tag}_tx{tx}_ty{ty}_1080.png"
    if realigned.is_file():
        thumbs = [Image.open(realigned).resize((640, 360))]
        thumbs.append(Image.open(OUT / f"{label}_1080.png").resize((640, 360))) if (OUT / f"{label}_1080.png").is_file() else None
    if thumbs:
        sheet = Image.new("RGB", (640 * len(thumbs), 360))
        for index, thumb in enumerate(thumbs):
            sheet.paste(thumb, (index * 640, 0))
        sheet.save(OUT / f"contact_fresh_align_{ai_tag}.png")

    (OUT / "align_params.txt").write_text(
        "method=t7_shift_fill_progressive_blur\n"
        f"ai_source={ai_path.as_posix()}\n"
        f"tx={tx}\nty={ty}\n"
        f"align_mad={align['mad']:.4f}\n"
        f"align_zero_mad={align['zero_mad']:.4f}\n"
        "fill=edge_replicate+telea_inpaint\n"
        f"prog_blur_max_r={MAX_BLUR_R}\n"
        f"prog_blur_falloff_px={BLUR_FALLOFF_PX}\n"
        f"prog_blur_inset_px={BLUR_INSET_PX}\n"
        f"prog_blur_seam_r={SEAM_BLUR_R}\n"
        f"preview=compose_{label}.png\n"
        "installed=false\n",
        encoding="utf-8",
    )
    print(f"PREVIEW ONLY {label}")
    print(f"wrote {OUT / f'compose_{label}.png'}")


if __name__ == "__main__":
    main()
