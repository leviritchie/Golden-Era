"""Full-3D town lane: measured mechanical kinds for town_full3d_fx (wheel, track).

town_full3d_fx dispatches these kinds (KIND_FN) and keeps its own module doc as the kind index; this module holds the
measurements and the pieces they emit. Every kind needs exactly one explicit rect (native DEF px) and measures on the
DEF's own frames, composited (frames 1.. over frame 0):

  * wheel  a disc turning about a hub, possibly seen at a slant (an ellipse) and with its hub hidden behind a wall:
           the hub, the ellipse (minor / major ratio q, major-axis angle psi; searched only when the effect sets
           "tilt": true) and the step per frame are searched so that frame 0, turned about the hub by k steps, best
           correlates (NCC of the median-subtracted grey over the px that change) with frame k. The DEF loops, so a
           turn of n steps must bring the disc onto itself: the step is snapped to 360 j / (N n) (N-fold symmetry, the
           smallest N within WHEEL_SNAP_DEG of the measured step). The disc's texture is rebuilt in its own plane from
           every frame (each texel sampled where the frames show it, folded by the N-fold symmetry, median); the
           disc is drawn whole, so the footprint px the sprite leaves transparent (a hole, a clipped edge) are counted
           in the report. Emitted as a disc like the stronghold windmill's (catalog spinPeriod) in the tilted plane, so the
           ellipse comes from the geometry, plus a static front card of the px in the disc's footprint that never change
           (a wall in front of the disc).
  * track  a rigid part moving along a path and back (an elevator cage, a rod): part px = px that differ from the
           frames' median (a part that is absent from most frames), optionally within "colour"; per frame the part
           template is tracked by translation (and rotation up to "turnDeg", default 0) with the swing kind's
           occlusion-tolerant score; frames that show too little of the part (TRACK_VIS_SHARE of the most) take the
           pose interpolated round the loop between their visible neighbours. Emitted as an unlit card at the
           template's centroid with keyed poses (catalog keyPeriod / keyPose: x, z holder units and degrees per DEF
           frame, played linearly), plus the front card of the never-changing px its path crosses.

Each fit redraws every DEF frame from its model (plate + moving piece + front card) and fails closed unless the mean
max-channel |RGB| error over the px that change is at most MECH_GAIN_MAX x that of the static plate (the frames'
median: what a non-moving stand-in shows). The fit report carries both numbers. The static texture (static_plate)
gets, inside the rect, the px median over the frames that do not show the piece (wheel: over all frames).
Proof tier: generated artifact; motion is only seen in game (editor renders do not advance Animators).
"""
from __future__ import annotations

import math

import cv2
import numpy as np
from PIL import Image

MECH_GAIN_MAX = 0.85        # a model must redraw the DEF at most this fraction of the static plate's error
WHEEL_STEP_MAX_DEG = 45.0   # |step| searched per frame
WHEEL_SNAP_DEG = 0.25       # the loop snap may move the step by at most max(this, 10 % of the step)
WHEEL_Q = (0.9, 0.8, 0.7, 0.6, 0.5)   # tilt search (minor / major), only when the effect sets "tilt"
WHEEL_UP = 4                # texels per DEF px
WHEEL_N_MAX = 24            # largest symmetry order the loop snap may use
WHEEL_FRONT_PULL_M = 0.15   # front cards sit this much further in front than the moving piece
TRACK_VIS_SHARE = 0.25      # a frame shows the part when it has this share of the busiest frame's part px
TRACK_REACH_PX = 40         # default |translation| searched (effect "reachPx")
WHEEL_GPU_EPS = 1e-4        # cuda hub grid: GPU vs CPU score bound (measured 3e-8 on tbfacas3); cells within 2 x of the
                            # third-best GPU cell are re-scored on the CPU and the CPU score picks (town_gpu_mech)

_CACHE: dict = {}


def _fx():
    import town_full3d_fx as FX
    return FX


def _rect_stack(F, rect):
    FX = _fx()
    x0, y0, x1, y1 = rect
    h, w = F[0].shape[:2]
    if not (0 <= x0 < x1 <= w and 0 <= y0 < y1 <= h):
        raise SystemExit(f"town_full3d_mech: rect {list(rect)} leaves the DEF frame ({w}x{h} px)")
    C = FX.composite(F)
    S = np.stack([f[y0:y1, x0:x1, :3] for f in C]).astype(np.float32)
    op = C[0][y0:y1, x0:x1, 3] > 0
    ever = (np.ptp(S, 0).max(-1) > FX.CHANGE_THR) & op
    return S, op, ever


