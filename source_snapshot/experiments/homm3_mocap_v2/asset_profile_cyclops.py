"""Explicit CPU-audited profile for the standard Cyclops SmartRig mesh."""
from __future__ import annotations
from pathlib import Path
import sys
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    from .asset_profiles import MIXAMO_REF_SEQ, MIXAMO_SPECIES, MIXAMO_REGION_JOINTS
    from .paths import MESHY, VENDOR_DEMO
except ImportError:
    from asset_profiles import MIXAMO_REF_SEQ, MIXAMO_SPECIES, MIXAMO_REGION_JOINTS
    from paths import MESHY, VENDOR_DEMO

CYCLOPS_MESH = MESHY / "h3_cyclops_smartrigged.glb"
CYCLOPS_SOURCE_IDLE = Path("V:/SteamLibrary/steamapps/common/Heroes of Might and Magic Olden Era - Golden Era/BepInEx/plugins/OfflineUnlockMod/homm3_lab/h3_cyclops/extracted_battle_source_12fps/CCYCLR.dir")
CYCLOPS_SHA256 = "b1d7b588c78833e4f6d1687d93075d5aa69d81feb7c25e9c6ba669ed06544248"

REGION_BONES = {
    "torso": ("Bone_000", "Bone_001", "Bone_005", "Bone_004", "Bone_003", "Bone_002"),
    "neck_head": ("Bone_018", "Bone_017", "Bone_016"),
    "arm_left": ("Bone_028", "Bone_027", "Bone_026", "Bone_025", "Bone_024", "Bone_039", "Bone_043", "Bone_038", "Bone_042", "Bone_037", "Bone_041", "Bone_036", "Bone_040"),
    "arm_right": ("Bone_023", "Bone_022", "Bone_021", "Bone_020", "Bone_019", "Bone_032", "Bone_031", "Bone_030", "Bone_029", "Bone_035", "Bone_034", "Bone_033"),
    "leg_left": ("Bone_015", "Bone_014", "Bone_013", "Bone_012", "Bone_011"),
    "leg_right": ("Bone_010", "Bone_009", "Bone_008", "Bone_007", "Bone_006"),
}

def _mapped():
    m = {b: "mixamorig:Hips" for b in REGION_BONES["torso"][:2]}
    m.update({"Bone_005":"mixamorig:Spine", "Bone_004":"mixamorig:Spine1", "Bone_003":"mixamorig:Spine2", "Bone_002":"mixamorig:Spine2", "Bone_018":"mixamorig:Neck", "Bone_017":"mixamorig:Head", "Bone_016":"mixamorig:HeadTop_End"})
    m.update({"Bone_028":"mixamorig:LeftShoulder", "Bone_027":"mixamorig:LeftArm", "Bone_026":"mixamorig:LeftForeArm", "Bone_025":"mixamorig:LeftHand", "Bone_024":"mixamorig:LeftHand"})
    m.update({"Bone_023":"mixamorig:RightShoulder", "Bone_022":"mixamorig:RightArm", "Bone_021":"mixamorig:RightForeArm", "Bone_020":"mixamorig:RightHand", "Bone_019":"mixamorig:RightHand"})
    m.update({b: "mixamorig:LeftHand" for b in REGION_BONES["arm_left"][5:]})
    m.update({b: "mixamorig:RightHand" for b in REGION_BONES["arm_right"][5:]})
    m.update({"Bone_015":"mixamorig:LeftUpLeg", "Bone_014":"mixamorig:LeftLeg", "Bone_013":"mixamorig:LeftFoot", "Bone_012":"mixamorig:LeftToeBase", "Bone_011":"mixamorig:LeftToeBase"})
    m.update({"Bone_010":"mixamorig:RightUpLeg", "Bone_009":"mixamorig:RightLeg", "Bone_008":"mixamorig:RightFoot", "Bone_007":"mixamorig:RightToeBase", "Bone_006":"mixamorig:RightToeBase"})
    return m

