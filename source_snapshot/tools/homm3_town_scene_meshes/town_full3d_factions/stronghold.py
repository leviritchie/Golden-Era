"""Stronghold profile of the full-3D town lane (docs/homm3_stronghold_full_3d_town.md,
docs/homm3_town_depth_building_solids.md). Values moved verbatim from the stronghold_full3d_* modules when the lane took
a faction argument; the installed solid_v3 bundle rebuilds byte-identically from them.
"""
from __future__ import annotations

import math

# ------------------------------------------------------------------------------------------------ identity
FRACTION = "homm3_stronghold"                      # town_scene_refs/<FRACTION>, catalog "fraction"
BACKGROUND = "Stronghold-in-background.png"        # the HoMM3 town screen (800x374)
DATA_DIR = "homm3_stronghold_full3d"               # artifacts/<DATA_DIR> (STRONGHOLD_FULL3D_ROOT overrides)
BUNDLE = "homm3_town_scene3d_stronghold"
PREFIX = "homm3_stronghold3d_"
ASSET_ROOT = "Assets/Homm3TownScene3d/stronghold"
LABEL = "Stronghold"                               # review sheet captions
FX_MODULE = "stronghold_full3d_fx"                 # animated-building effects (fountains, windmill, lightning)

# ------------------------------------------------------------------------------------------------ scene / catalog
# Key light: hand-set from the painting (lit faces of the obelisks / towers look left and toward the camera); the
# albedo bake divides by this rig, so the rest pose reproduces the painting whatever the direction; it only decides
# how the relief reads when the camera pans. toSun in camera axes (right, up, toward camera):
TO_SUN_CAM = (-0.55, 0.55, 0.62)
STATES = {
    # HoMM3 build states for the editor renders (every layer is also its own prefab; the runtime swaps by BhBuilding)
    "start": ["extraCapitol_1", "tavern", "dwellingUp2Lvl1_1"],
    "full": ["extraCapitol_3", "wall_3", "magicGuild_3", "tavern", "market", "resourceDepot", "artifactMarket", "bank",
             "lyceum", "dwellingUp2Lvl1_2", "dwellingUp2Lvl2_2", "dwellingUp2Lvl3_2", "dwellingUp2Lvl4_2",
             "dwellingUp2Lvl5_2", "dwellingUp2Lvl6_2", "dwellingUp2Lvl7_2"],
    "anim": ["extraCapitol_1", "dwellingUp2Lvl6_2", "dwellingUp2Lvl7_2"],
}
WATER_USE = "the Town Hall fountain basins (no river in this town)"

# ------------------------------------------------------------------------------------------------ sky
# Explicit per-faction rule (town_full3d_masks.sky_mask); there is no default rule and no fallback to another faction's.
#   rule "blue": blue, bright, connected to the top edge, above the horizon (+4 px) - the lane's original rule.
#   extension: the grade's rule for the outpaint's own sky (CIELAB; rows >= maxRow never sky).
SKY_MASK = {"rule": "blue", "reason": "clear blue sky over the canyon mouth",
            "extension": {"bMax": -2.0, "aMax": 8.0, "lMin": 45.0, "maxRow": 520}}
# Slow sky drift (town_full3d_sky). Deferred for Stronghold: its scene is being finished separately and its staged
# outputs must rebuild byte-identically; the drift is its own reviewed change.
SKY_ANIM = {"mode": "deferred", "reason": "Stronghold is finished in its own lane; adding the drift is a separate change"}
# DEF ids in layers/anims/metadata.json that are not positions.json layer ids -> the layer they animate. Stronghold's
# lightning was re-keyed in the refs themselves (solid_v3_1); the two banner DEFs have no matching layer (static).
ANIM_CROSSWALK = {}

