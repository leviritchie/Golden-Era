"""Software rasterizer for coarse volume meshes (lit texture + orbit frames)."""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np
from PIL import Image

from volume_mesh import VolumeMesh


def _look_rotation(yaw_deg: float, pitch_deg: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    yaw = math.radians(yaw_deg)
    pitch = math.radians(pitch_deg)
    cy, sy = math.cos(yaw), math.sin(yaw)
    cp, sp = math.cos(pitch), math.sin(pitch)
    forward = np.array((-sy * cp, sp, -cy * cp), dtype=np.float32)
    right = np.array((cy, 0.0, -sy), dtype=np.float32)
    up = np.cross(right, forward)
    up_norm = float(np.linalg.norm(up))
    if up_norm < 1e-6:
        raise ValueError("camera up is degenerate")
    up = (up / up_norm).astype(np.float32)
    return forward, right, up.astype(np.float32)


def _load_texture_rgba(path: Path) -> np.ndarray:
    return np.asarray(Image.open(path).convert("RGBA"), dtype=np.uint8)


def _sample_texture_bilinear(texture: np.ndarray, u: float, v: float) -> np.ndarray:
    h, w = texture.shape[:2]
    u = float(np.clip(u, 0.0, 1.0))
    v = float(np.clip(v, 0.0, 1.0))
    x = u * (w - 1)
    y = (1.0 - v) * (h - 1)
    x0 = int(np.floor(x))
    y0 = int(np.floor(y))
    x1 = min(x0 + 1, w - 1)
    y1 = min(y0 + 1, h - 1)
    tx = x - x0
    ty = y - y0
    c00 = texture[y0, x0].astype(np.float32)
    c10 = texture[y0, x1].astype(np.float32)
    c01 = texture[y1, x0].astype(np.float32)
    c11 = texture[y1, x1].astype(np.float32)
    top = c00 * (1 - tx) + c10 * tx
    bot = c01 * (1 - tx) + c11 * tx
    return top * (1 - ty) + bot * ty


def _rasterize_triangle(
    canvas: np.ndarray,
    depth_buf: np.ndarray,
    x0: float,
    y0: float,
    z0: float,
    x1: float,
    y1: float,
    z1: float,
    x2: float,
    y2: float,
    z2: float,
    *,
    rgba0: np.ndarray | None = None,
    rgba1: np.ndarray | None = None,
    rgba2: np.ndarray | None = None,
    uv0: np.ndarray | None = None,
    uv1: np.ndarray | None = None,
    uv2: np.ndarray | None = None,
    texture: np.ndarray | None = None,
    shade0: float = 1.0,
    shade1: float = 1.0,
    shade2: float = 1.0,
) -> None:
    minx = max(0, int(np.floor(min(x0, x1, x2))))
    maxx = min(canvas.shape[1] - 1, int(np.ceil(max(x0, x1, x2))))
    miny = max(0, int(np.floor(min(y0, y1, y2))))
    maxy = min(canvas.shape[0] - 1, int(np.ceil(max(y0, y1, y2))))
    if minx > maxx or miny > maxy:
        return

    denom = (y1 - y2) * (x0 - x2) + (x2 - x1) * (y0 - y2)
    if abs(denom) < 1e-12:
        return

    for py in range(miny, maxy + 1):
        for px in range(minx, maxx + 1):
            w0 = ((y1 - y2) * (px - x2) + (x2 - x1) * (py - y2)) / denom
            w1 = ((y2 - y0) * (px - x2) + (x0 - x2) * (py - y2)) / denom
            w2 = 1.0 - w0 - w1
            if w0 < 0.0 or w1 < 0.0 or w2 < 0.0:
                continue
            z = w0 * z0 + w1 * z1 + w2 * z2
            if z >= depth_buf[py, px]:
                continue
            depth_buf[py, px] = z
            shade = shade0 * w0 + shade1 * w1 + shade2 * w2
            if texture is not None and uv0 is not None and uv1 is not None and uv2 is not None:
                u = uv0[0] * w0 + uv1[0] * w1 + uv2[0] * w2
                v = uv0[1] * w0 + uv1[1] * w1 + uv2[1] * w2
                rgba = _sample_texture_bilinear(texture, u, v)
            else:
                rgba = (
                    rgba0.astype(np.float32) * w0
                    + rgba1.astype(np.float32) * w1
                    + rgba2.astype(np.float32) * w2
                )
            alpha = rgba[3] / 255.0
            if alpha < 0.04:
                continue
            rgb = np.clip(rgba[:3] * shade, 0.0, 255.0)
            canvas[py, px, :3] = rgb.astype(np.uint8)
            canvas[py, px, 3] = min(255, int(alpha * 255.0))


def render_mesh_frame(
    mesh: VolumeMesh,
    texture: np.ndarray | None = None,
    *,
    yaw_deg: float = 0.0,
    pitch_deg: float = 12.0,
    out_width: int = 768,
    out_height: int = 576,
    background: tuple[int, int, int, int] = (18, 22, 28, 255),
    camera_distance: float = 2.4,
    light_dir: tuple[float, float, float] = (0.45, 0.75, 0.65),
    flat_shading: bool = False,
    texture_sampling: bool = True,
) -> np.ndarray:
    """Rasterize one perspective view of a volume mesh with simple diffuse light."""
    use_texture = texture_sampling and texture is not None and texture.ndim == 3
    forward, right, up = _look_rotation(yaw_deg, pitch_deg)
    xyz = mesh.vertices.astype(np.float32, copy=False)
    cam_x = xyz @ right
    cam_y = xyz @ up
    cam_z = xyz @ forward

    view_depth = camera_distance + cam_z
    visible = view_depth > 1e-3
    scale = camera_distance / np.clip(view_depth, 0.35, None)
    scale = np.minimum(scale, 2.5)
    proj_x = cam_x * scale
    proj_y = cam_y * scale

    aspect = float(mesh.width) / float(mesh.height)
    cols = (proj_x / aspect + 0.5) * float(out_width)
    rows = (0.5 - proj_y) * float(out_height)

    light = np.array(light_dir, dtype=np.float32)
    light /= max(float(np.linalg.norm(light)), 1e-6)
    if flat_shading:
        shade = np.ones(mesh.vertices.shape[0], dtype=np.float32)
    else:
        shade = np.clip(0.55 + 0.45 * np.maximum(0.0, mesh.normals @ light), 0.55, 1.0)

    canvas = np.zeros((out_height, out_width, 4), dtype=np.uint8)
    canvas[:] = np.array(background, dtype=np.uint8)
    depth_buf = np.full((out_height, out_width), np.inf, dtype=np.float32)

    face_depth = view_depth[mesh.faces].mean(axis=1)
    order = np.argsort(face_depth, kind="stable")

    for face_idx in order:
        tri = mesh.faces[face_idx]
        if not visible[tri].any():
            continue
        xs = cols[tri]
        ys = rows[tri]
        zs = view_depth[tri]
        shades = shade[tri]
        rgba_corners = mesh.vertex_rgba[tri]
        uvs = mesh.uvs[tri]
        _rasterize_triangle(
            canvas,
            depth_buf,
            xs[0],
            ys[0],
            zs[0],
            xs[1],
            ys[1],
            zs[1],
            xs[2],
            ys[2],
            zs[2],
            rgba0=None if use_texture else rgba_corners[0],
            rgba1=None if use_texture else rgba_corners[1],
            rgba2=None if use_texture else rgba_corners[2],
            uv0=uvs[0] if use_texture else None,
            uv1=uvs[1] if use_texture else None,
            uv2=uvs[2] if use_texture else None,
            texture=texture if use_texture else None,
            shade0=shades[0],
            shade1=shades[1],
            shade2=shades[2],
        )
    return canvas


def load_mesh_from_obj(mesh_path: Path) -> VolumeMesh:
    import trimesh

    loaded = trimesh.load(mesh_path, process=False)
    if not isinstance(loaded, trimesh.Trimesh):
        raise ValueError(f"expected Trimesh at {mesh_path}")
    uvs = np.asarray(loaded.visual.uv, dtype=np.float32)
    if uvs.shape[0] != loaded.vertices.shape[0]:
        raise ValueError("OBJ UV count does not match vertex count")
    normals = np.asarray(loaded.vertex_normals, dtype=np.float32)
    texture = None
    sprite_path = mesh_path.parent / "sprite.png"
    if sprite_path.is_file():
        texture = np.asarray(Image.open(sprite_path).convert("RGBA"), dtype=np.uint8)
    elif loaded.visual.material is not None and loaded.visual.material.image is not None:
        texture = np.asarray(loaded.visual.material.image.convert("RGBA"), dtype=np.uint8)
    vertex_rgba = np.zeros((loaded.vertices.shape[0], 4), dtype=np.uint8)
    if texture is not None:
        from volume_mesh import _vertex_rgba_from_sprite

        vertex_rgba = _vertex_rgba_from_sprite(
            np.asarray(loaded.vertices, dtype=np.float32),
            texture,
            int(texture.shape[1]),
            int(texture.shape[0]),
        )
    return VolumeMesh(
        vertices=np.asarray(loaded.vertices, dtype=np.float32),
        faces=np.asarray(loaded.faces, dtype=np.int32),
        normals=normals,
        uvs=uvs,
        vertex_rgba=vertex_rgba,
        width=int(texture.shape[1]) if texture is not None else 1,
        height=int(texture.shape[0]) if texture is not None else 1,
    )


def _sample_texture_nearest(texture: np.ndarray, u: float, v: float) -> np.ndarray:
    h, w = texture.shape[:2]
    x = int(np.clip(round(u * (w - 1)), 0, w - 1))
    y = int(np.clip(round((1.0 - v) * (h - 1)), 0, h - 1))
    return texture[y, x].astype(np.uint8, copy=False)


def render_orbit_frames(
    mesh: VolumeMesh,
    texture_path: Path,
    *,
    yaw_steps: int = 48,
    yaw_max_deg: float = 360.0,
    **render_kwargs,
) -> list[tuple[float, np.ndarray]]:
    texture = _load_texture_rgba(texture_path)
    if mesh.width <= 1 and mesh.height <= 1:
        mesh = VolumeMesh(
            vertices=mesh.vertices,
            faces=mesh.faces,
            normals=mesh.normals,
            uvs=mesh.uvs,
            vertex_rgba=mesh.vertex_rgba,
            width=int(texture.shape[1]),
            height=int(texture.shape[0]),
        )
    frames: list[tuple[float, np.ndarray]] = []
    steps = max(2, int(yaw_steps))
    for index in range(steps):
        yaw = float(yaw_max_deg) * (index / steps)
        image = render_mesh_frame(mesh, texture, yaw_deg=yaw, **render_kwargs)
        frames.append((yaw, image))
    return frames
