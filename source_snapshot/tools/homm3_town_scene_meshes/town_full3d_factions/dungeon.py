"""Dungeon profile of the full-3D town lane (docs/homm3_stronghold_full_3d_town.md). An underground cavern: dark brown
limestone walls and a ceiling hung with stalactites, arched cave mouths along a middle ledge, a brown earth floor with
stalagmites, rows of painted (non-layer) mushroom-domed huts with candle lights, and a teal pool at the bottom left.
There is no open sky. Measured values say where they come from; hand-set values say so. Proof tier: staged candidate
only (no bundle, no install).
"""
from __future__ import annotations

# ------------------------------------------------------------------------------------------------ identity
FRACTION = "homm3_dungeon"
BACKGROUND = "Dungeon-in-background.png"
DATA_DIR = "homm3_dungeon_full3d"
BUNDLE = "homm3_town_scene3d_dungeon"
PREFIX = "homm3_dungeon3d_"
ASSET_ROOT = "Assets/Homm3TownScene3d/dungeon"
LABEL = "Dungeon"
FX_MODULE = "town_full3d_fx"   # the shared profile-classified effects module (FX_LAYERS below)

# Animated reachable layers (layers/anims/metadata.json frames > 1), classified from the DEF's changed-pixel mask
# (town_all/fx_probe/dungeon_changed.png, 2026-09-28). Kinds and filters are hand-set from that look; every place,
# extent, colour and timing is measured by town_full3d_fx from the DEF itself.
_SLIME = {"moves": "green slime oozes and drips down the warren's walls and door posts (small green px, all frames)",
          "effects": [{"kind": "glow", "why": "the slime's green shimmer, masked by the DEF's own changed px"}]}
_FLAME = {"hue": [15, 55], "minS": 0.55, "minV": 0.6}     # measured: candle flames are orange (hue 30-45, v > 0.7)
_HOARD = {"moves": "candle flames flicker and the treasure hoard glints (white/violet star sparkles)",
          "effects": [{"kind": "flame", "colour": _FLAME, "minPx": 8},
                      {"kind": "glints", "colourNot": _FLAME, "minPx": 8}]}
FX_LAYERS = {
    "tbdndw_0": _SLIME, "tbdndw_0_2": _SLIME, "tbdnhrd2": _SLIME,
    "tbdndw_2": {"moves": "the living beholder spire shimmers: light crawls over its whole fleshy body",
                 "effects": [{"kind": "glow"}]},
    "tbdndw_2_2": {"moves": "the living beholder spire shimmers: light crawls over its whole fleshy body",
                   "effects": [{"kind": "glow"}]},
    "tbdndw_6": _HOARD, "tbdndw_6_2": _HOARD,
    "tbdnext0": {"moves": "the ring of the portal of summoning sparkles (white/violet stars travel round it)",
                 "effects": [{"kind": "glints", "minPx": 8, "colour": {"minV": 0.6}}]},
}

# Building mask (stronghold_full3d_buildings.coherent_painting): only the rim-connected carried painting is cut from a
# sprite; dark castle px that match the dark cave within BG_EQUAL stay building (2026-10-18: holes in the fort's
# arches, the mage tower door).
MASK_PAINT_COHERENT = True

# ------------------------------------------------------------------------------------------------ scene / catalog
TO_SUN_CAM = (-0.55, 0.55, 0.62)   # hand-set as Castle / Stronghold (the albedo bake divides by the rig: rest unchanged)
# positions.json keys Dungeon's layers by DEF name (building_layer_map.json maps the OE SIDs onto them)
STATES = {
    "start": ["tbdnhall", "tbdntvrn", "tbdndw_0"],
    # reachable layers only (every render-state id must be a bundle prefab; the 2026-09-28 fx_v1 render refused
    # tbdnhall_4): the top reachable level of each building
    "full": ["tbdnhall_3", "tbdncstl_3", "tbdnmage_4", "tbdntvrn", "tbdnmark", "tbdnsilo", "tbdnblak", "tbdnspec",
             "tbdnholy", "tbdnext0", "tbdnhrd2", "tbdndw_0_2", "tbdndw_1_2", "tbdndw_2_2", "tbdndw_3_2", "tbdndw_4_2",
             "tbdndw_5_2", "tbdndw_6_2"],
    "anim": ["tbdnext0", "tbdndw_0", "tbdndw_2", "tbdndw_6", "tbdnhrd2"],
}
WATER_USE = "the painted teal pool at the bottom left (inside the painting; the lane builds no water body for it)"

