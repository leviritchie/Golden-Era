from __future__ import annotations

import numpy as np
import torch

from mocap_skin_solver import (
    capsule_bone_weights,
    dual_quaternion_skin,
    fit_rest_skeleton_to_surface,
    local_offsets_from_world,
    optimize_sequence_weights_3d,
    pose_corrective_residuals_3d,
    region_capsule_weights,
    region_capsule_weights_3d,
    rest_world_from_offsets,
    sparsify_weights,
    topology_weight_support,
    MocapSparseWeightField,
    transfer_weights_from_donor,
    validate_weights,
)
from preview_behemoth_t2_smartrig import bind_relative_local_deltas


def test_capsule_weights_are_sparse_and_normalized():
    offsets = np.array([[0, 0, 0], [0, 1, 0], [0, 1, 0]], dtype=float)
    parents = np.array([-1, 0, 1])
    vertices = np.array([[0, 0.1, 0], [0.2, 1.2, 0], [0, 2, 0]], dtype=float)
    weights = capsule_bone_weights(vertices, offsets, parents, max_influences=3)
    validate_weights(weights, max_influences=3)


def test_bilateral_capsule_gate_rejects_opposite_limb():
    offsets = np.array([[0, 0, 0], [1, 0, 0], [-1, 0, 0]], dtype=float)
    parents = np.array([-1, 0, 0])
    vertices = np.array([[0.8, 0.0, 0.0], [-0.8, 0.0, 0.0]], dtype=float)
    weights = capsule_bone_weights(
        vertices,
        offsets,
        parents,
        max_influences=3,
        side_axis=np.array([1.0, 0.0, 0.0]),
        side_labels=np.array([0, 1, -1]),
        side_origin=np.zeros(3),
    )
    assert weights[0, 1] > weights[0, 2]
    assert weights[1, 2] > weights[1, 1]
    assert weights[0, 2] < 1e-10
    assert weights[1, 1] < 1e-10


def test_capsule_allowed_mask_is_hard_and_normalized():
    offsets = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype=float)
    parents = np.array([-1, 0, 0])
    vertices = np.array([[0.8, 0.0, 0.0], [0.0, 0.8, 0.0]], dtype=float)
    weights = capsule_bone_weights(
        vertices, offsets, parents, max_influences=2,
        allowed_mask=np.array([True, False, False]),
    )
    assert np.allclose(weights[:, 0], 1.0)
    assert np.allclose(weights[:, 1:], 0.0)


def test_region_capsule_weights_covers_named_regions():
    offsets = np.array([[0, 0, 0], [0, 1, 0], [1, 0, 0]], dtype=float)
    parents = np.array([-1, 0, 0])
    names = ["mixamorig:Hips", "mixamorig:Spine", "mixamorig:RightArm"]
    vertices = np.array([[0, 0.5, 0], [0.9, 0.1, 0]], dtype=float)
    weights = region_capsule_weights(
        vertices, offsets, parents, names, np.eye(3),
        {"torso": ("mixamorig:Hips", "mixamorig:Spine"),
         "arm_right": ("mixamorig:RightArm",)},
        region_widths={"torso": 0.30, "arm_right": 0.05},
        max_influences=2,
    )
    validate_weights(weights, max_influences=2)
    assert weights[0, 0] >= 0.5
    assert weights[1, 2] > 0.5


def test_region_capsule_weights_3d_is_camera_free_and_sparse():
    offsets = np.array([[0, 0, 0], [0, 1, 0], [1, 0, 0], [-1, 0, 0]], dtype=float)
    parents = np.array([-1, 0, 0, 0])
    names = ["mixamorig:Hips", "mixamorig:Spine", "mixamorig:RightArm", "mixamorig:LeftArm"]
    vertices = np.array([[0, 0.5, 0], [0.9, 0.1, 0], [-0.9, 0.1, 0], [0.0, 0.0, 0.4]], dtype=float)
    weights = region_capsule_weights_3d(
        vertices, offsets, parents, names,
        {"torso": ("mixamorig:Hips", "mixamorig:Spine"),
         "arm_right": ("mixamorig:RightArm",),
         "arm_left": ("mixamorig:LeftArm",)},
        max_influences=2,
    )
    validate_weights(weights, max_influences=2)
    assert weights[1, 2] > 0.5
    assert weights[2, 3] > 0.5


