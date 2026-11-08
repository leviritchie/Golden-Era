"""Factory (HotA) profile of the full-3D town lane (docs/homm3_stronghold_full_3d_town.md). A sandstone canyon at noon:
a blue sky with white cumulus, red-orange mesas and a natural arch on the right, a stepped plateau with a dragon skeleton
in the middle, the canyon floor of orange sand with cacti and dry scrub, rows of painted (non-layer) timber cottages on
the floor. Measured values say where they come from; hand-set values say so. Proof tier: staged candidate only (no
bundle, no install).
"""
from __future__ import annotations

import math
from pathlib import Path

# ------------------------------------------------------------------------------------------------ identity
FRACTION = "homm3_factory"
BACKGROUND = "Factory-in-background.png"
DATA_DIR = "homm3_factory_full3d"
BUNDLE = "homm3_town_scene3d_factory"
PREFIX = "homm3_factory3d_"
ASSET_ROOT = "Assets/Homm3TownScene3d/factory"
LABEL = "Factory"
FX_MODULE = "town_full3d_fx"   # the shared profile-classified effects module (FX_LAYERS below)

# The ten reachable animated layers, classified from each DEF's changed-px mask and frame strips
# (town_all/t2b/factory_chg.png, fa_hrd2.png, fa_up3.png, fa_up3_wheel.png, fa_cas3a.png, fa_holy.png, fa_up4.png;
# 2026-09-29). Kinds are hand-set from that look; place, extent, colour, timing and the rotor's hub / radius / sense /
# speed are measured by town_full3d_fx from the DEF frames. The windmill passes fit_spin (every frame step agrees; long-
# baseline track 1.97 deg / frame counter-clockwise). The mechanical parts take the measured town_full3d_mech kinds
# where one redraws the DEF clearly better than the static plate (MECH_GAIN_MAX), and stay static otherwise (no
# stand-in effect; 2026-09-29, t2b/mech_*.py): the right-hand cog of the castle is a wheel (its hub behind the wall)
# and the elevator cage a track. Measured and refused (static): the castle's left cog and its two recessed drums
# (a wheel fit redraws them worse than the plate; a translating tooth texture too), the Upgrade's flywheel (a 6-frame
# crank cycle: its spokes alias, no rigid turn fits), its two connecting rods (a turning track fits 0.90 / 0.92 of
# the plate's error) and the flyball governor above the lamp (a card turning about its vertical axis fits 0.90).
_WINDMILL = {"moves": "the many-bladed windmill rotor turns slowly (counter-clockwise on screen)",
             "effects": [{"kind": "spin", "rects": [[20, 0, 72, 48]]}]}
_STACK = {"moves": "a thick white-grey smoke plume billows up from the tall chimney",
          "effects": [{"kind": "smoke", "minPx": 40}]}