# ------------------------------------------------------------------------------------------------ sky
# Underground: there is no open sky anywhere in the painting (the top rows are the stalactite ceiling), so the painted
# sky mask and the fill's sky are both empty (rule "none"); the extension's top rows are graded as rock like the rest.
SKY_MASK = {"rule": "none", "reason": "underground cavern: the top of the painting is the rock ceiling, no open sky",
            "extension": {"rule": "none"}}
SKY_ANIM = {"mode": "none", "reason": "underground cavern: no open sky to drift"}
ANIM_CROSSWALK = {}   # every layers/anims id is a positions.json layer id (checked 2026-09-28: 14 of 14)

# ------------------------------------------------------------------------------------------------ framing
# measured (town_full3d_framing.py measure, sdgrade_v2 stage, 2026-09-28; town_all/framing/dungeon*.json): zoom 1.18 is
# the largest at which every building's body bounds stay inside the visible (non-HUD) region at the rest view with the
# building-centred aim (1.19 pushes the Dragon Cave tbdndw_6 over the top frame and the marketplace / artifact merchant
# tbdnmark / tbdnspec under the hero panel, the last two then reachable from no pose). The visible viewport goes from
# 66% painting to 91% at rest. panScale 0.5 as Stronghold / Castle: every pan pose >= 80% painting (57-74% before).
FRAMING = {"zoom": 1.18, "aim": "buildings", "panScale": 0.5,
           "reason": "the painting fills the visible region between the HUD panels; the extension seams leave the view"}

# ------------------------------------------------------------------------------------------------ texture (sdgrade)
TEX = {
    "styleCropNative": (150, 60, 550, 300),
    # p1 ("vast underground limestone cavern ... stalactites ... dim warm light", seeds 11/23/37) painted a pale white
    # limestone grotto with giant white dripstone columns and root-like flows, far brighter than the painting
    # (sdinpaint_runs/p1_s*_props): superseded. p2 asks for the painting's dark brown rock and says no to white.
    "sd": {"prompt": ("a matte painting of a dark underground cavern, rough dark brown rock walls, small stalactites "
                      "on the rock ceiling, a dark brown earth cave floor with scattered small stones, dim warm light, "
                      "deep shadows, painterly, detailed"),
           "negative": ("white, pale, bright, sunlight, sunbeam, daylight, sky, tree roots, pillar, column, "
                        "building, house, hut, dome, mushroom, tent, tower, castle, wall, fence, person, animal, "
                        "candle, lamp, lantern, torch, fire, glow, water, pool, lake, river, cloud, grass, tree, plant, "
                        "green, blue, text, watermark, signature, frame, border, blurry, lowres, jpeg artifacts, photo"),
           "promptKey": "p2", "seed": 23, "context": "props"},
    # seed 23 of p2 (11 / 23 / 37 explored, sdinpaint_runs/p2_s*): a cave mouth and dripstone left, a rock wall and a
    # stony floor right, no signature scribbles; seed 11 cloned gold nuggets (the huts' domes) onto the right floor.
    "clean": [],
    "integrate": {"esrgan": True, "grain": True,
                  "paintFloor": (600, 604, 830, 671),   # bare earth at the bottom middle, clear of the huts (>= 64 rows: the grain patch)
                  "floorRamp": (410, 500)},              # grain weight 0 above (walls, ceiling), 1 below (floor)
    "grade": {"floorRows": (600, 665), "cliffRows": 400, "floorzRows": 470, "extOnlyBands": True},
    # the painted mushroom-domed huts: golden thatch domes and lit walls (hue 50-100 deg, chroma > 14) on the floor
    # rows; measured: bare floor L* p95 17-20, chroma p95 9-12; hut domes chroma p50 20-25. No white rule.
    "propMask": {"rule": "hue_white", "hueMin": 50.0, "hueMax": 100.0, "chromaMin": 14.0, "lMax": 90.0,
                 "whiteL": 101.0, "whiteChromaMax": 0.0, "close": 5, "minArea": 150, "dilate": 11, "minRow": 380},
    # toneRows: the cave walls beside the side edges; faded to 0 on the floor. Seam opt-ins (dg_v2_edge, measured on
    # the rest preview): bottomMirrorPx - the painted floor's dark last rows against the fill's lit stones (y673 p90
    # 5.39 -> 1.54); edgeSource paintedAll + writeExtBuildingMask + toneLMode gain - rows 40-100 beside the Dragon
    # Cave's painted near-black backdrop, where the additive tone shift clipped the extension to a flat L* 0 and the
    # edge blend skipped the rows (x1440 p90 4.17 -> 3.08).
    # rightMirrorPx 8 + rightMirrorMode offset (dg_v4_edge): the Unity rest render read 3.60 at x1440 (rows 91-141
    # near-black ceiling; rows 320-400 / 530-572 the low-pass edge's residual step); canvas seam 3.03 -> 0.80. The
    # reflect mode (dg_v3_edge, Unity 0.59) doubled the painting's own darker column at x 1436-1437 into a symmetric
    # zipper (rejected on review); skipping those columns in the reflection re-opened the step (3.10-3.90).
    "blend": {"toneRows": (400, 480), "bottomMirrorPx": 24, "writeExtBuildingMask": True,
              "toneLMode": "gain", "edgeSource": "paintedAll", "rightMirrorPx": 8, "rightMirrorMode": "offset"},
    # right-edge bridge (town_full3d_sdfill --step bridge, between grade and blend): the painting's cave wall, ceiling
    # and floor continued into a band of the extension (fx_v1 rest seam-line x = TW p90 9.06 / run 168: the fill's
    # smoother, lighter cave meets the painted rock in a straight line; canvas rows 560-620 ratio 3.6-5.3). No sky.
    "bridge": {"prompt": ("a matte painting of a dark underground cavern, rough dark brown rock walls with deep "
                          "crevices, a dark rock ceiling, a dark brown earth cave floor with scattered stones, dim warm "
                          "light, deep shadows, painterly, detailed"),
               "negative": ("white, pale, bright, sunlight, daylight, sky, building, house, hut, dome, mushroom, tent, "
                            "tower, castle, wall, fence, gold, treasure, candle, lamp, lantern, torch, fire, flame, "
                            "glow, person, animal, dragon, tree, water, text, watermark, signature, frame, border, "
                            "seam, vertical line, blurry, lowres, jpeg artifacts, photo"),
               "seed": 23, "bandPx": 192, "fadePx": 96, "rowsBelowPx": 48, "contextPx": 560, "strength": 0.75,
               "rectContext": None,
               # the building mask's margin past the edge (the artifact merchant tbdnspec, the Dragon Cave) kept the
               # raw fill's specks, a dotted line at x = TW once EDGE_FRAY cuts the buildings back
               "writeExtBuildingMask": True},
    "renderRefPass": True,
}

