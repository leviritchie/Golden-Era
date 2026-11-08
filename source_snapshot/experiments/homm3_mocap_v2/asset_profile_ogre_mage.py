"""Ogre Mage fixed-Mixamo preparation profile (CPU-only asset evidence)."""
from __future__ import annotations

from asset_profiles import MIXAMO_REGION_JOINTS, MIXAMO_REF_SEQ, MIXAMO_SPECIES
from paths import MESHY, VENDOR_DEMO


OGRE_MAGE_MIXAMO = {
    "assetId": "h3_ogre_mage",
    "displayName": "Ogre Mage",
    "mesh": MESHY / "h3_ogre_mage_smartrigged.glb",
    "expectedMeshSha256": "25d7c5748928a32b6e8b4bf2ee8d7a7570cd87094fa4a07ea161f99487957066",
    "donorKind": "obj",
    "donorRefSeq": MIXAMO_REF_SEQ,
    "donorCharacterDir": VENDOR_DEMO / "obj1k" / "characters" / MIXAMO_SPECIES,
    "donorBindSource": "ffs_bvh_capture_scale",
    "sourceIdleDir": "V:/Games/Olden Era Playtest Tweak/artifacts/homm3_mocap_v2/skin_mesh_pilot/ogre_mage/source_identity_v1/extracted/cogmag.dir",
    "sourceIdleGroup": 2,
    "sourceIdleFrameCount": 8,
    "regionJoints": MIXAMO_REGION_JOINTS,
    # Capture package names verified on the isolated linked-master pilot.
    # These legacy canonical axes do not override accepted static registration;
    # generated animation and the new T2 skin are not yet visually validated.
    "captureBind": {
        "headJoint": "mixamorig:Head",
        "leftJoint": "mixamorig:LeftShoulder",
        "rightJoint": "mixamorig:RightShoulder",
        "meshBodyAxis": (0.0, 1.0, 0.0),
        "meshSecondAxis": (0.0, 0.0, 1.0),
        "skinFrozenRegions": (),
    },
    "regionBones": {
        "torso": ("Hips", "Spine", "Spine01", "Spine02"),
        "neck_head": ("neck", "Head", "head_end", "headfront"),
        "arm_left": ("LeftShoulder", "LeftArm", "LeftForeArm", "LeftHand"),
        "arm_right": ("RightShoulder", "RightArm", "RightForeArm", "RightHand"),
        "leg_left": ("LeftUpLeg", "LeftLeg", "LeftFoot", "LeftToeBase"),
        "leg_right": ("RightUpLeg", "RightLeg", "RightFoot", "RightToeBase"),
    },
    "beakFromHeadQuantile": None,
    "headBone": "Head",
    "neckBone": "neck",
    "rigidAttachments": (),
    "hubs": {
        "mixamorig:Hips": "Hips",
        "mixamorig:Spine": "Spine02",
        "mixamorig:Spine1": "Spine01",
        "mixamorig:Spine2": "Spine",
    },
    "chains": (
        {"name": "neck", "kind": "polyline", "donor": ("mixamorig:Neck", "mixamorig:Head"), "evidence": ("neck", "Head")},
        {"name": "head_end", "kind": "relative_to_parent", "donor": ("mixamorig:HeadTop_End",), "anchor": "mixamorig:Head", "region": "neck_head", "helper": True},
        {"name": "arm_left", "kind": "polyline", "donor": ("mixamorig:LeftShoulder", "mixamorig:LeftArm", "mixamorig:LeftForeArm", "mixamorig:LeftHand"), "evidence": ("LeftShoulder", "LeftArm", "LeftForeArm", "LeftHand")},
        {"name": "arm_right", "kind": "polyline", "donor": ("mixamorig:RightShoulder", "mixamorig:RightArm", "mixamorig:RightForeArm", "mixamorig:RightHand"), "evidence": ("RightShoulder", "RightArm", "RightForeArm", "RightHand")},
        {"name": "leg_left", "kind": "polyline", "donor": ("mixamorig:LeftUpLeg", "mixamorig:LeftLeg", "mixamorig:LeftFoot", "mixamorig:LeftToeBase"), "evidence": ("LeftUpLeg", "LeftLeg", "LeftFoot", "LeftToeBase")},
        {"name": "leg_right", "kind": "polyline", "donor": ("mixamorig:RightUpLeg", "mixamorig:RightLeg", "mixamorig:RightFoot", "mixamorig:RightToeBase"), "evidence": ("RightUpLeg", "RightLeg", "RightFoot", "RightToeBase")},
        {"name": "toe_left", "kind": "relative_to_parent", "donor": ("mixamorig:LeftToe_End",), "anchor": "mixamorig:LeftToeBase", "region": "leg_left", "helper": True},
        {"name": "toe_right", "kind": "relative_to_parent", "donor": ("mixamorig:RightToe_End",), "anchor": "mixamorig:RightToeBase", "region": "leg_right", "helper": True},
    ),
    "leftRightPairs": (
        {"donor": ("mixamorig:LeftHand", "mixamorig:RightHand"), "evidence": ("LeftHand", "RightHand")},
        {"donor": ("mixamorig:LeftFoot", "mixamorig:RightFoot"), "evidence": ("LeftFoot", "RightFoot")},
    ),
    "requiredBranches": ("torso", "neck_head", "arm_left", "arm_right", "leg_left", "leg_right"),
    "extraTargetBones": ("head_end", "headfront"),
    "unsupportedRequiredArticulations": ("ogre_mage_hand_detail_is_not_separately_articulated",),
    "actuation": (
        ("shoulder_L", "mixamorig:LeftArm", "arm_left", "arm_right"),
        ("forearm_L", "mixamorig:LeftForeArm", "arm_left", "arm_right"),
        ("thigh_L", "mixamorig:LeftUpLeg", "leg_left", "leg_right"),
        ("spine", "mixamorig:Spine1", "torso", "leg_right"),
    ),
    "wholeBodyHubs": ("mixamorig:Hips", "mixamorig:Spine2", "mixamorig:Head", "mixamorig:LeftShoulder", "mixamorig:RightShoulder", "mixamorig:LeftUpLeg", "mixamorig:RightUpLeg"),
    "syntheticMotionOnly": True,
    "sourceJointMap": {
        "Hips": "mixamorig:Hips", "Spine02": "mixamorig:Spine", "Spine01": "mixamorig:Spine1", "Spine": "mixamorig:Spine2",
        "neck": "mixamorig:Neck", "Head": "mixamorig:Head", "head_end": "mixamorig:HeadTop_End",
        "LeftShoulder": "mixamorig:LeftShoulder", "LeftArm": "mixamorig:LeftArm", "LeftForeArm": "mixamorig:LeftForeArm", "LeftHand": "mixamorig:LeftHand",
        "RightShoulder": "mixamorig:RightShoulder", "RightArm": "mixamorig:RightArm", "RightForeArm": "mixamorig:RightForeArm", "RightHand": "mixamorig:RightHand",
        "LeftUpLeg": "mixamorig:LeftUpLeg", "LeftLeg": "mixamorig:LeftLeg", "LeftFoot": "mixamorig:LeftFoot", "LeftToeBase": "mixamorig:LeftToeBase", "LeftToe_End": "mixamorig:LeftToe_End",
        "RightUpLeg": "mixamorig:RightUpLeg", "RightLeg": "mixamorig:RightLeg", "RightFoot": "mixamorig:RightFoot", "RightToeBase": "mixamorig:RightToeBase", "RightToe_End": "mixamorig:RightToe_End",
    },
    "skinInitialization": "source_joint_map",
}

