"""Render approval mockups of the Factory Logistics Network viewer (the free spell's pan/zoom map) without the game.

docs/factory_logistics_network_design.md, "Network viewer": Olden Era panel shell, neon glow for path elements only,
real map tiles (square grid, 8 neighbours), thin routes coloured by originating building, parallel offset lines where
routes share tiles, pulsing arrows, red X + red text where a route runs out of range, red glow on stacks whose defeat
would create a link, per-building Upgrade Center badges and the selected-building card (weekly switch, remote builds).

Sources:
  * shell, buttons, fonts, colours, resource/mine/building icons and the overflow check: tools/factory_logistics/upgrade_panel_mockup.py
  * close / zoom buttons: native FullSkreanExitButton, button_plus / button_minus exported read-only from the installed game
  * town banners: homm3_runtime_assets/faction_icons; hero portraits: homm3_hero_portraits; unit cards: homm3_portraits
  * map: a REAL Olden Era map region, read read-only from the installed game:
    StreamingAssets/maps/Thirst_for_Power.map, columns x 1..63, rows z 37..7 (north up), through
    tools/map_model_lens_viewer.MapModel (tilesMap biome ids, levelsMap, waterMap, roadsMap, native object footprint
    masks: 1 = blocked, 2 = entrance). The crop is cached in the assets folder (map_crop_*.npz) so the script also runs
    without the game. The adventure map is a SQUARE grid with 8 neighbours (Hex.Neighbourhood.All; "Hex" is only the
    engine namespace; feasibility.md section 7).
  * range rule (design doc "Logistics range"): 10 MP per step, x1.41 diagonal, no terrain penalty, road tiles minus
    the road bonus (Core.zip DB/map/roads/roads.json: 0.20 / 0.30); range = logistics level x 100 MP. Routes are the
    cheapest 8-direction tile paths; a route that costs more than the range is cut on the last tile it can pay for and
    its label gives the missing range in logistics levels (runtime contract: MissingRangeLevels = ceil(missing MP / 100)).
  * invented for the mockup: which real town / mine / dwelling sites the player owns and their names and enhancement
    states, the hero positions, the fog patches, and that every neutral stack but one has been defeated (the remaining
    one stands on a real random-squad tile of the map).

    python tools/factory_logistics/network_viewer_mockup.py [--out V:/olden_port_work/factory_logistics/mockups] [--frames 10]
"""
from __future__ import annotations

import argparse
import heapq
import math
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

sys.path.insert(0, str(Path(__file__).resolve().parent))
import upgrade_panel_mockup as up  # noqa: E402
from upgrade_panel_mockup import ASSETS, OUT, FitCanvas, meter, pm, rect, shell  # noqa: E402

MOD = up.MOD
FACTION = MOD / "homm3_runtime_assets" / "faction_icons"
HEROES = MOD / "homm3_hero_portraits"

# Placeholder enhancement badges (vanilla town-building icons, as in the upgrade panel).
BADGES = {"Power Station": "N_build_Resource_Silo", "Rail Station": "D_build_Resource_Depot", "Warehouse": "H_build_Resource_Depot_2",
          "Logistics Hub": "H_build_Resource_Depot", "Food Distribution Center": "H_build_Tavern", "Export Office": "H_build_Merchant",
          "Material Synthesizer": "N_build_Skeleton_Converter"}
EXTRA = ["D_build_Resource_Depot", "H_build_Resource_Depot_2", "N_build_Skeleton_Converter", "mine_ore", "mine_wood", "mine_gemstones",
         "button_plus", "button_plus_mouseover", "button_minus", "Frame_Law_Back", "tolltip_hader", "littlr_tooltip 2", "tolltip_futer", "FullSkreanExitButton", "FullSkreanExitButton_MouseOver"]

RED = (255, 70, 60)
LABEL_PLATE = (8, 12, 20, 205)


class Lay:
    Width = 1680.0
    Height = 1000.0
    MapX = 22.0
    MapY = 58.0
    Tile = 26.0
    Cols = 63
    Rows = 31
    LegendTop = 878.0
    LegendHeight = 54.0
    Marker = 52.0
    Badge = 26.0
    TownSize = 64.0
    HeroSize = 50.0
    CloseSize = 46.0
    ZoomSize = 44.0
    LabelSize = 16.0
    ChevronGap = 44.0
    ChevronSize = 5.0
    BundleGap = 9.0          # px between parallel routes sharing tiles
    PulsePeriod = 220.0      # px between pulse crests
    CardWidth = 384.0
    CardHeader = 74.0
    CardTabs = 34.0
    CardRow = 40.0
    CardRowPending = 52.0    # name + status line ("Active until end of day" / "Active tomorrow")
    CardNote = 26.0
    RemoteCardWidth = 470.0


MAP_W, MAP_H = Lay.Cols * Lay.Tile, Lay.Rows * Lay.Tile
GRID = None   # dict of (Rows, Cols) arrays, see load_map()

# ----------------------------------------------------------------------------------------- real map crop
MAP_NAME = "Thirst_for_Power"
MAP_X0, MAP_Z1 = 1, 37                      # viewport column 0 = map x 1; viewport row 0 = map z 38 (north up)
ROAD_BONUS = {0: 0.0, 1: 0.20, 2: 0.30}     # Core.zip DB/map/roads/roads.json
STEP_MP = 10.0
BUNDLE_BIAS = 0.90                          # tiles already carrying a route are this much cheaper when choosing a path
MP_PER_LEVEL = 100
# tiles.json biome per tilesMap id (Core.zip DB/map/tiles/tiles.json): strategic-view colours
BIOME_RGB = {1: (80, 108, 58),    # Grass
             2: (156, 138, 96),   # Sand
             3: (92, 84, 92),     # Deathland
             4: (150, 160, 176),  # Snow
             5: (132, 104, 56),   # Autumn
             6: (104, 58, 46),    # Lava
             7: (114, 94, 66)}    # Dirt
WATER_RGB = (40, 74, 108)
FREE, TREE, MOUNTAIN, OBJECT = range(4)
NEIGHBOURS = [(-1, -1), (0, -1), (1, -1), (-1, 0), (1, 0), (-1, 1), (0, 1), (1, 1)]


def mt(x, z):
    """Map node (x, z) -> viewport tile (col, row)."""
    return x - MAP_X0, MAP_Z1 - z


def tp(c, r):
    """Viewport tile -> window coords (tile centre)."""
    return Lay.MapX + (c + 0.5) * Lay.Tile, Lay.MapY + (r + 0.5) * Lay.Tile


def load_map(assets: Path):
    """Crop of the real map as (Rows, Cols) arrays: tile (biome id), level, water, road, block kind, passable."""
    cache = assets / f"map_crop_{MAP_NAME}_{MAP_X0}_{MAP_Z1}_{Lay.Cols}x{Lay.Rows}.npz"
    if cache.is_file():
        with np.load(cache) as z:
            return {k: z[k] for k in z.files}
    sys.path.insert(0, str(up.ROOT / "tools"))
    import map_model_lens_viewer as lv  # read-only reader of Olden .map files + native object footprints
    model = lv.MapModel(meter.GAME_DATA / "StreamingAssets" / "maps" / f"{MAP_NAME}.map", None)
    W = model.width
    roads = model.md["roadsMap"]
    g = {k: np.zeros((Lay.Rows, Lay.Cols), np.uint8) for k in ("tile", "water", "road", "block", "passable")}
    g["level"] = np.zeros((Lay.Rows, Lay.Cols), np.int8)
    for r in range(Lay.Rows):
        for c in range(Lay.Cols):
            x, zz = c + MAP_X0, MAP_Z1 - r
            n = x + zz * W
            g["tile"][r, c], g["level"][r, c] = model.tiles[n], model.levels[n]
            g["water"][r, c], g["road"][r, c] = (1 if model.water[n] else 0), roads[n]
            kind = FREE
            if n in model.blocked_nodes and n not in model.gate_nodes:
                sids = [cv["sid"] for cv in model.cover_at[n] if cv["occupied"]]
                kind = (MOUNTAIN if any("mountain" in s or "rock" in s or "ice" in s for s in sids) else
                        TREE if any("tree" in s or "pine" in s or "snag" in s or "thorn" in s for s in sids) else OBJECT)
            g["block"][r, c] = kind
            g["passable"][r, c] = 0 if (kind != FREE or model.water[n]) else 1
    assets.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(cache, **g)
    return g


