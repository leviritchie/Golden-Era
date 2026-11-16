"""Elemental Fusion stage 2 (h3_fusion_ii_*) mesh-fx rows: each stage-2 unit gets its own themed set of native vanilla
particle effects (battle_skinned vanillaStyle rows through vanilla_style_fx.build_rows on the host mesh's delivery
facts), plus the host element's own rows, an emission row (host parent's body map + the stage-2 crest atlas) and the
fusion overlay (mech_guard VfxUber, theme tint, body + crest masks), exactly the stage-1 row shapes.

    python tools/homm3_vfx/fusion_stage2_fx.py compile --sources V:/.../vanilla_sources_stage2.json --assets DIR --out DIR

--sources: a vanilla_sources.json that also holds the stage-2 prefabs (vanilla_style_fx.py sources with the extra
paths; the shipped tools/homm3_vfx/vanilla_style/vanilla_sources.json does not yet). --assets: the
fusion_stage2_bundles.py build dir (per-unit homm3_mesh_fx PNGs). No two stage-2 units share the same themed set
(checked). Proof tier: generated rows; lab-proven for a few units only, in-game look unproven.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import fusion_fx as FX  # noqa: E402
import vanilla_style_fx as VSF  # noqa: E402

RECIPES = Path("V:/olden_port_work/elemental_fusion/stage2/recipes_preview.json")
PROOF = "generated artifact; in-game look unproven"

P = "units/nature/1prefabs/phoenix"
PH = "scale_roll/phoenix/"
SC = "units/neutral/1prefabs/star_child"
NA = "units/nature/1prefabs/aqualotl_upg"
MX = "magic/prefabs_vfx/"
# key -> (resPath, childPath, keepNodes)
SRC = {
    "P_FIRE": (P, PH + "Root/Hips/Spine/Chest/Shoulder_L/Elbow_L/Wrist_L/WristFeather1_L/Phoenix_upg_ability_fire_01", ["Fire_01", "Fire_02"]),
    "P_SPARKS": (P, PH + "Root/Hips/Spine/Phoenix_ability_rise_spine", ["Fire_sparks"]),
    "P_SMOKE": (P, PH + "Phoenix_ability_smoke_rise_root", ["smoke_dust_01", "smoke_dust_02"]),
    "P_STEAM": (P, PH + "Phoenix_ability_smoke_rise_root", ["smoke"]),
    "VORTEX": (MX + "nature/aqualotl/naiad_alt_ability_vortex_unit", "Transform/Idle_start/Wind_start_small_01", ["", "Wind_01", "Wind_02", "Wind_03", "Wind_04"]),
    "SENT_ENERGY": ("units/neutral/1prefabs/sentinel", "scale_roll/Angel/Root/Hips/SmallWing1_L/SmallWing2_L/SmallWing3_L/SmallWing4_L/Angel_idle_SmallWing4_L", ["Energy_01", "Smoke"]),
    "LS_SMALL": (MX + "magic_lightning_strike_hex", "Transform_lightning/Impact", ["Lightning_sparks_small_01", "Lightning_sparks_small_02", "Lightning_sparks_small_03", "Lightning_trails", "Lightning_sphere"]),
    "LS_TRAIL": (MX + "magic_lightning_strike_hex", "Transform_lightning/Impact", ["Lightning_trails", "Lightning_sparks_small_01", "Lightning_sparks_small_02"]),
    "NAIAD_BALL": (NA, "scale_roll/naiad_upg/Root/Naiad_upg_ability_water_ball_root/Ball", ["Water_01", "Water_01/Water_02", "Water_03", "Water_03/Water_04"]),
    "NAIAD_HIT": (NA, "scale_roll/naiad_upg/Root/Naiad_upg_hit_root/Water_01", ["", "Water_02", "Water_03"]),
    "NAIAD_IDLE": (NA, "scale_roll/naiad_upg/Root/Naiad_upg_idle_root", ["Water_01", "Water_02", "Water_03"]),
    "NAIAD_SPRAY": (NA, "scale_roll/naiad_upg/Root/Naiad_upg_idle_root", ["Sparks_01"]),
    "NAIAD_FLOOD": (NA, "scale_roll/naiad_upg/Root/Naiad_upg_moove_end_root", ["Water_01", "Water_02", "Water_03", "Wave_water_01", "Wave_water_04", "Sparks_01"]),
    "STAR_IDLE": (SC, "scale_roll/star_child/Root/Hips/Spine/Chest/Scapula_L/Shoulder_L/Elbow_L/Hand_L/Star_child_idle_sparks_Hand_L", ["Sparks"]),
    "STAR_BURST": (SC, "scale_roll/star_child/Star_child_teleport_out_Root/Transform", ["Flash_flick", "Sparks_burst_out_01", "Sparks_burst_out_02", "Sparks_burst_out_03", "Sparks_burst_out_04"]),
    "STAR_HIT": (SC, "scale_roll/star_child/Root/Hips/Spine/Chest/Star_child_hit_Chest/Transform", ["Star_fast", "Energy", "Flash_start", "Sparks_idle_in_01", "Sparks_idle_in_02", "Sparks_idle_in_03", "Sparks_in_idle"]),
    "QILIN_ARCS": ("units/nature/1prefabs/qilin_upg", "scale_roll/qilin_upg/Root/Hips/Spine/Qilin_upg_idle_Spine", ["", "Lightning_wave_01", "Lightning_wave_02"]),
    "MECH_HIT": ("units/neutral/1prefabs/mech_guard", "scale_roll/world_watcher/Root/Ring2/World_watcher_hit_Ring2", ["Star_01", "Sparks", "Lightning_01", "Lightning_02", "Lightning_03"]),
    "FROST_HIT": ("units/unfrozen/1prefabs/frostworm_rider_upg", "scale_roll/frostworm_rider_upg/Root/WormSpine1/WormHead/WormBottomJaw/FrostWorm_upg_hit_WormBottomJaw", ["Energy_01", "Snow_smoke"]),
    "FROST_IDLE": ("units/unfrozen/1prefabs/frostworm_rider_upg", "scale_roll/FrostWorm_upg_idle_root", ["Snow_smoke_01"]),
    "ANGEL_IMPACT": ("units/humans/1prefabs/angel_upg", "scale_roll/angel_upg/Root/Angel_upg_impact_spine/Transform", ["FlashLight", "Flash", "Flash_sun_01", "Flash_sun_02", "Sparks", "Energy_up"]),
    "LW_HAND": ("units/humans/1prefabs/lightweaver_upg", "Scale_roll/lightweaver_upg/Root/Hips/Spine/Chest/Scapula_L/Shoulder_L/Elbow_L/Hand_L/Lightweaver_upg_ability_01_Hand_L", ["Energy_up_01", "Energy_up_02"]),
    "LW_BURST": ("units/humans/1prefabs/lightweaver_upg", "Scale_roll/lightweaver_upg/Root/Hips/Spine/Chest/Scapula_L/Shoulder_L/Elbow_L/Hand_L/Lightweaver_upg_ability_01_burst_Hand_L", ["Smoke", "Energy_up"]),
    "UNICORN_HIT": ("units/neutral/1prefabs/unicorn", "scale_roll/Unicorn/Rig_Unocorn/Root/DEF.Spine_1/DEF.Spine_2/DEF.Spine_3/DEF.Neck_1/DEF.Neck_2/DEF.Neck_3/DEF.Neck_4/DEF.head/unicorn_hit_Def_head", ["flame_01", "flame_02", "Flash_01", "Flash_02", "Sparks"]),
    "VAMP_HEART": ("units/undead/1prefabs/vampire_upg_alt", "Scale_roll/vampire_upg_alt/Root/Heart/Vampire_alt_idle_Heart", ["Flash", "Blood"]),
    "PIXIE_POLLEN": ("units/neutral/1prefabs/pixie", "scale_roll/Pixie/Rig_Pixie/Root/DEF.Spine_1/DEF.Spine_2/DEF.Spine_3/DEF.Wing_1.L/DEF.Wing_2.L/Pixie_idle_def.wing_2.L", ["Pollen_01", "Pollen_01/Pollen_01", "Pollen_01/Pollen_02", "Pollen_01/Pollen_03"]),
    "PIXIE_HIT": ("units/neutral/1prefabs/pixie", "scale_roll/Pixie/Rig_Pixie/Root/Pixie_hit_start_root/Ground_pollen", ["Flash_bottom_01", "Smoke_end", "FlashLight_01", "Pollen_wave_01", "Pollen_wave_02"]),
    "LOCUST": ("units/demons/1prefabs/locust_upg", "scale_roll/locust_upg/Armature/Root/Hips/Head/BottomJaw/Locust_upg_hit_BottomJaw", ["Energy_01", "Energy_02", "Flash_dark"]),
    "OLGOI_LAVA": ("units/demons/1prefabs/olgoi_upg", "scale_roll/olgoi_upg/Olgoi_upg_lava_end_root/Transform_ability", ["Lava_sparks_01", "Lava_sparks_02", "Sparks", "FlashLight", "Crack_smoke/Smoke"]),
    "ASSASSIN_SMOKE": ("units/dungeon/1prefabs/assassin_upg", "Scale_roll_pos/assassin_upg/Assassin_upg_ability_smoke_uppear_root", ["Fire_smoke_01", "Smoke", "flash_flick", "Sparks_01"]),
    "LICH_BURST": ("units/undead/1prefabs/lich_upg", "scale_roll/lich_upg/Root/Staff/Lich_upg_burst_Staff", ["FlashLight", "flick", "Energy_wave"]),
    "LICH_ALT": ("units/undead/1prefabs/lich_upg_alt", "scale_roll/lich_upg_alt/Root/Staff/Lich_alt_upg_hit_Staff", ["Flash_red", "Flash_camera_01", "Trails"]),
    "DRAGON_BREATH": ("units/neutral/1prefabs/dragon", "scale_roll/dragon/Root/Hips/Spine/Chest/Neck1/Neck2/Neck3/Head/Dragon_hit_02_Head/Transform", ["Breath_of_fire_01", "Breath_of_fire_02", "Breath_of_fire_03", "Breath_of_fire_04"]),
    "BLACKDRAGON": ("units/dungeon/1prefabs/black_dragon", "scale_roll/black_dragon/Root/Hips/Spine/Chest/Neck1/Neck2/Neck3/Neck4/Head/Black_dragon_hit_02_jaw_fire_Head/Transform", ["sparks", "Fire_spark_01", "Fire_spark_02", "Fire_spark_03", "Fire_spark_04", "Smoke"]),
    "DRUID_CRYSTAL": ("units/nature/1prefabs/druid_upg", "scale_roll/druid_upg/Root/Hips/Spine/Chest/Clavicle_L/Shoulder_L/Elbow_L/Hand_L/Staf/Druid_upg_hit_close_Staf", ["Flick", "Crystal_01", "Crystal_02", "Crystal_03"]),
    "TRICK_SLASH": ("units/demons/1prefabs/trick_demon_upg", "scale_roll/trick_demon_upg/Root/Trick_demon_upg_slash_hit_02_root", ["Transform", "Transform/Slash_01", "Transform/Slash_02"]),
    "FLICKER_HIT": ("units/undead/1prefabs/flicker", "Scale_roll/Flicker_hit_root", ["Transform/Trail_hit_01", "Transform/Trail_hit_02", "Transform/drops"]),
    "EMISSARY_FIRE": (MX + "humans/emissary/emissary_fire_hit_root", "Transform", ["Breath_of_fire_01", "Breath_of_fire_03", "Sparks"]),
    "CAV_SMOKE": (MX + "humans/sunlight_cavalry/cavalry_smoke_root", "Transform", ["smoke_dust_01", "smoke_dust_02"]),
    "FANGS": (MX + "magic_stones_fangs_hex", "Transform_fangs", ["smoke_dust_01", "Wind_smoke_01"]),
    # stage-2 additions (probed into the --sources file)
    "BH_TRAILS": (MX + "magic_black_hole_hex", "Transform_black_hole/Black_hole/Black_hole_trails", ["Nebula_trails_01", "Nebula_trails_02"]),
    "BH_STAR": (MX + "magic_black_hole_hex", "Transform_black_hole/Black_hole", ["Star_horizontal", "Nebula_smoke"]),
    "BH_RAY": (MX + "magic_black_hole_hex", "Transform_black_hole/impact_start/Ray_start_impact", ["Dark_energy_01", "Dark_energy_02", "Dark_energy_03", "Dark_energy_04", "Plane_ray_01"]),
    "BH_BOOM": (MX + "magic_black_hole_hex", "Transform_black_hole/impact_start", ["Sparks_boom_01", "Sparks_boom_02", "Sparks_boom_03", "Sparks_boom_04", "Stretched_sparks_01", "Stretched_sparks_02"]),
    "FLAME_IDLE": (MX + "magic_wall_of_flame_hex", "Transform_flame/Idle_flame", ["Flame_sparks_01", "Flame_sparks_02", "Flame_02", "Light_big_01"]),
    "FLAME_EMBERS": (MX + "magic_wall_of_flame_hex", "Transform_flame/Idle_flame/Sparks_01", ["Sparks_02", "Sparks_03"]),
    "FIREFLY_B": ("objects/fx/fx_fireflies_blue", "Particle System", [""]),
    "FIREFLY_P": ("objects/fx/fx_fireflies_purple", "Particle System", [""]),
    "FAIRY": (MX + "global_map/global_object_fairy_ring_vfx", "FlashPurple_01", [""]),
    "CROWN_SHARDS": (MX + "magic_crystal_crown_hex", "Crystal_Crown_timeline/CrystalCrown_idle/Transform /CrystalFragment_small_01",
                     ["CrystalFragment_small_02", "CrystalFragment_small_03", "CrystalFragment_small_04", "CrystalFragment_small_05", "CrystalFragment_small_06", "CrystalFragment_small_07"]),
    "CROWN_WIND": (MX + "magic_crystal_crown_hex", "Crystal_Crown_timeline/CrystalCrown_idle/Transform ", ["Wind_01", "Wind_02", "sparks_in"]),
    "LW_SUN": (MX + "humans/lightweaver/lightweaver_upg_idle_sun_def.nimb", "Transform", ["Sun_02", "Sun_03", "Flash_wave", "Flash_sun_03"]),
    "LW_RAYS": (MX + "humans/lightweaver/lightweaver_upg_idle_sun_def.nimb", "Transform", ["Energy_up", "Smoke", "Wind_white"]),
    "PARAGON_CRYS": (MX + "humans/paragon/paragon_upg_idle_crystal_spine", "Transform", ["Sun_02", "Sun_03", "Flash_sun_01", "Smoke"]),
    "QILIN_SMOKE": (MX + "nature/qilin/qilin_upg_idle_root", "SmokeEnergy_01", [""]),
    "OPT_RING": (MX + "magic_optical_illusion_unit", "Transform/Start_transform (1)/Cosmo_circle_idle", ["", "Cosmo_circle_01", "Cosmo_circle_02"]),
    "OPT_EYE": (MX + "magic_optical_illusion_unit", "Transform/Start_transform (1)/Eye_cosmo", ["", "Eye_01", "eyelashes_01", "eyelashes_02", "star_01", "star_02"]),
    "OPT_TRI": (MX + "magic_optical_illusion_unit", "Transform/Start_transform (1)/triangle_cosmo", ["", "triangle_cosmo_01", "triangle_cosmo_02"]),
    "CLOCK": (MX + "magic_reality_distortion_hex", "Transform/Cosmo_circle_idle", ["Cosmo_circle_01", "Cosmo_circle_02", "Cosmo_circle_03", "Cosmo_clock_01", "Cosmo_clock_01/Cosmo_clock_02"]),
    "HEAL_WATER": (MX + "magic_healing_water_unit", "Transform_water", ["WaterSparks", "LineWater"]),
    "CHAIN_RING": (MX + "magic_chain_lightning_hex", "Transform_lightning/Impact", ["Lightning_circle_01", "Lightning_circle_02", "Lightning_sphere", "Lightning_sparks"]),
    "METEOR_IDLE": (MX + "magic_meteor_hex", "Transform_meteor/Meteor_move/Meteor", ["SmokeSparks", "Sparks", "Flame_sparks"]),
    "METEOR_TRAIL": (MX + "magic_meteor_hex", "Transform_meteor/Meteor_move", ["fire_trail_01", "fire_trail_02", "fire_conus_01"]),
    "METEOR_STONES": (MX + "magic_meteor_hex", "Transform_meteor/Explosion/Stones_big", ["", "Stones_big_01", "Stones_small"]),
    "METEOR_WINGS": (MX + "magic_meteor_hex", "Transform_meteor/Sparks_meteor", ["Sparks", "Fire_start", "Sparks_wings_01", "Sparks_wings_02"]),
    "AVAL_WIND": (MX + "magic_avalanche_hex", "Transform_avalanche/Wind_down", ["Snowflakes_01", "Snow_smoke", "Trails_01", "Snow_smoke_02"]),
    "AVAL_ICE": (MX + "magic_avalanche_hex", "Transform_avalanche/Impact_ground", ["Ice_impact_01", "Ice_impact_02", "Snowflakes", "Snow_ground_impact_01"]),
    "SNOW_GROUND": (MX + "magic_snowball_idle_root", "Transform/Snow_ground_01", ["Snow_smoke_01", "Snow_smoke_02", "Snow_smoke_03", "Snow_ground_02", "Snow_ground_03"]),
    "SLEEP_IDLE": (MX + "magic_sleep_hex", "Transform_sleep/Idle", ["Dark_circle_01", "Dark_circle_02", "Light_conus", "Flash_01"]),
    "DESPAIR": (MX + "magic_despair_unit", "Transform_despair", ["Dark_spirals", "SmokeEnergyDark", "Force_wave_spine"]),
    "VENG_FLAME": (MX + "magic_vengeance_unit", "Transform/Idle_flame", ["Flame_sparks_01", "Flame_sparks_02", "Flame_sparks_03"]),
    "VENG_EMIT": (MX + "magic_vengeance_unit", "Transform/Idle_flame/Shield_fresnel/EmitterMove_01", ["Sparks", "Flame_sparks"]),
    "CLEANSE_WIND": (MX + "magic_cleansing_ray_unit", "Transform/Wind_dark", ["Wind_white_01", "Wind_white_02"]),
    "CLEANSE_SMOKE": (MX + "magic_cleansing_ray_unit", "Transform/SmokeEnergyDark", ["SmokeEnergyDark_up", "SparksEnergyDark"]),
    "PRIMAL_SYM": (MX + "magic_primal_state_unit", "Transform_primal/Eye_slide", ["Symbols_idle", "Aura_idle"]),
    "OBS_FIRE": (MX + "neutral/obsidiandragon/obsidiandragon_fire_idle_jaw", "Transform", ["fire_idle", "fire_idle/fire_surge", "flash_jaw"]),
    "MIRROR_IMPACT": (MX + "magic_mirror_copy_unit", "Transform_portal/impact", ["Wave_burst_01", "Wave_burst_02", "Energy_wave_01", "Energy_wave_02", "Flash_texture", "Sparks_burst_out"]),
    "TWI_SUN": (MX + "magic_twilight_hex", "Transform_twilight/Sun_moon/Sun", ["Sunlight_01", "Sunlight_02", "Sunlight_03", "Ray_fire", "flash_sun"]),
    "DRUID_LEAVES": (MX + "nature/druid/druid_upg_idle_root", "Leaves", [""]),
}

# default world scale per source (hex-sized spell prefabs are far larger than unit-socket effects)
SCALE = {k: 0.4 for k in SRC}
SCALE.update({k: 0.18 for k in ("BH_TRAILS", "BH_STAR", "BH_RAY", "BH_BOOM", "FLAME_IDLE", "FLAME_EMBERS", "CROWN_SHARDS",
                                "CROWN_WIND", "OPT_RING", "OPT_EYE", "OPT_TRI", "CLOCK", "CHAIN_RING", "METEOR_IDLE",
                                "METEOR_TRAIL", "METEOR_STONES", "METEOR_WINGS", "AVAL_WIND", "AVAL_ICE", "SNOW_GROUND",
                                "SLEEP_IDLE", "TWI_SUN", "PRIMAL_SYM", "FAIRY")})
SCALE.update({"LS_SMALL": 0.35, "LS_TRAIL": 0.3, "VORTEX": 0.3, "P_SMOKE": 0.3, "P_STEAM": 0.3, "CAV_SMOKE": 0.45,
              "FANGS": 0.25, "FIREFLY_B": 0.35, "FIREFLY_P": 0.35, "LW_SUN": 0.45, "LW_RAYS": 0.45, "PARAGON_CRYS": 0.4,
              "DESPAIR": 0.35, "VENG_FLAME": 0.35, "VENG_EMIT": 0.35, "HEAL_WATER": 0.45, "CLEANSE_WIND": 0.35,
              "CLEANSE_SMOKE": 0.35, "QILIN_SMOKE": 0.4})

GREY, ASH, SAND, OCHRE = [0.6, 0.58, 0.56], [0.45, 0.42, 0.4], [0.9, 0.72, 0.45], [0.85, 0.55, 0.3]
ICE, CYAN, SILVER, GOLD = [0.75, 0.9, 1.0], [0.4, 0.9, 1.0], [0.85, 0.88, 0.95], [1.0, 0.8, 0.3]
VIOLET, GREEN, CRIMSON, ORANGE = [0.6, 0.35, 1.0], [0.35, 1.0, 0.55], [1.0, 0.2, 0.15], [1.0, 0.55, 0.15]
# unit slug -> (theme line, overlay tint rgb, [(source, bone, trigger 'idle'|'atk', recolor or None, scale mul)])
DESIGN = {
    "dirty_thunder": ("ash smoke plume + crackling lightning arcs", [0.45, 0.5, 0.75],
                      [("P_SMOKE", "Spine2", "idle", ASH, 1.2), ("QILIN_ARCS", "Head", "idle", [0.7, 0.8, 1.0], 1.0), ("LS_SMALL", "RightHand", "atk", None, 1.0)]),
    "pyrocumulus": ("billowing fire-cloud with drifting embers", [1.0, 0.5, 0.2],
                    [("CAV_SMOKE", "Head", "idle", [0.75, 0.6, 0.55], 1.0), ("FLAME_EMBERS", "Spine2", "idle", ORANGE, 1.0), ("EMISSARY_FIRE", "RightHand", "atk", None, 1.0)]),
    "supercell": ("rotating storm wall + ring lightning", [0.45, 0.55, 0.85],
                  [("VORTEX", "Hips", "idle", [0.55, 0.6, 0.75], 1.3), ("CHAIN_RING", "Head", "idle", None, 0.8), ("MECH_HIT", "RightHand", "atk", None, 1.0)]),
    "maelstrom": ("whirlpool funnel + churning water", [0.15, 0.6, 0.7],
                  [("VORTEX", "Hips", "idle", [0.2, 0.6, 0.7], 1.2), ("NAIAD_IDLE", "Spine2", "idle", None, 1.0), ("NAIAD_HIT", "RightHand", "atk", None, 1.0)]),
    "polar_vortex": ("swirling snow-wind + frost breath", [0.7, 0.85, 1.0],
                     [("AVAL_WIND", "Hips", "idle", None, 1.0), ("FROST_IDLE", "Head", "idle", None, 1.0), ("FROST_HIT", "RightHand", "atk", None, 1.0)]),
    "dust_devil": ("sand whirlwind + grit spray", [0.9, 0.7, 0.4],
                   [("VORTEX", "Hips", "idle", SAND, 1.2), ("CAV_SMOKE", "Spine", "idle", SAND, 0.9), ("FANGS", "RightHand", "atk", SAND, 1.0)]),
    "haboob": ("rolling dust wall + choking smoke burst", [0.85, 0.55, 0.3],
                [("CLEANSE_WIND", "Spine2", "idle", OCHRE, 1.0), ("P_STEAM", "Hips", "idle", OCHRE, 1.2), ("ASSASSIN_SMOKE", "RightHand", "atk", OCHRE, 1.0)]),
    "rainbow": ("prismatic shimmer rings + glitter", [0.9, 0.6, 1.0],
                [("OPT_RING", "Head", "idle", None, 1.0), ("PIXIE_POLLEN", "Spine2", "idle", None, 1.0), ("STAR_BURST", "RightHand", "atk", None, 1.0)]),
    "borealis": ("aurora light curtains + green-violet glow", [0.35, 1.0, 0.65],
                 [("LW_RAYS", "Head", "idle", GREEN, 1.0), ("SENT_ENERGY", "Spine2", "idle", [0.5, 0.4, 1.0], 1.0), ("LW_HAND", "RightHand", "atk", GREEN, 1.0)]),
    "lahar": ("molten mudflow + ember sparks", [0.8, 0.45, 0.2],
              [("NAIAD_IDLE", "Hips", "idle", [0.7, 0.4, 0.2], 1.1), ("P_SPARKS", "Spine2", "idle", None, 1.0), ("OLGOI_LAVA", "RightHand", "atk", None, 1.0)]),
    "supervolcano": ("lava eruption from the crest + smoking lava sparks", [1.0, 0.35, 0.1],
                     [("FLAME_IDLE", "Head", "idle", None, 1.0), ("METEOR_IDLE", "Spine2", "idle", None, 1.0), ("BLACKDRAGON", "RightHand", "atk", None, 1.0)]),
    "fulgurite": ("glass shards + ground crackle", [1.0, 0.9, 0.6],
                  [("CROWN_SHARDS", "Head", "idle", [0.95, 0.85, 0.6], 1.0), ("QILIN_ARCS", "Hips", "idle", [1.0, 0.9, 0.6], 1.0), ("LS_TRAIL", "RightHand", "atk", [1.0, 0.9, 0.6], 1.0)]),
    "glass": ("crystal glints + furnace fire", [1.0, 0.75, 0.45],
              [("PARAGON_CRYS", "Head", "idle", None, 1.0), ("P_FIRE", "Spine2", "idle", ORANGE, 0.9), ("DRUID_CRYSTAL", "RightHand", "atk", None, 1.0)]),
    "quicksilver": ("liquid-metal orbs + silver sparkle", [0.85, 0.88, 0.95],
                    [("NAIAD_BALL", "Spine2", "idle", SILVER, 0.8), ("STAR_IDLE", "Head", "idle", SILVER, 1.0), ("NAIAD_FLOOD", "RightHand", "atk", SILVER, 0.9)]),
    "philosophers_stone": ("golden transmutation halo + gold dust", [1.0, 0.8, 0.3],
                           [("LW_SUN", "Head", "idle", GOLD, 1.0), ("PIXIE_POLLEN", "Spine2", "idle", GOLD, 1.0), ("ANGEL_IMPACT", "RightHand", "atk", GOLD, 1.0)]),
    "causeway": ("basalt ground mist + sea spray", [0.45, 0.55, 0.7],
                 [("SNOW_GROUND", "Hips", "idle", [0.45, 0.5, 0.6], 1.0), ("NAIAD_SPRAY", "Spine2", "idle", None, 1.0), ("AVAL_ICE", "RightHand", "atk", [0.45, 0.45, 0.5], 1.0)]),
    "henge": ("orbiting runestones + fairy-ring glows", [0.6, 0.5, 0.9],
              [("CROWN_SHARDS", "Spine2", "idle", GREY, 1.3), ("FAIRY", "Hips", "idle", None, 1.0), ("PRIMAL_SYM", "RightHand", "atk", None, 1.0)]),
    "permafrost": ("frozen ground mist + frost breath", [0.7, 0.85, 1.0],
                   [("SNOW_GROUND", "Hips", "idle", ICE, 1.0), ("FROST_IDLE", "Spine2", "idle", None, 1.0), ("FROST_HIT", "RightHand", "atk", ICE, 1.0)]),
    "iceberg": ("floating ice chunks + cold sea", [0.55, 0.8, 1.0],
                [("CROWN_SHARDS", "Head", "idle", ICE, 1.0), ("NAIAD_IDLE", "Hips", "idle", [0.4, 0.7, 1.0], 1.0), ("AVAL_ICE", "RightHand", "atk", ICE, 1.0)]),
    "hoarfrost": ("frost breath + white frost glitter", [0.85, 0.95, 1.0],
                  [("FROST_IDLE", "Head", "idle", None, 1.0), ("PIXIE_POLLEN", "Spine2", "idle", [0.9, 0.95, 1.0], 1.0), ("AVAL_WIND", "RightHand", "atk", None, 0.8)]),
    "jokulhlaup": ("glacial meltwater + rising steam", [0.4, 0.9, 1.0],
                   [("NAIAD_IDLE", "Spine2", "idle", CYAN, 1.0), ("P_STEAM", "Head", "idle", [0.9, 0.95, 1.0], 1.0), ("NAIAD_FLOOD", "RightHand", "atk", CYAN, 1.0)]),
    "spring": ("hot-spring steam + blossom leaves", [0.5, 1.0, 0.7],
               [("P_STEAM", "Spine2", "idle", [0.95, 0.95, 0.95], 1.0), ("DRUID_LEAVES", "Hips", "idle", None, 1.0), ("NAIAD_HIT", "RightHand", "atk", [0.5, 1.0, 0.85], 1.0)]),
    "fountain_of_youth": ("healing water ring + golden-green motes", [0.5, 1.0, 0.8],
                          [("HEAL_WATER", "Head", "idle", None, 1.0), ("STAR_IDLE", "Spine2", "idle", [0.7, 1.0, 0.5], 1.0), ("LW_BURST", "RightHand", "atk", [0.5, 1.0, 0.85], 1.0)]),
    "bolide": ("burning rock with smoke trail", [1.0, 0.5, 0.2],
               [("METEOR_IDLE", "Head", "idle", None, 1.0), ("P_FIRE", "Spine2", "idle", None, 0.9), ("METEOR_WINGS", "RightHand", "atk", None, 1.0)]),
    "meteor_shower": ("falling fire streaks + star sparks", [1.0, 0.7, 0.35],
                      [("METEOR_TRAIL", "Head", "idle", None, 1.0), ("STAR_IDLE", "Spine2", "idle", [1.0, 0.75, 0.4], 1.0), ("METEOR_STONES", "RightHand", "atk", None, 1.0)]),
    "protostar": ("blazing corona + accretion swirl", [1.0, 0.75, 0.4],
                  [("LW_SUN", "Head", "idle", [1.0, 0.65, 0.3], 1.1), ("BH_TRAILS", "Spine2", "idle", [1.0, 0.6, 0.3], 1.0), ("STAR_HIT", "RightHand", "atk", None, 1.0)]),
    "singularity": ("dark star + spiralling nebula trails", [0.5, 0.3, 0.9],
                    [("BH_STAR", "Head", "idle", None, 1.0), ("BH_TRAILS", "Spine2", "idle", None, 1.0), ("BH_BOOM", "RightHand", "atk", None, 1.0)]),
    "eclipse": ("dark corona ring + shadow smoke", [0.35, 0.15, 0.6],
                [("LW_SUN", "Head", "idle", [0.35, 0.15, 0.6], 1.2), ("CLEANSE_SMOKE", "Spine2", "idle", None, 1.0), ("BH_RAY", "RightHand", "atk", None, 1.0)]),
    "wormhole": ("swirling portal rings + violet vortex", [0.55, 0.4, 1.0],
                 [("CLOCK", "Spine2", "idle", None, 1.0), ("VORTEX", "Hips", "idle", VIOLET, 1.2), ("MIRROR_IMPACT", "RightHand", "atk", None, 1.0)]),
    "illusionist": ("mystic triangle sigil + violet mist", [0.65, 0.4, 1.0],
                    [("OPT_TRI", "Head", "idle", None, 1.0), ("SENT_ENERGY", "Spine2", "idle", VIOLET, 1.0), ("TRICK_SLASH", "RightHand", "atk", None, 1.0)]),
    "fever_dream": ("drowsy dream waves + purple fireflies", [0.75, 0.45, 1.0],
                    [("SLEEP_IDLE", "Hips", "idle", None, 1.0), ("FIREFLY_P", "Head", "idle", None, 1.0), ("LICH_ALT", "RightHand", "atk", None, 1.0)]),
    "nightmare": ("dark smoke aura + bleeding heart", [0.6, 0.1, 0.25],
                  [("QILIN_SMOKE", "Spine2", "idle", None, 1.0), ("VAMP_HEART", "Spine1", "idle", None, 0.7), ("LOCUST", "RightHand", "atk", None, 1.0)]),
    "kaleidoscope": ("nested prism rings + triangle facets", [0.7, 0.85, 1.0],
                     [("OPT_RING", "Spine2", "idle", None, 1.3), ("OPT_TRI", "Hips", "idle", None, 1.0), ("PIXIE_HIT", "RightHand", "atk", None, 1.0)]),
    "black_mirror": ("staring cosmic eye + dark spirals", [0.25, 0.2, 0.35],
                     [("OPT_EYE", "Head", "idle", None, 1.0), ("DESPAIR", "Spine2", "idle", None, 1.0), ("FLICKER_HIT", "RightHand", "atk", None, 1.0)]),
    "will_o_wisp": ("floating wisp lights + ghost flame", [0.4, 0.95, 0.8],
                    [("FIREFLY_B", "Spine2", "idle", None, 1.2), ("OBS_FIRE", "Head", "idle", [0.4, 1.0, 0.75], 0.8), ("UNICORN_HIT", "RightHand", "atk", [0.4, 1.0, 0.75], 1.0)]),
    "ley_line": ("glowing rune glyphs + energy lines", [0.45, 0.7, 1.0],
                 [("PRIMAL_SYM", "Hips", "idle", None, 1.0), ("LW_RAYS", "Spine2", "idle", [0.45, 0.7, 1.0], 1.0), ("LICH_BURST", "RightHand", "atk", None, 1.0)]),
    "vengeance": ("fire-shield flames + orbiting sparks", [1.0, 0.25, 0.15],
                  [("VENG_FLAME", "Spine2", "idle", None, 1.0), ("VENG_EMIT", "Head", "idle", None, 1.0), ("DRAGON_BREATH", "RightHand", "atk", CRIMSON, 1.0)]),
}


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def layer(lid, key, bone, trig, recolor, mul, nk):
    res, child, keep = SRC[key]
    always = trig == "idle"
    l = {"id": lid, "type": "vanillaParticles", "source": {"resPath": res, "childPath": child, "keepNodes": list(keep)},
         "bones": [bone], "scale": round(SCALE[key] * mul, 4), "rateMul": 1.0, "loop": always, "orient": "bone",
         "zeroChildPositions": False,
         "triggers": [{"mode": "always"}] if always else
         [{"mode": "window", "clip": "Unit_AttackFront", "startKey": max(0, round(0.45 * nk) - 1), "end": "stopEmitting"}]}
    if recolor:
        l["recolor"] = recolor
    return l


def build_layer_rows(sid, l, df):
    """Build one layer; drop the recolour if the source cannot take it, and Local-mode descendants issues -> zero."""
    src = VSF.load(VSF.SOURCES)["sources"][l["source"]["resPath"]]
    full = VSF.resolve_child(src, l["source"]["childPath"], f"{sid}/{l['id']}")
    sub = VSF.subtree(src, full)
    bad = [p for p, n in sub.items() if n["scripts"] or n["animator"] or n["director"]]
    missing = [k for k in l["source"]["keepNodes"] if not (sub.get(k) or {}).get("particleSystem")]
    if bad or missing:
        raise SystemExit(f"{sid}/{l['id']}: subtree has script/animator nodes {bad} or keepNodes without a ParticleSystem {missing}")
    for attempt in range(4):
        try:
            return VSF.build_rows(sid, {"gameUnitSids": [sid], "layers": [l]}, df, {}), l
        except VSF.VsError as ex:
            msg = str(ex)
            if "use recolorMode 'multiply'" in msg and l.get("recolor") and not l.get("recolorMode"):
                l = dict(l, recolorMode="multiply")
                continue
            if ("recolour" in msg or "recolorMode" in msg) and l.get("recolor"):
                l.pop("recolorMode", None)
                l = dict(l)
                l.pop("recolor")
                l["note"] = "recolour dropped: " + msg[:160]
                continue
            if "zeroChildPositions" in msg and not l["zeroChildPositions"]:
                l = dict(l, zeroChildPositions=True)
                continue
            raise


def catalog_row(rows, rid):
    return next(r for r in rows if r["id"] == rid)


def cmd_compile(sources: Path, assets: Path, out: Path) -> None:
    VSF.SOURCES = sources
    pb = FX.pair_by_sid()
    cat = json.loads(VSF.CATALOG.read_text(encoding="utf-8"))["entries"]
    recs = json.loads(RECIPES.read_text(encoding="utf-8"))
    seen, allrows, themes = {}, [], {}
    for r in recs:
        sid, a = r["fused"], r["host"]
        slug = sid[len("h3_fusion_ii_"):]
        theme, tint, design = DESIGN[slug]
        h = pb[a][0]
        hu = FX.unit(h)
        df = FX.host_df(h)
        nk = hu["defKeys"]["Unit_AttackFront"]
        origin, sids = FX.ORIGIN_PREFIX + sid, [sid]
        sig = tuple(sorted((k, b, t) for k, b, t, _, _ in design))
        if sig in seen:
            raise SystemExit(f"{sid}: same themed set as {seen[sig]}")
        seen[sig] = sid
        rows = []
        for hr in hu["record"]["rows"]:
            if hr["lane"] in ("battle_emission", "battle_body_displacement"):
                continue
            r2 = json.loads(json.dumps(hr))
            r2["id"] = hr["id"].replace(f"vs_{h}_", f"fx_{sid}_host_", 1)
            r2["origin"], r2["match"] = origin, {"unitSids": sids}
            rows.append(r2)
        em1 = catalog_row(cat, f"fx_{a}_fused_emission")["emission"]
        mfx = assets / sid / "homm3_mesh_fx"
        be, ce = f"emission/{sid}__body_emission.png", f"emission/{sid}__crest_emission.png"
        bm, cm = f"fusion/{sid}__body_mask.png", f"fusion/{sid}__crest_mask.png"
        rows.append({"id": f"fx_{sid}_fused_emission", "lane": "battle_emission", "origin": origin, "match": {"unitSids": sids},
                     "emission": {"texture": be, "textureSha256": sha(mfx / be), "color": em1["color"],
                                  "minPower": em1["minPower"], "blinkPower": em1["blinkPower"], "blinkSpeed": em1["blinkSpeed"],
                                  "crestTexture": ce, "crestTextureSha256": sha(mfx / ce)}, "proof": PROOF})
        ov1 = catalog_row(cat, f"fx_{a}_fusion_overlay")["source"]
        rows.append({"id": f"fx_{sid}_fusion_overlay", "lane": "battle_body_overlay", "origin": origin, "match": {"unitSids": sids},
                     "source": {"nativeResPath": ov1["nativeResPath"], "rendererPath": ov1["rendererPath"],
                                "materialIndex": ov1["materialIndex"],
                                "colors": [{"property": "_Color", "rgba": [float(c) for c in tint] + [1.0]}],
                                "textures": [{"property": "_Mask", "file": bm, "sha256": sha(mfx / bm)}],
                                "crestTextures": [{"property": "_Mask", "file": cm, "sha256": sha(mfx / cm)}]},
                     "trigger": {"mode": "always"}, "proof": PROOF})
        notes = []
        for i, (key, bone, trig, rec, mul) in enumerate(design):
            lid = f"s2_{'idle' if trig == 'idle' else 'atk'}{i}_{key.lower()}"
            built, used = build_layer_rows(sid, layer(lid, key, bone, trig, rec, mul, nk), df)
            if used.get("note"):
                notes.append(f"{lid}: {used['note']}")
            for b in built:
                b["id"] = b["id"].replace(f"vs_{sid}_", f"fx_{sid}_", 1)
                b["origin"], b["match"] = origin, {"unitSids": sids}
            rows += built
        ids = [x["id"] for x in rows]
        if len(ids) != len(set(ids)):
            raise SystemExit(f"{sid}: duplicate ids")
        allrows += rows
        themes[sid] = {"name": r["name"], "theme": theme, "tint": tint,
                       "layers": [f"{k}@{b}:{t}" for k, b, t, _, _ in design], "notes": notes, "rows": len(rows)}
        print(f"compile: {sid} rows={len(rows)} {'; '.join(notes)[:200]}")
    out.mkdir(parents=True, exist_ok=True)
    (out / "stage2_rows.json").write_text(json.dumps({"count": len(allrows), "entries": allrows}, indent=1), encoding="utf-8")
    (out / "stage2_themes.json").write_text(json.dumps(themes, indent=1), encoding="utf-8")
    used = sorted({x["source"]["nativeResPath"] for x in allrows if "source" in x})
    (out / "stage2_native_res_paths.json").write_text(json.dumps(used, indent=1), encoding="utf-8")
    print(f"rows: {len(allrows)} for {len(themes)} units; {len(used)} native sources")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=("compile",))
    ap.add_argument("--sources", required=True, type=Path)
    ap.add_argument("--assets", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    a = ap.parse_args()
    cmd_compile(a.sources, a.assets, a.out)
