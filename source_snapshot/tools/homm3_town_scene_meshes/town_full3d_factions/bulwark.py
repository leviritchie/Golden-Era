"""Bulwark profile of the full-3D town lane (docs/homm3_stronghold_full_3d_town.md). A snowbound mountain valley at night:
a dark teal-green starry sky with a full moon at the top right, jagged snow-capped peaks and one dark green peak across
the back, a snow-dusted rock cliff at the left, a snowfield with grey rock outcrops, a dark river running from the
middle to the bottom edge under a stone bridge, and painted (non-layer) yurts scattered on the snow at the bottom left,
the right slope and the bottom edge. Measured values say where they come from; hand-set values say so.
Proof tier: staged candidate only (no bundle, no install).
"""
from __future__ import annotations

# ------------------------------------------------------------------------------------------------ identity
FRACTION = "homm3_bulwark"
BACKGROUND = "Bulwark-in-background.png"
DATA_DIR = "homm3_bulwark_full3d"
BUNDLE = "homm3_town_scene3d_bulwark"
PREFIX = "homm3_bulwark3d_"
ASSET_ROOT = "Assets/Homm3TownScene3d/bulwark"
LABEL = "Bulwark"
FX_MODULE = "town_full3d_fx"   # the shared profile-classified effects module (FX_LAYERS below)

# Animated reachable layers classified from the DEF's changed-pixel mask (town_all/fx_probe/bulwark_changed.png,
# 2026-09-28). Kinds are hand-set from that look; place, extent, colour and timing are measured by town_full3d_fx.
# Window / hearth fires are orange (measured hue 13-36); rune and spirit lights are teal-blue (hue 170-201).
_FIRE = lambda what, n=4: {"moves": f"{what} flicker (orange firelight)", "effects": [{"kind": "flame", "minPx": n}]}
_EMBER = lambda what, n: {"moves": f"{what} flickers ({n} changed px: a single ember-sized glow)",
                          "effects": [{"kind": "glow", "minPx": 1}]}
_RUNES = {"moves": "the blue rune lights on the tower pulse", "effects": [{"kind": "glow", "minPx": 20}]}
FX_LAYERS = {
    "tbbha201": _EMBER("the hall's door lantern", 3), "tbbha301": _EMBER("the hall's door lantern", 1),
    "tbbuha01": _EMBER("the hall's door lantern", 3), "tbbutv01": _EMBER("the tavern lantern", 14),
    "tbbuu101": {"moves": "a blue rune light pulses (5 changed px)", "effects": [{"kind": "glow", "minPx": 1}]},
    "tbbubl01": {"moves": "the forge fire flickers (orange); the cold blue glints on the anvil are not a flame",
                 "effects": [{"kind": "flame", "minPx": 8, "colour": {"hue": [0, 45], "minS": 0.35, "minV": 0.4}}]},
    "tbbud001": _FIRE("the hut's window fires"), "tbbud201": _EMBER("the lodge's window fire", 11),
    "tbbud301": {"moves": "the hearth fires in the cave dwelling flicker (orange); its teal ice glints are not flames",
                 "effects": [{"kind": "flame", "minPx": 4, "colour": {"hue": [0, 45], "minS": 0.3, "minV": 0.35}}]}, "tbbud501": _FIRE("the three window fires"),
    "tbbuhu01": _FIRE("the three window fires"), "tbbuu501": _FIRE("the three window fires"),
    "tbbuu201": _EMBER("the lodge's window fire", 16), "tbbus201": _FIRE("the shrine's lamps", 8),
    "tbbumr01": {"moves": "the great pyre burns (tall orange flames)", "effects": [{"kind": "flame", "minPx": 20}]},
    "tbbum101": _RUNES, "tbbum201": _RUNES, "tbbum301": _RUNES, "tbbum401": _RUNES,
    "tbbuma01": {"moves": "blue rune lights on the mage guild pulse", "effects": [{"kind": "glow", "minPx": 20}]},
    "tbbuho01": {"moves": "teal spirit lights drift over the ice cathedral", "effects": [{"kind": "glow", "minPx": 20}]},
    "tbbuu301": {"moves": "the teal hearth light in the cave dwelling pulses", "effects": [{"kind": "glow", "minPx": 20}]},
    "tbbuu001": {"moves": "the hoist's bucket rises and falls on its rope (mechanical; no mechanical kind in the lane, "
                          "so only a teal shimmer where the DEF moves: a stand-in, the bucket itself stays static)",
                 "effects": [{"kind": "glow", "minPx": 20}]},
}

