"""CPU tests for the identity-rest V2 to original-GLB rotation mapping."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np

EXPERIMENT = Path(__file__).resolve().parent
if str(EXPERIMENT) not in sys.path:
    sys.path.insert(0, str(EXPERIMENT))

from glb_skeleton import BindSkeleton
from mesh_preview import (
    fk_world_matrices,
    joint_world_from_pred_rot6d,
    model_fk_positions_mapped_to_source,
    rest_world_matrices,
    skin_vertices,
    source_local_rotations_from_model,
    validate_pose_vertices,
    validate_pose_world,
    validate_preview_camera,
)
from paths import MESHY, RUNS
from paths import MESHY


def axis_rotation(axis: int, angle: float) -> np.ndarray:
    c = float(np.cos(angle))
    s = float(np.sin(angle))
    out = np.eye(3, dtype=np.float64)
    a = int(axis)
    b = (a + 1) % 3
    d = (a + 2) % 3
    out[b, b] = c
    out[d, d] = c
    out[b, d] = -s
    out[d, b] = s
    return out


def fixture_skeleton() -> BindSkeleton:
    parents = np.asarray((-1, 0, 0, 1), dtype=np.int64)
    local_rotation = np.stack(
        (
            axis_rotation(1, 0.2),
            axis_rotation(2, -0.3),
            axis_rotation(0, 0.4),
            axis_rotation(1, 0.15),
        )
    )
    local_translation = np.asarray(
        (
            (0.25, -0.1, 0.3),
            (0.0, 1.0, 0.0),
            (0.8, 0.1, 0.0),
            (0.0, 0.65, 0.0),
        ),
        dtype=np.float64,
    )
    provisional = BindSkeleton(
        names=("root", "spine", "wing", "head"),
        node_indices=(0, 1, 2, 3),
        parents=tuple(int(value) for value in parents),
        rest_world=np.zeros((4, 3), dtype=np.float64),
        rest_local_rotation=local_rotation,
        rest_local_translation=local_translation,
        inverse_bind=None,
        vertices=None,
        vertex_joints=None,
        vertex_weights=None,
        triangles=None,
        uvs=None,
        normals=None,
        albedo=None,
    )
    rest = rest_world_matrices(provisional)
    return BindSkeleton(
        **{
            **provisional.__dict__,
            "rest_world": rest[:, :3, 3],
        }
    )


def skeleton_with_local_rotation(skeleton: BindSkeleton, local_rotation: np.ndarray) -> BindSkeleton:
    """Rebuild bind globals after changing the source linear bind blocks."""
    provisional = BindSkeleton(
        **{
            **skeleton.__dict__,
            "rest_local_rotation": np.asarray(local_rotation, dtype=np.float64),
        }
    )
    rest = rest_world_matrices(provisional)
    return BindSkeleton(**{**provisional.__dict__, "rest_world": rest[:, :3, 3]})


class NativeRotationTests(unittest.TestCase):
    def test_identity_model_rest_recovers_original_bind(self) -> None:
        skeleton = fixture_skeleton()
        identity = np.broadcast_to(np.eye(3), (1, 4, 3, 3)).copy()
        source_local = source_local_rotations_from_model(
            model_local_rotation=identity,
            skeleton=skeleton,
        )
        np.testing.assert_allclose(
            source_local[0], skeleton.rest_local_rotation, atol=1e-10, rtol=0.0
        )
        posed = fk_world_matrices(
            local_rotation=source_local[0],
            local_translation=skeleton.rest_local_translation,
            parents=np.asarray(skeleton.parents),
            root_world=skeleton.rest_world[0],
        )
        np.testing.assert_allclose(posed, rest_world_matrices(skeleton), atol=1e-10, rtol=0.0)

    def test_branching_positions_match_mapped_identity_bvh_fk(self) -> None:
        skeleton = fixture_skeleton()
        source_to_model = axis_rotation(2, 0.55)
        model_local = np.stack(
            (
                axis_rotation(0, 0.25),
                axis_rotation(1, -0.4),
                axis_rotation(2, 0.65),
                axis_rotation(0, 0.3),
            )
        )[None, ...]
        source_local = source_local_rotations_from_model(
            model_local_rotation=model_local,
            skeleton=skeleton,
            source_to_model=source_to_model,
        )
        actual = fk_world_matrices(
            local_rotation=source_local[0],
            local_translation=skeleton.rest_local_translation,
            parents=np.asarray(skeleton.parents),
            root_world=skeleton.rest_world[0],
        )[:, :3, 3]
        expected = model_fk_positions_mapped_to_source(
            model_local_rotation=model_local,
            skeleton=skeleton,
            source_to_model=source_to_model,
        )[0]
        np.testing.assert_allclose(actual, expected, atol=1e-10, rtol=0.0)
        # Both children of the root and the grandchild must survive the map.
        self.assertGreater(float(np.linalg.norm(actual[2] - actual[0])), 0.1)
        self.assertGreater(float(np.linalg.norm(actual[3] - actual[1])), 0.1)

    def test_vendor_6d_nonidentity_matches_canonical_fk(self) -> None:
        """Use the vendor's row-major first-two-rows 6D convention end to end."""
        skeleton = fixture_skeleton()
        source_to_model = axis_rotation(2, -0.35)
        model_local = np.stack(
            (
                axis_rotation(0, -0.2),
                axis_rotation(1, 0.5),
                axis_rotation(2, -0.6),
                axis_rotation(0, 0.35),
            )
        )
        # transforms3d.matrix_to_rotation_6d drops the last row, then flattens
        # the first two rows. Do not transpose this to the column convention.
        vendor_6d = model_local[:, :2, :].reshape(4, 6).astype(np.float32)[None, ...]
        actual = joint_world_from_pred_rot6d(
            pred_rot6d=vendor_6d,
            skeleton=skeleton,
            source_to_model=source_to_model,
        )[0, :, :3, 3]
        expected = model_fk_positions_mapped_to_source(
            model_local_rotation=model_local[None, ...],
            skeleton=skeleton,
            source_to_model=source_to_model,
        )[0]
        np.testing.assert_allclose(actual, expected, atol=2e-5, rtol=0.0)

    def test_pred_rot6d_identity_accepts_single_frame(self) -> None:
        skeleton = fixture_skeleton()
        identity = np.zeros((4, 6), dtype=np.float32)
        identity[:, 0] = 1.0
        identity[:, 4] = 1.0
        posed = joint_world_from_pred_rot6d(pred_rot6d=identity, skeleton=skeleton)
        np.testing.assert_allclose(
            posed, rest_world_matrices(skeleton), atol=1e-5, rtol=0.0
        )

    def test_real_crusader_identity_preserves_bind_skin(self) -> None:
        mesh = MESHY / "h3_crusader_smartrigged.glb"
        if not mesh.is_file():
            self.skipTest("crusader GLB missing")
        from glb_skeleton import load_bind_skeleton

        skeleton = load_bind_skeleton(mesh)
        identity = np.zeros((len(skeleton.names), 6), dtype=np.float32)
        identity[:, 0] = 1.0
        identity[:, 4] = 1.0
        posed = joint_world_from_pred_rot6d(pred_rot6d=identity, skeleton=skeleton)
        skinned = skin_vertices(skeleton, posed)
        error = float(np.linalg.norm(skinned - skeleton.vertices, axis=1).mean())
        self.assertLess(error, 1e-4)

    def test_nonexact_source_bind_uses_true_inverse(self) -> None:
        """A glTF bind scale residual must survive exact local recovery."""
        skeleton = fixture_skeleton()
        nonexact_local = skeleton.rest_local_rotation.copy()
        # This is deliberately not a rotation: the real GLB parser preserves
        # tiny imported scale/shear in each bind linear block.
        nonexact_local[3, 1, 1] *= 1.0002
        nonexact = skeleton_with_local_rotation(skeleton, nonexact_local)
        identity = np.broadcast_to(np.eye(3), (1, 4, 3, 3)).copy()
        recovered = source_local_rotations_from_model(
            model_local_rotation=identity,
            skeleton=nonexact,
        )
        np.testing.assert_allclose(recovered[0], nonexact_local, atol=1e-11, rtol=0.0)
        posed = fk_world_matrices(
            local_rotation=recovered[0],
            local_translation=nonexact.rest_local_translation,
            parents=np.asarray(nonexact.parents),
            root_world=nonexact.rest_world[0],
        )
        np.testing.assert_allclose(posed, rest_world_matrices(nonexact), atol=1e-11, rtol=0.0)

    def test_saved_paired_crusader_proposal_has_finite_native_pose(self) -> None:
        """Validate the saved paired artifact without invoking the model or renderer."""
        run = RUNS / "h3_crusader" / "attack_front_g12" / "paired_native_v1"
        proposal_path = run / "proposal.npz"
        reference_path = run / "reference" / "reference.npz"
        if not proposal_path.is_file() or not reference_path.is_file():
            self.skipTest("saved paired proposal is not present")
        from glb_skeleton import load_bind_skeleton

        mesh = MESHY / "h3_crusader_smartrigged.glb"
        if not mesh.is_file():
            self.skipTest("crusader GLB missing")
        skeleton = load_bind_skeleton(mesh)
        proposal = np.load(proposal_path)
        reference = np.load(reference_path)
        posed = joint_world_from_pred_rot6d(
            pred_rot6d=proposal["pred_rot6d"],
            skeleton=skeleton,
            source_to_model=reference["source_to_model"],
        )
        self.assertGreater(posed.shape[0], 0)
        for frame in posed:
            validate_pose_world(frame, joint_count=len(skeleton.parents))
            vertices = skin_vertices(skeleton, frame)
            validate_pose_vertices(vertices, vertex_count=len(skeleton.vertices))


