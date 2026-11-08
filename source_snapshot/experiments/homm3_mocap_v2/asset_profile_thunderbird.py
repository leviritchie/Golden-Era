"""Thunderbird source-mapped profile for the verified Eagle mocap donor."""
from __future__ import annotations

from paths import MESHY, VENDOR_DEMO
from donor_eagle import EAGLE_KIND, EAGLE_REF_SEQ, REGION_JOINTS as EAGLE_REGION_JOINTS

MESH = MESHY / "h3_thunderbird_smartrigged.glb"
MESH_SHA256 = "a7993c7f3b3ab12e89ed063441f4727dd4d6cb50bc3e6139aa290dc6864a6e45"
REGION_JOINTS = dict(EAGLE_REGION_JOINTS)
REGION_JOINTS["leg_left"] = EAGLE_REGION_JOINTS["leg_left"][:4]
REGION_JOINTS["leg_right"] = EAGLE_REGION_JOINTS["leg_right"][:4]
REGION_JOINTS["toe_left_detail"] = EAGLE_REGION_JOINTS["leg_left"][4:]
REGION_JOINTS["toe_right_detail"] = EAGLE_REGION_JOINTS["leg_right"][4:]

REGION_BONES = {
    "torso": ("Bone_000", "Bone_001", "Bone_003", "Bone_002"),
    "neck_head": ("Bone_016", "Bone_015", "Bone_014"),
    "wing_left": ("Bone_022", "Bone_021", "Bone_020"),
    "wing_right": ("Bone_019", "Bone_018", "Bone_017"),
    "leg_left": ("Bone_007", "Bone_006", "Bone_005", "Bone_004"),
    "leg_right": ("Bone_011", "Bone_010", "Bone_009", "Bone_008"),
    "tail": ("Bone_013", "Bone_012"),
}

SOURCE_JOINT_MAP = {
    "Bone_000": "Hips", "Bone_001": "Bip01_Pelvis", "Bone_003": "Bip01_Spine", "Bone_002": "Bip01_Spine1",
    "Bone_016": "Bip01_Neck", "Bone_015": "Bip01_Neck1", "Bone_014": "Bip01_Head",
    "Bone_022": "BN_Wing_L_01", "Bone_021": "BN_Wing_L_03", "Bone_020": "BN_Wing_L_04",
    "Bone_019": "BN_Wing_R_01", "Bone_018": "BN_Wing_R_03", "Bone_017": "BN_Wing_R_04",
    "Bone_007": "Bip01_L_Thigh", "Bone_006": "Bip01_L_Calf", "Bone_005": "Bip01_L_HorseLink", "Bone_004": "Bip01_L_Foot",
    "Bone_011": "Bip01_R_Thigh", "Bone_010": "Bip01_R_Calf", "Bone_009": "Bip01_R_HorseLink", "Bone_008": "Bip01_R_Foot",
    "Bone_013": "BN_Tai_01", "Bone_012": "BN_Tai_R_02",
}

