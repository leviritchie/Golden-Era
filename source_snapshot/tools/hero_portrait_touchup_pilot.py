#!/usr/bin/env python3
"""Local prepass/postpass helpers for the Fortress/Stronghold hero portrait pilot.

Does not call generative AI. Writes under artifacts/hero_portrait_touchup_pilot/.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
PILOT_ROOT = ROOT / "artifacts" / "hero_portrait_touchup_pilot"
ORIG_DIR = PILOT_ROOT / "original"
UPSCALED_DIR = PILOT_ROOT / "upscaled"
PREPASS_DIR = PILOT_ROOT / "prepass"
AI_DIR = PILOT_ROOT / "ai"
FINAL_DIR = PILOT_ROOT / "final"
STRIPS_DIR = PILOT_ROOT / "strips"
OUTPUT_SIDE = 1254

PILOT_SIDS_BATCH1 = [
    "homm3_fortress_hero_18",
    "homm3_fortress_hero_7",
    "homm3_fortress_hero_10",
    "homm3_fortress_hero_17",
    "homm3_stronghold_hero_1",
    "homm3_stronghold_hero_8",
    "homm3_stronghold_hero_12",
    "homm3_stronghold_hero_17",
]

# Remaining Fortress roster after batch1 (exclude already-piloted SIDs).
PILOT_SIDS_FORTRESS_REMAINING = [
    "homm3_fortress_hero_1",
    "homm3_fortress_hero_2",
    "homm3_fortress_hero_3",
    "homm3_fortress_hero_4",
    "homm3_fortress_hero_5",
    "homm3_fortress_hero_6",
    "homm3_fortress_hero_8",
    "homm3_fortress_hero_9",
    "homm3_fortress_hero_11",
    "homm3_fortress_hero_12",
    "homm3_fortress_hero_13",
    "homm3_fortress_hero_14",
    "homm3_fortress_hero_15",
    "homm3_fortress_hero_16",
]

# Mutable active SID list (set by CLI).
PILOT_SIDS: list[str] = list(PILOT_SIDS_BATCH1)

KEY_COLORS_PATH = PILOT_ROOT / "key_colors.json"

# Default chroma plate (campaign green). Fall through candidates if present in art.
DEFAULT_KEY_COLOR = (20, 243, 14)
KEY_COLOR_CANDIDATES: list[tuple[int, int, int]] = [
    (20, 243, 14),  # neon green
    (255, 0, 255),  # magenta
    (0, 255, 255),  # cyan
    (0, 64, 255),  # strong blue
    (255, 255, 0),  # yellow
    (255, 0, 128),  # hot pink
    (0, 255, 128),  # spring green
    (128, 0, 255),  # violet
    (255, 128, 0),  # orange (last resorts — likelier skin/metal clash)
]


def color_collision_fraction(
    img: Image.Image,
    color: tuple[int, int, int],
    threshold: float = 48.0,
) -> float:
    """Fraction of opaque-ish pixels within Euclidean RGB distance of color."""
    arr = np.asarray(img.convert("RGBA"), dtype=np.float32)
    rgb = arr[:, :, :3]
    a = arr[:, :, 3]
    # Prefer original opaque disk, but also count any solid paint.
    mask = a >= 8
    if mask.sum() < 64:
        mask = np.ones(a.shape, dtype=bool)
    dist = np.linalg.norm(rgb - np.array(color, dtype=np.float32), axis=2)
    return float(((dist <= threshold) & mask).mean())


def choose_key_color(
    img: Image.Image,
    *,
    default: tuple[int, int, int] = DEFAULT_KEY_COLOR,
    threshold: float = 48.0,
    max_collision: float = 0.002,
) -> tuple[int, int, int]:
    """Pick a plate color absent from the portrait.

    Default green unless it already appears in the image; then try other
    high-chroma candidates; finally search the RGB cube for a free color.
    """
    ordered = [default] + [c for c in KEY_COLOR_CANDIDATES if c != default]
    for color in ordered:
        if color_collision_fraction(img, color, threshold=threshold) <= max_collision:
            return color

    # Fail-closed search: coarsest free lattice point maximally far from image colors.
    arr = np.asarray(img.convert("RGBA"), dtype=np.float32)
    rgb = arr[:, :, :3].reshape(-1, 3)
    a = arr[:, :, 3].reshape(-1)
    sample = rgb[a >= 8]
    if sample.size == 0:
        return default
    # Subsample for speed.
    if sample.shape[0] > 8000:
        rng = np.random.default_rng(0)
        sample = sample[rng.choice(sample.shape[0], 8000, replace=False)]
    best = default
    best_min = -1.0
    for r in range(0, 256, 32):
        for g in range(0, 256, 32):
            for b in range(0, 256, 32):
                # Prefer saturated plates (bad key if grey).
                if max(r, g, b) < 180 or (max(r, g, b) - min(r, g, b)) < 80:
                    continue
                cand = np.array([r, g, b], dtype=np.float32)
                dmin = float(np.linalg.norm(sample - cand, axis=1).min())
                if dmin > best_min:
                    best_min = dmin
                    best = (r, g, b)
    if best_min < threshold:
        raise RuntimeError(
            f"no free chroma key color found (best min-dist {best_min:.1f} < {threshold})"
        )
    return best


def write_key_colors(sids: list[str]) -> dict:
    """Choose and persist per-SID key colors from original portraits."""
    ensure_source_copies(sids)
    payload: dict = {
        "schema": "hero_portrait_touchup_pilot.key_colors.v1",
        "default": list(DEFAULT_KEY_COLOR),
        "threshold": 48.0,
        "entries": {},
    }
    for sid in sids:
        orig = Image.open(ORIG_DIR / f"{sid}.png")
        # Also consult live upscale colors — collision in either blocks the plate.
        up = Image.open(UPSCALED_DIR / f"{sid}.png")
        color = choose_key_color(orig)
        # If upscale introduces the color, re-choose against a concat sample.
        if color_collision_fraction(up, color) > 0.002:
            # Build a small contact of both for collision test via choose on upscale
            # then verify against original.
            color = choose_key_color(up)
            if color_collision_fraction(orig, color) > 0.002:
                # Force search against both by pasting side by side.
                w = max(orig.width, up.width)
                both = Image.new("RGBA", (w * 2, max(orig.height, up.height)), (0, 0, 0, 0))
                both.paste(orig.convert("RGBA"), (0, 0))
                both.paste(up.convert("RGBA"), (w, 0))
                color = choose_key_color(both)
        payload["entries"][sid] = {
            "rgb": list(color),
            "hex": f"#{color[0]:02X}{color[1]:02X}{color[2]:02X}",
            "collisionOrig": round(color_collision_fraction(orig, color), 5),
            "collisionUpscaled": round(color_collision_fraction(up, color), 5),
        }
        print(f"key-color {sid}: {payload['entries'][sid]['hex']}")
    KEY_COLORS_PATH.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload


def load_key_color(sid: str) -> tuple[int, int, int]:
    if not KEY_COLORS_PATH.is_file():
        return DEFAULT_KEY_COLOR
    data = json.loads(KEY_COLORS_PATH.read_text(encoding="utf-8"))
    entry = (data.get("entries") or {}).get(sid)
    if not entry:
        return DEFAULT_KEY_COLOR
    rgb = entry.get("rgb") or list(DEFAULT_KEY_COLOR)
    return (int(rgb[0]), int(rgb[1]), int(rgb[2]))


def is_checker_or_near_white(r: np.ndarray, g: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Baked transparency checker / failed alpha white leftovers."""
    grayish = (np.abs(r.astype(np.int16) - g.astype(np.int16)) <= 10) & (
        np.abs(g.astype(np.int16) - b.astype(np.int16)) <= 10
    )
    near_white = (r >= 240) & (g >= 240) & (b >= 240)
    checker_light = grayish & (r >= 185) & (r <= 230)
    checker_mid = grayish & (r >= 135) & (r <= 175)
    # Alternating checker pairs: light next to mid in 8px neighborhood.
    shift = np.zeros_like(checker_light)
    shift[:, 8:] = checker_light[:, :-8]
    alt = (checker_light & (~shift) & checker_mid) | (checker_mid & shift)
    return near_white | alt | (checker_light & checker_mid)