# ----------------------------------------------------------------------------------------- scene (real sites, invented ownership)
TOWNS = [dict(name="Forgehold", faction="homm3_factory/Icon_Faction_Factory.png", at=mt(20, 19)),
         dict(name="Castle Town", faction="homm3_castle/Icon_Faction_Castle.png", at=mt(59, 30))]
HERO_LIST = [dict(name="Henrietta", sid="homm3_factory_hero_1", at=mt(5, 17)),
             dict(name="Sam", sid="homm3_factory_hero_2", at=mt(17, 26))]
# uc = Upgrade Center level (skill level of the best skilled hero that visited this building); None = never visited.
BUILDINGS = [
    dict(name="Crystal Mine", icon="mine_crystals", enh="Power Station", lvl=2, at=mt(29, 11), uc=2, uc_by="Henrietta",
         built=[("Power Station", 2), ("Export Office", 1), ("Logistics Hub", 2)]),
    dict(name="Ore Pit", icon="mine_ore", enh="Rail Station", lvl=1, at=mt(16, 11), hub=True, uc=1),
    dict(name="Sawmill", icon="mine_wood", enh="Warehouse", lvl=1, at=mt(9, 14), uc=1),
    dict(name="Automaton Factory", portrait="h3_automaton", enh="Food Distribution Center", lvl=2, at=mt(16, 30), uc=2),
    dict(name="Gem Pond", icon="mine_gemstones", enh="Export Office", lvl=3, at=mt(21, 30), uc=3),
    dict(name="Gold Mine", icon="mine_gold", enh="Logistics Hub", lvl=1, at=mt(52, 27), hub=True, uc=2),
    dict(name="Mechanic Workshop", portrait="h3_mechanic", enh=None, lvl=0, at=mt(15, 18), uc=None),
]
LOGISTICS_LEVEL = 1 + sum(b["lvl"] for b in BUILDINGS if b["enh"] == "Rail Station")
RANGE_MP = LOGISTICS_LEVEL * MP_PER_LEVEL
STACK = dict(name="Behemoths", portrait="h3_behemoth", at=mt(27, 10), link=("Crystal Mine", "Forgehold"))
# Routes shown (source -> target); paths, costs and cut points are computed by solve_routes().
ROUTES = [dict(src=s, dst=d) for s, d in [
    ("Crystal Mine", "Ore Pit"), ("Crystal Mine", "Forgehold"),
    ("Ore Pit", "Forgehold"), ("Ore Pit", "Sawmill"), ("Ore Pit", "Henrietta"), ("Ore Pit", "Sam"),
    ("Sawmill", "Forgehold"), ("Sawmill", "Henrietta"), ("Sawmill", "Sam"),
    ("Automaton Factory", "Sam"), ("Automaton Factory", "Henrietta"), ("Automaton Factory", "Castle Town"),
    ("Gem Pond", "Sam"), ("Gem Pond", "Castle Town"), ("Gem Pond", "Gold Mine"),
    ("Gold Mine", "Castle Town"),
]]
# Route colour = source building (colour-blind-friendly neon hues after Okabe-Ito; red is reserved for cuts / blocking stacks).
SOURCE_COLOURS = {"Crystal Mine": (40, 230, 255),         # cyan
                  "Ore Pit": (70, 120, 255),               # blue
                  "Sawmill": (40, 220, 140),              # bluish green
                  "Automaton Factory": (255, 165, 35),    # orange
                  "Gem Pond": (230, 130, 240),            # reddish purple
                  "Gold Mine": (245, 228, 70)}            # yellow
SOURCE_ORDER = list(SOURCE_COLOURS)            # fixed lateral order inside a bundle
HUB_RING = (225, 238, 255)
# Unexplored patches (viewport tiles: centre col, row, radius); never on or near routes and markers.
FOG_PATCHES = [(1, 0, 7), (44, 0, 5), (36, 26, 5), (62, 15, 4)]


def node_at(name):
    return next(o["at"] for o in TOWNS + HERO_LIST + BUILDINGS if o["name"] == name)


def guard_ring(at):
    return {(at[0] + dx, at[1] + dy) for dx, dy in NEIGHBOURS}


# ----------------------------------------------------------------------------------------- range engine (square grid, 8 neighbours)
def step_cost(t, diagonal):
    return STEP_MP * (1.0 - ROAD_BONUS[int(GRID["road"][t[1], t[0]])]) * (1.41 if diagonal else 1.0)


def find_path(start, goal, banned=frozenset(), used=frozenset()):
    """Cheapest 8-direction tile path (no corner cutting between two blocked tiles). Marker tiles are endpoints only.
    Tiles already carrying a route are slightly cheaper (BUNDLE_BIAS), so near-equal alternatives bundle; costs are true MP. Returns (tiles, cumulative MP)."""
    C, R = Lay.Cols, Lay.Rows
    passable = GRID["passable"]
    markers = {o["at"] for o in TOWNS + HERO_LIST + BUILDINGS} | {STACK["at"]}

    def ok(t):
        return 0 <= t[0] < C and 0 <= t[1] < R and passable[t[1], t[0]] and t not in banned and t not in markers

    best, prev = {start: 0.0}, {}
    q = [(0.0, start)]
    while q:
        g, cur = heapq.heappop(q)
        if cur == goal:
            break
        if g > best[cur]:
            continue
        for dx, dy in NEIGHBOURS:
            nxt = (cur[0] + dx, cur[1] + dy)
            if nxt != goal and not ok(nxt):
                continue
            if nxt in banned:
                continue
            if dx and dy and not ok((cur[0] + dx, cur[1])) and not ok((cur[0], cur[1] + dy)):
                continue
            ng = g + step_cost(nxt, dx and dy) * (BUNDLE_BIAS if nxt in used else 1.0)
            if ng < best.get(nxt, 1e18):
                best[nxt], prev[nxt] = ng, cur
                heapq.heappush(q, (ng, nxt))
    if goal not in prev:
        return None, None
    path, t = [goal], goal
    while t != start:
        t = prev[t]
        path.append(t)
    path.reverse()
    cum = [0.0]
    for a, b in zip(path, path[1:]):
        cum.append(cum[-1] + step_cost(b, a[0] != b[0] and a[1] != b[1]))
    return path, cum


def solve_routes():
    """Fills ROUTES[i] with tiles / cost / live (tiles reached) / need (missing logistics levels), and STACK['shortcut']."""
    ring = frozenset(guard_ring(STACK["at"]) | {STACK["at"]})
    used = set()
    for rt in ROUTES:
        tiles, cum = find_path(node_at(rt["src"]), node_at(rt["dst"]), ring, used)
        if tiles is None:
            raise SystemExit(f"no path {rt['src']} -> {rt['dst']}")
        rt["tiles"], rt["cost"] = tiles, cum[-1]
        k = max(i for i, c in enumerate(cum) if c <= RANGE_MP + 1e-6)
        rt["cut"] = cum[-1] > RANGE_MP
        rt["live"] = tiles[:k + 1] if rt["cut"] else tiles
        rt["need"] = math.ceil((cum[-1] - RANGE_MP) / MP_PER_LEVEL) if rt["cut"] else 0
        used.update(rt["live"])
    # the blocking stack: without its guard ring the named route must be in range, with it it is cut
    a, b = STACK["link"]
    tiles, cum = find_path(node_at(a), node_at(b), frozenset(), used)
    with_ring = next(r for r in ROUTES if r["src"] == a and r["dst"] == b)
    if not (cum[-1] <= RANGE_MP < with_ring["cost"]):
        raise SystemExit(f"blocking stack does not decide {a} -> {b}: {cum[-1]:.0f} MP without, {with_ring['cost']:.0f} with, range {RANGE_MP}")
    STACK["shortcut"], STACK["shortcut_cost"] = tiles, cum[-1]
    STACK["note"] = f"Defeat to link {a} -> {b}"


