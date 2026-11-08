"""Tower profile of the full-3D town lane (docs/homm3_stronghold_full_3d_town.md). An alpine gorge under a clouded blue
sky: two snow-capped rock massifs close the frame left and right, a far green valley and distant ranges show through
the gap, painted stone cottages with moss roofs climb both slopes and fill the snowfield at the bottom right, a paved
plaza and a small pool sit at the bottom left. Measured values say where they come from; hand-set values say so.
Proof tier: staged candidate only (no bundle, no install).
"""
from __future__ import annotations

# ------------------------------------------------------------------------------------------------ identity
FRACTION = "homm3_tower"
BACKGROUND = "Tower-in-background.png"
DATA_DIR = "homm3_tower_full3d"
BUNDLE = "homm3_town_scene3d_tower"
PREFIX = "homm3_tower3d_"
ASSET_ROOT = "Assets/Homm3TownScene3d/tower"
LABEL = "Tower"
FX_MODULE = "town_full3d_fx"   # the shared profile-classified effects module (FX_LAYERS / ANIM_OFFSETS below)

# The three animated dwellings, classified from each DEF's changed-px mask (town_all/t2b/tower_chg.png and the frame
# strips tw0_frames.png / tw2_frames.png, 2026-09-29). Kinds are hand-set from that look; place, extent, colour and
# timing are measured by town_full3d_fx. Rects are DEF px (ANIM_OFFSETS converts to sprite px).
FX_LAYERS = {
    "tbtwdw_0_2": {"moves": "the brass pendulum bob under the clock swings side to side behind the frame's braces "
                            "(one swing per 20-frame loop; fit_swing puts the pivot under the clock face)",
                   "effects": [{"kind": "swing", "rects": [[15, 30, 55, 66]],
                                "colour": {"hue": [30, 70], "minS": 0.35, "minV": 0.4},
                                "why": "the brass bob; the dark braces and posts in front of it never change"}]},
    "tbtwdw_2_2": {"moves": "steam puffs from the four chimney tops; sparks glint in the dark works and on the white "
                            "coil at the left",
                   "effects": [{"kind": "smoke", "rects": [[21, 0, 74, 23]], "minPx": 40},
                               {"kind": "glints", "rects": [[5, 40, 70, 95]], "minPx": 6}]},
    "tbtwdw_6_2": {"moves": "a lightning bolt strikes from the storm cloud down onto the golden dome",
                   "effects": [{"kind": "lightning", "minPx": 40}]},
}

# ------------------------------------------------------------------------------------------------ scene / catalog
TO_SUN_CAM = (-0.55, 0.55, 0.62)   # hand-set: the massifs' and towers' lit faces look left and toward the camera
# positions.json keys Tower's 35 layers by DEF name (tbtw*, sprites tbtw*.dir.png); building_layer_map.json maps the OE
# SIDs onto them. The other 83 PNGs in layers/ (artifactMarket.png, dwellingUp2Lvl3_1.png ...) are an older
# OE-SID-keyed copy that no positions.json layer names: the lane never reads them.
# tbtwext0 / tbtwext1 are positions.json layers that no OE level reaches (building_layer_map nativeLevels), so they are
# not in the bundle and the full state leaves them out (the first tw_v3 render refused "prefab tbtwext0 not in bundle").
STATES = {
    "start": ["tbtwhall", "tbtwtvrn", "tbtwdw_0"],
    "full": ["tbtwhall_4", "tbtwcstl_3", "tbtwmage_4", "tbtwtvrn", "tbtwmark", "tbtwsilo", "tbtwblak", "tbtwspec",
             "tbtwext2", "tbtwholy", "tbtwdw_0_2", "tbtwdw_1_2", "tbtwdw_2_2", "tbtwdw_3_2",
             "tbtwdw_4_2", "tbtwdw_5_2", "tbtwdw_6_2"],
    "anim": ["tbtwdw_0_2", "tbtwdw_2_2", "tbtwdw_6_2"],
}
WATER_USE = "the painted pool at the bottom left (inside the painting; it meets the rect's bottom edge only)"

