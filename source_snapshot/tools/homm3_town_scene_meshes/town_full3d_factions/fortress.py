"""Fortress profile of the full-3D town lane (docs/homm3_stronghold_full_3d_town.md). A misty swamp forest: tall mossy
trunks with hanging moss frame the view, grey fog shows through the canopy in the middle and between the far trunks,
a murky olive swamp pool with lily pads and reeds fills the middle and bottom and leaves the rect at its bottom edge,
dark mossy banks with ferns and low bushes left and right. The painting carries no painted houses (one painted log,
dock and stump at the left bank, single, not repeated). Measured values say where they come from; hand-set values say
so. Proof tier: staged candidate only (no bundle, no install).
"""
from __future__ import annotations

# ------------------------------------------------------------------------------------------------ identity
FRACTION = "homm3_fortress"
BACKGROUND = "Fortress-in-background.png"
DATA_DIR = "homm3_fortress_full3d"
BUNDLE = "homm3_town_scene3d_fortress"
PREFIX = "homm3_fortress3d_"
ASSET_ROOT = "Assets/Homm3TownScene3d/fortress"
LABEL = "Fortress"
FX_MODULE = "town_full3d_fx"   # the shared profile-classified effects module (FX_LAYERS below)

# Animated reachable layers classified from the DEF's changed-pixel mask (town_all/fx_probe/fortress_changed.png,
# 2026-09-28). Kinds are hand-set from that look; place, extent, colour and timing are measured by town_full3d_fx.
FX_LAYERS = {
    "tbfrcstl_3": {"moves": "the fire in the castle's top shrine window flickers (orange)",
                   "effects": [{"kind": "flame", "minPx": 8}]},
    "tbfrdw_3_2": {"moves": "the red wyvern egg-pod in the tree trunk pulses with light",
                   "effects": [{"kind": "glow"}]},
    "tbfrdw_4_2": {"moves": "the red lamp caps on the gorgon lair's posts pulse",
                   "effects": [{"kind": "glow"}]},
    "tbfrdw_6_2": {"moves": "the hydra pond's surface ripples between the lily pads",
                   "effects": [{"kind": "water", "rects": [[70, 45, 213, 111]], "minPx": 60}]},
    "tbfrmage_3": {"moves": "the two blue-green torch flames at the mage guild's door flicker",
                   "effects": [{"kind": "flame", "minPx": 30}]},
    # animated through ANIM_CROSSWALK (their DEF id carries a _1 suffix; town_all/fx_probe/fortress_changed.png)
    "tbfrtvrn": {"moves": "the tavern's hearth fire flickers (yellow-orange)", "effects": [{"kind": "flame", "minPx": 20}]},
    "tbfrmark": {"moves": "light glints on the water round the market boats (the boats' bob and the pennants stay "
                          "static: no cloth / float kind)", "effects": [{"kind": "glints", "minPx": 6}]},
    "tbfrsilo": {"moves": "light glints on the water round the resource silo", "effects": [{"kind": "glints", "minPx": 4}]},
    "tbfrdw_3": {"moves": "the red wyvern egg-pod in the tree trunk pulses with light", "effects": [{"kind": "glow"}]},
    "tbfrdw_6": {"moves": "the hydra pond's surface ripples between the lily pads",
                 "effects": [{"kind": "water", "rects": [[45, 18, 192, 86]], "minPx": 60}]},
}

