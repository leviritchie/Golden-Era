"""Shared-camera previews for the Eagle-skinned Roc copy. No per-panel auto-fit."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw

from mesh_preview import raster_mesh
from paths import SOURCE_FRAME_MS
from shared_camera import project_view

PANEL = 200


def _label(image: Image.Image, text: str) -> Image.Image:
    labeled = image.convert("RGB")
    draw = ImageDraw.Draw(labeled)
    draw.rectangle((0, 0, labeled.width, 16), fill=(12, 12, 16))
    draw.text((4, 2), text, fill=(230, 230, 235))
    return labeled


def _stick(
    cameras: dict[str, Any],
    view: str,
    joints: np.ndarray,
    parents: np.ndarray,
    color: tuple[int, int, int],
    *,
    background: Image.Image | None = None,
) -> Image.Image:
    if background is None:
        image = Image.new("RGB", (int(cameras["width"]), int(cameras["height"])), (245, 245, 247))
    else:
        image = background.convert("RGB")
    draw = ImageDraw.Draw(image)
    xy = project_view(joints, cameras, view)
    for index, parent in enumerate(parents):
        if int(parent) < 0:
            continue
        x0, y0 = xy[int(parent)]
        x1, y1 = xy[index]
        draw.line((x0, y0, x1, y1), fill=color, width=2)
    for x, y in xy:
        draw.ellipse((x - 2, y - 2, x + 2, y + 2), fill=color)
    return image


def _mesh(
    cameras: dict[str, Any],
    view: str,
    vertices: np.ndarray,
    triangles: np.ndarray,
    uvs: np.ndarray | None,
    albedo: np.ndarray | None,
    wire: bool = False,
) -> Image.Image:
    camera = cameras[view]
    if wire:
        image = Image.new("RGB", (int(cameras["width"]), int(cameras["height"])), (20, 20, 24))
        draw = ImageDraw.Draw(image)
        xy = project_view(vertices, cameras, view)
        for a, b, c in triangles:
            pts = [tuple(xy[int(a)]), tuple(xy[int(b)]), tuple(xy[int(c)])]
            draw.line(pts + pts[:1], fill=(180, 180, 190), width=1)
        return image
    return raster_mesh(
        vertices=vertices,
        triangles=triangles,
        camera=camera,
        width=int(cameras["width"]),
        height=int(cameras["height"]),
        uvs=uvs,
        albedo=albedo,
    ).convert("RGB")


def load_gif_frames(path: Path) -> list[Image.Image]:
    image = Image.open(path)
    frames: list[Image.Image] = []
    index = 0
    while True:
        image.seek(index)
        frames.append(image.convert("RGB").copy())
        index += 1
        try:
            image.seek(index)
        except EOFError:
            break
    if not frames:
        raise ValueError(f"GIF has no frames: {path}")
    return frames


def write_bind_sheet(
    dest: Path,
    *,
    cameras: dict[str, Any],
    vertices: np.ndarray,
    triangles: np.ndarray,
    uvs: np.ndarray,
    albedo: np.ndarray,
    joints: np.ndarray,
    parents: np.ndarray,
    title: str,
) -> Path:
    views = ("front", "side", "top", "underside")
    row_mesh = Image.new("RGB", (PANEL * 5, PANEL + 16), (16, 16, 20))
    row_stick = Image.new("RGB", (PANEL * 5, PANEL + 16), (16, 16, 20))
    for index, view in enumerate(views):
        mesh = _label(_mesh(cameras, view, vertices, triangles, uvs, albedo).resize((PANEL, PANEL)), f"{view}")
        wire = _label(
            _mesh(cameras, view, vertices, triangles, uvs, albedo, wire=True).resize((PANEL, PANEL)),
            f"{view} wire",
        )
        stick = _label(_stick(cameras, view, joints, parents, (40, 90, 200)).resize((PANEL, PANEL)), f"{view} joints")
        if index == 0:
            row_mesh.paste(wire, (PANEL * 4, 16))
        row_mesh.paste(mesh, (PANEL * index, 16))
        row_stick.paste(stick, (PANEL * index, 16))
    canvas = Image.new("RGB", (row_mesh.width, row_mesh.height + row_stick.height + 18), (12, 12, 16))
    ImageDraw.Draw(canvas).text((4, 2), title, fill=(230, 230, 235))
    canvas.paste(row_mesh, (0, 18))
    canvas.paste(row_stick, (0, 18 + row_mesh.height))
    dest.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(dest)
    return dest


def write_stage_sheet(
    dest: Path,
    *,
    cameras: dict[str, Any],
    stages: list[tuple[str, np.ndarray]],
    triangles: np.ndarray,
    uvs: np.ndarray,
    albedo: np.ndarray,
    joints: np.ndarray,
    parents: np.ndarray,
    title: str,
) -> Path:
    views = ("front", "side")
    row_h = PANEL + 16
    canvas = Image.new("RGB", (PANEL * (len(views) + 1), row_h * len(stages) + 18), (12, 12, 16))
    ImageDraw.Draw(canvas).text((4, 2), title, fill=(230, 230, 235))
    for row, (label, vertices) in enumerate(stages):
        y = 18 + row * row_h
        for col, view in enumerate(views):
            mesh = _label(_mesh(cameras, view, vertices, triangles, uvs, albedo).resize((PANEL, PANEL)), f"{label} {view}")
            canvas.paste(mesh, (PANEL * col, y))
        stick = _label(_stick(cameras, "front", joints, parents, (40, 90, 200)).resize((PANEL, PANEL)), f"{label} joints")
        canvas.paste(stick, (PANEL * len(views), y))
    dest.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(dest)
    return dest


def write_overlay_gif(
    dest: Path,
    *,
    cameras: dict[str, Any],
    sprites: list[Image.Image] | None,
    previous_retarget: list[Image.Image] | None,
    capture: np.ndarray,
    joints_a: np.ndarray,
    joints_b: np.ndarray,
    parents: np.ndarray,
    mesh_a: list[np.ndarray],
    mesh_b: list[np.ndarray],
    triangles: np.ndarray,
    uvs: np.ndarray,
    albedo: np.ndarray,
    title: str,
) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    columns = 5
    if sprites is not None:
        columns += 1
    if previous_retarget is not None:
        columns += 1
    frames = []
    for index in range(len(capture)):
        row = Image.new("RGB", (PANEL * columns, PANEL + 16), (16, 16, 20))
        x = 0
        if sprites is not None:
            sprite = sprites[index].convert("RGB").resize((PANEL, PANEL))
            row.paste(_label(sprite, "source sprite (not this camera)"), (x, 16))
            x += PANEL
        if previous_retarget is not None:
            prev = previous_retarget[min(index, len(previous_retarget) - 1)].convert("RGB").resize((PANEL, PANEL))
            row.paste(_label(prev, "previous SmartRig retarget (own camera)"), (x, 16))
            x += PANEL
        overlay = _stick(cameras, "front", capture[index], parents, (40, 180, 90))
        overlay = _stick(cameras, "front", joints_a[index], parents, (40, 90, 200), background=overlay)
        overlay = _stick(cameras, "front", joints_b[index], parents, (200, 120, 40), background=overlay)
        a_m = _mesh(cameras, "front", mesh_a[index], triangles, uvs, albedo)
        b_m = _mesh(cameras, "front", mesh_b[index], triangles, uvs, albedo)
        a_s = _mesh(cameras, "side", mesh_a[index], triangles, uvs, albedo)
        b_s = _mesh(cameras, "side", mesh_b[index], triangles, uvs, albedo)
        for image, label in (
            (overlay.resize((PANEL, PANEL)), "green=capture A=blue B=orange"),
            (a_m.resize((PANEL, PANEL)), "A mesh front"),
            (b_m.resize((PANEL, PANEL)), "B mesh front"),
            (a_s.resize((PANEL, PANEL)), "A mesh side"),
            (b_s.resize((PANEL, PANEL)), "B mesh side"),
        ):
            row.paste(_label(image, label), (x, 16))
            x += PANEL
        ImageDraw.Draw(row).text((4, 2), f"{title} f{index:02d}", fill=(230, 230, 235))
        frames.append(row)
    frames[0].save(
        dest,
        save_all=True,
        append_images=frames[1:],
        duration=max(1, int(round(SOURCE_FRAME_MS))),
        loop=0,
    )
    return dest


def write_actuation_gif(
    dest: Path,
    *,
    cameras: dict[str, Any],
    rest_vertices: np.ndarray,
    posed_sets: dict[str, np.ndarray],
    triangles: np.ndarray,
    uvs: np.ndarray,
    albedo: np.ndarray,
) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    names = list(posed_sets)
    frames = []
    for step in range(8):
        amount = 0.5 - 0.5 * np.cos(2.0 * np.pi * step / 8.0)
        row = Image.new("RGB", (PANEL * len(names), PANEL + 16), (16, 16, 20))
        for index, name in enumerate(names):
            posed = rest_vertices * (1.0 - amount) + posed_sets[name] * amount
            mesh = _mesh(cameras, "front", posed, triangles, uvs, albedo).resize((PANEL, PANEL))
            row.paste(_label(mesh, name), (PANEL * index, 16))
        frames.append(row)
    frames[0].save(dest, save_all=True, append_images=frames[1:], duration=80, loop=0)
    return dest


def write_mesh_gif(
    dest: Path,
    *,
    cameras: dict[str, Any],
    meshes: list[np.ndarray],
    triangles: np.ndarray,
    uvs: np.ndarray | None,
    albedo: np.ndarray | None,
    title: str,
    view: str = "front",
) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    frames = []
    for index, vertices in enumerate(meshes):
        image = _label(_mesh(cameras, view, vertices, triangles, uvs, albedo).resize((PANEL, PANEL)), f"{title} f{index:02d}")
        frames.append(image)
    frames[0].save(
        dest,
        save_all=True,
        append_images=frames[1:],
        duration=max(1, int(round(SOURCE_FRAME_MS))),
        loop=0,
    )
    return dest


def write_shape_compare_gif(
    dest: Path,
    *,
    cameras: dict[str, Any],
    sprites: list[Image.Image] | None,
    previous_retarget: list[Image.Image] | None,
    v2_frames: list[Image.Image] | None,
    capture: np.ndarray,
    joints: np.ndarray,
    parents: np.ndarray,
    meshes: list[np.ndarray],
    triangles: np.ndarray,
    uvs: np.ndarray,
    albedo: np.ndarray,
    title: str,
) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    columns = 4
    if sprites is not None:
        columns += 1
    if previous_retarget is not None:
        columns += 1
    if v2_frames is not None:
        columns += 1
    frames = []
    for index in range(len(meshes)):
        row = Image.new("RGB", (PANEL * columns, PANEL + 16), (16, 16, 20))
        x = 0
        if sprites is not None:
            sprite = sprites[min(index, len(sprites) - 1)].convert("RGB").resize((PANEL, PANEL))
            row.paste(_label(sprite, "source sprite (not this camera)"), (x, 16))
            x += PANEL
        if previous_retarget is not None:
            prev = previous_retarget[min(index, len(previous_retarget) - 1)].convert("RGB").resize((PANEL, PANEL))
            row.paste(_label(prev, "original SmartRig retarget (own camera)"), (x, 16))
            x += PANEL
        if v2_frames is not None:
            v2 = v2_frames[min(index, len(v2_frames) - 1)].convert("RGB").resize((PANEL, PANEL))
            row.paste(_label(v2, "v2 conformed copy (own camera, historical)"), (x, 16))
            x += PANEL
        overlay = _stick(cameras, "front", capture[index], parents, (40, 180, 90))
        overlay = _stick(cameras, "front", joints[index], parents, (40, 90, 200), background=overlay)
        front = _mesh(cameras, "front", meshes[index], triangles, uvs, albedo)
        side = _mesh(cameras, "side", meshes[index], triangles, uvs, albedo)
        for image, label in (
            (overlay.resize((PANEL, PANEL)), "green=mapped capture blue=adapted"),
            (front.resize((PANEL, PANEL)), "shape-preserved front"),
            (side.resize((PANEL, PANEL)), "shape-preserved side"),
            (
                _stick(cameras, "side", joints[index], parents, (40, 90, 200)).resize((PANEL, PANEL)),
                "adapted joints side",
            ),
        ):
            row.paste(_label(image, label), (x, 16))
            x += PANEL
        ImageDraw.Draw(row).text((4, 2), f"{title} f{index:02d}", fill=(230, 230, 235))
        frames.append(row)
    frames[0].save(
        dest,
        save_all=True,
        append_images=frames[1:],
        duration=max(1, int(round(SOURCE_FRAME_MS))),
        loop=0,
    )
    return dest
