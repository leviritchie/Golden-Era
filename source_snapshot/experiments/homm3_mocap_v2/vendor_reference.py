"""Complete vendor capture-skeleton packages. Directory presence is not enough.

A package is complete only when skeleton, pose, stored reference embedding,
species tensors, and global scale are all present for the exact ref_seq.
This module never renames joints, reshapes offsets, prunes branches, or
combines skeletons into a new prompt.
"""
from __future__ import annotations

import pickle
import sys
from pathlib import Path
from typing import Any

EXPERIMENT = Path(__file__).resolve().parent
if str(EXPERIMENT) not in sys.path:
    sys.path.insert(0, str(EXPERIMENT))

import numpy as np

from paths import VENDOR, VENDOR_DEMO, require_file
from pin import sha256_file

REQUIRED_SPECIES_FIELDS = ("t5_embedding", "joints_distance", "joint_relation", "static_joints")
REQUIRED_POSE_FIELDS = ("position", "rot6d")
REQUIRED_TRAIN_FIELDS = ("image_embed",)


def _vendor_on_path() -> None:
    vendor = str(VENDOR)
    if vendor not in sys.path:
        sys.path.insert(0, vendor)


def zoo_root() -> Path:
    return VENDOR_DEMO / "zoo1030"


def obj_root() -> Path:
    return VENDOR_DEMO / "obj1k"


def demo_root(kind: str) -> Path:
    if kind == "zoo":
        return zoo_root()
    if kind == "obj":
        return obj_root()
    raise ValueError(f"unknown vendor package kind {kind!r}")


def parse_ref_seq(ref_seq: str) -> tuple[str, str, str]:
    """Return (sequence_id, yaw, species). Sequence id is Species#Clip."""
    text = str(ref_seq).replace("\\", "/").strip()
    if "/" not in text:
        raise ValueError(f"ref_seq must be SequenceId/yaw, got {ref_seq!r}")
    sequence_id, yaw = text.rsplit("/", 1)
    if not yaw.startswith("y") or not yaw[1:].isdigit():
        raise ValueError(f"ref_seq yaw must look like y15, got {yaw!r}")
    species = sequence_id.split("#", 1)[0]
    if not species:
        raise ValueError(f"ref_seq has no species token: {ref_seq!r}")
    return sequence_id, yaw, species


def package_paths(kind: str, ref_seq: str) -> dict[str, Path]:
    parse_ref_seq(ref_seq)
    base = demo_root(kind)
    return {
        "base": base,
        "bvh": base / "bvh" / f"{ref_seq}.bvh",
        "pose": base / "bvh_pose" / f"{ref_seq}.npz",
        "train": base / "npz_train_image_only" / f"{ref_seq}.npz",
        "speciesInfo": base / "species_info_dict.npy",
        "scaleCache": base / "cache" / "__mesh2pose1002_species_scale_cache.pkl",
    }


def bvh_joint_names(bvh_path: Path) -> list[str]:
    """Unmodified ROOT/JOINT names from the vendor BVH text."""
    names: list[str] = []
    for raw in require_file(bvh_path, label="vendor BVH").read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if line.startswith("ROOT ") or line.startswith("JOINT "):
            token = line.split(None, 1)[1].strip()
            if not token:
                raise ValueError(f"{bvh_path} has an empty joint name")
            names.append(token)
    if not names:
        raise ValueError(f"{bvh_path} has no ROOT/JOINT names")
    return names


def load_bvh_skeleton(bvh_path: Path) -> dict[str, Any]:
    """Load the vendor BVH without renaming or pruning."""
    _vendor_on_path()
    from utils import bvh as BVH

    anim, names, _frametime = BVH.load(str(require_file(bvh_path, label="vendor BVH")))
    text_names = bvh_joint_names(bvh_path)
    loaded = [str(name) for name in names]
    if loaded != text_names:
        raise ValueError(
            f"{bvh_path} loader names do not match the BVH text; "
            "refusing to treat a mutated skeleton as a vendor reference"
        )
    parents = np.asarray(anim.parents, dtype=np.int64)
    offsets = np.asarray(anim.offsets, dtype=np.float64)
    if parents.shape[0] != len(loaded) or offsets.shape != (len(loaded), 3):
        raise ValueError(f"{bvh_path} parent/offset rank does not match joint names")
    return {
        "jointNames": loaded,
        "parents": parents,
        "offsets": offsets,
        "anim": anim,
    }


