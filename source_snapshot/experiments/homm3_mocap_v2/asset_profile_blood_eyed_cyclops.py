"""Explicit CPU-audited profile for the Blood-Eyed Cyclops SmartRig mesh."""
from __future__ import annotations
from pathlib import Path

from asset_profiles import MIXAMO_REF_SEQ, MIXAMO_SPECIES, MIXAMO_REGION_JOINTS
from paths import MESHY, VENDOR_DEMO

BLOOD_EYED_MESH = MESHY / "toa_blood_eyed_cyclops_smartrigged.glb"
BLOOD_EYED_SOURCE_IDLE = Path(
    "V:/SteamLibrary/steamapps/common/Heroes of Might and Magic Olden Era - Golden Era/"
    "BepInEx/plugins/OfflineUnlockMod/homm3_lab/toa_blood_eyed_cyclops/"
    "extracted_battle_source_12fps/lvl6alt.dir"
)
BLOOD_EYED_SHA256 = "463690c8e9949d594ee2618b7e2cc56620253d27bccf3d01056978ce7cdd7c0b"

REGION_BONES = {
    "torso": ("Bone_000", "Bone_001", "Bone_005", "Bone_004", "Bone_003", "Bone_002"),
    "neck_head": ("Bone_028", "Bone_027", "Bone_026"),
    "arm_left": ("Bone_020", "Bone_019", "Bone_018", "Bone_017", "Bone_016", "Bone_031", "Bone_030", "Bone_029", "Bone_034", "Bone_033", "Bone_032", "Bone_038", "Bone_037", "Bone_036", "Bone_035", "Bone_041", "Bone_040", "Bone_039", "Bone_046", "Bone_045", "Bone_044", "Bone_043", "Bone_042"),
    "arm_right": ("Bone_025", "Bone_024", "Bone_023", "Bone_022", "Bone_021", "Bone_050", "Bone_049", "Bone_048", "Bone_047", "Bone_054", "Bone_053", "Bone_052", "Bone_051", "Bone_058", "Bone_057", "Bone_056", "Bone_055", "Bone_062", "Bone_061", "Bone_060", "Bone_059", "Bone_066", "Bone_065", "Bone_064", "Bone_063"),
    "leg_left": ("Bone_015", "Bone_014", "Bone_013", "Bone_012", "Bone_011"),
    "leg_right": ("Bone_010", "Bone_009", "Bone_008", "Bone_007", "Bone_006"),
}

def _mapped():
    m = {"Bone_000":"mixamorig:Hips", "Bone_001":"mixamorig:Hips", "Bone_005":"mixamorig:Spine", "Bone_004":"mixamorig:Spine1", "Bone_003":"mixamorig:Spine2", "Bone_002":"mixamorig:Spine2", "Bone_028":"mixamorig:Neck", "Bone_027":"mixamorig:Head", "Bone_026":"mixamorig:HeadTop_End"}
    m.update({"Bone_020":"mixamorig:LeftShoulder", "Bone_019":"mixamorig:LeftArm", "Bone_018":"mixamorig:LeftForeArm", "Bone_017":"mixamorig:LeftHand", "Bone_016":"mixamorig:LeftHand"})
    m.update({"Bone_025":"mixamorig:RightShoulder", "Bone_024":"mixamorig:RightArm", "Bone_023":"mixamorig:RightForeArm", "Bone_022":"mixamorig:RightHand", "Bone_021":"mixamorig:RightHand"})
    m.update({b:"mixamorig:LeftHand" for b in REGION_BONES["arm_left"][5:]})
    m.update({b:"mixamorig:RightHand" for b in REGION_BONES["arm_right"][5:]})
    m.update({"Bone_015":"mixamorig:LeftUpLeg", "Bone_014":"mixamorig:LeftLeg", "Bone_013":"mixamorig:LeftFoot", "Bone_012":"mixamorig:LeftToeBase", "Bone_011":"mixamorig:LeftToeBase", "Bone_010":"mixamorig:RightUpLeg", "Bone_009":"mixamorig:RightLeg", "Bone_008":"mixamorig:RightFoot", "Bone_007":"mixamorig:RightToeBase", "Bone_006":"mixamorig:RightToeBase"})
    return m

