"""Ancient Behemoth source-mapped profile using the fixed Mixamo donor."""
from __future__ import annotations
from pathlib import Path
from paths import MESHY, VENDOR_DEMO
from asset_profiles import MIXAMO_REF_SEQ, MIXAMO_SPECIES, MIXAMO_REGION_JOINTS

MESH = MESHY / "h3_ancient_behemoth_smartrigged.glb"
MESH_SHA256 = "c05435546d5b0841ef42eb327fc774f1599dd65f1520b0add03f96e6390dba76"
SOURCE_IDLE = Path("V:/SteamLibrary/steamapps/common/Heroes of Might and Magic Olden Era - Golden Era/BepInEx/plugins/OfflineUnlockMod/homm3_lab/h3_ancient_behemoth/extracted_battle_source_12fps/CABEHE.dir")
REGION_BONES = {
    "torso": ("Bone_000", "Bone_001", "Bone_014", "Bone_013", "Bone_012", "Bone_011", "Bone_010"),
    "neck_head": ("Bone_028", "Bone_027", "Bone_038", "Bone_037", "Bone_040", "Bone_039"),
    "arm_left": ("Bone_036", "Bone_035", "Bone_034", "Bone_033", "Bone_052", "Bone_055", "Bone_058", "Bone_051", "Bone_054", "Bone_057", "Bone_050", "Bone_053", "Bone_056"),
    "arm_right": ("Bone_032", "Bone_031", "Bone_030", "Bone_029", "Bone_043", "Bone_046", "Bone_049", "Bone_042", "Bone_045", "Bone_048", "Bone_041", "Bone_044", "Bone_047"),
    "leg_left": ("Bone_009", "Bone_008", "Bone_007", "Bone_006", "Bone_023", "Bone_026", "Bone_025", "Bone_024", "Bone_022", "Bone_021"),
    "leg_right": ("Bone_005", "Bone_004", "Bone_003", "Bone_002", "Bone_017", "Bone_016", "Bone_015", "Bone_020", "Bone_019", "Bone_018"),
}
REGION_JOINTS = dict(MIXAMO_REGION_JOINTS)
SOURCE_JOINT_MAP = {"Bone_000": "mixamorig:Hips", "Bone_001": "mixamorig:Hips", "Bone_014": "mixamorig:Spine", "Bone_013": "mixamorig:Spine1", "Bone_012": "mixamorig:Spine2", "Bone_011": "mixamorig:Spine2", "Bone_010": "mixamorig:Spine2", "Bone_028": "mixamorig:Neck", "Bone_027": "mixamorig:Head", "Bone_038": "mixamorig:Head", "Bone_037": "mixamorig:Head", "Bone_040": "mixamorig:Head", "Bone_039": "mixamorig:Head"}
SOURCE_JOINT_MAP.update({"Bone_036": "mixamorig:LeftArm", "Bone_035": "mixamorig:LeftForeArm", "Bone_034": "mixamorig:LeftHand", "Bone_033": "mixamorig:LeftHand", "Bone_052": "mixamorig:LeftHand", "Bone_055": "mixamorig:LeftHand", "Bone_058": "mixamorig:LeftHand", "Bone_051": "mixamorig:LeftHand", "Bone_054": "mixamorig:LeftHand", "Bone_057": "mixamorig:LeftHand", "Bone_050": "mixamorig:LeftHand", "Bone_053": "mixamorig:LeftHand", "Bone_056": "mixamorig:LeftHand"})
SOURCE_JOINT_MAP.update({"Bone_032": "mixamorig:RightArm", "Bone_031": "mixamorig:RightForeArm", "Bone_030": "mixamorig:RightHand", "Bone_029": "mixamorig:RightHand", "Bone_043": "mixamorig:RightHand", "Bone_046": "mixamorig:RightHand", "Bone_049": "mixamorig:RightHand", "Bone_042": "mixamorig:RightHand", "Bone_045": "mixamorig:RightHand", "Bone_048": "mixamorig:RightHand", "Bone_041": "mixamorig:RightHand", "Bone_044": "mixamorig:RightHand", "Bone_047": "mixamorig:RightHand"})
SOURCE_JOINT_MAP.update({b: d for b, d in zip(REGION_BONES["leg_left"], ("mixamorig:LeftUpLeg", "mixamorig:LeftLeg", "mixamorig:LeftFoot", "mixamorig:LeftToeBase") + ("mixamorig:LeftToeBase",) * 9)})
SOURCE_JOINT_MAP.update({b: d for b, d in zip(REGION_BONES["leg_right"], ("mixamorig:RightUpLeg", "mixamorig:RightLeg", "mixamorig:RightFoot", "mixamorig:RightToeBase") + ("mixamorig:RightToeBase",) * 6)})

