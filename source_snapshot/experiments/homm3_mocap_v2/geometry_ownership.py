"""Source-pinned physical ownership with replayable, rest-preserving seams."""
import hashlib
import json
from pathlib import Path

import numpy as np

from attachment_repair import split_attachment

SCHEMA = "homm3-source-geometry-ownership-v1"
ROOT = Path(__file__).resolve().parents[2]


def _object(value, label, *, keys=None):
    if not isinstance(value, dict) or (keys is not None and set(value) != set(keys)):
        raise ValueError(f"{label} requires an object" + (f" with exactly {sorted(keys)}" if keys else ""))
    return value


def _text(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} requires a nonempty string")
    return value


def load_ownership(profile):
    _object(profile, "profile")
    reference = _object(profile.get("geometryOwnership"), "geometryOwnership", keys={"path", "sha256"})
    path = (ROOT / _text(reference["path"], "geometry ownership path")).resolve()
    _text(reference["sha256"], "geometry ownership sha256")
    if not path.is_relative_to(ROOT):
        raise ValueError("geometry ownership path escapes workspace")
    payload = path.read_bytes()
    if hashlib.sha256(payload).hexdigest() != reference["sha256"]:
        raise ValueError("geometry ownership sidecar hash mismatch; regenerate upstream artifacts")
    from structured_profiles import _unique_object
    data = json.loads(payload, object_pairs_hook=_unique_object)
    optional = {"bodyWeightOverrides"} if isinstance(data, dict) and "bodyWeightOverrides" in data else set()
    _object(data, "geometry ownership sidecar", keys={"schema", "sourceMeshSha256", "sourceVertexCount",
        "sourceFaceCount", "rigidParts", "bodyVertexRegions", "maxBoundaryGap", "boundaryGapUnits",
        "authorship", "boundaryGapEvidence"} | optional)
    if data.get("schema") != SCHEMA or data.get("sourceMeshSha256") != profile.get("expectedMeshSha256"):
        raise ValueError("geometry ownership schema or source hash mismatch")
    for key in ("sourceVertexCount", "sourceFaceCount"):
        if type(data[key]) is not int or data[key] <= 0:
            raise ValueError(f"geometry ownership {key} requires a positive integer")
    if not isinstance(data["rigidParts"], list) or not data["rigidParts"]:
        raise ValueError("geometry ownership requires nonempty rigidParts")
    for part in data["rigidParts"]:
        _object(part, "rigid part", keys={"region", "owner", "faceIds", "interfaceMode"})
        _text(part["region"], "rigid part region")
        _text(part["owner"], "rigid part owner")
        if part["interfaceMode"] not in ("split_shared", "source_detached"):
            raise ValueError("rigid part interfaceMode must be split_shared or source_detached")
        if not len(_ids(part["faceIds"], data["sourceFaceCount"], "rigid face mask")):
            raise ValueError("rigid face masks must be nonempty")
    for region, values in _object(data["bodyVertexRegions"], "bodyVertexRegions").items():
        _text(region, "body region")
        _ids(values, data["sourceVertexCount"], "body vertex mask")
    body_weight_overrides(data, profile)
    tolerance = data.get("maxBoundaryGap")
    if type(tolerance) not in (float, int) or not np.isfinite(tolerance) or tolerance < 0:
        raise ValueError("geometry ownership requires explicit finite nonnegative maxBoundaryGap")
    if data.get("boundaryGapUnits") != "source_mesh_units":
        raise ValueError("geometry ownership boundary tolerance requires source_mesh_units")
    authorship = _object(data["authorship"], "geometry ownership authorship")
    if authorship.get("status") != "reviewed_source_geometry":
        raise ValueError("geometry ownership is not source-geometry reviewed; draft cannot prepare")
    evidence = _object(data["boundaryGapEvidence"], "boundaryGapEvidence", keys={"cameraPath", "cameraSha256",
        "worldUnitsPerPixel", "pixelLimit", "acceptance"})
    camera_path = (ROOT / _text(evidence["cameraPath"], "boundary camera path")).resolve()
    _text(evidence["cameraSha256"], "boundary camera sha256")
    if not camera_path.is_relative_to(ROOT):
        raise ValueError("boundary camera escapes workspace")
    camera_bytes = camera_path.read_bytes()
    if hashlib.sha256(camera_bytes).hexdigest() != evidence["cameraSha256"]:
        raise ValueError("boundary tolerance camera hash mismatch")
    camera = _object(json.loads(camera_bytes, object_pairs_hook=_unique_object), "boundary camera")
    scale = camera.get("pxPerWorld")
    pixels = evidence.get("pixelLimit")
    if type(scale) not in (int, float) or not np.isfinite(scale) or scale <= 0:
        raise ValueError("boundary camera requires finite positive pxPerWorld")
    if type(pixels) not in (int, float) or not np.isfinite(pixels) or not 0 <= pixels <= 1:
        raise ValueError("provisional boundary tolerance must not exceed one rendered pixel")
    if evidence.get("acceptance") != "provisional_unaccepted":
        raise ValueError("boundary tolerance must retain provisional unaccepted status")
    conversion = evidence["worldUnitsPerPixel"]
    if type(conversion) not in (int, float) or not np.isfinite(conversion) or not np.isclose(conversion, 1 / scale, rtol=1e-12, atol=0):
        raise ValueError("boundary camera pixel conversion mismatch")
    if not np.isclose(tolerance, pixels / scale, rtol=1e-12, atol=0):
        raise ValueError("boundary tolerance differs from pinned camera conversion")
    return data


