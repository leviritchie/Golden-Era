"""Deterministic promotion gate for sequence-aware auto-rig candidates.

The gate intentionally consumes reports emitted by the preview/solver lane and
does not inspect pixels or ask a reviewer to choose the least-bad result.  A
candidate must satisfy absolute deformation/retention floors *and* improve on
the matched SmartRig baseline.  This is a rig-quality gate; sprite fidelity is
reported separately and never replaces the 3-D checks here.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np


def _finite_number(value: Any, label: str) -> float:
    number = float(value)
    if not number == number or number in (float("inf"), float("-inf")):
        raise ValueError(f"{label} must be finite")
    return number


def evaluate_reports(
    baseline: dict[str, Any],
    candidate: dict[str, Any],
    *,
    min_relative_improvement: float = 0.05,
    max_bind_error: float = 1e-5,
    min_motion_p05: float = 0.80,
    max_motion_below_floor: float = 0.05,
    min_articulation_p05: float = 0.60,
    max_articulation_below_floor: float = 0.12,
    max_heldout_articulation_regression: float = 0.10,
    max_severe_collapse: float = 0.02,
    max_edge_stretch: float = 0.25,
    require_sidecar: bool = True,
    require_export: bool = True,
    max_image_iou_drop: float = 0.002,
    max_image_alpha_l1_increase: float = 0.002,
    max_image_compactness_increase: float = 0.02,
) -> dict[str, Any]:
    """Return structured pass/fail checks for one matched A/B pair."""
    if not isinstance(baseline, dict) or not isinstance(candidate, dict):
        raise ValueError("baseline and candidate reports must be objects")
    baseline_keys = tuple(baseline.get("clipKeys") or ())
    candidate_keys = tuple(candidate.get("clipKeys") or ())
    checks: list[dict[str, Any]] = []

    def check(name: str, passed: bool, value: Any, requirement: str) -> None:
        checks.append({"name": name, "passed": bool(passed), "value": value, "requirement": requirement})

    check("candidate_mode_explicit", candidate.get("candidateMode") in {"smartrig", "m7"},
          candidate.get("candidateMode"), "candidateMode must be smartrig or m7")
    check("clip_set_matches", baseline_keys == candidate_keys,
          {"baseline": list(baseline_keys), "candidate": list(candidate_keys)}, "identical clipKeys")

    bind_error = _finite_number(candidate.get("idleBindWorldMaxError", float("inf")), "idleBindWorldMaxError")
    check("bind_reconstruction", bind_error <= float(max_bind_error), bind_error,
          f"<= {max_bind_error:g}")

    baseline_strain = _finite_number(
        (baseline.get("selectedSurfaceStrain") or {}).get("total", float("inf")),
        "baseline.selectedSurfaceStrain.total",
    )
    candidate_strain = _finite_number(
        (candidate.get("selectedSurfaceStrain") or {}).get("total", float("inf")),
        "candidate.selectedSurfaceStrain.total",
    )
    improvement = (baseline_strain - candidate_strain) / max(abs(baseline_strain), 1e-12)
    check("surface_strain_improves_baseline", improvement >= float(min_relative_improvement),
          {"baseline": baseline_strain, "candidate": candidate_strain, "relativeImprovement": improvement},
          f">= {min_relative_improvement:.3f}")

    retention = ((candidate.get("motionRetention") or {}).get("pooled") or {})
    motion_p05 = _finite_number(retention.get("p05Ratio", 0.0), "motionRetention.pooled.p05Ratio")
    below_floor = _finite_number(retention.get("belowFloorFraction", 1.0), "motionRetention.pooled.belowFloorFraction")
    check("motion_retention_floor", motion_p05 >= float(min_motion_p05), motion_p05,
          f">= {min_motion_p05:.3f}")
    check("motion_floor_violations", below_floor <= float(max_motion_below_floor), below_floor,
          f"<= {max_motion_below_floor:.3f}")

    articulation = candidate.get("articulationRetention") or {}
    articulation_pooled = articulation.get("pooled") or {}
    articulation_p05 = _finite_number(
        articulation_pooled.get("p05FrameRatio", 0.0),
        "articulationRetention.pooled.p05FrameRatio",
    )
    articulation_below = _finite_number(
        articulation_pooled.get("belowFloorFraction", 1.0),
        "articulationRetention.pooled.belowFloorFraction",
    )
    active_joints = _finite_number(
        articulation.get("activeJointCount", 0.0),
        "articulationRetention.activeJointCount",
    )
    check("articulation_regions_present", active_joints >= 1.0, active_joints,
          ">= 1 active geometric mocap region")
    check("articulation_retention_floor", articulation_p05 >= float(min_articulation_p05), articulation_p05,
          f">= {min_articulation_p05:.3f}")
    check("articulation_floor_violations", articulation_below <= float(max_articulation_below_floor), articulation_below,
          f"<= {max_articulation_below_floor:.3f}")

    topology = candidate.get("topologyMetrics") or {}
    severe = _finite_number(topology.get("triangleSevereCollapseFraction", 1.0),
                            "topologyMetrics.triangleSevereCollapseFraction")
    edge_stretch = _finite_number(topology.get("edgeStretchFraction", 1.0),
                                  "topologyMetrics.edgeStretchFraction")
    check("triangle_collapse", severe <= float(max_severe_collapse), severe,
          f"<= {max_severe_collapse:.3f}")
    check("edge_stretch", edge_stretch <= float(max_edge_stretch), edge_stretch,
          f"<= {max_edge_stretch:.3f}")

    # A report from a candidate that did not actually emit a sparse field is
    # not promotable, even if older metrics happen to look plausible.
    sidecar = candidate.get("weightsSidecar")
    sidecar_path = Path(sidecar) if isinstance(sidecar, str) else None
    sidecar_ok = bool(sidecar_path and sidecar_path.is_file())
    check("weights_sidecar_declared", sidecar_ok if require_sidecar else bool(sidecar), sidecar,
          "weightsSidecar must name an existing .npz" if require_sidecar else "weightsSidecar must be declared")
    if sidecar_ok and require_sidecar:
        try:
            with np.load(sidecar_path, allow_pickle=False) as payload:
                weights = np.asarray(payload["weights"], dtype=np.float64)
                normalized = weights.ndim == 2 and np.isfinite(weights).all() and np.all(weights >= -1e-8)
                row_sums = weights.sum(axis=1) if weights.ndim == 2 else np.asarray([])
                normalized = bool(normalized and np.allclose(row_sums, 1.0, atol=1e-4))
                influences = int((weights > 1e-8).sum(axis=1).max()) if weights.ndim == 2 and len(weights) else 0
            check("weights_finite_normalized", normalized,
                  {"shape": list(weights.shape), "maxInfluences": influences},
                  "finite nonnegative rows summing to one")
        except Exception as exc:  # pragma: no cover - malformed external artifact
            check("weights_finite_normalized", False, str(exc), "readable weights.npz")

    optimized_glb = candidate.get("optimizedGlb")
    optimized_path = Path(optimized_glb) if isinstance(optimized_glb, str) else None
    export_validation = candidate.get("exportValidation") or {}
    export_ok = bool(optimized_path and optimized_path.is_file() and export_validation.get("passed") is True)
    export_declared = bool(optimized_path and export_validation.get("passed") is True)
    check("optimized_glb_validated", export_ok if require_export else export_declared,
          {"path": optimized_glb, "exportValidation": export_validation},
          "optimizedGlb exists and exportValidation.passed is true"
          if require_export else "optimizedGlb and passing exportValidation must be declared")

    baseline_image = baseline.get("imageValidation") or {}
    candidate_image = candidate.get("imageValidation") or {}
    baseline_iou = _finite_number(baseline_image.get("meanSilhouetteIou", 0.0), "baseline.imageValidation.meanSilhouetteIou")
    candidate_iou = _finite_number(candidate_image.get("meanSilhouetteIou", 0.0), "candidate.imageValidation.meanSilhouetteIou")
    baseline_alpha = _finite_number(baseline_image.get("meanAlphaL1", 1.0), "baseline.imageValidation.meanAlphaL1")
    candidate_alpha = _finite_number(candidate_image.get("meanAlphaL1", 1.0), "candidate.imageValidation.meanAlphaL1")
    check("matched_view_iou_not_regressed", candidate_iou >= baseline_iou - float(max_image_iou_drop),
          {"baseline": baseline_iou, "candidate": candidate_iou, "drop": baseline_iou - candidate_iou},
          f"drop <= {max_image_iou_drop:.4f}")
    check("matched_view_alpha_not_regressed", candidate_alpha <= baseline_alpha + float(max_image_alpha_l1_increase),
          {"baseline": baseline_alpha, "candidate": candidate_alpha, "increase": candidate_alpha - baseline_alpha},
          f"increase <= {max_image_alpha_l1_increase:.4f}")
    baseline_compactness = _finite_number(
        baseline_image.get("meanSilhouetteCompactness", 0.0),
        "baseline.imageValidation.meanSilhouetteCompactness",
    )
    candidate_compactness = _finite_number(
        candidate_image.get("meanSilhouetteCompactness", 0.0),
        "candidate.imageValidation.meanSilhouetteCompactness",
    )
    compactness_increase = (candidate_compactness - baseline_compactness) / max(abs(baseline_compactness), 1e-12)
    check("matched_view_compactness_not_regressed",
          compactness_increase <= float(max_image_compactness_increase),
          {"baseline": baseline_compactness, "candidate": candidate_compactness,
           "relativeIncrease": compactness_increase},
          f"relative increase <= {max_image_compactness_increase:.4f}")

    validation_keys = tuple(candidate.get("validationClipKeys") or ())
    if validation_keys:
        baseline_validation = baseline.get("validationSurfaceStrain") or {}
        candidate_validation = candidate.get("validationSurfaceStrain") or {}
        baseline_v = _finite_number(
            baseline_validation.get("total", baseline_strain),
            "baseline.validationSurfaceStrain.total",
        )
        candidate_v = _finite_number(
            candidate_validation.get("total", float("inf")),
            "candidate.validationSurfaceStrain.total",
        )
        validation_improvement = (baseline_v - candidate_v) / max(abs(baseline_v), 1e-12)
        check("heldout_surface_strain_improves", validation_improvement >= float(min_relative_improvement),
              {"baseline": baseline_v, "candidate": candidate_v, "relativeImprovement": validation_improvement},
              f">= {min_relative_improvement:.3f}")
        validation_retention = (candidate.get("validationMotionRetention") or {}).get("pooled") or {}
        validation_p05 = _finite_number(validation_retention.get("p05Ratio", 0.0),
                                        "validationMotionRetention.pooled.p05Ratio")
        validation_below = _finite_number(validation_retention.get("belowFloorFraction", 1.0),
                                          "validationMotionRetention.pooled.belowFloorFraction")
        check("heldout_motion_retention_floor", validation_p05 >= float(min_motion_p05), validation_p05,
              f">= {min_motion_p05:.3f}")
        check("heldout_motion_floor_violations", validation_below <= float(max_motion_below_floor), validation_below,
              f"<= {max_motion_below_floor:.3f}")
        baseline_art = ((baseline.get("validationArticulationRetention") or {}).get("pooled") or {})
        candidate_art = ((candidate.get("validationArticulationRetention") or {}).get("pooled") or {})
        baseline_art_p05 = _finite_number(
            baseline_art.get("p05FrameRatio", 0.0),
            "baseline.validationArticulationRetention.pooled.p05FrameRatio",
        )
        candidate_art_p05 = _finite_number(
            candidate_art.get("p05FrameRatio", 0.0),
            "candidate.validationArticulationRetention.pooled.p05FrameRatio",
        )
        art_regression = (baseline_art_p05 - candidate_art_p05) / max(abs(baseline_art_p05), 1e-12)
        check("heldout_articulation_not_regressed", art_regression <= float(max_heldout_articulation_regression),
              {"baseline": baseline_art_p05, "candidate": candidate_art_p05,
               "relativeRegression": art_regression},
              f"<= {max_heldout_articulation_regression:.3f}")
        candidate_art_below = _finite_number(
            candidate_art.get("belowFloorFraction", 1.0),
            "candidate.validationArticulationRetention.pooled.belowFloorFraction",
        )
        check("heldout_articulation_floor_violations", candidate_art_below <= float(max_articulation_below_floor),
              candidate_art_below, f"<= {max_articulation_below_floor:.3f}")
    passed = all(bool(item["passed"]) for item in checks)
    return {
        "passed": passed,
        "baseline": baseline.get("candidate"),
        "candidate": candidate.get("candidate"),
        "checks": checks,
        "policy": {
            "minRelativeImprovement": float(min_relative_improvement),
            "maxBindError": float(max_bind_error),
            "minMotionP05": float(min_motion_p05),
            "maxMotionBelowFloor": float(max_motion_below_floor),
            "minArticulationP05": float(min_articulation_p05),
            "maxArticulationBelowFloor": float(max_articulation_below_floor),
            "maxHeldoutArticulationRegression": float(max_heldout_articulation_regression),
            "maxSevereCollapse": float(max_severe_collapse),
            "maxEdgeStretch": float(max_edge_stretch),
            "requireExport": bool(require_export),
            "maxImageIouDrop": float(max_image_iou_drop),
            "maxImageAlphaL1Increase": float(max_image_alpha_l1_increase),
            "maxImageCompactnessIncrease": float(max_image_compactness_increase),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--min-relative-improvement", type=float, default=0.05)
    parser.add_argument("--min-motion-p05", type=float, default=0.80)
    parser.add_argument("--max-motion-below-floor", type=float, default=0.05)
    parser.add_argument("--min-articulation-p05", type=float, default=0.60)
    parser.add_argument("--max-articulation-below-floor", type=float, default=0.12)
    parser.add_argument("--max-heldout-articulation-regression", type=float, default=0.10)
    parser.add_argument("--max-severe-collapse", type=float, default=0.02)
    parser.add_argument("--max-edge-stretch", type=float, default=0.25)
    parser.add_argument("--max-image-iou-drop", type=float, default=0.002)
    parser.add_argument("--max-image-alpha-l1-increase", type=float, default=0.002)
    parser.add_argument("--max-image-compactness-increase", type=float, default=0.02)
    args = parser.parse_args()
    baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
    candidate = json.loads(args.candidate.read_text(encoding="utf-8"))
    result = evaluate_reports(
        baseline, candidate,
        min_relative_improvement=args.min_relative_improvement,
        min_motion_p05=args.min_motion_p05,
        max_motion_below_floor=args.max_motion_below_floor,
        min_articulation_p05=args.min_articulation_p05,
        max_articulation_below_floor=args.max_articulation_below_floor,
        max_heldout_articulation_regression=args.max_heldout_articulation_regression,
        max_severe_collapse=args.max_severe_collapse,
        max_edge_stretch=args.max_edge_stretch,
        max_image_iou_drop=args.max_image_iou_drop,
        max_image_alpha_l1_increase=args.max_image_alpha_l1_increase,
        max_image_compactness_increase=args.max_image_compactness_increase,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0 if result["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
