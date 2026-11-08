"""The canonical T-pose rule, its measurement, and what each refuses.

Pure-array rule: no artifacts, no capture, no GLB.  The synthetic reference is the 25-joint Mixamo
topology posed as a relaxed idle (arms hanging beside the chest), so the T-pose has to do real work.
"""
from __future__ import annotations

import unittest

import numpy as np

from owned_rerig.tpose import (
    CANONICAL_T_POSE,
    TPOSE_SCHEMA,
    character_frame,
    edge_stretch,
    rigid_weights,
    short_name,
    stretch_regions,
    tpose_joint_track,
)


def synthetic_reference() -> tuple[np.ndarray, list[int | None], list[str]]:
    """A 25-joint Mixamo biped standing with its arms down, plus the expected parent table."""
    rest = {
        "Hips": (0.00, 1.00, 0.00),
        "Spine": (0.00, 1.10, 0.00),
        "Spine1": (0.00, 1.20, 0.00),
        "Spine2": (0.00, 1.30, 0.00),
        "Neck": (0.00, 1.40, 0.00),
        "Head": (0.00, 1.50, 0.00),
        "HeadTop_End": (0.00, 1.60, 0.00),
        "LeftShoulder": (0.06, 1.35, 0.00),
        "LeftArm": (0.15, 1.28, 0.00),
        "LeftForeArm": (0.17, 1.08, 0.00),
        "LeftHand": (0.18, 0.88, 0.00),
        "RightShoulder": (-0.06, 1.35, 0.00),
        "RightArm": (-0.15, 1.28, 0.00),
        "RightForeArm": (-0.17, 1.08, 0.00),
        "RightHand": (-0.18, 0.88, 0.00),
        "LeftUpLeg": (0.08, 0.95, 0.00),
        "LeftLeg": (0.08, 0.55, 0.00),
        "LeftFoot": (0.08, 0.15, 0.00),
        "LeftToeBase": (0.08, 0.05, 0.12),
        "LeftToe_End": (0.08, 0.05, 0.24),
        "RightUpLeg": (-0.08, 0.95, 0.00),
        "RightLeg": (-0.08, 0.55, 0.00),
        "RightFoot": (-0.08, 0.15, 0.00),
        "RightToeBase": (-0.08, 0.05, 0.12),
        "RightToe_End": (-0.08, 0.05, 0.24),
    }
    parents: list[int | None] = [
        None, 0, 1, 2, 3, 4, 5, 3, 7, 8, 9, 3, 11, 12, 13, 0, 15, 16, 17, 18, 0, 20, 21, 22, 23,
    ]
    names = [f"mixamorig:{name}" for name in rest]
    if tuple(CANONICAL_T_POSE) != tuple(rest):
        raise AssertionError("the synthetic reference and the canonical table describe different joints")
    return np.array([rest[name] for name in rest], dtype=np.float64), parents, names


def index_of(names: list[str]) -> dict[str, int]:
    return {short_name(name): position for position, name in enumerate(names)}


class CharacterFrameTest(unittest.TestCase):
    def test_axes_follow_the_body_not_the_mesh_frame(self) -> None:
        rest, parents, names = synthetic_reference()
        frame = character_frame(rest=rest, parents=parents, joint_names=names)
        # The synthetic character faces +z with its left toward +x, so both must be recovered from
        # the hip axis and the ankle-to-toe direction rather than from the coordinate axes.
        self.assertGreater(float(frame["side"] @ np.array([1.0, 0.0, 0.0])), 0.95)
        self.assertGreater(float(frame["forward"] @ np.array([0.0, 0.0, 1.0])), 0.95)
        self.assertAlmostEqual(float(frame["up"] @ np.array([0.0, 1.0, 0.0])), 1.0, places=12)
        self.assertAlmostEqual(frame["toeAlignmentCos"], 1.0, places=6)

    def test_refuses_a_reference_whose_spine_is_not_upright(self) -> None:
        rest, parents, names = synthetic_reference()
        index = index_of(names)
        rest = rest.copy()
        rest[index["Spine"]] = rest[index["Hips"]] + np.array([0.0, 0.05, 0.20])
        with self.assertRaisesRegex(ValueError, "spine does not point along"):
            character_frame(rest=rest, parents=parents, joint_names=names)

    def test_refuses_a_topology_without_the_biped_joints(self) -> None:
        rest, parents, names = synthetic_reference()
        with self.assertRaisesRegex(ValueError, "the reference has no"):
            character_frame(rest=rest[:6], parents=parents[:6], joint_names=names[:6])


