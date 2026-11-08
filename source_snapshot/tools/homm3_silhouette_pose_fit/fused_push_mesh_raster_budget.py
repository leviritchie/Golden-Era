"""Size fused-push packed raster from mesh properties, not GPU-VRAM probing.

Packed ``evaluate`` skins every vertex for every pose slot, then rasters
capped triangles into a chroma-upsampled grid. A dense Goblin-class GLB
must get a smaller pack than a Cavalier-class GLB automatically.

``--memory-safe`` / ``--gpu-fed`` remain explicit constant overrides.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

# Same cap the GPU cascade applies per primitive before nvdiffrast.
DEFAULT_MAX_TRIANGLES_PER_PRIMITIVE = 2048

# Chroma 3 is the quality default when the mesh is light enough.
CHROMA_QUALITY = 3
CHROMA_TIGHT = 2

# LBS peak scales with pose_slots * vertices (see gpu_mesh_collision LBS note).
# 768 slots on a Cavalier-class (~28k vert) mesh is the packed ceiling.
# A denser Stronghold mesh must shrink slots so slots * load stays under this.
LBS_POSE_VERTEX_CAP = 768 * 28_000

# Chroma buffers scale with slots * chroma_scale^2. 768×3^2 spilled into the
# shared pool; 512×3^2 did not. Cap at 512 chroma-3 equivalents.
CHROMA_SLOT_SCALE_CAP = 512 * (CHROMA_QUALITY ** 2)

# Prefer chroma 3 only when that pack still holds this many clip-length hyps
# and the skeleton is not a high-search-bone mesh (Goblin-class ~80 joints).
MIN_QUALITY_HYPS = 12
MAX_JOINTS_FOR_QUALITY_CHROMA = 64

# Packed batch never exceeds this unless an explicit --gpu-fed override.
BATCH_SLOT_CEILING = 768
BATCH_SLOT_FLOOR_HYPS = 1


@dataclass(frozen=True)
class MeshRasterStats:
    path: str
    vertex_count: int
    raster_triangle_count: int
    primitive_count: int
    skinned_joint_count: int


def primitive_triangle_count(indices: np.ndarray | None, vertex_count: int) -> int:
    verts = int(vertex_count)
    if verts < 0:
        raise ValueError("vertex_count must be non-negative")
    if indices is None:
        return (verts // 3)
    faces = np.asarray(indices, dtype=np.int64).reshape(-1)
    if faces.size % 3 != 0:
        raise ValueError("triangle indices length must be a multiple of 3")
    tris = faces.reshape(-1, 3)
    return int((tris >= 0).all(axis=1).sum())


def raster_triangle_count_for_primitives(
    primitives: Sequence[Any],
    *,
    max_triangles_per_primitive: int = DEFAULT_MAX_TRIANGLES_PER_PRIMITIVE,
) -> int:
    cap = int(max_triangles_per_primitive)
    if cap < 1:
        raise ValueError("max_triangles_per_primitive must be positive")
    total = 0
    for primitive in primitives:
        positions = getattr(primitive, "positions")
        vertex_count = int(len(positions))
        faces = primitive_triangle_count(getattr(primitive, "indices", None), vertex_count)
        total += min(faces, cap)
    return int(total)


def skinned_joint_count_for_asset(asset: Any) -> int:
    names: set[int] = set()
    skins = tuple(getattr(asset, "skins", ()) or ())
    for skin in skins:
        for joint in tuple(getattr(skin, "joints", ()) or ()):
            names.add(int(joint))
    if names:
        return len(names)
    # Fail closed if the GLB has primitives but no skin joints to search.
    primitives = tuple(getattr(asset, "primitives", ()) or ())
    if primitives:
        raise ValueError("skinned mesh has primitives but no skin joints")
    raise ValueError("mesh has no skins")


def inspect_mesh_raster_stats(
    path: str | Path,
    *,
    max_triangles_per_primitive: int = DEFAULT_MAX_TRIANGLES_PER_PRIMITIVE,
) -> MeshRasterStats:
    from roc_geometric_proxy import load_asset

    mesh = Path(path)
    if not mesh.is_file():
        raise FileNotFoundError(f"mesh GLB missing: {mesh}")
    asset = load_asset(mesh, decode_images=False)
    primitives = tuple(asset.primitives)
    if not primitives:
        raise ValueError(f"mesh has no primitives: {mesh}")
    vertices = int(sum(len(primitive.positions) for primitive in primitives))
    if vertices < 1:
        raise ValueError(f"mesh has no vertices: {mesh}")
    return MeshRasterStats(
        path=str(mesh.resolve()),
        vertex_count=vertices,
        raster_triangle_count=raster_triangle_count_for_primitives(
            primitives,
            max_triangles_per_primitive=max_triangles_per_primitive,
        ),
        primitive_count=len(primitives),
        skinned_joint_count=skinned_joint_count_for_asset(asset),
    )


def _lbs_load(*, vertex_count: int, raster_triangle_count: int, primitive_count: int, skinned_joint_count: int) -> int:
    verts = int(vertex_count)
    tris = int(raster_triangle_count)
    prims = int(primitive_count)
    joints = int(skinned_joint_count)
    if min(verts, tris, prims, joints) < 1:
        raise ValueError("mesh raster stats must be positive")
    # Extra primitives (detached weapons / UV shells) and extra joints
    # lengthen the GPU walk; charge them as extra vertices so the pack shrinks.
    return verts + (4 * tris) + (400 * prims) + (80 * joints)


def _slots_for_chroma(
    *,
    lbs_load: int,
    chroma_scale: int,
    frame_count: int,
    slot_ceiling: int,
) -> int:
    frames = int(frame_count)
    chroma = int(chroma_scale)
    ceiling = int(slot_ceiling)
    if frames < 1:
        raise ValueError("frame_count must be at least 1")
    if chroma < 2:
        raise ValueError("chroma_scale must be at least 2")
    if ceiling < frames:
        raise ValueError("slot_ceiling must cover at least one packed clip")
    lbs_slots = max(BATCH_SLOT_FLOOR_HYPS, int(LBS_POSE_VERTEX_CAP // max(1, lbs_load)))
    chroma_slots = max(BATCH_SLOT_FLOOR_HYPS, int(CHROMA_SLOT_SCALE_CAP // (chroma * chroma)))
    raw = min(lbs_slots, chroma_slots, ceiling)
    hyps = max(BATCH_SLOT_FLOOR_HYPS, raw // frames)
    slots = hyps * frames
    if slots > ceiling:
        hyps = max(BATCH_SLOT_FLOOR_HYPS, ceiling // frames)
        slots = hyps * frames
    if slots < frames:
        raise RuntimeError("packed raster budget collapsed below one hypothesis")
    return int(slots)


def choose_batch_raster(
    *,
    vertex_count: int,
    raster_triangle_count: int,
    primitive_count: int,
    skinned_joint_count: int,
    frame_count: int,
    slot_ceiling: int = BATCH_SLOT_CEILING,
) -> dict[str, Any]:
    """Return ``joint_score_raster_batch`` and ``chroma_scale`` for this mesh+clip."""
    load = _lbs_load(
        vertex_count=vertex_count,
        raster_triangle_count=raster_triangle_count,
        primitive_count=primitive_count,
        skinned_joint_count=skinned_joint_count,
    )
    # Prefer chroma 3 when both caps still leave a packed launch.
    quality = _slots_for_chroma(
        lbs_load=load,
        chroma_scale=CHROMA_QUALITY,
        frame_count=frame_count,
        slot_ceiling=slot_ceiling,
    )
    tight = _slots_for_chroma(
        lbs_load=load,
        chroma_scale=CHROMA_TIGHT,
        frame_count=frame_count,
        slot_ceiling=slot_ceiling,
    )
    quality_hyps = quality // int(frame_count)
    tight_hyps = tight // int(frame_count)
    high_search = int(skinned_joint_count) > MAX_JOINTS_FOR_QUALITY_CHROMA
    if (not high_search) and quality_hyps >= MIN_QUALITY_HYPS:
        chroma = CHROMA_QUALITY
        slots = quality
    else:
        chroma = CHROMA_TIGHT
        slots = tight
        if tight_hyps < 4:
            chroma = CHROMA_TIGHT
            slots = tight
    return {
        "joint_score_raster_batch": int(slots),
        "chroma_scale": int(chroma),
        "meshRasterLoad": int(load),
        "meshVertexCount": int(vertex_count),
        "meshRasterTriangles": int(raster_triangle_count),
        "meshPrimitiveCount": int(primitive_count),
        "meshSkinnedJoints": int(skinned_joint_count),
        "clipFrameCount": int(frame_count),
        "jointScoreHypsPerLaunch": int(slots // int(frame_count)),
    }


def choose_batch_raster_from_glb(
    mesh: str | Path,
    *,
    frame_count: int,
    max_triangles_per_primitive: int = DEFAULT_MAX_TRIANGLES_PER_PRIMITIVE,
) -> dict[str, Any]:
    stats = inspect_mesh_raster_stats(
        mesh,
        max_triangles_per_primitive=max_triangles_per_primitive,
    )
    chosen = choose_batch_raster(
        vertex_count=stats.vertex_count,
        raster_triangle_count=stats.raster_triangle_count,
        primitive_count=stats.primitive_count,
        skinned_joint_count=stats.skinned_joint_count,
        frame_count=frame_count,
    )
    chosen["meshPath"] = stats.path
    return chosen


def apply_mesh_raster_budget(
    kwargs: Mapping[str, Any],
    mesh: str | Path,
    *,
    frame_count: int,
) -> dict[str, Any]:
    chosen = choose_batch_raster_from_glb(mesh, frame_count=frame_count)
    updated = dict(kwargs)
    updated["joint_score_raster_batch"] = int(chosen["joint_score_raster_batch"])
    updated["chroma_scale"] = int(chosen["chroma_scale"])
    return updated, chosen
