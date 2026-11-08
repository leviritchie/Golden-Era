"""Render approval mockups of the shared hero-skill meter (Dungeon Captives, Fortress Hunting Grounds) next to the
vanilla necromancy meter, without launching the game.

Single sources of truth (nothing is re-typed here):
  * meter geometry / stacking / tick style: parsed from Homm3HeroSkillMeterLayout in
    Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/Homm3HeroSkillMeterHud.cs
    (values copied there from level12 CanvasHeroHUDPanel / HERO VIEW HUD / ContainerEnergy)
  * per-skill icon / fill colour / tooltip colours: Layout classes in Homm3DungeonCaptivesHud.cs and
    Homm3FortressHuntingGroundsMeter.cs; Fortress milestones parsed from the C# table and asserted equal to
    HOMM3_FORTRESS_HUNTING_GROUNDS_MILESTONES / CAPS in tools/release_port/apply_release_core_overlay.py
  * Captives numbers: Homm3DungeonCaptivesRuntime.cs; text: Python mirrors of the C# tooltip builders
  * sprites: the vanilla meter's own sprites (housing HUD_DownBar_Frame_HeroPortret_Back_WithEnergy, fill
    ProgressBar_FractionEnergi, skull Icon_Stats_Necromancy_Activ), the tooltip plate littlr_tooltip 2 and the
    vanilla necromancer portrait, exported read-only from the installed game (UnityPy); fill recoloured exactly
    like the runtime (luminance / max luminance, then multiply by the skill colour)
  * font: Amrys EN-Regular SDF (shared with tools/homm3_dungeon_captives_ui_mockup v2 renderer, inlined here)
  * capture: V:/olden_port_work/run4_s10.png (1280x720 adventure map, Dungeon hero); the native 1920x1080 canvas
    is scaled by 2/3

    python tools/homm3_hero_skill_meter_mockup.py [--out V:/tmp/ui_meter_v3]
"""
from __future__ import annotations

import argparse
import json
import re
import struct
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
MOD = ROOT / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod"
METER_CS = MOD / "Homm3HeroSkillMeterHud.cs"
CAPTIVES_CS = MOD / "Homm3DungeonCaptivesHud.cs"
FORTRESS_CS = MOD / "Homm3FortressHuntingGroundsMeter.cs"
FORTRESS_HOOK_CS = MOD / "Homm3FortressHuntingGroundsHook.cs"
RUNTIME_CS = MOD / "Homm3DungeonCaptivesRuntime.cs"
PORTRAITS = MOD / "homm3_hero_portraits_upscaled"
SKILL_ICON_DIR = MOD / "homm3_skill_icons"
GAME_DATA = Path("V:/SteamLibrary/steamapps/common/Heroes of Might and Magic Olden Era - Golden Era/HeroesOldenEra_Data")
SPRITE_FILES = ("sharedassets4.assets", "sharedassets11.assets", "resources.assets")
FONT_FILE = "resources.assets"
FONT_PATH_ID = 568982
FONT_ATLAS_PATH_ID = 11159
MAP_SHOT = Path("V:/olden_port_work/run4_s10.png")
CAPTION_FONT = Path("C:/Windows/Fonts/segoeui.ttf")

V_BACK, V_FILL, V_ICON = "HUD_DownBar_Frame_HeroPortret_Back_WithEnergy", "ProgressBar_FractionEnergi", "Icon_Stats_Necromancy_Activ"
V_PORTRAIT, PLATE, SEPARATOR = "hero_necromancer_2_king_of_kings", "littlr_tooltip 2", "tooltip_separate_string"

S = 720.0 / 1080.0
HERO_VIEW = (437.0 - 61.6 * S, 630.6 + 47.7 * S)  # heroView centre on MAP_SHOT (from the v2 calibration)
MAP_PORTRAIT = ((402, 661), 41)
MAP_LEVEL_BADGE = (399, 702, 15)
SS = 4


# ----------------------------------------------------------------------------------------- sources
def parse_class(path: Path, marker: str) -> dict:
    text = path.read_text(encoding="utf-8")
    src = text[text.index(marker):]
    end = src.find("\n}\n") if marker.startswith("internal static class Homm3") else src.find("\n\t}\n")
    src = src[: end if end > 0 else len(src)]
    out: dict = {}
    for m in re.finditer(r"const float (\w+) = (-?[\d.]+)f;", src):
        out[m.group(1)] = float(m.group(2))
    for m in re.finditer(r"const (?:int|byte) (\w+) = (\d+);", src):
        out[m.group(1)] = int(m.group(2))
    for m in re.finditer(r'const string (\w+) = "([^"]*)";', src):
        out[m.group(1)] = m.group(2)
    for m in re.finditer(r"Color (\w+) = new\(([^)]*)\);", src):
        out[m.group(1)] = tuple(int(round(float(v.strip().rstrip("f")) * 255)) for v in m.group(2).split(","))
    for m in re.finditer(r"string\[\] (\w+) = \{([^}]*)\};", src):
        out[m.group(1)] = [v.strip().strip('"') for v in m.group(2).split(",")]
    return out


