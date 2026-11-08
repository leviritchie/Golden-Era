#!/usr/bin/env python3
"""GPU-deform sparse batched helper"""
import torch
import numpy as np

def deform_sparse_batched(verts, rest, hidx, weights, vecs, cam):
    B = vecs.shape[0]
    N = verts.shape[0]
    H = rest.shape[0]
    device = verts.device
    dtype = verts.dtype
    vecs_r = vecs.reshape(B, H, 6)
    u = vecs_r[:,:,0]; v = vecs_r[:,:,1]; d = vecs_r[:,:,2]
    rx = vecs_r[:,:,3]; ry = vecs_r[:,:,4]; rz = vecs_r[:,:,5]
    right = torch.tensor(cam["right"], device=device, dtype=dtype)
    up = torch.tensor(cam["up"], device=device, dtype=dtype)
    forward = torch.tensor(cam["forward"], device=device, dtype=dtype)
    T = right[None,None,:]*u[:,:,None] + up[None,None,:]*v[:,:,None] + forward[None,None,:]*d[:,:,None]
    cx=torch.cos(rx); sx=torch.sin(rx)
    cy=torch.cos(ry); sy=torch.sin(ry)
    cz=torch.cos(rz); sz=torch.sin(rz)
    Rx=torch.zeros((B,H,3,3), device=device, dtype=dtype)
    Rx[:,:,0,0]=1; Rx[:,:,1,1]=cx; Rx[:,:,1,2]=-sx; Rx[:,:,2,1]=sx; Rx[:,:,2,2]=cx
    Ry=torch.zeros((B,H,3,3), device=device, dtype=dtype)
    Ry[:,:,1,1]=1; Ry[:,:,0,0]=cy; Ry[:,:,0,2]=sy; Ry[:,:,2,0]=-sy; Ry[:,:,2,2]=cy
    Rz=torch.zeros((B,H,3,3), device=device, dtype=dtype)
    Rz[:,:,2,2]=1; Rz[:,:,0,0]=cz; Rz[:,:,0,1]=-sz; Rz[:,:,1,0]=sz; Rz[:,:,1,1]=cz
    R=torch.matmul(torch.matmul(Rz,Ry),Rx)
    deformed = torch.zeros((B,N,3), device=device, dtype=dtype)
    for k in range(4):
        hi = hidx[:,k]
        w = weights[:,k]
        mask = (hi >= 0)
        if not mask.any():
            continue
        p = rest[hi.clamp(min=0)]
        Rk = R[:, hi.clamp(min=0)]
        Tk = T[:, hi.clamp(min=0)]
        diff = verts[None,:,:] - p[None,:,:]
        diff_rot = torch.einsum('bnk,bnkj->bnj', diff, Rk.transpose(-1,-2))
        vt = diff_rot + p[None,:,:] + Tk
        w_exp = w[None,:,None] * mask[None,:,None].float()
        deformed += vt * w_exp
    return deformed

def project_batched(verts_b, cam, W, H):
    cam_loc=torch.tensor(cam["cam_loc"], device=verts_b.device, dtype=verts_b.dtype)
    right=torch.tensor(cam["right"], device=verts_b.device, dtype=verts_b.dtype)
    up=torch.tensor(cam["up"], device=verts_b.device, dtype=verts_b.dtype)
    ortho=float(cam["ortho"])
    aspect=H/float(W)
    rel=verts_b - cam_loc[None,None,:]
    xc=rel @ right
    yc=rel @ up
    px=(xc/ortho+0.5)*W
    py=(-yc/(ortho*aspect)+0.5)*H
    pts=torch.stack([px,py], dim=-1)
    return pts

def rasterize_cv2_batch_proj(pts_batch_np, faces, H, W):
    import cv2
    B = pts_batch_np.shape[0]
    masks = np.zeros((B, H, W), dtype=np.float32)
    for b in range(B):
        pts = np.round(pts_batch_np[b]).astype(np.int32)
        m = np.zeros((H,W), dtype=np.uint8)
        tris=[pts[f] for f in faces]
        cv2.fillPoly(m, tris, 1)
        masks[b]=m.astype(np.float32)
    return masks