FX_LAYERS = {
    "tbfatvrn": {"moves": "grey smoke rises from the tavern's chimney stack", "effects": [{"kind": "smoke", "minPx": 40}]},
    "tbfacas3": {"moves": "the cogwheels on the castle's towers turn: the right-hand cog, half behind the sloping wall, "
                          "turns clockwise about a hidden hub (a measured wheel); the left cog and the two recessed "
                          "drums fit no measured kind and stay static",
                 "effects": [{"kind": "wheel", "rects": [[140, 24, 176, 66]],
                              "why": "fit_wheel: hub (151.5, 45.1) DEF px behind the wall, -5 deg / frame, 8-fold, "
                                     "redraw 31.4 vs static 41.8"}]},
    "tbfablak": {"moves": "white steam puffs from the blacksmith's stacks", "effects": [{"kind": "smoke", "minPx": 40}]},
    "tbfahrd2": _WINDMILL,
    "tbfaup_2": _WINDMILL,
    "tbfaholy": {"moves": "an elevator cage rides down the lattice tower from the housing, waits at the bottom and "
                          "rides back up into the housing (a measured track; the lattice in front stays in front)",
                 "effects": [{"kind": "track", "rects": [[44, 80, 84, 217]], "reachPx": 110,
                              "why": "fit_track: the cage is off the frames' median; hidden frames (inside the "
                                     "housing) interpolated; redraw 5.1 vs static 7.8"}]},
    "tbfadw_1": _STACK,
    "tbfaup_1": _STACK,
    "tbfaup_3": {"moves": "steam rises from the roof stack; the flywheel, its two crank rods and the flyball governor "
                          "above the lamp move, and fit no measured kind (see above): they stay static",
                 "effects": [{"kind": "smoke", "rects": [[110, 15, 150, 90]], "minPx": 40}]},
    "tbfaup_4": {"moves": "green light pulses behind the round grate", "effects": [{"kind": "glow", "minPx": 20}]},
}
# The committed Factory refs are not native canvas px: positions.json x,y are doubled (reference_x = 1.8 x, Castle's is
# 3.6 x) and 29 of 41 static sprites are painted upscales clamped to 1024 on the long side. Measured normalisation
# (artifacts/claude_takeover_20260927/town_all/factory/sprite_norm/build_native.py, asserted for all 41 layers):
# native x,y = positions x/2,y/2 = the HotA town.json structure x,y; native size = reference_w/h / 3.6 = the DEF canvas;
# native pixels = the HotA DEF frame 0 (content.zip sprites/hota/factory/town/buildings). The village hall's DEF repeats
# the painted hall: mean abs error 3.4/255 against the painting at (0,264), best at zero shift. anims/ frames are
# already native and stay on the committed refs.
LAYER_REFS = Path(__file__).resolve().parents[3] / "artifacts" / "homm3_factory_full3d" / "layers_native"

# ------------------------------------------------------------------------------------------------ scene / catalog
TO_SUN_CAM = (-0.55, 0.55, 0.62)   # hand-set: the mesas' lit faces look left and toward the camera, as Stronghold's
# positions.json keys Factory's layers by DEF name (building_layer_map.json maps the OE SIDs onto them); the horde
# layers (tbfahrd*) share the dwellings' places and are left out of the review states
# tbfaext1..3 are positions.json layers that no OE level reaches (building_layer_map nativeLevels), so they are not in
# the bundle and the full state leaves them out (the first fa_v3 render refused "prefab tbfaext1 not in bundle").
STATES = {
    "start": ["tbfahall", "tbfatvrn", "tbfadw_0"],
    "full": ["tbfahal3", "tbfacas3", "tbfamag4", "tbfatvrn", "tbfamark", "tbfasilo", "tbfablak", "tbfaholy",
             "tbfaspc1", "tbfamrch", "tbfaup_0", "tbfaup_1", "tbfaup_2",
             "tbfaup_3", "tbfaup_4", "tbfaup_5", "tbfaup_6"],
    "anim": ["tbfacas3", "tbfatvrn", "tbfaholy"],
}
WATER_USE = "none: a dry sandstone canyon (no river, lake or basin in the painting)"
ANIM_CROSSWALK = {}   # every layers/anims id is a positions.json layer id

# ------------------------------------------------------------------------------------------------ framing
# measured (town_full3d_framing.py measure, sdgrade_v2 stage, 2026-09-28; town_all/framing/factory*.json): zoom 1.17 is
# the largest at which every building's body bounds stay inside the visible (non-HUD) region at the rest view with the
# building-centred aim (1.18: 2 buildings out at rest, 1 then reachable from no pose). The visible viewport goes from
# 66% painting to 90% at rest. panScale 0.5 as Stronghold / Castle / Dungeon: every pan pose >= 73% painting.
FRAMING = {"zoom": 1.17, "aim": "buildings", "panScale": 0.5,
           "reason": "the painting fills the visible region between the HUD panels; the extension seams leave the view"}

