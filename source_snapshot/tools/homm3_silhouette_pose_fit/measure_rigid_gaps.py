#!/usr/bin/env python3
"""Quantify rigid-armor seam gaps: bind pose vs. an animation clip's frame-0 pose.

Skinned positions are computed from the GLB skin data (JOINTS_0/WEIGHTS_0 +
inverseBindMatrices + node TRS). For every vertex the nearest vertex belonging to
a DIFFERENT owning bone is measured; large nearest-neighbor distances on seam
surfaces are the visible "floating armor pieces / holes" the user reports in
combat (small GIF previews hide them, full-res combat does not).

Usage:
  py -3 measure_rigid_gaps.py --master <master.glb> --clip <clip.glb> --frame 0
"""
from __future__ import annotations

import argparse
import json
import struct
import sys
from pathlib import Path

import numpy as np

from inspect_glb_skinning import _read_glb, _accessor, _node_matrix, _world_matrix


def _skin(doc: dict, bin_chunk: bytes, pose_rotations: dict) -> np.ndarray:
    json_doc = doc["json"]
    skin = json_doc["skins"][0]
    joints = skin["joints"]
    ibm = _accessor(doc, bin_chunk, skin["inverseBindMatrices"]).reshape(-1, 4, 4)
    mesh = json_doc["meshes"][0]
    prim = mesh["primitives"][0]
    positions = _accessor(doc, bin_chunk, prim["attributes"]["POSITION"]).reshape(-1, 3)
    joint_ids = _accessor(doc, bin_chunk, prim["attributes"]["JOINTS_0"]).astype(np.int32).reshape(-1, 4)
    weights = _accessor(doc, bin_chunk, prim["attributes"]["WEIGHTS_0"]).reshape(-1, 4)
    # World matrices per joint at the given pose (rotation override, translation from rest).
    cache: dict = {}
    world = {}
    for j, joint_index in enumerate(joints):
        m = _world_matrix(doc, joint_index, cache)
        if joint_index in pose_rotations:
            # Replace the rotation of this node's local matrix while keeping rest translation/scale.
            q = pose_rotations[joint_index]
            local = _node_matrix(doc, joint_index)
            rest_t = local[:3, 3]
            rest_s = np.array([np.linalg.norm(local[0, :3]), np.linalg.norm(local[1, :3]), np.linalg.norm(local[2, :3])])
            qx, qy, qz, qw = q
            rot = np.eye(4)
            rot[0, 0] = 1 - 2 * (qy * qy + qz * qz)
            rot[0, 1] = 2 * (qx * qy - qz * qw)
            rot[0, 2] = 2 * (qx * qz + qy * qw)
            rot[1, 0] = 2 * (qx * qy + qz * qw)
            rot[1, 1] = 1 - 2 * (qx * qx + qz * qz)
            rot[1, 2] = 2 * (qy * qz - qx * qw)
            rot[2, 0] = 2 * (qx * qz - qy * qw)
            rot[2, 1] = 2 * (qy * qz + qx * qw)
            rot[2, 2] = 1 - 2 * (qx * qx + qy * qy)
            rot[:3, :3] *= rest_s
            rot[:3, 3] = rest_t
            # Find this node's parent world and rebuild the world matrix.
            parents = [i for i, n in enumerate(json_doc["nodes"]) if joint_index in n.get("children", [])]
            parent_world = _world_matrix(doc, parents[0], {}) if parents else np.eye(4)
            m = parent_world @ rot
        world[joint_index] = m
    out = np.zeros_like(positions, dtype=np.float64)
    matrices = {}
    for k, jidx in enumerate(joints):
        # GLB stores IBM column-major; the raw read is transposed relative to the
        # row-major world matrices composed below, so multiply with ibm[k].T.
        matrices[jidx] = world[jidx] @ ibm[k].T
    for c in range(4):
        ids = joint_ids[:, c]
        w = weights[:, c]
        for jidx, mat in matrices.items():
            sel = ids == jidx
            if sel.any():
                out[sel] += (positions[sel] @ mat[:3, :3].T + mat[:3, 3]) * w[sel, None]
    return positions, out, joint_ids[:, 0]


def _clip_frame_rotations(doc: dict, bin_chunk: bytes, frame: int) -> dict:
    json_doc = doc["json"]
    anim = json_doc["animations"][0]
    out = {}
    for channel in anim.get("channels", []):
        sampler = anim["samplers"][channel["sampler"]]
        target = channel["target"]
        if target.get("path") != "rotation":
            continue
        times = _accessor(doc, bin_chunk, sampler["input"])
        quats = _accessor(doc, bin_chunk, sampler["output"]).reshape(-1, 4)
        idx = int(np.argmin(np.abs(times - frame * 1.0)))
        if frame is not None:
            idx = min(int(np.searchsorted(times, frame)), len(times) - 1)
        out[target["node"]] = quats[idx]
    return out


def measure(master_path: Path, clip_path: Path | None, frame: float | None) -> dict:
    doc = _read_glb(master_path)
    rest_pos, rest_skin, owners = _skin(doc, doc["bin"], {})
    skin_error = float(np.max(np.abs(rest_skin - rest_pos)))
    pose_skin = rest_skin
    pose_rotations = {}
    if clip_path is not None:
        cdoc = _read_glb(clip_path)
        pose_rotations = _clip_frame_rotations(cdoc, cdoc["bin"], frame if frame is not None else 0.0)
        _, pose_skin, _ = _skin(doc, doc["bin"], pose_rotations)

    def gaps(pos: np.ndarray) -> dict:
        n = len(pos)
        best = np.full(n, np.inf)
        # Brute force nearest-neighbor across different owners (6972 verts is small).
        for i in range(n):
            d = np.linalg.norm(pos - pos[i], axis=1)
            d[owners == owners[i]] = np.inf
            best[i] = d.min()
        p99 = float(np.percentile(best, 99))
        p95 = float(np.percentile(best, 95))
        return {
            "maxGap": round(float(best.max()), 4),
            "p99Gap": round(p99, 4),
            "p95Gap": round(p95, 4),
            "meanGap": round(float(best.mean()), 4),
            "vertsGapOver2cm": int((best > 0.02).sum()),
            "vertsGapOver5cm": int((best > 0.05).sum()),
        }

    return {
        "rest": gaps(rest_skin),
        "pose": gaps(pose_skin),
        "poseRotationCount": len(pose_rotations),
        "restSkinMaxErrorVsMesh": round(skin_error, 6),
        "seamOpeningP99": round(float(np.percentile(nearest_delta(pose_skin, rest_skin, owners), 99)), 4),
        "seamOpeningP95": round(float(np.percentile(nearest_delta(pose_skin, rest_skin, owners), 95)), 4),
    }


def nearest_delta(pose: np.ndarray, rest: np.ndarray, owners: np.ndarray) -> np.ndarray:
    """For each vertex, |nearest different-owner vertex at pose| - |at rest|; positive means the seam opened."""
    def nearest(pos: np.ndarray) -> np.ndarray:
        n = len(pos)
        best = np.full(n, np.inf)
        for i in range(n):
            d = np.linalg.norm(pos - pos[i], axis=1)
            d[owners == owners[i]] = np.inf
            best[i] = d.min()
        return best
    return nearest(pose) - nearest(rest)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--master", required=True, type=Path)
    parser.add_argument("--clip", type=Path)
    parser.add_argument("--frame", type=float)
    args = parser.parse_args()
    report = measure(args.master.resolve(), args.clip.resolve() if args.clip else None, args.frame)
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
