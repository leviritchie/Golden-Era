"""Inferno profile of the full-3D town lane (docs/homm3_stronghold_full_3d_town.md). A lava valley at dusk: a crimson sky
with black smoke clouds and a low sun on the left, a black mountain range across the whole width, jagged red rock ridges
on both sides and a dark basalt / ash floor with orange lava veins, rows of painted (non-layer) huts on the floor.
Measured values say where they come from; hand-set values say so. Proof tier: staged candidate only (no bundle, no
install).
"""
from __future__ import annotations

# ------------------------------------------------------------------------------------------------ identity
FRACTION = "homm3_inferno"
BACKGROUND = "Inferno-in-background.png"
DATA_DIR = "homm3_inferno_full3d"
BUNDLE = "homm3_town_scene3d_inferno"
PREFIX = "homm3_inferno3d_"
ASSET_ROOT = "Assets/Homm3TownScene3d/inferno"
LABEL = "Inferno"
FX_MODULE = "town_full3d_fx"   # the shared profile-classified effects module (FX_LAYERS below)

# Animated reachable layers (layers/anims/metadata.json frames > 1), classified from the DEF's changed-pixel mask
# (town_all/fx_probe/inferno_changed.png, 2026-09-28). Every moving px is fire: brightest-frame hue 25-48 deg,
# saturation 0.78-1.0, value 0.89-1.0. Place, extent, colour and timing are measured by town_full3d_fx from the DEF.
_FIRE = {"kind": "flame", "minPx": 4}
FX_LAYERS = {lid: {"moves": moves, "effects": [dict(_FIRE)]} for lid, moves in {
    "tbinblak": "the forge fire flares (orange px above the anvil)",
    "tbincstl": "the castle gate's fire pit burns", "tbincstl_2": "the castle gate's fire pit burns",
    "tbincstl_3": "the castle gate's fire pit burns",
    "tbindw_0": "the imp crucible's flames flicker", "tbindw_0_2": "the imp crucible's flames flicker",
    "tbindw_1": "the hall of sins' braziers burn", "tbindw_1_2": "the hall of sins' braziers and pyre burn",
    "tbinext1": "the brimstone pyre burns",
    "tbinmage": "the mage guild's fire bowls burn", "tbinmage_2": "the mage guild's fire bowls burn",
    "tbinmage_3": "the mage guild's fire bowls burn", "tbinmage_4": "the mage guild's fire bowls burn",
}.items()}

# ------------------------------------------------------------------------------------------------ scene / catalog
# hand-set: the painted sun sits low behind the town on the left, so the painting has no readable front key; a key
# from the left and toward the camera (Stronghold's) keeps the relief legible on the pans. The albedo bake divides by
# the rig, so the rest pose reproduces the painting whatever the direction.
TO_SUN_CAM = (-0.55, 0.55, 0.62)
# positions.json keys Inferno's layers by DEF name (building_layer_map.json maps the OE SIDs onto them); the horde
# layers (tbinhrd*) share the dwellings' places and are left out of the review states
# render-only (not in the catalog): the building layer map reaches level 3 hall, level 4 guild, the _2 dwellings
# and no tbinext0 / tbifext5 (the fx_v1 editor render refused 'full': tbinhall_4 not in the bundle), so the review
# states name the highest reachable level of each building (as Dungeon, 738d9c3098)
STATES = {
    "start": ["tbinhall", "tbintvrn", "tbindw_0"],
    "full": ["tbinhall_3", "tbincstl_3", "tbinmage_4", "tbintvrn", "tbinmark", "tbinsilo", "tbinblak",
             "tbinext1", "tbinext2", "tbinholy", "tbindw_0_2", "tbindw_1_2", "tbindw_2_2", "tbindw_3_2",
             "tbindw_4_2", "tbindw_5_2", "tbindw_6_2"],
    "anim": ["tbincstl_3", "tbinext1", "tbinmage_4"],
}
WATER_USE = "none: the town stands on a lava floor (no river, lake or basin in the painting)"

