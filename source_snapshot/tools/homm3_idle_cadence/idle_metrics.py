"""Scale-free cadence metrics for one looping idle clip.

Input: uniformly resampled local bone rotations, {bone: (T, 4) quaternion xyzw}, over one loop
of `length` seconds (the last sample is the loop end, equal in time to `length`). Both the
native Olden Era extractor (Unity AnimationClip) and the GLB extractor feed this same function,
so native and ours are measured by one rule.

Metrics
- lengthS: loop period in seconds.
- movingBones: bones whose rotation leaves their loop-mean pose by more than 0.5 deg.
- angSpeedDegS: per moving bone, the time-mean local angular speed; reported as the median
  over moving bones (`median`) and the 90th percentile (`p90`).
- peakAngSpeedDegS: per moving bone, the peak angular speed; median and p90 over bones.
- amplitudeDeg: per moving bone, the largest angle from the bone's loop-mean rotation;
  median and p90 over bones.
- beats: motion beats (breaths / sways) per loop. The loop's pose trajectory (all moving
  bones' sign-aligned quaternion components, mean-removed) is projected on its first
  principal component; beats = dominant cycles per loop of that signal (rFFT peak over
  harmonics 1..T/4), which counts a breathe-in / breathe-out as one beat.
- beatPeriodS: lengthS / beats, the time one breath or sway takes.
"""
from __future__ import annotations

import numpy as np

MOVING_DEG = 0.5


def _normalize(q: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(q, axis=-1, keepdims=True)
    return q / np.maximum(n, 1e-12)


def _align_signs(q: np.ndarray) -> np.ndarray:
    q = q.copy()
    for i in range(1, len(q)):
        if np.dot(q[i], q[i - 1]) < 0:
            q[i] = -q[i]
    return q


def _angle_deg(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    d = np.abs(np.sum(a * b, axis=-1))
    return np.degrees(2.0 * np.arccos(np.clip(d, -1.0, 1.0)))


def _mean_rotation(q: np.ndarray) -> np.ndarray:
    # principal eigenvector of sum q q^T (Markley average)
    m = q.T @ q
    w, v = np.linalg.eigh(m)
    return v[:, -1]


def cadence(rotations: dict[str, np.ndarray], length: float) -> dict:
    if length <= 0:
        raise ValueError("clip length must be > 0")
    stats = {"lengthS": round(float(length), 4)}
    names, speeds_mean, speeds_peak, amps, series = [], [], [], [], []
    for name, q in rotations.items():
        q = _align_signs(_normalize(np.asarray(q, dtype=np.float64)))
        if len(q) < 3:
            continue
        mean = _mean_rotation(q)
        amp = float(np.max(_angle_deg(q, mean[None, :])))
        if amp <= MOVING_DEG:
            continue
        dt = length / (len(q) - 1)
        w = _angle_deg(q[1:], q[:-1]) / dt
        names.append(name)
        speeds_mean.append(float(np.mean(w)))
        speeds_peak.append(float(np.max(w)))
        amps.append(amp)
        series.append(q - q.mean(axis=0))
    stats["movingBones"] = len(names)
    if not names:
        stats.update({"angSpeedDegS": None, "peakAngSpeedDegS": None, "amplitudeDeg": None,
                      "beats": 0, "beatPeriodS": None})
        return stats

    def mp(v):
        v = np.asarray(v)
        return {"median": round(float(np.median(v)), 3), "p90": round(float(np.percentile(v, 90)), 3)}

    stats["angSpeedDegS"] = mp(speeds_mean)
    stats["peakAngSpeedDegS"] = mp(speeds_peak)
    stats["amplitudeDeg"] = mp(amps)
    X = np.concatenate(series, axis=1)[:-1]          # drop the closing sample (== first on a loop)
    u, s, vt = np.linalg.svd(X - X.mean(axis=0), full_matrices=False)
    pc1 = u[:, 0] * s[0]
    spec = np.abs(np.fft.rfft(pc1))
    hi = max(2, len(pc1) // 4)
    beats = int(np.argmax(spec[1:hi]) + 1) if len(spec) > 2 else 1
    stats["beats"] = beats
    stats["beatPeriodS"] = round(float(length / beats), 4)
    stats["pc1Share"] = round(float(s[0] ** 2 / max(np.sum(s ** 2), 1e-12)), 3)
    return stats


def summarize(rows: list[dict], key: str) -> dict:
    """median / p10 / p90 of a scalar or {median} metric across clips."""
    vals = []
    for r in rows:
        v = r.get(key)
        if isinstance(v, dict):
            v = v.get("median")
        if v is not None:
            vals.append(float(v))
    if not vals:
        return {}
    a = np.asarray(vals)
    return {"n": len(a), "p10": round(float(np.percentile(a, 10)), 3),
            "median": round(float(np.median(a)), 3), "p90": round(float(np.percentile(a, 90)), 3)}
