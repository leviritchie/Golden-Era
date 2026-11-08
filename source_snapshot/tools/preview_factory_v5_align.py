#!/usr/bin/env python3
"""Preview Factory AI v5 outpaint alignment candidates (no install)."""
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


def warp_affine(img: Image.Image, matrix: np.ndarray) -> Image.Image:
    arr = cv2.warpAffine(
        np.asarray(img),
        matrix.astype(np.float32),
        TARGET,
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_REPLICATE,
    )
    return Image.fromarray(arr)


def warp_scale_shift(img: Image.Image, scale: float, dx: int, dy: int) -> Image.Image:
    nw = max(8, int(round(TARGET[0] * scale)))
    nh = max(8, int(round(TARGET[1] * scale)))
    scaled = img.resize((nw, nh), Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", TARGET, (0, 0, 0, 255))
    canvas.paste(scaled, (int(dx), int(dy)))
    return canvas


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    source = Image.open(PILOT / "original" / "background_mock_1920x1080.png").convert("RGBA")
    x0, y0, x1, y1 = AUTH
    iw = TARGET[0] * (x1 - x0) // 1920
    ih = TARGET[1] * (y1 - y0) // 1080
    auth_img = source.crop((x0, y0, x1, y1)).resize((iw, ih), Image.Resampling.LANCZOS)
    auth = np.asarray(auth_img).astype(np.float32)
    v5_img = (
        Image.open(PILOT / "ai" / "factory_background_outpaint_terrain_v5.png")
        .convert("RGBA")
        .resize(TARGET, Image.Resampling.LANCZOS)
    )

    def cross_boundary_score(warped: Image.Image) -> float:
        w = np.asarray(warped.convert("RGBA")).astype(np.float32)
        band = 32
        left = auth[:, iw - band : iw, :3]
        right = w[:ih, iw : iw + band, :3]
        c1 = float(np.mean(np.abs(left.mean(axis=1) - right.mean(axis=1))))
        g1 = float(
            np.mean(np.abs(np.diff(left.mean(axis=1), axis=0) - np.diff(right.mean(axis=1), axis=0)))
        )
        top = auth[ih - band : ih, :, :3]
        bot = w[ih : ih + band, :iw, :3]
        c2 = float(np.mean(np.abs(top.mean(axis=1) - bot.mean(axis=1))))
        g2 = float(
            np.mean(np.abs(np.diff(top.mean(axis=1), axis=0) - np.diff(bot.mean(axis=1), axis=0)))
        )
        return c1 + c2 + 0.5 * (g1 + g2)

    def interior_mad(warped: Image.Image, step: int = 6) -> float:
        w = np.asarray(warped.convert("RGBA")).astype(np.float32)
        a = auth[80 : ih - 80 : step, 80 : iw - 80 : step, :3]
        b = w[80 : ih - 80 : step, 80 : iw - 80 : step, :3]
        return float(np.mean(np.abs(a - b)))

    def compose_hard(warped: Image.Image, seam: int = 14) -> Image.Image:
        gen = np.asarray(warped.convert("RGBA")).astype(np.float32)
        lmask = np.zeros((TARGET[1], TARGET[0]), dtype=bool)
        lmask[:, iw:] = True
        lmask[ih:, :] = True
        strip = 48
        samples = np.concatenate(
            [
                auth[:, max(0, iw - strip) : iw, :3].reshape(-1, 3),
                auth[max(0, ih - strip) : ih, :, :3].reshape(-1, 3),
            ],
            axis=0,
        )
        src_mean = samples.mean(axis=0)
        src_std = samples.std(axis=0) + 1e-6
        near = np.concatenate(
            [
                gen[:ih, iw : min(TARGET[0], iw + strip), :3].reshape(-1, 3),
                gen[ih : min(TARGET[1], ih + strip), :iw, :3].reshape(-1, 3),
            ],
            axis=0,
        )
        if near.size:
            gen_mean = near.mean(axis=0)
            gen_std = near.std(axis=0) + 1e-6
            for channel in range(3):
                adjusted = (gen[:, :, channel] - gen_mean[channel]) * (
                    src_std[channel] / gen_std[channel]
                ) + src_mean[channel]
                out_ch = gen[:, :, channel].copy()
                out_ch[lmask] = np.clip(adjusted[lmask], 0, 255)
                gen[:, :, channel] = out_ch
        mask = np.zeros((TARGET[1], TARGET[0]), dtype=np.uint8)
        mask[:ih, :iw] = 255
        mask = (
            np.asarray(Image.fromarray(mask, "L").filter(ImageFilter.GaussianBlur(seam))).astype(
                np.float32
            )
            / 255.0
        )
        base = gen.copy()
        base[:ih, :iw] = auth
        result = base * mask[:, :, None] + gen * (1.0 - mask[:, :, None])
        margin = max(seam * 2, 24)
        result[: ih - margin, : iw - margin] = auth[: ih - margin, : iw - margin]
        result[..., 3] = 255
        return Image.fromarray(np.clip(result, 0, 255).astype(np.uint8), "RGBA")

    cands: dict[str, Image.Image] = {"A_identity": v5_img}

    # MAD translation: auth(x,y) ~= v5(x-179, y-164)
    matrix_trans = np.array([[1.0, 0.0, -179.0], [0.0, 1.0, -164.0]], dtype=np.float32)
    cands["B_trans_mad"] = warp_affine(v5_img, matrix_trans)
    cands["C_paste_179_164"] = warp_scale_shift(v5_img, 1.0, 179, 164)

    auth_g = np.asarray(auth_img.convert("L"))
    v5_plate = np.asarray(v5_img.crop((0, 0, iw, ih)).convert("L"))
    orb = cv2.ORB_create(5000)
    keypoints_a, desc_a = orb.detectAndCompute(auth_g, None)
    keypoints_b, desc_b = orb.detectAndCompute(v5_plate, None)
    if desc_a is not None and desc_b is not None:
        matcher = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
        matches = sorted(matcher.match(desc_a, desc_b), key=lambda item: item.distance)[:400]
        pts_a = np.float32([keypoints_a[item.queryIdx].pt for item in matches])
        pts_b = np.float32([keypoints_b[item.trainIdx].pt for item in matches])
        matrix_sim, inliers = cv2.estimateAffinePartial2D(
            pts_b, pts_a, method=cv2.RANSAC, ransacReprojThreshold=5.0
        )
        inlier_count = int(inliers.sum()) if inliers is not None else 0
        print(f"ORB similarity matrix={matrix_sim} inliers={inlier_count}")
        if matrix_sim is not None:
            cands["D_orb_similarity"] = warp_affine(v5_img, matrix_sim.astype(np.float32))
    else:
        print("ORB failed")

    auth_n = (auth_g.astype(np.float32) - auth_g.mean()) / (auth_g.std() + 1e-6)
    plate_n = (v5_plate.astype(np.float32) - v5_plate.mean()) / (v5_plate.std() + 1e-6)
    half = 2
    auth_h = cv2.resize(auth_n, (iw // half, ih // half))
    plate_h = cv2.resize(plate_n, (iw // half, ih // half))
    warp_init = np.array([[1.0, 0.0, -179.0 / half], [0.0, 1.0, -164.0 / half]], dtype=np.float32)
    criteria = (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 300, 1e-7)
    try:
        corr, matrix_ecc = cv2.findTransformECC(
            auth_h, plate_h, warp_init.copy(), cv2.MOTION_EUCLIDEAN, criteria, None, 5
        )
        matrix_ecc[0, 2] *= half
        matrix_ecc[1, 2] *= half
        print(f"ECC corr={corr} matrix={matrix_ecc}")
        cands["E_ecc_euclidean"] = warp_affine(v5_img, matrix_ecc)
    except cv2.error as exc:
        print(f"ECC fail: {exc}")

    v5_small = v5_img.resize((TARGET[0] // 4, TARGET[1] // 4), Image.Resampling.BILINEAR)
    auth_small = auth_img.resize((iw // 4, ih // 4), Image.Resampling.BILINEAR)
    iw_s, ih_s = iw // 4, ih // 4

    def cross_boundary_small(scale: float, dx: int, dy: int) -> float:
        nw = max(8, int((TARGET[0] // 4) * scale))
        nh = max(8, int((TARGET[1] // 4) * scale))
        scaled = v5_small.resize((nw, nh), Image.Resampling.BILINEAR)
        canvas = Image.new("RGBA", (TARGET[0] // 4, TARGET[1] // 4), (0, 0, 0, 255))
        canvas.paste(scaled, (dx, dy))
        warped = np.asarray(canvas).astype(np.float32)
        auth_s = np.asarray(auth_small).astype(np.float32)
        band = 8
        left = auth_s[:, iw_s - band : iw_s, :3]
        right = warped[:ih_s, iw_s : iw_s + band, :3]
        top = auth_s[ih_s - band : ih_s, :, :3]
        bot = warped[ih_s : ih_s + band, :iw_s, :3]
        if right.shape != left.shape or bot.shape != top.shape:
            return 1e9
        return float(
            np.mean(np.abs(left.mean(axis=1) - right.mean(axis=1)))
            + np.mean(np.abs(top.mean(axis=1) - bot.mean(axis=1)))
        )

    best_small = (1e9, 1.0, 45, 41)
    for scale in np.linspace(0.94, 1.12, 19):
        for dy in range(20, 70):
            for dx in range(20, 80):
                score = cross_boundary_small(float(scale), dx, dy)
                if score < best_small[0]:
                    best_small = (score, float(scale), dx, dy)
    print(
        "small scale/shift best",
        best_small,
        "full",
        (best_small[0], best_small[1], best_small[2] * 4, best_small[3] * 4),
    )

    scale, dx, dy = best_small[1], best_small[2] * 4, best_small[3] * 4
    best_full = (cross_boundary_score(warp_scale_shift(v5_img, scale, dx, dy)), scale, dx, dy)
    for scale2 in np.linspace(scale - 0.02, scale + 0.02, 5):
        for dy2 in range(dy - 8, dy + 9, 2):
            for dx2 in range(dx - 8, dx + 9, 2):
                image = warp_scale_shift(v5_img, float(scale2), dx2, dy2)
                score = cross_boundary_score(image)
                if score < best_full[0]:
                    best_full = (score, float(scale2), dx2, dy2)
    print("fine F", best_full)
    cands["F_scale_shift"] = warp_scale_shift(v5_img, best_full[1], best_full[2], best_full[3])

    rows = []
    for name, image in cands.items():
        cross = cross_boundary_score(image)
        mad = interior_mad(image)
        rows.append((cross, mad, name))
        print(f"{name}: cross={cross:.2f} interior_mad={mad:.2f}")
    rows.sort()

    preview_names = [
        name
        for name in (
            "A_identity",
            "B_trans_mad",
            "D_orb_similarity",
            "E_ecc_euclidean",
            "F_scale_shift",
        )
        if name in cands
    ]
    composed: dict[str, Image.Image] = {}
    for name in preview_names:
        composed[name] = compose_hard(cands[name])
        composed[name].save(OUT / f"compose_{name}.png")

    def make_preview(image: Image.Image, label: str) -> None:
        half = image.convert("RGB").resize((1920, 1080), Image.Resampling.LANCZOS)
        draw = ImageDraw.Draw(half)
        draw.rectangle([0, 0, iw // 2 - 1, ih // 2 - 1], outline=(255, 0, 0), width=2)
        draw.rectangle([0, 0, 900, 34], fill=(0, 0, 0))
        draw.text((8, 8), label, fill=(255, 255, 0))
        half.save(OUT / f"{label}_1080.png")
        right = image.convert("RGB").crop((iw - 220, 160, min(TARGET[0], iw + 420), ih - 20))
        draw = ImageDraw.Draw(right)
        draw.line([(220, 0), (220, right.height)], fill=(255, 0, 0), width=2)
        draw.text((8, 8), f"{label} RIGHT", fill=(255, 255, 0))
        right.save(OUT / f"{label}_seam_right.png")
        bottom = image.convert("RGB").crop((180, ih - 180, iw - 80, min(TARGET[1], ih + 400)))
        draw = ImageDraw.Draw(bottom)
        draw.line([(0, 180), (bottom.width, 180)], fill=(255, 0, 0), width=2)
        draw.text((8, 8), f"{label} BOTTOM", fill=(255, 255, 0))
        bottom.save(OUT / f"{label}_seam_bottom.png")

    for name in preview_names:
        make_preview(composed[name], name)

    thumbs = [Image.open(OUT / f"{name}_1080.png").resize((640, 360)) for name in preview_names]
    sheet = Image.new("RGB", (len(thumbs) * 640, 360), (20, 20, 20))
    for index, thumb in enumerate(thumbs):
        sheet.paste(thumb, (index * 640, 0))
    sheet.save(OUT / "contact_aligned_candidates.png")

    (OUT / "align_params.txt").write_text(
        "\n".join(f"{cross:.3f}\t{mad:.3f}\t{name}" for cross, mad, name in rows)
        + f"\n\nF_params scale={best_full[1]} dx={best_full[2]} dy={best_full[3]}\n",
        encoding="utf-8",
    )
    print("BEST by cross-boundary", rows[0])
    print("OUT", OUT)


if __name__ == "__main__":
    main()
