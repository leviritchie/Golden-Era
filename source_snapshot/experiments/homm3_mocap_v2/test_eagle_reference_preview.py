"""Reference actor orientation must not be removed as a coordinate correction."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parent))
from preview_eagle_reference_comparison import reference_conversion
from donor_eagle import quat_wxyz_to_matrix
from mesh_preview import fk_world_matrices


class ReferencePreviewTests(unittest.TestCase):
    def test_reference_yaw_is_pose_not_coordinate_basis(self):
        parents=np.array([-1,0,0,0])
        offsets=np.array([[0.,.2,.1],[1.,0.,0.],[0.,1.,0.],[0.,0.,1.]])
        for yaw in (0.,.3,np.pi/2):
            quaternions=np.zeros((1,4,4)); quaternions[:,:,0]=1.
            quaternions[0,0]=[np.cos(yaw/2),0.,np.sin(yaw/2),0.]
            positions=offsets[None].copy()
            world=fk_world_matrices(local_rotation=quat_wxyz_to_matrix(quaternions)[0],
                local_translation=offsets,parents=parents,root_world=offsets[0])
            package=dict(parents=parents,offsets=offsets,globalScale=.4,
                posePosition=world[None,:,:3,3]/2.,
                anim=SimpleNamespace(rotations=quaternions,positions=positions))
            conversion=reference_conversion(package)
            self.assertAlmostEqual(conversion['scale'],.8,places=10)
            np.testing.assert_allclose(conversion['rotation'],np.eye(3),atol=1e-10)


if __name__=='__main__': unittest.main()
