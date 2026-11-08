"""Cove profile of the full-3D town lane (docs/homm3_stronghold_full_3d_town.md). A pirate lagoon at dusk (HotA Cove):
a dark palm-topped cliff closes the left, a red-orange sunset under purple-grey cloud fills the middle, a pale
snow-lit mountain and a far shore close the right; the floor is the lagoon itself (dark water reflecting the sunset,
reed tufts, grey boulders, a painted shipwreck on the right shore) with lichen rocks and agave leaves along the bottom
edge. Every house is a building layer. Measured values say where they come from; hand-set values say so.
Proof tier: staged candidate only (no bundle, no install).
"""
from __future__ import annotations

# ------------------------------------------------------------------------------------------------ identity
FRACTION = "homm3_cove"
BACKGROUND = "Cove-in-background.png"
DATA_DIR = "homm3_cove_full3d"
BUNDLE = "homm3_town_scene3d_cove"
PREFIX = "homm3_cove3d_"
ASSET_ROOT = "Assets/Homm3TownScene3d/cove"
LABEL = "Cove"
FX_MODULE = "town_full3d_fx"   # the shared profile-classified effects module (FX_LAYERS below)

# Animated reachable layers classified from the DEF's changed-pixel mask (town_all/fx_probe/cove_changed.png and
# cove_changed_zoomA.png, 2026-09-28). Kinds are hand-set from that look; place, extent, colour and timing are measured
# by town_full3d_fx. Waving flags have no effect kind (no cloth motion in the lane or runtime): their rects are excluded
# and they stay static; the "moves" text says so.
_SHIMMER = "light glints on the dark water under the stilts / pier (sparse reflection flicker)"
FX_LAYERS = {
    "tbcvgral": {"moves": "stars twinkle in the night sky and the large star flares",
                 "effects": [{"kind": "glints", "minPx": 6, "colour": {"minV": 0.55}}]},
    "tbcvhall": {"moves": _SHIMMER, "effects": [{"kind": "glints", "minPx": 6}]},
    "tbcvhal2": {"moves": _SHIMMER, "effects": [{"kind": "glints", "minPx": 6}]},
    "tbcvhal3": {"moves": _SHIMMER, "effects": [{"kind": "glints", "minPx": 6}]},
    "tbcvmark": {"moves": _SHIMMER + "; the two post pennants wave (static here: no cloth kind)",
                 "effects": [{"kind": "glints", "minPx": 6, "exclude": [[100, 0, 150, 45], [370, 0, 420, 45]]}]},
    "tbcvnix1": {"moves": "a faint glimmer on the nix fountain's bowl (8 changed px)",
                 "effects": [{"kind": "glow", "minPx": 4}]},
    "tbcvnix2": {"moves": "a faint glimmer on the nix fountain's bowl (13 changed px)",
                 "effects": [{"kind": "glow", "minPx": 4}]},
    "tbcvnmp1": {"moves": "the waterfall pours down the rock into the pool",
                 "effects": [{"kind": "water", "minPx": 40, "flowDir": [0.0, 1.0]}]},
    "tbcvnmp2": {"moves": "the waterfall pours down the rock into the pool",
                 "effects": [{"kind": "water", "minPx": 40, "flowDir": [0.0, 1.0]}]},
    "tbcvpir1": {"moves": "the hull lanterns and the water at the keel glint; the mast flag waves (static here)",
                 "effects": [{"kind": "glints", "minPx": 6, "exclude": [[70, 60, 92, 84]]}]},
    "tbcvpir2": {"moves": "the hull lanterns and the water at the keel glint; the mast flag waves (static here)",
                 "effects": [{"kind": "glints", "minPx": 6, "exclude": [[50, 0, 95, 30]]}]},
    "tbcvsa2p": {"moves": _SHIMMER, "effects": [{"kind": "glints", "minPx": 6}]},
    "tbcvsay1": {"moves": _SHIMMER, "effects": [{"kind": "glints", "minPx": 6}]},
    "tbcvsay2": {"moves": _SHIMMER, "effects": [{"kind": "glints", "minPx": 6}]},
    "tbcvsmth": {"moves": _SHIMMER + "; the mast flag waves (static here: no cloth kind)",
                 "effects": [{"kind": "glints", "minPx": 6, "exclude": [[0, 0, 67, 56]]}]},
    "tbcvsor2": {"moves": "the lighthouse crystal pulses with pale blue light",
                 "effects": [{"kind": "glow", "minPx": 20}]},
    "tbcvtave": {"moves": _SHIMMER + "; the roof flag waves (static here: no cloth kind)",
                 "effects": [{"kind": "glints", "minPx": 6, "exclude": [[66, 5, 95, 34]]}]},
    "tbcvwhr1": {"moves": "the whirlpool's water churns round its eye",
                 "effects": [{"kind": "water", "minPx": 60}]},
    "tbcvwhr2": {"moves": "the whirlpool's water churns round its eye",
                 "effects": [{"kind": "water", "minPx": 60}]},
}

