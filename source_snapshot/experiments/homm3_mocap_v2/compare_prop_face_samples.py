"""Compare vertex-only and interior-face prop masks; never modify the skin."""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from propose_rigid_prop_mask import _load_frozen_prep, _render_views, _sha, propose
from prop_face_samples import classify_faces


def run(asset: str, annotation_path: Path, output: Path) -> None:
    if output.exists():
        raise FileExistsError(output)
    started = time.perf_counter()
    annotation = json.loads(annotation_path.read_text())
    baseline, report = propose(asset, annotation)
    skin, _, skin_path = _load_frozen_prep(asset)
    result = classify_faces(vertices=skin["vertices"], triangles=skin["triangles"],
                            uvs=skin["uvs"], albedo=skin["albedo"],
                            cameras=report["camera"], annotation=annotation)
    faces = np.asarray(result["propTriangles"], dtype=np.int64)
    if not len(faces):
        raise ValueError("empty interior-face proposal")
    output.mkdir(parents=True)
    for label, selection in (("vertex", baseline), ("face", result)):
        directory = output / label
        directory.mkdir()
        _render_views(directory, skin, report["camera"], selection)
    sheet = Image.new("RGB", (3 * 256, 3 * 280), (18,18,18))
    draw = ImageDraw.Draw(sheet)
    for row, view in enumerate(("front","side","top")):
        for col, (directory, suffix, label) in enumerate((("vertex","before","texture"), ("vertex","highlight","vertex mask"), ("face","highlight","interior-face mask"))):
            draw.text((col*256+4,row*280+4), f"{view}: {label}", fill=(240,240,240))
            with Image.open(output / directory / f"{view}_{suffix}.png") as panel:
                sheet.paste(panel, (col*256,row*280+24))
    sheet.save(output / "comparison.png")
    np.savez(output / "face_proposal.npz", **result)
    previous = set(baseline["propTriangles"].tolist())
    current = set(faces.tolist())
    report["vertexBaseline"] = {key: report.pop(key) for key in (
        "selectedVertexCount", "propTriangleCount", "boundaryTriangleCount",
        "ownerWeightDistribution", "selectedBoundsMin", "selectedBoundsMax")}
    report.update({"proof":"diagnostic-face-sampling-comparison", "accepted":False,
                   "vertexMaskFaceCount":len(previous), "interiorMaskFaceCount":len(current),
                   "addedFaces":len(current-previous), "removedFaces":len(previous-current),
                   "annotationSha256":_sha(annotation_path),
                   "maskSha256":_sha(output / "face_proposal.npz"),
                   "researchSkinUnchanged":_sha(skin_path)==report["researchSkinSha256"],
                   "comparisonImplementationSha256":_sha(Path(__file__)),
                   "classifierImplementationSha256":_sha(Path(__file__).with_name("prop_face_samples.py")),
                   "elapsedSeconds":time.perf_counter()-started})
    (output / "report.json").write_text(json.dumps(report,indent=2))
    print(json.dumps({k:report[k] for k in ("asset","vertexMaskFaceCount","interiorMaskFaceCount","addedFaces","removedFaces","elapsedSeconds")}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--asset",required=True)
    parser.add_argument("--annotation",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    args = parser.parse_args()
    run(args.asset,args.annotation,args.output)
