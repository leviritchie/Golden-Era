#!/usr/bin/env python3
"""Per-chain motion report for solved angel clips.

Clip score says how well the silhouette matched; it says nothing about
*which* bones did the matching. "The feet go all over the place" is a
statement about frame-to-frame travel of the foot joints, so measure
that directly: reconstruct each frame's bind-space skeleton from the
solved pose and report how far each chain's tip moves per frame.

Root translation and root rotation are deliberately excluded. Root motion
moves both feet together and is the intended walk translation; the
complaint is about feet moving relative to the body.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

TOOL = Path(__file__).resolve().parent
if str(TOOL) not in sys.path:
    sys.path.insert(0, str(TOOL))

from roc_geometric_proxy import load_asset  # noqa: E402
from run_angel_wing_dominance_compare import BONE_GROUPS  # noqa: E402

# Tip joint of each chain: the one whose wandering is visible on screen.
CHAIN_TIPS = {
    "head": "Bone_017",
    "wing_left": "Bone_020",
    "wing_right": "Bone_025",
    "leg_left": "Bone_009",
    "leg_right": "Bone_013",
    "hem": "Bone_005",
}


def _quat_to_matrix(quat: Sequence[float]) -> np.ndarray:
    x, y, z, w = (float(value) for value in quat)
    return np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
        ],
        dtype=np.float64,
    )


def _axis_angle_to_matrix(vector: Sequence[float]) -> np.ndarray:
    axis = np.asarray(vector, dtype=np.float64)
    angle = float(np.linalg.norm(axis))
    if angle < 1e-12:
        return np.eye(3)
    axis = axis / angle
    cross = np.array(
        [
            [0.0, -axis[2], axis[1]],
            [axis[2], 0.0, -axis[0]],
            [-axis[1], axis[0], 0.0],
        ]
    )
    return (
        np.eye(3)
        + math.sin(angle) * cross
        + (1.0 - math.cos(angle)) * (cross @ cross)
    )


def _joint_heads(asset: Any, pose: Mapping[str, Any]) -> dict[str, np.ndarray]:
    """Bind-space world head of every node under one solved pose.

    Matches the GPU evaluator: local rotation is the bind rotation
    followed by the solved axis-angle delta.
    """
    by_index = {node.index: node for node in asset.nodes}
    world: dict[int, np.ndarray] = {}

    def local(node: Any) -> np.ndarray:
        entry = pose.get(node.name)
        delta = (
            _axis_angle_to_matrix((entry["x"], entry["y"], entry["z"]))
            if isinstance(entry, Mapping)
            else np.eye(3)
        )
        rotation = _quat_to_matrix(node.rotation) @ delta
        matrix = np.eye(4)
        matrix[:3, :3] = rotation @ np.diag(np.asarray(node.scale, dtype=np.float64))
        matrix[:3, 3] = np.asarray(node.translation, dtype=np.float64)
        return matrix

    def resolve(index: int) -> np.ndarray:
        if index in world:
            return world[index]
        node = by_index[index]
        parent = node.parent
        world[index] = local(node) if parent is None else resolve(int(parent)) @ local(node)
        return world[index]

    return {node.name: resolve(node.index)[:3, 3] for node in asset.nodes}


def _pose_frames(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    poses = payload["poses"]
    return [poses[str(frame)] for frame in payload["frameIndices"]]


def chain_motion(mesh: Path, clip: Path) -> dict[str, Any]:
    asset = load_asset(mesh)
    payload = json.loads(Path(clip).read_text(encoding="utf-8"))
    frames = _pose_frames(payload)
    heads = [_joint_heads(asset, pose) for pose in frames]

    positions = np.asarray(asset.primitives[0].positions, dtype=np.float64)
    body_length = float(positions[:, 1].max() - positions[:, 1].min())
    if body_length <= 0.0:
        raise RuntimeError(f"{mesh.name} has no vertical extent to normalize by")

    pelvis = np.stack([frame["Bone_001"] for frame in heads])
    report: dict[str, Any] = {}
    for chain, tip in CHAIN_TIPS.items():
        tips = np.stack([frame[tip] for frame in heads]) - pelvis
        step = np.linalg.norm(np.diff(tips, axis=0), axis=1) / body_length
        report[chain] = {
            "tip": tip,
            "meanStepBodyLengths": round(float(step.mean()), 4),
            "maxStepBodyLengths": round(float(step.max()), 4),
        }
    rotation: dict[str, float] = {}
    for chain, names in BONE_GROUPS.items():
        degrees = [
            math.degrees(
                float(
                    np.linalg.norm(
                        [pose[name]["x"], pose[name]["y"], pose[name]["z"]]
                    )
                )
            )
            for pose in frames
            for name in names
            if isinstance(pose.get(name), Mapping)
        ]
        rotation[chain] = round(float(np.mean(degrees)) if degrees else 0.0, 2)
    return {
        "clip": str(clip).replace("\\", "/"),
        "score": round(float(payload["score"]), 4),
        "frames": len(frames),
        "tipTravel": report,
        "meanBoneRotationDeg": rotation,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mesh", type=Path, required=True)
    parser.add_argument("--root", type=Path, required=True, help="directory of trial subdirs")
    parser.add_argument("--trials", nargs="+", required=True)
    parser.add_argument("--json-out", type=Path, default=None)
    args = parser.parse_args()

    rows = {}
    for trial in args.trials:
        clip = Path(args.root) / trial / "gpu_clip_result.json"
        if not clip.is_file():
            raise FileNotFoundError(clip)
        rows[trial] = chain_motion(Path(args.mesh), clip)

    header = (
        f"{'trial':12s} {'score':>7s} {'feetStep':>9s} {'wingStep':>9s} "
        f"{'hemStep':>8s} {'legRot':>7s} {'wingRot':>8s}"
    )
    print(header)
    print("-" * len(header))
    for trial, row in rows.items():
        feet = 0.5 * (
            row["tipTravel"]["leg_left"]["meanStepBodyLengths"]
            + row["tipTravel"]["leg_right"]["meanStepBodyLengths"]
        )
        wings = 0.5 * (
            row["tipTravel"]["wing_left"]["meanStepBodyLengths"]
            + row["tipTravel"]["wing_right"]["meanStepBodyLengths"]
        )
        legs_rot = 0.5 * (
            row["meanBoneRotationDeg"]["leg_left"] + row["meanBoneRotationDeg"]["leg_right"]
        )
        wing_rot = 0.5 * (
            row["meanBoneRotationDeg"]["wing_left"] + row["meanBoneRotationDeg"]["wing_right"]
        )
        print(
            f"{trial:12s} {row['score']:7.4f} {feet:9.4f} {wings:9.4f} "
            f"{row['tipTravel']['hem']['meanStepBodyLengths']:8.4f} "
            f"{legs_rot:7.1f} {wing_rot:8.1f}"
        )
    if args.json_out is not None:
        Path(args.json_out).write_text(
            json.dumps(rows, indent=2) + "\n", encoding="utf-8"
        )
        print(f"wrote {args.json_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