# ------------------------------------------------------------------------------------------------ scene / catalog
TO_SUN_CAM = (-0.55, 0.55, 0.62)   # hand-set: the left cliff's and the lighthouse's lit faces look left and toward the camera
# positions.json keys Cove's 43 layers by DEF name (tbcv*); building_layer_map.json maps the OE SIDs onto them. Five are
# flagged hidden (tbcvsa1p, tbcvsa2p, tbcvas1p, tbcvas2p, tbcvboat): of those only tbcvsa2p is
# reachable (Build_Resource_Depot_level_2, the Pub horde upgrade) and is staged like any reachable layer; it is not in a
# state below. tbcvwhtr (animatedWater, the lagoon's ripple overlay), tbcvgrot, tbcvhal4 and tbcvpgr3 are not reachable.
STATES = {
    "start": ["tbcvhall", "tbcvtave", "tbcvnmp1"],
    "full": ["tbcvhal3", "tbcvcas3", "tbcvgmg4", "tbcvtave", "tbcvmark", "tbcvsmrk", "tbcvsmth", "tbcvthgd", "tbcvdock",
             "tbcvgral", "tbcvnmp2", "tbcvsay2", "tbcvpir2", "tbcvass2", "tbcvsor2", "tbcvnix2", "tbcvwhr2"],
    "anim": ["tbcvhall", "tbcvtave", "tbcvgral"],
}
WATER_USE = ("the painted lagoon (inside the painting; it is the town's floor and meets the rect's bottom and right "
             "edges; its animated ripple overlay tbcvwhtr is not a reachable layer)")

# ------------------------------------------------------------------------------------------------ sky
# Sunset sky under purple-grey cloud. Colour cannot split it from the land: the lit cliff reads L* 0-76 a* -2..+30
# b* -5..+42, the snow-lit mountain L* 68-83 a* 7-16 b* 18-36, and the sky spans L* 17-84 a* -1..+53 b* -9..+52 (CIELAB
# p5..p95 over hand-set boxes, native px; town_all/cove probe). The lane's DA V2 Large disparity does: every sky box
# reads 0.00 at p5..p95 (the grey cloud top left, the upper sky, the orange glow, the pale sunset), the mountain 1.9-8.8
# (p50), its dark right flank 18, the cliff 37-44, the palms 17. So the lab rule takes no colour box and only
# da_large < 0.5 (hand-set threshold; 1.0 gives 265641 px against 264755, the difference being haze at the mountain's
# foot), connected to the top edge, rows < horizon + 4 (sky_b.png: the top-left cloud is in, the cliff, the palms and
# the mountain are out). The fill's own sky (seed 23): L* > 8 connected to the canvas top, capped at frame row 310
# (the right sunset band reaches row ~300). Sky the rule misses is graded as terrain, and that is the worse failure:
# with L* > 22 (and > 12) the dark blue cloud beside the right seam (integrated canvas x 2045-2240, rows 0-130: L* p5
# 12.0 / p50 20.5, b* -8) was histogram-matched to the cliff and turned into a black rock blob (town_all/cove/
# blob_steps.png). L* > 8 also takes the fill's darker left hills (L* p50 14.5) and palms, which then keep their
# integrated fill colour ungraded (harmless, as Castle's snow peaks; town_all/cove/masks_probe.png).
# stdMax (cv_v2_edge): the fill's far mountains, palms and the ridge beside the right edge share the sky's L* > 8, so
# the old rule handed them to the dome (the panorama drew over them down to row 310). The sky is smooth and they are
# not: local L* std over 11 px < 2.5 keeps the sky and gives them back to the terrain (town_all/cove/skystd_all.png;
# 1.5 also cut the smooth sunset glow at the horizon, 4.0 took the hazy far ridge back into the sky).
SKY_MASK = {"rule": "lab", "reason": "sunset sky; colour overlaps the lit cliff and the mountain, disparity splits them",
            "daMax": 0.5, "extension": {"lMin": 8.0, "maxRow": 310, "stdMax": 2.5, "stdWin": 11}}