# ------------------------------------------------------------------------------------------------ sky
# Blue sky with white cumulus: sky L* 76-85 b* -16..-8, cloud L* 73-99 b* -20..+3; the sandstone is b* > +14. The CIELAB
# box (b* < 5, L* > 55) takes sky and cloud alike, but also the distant blue-grey mountain silhouettes between the mesas
# (HoMM3 y 100-145, b* -9..-6, L* 76-91). The lane's DA V2 Large disparity separates them: sky and cloud read 0, the
# far mountains 3-5, the far mesas 30 (measured, depth/da_large.npy), so daMax 1.5 keeps the mountains as painting.
# The sky seen through the arch (HoMM3 x 650-690, y 95-130) is not connected to the top edge: painting at the far cap.
SKY_MASK = {"rule": "lab", "reason": "blue sky with white cumulus; the distant blue mountains are excluded by disparity",
            "bMax": 5.0, "lMin": 55.0, "daMax": 1.5,
            "extension": {"bMax": 5.0, "lMin": 45.0, "maxRow": 300}}
# seam pass (fa_v2_edge, Cove's recipe 951e6e7995): the canvas (bridged mesas and sky) carried across the right edge
# onto the dome (town_full3d_sky._edge_join, method canvas; topFadePx: the directions above the rect's top fade to the
# panorama, not the clamped top row). No SKY_EDGE_MATCH (Tower: its low-pass shift tinted the white cumulus peach).
SKY_EDGE_JOIN = {"method": "canvas", "edges": ["right"], "fadePx": 240, "rectFeather": False, "topFeather": False,
                 "canvasSkyOnly": False, "topFadePx": 32,
                 "reason": "the panorama beside the painted rect does not continue the painted cumulus and mesas"}
SKY_ANIM = {"mode": "deferred", "reason": "the periodic 360 deg sky band is being rebuilt in the parent's change; "
            "drift follows it (open cumulus sky over the canyon)"}
SKY_PANO = {"key": "p1_s11", "seed": 11,
            "prompt": "hand-painted fantasy game background sky, 1990s painted matte art, bright clear blue midday desert sky, "
                      "scattered white cumulus clouds, soft light, sky and clouds only",
            "negative": "snow, mountains, land, ground, hills, rocks, desert, trees, water, building, tower, person, bird, "
                        "sunset, storm, dark clouds, horizon line, photo, text, watermark, frame, border, seam, lowres"}

