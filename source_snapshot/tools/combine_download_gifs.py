#!/usr/bin/env python3
"""Combine the N most recent GIFs from Downloads with filename overlays."""

from __future__ import annotations

import argparse
import glob
import os
import subprocess
import sys
from pathlib import Path

import imageio_ffmpeg
import numpy as np
from PIL import Image, ImageDraw, ImageFont


def newest_gifs(folder: Path, count: int) -> list[Path]:
    skip_prefixes = ("combined_recent_",)
    paths = [
        Path(p)
        for p in glob.glob(str(folder / "*.gif"))
        if not Path(p).name.lower().startswith(skip_prefixes)
    ]
    paths.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return paths[:count]


def overlay_label(path: Path) -> str:
    """Display name for the top banner (no .gif extension)."""
    name = path.name
    if name.lower().endswith(".gif"):
        return name[:-4]
    return path.stem


def load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        r"C:\Windows\Fonts\arialbd.ttf",
        r"C:\Windows\Fonts\arial.ttf",
        r"C:\Windows\Fonts\segoeuib.ttf",
        r"C:\Windows\Fonts\segoeui.ttf",
    ]
    for path in candidates:
        if os.path.isfile(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def scale_to_width(img: Image.Image, width: int) -> Image.Image:
    if img.width == width:
        return img.convert("RGBA")
    h = max(1, round(img.height * width / img.width))
    return img.resize((width, h), Image.Resampling.LANCZOS).convert("RGBA")


def draw_filename_banner(frame: Image.Image, label: str, font: ImageFont.ImageFont) -> Image.Image:
    draw = ImageDraw.Draw(frame)
    margin = 16
    bbox = draw.textbbox((0, 0), label, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    x = (frame.width - tw) // 2
    y = margin
    pad_x, pad_y = 18, 10
    bar = [
        x - pad_x,
        y - pad_y,
        x + tw + pad_x,
        y + th + pad_y,
    ]
    draw.rounded_rectangle(bar, radius=10, fill=(0, 0, 0, 170))
    draw.text((x, y), label, font=font, fill=(255, 255, 255, 255))
    return frame


def iter_gif_frames(path: Path) -> tuple[list[Image.Image], list[int]]:
    frames: list[Image.Image] = []
    durations: list[int] = []
    with Image.open(path) as im:
        n = getattr(im, "n_frames", 1)
        for i in range(n):
            im.seek(i)
            duration = im.info.get("duration", 100)
            durations.append(int(duration) if duration else 100)
            frames.append(im.convert("RGBA").copy())
    return frames, durations


def write_gif(
    frames: list[Image.Image],
    durations: list[int],
    output: Path,
) -> None:
    first, rest = frames[0], frames[1:]
    first.save(
        output,
        save_all=True,
        append_images=rest,
        duration=durations,
        loop=0,
        disposal=2,
        optimize=False,
    )


def write_mp4(
    frames: list[Image.Image],
    durations: list[int],
    output: Path,
    *,
    fps: int = 30,
    crf: int = 23,
) -> int:
    """Encode H.264 MP4 (yuv420p + faststart) for web/streaming."""
    if not frames:
        raise ValueError("No frames to encode")

    width, height = frames[0].size
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    cmd = [
        ffmpeg,
        "-y",
        "-f",
        "rawvideo",
        "-vcodec",
        "rawvideo",
        "-s",
        f"{width}x{height}",
        "-pix_fmt",
        "rgb24",
        "-r",
        str(fps),
        "-i",
        "-",
        "-an",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-preset",
        "medium",
        "-crf",
        str(crf),
        "-movflags",
        "+faststart",
        str(output),
    ]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    assert proc.stdin is not None

    frame_time_ms = 1000.0 / fps
    written = 0
    try:
        for frame, dur in zip(frames, durations):
            rgb = np.asarray(frame.convert("RGB"), dtype=np.uint8)
            repeats = max(1, round(dur / frame_time_ms))
            payload = rgb.tobytes()
            for _ in range(repeats):
                proc.stdin.write(payload)
                written += 1
    finally:
        proc.stdin.close()

    stderr = proc.stderr.read().decode("utf-8", errors="replace") if proc.stderr else ""
    rc = proc.wait()
    if rc != 0:
        raise RuntimeError(f"ffmpeg failed ({rc}):\n{stderr[-4000:]}")
    return written


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--downloads", type=Path, default=Path.home() / "Downloads")
    parser.add_argument("--count", type=int, default=4)
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument(
        "--format",
        choices=("mp4", "gif"),
        default="mp4",
        help="Output container (default: mp4 for streaming)",
    )
    parser.add_argument("--fps", type=int, default=30, help="MP4 frame rate")
    parser.add_argument("--crf", type=int, default=23, help="MP4 H.264 quality (lower=better)")
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output path (default: Downloads/combined_recent_gifs.mp4 or .gif)",
    )
    args = parser.parse_args()

    gifs = newest_gifs(args.downloads, args.count)
    if len(gifs) < args.count:
        raise SystemExit(f"Found only {len(gifs)} GIF(s) in {args.downloads}")

    # Oldest-first among the selected set (natural playback order).
    gifs = list(reversed(gifs))

    scaled_sections: list[tuple[str, list[Image.Image], list[int]]] = []
    max_h = 0
    for path in gifs:
        raw_frames, durs = iter_gif_frames(path)
        scaled = [scale_to_width(f, args.width) for f in raw_frames]
        max_h = max(max_h, max(f.height for f in scaled))
        scaled_sections.append((overlay_label(path), scaled, durs))

    canvas_size = (args.width, max_h)
    font = load_font(max(22, args.width // 48))
    out_frames: list[Image.Image] = []
    out_durations: list[int] = []

    for label, frames, durs in scaled_sections:
        for frame, dur in zip(frames, durs):
            canvas = Image.new("RGBA", canvas_size, (0, 0, 0, 255))
            oy = (max_h - frame.height) // 2
            canvas.paste(frame, (0, oy), frame)
            canvas = draw_filename_banner(canvas, label, font)
            out_frames.append(canvas)
            out_durations.append(dur)

    ext = ".mp4" if args.format == "mp4" else ".gif"
    output = args.output or (args.downloads / f"combined_recent_gifs{ext}")
    output.parent.mkdir(parents=True, exist_ok=True)

    if args.format == "mp4":
        encoded_frames = write_mp4(
            out_frames,
            out_durations,
            output,
            fps=args.fps,
            crf=args.crf,
        )
        size_mb = output.stat().st_size / (1024 * 1024)
        print(
            f"Wrote {output} ({encoded_frames} video frames @ {args.fps} fps, "
            f"{canvas_size[0]}x{canvas_size[1]}, {size_mb:.1f} MB, H.264 yuv420p)"
        )
    else:
        write_gif(out_frames, out_durations, output)
        print(f"Wrote {output} ({len(out_frames)} frames, {canvas_size[0]}x{canvas_size[1]})")

    print("Sections (in order):")
    for label, frames, _ in scaled_sections:
        print(f"  - {label}: {len(frames)} frames")


if __name__ == "__main__":
    main()
