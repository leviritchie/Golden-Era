"""Render approval mockups of the Conflux Elemental Fusion panel without launching the game.

Single sources of truth (nothing is re-typed here):
  * panel geometry and its own sprites: Homm3ConfluxFusionPanelLayout in
    Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/Homm3ConfluxFusionPanel.cs
  * shell, slot, card and button geometry: Homm3DungeonWarCaptivesWindowLayout (the recruit panel the fusion panel reuses)
  * fonts, sizes, colours: Homm3TowerArtificingPickerLayout (the law-tooltip clone both panels use)
  * rules: custom_factions/conflux_fusion/fusion_config.json (penalty, minShare, tierLines, lines, pairs)
  * maths and texts: Python mirrors of Homm3ConfluxFusionRuntime.BuildPlan / BuildTrimmedPlan / Homm3ConfluxFusionMath /
    EligibilityBlock and of the panel's Build() (v2, 2026-11-15: slots + Cancel / Fuse only, drag, trim always on)
  * squad values: parents from the installed Core.zip units_logics rows (what Homm3ConfluxFusionRuntime.SquadValue reads
    live), fused units from custom_factions/conflux_fusion/fusion_units.json (what the Core overlay writes)
  * display names: the installed Core.zip Lang/english/texts/units.json / heroes.json tokens (Homm3UnitDisplayNames /
    Homm3HeroDisplayNames); fused units fall back to the pair name (Homm3ConfluxFusionRuntime.FusedName)
  * portraits: OfflineUnlockMod/homm3_portraits/<sid>.png; skill icon: homm3_skill_icons/skill_faction_homm3_conflux.png
  * native sprites and SDF fonts: exported read-only from the installed game by tools/tower_artificing/picker_mockup.py
  * background: V:/olden_port_work/run4_s10.png scaled to 1920x1080, dimmed like the panel's Block

    python tools/conflux_fusion/panel_mockup.py [--out V:/olden_port_work/elemental_fusion/mockup_native_v2]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import zipfile
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_EVEN, Decimal
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
PANEL_CS = MOD / "Homm3ConfluxFusionPanel.cs"
WINDOW_CS = MOD / "Homm3DungeonWarCaptivesWindow.cs"
CONFIG = ROOT / "custom_factions" / "conflux_fusion" / "fusion_config.json"
UNITS = ROOT / "custom_factions" / "conflux_fusion" / "fusion_units.json"
SKILL_ICON = MOD / "homm3_skill_icons" / "skill_faction_homm3_conflux.png"
PORTRAITS = MOD / "homm3_portraits"
CORE_ZIP = pm.GAME_DATA / "StreamingAssets" / "Core.zip"
HERO_SID = "homm3_conflux_hero_1"
MAX_SLOTS = 7


# ----------------------------------------------------------------------------------------- data
class Data:
    def __init__(self):
        self.cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
        self.penalty = Decimal(str(self.cfg["penalty"]))
        self.min_share = Decimal(str(self.cfg["minShare"]))
        self.line_by_unit = {sid: line for line, sids in self.cfg["lines"].items() for sid in sids}
        self.line_order = list(self.cfg["lines"])
        self.tier_lines = {int(k): set(v) for k, v in self.cfg["tierLines"].items()}
        self.pairs = {frozenset((p["a"], p["b"])): p for p in self.cfg["pairs"]}
        fused_units = json.loads(UNITS.read_text(encoding="utf-8"))["units"]
        self.values = {sid: int(u["squadValue"]) for sid, u in fused_units.items()}
        with zipfile.ZipFile(CORE_ZIP) as z:
            for name in z.namelist():
                if name.startswith("DB/units/units_logics/homm3_conflux/") and name.endswith("_l.json"):
                    row = json.loads(z.read(name))
                    for r in row.get("array", [row]) if isinstance(row, dict) else row:
                        if isinstance(r, dict) and r.get("id") and "squadValue" in r and not r["id"].startswith("h3_fusion_"):
                            self.values[r["id"]] = int(r["squadValue"])
            self.unit_names = {t["sid"]: t["text"] for t in json.loads(z.read("Lang/english/texts/units.json"))["tokens"] if t.get("text")}
            self.hero_names = {t["sid"]: t["text"] for t in json.loads(z.read("Lang/english/texts/heroes.json"))["tokens"] if t.get("text")}

    def unlocked(self, rank):
        return set().union(*(v for k, v in self.tier_lines.items() if k <= rank))

    def rank_for_line(self, line):
        return min((k for k, v in self.tier_lines.items() if line in v), default=4)

    def unit_name(self, sid):
        """Homm3UnitDisplayNames.Resolve."""
        return self.unit_names.get(sid + "_name", sid)

    def hero_name(self, sid):
        """Homm3HeroDisplayNames.Resolve."""
        return self.hero_names.get(sid + "_name") or self.hero_names.get(sid) or sid

    def fused_name(self, pair):
        """Homm3ConfluxFusionRuntime.FusedName."""
        name = self.unit_name(pair["fused"])
        return name if name != pair["fused"] or not pair.get("name") else pair["name"].strip()


RANKS = {1: "Basic", 2: "Advanced", 3: "Expert"}


def rank_name(rank):
    return RANKS.get(rank, "higher")


def cap(s):
    return s[:1].upper() + s[1:]


def percent(share: Decimal) -> str:
    """Homm3ConfluxFusionRuntime.Percent (Math.Round: banker's)."""
    return str((share * 100).quantize(Decimal(1), ROUND_HALF_EVEN)) + "%"


def n0(v) -> str:
    return f"{int(v):,}"


def unlocked_lines_text(d: Data, rank):
    u = d.unlocked(rank)
    return ", ".join(cap(line) for line in d.line_order if line in u)


def eligibility_block(d: Data, rank, sid):
    """Homm3ConfluxFusionRuntime.EligibilityBlock."""
    line = d.line_by_unit.get(sid)
    if sid is None or line is None:
        return "Not an elemental."
    if line not in d.unlocked(rank):
        return f"Requires {rank_name(d.rank_for_line(line))} Conflux ({cap(line)} line)."
    return None


# Homm3ConfluxFusionMath
def fused_count(nA, vA, nB, vB, vF, penalty):
    if vF <= 0:
        return 0
    f = (penalty * (Decimal(nA) * vA + Decimal(nB) * vB) / vF).to_integral_value(ROUND_FLOOR)
    return max(0, int(f))


def shares_ok(nA, vA, nB, vB, min_share):
    a, b = Decimal(nA) * vA, Decimal(nB) * vB
    pooled = a + b
    if pooled <= 0:
        return False, 0
    if a < min_share * pooled:
        return False, 0
    if b < min_share * pooled:
        return False, 1
    return True, -1


def _ceil(v: Decimal) -> int:
    return int(v.to_integral_value(ROUND_CEILING))


def _floor(v: Decimal) -> int:
    return int(v.to_integral_value(ROUND_FLOOR))


def best_inputs(nA, vA, nB, vB, vF, penalty, min_share):
    """Homm3ConfluxFusionMath.BestInputs: most fused under the share rule, then least pooled; ties keep more of A."""
    if nA < 1 or nB < 1 or vA <= 0 or vB <= 0 or vF <= 0 or penalty <= 0:
        return None
    best, best_count, best_pooled = None, 0, None
    for tA in range(1, nA + 1):
        lo, hi = 1, nB
        if 0 < min_share < 1:
            a = Decimal(tA) * vA
            lo = min(max(_ceil(min_share * a / ((1 - min_share) * vB)), 1), nB + 1)
            hi = min(max(_floor(a * (1 - min_share) / (min_share * vB)), 0), nB)
        while lo <= hi and not shares_ok(tA, vA, lo, vB, min_share)[0]:
            lo += 1
        while hi >= lo and not shares_ok(tA, vA, hi, vB, min_share)[0]:
            hi -= 1
        if lo > hi:
            continue
        count = fused_count(tA, vA, hi, vB, vF, penalty)
        if count < 1:
            continue
        need = Decimal(count) * vF / penalty - Decimal(tA) * vA
        tB = lo if need <= 0 else max(lo, min(max(_ceil(need / vB), lo), hi))
        while tB < hi and fused_count(tA, vA, tB, vB, vF, penalty) < count:
            tB += 1
        while tB > lo and fused_count(tA, vA, tB - 1, vB, vF, penalty) >= count:
            tB -= 1
        pooled = Decimal(tA) * vA + Decimal(tB) * vB
        if count > best_count or (count == best_count and pooled < best_pooled):
            best, best_count, best_pooled = (tA, tB), count, pooled
    return best


class Plan:
    pass


def build_plan(d: Data, rank, sids, counts, a, b, inA, inB, discard=-1):
    """Homm3ConfluxFusionRuntime.BuildPlan."""
    p = Plan()
    p.InA, p.InB, p.Pair, p.Pooled, p.Fused, p.ValueA, p.ValueB, p.ValueF = inA, inB, None, 0, 0, 0, 0, 0
    p.Blocked, p.NoFreeSlot, p.CountA, p.CountB = None, False, 0, 0
    p.LostSid, p.LostCount, p.LossWarning = None, 0, None
    if a < 0 or b < 0 or a == b or sids[a] is None or sids[b] is None:
        p.Blocked = "Pick two elemental stacks."
        return p
    p.SidA, p.SidB, p.CountA, p.CountB = sids[a], sids[b], counts[a], counts[b]
    if p.SidA == p.SidB:
        p.Blocked = "Pick two different elementals."
        return p
    p.Blocked = eligibility_block(d, rank, p.SidA) or eligibility_block(d, rank, p.SidB)
    if p.Blocked:
        return p
    p.Pair = d.pairs.get(frozenset((p.SidA, p.SidB)))
    if p.Pair is None:
        p.Blocked = "These two elementals do not fuse."
        return p
    p.ValueA, p.ValueB, p.ValueF = d.values.get(p.SidA, 0), d.values.get(p.SidB, 0), d.values.get(p.Pair["fused"], 0)
    if p.ValueF <= 0:
        p.Blocked = f"{d.fused_name(p.Pair)} is not installed in this game ({p.Pair['fused']})."
        return p
    if inA < 1 or inB < 1 or inA > counts[a] or inB > counts[b]:
        p.Blocked = "Put at least one of each in."
        return p
    p.Pooled = inA * p.ValueA + inB * p.ValueB
    p.Fused = fused_count(inA, p.ValueA, inB, p.ValueB, p.ValueF, d.penalty)
    ok, weak = shares_ok(inA, p.ValueA, inB, p.ValueB, d.min_share)
    if not ok:
        p.Blocked = f"Each elemental must bring at least {percent(d.min_share)} of the pooled strength (add more {d.unit_name(p.SidA if weak == 0 else p.SidB)})."
        return p
    if p.Fused < 1:
        p.Blocked = f"Too few creatures for one {d.fused_name(p.Pair)}."
        return p
    after = list(sids)
    for s, n in ((a, inA), (b, inB)):
        if counts[s] - n <= 0:
            after[s] = None
        elif s == discard:
            p.LostSid, p.LostCount = sids[s], counts[s] - n
            p.LossWarning = f"Your army is full: the {n0(p.LostCount)} leftover {d.unit_name(p.LostSid)} will be lost."
            after[s] = None
    if after[a] is not None and after[b] is not None and p.Pair["fused"] not in after and None not in after:
        p.Blocked, p.NoFreeSlot = f"No free army slot for the {d.fused_name(p.Pair)}.", True
    return p


def build_trimmed_plan(d: Data, rank, sids, counts, a, b):
    """Homm3ConfluxFusionRuntime.BuildTrimmedPlan (trim is always on)."""
    whole = build_plan(d, rank, sids, counts, a, b, counts[a] if a >= 0 else 0, counts[b] if b >= 0 else 0)
    if whole.Pair is None or whole.ValueA <= 0 or whole.ValueB <= 0 or whole.ValueF <= 0 or whole.CountA < 1 or whole.CountB < 1:
        return whole
    args = (whole.CountA, whole.ValueA, whole.CountB, whole.ValueB, whole.ValueF, d.penalty, d.min_share)
    t = best_inputs(*args)
    if t is None:
        return whole
    plan = build_plan(d, rank, sids, counts, a, b, *t)
    if plan.NoFreeSlot:
        lost_a, lost_b = (whole.CountA - t[0]) * whole.ValueA, (whole.CountB - t[1]) * whole.ValueB
        plan = build_plan(d, rank, sids, counts, a, b, *t, discard=a if lost_a < lost_b else b)
    return plan


# ----------------------------------------------------------------------------------------- scene
class State:
    def __init__(self, rank, army, a=-1, b=-1, hover=None, drag=None, status=None, confirm=False):
        self.rank = rank
        self.sids = [s[0] if s else None for s in army] + [None] * (MAX_SLOTS - len(army))
        self.counts = [s[1] if s else 0 for s in army] + [0] * (MAX_SLOTS - len(army))
        self.inn = [a, b]
        self.hover = hover  # ("card", i) / ("button", label) / ("fusion", which)
        self.drag = drag    # (sid, (x, y) window space, target fusion slot or None)
        self.status = status
        self.confirm = confirm  # Fuse pressed on a plan that drops a leftover: Cancel / Confirm


class Panel:
    """Mirror of Homm3ConfluxFusionPanel.Build (+ the hover / drag state Tick draws)."""

    def __init__(self, P, W, L, cv, d: Data, portraits, icon):
        self.P, self.W, self.L, self.cv, self.d, self.portraits, self.icon = P, W, L, cv, d, portraits, icon

    def flip(self, name, x, y, w, h, fx, fy, color=None):
        im = self.cv.spr[name]
        if fx:
            im = im.transpose(Image.FLIP_LEFT_RIGHT)
        if fy:
            im = im.transpose(Image.FLIP_TOP_BOTTOM)
        self.cv.image(im, x, y, w, h, color)

    def text(self, font, size, s, x, y, w, h, color, align="left"):
        self.cv.text(font, size, s, x, y, w, h, color, align=align)

    def portrait(self, sid, cx, cy, tint=None):
        W, cv = self.W, self.cv
        im = self.portraits.get(sid)
        if im is None:
            self.text(self.P["FontMedium"], self.P["SizeSmall"], self.d.unit_name(sid), cx - W["RecruitPortraitWidth"] / 2, cy - W["RecruitPortraitHeight"] / 2,
                      W["RecruitPortraitWidth"], W["RecruitPortraitHeight"] - 20, self.P["TipNote"], "center")
            return
        pw, ph = W["RecruitPortraitWidth"], W["RecruitPortraitHeight"]
        k = max(pw / im.width, ph / im.height)
        big = im.resize((max(1, round(im.width * k * 2)), max(1, round(im.height * k * 2))), Image.LANCZOS)
        ox, oy = (big.width - round(pw * 2)) // 2, (big.height - round(ph * 2)) // 2
        crop = big.crop((ox, oy, ox + round(pw * 2), oy + round(ph * 2)))
        mask = cv.spr[W["SpriteRecruitPortraitMask"]].resize(crop.size, Image.LANCZOS).getchannel("A")
        crop.putalpha(Image.composite(crop.getchannel("A"), Image.new("L", crop.size, 0), mask))
        cv.image(crop, cx - pw / 2, cy - ph / 2, pw, ph, tint)

    def render(self, s: State):
        P, W, L, cv, d = self.P, self.W, self.L, self.cv, self.d
        self.s = s
        w, h = W["RecruitWidth"], L["Height"]
        cv.ox, cv.oy = P["ReferenceWidth"] / 2 - w / 2, P["ReferenceHeight"] / 2 - h / 2
        cv.img.alpha_composite(Image.new("RGBA", cv.img.size, (0, 0, 0, int(255 * P["BlockAlpha"]))))
        self.hint = None

        cv.sprite(W["SpriteRecruitBack"], 0, 0, w, h)
        cv.sliced(W["SpriteRecruitGradient"], 0, 0, w, h, 1.0)
        cv.sprite(W["SpriteRecruitLightBack"], (w - W["RecruitBandWidth"]) / 2, W["RecruitHeaderHeight"] / 2, W["RecruitBandWidth"], W["RecruitTopBandHeight"])
        cv.sprite(W["SpriteRecruitLightBack"], (w - W["RecruitBandWidth"]) / 2, h - W["RecruitBottomBandHeight"] - W["RecruitFrameInset"], W["RecruitBandWidth"], W["RecruitBottomBandHeight"])
        cv.sliced(W["SpriteRecruitSeparator"], (w - W["RecruitSeparatorWidth"]) / 2, L["ButtonY"] - W["RecruitSeparatorHeight"] / 2, W["RecruitSeparatorWidth"], W["RecruitSeparatorHeight"], 1.0)
        cv.sliced(W["SpriteRecruitBackFrame"], 0, 0, w, h, 1.0)
        cv.sliced(W["SpriteRecruitFrame"], 0, 0, w, h, 1.0)
        c = W["RecruitCorner"]
        self.flip(W["SpriteRecruitCorner"], 0, 0, c, c, False, False)
        self.flip(W["SpriteRecruitCorner"], w - c, 0, c, c, True, False)
        self.flip(W["SpriteRecruitCorner"], 0, h - c, c, c, False, True)
        self.flip(W["SpriteRecruitCorner"], w - c, h - c, c, c, True, True)
        cv.centered(W["SpriteRecruitDecorFooter"], w / 2, h - W["RecruitDecorFooterHeight"] / 2, W["RecruitDecorFooterWidth"], W["RecruitDecorFooterHeight"])
        ov = W["RecruitHeaderOverhang"]
        cv.sliced(W["SpriteRecruitHeader"], -ov / 2, 0, w + ov, W["RecruitHeaderHeight"], 1.0)
        hy = W["RecruitHeaderHeight"] / 2
        ow, oh, ox = W["RecruitOrnamentWidth"], W["RecruitOrnamentHeight"], W["RecruitOrnamentX"]
        self.flip(W["SpriteRecruitHeaderOrnament"], w / 2 + ox - ow / 2, hy - oh / 2, ow, oh, False, False)
        self.flip(W["SpriteRecruitHeaderOrnament"], w / 2 - ox - ow / 2, hy - oh / 2, ow, oh, True, False)
        mw, mh, mx = W["RecruitMetalWidth"], W["RecruitMetalHeight"], W["RecruitMetalX"]
        self.flip(W["SpriteRecruitHeaderMetal"], w / 2 + mx - mw / 2, hy - mh / 2, mw, mh, False, False)
        self.flip(W["SpriteRecruitHeaderMetal"], w / 2 - mx - mw / 2, hy - mh / 2, mw, mh, True, False)
        cv.centered(W["SpriteRecruitDecorHeader"], w / 2, W["RecruitDecorHeaderHeight"] / 2 - W["RecruitFrameInset"], W["RecruitDecorHeaderWidth"], W["RecruitDecorHeaderHeight"])
        self.text(P["FontBook"], P["SizeSubHeader"], "Elemental Fusion", w / 2 - W["RecruitTitleWidth"] / 2, 0, W["RecruitTitleWidth"], W["RecruitHeaderHeight"], P["TipTitle"], "center")
        cv.image(self.icon, L["IconCenterX"] - L["IconSize"] / 2, hy - L["IconSize"] / 2, L["IconSize"], L["IconSize"], preserve=True)
        cv.centered(P["SpritePanelRing"], L["IconCenterX"], hy, L["IconRing"], L["IconRing"])

        a, b = s.inn
        plan = build_trimmed_plan(d, s.rank, s.sids, s.counts, a, b) if a >= 0 and b >= 0 else None
        ok = plan is not None and plan.Blocked is None
        blocked = plan.Blocked if plan is not None else None
        taken = [0 if s.inn[k] < 0 else ((plan.InA, plan.InB)[k] if ok else s.counts[s.inn[k]]) for k in (0, 1)]
        for i in range(MAX_SLOTS):
            self.army_slot(s, i, taken[0] if i == a else taken[1] if i == b else 0, i in (a, b))
        self.fusion_slot(s, 0, L["RecipeAX"], taken[0])
        self.centered_text("+", L["RecipePlusX"], L["RecipeRowY"], P["SizeBigNumbers"], P["TipTitle"])
        self.fusion_slot(s, 1, L["RecipeBX"], taken[1])
        self.centered_text("=", L["RecipeEqualsX"], L["RecipeRowY"], P["SizeBigNumbers"], P["TipTitle"])
        self.result_slot(plan.Pair["fused"] if plan is not None and plan.Pair is not None and plan.ValueF > 0 else None, plan.Fused if ok else 0)

        bw = W["RecruitButtonWidth"]
        bx = (w - 2 * bw - W["RecruitButtonGap"]) / 2
        by = L["ButtonY"] - W["RecruitButtonHeight"] / 2
        loss = plan.LossWarning if ok else None
        self.button("Cancel", bx, by, bw, W["SpriteRecruitButton"], W["SpriteRecruitButtonHover"], True, s)
        self.button("Confirm" if s.confirm and loss else "Fuse", bx + bw + W["RecruitButtonGap"], by, bw, W["SpriteRecruitButton"], W["SpriteRecruitButtonHover"], ok, s)
        # Tick: an ineligible card's hint (TipNote), else a Fuse refusal / the block reason (TipWarn), else nothing.
        line = self.hint or s.status or blocked or loss or ""
        inset = W["RecruitTextInset"]
        self.text(P["FontMedium"], P["SizeSmall"], line, inset, L["StatusY"], w - 2 * inset, W["RecruitLineHeight"], P["TipNote"] if self.hint else P["TipWarn"], "center")
        if s.drag:
            self.ghost(*s.drag[:2])
        return plan

    def centered_text(self, text, cx, cy, size, color):
        g = self.L["GlyphBox"]
        self.text(self.P["FontBook"], size, text, cx - g / 2, cy - g / 2, g, g, color, "center")

    def card(self, sid, cx, cy, count, frame, tint=None, count_color=None):
        P, W, cv = self.P, self.W, self.cv
        cv.centered(frame, cx, cy, W["RecruitCardWidth"], W["RecruitCardHeight"], tint)
        self.portrait(sid, cx, cy, tint)
        cv.centered(W["SpriteRecruitCountOverlay"], cx, cy + W["RecruitCountOffset"], W["RecruitCountWidth"], W["RecruitCountHeight"], tint)
        self.text(P["FontMedium"], P["SizeMain"], n0(count), cx - W["RecruitSlotWidth"] / 2, cy + W["RecruitAmountOffset"] - W["RecruitLineHeight"] / 2,
                  W["RecruitSlotWidth"], W["RecruitLineHeight"], count_color or P["TipTitle"], "center")

    def army_slot(self, s: State, i, taken, in_fusion):
        P, W, L, cv, d = self.P, self.W, self.L, self.cv, self.d
        cx, cy = W["RecruitSlotFirstX"] + i * W["RecruitSlotPitch"], L["ArmyRowY"]
        cv.centered(W["SpriteRecruitSlotBack"], cx, cy, W["RecruitSlotBackWidth"], W["RecruitSlotBackHeight"])
        sid = s.sids[i]
        left = 0 if sid is None else s.counts[i] - taken
        if left <= 0:
            cv.centered(W["SpriteRecruitSlotEmpty"], cx, cy, W["RecruitSlotBackWidth"], W["RecruitSlotBackHeight"])
            return
        block = eligibility_block(d, s.rank, sid)
        tint = L["IneligibleTint"] if block is not None else None
        self.card(sid, cx, cy, left, W["SpriteRecruitCard"], tint, P["ButtonTextDisabled"] if block is not None else None)
        if s.hover == ("card", i) and not s.drag:
            if block is None and not in_fusion:
                cv.centered(W["SpriteRecruitCardHover"], cx, cy, W["RecruitCardWidth"], W["RecruitCardHeight"])
            if block is not None:
                self.hint = f"{d.unit_name(sid)}: {block}"

    def fusion_slot(self, s: State, which, cx, count):
        W, L, cv = self.W, self.L, self.cv
        cy = L["RecipeRowY"]
        cv.centered(W["SpriteRecruitSlotBack"], cx, cy, W["RecruitSlotBackWidth"], W["RecruitSlotBackHeight"])
        slot = s.inn[which]
        lit = (s.drag and s.drag[2] == which) or (s.hover == ("fusion", which) and slot >= 0)
        if slot < 0:
            cv.centered(W["SpriteRecruitSlotEmpty"], cx, cy, W["RecruitSlotBackWidth"], W["RecruitSlotBackHeight"])
            if lit:
                cv.centered(W["SpriteRecruitSlotEmptyHover"], cx, cy, W["RecruitSlotBackWidth"], W["RecruitSlotBackHeight"])
            return
        self.card(s.sids[slot], cx, cy, count, W["SpriteRecruitCardSelected"])
        if lit:
            cv.centered(W["SpriteRecruitCardHover"], cx, cy, W["RecruitCardWidth"], W["RecruitCardHeight"])

    def result_slot(self, sid, count):
        P, W, L, cv = self.P, self.W, self.L, self.cv
        cx, cy = L["RecipeFusedX"], L["RecipeRowY"]
        cv.centered(W["SpriteRecruitSlotBack"], cx, cy, W["RecruitSlotBackWidth"], W["RecruitSlotBackHeight"])
        if sid is None:
            cv.centered(W["SpriteRecruitSlotEmpty"], cx, cy, W["RecruitSlotBackWidth"], W["RecruitSlotBackHeight"])
            return
        self.card(sid, cx, cy, count, W["SpriteRecruitCard"], None, P["TipTitle"] if count > 0 else P["CostBad"])

    def ghost(self, sid, at):
        """Mirror of Homm3DungeonWarCaptivesWindow.NewDragGhost: selected card + aspect-kept portrait at 85% alpha."""
        W, cv = self.W, self.cv
        x, y = at
        layer = (255, 255, 255, round(255 * 0.85))
        cv.centered(W["SpriteRecruitCardSelected"], x, y, W["RecruitCardWidth"], W["RecruitCardHeight"], layer)
        im = self.portraits.get(sid)
        if im is not None:
            cv.image(im, x - W["RecruitPortraitWidth"] / 2, y - W["RecruitPortraitHeight"] / 2, W["RecruitPortraitWidth"], W["RecruitPortraitHeight"], layer, preserve=True)

    def button(self, label, x, y, bw, normal, hover, enabled, s: State):
        """Mirror of AddButton."""
        P, W, cv = self.P, self.W, self.cv
        bh = W["RecruitButtonHeight"]
        cv.sprite(W["SpriteRecruitButtonBase"], x, y, bw, bh)
        name = (hover if s.hover == ("button", label) and not s.drag else normal) if enabled else W["SpriteRecruitButtonDisabled"]
        cv.sliced(name, x, y, bw, bh, W["RecruitButtonSliceMultiplier"])
        self.text(P["FontBook"], P["SizeSubHeader"], label, x, y, bw, bh, P["ButtonText"] if enabled else P["ButtonTextDisabled"], "center")


def self_test(d: Data):
    """BestInputs against brute force on small stacks (every pair value combination in the config)."""
    vals = sorted({d.values[s] for s in d.line_by_unit if s in d.values})[:6]
    fv = sorted({d.values.get(p["fused"], 0) for p in d.cfg["pairs"]} - {0})[:4]
    for vA in vals:
        for vB in vals:
            for vF in fv:
                for nA in (1, 3, 7, 12):
                    for nB in (1, 2, 9, 15):
                        got = best_inputs(nA, vA, nB, vB, vF, d.penalty, d.min_share)
                        best, key = None, None
                        for tA in range(1, nA + 1):
                            for tB in range(1, nB + 1):
                                if not shares_ok(tA, vA, tB, vB, d.min_share)[0]:
                                    continue
                                f = fused_count(tA, vA, tB, vB, vF, d.penalty)
                                if f < 1:
                                    continue
                                k = (-f, tA * vA + tB * vB, tA)
                                if key is None or k < key:
                                    best, key = (tA, tB), k
                        assert got == best, (nA, vA, nB, vB, vF, got, best)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=Path("V:/olden_port_work/elemental_fusion/mockup_native_v2"))
    ap.add_argument("--assets", type=Path, default=Path("V:/olden_port_work/elemental_fusion/mockup_native/assets"),
                    help="native sprite/font export cache (re-exported from the installed game when missing)")
    args = ap.parse_args()
    out: Path = args.out
    out.mkdir(parents=True, exist_ok=True)
    P = pm.layout()
    W = meter.parse_class(WINDOW_CS, "internal static class Homm3DungeonWarCaptivesWindowLayout")
    L = meter.parse_class(PANEL_CS, "internal static class Homm3ConfluxFusionPanelLayout")
    d = Data()
    self_test(d)
    assets = args.assets
    pm.SPRITE_FILES = tuple(pm.SPRITE_FILES) + tuple(f for f in ("sharedassets3.assets", "sharedassets6.assets") if f not in pm.SPRITE_FILES)
    sprite_names = list(dict.fromkeys(list(W["RecruitSprites"]) + [P["SpritePanelRing"], P["SpriteTierBadge"]]))
    meta = pm.export(assets, sprite_names, [])
    spr = {n: Image.open(assets / m["file"]).convert("RGBA") for n, m in meta.items() if n in sprite_names}
    sep = meta[W["SpriteRecruitSeparator"]]
    half = spr[W["SpriteRecruitSeparator"]].height / 2
    sep["border"] = [sep["border"][0], min(sep["border"][1], half), sep["border"][2], min(sep["border"][3], half)]
    portraits = {p.stem: Image.open(p).convert("RGBA") for p in PORTRAITS.glob("h3_*.png") if re.match(r"h3_(fusion_|\w+_elemental|pixie|firebird)", p.stem)}
    fonts = {f: pm.Font(assets, f) for f in pm.FONTS}
    icon = Image.open(SKILL_ICON).convert("RGBA")
    bg = Image.open(pm.MAP_SHOT) if pm.MAP_SHOT.is_file() else Image.new("RGBA", (1920, 1080), (30, 34, 40, 255))
    shots = []

    def shot(fname, state, lines):
        cv = pm.Canvas(P, spr, meta, fonts, bg)
        plan = Panel(P, W, L, cv, d, portraits, icon).render(state)
        meter.caption(cv.img, lines, size=15).save(out / fname)
        shots.append(fname)
        return plan

    v = d.values
    # Expert Conflux, a mixed army: Pixie and Firebird are not elementals (greyed, hover says why).
    army = [("h3_pixie", 30), ("h3_air_elemental", 40), ("h3_water_elemental", 12), ("h3_fire_elemental", 9), ("h3_earth_elemental", 7), ("h3_psychic_elemental", 6), ("h3_firebird", 2)]
    shot("fusion_v2_a_empty.png", State(3, army, hover=("card", 0)), [
        "ELEMENTAL FUSION v2 (1920x1080 reference), empty: only the army row, two fusion slots, the result slot and Cancel / Fuse. No rules or maths text, no steppers, no Auto-trim.",
        "Hovering a greyed card (Pixie: not an elemental) is the only time the status line speaks before a fusion; Fuse sits on the native locked plate until both slots hold a stack.",
    ])
    # (b) Air already in A; Psychic being dragged from the army onto B (B lit as the drop target).
    gx, gy = L["RecipeBX"] + 22, L["RecipeRowY"] - 26  # cursor just inside slot B, about to release
    shot("fusion_v2_b_dragging.png", State(3, army, a=1, drag=("h3_psychic_elemental", (gx, gy), 1)), [
        "Dragging: 40 Air Elemental already sit in slot A (their army slot is empty: the whole stack is in until the second parent is known). The Psychic Elemental stack is being dragged",
        "from the army (native drag ghost, as in the War Captives recruit panel) onto slot B, which lights up with the native slot hover. Release over a slot puts the stack in; dragging a",
        "filled slot onto the other swaps them, anywhere else takes it back out. Clicks do nothing.",
    ])
    # (c) Both in: always-trimmed result, surplus stays in the army.
    sc = State(3, army, a=1, b=5, hover=("button", "Fuse"))
    pc = build_trimmed_plan(d, 3, sc.sids, sc.counts, 1, 5)
    assert pc.Blocked is None, pc.Blocked
    whole = fused_count(40, v["h3_air_elemental"], 6, v["h3_psychic_elemental"], pc.ValueF, d.penalty)
    kept = " and ".join(f"{n} {name}" for n, name in ((40 - pc.InA, "Air"), (6 - pc.InB, "Psychic")) if n > 0) or "nothing"
    shot("fusion_v2_c_filled.png", sc, [
        f"Both slots filled: trim is always on, so the slots show what goes in ({pc.InA} Air + {pc.InB} Psychic) and the army row keeps the surplus ({kept}).",
        f"Result: {pc.Fused} {d.fused_name(pc.Pair)} = floor(90% x ({pc.InA} x {v['h3_air_elemental']} + {pc.InB} x {v['h3_psychic_elemental']}) / {pc.ValueF}); the whole stacks would make {whole}.",
        "Fuse (native button, hovered) writes it; Cancel / Esc close and refund. A blocked pair shows only its one-line reason above the buttons.",
    ])
    # (d/e) Full army (7 stacks), both parents leave a surplus: the weaker leftover is dropped after a confirm.
    full = [("h3_pixie", 30), ("h3_air_elemental", 60), ("h3_water_elemental", 12), ("h3_fire_elemental", 9), ("h3_earth_elemental", 7), ("h3_psychic_elemental", 12), ("h3_firebird", 2)]
    sd = State(3, full, a=1, b=5, hover=("button", "Fuse"))
    pd = build_trimmed_plan(d, 3, sd.sids, sd.counts, 1, 5)
    assert pd.Blocked is None and pd.LostCount > 0, (pd.Blocked, pd.LostCount)
    shot("fusion_v2_d_full_warning.png", sd, [
        f"Army full (7 stacks) and both parents leave a surplus ({60 - pd.InA} Air, {12 - pd.InB} Psychic): no slot for the {d.fused_name(pd.Pair)}. No retry, no block:",
        f"the weaker leftover (less squad value) gives up its slot, and the status line names it before anything happens. Fuse is still the normal button.",
    ])
    shot("fusion_v2_e_confirm.png", State(3, full, a=1, b=5, hover=("button", "Confirm"), confirm=True), [
        "After pressing Fuse: the buttons become Cancel / Confirm. Cancel (or Esc) backs out to the normal Cancel / Fuse state and nothing is lost;",
        f"Confirm fuses: {pd.Fused} {d.fused_name(pd.Pair)} take the freed slot and the {pd.LostCount} leftover {d.unit_name(pd.LostSid)} are lost (named again in the result banner).",
    ])
    print(f"{len(shots)} mockups -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