# ------------------------------------------------------------------------------------------------ scene / catalog
TO_SUN_CAM = (-0.55, 0.55, 0.62)   # hand-set as every other faction: the HoMM3 sprites are lit from the left (the
# painted moon at the top right is not their key light)
# positions.json keys Bulwark's layers by DEF name (tbbu* / tbbha*); building_layer_map.json maps the OE SIDs onto
# them. Only nativeLevels layers are built (32: stronghold_full3d_common.reachable_layers); the capitol tbbha401, the
# Mother Nature special tbbuspc1, the shipyard / ship, the horde1 base tbbuh101 and the animated river tbbuex01 have no
# native level. full: tbbuhu01 (the upgraded Lvl6 dwelling with its horde, same place and size as tbbuu501, 6844 px
# differ: the horde's tusks and fence) stands in for tbbuu501 so the two do not draw over each other.
STATES = {
    "start": ["tbbuha01", "tbbutv01", "tbbud001"],
    "full": ["tbbha301", "tbbucas3", "tbbum401", "tbbutv01", "tbbuma01", "tbbusilo", "tbbubl01", "tbbumr01",
             "tbbus201", "tbbuho01", "tbbuu001", "tbbuu101", "tbbuu201", "tbbuu301", "tbbuup_4", "tbbuhu01",
             "tbbuup_6"],
    "anim": ["tbbubl01", "tbbud301", "tbbuu001"],   # the three DEFs with the most frames (36 / 36 / 87)
}
WATER_USE = ("the painted river from the middle of the valley to the bottom edge (inside the painting; it leaves the "
             "rect only at its bottom edge)")

# ------------------------------------------------------------------------------------------------ sky
# Dark teal-green night sky with stars and a moon (CIELAB measured boxes, frame rect: sky L* 18-41, a* -27..-10,
# b* -14..+3; moon core L* 53-63 (max 63.2), halo b* up to +5.4). The peaks share the sky's colour (the dark green peak
# L* 4-24 a* -20..-5; the far green range a* -34..-27 b* +3..+11; snow peaks L* 3-47). The lane's own Depth Anything V2
# Large disparity splits them, as Tower / Necropolis: every sky box and the moon read 0.00 (p5..p95), the peaks 23-129.
# So a CIELAB box hand-set around the measured sky AND da_large < 0.5 (Tower's threshold; 0.5 and 3.0 give 192653 /
# 192921 px). Viewed (town_all/bulwark/skymask_da0.5.png): the whole sky and the moon down to the skyline (lowest sky
# row: frame 189, HoMM3 105), no peak; 18 px of the two brightest stars stay out (holes), harmless. The fill's own sky:
# the same box without disparity, capped at frame row 230 (hand-set, above the fill's peaks' feet).
SKY_MASK = {"rule": "lab", "reason": "dark green starry night sky with a moon over snow and dark green peaks; the peaks "
            "are cut by disparity",
            "lMin": 8.0, "lMax": 80.0, "aMin": -36.0, "aMax": -4.0, "bMin": -16.0, "bMax": 8.0, "daMax": 0.5,
            "extension": {"lMin": 8.0, "lMax": 80.0, "aMin": -36.0, "aMax": -4.0, "bMin": -16.0, "bMax": 8.0,
                          "maxRow": 230, "stdMax": 2.0, "stdWin": 11}}