def _gate(lid: str, kind: str, rect, err: float, err0: float) -> None:
    if not err <= MECH_GAIN_MAX * err0:
        raise SystemExit(f"town_full3d_mech: {lid}: {kind} rect {list(rect)} does not redraw the DEF: model error "
                         f"{err:.2f} against the static plate's {err0:.2f} (need <= {MECH_GAIN_MAX} x): this part is "
                         f"not a {kind}")


# ------------------------------------------------------------------------------------------------ wheel
def ell_affine(cx, cy, q, psi, ang):
    """2x3 screen map: a disc whose screen image is an ellipse (minor / major q, major axis at psi rad, screen px, y
    down) turned by ang deg (+ = counter-clockwise on screen) about its hub (cx, cy)."""
    c, s = math.cos(psi), math.sin(psi)
    A = np.array([[c, -s], [s, c]]) @ np.diag([1.0, q])
    a = math.radians(ang)
    R = np.array([[math.cos(a), math.sin(a)], [-math.sin(a), math.cos(a)]])
    M = A @ R @ np.linalg.inv(A)
    t = np.array([cx, cy]) - M @ np.array([cx, cy])
    return np.hstack([M, t[:, None]]).astype(np.float32)


def _wheel_score(D, ev, ever, cx, cy, q, psi, s, ks) -> float:
    H, W = ever.shape
    out = []
    for k in ks:
        M = ell_affine(cx, cy, q, psi, s * k)
        r = cv2.warpAffine(D[0], M, (W, H), flags=cv2.INTER_LINEAR)
        m = (cv2.warpAffine(ev, M, (W, H), flags=cv2.INTER_LINEAR) > 0.5) & ever
        if m.sum() < 20:
            return -1.0
        a = r[m] - r[m].mean()
        b = D[k][m] - D[k][m].mean()
        out.append(float(a @ b / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-9)))
    return float(np.mean(out))


def snap_step(s: float, n: int, tol: float):
    """(N, j, step): the step whose n-frame turn is j / N of a turn (N-fold symmetric disc), smallest N within tol."""
    best = None
    for N in range(1, WHEEL_N_MAX + 1):
        for j in range(1, 73):
            v = math.copysign(360.0 * j / (N * n), s)
            if math.gcd(N, j) == 1 and abs(v - s) <= tol and (best is None or N < best[0]):
                best = (N, j, v)
    return best


def _wheel_tex(S, ever, op, cx, cy, q, psi, s, N):
    """Disc-plane texture (u along the major axis, v along the minor, WHEEL_UP texels / px) and its radius (px)."""
    n, H, W = S.shape[:3]
    ys, xs = np.nonzero(ever)
    c, sn = math.cos(psi), math.sin(psi)
    A = np.array([[c, -sn], [sn, c]]) @ np.diag([1.0, q])
    d = np.linalg.inv(A) @ np.stack([xs + 0.5 - cx, ys + 0.5 - cy])
    rmax = float(np.hypot(*d).max()) + 1.0
    up = WHEEL_UP
    g = (np.arange(int(math.ceil(2 * rmax * up))) + 0.5) / up - rmax
    U, V = np.meshgrid(g, g)
    uv = np.stack([U.ravel(), V.ravel()])
    P = 360.0 / N

    def at(ang, u):
        a = math.radians(ang)
        R = np.array([[math.cos(a), math.sin(a)], [-math.sin(a), math.cos(a)]])
        p = A @ (R @ u)
        return p[0] + cx, p[1] + cy

    inside = np.hypot(uv[0], uv[1]) <= rmax
    med = np.zeros((uv.shape[1], 3))
    keep = np.zeros(uv.shape[1], bool)
    for c0 in range(0, uv.shape[1], 4096):             # texel chunks: n x N samples each
        sl = slice(c0, c0 + 4096)
        samples = []
        for k in range(n):
            for j in range(N):
                px, py = at(s * k + j * P, uv[:, sl])
                ix, iy = np.floor(px).astype(int), np.floor(py).astype(int)
                ok = (ix >= 0) & (iy >= 0) & (ix < W) & (iy < H)
                vis = np.zeros(ok.shape, bool)
                vis[ok] = ever[iy[ok], ix[ok]]
                col = cv2.remap(S[k], (px - 0.5)[None].astype(np.float32), (py - 0.5)[None].astype(np.float32),
                                cv2.INTER_LINEAR)[0]
                samples.append(np.where(vis[:, None], col, np.nan))
        St = np.stack(samples)
        kk = np.isfinite(St[..., 0]).any(0) & inside[sl]
        keep[sl] = kk
        if kk.any():
            med[np.arange(uv.shape[1])[sl][kk]] = np.nanmedian(St[:, kk], 0)
    tex = np.zeros(U.shape + (4,), np.uint8)
    tex[..., :3] = med.reshape(U.shape + (3,)).round().clip(0, 255)
    tex[..., 3] = keep.reshape(U.shape) * 255
    return tex, rmax, A