def border_flood_junk(alpha_kill: np.ndarray) -> np.ndarray:
    """Keep only junk connected to the image border (fail-closed for interior)."""
    from collections import deque

    h, w = alpha_kill.shape
    visited = np.zeros((h, w), dtype=bool)
    q: deque[tuple[int, int]] = deque()
    for x in range(w):
        for y in (0, h - 1):
            if alpha_kill[y, x]:
                visited[y, x] = True
                q.append((x, y))
    for y in range(h):
        for x in (0, w - 1):
            if alpha_kill[y, x] and not visited[y, x]:
                visited[y, x] = True
                q.append((x, y))
    while q:
        x, y = q.popleft()
        for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
            if 0 <= nx < w and 0 <= ny < h and not visited[ny, nx] and alpha_kill[ny, nx]:
                visited[ny, nx] = True
                q.append((nx, ny))
    return visited


def guided_subject_boost(up: Image.Image, orig: Image.Image) -> np.ndarray:
    """Soft subject prior from original: opaque original pixels are kept."""
    o = orig.convert("RGBA").resize(up.size, Image.Resampling.NEAREST)
    oa = np.asarray(o)[:, :, 3].astype(np.float32) / 255.0
    # Dilate original silhouette slightly so upscale fringe of subject survives.
    hard = Image.fromarray((oa * 255).astype(np.uint8), "L")
    dilated = hard.filter(ImageFilter.MaxFilter(9))
    return np.asarray(dilated, dtype=np.float32) / 255.0


def prepass_portrait(up: Image.Image, orig: Image.Image) -> tuple[Image.Image, dict]:
    rgba = np.asarray(up.convert("RGBA"), dtype=np.uint8)
    h, w = rgba.shape[:2]
    r = rgba[:, :, 0]
    g = rgba[:, :, 1]
    b = rgba[:, :, 2]
    a = rgba[:, :, 3].astype(np.float32)

    junk = is_checker_or_near_white(r, g, b) & (a >= 8)
    # Only clear junk reachable from the border, or junk on already-soft alpha.
    border_junk = border_flood_junk(junk)
    soft_junk = junk & (a < 220)
    kill = border_junk | soft_junk

    subject = guided_subject_boost(up, orig)
    # Never kill strong subject interior from original silhouette.
    kill = kill & (subject < 0.35)

    a2 = a.copy()
    a2[kill] = 0.0

    # Soften hard leftover fringe: near-white on low subject prior.
    fringe = (
        (a2 >= 8)
        & (subject < 0.55)
        & (r.astype(np.int16) >= 230)
        & (g.astype(np.int16) >= 230)
        & (b.astype(np.int16) >= 230)
    )
    a2[fringe] = np.minimum(a2[fringe], 0.0)

    out = rgba.astype(np.float32)
    out[:, :, 3] = a2
    clear = out[:, :, 3] < 8
    out[clear, 0:3] = 0

    meta = {
        "inputSize": [w, h],
        "killPx": int(kill.sum()),
        "fringePx": int(fringe.sum()),
        "opaquePctAfter": round(float((out[:, :, 3] >= 250).mean() * 100), 2),
    }
    return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8), "RGBA"), meta


def key_near_black_void(img: Image.Image, orig: Image.Image | None = None) -> Image.Image:
    """Turn painted black voids into true alpha (not an opaque black disk).

    Border-floods near-black achromatic plate only. Does not globally delete dark
    paint (that destroyed Adrienne-style black hair). Does not restore from the
    original circular opaque plate (that reintroduced a black disk).
    """
    del orig
    rgba = np.asarray(img.convert("RGBA"), dtype=np.uint8)
    rgb = rgba[:, :, :3].astype(np.int16)
    lum = rgb.max(axis=2)
    chroma = rgb.max(axis=2) - rgb.min(axis=2)
    # Strict void: flat almost-black plate, not merely dark subject paint.
    voidish = (lum <= 22) & (chroma <= 8)
    bg = border_flood_junk(voidish)
    # Tiny soft expansion into slightly brighter plate only.
    weak = (lum <= 34) & (chroma <= 8)
    dil = np.asarray(
        Image.fromarray((bg.astype(np.uint8) * 255), "L").filter(ImageFilter.MaxFilter(3)),
        dtype=np.uint8,
    ) > 0
    # Protect chromatic or clearly lit paint from dilate bleed.
    protect = (chroma > 14) | (lum > 40)
    bg = bg | (dil & weak & (~protect))

    out = rgba.astype(np.float32)
    out[bg, 3] = 0.0
    out[bg, 0:3] = 0.0
    hard = Image.fromarray(np.where(bg, 0, 255).astype(np.uint8), "L")
    soft = hard.filter(ImageFilter.GaussianBlur(radius=0.9))
    out[:, :, 3] = np.minimum(out[:, :, 3], np.asarray(soft, dtype=np.float32))
    # Keep protected paint opaque if soft edge nibbled it.
    out[protect & (~bg), 3] = np.maximum(
        out[protect & (~bg), 3],
        rgba[protect & (~bg), 3].astype(np.float32),
    )
    clear = out[:, :, 3] < 8
    out[clear, 0:3] = 0
    return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8), "RGBA")


