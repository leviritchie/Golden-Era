"""Rampart profile of the full-3D town lane (docs/homm3_stronghold_full_3d_town.md). A green meadow valley under low
white fog: dark pine slopes left and right, pink-red rock crags on the right hillside, a fogged far valley through the
middle, grass tufts and two grey stone outcrops on the meadow. The painting carries no painted houses: every house is
a building layer. Measured values say where they come from; hand-set values say so. Proof tier: staged candidate only
(no bundle, no install).
"""
from __future__ import annotations

# ------------------------------------------------------------------------------------------------ identity
FRACTION = "homm3_rampart"
BACKGROUND = "Rampart-in-background.png"
DATA_DIR = "homm3_rampart_full3d"
BUNDLE = "homm3_town_scene3d_rampart"
PREFIX = "homm3_rampart3d_"
ASSET_ROOT = "Assets/Homm3TownScene3d/rampart"
LABEL = "Rampart"
FX_MODULE = "town_full3d_fx"   # the shared profile-classified effects module (FX_LAYERS below)

# Animated reachable layers (layers/anims/metadata.json frames > 1), classified from the DEF's changed-pixel mask
# (town_all/fx_probe/rampart_changed.png, 2026-09-28). Place, extent, colour and timing are measured by
# town_full3d_fx from the DEF itself.
_FALL = {"moves": "the waterfall pours down the rock (pale cyan px down the fall and into the pool)",
         "effects": [{"kind": "water"}]}
_LAMP = {"moves": "a lamp in the homestead flickers (3-6 orange px, hue 26-27)",
         "effects": [{"kind": "flame", "minPx": 1}]}
_CLIFF = {"moves": "faint movement on the dragon cliff (scattered low-saturation px, 40 frames)",
          "effects": [{"kind": "glow"}]}
FX_LAYERS = {
    "tbrmdw_0": _LAMP, "tbrmdw_0_2": _LAMP,
    "tbrmdw_3": _FALL, "tbrmdw_3_2": _FALL,
    "tbrmdw_6": _CLIFF, "tbrmdw_6_2": _CLIFF,
    # the wooden rig on the right moves too, but not as a rotor: kind 'spin' measured a 0 deg frame-to-frame rotation
    # there (stronghold_full3d_fx.windmill divided by it, fx_v1 first stage), so it takes a masked 'glow' instead
    "tbrmext0": {"moves": "the waterfall pours into the pool and the wooden rig at the pool's right edge moves",
                 "effects": [{"kind": "water", "rects": [[88, 8, 123, 80]]},
                             {"kind": "glow", "rects": [[138, 33, 180, 79]],
                              "why": "the rig does not rotate (spin fit 0 deg/frame); its own changed px breathe"}]},
    "tbrmspec": {"moves": "the waterfall pours into the pool (pale cyan px)", "effects": [{"kind": "water"}]},
}

# ------------------------------------------------------------------------------------------------ scene / catalog
TO_SUN_CAM = (-0.55, 0.55, 0.62)   # hand-set: the huts' lit faces look left and toward the camera (soft, overcast)
# positions.json keys Rampart's layers by DEF name (building_layer_map.json maps the OE SIDs onto them). full = every
# native top level; tbrmspec (Mystic Pond) and tbrmext0 (its fountain upgrade) share a place, so full shows ext0.
STATES = {
    "start": ["tbrmhall", "tbrmtvrn", "tbrmdw_0"],
    "full": ["tbrmhal3", "tbrmcas3", "tbrmmag4", "tbrmtvrn", "tbrmmark", "tbrmsilo", "tbrmblak", "tbrmext0",
             "tbrmhrd1", "tbrmholy", "tbrmdw_0_2", "tbrmdw_1_2", "tbrmdw_2_2", "tbrmdw_3_2", "tbrmdw_4_2",
             "tbrmdw_5_2", "tbrmdw_6_2"],
    "anim": ["tbrmdw_0", "tbrmdw_3", "tbrmdw_6", "tbrmspec"],
}
WATER_USE = ("none in the painting: the waterfalls and the pond are building layers (tbrmdw_3*, tbrmspec/tbrmext0), "
             "textured with their static sprites")

