#!/usr/bin/env python3
"""Shared constants for dense multi-angle bone consensus."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "artifacts/hobgoblin_attack_pose_pipeline/out_dense_skeleton_g11"
SRC = ROOT / "artifacts/hobgoblin_attack_pose_pipeline/source_attack_frames/canonical_group_11"
# Temporally stable nearest-neighbor enlarge of a shared union crop (not GenAI).
SRC_UPSCALED = ROOT / "artifacts/hobgoblin_attack_pose_pipeline/source_attack_frames/canonical_group_11_nn_upscale"
MANIFEST = OUT / "source_manifest.json"

JOINT_ORDER = [
    "Nose",
    "Neck",
    "RShoulder",
    "RElbow",
    "RWrist",
    "WeaponTip",
    "LShoulder",
    "LElbow",
    "LWrist",
    "MidHip",
    "RHip",
    "RKnee",
    "RAnkle",
    "LHip",
    "LKnee",
    "LAnkle",
]

REQUIRED_CORE = [
    "Nose",
    "Neck",
    "MidHip",
    "RShoulder",
    "RElbow",
    "RWrist",
    "WeaponTip",
    "LShoulder",
    "LElbow",
    "LWrist",
]

BONE_EDGES = [
    ("Nose", "Neck"),
    ("Neck", "MidHip"),
    ("Neck", "RShoulder"),
    ("RShoulder", "RElbow"),
    ("RElbow", "RWrist"),
    ("RWrist", "WeaponTip"),
    ("Neck", "LShoulder"),
    ("LShoulder", "LElbow"),
    ("LElbow", "LWrist"),
    ("MidHip", "RHip"),
    ("RHip", "RKnee"),
    ("RKnee", "RAnkle"),
    ("MidHip", "LHip"),
    ("LHip", "LKnee"),
    ("LKnee", "LAnkle"),
]