# ------------------------------------------------------------------------------------------------ texture (sdgrade)
TEX = {
    "styleCropNative": (160, 120, 640, 340),
    # p1 ("... scattered saguaro cacti ...", seeds 11 / 23 / 37, kit/sdinpaint_runs/p1_s*_props) painted a pale grey-beige
    # desert and giant blue-green cacti in the foreground (a tall prop on the ground plane stretches on the pans):
    # rejected. p2 drops the cacti, asks for the painting's saturated orange and negates the pale palette; SDXL still paints
    # a pale palette (the grade matches it to the painting). p2 seed 23 (probe/sdfill_seeds_p2.png) painted a white-veined
    # cracked-plate floor on the right that read as crazing on every pan (tex/superseded_p2s23_crackedfloor/). p3 adds
    # the cracks to the negative; seeds 23 / 5 / 41 / 7 (probe/sdfill_seeds_p3.png): 23 grows huge pale slabs on the
    # right, 7 a fog of pale rock, 5 a gorge drop-off across the left floor; 41 continues the right cliff as a red mesa
    # and both floors as plain sand with dry grass tufts: kept.
    "sd": {"prompt": ("a matte painting of a sandstone desert canyon, saturated red-orange eroded mesas and cliffs "
                      "with horizontal strata, a flat vivid orange sand canyon floor with sparse dry yellow grass "
                      "tufts and small red stones, bright midday sunlight from the left, blue sky with white cumulus "
                      "clouds, painterly, detailed"),
           "negative": ("cactus, cacti, cracked ground, cracks, mud crack pattern, building, house, cottage, roof, hut, tent, tower, castle, wall, fence, "
                        "windmill, person, animal, skeleton, bones, dragon, road, river, water, lake, green grass, "
                        "trees, snow, pale, grey, white sand, text, watermark, signature, frame, border, blurry, "
                        "lowres, jpeg artifacts, photo"),
           "promptKey": "p3", "seed": 41, "context": "props"},
    # p3 s41's left job paints the floor below the painted rect as a patchwork of pale blocks and smeared cacti
    # (probe/s41_left.png) and haze over the left mesas: re-inpainted (fill px)
    "clean": ["job_B_left:0,560,1536,1024@5", "job_B_left:0,230,420,560@5"],
    "integrate": {"esrgan": True, "grain": True,
                  # bare sand right of the front cottages (HoMM3 x 472-560, y 316-354), clear of cacti and scrub: the
                  # first box (x 365-560, y 300-350) held a cactus, and the grain quilt stamped it all over the
                  # extension floor (tex/superseded_quilted_cacti/)
                  "paintFloor": (850, 569, 1008, 637),
                  "floorRamp": (430, 500)},               # grain weight 0 above (mesas, sky), 1 below (canyon floor)
    "grade": {"floorRows": (540, 640), "cliffRows": 420, "floorzRows": 480, "extOnlyBands": True},
    # the painted cottages: timber walls and cream roofs share the sand path's and the cliffs' colours (hue_white with
    # darkL swallows the left cliffs, lowchroma_white the pale sand path), and da_bump finds the cacti and misses the
    # middle row (town_all/factory/probe/propmask.png), so they are hand-traced (HoMM3 px, probe/floorL.png, floorR.png).
    "propMask": {"rule": "boxes", "reason": "cottages share the sand's and cliffs' colours; the disparity bump "
                 "misses the middle row", "dilate": 7,
                 "boxes": [(170, 250, 245, 280),    # back-left pair
                           (305, 257, 420, 293),    # middle row
                           (445, 225, 540, 297),    # right cluster with the water tower
                           (158, 305, 362, 374),    # front row
                           (715, 302, 800, 350),    # right pair under the cliff
                           (470, 358, 530, 374),    # bottom-centre roof
                           (600, 358, 672, 374),    # bottom-right roof
                           (0, 265, 172, 345)]},    # the painted village hall (under tbfahall) and the left-edge hut
    "blend": {"toneRows": (440, 540),   # the cliffs beside the side edges; faded to 0 on the floor
              # seam pass (Cove's recipe, 951e6e7995; candidate fa_v2_edge): the edge blend also takes the building
              # mask's margin and every painted pixel at the edge, the sky beside the edges, and a mirrored crossfade
              # over the first columns right of x = TW and rows below y = TH (sdgrade_v2 rest seam-line x = TW p90
              # 6.78 run 179, y = TH p90 4.88 run 220)
              "writeExtBuildingMask": True, "edgeSource": "paintedAll", "sideEdgeSky": True,
              "rightMirrorPx": 12, "bottomMirrorPx": 24,
              # the propMask boxes cover the cottages' whole footprints down to the last rows (cols 280-680, 840-960,
              # 1080-1200), which the bottom edge otherwise leaves unblended
              "bottomSourceHut": True},
    # right-edge bridge (town_full3d_sdfill --step bridge, between grade and blend): the painted mesas, cliffs, sky and
    # canyon floor continued into a band of the extension
    "bridge": {"prompt": ("a matte painting of a sandstone desert canyon, saturated red-orange eroded mesas and cliffs "
                          "with horizontal strata continuing to the right, blue sky with white cumulus clouds, a flat "
                          "vivid orange sand canyon floor with sparse dry yellow grass tufts and small red stones, "
                          "bright midday sunlight from the left, painterly, detailed"),
               "negative": ("cactus, cacti, cracked ground, building, house, cottage, roof, hut, tent, tower, castle, "
                            "wall, fence, windmill, factory, chimney, smoke, person, animal, skeleton, bones, road, "
                            "river, water, green grass, trees, snow, text, watermark, signature, frame, border, seam, "
                            "vertical line, blurry, lowres, jpeg artifacts, photo"),
               "seed": 11, "bandPx": 192, "fadePx": 96, "rowsBelowPx": 48, "contextPx": 560, "strength": 0.75,
               "writeSky": True, "writeExtBuildingMask": True,
               "rectContext": "buildingsInpainted", "stripPx": 48, "stripRows": (0, 673)},
    "renderRefPass": True,
}