def _wheel_redraw(S, ever, op, tex, rmax, A, cx, cy, s, plate):
    n, H, W = S.shape[:3]
    up = WHEEL_UP
    yy, xx = np.mgrid[0:H, 0:W]
    Ai = np.linalg.inv(A)
    tf = tex.astype(np.float32)
    err, err0 = [], []
    m = ever & op
    for k in range(n):
        a = math.radians(-s * k)
        R = np.array([[math.cos(a), math.sin(a)], [-math.sin(a), math.cos(a)]])
        d = R @ Ai @ np.stack([xx.ravel() + 0.5 - cx, yy.ravel() + 0.5 - cy])
        tu = ((d[0] + rmax) * up - 0.5).reshape(H, W).astype(np.float32)
        tv = ((d[1] + rmax) * up - 0.5).reshape(H, W).astype(np.float32)
        smp = cv2.remap(tf, tu, tv, cv2.INTER_LINEAR, borderValue=0)
        al = smp[..., 3:4] / 255.0
        img = plate * (1 - al) + smp[..., :3] * al
        err.append(float(np.abs(img - S[k]).max(-1)[m].mean()))
        err0.append(float(np.abs(plate - S[k]).max(-1)[m].mean()))
    return float(np.mean(err)), float(np.mean(err0))


