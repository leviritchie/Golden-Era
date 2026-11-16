"""Render approval mockups of the HoMM3 Dungeon War Captives choice window without launching the game.

Single sources of truth (nothing is re-typed here):
  * window geometry: Homm3DungeonWarCaptivesWindowLayout in
    Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/Homm3DungeonWarCaptivesWindow.cs
  * sprites, fonts, sizes, colours: Homm3TowerArtificingPickerLayout (the law-tooltip clone the window reuses)
  * numbers: the constants of Homm3DungeonCaptivesRuntime.cs; texts: Python mirrors of the window's row builders
  * native sprites and SDF fonts: exported read-only from the installed game by tools/tower_artificing/picker_mockup.py
  * skill icon: OfflineUnlockMod/homm3_skill_icons/skill_faction_homm3_dungeon.png
  * background: V:/olden_port_work/run4_s10.png scaled to 1920x1080, dimmed like the window's Block

    python tools/dungeon_war_captives/window_mockup.py [--out V:/tmp/dungeon_war_captives_window]
"""
from __future__ import annotations

import argparse
import math
import re
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tools" / "tower_artificing"))
import homm3_hero_skill_meter_mockup as meter  # noqa: E402
import picker_mockup as pm  # noqa: E402

MOD = pm.MOD
WINDOW_CS = MOD / "Homm3DungeonWarCaptivesWindow.cs"
RUNTIME_CS = MOD / "Homm3DungeonCaptivesRuntime.cs"
SKILL_ICON = MOD / "homm3_skill_icons" / "skill_faction_homm3_dungeon.png"
# resources.assets path ids of the EN SDF fonts (MonoBehaviour, atlas Texture2D) in Steam build 26615913; picker_mockup.FONTS
# still lists the pre-26615913 ids.
PORTRAITS = {"Infernal Troglodyte": "h3_troglodyte_upg", "Harpy Hag": "h3_harpy_upg", "Beholder": "h3_beholder", "Minotaur": "h3_minotaur",
             "Halberdier": "h3_pikeman_upg", "Crusader": "h3_swordsman_upg", "Marksman": "h3_archer_upg"}
pm.FONTS = {"EN-Regular": (581225, 11432), "EN-Medium": (581224, (11448, 11449)), "EN-Book": (581222, 4967)}


def runtime_constants() -> dict:
    text = RUNTIME_CS.read_text(encoding="utf-8")
    out = {}
    for name in ("ExecuteXpPerCaptive", "RansomGoldPerCaptive", "EatPercent", "RecruitPercent"):
        out[name] = [int(v) for v in re.search(name + r" = \{([^}]*)\}", text).group(1).split(",")]
    out["EnslaveGoldPerDay"] = [float(v) for v in re.search(r"EnslaveGoldPerDay = \{([^}]*)\}", text).group(1).split(",")]
    for name in ("ValuePerCaptive",):
        out[name] = int(re.search(name + r" = (\d+);", text).group(1))
    for name in ("SlaveMarketsGoldMultiplier", "DungeonCellsCaptiveMultiplier", "InterrogationManaPerXp"):
        out[name] = float(re.search(name + r" = ([\d.]+);", text).group(1))
    return out


def n0(v: int) -> str:
    return f"{v:,}"


