"""Focused diagnostic selection tests; no GPU or rendered assets required."""
import unittest

import numpy as np

from pose_representation_exception import detect_conflicts


class ConflictTests(unittest.TestCase):
    def inputs(self, trials=2):
        return dict(baseline_iou=np.array([0.5, 0.5]),
                    candidate_iou=np.full((trials, 2), 0.6),
                    baseline_stretches=np.ones((2, 3, 2)),
                    candidate_stretches=np.ones((trials, 2, 3, 2)),
                    valid_faces=np.ones(3, dtype=bool),
                    visible_face_error=np.ones((2, 3)),
                    candidate_visible_face_error=np.full((trials, 2, 3), 0.5),
                    visible_face_coverage=np.full((2, 3), 10.0),
                    candidate_visible_face_coverage=np.full((trials, 2, 3), 10.0),
                    triangles=np.array([[0, 1, 2], [2, 3, 4], [5, 6, 7]]))

    def test_healthy(self):
        report = detect_conflicts(**self.inputs())
        self.assertEqual(report["correctionVertexIds"], [])
        self.assertEqual(report["perFrame"][0]["classification"], "no_repeated_conflict_observed")

    def test_one_trial_is_unresolved(self):
        data = self.inputs(1)
        data["candidate_stretches"][:] = 2
        report = detect_conflicts(**data)
        self.assertEqual(report["repeatedConflictFaceIds"], [])
        self.assertEqual(report["perFrame"][0]["classification"], "unresolved_insufficient_trials")

    def test_repeated_same_face_and_topological_components(self):
        data = self.inputs()
        data["candidate_stretches"][:, 0, :2] = 2
        data["candidate_stretches"][:, 1, 2] = 0.4
        report = detect_conflicts(**data)
        self.assertEqual(report["faceComponents"], [[0, 1], [2]])
        self.assertEqual(report["correctionVertexIds"], list(range(8)))
        self.assertEqual(report["perFrame"][0]["conflictFaceIds"], [0, 1])
        self.assertFalse(report["automaticCorrectionAuthorized"])
        self.assertFalse(report["provesRepresentationImpossible"])

    def test_unowned_source_error_does_not_select_geometry(self):
        data = self.inputs()
        data["candidate_stretches"][:] = 2
        data["visible_face_error"][:] = 0
        self.assertEqual(detect_conflicts(**data)["correctionVertexIds"], [])

    def test_trials_must_conflict_on_same_face(self):
        data = self.inputs()
        data["candidate_stretches"][0, :, 0] = 2
        data["candidate_stretches"][1, :, 1] = 2
        self.assertEqual(detect_conflicts(**data)["repeatedConflictFaceIds"], [])

    def test_unrelated_face_image_gain_is_rejected(self):
        data = self.inputs()
        data["candidate_stretches"][:, :, 0] = 2
        data["candidate_visible_face_error"][:, :, 0] = 1
        self.assertEqual(detect_conflicts(**data)["repeatedConflictFaceIds"], [])

    def test_hidden_or_mostly_hidden_face_does_not_vote(self):
        for remaining in (0.0, 4.9):
            with self.subTest(remaining=remaining):
                data = self.inputs()
                data["candidate_stretches"][:, :, 0] = 2
                data["candidate_visible_face_error"][:, :, 0] = 0
                data["candidate_visible_face_coverage"][:, :, 0] = remaining
                report = detect_conflicts(**data)
                self.assertEqual(report["repeatedConflictFaceIds"], [])
                self.assertEqual(report["lostCoverageExcludedFaceIds"], [0])

    def test_retained_coverage_and_mean_error_improvement_votes(self):
        data = self.inputs()
        data["candidate_stretches"][:, :, 0] = 2
        data["candidate_visible_face_coverage"][:, :, 0] = 5.0
        report = detect_conflicts(**data)
        self.assertEqual(report["repeatedConflictFaceIds"], [0])
        self.assertEqual(report["lostCoverageExcludedFaceIds"], [])

    def test_baseline_invisible_face_does_not_vote(self):
        data = self.inputs()
        data["candidate_stretches"][:] = 2
        data["visible_face_coverage"][:] = 0
        self.assertEqual(detect_conflicts(**data)["repeatedConflictFaceIds"], [])

    def test_invalid_faces_and_no_image_gain_are_excluded(self):
        data = self.inputs()
        data["candidate_stretches"][:] = 2
        data["valid_faces"][:] = False
        self.assertEqual(detect_conflicts(**data)["repeatedConflictFaceIds"], [])
        data["valid_faces"][:] = True
        data["candidate_iou"][:] = 0.5
        self.assertEqual(detect_conflicts(**data)["repeatedConflictFaceIds"], [])


if __name__ == "__main__":
    unittest.main()