# ------------------------------------------------------------------------------------------------ texture (sdgrade)
# The frame extension's texture chain (town_full3d_tex): SD inpaint kit -> SDXL fill -> clean -> integrate -> grade.
# Values moved verbatim from the tex_sdgrade scripts (artifacts/claude_takeover_20260927/town_scenes/texture/).
TEX = {
    "styleCropNative": (120, 110, 480, 350),   # a band of the town's own buildings (native px), kit style reference
    "sd": {"prompt": ("a matte painting of a desert badlands canyon, striped red, brown and cream eroded cliffs and "
                      "spires, a red-brown dirt valley floor with sparse dry olive scrub and small stones, bright "
                      "afternoon sunlight from the left, soft blue sky with thin clouds, painterly, detailed"),
           "negative": ("building, house, hut, tent, tower, castle, wall, fence, person, animal, road, river, water, "
                        "text, watermark, signature, frame, border, blurry, lowres, jpeg artifacts, photo"),
           "promptKey": "p1", "seed": 37, "context": "nohuts",
           "floorTopY": 340,      # frame row: below it the painting's floor carries the painted hut rows
           "seamKeepPx": 40},     # context nohuts keeps this much painted floor along the seams
    # signature-like scribbles SD painted into the fill corners, re-inpainted (job:x0,y0,x1,y1[@seed], fill px)
    "clean": ["job_A_right:1448,988,1530,1024", "job_B_left:45,978,300,1024", "job_B_left:1448,988,1530,1024@41"],
    "integrate": {"esrgan": True, "grain": True,
                  "paintFloor": (80, 585, 1300, 665),   # the painting's bare floor (frame box), clear of the edge huts
                  "floorRamp": (420, 520)},              # frame rows: grain weight 0 above, 1 below
    "grade": {"floorRows": (585, 665),   # the painting's bare floor above its dark bottom border
              "cliffRows": 450, "floorzRows": 520},      # local-contrast zone blend rows (cliff above, floor below)
    # painted (non-layer) buildings in the painting, excluded from the grade statistics: the manual lane's low-chroma
    # white-walled hut rule (manual/explore2.py -> hutmask.npy), restricted to the floor polygon by the grade
    "propMask": {"rule": "lowchroma_white", "chromaMax": 17.0, "brightL": 68.0, "brightChromaMax": 26.0, "close": 5,
                 "minArea": 350, "whiteL": 72.0, "whiteChromaMax": 18.0, "minWhite": 25, "dilate": 9},
    # seam blend post-pass: the side-edge tone shift applies above toneRows[0] and fades to 0 at toneRows[1] (cliffs)
    "blend": {"toneRows": (440, 540)},
    # right-edge bridge (town_full3d_sdfill --step bridge, between grade and blend): the painting's cliffs and floor
    # are continued into a band of the extension. No huts: the edge huts are modelled cabins (town_full3d_houses,
    # openRectEdges) that continue past the edge themselves; a painted hut there would be a flat duplicate
    "bridge": {"prompt": ("a matte painting of a desert badlands canyon, striped red, brown and cream eroded cliffs, "
                          "a red-brown dirt valley floor with sparse dry olive scrub and small stones, bright "
                          "afternoon sunlight from the left, painterly, detailed"),
               "negative": ("building, house, hut, tent, tower, castle, wall, fence, roof, person, animal, road, "
                            "river, water, text, watermark, signature, frame, border, seam, vertical line, blurry, "
                            "lowres, jpeg artifacts, photo"),
               "seed": 37, "bandPx": 192, "fadePx": 96, "rowsBelowPx": 48, "contextPx": 560, "strength": 0.6,
               "rectContext": "housesCarved"},
    # grade passes: the second pass adds the step left in the first pass's staged rest preview (render reference)
    "renderRefPass": True,
}

# ------------------------------------------------------------------------------------------------ terrain
HORIZON_HOMM3_Y = 91.0          # measured (see stronghold_full3d_terrain's module doc)
HUT_WALL_UNITS, HUT_EAVE_M = 0.62, 2.2
FAR_CAP_M = 400.0               # painting metres along the ray: the far plain / mesas are clamped here
# Hand-traced floor polygon (HoMM3 px): the painted valley floor below both canyon walls' feet.
FLOOR_POLY_HOMM3 = [(0, 238), (50, 228), (95, 222), (150, 217), (200, 212), (250, 205), (290, 200), (320, 195),
                    (340, 185), (355, 170), (362, 150), (372, 170), (380, 190), (400, 205), (450, 215), (500, 225),
                    (560, 232), (600, 238), (650, 245), (700, 250), (750, 255), (800, 262), (800, 374), (0, 374)]
SPUR_SCALE, SPUR_AMP = 6.0, 0.8   # badlands spurs: across-slope scale (arc m at 100 m) and relative height
WALL_SHIFT_M = 90.0             # a continued wall's foot comes this much nearer per unit of edge weight
                                # (hand-set: the valley closes round the camera as a bowl, the vanilla idiom)