def grabcut_bust(img: Image.Image, orig: Image.Image) -> Image.Image:
    """Remove painted scene backgrounds using color+center priors (not opaque disk)."""
    import cv2

    rgba = np.asarray(img.convert("RGBA"), dtype=np.uint8)
    h, w = rgba.shape[:2]
    bgr = cv2.cvtColor(rgba[:, :, :3], cv2.COLOR_RGB2BGR)
    rgb = rgba[:, :, :3].astype(np.int16)
    lum = rgb.max(axis=2)
    chroma = rgb.max(axis=2) - rgb.min(axis=2)
    yy, xx = np.mgrid[0:h, 0:w]
    cy, cx = (h - 1) / 2.0, (w - 1) / 2.0
    rr = np.sqrt((yy - cy) ** 2 + (xx - cx) ** 2)
    rmax = min(cx, cy)
    # Prefer center mass as subject; outer ring as background.
    mask = np.full((h, w), cv2.GC_PR_BGD, dtype=np.uint8)
    mask[(rr < rmax * 0.55) & ((lum > 40) | (chroma > 15))] = cv2.GC_FGD
    mask[(rr < rmax * 0.72) & ((lum > 28) | (chroma > 12))] = cv2.GC_PR_FGD
    mask[rr > rmax * 0.88] = cv2.GC_BGD
    mask[(lum <= 28) & (chroma <= 12)] = cv2.GC_BGD
    mask[0, :] = cv2.GC_BGD
    mask[-1, :] = cv2.GC_BGD
    mask[:, 0] = cv2.GC_BGD
    mask[:, -1] = cv2.GC_BGD
    # Nudge with original alpha only as probable FG core (eroded so bg plate is excluded).
    prior = guided_subject_boost(img, orig)
    eroded = np.asarray(
        Image.fromarray((prior * 255).astype(np.uint8), "L").filter(ImageFilter.MinFilter(15)),
        dtype=np.float32,
    ) / 255.0
    mask[eroded >= 0.7] = cv2.GC_FGD
    bgd = np.zeros((1, 65), np.float64)
    fgd = np.zeros((1, 65), np.float64)
    cv2.grabCut(bgr, mask, None, bgd, fgd, 5, cv2.GC_INIT_WITH_MASK)
    keep = (mask == cv2.GC_FGD) | (mask == cv2.GC_PR_FGD)
    soft = Image.fromarray((keep.astype(np.uint8) * 255), "L").filter(ImageFilter.GaussianBlur(radius=1.25))
    out = rgba.astype(np.float32)
    out[:, :, 3] = np.minimum(out[:, :, 3], np.asarray(soft, dtype=np.float32))
    keyed = key_near_black_void(Image.fromarray(np.clip(out, 0, 255).astype(np.uint8), "RGBA"))
    return keyed

def needs_scene_bg_removal(img: Image.Image) -> bool:
    """True when outer band is still opaque with non-black paint (scene leftover)."""
    arr = np.asarray(img.convert("RGBA"))
    h, w = arr.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w]
    cy, cx = (h - 1) / 2, (w - 1) / 2
    rr = np.sqrt((yy - cy) ** 2 + (xx - cx) ** 2)
    rmax = min(cx, cy) * 0.98
    band = (rr > rmax * 0.78) & (rr < rmax * 0.96)
    if band.sum() < 100:
        return False
    opaque = arr[:, :, 3][band] >= 200
    if opaque.mean() < 0.25:
        return False
    rgb = arr[:, :, :3][band][opaque]
    if rgb.size == 0:
        return False
    # Non-black painted pixels in the outer ring.
    return bool((rgb.max(axis=1) > 40).mean() > 0.35)


def is_green_bg(r: np.ndarray, g: np.ndarray, b: np.ndarray) -> np.ndarray:
    return (g >= 120) & (g >= r + 30) & (g >= b + 30) & ((r + b) < 220)


def fill_enclosed_alpha_holes(img: Image.Image, max_hole_px: int = 2500) -> Image.Image:
    """Restore small transparent pockets fully enclosed by opaque paint.

    Fail-closed: only fills components below max_hole_px that do not touch the
    image border. RGB is inpainted from the mean of the opaque ring.
    """
    from collections import deque

    rgba = np.asarray(img.convert("RGBA"), dtype=np.uint8)
    h, w = rgba.shape[:2]
    opaque = rgba[:, :, 3] >= 128
    hole = ~opaque
    # Mark border-connected transparency so we never fill the exterior.
    border_air = border_flood_junk(hole)
    visited = border_air.copy()
    out = rgba.copy()
    ys, xs = np.where(hole & (~visited))
    for y0, x0 in zip(ys.tolist(), xs.tolist()):
        if visited[y0, x0]:
            continue
        q: deque[tuple[int, int]] = deque([(x0, y0)])
        visited[y0, x0] = True
        comp: list[tuple[int, int]] = []
        while q:
            x, y = q.popleft()
            comp.append((x, y))
            for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                if 0 <= nx < w and 0 <= ny < h and not visited[ny, nx] and hole[ny, nx]:
                    visited[ny, nx] = True
                    q.append((nx, ny))
        if len(comp) > max_hole_px:
            continue
        ring_rgb: list[np.ndarray] = []
        for x, y in comp:
            for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                if 0 <= nx < w and 0 <= ny < h and opaque[ny, nx]:
                    ring_rgb.append(out[ny, nx, :3].astype(np.float32))
        if not ring_rgb:
            continue
        fill = np.mean(np.stack(ring_rgb, axis=0), axis=0)
        for x, y in comp:
            out[y, x, 0:3] = fill
            out[y, x, 3] = 255
    return Image.fromarray(out, "RGBA")