# ------------------------------------------------------------------------------------------------ sky
# Clouded blue sky over snow peaks. Colour cannot split them: cumulus reads L* 77-100 b* -19..+0.5 and the snow peaks
# L* 63-100 b* -23..+2 (measured boxes, frame rect). The lane's own Depth Anything V2 Large disparity does: every sky /
# cloud box reads 0.00 (p5..p95), the left peak 103-125, the right peak 0-127 (its box grazes sky). So the CIELAB box of
# Castle (b* < 2, L* > 40) is kept and the mask also requires da_large < 0.5 (town_full3d_masks daMax, hand-set
# threshold; 0.5 and 3.0 give 218190 / 220579 px, the difference is the far range's tops through the gap, which stay
# terrain at 0.5). The fill's own sky: the same box; its snow peaks may read as sky there and keep their fill colour
# ungraded (harmless, as Castle's), capped at frame row 300 (hand-set, above the fill's slopes).
SKY_MASK = {"rule": "lab", "reason": "blue sky with white cumulus over snow peaks; the peaks are cut by disparity",
            "bMax": 2.0, "lMin": 40.0, "daMax": 0.5,
            "extension": {"bMax": 2.0, "lMin": 40.0, "maxRow": 300}}
# seam pass (tw_v2_edge, Cove's recipe 951e6e7995): the canvas (bridged massif, peaks and sky) carried across the right
# edge onto the dome (town_full3d_sky._edge_join, method canvas; topFadePx: the directions above the rect's top fade to
# the panorama, not the clamped top row)
# (no SKY_EDGE_MATCH: its low-pass shift, blue sky -> the painted white cloud, tinted the panorama's white cumulus
# peach above the rect's top-right corner in the cursor poses)
SKY_EDGE_JOIN = {"method": "canvas", "edges": ["right"], "fadePx": 240, "rectFeather": False, "topFeather": False,
                 "canvasSkyOnly": False, "topFadePx": 32,
                 "reason": "the cold panorama beside the painted rect does not continue the painted cumulus and peaks"}
SKY_ANIM = {"mode": "deferred", "reason": "the periodic 360 deg sky band is being rebuilt in the parent's change; "
            "drift follows it"}
# the static dome's periodic 360 deg panorama outside the painted sky (town_full3d_sky kit, then town_full3d_sdfill.py --step sky):
# the mirror dome streaked right of the painted rect under the sweeps
SKY_PANO = {"key": "p1_s11", "seed": 11,
            "prompt": "hand-painted fantasy game background sky, 1990s painted matte art, cold winter sky, pale blue with drifting white and grey snow clouds, crisp alpine light, sky and clouds only",
            "negative": "sun disc, sunset, orange, warm, photo, photorealistic, land, ground, hills, mountains, trees, water, building, tower, person, bird, horizon line, text, watermark, frame, border, seam, lowres"}
# DEF ids in layers/anims/metadata.json that are not positions.json layer ids -> the layer they animate. Measured: each
# DEF's frame 0 against every positions sprite at its best offset (identical opaque px / overlapping opaque px), and
# checked by eye (town_all/tower/anim_crosswalk.png): the Tower anims were cut from a different extraction, so frame 0
# is not pixel-identical to any layer sprite.
#   dwellingUp2Lvl1_1 (71x76, 20 frames)  -> tbtwdw_0_2 (tbtwup_0, 71x64): 2829 / 2999 px identical at dy 0, dx 6
#   dwellingUp2Lvl3_1 (127x108, 20)        -> tbtwdw_2_2 (tbtwup_2, 127x108): same box; 2018 / 8400 identical (repaletted)
#   dwellingUp2Lvl7_1 (223x173, 10)        -> tbtwdw_6_2 (tbtwup_6, 139x173): frame 0 adds the storm cloud 84 px above;
#                                            970 / 12358 identical (repaletted), same temple by eye
ANIM_CROSSWALK = {"dwellingUp2Lvl1_1": "tbtwdw_0_2", "dwellingUp2Lvl3_1": "tbtwdw_2_2", "dwellingUp2Lvl7_1": "tbtwdw_6_2"}
# sprite origin in DEF px (sprite px = DEF px - (dx, dy)) for the DEFs whose box differs from their sprite, refit
# 2026-09-29 by town_all/t2b/offset_fit.py (identical px / overlapping opaque px at the best offset):
#   dwellingUp2Lvl1_1 (76x71 DEF, 64x71 sprite): (6, 0), 2909 / 2999; dwellingUp2Lvl7_1 (173x223, 173x139): (0, 84),
#   12325 / 12358 (the storm cloud is the DEF's top 84 rows; the bolt floats above the dome). Lvl3 is the same box.
ANIM_OFFSETS = {"dwellingUp2Lvl1_1": [6, 0], "dwellingUp2Lvl7_1": [0, 84]}