# stdMax (2026-09-29): the colour box alone took the fill's dark teal peak faces as sky down to row 230 (viewed
# town_all/bulwark/sky_mask_edge.png), so they went ungraded and the terrain wall's height had no skyline to meet.
# Measured on the fill (town_all/bulwark/sky_probe.py, local L* std over 11 px): sky p50 0.33 / p95 0.71, peaks p50
# 4.7-8.1. Viewed at 2.0 (town_all/bulwark/skymask_std2.0.png): the mask stops on every peak's outline.
SKY_ANIM = {"mode": "deferred", "reason": "night sky with stars and moon: a drifting pano would slide the moon and star "
            "field; needs its own decision"}
# the static dome's periodic 360 deg panorama outside the painted sky (town_full3d_sky kit, then town_full3d_sdfill.py --step sky):
# the mirror dome streaked right of the painted rect under the sweeps
SKY_PANO = {"key": "p1_s11", "seed": 11,
            "prompt": "hand-painted fantasy game background sky, 1990s painted matte art, arctic night sky, dark teal and green aurora veils, scattered small stars, deep blue-black, sky only",
            "negative": "moon, sun, daylight, clouds bright, photo, photorealistic, land, ground, hills, mountains, trees, water, building, tower, person, bird, horizon line, text, watermark, frame, border, seam, lowres"}
# the panorama's tone matched to the painted sky at the rect's edges (town_full3d_sky.composite; sky only): the painted
# night sky is lighter and cloudier than the panorama beside it, a vertical line in the rest view (seam-line ratio
# 6.7-7.2 over rows 0-40 at x = TW, fx_v1 and fx_v2_edge pass 1). Hand-set: low-pass sigma 2 deg, fade radius 8 deg.
SKY_EDGE_MATCH = {"sigmaDeg": 2.0, "radiusDeg": 8.0}
# the painted sky mirrored across x = TW and faded into the (tone-matched) panorama (town_full3d_sky._edge_join): with
# the tone matched the step is under 1 L*, but the flat panorama beside the painted clouds still reads as a line
# (seam-line ratio 7.2-8.9 over rows 0-40, fx_v2_edge). fadePx hand-set.
SKY_EDGE_JOIN = {"method": "mirror", "edges": ["right"], "fadePx": 160,
                 "reason": "the painted night sky's clouds end at the frame edge against a flat panorama"}
# every layers/anims/metadata.json id is a positions.json layer id (28 DEFs)
ANIM_CROSSWALK = {}

# ------------------------------------------------------------------------------------------------ framing
# measured (town_full3d_framing.py measure, sdgrade_pilot stage, 2026-09-28; town_all/framing/bulwark_coarse.json,
# bulwark_fine.json): zoom 1.21 is the largest at which every building's body bounds stay inside the visible (non-HUD)
# region at the rest view with the building-centred aim (1.22 pushes the Lvl3 dwelling tbbud201 / tbbuu201 at the
# right edge and the Grail tbbuho01, drawn from HoMM3 y 0, out, and they are then reachable from no pose). The visible
# viewport goes from 66% painting to 95% at rest. panScale 0.5 as Stronghold / Castle: every pan pose >= 84% painting
# (63-74% before).
FRAMING = {"zoom": 1.21, "aim": "buildings", "panScale": 0.5,
           "reason": "the painting fills the visible region between the HUD panels; the extension seams leave the view"}