# ------------------------------------------------------------------------------------------------ ground
FLOOR_TEX = (("sand3", 3.6), ("sand1", 4.2), ("dirt_ground4", 5.0), ("dirt_ground1", 4.4), ("sand2", 6.5))
# (vanilla texture, metres per tile) - hand-set. The Dez_Rock / des_rock textures are mesh UV atlases (not tileable)
# and 512_1_dirt_crack carries a painted flower: neither is used as tiling detail.
ROCK_TEX = (("Cliff_01_diffuse", 12.0), ("dirt_ground1", 6.0), ("sand3", 9.0))
ROCK_ROT = {"Cliff_01_diffuse": math.pi / 2}   # its striations run vertically in the texture: turned to strata
DETAIL_CONTRAST = 2.0          # floor detail exponent (calibrated: extension floor log-contrast 0.49/0.61/0.64 vs painting 0.44/0.62/0.73 at sigma 2/6/20 px)
ROCK_CONTRAST = 5.0            # wall rock detail exponent (calibrated with SHADE_GAIN[0], CAV_K: fine scale 0.55 vs painting 0.53)
FLOOR_STONES = (("256_4_desert_stones_diffuse_v2", 2.2), ("512_3_dirt_rock1_diffuse", 3.0))   # pebbly floor layers
STRATA_COLS = {"left": (0, 420), "right": (1150, 1440)}   # rect columns the strata palettes are read from
CONTRAST_REGIONS = {"floor": ((300, 450, 1100, 600), (100, 720, 1800, 1000)),
                    "rightWall": ((1150, 150, 1430, 450), (1480, 150, 1900, 600))}   # (painting box, extension box)

# ------------------------------------------------------------------------------------------------ periphery
ROCK_MESHES = {"Rock_desert_new_01": "1024_1_Dez_Rock_New_01_diffuse", "Rock_desert_new_02": "1024_2_Dez_Rock_New_02_diffuse",
               "Rock_desert_new_03": "1024_3_Dez_Rock_New_03_diffuse", "Des_Rock_01": "des_rock_1_diffuse",
               "Des_Rock_02": "des_rock_2_diffuse", "Des_Rock_03": "des_rock_3_diffuse", "Des_Rock_04": "des_rock_4_diffuse"}
SCRUB_MESH, SCRUB_TEX = "Dead_thorns_01", "512_8_dead_thorns_2_diffuse"
ROCK_SIZE_M = (1.5, 5.0)   # boulder diameter (painting m); the painting's scree blocks read 1-5 m
SCRUB_SIZE_M = (1.6, 3.2)  # bush width; the painted scrub is 1.5-3 m across at the market's depth
SCRUB_ROW0 = 250          # rect rows (1440x673) below which olive pixels are floor scrub, not canyon lichen
PERIPHERY_VANILLA_NOTE = ("vanilla towns carry terrain and hills all round the "
                          "camera's sweep with rock / plant dressing in the mid field; the Stronghold outer world "
                          "continues the painted canyon instead of the vanilla hills")
PERIPHERY_WATER = {"required": False, "reason": "the HoMM3 Stronghold painting has no river or lake leaving the "
                   "frame (dry canyon floor); a continued water body would be invented, not continued"}
# Scatter policy, enforced against the catalog by tools/validate_town_scene3d_contract.py (a profile without it fails):
#   scrub        the catalog's periphery.scatter._tree kind; required -> its declared prefixes must be built bins
#   rock         periphery.scatter._rock, the same rule
#   nearDensity  the near-field dressing density: "measured" (the olive-blob count) or "profile" (perM2 + reason)
PERIPHERY_SCATTER = {"scrub": {"required": True, "prefixes": ["Mesh_Outer_scrub_"]},
                     "rock": {"required": True, "prefixes": ["Mesh_Outer_boulders_"]},
                     "nearDensity": {"source": "measured"}}

# ------------------------------------------------------------------------------------------------ near field
NEAR_ROCKS = ("Rock_desert_new_01", "Rock_desert_new_02", "Rock_desert_new_03")
PEBBLE = "Des_Rock_02"