def parse_fortress_milestones() -> tuple[dict, dict]:
    text = FORTRESS_CS.read_text(encoding="utf-8")
    block = text[text.index("int[][][] Milestones"):]
    block = block[: block.index("};")]
    levels = re.findall(r"new\[\] \{((?: ?new\[\] \{ [\d, ]+ \},?)+) \}", block)
    ms = {i + 1: tuple(tuple(int(v) for v in t.split(",")) for t in re.findall(r"new\[\] \{ ([\d, ]+) \}", lv)) for i, lv in enumerate(levels)}
    caps_txt = re.search(r"CapByLevel = \{([^}]*)\}", FORTRESS_HOOK_CS.read_text(encoding="utf-8")).group(1)
    caps = {i: int(v) for i, v in enumerate(caps_txt.split(",")) if i > 0}
    sys.path.insert(0, str(ROOT / "tools" / "release_port"))
    import apply_release_core_overlay as overlay  # noqa: E402

    assert ms == {k: tuple(v) for k, v in overlay.HOMM3_FORTRESS_HUNTING_GROUNDS_MILESTONES.items()}, (ms, overlay.HOMM3_FORTRESS_HUNTING_GROUNDS_MILESTONES)
    assert caps == overlay.HOMM3_FORTRESS_HUNTING_GROUNDS_CAPS, (caps, overlay.HOMM3_FORTRESS_HUNTING_GROUNDS_CAPS)
    return ms, caps


def parse_runtime() -> dict:
    text = RUNTIME_CS.read_text(encoding="utf-8")
    arr = lambda n: [float(v) for v in re.search(n + r"\s*=\s*\{([^}]*)\}", text).group(1).split(",")]  # noqa: E731
    const = lambda n: float(re.search(n + r" = ([\d.]+);", text).group(1))  # noqa: E731
    return {"tiers": [int(v) for v in arr("TierThresholds")], "xp": arr("ExecuteXpPerStrength"), "gold": arr("RansomGoldPerStrength"),
            "slave": const("SlaveMarketsGoldMultiplier"), "mana": const("InterrogationManaPerXp"), "cells": const("DungeonCellsTierStrengthMultiplier")}


def n0(v: int) -> str:
    return f"{v:,}"


def captives(rt, strength, squads, rank, interrogation=False, slave=False, cells=False) -> dict:
    """Mirror of Homm3DungeonCaptivesRuntime.BuildUiSnapshot (cumulative fill = effective / next)."""
    eff = round(strength * (rt["cells"] if cells else 1.0))
    tier = 0 if strength <= 0 else sum(1 for t in rt["tiers"] if eff >= t)
    nxt = 0 if tier >= len(rt["tiers"]) else rt["tiers"][tier]
    xp = round(strength * rt["xp"][rank - 1]) if rank > 0 else 0
    return {"Squads": squads, "Strength": strength, "Eff": eff, "Tier": tier, "Next": nxt, "Fill": 1.0 if nxt == 0 else min(1.0, eff / nxt),
            "Xp": xp, "Mana": round(xp * rt["mana"]) if rank > 0 and interrogation else 0,
            "Gold": round(strength * rt["gold"][rank - 1] * (rt["slave"] if slave else 1.0)) if rank > 0 else 0,
            "Rank": rank, "Cells": cells, "Slave": slave}


def captives_tooltip(C, s) -> str:
    """Mirror of Homm3DungeonCaptivesUi.BuildMeterTooltip."""
    h, note = C["TooltipHeadingColor"], C["TooltipNoteColor"]
    out = f"<color={h}>Captives</color>\n"
    if s["Strength"] <= 0:
        out += "No captives held. Let fleeing enemy squads go to capture them."
    else:
        out += f"{s['Squads']}{' squad, ' if s['Squads'] == 1 else ' squads, '}{n0(s['Strength'])} strength"
        if s["Cells"]:
            out += f" ({n0(s['Eff'])} with Dungeon Cells)"
    out += "\n" + (f"Tier {s['Tier']}: +{s['Tier']} Attack, +{s['Tier']} Defense" if s["Tier"] > 0 else "No tier bonus yet") + "\n"
    out += f"Next: Tier {s['Tier'] + 1} at {n0(s['Next'])} ({n0(s['Eff'])} / {n0(s['Next'])})" if s["Next"] > 0 else "Maximum tier"
    if s["Rank"] > 0 and s["Strength"] > 0:
        out += f"\n<color={h}>Cast now</color>\nExecute: +{n0(s['Xp'])} XP"
        if s["Mana"] > 0:
            out += f", +{n0(s['Mana'])} mana <color={note}>(Interrogation)</color>"
        out += f"\nRansom: +{n0(s['Gold'])} gold"
        if s["Slave"]:
            out += f" <color={note}>(Slave Markets +25%)</color>"
    return out


