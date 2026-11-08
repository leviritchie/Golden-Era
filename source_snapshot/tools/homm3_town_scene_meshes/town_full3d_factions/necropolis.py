"""Necropolis profile of the full-3D town lane (docs/homm3_stronghold_full_3d_town.md). A dead grey-brown wasteland
under a dark overcast night sky: a flat cracked-mud floor, a low jagged rock ridge across the middle, a tall craggy cliff
closing the right edge, a rock outcrop at the left edge and dark purple-brown mountains through the middle. The painting
itself carries no props: every tomb, tree and house is a building layer (the graveyard is tbncext2). Measured values
say where they come from; hand-set values say so. Proof tier: staged candidate only (no bundle, no install).
"""
from __future__ import annotations

# ------------------------------------------------------------------------------------------------ identity
FRACTION = "homm3_necropolis"
BACKGROUND = "Necropolis-in-background.png"
DATA_DIR = "homm3_necropolis_full3d"
BUNDLE = "homm3_town_scene3d_necropolis"
PREFIX = "homm3_necropolis3d_"
ASSET_ROOT = "Assets/Homm3TownScene3d/necropolis"
LABEL = "Necropolis"
FX_MODULE = "town_full3d_fx"   # the shared profile-classified effects module (FX_LAYERS below)

# Animated reachable layers (layers/anims/metadata.json frames > 1), classified from the DEF's changed-pixel mask
# (town_all/fx_probe/necropolis_changed.png, 2026-09-28). Place, extent, colour and timing are measured by
# town_full3d_fx from the DEF itself.
FX_LAYERS = {
    "tbncblak": {"moves": "the forge's red-hot outlines pulse (red px, hue 357, along the frame and chains)",
                 "effects": [{"kind": "glow"}]},
    "tbncdock": {"moves": "the black water at the dock twinkles (small dark ripple px, 22 changed)",
                 "effects": [{"kind": "glints", "minPx": 2}]},
    "tbncholy": {"moves": "the gem atop the obelisk flares (pale yellow px)",
                 "effects": [{"kind": "glow"}]},
    "tbncspec": {"moves": "the storm cloud over the tower billows (grey px over the whole cloud, 20 frames)",
                 "effects": [{"kind": "smoke"}]},
}

# ------------------------------------------------------------------------------------------------ scene / catalog
TO_SUN_CAM = (-0.55, 0.55, 0.62)   # hand-set: the ridge's and the right cliff's lit faces look left and toward the camera
# positions.json keys Necropolis's layers by DEF name (tbnc*); building_layer_map.json maps the OE SIDs onto them.
# Only the layers building_layer_map.json nativeLevels reaches are built (stronghold_full3d_common.reachable_layers):
# the graveyard (tbncext2, extraAnimation), the other extras (tbncext0/1/3/4/5), tbnchall_4, tbncmage_5 and the third
# upgrades (tbncdw_*_3) have no native level in the refs map, so no prefab (and no state lists them).
STATES = {
    "start": ["tbnchall", "tbnctvrn", "tbncdw_0"],
    "full": ["tbnchall_3", "tbnccstl_3", "tbncmage_4", "tbnctvrn", "tbncmark", "tbncsilo", "tbncblak", "tbncspec",
             "tbncdock", "tbncholy", "tbnchrd2", "tbncdw_0_2", "tbncdw_1_2", "tbncdw_2_2", "tbncdw_3_2", "tbncdw_4_2",
             "tbncdw_5_2", "tbncdw_6_2"],
    "anim": ["tbncspec", "tbncblak", "tbncholy"],
}
WATER_USE = ("the shipyard sprite's own dark water at the bottom right (tbncdock, a building layer); the painting has "
             "no water")

