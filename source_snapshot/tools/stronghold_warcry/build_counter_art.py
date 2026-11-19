"""Bake the Stronghold Warcry chain-counter art (fighting-game combo counter with a fire outline).

Outputs (homm3_ui/stronghold_warcry/, loaded by Homm3StrongholdWarcryCounter.cs):
  digits_face.png   10 columns (digits 0-9) x HEAT_STAGES rows: the solid slanted digit, one row per heat stage.
  digits_flame.png  10 columns x FLAME_FRAMES rows: looping fire that licks around and above each digit, in the
                    full fire palette. The runtime tints and scales it per heat stage.
  label.png         1 column x HEAT_STAGES rows: the "WARCRY" caption.
  counter_art.json  cell sizes and counts, so the runtime and the mockup never hard-code them.

Everything is procedural (numpy + Pillow); the savage numerals are hand-defined strokes in this file, not a font,
and there is no generative art. The flame loops exactly:
its noise is tileable and scrolls a whole number of periods over FLAME_FRAMES.

Usage: python tools/stronghold_warcry/build_counter_art.py [--out DIR]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage

REPO = Path(__file__).resolve().parents[2]
DEFAULT_OUT = REPO / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod" / "homm3_ui" / "stronghold_warcry"

CELL_W = 160
CELL_H = 224
# The digit sits low in the cell so the flames have room above it.
DIGIT_HEIGHT = 124
DIGIT_BASELINE = 204
DIGIT_ADVANCE = 92  # runtime spacing between digit cells, in cell pixels
SHEAR = 0.17  # forward slant
FLAME_FRAMES = 24
FLAME_FPS = 18
FLAME_DOWNSCALE = 2
HEAT_STAGES = 5
SUPERSAMPLE = 3

LABEL_TEXT = "WARCRY"
LABEL_W = 320
LABEL_H = 72

# Digit face colours per heat stage: (top, bottom, rim, outline).
STAGE_FACE = [
    ((176, 34, 26), (92, 10, 10), (226, 86, 60), (24, 4, 4)),      # ember red
    ((224, 48, 28), (128, 14, 10), (255, 122, 70), (30, 5, 4)),    # blood red
    ((255, 108, 30), (176, 30, 10), (255, 178, 90), (40, 8, 4)),   # forge orange
    ((255, 196, 54), (226, 84, 14), (255, 236, 150), (52, 14, 4)), # bright flame
    ((255, 252, 224), (255, 190, 60), (255, 255, 255), (74, 24, 4)), # white-hot
]


# Savage numerals: every glyph is hand-defined here as hacked strokes (axe cuts / war paint), not a font.
# Coordinates are in a unit box, x right, y down; the box is GLYPH_ASPECT wide per unit of height.
# Each stroke is (points, start width, end width); widths are fractions of the glyph height.
# Strokes overshoot their corners (barbs) and end in blade points; edges are then chewed up with noise and nicked.
GLYPH_ASPECT = 0.64
T = 0.215  # base stroke weight
STROKES = {
    "0": [([(0.50, 0.00), (0.96, 0.22), (0.88, 0.84), (0.48, 1.00), (0.06, 0.78), (0.12, 0.16), (0.56, -0.02)], T, T * 0.8)],
    "1": [([(0.02, 0.36), (0.66, -0.02)], T * 0.7, T * 1.05), ([(0.62, 0.00), (0.52, 0.98)], T * 1.3, T * 0.95)],
    "2": [([(0.04, 0.30), (0.42, 0.02), (0.94, 0.20), (0.82, 0.50), (0.08, 0.96), (1.00, 0.88)], T * 0.7, T)],
    "3": [([(0.04, 0.10), (0.94, 0.04), (0.46, 0.46), (0.95, 0.68), (0.56, 1.00), (0.02, 0.84)], T * 0.8, T * 0.75)],
    "4": [([(0.66, -0.02), (0.04, 0.68), (1.02, 0.62)], T * 0.9, T * 0.7), ([(0.74, 0.18), (0.68, 1.00)], T * 1.15, T * 0.85)],
    "5": [([(0.98, 0.02), (0.20, 0.08), (0.12, 0.46), (0.74, 0.42), (0.95, 0.70), (0.54, 1.00), (0.00, 0.86)], T * 0.75, T * 0.8)],
    "6": [([(0.90, -0.02), (0.26, 0.28), (0.06, 0.72), (0.44, 1.00), (0.93, 0.76), (0.62, 0.47), (0.16, 0.64)], T * 0.6, T * 0.8)],
    "7": [([(0.00, 0.14), (1.00, 0.02), (0.34, 1.03)], T * 0.8, T * 0.6)],
    "8": [([(0.50, 0.00), (0.88, 0.20), (0.50, 0.47), (0.14, 0.22), (0.56, -0.01)], T * 0.85, T * 0.7),
          ([(0.50, 0.47), (0.97, 0.76), (0.50, 1.00), (0.03, 0.75), (0.56, 0.45)], T, T * 0.8)],
    "W": [([(0.00, 0.00), (0.24, 1.00), (0.50, 0.30), (0.76, 1.00), (1.00, -0.02)], T * 0.9, T * 0.8)],
    "A": [([(0.02, 1.02), (0.50, 0.00), (0.98, 1.02)], T * 0.8, T * 0.8), ([(0.20, 0.66), (0.86, 0.60)], T * 0.7, T * 0.5)],
    "R": [([(0.14, 1.02), (0.14, 0.02), (0.92, 0.22), (0.20, 0.52), (0.98, 1.02)], T * 0.9, T * 0.7)],
    "C": [([(0.96, 0.16), (0.50, 0.00), (0.06, 0.40), (0.30, 0.94), (0.98, 0.84)], T * 0.7, T * 0.8)],
    "Y": [([(0.00, 0.00), (0.50, 0.50), (1.00, -0.02)], T * 0.8, T * 0.8), ([(0.52, 0.44), (0.44, 1.03)], T * 0.95, T * 0.55)],
}
STROKES["9"] = [([(1.0 - x, 1.0 - y) for x, y in pts], w0, w1) for pts, w0, w1 in STROKES["6"]]
GLYPH_WIDTH = {"1": 0.52, "W": 0.86, "A": 0.70, "R": 0.62, "C": 0.60, "Y": 0.66}


def _stroke_polys(points, w0, w1):
    """Polygons for one hacked stroke: tapered segment slabs that overshoot each corner, blade-point ends."""
    pts = [np.array(q, dtype=np.float64) for q in points]
    lens = [float(np.linalg.norm(pts[i + 1] - pts[i])) for i in range(len(pts) - 1)]
    total = sum(lens) or 1.0
    polys, run = [], 0.0
    for i, seg in enumerate(lens):
        a, b = pts[i], pts[i + 1]
        d = (b - a) / max(seg, 1e-6)
        n = np.array([-d[1], d[0]])
        wa = w0 + (w1 - w0) * (run / total)
        run += seg
        wb = w0 + (w1 - w0) * (run / total)
        first, last = i == 0, i == len(lens) - 1
        # overshoot corners into barbs; free ends become long blade points
        a2 = a - d * (wa * (0.10 if first else 0.42))
        b2 = b + d * (wb * (0.10 if last else 0.42))
        poly = [a2 + n * wa / 2, b2 + n * wb / 2 * 0.78, b2 - n * wb / 2, a2 - n * wa / 2 * 0.86]
        if first:
            poly = [a2 - d * wa * 0.55 + n * wa * 0.30] + poly
        if last:
            poly = poly[:2] + [b2 + d * wb * 0.95 - n * wb * 0.34] + poly[2:]
        polys.append(poly)
    return polys


def glyph_width(ch: str) -> float:
    return GLYPH_WIDTH.get(ch, GLYPH_ASPECT)


def word_width(text: str, height: float) -> float:
    return sum(glyph_width(ch) * height for ch in text) + height * 0.13 * (len(text) - 1)


def _word_mask(text: str, height: float, s: int, size: tuple[int, int], origin: tuple[float, float], shear: float, seed: int) -> np.ndarray:
    """Supersampled mask of hacked glyphs; origin = (left x, baseline y) in output pixels."""
    rng = np.random.default_rng(seed)
    img = Image.new("L", (size[0] * s, size[1] * s), 0)
    d = ImageDraw.Draw(img)
    x = origin[0]
    for ch in text:
        gw = glyph_width(ch)
        for points, w0, w1 in STROKES[ch]:
            jit = [((px + rng.normal(0, 0.012)) * gw, py + rng.normal(0, 0.010)) for px, py in points]
            for poly in _stroke_polys(jit, w0, w1):
                out = []
                for q in poly:
                    yy = origin[1] - (1.0 - q[1]) * height
                    xx = x + q[0] * height + shear * (origin[1] - yy)
                    out.append((xx * s, yy * s))
                d.polygon(out, fill=255)
        x += gw * height + height * 0.13
    return np.asarray(img, dtype=np.float32) / 255.0


def _noise(shape: tuple[int, int], cell: float, rng: np.random.Generator, order: int) -> np.ndarray:
    cell = max(2.0, cell)
    grid = rng.random((int(shape[0] / cell) + 3, int(shape[1] / cell) + 3))
    return ndimage.zoom(grid, cell, order=order)[: shape[0], : shape[1]]


def glyph_mask(text: str, height: int, cell_w: int, cell_h: int, baseline: int, shear: float = SHEAR) -> np.ndarray:
    """Antialiased savage glyph coverage (0..1) centred in a cell, feet on the baseline."""
    s = SUPERSAMPLE + 1
    seed = sum(ord(c) * (i + 3) for i, c in enumerate(text)) * 7919
    left = (cell_w - word_width(text, height)) / 2 - shear * height / 2
    big = _word_mask(text, height, s, (cell_w, cell_h), (left, baseline), shear, seed)
    rng = np.random.default_rng(seed + 1)
    k = height * s / 124.0
    # chew the edges: coarse bites + fine grit, re-thresholded so the cut stays crisp
    soft = ndimage.gaussian_filter(big, 1.6 * k)
    rough = soft + (_noise(big.shape, 9 * k, rng, 3) - 0.5) * 0.34 + (_noise(big.shape, 3 * k, rng, 1) - 0.5) * 0.16
    cut = Image.fromarray(((rough > 0.5) * 255).astype(np.uint8), "L")
    # claw nicks: thin slashes cut clean through the strokes
    d = ImageDraw.Draw(cut)
    ys, xs = np.nonzero(rough > 0.5)
    if len(xs):
        for _ in range(max(2, len(text) * 2)):
            j = rng.integers(len(xs))
            cx, cy = float(xs[j]), float(ys[j])
            ang = np.deg2rad(rng.uniform(-62, -38))
            ln = rng.uniform(0.16, 0.30) * height * s
            dx, dy = np.cos(ang) * ln, np.sin(ang) * ln
            wn = rng.uniform(0.022, 0.034) * height * s
            d.polygon([(cx - dx, cy - dy), (cx + wn * 0.6, cy - wn), (cx + dx, cy + dy), (cx - wn * 0.6, cy + wn)], fill=0)
    return np.asarray(cut.resize((cell_w, cell_h), Image.LANCZOS), dtype=np.float32) / 255.0


def lerp(a, b, t):
    return a + (b - a) * t


def face_rgba(mask: np.ndarray, stage: int) -> np.ndarray:
    """Chiselled digit: vertical gradient, lit top-left bevel, hot rim, dark outline and a soft drop shadow."""
    top, bottom, rim, outline = [np.array(c, dtype=np.float32) for c in STAGE_FACE[stage]]
    h, w = mask.shape
    ys, _ = np.nonzero(mask > 0.5)
    y0, y1 = (ys.min(), ys.max()) if len(ys) else (0, h - 1)
    grad = np.clip((np.arange(h, dtype=np.float32) - y0) / max(1, y1 - y0), 0, 1)[:, None]
    # slight S-curve so the middle band reads as a forged highlight
    band = np.exp(-((grad - 0.42) ** 2) / 0.012) * 0.22
    rgb = lerp(top[None, None, :], bottom[None, None, :], grad[..., None] ** 1.15)
    rgb = rgb + band[..., None] * (rim[None, None, :] - rgb)

    inside = ndimage.distance_transform_edt(mask > 0.5).astype(np.float32)
    soft = ndimage.gaussian_filter(mask, 2.2)
    gy, gx = np.gradient(soft)
    light = np.clip((-gx * 0.55 - gy * 0.85) * 9.0, -1, 1)  # lit from the top-left
    bevel = np.clip(1.0 - inside / 5.5, 0, 1)
    rgb = rgb + (light * bevel)[..., None] * np.where(light[..., None] > 0, 255 - rgb, rgb) * 0.62
    rim_w = np.clip(1.0 - inside / 2.2, 0, 1) * 0.55
    rgb = rgb + rim_w[..., None] * (rim[None, None, :] - rgb)

    out_mask = np.clip(ndimage.gaussian_filter((ndimage.binary_dilation(mask > 0.35, iterations=4)).astype(np.float32), 1.0) * 1.25, 0, 1)
    shadow = np.roll(ndimage.gaussian_filter(out_mask, 4.0), (5, 3), axis=(0, 1)) * 0.6

    alpha = np.maximum(out_mask, shadow)
    color = np.zeros((h, w, 3), dtype=np.float32)
    color[:] = outline * 0.25  # shadow colour
    color = lerp(color, outline[None, None, :], out_mask[..., None])
    color = lerp(color, rgb, mask[..., None])
    rgba = np.dstack([np.clip(color, 0, 255), np.clip(alpha, 0, 1) * 255.0])
    return rgba.astype(np.uint8)


def tile_noise(shape: tuple[int, int], period: tuple[int, int], rng: np.random.Generator) -> np.ndarray:
    """Smooth value noise, tileable with the given (y, x) period, in 0..1."""
    py, px = period
    grid = rng.random((py, px)).astype(np.float32)
    h, w = shape
    y = np.arange(h, dtype=np.float32)[:, None] * (py / h) * (h / shape[0])
    x = np.arange(w, dtype=np.float32)[None, :] * (px / w)
    return _sample_periodic(grid, y * 1.0, x * 1.0)


def _sample_periodic(grid: np.ndarray, y: np.ndarray, x: np.ndarray) -> np.ndarray:
    py, px = grid.shape
    y0 = np.floor(y).astype(int)
    x0 = np.floor(x).astype(int)
    fy = y - y0
    fx = x - x0
    fy = fy * fy * (3 - 2 * fy)
    fx = fx * fx * (3 - 2 * fx)
    a = grid[y0 % py, x0 % px]
    b = grid[y0 % py, (x0 + 1) % px]
    c = grid[(y0 + 1) % py, x0 % px]
    d = grid[(y0 + 1) % py, (x0 + 1) % px]
    return (a * (1 - fx) + b * fx) * (1 - fy) + (c * (1 - fx) + d * fx) * fy


class LoopNoise:
    """Fractal noise that scrolls upward and loops over FLAME_FRAMES (each octave scrolls whole periods)."""

    def __init__(self, seed: int, octaves=((7, 5, 1), (13, 9, 2), (25, 17, 3), (49, 33, 5))):
        rng = np.random.default_rng(seed)
        # (grid rows, grid cols, loops per cycle)
        self.octaves = [(rng.random((gy, gx)).astype(np.float32), loops) for gy, gx, loops in octaves]

    def sample(self, h: int, w: int, t: float, y_stretch: float = 1.0, warp: np.ndarray | None = None) -> np.ndarray:
        yy = np.arange(h, dtype=np.float32)[:, None] / h
        xx = np.arange(w, dtype=np.float32)[None, :] / w
        if warp is not None:
            xx = xx + warp
        total = np.zeros((h, w), dtype=np.float32)
        amp, norm = 1.0, 0.0
        for grid, loops in self.octaves:
            gy, gx = grid.shape
            # flames rise: sample further down the field as time advances
            y = (yy * y_stretch + t * loops) * gy
            x = xx * gx + np.zeros_like(yy)
            total += amp * _sample_periodic(grid, y + np.zeros_like(xx), x)
            norm += amp
            amp *= 0.55
        return total / norm


def fire_palette(heat: np.ndarray) -> np.ndarray:
    """Heat 0..1 -> RGBA: transparent, deep red, orange, yellow, white core."""
    stops = np.array([0.0, 0.16, 0.36, 0.58, 0.80, 1.0], dtype=np.float32)
    cols = np.array(
        [
            (60, 0, 0, 0),
            (150, 12, 4, 150),
            (232, 52, 8, 232),
            (255, 138, 18, 250),
            (255, 222, 96, 255),
            (255, 255, 236, 255),
        ],
        dtype=np.float32,
    )
    heat = np.clip(heat, 0, 1)
    out = np.zeros(heat.shape + (4,), dtype=np.float32)
    for c in range(4):
        out[..., c] = np.interp(heat, stops, cols[:, c])
    return out.astype(np.uint8)


def flame_frames(mask: np.ndarray, seed: int) -> list[np.ndarray]:
    """Looping flame around one glyph: an outline of fire hugging the digit, with tongues rising off it."""
    h, w = mask.shape
    solid = mask > 0.5
    dist = ndimage.distance_transform_edt(~solid).astype(np.float32)
    # Envelope: tight glow all round the glyph (the fire outline)...
    hug = np.exp(-(dist / 7.5) ** 1.35)
    # ...plus an upward plume: smear the glyph upward with decay.
    plume = np.zeros_like(mask)
    acc = np.zeros(w, dtype=np.float32)
    spread = ndimage.gaussian_filter(mask, 3.0)
    for y in range(h - 1, -1, -1):
        acc = np.maximum(acc * 0.962, spread[y])
        acc = ndimage.gaussian_filter1d(acc, 0.8) * 1.006
        plume[y] = np.clip(acc, 0, 1)
    ys = np.nonzero(solid.any(axis=1))[0]
    top = ys.min() if len(ys) else 0
    rise = np.clip((top - np.arange(h, dtype=np.float32)) / max(1.0, top), 0, 1)[:, None]  # 0 at digit top, 1 at cell top
    plume = plume * (1.0 - rise ** 1.6)
    # keep flames inside the cell: fade at the left/right/top borders
    xs = np.arange(w, dtype=np.float32)[None, :]
    border = np.clip(np.minimum(xs, w - 1 - xs) / 30.0, 0, 1) ** 1.5 * np.clip(np.arange(h, dtype=np.float32)[:, None] / 34.0, 0, 1) ** 1.5

    noise = LoopNoise(seed)
    warp_noise = LoopNoise(seed + 101, octaves=((5, 4, 1), (9, 7, 2)))
    detail = LoopNoise(seed + 202, octaves=((19, 15, 2), (37, 29, 4)))
    frames = []
    for i in range(FLAME_FRAMES):
        t = i / FLAME_FRAMES
        warp = (warp_noise.sample(h, w, t, y_stretch=0.8) - 0.5) * 0.11 * (0.35 + rise * 1.4)
        n = noise.sample(h, w, t, y_stretch=0.62, warp=warp)
        n2 = detail.sample(h, w, t, y_stretch=0.7, warp=warp * 0.6)
        n = np.clip((n - 0.5) * 2.3 + 0.5, 0, 1)
        # Tongues: the plume survives only where the noise is strong, more so the higher it climbs.
        tongues = np.clip(plume * 1.5 - (1.0 - n) * (0.74 + rise * 1.25), 0, 1)
        outline = np.clip(hug * (0.62 + 0.75 * n2) - 0.18, 0, 1)
        heat = np.maximum(tongues ** 0.85, outline) * border
        heat = heat * (0.9 + 0.2 * n2)
        # the body of the digit is covered by the face sprite; keep some heat under its edge only
        heat = np.where(solid, np.minimum(heat, 0.55), heat)
        heat = ndimage.gaussian_filter(heat, 0.6)
        frames.append(fire_palette(heat))
    return frames


def label_rgba(stage: int) -> np.ndarray:
    mask = glyph_mask(LABEL_TEXT, 42, LABEL_W, LABEL_H, 58, shear=SHEAR)
    return face_rgba(mask, stage)


def build(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    face = Image.new("RGBA", (CELL_W * 10, CELL_H * HEAT_STAGES), (0, 0, 0, 0))
    flame = Image.new("RGBA", (CELL_W * 10, CELL_H * FLAME_FRAMES), (0, 0, 0, 0))
    for digit in range(10):
        mask = glyph_mask(str(digit), DIGIT_HEIGHT, CELL_W, CELL_H, DIGIT_BASELINE)
        for stage in range(HEAT_STAGES):
            face.paste(Image.fromarray(face_rgba(mask, stage), "RGBA"), (digit * CELL_W, stage * CELL_H))
        for i, frame in enumerate(flame_frames(mask, 9000 + digit * 17)):
            flame.paste(Image.fromarray(frame, "RGBA"), (digit * CELL_W, i * CELL_H))
        print(f"digit {digit} baked")
    face.save(out / "digits_face.png", optimize=True)
    # Fire is soft: the flame atlas ships at half resolution (a quarter of the texture memory) and is stretched back.
    flame = flame.resize((flame.width // FLAME_DOWNSCALE, flame.height // FLAME_DOWNSCALE), Image.LANCZOS)
    flame.save(out / "digits_flame.png", optimize=True)
    label = Image.new("RGBA", (LABEL_W, LABEL_H * HEAT_STAGES), (0, 0, 0, 0))
    for stage in range(HEAT_STAGES):
        label.paste(Image.fromarray(label_rgba(stage), "RGBA"), (0, stage * LABEL_H))
    label.save(out / "label.png", optimize=True)
    meta = {
        "cellWidth": CELL_W,
        "cellHeight": CELL_H,
        "digitAdvance": DIGIT_ADVANCE,
        "digitHeight": DIGIT_HEIGHT,
        "digitBaseline": DIGIT_BASELINE,
        "flameFrames": FLAME_FRAMES,
        "flameFps": FLAME_FPS,
        "flameDownscale": FLAME_DOWNSCALE,
        "heatStages": HEAT_STAGES,
        "labelWidth": LABEL_W,
        "labelHeight": LABEL_H,
    }
    (out / "counter_art.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    for name in ("digits_face.png", "digits_flame.png", "label.png"):
        print(name, (out / name).stat().st_size // 1024, "KB")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    build(parser.parse_args().out)
