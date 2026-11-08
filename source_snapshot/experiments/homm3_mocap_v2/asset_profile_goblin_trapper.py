"""Goblin Trapper source-mapped profile for the fixed Mixamo mocap donor."""
from __future__ import annotations

from pathlib import Path

from asset_profiles import MIXAMO_REGION_JOINTS, MIXAMO_REF_SEQ, MIXAMO_SPECIES
from paths import MESHY, VENDOR_DEMO


MESH = MESHY / "toa_goblin_trapper_smartrigged.glb"
MESH_SHA256 = "c5425001ab73fafb3c2406578dcbdfd8a4ca2ddc476f05069799ba633357f904"

_LEFT_ARM = (
    "Bone_027", "Bone_026", "Bone_025", "Bone_024", "Bone_023",
    "Bone_050", "Bone_054", "Bone_058", "Bone_062",
    "Bone_049", "Bone_053", "Bone_057", "Bone_061",
    "Bone_048", "Bone_052", "Bone_056", "Bone_060",
    "Bone_047", "Bone_051", "Bone_055", "Bone_059",
)
_RIGHT_ARM = (
    "Bone_032", "Bone_031", "Bone_030", "Bone_029", "Bone_028",
    "Bone_066", "Bone_070", "Bone_074", "Bone_078",
    "Bone_065", "Bone_069", "Bone_073", "Bone_077",
    "Bone_064", "Bone_068", "Bone_072", "Bone_076",
    "Bone_063", "Bone_067", "Bone_071", "Bone_075",
)
_TORSO = ("Bone_000", "Bone_001", "Bone_003", "Bone_005", "Bone_004", "Bone_002", "Bone_009", "Bone_008", "Bone_007", "Bone_006")
_HEAD = ("Bone_022", "Bone_021", "Bone_020", "Bone_035", "Bone_037", "Bone_040", "Bone_043", "Bone_046", "Bone_034", "Bone_036", "Bone_039", "Bone_042", "Bone_045", "Bone_033", "Bone_038", "Bone_041", "Bone_044")
_LEFT_LEG = ("Bone_019", "Bone_018", "Bone_017", "Bone_016", "Bone_015")
_RIGHT_LEG = ("Bone_014", "Bone_013", "Bone_012", "Bone_011", "Bone_010")

REGION_BONES = {
    "torso": _TORSO,
    "neck_head": _HEAD,
    "arm_left": _LEFT_ARM,
    "arm_right": _RIGHT_ARM,
    "leg_left": _LEFT_LEG,
    "leg_right": _RIGHT_LEG,
}


def _map_bones() -> dict[str, str]:
    mapping = {bone: "mixamorig:Hips" for bone in ("Bone_000", "Bone_001")}
    mapping.update({"Bone_003": "mixamorig:Spine", "Bone_005": "mixamorig:Spine1", "Bone_004": "mixamorig:Spine1", "Bone_002": "mixamorig:Spine2"})
    mapping.update({"Bone_009": "mixamorig:Spine", "Bone_008": "mixamorig:Spine1", "Bone_007": "mixamorig:Spine2", "Bone_006": "mixamorig:Spine2"})
    mapping.update({bone: "mixamorig:Head" for bone in _HEAD})
    mapping["Bone_022"] = "mixamorig:Neck"
    mapping.update({bone: donor for bone, donor in zip(_LEFT_ARM, ("mixamorig:LeftShoulder", "mixamorig:LeftArm", "mixamorig:LeftForeArm", "mixamorig:LeftHand", "mixamorig:LeftHand") + ("mixamorig:LeftHand",) * 16)})
    mapping.update({bone: donor for bone, donor in zip(_RIGHT_ARM, ("mixamorig:RightShoulder", "mixamorig:RightArm", "mixamorig:RightForeArm", "mixamorig:RightHand", "mixamorig:RightHand") + ("mixamorig:RightHand",) * 16)})
    mapping.update({bone: donor for bone, donor in zip(_LEFT_LEG, ("mixamorig:LeftUpLeg", "mixamorig:LeftLeg", "mixamorig:LeftFoot", "mixamorig:LeftToeBase", "mixamorig:LeftToeBase"))})
    mapping.update({bone: donor for bone, donor in zip(_RIGHT_LEG, ("mixamorig:RightUpLeg", "mixamorig:RightLeg", "mixamorig:RightFoot", "mixamorig:RightToeBase", "mixamorig:RightToeBase"))})
    return mapping


