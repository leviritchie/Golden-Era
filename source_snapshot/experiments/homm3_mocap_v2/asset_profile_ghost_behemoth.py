"""Explicit CPU-audited profile for the 49-joint Ghost Behemoth mesh."""
from pathlib import Path
from paths import MESHY, VENDOR_DEMO
from asset_profiles import MIXAMO_REF_SEQ, MIXAMO_SPECIES, MIXAMO_REGION_JOINTS

MESH = MESHY / "toa_ghost_behemoth_smartrigged.glb"
SOURCE_IDLE = Path("V:/SteamLibrary/steamapps/common/Heroes of Might and Magic Olden Era - Golden Era/BepInEx/plugins/OfflineUnlockMod/homm3_lab/toa_ghost_behemoth/extracted_battle_source_12fps/lvl7alt.dir")
SHA256 = "f9cf6c61eded9fb82e96961931fe8be932f0d5567c6927a4bb413d1cb9b7ac68"

REGION_BONES = {
    "torso": ("Bone_000", "Bone_001", "Bone_004", "Bone_003", "Bone_002"),
    "neck_head": ("Bone_016", "Bone_015", "Bone_014", "Bone_013"),
    "arm_left": ("Bone_020", "Bone_019", "Bone_018", "Bone_017", "Bone_038", "Bone_040", "Bone_042", "Bone_037", "Bone_039", "Bone_041"),
    "arm_right": ("Bone_024", "Bone_023", "Bone_022", "Bone_021", "Bone_044", "Bone_046", "Bone_048", "Bone_043", "Bone_045", "Bone_047"),
    "leg_right": ("Bone_008", "Bone_007", "Bone_006", "Bone_005", "Bone_026", "Bone_028", "Bone_030", "Bone_025", "Bone_027", "Bone_029"),
    "leg_left": ("Bone_012", "Bone_011", "Bone_010", "Bone_009", "Bone_032", "Bone_034", "Bone_036", "Bone_031", "Bone_033", "Bone_035"),
}

def _map():
    m = {b: "mixamorig:Hips" for b in REGION_BONES["torso"]}
    m.update({"Bone_004": "mixamorig:Spine", "Bone_003": "mixamorig:Spine1", "Bone_002": "mixamorig:Spine2"})
    m.update(dict(zip(REGION_BONES["neck_head"][:4], ("mixamorig:Neck", "mixamorig:Head", "mixamorig:Head", "mixamorig:HeadTop_End"))))
    for group, donors in (("arm_left", ("mixamorig:LeftShoulder", "mixamorig:LeftArm", "mixamorig:LeftForeArm", "mixamorig:LeftHand")), ("arm_right", ("mixamorig:RightShoulder", "mixamorig:RightArm", "mixamorig:RightForeArm", "mixamorig:RightHand"))):
        for b, d in zip(REGION_BONES[group][:4], donors): m[b] = d
        for b in REGION_BONES[group][4:]: m[b] = donors[-1]
    for group, donors in (("leg_left", ("mixamorig:LeftUpLeg", "mixamorig:LeftLeg", "mixamorig:LeftFoot", "mixamorig:LeftToeBase")), ("leg_right", ("mixamorig:RightUpLeg", "mixamorig:RightLeg", "mixamorig:RightFoot", "mixamorig:RightToeBase"))):
        for b, d in zip(REGION_BONES[group][:4], donors): m[b] = d
        for b in REGION_BONES[group][4:]: m[b] = donors[-1]
    return m

