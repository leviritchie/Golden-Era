"""Cove Treasure Hunting mockup v4 (for approval before install): the Treasure Chart.

One parchment sheet that shows every region of the map and, per region, how many map pieces the player holds and
whether the treasure is still buried. Drawn from a real exported map (tools/cove_treasure/export_map_regions.py),
with invented piece counts. In game the body text uses the game's own font.
Usage: python tools/cove_treasure/chart_mockup.py <vanilla_dir> <map.json> <out.png>
"""
import json
import random
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

sys.path.insert(0, "tools/cove_treasure")
import marker_mockup as mm  # noqa: E402
import popup_marks_mockup as pm  # noqa: E402

INK = pm.INK
BLOOD = pm.BLOOD
# state -> parchment tint (multiplied over the paper)
TINT = {
    "uncharted": (150, 132, 100),
    "none": (236, 222, 184),
    "pieces": (244, 226, 160),
    "site": (250, 214, 120),
    "yours": (196, 214, 170),
    "rival": (176, 168, 158),
}


def region_layers(data, scale):
    w, h = data["width"], data["height"]
    grid = np.full(w * h, -1, dtype=np.int32)
    areas = sorted(data["areas"], key=lambda a: -len(a["nodes"]))
    sea = areas[0]["id"] if len(areas[0]["nodes"]) > w * h * 0.4 else None
    for a in areas:
        if a["id"] != sea:
            grid[np.array(a["nodes"], dtype=np.int64)] = a["id"]
    grid = grid.reshape(h, w)[::-1]  # node rows run bottom-up on the map
    big = np.kron(grid, np.ones((scale, scale), dtype=np.int32))
    return grid, big, [a for a in areas if a["id"] != sea]


def chart(data, size, paper_tex, seed):
    scale = size // data["width"]
    grid, big, areas = region_layers(data, scale)
    rnd = random.Random(seed)
    states = {}
    for a in areas:
        r = rnd.random()
        if r < 0.30:
            states[a["id"]] = ("uncharted", 0)
        elif r < 0.50:
            states[a["id"]] = ("none", 0)
        elif r < 0.78:
            states[a["id"]] = ("pieces", rnd.randrange(1, 4))
        elif r < 0.86:
            states[a["id"]] = ("site", rnd.randrange(4, 6))
        elif r < 0.94:
            states[a["id"]] = ("yours", 0)
        else:
            states[a["id"]] = ("rival", 0)
    hh, ww = big.shape
    tint = np.zeros((hh, ww, 3), dtype=np.float32)
    tint[:] = (150, 176, 178)  # sea wash
    for aid, (state, _) in states.items():
        tint[big == aid] = TINT[state]
    paper = np.asarray(paper_tex.convert("RGB").resize((ww, hh)), dtype=np.float32) / 255.0
    paper = 0.55 + 0.45 * paper / max(paper.mean(), 1e-3) * 0.9
    rgb = np.clip(tint * paper, 0, 255)
    # ink the borders between regions
    edge = np.zeros((hh, ww), dtype=bool)
    edge[:, 1:] |= big[:, 1:] != big[:, :-1]
    edge[1:, :] |= big[1:, :] != big[:-1, :]
    img = Image.fromarray(rgb.astype(np.uint8)).convert("RGBA")
    line = Image.fromarray((edge * 255).astype(np.uint8)).filter(ImageFilter.MaxFilter(3)).filter(ImageFilter.GaussianBlur(0.8))
    img.paste(Image.new("RGBA", img.size, (70, 46, 26, 255)), (0, 0), line)
    d = ImageDraw.Draw(img)
    f = pm.ttf("palab.ttf", 19)
    cross = pm.brush_glyph("X", 44, BLOOD, 5)
    grey = pm.brush_glyph("X", 40, (88, 82, 76), 6)
    bang = pm.brush_glyph("!", 52, BLOOD, 4)
    for a in areas:
        ys, xs = np.nonzero(grid == a["id"])
        if len(xs) < 60:
            continue
        cx, cy = int(xs.mean() * scale + scale / 2), int(ys.mean() * scale + scale / 2)
        state, n = states[a["id"]]
        if state == "pieces":
            for k in range(5):  # five pips, filled per piece held
                x = cx - 26 + k * 13
                d.ellipse((x - 5, cy - 5, x + 5, cy + 5), fill=(120, 30, 22) if k < n else None, outline=INK, width=2)
        elif state == "site":
            pm.stamp(img, bang, cx, cy, 40)
        elif state == "yours":
            pm.stamp(img, cross, cx, cy, 34)
        elif state == "rival":
            pm.stamp(img, grey, cx, cy, 30)
        elif state == "none":
            for k in range(5):
                x = cx - 26 + k * 13
                d.ellipse((x - 5, cy - 5, x + 5, cy + 5), outline=(120, 96, 66), width=1)
        else:
            d.text((cx, cy), "?", font=f, fill=(92, 78, 58), anchor="mm")
    return img, states


