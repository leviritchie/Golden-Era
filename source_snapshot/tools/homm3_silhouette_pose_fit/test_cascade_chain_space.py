"""Chain-space topology, clip-block directions, and fail-closed knobs."""
from __future__ import annotations

import inspect

from cascade_chain_space import (
    CHAIN_SPACE_MODES,
    chain_block_directions,
    chain_block_rms_directions,
    chains_for_mode,
    clip_block_direction,
    derive_disjoint_branch_segments,
    derive_layer_joints,
    derive_root_to_leaf_chains,
    equal_share_chain_directions,
    select_clipwide_trust_candidate,
    validate_chain_space_config,
)
from gpu_raster_depth_animation import run_gpu_depth_fit_from_hybrid_config
from roc_gpu_cascade_experiment import GpuCascadeConfig
from run_dinov3_branch_vector_examples import (
    _canonical_gpu_config,
    _validated_branch_decision_rows,
)


def run() -> dict[str, object]:
    import torch

    forward_path = {
        "depth_target_dir": "V:/repo/targets",
        "dense_semantic_model_id": "facebook/dinov3-vits16-pretrain-lvd1689m",
    }
    backward_path = {
        "depth_target_dir": r"V:\repo\targets",
        "dense_semantic_model_id": "facebook/dinov3-vits16-pretrain-lvd1689m",
    }
    assert _canonical_gpu_config(forward_path) == _canonical_gpu_config(backward_path)
    decision = {"group": 0, "accepted": False}
    terminal = {
        "stage": "chain_space",
        "mode": "branch_trust",
        "finish": "temporal_consensus",
        "consensusMoved": 0,
    }
    assert _validated_branch_decision_rows([decision, terminal]) == [decision]
    bad_histories = (
        [decision, {key: value for key, value in terminal.items() if key != "consensusMoved"}],
        [decision, {**terminal, "consensusMoved": 1}],
        [decision, {**terminal, "consensusMoved": 0.5}],
        [decision, {**terminal, "consensusMoved": False}],
        [{**decision, "finish": "temporal_consensus"}, terminal],
        [{}, terminal],
        [decision, {**terminal, "group": 1}],
    )
    for bad_history in bad_histories:
        try:
            _validated_branch_decision_rows(bad_history)
            raise AssertionError("malformed branch terminal partition must fail closed")
        except RuntimeError:
            pass

    dino_branch = {
        "score_mode": "dinov3_dense",
        "depth_weight": 0.0,
        "silhouette_weight": 0.0,
        "chroma_weight": 0.0,
        "collision_enabled": False,
        "collision_weight": 0.0,
        "joint_unique_gain_weight": 0.0,
        "fine_unique_gain_weight": 0.0,
        "root_iterations": 0,
        "joint_solver_mode": "branch_vector",
        "chain_space_enabled": True,
        "chain_space_mode": "branch_trust",
        "dense_semantic_autograd_enabled": True,
        "dense_semantic_subject_crop": False,
        "root_search_enabled": False,
        "root_rotation_defer_camera_up": False,
        "root_refit_after_base_enabled": False,
        "joint_adaptive_step_enabled": False,
        "joint_temporal_consensus_enabled": False,
        "base_pose_enabled": False,
        "mid_pose_enabled": False,
        "branch_rescue_enabled": False,
        "physics_smooth_enabled": False,
        "fine_root_enabled": False,
        "skip_tiny_bones": False,
        "fine_only_leaf_length_frac": 0.0,
        "include_unlisted_search_bones": True,
        "articulated_iterations": 0,
        "fine_iterations": 0,
    }

    # Y-fork: 0 → 1 → {2→3, 4→5}
    parents = [None, 0, 1, 2, 1, 4]
    search = (0, 1, 2, 3, 4, 5)
    overlapping = derive_root_to_leaf_chains(parents, search)
    assert overlapping == ((0, 1, 2, 3), (0, 1, 4, 5)), overlapping
    disjoint = derive_disjoint_branch_segments(parents, search)
    assert disjoint == ((0, 1), (2, 3), (4, 5)), disjoint
    # Preserve search order (anatomy schedules rely on this). Depth-first
    # defaults come from the cascade search resolve, not from re-sorting here.
    layers = derive_layer_joints(parents, search, node_depths=(0, 1, 2, 3, 2, 3))
    assert layers == ((0,), (1,), (2,), (3,), (4,), (5,)), layers
    depth_first = (0, 1, 2, 4, 3, 5)
    assert derive_layer_joints(
        parents, depth_first, node_depths=(0, 1, 2, 3, 2, 3)
    ) == ((0,), (1,), (2,), (4,), (3,), (5,))
    assert chains_for_mode(
        "chain_grad", parents=parents, search_indices=search, node_depths=(0, 1, 2, 3, 2, 3)
    ) == overlapping
    assert chains_for_mode(
        "branch_trust", parents=parents, search_indices=search, node_depths=(0, 1, 2, 3, 2, 3)
    ) == disjoint
    assert chains_for_mode(
        "layer_surface",
        parents=parents,
        search_indices=depth_first,
        node_depths=(0, 1, 2, 3, 2, 3),
    ) == ((0,), (1,), (2,), (4,), (3,), (5,))

    try:
        derive_root_to_leaf_chains(parents, ())
        raise AssertionError("empty search must fail closed")
    except ValueError as exc:
        assert "empty" in str(exc)

    cyclic = [1, 0]
    try:
        derive_root_to_leaf_chains(cyclic, (0, 1))
        raise AssertionError("a two-node cycle must fail closed")
    except ValueError as exc:
        assert "cycle" in str(exc) or "leaves" in str(exc)

    default = GpuCascadeConfig()
    assert bool(default.chain_space_enabled) is False
    assert str(default.chain_space_mode) == "chain_grad"
    assert default.chain_space_eval_budget is None
    GpuCascadeConfig(
        chain_space_enabled=True,
        chain_space_mode="layer_surface",
        chain_space_iterations=2,
        chain_space_step_degs=(5.0, 10.0),
    ).validate()
    try:
        GpuCascadeConfig(chain_space_enabled=True, chain_space_mode="tip_ik").validate()
        raise AssertionError("unknown chain_space_mode must fail closed")
    except ValueError as exc:
        assert "chain_space_mode" in str(exc)
    try:
        GpuCascadeConfig(
            chain_space_enabled=True,
            chain_space_mode="chain_grad",
            sa_enabled=True,
        ).validate()
        raise AssertionError("chain space cannot mix SA")
    except ValueError as exc:
        assert "sa_enabled" in str(exc)
    try:
        GpuCascadeConfig(
            chain_space_enabled=True,
            chain_space_mode="chain_grad",
            gradient_ladder_enabled=True,
            gradient_ladder_step_degs=(5.0,),
        ).validate()
        raise AssertionError("chain space cannot mix the gradient ladder")
    except ValueError as exc:
        assert "gradient_ladder" in str(exc)
    try:
        GpuCascadeConfig(
            score_mode="dinov3_dense",
            depth_weight=0.0,
            silhouette_weight=0.0,
            chroma_weight=0.0,
            collision_enabled=False,
            collision_weight=0.0,
            joint_unique_gain_weight=0.0,
            fine_unique_gain_weight=0.0,
            root_iterations=0,
            chain_space_enabled=True,
            chain_space_mode="chain_grad",
        ).validate()
        raise AssertionError("dinov3_dense cannot mix chain space")
    except ValueError as exc:
        assert "dinov3" in str(exc).lower() or "chain_space" in str(exc)
    GpuCascadeConfig(**dino_branch).validate()
    try:
        GpuCascadeConfig(
            **{
                **dino_branch,
                "chain_space_mode": "chain_grad",
            },
        ).validate()
        raise AssertionError("DINOv3 autograd must use atomic branch_trust")
    except ValueError as exc:
        assert "branch_trust" in str(exc)

    for name, value in (
        ("root_search_enabled", True),
        ("root_rotation_defer_camera_up", True),
        ("root_refit_after_base_enabled", True),
        ("joint_adaptive_step_enabled", True),
        ("joint_temporal_consensus_enabled", True),
        ("base_pose_enabled", True),
        ("mid_pose_enabled", True),
        ("branch_rescue_enabled", True),
        ("physics_smooth_enabled", True),
        ("sprite_aligned_motion_keep_enabled", True),
        ("fine_root_enabled", True),
        ("articulated_iterations", 1),
        ("fine_iterations", 1),
        ("skip_tiny_bones", True),
        ("fine_only_leaf_length_frac", 0.75),
        ("include_unlisted_search_bones", False),
    ):
        try:
            GpuCascadeConfig(**{**dino_branch, name: value}).validate()
            raise AssertionError(f"DINOv3 branch_vector must reject {name}")
        except ValueError as exc:
            assert name in str(exc), (name, exc)

    signature = inspect.signature(run_gpu_depth_fit_from_hybrid_config)
    for name in (
        "chain_space_enabled",
        "joint_solver_mode",
        "config_only",
        "chain_space_mode",
        "chain_space_iterations",
        "chain_space_step_degs",
        "chain_space_min_gradient_norm",
        "chain_space_trust_radius_deg",
        "dense_semantic_autograd_enabled",
        "chain_space_eval_budget",
        "motion_weight",
        "sprite_aligned_motion_keep_enabled",
        "sprite_aligned_motion_keep_min_improvement",
    ):
        assert name in signature.parameters, name

    grad = torch.zeros((2, 4, 3), dtype=torch.float32)
    grad[:, 1, 0] = 4.0
    grad[:, 2, 1] = 3.0
    direction, pooled_norm = clip_block_direction(grad, (1, 2), min_gradient_norm=1e-6)
    assert abs(float(pooled_norm) - 5.0) < 1e-5, pooled_norm
    chain = direction[:, (1, 2), :]
    assert abs(float(chain[0].reshape(-1).norm()) - 1.0) < 1e-5
    assert torch.allclose(direction[0], direction[1])
    assert float(direction[:, 0].abs().max()) == 0.0
    assert float(direction[:, 3].abs().max()) == 0.0
    varied_grad = grad.clone()
    varied_grad[1] *= 2.0
    rms_direction, rms_norms, clip_rms = chain_block_rms_directions(
        varied_grad, (1, 2), min_gradient_norm=1e-6
    )
    rms_block = rms_direction[:, (1, 2), :].reshape(2, -1)
    assert abs(float(torch.sqrt(torch.mean(rms_block * rms_block))) - 1.0) < 1e-6
    assert abs(float(rms_block[1].norm() / rms_block[0].norm()) - 2.0) < 1e-6
    assert bool((rms_norms > 0.0).all())
    assert float(clip_rms) > 0.0
    sparse = torch.zeros((4, 2, 3), dtype=torch.float32)
    sparse[0, 0, 0] = 2e-6
    sparse_direction, sparse_frames, sparse_clip = chain_block_rms_directions(
        sparse, (0,), min_gradient_norm=1e-6
    )
    assert float(sparse_frames[0]) > 1e-6
    assert float(sparse_clip) <= 1e-6
    assert float(sparse_direction.abs().max()) == 0.0
    flat, flat_norm = clip_block_direction(torch.zeros_like(grad), (1,), min_gradient_norm=1e-3)
    assert float(flat_norm) <= 1e-3
    assert float(flat.abs().max()) == 0.0

    # Hip-dominated overlapping path: RSS spends the step on bone 0; equal
    # share keeps the distal bone in the step.
    dominated = torch.zeros((1, 3, 3), dtype=torch.float32)
    dominated[0, 0, 0] = 10.0
    dominated[0, 2, 1] = 0.1
    rss, _rss_norms = chain_block_directions(dominated, (0, 1, 2), min_gradient_norm=1e-6)
    equal, equal_norms = equal_share_chain_directions(
        dominated, (0, 1, 2), min_gradient_norm=1e-6
    )
    assert float(rss[0, 2].norm()) < 0.02
    assert abs(float(equal[0, 0].norm()) - 1.0) < 1e-5
    assert abs(float(equal[0, 2].norm()) - 1.0) < 1e-5
    assert float(equal[0, 1].norm()) == 0.0
    assert abs(float(equal_norms[0]) - 10.0) < 1e-5
    try:
        equal_share_chain_directions(dominated, (), min_gradient_norm=1e-6)
        raise AssertionError("empty bone list must fail closed")
    except ValueError as exc:
        assert "at least one bone" in str(exc)

    assert select_clipwide_trust_candidate(
        0.5, (0.49, 0.51), min_improvement=0.02
    ) == -1
    assert select_clipwide_trust_candidate(
        0.5, (0.52,), min_improvement=0.02
    ) == -1
    assert select_clipwide_trust_candidate(
        0.5, (0.49, 0.53, 0.52), min_improvement=0.02
    ) == 1
    validate_chain_space_config(
        enabled=True,
        mode="branch_trust",
        iterations=3,
        step_degs=(5.0, 10.0, 20.0),
        min_gradient_norm=1e-6,
        trust_radius_deg=20.0,
        trust_radius_min_deg=1.25,
        trust_radius_max_deg=40.0,
        min_clip_improvement=1e-6,
    )
    try:
        validate_chain_space_config(
            enabled=True,
            mode="chain_grad",
            iterations=3,
            step_degs=(10.0, 5.0),
            min_gradient_norm=1e-6,
            trust_radius_deg=20.0,
            trust_radius_min_deg=1.25,
            trust_radius_max_deg=40.0,
            min_clip_improvement=1e-6,
        )
        raise AssertionError("non-increasing steps must fail closed")
    except ValueError as exc:
        assert "increasing" in str(exc)
    try:
        validate_chain_space_config(
            enabled=True,
            mode="chain_grad",
            iterations=3,
            step_degs=(5.0, 10.0),
            min_gradient_norm=1e-6,
            trust_radius_deg=20.0,
            trust_radius_min_deg=1.25,
            trust_radius_max_deg=40.0,
            min_clip_improvement=1e-6,
            eval_budget=0,
        )
        raise AssertionError("zero eval budget must fail closed")
    except ValueError as exc:
        assert "eval_budget" in str(exc)
    try:
        GpuCascadeConfig(
            chain_space_enabled=True,
            chain_space_mode="chain_grad",
            chain_space_eval_budget=0,
        ).validate()
        raise AssertionError("zero chain_space_eval_budget must fail closed")
    except ValueError as exc:
        assert "eval_budget" in str(exc)

    assert CHAIN_SPACE_MODES == ("chain_grad", "branch_trust", "layer_surface")
    from pathlib import Path as _Path

    cascade_text = _Path(__file__).with_name("roc_gpu_cascade_experiment.py").read_text(
        encoding="utf-8"
    )
    chain_body = cascade_text[
        cascade_text.index("def run_chain_space() -> None:") : cascade_text.index(
            "def run_simulated_annealing() -> None:"
        )
    ]
    assert "gather_per_frame_winners(" in chain_body
    assert chain_body.index("gather_per_frame_winners(") < chain_body.index(
        "apply_temporal_consensus("
    )
    from run_chain_space_surface_compare import SHARED_EXPERIMENT

    assert SHARED_EXPERIMENT["joint_temporal_consensus_enabled"] is True
    assert SHARED_EXPERIMENT["physics_smooth_enabled"] is False
    assert SHARED_EXPERIMENT["sprite_aligned_motion_keep_enabled"] is True
    assert abs(float(SHARED_EXPERIMENT["sprite_aligned_motion_keep_min_improvement"]) - 0.01) <= 1e-12
    return {"ok": True}


if __name__ == "__main__":
    print(run())