# ------------------------------------------------------------------------------------------------ terrain
# measured (town_all/dungeon/measure_horizon.py + hut crops): the monocular depths do not give a usable floor
# vanishing row here (Depth Pro inverse depth is nearly flat over the cave floor: its zero lands above the frame; DA V2
# is relative, zero undefined). The hut walls do: five like huts on the right floor (base HoMM3 y 290-346, wall 13-19
# px, dome rim to base) regress to wall = 0.106 (base - 167). Rounded to 170; uncertain by about +-10 px.
HORIZON_HOMM3_Y = 170.0
# measured: those five huts' walls are 0.541-0.565 camera units at their depth on this floor plane (median 0.55);
# one-storey eave hand-set 2.2 m as Stronghold's and Castle's (the domes are then ~4 m across).
HUT_WALL_UNITS, HUT_EAVE_M = 0.55, 2.2
FAR_CAP_M = 250.0   # hand-set: the cavern's back wall closes the view; nothing reads as open distance
# Hand-traced floor polygon (HoMM3 px): the lower cave floor, left and right of the central rock mound (excluded).
FLOOR_POLY_HOMM3 = [(0, 228), (50, 232), (100, 228), (150, 224), (200, 222), (250, 225), (255, 300), (300, 328),
                    (380, 336), (450, 322), (468, 245), (500, 220), (550, 215), (600, 218), (650, 222), (700, 240),
                    (760, 290), (800, 298), (800, 374), (0, 374)]
SPUR_SCALE, SPUR_AMP = 8.0, 0.6   # hand-set: rugged cave walls, between Castle's hills and Stronghold's badlands
WALL_SHIFT_M = 60.0               # hand-set: the cavern walls close round the camera

# ------------------------------------------------------------------------------------------------ ground
FLOOR_TEX = (("dirt_ground1", 4.4), ("dirt_ground2", 5.0), ("dirt_ground4", 5.0), ("road_dirt", 6.0))
ROCK_TEX = (("512_3_dirt_rock1_diffuse", 12.0), ("dirt_ground1", 6.0), ("512_4_dirt_rock2_diffuse", 9.0))
ROCK_ROT = {}
DETAIL_CONTRAST = 2.0
ROCK_CONTRAST = 3.0
FLOOR_STONES = (("256_1_dirt_stines_texture", 2.2), ("512_3_dirt_rock1_diffuse", 3.0))
STRATA_COLS = {"left": (0, 300), "right": (1150, 1440)}
CONTRAST_REGIONS = {"floor": ((600, 600, 840, 665), (100, 720, 1800, 1000)),
                    "rightWall": ((1150, 150, 1430, 450), (1480, 150, 1900, 600))}

