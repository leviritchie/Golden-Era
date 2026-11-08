#!/usr/bin/env python3
"""Measure where each adventure-map building prefab puts its footprint, in the pose the game renders.

The runtime (``Homm3MapBuildingMeshBundle.OrientToBillboardArtAndSeat``) places the prefab root on the
donor's footprint centre, *replaces* the root rotation with ``Euler(0, 180 + artYaw, 0) * upright``
and then lifts it so the bounds bottom sits on the ground. The yaw spins the footprint about the root
origin, so the one thing the prefab itself must get right is that its renderers' horizontal bounds
centre sits on that origin. The bundle builder's ``OrientUprightByMaxHeight`` bakes a tip (-90 about X
or Z) into the root that the runtime throws away; a child offset computed in the tipped pose becomes a
horizontal slide once the tip is gone (the Factory city stood 1.8 world units off its town,
playtest 2026-09-29).

This reads the staged AssetBundle with UnityPy (no Unity, no game) and emulates exactly that runtime
pose: ``ResolveUprightPitchOnce`` on the baked root rotation (tip candidates only when the baked pose
reads flat), yaw dropped (it cannot move the centre off the origin), root scale kept.

    python tools/homm3_map_building_meshes/map_building_prefab_placement.py [--filter _city__] [--json out.json]
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BUNDLE = (
    ROOT
    / "Heroes of Might & Magic Olden Era Playtest"
    / "OfflineUnlockMod"
    / "homm3_map_building_meshes"
    / "homm3_map_building_meshes"
)
# Homm3MapBuildingMeshBundle.GetRuntimeScale() as logged by the 2026-09-29 playtest (scale=0.8).
RUNTIME_SCALE = 0.8
# ResolveUprightPitchOnce candidates, in its order (Unity Euler degrees).
UPRIGHT_CANDIDATES = [(0, 0, 0), (-90, 0, 0), (90, 0, 0), (0, 0, -90), (0, 0, 90)]


def quat_to_mat(x: float, y: float, z: float, w: float) -> np.ndarray:
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ])


def unity_euler_to_mat(ex: float, ey: float, ez: float) -> np.ndarray:
    """Unity Quaternion.Euler: Z, then X, then Y (R = Ry * Rx * Rz)."""
    rx, ry, rz = (math.radians(v) for v in (ex, ey, ez))
    Rx = np.array([[1, 0, 0], [0, math.cos(rx), -math.sin(rx)], [0, math.sin(rx), math.cos(rx)]])
    Ry = np.array([[math.cos(ry), 0, math.sin(ry)], [0, 1, 0], [-math.sin(ry), 0, math.cos(ry)]])
    Rz = np.array([[math.cos(rz), -math.sin(rz), 0], [math.sin(rz), math.cos(rz), 0], [0, 0, 1]])
    return Ry @ Rx @ Rz


def _trs(tr) -> np.ndarray:
    q, p, s = tr.m_LocalRotation, tr.m_LocalPosition, tr.m_LocalScale
    M = np.eye(4)
    M[:3, :3] = quat_to_mat(q.x, q.y, q.z, q.w) @ np.diag([s.x, s.y, s.z])
    M[:3, 3] = [p.x, p.y, p.z]
    return M


def _mesh_boxes(tr, parent: np.ndarray, out: list) -> None:
    """Collect (8x3 corner array) of every MeshFilter AABB under ``tr`` in the root's local space."""
    go = tr.m_GameObject.read()
    for c in go.m_Components:
        ptr = c.component if hasattr(c, "component") else c
        if ptr.type.name != "MeshFilter":
            continue
        mf = ptr.read()
        if mf.m_Mesh.path_id == 0:
            continue
        ab = mf.m_Mesh.read().m_LocalAABB
        cen = np.array([ab.m_Center.x, ab.m_Center.y, ab.m_Center.z])
        ext = np.array([ab.m_Extent.x, ab.m_Extent.y, ab.m_Extent.z])
        corners = np.array([[sx, sy, sz] for sx in (-1, 1) for sy in (-1, 1) for sz in (-1, 1)]) * ext + cen
        out.append((parent[:3, :3] @ corners.T).T + parent[:3, 3])
    for ch in tr.m_Children:
        child = ch.read()
        _mesh_boxes(child, parent @ _trs(child), out)


