"""Contract tests for wrap-safe rotations and differentiable fixed-length FK."""
from __future__ import annotations

import math
import unittest

import numpy as np

from mesh_preview import fk_world_matrices
from pose_rotation_fk import (
    apply_joint_deltas,
    bone_lengths_from_world,
    bone_lengths_from_world_np,
    clamp_axis_angle_magnitude_np,
    compose_local,
    compose_local_np,
    edge_strain,
    fk_world,
    skin_lbs,
    so3_exp,
    so3_exp_np,
    so3_geodesic,
    so3_geodesic_np,
    so3_geodesic_sq,
    wrap_axis_angle,
    wrap_axis_angle_np,
)


def _chain():
    parents = np.asarray((-1, 0, 1), dtype=np.int64)
    offsets = np.zeros((3, 3), dtype=np.float64)
    offsets[1] = (1.0, 0.0, 0.0)
    offsets[2] = (1.0, 0.0, 0.0)
    return parents, offsets


class WrapAndGeodesicTests(unittest.TestCase):
    def test_magnitude_bound_is_not_a_component_clamp(self) -> None:
        over = np.array([1.2, 1.2, 1.2], dtype=np.float64)
        clamped = clamp_axis_angle_magnitude_np(over, 2.0)
        self.assertAlmostEqual(float(np.linalg.norm(clamped)), 2.0, places=6)
        self.assertGreater(float(np.linalg.norm(over)), 2.0)
        self.assertTrue(np.all(np.abs(over) < 2.0))
        axis = np.array([3.0, 0.0, 0.0], dtype=np.float64)
        np.testing.assert_allclose(clamp_axis_angle_magnitude_np(axis, 2.0), [2.0, 0.0, 0.0], atol=1e-12)

    def test_two_pi_wraps_to_identity(self) -> None:
        omega = np.array([0.0, 0.0, 2.0 * math.pi], dtype=np.float64)
        wrapped = wrap_axis_angle_np(omega)
        self.assertLess(float(np.linalg.norm(wrapped)), 1e-8)
        self.assertLess(float(np.linalg.norm(so3_exp_np(omega) - np.eye(3))), 1e-8)

    def test_float32_geodesic_of_identical_capture_locals_can_exceed_one_micro_rad(self) -> None:
        """Protected-joint checks must compare matrices. float32 acos(RᵀR) is not a 1e-6 zero."""
        import torch

        rotation = torch.tensor(
            [[0.999, 0.03, 0.0], [-0.03, 0.999, 0.0], [0.0, 0.0, 1.0]], dtype=torch.float32
        )
        self.assertGreater(float(so3_geodesic(rotation, rotation)), 1e-6)

    def test_geodesic_is_wrap_safe(self) -> None:
        plus = so3_exp_np(np.array([0.0, 0.0, math.pi * 0.5]))
        minus = so3_exp_np(np.array([0.0, 0.0, -math.pi * 1.5]))
        self.assertLess(float(so3_geodesic_np(plus, minus)), 1e-6)

    def test_zero_delta_is_identity_compose(self) -> None:
        base = so3_exp_np(np.array([0.2, -0.1, 0.4]))
        composed = compose_local_np(base, np.zeros(3))
        self.assertLess(float(np.max(np.abs(composed - base))), 1e-12)


class FixedLengthFkTests(unittest.TestCase):
    def test_zero_correction_matches_numpy_fk(self) -> None:
        import torch

        parents, offsets = _chain()
        local = np.repeat(np.eye(3)[None], 3, axis=0)
        local[1] = so3_exp_np(np.array([0.0, 0.0, 0.4]))
        root = np.array([0.1, 0.0, 0.0])
        expected = fk_world_matrices(
            local_rotation=local, local_translation=offsets, parents=parents, root_world=root
        )
        world = fk_world(
            torch.as_tensor(local[None], dtype=torch.float64),
            torch.as_tensor(offsets, dtype=torch.float64),
            parents,
            torch.as_tensor(root[None], dtype=torch.float64),
        )
        np.testing.assert_allclose(world[0].numpy(), expected, atol=1e-12)
        lengths = bone_lengths_from_world_np(expected, parents)
        np.testing.assert_allclose(lengths[1:], np.linalg.norm(offsets[1:], axis=1), atol=1e-12)

    def test_protected_joints_stay_exact_when_only_child_moves(self) -> None:
        import torch

        parents, offsets = _chain()
        base = np.repeat(np.eye(3)[None, None], 2, axis=0).repeat(3, axis=1)
        omega = torch.zeros((2, 1, 3), dtype=torch.float64)
        omega[:, 0, 2] = 0.3
        local = apply_joint_deltas(
            torch.as_tensor(base, dtype=torch.float64),
            omega,
            free_frames=torch.tensor([0, 1]),
            free_joints=torch.tensor([2]),
        )
        np.testing.assert_allclose(local[:, 0].detach().numpy(), base[:, 0], atol=1e-12)
        np.testing.assert_allclose(local[:, 1].detach().numpy(), base[:, 1], atol=1e-12)
        self.assertGreater(float(so3_geodesic_np(local[0, 2].detach().numpy(), base[0, 2])), 0.2)

    def test_bone_lengths_unchanged_after_child_rotation(self) -> None:
        import torch

        parents, offsets = _chain()
        base = np.repeat(np.eye(3)[None], 3, axis=0)
        local = compose_local_np(base, np.array([[0.0, 0.0, 0.0], [0.0, 0.5, 0.0], [0.0, 0.0, 0.7]]))
        world = fk_world(
            torch.as_tensor(local[None], dtype=torch.float64),
            torch.as_tensor(offsets, dtype=torch.float64),
            parents,
            torch.zeros((1, 3), dtype=torch.float64),
        )
        lengths = bone_lengths_from_world(world, parents)[0].numpy()
        np.testing.assert_allclose(lengths[1:], [1.0, 1.0], atol=1e-12)