# ------------------------------------------------------------------------------------------------ texture (sdgrade)
TEX = {
    "styleCropNative": (150, 40, 700, 300),   # the fort, the peaks, the river gorge and the right slope (hand-set)
    # seeds 11 / 23 / 37 viewed (town_all/bulwark/sdfill_seeds.png): all three continue the river below the rect and
    # the left cliff; 11 rims the right peaks with a neon green edge, 37 grows a sheer cliff wall at the left and a
    # painter's signature; 23 continues the right massif as a jagged snow range over a snowfield with boulders. seed 23.
    "sd": {"prompt": ("a matte painting of a snowbound mountain valley at night, deep snow fields in cold blue "
                      "moonlight, grey granite rock outcrops and boulders dusted with snow, jagged snow-capped "
                      "mountains, a dark teal-green night sky with faint small stars, painterly, detailed"),
           "negative": ("building, house, hut, yurt, tent, cottage, roof, tower, castle, wall, fence, person, animal, "
                        "road, path, river, water, lake, moon, sun, daylight, blue sky, sunset, trees, forest, grass, "
                        "desert, sand, text, watermark, signature, frame, border, blurry, lowres, jpeg artifacts, "
                        "photo"),
           "promptKey": "p1", "seed": 23, "context": "props"},
    # a painter's signature the fill wrote at its bottom right corner (fill px; frame x ~2230-2320, y ~1000-1080)
    "clean": ["job_A_right:1380,900,1536,1024@7"],
    "integrate": {"esrgan": True, "grain": True,
                  "paintFloor": (885, 560, 1025, 665),   # bare snow (HoMM3 x 492-569, y 311-369), clear of the yurts
                  "floorRamp": (320, 460)},              # grain weight 0 above (peaks, sky), 1 below (snowfield)
    "grade": {"floorRows": (600, 665), "cliffRows": 360, "floorzRows": 480, "extOnlyBands": True},
    # The painted yurts: snow-dusted grey-blue timber on blue snow. Colour cannot split them (measured boxes, frame
    # rect: yurts L* 11-61 a* -9..-2 b* -18..-4 hue -136..-104 deg; rock outcrops L* 4-64 a* -7..-1 b* -19..-7 hue
    # -114..-99; snow L* 50-68 b* -20..-9), and the da_bump rule (town_all/bulwark/propmask_probe*.png) finds the mid
    # yurts but misses the two cut by the bottom edge at every opening tried (91 / 121 / 201 px) and takes rock crests.
    # So hand-traced boxes (HoMM3 px, one per yurt; viewed town_all/bulwark/prop_boxes_probe.png).
    "propMask": {"rule": "boxes", "reason": "yurts share the snow's and the rocks' colours; their disparity bump fails "
                 "at the bottom edge",
                 "boxes": [(612, 175, 658, 198), (579, 192, 623, 219), (514, 223, 568, 256), (560, 228, 626, 265),
                           (737, 300, 800, 355), (572, 340, 660, 374), (20, 279, 84, 321), (99, 274, 171, 315),
                           (0, 297, 35, 343), (4, 330, 85, 374), (380, 338, 490, 374)],
                 "dilate": 5},
    "blend": {"toneRows": (360, 480),    # the cliff and the massif beside the side edges; faded to 0 on the snowfield
              # rows with too few samples (the fill's sky above its peaks, the Lvl3 dwelling on the painting's edge)
              # take the neighbours' shift instead of 0: the 0 bands ended in hard lines on the far rock (L* steps
              # 4.9 / 9.5 at canvas rows 135 / 327, extsrc_p2_blend)
              "lowCountRows": "interp",
              # fx_v6: fx_v5's Unity rest render failed the seam line at x1440 (p90 3.80: the sky's tone and the
              # massif's rock stepping at the edge, rows 0-54 / 108-139 / 365-394) and at y673 (run 129, cols 40-168:
              # the painted yurt cut by the frame bottom and the snow beside it). Canvas x1440 3.95 / run 66 ->
              # 1.30 / 14 with the right edge offset (Dungeon dg_v4_edge's rule, no painted texel copied across);
              # y673 2.46 / 82 -> 0.23 / 0 with the bottom rows reflected over 8 px, the painted yurt cut by the frame
              # bottom included (Tower's bottomSourceHut): its base now runs 8 px on into a shadow instead of ending in a
              # straight line. Reflecting 24 px without the yurt (Dungeon's setting) left the yurt's cut (Unity y673 run
              # 109, cols 40-148); 12-24 px with it showed a mirrored yurt; a per-column offset below the edge (as
              # rightMirrorMode "offset", tried in scratch and not kept) drew the door and the bank as vertical streaks
              # and a pale blob (town_all/bulwark/seam_v6/canvas_bottom_3.png, canvas_bl_variants*.png).
              # fx_v6 Unity rest render: x1440 p90 1.85 / run 55, y673 0.36 / 0 (gate 3.5 / 100); buildings unchanged.
              "rightMirrorPx": 8, "rightMirrorMode": "offset", "bottomMirrorPx": 8, "bottomSourceHut": True},
    # right-edge bridge (town_full3d_sdfill --step bridge, between grade and blend): the painting's massif and snow
    # plateau continued into a band of the extension; buildings are refused (the cut halls end geometrically, EDGE_FRAY)
    "bridge": {"prompt": ("a matte painting of a snowbound mountain valley at night, jagged snow-capped dark teal "
                          "granite peaks, deep snow fields in cold blue moonlight, snow-dusted boulders, a dark "
                          "teal-green night sky, painterly, detailed"),
               "negative": ("building, house, hut, yurt, tent, cottage, hall, roof, tower, castle, wall, fence, "
                            "person, animal, road, river, water, moon, text, watermark, signature, frame, border, "
                            "seam, vertical line, blurry, lowres, jpeg artifacts, photo"),
               # seed 101 of 11 swept (5 11 23 37 51 77 101 131 173 211 257; canvas seam-line p90 over rows 60+:
               # 3.81, the rest 4.03-5.22; town_all/bulwark/canvas_p90.py). Staged fx_v2_edge (with the far-cell cap and the
               # stale Mesh_OuterC2 pruned): rest-preview x1440 p90 3.48 / run 64, y673 2.61 / 61
               "seed": 101, "bandPx": 192, "fadePx": 96, "rowsBelowPx": 48, "contextPx": 560, "strength": 0.6,
               # the painted edge peak meets the fill's sky at x = TW: its slope can only continue into that sky
               "writeSky": True,
               # the building mask's margin past the edge kept the raw fill's specks, a dotted line at x = TW once the
               # halls are frayed (seam-line ratio 5.7 / 4.9 at rows 300 / 320)
               "writeExtBuildingMask": True,
               # the halls' roof ridge at the edge was continued as a bright 4 px line (canvas L* 41-55 at frame rows
               # 307-310, x 1440-1443): the SD input sees the building pixels near the edge filled from around them
               # (the halls' roof rows only: filling the Lvl3 dwelling's snowy base too made the model paint a smooth
               # snow mound beside it, ratio 4-5 over rows 480-560)
               "rectContext": "buildingsInpainted", "stripPx": 48, "stripRows": (280, 345)},
    "renderRefPass": True,
}