# ------------------------------------------------------------------------------------------------ sky
# Overcast white fog, not blue: the Stronghold 'blue' rule finds nothing. Measured (CIELAB, blur 1.2): the fog sky is
# L* 81-100, b* -12..0 (sampled at HoMM3 (300-600, 0-80)); the fogged pine slopes are L* 22-65 and the pink crags
# b* > +5, so the box L* >= 75, b* <= 2 connected to the top edge takes the sky and leaves the slopes. Its lowest row is
# HoMM3 y 101 (x 550, the valley mouth), inside the horizon cap (HORIZON_HOMM3_Y + 4). Extension rule: see TEX below.
SKY_MASK = {"rule": "lab", "reason": "white fog / overcast sky over the valley; fogged slopes are darker (L* < 75)",
            "bMax": 2.0, "lMin": 75.0,
            # the fill's own fog (seed 23) is L* 49-80, b* -12..-1 and drifts down its right slope to frame row ~260,
            # over a fogged hill of L* 34-56, b* -3; its pines and meadow are L* 21-27, b* +10. lMin 45 graded the
            # fogged hill toward the painted pine slopes (a dark silhouette with a bright rim at the box edge), so the
            # box is L* > 33, b* < 2: the fogged hill keeps the fill's own fog colour, as the painted fog is ungraded
            "extension": {"bMax": 2.0, "lMin": 33.0, "maxRow": 300}}
# The right wall's far part scaled per azimuth onto the fill's own skyline (stronghold_full3d_terrain.fit_ext_skyline),
# Bulwark's values (4b9c62d0ea) with its 64 px edge ramp, except kMax: the bridge repaints the fill's sky beside the edge
# (writeSky) up to frame row 0, so the terrain silhouette must follow the bridged skyline instead of the dome showing over
# painted rock. At kMax 4 the fit refused (13 of 269 bins needed k > 4, residual max 5.19 deg); kMax 8 is measured below.
EXT_SKYLINE = {"rhoMinM": 20.0, "rhoFullM": 60.0, "kMin": 0.05, "kMax": 8.0, "fadeDeg": 0.05, "maxBinsAtKMax": 4,
               "edgeRampPx": 64}
SKY_ANIM = {"mode": "deferred", "reason": "the periodic 360 deg sky band is being rebuilt in the parent's change; "
            "drift follows it"}
# the static dome's periodic 360 deg panorama outside the painted sky (town_full3d_sky kit, then town_full3d_sdfill.py --step sky):
# the mirror dome streaked right of the painted rect under the sweeps
SKY_PANO = {"key": "p1_s11", "seed": 11,
            "prompt": "hand-painted fantasy game background sky, 1990s painted matte art, soft misty grey-blue sky, pale layered clouds, gentle diffuse daylight, sky and clouds only",
            "negative": "sun disc, sunset, orange, dark storm, photo, photorealistic, land, ground, hills, mountains, trees, water, building, tower, person, bird, horizon line, text, watermark, frame, border, seam, lowres"}
# the painted sky continued across the rect's side edges onto the panorama (town_full3d_sky SKY_EDGE_JOIN): without it
# the dome is pure panorama right of x = TW and the painted clouds end in a vertical step (seam-line gate, fx_v1 rest)
SKY_EDGE_JOIN = {"method": "mirror", "edges": ["right", "left"], "fadePx": 360.0,
                 "reason": "the panorama beside the painted rect does not continue the painted clouds"}
ANIM_CROSSWALK = {}   # every layers/anims id (tbrmdw_0*, tbrmdw_3*, tbrmdw_6*, tbrmext0, tbrmspec) is a layer id

