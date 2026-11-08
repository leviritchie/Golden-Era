"""Analytic regression tests for rest-space retargeting, not render-score tests."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from owned_rerig.rest_retarget import (  # noqa: E402
    corresponding_source_rest, outgoing_skin_transforms, retarget_motion,
)


NAMES = [
    "Hips", "Spine", "Spine1", "Spine2", "Neck", "Head", "HeadTop_End",
    "LeftShoulder", "LeftArm", "LeftForeArm", "LeftHand",
    "RightShoulder", "RightArm", "RightForeArm", "RightHand",
    "LeftUpLeg", "LeftLeg", "LeftFoot", "LeftToeBase", "LeftToe_End",
    "RightUpLeg", "RightLeg", "RightFoot", "RightToeBase", "RightToe_End",
]
PARENTS = [None, 0, 1, 2, 3, 4, 5, 3, 7, 8, 9, 3, 11, 12, 13,
           0, 15, 16, 17, 18, 0, 20, 21, 22, 23]


def rotation(axis, angle):
    axis = np.asarray(axis, dtype=float)
    axis /= np.linalg.norm(axis)
    x, y, z = axis
    skew = np.array([[0, -z, y], [z, 0, -x], [-y, x, 0]])
    return np.eye(3) + np.sin(angle) * skew + (1 - np.cos(angle)) * (skew @ skew)


def fixture(t_pose=False):
    offsets = np.array([
        [0, 1, 0], [0, .16, 0], [0, .13, 0], [0, .13, 0],
        [0, .12, 0], [0, .12, 0], [0, .16, 0],
        [.08, .025, 0], [.13, -.02, 0], [.22, -.24, 0], [.27, -.12, 0],
        [-.08, .025, 0], [-.13, -.02, 0], [-.22, -.24, 0], [-.27, -.12, 0],
        [.16, 0, 0], [0, -.43, 0], [0, -.40, 0], [0, -.06, .20], [0, 0, .08],
        [-.16, 0, 0], [0, -.43, 0], [0, -.40, 0], [0, -.06, .20], [0, 0, .08],
    ])
    if t_pose:
        offsets *= np.linspace(.85, 1.4, len(NAMES))[:, None]
        for joint in (8, 9, 10, 12, 13, 14):
            offsets[joint] = [np.sign(offsets[joint, 0]) * np.linalg.norm(offsets[joint]), 0, 0]
    points = offsets.copy()
    for j, parent in enumerate(PARENTS):
        if parent is not None:
            points[j] += points[parent]
    return points


class RestRetargetTests(unittest.TestCase):
    def setUp(self):
        self.source = fixture()
        self.yaw = rotation([0, 1, 0], np.deg2rad(46))
        self.target = fixture(True) @ self.yaw.T + [2, .4, -1]

    def run_retarget(self, frames, **kwargs):
        return retarget_motion(self.source, self.target, PARENTS, NAMES, frames, **kwargs)

    def assertRigidAndAnchored(self, result, target=None):
        target = self.target if target is None else target
        rs, points = result["rotations"], result["frame_joints"]
        identity = np.broadcast_to(np.eye(3), rs.shape)
        np.testing.assert_allclose(rs @ rs.swapaxes(-1, -2), identity, atol=2e-12)
        np.testing.assert_allclose(np.linalg.det(rs), 1, atol=2e-12)
        np.testing.assert_allclose(np.einsum("fjab,jb->fja", rs, target) + result["offsets"],
                                   points, atol=2e-12)
        for j, p in enumerate(PARENTS):
            if p is not None:
                np.testing.assert_allclose(np.linalg.norm(points[:, j] - points[:, p], axis=-1),
                                           np.linalg.norm(target[j] - target[p]), atol=2e-12)
                # A link's transform maps BOTH endpoints, not just its anchor.
                np.testing.assert_allclose(np.einsum("fab,b->fa", rs[:, j], target[p])
                                           + result["offsets"][:, j], points[:, p], atol=2e-12)

    def test_rest_maps_to_fitted_rest_and_identity_skin(self):
        result = self.run_retarget(self.source[None])
        np.testing.assert_allclose(result["frame_joints"][0], self.target, atol=2e-12)
        np.testing.assert_allclose(result["rotations"][0], np.tile(np.eye(3), (25, 1, 1)), atol=2e-12)
        np.testing.assert_allclose(result["offsets"], 0, atol=2e-12)
        np.testing.assert_allclose(result["source_to_target_rotation"], self.yaw, atol=2e-12)
        self.assertRigidAndAnchored(result)

    def test_global_rotation_uses_target_frame_not_source_directions(self):
        motion = rotation([1, 2, 3], .67)
        travel = np.array([.3, -.1, .2])
        frame = (self.source - self.source[0]) @ motion.T + self.source[0] + travel
        result = self.run_retarget(frame[None])
        expected_rotation = self.yaw @ motion @ self.yaw.T
        expected = ((self.target - self.target[0]) @ expected_rotation.T
                    + self.target[0] + self.yaw @ travel)
        np.testing.assert_allclose(result["frame_joints"][0], expected, atol=2e-12)
        np.testing.assert_allclose(result["rotations"][0],
                                   np.tile(expected_rotation, (25, 1, 1)), atol=2e-12)
        self.assertRigidAndAnchored(result)

    def test_arm_local_change_respects_different_rest_pose(self):
        motion = rotation([0, 0, 1], .65)
        frame = self.source.copy()
        frame[9:11] = (frame[9:11] - frame[8]) @ motion.T + frame[8]
        result = self.run_retarget(frame[None])
        target_motion = self.yaw @ motion @ self.yaw.T
        expected = self.target.copy()
        expected[9:11] = (expected[9:11] - expected[8]) @ target_motion.T + expected[8]
        np.testing.assert_allclose(result["frame_joints"][0], expected, atol=2e-12)
        self.assertRigidAndAnchored(result)

    def test_parent_twist_is_retained_when_joint_positions_cannot_show_it(self):
        # Yaw leaves all central spine positions unchanged. Independent incoming
        # link swing would return identity there, incorrectly leaving skin/normals still.
        motion = rotation([0, 1, 0], .8)
        frame = (self.source - self.source[0]) @ motion.T + self.source[0]
        result = self.run_retarget(frame[None])
        np.testing.assert_allclose(result["frame_joints"][0, 1:7], self.target[1:7], atol=2e-12)
        expected = self.yaw @ motion @ self.yaw.T
        np.testing.assert_allclose(result["rotations"][0, 5], expected, atol=2e-12)
        normal = np.array([1., 0., 0.])
        np.testing.assert_allclose(result["rotations"][0, 5] @ normal, expected @ normal, atol=2e-12)
        self.assertGreater(np.linalg.norm(expected @ normal - normal), .5)

    def test_noncommuting_parent_and_child_local_changes(self):
        def rest_basis(points, joint):
            y = points[joint] - points[PARENTS[joint]]
            y /= np.linalg.norm(y)
            z = np.array([0., 0., 1.])
            return np.column_stack((np.cross(y, z), y, z))

        source, target = self.source, fixture(True)
        root_rotation = rotation([0, 1, 0], .48)
        parent_change = rotation([0, 0, 1], .7)
        child_change = rotation([1, 0, 0], -.8)
        source_rotations = np.tile(root_rotation, (25, 1, 1))
        target_rotations = source_rotations.copy()
        for rest, rs in ((source, source_rotations), (target, target_rotations)):
            b9, b10 = rest_basis(rest, 9), rest_basis(rest, 10)
            f9 = root_rotation @ b9 @ parent_change
            f10 = f9 @ (b9.T @ b10) @ child_change
            rs[9], rs[10] = f9 @ b9.T, f10 @ b10.T
        posed = []
        for rest, rs in ((source, source_rotations), (target, target_rotations)):
            points = rest.copy()
            for j, p in enumerate(PARENTS):
                if p is not None:
                    points[j] = points[p] + rs[j] @ (rest[j] - rest[p])
            posed.append(points)
        target = target @ self.yaw.T + [2, .4, -1]
        result = retarget_motion(source, target, PARENTS, NAMES, posed[0][None])
        expected_points = posed[1] @ self.yaw.T + [2, .4, -1]
        expected_rotations = self.yaw @ target_rotations @ self.yaw.T
        np.testing.assert_allclose(result["frame_joints"][0], expected_points, atol=2e-12)
        np.testing.assert_allclose(result["rotations"][0], expected_rotations, atol=2e-12)
        self.assertRigidAndAnchored(result, target)

    def test_identity_retarget_reproduces_positions(self):
        frames = np.stack([self.source.copy() for _ in range(3)])
        for f, angle in enumerate((0, .4, -.8)):
            frames[f, 9:11] = ((self.source[9:11] - self.source[8])
                               @ rotation([0, 0, 1], angle).T + self.source[8])
        result = retarget_motion(self.source, self.source, PARENTS, NAMES, frames)
        np.testing.assert_allclose(result["frame_joints"], frames, atol=2e-12)
        self.assertRigidAndAnchored(result, self.source)

    def test_independent_source_and_target_coordinate_changes(self):
        motion = rotation([1, 2, 3], .5)
        frames = ((self.source - self.source[0]) @ motion.T + self.source[0] + [.1, .2, .3])[None]
        baseline = self.run_retarget(frames)
        s, t = rotation([2, 1, 3], -.7), rotation([3, 1, 2], .9)
        st, tt = np.array([4., -3., 2.]), np.array([-2., 5., 1.])
        result = retarget_motion(self.source @ s.T + st, self.target @ t.T + tt,
                                 PARENTS, NAMES, frames @ s.T + st)
        np.testing.assert_allclose(result["frame_joints"], baseline["frame_joints"] @ t.T + tt, atol=2e-12)
        np.testing.assert_allclose(result["rotations"], t @ baseline["rotations"] @ t.T, atol=2e-12)
        expected_offset = baseline["offsets"] @ t.T + tt - np.einsum("fjab,b->fja", result["rotations"], tt)
        np.testing.assert_allclose(result["offsets"], expected_offset, atol=2e-12)

    def test_root_travel_scale_is_explicit(self):
        travel = np.array([.2, -.1, .3])
        for scale in (0, .5, 2):
            result = self.run_retarget((self.source + travel)[None], root_translation_scale=scale)
            np.testing.assert_allclose(result["frame_joints"][0],
                                       self.target + scale * (self.yaw @ travel), atol=2e-12)

    def test_source_length_noise_does_not_resize_target(self):
        frame = self.source.copy()
        for j, p in enumerate(PARENTS):
            if p is not None:
                frame[j] = frame[p] + (1 + .01 * j) * (self.source[j] - self.source[p])
        result = self.run_retarget(frame[None])
        np.testing.assert_allclose(result["frame_joints"][0], self.target, atol=2e-12)
        self.assertRigidAndAnchored(result)

    def test_exact_half_turn_is_proper_and_deterministic(self):
        frame = self.source.copy()
        frame[9:11] = 2 * frame[8] - frame[9:11]
        result = self.run_retarget(frame[None])
        self.assertRigidAndAnchored(result)
        np.testing.assert_allclose(result["frame_joints"][0, 9],
                                   2 * self.target[8] - self.target[9], atol=2e-12)
        np.testing.assert_array_equal(result["rotations"], self.run_retarget(frame[None])["rotations"])

    def test_batch_matches_single_frames_and_does_not_mutate_inputs(self):
        frames = np.stack([self.source, self.source + [.2, .1, 0]])
        originals = [array.copy() for array in (self.source, self.target, frames)]
        result = self.run_retarget(frames)
        for f in range(len(frames)):
            single = self.run_retarget(frames[f:f+1])
            for key in ("frame_joints", "rotations", "offsets"):
                np.testing.assert_allclose(result[key][f], single[key][0], atol=2e-12)
        for old, new in zip(originals, (self.source, self.target, frames)):
            np.testing.assert_array_equal(old, new)

    def test_unordered_namespaced_tree_and_minus_one_root(self):
        permutation = np.random.default_rng(7).permutation(25)
        inverse = np.argsort(permutation)
        parents = [-1 if PARENTS[j] is None else int(inverse[PARENTS[j]]) for j in permutation]
        names = [f"mixamorig:{NAMES[j]}" for j in permutation]
        result = retarget_motion(self.source[permutation], self.target[permutation], parents, names,
                                 self.source[None, permutation])
        np.testing.assert_allclose(result["frame_joints"][0, inverse], self.target, atol=2e-12)

    def test_empty_clip_returns_correct_shapes(self):
        result = self.run_retarget(np.empty((0, 25, 3)))
        self.assertEqual(result["frame_joints"].shape, (0, 25, 3))
        self.assertEqual(result["rotations"].shape, (0, 25, 3, 3))
        self.assertEqual(result["offsets"].shape, (0, 25, 3))

    def test_invalid_input_errors_are_specific(self):
        with self.assertRaisesRegex(ValueError, "finite"):
            self.run_retarget(np.full((1, 25, 3), np.nan))
        with self.assertRaisesRegex(ValueError, "shape"):
            self.run_retarget(self.source)
        with self.assertRaisesRegex(ValueError, "root_translation_scale"):
            self.run_retarget(self.source[None], root_translation_scale=-1)
        parents = list(PARENTS)
        parents[9], parents[10] = 10, 9
        with self.assertRaisesRegex(ValueError, "cycles"):
            retarget_motion(self.source, self.target, parents, NAMES, self.source[None])
        frame = self.source.copy()
        frame[9] = frame[8]
        with self.assertRaisesRegex(ValueError, "frame link"):
            self.run_retarget(frame[None])
        target = self.target.copy()
        target[9] = target[8]
        with self.assertRaisesRegex(ValueError, "target rest link 9"):
            retarget_motion(self.source, target, PARENTS, NAMES, self.source[None])


class CorrespondingSourceRestTests(unittest.TestCase):
    @staticmethod
    def body_axes(points):
        side = points[15] - points[20]
        side /= np.linalg.norm(side)
        up = points[1] - points[0]
        up -= (up @ side) * side
        up /= np.linalg.norm(up)
        return np.column_stack((side, up, np.cross(side, up)))

    def test_authored_60_degree_arms_do_not_double_close(self):
        source = fixture(True)
        target = source.copy()
        for pivot, joints, sign in ((8, [9, 10], -1), (12, [13, 14], 1)):
            turn = rotation([0, 0, 1], sign * np.pi / 3)
            target[joints] = (source[joints] - source[pivot]) @ turn.T + source[pivot]
        reference = corresponding_source_rest(source, target, PARENTS, NAMES)
        np.testing.assert_allclose(reference, target, atol=2e-12)
        wrong = retarget_motion(source, target, PARENTS, NAMES, target[None])
        wrong_arm = wrong["frame_joints"][0, 9] - wrong["frame_joints"][0, 8]
        original_arm = source[9] - source[8]
        cosine = wrong_arm @ original_arm / np.linalg.norm(wrong_arm) / np.linalg.norm(original_arm)
        self.assertAlmostEqual(cosine, np.cos(2 * np.pi / 3))
        motion = retarget_motion(reference, target, PARENTS, NAMES, target[None])
        skin = outgoing_skin_transforms(motion, target, PARENTS, NAMES)
        np.testing.assert_allclose(skin["frame_joints"][0], target, atol=2e-12)
        np.testing.assert_allclose(skin["rotations"][0], np.tile(np.eye(3), (25, 1, 1)), atol=2e-12)
        np.testing.assert_allclose(skin["offsets"], 0, atol=2e-12)

    def test_asymmetric_pelvis_preserves_axes_lengths_and_common_direction_rotation(self):
        source = fixture(True)
        source[15] = source[0] + [.31, -.09, .02]
        source[20] = source[0] + [-.12, -.02, -.04]
        source = source @ rotation([1, 2, 3], .7).T + [3, -2, 5]
        target = fixture()
        target[15] = target[0] + [.1, -.14, .06]
        target[20] = target[0] + [-.24, -.08, .09]
        target = target @ rotation([3, 1, 2], -.8).T + [-1, 4, 2]
        originals = source.copy(), target.copy()
        result = corresponding_source_rest(source, target, PARENTS, NAMES)
        np.testing.assert_array_equal(result[0], source[0])
        np.testing.assert_allclose(self.body_axes(result), self.body_axes(source), atol=2e-12)
        child = np.arange(1, 25)
        parent = np.array(PARENTS[1:])
        src_vectors = source[child] - source[parent]
        dst_vectors = target[child] - target[parent]
        got_vectors = result[child] - result[parent]
        np.testing.assert_allclose(np.linalg.norm(got_vectors, axis=1),
                                   np.linalg.norm(src_vectors, axis=1), atol=2e-12)
        desired = dst_vectors / np.linalg.norm(dst_vectors, axis=1, keepdims=True)
        actual = got_vectors / np.linalg.norm(got_vectors, axis=1, keepdims=True)
        # A single proper rotation must carry ALL authored directions, including hips.
        u, _, vt = np.linalg.svd(desired.T @ actual)
        common = u @ vt
        np.testing.assert_allclose(np.linalg.det(common), 1, atol=2e-12)
        np.testing.assert_allclose(desired @ common, actual, atol=2e-12)
        naive = self.body_axes(source) @ self.body_axes(target).T
        self.assertGreater(np.max(np.abs(desired @ naive.T - actual)), .01)
        motion = retarget_motion(result, target, PARENTS, NAMES, result[None])
        np.testing.assert_allclose(motion["frame_joints"][0], target, atol=2e-12)
        np.testing.assert_allclose(motion["rotations"][0], np.tile(np.eye(3), (25, 1, 1)), atol=2e-12)
        for before, after in zip(originals, (source, target)):
            np.testing.assert_array_equal(before, after)

    def test_identity_and_unordered_namespaced_tree(self):
        source = fixture(True)
        np.testing.assert_allclose(corresponding_source_rest(source, source, PARENTS, NAMES),
                                   source, atol=2e-12)
        target = fixture()
        expected = corresponding_source_rest(source, target, PARENTS, NAMES)
        permutation = np.random.default_rng(17).permutation(25)
        inverse = np.argsort(permutation)
        parents = [-1 if PARENTS[j] is None else int(inverse[PARENTS[j]]) for j in permutation]
        names = ["mixamorig:" + NAMES[j] for j in permutation]
        actual = corresponding_source_rest(source[permutation], target[permutation], parents, names)
        np.testing.assert_allclose(actual[inverse], expected, atol=2e-12)

    def test_invalid_arrays_and_degenerate_frames(self):
        good = fixture(True)
        for argument in (0, 1):
            for bad, message in ((good[:-1], "shape"), (np.full_like(good, np.nan), "finite"),
                                 (np.full_like(good, np.inf), "finite")):
                args = [good, good]
                args[argument] = bad
                with self.subTest(argument=argument, message=message):
                    with self.assertRaisesRegex(ValueError, message):
                        corresponding_source_rest(*args, PARENTS, NAMES)
            for joint, parent, message in ((9, 8, "link 9"), (15, 20, "pelvis axis")):
                bad = good.copy()
                bad[joint] = bad[parent]
                args = [good, good]
                args[argument] = bad
                with self.assertRaisesRegex(ValueError, message):
                    corresponding_source_rest(*args, PARENTS, NAMES)
        bad = good.copy()
        bad[1] = bad[0] + (bad[15] - bad[20])
        with self.assertRaisesRegex(ValueError, "spine axis"):
            corresponding_source_rest(good, bad, PARENTS, NAMES)
        # Valid target axes can collapse after imposing the source's equal hip lengths.
        target = good.copy()
        target[15] = target[0] + [.1, -.1, 0]
        target[20] = target[0] + [.2, -.2, 0]
        source = good.copy()
        source[15] = source[0] + [.2, 0, 0]
        source[20] = source[0] + [-.2, 0, 0]
        with self.assertRaisesRegex(ValueError, "pelvis axis"):
            corresponding_source_rest(source, target, PARENTS, NAMES)

    def test_invalid_names_and_hierarchy(self):
        rest = fixture(True)
        for names, message in ((NAMES[:-1], "unique"), (["Hips"] * 25, "unique"),
                               (["Other"] + NAMES[1:], "missing body-frame")):
            with self.assertRaisesRegex(ValueError, message):
                corresponding_source_rest(rest, rest, PARENTS, names)
        for changes, message in (({9: 25}, "invalid parent"), ({9: 9}, "invalid parent"),
                                 ({9: True}, "invalid parent"), ({9: .5}, "invalid parent"),
                                 ({9: None}, "single root"), ({9: 10, 10: 9}, "cycles"),
                                 ({15: 1}, "direct children")):
            parents = list(PARENTS)
            for joint, parent in changes.items():
                parents[joint] = parent
            with self.assertRaisesRegex(ValueError, message):
                corresponding_source_rest(rest, rest, parents, NAMES)


class OutgoingSkinTests(unittest.TestCase):
    def test_elbow_90_degrees_drives_forearm_weighted_vertices_and_normals(self):
        source = fixture(True)
        yaw = rotation([0, 1, 0], np.deg2rad(46))
        target = source @ yaw.T + [2, .4, -1]
        elbow, wrist = NAMES.index("LeftForeArm"), NAMES.index("LeftHand")
        bend = rotation([0, 0, 1], np.pi / 2)
        frame = source.copy()
        frame[wrist] = source[elbow] + bend @ (source[wrist] - source[elbow])
        incoming = retarget_motion(source, target, PARENTS, NAMES, np.stack((source, frame)))
        original_rotations = incoming["rotations"].copy()
        skin = outgoing_skin_transforms(incoming, target, PARENTS, NAMES)
        expected_bend = yaw @ bend @ yaw.T
        # 100% LeftForeArm weights on elbow, midpoint, wrist and a surface vertex.
        vertices = np.stack((target[elbow], (target[elbow] + target[wrist]) / 2,
                             target[wrist], target[wrist] + yaw @ [0, .04, 0]))
        posed = vertices @ skin["rotations"][1, elbow].T + skin["offsets"][1, elbow]
        expected = (vertices - target[elbow]) @ expected_bend.T + target[elbow]
        np.testing.assert_allclose(posed, expected, atol=2e-12)
        np.testing.assert_allclose(posed[2], incoming["frame_joints"][1, wrist], atol=2e-12)
        normal = yaw @ np.array([0., 1., 0.])
        np.testing.assert_allclose(skin["rotations"][1, elbow] @ normal,
                                   expected_bend @ normal, atol=2e-12)
        wrong_wrist = incoming["rotations"][1, elbow] @ target[wrist] + incoming["offsets"][1, elbow]
        self.assertGreater(np.linalg.norm(wrong_wrist - posed[2]), .3)
        np.testing.assert_array_equal(incoming["rotations"], original_rotations)
        self.assertIs(skin["frame_joints"], incoming["frame_joints"])
        np.testing.assert_allclose(skin["rotations"][0], np.tile(np.eye(3), (25, 1, 1)), atol=2e-12)
        np.testing.assert_allclose(skin["offsets"][0], 0, atol=2e-12)

    def test_named_branches_leaves_and_anchor_offsets(self):
        source = fixture(True)
        frame = (source - source[0]) @ rotation([1, 2, 3], .6).T + source[0] + [.2, .1, .3]
        incoming = retarget_motion(source, source, PARENTS, NAMES, frame[None])
        names = ["mixamorig:" + name for name in NAMES]
        skin = outgoing_skin_transforms(incoming, source, PARENTS, names)
        expected_map = np.array([0, 2, 3, 4, 5, 6, 6, 8, 9, 10, 10, 12, 13, 14, 14,
                                 16, 17, 18, 19, 19, 21, 22, 23, 24, 24])
        np.testing.assert_array_equal(skin["skin_rotation_sources"], expected_map)
        np.testing.assert_array_equal(skin["rotations"], incoming["rotations"][:, expected_map])
        np.testing.assert_allclose(np.einsum("fjab,jb->fja", skin["rotations"], source)
                                   + skin["offsets"], incoming["frame_joints"], atol=2e-12)
        self.assertIs(skin["source_to_target_rotation"], incoming["source_to_target_rotation"])
        with self.assertRaisesRegex(ValueError, "already"):
            outgoing_skin_transforms(skin, source, PARENTS, names)

    def test_unordered_tree_and_empty_clip(self):
        source = fixture(True)
        permutation = np.random.default_rng(5).permutation(25)
        inverse = np.argsort(permutation)
        parents = [-1 if PARENTS[j] is None else int(inverse[PARENTS[j]]) for j in permutation]
        names = [NAMES[j] for j in permutation]
        rest = source[permutation]
        incoming = retarget_motion(rest, rest, parents, names, np.empty((0, 25, 3)))
        skin = outgoing_skin_transforms(incoming, rest, parents, names)
        self.assertEqual(skin["rotations"].shape, (0, 25, 3, 3))
        self.assertEqual(skin["offsets"].shape, (0, 25, 3))
        for owner, driver in (("Hips", "Hips"), ("Spine2", "Neck"), ("LeftForeArm", "LeftHand")):
            self.assertEqual(skin["skin_rotation_sources"][names.index(owner)], names.index(driver))

    def test_canonical_source_rest_replays_idle_instead_of_spread_arms(self):
        from owned_rerig.tpose import tpose_joint_track

        idle = fixture()
        canonical = tpose_joint_track(rest=idle, parents=PARENTS, joint_names=NAMES)["joints"]
        yaw = rotation([0, 1, 0], np.deg2rad(46))
        target = 1.4 * canonical @ yaw.T + [2, .4, -1]
        motion = retarget_motion(canonical, target, PARENTS, NAMES, idle[None])
        np.testing.assert_allclose(motion["frame_joints"][0],
                                   1.4 * idle @ yaw.T + [2, .4, -1], atol=2e-12)
        self.assertGreater(np.linalg.norm(motion["frame_joints"][0, 10] - target[10]), .3)


if __name__ == "__main__":
    unittest.main()