def key_chroma_plate(img: Image.Image, plate_rgb: tuple[int, int, int]) -> Image.Image:
    """Chroma-key a solid plate color to alpha (generalized campaign green key).

    Only border-connected plate is removed as background. Near-exact plate
    pockets fully enclosed by subject are also cleared (true leftover plate in
    silhouette gaps), but olive/greenish subject paint is left alone.
    """
    from collections import deque

    rgba = np.asarray(img.convert("RGBA"), dtype=np.uint8)
    h, w = rgba.shape[:2]
    rgb = rgba[:, :, :3].astype(np.float32)
    r = rgb[:, :, 0]
    g = rgb[:, :, 1]
    b = rgb[:, :, 2]
    plate = np.array(plate_rgb, dtype=np.float32)
    dist = np.linalg.norm(rgb - plate, axis=2)

    pr, pg, pb = float(plate[0]), float(plate[1]), float(plate[2])
    plate_channels = sorted([(pr, "r"), (pg, "g"), (pb, "b")], reverse=True)
    dominant = plate_channels[0][1]
    # Stricter dominance so swampy subject greens survive.
    if dominant == "g":
        chroma_dom = (g >= 160) & (g >= r + 50) & (g >= b + 50) & ((r + b) < 180)
    elif dominant == "r":
        chroma_dom = (r >= 160) & (r >= g + 50) & (r >= b + 50) & ((g + b) < 180)
    else:
        chroma_dom = (b >= 160) & (b >= r + 50) & (b >= g + 50) & ((r + g) < 180)

    # Flood seed: near plate OR strong chroma-dom plate.
    plate_like = (dist < 48.0) | chroma_dom
    visited = np.zeros((h, w), dtype=bool)
    q: deque[tuple[int, int]] = deque()
    for x in range(w):
        for y in (0, h - 1):
            if plate_like[y, x]:
                visited[y, x] = True
                q.append((x, y))
    for y in range(h):
        for x in (0, w - 1):
            if plate_like[y, x] and not visited[y, x]:
                visited[y, x] = True
                q.append((x, y))
    while q:
        x, y = q.popleft()
        for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
            if 0 <= nx < w and 0 <= ny < h and not visited[ny, nx] and plate_like[ny, nx]:
                visited[ny, nx] = True
                q.append((nx, ny))

    bg = visited
    # Mild dilate into near-plate fringe only; protect clearly non-plate paint.
    weak = dist < 72.0
    dil = np.asarray(
        Image.fromarray((bg.astype(np.uint8) * 255), "L").filter(ImageFilter.MaxFilter(3)),
        dtype=np.uint8,
    ) > 0
    protect = (dist >= 42.0) & (~chroma_dom)
    bg = bg | (dil & weak & (~protect))

    # Enclosed near-exact plate pockets (silhouette gaps), not greenish fur.
    exact = dist < 28.0
    pocket_vis = bg.copy()
    ys, xs = np.where(exact & (~pocket_vis))
    for y0, x0 in zip(ys.tolist(), xs.tolist()):
        if pocket_vis[y0, x0]:
            continue
        qq: deque[tuple[int, int]] = deque([(x0, y0)])
        pocket_vis[y0, x0] = True
        comp: list[tuple[int, int]] = []
        touches_border = False
        while qq:
            x, y = qq.popleft()
            comp.append((x, y))
            if x == 0 or y == 0 or x == w - 1 or y == h - 1:
                touches_border = True
            for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                if 0 <= nx < w and 0 <= ny < h and not pocket_vis[ny, nx] and exact[ny, nx]:
                    pocket_vis[ny, nx] = True
                    qq.append((nx, ny))
        if touches_border:
            continue
        if 8 <= len(comp) <= 12000:
            for x, y in comp:
                bg[y, x] = True

    hard = Image.fromarray(np.where(bg, 0, 255).astype(np.uint8), "L")
    soft = hard.filter(ImageFilter.GaussianBlur(radius=0.75))
    flood_alpha = np.asarray(soft, dtype=np.float32) / 255.0

    # Despill plate chroma on fringe into neighboring subject channels.
    edge = np.asarray(hard.filter(ImageFilter.FIND_EDGES), dtype=np.float32) / 255.0
    edge_band = (
        np.asarray(
            Image.fromarray((edge * 255).astype(np.uint8), "L").filter(ImageFilter.MaxFilter(5)),
            dtype=np.float32,
        )
        / 255.0
    )
    out = rgba.astype(np.float32)
    for ci, plate_c in enumerate((pr, pg, pb)):
        other = [0, 1, 2]
        other.remove(ci)
        other_mean = (out[:, :, other[0]] + out[:, :, other[1]]) * 0.5
        excess = np.clip(out[:, :, ci] - other_mean, 0, None)
        if plate_c < max(pr, pg, pb) - 10:
            continue
        wgt = np.clip(excess / 55.0, 0, 1) * edge_band * (flood_alpha > 0.05)
        out[:, :, ci] = out[:, :, ci] * (1.0 - wgt) + other_mean * wgt

    out[:, :, 3] = np.where(bg, 0.0, flood_alpha * 255.0)
    # Break plate-colored soft fringe so a later pass cannot tunnel into subject.
    fringe = (out[:, :, 3] > 0) & (out[:, :, 3] < 250) & (dist < 55.0)
    for ci, plate_c in enumerate((pr, pg, pb)):
        other = [0, 1, 2]
        other.remove(ci)
        other_mean = (out[:, :, other[0]] + out[:, :, other[1]]) * 0.5
        if plate_c < max(pr, pg, pb) - 10:
            continue
        out[:, :, ci] = np.where(fringe, other_mean, out[:, :, ci])
    clear = out[:, :, 3] < 10
    out[clear, 0:3] = 0
    keyed = Image.fromarray(np.clip(out, 0, 255).astype(np.uint8), "RGBA")
    return fill_enclosed_alpha_holes(keyed)

def key_green_screen(img: Image.Image) -> Image.Image:
    """Back-compat wrapper for default green plate."""
    return key_chroma_plate(img, DEFAULT_KEY_COLOR)


def looks_plate_color(img: Image.Image, plate_rgb: tuple[int, int, int]) -> bool:
    """True when border samples mostly match the plate."""
    arr = np.asarray(img.convert("RGBA"))
    border = np.concatenate(
        [arr[0, :, :3], arr[-1, :, :3], arr[:, 0, :3], arr[:, -1, :3]],
        axis=0,
    ).astype(np.float32)
    dist = np.linalg.norm(border - np.array(plate_rgb, dtype=np.float32), axis=1)
    return bool((dist < 70.0).mean() >= 0.55)


def looks_near_black_void(img: Image.Image) -> bool:
    """True when opaque border samples are mostly near-black achromatic plate.

    Matches the void thresholds used by key_near_black_void (strict plate, not
    merely dark subject paint). Opaque fraction must be high so already-keyed
    transparent corners do not false-positive.
    """
    arr = np.asarray(img.convert("RGBA"))
    border = np.concatenate(
        [arr[0, :, :], arr[-1, :, :], arr[:, 0, :], arr[:, -1, :]],
        axis=0,
    )
    opaque = border[:, 3] >= 200
    if float(opaque.mean()) < 0.40:
        return False
    rgb = border[opaque, :3].astype(np.int16)
    lum = rgb.max(axis=1)
    chroma = rgb.max(axis=1) - rgb.min(axis=1)
    voidish = (lum <= 28) & (chroma <= 12)
    return bool(float(voidish.mean()) >= 0.55)


def looks_green_screened(img: Image.Image) -> bool:
    return looks_plate_color(img, DEFAULT_KEY_COLOR)


