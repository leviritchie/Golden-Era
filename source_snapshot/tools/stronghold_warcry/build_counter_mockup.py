"""Animated mockup of the Stronghold Warcry chain counter, composed from the shipped art.

Mirrors Homm3StrongholdWarcryCounterLayout (Homm3StrongholdWarcryCounter.cs): same anchor, scales, heat stages,
flame sizes, pop, shake and break. Change both together. The backdrop is a plain dark field, not a game capture.

Usage: python tools/stronghold_warcry/build_counter_mockup.py --out V:/olden_port_work/warcry_build/warcry_counter_mockup.gif
"""

from __future__ import annotations

import argparse
import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

REPO = Path(__file__).resolve().parents[2]
ART = REPO / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod" / "homm3_ui" / "stronghold_warcry"

# --- Homm3StrongholdWarcryCounterLayout
CELL_W, CELL_H, BASELINE, ADVANCE = 160, 224, 204, 92
FLAME_FRAMES, FLAME_DOWN = 24, 2
LABEL_W, LABEL_H = 320, 72
ANCHOR_RIGHT_X, BASELINE_Y = 1836.0, 356.0
DIGIT_SCALE, LABEL_SCALE, LABEL_GAP = 0.86, 0.62, 12.0
SUB_SIZE = 21
STAGE_FROM = [1, 3, 6, 10, 15]
FLAME_ALPHA = [0.50, 0.72, 0.88, 1.00, 1.00]
FLAME_SIZE = [0.90, 1.00, 1.10, 1.22, 1.36]
FLAME_FPS = [13, 16, 19, 23, 27]
SHAKE = [0.0, 0.0, 0.6, 1.4, 2.4]
POP_SECONDS, POP_SCALE, POP_PER_STAGE = 0.26, 1.55, 0.08
BREAK_SECONDS, BREAK_DROP, BREAK_TILT = 0.55, 46.0, -9.0

# --- mockup timeline: (time, chain value, units warcrying); the chain breaks at BREAK_AT
HITS = [(0.6, 1, 1), (1.5, 3, 2), (2.4, 6, 3), (3.3, 10, 4), (4.2, 15, 5), (5.1, 21, 6), (6.0, 27, 6), (6.9, 33, 6), (7.8, 39, 6), (8.7, 45, 6), (9.6, 56, 6)]
BREAK_AT = 11.2
END = 12.4
FPS = 20
VIEW = (1300, 60, 1920, 500)  # region of the 1920x1080 canvas shown


def stage_for(value: int) -> int:
    stage = 0
    for i, start in enumerate(STAGE_FROM):
        if value >= start:
            stage = i
    return stage


def cell(atlas: Image.Image, col: int, row: int, w: int, h: int) -> Image.Image:
    return atlas.crop((col * w, row * h, (col + 1) * w, (row + 1) * h))


def with_alpha(img: Image.Image, alpha: float, grey: bool = False) -> Image.Image:
    arr = np.asarray(img, dtype=np.float32).copy()
    if grey:
        lum = arr[..., :3].mean(axis=2, keepdims=True)
        arr[..., :3] = lum * np.array([0.42, 0.36, 0.34]) / 0.5
    arr[..., 3] *= alpha
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), "RGBA")


