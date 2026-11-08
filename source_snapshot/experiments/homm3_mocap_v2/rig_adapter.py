"""Build a bind-reference bundle for MoCapAnything V2 from a SmartRig GLB."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping

import numpy as np

EXPERIMENT = Path(__file__).resolve().parent
if str(EXPERIMENT) not in sys.path:
    sys.path.insert(0, str(EXPERIMENT))

from glb_skeleton import load_bind_skeleton
from memory_bank import build_kinematic_memory, load_memory_recipe
from names import readable_joint_names, semantic_joint_names
from paths import CACHE, DATA, MAX_JOINTS, VENDOR, require_file
from topology import ancestor_mask, identity_rot6d, local_offsets, pad_joints


REQUIRED_NPZ = (
    "ref_position",
    "ref_rot6d",
    "offset",
    "parents",
    "joint_mask",
    "ancestor_mask",
    "graph_hop",
    "graph_edge",
    "joint_t5embed",
    "static_pos_joint_mask",
    "static_rot_joint_mask",
    "memory_pose",
    "memory_rot6d",
    "global_scale",
    "J_valid",
    "rest_world",
    "rest_local_rotation",
    "rest_local_translation",
    "node_indices",
)

MODEL_FORWARD = np.asarray((0.0, 0.0, 1.0), dtype=np.float64)


def source_to_model_matrix(source_facing: np.ndarray | list[float] | tuple[float, ...] | None) -> np.ndarray:
    """Return the column-vector Y-up rotation from GLB space to vendor +Z space.

    The SmartRig GLBs and the vendor BVH are both Y-up.  Only a grounded yaw is
    allowed here; accepting a guessed tilt or an arbitrary 3-D basis would make
    the bind/reference contract impossible to audit.  ``None`` is retained as
    the legacy direct-caller identity, while case definitions must provide a
    verified value (or fail closed in their runner).
    """
    if source_facing is None:
        return np.eye(3, dtype=np.float64)
    facing = np.asarray(source_facing, dtype=np.float64)
    if facing.shape != (3,) or not np.isfinite(facing).all():
        raise ValueError(f"source_facing must be a finite 3-vector, got {facing.shape}")
    if abs(float(facing[1])) > 1e-5:
        raise ValueError("source_facing must be a Y-up ground-plane direction")
    norm = float(np.linalg.norm(facing[[0, 2]]))
    if norm <= 1e-6:
        raise ValueError("source_facing is degenerate")
    source = facing[[0, 2]] / norm
    target = MODEL_FORWARD[[0, 2]]
    delta = float(np.arctan2(target[1], target[0]) - np.arctan2(source[1], source[0]))
    cosine = float(np.cos(delta))
    sine = float(np.sin(delta))
    # C maps a column source vector to a column model vector.  For a row-wise
    # position stack, use positions @ C.T (kept explicit at each call site).
    matrix = np.asarray(
        ((cosine, 0.0, -sine), (0.0, 1.0, 0.0), (sine, 0.0, cosine)),
        dtype=np.float64,
    )
    if not np.allclose(matrix @ matrix.T, np.eye(3), atol=1e-6, rtol=0.0):
        raise ValueError("source_to_model rotation is not orthonormal")
    if float(np.linalg.det(matrix)) <= 0.0:
        raise ValueError("source_to_model rotation must preserve handedness")
    return matrix


def maxabs_global_scale(root_relative_model: np.ndarray) -> float:
    """Vendor-compatible scale: maximum absolute coordinate after facing."""
    values = np.asarray(root_relative_model, dtype=np.float64)
    if values.ndim != 2 or values.shape[1] != 3 or not np.isfinite(values).all():
        raise ValueError(f"root_relative_model must be finite [J,3], got {values.shape}")
    return float(np.max(np.abs(values)))


def adapt_bind_geometry(
    rest_world: np.ndarray,
    parents: np.ndarray,
    *,
    source_facing: np.ndarray | list[float] | tuple[float, ...] | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, float]:
    """Canonicalize bind positions without changing the source skeleton.

    Returns ``(source_to_model, model_to_source, model_root_relative,
    normalized_offsets, global_scale)``.  Offsets are world parent-child
    deltas in model space and the root offset is always zero.
    """
    source = np.asarray(rest_world, dtype=np.float64)
    parent = np.asarray(parents, dtype=np.int64).reshape(-1)
    if source.ndim != 2 or source.shape != (parent.size, 3) or not np.isfinite(source).all():
        raise ValueError(f"rest_world must be finite [J,3] matching parents, got {source.shape}")
    if parent.size == 0 or int(parent[0]) >= 0:
        raise ValueError("bind skeleton must have a root at joint 0")
    if np.any((parent < -1) | (parent >= parent.size)):
        raise ValueError("parents contain an out-of-range index")
    if np.any(parent[1:] >= np.arange(1, parent.size)):
        raise ValueError("parents must precede children in bind joint order")
    source_to_model = source_to_model_matrix(source_facing)
    model_to_source = source_to_model.T
    model_root_relative = (source - source[0:1]) @ source_to_model.T
    scale = maxabs_global_scale(model_root_relative)
    if not np.isfinite(scale) or scale <= 1e-6:
        raise ValueError(f"bind skeleton global_scale is degenerate: {scale}")
    offsets = local_offsets(model_root_relative, parent) / scale
    offsets[0] = 0.0
    return (
        source_to_model,
        model_to_source,
        model_root_relative.astype(np.float32),
        offsets.astype(np.float32),
        scale,
    )


def _vendor_on_path() -> None:
    vendor = str(VENDOR)
    if vendor not in sys.path:
        sys.path.insert(0, vendor)


def graph_from_parents(parents: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    _vendor_on_path()
    from preprocess.build_species_info import create_topology_edge_relations

    edge, hop = create_topology_edge_relations(parents, max_path_len=5)
    hop = np.clip(hop, 0, 5)
    return hop.astype(np.int64), edge.astype(np.int64)


def encode_t5_names(names: list[str]) -> np.ndarray:
    _vendor_on_path()
    from preprocess.build_species_info import make_t5_encoder

    CACHE.mkdir(parents=True, exist_ok=True)
    cache_path = CACHE / "t5_joint_name_cache.json"
    cache: dict[str, list[float]] = {}
    if cache_path.is_file():
        cache = json.loads(cache_path.read_text(encoding="utf-8"))
    missing = [name for name in names if name not in cache]
    if missing:
        embed = make_t5_encoder(device="cpu")
        vectors = embed(missing)
        for name, vector in zip(missing, vectors):
            cache[name] = [float(value) for value in np.asarray(vector).reshape(-1)]
        cache_path.write_text(json.dumps(cache), encoding="utf-8")
    stacked = np.stack([np.asarray(cache[name], dtype=np.float32) for name in names], axis=0)
    if stacked.shape[1] != 768:
        raise ValueError(f"T5 embedding width {stacked.shape[1]} != 768")
    return stacked


def role_map_from_bone_roles(path: Path | None) -> dict[str, str] | None:
    if path is None:
        return None
    payload = json.loads(require_file(path, label="bone roles").read_text(encoding="utf-8"))
    joints = payload.get("joints") or {}
    return {str(bone): str(role) for role, bone in joints.items()}


def build_reference(
    unit: str,
    mesh_glb: Path,
    camera_json: Path | None,
    out_dir: Path,
    *,
    bone_roles_path: Path | None = None,
    joint_names_path: Path | None = None,
    source_facing: np.ndarray | list[float] | tuple[float, ...] | None = None,
    memory_recipe_path: Path | None = None,
) -> dict[str, Path]:
    skeleton = load_bind_skeleton(mesh_glb)
    raw_names = list(skeleton.names)
    if joint_names_path is not None and bone_roles_path is not None:
        raise ValueError("choose one joint-name authority, not aliases plus legacy roles")
    readable = (
        semantic_joint_names(joint_names_path, mesh_glb, raw_names)
        if joint_names_path is not None
        else readable_joint_names(raw_names, role_by_bone=role_map_from_bone_roles(bone_roles_path))
    )
    parents = np.asarray(skeleton.parents, dtype=np.int64)
    rest_world = np.asarray(skeleton.rest_world, dtype=np.float32)
    (
        source_to_model,
        model_to_source,
        root_relative,
        offset,
        global_scale,
    ) = adapt_bind_geometry(rest_world, parents, source_facing=source_facing)
    ref_position = (root_relative / global_scale).astype(np.float32)
    # Vendor BVH rest is identity local rotation plus parent-relative offsets.
    # GLB rest local matrices stay in rest_local_rotation for later mesh apply.
    ref_rot6d = identity_rot6d(len(raw_names))
    hop, edge = graph_from_parents(parents)
    t5 = encode_t5_names(readable)
    joint_count = len(raw_names)
    joint_mask = np.zeros((MAX_JOINTS,), dtype=np.bool_)
    joint_mask[:joint_count] = True
    static_pos = np.zeros((MAX_JOINTS,), dtype=np.bool_)
    static_pos[0] = True
    static_rot = np.zeros((MAX_JOINTS,), dtype=np.bool_)
    camera: Mapping[str, Any] | None = None
    if camera_json is not None:
        camera = json.loads(require_file(camera_json, label="camera json").read_text(encoding="utf-8"))
    memory_ids = ["rest"]
    if memory_recipe_path is None:
        memory_pose = pad_joints(ref_position, fill=0.0)[None, ...]
        memory_rot6d = pad_joints(ref_rot6d, fill=0.0)[None, ...]
        memory_policy = "singleton_bind_reference"
    else:
        if joint_names_path is None:
            raise ValueError("kinematic memory requires semantic joint names")
        names_payload = json.loads(require_file(joint_names_path, label="joint names").read_text(encoding="utf-8"))
        recipe = load_memory_recipe(memory_recipe_path)
        memory_pose, memory_rot6d, memory_ids = build_kinematic_memory(
            readable_names=readable,
            offsets=offset,
            parents=parents,
            recipe=recipe,
            names_mesh_sha256=str(names_payload.get("meshSha256", "")),
        )
        rest_err = float(np.max(np.abs(memory_pose[0, :joint_count] - ref_position)))
        if rest_err > 1e-5:
            raise ValueError(f"memory rest does not match bind reference ({rest_err})")
        memory_policy = "kinematic_range_prior"

    out_dir.mkdir(parents=True, exist_ok=True)
    npz_path = out_dir / "reference.npz"
    np.savez(
        npz_path,
        ref_position=pad_joints(ref_position, fill=0.0),
        ref_rot6d=pad_joints(ref_rot6d, fill=0.0),
        offset=pad_joints(offset, fill=0.0),
        parents=pad_joints(parents, fill=-1),
        joint_mask=joint_mask,
        ancestor_mask=ancestor_mask(parents, joint_count),
        graph_hop=pad_square(hop, fill=5),
        graph_edge=pad_square(edge, fill=4),
        joint_t5embed=pad_joints(t5, fill=0.0),
        static_pos_joint_mask=static_pos,
        static_rot_joint_mask=static_rot,
        memory_pose=memory_pose,
        memory_rot6d=memory_rot6d,
        global_scale=np.asarray([global_scale], dtype=np.float32),
        J_valid=np.asarray([joint_count], dtype=np.int32),
        rest_world=rest_world,
        rest_local_rotation=np.asarray(skeleton.rest_local_rotation, dtype=np.float32),
        rest_local_translation=np.asarray(skeleton.rest_local_translation, dtype=np.float32),
        node_indices=np.asarray(skeleton.node_indices, dtype=np.int32),
        names=np.asarray(raw_names),
        readable_names=np.asarray(readable),
        source_to_model=source_to_model.astype(np.float32),
        model_to_source=model_to_source.astype(np.float32),
    )
    rig = {
        "unit": unit,
        "meshGlb": str(mesh_glb).replace("\\", "/"),
        "jointCount": joint_count,
        "names": raw_names,
        "readableNames": readable,
        "parents": [int(value) for value in parents],
        "nodeIndices": [int(value) for value in skeleton.node_indices],
        "globalScale": global_scale,
        "sourceFacing": None if source_facing is None else [float(value) for value in np.asarray(source_facing)],
        "modelFacing": MODEL_FORWARD.astype(float).tolist(),
        "sourceToModel": source_to_model.astype(float).tolist(),
        "modelToSource": model_to_source.astype(float).tolist(),
        "coordinatePolicy": "source_glb_y_up_to_vendor_y_up_plus_z",
        "scalePolicy": "max_abs_root_relative_after_source_to_model",
        "offsetPolicy": "world_parent_child_delta_in_model_space_root_zero",
        "staticPosPolicy": "root_equals_reference_evaluate_root_relative",
        "staticRotPolicy": "none",
        "restRotPolicy": "vendor_identity_bvh",
        "memoryPolicy": memory_policy,
        "memoryPoseIds": memory_ids,
        "memoryCount": int(memory_pose.shape[0]),
        "jointNamesSource": str(joint_names_path) if joint_names_path is not None else "ordinal_or_legacy_roles",
        "camera": camera,
        "keepAuthority": "mocap_v2_temporal_proposal",
        "proof": "generated-artifact",
        "deletedBones": False,
        "fbxConverted": False,
    }
    rig_path = out_dir / "rig.json"
    rig_path.write_text(json.dumps(rig, indent=2) + "\n", encoding="utf-8")
    return {"reference": npz_path, "rig": rig_path}


def pad_square(values: np.ndarray, *, fill: int) -> np.ndarray:
    out = np.full((MAX_JOINTS, MAX_JOINTS), fill, dtype=values.dtype)
    count = values.shape[0]
    out[:count, :count] = values
    return out


def load_reference(path: Path) -> dict[str, np.ndarray]:
    payload = np.load(require_file(path, label="reference npz"), allow_pickle=False)
    missing = [key for key in REQUIRED_NPZ if key not in payload.files]
    if missing:
        raise KeyError(f"{path} is missing required fields: {missing}")
    return {key: payload[key] for key in payload.files}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--unit", required=True)
    parser.add_argument("--mesh", required=True, type=Path)
    parser.add_argument("--camera", type=Path)
    parser.add_argument("--bone-roles", type=Path)
    parser.add_argument("--out", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    out_dir = args.out or (DATA / str(args.unit))
    written = build_reference(
        str(args.unit),
        Path(args.mesh),
        args.camera,
        out_dir,
        bone_roles_path=args.bone_roles,
    )
    print(json.dumps({key: str(path).replace("\\", "/") for key, path in written.items()}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