# ------------------------------------------------------------------------------------------------ vanilla filler
VANILLA_TEXTURES = {   # name -> expected width
    "sand1": 512, "sand2": 512, "sand3": 512, "dirt_ground1": 512, "dirt_ground2": 512, "dirt_ground4": 512,
    "512_1_dirt_crack_in_the_ground_diffuse": 512, "512_6_dirt_rock4_diffuse": 512, "512_3_dirt_rock1_diffuse": 512,
    "1024_1_Dez_Rock_New_01_diffuse": 1024, "1024_2_Dez_Rock_New_02_diffuse": 1024,
    "1024_3_Dez_Rock_New_03_diffuse": 1024, "des_rock_1_diffuse": 1024, "des_rock_2_diffuse": 1024,
    "des_rock_3_diffuse": 1024, "des_rock_4_diffuse": 1024, "Cliff_01_diffuse": 1024,
    "256_4_desert_stones_diffuse_v2": 256, "1024_4_Des_Hill_01_diffuse": 1024,
    "512_7_dead_thorns_1_diffuse": 512, "512_8_dead_thorns_2_diffuse": 512,
}
VANILLA_VFX = {   # name -> expected width; kept RGBA (alpha is the effect's mask) under vanilla/vfx/
    "WaterNormal": 1024, "TileNoise_07_vfx": 256, "TileNoise_23_vfx": 512, "TileNoise_19_vfx": 512,
    "glow_08_vfx": 256, "glow_10_vfx": 512, "glow_18_vfx": 64, "smoke_06_vfx": 256,
}
VANILLA_MESHES = ("Rock_desert_new_01", "Rock_desert_new_02", "Rock_desert_new_03", "Des_Rock_01", "Des_Rock_02",
                  "Des_Rock_03", "Des_Rock_04", "Cliff2_Big", "Cliff2_Small", "Dead_thorns_01")

# ------------------------------------------------------------------------------------------------ buildings (relief)
# Hand-tuned per layer: relief half-range and thickness (m); None = derived from the width.
RELIEF_TUNE = {
    "dwellingUp2Lvl5_1": {"relief": 30.0, "thick": 30.0, "kind": "crag"},
    "dwellingUp2Lvl5_2": {"relief": 30.0, "thick": 30.0, "kind": "crag"},
    "dwellingUp2Lvl6_1": {"relief": 12.0, "thick": 20.0, "kind": "crag"},
    "dwellingUp2Lvl6_2": {"relief": 18.0, "thick": 25.0, "kind": "crag"},
    "dwellingUp2Lvl7_1": {"relief": 25.0, "thick": 30.0, "kind": "crag"},
    "dwellingUp2Lvl7_2": {"relief": 25.0, "thick": 30.0, "kind": "crag"},
    "lyceum": {"relief": 3.0, "thick": 4.0},
    "resourceDepot": {"relief": 1.5, "thick": 2.5},
    "magicGuild_1": {"relief": 4.0, "thick": 5.0},
    "magicGuild_2": {"relief": 4.0, "thick": 5.0},
    "magicGuild_3": {"relief": 4.0, "thick": 5.0},
}

# ------------------------------------------------------------------------------------------------ buildings (solid)
# Layers closed with part separation under --building-method solid_parts (None = every layer: evaluation). Chosen by
# the solid_v2 review: a layer is listed only where it is equal or better than the solid_v1 closure at rest and at the
# sweep extremes; every other layer keeps its solid_v1 geometry.
PARTS_LAYERS = {"dwellingUp2Lvl5_2", "market", "wall_2"}
# Layers whose back half uses the edge-filled texture under --back-fill (None = every layer: evaluation). Chosen by the
# solid_v3 review under the same bar as PARTS_LAYERS; every other layer keeps the solid_v2 back.
BACK_FILL_LAYERS = {
    "artifactMarket",
    "bank",
    "dwellingUp2Lvl4_1",
    "dwellingUp2Lvl4_2",
    "dwellingUp2Lvl5_1",
    "dwellingUp2Lvl6_2",
    "dwellingUp2Lvl7_1",
    "dwellingUp2Lvl7_2",
    "extraCapitol_2",
    "extraCapitol_3",
    "lyceum",
    "magicGuild_1",
    "magicGuild_2",
    "magicGuild_3",
    "resourceDepot",
    "tavern",
    "wall_1",
    "wall_3",
}
# Layers cut by the painting's right frame edge, given a ragged geometric edge (stronghold_full3d_buildings.edge_fray;
# frame px): the Behemoth cave's two sprites end in a straight line at x = TW that the seam-line gate fails on.
EDGE_FRAY = {
    "dwellingUp2Lvl6_1": {"minPx": 10, "maxPx": 48, "sigmaPx": 5},
    "dwellingUp2Lvl6_2": {"minPx": 10, "maxPx": 48, "sigmaPx": 5},
}
# Hand-set per layer where the width rule is wrong. crag: the relief lane's hand-set cliff thickness is the cap.
SOLID_TUNE = {
    "lyceum": {"tmax": 1.2, "n": 2.0},               # a pole with cloth banners and a ring of blades
    "resourceDepot": {"n": 2.0},                     # round tower
    "dwellingUp2Lvl3_1": {"n": 2.0},                 # dome
    "dwellingUp2Lvl3_2": {"n": 2.0},                 # round tower on the dome
    "market": {"partRatio": 1.01, "partColor": 8},   # stalls, cart and hay: shallow depth steps; colour cue splits cart/hay (solid_v3)
    "magicGuild_1": {"n": 2.5}, "magicGuild_2": {"n": 2.5}, "magicGuild_3": {"n": 2.5},   # octagonal tower
}