# ------------------------------------------------------------------------------------------------ framing
# measured (town_full3d_framing.py measure, sdgrade_pilot stage, 2026-09-28; framing/tower*.json): zoom 1.22 is the
# largest at which every building's body bounds stay inside the visible (non-HUD) region at the rest view with the
# building-centred aim (1.23 pushes the castle spires (tbtwcstl*, drawn from HoMM3 y 0) over the top frame, the
# upgraded Genie dwelling tbtwdw_4_2 (from y 8) and the capitol too, and the marketplace and tavern under the hero panel, where
# no pose reaches them). The visible viewport goes from 66% painting to 96% at rest. panScale 0.5 as Stronghold and
# Castle: every pan pose >= 79% painting (60-71% before).
FRAMING = {"zoom": 1.22, "aim": "buildings", "panScale": 0.5,
           "reason": "the painting fills the visible region between the HUD panels; the extension seams leave the view"}

# ------------------------------------------------------------------------------------------------ texture (sdgrade)
TEX = {
    "styleCropNative": (120, 40, 620, 300),   # the massifs, the gap and the slope cottages (hand-set)
    # seeds 11 / 23 / 37 viewed (town_all/tower/sdfill_seeds.png): 11 and 37 grow smoke-like grey clouds over the
    # right extension's snowfield; 23 continues the right massif as a jagged snow range and the left side as a snowy
    # shelf with a few meltwater puddles by the painted pool. seed 23.
    "sd": {"prompt": ("a matte painting of a high alpine gorge, grey granite massifs with deep snow fields and "
                      "snow-capped peaks, snowy slopes with scattered grey boulders, a flat snowfield in the valley, "
                      "bright afternoon sunlight from the left, deep blue sky with white cumulus clouds, painterly, "
                      "detailed"),
           "negative": ("building, house, cottage, roof, hut, tower, castle, wall, fence, person, animal, road, path, "
                        "river, water, lake, pool, green meadow, grass, desert, sand, red rock, text, watermark, "
                        "signature, frame, border, blurry, lowres, jpeg artifacts, photo"),
           "promptKey": "p1", "seed": 23, "context": "props"},
    "clean": [],
    "integrate": {"esrgan": True, "grain": True,
                  "paintFloor": (760, 606, 995, 672),   # bare snowfield (HoMM3 x 422-553, y 337-373), clear of the cottages; >= 64 rows (grain patch)
                  "floorRamp": (430, 560)},             # grain weight 0 above (massifs, sky), 1 below (snowfield)
    "grade": {"floorRows": (615, 665), "cliffRows": 400, "floorzRows": 480, "extOnlyBands": True},
    # the painted cottages: moss roofs (hue ~95-110 deg) and orange-brown door arches / trim (hue ~40-62 deg), chroma
    # > 12 (measured boxes: roof C* median 8-14 p90 15-19, trim p90 29; the dirt field and plaza C* median 7.7-8.5);
    # no white term (the snow is white). Hand-set closing / area. False positives measured on the probe: the pool's tan
    # rocks and parts of the dirt field (grade statistics exclude them too, which is harmless).
    "propMask": {"rule": "hue_white", "hueMin": 40.0, "hueMax": 118.0, "chromaMin": 12.0, "lMax": 80.0,
                 "whiteL": 101.0, "whiteChromaMax": 0.0, "close": 5, "minArea": 200, "dilate": 7, "minRow": 0},
    "blend": {"toneRows": (400, 520),   # the massifs beside the side edges; faded to 0 on the snowfield
              # seam pass (Cove's recipe, 951e6e7995; candidate tw_v2_edge): the edge blend also takes the building
              # mask's margin and every painted pixel at the edge, the sky beside the edges, and a mirrored crossfade
              # over the first columns right of x = TW and rows below y = TH (sky_v1 rest seam-line x = TW p90 8.09
              # run 101, y = TH p90 4.74 run 246); bottomSourceHut: the propMask's hue rule also takes the gravel
              # plaza and the pool's tan rocks on the last rows (cols 40-285, 981-1050, 1183-1221), which left the
              # bottom edge unblended there (tw_v2_edge without it: y = TH run 162)
              "writeExtBuildingMask": True, "edgeSource": "paintedAll", "sideEdgeSky": True,
              "rightMirrorPx": 12, "bottomMirrorPx": 24, "bottomSourceHut": True},
    # right-edge bridge (town_full3d_sdfill --step bridge, between grade and blend): the painted massif, snow peaks,
    # cumulus and snowfield continued into a band of the extension
    "bridge": {"prompt": ("a matte painting of a high alpine gorge, a grey granite massif with deep snow fields and "
                          "snow-capped peaks continuing to the right, deep blue sky with white cumulus clouds, snowy "
                          "slopes with scattered grey boulders descending to a flat snowfield, bright afternoon "
                          "sunlight from the left, painterly, detailed"),
               "negative": ("building, house, cottage, roof, hut, tower, castle, wall, fence, person, animal, road, "
                            "river, water, lake, green meadow, grass, desert, sand, red rock, smoke, text, watermark, "
                            "signature, frame, border, seam, vertical line, blurry, lowres, jpeg artifacts, photo"),
               "seed": 11, "bandPx": 192, "fadePx": 96, "rowsBelowPx": 48, "contextPx": 560, "strength": 0.75,
               "writeSky": True, "writeExtBuildingMask": True,
               "rectContext": "buildingsInpainted", "stripPx": 48, "stripRows": (0, 673)},
    "renderRefPass": True,
}