class TPoseTrackTest(unittest.TestCase):
    def setUp(self) -> None:
        self.rest, self.parents, self.names = synthetic_reference()
        self.index = index_of(self.names)
        self.track = tpose_joint_track(
            rest=self.rest, parents=self.parents, joint_names=self.names
        )

    def test_bone_lengths_are_preserved_exactly(self) -> None:
        self.assertLess(self.track["boneLengthDrift"], 1e-12)
        self.assertEqual(self.track["schema"], TPOSE_SCHEMA)

    def test_root_is_not_moved(self) -> None:
        np.testing.assert_allclose(
            self.track["joints"][self.index["Hips"]], self.rest[self.index["Hips"]], atol=1e-12
        )

    def test_arms_are_horizontal_and_reach_forward_of_the_shoulder(self) -> None:
        joints = self.track["joints"]
        for side in ("Left", "Right"):
            hand = joints[self.index[f"{side}Hand"]]
            arm = joints[self.index[f"{side}Arm"]]
            span = hand - arm
            self.assertLess(abs(float(span[1])), 1e-9, f"{side} arm is not horizontal")
            self.assertLess(abs(float(span[2])), 1e-9, f"{side} arm is not lateral")
            self.assertGreater(abs(float(span[0])), 0.3)
        self.assertGreater(joints[self.index["LeftHand"]][0], joints[self.index["RightHand"]][0])

    def test_legs_hang_straight_down_from_the_hip_offsets(self) -> None:
        joints = self.track["joints"]
        for side in ("Left", "Right"):
            thigh = joints[self.index[f"{side}Leg"]] - joints[self.index[f"{side}UpLeg"]]
            shin = joints[self.index[f"{side}Foot"]] - joints[self.index[f"{side}Leg"]]
            for span in (thigh, shin):
                self.assertLess(max(abs(float(span[0])), abs(float(span[2]))), 1e-9)
                self.assertLess(float(span[1]), 0.0)
        # The pelvis offset is lateral, so a T-pose keeps the hip joints level with each other.
        self.assertAlmostEqual(
            float(joints[self.index["LeftUpLeg"]][1]), float(joints[self.index["RightUpLeg"]][1]), places=12
        )

    def test_spine_and_head_are_upright(self) -> None:
        joints = self.track["joints"]
        for joint in ("Spine", "Spine1", "Spine2", "Neck", "Head", "HeadTop_End"):
            offset = joints[self.index[joint]] - joints[self.index["Hips"]]
            self.assertGreater(float(offset[1]), 0.0)
            self.assertLess(max(abs(float(offset[0])), abs(float(offset[2]))), 1e-9)

    def test_the_pose_actually_rotates_the_arms(self) -> None:
        rotations = {short_name(row["joint"]): row["restAngleDeg"] for row in self.track["boneRotations"]}
        self.assertGreater(rotations["LeftForeArm"], 80.0)
        self.assertGreater(rotations["RightForeArm"], 80.0)

    def test_refuses_a_joint_with_no_canonical_direction(self) -> None:
        names = list(self.names)
        names[7] = "mixamorig:LeftTentacle"
        with self.assertRaisesRegex(ValueError, "no canonical T-pose direction"):
            tpose_joint_track(rest=self.rest, parents=self.parents, joint_names=names)

    def test_refuses_a_root_that_the_table_gives_a_direction(self) -> None:
        names = list(self.names)
        names[0] = "mixamorig:Spine"
        with self.assertRaisesRegex(ValueError, "is the root but the canonical table"):
            tpose_joint_track(
                rest=self.rest,
                parents=self.parents,
                joint_names=names,
                frame=self.track["frame"],
            )

    def test_refuses_a_table_that_marks_a_child_as_the_root(self) -> None:
        names = list(self.names)
        names[7] = "mixamorig:Hips"
        with self.assertRaisesRegex(ValueError, "has a parent but the canonical table"):
            tpose_joint_track(
                rest=self.rest,
                parents=self.parents,
                joint_names=names,
                frame=self.track["frame"],
            )


