"""Shape-preserved preparation profile for the standard Behemoth.

The installed source idle is a hunched, two-legged creature with paired long
arms; it is not a quadruped.  The old ``behemoth_smartrig_anatomy_groups``
labels therefore are intentionally not reused here.  This profile keeps the
donor as the known complete Mixamo biped and maps only the target chains that
are supported by the current owned bind.  The exact DEF directory is retained
as provenance even when a checkout does not contain the extracted payload.
"""
from __future__ import annotations

from pathlib import Path

from paths import MESHY, REPO, VENDOR_DEMO
from asset_profiles import MIXAMO_REF_SEQ, MIXAMO_SPECIES, MIXAMO_REGION_JOINTS

BEHEMOTH_SOURCE_IDLE = (
    Path("V:/")
    / "SteamLibrary/steamapps/common/Heroes of Might and Magic Olden Era - Golden Era"
    / "BepInEx/plugins/OfflineUnlockMod/homm3_lab/h3_behemoth"
    / "extracted_battle_source_12fps/CYBEHE.dir"
)

BEHEMOTH_REGION_BONES = {
    "torso": ("Bone_000", "Bone_001", "Bone_012", "Bone_011", "Bone_010"),
    # Bone_010 is the chest hub.  The proximal Bone_027 chain and its two
    # short forks are the cranial silhouette; the old file mislabeled them
    # as a forelimb.  Every distal fork is retained in its owning region.
    "neck_head": ("Bone_027", "Bone_026", "Bone_025", "Bone_039", "Bone_038", "Bone_041", "Bone_040"),
    "arm_left": ("Bone_032", "Bone_031", "Bone_030", "Bone_029", "Bone_028", "Bone_044", "Bone_043", "Bone_047", "Bone_046", "Bone_042", "Bone_045"),
    "arm_right": ("Bone_037", "Bone_036", "Bone_035", "Bone_034", "Bone_033", "Bone_050", "Bone_049", "Bone_053", "Bone_052", "Bone_056", "Bone_055", "Bone_054", "Bone_048", "Bone_051"),
    "leg_left": ("Bone_009", "Bone_008", "Bone_007", "Bone_006", "Bone_024", "Bone_023", "Bone_022", "Bone_021", "Bone_020", "Bone_019"),
    "leg_right": ("Bone_005", "Bone_004", "Bone_003", "Bone_002", "Bone_015", "Bone_014", "Bone_013", "Bone_018", "Bone_017", "Bone_016"),
}

