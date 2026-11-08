"""CPU-audited profile for the Orc Chieftain SmartRig mesh.

The GLB has a 66-joint SmartRig.  Bone names are used as the only identity;
numeric skin-joint order is deliberately not used as an anatomical shortcut.
The distal hand branches are retained in the hand region.  No rigid weapon
attachment is declared because this mesh audit found no independently
identified prop bone.
"""
from __future__ import annotations

from pathlib import Path
from asset_profiles import MIXAMO_REF_SEQ, MIXAMO_SPECIES, MIXAMO_REGION_JOINTS
from paths import MESHY, VENDOR_DEMO

ORC_CHIEFTAIN_MESH = MESHY / "h3_orc_chieftain_smartrigged.glb"
ORC_CHIEFTAIN_SOURCE_IDLE = Path(
    "V:/SteamLibrary/steamapps/common/Heroes of Might and Magic Olden Era - Golden Era"
    "/BepInEx/plugins/OfflineUnlockMod/homm3_lab/h3_orc_chieftain"
    "/extracted_battle_source_12fps/CORCCH.dir"
)
ORC_CHIEFTAIN_SHA256 = "6ff8c327efddf43528beb4d2e59616f25cd7ec2f6776e4de6ed9e1b10e5642cb"

# The four short branches below the pelvis are the two sides' paired lower
# limb chains.  Positive X is left and negative X is right in rest-world data.
REGION_BONES = {
    "torso": ("Bone_000", "Bone_001", "Bone_004", "Bone_003", "Bone_002"),
    "neck_head": ("Bone_023", "Bone_022", "Bone_021"),
    "leg_right": ("Bone_007", "Bone_006", "Bone_005", "Bone_012", "Bone_011", "Bone_015", "Bone_014", "Bone_013"),
    "leg_left": ("Bone_010", "Bone_009", "Bone_008", "Bone_020", "Bone_019", "Bone_018", "Bone_017", "Bone_016"),
    "arm_right": ("Bone_028", "Bone_027", "Bone_026", "Bone_025", "Bone_024") + tuple(f"Bone_{i:03d}" for i in range(34, 50)),
    "arm_left": ("Bone_033", "Bone_032", "Bone_031", "Bone_030", "Bone_029") + tuple(f"Bone_{i:03d}" for i in range(50, 66)),
}

_ALL_BONES = tuple(b for group in REGION_BONES.values() for b in group)


def _mapped() -> dict[str, str]:
    m = {"Bone_000": "mixamorig:Hips", "Bone_001": "mixamorig:Hips", "Bone_004": "mixamorig:Spine", "Bone_003": "mixamorig:Spine1", "Bone_002": "mixamorig:Spine2"}
    m.update({"Bone_023": "mixamorig:Neck", "Bone_022": "mixamorig:Head", "Bone_021": "mixamorig:HeadTop_End"})
    m.update({"Bone_007": "mixamorig:RightUpLeg", "Bone_006": "mixamorig:RightLeg", "Bone_005": "mixamorig:RightFoot", "Bone_012": "mixamorig:RightToeBase", "Bone_011": "mixamorig:RightToeBase", "Bone_015": "mixamorig:RightUpLeg", "Bone_014": "mixamorig:RightLeg", "Bone_013": "mixamorig:RightFoot"})
    m.update({"Bone_010": "mixamorig:LeftUpLeg", "Bone_009": "mixamorig:LeftLeg", "Bone_008": "mixamorig:LeftFoot", "Bone_020": "mixamorig:LeftUpLeg", "Bone_019": "mixamorig:LeftLeg", "Bone_018": "mixamorig:LeftFoot", "Bone_017": "mixamorig:LeftToeBase", "Bone_016": "mixamorig:LeftToeBase"})
    for group, hand in (("arm_right", "mixamorig:RightHand"), ("arm_left", "mixamorig:LeftHand")):
        proximal = REGION_BONES[group][:4]
        for bone, donor in zip(proximal, (hand.replace("Hand", "Shoulder"), hand.replace("Hand", "Arm"), hand.replace("Hand", "ForeArm"), hand)):
            m[bone] = donor
        for bone in REGION_BONES[group][4:]:
            m[bone] = hand
    return m