class EdgeStretchTest(unittest.TestCase):
    def setUp(self) -> None:
        self.positions = np.array(
            [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [1.0, 1.0, 0.0], [0.0, 1.0, 0.0]], dtype=np.float64
        )
        self.indices = np.array([[0, 1, 2], [0, 2, 3]], dtype=np.int64)

    def test_a_rigid_motion_stretches_nothing(self) -> None:
        angle = 0.7
        rotation = np.array(
            [
                [np.cos(angle), -np.sin(angle), 0.0],
                [np.sin(angle), np.cos(angle), 0.0],
                [0.0, 0.0, 1.0],
            ]
        )
        rigid = self.positions @ rotation.T + np.array([3.0, -2.0, 0.5])
        block = edge_stretch(positions=self.positions, indices=self.indices, deformed=rigid)
        self.assertAlmostEqual(block["max"], 0.0, places=12)
        self.assertAlmostEqual(block["maxEdgeGrowth"], 0.0, places=12)
        self.assertEqual(block["edgesPastReviewLimit"], 0)

    def test_doubling_one_edge_is_past_the_review_limit(self) -> None:
        # The review limit is a strict inequality, so exactly 2x the rest length is the boundary and
        # is *not* counted: the audit's own convention, kept so the two are readable together.
        doubled = self.positions.copy()
        doubled[1] = np.array([2.0, 0.0, 0.0])
        boundary = edge_stretch(positions=self.positions, indices=self.indices, deformed=doubled)
        self.assertAlmostEqual(boundary["max"], 1.0, places=9)
        self.assertEqual(boundary["edgesPastReviewLimit"], 0)

        tripled = self.positions.copy()
        tripled[1] = np.array([3.0, 0.0, 0.0])
        block = edge_stretch(positions=self.positions, indices=self.indices, deformed=tripled)
        self.assertAlmostEqual(block["max"], 2.0, places=9)
        # Both the doubled edge and the triangle's other edge leaving the moved vertex are past it.
        self.assertEqual(block["edgesPastReviewLimit"], 2)
        self.assertAlmostEqual(block["maxEdgeGrowth"], 2.0, places=9)
        self.assertEqual(block["edges"], 5)
        self.assertEqual(block["edgeKeying"], "undirected_unique")

    def test_absolute_growth_is_reported_against_a_height(self) -> None:
        deformed = self.positions.copy()
        deformed[2] = np.array([1.0, 3.0, 0.0])
        block = edge_stretch(
            positions=self.positions, indices=self.indices, deformed=deformed, subject_height=2.0
        )
        self.assertAlmostEqual(block["maxEdgeGrowth"], 2.0, places=9)
        self.assertAlmostEqual(block["maxEdgeGrowthFractionOfHeight"], 1.0, places=9)
        self.assertGreater(block["edgesGrowingPastFivePercentOfHeight"], 0)

    def test_weight_jump_fields_need_the_bind_and_are_otherwise_none(self) -> None:
        block = edge_stretch(positions=self.positions, indices=self.indices, deformed=self.positions)
        self.assertIsNone(block["edgesWithWeightJumpOverHalf"])
        self.assertIsNone(block["meanStretchAtWeightJump"])
        joints = np.zeros((4, 4), dtype=np.int64)
        joints[:2, 0] = 0
        joints[2:, 0] = 1
        weights = np.zeros((4, 4), dtype=np.float64)
        weights[:, 0] = 1.0
        deformed = self.positions.copy()
        deformed[2] = np.array([1.0, 2.0, 0.0])
        block = edge_stretch(
            positions=self.positions,
            indices=self.indices,
            deformed=deformed,
            joints=joints,
            weights=weights,
        )
        self.assertEqual(block["edgesWithWeightJumpOverHalf"], 3)
        self.assertGreater(block["meanStretchAtWeightJump"], block["meanStretchElsewhere"])