# ------------------------------------------------------------------------------------------------ texture (sdgrade)
TEX = {
    "styleCropNative": (150, 150, 560, 374),   # the meadow huts, tavern and market (native px), kit style reference
    # context 'full': the painting has no painted props to keep out of the extension, so the model sees it whole
    "sd": {"prompt": ("a matte painting of a misty green mountain valley, a wide lush green meadow with small grass "
                      "tufts and a few grey stones, steep slopes of dark pine forest, pink-red rock crags on the "
                      "hillside, low white fog and clouds filling the valley, soft overcast light, painterly, detailed"),
           "negative": ("building, house, cottage, roof, hut, tent, tower, castle, wall, fence, person, animal, road, "
                        "path, river, water, lake, flowers, blue sky, sun, snow, desert, sand, canyon, text, "
                        "watermark, signature, frame, border, blurry, lowres, jpeg artifacts, photo"),
           "promptKey": "p1", "seed": 23, "context": "full"},
    # seeds 11 / 23 / 37 compared (town_all/rampart/sdfill_seeds.png): 11 lays a fog blanket over the right meadow,
    # 37 scatters pink boulders; 23 keeps the meadow open with the fog on the slopes
    "clean": [],
    "integrate": {"esrgan": True, "grain": True,
                  "paintFloor": (100, 560, 1400, 665),   # bare meadow at the bottom of the painting (frame box)
                  "floorRamp": (230, 300)},               # grain weight 0 above (slopes, fog), 1 below (meadow)
    # the meadow starts at frame row ~247 (HoMM3 y 137); extOnlyBands as Castle (a green meadow beside a darker edge)
    "grade": {"floorRows": (560, 665), "cliffRows": 245, "floorzRows": 300, "extOnlyBands": True},
    "propMask": {"rule": "none", "reason": "no painted houses: every house in the Rampart screen is a building layer; "
                 "the two stone outcrops are ground"},
    "blend": {"toneRows": (200, 280),   # the slopes beside the side edges; faded to 0 on the meadow
              # the building mask's 3 px margin past x = TW (frame rows 210-658) is written too, as in the bridge below
              "writeExtBuildingMask": True},
    # right-edge bridge (town_full3d_sdfill --step bridge, between grade and blend): the painting's red cliffs, pine
    # forest and meadow continued into a band of the extension; the painted cliff and forest reach the frame top while
    # the fill has sky there (fx_v1 rest seam-line rows 0-190, ratio 65-115), so the band repaints the fill's sky too
    # (the terrain skyline follows, EXT_SKYLINE)
    "bridge": {"prompt": ("a matte painting of a forested mountain valley, tall red sandstone cliffs, dark green pine "
                          "forest on the slopes, a green grass meadow below, soft misty daylight, painterly, detailed"),
               "negative": ("building, house, cottage, hut, tent, tower, castle, wall, fence, roof, person, animal, road, "
                            "text, watermark, signature, frame, border, seam, vertical line, blurry, lowres, "
                            "jpeg artifacts, photo"),
               # seed 53 of 37 / 41 / 53: 37 grew a grey cloud and 41 a dark blob over the forest; 53 continues it into the mist
               "seed": 53, "bandPx": 192, "fadePx": 96, "rowsBelowPx": 48, "contextPx": 560, "strength": 0.6,
               "rectContext": None, "writeSky": True,
               # the building mask's dilation margin past the rect (3 px at x 1440-1442, frame rows 210-658) kept the raw
               # fill: a light line at x = TW (seam_v1 rest, rows 204-374: canvas L* 22 at x 1440-1442 against 17.5 at
               # 1443, the painted edge's replicated column), as Bulwark's dotted line
               "writeExtBuildingMask": True},
    "renderRefPass": True,
}