# ------------------------------------------------------------------------------------------------ terrain
# Horizon, measured (town_all/bulwark/measure_horizon.py over FLOOR_POLY_HOMM3, yurt boxes excluded): DA V2 Large
# inverse-depth rows fit -> HoMM3 y 138.2-146.5 over row starts 324-484 (100% inliers); Depth Pro -> 61.6-79.3 there and
# 114-173 from row 524 down (its floor is not one plane: rejected). Cross-check by the painted yurts: wall 12 px at base
# y 263 and 14 px at base y 313 scale as a much flatter floor than either model (their ratio 1.17 gives a horizon
# above the frame; 1.41 predicted at 140), so the painter did not scale them by one plane. The painted snow plateau
# reaches y ~165-180 below the peaks, so the horizon lies above that. Taken 140 (hand-set inside the DA range).
HORIZON_HOMM3_Y = 140.0
# measured at horizon 140 (town_all/bulwark/hut_units.py): the yurt at HoMM3 x 560-626 has a 12 px wall (eave y 251 to
# base y 263) = 0.630 camera units; the yurt at x 99-171 (14 px, base y 313) 0.522 (19% apart, see the horizon note).
# Taken their mean 0.58; eave hand-set 2.2 m as Stronghold's.
HUT_WALL_UNITS, HUT_EAVE_M = 0.58, 2.2
FAR_CAP_M = 400.0
# Hand-traced floor polygon (HoMM3 px): the snowfield below the left cliff, the slope down to the river and the right
# snow plateau below the massif's foot.
FLOOR_POLY_HOMM3 = [(0, 285), (110, 282), (200, 265), (240, 235), (290, 215), (340, 225), (380, 250), (420, 235),
                    (470, 215), (540, 205), (600, 190), (680, 180), (740, 190), (800, 200), (800, 374), (0, 374)]