def bust_to_square(
    img: Image.Image,
    side: int = OUTPUT_SIDE,
    orig: Image.Image | None = None,
    plate_rgb: tuple[int, int, int] | None = None,
    circular_clip: bool = True,
) -> Image.Image:
    """Fit bust onto a transparent square.

    When circular_clip is True (default, hero portraits), soft-multiply a circular
    alpha mask so square corners stay transparent for circular UI holes.
    When False (unit portraits), keep freeform alpha with no circular corner clip.
    """
    rgba = img.convert("RGBA")
    plate = plate_rgb or DEFAULT_KEY_COLOR
    if looks_plate_color(rgba, plate):
        rgba = key_chroma_plate(rgba, plate)
    elif looks_green_screened(rgba):
        rgba = key_chroma_plate(rgba, DEFAULT_KEY_COLOR)
    elif looks_near_black_void(rgba):
        # Prefer border-flood black void over grabcut when AI used a black matte.
        rgba = key_near_black_void(rgba)
    elif orig is not None:
        rgba = grabcut_bust(rgba, orig)
        rgba = key_near_black_void(rgba)
    else:
        rgba = key_near_black_void(rgba)

    # Light residual-plate cleanup only — do NOT full re-key (that tunnels into
    # greenish subject paint via soft fringe corridors).
    arr_chk = np.asarray(rgba.convert("RGBA"))
    border = np.concatenate(
        [arr_chk[0, :, :3], arr_chk[-1, :, :3], arr_chk[:, 0, :3], arr_chk[:, -1, :3]],
        axis=0,
    ).astype(np.float32)
    residual = float(
        (np.linalg.norm(border - np.array(plate, dtype=np.float32), axis=1) < 40.0).mean()
    )
    if residual >= 0.08:
        rgba = key_chroma_plate(rgba, plate)

    canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    src = rgba
    arr = np.asarray(src)
    ys, xs = np.where(arr[:, :, 3] > 24)
    if len(xs) == 0:
        raise RuntimeError("bust empty after chroma key")
    pad = 6
    x0 = max(0, int(xs.min()) - pad)
    y0 = max(0, int(ys.min()) - pad)
    x1 = min(src.width, int(xs.max()) + pad + 1)
    y1 = min(src.height, int(ys.max()) + pad + 1)
    src = src.crop((x0, y0, x1, y1))
    # Cull empty margins: fit the opaque bust nearly to the square. Soft circular
    # corner clip (when enabled) still prevents an opaque medallion disk. (0.78
    # left large empty gutters and made faces sit high in circular UI holes.)
    target = int(side * 0.98)
    scale = target / max(src.size)
    nw = max(1, int(src.width * scale))
    nh = max(1, int(src.height * scale))
    src = src.resize((nw, nh), Image.Resampling.LANCZOS)
    canvas.alpha_composite(src, ((side - nw) // 2, (side - nh) // 2))

    arr = np.asarray(canvas).astype(np.float32)
    out_a = arr[:, :, 3].astype(np.uint8)

    if circular_clip:
        # Soft circular clip for square corners only — multiplies existing alpha.
        s = 4
        mask = Image.new("L", (side * s, side * s), 0)
        draw = ImageDraw.Draw(mask)
        draw.ellipse((s, s, side * s - s - 1, side * s - s - 1), fill=255)
        mask = mask.resize((side, side), Image.Resampling.LANCZOS)
        src_a = np.asarray(canvas.getchannel("A"), dtype=np.float32)
        circ = np.asarray(mask, dtype=np.float32) / 255.0
        out_a = (src_a * circ).astype(np.uint8)
        canvas.putalpha(Image.fromarray(out_a, "L"))
        arr = np.asarray(canvas).astype(np.float32)

    clear = arr[:, :, 3] < 8
    arr[clear, 0:3] = 0
    out_a = arr[:, :, 3].astype(np.uint8)

    # Fail-closed: most of the square must stay transparent (bust, not opaque disk).
    # When circular_clip is on, measure inside the circle; otherwise the full frame.
    h, w = out_a.shape
    if circular_clip:
        yy, xx = np.mgrid[0:h, 0:w]
        cy, cx = (h - 1) / 2.0, (w - 1) / 2.0
        rr = np.sqrt((yy - cy) ** 2 + (xx - cx) ** 2)
        rmax = min(cx, cy) * 0.98
        inside = rr <= rmax
    else:
        inside = np.ones((h, w), dtype=bool)
    trans_inside = float(((out_a < 8) & inside).mean())
    if trans_inside < 0.20:
        # Likely opaque medallion — punch remaining near-plate / near-black flat fill
        # connected to transparent regions.
        from collections import deque

        flat = (arr[:, :, 3] >= 200) & (
            (np.linalg.norm(arr[:, :, :3] - np.array(plate, dtype=np.float32), axis=2) < 80)
            | ((arr[:, :, :3].max(axis=2) <= 28) & ((arr[:, :, :3].max(axis=2) - arr[:, :, :3].min(axis=2)) <= 10))
        )
        # Seed from already-transparent neighbors.
        seed = (out_a < 8)
        dil = np.asarray(
            Image.fromarray((seed.astype(np.uint8) * 255), "L").filter(ImageFilter.MaxFilter(5)),
            dtype=np.uint8,
        ) > 0
        kill = flat & dil
        # Grow into flat fill.
        visited = kill.copy()
        # np.where returns (ys, xs); deque of (y,x)
        q = deque((int(y), int(x)) for y, x in zip(*np.where(kill)))
        while q:
            y, x = q.popleft()
            for ny, nx in ((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)):
                if 0 <= ny < h and 0 <= nx < w and not visited[ny, nx] and flat[ny, nx]:
                    visited[ny, nx] = True
                    q.append((ny, nx))
        arr[visited, 3] = 0
        arr[visited, 0:3] = 0
        out_a = arr[:, :, 3].astype(np.uint8)
        trans_inside = float(((out_a < 8) & inside).mean())
        if trans_inside < 0.15:
            raise RuntimeError(
                f"opaque medallion remains after plate key "
                f"(transparent-inside={'circle' if circular_clip else 'frame'}={trans_inside:.3f})"
            )

    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), "RGBA")


# Back-compat alias used by older call sites / docs.
circular_alpha = bust_to_square


