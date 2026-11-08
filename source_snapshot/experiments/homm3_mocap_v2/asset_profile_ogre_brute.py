"""Explicit CPU-audited profile for the ToA Ogre Brute SmartRig mesh."""
from __future__ import annotations
from pathlib import Path

from asset_profiles import MIXAMO_REF_SEQ, MIXAMO_SPECIES, MIXAMO_REGION_JOINTS
from paths import MESHY, VENDOR_DEMO

OGRE_BRUTE_MESH = MESHY / "toa_ogre_brute_smartrigged.glb"
OGRE_BRUTE_SOURCE_IDLE = Path(
    "V:/SteamLibrary/steamapps/common/Heroes of Might and Magic Olden Era - Golden Era/"
    "BepInEx/plugins/OfflineUnlockMod/homm3_lab/toa_ogre_brute/"
    "extracted_battle_source_12fps/lvl4alt.dir"
)
OGRE_BRUTE_SHA256 = "24d46f90e1125800b177cf918dee7175b2e17990d7c93347bbcc31320167d251"

REGION_BONES = {
    "torso": ("Bone_000", "Bone_001", "Bone_004", "Bone_003", "Bone_002"),
    "neck_head": ("Bone_017", "Bone_016", "Bone_015"),
    "arm_left": ("Bone_027", "Bone_026", "Bone_025", "Bone_024", "Bone_023", "Bone_050", "Bone_049", "Bone_048", "Bone_047", "Bone_054", "Bone_053", "Bone_052", "Bone_051", "Bone_058", "Bone_057", "Bone_056", "Bone_055", "Bone_062", "Bone_061", "Bone_060", "Bone_059", "Bone_066", "Bone_065", "Bone_064", "Bone_063"),
    "arm_right": ("Bone_022", "Bone_021", "Bone_020", "Bone_019", "Bone_018", "Bone_030", "Bone_029", "Bone_034", "Bone_033", "Bone_038", "Bone_037", "Bone_042", "Bone_041", "Bone_046", "Bone_045", "Bone_044", "Bone_043", "Bone_028", "Bone_032", "Bone_036", "Bone_040", "Bone_039", "Bone_031", "Bone_035"),
    "leg_left": ("Bone_009", "Bone_008", "Bone_007", "Bone_006", "Bone_005"),
    "leg_right": ("Bone_014", "Bone_013", "Bone_012", "Bone_011", "Bone_010"),
}

def _mapped():
    m = {"Bone_000":"mixamorig:Hips", "Bone_001":"mixamorig:Hips", "Bone_004":"mixamorig:Spine", "Bone_003":"mixamorig:Spine1", "Bone_002":"mixamorig:Spine2", "Bone_017":"mixamorig:Neck", "Bone_016":"mixamorig:Head", "Bone_015":"mixamorig:HeadTop_End"}
    m.update({"Bone_027":"mixamorig:LeftShoulder", "Bone_026":"mixamorig:LeftArm", "Bone_025":"mixamorig:LeftForeArm", "Bone_024":"mixamorig:LeftHand", "Bone_023":"mixamorig:LeftHand"})
    m.update({"Bone_022":"mixamorig:RightShoulder", "Bone_021":"mixamorig:RightArm", "Bone_020":"mixamorig:RightForeArm", "Bone_019":"mixamorig:RightHand", "Bone_018":"mixamorig:RightHand"})
    m.update({b:"mixamorig:LeftHand" for b in REGION_BONES["arm_left"][5:]})
    m.update({b:"mixamorig:RightHand" for b in REGION_BONES["arm_right"][5:]})
    m.update({"Bone_009":"mixamorig:LeftUpLeg", "Bone_008":"mixamorig:LeftLeg", "Bone_007":"mixamorig:LeftFoot", "Bone_006":"mixamorig:LeftToeBase", "Bone_005":"mixamorig:LeftToeBase", "Bone_014":"mixamorig:RightUpLeg", "Bone_013":"mixamorig:RightLeg", "Bone_012":"mixamorig:RightFoot", "Bone_011":"mixamorig:RightToeBase", "Bone_010":"mixamorig:RightToeBase"})
    return m

