"""Detach a seeded thin prop from a welded surface and attach it as a rigid object.

This is a local, configured surface cut, not whole-character segmentation. Seeds name the
prop's thin stock/limbs; an explicit envelope pins the surrounding body. A minimum surface
cut finds their connecting necks. Triangles are retained, boundary render vertices are
duplicated, and the existing UVs and normals travel with their original textured geometry.
"""
from __future__ import annotations

import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import breadth_first_order, connected_components, maximum_flow


def _points(value, name):
    result = np.asarray(value, dtype=float)
    if result.shape != (3,) or not np.isfinite(result).all():
        raise ValueError(f"{name} must contain three finite coordinates")
    return result


def _frame(forward, up):
    forward = _points(forward, "forward")
    up = _points(up, "up")
    length = np.linalg.norm(forward)
    if length < 1e-10:
        raise ValueError("forward must be nonzero")
    forward /= length
    up -= forward * np.dot(up, forward)
    length = np.linalg.norm(up)
    if length < 1e-10:
        raise ValueError("up must not be parallel to forward")
    up /= length
    return np.column_stack((forward, up, np.cross(forward, up)))


def _seed_mask(points, seeds):
    selected = np.zeros(len(points), dtype=bool)
    for seed in seeds:
        a = _points(seed["a"], "seed.a")
        b = _points(seed.get("b", seed["a"]), "seed.b")
        radius = float(seed["radius"])
        if not np.isfinite(radius) or radius <= 0:
            raise ValueError("seed radius must be positive")
        ab = b - a
        t = np.clip((points - a) @ ab / max(float(ab @ ab), 1e-20), 0, 1)
        selected |= np.linalg.norm(points - a - t[:, None] * ab, axis=1) <= radius
    return selected


def extract_prop_faces(positions, indices, region):
    """Return original face IDs selected by a seeded cut on the welded surface graph.

    All distances are in source mesh coordinates. The envelope is deliberately explicit:
    a local prop repair must not silently become a global anatomy classification problem.
    """
    positions = np.asarray(positions, dtype=float)
    faces = np.asarray(indices, dtype=np.int64).reshape(-1, 3)
    if positions.ndim != 2 or positions.shape[1] != 3 or not np.isfinite(positions).all():
        raise ValueError("positions must be finite 3D points")
    if not len(faces) or faces.min() < 0 or faces.max() >= len(positions):
        raise ValueError("indices must name source vertices")
    tolerance = float(region.get("weldTolerance", 1e-5))
    if tolerance <= 0 or not np.isfinite(tolerance):
        raise ValueError("weldTolerance must be positive")
    _, first, inverse = np.unique(np.rint(positions / tolerance).astype(np.int64),
                                  axis=0, return_index=True, return_inverse=True)
    points = positions[first]
    welded_faces = inverse[faces]
    edges = np.concatenate((welded_faces[:, [0, 1]], welded_faces[:, [1, 2]],
                            welded_faces[:, [2, 0]]))
    edges = np.unique(np.sort(edges, axis=1), axis=0)
    edges = edges[edges[:, 0] != edges[:, 1]]
    low = _points(region["bounds"][0], "bounds minimum")
    high = _points(region["bounds"][1], "bounds maximum")
    if np.any(high <= low):
        raise ValueError("region bounds must have positive extent")
    foreground = _seed_mask(points, region["seeds"])
    background = np.any((points < low) | (points > high), axis=1)
    background |= _seed_mask(points, region.get("bodySeeds", []))
    if np.any(foreground & background):
        raise ValueError("prop and body seeds overlap; widen envelope or correct seeds")
    if not foreground.any() or not background.any():
        raise ValueError("the region must seed both prop and body vertices")
    n = len(points)
    a, b = edges.T
    # Edge length approximates cut perimeter. Integer capacities keep scipy's sparse
    # max-flow deterministic; hard seed capacity exceeds the sum of all soft edges.
    lengths = np.linalg.norm(points[a] - points[b], axis=1)
    quantum = max(tolerance, float(4 * lengths.sum() / 1_000_000_000))
    capacity = np.maximum(1, np.rint(lengths / quantum).astype(np.int64))
    hard = int(2 * capacity.sum() + 1)
    rows = np.r_[a, b, np.full(foreground.sum(), n), np.flatnonzero(background)]
    cols = np.r_[b, a, np.flatnonzero(foreground), np.full(background.sum(), n + 1)]
    values = np.r_[capacity, capacity, np.full(foreground.sum() + background.sum(), hard)]
    graph = coo_matrix((values, (rows, cols)), shape=(n + 2, n + 2)).tocsr()
    flow = maximum_flow(graph, n, n + 1)
    residual = graph - flow.flow
    residual.data[residual.data <= 0] = 0
    residual.eliminate_zeros()
    reachable = breadth_first_order(residual, n, directed=True, return_predecessors=False)
    selected = np.zeros(n + 2, dtype=bool)
    selected[reachable] = True
    face_mask = selected[welded_faces].sum(axis=1) >= 2
    ids = np.flatnonzero(face_mask)
    if not len(ids) or face_mask.all():
        raise ValueError("prop cut must leave nonempty prop and body surfaces")
    selected_nodes = np.unique(welded_faces[face_mask])
    selected_faces = welded_faces[face_mask]
    prop_edges = np.concatenate((selected_faces[:, [0, 1]], selected_faces[:, [1, 2]],
                                 selected_faces[:, [2, 0]]))
    adj = coo_matrix((np.ones(len(prop_edges)), (prop_edges[:, 0], prop_edges[:, 1])),
                     shape=(n, n)).tocsr()[selected_nodes][:, selected_nodes]
    components = connected_components(adj, directed=False, return_labels=False)
    return ids, {"weldedVertices": n, "seedVertices": int(foreground.sum()),
                 "selectedFaces": len(ids), "selectedNodes": len(selected_nodes),
                 "connectedComponents": int(components),
                 "cutPerimeter": float(flow.flow_value * quantum)}


