"""Diagnostic proposal of a texture- and two-view-constrained rigid prop mask.

This module only proposes vertices/faces.  It never edits skin weights or bind
metadata; an accepted rigid attachment needs a separate reviewed contract.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw

from shared_camera import freeze_shared_camera, project_view
import run_shape_preserved as shared
from eagle_preview import _mesh as render_mesh
from mesh_preview import raster_mesh


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _annotation(value: Any, *, asset: str | None = None, research_hash: str | None = None) -> dict[str, Any]:
    if not isinstance(value, dict) or value.get("schema") != 1:
        raise ValueError("annotation schema must be integer 1")
    if not isinstance(value.get("prop"), str) or not value["prop"].strip():
        raise ValueError("annotation prop must be a nonempty string")
    if asset is not None and value.get("asset") != asset:
        raise ValueError("annotation asset does not match requested asset")
    if research_hash is not None and value.get("researchSkinSha256") != research_hash:
        raise ValueError("annotation researchSkinSha256 does not match frozen skin")
    views = value.get("viewPolygons")
    if not isinstance(views, dict) or set(views) != {"front", "side"}:
        raise ValueError("viewPolygons must contain exactly front and side")
    for name, points in views.items():
        if not isinstance(points, list) or len(points) < 3:
            raise ValueError(f"{name} polygon must contain at least three points")
        for point in points:
            if not isinstance(point, list) or len(point) != 2 or not all(isinstance(x, (int, float)) and np.isfinite(x) for x in point):
                raise ValueError(f"{name} polygon contains an invalid point")
            if not (0 <= float(point[0]) <= 200 and 0 <= float(point[1]) <= 200):
                raise ValueError(f"{name} polygon point lies outside 200x200 panel")
    spread = value.get("rgbMaxSpread")
    mean_range = value.get("rgbMeanRange")
    if not isinstance(spread, (int, float)) or not np.isfinite(spread) or not (0 < float(spread) <= 1):
        raise ValueError("rgbMaxSpread must be finite and in (0,1]")
    if not isinstance(mean_range, list) or len(mean_range) != 2 or not all(isinstance(x, (int, float)) and np.isfinite(x) for x in mean_range):
        raise ValueError("rgbMeanRange must be [lo,hi]")
    if not (0 <= mean_range[0] <= mean_range[1] <= 1):
        raise ValueError("rgbMeanRange must be ordered in [0,1]")
    if "channelOrder" in value or "channelMinGap" in value:
        order = value.get("channelOrder")
        gap = value.get("channelMinGap")
        if not isinstance(order, list) or len(order) != 3 or sorted(order) != [0, 1, 2]:
            raise ValueError("channelOrder must be a permutation of [0,1,2]")
        if not isinstance(gap, (int, float)) or not np.isfinite(gap) or not 0 <= float(gap) <= 1:
            raise ValueError("channelMinGap must be finite and in [0,1]")
    return value


def color_gate(rgb: np.ndarray, annotation: dict[str, Any]) -> np.ndarray:
    """Apply the shared RGB spread/mean gate and optional ordered-channel gate."""
    values = np.asarray(rgb, dtype=np.float64)
    spread = values.max(axis=-1) - values.min(axis=-1)
    mean = values.mean(axis=-1)
    result = (spread <= float(annotation["rgbMaxSpread"])) & (mean >= float(annotation["rgbMeanRange"][0])) & (mean <= float(annotation["rgbMeanRange"][1]))
    if "channelOrder" in annotation or "channelMinGap" in annotation:
        order = annotation["channelOrder"]
        gap = float(annotation["channelMinGap"])
        ordered = values[..., order]
        result &= (ordered[..., 0] - ordered[..., 1] >= gap) & (ordered[..., 1] - ordered[..., 2] >= gap)
    return result


def sample_albedo_uv(uvs: np.ndarray, albedo: np.ndarray) -> np.ndarray:
    uv = np.asarray(uvs, dtype=np.float64)
    image = np.asarray(albedo)
    if uv.ndim != 2 or uv.shape[1] != 2 or image.ndim != 3 or image.shape[2] < 3:
        raise ValueError("invalid UV/albedo shapes")
    if not np.isfinite(uv).all() or (uv < 0).any() or (uv > 1).any():
        raise ValueError("UVs must be finite and in [0,1]")
    # The prepared glTF uses the first-row texture convention for these audits.
    x = np.clip(np.floor(uv[:, 0] * image.shape[1]).astype(int), 0, image.shape[1] - 1)
    y = np.clip(np.floor(uv[:, 1] * image.shape[0]).astype(int), 0, image.shape[0] - 1)
    return image[y, x, :3].astype(np.float64) / 255.0


def _inside(points: np.ndarray, polygon: list[list[float]]) -> np.ndarray:
    image = Image.new("1", (201, 201), 0)
    draw = ImageDraw.Draw(image)
    draw.polygon([(float(x), float(y)) for x, y in polygon], fill=1)
    xy = np.floor(np.asarray(points, dtype=np.float64)).astype(int)
    result = np.zeros(len(xy), dtype=bool)
    valid = (xy[:, 0] >= 0) & (xy[:, 0] <= 200) & (xy[:, 1] >= 0) & (xy[:, 1] <= 200)
    result[valid] = np.asarray(image)[xy[valid, 1], xy[valid, 0]].astype(bool)
    return result


def propose_mask(*, vertices: np.ndarray, triangles: np.ndarray, uvs: np.ndarray,
                 albedo: np.ndarray, cameras: dict[str, Any], annotation: dict[str, Any]) -> dict[str, np.ndarray]:
    ann = _annotation(annotation)
    v = np.asarray(vertices, dtype=np.float64)
    f = np.asarray(triangles)
    if v.ndim != 2 or v.shape[1] != 3 or not len(v) or not np.isfinite(v).all():
        raise ValueError("vertices must be finite [V,3]")
    if f.ndim != 2 or f.shape[1] != 3 or not np.issubdtype(f.dtype, np.integer) or (f < 0).any() or (f >= len(v)).any():
        raise ValueError("triangles must be integer [T,3] in vertex range")
    rgb = sample_albedo_uv(uvs, albedo)
    front = project_view(v, cameras, "front") * (200.0 / 256.0)
    side = project_view(v, cameras, "side") * (200.0 / 256.0)
    view_ok = _inside(front, ann["viewPolygons"]["front"]) & _inside(side, ann["viewPolygons"]["side"])
    color_ok = color_gate(rgb, ann)
    selected = view_ok & color_ok
    prop = np.flatnonzero(selected[f].all(axis=1)).astype(np.int64)
    mixed = selected[f].any(axis=1) & ~selected[f].all(axis=1)
    boundary = np.flatnonzero(mixed).astype(np.int64)
    return {"selectedVertices": np.flatnonzero(selected).astype(np.int64),
            "propTriangles": prop, "boundaryTriangles": boundary,
            "viewSelected": view_ok, "colorSelected": color_ok}


def _load_frozen_prep(asset: str) -> tuple[dict[str, Any], dict[str, Any], Path]:
    freeze, loaded = shared._load_frozen_prep(asset)
    skin_path = Path(freeze["researchSkin"])
    return loaded, freeze, skin_path


def propose(asset: str, annotation: dict[str, Any]) -> tuple[dict[str, np.ndarray], dict[str, Any]]:
    skin, freeze, skin_path = _load_frozen_prep(asset)
    annotation = _annotation(annotation, asset=asset, research_hash=_sha(skin_path))
    names = np.asarray(skin["names"])
    inverse = np.asarray(skin["inverseBind"], dtype=np.float64)
    joints = np.linalg.inv(inverse)[:, :3, 3]
    camera = freeze_shared_camera(np.concatenate([skin["vertices"], joints]), width=256, height=256, space="targetBindSpace")
    result = propose_mask(vertices=skin["vertices"], triangles=skin["triangles"], uvs=skin["uvs"], albedo=skin["albedo"], cameras=camera, annotation=annotation)
    selected = result["selectedVertices"]
    owner_means = {str(name): (float(skin["weights"][selected, i].mean()) if len(selected) else None)
                   for i, name in enumerate(skin["names"])}
    report = {"schema": 1, "asset": asset, "prop": annotation["prop"], "proof": "diagnostic-proposal",
              "researchSkinSha256": _sha(skin_path), "selectedVertexCount": int(len(selected)),
              "propTriangleCount": int(len(result["propTriangles"])), "boundaryTriangleCount": int(len(result["boundaryTriangles"])),
              "ownerWeightDistribution": owner_means,
              "selectedBoundsMin": np.asarray(skin["vertices"])[selected].min(axis=0).tolist() if len(selected) else None,
              "selectedBoundsMax": np.asarray(skin["vertices"])[selected].max(axis=0).tolist() if len(selected) else None,
              "camera": camera, "annotation": annotation, "accepted": False, "weightsChanged": False,
              "jointNames": names.tolist(), "implementationSha256": _sha(Path(__file__))}
    return result, report


def _render_views(output: Path, skin: dict[str, np.ndarray], camera: dict[str, Any], result: dict[str, np.ndarray]) -> None:
    """Render diagnostic before/highlight panels with the same frozen camera."""
    prop = np.zeros(len(skin["triangles"]), dtype=bool)
    prop[result["propTriangles"]] = True
    for view in ("front", "side", "top"):
        before = render_mesh(camera, view, skin["vertices"], skin["triangles"], skin["uvs"], skin["albedo"])
        # Expand every face so one atlas texel can identify selected faces.
        # Rendering the complete expanded mesh keeps one depth buffer for body
        # and prop faces; selected-only compositing would allow false overlays.
        faces = np.asarray(skin["triangles"], dtype=np.int64)
        expanded = skin["vertices"][faces].reshape(-1, 3)
        expanded_faces = np.arange(len(expanded), dtype=np.int64).reshape(-1, 3)
        # CPU sampler maps u to u*(width-1), unlike the CUDA texel-center sampler.
        expanded_uv = np.zeros((len(expanded), 2), dtype=np.float64)
        expanded_uv[:, 0] = np.repeat(prop.astype(np.float64), 3)
        expanded_uv[:, 1] = 0.5
        atlas = np.asarray([[[112, 112, 112, 255], [220, 65, 45, 255]]], dtype=np.uint8)
        highlighted = raster_mesh(vertices=expanded, triangles=expanded_faces, camera=camera[view], width=256, height=256, uvs=expanded_uv, albedo=atlas).convert("RGB")
        before.save(output / f"{view}_before.png")
        highlighted.save(output / f"{view}_highlight.png")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--asset", required=True)
    parser.add_argument("--annotation", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(f"refusing existing output: {args.output}")
    ann = json.loads(args.annotation.read_text(encoding="utf-8"))
    annotation_hash = _sha(args.annotation)
    skin, freeze, skin_path = _load_frozen_prep(args.asset)
    ann = _annotation(ann, asset=args.asset, research_hash=_sha(skin_path))
    result, report = propose(args.asset, ann)
    if not len(result["selectedVertices"]) or not len(result["propTriangles"]):
        raise ValueError("proposal is empty; annotation must be reviewed")
    args.output.mkdir(parents=True)
    np.savez(args.output / "rigid_prop_mask.npz", selectedVertices=result["selectedVertices"], propTriangles=result["propTriangles"], boundaryTriangles=result["boundaryTriangles"])
    _render_views(args.output, skin, report["camera"], result)
    report["maskSha256"] = _sha(args.output / "rigid_prop_mask.npz")
    report["annotationSha256"] = annotation_hash
    (args.output / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")


if __name__ == "__main__":
    main()