# ------------------------------------------------------------------------------------------------ sky
# Crimson sky with BLACK smoke clouds: the clouds (L* 0.4 median) are as black as the mountain range (L* 0), so no
# colour box separates them; the lane caps the sky rows at the horizon (+4 frame px, HoMM3 y ~94), which lies above
# every painted peak (the highest, x ~645, tops out at HoMM3 y ~122), so the whole band above the cap connected to the
# top edge is sky (sun and clouds alike). The red sky below the cap, between the peaks, stays painting at the far cap.
# The fill's own sky: extension rule "none", so the grade matches it to the painting like the ground. SDXL paints a
# pale salmon / grey sunset sky (L* ~50-70) for this prompt; left ungraded (the first grade kept the box 'every colour
# above frame row 215', tex/superseded_extsky_ungraded/) it stood as a bright band beside the crimson painted sky.
SKY_MASK = {"rule": "lab", "reason": "crimson sky with black smoke clouds; the horizon row cap excludes the black "
            "mountain range, which colour cannot", "lMin": -1.0, "lMax": 101.0,
            # the crimson sky runs below the horizon row down to the black ridge (frame row ~297 at the right edge);
            # carried by the relief it stopped at x = TW as a slab (fx_v1 seam-line rows 150-250, ratio ~120). The
            # ridge is L* ~0, that sky 13-21 (measured on the frame-rect painting, blurred 1.2 px)
            "belowHorizon": {"capHoMM3Y": 185.0, "lMin": 8.0},
            "extension": {"rule": "none"}}
SKY_ANIM = {"mode": "deferred", "reason": "the periodic 360 deg sky band is being rebuilt in the parent's change; "
            "drift follows it"}
# the static dome's periodic 360 deg panorama outside the painted sky (town_full3d_sky kit, then town_full3d_sdfill.py --step sky):
# the mirror dome streaked right of the painted rect under the sweeps
SKY_PANO = {"key": "p1_s11", "seed": 11,
            "prompt": "hand-painted fantasy game background sky, 1990s painted matte art, hellish dark crimson sky, billowing blood-red and black smoke clouds, ember glow, sky and clouds only",
            "negative": "blue sky, white clouds, daylight, green, photo, photorealistic, land, ground, hills, mountains, trees, water, building, tower, person, bird, horizon line, text, watermark, frame, border, seam, lowres"}
# the painted sky continued across the rect's side edges onto the panorama (town_full3d_sky SKY_EDGE_JOIN): without it
# the dome is pure panorama right of x = TW and the painted clouds end in a vertical step (seam-line gate, fx_v1 rest)
# rectFeather False: the belowHorizon sky rows reach the right-edge ridge, and the default feather toward the rect's
# own relief tinted them with the smoky panorama (seam-line rows 243-294)
SKY_EDGE_JOIN = {"method": "mirror", "edges": ["right", "left"], "fadePx": 360.0, "rectFeather": False,
                 "reason": "the panorama beside the painted rect does not continue the painted clouds"}
ANIM_CROSSWALK = {}   # every layers/anims id is a positions.json layer id

# ------------------------------------------------------------------------------------------------ framing
# measured (town_full3d_framing.py measure, sdgrade_v2 stage, 2026-09-28; framing/inferno*.json): zoom 1.22 is the
# largest at which every building's body bounds stay inside the visible (non-HUD) region at the rest view with the
# building-centred aim (1.23 pushes the blacksmith under the right HUD column and the village / town / city hall past the
# left edge, and the blacksmith is then reachable from no pose). The visible viewport goes from 67% painting to 95% at
# rest. panScale 0.5: every pan pose >= 84% painting (62-73% at the native zoom and pan; 1.22 with the native pan
# extent would drop the sweeps to 75-79%).
FRAMING = {"zoom": 1.22, "aim": "buildings", "panScale": 0.5,
           "reason": "the painting fills the visible region between the HUD panels; the extension seams leave the view"}