def extract_prop_vertex_range(positions, indices, vertex_range):
    """Select a complete prop that was composed as a separate source asset.

    A separately generated prop can be UV/seam split so every render triangle
    has private vertices.  A surface graph cut is then the wrong operation: it
    sees thousands of disconnected triangle islands and can silently keep only
    the seeded island.  The composer records the prop's contiguous vertex range
    explicitly, so this route is both faster and stricter than guessing.
    """
    positions = np.asarray(positions, dtype=float)
    faces = np.asarray(indices, dtype=np.int64).reshape(-1, 3)
    if (not isinstance(vertex_range, list) or len(vertex_range) != 2 or
            any(type(value) is not int for value in vertex_range)):
        raise ValueError("sourceVertexRange must contain two integer bounds")
    start, end = vertex_range
    if start < 0 or end <= start or end > len(positions):
        raise ValueError("sourceVertexRange must be inside the source vertex array")
    selected = np.all((faces >= start) & (faces < end), axis=1)
    if not selected.any() or selected.all():
        raise ValueError("sourceVertexRange must select a nonempty prop and retain body faces")
    prop_vertices = np.unique(faces[selected])
    return np.flatnonzero(selected), {
        "mode": "source_vertex_range",
        "sourceVertexRange": [start, end],
        "selectedFaces": int(selected.sum()),
        "selectedNodes": int(len(prop_vertices)),
        "connectedComponents": 1,
        "cutPerimeter": 0.0,
    }


def extract_prop_face_ids(positions, indices, face_ids):
    """Select an explicitly reviewed face set from this exact source mesh."""
    faces = np.asarray(indices, dtype=np.int64).reshape(-1, 3)
    if (not isinstance(face_ids, list) or not face_ids or
            any(type(value) is not int for value in face_ids) or
            any(a >= b for a, b in zip(face_ids, face_ids[1:])) or
            face_ids[0] < 0 or face_ids[-1] >= len(faces)):
        raise ValueError("sourceFaceIds must be nonempty, sorted, unique source face indices")
    if len(face_ids) == len(faces):
        raise ValueError("sourceFaceIds must leave body faces")
    ids = np.asarray(face_ids, dtype=np.int64)
    return ids, {
        "mode": "source_face_ids",
        "selectedFaces": int(len(ids)),
        "selectedNodes": int(len(np.unique(faces[ids]))),
    }