# ------------------------------------------------------------------------------------------------ scene / catalog
TO_SUN_CAM = (-0.55, 0.55, 0.62)   # hand-set as Castle / Stronghold (diffuse fog light; the albedo bake divides by it)
# positions.json keys the Fortress layers by DEF name (building_layer_map.json maps the OE SIDs onto them). full = every
# top level; tbfrdock and tbfrboat share a place (the shipyard without / with its boat), full shows the dock.
STATES = {
    "start": ["tbfrhall", "tbfrtvrn", "tbfrdw_0"],
    # full = the top reachable level of every native building (building_layer_map nativeLevels; the _3 / hall_4 /
    # ext / hrd3 sprites exist in the DEF set but no OE building reaches them, so they have no prefab)
    "full": ["tbfrhall_3", "tbfrcstl_3", "tbfrmage_3", "tbfrtvrn", "tbfrmark", "tbfrsilo", "tbfrblak", "tbfrspec",
             "tbfrdock", "tbfrhrd2", "tbfrholy", "tbfrdw_0_2", "tbfrdw_1_2", "tbfrdw_2_2", "tbfrdw_3_2", "tbfrdw_4_2",
             "tbfrdw_5_2", "tbfrdw_6_2"],
    # reachable layers whose own DEF has frames (anims/metadata.json); their effects are FX_LAYERS
    "anim": ["tbfrcstl_3", "tbfrmage_3", "tbfrdw_3_2", "tbfrdw_4_2", "tbfrdw_6_2"],
}
WATER_USE = ("the painted swamp pool (inside the painting; it meets the rect's bottom edge and the frame extension "
             "continues it as texture only)")

# ------------------------------------------------------------------------------------------------ sky
# No blue sky: grey fog shows through the canopy. Measured (CIELAB, blur 1.2, town_all/fortress/probe_lab.py): the fog
# is L* 39-52, b* -5.5..+3, C* < 8.5 (HoMM3 (460-600, 0-150)); the canopy is L* < 36 with b* > +6, the trunks
# L* < 26. The box L* >= 36, b* <= 4 connected to the top edge takes the central fog gap (66497 px down to the horizon
# cap; the faint far trunk inside the fog goes with it) and leaves the enclosed fog pockets between the left trunks as
# terrain. Extension rule: see the fill below.
SKY_MASK = {"rule": "lab", "reason": "grey fog through the canopy gap; canopy and trunks are darker and yellower",
            "bMax": 4.0, "lMin": 36.0,
            "extension": {"bMax": 4.0, "lMin": 36.0, "maxRow": 300}}
# seam pass (fr_v2_edge, Cove's recipe): the panorama's tone matched to the painted sky at the edges, and the canvas
# (bridged canopy and fog) carried across the right edge onto the dome (town_full3d_sky._edge_join, method canvas).
# The painting's fog gap does not reach the right edge (the canopy and the tavern cover it), so the mirror has no source.
SKY_EDGE_MATCH = {"sigmaDeg": 2.0, "radiusDeg": 10.0}
SKY_EDGE_JOIN = {"method": "canvas", "edges": ["right"], "fadePx": 240, "rectFeather": False, "topFeather": False,
                 "canvasSkyOnly": False, "topFadePx": 32,
                 "reason": "the panorama's pale fog beside the painted rect does not continue the painted dark canopy"}
SKY_ANIM = {"mode": "deferred", "reason": "the periodic 360 deg sky band is being rebuilt in the parent's change; "
            "drift follows it"}
# the static dome's periodic 360 deg panorama outside the painted sky (town_full3d_sky kit, then town_full3d_sdfill.py --step sky):
# the mirror dome streaked right of the painted rect under the sweeps
SKY_PANO = {"key": "p1_s11", "seed": 11,
            "prompt": "hand-painted fantasy game background sky, 1990s painted matte art, dense grey-green swamp mist and haze, soft overcast fog layers, muted olive and slate tones, sky only",
            "negative": "blue sky, sun, sunset, orange, photo, photorealistic, land, ground, hills, mountains, trees, water, building, tower, person, bird, horizon line, text, watermark, frame, border, seam, lowres"}