# ------------------------------------------------------------------------------------------------ terrain
# Horizon: the flat patches do not agree on one plane (the dirt field is a raised shelf). Measured, per-row medians of
# the disparity over three flat patches (dirt field, snowfield, plaza; town_all/tower/measure_horizon.py): DA V2 Large
# linear fit -> HoMM3 y 153.1; Depth Pro -> 94.1 (its per-patch slopes disagree 3.5x, rejected). Cross-check by the
# cottages' own size on the floor: a 19 px wall at base y 333 and a 15 px wall at base y 300 give the same camera size
# (3% apart) at horizon 155 and 1% at 175-180 (7% at 120). The painted far range's foot through the gap sits near
# y 160. Taken 160 (hand-set within the measured 153-180).
HORIZON_HOMM3_Y = 160.0
# measured at horizon 160 (town_all/tower/hut_units.py): the long cottage at HoMM3 x 425-510 has a 19 px wall (eave
# y 314 to base y 333) = 0.61 camera units; the back cottage at x 598-650 (15 px at base 300) 0.59. Eave hand-set
# 2.2 m as Stronghold's.
HUT_WALL_UNITS, HUT_EAVE_M = 0.60, 2.2
FAR_CAP_M = 400.0
# Hand-traced floor polygon (HoMM3 px): the plaza, the pool, the snowfield and the dirt shelf below both massifs' feet.
FLOOR_POLY_HOMM3 = [(0, 292), (90, 292), (175, 300), (250, 305), (300, 330), (420, 330), (440, 300), (470, 262),
                    (560, 258), (700, 258), (800, 262), (800, 374), (0, 374)]
SPUR_SCALE, SPUR_AMP = 8.0, 0.7   # hand-set: steep granite spurs, between Stronghold's badlands and Castle's hills
WALL_SHIFT_M = 60.0               # hand-set: the massifs close round the camera

# ------------------------------------------------------------------------------------------------ ground
# (vanilla texture, metres per tile) - hand-set. Viewed (town_all/tower/vanilla_tex.png): Snow1 / Snow2 / Snow5 tile
# (rock-streaked snow, fine powder, wind ripples); 1024_9/10/11_snow_0x, 1024_6_Snow_Ice_01 and snow_rock_0x are mesh UV
# atlases (not tileable), Snow4 is cracked ice (no ice in the painting): none of those is used as tiling detail.
FLOOR_TEX = (("Snow2", 4.0), ("Snow5", 5.0), ("Snow1", 6.5))
ROCK_TEX = (("1024_1_mountain_large_snow_diffuse", 12.0), ("Snow1", 6.0), ("Snow5", 9.0))
ROCK_ROT = {}
DETAIL_CONTRAST = 2.0
ROCK_CONTRAST = 3.0
FLOOR_STONES = (("256_2_snow_stones_texture", 2.2), ("Snow1", 3.0))
STRATA_COLS = {"left": (0, 300), "right": (1150, 1440)}
CONTRAST_REGIONS = {"floor": ((780, 610, 1100, 665), (100, 720, 1800, 1000)),
                    "rightWall": ((1150, 150, 1430, 400), (1480, 150, 1900, 500))}