# ------------------------------------------------------------------------------------------------ terrain
# Horizon (hand-set within measured bounds): the painted fog sky reaches HoMM3 y 101 (valley mouth, x 550), so the
# floor's vanishing line cannot sit above ~y 97 without cutting the sky mask (cap = horizon + 4). Depth Anything V2
# disparity over the meadow polygon, taken as proportional to inverse depth, vanishes at y 104 (Large, rows >= 200;
# Base 99). Depth Pro's inverse depth is linear in the row (Tukey IRLS, 92% inliers) but vanishes at y 30: it reads
# the meadow as rising to the tree line, which a single floor plane cannot hold together with the sky, so it is
# recorded and not used (measure_horizon.py under town_all/rampart).
HORIZON_HOMM3_Y = 104.0
# measured: the tavern (tbrmtvrn, one-storey thatched hut) has a 25 px wall (eave y 268 to base y 293) = 1.07 camera
# units at its depth on this floor plane (1.09 with the Depth Pro horizon: the scale barely depends on it); one-storey
# eave hand-set 2.2 m as Stronghold's. No painted hut exists, so the scale comes from a building layer.
HUT_WALL_UNITS, HUT_EAVE_M = 1.07, 2.2
FAR_CAP_M = 400.0
# Hand-traced meadow polygon (HoMM3 px): below the tree line (y 137-139) and the right-hand hedge (y 148-152).
FLOOR_POLY_HOMM3 = [(0, 140), (100, 140), (200, 140), (300, 140), (400, 140), (500, 140), (600, 140), (650, 142),
                    (700, 149), (800, 153), (800, 374), (0, 374)]
SPUR_SCALE, SPUR_AMP = 14.0, 0.35   # hand-set: rounded forested slopes, as Castle's hills
WALL_SHIFT_M = 40.0                 # hand-set: the slopes close round the meadow gently

# ------------------------------------------------------------------------------------------------ ground
# Castle's vanilla green set (the same meadow biome; every name exists in the vanilla extraction)
FLOOR_TEX = (("grass1", 4.0), ("grass2", 4.5), ("512_10_grass_forest_lawn_1_diffuse", 5.0), ("grass3", 5.5),
             ("dirt_ground3", 6.0))
ROCK_TEX = (("512_12_grass_hill_1_diffuse", 12.0), ("grass2", 6.0), ("green_rock_big_diffuse", 9.0))
ROCK_ROT = {}
DETAIL_CONTRAST = 2.0
ROCK_CONTRAST = 3.0
FLOOR_STONES = (("256_7_grass_diffuse", 2.2), ("dirt_grass_diffuse", 3.0))
STRATA_COLS = {"left": (0, 300), "right": (1150, 1440)}   # the pine slope (left) and the crag slope (right)
CONTRAST_REGIONS = {"floor": ((300, 420, 1100, 600), (100, 720, 1800, 1000)),
                    "rightWall": ((1150, 100, 1430, 240), (1480, 100, 1900, 240))}

# ------------------------------------------------------------------------------------------------ periphery
ROCK_MESHES = {"Green_Rock_1x1": "green_rock_small_diffuse", "Green_Rock_2x2": "green_rock_big_diffuse"}
# No scrub: the meadow's tufts are grass, and vanilla bush_small_leaves is an alpha-card foliage mesh that the lane
# bakes as opaque RGB (Castle's sdgrade_pilot: black blots).
SCRUB_MESH, SCRUB_TEX = None, None
PERIPHERY_SCATTER = {
    "scrub": {"required": False, "reason": ("no scrub: the painted meadow carries grass tufts, not bushes, and the "
                                            "vanilla foliage mesh is alpha-card (the lane bakes opaque RGB)")},
    "rock": {"required": True, "prefixes": ["Mesh_Outer_boulders_"]},
    "nearDensity": {"source": "profile", "perM2": 0.0028,
                    "reason": "the olive-blob count reads a meadow's grass as scrub; Stronghold's measured density"}}
ROCK_SIZE_M = (1.0, 3.5)
SCRUB_SIZE_M = (1.2, 2.6)
SCRUB_ROW0 = 260
PERIPHERY_VANILLA_NOTE = ("vanilla towns ring the camera's sweep with grassy hills and meadow; the Rampart outer world "
                          "continues the painted forested slopes and meadow")
