import sys
import unittest
from pathlib import Path
import torch

HERE=Path(__file__).resolve().parent
if str(HERE) not in sys.path: sys.path.insert(0,str(HERE))
from joint_axis_calibration import JointAxisCalibration


class JointAxisCalibrationTests(unittest.TestCase):
    def fixture(self):
        f,j=4,3
        source=torch.eye(3,dtype=torch.float64).repeat(f,j,1,1)
        roots=torch.tensor([[0.,0,0],[1.,0,0],[0,1,0],[0,0,1]],dtype=torch.float64)
        off=torch.tensor([[0.,0,0],[0,1,0],[1,0,0]],dtype=torch.float64)
        parents=torch.tensor([-1,0,1])
        return source,roots,off,parents

    def test_identity_and_neutral(self):
        m=JointAxisCalibration(*self.fixture()); out=m(); self.assertTrue(torch.allclose(out[:,:, :3,:3],m.source_local)); self.assertTrue(torch.allclose(out[:,1, :3,3]-out[:,0,:3,3],m.offsets[1]))

    def test_inputs_detached_and_root_unchanged(self):
        src,root,off,par=self.fixture(); src.requires_grad_(); m=JointAxisCalibration(src,root,off,par); m.raw.data[0,0]=.4
        self.assertFalse(m.source_local.requires_grad); self.assertTrue(torch.allclose(m().detach()[:,0,:3,:3],src.detach()[:,0]))

    def test_arbitrary_axes_preserve_neutral_identity(self):
        m=JointAxisCalibration(*self.fixture()); m.raw.data.copy_(torch.tensor([[.7,-.2,.4],[.1,.3,-.5]],dtype=torch.float64))
        self.assertTrue(torch.allclose(m.locals()[:,1:], torch.eye(3,dtype=torch.float64).expand(4,2,3,3), atol=1e-10))

    def test_rigid_root_motion_identity_nonroots(self):
        src,roots,off,par=self.fixture(); m=JointAxisCalibration(src,roots,off,par); out=m()
        self.assertTrue(torch.allclose(out[:,:,:3,:3], torch.eye(3,dtype=torch.float64).expand(4,3,3,3), atol=1e-10))
        self.assertTrue(torch.allclose(out[:,0,:3,3], roots, atol=1e-10))
        self.assertTrue(torch.allclose(out[:,2,:3,3]-out[:,1,:3,3], off[2], atol=1e-10))

    def test_conjugation_preserves_rotation_trace(self):
        src,roots,off,par=self.fixture(); src[0,1]=torch.tensor([[0.,-1.,0.],[1.,0.,0.],[0.,0.,1.]],dtype=torch.float64)
        m=JointAxisCalibration(src,roots,off,par); m.raw.data.fill_(.35)
        before=torch.diagonal(src[:,1:],dim1=-2,dim2=-1).sum(-1); after=torch.diagonal(m.locals()[:,1:],dim1=-2,dim2=-1).sum(-1)
        self.assertTrue(torch.allclose(before,after,atol=1e-9))

    def test_lengths_and_gradients(self):
        m=JointAxisCalibration(*self.fixture()); m.raw.data.fill_(.2); loss=m()[:,:, :3,3].square().sum(); loss.backward(); self.assertTrue(torch.isfinite(m.raw.grad).all())

    def test_small_vertex_objective_optimizes(self):
        src,roots,off,par=self.fixture(); truth=JointAxisCalibration(src,roots,off,par); truth.raw.data[0]=torch.tensor([.25,-.1,.2])
        target=truth()[:,2,:3,3].detach(); trial=JointAxisCalibration(src,roots,off,par); opt=torch.optim.Adam(trial.parameters(),lr=.08)
        for _ in range(80):
            opt.zero_grad(); loss=(trial()[:,2,:3,3]-target).square().mean(); loss.backward(); opt.step()
        self.assertTrue(torch.isfinite(trial.raw).all()); self.assertLess(float((trial()[:,2,:3,3]-target).square().mean().detach()),1e-8)

    def test_validation(self):
        src,root,off,par=self.fixture(); bad=src.clone(); bad[0,0,0,0]=2
        with self.assertRaises(ValueError): JointAxisCalibration(bad,root,off,par)


if __name__=='__main__': unittest.main()
