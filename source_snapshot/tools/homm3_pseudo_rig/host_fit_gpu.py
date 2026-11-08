#!/usr/bin/env python3
"""Host fit GPU batch for death animation -- bold experiment, death only"""
import argparse, json
from pathlib import Path
import numpy as np
import torch

ROOT = Path(__file__).resolve().parents[2]
TOOL = Path(__file__).resolve().parent
import sys
if str(TOOL) not in sys.path: sys.path.insert(0, str(TOOL))
if str(ROOT/"tools/homm3_silhouette_pose_fit") not in sys.path: sys.path.insert(0, str(ROOT/"tools/homm3_silhouette_pose_fit"))

from host_common import build_torch_buffers, compute_camera_basis, alpha_loss, sobel_edges
from host_common_gpu import deform_sparse_batched, project_batched, rasterize_cv2_batch_proj
from PIL import Image

def load_job(p):
    j=json.loads(p.read_text(encoding='utf-8'))
    def resolve(s):
        pp=Path(s)
        return str(pp) if pp.is_absolute() else str((ROOT/pp).resolve())
    j["masterGlb"]=resolve(j["masterGlb"])
    j["handleCatalog"]=resolve(j["handleCatalog"])
    j["outputDir"]=resolve(j["outputDir"])
    if j.get("exportDir"): j["exportDir"]=resolve(j["exportDir"])
    for fr in j["frames"]:
        fr["path"]=resolve(fr["path"])
    return j

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--config", type=Path, required=True)
    ap.add_argument("--device", type=str, default="cuda")
    ap.add_argument("--batch", type=int, default=32)
    args=ap.parse_args()
    job=load_job(args.config)
    out_dir=Path(job["outputDir"])
    out_dir.mkdir(parents=True, exist_ok=True)
    export_dir=Path(job.get("exportDir") or (out_dir.parent/"export"))
    # prepare targets if missing (reuse prepare_targets_v1)
    target_dir=out_dir/"targets"
    # expect targets already prepared by run_host_fit, but ensure
    if not (target_dir/"target_00.npy").exists():
        import subprocess
        py=sys.executable
        cmd=[py, str(TOOL/"prepare_targets_v1.py"), "--config", str(out_dir/"job.resolved.json")]
        # Instead just run prepare via python import
        from pathlib import Path as P
        import json as js
        # Ensure job has outputDir absolute etc? We'll just call subprocess like launcher
        # For now assume targets exist because we already ran death_bold
        pass

    # Load targets
    n_frames=len(job["frames"])
    targets=[]
    edges=[]
    for i in range(n_frames):
        npy=target_dir/f"target_{i:02d}.npy"
        if not npy.is_file(): npy=target_dir/f"target_{i:03d}.npy"
        arr=np.load(str(npy)).astype(np.float32)
        targets.append(arr)
        edge=target_dir/f"edge_{i:02d}.npy"
        if not edge.is_file(): edge=target_dir/f"edge_{i:03d}.npy"
        if edge.is_file():
            edges.append(np.load(str(edge)).astype(np.float32))
        else:
            edges.append(sobel_edges(arr))
    from scipy.ndimage import distance_transform_edt
    dts=[distance_transform_edt(1-(t>0.5).astype(np.uint8)).astype(np.float32) for t in targets]

    # Buffers
    glb=Path(job["masterGlb"])
    cat=Path(job["handleCatalog"])
    device=args.device if torch.cuda.is_available() else "cpu"
    buffers=build_torch_buffers(glb, cat, device=device)
    verts=buffers["verts"]
    rest=buffers["rest_handles"]
    hidx=buffers["handle_indices"]
    weights=buffers["weights"]
    faces=buffers["faces"]
    rest_np=buffers["rest_handles_np"]
    cam=compute_camera_basis(job)
    cam["ortho"]=float(job["camera"]["orthoScale"])
    print(f"[gpu] verts {verts.shape} faces {faces.shape} device {verts.device} cam ortho {cam['ortho']}")
    # Check GPU usage
    print(f"[gpu] torch cuda {torch.cuda.is_available()} {torch.cuda.get_device_name(0) if torch.cuda.is_available() else ''}")
    # Optimizer params from job
    dof=job.get("dof") or {}
    plane_b=float(dof.get("planeTranslateBound",0.35))
    depth_b=float(dof.get("depthTranslateBound",0.06))
    rot_b=float(dof.get("rotateBoundRad",0.61))
    # For bold death we freeze rot, already set 0.0 in config
    print(f"[gpu] dof plane {plane_b} depth {depth_b} rot {rot_b}")

    # Build handle KNN for stretch (translation only)
    knn_k=int((job.get("loss") or {}).get("handleNeighborK",4))
    rest_pos=rest_np
    n_handles=len(job["optimizeBones"])
    def build_knn(rest, k):
        n=rest.shape[0]
        k_use=max(1, min(int(k), max(1,n-1)))
        neigh=[]
        for i in range(n):
            d=np.linalg.norm(rest-rest[i][None,:], axis=1)
            d[i]=np.inf
            idx=np.argsort(d)[:k_use]
            neigh.append([int(j) for j in idx])
        return neigh
    handle_knn=build_knn(rest_pos, knn_k)

    # Rest IoU
    def eval_single(vec_np, idx):
        vec_t=torch.from_numpy(vec_np.astype(np.float32)).to(verts.device)
        deformed=deform_sparse_batched(verts, rest, hidx, weights, vec_t[None], cam)
        pts=project_batched(deformed, cam, targets[idx].shape[1], targets[idx].shape[0])
        pts_np=pts[0].detach().cpu().numpy()
        from host_common import rasterize_cv2
        mask=rasterize_cv2(pts_np, faces, targets[idx].shape[0], targets[idx].shape[1])
        # no normalize for clip_rest
        pred=mask
        alpha,iou=alpha_loss(pred, targets[idx])
        return alpha,iou,pred

    rest_vec=np.zeros(n_handles*6, dtype=np.float64)
    for i in range(n_frames):
        _,iou,_=eval_single(rest_vec,i)
        print(f" rest frame {i} iou {iou:.4f}")

    # Now batched random search demonstration
    B=args.batch
    print(f"[gpu] batch random search B={B} for death frame 5 (most motion)")
    target_idx=5
    # Build bounds
    bounds=[]
    for _ in range(n_handles):
        bounds.extend([(-plane_b, plane_b), (-plane_b, plane_b), (-depth_b, depth_b), (-rot_b, rot_b), (-rot_b, rot_b), (-rot_b, rot_b)])
    lo=np.array([b[0] for b in bounds], dtype=np.float32)
    hi=np.array([b[1] for b in bounds], dtype=np.float32)

    rng=np.random.default_rng(0)
    # Generate B random candidates + one zero
    vecs=np.zeros((B, n_handles*6), dtype=np.float32)
    for b in range(1,B):
        # uniform for translation, normal for rot (but rot 0 bound)
        for hi_i in range(n_handles):
            base=hi_i*6
            vecs[b,base+0]=rng.uniform(-plane_b, plane_b)
            vecs[b,base+1]=rng.uniform(-plane_b, plane_b)
            vecs[b,base+2]=rng.uniform(-depth_b, depth_b)
            if rot_b>1e-6:
                vecs[b,base+3:base+6]=rng.normal(0,0.15, size=3)
        vecs[b]=np.clip(vecs[b], lo, hi)

    # Batch evaluate
    import time
    t0=time.perf_counter()
    vecs_t=torch.from_numpy(vecs).to(verts.device)
    deformed_batch=deform_sparse_batched(verts, rest, hidx, weights, vecs_t, cam)
    pts_batch=project_batched(deformed_batch, cam, targets[target_idx].shape[1], targets[target_idx].shape[0])
    pts_batch_np=pts_batch.detach().cpu().numpy()
    masks_batch=rasterize_cv2_batch_proj(pts_batch_np, faces, targets[target_idx].shape[0], targets[target_idx].shape[1])
    # Compute alpha quickly
    ious=[]
    for b in range(B):
        _,iou=alpha_loss(masks_batch[b], targets[target_idx])
        ious.append(iou)
    t1=time.perf_counter()
    print(f" batch eval {B} took {(t1-t0)*1000:.1f} ms {(t1-t0)/B*1000:.2f} per")
    best=np.argmax(ious)
    print(f" best random IoU {ious[best]:.4f} vs rest {ious[0]:.4f}")
    # Save best mask
    Image.fromarray((masks_batch[best]*255).astype(np.uint8)).save(out_dir/"_batch_best.png")
    Image.fromarray((targets[target_idx]*255).astype(np.uint8)).save(out_dir/"_batch_target.png")
    print(f" saved to {out_dir / '_batch_best.png'}")

    # Now iterative batched CMA-like: pick best 4, mutate
    loss_cfg=job.get("loss") or {}
    lam_d=float(loss_cfg.get("lambdaDeformStageA",0.01))
    # For viz we just do 10 generations of 32
    best_vec=vecs[best].copy()
    best_iou=ious[best]
    print(f" Starting evolution best {best_iou:.4f}")
    for gen in range(10):
        # generate 32 around best with decaying noise
        sigma = 0.15 * (0.9**gen)
        vecs2=np.repeat(best_vec[None,:], B, axis=0)
        vecs2[1:]+=rng.normal(0, sigma, size=(B-1, n_handles*6))
        # clip
        vecs2=np.clip(vecs2, lo, hi)
        vecs2[0]=best_vec # keep elite
        vecs_t=torch.from_numpy(vecs2).to(verts.device)
        deformed_batch=deform_sparse_batched(verts, rest, hidx, weights, vecs_t, cam)
        pts_batch=project_batched(deformed_batch, cam, targets[target_idx].shape[1], targets[target_idx].shape[0])
        pts_batch_np=pts_batch.detach().cpu().numpy()
        masks_batch=rasterize_cv2_batch_proj(pts_batch_np, faces, targets[target_idx].shape[0], targets[target_idx].shape[1])
        ious2=[]
        for b in range(B):
            _,iou=alpha_loss(masks_batch[b], targets[target_idx])
            ious2.append(iou)
        gen_best=np.argmax(ious2)
        if ious2[gen_best] > best_iou:
            best_iou=ious2[gen_best]
            best_vec=vecs2[gen_best].copy()
            print(f" gen {gen} new best {best_iou:.4f} sigma {sigma:.3f}")
        else:
            print(f" gen {gen} no improve best {best_iou:.4f} gen_best {ious2[gen_best]:.4f}")
    print(f" final best {best_iou:.4f}")
    # Run nvidia-smi check
    import subprocess
    try:
        out=subprocess.check_output(["nvidia-smi","--query-gpu=utilization.gpu,memory.used","--format=csv,noheader,nounits"], text=True)
        print("nvidia-smi", out.strip())
    except Exception as e:
        print(e)

if __name__=="__main__":
    main()
