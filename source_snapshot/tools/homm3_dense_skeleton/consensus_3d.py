#!/usr/bin/env python3
"""
Within-angle average + multi-view midpoint triangulation → MidHip-local 3D joints.

GenAI overlays do not share absolute framing. Each angle's 2D joints are therefore
body-normalized (MidHip origin, Neck distance = 1, +v = up) before triangulation
with the prompted azimuth/elevation cameras.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

TOOL = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOL))
from constants import JOINT_ORDER, MANIFEST, OUT, REQUIRED_CORE  # noqa: E402


def _load_jsonl(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def _cam_basis(az_deg: float, el_deg: float, distance: float = 3.0):
    """Return (cam_pos, right, up, forward, look_at)."""
    az = math.radians(az_deg)
    el = math.radians(el_deg)
    look_at = np.array([0.0, 0.0, 0.75], dtype=np.float64)
    r = distance * math.cos(el)
    cam = np.array([-r * math.sin(az), -r * math.cos(az), distance * math.sin(el) + 0.35], dtype=np.float64)
    forward = look_at - cam
    forward /= np.linalg.norm(forward) + 1e-9
    world_up = np.array([0.0, 0.0, 1.0], dtype=np.float64)
    right = np.cross(forward, world_up)
    if np.linalg.norm(right) < 1e-6:
        right = np.array([1.0, 0.0, 0.0], dtype=np.float64)
    right /= np.linalg.norm(right)
    up = np.cross(right, forward)
    up /= np.linalg.norm(up)
    return cam, right, up, forward, look_at


def _plane_point_uv(u: float, v: float, right, up, look_at) -> np.ndarray:
    """Body-normalized (u right, v up, MidHip=0, Neck≈1) → point on ortho plane."""
    return look_at + float(u) * right + float(v) * up


def _closest_point_rays(p1: np.ndarray, d1: np.ndarray, p2: np.ndarray, d2: np.ndarray) -> np.ndarray:
    d1 = d1 / (np.linalg.norm(d1) + 1e-9)
    d2 = d2 / (np.linalg.norm(d2) + 1e-9)
    w0 = p1 - p2
    a = 1.0
    b = float(np.dot(d1, d2))
    c = 1.0
    d = float(np.dot(d1, w0))
    e = float(np.dot(d2, w0))
    denom = a * c - b * b
    if abs(denom) < 1e-8:
        return 0.5 * (p1 + p2)
    t = (b * e - c * d) / denom
    s = (a * e - b * d) / denom
    q1 = p1 + t * d1
    q2 = p2 + s * d2
    return 0.5 * (q1 + q2)


def _reproject_uv(point: np.ndarray, u: float, v: float, right, up, look_at) -> float:
    rel = point - look_at
    pu = float(np.dot(rel, right))
    pv = float(np.dot(rel, up))
    return math.hypot(pu - u, pv - v)


def average_angle_2d(recs: list[dict]) -> dict[str, tuple[float, float]]:
    acc: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for r in recs:
        for name, j in (r.get("joints") or {}).items():
            if j.get("visible", True):
                acc[name].append((float(j["nx"]), float(j["ny"])))
    out = {}
    for name, pts in acc.items():
        arr = np.asarray(pts, dtype=np.float64)
        out[name] = (float(np.mean(arr[:, 0])), float(np.mean(arr[:, 1])))
    return out


def body_normalize_2d(avg: dict[str, tuple[float, float]]) -> dict[str, tuple[float, float]]:
    """MidHip→(0,0), image-up = +v, Neck distance = 1. Fail-closed without MidHip/Neck."""
    if "MidHip" not in avg or "Neck" not in avg:
        raise RuntimeError("angle average missing MidHip/Neck for body normalize")
    mx, my = avg["MidHip"]
    nx, ny = avg["Neck"]
    span = math.hypot(nx - mx, ny - my)
    if span < 1e-6:
        raise RuntimeError("degenerate MidHip-Neck span in angle average")
    out: dict[str, tuple[float, float]] = {}
    for name, (x, y) in avg.items():
        u = (x - mx) / span
        v = -(y - my) / span  # image y down → body up
        out[name] = (float(u), float(v))
    return out


def triangulate_joint_uv(
    observations: list[tuple[str, float, float, dict]],
    *,
    max_reproj: float = 0.25,
) -> tuple[np.ndarray, float] | None:
    """
    observations: list of (angle, u, v, angle_cfg) in body-normalized plane coords.
    """
    if len(observations) < 2:
        return None
    packs = []
    planes = []
    for angle, u, v, cfg in observations:
        cam, right, up, forward, look_at = _cam_basis(
            float(cfg["isoAzimuthDeg"]), float(cfg["isoElevationDeg"])
        )
        packs.append((angle, u, v, cam, right, up, forward, look_at))
        planes.append(_plane_point_uv(u, v, right, up, look_at))

    mids = []
    for i in range(len(planes)):
        for j in range(i + 1, len(planes)):
            p1 = packs[i][3]
            p2 = packs[j][3]
            d1 = planes[i] - p1
            d2 = planes[j] - p2
            mids.append(_closest_point_rays(p1, d1, p2, d2))
    xyz = np.mean(np.stack(mids, axis=0), axis=0)
    errs = [
        _reproject_uv(xyz, u, v, right, up, look_at)
        for _, u, v, _, right, up, _, look_at in packs
    ]
    mean_err = float(np.mean(errs))
    if mean_err > max_reproj:
        return None
    return xyz, mean_err


def consensus_frame(
    frame_recs: list[dict],
    angles_cfg: dict,
    *,
    max_reproj: float = 0.25,
) -> dict:
    by_angle: dict[str, list[dict]] = defaultdict(list)
    for r in frame_recs:
        by_angle[str(r["angle"])].append(r)

    angle_avg_raw = {}
    angle_avg_uv = {}
    for angle, recs in by_angle.items():
        if angle not in angles_cfg or not recs:
            continue
        raw = average_angle_2d(recs)
        angle_avg_raw[angle] = raw
        angle_avg_uv[angle] = body_normalize_2d(raw)

    joints_3d = {}
    reproj = {}
    missing = []
    for jname in JOINT_ORDER:
        obs = []
        for angle, avg in angle_avg_uv.items():
            if jname not in avg:
                continue
            u, v = avg[jname]
            obs.append((angle, u, v, angles_cfg[angle]))
        if len(obs) < 2:
            if jname in REQUIRED_CORE:
                missing.append(jname)
            continue
        tri = triangulate_joint_uv(obs, max_reproj=max_reproj)
        if tri is None and jname == "WeaponTip":
            tri = triangulate_joint_uv(obs, max_reproj=max_reproj * 1.75)
        if tri is None and len(obs) >= 2:
            plane_dirs = []
            for angle, u, v, cfg in obs:
                cam, right, up, forward, look_at = _cam_basis(
                    float(cfg["isoAzimuthDeg"]), float(cfg["isoElevationDeg"])
                )
                pt = _plane_point_uv(u, v, right, up, look_at)
                plane_dirs.append((cam, pt - cam, u, v, right, up, look_at))
            mids = []
            for i in range(len(plane_dirs)):
                for j in range(i + 1, len(plane_dirs)):
                    p1, d1, *_ = plane_dirs[i]
                    p2, d2, *_ = plane_dirs[j]
                    mids.append(_closest_point_rays(p1, d1, p2, d2))
            xyz = np.mean(np.stack(mids, axis=0), axis=0)
            errs = [
                _reproject_uv(xyz, u, v, right, up, look_at)
                for _, _, u, v, right, up, look_at in plane_dirs
            ]
            joints_3d[jname] = xyz
            reproj[jname] = float(np.mean(errs))
            continue
        if tri is None:
            if jname in REQUIRED_CORE:
                missing.append(jname)
            continue
        xyz, err = tri
        joints_3d[jname] = xyz
        reproj[jname] = err

    if missing:
        raise RuntimeError(f"frame missing triangulated core joints: {missing}")

    mid = joints_3d["MidHip"]
    neck = joints_3d["Neck"]
    span = float(np.linalg.norm(neck - mid))
    if span < 1e-6:
        raise RuntimeError("degenerate MidHip-Neck span")
    local = {k: ((v - mid) / span).tolist() for k, v in joints_3d.items()}

    # Soft topology checks (diagnostic; do not silent-fix).
    topology_warnings = []
    if local["Neck"][2] <= 0.2:
        topology_warnings.append("Neck.z unexpectedly low vs MidHip")
    for ankle in ("RAnkle", "LAnkle"):
        if ankle in local and local[ankle][2] > 0.2:
            topology_warnings.append(f"{ankle}.z above MidHip (expected feet below)")

    return {
        "jointsLocal": local,
        "midHipWorld": mid.tolist(),
        "neckSpan": span,
        "reprojMean": reproj,
        "anglesUsed": sorted(angle_avg_uv.keys()),
        "angleAvg2d": {a: {k: [v[0], v[1]] for k, v in avg.items()} for a, avg in angle_avg_raw.items()},
        "angleAvgUv": {a: {k: [v[0], v[1]] for k, v in avg.items()} for a, avg in angle_avg_uv.items()},
        "topologyWarnings": topology_warnings,
        "bodyNormalize": True,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--manifest", type=Path, default=MANIFEST)
    ap.add_argument("--culled", type=Path, default=OUT / "digitize" / "samples_culled.jsonl")
    ap.add_argument("--out", type=Path, default=OUT / "consensus" / "joints_3d.json")
    ap.add_argument("--max-reproj", type=float, default=0.35)
    args = ap.parse_args()
    man = json.loads(args.manifest.read_text(encoding="utf-8"))
    angles_cfg = man["angles"]
    if not args.culled.is_file():
        print(f"missing {args.culled}", file=sys.stderr)
        return 2
    rows = _load_jsonl(args.culled)
    by_frame: dict[int, list[dict]] = defaultdict(list)
    for r in rows:
        by_frame[int(r["frameIndex"])].append(r)

    frames = {}
    errors = {}
    for fi, recs in sorted(by_frame.items()):
        try:
            frames[str(fi)] = consensus_frame(recs, angles_cfg, max_reproj=args.max_reproj)
        except Exception as e:
            errors[str(fi)] = str(e)

    if not frames:
        report = {"ok": False, "error": "no frames consensus", "frameErrors": errors}
        args.out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, indent=2))
        return 1

    report = {
        "ok": len(errors) == 0,
        "frames": frames,
        "frameErrors": errors,
        "proof": (
            "generated artifact validated — body-normalized multi-view midpoint "
            "triangulation; not calibrated mocap"
        ),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": report["ok"], "frameCount": len(frames), "errors": errors}, indent=2))
    return 0 if frames else 1


if __name__ == "__main__":
    raise SystemExit(main())
