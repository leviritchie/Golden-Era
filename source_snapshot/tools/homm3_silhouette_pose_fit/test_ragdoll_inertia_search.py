"""CPU tests for ragdoll inertia search. No GPU."""
from __future__ import annotations

import math
import unittest

import numpy as np

from ragdoll_inertia_plant import (
    SKIP_SEARCH_BONES,
    RagdollPlantConfig,
    assert_ragdoll_write_path,
    death_skips_idle_end,
    idle_end_required,
    make_chain_fixture,
)
from ragdoll_inertia_search import (
    REQUIRED_SCORE_CONFIG,
    ClipTrajectory,
    ScoreBreakdown,
    apply_nudge,
    assert_not_idle_search_clip,
    assert_score_config,
    boundary_report,
    clip_bands,
    consolidate_fused_clip,
    idle_stability_report,
    integrate_clip,
    keep_probe,
    motion_keep_report,
    mock_grad,
    prefix_unchanged,
    rank_cells_from_grad,
    run_sweeps,
    searchable_joints,
    suffix_unchanged,
    zero_motion_seed,
)


def _idle_trajectory(plant, frames: int, *, prefix: int = 0, suffix: int = 0) -> ClipTrajectory:
    joints = plant.joint_count()
    idle = np.zeros((joints, 3), dtype=np.float64)
    rotvecs = np.repeat(idle[None, :, :], frames, axis=0)
    return ClipTrajectory(
        rotvecs=rotvecs,
        omega=np.zeros_like(rotvecs),
        alpha_control=np.zeros_like(rotvecs),
        clamp_counts=np.zeros((frames, joints), dtype=np.int64),
        idle_rotvecs=idle,
        prefix_poses=rotvecs.copy(),
        suffix_poses=rotvecs.copy() if suffix > 0 else None,
    )


def _score_from_rotvecs(trajectory: ClipTrajectory) -> ScoreBreakdown:
    frames = int(trajectory.rotvecs.shape[0])
    energy = float(np.mean(np.linalg.norm(trajectory.rotvecs, axis=-1)))
    clip_obj = -energy
    image = np.full((frames,), clip_obj, dtype=np.float64)
    collision = np.zeros((frames,), dtype=np.float64)
    return ScoreBreakdown(
        clip_objective=clip_obj,
        score_mean=clip_obj,
        image_mean=image,
        collision=collision,
        temporal=0.0,
    )


