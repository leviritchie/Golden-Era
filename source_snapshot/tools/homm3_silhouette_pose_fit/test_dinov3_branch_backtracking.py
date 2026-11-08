"""DINOv3 branch-vector line-search and motion-evidence contracts."""
from __future__ import annotations

from cascade_chain_space import trust_region_backtracking_steps
from run_dinov3_branch_vector_examples import _pose_motion_coverage


def run() -> dict[str, object]:
    assert trust_region_backtracking_steps(20.0, 1.25) == (
        20.0,
        10.0,
        5.0,
        2.5,
        1.25,
    )
    assert trust_region_backtracking_steps(1.875, 1.25) == (1.875, 1.25)
    assert trust_region_backtracking_steps(1.25, 1.25) == (1.25,)
    try:
        trust_region_backtracking_steps(1.0, 1.25)
        raise AssertionError("trust floor above radius must fail closed")
    except ValueError as exc:
        assert "cannot exceed" in str(exc)

    coverage = _pose_motion_coverage(
        {
            "0": {"a": {"x": 0.0, "y": 0.0, "z": 0.0}},
            "1": {
                "a": {"x": 0.0, "y": 0.0, "z": 0.0},
                "b": {"x": 0.0, "y": 0.0, "z": 0.1},
            },
        },
        ["a", "b", "c"],
    )
    assert coverage == {
        "searchBoneCount": 3,
        "exactlyFrozenBoneCount": 2,
        "meaningfullyMovedBoneCount": 1,
        "meaningfulMotionThresholdDeg": 1.0,
        "meaningfulBoneCoverage": 1.0 / 3.0,
        "motionCoverageStatus": "sparse",
    }
    return {"ok": True, **coverage}


if __name__ == "__main__":
    print(run())