# ------------------------------------------------------------------------------------------------ texture (sdgrade)
TEX = {
    "styleCropNative": (180, 80, 620, 320),
    # context 'props': the painted huts (propMask) are pre-filled in the SD input, so the model sees the lava floor it
    # continues and cannot clone the huts into the extension. Seeds 11 / 23 / 37 tried (kit/sdinpaint_runs/p1_s*_props):
    # 11 paints a flat pale plain, 37 volcano cones, a creature and a signature scribble; 23 continues the red ridges
    # on the left and carries thin lava veins over the floor.
    # p2 (a 'dark ... at night' prompt with 'bright sky, orange sunset' negated; seeds 23 / 5 / 41, p2_s*_props) did not
    # darken SDXL's sunset sky and grew grey smoke masses and a lone peak at the right: rejected, p1 kept.
    "sd": {"prompt": ("a matte painting of a volcanic valley at dusk, a dark basalt and grey ash plain cracked with "
                      "thin glowing orange lava veins, jagged dark red eroded rock ridges and cliffs, a black volcanic "
                      "mountain range on the horizon, dark crimson sky with black smoke clouds, painterly, detailed"),
           "negative": ("building, house, hut, roof, tent, tower, castle, wall, fence, person, animal, demon, road, "
                        "path, river, water, lake, sea, green, grass, trees, blue sky, snow, sun, moon, text, "
                        "watermark, signature, frame, border, blurry, lowres, jpeg artifacts, photo"),
           "promptKey": "p1", "seed": 23, "context": "props"},
    "clean": [],
    "integrate": {"esrgan": True, "grain": True,
                  "paintFloor": (790, 590, 1000, 665),   # bare lava floor between the hut rows, clear of the huts
                  "floorRamp": (370, 450)},               # grain weight 0 above (mountains, sky), 1 below (floor)
    # floorRows: the target band for the extension below the rect. The painting's bottom rows (590-665) are covered by
    # building layers across frame x 540-720, so the grade there borrowed the lighter grey lava patch at x 780-900 and
    # printed a pale ghost column under the Efreet domes (tex/superseded_floorrows_590/); rows 520-600 carry bare
    # floor across the width and the column is gone (gradetry/cmp.png).
    "grade": {"floorRows": (520, 600), "cliffRows": 380, "floorzRows": 440, "extOnlyBands": True},
    # the painted huts: their dark shingle roofs and walls share the lava floor's colours (hue_white also keeps the
    # orange lava streaks), so they are found as disparity bumps (town_full3d_masks da_bump). Measured on this
    # painting: 22 components; misses the small cluster behind the left ridge (HoMM3 x 210-255, y 233-260, merged
    # with the ridge) and keeps three small ridge crests (left edge, x 108-140 y 244-270, right edge)
    "propMask": {"rule": "da_bump", "openPx": 61, "relMin": 0.06, "minRow": 400, "rowFracMax": 0.4, "minArea": 150,
                 "maxWidth": 150, "minHeight": 18, "extendDown": 0.9, "dilate": 7},
    "blend": {"toneRows": (380, 480)},   # the red ridges beside the side edges; faded to 0 on the floor
    # right-edge bridge (town_full3d_sdfill --step bridge, between grade and blend): the painting's red ridges and lava floor continued into a band of the
    # extension (fx_v1 rest: the fill's black ridge stood against the painted sky, seam-line rows 150-250)
    "bridge": {"prompt": ("a matte painting of a hellish volcanic wasteland, dark crimson rock ridges, cracked black "
                          "and red ground with glowing lava veins, red smoky haze, painterly, detailed"),
               "negative": ("building, house, cottage, hut, tent, tower, castle, wall, fence, roof, person, animal, road, "
                            "text, watermark, signature, frame, border, seam, vertical line, blurry, lowres, "
                            "jpeg artifacts, photo"),
               # seed 41 of 37/5/11/23/41/51/53/77/101/131/173: canvas seam-line p90 3.42 (37: 4.24)
               "seed": 41, "bandPx": 192, "fadePx": 96, "rowsBelowPx": 48, "contextPx": 560, "strength": 0.6,
               "rectContext": None},
    "renderRefPass": True,
}

# ------------------------------------------------------------------------------------------------ terrain
# measured: Depth Pro inverse depth over the valley-floor polygon (huts masked by the da_bump prop mask) is linear in
# the row (Tukey IRLS, 99.8-100% inliers) and reaches 0 at HoMM3 y 82-102 over row starts 380-520 (column bands
# x 100-500: 86-95); two painted huts' walls (16.5 px at base y 294, 14 px at base y 262) scale as (base - 92) within 2%.
# The horizon lies above the painted mountain range (its foot at y ~205): the painter's floor is steep.
HORIZON_HOMM3_Y = 92.0
# measured: the hut at HoMM3 x 600-630 has a 16.5 px wall (eave y 277.5 to base y 294) = 0.706 camera units at its
# depth on this floor plane (the hut at x 530-555, 14 px at base 262, gives 0.712); one-storey eave hand-set 2.2 m as
# Stronghold's.
HUT_WALL_UNITS, HUT_EAVE_M = 0.71, 2.2
FAR_CAP_M = 400.0
# Hand-traced valley floor (HoMM3 px): below the mountains' foot, inside the red ridges on both sides.
FLOOR_POLY_HOMM3 = [(180, 215), (300, 207), (450, 204), (560, 207), (590, 225), (600, 260), (640, 300), (720, 312),
                    (800, 318), (800, 374), (170, 374), (200, 340), (240, 300), (250, 265), (215, 240)]
SPUR_SCALE, SPUR_AMP = 8.0, 0.6     # hand-set: jagged eroded ridges, between Castle's hills and Stronghold's spurs
WALL_SHIFT_M = 60.0                 # hand-set: the ridges close round the valley

