"""Render approval mockups of the native-styled Tower Artificing graft picker without launching the game.

Single sources of truth (nothing is re-typed here):
  * geometry, sprite names, fonts, sizes, colours: parsed from Homm3TowerArtificingPickerLayout in
    Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/Homm3TowerArtificingPicker.cs
    (values copied there from level11 FractionLaws and its docked law tooltip)
  * texts: Python mirrors of the picker's text builders (LineSubtitle / BookSubtitle / BlockedReason, LineName) in the same file
  * catalog (names, descriptions, tiers, cost matrix, Tower lines): custom_factions/tower_artificing/schematic_catalog.json
  * native sprites, passive icons (icons/abilities/<key>_name) and the EN-Regular / EN-Medium / EN-Book SDF fonts:
    exported read-only from the installed game with UnityPy into the output folder's assets cache
  * Tower line portraits and banner: the plugin's local homm3_portraits / homm3_runtime_assets (gitignored; looked up
    in this checkout first, then the main checkout)
  * background: V:/olden_port_work/run4_s10.png (adventure map capture) scaled to 1920x1080

    python tools/tower_artificing/picker_mockup.py [--out V:/tmp/tower_artificing_picker]
"""
from __future__ import annotations

import argparse
import codecs
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import homm3_hero_skill_meter_mockup as meter  # noqa: E402  (parse_class, parse_tmp_font, SdfFont, caption)

MOD = ROOT / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod"
PICKER_CS = MOD / "Homm3TowerArtificingPicker.cs"
ICON_HOOK_CS = MOD / "Homm3CustomUiIconHook.cs"
CATALOG = ROOT / "custom_factions" / "tower_artificing" / "schematic_catalog.json"
POLICY = ROOT / "custom_factions" / "tower_artificing" / "artificing_policy.json"
GAME_DATA = meter.GAME_DATA
SPRITE_FILES = ("sharedassets11.assets", "sharedassets4.assets", "sharedassets1.assets", "sharedassets0.assets", "resources.assets")
FONTS = {"EN-Regular": (568982, 11159), "EN-Medium": (568981, (11175, 11176)), "EN-Book": (568979, 4882)}
MAP_SHOT = Path("V:/olden_port_work/run4_s10.png")
MAIN_MOD = Path("V:/games/olden era playtest tweak/Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod")
BANNER = "homm3_runtime_assets/faction_icons/homm3_tower/H5-Wizard.png"


# ----------------------------------------------------------------------------------------- sources
def layout() -> dict:
    L = meter.parse_class(PICKER_CS, "internal static class Homm3TowerArtificingPickerLayout")
    return {k: codecs.decode(v, "unicode_escape") if isinstance(v, str) and "\\u" in v else v for k, v in L.items()}


def semantic_icons() -> dict:
    """h3_* passive name sid -> donor icon (Homm3CustomUiIconHook.ResolveStrongholdAbilitySemanticIconKey switch)."""
    import re

    text = ICON_HOOK_CS.read_text(encoding="utf-8")
    return dict(re.findall(r'"(h3_\w+_name)" => "(\w+)"', text))


def plugin_asset(rel: str) -> Path | None:
    for base in (MOD, MAIN_MOD):
        p = base / rel
        if p.is_file():
            return p
    return None


