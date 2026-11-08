"""Explicit shape-preserving profile for the standard Orc mesh.

The SmartRig hierarchy was inspected from the pinned GLB rather than copied
from another unit: the central 008->007->006 chain is the torso, 021->020->019
is the head, and the +/- X five-bone chains are the arms and legs.  Terminal
finger details remain owned by their corresponding hand.
"""
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

ORC_MESH = MESHY / "h3_orc_smartrigged.glb"
ORC_SOURCE_IDLE = Path(
    "V:/SteamLibrary/steamapps/common/Heroes of Might and Magic Olden Era - Golden Era"
    "/BepInEx/plugins/OfflineUnlockMod/homm3_lab/h3_orc"
    "/extracted_battle_source_12fps/CORC.dir"
)
ORC_SHA256 = "b31ea821f9e48ee03d209d177c06d408bb896c90d84c9418caaf0baf23fb3325"

REGION_BONES = {
    # The short 003->002 and 005->004 branches are retained as lower-body
    # source detail; their ownership is deliberately explicit even though
    # the current donor has no corresponding auxiliary joints.
    "torso": ("Bone_000", "Bone_001", "Bone_003", "Bone_002", "Bone_005", "Bone_004", "Bone_008", "Bone_007", "Bone_006"),
    "neck_head": ("Bone_021", "Bone_020", "Bone_019"),
    "arm_left": ("Bone_026", "Bone_025", "Bone_024", "Bone_023", "Bone_022", "Bone_035", "Bone_039", "Bone_043", "Bone_047", "Bone_034", "Bone_038", "Bone_042", "Bone_046", "Bone_033", "Bone_037", "Bone_041", "Bone_045", "Bone_032", "Bone_036", "Bone_040", "Bone_044"),
    "arm_right": ("Bone_031", "Bone_030", "Bone_029", "Bone_028", "Bone_027", "Bone_051", "Bone_055", "Bone_059", "Bone_063", "Bone_065", "Bone_064", "Bone_050", "Bone_054", "Bone_058", "Bone_062", "Bone_049", "Bone_053", "Bone_057", "Bone_061", "Bone_048", "Bone_052", "Bone_056", "Bone_060"),
    "leg_right": ("Bone_013", "Bone_012", "Bone_011", "Bone_010", "Bone_009"),
    "leg_left": ("Bone_018", "Bone_017", "Bone_016", "Bone_015", "Bone_014"),
}


def _mapped() -> dict[str, str]:
    mapping = {
        **{b: "mixamorig:Hips" for b in REGION_BONES["torso"][:6]},
        "Bone_008": "mixamorig:Spine", "Bone_007": "mixamorig:Spine1", "Bone_006": "mixamorig:Spine2",
        "Bone_021": "mixamorig:Neck", "Bone_020": "mixamorig:Head", "Bone_019": "mixamorig:HeadTop_End",
        "Bone_026": "mixamorig:LeftShoulder", "Bone_025": "mixamorig:LeftArm", "Bone_024": "mixamorig:LeftForeArm", "Bone_023": "mixamorig:LeftHand", "Bone_022": "mixamorig:LeftHand",
        "Bone_031": "mixamorig:RightShoulder", "Bone_030": "mixamorig:RightArm", "Bone_029": "mixamorig:RightForeArm", "Bone_028": "mixamorig:RightHand", "Bone_027": "mixamorig:RightHand",
        "Bone_013": "mixamorig:RightUpLeg", "Bone_012": "mixamorig:RightLeg", "Bone_011": "mixamorig:RightFoot", "Bone_010": "mixamorig:RightToeBase", "Bone_009": "mixamorig:RightToeBase",
        "Bone_018": "mixamorig:LeftUpLeg", "Bone_017": "mixamorig:LeftLeg", "Bone_016": "mixamorig:LeftFoot", "Bone_015": "mixamorig:LeftToeBase", "Bone_014": "mixamorig:LeftToeBase",
    }
    for region, donor in (("arm_left", "mixamorig:LeftHand"), ("arm_right", "mixamorig:RightHand")):
        for bone in REGION_BONES[region][5:]:
            mapping[bone] = donor
    return mapping