def test_region_capsule_weights_3d_keeps_nearest_cranial_region_exclusive():
    # A broad softmax can leave an arm as a secondary influence even when the
    # head region is the nearest 3-D owner. That makes muzzle vertices follow
    # an unrelated limb during motion; semantic cranial regions must win
    # exclusively at their nearest surface.
    offsets = np.array([
        [0.0, 0.0, 0.0],
        [0.0, 0.2, 0.0],
        [0.0, 0.2, 0.0],
        [0.2, 0.2, 0.0],
        [1.0, 0.0, 0.0],
    ])
    parents = np.array([-1, 0, 1, 2, 0])
    names = [
        "mixamorig:Hips", "mixamorig:Spine", "mixamorig:Spine2",
        "mixamorig:Head", "mixamorig:RightArm",
    ]
    regions = {
        "torso": ("mixamorig:Hips", "mixamorig:Spine", "mixamorig:Spine2"),
        "neck_head": ("mixamorig:Head",),
        "arm_right": ("mixamorig:RightArm",),
    }
    vertex = np.array([[0.6, 0.5, 0.0]])
    weights = region_capsule_weights_3d(
        vertex, offsets, parents, names, regions,
        max_influences=2, exclusive_region_tokens=("head", "neck"),
    )
    assert weights[0, names.index("mixamorig:Head")] > 0.99
    assert weights[0, names.index("mixamorig:RightArm")] < 1e-8


def test_sparsify_weights_preserves_row_normalization():
    weights = sparsify_weights(np.array([[0.1, 0.2, 0.7], [0.4, 0.3, 0.3]]), max_influences=2)
    validate_weights(weights, max_influences=2)


def test_topology_weight_support_preserves_dominant_and_unique_ids():
    weights = np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]], dtype=float)
    support = topology_weight_support(
        weights, np.array([[0, 1], [1, 2]], dtype=np.int64), max_influences=2
    )
    assert support.shape == (3, 2)
    assert np.all(np.any(support == np.argmax(weights, axis=1)[:, None], axis=1))
    assert np.all(np.diff(np.sort(support, axis=1), axis=1) > 0)


def test_pose_corrective_identity_sequence_is_zero():
    rest = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype=float)
    faces = np.array([[0, 1, 2]], dtype=np.int64)
    weights = np.eye(3, dtype=float)
    posed = np.repeat(rest[None], 2, axis=0)
    transforms = np.repeat(np.eye(4, dtype=float)[None, None], 6, axis=0).reshape(2, 3, 4, 4)
    residuals, history = pose_corrective_residuals_3d(
        rest, posed, faces, weights, transforms, steps=2
    )
    assert np.allclose(residuals, 0.0)
    assert len(history) == 2


def test_sequence_weight_optimizer_preserves_identity_pose_weights():
    rest = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype=float)
    faces = np.array([[0, 1, 2]], dtype=np.int64)
    initial = np.eye(3, dtype=float)
    transforms = torch.eye(4).repeat(2, 3, 1, 1)
    weights, history = optimize_sequence_weights_3d(
        rest, faces, initial, transforms, max_influences=1, steps=2,
        max_edges=8, max_triangles=8,
    )
    validate_weights(weights, max_influences=1)
    assert np.allclose(weights, initial, atol=1e-4)
    assert len(history) == 2


