"""Castle profile of the full-3D town lane (docs/homm3_stronghold_full_3d_town.md). Pilot of the per-faction rollout:
a meadow valley under a clouded blue sky, limestone spires and a waterfall on the left hills, a distant lake and snow
peaks through the middle, rows of painted (non-layer) cottages on the meadow. Measured values say where they come
from; hand-set values say so. Proof tier: staged candidate only (no bundle, no install).
"""
from __future__ import annotations

# ------------------------------------------------------------------------------------------------ identity
FRACTION = "homm3_castle"
BACKGROUND = "Castle-in-background.png"
DATA_DIR = "homm3_castle_full3d"
BUNDLE = "homm3_town_scene3d_castle"
PREFIX = "homm3_castle3d_"
ASSET_ROOT = "Assets/Homm3TownScene3d/castle"
LABEL = "Castle"
FX_MODULE = "town_full3d_fx"   # the shared profile-classified effects module (FX_LAYERS below)

# Animated reachable layers (layers/anims/metadata.json frames > 1), classified from the DEF's changed-pixel mask
# (town_all/fx_probe/castle_changed.png, 2026-09-28). Kinds and filters are hand-set from that look; place, extent,
# colour and timing are measured by town_full3d_fx from the DEF itself.
# SUBSTITUTE: the shared module has no cloth kind, so the waving banners are a masked 'glow' (the banner cloth breathes
# in its own measured colour) - a vanilla-style stand-in for the wave, not the wave itself.
_BANNERS = {"moves": "the blue-and-gold banners wave (cloth px across every frame)",
            "effects": [{"kind": "glow", "why": "substitute for the cloth wave (no cloth kind): the banners' own "
                                                "changed px breathe over the DEF loop"}]}
FX_LAYERS = {
    "tbcshall": _BANNERS, "tbcshal2": _BANNERS, "tbcshal3": _BANNERS,
    "tbcsdw_5": _BANNERS, "tbcsdw_5_2": _BANNERS,
    "tbcsdock": {"moves": "the lake water at the shipyard ripples (2-frame DEF, the shore water patch)",
                 "effects": [{"kind": "water"}]},
    "tbcsmag3": {"moves": "the two blue crystal orbs at the guild's foot pulse (white/blue px)",
                 "effects": [{"kind": "glow"}]},
    "tbcsmag4": {"moves": "the two blue crystal orbs at the guild's foot pulse (white/blue px)",
                 "effects": [{"kind": "glow"}]},
    "tbcsspec": {"moves": "the light at the lighthouse top shimmers (pale blue px, 20 frames)",
                 "effects": [{"kind": "glow"}]},
}

# ------------------------------------------------------------------------------------------------ scene / catalog
TO_SUN_CAM = (-0.55, 0.55, 0.62)   # hand-set: the towers' lit faces look left and toward the camera, as Stronghold's
# positions.json keys Castle's layers by DEF name (building_layer_map.json maps the OE SIDs onto them)
# Only the layers building_layer_map.json nativeLevels reaches are built (stronghold_full3d_common.reachable_layers), so
# "full" is the highest reachable level of each (as Necropolis): tbcshal4, tbcsext0-2, tbcshrd3, tbcstext5 and the
# third upgrades (tbcsdw_*_3) have no native level and no prefab (the Unity RenderStates stopped on tbcshal4).
STATES = {
    "start": ["tbcshall", "tbcstvrn", "tbcsdw_0"],
    "full": ["tbcshal3", "tbcscas3", "tbcsmag4", "tbcstvrn", "tbcmark", "tbcssilo", "tbcsblak", "tbcsspec", "tbcsdock",
             "tbcshrd2", "tbcsholy", "tbcsdw_0_2", "tbcsdw_1_2", "tbcsdw_2_2", "tbcsdw_3_2", "tbcsdw_4_2", "tbcsdw_5_2",
             "tbcsdw_6_2"],
    "anim": ["tbcshall", "tbcsspec", "tbcsdock"],   # tbcsext2 (animated) is unreachable: tbcsspec, also animated
}
WATER_USE = "the painted lake behind the town (inside the painting; no water body leaves the frame)"