class GradientTests(unittest.TestCase):
    def test_pose_gradients_are_finite_and_nonzero(self) -> None:
        import torch

        if not torch.cuda.is_available():
            self.skipTest("CUDA required for the skin/FK gradient path used in the pilot")
        parents, offsets = _chain()
        device = torch.device("cuda")
        base = torch.eye(3, dtype=torch.float32, device=device).expand(1, 3, 3, 3).contiguous()
        omega = torch.zeros((1, 1, 3), dtype=torch.float32, device=device, requires_grad=True)
        local = apply_joint_deltas(base, omega, free_frames=torch.tensor([0], device=device), free_joints=torch.tensor([1], device=device))
        world = fk_world(
            local,
            torch.as_tensor(offsets, dtype=torch.float32, device=device),
            parents,
            torch.zeros((1, 3), dtype=torch.float32, device=device),
        )
        verts = torch.tensor([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [2.0, 0.1, 0.0]], dtype=torch.float32, device=device)
        weights = torch.tensor([[1.0, 0.0, 0.0], [0.2, 0.8, 0.0], [0.0, 0.3, 0.7]], dtype=torch.float32, device=device)
        inverse = torch.eye(4, dtype=torch.float32, device=device).expand(3, 4, 4).contiguous()
        inverse[:, :3, 3] = -torch.as_tensor(np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [2.0, 0.0, 0.0]]), dtype=torch.float32, device=device)
        posed = skin_lbs(world, inverse, verts, weights)
        posed.sum().backward()
        self.assertTrue(torch.isfinite(omega.grad).all())
        self.assertGreater(float(omega.grad.abs().max()), 1e-6)

    def test_torch_wrap_matches_numpy(self) -> None:
        import torch

        omega = np.array([[0.0, 0.0, 3.0 * math.pi], [0.1, -0.2, 0.3]], dtype=np.float64)
        np.testing.assert_allclose(wrap_axis_angle(torch.as_tensor(omega)).numpy(), wrap_axis_angle_np(omega), atol=1e-12)
        np.testing.assert_allclose(so3_exp(torch.as_tensor(omega)).numpy(), so3_exp_np(omega), atol=1e-10)
        first = so3_exp_np(omega[1])
        second = so3_exp_np(-omega[1])
        self.assertAlmostEqual(
            float(so3_geodesic(torch.as_tensor(first), torch.as_tensor(second))),
            float(so3_geodesic_np(first, second)),
            places=6,
        )

    def test_identity_rotation_penalty_has_finite_zero_grad(self) -> None:
        import torch

        rotation = torch.eye(3, dtype=torch.float64)
        omega = torch.zeros(3, dtype=torch.float64, requires_grad=True)
        extra = so3_exp(omega)
        penalty = so3_geodesic_sq(rotation, extra @ rotation)
        self.assertLess(float(penalty.detach()), 1e-20)
        penalty.backward()
        self.assertTrue(torch.isfinite(omega.grad).all())
        self.assertLess(float(omega.grad.abs().max()), 1e-8)

    def test_geodesic_sq_is_wrap_safe_and_matches_chordal(self) -> None:
        import torch

        plus = so3_exp_np(np.array([0.0, 0.0, math.pi * 0.5]))
        minus = so3_exp_np(np.array([0.0, 0.0, -math.pi * 1.5]))
        self.assertLess(float(so3_geodesic_sq(torch.as_tensor(plus), torch.as_tensor(minus))), 1e-12)
        identity = np.eye(3)
        spun = so3_exp_np(np.array([0.0, 0.0, 2.0 * math.pi]))
        self.assertLess(float(so3_geodesic_sq(torch.as_tensor(identity), torch.as_tensor(spun))), 1e-12)
        offset = so3_exp_np(np.array([0.0, 0.4, 0.0]))
        angle = float(so3_geodesic_np(identity, offset))
        proxy = float(so3_geodesic_sq(torch.as_tensor(identity), torch.as_tensor(offset)))
        self.assertAlmostEqual(proxy, 2.0 * (1.0 - math.cos(angle)), places=6)

    def test_collapsed_edge_strain_gradient_is_finite(self) -> None:
        import torch

        verts = torch.tensor([[[0.0, 0.0, 0.0], [0.0, 0.0, 0.0]]], dtype=torch.float64, requires_grad=True)
        edges = torch.tensor([[0, 1]], dtype=torch.long)
        rest = torch.tensor([1.0], dtype=torch.float64)
        loss, _ = edge_strain(verts, edges, rest)
        loss.backward()
        self.assertTrue(torch.isfinite(verts.grad).all())


if __name__ == "__main__":
    unittest.main()
