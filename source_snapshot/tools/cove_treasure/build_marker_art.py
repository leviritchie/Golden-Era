"""Builds the Cove Treasure Hunting marker art from vanilla Olden Era sprites, so the markers match the game's
painted, lit look instead of flat vector shapes.

Sources (read from the installed game with UnityPy, never committed):
  magic_scroll_artifact  - the vanilla curled scroll (512 px). Its ink glyph is painted out and a treasure-map
                           drawing (dashed route, coast, red X) is inked on in the same hand.
  Quest_mark_01_vfx / Quest_mark_02_vfx - the vanilla "?" and "!" quest marks (alpha masks), tinted with the
                           vanilla quest gold (quest_mark_color).

Outputs (PNG, RGBA) into the given folder:
  map_piece.png        scroll with the treasure-map drawing
  mark_question.png    gold "?" with soft glow
  mark_exclaim.png     gold "!" with soft glow
  ground_x.png         a red X painted on the ground (perspective-flattened brush strokes)
  hole.png             a dug hole with a dirt rim

Usage: python tools/cove_treasure/build_marker_art.py <game HeroesOldenEra_Data dir> <out dir>
"""
import math
import os
import random
import sys

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter

QUEST_GOLD = (255, 201, 64)
INK = (64, 40, 26)
RED = (176, 34, 26)


def load_textures(data_dir, names):
    import UnityPy

    env = UnityPy.load(os.path.join(data_dir, "resources.assets"))
    found = {}
    for obj in env.objects:
        if obj.type.name != "Texture2D":
            continue
        try:
            name = obj.peek_name()
        except Exception:
            continue
        if name in names and name not in found:
            found[name] = obj.read().image.convert("RGBA")
    missing = [n for n in names if n not in found]
    if missing:
        raise SystemExit("missing vanilla textures: " + ", ".join(missing))
    return found


