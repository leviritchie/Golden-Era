#!/usr/bin/env python3
"""
Part-rig GPU fitter: rigid parts + differentiable soft raster + Adam.

Deformation model (structurally CANNOT spike or hole):
  v' = sum_k w_k ( R_k (v - c_k) + c_k + t_k )
Interior verts are rigid (single influence); seam verts blend two rigid
transforms. Each part has 6 DOF (u,v,d translation in camera basis + euler
rx,ry,rz about its centroid). 15 parts => 90 DOF.

Optimizer: Adam on a differentiable soft rasterizer (pure torch, GPU). The
soft coverage is smooth w.r.t. vertex positions (edge-function ramp), so
gradients flow to part transforms. Fit runs on a decimated PROXY mesh
(~10K faces); the same part transforms are then evaluated on the full
46K-face welded mesh with exact cv2 raster.

Loss: 1-IoU + lambdaEdge*edge + lambdaDt*dt + lambdaAdj*adjacency + lambdaReg.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import torch

ROOT = Path(__file__).resolve().parents[2]
TOOL = Path(__file__).resolve().parent
if str(TOOL) not in sys.path:
    sys.path.insert(0, str(TOOL))
if str(ROOT / "tools/homm3_silhouette_pose_fit") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools/homm3_silhouette_pose_fit"))

from host_common import compute_camera_basis, gltf_to_blender_pos, alpha_loss, rasterize_cv2  # noqa: E402
from prepare_targets_v1 import prepare_job_targets_v1  # noqa: E402


# --------------------------------------------------------------- deformation

def part_rig_deform(verts, centroids, influence_parts, influence_weights, params, cam):
    """Deform welded mesh by rigid part transforms. Fully differentiable.
    verts (N,3) rest, centroids (P,3), influence (N,K) parts+weights,
    params (B, P*6) [u,v,d,rx,ry,rz], cam basis. Returns (B,N,3)."""
    B = params.shape[0]
    P = centroids.shape[0]
    N = verts.shape[0]
    K = influence_parts.shape[1]
    dev = verts.device
    dtype = verts.dtype
    pr = params.reshape(B, P, 6)
    u = pr[..., 0]; v = pr[..., 1]; d = pr[..., 2]
    rx = pr[..., 3]; ry = pr[..., 4]; rz = pr[..., 5]
    right = torch.tensor(cam["right"], device=dev, dtype=dtype)
    up = torch.tensor(cam["up"], device=dev, dtype=dtype)
    forward = torch.tensor(cam["forward"], device=dev, dtype=dtype)
    T = (right[None, None, :] * u[..., None]
         + up[None, None, :] * v[..., None]
         + forward[None, None, :] * d[..., None])  # (B,P,3)
    cx = torch.cos(rx); sx = torch.sin(rx)
    cy = torch.cos(ry); sy = torch.sin(ry)
    cz = torch.cos(rz); sz = torch.sin(rz)
    Rx = torch.zeros((B, P, 3, 3), device=dev, dtype=dtype)
    Rx[..., 0, 0] = 1
    Rx[..., 1, 1] = cx; Rx[..., 1, 2] = -sx; Rx[..., 2, 1] = sx; Rx[..., 2, 2] = cx
    Ry = torch.zeros((B, P, 3, 3), device=dev, dtype=dtype)
    Ry[..., 1, 1] = 1
    Ry[..., 0, 0] = cy; Ry[..., 0, 2] = sy; Ry[..., 2, 0] = -sy; Ry[..., 2, 2] = cy
    Rz = torch.zeros((B, P, 3, 3), device=dev, dtype=dtype)
    Rz[..., 2, 2] = 1
    Rz[..., 0, 0] = cz; Rz[..., 0, 1] = -sz; Rz[..., 1, 0] = sz; Rz[..., 1, 1] = cz
    R = torch.matmul(torch.matmul(Rz, Ry), Rx)  # (B,P,3,3)
    out = torch.zeros((B, N, 3), device=dev, dtype=dtype)
    for k in range(K):
        pk = influence_parts[:, k].clamp(min=0)
        wk = influence_weights[:, k]
        Rk = R[:, pk]          # (B,N,3,3)
        Tk = T[:, pk]          # (B,N,3)
        ck = centroids[pk]     # (N,3)
        diff = verts[None, :, :] - ck[None, :, :]
        rot = torch.einsum("bnj,bnij->bni", diff, Rk.transpose(-1, -2))
        vt = rot + ck[None, :, :] + Tk
        valid = ((influence_parts[:, k] >= 0) & (wk > 0)).float()[None, :, None]
        out += vt * valid
    return out


def posed_centroids(centroids, params, cam):
    """Centroids after their own part transform: c + t (rotation about own
    centroid leaves it fixed). params (B,P,6). Returns (B,P,3)."""
    B = params.shape[0]
    dev = params.device
    dtype = params.dtype
    right = torch.tensor(cam["right"], device=dev, dtype=dtype)
    up = torch.tensor(cam["up"], device=dev, dtype=dtype)
    forward = torch.tensor(cam["forward"], device=dev, dtype=dtype)
    pr = params.reshape(B, -1, 6)
    t = (right[None, None, :] * pr[..., 0, None]
         + up[None, None, :] * pr[..., 1, None]
         + forward[None, None, :] * pr[..., 2, None])
    return centroids[None] + t


def project_ortho(verts_b, cam, W, H):
    dev = verts_b.device
    dtype = verts_b.dtype
    cam_loc = torch.tensor(cam["cam_loc"], device=dev, dtype=dtype)
    right = torch.tensor(cam["right"], device=dev, dtype=dtype)
    up = torch.tensor(cam["up"], device=dev, dtype=dtype)
    ortho = float(cam["ortho"])
    aspect = H / float(W)
    rel = verts_b - cam_loc[None, None, :]
    xc = rel @ right
    yc = rel @ up
    px = (xc / ortho + 0.5) * W
    py = (-yc / (ortho * aspect) + 0.5) * H
    return torch.stack([px, py], dim=-1)


# ---------------------------------------------------------------- soft raster

# bucket by max(w,h) so the padded grid stays tight (exact per-pixel coverage)
BUCKETS = [4, 6, 8, 10, 12, 16, 20, 24, 32, 40, 48, 64, 96, 128, 192, 288]


def _bucket_id(sz):
    import bisect
    return bisect.bisect_left(BUCKETS, sz)


def soft_raster_batched(pts, faces, H, W, G=12, soft=0.4, chunk=4096):
    """Differentiable soft coverage raster with per-pixel-center sampling.

    For each triangle, sample every pixel center inside its screen bbox and
    compute signed edge distances (winding-corrected). Coverage ramps from 0
    (outside) to 1 (>= soft px inside). Sum-based union, clamp at 1.
    Pixel indices are detached (straight-through); coverage is smooth.
    Triangles are bucketed by bbox size so the padded grid is tight.
    """
    B = pts.shape[0]
    F = len(faces)
    dev = pts.device
    tri = pts[:, faces]  # (B,F,3,2)
    xmin = tri[..., 0].min(-1).values
    xmax = tri[..., 0].max(-1).values
    ymin = tri[..., 1].min(-1).values
    ymax = tri[..., 1].max(-1).values
    x0 = torch.floor(xmin).long()
    y0 = torch.floor(ymin).long()
    w = (torch.ceil(xmax).long() - x0).clamp(1, W)
    h = (torch.ceil(ymax).long() - y0).clamp(1, H)
    sz = torch.maximum(w, h)
    # bucket by the largest size across the batch so one face group serves all B
    sz_max = sz.max(dim=0).values  # (F,)
    mask_parts = []
    for bid, pmax in enumerate(BUCKETS):
        sel = (sz_max <= pmax) & (sz_max > (BUCKETS[bid - 1] if bid > 0 else 0))
        ids = torch.where(sel)[0]
        if len(ids) == 0:
            continue
        for f0 in range(0, len(ids), chunk):
            ids_c = ids[f0:f0 + chunk]
            C = len(ids_c)
            ix = x0[:, ids_c][..., None, None] + torch.arange(pmax, device=dev)[None, None, :, None]
            iy = y0[:, ids_c][..., None, None] + torch.arange(pmax, device=dev)[None, None, None, :]
            valid = (ix - x0[:, ids_c][..., None, None] < w[:, ids_c][..., None, None]) & \
                    (iy - y0[:, ids_c][..., None, None] < h[:, ids_c][..., None, None])
            px_ = ix + 0.5
            py_ = iy + 0.5
            p0 = tri[:, ids_c, 0]; p1 = tri[:, ids_c, 1]; p2 = tri[:, ids_c, 2]
            # winding: signed area per triangle -> flip edge test for CW
            area2 = ((p1[..., 0] - p0[..., 0]) * (p2[..., 1] - p0[..., 1])
                     - (p1[..., 1] - p0[..., 1]) * (p2[..., 0] - p0[..., 0]))  # (B,C)
            wind = torch.where(area2 >= 0, -1.0, 1.0)[..., None, None]

            def edge(pa, pb, pxx, pyy):
                ex = (pb[..., 0] - pa[..., 0])[..., None, None]
                ey = (pb[..., 1] - pa[..., 1])[..., None, None]
                ln = torch.sqrt((ex * ex + ey * ey).clamp(min=1e-12))
                return ((pxx - pa[..., 0, None, None]) * ey
                        - (pyy - pa[..., 1, None, None]) * ex) / ln

            e0 = edge(p0, p1, px_, py_) * wind
            e1 = edge(p1, p2, px_, py_) * wind
            e2 = edge(p2, p0, px_, py_) * wind
            cov = torch.clamp(torch.minimum(torch.minimum(e0, e1), e2) / soft, 0.0, 1.0)
            cov = cov * valid.float()
            px_i = ix.clamp(0, W - 1)
            py_i = iy.clamp(0, H - 1)
            idx = (py_i * W + px_i).reshape(B, -1)
            src = cov.reshape(-1)
            row = torch.arange(B, device=dev)[:, None]
            flat = (row * (H * W) + idx).reshape(-1)
            big = torch.zeros(B * H * W, device=dev)
            big = big.index_add(0, flat, src)
            mask_parts.append(big.view(B, H, W))
    if not mask_parts:
        return torch.zeros((B, H, W), device=dev)
    return sum(mask_parts).clamp(max=1.0)


# ------------------------------------------------------------------ losses

def build_losses(targets, edges, dts, params, buffers, cam, faces, H, W, cfg):
    B = params.shape[0]
    verts, centroids, iparts, iweights = buffers
    deformed = part_rig_deform(verts, centroids, iparts, iweights, params, cam)
    pts = project_ortho(deformed, cam, W, H)
    masks = soft_raster_batched(pts, faces, H, W)
    target = torch.from_numpy(targets).to(params.device)[None].expand(B, -1, -1)
    edge_t = torch.from_numpy(edges).to(params.device)[None].expand(B, -1, -1)
    dt_t = torch.from_numpy(dts).to(params.device)[None].expand(B, -1, -1)

    inter = (masks * target).sum(dim=(1, 2))
    union = (masks + target - masks * target).sum(dim=(1, 2)).clamp(min=1e-6)
    iou = inter / union
    loss_iou = 1.0 - iou

    if cfg["lambdaEdge"] > 0:
        kx = torch.tensor([[[-1, 0, 1], [-2, 0, 2], [-1, 0, 1]]], dtype=masks.dtype, device=params.device)[None]
        ky = torch.tensor([[[-1, -2, -1], [0, 0, 0], [1, 2, 1]]], dtype=masks.dtype, device=params.device)[None]
        pad = torch.nn.functional.pad(masks[:, None], (1, 1, 1, 1), mode="replicate")
        gx = torch.nn.functional.conv2d(pad, kx)
        gy = torch.nn.functional.conv2d(pad, ky)
        mag = torch.sqrt(gx * gx + gy * gy + 1e-8)
        pe = mag[:, 0] / mag.max().clamp(min=1e-6)
        loss_edge = ((pe - edge_t) ** 2).mean(dim=(1, 2))
    else:
        loss_edge = torch.zeros(B, device=params.device)

    if cfg["lambdaDt"] > 0:
        a = (masks * dt_t).sum(dim=(1, 2)) / masks.sum(dim=(1, 2)).clamp(min=1)
        b = (target * dt_t).sum(dim=(1, 2)) / target.sum(dim=(1, 2)).clamp(min=1)
        loss_dt = (a + b) / 2.0 / max(1.0, float(np.hypot(H, W)))
    else:
        loss_dt = torch.zeros(B, device=params.device)

    if cfg["lambdaAdj"] > 0 and cfg["adjPairs"]:
        pc = posed_centroids(centroids, params, cam)  # (B,P,3)
        adj_l = torch.zeros(B, device=params.device)
        for (a, b, rest_d) in cfg["adjPairs"]:
            d_now = torch.norm(pc[:, a] - pc[:, b], dim=-1)
            adj_l += (d_now - rest_d) ** 2
        loss_adj = adj_l / len(cfg["adjPairs"])
    else:
        loss_adj = torch.zeros(B, device=params.device)

    if cfg["lambdaReg"] > 0:
        loss_reg = (params ** 2).mean(dim=1)
    else:
        loss_reg = torch.zeros(B, device=params.device)

    loss = (loss_iou + cfg["lambdaEdge"] * loss_edge + cfg["lambdaDt"] * loss_dt
            + cfg["lambdaAdj"] * loss_adj + cfg["lambdaReg"] * loss_reg)
    return loss, iou, masks


def adam_step(params, grads, m, v, t, lr, b1=0.9, b2=0.999, eps=1e-8):
    m = b1 * m + (1 - b1) * grads
    v = b2 * v + (1 - b2) * grads ** 2
    mh = m / (1 - b1 ** t)
    vh = v / (1 - b2 ** t)
    return params - lr * mh / (torch.sqrt(vh) + eps), m, v


# ---------------------------------------------------------------- proxy mesh

def build_fit_proxy(verts, faces, iparts, iweights, n_parts, target_faces=12000):
    """Decimate the welded mesh into a fit proxy; propagate weld influence via
    nearest-vertex lookup. Returns (pv, pf, pip, piw) torch tensors (CPU)."""
    import fast_simplification as fs
    from scipy.spatial import cKDTree
    v = verts.astype(np.float64)
    f = faces.astype(np.int64)
    v2, f2 = fs.simplify(v, f, target_count=target_faces, agg=4.0)
    v2 = np.asarray(v2, dtype=np.float32)
    f2 = np.asarray(f2, dtype=np.int64)
    tree = cKDTree(v)
    _, nn = tree.query(v2, k=1)
    pip = iparts[nn].copy()
    piw = iweights[nn].copy()
    # renormalize weights
    s = piw.sum(1, keepdims=True)
    piw = piw / np.maximum(s, 1e-9)
    return v2, f2, pip, piw


# ----------------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--clips", type=str, default="death_g5")
    ap.add_argument("--gens", type=int, default=240)
    ap.add_argument("--restarts", type=int, default=12)
    ap.add_argument("--lr", type=float, default=0.02)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--proxy-faces", type=int, default=12000)
    ap.add_argument("--g", type=int, default=12)
    ap.add_argument("--device", type=str, default="cuda")
    ap.add_argument("--out-suffix", type=str, default="parts")
    args = ap.parse_args()

    t_start = time.perf_counter()
    device = args.device if torch.cuda.is_available() else "cpu"
    print(f"[parts] device {device} torch {torch.__version__}")

    parts_dir = ROOT / "artifacts/crusader_pose_pipeline/pseudo_rig/parts_rig"
    npz = np.load(parts_dir / "crusader_parts_rig.npz")
    meta = json.loads((parts_dir / "crusader_parts_rig.json").read_text())
    verts_n = npz["verts"].astype(np.float32)
    faces = npz["faces"].astype(np.int64)
    centroids = npz["centroids"].astype(np.float32)
    iparts = npz["influence_parts"].astype(np.int64)
    iweights = npz["influence_weights"].astype(np.float32)
    n_parts = centroids.shape[0]
    # drop zero-area triangles (welded cap slivers) for raster robustness
    a = verts_n[faces[:, 0]]; b = verts_n[faces[:, 1]]; c = verts_n[faces[:, 2]]
    area = 0.5 * np.linalg.norm(np.cross(b - a, c - a), axis=1)
    keep = area > 1e-9
    if not keep.all():
        print(f"[parts] dropping {int((~keep).sum())} zero-area tris")
        faces = faces[keep]
    print(f"[parts] full mesh {verts_n.shape} faces {faces.shape} parts {n_parts}")

    # fit proxy (decimated)
    pv, pf, pip, piw = build_fit_proxy(verts_n, faces, iparts, iweights, n_parts,
                                       target_faces=args.proxy_faces)
    print(f"[parts] proxy {pv.shape} faces {pf.shape}")

    # Blender Z-up
    verts_full = torch.from_numpy(gltf_to_blender_pos(verts_n)).to(device)
    verts = torch.from_numpy(gltf_to_blender_pos(pv)).to(device)
    c = torch.from_numpy(gltf_to_blender_pos(centroids).astype(np.float32)).to(device)
    ip_full = torch.from_numpy(iparts).to(device)
    iw_full = torch.from_numpy(iweights).to(device)
    ip = torch.from_numpy(pip).to(device)
    iw = torch.from_numpy(piw).to(device)

    # job + targets
    job = json.loads((ROOT / "tools/homm3_pseudo_rig/configs/h3_crusader_split_death_bold.json").read_text())
    clip_ids = [x.strip() for x in args.clips.split(",")]
    frames = [f for f in job["frames"] if str(f.get("clipId")) in clip_ids]
    job2 = dict(job)
    job2["frames"] = frames
    job2["clipId"] = ",".join(clip_ids)
    out_dir = ROOT / "artifacts/crusader_pose_pipeline/pseudo_rig" / f"out_fit_{args.out_suffix}_{args.clips}"
    out_dir.mkdir(parents=True, exist_ok=True)
    job2["outputDir"] = str(out_dir)
    for fr in job2["frames"]:
        p = Path(fr["path"])
        fr["path"] = str(p if p.is_absolute() else (ROOT / p).resolve())
    (out_dir / "job.parts.json").write_text(json.dumps(job2, indent=2), encoding="utf-8")
    prepare_job_targets_v1(job2, force=False)

    target_dir = out_dir / "targets"
    n_frames = len(frames)
    targets, edges, dts = [], [], []
    from scipy.ndimage import distance_transform_edt
    for i in range(n_frames):
        targets.append(np.load(target_dir / f"target_{i:02d}.npy").astype(np.float32))
        edges.append(np.load(target_dir / f"edge_{i:02d}.npy").astype(np.float32))
        t = targets[-1]
        dts.append(distance_transform_edt(1 - (t > 0.5).astype(np.uint8)).astype(np.float32))

    cam = compute_camera_basis(job2)
    cam["ortho"] = float(job2["camera"]["orthoScale"])
    W = int(job2["render"]["width"])
    H = int(job2["render"]["height"])

    loss_cfg = job2.get("loss") or {}
    cfg = {
        "lambdaEdge": float(loss_cfg.get("lambdaEdge", 0.9)),
        "lambdaDt": float(loss_cfg.get("lambdaDt", 1.3)),
        "lambdaAdj": float(loss_cfg.get("lambdaAdj", 2.0)),
        "lambdaReg": float(loss_cfg.get("lambdaReg", 0.02)),
        "adjPairs": [(a, b, r) for (a, b, r) in meta.get("adjacentPairs", [])],
    }
    dof = job2.get("dof") or {}
    plane_b = float(dof.get("planeTranslateBound", 0.35))
    depth_b = float(dof.get("depthTranslateBound", 0.06))
    rot_b = float(dof.get("rotateBoundRad", 0.61))
    bounds = []
    for _ in range(n_parts):
        bounds.extend([(-plane_b, plane_b), (-plane_b, plane_b), (-depth_b, depth_b),
                       (-rot_b, rot_b), (-rot_b, rot_b), (-rot_b, rot_b)])
    lo = torch.tensor([b[0] for b in bounds], device=device)
    hi = torch.tensor([b[1] for b in bounds], device=device)

    buffers = (verts, c, ip, iw)
    buffers_full = (verts_full, c, ip_full, iw_full)
    faces_np = pf
    faces_full_np = faces

    rng = np.random.default_rng(args.seed)
    B = args.restarts
    poses = []
    ious_hist = []
    x_prev = torch.zeros((B, n_parts * 6), device=device)
    for fi in range(n_frames):
        t0 = time.perf_counter()
        x = x_prev.clone()
        if fi > 0:
            noise = torch.empty_like(x).uniform_(0, 1)
            x = x + (noise - 0.5) * (hi - lo) * 0.4
        x = x.clamp(lo, hi)
        # persistent leaf tensor: grad accumulates into x.grad, updates via .data
        x = x.detach().requires_grad_(True)
        m = torch.zeros_like(x)
        v = torch.zeros_like(x)
        best_iou = 0.0
        best_x = x.detach().clone()
        for g in range(args.gens):
            if x.grad is not None:
                x.grad.zero_()
            loss, iou, _ = build_losses(targets[fi], edges[fi], dts[fi],
                                        x, buffers, cam, faces_np, H, W, cfg)
            loss.sum().backward()
            with torch.no_grad():
                grad = torch.nan_to_num(x.grad, 0.0, 0.0, 0.0)
                # adam on x.data, then reattach leaf
                new_x, m, v = adam_step(x, grad, m, v, float(g + 1), args.lr)
                x = new_x.detach().clamp(lo, hi).requires_grad_(True)
                bi = int(iou.detach().argmax().item())
                if float(iou[bi].detach()) > best_iou:
                    best_iou = float(iou[bi].detach())
                    best_x = x[bi].detach().clone()
            if g % 40 == 0 or g == args.gens - 1:
                print(f"  frame {fi} gen {g} bestIoU {best_iou:.4f} "
                      f"meanIoU {float(iou.mean().detach()):.4f} ({time.perf_counter()-t0:.1f}s)", flush=True)
        # exact eval on FULL mesh
        with torch.no_grad():
            deformed = part_rig_deform(verts_full, c, ip_full, iw_full, best_x[None], cam)
            pts = project_ortho(deformed, cam, W, H)
            pts_np = pts[0].detach().cpu().numpy()
            mask = rasterize_cv2(pts_np, faces_full_np, H, W)
            _, exact_iou = alpha_loss(mask, targets[fi])
        print(f"[parts] frame {fi} final exact IoU {exact_iou:.4f}", flush=True)
        poses.append(best_x.cpu().numpy())
        ious_hist.append(exact_iou)
        x_prev = best_x[None].repeat(B, 1)
        poses_dir = out_dir / "poses_parts"
        poses_dir.mkdir(parents=True, exist_ok=True)
        np.save(poses_dir / f"pose_{fi:03d}.npy", best_x.cpu().numpy().astype(np.float64))
        from PIL import Image
        Image.fromarray((mask * 255).astype(np.uint8)).save(out_dir / f"_parts_frame{fi}.png")

    # GIF
    from PIL import Image
    gifs = out_dir / "gifs_parts"
    gifs.mkdir(parents=True, exist_ok=True)
    frames_im = []
    for fi in range(n_frames):
        t = targets[fi]
        p = np.array(Image.open(out_dir / f"_parts_frame{fi}.png").convert("L")) / 255.0
        h, w = t.shape
        canvas = Image.new("RGB", (w * 2, h), (0, 0, 0))
        canvas.paste(Image.fromarray((t * 255).astype(np.uint8), mode="L").convert("RGB"), (0, 0))
        canvas.paste(Image.fromarray((p * 255).astype(np.uint8), mode="L").convert("RGB"), (w, 0))
        frames_im.append(canvas)
    gif_path = gifs / f"{clip_ids[0]}_parts.gif"
    frames_im[0].save(gif_path, save_all=True, append_images=frames_im[1:], duration=180, loop=0)
    print(f"[parts] gif {gif_path} ious {[round(x, 3) for x in ious_hist]}")

    report = {
        "schema": "homm3_pseudo_rig_fit_report.v2_parts",
        "frameCount": n_frames, "parts": n_parts, "dofPerPart": 6,
        "restarts": B, "gens": args.gens, "proxyFaces": args.proxy_faces,
        "iouPerFrame": [round(x, 4) for x in ious_hist],
        "meanIoU": round(float(np.mean(ious_hist)), 4),
        "gif": str(gif_path),
        "proof": "generated-artifact — part-rig Adam fit; not OE runtime",
        "runtimeS": round(time.perf_counter() - t_start, 1),
    }
    (out_dir / "fit_report_parts.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