def offer(rt, rank, defeated_value, losses, killed, enslaved_before=0, interrogation=False, enslave=False, recruit=False,
          slave=False, cells=False, gold=99999, army_writable=True, living_types=3):
    """Mirror of Homm3DungeonCaptivesRuntime.TryBuildOffer / BuildEat / BuildRecruit (losses/killed: (name, count, squadValue[, goldCost]))."""
    i = rank - 1
    captives = math.floor(defeated_value * (rt["DungeonCellsCaptiveMultiplier"] if cells else 1.0) / rt["ValuePerCaptive"])
    xp = captives * rt["ExecuteXpPerCaptive"][i]
    o = dict(rank=rank, captives=captives, xp=xp, mana=math.floor(xp * rt["InterrogationManaPerXp"]) if interrogation else 0,
             ransom=math.floor(captives * rt["RansomGoldPerCaptive"][i] * (rt["SlaveMarketsGoldMultiplier"] if slave else 1.0)),
             slave=slave, cells=cells, enslave=enslave, recruit=recruit, army=army_writable)

    def daily(n):
        return math.floor(n * rt["EnslaveGoldPerDay"][i] * (rt["SlaveMarketsGoldMultiplier"] if slave else 1.0)) if n > 0 else 0

    o["daily_now"], o["daily_after"] = daily(enslaved_before), daily(enslaved_before + captives)
    eat = [(nm, c * rt["EatPercent"][i] // 100, v) for nm, c, v in losses]
    value = sum(c * v for _, c, v in eat)
    cap = captives * rt["ValuePerCaptive"]
    if value > cap:
        eat = [(nm, math.floor(c * cap / value), v) for nm, c, v in eat]
    o["eat"] = [(nm, c) for nm, c, _ in eat if c > 0]
    rec, cost, unit_cost = [], 0, {}
    for nm, c, v, each in sorted(killed, key=lambda k: -(k[1] * rt["RecruitPercent"][i] // 100) * k[2]):
        cnt = c * rt["RecruitPercent"][i] // 100
        if cnt <= 0 or len(rec) >= 7:
            continue
        rec.append((nm, cnt))
        unit_cost[nm] = each
        cost += cnt * each
    o["recruit_units"], o["recruit_cost"], o["unit_cost"], o["gold"] = rec, cost, unit_cost, gold
    return o


def blocked(o, choice):
    """Mirror of Homm3DungeonCaptivesRuntime.IsChoiceAvailable."""
    if choice == "Eat":
        if not o["army"]:
            return "Only right after the battle"
        if not o["eat"]:
            return "No losses to recover"
    if choice == "Enslave" and not o["enslave"]:
        return "Requires Enslave Captives"
    if choice == "Recruit":
        if not o["recruit"]:
            return "Requires Recruit Captives"
        if not o["army"]:
            return "Only right after the battle"
        if not o["recruit_units"]:
            return "Too few captives to recruit"
        if o["gold"] < min(o["unit_cost"].values()):
            return "Not enough gold"
    return None


def units(lines):
    return ", ".join(f"{nm} x{n0(c)}" for nm, c in lines)


def rows(o):
    """Mirror of Homm3DungeonWarCaptivesWindow.BuildRowModels."""
    eat_n = sum(c for _, c in o["eat"])
    rec_n = sum(c for _, c in o["recruit_units"])
    sm = " (Slave Markets +25%)" if o["slave"] else ""
    out = [
        ("Execute", f"+{n0(o['xp'])} experience" + (f", +{n0(o['mana'])} mana (Interrogation)" if o["mana"] else ""), None),
        ("Ransom", f"+{n0(o['ransom'])} gold" + sm, None),
        ("Eat", f"Restore {n0(eat_n)} of your fallen creatures" if eat_n else "Restore part of your losses", units(o["eat"]) if o["eat"] else None),
        ("Enslave", f"+{n0(o['daily_after'] - o['daily_now'])} gold every day" + sm,
         f"Daily gold {n0(o['daily_now'])} -> {n0(o['daily_after'])} while this hero serves" if o["enslave"] else None),
        ("Recruit", f"Recruit up to {n0(rec_n)} defeated creatures" if rec_n else "Recruit some of the defeated",
         f"{units(o['recruit_units'])}; all for {n0(o['recruit_cost'])} gold, choose who joins next" if o["recruit"] and o["recruit_units"] else None),
    ]
    return [(t, e, d, blocked(o, t)) for t, e, d in out]


def render(P, W, cv, o, hero, icon, hover=None, status=None):
    model = rows(o)

    def row_h(r):
        return W["RowHeight"] + (W["RowExtraLine"] if r[2] else 0) + (W["RowExtraLine"] if r[3] else 0)

    height = W["HeaderHeight"] + W["IntroTop"] + W["IntroHeight"] + W["FooterHeight"] + W["BottomPad"] + (W["StatusHeight"] if status else 0)
    height += sum(row_h(r) + W["RowGap"] for r in model)
    width = W["Width"]
    cv.ox, cv.oy = P["ReferenceWidth"] / 2 - width / 2, P["ReferenceHeight"] / 2 - height / 2
    dim = Image.new("RGBA", cv.img.size, (0, 0, 0, int(255 * P["BlockAlpha"])))
    cv.img.alpha_composite(dim)

    pm_ = P["PanelSliceMultiplier"]
    cv.sliced(P["SpritePanelBody"], 0, W["HeaderHeight"] - 12, width, height - W["HeaderHeight"] - W["FooterHeight"] + 24, pm_)
    cv.sliced(P["SpritePanelHeader"], 0, 0, width, W["HeaderHeight"], pm_)
    cv.sliced(P["SpritePanelFooter"], 0, height - W["FooterHeight"], width, W["FooterHeight"], pm_)
    rcx, rcy = W["Pad"] + W["Ring"] / 2, W["HeaderHeight"] / 2
    if icon is not None:
        cv.image(icon, rcx - W["RingIcon"] / 2, rcy - W["RingIcon"] / 2, W["RingIcon"], W["RingIcon"], preserve=True)
    cv.centered(P["SpritePanelRing"], rcx, rcy, W["Ring"], W["Ring"])
    tx = W["Pad"] + W["Ring"] + 12
    tw = width - tx - W["Pad"]
    sub = f"{n0(o['captives'])} captive{'' if o['captives'] == 1 else 's'} taken" + (" (Dungeon Cells +15%)" if o["cells"] else "")
    cv.text(P["FontBook"], P["SizeSubHeader"], "War Captives", tx, 12, tw, 28, P["TipTitle"])
    cv.text(P["FontMedium"], P["SizeSmall"], sub, tx, 40, tw, 22, P["TipNote"])
    y = W["HeaderHeight"] + W["IntroTop"]
    intro = f"{hero} has taken prisoners. Decide their fate." if o["army"] else \
        f"{hero} has taken prisoners. The army has already marched on, so Eat and Recruit are unavailable."
    cv.text(P["FontMedium"], P["SizeMain"], intro, W["Pad"], y, width - 2 * W["Pad"], W["IntroHeight"], P["TipBody"], wrap=True)
    y += W["IntroHeight"]
    for r in model:
        title, effect, detail, why = r
        h = row_h(r)
        x, w = W["Pad"], width - 2 * W["Pad"]
        on = why is None
        sprite = P["SpriteButtonHover"] if on and hover == title else P["SpriteButton"]
        cv.sliced(sprite, x, y, w, h, W["RowSliceMultiplier"], None if on else W["DisabledRowTint"])
        ix, iw = x + W["RowTextInset"], w - 2 * W["RowTextInset"]
        cv.text(P["FontBook"], P["SizeSubHeader"], title, ix, y + W["RowTitleTop"], W["RowTitleWidth"], 28, P["ButtonText"] if on else P["ButtonTextDisabled"])
        ex = ix + W["RowTitleWidth"]
        cv.text(P["FontMedium"], P["SizeMain"], effect, ex, y + W["RowTitleTop"], iw - W["RowTitleWidth"], 28, P["TipBody"] if on else P["ButtonTextDisabled"])
        ly = y + W["RowTitleTop"] + W["RowDetailOffset"]
        if detail:
            cv.text(P["FontMedium"], P["SizeSmall"], detail, ex, ly, iw - W["RowTitleWidth"], 22, P["TipNote"] if on else P["ButtonTextDisabled"])
            ly += W["RowExtraLine"]
        if not on:
            cv.text(P["FontMedium"], P["SizeSmall"], why, ex, ly, iw - W["RowTitleWidth"], 22, P["TipWarn"])
        y += h + W["RowGap"]
    if status:
        cv.text(P["FontMedium"], P["SizeSmall"], status, W["Pad"], y, width - 2 * W["Pad"], W["StatusHeight"], P["CostBad"], wrap=True)


# ----------------------------------------------------------------------------------------- recruit panel
class Board:
    """Mirror of Homm3DungeonCaptivesRuntime.RecruitBoard (rows of (name, count) or None; 7 slots each)."""

    ARMY_NEEDS_A_STACK = "Your hero must keep at least one stack."

    def __init__(self, army, captives, unit_cost):
        self.top = [None] * 7
        self.bottom = [None] * 7
        for i, s in enumerate(army):
            self.top[i] = s
        for i, s in enumerate(captives[:7]):
            self.bottom[i] = s
        self.own, self.captured = {}, {}
        for s in army:
            if s:
                self.own[s[0]] = self.own.get(s[0], 0) + s[1]
        for nm, c in captives[:7]:
            self.captured[nm] = self.captured.get(nm, 0) + c
        self.unit_cost = unit_cost

    def row(self, top):
        return self.top if top else self.bottom

    def total(self, top, nm):
        return sum(s[1] for s in self.row(top) if s and s[0] == nm)

    def recruited(self, nm):
        return max(0, self.total(True, nm) - self.own.get(nm, 0))

    def recruited_total(self):
        return sum(self.recruited(nm) for nm in self.captured)

    def released(self, nm):
        return max(0, self.own.get(nm, 0) - self.total(True, nm))

    def released_total(self):
        return sum(self.released(nm) for nm in self.own)

    def changed(self):
        return self.recruited_total() > 0 or self.released_total() > 0

    def valid(self):
        return any(self.top)

    def first_free(self, top):
        return next((i for i, s in enumerate(self.row(top)) if s is None), -1)

    def move(self, ft, f, tt, t, amount=0):
        src, dst = self.row(ft), self.row(tt)
        if (ft == tt and f == t) or src[f] is None:
            return ""
        nm, cnt = src[f]
        amount = cnt if amount <= 0 or amount > cnt else amount
        snap = (list(self.top), list(self.bottom))
        if dst[t] is None:
            dst[t], src[f] = (nm, amount), ((nm, cnt - amount) if cnt > amount else None)
        elif dst[t][0] == nm:
            dst[t], src[f] = (nm, dst[t][1] + amount), ((nm, cnt - amount) if cnt > amount else None)
        else:
            if amount < cnt:
                return "Split into an empty slot."
            dst[t], src[f] = src[f], dst[t]
        if self.valid():
            return None
        self.top, self.bottom = snap
        return self.ARMY_NEEDS_A_STACK

    def move_to_other_row(self, top, i):
        s = self.row(top)[i]
        if s is None:
            return ""
        other = self.row(not top)
        target = next((j for j, o in enumerate(other) if o and o[0] == s[0]), -1)
        if target < 0:
            target = self.first_free(not top)
        if target < 0:
            return "No free slot among the captives." if top else "No free army slot."
        return self.move(top, i, not top, target)

    def recruit_all(self):
        for i in range(7):
            if self.bottom[i] is not None:
                self.move_to_other_row(False, i)

    def cost(self):
        return sum(self.recruited(nm) * self.unit_cost[nm] for nm in self.captured)


def render_recruit(P, W, cv, board, hero, portraits, gold, selected=None, hover=None, hover_radial=None, status=None, drag=None):
    """Mirror of Homm3DungeonWarCaptivesWindow.BuildRecruit (+ the hover/drag state TickRecruit draws)."""
    w, h = W["RecruitWidth"], W["RecruitHeight"]
    cv.ox, cv.oy = P["ReferenceWidth"] / 2 - w / 2, P["ReferenceHeight"] / 2 - h / 2
    dim = Image.new("RGBA", cv.img.size, (0, 0, 0, int(255 * P["BlockAlpha"])))
    cv.img.alpha_composite(dim)

    def flip(name, x, y, ww, hh, fx, fy):
        im = cv.spr[name]
        if fx:
            im = im.transpose(Image.FLIP_LEFT_RIGHT)
        if fy:
            im = im.transpose(Image.FLIP_TOP_BOTTOM)
        cv.image(im, x, y, ww, hh)

    cv.sprite(W["SpriteRecruitBack"], 0, 0, w, h)
    cv.sliced(W["SpriteRecruitGradient"], 0, 0, w, h, 1.0)
    cv.sprite(W["SpriteRecruitLightBack"], (w - W["RecruitBandWidth"]) / 2, W["RecruitHeaderHeight"] / 2, W["RecruitBandWidth"], W["RecruitTopBandHeight"])
    cv.sprite(W["SpriteRecruitLightBack"], (w - W["RecruitBandWidth"]) / 2, h - W["RecruitBottomBandHeight"] - W["RecruitFrameInset"], W["RecruitBandWidth"], W["RecruitBottomBandHeight"])
    cv.sliced(W["SpriteRecruitSeparator"], (w - W["RecruitSeparatorWidth"]) / 2, W["RecruitButtonY"] - W["RecruitSeparatorHeight"] / 2, W["RecruitSeparatorWidth"], W["RecruitSeparatorHeight"], 1.0)
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
    tw = W["RecruitTitleWidth"]
    cv.text(P["FontBook"], P["SizeSubHeader"], "Recruit Captives", w / 2 - tw / 2, 0, tw, W["RecruitHeaderHeight"], P["TipTitle"], align="center")

    lw, lh = W["RecruitLabelWidth"], W["RecruitLabelHeight"]
    cv.text(P["FontMedium"], P["SizeMain"], f"Army of {hero}", (w - lw) / 2, W["RecruitArmyLabelY"] - lh / 2, lw, lh, P["TipTitle"], align="center")
    cv.text(P["FontMedium"], P["SizeMain"], "Captives willing to join", (w - lw) / 2, W["RecruitCaptiveLabelY"] - lh / 2, lw, lh, P["TipTitle"], align="center")

    def sx(i):
        return W["RecruitSlotFirstX"] + i * W["RecruitSlotPitch"]

    def ry(top):
        return W["RecruitArmyRowY"] if top else W["RecruitCaptiveRowY"]

    def portrait(nm, cx, cy, alpha=255):
        im = portraits[nm]
        pw, ph = W["RecruitPortraitWidth"], W["RecruitPortraitHeight"]
        k = max(pw / im.width, ph / im.height)
        big = im.resize((max(1, round(im.width * k * 2)), max(1, round(im.height * k * 2))), Image.LANCZOS)
        crop = big.crop(((big.width - round(pw * 2)) // 2, (big.height - round(ph * 2)) // 2,
                         (big.width - round(pw * 2)) // 2 + round(pw * 2), (big.height - round(ph * 2)) // 2 + round(ph * 2)))
        mask = cv.spr[W["SpriteRecruitPortraitMask"]].resize(crop.size, Image.LANCZOS).getchannel("A")
        a = Image.composite(crop.getchannel("A"), Image.new("L", crop.size, 0), mask)
        if alpha < 255:
            a = a.point(lambda v: v * alpha // 255)
        crop.putalpha(a)
        cv.image(crop, cx - pw / 2, cy - ph / 2, pw, ph)

    for top in (True, False):
        for i in range(7):
            cx, cy = sx(i), ry(top)
            s = board.row(top)[i]
            bw, bh = W["RecruitSlotBackWidth"], W["RecruitSlotBackHeight"]
            cv.centered(W["SpriteRecruitSlotBack"], cx, cy, bw, bh)
            is_hover = hover == (top, i)
            if s is None:
                cv.centered(W["SpriteRecruitSlotEmptyHover"] if is_hover and drag else W["SpriteRecruitSlotEmpty"], cx, cy, bw, bh)
                continue
            cw, ch = W["RecruitCardWidth"], W["RecruitCardHeight"]
            cv.centered(W["SpriteRecruitCardSelected"] if selected == (top, i) else W["SpriteRecruitCard"], cx, cy, cw, ch)
            portrait(s[0], cx, cy)
            cv.centered(W["SpriteRecruitCountOverlay"], cx, cy + W["RecruitCountOffset"], W["RecruitCountWidth"], W["RecruitCountHeight"])
            cv.text(P["FontMedium"], P["SizeMain"], n0(s[1]), cx - W["RecruitSlotWidth"] / 2, cy + W["RecruitAmountOffset"] - W["RecruitLineHeight"] / 2,
                    W["RecruitSlotWidth"], W["RecruitLineHeight"], P["TipTitle"], align="center")
            if is_hover:
                cv.centered(W["SpriteRecruitCardHover"], cx, cy, cw, ch)

    hint = None
    if selected is not None:
        top, i = selected
        cx, cy = sx(i), ry(top)
        nm, cnt = board.row(top)[i]
        dx, dy = W["RecruitRadialDx"], W["RecruitRadialDy"]
        buttons = [(cx - dx, cy - dy, W["SpriteRecruitRadialMove"], "Release (move below)" if top else "Move into your army")]
        if board.total(top, nm) > cnt:
            buttons.append((cx + dx, cy - dy, W["SpriteRecruitRadialGather"], f"Gather every {nm} stack here"))
        if cnt >= 2 and board.first_free(top) >= 0:
            buttons.append((cx - dx, cy + dy, W["SpriteRecruitRadialHalf"], "Split in half"))
            buttons.append((cx + dx, cy + dy, W["SpriteRecruitRadialDivide"], "Split one off"))
        for k, (bx, by, spr, text) in enumerate(buttons):
            on = hover_radial == k
            cv.centered(spr + "_MouseOver" if on else spr, bx, by, W["RecruitRadialWidth"], W["RecruitRadialHeight"])
            if on:
                hint = text

    if drag is not None:
        (ft, fi), (mx, my) = drag
        nm = board.row(ft)[fi][0]
        cw, ch = W["RecruitCardWidth"], W["RecruitCardHeight"]
        cv.centered(W["SpriteRecruitCardSelected"], mx, my, cw, ch)
        portrait(nm, mx, my, 217)

    recruited = board.recruited_total()
    released = board.released_total()
    cost = board.cost()
    ok = gold >= cost
    gone = ", ".join(f"{nm} x{n0(board.released(nm))}" for nm in board.own if board.released(nm) > 0)
    if recruited <= 0 and released <= 0:
        line = "Drag captives into your army to recruit them. Whatever is left below is released."
    elif recruited <= 0:
        line = f"Releasing {gone} from your army"
    else:
        parts = ", ".join(f"{nm} x{n0(board.recruited(nm))}" for nm in board.captured if board.recruited(nm) > 0)
        line = f"Recruiting {parts} for {n0(cost)} gold" + ("" if ok else " (not enough gold)") + (f"; releasing {gone}" if released else "")
    inset = W["RecruitTextInset"]
    cv.text(P["FontMedium"], P["SizeMain"], line, inset, W["RecruitCostY"], w - 2 * inset, W["RecruitLineHeight"], P["CostBad"] if recruited and not ok else P["TipBody"], align="center")
    note = hint or status
    if note:
        cv.text(P["FontMedium"], P["SizeSmall"], note, inset, W["RecruitStatusY"], w - 2 * inset, W["RecruitLineHeight"], P["TipNote"] if hint else P["TipWarn"], align="center")

    bw, bh, gap = W["RecruitButtonWidth"], W["RecruitButtonHeight"], W["RecruitButtonGap"]
    bx = (w - 3 * bw - 2 * gap) / 2
    by = W["RecruitButtonY"] - bh / 2
    for k, (label, normal, hov, enabled) in enumerate([
        ("Back", W["SpriteRecruitButton"], W["SpriteRecruitButtonHover"], True),
        ("Recruit all", W["SpriteRecruitButtonGreen"], W["SpriteRecruitButtonGreenHover"], True),
        ("Recruit", W["SpriteRecruitButton"], W["SpriteRecruitButtonHover"], board.changed() and ok),
    ]):
        x = bx + k * (bw + gap)
        cv.sprite(W["SpriteRecruitButtonBase"], x, by, bw, bh)
        name = (hov if hover == ("button", k) else normal) if enabled else W["SpriteRecruitButtonDisabled"]
        cv.sliced(name, x, by, bw, bh, W["RecruitButtonSliceMultiplier"])
        cv.text(P["FontBook"], P["SizeSubHeader"], label, x, by, bw, bh, P["ButtonText"] if enabled else P["ButtonTextDisabled"], align="center")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=Path("V:/tmp/dungeon_war_captives_window"))
    args = ap.parse_args()
    out: Path = args.out
    out.mkdir(parents=True, exist_ok=True)
    P = pm.layout()
    W = meter.parse_class(WINDOW_CS, "internal static class Homm3DungeonWarCaptivesWindowLayout")
    rt = runtime_constants()
    sprite_names = [P[k] for k in ("SpritePanelHeader", "SpritePanelBody", "SpritePanelFooter", "SpritePanelRing",
                                   "SpriteButton", "SpriteButtonHover")]
    assets = out / "assets"
    pm.SPRITE_FILES = tuple(pm.SPRITE_FILES) + tuple(f for f in ("sharedassets3.assets", "sharedassets6.assets") if f not in pm.SPRITE_FILES)
    sprite_names += [v for v in W["RecruitSprites"] if v not in sprite_names]
    meta = pm.export(assets, sprite_names, [])
    spr = {n: Image.open(assets / m["file"]).convert("RGBA") for n, m in meta.items() if n in sprite_names}
    # Separators_Horizontal's top+bottom borders (75+75 px) overlap its 116 px height; clamp for the crop (uGUI does the same).
    sep = meta[W["SpriteRecruitSeparator"]]
    half = spr[W["SpriteRecruitSeparator"]].height / 2
    sep["border"] = [sep["border"][0], min(sep["border"][1], half), sep["border"][2], min(sep["border"][3], half)]
    portraits = {nm: Image.open(MOD / "homm3_portraits" / f"{key}.png").convert("RGBA") for nm, key in PORTRAITS.items()}
    fonts = {f: pm.Font(assets, f) for f in pm.FONTS}
    icon = Image.open(SKILL_ICON).convert("RGBA") if SKILL_ICON.is_file() else None
    bg = Image.open(pm.MAP_SHOT) if pm.MAP_SHOT.is_file() else Image.new("RGBA", (1920, 1080), (30, 34, 40, 255))
    shots = []

    def shot(fname, o, lines, **kw):
        cv = pm.Canvas(P, spr, meta, fonts, bg)
        render(P, W, cv, o, "Alamar", icon, **kw)
        meter.caption(cv.img, lines, size=15).save(out / fname)
        shots.append(fname)

    losses = [("Infernal Troglodyte", 8, 70), ("Harpy Hag", 3, 160)]
    killed = [("Halberdier", 20, 115, 75), ("Crusader", 6, 300, 300), ("Marksman", 9, 220, 175)]
    expert = offer(rt, 3, 3240, losses, killed, enslaved_before=52, interrogation=True, enslave=True, recruit=True, slave=True, cells=True)
    shot("01_expert_all_options.png", expert, [
        "WAR CAPTIVES choice window (1920x1080 reference), opened when a Dungeon hero wins a battle, before the result is written to the army. Native law-tooltip sprites and fonts (same set as the Artificing panel).",
        f"Expert War Captives with every subskill: 3,240 squad value killed x1.15 Dungeon Cells / 100 = {expert['captives']} captives. Execute 12 XP each (+10% mana Interrogation); Ransom 20 gold each x1.25 Slave Markets;",
        "Eat 40% of each lost stack (floor); Enslave 2 gold/day each x1.25 (52 already enslaved); Recruit 20% of each defeated type at full cost. Click a row to choose; no close button (the result waits on the choice).",
    ], hover="Eat")
    basic = offer(rt, 1, 860, [], killed[:1])
    shot("02_basic_no_subskills.png", basic, [
        f"Basic War Captives, no subskills, no losses: 860 squad value killed -> {basic['captives']} captives. Eat greyed (no losses), Enslave and Recruit greyed with the subskill they need, on the greyed button plate.",
    ])
    poor = offer(rt, 2, 2100, losses, killed, enslave=True, recruit=True, gold=150)
    shot("03_advanced_recruit_unaffordable.png", poor, [
        "Advanced with Enslave and Recruit but only 150 gold: Recruit shows the creatures and price but is greyed 'Not enough gold' (rechecked on click and again when it applies).",
        "Hover state on Ransom (buttom_MouseOver).",
    ], hover="Ransom")
    late = dict(expert, army=False)
    shot("04_late_fallback.png", late, [
        "Fallback only: if the battle's result was written before the window could open (deferral hook missing), Eat and Recruit are unavailable and the intro says why. Normal play never shows this.",
    ])
    def panel(fname, board, lines, gold=99999, **kw):
        cv = pm.Canvas(P, spr, meta, fonts, bg)
        render_recruit(P, W, cv, board, "Alamar", portraits, gold, **kw)
        meter.caption(cv.img, lines, size=15).save(out / fname)
        shots.append(fname)

    army = [("Infernal Troglodyte", 38), ("Harpy Hag", 14), None, ("Beholder", 9), ("Minotaur", 4), None, None]
    # A bigger fight than shot 01 so the stacks read: 60 Halberdiers, 18 Crusaders, 30 Marksmen killed.
    big = offer(rt, 3, 12000, losses, [("Halberdier", 60, 115, 75), ("Crusader", 18, 300, 300), ("Marksman", 30, 220, 175)],
                interrogation=True, enslave=True, recruit=True, slave=True, cells=True)
    expert = big
    caps = expert["recruit_units"]
    board = Board(army, caps, expert["unit_cost"])
    panel("05_recruit_panel_open.png", board, [
        "RECRUIT panel (clicking Recruit in the choice window): a clone of the native diplomacy join panel CanvasDiplomacyUnitsPanel, same geometry and sprites",
        "(Window_ModalWindow_*, HUD_DownBar_UnitSlot, Frame_Unit_Back cards with the portrait mask and squad-count overlay, buttom / buttom_green buttons).",
        f"Top row: the hero's army as it stands after the battle (slot positions kept). Bottom row: the {len(caps)} captive stacks willing to join (Expert: 20% of each defeated type). Nothing recruited yet.",
    ], hover=(False, 0))
    b2 = Board(army, caps, expert["unit_cost"])
    b2.recruit_all()
    panel("06_recruit_all.png", b2, [
        "After 'Recruit all' (native 'Add all Army'): every captive stack moves up into a free army slot (or onto the same creature). Price is the recruited creatures only.",
        "Recruit confirms exactly this arrangement and charges the shown price; Back returns to the choice window without recruiting.",
    ], hover=("button", 2))
    b3 = Board(army, caps, expert["unit_cost"])
    b3.move(False, 0, True, 2)
    b3.move(False, 2, True, 5)
    b3.move(True, 0, True, 6)
    status = b3.move(True, 1, False, 4)
    panel("07_partial_rearranged.png", b3, [
        "Partial recruit by drag and drop: Halberdiers dragged to army slot 3, Marksmen to slot 6, the Troglodytes moved to slot 7 (own stacks rearrange freely); Crusaders left below are released.",
        "The hero's own Harpies were dragged down into the bottom row: as in the native panel they are released on Recruit (the army must keep at least one stack).",
    ], status=status, gold=3000)
    b4 = Board(army, caps, expert["unit_cost"])
    b4.move(False, 0, True, 2)
    panel("08_stack_buttons.png", b4, [
        "Clicking a stack opens the native split/move buttons around it (Button_Unit_Move / Union / Half / Divide): move to the other row, gather same-creature stacks, split in half, split one off.",
        "Hovering a button shows what it does on the hint line. Drag a stack onto another slot to move it; onto the same creature to merge; onto a different creature to swap.",
    ], selected=(True, 2), hover_radial=1)
    b5 = Board(army, caps, expert["unit_cost"])
    panel("09_dragging.png", b5, [
        "Dragging: the stack's card follows the cursor; the slot under it lights up (Frame_Unit_Empty-1 / Frame_Unit_Top_MauseOver). Releasing on a slot moves the whole stack.",
    ], hover=(True, 5), drag=((False, 1), (W["RecruitSlotFirstX"] + 5 * W["RecruitSlotPitch"] + 14, W["RecruitArmyRowY"] + 18)))
    print(f"{len(shots)} mockups -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
