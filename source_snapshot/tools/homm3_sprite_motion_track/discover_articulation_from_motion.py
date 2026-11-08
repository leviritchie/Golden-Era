#!/usr/bin/env python3
"""
Discover articulation from multi-frame sprite motion (topology-free).

High-motion / short-lived tracks are first-class (weapon tips, extremities).
Tracks do NOT need to survive the whole clip.

1. Seed denser where early-frame flow is large (moving extremities).
2. Advect with Farneback; NCC-reacquire when a track would die.
3. Cluster partial trajectories by travel pattern.
4. Hinges = boundaries between neighboring parts with different travel.

Example:
  tools/.venvs/homm3_dwpose/Scripts/python.exe \\
    tools/homm3_sprite_motion_track/discover_articulation_from_motion.py \\
    --frames-dir artifacts/.../canonical_group_11_nn_upscale \\
    --out-dir artifacts/.../out_articulation_motion_g11
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_FRAMES = (
    ROOT
    / "artifacts/hobgoblin_attack_pose_pipeline/source_attack_frames/canonical_group_11_nn_upscale"
)
DEFAULT_OUT = ROOT / "artifacts/hobgoblin_attack_pose_pipeline/out_articulation_motion_g11"

PART_COLORS = [
    (255, 80, 80),
    (80, 200, 255),
    (255, 200, 40),
    (120, 255, 120),
    (220, 120, 255),
    (255, 140, 40),
    (80, 255, 200),
    (180, 180, 255),
    (255, 100, 180),
    (160, 255, 80),
    (100, 160, 255),
    (255, 220, 140),
]


def _load_rgba(path: Path) -> np.ndarray:
    return np.asarray(Image.open(path).convert("RGBA"))


def _opaque_mask(alpha: np.ndarray, thr: int = 8) -> np.ndarray:
    return alpha >= thr


def _farneback(prev: np.ndarray, nxt: np.ndarray) -> np.ndarray:
    return cv2.calcOpticalFlowFarneback(
        prev,
        nxt,
        None,
        pyr_scale=0.5,
        levels=5,
        winsize=25,
        iterations=4,
        poly_n=7,
        poly_sigma=1.5,
        flags=0,
    )


def _flow_mag(flow: np.ndarray) -> np.ndarray:
    return np.linalg.norm(flow, axis=2)


def _sample_flow(flow: np.ndarray, pts: np.ndarray) -> np.ndarray:
    out = pts.copy()
    h, w = flow.shape[:2]
    for i, (x, y) in enumerate(pts):
        xi, yi = int(round(x)), int(round(y))
        if 0 <= yi < h and 0 <= xi < w:
            dx, dy = flow[yi, xi]
            out[i, 0] = x + float(dx)
            out[i, 1] = y + float(dy)
    return out


def _extract_patch(gray: np.ndarray, x: float, y: float, half: int) -> np.ndarray | None:
    xi, yi = int(round(x)), int(round(y))
    h, w = gray.shape
    if yi - half < 0 or xi - half < 0 or yi + half >= h or xi + half >= w:
        return None
    patch = gray[yi - half : yi + half + 1, xi - half : xi + half + 1]
    if float(np.std(patch)) < 2.0:
        return None
    return patch


def _ncc_reacquire(
    gray: np.ndarray,
    mask: np.ndarray,
    patch: np.ndarray,
    pred_xy: tuple[float, float],
    *,
    search: int,
) -> tuple[float, float, float] | None:
    """Return (x, y, ncc) or None."""
    ph, pw = patch.shape
    half_y, half_x = ph // 2, pw // 2
    px, py = pred_xy
    h, w = gray.shape
    x0 = max(half_x, int(round(px)) - search)
    y0 = max(half_y, int(round(py)) - search)
    x1 = min(w - half_x, int(round(px)) + search)
    y1 = min(h - half_y, int(round(py)) + search)
    if x1 - x0 < pw or y1 - y0 < ph:
        return None
    roi = gray[y0:y1, x0:x1]
    if roi.shape[0] < ph or roi.shape[1] < pw:
        return None
    res = cv2.matchTemplate(roi, patch, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(res)
    if max_val < 0.35:
        return None
    mx, my = max_loc
    x = float(x0 + mx + half_x)
    y = float(y0 + my + half_y)
    xi, yi = int(round(x)), int(round(y))
    if yi < 0 or xi < 0 or yi >= h or xi >= w or not mask[yi, xi]:
        return None
    return x, y, float(max_val)


def _seed_points(
    gray: np.ndarray,
    mask: np.ndarray,
    flow0: np.ndarray,
    *,
    max_points: int,
    min_dist: float,
) -> np.ndarray:
    """Seed opaque pixels; oversample high-flow (moving extremities)."""
    mag = _flow_mag(flow0)
    mag = np.where(mask, mag, 0.0)
    thr = float(np.percentile(mag[mask], 70)) if np.any(mask) else 0.0
    hot = mask & (mag >= max(thr, 2.0))

    ys, xs = np.where(mask)
    if len(xs) == 0:
        raise RuntimeError("no opaque pixels — fail-closed")

    def grid_on(region: np.ndarray, step: int) -> list[tuple[float, float]]:
        ry, rx = np.where(region)
        if len(rx) == 0:
            return []
        out = []
        for y in range(int(ry.min()), int(ry.max()) + 1, step):
            for x in range(int(rx.min()), int(rx.max()) + 1, step):
                if region[y, x]:
                    out.append((float(x), float(y)))
        return out

    # Hot (high motion) first at fine step, then body at coarser step.
    fine = max(4, int(min_dist // 2) or 4)
    coarse = max(8, int(min_dist))
    merged = grid_on(hot, fine) + grid_on(mask & ~hot, coarse)

    # Corners add texture anchors.
    g = gray.copy()
    g[~mask] = 0
    corners = cv2.goodFeaturesToTrack(
        g,
        maxCorners=max_points // 3,
        qualityLevel=0.01,
        minDistance=float(min_dist),
        blockSize=7,
        mask=(mask.astype(np.uint8) * 255),
    )
    if corners is not None:
        merged = corners.reshape(-1, 2).astype(np.float32).tolist() + merged

    seen = set()
    out = []
    for x, y in merged:
        key = (int(round(x / 2.0)), int(round(y / 2.0)))
        if key in seen:
            continue
        seen.add(key)
        out.append((x, y))
        if len(out) >= max_points:
            break
    if not out:
        raise RuntimeError("no seed points — fail-closed")
    return np.asarray(out, dtype=np.float32)


def _track_clip(
    grays: list[np.ndarray],
    masks: list[np.ndarray],
    rgbas: list[np.ndarray],
    pts0: np.ndarray,
    *,
    min_span: int,
    reacq_search: int,
    patch_half: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, dict]:
    """Partial trajectories.

    Returns:
      traj (T,N,2), start_frame (N,), end_frame (N,) exclusive, stats
    A track is usable if (end-start) >= min_span.
    """
    t_count = len(grays)
    n = pts0.shape[0]
    traj = np.full((t_count, n, 2), np.nan, dtype=np.float32)
    traj[0] = pts0
    start = np.zeros(n, dtype=np.int32)
    end = np.full(n, t_count, dtype=np.int32)  # exclusive; shrink when dead
    alive = np.ones(n, dtype=bool)
    patches: list[np.ndarray | None] = [_extract_patch(grays[0], float(x), float(y), patch_half) for x, y in pts0]
    reacq_hits = 0
    flows = [_farneback(grays[i], grays[i + 1]) for i in range(t_count - 1)]

    for ti in range(t_count - 1):
        p_prev = traj[ti].copy()
        p_next = _sample_flow(flows[ti], np.nan_to_num(p_prev, nan=0.0))
        still = alive.copy()
        for i in np.where(still)[0]:
            if not np.isfinite(p_prev[i, 0]):
                alive[i] = False
                end[i] = ti
                continue
            x, y = float(p_next[i, 0]), float(p_next[i, 1])
            xi, yi = int(round(x)), int(round(y))
            ok = (
                0 <= yi < masks[ti + 1].shape[0]
                and 0 <= xi < masks[ti + 1].shape[1]
                and bool(masks[ti + 1][yi, xi])
            )
            if not ok:
                # NCC reacquire — first-class path for tips / large jumps.
                patch = patches[i]
                hit = None
                if patch is not None:
                    hit = _ncc_reacquire(
                        grays[ti + 1],
                        masks[ti + 1],
                        patch,
                        (float(p_prev[i, 0]), float(p_prev[i, 1])),
                        search=reacq_search,
                    )
                    if hit is None:
                        # Also search around Farneback prediction.
                        hit = _ncc_reacquire(
                            grays[ti + 1],
                            masks[ti + 1],
                            patch,
                            (x, y),
                            search=reacq_search,
                        )
                if hit is None:
                    alive[i] = False
                    end[i] = ti + 1  # last valid frame index exclusive = ti+1 means valid through ti
                    # end exclusive: valid frames start..ti inclusive → end=ti+1 already; if died before landing, end=ti+1 with last at ti
                    end[i] = ti + 1
                    continue
                x, y, _score = hit
                reacq_hits += 1
                p_next[i, 0], p_next[i, 1] = x, y
                new_patch = _extract_patch(grays[ti + 1], x, y, patch_half)
                if new_patch is not None:
                    patches[i] = new_patch
            else:
                # Refresh patch occasionally while healthy.
                if patches[i] is None or (ti % 2 == 0):
                    new_patch = _extract_patch(grays[ti + 1], x, y, patch_half)
                    if new_patch is not None:
                        patches[i] = new_patch
            traj[ti + 1, i, 0] = x
            traj[ti + 1, i, 1] = y

        # Tracks that died: leave NaNs after end.
        for i in np.where(~alive)[0]:
            if end[i] <= ti:
                traj[ti + 1, i] = np.nan

    # Fix end for tracks that stayed alive.
    for i in range(n):
        if alive[i]:
            end[i] = t_count
        # Ensure at least start position exists
        if end[i] <= start[i]:
            end[i] = start[i] + 1

    usable = (end - start) >= int(min_span)
    stats = {
        "reacquireHits": int(reacq_hits),
        "usableTracks": int(usable.sum()),
        "seedTracks": int(n),
        "fullClipTracks": int(np.sum(end == t_count)),
        "partialTracks": int(np.sum(usable & (end < t_count))),
    }
    _ = rgbas  # reserved for color-affinity reacquire later
    return traj, start, end, stats


def _trajectory_features(
    traj: np.ndarray,
    start: np.ndarray,
    end: np.ndarray,
    usable: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Features for usable tracks. Also returns travel magnitude weights and f0 xy."""
    idxs = np.where(usable)[0]
    if idxs.size == 0:
        raise RuntimeError("zero usable tracks (min_span) — fail-closed")
    feats = []
    weights = []
    xy0 = []
    t_count = traj.shape[0]
    for i in idxs:
        s, e = int(start[i]), int(end[i])
        path = traj[s:e, i]
        if path.shape[0] < 2 or not np.isfinite(path).all():
            # should not happen for usable
            path = traj[s : s + 1, i]
        travel = path[-1] - path[0]
        mag = float(np.linalg.norm(travel))
        # Per-step mean direction (pad to fixed length via summary, not full T).
        steps = path[1:] - path[:-1]
        step_mag = np.linalg.norm(steps, axis=1) if len(steps) else np.zeros(1)
        peak = float(step_mag.max()) if len(step_mag) else 0.0
        mean_step = steps.mean(axis=0) if len(steps) else np.zeros(2)
        life = float(e - s) / float(t_count)
        # Emphasize direction of total travel; log-scale magnitude so tips aren't only cluster.
        dir_vec = travel / (mag + 1e-6)
        feat = np.array(
            [
                dir_vec[0],
                dir_vec[1],
                np.log1p(mag) / 6.0,
                np.log1p(peak) / 6.0,
                mean_step[0] / 40.0,
                mean_step[1] / 40.0,
                life,
                path[0, 0] / 1000.0,
                path[0, 1] / 1000.0,
            ],
            dtype=np.float64,
        )
        feats.append(feat)
        # Weight: high travel + short life still counts (tip-like).
        weights.append(1.0 + mag / 20.0 + peak / 25.0)
        xy0.append(path[0].astype(np.float64))
    return np.vstack(feats), np.asarray(weights), np.vstack(xy0)


