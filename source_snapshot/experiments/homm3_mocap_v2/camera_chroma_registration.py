"""Chroma-aware camera candidate ranking, kept separate from camera defaults."""
from __future__ import annotations

from typing import Any, Iterable

import numpy as np


def _array(value, shape_last=None):
    result = np.asarray(value, dtype=np.float64)
    if shape_last is not None and (result.ndim != 3 or result.shape[-1] != shape_last):
        raise ValueError("image must be [H,W,C]")
    if not np.isfinite(result).all():
        raise ValueError("image contains non-finite values")
    return result


def chromaticity(image: Any, alpha: Any, *, floor=1e-6) -> np.ndarray:
    rgb = _array(image, 3)
    mask = _array(alpha)[..., 0] if np.asarray(alpha).ndim == 3 else _array(alpha)
    if rgb.shape[:2] != mask.shape:
        raise ValueError("RGB and alpha dimensions differ")
    total = np.maximum(rgb.sum(axis=-1, keepdims=True), floor)
    return rgb / total


def score_candidate(source_rgb, source_alpha, predicted_rgb, predicted_alpha) -> dict[str, float]:
    source_rgb, predicted_rgb = _array(source_rgb, 3), _array(predicted_rgb, 3)
    source_alpha = _array(source_alpha)
    predicted_alpha = _array(predicted_alpha)
    if source_rgb.shape != predicted_rgb.shape or source_alpha.shape != predicted_alpha.shape:
        raise ValueError("source and candidate image shapes differ")
    source_mask = np.clip(source_alpha[..., 0] if source_alpha.ndim == 3 else source_alpha, 0, 1)
    predicted_mask = np.clip(predicted_alpha[..., 0] if predicted_alpha.ndim == 3 else predicted_alpha, 0, 1)
    intersection = float((source_mask * predicted_mask).sum())
    union = float((source_mask + predicted_mask - source_mask * predicted_mask).sum())
    iou = intersection / union if union > 1e-12 else 0.0
    source_chroma = chromaticity(source_rgb, source_mask)
    predicted_chroma = chromaticity(predicted_rgb, predicted_mask)
    support = np.minimum(source_mask, predicted_mask)[..., None]
    chroma_error = float((np.abs(source_chroma - predicted_chroma) * support).sum() / max(float(support.sum()), 1e-12))
    score = (1.0 - iou) + chroma_error
    return {"score": score, "alphaIoU": iou, "chromaError": chroma_error}


def rank_candidates(candidates: Iterable[dict[str, Any]], source_rgb, source_alpha) -> list[dict[str, Any]]:
    ranked = []
    for candidate in candidates:
        if not isinstance(candidate, dict) or "rgb" not in candidate or "alpha" not in candidate:
            raise ValueError("each camera candidate requires rgb and alpha")
        row = dict(candidate)
        row.update(score_candidate(source_rgb, source_alpha, candidate["rgb"], candidate["alpha"]))
        ranked.append(row)
    if not ranked:
        raise ValueError("at least one camera candidate is required")
    return sorted(ranked, key=lambda value: (value["score"], -value["alphaIoU"]))


def audit(skin_path,source,output):
    import json
    import torch
    from PIL import Image
    from pin import sha256_file
    from skin_camera_registration import _basis_yup,_bbox_scale_offset,_target_bbox,_camera
    from skin_image_objective import SkinImageRenderer
    from run_skin_weight_pilot import cascade_batch_lock,ROOT,source_images
    from run_skin_mesh_pilot import comparison
    if output.exists():raise FileExistsError(output)
    with np.load(skin_path,allow_pickle=False) as z:skin={k:z[k].copy() for k in z.files}
    with Image.open(source) as im:size=im.size
    crop_size=min(size);crop=dict(left=(size[0]-crop_size)//2,top=(size[1]-crop_size)//2,size=crop_size)
    candidates=[]
    with cascade_batch_lock(ROOT):
        target=source_images([source],crop,224)
        rgb,alpha=[x[0].detach().cpu().numpy() for x in target[:2]]
        bounds=_target_bbox(alpha[...,0])
        for yaw in sorted(set(range(20,161,20))|{55,115}):
            for pitch in (0,10,20,30,40):
                basis=_basis_yup(yaw,pitch);scale,offset=_bbox_scale_offset(skin['vertices'],basis,bounds)
                camera=_camera(basis,scale=scale,offset=offset,vertices=skin['vertices'],source_size=size,source_crop=crop,resolution=224,yaw_deg=yaw,pitch_deg=pitch)
                if not candidates:renderer=SkinImageRenderer(skin['triangles'],skin['uvs'],skin['albedo'],camera,224)
                else:renderer.set_camera(camera)
                predicted=renderer.render(skin['vertices'][None])
                candidates.append(dict(camera=camera,yaw=yaw,pitch=pitch,rgb=predicted[0][0].detach().cpu().numpy(),alpha=predicted[1][0].detach().cpu().numpy()))
        ranked=rank_candidates(candidates,rgb,alpha)
        output.mkdir(parents=True)
        columns=[target[0]]+[torch.as_tensor(row['rgb'][None]) for row in ranked[:4]]
        labels=['Source']+[f'yaw {r["yaw"]} pitch {r["pitch"]}' for r in ranked[:4]]
        comparison(output/'ranked.gif',columns,labels,'Chroma camera audit, no pose fit')
    serial=[{k:v for k,v in row.items() if k not in ('rgb','alpha','camera')} for row in ranked]
    report=dict(sourceSha256=sha256_file(source),skinSha256=sha256_file(skin_path),ranked=serial,
        policy='diagnostic only: one minus IoU plus overlapping normalized RGB L1; no default camera change')
    (output/'report.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(report,indent=2))


if __name__=='__main__':
    import argparse
    from pathlib import Path
    p=argparse.ArgumentParser()
    for n in ('skin','source','output'):p.add_argument('--'+n,type=Path,required=True)
    a=p.parse_args();audit(a.skin,a.source,a.output)
