import unittest
import sys
from pathlib import Path
import numpy as np
import torch
sys.path.insert(0, str(Path(__file__).resolve().parent))
from topology_weight_field import TopologyWeightField, RepairWeightField


class TopologyWeightFieldTests(unittest.TestCase):
    def setUp(self):
        self.vertices = [[0,0,0],[1,0,0],[0,1,0],[0,0,0]]
        self.triangles = [[0,1,2],[3,1,2]]
        self.weights = [[.7,.3],[.2,.8],[1,0],[.7,.3]]

    def test_welds_share_weights_and_train_step_changes_nonrigid(self):
        field = TopologyWeightField(self.vertices, self.triangles, self.weights, [2])
        torch.testing.assert_close(field.weights()[0], field.weights()[3])
        before = field.weights().detach().clone(); loss = field.penalty() + field.logits[0,0] * .1
        loss.backward(); torch.optim.SGD(field.parameters(), lr=.1).step()
        self.assertFalse(torch.equal(before[0], field.weights()[0]))
        self.assertTrue(field.validate())

    def test_rigid_and_invalid_weld_contracts(self):
        field = TopologyWeightField(self.vertices, self.triangles, self.weights, [2])
        torch.testing.assert_close(field.weights()[2], torch.tensor([1.,0.]))
        with self.assertRaises(ValueError):
            TopologyWeightField(self.vertices, self.triangles, [[.5,.5],[.2,.8],[1,0],[.6,.4]], [])
        with self.assertRaises(ValueError):
            TopologyWeightField(self.vertices, self.triangles, self.weights, [0])

    def test_interleaved_duplicates_preserve_initial_and_rigid_group(self):
        vertices=[[0,0,0],[0,0,0],[1,0,0],[0,1,0],[1,0,0]]
        weights=[[.7,.3],[.7,.3],[.2,.8],[1.,0],[.2,.8]]
        field=TopologyWeightField(vertices,[[0,2,3],[1,4,3]],weights,[3])
        torch.testing.assert_close(field.weights(),torch.tensor(weights))
        loss=field.weights()[2,0]+field.penalty(field.weights())
        loss.backward()
        self.assertTrue(torch.isfinite(field.logits.grad).all())
        torch.optim.SGD(field.parameters(),lr=.5).step()
        self.assertLess(float(field.weights()[2,0].detach()),.2)
        torch.testing.assert_close(field.weights()[2],field.weights()[4],rtol=0,atol=0)
        torch.testing.assert_close(field.weights()[3],torch.tensor([1.,0.]),rtol=0,atol=0)
        self.assertTrue(field.validate())

    def test_repair_ownership_keeps_coincident_body_prop_separate(self):
        v=[[0,0,0],[0,0,0],[1,0,0]]; tri=[[0,1,2]]
        w=[[1.,0,0],[0.,1.,0],[1.,0,0]]; owners=[1,2,1]
        train=np.array([True,True,False], dtype=bool); support=np.array([[1,1,0],[1,1,0],[1,0,0]], dtype=bool)
        field=RepairWeightField(v,tri,w,owners,train,support)
        self.assertEqual(len(field._weld_rows), 3)
        torch.testing.assert_close(field.weights(), torch.tensor(w))
        field.delta[0,1].data.fill_(.2)
        self.assertFalse(torch.equal(field.weights()[0], field.weights()[1]))
        torch.testing.assert_close(field.weights()[2], torch.tensor(w[2]))
        self.assertTrue(field.validate())

    def test_repair_zero_support_can_learn_and_frozen_rows_are_exact(self):
        v=[[0,0,0],[1,0,0]]; tri=[[0,1,1]]
        w=[[1.,0,0],[.5,.5,0]]; owners=[1,1]
        train=np.array([True,False], dtype=bool); support=np.array([[1,1,0],[1,1,0]], dtype=bool)
        field=RepairWeightField(v,tri,w,owners,train,support)
        field.delta.data[0,1]=.5
        loss=field.weights()[0,1]; loss.backward()
        self.assertTrue(torch.isfinite(field.delta.grad).all())
        self.assertTrue(torch.equal(field.weights()[1],torch.tensor(w[1])))
        self.assertTrue(field.validate())

    def test_repair_rejects_support_and_weld_mismatches(self):
        with self.assertRaises(ValueError):
            RepairWeightField([[0,0,0]], [], [[1.,0]], [1], [True], [[True,True,True]])
        with self.assertRaises(ValueError):
            RepairWeightField([[0,0,0],[0,0,0]], [], [[1.,0],[.5,.5]], [1,1], [True,True], [[True,True],[True,True]])

    def test_repair_rejects_overwide_support_and_bad_input_dtypes(self):
        v=[[0,0,0]]; w=[[1.,0,0,0,0,0,0,0,0]]
        with self.assertRaises(ValueError):
            RepairWeightField(v, np.empty((0,3), dtype=np.int64), w, np.array([1]), np.array([True]), np.ones((1,9), dtype=bool))
        with self.assertRaises(ValueError):
            RepairWeightField(v, np.empty((0,3), dtype=np.float64), [[1.]], np.array([1]), np.array([True]), np.array([[True]]))
        with self.assertRaises(ValueError):
            RepairWeightField(v, np.empty((0,3), dtype=np.int64), [[1.]], np.array([1]), np.array([1], dtype=np.int64), np.array([[True]]))
        with self.assertRaises(ValueError):
            RepairWeightField(v, np.empty((0,3), dtype=np.int64), [[1.]], np.array([1]), np.array([True]), np.array([[1]], dtype=np.int64))

    def test_repair_rejects_train_flag_conflict_and_keeps_tiny_support(self):
        args=([[0,0,0],[0,0,0]], [], [[1.,0.],[1.,0.]], np.array([1,1]),
              np.array([True,False]), np.array([[True,True],[True,True]]))
        with self.assertRaises(ValueError): RepairWeightField(*args)
        tiny=np.array([[True,True]], dtype=bool)
        field=RepairWeightField([[0,0,0]], np.empty((0,3), dtype=np.int64), [[1.-1e-10,1e-10]], np.array([1]), np.array([True]), tiny)
        self.assertTrue(field.validate())

    def test_repair_weld_and_edge_penalty_use_interleaved_uv_duplicates(self):
        v=[[0,0,0],[0,0,0],[1,0,0],[0,1,0],[1,0,0]]
        tri=np.array([[0,2,3],[1,4,3]], dtype=np.int64)
        w=np.array([[.7,.3],[.7,.3],[.2,.8],[1.,0.],[.2,.8]])
        field=RepairWeightField(v,tri,w,np.array([1]*5),np.array([True]*5),np.array([[True,True]]*5))
        self.assertEqual(len(field._weld_rows),3)
        field.delta.data[0,0]=.2
        value=field.weights(); self.assertTrue(torch.equal(value[0],value[1]))
        self.assertAlmostEqual(float(field.penalty(value).detach()), .004 + .02 / 3, places=6)


if __name__ == '__main__': unittest.main()