SKY_ANIM = {"mode": "deferred", "reason": "the periodic 360 deg sky band is being rebuilt in the parent's change; "
            "drift follows it"}
# the static dome's periodic 360 deg panorama outside the painted sky (town_full3d_sky kit, then town_full3d_sdfill.py --step sky):
# the mirror dome streaked right of the painted rect under the sweeps
SKY_PANO = {"key": "p1_s11", "seed": 11,
            "prompt": "hand-painted fantasy game background sky, 1990s painted matte art, tropical sunset sky, warm orange and rose clouds low, deep violet-blue sky above with faint stars, sky and clouds only",
            "negative": "sun disc, moon, midday, grey overcast, photo, photorealistic, land, ground, hills, mountains, trees, water, building, tower, person, bird, horizon line, text, watermark, frame, border, seam, lowres"}
# the panorama's tone matched to the painted sky at the rect's edges (town_full3d_sky.composite; sky only): the
# SKY_PANO dome beside the right edge carries a dark cloud band and an orange glow the painted violet-rose sky does not
# (cv_v2_edge pass 1, town_all/cove/p1_right.png). Hand-set: low-pass sigma 2 deg, fade radius 10 deg.
SKY_EDGE_MATCH = {"sigmaDeg": 2.0, "radiusDeg": 10.0}
# the canvas's own sky beside the right edge on the dome, faded into the panorama (town_full3d_sky._edge_join, method
# canvas): without it the SKY_PANO dome's dark cloud band meets the painted rose sky in a vertical step (rest-preview
# seam-line x = TW ratio 9-17 over rows 0-120, fx_v1). The mirror has no source there: the Grail's moon statue and the
# lighthouse cover the painted sky beside the edge (rows ~60-230), and the bridge (TEX["bridge"], writeSky) has
# continued the painted sky into the canvas. fadePx hand-set.
SKY_EDGE_JOIN = {"method": "canvas", "edges": ["right"], "fadePx": 240, "rectFeather": False, "topFeather": False,
                 "canvasSkyOnly": False,
                 # cv_v3: without topFadePx the directions above the rect's top carried the painting clamped at its
                 # top row (cv_v2_edge cursor poses: a dark streaked band over rows 0-45 ending in a vertical line)
                 "topFadePx": 32,
                 "reason": "the panorama beside the painted rect does not continue the painted sunset clouds"}
# every layers/anims/metadata.json id (24, incl. tbcvwhtr / tbcvgrot / tbcvsa1p / tbcvsa2p / tbcvhal4 / tbcvpgr3) is a
# positions.json layer id (checked 2026-09-28): no crosswalk.
ANIM_CROSSWALK = {}

# ------------------------------------------------------------------------------------------------ framing
# measured (town_full3d_framing.py measure, sdgrade_pilot stage, 2026-09-28; framing/cove.json, cove_fine.json): zoom
# 1.18 is the largest at which every building's body bounds stay inside the visible (non-HUD) region at the rest view
# with the building-centred aim (1.19 pushes the Grail's full-width star sky tbcvgral over the frame edges and the
# marketplace tbcvmark under the hero panel, where no pose reaches it). The visible viewport goes from 66% painting to
# 91% at rest. panScale 0.5 as Stronghold and Castle: every pan pose >= 76% painting (62-66% before).
# 2026-09-29: 1.17. drop_fringe (the mask no longer shaves each sprite's top / left px) gave tbcvgral back its top
# row; with the building-centred aim the union of tbcvgral (top) and tbcvmark (bottom) then spans 0.0300-0.7621 at
# 1.18, over HUD_TOP by rounding, so the stage's framing gate refused cv_v7. 1.17: tbcvgral top 0.0331, tbcvmark
# bottom 0.7590, every building inside.
FRAMING = {"zoom": 1.17, "aim": "buildings", "panScale": 0.5,
           "reason": "the painting fills the visible region between the HUD panels; the extension seams leave the view"}