SPUR_SCALE, SPUR_AMP = 8.0, 0.7   # hand-set: steep snowy granite spurs, as Tower's
WALL_SHIFT_M = 60.0               # hand-set: the cliff and the massifs close round the camera
# The right wall's far part scaled per azimuth onto the fill's own skyline (stronghold_full3d_terrain.fit_ext_skyline).
# Without it (town_all/bulwark/skyfit_probe.py on extsrc_p2_blend, every 4th px of frame x 1440-2320, rows 0-300) the
# silhouette agreed with the fill's sky on 64% of samples: the dome showed over the painted peaks beside the edge and
# the fill's sky was projected onto rock standing up to row 0 further right. Fitted: 99.3% / 99.5% (x < / >= 1920).
# rhoMinM / rhoFullM hand-set so the snowfield keeps its height. edgeRampPx: the bridge (writeSky) continues the painted
# edge peak's slope as a smooth dark face the sky rule takes for sky, so the target ramps from the painted skyline at the
# edge (row 78.5) to the fill's over 64 px (viewed town_all/bulwark/skyfit_i_zoom.png: the slope now carries rock).
# Cells past the raymarch's reach are capped at the skyline (the periphery ring draws them: uncapped, 3991 of them stood
# up to 4 deg above it and the ring's far piece Mesh_OuterC2 drew a needle over the sky at x ~1446, fx_v2_edge Unity).
EXT_SKYLINE = {"rhoMinM": 20.0, "rhoFullM": 60.0, "kMin": 0.05, "kMax": 4.0, "fadeDeg": 0.05, "maxBinsAtKMax": 4,
               "edgeRampPx": 64}

# ------------------------------------------------------------------------------------------------ ground
# (vanilla texture, metres per tile) - hand-set, Tower's snow set (viewed there: town_all/tower/vanilla_tex.png):
# Snow1 / Snow2 / Snow5 tile (rock-streaked snow, fine powder, wind ripples); the snow mountain atlas is the rock detail.
FLOOR_TEX = (("Snow2", 4.0), ("Snow5", 5.0), ("Snow1", 6.5))
ROCK_TEX = (("1024_1_mountain_large_snow_diffuse", 12.0), ("Snow1", 6.0), ("Snow5", 9.0))
ROCK_ROT = {}
DETAIL_CONTRAST = 2.0
ROCK_CONTRAST = 3.0
FLOOR_STONES = (("256_2_snow_stones_texture", 2.2), ("Snow1", 3.0))
STRATA_COLS = {"left": (0, 300), "right": (1150, 1440)}
# (painting box, extension box), frame px, measured on the rest preview (full state): the floor box is the largest
# bare-snow window no full-state sprite or yurt box covers (98% free, L* > 35; the snow slope left of the river, HoMM3
# x 229-273, y 282-304): every snow patch nearer the bottom edge lies under the Lvl6 cave, the tavern, the bonfire or
# the Lvl3 longhouse. The right wall box is the massif right of the capitol and mage guild (79% free of sprites and
# sky; the box beside them was 56%).
CONTRAST_REGIONS = {"floor": ((412, 508, 492, 548), (100, 720, 1800, 1000)),
                    "rightWall": ((1340, 100, 1440, 260), (1480, 100, 1900, 400))}