def repair_prop_attachments(*, surface, joints, weights, heads, names, config):
    """Return repaired surface, skin arrays, original-vertex map, and JSON-safe report.

    Run after fitting and skinning the *original* body. ``sourceGrip`` maps exactly to the
    named bone's head plus ``targetOffset``. Prop vertices get weight 1 on that bone.
    ``sourceForward/sourceUp`` and ``targetForward/targetUp`` define a rigid rotation.
    Distinct props must not claim the same source faces. No source triangle is discarded.
    Optional shaftBridges use explicit attached-rest a/b endpoints, radius, sections and
    uvSourceFace (original triangle UV centroid). Generated vertices have source ID -1.
    """
    if config.get("schema") != "prop_attachment.v1":
        raise ValueError("expected prop_attachment.v1 config")
    source_hash = config.get("sourceMeshSha256")
    if not isinstance(source_hash, str) or len(source_hash) != 64:
        raise ValueError("attachment coordinates require a sourceMeshSha256 fingerprint")
    if source_hash.lower() != str(surface.get("sourceSha256", "")).lower():
        raise ValueError("attachment sourceMeshSha256 does not match this mesh; recheck region and grip")
    original = np.asarray(surface["positions"], dtype=float)
    faces = np.asarray(surface["indices"], dtype=np.int64).reshape(-1, 3)
    joints = np.asarray(joints, dtype=np.int64)
    weights = np.asarray(weights, dtype=float)
    if joints.shape != weights.shape or len(joints) != len(original):
        raise ValueError("skin arrays must have one row per source vertex")
    face_owner = np.full(len(faces), -1, dtype=int)
    props, reports = [], []
    for number, prop in enumerate(config["props"]):
        if prop["bone"] not in names:
            raise ValueError(f"unknown attachment bone {prop['bone']}")
        if sum(key in prop for key in ("sourceFaceIds", "sourceVertexRange", "region")) != 1:
            raise ValueError("prop requires exactly one source face selector")
        bone = names.index(prop["bone"])
        if "sourceFaceIds" in prop:
            ids, extraction = extract_prop_face_ids(original, faces, prop["sourceFaceIds"])
        elif "sourceVertexRange" in prop:
            ids, extraction = extract_prop_vertex_range(original, faces, prop["sourceVertexRange"])
        else:
            ids, extraction = extract_prop_faces(original, faces, prop["region"])
        if np.any(face_owner[ids] >= 0):
            raise ValueError("prop regions claim the same faces")
        face_owner[ids] = number
        rotation = _frame(prop["targetForward"], prop["targetUp"]) @ _frame(
            prop["sourceForward"], prop["sourceUp"]).T
        grip = _points(prop["sourceGrip"], "sourceGrip")
        target = np.asarray(heads[bone]) + _points(prop["targetOffset"], "targetOffset")
        props.append((bone, rotation, target - rotation @ grip))
        reports.append({"name": prop["name"], "bone": prop["bone"],
                        "extraction": extraction, "sourceGrip": grip.tolist(),
                        "targetGrip": target.tolist(), "rotation": rotation.tolist()})
    # Each (owner, source render vertex) pair is independent. This duplicates only actual
    # contact vertices while retaining UV seam splits and every triangle's winding.
    corners = np.column_stack((np.repeat(face_owner, 3), faces.reshape(-1)))
    pairs, inverse = np.unique(corners, axis=0, return_inverse=True)
    source_ids, owner = pairs[:, 1], pairs[:, 0]
    result = {key: value for key, value in surface.items()}
    for attribute in ("positions", "normals", "uvs"):
        if surface.get(attribute) is not None:
            result[attribute] = np.asarray(surface[attribute])[source_ids].copy()
    result["indices"] = inverse.reshape(-1)
    new_joints, new_weights = joints[source_ids].copy(), weights[source_ids].copy()
    for number, (bone, rotation, offset) in enumerate(props):
        selected = owner == number
        result["positions"][selected] = original[source_ids[selected]] @ rotation.T + offset
        if result.get("normals") is not None:
            result["normals"][selected] = result["normals"][selected] @ rotation.T
        new_joints[selected] = 0
        new_weights[selected] = 0
        new_joints[selected, 0] = bone
        new_weights[selected, 0] = 1
        reports[number]["renderVertices"] = int(selected.sum())
        source_faces = faces[face_owner == number]
        welded = np.unique(np.round(original[source_faces.reshape(-1)], 5), axis=0)
        reports[number]["sourceBounds"] = [welded.min(axis=0).tolist(),
                                             welded.max(axis=0).tolist()]
    retained_vertices = len(source_ids)
    for number, (bone, _, _) in enumerate(props):
        reports[number].update(generatedVertices=0, generatedFaces=0)
        for bridge in config["props"][number].get("shaftBridges", []):
            import trimesh
            a, b = _points(bridge["a"], "shaftBridge.a"), _points(bridge["b"], "shaftBridge.b")
            radius, sections, face = bridge["radius"], bridge["sections"], bridge["uvSourceFace"]
            length = np.linalg.norm(b - a)
            if not np.isscalar(radius) or isinstance(radius, (bool, str)) or not np.isfinite(radius) or radius <= 0 or not np.isfinite(length) or length <= 1e-10:
                raise ValueError("shaftBridge radius and endpoint distance must be finite and positive")
            if type(sections) is not int or sections < 3 or type(face) is not int or not 0 <= face < len(faces):
                raise ValueError("shaftBridge sections must be an integer >= 3 and uvSourceFace a source face index")
            if result.get("normals") is None or surface.get("uvs") is None:
                raise ValueError("shaftBridge requires source normals and UVs")
            uv = np.asarray(surface["uvs"])[faces[face]]
            if uv.shape != (3, 2) or not np.isfinite(uv).all():
                raise ValueError("shaftBridge uvSourceFace must have finite triangle UVs")
            cylinder = trimesh.creation.cylinder(radius=radius, sections=sections, segment=[a, b])
            count, start = len(cylinder.vertices), len(source_ids)
            if (len(cylinder.faces) != 4 * sections or not np.isfinite(cylinder.vertices).all()
                    or not np.isfinite(cylinder.vertex_normals).all()
                    or np.any(np.linalg.norm(cylinder.vertex_normals, axis=1) == 0)):
                raise ValueError("shaftBridge generated nonfinite or degenerate geometry")
            for key, values in (("positions", cylinder.vertices), ("normals", cylinder.vertex_normals),
                                ("uvs", np.tile(uv.mean(axis=0), (count, 1)))):
                result[key] = np.concatenate((result[key], values))
            result["indices"] = np.r_[result["indices"], (cylinder.faces + start).reshape(-1)]
            extra_joints = np.zeros((count, joints.shape[1]), dtype=new_joints.dtype)
            extra_weights = np.zeros_like(extra_joints, dtype=new_weights.dtype)
            extra_joints[:, 0], extra_weights[:, 0] = bone, 1
            new_joints, new_weights = np.concatenate((new_joints, extra_joints)), np.concatenate((new_weights, extra_weights))
            source_ids, owner = np.r_[source_ids, np.full(count, -1)], np.r_[owner, np.full(count, number)]
            reports[number]["generatedVertices"] += count
            reports[number]["generatedFaces"] += len(cylinder.faces)
            reports[number]["renderVertices"] += count
    report = {"schema": "prop_attachment.v1", "props": reports,
              "sourceMeshSha256": source_hash.lower(),
              "sourceVertices": len(original), "outputVertices": len(source_ids),
              "sourceFaces": len(faces), "outputFaces": len(result["indices"]) // 3,
              "generatedVertices": len(source_ids) - retained_vertices,
              "generatedFaces": len(result["indices"]) // 3 - len(faces),
              "duplicatedContactVertices": retained_vertices - len(np.unique(faces)),
              "preservedTexturedFaces": len(faces)}
    return {"surface": result, "joints": new_joints, "weights": new_weights,
            "sourceVertices": source_ids, "propOwners": owner, "report": report}
