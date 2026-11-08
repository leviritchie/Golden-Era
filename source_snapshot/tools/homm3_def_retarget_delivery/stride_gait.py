"""Gait measurement shared by the stride tools: foot slip of a looping in-place walk against the ground speed OE
translates the unit at.

How OE plays a battle walk (static evidence, see docs/homm3_stride_match.md):
  * `UnitViewConfig.moveSpeed` (Core.zip DB/units/units_views/*) is the ground speed, world units per second;
  * the Animator is not root-moved (`m_ApplyRootMotion: 0` on stock prefabs, `applyRootMotion = false` on owned);
  * the walk state `move 0` of `_Battle_Unit_Anim_ctrl_v2` (and the StockEsquireBattle.controller copy owned
    units override) plays `01.Walk` at `m_Speed 0.8` times the `battleSpeed` float parameter.
So one clip cycle of length L clip-seconds lasts L / (0.8 * battleSpeed) game seconds, and a foot that the clip
sweeps backward at u clip-units per clip-second moves backward at u * worldScale * 0.8 * battleSpeed in the world.
Assuming the translation speed scales with battleSpeed the same way (hypothesis), battleSpeed cancels and the
numbers below are for battleSpeed = 1.

Everything here is numpy on sampled trajectories; the GLB and UnityPy readers live in the callers.
Proof tier: generated artifact (offline sampling, no game).
"""
from __future__ import annotations

import numpy as np

MOVE_STATE_SPEED = 0.8          # _Battle_Unit_Anim_ctrl_v2 state "move 0" m_Speed (battleSpeed multiplier)
UP = 1                          # Y up (glTF and Unity)


# ----------------------------------------------------------------------------------------------- quaternions (xyzw)
def qmul(a, b):
    a = np.asarray(a, dtype=np.float64); b = np.asarray(b, dtype=np.float64)
    ax, ay, az, aw = np.moveaxis(a, -1, 0); bx, by, bz, bw = np.moveaxis(b, -1, 0)
    return np.stack([aw * bx + ax * bw + ay * bz - az * by, aw * by - ax * bz + ay * bw + az * bx,
                     aw * bz + ax * by - ay * bx + az * bw, aw * bw - ax * bx - ay * by - az * bz], axis=-1)


def qconj(q):
    q = np.asarray(q, dtype=np.float64)
    return q * np.array([-1.0, -1.0, -1.0, 1.0])


def qnorm(q):
    q = np.asarray(q, dtype=np.float64)
    return q / np.maximum(np.linalg.norm(q, axis=-1, keepdims=True), 1e-12)


def qrot(q, v):
    """Rotate vectors v (..., 3) by quaternions q (..., 4)."""
    q = np.asarray(q, dtype=np.float64); v = np.asarray(v, dtype=np.float64)
    u = q[..., :3]; w = q[..., 3:4]
    t = 2.0 * np.cross(u, v)
    return v + w * t + np.cross(u, t)


def qmat(q):
    q = qnorm(q)
    x, y, z, w = np.moveaxis(q, -1, 0)
    m = np.empty(q.shape[:-1] + (3, 3))
    m[..., 0, 0] = 1 - 2 * (y * y + z * z); m[..., 0, 1] = 2 * (x * y - z * w); m[..., 0, 2] = 2 * (x * z + y * w)
    m[..., 1, 0] = 2 * (x * y + z * w); m[..., 1, 1] = 1 - 2 * (x * x + z * z); m[..., 1, 2] = 2 * (y * z - x * w)
    m[..., 2, 0] = 2 * (x * z - y * w); m[..., 2, 1] = 2 * (y * z + x * w); m[..., 2, 2] = 1 - 2 * (x * x + y * y)
    return m


def mat_q(m):
    """Rotation matrices (..., 3, 3) -> quaternions xyzw (no scale allowed)."""
    m = np.asarray(m, dtype=np.float64)
    flat = m.reshape(-1, 3, 3)
    out = np.empty((len(flat), 4))
    for i, r in enumerate(flat):
        tr = r[0, 0] + r[1, 1] + r[2, 2]
        if tr > 0:
            s = np.sqrt(tr + 1.0) * 2
            out[i] = [(r[2, 1] - r[1, 2]) / s, (r[0, 2] - r[2, 0]) / s, (r[1, 0] - r[0, 1]) / s, 0.25 * s]
        elif r[0, 0] > r[1, 1] and r[0, 0] > r[2, 2]:
            s = np.sqrt(1.0 + r[0, 0] - r[1, 1] - r[2, 2]) * 2
            out[i] = [0.25 * s, (r[0, 1] + r[1, 0]) / s, (r[0, 2] + r[2, 0]) / s, (r[2, 1] - r[1, 2]) / s]
        elif r[1, 1] > r[2, 2]:
            s = np.sqrt(1.0 + r[1, 1] - r[0, 0] - r[2, 2]) * 2
            out[i] = [(r[0, 1] + r[1, 0]) / s, 0.25 * s, (r[1, 2] + r[2, 1]) / s, (r[0, 2] - r[2, 0]) / s]
        else:
            s = np.sqrt(1.0 + r[2, 2] - r[0, 0] - r[1, 1]) * 2
            out[i] = [(r[0, 2] + r[2, 0]) / s, (r[1, 2] + r[2, 1]) / s, 0.25 * s, (r[1, 0] - r[0, 1]) / s]
    return qnorm(out.reshape(m.shape[:-2] + (4,)))


