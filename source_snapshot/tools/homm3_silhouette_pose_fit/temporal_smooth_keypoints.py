#!/usr/bin/env python3
"""
Temporal smoother for DWPose (or landmark) keypoints.json tracks.

Applies a causal+acausal score-weighted moving average across the clip so
joint positions are not independent per frame. Fail-closed: refuses empty /
partial clips and unknown methods.

  python temporal_smooth_keypoints.py --keypoints in.json --out out.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np


def _gaussian_kernel(radius: int, sigma: float) -> np.ndarray:
    xs = np.arange(-radius, radius + 1, dtype=np.float64)
    k = np.exp(-0.5 * (xs / max(sigma, 1e-6)) ** 2)
    k /= float(np.sum(k))
    return k


def smooth_tracks(
    frames: list[dict],
    *,
    joint_names: list[str],
    window: int,
    sigma: float,
    score_power: float,
) -> list[dict]:
    if window < 3 or window % 2 == 0:
        raise ValueError(f"window must be odd and >=3, got {window}")
    radius = window // 2
    kernel = _gaussian_kernel(radius, sigma)
    n = len(frames)
    # (T, J, 2), (T, J)
    xy = np.zeros((n, len(joint_names), 2), dtype=np.float64)
    sc = np.zeros((n, len(joint_names)), dtype=np.float64)
    vis = np.zeros((n, len(joint_names)), dtype=bool)

    for t, fr in enumerate(frames):
        joints = fr.get("joints") or {}
        for j, name in enumerate(joint_names):
            jj = joints.get(name)
            if not jj:
                continue
            xy[t, j, 0] = float(jj["x"])
            xy[t, j, 1] = float(jj["y"])
            sc[t, j] = max(0.0, float(jj.get("score", 0.0)))
            vis[t, j] = bool(jj.get("visible", False))

    w = (sc ** score_power) * vis.astype(np.float64)
    out_xy = np.zeros_like(xy)
    out_sc = np.zeros_like(sc)

    for t in range(n):
        for j in range(len(joint_names)):
            num = np.zeros(2, dtype=np.float64)
            den = 0.0
            score_acc = 0.0
            wsum = 0.0
            for k in range(-radius, radius + 1):
                tt = t + k
                if tt < 0 or tt >= n:
                    continue
                wk = float(kernel[k + radius] * w[tt, j])
                if wk <= 0.0:
                    continue
                num += wk * xy[tt, j]
                den += wk
                score_acc += wk * sc[tt, j]
                wsum += wk
            if den <= 1e-12:
                # No temporal support — keep original (may be invisible).
                out_xy[t, j] = xy[t, j]
                out_sc[t, j] = sc[t, j]
            else:
                out_xy[t, j] = num / den
                out_sc[t, j] = score_acc / max(wsum, 1e-12)

    smoothed: list[dict] = []
    for t, fr in enumerate(frames):
        new_joints = {}
        src_joints = fr.get("joints") or {}
        for j, name in enumerate(joint_names):
            if name not in src_joints and not vis[t, j]:
                continue
            base = dict(src_joints.get(name) or {})
            base["x"] = float(out_xy[t, j, 0])
            base["y"] = float(out_xy[t, j, 1])
            base["score"] = float(out_sc[t, j])
            thr = 0.12
            base["visible"] = bool(out_sc[t, j] >= thr and den_nearby(w, t, j, radius))
            base["smoothed"] = True
            new_joints[name] = base
        nf = dict(fr)
        nf["joints"] = new_joints
        nf["temporalSmooth"] = {
            "method": "score_weighted_gaussian",
            "window": window,
            "sigma": sigma,
            "scorePower": score_power,
        }
        smoothed.append(nf)
    return smoothed


def den_nearby(w: np.ndarray, t: int, j: int, radius: int) -> bool:
    n = w.shape[0]
    for k in range(-radius, radius + 1):
        tt = t + k
        if 0 <= tt < n and w[tt, j] > 0.0:
            return True
    return False


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--keypoints", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--method", default="score_weighted_gaussian", choices=["score_weighted_gaussian"])
    ap.add_argument("--window", type=int, default=5, help="Odd frame window (>=3)")
    ap.add_argument("--sigma", type=float, default=1.25)
    ap.add_argument("--score-power", type=float, default=1.0)
    args = ap.parse_args()

    report = json.loads(args.keypoints.read_text(encoding="utf-8"))
    if not report.get("ok"):
        print(f"refuse: keypoints not ok: {args.keypoints}", file=sys.stderr)
        return 2
    frames = sorted(report.get("frames") or [], key=lambda f: int(f["frameIndex"]))
    if len(frames) < 2:
        print("refuse: need >=2 frames for temporal smooth", file=sys.stderr)
        return 2
    expected = report.get("frameCountExpected")
    if expected is not None and len(frames) != int(expected):
        print("refuse: partial clip (frameCountOk != expected)", file=sys.stderr)
        return 2

    # Union of joint names across frames (OpenPose body-18 + optional WeaponTip).
    names: list[str] = []
    seen = set()
    for fr in frames:
        for name in (fr.get("joints") or {}):
            if name not in seen:
                seen.add(name)
                names.append(name)
    if not names:
        print("refuse: no joints", file=sys.stderr)
        return 2

    if args.method != "score_weighted_gaussian":
        print(f"unknown method {args.method}", file=sys.stderr)
        return 2

    smoothed = smooth_tracks(
        frames,
        joint_names=names,
        window=int(args.window),
        sigma=float(args.sigma),
        score_power=float(args.score_power),
    )
    out = dict(report)
    out["frames"] = smoothed
    out["temporalSmooth"] = {
        "method": args.method,
        "window": int(args.window),
        "sigma": float(args.sigma),
        "scorePower": float(args.score_power),
        "sourceKeypoints": str(args.keypoints.resolve()).replace("\\", "/"),
    }
    out["detector"] = f"{report.get('detector', 'unknown')}+temporal_smooth"
    out["proof"] = (
        "generated artifact validated — temporally smoothed keypoints; not OE runtime proven"
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "ok": True,
                "out": str(args.out.resolve()).replace("\\", "/"),
                "frames": len(smoothed),
                "joints": len(names),
                "method": args.method,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