def test_sequence_arap_is_zero_for_translated_rotated_rigid_triangles():
    # An off-origin asymmetric triangle catches coordinate-axis centering.
    rest = np.array([[2, 3, 4], [3, 3, 4], [2.2, 4.4, 4.5]], dtype=float)
    faces = np.array([[0, 1, 2]], dtype=np.int64)
    initial = np.ones((3, 1))
    transforms = torch.eye(4).repeat(3, 1, 1, 1)
    transforms[1, 0, :3, 3] = torch.tensor([4., -2., 1.])
    transforms[2, 0, :3, :3] = torch.tensor([[0., -1., 0.], [1., 0., 0.], [0., 0., 1.]])
    transforms[2, 0, :3, 3] = torch.tensor([-1., 3., 2.])
    _, history = optimize_sequence_weights_3d(
        rest, faces, initial, transforms, max_influences=1, steps=1,
    )
    assert history[0]['arap'] < 1e-10


def test_sequence_returns_evaluated_best_state_not_unmeasured_update():
    from unittest.mock import patch
    rest = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype=float)
    faces = np.array([[0, 1, 2]], dtype=np.int64)
    initial = np.tile([.8, .2], (3, 1))
    transforms = torch.eye(4).repeat(2, 2, 1, 1)
    updates = []

    def force_distinct_unmeasured_update(optimizer, closure=None):
        with torch.no_grad():
            for group in optimizer.param_groups:
                for parameter in group['params']:
                    parameter.add_(torch.arange(parameter.shape[-1], dtype=parameter.dtype) * 10)
        updates.append(True)

    with patch.object(torch.optim.Adam, 'step', force_distinct_unmeasured_update):
        weights, history = optimize_sequence_weights_3d(
            rest, faces, initial, transforms, max_influences=2, steps=1,
        )
    assert updates == [True]
    assert len(history) == 1
    np.testing.assert_allclose(weights, initial, atol=1e-6)


def test_sequence_weight_optimizer_rejects_degenerate_topology():
    rest = np.array([[0, 0, 0], [0, 0, 0], [0, 0, 0]], dtype=float)
    faces = np.array([[0, 1, 2]], dtype=np.int64)
    initial = np.eye(3, dtype=float)
    transforms = torch.eye(4).repeat(2, 3, 1, 1)
    try:
        optimize_sequence_weights_3d(rest, faces, initial, transforms, max_influences=1, steps=1)
    except ValueError as exc:
        assert "nondegenerate mesh edge" in str(exc)
    else:
        raise AssertionError("degenerate topology must fail closed")


def test_sequence_weight_optimizer_rejects_invalid_motion_floor():
    rest = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype=float)
    faces = np.array([[0, 1, 2]], dtype=np.int64)
    initial = np.eye(3, dtype=float)
    transforms = torch.eye(4).repeat(2, 3, 1, 1)
    try:
        optimize_sequence_weights_3d(
            rest, faces, initial, transforms, max_influences=1,
            steps=1, motion_floor=0.0,
        )
    except ValueError as exc:
        assert "motion_floor" in str(exc)
    else:
        raise AssertionError("invalid motion floor must fail closed")


def test_sequence_weight_optimizer_rejects_invalid_weight_variation_cap():
    rest = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype=float)
    faces = np.array([[0, 1, 2]], dtype=np.int64)
    initial = np.eye(3, dtype=float)
    transforms = torch.eye(4).repeat(2, 3, 1, 1)
    try:
        optimize_sequence_weights_3d(
            rest, faces, initial, transforms, max_influences=1,
            steps=1, max_total_variation=0.0,
        )
    except ValueError as exc:
        assert "max_total_variation" in str(exc)
    else:
        raise AssertionError("invalid weight variation cap must fail closed")


def test_bind_relative_local_delta_solves_anchor_composition():
    def rz(degrees):
        angle = np.deg2rad(degrees)
        return np.array([[np.cos(angle), -np.sin(angle), 0.0],
                         [np.sin(angle), np.cos(angle), 0.0],
                         [0.0, 0.0, 1.0]])

    def rx(degrees):
        angle = np.deg2rad(degrees)
        return np.array([[1.0, 0.0, 0.0],
                         [0.0, np.cos(angle), -np.sin(angle)],
                         [0.0, np.sin(angle), np.cos(angle)]])

    anchor = np.stack((rz(55), rz(-20)))
    current = np.stack((rx(35), rz(40) @ rx(-25)))[None]
    delta = bind_relative_local_deltas(current, anchor)
    assert np.allclose(anchor[None] @ delta, current, atol=1e-7)
    assert not np.allclose(delta, current @ np.swapaxes(anchor, -1, -2)[None], atol=1e-4)


