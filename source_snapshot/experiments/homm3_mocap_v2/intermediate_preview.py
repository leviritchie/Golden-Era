"""Source | intermediate-skeleton GIFs. Capture failures stay visible."""
from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from paths import SOURCE_FRAME_MS


def _numbered_frames(frame_dir: Path) -> list[Path]:
    paths = sorted(path for path in frame_dir.glob("*.png") if path.stem.isdigit())
    if not paths:
        raise FileNotFoundError(f"no numbered PNG frames in {frame_dir}")
    return paths


def draw_skeleton_panel(
    joints: np.ndarray,
    parents: np.ndarray,
    *,
    size: int,
    color: tuple[int, int, int],
    plane: str,
) -> Image.Image:
    image = Image.new("RGB", (size, size), (245, 245, 245))
    draw = ImageDraw.Draw(image)
    values = np.asarray(joints, dtype=np.float64)
    if plane == "xy":
        coords = values[:, [0, 1]]
        label = "XY front"
    elif plane == "xz":
        coords = values[:, [0, 2]]
        label = "XZ alt"
    else:
        raise ValueError(f"unknown skeleton plane {plane!r}")
    span = np.maximum(coords.max(axis=0) - coords.min(axis=0), 1e-6)
    scale = 0.8 * size / float(span.max())
    center = coords.mean(axis=0)
    xy = (coords - center) * scale + size / 2.0
    xy[:, 1] = size - xy[:, 1]
    for index, parent in enumerate(parents):
        if int(parent) < 0:
            continue
        x0, y0 = xy[int(parent)]
        x1, y1 = xy[index]
        draw.line((x0, y0, x1, y1), fill=color, width=2)
    for x, y in xy:
        draw.ellipse((x - 2, y - 2, x + 2, y + 2), fill=color)
    draw.text((4, 4), label, fill=(40, 40, 50))
    return image


def write_capture_gif(
    *,
    frames_dir: Path,
    pred: np.ndarray,
    parents: np.ndarray,
    dest: Path,
    title: str,
    gt: np.ndarray | None = None,
) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    pngs = _numbered_frames(frames_dir)
    pred_pos = np.asarray(pred, dtype=np.float64)
    count = min(len(pngs), pred_pos.shape[0])
    gt_pos = None
    if gt is not None:
        gt_pos = np.asarray(gt, dtype=np.float64)
        count = min(count, gt_pos.shape[0])
    if count < 1:
        raise ValueError("no frames to preview")
    width = 800 if gt_pos is None else 1200
    images: list[Image.Image] = []
    for index in range(count):
        rgba = Image.open(pngs[index]).convert("RGBA")
        source = Image.new("RGB", rgba.size, (245, 245, 245))
        source.paste(rgba, (0, 0), rgba)
        source.thumbnail((200, 200))
        pred_xy = draw_skeleton_panel(pred_pos[index], parents, size=200, color=(40, 180, 90), plane="xy")
        pred_xz = draw_skeleton_panel(pred_pos[index], parents, size=200, color=(40, 180, 90), plane="xz")
        row = Image.new("RGB", (width, 232), (16, 16, 20))
        row.paste(source, (0, 16))
        row.paste(pred_xy, (200, 16))
        row.paste(pred_xz, (400, 16))
        draw = ImageDraw.Draw(row)
        draw.text((4, 2), f"{title} f{index:02d} source|predXY|predXZ", fill=(230, 230, 235))
        if gt_pos is not None:
            gt_xy = draw_skeleton_panel(gt_pos[index], parents, size=200, color=(40, 90, 200), plane="xy")
            gt_xz = draw_skeleton_panel(gt_pos[index], parents, size=200, color=(40, 90, 200), plane="xz")
            row.paste(gt_xy, (600, 16))
            row.paste(gt_xz, (800, 16))
            draw.text((600, 2), "gtXY|gtXZ", fill=(180, 180, 190))
        else:
            draw.text((4, 218), "intermediate capture; mesh retarget is gated", fill=(180, 180, 190))
        images.append(row)
    duration = max(1, int(round(SOURCE_FRAME_MS)))
    images[0].save(dest, save_all=True, append_images=images[1:], duration=duration, loop=0)
    return dest
