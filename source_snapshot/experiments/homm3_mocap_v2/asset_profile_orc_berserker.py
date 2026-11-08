"""CPU-audited ToA Orc Berserker profile for the fixed Mixamo mocap donor."""
from __future__ import annotations

from asset_profiles import MIXAMO_REGION_JOINTS, MIXAMO_REF_SEQ, MIXAMO_SPECIES
from paths import MESHY, VENDOR_DEMO

MESH = MESHY / "toa_orc_berserker_smartrigged.glb"
REGION_BONES = {
    "torso": ("Bone_000", "Bone_001", "Bone_005", "Bone_004", "Bone_003", "Bone_002"),
    "neck_head": ("Bone_018", "Bone_017", "Bone_016"),
    "arm_left": ("Bone_023", "Bone_022", "Bone_021", "Bone_020", "Bone_019"),
    "arm_right": ("Bone_028", "Bone_027", "Bone_026", "Bone_025", "Bone_024"),
    "leg_left": ("Bone_015", "Bone_014", "Bone_013", "Bone_012", "Bone_011"),
    "leg_right": ("Bone_010", "Bone_009", "Bone_008", "Bone_007", "Bone_006"),
}


def _mapped() -> dict[str, str]:
    return {
        "Bone_000": "mixamorig:Hips", "Bone_001": "mixamorig:Hips",
        "Bone_005": "mixamorig:Spine", "Bone_004": "mixamorig:Spine1", "Bone_003": "mixamorig:Spine2", "Bone_002": "mixamorig:Spine2",
        "Bone_018": "mixamorig:Neck", "Bone_017": "mixamorig:Head", "Bone_016": "mixamorig:HeadTop_End",
        "Bone_023": "mixamorig:LeftShoulder", "Bone_022": "mixamorig:LeftArm", "Bone_021": "mixamorig:LeftForeArm", "Bone_020": "mixamorig:LeftHand", "Bone_019": "mixamorig:LeftHand",
        "Bone_028": "mixamorig:RightShoulder", "Bone_027": "mixamorig:RightArm", "Bone_026": "mixamorig:RightForeArm", "Bone_025": "mixamorig:RightHand", "Bone_024": "mixamorig:RightHand",
        "Bone_015": "mixamorig:LeftUpLeg", "Bone_014": "mixamorig:LeftLeg", "Bone_013": "mixamorig:LeftFoot", "Bone_012": "mixamorig:LeftToeBase", "Bone_011": "mixamorig:LeftToeBase",
        "Bone_010": "mixamorig:RightUpLeg", "Bone_009": "mixamorig:RightLeg", "Bone_008": "mixamorig:RightFoot", "Bone_007": "mixamorig:RightToeBase", "Bone_006": "mixamorig:RightToeBase",
    }


ORC_BERSERKER_MIXAMO = {
    "assetId": "h3_orc_berserker", "displayName": "Orc Berserker", "mesh": MESH,
    "expectedMeshSha256": "323f0f0e24954914ac870de9c13c13db85b730edff8985288661005cde3856ff",
    "donorKind": "obj", "donorRefSeq": MIXAMO_REF_SEQ,
    "donorCharacterDir": VENDOR_DEMO / "obj1k" / "characters" / MIXAMO_SPECIES,
    "donorBindSource": "ffs_bvh_capture_scale", "regionJoints": MIXAMO_REGION_JOINTS,
    "regionBones": REGION_BONES, "headBone": "Bone_017", "neckBone": "Bone_018",
    "requireCompleteRegionCoverage": True, "sourceJointMap": _mapped(), "rigidAttachments": (),
    "skinInitialization": "source_joint_map",
    "hubs": {"mixamorig:Hips": "Bone_001", "mixamorig:Spine": "Bone_005", "mixamorig:Spine1": "Bone_004", "mixamorig:Spine2": "Bone_003"},
    "chains": (
        {"name": "neck", "kind": "polyline", "donor": ("mixamorig:Neck", "mixamorig:Head"), "evidence": ("Bone_018", "Bone_017")},
        {"name": "head_end", "kind": "relative_to_parent", "donor": ("mixamorig:HeadTop_End",), "anchor": "mixamorig:Head", "region": "neck_head", "helper": True},
        {"name": "arm_left", "kind": "polyline", "donor": ("mixamorig:LeftShoulder", "mixamorig:LeftArm", "mixamorig:LeftForeArm", "mixamorig:LeftHand"), "evidence": ("Bone_023", "Bone_022", "Bone_021", "Bone_020")},
        {"name": "arm_right", "kind": "polyline", "donor": ("mixamorig:RightShoulder", "mixamorig:RightArm", "mixamorig:RightForeArm", "mixamorig:RightHand"), "evidence": ("Bone_028", "Bone_027", "Bone_026", "Bone_025")},
        {"name": "leg_left", "kind": "polyline", "donor": ("mixamorig:LeftUpLeg", "mixamorig:LeftLeg", "mixamorig:LeftFoot", "mixamorig:LeftToeBase"), "evidence": ("Bone_015", "Bone_014", "Bone_013", "Bone_012")},
        {"name": "leg_right", "kind": "polyline", "donor": ("mixamorig:RightUpLeg", "mixamorig:RightLeg", "mixamorig:RightFoot", "mixamorig:RightToeBase"), "evidence": ("Bone_010", "Bone_009", "Bone_008", "Bone_007")},
        {"name": "toe_left", "kind": "relative_to_parent", "donor": ("mixamorig:LeftToe_End",), "anchor": "mixamorig:LeftToeBase", "region": "leg_left", "helper": True},
        {"name": "toe_right", "kind": "relative_to_parent", "donor": ("mixamorig:RightToe_End",), "anchor": "mixamorig:RightToeBase", "region": "leg_right", "helper": True},
    ),
    "leftRightPairs": ({"donor": ("mixamorig:LeftHand", "mixamorig:RightHand"), "evidence": ("Bone_020", "Bone_025")}, {"donor": ("mixamorig:LeftFoot", "mixamorig:RightFoot"), "evidence": ("Bone_013", "Bone_008")}),
    "requiredBranches": ("torso", "neck_head", "arm_left", "arm_right", "leg_left", "leg_right"),
    "extraTargetBones": (), "unsupportedRequiredArticulations": ("berserker_terminal_hand_detail_has_no_independent_mocap_joint",),
    "actuation": (("shoulder_L", "mixamorig:LeftArm", "arm_left", "arm_right"), ("forearm_L", "mixamorig:LeftForeArm", "arm_left", "arm_right"), ("thigh_L", "mixamorig:LeftUpLeg", "leg_left", "leg_right"), ("spine", "mixamorig:Spine1", "torso", "leg_right")),
    "wholeBodyHubs": ("mixamorig:Hips", "mixamorig:Spine2", "mixamorig:Head", "mixamorig:LeftShoulder", "mixamorig:RightShoulder", "mixamorig:LeftUpLeg", "mixamorig:RightUpLeg"),
    "syntheticMotionOnly": True, "visualAcceptance": "unreviewed_candidate",
}


def get_profile() -> dict:
    return ORC_BERSERKER_MIXAMO
