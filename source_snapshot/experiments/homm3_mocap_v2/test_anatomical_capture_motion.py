import sys
import unittest
from pathlib import Path
import numpy as np

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path: sys.path.insert(0, str(HERE))
from anatomical_capture_motion import reconstruct_anatomical_capture
from mesh_preview import fk_world_matrices
from test_anatomical_direction_transfer import rot


def rz(a):
    c, s = np.cos(a), np.sin(a)
    return np.array([[c,-s,0],[s,c,0],[0,0,1.]])


def fixture():
    parents = np.array([-1,0,0,1,1,2,2])
    off = np.array([[0,0,0],[1,.2,0],[-.3,1.1,.1],[.4,.2,.3],[-.2,.3,.1],[.3,.5,.2],[-.4,.2,.3]],float)
    rest = np.zeros_like(off)
    for i,p in enumerate(parents): rest[i] = off[i] if p < 0 else rest[p]+off[i]
    names=[f'J{i}' for i in range(len(parents))]
    return parents,off,rest,names


class AnatomicalCaptureTests(unittest.TestCase):
    def test_rigid_motion_is_one_rotation_not_merely_fixed_lengths(self):
        parents, offsets, reference, names = fixture()
        target = offsets * np.linspace(.7, 1.4, len(names))[:, None]
        travel = np.array([.25, -.13, .07])
        for axis in np.eye(3):
            for degrees in (-90, -45, 0, 45, 90):
                q = rot(axis, degrees)
                frames = (reference @ q.T + travel)[None]
                result = self.call(frames=frames, offsets=target)
                gauge = result['wholeBodyRotation']
                target_q = gauge @ q @ gauge.T
                rest = result['fittedRest']
                expected_positions = (rest - rest[0]) @ target_q.T + rest[0] + gauge @ travel
                np.testing.assert_allclose(result['positions'][0], expected_positions, atol=1e-8)
                np.testing.assert_allclose(result['jointWorld'][0, :, :3, :3],
                    np.broadcast_to(target_q, (len(names), 3, 3)), atol=1e-8)

    def test_straight_terminal_chain_uses_observable_ancestor_plane(self):
        parents = np.array([-1, 0, 0, 1, 3])
        off = np.array([[0., 0., 0.], [1., 0., 0.], [0., 1., .2], [1., 0., 0.], [1., 0., 0.]])
        rest = off.copy()
        for i in range(1, len(parents)):
            rest[i] += rest[parents[i]]
        names = ['root', 'base', 'side', 'middle', 'tip']
        result = reconstruct_anatomical_capture(capture_positions=rest[None],
            capture_reference_positions=rest, capture_offsets=off, fitted_offsets=off,
            parents=parents, names=names, hub_names=('root', 'base', 'side'))
        self.assertGreater(result['hints']['tip']['graphDistance'], 1)
        np.testing.assert_allclose(result['positions'][0], rest, atol=1e-8)

    def call(self, frames=None, source=None, target=None, offsets=None, target_weights=None):
        parents, off, rest, names = fixture()
        source = rest if source is None else source
        target = rest if target is None else target
        offsets = off if offsets is None else offsets
        if frames is None: frames = source[None]
        return reconstruct_anatomical_capture(capture_positions=frames,
            capture_reference_positions=source, capture_offsets=off,
            fitted_offsets=offsets, parents=parents, names=names,
            hub_names=('J1','J2','J5'), target_weights=target_weights)

    def test_neutral_bind_and_lengths(self):
        result=self.call()
        self.assertTrue(result['clipFrame0IsBind'] if 'clipFrame0IsBind' in result else np.max(np.abs(result['positions'][0]-result['fittedRest']))<1e-8)
        self.assertLess(result['fixedLengthErrorMax'],1e-8)
        np.testing.assert_allclose(result['positions'][0], result['fittedRest'], atol=1e-8)
        self.assertTrue(all(item['graphDistance'] >= 1 and '->' in item['hintJoint'] for item in result['hints'].values()))

    def test_rigid_common_rotation_preserves_lengths(self):
        _,_,rest,_=fixture(); q=rz(np.deg2rad(45)); frame=(q@ (rest-rest[0]).T).T+rest[0]
        result=self.call(frames=frame[None])
        self.assertLess(result['fixedLengthErrorMax'],1e-8)
        self.assertTrue(np.isfinite(result['jointWorld']).all())

    def test_collapsed_posed_hubs_fail_closed(self):
        _, _, rest, _ = fixture()
        frame = rest.copy()
        frame[[1, 2, 5]] = frame[1]
        with self.assertRaises(ValueError):
            self.call(frames=frame[None])

    def test_returned_local_fk_matches_root_motion_world(self):
        _, _, rest, _ = fixture(); q=rz(np.deg2rad(32.)); frame=(q @ (rest-rest[0]).T).T+np.array([.7,-.2,.3])
        result=self.call(frames=frame[None])
        parents, off, _, _ = fixture(); root=result['positions'][0,0]
        replay=fk_world_matrices(local_rotation=result['localRotation'][0], local_translation=np.where(np.arange(len(off))[:,None]==0,0.,off), parents=parents, root_world=root)
        np.testing.assert_allclose(replay, result['jointWorld'][0], atol=1e-7)

    def test_arbitrary_articulation_preserves_lengths(self):
        parents,off,rest,names=fixture(); posed=rest.copy(); posed[3]=rest[1]+rz(.4)@(rest[3]-rest[1]); posed[4]=rest[1]+rz(-.3)@(rest[4]-rest[1])
        result=self.call(frames=posed[None]); self.assertLess(result['fixedLengthErrorMax'],1e-8)

    def test_target_zero_observable_fails(self):
        parents,off,rest,names=fixture(); bad=off.copy(); bad[3]=0
        with self.assertRaisesRegex(ValueError,'zero-length'):
            self.call(offsets=bad)

    def test_inactive_zero_weight_leaf_is_explicitly_omitted(self):
        parents, off, rest, names = fixture(); bad=off.copy(); bad[3]=0.
        weights=np.zeros((2,len(names))); weights[:,0]=1.
        result=self.call(offsets=bad, target_weights=weights)
        self.assertEqual(result['inactiveTargetLeaves'][0]['joint'], 'J3')
        self.assertLess(result['fixedLengthErrorMax'], 1e-8)

    def test_zero_weight_requirement_and_nonleaf_are_hard_failures(self):
        parents, off, rest, names = fixture(); bad=off.copy(); bad[3]=0.
        weights=np.zeros((2,len(names))); weights[:,0]=1.; weights[:,3]=.1; weights[:,0]=.9
        with self.assertRaisesRegex(ValueError, 'zero-length'):
            self.call(offsets=bad, target_weights=weights)
        bad=off.copy(); bad[1]=0.
        weights=np.zeros((2,len(names))); weights[:,0]=1.
        with self.assertRaisesRegex(ValueError, 'zero-length'):
            self.call(offsets=bad, target_weights=weights)

    def test_degenerate_hint_fails(self):
        parents,off,rest,names=fixture(); bad=off.copy(); bad[1:]=np.array([[1.,0,0],[2.,0,0],[1.,0,0],[2.,0,0],[3.,0,0],[4.,0,0]])
        with self.assertRaises(ValueError):
            self.call(offsets=bad)


if __name__=='__main__': unittest.main()