def _aabb(corners: np.ndarray, R: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    p = (R @ corners.T).T
    return p.min(0), p.max(0)


def measure_root(tr) -> dict:
    """Runtime-pose footprint of one prefab root transform (root local space x root scale)."""
    s = tr.m_LocalScale
    S = np.diag([s.x, s.y, s.z])
    boxes: list = []
    _mesh_boxes(tr, np.eye(4), boxes)
    if not boxes:
        return {"renderers": 0}
    pts = np.concatenate(boxes) @ S.T
    q = tr.m_LocalRotation
    baked = quat_to_mat(q.x, q.y, q.z, q.w)
    # ResolveUprightPitchOnce: flat test on the baked pose, then the tallest candidate.
    mn, mx = _aabb(pts, baked)
    size = mx - mn
    upright = (0, 0, 0)
    if size[1] < size[0] * 0.85 and size[1] < size[2] * 0.85:
        best = -1.0
        for cand in UPRIGHT_CANDIDATES:
            cmn, cmx = _aabb(pts, unity_euler_to_mat(*cand))
            if cmx[1] - cmn[1] > best:
                best, upright = cmx[1] - cmn[1], cand
    mn, mx = _aabb(pts, unity_euler_to_mat(*upright))
    ext = mx - mn
    ctr = (mn + mx) / 2
    off = float(math.hypot(ctr[0], ctr[2]))
    foot = float(max(ext[0], ext[2]))
    return {
        "renderers": len(boxes),
        "bakedRootEuler": [round(v, 1) for v in _mat_to_unity_euler(baked)],
        "runtimeUpright": list(upright),
        "footprint": [round(float(ext[0]), 4), round(float(ext[2]), 4)],
        "height": round(float(ext[1]), 4),
        "centreXZ": [round(float(ctr[0]), 4), round(float(ctr[2]), 4)],
        "offset": round(off, 4),
        "offsetWorld": round(off * RUNTIME_SCALE, 4),
        "offsetRel": round(off / foot, 4) if foot > 0 else None,
    }


def _mat_to_unity_euler(R: np.ndarray) -> tuple[float, float, float]:
    ex = math.degrees(math.asin(max(-1.0, min(1.0, -R[1, 2]))))
    ey = math.degrees(math.atan2(R[0, 2], R[2, 2]))
    ez = math.degrees(math.atan2(R[1, 0], R[1, 1]))
    return ex, ey, ez


def measure_bundle(bundle: Path, name_filter: str | None = None) -> dict[str, dict]:
    import UnityPy  # local import: only the placement check needs it

    env = UnityPy.load(str(bundle))
    out: dict[str, dict] = {}
    for obj in env.objects:
        if obj.type.name != "Transform":
            continue
        tr = obj.read()
        if tr.m_Father.path_id != 0:
            continue
        name = tr.m_GameObject.read().m_Name
        if not name.startswith("map_mesh_"):
            continue
        if name_filter and name_filter not in name:
            continue
        out[name] = measure_root(tr)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--bundle", type=Path, default=DEFAULT_BUNDLE)
    ap.add_argument("--filter", default=None, help="substring of the prefab name, e.g. _city__")
    ap.add_argument("--json", type=Path, default=None)
    args = ap.parse_args()
    rows = measure_bundle(args.bundle, args.filter)
    for k in sorted(rows):
        r = rows[k]
        print(f"{k:48s} baked={r.get('bakedRootEuler')} upright={r.get('runtimeUpright')} "
              f"foot={r.get('footprint')} centreXZ={r.get('centreXZ')} "
              f"offsetWorld={r.get('offsetWorld')} rel={r.get('offsetRel')}")
    if args.json:
        args.json.write_text(json.dumps(rows, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
