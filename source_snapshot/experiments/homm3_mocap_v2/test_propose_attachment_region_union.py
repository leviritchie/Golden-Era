import sys
from pathlib import Path
import unittest
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from propose_attachment_region_union import _snapshot_recipe, union_face_region, sha256_file


class AttachmentRegionUnionTests(unittest.TestCase):
    def setUp(self):
        self.triangles = np.array([[0, 1, 2], [2, 3, 0], [4, 5, 6], [0, 4, 6]], dtype=np.int64)
        self.labels = np.array(["body", "weapon", "weapon", "body", "weapon", "weapon", "weapon"])

    def test_all_corners_only_and_existing_retained(self):
        result = union_face_region(self.triangles, self.labels, np.array([0], dtype=np.int64), "weapon")
        self.assertEqual(result["regionFaceIds"].tolist(), [2])
        self.assertEqual(result["faceIds"].tolist(), [0, 2])

    def test_exact_noop_and_inputs_unchanged(self):
        tri, labels = self.triangles.copy(), self.labels.copy()
        result = union_face_region(tri, labels, np.array([0, 2], dtype=np.int64), "weapon")
        self.assertEqual(result["addedFaceIds"].tolist(), [])
        np.testing.assert_array_equal(tri, self.triangles)
        np.testing.assert_array_equal(labels, self.labels)

    def test_invalid_ids_and_labels_fail(self):
        with self.assertRaises(ValueError): union_face_region(self.triangles, self.labels, [99], "weapon")
        with self.assertRaises(ValueError): union_face_region(self.triangles, self.labels, [0, 0], "weapon")
        with self.assertRaises(ValueError): union_face_region(self.triangles, self.labels, [0], "")
        with self.assertRaises(ValueError): union_face_region(self.triangles, np.zeros((7, 1)), [0], "weapon")

    def test_recipe_snapshot_wins_over_historical_source_path(self):
        root = Path("artifacts") / "_region_union_recipe_test"
        root.mkdir(parents=True, exist_ok=True)
        try:
            snapshot = root / "recipe.json"
            snapshot.write_text('{"schema":"attachment-repair-recipe-v1","asset":"h3_test"}\n', encoding="utf-8")
            repair = {"recipePath": str(snapshot), "recipeSha256": sha256_file(snapshot),
                      "sourceRecipePath": str(root / "missing-or-drifted-source.json")}
            path, recipe = _snapshot_recipe(repair)
            self.assertEqual(path, snapshot.resolve())
            self.assertEqual(recipe["asset"], "h3_test")
        finally:
            if root.exists():
                import shutil
                shutil.rmtree(root)


if __name__ == "__main__": unittest.main()