# ------------------------------------------------------------------------------------------------ terrain
# measured: Depth Pro inverse depth over the canyon-floor polygon is linear in the row (Tukey IRLS, 100% inliers) and
# reaches 0 at HoMM3 y 142.1 / 147.5 / 148.6 over row starts 260 / 280 / 300 (124.3 from 320: 54 rows only); an
# earlier coarser polygon gave 147.5 / 145.7 / 152.9. Hand-rounded to 146, level with the plateau top.
HORIZON_HOMM3_Y = 146.0
# measured: four painted cottages' walls (eave to base, HoMM3 px) at their depth on this floor plane, in camera units:
# 18 px at base y 290 -> 0.773, 16 px at 294 -> 0.668, 18 px at 348 -> 0.551, 17 px at 338 -> 0.547 (the painter's
# back row is drawn larger than the front row). Median 0.61; one-storey eave hand-set 2.2 m as Stronghold's.
HUT_WALL_UNITS, HUT_EAVE_M = 0.61, 2.2
FAR_CAP_M = 400.0
# Hand-traced canyon floor (HoMM3 px): below the left cliffs, the central mesa's front face and the right cliff.
FLOOR_POLY_HOMM3 = [(0, 285), (40, 280), (100, 275), (150, 262), (175, 256), (300, 262), (400, 258), (450, 245),
                    (560, 240), (600, 245), (630, 262), (650, 305), (700, 318), (760, 308), (800, 300), (800, 374),
                    (0, 374)]
SPUR_SCALE, SPUR_AMP = 6.0, 0.8   # hand-set: blocky eroded mesas, Stronghold's badlands spurs
WALL_SHIFT_M = 90.0               # hand-set: the canyon closes round the camera as a bowl (Stronghold's)

# ------------------------------------------------------------------------------------------------ ground
# (vanilla texture, metres per tile) - hand-set, Stronghold's vanilla desert set (the same biome: orange sand, layered
# sandstone). The Dez_Rock / des_rock textures are mesh UV atlases, not tiling detail.
FLOOR_TEX = (("sand3", 3.6), ("sand1", 4.2), ("dirt_ground4", 5.0), ("dirt_ground1", 4.4), ("sand2", 6.5))
ROCK_TEX = (("Cliff_01_diffuse", 12.0), ("dirt_ground1", 6.0), ("sand3", 9.0))
ROCK_ROT = {"Cliff_01_diffuse": math.pi / 2}   # its striations run vertically in the texture: turned to strata
DETAIL_CONTRAST = 2.0
ROCK_CONTRAST = 5.0
FLOOR_STONES = (("256_4_desert_stones_diffuse_v2", 2.2), ("512_3_dirt_rock1_diffuse", 3.0))
STRATA_COLS = {"left": (0, 270), "right": (1150, 1440)}   # the left cliffs (HoMM3 x 0-150) and the right cliff and arch
CONTRAST_REGIONS = {"floor": ((850, 569, 1008, 637), (100, 720, 1800, 1000)),
                    "rightWall": ((1150, 150, 1430, 450), (1480, 150, 1900, 600))}

# ------------------------------------------------------------------------------------------------ periphery
ROCK_MESHES = {"Rock_desert_new_01": "1024_1_Dez_Rock_New_01_diffuse",
               "Rock_desert_new_02": "1024_2_Dez_Rock_New_02_diffuse",
               "Rock_desert_new_03": "1024_3_Dez_Rock_New_03_diffuse", "Des_Rock_01": "des_rock_1_diffuse",
               "Des_Rock_02": "des_rock_2_diffuse", "Des_Rock_03": "des_rock_3_diffuse",
               "Des_Rock_04": "des_rock_4_diffuse"}
# No scrub: the painted floor's tufts are dry yellow grass, not olive (the periphery's olive scrub palette found 52
# pixels, < 200, in the sdgrade_pilot stage), and the cacti have no opaque vanilla mesh (the lane bakes opaque RGB).
SCRUB_MESH, SCRUB_TEX = None, None
PERIPHERY_SCATTER = {
    "scrub": {"required": False, "reason": ("no scrub: the painted tufts are dry yellow grass (52 olive px) and the "
                                            "cacti have no opaque vanilla mesh")},
    "rock": {"required": True, "prefixes": ["Mesh_Outer_boulders_"]},
    "nearDensity": {"source": "profile", "perM2": 0.0028,
                    "reason": "the olive-blob count has no olive scrub to read on this sand floor; Stronghold's "
                              "measured density"}}