ORC_MIXAMO = {
    "assetId": "h3_orc", "displayName": "Orc", "mesh": ORC_MESH,
    "expectedMeshSha256": ORC_SHA256, "donorKind": "obj", "donorRefSeq": MIXAMO_REF_SEQ,
    "donorCharacterDir": VENDOR_DEMO / "obj1k" / "characters" / MIXAMO_SPECIES,
    "donorBindSource": "ffs_bvh_capture_scale", "sourceIdleDir": ORC_SOURCE_IDLE,
    "sourceIdleGroup": 2, "sourceIdleFrameCount": 8, "regionJoints": MIXAMO_REGION_JOINTS,
    "regionBones": REGION_BONES, "headBone": "Bone_020", "neckBone": "Bone_021",
    "requireCompleteRegionCoverage": True, "sourceJointMap": _mapped(),
    "hubs": {"mixamorig:Hips": "Bone_001", "mixamorig:Spine": "Bone_008", "mixamorig:Spine1": "Bone_007", "mixamorig:Spine2": "Bone_006"},
    "chains": (
        {"name": "neck", "kind": "polyline", "donor": ("mixamorig:Neck", "mixamorig:Head"), "evidence": ("Bone_021", "Bone_020")},
        {"name": "head_end", "kind": "relative_to_parent", "donor": ("mixamorig:HeadTop_End",), "anchor": "mixamorig:Head", "region": "neck_head", "helper": True},
        {"name": "arm_left", "kind": "polyline", "donor": ("mixamorig:LeftShoulder", "mixamorig:LeftArm", "mixamorig:LeftForeArm", "mixamorig:LeftHand"), "evidence": ("Bone_026", "Bone_025", "Bone_024", "Bone_023")},
        {"name": "arm_right", "kind": "polyline", "donor": ("mixamorig:RightShoulder", "mixamorig:RightArm", "mixamorig:RightForeArm", "mixamorig:RightHand"), "evidence": ("Bone_031", "Bone_030", "Bone_029", "Bone_028")},
        {"name": "leg_left", "kind": "polyline", "donor": ("mixamorig:LeftUpLeg", "mixamorig:LeftLeg", "mixamorig:LeftFoot", "mixamorig:LeftToeBase"), "evidence": ("Bone_018", "Bone_017", "Bone_016", "Bone_015")},
        {"name": "leg_right", "kind": "polyline", "donor": ("mixamorig:RightUpLeg", "mixamorig:RightLeg", "mixamorig:RightFoot", "mixamorig:RightToeBase"), "evidence": ("Bone_013", "Bone_012", "Bone_011", "Bone_010")},
        {"name": "toe_left", "kind": "relative_to_parent", "donor": ("mixamorig:LeftToe_End",), "anchor": "mixamorig:LeftToeBase", "region": "leg_left", "helper": True},
        {"name": "toe_right", "kind": "relative_to_parent", "donor": ("mixamorig:RightToe_End",), "anchor": "mixamorig:RightToeBase", "region": "leg_right", "helper": True},
    ),
    "leftRightPairs": ({"donor": ("mixamorig:LeftHand", "mixamorig:RightHand"), "evidence": ("Bone_023", "Bone_028")}, {"donor": ("mixamorig:LeftFoot", "mixamorig:RightFoot"), "evidence": ("Bone_016", "Bone_011")}),
    "requiredBranches": ("torso", "neck_head", "arm_left", "arm_right", "leg_left", "leg_right"),
    "extraTargetBones": tuple(sorted(set(sum(REGION_BONES.values(), ())) - set(_mapped()))),
    "rigidAttachments": (), "skinInitialization": "source_joint_map",
    "wholeBodyHubs": ("mixamorig:Hips", "mixamorig:Spine2", "mixamorig:Head", "mixamorig:LeftShoulder", "mixamorig:RightShoulder", "mixamorig:LeftUpLeg", "mixamorig:RightUpLeg"),
    "actuation": (("shoulder_L", "mixamorig:LeftArm", "arm_left", "arm_right"), ("forearm_L", "mixamorig:LeftForeArm", "arm_left", "arm_right"), ("thigh_L", "mixamorig:LeftUpLeg", "leg_left", "leg_right"), ("spine", "mixamorig:Spine1", "torso", "leg_right")),
    "syntheticMotionOnly": True, "visualAcceptance": "unreviewed_candidate",
    "anatomyEvidence": "GLB rest-world hierarchy and weighted mesh audited CPU-only; central torso, vertical head, +/-X arms, and +/-X legs are explicit.",
}


def get_profile() -> dict:
    return ORC_MIXAMO


if __name__ == "__main__":
    print(ORC_MIXAMO)
