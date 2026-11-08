"""CPU-only shape-preserving profile for the installed standard Ogre mesh."""
from __future__ import annotations

from pathlib import Path

from asset_profiles import MIXAMO_REGION_JOINTS, MIXAMO_REF_SEQ, MIXAMO_SPECIES
from paths import MESHY, VENDOR_DEMO


OGRE_MESH = MESHY / "h3_ogre_smartrigged.glb"
OGRE_SOURCE_IDLE = Path(
    "V:/SteamLibrary/steamapps/common/Heroes of Might and Magic Olden Era - Golden Era/"
    "BepInEx/plugins/OfflineUnlockMod/homm3_lab/h3_ogre/"
    "extracted_battle_source_12fps/COGRE.dir"
)

OGRE_REGION_BONES = {
    "torso": ("Bone_000", "Bone_001", "Bone_005", "Bone_004", "Bone_003", "Bone_002"),
    "neck_head": ("Bone_018", "Bone_017", "Bone_016"),
    "arm_left": ("Bone_028", "Bone_027", "Bone_026", "Bone_025", "Bone_024"),
    "arm_right": ("Bone_023", "Bone_022", "Bone_021", "Bone_020"),
    "weapon": ("Bone_019",),
    "leg_left": ("Bone_010", "Bone_009", "Bone_008", "Bone_007", "Bone_006"),
    "leg_right": ("Bone_015", "Bone_014", "Bone_013", "Bone_012", "Bone_011"),
}

OGRE_MIXAMO = {
    "assetId": "h3_ogre",
    "displayName": "Ogre",
    "mesh": OGRE_MESH,
    "expectedMeshSha256": "ce5ccf1fa0e76fc561924840f16c363e2fb567484ada545f4257b2f6f8fce76a",
    "donorKind": "obj",
    "donorRefSeq": MIXAMO_REF_SEQ,
    "donorCharacterDir": VENDOR_DEMO / "obj1k" / "characters" / MIXAMO_SPECIES,
    "donorBindSource": "ffs_bvh_capture_scale",
    "sourceIdleDir": OGRE_SOURCE_IDLE,
    "sourceIdleGroup": 2,
    "sourceIdleFrameCount": 8,
    "regionJoints": MIXAMO_REGION_JOINTS,
    "regionBones": OGRE_REGION_BONES,
    "headBone": "Bone_017",
    "neckBone": "Bone_018",
    "requireCompleteRegionCoverage": True,
    "rigidAttachments": ({"region": "weapon", "donorJoints": ("mixamorig:RightHand",), "reason": "Bone_019 is the terminal club tip and is held rigidly by the right hand"},),
    "hubs": {
        "mixamorig:Hips": "Bone_001",
        "mixamorig:Spine": "Bone_005",
        "mixamorig:Spine1": "Bone_004",
        "mixamorig:Spine2": "Bone_002",
    },
    "chains": (
        {"name": "neck", "kind": "polyline", "donor": ("mixamorig:Neck", "mixamorig:Head"), "evidence": ("Bone_018", "Bone_017")},
        {"name": "head_end", "kind": "relative_to_parent", "donor": ("mixamorig:HeadTop_End",), "anchor": "mixamorig:Head", "region": "neck_head", "helper": True},
        {"name": "arm_left", "kind": "polyline", "donor": ("mixamorig:LeftShoulder", "mixamorig:LeftArm", "mixamorig:LeftForeArm", "mixamorig:LeftHand"), "evidence": ("Bone_028", "Bone_027", "Bone_026", "Bone_025")},
        {"name": "arm_right", "kind": "polyline", "donor": ("mixamorig:RightShoulder", "mixamorig:RightArm", "mixamorig:RightForeArm", "mixamorig:RightHand"), "evidence": ("Bone_023", "Bone_022", "Bone_021", "Bone_020")},
        {"name": "leg_left", "kind": "polyline", "donor": ("mixamorig:LeftUpLeg", "mixamorig:LeftLeg", "mixamorig:LeftFoot", "mixamorig:LeftToeBase"), "evidence": ("Bone_010", "Bone_009", "Bone_008", "Bone_007")},
        {"name": "leg_right", "kind": "polyline", "donor": ("mixamorig:RightUpLeg", "mixamorig:RightLeg", "mixamorig:RightFoot", "mixamorig:RightToeBase"), "evidence": ("Bone_015", "Bone_014", "Bone_013", "Bone_012")},
        {"name": "toe_left", "kind": "relative_to_parent", "donor": ("mixamorig:LeftToe_End",), "anchor": "mixamorig:LeftToeBase", "region": "leg_left", "helper": True},
        {"name": "toe_right", "kind": "relative_to_parent", "donor": ("mixamorig:RightToe_End",), "anchor": "mixamorig:RightToeBase", "region": "leg_right", "helper": True},
    ),
    "leftRightPairs": (
        {"donor": ("mixamorig:LeftHand", "mixamorig:RightHand"), "evidence": ("Bone_025", "Bone_020")},
        {"donor": ("mixamorig:LeftFoot", "mixamorig:RightFoot"), "evidence": ("Bone_007", "Bone_012")},
    ),
    "requiredBranches": ("torso", "neck_head", "arm_left", "arm_right", "leg_left", "leg_right"),
    "extraTargetBones": ("Bone_006", "Bone_011", "Bone_016", "Bone_019", "Bone_020", "Bone_021", "Bone_022", "Bone_024", "Bone_025", "Bone_026", "Bone_027", "Bone_028"),
    "unsupportedRequiredArticulations": ("Ogre hand/claw detail is not separately articulated; Bone_019 club tip is rigidly owned by RightHand",),
    "actuation": (
        ("shoulder_L", "mixamorig:LeftArm", "arm_left", "arm_right"),
        ("forearm_L", "mixamorig:LeftForeArm", "arm_left", "arm_right"),
        ("thigh_L", "mixamorig:LeftUpLeg", "leg_left", "leg_right"),
        ("spine", "mixamorig:Spine1", "torso", "leg_right"),
    ),
    "wholeBodyHubs": ("mixamorig:Hips", "mixamorig:Spine2", "mixamorig:Head", "mixamorig:LeftShoulder", "mixamorig:RightShoulder", "mixamorig:LeftUpLeg", "mixamorig:RightUpLeg"),
    "syntheticMotionOnly": True,
    "skinInitialization": "source_joint_map",
    "anatomyEvidence": "CPU rest-world and multiangle mesh audit: positive-X left limbs, negative-X right limbs; Bone_020 is the right wrist and Bone_019 the upturned club endpoint, rigidly owned by RightHand. Generated preparation only.",
}