PERIPHERY_WATER = {"required": False, "reason": "the Rampart painting has no water body (its falls and pond are "
                   "building layers inside the frame); a continued water body would be invented"}

# ------------------------------------------------------------------------------------------------ near field
NEAR_ROCKS = ("Green_Rock_1x1", "Green_Rock_2x2")
PEBBLE = "Green_Rock_1x1"

# ------------------------------------------------------------------------------------------------ vanilla filler
VANILLA_TEXTURES = {
    "grass1": 512, "grass2": 512, "grass3": 512, "512_10_grass_forest_lawn_1_diffuse": 512, "dirt_ground3": 512,
    "512_12_grass_hill_1_diffuse": 512, "green_rock_big_diffuse": 512, "green_rock_small_diffuse": 512,
    "foliage_smallLeavesBush_diffuse": 1024, "256_7_grass_diffuse": 256, "dirt_grass_diffuse": 256,
}
VANILLA_VFX = {
    "WaterNormal": 1024, "TileNoise_07_vfx": 256, "TileNoise_23_vfx": 512, "TileNoise_19_vfx": 512,
    "glow_08_vfx": 256, "glow_10_vfx": 512, "glow_18_vfx": 64, "smoke_06_vfx": 256,
}
VANILLA_MESHES = ("Green_Rock_1x1", "Green_Rock_2x2", "bush_small_leaves")

# ------------------------------------------------------------------------------------------------ buildings
RELIEF_TUNE = {}
PARTS_LAYERS = set()        # no part separation until a review earns it (Stronghold's bar)
BACK_FILL_LAYERS = None     # every layer takes the edge-filled back (evaluation)
SOLID_TUNE = {}

# ------------------------------------------------------------------------------------------------ framing
# measured (town_full3d_framing.py measure, sdgrade_v2 stage, 2026-09-28; framing/rampart*.json): zoom 1.18 is the
# largest at which every building's body bounds stay inside the visible (non-HUD) region at the rest view with the
# building-centred aim (1.19 pushes the Dragon Cliffs tbrmdw_6_2 over the top frame and the Mystic Pond tbrmspec /
# tbrmext0 under the hero panel, the pond then reachable from no pose). The visible viewport goes from 66% painting to
# 91% at rest. panScale 0.5 as Stronghold / Castle: every pan pose >= 80% painting (62-73% before).
# 2026-10-19 no-split rebuild: 1.17 -- the uncut bodies of tbrmdw_6_2 and tbrmspec / tbrmext0 span 0.0296..0.7644,
# 0.0004 past both HUD edges at 1.18
FRAMING = {"zoom": 1.17, "aim": "buildings", "panScale": 0.5,
           "reason": "the painting fills the visible region between the HUD panels; the extension seams leave the view"}

# Layers cut by the painting's right frame edge, given a ragged geometric edge (stronghold_full3d_buildings.edge_fray;
# frame px): the Lvl3 dwelling's stone pillar, the Lvl7 cliff and the upgraded hall end in a straight line at x = TW
EDGE_FRAY = {lid: {"minPx": 10, "maxPx": 48, "sigmaPx": 5}
             for lid in ('tbrmdw_2', 'tbrmdw_2_2', 'tbrmdw_6_2', 'tbrmhal3')}

# Layers cut by the painting's BOTTOM frame edge (stronghold_full3d_buildings.edge_fray_bottom; frame px): the market, the fountain (spec / ext0) and the Lvl1 dwelling's fence end in a straight line at y = TH (seam_v1 rest, y673 run cols 1119-1381 and 295-402)
EDGE_FRAY_BOTTOM = {lid: {"minPx": 8, "maxPx": 36, "sigmaPx": 6}
                    for lid in ('tbrmmark', 'tbrmspec', 'tbrmext0', 'tbrmdw_0', 'tbrmdw_0_2')}
