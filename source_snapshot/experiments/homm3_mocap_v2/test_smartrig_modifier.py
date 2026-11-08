import json
import unittest
from pathlib import Path

import numpy as np

from run_smartrig_modifier import (
    _edge_strain_diagnostics,
    _motion_retention,
    _preview_worlds,
    _segment_regions,
    _split_strain_seams,
    _surface_metrics,
)
from validate_smartrig_modifier_report import validate


class SmartRigModifierHelperTests(unittest.TestCase):
    def test_segment_regions_assigns_vertices_to_bones(self):
        vertices = np.asarray([[0, 0, 0], [0, 0.5, 0], [0, 1, 0], [1, 1, 0]], dtype=float)
        bind = np.repeat(np.eye(4)[None], 3, axis=0)
        bind[:, :3, 3] = [[0, 0, 0], [0, 1, 0], [1, 1, 0]]
        regions = _segment_regions(vertices, bind, np.asarray([-1, 0, 1]), min_vertices=1)
        self.assertEqual(set(regions), {1, 2})
        self.assertEqual(sorted(np.concatenate(list(regions.values())).tolist()), [0, 1, 2, 3])

    def test_motion_retention_reports_no_change(self):
        pose = np.zeros((3, 4, 3), dtype=float)
        pose[:, :, 0] = [[0, 0, 0, 0], [0, 1, 2, 3], [0, 2, 4, 6]]
        report = _motion_retention(pose, pose.copy())
        self.assertEqual(report["p05EnergyRatio"], 1.0)
        self.assertEqual(report["belowFloorFraction"], 0.0)

    def test_surface_metrics_accepts_rigid_translation(self):
        rest = np.asarray([[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype=float)
        posed = np.stack([rest, rest + [2, 3, 4]], axis=0)
        metrics = _surface_metrics(rest, posed, np.asarray([[0, 1, 2]], dtype=np.int64))
        self.assertAlmostEqual(metrics["p95Ratio"], 1.0)
        self.assertEqual(metrics["compressionViolationFraction"], 0.0)

    def test_seam_split_duplicates_faces_without_authored_mask(self):
        vertices = np.asarray([[0, 0, 0], [1, 0, 0], [0, 1, 0], [1, 1, 0]], dtype=float)
        triangles = np.asarray([[0, 1, 2], [1, 0, 3]], dtype=np.int64)
        uvs = vertices[:, :2].copy()
        weights = np.zeros((4, 2), dtype=float)
        weights[[0, 2]] = [1, 0]
        weights[[1, 3]] = [0, 1]
        detector = {"selectedEdges": [{"edge": [0, 1], "p95AbsLogStrain": 1.0,
                                       "maxAbsLogStrain": 1.5, "weightDisagreement": 1.0}]}
        v2, t2, uv2, w2, report = _split_strain_seams(vertices, triangles, uvs, weights, detector, max_cuts=4)
        self.assertEqual(report["cutCount"], 1)
        self.assertEqual(report["duplicatedVertexCount"], 4)
        self.assertEqual(len(v2), len(w2))
        self.assertEqual(len(v2), len(uv2))
        self.assertFalse(any(set(face).issuperset({0, 1}) for face in t2))

    def test_seam_split_skips_conflicting_face_operations(self):
        vertices = np.asarray([[0, 0, 0], [1, 0, 0], [0, 1, 0],
                               [1, 1, 0], [-1, 1, 0]], dtype=float)
        triangles = np.asarray([[0, 1, 2], [1, 0, 3], [2, 1, 4]])
        detector = {"selectedEdges": [
            {"edge": edge, "p95AbsLogStrain": 1.0, "weightDisagreement": 1.0}
            for edge in ([0, 1], [1, 2])
        ]}
        v, t, uv, w, report = _split_strain_seams(
            vertices, triangles, vertices[:, :2], np.ones((5, 1)), detector,
        )
        self.assertEqual(report["cutCount"], 1)
        self.assertEqual(report["duplicatedVertexCount"], 4)
        np.testing.assert_array_equal(t[2], triangles[2])
        np.testing.assert_array_equal(v[t], vertices[triangles])
        np.testing.assert_array_equal(uv[t], vertices[triangles, :2])
        self.assertEqual(len(w), len(v))

    def test_preview_style_marks_move_as_exaggerated_only(self):
        local = np.zeros((3, 2, 3, 3), dtype=float)
        local[:] = np.eye(3)
        local[1, 1] = [[0, -1, 0], [1, 0, 0], [0, 0, 1]]
        local[2, 1] = [[-1, 0, 0], [0, -1, 0], [0, 0, 1]]
        world = np.repeat(np.eye(4)[None, None], 3, axis=0)
        world = np.repeat(world, 2, axis=1)
        skin = {"parents": np.asarray([-1, 0], dtype=np.int64)}
        moved, style = _preview_worlds({"jointWorld": world, "localRotation": local}, skin, "g00_move")
        self.assertEqual(style["gain"], 2.2)
        self.assertEqual(style["mode"], "move")
        self.assertTrue(np.isfinite(moved).all())

    def test_validator_rejects_missing_report(self):
        path = Path("artifacts/homm3_mocap_v2/test_invalid_smartrig_modifier_report.json").resolve()
        try:
            path.write_text(json.dumps({"asset": "h3_archer"}), encoding="utf-8")
            with self.assertRaises(ValueError):
                validate(path)
        finally:
            path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