def qslerp(a, b, t):
    a = qnorm(a); b = qnorm(b)
    d = np.sum(a * b, axis=-1, keepdims=True)
    b = np.where(d < 0, -b, b); d = np.abs(d)
    t = np.asarray(t, dtype=np.float64)[..., None]
    lin = d > 0.9995
    th = np.arccos(np.clip(d, -1, 1)); s = np.sin(th)
    wa = np.where(lin, 1 - t, np.sin((1 - t) * th) / np.where(lin, 1, s))
    wb = np.where(lin, t, np.sin(t * th) / np.where(lin, 1, s))
    return qnorm(wa * a + wb * b)


def q_between(u, v):
    """Shortest-arc rotations taking unit-ish vectors u to v (..., 3)."""
    u = np.asarray(u, dtype=np.float64); v = np.asarray(v, dtype=np.float64)
    u = u / np.maximum(np.linalg.norm(u, axis=-1, keepdims=True), 1e-12)
    v = v / np.maximum(np.linalg.norm(v, axis=-1, keepdims=True), 1e-12)
    c = np.cross(u, v); d = np.sum(u * v, axis=-1, keepdims=True)
    q = np.concatenate([c, 1.0 + d], axis=-1)
    anti = (1.0 + d[..., 0]) < 1e-9
    if np.any(anti):   # 180 degrees: any axis orthogonal to u
        ax = np.cross(u, np.array([1.0, 0, 0]))
        ax = np.where(np.linalg.norm(ax, axis=-1, keepdims=True) < 1e-6, np.cross(u, np.array([0, 1.0, 0])), ax)
        q = np.where(anti[..., None], np.concatenate([ax, np.zeros(ax.shape[:-1] + (1,))], axis=-1), q)
    return qnorm(q)


# ------------------------------------------------------------------------------------------------------ gait metrics
def contact_mask(h: np.ndarray, body_height: float, rel: float = 0.25, abs_frac: float = 0.01) -> np.ndarray:
    """Samples where a contact point is on its own floor: within max(rel * its height range, abs_frac * body) of its
    lowest sample. Coarse DEF walks never hold a foot exactly still, so the band is relative to the foot's lift."""
    lo, hi = float(h.min()), float(h.max())
    return h <= lo + max(rel * (hi - lo), abs_frac * body_height)


def periodic_velocity(p: np.ndarray, dt: float) -> np.ndarray:
    """Central differences on uniform samples of one closed cycle (no duplicated end sample)."""
    return (np.roll(p, -1, axis=0) - np.roll(p, 1, axis=0)) / (2.0 * dt)


def forward_axis(vels: list[np.ndarray]) -> np.ndarray:
    """Principal horizontal direction of contact-phase foot velocities (sign arbitrary)."""
    v = np.concatenate([x for x in vels if len(x)])
    hz = v[:, [0, 2]]
    w, vec = np.linalg.eigh(hz.T @ hz)
    a = vec[:, int(np.argmax(w))]
    return np.array([a[0], 0.0, a[1]])


