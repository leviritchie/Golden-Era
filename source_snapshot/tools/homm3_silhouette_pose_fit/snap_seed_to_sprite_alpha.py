#!/usr/bin/env python3
"""Snap mesh-bind seed joints onto nearest opaque sprite pixels (fail-closed).

Mesh-bind camera projection often lands slightly off the NN sprite silhouette.
This rewrites joints that miss alpha to the nearest opaque pixel within --max-dist-px.
Joints beyond that distance abort — do not invent poses.

  py -3 tools/homm3_silhouette_pose_fit/snap_seed_to_sprite_alpha.py \\
    --seed seed_joints_f00_mesh_bind.json --sprite frame_00.png --out seed_joints_f00.json
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image


def _nearest_opaque(alpha: np.ndarray, x: float, y: float, max_dist: float) -> tuple[float, float, float] | None:
    h, w = alpha.shape
    xi = int(round(x))
    yi = int(round(y))
    if 0 <= xi < w and 0 <= yi < h and alpha[yi, xi] > 0:
        return float(xi), float(yi), 0.0
    r = int(np.ceil(max_dist))
    best = None
    best_d2 = max_dist * max_dist + 1.0
    y0 = max(0, yi - r)
    y1 = min(h, yi + r + 1)
    x0 = max(0, xi - r)
    x1 = min(w, xi + r + 1)
    ys, xs = np.nonzero(alpha[y0:y1, x0:x1] > 0)
    if ys.size == 0:
        return None
    xs = xs.astype(np.float64) + x0
    ys = ys.astype(np.float64) + y0
    d2 = (xs - x) ** 2 + (ys - y) ** 2
    i = int(np.argmin(d2))
    if float(d2[i]) > max_dist * max_dist:
        return None
    return float(xs[i]), float(ys[i]), float(np.sqrt(d2[i]))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=Path, required=True)
    ap.add_argument("--sprite", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--max-dist-px", type=float, default=48.0)
    ap.add_argument("--alpha-thr", type=int, default=8)
    args = ap.parse_args()

    seed = json.loads(args.seed.read_text(encoding="utf-8"))
    rgba = np.asarray(Image.open(args.sprite).convert("RGBA"))
    alpha = rgba[:, :, 3]
    alpha = (alpha >= int(args.alpha_thr)).astype(np.uint8)

    joints = seed.get("joints") or {}
    if not joints:
        raise SystemExit("seed has no joints")
    moved = []
    failed = []
    out_joints = {}
    for name, j in joints.items():
        x = float(j["x"])
        y = float(j["y"])
        hit = _nearest_opaque(alpha, x, y, float(args.max_dist_px))
        if hit is None:
            failed.append(f"{name}@({x:.1f},{y:.1f})")
            continue
        nx, ny, dist = hit
        nj = dict(j)
        nj["x"] = nx
        nj["y"] = ny
        if dist > 0.5:
            nj["snapDistPx"] = dist
            nj["snapFrom"] = [x, y]
            nj["source"] = str(j.get("source") or "mesh_bind") + "+alpha_snap"
            moved.append(f"{name}:{dist:.1f}px")
        out_joints[name] = nj

    if failed:
        raise SystemExit(
            "fail-closed: seed joints too far from sprite alpha (>"
            f"{args.max_dist_px}px): " + ", ".join(failed)
        )

    out = dict(seed)
    out["joints"] = out_joints
    out["alphaSnap"] = {
        "maxDistPx": float(args.max_dist_px),
        "moved": moved,
        "sprite": str(args.sprite).replace("\\", "/"),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "out": str(args.out), "moved": moved}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