# ------------------------------------------------------------------------------------------------ ground
# (vanilla texture, metres per tile) - hand-set. Of the vanilla lava ground set, 1024_15/16 and b_1024_1 are mesh UV
# atlases (a painted cactus, a lava pool, red plant cards) and 256_1_lava_stones is an alpha card, and
# 1024_13_lava_rocks_01 is the Lava_rock meshes' atlas: none is used as tiling detail.
FLOOR_TEX = (("1024_14_ground_lava_1", 5.0), ("512_8_dirt_volcanic_rock_diffuse", 4.0),
             ("1024_14_ground_lava_1", 7.5))
ROCK_TEX = (("512_8_dirt_volcanic_rock_diffuse", 8.0), ("1024_14_ground_lava_1", 10.0))
ROCK_ROT = {}
DETAIL_CONTRAST = 2.0
ROCK_CONTRAST = 3.0
FLOOR_STONES = (("512_8_dirt_volcanic_rock_diffuse", 2.2),)
STRATA_COLS = {"left": (0, 300), "right": (1150, 1440)}
CONTRAST_REGIONS = {"floor": ((790, 430, 1000, 560), (100, 720, 1800, 1000)),
                    "rightWall": ((1100, 390, 1430, 520), (1480, 390, 1900, 560))}

# ------------------------------------------------------------------------------------------------ periphery
ROCK_MESHES = {"Lava_rock_01": "1024_13_lava_rocks_01_diffuse", "Lava_rock_02": "1024_13_lava_rocks_01_diffuse",
               "Lava_rock_03": "1024_13_lava_rocks_01_diffuse", "Lava_rock_04": "1024_13_lava_rocks_01_diffuse"}
# No scrub: the painted lava floor carries no plants
SCRUB_MESH, SCRUB_TEX = None, None
PERIPHERY_SCATTER = {
    "scrub": {"required": False, "reason": "no scrub: the painted lava floor and ridges carry no plants"},
    "rock": {"required": True, "prefixes": ["Mesh_Outer_boulders_"]},
    "nearDensity": {"source": "profile", "perM2": 0.0028,
                    "reason": "the olive-blob count has no olive scrub to read on a lava floor; Stronghold's "
                              "measured density"}}
ROCK_SIZE_M = (1.0, 4.0)
SCRUB_SIZE_M = (1.2, 2.6)
SCRUB_ROW0 = 400
PERIPHERY_VANILLA_NOTE = ("vanilla Inferno terrain is lava ground and volcanic rock; the Inferno outer world continues "
                          "the painted red ridges and lava floor")
PERIPHERY_WATER = {"required": False, "reason": "the painting has no water: a lava floor with thin lava veins, no "
                   "river or lake leaving the frame"}

# ------------------------------------------------------------------------------------------------ near field
NEAR_ROCKS = ("Lava_rock_01", "Lava_rock_02", "Lava_rock_03")
PEBBLE = "Lava_rock_04"

# ------------------------------------------------------------------------------------------------ vanilla filler
VANILLA_TEXTURES = {
    "1024_14_ground_lava_1": 1024, "512_8_dirt_volcanic_rock_diffuse": 512, "1024_13_lava_rocks_01_diffuse": 1024,
}
VANILLA_VFX = {
    "WaterNormal": 1024, "TileNoise_07_vfx": 256, "TileNoise_23_vfx": 512, "TileNoise_19_vfx": 512,
    "glow_08_vfx": 256, "glow_10_vfx": 512, "glow_18_vfx": 64, "smoke_06_vfx": 256,
}
VANILLA_MESHES = ("Lava_rock_01", "Lava_rock_02", "Lava_rock_03", "Lava_rock_04")

# ------------------------------------------------------------------------------------------------ buildings
# the Brimstone Stormclouds (tbinext0) hang in the sky over the town: no terrain below the sprite. Hand-set 380 m, inside
# the far cap (400 m) and the sky dome (415 m), so the clouds read as sky above every building.
RELIEF_TUNE = {"tbinext0": {"floatZm": 380.0}}
PARTS_LAYERS = set()        # no part separation until a review earns it (Stronghold's bar)
BACK_FILL_LAYERS = None     # every layer takes the edge-filled back (evaluation)
SOLID_TUNE = {
    "tbindw_5": {"n": 2.0}, "tbindw_5_2": {"n": 2.0}, "tbindw_5_3": {"n": 2.0},   # the Efreet's onion domes
    "tbindw_6": {"n": 2.0}, "tbindw_6_2": {"n": 2.0}, "tbindw_6_3": {"n": 2.0},   # the Devils' round dome
}

# Building mask (stronghold_full3d_buildings.coherent_painting), as Dungeon: only the rim-connected carried painting is
# cut from a sprite (2026-10-18 no-Meshy nm1 rollout, all buildings solid + MoGe relief).
MASK_PAINT_COHERENT = True