CYLOPS_MIXAMO = {
    "assetId":"h3_cyclops", "displayName":"Cyclops", "mesh":CYCLOPS_MESH, "expectedMeshSha256":CYCLOPS_SHA256,
    "donorKind":"obj", "donorRefSeq":MIXAMO_REF_SEQ, "donorCharacterDir":VENDOR_DEMO / "obj1k" / "characters" / MIXAMO_SPECIES,
    "donorBindSource":"ffs_bvh_capture_scale", "sourceIdleDir":CYCLOPS_SOURCE_IDLE, "sourceIdleGroup":2, "sourceIdleFrameCount":6,
    "regionJoints":MIXAMO_REGION_JOINTS, "regionBones":REGION_BONES, "headBone":"Bone_017", "neckBone":"Bone_018",
    "requireCompleteRegionCoverage":True, "sourceJointMap":_mapped(), "skinInitialization":"source_joint_map", "rigidAttachments":(),
    "hubs":{"mixamorig:Hips":"Bone_001", "mixamorig:Spine":"Bone_005", "mixamorig:Spine1":"Bone_004", "mixamorig:Spine2":"Bone_003"},
    "chains":(
        {"name":"neck", "kind":"polyline", "donor":("mixamorig:Neck","mixamorig:Head"), "evidence":("Bone_018","Bone_017")},
        {"name":"head_end", "kind":"relative_to_parent", "donor":("mixamorig:HeadTop_End",), "anchor":"mixamorig:Head", "region":"neck_head", "helper":True},
        {"name":"arm_left", "kind":"polyline", "donor":("mixamorig:LeftShoulder","mixamorig:LeftArm","mixamorig:LeftForeArm","mixamorig:LeftHand"), "evidence":("Bone_028","Bone_027","Bone_026","Bone_025")},
        {"name":"arm_right", "kind":"polyline", "donor":("mixamorig:RightShoulder","mixamorig:RightArm","mixamorig:RightForeArm","mixamorig:RightHand"), "evidence":("Bone_023","Bone_022","Bone_021","Bone_020")},
        {"name":"leg_left", "kind":"polyline", "donor":("mixamorig:LeftUpLeg","mixamorig:LeftLeg","mixamorig:LeftFoot","mixamorig:LeftToeBase"), "evidence":("Bone_015","Bone_014","Bone_013","Bone_012")},
        {"name":"leg_right", "kind":"polyline", "donor":("mixamorig:RightUpLeg","mixamorig:RightLeg","mixamorig:RightFoot","mixamorig:RightToeBase"), "evidence":("Bone_010","Bone_009","Bone_008","Bone_007")},
        {"name":"toe_left", "kind":"relative_to_parent", "donor":("mixamorig:LeftToe_End",), "anchor":"mixamorig:LeftToeBase", "region":"leg_left", "helper":True},
        {"name":"toe_right", "kind":"relative_to_parent", "donor":("mixamorig:RightToe_End",), "anchor":"mixamorig:RightToeBase", "region":"leg_right", "helper":True},
    ),
    "leftRightPairs":({"donor":("mixamorig:LeftHand","mixamorig:RightHand"),"evidence":("Bone_025","Bone_020")},{"donor":("mixamorig:LeftFoot","mixamorig:RightFoot"),"evidence":("Bone_013","Bone_008")}),
    "requiredBranches":("torso","neck_head","arm_left","arm_right","leg_left","leg_right"), "extraTargetBones":(),
    "wholeBodyHubs":("mixamorig:Hips","mixamorig:Spine2","mixamorig:Head","mixamorig:LeftShoulder","mixamorig:RightShoulder","mixamorig:LeftUpLeg","mixamorig:RightUpLeg"),
    "actuation":(("shoulder_L","mixamorig:LeftArm","arm_left","arm_right"),("forearm_L","mixamorig:LeftForeArm","arm_left","arm_right"),("thigh_L","mixamorig:LeftUpLeg","leg_left","leg_right"),("spine","mixamorig:Spine1","torso","leg_right")),
    "syntheticMotionOnly":True, "visualAcceptance":"unreviewed_candidate", "anatomyEvidence":"CPU rest-world hierarchy audit: positive-X is left, negative-X is right; no terminal bone is promoted to wrist. No independent rock-release evidence is asserted.",
}

def get_profile():
    return CYLOPS_MIXAMO
