"""Build a common-frame Archer experiment instead of comparing mismatched rest poses.

The original source is an idle-pose surface.  Meshy 7.1's selected Archer candidate is a T-pose
surface.  Assigning both the same synthetic T-pose skeleton makes the source baseline absorb a
large rest-pose error.  This experiment reposes the original source through its existing registered
owned bind, rebases the captured motion into that same T-pose, and transfers the known source skin
onto the regenerated surface by nearest-surface correspondence.

This is deliberately an experimental quality lane.  It emits a three-way measurement artifact:
the untouched registered source remains the production control, while the reposed source and
Meshy candidate are compared in one reference-space T-pose.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from scipy.spatial import cKDTree

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT / "artifacts/homm3_owned_bind"))

import preview_exact_reference_bind as pv  # noqa: E402
from owned_rerig.exact_bind import (  # noqa: E402
    driver_transforms,
    replay_deformed_vertices,
)
from owned_rerig.glb_io import load_render_surface, write_skinned_mesh  # noqa: E402
from owned_rerig.pose_source import load_registered_pose_source  # noqa: E402
from owned_rerig.tpose import edge_stretch, tpose_joint_track  # noqa: E402

SCHEMA = "meshy71.archer_reference_space.v1"


def plain(value: object) -> object:
    if isinstance(value, np.ndarray):
        return np.asarray(value, dtype=np.float64).round(8).tolist()
    if isinstance(value, (np.floating, np.integer)):
        return value.item()
    raise TypeError(f"not JSON serializable: {type(value).__name__}")


def load_tracks(run_dir: Path, clip: str) -> np.ndarray:
    capture = run_dir / "linked_master/capture/capture/raw_capture.npz"
    sequence = run_dir / "linked_master/master_sequence/master_sequence.json"
    registration = next(
        (
            path
            for path in (
                run_dir / "linked_master_remaining_scale/idle0_registration.json",
                run_dir / "linked_master/idle0_registration.json",
            )
            if path.is_file()
        ),
        None,
    )
    if registration is None:
        raise FileNotFoundError(f"no registration under {run_dir}")
    pose = load_registered_pose_source(
        capture=capture,
        registration=registration,
        master_sequence=sequence,
        segment_index=None,
        clip_key=clip,
        max_frames=None,
    )
    return pose.similarity.apply(pose.capture_positions[pose.capture_indices])


def canonical_tracks(
    *, source_heads: np.ndarray, target_heads: np.ndarray, original_tracks: np.ndarray, parents: list[int | None]
) -> np.ndarray:
    """Apply the original source-rest motion after changing the rest skeleton to T-pose."""
    canonical_rotation, canonical_offset = driver_transforms(
        heads=source_heads,
        parents=parents,
        frame_joints=target_heads,
    )
    out: list[np.ndarray] = []
    for frame in original_tracks:
        motion_rotation, motion_offset = driver_transforms(
            heads=source_heads,
            parents=parents,
            frame_joints=frame,
        )
        # D = G o C^-1: preserve the source motion's twist convention after rebasing.
        rebased_rotation = np.einsum("nij,nkj->nik", motion_rotation, canonical_rotation)
        rebased_offset = motion_offset - np.einsum(
            "nij,nj->ni", rebased_rotation, canonical_offset
        )
        out.append(
            np.einsum("nij,nj->ni", rebased_rotation, target_heads) + rebased_offset
        )
    return np.asarray(out, dtype=np.float64)


def nearest_weight_transfer(
    *, target_positions: np.ndarray, source_positions: np.ndarray, source_joints: np.ndarray, source_weights: np.ndarray
) -> tuple[np.ndarray, np.ndarray, dict]:
    """Transfer the registered source skin over a regenerated surface in common T-pose space."""
    tree = cKDTree(source_positions)
    distances, neighbours = tree.query(target_positions, k=min(8, len(source_positions)))
    distances = np.atleast_2d(distances)
    neighbours = np.atleast_2d(neighbours)
    kernel = 1.0 / np.maximum(distances, 1e-7) ** 2
    kernel /= kernel.sum(axis=1, keepdims=True)
    dense = np.zeros((len(target_positions), int(source_joints.max()) + 1), dtype=np.float64)
    # The source has only four influences per vertex; accumulate the local barycentric proxy.
    for slot in range(source_joints.shape[1]):
        np.add.at(
            dense,
            (np.arange(len(target_positions))[:, None], source_joints[neighbours, slot]),
            kernel * source_weights[neighbours, slot],
        )
    order = np.argsort(-dense, axis=1)[:, :4]
    weights = np.take_along_axis(dense, order, axis=1)
    weights /= np.maximum(weights.sum(axis=1, keepdims=True), 1e-12)
    report = {
        "rule": "eight-nearest-source-vertices-in-common-tpose-space",
        "meanNearestDistance": float(np.mean(distances[:, 0])),
        "p95NearestDistance": float(np.percentile(distances[:, 0], 95)),
        "maxNearestDistance": float(np.max(distances[:, 0])),
    }
    return order.astype(np.int32), weights, report


def orient_and_scale_candidate(*, candidate: np.ndarray, source_tpose: np.ndarray) -> tuple[np.ndarray, dict]:
    """Try four facing orientations and choose the one whose extents best match the source T-pose."""
    source_extent = np.ptp(source_tpose, axis=0)
    source_center = (source_tpose.min(axis=0) + source_tpose.max(axis=0)) * 0.5
    candidate_extent = np.ptp(candidate, axis=0)
    body_scale = float(source_extent[1] / max(candidate_extent[1], 1e-9))
    best: tuple[float, np.ndarray, dict] | None = None
    for yaw in (0, 90, 180, 270):
        angle = np.radians(yaw)
        rotation = np.array(
            [[np.cos(angle), 0.0, -np.sin(angle)], [0.0, 1.0, 0.0], [np.sin(angle), 0.0, np.cos(angle)]]
        )
        rotated = candidate @ rotation.T
        scaled = rotated * body_scale
        center = (scaled.min(axis=0) + scaled.max(axis=0)) * 0.5
        aligned = scaled + (source_center - center)
        extent = np.ptp(aligned, axis=0)
        score = float(abs(extent[0] - source_extent[0]) + abs(extent[2] - source_extent[2]))
        row = {"yaw": yaw, "score": score, "scale": body_scale, "extent": extent}
        if best is None or score < best[0]:
            best = (score, aligned, row)
    assert best is not None
    return best[1], {"chosen": best[2], "sourceExtent": source_extent, "candidateExtent": candidate_extent}


def run(args: argparse.Namespace) -> int:
    run_dir = Path(args.run_dir).resolve()
    source_bind_path = Path(args.source_bind).resolve()
    candidate_path = Path(args.candidate_mesh).resolve()
    source = pv.load_delivered_skeleton(source_bind_path)
    candidate_surface = load_render_surface(candidate_path)
    candidate_positions = np.asarray(candidate_surface["positions"], dtype=np.float64)
    source_positions = np.asarray(source["positions"], dtype=np.float64)
    source_heads = np.asarray(source["heads"], dtype=np.float64)
    parents = list(source["parents"])
    tpose = tpose_joint_track(
        rest=source_heads, parents=parents, joint_names=list(source["names"])
    )
    tpose_heads = np.asarray(tpose["joints"], dtype=np.float64)
    source_tpose = replay_deformed_vertices(
        positions=source_positions,
        heads=source_heads,
        parents=parents,
        joints=source["joints"],
        weights=source["weights"],
        frame_joints=tpose_heads,
    )
    aligned_candidate, alignment = orient_and_scale_candidate(
        candidate=candidate_positions, source_tpose=source_tpose
    )
    transferred_joints, transferred_weights, transfer = nearest_weight_transfer(
        target_positions=aligned_candidate,
        source_positions=source_tpose,
        source_joints=source["joints"],
        source_weights=source["weights"],
    )
    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    source_out = out_dir / "archer_source_reposed_tpose.glb"
    candidate_out = out_dir / "archer_meshy71_aligned_source_weights.glb"
    extras = {
        "experimentSchema": SCHEMA,
        "bindPose": "reference_space_canonical_tpose",
        "skinSource": "registered_archer_source_nearest_surface_transfer",
    }
    write_skinned_mesh(
        source_out,
        positions=source_tpose,
        indices=source["indices"],
        bone_names=[str(name) for name in source["names"]],
        parents=parents,
        heads=tpose_heads,
        joints=source["joints"],
        weights=source["weights"],
        source_glb=source_bind_path,
        extras=extras,
    )
    write_skinned_mesh(
        candidate_out,
        positions=aligned_candidate,
        indices=np.asarray(candidate_surface["indices"], dtype=np.int64),
        bone_names=[str(name) for name in source["names"]],
        parents=parents,
        heads=tpose_heads,
        joints=transferred_joints,
        weights=transferred_weights,
        source_glb=candidate_path,
        extras=extras,
    )
    master = json.loads(
        (run_dir / "linked_master/master_sequence/master_sequence.json").read_text(encoding="utf-8")
    )
    clips = [str(segment["clipKey"]) for segment in master["segments"] if str(segment["role"]) != "bookend"]
    rows = []
    for clip in clips:
        original = load_tracks(run_dir, clip)
        tracks = canonical_tracks(
            source_heads=source_heads,
            target_heads=tpose_heads,
            original_tracks=original,
            parents=parents,
        )
        source_frames = [
            replay_deformed_vertices(
                positions=source_tpose,
                heads=tpose_heads,
                parents=parents,
                joints=source["joints"],
                weights=source["weights"],
                frame_joints=frame,
            )
            for frame in tracks
        ]
        candidate_frames = [
            replay_deformed_vertices(
                positions=aligned_candidate,
                heads=tpose_heads,
                parents=parents,
                joints=transferred_joints,
                weights=transferred_weights,
                frame_joints=frame,
            )
            for frame in tracks
        ]
        source_edges = [
            edge_stretch(
                positions=source_tpose,
                indices=np.asarray(source["indices"]),
                deformed=frame,
                subject_height=float(np.ptp(source_tpose[:, 1])),
            )
            for frame in source_frames
        ]
        candidate_edges = [
            edge_stretch(
                positions=aligned_candidate,
                indices=np.asarray(candidate_surface["indices"]),
                deformed=frame,
                subject_height=float(np.ptp(aligned_candidate[:, 1])),
            )
            for frame in candidate_frames
        ]
        rows.append(
            {
                "clip": clip,
                "frames": len(tracks),
                "sourceReposed": {
                    "worstStretch": max(row["max"] for row in source_edges),
                    "worstEdgesPastReviewLimit": max(row["edgesPastReviewLimit"] for row in source_edges),
                },
                "candidateTransferred": {
                    "worstStretch": max(row["max"] for row in candidate_edges),
                    "worstEdgesPastReviewLimit": max(row["edgesPastReviewLimit"] for row in candidate_edges),
                },
            }
        )
    report = {
        "schema": SCHEMA,
        "proof": "generated-artifact",
        "unit": "h3_archer",
        "sourceBind": str(source_bind_path).replace("\\", "/"),
        "candidateMesh": str(candidate_path).replace("\\", "/"),
        "sourceReposed": str(source_out).replace("\\", "/"),
        "candidateTransferred": str(candidate_out).replace("\\", "/"),
        "canonicalTpose": {"boneLengthDrift": tpose["boneLengthDrift"], "worstJointMove": tpose["worstJointMove"]},
        "alignment": alignment,
        "transfer": transfer,
        "clips": rows,
        "motionRebase": "D_frame = G_frame o C_canonical_inverse",
    }
    report_path = out_dir / "experiment_report.json"
    report_path.write_text(json.dumps(report, indent=2, default=plain) + "\n", encoding="utf-8")
    print(json.dumps({"report": str(report_path), "sourceReposed": str(source_out), "candidateTransferred": str(candidate_out)}, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--source-bind", required=True)
    parser.add_argument("--candidate-mesh", required=True)
    parser.add_argument("--out-dir", required=True)
    return run(parser.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