OGRE_MIXAMO["sourceJointMap"] = {
    "Bone_000": "mixamorig:Hips", "Bone_001": "mixamorig:Hips",
    "Bone_005": "mixamorig:Spine", "Bone_004": "mixamorig:Spine1", "Bone_003": "mixamorig:Spine2", "Bone_002": "mixamorig:Spine2",
    "Bone_018": "mixamorig:Neck", "Bone_017": "mixamorig:Head", "Bone_016": "mixamorig:Head",
    "Bone_023": "mixamorig:RightShoulder", "Bone_022": "mixamorig:RightArm", "Bone_021": "mixamorig:RightForeArm", "Bone_020": "mixamorig:RightHand", "Bone_019": "mixamorig:RightHand",
    "Bone_028": "mixamorig:LeftShoulder", "Bone_027": "mixamorig:LeftArm", "Bone_026": "mixamorig:LeftForeArm", "Bone_025": "mixamorig:LeftHand", "Bone_024": "mixamorig:LeftHand",
    "Bone_010": "mixamorig:LeftUpLeg", "Bone_009": "mixamorig:LeftLeg", "Bone_008": "mixamorig:LeftFoot", "Bone_007": "mixamorig:LeftToeBase", "Bone_006": "mixamorig:LeftToeBase",
    "Bone_015": "mixamorig:RightUpLeg", "Bone_014": "mixamorig:RightLeg", "Bone_013": "mixamorig:RightFoot", "Bone_012": "mixamorig:RightToeBase", "Bone_011": "mixamorig:RightToeBase",
}


def get_profile() -> dict:
    return OGRE_MIXAMO
