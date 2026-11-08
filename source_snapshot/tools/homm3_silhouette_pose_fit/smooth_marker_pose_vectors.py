#!/usr/bin/env python3
"""Post-fit temporal smooth + windup ease for marker-IK pose vectors.

Does not re-solve IK. Softens single-frame sprite spikes (e.g. one-frame
backswing) by Gaussian-smoothing bone Eulers and optionally time-stretching
the windup segment before playback/resample.

  python tools/homm3_silhouette_pose_fit/smooth_marker_pose_vectors.py \\
    --report artifacts/.../fit_report.json \\
    --out artifacts/.../fit_report_smoothed.json
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]


def _gaussian_kernel(radius: int, sigma: float) -> np.ndarray:
    xs = np.arange(-radius, radius + 1, dtype=np.float64)
    k = np.exp(-0.5 * (xs / max(sigma, 1e-6)) ** 2)
    k /= float(np.sum(k))
    return k


def _smooth_rotations(vecs: np.ndarray, n_rot: int, *, sigma: float) -> np.ndarray:
    if sigma <= 0.0:
        return vecs.copy()
    radius = max(1, int(round(sigma * 2)))
    kernel = _gaussian_kernel(radius, sigma)
    out = vecs.copy()
    n = vecs.shape[0]
    for d in range(n_rot):
        padded = np.pad(vecs[:, d], (radius, radius), mode="edge")
        out[:, d] = np.convolve(padded, kernel, mode="valid")
        if out.shape[0] != n:
            raise RuntimeError("smooth length mismatch")
    return out


def _restore_extrema(
    smoothed: np.ndarray,
    original: np.ndarray,
    n_rot: int,
    frames: list[int],
    *,
    blend: float,
) -> np.ndarray:
    """Pull selected keyframes back toward the unsmoothed pose (preserve reach)."""
    out = smoothed.copy()
    b = float(np.clip(blend, 0.0, 1.0))
    if b <= 0.0:
        return out
    for fi in frames:
        if fi < 0 or fi >= len(out):
            continue
        out[fi, :n_rot] = (1.0 - b) * smoothed[fi, :n_rot] + b * original[fi, :n_rot]
    return out


def _arm_energy(vecs: np.ndarray, names: list[str]) -> np.ndarray:
    n_rot = len(names) * 3
    rot = vecs[:, :n_rot].reshape(len(vecs), len(names), 3)
    want = {"RightShoulder", "RightArm", "RightForeArm", "RightHand", "LeftShoulder", "LeftArm"}
    idxs = [i for i, n in enumerate(names) if n in want]
    if not idxs:
        idxs = list(range(min(6, len(names))))
    return np.linalg.norm(rot[:, idxs], axis=2).sum(axis=1)


def _find_windup_apex(energy: np.ndarray) -> int:
    """Last energy peak before the global arm-energy maximum (strike)."""
    n = len(energy)
    if n < 3:
        return max(0, n - 1)
    strike = int(np.argmax(energy))
    if strike <= 1:
        return strike
    # Prefer a local maximum before the strike peak.
    candidates: list[int] = []
    for i in range(1, strike):
        if energy[i] >= energy[i - 1] and energy[i] >= energy[min(i + 1, n - 1)]:
            candidates.append(i)
    if candidates:
        return int(candidates[-1])
    return int(np.argmax(energy[:strike]))


def _time_stretch_keys(
    vecs: np.ndarray,
    *,
    windup_frame: int,
    stretch: float,
    pad: int,
) -> np.ndarray:
    """Rebuild a denser key timeline that spends more time near windup_frame.

    Returns pose keys at ~2x density with segment weights; caller stores fps hint.
    """
    n = len(vecs)
    if n < 2 or stretch <= 1.0:
        return vecs.copy()
    # Segment weights between consecutive source frames.
    w = np.ones(n - 1, dtype=np.float64)
    lo = max(0, windup_frame - pad)
    hi = min(n - 2, windup_frame + pad)
    for i in range(lo, hi + 1):
        # Strongest on the segment entering the apex.
        dist = abs(i - (windup_frame - 1))
        w[i] *= 1.0 + (stretch - 1.0) * max(0.0, 1.0 - dist / max(1, pad))
    # Emit roughly 2 keys per unit weight (keeps clip length in source-time similar
    # when played at adjusted fps — we keep the same duration by resampling to
    # the original frame count after warp for GLB compatibility, OR expand count).
    # Expand: total out frames ~ sum(w)*2 + 1, then we will note duration from src fps.
    steps = np.maximum(1, np.round(w * 2.0).astype(np.int32))
    pieces = [vecs[0:1]]
    for i, s in enumerate(steps):
        a = vecs[i]
        b = vecs[i + 1]
        for k in range(1, int(s) + 1):
            t = k / float(s)
            pieces.append((a * (1.0 - t) + b * t).reshape(1, -1))
    return np.concatenate(pieces, axis=0)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--report", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--sigma", type=float, default=0.55, help="Gaussian sigma in source frames")
    ap.add_argument("--windup-stretch", type=float, default=2.2, help=">1 lengthens windup; 1 disables")
    ap.add_argument("--windup-pad", type=int, default=1, help="segments around apex to stretch")
    ap.add_argument(
        "--preserve-extrema",
        type=float,
        default=1.0,
        help="0..1 blend restoring unsmoothed windup/strike apex poses (1=full reach)",
    )
    ap.add_argument("--src-fps", type=float, default=None)
    args = ap.parse_args()

    report_path = args.report if args.report.is_absolute() else ROOT / args.report
    out_path = args.out if args.out.is_absolute() else ROOT / args.out
    report = json.loads(report_path.read_text(encoding="utf-8"))
    names = list(report["optimizeBones"])
    vecs = np.asarray(report["poseVectors"], dtype=np.float64)
    if vecs.ndim != 2 or vecs.shape[0] < 2:
        raise RuntimeError("need >=2 pose vectors")
    n_rot = len(names) * 3
    if vecs.shape[1] < n_rot:
        raise RuntimeError("pose vector shorter than optimizeBones*3")

    energy_src = _arm_energy(vecs, names)
    apex = _find_windup_apex(energy_src)
    strike = int(np.argmax(energy_src))

    smoothed = _smooth_rotations(vecs, n_rot, sigma=float(args.sigma))
    # Keep root translate exact (frame0_root / anti-skate).
    if vecs.shape[1] > n_rot:
        smoothed[:, n_rot:] = vecs[:, n_rot:]
    smoothed = _restore_extrema(
        smoothed,
        vecs,
        n_rot,
        [apex, strike],
        blend=float(args.preserve_extrema),
    )

    stretched = _time_stretch_keys(
        smoothed,
        windup_frame=apex,
        stretch=float(args.windup_stretch),
        pad=max(0, int(args.windup_pad)),
    )
    src_fps = float(args.src_fps) if args.src_fps is not None else float(report.get("fps") or 12.0)
    # Preserve wall-clock clip duration: denser keys => higher effective key fps.
    duration_s = (len(vecs) - 1) / src_fps
    key_fps = (len(stretched) - 1) / duration_s if duration_s > 0 else src_fps

    out = dict(report)
    out["poseVectors"] = stretched.tolist()
    out["frameCount"] = int(len(stretched))
    out["fps"] = float(key_fps)
    out["smoothPose"] = {
        "sourceReport": str(report_path).replace("\\", "/"),
        "sigma": float(args.sigma),
        "windupStretch": float(args.windup_stretch),
        "windupPad": int(args.windup_pad),
        "preserveExtrema": float(args.preserve_extrema),
        "windupApexFrame": int(apex),
        "strikeFrame": int(strike),
        "armEnergy": [float(x) for x in energy_src.tolist()],
        "sourceFrameCount": int(len(vecs)),
        "sourceFps": float(src_fps),
        "outputKeyFps": float(key_fps),
        "durationSec": float(duration_s),
        "proof": (
            "generated artifact validated — post-fit Gaussian smooth + extrema restore + "
            "windup time-stretch; not a new IK solve; not OE runtime proven"
        ),
    }
    # Drop stale per-frame IK stats (length no longer matches).
    out["frames"] = [
        {"frameIndex": i, "lossPx": None, "stopReason": "smoothed_playback"}
        for i in range(len(stretched))
    ]
    out["method"] = str(report.get("method") or "marker_ik") + "_smoothed"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "ok": True,
                "out": str(out_path).replace("\\", "/"),
                "windupApexFrame": apex,
                "strikeFrame": strike,
                "preserveExtrema": float(args.preserve_extrema),
                "sigma": float(args.sigma),
                "sourceFrames": len(vecs),
                "outputKeys": len(stretched),
                "keyFps": key_fps,
                "durationSec": duration_s,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
