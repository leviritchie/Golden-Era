"""Authored anatomy for semantic Wolf Rider (download basename wolf_raider).

This is data only. Bone names are taken from the corrected mesh; no array
position is used as an identity outside the explicit ``Bone_NNN`` name.
"""
from __future__ import annotations

MESH_ASSET = "h3_wolf_rider"
MESH_SHA256 = "2fb1bb0700827cc1de2d8e67a68fc31d7816ccd0e76e7666e72ea0619a0fd00a"


def _bones(values):
    return tuple(f"Bone_{value:03d}" for value in values)


SOURCE_GROUPS = {
    "mount_torso": _bones((0, 1, 3, 2)),
    "mount_tail": _bones((8, 7, 6, 5, 4)),
    "mount_head": _bones((52, 51, 50)),
    "rider_torso": _bones((11, 10, 9, 31, 30)),
    "rider_neck_head": _bones((45, 44, 43, 42)),
    "rider_arm_right": _bones((36, 35, 34, 33)),
    "weapon": _bones((32,)),
    "rider_arm_left": _bones((49, 48, 47, 46)),
    "rider_leg_left": _bones((19, 18, 17, 16)),
    "rider_leg_right": _bones((15, 14, 13, 12)),
    "mount_hind_left": _bones((29, 28, 27, 26, 25)),
    "mount_hind_right": _bones((24, 23, 22, 21, 20)),
    "mount_front_left": _bones((41, 40, 39, 38, 37)),
    "mount_front_right": _bones((57, 56, 55, 54, 53)),
}


def _complete_source_names():
    values = [bone for group in SOURCE_GROUPS.values() for bone in group]
    if len(values) != 58 or len(set(values)) != 58:
        raise ValueError("corrected Wolf Rider source groups must cover 58 unique bones")
    return frozenset(values)


SOURCE_BONES = _complete_source_names()

# Source graph attaches the front legs to rider-head bones. Anatomical world
# anchors are reused, but that source parent graph is not the owned hierarchy.
MOUNT_MAP = {
    "Hips": "Bone_001", "Bip01_Pelvis": "Bone_001", "Bip01_Spine": "Bone_003",
    "Bip01_Spine1": "Bone_002", "Bip01_Neck1": "Bone_052",
    "Bip01_Head": "Bone_051", "BN_Mouth_01": "Bone_050",
    "BN_Tail_01": "Bone_008", "BN_Tail_02": "Bone_006", "BN_Tail_03": "Bone_004",
}
for side, hind, front in (("L", (29, 28, 27, 26, 25), (41, 40, 39, 38, 37)),
                          ("R", (24, 23, 22, 21, 20), (57, 56, 55, 54, 53))):
    for donor, bone in zip(("Thigh", "Calf", "HorseLink", "Foot", "Toe0"), hind):
        MOUNT_MAP[f"Bip01_{side}_{donor}"] = f"Bone_{bone:03d}"
    for donor, bone in zip(("UpperArm", "Forearm", "Hand", "Finger0", "Finger01"), front):
        MOUNT_MAP[f"Bip01_{side}_{donor}"] = f"Bone_{bone:03d}"

RIDER_MAP = {
    "mixamorig:Hips": "Bone_011", "mixamorig:Spine": "Bone_010",
    "mixamorig:Spine2": "Bone_009", "mixamorig:Neck": "Bone_031", "mixamorig:Head": "Bone_030",
    "mixamorig:LeftArm": "Bone_049", "mixamorig:LeftForeArm": "Bone_048", "mixamorig:LeftHand": "Bone_046",
    "mixamorig:RightArm": "Bone_036", "mixamorig:RightForeArm": "Bone_035", "mixamorig:RightHand": "Bone_032",
    "mixamorig:LeftUpLeg": "Bone_019", "mixamorig:LeftLeg": "Bone_018", "mixamorig:LeftFoot": "Bone_017",
    "mixamorig:LeftToeBase": "Bone_016", "mixamorig:RightUpLeg": "Bone_015", "mixamorig:RightLeg": "Bone_014",
    "mixamorig:RightFoot": "Bone_013", "mixamorig:RightToeBase": "Bone_012",
}

MOUNT_POINTS = {
    'Bip01_Spine2': (.012,.83,.03), 'Bip01_Neck': (.012,.90,.23),
    'Bip01_L_Clavicle': (.17,.86,.24), 'Bip01_R_Clavicle': (-.16,.86,.24),
    'BN_Ear_L_01': (.10,1.20,.45), 'BN_Ear_R_01': (-.10,1.20,.45),
}
RIDER_POINTS = {
    'mixamorig:Spine1': (.012,1.15,-.20), 'mixamorig:HeadTop_End': (.012,1.61,-.17),
    'mixamorig:LeftShoulder': (.13,1.31,-.16), 'mixamorig:RightShoulder': (-.06,1.34,-.17),
    'mixamorig:LeftToe_End': (.35,.46,.06), 'mixamorig:RightToe_End': (-.30,.46,.04),
}
# Source-weight inspection exposes face owned by the arm and torso owned by
# legs. These explicit authored volumes correct those regions before skinning.
REGION_VOLUMES = (
    {'region':'mount_torso','min':(-.28,.64,-.63),'max':(.28,.95,.25),'sourcePrefix':'mount_'},
    {'region':'rider_torso','min':(-.19,.94,-.31),'max':(.19,1.34,.02),'sourcePrefix':'rider_'},
    {'region':'rider_neck_head','min':(-.25,1.37,-.50),'max':(.25,1.75,.08),'sourcePrefix':'rider_'},
)
AUTHORING_PROOF = 'named source joints plus four-view source ownership inspection; candidate anatomy, not animation acceptance'
