"""CPU-audited fixed-mocap profile for the Cyclops King SmartRig mesh."""
from __future__ import annotations
from pathlib import Path
from asset_profiles import MIXAMO_REF_SEQ, MIXAMO_SPECIES, MIXAMO_REGION_JOINTS
from paths import MESHY, VENDOR_DEMO

CYCLOPS_KING_MESH = MESHY / "h3_cyclops_king_smartrigged.glb"
CYCLOPS_KING_SOURCE_IDLE = Path(
    "V:/SteamLibrary/steamapps/common/Heroes of Might and Magic Olden Era - Golden Era/"
    "BepInEx/plugins/OfflineUnlockMod/homm3_lab/h3_cyclops_king/"
    "extracted_battle_source_12fps/CcyclLor.dir"
)
CYCLOPS_KING_SHA256 = "4bb04172223bbe472fbcda21c16b8d6de4429a56823cae09f5adce98ccb816ff"

REGION_BONES = {
    "torso": ("Bone_000", "Bone_001", "Bone_005", "Bone_004", "Bone_003", "Bone_002"),
    "neck_head": ("Bone_019", "Bone_018", "Bone_017", "Bone_016"),
    "arm_left": ("Bone_024", "Bone_023", "Bone_022", "Bone_021", "Bone_020", "Bone_033", "Bone_032", "Bone_031", "Bone_030", "Bone_037", "Bone_036", "Bone_035", "Bone_034"),
    "arm_right": ("Bone_029", "Bone_028", "Bone_027", "Bone_026", "Bone_025", "Bone_038", "Bone_039", "Bone_040", "Bone_041", "Bone_042", "Bone_043", "Bone_044"),
    "leg_left": ("Bone_015", "Bone_014", "Bone_013", "Bone_012", "Bone_011"),
    "leg_right": ("Bone_010", "Bone_009", "Bone_008", "Bone_007", "Bone_006"),
}

def _mapped():
    m = {"Bone_000": "mixamorig:Hips", "Bone_001": "mixamorig:Hips",
         "Bone_005": "mixamorig:Spine", "Bone_004": "mixamorig:Spine1",
         "Bone_003": "mixamorig:Spine2", "Bone_002": "mixamorig:Spine2",
         "Bone_019": "mixamorig:Neck", "Bone_018": "mixamorig:Head",
         "Bone_017": "mixamorig:Head", "Bone_016": "mixamorig:HeadTop_End"}
    m.update({"Bone_024":"mixamorig:LeftShoulder", "Bone_023":"mixamorig:LeftArm", "Bone_022":"mixamorig:LeftForeArm", "Bone_021":"mixamorig:LeftHand", "Bone_020":"mixamorig:LeftHand"})
    m.update({"Bone_029":"mixamorig:RightShoulder", "Bone_028":"mixamorig:RightArm", "Bone_027":"mixamorig:RightForeArm", "Bone_026":"mixamorig:RightHand", "Bone_025":"mixamorig:RightHand"})
    m.update({b: "mixamorig:LeftHand" for b in REGION_BONES["arm_left"][5:]})
    m.update({b: "mixamorig:RightHand" for b in REGION_BONES["arm_right"][5:]})
    m.update({"Bone_015":"mixamorig:LeftUpLeg", "Bone_014":"mixamorig:LeftLeg", "Bone_013":"mixamorig:LeftFoot", "Bone_012":"mixamorig:LeftToeBase", "Bone_011":"mixamorig:LeftToeBase", "Bone_010":"mixamorig:RightUpLeg", "Bone_009":"mixamorig:RightLeg", "Bone_008":"mixamorig:RightFoot", "Bone_007":"mixamorig:RightToeBase", "Bone_006":"mixamorig:RightToeBase"})
    return m

