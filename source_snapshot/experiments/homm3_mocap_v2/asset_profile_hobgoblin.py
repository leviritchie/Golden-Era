"""Hobgoblin shape-preserving profile using the installed 25-joint Mixamo donor."""
from __future__ import annotations

from pathlib import Path

from asset_profiles import MIXAMO_REGION_JOINTS, MIXAMO_REF_SEQ, MIXAMO_SPECIES
from paths import MESHY, VENDOR_DEMO


HOBGOBLIN_MIXAMO = {
    "assetId": "h3_hobgoblin",
    "displayName": "Hobgoblin",
    "mesh": MESHY / "h3_hobgoblin_smartrigged_rigidized.glb",
    "expectedMeshSha256": "6abe1d66e94e8b04848052bcd98f43a4204144a7234431c58ae56a6a06c4ba0a",
    "donorKind": "obj",
    "donorRefSeq": MIXAMO_REF_SEQ,
    "donorCharacterDir": VENDOR_DEMO / "obj1k" / "characters" / MIXAMO_SPECIES,
    "donorBindSource": "ffs_bvh_capture_scale",
    "regionJoints": MIXAMO_REGION_JOINTS,
    "regionBones": {
        "torso": ("Bone_000", "Bone_001", "Bone_004", "Bone_003", "Bone_002"),
        "neck_head": ("Bone_017", "Bone_016", "Bone_015"),
        "arm_left": ("Bone_022", "Bone_021", "Bone_020", "Bone_019", "Bone_018", "Bone_030", "Bone_033", "Bone_036", "Bone_029", "Bone_032", "Bone_035", "Bone_034", "Bone_031", "Bone_028"),
        "arm_right": ("Bone_027", "Bone_026", "Bone_025", "Bone_024", "Bone_039", "Bone_042", "Bone_045", "Bone_038", "Bone_041", "Bone_044", "Bone_037", "Bone_040", "Bone_043"),
        "weapon": ("Bone_023",),
        "leg_left": ("Bone_014", "Bone_013", "Bone_012", "Bone_011", "Bone_010"),
        "leg_right": ("Bone_009", "Bone_008", "Bone_007", "Bone_006", "Bone_005"),
    },
    "beakFromHeadQuantile": None,
    "headBone": "Bone_016",
    "requireCompleteRegionCoverage": True,
    "neckBone": "Bone_017",
    "rigidAttachments": (
        {"region": "weapon", "donorJoints": ("mixamorig:RightHand",), "reason": "mace is a rigid prop, not a mocap joint"},
    ),
    "hubs": {
        "mixamorig:Hips": "Bone_001",
        "mixamorig:Spine": "Bone_004",
        "mixamorig:Spine1": "Bone_003",
        "mixamorig:Spine2": "Bone_002",
    },
    "chains": (
        {"name": "neck", "kind": "polyline", "donor": ("mixamorig:Neck", "mixamorig:Head"), "evidence": ("Bone_017", "Bone_016")},
        {"name": "head_end", "kind": "relative_to_parent", "donor": ("mixamorig:HeadTop_End",), "anchor": "mixamorig:Head", "region": "neck_head", "helper": True},
        {"name": "arm_left", "kind": "polyline", "donor": ("mixamorig:LeftShoulder", "mixamorig:LeftArm", "mixamorig:LeftForeArm", "mixamorig:LeftHand"), "evidence": ("Bone_022", "Bone_021", "Bone_020", "Bone_019")},
        {"name": "arm_right", "kind": "polyline", "donor": ("mixamorig:RightShoulder", "mixamorig:RightArm", "mixamorig:RightForeArm", "mixamorig:RightHand"), "evidence": ("Bone_027", "Bone_026", "Bone_025", "Bone_024")},
        {"name": "leg_left", "kind": "polyline", "donor": ("mixamorig:LeftUpLeg", "mixamorig:LeftLeg", "mixamorig:LeftFoot", "mixamorig:LeftToeBase"), "evidence": ("Bone_014", "Bone_013", "Bone_012", "Bone_011")},
        {"name": "leg_right", "kind": "polyline", "donor": ("mixamorig:RightUpLeg", "mixamorig:RightLeg", "mixamorig:RightFoot", "mixamorig:RightToeBase"), "evidence": ("Bone_009", "Bone_008", "Bone_007", "Bone_006")},
        {"name": "toe_left", "kind": "relative_to_parent", "donor": ("mixamorig:LeftToe_End",), "anchor": "mixamorig:LeftToeBase", "region": "leg_left", "helper": True},
        {"name": "toe_right", "kind": "relative_to_parent", "donor": ("mixamorig:RightToe_End",), "anchor": "mixamorig:RightToeBase", "region": "leg_right", "helper": True},
    ),
    "leftRightPairs": (
        {"donor": ("mixamorig:LeftHand", "mixamorig:RightHand"), "evidence": ("Bone_019", "Bone_024")},
        {"donor": ("mixamorig:LeftFoot", "mixamorig:RightFoot"), "evidence": ("Bone_011", "Bone_006")},
    ),
    "requiredBranches": ("torso", "neck_head", "arm_left", "arm_right", "leg_left", "leg_right"),
    "extraTargetBones": ("Bone_005", "Bone_010", "Bone_015", "Bone_018", "Bone_023", "Bone_028", "Bone_029", "Bone_031", "Bone_032", "Bone_033", "Bone_034", "Bone_035", "Bone_036", "Bone_037", "Bone_038", "Bone_039", "Bone_040", "Bone_041", "Bone_042", "Bone_043", "Bone_044", "Bone_045"),
    "unsupportedRequiredArticulations": (
        "hobgoblin_fingers_and_mace_chain_are_rigid_prop_detail_not_mixamo_mocap_joints",
    ),
    "actuation": (
        ("shoulder_L", "mixamorig:LeftArm", "arm_left", "arm_right"),
        ("forearm_L", "mixamorig:LeftForeArm", "arm_left", "arm_right"),
        ("thigh_L", "mixamorig:LeftUpLeg", "leg_left", "leg_right"),
        ("spine", "mixamorig:Spine1", "torso", "leg_right"),
    ),
    "wholeBodyHubs": (
        "mixamorig:Hips", "mixamorig:Spine2", "mixamorig:Head",
        "mixamorig:LeftShoulder", "mixamorig:RightShoulder",
        "mixamorig:LeftUpLeg", "mixamorig:RightUpLeg",
    ),
    "syntheticMotionOnly": True,
}