THUNDERBIRD_EAGLE = {
    "assetId": "h3_thunderbird", "displayName": "Thunderbird", "mesh": MESH, "expectedMeshSha256": MESH_SHA256,
    "donorKind": EAGLE_KIND, "donorRefSeq": EAGLE_REF_SEQ,
    "donorCharacterDir": VENDOR_DEMO / "zoo1030" / "characters_fix_facezplus" / "Eagle",
    "donorBindSource": "capture_bvh_offsets", "regionJoints": REGION_JOINTS, "regionBones": REGION_BONES,
    "beakFromHeadQuantile": None, "headBone": "Bone_014", "neckBone": "Bone_016",
    "requireCompleteRegionCoverage": True, "rigidAttachments": (),
    "hubs": {"Hips": "Bone_000", "Bip01_Pelvis": "Bone_001", "Bip01_Spine": "Bone_003", "Bip01_Spine1": "Bone_002"},
    "chains": (
        {"name": "neck", "kind": "polyline", "donor": ("Bip01_Neck", "Bip01_Neck1", "Bip01_Neck2", "Bip01_Head"), "evidence": ("Bone_016", "Bone_015", "Bone_014")},
        {"name": "wing_left", "kind": "polyline", "donor": ("BN_Wing_L_01", "BN_Wing_L_02", "BN_Wing_L_03", "BN_Wing_L_04"), "evidence": ("Bone_022", "Bone_021", "Bone_020")},
        {"name": "wing_left_trail", "kind": "fork", "donor": ("BN_Wing_L_05", "BN_Wing_L_06"), "parent": "BN_Wing_L_03", "primary": "BN_Wing_L_04", "region": "wing_left", "helper": True},
        {"name": "wing_right", "kind": "polyline", "donor": ("BN_Wing_R_01", "BN_Wing_R_02", "BN_Wing_R_03", "BN_Wing_R_04"), "evidence": ("Bone_019", "Bone_018", "Bone_017")},
        {"name": "wing_right_trail", "kind": "fork", "donor": ("BN_Wing_R_05", "BN_Wing_R_06"), "parent": "BN_Wing_R_03", "primary": "BN_Wing_R_04", "region": "wing_right", "helper": True},
        {"name": "leg_left", "kind": "polyline", "donor": ("Bip01_L_Thigh", "Bip01_L_Calf", "Bip01_L_HorseLink", "Bip01_L_Foot"), "evidence": ("Bone_007", "Bone_006", "Bone_005", "Bone_004")},
        {"name": "leg_right", "kind": "polyline", "donor": ("Bip01_R_Thigh", "Bip01_R_Calf", "Bip01_R_HorseLink", "Bip01_R_Foot"), "evidence": ("Bone_011", "Bone_010", "Bone_009", "Bone_008")},
        {"name": "tail", "kind": "polyline", "donor": ("BN_Tai_01", "BN_Tai_R_01", "BN_Tai_R_02"), "evidence": ("Bone_013", "Bone_012")},
        {"name": "toes_left", "kind": "relative_to_parent", "donor": ("BN_Toe_L_00", "BN_Toe_L_01", "BN_Toe_L_10", "BN_Toe_L_11", "BN_Toe_L_20", "BN_Toe_L_21", "BN_Toe_L_30", "BN_Toe_L_31"), "anchor": "Bip01_L_Foot", "region": "leg_left", "helper": True},
        {"name": "toes_right", "kind": "relative_to_parent", "donor": ("BN_Toe_R_00", "BN_Toe_R_01", "BN_Toe_R_10", "BN_Toe_R_11", "BN_Toe_R_20", "BN_Toe_R_21", "BN_Toe_R_30", "BN_Toe_R_31"), "anchor": "Bip01_R_Foot", "region": "leg_right", "helper": True},
        {"name": "tail_left", "kind": "relative_to_parent", "donor": ("BN_Tai_L_01", "BN_Tai_L_02"), "anchor": "BN_Tai_01", "region": "tail", "helper": True},
        {"name": "jaw", "kind": "toward_region", "donor": ("BN_Jaw",), "parent": "Bip01_Head", "region": "neck_head", "helper": True},
    ),
    "leftRightPairs": (
        {"donor": ("BN_Wing_L_04", "BN_Wing_R_04"), "evidence": ("Bone_020", "Bone_017")},
        {"donor": ("Bip01_L_Foot", "Bip01_R_Foot"), "evidence": ("Bone_004", "Bone_008")},
    ),
    "requiredBranches": ("torso", "neck_head", "wing_left", "wing_right", "leg_left", "leg_right", "tail"),
    "extraTargetBones": (), "unsupportedRequiredArticulations": ("thunderbird_beak_and_feather_detail_not_separately_proven",),
    "actuation": (("shoulder_L", "BN_Wing_L_01", "wing_left", "wing_right"), ("midwing_L", "BN_Wing_L_03", "wing_left", "wing_right"), ("neck", "Bip01_Neck", "neck_head", "wing_right"), ("tail", "BN_Tai_01", "tail", "wing_left"), ("leg_L", "Bip01_L_Thigh", "leg_left", "leg_right")),
    "wholeBodyHubs": ("Hips", "Bip01_Spine", "Bip01_Spine1", "Bip01_Head", "BN_Wing_L_01", "BN_Wing_R_01", "Bip01_L_Thigh", "Bip01_R_Thigh"),
    "syntheticMotionOnly": True, "skinInitialization": "source_joint_map", "sourceJointMap": SOURCE_JOINT_MAP,
}


def get_profile() -> dict:
    return THUNDERBIRD_EAGLE
