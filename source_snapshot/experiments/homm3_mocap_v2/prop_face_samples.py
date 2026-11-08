"""Independent diagnostic face sampling for a proposed rigid prop mask."""
from __future__ import annotations

from typing import Any

import numpy as np

from propose_rigid_prop_mask import _annotation, _inside, color_gate, project_view, sample_albedo_uv


_BARYCENTRIC = np.asarray(
    [[1 / 3, 1 / 3, 1 / 3],
     [0.6, 0.2, 0.2], [0.2, 0.6, 0.2], [0.2, 0.2, 0.6],
     [0.45, 0.45, 0.1], [0.45, 0.1, 0.45], [0.1, 0.45, 0.45]], dtype=np.float64
)


def classify_prop_faces(*, vertices: Any, triangles: Any, uvs: Any, albedo: Any,
                        cameras: dict[str, Any], annotation: dict[str, Any],
                        minimum_samples: int = 5) -> dict[str, np.ndarray]:
    """Classify faces from seven per-face interior samples, without vertex mixing."""
    ann = _annotation(annotation)
    v = np.asarray(vertices, dtype=np.float64)
    f = np.asarray(triangles)
    tex_uv = np.asarray(uvs, dtype=np.float64)
    if v.ndim != 2 or v.shape[1] != 3 or not len(v) or not np.isfinite(v).all():
        raise ValueError("vertices must be finite nonempty [V,3]")
    if f.ndim != 2 or f.shape[1] != 3 or not np.issubdtype(f.dtype, np.integer) or (f < 0).any() or (f >= len(v)).any():
        raise ValueError("triangles must be integer [T,3] in vertex range")
    if tex_uv.shape != (len(v), 2) or not np.isfinite(tex_uv).all() or (tex_uv < 0).any() or (tex_uv > 1).any():
        raise ValueError("uvs must be finite [V,2] in [0,1]")
    if int(minimum_samples) < 1 or int(minimum_samples) > len(_BARYCENTRIC):
        raise ValueError("minimum_samples must be in [1,7]")
    # [T,7,3] keeps each face's UV seam and geometry local to that face.
    face_v = v[f]
    face_uv = tex_uv[f]
    points = np.einsum("sk,tkd->tsd", _BARYCENTRIC, face_v)
    sample_uv = np.einsum("sk,tkd->tsd", _BARYCENTRIC, face_uv)
    rgb = sample_albedo_uv(sample_uv.reshape(-1, 2), albedo).reshape(len(f), len(_BARYCENTRIC), 3)
    front = _inside((project_view(points.reshape(-1, 3), cameras, "front") * (200.0 / 256.0)), ann["viewPolygons"]["front"]).reshape(len(f), -1)
    side = _inside((project_view(points.reshape(-1, 3), cameras, "side") * (200.0 / 256.0)), ann["viewPolygons"]["side"]).reshape(len(f), -1)
    inside = front & side
    color = color_gate(rgb, ann)
    passed = inside & color
    counts = passed.sum(axis=1).astype(np.int64)
    accepted = counts >= int(minimum_samples)
    face_ids = np.flatnonzero(accepted).astype(np.int64)
    return {"faceIds": face_ids, "propTriangles": face_ids.copy(), "samplePassCounts": counts,
            "samplePoints": points, "sampleUvs": sample_uv, "sampleRgb": rgb, "samplePassed": passed}


def classify_faces(*, vertices: Any, triangles: Any, uvs: Any, albedo: Any,
                   cameras: dict[str, Any], annotation: dict[str, Any],
                   minimum_samples: int = 5) -> dict[str, np.ndarray]:
    """Runner-facing name for the same strict classifier."""
    return classify_prop_faces(vertices=vertices, triangles=triangles, uvs=uvs, albedo=albedo,
                               cameras=cameras, annotation=annotation, minimum_samples=minimum_samples)