HOBGOBLIN_MIXAMO["skinInitialization"] = "source_joint_map"
HOBGOBLIN_MIXAMO["sourceJointMap"] = {
    **{bone: "mixamorig:Head" for bone in HOBGOBLIN_MIXAMO["regionBones"]["neck_head"]},
    **{bone: "mixamorig:LeftHand" for bone in HOBGOBLIN_MIXAMO["regionBones"]["arm_left"]},
    **{bone: "mixamorig:RightHand" for bone in HOBGOBLIN_MIXAMO["regionBones"]["arm_right"]},
    **{bone: "mixamorig:LeftToeBase" for bone in HOBGOBLIN_MIXAMO["regionBones"]["leg_left"]},
    **{bone: "mixamorig:RightToeBase" for bone in HOBGOBLIN_MIXAMO["regionBones"]["leg_right"]},
    "Bone_023": "mixamorig:RightHand",
    "Bone_000": "mixamorig:Hips", "Bone_001": "mixamorig:Hips",
    "Bone_004": "mixamorig:Spine", "Bone_003": "mixamorig:Spine1", "Bone_002": "mixamorig:Spine2",
    "Bone_017": "mixamorig:Neck",
    "Bone_022": "mixamorig:LeftShoulder", "Bone_021": "mixamorig:LeftArm", "Bone_020": "mixamorig:LeftForeArm",
    "Bone_027": "mixamorig:RightShoulder", "Bone_026": "mixamorig:RightArm", "Bone_025": "mixamorig:RightForeArm",
    "Bone_014": "mixamorig:LeftUpLeg", "Bone_013": "mixamorig:LeftLeg", "Bone_012": "mixamorig:LeftFoot",
    "Bone_009": "mixamorig:RightUpLeg", "Bone_008": "mixamorig:RightLeg", "Bone_007": "mixamorig:RightFoot",
}


def get_profile() -> dict:
    return HOBGOBLIN_MIXAMO


if __name__ == "__main__":
    print(HOBGOBLIN_MIXAMO)
