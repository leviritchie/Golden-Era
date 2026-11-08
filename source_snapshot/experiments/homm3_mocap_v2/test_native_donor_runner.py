"""Fail-closed input identity and shared framing checks for donor diagnostics."""
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parent))
from run_native_donor_capture_comparison import validate_capture, frozen_camera, SIZE
from shared_camera import project_view


class NativeRunnerTests(unittest.TestCase):
    def fixture(self):
        skeleton=dict(jointNames=['root','tip'], parents=np.array([-1,0]),
            offsets=np.array([[0.,0.,0.],[1.,0.,0.]]))
        raw=dict(joint_names=np.array(skeleton['jointNames']),
            parents=skeleton['parents'].copy(), offsets=skeleton['offsets'].copy(),
            pred_position=np.arange(18.).reshape(3,2,3))
        return skeleton, raw, dict(sourceIndices=[1,2],frames=['one','two'])

    def test_exact_authored_indices(self):
        skeleton,raw,row=self.fixture()
        np.testing.assert_array_equal(validate_capture(raw,row,skeleton),raw['pred_position'][[1,2]])

    def test_identity_and_indices_rejected(self):
        for field, value in (('joint_names',np.array(['tip','root'])),
                ('parents',np.array([-1,-1])),('offsets',np.zeros((2,3)))):
            skeleton,raw,row=self.fixture()
            raw[field]=value
            with self.assertRaises(ValueError): validate_capture(raw,row,skeleton)
        for indices in ([1,1],[-1,0],[1,3],[1.2,2.],[]):
            skeleton,raw,row=self.fixture()
            row['sourceIndices']=indices
            with self.assertRaises(ValueError): validate_capture(raw,row,skeleton)

    def test_density_cannot_clip_camera(self):
        points=np.concatenate((np.zeros((10000,3)),np.array([[100.,50.,-30.]])))
        camera=frozen_camera([points])
        self.assertFalse(camera['perPanelAutofit'])
        for view in ('front','side'):
            xy=project_view(points,camera,view)
            self.assertGreaterEqual(xy.min(),0.)
            self.assertLessEqual(xy.max(),SIZE)


if __name__=='__main__': unittest.main()