def penalty_text(ini, spd) -> str:
    parts = ([f"-{ini} Initiative"] if ini else []) + ([f"-{spd} Speed"] if spd else [])
    return " and ".join(parts) if parts else "no penalty yet"


def fortress(F, ms, caps, level, trophies) -> dict:
    """Mirror of Homm3FortressHuntingGroundsMeter.BuildState (penalty level = skill level here)."""
    cap = caps[level]
    n = max(0, min(trophies, cap))
    full = n >= cap
    ini = spd = 0
    for t, i, sp in ms[level]:
        if n >= t:
            ini, spd = i, sp
    h, note = F["TooltipHeadingColor"], F["TooltipNoteColor"]
    out = f"<color={h}>Hunting Grounds</color>\nTrophies: {n} / {cap}{' (full)' if full else ''}\nEnemy units in this hero's battles: {penalty_text(ini, spd)}\n"
    if full:
        out += "This week's restock: used"
    else:
        nxt = next((m for m in ms[level] if m[0] > n), None)
        if nxt and nxt[0] < cap:
            out += f"Next: {penalty_text(nxt[1], nxt[2])} at {nxt[0]}"
        elif nxt:
            out += f"Next: {penalty_text(nxt[1], nxt[2])} and the restock at {cap}"
        else:
            out += f"Next: the restock at {cap}"
        out += "\nThis week's restock: not used yet (fill the meter to restock the weekly sites you visited)"
    out += f"\n<color={note}>Win battles to add Trophies. Resets at the start of each week.</color>"
    return {"Fill": n / cap, "Ticks": [t / cap for t, _, _ in ms[level] if 0 < t < cap], "Spent": full, "Icon": F["IconKeyByLevel"][level],
            "Tooltip": out, "Label": f"L{level} {n}/{cap}" + (" restock used" if full else "")}


# ----------------------------------------------------------------------------------------- native assets
def export_assets(asset_dir: Path, names: list[str]) -> dict:
    asset_dir.mkdir(parents=True, exist_ok=True)
    meta_path = asset_dir / "sprites.json"
    meta = json.loads(meta_path.read_text()) if meta_path.is_file() else {}
    missing = [n for n in names if n not in meta]
    font_ok = (asset_dir / "amrys_en_regular_atlas.png").is_file() and (asset_dir / "amrys_en_regular.json").is_file()
    if missing or not font_ok:
        import UnityPy  # read-only loads of the installed game's asset files

        for fname in SPRITE_FILES:
            if not missing and font_ok:
                break
            env = UnityPy.load(str(GAME_DATA / fname))
            for o in env.objects:
                if missing and o.type.name == "Sprite" and o.peek_name() in missing:
                    d = o.read()
                    safe = d.m_Name.replace(" ", "_").replace("=", "_")
                    d.image.convert("RGBA").save(asset_dir / f"{safe}.png")
                    b = d.m_Border
                    meta[d.m_Name] = {"file": f"{safe}.png", "source": f"{fname}:{o.path_id}", "border": [b.x, b.y, b.z, b.w], "ppu": d.m_PixelsToUnits}
                    missing.remove(d.m_Name)
                elif not font_ok and fname == FONT_FILE and o.path_id == FONT_ATLAS_PATH_ID:
                    o.read().image.save(asset_dir / "amrys_en_regular_atlas.png")
                elif not font_ok and fname == FONT_FILE and o.path_id == FONT_PATH_ID:
                    (asset_dir / "amrys_en_regular.json").write_text(json.dumps(parse_tmp_font(o.get_raw_data())))
            font_ok = (asset_dir / "amrys_en_regular_atlas.png").is_file() and (asset_dir / "amrys_en_regular.json").is_file()
            del env
        meta_path.write_text(json.dumps(meta, indent=1))
    if missing:
        raise SystemExit(f"native sprites not found in {SPRITE_FILES}: {missing}")
    return meta


