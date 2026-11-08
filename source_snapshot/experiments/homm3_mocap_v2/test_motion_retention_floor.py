import unittest
import numpy as np
import torch

from experiments.homm3_mocap_v2.motion_retention_floor import RegionMotionFloor


class RegionMotionFloorTests(unittest.TestCase):
    def setUp(self):
        self.regions = np.array(["body", "body", "weapon"])
        self.slices = {"a": (0, 3), "b": (3, 6)}
        self.base = np.zeros((6, 3, 3), dtype=np.float64)
        self.base[:3, 0, 0] = [0, 1, 0]
        self.base[:3, 1, 0] = [0, 1, 0]
        self.base[:3, 2, 1] = [0, 2, 0]
        self.base[3:, :, 2] = 10

    def test_constant_pose_offset_does_not_count_as_motion(self):
        floor = RegionMotionFloor(self.base, self.regions, self.slices)
        shifted = self.base + np.array([4., -2., 7.])
        self.assertEqual(float(floor.loss(shifted)), 0.0)

    def test_two_static_clips_at_different_positions_do_not_fake_motion(self):
        floor = RegionMotionFloor(self.base, self.regions, self.slices)
        self.assertEqual(float(floor.loss(self.base)), 0.0)
        self.assertEqual(floor.report(self.base)["thresholdCount"], 0)

    def test_shrink_half_has_finite_positive_gradient(self):
        floor = RegionMotionFloor(self.base, self.regions, self.slices, fraction=.9)
        current = self.base.copy(); current[:3, 2, 1] *= .5
        tensor = torch.tensor(current, requires_grad=True)
        value = floor.loss(tensor)
        value.backward()
        self.assertGreater(float(value), 0)
        self.assertTrue(torch.isfinite(tensor.grad).all())
        self.assertGreater(float(torch.linalg.vector_norm(tensor.grad)), 0)

    def test_equal_motion_is_zero(self):
        floor = RegionMotionFloor(self.base, self.regions, self.slices)
        self.assertEqual(float(floor.loss(torch.tensor(self.base))), 0.0)

    def test_different_clip_lengths_keep_region_and_time_axes_distinct(self):
        baseline=np.zeros((5,3,3),dtype=float)
        baseline[:2,:2,0]=np.array([0,2])[:,None]
        baseline[:2,2,1]=[0,4]
        baseline[2:,:,0]=9
        floor=RegionMotionFloor(baseline,self.regions,{'short':(0,2),'long':(2,5)})
        np.testing.assert_allclose(floor.baseline_ranges,[[2,4],[0,0]])
        report=floor.report(baseline)
        self.assertEqual(report['observableCount'],2)
        self.assertEqual(sum(row['ignoredBaseline'] for row in report['rows']),2)

    def test_invalid_shapes_labels_and_slices_fail(self):
        with self.assertRaises(ValueError): RegionMotionFloor(self.base[:, :, :2], self.regions, self.slices)
        with self.assertRaises(ValueError): RegionMotionFloor(self.base, np.array(["body", "", "weapon"]), self.slices)
        with self.assertRaises(ValueError): RegionMotionFloor(self.base, self.regions, {"a": (1, 3), "b": (3, 6)})
        with self.assertRaises(ValueError): RegionMotionFloor(self.base, self.regions, {"a": (0, 3)})


if __name__ == "__main__": unittest.main()
