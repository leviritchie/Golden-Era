#!/usr/bin/env python3
"""Audit generated skin weights for unintended left/right mixing.

This is a diagnostic, not a repair policy.  It reports how much of each
vertex is owned by left and right joint families and fails closed when the
weight matrix is malformed.  A high mixed-vertex count is evidence for a
weight/ownership problem; it does not by itself prove that a mesh was
mirrored.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np


def _decode_names(values: Any) -> list[str]:
    return [value.decode("utf-8") if isinstance(value, bytes) else str(value) for value in values]


def _side(name: str) -> str | None:
    token = str(name).lower()
    if any(mark in token for mark in ("left", "_l_", ":l_", ".l", "_l")):
        return "left"
    if any(mark in token for mark in ("right", "_r_", ":r_", ".r", "_r")):
        return "right"
    return None


def audit(
    weights_path: Path,
    *,
    mixed_threshold: float = 0.1,
    regions_path: Path | None = None,
    mesh_path: Path | None = None,
    bind_report_path: Path | None = None,
    capture_path: Path | None = None,
) -> dict[str, Any]:
    raw = np.load(weights_path, allow_pickle=False)
    if "weights" not in raw or "names" not in raw:
        raise ValueError(f"{weights_path} must contain weights and names arrays")
    weights = np.asarray(raw["weights"], dtype=np.float64)
    names = _decode_names(np.asarray(raw["names"]).tolist())
    if weights.ndim != 2 or weights.shape[1] != len(names):
        raise ValueError(f"weights shape {weights.shape} does not match {len(names)} joint names")
    if not np.isfinite(weights).all() or np.any(weights < -1e-8):
        raise ValueError("weights must be finite and nonnegative")
    row_sums = weights.sum(axis=1)
    if np.any(row_sums <= 1e-8) or np.any(np.abs(row_sums - 1.0) > 2e-3):
        raise ValueError("weights must be normalized per vertex")

    left = np.asarray([_side(name) == "left" for name in names], dtype=bool)
    right = np.asarray([_side(name) == "right" for name in names], dtype=bool)
    if not left.any() or not right.any():
        raise ValueError("joint names do not contain both left and right families")
    left_mass = weights[:, left].sum(axis=1)
    right_mass = weights[:, right].sum(axis=1)
    mixed = (left_mass >= mixed_threshold) & (right_mass >= mixed_threshold)
    left_dominant = left_mass > 0.5
    right_dominant = right_mass > 0.5
    result: dict[str, Any] = {
        "schema": "homm3.bilateral-weight-audit.v1",
        "weights": str(weights_path).replace("\\", "/"),
        "vertexCount": int(len(weights)),
        "jointCount": int(len(names)),
        "leftJoints": [name for name, is_left in zip(names, left) if is_left],
        "rightJoints": [name for name, is_right in zip(names, right) if is_right],
        "mixedThreshold": float(mixed_threshold),
        "mixedVertexCount": int(mixed.sum()),
        "mixedVertexFraction": float(mixed.mean()),
        "leftDominantVertexCount": int(left_dominant.sum()),
        "rightDominantVertexCount": int(right_dominant.sum()),
        "unownedSideVertexCount": int((~left_dominant & ~right_dominant).sum()),
        "maxRightMassOnLeftDominant": float(right_mass[left_dominant].max(initial=0.0)),
        "maxLeftMassOnRightDominant": float(left_mass[right_dominant].max(initial=0.0)),
        "meanLeftMass": float(left_mass.mean()),
        "meanRightMass": float(right_mass.mean()),
        "proof": "generated-artifact diagnostic; mixed weights are not proof of a global mirror",
    }
    if regions_path is not None:
        regions_payload = json.loads(regions_path.read_text(encoding="utf-8"))
        region_names = [str(value) for value in regions_payload.get("regions") or ()]
        if len(region_names) != len(weights):
            raise ValueError(f"regions length {len(region_names)} does not match vertex count {len(weights)}")
        bilateral_regions: dict[str, dict[str, Any]] = {}
        for region in ("wing_left", "wing_right", "leg_left", "leg_right"):
            mask = np.asarray([value == region for value in region_names], dtype=bool)
            if not mask.any():
                continue
            bilateral_regions[region] = {
                "vertexCount": int(mask.sum()),
                "meanOwnSideMass": float((left_mass[mask] if region.endswith("left") else right_mass[mask]).mean()),
                "meanOppositeSideMass": float((right_mass[mask] if region.endswith("left") else left_mass[mask]).mean()),
                "oppositeSideOverThreshold": int(((right_mass if region.endswith("left") else left_mass)[mask] >= mixed_threshold).sum()),
            }
        result["regionSideAudit"] = bilateral_regions
        result["regions"] = str(regions_path).replace("\\", "/")
        if mesh_path is not None or bind_report_path is not None:
            if mesh_path is None or bind_report_path is None:
                raise ValueError("--mesh and --bind-report must be supplied together")
            import sys

            experiment = Path(__file__).resolve().parents[2] / "experiments" / "homm3_mocap_v2"
            if str(experiment) not in sys.path:
                sys.path.insert(0, str(experiment))
            from roc_copy import _load_unskinned_triangle_surface

            surface = _load_unskinned_triangle_surface(mesh_path)
            bind_report = json.loads(bind_report_path.read_text(encoding="utf-8"))
            alignment = bind_report.get("surfaceAlignment") or {}
            rotation = np.asarray(alignment.get("rotation"), dtype=np.float64)
            translation = np.asarray(alignment.get("translation"), dtype=np.float64)
            scale = float(alignment.get("scale"))
            if rotation.shape != (3, 3) or translation.shape != (3,) or not np.isfinite(scale):
                raise ValueError("bind report has no finite surfaceAlignment")
            vertices = scale * (np.asarray(surface["vertices"], dtype=np.float64) @ rotation.T) + translation
            if len(vertices) != len(region_names):
                raise ValueError(f"mesh vertex count {len(vertices)} does not match regions {len(region_names)}")
            geometry_regions: dict[str, dict[str, Any]] = {}
            for region in ("wing_left", "wing_right", "leg_left", "leg_right"):
                mask = np.asarray([value == region for value in region_names], dtype=bool)
                if not mask.any():
                    continue
                x = vertices[mask, 0]
                geometry_regions[region] = {
                    "meanCaptureX": float(x.mean()),
                    "positiveXFraction": float((x > 0.0).mean()),
                    "negativeXFraction": float((x < 0.0).mean()),
                }
            result["regionGeometryAudit"] = geometry_regions
            result["mesh"] = str(mesh_path).replace("\\", "/")
            result["bindReport"] = str(bind_report_path).replace("\\", "/")
    if capture_path is not None:
        capture = np.load(capture_path, allow_pickle=False)
        capture_names = _decode_names(np.asarray(capture["joint_names"]).tolist())
        positions = np.asarray(capture["pred_position"], dtype=np.float64)
        if positions.ndim != 3 or positions.shape[1] != len(capture_names):
            raise ValueError("capture pred_position shape does not match joint_names")
        bind = positions[0]
        capture_x: dict[str, Any] = {}
        for side, names_for_side in (("left", left), ("right", right)):
            indices = [index for index, name in enumerate(capture_names) if _side(name) == side]
            if indices:
                capture_x[side] = {
                    "jointCount": len(indices),
                    "meanBindX": float(bind[indices, 0].mean()),
                    "minBindX": float(bind[indices, 0].min()),
                    "maxBindX": float(bind[indices, 0].max()),
                }
        result["captureSideAudit"] = capture_x
        result["capture"] = str(capture_path).replace("\\", "/")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--weights", type=Path, required=True)
    parser.add_argument("--mixed-threshold", type=float, default=0.1)
    parser.add_argument("--regions", type=Path)
    parser.add_argument("--mesh", type=Path)
    parser.add_argument("--bind-report", type=Path)
    parser.add_argument("--capture", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = audit(
        args.weights,
        mixed_threshold=float(args.mixed_threshold),
        regions_path=args.regions,
        mesh_path=args.mesh,
        bind_report_path=args.bind_report,
        capture_path=args.capture,
    )
    payload = json.dumps(result, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
