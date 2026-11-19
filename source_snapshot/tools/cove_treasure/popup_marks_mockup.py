"""Cove Treasure Hunting mockup v3 (for approval before install): pirate-style map marks and the central popups.

Left: the current "?"/"!" marks next to the proposed brush-inked ones, each with the pulsing gold halo.
Right: the proposed central, confirmed popups for a map piece, a treasure and an empty hole.
Schematic backdrop, not a game screenshot. In game the body text uses the game's own font.
Usage: python tools/cove_treasure/popup_marks_mockup.py <vanilla_dir> <out.png>
  vanilla_dir holds map_paper.png (exported crumpled-paper texture).
"""
import random
import sys

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

sys.path.insert(0, "tools/cove_treasure")
import marker_mockup as mm  # noqa: E402

FONTS = "C:/Windows/Fonts/"
INK = (58, 38, 22)
BLOOD = (150, 26, 20)
PAPER = (222, 198, 150)


def ttf(name, size):
    return ImageFont.truetype(FONTS + name, size)


def noise(size, cell, seed, blur):
    rnd = random.Random(seed)
    w, h = size
    small = Image.new("L", (max(2, w // cell), max(2, h // cell)))
    small.putdata([rnd.randrange(256) for _ in range(small.size[0] * small.size[1])])
    return small.resize(size, Image.BICUBIC).filter(ImageFilter.GaussianBlur(blur))


def brush_glyph(text, size, color, seed, font_name="palabi.ttf"):
    """A glyph that looks painted with a loaded brush: swollen, ragged edge, dry streaks, darker rim."""
    f = ttf(font_name, size)
    box = f.getbbox(text)
    pad = size // 3
    w, h = box[2] - box[0] + pad * 2, box[3] - box[1] + pad * 2
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).text((pad - box[0], pad - box[1]), text, font=f, fill=255)
    mask = mask.filter(ImageFilter.MaxFilter(2 * max(1, size // 34) + 1))
    # ragged edge: threshold a blurred mask against noise
    soft = mask.filter(ImageFilter.GaussianBlur(size / 28))
    rag = noise((w, h), max(2, size // 22), seed, size / 60)
    edge = ImageChops.add(soft, rag.point(lambda v: (v - 128) // 2), 1, 0).point(lambda v: 255 if v > 118 else 0)
    # dry-brush streaks
    rnd = random.Random(seed + 1)
    streaks = Image.new("L", (w, h), 255)
    d = ImageDraw.Draw(streaks)
    for _ in range(size // 5):
        x, y = rnd.randrange(w), rnd.randrange(h)
        ln = rnd.randrange(size // 6, size // 2)
        d.line((x, y, x + ln, y - ln // 3), fill=rnd.randrange(90, 190), width=1)
    edge = ImageChops.multiply(edge, streaks).filter(ImageFilter.GaussianBlur(0.7))
    out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    rim = edge.filter(ImageFilter.MaxFilter(2 * max(1, size // 30) + 1))
    out.paste(Image.new("RGBA", (w, h), (246, 232, 196, 255)), (0, 0), rim)  # parchment-coloured rim keeps it readable on any ground
    dark = tuple(int(c * 0.55) for c in color)
    out.paste(Image.new("RGBA", (w, h), dark + (255,)), (0, 0), edge)
    inner = edge.filter(ImageFilter.MinFilter(2 * max(1, size // 40) + 1))
    out.paste(Image.new("RGBA", (w, h), color + (255,)), (0, 0), inner)
    return out


def halo(base, cx, cy, w, h, alpha):
    layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    ImageDraw.Draw(layer).ellipse((cx - w // 2, cy - h // 2, cx + w // 2, cy + h // 2), fill=(255, 214, 107, alpha))
    base.alpha_composite(layer.filter(ImageFilter.GaussianBlur(min(w, h) / 4)))


def stamp(base, sprite, cx, cy, height=None):
    if height:
        sprite = sprite.resize((max(1, round(sprite.size[0] * height / sprite.size[1])), height), Image.LANCZOS)
    base.alpha_composite(sprite, (int(cx - sprite.size[0] / 2), int(cy - sprite.size[1] / 2)))


def parchment(w, h, paper_tex, seed):
    rnd = random.Random(seed)
    tex = paper_tex.convert("L")
    x, y = rnd.randrange(tex.size[0] - w), rnd.randrange(tex.size[1] - h)
    crumple = tex.crop((x, y, x + w, y + h)).point(lambda v: max(0, min(255, int((v - 150) * 3.2 + 205))))
    sheet = ImageChops.multiply(Image.new("RGB", (w, h), PAPER), Image.merge("RGB", (crumple, crumple, crumple)))
    # torn edge
    m = Image.new("L", (w, h), 0)
    ImageDraw.Draw(m).rounded_rectangle((14, 14, w - 14, h - 14), 18, fill=255)
    rag = noise((w, h), 9, seed, 2.2)
    m = ImageChops.add(m.filter(ImageFilter.GaussianBlur(7)), rag.point(lambda v: (v - 128) // 2), 1, 0).point(lambda v: 255 if v > 130 else 0)
    m = m.filter(ImageFilter.GaussianBlur(0.8))
    # scorched rim
    rim = ImageChops.subtract(m, m.filter(ImageFilter.GaussianBlur(16)).point(lambda v: 255 if v > 235 else int(v * 0.4)))
    sheet.paste(Image.new("RGB", (w, h), (96, 62, 30)), (0, 0), rim.filter(ImageFilter.GaussianBlur(5)).point(lambda v: min(255, v * 2)))
    out = sheet.convert("RGBA")
    out.putalpha(m)
    return out


def wrap(d, text, f, width):
    lines, line = [], ""
    for word in text.split():
        trial = (line + " " + word).strip()
        if d.textlength(trial, font=f) <= width:
            line = trial
        else:
            lines.append(line)
            line = word
    lines.append(line)
    return lines


def popup(base, cx, top, w, h, paper_tex, seed, title, flavor, facts, button="OK", mark=None):
    sheet = parchment(w, h, paper_tex, seed)
    shadow = Image.new("RGBA", base.size, (0, 0, 0, 0))
    shadow.paste(Image.new("RGBA", sheet.size, (0, 0, 0, 170)), (cx - w // 2 + 10, top + 14), sheet.getchannel("A"))
    base.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(12)))
    base.alpha_composite(sheet, (cx - w // 2, top))
    d = ImageDraw.Draw(base)
    y = top + 34
    t = brush_glyph(title, 46, INK, seed + 7)
    stamp(base, t, cx, y + 26)
    y += 70
    d.line((cx - w // 2 + 70, y, cx + w // 2 - 70, y), fill=(120, 86, 48), width=2)
    y += 16
    fi = ttf("palai.ttf", 22)
    for line in wrap(d, flavor, fi, w - 120):
        d.text((cx, y), line, font=fi, fill=INK, anchor="ma")
        y += 29
    y += 12
    fb = ttf("palab.ttf", 21)
    for fact in facts:
        colour = BLOOD if fact.startswith("*") else (44, 30, 18)
        for line in wrap(d, fact.lstrip("*"), fb, w - 120):
            d.text((cx, y), line, font=fb, fill=colour, anchor="ma")
            y += 28
    if mark is not None:
        stamp(base, mark, cx + w // 2 - 78, top + h - 96, 92)
    # button: dark wood plate with gold text, as the game's confirm buttons
    bw, bh, by = 170, 46, top + h - 76
    d.rounded_rectangle((cx - bw // 2, by, cx + bw // 2, by + bh), 8, fill=(52, 34, 20), outline=(196, 156, 82), width=2)
    d.text((cx, by + bh // 2), button, font=ttf("georgiab.ttf", 22), fill=(240, 208, 130), anchor="mm")


def main(vanilla_dir, out):
    paper_tex = Image.open(vanilla_dir + "/map_paper.png")
    base = Image.new("RGBA", (1900, 1180), (22, 24, 30, 255))
    d = ImageDraw.Draw(base)
    title = ttf("georgiab.ttf", 26)
    note = ttf("georgia.ttf", 17)
    d.text((40, 24), "Cove Treasure Hunting: pirate marks and central popups (mockup v3, schematic backdrop)", font=title, fill=mm.GOLD)

    q = brush_glyph("?", 150, BLOOD, 3)
    e = brush_glyph("!", 170, BLOOD, 4)
    gx = Image.open(mm.ART_DIR + "/ground_x.png").convert("RGBA")

    # ---- left: marks on the map
    panels = (("Now", False), ("Proposed: brush-inked marks + pulsing gold halo", True))
    for i, (name, new) in enumerate(panels):
        x0, y0, w, h = 40, 80 + i * 540, 620, 500
        ter = mm.terrain(w, h, 11, fog_from=430).convert("RGBA")
        base.alpha_composite(ter, (x0, y0))
        d.rectangle((x0, y0, x0 + w, y0 + h), outline=(90, 90, 96))
        d.text((x0 + 12, y0 + 10), name, font=ttf("georgiab.ttf", 19), fill=(240, 232, 214))
        spots = ((x0 + 130, y0 + 330, False), (x0 + 330, y0 + 240, False), (x0 + 520, y0 + 360, True))
        for cx, cy, exact in spots:
            if new:
                halo(base, cx, cy - (46 if exact else 34), 150 if exact else 120, 190 if exact else 150, 105 if exact else 80)
                stamp(base, gx, cx, cy, 58 if exact else 44)
                stamp(base, e if exact else q, cx, cy - (84 if exact else 62), 104 if exact else 78)
            else:
                mm.lead_marker(base, cx, cy, exact=exact)
        mm.piece_marker(base, x0 + 220, y0 + 420)
        if new:
            halo(base, x0 + 220, y0 + 420 - 68, 150, 150, 90)
            mm.piece_marker(base, x0 + 220, y0 + 420)
        d.text((x0 + 12, y0 + h - 30), "possible site  ·  possible site  ·  exact site (4 pieces)  ·  map piece on a pickup", font=note, fill=mm.NOTE)

    # ---- right: popups over a dimmed map
    x0, y0, w, h = 700, 80, 1160, 1040
    ter = mm.terrain(w, h, 23).convert("RGBA")
    ter.alpha_composite(Image.new("RGBA", (w, h), (8, 10, 16, 120)))
    base.alpha_composite(ter, (x0, y0))
    d.rectangle((x0, y0, x0 + w, y0 + h), outline=(90, 90, 96))
    d.text((x0 + 12, y0 + 10), "Proposed popups: centred, the map dims, closes on OK / Enter / Esc", font=ttf("georgiab.ttf", 19), fill=(240, 232, 214))

    popup(base, x0 + 300, y0 + 56, 540, 400, paper_tex, 5, "A Scrap of a Map",
          "Among the spoils lies a torn scrap of sea-stained parchment. Whoever drew it took great pains to hide what it points to.",
          ["Map piece 2 of 5 for this region.", "3 possible sites remain. Each further piece rules one out; the 4th marks the spot."],
          )
    popup(base, x0 + 860, y0 + 56, 540, 400, paper_tex, 9, "X Marks the Spot",
          "The last tear fits. Faded ink joins into a single bold cross, and your navigator grins from ear to ear.",
          ["Map piece 4 of 5 for this region.", "The treasure site is marked on the map.", "*Digging needs two thirds of a day's movement."],
          )
    popup(base, x0 + 300, y0 + 500, 540, 480, paper_tex, 14, "Buried Treasure!",
          "A spade rings on iron. The crew hauls a brine-crusted chest out of the pit and its rotten lock gives way to a single blow.",
          ["3,400 gold", "8 wood", "3 Liches join your army", "Artifact: Ring of Vitality", "*The hero's movement is spent for today."],
          button="Take it")
    popup(base, x0 + 860, y0 + 500, 540, 400, paper_tex, 21, "Nothing but Sand",
          "Your men dig until their backs give out and find only worms and wet sand. The map lied, or you read it wrong.",
          ["An empty hole is left. This lead is struck from the map.", "*The hero's movement is spent for today."])
    d.text((x0 + 600, y0 + 930), "Refusals (road, too little movement, already dug)\nstay as the short banner: they cost nothing.", font=note, fill=mm.NOTE)
    base.convert("RGB").save(out)
    print("wrote", out)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