def paint_out_ink(scroll):
    """Removes the dark ink glyph and lines from the face of the scroll by filling them from nearby parchment."""
    arr = np.asarray(scroll).astype(np.float32)
    rgb, alpha = arr[..., :3], arr[..., 3]
    lum = rgb.mean(axis=2)
    face = Image.new("L", scroll.size, 0)
    ImageDraw.Draw(face).polygon([(178, 205), (372, 160), (378, 292), (176, 322)], fill=255)
    face = np.asarray(face) > 0
    blurred_lum = np.asarray(Image.fromarray(lum.astype(np.uint8)).filter(ImageFilter.GaussianBlur(14))).astype(np.float32)
    ink = face & (lum < blurred_lum - 22) & (alpha > 200)
    ink = np.asarray(Image.fromarray((ink * 255).astype(np.uint8)).filter(ImageFilter.MaxFilter(7))) > 0
    keep = (~ink) & (alpha > 200)
    # normalised blur of the non-ink pixels
    weight = np.asarray(Image.fromarray((keep * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(9))).astype(np.float32) / 255.0
    out = rgb.copy()
    for c in range(3):
        channel = np.asarray(Image.fromarray((rgb[..., c] * keep).astype(np.uint8)).filter(ImageFilter.GaussianBlur(9))).astype(np.float32)
        fill = channel / np.maximum(weight, 1e-3)
        out[..., c] = np.where(ink, fill, rgb[..., c])
    result = np.dstack([np.clip(out, 0, 255), alpha]).astype(np.uint8)
    return Image.fromarray(result, "RGBA")


def rough_line(d, pts, fill, width, rnd, jitter=1.2):
    for i in range(len(pts) - 1):
        (x0, y0), (x1, y1) = pts[i], pts[i + 1]
        d.line((x0 + rnd.uniform(-jitter, jitter), y0 + rnd.uniform(-jitter, jitter), x1 + rnd.uniform(-jitter, jitter), y1 + rnd.uniform(-jitter, jitter)), fill=fill, width=width)


def map_drawing(size):
    """The treasure-map drawing, upright; composited onto the scroll after rotation."""
    rnd = random.Random(17)
    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    cx, cy = size[0] // 2, size[1] // 2
    ink = INK + (215,)
    # coastline
    coast = [(cx - 88, cy - 34), (cx - 70, cy - 46), (cx - 48, cy - 40), (cx - 30, cy - 52), (cx - 6, cy - 48), (cx + 10, cy - 58)]
    rough_line(d, coast, ink, 4, rnd)
    # hills
    for hx, hy in ((cx - 62, cy + 6), (cx - 40, cy - 6)):
        d.arc((hx - 13, hy - 12, hx + 13, hy + 14), 190, 350, fill=ink, width=4)
    # dashed route
    route = []
    for i in range(0, 15):
        t = i / 14.0
        route.append((cx - 80 + 132 * t, cy + 38 - 50 * t + math.sin(t * 6.0) * 13))
    for i in range(0, len(route) - 1, 2):
        rough_line(d, [route[i], route[i + 1]], ink, 4, rnd, 0.6)
    # the X
    ex, ey, k = cx + 66, cy - 22, 17
    red = RED + (240,)
    rough_line(d, [(ex - k, ey - k), (ex + k, ey + k)], red, 9, rnd, 0.8)
    rough_line(d, [(ex - k, ey + k), (ex + k, ey - k)], red, 9, rnd, 0.8)
    # compass tick
    d.line((cx + 70, cy + 34, cx + 70, cy + 54), fill=ink, width=3)
    d.line((cx + 61, cy + 44, cx + 79, cy + 44), fill=ink, width=3)
    return layer.filter(ImageFilter.GaussianBlur(0.7))


def build_map_piece(scroll):
    clean = paint_out_ink(scroll)
    drawing = map_drawing((260, 170)).rotate(12.5, resample=Image.BICUBIC, expand=True)
    layer = Image.new("RGBA", clean.size, (0, 0, 0, 0))
    layer.alpha_composite(drawing, (276 - drawing.size[0] // 2, 243 - drawing.size[1] // 2))
    # keep the ink on the parchment face only, and let the parchment shading show through (multiply)
    face = Image.new("L", clean.size, 0)
    ImageDraw.Draw(face).polygon([(172, 200), (376, 152), (384, 298), (170, 330)], fill=255)
    face = face.filter(ImageFilter.GaussianBlur(3))
    alpha = ImageChops.multiply(layer.getchannel("A"), face)
    alpha = ImageChops.multiply(alpha, clean.getchannel("A"))
    base = clean.convert("RGB")
    inked = ImageChops.multiply(base, Image.composite(layer.convert("RGB"), Image.new("RGB", clean.size, (255, 255, 255)), alpha))
    # multiply keeps the paper's light; blend a little straight colour so the red stays red
    straight = Image.composite(layer.convert("RGB"), base, alpha)
    out = Image.blend(inked, straight, 0.45)
    out.putalpha(clean.getchannel("A"))
    bbox = out.getchannel("A").getbbox()
    return out.crop(bbox)


def build_mark(mask_image):
    mask = mask_image.convert("L")
    mask = mask.point(lambda v: min(255, int(v * 2.4)))  # the "?" mask is soft; firm it up so both marks get the same outline
    bbox = mask.point(lambda v: 255 if v > 12 else 0).getbbox()
    pad = 44
    w, h = bbox[2] - bbox[0] + pad * 2, bbox[3] - bbox[1] + pad * 2
    m = Image.new("L", (w, h), 0)
    m.paste(mask.crop(bbox), (pad, pad))
    out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    glow = m.filter(ImageFilter.GaussianBlur(18)).point(lambda v: min(255, int(v * 1.2)))
    out.paste(Image.new("RGBA", (w, h), (255, 170, 40, 255)), (0, 0), glow.point(lambda v: int(v * 0.75)))
    outline = m.filter(ImageFilter.MaxFilter(9))
    out.paste(Image.new("RGBA", (w, h), (70, 40, 10, 255)), (0, 0), outline)
    body = Image.new("RGBA", (w, h), QUEST_GOLD + (255,))
    # top-lit: lighter towards the top, like the game's quest marks
    grad = Image.linear_gradient("L").resize((w, h))
    light = Image.composite(Image.new("RGBA", (w, h), (255, 244, 190, 255)), body, grad.point(lambda v: 255 - v).point(lambda v: int(v * 0.7)))
    out.paste(light, (0, 0), m)
    return out


def build_ground_x(size=260):
    rnd = random.Random(5)
    layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    c, k = size // 2, int(size * 0.34)
    for a, b in (((c - k, c - k), (c + k, c + k)), ((c - k, c + k), (c + k, c - k))):
        for _ in range(26):
            j = lambda: rnd.uniform(-7, 7)
            t0, t1 = rnd.uniform(0, 0.25), rnd.uniform(0.75, 1)
            p0 = (a[0] + (b[0] - a[0]) * t0 + j(), a[1] + (b[1] - a[1]) * t0 + j())
            p1 = (a[0] + (b[0] - a[0]) * t1 + j(), a[1] + (b[1] - a[1]) * t1 + j())
            shade = rnd.randrange(-26, 20)
            d.line((p0, p1), fill=(RED[0] + shade, RED[1] + shade // 3, RED[2] + shade // 3, rnd.randrange(120, 215)), width=rnd.randrange(6, 15))
    layer = layer.filter(ImageFilter.GaussianBlur(1.1))
    # painted on the ground: flatten to the map camera's perspective and add a dark edge
    flat = layer.resize((size, int(size * 0.56)), Image.BICUBIC)
    edge = flat.getchannel("A").filter(ImageFilter.MaxFilter(5)).filter(ImageFilter.GaussianBlur(2))
    out = Image.new("RGBA", flat.size, (0, 0, 0, 0))
    out.paste(Image.new("RGBA", flat.size, (40, 12, 8, 255)), (0, 3), edge.point(lambda v: int(v * 0.55)))
    out.alpha_composite(flat)
    return out


def build_hole(size=220):
    w, h = size, int(size * 0.6)
    rnd = random.Random(9)
    out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(out)
    cx, cy = w // 2, h // 2
    for _ in range(70):  # dirt rim clods
        a = rnd.uniform(0, math.tau)
        r = rnd.uniform(0.80, 1.0)
        x, y = cx + math.cos(a) * w * 0.40 * r, cy + math.sin(a) * h * 0.36 * r + 4
        s = rnd.randrange(8, 18)
        g = rnd.randrange(-18, 22)
        d.ellipse((x - s, y - s * 0.6, x + s, y + s * 0.6), fill=(118 + g, 86 + g, 54 + g, 255))
    d.ellipse((cx - w * 0.30, cy - h * 0.24, cx + w * 0.30, cy + h * 0.26), fill=(26, 17, 11, 255))
    d.ellipse((cx - w * 0.26, cy - h * 0.10, cx + w * 0.26, cy + h * 0.26), fill=(12, 8, 5, 255))
    out = out.filter(ImageFilter.GaussianBlur(1.3))
    # rim light from the top-left, shadow bottom-right
    hl = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(hl).arc((cx - w * 0.40, cy - h * 0.34, cx + w * 0.40, cy + h * 0.40), 180, 300, fill=(214, 180, 130, 150), width=5)
    out.alpha_composite(hl.filter(ImageFilter.GaussianBlur(2)))
    return out


GLOW_PAD = 0.18  # padding on every side as a fraction of the sprite height; Homm3CoveTreasureMarkers.GlowPad must match


def build_glow(sprite):
    """White outline glow fitted to a sprite's silhouette (tinted and pulsed by the plugin, drawn behind the sprite)."""
    w, h = sprite.size
    pad = round(h * GLOW_PAD)
    mask = Image.new("L", (w + 2 * pad, h + 2 * pad), 0)
    mask.paste(sprite.getchannel("A").point(lambda v: 255 if v > 150 else 0), (pad, pad))
    grow = max(3, int(h * 0.035)) | 1
    wide = mask.filter(ImageFilter.MaxFilter(grow)).filter(ImageFilter.GaussianBlur(h * 0.045))
    tight = mask.filter(ImageFilter.MaxFilter(grow)).filter(ImageFilter.GaussianBlur(h * 0.012))
    alpha = Image.eval(wide, lambda v: min(255, int(v * 1.25)))
    alpha = ImageChops.lighter(alpha, tight)
    out = Image.new("RGBA", mask.size, (255, 255, 255, 0))
    out.putalpha(alpha)
    return out




def main(data_dir, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    tex = load_textures(data_dir, ["magic_scroll_artifact", "Quest_mark_01_vfx", "Quest_mark_02_vfx"])
    build_map_piece(tex["magic_scroll_artifact"]).save(os.path.join(out_dir, "map_piece.png"))
    build_mark(tex["Quest_mark_01_vfx"]).save(os.path.join(out_dir, "mark_question.png"))
    build_mark(tex["Quest_mark_02_vfx"]).save(os.path.join(out_dir, "mark_exclaim.png"))
    build_ground_x().save(os.path.join(out_dir, "ground_x.png"))
    build_hole().save(os.path.join(out_dir, "hole.png"))
    for name in ("map_piece", "mark_question", "mark_exclaim", "ground_x"):
        build_glow(Image.open(os.path.join(out_dir, name + ".png")).convert("RGBA")).save(os.path.join(out_dir, name + "_glow.png"))
    print("wrote marker art to", out_dir)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    main(sys.argv[1], sys.argv[2])
