from __future__ import annotations

from auto_rig_quality_gate import evaluate_reports


def _report(*, mode="m7", strain=0.02, p05=0.95, below=0.01, severe=0.0, stretch=0.10,
            articulation_p05=0.90, articulation_below=0.01):
    return {
        "candidate": "candidate.glb",
        "candidateMode": mode,
        "clipKeys": ["move", "idle"],
        "idleBindWorldMaxError": 1e-8,
        "selectedSurfaceStrain": {"total": strain},
        "motionRetention": {"pooled": {"p05Ratio": p05, "belowFloorFraction": below}},
        "articulationRetention": {
            "activeJointCount": 4,
            "pooled": {"p05FrameRatio": articulation_p05, "belowFloorFraction": articulation_below},
        },
        "validationClipKeys": [],
        "topologyMetrics": {
            "triangleSevereCollapseFraction": severe,
            "edgeStretchFraction": stretch,
        },
        "weightsSidecar": "weights.npz",
        "optimizedGlb": "candidate.autorig.glb",
        "exportValidation": {"passed": True},
    }


def _evaluate(baseline, candidate):
    return evaluate_reports(baseline, candidate, require_sidecar=False, require_export=False)


def test_gate_requires_absolute_floors_and_baseline_improvement():
    baseline = _report(mode="smartrig", strain=0.10)
    candidate = _report(strain=0.05)
    result = _evaluate(baseline, candidate)
    assert result["passed"]


def test_gate_rejects_lower_strain_when_topology_collapses():
    baseline = _report(mode="smartrig", strain=0.10)
    candidate = _report(strain=0.05, severe=0.25)
    result = _evaluate(baseline, candidate)
    assert not result["passed"]
    assert any(item["name"] == "triangle_collapse" and not item["passed"]
               for item in result["checks"])


def test_gate_rejects_inconclusive_candidate_without_baseline_improvement():
    baseline = _report(mode="smartrig", strain=0.05)
    candidate = _report(strain=0.049)
    result = _evaluate(baseline, candidate)
    assert not result["passed"]
    assert any(item["name"] == "surface_strain_improves_baseline" and not item["passed"]
               for item in result["checks"])
