"""Diagnostic native-donor replay anchored to raw joint positions."""
from __future__ import annotations
import numpy as np
from donor_eagle import skin_dense
from mesh_preview import fk_world_matrices


def replay_position_anchored(*, joint_world, raw_positions, parents, donor_offsets,
                             vertices=None, weights=None, inverse_bind=None):
    worlds=np.asarray(joint_world,dtype=np.float64); raw=np.asarray(raw_positions,dtype=np.float64)
    parent=np.asarray(parents); offsets=np.asarray(donor_offsets,dtype=np.float64)
    if worlds.ndim!=4 or worlds.shape[-2:]!=(4,4) or not worlds.shape[0] or not worlds.shape[1] or not np.isfinite(worlds).all(): raise ValueError('joint_world must be nonempty finite [F,J,4,4]')
    if not np.allclose(worlds[:,:,3,:], [0.,0.,0.,1.],atol=1e-10,rtol=0): raise ValueError('joint_world must be affine')
    if raw.shape!=worlds.shape[:2]+(3,) or not np.isfinite(raw).all(): raise ValueError('raw_positions must be finite [F,J,3]')
    if parent.ndim!=1 or parent.dtype.kind not in 'iu' or parent.shape!=(worlds.shape[1],) or parent[0]!=-1 or any(int(p)<0 or int(p)>=i for i,p in enumerate(parent[1:],1)): raise ValueError('parents must be root-first integer')
    if offsets.shape!=(len(parent),3) or not np.isfinite(offsets).all(): raise ValueError('donor_offsets must be finite [J,3]')
    rot=worlds[:,:,:3,:3]; eye=np.eye(3)
    if not np.allclose(rot.swapaxes(-1,-2)@rot,eye,atol=1e-6,rtol=0) or np.any(np.linalg.det(rot)<=0): raise ValueError('joint_world rotations must be proper SO(3)')
    local_r=np.empty_like(rot); local_t=np.empty_like(raw); local_r[:,0]=rot[:,0]; local_t[:,0]=raw[:,0]
    for j in range(1,len(parent)):
        p=int(parent[j]); local_r[:,j]=rot[:,p].swapaxes(-1,-2)@rot[:,j]; local_t[:,j]=np.einsum('fij,fj->fi',rot[:,p].swapaxes(-1,-2),raw[:,j]-raw[:,p])
    replay=np.stack([fk_world_matrices(local_rotation=local_r[f],local_translation=local_t[f],parents=parent,root_world=raw[f,0]) for f in range(len(raw))])
    anchored=worlds.copy()
    anchored[:,:,:3,3]=raw
    parity=float(np.max(np.abs(replay-anchored)))
    if parity>1e-6 or not np.isfinite(parity): raise ValueError('position-anchored FK parity failed')
    deviation=float(np.max(np.linalg.norm(replay[:,:,:3,3]-raw,axis=-1)))
    result={'jointWorld':anchored,'positions':anchored[:,:,:3,3],'localRotation':local_r,'localTranslation':local_t,
            'fkParityMax':parity,
            'rawPositionReplayMaxError':deviation,'donorOffsetDeviationMax':float(np.max(np.abs(local_t[:,1:]-offsets[1:]),initial=0.)),
            'motionOwner':'position_anchored_native_donor_diagnostic','accepted':False,'fixedLengthClaim':False}
    if vertices is not None or weights is not None or inverse_bind is not None:
        if vertices is None or weights is None or inverse_bind is None: raise ValueError('vertices, weights, inverse_bind must be supplied together')
        verts=np.asarray(vertices,dtype=np.float64); skin=np.asarray(weights,dtype=np.float64); ibm=np.asarray(inverse_bind,dtype=np.float64)
        if verts.ndim!=2 or verts.shape[1]!=3 or skin.shape!=(len(verts),len(parent)) or not np.isfinite(verts).all() or not np.isfinite(skin).all() or np.any(skin<0) or not np.allclose(skin.sum(1),1.,atol=1e-8) or ibm.shape!=(len(parent),4,4) or not np.isfinite(ibm).all(): raise ValueError('invalid native donor skin inputs')
        result['meshes']=np.stack([skin_dense(verts,skin,w,ibm) for w in anchored])
    return result

__all__=['replay_position_anchored']
