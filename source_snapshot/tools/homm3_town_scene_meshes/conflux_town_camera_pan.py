"""The vanilla town camera's real motion, expressed in the Conflux full-3D scene's frames (phase 6).

Source: vanilla_city_camera_pan.json (extract_city_camera_pan.py, the installed game's own cityHuman2 camera: the
BhCityCameraController on the CityCamera pivot and its SoCityCameraSettings "human2"). The v2 full-3D runtime seats
the scene root at MainCamera's authored rest pose relative to the CityCamera pivot; the root stays fixed while the
town camera moves. Legacy v1 catalogs retain camera-follow seating and are not valid phase-6 payloads:

  * Default (dxj.EType 0, dxo): the rest pose (MainCamera local pose under the pivot).
  * Cursor  (EType 1, dxn): the rest position; rotation = rest * Euler(mouse * deltaVerticalAngle, mouse *
    deltaHorizontalAngle), SmoothDamp'd and Slerp'd at rotationSpeed (GameAssembly disassembly: Input.mousePosition,
    Screen.width/height, Mathf.SmoothDamp, Quaternion.Euler, Quaternion.Slerp, Transform.set_rotation).
  * Free    (EType 2, dxp): the sweep. dxp.balv(t): position = spline(positionNodes)(t * length), Transform.set_position,
    then Transform.LookAt(lookAtTransform.position) -- the camera looks at the CityCamera pivot throughout.
    The first loop runs on firstLoopMovementSpeedCurve, later loops on movementSpeedCurve.
  * Mode switches (dxl): localPosition / localRotation lerped from the old pose to the new one over transitionTime.

The spline class (ks) is a closed curve through the nodes; its exact basis is not recovered, so the sweep is sampled
both as a uniform closed Catmull-Rom and as the node polygon, and every sample is taken with both the look-at-pivot
orientation (read from the disassembly) and the rest orientation (a margin). Sampled transitions include Default and
the Cursor yaw/pitch corners to Free; they are not an exhaustive motion proof. Aspects: 16:9, the user's 4096x2160 and 21:9 (64:27); the runtime root scale
(kx, ky, 1) with kx = ky * aspect / referenceAspect is intended to retain default-frame registration at each aspect;
editor renders have not yet verified that claim.

Frames: Unity world (vanilla cityHuman2 metres), root-local (prefab units; the scene bundle's frame), and the
painting world "w" the builders use (ctx.local(w) = ((w - cpos) @ C) * DEPTH_SCALE).
"""
from __future__ import annotations

import json
import math
import re
from pathlib import Path

import numpy as np
from scipy.spatial.transform import Rotation, Slerp

HERE = Path(__file__).resolve().parent
PAN_JSON = HERE / "vanilla_city_camera_pan.json"
CITY = "cityHuman2"
ASPECTS = {"16:9": 16 / 9, "4096x2160": 4096 / 2160, "21:9": 64 / 27}
REF_ASPECT = 16 / 9


def load(city: str = CITY, pan_json: Path | None = None) -> dict:
    source = Path(pan_json) if pan_json is not None else PAN_JSON
    doc = json.loads(source.read_text(encoding="utf-8"))
    for c in doc["cities"]:
        if c["scene"] == city:
            return c
    raise KeyError(city)


def rest_pose_contract(city: str = CITY, pan_json: Path | None = None) -> dict:
    """The native pivot-relative rest pose, pinned to the exact installed scene asset used for extraction."""
    source = Path(pan_json) if pan_json is not None else PAN_JSON
    doc = json.loads(source.read_text(encoding="utf-8"))
    rows = [row for row in doc["cities"] if row["scene"] == city]
    if len(rows) != 1:
        raise ValueError(f"expected one camera row for {city}, got {len(rows)}")
    row = rows[0]
    pivot, camera = row["lookAt"], row["camera"]
    if camera.get("parentPathId") != pivot["pathId"]:
        raise ValueError(f"{city}: camera is not a direct child of the look-at pivot")
    level = row["level"]
    if city == CITY and (level != "level67" or pivot["name"] != "CityCamera" or camera["name"] != "MainCamera"):
        raise ValueError("cityHuman2 rest pose must be CityCamera/MainCamera from level67")
    sha = doc["gameFiles"].get(level)
    if not re.fullmatch(r"[0-9a-f]{64}", str(sha)):
        raise ValueError(f"{city}: no pinned {level} sha256")
    if not level.startswith("level") or not level[5:].isdigit():
        raise ValueError(f"{city}: invalid level basename {level!r}")
    pos, rot = camera["localPosition"], camera["localRotation"]
    if len(pos) != 3 or len(rot) != 4 or rot[3] < 0:
        raise ValueError(f"{city}: invalid canonical rest pose")
    return {"pivotName": pivot["name"], "cameraName": camera["name"], "sourceScene": row["scene"],
            "sourceLevelFile": level, "sourceLevelSha256": sha,
            "localPosition": pos, "localRotation": rot}