class RagdollSearchTests(unittest.TestCase):
    def test_prefix_and_suffix_stay_copied(self) -> None:
        plant, _state = make_chain_fixture()
        bands = clip_bands(frame_count=6, prefix=2, suffix=2, lock_suffix=True)
        source = _idle_trajectory(plant, 6, prefix=2, suffix=2)
        source.prefix_poses[0, 2, 0] = math.radians(3.0)
        source.prefix_poses[1, 2, 0] = math.radians(3.0)
        source.suffix_poses[4, 2, 0] = math.radians(-2.0)
        source.suffix_poses[5, 2, 0] = math.radians(-2.0)
        source.alpha_control[2, 2, 0] = float(plant.tau_budget / plant.lambda_max[2])
        out = integrate_clip(plant, source, bands)
        self.assertTrue(prefix_unchanged(out, bands))
        self.assertTrue(suffix_unchanged(out, bands))
        self.assertTrue(np.allclose(out.rotvecs[:2], source.prefix_poses[:2]))
        self.assertTrue(np.allclose(out.rotvecs[4:], source.suffix_poses[4:]))

    def test_suffix_boundary_miss_rejects_keep(self) -> None:
        plant, _state = make_chain_fixture(tilt_deg=0.0)
        bands = clip_bands(frame_count=5, prefix=1, suffix=1, lock_suffix=True)
        source = _idle_trajectory(plant, 5, prefix=1, suffix=1)
        integrated = integrate_clip(plant, source, bands)
        integrated.rotvecs[int(bands.last_free()), 2, 0] = math.radians(40.0)
        residual = boundary_report(plant, integrated, bands)
        self.assertFalse(residual["ok"])
        current = _score_from_rotvecs(integrated)
        keep, reason = keep_probe(
            current=current,
            candidate=ScoreBreakdown(
                clip_objective=float(current.clip_objective) + 0.5,
                score_mean=0.0,
                image_mean=current.image_mean + 0.5,
                collision=current.collision,
                temporal=0.0,
            ),
            trajectory=integrated,
            bands=bands,
            plant=plant,
            prefix_ok=True,
            suffix_ok=True,
        )
        self.assertFalse(keep)
        self.assertEqual(reason, "idle_end")

    def test_mid_clip_nudge_changes_later_free_frames(self) -> None:
        plant, _state = make_chain_fixture(tilt_deg=0.0)
        bands = clip_bands(frame_count=5, prefix=1, suffix=1, lock_suffix=True)
        source = _idle_trajectory(plant, 5, prefix=1, suffix=1)
        baseline = integrate_clip(plant, source, bands)
        nudged = copy_with_nudge(plant, source, frame=2, joint=2)
        later = integrate_clip(plant, nudged, bands)
        self.assertGreater(float(np.linalg.norm(later.rotvecs[3] - baseline.rotvecs[3])), 1e-4)
        self.assertTrue(np.allclose(later.rotvecs[0], baseline.rotvecs[0]))
        self.assertLess(
            float(np.linalg.norm(later.omega[3])),
            float(np.linalg.norm(later.omega[2])),
        )

    def test_bone_000_is_not_searchable(self) -> None:
        plant, _state = make_chain_fixture()
        names = list(plant.node_names)
        names[1] = "Bone_000"
        plant.node_names = tuple(names)
        joints = searchable_joints(plant)
        self.assertNotIn(1, joints)
        self.assertNotIn(0, joints)
        self.assertEqual(SKIP_SEARCH_BONES, frozenset({"Bone_000"}))

    def test_death_does_not_lock_suffix(self) -> None:
        self.assertTrue(death_skips_idle_end((2, 5)))
        self.assertFalse(idle_end_required((2, 5)))
        bands = clip_bands(frame_count=8, prefix=2, suffix=2, lock_suffix=False)
        self.assertEqual(bands.free_frames, tuple(range(2, 8)))
        self.assertFalse(bands.lock_suffix)

    def test_writes_refuse_fused_push_paths(self) -> None:
        from pathlib import Path
        from ragdoll_inertia_plant import REPO_ROOT, SOLVER_ID

        fused = (
            REPO_ROOT
            / "artifacts"
            / "pose_picker_runs"
            / "h3_goblin"
            / "idle"
            / "fused_push_v24_pipeline"
            / "gpu_clip_result.json"
        )
        with self.assertRaises(RuntimeError):
            assert_ragdoll_write_path(fused)
        legal = (
            REPO_ROOT
            / "artifacts"
            / "pose_picker_runs"
            / "h3_goblin"
            / "idle"
            / SOLVER_ID
            / "gpu_clip_result.json"
        )
        self.assertEqual(assert_ragdoll_write_path(legal), legal.resolve())

    def test_zero_motion_seed_does_not_copy_fused_free_frames(self) -> None:
        plant, _state = make_chain_fixture()
        bands = clip_bands(frame_count=6, prefix=2, suffix=2, lock_suffix=True)
        source = _idle_trajectory(plant, 6, prefix=2, suffix=2)
        source.rotvecs[3, 2, 0] = math.radians(40.0)
        seeded = zero_motion_seed(plant, source, bands)
        self.assertTrue(np.allclose(seeded.rotvecs[2], source.prefix_poses[1]))
        self.assertLess(float(np.linalg.norm(seeded.rotvecs[3])), 1e-12)

    def test_rank_prefers_late_frames_in_reverse_order(self) -> None:
        plant, _state = make_chain_fixture()
        bands = clip_bands(frame_count=6, prefix=1, suffix=1, lock_suffix=True)
        traj = _idle_trajectory(plant, 6, prefix=1, suffix=1)
        grad = mock_grad(traj, (1, 2), bands.free_frames)
        grad[1, 2] = 0.2
        grad[3, 2] = 0.2
        forward = rank_cells_from_grad(
            grad, plant=plant, joints=(1, 2), free_frames=bands.free_frames, top_k=2, reverse_order=False
        )
        reverse = rank_cells_from_grad(
            grad, plant=plant, joints=(1, 2), free_frames=bands.free_frames, top_k=2, reverse_order=True
        )
        self.assertEqual(forward[0][0], 1)
        self.assertEqual(reverse[0][0], 3)

    def test_mock_search_can_keep_a_restoring_nudge(self) -> None:
        plant, _state = make_chain_fixture(tilt_deg=0.0)
        bands = clip_bands(frame_count=4, prefix=0, suffix=0, lock_suffix=False)
        source = _idle_trajectory(plant, 4)
        joints = searchable_joints(plant)

        def rank_fn(traj: ClipTrajectory, reverse_order: bool):
            grad = mock_grad(traj, joints, bands.free_frames)
            return rank_cells_from_grad(
                grad,
                plant=plant,
                joints=joints,
                free_frames=bands.free_frames,
                top_k=2,
                reverse_order=bool(reverse_order),
            )

        _traj, _score, stats = run_sweeps(
            plant=plant,
            trajectory=source,
            bands=bands,
            joints=joints,
            score_fn=_score_from_rotvecs,
            rank_fn=rank_fn,
            reverse_order=True,
            max_sweeps=1,
            deadline=1e100,
            config=RagdollPlantConfig(),
        )
        self.assertGreaterEqual(int(stats["sweeps"]), 1)

    def test_score_config_pins_recorded_goblin_walk(self) -> None:
        assert_score_config(REQUIRED_SCORE_CONFIG)
        bad = dict(REQUIRED_SCORE_CONFIG)
        bad["chroma_scale"] = 3
        with self.assertRaises(RuntimeError):
            assert_score_config(bad)
        roc = dict(REQUIRED_SCORE_CONFIG)
        roc["chroma_scale"] = 3
        assert_score_config(roc, chroma_scale=3)
        from gpu_cascade_batch_lock import SCRIPT_TOKENS

        self.assertIn("run_ragdoll_inertia_goblin.py", SCRIPT_TOKENS)

    def test_idle_stability_holds_rest(self) -> None:
        plant, _state = make_chain_fixture()
        bands = clip_bands(frame_count=4, prefix=1, suffix=1, lock_suffix=True)
        traj = _idle_trajectory(plant, 4, prefix=1, suffix=1)
        seed = _score_from_rotvecs(traj)
        report = idle_stability_report(
            seed_score=seed,
            picked_score=seed,
            trajectory=traj,
            bands=bands,
        )
        self.assertTrue(report["ok"])
        self.assertEqual(report["reason"], "")

    def test_idle_stability_rejects_objective_collapse(self) -> None:
        plant, _state = make_chain_fixture()
        bands = clip_bands(frame_count=4, prefix=1, suffix=1, lock_suffix=True)
        traj = _idle_trajectory(plant, 4, prefix=1, suffix=1)
        seed = _score_from_rotvecs(traj)
        collapsed = ScoreBreakdown(
            clip_objective=float(seed.clip_objective) - 0.20,
            score_mean=float(seed.score_mean) - 0.20,
            image_mean=seed.image_mean.copy(),
            collision=seed.collision.copy(),
            temporal=0.0,
        )
        report = idle_stability_report(
            seed_score=seed,
            picked_score=collapsed,
            trajectory=traj,
            bands=bands,
        )
        self.assertFalse(report["ok"])
        self.assertEqual(report["reason"], "objective_collapse")

    def test_idle_stability_rejects_rest_drift(self) -> None:
        plant, _state = make_chain_fixture()
        bands = clip_bands(frame_count=4, prefix=1, suffix=1, lock_suffix=True)
        traj = _idle_trajectory(plant, 4, prefix=1, suffix=1)
        seed = _score_from_rotvecs(traj)
        traj.rotvecs[2, 2, 0] = math.radians(80.0)
        report = idle_stability_report(
            seed_score=seed,
            picked_score=seed,
            trajectory=traj,
            bands=bands,
        )
        self.assertFalse(report["ok"])
        self.assertEqual(report["reason"], "rest_drift")

    def test_idle_is_not_its_own_search_clip(self) -> None:
        with self.assertRaises(RuntimeError):
            assert_not_idle_search_clip("idle")
        assert_not_idle_search_clip("idle_start_move_end")

    def test_fused_post_pass_keeps_walk_amplitude(self) -> None:
        plant, _state = make_chain_fixture()
        bands = clip_bands(frame_count=8, prefix=1, suffix=1, lock_suffix=True)
        source = _idle_trajectory(plant, 8, prefix=1, suffix=1)
        for frame in range(8):
            source.rotvecs[frame, 2, 0] = math.radians(25.0 * math.sin(frame * 0.7))
        source.prefix_poses = source.rotvecs.copy()
        source.suffix_poses = source.rotvecs.copy()
        picked, report = consolidate_fused_clip(plant, source, bands)
        self.assertGreaterEqual(float(report["keepFrac"]), 0.85)
        self.assertTrue(np.allclose(picked.rotvecs[0], source.rotvecs[0]))
        self.assertTrue(np.allclose(picked.rotvecs[-1], source.rotvecs[-1]))

    def test_fused_post_pass_carries_spike_into_later_frame(self) -> None:
        plant, _state = make_chain_fixture()
        bands = clip_bands(frame_count=5, prefix=1, suffix=1, lock_suffix=True)
        source = _idle_trajectory(plant, 5, prefix=1, suffix=1)
        source.rotvecs[2, 2, 0] = math.radians(30.0)
        source.prefix_poses = source.rotvecs.copy()
        source.suffix_poses = source.rotvecs.copy()
        picked, _report = consolidate_fused_clip(plant, source, bands)
        self.assertGreater(float(np.linalg.norm(picked.rotvecs[3, 2])), 1e-4)
        self.assertLess(
            float(np.linalg.norm(picked.omega[3, 2])),
            float(np.linalg.norm(picked.omega[2, 2])),
        )

    def test_fused_post_pass_refuses_flattened_motion(self) -> None:
        fused = np.zeros((6, 3, 3), dtype=np.float64)
        for frame in range(6):
            fused[frame, 2, 0] = math.radians(20.0 * math.sin(frame))
        flat = np.zeros_like(fused)
        report = motion_keep_report(fused, flat, range(6), rest=np.zeros((3, 3), dtype=np.float64))
        self.assertFalse(report["ok"])
        self.assertEqual(report["reason"], "motion_damped")


def copy_with_nudge(plant, source: ClipTrajectory, *, frame: int, joint: int) -> ClipTrajectory:
    out = ClipTrajectory(
        rotvecs=source.rotvecs.copy(),
        omega=source.omega.copy(),
        alpha_control=apply_nudge(
            source.alpha_control,
            frame=frame,
            joint=joint,
            direction=(1.0, 0.0, 0.0),
            rung=1.0,
            plant=plant,
        ),
        clamp_counts=source.clamp_counts.copy(),
        idle_rotvecs=source.idle_rotvecs.copy(),
        prefix_poses=source.prefix_poses.copy(),
        suffix_poses=None if source.suffix_poses is None else source.suffix_poses.copy(),
    )
    return out


if __name__ == "__main__":
    unittest.main()