def fit_wheel(F, rect, lid: str, e: dict, device: str | None = None) -> dict:
    """Wheel measurement (see the module doc). Rect-local px: {"hub", "q", "psiDeg", "step", "N", "tex" (disc-plane
    RGBA), "rmax", "front" (RGBA or None), "plate", "fit"}.

    device (else TOWN_FULL3D_DEVICE, else cuda): cuda scores the hub x step grid on the GPU (town_gpu_mech) and
    re-scores the near-best cells here, so the chosen fit is the cpu path's (no fallback; test_town_gpu_mech.py)."""
    import town_gpu_kernels as GK
    dev = GK.resolve_device(device)
    key = ("wheel", lid, tuple(rect), repr(sorted(e.items())))
    if key in _CACHE:
        return _CACHE[key]
    S, op, ever = _rect_stack(F, rect)
    n, H, W = S.shape[:3]
    if int(ever.sum()) < 20:
        raise SystemExit(f"town_full3d_mech: {lid}: wheel rect {list(rect)} has {int(ever.sum())} changing px")
    G = S.mean(-1)
    D = G - np.median(G, 0)
    ev = ever.astype(np.float32)
    ks = list(range(1, n)) if n <= 13 else sorted({int(round(v)) for v in np.linspace(1, n - 1, 12)})
    tilt = bool(e.get("tilt", False))
    steps = [v for v in np.arange(-WHEEL_STEP_MAX_DEG, WHEEL_STEP_MAX_DEG + 1e-6, 1.0) if abs(v) >= 0.5]
    # the hub may lie anywhere in the rect (hidden behind a wall)
    cells = [(cx, cy) for cx in np.arange(0.0, W + 1e-6, 2.0) for cy in np.arange(0.0, H + 1e-6, 2.0)]
    near, g = range(len(cells)), None
    if dev == "cuda":
        import town_gpu_mech as GM
        g = GM.wheel_grid_scores(D, ev, ever, cells, steps, ks)
        g3 = np.sort(g)[::-1][min(2, len(g) - 1)]
        near = [i for i in range(len(cells)) if g[i] >= g3 - 2 * WHEEL_GPU_EPS]
    cand = []
    for i in near:                                    # in grid order, so the stable sort below breaks ties as cpu
        cx, cy = cells[i]
        b = max((_wheel_score(D, ev, ever, cx, cy, 1.0, 0.0, s, ks), s) for s in steps)
        if g is not None and abs(b[0] - g[i]) > WHEEL_GPU_EPS:
            raise SystemExit(f"town_full3d_mech: {lid}: cuda hub score {g[i]:.6f} vs cpu {b[0]:.6f} at "
                             f"({cx}, {cy}) exceeds WHEEL_GPU_EPS; run with --device cpu and report")
        cand.append((b[0], cx, cy, 1.0, 0.0, b[1]))
    cand.sort(key=lambda c: -c[0])
    top = cand[:3]
    if tilt:
        more = []
        for _, cx, cy, _, _, s in top:
            for q in WHEEL_Q:
                for psi in range(0, 180, 15):
                    b = max((_wheel_score(D, ev, ever, cx, cy, q, math.radians(psi), ss, ks), ss)
                            for ss in np.arange(s - 4, s + 4.01, 1.0) if abs(ss) >= 0.5)
                    more.append((b[0], cx, cy, q, float(psi), b[1]))
        top = sorted(top + more, key=lambda c: -c[0])[:3]
    _, cx, cy, q, psi, s = top[0]
    cur = {"cx": cx, "cy": cy, "q": q, "psi": psi, "s": s}

    def f(p):
        if not (0.2 <= p["q"] <= 1.0) or abs(p["s"]) < 0.25:
            return -2.0
        return _wheel_score(D, ev, ever, p["cx"], p["cy"], p["q"], math.radians(p["psi"]), p["s"], ks)
    best = f(cur)
    stp = {"cx": 1.0, "cy": 1.0, "q": 0.05, "psi": 7.5, "s": 0.5}
    for _ in range(4):                                  # coordinate ascent, halving steps
        for kk in ["cx", "cy", "s"] + (["q", "psi"] if tilt else []):
            for d in (-1, 1):
                while True:
                    p = dict(cur)
                    p[kk] += d * stp[kk]
                    v = f(p)
                    if v > best + 1e-4:
                        best, cur = v, p
                    else:
                        break
        stp = {k: v / 2 for k, v in stp.items()}
    if abs(cur["s"]) >= WHEEL_STEP_MAX_DEG - 1:
        raise SystemExit(f"town_full3d_mech: {lid}: wheel step {cur['s']:.2f} deg reaches the search bound")
    sn = snap_step(cur["s"], n, max(WHEEL_SNAP_DEG, 0.1 * abs(cur["s"])))
    if sn is None:
        raise SystemExit(f"town_full3d_mech: {lid}: wheel step {cur['s']:.3f} deg x {n} frames is no whole fraction of "
                         f"a turn (the DEF loop would not close)")
    N, j, step = sn
    psi_r = math.radians(cur["psi"])
    tex, rmax, A = _wheel_tex(S, ever, op, cur["cx"], cur["cy"], cur["q"], psi_r, step, N)
    plate = np.median(S, 0)
    err, err0 = _wheel_redraw(S, ever, op, tex, rmax, A, cur["cx"], cur["cy"], step, plate)
    _gate(lid, "wheel", rect, err, err0)
    # front: px of the disc's footprint (ellipse, radius rmax) that never change and are opaque
    yy, xx = np.mgrid[0:H, 0:W]
    dd = np.linalg.inv(A) @ np.stack([xx.ravel() + 0.5 - cur["cx"], yy.ravel() + 0.5 - cur["cy"]])
    foot = (np.hypot(*dd) <= rmax + 1.0).reshape(H, W)
    hid = foot & ~ever & op
    front = None
    if hid.any():
        front = np.zeros((H, W, 4), np.uint8)
        front[..., :3] = S[0].round().clip(0, 255).astype(np.uint8)
        front[..., 3] = hid * 255
    x0, y0 = rect[0], rect[1]
    fit = {"method": "frame 0 turned about a searched hub onto every frame (NCC of the median-subtracted grey over "
                     "the changing px); step snapped to the loop's N-fold symmetry; texture rebuilt in the disc's plane",
           "nccScore": round(best, 3), "hubPx": [round(float(cur["cx"]) + x0, 2), round(float(cur["cy"]) + y0, 2)],
           "q": round(float(cur["q"]), 3), "psiDeg": round(float(cur["psi"]), 2), "tilt": tilt,
           "stepMeasuredDeg": round(float(cur["s"]), 3), "stepDeg": round(step, 4), "symmetryN": N, "loopTurnsOverN": j,
           "screenSense": "ccw" if step > 0 else "cw", "radiusPx": round(rmax, 2), "changingPx": int(ever.sum()),
           "footprintTransparentPx": int((foot & ~op).sum()), "frontPx": int(hid.sum()),
           "redrawMaeRgb": round(err, 2), "staticPlateMaeRgb": round(err0, 2)}
    out = {"hub": (cur["cx"], cur["cy"]), "q": cur["q"], "psiDeg": cur["psi"], "step": step, "N": N, "tex": tex,
           "rmax": rmax, "front": front, "plate": plate.round().clip(0, 255).astype(np.uint8), "fit": fit}
    _CACHE[key] = out
    return out


