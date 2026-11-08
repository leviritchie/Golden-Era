import unittest
import numpy as np
from scipy.spatial.transform import Rotation
from screen_attachment_direction import correct


class ScreenAttachmentDirectionTests(unittest.TestCase):
    def test_tilted_camera_corrects_leaf_and_preserves_other_motion(self):
        local = np.repeat(np.eye(3)[None, None], 3, axis=0).repeat(2, axis=1)
        worlds = np.repeat(np.eye(4)[None, None], 3, axis=0).repeat(2, axis=1)
        worlds[:, 1, 0, 3] = 1
        camera = {"right": [1, 0, 0], "down": [0, .8, .6]}
        local[:,0] = Rotation.from_euler('x', np.array([0,20,40])[:,None], degrees=True).as_matrix()
        worlds[:,0,:3,:3] = local[:,0]
        worlds[:,1,:3,:3] = local[:,0]
        source = np.array([[1,0],[0,1],[0,-1]])
        fixed, fixed_world, report = correct(local, worlds, [-1, 0], 1, [1, 0, 0], camera, source)
        axis = fixed_world[:,1,:3,0]
        actual = axis @ np.asarray([camera['right'],camera['down']]).T
        np.testing.assert_allclose(actual, source, atol=1e-10)
        self.assertGreater(np.max(np.abs(fixed[:,1]-local[:,1])), .5)
        np.testing.assert_array_equal(fixed[:,0], local[:,0])
        np.testing.assert_array_equal(fixed_world[:,0], worlds[:,0])
        np.testing.assert_array_equal(fixed_world[0], worlds[0])
        self.assertLess(report['afterAngularErrorDegrees'], 1e-10)
        self.assertTrue(report["anchorUnchanged"])
        self.assertEqual(report["inactiveLocalMax"], 0)
        self.assertTrue(report["translationsUnchanged"])

    def test_rejects_nonleaf_and_degenerate_projection(self):
        local = np.repeat(np.eye(3)[None, None], 1, axis=0).repeat(2, axis=1)
        worlds = np.repeat(np.eye(4)[None, None], 1, axis=0).repeat(2, axis=1)
        camera = {"right": [1, 0, 0], "down": [0, 1, 0]}
        with self.assertRaises(ValueError):
            correct(local, worlds, [-1, 0], 0, [1, 0, 0], camera, [[1, 0]])
        with self.assertRaises(ValueError):
            correct(local, worlds, [-1, 0], 1, [0, 0, 1], camera, [[1, 0]])

    def test_rejects_bound_and_bad_inputs(self):
        local=np.tile(np.eye(3),(2,2,1,1)); world=np.tile(np.eye(4),(2,2,1,1))
        camera={'right':[1,0,0],'down':[0,1,0]}
        args=(local,world,[-1,0],1,[1,0,0],camera,[[1,0],[0,1]])
        with self.assertRaisesRegex(ValueError,'exceeds bound'):
            correct(*args,max_correction_degrees=30)
        for anchor in (True, .5, -1, 2):
            with self.subTest(anchor=anchor), self.assertRaises(ValueError):
                correct(*args,anchor_frame=anchor)
        with self.assertRaises(ValueError):
            correct(local,world,[-1,0],1,[1,0,0],None,[[1,0],[0,1]])
        world[1,1,0,0]=2
        with self.assertRaisesRegex(ValueError,'inconsistent'):
            correct(local,world,[-1,0],1,[1,0,0],camera,[[1,0],[0,1]])


if __name__ == "__main__": unittest.main()
