"""Cove Treasure Hunting map-marker mockup (for approval before any marker is installed).

Marker art comes from tools/cove_treasure/build_marker_art.py (run it first).

Draws the proposed overlay markers on a schematic adventure-map backdrop (not a game screenshot):
map-piece markers on holders, a loose piece, lead markers through fog, the exact-site marker and the pickup notice.
Usage: python tools/cove_treasure/marker_mockup.py <out.png>
"""
import random
import sys

from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H = 1800, 1040
ART_DIR = "artifacts/cove_treasure/marker_art"
GOLD = (232, 190, 96)
NOTE = (190, 186, 176)


def font(size, bold=True):
    for name in (("georgiab.ttf" if bold else "georgia.ttf"), "arialbd.ttf"):
        try:
            return ImageFont.truetype("C:/Windows/Fonts/" + name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def terrain(w, h, seed, fog_from=None):
    rnd = random.Random(seed)
    im = Image.new("RGB", (w, h), (74, 112, 66))
    d = ImageDraw.Draw(im)
    for _ in range(900):
        x, y = rnd.randrange(w), rnd.randrange(h)
        r = rnd.randrange(8, 46)
        g = rnd.randrange(-14, 15)
        d.ellipse((x - r, y - r, x + r, y + r), fill=(74 + g, 112 + g, 66 + g // 2))
    for _ in range(26):
        x, y = rnd.randrange(w), rnd.randrange(h)
        d.ellipse((x - 16, y - 20, x + 16, y + 12), fill=(38, 78, 44))
        d.ellipse((x - 10, y - 26, x + 10, y - 4), fill=(48, 94, 52))
    im = im.filter(ImageFilter.GaussianBlur(1.6))
    if fog_from is not None:
        fog = Image.new("RGB", (w, h), (16, 20, 30))
        mask = Image.new("L", (w, h), 0)
        ImageDraw.Draw(mask).rectangle((fog_from, 0, w, h), fill=215)
        mask = mask.filter(ImageFilter.GaussianBlur(40))
        im.paste(fog, (0, 0), mask)
    return im


ART = {}


def art(name, height):
    key = (name, height)
    if key not in ART:
        im = Image.open(ART_DIR + "/" + name + ".png").convert("RGBA")
        w = max(1, round(im.size[0] * height / im.size[1]))
        ART[key] = im.resize((w, height), Image.LANCZOS)
    return ART[key]


def stamp(base, sprite, cx, cy, shadow=True):
    """Pastes a sprite centred on (cx, cy) with a soft drop shadow, the way the game lifts icons off the map."""
    x, y = int(cx - sprite.size[0] / 2), int(cy - sprite.size[1] / 2)
    if shadow:
        sh = Image.new("RGBA", sprite.size, (0, 0, 0, 0))
        sh.paste(Image.new("RGBA", sprite.size, (0, 0, 0, 150)), (0, 0), sprite.getchannel("A"))
        sh = sh.filter(ImageFilter.GaussianBlur(5))
        base.alpha_composite(sh, (x + 4, y + 7))
    base.alpha_composite(sprite, (x, y))


def ground_shadow(base, cx, cy, w):
    sh = Image.new("RGBA", (w * 2, w), (0, 0, 0, 0))
    ImageDraw.Draw(sh).ellipse((w * 0.5, w * 0.3, w * 1.5, w * 0.7), fill=(0, 0, 0, 120))
    base.alpha_composite(sh.filter(ImageFilter.GaussianBlur(6)), (int(cx - w), int(cy - w / 2)))


def piece_marker(base, cx, cy, loose=False):
    if loose:
        # lying on the tile: flattened and tilted, with a contact shadow
        s = art("map_piece", 74)
        flat = s.resize((s.size[0], int(s.size[1] * 0.62)), Image.LANCZOS).rotate(-8, resample=Image.BICUBIC, expand=True)
        ground_shadow(base, cx, cy + 34, 62)
        stamp(base, flat, cx, cy + 22)
    else:
        ground_shadow(base, cx, cy + 46, 34)
        stamp(base, art("map_piece", 78), cx, cy)


def lead_marker(base, cx, cy, exact=False):
    x = art("ground_x", 62 if exact else 44)
    if exact:
        glow = Image.new("RGBA", (220, 130), (0, 0, 0, 0))
        ImageDraw.Draw(glow).ellipse((20, 20, 200, 110), fill=(255, 200, 70, 120))
        base.alpha_composite(glow.filter(ImageFilter.GaussianBlur(18)), (int(cx - 110), int(cy - 65)))
    stamp(base, x, cx, cy, shadow=False)
    mark = art("mark_exclaim" if exact else "mark_question", 96 if exact else 70)
    stamp(base, mark, cx, cy - (92 if exact else 66))


def label(d, cx, y, text, size=17, fill=(240, 232, 214)):
    f = font(size)
    w = d.textlength(text, font=f)
    d.rounded_rectangle((cx - w / 2 - 10, y - 4, cx + w / 2 + 10, y + size + 8), radius=6, fill=(18, 22, 34, 215), outline=(120, 104, 70), width=1)
    d.text((cx - w / 2, y), text, font=f, fill=fill)


def chest(d, cx, cy):
    d.rounded_rectangle((cx - 20, cy - 12, cx + 20, cy + 14), radius=4, fill=(120, 78, 40), outline=(50, 30, 14), width=2)
    d.rectangle((cx - 20, cy - 2, cx + 20, cy + 2), fill=(214, 176, 80))
    d.rectangle((cx - 4, cy - 5, cx + 4, cy + 6), fill=(214, 176, 80), outline=(50, 30, 14))


def stack(d, cx, cy):
    d.ellipse((cx - 16, cy - 2, cx + 16, cy + 12), fill=(0, 0, 0, 80))
    d.polygon([(cx - 14, cy + 6), (cx - 10, cy - 20), (cx + 10, cy - 20), (cx + 14, cy + 6)], fill=(110, 40, 46), outline=(40, 20, 24))
    d.ellipse((cx - 9, cy - 38, cx + 9, cy - 20), fill=(196, 170, 150), outline=(40, 30, 30), width=2)
    d.line((cx + 16, cy - 40, cx + 16, cy + 6), fill=(190, 190, 200), width=3)


def hero(d, cx, cy):
    d.ellipse((cx - 20, cy + 2, cx + 20, cy + 16), fill=(0, 0, 0, 90))
    d.polygon([(cx - 16, cy + 8), (cx - 10, cy - 26), (cx + 10, cy - 26), (cx + 16, cy + 8)], fill=(34, 86, 140), outline=(14, 30, 54))
    d.ellipse((cx - 10, cy - 46, cx + 10, cy - 26), fill=(214, 180, 150), outline=(40, 30, 30), width=2)
    d.polygon([(cx - 14, cy - 44), (cx + 14, cy - 44), (cx + 6, cy - 54), (cx - 6, cy - 54)], fill=(30, 30, 40))


def panel(base, x, y, w, h, title, seed, fog_from=None):
    base.paste(terrain(w, h, seed, fog_from), (x, y))
    d = ImageDraw.Draw(base)
    d.rectangle((x, y, x + w, y + h), outline=(150, 128, 80), width=2)
    d.rectangle((x, y, x + w, y + 34), fill=(18, 22, 34, 235))
    d.text((x + 12, y + 6), title, font=font(19), fill=GOLD)
    return d


def main(out):
    im = Image.new("RGBA", (W, H), (22, 24, 32, 255))
    d0 = ImageDraw.Draw(im)
    d0.text((30, 18), "Cove Treasure Hunting: map markers, v2 (vanilla scroll and quest-mark art; schematic backdrop)", font=font(28), fill=GOLD)
    d0.text((30, 56), "Markers are an overlay for the Cove side only. They show through fog and do not block clicks.", font=font(17, False), fill=(200, 196, 186))

    pw, ph = 860, 440
    x1, x2, y1, y2 = 30, 30 + pw + 20, 96, 96 + ph + 20

    d = panel(im, x1, y1, pw, ph, "1. Search: pieces within 3 tiles of a Cove hero are marked", 3)
    hx, hy = x1 + 300, y1 + 290
    d.rounded_rectangle((hx - 150, hy - 144, hx + 150, hy + 156), radius=30, outline=(232, 190, 96, 110), width=2)
    hero(d, hx, hy)
    chest(d, hx + 110, hy - 96)
    piece_marker(im, hx + 110, hy - 160)
    label(d, hx + 110, hy - 70, "Map piece")
    stack(d, hx - 100, hy - 70)
    piece_marker(im, hx - 100, hy - 162)
    label(d, hx - 100, hy - 52, "Map piece")
    chest(d, hx + 420, hy - 40)
    label(d, hx + 420, hy - 14, "outside the search range: not marked", 15, NOTE)
    label(d, hx + 30, hy + 120, "search range outline is for this mockup only", 14, NOTE)

    d = panel(im, x2, y1, pw, ph, "2. Holder taken by someone else: the piece stays on the tile", 7)
    bx, by = x2 + 250, y1 + 290
    piece_marker(im, bx, by - 40, loose=True)
    label(d, bx, by + 34, "Map piece (step here)")
    hx2, hy2 = bx + 340, by + 10
    hero(d, hx2, hy2)
    f = font(24)
    text = "Map piece 2/5: 3 possible sites"
    w = d.textlength(text, font=f)
    d.text((hx2 - w / 2, hy2 - 108), text, font=f, fill=(255, 226, 150), stroke_width=3, stroke_fill=(20, 14, 10))
    label(d, hx2, hy2 + 30, "notice floats above the hero for 3 seconds", 14, NOTE)

    d = panel(im, x1, y2, pw, ph, "3. First piece: 4 possible treasure sites, visible through fog", 11, fog_from=330)
    for px, py in ((180, 190), (430, 130), (610, 300), (760, 170)):
        lead_marker(im, x1 + px, y2 + py)
        label(d, x1 + px, y2 + py + 34, "Possible site", 15)
    label(d, x1 + 430, y2 + 392, "each further piece removes one false site: 4 > 3 > 2 > 1", 15, NOTE)

    d = panel(im, x2, y2, pw, ph, "4. Fourth piece: only the real site is left", 13, fog_from=330)
    lead_marker(im, x2 + 610, y2 + 240, exact=True)
    label(d, x2 + 610, y2 + 290, "Buried treasure", 18, (255, 226, 150))
    stamp(im, art("hole", 54), x2 + 195, y2 + 208, shadow=False)
    label(d, x2 + 195, y2 + 236, "Hole", 15)
    label(d, x2 + 330, y2 + 392, "a wrong dig leaves a hole (arrives with the Dig step)", 15, NOTE)

    im.convert("RGB").save(out)
    print(out)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "marker_mockup.png")