# ------------------------------------------------------------------------------------------------ sky
# Clouded blue sky: white cumulus is not blue, so the Stronghold 'blue' rule would cut the clouds out of the sky. The
# CIELAB box takes blue sky and white / grey cloud alike (b* < 2, L* > 40) and leaves the tan spires (b* ~ +28) and the
# green hills (b* > 15). The snow peaks read as sky in colour (L* 63-73, b* -22), so rows are capped at HoMM3 y 122,
# just above the highest peak (the right-hand mountain, y ~124). The fill's own sky reaches lower beside the rect (its
# hills stand lower), so the extension rule caps at frame row 330 (the fill's hill tops; its snow peaks may read as sky
# there and keep their fill colour ungraded, which is harmless). The fill paints a deeper blue (L* ~30) than the
# painting, so its floor is L* 20 (its dark pines have b* > +5).
SKY_MASK = {"rule": "lab", "reason": "blue sky with white cumulus; snow peaks excluded by the row cap",
            "bMax": 2.0, "lMin": 40.0, "maxHoMM3Y": 122.0,
            "extension": {"bMax": 2.0, "lMin": 20.0, "maxRow": 330}}
# The right wall's far part scaled per azimuth onto the bridged canvas's own skyline (stronghold_full3d_terrain.
# fit_ext_skyline; Rampart's / Bulwark's values). Without it the wall keeps the painted edge's profile (top ~ frame row
# 222 at x 1445-1700), 25-60 px above the canvas's skyline, so the canvas's sky (the cloud's dark-blue underside, the
# fill's pale haze) was projected onto rock: a horizontal cloud cut-off and a dark / pale band right of the mage tower
# (seam_v1 Unity rest rows ~213-240). skyRule: the fill paints its pines and peaks in the sky's blue, so the extension
# box takes them as sky; smooth-and-in-box sky, 30-row rock runs, 41-column median (viewed:
# town_all/castle/ext_skyline_run.png, middle panel, before the median)
EXT_SKYLINE = {"rhoMinM": 20.0, "rhoFullM": 60.0, "kMin": 0.05, "kMax": 8.0, "fadeDeg": 0.05, "maxBinsAtKMax": 4,
               # seam_v3: the re-bridged canvas (TEX bridge rowRepaint) continues the painting's snow-capped mountains
               # across the edge; rockLab keeps their smooth grey body out of the sky (it had dropped the wall to rows
               # 272-285, the mountains then drifting on the dome), and edgeRampPx 48 starts the wall at the painted
               # edge's own terrain top (212.5) so the painting's dark-blue sky under the cloud, which the rect shows on
               # its terrain at rows 213-230, continues on the wall (the canvas there is that same dark blue now) instead
               # of meeting the dome's lighter haze in a vertical step at x 1443. seam_v2 had no ramp: the old canvas
               # was cloud underside there, and the ramp raised the wall over it.
               "skyRule": {"stdMax": 4.0, "stdWin": 11, "rockRunPx": 30, "medianPx": 41,
                           "rockLab": {"lMax": 55.0, "bMin": -18.0}},
               "edgeRampPx": 48}
# Very slow cloud drift (town_full3d_sky): vanilla cityHuman2 animates no sky (static panoramic skybox, no time
# parameter), so the owned band applies. The painting's own sky, extended to a periodic band, turns about the camera.
SKY_ANIM = {"mode": "drift", "reason": "open cumulus sky over the lake; slow drift reads as weather, no native "
            "sky animation to reuse", "periodS": 2400.0}
# the periodic 360 deg panorama the dome and the drift band take outside the painted sky (town_full3d_sdfill.py --step sky)
SKY_PANO = {"key": "p3_s7", "seed": 7,
                     "prompt": ("hand-painted fantasy game background sky, 1990s painted matte art, deep saturated "
                                "cobalt blue sky, crisp white cumulus clouds with painterly brush strokes and sharp "
                                "bright edges, clear daylight, sky and clouds only"),
                     # SDXL keeps the first 77 CLIP tokens: the words that matter come first
                     "negative": ("photo, photorealistic, soft blurry clouds, haze, grey sky, land, ground, hills, "
                                  "mountains, trees, water, sea, building, castle, tower, bird, person, sun disc, "
                                  "horizon line, sepia, brown, beige, dusk, sunset, storm, text, watermark, frame, "
                                  "border, seam, lowres")}