def parse_tmp_font(b: bytes) -> dict:
    nl = struct.unpack_from("<I", b, 28)[0]
    off = 32 + (nl + 3) // 4 * 4
    for _ in range(4):
        sl = struct.unpack_from("<I", b, off)[0]
        off += 4 + (sl + 3) // 4 * 4
    point_size, scale = struct.unpack_from("<ff", b, off)
    line_height, ascent, cap, mean, baseline, descent = struct.unpack_from("<6f", b, off + 12)
    glyphs, goff = {}, 420
    while True:
        v = struct.unpack_from("<I5f4ifii", b, goff)
        if v[10] != 1.0:
            break
        glyphs[v[0]] = {"w": v[1], "h": v[2], "bx": v[3], "by": v[4], "adv": v[5], "rect": v[6:10]}
        goff += 52
    count = struct.unpack_from("<I", b, goff)[0]
    chars = {}
    for i in range(count):
        _et, u, g, _s = struct.unpack_from("<IIIf", b, goff + 4 + 16 * i)
        chars[u] = g
    return {"pointSize": point_size, "scale": scale, "lineHeight": line_height, "ascent": ascent, "cap": cap, "descent": descent,
            "padding": 9, "glyphs": glyphs, "chars": chars}


class SdfFont:
    def __init__(self, asset_dir: Path):
        self.f = json.loads((asset_dir / "amrys_en_regular.json").read_text())
        self.glyphs = {int(k): v for k, v in self.f["glyphs"].items()}
        self.chars = {int(k): v for k, v in self.f["chars"].items()}
        self.alpha = Image.open(asset_dir / "amrys_en_regular_atlas.png").getchannel("A")
        self.missing: set[str] = set()

    def glyph(self, ch):
        g = self.chars.get(ord(ch))
        if g is None or g not in self.glyphs:
            self.missing.add(ch)
            return None
        return self.glyphs[g]

    def advance(self, text, size):
        k = size / self.f["pointSize"] * self.f["scale"]
        return sum((g["adv"] if (g := self.glyph(c)) else 0) * k for c in text)

    @staticmethod
    def runs(text, default):
        lines, cur, stack = [[]], default, []
        for tok in re.split(r"(<color=#[0-9A-Fa-f]{6}>|</color>|\n)", text):
            if not tok:
                continue
            if tok == "\n":
                lines.append([])
            elif tok.startswith("<color="):
                stack.append(cur)
                h = tok[8:14]
                cur = (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), 255)
            elif tok == "</color>":
                cur = stack.pop() if stack else default
            else:
                lines[-1].append((tok, cur))
        return lines

    def draw(self, img, x0, top, lines, size, px, line_h):
        k = size / self.f["pointSize"] * self.f["scale"] * px
        pad = self.f["padding"]
        for li, runs in enumerate(lines):
            pen, by = x0, top + self.f["cap"] * k + li * line_h * px
            for t, col in runs:
                for ch in t:
                    g = self.glyph(ch)
                    if not g:
                        continue
                    rx, ry, rw, rh = g["rect"]
                    if rw > 0 and rh > 0:
                        tp = self.alpha.height - (ry + rh)
                        crop = self.alpha.crop((rx - pad, tp - pad, rx + rw + pad, tp + rh + pad))
                        ow, oh = max(1, round((rw + 2 * pad) * k)), max(1, round((rh + 2 * pad) * k))
                        sdf = crop.resize((ow, oh), Image.BILINEAR)
                        gain = 2.0 * pad * k
                        cov = sdf.point(lambda a, gain=gain: int(max(0.0, min(1.0, 0.5 + (a / 255.0 - 0.5) * gain)) * col[3]))
                        layer = Image.new("RGBA", (ow, oh), col[:3] + (0,))
                        layer.putalpha(cov)
                        img.paste(layer, (round(pen + (g["bx"] - pad) * k), round(by - (g["by"] + pad) * k)), layer)
                    pen += g["adv"] * k


def wrap_rich(font, text, size, width):
    """Word-wrap TMP rich lines (runs) to width canvas units."""
    out = []
    for runs in SdfFont.runs(text, (236, 236, 236, 255)):
        line, w = [], 0.0
        for t, col in runs:
            for word in re.split(r"( )", t):
                if not word:
                    continue
                aw = font.advance(word, size)
                if w + aw > width and word != " " and line:
                    out.append(line)
                    line, w = [], 0.0
                if word == " " and not line:
                    continue
                line.append((word, col))
                w += aw
        out.append(line)
    return out


