"""Bind and audit a Meshy 7.1 candidate against a registered mocap reference.

This is the promotion gate for regenerated geometry.  Meshy supplies geometry only; the vendor
armature is never trusted.  A candidate requested in ``t-pose`` is bound in a canonical T-pose made
from the registered reference skeleton, then replayed against the reference clips by the existing
owned-bind solver.  The result is generated-artifact evidence, not runtime delivery proof.

The script intentionally supports one explicit pose lane at a time.  It does not silently fall back
to the source mesh, an exporter armature, or the legacy articulation binder when a candidate refuses.
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from owned_rerig.exact_bind import bind_from_exact_reference  # noqa: E402
from owned_rerig.glb_io import load_render_surface, write_skinned_mesh  # noqa: E402
from owned_rerig.pose_source import load_registered_pose_source  # noqa: E402
from owned_rerig.tpose import tpose_joint_track  # noqa: E402

SCHEMA = "meshy71.candidate_bind.v1"


def plain(value: object) -> object:
    if isinstance(value, np.ndarray):
        return np.round(np.asarray(value, dtype=np.float64), 8).tolist()
    if isinstance(value, (np.floating, np.integer)):
        return value.item()
    raise TypeError(f"not JSON serializable: {type(value).__name__}")


def load_mesh(path: Path) -> dict[str, np.ndarray]:
    surface = load_render_surface(path)
    return {
        "positions": np.asarray(surface["positions"], dtype=np.float64),
        "indices": np.asarray(surface["indices"], dtype=np.int64),
    }


def load_pose(run_dir: Path, clip: str, registration_path: Path | None = None):
    capture = run_dir / "linked_master/capture/capture/raw_capture.npz"
    sequence = run_dir / "linked_master/master_sequence/master_sequence.json"
    if registration_path is not None:
        registration = Path(registration_path).resolve()
        if not registration.is_file():
            raise FileNotFoundError(f"fail-closed: explicit idle registration is missing: {registration}")
    else:
        registration_candidates = (
            run_dir / "linked_master_remaining_scale/idle0_registration.json",
            run_dir / "linked_master/idle0_registration.json",
        )
        registration = next((path for path in registration_candidates if path.exists()), None)
        if registration is None:
            raise FileNotFoundError(
                "fail-closed: no linked-master idle registration found in "
                + ", ".join(str(path) for path in registration_candidates)
            )
    return load_registered_pose_source(
        capture=capture,
        registration=registration,
        master_sequence=sequence,
        segment_index=None,
        clip_key=clip,
        max_frames=None,
    )


def canonical_tpose_reference(pose):
    rest_capture = np.asarray(pose.capture_positions[pose.bind_index()], dtype=np.float64)
    rest_mesh = pose.similarity.apply(rest_capture)
    track = tpose_joint_track(
        rest=rest_mesh,
        parents=pose.parents,
        joint_names=pose.joint_names,
    )
    tpose_capture = pose.similarity.inverse_apply(np.asarray(track["joints"], dtype=np.float64))
    return dataclasses.replace(
        pose,
        capture_positions=np.concatenate(
            [pose.capture_positions, tpose_capture[None, :, :]], axis=0
        ),
        bind_frame=int(pose.capture_positions.shape[0]),
    ), track


def bind(args: argparse.Namespace) -> int:
    mesh_path = Path(args.mesh).resolve()
    run_dir = Path(args.run_dir).resolve()
    output_dir = Path(args.output_dir).resolve()
    mesh = load_mesh(mesh_path)
    pose = load_pose(run_dir, args.clip, args.registration)
    pose_report = None
    if args.bind_pose == "canonical-t-pose":
        pose, pose_report = canonical_tpose_reference(pose)
    elif args.bind_pose == "registered-reference":
        # Source-pose candidates retain the captured rest correspondence and must not be
        # compared through the synthetic T-pose rest frame.
        pose_report = {"schema": "registered_reference.v1", "boneLengthDrift": 0.0, "worstJointMove": 0.0}
    else:
        raise ValueError(f"fail-closed: unsupported bind pose {args.bind_pose!r}")

    result = bind_from_exact_reference(
        pose=pose,
        mesh_positions=mesh["positions"],
        mesh_indices=mesh["indices"],
    )
    audit = result["audit"]
    report = {
        "schema": SCHEMA,
        "proof": "generated-artifact",
        "unit": args.unit,
        "candidateVariant": args.variant,
        "mesh": str(mesh_path).replace("\\", "/"),
        "referenceRun": str(run_dir).replace("\\", "/"),
        "referenceClip": args.clip,
        "registration": str(Path(args.registration).resolve()).replace("\\", "/") if args.registration else None,
        "armatureAuthority": "owned_in_repo_after_candidate_audit",
        "bindPose": args.bind_pose,
        "pose": {
            "schema": pose_report["schema"],
            "boneLengthDrift": pose_report["boneLengthDrift"],
            "worstJointMove": pose_report["worstJointMove"],
        },
        "reference": {
            **result["reference"],
            "mesh": str(mesh_path).replace("\\", "/"),
            "sourceMesh": result["reference"].get("mesh"),
        },
        "similarity": result["similarity"],
        "scaleFit": result["scaleFit"],
        "restIdentityMaxError": result["restIdentityMaxError"],
        "vertexCount": int(len(mesh["positions"])),
        "auditOk": bool(audit["ok"]),
        "maxOutsideExcess": audit.get("maxOutsideExcess"),
        "outsideExcessBudget": audit.get("outsideExcessBudget"),
        "audit": {
            "ok": audit["ok"],
            "issues": audit["issues"],
            "reviewNotes": audit["reviewNotes"],
            "containmentProof": audit.get("containmentProof"),
            "maxEscapedFraction": audit.get("maxEscapedFraction"),
            "escapePopulation": audit.get("escapePopulation"),
            "tearing": audit.get("tearing"),
            "cohesion": audit.get("cohesion"),
            "escaping": audit.get("escaping"),
        },
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / f"bind_{args.unit}_{args.variant}.json"
    emitted = None
    if args.emit:
        emitted_path = output_dir / f"owned_bind_{args.unit}_{args.variant}.glb"
        write_skinned_mesh(
            emitted_path,
            positions=mesh["positions"],
            indices=mesh["indices"],
            bone_names=[str(name) for name in result["boneNames"]],
            parents=result["parents"],
            heads=np.asarray(result["heads"], dtype=np.float64),
            joints=np.asarray(result["joints"], dtype=np.int64),
            weights=np.asarray(result["weights"], dtype=np.float64),
            source_glb=mesh_path,
            extras={
                "ownedBindSchema": "exact_reference_owned_bind.v1",
                "candidateBindSchema": SCHEMA,
                "bindPose": args.bind_pose,
                "meshSource": "meshy-7.1",
            },
        )
        emitted = str(emitted_path).replace("\\", "/")
        report["emitted"] = emitted

    report_path.write_text(json.dumps(report, indent=2, default=plain) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "report": str(report_path).replace("\\", "/"),
                "emitted": emitted,
                "restIdentityMaxError": result["restIdentityMaxError"],
                "auditOk": audit["ok"],
                "issueCount": len(audit["issues"]),
                "reviewNoteCount": len(audit["reviewNotes"]),
            },
            indent=2,
            default=plain,
        )
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--unit", required=True)
    parser.add_argument("--variant", required=True)
    parser.add_argument("--mesh", required=True)
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--clip", default="g02_idle")
    parser.add_argument("--registration", type=Path, default=None)
    parser.add_argument(
        "--bind-pose",
        choices=("canonical-t-pose", "registered-reference"),
        default="canonical-t-pose",
    )
    parser.add_argument("--emit", action="store_true")
    args = parser.parse_args()
    return bind(args)


if __name__ == "__main__":
    raise SystemExit(main())