def native_layout_differences(current: dict, canonical: dict) -> list[str]:
    """Compare camera values that affect town framing; path IDs and source hashes are build-specific."""
    fields = {
        "lookAt": ("name", "worldPos", "worldRot"),
        "camera": ("name", "localPosition", "localRotation", "worldPos", "worldRot"),
    }
    differences = [f"{block}.{field}" for block, names in fields.items() for field in names
                   if current.get(block, {}).get(field) != canonical.get(block, {}).get(field)]
    current_fov = current.get("camera", {}).get("fieldOfView")
    canonical_fov = canonical.get("camera", {}).get("fieldOfView")
    if not isinstance(current_fov, (int, float)) or not isinstance(canonical_fov, (int, float)) or not math.isclose(
            float(current_fov), float(canonical_fov), rel_tol=0.0, abs_tol=1e-5):
        differences.append("camera.fieldOfView")
    if current.get("settingsRef", {}).get("file") != canonical.get("settingsRef", {}).get("file"):
        differences.append("settingsRef.file")
    if current.get("settings") != canonical.get("settings"):
        differences.append("settings")
    return differences


def quat_to_mat(q) -> np.ndarray:
    x, y, z, w = q
    return np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                     [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                     [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])


def look_at(pos, target) -> np.ndarray:
    """Unity Transform.LookAt(target) with world up: columns right, up, forward."""
    f = np.asarray(target, np.float64) - pos
    f /= np.linalg.norm(f)
    r = np.cross([0.0, 1.0, 0.0], f)
    r /= np.linalg.norm(r)
    u = np.cross(f, r)
    return np.stack([r, u, f], 1)


def catmull_rom_closed(nodes: np.ndarray, per_seg: int) -> np.ndarray:
    n = len(nodes)
    out = []
    for i in range(n):
        p0, p1, p2, p3 = nodes[(i - 1) % n], nodes[i], nodes[(i + 1) % n], nodes[(i + 2) % n]
        for t in np.linspace(0, 1, per_seg, endpoint=False):
            t2, t3 = t * t, t * t * t
            out.append(0.5 * (2 * p1 + (-p0 + p2) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t2
                              + (-p0 + 3 * p1 - 3 * p2 + p3) * t3))
    return np.array(out)


def polygon_closed(nodes: np.ndarray, per_seg: int) -> np.ndarray:
    n = len(nodes)
    return np.array([nodes[i] + (nodes[(i + 1) % n] - nodes[i]) * t
                     for i in range(n) for t in np.linspace(0, 1, per_seg, endpoint=False)])


def euler_yx(yaw_deg: float, pitch_deg: float) -> np.ndarray:
    a, b = math.radians(yaw_deg), math.radians(pitch_deg)
    ry = np.array([[math.cos(a), 0, math.sin(a)], [0, 1, 0], [-math.sin(a), 0, math.cos(a)]])
    rx = np.array([[1, 0, 0], [0, math.cos(b), -math.sin(b)], [0, math.sin(b), math.cos(b)]])
    return ry @ rx