# DEF ids in layers/anims/metadata.json that are not positions.json layer ids -> the layer they animate (the base DEF
# of a level carries a _1 suffix in the anims extraction). Measured: each DEF's frame 0 is pixel-identical to its layer
# sprite (same box, every opaque px equal; 1274-41454 px). town_full3d_fx and the
# validator (since 3db569ff00) move each DEF onto its layer, so the crosswalked layers get FX_LAYERS rows too.
ANIM_CROSSWALK = {"tbfrext2_1": "tbfrext2", "tbfrtvrn_1": "tbfrtvrn", "tbfrmark_1": "tbfrmark",
                  "tbfrsilo_1": "tbfrsilo", "tbfrboat_1": "tbfrboat", "tbfrdw_3_1": "tbfrdw_3", "tbfrdw_6_1": "tbfrdw_6"}

# ------------------------------------------------------------------------------------------------ framing
# measured (town_full3d_framing.py measure, sdgrade_v2 stage, 2026-09-28; town_all/fortress/framing_coarse.json and
# framing_fine.json): zoom 1.21 is the largest at which every building's body bounds stay inside the visible (non-HUD)
# region at the rest view with the building-centred aim (1.22 pushes the hydra pond tbfrdw_6 / tbfrdw_6_2 under the
# hero panel and they are then reachable from no pose; 1.23 adds tbfrdw_4 / _4_2 and the tavern). Painting share of
# the visible region, panScale 0.5 (default / cursor L / cursor R / sweep L / sweep R / sweep high):
#   zoom 1.00: 0.657 0.651 0.658 0.625 0.712 0.646   (panScale 1.0: 0.657 0.648 0.662 0.598 0.729 0.641)
#   zoom 1.20: 0.911 0.911 0.923 0.804 0.864 0.840
#   zoom 1.21: 0.923 0.920 0.933 0.809 0.866 0.846   <- chosen
#   zoom 1.22: 0.934 0.926 0.939 0.813 0.868 0.851   (2 buildings out at rest)
# panScale 0.5 as Stronghold / Castle: at 1.21 every pan pose >= 81% painting (at panScale 1.0 sweep_left falls to ~72%).
FRAMING = {"zoom": 1.21, "aim": "buildings", "panScale": 0.5,
           "reason": "the painting fills the visible region between the HUD panels; the extension seams leave the view"}

