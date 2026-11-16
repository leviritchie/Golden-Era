"""Render approval mockups of the Factory Logistics Network upgrade panel without launching the game.

The panel opens when a Factory hero with the Logistics Network skill visits an owned mine or creature dwelling
(docs/factory_logistics_network_design.md). Nothing is implemented in the plugin yet, so the layout constants live
here (class Lay) until a Homm3FactoryLogisticsPanelLayout exists to parse.

Sources (nothing else is re-typed here):
  * shell, rows, buttons: the War Captives recruit shell (Homm3DungeonWarCaptivesWindowLayout, the frame the Elemental
    Fusion panel and its glossary reuse) and the glossary's native list plates (tab_1 / tab_selected_1)
  * fonts, sizes, colours: Homm3TowerArtificingPickerLayout (the law-tooltip clone every custom panel uses)
  * numbers and texts: the draft "Proposed numbers" of docs/factory_logistics_network_design.md (2026-11-16) plus the
    coordinator's later effect corrections (Byproduct Processing output bonus, Export Office 2x/3x/4x); placeholders
  * native sprites, resource icons (top-bar Icon_Resource_*), mine icons (mine_*) and placeholder enhancement icons
    (vanilla town-building icons) and SDF fonts: exported read-only from the installed game by
    tools/tower_artificing/picker_mockup.py into the assets cache
  * skill icon: OfflineUnlockMod/homm3_skill_icons/skill_faction_homm3_factory.png; unit card: homm3_portraits/h3_automaton.png
  * background: V:/olden_port_work/run4_s10.png scaled to 1920x1080, dimmed like the panel's Block

    python tools/factory_logistics/upgrade_panel_mockup.py [--out V:/olden_port_work/factory_logistics/mockups]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tools" / "tower_artificing"))
sys.path.insert(0, str(ROOT / "tools" / "dungeon_war_captives"))
import homm3_hero_skill_meter_mockup as meter  # noqa: E402
import picker_mockup as pm  # noqa: E402
import window_mockup as wc  # noqa: E402  (sets pm.FONTS to the 26615913 font ids)

MOD = pm.MOD
SKILL_ICON = MOD / "homm3_skill_icons" / "skill_faction_homm3_factory.png"
PORTRAITS = MOD / "homm3_portraits"
OUT = Path("V:/olden_port_work/factory_logistics/mockups")
ASSETS = OUT / "assets"
EXTRA_FILES = ("sharedassets3.assets", "sharedassets6.assets", "sharedassets4.assets", "sharedassets12.assets", "sharedassets65.assets")

RES = {"gold": "Icon_Resource_Gold", "wood": "Icon_Resource_Wood", "ore": "Icon_Resource_Iron", "crystal": "Icon_Resource_\u0421rystal",
       "mercury": "Icon_Resource_Mercury", "gems": "Icon_Resource_GemStone", "dust": "Icon_Resource_AlchemicalDust"}
# Placeholder enhancement icons: vanilla town-building icons with a related look (to be replaced by real art).
ICONS = {"byproduct": "H_build_Treasury", "export": "H_build_Merchant", "power": "N_build_Resource_Silo", "hub": "H_build_Resource_Depot", "arcane": "U_build_Mage_Guild_Level_3",
         "food": "H_build_Tavern", "housing": "H_build_Main_Level_1", "rail": "U_build_Portal_Summoning", "merc": "H_build_Training_Range"}
MINES = {"crystal": "mine_crystals", "gold": "mine_gold", "gems": "mine_gemstones"}
EXTRA = ["tab_1", "tab_selected_1", "Button_Tab_Dark", "Button_Tab_Dark_Selected", "Button_Tab_Dark_MouseOver", "Frame_LawLevel (1)", "Icon_Scroll_LevelLock",
         "Overlay_Law_NotOpen", "Frame_Law_Top", "U_build_Mage_Guild_Level_3", "FullSkreanExitButton", "button_plus", "button_minus"]
SPRITES = EXTRA + list(RES.values()) + list(ICONS.values()) + list(MINES.values())
RANKS = {1: "Basic", 2: "Advanced", 3: "Expert"}


class Lay:
    """Panel geometry (window space, 1920x1080 reference)."""
    Width = 1240.0
    IconCenterX = 58.0       # skill icon in the header (as the fusion panel)
    IconRing = 58.0
    IconSize = 42.0
    InfoTop = 60.0
    InfoHeight = 74.0
    BuildingIcon = 66.0
    Pad = 30.0
    RowsTop = 146.0
    RowHeight = 112.0
    RowExtra = 26.0          # an extra line (Material Synthesizer multiplier)
    RowGap = 8.0
    NoteHeight = 34.0
    CellCenterX = 92.0
    CellBack = 74.0
    CellIcon = 64.0
    NameX = 142.0
    NameWidth = 236.0
    StateWidth = 116.0       # "Built: level 2", then the Active badge / Set active toggle
    ToggleWidth = 104.0
    LevelX = 392.0
    BadgeSize = 26.0
    LevelTextX = 426.0
    LevelTextWidth = 380.0
    LockX = 812.0
    LockWidth = 120.0
    LevelTop = 12.0
    LevelPitch = 28.0
    CostX = 948.0
    CostWidth = 262.0
    CostIcon = 28.0
    StatusGap = 10.0
    StatusHeight = 28.0
    ButtonAreaHeight = 92.0
    HighlightTint = (214, 188, 124, 46)
    LockedTint = (120, 120, 120, 255)


def n0(v) -> str:
    return f"{int(v):,}"


# ----------------------------------------------------------------------------------------- canvas with overflow check
class FitCanvas(pm.Canvas):
    """pm.Canvas that records any single-line text wider than its box (and wrapped text that would be truncated)."""

    problems: list = []

    def text(self, font, size, text, x, y, w, h, color, align="left", valign="middle", wrap=False, screen=False):
        f = self.fonts[font]
        if wrap:
            lines = pm.wrap_plain(f, text, size, w)
            k = size / f.f["pointSize"] * f.f["scale"]
            max_lines = max(1, int((h - f.f["cap"] * k) // (size * self.L["LineSpacing"])) + 1)
            if len(lines) > max_lines:
                FitCanvas.problems.append(f"wrapped text truncated ({len(lines)}>{max_lines} lines): {text!r}")
        else:
            for line in text.split("\n"):
                if f.advance(line, size) > w + 0.5:
                    FitCanvas.problems.append(f"overflow {f.advance(line, size):.0f}>{w:.0f}: {line!r}")
        if f.missing:
            FitCanvas.problems.append(f"missing glyphs {sorted(f.missing)} in {text!r}")
            f.missing.clear()
        super().text(font, size, text, x, y, w, h, color, align, valign, wrap, screen)


def rect(cv, x, y, w, h, color):
    """Plain translucent rectangle in window space (highlight bars)."""
    X, Y, W_, H_ = cv.rect(x, y, w, h)
    cv.img.alpha_composite(Image.new("RGBA", (max(1, round(W_)), max(1, round(H_))), color), (round(X), round(Y)))


def shell(P, W, cv, w, h, title, icon):
    """Native recruit shell (the fusion panel's frame), sized w x h, centred."""
    cv.ox, cv.oy = P["ReferenceWidth"] / 2 - w / 2, P["ReferenceHeight"] / 2 - h / 2

    def flip(name, x, y, ww, hh, fx, fy):
        im = cv.spr[name]
        im = im.transpose(Image.FLIP_LEFT_RIGHT) if fx else im
        im = im.transpose(Image.FLIP_TOP_BOTTOM) if fy else im
        cv.image(im, x, y, ww, hh)

    cv.sprite(W["SpriteRecruitBack"], 0, 0, w, h)
    cv.sliced(W["SpriteRecruitGradient"], 0, 0, w, h, 1.0)
    bw = w - 2 * W["RecruitFrameInset"]
    cv.sprite(W["SpriteRecruitLightBack"], (w - bw) / 2, W["RecruitHeaderHeight"] / 2, bw, W["RecruitTopBandHeight"])
    cv.sprite(W["SpriteRecruitLightBack"], (w - bw) / 2, h - W["RecruitBottomBandHeight"] - W["RecruitFrameInset"], bw, W["RecruitBottomBandHeight"])
    cv.sliced(W["SpriteRecruitBackFrame"], 0, 0, w, h, 1.0)
    cv.sliced(W["SpriteRecruitFrame"], 0, 0, w, h, 1.0)
    c = W["RecruitCorner"]
    flip(W["SpriteRecruitCorner"], 0, 0, c, c, False, False)
    flip(W["SpriteRecruitCorner"], w - c, 0, c, c, True, False)
    flip(W["SpriteRecruitCorner"], 0, h - c, c, c, False, True)
    flip(W["SpriteRecruitCorner"], w - c, h - c, c, c, True, True)
    cv.centered(W["SpriteRecruitDecorFooter"], w / 2, h - W["RecruitDecorFooterHeight"] / 2, W["RecruitDecorFooterWidth"], W["RecruitDecorFooterHeight"])
    ov = W["RecruitHeaderOverhang"]
    cv.sliced(W["SpriteRecruitHeader"], -ov / 2, 0, w + ov, W["RecruitHeaderHeight"], 1.0)
    hy = W["RecruitHeaderHeight"] / 2
    ow, oh, ox = W["RecruitOrnamentWidth"], W["RecruitOrnamentHeight"], W["RecruitOrnamentX"]
    flip(W["SpriteRecruitHeaderOrnament"], w / 2 + ox - ow / 2, hy - oh / 2, ow, oh, False, False)
    flip(W["SpriteRecruitHeaderOrnament"], w / 2 - ox - ow / 2, hy - oh / 2, ow, oh, True, False)
    mw, mh, mx = W["RecruitMetalWidth"], W["RecruitMetalHeight"], W["RecruitMetalX"]
    flip(W["SpriteRecruitHeaderMetal"], w / 2 + mx - mw / 2, hy - mh / 2, mw, mh, False, False)
    flip(W["SpriteRecruitHeaderMetal"], w / 2 - mx - mw / 2, hy - mh / 2, mw, mh, True, False)
    cv.centered(W["SpriteRecruitDecorHeader"], w / 2, W["RecruitDecorHeaderHeight"] / 2 - W["RecruitFrameInset"], W["RecruitDecorHeaderWidth"], W["RecruitDecorHeaderHeight"])
    cv.text(P["FontBook"], P["SizeSubHeader"], title, w / 2 - W["RecruitTitleWidth"] / 2, 0, W["RecruitTitleWidth"], W["RecruitHeaderHeight"], P["TipTitle"], "center")
    if icon is not None:
        cv.image(icon, Lay.IconCenterX - Lay.IconSize / 2, hy - Lay.IconSize / 2, Lay.IconSize, Lay.IconSize, preserve=True)
        cv.centered(P["SpritePanelRing"], Lay.IconCenterX, hy, Lay.IconRing, Lay.IconRing)


def button(P, W, cv, label, x, y, bw, enabled=True, hover=False, green=False):
    """Mirror of the fusion panel's AddButton (button_gray base + sliced plate)."""
    bh = W["RecruitButtonHeight"]
    cv.sprite(W["SpriteRecruitButtonBase"], x, y, bw, bh)
    if not enabled:
        name = W["SpriteRecruitButtonDisabled"]
    elif green:
        name = W["SpriteRecruitButtonGreenHover"] if hover else W["SpriteRecruitButtonGreen"]
    else:
        name = W["SpriteRecruitButtonHover"] if hover else W["SpriteRecruitButton"]
    cv.sliced(name, x, y, bw, bh, W["RecruitButtonSliceMultiplier"])
    cv.text(P["FontBook"], P["SizeSubHeader"], label, x, y, bw, bh, P["ButtonText"] if enabled else P["ButtonTextDisabled"], "center")


def cost_width(cv, P, cost, size):
    f = cv.fonts[P["FontMedium"]]
    return sum(Lay.CostIcon + 4 + f.advance(n0(a), size) + 12 for _, a in cost) - 12


def draw_cost(cv, P, cost, x, cy, color, size=None, align="left", width=None):
    """Resource icons + amounts in one row (as the native town-building cost line)."""
    size = size or P["SizeMain"]
    f = cv.fonts[P["FontMedium"]]
    total = cost_width(cv, P, cost, size)
    if width is not None and total > width:
        FitCanvas.problems.append(f"cost row {total:.0f}>{width:.0f}: {cost}")
    if align == "right" and width is not None:
        x = x + width - total
    for res, amt in cost:
        cv.sprite(RES[res], x, cy - Lay.CostIcon / 2, Lay.CostIcon, Lay.CostIcon, preserve=True)
        x += Lay.CostIcon + 4
        tw = f.advance(n0(amt), size)
        cv.text(P["FontMedium"], size, n0(amt), x, cy - 13, tw + 2, 26, color)
        x += tw + 12


# ----------------------------------------------------------------------------------------- data (draft numbers)
def mine_options(resource, rare, daily, sell_each):
    """Draft mine enhancements (design doc 'Proposed numbers' + coordinator corrections). rare = the L2/L3 resource."""
    res_name = resource
    ex = [2 * daily * sell_each, 3 * daily * sell_each, 4 * daily * sell_each]
    return {
        "byproduct": dict(name="Byproduct Processing", icon="byproduct", sub="Extra output pooled, rounded down",
                          levels=["+100 gold per day", f"+200 gold, +50% {res_name} per day", f"+350 gold, +100% {res_name} per day"],
                          costs=[[("gold", 1000), ("wood", 3), ("ore", 3)], [("gold", 1500), (rare, 2)], [("gold", 2000), (rare, 4)]]),
        "export": dict(name="Export Office", icon="export", sub=f"Sells the {res_name} instead", conversion=True,
                       levels=[f"{n0(ex[0])} gold per day (2x sell value)", f"{n0(ex[1])} gold per day (3x)", f"{n0(ex[2])} gold per day (4x)"],
                       at_level=lambda lv: f"{lv + 1}x, {n0((lv + 1) * daily * sell_each)} gold per day",
                       costs=[[("gold", 1000), ("wood", 5)], [("gold", 1500), (rare, 2)], [("gold", 2500), (rare, 3)]]),
        "power": dict(name="Power Station", icon="power", sub=f"{res_name.capitalize()} now powers the network",
                      levels=["+1 level to enhanced buildings in range", "+2 levels to enhanced buildings in range", "+3 levels to enhanced buildings in range"],
                      costs=[[("gold", 2500), ("wood", 5), ("ore", 5)], [("gold", 3500), ("mercury", 4)], [("gold", 5000), ("mercury", 6)]]),
        "arcane": dict(name="Arcane Manufactory", icon="arcane", sub=f"{res_name.capitalize()} now feeds the network",
                       levels=["+1 hero stats in range, 1/6 units upgraded", "+2 hero stats in range, 2/6 units upgraded", "+3 hero stats in range, 3/6 units upgraded"],
                       costs=[[("gold", 3000), ("wood", 5), ("ore", 5)], [("gold", 4000), ("crystal", 4)], [("gold", 6000), ("crystal", 6)]]),
        "hub": dict(name="Logistics Hub", icon="hub", sub="Building works as before",
                    levels=["Routes through refresh 33% range", "Routes through refresh 66% range", "Routes through refresh 100% range"],
                    costs=[[("gold", 1000), ("wood", 3), ("ore", 3)], [("gold", 1500), (rare, 2)], [("gold", 2500), (rare, 3)]]),
    }


def dwelling_options(unit, weekly, price, D_costs, rare, b, q):
    """Draft dwelling enhancements for one unit (D-scaled gold, rounded to 250; b wood/ore at L1, q / 2q rare after)."""
    g = D_costs
    return {
        "food": dict(name="Food Distribution Center", icon="food", sub="More units each week",
                     levels=[f"+{round(weekly / 3)} {unit}s per week (+33%)", f"+{round(weekly * 2 / 3)} per week (+66%)", f"+{weekly} per week (+100%), hire now"],
                     costs=[[("gold", g["food"][0]), ("wood", b), ("ore", b)], [("gold", g["food"][1]), (rare, q)], [("gold", g["food"][2]), (rare, 2 * q)]]),
        "housing": dict(name="Housing Office", icon="housing", sub="Cheaper hiring here",
                        levels=[f"{unit}s cost {n0(price * 0.8)} gold (-20%)", f"{unit}s cost {n0(price * 0.6)} gold (-40%)", f"{unit}s cost {n0(price * 0.4)} gold (-60%)"],
                        costs=[[("gold", g["housing"][0]), ("wood", b), ("ore", b)], [("gold", g["housing"][1]), (rare, q)], [("gold", g["housing"][2]), (rare, 2 * q)]]),
        "rail": dict(name="Rail Network", icon="rail", sub="Hire from anywhere",
                     levels=["Hire remotely to a town in range", "Same, +1 range level for this dwelling's routes", "Delivers to a town or hero; +2 range level for this dwelling's routes"],
                     costs=[[("gold", g["rail"][0]), ("wood", b), ("ore", b)], [("gold", g["rail"][1]), (rare, q)], [("gold", g["rail"][2]), (rare, 2 * q)]]),
        "merc": dict(name="Mercenary Headquarters", icon="merc", sub="Gold instead of units", conversion=True,
                     at_level=lambda lv: f"{lv}x, {n0(weekly * price * lv)} gold per week",
                     levels=[f"No units; {n0(weekly * price)} gold per week (1x)", f"No units; {n0(weekly * price * 2)} gold per week (2x)",
                             f"No units; {n0(weekly * price * 3)} gold per week (3x)"],
                     costs=[[("gold", g["merc"][0]), ("wood", b), ("ore", b)], [("gold", g["merc"][1]), (rare, q)], [("gold", g["merc"][2]), (rare, 2 * q)]]),
        "hub": dict(name="Logistics Hub", icon="hub", sub="Dwelling works as before",
                    levels=["Routes through refresh 33% range", "Routes through refresh 66% range", "Routes through refresh 100% range"],
                    costs=[[("gold", 1000), ("wood", 3), ("ore", 3)], [("gold", 1500), (rare, 2)], [("gold", 2500), (rare, 3)]]),
    }


class Building:
    def __init__(self, name, sub, icon=None, portrait=None, options=(), built=None, active=None, note=None, synth=None, power=None):
        self.name, self.sub, self.icon, self.portrait = name, sub, icon, portrait
        self.options = list(options)    # option dicts in display order
        self.built = dict(built or {})  # key -> built level (any number of enhancements may be built)
        self.active = active            # the one built enhancement that works
        self.note = note                # one-line note under the info strip
        self.synth = synth              # (multiplier, source) of a Material Synthesizer in range
        self.power = power              # extra effective levels from Power Stations in range (applies to the built enhancement)


# ----------------------------------------------------------------------------------------- render
class Panel:
    def __init__(self, P, W, cv, icons, skill_icon, portraits):
        self.P, self.W, self.cv, self.icons, self.skill_icon, self.portraits = P, W, cv, icons, skill_icon, portraits

    @staticmethod
    def extras(b, o):
        """Extra lines under an option's levels: Material Synthesizer on conversion entries, Power Station on the built one."""
        out = []
        if b.synth and o.get("conversion"):
            out.append(f"x{b.synth[0]:g} from Material Synthesizer ({b.synth[1]})")
        if b.power and b.active == o["key"] and o.get("at_level"):
            n = b.power
            out.append(f"+{n} level{'s' if n > 1 else ''} from Power Station: {o['at_level'](b.built[o['key']] + n)}")
        return out

    def row_height(self, b, o):
        return Lay.RowHeight + Lay.RowExtra * len(self.extras(b, o))

    def render(self, b: Building, hero, rank, network, selected, hover=None, status=None, status_color=None, buttons=()):
        P, W, cv = self.P, self.W, self.cv
        cv.img.alpha_composite(Image.new("RGBA", cv.img.size, (0, 0, 0, int(255 * P["BlockAlpha"]))))
        rows_h = sum(self.row_height(b, o) + Lay.RowGap for o in b.options)
        top = Lay.RowsTop + (Lay.NoteHeight if b.note else 0)
        h = top + rows_h + Lay.StatusGap + Lay.StatusHeight + Lay.ButtonAreaHeight
        w = Lay.Width
        shell(P, W, cv, w, h, "Logistics Network", self.skill_icon)

        # Info strip: building, its output, the hero and the network.
        iy = Lay.InfoTop
        icx, icy = Lay.Pad + Lay.BuildingIcon / 2 + 6, iy + Lay.InfoHeight / 2
        if b.portrait is not None:
            self.card(b.portrait, icx, icy, Lay.BuildingIcon + 6)
        else:
            cv.centered("Overlay_Law_NotOpen", icx, icy, Lay.BuildingIcon + 4, Lay.BuildingIcon + 4)
            cv.sprite(b.icon, icx - Lay.BuildingIcon / 2 + 5, icy - Lay.BuildingIcon / 2 + 5, Lay.BuildingIcon - 10, Lay.BuildingIcon - 10, preserve=True)
            cv.centered("Frame_Law_Top", icx, icy, Lay.BuildingIcon + 8, Lay.BuildingIcon + 8)
        tx = Lay.Pad + Lay.BuildingIcon + 26
        cv.text(P["FontBook"], P["SizeHeaderBig"], b.name, tx, iy + 6, 420, 32, P["TipTitle"])
        cv.text(P["FontMedium"], P["SizeSmall"], b.sub, tx, iy + 40, 420, 24, P["TipNote"])
        rx, rw = w / 2, w / 2 - Lay.Pad
        cv.text(P["FontMedium"], P["SizeMain"], network, rx, iy + 0, rw, 28, P["TipBody"], "right")
        cv.text(P["FontMedium"], P["SizeSmall"], f"{hero}: {RANKS[rank]} Logistics Network (builds up to level {rank})", rx, iy + 28, rw, 24, P["TipNote"], "right")
        # Every visit by a skilled hero marks this building's own Upgrade Center at the hero's skill level.
        cv.text(P["FontMedium"], P["SizeSmall"], f"Upgrade Center: level {rank} (set by {hero}'s visit)", rx, iy + 52, rw, 24, P["TipTitle"], "right")
        y = Lay.RowsTop
        if b.note:
            cv.text(P["FontMedium"], P["SizeSmall"], b.note, Lay.Pad, y - 6, w - 2 * Lay.Pad, Lay.NoteHeight, P["TipWarn"], "center")
            y += Lay.NoteHeight

        for o in b.options:
            rh = self.row_height(b, o)
            self.row(b, o, rank, Lay.Pad, y, w - 2 * Lay.Pad, rh, o["key"] == selected, hover == o["key"])
            y += rh + Lay.RowGap

        # Status line + buttons.
        y += Lay.StatusGap
        if status:
            cv.text(P["FontMedium"], P["SizeSmall"], status, W["RecruitTextInset"], y, w - 2 * W["RecruitTextInset"], Lay.StatusHeight, status_color or P["TipNote"], "center")
        by_c = h - Lay.ButtonAreaHeight / 2 - 4
        cv.sliced(W["SpriteRecruitSeparator"], (w - W["RecruitSeparatorWidth"]) / 2, by_c - W["RecruitSeparatorHeight"] / 2 - 4, W["RecruitSeparatorWidth"], W["RecruitSeparatorHeight"], 1.0)
        bw, gap = W["RecruitButtonWidth"], W["RecruitButtonGap"]
        bx = (w - len(buttons) * bw - (len(buttons) - 1) * gap) / 2
        for i, (label, enabled, kind) in enumerate(buttons):
            button(P, W, cv, label, bx + i * (bw + gap), by_c - W["RecruitButtonHeight"] / 2, bw, enabled, hover == ("button", label), kind == "green")
        return h

    def card(self, portrait, cx, cy, size):
        W, cv = self.W, self.cv
        k = size / W["RecruitCardHeight"]
        cw, ch = W["RecruitCardWidth"] * k, W["RecruitCardHeight"] * k
        cv.centered(W["SpriteRecruitCard"], cx, cy, cw, ch)
        pw, ph = W["RecruitPortraitWidth"] * k, W["RecruitPortraitHeight"] * k
        im = portrait
        s = max(pw / im.width, ph / im.height)
        big = im.resize((max(1, round(im.width * s * 2)), max(1, round(im.height * s * 2))), Image.LANCZOS)
        ox, oy = (big.width - round(pw * 2)) // 2, (big.height - round(ph * 2)) // 2
        crop = big.crop((ox, oy, ox + round(pw * 2), oy + round(ph * 2)))
        mask = cv.spr[W["SpriteRecruitPortraitMask"]].resize(crop.size, Image.LANCZOS).getchannel("A")
        crop.putalpha(Image.composite(crop.getchannel("A"), Image.new("L", crop.size, 0), mask))
        cv.image(crop, cx - pw / 2, cy - ph / 2, pw, ph)

    def row(self, b, o, rank, x, y, w, h, selected, hover):
        P, cv = self.P, self.cv
        built_lvl = b.built.get(o["key"], 0)
        is_built = built_lvl > 0
        active = b.active == o["key"]
        cv.sliced("tab_selected_1" if selected or hover == o["key"] else "tab_1", x, y, w, h, 1.0)
        if selected:
            rect(cv, x, y, 4, h, P["TipTitle"])
        cy = y + Lay.RowHeight / 2
        # icon cell (law cell sprites, as the Artificing picker)
        cv.centered("Overlay_Law_NotOpen", Lay.CellCenterX, cy, Lay.CellBack, Lay.CellBack)
        cv.sprite(ICONS[o["icon"]], Lay.CellCenterX - Lay.CellIcon / 2, cy - Lay.CellIcon / 2, Lay.CellIcon, Lay.CellIcon, preserve=True)
        cv.centered("Frame_Law_Top", Lay.CellCenterX, cy, Lay.CellBack + 6, Lay.CellBack + 6)
        dis = P["ButtonTextDisabled"]
        cv.text(P["FontBook"], P["SizeSubHeader"], o["name"], Lay.NameX, cy - 38, Lay.NameWidth, 28, P["TipTitle"] if selected else P["ButtonText"])
        if is_built:
            cv.text(P["FontMedium"], P["SizeSmall"], f"Built: level {built_lvl}", Lay.NameX, cy - 8, Lay.StateWidth, 26, P["CostOk"] if active else P["TipBody"])
            tx = Lay.NameX + Lay.StateWidth
            if active:
                cv.sliced("buttom_green", tx, cy - 8, Lay.ToggleWidth, 26, 3.0)
                cv.text(P["FontMedium"], P["SizeSmall"], "Active", tx, cy - 8, Lay.ToggleWidth, 26, P["ButtonText"], "center")
            else:
                hov = hover == ("toggle", o["key"])
                cv.sprite("Button_Tab_Dark_MouseOver" if hov else "Button_Tab_Dark", tx, cy - 8, Lay.ToggleWidth, 26)
                cv.text(P["FontMedium"], P["SizeSmall"], "Set active", tx, cy - 8, Lay.ToggleWidth, 26, P["ButtonText"], "center")
        else:
            cv.text(P["FontMedium"], P["SizeSmall"], "Not built", Lay.NameX, cy - 8, Lay.NameWidth, 26, P["TipNote"])
        cv.text(P["FontMedium"], P["SizeSmall"], o["sub"], Lay.NameX, cy + 20, Lay.NameWidth, 22, P["TipNote"])

        # level lines
        for i, line in enumerate(o["levels"]):
            lvl = i + 1
            ly = y + Lay.LevelTop + i * Lay.LevelPitch
            reach = lvl <= rank
            done = lvl <= built_lvl
            if reach and not done:
                rect(cv, Lay.LevelX - 6, ly, Lay.LockX - Lay.LevelX + Lay.LockWidth - 6, Lay.LevelPitch - 4, Lay.HighlightTint)
            col = (P["CostOk"] if active else P["TipBody"]) if done else P["TipBody"] if reach else dis
            cv.centered("Frame_LawLevel (1)", Lay.LevelX + Lay.BadgeSize / 2, ly + (Lay.LevelPitch - 4) / 2, Lay.BadgeSize, Lay.BadgeSize, None if reach or done else Lay.LockedTint)
            cv.text(P["FontBook"], P["SizeSmall"], str(lvl), Lay.LevelX, ly, Lay.BadgeSize, Lay.LevelPitch - 4, P["Ink"], "center")
            tag = "Built" if done else None if reach else f"Requires {RANKS[lvl]}"
            # untagged lines may run into the (empty) tag column
            tw_ = Lay.LevelTextWidth + (0 if tag else Lay.LockWidth - 12)
            cv.text(P["FontMedium"], P["SizeSmall"], line, Lay.LevelTextX, ly, tw_, Lay.LevelPitch - 4, col)
            if tag:
                cv.text(P["FontMedium"], P["SizeSmall"], tag, Lay.LockX, ly, Lay.LockWidth - 12, Lay.LevelPitch - 4,
                        (P["CostOk"] if active else P["TipNote"]) if done else P["TipWarn"], "right")
        for j, extra in enumerate(self.extras(b, o)):
            ly = y + Lay.LevelTop + (3 + j) * Lay.LevelPitch
            cv.text(P["FontMedium"], P["SizeSmall"], extra, Lay.LevelTextX, ly, Lay.LevelTextWidth + Lay.LockWidth, Lay.LevelPitch - 4, P["TipTitle"])

        # cost column: the next step this hero can take
        cx0, cw = Lay.CostX, Lay.CostWidth
        nxt = built_lvl + 1
        if nxt > 3:
            cv.text(P["FontMedium"], P["SizeSmall"], "Fully upgraded", cx0, cy - 12, cw, 24, P["CostOk"], "center")
            return
        if nxt > rank:
            cv.text(P["FontMedium"], P["SizeSmall"], f"Level {nxt} requires {RANKS[nxt]}", cx0, cy - 12, cw, 24, P["TipWarn"], "center")
            return
        label = f"Upgrade to level {nxt}" if is_built else "Build: level 1"
        cv.text(P["FontMedium"], P["SizeSmall"], label, cx0, cy - 34, cw, 22, P["TipNote"], "center")
        cost = o["costs"][nxt - 1]
        tw = cost_width(cv, P, cost, P["SizeMain"])
        draw_cost(cv, P, cost, cx0 + (cw - tw) / 2, cy + 6, P["TipBody"], width=cw)


def with_dust(opts):
    """Every enhancement costs +10 dust at level 2 and +20 dust at level 3 on top of its normal cost."""
    for k, o in opts.items():
        o["key"] = k
        o["costs"] = [o["costs"][0], o["costs"][1] + [("dust", 10)], o["costs"][2] + [("dust", 20)]]
    return opts


# ----------------------------------------------------------------------------------------- setup + shots
def load(assets: Path):
    P = pm.layout()
    W = meter.parse_class(wc.WINDOW_CS, "internal static class Homm3DungeonWarCaptivesWindowLayout")
    pm.SPRITE_FILES = tuple(pm.SPRITE_FILES) + tuple(f for f in EXTRA_FILES if f not in pm.SPRITE_FILES)
    names = list(dict.fromkeys(list(W["RecruitSprites"]) + [P["SpritePanelRing"]] + SPRITES))
    meta = pm.export(assets, names, [])
    spr = {n: Image.open(assets / m["file"]).convert("RGBA") for n, m in meta.items() if n in names}
    sep = meta[W["SpriteRecruitSeparator"]]
    half = spr[W["SpriteRecruitSeparator"]].height / 2
    sep["border"] = [sep["border"][0], min(sep["border"][1], half), sep["border"][2], min(sep["border"][3], half)]
    fonts = {f: pm.Font(assets, f) for f in pm.FONTS}
    bg = Image.open(pm.MAP_SHOT) if pm.MAP_SHOT.is_file() else Image.new("RGBA", (1920, 1080), (30, 34, 40, 255))
    return P, W, spr, meta, fonts, bg


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--assets", type=Path, default=ASSETS, help="native sprite/font export cache (re-exported from the installed game when missing)")
    args = ap.parse_args()
    out: Path = args.out
    out.mkdir(parents=True, exist_ok=True)
    P, W, spr, meta, fonts, bg = load(args.assets)
    skill_icon = Image.open(SKILL_ICON).convert("RGBA")
    automaton = Image.open(PORTRAITS / "h3_automaton.png").convert("RGBA")
    hero = "Henrietta"
    network = "Network: 6 buildings \u00b7 logistics level 2 \u00b7 range 200 MP"
    shots = []

    def shot(fname, b, rank, selected, lines, **kw):
        FitCanvas.problems = []
        cv = FitCanvas(P, spr, meta, fonts, bg)
        Panel(P, W, cv, spr, skill_icon, {}).render(b, hero, rank, network, selected, **kw)
        if FitCanvas.problems:
            raise SystemExit(f"{fname}: text does not fit:\n  " + "\n  ".join(FitCanvas.problems))
        meter.caption(cv.img, lines, size=15).save(out / fname)
        shots.append(fname)

    # Crystal mine: 1 crystal/day; one town market sells a rare for 500/4 = 125 gold. L2/L3 resource: mercury.
    crystal = with_dust(mine_options("crystal", "mercury", 1, 125))
    crystal_opts = [crystal[k] for k in ("byproduct", "export", "power", "hub")]

    a = Building("Crystal Mine", "+1 crystal per day \u00b7 owned by you", icon=MINES["crystal"], options=crystal_opts)
    pw = crystal["power"]
    shot("upgrade_a_crystal_mine_new.png", a, 2, "power", [
        "LOGISTICS NETWORK upgrade panel (1920x1080 reference): a Factory hero with the skill (Advanced) visits an owned Crystal Mine with no enhancement. Native recruit shell, glossary list plates, law-cell icons.",
        "Each row: placeholder icon (vanilla town-building art), effect per level; levels the hero can reach are lit, higher ones greyed 'Requires Expert'. Right: the next step's cost (top-bar resource icons).",
        "Power Station is selected; Build makes level 1 and works immediately (active at once: nothing else is active, so it is not a switch). Upgrade steps one level per click, also immediate. L2/L3 +10/+20 dust.",
    ], hover=("button", "Build"), status="Power Station: crystal stops being granted daily; enhanced buildings in range gain +1 level instead.",
       buttons=[("Close", True, ""), ("Build", True, "")])

    b = Building("Crystal Mine", "No daily crystal (Power Station active) · owned by you", icon=MINES["crystal"], options=crystal_opts,
                 built={"power": 1, "byproduct": 2}, active="power")
    shot("upgrade_b_crystal_mine_built.png", b, 2, "power", [
        "Same mine later: Power Station level 1 is the active enhancement (green, 'Active'); Byproduct Processing level 2 is also built but inactive ('Set active' switches to it from the next day).",
        "A building can hold any number of enhancements, one active at a time; Export Office and Logistics Hub can still be built without demolishing anything. Building and upgrading need the hero",
        "on site and apply immediately; switching the active one (once per building per week) applies at the start of the next day and also works remotely from the network viewer. Demolish is free, no refund.",
    ], status="Only the active enhancement works. 1 switch left this week; a switch applies next day. Builds and upgrades apply now.",
       buttons=[("Demolish", True, ""), ("Close", True, ""), ("Upgrade to L2", True, "")])

    # T4 dwelling (Automaton Factory, Factory T4): 6 per week, 350 gold each; D = 3500, b = 4 wood/ore, q = 3 gems.
    D = 3500

    def r250(v):
        return int((v + 125) // 250 * 250)

    gold = {k: [r250(m * D) for m in ms] for k, ms in {"food": (.25, .30, .45), "housing": (.20, .25, .35), "rail": (.20, .25, .45), "merc": (.25, .35, .50)}.items()}
    dw = with_dust(dwelling_options("Automaton", 6, 350, gold, "gems", 4, 3))
    c = Building("Automaton Factory", "Tier 4 dwelling \u00b7 +6 Automatons per week \u00b7 owned by you", portrait=automaton,
                 options=[dw[k] for k in ("food", "housing", "rail", "merc", "hub")], synth=(2, "Mercury Mine, level 3, in range"))
    shot("upgrade_c_t4_dwelling.png", c, 3, "merc", [
        "A tier 4 creature dwelling (Automaton Factory, 6 per week, 350 gold each) visited by an Expert hero: all three levels are reachable. Dwelling costs follow the unit's town dwelling (D = 3,500 gold,",
        "4 wood/ore at L1, then 3/6 gems). Mercenary Headquarters is a conversion entry, so with a level 3 Material Synthesizer in range it shows the x2 multiplier line under its levels.",
    ], hover=("button", "Build"), status="Mercenary Headquarters: no new Automatons each week; their purchase value is paid in gold instead (x2 here).",
       buttons=[("Close", True, ""), ("Build", True, "")])

    # Gems mine, Export Office L3 built, a level 3 Power Station in range: 4x + 3 levels = 7x (gems sell for 125 at one market).
    gems = with_dust(mine_options("gems", "crystal", 1, 125))
    e = Building("Gem Pond", "No daily gems (Export Office) · owned by you", icon=MINES["gems"],
                 options=[gems[k] for k in ("byproduct", "export", "arcane", "hub")], built={"export": 3, "arcane": 1}, active="export", power=3)
    shot("upgrade_e_gem_mine_powered.png", e, 3, "export", [
        "Power Station in range: a Gem Pond with Export Office level 3 (4x) inside a level 3 Power Station's range gets +3 effective levels, extending the per-level step to 7x;",
        "the line under the active enhancement says so. Arcane Manufactory level 1 is built but inactive. Export Office is fully upgraded, so Demolish and Close remain for it.",
    ], buttons=[("Demolish", True, ""), ("Close", True, "")])

    gm = with_dust({"hub": mine_options("gold", "crystal", 1, 0)["hub"]})["hub"]
    d = Building("Gold Mine", "+1,000 gold per day \u00b7 owned by you", icon=MINES["gold"], options=[gm], built={"hub": 1}, active="hub",
                 note="Gold mines join the network and receive its bonuses, but only a Logistics Hub can be built here.")
    shot("upgrade_d_gold_mine.png", d, 2, "hub", [
        "A gold mine: it is a network member (it receives the network's bonuses) but the only enhancement offered is the Logistics Hub; the one-line note says why. Its hub is built (level 1),",
        "and Henrietta's visit marks this mine's Upgrade Center at her skill level (2), as on every visited building: its own enhancements can then be built or upgraded from the network viewer up to",
        "level 2, at the same cost, active at the start of the next day. The marker is per building, rises with a higher-skilled visit and is lost when the building is captured. L2-3 use crystal.",
    ], status="From the network viewer this mine's hub can now be upgraded remotely up to level 2, active the next day.",
       buttons=[("Close", True, ""), ("Upgrade to L2", True, "")])
    print(f"{len(shots)} mockups -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