def _kmeans_weighted(features: np.ndarray, weights: np.ndarray, k: int, *, seed: int, iters: int = 50) -> np.ndarray:
    rng = np.random.default_rng(seed)
    n = features.shape[0]
    k = int(min(k, n))
    w = weights / (weights.sum() + 1e-12)
    centers = np.empty((k, features.shape[1]), dtype=np.float64)
    centers[0] = features[int(rng.choice(n, p=w))]
    closest = np.full(n, np.inf)
    for c in range(1, k):
        d2 = ((features - centers[c - 1]) ** 2).sum(axis=1)
        closest = np.minimum(closest, d2)
        probs = closest * weights
        probs = probs / (probs.sum() + 1e-12)
        centers[c] = features[int(rng.choice(n, p=probs))]
    labels = np.zeros(n, dtype=np.int32)
    for _ in range(iters):
        d2 = ((features[:, None, :] - centers[None, :, :]) ** 2).sum(axis=2)
        new_labels = np.argmin(d2, axis=1).astype(np.int32)
        if np.array_equal(new_labels, labels):
            break
        labels = new_labels
        for c in range(k):
            m = labels == c
            if not np.any(m):
                centers[c] = features[int(rng.choice(n, p=w))]
            else:
                ww = weights[m][:, None]
                centers[c] = (features[m] * ww).sum(axis=0) / (ww.sum() + 1e-12)
    return labels


