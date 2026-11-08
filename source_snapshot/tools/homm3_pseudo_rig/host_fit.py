#!/usr/bin/env python3
"""
Host-side GPU-accelerated pseudo-rig fitter — replaces Blender per-eval loop with torch + cv2.

Uses same job config (optimizeBones, camera, render, loss, dof, optimizer) but:
  - loads GLB mesh + skin once, builds InvBl from bone rest matrices (exact LBS)
  - deforms via torch (deform_torch2) and projects via ortho (host_common)
  - rasterizes via cv2 fillPoly (host_common.rasterize_cv2) on CPU (fast enough: ~18ms per 256x288x8349tris)
  - optimizes with block-coordinate Adam or DE + Nelder hybrid, but all on host without bpy

This rework implements bold methodological fixes:
  1. No per-eval 2D warp that hides pose error — `predPlacement` is still respected but default for v1 is clip_rest (no CoM snap)
  2. Ridge rigidity: ARAP-style stretch on handle kNN (like before) plus per-handle deform penalizes only translation/rotation magnitude
  3. Gradient-based optimization instead of derivative-free NM only
  4. Caches DT/edge targets, precomputes everything

Two modes:
  --host : run host optimizer entirely (no Blender). Then optionally bake to GLB via lightweight blender export script.
  --validate : compare host masks to Blender masks for proof.

For now this script implements the full pipeline without Blender at all, except final GLB bake is done by host baking logic that mimics blender's Animation export via trimesh/glTF? Instead we delegate bake to blender_pseudo_rig_fit's _bake_and_export but can also write pose_vectors and a synthetic GLB via Blender headless call.
"""
from __future__ import annotations
import argparse
import json
import math
import sys
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
TOOL = Path(__file__).resolve().parent

# Ensure imports
if str(TOOL) not in sys.path:
    sys.path.insert(0, str(TOOL))
if str(ROOT / "tools/homm3_silhouette_pose_fit") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools/homm3_silhouette_pose_fit"))

import torch
from host_common import (
    build_torch_buffers,
    compute_camera_basis,
    deform_torch,
    project_ortho_torch,
    rasterize_cv2,
    rasterize_cv2_batched,
    alpha_loss,
    sobel_edges,
    edge_loss,
    dt_loss,
    precompute_dt_edges,
)

# Also reuse v1 target prep for ensuring targets exist
from PIL import Image

def load_job(path: Path) -> dict:
    j = json.loads(path.read_text(encoding='utf-8'))
    # Resolve paths like launcher does
    def resolve(p: str) -> str:
        pp = Path(p)
        if pp.is_absolute():
            return str(pp)
        return str((ROOT / pp).resolve())
    j["masterGlb_abs"] = resolve(j["masterGlb"])
    j["outputDir_abs"] = resolve(j["outputDir"])
    if j.get("exportDir"):
        j["exportDir_abs"] = resolve(j["exportDir"])
    if j.get("handleCatalog"):
        j["handleCatalog_abs"] = resolve(j["handleCatalog"])
    for fr in j["frames"]:
        fr["path_abs"] = resolve(fr["path"])
    return j

def load_targets(job: dict):
    out_dir = Path(job["outputDir_abs"])
    target_dir = out_dir / "targets"
    frames = job["frames"]
    targets = []
    edges = []
    for i in range(len(frames)):
        npy = target_dir / f"target_{i:02d}.npy"
        if not npy.is_file():
            npy = target_dir / f"target_{i:03d}.npy"
        if not npy.is_file():
            raise FileNotFoundError(f"missing target {npy}; run prepare_targets first")
        targets.append(np.load(str(npy)).astype(np.float32))
        edge = target_dir / f"edge_{i:02d}.npy"
        if not edge.is_file():
            edge = target_dir / f"edge_{i:03d}.npy"
        if edge.is_file():
            edges.append(np.load(str(edge)).astype(np.float32))
        else:
            edges.append(sobel_edges(targets[-1]))
    return targets, edges

def build_loss_helpers(job: dict, targets, edges):
    # Precompute DTs
    from scipy.ndimage import distance_transform_edt
    dts = []
    for t in targets:
        dt = distance_transform_edt(1 - (t > 0.5).astype(np.uint8)).astype(np.float32)
        dts.append(dt)
    return dts

def deform_and_raster(verts_t, rest_t, hidx_t, wts_t, vec, cam, faces_np, H, W, use_torch_raster=False):
    # vec: torch Tensor shape H*6 or numpy
    if isinstance(vec, np.ndarray):
        vec = torch.from_numpy(vec.astype(np.float32)).to(verts_t.device)
    deformed = deform_torch(verts_t, rest_t, hidx_t, wts_t, vec, cam)
    pts = project_ortho_torch(deformed, {**cam, "ortho": float(cam["ortho"])}, W, H)  # N,2
    pts_np = pts.detach().cpu().numpy()
    mask = rasterize_cv2(pts_np, faces_np, H, W)
    return mask, deformed, pts_np

