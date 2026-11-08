#!/usr/bin/env python3
"""Build a multi-method grid MP4 from pose-fit preview mesh frames."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from compose_method_compare_gif import _find_frame, _fit_cell, _load_font
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]

if str(ROOT / "tools/homm3_silhouette_pose_fit") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools/homm3_silhouette_pose_fit"))

from preview_timing import PREVIEW_GIF_FRAME_MS  # noqa: E402


def _write_mp4(frames: list[Image.Image], path: Path, *, fps: int) -> None:
    import cv2

    if not frames:
        raise RuntimeError("no frames to encode")
    width, height = frames[0].size
    writer = cv2.VideoWriter(
        str(path),
        cv2.VideoWriter_fourcc(*"mp4v"),
        int(fps),
        (int(width), int(height)),
    )
    if not writer.isOpened():
        raise RuntimeError(f"OpenCV could not open MP4 writer for {path}")
    try:
        for frame in frames:
            bgr = cv2.cvtColor(
                __import__("numpy").asarray(frame.convert("RGB")),
                cv2.COLOR_RGB2BGR,
            )
            writer.write(bgr)
    finally:
        writer.release()


def compose_grid_frames(
    *,
    panels: list[tuple[str, Path]],
    frame_count: int,
    cell_w: int,
    cell_h: int,
    cols: int,
    hold: int,
) -> list[Image.Image]:
    font = _load_font(15)
    font_sm = _load_font(13)
    header_h = 28
    cols = int(cols) if int(cols) > 0 else len(panels)
    if cols < 1:
        raise ValueError("cols must be positive")
    rows = (len(panels) + cols - 1) // cols
    canvas_w = cols * cell_w
    canvas_h = rows * (header_h + cell_h)
    hold = max(1, int(hold))
    frames_out: list[Image.Image] = []
    for i in range(int(frame_count)):
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
                ImageDraw.Draw(cell).text(
                    (12, 12), f"missing f{i:02d}", fill=(255, 120, 120), font=font_sm
                )
            else:
                with Image.open(src) as raw:
                    cell = _fit_cell(raw, (cell_w, cell_h))
            canvas.paste(cell, (x0, y0 + header_h))
            draw.text(
                (x0 + 8, y0 + header_h + 6),
                f"f{i:02d}",
                fill=(180, 180, 190),
                font=font_sm,
            )
        for _ in range(hold):
            frames_out.append(canvas.copy())
    if not frames_out:
        raise RuntimeError("no MP4 frames composed")
    return frames_out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--hold", type=int, default=0, help="0 = derive from GIF frame ms / fps")
    ap.add_argument("--fps", type=int, default=60)
    ap.add_argument(
        "--duration-ms",
        type=int,
        default=PREVIEW_GIF_FRAME_MS,
        help="Wall-clock ms per source frame (GIF timing)",
    )
    ap.add_argument("--cell-w", type=int, default=220)
    ap.add_argument("--cell-h", type=int, default=260)
    ap.add_argument(
        "--panel",
        action="append",
        nargs=2,
        metavar=("LABEL", "DIR"),
        required=True,
    )
    ap.add_argument("--frame-count", type=int, default=30)
    ap.add_argument("--cols", type=int, default=3)
    args = ap.parse_args()

    panels: list[tuple[str, Path]] = []
    for label, raw in args.panel:
        p = Path(raw)
        if not p.is_absolute():
            p = ROOT / p
        panels.append((str(label), p))

    fps = max(1, int(args.fps))
    source_ms = max(1, int(args.duration_ms))
    hold = int(args.hold)
    if hold <= 0:
        hold = max(1, round(source_ms * fps / 1000.0))

    raster_frames = compose_grid_frames(
        panels=panels,
        frame_count=int(args.frame_count),
        cell_w=int(args.cell_w),
        cell_h=int(args.cell_h),
        cols=int(args.cols),
        hold=hold,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    _write_mp4(raster_frames, args.out, fps=fps)
    meta = {
        "ok": True,
        "out": str(args.out).replace("\\", "/"),
        "panels": [label for label, _ in panels],
        "frameCount": int(args.frame_count),
        "hold": hold,
        "fps": fps,
        "sourceFrameDurationMs": source_ms,
        "cols": int(args.cols),
        "proof": "generated-artifact",
    }
    meta_path = args.out.with_suffix(".json")
    meta_path.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(meta, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