# ------------------------------------------------------------------------------------------------ track
def _rot(a, ang, piv):
    return cv2.warpAffine(a, cv2.getRotationMatrix2D(piv, ang, 1.0), a.shape[1::-1], flags=cv2.INTER_LINEAR)


def pose_matrix(dx, dy, ang, piv):
    """Rest pose -> frame pose: turn about piv by ang deg (+ = counter-clockwise on screen), then shift."""
    M = cv2.getRotationMatrix2D(piv, ang, 1.0)
    M[0, 2] += dx
    M[1, 2] += dy
    return M


def _track(B, T, piv, R, angs):
    """Per frame (dx, dy, ang): the swing kind's occlusion-tolerant score (2 cov - tot - template px on the part's
    path where this frame shows no part), integer translation by correlation, sub-px by the parabola vertex."""
    ever = np.stack(B).max(0)
    Ts = [_rot(T, a, piv) for a in angs]
    out = []
    for b in B:
        tot = float(b.sum())
        bg = ever * (1 - b)
        pb = cv2.copyMakeBorder(b, R, R, R, R, cv2.BORDER_CONSTANT, value=0)
        pg = cv2.copyMakeBorder(bg, R, R, R, R, cv2.BORDER_CONSTANT, value=0)
        best = None
        for a, Tr in zip(angs, Ts):
            sc = 2 * cv2.matchTemplate(pb, Tr, cv2.TM_CCORR) - tot - cv2.matchTemplate(pg, Tr, cv2.TM_CCORR)
            iy, ix = np.unravel_index(int(np.argmax(sc)), sc.shape)
            if best is None or sc[iy, ix] > best[0]:
                best = (float(sc[iy, ix]), ix, iy, a, sc)
        _, ix, iy, a, sc = best

        def vtx(lo, mid, hi):
            den = lo - 2 * mid + hi
            return 0.0 if den >= 0 else float(np.clip(0.5 * (lo - hi) / den, -0.5, 0.5))
        fx = vtx(sc[iy, ix - 1], sc[iy, ix], sc[iy, ix + 1]) if 0 < ix < 2 * R else 0.0
        fy = vtx(sc[iy - 1, ix], sc[iy, ix], sc[iy + 1, ix]) if 0 < iy < 2 * R else 0.0
        out.append((ix - R + fx, iy - R + fy, float(a), ix in (0, 2 * R) or iy in (0, 2 * R)))
    return out


def _part_masks(S, op, ever, sel):
    FX = _fx()
    med = np.median(S, 0)
    return [((np.abs(s - med).max(-1) > FX.CHANGE_THR) & FX.hsv_in(s, sel) & ever & op).astype(np.float32) for s in S]


def _plate_without(S, B):
    cov = np.stack([cv2.dilate(b, np.ones((3, 3), np.uint8)) > 0 for b in B])
    plate = np.median(S, 0)
    free = ~cov.all(0)
    plate[free] = np.nanmedian(np.stack([np.where(c[..., None], np.nan, s) for s, c in zip(S, cov)])[:, free], 0)
    return plate