# ------------------------------------------------------------------------------------------------ periphery
ROCK_MESHES = {"dirt_rock1": "512_3_dirt_rock1_diffuse", "dirt_rock2": "512_4_dirt_rock2_diffuse",
               "dirt_rock3": "512_5_dirt_rock3_diffuse", "dirt_rock4": "512_6_dirt_rock4_diffuse"}
SCRUB_MESH, SCRUB_TEX = None, None
PERIPHERY_SCATTER = {
    "scrub": {"required": False, "reason": ("no scrub: the painted cave floor carries stalagmites, not plants, and the "
                                            "vanilla extraction has no stalagmite mesh")},
    "rock": {"required": True, "prefixes": ["Mesh_Outer_boulders_"]},
    "nearDensity": {"source": "profile", "perM2": 0.0028,
                    "reason": "the olive-blob count reads plant scrub, which a cave floor lacks; Stronghold's measured "
                              "density"}}
ROCK_SIZE_M = (1.0, 3.5)
SCRUB_SIZE_M = (1.2, 2.6)
SCRUB_ROW0 = 400
PERIPHERY_VANILLA_NOTE = ("the Dungeon outer world continues the painted cavern walls and earth floor with the vanilla "
                          "dirt rocks as scatter")
PERIPHERY_WATER = {"required": False, "reason": "the painted pool is a still pond in the frame's bottom-left corner; "
                   "no river or open water continues beside the pans, a continued water body would be invented"}

# ------------------------------------------------------------------------------------------------ near field
NEAR_ROCKS = ("dirt_rock1", "dirt_rock2", "dirt_rock3")
PEBBLE = "dirt_rock4"

# ------------------------------------------------------------------------------------------------ vanilla filler
VANILLA_TEXTURES = {
    "dirt_ground1": 512, "dirt_ground2": 512, "dirt_ground4": 512, "road_dirt": 512,
    "512_3_dirt_rock1_diffuse": 512, "512_4_dirt_rock2_diffuse": 512, "512_5_dirt_rock3_diffuse": 512,
    "512_6_dirt_rock4_diffuse": 512, "256_1_dirt_stines_texture": 256,
}
VANILLA_VFX = {
    "WaterNormal": 1024, "TileNoise_07_vfx": 256, "TileNoise_23_vfx": 512, "TileNoise_19_vfx": 512,
    "glow_08_vfx": 256, "glow_10_vfx": 512, "glow_18_vfx": 64, "smoke_06_vfx": 256,
}
VANILLA_MESHES = ("dirt_rock1", "dirt_rock2", "dirt_rock3", "dirt_rock4")

# ------------------------------------------------------------------------------------------------ buildings
RELIEF_TUNE = {}
PARTS_LAYERS = set()        # no part separation until a review earns it (Stronghold's bar)
BACK_FILL_LAYERS = None     # every layer takes the edge-filled back (evaluation)
SOLID_TUNE = {
    "tbdnmage": {"n": 2.0}, "tbdnmage_2": {"n": 2.0}, "tbdnmage_3": {"n": 2.0}, "tbdnmage_4": {"n": 2.0},
    "tbdnmage_5": {"n": 2.0},   # round minaret towers
}

# ------------------------------------------------------------------------------------------------ edge fray
# Layers cut by the painting's frame edges, given a ragged geometric edge (stronghold_full3d_buildings.edge_fray /
# edge_fray_bottom; frame px, geometry only). Measured on fx_v1 at rest (town_all/dungeon/edge_layers.py): the Dragon
# Cave tbdndw_6 / _6_2 (rows 25-144) and the Grail tbdnholy (rows 112-171) end in a straight line at x = TW (seam-line
# ratio 17-41 over rows 40-120), the artifact merchant tbdnspec at both edges; at y = TH the pool's dwellings
# tbdndw_0 / _0_2 and horde tbdnhrd2 (cols 1-255), tbdndw_2 / _2_2 (217-396), the marketplace tbdnmark (1174-1394:
# ratio 5.5-9.3). The canvas under them is the cleaned painting, so the fray uncovers the cave, not a painted sprite.
EDGE_FRAY = {lid: {"minPx": 10, "maxPx": 48, "sigmaPx": 5}
             for lid in ("tbdndw_6", "tbdndw_6_2", "tbdnholy", "tbdnspec")}
EDGE_FRAY_BOTTOM = {lid: {"minPx": 8, "maxPx": 36, "sigmaPx": 6}
                    for lid in ("tbdndw_0", "tbdndw_0_2", "tbdnhrd2", "tbdndw_2", "tbdndw_2_2", "tbdnmark", "tbdnspec")}
