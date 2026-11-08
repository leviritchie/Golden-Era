#!/usr/bin/env python3
"""Compose 4K custom-town backgrounds with the Factory-approved recipe.

Recipe (per faction):
1. Load 1920x1080 mock + AI outpaint
2. Fresh MAD translation align (never reuse another faction's shift)
3. Fill black holes (edge replicate + Telea)
4. Hard-preserve authentic plate with thin feather
5. Progressive gaussian blur creeping inside the seam

Writes working artifacts under artifacts/custom_town_4k_work/{faction}/
and clean finals only under artifacts/custom_town_4k_finals/
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageFilter

ROOT = Path(__file__).resolve().parents[1]
MOD = ROOT / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod"
TOWN_REFS = MOD / "homm3_runtime_assets" / "town_scene_refs"
WORK = ROOT / "artifacts" / "custom_town_4k_work"
FINALS = ROOT / "artifacts" / "custom_town_4k_finals"
AUTH = (0, 0, 1440, 673)
TARGET = (3840, 2160)
MAX_BLUR_R = 32.0
BLUR_FALLOFF_PX = 1100.0
BLUR_INSET_PX = 72.0
SEAM_BLUR_R = 5.0
SEAM_FEATHER = 256
RADII = [0, 1, 2, 4, 7, 11, 16, 22, 28, 32]

FACTIONS = [
    "bulwark",
    "castle",
    "conflux",
    "cove",
    "dungeon",
    "factory",
    "fortress",
    "inferno",
    "necropolis",
    "rampart",
    "stronghold",
    "tower",
]


def find_mad_shift(auth_img: Image.Image, auth_g: np.ndarray, ai_img: Image.Image, iw: int, ih: int) -> dict:
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
    return {
        "mad": bestf[0],
        "zero_mad": float(np.mean(np.abs(tpl - plate[cy0:cy1:2, cx0:cx1:2]))),
        "dx": dx,
        "dy": dy,
        "tx": -dx,
        "ty": -dy,
    }


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
        band = apply_mask & (desired_r >= radius0)
        if index < len(RADII) - 2:
            band = band & (desired_r < radius1)
        if not np.any(band):
            continue
        t = np.clip((desired_r - radius0) / max(radius1 - radius0, 1e-6), 0.0, 1.0)[:, :, None]
        mixed = blurred[index] * (1.0 - t) + blurred[index + 1] * t
        out[band] = mixed[band]
    return out


def compose_faction(faction: str, ai_path: Path, *, write_final: bool = True) -> dict:
    scene = TOWN_REFS / f"homm3_{faction}"
    mock = scene / "mockups" / f"homm3_{faction}_background_mock_1920x1080.png"
    if not mock.is_file():
        raise FileNotFoundError(mock)
    if not ai_path.is_file():
        raise FileNotFoundError(ai_path)

    work = WORK / faction
    work.mkdir(parents=True, exist_ok=True)
    FINALS.mkdir(parents=True, exist_ok=True)

    source = Image.open(mock).convert("RGBA")
    if source.size != (1920, 1080):
        raise RuntimeError(f"{faction} mock size {source.size}")
    x0, y0, x1, y1 = AUTH
    iw = TARGET[0] * (x1 - x0) // 1920
    ih = TARGET[1] * (y1 - y0) // 1080
    auth_img = source.crop((x0, y0, x1, y1)).resize((iw, ih), Image.Resampling.LANCZOS)
    auth = np.asarray(auth_img).astype(np.float32)
    auth_g = np.asarray(auth_img.convert("L"), np.float32)
    ai = Image.open(ai_path).convert("RGBA").resize(TARGET, Image.Resampling.LANCZOS)
    align = find_mad_shift(auth_img, auth_g, ai, iw, ih)
    tx, ty = int(align["tx"]), int(align["ty"])

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
    filled = np.where(valid[:, :, None], arr[:, :, :3], inpainted * near + base * (1.0 - near))

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

    work_out = work / f"homm3_{faction}_background_upscaled_3840x2160.png"
    final_name = f"homm3_{faction}_background_upscaled_3840x2160.png"
    final_out = FINALS / final_name
    final.save(work_out)
    if write_final:
        shutil.copy2(work_out, final_out)
    meta = {
        "faction": faction,
        "aiSource": ai_path.as_posix(),
        "mock": mock.as_posix(),
        "pasteTx": tx,
        "pasteTy": ty,
        "alignMad": align["mad"],
        "alignZeroMad": align["zero_mad"],
        "final": final_out.as_posix() if write_final else work_out.as_posix(),
        "size": list(TARGET),
        "authRect": list(AUTH),
        "composeMethod": "fresh_mad_shift_fill_progressive_blur",
        "seamFeather": SEAM_FEATHER,
    }
    (work / "compose_meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    print(
        f"{faction}: paste=({tx},{ty}) mad={align['mad']:.2f} -> {final_out.name}"
    )
    return meta


def scale_positions(faction: str) -> None:
    positions = TOWN_REFS / f"homm3_{faction}" / "layers" / "positions.json"
    if not positions.is_file():
        raise FileNotFoundError(positions)
    data = json.loads(positions.read_text(encoding="utf-8"))
    basis = data.get("coordinateBasis") or {}
    canvas = basis.get("referenceCanvas") or {}
    if int(canvas.get("w", 0)) == 3840 and int(canvas.get("h", 0)) == 2160:
        print(f"{faction}: positions already 4K")
        return
    if int(canvas.get("w", 0)) != 1920 or int(canvas.get("h", 0)) != 1080:
        raise RuntimeError(f"{faction}: unexpected canvas {canvas}")
    # Runtime places via reference_* + referenceCanvas. Keep VCMI x/y untouched
    # (Fortress contract compares those axes to VCMI source).
    for row in data.get("layers", []):
        for key in ("reference_x", "reference_y", "reference_w", "reference_h"):
            if key in row:
                row[key] = row[key] * 2
    basis["referenceCanvas"] = {"w": 3840, "h": 2160}
    plate = basis.get("referencePlate") or {}
    for key in ("x", "y", "w", "h"):
        if key in plate:
            plate[key] = plate[key] * 2
    basis["referencePlate"] = plate
    basis["uniformScale"] = 3.6
    basis["xScale"] = 3.6
    basis["yScale"] = 3.6
    basis["source"] = (
        f"vcmi-top-left-800x374-on-3840x2160-{faction}-4k-outpaint-"
        "source-plate-preserved-right-bottom-generated"
    )
    basis["runtimeLayout"] = f"{faction}_4k_outpaint_v1"
    data["coordinateBasis"] = basis
    positions.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print(f"{faction}: positions scaled to 4K (reference_* only; VCMI x/y preserved)")


def install_background(faction: str) -> Path:
    final = FINALS / f"homm3_{faction}_background_upscaled_3840x2160.png"
    if not final.is_file():
        raise FileNotFoundError(final)
    dest = TOWN_REFS / f"homm3_{faction}" / "mockups" / final.name
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(final, dest)
    print(f"{faction}: installed {dest.relative_to(ROOT).as_posix()}")
    return dest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--faction", action="append", default=[])
    parser.add_argument("--ai-dir", type=Path, default=WORK / "_ai_outpaints")
    parser.add_argument("--compose", action="store_true")
    parser.add_argument("--scale-positions", action="store_true")
    parser.add_argument("--install", action="store_true")
    parser.add_argument("--copy-factory-final", action="store_true")
    args = parser.parse_args()
    factions = args.faction or [f for f in FACTIONS if f != "factory"]
    FINALS.mkdir(parents=True, exist_ok=True)
    WORK.mkdir(parents=True, exist_ok=True)

    if args.copy_factory_final:
        src = (
            TOWN_REFS
            / "homm3_factory"
            / "mockups"
            / "homm3_factory_background_upscaled_3840x2160.png"
        )
        if src.is_file():
            shutil.copy2(src, FINALS / src.name)
            print(f"copied factory final -> {FINALS / src.name}")

    if args.compose:
        for faction in factions:
            ai = args.ai_dir / f"homm3_{faction}_background_outpaint.png"
            compose_faction(faction, ai)
    if args.scale_positions:
        for faction in factions:
            scale_positions(faction)
    if args.install:
        for faction in factions:
            install_background(faction)
            if args.scale_positions or True:
                # always keep positions with installed bg
                try:
                    scale_positions(faction)
                except Exception as exc:
                    print(f"{faction}: positions skip: {exc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