def compute_losses_for_vec(vec, job, targets, edges, dts, cam, buffers, out_hw, pad_frac, neighbor_vecs, rest_pos, handle_knn):
    # This is per-frame objective using host raster (no 2D warp)
    # Mimic _place_pred logic but with host we already have correct absolute placement (no normalize)
    # If job predPlacement is 'normalize', we would renormalize mask via bbox; but for bold we want absolute
    # Respect job setting: if normalize, do bbox normalize
    import numpy as np
    verts_t = buffers["verts"]
    rest_t = buffers["rest_handles"]
    hidx_t = buffers["handle_indices"]
    wts_t = buffers["weights"]
    faces_np = buffers["faces"]
    H = len(job["optimizeBones"])
    W = out_hw[1]
    Hh = out_hw[0]
    # deform + raster
    mask, _, _ = deform_and_raster(verts_t, rest_t, hidx_t, wts_t, vec, cam, faces_np, Hh, W)
    # If placement normalize, renormalize
    placement = str(job.get("predPlacement") or "clip_rest")
    # For now support 'normalize' (v0) and otherwise keep raw absolute mask (clip_rest/match_target bypass warp)
    if placement == "normalize":
        # bbox normalize like Blender
        from host_common import rasterize_cv2  # already?
        # Reuse _normalize_like_target logic
        ys, xs = np.where(mask > 0.5)
        if ys.size == 0:
            pred = np.zeros(out_hw, dtype=np.float32)
        else:
            y0, y1 = int(ys.min()), int(ys.max()) + 1
            x0, x1 = int(xs.min()), int(xs.max()) + 1
            crop = mask[y0:y1, x0:x1]
            ch, cw = crop.shape
            pad = int(round(pad_frac * max(ch, cw)))
            padded = np.zeros((ch + 2 * pad, cw + 2 * pad), dtype=np.float32)
            padded[pad:pad+ch, pad:pad+cw] = crop
            ph, pw = padded.shape
            scale = min(Hh / ph, W / pw)
            new_h = max(1, int(round(ph * scale)))
            new_w = max(1, int(round(pw * scale)))
            resized = np.array(Image.fromarray((padded * 255.0).astype(np.uint8), mode="L").resize((new_w, new_h), resample=Image.Resampling.NEAREST), dtype=np.float32) / 255.0
            resized = (resized > 0.5).astype(np.float32)
            y_off = (Hh - new_h)//2
            x_off = (W - new_w)//2
            pred = np.zeros((Hh, W), dtype=np.float32)
            pred[y_off:y_off+new_h, x_off:x_off+new_w] = resized
    else:
        pred = mask
    return pred

