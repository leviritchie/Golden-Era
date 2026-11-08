"""Per-asset metadata for shape-preserving preparation. Not species-specific solvers."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from donor_eagle import EAGLE_KIND, EAGLE_REF_SEQ, REGION_JOINTS as EAGLE_REGION_JOINTS
from paths import MESHY, VENDOR_DEMO
from roc_copy import ROC_REGION_BONES

MIXAMO_REF_SEQ = "00160523-f3b6-5765-931a-351e339862d7#00160523-f3b6-5765-931a-351e339862d7/y0"
MIXAMO_SPECIES = "00160523-f3b6-5765-931a-351e339862d7"

MIXAMO_CAPTURE_BIND = {
    "headJoint": "mixamorig:Head",
    "leftJoint": "mixamorig:LeftShoulder",
    "rightJoint": "mixamorig:RightShoulder",
    "meshBodyAxis": (0.0, 1.0, 0.0),
    "meshSecondAxis": (0.0, 0.0, 1.0),
    "skinFrozenRegions": (),
}

EAGLE_CAPTURE_BIND = {
    "headJoint": "Bip01_Head",
    "leftJoint": "BN_Wing_L_06",
    "rightJoint": "BN_Wing_R_06",
    "meshBodyAxis": (0.0, 0.0, 1.0),
    "meshSecondAxis": (0.0, 1.0, 0.0),
    "skinFrozenRegions": ("leg_left", "leg_right", "beak"),
}

MIXAMO_REGION_JOINTS = {
    "torso": (
        "mixamorig:Hips",
        "mixamorig:Spine",
        "mixamorig:Spine1",
        "mixamorig:Spine2",
    ),
    "neck_head": (
        "mixamorig:Neck",
        "mixamorig:Head",
        "mixamorig:HeadTop_End",
    ),
    "arm_left": (
        "mixamorig:LeftShoulder",
        "mixamorig:LeftArm",
        "mixamorig:LeftForeArm",
        "mixamorig:LeftHand",
    ),
    "arm_right": (
        "mixamorig:RightShoulder",
        "mixamorig:RightArm",
        "mixamorig:RightForeArm",
        "mixamorig:RightHand",
    ),
    "leg_left": (
        "mixamorig:LeftUpLeg",
        "mixamorig:LeftLeg",
        "mixamorig:LeftFoot",
        "mixamorig:LeftToeBase",
        "mixamorig:LeftToe_End",
    ),
    "leg_right": (
        "mixamorig:RightUpLeg",
        "mixamorig:RightLeg",
        "mixamorig:RightFoot",
        "mixamorig:RightToeBase",
        "mixamorig:RightToe_End",
    ),
}

CRUSADER_REGION_BONES = {
    "torso": ("Bone_000", "Bone_001", "Bone_010", "Bone_009", "Bone_008", "Bone_007", "Bone_006"),
    "neck_head": ("Bone_021", "Bone_020", "Bone_019"),
    "arm_left": ("Bone_026", "Bone_025", "Bone_024", "Bone_023", "Bone_022", "Bone_035", "Bone_034", "Bone_033", "Bone_032"),
    "arm_right": ("Bone_031", "Bone_030", "Bone_029", "Bone_028", "Bone_027"),
    "leg_left": ("Bone_014", "Bone_013", "Bone_012", "Bone_011"),
    "leg_right": ("Bone_018", "Bone_017", "Bone_016", "Bone_015"),
    "shield": ("Bone_039", "Bone_038", "Bone_037", "Bone_036"),
    "weapon": ("Bone_047", "Bone_046", "Bone_045", "Bone_044"),
    "accessory": ("Bone_043", "Bone_042", "Bone_041", "Bone_040"),
    "pelvis_aux": ("Bone_003", "Bone_002", "Bone_005", "Bone_004"),
}

# Existing SmartRig labels are evidence, not anatomical truth.
ROC_EAGLE = {
    "assetId": "h3_roc",
    "displayName": "Roc",
    "mesh": MESHY / "h3_roc_smartrigged.glb",
    "expectedMeshSha256": "f3644a01a07413441dd0081406e63c56c45ee70218d38e7a2a525864c67acf3a",
    "donorKind": EAGLE_KIND,
    "donorRefSeq": EAGLE_REF_SEQ,
    "donorCharacterDir": VENDOR_DEMO / "zoo1030" / "characters_fix_facezplus" / "Eagle",
    "donorBindSource": "capture_bvh_offsets",
    "regionJoints": EAGLE_REGION_JOINTS,
    "regionBones": ROC_REGION_BONES,
    "beakFromHeadQuantile": 0.92,
    "headBone": "Bone_014",
    "neckBone": "Bone_015",
    "rigidAttachments": (
        {"region": "beak", "donorJoints": ("BN_Jaw", "Bip01_Head"), "reason": "five_vertex_beak_cannot_support_jaw_articulation"},
    ),
    "hubs": {
        "Hips": "Bone_000",
        "Bip01_Pelvis": "Bone_001",
        "Bip01_Spine": "Bone_003",
        "Bip01_Spine1": "Bone_002",
    },
    "chains": (
        {"name": "neck", "kind": "polyline", "donor": ("Bip01_Neck", "Bip01_Neck1", "Bip01_Neck2", "Bip01_Head"), "evidence": ("Bone_016", "Bone_015", "Bone_014")},
        {"name": "jaw", "kind": "toward_region", "donor": ("BN_Jaw",), "parent": "Bip01_Head", "region": "beak", "helper": True},
        {
            "name": "wing_left",
            "kind": "polyline",
            "donor": ("BN_Wing_L_01", "BN_Wing_L_02", "BN_Wing_L_03", "BN_Wing_L_04"),
            "evidence": ("Bone_022", "Bone_021", "Bone_020"),
        },
        {
            "name": "wing_left_trail",
            "kind": "fork",
            "donor": ("BN_Wing_L_05", "BN_Wing_L_06"),
            "parent": "BN_Wing_L_03",
            "primary": "BN_Wing_L_04",
            "region": "wing_left",
        },
        {
            "name": "wing_right",
            "kind": "polyline",
            "donor": ("BN_Wing_R_01", "BN_Wing_R_02", "BN_Wing_R_03", "BN_Wing_R_04"),
            "evidence": ("Bone_019", "Bone_018", "Bone_017"),
        },
        {
            "name": "wing_right_trail",
            "kind": "fork",
            "donor": ("BN_Wing_R_05", "BN_Wing_R_06"),
            "parent": "BN_Wing_R_03",
            "primary": "BN_Wing_R_04",
            "region": "wing_right",
        },
        {
            "name": "leg_left",
            "kind": "polyline",
            "donor": ("Bip01_L_Thigh", "Bip01_L_Calf", "Bip01_L_HorseLink", "Bip01_L_Foot"),
            "evidence": ("Bone_007", "Bone_006", "Bone_005", "Bone_004"),
        },
        {
            "name": "leg_right",
            "kind": "polyline",
            "donor": ("Bip01_R_Thigh", "Bip01_R_Calf", "Bip01_R_HorseLink", "Bip01_R_Foot"),
            "evidence": ("Bone_011", "Bone_010", "Bone_009", "Bone_008"),
        },
        {
            "name": "toes_left",
            "kind": "relative_to_parent",
            "donor": (
                "BN_Toe_L_00",
                "BN_Toe_L_01",
                "BN_Toe_L_10",
                "BN_Toe_L_11",
                "BN_Toe_L_20",
                "BN_Toe_L_21",
                "BN_Toe_L_30",
                "BN_Toe_L_31",
            ),
            "anchor": "Bip01_L_Foot",
            "region": "leg_left",
            "helper": True,
        },
        {
            "name": "toes_right",
            "kind": "relative_to_parent",
            "donor": (
                "BN_Toe_R_00",
                "BN_Toe_R_01",
                "BN_Toe_R_10",
                "BN_Toe_R_11",
                "BN_Toe_R_20",
                "BN_Toe_R_21",
                "BN_Toe_R_30",
                "BN_Toe_R_31",
            ),
            "anchor": "Bip01_R_Foot",
            "region": "leg_right",
            "helper": True,
        },
        {
            "name": "tail",
            "kind": "polyline",
            "donor": ("BN_Tai_01", "BN_Tai_R_01", "BN_Tai_R_02"),
            "evidence": ("Bone_013", "Bone_012"),
        },
        {
            "name": "tail_left",
            "kind": "fork",
            "donor": ("BN_Tai_L_01", "BN_Tai_L_02"),
            "parent": "BN_Tai_01",
            "primary": "BN_Tai_R_02",
            "region": "tail",
            "helper": True,
        },
    ),
    "leftRightPairs": (
        {
            "donor": ("BN_Wing_L_04", "BN_Wing_R_04"),
            "evidence": ("Bone_020", "Bone_017"),
        },
        {
            "donor": ("Bip01_L_Foot", "Bip01_R_Foot"),
            "evidence": ("Bone_004", "Bone_008"),
        },
    ),
    "requiredBranches": ("torso", "neck_head", "wing_left", "wing_right", "leg_left", "leg_right", "tail"),
    "actuation": (
        ("shoulder_L", "BN_Wing_L_01", "wing_left", "wing_right"),
        ("midwing_L", "BN_Wing_L_03", "wing_left", "wing_right"),
        ("neck", "Bip01_Neck", "neck_head", "wing_right"),
        ("tail", "BN_Tai_01", "tail", "wing_left"),
        ("leg_L", "Bip01_L_Thigh", "leg_left", "leg_right"),
    ),
    "wholeBodyHubs": ("Hips", "Bip01_Spine", "Bip01_Spine1", "Bip01_Head", "BN_Wing_L_01", "BN_Wing_R_01", "Bip01_L_Thigh", "Bip01_R_Thigh"),
    # Linked-master owned-bones bind (prepare_move_bind_capture_bind). Capture
    # body axis = root->head, lateral = left->right joint. The Meshy mesh for a
    # gliding bird has its body axis along canonical +Z and its back along +Y.
    "captureBind": EAGLE_CAPTURE_BIND,
}

CRUSADER_MIXAMO = {
    "assetId": "h3_crusader",
    "displayName": "Crusader",
    "mesh": MESHY / "h3_crusader_smartrigged.glb",
    "expectedMeshSha256": "607ccbe1ad782b7366ea7ed754b03880985f369ef09bb9be3b01ac4ccd32772d",
    "donorKind": "obj",
    "donorRefSeq": MIXAMO_REF_SEQ,
    "donorCharacterDir": VENDOR_DEMO / "obj1k" / "characters" / MIXAMO_SPECIES,
    "donorBindSource": "ffs_bvh_capture_scale",
    "regionJoints": MIXAMO_REGION_JOINTS,
    "regionBones": CRUSADER_REGION_BONES,
    "beakFromHeadQuantile": None,
    "headBone": "Bone_019",
    "neckBone": "Bone_020",
    "rigidAttachments": (
        {"region": "shield", "donorJoints": ("mixamorig:LeftHand",), "reason": "shield_is_rigid_prop_not_a_mixamo_surface"},
        {"region": "weapon", "donorJoints": ("mixamorig:RightHand",), "reason": "weapon_is_rigid_prop_not_a_mixamo_surface"},
        {"region": "accessory", "donorJoints": ("mixamorig:RightHand",), "reason": "accessory_is_rigid_prop_not_a_mixamo_surface"},
    ),
    "hubs": {
        "mixamorig:Hips": "Bone_001",
        "mixamorig:Spine": "Bone_010",
        "mixamorig:Spine1": "Bone_009",
        "mixamorig:Spine2": "Bone_006",
    },
    "chains": (
        {"name": "neck", "kind": "polyline", "donor": ("mixamorig:Neck", "mixamorig:Head"), "evidence": ("Bone_021", "Bone_019")},
        {
            "name": "head_end",
            "kind": "relative_to_parent",
            "donor": ("mixamorig:HeadTop_End",),
            "anchor": "mixamorig:Head",
            "region": "neck_head",
            "helper": True,
        },
        {
            "name": "arm_left",
            "kind": "polyline",
            "donor": ("mixamorig:LeftShoulder", "mixamorig:LeftArm", "mixamorig:LeftForeArm", "mixamorig:LeftHand"),
            "evidence": ("Bone_026", "Bone_025", "Bone_024", "Bone_032"),
        },
        {
            "name": "arm_right",
            "kind": "polyline",
            "donor": ("mixamorig:RightShoulder", "mixamorig:RightArm", "mixamorig:RightForeArm", "mixamorig:RightHand"),
            "evidence": ("Bone_031", "Bone_030", "Bone_029", "Bone_027"),
        },
        {
            "name": "leg_left",
            "kind": "polyline",
            "donor": ("mixamorig:LeftUpLeg", "mixamorig:LeftLeg", "mixamorig:LeftFoot", "mixamorig:LeftToeBase"),
            "evidence": ("Bone_014", "Bone_013", "Bone_012", "Bone_011"),
        },
        {
            "name": "leg_right",
            "kind": "polyline",
            "donor": ("mixamorig:RightUpLeg", "mixamorig:RightLeg", "mixamorig:RightFoot", "mixamorig:RightToeBase"),
            "evidence": ("Bone_018", "Bone_017", "Bone_016", "Bone_015"),
        },
        {
            "name": "toe_end_left",
            "kind": "relative_to_parent",
            "donor": ("mixamorig:LeftToe_End",),
            "anchor": "mixamorig:LeftToeBase",
            "region": "leg_left",
            "helper": True,
        },
        {
            "name": "toe_end_right",
            "kind": "relative_to_parent",
            "donor": ("mixamorig:RightToe_End",),
            "anchor": "mixamorig:RightToeBase",
            "region": "leg_right",
            "helper": True,
        },
    ),
    "leftRightPairs": (
        {
            "donor": ("mixamorig:LeftHand", "mixamorig:RightHand"),
            "evidence": ("Bone_032", "Bone_027"),
        },
        {
            "donor": ("mixamorig:LeftFoot", "mixamorig:RightFoot"),
            "evidence": ("Bone_011", "Bone_015"),
        },
    ),
    "requiredBranches": ("torso", "neck_head", "arm_left", "arm_right", "leg_left", "leg_right"),
    "extraTargetBones": (
        "Bone_000",
        "Bone_003",
        "Bone_002",
        "Bone_005",
        "Bone_004",
        "Bone_008",
        "Bone_007",
        "Bone_023",
        "Bone_022",
        "Bone_035",
        "Bone_034",
        "Bone_033",
        "Bone_028",
        "Bone_039",
        "Bone_038",
        "Bone_037",
        "Bone_036",
        "Bone_047",
        "Bone_046",
        "Bone_045",
        "Bone_044",
        "Bone_043",
        "Bone_042",
        "Bone_041",
        "Bone_040",
    ),
    "unsupportedRequiredArticulations": (
        "crusader_shield_chain_is_a_rigid_prop_not_a_mixamo_joint",
        "crusader_weapon_chain_is_a_rigid_prop_not_a_mixamo_joint",
    ),
    "actuation": (
        ("shoulder_L", "mixamorig:LeftArm", "arm_left", "arm_right"),
        ("forearm_L", "mixamorig:LeftForeArm", "arm_left", "arm_right"),
        ("thigh_L", "mixamorig:LeftUpLeg", "leg_left", "leg_right"),
        ("spine", "mixamorig:Spine1", "torso", "leg_right"),
    ),
    "wholeBodyHubs": (
        "mixamorig:Hips",
        "mixamorig:Spine2",
        "mixamorig:Head",
        "mixamorig:LeftShoulder",
        "mixamorig:RightShoulder",
        "mixamorig:LeftUpLeg",
        "mixamorig:RightUpLeg",
    ),
    "syntheticMotionOnly": True,
    "captureBind": MIXAMO_CAPTURE_BIND,
}

PROFILES = {
    "h3_roc": ROC_EAGLE,
    "h3_crusader": CRUSADER_MIXAMO,
}


def get_profile(asset_id: str) -> dict[str, Any]:
    from structured_profiles import registered_profiles, load_registered_profile
    registered = registered_profiles()
    if asset_id in registered:
        return load_registered_profile(asset_id, registered[asset_id])
    if asset_id == "h3_boar_rider":
        from asset_profile_boar_rider import get_profile as boar_profile
        return boar_profile()
    if asset_id == "h3_ancient_behemoth":
        from asset_profile_ancient_behemoth import get_profile as ancient_profile
        return ancient_profile()
    if asset_id == "h3_shahrokh":
        from asset_profile_shahrokh import get_profile as shahrokh_profile
        return shahrokh_profile()
    if asset_id == "h3_thunderbird":
        from asset_profile_thunderbird import get_profile as thunderbird_profile
        return thunderbird_profile()
    if asset_id == "h3_goblin_trapper":
        from asset_profile_goblin_trapper import get_profile as trapper_profile
        return trapper_profile()
    if asset_id == "h3_ghost_behemoth":
        from asset_profile_ghost_behemoth import get_profile as ghost_profile
        return ghost_profile()
    if asset_id == "h3_ogre_brute":
        from asset_profile_ogre_brute import get_profile as brute_profile
        return brute_profile()
    if asset_id == "h3_orc_berserker":
        from asset_profile_orc_berserker import get_profile as berserker_profile
        return berserker_profile()
    if asset_id == "h3_blood_eyed_cyclops":
        from asset_profile_blood_eyed_cyclops import get_profile as blood_eyed_profile
        return blood_eyed_profile()
    if asset_id == "h3_orc_chieftain":
        from asset_profile_orc_chieftain import get_profile as orc_chieftain_profile
        return orc_chieftain_profile()
    if asset_id == "h3_ogre_mage":
        from asset_profile_ogre_mage import get_profile as ogre_mage_profile
        return ogre_mage_profile()
    if asset_id == "h3_cyclops_king":
        from asset_profile_cyclops_king import get_profile as cyclops_king_profile
        return cyclops_king_profile()
    if asset_id == "h3_cyclops":
        from asset_profile_cyclops import get_profile as cyclops_profile
        return cyclops_profile()
    if asset_id == "h3_orc":
        from asset_profile_orc import get_profile as orc_profile
        return orc_profile()
    if asset_id == "h3_ogre":
        from asset_profile_ogre import get_profile as ogre_profile
        return ogre_profile()
    if asset_id == "h3_goblin":
        from asset_profile_goblin import get_profile as goblin_profile
        return goblin_profile()
    if asset_id == "h3_wolf_rider":
        from corrected_mounted_authoring import get_profile as wolf_profile
        return wolf_profile()
    if asset_id == "h3_wolf_raider":
        from corrected_mounted_authoring import get_profile as wolf_profile
        return wolf_profile("h3_wolf_raider")
    if asset_id == "h3_behemoth":
        from asset_profile_behemoth import BEHEMOTH_MIXAMO
        return BEHEMOTH_MIXAMO
    if asset_id == "h3_hobgoblin":
        from asset_profile_hobgoblin import HOBGOBLIN_MIXAMO
        return HOBGOBLIN_MIXAMO
    if asset_id not in PROFILES:
        raise KeyError(f"no shape-preserved profile for {asset_id!r}")
    return PROFILES[asset_id]


def profile_mesh(profile: dict[str, Any]) -> Path:
    return Path(profile["mesh"])