# ------------------------------------------------------------------------------------------------ sky
# Dark overcast night sky (CIELAB measured boxes, native px: L* 10-28, a* -2..+1, b* -7..-2). Colour cannot split it
# from the far mountains (peak L* 1-19 b* -9..-1, left range L* 13-28 b* -10..+1, the pale range through the gap L*
# 10-27 b* -7..+7). The lane's own Depth Anything V2 Large disparity does, as Tower's: every sky box reads 0.00
# (p5..p95), the far ranges 3-12 median, the right cliff 145-167. So a wide CIELAB box (hand-set around the measured
# sky) AND da_large < 0.5 (Tower's threshold; 0.5 and 2.0 give 257357 / 260640 px). Viewed:
# town_all/necropolis/skymask_da0.5.png (the whole cloud deck down to the mountains' skyline, nothing of the cliff or
# the ranges). The fill's own sky: the same box without disparity, capped at frame row 220 (hand-set, above the fill's
# ridge and cliff feet).
SKY_MASK = {"rule": "lab", "reason": "dark overcast night sky over dark far ranges; the ranges are cut by disparity",
            "lMin": 3.0, "lMax": 45.0, "aMin": -4.0, "aMax": 4.0, "bMin": -12.0, "bMax": 1.0, "daMax": 0.5,
            "extension": {"lMin": 3.0, "lMax": 100.0, "aMin": -4.0, "aMax": 4.0, "bMax": 1.0, "maxRow": 220}}
SKY_ANIM = {"mode": "deferred", "reason": "the periodic 360 deg sky band is being rebuilt in the parent's change; "
            "drift follows it"}
# the static dome's periodic 360 deg panorama outside the painted sky (town_full3d_sky kit, then town_full3d_sdfill.py --step sky):
# the mirror dome streaked right of the painted rect under the sweeps
SKY_PANO = {"key": "p1_s11", "seed": 11,
            "prompt": "hand-painted fantasy game background sky, 1990s painted matte art, gloomy dark overcast sky, heavy brooding grey-brown storm clouds, dim cold light, sky and clouds only",
            "negative": "blue sky, sun, bright, sunset colours, photo, photorealistic, land, ground, hills, mountains, trees, water, building, tower, person, bird, horizon line, text, watermark, frame, border, seam, lowres"}
# every layers/anims/metadata.json id (tbncdock, tbncblak, tbncspec, tbncboat, tbncext0, tbncholy) is a positions.json
# layer id
# the painted sky continued across the rect's side edges onto the panorama (town_full3d_sky SKY_EDGE_JOIN): without it
# the dome is pure panorama right of x = TW and the painted clouds end in a vertical step (seam-line gate, fx_v1 rest)
SKY_EDGE_JOIN = {"method": "mirror", "edges": ["right", "left"], "fadePx": 360.0,
                 "reason": "the panorama beside the painted rect does not continue the painted clouds"}
ANIM_CROSSWALK = {}

# ------------------------------------------------------------------------------------------------ framing
# measured (town_full3d_framing.py measure, sdgrade_pilot stage, 2026-09-28; town_all/framing/necropolis*.json): zoom
# 1.21 is the largest at which every building's body bounds stay inside the visible (non-HUD) region at the rest view
# with the building-centred aim (1.22 pushes the shipyard tbncdock and the Lvl3 dwelling tbncdw_2 / tbncdw_2_2 out, and
# they are then reachable from no pose). The visible viewport goes from 66% painting to 95% at rest. panScale 0.5 as
# Stronghold / Castle: every pan pose >= 81% painting (62-74% before).
FRAMING = {"zoom": 1.21, "aim": "buildings", "panScale": 0.5,
           "reason": "the painting fills the visible region between the HUD panels; the extension seams leave the view"}