def build_fog():
    """Dark unexplored tiles: noise-edged patches, kept 3 tiles clear of every route, marker and the guard ring."""
    C, R = Lay.Cols, Lay.Rows
    rng = np.random.default_rng(7)
    noise = np.asarray(Image.fromarray((rng.random((8, 16)) * 255).astype(np.uint8), "L").resize((C, R), Image.BICUBIC), np.float32) / 255.0
    yy, xx = np.mgrid[0:R, 0:C].astype(np.float32)
    fog = np.zeros((R, C), bool)
    for cx, cy, rad in FOG_PATCHES:
        fog |= np.hypot(xx - cx, yy - cy) < rad * (0.75 + 0.5 * noise)
    keep = {o["at"] for o in TOWNS + HERO_LIST + BUILDINGS} | guard_ring(STACK["at"]) | set(STACK["shortcut"])
    for rt in ROUTES:
        keep |= set(rt["tiles"])
    clear = np.zeros((R, C), bool)
    for c, r in keep:
        clear[max(0, r - 3):r + 4, max(0, c - 3):c + 4] = True
    return fog & ~clear


def map_base() -> Image.Image:
    """The real tiles: biome colour per tile (level shading), tree / mountain / object blockers, water, road tiles
    drawn as roads, dark fog tiles, thin grid lines, red-tinted guard ring; dimmed so the neon carries the read."""
    g, fog = GRID, GRID["fog"]
    T, C, R = Lay.Tile, Lay.Cols, Lay.Rows
    w, h = int(MAP_W), int(MAP_H)
    rng = np.random.default_rng(11)
    img = Image.new("RGBA", (w, h), (0, 0, 0, 255))
    d = ImageDraw.Draw(img)
    for r in range(R):
        for c in range(C):
            x0, y0 = c * T, r * T
            if fog[r, c]:
                k = 16 + int(rng.integers(0, 6))
                d.rectangle([x0, y0, x0 + T, y0 + T], fill=(k, k + 4, k + 16, 255))
                continue
            water = bool(g["water"][r, c])
            j = (0.94 + 0.12 * rng.random()) * (1.0 + 0.07 * int(g["level"][r, c]))
            col = tuple(int(v * j) for v in (WATER_RGB if water else BIOME_RGB.get(int(g["tile"][r, c]), (110, 110, 110))))
            d.rectangle([x0, y0, x0 + T, y0 + T], fill=col + (255,))
            cx, cy = x0 + T / 2, y0 + T / 2
            kind = int(g["block"][r, c])
            dark = tuple(int(v * 0.45) for v in col) + (255,)
            if water:
                if rng.random() < 0.4:
                    d.line([(cx - 6, cy), (cx - 2, cy - 2), (cx + 2, cy), (cx + 6, cy - 2)], fill=(74, 112, 148, 255), width=1)
            elif kind == TREE:
                d.rectangle([x0, y0, x0 + T, y0 + T], fill=tuple(int(v * 0.78) for v in col) + (255,))
                for ox, oy in ((-5, 2), (4, -3), (3, 7)):
                    d.polygon([(cx + ox, cy + oy - 8), (cx + ox - 5, cy + oy + 3), (cx + ox + 5, cy + oy + 3)], fill=dark)
            elif kind == MOUNTAIN:
                d.rectangle([x0, y0, x0 + T, y0 + T], fill=tuple(int(v * 0.72) for v in col) + (255,))
                d.polygon([(cx, cy - 9), (cx - 10, cy + 8), (cx + 10, cy + 8)], fill=dark)
                d.polygon([(cx, cy - 9), (cx - 3, cy - 3), (cx + 3, cy - 3)], fill=tuple(min(255, int(v * 1.5) + 30) for v in col) + (255,))
            elif kind == OBJECT:
                d.rectangle([x0, y0, x0 + T, y0 + T], fill=tuple(int(v * 0.72) for v in col) + (255,))
                d.rectangle([cx - 5, cy - 5, cx + 5, cy + 5], fill=dark)
    # road tiles: a road band joining neighbouring road tiles through tile centres
    road = g["road"]
    for width, colr in ((9, (56, 46, 36, 255)), (5, (184, 168, 134, 255))):
        for r in range(R):
            for c in range(C):
                if not road[r, c] or fog[r, c]:
                    continue
                cx, cy = (c + 0.5) * T, (r + 0.5) * T
                d.ellipse([cx - width / 2, cy - width / 2, cx + width / 2, cy + width / 2], fill=colr)
                for dx, dy in ((1, 0), (0, 1), (1, 1), (-1, 1)):
                    nc, nr = c + dx, r + dy
                    if not (0 <= nc < C and 0 <= nr < R and road[nr, nc]) or fog[nr, nc]:
                        continue
                    if dx and dy and (road[r, nc] or road[nr, c]):
                        continue      # an orthogonal pair already joins them
                    d.line([(cx, cy), ((nc + 0.5) * T, (nr + 0.5) * T)], fill=colr, width=width)
    # guard zone: the stack tile's 8 neighbours tinted red
    over = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    od = ImageDraw.Draw(over)
    for c, r in guard_ring(STACK["at"]):
        od.rectangle([c * T + 1, r * T + 1, c * T + T - 1, r * T + T - 1], fill=(225, 40, 30, 150), outline=(255, 90, 70, 235))
    img.alpha_composite(over)
    # strategic-view dim, then thin grid lines (not over fog)
    arr = np.asarray(img, np.float32).copy()
    grey = arr[..., :3].mean(axis=2, keepdims=True)
    arr[..., :3] = (arr[..., :3] * 0.78 + grey * 0.22) * 0.62
    img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), "RGBA")
    grid = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    gd = ImageDraw.Draw(grid)
    for r in range(R):
        for c in range(C):
            if not fog[r, c]:
                gd.rectangle([c * T, r * T, c * T + T, r * T + T], outline=(0, 0, 0, 105))
    img.alpha_composite(grid)
    return img


# ----------------------------------------------------------------------------------------- neon
def poly(pts):
    return [tp(c, r) for c, r in pts]


def seg_lengths(xy):
    return [math.dist(a, b) for a, b in zip(xy, xy[1:])]


def at_length(xy, s):
    """Point and unit direction at arc length s."""
    for (a, b), L in zip(zip(xy, xy[1:]), seg_lengths(xy)):
        if s <= L or b == xy[-1]:
            t = min(1.0, s / L) if L else 0.0
            return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t), ((b[0] - a[0]) / L, (b[1] - a[1]) / L)
        s -= L
    return xy[-1], (1.0, 0.0)


def cut_poly(xy, s_end):
    out, s = [xy[0]], 0.0
    for (a, b), L in zip(zip(xy, xy[1:]), seg_lengths(xy)):
        if s + L >= s_end:
            t = (s_end - s) / L
            out.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
            return out
        out.append(b)
        s += L
    return out


def trim_ends(xy, start, end):
    """Keep the line out from under the end markers."""
    total = sum(seg_lengths(xy))
    pts, s0 = [], start
    steps = max(2, int((total - start - end) / 6))
    for i in range(steps + 1):
        pts.append(at_length(xy, s0 + (total - start - end) * i / steps)[0])
    return pts