BEHEMOTH_MIXAMO = {
    "assetId": "h3_behemoth",
    "displayName": "Behemoth",
    "mesh": MESHY / "h3_behemoth_smartrigged.glb",
    "expectedMeshSha256": "7f07fe873e24c342f0afbb02779ed88aa334ab4a00d2e987155e954b0daa72c7",
    "donorKind": "obj",
    "donorRefSeq": MIXAMO_REF_SEQ,
    "donorCharacterDir": VENDOR_DEMO / "obj1k" / "characters" / MIXAMO_SPECIES,
    "donorBindSource": "ffs_bvh_capture_scale",
    "sourceIdleDir": BEHEMOTH_SOURCE_IDLE,
    "sourceIdleGroup": 2,
    "sourceIdleFrameCount": 8,
    "regionJoints": MIXAMO_REGION_JOINTS,
    "regionBones": BEHEMOTH_REGION_BONES,
    "headBone": "Bone_025",
    "neckBone": "Bone_027",
    "requireCompleteRegionCoverage": True,
    "hubs": {
        "mixamorig:Hips": "Bone_001",
        "mixamorig:Spine": "Bone_012",
        "mixamorig:Spine1": "Bone_011",
        "mixamorig:Spine2": "Bone_010",
    },
    "chains": (
        {"name": "neck", "kind": "polyline", "donor": ("mixamorig:Neck", "mixamorig:Head"), "evidence": ("Bone_027", "Bone_025")},
        {"name": "head_end", "kind": "relative_to_parent", "donor": ("mixamorig:HeadTop_End",), "anchor": "mixamorig:Head", "region": "neck_head", "helper": True},
        {"name": "arm_left", "kind": "polyline", "donor": ("mixamorig:LeftShoulder", "mixamorig:LeftArm", "mixamorig:LeftForeArm", "mixamorig:LeftHand"), "evidence": ("Bone_032", "Bone_031", "Bone_030", "Bone_029")},
        {"name": "arm_right", "kind": "polyline", "donor": ("mixamorig:RightShoulder", "mixamorig:RightArm", "mixamorig:RightForeArm", "mixamorig:RightHand"), "evidence": ("Bone_037", "Bone_036", "Bone_035", "Bone_034")},
        {"name": "leg_left", "kind": "polyline", "donor": ("mixamorig:LeftUpLeg", "mixamorig:LeftLeg", "mixamorig:LeftFoot", "mixamorig:LeftToeBase"), "evidence": ("Bone_009", "Bone_008", "Bone_007", "Bone_006")},
        {"name": "leg_right", "kind": "polyline", "donor": ("mixamorig:RightUpLeg", "mixamorig:RightLeg", "mixamorig:RightFoot", "mixamorig:RightToeBase"), "evidence": ("Bone_005", "Bone_004", "Bone_003", "Bone_002")},
        {"name": "toe_end_left", "kind": "relative_to_parent", "donor": ("mixamorig:LeftToe_End",), "anchor": "mixamorig:LeftToeBase", "region": "leg_left", "helper": True},
        {"name": "toe_end_right", "kind": "relative_to_parent", "donor": ("mixamorig:RightToe_End",), "anchor": "mixamorig:RightToeBase", "region": "leg_right", "helper": True},
    ),
    "leftRightPairs": (
        {"donor": ("mixamorig:LeftHand", "mixamorig:RightHand"), "evidence": ("Bone_029", "Bone_034")},
        {"donor": ("mixamorig:LeftFoot", "mixamorig:RightFoot"), "evidence": ("Bone_007", "Bone_003")},
    ),
    "requiredBranches": ("torso", "neck_head", "arm_left", "arm_right", "leg_left", "leg_right"),
    "actuation": (
        ("shoulder_L", "mixamorig:LeftArm", "arm_left", "arm_right"),
        ("forearm_L", "mixamorig:LeftForeArm", "arm_left", "arm_right"),
        ("thigh_L", "mixamorig:LeftUpLeg", "leg_left", "leg_right"),
        ("spine", "mixamorig:Spine1", "torso", "leg_right"),
    ),
    "wholeBodyHubs": (
        "mixamorig:Hips", "mixamorig:Spine2", "mixamorig:Head",
        "mixamorig:LeftShoulder", "mixamorig:RightShoulder",
        "mixamorig:LeftUpLeg", "mixamorig:RightUpLeg",
    ),
    "syntheticMotionOnly": True,
    "anatomyEvidence": "source idle visually audited as hunched biped; generic Bone_* limb mapping remains preparation evidence, not runtime proof",
}

# Explicit source-skin remapping initializes the optimization without a human
# surface proxy. Distal fingers/claws follow the hand; no finger motion invented.
BEHEMOTH_MIXAMO["skinInitialization"] = "source_joint_map"
BEHEMOTH_MIXAMO["sourceJointMap"] = {
    **{bone: "mixamorig:Head" for bone in BEHEMOTH_REGION_BONES["neck_head"]},
    **{bone: "mixamorig:LeftHand" for bone in BEHEMOTH_REGION_BONES["arm_left"]},
    **{bone: "mixamorig:RightHand" for bone in BEHEMOTH_REGION_BONES["arm_right"]},
    **{bone: "mixamorig:LeftToeBase" for bone in BEHEMOTH_REGION_BONES["leg_left"]},
    **{bone: "mixamorig:RightToeBase" for bone in BEHEMOTH_REGION_BONES["leg_right"]},
    "Bone_000": "mixamorig:Hips", "Bone_001": "mixamorig:Hips",
    "Bone_012": "mixamorig:Spine", "Bone_011": "mixamorig:Spine1", "Bone_010": "mixamorig:Spine2",
    "Bone_027": "mixamorig:Neck",
    "Bone_032": "mixamorig:LeftShoulder", "Bone_031": "mixamorig:LeftArm", "Bone_030": "mixamorig:LeftForeArm",
    "Bone_037": "mixamorig:RightShoulder", "Bone_036": "mixamorig:RightArm", "Bone_035": "mixamorig:RightForeArm",
    "Bone_009": "mixamorig:LeftUpLeg", "Bone_008": "mixamorig:LeftLeg", "Bone_007": "mixamorig:LeftFoot",
    "Bone_005": "mixamorig:RightUpLeg", "Bone_004": "mixamorig:RightLeg", "Bone_003": "mixamorig:RightFoot",
}