# ------------------------------------------------------------------------------------------------ texture (sdgrade)
TEX = {
    "styleCropNative": (120, 20, 660, 300),   # the castle, mage guild, obelisk and hall over the ridge (hand-set)
    # context full: the painting has no painted props to keep out of the model's view (propMask rule none)
    "sd": {"prompt": ("a matte painting of a desolate dead wasteland at night, a flat dry cracked grey-brown mud floor "
                      "with small scattered stones, low jagged grey rock ridges, a tall craggy grey rock cliff, distant "
                      "dark purple-brown mountains, dark overcast sky with heavy grey storm clouds, dim cold light, "
                      "painterly, detailed"),
           "negative": ("building, house, ruin, tomb, gravestone, cross, castle, tower, wall, fence, person, animal, "
                        "skeleton, skull, road, path, river, water, lake, grass, green, tree, bush, moon, sun, blue sky, "
                        "bright, sunset, snow, text, watermark, signature, frame, border, blurry, lowres, jpeg "
                        "artifacts, photo"),
           "promptKey": "p1", "seed": 11, "context": "full"},
    "clean": ["job_A_right:690,0,880,300@7"],
    "integrate": {"esrgan": True, "grain": True,
                  "paintFloor": (100, 580, 1340, 665),   # bare cracked floor (the graveyard is a layer over it)
                  "floorRamp": (380, 460)},              # grain weight 0 above (ridge, cliff, sky), 1 below (floor)
    "grade": {"floorRows": (600, 665), "cliffRows": 370, "floorzRows": 440, "extOnlyBands": True},
    "propMask": {"rule": "none", "reason": "the painting is bare cracked mud, ridges, cliff and sky: every tomb, tree "
                 "and house is a building layer (tbncext2 is the graveyard)"},
    "blend": {"toneRows": (360, 440),
              # the bridge repaints the fill's sky (writeSky), so the blend takes the extension sky from its own input
              # (masks.npy is the pre-bridge grade's: x 1440-1520 was the fill's streaked rock there)
              "skyFromSource": True,
              # the rows whose edge column is the cliff mansion (tbncdw_6) take the side edge blend too (T2's
              # edgeSource 'paintedAll'); plain-ground-only left them unblended beside blended rows, horizontal blocks
              # in the bridged rock (seed 61 canvas rows 110-145 / 260-280). The margin of the building mask past
              # the rect (<= 3 px) is written with the extension; the building mask inside the rect never is.
              "edgeSource": "paintedAll", "writeExtBuildingMask": True,
              # the painted cliff's last 4 columns: its dark edge crease, which the bridge continues (16 px: L* 15
              # beside L* 4.3, seam-line rows 79-149 at 3.6)
              "sideEdgePx": 4},   # the ridge and cliff beside the side edges; faded to 0 on the floor
    # right-edge bridge (town_full3d_sdfill --step bridge, between grade and blend): the painting's cracked ground and rock spires continued into a band of the
    # extension
    "bridge": {"prompt": ("a matte painting of a bleak dead wasteland at dusk, dark grey cracked barren earth, jagged "
                          "grey rock spires, distant dark mountains, gloomy cold light, painterly, detailed"),
               "negative": ("building, house, cottage, hut, tent, tower, castle, wall, fence, roof, person, animal, road, "
                            "text, watermark, signature, frame, border, seam, vertical line, blurry, lowres, "
                            "jpeg artifacts, photo"),
               "seed": 61, "bandPx": 192, "fadePx": 96, "rowsBelowPx": 48, "contextPx": 560, "strength": 0.6,
               "rectContext": None,
               # seed 61 of 5/19/29/37/41/53/61/83/101: without EXT_SKYLINE the terrain wall past the edge keeps the
               # painted edge's profile (up to row ~20 beside tbncdw_6); 61 continues the cliff as rock over that
               # wall, the sky seeds (37, 53) left it a lit sky-textured ghost rock (x1440 4.5), 41 a thin dark one
               # the fill's smoky streaks right of the edge (top rows) are neither sky nor ground; with the sky as
               # context only, the band turned them into white blocks (seed 37), so it repaints the sky there too
               "writeSky": True},
    "renderRefPass": True,
}