# the painted sky continued across the rect's side edges onto the panorama (town_full3d_sky SKY_EDGE_JOIN): without it
# the dome is pure panorama right of x = TW and the painted clouds end in a vertical step (seam-line gate, fx_v1 rest)
# mirrorUnderBuildings: the painting's clouds are finished behind the mage tower and the wall towers (viewed:
# town_all/castle/tex_bridge_v2/v2/under_tower.png), so the edge's tower columns are mirror sources too
# canvasBelowMirror: with EXT_SKYLINE the far wall stands at the canvas skyline, below the painted sky's bottom; those
# directions take the bridged canvas instead of the flat panorama (seam_v2)
SKY_EDGE_JOIN = {"method": "mirror", "edges": ["right", "left"], "fadePx": 360.0, "mirrorUnderBuildings": True,
                 "canvasBelowMirror": True, "canvasBlendPx": 48.0,
                 "reason": "the panorama beside the painted rect does not continue the painted clouds"}
ANIM_CROSSWALK = {}   # every layers/anims id is a positions.json layer id

# ------------------------------------------------------------------------------------------------ framing
# measured (town_full3d_framing.py measure, sdgrade_pilot stage, 2026-09-28; framing/castle*.json): zoom 1.19 is the
# largest at which every building's body bounds stay inside the visible (non-HUD) region at the rest view with the
# building-centred aim (1.20 pushes the marketplace under the hero panel and the Portal of Glory's cloud over the top
# frame, and the marketplace is then reachable from no pose). The visible viewport goes from 66% painting to 93% at
# rest. panScale 0.5 as Stronghold: every pan pose >= 79% painting (62-71% before).
# 1.19 -> 1.18 (2026-10-19, no-split ns1): the uncut sprite bodies reach a fraction of a px past the cut bodies, which
# put the marketplace 0.0004 under the hero panel and the Portal of Glory 0.0004 over the top frame at 1.19.
FRAMING = {"zoom": 1.18, "aim": "buildings", "panScale": 0.5,
           "reason": "the painting fills the visible region between the HUD panels; the extension seams leave the view"}