PROFILE = {
    "assetId":"h3_ogre_brute", "displayName":"Ogre Brute", "mesh":OGRE_BRUTE_MESH, "expectedMeshSha256":OGRE_BRUTE_SHA256,
    "donorKind":"obj", "donorRefSeq":MIXAMO_REF_SEQ, "donorCharacterDir":VENDOR_DEMO / "obj1k" / "characters" / MIXAMO_SPECIES,
    "donorBindSource":"ffs_bvh_capture_scale", "sourceIdleDir":OGRE_BRUTE_SOURCE_IDLE, "sourceIdleGroup":2, "sourceIdleFrameCount":8,
    "regionJoints":MIXAMO_REGION_JOINTS, "regionBones":REGION_BONES, "headBone":"Bone_016", "neckBone":"Bone_017",
    "requireCompleteRegionCoverage":True, "sourceJointMap":_mapped(), "skinInitialization":"source_joint_map", "rigidAttachments":(),
    "hubs":{"mixamorig:Hips":"Bone_001", "mixamorig:Spine":"Bone_004", "mixamorig:Spine1":"Bone_003", "mixamorig:Spine2":"Bone_002"},
    "chains":(
        {"name":"neck", "kind":"polyline", "donor":("mixamorig:Neck","mixamorig:Head"), "evidence":("Bone_017","Bone_016")},
        {"name":"head_end", "kind":"relative_to_parent", "donor":("mixamorig:HeadTop_End",), "anchor":"mixamorig:Head", "region":"neck_head", "helper":True},
        {"name":"arm_left", "kind":"polyline", "donor":("mixamorig:LeftShoulder","mixamorig:LeftArm","mixamorig:LeftForeArm","mixamorig:LeftHand"), "evidence":("Bone_027","Bone_026","Bone_025","Bone_024")},
        {"name":"arm_right", "kind":"polyline", "donor":("mixamorig:RightShoulder","mixamorig:RightArm","mixamorig:RightForeArm","mixamorig:RightHand"), "evidence":("Bone_022","Bone_021","Bone_020","Bone_019")},
        {"name":"leg_left", "kind":"polyline", "donor":("mixamorig:LeftUpLeg","mixamorig:LeftLeg","mixamorig:LeftFoot","mixamorig:LeftToeBase"), "evidence":("Bone_009","Bone_008","Bone_007","Bone_006")},
        {"name":"leg_right", "kind":"polyline", "donor":("mixamorig:RightUpLeg","mixamorig:RightLeg","mixamorig:RightFoot","mixamorig:RightToeBase"), "evidence":("Bone_014","Bone_013","Bone_012","Bone_011")},
        {"name":"toe_left", "kind":"relative_to_parent", "donor":("mixamorig:LeftToe_End",), "anchor":"mixamorig:LeftToeBase", "region":"leg_left", "helper":True},
        {"name":"toe_right", "kind":"relative_to_parent", "donor":("mixamorig:RightToe_End",), "anchor":"mixamorig:RightToeBase", "region":"leg_right", "helper":True},
    ),
    "leftRightPairs":({"donor":("mixamorig:LeftHand","mixamorig:RightHand"),"evidence":("Bone_024","Bone_019")},{"donor":("mixamorig:LeftFoot","mixamorig:RightFoot"),"evidence":("Bone_007","Bone_012")}),
    "requiredBranches":("torso","neck_head","arm_left","arm_right","leg_left","leg_right"), "extraTargetBones":(),
    "wholeBodyHubs":("mixamorig:Hips","mixamorig:Spine2","mixamorig:Head","mixamorig:LeftShoulder","mixamorig:RightShoulder","mixamorig:LeftUpLeg","mixamorig:RightUpLeg"),
    "actuation":(("shoulder_L","mixamorig:LeftArm","arm_left","arm_right"),("forearm_L","mixamorig:LeftForeArm","arm_left","arm_right"),("thigh_L","mixamorig:LeftUpLeg","leg_left","leg_right"),("spine","mixamorig:Spine1","torso","leg_right")),
    "syntheticMotionOnly":True, "visualAcceptance":"unreviewed_candidate",
    "anatomyEvidence":"CPU GLB hierarchy audit: positive-X left arm Bone_027-026-025-024-023 and negative-X right arm Bone_022-021-020-019-018; Bone_024 and Bone_019 are anatomical wrists before same-hand terminal joints and claw branches. Legs are positive-X Bone_009 branch and negative-X Bone_014 branch. No independent weapon attachment or release evidence is asserted.",
}

def get_profile():
    return PROFILE