class Neon:
    """Additive glow layers in window space (map viewport only). core/halo/wide are 'L' masks per colour."""

    def __init__(self, ox, oy, w, h):
        self.ox, self.oy, self.w, self.h = ox, oy, int(w), int(h)
        self.layers = {}

    def _lay(self, color):
        if color not in self.layers:
            self.layers[color] = [Image.new("L", (self.w, self.h), 0) for _ in range(3)]
        return self.layers[color]

    def loc(self, xy):
        return [(x - self.ox, y - self.oy) for x, y in xy]

    def line(self, xy, color, core=2, alpha=255, dash=None):
        core_l, halo_l, wide_l = self._lay(color)
        pts = self.loc(xy)
        segs = [pts]
        if dash:
            segs, s, total = [], 0.0, sum(seg_lengths(pts))
            while s < total:
                segs.append(cut_poly_from(pts, s, min(total, s + dash[0])))
                s += dash[0] + dash[1]
        for sg in segs:
            if len(sg) < 2:
                continue
            ImageDraw.Draw(core_l).line(sg, fill=alpha, width=core, joint="curve")
            ImageDraw.Draw(halo_l).line(sg, fill=int(alpha * 0.8), width=core + 3, joint="curve")
            ImageDraw.Draw(wide_l).line(sg, fill=int(alpha * 0.6), width=core + 9, joint="curve")

    def chevron(self, p, d, color, size, alpha):
        core_l, halo_l, wide_l = self._lay(color)
        x, y = p[0] - self.ox, p[1] - self.oy
        nx, ny = -d[1], d[0]
        tip = (x + d[0] * size, y + d[1] * size)
        a = (x - d[0] * size + nx * size, y - d[1] * size + ny * size)
        b = (x - d[0] * size - nx * size, y - d[1] * size - ny * size)
        a_ = int(alpha)
        for lay, wd in ((core_l, 2), (halo_l, 5), (wide_l, 10)):
            ImageDraw.Draw(lay).line([a, tip, b], fill=a_, width=wd, joint="curve")

    def x_mark(self, p, color, size=11):
        core_l, halo_l, wide_l = self._lay(color)
        x, y = p[0] - self.ox, p[1] - self.oy
        for lay, wd in ((core_l, 4), (halo_l, 10), (wide_l, 22)):
            d = ImageDraw.Draw(lay)
            d.line([(x - size, y - size), (x + size, y + size)], fill=255, width=wd)
            d.line([(x - size, y + size), (x + size, y - size)], fill=255, width=wd)

    def disc(self, p, r, color, alpha=255):
        core_l, halo_l, wide_l = self._lay(color)
        x, y = p[0] - self.ox, p[1] - self.oy
        ImageDraw.Draw(halo_l).ellipse([x - r, y - r, x + r, y + r], outline=alpha, width=5)
        ImageDraw.Draw(wide_l).ellipse([x - r - 6, y - r - 6, x + r + 6, y + r + 6], fill=alpha)

    def ring(self, p, r, color, alpha=255):
        core_l, halo_l, wide_l = self._lay(color)
        x, y = p[0] - self.ox, p[1] - self.oy
        ImageDraw.Draw(core_l).ellipse([x - r, y - r, x + r, y + r], outline=alpha, width=2)
        ImageDraw.Draw(halo_l).ellipse([x - r, y - r, x + r, y + r], outline=alpha, width=6)

    def apply(self, img: Image.Image, screen_x, screen_y):
        """Additively blend all layers onto img at (screen_x, screen_y)."""
        box = (round(screen_x), round(screen_y), round(screen_x) + self.w, round(screen_y) + self.h)
        region = np.asarray(img.crop(box).convert("RGB"), np.float32)
        add = np.zeros_like(region)
        for color, (core_l, halo_l, wide_l) in self.layers.items():
            col = np.array(color, np.float32)
            wide = np.asarray(wide_l.filter(ImageFilter.GaussianBlur(12)), np.float32) / 255.0 * 0.13
            halo = np.asarray(halo_l.filter(ImageFilter.GaussianBlur(3)), np.float32) / 255.0 * 0.4
            core = np.asarray(core_l.filter(ImageFilter.GaussianBlur(0.8)), np.float32) / 255.0
            add += (wide + halo)[..., None] * col
            add += core[..., None] * (col * 0.85 + 255 * 0.15)   # hue-true core (routes are told apart by colour)
        out = np.clip(region + add, 0, 255).astype(np.uint8)
        img.paste(Image.fromarray(out, "RGB").convert("RGBA"), box[:2])


def cut_poly_from(xy, s0, s1):
    out = [at_length(xy, s0)[0]]
    s = 0.0
    for (a, b), L in zip(zip(xy, xy[1:]), seg_lengths(xy)):
        if s0 < s + L and s + L < s1:
            out.append(b)
        s += L
    out.append(at_length(xy, s1)[0])
    return out


def lane_offsets(live):
    """live: {route index: tiles}. One lane per SOURCE building on every tile edge (a source's routes form one tree, so
    its routes on the same edge are one line). Lanes sit side by side, transit-map style: the offset is measured to the
    right of the travel direction and ordered by SOURCE_ORDER, so the order holds along a shared stretch; sources
    travelling the edge in opposite directions keep to their own right-hand side."""
    use = {}
    for i, tiles in live.items():
        src = ROUTES[i]["src"]
        for a, b in zip(tiles, tiles[1:]):
            use.setdefault((min(a, b), max(a, b)), set()).add((src, a < b))
    off = {}
    for e, ks in use.items():
        fwd = sorted({s for s, d in ks if d}, key=SOURCE_ORDER.index)
        back = sorted({s for s, d in ks if not d}, key=SOURCE_ORDER.index)
        n = len(fwd) + len(back)
        gap = min(Lay.BundleGap, 20.0 / (n - 1)) if n > 1 else 0.0
        for grp, d in ((fwd, True), (back, False)):
            for i, s in enumerate(grp):
                off[(e, s, d)] = (i + 0.5) * gap if fwd and back else (i - (len(grp) - 1) / 2) * gap
    return off, use


def offset_xy(src, tiles, off):
    vecs = []
    for a, b in zip(tiles, tiles[1:]):
        (ax, ay), (bx, by) = tp(*a), tp(*b)
        L = math.hypot(bx - ax, by - ay)
        o = off[((min(a, b), max(a, b)), src, a < b)]
        vecs.append((-(by - ay) / L * o, (bx - ax) / L * o))     # right of travel (screen y points down)
    pts = []
    for i, t in enumerate(tiles):
        x, y = tp(*t)
        vs = [v for v in ((vecs[i - 1] if i > 0 else None), (vecs[i] if i < len(vecs) else None)) if v]
        pts.append((x + sum(v[0] for v in vs) / len(vs), y + sum(v[1] for v in vs) / len(vs)))
    return pts


def hit(a, b, pad=0.0):
    return a[0] < b[0] + b[2] + pad and b[0] < a[0] + a[2] + pad and a[1] < b[1] + b[3] + pad and b[1] < a[1] + a[3] + pad


