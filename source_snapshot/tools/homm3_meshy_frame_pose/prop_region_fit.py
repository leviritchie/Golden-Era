#!/usr/bin/env python3
"""Ask, per prop region, whether any bone can place it inside its own frames' plates.

A prop is geometry the skeleton does not run through, and when the generator fuses one to the wrong
part of a body the sign is stretching.  Before a repair (rigid ownership, cutting the bridging
triangles, deleting the patches) is attempted, this says whether a weighting repair can work at all:
the plates are ground truth for where the unit is in each authored frame, so every flesh bone's own
rigid transform is tried against every frame's plate and the best one is reported.  If even the best
leaves the region outside, no weighting rule can place it and the fault is in the geometry.

Runs on a delivered bind when ``--bind-dir`` is given (cheap, and the way to sweep a whole unit set), or
solves one from the reference when it is not.

Example:

  py -3 tools/homm3_meshy_frame_pose/prop_region_fit.py \\
    --run-dir "artifacts/homm3_mocap_v2/full_set_mocap_idle0_v1/runs/h3_wood_elf" \\
    --bind-dir "artifacts/homm3_owned_bind/h3_wood_elf_positionfield/g15_shoot_front" \\
    --clip g15_shoot_front
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from owned_rerig.exact_bind import ExactBindParams, bind_from_exact_reference  # noqa: E402
from owned_rerig.glb_io import load_mesh  # noqa: E402
from owned_rerig.pose_source import load_registered_pose_source  # noqa: E402
from owned_rerig.prop_fit import PropFitParams, measure_prop_region_fit  # noqa: E402


def _resolve(value: str | None, default: Path | None) -> Path | None:
    if value is None:
        return default
    path = Path(value)
    return path if path.is_absolute() else (ROOT / path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--run-dir", type=Path, required=True, help="one full-set mocap unit run directory")
    parser.add_argument("--clip", default=None, help="clipKey of the segment to measure")
    parser.add_argument("--segment", type=int, default=None, help="segmentIndex to measure")
    parser.add_argument("--max-frames", type=int, default=None)
    parser.add_argument("--mesh", type=Path, default=None, help="override the mesh the registration names")
    parser.add_argument("--bind-dir", type=Path, default=None, help="a delivered owned_bind.glb to measure")
    parser.add_argument("--out-dir", type=Path, default=None, help="write prop_region_fit.json here")
    parser.add_argument("--far-frac", type=float, default=None, help="of subject height (default 0.08)")
    parser.add_argument("--link-frac", type=float, default=None, help="of subject height (default 0.04)")
    parser.add_argument("--min-vertices", type=int, default=None)
    args = parser.parse_args()

    run_dir = args.run_dir if args.run_dir.is_absolute() else (ROOT / args.run_dir)
    if not run_dir.is_dir():
        raise SystemExit(f"fail-closed: run directory missing: {run_dir}")
    capture = run_dir / "linked_master/capture/capture/raw_capture.npz"
    registration = run_dir / "linked_master_remaining_scale/idle0_registration.json"
    master = run_dir / "linked_master/master_sequence/master_sequence.json"
    for label, path in (("capture", capture), ("registration", registration), ("master sequence", master)):
        if not path.is_file():
            raise SystemExit(f"fail-closed: {label} missing: {path}")

    settings = PropFitParams(
        far_frac=args.far_frac if args.far_frac is not None else PropFitParams.far_frac,
        link_frac=args.link_frac if args.link_frac is not None else PropFitParams.link_frac,
        min_vertices=args.min_vertices if args.min_vertices is not None else PropFitParams.min_vertices,
    )

    registration_payload = json.loads(registration.read_text(encoding="utf-8"))
    mesh_path = _resolve(str(args.mesh) if args.mesh else None, Path(str(registration_payload["mesh"])))
    if mesh_path is None or not mesh_path.is_file():
        raise SystemExit(f"fail-closed: mesh missing: {mesh_path}")

    pose = load_registered_pose_source(
        capture=capture,
        registration=registration,
        master_sequence=master,
        segment_index=args.segment,
        clip_key=args.clip,
        max_frames=args.max_frames,
    )
    source = load_mesh(Path(mesh_path))
    params = ExactBindParams()

    if args.bind_dir is not None:
        bind_dir = args.bind_dir if args.bind_dir.is_absolute() else (ROOT / args.bind_dir)
        glb = bind_dir / "owned_bind.glb"
        report_path = bind_dir / "owned_bind_report.json"
        if not glb.is_file() or not report_path.is_file():
            raise SystemExit(f"fail-closed: delivered bind incomplete in {bind_dir}")
        delivered = _load_delivered(glb)
        report_path_text = report_path.read_text(encoding="utf-8")
        json.loads(report_path_text)  # fail-closed: the sibling report must be readable
        result = None
        similarity = _fitted_similarity(pose, source, params)
    else:
        result = bind_from_exact_reference(
            pose=pose,
            mesh_positions=np.asarray(source.positions, dtype=np.float64),
            mesh_indices=np.asarray(source.indices, dtype=np.int64),
            params=params,
        )
        delivered = {
            "names": list(result["boneNames"]),
            "parents": list(result["parents"]),
            "heads": np.asarray(result["heads"], dtype=np.float64),
            "joints": np.asarray(result["joints"], dtype=np.int64),
            "weights": np.asarray(result["weights"], dtype=np.float64),
        }
        # ``result["similarity"]`` is the serialised form; the measurement needs the object, and the
        # fit is deterministic, so it is recomputed the same way the solver made it.
        similarity = _fitted_similarity(pose, source, params)

    measured = measure_prop_region_fit(
        pose=pose,
        similarity=similarity,
        mesh_positions=np.asarray(source.positions, dtype=np.float64),
        mesh_indices=np.asarray(source.indices, dtype=np.int64),
        parents=delivered["parents"],
        bone_names=delivered["names"],
        heads=delivered["heads"],
        joints=delivered["joints"],
        weights=delivered["weights"],
        params=settings,
    )
    if args.out_dir is not None:
        out_dir = args.out_dir if args.out_dir.is_absolute() else (ROOT / args.out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "prop_region_fit.json").write_text(
            json.dumps(measured, indent=2) + "\n", encoding="utf-8"
        )
    print(
        json.dumps(
            {
                "ok": True,
                "clip": pose.frames[0].clip_key,
                "units": "pixels in the frame's own plate",
                "regionCount": measured["regionCount"],
                "unbindableVertices": measured["unbindableVertices"],
                "regions": [
                    {
                        "vertices": row["vertices"],
                        "patches": row["patches"],
                        "fieldWorstPxOutside": row["field"]["worstPxOutside"],
                        "bestBone": row["bestRigid"]["bone"],
                        "bestWorstPxOutside": row["bestRigid"]["worstPxOutside"],
                        "verdict": row["verdict"],
                    }
                    for row in measured["regions"]
                ],
                "reviewNotes": measured["reviewNotes"],
            },
            indent=2,
        )
    )
    return 0


def _fitted_similarity(pose, source, params: ExactBindParams):
    from owned_rerig.exact_bind import fit_reference_scale

    similarity, _scale_fit = fit_reference_scale(
        pose=pose,
        mesh_positions=np.asarray(source.positions, dtype=np.float64),
        mesh_indices=np.asarray(source.indices, dtype=np.int64),
        params=params,
    )
    return similarity


def _load_delivered(glb: Path) -> dict:
    """Read a delivered bind back: its skeleton and its weights, as the export wrote them."""
    import preview_exact_reference_bind as preview

    delivered = preview.load_delivered_skeleton(glb)
    return {
        "names": list(delivered["names"]),
        "parents": list(delivered["parents"]),
        "heads": np.asarray(delivered["heads"], dtype=np.float64),
        "joints": np.asarray(delivered["joints"], dtype=np.int64),
        "weights": np.asarray(delivered["weights"], dtype=np.float64),
    }


if __name__ == "__main__":
    raise SystemExit(main())
