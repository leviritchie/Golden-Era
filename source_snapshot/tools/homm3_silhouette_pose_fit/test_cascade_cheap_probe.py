"""Cheap stacked-pass probe frame selection."""
from __future__ import annotations

from cascade_cheap_probe import (
    cheap_probe_positions,
    free_frame_positions,
    scatter_sparse_scores,
)


def run() -> dict[str, object]:
    free = free_frame_positions(frame_count=10, prefix=2, suffix=2)
    assert free == (2, 3, 4, 5, 6, 7), free
    try:
        free_frame_positions(frame_count=4, prefix=2, suffix=2)
        raise AssertionError("no free frames must fail closed")
    except ValueError as exc:
        assert "free frames" in str(exc)

    scores = [0.9, 0.9, 0.4, 0.8, 0.1, 0.7, 0.2, 0.6, 0.95, 0.95]
    all_free = cheap_probe_positions(scores, prefix=2, suffix=2, keep_count=0)
    assert all_free == (2, 3, 4, 5, 6, 7), all_free
    worst = cheap_probe_positions(scores, prefix=2, suffix=2, keep_count=3)
    assert worst == (2, 4, 6), worst
    assert 0 not in worst and 9 not in worst
    scattered = scatter_sparse_scores(scores, [0.01, 0.02, 0.03], worst)
    assert scattered[2] == 0.01 and scattered[4] == 0.02 and scattered[6] == 0.03
    assert scattered[0] == 0.9 and scattered[3] == 0.8
    try:
        cheap_probe_positions(scores, prefix=2, suffix=2, keep_count=-1)
        raise AssertionError("negative keep_count must fail closed")
    except ValueError as exc:
        assert "keep_count" in str(exc)

    import inspect
    from roc_gpu_cascade_experiment import GpuCascadeConfig, GpuCascadeExperiment

    GpuCascadeConfig(
        cheap_joint_probe_occupancy_only=True,
        cheap_joint_probe_frame_count=8,
    ).validate()
    src = inspect.getsource(GpuCascadeExperiment.evaluate)
    assert "occupancy_only" in src
    score_src = inspect.getsource(GpuCascadeExperiment._score_geometry)
    assert "chroma_weight = 0.0 if occupancy_only" in score_src
    assert "collision_error_from_table" in score_src
    assert "if not occupancy_only:" not in score_src
    probe_src = inspect.getsource(GpuCascadeExperiment.optimize_clip)
    assert "cheap_probe_positions" in probe_src
    assert "cheap_occupancy" in probe_src
    assert "sparse_probe_frames" in probe_src
    assert "occupancy_only" in probe_src
    from gpu_cascade_batch_lock import SCRIPT_TOKENS

    assert "run_roc_stacked_small_pass.py" in SCRIPT_TOKENS
    assert "run_roc_stacked_small_ik_pass.py" in SCRIPT_TOKENS
    assert "run_roc_stacked_dinov3_quick.py" in SCRIPT_TOKENS
    probe_src = inspect.getsource(GpuCascadeExperiment.optimize_clip)
    assert "gpu ik cheapProbe occupancyOnly" in probe_src
    assert "_seed_transit_pose_from_previous_" in inspect.getsource(GpuCascadeExperiment)
    from run_roc_stacked_small_pass import refuse_imported_pose_seed

    stripped = refuse_imported_pose_seed(
        {"initial_poses": {0: {"wing_a": {"x": 1.0}}}, "joint_step_deg": 2.5}
    )
    assert "initial_poses" not in stripped
    assert stripped["joint_step_deg"] == 2.5
    assert refuse_imported_pose_seed({"joint_step_deg": 2.5})["joint_step_deg"] == 2.5
    return {"ok": True, "worst": list(worst)}


if __name__ == "__main__":
    print(run())