# ------------------------------------------------------------------------------------------------ terrain
# Horizon, measured (town_all/necropolis/measure_horizon.py over FLOOR_POLY_HOMM3): DA V2 Large inverse-depth rows
# fit -> HoMM3 y 146.5-157.4 over row starts 196-329 (100% inliers); Depth Pro -> 53.5 falling to 2.4 as the start row
# moves down (its floor is not a plane here: rejected). The floor vanishes behind the ridge (feet y ~205), so the
# painting shows no floor horizon to check by eye. Taken 150 (hand-set inside the DA range).
HORIZON_HOMM3_Y = 150.0
# Scale. Measured at horizon 150 (town_all/tower/hut_units.py): the tavern doorway (tbnctvrn, 29 px, base y 226) is
# 2.29 camera units and a near headstone of the graveyard (tbncext2, 28 px, base y 372) 0.76 units; a hand-set 2.8 m
# doorway gives 0.82 units / m and the headstone 0.93 m (consistent). The lane's metric constants (sky dome 415 m,
# periphery 6-398 m, FAR_CAP_M) are painting metres that must stay inside the runtime far clip (120 units), which bounds
# DEPTH_SCALE near Stronghold's 0.282. So the lane scale is hand-set to Stronghold's (0.62 / 2.2 = 0.282): one painting
# metre here is ~2.9 doorway-scale metres. Only metric sizes (rocks, scrub, near density) inherit this.
HUT_WALL_UNITS, HUT_EAVE_M = 0.62, 2.2
FAR_CAP_M = 400.0
# Hand-traced floor polygon (HoMM3 px): the cracked-mud floor below the ridge, the left outcrop and the right cliff.
FLOOR_POLY_HOMM3 = [(0, 212), (60, 210), (120, 206), (170, 204), (230, 206), (300, 208), (400, 210), (500, 210),
                    (580, 208), (630, 200), (700, 196), (760, 196), (800, 198), (800, 374), (0, 374)]
SPUR_SCALE, SPUR_AMP = 7.0, 0.7   # hand-set: jagged rock ridges, near Stronghold's badlands spurs
WALL_SHIFT_M = 70.0               # hand-set: the ridge and cliff close round the camera

# ------------------------------------------------------------------------------------------------ ground
# (vanilla texture, metres per tile) - hand-set. Viewed (town_all/necropolis/vanilla_probe_sheet.png): dirt_ground1 /
# dirt_ground2 / dirt_ground4 are cracked dry mud as painted; dead_ground3 / dead_ground4 plain dead soil with small
# stones. Not used: dirt_ground3 (green weeds), 512_1_dirt_crack_in_the_ground (a painted flower, as Stronghold
# found), dead_ground1 (bones), dead_grass* (grass). The necro mountain textures are mesh UV atlases; the large one is
# the rock detail, as Tower's mountain atlas.
FLOOR_TEX = (("dirt_ground1", 4.0), ("dirt_ground2", 4.6), ("dead_ground3", 5.0), ("dirt_ground4", 5.5),
             ("dead_ground4", 6.0))
ROCK_TEX = (("1024_2_necro_mountain_large_diffuse", 12.0), ("dirt_ground1", 6.0), ("dead_ground3", 9.0))
ROCK_ROT = {}
DETAIL_CONTRAST = 2.0
ROCK_CONTRAST = 3.0
FLOOR_STONES = (("256_2_dead_stones_texture", 2.2), ("dead_ground4", 3.0))
STRATA_COLS = {"left": (0, 230), "right": (1150, 1440)}
CONTRAST_REGIONS = {"floor": ((200, 470, 1300, 640), (100, 720, 1800, 1000)),
                    "rightWall": ((1150, 40, 1430, 330), (1480, 40, 1900, 400))}

# ------------------------------------------------------------------------------------------------ periphery
# Mesh -> texture measured (town_all/necropolis/probe_rock_uv.py, rock_uv_probe.json): UV-island coverage on the
# texture's non-background texels 0.975 / 0.961 / 1.000 against 0.76-0.80 for every other dead rock texture. The
# Nec_Rock_0x meshes match none of the extracted textures (<= 0.80) and are not used.
ROCK_MESHES = {"Dead_Rock_1x1_01": "dead_rock_1_diffuse", "Dead_Rock_2x2_02": "dead_rock_2_diffuse",
               "Dead_Rock_2x2_04": "Dead_Rock_10_diffuse"}
SCRUB_MESH, SCRUB_TEX = None, None
PERIPHERY_SCATTER = {
    "scrub": {"required": False, "reason": ("no scrub: the painted floor is bare cracked mud (the dead trees are in "
                                            "the graveyard building layer, not the painting)")},
    "rock": {"required": True, "prefixes": ["Mesh_Outer_boulders_"]},
    "nearDensity": {"source": "profile", "perM2": 0.0028,
                    "reason": "the painted floor has no countable scrub or stones; Stronghold's measured density"}}