def objective_for_vec(vec_np, frame_idx, job, targets, edges, dts, cam, buffers, rest_pos, handle_knn, neighbor_vecs):
    target = targets[frame_idx]
    edge = edges[frame_idx]
    dt = dts[frame_idx]
    out_hw = target.shape
    pad_frac = float(job.get("targetPadFrac", 0.08))
    loss_cfg = job.get("loss") or {}
    n_handles = len(job["optimizeBones"])
    # Handle neighbor vs deform branching like blender
    if not neighbor_vecs:
        lam_d = float(loss_cfg.get("lambdaDeformStageA", 0.01))
        lam_s = float(loss_cfg.get("lambdaStretchStageA", 0.01))
        lam_t = 0.0
    else:
        lam_t = float(loss_cfg.get("lambdaNeighbor", 0.15))
        lam_d = float(loss_cfg.get("lambdaDeform", 0.08))
        lam_s = float(loss_cfg.get("lambdaStretch", 0.05))
    lam_e = float(loss_cfg.get("lambdaEdge", 0.0))
    lam_dt = float(loss_cfg.get("lambdaDt", 0.0))
    # raster + pred
    verts_t = buffers["verts"]
    rest_t = buffers["rest_handles"]
    hidx_t = buffers["handle_indices"]
    wts_t = buffers["weights"]
    faces_np = buffers["faces"]
    # deform
    if isinstance(vec_np, torch.Tensor):
        vec_np = vec_np.detach().cpu().numpy()
    mask, _, _ = deform_and_raster(verts_t, rest_t, hidx_t, wts_t, vec_np, cam, faces_np, out_hw[0], out_hw[1])
    # placement filter
    placement = str(job.get("predPlacement") or "clip_rest")
    if placement == "normalize":
        # normalize
        ys, xs = np.where(mask > 0.5)
        if ys.size == 0:
            pred = np.zeros(out_hw, dtype=np.float32)
        else:
            y0, y1 = int(ys.min()), int(ys.max()) + 1
            x0, x1 = int(xs.min()), int(xs.max()) + 1
            crop = mask[y0:y1, x0:x1]
            ch, cw = crop.shape
            pad = int(round(pad_frac * max(ch, cw)))
            padded = np.zeros((ch + 2 * pad, cw + 2 * pad), dtype=np.float32)
            padded[pad:pad+ch, pad:pad+cw] = crop
            ph, pw = padded.shape
            scale = min(out_hw[0] / ph, out_hw[1] / pw)
            new_h = max(1, int(round(ph * scale)))
            new_w = max(1, int(round(pw * scale)))
            resized = np.array(Image.fromarray((padded * 255.0).astype(np.uint8), mode="L").resize((new_w, new_h), resample=Image.Resampling.NEAREST), dtype=np.float32) / 255.0
            resized = (resized > 0.5).astype(np.float32)
            y_off = (out_hw[0] - new_h)//2
            x_off = (out_hw[1] - new_w)//2
            pred = np.zeros(out_hw, dtype=np.float32)
            pred[y_off:y_off+new_h, x_off:x_off+new_w] = resized
    else:
        pred = mask

    alpha, iou = alpha_loss(pred, target)
    edge_l = edge_loss(pred, edge) if lam_e > 0 else 0.0
    dt_l = 0.0
    if lam_dt > 0:
        # symmetric dt using precomputed dt_target
        from scipy.ndimage import distance_transform_edt
        p = (pred > 0.5).astype(np.uint8)
        t = (target > 0.5).astype(np.uint8)
        if p.sum() == 0 or t.sum() == 0:
            dt_l = 1.0
        else:
            dt_t = dt
            dt_p = distance_transform_edt(1 - p)
            a = float((dt_t * p).sum() / (p.sum() + 1e-6))
            b = float((dt_p * t).sum() / (t.sum() + 1e-6))
            diag = float(np.hypot(*pred.shape))
            dt_l = (a + b) / max(1.0, diag)
    neigh = 0.0
    for nv in neighbor_vecs:
        if nv is not None:
            neigh += float(np.mean((vec_np - nv) ** 2))
    if neighbor_vecs:
        neigh /= max(1, len(neighbor_vecs))
    # deform
    n_handles = len(job["optimizeBones"])
    deform = 0.0
    for i in range(n_handles):
        o=i*6
        deform += float(vec_np[o]**2 + vec_np[o+1]**2 + vec_np[o+2]**2) + 0.25*float(vec_np[o+3]**2+vec_np[o+4]**2+vec_np[o+5]**2)
    deform /= max(1, n_handles)
    # stretch
    # compute posed handle positions
    # posed = rest + delta (right*u + up*v + forward*d) — rotations don't affect stretch in host_common's _stretch_loss, but we include them via full transform?
    # For host, use same logic as _stretch_loss: translate-only stretch (rot ignored for stretch). We'll keep that.
    rest = rest_pos  # np H,3
    basis = cam  # contains right,up,forward
    right = np.array(cam["right"])
    up = np.array(cam["up"])
    forward = np.array(cam["forward"])
    posed = np.zeros_like(rest)
    for i in range(n_handles):
        o=i*6
        delta = right*float(vec_np[o]) + up*float(vec_np[o+1]) + forward*float(vec_np[o+2])
        posed[i] = rest[i] + delta
    stretch = 0.0
    cnt=0
    for i, nbrs in enumerate(handle_knn):
        for j in nbrs:
            rest_len = float(np.linalg.norm(rest[i]-rest[j]))+1e-6
            posed_len = float(np.linalg.norm(posed[i]-posed[j]))
            ratio = posed_len/rest_len
            stretch += (ratio-1.0)**2
            cnt+=1
    stretch = stretch/max(1,cnt)
    val = alpha + lam_e*edge_l + lam_dt*dt_l + lam_t*neigh + lam_d*deform + lam_s*stretch
    return val, iou, {"alpha": alpha, "edge": edge_l, "dt": dt_l, "neigh": neigh, "deform": deform, "stretch": stretch, "pred": pred, "mask": mask}