def export(asset_dir: Path, sprite_names: list[str], icon_names: list[str]) -> dict:
    """Read-only export of named sprites (+ passive icons, + 3 SDF fonts) into asset_dir; cached in sprites.json."""
    asset_dir.mkdir(parents=True, exist_ok=True)
    meta_path = asset_dir / "sprites.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.is_file() else {}
    want = [n for n in sprite_names + icon_names if n not in meta]
    fonts_missing = [f for f in FONTS if not (asset_dir / f"{f}.json").is_file()]
    if want or fonts_missing:
        import UnityPy

        icons = set(icon_names)
        for fname in SPRITE_FILES:
            env = UnityPy.load(str(GAME_DATA / fname))
            for o in env.objects:
                if o.type.name == "Sprite":
                    try:
                        name = o.peek_name()
                    except Exception:  # noqa: BLE001
                        continue
                    if name not in want:
                        continue
                    d = o.read()
                    img = d.image.convert("RGBA")
                    if name in icons and name in meta and Image.open(asset_dir / meta[name]["file"]).width >= img.width:
                        continue  # icons exist at several sizes; keep the largest
                    safe = "".join(c if c.isalnum() or c in "_-" else "_" for c in name)
                    img.save(asset_dir / f"{safe}.png")
                    b = d.m_Border
                    meta[name] = {"file": f"{safe}.png", "source": f"{fname}:{o.path_id}", "border": [b.x, b.y, b.z, b.w], "ppu": d.m_PixelsToUnits}
                    if name not in icons:
                        want.remove(name)
                elif fname == "resources.assets" and o.type.name in ("MonoBehaviour", "Texture2D"):
                    for font, (fid, atlas) in FONTS.items():
                        if font not in fonts_missing:
                            continue
                        if o.type.name == "MonoBehaviour" and o.path_id == fid:
                            (asset_dir / f"{font}.json").write_text(json.dumps(parse_font(o.get_raw_data())))
                        atlases = atlas if isinstance(atlas, tuple) else (atlas,)
                        if o.type.name == "Texture2D" and o.path_id in atlases:
                            o.read().image.save(asset_dir / f"{font}_atlas_{o.path_id}.png")
            del env
        meta_path.write_text(json.dumps(meta, indent=1, ensure_ascii=False), encoding="utf-8")
    missing = [n for n in sprite_names if n not in meta]
    if missing:
        raise SystemExit(f"native sprites not found in {SPRITE_FILES}: {missing}")
    return meta


def parse_font(b: bytes) -> dict:
    """meter.parse_tmp_font, but the glyph table is located by scanning (its offset depends on the asset's strings)."""
    import struct

    f = meter.parse_tmp_font(b)
    if f["glyphs"]:
        return f
    for goff in range(256, min(len(b) - 160, 4096), 4):
        recs = [struct.unpack_from("<I5f4ifii", b, goff + 52 * i) for i in range(3)]
        if all(r[10] == 1.0 and r[11] == 0 and 0 < r[8] < 512 and 0 < r[9] < 512 for r in recs[1:]) and recs[0][10] == 1.0:
            break
    else:
        raise SystemExit("TMP glyph table not found")
    glyphs = {}
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
    f.update(glyphs=glyphs, chars=chars)
    return f


class Font(meter.SdfFont):
    """SdfFont for any exported TMP font; picks the atlas whose size fits the glyph rects."""

    def __init__(self, asset_dir: Path, name: str):  # noqa: D107  (no super().__init__: different file names)
        self.f = json.loads((asset_dir / f"{name}.json").read_text())
        self.glyphs = {int(k): v for k, v in self.f["glyphs"].items()}
        self.chars = {int(k): v for k, v in self.f["chars"].items()}
        need_w = max(g["rect"][0] + g["rect"][2] for g in self.glyphs.values())
        need_h = max(g["rect"][1] + g["rect"][3] for g in self.glyphs.values())
        fits = []
        for p in sorted(asset_dir.glob(f"{name}_atlas_*.png")):
            im = Image.open(p)
            if im.width >= need_w and im.height >= need_h:
                fits.append((im.width * im.height, p))
        if not fits:
            raise SystemExit(f"no atlas fits {name}")
        self.alpha = Image.open(min(fits)[1]).getchannel("A")
        self.missing: set[str] = set()