def test_surface_transfer_preserves_donor_one_hot_regions():
    donor = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype=float)
    donor_weights = np.eye(3)
    weights = transfer_weights_from_donor(donor, donor, donor_weights, neighbors=2, max_influences=3)
    assert np.allclose(weights, donor_weights)


def test_dual_quaternion_identity_is_exact():
    vertices = torch.tensor([[1.0, 2.0, 3.0], [0.0, 0.0, 0.0]], device="cuda")
    weights = torch.tensor([[1.0, 0.0], [0.0, 1.0]], device="cuda")
    transforms = torch.eye(4, device="cuda").repeat(1, 2, 1, 1)
    posed = dual_quaternion_skin(vertices, weights, transforms)
    assert torch.allclose(posed[0], vertices, atol=1e-5)


def test_rest_fit_changes_joint_translations_only():
    rest = np.repeat(np.eye(4)[None], 2, axis=0)
    rest[1, :3, 3] = [0, 1, 0]
    fitted, scale = fit_rest_skeleton_to_surface(rest, np.array([[0, 0, 0], [2, 4, 6]], dtype=float))
    assert np.all(scale > 0)
    assert float(scale.max() / scale.min()) <= 2.0 + 1e-6
    assert np.allclose(fitted[:, :3, :3], rest[:, :3, :3])


def test_symmetric_3d_rest_fit_changes_joint_translations_only():
    rest = np.repeat(np.eye(4)[None], 2, axis=0)
    rest[1, :3, 3] = [0, 1, 0]
    fitted, scale = fit_rest_skeleton_to_surface(
        rest, np.array([[0, 0, 0], [2, 4, 6]], dtype=float), objective="symmetric_3d"
    )
    assert np.all(scale > 0)
    assert np.allclose(fitted[:, :3, :3], rest[:, :3, :3])


def test_world_fit_round_trips_to_parent_relative_offsets():
    offsets = np.array([[0.2, -0.1, 0.3], [0.0, 1.0, 0.0], [0.4, 0.0, -0.2]])
    parents = np.array([-1, 0, 1])
    world = rest_world_from_offsets(offsets, parents)
    recovered = local_offsets_from_world(world, parents)
    assert np.allclose(recovered, offsets)


def test_dual_quaternion_support_relative_hemisphere_is_finite():
    def rz(degrees):
        angle = np.deg2rad(degrees)
        c, s = np.cos(angle), np.sin(angle)
        matrix = torch.eye(4, device="cuda")
        matrix[:3, :3] = torch.tensor([[c, -s, 0], [s, c, 0], [0, 0, 1]], device="cuda")
        return matrix

    vertices = torch.tensor([[1.0, 0.0, 0.0]], device="cuda")
    # Joint 0 is deliberately unrelated to the vertex support.  Its 180
    # degree quaternion would be a poor global sign reference.
    transforms = torch.stack((rz(180), rz(0), rz(-179)), dim=0).unsqueeze(0)
    weights = torch.tensor([[0.0, 0.5, 0.5]], device="cuda")
    posed = dual_quaternion_skin(vertices, weights, transforms)
    assert torch.isfinite(posed).all()
    # The local support should land near the -89.5 degree midpoint, not
    # collapse toward the unrelated joint-0 hemisphere.
    expected = torch.tensor([[np.cos(np.deg2rad(-89.5)), np.sin(np.deg2rad(-89.5)), 0.0]], device="cuda")
    assert torch.linalg.vector_norm(posed - expected) < 0.08


def test_sparse_field_respects_influence_budget():
    field = MocapSparseWeightField(np.array([[0.7, 0.2, 0.1], [0.0, 1.0, 0.0]], dtype=float), max_influences=2, device="cpu")
    weights = field.weights().detach().numpy()
    assert np.allclose(weights.sum(1), 1.0)
    assert int((weights > 1e-8).sum(1).max()) <= 2
