"""Fit explicit normalized vendor coordinates to native donor coordinates."""
from __future__ import annotations
import numpy as np

def fit_normalized_pose_to_native(normalized_positions, native_positions):
    source=np.asarray(normalized_positions,dtype=np.float64); target=np.asarray(native_positions,dtype=np.float64)
    if source.ndim!=3 or source.shape!=target.shape or source.shape[-1]!=3 or not np.isfinite(source).all() or not np.isfinite(target).all(): raise ValueError('positions must have matching finite [F,J,3] shape')
    if source.shape[0]<1 or source.shape[1]<3: raise ValueError('positions require at least three joints')
    s=source-source[:,0:1]; t=target-target[:,0:1]
    flat_s=s.reshape(-1,3); flat_t=t.reshape(-1,3)
    if np.linalg.matrix_rank(flat_s,tol=1e-10)<2 or np.linalg.norm(flat_s)>0 and np.linalg.norm(flat_t)<=1e-12: raise ValueError('paired positions are rank-deficient')
    denom=float(np.sum(flat_s*flat_s))
    u,_,vh=np.linalg.svd(flat_s.T@flat_t); q=vh.T@u.T
    if np.linalg.det(q)<0: vh[-1]*=-1; q=vh.T@u.T
    if np.linalg.det(q)<=0: raise ValueError('similarity fit requires reflection')
    scale=float(np.sum(flat_s*(flat_t@q))/denom)
    if not np.isfinite(scale) or scale<=0: raise ValueError('similarity scale is not positive')
    rotation=q
    residual=float(np.linalg.norm(scale*flat_s@rotation.T-flat_t,axis=1).max())
    extent=float(np.linalg.norm(np.ptp(flat_t,axis=0)))
    limit=1e-6*max(1.,extent)
    if residual>limit: raise ValueError(f'non-similarity residual too large: {residual}')
    return {'scale':scale,'rotation':rotation.tolist(),'residualMax':residual,'residualLimit':limit,'sourceFrameCount':source.shape[0],'jointCount':source.shape[1]}

def apply_pose_to_native(positions, conversion, native_root_anchor):
    values=np.asarray(positions,dtype=np.float64)
    if values.ndim!=3 or values.shape[-1]!=3 or not values.shape[0] or not values.shape[1] or not np.isfinite(values).all(): raise ValueError('positions must be nonempty finite [F,J,3]')
    if not np.allclose(values[:,0],0.,atol=1e-8,rtol=0): raise ValueError('positions must be root-relative with zero roots')
    scale=float(conversion['scale']); rotation=np.asarray(conversion['rotation'],dtype=np.float64)
    if not np.isfinite(scale) or scale<=0 or rotation.shape!=(3,3) or not np.allclose(rotation.T@rotation,np.eye(3),atol=1e-6,rtol=0) or np.linalg.det(rotation)<=0: raise ValueError('invalid conversion')
    anchor=np.asarray(native_root_anchor,dtype=np.float64)
    if anchor.shape==(3,): anchor=np.broadcast_to(anchor,(len(values),3))
    if anchor.shape!=(len(values),3) or not np.isfinite(anchor).all(): raise ValueError('native_root_anchor must be [3] or [F,3]')
    return scale*values@rotation.T+anchor[:,None,:]

__all__=['fit_normalized_pose_to_native','apply_pose_to_native']