# ----------------------------------------------------------------------------------------- render
class Viewer:
    def __init__(self, P, W, spr, meta, fonts, bg, base, icon, heroes, portraits, banners):
        self.P, self.W, self.spr, self.meta, self.fonts, self.bg = P, W, spr, meta, fonts, bg
        self.base, self.icon, self.heroes, self.portraits, self.banners = base, icon, heroes, portraits, banners

    # ---- placement
    def inside(self, r):
        return r[0] >= Lay.MapX + 2 and r[1] >= Lay.MapY + 2 and r[0] + r[2] <= Lay.MapX + MAP_W - 2 and r[1] + r[3] <= Lay.MapY + MAP_H - 2

    def place(self, what, w, h, candidates, taken, pad=2.0, soft=()):
        """First candidate (x, y) whose w x h box is inside the map and clear of everything already placed; `soft`
        boxes (route tiles) are avoided when some candidate allows it."""
        for avoid in (list(soft), []):
            for x, y in candidates:
                r = (x, y, w, h)
                if self.inside(r) and not any(hit(r, t, pad) for _, t in taken) and not any(hit(r, t) for t in avoid):
                    return r
        FitCanvas.problems.append(f"no free place for {what!r}")
        x, y = candidates[0]
        return (x, y, w, h)

    @staticmethod
    def around(cx, cy, w, h, gaps):
        """Candidate top-left corners around a point: right, left, below, above, then the diagonals, per gap."""
        out = []
        for g in gaps:
            out += [(cx + g, cy - h / 2), (cx - g - w, cy - h / 2), (cx - w / 2, cy + g), (cx - w / 2, cy - g - h),
                    (cx + g, cy + g * 0.6), (cx + g, cy - g * 0.6 - h), (cx - g - w, cy + g * 0.6), (cx - g - w, cy - g * 0.6 - h)]
        return out

    def plate(self, cv, lines, r, colors, sizes=None, align="center"):
        """Text lines on one dark plate filling rect r."""
        P = self.P
        rect(cv, *r, LABEL_PLATE)
        lh = (r[3] - 4) / len(lines)
        for j, t in enumerate(lines):
            size = (sizes or [Lay.LabelSize] * len(lines))[j]
            cv.text(P["FontMedium"], size, t, r[0] + 7, r[1] + 2 + lh * j, r[2] - 13, lh, colors[j], align)

    def text_w(self, cv, lines, sizes=None):
        f = cv.fonts[self.P["FontMedium"]]
        return max(f.advance(t, (sizes or [Lay.LabelSize] * len(lines))[j]) for j, t in enumerate(lines)) + 15

    def uc_pill(self, cv, cx, cy, level):
        """Small 'UC n' badge: this building's Upgrade Center level (best skilled hero that visited it)."""
        P = self.P
        w_, h_ = 42, 20
        X, Y, _, _ = cv.rect(cx - w_ / 2, cy - h_ / 2, 0, 0)
        ImageDraw.Draw(cv.img).rounded_rectangle([X, Y, X + w_, Y + h_], radius=6, fill=(14, 20, 32, 245),
                                                 outline=tuple(P["TipTitle"][:3]) + (255,), width=1)
        cv.text(P["FontBook"], 13, f"UC {level}", cx - w_ / 2, cy - h_ / 2, w_, h_, P["TipTitle"], "center")

    def glyph_clock(self, cv, x, y, r=9):
        X, Y, _, _ = cv.rect(x, y, 0, 0)
        d = ImageDraw.Draw(cv.img)
        c = tuple(self.P["TipTitle"][:3]) + (255,)
        d.ellipse([X - r, Y - r, X + r, Y + r], outline=c, width=2)
        d.line([X, Y, X, Y - r + 3], fill=c, width=2)
        d.line([X, Y, X + r - 4, Y + 2], fill=c, width=2)

    def glyph_order(self, cv, x, y):
        """Hammer + clock: a remote build ordered, lands at the start of the next day."""
        X, Y, _, _ = cv.rect(x, y, 0, 0)
        d = ImageDraw.Draw(cv.img)
        c = tuple(self.P["TipTitle"][:3]) + (255,)
        d.line([(X - 7, Y + 7), (X + 1, Y - 1)], fill=c, width=2)       # handle
        d.line([(X - 2, Y - 7), (X + 6, Y + 1)], fill=c, width=5)       # head
        self.glyph_clock(cv, x + 20, y, 7)

    def panel_box(self, cv, x0, y0, cw, h, hh):
        P = self.P
        pm_, foot = P["PanelSliceMultiplier"], 30
        rect(cv, x0 + 5, y0 + 5, cw - 10, h - 10, (13, 18, 38, 242))    # opaque backing: the map must not show through
        cv.sliced(P["SpritePanelBody"], x0, y0 + hh - 12, cw, h - hh - foot + 24, pm_)
        cv.sliced(P["SpritePanelHeader"], x0, y0, cw, hh, pm_)
        cv.sliced(P["SpritePanelFooter"], x0, y0 + h - foot, cw, foot, pm_)

    # ---- selected-building card
    def card_rect(self, b, pending, remote):
        if remote:
            cw = Lay.RemoteCardWidth
            h = Lay.CardHeader + Lay.CardTabs + 8 + 48 + len(remote) * 60 + 26 + 22
        else:
            cw = Lay.CardWidth
            rh = Lay.CardRowPending if pending else Lay.CardRow
            h = Lay.CardHeader + Lay.CardTabs + 8 + len(b["built"]) * (rh + 6) + 2 * Lay.CardNote + 24
        return (Lay.MapX + MAP_W - 14 - cw, Lay.MapY + MAP_H - 14 - h, cw, h)

    def card_head(self, cv, b, r, tab):
        """Header (icon, name, Upgrade Center line) + the two tabs; returns the y under the tabs."""
        P = self.P
        x0, y0, cw, h = r
        hh = Lay.CardHeader
        self.panel_box(cv, x0, y0, cw, h, hh)
        ring, ricon = 64, 46
        rcx, rcy = x0 + 18 + ring / 2, y0 + hh / 2
        cv.image(self.spr[b["icon"]], rcx - ricon / 2, rcy - ricon / 2, ricon, ricon, preserve=True)
        cv.centered(P["SpritePanelRing"], rcx, rcy, ring, ring)
        tx = x0 + 18 + ring + 12
        tw_ = cw - (tx - x0) - 16
        cv.text(P["FontBook"], P["SizeSubHeader"], b["name"], tx, y0 + 10, tw_, 28, P["TipTitle"])
        cv.text(P["FontMedium"], P["SizeSmall"], f"Upgrade Center level {b['uc']} ({b['uc_by']} visited)", tx, y0 + 38, tw_, 22, P["TipNote"])
        ix, iw = x0 + 18, cw - 36
        ty = y0 + hh + 2
        half = (iw - 6) / 2
        for j, name in enumerate(("Active enhancement", "Build / Upgrade")):
            sel = j == tab
            cv.sliced("tab_selected_1" if sel else "tab_1", ix + j * (half + 6), ty, half, Lay.CardTabs - 6, 1.0)
            cv.text(P["FontMedium"], P["SizeSmall"], name, ix + j * (half + 6), ty, half, Lay.CardTabs - 6, P["TipTitle"] if sel else P["ButtonText"], "center")
        return ty + Lay.CardTabs + 2

    def remote_card(self, cv, b, rows, r):
        """'Build / Upgrade' tab: this building's own enhancements, ordered remotely up to its Upgrade Center level."""
        P = self.P
        x0, y0, cw, h = r
        y = self.card_head(cv, b, r, 1)
        ix, iw = x0 + 18, cw - 36
        cv.text(P["FontMedium"], P["SizeSmall"], f"Upgrade Center level {b['uc']} ({b['uc_by']} visited):", ix, y, iw, 22, P["TipBody"], "center")
        cv.text(P["FontMedium"], P["SizeSmall"], f"remote builds up to level {b['uc']}, active tomorrow", ix, y + 21, iw, 22, P["TipBody"], "center")
        y += 48
        rh = 54
        for row in rows:
            order = row.get("order")
            cv.sliced("tab_selected_1" if order else "tab_1", ix, y, iw, rh, 1.0)
            cy = y + rh / 2
            cv.centered("Overlay_Law_NotOpen", ix + 26, cy, 40, 40)
            cv.sprite(up.ICONS[row["icon"]], ix + 26 - 16, cy - 16, 32, 32, preserve=True)
            nx = ix + 54
            cv.text(P["FontMedium"], P["SizeMain"], row["name"], nx, y + 4, 196, 24, P["TipTitle"] if order else P["ButtonText"])
            if order:
                self.glyph_order(cv, nx + 9, y + 39)
                cv.text(P["FontMedium"], P["SizeSmall"], row["state"], nx + 40, y + 28, iw - 54 - 48, 22, P["TipTitle"])
                cv.text(P["FontMedium"], P["SizeSmall"], row["right"], ix + iw - 150, y + 4, 140, 24, P["TipTitle"], "right")
            else:
                cv.text(P["FontMedium"], P["SizeSmall"], row["state"], nx, y + 28, 150, 22, P["CostOk"] if row.get("active") else P["TipNote"])
                if row.get("cost"):
                    bw_ = 108
                    cw_ = iw - 250 - bw_ - 8
                    up.draw_cost(cv, P, row["cost"], ix + 250 - 62, y + 15, P["TipBody"], size=P["SizeSmall"], align="right", width=iw - 250 + 62 - 8)
                    cv.sliced("tab_highlight_1" if row.get("hover") else "tab_1", ix + iw - bw_ - 8, y + 29, bw_, 22, 1.0)
                    cv.text(P["FontMedium"], P["SizeSmall"], row["button"], ix + iw - bw_ - 8, y + 29, bw_, 22, P["ButtonText"], "center")
                else:
                    cv.text(P["FontMedium"], P["SizeSmall"], row["right"], ix + iw - 230, y + 28, 222, 22, P["TipWarn"], "right")
            y += rh + 6
        cv.text(P["FontMedium"], P["SizeSmall"], "Same cost as on site. A hero on site builds immediately.", ix, y, iw, 24, P["TipNote"], "center")

    def card(self, cv, b, switch_used, pending, r):
        """'Active enhancement' tab: built enhancements, levels, and the weekly switch of the active one.

        A switch takes effect at the start of the next day. With `pending` (the target enhancement's name) the current
        one reads 'Active until end of day' and the target 'Active tomorrow' beside a clock marker; the week's switch
        is then spent, so the other rows grey out."""
        switch_used = switch_used or bool(pending)
        P = self.P
        x0, y0, cw, h = r
        y = self.card_head(cv, b, r, 0)
        rh = Lay.CardRowPending if pending else Lay.CardRow
        ix, iw = x0 + 18, cw - 36
        for name, lvl in b["built"]:
            active = name == b["enh"]
            target = name == pending
            cv.sliced("tab_selected_1" if active or target else "tab_1", ix, y, iw, rh, 1.0)
            if target:
                self.glyph_clock(cv, ix + 22, y + rh / 2)      # the switch lands at the start of the next day
            else:
                # radio: filled when active; greyed while the weekly switch is spent
                X, Y, _, _ = cv.rect(ix + 22, y + rh / 2, 0, 0)
                d = ImageDraw.Draw(cv.img)
                on_col = P["CostOk"] if active else (P["ButtonTextDisabled"] if switch_used else P["TipTitle"])
                d.ellipse([X - 9, Y - 9, X + 9, Y + 9], outline=tuple(on_col[:3]) + (255,), width=2)
                if active:
                    d.ellipse([X - 4.5, Y - 4.5, X + 4.5, Y + 4.5], fill=tuple(on_col[:3]) + (255,))
            cv.centered("Overlay_Law_NotOpen", ix + 58, y + rh / 2, 32, 32)
            cv.sprite(BADGES[name], ix + 44, y + rh / 2 - 14, 28, 28, preserve=True)
            name_col = P["TipTitle"] if active or target else (P["ButtonTextDisabled"] if switch_used else P["ButtonText"])
            status = None
            if pending and active:
                status = ("Active until end of day", P["TipWarn"])
            elif target:
                status = ("Active tomorrow", P["TipTitle"])
            ny, nh = (y + 4, 26) if status else (y, rh)
            if status:
                cv.text(P["FontMedium"], P["SizeSmall"], status[0], ix + 82, y + 27, iw - 92, 22, status[1])
            cv.text(P["FontMedium"], P["SizeMain"], name, ix + 82, ny, 122, nh, name_col)
            cv.text(P["FontMedium"], P["SizeSmall"], f"Level {lvl}", ix + 204, ny, 58, nh, P["TipBody"] if active or target else P["TipNote"], "right")
            if active and not pending:
                cv.text(P["FontMedium"], P["SizeSmall"], "Active", ix + iw - 64, y, 54, rh, P["CostOk"], "right")
            y += rh + 6
        if pending:
            notes = [("Switch applies at the start of tomorrow", P["TipWarn"]), ("Next switch: start of next week", P["ButtonTextDisabled"])]
        elif switch_used:
            notes = [("Switch used this week", P["TipWarn"]), ("Next switch: start of next week", P["TipWarn"])]
        else:
            notes = [("1 switch left this week", P["TipBody"]), ("Click a row to switch; it applies next day.", P["TipNote"])]
        for j, (t, col) in enumerate(notes):
            cv.text(P["FontMedium"], P["SizeSmall"], t, ix, y + j * Lay.CardNote, iw, Lay.CardNote, col, "center")

    TIP_TEXT = "Not yet visited: a hero must visit to build here"

    def tip_rect(self, cv, b, taken, soft):
        """Reserve the hover tooltip's box (before the map labels, so they flow around it)."""
        x, y = tp(*b["at"])
        cw, h = cv.fonts[self.P["FontMedium"]].advance(self.TIP_TEXT, self.P["SizeSmall"]) + 40, 92
        r = self.place("unvisited tooltip", cw, h, self.around(x, y, cw, h, (Lay.Marker / 2 + 14, Lay.Marker / 2 + 40, Lay.Marker / 2 + 70)), taken, soft=soft)
        taken.append(("unvisited tooltip", r))
        return r

    def unvisited_tip(self, cv, b, r):
        """Hover tooltip on an owned building no skilled hero has visited yet."""
        P = self.P
        x, y = tp(*b["at"])
        text = self.TIP_TEXT
        cw, hh, h = r[2], 44, r[3]
        self.panel_box(cv, r[0], r[1], cw, h, hh)
        cv.text(P["FontBook"], P["SizeMain"], b["name"], r[0] + 20, r[1] + 8, cw - 40, 28, P["TipTitle"])
        cv.text(P["FontMedium"], P["SizeSmall"], text, r[0] + 20, r[1] + 46, cw - 40, 24, P["TipWarn"])
        X, Y, _, _ = cv.rect(x, y, 0, 0)
        rr = Lay.Marker / 2 + 7
        ImageDraw.Draw(cv.img).rounded_rectangle([X - rr, Y - rr, X + rr, Y + rr], radius=8, outline=tuple(P["TipBody"][:3]) + (220,), width=2)

    # ---- frame
    def render(self, phase=0.0, switch_used=False, pending=None, remote=None):
        P, W = self.P, self.W
        FitCanvas.problems = []
        cv = FitCanvas(P, self.spr, self.meta, self.fonts, self.bg)
        cv.img.alpha_composite(Image.new("RGBA", cv.img.size, (0, 0, 0, int(255 * P["BlockAlpha"]))))
        w, h = Lay.Width, Lay.Height
        shell(P, W, cv, w, h, "Logistics Network", self.icon)
        cv.image(self.base, Lay.MapX, Lay.MapY, MAP_W, MAP_H)
        by_name = {b["name"]: b for b in BUILDINGS}
        sel = next(b for b in BUILDINGS if b.get("built"))
        card_r = self.card_rect(sel, pending, remote)
        zx = Lay.MapX + MAP_W - Lay.ZoomSize / 2 - 12
        taken = [("card", card_r), ("zoom buttons", (zx - Lay.ZoomSize / 2 - 4, Lay.MapY + 8, Lay.ZoomSize + 8, Lay.ZoomSize * 2 + 18))]
        labels = []     # (text, rect) of every map label, for the overlap report

        # ---- neon: routes (one thin line per source per tile edge), chevrons, hub rings, stack glow
        neon = Neon(Lay.MapX, Lay.MapY, MAP_W, MAP_H)
        top = Neon(Lay.MapX, Lay.MapY, MAP_W, MAP_H)       # cut marks, applied over the markers
        live = {i: rt["live"] for i, rt in enumerate(ROUTES)}
        off, _ = lane_offsets(live)
        cuts = {}
        for i, rt in enumerate(ROUTES):
            col = SOURCE_COLOURS[rt["src"]]
            xy = offset_xy(rt["src"], live[i], off)
            if rt["cut"]:
                rest_xy = [tp(*t) for t in rt["tiles"][len(live[i]) - 1:]]
                rl = sum(seg_lengths(rest_xy))
                if rl > 60:
                    neon.line(cut_poly_from(rest_xy, 14, rl - 34), RED, core=2, alpha=105, dash=(7, 9))
                neon.line(trim_ends(xy, 30, 0), col)
                self.chevrons(neon, xy, phase, 30, 14, col)
                cuts.setdefault((rt["src"], live[i][-1]), []).append(rt)
            else:
                neon.line(trim_ends(xy, 30, 30), col)
                self.chevrons(neon, xy, phase, 30, 30, col)
        # the link the stack blocks: dim dashed red where the unguarded path leaves the route in use
        a, b_ = STACK["link"]
        used_tiles = set(next(r for r in ROUTES if r["src"] == a and r["dst"] == b_)["tiles"])
        seg = []
        for t in STACK["shortcut"] + [None]:
            if t is not None and (t not in used_tiles or not seg):
                seg = (seg + [t]) if t not in used_tiles else [t]
                continue
            if len(seg) > 1:
                neon.line([tp(*q) for q in seg + ([t] if t is not None else [])], RED, core=2, alpha=110, dash=(7, 7))
            seg = [t] if t is not None else []
        sx, sy = tp(*STACK["at"])
        pulse = 0.75 + 0.25 * math.cos(phase * 2 * math.pi)
        neon.disc((sx, sy), 30, RED, int(200 * pulse))
        for b in BUILDINGS:
            if b.get("hub"):
                neon.ring(tp(*b["at"]), Lay.Marker / 2 + 9, HUB_RING, 200)
        neon.apply(cv.img, cv.ox + Lay.MapX, cv.oy + Lay.MapY)

        # ---- selection: gold contour around the clicked marker (under its badges)
        X, Y, _, _ = cv.rect(*tp(*sel["at"]), 0, 0)
        d = ImageDraw.Draw(cv.img)
        gold = tuple(self.P["TipTitle"][:3])
        r_ = Lay.Marker / 2 + 9
        d.rounded_rectangle([X - r_, Y - r_, X + r_, Y + r_], radius=8, outline=gold + (255,), width=3)
        d.rounded_rectangle([X - r_ - 5, Y - r_ - 5, X + r_ + 5, Y + r_ + 5], radius=11, outline=gold + (110,), width=2)

        # ---- markers
        for t in TOWNS:
            x, y = tp(*t["at"])
            s = Lay.TownSize
            cv.image(self.banners[t["name"]], x - s / 2, y - s / 2, s, s, preserve=True)
            taken.append((t["name"] + " marker", (x - s / 2, y - s / 2, s, s)))
        for hr in HERO_LIST:
            x, y = tp(*hr["at"])
            im = self.heroes[hr["sid"]]
            s = Lay.HeroSize
            mask = Image.new("L", im.size, 0)
            ImageDraw.Draw(mask).ellipse([0, 0, im.width - 1, im.height - 1], fill=255)
            round_im = im.copy()
            round_im.putalpha(Image.composite(im.getchannel("A"), Image.new("L", im.size, 0), mask))
            cv.image(round_im, x - s / 2 + 3, y - s / 2 + 3, s - 6, s - 6)
            cv.centered(P["SpritePanelRing"], x, y, s + 6, s + 6)
            taken.append((hr["name"] + " marker", (x - s / 2, y - s / 2, s, s)))
        m = Lay.Marker
        for b in BUILDINGS:
            x, y = tp(*b["at"])
            if b.get("portrait"):
                up.Panel(P, W, cv, None, None, None).card(self.portraits[b["portrait"]], x, y, m + 6)
            else:
                cv.centered("Overlay_Law_NotOpen", x, y, m, m)
                cv.sprite(b["icon"], x - m / 2 + 5, y - m / 2 + 5, m - 10, m - 10, preserve=True)
                cv.centered("Frame_Law_Top", x, y, m + 6, m + 6)
            if b["enh"]:      # enhancement badge with level
                bx, by = x + m / 2 - 4, y + m / 2 - 6
                cv.centered("Overlay_Law_NotOpen", bx, by, Lay.Badge + 4, Lay.Badge + 4)
                cv.sprite(BADGES[b["enh"]], bx - Lay.Badge / 2, by - Lay.Badge / 2, Lay.Badge, Lay.Badge, preserve=True)
                cv.centered("Frame_LawLevel (1)", bx + 13, by - 13, 20, 20)
                cv.text(P["FontBook"], 13, str(b["lvl"]), bx + 3, by - 23, 20, 20, P["Ink"], "center")
            if b.get("uc"):
                self.uc_pill(cv, x + m / 2 - 6, y - m / 2 - 2, b["uc"])
            if b["name"] in SOURCE_COLOURS:   # route colour key
                X, Y, _, _ = cv.rect(x - m / 2 + 1, y - m / 2 + 1, 0, 0)
                ImageDraw.Draw(cv.img).ellipse([X - 8, Y - 8, X + 8, Y + 8], fill=SOURCE_COLOURS[b["name"]] + (255,), outline=(10, 14, 22, 255), width=2)
            taken.append((b["name"] + " marker", (x - m / 2 - 8, y - m / 2 - 12, m + 26, m + 22)))
        up.Panel(P, W, cv, None, None, None).card(self.portraits[STACK["portrait"]], sx, sy, 46)
        taken.append(("stack marker", (sx - 39, sy - 39, 78, 78)))     # stack + its guard ring stay readable

        # ---- cut marks over the markers (a route may run out one tile short of its target)
        for (src, tile), rts in cuts.items():
            top.x_mark(tp(*tile), RED, 9)
        top.apply(cv.img, cv.ox + Lay.MapX, cv.oy + Lay.MapY)
        for (src, tile), rts in cuts.items():
            x, y = tp(*tile)
            taken.append((f"cut mark {src}", (x - 12, y - 12, 24, 24)))

        # ---- labels: marker names first, then the stack note, then the cut labels
        route_boxes = [(tp(*t)[0] - 9, tp(*t)[1] - 9, 18, 18) for tiles in live.values() for t in tiles]

        def put(what, lines, colors, cands, sizes=None, align="center", soft=()):
            tw = self.text_w(cv, lines, sizes)
            r = self.place(what, tw, 20 * len(lines) + 4, cands(tw, 20 * len(lines) + 4), taken, soft=soft)
            self.plate(cv, lines, r, colors, sizes, align)
            taken.append((what, r))
            labels.append((what, r))
            return r

        def near(x, y, half):
            return lambda tw, th: [(x - tw / 2, y + half + 4), (x - tw / 2, y - half - 6 - th), (x + half + 8, y - th / 2), (x - half - 8 - tw, y - th / 2),
                                   (x - tw / 2, y + half + 14), (x - tw / 2, y - half - 18 - th)]

        hovered = next(b for b in BUILDINGS if b["uc"] is None) if remote else None
        tip_r = self.tip_rect(cv, hovered, taken, route_boxes) if hovered else None
        for t in TOWNS:
            x, y = tp(*t["at"])
            put(t["name"], [t["name"]], [P["TipTitle"]], near(x, y, Lay.TownSize / 2))
        for hr in HERO_LIST:
            x, y = tp(*hr["at"])
            put(hr["name"], [hr["name"]], [P["TipBody"]], near(x, y, Lay.HeroSize / 2 + 2))
        for b in BUILDINGS:
            if b is hovered:
                continue                                # the tooltip names it
            x, y = tp(*b["at"])
            second = f"{b['enh']} {b['lvl']}" if b["enh"] else "Not yet visited"
            put(b["name"], [b["name"], second], [P["TipBody"], P["TipNote"] if b["enh"] else P["TipWarn"]],
                lambda tw, th, x=x, y=y: [(x - tw / 2, y + m / 2 + 10), (x - tw / 2, y - m / 2 - 14 - th), (x + m / 2 + 20, y - th / 2), (x - m / 2 - 10 - tw, y - th / 2)]
                + self.around(x, y, tw, th, (m / 2 + 24, m / 2 + 40)),
                sizes=[Lay.LabelSize, 14])
        put("stack note", [STACK["note"]], [RED + (255,)], lambda tw, th: self.around(sx, sy, tw, th, (42, 58, 80)), soft=route_boxes)
        for (src, tile), rts in cuts.items():
            x, y = tp(*tile)
            lines = [f"{by_name[src]['enh']} ({src})"] + [f"-> {rt['dst']}: +{rt['need']} range needed" for rt in rts]
            r = put(f"cut label {src}", lines, [RED + (255,)] * len(lines), lambda tw, th: self.around(x, y, tw, th, (16, 30, 48, 70, 100)), align="left", soft=route_boxes)
            # leader line when the plate is not touching the mark
            px = min(max(x, r[0]), r[0] + r[2])
            py = min(max(y, r[1]), r[1] + r[3])
            if math.hypot(px - x, py - y) > 18:
                X, Y, _, _ = cv.rect(x, y, 0, 0)
                PX, PY, _, _ = cv.rect(px, py, 0, 0)
                ImageDraw.Draw(cv.img).line([(X, Y), (PX, PY)], fill=RED + (210,), width=1)

        # ---- selected building: gold contour on its marker + the card; hover tooltip in the remote-build shot
        if remote:
            self.unvisited_tip(cv, hovered, tip_r)
            self.remote_card(cv, sel, remote, card_r)
        else:
            self.card(cv, sel, switch_used, pending, card_r)
        # ---- zoom + close + legend
        cv.centered("button_plus", zx, Lay.MapY + 12 + Lay.ZoomSize / 2, Lay.ZoomSize, Lay.ZoomSize)
        cv.centered("button_minus", zx, Lay.MapY + 18 + Lay.ZoomSize * 1.5, Lay.ZoomSize, Lay.ZoomSize)
        cv.centered("FullSkreanExitButton", w - 34, W["RecruitHeaderHeight"] / 2, Lay.CloseSize, Lay.CloseSize)
        self.legend(cv, phase)
        return cv

    def chevrons(self, neon, xy, phase, start, end, color):
        total = sum(seg_lengths(xy))
        s = start + (phase * Lay.ChevronGap) % Lay.ChevronGap
        while s < total - end:
            p, d = at_length(xy, s)
            # bright crest travelling from the source to the receiver
            k = ((s - phase * Lay.PulsePeriod) % Lay.PulsePeriod) / Lay.PulsePeriod
            crest = math.exp(-((k - 0.5) ** 2) / 0.02)
            neon.chevron(p, d, color, Lay.ChevronSize, 110 + 145 * crest)
            s += Lay.ChevronGap

    def legend(self, cv, phase):
        P = self.P
        y0, hgt = Lay.LegendTop, Lay.LegendHeight
        cy = y0 + hgt / 2
        rect(cv, Lay.MapX, y0, MAP_W, hgt, (6, 10, 18, 150))
        neon = Neon(Lay.MapX, y0, MAP_W, hgt)
        f = cv.fonts[P["FontMedium"]]
        items = []
        x = Lay.MapX + 22

        def item(text, icon_w, gap=30):
            nonlocal x
            items.append((x + icon_w + 10, text))
            x += icon_w + 10 + f.advance(text, P["SizeSmall"]) + gap

        cols = list(SOURCE_COLOURS.values())
        for j, col in enumerate(cols[:3]):
            yy = cy + (j - 1) * Lay.BundleGap
            neon.line([(x, yy), (x + 64, yy)], col)
            neon.chevron((x + 36, yy), (1, 0), col, 4, 230)
        item("Route (colour = source building)", 64)
        neon.ring((x + 14, cy), 12, HUB_RING, 200)
        item("Hub", 28)
        uc_x = x
        item("Upgrade Center level (hero visit)", 44)
        neon.line([(x, cy), (x + 26, cy)], cols[0])
        neon.x_mark((x + 36, cy), RED, 7)
        item("Cut: extra range levels needed", 46)
        neon.disc((x + 14, cy), 11, RED, 220)
        item("Stack blocking a link", 28)
        neon.apply(cv.img, cv.ox + Lay.MapX, cv.oy + y0)
        self.uc_pill(cv, uc_x + 22, cy, 2)
        for tx, text in items:
            tw = f.advance(text, P["SizeSmall"])
            cv.text(P["FontMedium"], P["SizeSmall"], text, tx, y0, tw + 2, hgt, P["TipBody"])
        right = f"Logistics level {LOGISTICS_LEVEL} · range {RANGE_MP} MP"
        tw = f.advance(right, P["SizeSmall"])
        if Lay.MapX + MAP_W - 20 - tw < x - 6:
            FitCanvas.problems.append("legend: right text collides with the items")
        cv.text(P["FontMedium"], P["SizeSmall"], right, Lay.MapX + MAP_W - 20 - tw, y0, tw + 2, hgt, P["TipNote"])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--assets", type=Path, default=ASSETS)
    ap.add_argument("--frames", type=int, default=10, help="GIF frames (0 = PNG only)")
    ap.add_argument("--force", action="store_true", help="save even when the layout check reports problems (for debugging)")
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    up.SPRITES[:] = list(dict.fromkeys(up.SPRITES + EXTRA))
    P, W, spr, meta, fonts, bg = up.load(args.assets)
    icon = Image.open(up.SKILL_ICON).convert("RGBA")
    heroes = {h["sid"]: Image.open(HEROES / f"{h['sid']}.png").convert("RGBA") for h in HERO_LIST}
    portraits = {n: Image.open(up.PORTRAITS / f"{n}.png").convert("RGBA") for n in ("h3_automaton", "h3_behemoth", "h3_mechanic")}
    banners = {t["name"]: Image.open(FACTION / t["faction"]).convert("RGBA") for t in TOWNS}
    global GRID
    GRID = load_map(args.assets)
    solve_routes()
    GRID["fog"] = build_fog()
    for rt in ROUTES:
        print(f"  {rt['src']} -> {rt['dst']}: {rt['cost']:.0f} MP" + (f", cut after {len(rt['live']) - 1} tiles, +{rt['need']} range" if rt["cut"] else ""))
    print(f"  stack: {STACK['note']} ({STACK['shortcut_cost']:.0f} MP without its guard ring); range {RANGE_MP} MP")
    _, use = lane_offsets({i: rt["live"] for i, rt in enumerate(ROUTES)})
    shared3 = sum(1 for ks in use.values() if len({s for s, _ in ks}) >= 3)
    print(f"  tile edges carrying 3+ sources: {shared3}")
    if shared3 < 3:
        raise SystemExit("no stretch where 3+ routes share tiles")
    viewer = Viewer(P, W, spr, meta, fonts, bg, map_base(), icon, heroes, portraits, banners)

    def save(cv, name, what, lines):
        if FitCanvas.problems:
            print(f"{what}:\n  " + "\n  ".join(FitCanvas.problems))
            if not args.force:
                raise SystemExit(1)
        meter.caption(cv.img, lines, size=15).save(args.out / name)
        print("->", args.out / name)

    cv = viewer.render(phase=0.35)
    save(cv, "network_viewer.png", "network viewer", [
        "LOGISTICS NETWORK viewer (free spell in every Factory hero's spellbook), 1920x1080 reference, still frame. The map is a real Olden Era region (Thirst for Power, x 1-63 / z 7-37): square tiles,",
        "8 neighbours, real terrain, roads, water and blocked tiles; fog patches, ownership and names are invented. Routes are thin neon lines coloured by their source building (dot on its marker) and step",
        "tile to tile along the cheapest path (10 MP a tile, x1.41 diagonal, roads cheaper); sources sharing tiles run side by side. Range is 200 MP (logistics level 2 from Rail Station 1): routes that cost",
        "more end in a red X on the last tile they reach, with the source's active enhancement, the target and the missing range levels. The Behemoths' guard ring forces Crystal Mine -> Forgehold on a detour",
        "that is 2 MP too long (192 MP without the stack). 'UC n' = Upgrade Center level of that building. Selected: Crystal Mine (gold contour); its card lists the built enhancements, one active, one switch per week.",
    ])
    cvp = viewer.render(phase=0.35, pending="Export Office")
    save(cvp, "network_viewer_switch_pending.png", "network viewer (switch pending)", [
        "Same day, right after clicking Export Office in the Crystal Mine card: a switch lands at the start of the next day. Power Station 2 stays active until end of day; Export Office 1 shows a clock",
        "marker and 'Active tomorrow'. The week's one switch is now spent, so the remaining row greys out. The map keeps showing Power Station 2 until the day turns.",
    ])
    crystal = up.with_dust(up.mine_options("crystal", "mercury", 1, 125))
    need_uc = "Level 3 needs Upgrade Center 3"
    remote_rows = [
        dict(icon="power", name="Power Station", state="Built: level 2 (active)", active=True, right=need_uc),
        dict(icon="export", name="Export Office", state="Under construction - active tomorrow", order=True, right="Level 2 ordered"),
        dict(icon="hub", name="Logistics Hub", state="Built: level 1", cost=crystal["hub"]["costs"][1], button="Upgrade to 2"),
        dict(icon="byproduct", name="Byproduct Processing", state="Not built", cost=crystal["byproduct"]["costs"][0], button="Build level 1", hover=True),
    ]
    cvr = viewer.render(phase=0.35, remote=remote_rows)
    save(cvr, "network_viewer_remote_build.png", "network viewer (remote build)", [
        "Remote build: Henrietta (Advanced) visited the Crystal Mine, so the mine's Upgrade Center is level 2. Its 'Build / Upgrade' tab orders this mine's own enhancements from the viewer, up to level 2,",
        "at the normal cost; an order takes a day and is active at the start of the next day (a hero on site still builds immediately). Export Office level 2 was ordered today: hammer + clock,",
        "'Under construction - active tomorrow'. Power Station is at the Upgrade Center's level, so level 3 needs a level 3 visit. The marker affects no other building. Hovering the Mechanic Workshop",
        "(owned, never visited by a skilled hero, no badge) shows 'Not yet visited: a hero must visit to build here'.",
    ])
    mine = next(b for b in BUILDINGS if b.get("built"))
    saved = dict(mine)
    mine.update(enh="Export Office", lvl=1)
    cv2 = viewer.render(phase=0.35, switch_used=True)
    mine.clear()
    mine.update(saved)
    save(cv2, "network_viewer_switch_used.png", "network viewer (switch used)", [
        "Next day: the switch has applied (Export Office 1 active; the map label, the badge and the cut label now say Export Office). The weekly switch stays spent: radios greyed,",
        "'Next switch: start of next week'. Builds and upgrades on site apply immediately; remote orders through the Upgrade Center apply at the start of the next day.",
    ])
    if args.frames > 0:
        frames = []
        box = (round(cv.ox), round(cv.oy), round(cv.ox + Lay.Width), round(cv.oy + Lay.Height))
        for i in range(args.frames):
            f = viewer.render(phase=i / args.frames).img.crop(box)
            f = f.resize((round(f.width * 0.7), round(f.height * 0.7)), Image.LANCZOS).convert("RGB")
            frames.append(f)
        pal = frames[0].quantize(colors=255, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
        frames = [f.quantize(palette=pal, dither=Image.Dither.NONE) for f in frames]
        gif = args.out / "network_viewer_pulse.gif"
        frames[0].save(gif, save_all=True, append_images=frames[1:], duration=90, loop=0, optimize=False)
        print("->", gif, f"{gif.stat().st_size / 1e6:.1f} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