def poses(city: dict | None = None, per_seg: int = 48) -> list[dict]:
    """Sampled camera poses (Unity world): position + rotation matrix + label, not an exhaustive controller path."""
    c = city or load()
    s = c["settings"]
    rest_p = np.asarray(c["camera"]["worldPos"], np.float64)
    rest_R = quat_to_mat(c["camera"]["worldRot"])
    pivot = np.asarray(c["lookAt"]["worldPos"], np.float64)
    nodes = np.asarray(s["positionNodes"], np.float64)
    out = [{"p": rest_p, "R": rest_R, "mode": "default"}]
    dh, dv = float(s["deltaHorizontalAngle"]), float(s["deltaVerticalAngle"])
    for yaw in (-dh, 0.0, dh):
        for pitch in (-dv, 0.0, dv):
            out.append({"p": rest_p, "R": rest_R @ euler_yx(yaw, pitch), "mode": "cursor"})
    cursor_starts = [("cursor", rest_R @ euler_yx(yaw, pitch))
                     for yaw in (-dh, dh) for pitch in (-dv, dv)]
    paths = {"catmullRom": catmull_rom_closed(nodes, per_seg), "polygon": polygon_closed(nodes, per_seg)}
    for name, pts in paths.items():
        for p in pts:
            out.append({"p": p, "R": look_at(p, pivot), "mode": f"free/{name}/lookAt"})
            out.append({"p": p, "R": rest_R, "mode": f"free/{name}/restRotation"})
        starts = set(range(0, len(pts), max(1, per_seg // 4)))
        forward = pivot - pts
        az = np.arctan2(forward @ rest_R[:, 0], forward @ rest_R[:, 2])
        cursor_points = {int(np.argmin(az)), int(np.argmax(az)), int(np.argmax(pts[:, 1]))}
        for point_i in sorted(starts | cursor_points):
            p = pts[point_i]
            Rl = look_at(p, pivot)
            transition_starts = [("default", rest_R)] + (cursor_starts if point_i in cursor_points else [])
            for origin, Rstart in transition_starts:
                turn = Slerp([0, 1], Rotation.from_matrix(np.stack([Rstart, Rl])))
                for a in (0.25, 0.5, 0.75):
                    out.append({"p": rest_p + (p - rest_p) * a, "R": turn(a).as_matrix(),
                                "mode": f"transition/{origin}ToFree/{name}"})
    return out


def root_frame(city: dict | None = None):
    c = city or load()
    return np.asarray(c["camera"]["worldPos"], np.float64), quat_to_mat(c["camera"]["worldRot"])


def image_rays(fov_deg: float, aspect: float, nx: int = 41, ny: int = 23, border_only: bool = False) -> np.ndarray:
    """Camera-local ray directions (x right, y up, z forward) over the image (a grid, or its border)."""
    t = math.tan(math.radians(fov_deg) / 2)
    u = np.linspace(-1, 1, nx)
    v = np.linspace(-1, 1, ny)
    if border_only:
        uv = np.concatenate([np.stack([u, np.full(nx, -1.0)], 1), np.stack([u, np.full(nx, 1.0)], 1),
                             np.stack([np.full(ny, -1.0), v], 1), np.stack([np.full(ny, 1.0), v], 1)])
    else:
        U, V = np.meshgrid(u, v)
        uv = np.stack([U.ravel(), V.ravel()], 1)
    d = np.stack([uv[:, 0] * t * aspect, uv[:, 1] * t, np.ones(len(uv))], 1)
    return d / np.linalg.norm(d, axis=1, keepdims=True)


def pan_rays_w(ctx_C: np.ndarray, ctx_cpos: np.ndarray, depth_scale: float, fov_deg: float,
               aspects: dict = ASPECTS, per_seg: int = 48, nx: int = 41, ny: int = 23) -> dict:
    """Sampled pan-pose image rays in the painting world w: origins (N,3) and unit directions (N,3), per aspect.

    Unity world pose (p, R) -> root-local: q = R0^T (p - p0) / k, directions R0^T R d / k (k = (kx, ky, 1)), then
    w = cpos + (q / depthScale) @ C^T. A linear map keeps rays straight, so each ray stays a ray."""
    c = load()
    p0, R0 = root_frame(c)
    ps = poses(c, per_seg)
    loc = image_rays(fov_deg, 1.0, nx, ny)  # placeholder; per-aspect below
    out = {}
    for name, asp in aspects.items():
        ky = 1.0
        kx = ky * asp / REF_ASPECT
        k = np.array([kx, ky, 1.0])
        loc = image_rays(fov_deg, asp, nx, ny)
        O, D, M = [], [], []
        for pose in ps:
            q = (R0.T @ (pose["p"] - p0)) / k
            d = (loc @ pose["R"].T @ R0) / k
            ow = ctx_cpos + (q / depth_scale) @ ctx_C.T
            dw = (d / depth_scale) @ ctx_C.T
            dw /= np.linalg.norm(dw, axis=1, keepdims=True)
            O.append(np.repeat(ow[None], len(dw), 0))
            D.append(dw)
            M += [pose["mode"]] * len(dw)
        out[name] = {"O": np.concatenate(O), "D": np.concatenate(D), "mode": np.array(M), "kx": kx}
    return out


def proof_poses(city: dict | None = None, per_seg: int = 48) -> list[dict]:
    """The poses the proof renders use, in the scene root's local frame (16:9, k = 1): the rest pose, the cursor
    look at full yaw either side, and the look-at-pivot sweep (the orientation read from the disassembly) at its
    leftmost / rightmost heading and its highest point. Each: name, pos, fwd, up (root-local), azimuthDeg."""
    c = city or load()
    p0, R0 = root_frame(c)
    ps = poses(c, per_seg)

    def loc(p):
        B = R0.T @ p["R"]
        f, u = B[:, 2], B[:, 1]
        return {"pos": (R0.T @ (p["p"] - p0)).tolist(), "fwd": f.tolist(), "up": u.tolist(),
                "azimuthDeg": round(math.degrees(math.atan2(f[0], f[2])), 2)}

    out = [{"name": "default", **loc(ps[0])}]
    cur = [p for p in ps if p["mode"] == "cursor"]
    az = [loc(p)["azimuthDeg"] for p in cur]
    out += [{"name": "cursor_left", **loc(cur[int(np.argmin(az))])}, {"name": "cursor_right", **loc(cur[int(np.argmax(az))])}]
    sw = [p for p in ps if p["mode"] == "free/catmullRom/lookAt"]
    az = [loc(p)["azimuthDeg"] for p in sw]
    out += [{"name": "sweep_left", **loc(sw[int(np.argmin(az))])}, {"name": "sweep_right", **loc(sw[int(np.argmax(az))])},
            {"name": "sweep_high", **loc(sw[int(np.argmax([p["p"][1] for p in sw]))])}]
    return out


def summary(ctx_C: np.ndarray, ctx_cpos: np.ndarray, depth_scale: float, fov_deg: float) -> dict:
    """Camera envelope (root-local and w) and the angular range of the pan in the default camera's heading frame."""
    c = load()
    p0, R0 = root_frame(c)
    ps = poses(c)
    Q = np.array([R0.T @ (p["p"] - p0) for p in ps])
    rays = pan_rays_w(ctx_C, ctx_cpos, depth_scale, fov_deg, nx=17, ny=9)
    f = ctx_C[:, 2].copy()
    f[1] = 0
    f /= np.linalg.norm(f)
    r = np.cross([0.0, 1.0, 0.0], f)
    env = {}
    for name, rr in rays.items():
        D = rr["D"]
        az = np.degrees(np.arctan2(D @ r, D @ f))
        el = np.degrees(np.arcsin(np.clip(D[:, 1], -1, 1)))
        env[name] = {"azimuthDeg": [round(float(az.min()), 2), round(float(az.max()), 2)],
                     "elevationDeg": [round(float(el.min()), 2), round(float(el.max()), 2)]}
    def_rays = image_rays(fov_deg, REF_ASPECT, 17, 9) @ ctx_C.T
    az0 = np.degrees(np.arctan2(def_rays @ r, def_rays @ f))
    el0 = np.degrees(np.arcsin(np.clip(def_rays[:, 1], -1, 1)))
    return {"city": CITY, "settings": c["settings"]["name"], "nodes": len(c["settings"]["positionNodes"]),
            "poses": len(ps),
            "cameraOffsetRootLocal": {"min": Q.min(0).round(3).tolist(), "max": Q.max(0).round(3).tolist()},
            "cameraOffsetW": {"min": (Q.min(0) / depth_scale).round(3).tolist(),
                              "max": (Q.max(0) / depth_scale).round(3).tolist()},
            "defaultFrame": {"azimuthDeg": [round(float(az0.min()), 2), round(float(az0.max()), 2)],
                             "elevationDeg": [round(float(el0.min()), 2), round(float(el0.max()), 2)]},
            "panEnvelope": env}