PROFILE = {
    "assetId":"h3_blood_eyed_cyclops", "displayName":"Blood-Eyed Cyclops", "mesh":BLOOD_EYED_MESH, "expectedMeshSha256":BLOOD_EYED_SHA256,
    "donorKind":"obj", "donorRefSeq":MIXAMO_REF_SEQ, "donorCharacterDir":VENDOR_DEMO / "obj1k" / "characters" / MIXAMO_SPECIES,
    "donorBindSource":"ffs_bvh_capture_scale", "sourceIdleDir":BLOOD_EYED_SOURCE_IDLE, "sourceIdleGroup":2, "sourceIdleFrameCount":6,
    "regionJoints":MIXAMO_REGION_JOINTS, "regionBones":REGION_BONES, "headBone":"Bone_027", "neckBone":"Bone_028",
    "requireCompleteRegionCoverage":True, "sourceJointMap":_mapped(), "skinInitialization":"source_joint_map", "rigidAttachments":(),
    "hubs":{"mixamorig:Hips":"Bone_001", "mixamorig:Spine":"Bone_005", "mixamorig:Spine1":"Bone_004", "mixamorig:Spine2":"Bone_003"},
    "chains":(
        {"name":"neck", "kind":"polyline", "donor":("mixamorig:Neck","mixamorig:Head"), "evidence":("Bone_028","Bone_027")},
        {"name":"head_end", "kind":"relative_to_parent", "donor":("mixamorig:HeadTop_End",), "anchor":"mixamorig:Head", "region":"neck_head", "helper":True},
        {"name":"arm_left", "kind":"polyline", "donor":("mixamorig:LeftShoulder","mixamorig:LeftArm","mixamorig:LeftForeArm","mixamorig:LeftHand"), "evidence":("Bone_020","Bone_019","Bone_018","Bone_017")},
        {"name":"arm_right", "kind":"polyline", "donor":("mixamorig:RightShoulder","mixamorig:RightArm","mixamorig:RightForeArm","mixamorig:RightHand"), "evidence":("Bone_025","Bone_024","Bone_023","Bone_022")},
        {"name":"leg_left", "kind":"polyline", "donor":("mixamorig:LeftUpLeg","mixamorig:LeftLeg","mixamorig:LeftFoot","mixamorig:LeftToeBase"), "evidence":("Bone_015","Bone_014","Bone_013","Bone_012")},
        {"name":"leg_right", "kind":"polyline", "donor":("mixamorig:RightUpLeg","mixamorig:RightLeg","mixamorig:RightFoot","mixamorig:RightToeBase"), "evidence":("Bone_010","Bone_009","Bone_008","Bone_007")},
        {"name":"toe_left", "kind":"relative_to_parent", "donor":("mixamorig:LeftToe_End",), "anchor":"mixamorig:LeftToeBase", "region":"leg_left", "helper":True},
        {"name":"toe_right", "kind":"relative_to_parent", "donor":("mixamorig:RightToe_End",), "anchor":"mixamorig:RightToeBase", "region":"leg_right", "helper":True},
    ),
    "leftRightPairs":({"donor":("mixamorig:LeftHand","mixamorig:RightHand"),"evidence":("Bone_017","Bone_022")},{"donor":("mixamorig:LeftFoot","mixamorig:RightFoot"),"evidence":("Bone_013","Bone_008")}),
    "requiredBranches":("torso","neck_head","arm_left","arm_right","leg_left","leg_right"), "extraTargetBones":(),
    "wholeBodyHubs":("mixamorig:Hips","mixamorig:Spine2","mixamorig:Head","mixamorig:LeftShoulder","mixamorig:RightShoulder","mixamorig:LeftUpLeg","mixamorig:RightUpLeg"),
    "actuation":(("shoulder_L","mixamorig:LeftArm","arm_left","arm_right"),("forearm_L","mixamorig:LeftForeArm","arm_left","arm_right"),("thigh_L","mixamorig:LeftUpLeg","leg_left","leg_right"),("spine","mixamorig:Spine1","torso","leg_right")),
    "syntheticMotionOnly":True, "visualAcceptance":"unreviewed_candidate",
    "anatomyEvidence":"CPU GLB hierarchy audit: positive-X arm is Bone_020 through Bone_017 and negative-X arm is Bone_025 through Bone_022; Bone_017 and Bone_022 are anatomical wrist joints, with same-hand terminal palm/claw joints Bone_016 and Bone_021. Bone_028-027-026 is neck/head/tip. Rock ownership is skinned and has no independent release evidence.",
}

def get_profile():
    return PROFILE