# ------------------------------------------------------------------------------------------------ texture (sdgrade)
TEX = {
    "styleCropNative": (0, 30, 800, 300),   # hand-set: the cliff, the sunset, the mountain and the lagoon
    "sd": {"prompt": ("a matte painting of a tropical pirate lagoon at dusk, dark weathered basalt cliffs with palm "
                      "trees, calm dark lagoon water reflecting a red-orange sunset, reed tufts and grey boulders at the "
                      "shore, mossy rocks with yellow lichen and green agave leaves in the foreground, a hazy pale "
                      "mountain on the horizon, dramatic orange sunset sky under dark purple clouds, painterly, detailed"),
           "negative": ("building, house, hut, tower, lighthouse, castle, wall, fence, ship, boat, shipwreck, pier, "
                        "dock, person, animal, road, snow, desert, sand dunes, green meadow, daylight blue sky, text, "
                        "watermark, signature, frame, border, blurry, lowres, jpeg artifacts, photo"),
           "promptKey": "p1", "seed": 23, "context": "full"},
    # seeds 11 / 23 / 37 viewed (town_all/cove/sdfill_seeds.png): 11 continues the cliff and agaves well on the left but
    # paves the right extension with pale flat stone slabs; 37 fills both sides with a pale pebble beach / stone flat;
    # 23 keeps open lagoon water with lichen boulders and reeds on both sides and a far range on the right. seed 23.
    # Its left fill floats a dark agave and its reflection on open water (job_B_left fill px ~490-650 x 720-925,
    # town_all/cove/s23_left_bottom.png), and its right fill grows a dark rock blob out of the painting's speckled top
    # right corner into the sky (job_A_right fill px ~700-790 x 20-115, town_all/cove/seam_right_sky.png): both
    # re-inpainted.
    "clean": ["job_B_left:440,690,700,1024@7", "job_A_right:680,0,1010,400@7"],
    "integrate": {"esrgan": True, "grain": True,
                  "paintFloor": (990, 545, 1150, 610),   # open lagoon water (HoMM3 x 550-639, y 303-339), clear of rocks
                  "floorRamp": (380, 470)},
    "grade": {"floorRows": (545, 610), "cliffRows": 380, "floorzRows": 440, "extOnlyBands": True},
    # Looked at (grid.png, full.png): every house is a building layer. The painted props are palms (foliage on the
    # cliff, the central outcrop and the right shore), one shipwreck on the right shore (not repeated), reed tufts, lagoon
    # boulders, and lichen rocks with agave leaves along the bottom edge. The fill is meant to continue the bottom-edge
    # rocks and agaves below the rect and the reeds and boulders beside it (context 'full'), so none of them is masked.
    "propMask": {"rule": "none", "reason": "no painted houses: every house in the Cove screen is a building layer; the "
                 "painted palms, reeds, boulders, agaves and the single shipwreck are landscape the fill continues"},
    # writeExtBuildingMask / edgeSource 'paintedAll' (as Dungeon): the building mask reaches the right edge at rows
    # ~170-180, 290-350 and 420-450 (the lighthouse shore and the nix pool, cut back by EDGE_FRAY), so the default side
    # edge blend skipped those rows and the bridge's lit shore met the dark painted pool (L* step ~15 at rows 420-450).
    # sideEdgeSky: the bridged sky's tone step at rows 20-40 (seam-line ratio 5-8). rightMirrorPx: the low-pass edge
    # blend cannot follow the peak's red rim (rows 238-250) or the plume's lit edge (rows 160-180); pass-1 rest preview
    # x = TW p90 3.71 -> 1.16 at 24 px, 1.28 at 12 px (kept: half the width of the mirrored chevron on the striped slope,
    # town_all/cove/p1_right12.png)
    "blend": {"toneRows": (330, 420), "writeExtBuildingMask": True, "edgeSource": "paintedAll", "sideEdgeSky": True,
              "rightMirrorPx": 12},
    # right-edge bridge (town_full3d_sdfill --step bridge, between grade and blend): the painted mountain's slope, the
    # sunset sky and the lagoon shore continued into a band of the extension (fx_v1 rest seam-line x = TW p90 16.5 /
    # run 378: the painted rose mountain (rows ~180-340 at the edge) meets the fill's dark sky and the panorama).
    "bridge": {"prompt": ("a matte painting of a tropical lagoon at sunset, the pale rose slope of a hazy mountain "
                          "descending to the right, warm orange and rose sunset glow low in a violet sky, calm dark "
                          "lagoon water, reed tufts and grey boulders on the shore, painterly, detailed"),
               "negative": ("building, house, hut, lighthouse, tower, castle, wall, ship, boat, pier, dock, moon, "
                            "planet, star, smoke, plume, tornado, waterspout, person, animal, text, watermark, signature, frame, border, seam, vertical "
                            "line, blurry, lowres, jpeg artifacts, photo"),
               # seed 51 of 51 / 23 / 101 / 77 (town_all/cove/bridge_p1_seeds.png): the only one that carries the painted
               # slope down to the right; 23 draws a second peak, 101 and 77 a green bush and a dark knoll at the edge
               "seed": 51, "bandPx": 192, "fadePx": 96, "rowsBelowPx": 48, "contextPx": 560, "strength": 0.75,
               # the painted mountain meets the fill's sky at x = TW: its slope can only continue into that sky
               "writeSky": True,
               "writeExtBuildingMask": True,
               # the Grail's moon and the nix pool at the edge: the SD input sees them filled from around them, so the
               # band does not continue a cut building
               "rectContext": "buildingsInpainted", "stripPx": 48, "stripRows": (0, 460)},
    "renderRefPass": True,
}