def _ids(values, count, label):
    if not isinstance(values, list) or any(type(value) is not int for value in values):
        raise ValueError(f"{label} must be integer IDs")
    if len(set(values)) != len(values) or any(value < 0 or value >= count for value in values):
        raise ValueError(f"{label} contains duplicate or out-of-range IDs")
    return np.asarray(values, dtype=np.int64)


def body_weight_overrides(data, profile):
    """Validate explicit source-body authoring; never infer unsupported weights."""
    if "bodyWeightOverrides" not in data:
        return {}
    rows = data["bodyWeightOverrides"]
    if not isinstance(rows, list):
        raise ValueError("bodyWeightOverrides requires a list")
    result = {}
    for row in rows:
        _object(row, "body weight override", keys={"sourceVertexId", "weights", "rationale"})
        vertex = int(_ids([row["sourceVertexId"]], data["sourceVertexCount"], "body override source vertex")[0])
        if vertex in result:
            raise ValueError("body weight overrides repeat a source vertex")
        _text(row["rationale"], "body weight override rationale")
        regions = [region for region, ids in data["bodyVertexRegions"].items() if vertex in ids]
        if len(regions) != 1 or regions[0] not in profile.get("regionJoints", {}):
            raise ValueError("body weight override must name exactly one declared body-complement vertex")
        region = regions[0]
        if region in {part["region"] for part in data["rigidParts"]}:
            raise ValueError("body weight override cannot name a rigid region")
        weights = _object(row["weights"], "body override weights")
        if not weights or any(not isinstance(name, str) or name not in profile["regionJoints"][region] for name in weights):
            raise ValueError("body override donors must belong to the declared anatomical region")
        if any(type(value) not in (float, int) or not np.isfinite(value) or value < 0 for value in weights.values()):
            raise ValueError("body override weights must be finite nonnegative numbers")
        if not np.isclose(sum(weights.values()), 1., rtol=0, atol=1e-8):
            raise ValueError("body override weights must be explicitly normalized")
        result[vertex] = {"region": region, "weights": weights}
    return result


def validate_boundary_pairs(source_ids, pairs, original_count):
    """Prove every appended vertex has exactly its source-corresponding split pair."""
    source_ids, pairs = np.asarray(source_ids), np.asarray(pairs)
    if (source_ids.ndim != 1 or not np.issubdtype(source_ids.dtype, np.integer) or
            len(source_ids) < original_count or np.any(source_ids < 0) or np.any(source_ids >= original_count) or
            not np.array_equal(source_ids[:original_count], np.arange(original_count))):
        raise ValueError("ownership sourceVertexIds must contain the complete original-to-prepared mapping")
    if (pairs.ndim != 2 or pairs.shape[1] != 2 or not np.issubdtype(pairs.dtype, np.integer) or
            np.any(pairs < 0) or np.any(pairs >= len(source_ids)) or
            len({tuple(pair) for pair in pairs.tolist()}) != len(pairs) or
            np.any(pairs[:, 0] >= pairs[:, 1]) or
            not np.array_equal(np.sort(pairs[:, 1]), np.arange(original_count, len(source_ids))) or
            not np.array_equal(source_ids[pairs[:, 0]], source_ids[pairs[:, 1]])):
        raise ValueError("ownership boundary pairs must uniquely cover every duplicate with its exact source correspondence")