# ------------------------------------------------------------------------------------------------ framing
# measured (town_full3d_framing.py measure, tex_sdgrade_v31 stage, 2026-09-28): zoom 1.17 is the largest at which every
# building's body bounds stay inside the visible (non-HUD) region at the rest view with the building-centred aim
# (1.18 pushes dwellingUp2Lvl7 over the top frame and the market under the hero panel). The visible viewport goes from
# 67% painting to 90% at rest. panScale 0.5: every pan pose >= 80% painting (60-71% before); below 0.5 buys < 3 points.
FRAMING = {"zoom": 1.17, "aim": "buildings", "panScale": 0.5,
           "reason": "the painting fills the visible region between the HUD panels; the extension seams leave the view"}

# ------------------------------------------------------------------------------------------------ buildings (Meshy T2)
# Layers whose Mesh_Body is a Meshy T2 mesh fitted to the sprite (stronghold_full3d_meshy.py; spend and verdicts in
# docs/homm3_stronghold_t2_town_buildings.md). glb: relative to artifacts/meshy_town_scene_meshes/homm3_stronghold/.
# openRight: the sprite is cut by the painting's right edge (the fit ignores the silhouette past x = TW). sink: share
# of the fitted height pushed into the terrain (default 0.02). stretch: allow the vertical-stretch refinement.
MESHY_T2 = {lid: {"glb": f"{lid}/t2_a1/model.glb"} for lid in (
    "extraCapitol_1", "extraCapitol_2", "extraCapitol_3", "wall_1", "wall_2", "wall_3",
    "magicGuild_1", "magicGuild_2", "magicGuild_3", "tavern", "bank", "market", "resourceDepot", "lyceum",
    "dwellingUp2Lvl1_1", "dwellingUp2Lvl1_2", "dwellingUp2Lvl2_1", "dwellingUp2Lvl2_2", "dwellingUp2Lvl3_1",
    "dwellingUp2Lvl3_2", "dwellingUp2Lvl4_1", "dwellingUp2Lvl4_2", "dwellingUp2Lvl7_1",
)}
# the Behemoth cave is cut by the painting's right edge
MESHY_T2.update({lid: {"glb": f"{lid}/t2_a1/model.glb", "openRight": True}
                 for lid in ("dwellingUp2Lvl6_1", "dwellingUp2Lvl6_2")})
# the Town Hall levels are cut by the painting's left edge (sprite x = 0)
for _lid in ("extraCapitol_1", "extraCapitol_2", "extraCapitol_3"):
    MESHY_T2[_lid]["clipLeft"] = True
# the upgraded thunder crag is the same sprite with a blue bolt (0 px of the rock differ): one mesh, one fit
MESHY_T2["dwellingUp2Lvl7_2"] = dict(MESHY_T2["dwellingUp2Lvl7_1"])
# Review 2026-09-29 (t2_v1 sheet, by eye at the sweeps): mesh surgery (stronghold_full3d_meshy.PARTS_RULES).
# Town Hall: the fountains' water was modelled as solid white domes / spikes / grey cylinders (the seed's Fx_Basin
# effect is the water) and _2 / _3 carry a ground sheet that read as a pale plaza slab. Market: a lone
# two-triangle cloth sheet made the dark awning wedge. Lyceum: the default sink (2% of a tall mast's height)
# buried the thin plinth disc.
for _lid in ("extraCapitol_1", "extraCapitol_2", "extraCapitol_3"):
    MESHY_T2[_lid]["cut"] = ["groundPlate", "fountainJets"]
MESHY_T2["extraCapitol_2"]["basins"] = [[-0.175, 0.12, 0.115, -0.11], [0.21, 0.115, 0.11, -0.11]]
MESHY_T2["market"]["cut"] = ["loneSheets"]
MESHY_T2["lyceum"]["sink"] = 0.0

# Building mask (stronghold_full3d_buildings.coherent_painting), as Dungeon: only the rim-connected carried painting is
# cut from a sprite (2026-10-18 no-Meshy nm1 rollout, all buildings solid + MoGe relief).
MASK_PAINT_COHERENT = True
