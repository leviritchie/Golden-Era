#!/usr/bin/env python3
"""Import green-screen campaign hero upscales into homm3_hero_portraits_upscaled/.

Reads the imagegen zip (green plate background), flood-fills chroma green from
the image border to alpha, despills fringe, then pads to the existing 1254x1254
circular-alpha upscaled portrait contract. Roster SIDs replace matching
upscaled PNGs; campaign-only keys are kept under artifacts for dialog use.
"""

from __future__ import annotations

import argparse
import json
import re
import zipfile
from collections import deque
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ZIP = Path.home() / "Downloads" / "homm3_campaign_hero_portraits_imagegen_upscaled_green.zip"
DEFAULT_UPSCALED = (
    ROOT
    / "Heroes of Might & Magic Olden Era Playtest"
    / "OfflineUnlockMod"
    / "homm3_hero_portraits_upscaled"
)
DEFAULT_BASE = (
    ROOT
    / "Heroes of Might & Magic Olden Era Playtest"
    / "OfflineUnlockMod"
    / "homm3_hero_portraits"
)
DEFAULT_CAMPAIGN_OUT = ROOT / "artifacts" / "homm3_campaign_hero_portraits_keyed"
SID_RE = re.compile(r"^(homm3_[a-z]+_hero_\d+)__", re.IGNORECASE)
OUTPUT_SIDE = 1254


def is_green_bg(r: np.ndarray, g: np.ndarray, b: np.ndarray) -> np.ndarray:
    return (g >= 120) & (g >= r + 30) & (g >= b + 30) & ((r + b) < 220)


def key_green_from_border(img: Image.Image) -> Image.Image:
    rgba = np.asarray(img.convert("RGBA"), dtype=np.uint8)
    h, w = rgba.shape[:2]
    rgb = rgba[:, :, :3].astype(np.float32)
    r = rgb[:, :, 0]
    g = rgb[:, :, 1]
    b = rgb[:, :, 2]
    plate = np.array([20.0, 243.0, 14.0], dtype=np.float32)
    dist = np.linalg.norm(rgb - plate, axis=2)

    # Global soft key against the chroma plate (catches trapped green pockets).
    plate_alpha = np.clip((dist - 18.0) / 55.0, 0.0, 1.0)
    strong_plate = dist < 70.0
    sat_green = (g >= 150) & (g >= r + 35) & (g >= b + 35) & ((r + b) < 240)

    green = is_green_bg(r.astype(np.int16), g.astype(np.int16), b.astype(np.int16)) | strong_plate
    visited = np.zeros((h, w), dtype=bool)
    q: deque[tuple[int, int]] = deque()
    for x in range(w):
        for y in (0, h - 1):
            if green[y, x]:
                visited[y, x] = True
                q.append((x, y))
    for y in range(h):
        for x in (0, w - 1):
            if green[y, x] and not visited[y, x]:
                visited[y, x] = True
                q.append((x, y))
    while q:
        x, y = q.popleft()
        for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
            if 0 <= nx < w and 0 <= ny < h and not visited[ny, nx] and green[ny, nx]:
                visited[ny, nx] = True
                q.append((nx, ny))

    # Also treat strong plate greens as background even if enclosed.
    bg = visited | strong_plate | ((dist < 45.0) & sat_green)

    weak = (g >= 90) & (g >= r + 15) & (g >= b + 15)
    # Vectorized 2px dilation of bg into weak greens.
    bg_u8 = (bg.astype(np.uint8) * 255)
    dilated = np.asarray(Image.fromarray(bg_u8, "L").filter(ImageFilter.MaxFilter(5)), dtype=np.uint8) > 0
    bg = bg | (dilated & weak)

    hard = Image.fromarray(np.where(bg, 0, 255).astype(np.uint8), "L")
    soft = hard.filter(ImageFilter.GaussianBlur(radius=1.25))
    flood_alpha = np.asarray(soft, dtype=np.float32) / 255.0
    alpha = np.minimum(flood_alpha, plate_alpha) * 255.0

    edge = np.asarray(hard.filter(ImageFilter.FIND_EDGES), dtype=np.float32) / 255.0
    edge_band = (
        np.asarray(
            Image.fromarray((edge * 255).astype(np.uint8), "L").filter(ImageFilter.MaxFilter(7)),
            dtype=np.float32,
        )
        / 255.0
    )
    max_rb = np.maximum(r, b)
    excess = np.clip(g - max_rb, 0, None)
    # Kill remaining saturated greens on the silhouette fringe.
    kill = (edge_band > 0.15) & (g > 150) & (excess > 35) & ((r + b) < 300)
    despill_w = np.clip(excess / 55.0, 0, 1) * edge_band * (alpha > 8)
    g2 = g * (1.0 - despill_w) + max_rb * despill_w

    out = rgba.astype(np.float32)
    out[:, :, 1] = g2
    out[:, :, 3] = np.where(kill | bg, 0.0, alpha)
    clear = out[:, :, 3] < 10
    out[clear, 0:3] = 0
    return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8), "RGBA")


