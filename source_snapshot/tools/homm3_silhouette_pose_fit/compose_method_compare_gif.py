#!/usr/bin/env python3
"""Build a multi-method side-by-side GIF from pose-fit preview mesh frames."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]


def _load_font(size: int = 16):
    for name in ("arial.ttf", "segoeui.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _find_frame(folder: Path, index: int) -> Path | None:
    stem = f"{index:02d}"
    candidates = (
        folder / f"mesh_{stem}.png",
        folder / f"side_{stem}.png",
        folder / f"frame_{stem}.png",
        folder / f"preview_{stem}.png",
        folder / f"{stem}.png",
        folder / "frames" / f"mesh_{stem}.png",
        folder / "frames" / f"side_{stem}.png",
        folder / "preview" / "frames" / f"mesh_{stem}.png",
        folder / "solved_rgb" / f"{stem}.png",
        folder / "preview" / f"preview_{stem}.png",
    )
    for cand in candidates:
        if cand.is_file():
            return cand
    return None


def _fit_cell(im: Image.Image, size: tuple[int, int], bg=(18, 18, 22)) -> Image.Image:
    cell = Image.new("RGB", size, bg)
    im = im.convert("RGBA")
    # letterbox
    scale = min(size[0] / im.width, size[1] / im.height)
    nw, nh = max(1, int(im.width * scale)), max(1, int(im.height * scale))
    resized = im.resize((nw, nh), Image.Resampling.NEAREST if scale >= 2 else Image.Resampling.LANCZOS)
    x = (size[0] - nw) // 2
    y = (size[1] - nh) // 2
    cell.paste(resized, (x, y), resized if resized.mode == "RGBA" else None)
    return cell


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--hold", type=int, default=5)
    ap.add_argument(
        "--duration-ms",
        type=int,
        default=0,
        help="Duration per displayed source frame. 0 preserves the 12 fps default.",
    )
    ap.add_argument("--cell-w", type=int, default=280)
    ap.add_argument("--cell-h", type=int, default=320)
    ap.add_argument(
        "--panel",
        action="append",
        nargs=2,
        metavar=("LABEL", "DIR_OR_GLOB"),
        help="Label and preview frames dir (expects mesh_XX.png) or sprite frame_XX.png dir",
        required=True,
    )
    ap.add_argument("--frame-count", type=int, default=8)
    ap.add_argument(
        "--cols",
        type=int,
        default=0,
        help="Wrap panels into this many columns. 0 keeps a single row.",
    )
    args = ap.parse_args()

    panels: list[tuple[str, Path]] = []
    for label, raw in args.panel:
        p = Path(raw)
        if not p.is_absolute():
            p = ROOT / p
        panels.append((label, p))

    font = _load_font(15)
    font_sm = _load_font(13)
    header_h = 28
    cell_w, cell_h = args.cell_w, args.cell_h
    n = args.frame_count
    cols = int(args.cols) if int(args.cols) > 0 else len(panels)
    if cols < 1:
        raise ValueError("--cols must be positive")
    rows = (len(panels) + cols - 1) // cols
    canvas_w = cols * cell_w
    canvas_h = rows * (header_h + cell_h)
    hold = max(1, args.hold)
    if int(args.duration_ms) < 0:
        raise ValueError("--duration-ms must be 0 or positive")

    frames_out: list[Image.Image] = []
    for i in range(n):
        canvas = Image.new("RGB", (canvas_w, canvas_h), (12, 12, 16))
        draw = ImageDraw.Draw(canvas)
        for index, (label, folder) in enumerate(panels):
            col = index % cols
            row = index // cols
            x0 = col * cell_w
            y0 = row * (header_h + cell_h)
            draw.rectangle([x0, y0, x0 + cell_w - 1, y0 + header_h - 1], fill=(28, 28, 36))
            draw.text((x0 + 8, y0 + 6), label, fill=(230, 230, 235), font=font)
            src = _find_frame(folder, i)
            if src is None:
                cell = Image.new("RGB", (cell_w, cell_h), (40, 20, 20))
                ImageDraw.Draw(cell).text((12, 12), f"missing f{i:02d}", fill=(255, 120, 120), font=font_sm)
            else:
                cell = _fit_cell(Image.open(src), (cell_w, cell_h))
            canvas.paste(cell, (x0, y0 + header_h))
            draw.text((x0 + 8, y0 + header_h + 6), f"f{i:02d}", fill=(180, 180, 190), font=font_sm)
        for _ in range(hold):
            frames_out.append(canvas.copy())

    if not frames_out:
        raise RuntimeError(
            f"no GIF frames composed (frame_count={n}); check panel dirs and numbered frames"
        )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    source_duration_ms = (
        int(args.duration_ms)
        if int(args.duration_ms) > 0
        else max(1, int(round(1000.0 / 12.0)))
    )
    duration_ms = max(1, int(round(source_duration_ms / hold)))
    frames_out[0].save(
        args.out,
        save_all=True,
        append_images=frames_out[1:],
        duration=duration_ms,
        loop=0,
    )
    meta = {
        "ok": True,
        "out": str(args.out).replace("\\", "/"),
        "panels": [label for label, _ in panels],
        "frameCount": n,
        "hold": hold,
        "sourceFrameDurationMs": source_duration_ms,
        "cols": cols,
        "rows": rows,
        "proof": "generated artifact validated — multi-method preview gif; not OE runtime proven",
    }
    meta_path = args.out.with_suffix(".json")
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(json.dumps(meta, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
