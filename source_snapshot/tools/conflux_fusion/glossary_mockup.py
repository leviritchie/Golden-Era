"""Approval mockups of the Elemental Fusion glossary (encyclopedia of all fusions) and its button on the fusion panel.

Data: tools/conflux_fusion/fusion_glossary.py output (built Core rows: names, stats, ability / passive cards, unlock rank).
Look: the fusion panel's native shell (Homm3DungeonWarCaptivesWindowLayout sprites) plus native list sprites exported
read-only from the installed game: Button_Database ("?" database button), KeyField (search field), tab_1 / tab_highlight_1 / tab_selected_1
(filter tabs, column headers), tab_1 / tab_selected_1 (rows), scroll_background / scroll (scrollbar), Dropdown_arrow (sort).
Stage 2 fusions use their own colour (name, row tint, badge) and the detail page shows a family tree.

    python tools/conflux_fusion/glossary_mockup.py --glossary <glossary.json> [--out V:/olden_port_work/elemental_fusion/glossary/mockup]
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from PIL import Image, ImageDraw

import panel_mockup as pmk
from panel_mockup import MOD, PANEL_CS, PORTRAITS, SKILL_ICON, WINDOW_CS, meter, pm

STAGE2 = (190, 150, 255, 255)        # stage 2: astral violet (names, badge, tree root)
STAGE2_ROW = (170, 110, 255, 90)    # tint on the native row plate
EXTRA = ["Button_Database", "Button_Database_MouseOver", "tab_highlight_1",
         "scroll_background", "scroll", "KeyField", "KeyField_MouseOver", "Dropdown_arrow", "tab_1", "tab_selected_1"]
WIN_W, WIN_H = 1520, 900
ROW_H, HEAD_H = 50, 40
COLS = [  # key, label, width, align
    ("name", "Name", 205, "left"), ("parents", "Fused from", 245, "left"), ("rank", "Needs", 92, "center"),
    ("hp", "HP", 58, "center"), ("attack", "Atk", 50, "center"), ("defence", "Def", 50, "center"),
    ("damage", "Damage", 78, "center"), ("speed", "Spd", 48, "center"), ("initiative", "Init", 48, "center"),
]
THUMB = 56


def clean(text: str | None) -> str:
    text = re.sub(r"<[^>]+>", "", text or "")
    return re.sub(r"\{\d+\}", "#", text).replace("\u00a0", " ").strip()


def sort_key(e, key):
    if key == "parents":
        return " ".join(e["parents"]).lower()
    if key == "damage":
        return (e["damageMin"] + e["damageMax"]) / 2
    if key == "name":
        return e["name"].lower()
    return e[key]


def matches(e, q):
    q = q.lower()
    hay = [e["name"], *e["parents"]] + [c["name"] or "" for c in e["abilities"] + e["passives"]] + [c["description"] or "" for c in e["abilities"] + e["passives"]]
    return any(q in h.lower() for h in hay)


class Glossary:
    def __init__(self, P, W, cv, entries, by_sid, portraits, icons):
        self.P, self.W, self.cv, self.entries, self.by_sid, self.portraits, self.icons = P, W, cv, entries, by_sid, portraits, icons

    # -- shell (same native frame as the fusion panel, bigger)
    def shell(self, title):
        P, W, cv = self.P, self.W, self.cv
        w, h = WIN_W, WIN_H
        cv.ox, cv.oy = P["ReferenceWidth"] / 2 - w / 2, P["ReferenceHeight"] / 2 - h / 2
        cv.sprite(W["SpriteRecruitBack"], 0, 0, w, h)
        cv.sliced(W["SpriteRecruitGradient"], 0, 0, w, h, 1.0)
        cv.sliced(W["SpriteRecruitBackFrame"], 0, 0, w, h, 1.0)
        cv.sliced(W["SpriteRecruitFrame"], 0, 0, w, h, 1.0)
        c = W["RecruitCorner"]
        for x, y, fx, fy in ((0, 0, 0, 0), (w - c, 0, 1, 0), (0, h - c, 0, 1), (w - c, h - c, 1, 1)):
            im = cv.spr[W["SpriteRecruitCorner"]]
            im = im.transpose(Image.FLIP_LEFT_RIGHT) if fx else im
            im = im.transpose(Image.FLIP_TOP_BOTTOM) if fy else im
            cv.image(im, x, y, c, c)
        cv.centered(W["SpriteRecruitDecorFooter"], w / 2, h - W["RecruitDecorFooterHeight"] / 2, W["RecruitDecorFooterWidth"], W["RecruitDecorFooterHeight"])
        ov = W["RecruitHeaderOverhang"]
        cv.sliced(W["SpriteRecruitHeader"], -ov / 2, 0, w + ov, W["RecruitHeaderHeight"], 1.0)
        cv.centered(W["SpriteRecruitDecorHeader"], w / 2, W["RecruitDecorHeaderHeight"] / 2 - W["RecruitFrameInset"], W["RecruitDecorHeaderWidth"], W["RecruitDecorHeaderHeight"])
        cv.text(P["FontBook"], P["SizeSubHeader"], title, w / 2 - 300, 0, 600, W["RecruitHeaderHeight"], P["TipTitle"], "center")

    def tab(self, label, x, y, w, h, selected=False, hover=False):
        name = "tab_selected_1" if selected else "tab_highlight_1" if hover else "tab_1"
        self.cv.sprite(name, x, y, w, h)
        self.cv.text(self.P["FontMedium"], self.P["SizeSmall"], label, x, y, w, h, self.P["TipTitle"] if selected else self.P["ButtonText"], "center")

    def thumb(self, sid, x, y, size, tint=None):
        """Native unit card, portrait masked into it (same as the fusion panel's cards, scaled)."""
        W, cv = self.W, self.cv
        k = size / W["RecruitCardWidth"]
        cw, ch = W["RecruitCardWidth"] * k, W["RecruitCardHeight"] * k
        cv.centered(W["SpriteRecruitCard"], x + cw / 2, y + ch / 2, cw, ch, tint)
        im = self.portraits.get(sid)
        if im is None:
            return ch
        pw, ph = W["RecruitPortraitWidth"] * k, W["RecruitPortraitHeight"] * k
        s = max(pw / im.width, ph / im.height)
        big = im.resize((max(1, round(im.width * s * 2)), max(1, round(im.height * s * 2))), Image.LANCZOS)
        ox, oy = (big.width - round(pw * 2)) // 2, (big.height - round(ph * 2)) // 2
        crop = big.crop((ox, oy, ox + round(pw * 2), oy + round(ph * 2)))
        mask = cv.spr[W["SpriteRecruitPortraitMask"]].resize(crop.size, Image.LANCZOS).getchannel("A")
        crop.putalpha(Image.composite(crop.getchannel("A"), Image.new("L", crop.size, 0), mask))
        cv.image(crop, x + cw / 2 - pw / 2, y + ch / 2 - ph / 2, pw, ph, tint)
        return ch

    def render(self, query, stage_filter, sort, desc, selected_sid, hover_row=None):
        P, cv = self.P, self.cv
        self.shell("Fusion Glossary")
        top = self.W["RecruitHeaderHeight"] + 22
        # toolbar: search + stage tabs + count
        cv.sliced("KeyField", 34, top, 440, 46, 1.6)
        cv.text(P["FontMedium"], P["SizeMain"], query + "|" if query else "Search names, parents, abilities\u2026", 62, top, 400, 46,
                P["TipBody"] if query else P["TipNote"], "left")
        rows = [e for e in self.entries if (stage_filter == 0 or e["stage"] == stage_filter) and (not query or matches(e, query))]
        rows.sort(key=lambda e: (sort_key(e, sort), e["name"]), reverse=desc)
        n1 = sum(1 for e in self.entries if e["stage"] == 1)
        n2 = len(self.entries) - n1
        tx = 500
        for i, (label, f) in enumerate(((f"All ({len(self.entries)})", 0), (f"Stage I ({n1})", 1), (f"Stage II ({n2})", 2))):
            self.tab(label, tx + i * 172, top + 3, 166, 40, stage_filter == f)
        # list header
        lx, ly = 30, top + 70
        x = lx + THUMB + 14
        cv.sprite("tab_1", lx, ly, THUMB + 14, HEAD_H)
        for key, label, w, align in COLS:
            if key == sort:
                cv.sprite("tab_selected_1", x, ly, w - 2, HEAD_H)
                lw = cv.fonts[P["FontMedium"]].advance(label, P["SizeSmall"])
                lx0 = x + (w - 2 - lw - 16) / 2
                cv.text(P["FontMedium"], P["SizeSmall"], label, lx0, ly, lw + 2, HEAD_H, P["TipTitle"], "left")
                arrow = cv.spr["Dropdown_arrow"]
                arrow = arrow if desc else arrow.transpose(Image.FLIP_TOP_BOTTOM)
                cv.image(arrow, lx0 + lw + 4, ly + HEAD_H / 2 - 5, 12, 10)
            else:
                self.tab(label, x, ly, w - 2, HEAD_H)
            x += w
        list_w = x - lx
        # rows
        y0 = ly + HEAD_H + 6
        visible = int((WIN_H - 70 - y0) // ROW_H)
        start = 0
        if selected_sid and selected_sid in [e["sid"] for e in rows]:
            start = max(0, min([e["sid"] for e in rows].index(selected_sid) - 2, len(rows) - visible))
        for i, e in enumerate(rows[start:start + visible]):
            y = y0 + i * ROW_H
            stage2 = e["stage"] == 2
            sel = e["sid"] == selected_sid
            plate = "tab_selected_1" if sel or hover_row == i else "tab_1"
            cv.sliced(plate, lx, y, list_w, ROW_H - 4, 1.0)
            if stage2 and not sel:  # second native plate, violet at low alpha, over the row
                cv.sliced("tab_selected_1", lx, y, list_w, ROW_H - 4, 1.0, STAGE2_ROW)
            if stage2:
                cv.image(Image.new("RGBA", (4, 4), STAGE2), lx, y, 4, ROW_H - 4)
            self.thumb(e["sid"], lx + 10, y + 1, (ROW_H - 6) * self.W["RecruitCardWidth"] / self.W["RecruitCardHeight"])
            x = lx + THUMB + 14
            for key, _label, w, align in COLS:
                if key == "name":
                    val, col = e["name"], STAGE2 if stage2 else P["TipTitle"]
                elif key == "parents":
                    val, col = " + ".join(e["parents"]), P["TipBody"]
                elif key == "rank":
                    val, col = e["rankName"], P["TipNote"]
                elif key == "damage":
                    val, col = f"{e['damageMin']}\u2013{e['damageMax']}", P["TipBody"]
                else:
                    val, col = str(e[key]), P["TipBody"]
                cv.text(P["FontMedium"], P["SizeSmall"], val, x + 8, y, w - 14, ROW_H - 4, col, align, wrap=key in ("name", "parents"))
                x += w
        cv.text(P["FontMedium"], P["SizeSmall"], f"{len(rows)} of {len(self.entries)} shown", lx, y0 + visible * ROW_H + 4, list_w, 26, P["TipNote"], "right")
        # scrollbar
        sx, sh = lx + list_w + 8, visible * ROW_H
        cv.sliced("scroll_background", sx, y0, 12, sh, 1.0)
        thumb_h = max(40, sh * visible / max(len(rows), 1))
        thumb_y = y0 + (sh - thumb_h) * (start / max(1, len(rows) - visible)) if len(rows) > visible else y0
        if len(rows) > visible:
            cv.sliced("scroll", sx, thumb_y, 12, thumb_h, 1.0)
        # detail page
        e = self.by_sid.get(selected_sid) if selected_sid else None
        if e is not None:
            self.detail(e, sx + 34, top, WIN_W - (sx + 34) - 34)
        return rows

    def detail(self, e, x, y, w):
        P, cv = self.P, self.cv
        stage2 = e["stage"] == 2
        ch = self.thumb(e["sid"], x, y, 110)
        cv.text(P["FontBook"], P["SizeHeaderBig"], e["name"], x + 128, y + 2, w - 128, 34, STAGE2 if stage2 else P["TipTitle"], "left")
        kind = "Stage II fusion" if stage2 else "Fusion"
        cv.text(P["FontMedium"], P["SizeSmall"], kind, x + 128, y + 38, w - 128, 22, STAGE2 if stage2 else P["TipNote"], "left")
        traits = ["Ranged" if e["ranged"] else "Melee"] + [c["name"] for c in e["passives"] if c["name"] == "Flying"]
        cv.text(P["FontMedium"], P["SizeSmall"], " \u00b7 ".join(traits), x + 128, y + 62, w - 128, 22, P["TipBody"], "left")
        cv.text(P["FontMedium"], P["SizeSmall"], f"Needs {e['rankName']} Conflux", x + 128, y + 86, w - 128, 22, P["TipNote"], "left")
        # stats
        sy = y + ch + 14
        stats = [("HP", e["hp"]), ("Attack", e["attack"]), ("Defence", e["defence"]), ("Damage", f"{e['damageMin']}\u2013{e['damageMax']}"),
                 ("Speed", e["speed"]), ("Initiative", e["initiative"])]
        cw = w / 3
        for i, (label, val) in enumerate(stats):
            cx, cy = x + (i % 3) * cw, sy + (i // 3) * 46
            cv.sprite("tab_1", cx, cy, cw - 6, 40)
            cv.text(P["FontMedium"], P["SizeSmall"], label, cx + 10, cy, cw - 20, 40, P["TipNote"], "left")
            cv.text(P["FontMedium"], P["SizeMain"], str(val), cx + 10, cy, cw - 26, 40, P["TipBody"], "right")
        # family tree
        ty = sy + 104
        cv.text(P["FontBook"], P["SizeMain"], "Family tree", x, ty, w, 26, P["TipTitle"], "left")
        ty = self.tree(e, x, ty + 30, w)
        # abilities
        cv.text(P["FontBook"], P["SizeMain"], "Abilities", x, ty + 6, w, 26, P["TipTitle"], "left")
        ay = ty + 38
        for c in e["abilities"] + e["passives"]:
            if c["name"] in ("Melee Attack", "Ranged Attack", "Flying"):
                continue
            icon = self.icons.get(c.get("icon"))
            if icon is not None:
                cv.image(icon, x, ay, 40, 40, preserve=True)
            active = c in e["abilities"]
            cv.text(P["FontMedium"], P["SizeMain"], c["name"] + ("  (active)" if active else ""), x + 52, ay, w - 52, 22, STAGE2 if stage2 and c is e["abilities"][:1] else P["TipTitle"], "left")
            desc = clean(c["description"])
            lines = max(1, len(pm.wrap_plain(cv.fonts[P["FontRegular"]], desc, P["SizeSmall"], w - 52)))
            h = min(4, lines) * P["SizeSmall"] * P["LineSpacing"] + 4
            cv.text(P["FontRegular"], P["SizeSmall"], desc, x + 52, ay + 24, w - 52, h, P["TipBody"], "left", "top", wrap=True)
            ay += 24 + h + 12
            if ay > WIN_H - 120:
                break

    def tree(self, e, x, y, w):
        """Stage II: unit <- two fusions <- four elementals. Stage I: unit <- two elementals."""
        P, cv = self.P, self.cv
        node = 54
        levels = [[e["sid"]], e["parentSids"]]
        if e["stage"] == 2:
            levels.append([g for p in e["parentSids"] for g in self.by_sid[p]["parentSids"]])
        gap = 74
        pos = {}
        for li, level in enumerate(levels):
            n = len(level)
            for i, sid in enumerate(level):
                cx = x + w * (i + 0.5) / n
                pos[(li, i)] = (cx, y + li * gap)
        draw = ImageDraw.Draw(cv.img)
        line = tuple(P["TipNote"])
        for li in range(1, len(levels)):
            for i in range(len(levels[li])):
                px, py = pos[(li - 1, i // 2)]
                cx, cy = pos[(li, i)]
                k = node * self.W["RecruitCardHeight"] / self.W["RecruitCardWidth"]
                draw.line([(cv.ox + px, cv.oy + py + k - 2), (cv.ox + px, cv.oy + py + k + 6), (cv.ox + cx, cv.oy + py + k + 6), (cv.ox + cx, cv.oy + cy + 2)], fill=line, width=2)
        for (li, i), (cx, cy) in pos.items():
            sid = levels[li][i]
            ent = self.by_sid.get(sid)
            is2 = ent is not None and ent["stage"] == 2
            nw = node * (1.15 if li == 0 else 1.0)
            self.thumb(sid, cx - nw / 2, cy, nw)
            label = ent["name"] if ent else pmk_names.get(sid, sid)
            col = STAGE2 if is2 else P["TipTitle"] if ent else P["TipNote"]
            if li == len(levels) - 1 or li == 0:
                pass
            cv.text(P["FontRegular"], 13, label, cx - w / len(levels[li]) / 2 + 60 if False else cx + nw / 2 + 4, cy, w / len(levels[li]) / 2 - nw / 2 - 6, 30, col, "left", wrap=True) if len(levels[li]) <= 2 else \
                cv.text(P["FontRegular"], 12, label, cx - w / 8, cy + nw * 1.2, w / 4, 16, col, "center")
        return y + gap * (len(levels) - 1) + node * 1.6 + (18 if len(levels) == 3 else 0)


pmk_names: dict[str, str] = {}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--glossary", type=Path, default=Path("V:/olden_port_work/elemental_fusion/glossary/glossary.json"))
    ap.add_argument("--out", type=Path, default=Path("V:/olden_port_work/elemental_fusion/glossary/mockup"))
    ap.add_argument("--assets", type=Path, default=Path("V:/olden_port_work/elemental_fusion/mockup_native/assets"))
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    entries = json.loads(a.glossary.read_text(encoding="utf-8"))["entries"]
    by_sid = {e["sid"]: e for e in entries}
    P = pm.layout()
    W = meter.parse_class(WINDOW_CS, "internal static class Homm3DungeonWarCaptivesWindowLayout")
    L = meter.parse_class(PANEL_CS, "internal static class Homm3ConfluxFusionPanelLayout")
    d = pmk.Data()
    for sid in {s for e in entries for s in e["parentSids"]}:
        pmk_names[sid] = d.unit_name(sid)
    pm.SPRITE_FILES = tuple(pm.SPRITE_FILES) + tuple(f for f in ("sharedassets3.assets", "sharedassets6.assets", "sharedassets4.assets") if f not in pm.SPRITE_FILES)
    icon_names = sorted({c["icon"] for e in entries for c in e["abilities"] + e["passives"] if c.get("icon")})
    sprite_names = list(dict.fromkeys(list(W["RecruitSprites"]) + [P["SpritePanelRing"], P["SpriteTierBadge"]] + EXTRA))
    meta = pm.export(a.assets, sprite_names, icon_names)
    spr = {n: Image.open(a.assets / m["file"]).convert("RGBA") for n, m in meta.items() if n in sprite_names}
    icons = {n: Image.open(a.assets / meta[n]["file"]).convert("RGBA") for n in icon_names if n in meta}
    for n in icon_names:  # plugin-provided icons (Homm3CustomUiIconHook serves these from homm3_skill_icons/)
        f = MOD / "homm3_skill_icons" / f"{n}.png"
        if n not in icons and f.is_file():
            icons[n] = Image.open(f).convert("RGBA")
    sep = meta[W["SpriteRecruitSeparator"]]
    half = spr[W["SpriteRecruitSeparator"]].height / 2
    sep["border"] = [sep["border"][0], min(sep["border"][1], half), sep["border"][2], min(sep["border"][3], half)]
    portraits = {p.stem: Image.open(p).convert("RGBA") for p in PORTRAITS.glob("h3_*.png") if re.match(r"h3_(fusion_|\w+_elemental|pixie|firebird)", p.stem)}
    fonts = {f: pm.Font(a.assets, f) for f in pm.FONTS}
    bg = Image.open(pm.MAP_SHOT) if pm.MAP_SHOT.is_file() else Image.new("RGBA", (1920, 1080), (30, 34, 40, 255))
    missing_icons = [n for n in icon_names if n not in icons]

    def canvas():
        cv = pm.Canvas(P, spr, meta, fonts, bg)
        cv.img.alpha_composite(Image.new("RGBA", cv.img.size, (0, 0, 0, int(255 * P["BlockAlpha"]))))
        return cv

    shots = []

    # (a) the fusion panel with the glossary button ("?" database button, mirrored opposite the skill icon)
    cv = pm.Canvas(P, spr, meta, fonts, bg)
    army = [("h3_pixie", 30), ("h3_air_elemental", 40), ("h3_water_elemental", 12), ("h3_fire_elemental", 9), ("h3_earth_elemental", 7), ("h3_psychic_elemental", 6), ("h3_firebird", 2)]
    pmk.Panel(P, W, L, cv, d, portraits, Image.open(SKILL_ICON).convert("RGBA")).render(pmk.State(3, army))
    w = W["RecruitWidth"]
    bx, by = w - L["IconCenterX"] - 8, W["RecruitHeaderHeight"] / 2
    cv.centered("Button_Database_MouseOver", bx, by, 44, 44)
    meter.caption(cv.img, [
        "Fusion panel: new glossary button in the header, opposite the skill icon (the game's own \"?\" database button, hovered; tooltip \"Fusion Glossary\").",
        "Clicking it opens the Fusion Glossary on top of the panel; closing the glossary returns to the panel unchanged.",
    ], size=15).save(a.out / "glossary_a_button.png")
    shots.append("glossary_a_button.png")

    # (b) whole list, sorted by name, a stage II unit selected (family tree with grandparents)
    s2 = sorted((e for e in entries if e["stage"] == 2), key=lambda e: e["name"])[3]
    cv = canvas()
    rows = Glossary(P, W, cv, entries, by_sid, portraits, icons).render("", 0, "name", False, s2["sid"])
    meter.caption(cv.img, [
        f"Fusion Glossary, all {len(entries)} fusions sorted by Name (click any column header to sort; again to reverse). Stage II rows are violet-tinted with a violet name and edge bar.",
        f"Right: the selected fusion ({s2['name']}): stats, its family tree (the two fusions it comes from and their four elementals), and every ability with the game's own text and icon.",
        "Mouse wheel / scrollbar scrolls the list. Ability numbers (#) are filled in game by the unit's own values.",
    ], size=15).save(a.out / "glossary_b_all.png")
    shots.append("glossary_b_all.png")

    # (c) search + sort by HP descending, a stage I unit selected
    q = "storm"
    cv = canvas()
    g = Glossary(P, W, cv, entries, by_sid, portraits, icons)
    hits = sorted((e for e in entries if matches(e, q)), key=lambda e: -e["hp"])
    pick = next(e for e in hits if e["stage"] == 1)
    rows = g.render(q, 0, "hp", True, pick["sid"])
    meter.caption(cv.img, [
        f"Typing filters live: \"{q}\" matches names, parents and ability text ({len(rows)} fusions, stage I and II mixed). Sorted by HP, highest first (arrow on the active column).",
        f"Stage I detail ({pick['name']}): the family tree is just its two elementals. Stage tabs narrow the list to stage I or stage II only.",
    ], size=15).save(a.out / "glossary_c_search.png")
    shots.append("glossary_c_search.png")

    # (d) stage II tab
    cv = canvas()
    s2b = max((e for e in entries if e["stage"] == 2), key=lambda e: e["squadValue"])
    rows = Glossary(P, W, cv, entries, by_sid, portraits, icons).render("", 2, "attack", True, s2b["sid"])
    meter.caption(cv.img, [
        f"Stage II tab: only the {len(rows)} second fusions, sorted by Attack. Selected: {s2b['name']}.",
    ], size=15).save(a.out / "glossary_d_stage2.png")
    shots.append("glossary_d_stage2.png")
    print(f"{len(shots)} mockups -> {a.out}; icons missing from game sprites: {len(missing_icons)} {missing_icons[:8]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
