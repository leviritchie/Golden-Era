import sys,unittest
from pathlib import Path
import numpy as np
HERE=Path(__file__).resolve().parent
if str(HERE) not in sys.path: sys.path.insert(0,str(HERE))
from native_donor_coordinates import fit_normalized_pose_to_native,apply_pose_to_native
class NativeCoordinateTests(unittest.TestCase):
 def test_known_similarity_and_root_anchor(self):
  s=np.array([[[0,0,0],[1,0,0],[0,1,0]],[[0,0,0],[0,1,0],[-1,0,0]]],float); q=np.array([[0,-1,0],[1,0,0],[0,0,1.]])
  t=2*s@q.T+np.array([[[3,2,1]],[[4,1,2]]]); c=fit_normalized_pose_to_native(s,t); self.assertAlmostEqual(c['scale'],2.,places=8); out=apply_pose_to_native(s,c,np.array([[3,2,1],[4,1,2]])); np.testing.assert_allclose(out,t)
 def test_model_normalization_is_not_stored_pose_units(self):
  stored=np.array([[[1.,2.,3.],[2.,2.,3.],[1.,3.,3.],[1.,2.,4.]]])
  normalized=(stored-stored[:,:1])/.4
  native=2.*(stored-stored[:,:1])+[.3,.2,.1]
  c=fit_normalized_pose_to_native(normalized,native)
  self.assertAlmostEqual(c['scale'],.8,places=12)
  np.testing.assert_allclose(apply_pose_to_native(normalized,c,[.3,.2,.1]),native)
 def test_reflection_and_degenerate_pairs_rejected(self):
  source=np.array([[[0.,0.,0.],[1.,0.,0.],[0.,1.,0.],[0.,0.,1.]]])
  target=source.copy(); target[:,:,0]*=-1
  with self.assertRaises(ValueError): fit_normalized_pose_to_native(source,target)
  with self.assertRaises(ValueError): fit_normalized_pose_to_native(np.zeros_like(source),source)
 def test_nonrigid_and_mutability(self):
  s=np.zeros((2,3,3)); s[0,1]=[1,0,0]; s[1,1]=[0,1,0]; t=s.copy(); t[1,2]=[2,0,0]; snap=s.copy()
  with self.assertRaises(ValueError): fit_normalized_pose_to_native(s,t)
  np.testing.assert_array_equal(s,snap)
 def test_nonzero_roots_rejected_for_apply(self):
  with self.assertRaises(ValueError): apply_pose_to_native(np.ones((1,2,3)),{'scale':1.,'rotation':np.eye(3)},[0,0,0])
if __name__=='__main__': unittest.main()