# ------------------------------------------------------------------------------------------------ terrain
# Horizon: the floor is the lagoon, one level water plane, and its far shore line is painted at HoMM3 y ~212, so the
# horizon lies above that. Measured (town_all/cove/measure_horizon.py and ../fortress/measure_horizon_da.py over the
# floor polygon, per-row medians, Tukey IRLS in the row): DA V2 Large disparity taken as inverse depth vanishes at
# y 184.7-187.6 (row starts 230-270; 193.7 from 290), DA V2 Base 189.8-195.0, Depth Pro inverse depth 154.6-173.0 (it
# reads the lagoon as rising toward the cliff foot). Taken 188 (hand-set inside the DA range, below the far shore).
HORIZON_HOMM3_Y = 188.0
# Scale: no painted hut exists (every house is a layer). Measured at horizon 188 (town_all/tower/hut_units.py): the
# ground-floor doors of the tavern (tbcvtave, x 72-80, y 322-342) and the blacksmith (tbcvsmth, x 752-762, y 318-342),
# 20 and 24 px on the deck at base y 342, are 0.555 and 0.665 camera units; their mean 22 px = 0.61. The lane's metric
# constants (sky dome 415 m, FAR_CAP_M) must stay inside the runtime far clip (120 units): a 2.0 m door (Fortress's
# anchor) gives 0.305 units / m and a 126.6-unit dome (sdgrade_pilot first stage), so the door is hand-set 2.16 m,
# which is Stronghold's 0.282 units / m (dome 117 units).
HUT_WALL_UNITS, HUT_EAVE_M = 0.61, 2.16
FAR_CAP_M = 400.0
# The right wall's far part scaled per azimuth onto the fill's own skyline (stronghold_full3d_terrain.fit_ext_skyline;
# cv_v2_edge): with the extension sky rule's stdMax the fill's far mountains, palms and the bridged slope of the painted
# mountain are terrain, and without the fit the wall stays at lagoon height, so the dome drew over them.
EXT_SKYLINE = {"rhoMinM": 20.0, "rhoFullM": 60.0, "kMin": 0.05, "kMax": 12.0, "fadeDeg": 0.05, "maxBinsAtKMax": 4,
               "edgeRampPx": 64}
# Hand-traced floor polygon (HoMM3 px): the lagoon and its shores below the left cliff's foot, the central outcrop's
# foot and the far shore line (grid.png).
FLOOR_POLY_HOMM3 = [(0, 246), (60, 240), (120, 233), (200, 228), (270, 226), (340, 226), (400, 232), (440, 224),
                    (480, 214), (560, 212), (640, 213), (720, 213), (800, 214), (800, 374), (0, 374)]
SPUR_SCALE, SPUR_AMP = 10.0, 0.6   # hand-set: steep weathered basalt spurs (between Tower's gorge and Castle's hills)
WALL_SHIFT_M = 50.0                # hand-set: the cliff and the far range close round the lagoon

