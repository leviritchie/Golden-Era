import sys, unittest
from pathlib import Path
import numpy as np
HERE=Path(__file__).resolve().parent
if str(HERE) not in sys.path: sys.path.insert(0,str(HERE))
from native_donor_position_replay import replay_native_donor
from donor_eagle import bind_world_matrices, inverse_bind_matrices, skin_dense
from mesh_preview import fk_world_matrices
from direction_retarget import _rodrigues

class NativeDonorReplayTests(unittest.TestCase):
    def fixture(self):
        parents=np.array([-1,0,0,1,1,2]); off=np.array([[0,0,0],[1,0,0],[0,1,0],[0,.5,0],[.3,.2,0],[.2,.4,0]],float)
        rest=np.zeros_like(off)
        for i,p in enumerate(parents): rest[i]=off[i] if p<0 else rest[p]+off[i]
        return parents,off,rest
    def test_native_rigid_and_articulation(self):
        p,o,r=self.fixture(); q=np.array([[0,-1,0],[1,0,0],[0,0,1.]])
        frame=(q@(r-r[0]).T).T+r[0]; out=replay_native_donor(captured_positions=frame[None],donor_offsets=o,parents=p,names=[str(i) for i in range(len(p))])
        self.assertLess(out['endpointResidualMax'][0],1e-8); self.assertTrue(out['exactReplay'])
    def test_neutral_mesh(self):
        p,o,r=self.fixture(); v=np.array([[0.,0,0],[1,0,0],[0,1,0]]); w=np.zeros((3,len(p))); w[:,0]=1
        ibm=np.repeat(np.eye(4)[None],len(p),axis=0)
        out=replay_native_donor(captured_positions=r[None],donor_offsets=o,parents=p,names=[str(i) for i in range(len(p))],vertices=v,weights=w,inverse_bind=ibm)
        self.assertEqual(out['meshes'].shape,(1,3,3))
        np.testing.assert_allclose(out['meshes'][0], v, atol=1e-10)

    def test_observable_articulated_forks_recover_weighted_mesh(self):
        p,o,_=self.fixture()
        o[0]=[.2,-.3,.4]
        rotations=np.repeat(np.eye(3)[None],len(p),axis=0)
        rotations[0]=_rodrigues(np.array([0.,0.,1.]), .7)
        rotations[1]=_rodrigues(np.array([1.,0.,0.]), -.4)
        world=fk_world_matrices(local_rotation=rotations,local_translation=o,
            parents=p,root_world=o[0]+[.5,.1,-.2])
        verts=np.array([[.7,.2,.1],[1.2,.3,-.1],[.5,-.2,.8]])
        weights=np.zeros((len(verts),len(p)))
        weights[:,:2]=[[1.,0.],[0.,1.],[.4,.6]]
        inverse=inverse_bind_matrices(bind_world_matrices(o,p))
        result=replay_native_donor(captured_positions=world[None,:,:3,3],
            donor_offsets=o,parents=p,names=list(map(str,range(len(p)))),
            vertices=verts,weights=weights,inverse_bind=inverse)
        np.testing.assert_allclose(result['positions'][0],world[:,:3,3],atol=1e-9)
        np.testing.assert_allclose(result['meshes'][0],
            skin_dense(verts,weights,world,inverse),atol=1e-9)

    def test_separated_structural_edge_rejected(self):
        p=np.array([-1,0,1]); o=np.array([[0.,0.,0.],[0.,0.,0.],[1.,0.,0.]])
        capture=np.array([[[0.,0.,0.],[0.,.1,0.],[1.,.1,0.]]])
        with self.assertRaisesRegex(ValueError,'coincident'):
            replay_native_donor(captured_positions=capture,donor_offsets=o,
                parents=p,names=['root','hub','tip'])

    def test_fixed_lengths_do_not_imply_compatible_fork_angles(self):
        parents=np.array([-1,0,0])
        offsets=np.array([[0.,0.,0.],[1.,0.,0.],[0.,1.,0.]])
        capture=offsets.copy()
        capture[2]=[.5,np.sqrt(.75),0.]
        result=replay_native_donor(captured_positions=capture[None],
            donor_offsets=offsets,parents=parents,names=['root','a','b'])
        self.assertLess(result['rawLengthErrorMax'][0],1e-12)
        self.assertGreater(result['directionErrorMaxDeg'][0],14.9)
        self.assertFalse(result['exactReplay'])

    def test_exact_positions_cannot_certify_axial_skin_rotation(self):
        parents=np.array([-1,0])
        offsets=np.array([[0.,0.,0.],[1.,0.,0.]])
        local=np.repeat(np.eye(3)[None],2,axis=0)
        local[0]=_rodrigues(np.array([1.,0.,0.]),np.pi/2)
        world=fk_world_matrices(local_rotation=local,local_translation=offsets,
            parents=parents,root_world=offsets[0])
        vertices=np.array([[.5,1.,0.]])
        weights=np.array([[1.,0.]])
        inverse=inverse_bind_matrices(bind_world_matrices(offsets,parents))
        result=replay_native_donor(captured_positions=world[None,:,:3,3],
            donor_offsets=offsets,parents=parents,names=['root','tip'],
            vertices=vertices,weights=weights,inverse_bind=inverse)
        self.assertTrue(result['exactReplay'])
        self.assertGreater(np.linalg.norm(result['meshes'][0]-
            skin_dense(vertices,weights,world,inverse)),1.)
    def test_collapsed_observable_rejected(self):
        p,o,r=self.fixture(); bad=r.copy(); bad[3]=bad[1]
        with self.assertRaises(ValueError): replay_native_donor(captured_positions=bad[None],donor_offsets=o,parents=p,names=[str(i) for i in range(len(p))])
    def test_raw_lengths_are_reported_not_claimed_fixed(self):
        p,o,r=self.fixture(); frame=r.copy(); frame[3]=r[1]+np.array([0.,.8,0.])
        out=replay_native_donor(captured_positions=frame[None],donor_offsets=o,parents=p,names=[str(i) for i in range(len(p))])
        self.assertGreater(out['rawLengthErrorMax'][0], 0.)
        self.assertFalse(out['exactReplay'])
    def test_root_offset_and_travel_are_replayed(self):
        p,o,r=self.fixture(); frame=r+np.array([2.,-1.,.5]); out=replay_native_donor(captured_positions=frame[None],donor_offsets=o,parents=p,names=[str(i) for i in range(len(p))])
        np.testing.assert_allclose(out['positions'][0,0], frame[0]); np.testing.assert_allclose(out['positions'][0,1]-out['positions'][0,0], o[1], atol=1e-8)
    def test_rejects_empty_and_noninteger_parents(self):
        p,o,r=self.fixture()
        with self.assertRaises(ValueError): replay_native_donor(captured_positions=np.zeros((1,0,3)),donor_offsets=np.zeros((0,3)),parents=np.zeros(0,dtype=int),names=[])
        with self.assertRaisesRegex(ValueError,'integer'):
            replay_native_donor(captured_positions=r[None],donor_offsets=o,parents=p.astype(float),names=[str(i) for i in range(len(p))])

if __name__=='__main__': unittest.main()