ORC_CHIEFTAIN_MIXAMO = {
    "assetId": "h3_orc_chieftain", "displayName": "Orc Chieftain", "mesh": ORC_CHIEFTAIN_MESH,
    "expectedMeshSha256": ORC_CHIEFTAIN_SHA256, "donorKind": "obj", "donorRefSeq": MIXAMO_REF_SEQ,
    "donorCharacterDir": VENDOR_DEMO / "obj1k" / "characters" / MIXAMO_SPECIES,
    "donorBindSource": "ffs_bvh_capture_scale", "sourceIdleDir": ORC_CHIEFTAIN_SOURCE_IDLE,
    "sourceIdleGroup": 2, "sourceIdleFrameCount": 8, "regionJoints": MIXAMO_REGION_JOINTS,
    "regionBones": REGION_BONES, "headBone": "Bone_022", "neckBone": "Bone_023",
    "requireCompleteRegionCoverage": True, "sourceJointMap": _mapped(), "rigidAttachments": (),
    "skinInitialization": "source_joint_map", "hubs": {"mixamorig:Hips": "Bone_001", "mixamorig:Spine": "Bone_004", "mixamorig:Spine1": "Bone_003", "mixamorig:Spine2": "Bone_002"},
    "chains": (
        {"name": "neck", "kind": "polyline", "donor": ("mixamorig:Neck", "mixamorig:Head"), "evidence": ("Bone_023", "Bone_022")},
        {"name": "head_end", "kind": "relative_to_parent", "donor": ("mixamorig:HeadTop_End",), "anchor": "mixamorig:Head", "region": "neck_head", "helper": True},
        {"name": "arm_left", "kind": "polyline", "donor": ("mixamorig:LeftShoulder", "mixamorig:LeftArm", "mixamorig:LeftForeArm", "mixamorig:LeftHand"), "evidence": ("Bone_033", "Bone_032", "Bone_031", "Bone_030")},
        {"name": "arm_right", "kind": "polyline", "donor": ("mixamorig:RightShoulder", "mixamorig:RightArm", "mixamorig:RightForeArm", "mixamorig:RightHand"), "evidence": ("Bone_028", "Bone_027", "Bone_026", "Bone_025")},
        {"name": "leg_left", "kind": "polyline", "donor": ("mixamorig:LeftUpLeg", "mixamorig:LeftLeg", "mixamorig:LeftFoot", "mixamorig:LeftToeBase"), "evidence": ("Bone_020", "Bone_019", "Bone_018", "Bone_017")},
        {"name": "leg_right", "kind": "polyline", "donor": ("mixamorig:RightUpLeg", "mixamorig:RightLeg", "mixamorig:RightFoot", "mixamorig:RightToeBase"), "evidence": ("Bone_015", "Bone_014", "Bone_013", "Bone_012")},
        {"name": "toe_left", "kind": "relative_to_parent", "donor": ("mixamorig:LeftToe_End",), "anchor": "mixamorig:LeftToeBase", "region": "leg_left", "helper": True},
        {"name": "toe_right", "kind": "relative_to_parent", "donor": ("mixamorig:RightToe_End",), "anchor": "mixamorig:RightToeBase", "region": "leg_right", "helper": True},
    ),
    "leftRightPairs": ({"donor": ("mixamorig:LeftHand", "mixamorig:RightHand"), "evidence": ("Bone_030", "Bone_025")}, {"donor": ("mixamorig:LeftFoot", "mixamorig:RightFoot"), "evidence": ("Bone_018", "Bone_013")} ),
    "requiredBranches": tuple(REGION_BONES), "extraTargetBones": (), "wholeBodyHubs": ("mixamorig:Hips", "mixamorig:Spine2", "mixamorig:Head", "mixamorig:LeftShoulder", "mixamorig:RightShoulder", "mixamorig:LeftUpLeg", "mixamorig:RightUpLeg"),
    "actuation": (("shoulder_L", "mixamorig:LeftArm", "arm_left", "arm_right"), ("forearm_L", "mixamorig:LeftForeArm", "arm_left", "arm_right"), ("thigh_L", "mixamorig:LeftUpLeg", "leg_left", "leg_right"), ("spine", "mixamorig:Spine1", "torso", "leg_right")),
    "syntheticMotionOnly": True, "visualAcceptance": "unreviewed_candidate",
    "anatomyEvidence": "CPU GLB audit: 66 joints, 8307 vertices, 9736 triangles; positive-X limb chains are left and negative-X chains right. Bone_023->022->021 is the neck/head chain. No independently identified weapon attachment bone is asserted.",
}


def get_profile() -> dict:
    return ORC_CHIEFTAIN_MIXAMO
