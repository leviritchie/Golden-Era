"""Unlit skinned-mesh GIFs from a V2 proposal. No silhouette keep."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Mapping

import numpy as np
from PIL import Image, ImageDraw

EXPERIMENT = Path(__file__).resolve().parent
if str(EXPERIMENT) not in sys.path:
    sys.path.insert(0, str(EXPERIMENT))

from glb_skeleton import BindSkeleton, load_bind_skeleton
from paths import SOURCE_FRAME_MS
from preview import compose_gif, project_points


def rotation_between(source: np.ndarray, target: np.ndarray) -> np.ndarray:
    a = np.asarray(source, dtype=np.float64).reshape(3)
    b = np.asarray(target, dtype=np.float64).reshape(3)
    a_norm = float(np.linalg.norm(a))
    b_norm = float(np.linalg.norm(b))
    if a_norm < 1e-8 or b_norm < 1e-8:
        return np.eye(3, dtype=np.float64)
    a = a / a_norm
    b = b / b_norm
    cos = float(np.clip(np.dot(a, b), -1.0, 1.0))
    if cos > 0.999999:
        return np.eye(3, dtype=np.float64)
    if cos < -0.999999:
        axis = np.cross(a, np.array((1.0, 0.0, 0.0)))
        if float(np.linalg.norm(axis)) < 1e-6:
            axis = np.cross(a, np.array((0.0, 1.0, 0.0)))
        axis = axis / float(np.linalg.norm(axis))
        k = np.array(
            [[0.0, -axis[2], axis[1]], [axis[2], 0.0, -axis[0]], [-axis[1], axis[0], 0.0]],
            dtype=np.float64,
        )
        return np.eye(3) + 2.0 * (k @ k)
    v = np.cross(a, b)
    k = np.array([[0.0, -v[2], v[1]], [v[2], 0.0, -v[0]], [-v[1], v[0], 0.0]], dtype=np.float64)
    return np.eye(3) + k + (k @ k) * (1.0 / (1.0 + cos))


def fk_world_matrices(
    *,
    local_rotation: np.ndarray,
    local_translation: np.ndarray,
    parents: np.ndarray,
    root_world: np.ndarray,
) -> np.ndarray:
    joint_count = local_rotation.shape[0]
    world = np.zeros((joint_count, 4, 4), dtype=np.float64)
    for index in range(joint_count):
        parent = int(parents[index])
        rotation = np.asarray(local_rotation[index], dtype=np.float64)
        translation = np.asarray(local_translation[index], dtype=np.float64)
        if parent < 0:
            world_rot = rotation
            world_pos = np.asarray(root_world, dtype=np.float64)
        else:
            parent_rot = world[parent, :3, :3]
            world_rot = parent_rot @ rotation
            world_pos = world[parent, :3, 3] + parent_rot @ translation
        world[index, :3, :3] = world_rot
        world[index, :3, 3] = world_pos
        world[index, 3, 3] = 1.0
    return world


def kinematic_clip_worlds(
    *,
    skeleton: BindSkeleton,
    mesh_glb: Path,
    joint_names_path: Path,
    clip_recipe_path: Path,
    frame_count: int,
) -> np.ndarray:
    """Idle-bookended FK from an authored weighted-memory clip recipe."""
    from aim_chains import idle_bookend_worlds
    from memory_bank import load_clip_recipe, load_memory_recipe, source_local_from_pose_blend
    from names import semantic_joint_names

    with mesh_glb.open("rb") as handle:
        digest = hashlib.file_digest(handle, "sha256").hexdigest()
    clip_recipe = load_clip_recipe(clip_recipe_path, frame_count=frame_count, mesh_sha256=digest)
    memory_recipe = load_memory_recipe(clip_recipe["memoryRecipePath"])
    readable = semantic_joint_names(joint_names_path, mesh_glb, skeleton.names)
    clip_worlds = []
    for blend in clip_recipe["frames"]:
        local = source_local_from_pose_blend(
            rest_local_rotation=skeleton.rest_local_rotation,
            rest_local_translation=skeleton.rest_local_translation,
            parents=np.asarray(skeleton.parents),
            readable_names=readable,
            recipe=memory_recipe,
            blend=blend,
        )
        clip_worlds.append(
            fk_world_matrices(
                local_rotation=local,
                local_translation=skeleton.rest_local_translation,
                parents=np.asarray(skeleton.parents),
                root_world=skeleton.rest_world[0],
            )
        )
    return idle_bookend_worlds(np.stack(clip_worlds), rest_world_matrices(skeleton))


def rest_world_matrices(skeleton: BindSkeleton) -> np.ndarray:
    parents = np.asarray(skeleton.parents, dtype=np.int64)
    return fk_world_matrices(
        local_rotation=skeleton.rest_local_rotation,
        local_translation=skeleton.rest_local_translation,
        parents=parents,
        root_world=skeleton.rest_world[0],
    )


def _validate_rotation_stack(values: np.ndarray, *, label: str) -> np.ndarray:
    values = np.asarray(values, dtype=np.float64)
    if values.ndim != 4 or values.shape[-2:] != (3, 3):
        raise ValueError(f"{label} must be [T,J,3,3], got {values.shape}")
    if not np.isfinite(values).all():
        raise ValueError(f"{label} contains non-finite values")
    return values


def _source_to_model_matrix(source_to_model: np.ndarray | None) -> np.ndarray:
    if source_to_model is None:
        return np.eye(3, dtype=np.float64)
    matrix = np.asarray(source_to_model, dtype=np.float64)
    if matrix.shape != (3, 3) or not np.isfinite(matrix).all():
        raise ValueError(f"source_to_model must be finite 3x3, got {matrix.shape}")
    if not np.allclose(matrix @ matrix.T, np.eye(3), atol=1e-5, rtol=0.0):
        raise ValueError("source_to_model must be orthonormal")
    if float(np.linalg.det(matrix)) < 0.0:
        raise ValueError("source_to_model must preserve handedness")
    return matrix


def validate_preview_camera(camera: dict) -> dict:
    """Validate the stored orthographic camera without repairing it."""
    if not isinstance(camera, dict):
        raise ValueError("preview camera must be an object")
    basis = np.asarray(camera.get("basisScreenRows"), dtype=np.float64)
    if basis.shape != (2, 3) or not np.isfinite(basis).all():
        raise ValueError("preview camera basis must be finite 2x3")
    norms = np.linalg.norm(basis, axis=1)
    if np.any(norms <= 1e-8):
        raise ValueError("preview camera basis contains a zero row")
    if not np.allclose(basis @ basis.T, np.eye(2), atol=1e-4, rtol=0.0):
        raise ValueError("preview camera basis rows must be orthonormal")
    try:
        scale = float(camera.get("pxPerWorld"))
    except (TypeError, ValueError) as exc:
        raise ValueError("preview camera pxPerWorld must be finite and positive") from exc
    if not np.isfinite(scale) or scale <= 0.0:
        raise ValueError("preview camera pxPerWorld must be finite and positive")
    offset = np.asarray(camera.get("screenOffsetPx"), dtype=np.float64)
    if offset.shape != (2,) or not np.isfinite(offset).all():
        raise ValueError("preview camera screenOffsetPx must be finite length 2")
    return camera


def validate_pose_world(joint_world: np.ndarray, *, joint_count: int) -> np.ndarray:
    """Reject malformed homogeneous transforms before skinning or rasterization.

    The source GLB bind linear blocks can contain small imported scale/shear
    residuals. They are part of the source rig and must not be normalized away;
    native retargeting therefore requires finite, invertible, handedness-
    preserving blocks rather than mathematically perfect rotations.
    """
    values = np.asarray(joint_world, dtype=np.float64)
    if values.shape != (joint_count, 4, 4) or not np.isfinite(values).all():
        raise ValueError(f"posed joint world must be finite [{joint_count},4,4]")
    if not np.allclose(values[:, 3, :], np.asarray((0.0, 0.0, 0.0, 1.0)), atol=1e-5, rtol=0.0):
        raise ValueError("posed joint world has invalid homogeneous rows")
    rotations = values[:, :3, :3]
    determinants = np.linalg.det(rotations)
    if not np.isfinite(determinants).all() or np.any(determinants <= 1e-8):
        raise ValueError("posed joint world contains a singular or reflected transform")
    return values


def validate_pose_vertices(vertices: np.ndarray, *, vertex_count: int) -> np.ndarray:
    values = np.asarray(vertices, dtype=np.float64)
    if values.shape != (vertex_count, 3) or not np.isfinite(values).all():
        raise ValueError(f"posed vertices must be finite [{vertex_count},3]")
    return values


def _global_rotations(local_rotation: np.ndarray, parents: np.ndarray) -> np.ndarray:
    """Compose local rotations in the topological joint order."""
    local = _validate_rotation_stack(
        np.asarray(local_rotation, dtype=np.float64)[None, ...],
        label="local_rotation",
    )[0]
    parent = np.asarray(parents, dtype=np.int64).reshape(-1)
    if local.shape[0] != parent.shape[0]:
        raise ValueError("local rotation and parent counts differ")
    world = np.zeros_like(local)
    for index, parent_index in enumerate(parent):
        if int(parent_index) < 0:
            world[index] = local[index]
        else:
            if int(parent_index) >= index:
                raise ValueError("parents must precede children")
            world[index] = world[int(parent_index)] @ local[index]
    return world


def source_local_rotations_from_model(
    *,
    model_local_rotation: np.ndarray,
    skeleton: BindSkeleton,
    source_to_model: np.ndarray | None = None,
) -> np.ndarray:
    """Map identity-rest BVH rotations back onto the original GLB rig.

    MoCapAnything's local rotations are relative to an identity-rest BVH.  The
    GLB has a non-identity bind orientation, so applying ``rest_local @ pred``
    is not a valid retarget.  Compose model global rotations, conjugate them
    into source space, compose with each source bind global rotation, and then
    recover source-local rotations.  Translations remain the original GLB
    translations and are handled by ``fk_world_matrices``.
    """
    pred_local = _validate_rotation_stack(model_local_rotation, label="model_local_rotation")
    joint_count = len(skeleton.parents)
    if pred_local.shape[1] != joint_count:
        raise ValueError(
            f"model rotation joint count {pred_local.shape[1]} != skeleton {joint_count}"
        )
    parents = np.asarray(skeleton.parents, dtype=np.int64)
    source_to_model = _source_to_model_matrix(source_to_model)
    model_to_source = source_to_model.T
    bind_global = _global_rotations(skeleton.rest_local_rotation, parents)
    model_global = np.empty_like(pred_local)
    for frame in range(pred_local.shape[0]):
        model_global[frame] = _global_rotations(pred_local[frame], parents)

    # A_j = C.T @ M_j @ C @ B_j, followed by A_parent^-1 @ A_j.  B_j is the
    # source bind linear block, not guaranteed to be a perfect rotation.
    source_global = np.matmul(
        np.matmul(
            np.matmul(model_to_source[None, None], model_global),
            source_to_model[None, None],
        ),
        bind_global[None],
    )
    source_local = np.empty_like(source_global)
    for index, parent in enumerate(parents):
        if int(parent) < 0:
            source_local[:, index] = source_global[:, index]
        else:
            source_local[:, index] = np.linalg.solve(
                source_global[:, int(parent)],
                source_global[:, index],
            )
    return source_local


def model_fk_positions_mapped_to_source(
    *,
    model_local_rotation: np.ndarray,
    skeleton: BindSkeleton,
    source_to_model: np.ndarray | None = None,
) -> np.ndarray:
    """Canonical identity-BVH FK positions, mapped back into GLB space."""
    pred_local = _validate_rotation_stack(model_local_rotation, label="model_local_rotation")
    source_to_model = _source_to_model_matrix(source_to_model)
    parents = np.asarray(skeleton.parents, dtype=np.int64)
    bind_global = _global_rotations(skeleton.rest_local_rotation, parents)
    source_offsets = np.asarray(skeleton.rest_local_translation, dtype=np.float64)
    model_offsets = np.zeros_like(source_offsets)
    for index, parent in enumerate(parents):
        if int(parent) < 0:
            model_offsets[index] = source_to_model @ source_offsets[index]
        else:
            source_world_offset = bind_global[int(parent)] @ source_offsets[index]
            model_offsets[index] = source_to_model @ source_world_offset
    model_root = np.asarray(skeleton.rest_world[0], dtype=np.float64) @ source_to_model.T
    positions = np.empty((pred_local.shape[0], len(parents), 3), dtype=np.float64)
    for frame in range(pred_local.shape[0]):
        model_world = fk_world_matrices(
            local_rotation=pred_local[frame],
            local_translation=model_offsets,
            parents=parents,
            root_world=model_root,
        )
        positions[frame] = model_world[:, :3, 3] @ source_to_model
    return positions


def rot6d_to_matrices(rot6d: np.ndarray) -> np.ndarray:
    from preview import _vendor_on_path

    _vendor_on_path()
    import torch
    from utils.transforms3d import rotation_6d_to_matrix

    tensor = torch.from_numpy(np.asarray(rot6d, dtype=np.float32))
    return rotation_6d_to_matrix(tensor).detach().cpu().numpy().astype(np.float64)


def joint_world_from_pred_rot6d(
    *,
    pred_rot6d: np.ndarray,
    skeleton: BindSkeleton,
    source_to_model: np.ndarray | None = None,
) -> np.ndarray:
    raw = np.asarray(pred_rot6d, dtype=np.float32)
    if raw.ndim not in (2, 3) or raw.shape[-1] != 6:
        raise ValueError(f"pred_rot6d must be [J,6] or [T,J,6], got {raw.shape}")
    single = raw.ndim == 2
    pred = rot6d_to_matrices(raw if not single else raw[None, ...])
    local = source_local_rotations_from_model(
        model_local_rotation=pred,
        skeleton=skeleton,
        source_to_model=source_to_model,
    )
    parents = np.asarray(skeleton.parents, dtype=np.int64)
    if local.shape[0] == 0:
        raise ValueError("pred_rot6d has no frames")
    worlds = np.stack(
        [
            fk_world_matrices(
                local_rotation=frame,
                local_translation=skeleton.rest_local_translation,
                parents=parents,
                root_world=skeleton.rest_world[0],
            )
            for frame in local
        ],
        axis=0,
    )
    return worlds[0] if single else worlds


def joint_world_from_pred_positions(
    *,
    pred_world: np.ndarray,
    skeleton: BindSkeleton,
) -> np.ndarray:
    """Aim each bone using carried parent rotation. Rest bone lengths. Root stays at bind."""
    parents = np.asarray(skeleton.parents, dtype=np.int64)
    joint_count = len(parents)
    children: list[list[int]] = [[] for _ in range(joint_count)]
    for index, parent in enumerate(parents):
        if int(parent) >= 0:
            children[int(parent)].append(index)
    rest_world = np.asarray(skeleton.rest_world, dtype=np.float64)
    pred = np.asarray(pred_world, dtype=np.float64)
    world = np.zeros((joint_count, 4, 4), dtype=np.float64)
    world[0, :3, 3] = rest_world[0]
    world[0, 3, 3] = 1.0
    for index in range(joint_count):
        if index == 0:
            carried = np.asarray(skeleton.rest_local_rotation[0], dtype=np.float64)
        else:
            parent = int(parents[index])
            carried = world[parent, :3, :3] @ skeleton.rest_local_rotation[index]
        kids = children[index]
        if kids:
            lengths = [float(np.linalg.norm(rest_world[child] - rest_world[index])) for child in kids]
            primary = kids[int(np.argmax(lengths))]
            rest_bone = carried @ skeleton.rest_local_translation[primary]
            pred_bone = pred[primary] - pred[index]
            world[index, :3, :3] = rotation_between(rest_bone, pred_bone) @ carried
        else:
            world[index, :3, :3] = carried
        world[index, 3, 3] = 1.0
        for child in kids:
            world[child, :3, 3] = world[index, :3, 3] + world[index, :3, :3] @ skeleton.rest_local_translation[child]
            world[child, 3, 3] = 1.0
    return world


def joint_world_from_named_chains(
    *,
    pred_world: np.ndarray,
    skeleton: BindSkeleton,
    aim_tips: Mapping[int, int],
) -> np.ndarray:
    """Rotate each chain root so its rest tip direction matches the proposal.

    Intermediate joints keep rest-local shape. Hubs that are not chain roots
    keep carried rest. Bone lengths stay at bind length.
    """
    parents = np.asarray(skeleton.parents, dtype=np.int64)
    joint_count = len(parents)
    children: list[list[int]] = [[] for _ in range(joint_count)]
    for index, parent in enumerate(parents):
        if int(parent) >= 0:
            children[int(parent)].append(index)
    rest_world = np.asarray(skeleton.rest_world, dtype=np.float64)
    pred = np.asarray(pred_world, dtype=np.float64)
    if pred.shape != (joint_count, 3) or not np.isfinite(pred).all():
        raise ValueError(f"pred_world must be finite [{joint_count},3], got {pred.shape}")
    bind = rest_world_matrices(skeleton)
    bind_rot = bind[:, :3, :3]
    local_tip: dict[int, np.ndarray] = {}
    for root, tip in aim_tips.items():
        root_i = int(root)
        tip_i = int(tip)
        if min(root_i, tip_i) < 0 or max(root_i, tip_i) >= joint_count:
            raise ValueError(f"aim pair ({root_i}, {tip_i}) is outside the skeleton")
        delta = rest_world[tip_i] - rest_world[root_i]
        if float(np.linalg.norm(delta)) < 1e-8:
            raise ValueError(f"chain root {root_i} and tip {tip_i} are coincident at rest")
        local_tip[root_i] = np.linalg.solve(bind_rot[root_i], delta)
    world = np.zeros((joint_count, 4, 4), dtype=np.float64)
    world[0, :3, 3] = rest_world[0]
    world[0, 3, 3] = 1.0
    for index in range(joint_count):
        if index == 0:
            carried = np.asarray(skeleton.rest_local_rotation[0], dtype=np.float64)
        else:
            parent = int(parents[index])
            carried = world[parent, :3, :3] @ skeleton.rest_local_rotation[index]
        if index in local_tip:
            rest_bone = carried @ local_tip[index]
            pred_bone = pred[int(aim_tips[index])] - pred[index]
            world[index, :3, :3] = rotation_between(rest_bone, pred_bone) @ carried
        else:
            world[index, :3, :3] = carried
        world[index, 3, 3] = 1.0
        for child in children[index]:
            world[child, :3, 3] = (
                world[index, :3, 3] + world[index, :3, :3] @ skeleton.rest_local_translation[child]
            )
            world[child, 3, 3] = 1.0
    return world


def proposal_source_pred_world(
    *,
    pred_position: np.ndarray,
    reference: Mapping[str, np.ndarray],
    skeleton: BindSkeleton,
) -> np.ndarray:
    """Map V2 root-centered positions into source GLB world coordinates."""
    pred = np.asarray(pred_position, dtype=np.float64)
    joint_count = len(skeleton.names)
    if pred.ndim != 3 or pred.shape[1] < joint_count or pred.shape[2] != 3:
        raise ValueError(f"pred_position must be [T,>=J,3], got {pred.shape}")
    if not np.isfinite(pred).all():
        raise ValueError("pred_position contains non-finite values")
    scale = float(np.asarray(reference["global_scale"]).reshape(-1)[0])
    if not np.isfinite(scale) or scale <= 0.0:
        raise ValueError(f"global_scale must be finite and positive, got {scale}")
    source_to_model = None
    files = reference.files if hasattr(reference, "files") else reference
    if "source_to_model" in files:
        source_to_model = _source_to_model_matrix(reference["source_to_model"])
    model_root = np.asarray(skeleton.rest_world[0], dtype=np.float64)
    if source_to_model is not None:
        model_root = model_root @ source_to_model.T
    pred_model_world = pred[:, :joint_count] * scale + model_root
    if source_to_model is not None:
        return pred_model_world @ source_to_model
    return pred_model_world


def skin_vertices(skeleton: BindSkeleton, joint_world: np.ndarray) -> np.ndarray:
    if skeleton.vertices is None or skeleton.vertex_joints is None or skeleton.vertex_weights is None:
        raise ValueError("GLB has no skinned vertices")
    if skeleton.inverse_bind is None:
        raise ValueError("GLB has no inverse bind matrices")
    vertices = np.asarray(skeleton.vertices, dtype=np.float64)
    joints = np.asarray(skeleton.vertex_joints, dtype=np.int32)
    weights = np.asarray(skeleton.vertex_weights, dtype=np.float64)
    weight_sum = weights.sum(axis=1, keepdims=True)
    weight_sum = np.where(weight_sum < 1e-8, 1.0, weight_sum)
    weights = weights / weight_sum
    bind = np.asarray(skeleton.inverse_bind, dtype=np.float64)
    palette = np.matmul(joint_world, bind)
    hom = np.concatenate([vertices, np.ones((len(vertices), 1), dtype=np.float64)], axis=1)
    posed = np.zeros_like(vertices)
    for slot in range(joints.shape[1]):
        joint_index = joints[:, slot]
        weight = weights[:, slot][:, None]
        moved = np.einsum("nij,nj->ni", palette[joint_index], hom)[:, :3]
        posed += weight * moved
    return posed


def skin_normals(skeleton: BindSkeleton, joint_world: np.ndarray) -> np.ndarray | None:
    if skeleton.normals is None:
        return None
    if skeleton.vertex_joints is None or skeleton.vertex_weights is None or skeleton.inverse_bind is None:
        raise ValueError("GLB has no skinned vertices")
    normals = np.asarray(skeleton.normals, dtype=np.float64)
    joints = np.asarray(skeleton.vertex_joints, dtype=np.int32)
    weights = np.asarray(skeleton.vertex_weights, dtype=np.float64)
    weight_sum = weights.sum(axis=1, keepdims=True)
    weight_sum = np.where(weight_sum < 1e-8, 1.0, weight_sum)
    weights = weights / weight_sum
    bind = np.asarray(skeleton.inverse_bind, dtype=np.float64)
    palette = np.matmul(joint_world, bind)
    posed = np.zeros_like(normals)
    for slot in range(joints.shape[1]):
        joint_index = joints[:, slot]
        weight = weights[:, slot][:, None]
        rotated = np.einsum("nij,nj->ni", palette[joint_index, :3, :3], normals)
        posed += weight * rotated
    lengths = np.linalg.norm(posed, axis=1, keepdims=True)
    return posed / np.where(lengths < 1e-8, 1.0, lengths)


def sample_albedo_uv(albedo: np.ndarray, u: np.ndarray, v: np.ndarray) -> np.ndarray:
    height, width = albedo.shape[:2]
    uu = np.clip(u, 0.0, 1.0) * (width - 1)
    vv = np.clip(v, 0.0, 1.0) * (height - 1)
    x0 = np.floor(uu).astype(np.int32)
    y0 = np.floor(vv).astype(np.int32)
    x1 = np.minimum(x0 + 1, width - 1)
    y1 = np.minimum(y0 + 1, height - 1)
    fx = (uu - x0).astype(np.float32)[..., None]
    fy = (vv - y0).astype(np.float32)[..., None]
    c00 = albedo[y0, x0, :3].astype(np.float32)
    c10 = albedo[y0, x1, :3].astype(np.float32)
    c01 = albedo[y1, x0, :3].astype(np.float32)
    c11 = albedo[y1, x1, :3].astype(np.float32)
    return c00 * (1.0 - fx) * (1.0 - fy) + c10 * fx * (1.0 - fy) + c01 * (1.0 - fx) * fy + c11 * fx * fy


def raster_mesh(
    *,
    vertices: np.ndarray,
    triangles: np.ndarray,
    camera: dict,
    width: int,
    height: int,
    uvs: np.ndarray | None = None,
    albedo: np.ndarray | None = None,
    normals: np.ndarray | None = None,
    return_face_ids: bool = False,
    cull_backfaces: bool = True,
    unlit: bool = False,
) -> Image.Image | tuple[Image.Image, np.ndarray]:
    """Raster opaque surfaces; optional IDs share the exact visible z-buffer."""
    xy = project_points(vertices, camera)
    basis = np.asarray(camera["basisScreenRows"], dtype=np.float64)
    view = np.cross(basis[0], basis[1])
    view_norm = float(np.linalg.norm(view))
    if view_norm < 1e-8:
        raise ValueError("camera basis is degenerate")
    view = view / view_norm
    # Smaller vertices·view is closer. Camera sits along -view, looking along +view.
    # Outward front faces point toward the camera, so n·view < 0.
    depth = vertices @ view
    zbuf = np.full((height, width), np.inf, dtype=np.float32)
    out = np.zeros((height, width, 4), dtype=np.uint8)
    face_ids = np.full((height, width), -1, dtype=np.int32) if return_face_ids else None
    tri = np.asarray(triangles, dtype=np.int32)
    for face_id, (a, b, c) in enumerate(tri):
        normal = np.cross(vertices[b] - vertices[a], vertices[c] - vertices[a])
        if cull_backfaces and float(normal @ view) > 1e-12:
            continue
        pts = [int(a), int(b), int(c)]
        x0, y0 = xy[pts[0]]
        x1, y1 = xy[pts[1]]
        x2, y2 = xy[pts[2]]
        area = (x1 - x0) * (y2 - y0) - (x2 - x0) * (y1 - y0)
        if abs(area) < 1e-6:
            continue
        if area < 0:
            pts[1], pts[2] = pts[2], pts[1]
            x1, y1, x2, y2 = x2, y2, x1, y1
            area = -area
        i0, i1, i2 = pts
        minx = max(0, int(np.floor(min(x0, x1, x2))))
        maxx = min(width - 1, int(np.ceil(max(x0, x1, x2))))
        miny = max(0, int(np.floor(min(y0, y1, y2))))
        maxy = min(height - 1, int(np.ceil(max(y0, y1, y2))))
        if minx > maxx or miny > maxy:
            continue
        xs = np.arange(minx, maxx + 1) + 0.5
        ys = np.arange(miny, maxy + 1) + 0.5
        grid_x, grid_y = np.meshgrid(xs, ys)
        w0 = ((x1 - grid_x) * (y2 - grid_y) - (x2 - grid_x) * (y1 - grid_y)) / area
        w1 = ((x2 - grid_x) * (y0 - grid_y) - (x0 - grid_x) * (y2 - grid_y)) / area
        w2 = 1.0 - w0 - w1
        mask = (w0 >= -1e-6) & (w1 >= -1e-6) & (w2 >= -1e-6)
        if not np.any(mask):
            continue
        zpix = (w0 * depth[i0] + w1 * depth[i1] + w2 * depth[i2]).astype(np.float32)
        window = zbuf[miny : maxy + 1, minx : maxx + 1]
        closer = mask & (zpix < window)
        if not np.any(closer):
            continue
        if normals is not None:
            n = w0[..., None] * normals[i0] + w1[..., None] * normals[i1] + w2[..., None] * normals[i2]
            nlen = np.linalg.norm(n, axis=2, keepdims=True)
            ndot = (n @ view) / np.maximum(nlen[..., 0], 1e-8)
            shade = np.clip(0.55 + 0.45 * np.clip(-ndot, 0.0, 1.0), 0.35, 1.0)[..., None]
        else:
            nlen = float(np.linalg.norm(normal))
            shade = float(np.clip(0.55 + 0.45 * max(0.0, -float(normal @ view) / (nlen + 1e-8)), 0.35, 1.0))
        if unlit:
            shade = 1.0
        if albedo is not None and uvs is not None:
            u = w0 * uvs[i0, 0] + w1 * uvs[i1, 0] + w2 * uvs[i2, 0]
            v = w0 * uvs[i0, 1] + w1 * uvs[i1, 1] + w2 * uvs[i2, 1]
            rgb = sample_albedo_uv(albedo, u, v) * shade
        else:
            if np.ndim(shade) == 0:
                rgb = np.full(grid_x.shape + (3,), 200.0 * float(shade), dtype=np.float32)
            else:
                rgb = np.full(grid_x.shape + (3,), 200.0, dtype=np.float32) * shade
        window[closer] = zpix[closer]
        if face_ids is not None:
            face_ids[miny : maxy + 1, minx : maxx + 1][closer] = face_id
        rgb_u8 = np.clip(rgb, 0, 255).astype(np.uint8)
        dest = out[miny : maxy + 1, minx : maxx + 1]
        dest[..., 0][closer] = rgb_u8[..., 0][closer]
        dest[..., 1][closer] = rgb_u8[..., 1][closer]
        dest[..., 2][closer] = rgb_u8[..., 2][closer]
        dest[..., 3][closer] = 255
    image = Image.fromarray(out, mode="RGBA")
    return (image, face_ids) if return_face_ids else image


def visible_faces_in_polygon(face_ids: np.ndarray, polygon: np.ndarray) -> dict:
    """Select only z-buffer-visible opaque faces, never projected hidden centers."""
    ids = np.asarray(face_ids)
    points = np.asarray(polygon, dtype=np.float64)
    if ids.ndim != 2 or not ids.size or ids.dtype.kind not in 'iu' or np.any(ids < -1):
        raise ValueError('face IDs must be a 2D integer buffer with -1 background')
    if points.ndim != 2 or points.shape[1] != 2 or len(points) < 3 or not np.isfinite(points).all():
        raise ValueError('selection polygon requires at least three finite pixel points')
    twice_area = np.sum(points[:, 0] * np.roll(points[:, 1], -1) - points[:, 1] * np.roll(points[:, 0], -1))
    if abs(twice_area) <= 1e-9:
        raise ValueError('selection polygon has zero signed area')
    height, width = ids.shape
    if np.any(points < 0) or np.any(points[:, 0] > width) or np.any(points[:, 1] > height):
        raise ValueError('selection polygon leaves its pinned image bounds')
    from PIL import ImageDraw
    mask = Image.new('1', (width, height), 0)
    ImageDraw.Draw(mask).polygon([tuple(point) for point in points], fill=1)
    selected = ids[np.asarray(mask, dtype=bool)]
    faces, counts = np.unique(selected[selected >= 0], return_counts=True)
    return {'faceIds': faces.tolist(), 'visiblePixelCounts': counts.tolist(),
            'method': 'opaque-z-buffer-visible-polygon', 'imageSize': [width, height]}


def prepare_albedo(albedo: np.ndarray | None, *, max_size: int = 1024) -> np.ndarray | None:
    """Box-filter a 4K atlas so a ~150px character does not alias into noise."""
    if albedo is None:
        return None
    height, width = albedo.shape[:2]
    if max(height, width) <= max_size:
        return albedo
    scale = max_size / float(max(height, width))
    size = (max(1, int(round(width * scale))), max(1, int(round(height * scale))))
    return np.asarray(Image.fromarray(albedo).resize(size, Image.Resampling.BOX))


def y_up_basis_from_job_camera(job_camera: dict) -> dict:
    """Job cameras in roc_sprite_camera_fit.json are Z-up. Meshy GLBs are glTF Y-up."""
    basis = np.asarray(job_camera["basisScreenRows"], dtype=np.float64)
    if basis.shape != (2, 3):
        raise ValueError(f"basisScreenRows must be 2x3, got {basis.shape}")
    # glTF (x, y, z) -> Z-up (x, -z, y). Apply the job basis in that frame.
    remapped = np.stack([basis[:, 0], basis[:, 2], -basis[:, 1]], axis=1)
    camera = dict(job_camera)
    camera["basisScreenRows"] = remapped.tolist()
    camera["basisName"] = "job_z_up_to_gltf_y_up"
    camera["cameraPolicy"] = "job_camera_y_up_remap"
    return camera


def panel_fit_camera(vertices: np.ndarray, source: dict, *, width: int, height: int, margin: float = 0.08) -> dict:
    basis = np.asarray(source["basisScreenRows"], dtype=np.float64)
    xy = (basis @ np.asarray(vertices, dtype=np.float64).T).T
    span = np.maximum(xy.max(axis=0) - xy.min(axis=0), 1e-8)
    scale = (1.0 - 2.0 * margin) * min(width / span[0], height / span[1])
    if scale <= 0:
        raise ValueError("panel fit scale is not positive")
    offset = np.asarray((width * 0.5, height * 0.5), dtype=np.float64) - scale * xy.mean(axis=0)
    camera = dict(source)
    camera["cameraPolicy"] = "mesh_panel_fit"
    camera["pxPerWorld"] = float(scale)
    camera["screenOffsetPx"] = offset.tolist()
    return camera


def _label(image: Image.Image, text: str) -> Image.Image:
    labeled = image.convert("RGB")
    draw = ImageDraw.Draw(labeled)
    draw.rectangle((0, 0, labeled.width, 16), fill=(12, 12, 16))
    draw.text((4, 2), text, fill=(230, 230, 235))
    return labeled


def _load_clip_sprite(sprite_dir: Path, frame_index: int) -> Image.Image:
    sprite_path = sprite_dir / f"{int(frame_index):02d}.png"
    if not sprite_path.is_file():
        sprite_path = sprite_dir / f"{int(frame_index)}.png"
    if not sprite_path.is_file():
        raise FileNotFoundError(f"clip sprite is missing: {sprite_path}")
    return Image.open(sprite_path).convert("RGBA")


def write_mesh_gif(
    *,
    sprite_dir: Path,
    proposal_npz: Path,
    rig_json: Path,
    mesh_glb: Path,
    idle_png: Path,
    dest: Path,
    drive: str = "named_chain_ik",
    joint_names_path: Path | None = None,
    clip_recipe_path: Path | None = None,
    weave_pose_path: Path | None = None,
) -> Path:
    if drive not in {"native_rot", "position_ik", "named_chain_ik", "kinematic_clip", "weaved"}:
        raise ValueError(
            "drive must be 'native_rot', 'position_ik', 'named_chain_ik', 'kinematic_clip', or 'weaved'"
        )
    dest.parent.mkdir(parents=True, exist_ok=True)
    payload = np.load(proposal_npz)
    rig = json.loads(rig_json.read_text(encoding="utf-8"))
    reference = np.load(rig_json.with_name("reference.npz"))
    skeleton = load_bind_skeleton(mesh_glb)
    joint_count = int(reference["J_valid"][0])
    if joint_count != len(skeleton.names):
        raise ValueError(f"proposal has {joint_count} joints, mesh has {len(skeleton.names)}")
    if skeleton.triangles is None:
        raise ValueError(f"{mesh_glb} has no triangles")
    camera = rig.get("camera")
    if not camera or camera.get("cameraPolicy") != "idle_yaw_register":
        raise ValueError(
            "rig.json must contain the stored idle_yaw_register camera; "
            "refusing to silently change preview registration"
        )
    validate_preview_camera(camera)
    frame_indices = [int(value) for value in payload["frame_indices"]]
    if not frame_indices:
        raise ValueError("proposal has no frame indices")
    rest_joints = rest_world_matrices(skeleton)
    pose_label = {
        "native_rot": "native pred-rot mesh",
        "position_ik": "position-IK mesh",
        "named_chain_ik": "named-chain mesh",
        "kinematic_clip": "kinematic-clip mesh",
        "weaved": "weaved mesh",
    }[drive]
    loop_policy = "clip_frames"
    gif_frame_indices = list(frame_indices)
    sprites: list[Image.Image] | None = None
    if drive == "weaved":
        if weave_pose_path is None:
            raise ValueError("weaved drive requires weave_pose_path")
        weave = np.load(weave_pose_path)
        if "posed_joint_world" not in weave.files:
            raise KeyError("weave_pose.npz is missing posed_joint_world")
        posed_joint_world = np.asarray(weave["posed_joint_world"], dtype=np.float64)
        expected = (len(frame_indices) + 2, joint_count, 4, 4)
        if posed_joint_world.shape != expected:
            raise ValueError(f"weaved worlds {posed_joint_world.shape} != {expected}")
        loop_policy = "idle_bookend"
        idle = Image.open(idle_png).convert("RGBA")
        clip_sprites = [_load_clip_sprite(sprite_dir, index) for index in frame_indices]
        if any(sprite.size != idle.size for sprite in clip_sprites):
            raise ValueError("idle canvas does not match clip canvas; refusing loop bookend")
        sprites = [idle, *clip_sprites, idle]
        gif_frame_indices = [-1, *frame_indices, -1]
    elif drive == "kinematic_clip":
        if joint_names_path is None or clip_recipe_path is None:
            raise ValueError("kinematic_clip requires joint_names_path and clip_recipe_path")
        posed_joint_world = kinematic_clip_worlds(
            skeleton=skeleton,
            mesh_glb=mesh_glb,
            joint_names_path=joint_names_path,
            clip_recipe_path=clip_recipe_path,
            frame_count=len(frame_indices),
        )
        loop_policy = "idle_bookend"
        idle = Image.open(idle_png).convert("RGBA")
        clip_sprites = [_load_clip_sprite(sprite_dir, index) for index in frame_indices]
        if any(sprite.size != idle.size for sprite in clip_sprites):
            raise ValueError("idle canvas does not match clip canvas; refusing loop bookend")
        sprites = [idle, *clip_sprites, idle]
        gif_frame_indices = [-1, *frame_indices, -1]
    elif drive == "native_rot":
        if "pred_rot6d" not in payload:
            raise KeyError("native_rot drive requires pred_rot6d in proposal")
        pred_rot6d = np.asarray(payload["pred_rot6d"], dtype=np.float32)
        if pred_rot6d.shape != (len(frame_indices), joint_count, 6):
            raise ValueError(
                f"pred_rot6d shape {pred_rot6d.shape} does not match "
                f"frames/joints {(len(frame_indices), joint_count, 6)}"
            )
        if not np.isfinite(pred_rot6d).all():
            raise ValueError("pred_rot6d contains non-finite values")
        source_to_model = None
        if "source_to_model" in reference.files:
            source_to_model = np.asarray(reference["source_to_model"], dtype=np.float64)
        posed_joint_world = joint_world_from_pred_rot6d(
            pred_rot6d=pred_rot6d,
            skeleton=skeleton,
            source_to_model=source_to_model,
        )
    else:
        if "pred_position" not in payload:
            raise KeyError(f"{drive} requires pred_position in proposal")
        pred_position = np.asarray(payload["pred_position"], dtype=np.float64)
        if pred_position.shape[:2] != (len(frame_indices), joint_count):
            raise ValueError(
                f"pred_position shape {pred_position.shape} does not match "
                f"frames/joints {(len(frame_indices), joint_count)}"
            )
        pred_world = proposal_source_pred_world(
            pred_position=pred_position,
            reference=reference,
            skeleton=skeleton,
        )
        if drive == "position_ik":
            posed_joint_world = np.stack(
                [
                    joint_world_from_pred_positions(pred_world=frame, skeleton=skeleton)
                    for frame in pred_world
                ]
            )
        elif drive == "named_chain_ik":
            if joint_names_path is None:
                raise ValueError("named_chain_ik requires joint_names_path")
            from aim_chains import chain_root_tips, idle_bookend_worlds, load_aim_chains

            aim_tips = chain_root_tips(
                load_aim_chains(joint_names_path, skeleton.names),
                skeleton.parents,
            )
            clip_worlds = np.stack(
                [
                    joint_world_from_named_chains(
                        pred_world=frame, skeleton=skeleton, aim_tips=aim_tips
                    )
                    for frame in pred_world
                ]
            )
            posed_joint_world = idle_bookend_worlds(clip_worlds, rest_joints)
            loop_policy = "idle_bookend"
            idle = Image.open(idle_png).convert("RGBA")
            clip_sprites = [_load_clip_sprite(sprite_dir, index) for index in frame_indices]
            if any(sprite.size != idle.size for sprite in clip_sprites):
                raise ValueError("idle canvas does not match clip canvas; refusing loop bookend")
            sprites = [idle, *clip_sprites, idle]
            gif_frame_indices = [-1, *frame_indices, -1]
        else:
            raise ValueError(f"unsupported preview drive {drive!r}")
    bind_vertices = skeleton.vertices
    if bind_vertices is None:
        raise ValueError(f"{mesh_glb} has no skinned vertices")
    bind_panels: list[Image.Image] = []
    posed_panels: list[Image.Image] = []
    identity3 = np.eye(3, dtype=np.float64)
    bind_transform_orthogonality_error = float(
        np.max(
            np.abs(
                np.matmul(
                    np.swapaxes(rest_joints[:, :3, :3], -1, -2),
                    rest_joints[:, :3, :3],
                )
                - identity3
            )
        )
    )
    rest_skinned = skin_vertices(skeleton, rest_joints)
    if float(np.linalg.norm(rest_skinned - bind_vertices, axis=1).mean()) > 1e-3:
        raise ValueError("rest skin does not recover bind vertices")
    albedo = prepare_albedo(skeleton.albedo)
    frame_reports: list[dict[str, object]] = []
    idle_rgba = Image.open(idle_png).convert("RGBA")
    for position, frame_index in enumerate(gif_frame_indices):
        if sprites is not None:
            sprite = sprites[position]
        else:
            sprite = _load_clip_sprite(sprite_dir, int(frame_index))
        bind_mesh = raster_mesh(
            vertices=bind_vertices,
            triangles=skeleton.triangles,
            camera=camera,
            width=sprite.width,
            height=sprite.height,
            uvs=skeleton.uvs,
            albedo=albedo,
            normals=skeleton.normals,
        )
        joints = posed_joint_world[position]
        validate_pose_world(joints, joint_count=joint_count)
        if drive == "native_rot":
            bind_linear = rest_joints[:, :3, :3]
            posed_linear = joints[:, :3, :3]
            if not np.allclose(
                np.swapaxes(posed_linear, -1, -2) @ posed_linear,
                np.swapaxes(bind_linear, -1, -2) @ bind_linear,
                atol=1e-4,
                rtol=0.0,
            ):
                raise ValueError(f"native rotation changed bind scale/shear at frame {frame_index}")
        posed = skin_vertices(skeleton, joints)
        validate_pose_vertices(posed, vertex_count=len(bind_vertices))
        posed_normals = skin_normals(skeleton, joints)
        if posed_normals is not None and not np.isfinite(posed_normals).all():
            raise ValueError(f"posed normals are non-finite at frame {frame_index}")
        posed_mesh = raster_mesh(
            vertices=posed,
            triangles=skeleton.triangles,
            camera=camera,
            width=sprite.width,
            height=sprite.height,
            uvs=skeleton.uvs,
            albedo=albedo,
            normals=posed_normals,
        )
        bind_alpha_pixels = int(np.count_nonzero(np.asarray(bind_mesh)[..., 3]))
        posed_alpha_pixels = int(np.count_nonzero(np.asarray(posed_mesh)[..., 3]))
        if bind_alpha_pixels <= 0:
            raise ValueError(f"bind raster is blank at frame {frame_index}")
        if posed_alpha_pixels <= 0:
            raise ValueError(f"posed raster is blank at frame {frame_index}")
        posed_transform_orthogonality_error = float(
            np.max(
                np.abs(
                    np.matmul(
                        np.swapaxes(joints[:, :3, :3], -1, -2),
                        joints[:, :3, :3],
                    )
                    - identity3
                )
            )
        )
        bookend = loop_policy == "idle_bookend" and (position == 0 or position == len(gif_frame_indices) - 1)
        frame_label = "idle" if bookend else f"f{int(frame_index):02d}"
        frame_reports.append(
            {
                "frame": None if bookend else int(frame_index),
                "bookend": bookend,
                "bindAlphaPixels": bind_alpha_pixels,
                "posedAlphaPixels": posed_alpha_pixels,
                "posedVerticesFinite": True,
                "posedTransformsFinite": True,
                "posedTransformOrthogonalityMaxError": posed_transform_orthogonality_error,
            }
        )
        bind_panels.append(_label(bind_mesh, f"bind mesh {frame_label}"))
        posed_panels.append(_label(posed_mesh, f"{pose_label} {frame_label}"))
        if position == 0:
            if idle_rgba.size != bind_mesh.size:
                raise ValueError(f"idle canvas {idle_rgba.size} != bind raster {bind_mesh.size}")
            Image.alpha_composite(idle_rgba, bind_mesh).save(dest.with_name("bind_on_idle.png"))
    gif_path = compose_gif(
        sprite_dir=sprite_dir,
        overlay_pred=bind_panels,
        overlay_bind=posed_panels,
        dest=dest,
        frame_indices=gif_frame_indices,
        frame_ms=SOURCE_FRAME_MS,
        panel_titles=("sprite", "bind mesh", pose_label),
        sprites=sprites,
    )
    bookend_rest_error = 0.0
    if loop_policy == "idle_bookend":
        bookend_rest_error = float(
            max(
                np.linalg.norm(posed_joint_world[0, :, :3, 3] - rest_joints[:, :3, 3], axis=1).max(),
                np.linalg.norm(posed_joint_world[-1, :, :3, 3] - rest_joints[:, :3, 3], axis=1).max(),
            )
        )
        if bookend_rest_error > 1e-6:
            raise ValueError(f"idle bookends are not rest: max joint error {bookend_rest_error}")
    report = {
        "ok": True,
        "proof": "generated-artifact",
        "drive": drive,
        "loopPolicy": loop_policy,
        "clipFrames": frame_indices,
        "gifFrames": gif_frame_indices,
        "frameMsAverage": float(SOURCE_FRAME_MS),
        "cameraPolicy": camera.get("cameraPolicy"),
        "poseTransformValidation": "finite_homogeneous_invertible_positive_determinant",
        "bindTransformOrthogonalityMaxError": bind_transform_orthogonality_error,
        "posedTransformOrthogonalityMaxError": max(
            float(frame["posedTransformOrthogonalityMaxError"]) for frame in frame_reports
        ),
        "idleBookendRestJointErrorMax": bookend_rest_error,
        "frameReports": frame_reports,
        "gif": str(gif_path).replace("\\", "/"),
    }
    dest.with_name(f"{dest.stem}_report.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    return gif_path