ROCK_SIZE_M = (1.5, 5.0)
SCRUB_SIZE_M = (1.2, 2.6)
SCRUB_ROW0 = 450          # rect rows below which olive pixels are floor scrub (the canyon floor starts ~HoMM3 y 250)
PERIPHERY_VANILLA_NOTE = ("vanilla desert terrain is sand, dunes and layered rock; the Factory outer world continues "
                          "the painted canyon walls and sand floor")
PERIPHERY_WATER = {"required": False, "reason": "the HoMM3 Factory painting has no river or lake (a dry sandstone "
                   "canyon); a continued water body would be invented"}

# ------------------------------------------------------------------------------------------------ near field
NEAR_ROCKS = ("Rock_desert_new_01", "Rock_desert_new_02", "Rock_desert_new_03")
PEBBLE = "Des_Rock_02"

# ------------------------------------------------------------------------------------------------ vanilla filler
VANILLA_TEXTURES = {
    "sand1": 512, "sand2": 512, "sand3": 512, "dirt_ground1": 512, "dirt_ground4": 512,
    "512_3_dirt_rock1_diffuse": 512,
    "1024_1_Dez_Rock_New_01_diffuse": 1024, "1024_2_Dez_Rock_New_02_diffuse": 1024,
    "1024_3_Dez_Rock_New_03_diffuse": 1024, "des_rock_1_diffuse": 1024, "des_rock_2_diffuse": 1024,
    "des_rock_3_diffuse": 1024, "des_rock_4_diffuse": 1024, "Cliff_01_diffuse": 1024,
    "256_4_desert_stones_diffuse_v2": 256,
}
VANILLA_VFX = {
    "WaterNormal": 1024, "TileNoise_07_vfx": 256, "TileNoise_23_vfx": 512, "TileNoise_19_vfx": 512,
    "glow_08_vfx": 256, "glow_10_vfx": 512, "glow_18_vfx": 64, "smoke_06_vfx": 256,
}
VANILLA_MESHES = ("Rock_desert_new_01", "Rock_desert_new_02", "Rock_desert_new_03", "Des_Rock_01", "Des_Rock_02",
                  "Des_Rock_03", "Des_Rock_04")

# ------------------------------------------------------------------------------------------------ buildings
RELIEF_TUNE = {}
# The village hall is painted into the background: tbfahall's DEF repeats the painting within BG_EQUAL (0 mask px, "no
# footing found"), and the upgraded halls share its base pixels. Their own alpha is their mask (PAINTED_LAYERS).
PAINTED_LAYERS = {"tbfahall", "tbfahal2", "tbfahal3", "tbfahal4"}
PARTS_LAYERS = set()        # no part separation until a review earns it (Stronghold's bar)
BACK_FILL_LAYERS = None     # every layer takes the edge-filled back (evaluation)
SOLID_TUNE = {
    "tbfamage": {"n": 2.0}, "tbfamag2": {"n": 2.0}, "tbfamag3": {"n": 2.0}, "tbfamag4": {"n": 2.0},   # round tower
}

# ------------------------------------------------------------------------------------------------ edge fray
# seam pass (fa_v2_edge): the building layers that reach the right edge (x > TW - 40 at rest) and the bottom edge
# (y > TH - 40) end in ragged geometric edges so the bridged / mirrored canvas shows through
# (stronghold_full3d_buildings.edge_fray; geometry only, no texel is recoloured).
EDGE_FRAY = {lid: {"minPx": 8, "maxPx": 40, "sigmaPx": 6}
             for lid in ("tbfadw_0", "tbfadw_5", "tbfatvrn", "tbfaup_0", "tbfaup_5")}
EDGE_FRAY_BOTTOM = {lid: {"minPx": 8, "maxPx": 40, "sigmaPx": 6}
                    for lid in ("tbfadw_3", "tbfamark", "tbfamrch", "tbfasilo", "tbfaspc1", "tbfatvrn", "tbfaup_3")}
