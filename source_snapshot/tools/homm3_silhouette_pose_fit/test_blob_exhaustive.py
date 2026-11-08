"""Blob-attributed exhaustive search: chain split, proximal skip, grid bound."""
from __future__ import annotations

import unittest

from blob_exhaustive import (
    blob_exhaustive_chain,
    blob_grid_candidate_count,
    require_blob_grid_fits,
    split_blob_exhaustive_search,
)
from gpu_depth_silhouette_solver import DepthSilhouetteConfig, _inclusive_grid


class BlobExhaustiveChainTests(unittest.TestCase):
    def test_keeps_distal_limb_and_drops_spine(self) -> None:
        # 0 root, 1 spine, 2 shoulder, 3 elbow, 4 wrist. Depths match index.
        parents = [None, 0, 1, 2, 3]
        depths = [0, 1, 2, 3, 4]
        chain = blob_exhaustive_chain(
            4,
            parents,
            depths,
            max_joints=4,
            min_bone_depth=3,
        )
        self.assertEqual(chain, (4, 3))

    def test_rejects_proximal_assigned_bone(self) -> None:
        parents = [None, 0, 1]
        depths = [0, 1, 2]
        with self.assertRaisesRegex(ValueError, "proximal"):
            blob_exhaustive_chain(
                1,
                parents,
                depths,
                max_joints=3,
                min_bone_depth=3,
            )

    def test_max_joints_truncates_before_proximal_filter(self) -> None:
        parents = [None, 0, 1, 2, 3]
        depths = [0, 1, 2, 3, 4]
        chain = blob_exhaustive_chain(
            4,
            parents,
            depths,
            max_joints=1,
            min_bone_depth=3,
        )
        self.assertEqual(chain, (4,))


class BlobExhaustiveSplitTests(unittest.TestCase):
    def test_block_of_two_uses_parent_then_child_cartesian(self) -> None:
        cartesian, remaining = split_blob_exhaustive_search((4, 3, 2), block_size=2)
        self.assertEqual(cartesian, (3, 4))
        self.assertEqual(remaining, (2,))

    def test_single_bone_stays_one_d(self) -> None:
        cartesian, remaining = split_blob_exhaustive_search((4,), block_size=2)
        self.assertEqual(cartesian, (4,))
        self.assertEqual(remaining, ())

    def test_block_of_three_reverses_whole_distal_set(self) -> None:
        cartesian, remaining = split_blob_exhaustive_search((6, 5, 4), block_size=3)
        self.assertEqual(cartesian, (4, 5, 6))
        self.assertEqual(remaining, ())


class BlobExhaustiveGridTests(unittest.TestCase):
    def test_product_and_fail_closed_overflow(self) -> None:
        self.assertEqual(blob_grid_candidate_count(2, 7), 49)
        self.assertEqual(require_blob_grid_fits(bone_count=2, angle_count=7, max_candidates=49), 49)
        with self.assertRaisesRegex(RuntimeError, "exceeds max_candidates"):
            require_blob_grid_fits(bone_count=3, angle_count=21, max_candidates=1024)

    def test_notebook_coarse_step_fits_two_bone_block(self) -> None:
        angles = _inclusive_grid(-150.0, 150.0, 60.0)
        count = require_blob_grid_fits(
            bone_count=2,
            angle_count=int(len(angles)),
            max_candidates=1024,
        )
        self.assertLessEqual(count, 1024)


class BlobExhaustiveConfigTests(unittest.TestCase):
    def test_enabled_and_disabled_both_validate(self) -> None:
        DepthSilhouetteConfig().validate()
        self.assertTrue(bool(DepthSilhouetteConfig().blob_exhaustive_enabled))
        DepthSilhouetteConfig(blob_exhaustive_enabled=False).validate()
        DepthSilhouetteConfig(blob_exhaustive_enabled=True).validate()

    def test_block_size_and_pairs_fail_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "blob_exhaustive_block_size"):
            DepthSilhouetteConfig(blob_exhaustive_enabled=True, blob_exhaustive_block_size=0).validate()
        with self.assertRaisesRegex(ValueError, "blob_exhaustive_max_pairs"):
            DepthSilhouetteConfig(blob_exhaustive_enabled=True, blob_exhaustive_max_pairs=0).validate()
        with self.assertRaisesRegex(ValueError, "blob_exhaustive_min_bone_depth"):
            DepthSilhouetteConfig(blob_exhaustive_enabled=True, blob_exhaustive_min_bone_depth=-1).validate()


if __name__ == "__main__":
    unittest.main()
