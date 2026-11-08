"""Vendor zoo packages for authored ground-animal donors.

These are complete zoo1030 families already on disk. Region joints and capture
axes are derived from the live package names. Generated-artifact only.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from paths import REPO, VENDOR_DEMO
from vendor_reference import load_complete_package, package_paths

PADDED_DUMMY_ROOT = REPO / "artifacts/homm3_mocap_v2/full_set_mocap_idle0_v1/padded_dummies"

ZOO_PACKAGES: dict[str, dict[str, str]] = {
    "zoo_horse": {"refSeq": "Horse#HorseALL-Attack/y0", "character": "Horse"},
    "zoo_anaconda": {"refSeq": "Anaconda#AnacondaALL-Attack/y0", "character": "Anaconda"},
    "zoo_mammoth": {"refSeq": "Mammoth#Mammoth-Bellow/y0", "character": "Mammoth"},
    "zoo_hound": {"refSeq": "Dog#Dog-Idle/y0", "character": "Dog"},
    "zoo_crocodile": {"refSeq": "Crocodile#Crocodile-Attack/y0", "character": "Crocodile"},
    "zoo_buffalo": {"refSeq": "Buffalo#Buffalo-AlertIdle/y0", "character": "Buffalo"},
    "zoo_goat": {"refSeq": "Goat#Goat-Attack/y0", "character": "Goat"},
    "zoo_turtle": {"refSeq": "Turtle#Turtle-Attack/y0", "character": "Turtle"},
    "zoo_bear": {"refSeq": "BrownBear#BEAR-Attack/y0", "character": "BrownBear"},
    "zoo_dragon": {"refSeq": "Dragon#Wyvern-Attack/y0", "character": "Dragon"},
    "zoo_coyote": {"refSeq": "Coyote#Coyote-Attack1/y0", "character": "Coyote"},
}


def _first(names: set[str], *candidates: str) -> str:
    for name in candidates:
        if name in names:
            return name
    raise ValueError(f"none of {candidates} exist in {sorted(names)[:12]}")


def region_joints_for(names: list[str]) -> dict[str, tuple[str, ...]]:
    helper = {"Null", "C_ctrl", "Bip01", "BN_center"}
    groups: dict[str, list[str]] = {
        "torso": [],
        "neck_head": [],
        "leg_left": [],
        "leg_right": [],
        "arm_left": [],
        "arm_right": [],
        "tail": [],
        "extra": [],
    }
    for name in names:
        if name in helper:
            groups["extra"].append(name)
            continue
        if name.startswith("BN_Tail") or name.startswith("BN_Tai") or name.startswith("BN_Spline"):
            groups["tail"].append(name)
        elif name.startswith(("Bip01_L_Thigh", "Bip01_L_Calf", "Bip01_L_Horse", "Bip01_L_Foot", "Bip01_L_Toe", "NPC_LLeg", "NPC_L_Toe", "NPC_LThigh")):
            groups["leg_left"].append(name)
        elif name.startswith(("Bip01_R_Thigh", "Bip01_R_Calf", "Bip01_R_Horse", "Bip01_R_Foot", "Bip01_R_Toe", "NPC_RLeg", "NPC_R_Toe", "NPC_RThigh")):
            groups["leg_right"].append(name)
        elif name.startswith(("Bip01_L_Clav", "Bip01_L_Upper", "Bip01_L_Fore", "Bip01_L_Hand", "Bip01_L_Finger", "NPC_LArm")):
            groups["arm_left"].append(name)
        elif name.startswith(("Bip01_R_Clav", "Bip01_R_Upper", "Bip01_R_Fore", "Bip01_R_Hand", "Bip01_R_Finger", "NPC_RArm")):
            groups["arm_right"].append(name)
        elif "Neck" in name or "Head" in name or name.startswith(("BN_Head", "BN_Neck", "BN_Jaw", "Bip01_Jaw", "NPC_Head", "NPC_Jaw")):
            groups["neck_head"].append(name)
        elif name in {"Hips", "Bip01_Pelvis", "NPC_Pelvis"} or name.startswith(("Bip01_Spine", "NPC_Spine", "NPC_Ribcage")):
            groups["torso"].append(name)
        else:
            groups["extra"].append(name)
    out = {key: tuple(values) for key, values in groups.items() if values}
    if "torso" not in out:
        raise ValueError(f"zoo package has no torso joints among {names[:16]}")
    return out


def capture_bind_for(names: list[str]) -> dict[str, Any]:
    present = set(names)
    head = _first(present, "Bip01_Head", "BN_Head", "BN_Head_01", "NPC_Head", "Bip01_Neck1", "Bip01_Neck")
    left = _first(
        present,
        "Bip01_L_Thigh",
        "Bip01_L_Clavicle",
        "NPC_LLeg1",
        "NPC_LArm1",
        "BN_Tail_04",
        "BN_Spline_03",
    )
    right = _first(
        present,
        "Bip01_R_Thigh",
        "Bip01_R_Clavicle",
        "NPC_RLeg1",
        "NPC_RArm1",
        "BN_Tail_10",
        "BN_Spline_06",
    )
    return {
        "headJoint": head,
        "leftJoint": left,
        "rightJoint": right,
        "meshBodyAxis": (0.0, 0.0, 1.0),
        "meshSecondAxis": (0.0, 1.0, 0.0),
        "skinFrozenRegions": (),
    }


def load_zoo_package(unit: str, donor_id: str) -> dict[str, Any]:
    spec = ZOO_PACKAGES.get(donor_id)
    if spec is None:
        raise ValueError(f"{unit}: unknown zoo donor {donor_id!r}")
    package = load_complete_package("zoo", spec["refSeq"])
    package["unit"] = unit
    package["candidateRole"] = "primary"
    package["laneDefault"] = False
    package["demoDonorId"] = donor_id
    package["kind"] = "zoo"
    package["refSeq"] = spec["refSeq"]
    package["why"] = f"authored zoo donor {donor_id} ({spec['refSeq']})"
    return package


def zoo_profile(unit: str, mesh, donor_id: str, mesh_sha256: str) -> dict[str, Any]:
    spec = ZOO_PACKAGES[donor_id]
    package = load_zoo_package(unit, donor_id)
    names = list(package["jointNames"])
    return {
        "assetId": unit,
        "displayName": unit,
        "mesh": mesh,
        "expectedMeshSha256": mesh_sha256,
        "donorKind": "zoo",
        "donorRefSeq": spec["refSeq"],
        "donorCharacterDir": VENDOR_DEMO / "zoo1030" / "characters_fix_facezplus" / spec["character"],
        "donorBindSource": "capture_bvh_offsets",
        "regionJoints": region_joints_for(names),
        "captureBind": capture_bind_for(names),
        "syntheticMotionOnly": True,
        "laneProfile": f"authored_{donor_id}",
    }


def _hardlink(src: Path, dst: Path) -> None:
    src = src.resolve()
    dst = dst.resolve()
    if not src.is_file():
        raise FileNotFoundError(src)
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists() or dst.is_symlink():
        if src.samefile(dst):
            return
        dst.unlink()
    try:
        dst.hardlink_to(src)
    except OSError:
        dst.write_bytes(src.read_bytes())


def pad_package_to_capacity(package: dict[str, Any], needed_frames: int) -> dict[str, Any]:
    """Hold the last pose in a staged vendor dummy the cascade actually loads.

    Numpy-only padding does not change ``bvh_pose/{ref}.npz``. The vendor batch
    builder reads that file and truncates the sprite reel to it.
    """
    pose = np.asarray(package["posePosition"], dtype=np.float64)
    rot = np.asarray(package["poseRot6d"], dtype=np.float64)
    if pose.ndim != 3 or rot.ndim != 3:
        raise ValueError("posePosition/poseRot6d must be [F,J,C]")
    if pose.shape[0] != rot.shape[0]:
        raise ValueError("pose and rot6d lengths disagree")
    # Vendor truncates one frame, so dummy length must be needed+1.
    want = int(needed_frames) + 1
    if pose.shape[0] >= want:
        return package
    extra = want - pose.shape[0]
    padded_pose = np.concatenate([pose, np.repeat(pose[-1:], extra, axis=0)], axis=0)
    padded_rot = np.concatenate([rot, np.repeat(rot[-1:], extra, axis=0)], axis=0)
    kind = str(package["kind"])
    ref_seq = str(package["refSeq"])
    src = package_paths(kind, ref_seq)
    token = f"{kind}_{ref_seq.replace('/', '_').replace('#', '_')}_f{want}"
    staging = PADDED_DUMMY_ROOT / token
    pose_out = staging / "bvh_pose" / f"{ref_seq}.npz"
    pose_out.parent.mkdir(parents=True, exist_ok=True)
    np.savez(pose_out, position=padded_pose.astype(np.float32), rot6d=padded_rot.astype(np.float32))
    _hardlink(Path(src["bvh"]), staging / "bvh" / f"{ref_seq}.bvh")
    _hardlink(Path(src["train"]), staging / "npz_train_image_only" / f"{ref_seq}.npz")
    _hardlink(Path(src["speciesInfo"]), staging / "species_info_dict.npy")
    _hardlink(Path(src["scaleCache"]), staging / "cache" / "__mesh2pose1002_species_scale_cache.pkl")
    padded = dict(package)
    padded["posePosition"] = padded_pose
    padded["poseRot6d"] = padded_rot
    padded["shortDonorPaddedFrames"] = extra
    padded["vendorBaseDir"] = str(staging.resolve()).replace("\\", "/")
    padded["unmodifiedVendorReference"] = False
    padded["why"] = f"{package.get('why') or ref_seq}; held last dummy pose +{extra} for a {needed_frames}-frame reel"
    return padded