def fit_track(F, rect, lid: str, e: dict) -> dict:
    """Track measurement (see the module doc). Rect-local px: {"pivot", "poses" [(dx, dy, deg)] per frame, "visible",
    "tex" (RGBA at the rest pose), "front", "plate", "fit"}."""
    key = ("track", lid, tuple(rect), repr(sorted(e.items())))
    if key in _CACHE:
        return _CACHE[key]
    S, op, ever = _rect_stack(F, rect)
    n = len(S)
    B = _part_masks(S, op, ever, e.get("colour"))
    px = [int(b.sum()) for b in B]
    need = max(8, int(TRACK_VIS_SHARE * max(px)))
    vis = [p >= need for p in px]
    if sum(vis) < 2:
        raise SystemExit(f"town_full3d_mech: {lid}: track rect {list(rect)}: part px per frame {px}: fewer than two "
                         f"frames show the part")
    R = int(e.get("reachPx", TRACK_REACH_PX))
    turn = float(e.get("turnDeg", 0.0))
    angs = tuple(np.arange(-turn, turn + 1e-6, 2.0)) if turn > 0 else (0.0,)
    ref = int(np.argmax(px))
    T = B[ref].copy()
    ys, xs = np.nonzero(T)
    piv = (float(xs.mean()), float(ys.mean()))
    for _ in range(2):                  # template = the part as the visible frames show it, back at the rest pose
        tr = _track(B, T, piv, R, angs)
        acc = np.zeros_like(T)
        for b, (dx, dy, a, _), v in zip(B, tr, vis):
            if v:
                acc += cv2.warpAffine(b, cv2.invertAffineTransform(pose_matrix(dx, dy, a, piv)), b.shape[::-1])
        T = (acc >= max(2.0, 0.3 * sum(vis))).astype(np.float32)
        if T.sum() < 8:
            raise SystemExit(f"town_full3d_mech: {lid}: track rect {list(rect)}: the frames agree on {int(T.sum())} "
                             f"template px (not one rigid part)")
    tr = _track(B, T, piv, R, angs)
    edge = [k for k, t in enumerate(tr) if vis[k] and t[3]]
    if edge:
        raise SystemExit(f"town_full3d_mech: {lid}: track rect {list(rect)}: frames {edge} reach the search bound "
                         f"({R} px); set a larger reachPx")
    if turn > 0 and any(vis[k] and abs(t[2]) >= turn for k, t in enumerate(tr)):
        raise SystemExit(f"town_full3d_mech: {lid}: track turns reach turnDeg {turn}: {[t[2] for t in tr]}")
    # hidden frames: poses interpolated round the loop between the visible neighbours
    pose = np.array([t[:3] for t in tr], np.float64)
    vk = [k for k in range(n) if vis[k]]
    for k in range(n):
        if vis[k]:
            continue
        a = max([v for v in vk if v < k], default=vk[-1] - n)
        b = min([v for v in vk if v > k], default=vk[0] + n)
        w = (k - a) / (b - a)
        pose[k] = (1 - w) * pose[a % n] + w * pose[b % n]
    # texture: per rest px, the median colour over the visible frames that show the part there
    stack = []
    for s, b, v, p in zip(S, B, vis, pose):
        if not v:
            continue
        Mi = cv2.invertAffineTransform(pose_matrix(*p, piv))
        sb = cv2.warpAffine(s, Mi, s.shape[1::-1], flags=cv2.INTER_NEAREST)
        bb = cv2.warpAffine(b, Mi, b.shape[::-1], flags=cv2.INTER_NEAREST) > 0.5
        stack.append(np.where(bb[..., None], sb, np.nan))
    St = np.stack(stack)
    ok = (T > 0) & np.isfinite(St[..., 0]).any(0)
    tex = np.zeros(T.shape + (4,), np.uint8)
    tex[ok, :3] = np.nanmedian(St[:, ok], 0).round().clip(0, 255)
    tex[..., 3] = ok * 255
    plate = _plate_without(S, B)
    swept = np.zeros(T.shape, np.float32)
    for p in pose:
        swept = np.maximum(swept, cv2.warpAffine(T, pose_matrix(*p, piv), T.shape[::-1]))
    hid = (cv2.dilate((swept > 0.5).astype(np.uint8), np.ones((3, 3), np.uint8)) > 0) & ~ever & op
    front = None
    if hid.any():
        front = np.zeros(T.shape + (4,), np.uint8)
        front[..., :3] = S[0].round().clip(0, 255).astype(np.uint8)
        front[..., 3] = hid * 255
    tf = tex.astype(np.float32)
    err, err0 = [], []
    m = ever & op
    for k in range(n):
        r = cv2.warpAffine(tf, pose_matrix(*pose[k], piv), T.shape[::-1], flags=cv2.INTER_LINEAR)
        al = r[..., 3:4] / 255.0
        img = plate * (1 - al) + r[..., :3] * al
        img[hid] = S[k][hid]
        err.append(float(np.abs(img - S[k]).max(-1)[m].mean()))
        err0.append(float(np.abs(plate - S[k]).max(-1)[m].mean()))
    err, err0 = float(np.mean(err)), float(np.mean(err0))
    _gate(lid, "track", rect, err, err0)
    x0, y0 = rect[0], rect[1]
    fit = {"method": "part = px off the frames' median; template tracked by translation" +
                     (f" and turn (|turn| < {turn} deg)" if turn > 0 else "") +
                     " with the swing kind's occlusion-tolerant score; hidden frames interpolated round the loop",
           "pivotPx": [round(piv[0] + x0, 2), round(piv[1] + y0, 2)], "templatePx": int(T.sum()),
           "partPxPerFrame": px, "visibleFrames": int(sum(vis)),
           "posesPx": [[round(float(v), 2) for v in p] for p in pose], "frontPx": int(hid.sum()),
           "redrawMaeRgb": round(err, 2), "staticPlateMaeRgb": round(err0, 2)}
    out = {"pivot": piv, "poses": pose, "visible": vis, "tex": tex, "front": front,
           "plate": plate.round().clip(0, 255).astype(np.uint8), "fit": fit}
    _CACHE[key] = out
    return out


