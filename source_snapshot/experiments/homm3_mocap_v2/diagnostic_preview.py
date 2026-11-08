"""Four-panel recovery/transfer GIFs. No idle bookends and no recipe drives."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PIL import Image

from glb_skeleton import load_bind_skeleton
from idle_camera import yaw_basis
from mesh_preview import (
    joint_world_from_pred_rot6d,
    prepare_albedo,
    proposal_source_pred_world,
    raster_mesh,
    rest_world_matrices,
    skin_normals,
    skin_vertices,
    validate_pose_vertices,
    validate_pose_world,
    validate_preview_camera,
)
from paths import SOURCE_FRAME_MS
from preview import compose_panel_gif, draw_sticks, project_points
from proposal_fk import rotation_fk_source_world


def _load_sprite(sprite_dir: Path, frame_index: int) -> Image.Image:
    path = sprite_dir / f"{int(frame_index):02d}.png"
    if not path.is_file():
        path = sprite_dir / f"{int(frame_index)}.png"
    if not path.is_file():
        raise FileNotFoundError(f"clip sprite is missing: {path}")
    return Image.open(path).convert("RGBA")


def _label(image: Image.Image, text: str) -> Image.Image:
    labeled = image.convert("RGB")
    from PIL import ImageDraw

    draw = ImageDraw.Draw(labeled)
    draw.rectangle((0, 0, labeled.width, 16), fill=(12, 12, 16))
    draw.text((4, 2), text, fill=(230, 230, 235))
    return labeled


def alternate_yaw_camera(camera: dict, *, extra_yaw_deg: float = 90.0) -> dict:
    validate_preview_camera(camera)
    base_yaw = float(camera.get("yawDeg", 0.0))
    yaw = (base_yaw + float(extra_yaw_deg)) % 360.0
    basis = yaw_basis(yaw)
    alt = dict(camera)
    alt["basisScreenRows"] = basis.tolist()
    alt["yawDeg"] = yaw
    alt["cameraPolicy"] = "idle_yaw_register_plus_yaw"
    alt["basisName"] = "y_up_yaw"
    validate_preview_camera(alt)
    return alt


def disagreement_report(
    *,
    pred_world: np.ndarray,
    rotation_world: np.ndarray,
    native_world: np.ndarray,
) -> dict[str, float]:
    pred = np.asarray(pred_world, dtype=np.float64)
    rot = np.asarray(rotation_world, dtype=np.float64)
    native = np.asarray(native_world, dtype=np.float64)
    rot_err = np.linalg.norm(rot - pred, axis=-1)
    native_err = np.linalg.norm(native[:, :, :3, 3] - pred, axis=-1)
    return {
        "predVsRotationMean": float(rot_err.mean()),
        "predVsRotationMax": float(rot_err.max()),
        "predVsNativeMean": float(native_err.mean()),
        "predVsNativeMax": float(native_err.max()),
    }


def write_diagnostic_gifs(
    *,
    sprite_dir: Path,
    idle_png: Path,
    raw_npz: Path,
    rig_json: Path,
    mesh_glb: Path,
    dest_dir: Path,
    position_worlds: np.ndarray | None = None,
    position_gif_name: str = "review_position_transfer.gif",
    plate_png: Path | None = None,
) -> dict[str, str]:
    dest_dir.mkdir(parents=True, exist_ok=True)
    payload = np.load(raw_npz)
    rig = json.loads(rig_json.read_text(encoding="utf-8"))
    reference = np.load(rig_json.with_name("reference.npz"))
    skeleton = load_bind_skeleton(mesh_glb)
    joint_count = int(reference["J_valid"][0])
    if joint_count != len(skeleton.names):
        raise ValueError(f"proposal has {joint_count} joints, mesh has {len(skeleton.names)}")
    if skeleton.triangles is None or skeleton.vertices is None:
        raise ValueError(f"{mesh_glb} has no skinned triangles")
    camera = rig.get("camera")
    if not camera or not str(camera.get("cameraPolicy", "")).startswith("idle_yaw_register"):
        raise ValueError("rig.json must contain the stored idle_yaw_register camera")
    validate_preview_camera(camera)
    frame_indices = [int(value) for value in payload["frame_indices"]]
    pred_rot6d = np.asarray(payload["pred_rot6d"], dtype=np.float32)
    pred_position = np.asarray(payload["pred_position"], dtype=np.float64)
    if pred_rot6d.shape != (len(frame_indices), joint_count, 6):
        raise ValueError(f"pred_rot6d shape {pred_rot6d.shape} does not match clip")
    source_to_model = np.asarray(reference["source_to_model"], dtype=np.float64)
    pred_world = proposal_source_pred_world(
        pred_position=pred_position,
        reference=reference,
        skeleton=skeleton,
    )
    rotation_world = rotation_fk_source_world(
        pred_rot6d=pred_rot6d,
        reference=reference,
        skeleton=skeleton,
    )
    native_world = joint_world_from_pred_rot6d(
        pred_rot6d=pred_rot6d,
        skeleton=skeleton,
        source_to_model=source_to_model,
    )
    rest = rest_world_matrices(skeleton)
    albedo = prepare_albedo(skeleton.albedo)
    parents = np.asarray(skeleton.parents, dtype=np.int64)
    alt_camera = alternate_yaw_camera(camera, extra_yaw_deg=90.0)
    disagreement = disagreement_report(
        pred_world=pred_world,
        rotation_world=rotation_world,
        native_world=native_world,
    )

    def _rows(view_camera: dict, view_name: str) -> list[list[Image.Image]]:
        rows: list[list[Image.Image]] = []
        for index, frame_index in enumerate(frame_indices):
            sprite = _load_sprite(sprite_dir, frame_index)
            native = native_world[index]
            validate_pose_world(native, joint_count=joint_count)
            posed = skin_vertices(skeleton, native)
            validate_pose_vertices(posed, vertex_count=len(skeleton.vertices))
            posed_normals = skin_normals(skeleton, native)
            mesh = raster_mesh(
                vertices=posed,
                triangles=skeleton.triangles,
                camera=view_camera,
                width=sprite.width,
                height=sprite.height,
                uvs=skeleton.uvs,
                albedo=albedo,
                normals=posed_normals,
            )
            pred_xy = project_points(pred_world[index], view_camera)
            rot_xy = project_points(rotation_world[index], view_camera)
            pred_panel = draw_sticks(
                sprite,
                xy=pred_xy,
                parents=parents,
                label=f"pred pos {view_name} f{frame_index:02d}",
                color=(80, 220, 120),
            )
            rot_panel = draw_sticks(
                sprite,
                xy=rot_xy,
                parents=parents,
                label=f"pred rot FK {view_name} f{frame_index:02d}",
                color=(80, 160, 230),
            )
            rows.append(
                [
                    _label(sprite.convert("RGB"), f"sprite f{frame_index:02d}"),
                    pred_panel,
                    rot_panel,
                    _label(mesh, f"native mesh {view_name} f{frame_index:02d}"),
                ]
            )
        return rows

    front = dest_dir / "review_front.gif"
    alt = dest_dir / "review_alt_yaw90.gif"
    compose_panel_gif(
        panels=_rows(camera, "front"),
        titles=("sprite", "raw predicted skeleton", "rotation FK skeleton", "driven mesh"),
        dest=front,
        frame_ms=SOURCE_FRAME_MS,
    )
    compose_panel_gif(
        panels=_rows(alt_camera, "yaw90"),
        titles=("sprite", "raw predicted skeleton", "rotation FK skeleton", "driven mesh"),
        dest=alt,
        frame_ms=SOURCE_FRAME_MS,
    )
    written = {"reviewFront": str(front).replace("\\", "/"), "reviewAltYaw90": str(alt).replace("\\", "/")}
    if position_worlds is not None:
        posed_ik = np.asarray(position_worlds, dtype=np.float64)
        if posed_ik.shape != native_world.shape:
            raise ValueError(f"position transfer worlds {posed_ik.shape} != native {native_world.shape}")
        ik_rows: list[list[Image.Image]] = []
        for index, frame_index in enumerate(frame_indices):
            sprite = _load_sprite(sprite_dir, frame_index)
            joints = posed_ik[index]
            validate_pose_world(joints, joint_count=joint_count)
            posed = skin_vertices(skeleton, joints)
            validate_pose_vertices(posed, vertex_count=len(skeleton.vertices))
            mesh = raster_mesh(
                vertices=posed,
                triangles=skeleton.triangles,
                camera=camera,
                width=sprite.width,
                height=sprite.height,
                uvs=skeleton.uvs,
                albedo=albedo,
                normals=skin_normals(skeleton, joints),
            )
            pred_xy = project_points(pred_world[index], camera)
            ik_rows.append(
                [
                    _label(sprite.convert("RGB"), f"sprite f{frame_index:02d}"),
                    draw_sticks(
                        sprite,
                        xy=pred_xy,
                        parents=parents,
                        label=f"pred pos f{frame_index:02d}",
                        color=(80, 220, 120),
                    ),
                    _label(mesh, f"position transfer f{frame_index:02d}"),
                ]
            )
        ik_path = dest_dir / position_gif_name
        compose_panel_gif(
            panels=ik_rows,
            titles=("sprite", "raw predicted skeleton", "position-transfer unsmoothed mesh"),
            dest=ik_path,
            frame_ms=SOURCE_FRAME_MS,
        )
        written["reviewPositionTransfer"] = str(ik_path).replace("\\", "/")
    bind_path = dest_dir / ("bind_on_idle.png" if plate_png is None else "bind_on_clip_f00.png")
    idle_like = Image.open(plate_png or idle_png).convert("RGBA")
    bind_mesh = raster_mesh(
        vertices=skeleton.vertices,
        triangles=skeleton.triangles,
        camera=camera,
        width=idle_like.width,
        height=idle_like.height,
        uvs=skeleton.uvs,
        albedo=albedo,
        normals=skeleton.normals,
    )
    Image.alpha_composite(idle_like, bind_mesh).save(bind_path)
    written["bindOnIdle"] = str(bind_path).replace("\\", "/")
    report = {
        "ok": True,
        "proof": "generated-artifact",
        "loopPolicy": "clip_frames",
        "clipFrames": frame_indices,
        "disagreement": disagreement,
        "gifs": written,
        "restSkinError": float(
            np.linalg.norm(skin_vertices(skeleton, rest) - skeleton.vertices, axis=1).mean()
        ),
    }
    (dest_dir / "diagnostic_preview_report.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    return written
