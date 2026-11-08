"""Candidate owned anatomy for semantic Raider, not the legacy filename label.

The source rig has no rider torso/head chain. Those sites and ownership volumes
are explicit estimates; source appendage sites are retained by name. No motion
is authored here. Visual animation acceptance is a separate gate.
"""
MESH_ASSET = "h3_wolf_raider"
MESH_SHA256 = "b15de4cfcd0ae93eebee224dae779ef9d8913f34cadfa86a65d86966a985916f"


def _bones(values):
    return tuple(f"Bone_{value:03d}" for value in values)


SOURCE_GROUPS = {
    "mount_torso": _bones((0, 1, 3, 2, 22, 21, 20)),
    "mount_head": _bones((34, 33, 32, 52, 51, 54, 53, 56, 55)),
    "mount_tail": _bones((7, 6, 5, 4)),
    "mount_hind_left": _bones((19, 18, 17, 16, 15, 14)),
    "mount_hind_right": _bones((13, 12, 11, 10, 9, 8)),
    "mount_front_left": _bones((50, 49, 48, 47, 46, 45)),
    "mount_front_right": _bones((44, 43, 42, 41, 40, 39)),
    "rider_arm_left": _bones((31, 30, 29)),
    "rider_arm_right": _bones((38, 37, 36)),
    "weapon": _bones((35,)),
    "rider_leg_left": _bones((25, 24, 23)),
    "rider_leg_right": _bones((28, 27, 26)),
}
SOURCE_BONES = frozenset(f"Bone_{i:03d}" for i in range(57))

# Positive X is anatomical left for the forward-positive-Z source mesh.
MOUNT_MAP = {
    "Hips": "Bone_001", "Bip01_Pelvis": "Bone_001",
    "Bip01_Spine": "Bone_003", "Bip01_Spine1": "Bone_022",
    "Bip01_Spine2": "Bone_021", "Bip01_Neck": "Bone_020",
    "Bip01_Neck1": "Bone_034", "Bip01_Head": "Bone_033",
    "BN_Mouth_01": "Bone_052", "BN_Ear_L_01": "Bone_054",
    "BN_Ear_R_01": "Bone_056", "BN_Tail_01": "Bone_007",
    "BN_Tail_02": "Bone_005", "BN_Tail_03": "Bone_004",
}
for side, hind, front in (("L", (19, 18, 17, 16, 15), (50, 49, 48, 47, 46, 45)),
                          ("R", (13, 12, 11, 10, 9), (44, 43, 42, 41, 40, 39))):
    for part, bone in zip(("Thigh", "Calf", "HorseLink", "Foot", "Toe0"), hind):
        MOUNT_MAP[f"Bip01_{side}_{part}"] = f"Bone_{bone:03d}"
    for part, bone in zip(("Clavicle", "UpperArm", "Forearm", "Hand", "Finger0", "Finger01"), front):
        MOUNT_MAP[f"Bip01_{side}_{part}"] = f"Bone_{bone:03d}"
MOUNT_POINTS = {}

RIDER_MAP = {
    "mixamorig:LeftArm": "Bone_031", "mixamorig:LeftForeArm": "Bone_030",
    "mixamorig:LeftHand": "Bone_029", "mixamorig:RightArm": "Bone_038",
    "mixamorig:RightForeArm": "Bone_037", "mixamorig:RightHand": "Bone_036",
    "mixamorig:LeftLeg": "Bone_025", "mixamorig:LeftFoot": "Bone_024",
    "mixamorig:LeftToeBase": "Bone_023", "mixamorig:RightLeg": "Bone_028",
    "mixamorig:RightFoot": "Bone_027", "mixamorig:RightToeBase": "Bone_026",
}
RIDER_POINTS = {
    "mixamorig:Hips": (.015, 1.00, -.12), "mixamorig:Spine": (.02, 1.10, -.14),
    "mixamorig:Spine1": (.02, 1.20, -.16), "mixamorig:Spine2": (.025, 1.32, -.19),
    "mixamorig:Neck": (.015, 1.40, -.18), "mixamorig:Head": (.015, 1.50, -.15),
    "mixamorig:HeadTop_End": (.015, 1.65, -.15),
    "mixamorig:LeftShoulder": (.10, 1.33, -.16),
    "mixamorig:RightShoulder": (-.06, 1.34, -.175),
    "mixamorig:LeftUpLeg": (.14, .96, -.18),
    "mixamorig:RightUpLeg": (-.12, .96, -.18),
    "mixamorig:LeftToe_End": (.36, .50, .10),
    "mixamorig:RightToe_End": (-.34, .50, .10),
}
# Bone_020 and arm roots own rider body pixels despite their mount ancestry.
# Restrict both corrections to the central rider volume; never capture the sword.
REGION_VOLUMES = tuple(
    {"region": region, "min": lo, "max": hi, "sourcePrefix": prefix}
    for region, lo, hi in (
        ("rider_torso", (-.18, 1.0, -.50), (.18, 1.35, .15)),
        ("rider_neck_head", (-.22, 1.35, -.50), (.22, 1.80, .15)),
    ) for prefix in ("mount_", "rider_")
)
AUTHORING_PROOF = (
    "Raider b15de4 source named-joint and four-view audit; missing rider torso/head "
    "sites and central ownership explicitly estimated; candidate not visually accepted"
)