def circular_square(img: Image.Image, side: int = OUTPUT_SIDE) -> Image.Image:
    rgba = img.convert("RGBA")
    alpha = np.asarray(rgba.getchannel("A"))
    ys, xs = np.where(alpha > 16)
    if len(xs) == 0:
        raise ValueError("portrait empty after green key")
    x0, x1 = int(xs.min()), int(xs.max())
    y0, y1 = int(ys.min()), int(ys.max())
    pad = 12
    x0 = max(0, x0 - pad)
    y0 = max(0, y0 - pad)
    x1 = min(rgba.width - 1, x1 + pad)
    y1 = min(rgba.height - 1, y1 + pad)
    cropped = rgba.crop((x0, y0, x1 + 1, y1 + 1))
    target = int(side * 0.92)
    scale = target / max(cropped.size)
    nw = max(1, int(cropped.width * scale))
    nh = max(1, int(cropped.height * scale))
    cropped = cropped.resize((nw, nh), Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    canvas.alpha_composite(cropped, ((side - cropped.width) // 2, (side - cropped.height) // 2))
    s = 4
    mask = Image.new("L", (side * s, side * s), 0)
    draw = ImageDraw.Draw(mask)
    draw.ellipse((s, s, side * s - s - 1, side * s - s - 1), fill=255)
    mask = mask.resize((side, side), Image.Resampling.LANCZOS)
    a = Image.composite(canvas.getchannel("A"), Image.new("L", (side, side), 0), mask)
    canvas.putalpha(a)
    return canvas


def to_base_64(circled: Image.Image) -> Image.Image:
    return circled.resize((64, 64), Image.Resampling.LANCZOS)


def parse_zip_member(name: str) -> tuple[str | None, str]:
    filename = Path(name).name
    stem = Path(filename).stem
    match = SID_RE.match(stem + "__")
    # stem is like homm3_castle_hero_17__catherine
    m = re.match(r"^(homm3_[a-z]+_hero_\d+)__(.+)$", stem, re.IGNORECASE)
    if m:
        return m.group(1).lower(), stem
    return None, stem


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--zip", type=Path, default=DEFAULT_ZIP)
    parser.add_argument("--upscaled-dir", type=Path, default=DEFAULT_UPSCALED)
    parser.add_argument("--base-dir", type=Path, default=DEFAULT_BASE)
    parser.add_argument("--campaign-out", type=Path, default=DEFAULT_CAMPAIGN_OUT)
    parser.add_argument("--skip-base64", action="store_true")
    args = parser.parse_args()

    if not args.zip.is_file():
        raise SystemExit(f"missing zip: {args.zip}")

    args.upscaled_dir.mkdir(parents=True, exist_ok=True)
    args.campaign_out.mkdir(parents=True, exist_ok=True)

    roster: list[dict] = []
    campaign_only: list[dict] = []

    with zipfile.ZipFile(args.zip) as zf:
        members = [n for n in zf.namelist() if n.lower().endswith(".png")]
        for member in sorted(members):
            sid, stem = parse_zip_member(member)
            raw = Image.open(zf.open(member))
            keyed = key_green_from_border(raw)
            circled = circular_square(keyed)
            fringe = 0
            arr = np.asarray(circled)
            rr, gg, bb, aa = (
                arr[:, :, 0].astype(np.int16),
                arr[:, :, 1].astype(np.int16),
                arr[:, :, 2].astype(np.int16),
                arr[:, :, 3],
            )
            fringe = int(((aa > 64) & (gg > 200) & (gg > rr + 50) & (gg > bb + 50)).sum())

            campaign_path = args.campaign_out / f"{stem}.png"
            circled.save(campaign_path)

            entry = {
                "zipMember": member,
                "stem": stem,
                "sid": sid,
                "outputSize": list(circled.size),
                "fringePx": fringe,
                "campaignPng": str(campaign_path.relative_to(ROOT)).replace("\\", "/"),
            }

            if sid:
                dest = args.upscaled_dir / f"{sid}.png"
                circled.save(dest)
                entry["upscaledPng"] = str(dest.relative_to(ROOT)).replace("\\", "/")
                if not args.skip_base64:
                    base_png = to_base_64(circled)
                    base_dest = args.base_dir / f"{sid}.png"
                    base_png.save(base_dest)
                    entry["basePng"] = str(base_dest.relative_to(ROOT)).replace("\\", "/")
                roster.append(entry)
                print(f"OK roster {sid} fringe={fringe}")
            else:
                campaign_only.append(entry)
                print(f"OK campaign-only {stem} fringe={fringe}")

    # Refresh upscaled manifest from base manifest names/sources, mark import.
    base_manifest_path = args.base_dir / "manifest.json"
    ups_manifest_path = args.upscaled_dir / "manifest.json"
    if base_manifest_path.is_file():
        manifest = json.loads(base_manifest_path.read_text(encoding="utf-8"))
        for row in roster:
            sid = row["sid"]
            if sid in (manifest.get("entries") or {}):
                manifest["entries"][sid]["upscalePending"] = False
                manifest["entries"][sid]["size"] = [OUTPUT_SIDE, OUTPUT_SIDE]
                manifest["entries"][sid]["circularAlpha"] = True
        manifest["campaignGreenUpscaleImport"] = {
            "sourceZip": str(args.zip),
            "tool": "import_homm3_campaign_green_upscaled_portraits.py",
            "outputSide": OUTPUT_SIDE,
            "importedSids": [r["sid"] for r in roster],
        }
        ups_manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    report = {
        "schema": "homm3.campaign_green_upscale_import.v1",
        "zip": str(args.zip),
        "rosterImported": roster,
        "campaignOnly": campaign_only,
        "rosterCount": len(roster),
        "campaignOnlyCount": len(campaign_only),
    }
    report_path = args.campaign_out / "import_report.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"roster": len(roster), "campaignOnly": len(campaign_only), "report": str(report_path)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