OGRE_MAGE_MIXAMO["sourceJointMap"] = {
    "Hips": "mixamorig:Hips", "Spine02": "mixamorig:Spine", "Spine01": "mixamorig:Spine1", "Spine": "mixamorig:Spine2",
    "neck": "mixamorig:Neck", "Head": "mixamorig:Head", "head_end": "mixamorig:HeadTop_End", "headfront": "mixamorig:Head",
    "LeftShoulder": "mixamorig:LeftShoulder", "LeftArm": "mixamorig:LeftArm", "LeftForeArm": "mixamorig:LeftForeArm", "LeftHand": "mixamorig:LeftHand",
    "RightShoulder": "mixamorig:RightShoulder", "RightArm": "mixamorig:RightArm", "RightForeArm": "mixamorig:RightForeArm", "RightHand": "mixamorig:RightHand",
    "LeftUpLeg": "mixamorig:LeftUpLeg", "LeftLeg": "mixamorig:LeftLeg", "LeftFoot": "mixamorig:LeftFoot", "LeftToeBase": "mixamorig:LeftToeBase",
    "RightUpLeg": "mixamorig:RightUpLeg", "RightLeg": "mixamorig:RightLeg", "RightFoot": "mixamorig:RightFoot", "RightToeBase": "mixamorig:RightToeBase",
}


def get_profile() -> dict:
    return OGRE_MAGE_MIXAMO