def strip_row(images: list[Image.Image], labels: list[str], cell: int = 384) -> Image.Image:
    panels: list[Image.Image] = []
    for im, label in zip(images, labels):
        im = im.convert("RGBA")
        # Magenta/cyan checker — opaque black plates cannot hide against it.
        tile = 16
        bg = Image.new("RGBA", (cell, cell), (0, 0, 0, 255))
        for y in range(0, cell, tile):
            for x in range(0, cell, tile):
                if ((x // tile) + (y // tile)) % 2 == 0:
                    ImageDraw.Draw(bg).rectangle(
                        (x, y, x + tile - 1, y + tile - 1), fill=(255, 0, 255, 255)
                    )
                else:
                    ImageDraw.Draw(bg).rectangle(
                        (x, y, x + tile - 1, y + tile - 1), fill=(0, 255, 255, 255)
                    )
        fitted = im.copy()
        fitted.thumbnail((cell - 8, cell - 28), Image.Resampling.LANCZOS)
        composed = bg.copy()
        composed.alpha_composite(
            fitted, ((cell - fitted.width) // 2, 20 + (cell - 28 - fitted.height) // 2)
        )
        draw = ImageDraw.Draw(composed)
        draw.text((8, 4), label, fill=(255, 255, 0, 255))
        panels.append(composed)
    strip = Image.new("RGBA", (cell * len(panels), cell), (0, 0, 0, 255))
    for i, p in enumerate(panels):
        strip.paste(p, (i * cell, 0))
    return strip


def ensure_source_copies(sids: list[str]) -> None:
    """Copy original + live upscaled sources into the pilot folders."""
    live_orig = (
        ROOT
        / "Heroes of Might & Magic Olden Era Playtest"
        / "OfflineUnlockMod"
        / "homm3_hero_portraits"
    )
    live_up = (
        ROOT
        / "Heroes of Might & Magic Olden Era Playtest"
        / "OfflineUnlockMod"
        / "homm3_hero_portraits_upscaled"
    )
    ORIG_DIR.mkdir(parents=True, exist_ok=True)
    UPSCALED_DIR.mkdir(parents=True, exist_ok=True)
    for sid in sids:
        src_o = live_orig / f"{sid}.png"
        src_u = live_up / f"{sid}.png"
        if not src_o.is_file():
            raise FileNotFoundError(src_o)
        if not src_u.is_file():
            raise FileNotFoundError(src_u)
        (ORIG_DIR / f"{sid}.png").write_bytes(src_o.read_bytes())
        (UPSCALED_DIR / f"{sid}.png").write_bytes(src_u.read_bytes())


def simple_enlarge_from_original(orig: Image.Image, side: int = OUTPUT_SIDE) -> Image.Image:
    """Deterministic enlarge of the 64x64 (or native) original — no external AI upscale.

    This is the Voy-proven reference path: Lanczos scale to the portrait contract size
    while preserving the original circular alpha. Blocky/soft is expected; GenerateImage
    does the real hand-painted reconstruction from this + the tiny original.
    """
    rgba = orig.convert("RGBA")
    if rgba.size == (side, side):
        return rgba
    # Scale RGB with Lanczos; scale alpha with Lanczos too so the circular mask stays soft.
    return rgba.resize((side, side), Image.Resampling.LANCZOS)


def run_prepass(*, enlarge_from_original: bool = False) -> dict:
    PREPASS_DIR.mkdir(parents=True, exist_ok=True)
    STRIPS_DIR.mkdir(parents=True, exist_ok=True)
    ensure_source_copies(PILOT_SIDS)
    report: dict = {
        "schema": "hero_portrait_touchup_pilot.prepass.v1",
        "enlargeFromOriginal": enlarge_from_original,
        "entries": [],
    }

    for sid in PILOT_SIDS:
        orig = Image.open(ORIG_DIR / f"{sid}.png")
        if enlarge_from_original:
            # Replace the live upscaled copy with an honest simple enlarge for this run.
            simple = simple_enlarge_from_original(orig)
            simple.save(UPSCALED_DIR / f"{sid}.png")
            cleaned = simple
            meta = {
                "inputSize": list(orig.size),
                "outputSize": list(simple.size),
                "killPx": 0,
                "fringePx": 0,
                "opaquePctAfter": round(
                    float((np.asarray(simple)[:, :, 3] >= 250).mean() * 100), 2
                ),
                "note": "simple Lanczos enlarge of original; external AI upscale ignored",
                "method": "simple_enlarge_from_original",
            }
            up_for_strip = simple
            pre_label = "simple_enlarge"
        else:
            up = Image.open(UPSCALED_DIR / f"{sid}.png")
            up_for_strip = up
            if up.size == (64, 64):
                cleaned = orig.convert("RGBA")
                meta = {
                    "inputSize": list(up.size),
                    "killPx": 0,
                    "fringePx": 0,
                    "opaquePctAfter": None,
                    "note": "no real upscale; prepass copies original for AI upscale+deslop",
                    "method": "copy_original",
                }
            else:
                cleaned, meta = prepass_portrait(up, orig)
                meta["method"] = "fringe_prepass_on_external_upscale"
            pre_label = "prepass"

        cleaned.save(PREPASS_DIR / f"{sid}.png")
        strip = strip_row(
            [orig, up_for_strip, cleaned],
            ["original", pre_label if enlarge_from_original else "upscaled", pre_label],
        )
        strip.save(STRIPS_DIR / f"{sid}__prepass.png")
        entry = {"sid": sid, **meta, "prepass": f"prepass/{sid}.png"}
        report["entries"].append(entry)
        print(f"prepass {sid}: method={meta.get('method')} size={cleaned.size}")

    path = PILOT_ROOT / "prepass_report.json"
    path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def load_manifest_entries() -> dict:
    path = (
        ROOT
        / "Heroes of Might & Magic Olden Era Playtest"
        / "OfflineUnlockMod"
        / "homm3_hero_portraits"
        / "manifest.json"
    )
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    return data.get("entries") or {}


def town_from_sid(sid: str) -> str:
    parts = sid.split("_")
    if len(parts) >= 3 and parts[0] == "homm3":
        return parts[1]
    return "other"


def list_sids_for_town(town: str) -> list[str]:
    entries = load_manifest_entries()
    return sorted(s for s in entries if town_from_sid(s) == town)


def list_remaining_sids(*, towns: list[str] | None = None) -> list[str]:
    """SIDs that do not yet have a pilot final."""
    entries = load_manifest_entries()
    done = {p.stem for p in FINAL_DIR.glob("*.png")} if FINAL_DIR.is_dir() else set()
    out: list[str] = []
    for sid in sorted(entries):
        if sid in done:
            continue
        if towns is not None and town_from_sid(sid) not in towns:
            continue
        out.append(sid)
    return out


def prepare_generation_refs(sids: list[str]) -> dict:
    """Write original + Lanczos enlarge refs used by GenerateImage."""
    ensure_source_copies(sids)
    ref_root = PILOT_ROOT / "gen_refs"
    ref_root.mkdir(parents=True, exist_ok=True)
    report = {"schema": "hero_portrait_touchup_pilot.gen_refs.v1", "entries": []}
    for sid in sids:
        orig = Image.open(ORIG_DIR / f"{sid}.png").convert("RGBA")
        nearest = orig.resize((512, 512), Image.Resampling.NEAREST)
        lanczos = orig.resize((512, 512), Image.Resampling.LANCZOS)
        orig256 = orig.resize((256, 256), Image.Resampling.NEAREST)
        nearest.save(ref_root / f"{sid}__nearest.png")
        lanczos.save(ref_root / f"{sid}__lanczos.png")
        orig256.save(ref_root / f"{sid}__orig256.png")
        # Also refresh simple enlarge prepass for review strips.
        simple = simple_enlarge_from_original(orig)
        PREPASS_DIR.mkdir(parents=True, exist_ok=True)
        simple.save(PREPASS_DIR / f"{sid}.png")
        simple.save(UPSCALED_DIR / f"{sid}.png")
        report["entries"].append(
            {
                "sid": sid,
                "orig256": f"gen_refs/{sid}__orig256.png",
                "lanczos": f"gen_refs/{sid}__lanczos.png",
                "nearest": f"gen_refs/{sid}__nearest.png",
            }
        )
        print(f"gen-refs {sid}")
    path = PILOT_ROOT / "gen_refs_report.json"
    path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def prompt_contract(sid: str, name: str | None = None) -> str:
    """Default GenerateImage prompt for the Voy-proven chroma path."""
    entries = load_manifest_entries()
    entry = entries.get(sid) or {}
    hero = name or entry.get("name") or sid
    cls = entry.get("classType") or "hero"
    return (
        f"Square Heroes of Might and Magic III style hero portrait bust ONLY of {hero} "
        f"({cls}). Faithfully redraw the SAME character shown in the reference images "
        f"(identity, pose, costume, colors, silhouette must match the small original sprite). "
        f"Do not invent jewelry, armor pieces, face paint, animal pelts, or facial features "
        f"absent from the original. Hand-painted 1990s fantasy game art: soft brushwork, "
        f"restrained lighting, no oily specular skin sheen, no plastic gloss, no pore-level "
        f"microtexture. Bust cutout on a flat solid chroma green background exactly #14F30E — "
        f"remove any scene, landscape, sky, or painted backdrop. Character body must be fully "
        f"opaque with NO green paint on skin, hair, armor, or shadows; keep dark recesses as "
        f"dark paint, not green. Centered freeform bust suitable for a game UI portrait. "
        f"No frame, no border, no checkerboard, no text."
    )


def qa_metrics(sid: str) -> dict:
    final_path = FINAL_DIR / f"{sid}.png"
    ai_path = AI_DIR / f"{sid}.png"
    if not final_path.is_file():
        return {"sid": sid, "status": "missing_final"}
    final = Image.open(final_path).convert("RGBA")
    arr = np.asarray(final)
    a = arr[:, :, 3]
    rgb = arr[:, :, :3].astype(np.float32)
    g, r, b = rgb[:, :, 1], rgb[:, :, 0], rgb[:, :, 2]
    green = int(((g > 180) & (g > r + 40) & (g > b + 40) & (a > 20)).sum())
    hole = a < 80
    interior_holes = int((hole & (~border_flood_junk(hole))).sum())
    plate = load_key_color(sid)
    plate_on_ai = looks_plate_color(Image.open(ai_path), plate) if ai_path.is_file() else False
    return {
        "sid": sid,
        "status": "ok",
        "opaquePct": round(float((a >= 200).mean() * 100), 2),
        "interiorHoles": interior_holes,
        "greenResidual": green,
        "plateOnAi": plate_on_ai,
        "needsReview": interior_holes > 200 or green > 800 or not plate_on_ai,
    }


def run_qa(sids: list[str] | None = None) -> dict:
    sids = sids or list(PILOT_SIDS)
    report = {"schema": "hero_portrait_touchup_pilot.qa.v1", "entries": []}
    for sid in sids:
        entry = qa_metrics(sid)
        report["entries"].append(entry)
        flag = " REVIEW" if entry.get("needsReview") else ""
        print(
            f"qa {sid}: holes={entry.get('interiorHoles')} "
            f"green={entry.get('greenResidual')} plate={entry.get('plateOnAi')}{flag}"
        )
    path = PILOT_ROOT / "qa_report.json"
    path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def promote_finals(sids: list[str] | None = None, *, dry_run: bool = False) -> dict:
    """Copy pilot finals into live homm3_hero_portraits_upscaled/."""
    live_up = (
        ROOT
        / "Heroes of Might & Magic Olden Era Playtest"
        / "OfflineUnlockMod"
        / "homm3_hero_portraits_upscaled"
    )
    sids = sids or [p.stem for p in sorted(FINAL_DIR.glob("*.png"))]
    report = {
        "schema": "hero_portrait_touchup_pilot.promote.v1",
        "dryRun": dry_run,
        "liveDir": str(live_up),
        "entries": [],
    }
    for sid in sids:
        src = FINAL_DIR / f"{sid}.png"
        dst = live_up / f"{sid}.png"
        if not src.is_file():
            report["entries"].append({"sid": sid, "status": "missing_final"})
            continue
        if dry_run:
            report["entries"].append({"sid": sid, "status": "would_write", "dst": str(dst)})
            print(f"promote DRY {sid} -> {dst}")
            continue
        dst.write_bytes(src.read_bytes())
        report["entries"].append({"sid": sid, "status": "written", "dst": str(dst)})
        print(f"promote {sid} -> {dst}")
    path = PILOT_ROOT / "promote_report.json"
    path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def run_postpass(*, circular_clip: bool = True) -> dict:
    FINAL_DIR.mkdir(parents=True, exist_ok=True)
    STRIPS_DIR.mkdir(parents=True, exist_ok=True)
    report: dict = {
        "schema": "hero_portrait_touchup_pilot.postpass.v1",
        "circularClip": circular_clip,
        "entries": [],
    }

    for sid in PILOT_SIDS:
        ai_path = AI_DIR / f"{sid}.png"
        if not ai_path.is_file():
            report["entries"].append({"sid": sid, "status": "missing_ai"})
            print(f"postpass SKIP {sid}: missing AI output")
            continue
        orig = Image.open(ORIG_DIR / f"{sid}.png")
        if (UPSCALED_DIR / f"{sid}.png").is_file():
            up = Image.open(UPSCALED_DIR / f"{sid}.png")
        else:
            up = simple_enlarge_from_original(orig)
        if (PREPASS_DIR / f"{sid}.png").is_file():
            pre = Image.open(PREPASS_DIR / f"{sid}.png")
        else:
            pre = up
        ai = Image.open(ai_path).convert("RGBA")
        plate = load_key_color(sid)

        plate_hit = looks_plate_color(ai, plate)
        # Chroma-plate gens must not go through fringe prepass (it can nibble edges).
        if plate_hit:
            cleaned = ai
            meta = {
                "inputSize": list(ai.size),
                "killPx": 0,
                "fringePx": 0,
                "opaquePctAfter": round(float((np.asarray(ai)[:, :, 3] >= 250).mean() * 100), 2),
                "method": "chroma_plate_passthrough",
            }
        else:
            cleaned, meta = prepass_portrait(ai, orig)
            meta["method"] = "fringe_prepass_on_ai"
        final = bust_to_square(
            cleaned,
            OUTPUT_SIDE,
            orig=orig,
            plate_rgb=plate,
            circular_clip=circular_clip,
        )
        arr = np.asarray(final)
        a = arr[:, :, 3]
        rgb = arr[:, :, :3].astype(np.float32)
        h, w = a.shape
        if circular_clip:
            yy, xx = np.mgrid[0:h, 0:w]
            cy, cx = (h - 1) / 2.0, (w - 1) / 2.0
            rr = np.sqrt((yy - cy) ** 2 + (xx - cx) ** 2)
            rmax = min(cx, cy)
            inside = rr <= rmax * 0.98
        else:
            inside = np.ones((h, w), dtype=bool)
        trans_inside = float(((a < 8) & inside).mean() * 100)
        residual_plate = float(
            ((a >= 200) & (np.linalg.norm(rgb - np.array(plate, dtype=np.float32), axis=2) < 55)).mean()
            * 100
        )
        meta.update(
            {
                "keyColor": list(plate),
                "plateDetectedOnAi": plate_hit,
                "circularClip": circular_clip,
                "transparentInsideCirclePct": round(trans_inside, 2),
                "residualPlatePct": round(residual_plate, 3),
            }
        )
        if trans_inside < 20:
            print(f"WARNING {sid}: transparent-inside only {trans_inside:.1f}% (medallion?)")
        if residual_plate > 0.5:
            print(f"WARNING {sid}: residual plate still {residual_plate:.2f}%")
        final.save(FINAL_DIR / f"{sid}.png")

        prepass_meta_path = PILOT_ROOT / "prepass_report.json"
        enlarge = False
        if prepass_meta_path.is_file():
            enlarge = bool(
                json.loads(prepass_meta_path.read_text(encoding="utf-8")).get(
                    "enlargeFromOriginal"
                )
            )
        mid_label = "simple_enlarge" if enlarge else "upscaled"
        strip = strip_row(
            [orig, up, pre, ai, final],
            ["original", mid_label, mid_label, "ai", "final"],
        )
        strip.save(STRIPS_DIR / f"{sid}__review.png")
        entry = {
            "sid": sid,
            "status": "ok",
            "aiSize": list(ai.size),
            "finalSize": list(final.size),
            **meta,
            "final": f"final/{sid}.png",
            "strip": f"strips/{sid}__review.png",
        }
        report["entries"].append(entry)
        print(
            f"postpass {sid}: {ai.size} -> {final.size} "
            f"plate=#{plate[0]:02X}{plate[1]:02X}{plate[2]:02X} "
            f"circular_clip={circular_clip} transInside={trans_inside:.1f}%"
        )

    path = PILOT_ROOT / "postpass_report.json"
    path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> int:
    global PILOT_SIDS
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "mode",
        choices=(
            "prepass",
            "postpass",
            "key-colors",
            "gen-refs",
            "qa",
            "promote",
            "list-remaining",
            "write-prompts",
        ),
    )
    ap.add_argument(
        "--batch",
        choices=("batch1", "fortress_remaining", "all_listed", "remaining", "town"),
        default="batch1",
        help="Which SID list to process",
    )
    ap.add_argument(
        "--town",
        type=str,
        default="",
        help="Town name for --batch town (castle, rampart, ...)",
    )
    ap.add_argument(
        "--sids",
        type=str,
        default="",
        help="Comma-separated SID override (wins over --batch)",
    )
    ap.add_argument(
        "--enlarge-from-original",
        action="store_true",
        help="Prepass: ignore external AI upscales; Lanczos-enlarge the 64x64 original (Voy path)",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="Promote: print destinations without writing",
    )
    ap.add_argument(
        "--no-circular-clip",
        action="store_true",
        help="Postpass: freeform alpha without soft circular corner clip (unit portraits)",
    )
    args = ap.parse_args()
    if args.sids.strip():
        PILOT_SIDS = [s.strip() for s in args.sids.split(",") if s.strip()]
    elif args.batch == "fortress_remaining":
        PILOT_SIDS = list(PILOT_SIDS_FORTRESS_REMAINING)
    elif args.batch == "batch1":
        PILOT_SIDS = list(PILOT_SIDS_BATCH1)
    elif args.batch == "remaining":
        PILOT_SIDS = list_remaining_sids()
    elif args.batch == "town":
        if not args.town.strip():
            raise SystemExit("--batch town requires --town")
        PILOT_SIDS = list_sids_for_town(args.town.strip().lower())
    else:
        PILOT_SIDS = list(PILOT_SIDS_BATCH1) + list(PILOT_SIDS_FORTRESS_REMAINING)

    if args.mode == "list-remaining":
        rem = list_remaining_sids(towns=[args.town.strip().lower()] if args.town.strip() else None)
        by: dict[str, list[str]] = {}
        for sid in rem:
            by.setdefault(town_from_sid(sid), []).append(sid)
        for town, sids in sorted(by.items()):
            print(f"{town}: {len(sids)}")
            for sid in sids:
                print(f"  {sid}")
        print(f"TOTAL {len(rem)}")
        return 0
    if args.mode == "prepass":
        run_prepass(enlarge_from_original=args.enlarge_from_original)
    elif args.mode == "key-colors":
        write_key_colors(PILOT_SIDS)
    elif args.mode == "gen-refs":
        prepare_generation_refs(PILOT_SIDS)
        write_key_colors(PILOT_SIDS)
    elif args.mode == "qa":
        run_qa(PILOT_SIDS)
    elif args.mode == "promote":
        promote_finals(PILOT_SIDS, dry_run=args.dry_run)
    elif args.mode == "write-prompts":
        entries = load_manifest_entries()
        out = PILOT_ROOT / "generation_prompts.json"
        payload = {
            "schema": "hero_portrait_touchup_pilot.generation_prompts.v1",
            "entries": {
                sid: {
                    "name": (entries.get(sid) or {}).get("name"),
                    "prompt": prompt_contract(sid),
                    "refs": [
                        f"gen_refs/{sid}__orig256.png",
                        f"gen_refs/{sid}__lanczos.png",
                    ],
                }
                for sid in PILOT_SIDS
            },
        }
        PILOT_ROOT.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {out} ({len(PILOT_SIDS)} prompts)")
    else:
        run_postpass(circular_clip=not args.no_circular_clip)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
