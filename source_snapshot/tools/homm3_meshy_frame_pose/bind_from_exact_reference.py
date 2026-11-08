#!/usr/bin/env python3
"""Bind an unrigged AI mesh to its own animation using an exact reference.

The reference is the registered mocap capture of the unit's DEF plates
(``experiments/homm3_mocap_v2``): per-frame 3D joints, the capture -> mesh similarity,
the source-view camera, and the plate each frame was observed from.  With that in hand
the bind is solved and then audited against ground truth - every deformed vertex must
stay inside the DEF coverage of every authored frame.

The Meshy/Rodin armature that ships inside the mesh is *never* consumed: it is stripped,
and bone hierarchy, joint placement and skin weights are authored from the reference.
Use ``--strip-out`` to also write the intermediate unskinned mesh.

Example:

  py -3 tools/homm3_meshy_frame_pose/bind_from_exact_reference.py \\
    --run-dir "artifacts/homm3_mocap_v2/full_set_mocap_idle0_v1/runs/h3_wood_elf" \\
    --out-dir "artifacts/homm3_owned_bind/h3_wood_elf/idle0"
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from owned_rerig.animation_bind import mesh_boundary_edges  # noqa: E402
from owned_rerig.exact_bind import (  # noqa: E402
    BIND_SCHEMA,
    ExactBindParams,
    bind_from_exact_reference,
)
from owned_rerig.glb_io import load_mesh, write_skinned_mesh  # noqa: E402
from owned_rerig.pose_source import load_registered_pose_source  # noqa: E402
from owned_rerig.strip import strip_armature  # noqa: E402


def _resolve(value: str | None, default: Path | None) -> Path | None:
    if value is None:
        return default
    path = Path(value)
    return path if path.is_absolute() else (ROOT / path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--run-dir", type=Path, required=True, help="one full-set mocap unit run directory")
    parser.add_argument("--mesh", type=Path, default=None, help="override the mesh the registration names")
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--capture", type=Path, default=None)
    parser.add_argument("--registration", type=Path, default=None)
    parser.add_argument("--master-sequence", type=Path, default=None)
    parser.add_argument("--strip-out", type=Path, default=None)
    parser.add_argument(
        "--clip",
        default=None,
        help="clipKey of the segment to audit (default: the segment containing the bind frame)",
    )
    parser.add_argument("--segment", type=int, default=None, help="segmentIndex to audit")
    parser.add_argument("--max-frames", type=int, default=None)
    parser.add_argument("--max-outside-excess", type=float, default=None)
    parser.add_argument("--rest-adjacent-pose-px", type=float, default=None)
    parser.add_argument(
        "--power",
        type=float,
        default=None,
        help=(
            "sharpness of the position field: a bone's influence falls as (1/distance)^power.  "
            "Lower blends more smoothly across flesh (fewer stretched edges, no seams opened) and "
            "lets distant bones influence a region (a head partly driven by the shoulder); higher "
            "does the opposite.  See docs/homm3_reference_frame_skeleton_binding.md for the sweep."
        ),
    )
    parser.add_argument(
        "--scale-source",
        default="extent",
        choices=("extent", "registered"),
        help=(
            "how the reference scale is decided: `extent` re-derives it from an upright bind pose and "
            "refuses a pose that is not upright, `registered` takes the registration's own scale and "
            "records the geometry caveat (needed for quadrupeds, whose mesh is longer than it is tall)"
        ),
    )
    parser.add_argument(
        "--prop-rigid",
        default="off",
        choices=("off", "platefit"),
        help=(
            "how props are owned: `off` (default) keeps the position field everywhere; `platefit` gives "
            "each prop region to the single bone whose own rigid transform keeps it inside every frame's "
            "plate, leaving alone any region the field already places or that no bone can place"
        ),
    )
    parser.add_argument("--report", type=Path, default=None)
    args = parser.parse_args()

    run_dir = args.run_dir if args.run_dir.is_absolute() else (ROOT / args.run_dir)
    if not run_dir.is_dir():
        raise SystemExit(f"fail-closed: run directory missing: {run_dir}")

    capture = _resolve(str(args.capture) if args.capture else None, run_dir / "linked_master/capture/capture/raw_capture.npz")
    registration = _resolve(
        str(args.registration) if args.registration else None,
        run_dir / "linked_master_remaining_scale/idle0_registration.json",
    )
    master = _resolve(
        str(args.master_sequence) if args.master_sequence else None,
        run_dir / "linked_master/master_sequence/master_sequence.json",
    )
    for label, path in (("capture", capture), ("registration", registration), ("master sequence", master)):
        if path is None or not path.is_file():
            raise SystemExit(f"fail-closed: {label} missing: {path}")

    registration_payload = json.loads(Path(registration).read_text(encoding="utf-8"))
    mesh_path = _resolve(str(args.mesh) if args.mesh else None, Path(str(registration_payload["mesh"])))
    if mesh_path is None or not mesh_path.is_file():
        raise SystemExit(f"fail-closed: mesh missing: {mesh_path}")

    pose = load_registered_pose_source(
        capture=Path(capture),
        registration=Path(registration),
        master_sequence=Path(master),
        segment_index=args.segment,
        clip_key=args.clip,
        max_frames=args.max_frames,
    )

    params = ExactBindParams()
    params.scale_source = str(args.scale_source)
    if args.max_outside_excess is not None:
        params.max_outside_excess_rest_adjacent = float(args.max_outside_excess)
    if args.power is not None:
        if args.power <= 0.0:
            raise SystemExit(f"fail-closed: --power must be positive; got {args.power}")
        params.power = float(args.power)
    params.prop_rigid = str(args.prop_rigid)

    # Work in the mesh's own frame.  The registration and the camera were fitted there, so
    # reorienting would silently invalidate both.
    source = load_mesh(Path(mesh_path))
    had_vendor_skin = bool(source.skin_joints)
    boundary_edges = mesh_boundary_edges(source.indices)

    result = bind_from_exact_reference(
        pose=pose,
        mesh_positions=source.positions,
        mesh_indices=source.indices,
        params=params,
    )

    out_dir = args.out_dir if args.out_dir.is_absolute() else (ROOT / args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    audit = result["audit"]
    prop = result["skin"].get("propRigid")
    # The pose loader's reference payload names the mesh used to create the
    # registration.  When --mesh overrides that asset, the emitted bind report
    # must name the candidate actually skinned, or the readback preview would
    # either caption the wrong surface or refuse the artifact for good reason.
    reference = dict(result["reference"])
    reference["registrationMesh"] = reference.get("mesh")
    reference["mesh"] = str(Path(mesh_path).resolve()).replace("\\", "/")
    report = {
        "schema": BIND_SCHEMA,
        "unit": result["unit"],
        "mesh": str(Path(mesh_path).resolve()).replace("\\", "/"),
        "meshHadVendorSkin": had_vendor_skin,
        "ignoredVendorSkin": True,
        "meshBoundaryEdges": boundary_edges,
        "vertexCount": int(len(source.positions)),
        "triangleCount": int(len(source.indices) // 3),
        "auditOk": bool(audit["ok"]),
        "audit": audit,
        "reference": reference,
        "scaleFit": result["scaleFit"],
        "similarity": result["similarity"],
        "restIdentityMaxError": result["restIdentityMaxError"],
        "jointPlacement": result["jointPlacement"],
        "skin": result["skin"],
        "propRigid": result["skin"].get("propRigid"),
        "params": result["params"],
        "proof": "generated-artifact",
    }
    report_path = _resolve(str(args.report) if args.report else None, out_dir / "owned_bind_report.json")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    glb_path = out_dir / "owned_bind.glb"
    write_skinned_mesh(
        glb_path,
        positions=source.positions,
        indices=source.indices,
        bone_names=result["boneNames"],
        parents=result["parents"],
        heads=result["heads"],
        joints=result["joints"],
        weights=result["weights"],
        source_glb=Path(mesh_path),
        extras={
            "ownedBindSchema": BIND_SCHEMA,
            "referenceCapture": result["reference"]["capture"],
            "referenceRegistration": result["reference"]["registration"],
            "vendorSkinIgnored": True,
        },
    )

    if args.strip_out is not None:
        strip_armature(Path(mesh_path), _resolve(str(args.strip_out), None))

    summary = {
        "ok": bool(audit["ok"]),
        "bones": len(result["boneNames"]),
        "framesAudited": audit["frameCount"],
        "clip": pose.frames[0].clip_key,
        "defGroup": pose.frames[0].def_group,
        "fittedScale": result["scaleFit"]["fittedScale"],
        "registeredScale": result["scaleFit"]["registeredScale"],
        "correctionFactor": result["scaleFit"]["correctionFactor"],
        "extentRatios": result["scaleFit"]["extentRatios"],
        "outsideFractionAtBind": audit["outsideFractionAtBind"],
        "maxOutsideExcess": audit["maxOutsideExcess"],
        "outsideExcessBudget": audit["outsideExcessBudget"],
        "poseExcursionPx": audit["poseExcursionPx"],
        "referenceRigidity": audit["referenceRigidity"],
        "maxEscapedFraction": audit["maxEscapedFraction"],
        "worstFrame": audit["worstFrame"],
        "maxBoneLengthDrift": audit["maxBoneLengthDrift"],
        "tearing": audit["tearing"],
        "containmentProof": audit["containmentProof"],
        "propRigid": None if prop is None else {
            key: prop[key]
            for key in ("rule", "regionsFound", "regionsOwnedRigidly", "verticesOwnedRigidly")
        },
        "issues": audit["issues"],
        "reviewNotes": audit["reviewNotes"],
        "glb": str(glb_path).replace("\\", "/"),
        "report": str(report_path).replace("\\", "/"),
    }
    print(json.dumps(summary, indent=2))
    return 0 if audit["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
