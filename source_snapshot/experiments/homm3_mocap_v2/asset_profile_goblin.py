"""Goblin source-mapped candidate profile; CPU preparation only until reviewed."""
from __future__ import annotations

from copy import deepcopy
import sys
from pathlib import Path

if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    from .asset_profile_hobgoblin import HOBGOBLIN_MIXAMO
except ImportError:
    from asset_profile_hobgoblin import HOBGOBLIN_MIXAMO

ROOT = Path(__file__).resolve().parents[2]
GOBLIN_MESH = ROOT / "artifacts/meshy_downloads/h3_goblin_smartrigged.glb"
GOBLIN_SHA256 = "9210950c1990323c61af29cc112221853a902b89aa60ef90ab854acc22c41d49"

REGION_BONES = {
    "torso": ("Bone_000", "Bone_001", "Bone_004", "Bone_003", "Bone_002"),
    "neck_head": ("Bone_017", "Bone_016", "Bone_015", "Bone_028", "Bone_029", "Bone_030", "Bone_031", "Bone_032", "Bone_033", "Bone_034", "Bone_035", "Bone_036", "Bone_037"),
    "arm_left": ("Bone_022", "Bone_021", "Bone_020", "Bone_019", "Bone_018", "Bone_038", "Bone_039", "Bone_040", "Bone_041", "Bone_042", "Bone_043", "Bone_044", "Bone_045", "Bone_046", "Bone_047", "Bone_048", "Bone_049", "Bone_050", "Bone_051", "Bone_052", "Bone_053", "Bone_054", "Bone_055", "Bone_056", "Bone_057"),
    "arm_right": ("Bone_027", "Bone_026", "Bone_025", "Bone_024", "Bone_023", "Bone_058", "Bone_059", "Bone_060", "Bone_061", "Bone_062", "Bone_063", "Bone_064", "Bone_065", "Bone_066", "Bone_067", "Bone_068", "Bone_069", "Bone_070", "Bone_071", "Bone_072", "Bone_073", "Bone_074", "Bone_075", "Bone_076", "Bone_077"),
    "weapon": ("Bone_079", "Bone_078"),
    "leg_left": ("Bone_014", "Bone_013", "Bone_012", "Bone_011", "Bone_010"),
    "leg_right": ("Bone_009", "Bone_008", "Bone_007", "Bone_006", "Bone_005"),
}


def get_profile() -> dict:
    profile = deepcopy(HOBGOBLIN_MIXAMO)
    profile.update({"assetId": "h3_goblin", "displayName": "Goblin", "mesh": GOBLIN_MESH,
                    "expectedMeshSha256": GOBLIN_SHA256, "regionBones": REGION_BONES,
                    "extraTargetBones": (), "visualAcceptance": "unreviewed_candidate"})
    mapping = {}
    for bone in REGION_BONES["torso"]:
        mapping[bone] = "mixamorig:Hips" if bone in REGION_BONES["torso"][:2] else "mixamorig:Spine"
    mapping.update({bone: "mixamorig:Head" for bone in REGION_BONES["neck_head"]})
    mapping.update({bone: "mixamorig:LeftHand" for bone in REGION_BONES["arm_left"]})
    mapping.update({bone: "mixamorig:RightHand" for bone in REGION_BONES["arm_right"]})
    mapping.update({bone: "mixamorig:RightHand" for bone in REGION_BONES["weapon"]})
    mapping.update({bone: "mixamorig:LeftToeBase" for bone in REGION_BONES["leg_left"]})
    mapping.update({bone: "mixamorig:RightToeBase" for bone in REGION_BONES["leg_right"]})
    # Terminal details collapse to their owning hand/head/foot; articulated
    # proximal source bones must retain the corresponding moving donor joint.
    mapping.update({
        'Bone_004':'mixamorig:Spine','Bone_003':'mixamorig:Spine1','Bone_002':'mixamorig:Spine2',
        'Bone_017':'mixamorig:Neck',
        'Bone_022':'mixamorig:LeftShoulder','Bone_021':'mixamorig:LeftArm','Bone_020':'mixamorig:LeftForeArm',
        'Bone_027':'mixamorig:RightShoulder','Bone_026':'mixamorig:RightArm','Bone_025':'mixamorig:RightForeArm',
        'Bone_014':'mixamorig:LeftUpLeg','Bone_013':'mixamorig:LeftLeg','Bone_012':'mixamorig:LeftFoot',
        'Bone_009':'mixamorig:RightUpLeg','Bone_008':'mixamorig:RightLeg','Bone_007':'mixamorig:RightFoot',
    })
    profile["sourceJointMap"] = mapping
    profile["rigidAttachments"] = ({"region": "weapon", "donorJoints": ("mixamorig:RightHand",), "reason": "club is a rigid prop"},)
    profile["chains"] = tuple({**chain, "evidence": tuple("Bone_079" if x == "Bone_024" else x for x in chain.get("evidence", ())),
                               "donor": tuple(chain.get("donor", ()))} if chain.get("name") == "arm_right" else chain
                              for chain in profile["chains"])
    profile["leftRightPairs"] = tuple({**pair, "evidence": ("Bone_019", "Bone_079")} if pair["donor"][-1] == "mixamorig:RightHand" else pair
                                      for pair in profile["leftRightPairs"])
    return profile


GOBLIN_MIXAMO = get_profile()

if __name__ == "__main__":
    print(GOBLIN_MIXAMO)