# ------------------------------------------------------------------------------------------------ texture (sdgrade)
TEX = {
    "styleCropNative": (150, 40, 700, 300),   # the trunks, fog gap, pool and banks (hand-set)
    # context 'full': no painted props to keep out of the extension (the single log / dock / stump is not repeated)
    # p1 ("dark misty swamp forest ... murky olive green swamp water ...", seeds 11 / 23 / 37, sdinpaint_runs/p1_s*): all
    # three paint pale fog mirrored in open water; the grade maps those bright reflections to pale pink blotches on the
    # foreground water (canvas_blend of p1_s11): superseded. p2 asks for dull dark water and says no to reflections.
    "sd": {"prompt": ("a dark gloomy matte painting of a swamp forest, dark murky olive brown water with a dull "
                      "surface and green lily pads, tall green reeds, dark mossy muddy banks with ferns and low "
                      "bushes, thick mossy tree trunks with hanging moss, dim grey fog far between the trunks, "
                      "painterly, detailed"),
           "negative": ("reflection, mirror, shiny water, bright water, white, pale, pink, building, house, hut, dock, "
                        "pier, boat, bridge, tower, wall, fence, person, animal, blue sky, sun, sunbeam, snow, "
                        "desert, sand, rock cliff, red, flowers, text, watermark, signature, frame, border, blurry, "
                        "lowres, jpeg artifacts, photo"),
           "promptKey": "p2", "seed": 11, "context": "full"},
    # p2 seeds 11 / 23 / 37 compared (town_all/fortress/sdfill_seeds_p2.png): 11 continues the big left trunk and
    # bank with ferns, puts one island in the right fog and leaves the pool mostly dull; it is the one integrated
    "clean": [],
    "integrate": {"esrgan": True, "grain": True,
                  "paintFloor": (760, 480, 1000, 560),   # open pool water (HoMM3 x 422-556, y 267-311), clear of pads
                  "floorRamp": (300, 380)},               # grain weight 0 above (trunks, fog), 1 below (banks, pool)
    "grade": {"floorRows": (600, 665), "cliffRows": 300, "floorzRows": 380, "extOnlyBands": True},
    "propMask": {"rule": "none", "reason": "no painted houses: every house in the Fortress screen is a building layer; "
                 "the painted log, dock and stump are single props and the lily pads lie flat on the water"},
    "blend": {"toneRows": (250, 350),   # the trunks and bushes beside the side edges; faded to 0 on the banks
              # seam pass (Cove's recipe, 951e6e7995; candidate fr_v2_edge): the edge blend also takes the building
              # mask's margin and every painted pixel at the edge (the right edge is building layers over rows
              # 124-673, cut back by EDGE_FRAY), the sky beside the edges, and a mirrored crossfade over the first
              # columns right of x = TW and rows below y = TH for painted features too short for the low-pass
              "writeExtBuildingMask": True, "edgeSource": "paintedAll", "sideEdgeSky": True,
              "rightMirrorPx": 12, "bottomMirrorPx": 24},
    # right-edge bridge (town_full3d_sdfill --step bridge, between grade and blend): the painted canopy, trunks and bank
    # continued into a band of the extension (fx_v1 rest seam-line x = TW p90 16.4 / run 210: the dark painted
    # canopy meets the fill's pale fog at rows 0-300)
    "bridge": {"prompt": ("a dark gloomy matte painting of a swamp forest, thick mossy tree trunks and a dark green "
                          "canopy with hanging moss continuing to the right, dim grey fog far between the trunks, dark "
                          "murky olive water with green lily pads, tall reeds, mossy banks, painterly, detailed"),
               "negative": ("building, house, hut, tower, dock, pier, boat, bridge, wall, fence, person, animal, "
                            "blue sky, sun, snow, desert, text, watermark, signature, frame, border, seam, vertical "
                            "line, blurry, lowres, jpeg artifacts, photo"),
               "seed": 11, "bandPx": 192, "fadePx": 96, "rowsBelowPx": 48, "contextPx": 560, "strength": 0.75,
               "writeSky": True, "writeExtBuildingMask": True,
               "rectContext": "buildingsInpainted", "stripPx": 48, "stripRows": (0, 673)},
    "renderRefPass": True,
}

# ------------------------------------------------------------------------------------------------ terrain
# Horizon (hand-set within measured bounds; town_all/fortress/measure_horizon*.py, lilypad_horizon.py): the painted
# lily pads are flat discs on one level water plane, so their width is proportional to (row - horizon): 14 pads,
# robust line, zero at HoMM3 y 132.3. DA V2 Large disparity over the floor polygon (as inverse depth) vanishes at
# y 116-136 (rows >= 280 / 190). Depth Pro's inverse depth vanishes at y 57-93: it reads the floor as rising to the
# fog line and disagrees with the pads, so it is recorded and not used. Taken 130.
HORIZON_HOMM3_Y = 130.0
# measured: the gnoll hut (tbfrdw_0, a stilt hut) has a 17 px door (y 205-222) above its stilt feet (base y ~265) =
# 0.90 camera units at their depth on this floor plane (town_all/tower/hut_units.py at horizon 130). No painted hut
# exists; the anchor is the door, hand-set 2.0 m (its 33 px eave-to-floor wall would make a 2.2 m eave's door 1.1 m).
HUT_WALL_UNITS, HUT_EAVE_M = 0.90, 2.0
FAR_CAP_M = 400.0
# Hand-traced floor polygon (HoMM3 px): the banks and the pool below the far bush line and the fog floor (y 162-190).
FLOOR_POLY_HOMM3 = [(0, 190), (100, 180), (200, 172), (300, 168), (420, 165), (500, 162), (600, 165), (700, 172),
                    (800, 185), (800, 374), (0, 374)]