PROFILE = {
    "assetId":"h3_cyclops_king", "displayName":"Cyclops King", "mesh":CYCLOPS_KING_MESH, "expectedMeshSha256":CYCLOPS_KING_SHA256,
    "donorKind":"obj", "donorRefSeq":MIXAMO_REF_SEQ, "donorCharacterDir":VENDOR_DEMO / "obj1k" / "characters" / MIXAMO_SPECIES,
    "donorBindSource":"ffs_bvh_capture_scale", "sourceIdleDir":CYCLOPS_KING_SOURCE_IDLE, "sourceIdleGroup":2, "sourceIdleFrameCount":6,
    "regionJoints":MIXAMO_REGION_JOINTS, "regionBones":REGION_BONES, "headBone":"Bone_018", "neckBone":"Bone_019",
    "requireCompleteRegionCoverage":True, "sourceJointMap":_mapped(), "skinInitialization":"source_joint_map", "rigidAttachments":(),
    "hubs":{"mixamorig:Hips":"Bone_001", "mixamorig:Spine":"Bone_005", "mixamorig:Spine1":"Bone_004", "mixamorig:Spine2":"Bone_003"},
    "chains":(
        {"name":"neck", "kind":"polyline", "donor":("mixamorig:Neck","mixamorig:Head"), "evidence":("Bone_019","Bone_018")},
        {"name":"head_end", "kind":"relative_to_parent", "donor":("mixamorig:HeadTop_End",), "anchor":"mixamorig:Head", "region":"neck_head", "helper":True},
        {"name":"arm_left", "kind":"polyline", "donor":("mixamorig:LeftShoulder","mixamorig:LeftArm","mixamorig:LeftForeArm","mixamorig:LeftHand"), "evidence":("Bone_024","Bone_023","Bone_022","Bone_021")},
        {"name":"arm_right", "kind":"polyline", "donor":("mixamorig:RightShoulder","mixamorig:RightArm","mixamorig:RightForeArm","mixamorig:RightHand"), "evidence":("Bone_029","Bone_028","Bone_027","Bone_026")},
        {"name":"leg_left", "kind":"polyline", "donor":("mixamorig:LeftUpLeg","mixamorig:LeftLeg","mixamorig:LeftFoot","mixamorig:LeftToeBase"), "evidence":("Bone_015","Bone_014","Bone_013","Bone_012")},
        {"name":"leg_right", "kind":"polyline", "donor":("mixamorig:RightUpLeg","mixamorig:RightLeg","mixamorig:RightFoot","mixamorig:RightToeBase"), "evidence":("Bone_010","Bone_009","Bone_008","Bone_007")},
        {"name":"toe_left", "kind":"relative_to_parent", "donor":("mixamorig:LeftToe_End",), "anchor":"mixamorig:LeftToeBase", "region":"leg_left", "helper":True},
        {"name":"toe_right", "kind":"relative_to_parent", "donor":("mixamorig:RightToe_End",), "anchor":"mixamorig:RightToeBase", "region":"leg_right", "helper":True},
    ),
    "leftRightPairs":({"donor":("mixamorig:LeftHand","mixamorig:RightHand"),"evidence":("Bone_021","Bone_026")},{"donor":("mixamorig:LeftFoot","mixamorig:RightFoot"),"evidence":("Bone_013","Bone_008")}),
    "requiredBranches":("torso","neck_head","arm_left","arm_right","leg_left","leg_right"), "extraTargetBones":(),
    "wholeBodyHubs":("mixamorig:Hips","mixamorig:Spine2","mixamorig:Head","mixamorig:LeftShoulder","mixamorig:RightShoulder","mixamorig:LeftUpLeg","mixamorig:RightUpLeg"),
    "actuation":(("shoulder_L","mixamorig:LeftArm","arm_left","arm_right"),("forearm_L","mixamorig:LeftForeArm","arm_left","arm_right"),("thigh_L","mixamorig:LeftUpLeg","leg_left","leg_right"),("spine","mixamorig:Spine1","torso","leg_right")),
    "syntheticMotionOnly":True, "visualAcceptance":"unreviewed_candidate",
    "anatomyEvidence":"CPU GLB hierarchy audit: Bone_024 branch is positive-X left arm and Bone_029 branch negative-X right arm; Bone_019-018-017-016 is neck/head/tip; wrists are Bone_021 and Bone_026, while Bone_020 and Bone_025 enter the held rock/hand geometry; distal claws remain hand-owned. The rock is part of the skinned mesh and has no independent release evidence.",
}

def get_profile():
    return PROFILE