def apply_ownership(target, profile):
    """Replay authored face ownership on original arrays, never on a prior split."""
    data = load_ownership(profile)
    vertices, triangles = target["vertices"], target["triangles"]
    if data.get("sourceVertexCount") != len(vertices) or data.get("sourceFaceCount") != len(triangles):
        raise ValueError("geometry ownership source counts mismatch")
    parts = data.get("rigidParts")
    if not isinstance(parts, list) or not parts:
        raise ValueError("geometry ownership requires nonempty rigidParts")
    attachments = {entry["region"]: entry["donorJoints"] for entry in profile["rigidAttachments"]}
    face_used = set()
    regions_used = set()
    interfaces = []
    for part in parts:
        _object(part, "rigid part", keys={"region", "owner", "faceIds", "interfaceMode"})
        region = _text(part["region"], "rigid part region")
        _text(part["owner"], "rigid part owner")
        if part["interfaceMode"] not in ("split_shared", "source_detached"):
            raise ValueError("rigid part interfaceMode must be split_shared or source_detached")
        if region in regions_used or attachments.get(region) != [part["owner"]]:
            raise ValueError("rigid part region must be unique and match its declared attachment owner")
        regions_used.add(region)
        ids = _ids(part["faceIds"], len(triangles), "rigid face mask")
        if not len(ids) or face_used.intersection(ids.tolist()):
            raise ValueError("rigid face masks must be nonempty and disjoint")
        face_used.update(ids.tolist())
        complement = sorted(set(range(len(triangles))) - set(ids.tolist()))
        shared = set(triangles[ids].ravel().tolist()) & set(triangles[complement].ravel().tolist())
        if bool(shared) != (part["interfaceMode"] == "split_shared"):
            raise ValueError(f"{region}: interfaceMode does not match original source shared vertices")
        interfaces.append({"region": region, "interfaceMode": part["interfaceMode"],
                           "sharedSourceVertexIds": sorted(shared)})
    body_faces = sorted(set(range(len(triangles))) - face_used)
    required_body = set(triangles[body_faces].ravel().tolist())
    body = data.get("bodyVertexRegions")
    if not isinstance(body, dict):
        raise ValueError("geometry ownership requires explicit bodyVertexRegions")
    labels = np.full(len(vertices), "", dtype=object)
    assigned = set()
    for region, values in body.items():
        if region not in profile["regionJoints"] or region in attachments:
            raise ValueError("body region must be a non-rigid anatomical region")
        ids = _ids(values, len(vertices), "body vertex mask")
        if assigned.intersection(ids.tolist()):
            raise ValueError("body vertex masks overlap")
        assigned.update(ids.tolist())
        labels[ids] = region
    if assigned != required_body:
        raise ValueError("body vertex masks must exactly cover complement-face vertices")
    for part in parts:
        for vertex in np.unique(triangles[part["faceIds"]]):
            if int(vertex) not in assigned:
                labels[vertex] = part["region"]
    if any(not label for label in labels):
        raise ValueError("source contains vertices without explicit ownership")
    # The existing splitter needs normalized weights; actual donor weights are
    # initialized later. This single column is topology-only, never exported.
    skin = {"vertices": vertices, "triangles": triangles, "uvs": target["uvs"],
            "regions": labels, "weights": np.ones((len(vertices), 1)), "names": np.asarray(["owner"])}
    source_ids = np.arange(len(vertices), dtype=np.int64)
    pairs = []
    for part in parts:
        skin, report = split_attachment(skin, part["faceIds"], "owner")
        source_ids = source_ids[np.asarray(report["sourceVertexIds"])]
        pairs.extend(report["boundaryPairs"])
        skin["regions"] = skin["regions"].astype(object)
        skin["regions"][np.unique(skin["triangles"][part["faceIds"]])] = part["region"]
    if not np.array_equal(source_ids[skin["triangles"]], triangles):
        raise ValueError("ownership split changed source face order or topology mapping")
    if not np.array_equal(skin["vertices"][skin["triangles"]], vertices[triangles]):
        raise ValueError("ownership split changed source position corners")
    if not np.array_equal(skin["uvs"][skin["triangles"]], target["uvs"][triangles]):
        raise ValueError("ownership split changed source UV corners")
    result = dict(target)
    pair_array = np.asarray(pairs, dtype=np.int64).reshape(-1, 2)
    validate_boundary_pairs(source_ids, pair_array, len(vertices))
    for interface in interfaces:
        related = [index for index, (left, right) in enumerate(pairs)
                   if skin["regions"][left] == interface["region"] or skin["regions"][right] == interface["region"]]
        represented = {int(source_ids[pairs[index][0]]) for index in related}
        if represented != set(interface["sharedSourceVertexIds"]):
            raise ValueError("replayed boundary pairs do not cover the complete original part interface")
        interface["boundaryPairIndices"] = related
        interface["boundaryStatus"] = "split_gap_requires_evaluation" if related else "not_applicable_source_detached"
        interface["contactProven"] = False
    result.update(vertices=skin["vertices"], triangles=skin["triangles"], uvs=skin["uvs"],
                  vertexRegions=skin["regions"], sourceDenseWeights=target["sourceDenseWeights"][source_ids],
                  sourceVertexIds=source_ids, ownershipBoundaryPairs=pair_array,
                  topologyPreserved=False, visibleMeshUnchanged=True)
    if target.get("normals") is not None:
        result["normals"] = target["normals"][source_ids]
    result["geometryOwnershipReport"] = {"sidecarSha256": profile["geometryOwnership"]["sha256"],
        "sourceVertexCount": len(vertices), "preparedVertexCount": len(source_ids),
        "sourceFaceCount": len(triangles), "boundaryPairCount": len(pairs),
        "sourceCornerPositionsAndUvsExact": True, "sourceFaceOrderAndCountExact": True,
        "animatedContactProven": False, "interfaces": interfaces}
    return result


