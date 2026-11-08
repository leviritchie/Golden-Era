#!/usr/bin/env python3
"""
Track seeded joints across NN-upscaled sprites.

Primary: Lucas-Kanade + local NCC.
High-motion landmarks (WeaponTip): color + pattern reacquire when local track loses
large DEF jumps. No silent wrist_offset fabrication.

Fail-closed:
  - Seed joints must land on opaque pixels.
  - Core joints missing after track → exit 1.
  - Optional --overrides only for debug; not the default automation path.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "artifacts/hobgoblin_attack_pose_pipeline/out_sprite_motion_track_g11"
SRC = ROOT / "artifacts/hobgoblin_attack_pose_pipeline/source_attack_frames/canonical_group_11_nn_upscale"
SEED = OUT / "seed" / "seed_joints_f00.json"

REQUIRED = [
    "Nose",
    "Neck",
    "MidHip",
    "RShoulder",
    "RElbow",
    "RWrist",
    "WeaponTip",
    "LShoulder",
    "LElbow",
    "LWrist",
    "RHip",
    "RKnee",
    "RAnkle",
    "LHip",
    "LKnee",
    "LAnkle",
]

LK_PARAMS = dict(
    winSize=(31, 31),
    maxLevel=4,
    criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 40, 0.01),
)

REACQUIRE_JOINTS = {"WeaponTip"}


def _load_rgba(path: Path) -> np.ndarray:
    return np.asarray(Image.open(path).convert("RGBA"))


def _inside_alpha(alpha: np.ndarray, x: float, y: float) -> bool:
    xi, yi = int(round(x)), int(round(y))
    if yi < 0 or xi < 0 or yi >= alpha.shape[0] or xi >= alpha.shape[1]:
        return False
    return int(alpha[yi, xi]) >= 8


def _validate_seed_on_alpha(joints: dict, alpha: np.ndarray) -> list[str]:
    bad = []
    for name, j in joints.items():
        if not _inside_alpha(alpha, float(j["x"]), float(j["y"])):
            bad.append(f"{name}@({j['x']:.1f},{j['y']:.1f})")
    return bad


def _extract_patch(gray: np.ndarray, alpha: np.ndarray, x: float, y: float, half: int) -> np.ndarray | None:
    xi, yi = int(round(x)), int(round(y))
    h, w = gray.shape
    if yi - half < 0 or xi - half < 0 or yi + half >= h or xi + half >= w:
        return None
    if int(alpha[yi, xi]) < 8:
        return None
    patch = gray[yi - half : yi + half + 1, xi - half : xi + half + 1]
    if float(np.std(patch)) < 1e-3:
        return None
    return patch.copy()


def _ncc_at(gray: np.ndarray, tmpl: np.ndarray, cx: float, cy: float) -> float:
    h, w = tmpl.shape
    hh, hw = h // 2, w // 2
    x0, y0 = int(round(cx)) - hw, int(round(cy)) - hh
    x1, y1 = x0 + w, y0 + h
    if x0 < 0 or y0 < 0 or x1 > gray.shape[1] or y1 > gray.shape[0]:
        return -1.0
    patch = gray[y0:y1, x0:x1].astype(np.float32)
    a = tmpl.astype(np.float32)
    if patch.shape != a.shape:
        return -1.0
    a = a - a.mean()
    b = patch - patch.mean()
    den = float(np.sqrt(np.sum(a * a) * np.sum(b * b)) + 1e-6)
    return float(np.sum(a * b) / den)


def _template_match(
    prev_gray: np.ndarray,
    next_gray: np.ndarray,
    next_alpha: np.ndarray,
    x: float,
    y: float,
    *,
    patch: int = 21,
    search: int = 80,
) -> tuple[float, float, float] | None:
    h, w = prev_gray.shape
    half = patch // 2
    xi, yi = int(round(x)), int(round(y))
    x0, y0 = xi - half, yi - half
    x1, y1 = x0 + patch, y0 + patch
    if x0 < 0 or y0 < 0 or x1 > w or y1 > h:
        return None
    tmpl = prev_gray[y0:y1, x0:x1]
    if tmpl.size == 0 or float(np.std(tmpl)) < 1e-3:
        return None
    sx0 = max(0, xi - search)
    sy0 = max(0, yi - search)
    sx1 = min(w, xi + search)
    sy1 = min(h, yi + search)
    roi = next_gray[sy0:sy1, sx0:sx1]
    if roi.shape[0] < patch or roi.shape[1] < patch:
        return None
    res = cv2.matchTemplate(roi, tmpl, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(res)
    nx = sx0 + max_loc[0] + half
    ny = sy0 + max_loc[1] + half
    if not _inside_alpha(next_alpha, nx, ny):
        return None
    return float(nx), float(ny), float(max_val)


def _gold_mask(rgba: np.ndarray) -> np.ndarray:
    rgb = rgba[:, :, :3].astype(np.float32)
    a = rgba[:, :, 3]
    r, g, b = rgb[:, :, 0], rgb[:, :, 1], rgb[:, :, 2]
    return (
        (r > 160)
        & (g > 120)
        & (b < 185)
        & (((r + g) * 0.5) > (b + 30))
        & (a >= 200)
        & (r >= g * 0.85)
    )


def _silver_blade_mask(rgba: np.ndarray) -> np.ndarray:
    """Bright low-chroma metal (sword blade). Explicitly excludes gold trim."""
    rgb = rgba[:, :, :3].astype(np.float32)
    a = rgba[:, :, 3]
    r, g, b = rgb[:, :, 0], rgb[:, :, 1], rgb[:, :, 2]
    mx = np.maximum(np.maximum(r, g), b)
    mn = np.minimum(np.minimum(r, g), b)
    chroma = mx - mn
    gold = _gold_mask(rgba)
    return (
        (a >= 180)
        & (mx >= 145.0)
        & (chroma <= 55.0)
        & (np.abs(r - g) <= 35.0)
        & (np.abs(g - b) <= 40.0)
        & (~gold)
    )


def _tip_color_mask(rgba: np.ndarray, tip_profile: str) -> np.ndarray:
    if tip_profile == "silver_blade":
        return _silver_blade_mask(rgba)
    if tip_profile == "gold":
        return _gold_mask(rgba)
    raise ValueError(f"unsupported tip_profile={tip_profile!r}")


def _color_components(
    rgba: np.ndarray, tip_profile: str, min_area: int = 12
) -> list[tuple[float, float, int, int]]:
    """Returns (cx, cy, area, label_id) for tip-profile color mask components."""
    mask = _tip_color_mask(rgba, tip_profile).astype(np.uint8) * 255
    n, _lab, stats, cent = cv2.connectedComponentsWithStats(mask, 8)
    out: list[tuple[float, float, int, int]] = []
    for i in range(1, n):
        area = int(stats[i, cv2.CC_STAT_AREA])
        if area < min_area:
            continue
        out.append((float(cent[i][0]), float(cent[i][1]), area, int(i)))
    return out


def _helmet_exclude_label(
    comps: list[tuple[float, float, int, int]],
    nose_xy: tuple[float, float] | None,
    *,
    tip_profile: str,
    max_dist: float = 130.0,
    min_area: int = 700,
) -> int | None:
    """Largest near-nose blob to exclude (helmet gold / silver helm plate)."""
    if nose_xy is None:
        return None
    area_gate = 400 if tip_profile == "silver_blade" else min_area
    best: tuple[int, int] | None = None  # (area, label)
    for cx, cy, area, lab in comps:
        if area < area_gate:
            continue
        if float(np.hypot(cx - nose_xy[0], cy - nose_xy[1])) > max_dist:
            continue
        if best is None or area > best[0]:
            best = (area, lab)
    return None if best is None else best[1]


def _seed_tip_area(rgba: np.ndarray, tip_xy: tuple[float, float], tip_profile: str = "gold") -> float:
    comps = _color_components(rgba, tip_profile, min_area=8)
    default = 80.0 if tip_profile == "silver_blade" else 250.0
    if not comps:
        return default
    tx, ty = tip_xy
    best = min(comps, key=lambda c: float(np.hypot(c[0] - tx, c[1] - ty)))
    if float(np.hypot(best[0] - tx, best[1] - ty)) > 28.0:
        return default
    return float(max(best[2], 40 if tip_profile == "silver_blade" else 80))


def _color_affinity(
    rgba: np.ndarray, cx: float, cy: float, mean_rgb: np.ndarray, tip_profile: str = "gold"
) -> float:
    a = rgba[:, :, 3]
    rgb = rgba[:, :, :3].astype(np.float32)
    xi, yi = int(round(cx)), int(round(cy))
    if yi < 0 or xi < 0 or yi >= a.shape[0] or xi >= a.shape[1] or a[yi, xi] < 8:
        return 0.0
    pix = rgb[yi, xi]
    r, g, b = float(pix[0]), float(pix[1]), float(pix[2])
    if tip_profile == "silver_blade":
        mx = max(r, g, b)
        mn = min(r, g, b)
        if mx < 130.0 or (mx - mn) > 70.0:
            return 0.0
        if abs(r - g) > 45.0 or abs(g - b) > 50.0:
            return 0.0
        if r > 160 and g > 120 and b < 185 and ((r + g) * 0.5) > (b + 30):
            return 0.0
    else:
        if not (r > 150 and g > 110 and b < 190):
            return 0.0
    d = float(np.linalg.norm(pix - mean_rgb))
    return float(np.exp(-d / 55.0))


def _reacquire_landmark(
    rgba: np.ndarray,
    gray: np.ndarray,
    *,
    seed_tmpl: np.ndarray,
    prev_tmpl: np.ndarray,
    mean_rgb: np.ndarray,
    last_xy: tuple[float, float],
    pred_xy: tuple[float, float],
    nose_xy: tuple[float, float] | None,
    wrist_xy: tuple[float, float] | None,
    mid_xy: tuple[float, float] | None,
    seed_tip_wrist_len: float,
    seed_tip_area: float = 250.0,
    ankle_y: float | None = None,
    min_score: float = 0.55,
    tip_profile: str = "gold",
) -> tuple[float, float, float, str] | None:
    """
    Color-component + pattern reacquire for long-travel landmarks.

    tip_profile=gold: mid-sized peripheral gold (mace head); excludes helmet gold.
    tip_profile=silver_blade: bright low-chroma metal tip; prefers far-from-wrist
    candidates along the predicted blade axis. Hard-requires profile color pixels.
    Returns (x, y, score, method) or None.
    """
    a = rgba[:, :, 3]
    half = seed_tmpl.shape[0] // 2
    comps = _color_components(rgba, tip_profile, min_area=6 if tip_profile == "silver_blade" else 10)
    helmet_lab = _helmet_exclude_label(comps, nose_xy, tip_profile=tip_profile)
    color = _tip_color_mask(rgba, tip_profile)
    lab = None
    if helmet_lab is not None:
        _n, lab, _stats, _cent = cv2.connectedComponentsWithStats(color.astype(np.uint8) * 255, 8)

    def _on_tip_color(cx: float, cy: float) -> bool:
        xi, yi = int(round(cx)), int(round(cy))
        if yi < 0 or xi < 0 or yi >= color.shape[0] or xi >= color.shape[1]:
            return False
        return bool(color[yi, xi])

    cands: list[tuple[float, float, float]] = []  # cx, cy, area
    for cx, cy, area, lab_i in comps:
        if helmet_lab is not None and lab_i == helmet_lab:
            continue
        cands.append((cx, cy, float(area)))

    # Seed-template NCC peaks — only on tip-profile color.
    res = cv2.matchTemplate(gray, seed_tmpl, cv2.TM_CCOEFF_NORMED).astype(np.float32)
    work = res.copy()
    for _ in range(30):
        _, v, _, loc = cv2.minMaxLoc(work)
        if v < 0.20:
            break
        x, y = loc
        cx, cy = float(x + half), float(y + half)
        work[max(0, y - 14) : y + 15, max(0, x - 14) : x + 15] = -1.0
        if not _inside_alpha(a, cx, cy) or not _on_tip_color(cx, cy):
            continue
        xi, yi = int(round(cx)), int(round(cy))
        if lab is not None and helmet_lab is not None and 0 <= yi < lab.shape[0] and 0 <= xi < lab.shape[1]:
            if int(lab[yi, xi]) == helmet_lab:
                continue
        area = seed_tip_area
        if comps:
            nearest = min(comps, key=lambda c: float(np.hypot(c[0] - cx, c[1] - cy)))
            if float(np.hypot(nearest[0] - cx, nearest[1] - cy)) < 36.0:
                if helmet_lab is not None and nearest[3] == helmet_lab:
                    continue
                area = float(nearest[2])
        cands.append((cx, cy, area))

    if not cands:
        return None

    core = mid_xy if mid_xy is not None else nose_xy
    blade_dir = None
    if wrist_xy is not None:
        bx = last_xy[0] - wrist_xy[0]
        by = last_xy[1] - wrist_xy[1]
        bl = float(np.hypot(bx, by))
        if bl > 8.0:
            blade_dir = (bx / bl, by / bl)

    scored: list[tuple[float, float, float, float]] = []
    seen: set[tuple[int, int]] = set()
    for cx, cy, area in cands:
        key = (int(round(cx / 10.0)), int(round(cy / 10.0)))
        if key in seen:
            continue
        seen.add(key)
        if not _on_tip_color(cx, cy):
            continue
        if ankle_y is not None and cy > float(ankle_y) - 30.0:
            continue
        if nose_xy is not None:
            dn = float(np.hypot(cx - nose_xy[0], cy - nose_xy[1]))
            if dn < 18.0:
                continue
        ncc_s = _ncc_at(gray, seed_tmpl, cx, cy)
        ncc_p = _ncc_at(gray, prev_tmpl, cx, cy)
        col = _color_affinity(rgba, cx, cy, mean_rgb, tip_profile=tip_profile)
        if col < 0.05 and ncc_s < 0.15:
            continue

        log_ratio = float(np.log(max(area, 8.0) / max(seed_tip_area, 8.0)))
        area_pen = 0.22 * min(abs(log_ratio), 2.5)
        if area > max(seed_tip_area * 9.0, 2200.0):
            area_pen += 0.45
        if area < seed_tip_area * 0.15:
            area_pen += 0.25

        extent = 0.0
        core_pen = 0.0
        if core is not None:
            dc = float(np.hypot(cx - core[0], cy - core[1]))
            extent = 0.00135 * min(dc, 450.0)
            if dc < 75.0:
                core_pen = 0.60 * (1.0 - dc / 75.0)

        dl = float(np.hypot(cx - last_xy[0], cy - last_xy[1]))
        dp = float(np.hypot(cx - pred_xy[0], cy - pred_xy[1]))

        len_pen = 0.0
        blade_boost = 0.0
        if wrist_xy is not None:
            dw = float(np.hypot(cx - wrist_xy[0], cy - wrist_xy[1]))
            if dw < 28.0:
                len_pen = 0.40
            elif dw > 520.0:
                len_pen = 0.20
            if tip_profile == "silver_blade":
                len_target = max(seed_tip_wrist_len, 40.0)
                len_pen += 0.18 * min(abs(dw - len_target) / max(len_target, 1.0), 2.0)
                if blade_dir is not None:
                    vx = cx - wrist_xy[0]
                    vy = cy - wrist_xy[1]
                    vl = float(np.hypot(vx, vy)) + 1e-6
                    align = (vx / vl) * blade_dir[0] + (vy / vl) * blade_dir[1]
                    if align < 0.15:
                        len_pen += 0.35
                    else:
                        blade_boost = 0.28 * align + 0.00045 * dw

        score = (
            0.70 * max(ncc_s, 0.0)
            + 0.18 * max(ncc_p, 0.0)
            + 0.65 * col
            + extent
            + blade_boost
            - area_pen
            - core_pen
            - len_pen
            - 0.00010 * min(dl, 600.0)
            - 0.00006 * min(dp, 600.0)
        )
        scored.append((score, cx, cy, max(ncc_s, ncc_p)))
    if not scored:
        return None
    scored.sort(reverse=True)
    best = scored[0]
    gate = 0.48 if tip_profile == "silver_blade" else min_score
    if best[0] < gate:
        return None
    return float(best[1]), float(best[2]), float(best[0]), f"reacq_color_ncc={best[0]:.3f}"


def _step_track(
    prev_gray: np.ndarray,
    next_gray: np.ndarray,
    next_rgba: np.ndarray,
    pts: np.ndarray,
    names: list[str],
    *,
    fb_thresh: float,
    min_ncc: float,
    allow_rigid_offsets: bool = False,
    high_motion_joints: set[str] | None = None,
    tip_state: dict | None = None,
) -> tuple[np.ndarray, np.ndarray, list[str]]:
    high = high_motion_joints or set()
    next_alpha = next_rgba[:, :, 3]
    jcount = pts.shape[0]
    p0 = pts.reshape(jcount, 1, 2).astype(np.float32)
    p1, st, _ = cv2.calcOpticalFlowPyrLK(prev_gray, next_gray, p0, None, **LK_PARAMS)
    methods = ["lost"] * jcount
    out = pts.copy()
    ok = np.zeros(jcount, dtype=bool)
    if p1 is None or st is None:
        p1 = p0.copy()
        st = np.zeros((jcount, 1), dtype=np.uint8)
    st = st.reshape(-1).astype(bool)
    p1 = p1.reshape(jcount, 2)

    p0b, st_b, _ = cv2.calcOpticalFlowPyrLK(
        next_gray, prev_gray, p1.reshape(jcount, 1, 2).astype(np.float32), None, **LK_PARAMS
    )
    if p0b is None or st_b is None:
        st_b = np.zeros((jcount, 1), dtype=np.uint8)
        p0b = p0.copy()
    st_b = st_b.reshape(-1).astype(bool)
    p0b = p0b.reshape(jcount, 2)

    name_to_i = {n: i for i, n in enumerate(names)}

    for j in range(jcount):
        name = names[j]
        hot = name in high
        search = 220 if hot else 100
        patch = 15 if hot else 21
        ncc_gate = (min_ncc - 0.08) if hot else min_ncc
        use_lk = False
        if st[j] and st_b[j]:
            fb = float(np.linalg.norm(p0b[j] - pts[j]))
            fb_lim = fb_thresh * (1.45 if hot else 1.0)
            if fb <= fb_lim and _inside_alpha(next_alpha, p1[j, 0], p1[j, 1]):
                out[j] = p1[j]
                ok[j] = True
                methods[j] = f"lk_fb={fb:.2f}"
                use_lk = True
        if use_lk:
            continue
        tm = _template_match(
            prev_gray,
            next_gray,
            next_alpha,
            float(pts[j, 0]),
            float(pts[j, 1]),
            patch=patch,
            search=search,
        )
        if tm is not None and tm[2] >= ncc_gate:
            out[j] = (tm[0], tm[1])
            ok[j] = True
            methods[j] = f"ncc={tm[2]:.3f}"
        else:
            methods[j] = "lost"
            ok[j] = False

    # Color+pattern reacquire for long-travel landmarks (automated; not wrist_offset).
    if tip_state is not None and "WeaponTip" in name_to_i:
        tip_profile = str(tip_state.get("tip_profile") or "gold")
        ti = name_to_i["WeaponTip"]
        # Reject local tip hits that drifted onto body color / collapsed shaft length.
        if ok[ti]:
            ncc_seed = _ncc_at(next_gray, tip_state["seed_tmpl"], float(out[ti, 0]), float(out[ti, 1]))
            col = _color_affinity(
                next_rgba,
                float(out[ti, 0]),
                float(out[ti, 1]),
                tip_state["mean_rgb"],
                tip_profile=tip_profile,
            )
            tip_mask = _tip_color_mask(next_rgba, tip_profile)
            xi, yi = int(round(float(out[ti, 0]))), int(round(float(out[ti, 1])))
            on_tip = 0 <= yi < tip_mask.shape[0] and 0 <= xi < tip_mask.shape[1] and bool(tip_mask[yi, xi])
            wrist_xy = None
            if "RWrist" in name_to_i:
                wi = name_to_i["RWrist"]
                wrist_xy = (float(out[wi, 0] if ok[wi] else pts[wi, 0]), float(out[wi, 1] if ok[wi] else pts[wi, 1]))
            len_ok = True
            if wrist_xy is not None:
                dw = float(np.hypot(out[ti, 0] - wrist_xy[0], out[ti, 1] - wrist_xy[1]))
                # Local tip on the grip / shaft is not the tip.
                if dw < 26.0:
                    len_ok = False
            nose_too_close = False
            if "Nose" in name_to_i:
                ni = name_to_i["Nose"]
                nx = float(out[ni, 0] if ok[ni] else pts[ni, 0])
                ny = float(out[ni, 1] if ok[ni] else pts[ni, 1])
                if float(np.hypot(out[ti, 0] - nx, out[ti, 1] - ny)) < 18.0:
                    nose_too_close = True
            mid_too_close = False
            if "MidHip" in name_to_i:
                mi = name_to_i["MidHip"]
                mx = float(out[mi, 0] if ok[mi] else pts[mi, 0])
                my = float(out[mi, 1] if ok[mi] else pts[mi, 1])
                if float(np.hypot(out[ti, 0] - mx, out[ti, 1] - my)) < 55.0 and ncc_seed < 0.35:
                    mid_too_close = True
            if (not on_tip) or (ncc_seed < 0.20 and col < 0.12) or (not len_ok) or nose_too_close or mid_too_close:
                ok[ti] = False
                methods[ti] = "lost_local_reject"
        # Always consider color/pattern reacquire; keep the better of local vs reacq.
        local_xy = (float(out[ti, 0]), float(out[ti, 1])) if ok[ti] else None
        local_method = methods[ti] if ok[ti] else None
        nose = None
        wrist = None
        mid = None
        ankle_y = None
        if "Nose" in name_to_i:
            ni = name_to_i["Nose"]
            nose = (float(out[ni, 0] if ok[ni] else pts[ni, 0]), float(out[ni, 1] if ok[ni] else pts[ni, 1]))
        if "RWrist" in name_to_i:
            wi = name_to_i["RWrist"]
            wrist = (float(out[wi, 0] if ok[wi] else pts[wi, 0]), float(out[wi, 1] if ok[wi] else pts[wi, 1]))
        if "MidHip" in name_to_i:
            mi = name_to_i["MidHip"]
            mid = (float(out[mi, 0] if ok[mi] else pts[mi, 0]), float(out[mi, 1] if ok[mi] else pts[mi, 1]))
        for an in ("RAnkle", "LAnkle"):
            if an in name_to_i:
                ai = name_to_i[an]
                ay = float(out[ai, 1] if ok[ai] else pts[ai, 1])
                ankle_y = ay if ankle_y is None else max(ankle_y, ay)
        last = (float(pts[ti, 0]), float(pts[ti, 1]))
        vel = tip_state.get("vel", (0.0, 0.0))
        pred = (last[0] + float(vel[0]), last[1] + float(vel[1]))
        hit = _reacquire_landmark(
            next_rgba,
            next_gray,
            seed_tmpl=tip_state["seed_tmpl"],
            prev_tmpl=tip_state["prev_tmpl"],
            mean_rgb=tip_state["mean_rgb"],
            last_xy=last,
            pred_xy=pred,
            nose_xy=nose,
            wrist_xy=wrist,
            mid_xy=mid,
            seed_tip_wrist_len=float(tip_state["seed_len"]),
            seed_tip_area=float(tip_state.get("seed_area", 250.0)),
            ankle_y=ankle_y,
            tip_profile=tip_profile,
        )
        if hit is not None:
            take_reacq = (not ok[ti]) or (hit[2] >= 0.62)
            if take_reacq:
                out[ti] = (hit[0], hit[1])
                ok[ti] = True
                methods[ti] = hit[3]
                tip_state["vel"] = (hit[0] - last[0], hit[1] - last[1])
                # Only refresh prev template on strong seed-NCC hits (limit drift lock).
                ncc_keep = _ncc_at(next_gray, tip_state["seed_tmpl"], hit[0], hit[1])
                if ncc_keep >= 0.28:
                    new_patch = _extract_patch(next_gray, next_alpha, hit[0], hit[1], tip_state["half"])
                    if new_patch is not None:
                        tip_state["prev_tmpl"] = new_patch
        if ok[ti] and methods[ti] == local_method and local_xy is not None:
            ncc_keep = _ncc_at(next_gray, tip_state["seed_tmpl"], float(out[ti, 0]), float(out[ti, 1]))
            if ncc_keep >= 0.28:
                new_patch = _extract_patch(next_gray, next_alpha, out[ti, 0], out[ti, 1], tip_state["half"])
                if new_patch is not None:
                    tip_state["prev_tmpl"] = new_patch
            tip_state["vel"] = (float(out[ti, 0] - pts[ti, 0]), float(out[ti, 1] - pts[ti, 1]))
        elif not ok[ti]:
            methods[ti] = "lost"

    if allow_rigid_offsets:
        if "WeaponTip" in name_to_i and "RWrist" in name_to_i:
            ti = name_to_i["WeaponTip"]
            wi = name_to_i["RWrist"]
            if not ok[ti] and ok[wi]:
                offset = pts[ti] - pts[wi]
                tip = out[wi] + offset
                out[ti] = tip
                ok[ti] = True
                methods[ti] = "wrist_offset"
        if "Neck" in name_to_i and "Nose" in name_to_i:
            ni = name_to_i["Neck"]
            oi = name_to_i["Nose"]
            if not ok[ni] and ok[oi]:
                offset = pts[ni] - pts[oi]
                out[ni] = out[oi] + offset
                ok[ni] = True
                methods[ni] = "nose_offset"
    return out, ok, methods


def _anatomical_drop(joints: dict[str, dict], *, names: list[str]) -> list[str]:
    dropped: list[str] = []

    def vis(n: str) -> bool:
        return n in joints and bool(joints[n].get("visible", False))

    def xy(n: str) -> np.ndarray:
        return np.array([joints[n]["x"], joints[n]["y"]], dtype=np.float64)

    for side in ("R", "L"):
        s, e, w = f"{side}Shoulder", f"{side}Elbow", f"{side}Wrist"
        if not (vis(s) and vis(e) and vis(w)):
            continue
        if joints[e].get("method") == "keyframe_override":
            continue
        ps, pe, pw = xy(s), xy(e), xy(w)
        se = pe - ps
        sw = pw - ps
        se_len = float(np.linalg.norm(se))
        sw_len = float(np.linalg.norm(sw))
        ew_len = float(np.linalg.norm(pw - pe))
        if se_len > sw_len * 1.35 and sw_len > 8.0:
            joints[e]["visible"] = False
            joints[e]["score"] = 0.0
            joints[e]["method"] = "anatomical_drop"
            joints[e]["dropReason"] = "elbow_beyond_wrist"
            dropped.append(e)
            continue
        if se_len > 8.0 and ew_len > 8.0 and sw_len > 8.0:
            t = float(np.clip(np.dot(se, sw) / (sw_len * sw_len + 1e-8), 0.0, 1.0))
            proj = ps + t * sw
            dist = float(np.linalg.norm(pe - proj))
            if dist > max(80.0, 0.85 * sw_len):
                joints[e]["visible"] = False
                joints[e]["score"] = 0.0
                joints[e]["method"] = "anatomical_drop"
                joints[e]["dropReason"] = "elbow_off_segment"
                dropped.append(e)
    _ = names
    return dropped


def _load_overrides(path: Path | None) -> dict[str, dict[int, dict]]:
    if path is None:
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    out: dict[str, dict[int, dict]] = {}
    for joint, frames in raw.items():
        if joint.startswith("_"):
            continue
        if not isinstance(frames, dict):
            raise RuntimeError(f"override joint {joint} must be a frame map")
        out[joint] = {}
        for fk, val in frames.items():
            fi = int(fk)
            if not isinstance(val, dict) or "x" not in val or "y" not in val:
                raise RuntimeError(f"override {joint}[{fk}] needs x/y")
            out[joint][fi] = {"x": float(val["x"]), "y": float(val["y"])}
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--seed", type=Path, default=SEED)
    ap.add_argument("--sprite-dir", type=Path, default=SRC)
    ap.add_argument("--out-dir", type=Path, default=OUT / "track")
    ap.add_argument("--fb-thresh", type=float, default=18.0)
    ap.add_argument("--min-ncc", type=float, default=0.28)
    ap.add_argument(
        "--allow-rigid-offsets",
        action="store_true",
        help="Unsafe: fabricate WeaponTip/Neck via wrist/nose offsets when track loses them.",
    )
    ap.add_argument(
        "--high-motion-joints",
        default="WeaponTip,RWrist,RElbow",
        help="Comma list: larger NCC search / looser FB / color reacquire.",
    )
    ap.add_argument(
        "--overrides",
        type=Path,
        default=None,
        help="Debug-only joint keyframe JSON. Not the default automation path.",
    )
    ap.add_argument(
        "--tip-profile",
        choices=("gold", "silver_blade"),
        default="gold",
        help="WeaponTip color reacquire profile. Use silver_blade for crusader sword.",
    )
    ap.add_argument(
        "--core-joints",
        default="Nose,Neck,MidHip,RWrist,WeaponTip",
        help="Comma list: must stay visible or track exits non-zero.",
    )
    args = ap.parse_args()

    seed = json.loads(args.seed.read_text(encoding="utf-8"))
    joints0 = seed["joints"]
    missing = [n for n in REQUIRED if n not in joints0]
    if missing:
        print(f"seed missing joints: {missing}", file=sys.stderr)
        return 2

    high_motion = {s.strip() for s in str(args.high_motion_joints).split(",") if s.strip()}
    overrides = _load_overrides(args.overrides)

    paths = sorted(args.sprite_dir.glob("frame_*.png"))
    if len(paths) < 2:
        print(f"need >=2 frames in {args.sprite_dir}", file=sys.stderr)
        return 2

    rgbas = [_load_rgba(p) for p in paths]
    grays = [cv2.cvtColor(im[:, :, :3], cv2.COLOR_RGB2GRAY) for im in rgbas]
    alphas = [im[:, :, 3] for im in rgbas]
    sw, sh = grays[0].shape[1], grays[0].shape[0]

    seed_bad = _validate_seed_on_alpha(joints0, alphas[0])
    if seed_bad:
        print(
            "fail-closed: seed joint(s) outside sprite alpha — fix seed, do not fabricate:\n  "
            + ", ".join(seed_bad),
            file=sys.stderr,
        )
        return 2

    names = list(REQUIRED)
    cur = np.array([[joints0[n]["x"], joints0[n]["y"]] for n in names], dtype=np.float64)

    tip_state = None
    if "WeaponTip" in names:
        half = 12
        tx, ty = float(joints0["WeaponTip"]["x"]), float(joints0["WeaponTip"]["y"])
        seed_tmpl = _extract_patch(grays[0], alphas[0], tx, ty, half)
        if seed_tmpl is None:
            print("fail-closed: WeaponTip seed patch empty/flat", file=sys.stderr)
            return 2
        rgb = rgbas[0][:, :, :3].astype(np.float32)
        a0 = alphas[0]
        yi, xi = int(round(ty)), int(round(tx))
        win = rgb[yi - half : yi + half + 1, xi - half : xi + half + 1]
        wm = a0[yi - half : yi + half + 1, xi - half : xi + half + 1] >= 8
        mean_rgb = win[wm].mean(axis=0) if np.any(wm) else rgb[yi, xi]
        wx, wy = float(joints0["RWrist"]["x"]), float(joints0["RWrist"]["y"])
        tip_state = {
            "half": half,
            "seed_tmpl": seed_tmpl,
            "prev_tmpl": seed_tmpl.copy(),
            "mean_rgb": mean_rgb.astype(np.float32),
            "seed_len": float(np.hypot(tx - wx, ty - wy)),
            "seed_area": _seed_tip_area(rgbas[0], (tx, ty), tip_profile=str(args.tip_profile)),
            "vel": (0.0, 0.0),
            "tip_profile": str(args.tip_profile),
        }

    frames_out = []
    joint_drop: dict[str, list[int]] = {n: [] for n in names}
    method_log: list[dict] = []
    override_hits: list[dict] = []

    for fi, path in enumerate(paths):
        prev_cur = cur.copy()
        if fi == 0:
            joints = {
                n: {
                    "x": float(cur[j, 0]),
                    "y": float(cur[j, 1]),
                    "score": 1.0,
                    "visible": True,
                    "dx": 0.0,
                    "dy": 0.0,
                    "method": "seed",
                }
                for j, n in enumerate(names)
            }
            method_log.append({"frameIndex": 0, "methods": {n: "seed" for n in names}})
        else:
            nxt, ok, methods = _step_track(
                grays[fi - 1],
                grays[fi],
                rgbas[fi],
                cur,
                names,
                fb_thresh=args.fb_thresh,
                min_ncc=args.min_ncc,
                allow_rigid_offsets=bool(args.allow_rigid_offsets),
                high_motion_joints=high_motion,
                tip_state=tip_state,
            )
            joints = {}
            for j, n in enumerate(names):
                if ok[j]:
                    joints[n] = {
                        "x": float(nxt[j, 0]),
                        "y": float(nxt[j, 1]),
                        "score": 1.0 if methods[j].startswith("lk") else 0.85,
                        "visible": True,
                        "dx": float(nxt[j, 0] - cur[j, 0]),
                        "dy": float(nxt[j, 1] - cur[j, 1]),
                        "method": methods[j],
                    }
                    cur[j] = nxt[j]
                else:
                    joints[n] = {
                        "x": float(cur[j, 0]),
                        "y": float(cur[j, 1]),
                        "score": 0.0,
                        "visible": False,
                        "dx": 0.0,
                        "dy": 0.0,
                        "method": "lost",
                        "dropReason": "track_lost",
                    }
                    joint_drop[n].append(fi)
            method_log.append({"frameIndex": fi, "methods": {n: methods[j] for j, n in enumerate(names)}})

        for n in names:
            if n not in overrides or fi not in overrides[n]:
                continue
            ov = overrides[n][fi]
            if not _inside_alpha(alphas[fi], ov["x"], ov["y"]):
                print(
                    f"fail-closed: override {n} frame {fi} outside alpha @({ov['x']:.1f},{ov['y']:.1f})",
                    file=sys.stderr,
                )
                return 2
            j = names.index(n)
            prev_x, prev_y = float(cur[j, 0]), float(cur[j, 1])
            cur[j, 0] = ov["x"]
            cur[j, 1] = ov["y"]
            joints[n] = {
                "x": float(ov["x"]),
                "y": float(ov["y"]),
                "score": 1.0,
                "visible": True,
                "dx": float(ov["x"] - prev_x),
                "dy": float(ov["y"] - prev_y),
                "method": "keyframe_override",
            }
            if fi in joint_drop.get(n, []):
                joint_drop[n] = [f for f in joint_drop[n] if f != fi]
            override_hits.append({"frameIndex": fi, "joint": n, "x": ov["x"], "y": ov["y"]})
            if method_log and method_log[-1]["frameIndex"] == fi:
                method_log[-1]["methods"][n] = "keyframe_override"

        anat = _anatomical_drop(joints, names=names)
        for n in anat:
            joint_drop[n].append(fi)
            j = names.index(n)
            if fi > 0:
                cur[j] = prev_cur[j]
                joints[n]["x"] = float(prev_cur[j, 0])
                joints[n]["y"] = float(prev_cur[j, 1])
                joints[n]["dx"] = 0.0
                joints[n]["dy"] = 0.0
            if method_log and method_log[-1]["frameIndex"] == fi:
                method_log[-1]["methods"][n] = "anatomical_drop"

        frames_out.append(
            {
                "frameIndex": fi,
                "ok": True,
                "path": str(path).replace("\\", "/"),
                "transform": {"srcWidth": sw, "srcHeight": sh, "pad": 0},
                "joints": joints,
            }
        )

    core = [s.strip() for s in str(args.core_joints).split(",") if s.strip()]
    if not core:
        raise SystemExit("--core-joints produced an empty list")
    errors = []
    for fr in frames_out:
        for c in core:
            if c not in fr["joints"] or not fr["joints"][c].get("visible"):
                errors.append(f"frame {fr['frameIndex']} core {c} not visible")

    args.out_dir.mkdir(parents=True, exist_ok=True)
    kpt = {
        "ok": len(errors) == 0,
        "method": "sprite_lk_ncc_color_reacquire",
        "tipProfile": str(args.tip_profile),
        "seed": str(args.seed).replace("\\", "/"),
        "fbThreshPx": args.fb_thresh,
        "minNcc": args.min_ncc,
        "allowRigidOffsets": bool(args.allow_rigid_offsets),
        "highMotionJoints": sorted(high_motion),
        "reacquireJoints": sorted(REACQUIRE_JOINTS),
        "coreJoints": core,
        "overrides": str(args.overrides).replace("\\", "/") if args.overrides else None,
        "overrideHits": override_hits,
        "frames": frames_out,
        "errors": errors,
        "proof": (
            "generated artifact validated — LK+NCC+color/pattern tip reacquire; not mocap. "
            "Rigid tip offsets disabled unless --allow-rigid-offsets."
        ),
    }
    kpt_path = args.out_dir / "keypoints.json"
    kpt_path.write_text(json.dumps(kpt, indent=2) + "\n", encoding="utf-8")

    summary = {
        "ok": kpt["ok"],
        "frameCount": len(frames_out),
        "fbThreshPx": args.fb_thresh,
        "minNcc": args.min_ncc,
        "droppedFramesByJoint": joint_drop,
        "methodLog": method_log,
        "overrideHits": override_hits,
        "errors": errors,
        "keypoints": str(kpt_path).replace("\\", "/"),
        "proof": "generated artifact validated — track report; not mocap",
    }
    (args.out_dir / "track_report.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {"ok": summary["ok"], "frames": len(frames_out), "errors": errors, "keypoints": str(kpt_path)},
            indent=2,
        )
    )
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
