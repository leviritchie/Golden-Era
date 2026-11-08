from __future__ import annotations
import json
from pathlib import Path
import numpy as np
import torch
from PIL import Image
import argparse

from run_attachment_skin_refit import load_refit
from skin_image_objective import SkinImageRenderer
from run_skin_mesh_pilot import ROOT, deform, sha256_file
from run_skin_weight_pilot import cascade_batch_lock


def _run_locked(args):
    fit, report, manifest, out = map(Path, (args.fit_dir, args.refit_report, args.camera_manifest, args.output))
    if out.exists(): raise FileExistsError(out)
    refit_report = json.loads(report.read_text(encoding="utf-8"))
    manifest_data = json.loads(manifest.read_text(encoding="utf-8"))
    if manifest_data.get("sourceReportSha256") != sha256_file(report): raise ValueError("camera manifest source report drift")
    if manifest_data.get("candidateSha256") != refit_report.get("candidateSha256"): raise ValueError("camera manifest candidate drift")
    camera = manifest_data["camera"]
    resolution = int(camera.get("resolution", 0))
    if resolution < 2: raise ValueError("camera manifest lacks valid resolution")
    key = args.clip; frame = int(args.frame)
    box = tuple(int(x) for x in args.pick_box)
    if not (0 <= box[0] < box[2] <= resolution and 0 <= box[1] < box[3] <= resolution): raise ValueError("pick box outside camera")
    _, _, original, candidate, motions = load_refit(report, args.asset, fit)
    if key not in motions or frame < 0 or frame >= len(motions[key]["jointWorld"]): raise ValueError("clip/frame outside motion")
    domain = dict(np.load(report.parent / "domain.npz", allow_pickle=False))
    motion = motions[key]
    transforms = torch.as_tensor(motion["jointWorld"] @ original["inverseBind"][None], dtype=torch.float32, device="cuda")[:, :, :3]
    rest = torch.as_tensor(original["vertices"], dtype=torch.float32, device="cuda")
    weights = torch.as_tensor(candidate["weights"], dtype=torch.float32, device="cuda")
    meshes = deform(transforms, weights, rest)
    renderer = SkinImageRenderer(candidate["triangles"], candidate["uvs"], candidate["albedo"], camera, resolution)
    rgb, alpha = renderer.render(meshes[frame:frame+1])
    # Reuse the renderer's camera/raster context to obtain the winning triangle ID.
    dr, torch_mod = renderer.dr, renderer.torch
    verts = meshes[frame:frame+1]
    x = torch_mod.einsum("fvi,i->fv", verts, renderer.right)
    y = torch_mod.einsum("fvi,i->fv", verts, renderer.down)
    z = torch_mod.einsum("fvi,i->fv", verts, renderer.forward)
    px = x * renderer.scale + renderer.offset[0]; py = y * renderer.scale + renderer.offset[1]
    ndc = torch_mod.stack((2*px/(resolution-1)-1, 1-2*py/(resolution-1), (z-renderer.depth_center)/renderer.depth_span, torch_mod.ones_like(z)), -1)
    rast, _ = dr.rasterize(renderer.ctx, ndc, renderer.triangles, resolution=[resolution, resolution])
    tri_id = torch_mod.flip(rast[..., 3], dims=(1,))[0].detach().cpu().numpy().astype(np.int64) - 1
    alpha_np = alpha[0, ..., 0].detach().cpu().numpy() > .1
    pick_mask = alpha_np.copy(); pick_mask[:box[1]] = False; pick_mask[box[3]:] = False; pick_mask[:, :box[0]] = False; pick_mask[:, box[2]:] = False
    picked = tri_id[pick_mask & (tri_id >= 0)]
    unique, counts = np.unique(picked, return_counts=True)
    order = np.argsort(counts)[::-1]; selected = unique[order].astype(int).tolist()
    tri = np.asarray(candidate["triangles"], dtype=np.int64)
    w = np.asarray(candidate["weights"]); owners = np.asarray(domain["ownershipIds"])
    rows = []
    for fid, count in zip(unique[order], counts[order]):
        vs = tri[int(fid)]; mean = w[vs].mean(0); rows.append({"face": int(fid), "pixels": int(count), "vertices": vs.tolist(), "owners": owners[vs].tolist(), "dominantJoints": np.argsort(mean)[::-1][:4].astype(int).tolist(), "dominantWeights": np.sort(mean)[::-1][:4].tolist()})
    # Overlay the picked pixel set in red on the exact serialized candidate render.
    base = np.clip(rgb[0].detach().cpu().numpy() * 255, 0, 255).astype(np.uint8)
    overlay = base.copy(); mask = pick_mask & (tri_id >= 0); overlay[mask] = (255, 30, 30)
    out.mkdir(parents=True)
    Image.fromarray(overlay).save(out / "picked_overlay.png")
    region_counts = {}
    for row in rows:
        for vertex in row["vertices"]:
            label = str(candidate["regions"][vertex]); region_counts[label] = region_counts.get(label, 0) + 1
    report_out = {"schema":"fragment-face-pick-v1", "asset":args.asset, "sourceReport":str(report.resolve()), "sourceReportSha256":sha256_file(report), "fitDirectory":str(fit.resolve()), "cameraManifest":str(manifest.resolve()), "cameraManifestSha256":sha256_file(manifest), "clip":key, "frame":frame, "pickBox":list(box), "pickedPixelCount":int(len(picked)), "selectedFaceCount":len(selected), "selectedFaces":rows, "regionCornerCounts":region_counts, "outputOverlay":str((out/"picked_overlay.png").resolve()), "candidateSha256":sha256_file(report.parent/"refitted_skin.npz")}
    (out/"report.json").write_text(json.dumps(report_out, indent=2)+"\n")
    print(json.dumps(report_out, indent=2))


def main(args):
    with cascade_batch_lock(ROOT):
        return _run_locked(args)
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--asset", required=True)
    parser.add_argument("--fit-dir", type=Path, required=True)
    parser.add_argument("--refit-report", type=Path, required=True)
    parser.add_argument("--camera-manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--clip", required=True)
    parser.add_argument("--frame", type=int, required=True)
    parser.add_argument("--pick-box", type=int, nargs=4, required=True, metavar=("X0", "Y0", "X1", "Y1"))
    main(parser.parse_args())