GOBLIN_TRAPPER_MIXAMO = {
    "assetId": "h3_goblin_trapper",
    "displayName": "Goblin Trapper",
    "mesh": MESH,
    "expectedMeshSha256": MESH_SHA256,
    "donorKind": "obj",
    "donorRefSeq": MIXAMO_REF_SEQ,
    "donorCharacterDir": VENDOR_DEMO / "obj1k" / "characters" / MIXAMO_SPECIES,
    "donorBindSource": "ffs_bvh_capture_scale",
    "regionJoints": MIXAMO_REGION_JOINTS,
    "regionBones": REGION_BONES,
    "beakFromHeadQuantile": None,
    "headBone": "Bone_021",
    "neckBone": "Bone_022",
    "requireCompleteRegionCoverage": True,
    "rigidAttachments": (),
    "hubs": {
        "mixamorig:Hips": "Bone_001",
        "mixamorig:Spine": "Bone_009",
        "mixamorig:Spine1": "Bone_008",
        "mixamorig:Spine2": "Bone_007",
    },
    "chains": (
        {"name": "neck", "kind": "polyline", "donor": ("mixamorig:Neck", "mixamorig:Head"), "evidence": ("Bone_022", "Bone_021")},
        {"name": "head_end", "kind": "relative_to_parent", "donor": ("mixamorig:HeadTop_End",), "anchor": "mixamorig:Head", "region": "neck_head", "helper": True},
        {"name": "arm_left", "kind": "polyline", "donor": ("mixamorig:LeftShoulder", "mixamorig:LeftArm", "mixamorig:LeftForeArm", "mixamorig:LeftHand"), "evidence": ("Bone_027", "Bone_026", "Bone_025", "Bone_024")},
        {"name": "arm_right", "kind": "polyline", "donor": ("mixamorig:RightShoulder", "mixamorig:RightArm", "mixamorig:RightForeArm", "mixamorig:RightHand"), "evidence": ("Bone_032", "Bone_031", "Bone_030", "Bone_029")},
        {"name": "leg_left", "kind": "polyline", "donor": ("mixamorig:LeftUpLeg", "mixamorig:LeftLeg", "mixamorig:LeftFoot", "mixamorig:LeftToeBase"), "evidence": ("Bone_019", "Bone_018", "Bone_017", "Bone_016")},
        {"name": "leg_right", "kind": "polyline", "donor": ("mixamorig:RightUpLeg", "mixamorig:RightLeg", "mixamorig:RightFoot", "mixamorig:RightToeBase"), "evidence": ("Bone_014", "Bone_013", "Bone_012", "Bone_011")},
        {"name": "toe_left", "kind": "relative_to_parent", "donor": ("mixamorig:LeftToe_End",), "anchor": "mixamorig:LeftToeBase", "region": "leg_left", "helper": True},
        {"name": "toe_right", "kind": "relative_to_parent", "donor": ("mixamorig:RightToe_End",), "anchor": "mixamorig:RightToeBase", "region": "leg_right", "helper": True},
    ),
    "leftRightPairs": (
        {"donor": ("mixamorig:LeftHand", "mixamorig:RightHand"), "evidence": ("Bone_024", "Bone_029")},
        {"donor": ("mixamorig:LeftFoot", "mixamorig:RightFoot"), "evidence": ("Bone_017", "Bone_012")},
    ),
    "requiredBranches": ("torso", "neck_head", "arm_left", "arm_right", "leg_left", "leg_right"),
    "extraTargetBones": tuple(bone for bones in REGION_BONES.values() for bone in bones if bone not in {"Bone_000", "Bone_001", "Bone_003", "Bone_005", "Bone_004", "Bone_002", "Bone_009", "Bone_008", "Bone_007", "Bone_006", "Bone_022", "Bone_021", "Bone_020", "Bone_027", "Bone_026", "Bone_025", "Bone_024", "Bone_032", "Bone_031", "Bone_030", "Bone_029", "Bone_014", "Bone_013", "Bone_012", "Bone_011", "Bone_019", "Bone_018", "Bone_017", "Bone_016"}),
    "unsupportedRequiredArticulations": ("goblin_trapper_finger_branches_are_source_detail_not_fixed_mocap_joints",),
    "actuation": (("shoulder_L", "mixamorig:LeftArm", "arm_left", "arm_right"), ("forearm_L", "mixamorig:LeftForeArm", "arm_left", "arm_right"), ("thigh_L", "mixamorig:LeftUpLeg", "leg_left", "leg_right"), ("spine", "mixamorig:Spine1", "torso", "leg_right")),
    "wholeBodyHubs": ("mixamorig:Hips", "mixamorig:Spine2", "mixamorig:Head", "mixamorig:LeftShoulder", "mixamorig:RightShoulder", "mixamorig:LeftUpLeg", "mixamorig:RightUpLeg"),
    "syntheticMotionOnly": True,
    "skinInitialization": "source_joint_map",
    "sourceJointMap": _map_bones(),
}


def get_profile() -> dict:
    return GOBLIN_TRAPPER_MIXAMO