GHOST_BEHEMOTH_MIXAMO = {
    "assetId": "h3_ghost_behemoth", "displayName": "Ghost Behemoth", "mesh": MESH, "expectedMeshSha256": SHA256,
    "donorKind": "obj", "donorRefSeq": MIXAMO_REF_SEQ, "donorCharacterDir": VENDOR_DEMO / "obj1k" / "characters" / MIXAMO_SPECIES,
    "donorBindSource": "ffs_bvh_capture_scale", "sourceIdleDir": SOURCE_IDLE, "sourceIdleGroup": 2, "sourceIdleFrameCount": 8,
    "regionJoints": MIXAMO_REGION_JOINTS, "regionBones": REGION_BONES, "headBone": "Bone_015", "neckBone": "Bone_016",
    "requireCompleteRegionCoverage": True, "sourceJointMap": _map(), "rigidAttachments": (), "skinInitialization": "source_joint_map",
    "hubs": {"mixamorig:Hips": "Bone_001", "mixamorig:Spine": "Bone_004", "mixamorig:Spine1": "Bone_003", "mixamorig:Spine2": "Bone_002"},
    "chains": (
        {"name": "neck", "kind": "polyline", "donor": ("mixamorig:Neck", "mixamorig:Head"), "evidence": ("Bone_016", "Bone_015")},
        {"name": "head_end", "kind": "relative_to_parent", "donor": ("mixamorig:HeadTop_End",), "anchor": "mixamorig:Head", "region": "neck_head", "helper": True},
        {"name": "arm_left", "kind": "polyline", "donor": ("mixamorig:LeftShoulder", "mixamorig:LeftArm", "mixamorig:LeftForeArm", "mixamorig:LeftHand"), "evidence": ("Bone_020", "Bone_019", "Bone_018", "Bone_017")},
        {"name": "arm_right", "kind": "polyline", "donor": ("mixamorig:RightShoulder", "mixamorig:RightArm", "mixamorig:RightForeArm", "mixamorig:RightHand"), "evidence": ("Bone_024", "Bone_023", "Bone_022", "Bone_021")},
        {"name": "leg_left", "kind": "polyline", "donor": ("mixamorig:LeftUpLeg", "mixamorig:LeftLeg", "mixamorig:LeftFoot", "mixamorig:LeftToeBase"), "evidence": ("Bone_012", "Bone_011", "Bone_010", "Bone_009")},
        {"name": "leg_right", "kind": "polyline", "donor": ("mixamorig:RightUpLeg", "mixamorig:RightLeg", "mixamorig:RightFoot", "mixamorig:RightToeBase"), "evidence": ("Bone_008", "Bone_007", "Bone_006", "Bone_005")},
        {"name": "toe_left", "kind": "relative_to_parent", "donor": ("mixamorig:LeftToe_End",), "anchor": "mixamorig:LeftToeBase", "region": "leg_left", "helper": True},
        {"name": "toe_right", "kind": "relative_to_parent", "donor": ("mixamorig:RightToe_End",), "anchor": "mixamorig:RightToeBase", "region": "leg_right", "helper": True},
    ),
    "requiredBranches": tuple(REGION_BONES), "extraTargetBones": (), "wholeBodyHubs": ("mixamorig:Hips", "mixamorig:Spine2", "mixamorig:Head", "mixamorig:LeftShoulder", "mixamorig:RightShoulder", "mixamorig:LeftUpLeg", "mixamorig:RightUpLeg"),
    "leftRightPairs": ({"donor": ("mixamorig:LeftHand", "mixamorig:RightHand"), "evidence": ("Bone_017", "Bone_021")}, {"donor": ("mixamorig:LeftFoot", "mixamorig:RightFoot"), "evidence": ("Bone_010", "Bone_006")}),
    "actuation": (("shoulder_L", "mixamorig:LeftArm", "arm_left", "arm_right"), ("forearm_L", "mixamorig:LeftForeArm", "arm_left", "arm_right"), ("thigh_L", "mixamorig:LeftUpLeg", "leg_left", "leg_right"), ("spine", "mixamorig:Spine1", "torso", "leg_right")),
    "syntheticMotionOnly": True, "visualAcceptance": "unreviewed_candidate", "anatomyEvidence": "CPU named-parent and dense-weight audit; region ownership follows actual torso, lateral arm, and grounded leg branches."
}

def get_profile():
    return GHOST_BEHEMOTH_MIXAMO
