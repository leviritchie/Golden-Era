"""Sprite | predicted sticks | bind sticks GIF. Source timing, no silhouette keep."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

EXPERIMENT = Path(__file__).resolve().parent
if str(EXPERIMENT) not in sys.path:
    sys.path.insert(0, str(EXPERIMENT))

from paths import SOURCE_FRAME_MS, VENDOR


def _vendor_on_path() -> None:
    vendor = str(VENDOR)
    if vendor not in sys.path:
        sys.path.insert(0, vendor)


def fk_world_positions(
    *,
    local_matrices: np.ndarray,
    rest_local_translation: np.ndarray,
    parents: np.ndarray,
    root_world: np.ndarray,
) -> np.ndarray:
    joint_count = local_matrices.shape[0]
    world_rot = np.zeros((joint_count, 3, 3), dtype=np.float64)
    world_pos = np.zeros((joint_count, 3), dtype=np.float64)
    for index in range(joint_count):
        parent = int(parents[index])
        local_rot = np.asarray(local_matrices[index], dtype=np.float64)
        local_off = np.asarray(rest_local_translation[index], dtype=np.float64)
        if parent < 0:
            world_rot[index] = local_rot
            world_pos[index] = np.asarray(root_world, dtype=np.float64)
        else:
            world_rot[index] = world_rot[parent] @ local_rot
            world_pos[index] = world_pos[parent] + world_rot[parent] @ local_off
    return world_pos


def proposal_fk_world(
    *,
    pred_rot6d: np.ndarray,
    offsets: np.ndarray,
    parents: np.ndarray,
    global_scale: float,
    rest_root: np.ndarray,
) -> np.ndarray:
    """Vendor BVH FK: identity rest + parent-relative offsets, then unnormalize."""
    _vendor_on_path()
    import torch
    from utils.rotation import rot6d_to_fk_positions

    rot6d = np.ascontiguousarray(pred_rot6d, dtype=np.float32)
    offset = np.ascontiguousarray(offsets, dtype=np.float32)
    parent = np.ascontiguousarray(parents, dtype=np.int64)
    if rot6d.ndim != 3 or rot6d.shape[-1] != 6:
        raise ValueError(f"pred_rot6d must be [T,J,6], got {rot6d.shape}")
    if offset.shape != (rot6d.shape[1], 3):
        raise ValueError(f"offset {offset.shape} does not match joints {rot6d.shape[1]}")
    if parent.shape != (rot6d.shape[1],):
        raise ValueError(f"parents {parent.shape} do not match joints {rot6d.shape[1]}")
    fk = rot6d_to_fk_positions(
        torch.from_numpy(rot6d[None]).contiguous(),
        torch.from_numpy(offset[None]).contiguous(),
        torch.from_numpy(parent[None]).contiguous(),
        torch.tensor([float(global_scale)], dtype=torch.float32),
    )
    root_centered = fk.squeeze(0).detach().cpu().numpy().astype(np.float64)
    return root_centered * float(global_scale) + np.asarray(rest_root, dtype=np.float64).reshape(1, 1, 3)


def idle_alpha_bbox(idle_png: Path) -> tuple[float, float, float, float]:
    image = Image.open(idle_png).convert("RGBA")
    alpha = np.asarray(image)[..., 3]
    ys, xs = np.where(alpha >= 8)
    if xs.size == 0:
        raise ValueError(f"{idle_png} has no opaque pixels")
    return float(xs.min()), float(ys.min()), float(xs.max()), float(ys.max())


def _project_xy(points: np.ndarray, basis: np.ndarray) -> np.ndarray:
    return (np.asarray(basis, dtype=np.float64) @ np.asarray(points, dtype=np.float64).T).T


def register_idle_camera(
    *,
    rest_world: np.ndarray,
    idle_png: Path,
    source_camera: dict | None,
) -> dict:
    """One-time rest-to-idle registration. Not a pose keep score."""
    x0, y0, x1, y1 = idle_alpha_bbox(idle_png)
    sprite_w = max(1.0, x1 - x0)
    sprite_h = max(1.0, y1 - y0)
    sprite_cx = 0.5 * (x0 + x1)
    sprite_cy = 0.5 * (y0 + y1)
    candidates: list[tuple[str, np.ndarray]] = [
        ("y_up_orthographic", np.asarray([[1.0, 0.0, 0.0], [0.0, -1.0, 0.0]], dtype=np.float64)),
        ("y_up_flipped", np.asarray([[-1.0, 0.0, 0.0], [0.0, -1.0, 0.0]], dtype=np.float64)),
        ("z_up_orthographic", np.asarray([[1.0, 0.0, 0.0], [0.0, 0.0, -1.0]], dtype=np.float64)),
        ("z_up_flipped", np.asarray([[-1.0, 0.0, 0.0], [0.0, 0.0, -1.0]], dtype=np.float64)),
    ]
    if source_camera is not None and "basisScreenRows" in source_camera:
        candidates.append(
            (
                "source_basis_rescaled",
                np.asarray(source_camera["basisScreenRows"], dtype=np.float64),
            )
        )
    best = None
    for name, basis in candidates:
        xy = _project_xy(rest_world, basis)
        width = float(xy[:, 0].max() - xy[:, 0].min())
        height = float(xy[:, 1].max() - xy[:, 1].min())
        size = max(width, height)
        if size <= 1e-8:
            continue
        scale = max(sprite_w, sprite_h) / size
        center = xy.mean(axis=0)
        offset = np.asarray((sprite_cx, sprite_cy), dtype=np.float64) - scale * center
        projected = xy * scale + offset
        px = np.clip(np.round(projected[:, 0]).astype(int), 0, int(x1) + 8)
        py = np.clip(np.round(projected[:, 1]).astype(int), 0, int(y1) + 8)
        inside = int(((px >= x0) & (px <= x1) & (py >= y0) & (py <= y1)).sum())
        record = (inside, name, basis, float(scale), offset)
        if best is None or inside > best[0]:
            best = record
    if best is None:
        raise ValueError("idle camera registration failed")
    _inside, name, basis, scale, offset = best
    return {
        "cameraPolicy": "idle_aabb_register",
        "basisName": name,
        "basisScreenRows": basis.tolist(),
        "pxPerWorld": scale,
        "screenOffsetPx": offset.tolist(),
        "sourceFrame": 0,
        "jointsInsideIdleBBox": int(_inside),
        "jointCount": int(len(rest_world)),
    }


def project_points(points: np.ndarray, camera: dict) -> np.ndarray:
    basis = np.asarray(camera["basisScreenRows"], dtype=np.float64)
    if basis.shape != (2, 3):
        raise ValueError(f"basisScreenRows must be 2x3, got {basis.shape}")
    scale = float(camera["pxPerWorld"])
    if scale <= 0:
        raise ValueError(f"pxPerWorld must be positive: {scale}")
    offset = np.asarray(camera["screenOffsetPx"], dtype=np.float64).reshape(2)
    xy = (basis @ np.asarray(points, dtype=np.float64).T).T * scale + offset
    return xy


def draw_sticks(
    sprite: Image.Image,
    *,
    xy: np.ndarray,
    parents: np.ndarray,
    label: str,
    color: tuple[int, int, int],
) -> Image.Image:
    canvas = sprite.convert("RGBA").copy()
    draw = ImageDraw.Draw(canvas)
    for index, parent in enumerate(parents):
        if int(parent) < 0:
            continue
        x0, y0 = xy[int(parent)]
        x1, y1 = xy[index]
        draw.line([(x0, y0), (x1, y1)], fill=color + (255,), width=2)
    for x, y in xy:
        draw.ellipse((x - 2, y - 2, x + 2, y + 2), fill=color + (255,))
    draw.rectangle((0, 0, canvas.width, 16), fill=(12, 12, 16, 220))
    draw.text((4, 2), label, fill=(230, 230, 235, 255))
    return canvas.convert("RGB")


def compose_gif(
    *,
    sprite_dir: Path,
    overlay_pred: list[Image.Image],
    overlay_bind: list[Image.Image],
    dest: Path,
    frame_indices: list[int],
    frame_ms: int = SOURCE_FRAME_MS,
    panel_titles: tuple[str, str, str] = ("sprite", "V2 proposal", "bind"),
    sprites: list[Image.Image] | None = None,
) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    panels: list[Image.Image] = []
    header = 22
    if sprites is not None and len(sprites) != len(overlay_pred):
        raise ValueError("provided sprites must match overlay frame count")
    if len(overlay_pred) != len(overlay_bind):
        raise ValueError("overlay panel counts must match")
    if sprites is None and len(frame_indices) != len(overlay_pred):
        raise ValueError("frame_indices must match overlay frame count")
    for position, frame_index in enumerate(frame_indices if sprites is None else range(len(overlay_pred))):
        if sprites is None:
            sprite_path = sprite_dir / f"{int(frame_index):02d}.png"
            if not sprite_path.is_file():
                sprite_path = sprite_dir / f"{int(frame_index)}.png"
            sprite = Image.open(sprite_path).convert("RGB")
        else:
            sprite = sprites[position].convert("RGB")
        pred = overlay_pred[position]
        bind = overlay_bind[position]
        canvas = Image.new("RGB", (sprite.width * 3, sprite.height + header), (12, 12, 16))
        draw = ImageDraw.Draw(canvas)
        draw.text((6, 4), panel_titles[0], fill=(230, 230, 235))
        draw.text((sprite.width + 6, 4), panel_titles[1], fill=(230, 230, 235))
        draw.text((sprite.width * 2 + 6, 4), panel_titles[2], fill=(230, 230, 235))
        canvas.paste(sprite, (0, header))
        canvas.paste(pred, (sprite.width, header))
        canvas.paste(bind, (sprite.width * 2, header))
        panels.append(canvas)
    if not panels:
        raise RuntimeError("no GIF panels")
    dest_path = Path(dest)
    panels[0].save(
        dest_path,
        save_all=True,
        append_images=panels[1:],
        duration=[
            10 * (round((i + 1) * frame_ms / 10) - round(i * frame_ms / 10))
            for i in range(len(panels))
        ],
        loop=0,
        optimize=False,
    )
    return dest_path


def compose_panel_gif(
    *,
    panels: list[list[Image.Image]],
    titles: tuple[str, ...],
    dest: Path,
    frame_ms: float = SOURCE_FRAME_MS,
) -> Path:
    if not panels:
        raise RuntimeError("no GIF panels")
    width_count = len(titles)
    if width_count < 1:
        raise ValueError("compose_panel_gif requires titles")
    header = 22
    frames: list[Image.Image] = []
    for row in panels:
        if len(row) != width_count:
            raise ValueError(f"panel row has {len(row)} images, expected {width_count}")
        cell_w = row[0].width
        cell_h = row[0].height
        if any(image.size != (cell_w, cell_h) for image in row):
            raise ValueError("GIF panels in a row must share one size")
        canvas = Image.new("RGB", (cell_w * width_count, cell_h + header), (12, 12, 16))
        draw = ImageDraw.Draw(canvas)
        for column, (title, image) in enumerate(zip(titles, row)):
            draw.text((cell_w * column + 6, 4), title, fill=(230, 230, 235))
            canvas.paste(image.convert("RGB"), (cell_w * column, header))
        frames.append(canvas)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest_path = Path(dest)
    frames[0].save(
        dest_path,
        save_all=True,
        append_images=frames[1:],
        duration=[
            10 * (round((i + 1) * frame_ms / 10) - round(i * frame_ms / 10))
            for i in range(len(frames))
        ],
        loop=0,
        optimize=False,
    )
    return dest_path


def write_proposal_gif(
    *,
    sprite_dir: Path,
    proposal_npz: Path,
    rig_json: Path,
    dest: Path,
) -> Path:
    payload = np.load(proposal_npz)
    rig = json.loads(rig_json.read_text(encoding="utf-8"))
    camera = rig.get("camera")
    if not camera:
        raise ValueError("rig.json has no camera; cannot project sticks")
    parents = np.asarray(rig["parents"], dtype=np.int64)
    reference = np.load(rig_json.with_name("reference.npz"))
    rest_world = np.asarray(reference["rest_world"], dtype=np.float64)
    joint_count = int(reference["J_valid"][0])
    parents = parents[:joint_count]
    offsets = np.asarray(reference["offset"][:joint_count], dtype=np.float32)
    scale = float(reference["global_scale"][0])
    frame_indices = [int(value) for value in payload["frame_indices"]]
    source_to_model = np.asarray(reference.get("source_to_model", np.eye(3)))
    pred_world = (payload["pred_position"][:, :joint_count].astype(np.float64) * scale) @ source_to_model + rest_world[0]
    fk_world = proposal_fk_world(
        pred_rot6d=payload["pred_rot6d"][:, :joint_count],
        offsets=offsets,
        parents=parents,
        global_scale=scale,
        rest_root=np.zeros(3),
    )
    fk_world = fk_world @ source_to_model + rest_world[0]
    bind_xy = project_points(rest_world, camera)
    pred_overlays: list[Image.Image] = []
    bind_overlays: list[Image.Image] = []
    pos_travel = float((pred_world.max(0) - pred_world.min(0)).max(axis=1).mean())
    fk_travel = float((fk_world.max(0) - fk_world.min(0)).max(axis=1).mean())
    for position, frame_index in enumerate(frame_indices):
        sprite_path = sprite_dir / f"{int(frame_index):02d}.png"
        if not sprite_path.is_file():
            sprite_path = sprite_dir / f"{int(frame_index)}.png"
        sprite = Image.open(sprite_path)
        pred_xy = project_points(pred_world[position], camera)
        pred_overlays.append(
            draw_sticks(
                sprite,
                xy=pred_xy,
                parents=parents,
                label=f"proposal pos f{frame_index:02d} travel={pos_travel:.3f} fk={fk_travel:.3f}",
                color=(80, 220, 120),
            )
        )
        bind_overlays.append(
            draw_sticks(sprite, xy=bind_xy, parents=parents, label=f"bind f{frame_index:02d}", color=(220, 180, 80))
        )
    return compose_gif(
        sprite_dir=sprite_dir,
        overlay_pred=pred_overlays,
        overlay_bind=bind_overlays,
        dest=dest,
        frame_indices=frame_indices,
    )