SPUR_SCALE, SPUR_AMP = 14.0, 0.35   # hand-set: low wooded banks, as Castle's hills
WALL_SHIFT_M = 40.0                 # hand-set: the forest closes round the pool gently

# ------------------------------------------------------------------------------------------------ ground
# (vanilla texture, metres per tile) - hand-set. Viewed (town_all/fortress/vanilla_tex.png): grass_dirt (mud with moss
# patches), grass2 (dark grass), dirt_ground2/3 tile; the 512_10..14 lawn / hill textures and 256_7_grass / dirt_grass
# are mesh UV or alpha-card atlases (not tileable) and are not used. resources.assets has no swamp ground set.
FLOOR_TEX = (("grass_dirt", 4.0), ("grass2", 4.5), ("dirt_ground3", 5.0), ("dirt_ground2", 6.0))
ROCK_TEX = (("grass2", 6.0), ("grass_dirt", 8.0), ("dirt_ground3", 9.0))
ROCK_ROT = {}
DETAIL_CONTRAST = 2.0
ROCK_CONTRAST = 3.0
FLOOR_STONES = (("dirt_ground3", 2.2), ("grass_dirt", 3.0))
STRATA_COLS = {"left": (0, 300), "right": (1150, 1440)}   # the left trunks and the right bank's trees
CONTRAST_REGIONS = {"floor": ((500, 560, 1300, 665), (100, 720, 1800, 1000)),
                    "rightWall": ((1150, 100, 1430, 380), (1480, 100, 1900, 420))}

# ------------------------------------------------------------------------------------------------ periphery
# Mossy stones and a fallen log (the painted banks carry logs and stumps, no rock). The vanilla meshes are Z-up in
# resources.assets and the lane places them Y-up with a yaw only: a rock or a log (a cylinder about X) still reads
# right, a stump would lie on its side, so Stump1/2 and Log2_Mushrooms are not used.
ROCK_MESHES = {"Green_Rock_1x1": "green_rock_small_diffuse", "Green_Rock_2x2": "green_rock_big_diffuse",
               "Log1": "256_4_log_1_diffuse"}
SCRUB_MESH, SCRUB_TEX = None, None
PERIPHERY_SCATTER = {
    "scrub": {"required": False, "reason": ("no scrub: the painted ferns, reeds and bushes have no opaque vanilla "
                                            "counterpart (bush_small_leaves is alpha-card; the lane bakes opaque RGB)")},
    "rock": {"required": True, "prefixes": ["Mesh_Outer_boulders_"]},
    "nearDensity": {"source": "profile", "perM2": 0.0028,
                    "reason": "the olive-blob count reads the banks' moss and ferns as scrub; Stronghold's measured "
                              "density"}}
ROCK_SIZE_M = (1.0, 3.0)
SCRUB_SIZE_M = (1.2, 2.6)
SCRUB_ROW0 = 400
PERIPHERY_VANILLA_NOTE = ("vanilla towns ring the camera's sweep with terrain and dressing; the Fortress outer world "
                          "continues the painted swamp banks and forest")
PERIPHERY_WATER = {"required": False, "reason": "the painted pool meets the rect's bottom edge (HoMM3 x ~250-760); "
                   "the frame extension below continues it as SD-fill texture, and this lane has no water-body "
                   "builder (the Conflux FlowWater periphery is another lane): no animated water leaves the frame, "
                   "an open gap recorded here"}

# ------------------------------------------------------------------------------------------------ near field
NEAR_ROCKS = ("Green_Rock_1x1", "Log1")
PEBBLE = "Green_Rock_1x1"