# ------------------------------------------------------------------------------------------------ pieces
def _one_rect(X, e, kind):
    if not e.get("rects") or len(e["rects"]) != 1:
        raise SystemExit(f"town_full3d_mech: {X.lid}: a {kind} effect needs exactly one explicit rect")
    rect = tuple(e["rects"][0])
    if X.floats(rect):
        raise SystemExit(f"town_full3d_mech: {X.lid}: {kind} at DEF {list(rect)} lies above the sprite (no relief)")
    return rect


def _basis(X, px, py, rect, pull):
    """Holder point on the relief at rect-local (px, py) and the screen basis there (prefab frame): view (camera ->
    point), right, up (unit, orthogonal to the view)."""
    sx, sy = X.spr([px + rect[0]], [py + rect[1]])
    hub = X.P.world(sx, sy, pull=pull)[0]
    hub_l = X.sc.local(hub[None, :])[0]
    view = hub_l / np.linalg.norm(hub_l)
    right = np.array([1.0, 0, 0]) - view * view[0]
    right /= np.linalg.norm(right)
    up = np.cross(right, view)
    if up @ np.array([0, 1.0, 0]) < 0:
        up = -up
    zc = float((hub - X.P.cam["pos"]) @ X.P.cam["fwd"])
    upx = X.P.m_per_px(zc) * X.sc.scale                 # holder units per DEF px at the piece's depth
    return hub_l, view, right, up, upx, zc


def _write(X, name, tex, Vl, uv, tris, toward, hub_l, R, extra):
    import stronghold_full3d_scene as S
    import stronghold_full3d_fx as SF
    cr = np.cross(Vl[tris[:, 1]] - Vl[tris[:, 0]], Vl[tris[:, 2]] - Vl[tris[:, 0]])
    flip = cr @ toward < 0
    tris = tris.copy()
    tris[flip] = tris[flip][:, [0, 2, 1]]
    X.dir.mkdir(parents=True, exist_ok=True)
    Image.fromarray(tex).save(X.dir / f"{name}_albedo.png")
    S.write_bin(X.dir / f"{name}.bytes", Vl, np.tile(toward, (len(Vl), 1)), uv, [tris])
    row = {"name": name, "mesh": f"{S.ASSET_ROOT}/{X.prefab}/{name}.bytes",
           "texture": f"{S.ASSET_ROOT}/{X.prefab}/{name}_albedo.png", "kind": "fx", "maxSize": 512,
           "pos": [float(v) for v in hub_l], "rot": SF.mat_to_quat(R)}
    row.update(extra)
    return row