# ----------------------------------------------------------------------------------------- drawing
def tint(im, c):
    r, g, b, a = im.split()
    return Image.merge("RGBA", (r.point(lambda v: v * c[0] // 255), g.point(lambda v: v * c[1] // 255),
                                b.point(lambda v: v * c[2] // 255), a.point(lambda v: v * c[3] // 255)))


def grey_fill(native: Image.Image) -> tuple[Image.Image, list]:
    """Mirror of Homm3HeroSkillMeterHud.GreyFillSprite: luminance / max opaque luminance; opaque row spans (y down)."""
    px = native.load()
    w, h = native.size
    thr = 96
    lum = lambda p: 0.299 * p[0] + 0.587 * p[1] + 0.114 * p[2]  # noqa: E731
    mx = max([lum(px[x, y]) for y in range(h) for x in range(w) if px[x, y][3] > thr] + [1.0])
    out = Image.new("RGBA", (w, h))
    o = out.load()
    spans = []
    for y in range(h):
        xs = [x for x in range(w) if px[x, y][3] > thr]
        spans.append((min(xs), max(xs)) if xs else None)
        for x in range(w):
            p = px[x, y]
            v = max(0, min(255, round(lum(p) * 255 / mx)))
            o[x, y] = (v, v, v, p[3])
    return out, spans


class Meter:
    def __init__(self, L, sprites: dict):
        self.L = L
        self.back = sprites[V_BACK]
        self.fill_native = sprites[V_FILL]
        self.fill_grey, self.spans = grey_fill(self.fill_native)

    def render(self, img, px, cx, cy, fill, color=None, icon=None, ticks=(), spent=False, slot=0, icon_dim=None):
        """Draw onto img; (cx, cy) = heroView centre in img pixels; px = img pixels per canvas unit; y up in layout."""
        L = self.L
        ox = slot * L["StackOffsetX"]

        def rect(x, y, w, h):
            return (cx + (x + ox - w / 2) * px, cy - (y + h / 2) * px, w * px, h * px)

        def put(im, r):
            x, y, w, h = r
            img.alpha_composite(im.resize((max(1, round(w)), max(1, round(h))), Image.LANCZOS), (round(x), round(y)))

        put(self.back, rect(L["BackX"], L["BackY"], L["BackWidth"], L["BackHeight"]))
        fr = rect(L["FillX"], L["FillY"], L["FillWidth"], L["FillHeight"])
        src = self.fill_native if color is None else tint(self.fill_grey, color)
        f = src.resize((max(1, round(fr[2])), max(1, round(fr[3]))), Image.LANCZOS)
        keep = round(f.height * max(0.0, min(1.0, fill)))  # Filled, Vertical, origin Bottom
        if keep > 0:
            f = f.crop((0, f.height - keep, f.width, f.height))
            img.alpha_composite(f, (round(fr[0]), round(fr[1] + fr[3] - keep)))
        d = ImageDraw.Draw(img)
        rows = len(self.spans)
        for t in ticks:
            row = rows - 1 - round(t * (rows - 1))  # PNG rows are top-down; fraction is bottom-up
            sp = self.spans[max(0, min(rows - 1, row))]
            if not sp:
                continue
            sx = L["FillWidth"] / self.fill_native.width
            left, right = sp[0] * sx - L["TickOverhang"], (sp[1] + 1) * sx + L["TickOverhang"]
            x0 = fr[0] + left * px
            yc = fr[1] + fr[3] - t * fr[3]
            d.rectangle([x0, yc - L["TickThickness"] * px / 2, x0 + (right - left) * px, yc + L["TickThickness"] * px / 2], fill=L["TickColor"])
        if icon is not None:
            ir = rect(L["IconX"], L["IconY"], L["IconSize"], L["IconSize"])
            ic = icon.resize((max(1, round(ir[2])), max(1, round(ir[3]))), Image.LANCZOS)
            if spent or icon_dim:
                ic = tint(ic, L["SpentIconColor"])
            img.alpha_composite(ic, (round(ir[0]), round(ir[1])))
        x, y, w, h = rect(L["BackX"], L["BackY"], L["BackWidth"], L["BackHeight"])
        return (x, y, x + w, y + h)


def tooltip(font, plate_sprites, text, px):
    """Native single-text BhTooltips look: littlr_tooltip 2 plate (sliced), Amrys body; inner padding approximate."""
    width, size, pad = 330.0, 15.0, 20.0
    lines = wrap_rich(font, text, size, width - 2 * pad)
    lh = font.f["lineHeight"] * size / font.f["pointSize"] * 0.85
    height = 2 * pad + lh * len(lines) - 4
    img = Image.new("RGBA", (round(width * px), round(height * px)), (0, 0, 0, 0))
    sliced(img, plate_sprites, (0, 0, width * px, height * px), px)
    font.draw(img, pad * px, (pad - 3) * px, lines, size, px, lh)
    return img


def sliced(dst, sp, rect, px):
    im, m = sp["img"], sp["meta"]
    l, b, r, t = m["border"]
    unit = m["ppu"] / 100.0 * 3.0  # pixelsPerUnitMultiplier 3 (v2 calibration of the native tooltip plate)
    x, y, w, h = rect
    dl, dr, dt, db = (v / unit * px for v in (l, r, t, b))
    sx, sy = [0, l, im.width - r, im.width], [0, t, im.height - b, im.height]
    dx, dy = [x, x + dl, x + w - dr, x + w], [y, y + dt, y + h - db, y + h]
    for i in range(3):
        for j in range(3):
            piece = im.crop((round(sx[i]), round(sy[j]), round(sx[i + 1]), round(sy[j + 1])))
            tw, th = round(dx[i + 1]) - round(dx[i]), round(dy[j + 1]) - round(dy[j])
            if tw > 0 and th > 0 and piece.width > 0 and piece.height > 0:
                dst.alpha_composite(piece.resize((tw, th), Image.LANCZOS), (round(dx[i]), round(dy[j])))


def circle_paste(base, src, center, radius):
    size = radius * 2
    art = src.resize((size, size), Image.LANCZOS)
    mask = Image.new("L", (size * 4, size * 4), 0)
    ImageDraw.Draw(mask).ellipse([0, 0, size * 4 - 1, size * 4 - 1], fill=255)
    mask = mask.resize((size, size), Image.LANCZOS)
    art.putalpha(Image.composite(art.getchannel("A"), Image.new("L", (size, size), 0), mask))
    base.alpha_composite(art, (int(center[0] - radius), int(center[1] - radius)))


def portrait_crop(im: Image.Image) -> Image.Image:
    """Square head crop (the native PORTRAIT rect is 143.7x162.5, taller than the ring; keep the top)."""
    s = min(im.width, im.height)
    return im.crop(((im.width - s) // 2, 0, (im.width - s) // 2 + s, s))


def base_with(portrait: Image.Image) -> Image.Image:
    img = Image.open(MAP_SHOT).convert("RGBA")
    native = img.copy()
    circle_paste(img, portrait_crop(portrait), *MAP_PORTRAIT)
    bx, by, br = MAP_LEVEL_BADGE
    mask = Image.new("L", img.size, 0)
    ImageDraw.Draw(mask).ellipse([bx - br, by - br, bx + br, by + br], fill=255)
    return Image.composite(native, img, mask)


def caption(img, lines, size=13):
    f = ImageFont.truetype(str(CAPTION_FONT), size)
    lh = size + 4
    out = Image.new("RGBA", (img.width, img.height + 16 + lh * len(lines)), (16, 16, 20, 255))
    out.alpha_composite(img, (0, 0))
    d = ImageDraw.Draw(out)
    for i, line in enumerate(lines):
        d.text((8, img.height + 8 + i * lh), line, font=f, fill=(210, 210, 210, 255))
    return out


def label(img, text, xy, size=15):
    ImageDraw.Draw(img).text(xy, text, font=ImageFont.truetype(str(CAPTION_FONT), size), fill=(255, 255, 255, 255), stroke_width=2, stroke_fill=(0, 0, 0, 255))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=Path("V:/tmp/ui_meter_v3"))
    args = ap.parse_args()
    out: Path = args.out
    out.mkdir(parents=True, exist_ok=True)
    L = parse_class(METER_CS, "internal static class Homm3HeroSkillMeterLayout")
    C = parse_class(CAPTIVES_CS, "internal static class Layout")
    F = parse_class(FORTRESS_CS, "internal static class Layout")
    ms, caps = parse_fortress_milestones()
    rt = parse_runtime()
    meta = export_assets(out / "assets", [V_BACK, V_FILL, V_ICON, V_PORTRAIT, PLATE, SEPARATOR])
    spr = {n: Image.open(out / "assets" / m["file"]).convert("RGBA") for n, m in meta.items()}
    plate = {"img": spr[PLATE], "meta": meta[PLATE]}
    font = SdfFont(out / "assets")
    meter = Meter(L, spr)
    icon = lambda key: Image.open(SKILL_ICON_DIR / f"{key}.png").convert("RGBA")  # noqa: E731
    p_dungeon = Image.open(PORTRAITS / "homm3_dungeon_hero_15.png").convert("RGBA")
    p_fortress = Image.open(PORTRAITS / "homm3_fortress_hero_1.png").convert("RGBA")
    p_necro = spr[V_PORTRAIT]
    cx, cy = HERO_VIEW

    def scene(portrait, draws, px=S):
        """draws: list of kwargs for Meter.render at 720p (rendered at SS x then downsampled)."""
        base = base_with(portrait)
        hi = Image.new("RGBA", (base.width * SS, base.height * SS), (0, 0, 0, 0))
        rects = [meter.render(hi, px * SS, cx * SS, cy * SS, **d) for d in draws]
        base.alpha_composite(hi.resize(base.size, Image.LANCZOS))
        return base, [tuple(v / SS for v in r) for r in rects]

    def zoom(img, box, k=3):
        c = img.crop(tuple(round(v) for v in box))
        return c.resize((c.width * k, c.height * k), Image.LANCZOS)

    def with_tip(img, rect, text):
        t_hi = tooltip(font, plate, text, S * SS)
        t = t_hi.resize((t_hi.width // SS, t_hi.height // SS), Image.LANCZOS)
        x = max(6, round(rect[0]) - t.width - 4)  # ESnapDirection.Left of the meter rect, clamped on screen
        y = max(6, min(img.height - t.height - 6, round((rect[1] + rect[3]) / 2 - t.height / 2)))
        img.alpha_composite(t, (x, y))
        return img, (x, y, x + t.width, y + t.height)

    cap_main = captives(rt, 7400, 3, 2, interrogation=True)
    fort_main = fortress(F, ms, caps, 2, 4)
    vanilla = dict(fill=0.62, color=None, icon=spr[V_ICON])
    zoom_box = (250, 545, 520, 720)

    # 01 vanilla reference: necromancer portrait + the vanilla meter rendered from its own prefab sprites/rects.
    img, r = scene(p_necro, [vanilla])
    caption(img, [
        "VANILLA REFERENCE: necromancy meter (BhFrameEnergyHero, level12 CanvasHeroHUDPanel / HERO VIEW HUD / ContainerEnergy) rendered from its own sprites and rects at true size, 1280x720.",
        "No live Necropolis capture exists: background = real capture run4_s10.png; portrait = vanilla hero_necromancer_2_king_of_kings in the native ring. Fill = Necromantic Energy (Filled, Vertical, Bottom).",
        "Vanilla hover: native BhTooltips single-text tooltip snapped Left (Necromantic Energy + mode + '(Shift) for raising info'); the skull socket is a button toggling Raising Undead / Restoring Energy.",
    ]).save(out / "01_vanilla_necromancy_meter_reference_720p.png")
    zv = zoom(img, zoom_box)

    # 02 Captives on the Dungeon hero.
    cap_draw = lambda s, slot=0: dict(fill=s["Fill"], color=C["FillColor"], icon=icon(C["IconKey"]), slot=slot)  # noqa: E731
    img, r = scene(p_dungeon, [cap_draw(cap_main)])
    zc = zoom(img, zoom_box)
    caption(img, [
        f"DUNGEON CAPTIVES meter at true size: same housing/fill/socket sprites and rects as vanilla; fill recoloured {C['FillColor'][:3]}, socket icon {C['IconKey']} (also the tier buffs' icon).",
        f"State: Advanced Captives + Interrogation, 3 squads 7,400 strength: fill = 7,400 / 12,000 = {cap_main['Fill']:.2f} (cumulative, equals the hover numbers). No text on screen.",
        f"Meter rect x{r[0][0]:.0f}-{r[0][2]:.0f} y{r[0][1]:.0f}-{r[0][3]:.0f}. Background: real capture run4_s10.png, portrait HoMM3 Dungeon hero 15.",
    ]).save(out / "02_dungeon_captives_meter_720p.png")
    tip_img, tr = with_tip(img.crop((0, 0, 1280, 720)).copy(), r[0], captives_tooltip(C, cap_main))
    caption(tip_img, [
        "Captives hover at true size: native BhTooltips single-text tooltip (Method_Public_Void_String_RectTransform_ESnapDirection_Boolean_1, snap Left), the same call vanilla Show makes.",
        "Plate littlr_tooltip 2 + Amrys font as the native tooltip; the exact inner padding and the native clamp when Left would leave the screen are approximate.",
    ]).save(out / "03_dungeon_captives_hover_720p.png")

    # 04 Fortress Hunting Grounds.
    fort_draw = lambda st, slot=0: dict(fill=st["Fill"], color=F["SpentFillColor"] if st["Spent"] else F["FillColor"], icon=icon(st["Icon"]),  # noqa: E731
                                        ticks=st["Ticks"], spent=st["Spent"], slot=slot)
    img, r = scene(p_fortress, [fort_draw(fort_main)])
    zf = zoom(img, zoom_box)
    caption(img, [
        f"FORTRESS HUNTING GROUNDS meter at true size: fill = trophies / cap ({fort_main['Label']}), tick marks at the enemy-penalty milestones (Advanced: 2 and 5 of 7).",
        "Ticks span the fill crescent's opaque width at that height (read from the native fill sprite). Socket icon = skill_faction_homm3_fortress{,_2,_3} by level; the Trophies buff stays the saved state.",
        "Background: real capture run4_s10.png (no Fortress capture), portrait HoMM3 Fortress hero 1 (Bron).",
    ]).save(out / "04_fortress_hunting_grounds_meter_720p.png")
    tip_img, _ = with_tip(img.crop((0, 0, 1280, 720)).copy(), r[0], fort_main["Tooltip"])
    caption(tip_img, ["Hunting Grounds hover at true size (native single-text tooltip, snap Left): trophies, current enemy penalty, next milestone, restock status, weekly reset."]).save(
        out / "05_fortress_hunting_grounds_hover_720p.png")

    # 06 states sheet (3x zoom of true-size renders).
    tiles = [("vanilla necromancy (reference)", zv)]
    for name, s in (("Captives: none held", captives(rt, 0, 0, 2)), ("Captives: 1,300 -> tier 1 at 2,000", captives(rt, 1300, 1, 1)),
                    ("Captives: 7,400 / 12,000 (tier 2)", cap_main), ("Captives: max tier", captives(rt, 41000, 14, 3))):
        tiles.append((name, zoom(scene(p_dungeon, [cap_draw(s)])[0], zoom_box)))
    for name, st in (("Hunting Grounds: Expert 0/6", fortress(F, ms, caps, 3, 0)), ("Hunting Grounds: Basic 3/8", fortress(F, ms, caps, 1, 3)),
                     ("Hunting Grounds: Advanced 5/7", fortress(F, ms, caps, 2, 5)), ("Hunting Grounds: Expert 6/6 restock used", fortress(F, ms, caps, 3, 6))):
        tiles.append((name, zoom(scene(p_fortress, [fort_draw(st)])[0], zoom_box)))
    tw, th = tiles[0][1].size
    cols = 3
    sheet = Image.new("RGBA", (cols * (tw + 10) + 10, ((len(tiles) + cols - 1) // cols) * (th + 10) + 10), (16, 16, 20, 255))
    for i, (name, t) in enumerate(tiles):
        x, y = 10 + (i % cols) * (tw + 10), 10 + (i // cols) * (th + 10)
        sheet.alpha_composite(t, (x, y))
        label(sheet, name, (x + 10, y + 8), 20)
    caption(sheet, ["All states, 3x zoom of the true-size 720p renders (resampled, not re-rendered). Same sprites, rects and fill maths as Homm3HeroSkillMeterHud; tile 1 = vanilla."], 16).save(
        out / "06_meter_states_zoom_3x.png")

    # 07 stacking: Dungeon hero who also learned Necromancy -> vanilla stays in place, ours moves out by StackOffsetX.
    img, r = scene(p_dungeon, [vanilla, cap_draw(cap_main, slot=1)])
    zs = zoom(img, (200, 545, 520, 720))
    caption(zs, [
        "Stacking (3x): a hero showing the vanilla necromancy meter AND a mod meter. Vanilla keeps slot 0;",
        f"mod meters take the next slots, StackOffsetX {L['StackOffsetX']:.0f} canvas units each (order: Captives 10, Hunting Grounds 20).",
        f"Mod meter rect at 720p: x{r[1][0]:.0f}-{r[1][2]:.0f}. It covers part of the faction ornament left of the ring",
        "(the vanilla meter does the same at slot 0).",
    ], 16).save(out / "07_stacking_with_vanilla_meter_zoom_3x.png")

    # 08 side by side: vanilla | Captives | Hunting Grounds.
    side = Image.new("RGBA", (3 * zv.width + 40, zv.height + 10), (16, 16, 20, 255))
    for i, (name, t) in enumerate((("vanilla necromancy", zv), ("Dungeon Captives", zc), ("Fortress Hunting Grounds", zf))):
        side.alpha_composite(t, (10 + i * (zv.width + 10), 5))
        label(side, name, (20 + i * (zv.width + 10), 12), 20)
    caption(side, ["Side by side, 3x zoom of the true-size renders: same size and visual language as the vanilla meter; only the fill colour, socket icon and (Fortress) ticks differ."], 16).save(
        out / "08_side_by_side_vanilla_captives_hunting_zoom_3x.png")

    if font.missing:
        print("WARNING: glyphs missing from Amrys EN-Regular:", sorted(font.missing))
    for p in sorted(out.glob("0*.png")):
        print(p)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