# ------------------------------------------------------------------------------------------------ ground
# (vanilla texture, metres per tile) - hand-set. Viewed (town_all/cove/vanilla_tex.png): Sand / sand1 tile (fine and
# rippled sand: the lagoon's ripples and the pale shore), 512_4_dirt_rock2_diffuse tiles as dark stony ground;
# cliff_texture_b / cliff_texture_new are vertical cliff strips, green_rock_* / autumn_* are mesh UV atlases (not
# tileable); 512_14_grass_tropical_lawn_diffuse is a bright jungle lawn with flowers the painting does not have.
FLOOR_TEX = (("Sand", 4.0), ("sand1", 5.0), ("512_4_dirt_rock2_diffuse", 6.5))
ROCK_TEX = (("512_4_dirt_rock2_diffuse", 9.0), ("cliff_texture_b", 12.0), ("512_3_dirt_rock1_diffuse", 7.0))
ROCK_ROT = {}
DETAIL_CONTRAST = 2.0
ROCK_CONTRAST = 3.0
FLOOR_STONES = (("256_4_desert_stones_diffuse_v2", 2.2), ("512_4_dirt_rock2_diffuse", 3.0))
STRATA_COLS = {"left": (0, 300), "right": (1150, 1440)}
CONTRAST_REGIONS = {"floor": ((990, 545, 1150, 610), (100, 720, 1800, 1000)),
                    "rightWall": ((1150, 250, 1430, 370), (1480, 250, 1900, 420))}

# ------------------------------------------------------------------------------------------------ periphery
ROCK_MESHES = {"Green_Rock_1x1": "green_rock_small_diffuse", "Green_Rock_2x2": "green_rock_big_diffuse"}
SCRUB_MESH, SCRUB_TEX = None, None
PERIPHERY_SCATTER = {
    "scrub": {"required": False, "reason": ("no scrub: the painted shores carry palms, reeds and agaves, and the vanilla "
                                            "Palm1-5 / tropical props are alpha-card foliage the lane bakes as opaque "
                                            "RGB (Castle's black-blot finding)")},
    "rock": {"required": True, "prefixes": ["Mesh_Outer_boulders_"]},
    "nearDensity": {"source": "profile", "perM2": 0.0028,
                    "reason": "the floor is water: the olive-blob count has no dry ground to count on; Stronghold's "
                              "measured density"}}
ROCK_SIZE_M = (1.0, 3.5)
SCRUB_SIZE_M = (1.2, 2.6)
SCRUB_ROW0 = 400
PERIPHERY_VANILLA_NOTE = ("vanilla coastal towns ring the camera with rocky shore and sea; the Cove outer world "
                          "continues the painted cliff, far range and lagoon as the fill's texture")
PERIPHERY_WATER = {"required": False, "reason": (
    "the painted lagoon is the town's floor and meets the rect's bottom and right edges; the lane builds outer water "
    "only for Conflux (Fx_WaterOuter with two continued rivers), which has no lagoon form, so the continuation beyond "
    "the rect is the SD fill's water texture on the floor plane. Open item: an owned outer lagoon surface")}

# ------------------------------------------------------------------------------------------------ near field
NEAR_ROCKS = ("Green_Rock_1x1", "Green_Rock_2x2")
PEBBLE = "Green_Rock_1x1"

# ------------------------------------------------------------------------------------------------ vanilla filler
VANILLA_TEXTURES = {
    "Sand": 256, "sand1": 512, "512_4_dirt_rock2_diffuse": 512, "512_3_dirt_rock1_diffuse": 512,
    "cliff_texture_b": 512, "256_4_desert_stones_diffuse_v2": 256,
    "green_rock_big_diffuse": 512, "green_rock_small_diffuse": 512,
}
VANILLA_VFX = {
    "WaterNormal": 1024, "TileNoise_07_vfx": 256, "TileNoise_23_vfx": 512, "TileNoise_19_vfx": 512,
    "glow_08_vfx": 256, "glow_10_vfx": 512, "glow_18_vfx": 64, "smoke_06_vfx": 256,
}
VANILLA_MESHES = ("Green_Rock_1x1", "Green_Rock_2x2")

# ------------------------------------------------------------------------------------------------ buildings
RELIEF_TUNE = {}
PARTS_LAYERS = set()        # no part separation until a review earns it (Stronghold's bar)
BACK_FILL_LAYERS = None     # every layer takes the edge-filled back (evaluation)
SOLID_TUNE = {}

# ------------------------------------------------------------------------------------------------ edge fray
# Layers cut by the painting's right frame edge, given a ragged geometric edge (stronghold_full3d_buildings.edge_fray;
# frame px, geometry only). Measured on fx_v1 at rest (town_all/dungeon/edge_layers.py cove): the nix pool tbcvnix1 /
# tbcvnix2 (rows 287-448) and the Grail's star sky tbcvgral (rows 166-179) end in a straight line at x = TW
# (rest-preview seam-line ratio 11-26 over rows 240-360).
EDGE_FRAY = {lid: {"minPx": 8, "maxPx": 40, "sigmaPx": 6} for lid in ("tbcvnix1", "tbcvnix2", "tbcvgral")}