def build(out: Path) -> None:
    face = Image.open(ART / "digits_face.png").convert("RGBA")
    flame = Image.open(ART / "digits_flame.png").convert("RGBA")
    label = Image.open(ART / "label.png").convert("RGBA")
    try:
        font = ImageFont.truetype("C:/Windows/Fonts/georgiai.ttf", SUB_SIZE)
    except OSError:
        font = ImageFont.load_default()
    vw, vh = VIEW[2] - VIEW[0], VIEW[3] - VIEW[1]
    # plain battlefield-toned backdrop with a vignette
    yy, xx = np.mgrid[0:vh, 0:vw].astype(np.float32)
    base = np.stack([52 + 20 * yy / vh, 62 + 26 * yy / vh, 44 + 10 * yy / vh], axis=2)
    vig = 1.0 - 0.35 * (((xx - vw * 0.55) / vw) ** 2 + ((yy - vh * 0.5) / vh) ** 2)
    backdrop = Image.fromarray(np.clip(base * vig[..., None], 0, 255).astype(np.uint8), "RGB").convert("RGBA")

    rng = np.random.default_rng(5)
    shake_seq = rng.normal(0, 0.5, size=(int(END * FPS) + 2, 2))
    frames = []
    flame_clock = 0.0
    G = 760  # group layer size; origin (right end of the baseline) sits at (GX, GY)
    GX, GY = 600, 420
    for f in range(int(END * FPS)):
        t = f / FPS
        value, crew, pop_at = 0, 0, -10.0
        for at, v, c in HITS:
            if t >= at:
                value, crew, pop_at = v, c, at
        breaking = BREAK_AT <= t < BREAK_AT + BREAK_SECONDS
        if t >= BREAK_AT + BREAK_SECONDS or value == 0:
            frames.append(backdrop.convert("RGB"))
            continue
        stage = stage_for(value)
        flame_clock += FLAME_FPS[stage] / FPS
        frame_index = int(flame_clock) % FLAME_FRAMES
        layer = Image.new("RGBA", (G, G), (0, 0, 0, 0))
        text = str(value)
        adv = ADVANCE * DIGIT_SCALE
        cw, ch = CELL_W * DIGIT_SCALE, CELL_H * DIGIT_SCALE
        places = []
        for i, chd in enumerate(text):
            slot = len(text) - 1 - i
            places.append((int(chd), GX - (slot + 0.5) * adv, i + (3 - len(text))))
        if not breaking:
            for d, cx, i in places:
                fl = cell(flame, d, (frame_index + i * 7) % FLAME_FRAMES, CELL_W // FLAME_DOWN, CELL_H // FLAME_DOWN)
                size = FLAME_SIZE[stage]
                fw, fh = int(cw * size), int(ch * size)
                fl = with_alpha(fl.resize((fw, fh), Image.BICUBIC), FLAME_ALPHA[stage])
                # the cell hangs on the baseline: its foot (BASELINE of CELL_H) sits on GY
                layer.alpha_composite(fl, (int(cx - fw / 2), int(GY - fh * BASELINE / CELL_H)))
        for d, cx, _ in places:
            fc = cell(face, d, stage, CELL_W, CELL_H).resize((int(cw), int(ch)), Image.LANCZOS)
            if breaking:
                fc = with_alpha(fc, 1.0, grey=True)
            layer.alpha_composite(fc, (int(cx - cw / 2), int(GY - ch * BASELINE / CELL_H)))
        lab = cell(label, 0, stage, LABEL_W, LABEL_H).resize((int(LABEL_W * LABEL_SCALE), int(LABEL_H * LABEL_SCALE)), Image.LANCZOS)
        if breaking:
            lab = with_alpha(lab, 1.0, grey=True)
        layer.alpha_composite(lab, (int(GX + 18 - lab.width), int(GY + LABEL_GAP)))
        d = ImageDraw.Draw(layer)
        sub = f"{crew} warcrying"
        tw = d.textlength(sub, font=font)
        d.text((GX - 4 - tw, GY + LABEL_GAP + lab.height), sub, font=font, fill=(255, 220, 158, 245), stroke_width=2, stroke_fill=(20, 4, 2, 255))

        scale, dx, dy, tilt, alpha = 1.0, 0.0, 0.0, 0.0, 1.0
        if breaking:
            u = (t - BREAK_AT) / BREAK_SECONDS
            dy = BREAK_DROP * u * u
            tilt = BREAK_TILT * u
            alpha = 1 - u * u
        else:
            u = (t - pop_at) / POP_SECONDS
            if u < 1:
                peak = POP_SCALE + POP_PER_STAGE * stage
                ease = 1 - (1 - u) ** 3
                scale = peak + (1 - peak) * ease - (0.06 * math.sin(u * math.pi) if u > 0.5 else 0)
            dx, dy = shake_seq[f] * 2 * SHAKE[stage]
        if scale != 1.0 or tilt:
            # scale/rotate about the group origin
            a = math.radians(-tilt)
            cos, sin = math.cos(a) / scale, math.sin(a) / scale
            layer = layer.transform((G, G), Image.AFFINE, (cos, sin, GX - cos * GX - sin * GY, -sin, cos, GY + sin * GX - cos * GY), resample=Image.BICUBIC)
        if alpha < 1:
            layer = with_alpha(layer, alpha)
        frame = backdrop.copy()
        frame.alpha_composite(layer, (int(ANCHOR_RIGHT_X - VIEW[0] - GX + dx), int(BASELINE_Y - VIEW[1] - GY + dy)), (0, 0))
        frames.append(frame.convert("RGB"))
    out.parent.mkdir(parents=True, exist_ok=True)
    pal = [fr.quantize(colors=255, method=Image.MEDIANCUT, dither=Image.FLOYDSTEINBERG) for fr in frames]
    pal[0].save(out, save_all=True, append_images=pal[1:], duration=int(1000 / FPS), loop=0, optimize=False)
    # a still at the hottest stage, for a quick look
    frames[int(10.4 * FPS)].save(out.with_suffix(".png"))
    print(out, out.stat().st_size // 1024, "KB", len(frames), "frames")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    build(parser.parse_args().out)