def analyze(traj: dict[str, np.ndarray], cycle_seconds: float, body_height: float, world_scale: float,
            move_speed: float, forward: np.ndarray | None = None, playback: float = MOVE_STATE_SPEED) -> dict:
    """Foot slip of an in-place looping walk.

    traj: contact point -> (N, 3) positions in the unit's body space (Y up) over one cycle sampled uniformly at
    t_i = i * cycle / N (no end duplicate). body_height / world_scale convert body units to world units.
    forward: the facing axis in body space (glTF +Z for owned units); None = principal axis of foot motion, signed so
    the planted foot moves backward. Returns per-limb and pooled numbers, world units and game seconds.
    """
    names = list(traj)
    n = len(next(iter(traj.values())))
    dt = cycle_seconds / n
    k = world_scale * playback                     # clip-units per clip-second -> world units per game second
    masks = {nm: contact_mask(traj[nm][:, UP], body_height) for nm in names}
    vels = {nm: periodic_velocity(traj[nm], dt) for nm in names}
    f = forward_axis([vels[nm][masks[nm]] for nm in names]) if forward is None else np.asarray(forward, float)
    f = f / np.linalg.norm(f)
    if forward is None:
        back = np.concatenate([-(vels[nm][masks[nm]] @ f) for nm in names])
        if back.mean() < 0:
            f = -f
    game_dt = dt / playback
    game_cycle = cycle_seconds / playback
    limbs, strides, all_slip, all_cont = {}, [], 0.0, 0.0
    for nm in names:
        m = masks[nm]
        v = vels[nm]
        z = traj[nm] @ f
        back = -(v @ f)                            # clip-units / clip-second the foot sweeps backward
        lat = v - np.outer(v @ f, f); lat[:, UP] = 0.0
        # world velocity of the foot while the body translates forward at move_speed
        slip_fwd = move_speed - k * back
        slip = np.sqrt(slip_fwd ** 2 + (k * np.linalg.norm(lat, axis=1)) ** 2)
        cont_t = m.sum() * game_dt
        # kinematic stride: a planted foot sweeps back by (body speed x stance time) while it moves backward, so the
        # stride the clip can carry is its backward sweep over the fraction of the cycle it spends moving backward
        dz = np.roll(z, -1) - z
        sweep = float(-dz[dz < 0].sum())
        beta = float((dz < 0).mean())
        stride = world_scale * sweep / beta if beta > 0 else 0.0
        strides.append(stride)
        limbs[nm] = {
            "contactFraction": round(float(m.mean()), 3),
            "backwardFraction": round(beta, 3),
            "backSweep": round(sweep, 5),
            "strideActual": round(stride, 4),
            "slipPerCycle": round(float((slip[m] * game_dt).sum()), 4),
            "slipRatio": round(float((slip[m] * game_dt).sum() / max(move_speed * cont_t, 1e-9)), 4),
            "excursion": round(float(np.ptp(z)), 5),
        }
        all_slip += float((slip[m] * game_dt).sum()); all_cont += cont_t
    stride = float(np.mean(strides)) if strides else 0.0
    planted = stride / game_cycle
    return {
        "forwardAxis": [round(float(x), 4) for x in f],
        "cycleClipSeconds": round(cycle_seconds, 5),
        "cycleGameSeconds": round(game_cycle, 5),
        "moveSpeed": move_speed,
        "worldScale": round(world_scale, 5),
        "plantedGroundSpeed": round(planted, 4),
        "strideRequired": round(move_speed * game_cycle, 4),
        "strideActual": round(stride, 4),
        "requiredOverActual": round(move_speed / planted, 4) if planted > 1e-9 else None,
        "slipPerCycle": round(all_slip / max(len(names), 1), 4),
        "slipRatio": round(all_slip / max(move_speed * all_cont, 1e-9), 4),
        "limbs": limbs,
    }


# ------------------------------------------------------------------------------------------------------- 2-bone IK
def two_bone_ik(hip, knee, ankle, target, pole_fallback, reach_frac: float = 0.999, pole_dir=None):
    """New knee positions for a hip-knee-ankle chain whose ankle must reach target, keeping each frame's bend plane.

    All (N, 3) world positions. Segment lengths are each frame's own. The bend plane is the original knee's offset from
    the hip->ankle line; a straight frame uses pole_fallback (N, 3 or 3). Targets beyond reach_frac of the full length
    are pulled back along hip->target. pole_dir (N, 3), when given, replaces the per-frame bend plane (a caller that
    has already made the knee direction consistent over the cycle). Returns (knee', ankle', clamped mask).
    """
    l1 = np.linalg.norm(knee - hip, axis=1); l2 = np.linalg.norm(ankle - knee, axis=1)
    d_vec = target - hip
    d = np.linalg.norm(d_vec, axis=1)
    dmax = (l1 + l2) * reach_frac
    dmin = np.abs(l1 - l2) + 1e-6
    clamped = d > dmax
    dc = np.clip(d, dmin, dmax)
    u = d_vec / np.maximum(d, 1e-12)[:, None]
    ankle_new = hip + u * dc[:, None]
    a = (l1 ** 2 - l2 ** 2 + dc ** 2) / (2 * dc)
    h = np.sqrt(np.maximum(l1 ** 2 - a ** 2, 0.0))
    ha = ankle - hip
    han = ha / np.maximum(np.linalg.norm(ha, axis=1), 1e-12)[:, None]
    kp = (knee - hip) - np.sum((knee - hip) * han, axis=1)[:, None] * han
    fb = np.broadcast_to(np.asarray(pole_fallback, float), kp.shape)
    weak = np.linalg.norm(kp, axis=1) < 1e-3 * np.maximum(l1, 1e-9)
    kp = np.where(weak[:, None], fb, kp)
    if pole_dir is not None:
        kp = np.asarray(pole_dir, float)
    pole = kp - np.sum(kp * u, axis=1)[:, None] * u
    pole = pole / np.maximum(np.linalg.norm(pole, axis=1), 1e-12)[:, None]
    knee_new = hip + u * a[:, None] + pole * h[:, None]
    return knee_new, ankle_new, clamped