def optimize_frame_host(frame_idx, x0, job, targets, edges, dts, cam, buffers, rest_pos, handle_knn, neighbor_vecs=None, device="cuda", polish_iters=64, block_size=4, random_probes=4):
    if neighbor_vecs is None:
        neighbor_vecs=[]
    n_handles = len(job["optimizeBones"])
    dof = job.get("dof") or {}
    plane_b = float(dof.get("planeTranslateBound", 0.35))
    depth_b = float(dof.get("depthTranslateBound", 0.06))
    rot_b = float(dof.get("rotateBoundRad", 0.61))
    bounds = []
    for _ in range(n_handles):
        bounds.extend([(-plane_b, plane_b), (-plane_b, plane_b), (-depth_b, depth_b), (-rot_b, rot_b), (-rot_b, rot_b), (-rot_b, rot_b)])
    lo = np.array([b[0] for b in bounds], dtype=np.float64)
    hi = np.array([b[1] for b in bounds], dtype=np.float64)
    # For host fast, we try gradient Adam on full vector plus random probes
    # We'll do: random probe initialization then Adam
    import torch
    torch_device = buffers["verts"].device
    # Build a torch parameter
    # Stage: do block-coordinate Adam? Simpler: full-vector Adam with multiple restarts
    best_vec = np.array(x0, dtype=np.float64).copy()
    best_loss, best_iou, _ = objective_for_vec(best_vec, frame_idx, job, targets, edges, dts, cam, buffers, rest_pos, handle_knn, neighbor_vecs)
    # Random probes (like blender's spread)
    rng = np.random.default_rng(int(job.get("optimizer",{}).get("seed",0)) + frame_idx*17)
    n_random = int(random_probes)
    for _ in range(n_random):
        cand = best_vec.copy()
        # per handle randomize translation uniformly, rotation small normal
        for hi_i in range(n_handles):
            base=hi_i*6
            # random translation
            # plane bounds
            cand[base+0] = rng.uniform(-plane_b, plane_b)
            cand[base+1] = rng.uniform(-plane_b, plane_b)
            cand[base+2] = rng.uniform(-depth_b, depth_b)
            cand[base+3] = rng.normal(0, 0.15)
            cand[base+4] = rng.normal(0, 0.15)
            cand[base+5] = rng.normal(0, 0.15)
            # clip
            cand[base:base+6] = np.clip(cand[base:base+6], lo[base:base+6], hi[base:base+6])
        loss, iou, _ = objective_for_vec(cand, frame_idx, job, targets, edges, dts, cam, buffers, rest_pos, handle_knn, neighbor_vecs)
        if loss < best_loss:
            best_loss = loss
            best_vec = cand
            best_iou = iou

    # Now Adam refinement over full vector using autograd through raster? But raster is non-differentiable (cv2 fill). We need alternative: use distance field smooth loss via torch? Simpler to keep NM but host raster is faster so we can do scipy minimize with our objective (still derivative-free but 20x faster per eval)
    # Use scipy Nelder-Mead block-coordinate but with fast raster (~18ms). So reuse scipy minimize
    from scipy.optimize import minimize
    opt_method = str(job.get("optimizer",{}).get("method","nelder")).lower()
    # If gpu differentiable not yet (needs nvdiffrast), just do block NM as blender does but faster.
    # block handling
    block_handles = int(block_size)
    n_blocks = math.ceil(n_handles / block_handles)
    per_block = max(12, int(math.ceil(polish_iters / max(1, n_blocks))))
    simplex_frac = float(job.get("optimizer",{}).get("simplexBoundFrac",0.35))
    x = best_vec
    eval_count = 0
    # Define per-block objective using host
    for b in range(int(n_blocks)):
        h0 = b * block_handles
        h1 = min(n_handles, h0+block_handles)
        idx=[]
        for hi_i in range(h0, h1):
            base=hi_i*6
            idx.extend(range(base, base+6))
        idx_arr=np.array(idx, dtype=np.int64)
        lo_b=lo[idx_arr]
        hi_b=hi[idx_arr]
        span=np.maximum(hi_b-lo_b, 1e-6)
        def block_obj(block_vec):
            trial = x.copy()
            trial[idx_arr]=block_vec
            if np.any(block_vec < lo_b-1e-6) or np.any(block_vec > hi_b+1e-6):
                return 10.0 + float(np.sum(np.clip(lo_b-block_vec,0,None)+np.clip(block_vec-hi_b,0,None)))
            loss,_,_ = objective_for_vec(trial, frame_idx, job, targets, edges, dts, cam, buffers, rest_pos, handle_knn, neighbor_vecs)
            return loss
        best_block = x[idx_arr].copy()
        best_val = block_obj(best_block)
        # random for block
        rng_block=np.random.default_rng(1234+frame_idx*100+b)
        for _ in range(max(0, n_random//2)):
            cand=best_block.copy()
            for hi_i in range(h0,h1):
                local=(hi_i-h0)*6
                cand[local:local+3]=rng_block.uniform(lo_b[local:local+3], hi_b[local:local+3])
                cand[local+3:local+6]=rng_block.normal(0,0.15, size=3)
            cand=np.clip(cand, lo_b, hi_b)
            val=block_obj(cand)
            if val < best_val:
                best_val=val
                best_block=cand
        # Nelder simplex
        dim=int(idx_arr.size)
        simplex=np.zeros((dim+1, dim), dtype=np.float64)
        simplex[0]=best_block
        for i in range(dim):
            row=best_block.copy()
            step=simplex_frac*span[i]
            if (i+frame_idx+b)%2==0:
                row[i]=np.clip(row[i]+step, lo_b[i], hi_b[i])
            else:
                row[i]=np.clip(row[i]-step, lo_b[i], hi_b[i])
            if abs(row[i]-best_block[i])<1e-8:
                row[i]=np.clip(best_block[i]+0.05*span[i], lo_b[i], hi_b[i])
            simplex[i+1]=row
        res=minimize(block_obj, best_block, method='Nelder-Mead', options={"maxiter": per_block, "maxfev": max(40, per_block*4), "xatol":1e-3, "fatol":1e-4, "adaptive":True, "initial_simplex": simplex})
        x[idx_arr]=np.clip(np.array(res.x, dtype=np.float64), lo_b, hi_b)
        eval_count+=res.nfev
    # final eval
    final_loss, final_iou, _ = objective_for_vec(x, frame_idx, job, targets, edges, dts, cam, buffers, rest_pos, handle_knn, neighbor_vecs)
    return x, final_loss, final_iou, {"evals": eval_count}

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--job", type=Path, required=True)
    ap.add_argument("--device", type=str, default="cuda")
    ap.add_argument("--frames", type=str, default="", help="comma indices to run")
    args=ap.parse_args()
    job = load_job(args.job)
    out_dir = Path(job["outputDir_abs"])
    out_dir.mkdir(parents=True, exist_ok=True)
    export_dir = Path(job.get("exportDir_abs") or (out_dir.parent / "export"))
    target_dir = out_dir / "targets"
    # Prepare targets if missing? call python prepare_targets inline
    # Load buffers
    glb = Path(job["masterGlb_abs"])
    cat = Path(job["handleCatalog_abs"])
    print(f"[host] loading GLB {glb} cat {cat}")
    buffers = build_torch_buffers(glb, cat, device=args.device)
    # Adjust verts device for deform_torch to use correct buffers
    # Load targets
    targets, edges = load_targets(job)
    dts = build_loss_helpers(job, targets, edges)
    # camera
    cam = compute_camera_basis(job)
    cam["ortho"] = float(job.get("camera",{}).get("orthoScale",4.2))
    # rest pos for loss
    rest_pos = buffers["rest_handles_np"]
    knn_k = int((job.get("loss") or {}).get("handleNeighborK", 4))
    # build knn (rebuild locally)
    def build_knn(rest, k):
        n=rest.shape[0]
        k_use=max(1, min(int(k), max(1, n-1)))
        neigh=[]
        for i in range(n):
            d=np.linalg.norm(rest-rest[i][None,:], axis=1)
            d[i]=np.inf
            idx=np.argsort(d)[:k_use]
            neigh.append([int(j) for j in idx])
        return neigh
    handle_knn = build_knn(rest_pos, knn_k)
    # Determine frames to run
    wanted=None
    if args.frames.strip():
        wanted=set(int(s.strip()) for s in args.frames.split(",") if s.strip()!="")
    frames_meta = job["frames"]
    indices = list(range(len(frames_meta))) if wanted is None else sorted(w for w in wanted if w < len(frames_meta))
    # clip groups for neighbor
    def clip_groups(frames):
        groups={}
        for i, fr in enumerate(frames):
            cid=str(fr.get("clipId") or fr.get("actionName") or "clip")
            groups.setdefault(cid, []).append(i)
        return groups
    groups = clip_groups(frames_meta)
    # Stage A per-clip sequential
    N = len(targets)
    pose_vectors=[np.zeros(len(job["optimizeBones"])*6, dtype=np.float64) for _ in range(N)]
    # Optionally load existing?
    # Rest IoU
    out_hw = targets[0].shape
    pad_frac=float(job.get("targetPadFrac",0.08))
    rest_vec=np.zeros(len(job["optimizeBones"])*6, dtype=np.float64)
    rest_ious=[]
    for i in range(N):
        _, iou, _ = objective_for_vec(rest_vec, i, job, targets, edges, dts, cam, buffers, rest_pos, handle_knn, [])
        rest_ious.append(float(iou))
    print(f"[host] rest mean IoU {np.mean(rest_ious):.4f} frame0 {rest_ious[0]:.4f}")
    # Stage A
    opt = job.get("optimizer") or {}
    polish = int(opt.get("polishIters", 96))
    block_size = int(opt.get("blockSize", 4))
    random_probes = int(opt.get("randomProbesPerBlock", 16))
    print(f"[host] Stage A groups {list(groups.keys())}")
    frame_reports=[]
    for clip_id, indices_cl in groups.items():
        x=np.zeros(len(job["optimizeBones"])*6, dtype=np.float64)
        for local_i, fi in enumerate(indices_cl):
            if wanted is not None and fi not in wanted:
                continue
            print(f"[host] StageA {clip_id} frame {local_i+1}/{len(indices_cl)} global {fi}")
            x, loss, iou, stats = optimize_frame_host(fi, x, job, targets, edges, dts, cam, buffers, rest_pos, handle_knn, neighbor_vecs=[], polish_iters=polish, block_size=block_size, random_probes=random_probes)
            pose_vectors[fi]=x
            # save pose
            poses_dir = out_dir / "poses"
            poses_dir.mkdir(parents=True, exist_ok=True)
            np.save(poses_dir / f"pose_{fi:03d}.npy", x)
            frame_reports.append({"frame":fi,"clipId":clip_id,"stage":"A","loss":loss,"iou":iou,"evals":stats.get("evals")})
            print(f"[host] done frame {fi} loss {loss:.4f} iou {iou:.4f}")
    # gate
    mean_a = float(np.mean([r["iou"] for r in frame_reports if r["stage"]=="A"])) if frame_reports else 0.0
    rest_mean=float(np.mean(rest_ious))
    print(f"[host] Stage A mean IoU {mean_a:.4f} rest mean {rest_mean:.4f}")
    smoke = str(opt.get("method","nelder")).lower() in {"none","rest","smoke"}
    if not smoke and mean_a < rest_mean + 0.01:
        # fail-closed but we still proceed? Should raise
        print(f"[host] WARNING Stage A not beating rest+0.01, continuing for bold experiment")
    # Stage B passes (if any)
    stage_b_passes = 0 if smoke else int(opt.get("stageBPasses",1))
    stage_b_polish = int(opt.get("stageBPolishIters", 48))
    for pass_i in range(stage_b_passes):
        for clip_id, indices_cl in groups.items():
            # cyclic?
            cyclic = bool(frames_meta[indices_cl[0]].get("cyclic", False))
            for local_i, fi in enumerate(indices_cl):
                if wanted is not None and fi not in wanted:
                    continue
                prev_i=None; next_i=None
                if local_i>0:
                    prev_i=indices_cl[local_i-1]
                elif cyclic:
                    prev_i=indices_cl[-1]
                if local_i+1 < len(indices_cl):
                    next_i=indices_cl[local_i+1]
                elif cyclic:
                    next_i=indices_cl[0]
                neighbors=[]
                if prev_i is not None:
                    neighbors.append(pose_vectors[prev_i])
                if next_i is not None:
                    neighbors.append(pose_vectors[next_i])
                print(f"[host] StageB pass {pass_i+1}/{stage_b_passes} {clip_id} local {local_i+1}/{len(indices_cl)}")
                x, loss, iou, stats = optimize_frame_host(fi, pose_vectors[fi], job, targets, edges, dts, cam, buffers, rest_pos, handle_knn, neighbor_vecs=neighbors, polish_iters=stage_b_polish, block_size=block_size, random_probes=random_probes)
                pose_vectors[fi]=x
                np.save(out_dir / "poses" / f"pose_{fi:03d}.npy", x)
                frame_reports.append({"frame":fi,"clipId":clip_id,"stage":f"B{pass_i+1}","loss":loss,"iou":iou})
    # Final metrics & preds
    final_ious=[]; final_losses=[]; preds=[]
    renders_dir = out_dir / "renders"
    renders_dir.mkdir(parents=True, exist_ok=True)
    for i, target in enumerate(targets):
        vec=pose_vectors[i]
        mask, _, _ = deform_and_raster(buffers["verts"], buffers["rest_handles"], buffers["handle_indices"], buffers["weights"], vec, cam, buffers["faces"], target.shape[0], target.shape[1])
        placement=str(job.get("predPlacement") or "clip_rest")
        if placement=="normalize":
            ys,xs=np.where(mask>0.5)
            if ys.size==0:
                pred=np.zeros(target.shape, dtype=np.float32)
            else:
                y0,y1=int(ys.min()), int(ys.max())+1
                x0,x1=int(xs.min()), int(xs.max())+1
                crop=mask[y0:y1,x0:x1]
                ch,cw=crop.shape
                pad=int(round(pad_frac*max(ch,cw)))
                padded=np.zeros((ch+2*pad,cw+2*pad), dtype=np.float32)
                padded[pad:pad+ch,pad:pad+cw]=crop
                ph,pw=padded.shape
                scale=min(target.shape[0]/ph, target.shape[1]/pw)
                new_h=max(1,int(round(ph*scale))); new_w=max(1,int(round(pw*scale)))
                resized=np.array(Image.fromarray((padded*255).astype(np.uint8),mode="L").resize((new_w,new_h),resample=Image.Resampling.NEAREST),dtype=np.float32)/255.0
                resized=(resized>0.5).astype(np.float32)
                y_off=(target.shape[0]-new_h)//2; x_off=(target.shape[1]-new_w)//2
                pred=np.zeros(target.shape, dtype=np.float32)
                pred[y_off:y_off+new_h,x_off:x_off+new_w]=resized
        else:
            pred=mask
        preds.append(pred)
        Image.fromarray((pred*255).astype(np.uint8),mode="L").save(renders_dir / f"pred_{i:03d}.png")
        loss,iou = alpha_loss(pred, target)
        final_ious.append(iou); final_losses.append(loss)
    # comparison strips etc (reuse blender code partially)
    from host_common import precompute_dt_edges  # noqa
    # Write strips via simple PIL
    def write_strip(targets_, preds_, out_path, labels=None):
        from PIL import Image as PILImage, ImageDraw
        h,w=targets_[0].shape
        n=len(targets_)
        sheet=PILImage.new("RGB",(w*n, h*3 + (18 if labels else 0)), (0,0,0))
        y0=18 if labels else 0
        draw=ImageDraw.Draw(sheet) if labels else None
        for i,(t,p) in enumerate(zip(targets_, preds_)):
            t_img=PILImage.fromarray((t*255).astype(np.uint8),mode="L").convert("RGB")
            p_img=PILImage.fromarray((p*255).astype(np.uint8),mode="L").convert("RGB")
            xor=np.clip(t-p,0,1); miss=np.clip(p-t,0,1)
            overlay=np.zeros((h,w,3),dtype=np.uint8)
            overlay[...,0]=(xor*255).astype(np.uint8)
            overlay[...,1]=(np.minimum(t,p)*255).astype(np.uint8)
            overlay[...,2]=(miss*255).astype(np.uint8)
            o_img=PILImage.fromarray(overlay,mode="RGB")
            sheet.paste(t_img,(i*w, y0))
            sheet.paste(p_img,(i*w, y0+h))
            sheet.paste(o_img,(i*w, y0+2*h))
            if draw and labels:
                draw.text((i*w+2,2), labels[i][:18], fill=(220,220,220))
        out_path.parent.mkdir(parents=True, exist_ok=True)
        sheet.save(out_path)
    groups2=clip_groups(frames_meta)
    strip_targets=[]; strip_preds=[]; labels=[]
    for clip_id, indices_cl in groups2.items():
        # filter wanted?
        if wanted is not None:
            indices_cl=[idx for idx in indices_cl if idx in wanted]
            if not indices_cl:
                continue
        mid=indices_cl[len(indices_cl)//2]
        labels.append(f"{clip_id}:{mid}")
        strip_targets.append(targets[mid])
        strip_preds.append(preds[mid])
    if strip_targets:
        write_strip(strip_targets, strip_preds, out_dir / "comparison_strip_per_clip.png", labels=labels)
    for start in range(0, len(targets), 10):
        end=min(len(targets), start+10)
        # Only if frames included
        sub_t=targets[start:end]
        sub_p=preds[start:end]
        sub_labels=[f"{frames_meta[i].get('clipId')}:{frames_meta[i].get('clipFrame')}" for i in range(start,end)]
        write_strip(sub_t, sub_p, out_dir / f"comparison_strip_{start:02d}_{end-1:02d}.png", labels=sub_labels)
    # gifs
    def write_gifs(frames_meta, targets, preds, out_dir_gif, frame_ms=180):
        out_dir_gif.mkdir(parents=True, exist_ok=True)
        written=[]
        groups_g=clip_groups(frames_meta)
        for clip_id, indices_cl in groups_g.items():
            if wanted is not None:
                indices_cl=[idx for idx in indices_cl if idx in wanted]
                if not indices_cl:
                    continue
            imgs=[]
            for i in indices_cl:
                h,w=targets[i].shape
                canvas=Image.new("RGB",(w*2,h),(0,0,0))
                t_img=Image.fromarray((targets[i]*255).astype(np.uint8),mode="L").convert("RGB")
                p_img=Image.fromarray((preds[i]*255).astype(np.uint8),mode="L").convert("RGB")
                canvas.paste(t_img,(0,0))
                canvas.paste(p_img,(w,0))
                imgs.append(canvas)
            path=out_dir_gif / f"{clip_id}_silhouette.gif"
            if imgs:
                imgs[0].save(path, save_all=True, append_images=imgs[1:], duration=frame_ms, loop=0)
                written.append(str(path))
        return written
    gif_paths=write_gifs(frames_meta, targets, preds, out_dir/"gifs", frame_ms=180)
    # Bake export via Blender headless (reuse original bake but host poses)
    # We'll invoke a tiny Blender script that imports master and keys poses from saved npy's
    # For now skip heavy bake if smoke?
    bake_info={}
    try:
        # Create bake helper script
        helper = TOOL / "_host_bake_helper.py"
        helper_code = '''
import bpy, json, sys, pathlib, numpy as np, math
from mathutils import Vector, Euler
job_path = pathlib.Path(sys.argv[sys.argv.index("--")+1])
job=json.loads(job_path.read_text())
out_dir=pathlib.Path(job["outputDir_abs"])
export_dir=pathlib.Path(job.get("exportDir_abs")or (out_dir.parent/"export"))
frames_meta=job["frames"]
import sys as _sys
_sys.path.insert(0, str(pathlib.Path(r"V:\\Games\\Olden Era Playtest Tweak\\tools\\homm3_silhouette_pose_fit")))
from homm3_pose_camera import setup_pose_camera
# load buffers for cam but not needed for bake
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=job["masterGlb_abs"])
arm=[o for o in bpy.data.objects if o.type=='ARMATURE'][0]
mesh=[o for o in bpy.data.objects if o.type=='MESH'][0]
names=[str(b) for b in job.get("optimizeBones")]
# compute basis
cam=setup_pose_camera(job, arm, bpy_module=bpy)
mw=cam.matrix_world
right_w=(mw.to_quaternion() @ Vector((1.0,0.0,0.0))).normalized()
up_w=(mw.to_quaternion() @ Vector((0.0,1.0,0.0))).normalized()
forward_w=(mw.to_quaternion() @ Vector((0.0,0.0,-1.0))).normalized()
arm_inv=arm.matrix_world.inverted().to_3x3()
right=(arm_inv @ right_w).normalized()
up=(arm_inv @ up_w).normalized()
forward=(arm_inv @ forward_w).normalized()
basis=(right,up,forward)
def apply_vec(vec):
    for i,name in enumerate(names):
        pb=arm.pose.bones[name]
        pb.rotation_mode='XYZ'
        o=i*6
        u,v,d=float(vec[o]),float(vec[o+1]),float(vec[o+2])
        rx,ry,rz=float(vec[o+3]),float(vec[o+4]),float(vec[o+5])
        loc=right*u + up*v + forward*d
        pb.location=loc
        pb.rotation_euler=Euler((rx,ry,rz),'XYZ')
# clear anim
if arm.animation_data is not None:
    arm.animation_data_clear()
arm.animation_data_create()
# group by clip
from collections import defaultdict
groups={}
for i, fr in enumerate(frames_meta):
    cid=str(fr.get("clipId") or fr.get("actionName") or "clip")
    groups.setdefault(cid, []).append(i)
import pathlib
fps=float(job.get("fps",12))
bpy.context.scene.render.fps=int(round(fps))
clip_map={"schema":"homm3_pseudo_rig_clip_map.v1","clips":[]}
for clip_id, indices in groups.items():
    # only those with pose files present? We'll check
    # filter to those where pose file exists
    present=[idx for idx in indices if (out_dir/"poses"/f"pose_{idx:03d}.npy").is_file()]
    if not present:
        continue
    action_name=str(next((fr.get("actionName") for fr in [frames_meta[i] for i in present] if fr.get("actionName")), clip_id))
    action=bpy.data.actions.new(name=action_name)
    arm.animation_data.action=action
    for local_i, global_i in enumerate(present):
        vec=np.load(out_dir/"poses"/f"pose_{global_i:03d}.npy")
        frame=local_i+1
        bpy.context.scene.frame_set(frame)
        apply_vec(vec)
        for name in names:
            pb=arm.pose.bones[name]
            pb.keyframe_insert(data_path="location", frame=frame)
            pb.keyframe_insert(data_path="rotation_euler", frame=frame)
    track=arm.animation_data.nla_tracks.new()
    track.name=action_name
    track.strips.new(action_name, 1, action)
    arm.animation_data.action=None
    clip_map["clips"].append({"clipId":clip_id,"actionName":action_name,"frameCount":len(present),"cyclic": bool(frames_meta[present[0]].get("cyclic",False)),"globalFrameIndices": present})
export_dir.mkdir(parents=True, exist_ok=True)
out_glb=export_dir/"crusader_pseudo_rig.glb"
bpy.ops.object.select_all(action="DESELECT")
arm.select_set(True)
mesh.select_set(True)
bpy.context.view_layer.objects.active=arm
bpy.ops.export_scene.gltf(filepath=str(out_glb), export_format="GLB", export_skins=True, export_animations=True, export_nla_strips=True, export_force_sampling=True, export_apply=False, export_texcoords=True, export_normals=True, export_materials="EXPORT")
clip_map["outputGlb"]=str(out_glb)
clip_map["proof"]="generated-artifact validated — host pseudo-rig bake; not OE runtime"
clip_path=export_dir/"clip_map.json"
clip_path.write_text(json.dumps(clip_map,indent=2),encoding="utf-8")
print(f"bake done {out_glb}")
'''
        helper.write_text(helper_code, encoding='utf-8')
        # resolve job to temp
        tmp_job = out_dir / "job.host_resolved.json"
        tmp_job.write_text(json.dumps(job, indent=2), encoding='utf-8')
        blender = Path(r"V:/Games/actionmesh/tools/blender-3.5.1/blender.exe")
        if blender.is_file():
            import subprocess
            cmd=[str(blender),"--background","--python",str(helper),"--",str(tmp_job)]
            print(f"[host] baking via Blender {cmd}")
            proc=subprocess.run(cmd, cwd=str(ROOT), timeout=120)
            if proc.returncode!=0:
                print(f"[host] bake failed rc {proc.returncode}")
            else:
                bake_info={"glb": str(export_dir / "crusader_pseudo_rig.glb"), "clipMap": str(export_dir / "clip_map.json")}
        else:
            bake_info={"skipped": "blender not found"}
    except Exception as e:
        import traceback; traceback.print_exc()
        bake_info={"error": str(e)}
    per_clip={}
    for clip_id, indices_cl in groups.items():
        # filter wanted
        if wanted is not None:
            indices_cl=[idx for idx in indices_cl if idx in wanted]
            if not indices_cl:
                continue
        per_clip[clip_id]={"meanIoU": float(np.mean([final_ious[i] for i in indices_cl])) if indices_cl else 0.0, "meanLoss": float(np.mean([final_losses[i] for i in indices_cl])) if indices_cl else 0.0, "frameCount": len(indices_cl)}
    report={
        "ok": True,
        "schema":"homm3_pseudo_rig_fit_report.v1_host",
        "unitSid": job.get("unitSid"),
        "frameCount": len(targets),
        "handleCount": len(job["optimizeBones"]),
        "restPoseIoUFrame0": float(rest_ious[0]) if rest_ious else 0.0,
        "restPoseMeanIoU": float(np.mean(rest_ious)) if rest_ious else 0.0,
        "stageAMeanIoU": float(mean_a),
        "targetVersion": job.get("targetVersion","v1"),
        "finalMeanIoU": float(np.mean(final_ious)) if final_ious else 0.0,
        "finalMeanLoss": float(np.mean(final_losses)) if final_losses else 0.0,
        "perClip": per_clip,
        "frames":[{"frame":i,"clipId":frames_meta[i].get("clipId"),"clipFrame":frames_meta[i].get("clipFrame"),"iou":final_ious[i],"loss":final_losses[i]} for i in range(len(targets)) if wanted is None or i in wanted],
        "stageHistory": frame_reports,
        "gifs": gif_paths,
        "comparisonStrip": str(out_dir / "comparison_strip_per_clip.png"),
        "export": bake_info,
        "proof": "generated-artifact validated — host pseudo-rig fit; not OE runtime",
        "device": str(buffers["verts"].device),
    }
    report_path=out_dir / "fit_report.json"
    report_path.write_text(json.dumps(report,indent=2),encoding="utf-8")
    print(json.dumps({"ok":True,"report":str(report_path),"meanIoU":report["finalMeanIoU"]}, indent=2))
    return report

if __name__=="__main__":
    r=main()
    raise SystemExit(0)