ROCK_SIZE_M = (1.5, 5.0)   # hand-set, Stronghold's (same camera units: 0.4-1.4, i.e. 0.5-1.7 doorway-scale m)
SCRUB_SIZE_M = (1.2, 2.6)
SCRUB_ROW0 = 400
PERIPHERY_VANILLA_NOTE = ("vanilla dead-land towns ring the camera with dark rock hills and dead soil; the Necropolis "
                          "outer world continues the painted ridge, cliff and cracked floor")
PERIPHERY_WATER = {"required": False, "reason": "the painting has no water; the shipyard's dark water belongs to its "
                   "own building sprite (tbncdock) and a continued water body would be invented"}

# ------------------------------------------------------------------------------------------------ near field
NEAR_ROCKS = ("Dead_Rock_1x1_01", "Dead_Rock_2x2_02", "Dead_Rock_2x2_04")
PEBBLE = "Dead_Rock_1x1_01"

# ------------------------------------------------------------------------------------------------ vanilla filler
VANILLA_TEXTURES = {
    "dirt_ground1": 512, "dirt_ground2": 512, "dirt_ground4": 512, "dead_ground3": 512, "dead_ground4": 512,
    "1024_2_necro_mountain_large_diffuse": 1024, "256_2_dead_stones_texture": 256,
    "dead_rock_1_diffuse": 512, "dead_rock_2_diffuse": 512, "Dead_Rock_10_diffuse": 1024,
}
VANILLA_VFX = {
    "WaterNormal": 1024, "TileNoise_07_vfx": 256, "TileNoise_23_vfx": 512, "TileNoise_19_vfx": 512,
    "glow_08_vfx": 256, "glow_10_vfx": 512, "glow_18_vfx": 64, "smoke_06_vfx": 256,
}
VANILLA_MESHES = ("Dead_Rock_1x1_01", "Dead_Rock_2x2_02", "Dead_Rock_2x2_04")

# ------------------------------------------------------------------------------------------------ buildings
# tbncspec (Cover of Darkness): the storm cloud over the tower is a flat card (stronghold_full3d_buildings.flat_region:
# the DEF's changed pixels, closed 4 / grown 3 native px, plus the dark smoke native_mask dropped as within BG_EQUAL of
# the dark sky - the painting has no cloud there, town_all/necropolis/tbncspec_bg_vs_sprite.png). As relief it floated
# in cracked, side-lit fragments top-left of cursor_right / sweep_high (seam_v1, town_all/necropolis/frag_cursor_right.png)
RELIEF_TUNE = {"tbncspec": {"flat": {"source": "defChanged", "closePx": 4, "growPx": 3}}}
PARTS_LAYERS = set()        # no part separation until a review earns it (Stronghold's bar)
BACK_FILL_LAYERS = None     # every layer takes the edge-filled back (evaluation)
SOLID_TUNE = {}

# Layers cut by the painting's right frame edge, given a ragged geometric edge (stronghold_full3d_buildings.edge_fray;
# frame px): the vampire mansion's cliff and the dock's water slab end in a straight line at x = TW (fx_v1 rest, seam-line rows 45-338 and 500-650)
EDGE_FRAY = {lid: {"minPx": 10, "maxPx": 48, "sigmaPx": 5}
             for lid in ('tbncdw_6', 'tbncdw_6_2', 'tbncdock')}
# the storm cloud (tbncspec) is cut by the painting's top edge: a straight line against the dome sky when a pan pose
# looks above the painting (seam_v1 cursor_right / sweep_high); frayed there (geometry only)
EDGE_FRAY_TOP = {"tbncspec": {"minPx": 2, "maxPx": 16, "sigmaPx": 8}}
# the Lvl3 dwelling is cut by the painting's bottom edge: after the mask / thin rebuild (wall_v2) its straight bottom
# line reads as a seam at y = TH (pan_default run 92 -> 117 cols over x 156-272, limit 100); frayed there like
# Dungeon's / Castle's bottom rows (geometry only; the solid is closed along the cut, solids.cap_cut)
EDGE_FRAY_BOTTOM = {lid: {"minPx": 8, "maxPx": 36, "sigmaPx": 6} for lid in ("tbncdw_2", "tbncdw_2_2")}
