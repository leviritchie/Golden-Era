"""Source-plate weapon-axis constraints for an explicitly owned leaf hand."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import numpy as np

from .rest_retarget import _swing
from .pose_source import camera_fit_from_payload, yaw_pitch_basis_rows


def load_orientation_evidence(path, master_path, registration_path):
    """Verify exact plate/frame provenance and consume the registered source camera."""
    from PIL import Image

    config = json.loads(Path(path).read_text(encoding="utf-8"))
    if "landmarkEvidence" in config or "landmarkEvidenceSha256" in config:
        evidence, digest = config.get("landmarkEvidence"), config.get("landmarkEvidenceSha256")
        if (not isinstance(evidence, str) or not evidence.strip()
                or not isinstance(digest, str) or len(digest) != 64
                or any(c not in "0123456789abcdef" for c in digest)):
            raise ValueError("declared landmarkEvidence requires a path and SHA256")
        evidence = Path(evidence)
        if not evidence.is_absolute():
            evidence = Path(__file__).resolve().parents[3] / evidence
        if hashlib.sha256(evidence.read_bytes()).hexdigest() != digest:
            raise ValueError("prop orientation landmarkEvidenceSha256 mismatch")
    master_path, registration_path = Path(master_path), Path(registration_path)
    for field, source in (("masterSequenceSha256", master_path), ("registrationSha256", registration_path)):
        if config.get(field) != hashlib.sha256(source.read_bytes()).hexdigest():
            raise ValueError(f"prop orientation {field} mismatch")
    frames = json.loads(master_path.read_text(encoding="utf-8"))["frames"]
    measured = config.get("frames")
    if not frames or not isinstance(measured, list) or len(measured) != len(frames):
        raise ValueError("prop orientation frame count mismatch")
    for number, (source, row) in enumerate(zip(frames, measured)):
        if (row.get("frame") != number or row.get("clipKey") != source["clipKey"]
                or row.get("sourcePng") != source["sourcePng"]
                or row.get("sourceSha256") != source["sourceSha256"]):
            raise ValueError(f"prop orientation frame {number} provenance mismatch")
        plate = Path(source["sourcePng"])
        if hashlib.sha256(plate.read_bytes()).hexdigest() != source["sourceSha256"]:
            raise ValueError(f"prop orientation frame {number} source plate changed")
        with Image.open(plate) as image:
            for key in ("grip", "tip"):
                if key == "grip" and row.get("status") == "occluded-axis-hold" and row.get(key) is None:
                    continue
                point = np.asarray(row[key], dtype=float)
                if (point.shape != (2,) or not np.isfinite(point).all()
                        or np.any(point < 0) or np.any(point >= image.size)):
                    raise ValueError(f"prop orientation frame {number} {key} outside source plate")
    with Image.open(frames[0]["sourcePng"]) as plate:
        registration = json.loads(registration_path.read_text(encoding="utf-8"))
        selected = registration.get("acceptance", {}).get("selectedCandidateId")
        candidates = [c for c in registration.get("views", {}).get("candidates", []) if selected and c.get("id") == selected]
        if registration.get("schema") != "homm3.static-bind-registration.v1" or len(candidates) != 1:
            raise ValueError("prop orientation requires one explicitly selected static registration camera")
        observed = candidates[0]["camera"]
        camera = camera_fit_from_payload({
            "basisScreenRows": yaw_pitch_basis_rows(observed["yawDeg"], observed["pitchDeg"])[:2],
            "pxPerWorld": observed["scale"], "screenOffsetPx": observed["offset"],
            "cameraPolicy": "explicit_selected_static_registration"},
            sprite_size=plate.size, source=str(registration_path), world_frame="y_up_gltf")
    return config, camera


def _clipped_triangle_depth(triangles, lower, upper):
    """Nearest camera depth of triangle surfaces intersecting a screen rectangle.

    Clip in screen XY while linearly carrying depth. This includes enclosing and
    edge-crossing triangles even when no original vertex lies in the rectangle.
    """
    overlaps = np.all((triangles[:, :, :2].max(axis=1) >= lower)
                      & (triangles[:, :, :2].min(axis=1) <= upper), axis=1)
    nearest = None
    for triangle in triangles[overlaps]:
        polygon = list(triangle)
        for axis, bound, sign in ((0, lower[0], 1), (0, upper[0], -1),
                                  (1, lower[1], 1), (1, upper[1], -1)):
            if not polygon:
                break
            clipped = []
            previous = polygon[-1]
            previous_distance = sign * (previous[axis] - bound)
            for current in polygon:
                distance = sign * (current[axis] - bound)
                if (distance >= 0) != (previous_distance >= 0):
                    fraction = previous_distance / (previous_distance - distance)
                    clipped.append(previous + fraction * (current - previous))
                if distance >= 0:
                    clipped.append(current)
                previous, previous_distance = current, distance
            polygon = clipped
        if polygon:
            depth = min(point[2] for point in polygon)
            nearest = float(depth) if nearest is None else min(nearest, float(depth))
    return nearest


def augment_source_prop_motion(motion, heads, parents, names, joints, prop_owners,
                               prop_number, config, source_sha256, camera, positions=None, weights=None,
                               indices=None):
    """Add one rigid prop trajectory, including explicit source-observed release.

    Held poses rotate the leaf hand and prop together. Released poses retain the
    original hand and place the prop's head at its observed plate location on the
    depth plane of the first released head, optionally moved toward the camera
    enough to clear body triangles covering its projected bounds. The visibility
    policy requires post-attachment positions, weights and triangle indices.
    Each contiguous release phase belongs to one explicit clipKey. Depth remains
    an explicit 2.5D assumption, not recovered source depth.
    """
    if config.get("handPolicy") != "rotate-while-held" or config.get("releasePolicy") not in (
            "first-release-depth-plane", "source-visible-front-depth-plane"):
        raise ValueError("explicit hand and release policies required")
    labels = [str(n).rsplit(":", 1)[-1] for n in names]
    driver = labels.index(config["owner"])
    if driver in parents:
        raise ValueError("held hand must be a leaf")
    prop_name = config.get("propBone")
    if not isinstance(prop_name, str) or not prop_name or prop_name in labels:
        raise ValueError("a new explicit propBone name is required")
    modes = [row.get("mode") for row in config["frames"]]
    if any(mode not in ("held", "released") for mode in modes):
        raise ValueError("every prop frame requires held/released mode")
    clips = [row.get("clipKey") for row in config["frames"]]
    if any(not isinstance(clip, str) or not clip.strip() for clip in clips):
        raise ValueError("every prop frame requires an explicit clipKey")
    selected = np.asarray(prop_owners) == prop_number
    if not selected.any() or len(selected) != len(joints):
        raise ValueError("prop vertex ownership missing")
    prop_id = len(labels)
    augmented = deepcopy(motion)
    for key in ("frame_joints", "rotations", "offsets"):
        augmented[key] = np.concatenate((motion[key], motion[key][:, driver:driver + 1]), axis=1)
    augmented["skin_rotation_sources"] = np.r_[motion["skin_rotation_sources"], driver]
    new_heads = np.vstack((heads, heads[driver]))
    new_names = list(names) + [prop_name]
    roots = [j for j, parent in enumerate(parents) if parent is None or parent == -1]
    if len(roots) != 1:
        raise ValueError("one skeleton root required for independent prop trajectory")
    new_parents = list(parents) + [roots[0]]
    core_config = {**config, "owner": prop_name}
    augmented = orient_prop_owner(augmented, new_heads, new_parents, new_names,
                                 core_config, source_sha256, camera.basis_rows)
    depth_bounds = {}
    if config["releasePolicy"] == "source-visible-front-depth-plane":
        positions, weights = np.asarray(positions, dtype=float), np.asarray(weights, dtype=float)
        margin, head_radius = config.get("visibilityMargin"), config.get("headRadius")
        if (positions.shape != (len(joints), 3) or weights.shape != joints.shape
                or not np.isfinite(positions).all() or not np.isfinite(weights).all()
                or not isinstance(margin, (int, float)) or isinstance(margin, bool) or not np.isfinite(margin) or margin <= 0
                or not isinstance(head_radius, (int, float)) or isinstance(head_radius, bool) or not np.isfinite(head_radius) or head_radius <= 0):
            raise ValueError("source-visible release needs geometry, positive margin and measured headRadius")
        faces = np.asarray(indices)
        if (faces.dtype.kind not in "iu" or faces.size == 0
                or not (faces.ndim == 1 and faces.size % 3 == 0 or faces.ndim == 2 and faces.shape[1] == 3)
                or np.any(faces < 0) or np.any(faces >= len(positions))):
            raise ValueError("source-visible release requires valid post-attachment triangle indices")
        faces = faces.reshape(-1, 3)
        prop_corners = selected[faces]
        if np.any(prop_corners.any(axis=1) != prop_corners.all(axis=1)):
            raise ValueError("visibility requires separated prop/body triangles")
        if (np.any(weights < 0) or not np.allclose(weights.sum(axis=1), 1, atol=1e-5, rtol=0)
                or np.asarray(joints).dtype.kind not in "iu" or np.any(joints < 0) or np.any(joints >= prop_id)):
            raise ValueError("visibility requires valid joint indices and normalized nonnegative weights")
        tip = np.asarray(config["axisEnd"], dtype=float)
        head_points = positions[selected & (np.linalg.norm(positions - tip, axis=1) <= head_radius)] - tip
        if len(head_points) < 3:
            raise ValueError("headRadius contains too few prop vertices")
        body_ids = np.flatnonzero(~selected)
        body_lookup = np.full(len(positions), -1, dtype=int)
        body_lookup[body_ids] = np.arange(len(body_ids))
        body_faces = body_lookup[faces[~prop_corners.any(axis=1)]]
        for f, mode in enumerate(modes):
            if mode != "released":
                continue
            body = np.zeros((len(body_ids), 3))
            for slot in range(joints.shape[1]):
                ids = joints[body_ids, slot]
                body += weights[body_ids, slot, None] * (np.einsum("vab,vb->va", motion["rotations"][f, ids], positions[body_ids]) + motion["offsets"][f, ids])
            relative = head_points @ augmented["rotations"][f, prop_id].T
            center_xy = (np.asarray(config["frames"][f]["tip"]) - camera.offset_px) / camera.px_per_world
            head_xy = relative @ camera.basis_rows.T + center_xy
            body_camera = np.column_stack((body @ camera.basis_rows.T, body @ camera.forward))
            nearest = _clipped_triangle_depth(body_camera[body_faces], head_xy.min(axis=0) - margin,
                                              head_xy.max(axis=0) + margin)
            if nearest is not None:
                depth_bounds[f] = float(nearest - (relative @ camera.forward).max() - margin)
    release_depth = None
    for f, mode in enumerate(modes):
        if f == 0 or clips[f] != clips[f - 1]:
            release_depth = None
        if mode == "held":
            augmented["rotations"][f, driver] = augmented["rotations"][f, prop_id]
            augmented["offsets"][f, driver] = augmented["offsets"][f, prop_id]
            release_depth = None
            continue
        rotation = augmented["rotations"][f, prop_id]
        tip = np.asarray(config["axisEnd"], dtype=float)
        old_tip = rotation @ tip + augmented["offsets"][f, prop_id]
        if release_depth is None:
            release_depth = float(old_tip @ camera.forward)
            end = f
            while end < len(modes) and modes[end] == "released" and clips[end] == clips[f]:
                end += 1
            release_depth = min([release_depth] + [depth_bounds[i] for i in range(f, end) if i in depth_bounds])
        xy = (np.asarray(config["frames"][f]["tip"], dtype=float) - camera.offset_px) / camera.px_per_world
        target = camera.basis_rows.T @ xy + camera.forward * release_depth
        augmented["offsets"][f, prop_id] = target - rotation @ tip
        augmented["frame_joints"][f, prop_id] = rotation @ new_heads[prop_id] + augmented["offsets"][f, prop_id]
    new_joints = np.asarray(joints).copy()
    new_joints[selected] = 0
    new_joints[selected, 0] = prop_id
    augmented["propOrientationReport"].update({"hand": config["owner"], "propBone": prop_name,
        "handPolicy": config["handPolicy"], "releasePolicy": config["releasePolicy"],
        "heldFrames": modes.count("held"), "releasedFrames": modes.count("released"),
        "visibilityDepthBounds": depth_bounds,
        "visibilityMethod": ("body-triangle-clipping-to-head-bounds"
                             if config["releasePolicy"] == "source-visible-front-depth-plane" else None),
        "limit": "source projected axis/head position; depth and axial twist assumed, not observed"})
    return augmented, new_heads, new_parents, new_names, new_joints


def orient_prop_owner(motion, heads, parents, names, config, source_sha256, screen_rows):
    """Orient the hand and its rigid prop from measured screen-space shaft directions.

    This resolves the projected axis only. The existing axis depth and axial twist
    are retained, not claimed to be recovered from a single view. Apply after the
    outgoing conversion so no forearm rotation is silently changed. Source hashes
    and frame identities are checked by the caller before invoking this numeric core.
    """
    if config.get("schema") != "prop_orientation.v1":
        raise ValueError("expected prop_orientation.v1")
    if config.get("sourceMeshSha256") != source_sha256:
        raise ValueError("prop orientation source mesh hash mismatch")
    if config.get("policy") != "preserve-depth-minimum-swing":
        raise ValueError("explicit preserve-depth-minimum-swing policy required")
    if "skin_rotation_sources" not in motion or "propOrientationReport" in motion:
        raise ValueError("apply orientation once, after outgoing conversion")
    labels = [str(n).rsplit(":", 1)[-1] for n in names]
    if len(set(labels)) != len(labels) or config.get("owner") not in labels:
        raise ValueError("unique names and explicit known owner required")
    owner = labels.index(config["owner"])
    if owner in parents:
        raise ValueError("prop owner must be a leaf; parent orientation is not supported")
    rest = np.asarray(heads, dtype=float)
    points = np.asarray(motion["frame_joints"], dtype=float)
    rotations = np.asarray(motion["rotations"], dtype=float)
    offsets = np.asarray(motion["offsets"], dtype=float)
    if (rest.shape != (len(labels), 3) or points.ndim != 3
            or points.shape[1:] != rest.shape or rotations.shape != points.shape[:2] + (3, 3)
            or offsets.shape != points.shape):
        raise ValueError("invalid motion shapes")
    screen = np.asarray(screen_rows, dtype=float)
    if screen.shape != (2, 3) or not np.allclose(screen @ screen.T, np.eye(2), atol=1e-8):
        raise ValueError("orthonormal right/down screen rows required")
    forward = np.cross(*screen)
    basis = np.vstack((screen, forward))
    start, end = np.asarray(config["axisStart"], dtype=float), np.asarray(config["axisEnd"], dtype=float)
    if start.shape != (3,) or end.shape != (3,):
        raise ValueError("axis points require three coordinates")
    axis = end - start
    length = np.linalg.norm(axis)
    if not np.isfinite(length) or length < 1e-8:
        raise ValueError("nonzero finite rest weapon axis required")
    axis /= length
    records = config.get("frames")
    if not isinstance(records, list) or len(records) != len(points):
        raise ValueError("one explicit source axis per replay frame required")
    if not all(np.isfinite(a).all() for a in (rest, points, rotations, offsets, screen)):
        raise ValueError("nonfinite motion or camera")
    if (not np.allclose(rotations @ rotations.swapaxes(-1, -2), np.eye(3), atol=1e-7)
            or not np.allclose(np.linalg.det(rotations), 1, atol=1e-7)
            or not np.allclose(np.einsum("fjab,jb->fja", rotations, rest) + offsets, points, atol=1e-7)):
        raise ValueError("proper anchored transforms required")
    result = deepcopy(motion)
    result["rotations"], result["offsets"] = rotations.copy(), offsets.copy()
    audit = []
    for f, row in enumerate(records):
        if row.get("frame") != f:
            raise ValueError(f"frame {f}: ordered source evidence required")
        if row.get("status") == "occluded-axis-hold":
            ref = row.get("orientationReferenceFrame")
            if (config.get("occlusionPolicy") != "explicit-last-observed-released-axis"
                    or not isinstance(ref, int) or isinstance(ref, bool) or not 0 <= ref < f
                    or f - ref > config.get("maxOccludedFrames", 0)
                    or records[ref].get("status") != "measured"
                    or any(r.get("mode") != "released" or r.get("clipKey") != row.get("clipKey")
                           for r in records[ref:f + 1])
                    or any(r.get("status") != "occluded-axis-hold" for r in records[ref + 1:f])):
                raise ValueError(f"frame {f}: invalid explicit released-axis hold")
            corrected = result["rotations"][ref, owner]
            result["rotations"][f, owner] = corrected
            result["offsets"][f, owner] = points[f, owner] - corrected @ rest[owner]
            audit.append({"frame": f, "status": "occluded-axis-hold", "orientationReferenceFrame": ref,
                          "angleAfterDeg": None, "limit": "axis unobserved; explicit temporal assumption"})
            continue
        if row.get("status") != "measured":
            raise ValueError(f"frame {f}: measured axis or explicit occlusion rule required")
        grip, tip = np.asarray(row["grip"], dtype=float), np.asarray(row["tip"], dtype=float)
        if grip.shape != (2,) or tip.shape != (2,) or not np.isfinite([grip, tip]).all():
            raise ValueError(f"frame {f}: invalid 2D axis")
        direction = tip - grip
        span = np.linalg.norm(direction)
        if span < 2:
            raise ValueError(f"frame {f}: source axis too short to constrain orientation")
        direction /= span
        old_axis = rotations[f, owner] @ axis
        camera_axis = basis @ old_axis
        projected_length = np.linalg.norm(camera_axis[:2])
        if projected_length < 1e-5:
            raise ValueError(f"frame {f}: axis points into view; retained depth cannot resolve direction")
        target = basis.T @ np.r_[direction * projected_length, camera_axis[2]]
        # Least-parallel chooses a stable helper; projection makes the half-turn axis perpendicular.
        pole = rotations[f, owner, :, np.argmin(np.abs(rotations[f, owner].T @ old_axis))]
        pole = pole - old_axis * ((pole @ old_axis) / (old_axis @ old_axis))
        pole /= np.linalg.norm(pole)
        delta = _swing(old_axis[None], target[None], pole[None])[0]
        corrected = delta @ rotations[f, owner]
        if not np.allclose(corrected @ axis, target, atol=1e-8, rtol=0):
            raise ValueError(f"frame {f}: axis depth/direction constraint not met")
        actual = screen @ (corrected @ axis)
        actual /= np.linalg.norm(actual)
        error = float(np.degrees(np.arccos(np.clip(actual @ direction, -1, 1))))
        if error > 1e-4:
            raise ValueError(f"frame {f}: axis constraint not met")
        result["rotations"][f, owner] = corrected
        result["offsets"][f, owner] = points[f, owner] - corrected @ rest[owner]
        before = camera_axis[:2] / projected_length
        audit.append({"frame": f, "angleBeforeDeg": float(np.degrees(np.arccos(np.clip(before @ direction, -1, 1)))),
                      "angleAfterDeg": error,
                      "ownerRotationChangeDeg": float(np.degrees(np.arccos(np.clip((np.trace(delta) - 1) / 2, -1, 1))))})
    result["propOrientationReport"] = {
        "schema": "prop_orientation_report.v1", "owner": config["owner"], "frames": audit,
        "policy": config["policy"], "accepted": False,
        "limit": "source-supported projected weapon axis; depth and axis twist retained, not observed",
        "sourceMeshSha256": source_sha256,
    }
    return result
