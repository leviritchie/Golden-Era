"""Synthetic branched appendage controls, independent of any production unit."""
import unittest
import numpy as np
from tools.homm3_meshy_frame_pose.test_rest_retarget import fixture, rotation, NAMES, PARENTS
from tools.homm3_meshy_frame_pose.owned_rerig.rest_retarget import retarget_motion, outgoing_skin_transforms


class BranchSkinTests(unittest.TestCase):
    def setUp(self):
        self.names=NAMES+['AppendageRoot','AppendageFork','PrimaryRay','SecondaryRay','SecondaryTip']
        self.parents=PARENTS+[3,25,26,26,28]
        self.rest=np.concatenate([fixture(),np.array([[.3,1.5,-.1],[.6,1.8,-.1],[1.,1.7,-.1],[.7,1.4,-.1],[.8,1.1,-.1]])])
        self.mapping={'AppendageFork':'PrimaryRay'}

    def convert(self,motion,mapping=None):
        return outgoing_skin_transforms(motion,self.rest,self.parents,self.names,branch_children=self.mapping if mapping is None else mapping)

    def test_rest_identity(self):
        m=retarget_motion(self.rest,self.rest,self.parents,self.names,self.rest[None])
        result=self.convert(m)
        np.testing.assert_allclose(result['rotations'],np.broadcast_to(np.eye(3),(1,30,3,3)),atol=1e-12)
        np.testing.assert_allclose(result['offsets'],0,atol=1e-12)
        self.assertEqual(result['skin_rotation_sources'][26],27)

    def test_rigid_flight_turn_keeps_every_skin_point(self):
        rot=rotation([0,1,0],.8)
        frame=(self.rest-self.rest[0])@rot.T+self.rest[0]
        m=retarget_motion(self.rest,self.rest,self.parents,self.names,frame[None])
        result=self.convert(m)
        np.testing.assert_allclose(result['rotations'],np.broadcast_to(rot,(1,30,3,3)),atol=1e-12)
        point=self.rest[26]+[.03,.06,.08]
        actual=result['rotations'][0,26]@point+result['offsets'][0,26]
        np.testing.assert_allclose(actual,(point-self.rest[0])@rot.T+self.rest[0],atol=1e-12)

    def test_explicit_primary_ray_anchored_at_fork(self):
        frame=self.rest.copy();rot=rotation([0,0,1],.5)
        frame[27]=(frame[27]-frame[26])@rot.T+frame[26]
        m=retarget_motion(self.rest,self.rest,self.parents,self.names,frame[None]);result=self.convert(m)
        for joint in (26,27):
            np.testing.assert_allclose(result['rotations'][0,26]@self.rest[joint]+result['offsets'][0,26],frame[joint],atol=1e-12)
        np.testing.assert_array_equal(m['frame_joints'],result['frame_joints'])
        self.assertNotIn('skin_rotation_sources',m)
        with self.assertRaises(ValueError):self.convert(result)

    def test_missing_unknown_nonchild_and_builtin_override_refused(self):
        m=retarget_motion(self.rest,self.rest,self.parents,self.names,self.rest[None])
        for mapping in [{},{'missing':'PrimaryRay'},{'AppendageFork':'Head'}, {'AppendageRoot':'AppendageFork'}, {'Spine2':'Neck'}]:
            with self.subTest(mapping=mapping),self.assertRaises(ValueError):self.convert(m,mapping)

    def test_biped_default_unchanged(self):
        rest=fixture();m=retarget_motion(rest,rest,PARENTS,NAMES,rest[None])
        a=outgoing_skin_transforms(m,rest,PARENTS,NAMES)
        b=outgoing_skin_transforms(m,rest,PARENTS,NAMES,branch_children={})
        for key in a:np.testing.assert_array_equal(a[key],b[key])

if __name__=='__main__':unittest.main()
