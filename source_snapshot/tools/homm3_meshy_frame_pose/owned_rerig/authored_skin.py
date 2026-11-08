"""Explicit, hash-pinned authored skin transfer; not an aesthetic acceptance gate."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np

from .glb_io import _accessor, read_glb


def _attribute(document, blob, attributes, name, width):
    accessor_id = attributes.get(name)
    accessors = document.get("accessors", [])
    if (not isinstance(accessor_id, int) or isinstance(accessor_id, bool)
            or not 0 <= accessor_id < len(accessors)):
        raise ValueError(f"{name}: missing or invalid accessor index")
    accessor = accessors[accessor_id]
    if "sparse" in accessor or "bufferView" not in accessor:
        raise ValueError(f"{name}: sparse or bufferless accessors are unsupported")
    if accessor.get("type") != f"VEC{width}":
        raise ValueError(f"{name}: expected VEC{width}")
    component = accessor.get("componentType")
    normalized = accessor.get("normalized", False)
    if not isinstance(normalized, bool):
        raise ValueError(f"{name}: normalized must be boolean")
    if name.startswith("JOINTS_"):
        if component not in (5121, 5123) or normalized:
            raise ValueError(f"{name}: requires unnormalized unsigned byte/short indices")
    elif name.startswith("WEIGHTS_"):
        if not ((component == 5126 and not normalized)
                or (component in (5121, 5123) and normalized)):
            raise ValueError(f"{name}: requires float or normalized unsigned byte/short weights")
    elif component != 5126 or normalized:
        raise ValueError(f"{name}: requires unnormalized float positions")
    view_id = accessor["bufferView"]
    views = document.get("bufferViews", [])
    if (not isinstance(view_id, int) or isinstance(view_id, bool)
            or not 0 <= view_id < len(views) or views[view_id].get("buffer", 0) != 0):
        raise ValueError(f"{name}: requires a valid embedded buffer view")
    try:
        values = np.asarray(_accessor(document, blob, accessor_id))
    except (KeyError, IndexError, TypeError, ValueError) as error:
        raise ValueError(f"{name}: invalid accessor data: {error}") from error
    if values.ndim != 2 or values.shape[1] != width:
        raise ValueError(f"{name}: expected an (N,{width}) array")
    if name.startswith("JOINTS_"):
        if values.dtype.kind not in "ui":
            raise ValueError(f"{name}: joint indices must be integers")
        return values.astype(np.int64)
    values = values.astype(np.float64)
    if normalized:
        values /= 255.0 if component == 5121 else 65535.0
    if not np.isfinite(values).all():
        raise ValueError(f"{name}: values must be finite")
    return values


def transfer_authored_skin(
    mesh_path: Path,
    surface_positions: np.ndarray,
    target_names: Sequence[str],
    config: Mapping[str, Any],
) -> dict[str, Any]:
    """Return {joints: uint16 (N,4), weights: float64 (N,4), report: dict}.

    Config requires schema='authored_skin_map.v1', sourceMeshSha256, an explicit
    boneMap from source skin node names to target names, and the literal
    reduction='top4-renormalize'. Every positively weighted source joint must
    be mapped; no ancestor lookup, inferred mapping or position-field recovery.

    Supports one mesh, one primitive and one skin. All contiguous JOINTS_n /
    WEIGHTS_n sets are read, including normalized uint8/uint16 weights. Source
    POSITION must exactly equal surface_positions in source vertex order.
    Duplicate influences are summed by target before reduction; ties keep the
    earlier target_names index. Rows within 1e-5 of unit mass are accepted.
    Dropped mass is reported as a fraction of each original row's total mass.
    Arrays/config are not mutated and no files are written.
    """
    if not isinstance(config, Mapping) or config.get("schema") != "authored_skin_map.v1":
        raise ValueError("config schema must be authored_skin_map.v1")
    if config.get("reduction") != "top4-renormalize":
        raise ValueError("reduction must explicitly be top4-renormalize")
    names = list(target_names)
    if (not names or len(names) > 65536
            or any(not isinstance(name, str) or not name for name in names)
            or len(set(names)) != len(names)):
        raise ValueError("target_names must be nonempty unique names within uint16 index capacity")
    bone_map = config.get("boneMap")
    if not isinstance(bone_map, Mapping):
        raise ValueError("boneMap must be an explicit source-name to target-name mapping")
    packed = read_glb(Path(mesh_path))
    digest = config.get("sourceMeshSha256")
    if not isinstance(digest, str) or digest != packed["sha256"]:
        raise ValueError("sourceMeshSha256 does not exactly match source GLB")
    document, blob = packed["json"], packed["bin"]
    meshes, skins = document.get("meshes", []), document.get("skins", [])
    if len(meshes) != 1 or len(meshes[0].get("primitives", [])) != 1 or len(skins) != 1:
        raise ValueError("authored skin transfer requires exactly one mesh, primitive and skin")
    nodes = document.get("nodes", [])
    skin_nodes = skins[0].get("joints", [])
    if (not skin_nodes or any(not isinstance(node, int) or isinstance(node, bool)
                             or not 0 <= node < len(nodes) for node in skin_nodes)
            or len(set(skin_nodes)) != len(skin_nodes)):
        raise ValueError("skin joints must be unique valid node indices")
    source_names = [nodes[node].get("name") for node in skin_nodes]
    if (any(not isinstance(name, str) or not name for name in source_names)
            or len(set(source_names)) != len(source_names)):
        raise ValueError("source skin node names must be nonempty and unique")
    source_index = {name: index for index, name in enumerate(source_names)}
    target_index = {name: index for index, name in enumerate(names)}
    mapped = np.full(len(source_names), -1, dtype=np.int64)
    for source_name, target_name in bone_map.items():
        if not isinstance(source_name, str) or source_name not in source_index:
            raise ValueError(f"boneMap contains unknown source node: {source_name!r}")
        if not isinstance(target_name, str) or target_name not in target_index:
            raise ValueError(f"boneMap contains unknown target bone: {target_name!r}")
        mapped[source_index[source_name]] = target_index[target_name]
    attributes = meshes[0]["primitives"][0].get("attributes", {})
    positions = _attribute(document, blob, attributes, "POSITION", 3)
    supplied = np.asarray(surface_positions, dtype=np.float64)
    if (not len(positions) or supplied.shape != positions.shape or not np.isfinite(supplied).all()
            or not np.array_equal(supplied, positions)):
        raise ValueError("surface_positions must exactly match source POSITION and vertex order")
    sets = {}
    for prefix in ("JOINTS_", "WEIGHTS_"):
        suffixes = []
        for name in attributes:
            if name.startswith(prefix):
                suffix = name[len(prefix):]
                if not suffix.isascii() or not suffix.isdecimal() or str(int(suffix)) != suffix:
                    raise ValueError(f"invalid influence set name: {name}")
                suffixes.append(int(suffix))
        sets[prefix] = sorted(suffixes)
    indices = sets["JOINTS_"]
    if not indices or indices != sets["WEIGHTS_"] or indices != list(range(len(indices))):
        raise ValueError("JOINTS_n and WEIGHTS_n must be paired contiguous sets starting at zero")
    dense = np.zeros((len(positions), len(names)), dtype=np.float64)
    rows = np.arange(len(positions))[:, None]
    used_source = np.zeros(len(source_names), dtype=bool)
    for index in indices:
        joints = _attribute(document, blob, attributes, f"JOINTS_{index}", 4)
        weights = _attribute(document, blob, attributes, f"WEIGHTS_{index}", 4)
        if joints.shape != (len(positions), 4) or weights.shape != joints.shape:
            raise ValueError(f"influence set {index}: vertex count must match POSITION")
        if np.any(joints < 0) or np.any(joints >= len(source_names)):
            raise ValueError(f"JOINTS_{index}: source skin index out of range")
        if np.any(weights < 0):
            raise ValueError(f"WEIGHTS_{index}: weights must be nonnegative")
        positive = weights > 0
        used_source[joints[positive]] = True
        targets = mapped[joints]
        if np.any(positive & (targets < 0)):
            missing = sorted({source_names[j] for j in joints[positive & (targets < 0)]})
            raise ValueError(f"weighted source nodes missing from boneMap: {missing}")
        # Ignore only zero-mass slots; a positive unmapped influence was rejected above.
        np.add.at(dense, (np.broadcast_to(rows, joints.shape)[positive], targets[positive]), weights[positive])
    totals = dense.sum(axis=1)
    if not np.isfinite(totals).all() or np.any(np.abs(totals - 1.0) > 1e-5):
        raise ValueError("authored weight totals across all sets must equal one within 1e-5")
    dense /= totals[:, None]
    chosen = np.argsort(-dense, axis=1, kind="stable")[:, :4]
    kept = np.take_along_axis(dense, chosen, axis=1)
    kept_mass = kept.sum(axis=1)
    dropped = np.maximum(0.0, 1.0 - kept_mass)
    out_joints = np.zeros((len(positions), 4), dtype=np.uint16)
    out_weights = np.zeros((len(positions), 4), dtype=np.float64)
    out_joints[:, :chosen.shape[1]] = chosen
    out_weights[:, :chosen.shape[1]] = kept / kept_mass[:, None]
    report = {
        "schema": "authored_skin_transfer.v1",
        "sourceMeshSha256": packed["sha256"],
        "boneMap": dict(bone_map),
        "reduction": config["reduction"],
        "targetNames": names,
        "sourceSkinNodeNames": source_names,
        "vertexCount": len(positions),
        "influenceSetCount": len(indices),
        "weightedSourceJointCount": int(used_source.sum()),
        "maxInputUnitTotalError": float(np.max(np.abs(totals - 1.0))),
        "maxDroppedMass": float(dropped.max()),
        "meanDroppedMass": float(dropped.mean()),
        "droppedMassUnits": "fraction_of_source_vertex_total",
        "proof": "explicit authored-weight transfer only; no aesthetic acceptance",
        "accepted": False,
    }
    return {"joints": out_joints, "weights": out_weights, "report": report}