def k_wheel(X, e: dict, m: np.ndarray, k: int):
    import stronghold_full3d_fx as SF
    FX = _fx()
    rect = _one_rect(X, e, "wheel")
    w = fit_wheel(X.F, rect, X.lid, e)
    cx, cy = w["hub"]
    hub_l, view, right, up, upx, zc = _basis(X, cx, cy, rect, SF.FRONT_PULL_M)
    down = -up
    psi = math.radians(w["psiDeg"])
    maj = math.cos(psi) * right + math.sin(psi) * down
    w0 = -math.sin(psi) * right + math.cos(psi) * down
    t = math.acos(min(1.0, w["q"]))
    mnr = math.cos(t) * w0 + math.sin(t) * view          # the minor direction leans away from the camera
    nrm = np.cross(maj, mnr)
    nrm /= np.linalg.norm(nrm)
    # Unity (left-handed): a positive spin about an axis pointing away from the camera reads counter-clockwise
    Yh = nrm if (nrm @ view > 0) == (w["step"] > 0) else -nrm
    Xh = maj
    Zh = np.cross(Xh, Yh)
    R = np.stack([Xh, Yh, Zh], 1)
    rmax = w["rmax"]
    seg = 64
    ang = np.linspace(0, 2 * np.pi, seg, endpoint=False)
    uu, vv = np.cos(ang) * rmax, np.sin(ang) * rmax
    Pw = (np.concatenate([[0.0], uu])[:, None] * maj + np.concatenate([[0.0], vv])[:, None] * mnr) * upx
    Vl = Pw @ R                                           # prefab -> holder-local
    uv = np.stack([(np.concatenate([[0.0], uu]) + rmax) / (2 * rmax),
                   1.0 - (np.concatenate([[0.0], vv]) + rmax) / (2 * rmax)], 1)
    tris = np.array([[0, 1 + i, 1 + (i + 1) % seg] for i in range(seg)])
    period = abs(360.0 / w["step"] * X.frame_s)
    nm = f"Fx_Wheel_{k}_{X.lid}"
    row = _write(X, nm, w["tex"], Vl, uv, tris, R.T @ (-view), hub_l, R, {"spinPeriod": round(period, 3)})
    rows = [row]
    rep = {"name": nm, "rect": list(rect), "periodSec": round(period, 3), "frameMs": X.frame_ms, "depthM": round(zc, 2),
           "radiusUnits": round(rmax * upx, 4), "fit": w["fit"], "defOffset": [int(X.off[0]), int(X.off[1])]}
    if w["front"] is not None:
        fn = f"Fx_WheelFront_{k}_{X.lid}"
        frow, fcard = FX.swing_card(X, fn, w["front"], rect, (cx, cy), SF.FRONT_PULL_M + WHEEL_FRONT_PULL_M)
        rows.append(frow)
        rep["front"] = {"name": fn, "px": w["fit"]["frontPx"], "card": fcard}
    X.places.append({"rect": list(rect), "placement": "relief"})
    return rows, [], [rep]


def k_track(X, e: dict, m: np.ndarray, k: int):
    import stronghold_full3d_fx as SF
    FX = _fx()
    rect = _one_rect(X, e, "track")
    t = fit_track(X.F, rect, X.lid, e)
    piv = t["pivot"]
    nm = f"Fx_Track_{k}_{X.lid}"
    row, card = FX.swing_card(X, nm, t["tex"], rect, piv, SF.FRONT_PULL_M)
    _, _, _, _, upx, _ = _basis(X, piv[0], piv[1], rect, SF.FRONT_PULL_M)
    # swing_card: holder x = screen right, holder z * zs_up = screen up, holder y = the view ray (a positive turn about
    # it reads counter-clockwise on screen, as the pose angles do)
    _, view, right, _, _, _ = _basis(X, piv[0], piv[1], rect, SF.FRONT_PULL_M)
    zs_up = 1.0 if np.cross(right, view) @ np.array([0, 1.0, 0]) >= 0 else -1.0   # swing_card's own sign
    keys = []
    for dx, dy, a in t["poses"]:
        keys += [round(float(dx * upx), 6), round(float(-dy * upx * zs_up), 6), round(float(a), 4)]
    row.update({"keyPeriod": round(len(t["poses"]) * X.frame_s, 4), "keyPose": keys})
    rows = [row]
    rep = {"name": nm, "rect": list(rect), "periodSec": row["keyPeriod"], "frameMs": X.frame_ms, "card": card,
           "unitsPerPx": round(upx, 6), "fit": t["fit"], "defOffset": [int(X.off[0]), int(X.off[1])]}
    if t["front"] is not None:
        fn = f"Fx_TrackFront_{k}_{X.lid}"
        frow, fcard = FX.swing_card(X, fn, t["front"], rect, piv, SF.FRONT_PULL_M + WHEEL_FRONT_PULL_M)
        rows.append(frow)
        rep["front"] = {"name": fn, "px": t["fit"]["frontPx"], "card": fcard}
    X.places.append({"rect": list(rect), "placement": "relief"})
    return rows, [], [rep]


KIND_FN = {"track": k_track, "wheel": k_wheel}
FIT_FN = {"track": fit_track, "wheel": fit_wheel}