# ------------------------------------------------------------------------------------------------ texture (sdgrade)
TEX = {
    "styleCropNative": (180, 60, 560, 300),
    # context 'props': only the painted cottages (propMask) are regenerated inside the rect, so the model sees the
    # meadow it continues. seed 37 p1 with the Stronghold row rule (context nohuts) lost the meadow context and grew
    # pink slickrock and giant daisies (sdinpaint_runs/p1_s37_nohuts): superseded.
    "sd": {"prompt": ("a matte painting of a wide green grass meadow in a valley, short lush grass with small yellow "
                      "specks, rolling green hills with a few tan limestone spires and dark pine woods, distant blue "
                      "mountains with snow caps, bright afternoon sunlight from the left, deep blue sky with white "
                      "cumulus clouds, painterly, detailed"),
           "negative": ("building, house, cottage, roof, hut, tent, tower, castle, wall, fence, person, animal, road, "
                        "path, river, water, lake, flowers, daisies, pink, purple, sandstone, slickrock, desert, "
                        "canyon, text, watermark, signature, frame, border, blurry, lowres, jpeg artifacts, photo"),
           "promptKey": "p2", "seed": 11, "context": "props"},
    "clean": [],
    "integrate": {"esrgan": True, "grain": True,
                  "paintFloor": (20, 600, 560, 665),   # bare meadow at the bottom left, clear of the cottages
                  "floorRamp": (380, 470)},             # grain weight 0 above (hills, sky), 1 below (meadow)
    # extOnlyBands: the painting's left edge is darker than its fill beside the cottages, and whole-canvas bands
    # amplified that step into a bright seam halo (L/floor gain 1.59)
    "grade": {"floorRows": (600, 665), "cliffRows": 380, "floorzRows": 440, "extOnlyBands": True},
    # the painted cottages: warm roof tiles and timber (hue 20-62 deg) or whitewash, on the meadow rows only
    "propMask": {"rule": "hue_white", "hueMin": 20.0, "hueMax": 62.0, "chromaMin": 10.0, "lMax": 65.0,
                 "whiteL": 62.0, "whiteChromaMax": 16.0, "close": 5, "minArea": 200, "dilate": 7, "minRow": 370,
                 "darkL": 20.0},   # measured: meadow L* p1 24.6, cottage shade p5 13.6,
    "blend": {"toneRows": (330, 420)},   # the hills beside the side edges; faded to 0 on the meadow
    # right-edge bridge (town_full3d_sdfill --step bridge, between grade and blend): the painting's meadow and hills continued into a band of the
    # extension; the edge longhouses are modelled (houses, openRectEdges) and carved out of the SD context
    "bridge": {"prompt": ("a matte painting of a wide green grass meadow, rolling green hills with dark pine woods, "
                          "distant blue mountains, bright afternoon sunlight from the left, painterly, detailed"),
               "negative": ("building, house, cottage, hut, tent, tower, castle, wall, fence, roof, person, animal, road, "
                            "text, watermark, signature, frame, border, seam, vertical line, blurry, lowres, "
                            "jpeg artifacts, photo"),
               # seed 173 of 5/11/23/37/41/51/53/77/101/131/173 (writeSky): continues the rock spires and the blue
               # mountain band across the edge; canvas seam p90 3.85 (41: 4.56; 51 scores 3.73 but invents round hills)
               "seed": 173, "bandPx": 192, "fadePx": 96, "rowsBelowPx": 48, "contextPx": 560, "strength": 0.6,
               "rectContext": "housesCarved",
               # the painted forest ridge at the edge stands above the fill's skyline, so its slope can only
               # continue into pixels the fill left as sky (seam_v2: EXT_SKYLINE with its own skyRule; the extension box takes the fill's blue pines as sky)
               "writeSky": True,
               # the building mask's 3 px margin past the rect (x 1440-1442) is also extension sky at rows 180-280 here,
               # so neither the bridge nor the blend wrote it: a dark strip L* 33.6 between 46.4 and 42.3 (seam line)
               "writeExtBuildingMask": True,
               # seam_v3: seed 173 left rows 170-250 beside the edge as smooth dark sky (L* ~34, b* ~-38) where the
               # painting's mountain band starts at row ~228; the sky join and the ghost wall showed it as a dark
               # blob with a hard left edge. A second pass over those rows continues the mountains / haze instead.
               "rowRepaint": {"rows": [150, 272], "seed": 23, "fadePx": 24, "strength": 0.9,
                              "prompt": ("a matte painting of distant blue mountains with snowy peaks fading into soft "
                                         "pale atmospheric haze under white clouds, bright afternoon light, painterly, "
                                         "detailed"),
                              "negative": ("dark sky, night, storm, building, house, tower, castle, wall, person, "
                                           "text, watermark, signature, frame, border, seam, vertical line, blurry, "
                                           "lowres, jpeg artifacts, photo")}},
    # RESOLVED 2026-09-29 (seam_v1): the earlier known failure (canvas p90 3.85 at best; wider bands, EDGE_FRAY and
    # EXT_SKYLINE all rejected) was the building mask's 3 px margin past the rect: at rows 180-280 it is also
    # extension sky, so with the bridge's default bkeep neither the bridge nor the blend wrote it (L* 33.6 between
    # 46.4 and 42.3, a dark line through the ridge band). With the bridge's writeExtBuildingMask, seed 173 scores
    # canvas p90 3.39 (seed 7 3.04 and 5 3.20, but they grow wind-swept green plumes / a bare yellow hill); the blend
    # options (edgeSource paintedAll, sideEdgePx) change it by < 0.1 here and are not used.
    "renderRefPass": True,
}

# ------------------------------------------------------------------------------------------------ terrain
# measured: Depth Pro inverse depth over the meadow polygon (props masked) is linear in the row (Tukey IRLS, 98% inliers)
# and reaches 0 at HoMM3 y 131.4 (rows >= 380; 129.4-133.3 over row starts 380-500). The snow peaks sit on it.
HORIZON_HOMM3_Y = 131.0
# measured: the cottage at HoMM3 x 570-600 has a 16 px wall (eave y 273 to base y 289) = 0.695 camera units at its
# depth on this floor plane (the front cottage, 22 px at base 330, gives 0.759: 9% apart); one-storey eave hand-set
# 2.2 m as Stronghold's.
HUT_WALL_UNITS, HUT_EAVE_M = 0.70, 2.2
FAR_CAP_M = 400.0
# Hand-traced meadow polygon (HoMM3 px): below the hills' feet and the lake shore.
FLOOR_POLY_HOMM3 = [(0, 224), (60, 221), (120, 218), (200, 215), (300, 212), (380, 209), (430, 207), (480, 206),
                    (540, 206), (560, 210), (600, 214), (680, 214), (760, 216), (800, 218), (800, 374), (0, 374)]
SPUR_SCALE, SPUR_AMP = 14.0, 0.35   # hand-set: rounded grassy hills, not badlands spurs
WALL_SHIFT_M = 40.0                 # hand-set: the hills close round the meadow gently

