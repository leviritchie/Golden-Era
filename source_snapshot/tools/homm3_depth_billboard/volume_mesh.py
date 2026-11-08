"""Mesh extraction from anchored VDA depth volumes.

Two lanes:

- ``front_shell`` (default): full-resolution depth surface + silhouette skirt/back cap.
- ``voxel``: coarse occupancy grid + marching cubes (fast prototype).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import numpy as np

from geometry import AnchoredZSurfaces, compute_anchored_z_surfaces

MeshStyle = Literal["front_shell", "voxel"]


@dataclass(frozen=True)
class VolumeMesh:
    """Triangle mesh in billboard object space (sprite height = 1)."""

    vertices: np.ndarray
    faces: np.ndarray
    normals: np.ndarray
    uvs: np.ndarray
    vertex_rgba: np.ndarray
    width: int
    height: int


def _coarse_cell_bounds(length: int, index: int, stride: int) -> tuple[int, int]:
    start = index * stride
    end = min(length, start + stride)
    return start, end


def build_coarse_occupancy(
    surfaces: AnchoredZSurfaces,
    *,
    cell_stride: int = 4,
    z_layers_max: int = 24,
) -> tuple[np.ndarray, np.ndarray]:
    """Build a coarse (Gy, Gx, Gz) occupancy grid from anchored Z surfaces."""
    if cell_stride < 1:
        raise ValueError("cell_stride must be >= 1")
    if z_layers_max < 2:
        raise ValueError("z_layers_max must be >= 2")

    height, width = surfaces.height, surfaces.width
    gy = int(np.ceil(height / cell_stride))
    gx = int(np.ceil(width / cell_stride))

    z_min = float(np.nanmin(surfaces.z_back))
    z_max = float(np.nanmax(surfaces.z_front))
    z_span = max(z_max - z_min, 1e-6)
    gz = int(min(z_layers_max, max(2, int(np.ceil(z_span * height / cell_stride)))))
    z_step = z_span / float(gz - 1)

    occupancy = np.zeros((gy, gx, gz), dtype=np.float32)
    for iy in range(gy):
        y0, y1 = _coarse_cell_bounds(height, iy, cell_stride)
        for ix in range(gx):
            x0, x1 = _coarse_cell_bounds(width, ix, cell_stride)
            block_mask = surfaces.mask[y0:y1, x0:x1]
            if not block_mask.any():
                continue
            z_front = float(np.nanmax(surfaces.z_front[y0:y1, x0:x1]))
            z_back = float(np.nanmin(surfaces.z_back[y0:y1, x0:x1]))
            lo = int(np.floor((z_back - z_min) / z_step))
            hi = int(np.ceil((z_front - z_min) / z_step))
            lo = max(0, min(gz - 1, lo))
            hi = max(0, min(gz - 1, hi))
            if hi < lo:
                continue
            occupancy[iy, ix, lo : hi + 1] = 1.0

    meta = np.array(
        [
            float(cell_stride),
            float(z_min),
            float(z_step),
            float(width),
            float(height),
        ],
        dtype=np.float64,
    )
    return occupancy, meta


def _voxel_vertices_to_world(
    verts: np.ndarray,
    meta: np.ndarray,
) -> np.ndarray:
    stride, z_min, z_step, width, height = meta
    aspect = float(width) / float(height)
    iy = verts[:, 0]
    ix = verts[:, 1]
    iz = verts[:, 2]
    col = ix * stride + (stride * 0.5)
    row = iy * stride + (stride * 0.5)
    x = (col / float(width) - 0.5) * aspect
    y = 0.5 - (row / float(height))
    z = z_min + iz * z_step
    return np.column_stack((x, y, z)).astype(np.float32, copy=False)


def _sprite_uv_from_world(
    vertices: np.ndarray,
    width: int,
    height: int,
) -> np.ndarray:
    aspect = float(width) / float(height)
    col = (vertices[:, 0] / aspect + 0.5) * float(width)
    row = (0.5 - vertices[:, 1]) * float(height)
    u = np.clip(col / float(width), 0.0, 1.0)
    v = np.clip(1.0 - (row / float(height)), 0.0, 1.0)
    return np.column_stack((u, v)).astype(np.float32, copy=False)


def _vertex_rgba_from_sprite(
    vertices: np.ndarray,
    rgba: np.ndarray,
    width: int,
    height: int,
) -> np.ndarray:
    """Nearest opaque sprite sample per vertex (avoids fringe bilinear washout)."""
    aspect = float(width) / float(height)
    col = np.clip(np.round((vertices[:, 0] / aspect + 0.5) * float(width)), 0, width - 1)
    row = np.clip(np.round((0.5 - vertices[:, 1]) * float(height)), 0, height - 1)
    colors = np.zeros((vertices.shape[0], 4), dtype=np.uint8)
    for index, (r, c) in enumerate(zip(row.astype(np.int64), col.astype(np.int64))):
        r0 = max(0, r - 2)
        r1 = min(height, r + 3)
        c0 = max(0, c - 2)
        c1 = min(width, c + 3)
        patch = rgba[r0:r1, c0:c1]
        opaque = patch[patch[..., 3] > 128]
        if opaque.size:
            mean = opaque.mean(axis=0)
            colors[index] = np.clip(np.rint(mean), 0, 255).astype(np.uint8)
        else:
            mask = rgba[..., 3] > 128
            cy = int(np.round(np.mean(np.nonzero(mask)[0])))
            cx = int(np.round(np.mean(np.nonzero(mask)[1])))
            colors[index] = rgba[cy, cx]
    return colors


def _compute_vertex_normals(vertices: np.ndarray, faces: np.ndarray) -> np.ndarray:
    face_normals = np.cross(
        vertices[faces[:, 1]] - vertices[faces[:, 0]],
        vertices[faces[:, 2]] - vertices[faces[:, 0]],
    )
    lengths = np.linalg.norm(face_normals, axis=1)
    valid = lengths > 1e-8
    face_normals[valid] /= lengths[valid][:, None]
    vertex_normals = np.zeros_like(vertices)
    for idx, face in enumerate(faces):
        if not valid[idx]:
            continue
        for corner in face:
            vertex_normals[corner] += face_normals[idx]
    lengths = np.linalg.norm(vertex_normals, axis=1)
    valid_v = lengths > 1e-8
    vertex_normals[valid_v] /= lengths[valid_v][:, None]
    return vertex_normals.astype(np.float32, copy=False)


def _pixel_xyz(
    rows: np.ndarray,
    cols: np.ndarray,
    z: np.ndarray,
    height: int,
    width: int,
) -> np.ndarray:
    aspect = float(width) / float(height)
    xs = ((cols.astype(np.float32) + 0.5) / float(width) - 0.5) * aspect
    ys = 0.5 - (rows.astype(np.float32) + 0.5) / float(height)
    return np.column_stack((xs, ys, z.astype(np.float32, copy=False))).astype(
        np.float32, copy=False
    )


def _pixel_uv(rows: np.ndarray, cols: np.ndarray, height: int, width: int) -> np.ndarray:
    u = (cols.astype(np.float32) + 0.5) / float(width)
    v = 1.0 - (rows.astype(np.float32) + 0.5) / float(height)
    return np.column_stack((u, v)).astype(np.float32, copy=False)


def _triangulate_index_grid(grid: np.ndarray) -> list[tuple[int, int, int]]:
    """Triangulate a 2D index grid (-1 = missing vertex)."""
    height, width = grid.shape
    faces: list[tuple[int, int, int]] = []
    for row in range(height - 1):
        for col in range(width - 1):
            i00 = int(grid[row, col])
            i10 = int(grid[row, col + 1])
            i11 = int(grid[row + 1, col + 1])
            i01 = int(grid[row + 1, col])
            if min(i00, i10, i11, i01) >= 0:
                faces.append((i00, i10, i11))
                faces.append((i00, i11, i01))
                continue
            missing = sum(1 for idx in (i00, i10, i11, i01) if idx < 0)
            if missing != 1:
                continue
            if i00 < 0:
                faces.append((i10, i11, i01))
            elif i10 < 0:
                faces.append((i00, i11, i01))
            elif i11 < 0:
                faces.append((i00, i10, i01))
            elif i01 < 0:
                faces.append((i00, i10, i11))
    return faces


def _filter_bilateral_wing_faces(
    faces: list[tuple[int, int, int]],
    uvs: np.ndarray,
    mask: np.ndarray,
    spine_x: float,
    upper_row_fraction: float,
    gap_half_width: int = 6,
) -> list[tuple[int, int, int]]:
    """Drop triangles that bridge left/right wings across a transparent spine gap."""
    height, width = mask.shape
    upper_end = int(height * float(upper_row_fraction))
    kept: list[tuple[int, int, int]] = []
    for a, b, c in faces:
        tri_uvs = uvs[[a, b, c]]
        rows = (1.0 - tri_uvs[:, 1]) * height - 0.5
        cols = tri_uvs[:, 0] * width - 0.5
        min_row = int(np.floor(float(rows.min())))
        if min_row >= upper_end:
            kept.append((a, b, c))
            continue
        col_min, col_max = float(cols.min()), float(cols.max())
        if col_min >= spine_x - 2.0 or col_max <= spine_x + 2.0:
            kept.append((a, b, c))
            continue
        gap_left = int(max(0, spine_x - gap_half_width))
        gap_right = int(min(width - 1, spine_x + gap_half_width))
        row_lo = max(0, min_row)
        row_hi = min(height, int(np.ceil(float(rows.max()))) + 1)
        has_gap = any(
            not mask[row, gap_left:gap_right + 1].any()
            for row in range(row_lo, row_hi)
            if row < upper_end
        )
        if has_gap:
            continue
        kept.append((a, b, c))
    return kept


def _sample_block(
    surfaces: AnchoredZSurfaces,
    row: int,
    col: int,
    stride: int,
) -> tuple[int, int, float, float, np.ndarray] | None:
    row_end = min(surfaces.height, row + stride)
    col_end = min(surfaces.width, col + stride)
    block_mask = surfaces.mask[row:row_end, col:col_end]
    if not block_mask.any():
        return None
    z_front = float(np.nanmax(surfaces.z_front[row:row_end, col:col_end]))
    z_back = float(np.nanmin(surfaces.z_back[row:row_end, col:col_end]))
    center_row = row + (stride - 1) // 2
    center_col = col + (stride - 1) // 2
    center_row = min(center_row, surfaces.height - 1)
    center_col = min(center_col, surfaces.width - 1)
    rgba = surfaces.rgba[center_row, center_col].copy()
    if rgba[3] < 32:
        opaque = surfaces.rgba[row:row_end, col:col_end][block_mask]
        rgba = np.clip(np.rint(opaque.mean(axis=0)), 0, 255).astype(np.uint8)
    return center_row, center_col, z_front, z_back, rgba


def build_front_shell_mesh(
    surfaces: AnchoredZSurfaces,
    *,
    grid_stride: int = 1,
    include_back_cap: bool = True,
    bilateral_wing_mesh_split: bool = False,
    depth_wing_lateral_upper_fraction: float = 0.5,
    depth_wing_lateral_body_lower_fraction: float = 0.5,
) -> VolumeMesh:
    """Full-res VDA front surface + silhouette skirt (and optional back cap)."""
    if grid_stride < 1:
        raise ValueError("grid_stride must be >= 1")

    from scipy.ndimage import binary_erosion

    sample_rows = np.arange(0, surfaces.height, grid_stride, dtype=np.int32)
    sample_cols = np.arange(0, surfaces.width, grid_stride, dtype=np.int32)
    grid_h = int(sample_rows.size)
    grid_w = int(sample_cols.size)

    front_grid = np.full((grid_h, grid_w), -1, dtype=np.int32)
    back_grid = np.full((grid_h, grid_w), -1, dtype=np.int32)
    mask_grid = np.zeros((grid_h, grid_w), dtype=bool)

    vertices: list[np.ndarray] = []
    uvs: list[np.ndarray] = []
    vertex_rgba: list[np.ndarray] = []

    def _add_vertex(row: int, col: int, z: float, rgba: np.ndarray) -> int:
        xyz = _pixel_xyz(
            np.array([row], dtype=np.int32),
            np.array([col], dtype=np.int32),
            np.array([z], dtype=np.float32),
            surfaces.height,
            surfaces.width,
        )[0]
        uv = _pixel_uv(
            np.array([row], dtype=np.int32),
            np.array([col], dtype=np.int32),
            surfaces.height,
            surfaces.width,
        )[0]
        vertices.append(xyz)
        uvs.append(uv)
        vertex_rgba.append(rgba.astype(np.uint8, copy=True))
        return len(vertices) - 1

    for gy, row in enumerate(sample_rows):
        for gx, col in enumerate(sample_cols):
            sampled = _sample_block(surfaces, int(row), int(col), grid_stride)
            if sampled is None:
                continue
            center_row, center_col, z_front, z_back, rgba = sampled
            mask_grid[gy, gx] = True
            front_grid[gy, gx] = _add_vertex(center_row, center_col, z_front, rgba)
            back_grid[gy, gx] = _add_vertex(center_row, center_col, z_back, rgba)

    faces: list[tuple[int, int, int]] = []
    faces.extend(_triangulate_index_grid(front_grid))

    if include_back_cap:
        for a, b, c in _triangulate_index_grid(back_grid):
            faces.append((a, c, b))

    interior = binary_erosion(mask_grid)
    boundary = mask_grid & ~interior
    for gy in range(grid_h):
        for gx in range(grid_w):
            if not boundary[gy, gx]:
                continue
            ff = int(front_grid[gy, gx])
            bf = int(back_grid[gy, gx])
            for dgy, dgx in ((0, 1), (1, 0)):
                ngy = gy + dgy
                ngx = gx + dgx
                if ngy >= grid_h or ngx >= grid_w or not boundary[ngy, ngx]:
                    continue
                ff1 = int(front_grid[ngy, ngx])
                bf1 = int(back_grid[ngy, ngx])
                faces.append((ff, ff1, bf1))
                faces.append((ff, bf1, bf))

    if not faces:
        raise ValueError("front shell produced no triangles")

    uv_array = np.asarray(uvs, dtype=np.float32)
    if bilateral_wing_mesh_split:
        from fill import _estimate_spine_col

        spine_x = _estimate_spine_col(
            surfaces.mask,
            body_lower_fraction=depth_wing_lateral_body_lower_fraction,
        )
        faces = _filter_bilateral_wing_faces(
            faces,
            uv_array,
            surfaces.mask,
            spine_x,
            depth_wing_lateral_upper_fraction,
        )
        if not faces:
            raise ValueError("bilateral wing mesh split removed all triangles")

    vertex_array = np.asarray(vertices, dtype=np.float32)
    face_array = np.asarray(faces, dtype=np.int32)
    normal_array = _compute_vertex_normals(vertex_array, face_array)
    return VolumeMesh(
        vertices=vertex_array,
        faces=face_array,
        normals=normal_array,
        uvs=np.asarray(uvs, dtype=np.float32),
        vertex_rgba=np.asarray(vertex_rgba, dtype=np.uint8),
        width=surfaces.width,
        height=surfaces.height,
    )


def extract_front_shell_mesh(
    rgba: np.ndarray,
    depth01: np.ndarray,
    *,
    depth_scale: float = 0.25,
    gap_close_radius: int = 1,
    depth_smooth_radius: int = 1,
    thickness_scale: float = 2.0,
    depth_edge_strength: float = 0.0,
    depth_edge_falloff_pixels: float = 3.0,
    depth_bow_vertical_strength: float = 0.8,
    depth_bow_edge_strength: float = 0.85,
    depth_bow_local_radius: int = 7,
    depth_bow_edge_falloff_pixels: float = 3.0,
    depth_wing_lateral_strength: float = 0.0,
    depth_wing_lateral_upper_fraction: float = 0.5,
    depth_wing_lateral_body_lower_fraction: float = 0.5,
    grid_stride: int = 1,
    include_back_cap: bool = True,
) -> VolumeMesh:
    surfaces = compute_anchored_z_surfaces(
        rgba,
        depth01,
        depth_scale=depth_scale,
        gap_close_radius=gap_close_radius,
        depth_smooth_radius=depth_smooth_radius,
        thickness_scale=thickness_scale,
        depth_edge_strength=depth_edge_strength,
        depth_edge_falloff_pixels=depth_edge_falloff_pixels,
        depth_bow_vertical_strength=depth_bow_vertical_strength,
        depth_bow_edge_strength=depth_bow_edge_strength,
        depth_bow_local_radius=depth_bow_local_radius,
        depth_bow_edge_falloff_pixels=depth_bow_edge_falloff_pixels,
        depth_wing_lateral_strength=depth_wing_lateral_strength,
        depth_wing_lateral_upper_fraction=depth_wing_lateral_upper_fraction,
        depth_wing_lateral_body_lower_fraction=depth_wing_lateral_body_lower_fraction,
    )
    return build_front_shell_mesh(
        surfaces,
        grid_stride=grid_stride,
        include_back_cap=include_back_cap,
        bilateral_wing_mesh_split=depth_wing_lateral_strength > 0.0,
        depth_wing_lateral_upper_fraction=depth_wing_lateral_upper_fraction,
        depth_wing_lateral_body_lower_fraction=depth_wing_lateral_body_lower_fraction,
    )


def extract_depth_mesh(
    rgba: np.ndarray,
    depth01: np.ndarray,
    *,
    style: MeshStyle = "front_shell",
    depth_scale: float = 0.25,
    gap_close_radius: int = 1,
    depth_smooth_radius: int = 1,
    thickness_scale: float = 2.0,
    depth_edge_strength: float = 0.0,
    depth_edge_falloff_pixels: float = 3.0,
    depth_bow_vertical_strength: float = 0.8,
    depth_bow_edge_strength: float = 0.85,
    depth_bow_local_radius: int = 7,
    depth_bow_edge_falloff_pixels: float = 3.0,
    depth_wing_lateral_strength: float = 0.0,
    depth_wing_lateral_upper_fraction: float = 0.5,
    depth_wing_lateral_body_lower_fraction: float = 0.5,
    grid_stride: int = 1,
    include_back_cap: bool = True,
    cell_stride: int = 4,
    z_layers_max: int = 24,
) -> VolumeMesh:
    if style == "front_shell":
        return extract_front_shell_mesh(
            rgba,
            depth01,
            depth_scale=depth_scale,
            gap_close_radius=gap_close_radius,
            depth_smooth_radius=depth_smooth_radius,
            thickness_scale=thickness_scale,
            depth_edge_strength=depth_edge_strength,
            depth_edge_falloff_pixels=depth_edge_falloff_pixels,
            depth_bow_vertical_strength=depth_bow_vertical_strength,
            depth_bow_edge_strength=depth_bow_edge_strength,
            depth_bow_local_radius=depth_bow_local_radius,
            depth_bow_edge_falloff_pixels=depth_bow_edge_falloff_pixels,
            depth_wing_lateral_strength=depth_wing_lateral_strength,
            depth_wing_lateral_upper_fraction=depth_wing_lateral_upper_fraction,
            depth_wing_lateral_body_lower_fraction=depth_wing_lateral_body_lower_fraction,
            grid_stride=grid_stride,
            include_back_cap=include_back_cap,
        )
    if style == "voxel":
        return extract_volume_mesh(
            rgba,
            depth01,
            depth_scale=depth_scale,
            gap_close_radius=gap_close_radius,
            depth_smooth_radius=depth_smooth_radius,
            thickness_scale=thickness_scale,
            depth_edge_strength=depth_edge_strength,
            depth_edge_falloff_pixels=depth_edge_falloff_pixels,
            cell_stride=cell_stride,
            z_layers_max=z_layers_max,
        )
    raise ValueError(f"unsupported mesh style: {style}")


def extract_volume_mesh(
    rgba: np.ndarray,
    depth01: np.ndarray,
    *,
    depth_scale: float = 0.25,
    gap_close_radius: int = 1,
    depth_smooth_radius: int = 1,
    thickness_scale: float = 2.0,
    depth_edge_strength: float = 0.75,
    depth_edge_falloff_pixels: float = 3.0,
    cell_stride: int = 4,
    z_layers_max: int = 24,
) -> VolumeMesh:
    """Extract a lit-ready triangle mesh from one sprite + VDA depth frame."""
    from skimage.measure import marching_cubes

    surfaces = compute_anchored_z_surfaces(
        rgba,
        depth01,
        depth_scale=depth_scale,
        gap_close_radius=gap_close_radius,
        depth_smooth_radius=depth_smooth_radius,
        thickness_scale=thickness_scale,
        depth_edge_strength=depth_edge_strength,
        depth_edge_falloff_pixels=depth_edge_falloff_pixels,
    )
    occupancy, meta = build_coarse_occupancy(
        surfaces,
        cell_stride=cell_stride,
        z_layers_max=z_layers_max,
    )
    if occupancy.sum() <= 0.0:
        raise ValueError("coarse occupancy is empty; check sprite alpha / depth")

    verts, faces, normals, _ = marching_cubes(
        occupancy,
        level=0.5,
        spacing=(1.0, 1.0, 1.0),
        allow_degenerate=False,
    )
    vertices = _voxel_vertices_to_world(verts, meta)
    face_array = faces.astype(np.int32, copy=False)
    vertex_normals = _compute_vertex_normals(vertices, face_array)
    uvs = _sprite_uv_from_world(vertices, surfaces.width, surfaces.height)
    vertex_rgba = _vertex_rgba_from_sprite(
        vertices, surfaces.rgba, surfaces.width, surfaces.height
    )
    return VolumeMesh(
        vertices=vertices,
        faces=face_array,
        normals=vertex_normals,
        uvs=uvs,
        vertex_rgba=vertex_rgba,
        width=surfaces.width,
        height=surfaces.height,
    )


def write_obj_mesh(
    path: Path,
    mesh: VolumeMesh,
    *,
    texture_name: str = "sprite.png",
) -> None:
    """Write OBJ with UVs + normals for Unity import."""
    path.parent.mkdir(parents=True, exist_ok=True)
    mtl_path = path.with_suffix(".mtl")
    mtl_name = mtl_path.name
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(f"mtllib {mtl_name}\n")
        handle.write("o depth_volume_mesh\n")
        for x, y, z in mesh.vertices:
            handle.write(f"v {x:.6f} {y:.6f} {z:.6f}\n")
        for u, v in mesh.uvs:
            handle.write(f"vt {u:.6f} {v:.6f}\n")
        for nx, ny, nz in mesh.normals:
            handle.write(f"vn {nx:.6f} {ny:.6f} {nz:.6f}\n")
        handle.write("usemtl SpritePaint\n")
        handle.write("s off\n")
        for a, b, c in mesh.faces:
            # OBJ indices are 1-based; v/vt/vn share index order.
            handle.write(
                f"f {a + 1}/{a + 1}/{a + 1} "
                f"{b + 1}/{b + 1}/{b + 1} "
                f"{c + 1}/{c + 1}/{c + 1}\n"
            )

    mtl_path = path.with_suffix(".mtl")
    mtl_path.write_text(
        "\n".join(
            [
                "newmtl SpritePaint",
                f"map_Kd {texture_name}",
                "",
            ]
        ),
        encoding="utf-8",
    )


def mesh_summary(mesh: VolumeMesh) -> dict[str, Any]:
    return {
        "vertexCount": int(mesh.vertices.shape[0]),
        "triangleCount": int(mesh.faces.shape[0]),
        "width": int(mesh.width),
        "height": int(mesh.height),
    }