# ------------------------------------------------------------------------------------------------ vanilla filler
VANILLA_TEXTURES = {
    "grass1": 512, "grass2": 512, "grass3": 512, "dirt_ground1": 512, "dirt_ground2": 512, "dirt_ground3": 512,
    "dirt_ground4": 512, "grass_dirt": 512, "512_10_grass_forest_lawn_1_diffuse": 512,
    "512_11_grass_forest_lawn_2_diffuse": 512, "512_14_grass_tropical_lawn_diffuse": 512, "dead_grass1": 512,
    "dirt_grass_diffuse": 256, "256_7_grass_diffuse": 256, "green_rock_big_diffuse": 512,
    "green_rock_small_diffuse": 512, "512_12_grass_hill_1_diffuse": 512, "512_13_grass_hill_2_diffuse": 512,
    "256_4_log_1_diffuse": 256,
}
VANILLA_VFX = {
    "WaterNormal": 1024, "TileNoise_07_vfx": 256, "TileNoise_23_vfx": 512, "TileNoise_19_vfx": 512,
    "glow_08_vfx": 256, "glow_10_vfx": 512, "glow_18_vfx": 64, "smoke_06_vfx": 256,
}
VANILLA_MESHES = ("Green_Rock_1x1", "Green_Rock_2x2", "Log1")

# ------------------------------------------------------------------------------------------------ buildings
# Canopy-hung layers (the hall's treehouse, the wyvern nests, the upgraded basilisk pit's bull idol): their lowest
# pixel sits over the far fog (footing 173-323 m) while the trunk / canopy they hang in is at 63-110 m
# (town_all/fortress_canopy/probe_canopy.json), so the body spanned 97-273 m. Footed on their ring instead.
RELIEF_TUNE = {k: {"hung": True} for k in ("tbfrhall", "tbfrhall_2", "tbfrhall_3", "tbfrdw_5", "tbfrdw_5_2",
                                           "tbfrdw_3_2")}
PARTS_LAYERS = set()        # no part separation until a review earns it (Stronghold's bar)
BACK_FILL_LAYERS = None     # every layer takes the edge-filled back (evaluation)
# Canopy-hung layers (the hall's treehouse, the wyvern nests, the upgraded basilisk pit's bull idol) have no ground
# under their lowest pixel, so their footing is the far fog/terrain (footZm 173-323 m, sdgrade_pilot stage_report)
# and the width rule made them 12-18 m deep. Hand-set thin slabs (thickP95 4.99 / 4.92 / 2.76 m after). Measured
# effect on sweep_left (town_all/fortress/sweep_left_r1_r2.png): none visible - the streaks there are the front
# relief and the canopy terrain, and the pan preview stacks every staged level; the footing depth is not a profile
# knob. Kept because a hanging platform is not an 18 m block; open item, not a fix.
SOLID_TUNE = {
    "tbfrhall": {"tmax": 5.0}, "tbfrhall_2": {"tmax": 5.0}, "tbfrhall_3": {"tmax": 5.0},   # treehouse on a trunk
    "tbfrdw_5": {"tmax": 5.0}, "tbfrdw_5_2": {"tmax": 5.0},                                # nests in the canopy
    "tbfrdw_3_2": {"tmax": 4.0},                                                           # bull idol in a tree
}

# ------------------------------------------------------------------------------------------------ edge fray
# seam pass (fr_v2_edge): the building layers that reach the right edge (x > TW - 40 at rest: the hydra pond, the
# tavern, the moss hut, the dwellings on the right bank) and the bottom edge (y > TH - 40: the dock, the left and right
# dwellings, the pond, the shrine) end in ragged geometric edges so the bridged / mirrored canvas shows through
# (stronghold_full3d_buildings.edge_fray; geometry only, no texel is recoloured).
EDGE_FRAY = {lid: {"minPx": 8, "maxPx": 40, "sigmaPx": 6}
             for lid in ("tbfrdw_0", "tbfrdw_0_2", "tbfrdw_6", "tbfrdw_6_2", "tbfrhrd2", "tbfrspec", "tbfrtvrn")}
EDGE_FRAY_BOTTOM = {lid: {"minPx": 8, "maxPx": 40, "sigmaPx": 6}
                    for lid in ("tbfrdock", "tbfrdw_4", "tbfrdw_4_2", "tbfrdw_6", "tbfrdw_6_2", "tbfrholy")}