# ------------------------------------------------------------------------------------------------ ground
FLOOR_TEX = (("grass1", 4.0), ("grass2", 4.5), ("512_10_grass_forest_lawn_1_diffuse", 5.0), ("grass3", 5.5),
             ("dirt_ground3", 6.0))
ROCK_TEX = (("512_12_grass_hill_1_diffuse", 12.0), ("grass2", 6.0), ("green_rock_big_diffuse", 9.0))
ROCK_ROT = {}
DETAIL_CONTRAST = 2.0
ROCK_CONTRAST = 3.0
FLOOR_STONES = (("256_7_grass_diffuse", 2.2), ("dirt_grass_diffuse", 3.0))
STRATA_COLS = {"left": (0, 300), "right": (1150, 1440)}
CONTRAST_REGIONS = {"floor": ((720, 390, 1000, 460), (100, 720, 1800, 1000)),
                    "rightWall": ((1100, 290, 1430, 380), (1480, 290, 1900, 420))}

# ------------------------------------------------------------------------------------------------ periphery
ROCK_MESHES = {"Green_Rock_1x1": "green_rock_small_diffuse", "Green_Rock_2x2": "green_rock_big_diffuse"}
# No scrub: the painted meadow carries no bushes, and vanilla bush_small_leaves is an alpha-card foliage mesh that the
# lane bakes as opaque RGB (it drew as black blots in the sdgrade_pilot stage).
SCRUB_MESH, SCRUB_TEX = None, None
# Scatter policy (stronghold.py documents the fields; tools/validate_town_scene3d_contract.py enforces it). Near-field
# stones: the olive-blob density rule counts every grass pixel of a meadow (0.10 /m2, 280 pebbles in the sdgrade_pilot
# stage), so the density is hand-set to Stronghold's measured scrub density (0.0028 /m2).
PERIPHERY_SCATTER = {
    "scrub": {"required": False, "reason": ("no scrub: the painted meadow has no bushes, and the vanilla foliage mesh "
                                            "is alpha-card (the lane bakes opaque RGB)")},
    "rock": {"required": True, "prefixes": ["Mesh_Outer_boulders_"]},
    "nearDensity": {"source": "profile", "perM2": 0.0028,
                    "reason": "the olive-blob count reads a meadow's grass as scrub; Stronghold's measured density"}}
ROCK_SIZE_M = (1.0, 3.5)
SCRUB_SIZE_M = (1.2, 2.6)
SCRUB_ROW0 = 400
PERIPHERY_VANILLA_NOTE = ("vanilla cityHuman2 rings its town with grassy hills and meadow; the Castle outer world "
                          "continues the painted hills and meadow")
PERIPHERY_WATER = {"required": False, "reason": "the painted lake sits inside the frame behind the town and does not "
                   "leave it; a continued water body beside the pans would be invented"}

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
# the Portal of Glory stands on a cloud over the castle: no terrain below its sprite. Hand-set 160 m, behind the castle's
# own footing (tbcscas* 134.9 m) so its cloud reads above and beyond the keep.
RELIEF_TUNE = {k: {"floatZm": 160.0} for k in ("tbcsdw_6", "tbcsdw_6_2", "tbcsdw_6_3")}
PARTS_LAYERS = set()        # no part separation until a review earns it (Stronghold's bar)
BACK_FILL_LAYERS = None     # every layer takes the edge-filled back (evaluation)
SOLID_TUNE = {
    "tbcsmage": {"n": 2.0}, "tbcsmag2": {"n": 2.0}, "tbcsmag3": {"n": 2.0}, "tbcsmag4": {"n": 2.0},   # round tower
    "tbcssilo": {"n": 2.0},                                                                            # round silo
}

# Layers cut by the painting's right frame edge, given a ragged geometric edge (stronghold_full3d_buildings.edge_fray;
# frame px): the castle's wall / tower and the mage guild's tower end in a straight line at x = TW (fx_v1 rest, seam-line rows 175-342)
EDGE_FRAY = {lid: {"minPx": 10, "maxPx": 48, "sigmaPx": 5}
             for lid in ('tbcscstl', 'tbcscas2', 'tbcscas3', 'tbcsmage', 'tbcsmag2', 'tbcsmag3', 'tbcsmag4')}

# Building mask (stronghold_full3d_buildings.coherent_painting), as Dungeon: only the rim-connected carried painting is
# cut from a sprite (2026-10-18 no-Meshy nm1 rollout, all buildings solid + MoGe relief).
MASK_PAINT_COHERENT = True