class RigidWeightsTest(unittest.TestCase):
    def test_every_duplicate_position_gets_one_bone(self) -> None:
        positions = np.array(
            [[0.0, 0.0, 0.0], [0.0, 0.0, 0.0], [1.0, 0.0, 0.0]], dtype=np.float64
        )
        joints = np.array([[0], [1], [1]], dtype=np.int64)
        weights = np.array([[1.0], [0.4], [1.0]], dtype=np.float64)
        out_joints, out_weights = rigid_weights(
            positions=positions, joints=joints, weights=weights
        )
        self.assertEqual(out_joints.shape, (3, 1))
        self.assertEqual(int(out_joints[0, 0]), int(out_joints[1, 0]))
        np.testing.assert_allclose(out_weights, 1.0)

    def test_the_chosen_bone_is_the_node_wide_argmax(self) -> None:
        positions = np.array(
            [[0.0, 0.0, 0.0], [0.0, 0.0, 0.0], [1.0, 0.0, 0.0]], dtype=np.float64
        )
        joints = np.array([[0], [1], [1]], dtype=np.int64)
        weights = np.array([[0.9], [1.0], [1.0]], dtype=np.float64)
        out_joints, _ = rigid_weights(positions=positions, joints=joints, weights=weights)
        self.assertEqual(int(out_joints[0, 0]), 1)


class StretchRegionsTest(unittest.TestCase):
    def test_a_flung_cluster_is_grouped_and_its_driver_named(self) -> None:
        # A 4x1 strip of unit squares; the two right-hand vertices are thrown clear of it.
        columns = 5
        positions = np.array(
            [[float(x), float(y), 0.0] for y in (0, 1) for x in range(columns)], dtype=np.float64
        )
        triangles = []
        for x in range(columns - 1):
            lower = x
            upper = columns + x
            triangles.append([lower, lower + 1, upper + 1])
            triangles.append([lower, upper + 1, upper])
        indices = np.array(triangles, dtype=np.int64)
        deformed = positions.copy()
        flung = positions[:, 0] >= 3.0
        deformed[flung] = positions[flung] + np.array([0.0, 4.0, 0.0])
        joints = np.zeros((len(positions), 4), dtype=np.int64)
        weights = np.zeros((len(positions), 4), dtype=np.float64)
        weights[:, 0] = 1.0
        joints[flung, 0] = 1
        joints[flung, 1] = 1
        weights[flung, 0] = 0.0
        weights[flung, 1] = 1.0
        names = ["hinge", "toss"]
        block = stretch_regions(
            positions=positions,
            indices=indices,
            deformed=deformed,
            joints=joints,
            weights=weights,
            bone_names=names,
            limit=1.0,
            radius=1.5,
            min_vertices=2,
        )
        self.assertEqual(block["schema"], "stretch_regions.v1")
        self.assertEqual(block["regionCount"], 1)
        region = block["regions"][0]
        # The two moved vertices and the two their edges drag out of place form one group, and the
        # reported place is the group's own rest position rather than a per-vertex array read by id.
        self.assertEqual(region["nodes"], 4)
        self.assertIn("toss", region["dominantBones"])
        self.assertGreater(region["maxEdgeGrowth"], 1.0)
        self.assertAlmostEqual(float(region["centroid"][0]), 2.5, places=9)
        self.assertAlmostEqual(float(region["centroid"][1]), 0.5, places=9)


if __name__ == "__main__":
    unittest.main()
