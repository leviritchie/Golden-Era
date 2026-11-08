"""Shahrokh Eagle metadata; generated anatomy, not visual acceptance."""
from donor_eagle import EAGLE_KIND, EAGLE_REF_SEQ, REGION_JOINTS as EAGLE_REGIONS
from paths import MESHY, VENDOR_DEMO

MESH_SHA256 = "ebca5d34894bd0776a5f9a3c58abec2f23945d7f2c438b01a9fb1db1b29b22db"
REGION_JOINTS = dict(EAGLE_REGIONS)
# Full donor coverage is separate from the target's supported skin palette.
REGION_JOINTS["jaw"] = REGION_JOINTS.pop("beak")
for side in ("left", "right"):
    REGION_JOINTS[f"leg_{side}"] = EAGLE_REGIONS[f"leg_{side}"][:4]
    REGION_JOINTS[f"toe_{side}_detail"] = EAGLE_REGIONS[f"leg_{side}"][4:]

REGION_BONES = {
    "torso": ("Bone_000", "Bone_001", "Bone_005", "Bone_004", "Bone_015", "Bone_014"),
    "neck_head": ("Bone_020", "Bone_019", "Bone_018", "Bone_028", "Bone_027"),
    "jaw": ("Bone_030", "Bone_029"),
    "wing_left": ("Bone_023", "Bone_022", "Bone_021", "Bone_033", "Bone_032", "Bone_031", "Bone_036", "Bone_035", "Bone_034"),
    "wing_right": ("Bone_026", "Bone_025", "Bone_024", "Bone_039", "Bone_038", "Bone_037", "Bone_042", "Bone_041", "Bone_040"),
    "leg_left": ("Bone_013", "Bone_012", "Bone_011", "Bone_010"),
    "leg_right": ("Bone_009", "Bone_008", "Bone_007", "Bone_006"),
    "tail": ("Bone_003", "Bone_002", "Bone_017", "Bone_016"),
}
SOURCE_JOINT_MAP = {
    "Bone_000": "Hips", "Bone_001": "Bip01_Pelvis", "Bone_005": "Bip01_Spine",
    "Bone_004": "Bip01_Spine", "Bone_015": "Bip01_Spine1", "Bone_014": "Bip01_Spine1",
    "Bone_020": "Bip01_Neck", "Bone_019": "Bip01_Neck1", "Bone_018": "Bip01_Neck2",
    "Bone_028": "Bip01_Head", "Bone_027": "Bip01_Head", "Bone_030": "BN_Jaw", "Bone_029": "BN_Jaw",
    "Bone_003": "BN_Tai_01", "Bone_002": "BN_Tai_R_02", "Bone_017": "BN_Tai_L_01", "Bone_016": "BN_Tai_L_02",
}
CHAINS = [
    {"name": "neck", "kind": "polyline", "donor": REGION_JOINTS["neck_head"], "evidence": ("Bone_020", "Bone_019", "Bone_018", "Bone_028")},
    {"name": "tail", "kind": "polyline", "donor": ("BN_Tai_01", "BN_Tai_R_01", "BN_Tai_R_02"), "evidence": ("Bone_003", "Bone_002")},
    {"name": "tail_secondary", "kind": "polyline", "donor": ("BN_Tai_L_01", "BN_Tai_L_02"), "evidence": ("Bone_017", "Bone_016")},
]
for side, letter in (("left", "L"), ("right", "R")):
    wing = REGION_BONES[f"wing_{side}"]
    # Keep the actual outer and inner feather forks distinct.
    for bone, suffix in zip(wing, ("01", "02", "03", "03", "04", "04", "05", "06", "06")):
        SOURCE_JOINT_MAP[bone] = f"BN_Wing_{letter}_{suffix}"
    SOURCE_JOINT_MAP.update(zip(REGION_BONES[f"leg_{side}"], REGION_JOINTS[f"leg_{side}"]))
    CHAINS.extend((
        {"name": f"wing_{side}", "kind": "polyline", "donor": tuple(f"BN_Wing_{letter}_{n:02d}" for n in range(1, 5)), "evidence": wing[:6]},
        {"name": f"wing_{side}_trail", "kind": "polyline", "donor": (f"BN_Wing_{letter}_05", f"BN_Wing_{letter}_06"), "evidence": wing[6:]},
        {"name": f"leg_{side}", "kind": "polyline", "donor": REGION_JOINTS[f"leg_{side}"], "evidence": REGION_BONES[f"leg_{side}"]},
        {"name": f"toes_{side}", "kind": "relative_to_parent", "donor": REGION_JOINTS[f"toe_{side}_detail"], "anchor": f"Bip01_{letter}_Foot", "region": f"leg_{side}", "helper": True},
    ))

SHAHROKH_EAGLE = {
    "assetId": "h3_shahrokh", "displayName": "Shahrokh",
    "mesh": MESHY / "toa_shahrokh_smartrigged.glb", "expectedMeshSha256": MESH_SHA256,
    "donorKind": EAGLE_KIND, "donorRefSeq": EAGLE_REF_SEQ,
    "donorCharacterDir": VENDOR_DEMO / "zoo1030" / "characters_fix_facezplus" / "Eagle",
    "donorBindSource": "capture_bvh_offsets", "regionJoints": REGION_JOINTS, "regionBones": REGION_BONES,
    "beakFromHeadQuantile": None, "headBone": "Bone_028", "neckBone": "Bone_020",
    "requireCompleteRegionCoverage": True, "skinInitialization": "source_joint_map",
    "sourceJointMap": SOURCE_JOINT_MAP, "rigidAttachments": (),
    "hubs": {"Hips": "Bone_000", "Bip01_Pelvis": "Bone_001", "Bip01_Spine": "Bone_005", "Bip01_Spine1": "Bone_014", "BN_Jaw": "Bone_030"},
    "chains": tuple(CHAINS), "requiredBranches": tuple(REGION_BONES),
    "leftRightPairs": (
        {"donor": ("BN_Wing_L_04", "BN_Wing_R_04"), "evidence": ("Bone_031", "Bone_037")},
        {"donor": ("Bip01_L_Foot", "Bip01_R_Foot"), "evidence": ("Bone_010", "Bone_006")},
    ),
    "wholeBodyHubs": ("Hips", "Bip01_Spine1", "Bip01_Head", "BN_Wing_L_01", "BN_Wing_R_01", "Bip01_L_Thigh", "Bip01_R_Thigh"),
    "actuation": (("shoulder_L", "BN_Wing_L_01", "wing_left", "wing_right"), ("midwing_L", "BN_Wing_L_03", "wing_left", "wing_right"), ("neck", "Bip01_Neck", "neck_head", "wing_right"), ("tail", "BN_Tai_01", "tail", "wing_left"), ("leg_L", "Bip01_L_Thigh", "leg_left", "wing_right")),
    "extraTargetBones": (), "unsupportedRequiredArticulations": ("independent_toe_and_individual_feather_motion_unproven",),
    "syntheticMotionOnly": True,
}


def get_profile():
    return SHAHROKH_EAGLE
