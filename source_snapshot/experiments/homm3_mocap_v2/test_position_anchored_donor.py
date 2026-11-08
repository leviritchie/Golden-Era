import sys,unittest
from pathlib import Path
import numpy as np
HERE=Path(__file__).resolve().parent
if str(HERE) not in sys.path: sys.path.insert(0,str(HERE))
from position_anchored_donor import replay_position_anchored
from mesh_preview import fk_world_matrices
from donor_eagle import bind_world_matrices,inverse_bind_matrices,skin_dense
from direction_retarget import _rodrigues
class PositionAnchoredTests(unittest.TestCase):
 def test_neutral_rigid_and_inputs_immutable(self):
  p=np.array([-1,0,0]); o=np.array([[.2,.3,-.1],[1.,0,0],[0.,1,0]])
  bind=bind_world_matrices(o,p); inverse=inverse_bind_matrices(bind)
  vertices=np.array([[.7,.1,.2],[1.2,.4,.3]]); weights=np.array([[.4,.6,0.],[.2,0.,.8]])
  for angle in (0.,.6):
   rotation=_rodrigues(np.array([0.,0.,1.]),angle)
   local=np.repeat(np.eye(3)[None],3,0); local[0]=rotation
   root=o[0]+np.array([angle,-angle,.2*angle])
   world=fk_world_matrices(local_rotation=local,local_translation=o,parents=p,root_world=root)[None]
   before=world.copy(); raw=world[:,:,:3,3].copy(); raw_before=raw.copy()
   result=replay_position_anchored(joint_world=world,raw_positions=raw,parents=p,donor_offsets=o,
       vertices=vertices,weights=weights,inverse_bind=inverse)
   np.testing.assert_array_equal(world,before); np.testing.assert_array_equal(raw,raw_before)
   np.testing.assert_array_equal(result['jointWorld'][:,:,:3,:3],world[:,:,:3,:3])
   expected=(vertices-o[0])@rotation.T+root
   np.testing.assert_allclose(result['meshes'][0],expected,atol=1e-10)
   self.assertLess(result['fkParityMax'],1e-10)

 def test_empty_and_nonaffine_rejected(self):
  for shape in ((0,2,4,4),(1,0,4,4)):
   with self.assertRaises(ValueError):
    replay_position_anchored(joint_world=np.zeros(shape),raw_positions=np.zeros(shape[:2]+(3,)),
        parents=np.array([-1,0]),donor_offsets=np.zeros((2,3)))
  world=np.eye(4)[None,None].copy(); world[0,0,3,0]=1.
  with self.assertRaisesRegex(ValueError,'affine'):
   replay_position_anchored(joint_world=world,raw_positions=np.zeros((1,1,3)),
       parents=np.array([-1]),donor_offsets=np.zeros((1,3)))
 def test_raw_positions_exact_and_variable_offsets(self):
  p=np.array([-1,0,0]); o=np.array([[0.,0,0],[1,0,0],[0,1,0]]); r=np.array([[0.,0,0],[1,0,0],[0,1,0]])
  w=np.stack([fk_world_matrices(local_rotation=np.repeat(np.eye(3)[None],3,0),local_translation=o,parents=p,root_world=x[0]) for x in (r,r+np.array([2.,1.,0.]))]); out=replay_position_anchored(joint_world=w,raw_positions=w[:,:,:3,3],parents=p,donor_offsets=o)
  np.testing.assert_allclose(out['positions'],w[:,:,:3,3]); self.assertLess(out['rawPositionReplayMaxError'],1e-8)
 def test_rejects_improper_rotation(self):
  p=np.array([-1,0]); o=np.array([[0.,0,0],[1,0,0]]); w=np.repeat(np.eye(4)[None,None],2,0); w=w.reshape(1,2,4,4); w[0,0,0,0]=-1
  with self.assertRaises(ValueError): replay_position_anchored(joint_world=w,raw_positions=np.zeros((1,2,3)),parents=p,donor_offsets=o)
 def test_fork_uses_explicit_local_translation(self):
  p=np.array([-1,0,0,1]); o=np.array([[0.,0,0],[1,0,0],[0,1,0],[0,.5,0]]); r=np.array([[0.,0,0],[1,0,0],[1,1,0],[1,.5,0]])
  w=np.stack([fk_world_matrices(local_rotation=np.repeat(np.eye(3)[None],4,0),local_translation=o,parents=p,root_world=np.zeros(3))]); raw=r[None].copy(); raw[0,3]=[1,.5,.2]; out=replay_position_anchored(joint_world=w,raw_positions=raw,parents=p,donor_offsets=o)
  self.assertGreater(out['donorOffsetDeviationMax'],0); np.testing.assert_allclose(out['positions'],raw,atol=1e-8)
if __name__=='__main__': unittest.main()
