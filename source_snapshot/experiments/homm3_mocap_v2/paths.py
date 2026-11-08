"""Isolated MoCapAnything V2 experiment paths.

This lane is a generated-artifact experiment. It does not deploy to Olden Era.
"""
from __future__ import annotations

from pathlib import Path

REPO = Path(r"V:/Games/Olden Era Playtest Tweak")
EXPERIMENT = REPO / "experiments" / "homm3_mocap_v2"
ARTIFACTS = REPO / "artifacts" / "homm3_mocap_v2"
VENDOR = ARTIFACTS / "vendor" / "MocapAnything"
CHECKPOINTS = ARTIFACTS / "checkpoints"
CHECKPOINT_FILE = CHECKPOINTS / "video2pos2rot_epoch60.pt"
DATA = ARTIFACTS / "data"
RUNS = ARTIFACTS / "runs"
CACHE = ARTIFACTS / "cache"
MESHY = REPO / "artifacts" / "meshy_downloads"
POSE_RUNS = REPO / "artifacts" / "pose_picker_runs"

VENDOR_INFERENCE_YAML = VENDOR / "configs" / "inference" / "inference_video2pose2rot.yaml"
MAX_JOINTS = 150
MAX_SEQ_LEN = 301
SOURCE_FRAME_MS = 1000 / 12
KEEP_AUTHORITY = "mocap_v2_temporal_proposal"
WEAVE_KEEP_AUTHORITY = "hybrid_dinov2"
MOCAP_BASELINE = ARTIFACTS / "mocap_baseline"
MOCAP_DIAGNOSIS = ARTIFACTS / "mocap_diagnosis"
MOCAP_INTERMEDIATE = ARTIFACTS / "mocap_intermediate"
MOCAP_EAGLE_SKINNED = ARTIFACTS / "eagle_skinned_roc"
MOCAP_KEEP_AUTHORITY = "mocap_v2_pretrained_baseline"
INTERMEDIATE_KEEP_AUTHORITY = "mocap_v2_intermediate_vendor_skeleton"
EAGLE_SKINNED_KEEP_AUTHORITY = "mocap_v2_roc_copy_skinned_to_eagle_capture"
SHAPE_PRESERVED_KEEP_AUTHORITY = "mocap_v2_shape_preserved_fitted_bind"
BONE_ENVELOPE_KEEP_AUTHORITY = "mocap_v2_skeleton_first_envelope_from_sprites"
OWNED_FLESH_KEEP_AUTHORITY = "mocap_v2_bone_owned_occupancy_sheet"
MOCAP_SHAPE_PRESERVED = ARTIFACTS / "shape_preserved"
MOCAP_BONE_ENVELOPE = ARTIFACTS / "roc_bone_envelope"
MOCAP_OWNED_MESH = ARTIFACTS / "roc_owned_mesh"
MOCAP_ARTICULATED_RECONSTRUCT = ARTIFACTS / "articulated_reconstruct"
VENDOR_DEMO = VENDOR / "demo" / "data"


def require_file(path: Path, *, label: str) -> Path:
    if not path.is_file():
        raise FileNotFoundError(f"{label} is missing: {path}")
    return path


def require_dir(path: Path, *, label: str) -> Path:
    if not path.is_dir():
        raise FileNotFoundError(f"{label} is missing: {path}")
    return path
