import sys, unittest
import numpy as np
import torch
sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parent))
from skin_weight_field import WeightField

class WeightFieldTests(unittest.TestCase):
    def setUp(self):
        self.v=np.array([[0,0,0],[1,0,0],[0,1,0],[1,0,0]],float); self.f=np.array([[0,1,2],[0,3,2]]); self.r=np.array(['wing_left']*4); self.n=['A','B','C']; self.w=np.array([[1,0,0],[.2,.8,0],[0,1,0],[.2,.8,0]])
    def test_normalized_allowed_and_duplicate_consistent(self):
        x=WeightField(self.v,self.f,self.w,self.r,self.n,{'wing_left':('A','B')},train_regions={'wing_left'})
        y=x.weights(); self.assertTrue(torch.allclose(y.sum(1),torch.ones(4))); self.assertTrue(torch.all(y[:,2]<1e-7)); self.assertTrue(torch.allclose(y[1],y[3])); self.assertLessEqual(x.support_stats()['maxInfluences'],8)
    def test_frozen_rows_are_exact(self):
        r=self.r.copy(); r[2]='leg_left'; x=WeightField(self.v,self.f,self.w,r,self.n,{'wing_left':('A','B'),'leg_left':('A','C')},train_regions={'wing_left'}); self.assertTrue(torch.equal(x.weights()[2],torch.tensor(self.w[2],dtype=torch.float32)))
    def test_frozen_vertices_keep_initial_weights_inside_train_region(self):
        x=WeightField(self.v,self.f,self.w,self.r,self.n,{'wing_left':('A','B')},train_regions={'wing_left'},frozen_vertices=[2])
        with torch.no_grad():
            x.group_logits[:, 0] = 8
            x.group_logits[:, 1] = -8
        y=x.weights()
        self.assertTrue(torch.equal(y[2], torch.tensor(self.w[2], dtype=torch.float32)))
        self.assertGreater(float(y[1, 0].detach()), 0.5)
    def test_invalid_frozen_vertices_refused(self):
        with self.assertRaises(ValueError):
            WeightField(self.v,self.f,self.w,self.r,self.n,{'wing_left':('A','B')},train_regions={'wing_left'},frozen_vertices=[4])
    def test_bind_identity_arbitrary_weights_and_gradients(self):
        x=WeightField(self.v,self.f,self.w,self.r,self.n,{'wing_left':('A','B')},train_regions={'wing_left'}); y=x.weights(); self.assertEqual(y.shape,(4,3)); loss=x.penalty(y); loss.backward(); self.assertIsNotNone(x.group_logits.grad)
    def test_unsupported_influence_count_refused(self):
        w=np.ones((4,9))/9; names=[f'J{i}' for i in range(9)]
        with self.assertRaises(ValueError): WeightField(self.v,self.f,w,self.r,names,{'wing_left':tuple(names)},train_regions={'wing_left'})

    def test_candidate_support_over_eight_refused_even_with_sparse_initial_weights(self):
        names=[f'J{i}' for i in range(9)]
        w=np.zeros((4,9)); w[:,0]=1
        with self.assertRaises(ValueError): WeightField(self.v,self.f,w,self.r,names,{'wing_left':tuple(names)},train_regions={'wing_left'})

    def test_bad_weight_sum_refused(self):
        bad=self.w.copy(); bad[0,0]=0.5
        with self.assertRaises(ValueError): WeightField(self.v,self.f,bad,self.r,self.n,{'wing_left':('A','B')},train_regions={'wing_left'})
if __name__=='__main__': unittest.main()