class PreviewValidationTests(unittest.TestCase):
    def test_camera_rejects_nonfinite_or_degenerate_fields(self) -> None:
        valid = {
            "basisScreenRows": [[1.0, 0.0, 0.0], [0.0, -1.0, 0.0]],
            "pxPerWorld": 10.0,
            "screenOffsetPx": [4.0, 5.0],
        }
        validate_preview_camera(valid)
        for bad in (
            {**valid, "basisScreenRows": [[1.0, 0.0, 0.0], [1.0, 0.0, 0.0]]},
            {**valid, "pxPerWorld": float("nan")},
            {**valid, "pxPerWorld": 0.0},
            {**valid, "screenOffsetPx": [float("inf"), 5.0]},
        ):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    validate_preview_camera(bad)

    def test_pose_validation_rejects_singular_transform_and_vertices(self) -> None:
        valid_world = np.broadcast_to(np.eye(4), (2, 4, 4)).copy()
        validate_pose_world(valid_world[:1], joint_count=1)
        bad_transform = valid_world[:1].copy()
        bad_transform[0, 0, 0] = 0.0
        with self.assertRaises(ValueError):
            validate_pose_world(bad_transform, joint_count=1)
        bad_homogeneous = valid_world[:1].copy()
        bad_homogeneous[0, 3, 0] = 1.0
        with self.assertRaises(ValueError):
            validate_pose_world(bad_homogeneous, joint_count=1)
        validate_pose_vertices(np.zeros((3, 3), dtype=np.float64), vertex_count=3)
        with self.assertRaises(ValueError):
            validate_pose_vertices(np.full((3, 3), np.nan), vertex_count=3)


if __name__ == "__main__":
    unittest.main()
