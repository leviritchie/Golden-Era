"""Orthographic PPM previews for part-map authorship and bind-proof stills."""

from __future__ import annotations

from pathlib import Path

import numpy as np


def write_ppm(path: Path, image: np.ndarray) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    h, w, _ = image.shape
    header = f"P6\n{w} {h}\n255\n".encode("ascii")
    path.write_bytes(header + np.ascontiguousarray(image, dtype=np.uint8).tobytes())


def _project(points: np.ndarray, axis: str) -> np.ndarray:
    if axis == "front":
        return points[:, [0, 2]]
    if axis == "side":
        return points[:, [1, 2]]
    if axis == "top":
        return points[:, [0, 1]]
    raise ValueError(axis)


def render_ortho_ppm(
    path: Path,
    positions: np.ndarray,
    *,
    axis: str,
    color: tuple[int, int, int] = (210, 200, 180),
    size: int = 320,
    background: tuple[int, int, int] = (16, 16, 20),
) -> None:
    xy = _project(np.asarray(positions, dtype=np.float64), axis)
    lo = xy.min(axis=0)
    hi = xy.max(axis=0)
    span = np.maximum(hi - lo, 1e-6)
    uv = (xy - lo) / span
    px = np.clip((uv[:, 0] * (size - 3) + 1).astype(int), 0, size - 1)
    py = np.clip(((1.0 - uv[:, 1]) * (size - 3) + 1).astype(int), 0, size - 1)
    img = np.zeros((size, size, 3), dtype=np.uint8)
    img[:] = background
    img[py, px] = color
    write_ppm(path, img)


def render_turntable_ppms(positions: np.ndarray, out_dir: Path) -> list[str]:
    out_dir = Path(out_dir)
    written = []
    for axis in ("front", "side", "top"):
        dest = out_dir / f"{axis}.ppm"
        render_ortho_ppm(dest, positions, axis=axis)
        written.append(str(dest).replace("\\", "/"))
    return written