def _species_entry(species_info_path: Path, species: str) -> dict[str, Any]:
    payload = np.load(require_file(species_info_path, label="species_info_dict"), allow_pickle=True).item()
    if species not in payload:
        raise KeyError(f"{species} is missing from {species_info_path}")
    entry = payload[species]
    if not isinstance(entry, dict):
        raise TypeError(f"{species} species_info is not a dict")
    return entry


def _global_scale(scale_path: Path, species: str) -> float:
    with require_file(scale_path, label="species scale cache").open("rb") as handle:
        cache = pickle.load(handle)
    if species not in cache:
        raise KeyError(f"{species} is missing from {scale_path}")
    scale = cache[species].get("global_scale")
    if scale is None:
        raise KeyError(f"{species} has no global_scale in {scale_path}")
    value = float(scale)
    if not np.isfinite(value) or value <= 0:
        raise ValueError(f"{species} global_scale is not a positive finite number: {value}")
    return value


def completeness_report(kind: str, ref_seq: str) -> dict[str, Any]:
    """Inspect files. Missing tensors mean incomplete, even if the folder exists."""
    sequence_id, yaw, species = parse_ref_seq(ref_seq)
    paths = package_paths(kind, ref_seq)
    missing: list[str] = []
    details: dict[str, Any] = {
        "kind": kind,
        "refSeq": ref_seq,
        "sequenceId": sequence_id,
        "yaw": yaw,
        "species": species,
    }
    for key in ("bvh", "pose", "train", "speciesInfo", "scaleCache"):
        path = paths[key]
        details[f"{key}Path"] = str(path).replace("\\", "/")
        if not path.is_file():
            missing.append(key)
    if "pose" not in missing:
        pose = np.load(paths["pose"], allow_pickle=False)
        pose_fields = list(pose.files)
        details["poseFields"] = pose_fields
        for field in REQUIRED_POSE_FIELDS:
            if field not in pose.files:
                missing.append(f"pose.{field}")
            else:
                details[f"pose.{field}Shape"] = list(np.asarray(pose[field]).shape)
        if "position" in pose.files:
            details["jointCount"] = int(np.asarray(pose["position"]).shape[1])
            details["poseFrameCount"] = int(np.asarray(pose["position"]).shape[0])
    if "train" not in missing:
        train = np.load(paths["train"], allow_pickle=False)
        details["trainFields"] = list(train.files)
        if "image_embed" not in train.files:
            missing.append("train.image_embed")
        else:
            details["imageEmbedShape"] = list(np.asarray(train["image_embed"]).shape)
    if "bvh" not in missing:
        try:
            details["bvhJointNames"] = bvh_joint_names(paths["bvh"])
            details["bvhJointCount"] = len(details["bvhJointNames"])
        except ValueError as exc:
            missing.append(f"bvh.names:{exc}")
    if "speciesInfo" not in missing:
        try:
            info = _species_entry(paths["speciesInfo"], species)
            for field in REQUIRED_SPECIES_FIELDS:
                if field not in info:
                    missing.append(f"species_info.{field}")
                else:
                    value = np.asarray(info[field])
                    details[f"species_info.{field}Shape"] = list(value.shape)
            if "static_rot_joints" in info:
                details["species_info.static_rot_jointsShape"] = list(np.asarray(info["static_rot_joints"]).shape)
        except KeyError:
            missing.append("species_info.species")
    if "scaleCache" not in missing:
        try:
            details["globalScale"] = _global_scale(paths["scaleCache"], species)
        except (KeyError, ValueError, TypeError):
            missing.append("global_scale")
    if details.get("jointCount") and details.get("bvhJointCount") and details["jointCount"] != details["bvhJointCount"]:
        missing.append("jointCountMismatch")
    t5_shape = details.get("species_info.t5_embeddingShape")
    if details.get("jointCount") and t5_shape and int(t5_shape[0]) != int(details["jointCount"]):
        missing.append("t5JointCountMismatch")
    character_dir = paths["base"] / "characters_fix_facezplus" / species
    if not character_dir.is_dir():
        character_dir = paths["base"] / "characters" / species
    details["characterDir"] = str(character_dir).replace("\\", "/") if character_dir.is_dir() else None
    details["missing"] = missing
    details["complete"] = not missing
    details["completeMeans"] = (
        "BVH + pose position/rot6d + stored image_embed + species T5/graphs/static + global_scale "
        "for this exact ref_seq. Directory existence is not completeness. "
        "Completeness is not checkpoint training exposure."
    )
    return details


