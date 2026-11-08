"""CPU unit tests for the ragdoll inertia plant. No GPU."""
from __future__ import annotations

import math
import tempfile
import unittest
from pathlib import Path

import numpy as np

from ragdoll_inertia_plant import (
    EPSILON_OMEGA_DEG_S,
    EPSILON_THETA_DEG,
    FORBIDDEN_WRITE_PARTS,
    REPO_ROOT,
    SOLVER_ID,
    RagdollPlantConfig,
    RagdollState,
    assert_ragdoll_write_path,
    bounded_round_trip_radians,
    build_plant,
    death_skips_idle_end,
    deserialize_pose_radians,
    exclusive_peak_owners,
    forward_kinematics,
    geodesic_deg,
    idle_end_required,
    integrate_frame,
    make_chain_fixture,
    posed_vertices,
    serialize_pose_degrees,
    suffix_residual,
)


class RagdollPlantTests(unittest.TestCase):
    def test_frozen_root_without_owned_mass_still_builds(self) -> None:
        names = ("Root", "Limb")
        parents: tuple[int | None, ...] = (None, 0)
        translations = np.asarray(((0.0, 0.0, 0.0), (0.0, 1.0, 0.0)), dtype=np.float64)
        bases = np.stack([np.eye(3, dtype=np.float64)] * 2)
        positions = np.asarray(
            (
                (-0.1, 1.0, -0.1),
                (0.1, 1.0, -0.1),
                (0.1, 1.0, 0.1),
                (-0.1, 1.0, 0.1),
            ),
            dtype=np.float64,
        )
        triangles = np.asarray(((0, 1, 2), (0, 2, 3)), dtype=np.int64)
        joints = np.ones((4, 1), dtype=np.int64)
        weights = np.ones((4, 1), dtype=np.float64)
        plant = build_plant(
            node_names=names,
            parents=parents,
            translations=translations,
            base_rotations=bases,
            bind_positions=positions,
            triangles=triangles,
            joints=joints,
            weights=weights,
            frozen_root=0,
            collision_sample_count=4,
            collision_geodesic_min_hops=1,
        )
        self.assertGreater(float(plant.lambda_max[0]), 0.0)
        self.assertGreater(float(plant.lambda_max[1]), 0.0)
        self.assertEqual(float(plant.owned_mass[0]), 0.0)

    def test_fk_parents_after_children_in_index_order(self) -> None:
        names = ("Child", "Root")
        parents: tuple[int | None, ...] = (1, None)
        translations = np.asarray(((0.0, 1.0, 0.0), (0.0, 0.0, 0.0)), dtype=np.float64)
        bases = np.stack([np.eye(3, dtype=np.float64)] * 2)
        positions = np.asarray(
            (
                (-0.1, 1.0, -0.1),
                (0.1, 1.0, -0.1),
                (0.1, 1.0, 0.1),
                (-0.1, 1.0, 0.1),
            ),
            dtype=np.float64,
        )
        triangles = np.asarray(((0, 1, 2), (0, 2, 3)), dtype=np.int64)
        joints = np.zeros((4, 1), dtype=np.int64)
        weights = np.ones((4, 1), dtype=np.float64)
        plant = build_plant(
            node_names=names,
            parents=parents,
            translations=translations,
            base_rotations=bases,
            bind_positions=positions,
            triangles=triangles,
            joints=joints,
            weights=weights,
            frozen_root=1,
            collision_sample_count=4,
            collision_geodesic_min_hops=1,
        )
        self.assertGreater(float(np.linalg.norm(plant.bind_origins[0])), 0.5)
        self.assertGreater(float(plant.lambda_max[0]), 0.0)
        self.assertFalse(plant.massless_joints)

    def test_peak_owners_cover_every_skinned_vert(self) -> None:
        plant, _state = make_chain_fixture()
        self.assertEqual(int(plant.peak_owner.shape[0]), int(plant.bind_positions.shape[0]))
        self.assertTrue(np.all(plant.peak_owner >= 0))
        self.assertGreater(float(plant.owned_mass[2]), 0.0)

    def test_unassigned_vertex_fails_closed(self) -> None:
        joints = np.zeros((2, 1), dtype=np.int64)
        weights = np.zeros((2, 1), dtype=np.float64)
        with self.assertRaises(RuntimeError):
            exclusive_peak_owners(joints=joints, weights=weights, vertex_count=2)

    def test_singular_lambda_max_raises(self) -> None:
        names = ("Root", "Empty")
        parents: tuple[int | None, ...] = (None, 0)
        translations = np.zeros((2, 3), dtype=np.float64)
        translations[1, 1] = 1.0
        bases = np.stack([np.eye(3)] * 2)
        positions = np.asarray(((0.0, 0.0, 0.0), (0.1, 0.0, 0.0), (0.0, 0.1, 0.0)), dtype=np.float64)
        triangles = np.asarray(((0, 1, 2),), dtype=np.int64)
        joints = np.zeros((3, 1), dtype=np.int64)
        weights = np.ones((3, 1), dtype=np.float64)
        with self.assertRaises(RuntimeError):
            build_plant(
                node_names=names,
                parents=parents,
                translations=translations,
                base_rotations=bases,
                bind_positions=positions,
                triangles=triangles,
                joints=joints,
                weights=weights,
                frozen_root=0,
                collision_sample_count=3,
                collision_geodesic_min_hops=1,
            )

    def test_serializer_one_radian_is_57_degrees(self) -> None:
        plant, _state = make_chain_fixture()
        rotvecs = np.zeros((plant.joint_count(), 3), dtype=np.float64)
        rotvecs[2, 0] = 1.0
        pose = serialize_pose_degrees(plant, rotvecs)
        self.assertAlmostEqual(float(pose["Elbow"]["x"]), math.degrees(1.0), places=6)
        back = deserialize_pose_radians(plant, pose)
        self.assertAlmostEqual(float(back[2, 0]), 1.0, places=6)

    def test_preview_loader_round_trip(self) -> None:
        plant, _state = make_chain_fixture()
        rotvecs = np.zeros((plant.joint_count(), 3), dtype=np.float64)
        rotvecs[2, 0] = 1.0
        recovered = bounded_round_trip_radians(
            rotvecs,
            joint_limit_deg=150.0,
            bone_limit_scales=plant.bone_limit_scales,
        )
        self.assertLess(float(np.max(np.abs(recovered - rotvecs))), 1e-4)

    def test_gravity_only_droops_when_enabled(self) -> None:
        plant, state = make_chain_fixture(tilt_deg=25.0)
        start = float(np.linalg.norm(state.rotvecs[2]))
        later = state
        heavy = RagdollPlantConfig(gravity=9.81)
        for _ in range(8):
            later = integrate_frame(plant, later, config=heavy)
        self.assertGreater(float(np.linalg.norm(later.rotvecs[2])), start)
        self.assertGreater(float(np.linalg.norm(later.omega[2])), 1e-6)

    def test_zero_gravity_holds_rest(self) -> None:
        plant, state = make_chain_fixture(tilt_deg=0.0)
        later = state
        for _ in range(8):
            later = integrate_frame(plant, later)
        self.assertLess(float(np.linalg.norm(later.rotvecs)), 1e-8)
        self.assertLess(float(np.linalg.norm(later.omega)), 1e-8)

    def test_mid_clip_nudge_changes_later_frames(self) -> None:
        plant, state = make_chain_fixture(tilt_deg=0.0)
        baseline = []
        current = state
        for _ in range(4):
            current = integrate_frame(plant, current)
            baseline.append(current.rotvecs.copy())
        nudged = RagdollState(
            rotvecs=state.rotvecs.copy(),
            omega=state.omega.copy(),
            alpha_control=state.alpha_control.copy(),
            clamp_counts=state.clamp_counts.copy(),
        )
        nudged.alpha_control[2, 0] = float(plant.tau_budget / plant.lambda_max[2])
        first = integrate_frame(plant, nudged)
        first.alpha_control[:] = 0.0
        later = first
        for _ in range(3):
            later = integrate_frame(plant, later)
        self.assertGreater(float(np.linalg.norm(later.rotvecs - baseline[-1])), 1e-4)
        self.assertLess(
            float(np.linalg.norm(later.omega[2])),
            float(np.linalg.norm(first.omega[2])),
        )
        self.assertLess(float(np.linalg.norm(later.omega[2])), float(np.linalg.norm(first.omega[2])))

    def test_suffix_boundary_miss_rejects(self) -> None:
        plant, state = make_chain_fixture(tilt_deg=40.0)
        idle = np.zeros_like(state.rotvecs)
        report = suffix_residual(plant, state.rotvecs, state.omega, idle)
        self.assertFalse(report["ok"])
        self.assertGreater(float(report["thetaDeg"]), float(EPSILON_THETA_DEG))

    def test_suffix_idle_accepts_near_rest(self) -> None:
        plant, state = make_chain_fixture(tilt_deg=0.0)
        idle = np.zeros_like(state.rotvecs)
        report = suffix_residual(plant, idle, np.zeros_like(state.omega), idle)
        self.assertTrue(report["ok"])
        self.assertLessEqual(float(report["thetaDeg"]), float(EPSILON_THETA_DEG))
        self.assertLessEqual(float(report["omegaDegS"]), float(EPSILON_OMEGA_DEG_S))

    def test_death_does_not_require_idle_end(self) -> None:
        self.assertTrue(death_skips_idle_end((2, 5)))
        self.assertFalse(idle_end_required((2, 5)))
        self.assertTrue(idle_end_required((2, 0, 2)))
        self.assertFalse(death_skips_idle_end((2, 0, 2)))

    def test_writes_refuse_fused_push_and_meshy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            outside = Path(tmp) / "nope.json"
            with self.assertRaises(RuntimeError):
                assert_ragdoll_write_path(outside)
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
        meshy = REPO_ROOT / "artifacts" / "meshy_downloads" / "h3_goblin.glb"
        with self.assertRaises(RuntimeError):
            assert_ragdoll_write_path(meshy)
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
        self.assertIn("fused_push_v24_pipeline", FORBIDDEN_WRITE_PARTS)
        self.assertIn("meshy_downloads", FORBIDDEN_WRITE_PARTS)

    def test_hand_force_torques_ancestors(self) -> None:
        plant, state = make_chain_fixture()
        worlds = forward_kinematics(plant, state.rotvecs)
        vertices = posed_vertices(plant, worlds)
        hand = int(np.argmax(plant.peak_owner == 2))
        from ragdoll_inertia_plant import _add_force

        tau = np.zeros((3, 3), dtype=np.float64)
        _add_force(
            tau,
            plant,
            owner=2,
            point=vertices[hand],
            force=np.asarray((1.0, 0.0, 0.0)),
            origins=worlds[:, :3, 3],
        )
        self.assertGreater(float(np.linalg.norm(tau[2])), 0.0)
        self.assertGreater(float(np.linalg.norm(tau[1])), 0.0)
        self.assertEqual(float(np.linalg.norm(tau[0])), 0.0)

    def test_parent_rotation_redirects_child_alpha(self) -> None:
        plant, state = make_chain_fixture(tilt_deg=0.0)
        heavy = RagdollPlantConfig(gravity=9.81)
        identity = _plant_alpha_at(plant, state, config=heavy)
        rotated = RagdollState(
            rotvecs=state.rotvecs.copy(),
            omega=state.omega.copy(),
            alpha_control=state.alpha_control.copy(),
            clamp_counts=state.clamp_counts.copy(),
        )
        rotated.rotvecs[1, 1] = math.radians(90.0)
        turned = _plant_alpha_at(plant, rotated, config=heavy)
        self.assertGreater(float(np.linalg.norm(turned[2] - identity[2])), 1e-6)


def _plant_alpha_at(plant, state, *, config=None):
    from ragdoll_inertia_plant import _plant_alpha

    return _plant_alpha(plant, state.rotvecs, state.omega, config=config or RagdollPlantConfig())


if __name__ == "__main__":
    unittest.main()
