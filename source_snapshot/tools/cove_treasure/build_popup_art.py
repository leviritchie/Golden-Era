"""Bake the Cove Treasure Hunting brush-inked marks and central popup art (approved mockup v3, 2026-11-17).

Usage: python tools/cove_treasure/build_popup_art.py <vanilla_dir> <out_dir>
  vanilla_dir holds map_paper.png (exported crumpled-paper texture); out_dir is the plugin's homm3_ui/cove_treasure.
Writes mark_question/mark_exclaim (+ _glow), popup_paper, popup_title_<kind>, popup_button and popup_button_hover.
"""
import os
import sys

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, "tools/cove_treasure")
import build_marker_art as art  # noqa: E402
import popup_marks_mockup as mock  # noqa: E402

TITLES = {
    "piece": "A Scrap of a Map",
    "spot": "X Marks the Spot",
    "treasure": "Buried Treasure!",
    "hole": "Nothing but Sand",
    "chart": "Treasure Chart",
}


def button(hover):
    w, h = 340, 92
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    fill = (74, 50, 28) if hover else (52, 34, 20)
    rim = (244, 208, 120) if hover else (196, 156, 82)
    d.rounded_rectangle((2, 2, w - 3, h - 3), 16, fill=fill + (255,), outline=rim + (255,), width=4)
    return im


def main(vanilla_dir, out_dir):
    paper = Image.open(os.path.join(vanilla_dir, "map_paper.png"))
    save = lambda im, name: im.save(os.path.join(out_dir, name + ".png"))
    for name, glyph, size, seed in (("mark_question", "?", 230, 3), ("mark_exclaim", "!", 250, 4)):
        mark = mock.brush_glyph(glyph, size, mock.BLOOD, seed)
        save(mark, name)
        save(art.build_glow(mark), name + "_glow")
    save(mock.parchment(1080, 900, paper, 5), "popup_paper")
    for kind, text in TITLES.items():
        save(mock.brush_glyph(text, 92, mock.INK, 12), "popup_title_" + kind)
    save(button(False), "popup_button")
    save(button(True), "popup_button_hover")
    print("wrote popup art to", out_dir)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    main(sys.argv[1], sys.argv[2])