def _pick_k(features: np.ndarray, weights: np.ndarray, *, k_min: int, k_max: int, seed: int) -> int:
    n = features.shape[0]
    k_max = int(min(k_max, n))
    k_min = int(min(k_min, k_max))
    ks = list(range(k_min, k_max + 1))
    inertias = []
    for k in ks:
        labels = _kmeans_weighted(features, weights, k, seed=seed)
        centers = []
        for c in range(k):
            m = labels == c
            if np.any(m):
                ww = weights[m][:, None]
                centers.append((features[m] * ww).sum(axis=0) / (ww.sum() + 1e-12))
            else:
                centers.append(features[0])
        centers = np.vstack(centers)
        d2 = ((features - centers[labels]) ** 2).sum(axis=1)
        inertias.append(float((d2 * weights).sum()))
    best_k, best_drop = ks[0], -1.0
    for i in range(1, len(ks)):
        drop = (inertias[i - 1] - inertias[i]) / (inertias[i - 1] + 1e-9)
        if drop > best_drop:
            best_drop = drop
            best_k = ks[i]
    return int(best_k)


def _hinge_candidates(xy0: np.ndarray, labels: np.ndarray, travels: np.ndarray, *, max_pair_dist: float, min_rel: float) -> list[dict]:
    parts = sorted(set(int(x) for x in labels.tolist()))
    hinges = []
    hid = 0
    for i, a in enumerate(parts):
        for b in parts[i + 1 :]:
            pa = xy0[labels == a]
            pb = xy0[labels == b]
            ca, cb = pa.mean(axis=0), pb.mean(axis=0)
            dist = float(np.linalg.norm(ca - cb))
            if dist > max_pair_dist:
                continue
            sa = pa[:: max(1, len(pa) // 40)]
            sb = pb[:: max(1, len(pb) // 40)]
            best = None
            best_d = 1e18
            for p in sa:
                d = np.linalg.norm(sb - p, axis=1)
                j = int(np.argmin(d))
                if d[j] < best_d:
                    best_d = float(d[j])
                    best = 0.5 * (p + sb[j])
            if best is None or best_d > max_pair_dist * 0.55:
                continue
            ta = travels[labels == a].mean(axis=0)
            tb = travels[labels == b].mean(axis=0)
            rel = float(np.linalg.norm(ta - tb))
            if rel < min_rel:
                continue
            hinges.append(
                {
                    "id": f"hinge_{hid:02d}",
                    "partA": f"part_{a:02d}",
                    "partB": f"part_{b:02d}",
                    "x": float(best[0]),
                    "y": float(best[1]),
                    "partDistPx": dist,
                    "boundaryGapPx": best_d,
                    "relMotionPx": rel,
                    "travelA": [float(ta[0]), float(ta[1])],
                    "travelB": [float(tb[0]), float(tb[1])],
                }
            )
            hid += 1
    hinges.sort(key=lambda h: -h["relMotionPx"])
    return hinges


def _draw_overlay(rgba, xy0, labels, hinges, *, title: str, high_motion_mask: np.ndarray | None = None) -> Image.Image:
    im = Image.fromarray(rgba).convert("RGBA")
    draw = ImageDraw.Draw(im)
    r = max(2, min(im.size) // 220)
    if high_motion_mask is not None:
        # Subtle glow under high-motion seeds (tips/extremities).
        ys, xs = np.where(high_motion_mask)
        for x, y in zip(xs[::2], ys[::2]):
            draw.point((int(x), int(y)), fill=(255, 255, 255, 40))
    for i, (x, y) in enumerate(xy0):
        c = PART_COLORS[int(labels[i]) % len(PART_COLORS)]
        draw.ellipse([x - r, y - r, x + r, y + r], fill=c + (255,))
    for h in hinges:
        x, y = h["x"], h["y"]
        hr = r + 3
        draw.ellipse([x - hr, y - hr, x + hr, y + hr], outline=(255, 255, 255, 255), width=2)
        draw.ellipse([x - hr + 2, y - hr + 2, x + hr - 2, y + hr - 2], fill=(255, 140, 0, 255))
        draw.line([(x - hr - 2, y), (x + hr + 2, y)], fill=(255, 255, 255, 255), width=1)
        draw.line([(x, y - hr - 2), (x, y + hr + 2)], fill=(255, 255, 255, 255), width=1)
    draw.rectangle([0, 0, im.size[0], 28], fill=(0, 0, 0, 180))
    draw.text((8, 6), title, fill=(255, 255, 255, 255))
    return im


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--frames-dir", type=Path, default=DEFAULT_FRAMES)
    ap.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--max-points", type=int, default=1100)
    ap.add_argument("--min-distance", type=float, default=8.0)
    ap.add_argument("--min-span", type=int, default=2, help="Min frames a track must cover (partial OK)")
    ap.add_argument("--reacq-search", type=int, default=90)
    ap.add_argument("--patch-half", type=int, default=10)
    ap.add_argument("--k", type=int, default=0)
    ap.add_argument("--k-min", type=int, default=5)
    ap.add_argument("--k-max", type=int, default=12)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--min-usable-frac", type=float, default=0.12)
    ap.add_argument("--min-rel-motion", type=float, default=8.0)
    ap.add_argument("--max-part-pair-dist", type=float, default=160.0)
    args = ap.parse_args()

    frames_dir = args.frames_dir if args.frames_dir.is_absolute() else ROOT / args.frames_dir
    out_dir = args.out_dir if args.out_dir.is_absolute() else ROOT / args.out_dir
    paths = sorted(frames_dir.glob("frame_*.png"))
    if len(paths) < 2:
        numbered = [path for path in frames_dir.glob("*.png") if path.stem.isdigit()]
        if len(numbered) >= 2:
            paths = sorted(numbered, key=lambda path: int(path.stem))
    if len(paths) < 2:
        print(f"need >=2 frames in {frames_dir}", file=sys.stderr)
        return 2

    rgbas = [_load_rgba(p) for p in paths]
    grays = [cv2.cvtColor(im[:, :, :3], cv2.COLOR_RGB2GRAY) for im in rgbas]
    masks = [_opaque_mask(im[:, :, 3]) for im in rgbas]
    mag_max = np.zeros(grays[0].shape, dtype=np.float32)
    flow0 = _farneback(grays[0], grays[1])
    mag_max = np.maximum(mag_max, _flow_mag(flow0))
    for index in range(1, len(grays) - 1):
        mag_max = np.maximum(mag_max, _flow_mag(_farneback(grays[index], grays[index + 1])))
    hot0 = masks[0] & (mag_max >= max(float(np.percentile(mag_max[masks[0]], 70)), 2.0))

    pts0 = _seed_points(
        grays[0],
        masks[0],
        flow0,
        max_points=args.max_points,
        min_dist=args.min_distance,
    )
    traj, start, end, track_stats = _track_clip(
        grays,
        masks,
        rgbas,
        pts0,
        min_span=args.min_span,
        reacq_search=args.reacq_search,
        patch_half=args.patch_half,
    )
    usable = (end - start) >= int(args.min_span)
    usable_frac = float(usable.mean())
    if usable_frac < args.min_usable_frac:
        print(
            f"fail-closed: usable track frac {usable_frac:.1%} < {args.min_usable_frac}",
            file=sys.stderr,
        )
        return 1

    feats, weights, xy0 = _trajectory_features(traj, start, end, usable)
    idxs = np.where(usable)[0]
    # Per-track travel for hinges / report
    travels = []
    for i in idxs:
        s, e = int(start[i]), int(end[i])
        travels.append(traj[e - 1, i] - traj[s, i])
    travels = np.asarray(travels, dtype=np.float64)

    k = int(args.k) if args.k > 0 else _pick_k(feats, weights, k_min=args.k_min, k_max=args.k_max, seed=args.seed)
    labels = _kmeans_weighted(feats, weights, k, seed=args.seed)
    # Remap by size
    counts = {int(c): int(np.sum(labels == c)) for c in set(labels.tolist())}
    order = sorted(counts, key=lambda c: -counts[c])
    remap = {old: new for new, old in enumerate(order)}
    labels = np.array([remap[int(x)] for x in labels], dtype=np.int32)

    parts = []
    part_centroids = []  # [frame][part] -> [x,y] or null
    n_frames = int(traj.shape[0])
    n_parts = int(len(set(labels.tolist())))
    for fi in range(n_frames):
        row = []
        for pid in range(n_parts):
            m = labels == pid
            alive = m & (start[idxs] <= fi) & (end[idxs] > fi)
            if not np.any(alive):
                row.append(None)
                continue
            pts = traj[fi, idxs[alive]]
            row.append([float(pts[:, 0].mean()), float(pts[:, 1].mean())])
        part_centroids.append(row)

    for pid in sorted(set(labels.tolist())):
        m = labels == pid
        c0 = xy0[m].mean(axis=0)
        tr = travels[m].mean(axis=0)
        spans = (end[idxs[m]] - start[idxs[m]]).astype(np.float64)
        parts.append(
            {
                "id": f"part_{pid:02d}",
                "trackCount": int(m.sum()),
                "centroidF0": [float(c0[0]), float(c0[1])],
                "meanTravelPx": [float(tr[0]), float(tr[1])],
                "meanTravelMag": float(np.linalg.norm(tr)),
                "meanSpanFrames": float(spans.mean()),
                "partialFrac": float(np.mean(end[idxs[m]] < traj.shape[0])),
            }
        )

    hinges = _hinge_candidates(
        xy0,
        labels,
        travels,
        max_pair_dist=args.max_part_pair_dist,
        min_rel=args.min_rel_motion,
    )

    out_dir.mkdir(parents=True, exist_ok=True)
    tracks_path = out_dir / "tracks.npz"
    np.savez_compressed(
        tracks_path,
        traj=traj.astype(np.float32),
        start=start.astype(np.int32),
        end=end.astype(np.int32),
        usable=usable.astype(np.bool_),
        labels=labels.astype(np.int32),
        usable_idxs=idxs.astype(np.int32),
        xy0=xy0.astype(np.float32),
        travels=travels.astype(np.float32),
    )
    overlay = _draw_overlay(
        rgbas[0],
        xy0,
        labels,
        hinges,
        title=(
            f"parts={len(parts)} hinges={len(hinges)} usable={usable_frac:.0%} "
            f"partial={track_stats['partialTracks']} reacq={track_stats['reacquireHits']}"
        ),
        high_motion_mask=hot0,
    )
    overlay_path = out_dir / "frame_00_parts_hinges.png"
    overlay.save(overlay_path)

    # Coverage diagnostic: fraction of hot (high-flow) f0 pixels near a usable track.
    cover_r = 6
    covered = 0
    hot_ys, hot_xs = np.where(hot0)
    if len(hot_xs):
        for x, y in zip(hot_xs[::3], hot_ys[::3]):
            d = np.linalg.norm(xy0 - np.array([x, y]), axis=1)
            if float(d.min()) <= cover_r:
                covered += 1
        hot_cover = covered / max(1, len(hot_xs[::3]))
    else:
        hot_cover = 0.0

    report = {
        "ok": True,
        "method": "dense_flow_partial_tracks_ncc_reacquire_weighted_kmeans",
        "framesDir": str(frames_dir.resolve()),
        "frameCount": len(paths),
        "trackStats": track_stats,
        "usableFrac": usable_frac,
        "highMotionSeedCoverFrac": hot_cover,
        "partCount": len(parts),
        "parts": parts,
        "partCentroidsPerFrame": part_centroids,
        "hinges": hinges,
        "tracks": str(tracks_path.resolve()),
        "overlay": str(overlay_path.resolve()),
        "params": {
            "maxPoints": args.max_points,
            "minSpan": args.min_span,
            "reacqSearch": args.reacq_search,
            "k": k,
            "minRelMotionPx": args.min_rel_motion,
            "seed": args.seed,
        },
        "notes": (
            "Partial high-motion tracks are first-class (NCC reacquire + travel-weighted clustering). "
            "Topology-free parts/hinges; not a humanoid skeleton. "
            "tracks.npz + partCentroidsPerFrame feed mesh surface mapping / part DOFs."
        ),
        "proof": "generated artifact validated — partial-track articulation pilot; not gameplay proven",
    }
    report_path = out_dir / "articulation_report.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "ok": True,
                "parts": len(parts),
                "hinges": len(hinges),
                "usableFrac": round(usable_frac, 3),
                "partialTracks": track_stats["partialTracks"],
                "reacquireHits": track_stats["reacquireHits"],
                "highMotionSeedCoverFrac": round(hot_cover, 3),
                "overlay": str(overlay_path),
                "report": str(report_path),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