# ----------------------------------------------------------------------------------------- drawing
class Canvas:
    def __init__(self, L, spr, meta, fonts, background: Image.Image):
        self.L, self.spr, self.meta, self.fonts = L, spr, meta, fonts
        self.img = background.convert("RGBA").resize((int(L["ReferenceWidth"]), int(L["ReferenceHeight"])), Image.LANCZOS)
        self.ox = L["ReferenceWidth"] / 2 + L["ContainerOffsetX"] - L["ContainerWidth"] / 2
        self.oy = L["ReferenceHeight"] / 2 - L["ContainerHeight"] / 2

    def rect(self, x, y, w, h, screen=False):
        return (x, y, w, h) if screen else (self.ox + x, self.oy + y, w, h)

    def image(self, im: Image.Image, x, y, w, h, color=None, screen=False, preserve=False):
        x, y, w, h = self.rect(x, y, w, h, screen)
        if preserve:  # Image.preserveAspect
            k = min(w / im.width, h / im.height)
            x, y, w, h = x + (w - im.width * k) / 2, y + (h - im.height * k) / 2, im.width * k, im.height * k
        tw, th = max(1, round(w)), max(1, round(h))
        piece = im.resize((tw, th), Image.LANCZOS)
        if color is not None:
            piece = meter.tint(piece, tuple(color))
        self.img.alpha_composite(piece, (round(x), round(y)))

    def sprite(self, name, x, y, w, h, color=None, screen=False, preserve=False):
        self.image(self.spr[name], x, y, w, h, color, screen, preserve)

    def centered(self, name, cx, cy, w, h, color=None):
        self.sprite(name, cx - w / 2, cy - h / 2, w, h, color)

    def sliced(self, name, x, y, w, h, mult=1.0, color=None):
        """uGUI Image.Type.Sliced: borders at sprite pixels / pixelsPerUnitMultiplier (reference ppu 100)."""
        im, (l, b, r, t) = self.spr[name], self.meta[name]["border"]
        unit = self.meta[name]["ppu"] / 100.0 * mult
        x, y, w, h = self.rect(x, y, w, h)
        dl, dr, dt, db = (v / unit for v in (l, r, t, b))
        sx, sy = [0, l, im.width - r, im.width], [0, t, im.height - b, im.height]
        dx, dy = [x, x + dl, x + w - dr, x + w], [y, y + dt, y + h - db, y + h]
        for i in range(3):
            for j in range(3):
                piece = im.crop((round(sx[i]), round(sy[j]), round(sx[i + 1]), round(sy[j + 1])))
                tw, th = round(dx[i + 1]) - round(dx[i]), round(dy[j + 1]) - round(dy[j])
                if tw > 0 and th > 0 and piece.width > 0 and piece.height > 0:
                    piece = piece.resize((tw, th), Image.LANCZOS)
                    if color is not None:
                        piece = meter.tint(piece, tuple(color))
                    self.img.alpha_composite(piece, (round(dx[i]), round(dy[j])))

    def text(self, font, size, text, x, y, w, h, color, align="left", valign="middle", wrap=False, screen=False):
        """TMP-like box text (no overflow beyond h for wrapped text)."""
        f = self.fonts[font]
        x, y, w, h = self.rect(x, y, w, h, screen)
        lines = wrap_plain(f, text, size, w) if wrap else text.split("\n")
        k = size / f.f["pointSize"] * f.f["scale"]
        cap = f.f["cap"] * k
        lh = size * self.L["LineSpacing"]
        max_lines = max(1, int((h - cap) // lh) + 1) if wrap else len(lines)
        if len(lines) > max_lines:
            lines = lines[:max_lines]
            lines[-1] = lines[-1].rstrip() + "\u2026"
        block = cap + lh * (len(lines) - 1)
        top = y if valign == "top" else y + (h - block) / 2 if valign == "middle" else y + h - block
        col = tuple(int(round(c * 255)) if isinstance(c, float) else c for c in color)
        for i, line in enumerate(lines):
            lw = f.advance(line, size)
            lx = x if align == "left" else x + (w - lw) / 2 if align == "center" else x + w - lw
            f.draw(self.img, lx, top + i * lh, [[(line, col)]], size, 1.0, lh)


def wrap_plain(font, text, size, width):
    out = []
    for para in text.split("\n"):
        line = ""
        for word in para.split(" "):
            cand = word if not line else line + " " + word
            if font.advance(cand, size) > width and line:
                out.append(line)
                line = word
            else:
                line = cand
        out.append(line)
    return out


def rgba(c):
    """parse_class already scales Color(...) to 0-255 ints."""
    return tuple(int(v) for v in c)


# ----------------------------------------------------------------------------------------- text mirrors
RANKS = {1: "Basic", 2: "Advanced", 3: "Expert"}


def line_name(sid: str) -> str:
    """Mirror of Homm3TowerArtificingPicker.LineName."""
    s = sid[3:] if sid.startswith("h3_") else sid
    return " ".join(w[:1].upper() + w[1:] for w in s.split("_"))


def line_subtitle(line: int, grafted: int, slots: int) -> str:
    """Mirror of LineSubtitle."""
    return f"Tier {line + 1}  \u00b7  {grafted}/{slots} grafted"


def book_subtitle(tier: int, on_line_slot: int | None) -> str:
    """Mirror of BookSubtitle."""
    return f"Tier {tier} schematic" + (f"  \u00b7  on this line, slot {on_line_slot + 1}" if on_line_slot is not None else "")


def blocked_reason(cur, pick, on_line, after) -> str | None:
    """Mirror of the picker's BlockedReason."""
    if cur == pick:
        return "Already grafted in this slot"
    if on_line is not None:
        return "Already grafted on this line"
    if after < 0:
        return "Not enough Arcane Essence"
    return None


# ----------------------------------------------------------------------------------------- scene
def render(L, cv: Canvas, cat, state, icons, portraits, banner, hover_button=False, status=None):
    sch = {s["index"]: s for s in cat["schematics"]}
    cost_m = cat["costMatrix"]
    lines = cat["towerLines"]
    rank, essence = state["rank"], state["essence"]
    policy = json.loads(POLICY.read_text(encoding="utf-8"))
    slots_unlocked = policy["graftSlotsByRank"][rank - 1]
    max_slots = max(policy["graftSlotsByRank"])
    sel_line, sel_slot, pick = state["line"], state["slot"], state["pick"]
    book = sorted(state["book"], key=lambda i: (state["tiers"][i], sch[i]["displayName"].lower()))
    W, H = L["ReferenceWidth"], L["ReferenceHeight"]

    # Block + Back + scroll.
    dim = Image.new("RGBA", (int(W), int(H)), (0, 0, 0, int(255 * L["BlockAlpha"])))
    cv.img.alpha_composite(dim)
    cv.sprite(L["SpriteBack"], (W - L["BackWidth"]) / 2, (H - L["BackHeight"]) / 2, L["BackWidth"], L["BackHeight"], screen=True)
    cv.sprite(L["SpritePaper"], L["PaperX"], L["PaperY"], L["PaperWidth"], L["PaperHeight"])
    cv.sprite(L["SpriteRollerLeft"], L["RollerLeftX"], L["RollerY"], L["RollerWidth"], L["RollerHeight"])
    cv.sprite(L["SpriteRollerRight"], L["RollerRightX"], L["RollerY"], L["RollerWidth"], L["RollerHeight"])
    cv.image(banner, L["EmblemCenterX"] - L["EmblemSize"] / 2, L["EmblemY"], L["EmblemSize"], L["EmblemSize"], preserve=True)
    ink, muted, good = rgba(L["Ink"]), rgba(L["InkMuted"]), rgba(L["InkGood"])
    cv.text(L["FontRegular"], L["SizeSubHeader"], "Tower Lines", L["LinesHeaderCenterX"] - 150, L["HeaderY"], 300, L["HeaderHeight"], ink, "center")
    cv.text(L["FontRegular"], L["SizeSubHeader"], f"Schematic Book ({len(book)})", L["BookHeaderCenterX"] - 150, L["HeaderY"], 300, L["HeaderHeight"], ink, "center")

    # Tier column.
    first = L["RowsTop"] + L["RowPitch"] / 2
    last = first + L["RowPitch"] * 6
    cv.sprite(L["SpriteTierLine"], L["TierColumnX"] - L["TierLineWidth"] / 2, first, L["TierLineWidth"], last - first)
    for line in range(7):
        cy = first + L["RowPitch"] * line
        cv.centered(L["SpriteTierBadge"], L["TierColumnX"], cy, L["TierBadgeSize"], L["TierBadgeSize"])
        cv.text(L["FontRegular"], L["SizeSubHeader"], str(line + 1), L["TierColumnX"] - 25, cy - 13, 50, 26, ink, "center")

    def cell(cx, cy, icon, size_back, size_frame, size_icon, selected=False, locked=False, contur=None):
        if selected:
            c = contur or L["CellContur"]
            cv.centered(L["SpriteCellContur"], cx, cy, c, c)
        cv.centered(L["SpriteCellBack"], cx, cy, size_back, size_back)
        if icon is not None:
            cv.image(icon, cx - size_icon / 2, cy - size_icon / 2, size_icon, size_icon)
        cv.centered(L["SpriteCellFrame"], cx, cy, size_frame, size_frame)
        if locked:
            cv.centered(L["SpriteCellLocked"], cx, cy, size_back * 1.12, size_back * 1.16, rgba(L["LockedTint"]))
            cv.centered(L["SpriteLock"], cx, cy, L["CellLockWidth"], L["CellLockHeight"])

    # Left half: Tower lines.
    for line in range(7):
        top = L["RowsTop"] + L["RowPitch"] * line
        cy = top + L["RowPitch"] / 2
        if line == sel_line:
            cv.sliced(L["SpriteRowSelected"], L["LeftX"], top + 4, L["LeftWidth"], L["RowPitch"] - 8, L["RowSliceMultiplier"])
        cell(L["PortraitCenterX"], cy, portraits[line], L["CellBack"], L["CellFrame"], L["CellIcon"])
        grafted = sum(1 for s in range(slots_unlocked) if state["grafts"][line][s] >= 0)
        cv.text(L["FontRegular"], L["SizeSubHeader"], line_name(lines[line]["baseSid"]), L["LineTextX"], cy - 26, L["LineTextWidth"], 26, ink)
        cv.text(L["FontMedium"], L["SizeSmall"], line_subtitle(line, grafted, slots_unlocked), L["LineTextX"], cy + 2, L["LineTextWidth"], 22, muted)
        for s in range(max_slots):
            sx = L["SlotCenterX"] + L["SlotPitch"] * s
            g = state["grafts"][line][s]
            cell(sx, cy, icons.get(g) if g >= 0 else None, L["CellBack"], L["CellFrame"], L["CellIcon"],
                 selected=line == sel_line and s == sel_slot, locked=s >= slots_unlocked)

    # Right half: Schematic Book.
    target_tier = sel_line + 1
    rows = L["BookRows"]
    pitch = (L["RowPitch"] * 7) / rows
    if not book:
        ch = policy["observation"]["chanceByRank"]
        cv.text(L["FontMedium"], L["SizeMain"], "The Schematic Book is empty.\n\nAt the end of every battle, each passive ability in the enemy army has a "
                f"{ch[0]} / {ch[1]} / {ch[2]}% chance (Basic / Advanced / Expert) to be learned.",
                L["BookX"] + 20, L["RowsTop"] + 40, L["BookWidth"] - 60, 200, muted, "center", "top", wrap=True)
    scroll = state.get("scroll", 0)
    for r, idx in enumerate(book[scroll:scroll + rows]):
        top = L["RowsTop"] + pitch * r
        cy = top + pitch / 2
        if idx == pick:
            cv.sliced(L["SpriteRowSelected"], L["BookX"], cy - L["BookRowHeight"] / 2, L["ScrollTrackX"] - L["BookX"] - 8, L["BookRowHeight"], L["RowSliceMultiplier"])
        cell(L["BookIconCenterX"], cy, icons.get(idx), L["BookCellBack"], L["BookCellFrame"], L["BookCellIcon"])
        on_line = next((s for s in range(slots_unlocked) if state["grafts"][sel_line][s] == idx), None)
        cv.text(L["FontRegular"], L["SizeMain"], sch[idx]["displayName"], L["BookTextX"], cy - 23, L["BookTextWidth"], 24, ink)
        cv.text(L["FontMedium"], L["SizeSmall"], book_subtitle(state["tiers"][idx], on_line), L["BookTextX"], cy + 1, L["BookTextWidth"], 20, good if on_line is not None else muted)
        cost = cost_m[state["tiers"][idx] - 1][target_tier - 1]
        px, pw, ph = L["PriceX"], L["PriceWidth"], L["PriceHeight"]
        cv.sprite(L["SpritePrice"], px, cy - ph / 2, pw, ph)
        cv.centered(L["SpriteEssence"], px + 4, cy, L["PriceIconSize"], L["PriceIconSize"])
        cv.text(L["FontRegular"], L["SizeMain"], str(cost), px + 18, cy - ph / 2, pw - 26, ph, rgba(L["CostOk"] if cost <= essence else L["CostBad"]), "right")
    if len(book) > rows:
        track_top, track_h = L["RowsTop"] + 6, pitch * rows - 12
        cv.sliced(L["SpriteScrollTrack"], L["ScrollTrackX"], track_top, L["ScrollTrackWidth"], track_h)
        frac = rows / len(book)
        hh = max(40, track_h * frac)
        hy = track_top + (track_h - hh) * (scroll / max(1, len(book) - rows))
        cv.sliced(L["SpriteScrollHandle"], L["ScrollTrackX"] + (L["ScrollTrackWidth"] - L["ScrollHandleWidth"]) / 2, hy + 4, L["ScrollHandleWidth"], hh - 8)

    # Points area.
    py = L["PointsCenterY"]
    num = str(essence)
    nw = cv.fonts[L["FontRegular"]].advance(num, L["SizeBigNumbers"]) * L["SizeBigNumbers"] / L["SizeBigNumbers"]
    total = L["PointsIconSize"] + 8 + nw
    x0 = L["EmblemCenterX"] - total / 2
    cv.centered(L["SpriteEssence"], x0 + L["PointsIconSize"] / 2, py - 10, L["PointsIconSize"], L["PointsIconSize"])
    cv.text(L["FontRegular"], L["SizeBigNumbers"], num, x0 + L["PointsIconSize"] + 8, py - 32, nw + 4, 44, ink)
    cv.text(L["FontMedium"], L["SizeSmall"], "Arcane Essence", L["EmblemCenterX"] - 100, py + 16, 200, 22, muted, "center")
    cv.text(L["FontMedium"], L["SizeHeaderBig"], state["hero"], L["EmblemCenterX"] - L["PointsSideOffset"] - L["PointsSideWidth"], py - 18, L["PointsSideWidth"], 32, ink, "right")
    cv.text(L["FontMedium"], L["SizeHeaderBig"], f"{RANKS[rank]} Artificing", L["EmblemCenterX"] + L["PointsSideOffset"], py - 18, L["PointsSideWidth"], 32, ink, "left")

    # Docked panel.
    x, y, w, h = L["PanelX"], L["PanelY"], L["PanelWidth"], L["PanelHeight"]
    hh, fh, pad = L["PanelHeaderHeight"], L["PanelFooterHeight"], L["PanelPad"]
    cv.sliced(L["SpritePanelBody"], x, y + hh - 12, w, h - hh - fh + 24, L["PanelSliceMultiplier"])
    cv.sliced(L["SpritePanelHeader"], x, y, w, hh, L["PanelSliceMultiplier"])
    cv.sliced(L["SpritePanelFooter"], x, y + h - fh, w, fh, L["PanelSliceMultiplier"])
    title, sub = "Artificing", "Choose a slot and a schematic"
    if pick is not None and pick >= 0:
        title, sub = sch[pick]["displayName"], f"Tier {state['tiers'][pick]} schematic"
    ring_cx, ring_cy = x + 16 + L["PanelRing"] / 2, y + hh / 2
    if pick is not None and pick >= 0 and icons.get(pick) is not None:
        meter.circle_paste(cv.img, icons[pick], (cv.ox + ring_cx, cv.oy + ring_cy), int(L["PanelRingIcon"] / 2))
    cv.centered(L["SpritePanelRing"], ring_cx, ring_cy, L["PanelRing"], L["PanelRing"])
    tx = x + 16 + L["PanelRing"] + 10
    tw = w - (tx - x) - pad
    tip_t, tip_b, tip_n, tip_w = rgba(L["TipTitle"]), rgba(L["TipBody"]), rgba(L["TipNote"]), rgba(L["TipWarn"])
    cv.text(L["FontBook"], L["SizeSubHeader"], title, tx, y + 12, tw, 28, tip_t)
    cv.text(L["FontMedium"], L["SizeSmall"], sub, tx, y + 40, tw, 22, tip_n)
    bx, by = x + (w - L["ButtonWidth"]) / 2, y + h - L["ButtonBottom"] - L["ButtonHeight"]
    cy = y + hh + 16
    cur = state["grafts"][sel_line][sel_slot]
    cv.text(L["FontMedium"], L["SizeSmall"], f"Target: {line_name(lines[sel_line]['baseSid'])} line, slot {sel_slot + 1}", x + pad, cy, w - 2 * pad, 22, tip_n, valign="top")
    cy += 26
    if cur >= 0 and cur != pick:
        cv.text(L["FontMedium"], L["SizeSmall"], f"Replaces {sch[cur]['displayName']} (no refund)", x + pad, cy, w - 2 * pad, 22, tip_w, valign="top")
        cy += 26
    cy += 6
    after_top = by - 150
    reason = None
    if pick is not None and pick >= 0:
        cv.text(L["FontMedium"], L["SizeSmall"], sch[pick]["description"], x + pad, cy, w - 2 * pad, after_top - cy - 12, tip_b, valign="top", wrap=True)
        cv.sprite(L["SpriteSeparator"], x + pad, after_top, w - 2 * pad, 2)
        cost = cost_m[state["tiers"][pick] - 1][target_tier - 1]
        after = essence - cost
        on_line = next((s for s in range(slots_unlocked) if state["grafts"][sel_line][s] == pick), None)
        reason = blocked_reason(cur, pick, on_line, after)
        cv.text(L["FontBook"], L["SizeMain"], "After grafting", x + pad, after_top + 12, w - 2 * pad, 26, tip_t)
        cv.text(L["FontMedium"], L["SizeSmall"], "Cost", x + pad, after_top + 46, 160, 24, tip_n)
        cv.text(L["FontRegular"], L["SizeMain"], str(cost), x + w - pad - 120, after_top + 46, 92, 24, rgba(L["CostOk"] if after >= 0 else L["CostBad"]), "right")
        cv.centered(L["SpriteEssence"], x + w - pad - 12, after_top + 58, 26, 26)
        cv.text(L["FontMedium"], L["SizeSmall"], "Essence left", x + pad, after_top + 76, 160, 24, tip_n)
        cv.text(L["FontRegular"], L["SizeMain"], str(after), x + w - pad - 160, after_top + 76, 132, 24, tip_b if after >= 0 else rgba(L["CostBad"]), "right")
        cv.centered(L["SpriteEssence"], x + w - pad - 12, after_top + 88, 26, 26)
    else:
        reason = "No schematic chosen"
    if reason is None:
        cv.sliced(L["SpriteButtonHover"] if hover_button else L["SpriteButton"], bx, by, L["ButtonWidth"], L["ButtonHeight"], L["ButtonSliceMultiplier"])
        cv.text(L["FontRegular"], L["SizeMain"], "Graft", bx, by, L["ButtonWidth"], L["ButtonHeight"], rgba(L["ButtonText"]), "center")
    else:
        cv.sliced(L["SpriteButtonDisabled"], bx, by, L["ButtonWidth"], L["ButtonHeight"], L["ButtonSliceMultiplier"])
        cv.text(L["FontRegular"], L["SizeMain"], "Graft", bx, by, L["ButtonWidth"], L["ButtonHeight"], rgba(L["ButtonTextDisabled"]), "center")
    note = status[0] if status else reason
    note_col = (rgba(L["CostOk"]) if status[1] else rgba(L["CostBad"])) if status else tip_n
    if note:
        cv.text(L["FontMedium"], L["SizeSmall"], note, x + pad, by + L["ButtonHeight"] + 8, w - 2 * pad, 40, note_col, "center", "top", wrap=True)

    # Close (screen corner).
    cs, cm = L["CloseSize"], L["CloseMargin"]
    cv.sprite(L["SpriteClose"], W - cm - cs, cm, cs, cs, screen=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=Path("V:/tmp/tower_artificing_picker"))
    args = ap.parse_args()
    out: Path = args.out
    out.mkdir(parents=True, exist_ok=True)
    L = layout()
    cat = json.loads(CATALOG.read_text(encoding="utf-8"))
    sch = {s["index"]: s for s in cat["schematics"]}
    sem = semantic_icons()
    sprite_names = [v for k, v in L.items() if k.startswith("Sprite") and isinstance(v, str)]
    icon_names = sorted({s["key"] + "_name" for s in cat["schematics"]} | set(sem.values()))
    assets = out / "assets"
    meta = export(assets, sprite_names, icon_names)
    spr = {n: Image.open(assets / m["file"]).convert("RGBA") for n, m in meta.items()}
    fonts = {f: Font(assets, f) for f in FONTS}

    def icon_for(idx):
        """Mirror of PassiveIcon: TryResolveSprite(<key>_name) (semantic h3 donors), the vanilla ability icon, the source unit."""
        name = sch[idx]["key"] + "_name"
        icon = spr.get(sem.get(name, name)) or spr.get(name)
        if icon is None:  # then the source unit's portrait (base sid first), like the runtime's SourcePortrait
            for unit in sorted((u["sid"] for u in sch[idx]["sourceUnits"]), key=len):
                p = plugin_asset(f"homm3_portraits/{unit}.png")
                if p:
                    return Image.open(p).convert("RGBA")
        return icon

    icons = {i: icon_for(i) for i in sch}
    no_icon = [sch[i]["key"] for i in sch if icons[i] is None]
    portraits = []
    for ln in cat["towerLines"]:
        p = plugin_asset(f"homm3_portraits/{ln['baseSid']}.png")
        portraits.append(Image.open(p).convert("RGBA") if p else None)
    banner_path = plugin_asset(BANNER)
    banner = Image.open(banner_path).convert("RGBA") if banner_path else Image.new("RGBA", (8, 8))
    bg = Image.open(MAP_SHOT) if MAP_SHOT.is_file() else Image.new("RGBA", (1920, 1080), (30, 34, 40, 255))

    by_name = {s["displayName"]: s["index"] for s in cat["schematics"]}
    learned = [i for i in sch if icons[i] is not None][::9][:16]
    grafts = [[-1, -1] for _ in range(7)]
    grafts[0][0] = learned[1]
    grafts[3][0] = learned[4]
    grafts[5][0] = learned[6]
    tiers = {i: sch[i]["minSourceTier"] for i in sch}
    pick = learned[9]
    base = dict(hero="Solmyr", rank=3, essence=412, line=5, slot=0, pick=pick, book=learned, tiers=tiers, grafts=grafts, scroll=0)

    shots = []

    def shot(fname, state, lines_, **kw):
        cv = Canvas(L, spr, meta, fonts, bg)
        render(L, cv, cat, state, icons, portraits, banner, **kw)
        img = meter.caption(cv.img, lines_, size=15)
        img.save(out / fname)
        shots.append(fname)

    shot("01_picker_expert_replace.png", base, [
        "ARTIFICING PICKER, native restyle (1920x1080 reference). Scroll, rollers, tier column, law cells, price pills, essence icon, close button, docked panel and button are the game's own sprites (level11 FractionLaws + its docked law tooltip).",
        "Left: Tower lines (portrait law cell, 2 graft slots at Expert). Right: Schematic Book, cost on the selected line. Panel: picked schematic, target slot, replacement warning, cost and essence after, Graft button.",
        "Text: EN-Regular / EN-Medium / EN-Book SDF fonts (the FontsAlias English styles) at native sizes. Background: adventure map capture, dimmed like the Laws window Block.",
    ])
    poor = dict(base, essence=60, rank=1, line=2, slot=0, pick=learned[12], scroll=4)
    shot("02_picker_basic_not_enough.png", poor, [
        "BASIC rank (1 slot per line: second slot shows the native law lock), Golem line selected, book scrolled (paper scrollbar), the picked schematic costs more than the essence held:",
        "costs above the essence turn red, the Graft button switches to the native disabled plate and the reason sits under it (resTip line).",
    ])
    shot("03_picker_after_graft.png", dict(base, essence=412 - 0, grafts=[g[:] for g in grafts]), [
        "Hover state of the Graft button (buttom_MouseOver) and the status line after a successful graft (TryGraft result).",
    ], hover_button=True, status=("Grafted onto the Naga line.", True))
    shot("04_picker_empty_book.png", dict(base, book=[], pick=-1, grafts=[[-1, -1] for _ in range(7)], essence=35, rank=2), [
        "Empty Schematic Book (first cast): the right half explains battle-end observation; the panel's button stays disabled.",
    ])
    (out / "report.json").write_text(json.dumps({"shots": shots, "schematicsWithoutIcon": no_icon, "fontsMissingGlyphs": {f: sorted(v.missing) for f, v in fonts.items()}}, indent=1))
    print(f"{len(shots)} mockups -> {out}; schematics without a native icon: {len(no_icon)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