ANCIENT_BEHEMOTH_MIXAMO = {
    "assetId": "h3_ancient_behemoth", "displayName": "Ancient Behemoth", "mesh": MESH, "expectedMeshSha256": MESH_SHA256,
    "donorKind": "obj", "donorRefSeq": MIXAMO_REF_SEQ, "donorCharacterDir": VENDOR_DEMO / "obj1k" / "characters" / MIXAMO_SPECIES, "donorBindSource": "ffs_bvh_capture_scale",
    "sourceIdleDir": SOURCE_IDLE, "sourceIdleGroup": 2, "sourceIdleFrameCount": 8, "regionJoints": REGION_JOINTS, "regionBones": REGION_BONES, "headBone": "Bone_027", "neckBone": "Bone_028", "beakFromHeadQuantile": None, "requireCompleteRegionCoverage": True, "rigidAttachments": (),
    "hubs": {"mixamorig:Hips": "Bone_001", "mixamorig:Spine": "Bone_014", "mixamorig:Spine1": "Bone_013", "mixamorig:Spine2": "Bone_010"},
    "chains": (
        {"name": "neck", "kind": "polyline", "donor": ("mixamorig:Neck", "mixamorig:Head"), "evidence": ("Bone_028", "Bone_027")},
        {"name": "head_end", "kind": "relative_to_parent", "donor": ("mixamorig:HeadTop_End",), "anchor": "mixamorig:Head", "region": "neck_head", "helper": True},
        {"name": "arm_left", "kind": "polyline", "donor": ("mixamorig:LeftShoulder", "mixamorig:LeftArm", "mixamorig:LeftForeArm", "mixamorig:LeftHand"), "evidence": ("Bone_036", "Bone_035", "Bone_034")},
        {"name": "arm_right", "kind": "polyline", "donor": ("mixamorig:RightShoulder", "mixamorig:RightArm", "mixamorig:RightForeArm", "mixamorig:RightHand"), "evidence": ("Bone_032", "Bone_031", "Bone_030")},
        {"name": "leg_left", "kind": "polyline", "donor": ("mixamorig:LeftUpLeg", "mixamorig:LeftLeg", "mixamorig:LeftFoot", "mixamorig:LeftToeBase"), "evidence": ("Bone_009", "Bone_008", "Bone_007", "Bone_006")},
        {"name": "leg_right", "kind": "polyline", "donor": ("mixamorig:RightUpLeg", "mixamorig:RightLeg", "mixamorig:RightFoot", "mixamorig:RightToeBase"), "evidence": ("Bone_005", "Bone_004", "Bone_003", "Bone_002")},
        {"name": "toe_left", "kind": "relative_to_parent", "donor": ("mixamorig:LeftToe_End",), "anchor": "mixamorig:LeftToeBase", "region": "leg_left", "helper": True},
        {"name": "toe_right", "kind": "relative_to_parent", "donor": ("mixamorig:RightToe_End",), "anchor": "mixamorig:RightToeBase", "region": "leg_right", "helper": True},
    ),
    "leftRightPairs": ({"donor": ("mixamorig:LeftHand", "mixamorig:RightHand"), "evidence": ("Bone_034", "Bone_030")}, {"donor": ("mixamorig:LeftFoot", "mixamorig:RightFoot"), "evidence": ("Bone_007", "Bone_003")}),
    "requiredBranches": ("torso", "neck_head", "arm_left", "arm_right", "leg_left", "leg_right"), "extraTargetBones": (), "unsupportedRequiredArticulations": ("ancient_behemoth_claws_and_foot_details_collapse_to_fixed_donor_endpoints",),
    "actuation": (("shoulder_L", "mixamorig:LeftArm", "arm_left", "arm_right"), ("forearm_L", "mixamorig:LeftForeArm", "arm_left", "arm_right"), ("thigh_L", "mixamorig:LeftUpLeg", "leg_left", "leg_right"), ("spine", "mixamorig:Spine1", "torso", "leg_right")),
    "wholeBodyHubs": ("mixamorig:Hips", "mixamorig:Spine2", "mixamorig:Head", "mixamorig:LeftShoulder", "mixamorig:RightShoulder", "mixamorig:LeftUpLeg", "mixamorig:RightUpLeg"), "syntheticMotionOnly": True, "skinInitialization": "source_joint_map", "sourceJointMap": SOURCE_JOINT_MAP,
}

def get_profile() -> dict:
    return ANCIENT_BEHEMOTH_MIXAMO