def validate_prepared_ownership(profile, skin):
    """Consumer proof: replay from original GLB and compare all ownership data."""
    from target_asset import load_target_asset
    target = load_target_asset(profile)
    for key, target_key in (("vertices", "vertices"), ("triangles", "triangles"), ("uvs", "uvs"),
                            ("regions", "vertexRegions"), ("sourceVertexIds", "sourceVertexIds"),
                            ("ownershipBoundaryPairs", "ownershipBoundaryPairs"), ("albedo", "albedo")):
        if key not in skin or not np.array_equal(skin[key], target[target_key]):
            raise ValueError(f"prepared geometry ownership replay mismatch: {key}")
    from source_skin_initialization import initialize_source_weights
    expected = initialize_source_weights(target["sourceDenseWeights"], target["names"], skin["names"],
                                         target["vertexRegions"], profile, source_vertex_ids=target["sourceVertexIds"])["weights"]
    if not np.array_equal(skin["weights"], expected):
        raise ValueError("prepared geometry ownership initial weights changed")


def animated_boundary_gate(profile, skin, animated, *, expected_frame_count):
    """Evaluate every source-replayed split pair, not a submitted subset."""
    from target_asset import load_target_asset
    from attachment_repair import boundary_gaps
    target = load_target_asset(profile)
    animated = np.asarray(animated)
    if (type(expected_frame_count) is not int or expected_frame_count <= 0 or
            animated.shape != (expected_frame_count, len(target["vertices"]), 3) or
            not np.isfinite(animated).all()):
        raise ValueError("ownership animation must contain every expected finite [F,V,3] frame")
    pairs = target["ownershipBoundaryPairs"]
    validate_boundary_pairs(target["sourceVertexIds"], pairs, target["geometryOwnershipReport"]["sourceVertexCount"])
    if not np.array_equal(skin.get("ownershipBoundaryPairs"), pairs):
        raise ValueError("animated ownership boundary pairs differ from complete source replay")
    report = boundary_gaps(animated, pairs)
    tolerance = load_ownership(profile)["maxBoundaryGap"]
    report.update(maxBoundaryGap=tolerance, passed=report["maxDistance"] <= tolerance,
                  acceptance="explicit authored source-unit tolerance" if len(pairs) else "not_applicable_source_detached",
                  frameCount=expected_frame_count, boundaryApplicable=bool(len(pairs)), contactProven=False,
                  interfaces=target["geometryOwnershipReport"]["interfaces"])
    return report