def require_complete_package(kind: str, ref_seq: str) -> dict[str, Any]:
    report = completeness_report(kind, ref_seq)
    if not report["complete"]:
        raise FileNotFoundError(
            f"vendor reference {kind}:{ref_seq} is incomplete: {report['missing']}"
        )
    return report


def load_complete_package(kind: str, ref_seq: str) -> dict[str, Any]:
    """Load tensors from a complete unmodified vendor package."""
    report = require_complete_package(kind, ref_seq)
    paths = package_paths(kind, ref_seq)
    skeleton = load_bvh_skeleton(paths["bvh"])
    pose = np.load(paths["pose"], allow_pickle=False)
    train = np.load(paths["train"], allow_pickle=False)
    info = _species_entry(paths["speciesInfo"], report["species"])
    joint_count = int(report["jointCount"])
    if skeleton["jointNames"] != report["bvhJointNames"]:
        raise ValueError("loaded BVH names drifted from the completeness snapshot")
    image_embed = np.asarray(train["image_embed"], dtype=np.float32)
    if image_embed.ndim == 2:
        image_embed = image_embed[None, ...]
    package = {
        "kind": kind,
        "refSeq": ref_seq,
        "species": report["species"],
        "sequenceId": report["sequenceId"],
        "yaw": report["yaw"],
        "jointCount": joint_count,
        "jointNames": list(skeleton["jointNames"]),
        "parents": np.asarray(skeleton["parents"], dtype=np.int64),
        "offsets": np.asarray(skeleton["offsets"], dtype=np.float64),
        "posePosition": np.asarray(pose["position"], dtype=np.float32),
        "poseRot6d": np.asarray(pose["rot6d"], dtype=np.float32),
        "refImageEmbed": image_embed[0].astype(np.float32),
        "t5": np.asarray(info["t5_embedding"], dtype=np.float32)[:joint_count],
        "graphHop": np.asarray(info["joints_distance"], dtype=np.int64)[:joint_count, :joint_count],
        "graphEdge": np.asarray(info["joint_relation"], dtype=np.int64)[:joint_count, :joint_count],
        "staticJoints": [int(index) for index in np.asarray(info["static_joints"]).reshape(-1)],
        "staticRotJoints": [int(index) for index in np.asarray(info.get("static_rot_joints", [])).reshape(-1)],
        "globalScale": float(report["globalScale"]),
        "fileSha256": {
            "bvh": sha256_file(paths["bvh"]),
            "pose": sha256_file(paths["pose"]),
            "train": sha256_file(paths["train"]),
        },
        "paths": {key: str(path).replace("\\", "/") for key, path in paths.items()},
        "characterDir": report["characterDir"],
        "unmodifiedVendorReference": True,
        "anim": skeleton["anim"],
    }
    return package


def refuse_skeleton_mutation(
    *,
    original_names: list[str],
    proposed_names: list[str] | None = None,
    pruned: bool = False,
    combined: bool = False,
    renamed: bool = False,
) -> None:
    if pruned or combined or renamed:
        raise ValueError(
            "vendor reference skeletons must stay unmodified; "
            "do not rename, prune, or combine them and still call the result a validated vendor reference"
        )
    if proposed_names is not None and list(proposed_names) != list(original_names):
        raise ValueError("refusing a renamed vendor joint list")


def config_name_for_kind(kind: str) -> str:
    if kind == "zoo":
        return "demo_zoo.yaml"
    if kind == "obj":
        return "demo_obj.yaml"
    raise ValueError(f"unknown vendor package kind {kind!r}")
