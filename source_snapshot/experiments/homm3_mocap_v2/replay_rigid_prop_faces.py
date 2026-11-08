"""Diagnostic rigid face ownership; body motion and fitted rest remain fixed."""
from __future__ import annotations
import argparse
import json
import time
from pathlib import Path
import numpy as np
import torch
from run_surface_loss_attribution import _load_inputs
from run_skin_mesh_pilot import ROOT, SkinImageRenderer, comparison, deform, digest, expand_camera_to_full_canvas, sha256_file
from run_skin_weight_pilot import cascade_batch_lock, source_images


def rigid_corners(baseline, rest, faces, selected, transform):
    """Replace only selected face corners; do not move shared body vertices."""
    result = baseline[:, faces].clone()
    points = rest[faces[selected]]
    moved = torch.einsum("fij,tkj->ftki", transform[:, :3, :3], points) + transform[:, None, None, :3, 3]
    result[:, selected] = moved
    return result


def run(asset, fit_dir, mask_dir, owner, output, visibility_path=None, ownership="face-corners"):
    started = time.perf_counter()
    if output.exists():
        raise FileExistsError(output)
    if ownership not in ("face-corners", "skin-vertices"):
        raise ValueError("unknown ownership representation")
    if ownership == "skin-vertices" and visibility_path is not None:
        raise ValueError("vertex ownership has no detached-prop visibility contract")
    fit_report, _, _, _, fitted, _, motions, frame_paths, provenance = _load_inputs(fit_dir, asset)
    visibility = None
    if visibility_path is not None:
        from prop_visibility import validate_visibility
        visibility = validate_visibility(json.loads(visibility_path.read_text()), asset, fit_report["inputs"]["corpusSha256"], frame_paths)
        # Explicit annotated-subset run, not an all-clips run with default visibility.
        motions = {key: motions[key] for key in visibility}
    mask_report = json.loads((mask_dir / "report.json").read_text())
    if mask_report["asset"] != asset or mask_report["researchSkinSha256"] != fit_report["inputs"]["researchSkin"]:
        raise ValueError("prop proposal asset/preparation mismatch")
    if mask_report.get("maskSha256") != sha256_file(mask_dir / "face_proposal.npz"):
        raise ValueError("prop mask does not match producer digest")
    with np.load(mask_dir / "face_proposal.npz", allow_pickle=False) as z:
        selected_np = z["propTriangles"].copy()
    if selected_np.ndim != 1 or selected_np.dtype.kind not in "iu" or not len(selected_np) or len(np.unique(selected_np)) != len(selected_np):
        raise ValueError("invalid selected face IDs")
    if selected_np.min() < 0 or selected_np.max() >= len(fitted["triangles"]):
        raise ValueError("prop faces outside topology")
    names = list(fitted["names"])
    if names.count(owner) != 1:
        raise ValueError("declared owner must match exactly one joint name")
    owner_index = names.index(owner)
    rigid_vertex_ids = np.unique(fitted["triangles"][selected_np])
    candidate_weights = np.asarray(fitted["weights"]).copy()
    if ownership == "skin-vertices":
        candidate_weights[rigid_vertex_ids] = 0
        candidate_weights[rigid_vertex_ids,owner_index] = 1
    camera_path = Path(fit_report["baselineDirectory"]) / "camera.json"
    camera = expand_camera_to_full_canvas(json.loads(camera_path.read_text()), 224)
    output.mkdir(parents=True)
    report = {"asset":asset,"owner":owner,"accepted":False,"proof":"rigid-face-diagnostic-no-release",
              "fitProvenance":provenance,"maskSha256":mask_report["maskSha256"],
              "maskReportSha256":sha256_file(mask_dir / "report.json"),"cameraSha256":sha256_file(camera_path),
              "implementationSha256":sha256_file(Path(__file__)),"cases":{},
              "restAuthority":"fitted vertices, not original prepared mesh", "sourceWeightsChanged":False}
    report["ownershipRepresentation"] = ownership
    report["candidateChangedWeightRows"] = int(np.count_nonzero(np.any(candidate_weights != fitted["weights"],axis=1)))
    report["candidateWeightsChanged"] = report["candidateChangedWeightRows"] > 0
    report["bodyInvariantScope"] = "vertices outside selected-face vertex union" if ownership == "skin-vertices" else "nonselected face corners"
    if ownership == "skin-vertices":
        report["proof"] = "derived-rigid-skin-candidate-no-delivery"
        np.savez_compressed(output / "rigid_skin_candidate.npz", weights=candidate_weights,
                            vertices=fitted["vertices"],names=np.asarray(names),parents=fitted["parents"])
        report["candidateSha256"] = sha256_file(output / "rigid_skin_candidate.npz")
        report["rigidVertexCount"] = len(rigid_vertex_ids)
    if visibility is not None:
        report["proof"] = "rigid-face-authored-visibility-diagnostic-no-projectile"
        report["visibilitySha256"] = sha256_file(visibility_path)
    with cascade_batch_lock(ROOT):
        rest = torch.as_tensor(fitted["vertices"],device="cuda",dtype=torch.float32)
        weights = torch.as_tensor(fitted["weights"],device="cuda",dtype=torch.float32)
        rigid_weights = torch.as_tensor(candidate_weights,device="cuda",dtype=torch.float32)
        unaffected_vertices = torch.ones(len(rest),device="cuda",dtype=torch.bool)
        unaffected_vertices[torch.as_tensor(rigid_vertex_ids,device="cuda")] = False
        faces = torch.as_tensor(fitted["triangles"],device="cuda",dtype=torch.long)
        selected = torch.as_tensor(selected_np,device="cuda",dtype=torch.long)
        nonprop = torch.ones(len(faces),device="cuda",dtype=torch.bool)
        nonprop[selected] = False
        shared_ids_np = np.intersect1d(fitted["triangles"][selected_np].reshape(-1),
                                      fitted["triangles"][nonprop.cpu().numpy()].reshape(-1))
        shared_ids = torch.as_tensor(shared_ids_np,device="cuda",dtype=torch.long)
        report["sharedBoundaryVertexCount"] = len(shared_ids_np)
        expanded_faces = np.arange(len(faces)*3).reshape(-1,3)
        expanded_uv = fitted["uvs"][fitted["triangles"]].reshape(-1,2)
        renderer = SkinImageRenderer(expanded_faces,expanded_uv,fitted["albedo"],camera,224)
        if visibility is not None:
            body_renderer = SkinImageRenderer(expanded_faces[nonprop.cpu().numpy()],expanded_uv,fitted["albedo"],camera,224)
        neutral = rigid_corners(rest[None],rest,faces,selected,torch.eye(4,device="cuda")[None])
        report["neutralMaxError"] = float((neutral-rest[faces][None]).abs().max())
        if ownership == "skin-vertices":
            identity = torch.eye(4,device="cuda")[None,None].expand(1,len(names),4,4)
            neutral_skin = deform(identity[:,:,:3],rigid_weights,rest)
            report["neutralSkinMaxError"] = float((neutral_skin-rest[None]).abs().max())
            if report["neutralSkinMaxError"] > 1e-6:
                raise ValueError("derived skin changed neutral rest")
        reference_edges = torch.linalg.vector_norm(rest[faces[selected]][:,1:]-rest[faces[selected]][:,:1],dim=-1)
        for key, motion in motions.items():
            transforms = torch.as_tensor(motion["jointWorld"] @ fitted["inverseBind"][None],device="cuda",dtype=torch.float32)
            meshes = deform(transforms[:,:,:3],weights,rest).detach()
            original = meshes[:,faces]
            candidate = rigid_corners(meshes,rest,faces,selected,transforms[:,owner_index])
            if ownership == "skin-vertices":
                candidate_meshes = deform(transforms[:,:,:3],rigid_weights,rest).detach()
                candidate = candidate_meshes[:,faces]
                body_error = float((candidate_meshes[:,unaffected_vertices]-meshes[:,unaffected_vertices]).abs().max())
            else:
                body_error = float((candidate[:,nonprop]-original[:,nonprop]).abs().max())
            edges = torch.linalg.vector_norm(candidate[:,selected,1:]-candidate[:,selected,:1],dim=-1)
            rigid_error = float((edges-reference_edges).abs().max())
            if body_error != 0 or rigid_error > 1e-5:
                raise ValueError("rigid/body preservation invariant failed")
            base_rgb,_ = renderer.render(original.reshape(len(meshes),-1,3))
            rigid_rgb,_ = renderer.render(candidate.reshape(len(meshes),-1,3))
            columns = [base_rgb, rigid_rgb]
            labels = ["Fitted baseline", "Rigid skin trial" if ownership == "skin-vertices" else "Rigid prop trial"]
            if visibility is not None:
                absent = torch.as_tensor(~visibility[key], device="cuda")
                lifecycle_rgb = rigid_rgb.clone()
                if bool(absent.any()):
                    body_rgb,_ = body_renderer.render(candidate[absent].reshape(int(absent.sum()),-1,3))
                    lifecycle_rgb[absent] = body_rgb
                columns.append(lifecycle_rgb)
                labels.append("Source visibility")
            source = source_images(frame_paths[key],camera["sourceCrop"],224)
            comparison(output / f"{key}_comparison.gif",[source[0]]+columns,["DEF"]+labels,f"{asset} {key}")
            owner_t = transforms[:,owner_index]
            rigid_boundary = torch.einsum("fij,vj->fvi",owner_t[:,:3,:3],rest[shared_ids]) + owner_t[:,None,:3,3]
            boundary_gap = float(torch.linalg.vector_norm(rigid_boundary-meshes[:,shared_ids],dim=-1).max()) if len(shared_ids) else 0.0
            report["cases"][key] = {"frames":len(meshes),"fixedMotionSha256":digest(motion["jointWorld"]),
                                   "bodyMaxError":body_error,"rigidEdgeMaxError":rigid_error,
                                   "renderRgbMeanAbsoluteDifference":float((rigid_rgb-base_rgb).abs().mean()),
                                   "maxOwnerVsBaselineBoundaryDistance":boundary_gap,
                                   "maxSharedBoundaryGap":boundary_gap if ownership == "face-corners" else 0.0,
                                   "maxPropCornerChange":float((candidate[:,selected]-original[:,selected]).abs().max())}
            if visibility is not None:
                report["cases"][key]["visible"] = visibility[key].tolist()
    report["elapsedSeconds"] = time.perf_counter()-started
    (output / "report.json").write_text(json.dumps(report,indent=2))
    print(json.dumps({"asset":asset,"clips":len(report["cases"]),"elapsedSeconds":report["elapsedSeconds"]}))


if __name__ == "__main__":
    p=argparse.ArgumentParser()
    for arg in ("asset","owner"):
        p.add_argument("--"+arg,required=True)
    for arg in ("fit-dir","mask-dir","output"):
        p.add_argument("--"+arg,type=Path,required=True)
    p.add_argument("--visibility",type=Path)
    p.add_argument("--ownership",choices=("face-corners","skin-vertices"),default="face-corners")
    a=p.parse_args()
    run(a.asset,a.fit_dir,a.mask_dir,a.owner,a.output,a.visibility,a.ownership)