# ------------------------------------------------------------------------------------------------ periphery
ROCK_MESHES = {"Snow_Rock_01": "snow_rock_01_diffuse", "Snow_Rock_02": "snow_rock_02_diffuse",
               "Snow_Rock_03": "snow_rock_03_diffuse"}
SCRUB_MESH, SCRUB_TEX = None, None
PERIPHERY_SCATTER = {
    "scrub": {"required": False, "reason": ("no scrub: the painted snowfield and slopes carry no bushes (a few pines on "
                                            "the far right ridge only)")},
    "rock": {"required": True, "prefixes": ["Mesh_Outer_boulders_"]},
    "nearDensity": {"source": "profile", "perM2": 0.0028,
                    "reason": "the olive-blob count finds no scrub on snow; Stronghold's measured density"}}
ROCK_SIZE_M = (1.0, 4.0)
SCRUB_SIZE_M = (1.2, 2.6)
SCRUB_ROW0 = 400
PERIPHERY_VANILLA_NOTE = ("vanilla snow towns ring the camera with snow hills and rocks; the Tower outer world "
                          "continues the painted massifs and snowfield")
PERIPHERY_WATER = {"required": False, "reason": "the painted pool meets only the rect's bottom edge; the frame "
                   "extension below carries its continuation as texture and no pan pose looks past it, so a continued "
                   "water body would be invented"}

# ------------------------------------------------------------------------------------------------ near field
NEAR_ROCKS = ("Snow_Rock_01", "Snow_Rock_02", "Snow_Rock_03")
PEBBLE = "Snow_Rock_03"

# ------------------------------------------------------------------------------------------------ vanilla filler
VANILLA_TEXTURES = {
    "Snow1": 1024, "Snow2": 1024, "Snow5": 1024, "1024_1_mountain_large_snow_diffuse": 1024,
    "snow_rock_01_diffuse": 1024, "snow_rock_02_diffuse": 1024, "snow_rock_03_diffuse": 1024,
    "256_2_snow_stones_texture": 256,
}
VANILLA_VFX = {
    "WaterNormal": 1024, "TileNoise_07_vfx": 256, "TileNoise_23_vfx": 512, "TileNoise_19_vfx": 512,
    "glow_08_vfx": 256, "glow_10_vfx": 512, "glow_18_vfx": 64, "smoke_06_vfx": 256,
}
VANILLA_MESHES = ("Snow_Rock_01", "Snow_Rock_02", "Snow_Rock_03")

# ------------------------------------------------------------------------------------------------ buildings
# the Skyship (Grail, tbtwholy) hangs in the sky: no terrain below its sprite (sdgrade_pilot stage: "no footing found").
# Hand-set 130 m: its mooring ropes end over the Golem Factory, whose own footing measured 128.0 m (tbtwdw_2).
RELIEF_TUNE = {"tbtwholy": {"floatZm": 130.0}}
PARTS_LAYERS = set()        # no part separation until a review earns it (Stronghold's bar)
BACK_FILL_LAYERS = None     # every layer takes the edge-filled back (evaluation)
SOLID_TUNE = {}

# ------------------------------------------------------------------------------------------------ edge fray
# seam pass (tw_v2_edge): the building layers that reach the right edge (x > TW - 40 at rest) and the bottom edge
# (y > TH - 40) end in ragged geometric edges so the bridged / mirrored canvas shows through
# (stronghold_full3d_buildings.edge_fray; geometry only, no texel is recoloured).
EDGE_FRAY = {lid: {"minPx": 8, "maxPx": 40, "sigmaPx": 6} for lid in ("tbtwdw_5_2", "tbtwmark", "tbtwsilo")}
EDGE_FRAY_BOTTOM = {lid: {"minPx": 8, "maxPx": 40, "sigmaPx": 6}
                    for lid in ("tbtwblak", "tbtwmark", "tbtwspec", "tbtwtvrn")}
# tbtwhall_4 left the bottom list on the 2026-09-29 restage (tw_v3): with the committed solids fixes its geometry ends
# at y 632.4, above the fray band (TH - 40 = 633), and edge_fray refuses a layer that does not reach it.

# Building mask (stronghold_full3d_buildings.coherent_painting), as Dungeon: only the rim-connected carried painting is
# cut from a sprite (2026-10-18 no-Meshy nm1 rollout, all buildings solid + MoGe relief).
MASK_PAINT_COHERENT = True
