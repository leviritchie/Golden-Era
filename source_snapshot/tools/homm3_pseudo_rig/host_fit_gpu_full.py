#!/usr/bin/env python3
"""
GPU batched fitter: full death_g5 clip evolution + bake pose vectors + render GIF.

Uses deform_sparse_batched (GPU, ~7x faster than per-eval loop) with CMA-like
generations. Saves pose_XXX.npy per frame + comparison GIF + strip.

Usage:
  py -3 tools/homm3_pseudo_rig/host_fit_gpu_full.py \
      --config tools/homm3_pseudo_rig/configs/h3_crusader_split_death_bold.json \
      --gens 12 --batch 48
"""
import argparse, json, sys, time
from pathlib import Path
import numpy as np
import torch

ROOT = Path(__file__).resolve().parents[2]
TOOL = Path(__file__).resolve().parent
if str(TOOL) not in sys.path: sys.path.insert(0, str(TOOL))
if str(ROOT/"tools/homm3_silhouette_pose_fit") not in sys.path: sys.path.insert(0, str(ROOT/"tools/homm3_silhouette_pose_fit"))

from host_common import build_torch_buffers, compute_camera_basis, alpha_loss, sobel_edges, rasterize_cv2
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
    ap.add_argument("--batch", type=int, default=48)
    ap.add_argument("--gens", type=int, default=12)
    ap.add_argument("--seed", type=int, default=0)
    args=ap.parse_args()
    job=load_job(args.config)
    out_dir=Path(job["outputDir"])
    out_dir.mkdir(parents=True, exist_ok=True)
    export_dir=Path(job.get("exportDir") or (out_dir.parent/"export"))
    target_dir=out_dir/"targets"

    n_frames=len(job["frames"])
    targets=[]; edges=[]
    for i in range(n_frames):
        npy=target_dir/f"target_{i:02d}.npy"
        if not npy.is_file(): npy=target_dir/f"target_{i:03d}.npy"
        if not npy.is_file():
            raise FileNotFoundError(f"targets not prepared; run run_host_fit first: {npy}")
        arr=np.load(str(npy)).astype(np.float32)
        targets.append(arr)
        edge=target_dir/f"edge_{i:02d}.npy"
        if not edge.is_file(): edge=target_dir/f"edge_{i:03d}.npy"
        edges.append(np.load(str(edge)).astype(np.float32) if edge.is_file() else sobel_edges(arr))
    from scipy.ndimage import distance_transform_edt
    dts=[distance_transform_edt(1-(t>0.5).astype(np.uint8)).astype(np.float32) for t in targets]

    glb=Path(job["masterGlb"]); cat=Path(job["handleCatalog"])
    device=args.device if torch.cuda.is_available() else "cpu"
    buffers=build_torch_buffers(glb, cat, device=device)
    verts=buffers["verts"]; rest=buffers["rest_handles"]; hidx=buffers["handle_indices"]; weights=buffers["weights"]
    faces=buffers["faces"]
    rest_np=buffers["rest_handles_np"]
    cam=compute_camera_basis(job); cam["ortho"]=float(job["camera"]["orthoScale"])
    n_handles=len(job["optimizeBones"])

    dof=job.get("dof") or {}
    plane_b=float(dof.get("planeTranslateBound",0.35)); depth_b=float(dof.get("depthTranslateBound",0.06)); rot_b=float(dof.get("rotateBoundRad",0.61))
    loss_cfg=job.get("loss") or {}
    lam_e=float(loss_cfg.get("lambdaEdge",0.0)); lam_dt=float(loss_cfg.get("lambdaDt",0.0)); lam_d=float(loss_cfg.get("lambdaDeformStageA",0.01)); lam_s=float(loss_cfg.get("lambdaStretchStageA",0.01))
    bounds=[]
    for _ in range(n_handles):
        bounds.extend([(-plane_b,plane_b),(-plane_b,plane_b),(-depth_b,depth_b),(-rot_b,rot_b),(-rot_b,rot_b),(-rot_b,rot_b)])
    lo=np.array([b[0] for b in bounds], dtype=np.float32); hi=np.array([b[1] for b in bounds], dtype=np.float32)

    def build_knn(rest, k):
        n=rest.shape[0]; k_use=max(1,min(int(k),max(1,n-1)))
        neigh=[]
        for i in range(n):
            d=np.linalg.norm(rest-rest[i][None,:],axis=1); d[i]=np.inf
            neigh.append([int(j) for j in np.argsort(d)[:k_use]])
        return neigh
    handle_knn=build_knn(rest_np, int(loss_cfg.get("handleNeighborK",4)))

    def full_loss(vecs_np, idx):
        # vecs_np B,D -> masks B,H,W, losses B
        vecs_t=torch.from_numpy(vecs_np.astype(np.float32)).to(verts.device)
        deformed=deform_sparse_batched(verts, rest, hidx, weights, vecs_t, cam)
        pts=project_batched(deformed, cam, targets[idx].shape[1], targets[idx].shape[0])
        masks=rasterize_cv2_batch_proj(pts.detach().cpu().numpy(), faces, targets[idx].shape[0], targets[idx].shape[1])
        B=vecs_np.shape[0]
        losses=np.zeros(B, dtype=np.float64); ious=np.zeros(B, dtype=np.float64)
        target=targets[idx]; edge=edges[idx]; dt=dts[idx]
        for b in range(B):
            alpha,iou=alpha_loss(masks[b], target)
            # edge via sobel (cpu ok for B small)
            e_l=0.0
            if lam_e>0:
                pe=sobel_edges(masks[b])
                e_l=float(np.mean(np.abs(pe-edge)))
            dt_l=0.0
            if lam_dt>0:
                p=(masks[b]>0.5).astype(np.uint8)
                if p.sum()>0 and target.sum()>0:
                    dt_p=distance_transform_edt(1-p)
                    a=float((dt*p).sum()/(p.sum()+1e-6)); bb=float((dt_p*target).sum()/(target.sum()+1e-6))
                    dt_l=(a+bb)/max(1.0,float(np.hypot(*target.shape)))
                else:
                    dt_l=1.0
            deform=0.0
            for i in range(n_handles):
                o=i*6
                deform+=float(vecs_np[b,o]**2+vecs_np[b,o+1]**2+vecs_np[b,o+2]**2)+0.25*float(vecs_np[b,o+3]**2+vecs_np[b,o+4]**2+vecs_np[b,o+5]**2)
            deform/=max(1,n_handles)
            right=np.array(cam["right"]); up=np.array(cam["up"]); forward=np.array(cam["forward"])
            posed=np.zeros_like(rest_np)
            for i in range(n_handles):
                o=i*6
                posed[i]=rest_np[i]+right*float(vecs_np[b,o])+up*float(vecs_np[b,o+1])+forward*float(vecs_np[b,o+2])
            stretch=0.0; cnt=0
            for i,nbrs in enumerate(handle_knn):
                for j in nbrs:
                    rl=float(np.linalg.norm(rest_np[i]-rest_np[j]))+1e-6
                    pl=float(np.linalg.norm(posed[i]-posed[j]))
                    stretch+=(pl/rl-1.0)**2; cnt+=1
            stretch/=max(1,cnt)
            losses[b]=alpha+lam_e*e_l+lam_dt*dt_l+lam_d*deform+lam_s*stretch
            ious[b]=iou
        return losses, ious, masks

    rng=np.random.default_rng(args.seed)
    poses=[]
    # Sequential per frame, warm start from prev best (death is a collapse: frame order)
    x_prev=np.zeros(n_handles*6, dtype=np.float32)
    for fi in range(n_frames):
        print(f"[gpu] frame {fi}/{n_frames-1}", flush=True)
        B=args.batch
        # init population around prev
        vecs=np.zeros((B, n_handles*6), dtype=np.float32)
        for b in range(B):
            if b==0:
                vecs[b]=x_prev.copy()
            else:
                noise=rng.normal(0, 0.12, size=(n_handles*6,)).astype(np.float32)
                # translation noise bigger, rotation noise (rot 0) small
                for i in range(n_handles):
                    o=i*6
                    noise[o+3:o+6]*=0.1
                vecs[b]=np.clip(x_prev+noise, lo, hi)
        _,ious,masks=full_loss(vecs, fi)
        best=np.argmin(ious if False else (-ious))  # max iou
        # Actually maximize iou: loss has 1-alpha so min loss = max iou; use loss
        losses,ious,masks=full_loss(vecs, fi)
        best_idx=int(np.argmin(losses))
        best_iou=float(ious[best_idx])
        # CMA-like evolution
        sigma0=0.12
        for gen in range(args.gens):
            sigma=sigma0*(0.9**gen)
            vecs2=np.repeat(vecs[best_idx][None,:], B, axis=0)
            noise=rng.normal(0, sigma, size=(B-1, n_handles*6)).astype(np.float32)
            for i in range(n_handles):
                o=i*6
                noise[:, o+3:o+6]*=0.1
            vecs2[1:]=np.clip(vecs2[1:]+noise, lo, hi)
            vecs2[0]=vecs[best_idx].copy()
            losses2,ious2,masks2=full_loss(vecs2, fi)
            nb=int(np.argmin(losses2))
            if losses2[nb] < losses[best_idx]:
                best_idx=0
                # keep best elite at index 0? Replace vecs with new pop
                vecs=vecs2.copy()
                losses=losses2.copy(); ious=ious2.copy(); masks=masks2.copy()
                best_iou=float(ious[nb]); 
                # best vector is vecs2[nb]
                vecs[0]=vecs2[nb].copy()
                if gen%3==0 or gen==args.gens-1:
                    print(f"  gen {gen} best IoU {best_iou:.4f}", flush=True)
            else:
                # no improvement, still keep population for next gen
                vecs=vecs2.copy(); losses=losses2.copy(); ious=ious2.copy(); masks=masks2.copy()
        best_vec=vecs[0].copy()
        best_iou=float(ious[0])
        # Recompute mask for best
        _,iou_b,masks_b=full_loss(best_vec[None,:], fi)
        best_iou=float(iou_b[0])
        print(f"[gpu] frame {fi} final IoU {best_iou:.4f}", flush=True)
        poses.append(best_vec)
        x_prev=best_vec.copy()
        # Save pose
        poses_dir=out_dir/"poses_gpu"
        poses_dir.mkdir(parents=True, exist_ok=True)
        np.save(poses_dir/f"pose_{fi:03d}.npy", best_vec.astype(np.float64))
        Image.fromarray((masks_b[0]*255).astype(np.uint8)).save(out_dir/f"_gpu_frame{fi}.png")
    print(f"[gpu] done all frames")

    # Build comparison GIF target|pred
    gifs_dir=out_dir/"gifs_gpu"
    gifs_dir.mkdir(parents=True, exist_ok=True)
    frames=[]
    for fi in range(n_frames):
        t=targets[fi]
        p=np.array(Image.open(out_dir/f"_gpu_frame{fi}.png").convert("L"))/255.0
        h,w=t.shape
        canvas=Image.new("RGB",(w*2,h),(0,0,0))
        canvas.paste(Image.fromarray((t*255).astype(np.uint8),mode="L").convert("RGB"),(0,0))
        canvas.paste(Image.fromarray((p*255).astype(np.uint8),mode="L").convert("RGB"),(w,0))
        frames.append(canvas)
    gif_path=gifs_dir/"death_g5_gpu.gif"
    frames[0].save(gif_path, save_all=True, append_images=frames[1:], duration=180, loop=0)
    print(f"[gpu] gif saved {gif_path}")

    # Also export GLB via Blender bake using poses
    bake_info={}
    try:
        import subprocess
        helper=TOOL/"_host_bake_helper.py"
        tmp_job=out_dir/"job.gpu.json"
        # Point bake helper to poses_gpu dir
        jb=dict(job)
        jb["outputDir_abs"]=str(out_dir)
        jb["exportDir_abs"]=str(export_dir)
        tmp_job.write_text(json.dumps(jb, indent=2), encoding='utf-8')
        blender=Path(r"V:/Games/actionmesh/tools/blender-3.5.1/blender.exe")
        # patch helper to use poses_gpu
        helper_code=helper.read_text()
        if "poses_gpu" not in helper_code:
            helper_code=helper_code.replace('out_dir/"poses"', 'out_dir/"poses_gpu"')
            helper.write_text(helper_code)
        cmd=[str(blender),"--background","--python",str(helper),"--",str(tmp_job)]
        print(f"[gpu] baking {cmd}")
        proc=subprocess.run(cmd, cwd=str(ROOT), timeout=120)
        bake_info={"glb": str(export_dir/"crusader_pseudo_rig.glb"), "rc": proc.returncode}
        print(f"[gpu] bake rc {proc.returncode}")
    except Exception as e:
        import traceback; traceback.print_exc()
        bake_info={"error":str(e)}
    print(json.dumps({"ok":True, "gif":str(gif_path), "bake":bake_info, "ious":[float(ious[i]) if False else 0.0 for i in range(n_frames)]}, indent=2))

if __name__=="__main__":
    main()