def main(vanilla_dir, map_json, out):
    paper_tex = Image.open(vanilla_dir + "/map_paper.png")
    data = json.load(open(map_json))
    base = Image.new("RGBA", (1900, 1180), (22, 24, 30, 255))
    d = ImageDraw.Draw(base)
    d.text((40, 24), "Cove Treasure Hunting: the Treasure Chart (mockup v4, schematic backdrop, invented progress)", font=pm.ttf("georgiab.ttf", 26), fill=mm.GOLD)
    note = pm.ttf("georgia.ttf", 17)

    # dimmed map behind the sheet
    x0, y0, w, h = 40, 76, 1820, 1064
    ter = mm.terrain(w, h, 23).convert("RGBA")
    ter.alpha_composite(Image.new("RGBA", (w, h), (8, 10, 16, 130)))
    base.alpha_composite(ter, (x0, y0))

    # how it opens: a small scroll button on the map HUD
    bx, by = x0 + 34, y0 + 30
    d.rounded_rectangle((bx, by, bx + 64, by + 64), 10, fill=(52, 34, 20), outline=(196, 156, 82), width=2)
    pm.stamp(base, Image.open(mm.ART_DIR + "/map_piece.png").convert("RGBA"), bx + 32, by + 32, 46)
    d.text((bx + 78, by + 8), "Chart button on the map screen\n(Cove heroes with the skill only),\nor hotkey T", font=note, fill=(240, 232, 214))

    # the sheet
    sw, sh = 1440, 1010
    sx, sy = x0 + (w - sw) // 2 + 120, y0 + 28
    sheet = pm.parchment(sw, sh, paper_tex, 31)
    shadow = Image.new("RGBA", base.size, (0, 0, 0, 0))
    shadow.paste(Image.new("RGBA", sheet.size, (0, 0, 0, 170)), (sx + 10, sy + 14), sheet.getchannel("A"))
    base.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(12)))
    base.alpha_composite(sheet, (sx, sy))
    d = ImageDraw.Draw(base)
    pm.stamp(base, pm.brush_glyph("Treasure Chart", 46, INK, 12), sx + sw // 2, sy + 60)
    d.line((sx + 70, sy + 104, sx + sw - 70, sy + 104), fill=(120, 86, 48), width=2)

    img, states = chart(data, 768, paper_tex, 7)
    mx, my = sx + 64, sy + 128
    base.alpha_composite(img, (mx, my))
    d.rectangle((mx - 2, my - 2, mx + img.size[0] + 1, my + img.size[1] + 1), outline=(70, 46, 26), width=3)

    # right column: tally, legend, hover card
    rx, ry = mx + img.size[0] + 44, my + 4
    fb, fi, fs = pm.ttf("palab.ttf", 23), pm.ttf("palai.ttf", 21), pm.ttf("pala.ttf", 20)
    count = lambda s: sum(1 for v in states.values() if v[0] == s)  # noqa: E731
    total = len(states)
    for line in (
        f"Treasures dug up by you: {count('yours')} of {total}",
        f"Lost to rivals: {count('rival')}",
        f"Sites marked, ready to dig: {count('site')}",
        f"Regions with map pieces: {count('pieces')}",
    ):
        d.text((rx, ry), line, font=fb, fill=(44, 30, 18))
        ry += 34
    ry += 16
    d.line((rx, ry, sx + sw - 70, ry), fill=(120, 86, 48), width=1)
    ry += 18
    cross = pm.brush_glyph("X", 44, BLOOD, 5)
    grey = pm.brush_glyph("X", 40, (88, 82, 76), 6)
    bang = pm.brush_glyph("!", 52, BLOOD, 4)
    legend = (
        ("pips", "Map pieces held, of 5 in the region"),
        ("bang", "Site marked: enough pieces to dig"),
        ("cross", "Treasure dug up by you"),
        ("grey", "Treasure taken by a rival"),
        ("q", "Uncharted: no hero of yours has been there"),
    )
    for kind, text in legend:
        cx, cy = rx + 36, ry + 16
        if kind == "pips":
            for k in range(5):
                x = cx - 26 + k * 13
                d.ellipse((x - 5, cy - 5, x + 5, cy + 5), fill=(120, 30, 22) if k < 2 else None, outline=INK, width=2)
        elif kind == "bang":
            pm.stamp(base, bang, cx, cy, 38)
        elif kind == "cross":
            pm.stamp(base, cross, cx, cy, 32)
        elif kind == "grey":
            pm.stamp(base, grey, cx, cy, 30)
        else:
            d.text((cx, cy), "?", font=fb, fill=(92, 78, 58), anchor="mm")
        d.text((rx + 84, ry + 4), text, font=fs, fill=(44, 30, 18))
        ry += 44
    ry += 14
    d.line((rx, ry, sx + sw - 70, ry), fill=(120, 86, 48), width=1)
    ry += 20
    # hover card
    d.text((rx, ry), "Hovering a region shows:", font=fi, fill=INK)
    ry += 36
    d.rounded_rectangle((rx, ry, sx + sw - 70, ry + 168), 8, fill=(246, 234, 200), outline=(120, 86, 48), width=2)
    for k, (text, col) in enumerate((
        ("Region 14", (44, 30, 18)),
        ("Map pieces: 2 of 5", (44, 30, 18)),
        ("3 possible sites marked", (44, 30, 18)),
        ("Treasure: still buried", (44, 30, 18)),
        ("Click to show the region on the map", BLOOD),
    )):
        d.text((rx + 18, ry + 14 + k * 29), text, font=fb if k == 0 else fs, fill=col)
    ry += 190
    for line in pm.wrap(d, "Dug regions keep their mark until the end of the game. Rivals' progress is never shown, only that a treasure is gone.", fi, sx + sw - 70 - rx):
        d.text((rx, ry), line, font=fi, fill=INK)
        ry += 28

    bw, bh, byy = 170, 46, sy + sh - 74
    cx = sx + sw // 2
    d.rounded_rectangle((cx - bw // 2, byy, cx + bw // 2, byy + bh), 8, fill=(52, 34, 20), outline=(196, 156, 82), width=2)
    d.text((cx, byy + bh // 2), "Close", font=pm.ttf("georgiab.ttf", 22), fill=(240, 208, 130), anchor="mm")
    base.convert("RGB").save(out)
    print("wrote", out)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3])