# ------------------------------------------------------------------------------------------------ periphery
ROCK_MESHES = {"Snow_Rock_01": "snow_rock_01_diffuse", "Snow_Rock_02": "snow_rock_02_diffuse",
               "Snow_Rock_03": "snow_rock_03_diffuse"}
SCRUB_MESH, SCRUB_TEX = None, None
PERIPHERY_SCATTER = {
    "scrub": {"required": False, "reason": ("no scrub: the painted snowfield, slopes and cliff carry no bushes or "
                                            "trees")},
    "rock": {"required": True, "prefixes": ["Mesh_Outer_boulders_"]},
    "nearDensity": {"source": "profile", "perM2": 0.0028,
                    "reason": "the olive-blob count finds no scrub on snow; Stronghold's measured density"}}
ROCK_SIZE_M = (1.0, 4.0)
SCRUB_SIZE_M = (1.2, 2.6)
SCRUB_ROW0 = 400
PERIPHERY_VANILLA_NOTE = ("vanilla snow towns ring the camera with snow hills and rocks; the Bulwark outer world "
                          "continues the painted cliff, massifs and snowfield")
PERIPHERY_WATER = {"required": False, "reason": "the painted river meets only the rect's bottom edge; the frame "
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
RELIEF_TUNE = {}
PARTS_LAYERS = set()        # no part separation until a review earns it (Stronghold's bar)
BACK_FILL_LAYERS = None     # every layer takes the edge-filled back (evaluation)
# Layers cut by the painting's right frame edge, given a ragged geometric edge (stronghold_full3d_buildings.edge_fray;
# frame px): the Lvl3 dwelling and the town hall's upgrades end in a straight line at x = TW, seen at sweep_right
# (town_all/bulwark/fx_after_right_half.png; rest-preview seam-line ratio 7.6-22 over rows 360-480, fx_v1). Shallower
# than Stronghold's cave: timber walls, not rock. The halls are frayed below their roof only (rows 345+): frayed whole
# (fx_v2_edge), the terrain uncovered under the roof inside the rect carries the painted roof's own pixels, a dotted
# line at x = TW (ratio 7.6 at row 300 against 2.9 unfrayed); unfrayed, their wall fails (8.8-21 over rows 380-440).
EDGE_FRAY = {"tbbud201": {"minPx": 6, "maxPx": 30, "sigmaPx": 6},
             "tbbuu201": {"minPx": 6, "maxPx": 30, "sigmaPx": 6},
             **{lid: {"minPx": 6, "maxPx": 30, "sigmaPx": 6, "rows": (345, 1080)}
                for lid in ("tbbuha01", "tbbha201", "tbbha301")}}
SOLID_TUNE = {}
# Opt-in (stronghold_full3d_solids.SINK_RIM_GRAZE_DROP; off for every other faction): drop the kept back triangles over a
# sunk step whose rim vertex tops a closing wall when their plane grazes the rest ray. Bulwark wall_v1 (fx_v6 + fray
# caps) failed the see-through gate by one px at pan_cursor_left / right (0 -> 1): one tbbum401 back triangle, 2 px^2 at
# rest, |cos(normal, rest ray)| 0.006, kept by the walled-rim rule. Measured at 0.02: Bulwark drops 64 (tbbum401 11)
# and passes (8156 px, no pose worse than fx_v6). Scoped to Bulwark because the same rule opens Cove: 85 tbcvnmp2
# triangles dropped, orbit y-18 24593 -> 30023 px (cv_v12 scratch, 2026-09-29).
SINK_RIM_GRAZE_DROP = {"maxCos": 0.02}

# Building mask (stronghold_full3d_buildings.coherent_painting), as Dungeon: only the rim-connected carried painting is
# cut from a sprite (2026-10-18 no-Meshy nm1 rollout, all buildings solid + MoGe relief).
MASK_PAINT_COHERENT = True
