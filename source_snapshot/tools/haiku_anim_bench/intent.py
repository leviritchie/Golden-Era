"""Round 5 (2026-10-08): intent-level ops. Haiku states a goal against readouts of OUR OWN pose; the bench owns the
geometry.

A goal is a target DIRECTION for one feature of our pose at a DEF frame (or every frame of a range):
  gaze    the head's gaze ray (Unit.gaze);
  trunk   the hips -> chest line (body carriage / pitch);
  reach   a limb's root -> tip line;
  spread  the same line, as a lateral angle out of the body's mid plane (0 = folded along the body, 1 = straight out);
  bend    a limb's middle joint: the second segment's angle to the first.
Targets come as words ("level forward", "steeply up", "out") or as numbers in the readout's own terms
(elev + = up, az 0 = forward, + = toward the unit's left). Nothing here reads a DEF metric.

The solver is damped least squares (weighted, so the bend spreads over the chain in proportion to the joint weights)
on an analytic Jacobian of the FK pose: rotating joint j about world axis a moves a downstream point x by
a x (x - p_j) and turns a downstream direction d by a x d. Each iteration re-poses the unit with the accumulated
per-joint LOCAL offsets (so the result is exactly what the bench's edit math will show), up to 15 iterations,
tolerance 0.3 deg. The offsets become ordinary bench rotation edits (patch_glb keyRotations math): one per joint
for a single frame (a raised-cosine bump of half width hw), or one hw=1 bump per DEF frame for a range (hw=1 bumps on
consecutive frames are a partition of unity, so every DEF frame gets exactly its own solve).
Tears: every candidate is skinned on the GPU over the clip's key grid (the per-edge rule); if it opens new defect
edges, the joints carrying the torn skin are down-weighted and the solve is repeated (2 retries); the candidate with
the best score (angle error + a tear penalty) is kept and its tear is worded.
"""
from __future__ import annotations

import math
import re

import numpy as np

from anim_core import HW_ALL, axis_angle, friendly, qmul

ELEV_WORDS = (("straight up", 85.0), ("steeply up", 55.0), ("slightly up", 15.0), ("straight down", -85.0),
              ("steeply down", -55.0), ("slightly down", -15.0), ("level", 0.0), ("up", 30.0), ("down", -30.0))
AZ_WORDS = (("forward-left", 45.0), ("forward-right", -45.0), ("back-left", 135.0), ("back-right", -135.0),
            ("forward", 0.0), ("front", 0.0), ("ahead", 0.0), ("left", 90.0), ("right", -90.0), ("back", 180.0),
            ("behind", 180.0), ("backward", 180.0))
GOALS = ("gaze", "trunk", "reach", "spread", "bend")
STRENGTHS = (0.5, 1.0, 1.5)
TOL_DEG = 0.3
ITERS = 15
LAM = 0.06
MAX_STEP_DEG = 25.0
MAX_GOAL_DEG = 40.0         # one gaze/trunk/reach intent turns its feature at most this far at 100% (big moves in steps)
TEAR_PENALTY = 0.5          # deg of angle error per new defect edge in the candidate score


# ---------------------------------------------------------------- small vector helpers
def unit(v):
    v = np.asarray(v, np.float64)
    n = np.linalg.norm(v)
    return v / n if n > 1e-12 else v


def dir_from(elev_deg: float, az_deg: float) -> np.ndarray:
    e, a = math.radians(elev_deg), math.radians(az_deg)
    return np.array([math.cos(e) * math.sin(a), math.sin(e), math.cos(e) * math.cos(a)])


def elev_az(v) -> tuple[float, float]:
    v = unit(v)
    return (math.degrees(math.asin(float(np.clip(v[1], -1, 1)))), math.degrees(math.atan2(v[0], v[2])))


def angle_deg(a, b) -> float:
    return math.degrees(math.acos(float(np.clip(np.dot(unit(a), unit(b)), -1, 1))))


def rotate_toward(u0, t, k: float):
    """u0 turned toward t by k x the angle between them, on their great circle (k > 1 overshoots)."""
    u0, t = unit(u0), unit(t)
    th = math.acos(float(np.clip(u0 @ t, -1, 1)))
    if th < 1e-9:
        return u0
    ax = np.cross(u0, t)
    if np.linalg.norm(ax) < 1e-9:                  # opposite: any perpendicular axis
        ax = np.cross(u0, [0, 1.0, 0]) if abs(u0[1]) < 0.9 else np.cross(u0, [1.0, 0, 0])
    ax = unit(ax)
    a = k * th
    return u0 * math.cos(a) + np.cross(ax, u0) * math.sin(a) + ax * (ax @ u0) * (1 - math.cos(a))


def quat_angle_axis(q):
    q = np.asarray(q, np.float64)
    q = q * (1 if q[3] >= 0 else -1)
    s = np.linalg.norm(q[:3])
    if s < 1e-12:
        return 0.0, np.array([1.0, 0, 0])
    return 2 * math.degrees(math.atan2(s, q[3])), q[:3] / s


def parse_dir(spec, cur: np.ndarray, side: float = 0.0) -> np.ndarray:
    """A target direction from words or numbers; a component that is not named keeps its current value.
    side: +1 / -1 for a left / right limb ("out" = toward its own side)."""
    e0, a0 = elev_az(cur)
    if isinstance(spec, dict):
        e = float(spec["elev"]) if spec.get("elev") is not None else e0 + float(spec.get("d_elev", 0) or 0)
        a = float(spec["az"]) if spec.get("az") is not None else a0 + float(spec.get("d_az", 0) or 0)
        return dir_from(float(np.clip(e, -89.5, 89.5)), a)
    s = " " + re.sub(r"[_,;]+", " ", str(spec).lower()) + " "
    e, a = None, None
    for w, v in ELEV_WORDS:
        if f" {w} " in s:
            e = v
            s = s.replace(f" {w} ", " ")
            break
    if " out " in s or " outward " in s or " outward" in s:
        a = 90.0 * (side or 1.0)
    else:
        for w, v in AZ_WORDS:
            if f" {w} " in s:
                a = v
                break
    if e is None and a is None:
        raise ValueError(f"dir {spec!r}: use words (level|slightly up|up|steeply up|straight up|... down, "
                         "forward|left|right|back|forward-left|...|out) or {\"elev\":..,\"az\":..} / {\"d_elev\":..}")
    return dir_from(e0 if e is None else e, a0 if a is None else a)


# ---------------------------------------------------------------- the generic solver (unit independent)
def jacobian(feats: list[dict], piv: np.ndarray):
    """Stacked (3F x 3N) Jacobian of the features' unit directions w.r.t. world-axis rotation vectors of the N joints,
    and the stacked residuals (target - current). A feature: {"kind": "dir"|"vec", "v": (3,), "A"/"B": points (vec),
    "dA"/"dB": (N,) bool (A / B downstream of joint j), "t": unit target, "w": weight}."""
    nj = len(piv)
    rows, res = [], []
    E = np.eye(3)
    for f in feats:
        v = np.asarray(f["v"], float)
        n = float(np.linalg.norm(v))
        u = v / n
        P = (np.eye(3) - np.outer(u, u)) / (n if f["kind"] == "vec" else 1.0)
        Jf = np.zeros((3, 3 * nj))
        for j in range(nj):
            for k in range(3):
                if f["kind"] == "dir":
                    dv = np.cross(E[k], v) if f["dB"][j] else np.zeros(3)
                else:
                    dv = (np.cross(E[k], f["B"] - piv[j]) if f["dB"][j] else 0.0) - \
                         (np.cross(E[k], f["A"] - piv[j]) if f["dA"][j] else 0.0)
                Jf[:, 3 * j + k] = P @ dv
        w = float(f.get("w", 1.0))
        rows.append(Jf * w)
        res.append((unit(f["t"]) - u) * w)
    return np.vstack(rows), np.concatenate(res)


def dls_step(J, r, weights, lam=LAM):
    """Weighted damped least squares: dx = W J^T (J W J^T + lam^2 I)^-1 r (W = per joint weights, 3 per joint)."""
    W = np.repeat(np.asarray(weights, float), 3)
    A = (J * W) @ J.T + lam ** 2 * np.eye(len(r))
    return W * (J.T @ np.linalg.solve(A, r))


def solve(fk, weights, iters=ITERS, tol_deg=TOL_DEG, lam=LAM, max_step_deg=MAX_STEP_DEG):
    """Gauss-Newton / DLS on local joint offsets. fk(qs) -> {"piv": (N,3), "R": (N,3,3) world rotations incl. the
    offsets, "feats": [...]}. Returns (qs, worst feature error in degrees, iterations used)."""
    nj = len(weights)
    qs = [np.array([0, 0, 0, 1.0]) for _ in range(nj)]
    err, it = 180.0, 0
    for it in range(iters + 1):
        st = fk(qs)
        err = max(angle_deg(f["v"], f["t"]) for f in st["feats"])
        if err < tol_deg or it == iters:
            break
        J, r = jacobian(st["feats"], st["piv"])
        dw = dls_step(J, r, weights, lam).reshape(nj, 3)
        for j in range(nj):
            a = float(np.linalg.norm(dw[j]))
            if a < 1e-10:
                continue
            if a > math.radians(max_step_deg):
                dw[j] *= math.radians(max_step_deg) / a
                a = math.radians(max_step_deg)
            al = st["R"][j].T @ (dw[j] / a)          # world axis -> the joint's local frame (R orthonormal)
            qs[j] = qmul(qs[j], axis_angle(al, a))
    return qs, err, it


# ---------------------------------------------------------------- the unit's anatomy (generic)
def partner(b: str):
    for a, c in (("Left", "Right"), ("Right", "Left")):
        if b.startswith(a):
            return c + b[len(a):]
    m = re.match(r"^(.*?)([LR])(_\d+)$", b)
    if m:
        return m.group(1) + {"L": "R", "R": "L"}[m.group(2)] + m.group(3)
    for a, c in (("_L", "_R"), ("_R", "_L"), (".L", ".R"), (".R", ".L")):
        if b.endswith(a):
            return b[:-len(a)] + c
    return None


def side_of(b: str) -> float:
    if b.startswith("Left") or re.match(r"^.*L_\d+$", b) or b.endswith(("_L", ".L")):
        return 1.0
    if b.startswith("Right") or re.match(r"^.*R_\d+$", b) or b.endswith(("_R", ".R")):
        return -1.0
    return 0.0


class Anatomy:
    """Chains found from the joint tree and the skin, no per-unit tables: hips, the head (Unit.head_bone), the chest
    (the head's first ancestor that is not a neck/head joint), the trunk path hips..chest, and limbs (the longest
    chain off any trunk joint that is not the head path and carries skin)."""

    def __init__(self, u):
        self.u = u
        s = u.scene
        nm = u.names
        J = set(s.joints)
        self.parent = {n: s.parent.get(n) for n in s.joints}
        kids = {}
        for n in s.joints:
            p = s.parent.get(n)
            if p in J:
                kids.setdefault(p, []).append(n)
        self.kids = kids
        self.hips = nm.index("Hips") if "Hips" in nm else s.joints[0]
        self.head = nm.index(u.head_bone)
        chest = self.head
        while self.parent.get(chest) in J and any(w in nm[chest].lower() for w in ("head", "neck")):
            chest = self.parent[chest]
        if chest == self.head and self.parent.get(self.head) in J:
            chest = self.parent[self.head]
        self.chest = chest
        self.trunk = self._path(self.hips, self.chest)          # hips .. chest
        neck = []
        n = self.head
        while n is not None and n != self.chest and n in J:
            neck.append(n)
            n = self.parent.get(n)
        self.neck = neck                                          # head, its neck ancestors (head first)
        skin = np.zeros(len(s.joints))
        np.add.at(skin, s.J.ravel(), (s.W > 0.3).ravel().astype(float))
        self.skin = {s.joints[k]: skin[k] for k in range(len(s.joints))}
        on_path = set(self.trunk) | set(self.neck)

        def chain(n):
            best = [n]
            for k in kids.get(n, []):
                c = chain(k)
                if len(c) + 1 > len(best):
                    best = [n] + c
            return best
        self.limbs = {}
        for t in self.trunk:
            for k in kids.get(t, []):
                if k in on_path:
                    continue
                c = chain(k)
                if len(c) < 2 or sum(self.skin.get(x, 0) for x in c) < 20:
                    continue
                low = nm[c[0]].lower()
                tip = min(2, len(c) - 1) if ("upleg" in low or "thigh" in low) else len(c) - 1
                self.limbs[nm[c[0]]] = {"chain": c, "tip": tip, "side": side_of(nm[c[0]])}

    def _path(self, a, b):
        out, n = [], b
        while n is not None and n != a:
            out.append(n)
            n = self.parent.get(n)
        return [a] + out[::-1] if n == a else [b]

    def anc(self, j, n) -> bool:
        """j is a strict ancestor of n."""
        p = self.parent.get(n)
        while p is not None and p in self.parent:
            if p == j:
                return True
            p = self.parent.get(p)
        return False

    def limb_list(self) -> str:
        return ", ".join(f"{k} ({friendly(k)}, {len(v['chain'])} joints)" for k, v in self.limbs.items())

    def find_limb(self, name) -> str:
        if name in self.limbs:
            return name
        n = str(name or "").strip().lower()
        for k in self.limbs:
            if friendly(k) == n or k.lower() == n:
                return k
        for k, v in self.limbs.items():               # a joint inside a chain names its limb
            if any(self.u.names[c].lower() == n for c in v["chain"]):
                return k
        raise ValueError(f"limb {name!r}: one of {list(self.limbs)}")


# ---------------------------------------------------------------- readouts of OUR pose (numbers, no DEF)
def readout(an: Anatomy, G) -> dict:
    u = an.u
    P = G[:, :3, 3]
    _, gd = u.gaze(G[None])
    out = {"gaze": elev_az(gd[0]), "trunk": elev_az(P[an.chest] - P[an.hips]), "limbs": {}}
    for k, v in an.limbs.items():
        c, t = v["chain"], v["tip"]
        d = P[c[t]] - P[c[0]]
        r = {"tip": elev_az(d)}
        if len(c) >= 3 and t >= 2:
            r["bend"] = angle_deg(P[c[1]] - P[c[0]], P[c[2]] - P[c[1]])
        if v["side"]:
            r["spread"] = math.degrees(math.asin(float(np.clip(unit(d)[0] * v["side"], -1, 1)))) / 90.0
        out["limbs"][k] = r
    return out


def readout_text(r: dict) -> str:
    g, t = r["gaze"], r["trunk"]
    s = f"gaze elev {g[0]:+.0f} az {g[1]:+.0f}; trunk elev {t[0]:+.0f} az {t[1]:+.0f}"
    for k, v in r["limbs"].items():
        s += f"; {k} tip elev {v['tip'][0]:+.0f} az {v['tip'][1]:+.0f}"
        if "bend" in v:
            s += f" bend {v['bend']:.0f}"
        if "spread" in v:
            s += f" spread {v['spread'] * 100:.0f}%"
    return s


# ---------------------------------------------------------------- goal -> features + chains on a real unit
class IntentSolver:
    def __init__(self, u, an: Anatomy | None = None):
        self.u = u
        self.an = an or Anatomy(u)

    def _has_rot(self, clip, node) -> bool:
        return any(ch[0] == "rotation" and ch[1] == node for ch in self.u.scene.channels[clip])

    def chains(self, goal: str, limb: str | None, clip: str):
        """(default (joints, weights, label), alternative or None). Weights set how the bend is shared."""
        an, nm = self.an, self.u.names
        if goal == "gaze":
            neck = an.neck
            j = neck + [an.chest]
            w = [1.0] * len(neck) + [0.3]
            alt = (neck[:max(1, (len(neck) + 1) // 2)], [0.5 ** k for k in range(max(1, (len(neck) + 1) // 2))],
                   "head-heavy")
            dflt = (j, w, "whole neck")
        elif goal == "trunk":
            mid = an.trunk[1:-1]
            dflt = (mid, [1.0] * len(mid), "spine") if mid else ([an.hips], [1.0], "hips (whole body)")
            alt = ([an.hips], [1.0], "hips (whole body)") if mid else None
        else:
            v = an.limbs[limb]
            c, t = v["chain"], v["tip"]
            if goal == "bend":
                dflt = ([c[1]], [1.0], f"{nm[c[1]]}")
                alt = None
            else:
                js = c[:t]
                dflt = (js, [1.0 - 0.25 * k for k in range(len(js))], "root-heavy")
                alt = (js, [0.4 + 0.3 * k for k in range(len(js))], "tip-heavy") if len(js) > 1 else None
        fix = lambda ch: None if ch is None else (  # noqa: E731
            [j for j in ch[0] if self._has_rot(clip, j)], [w for j, w in zip(ch[0], ch[1]) if self._has_rot(clip, j)], ch[2])
        d, a = fix(dflt), fix(alt)
        if not d[0]:
            raise ValueError(f"{goal}: no joint of that chain is animated in {clip}")
        return d, (a if a and a[0] else None)

    def feature(self, goal, limb, G, cur_only=False) -> dict:
        an, u = self.an, self.u
        P = G[:, :3, 3]
        if goal == "gaze":
            _, gd = u.gaze(G[None])
            return {"kind": "dir", "v": gd[0], "node": an.head}
        if goal == "trunk":
            return {"kind": "vec", "A": P[an.hips], "B": P[an.chest], "v": P[an.chest] - P[an.hips],
                    "nA": an.hips, "nB": an.chest}
        c, t = an.limbs[limb]["chain"], an.limbs[limb]["tip"]
        if goal == "bend":
            return {"kind": "vec", "A": P[c[1]], "B": P[c[2]], "v": P[c[2]] - P[c[1]], "nA": c[1], "nB": c[2],
                    "seg1": P[c[1]] - P[c[0]]}
        return {"kind": "vec", "A": P[c[0]], "B": P[c[t]], "v": P[c[t]] - P[c[0]], "nA": c[0], "nB": c[t]}

    def target(self, goal, limb, f0: dict, spec: dict) -> np.ndarray:
        cur = unit(f0["v"])
        side = self.an.limbs[limb]["side"] if limb else 0.0
        if goal == "spread":
            amt = float(np.clip(float(spec.get("amount", 1.0)), 0.0, 1.0))
            sag = cur.copy()
            sag[0] = 0.0
            sag = unit(sag) if np.linalg.norm(sag) > 1e-6 else np.array([0, 0, -1.0])
            phi = math.radians(amt * 90.0)
            return unit(math.cos(phi) * sag + math.sin(phi) * np.array([side or 1.0, 0, 0]))
        if goal == "bend":
            deg = float(np.clip(float(spec.get("deg", 30)), 0.0, 170.0))
            s1 = unit(f0["seg1"])
            n = np.cross(s1, cur)
            if np.linalg.norm(n) < 1e-6:
                n = np.cross(s1, [0, 1.0, 0]) if abs(s1[1]) < 0.9 else np.array([1.0, 0, 0])
            return unit(s1 * math.cos(math.radians(deg)) + np.cross(unit(n), s1) * math.sin(math.radians(deg)))
        d = spec.get("dir")
        if d is None:
            d = {k: spec[k] for k in ("elev", "az", "d_elev", "d_az") if spec.get(k) is not None} or None
        if d is None:
            raise ValueError(f"{goal} needs \"dir\" (words) or \"elev\"/\"az\" numbers")
        return parse_dir(d, cur, side)

    # -------------------------------------------------- one frame
    def pose_at(self, clip, frame, edits):
        G, _, _ = self.u.pose(clip, [self.u.frame_time(clip, frame)], edits)
        return G[0]

    def solve_frame(self, clip, frame, base, goal, limb, spec, joints, weights, k: float, hw: float):
        """Solve one frame: returns (parts, achieved error deg, target error from the start, words)."""
        u, an = self.u, self.an
        G0 = self.pose_at(clip, frame, base)
        f0 = self.feature(goal, limb, G0)
        t_full = self.target(goal, limb, f0, spec)
        if goal in ("gaze", "trunk", "reach"):
            full = angle_deg(f0["v"], t_full)
            if full > MAX_GOAL_DEG:
                t_full = rotate_toward(f0["v"], t_full, MAX_GOAL_DEG / full)
        t = rotate_toward(f0["v"], t_full, k)
        nodes = joints
        nm = u.names

        def mk(qs):
            parts = []
            for n, q in zip(nodes, qs):
                ang, ax = quat_angle_axis(q)
                if ang > 1e-4:
                    parts.append({"kind": "rot", "clip": clip, "bone": nm[n], "frame": float(frame), "hw": hw,
                                  "axis": "intent", "deg": round(ang, 4), "axisLocal": [float(x) for x in ax]})
            return parts

        def fk(qs):
            G = self.pose_at(clip, frame, base + mk(qs))
            f = self.feature(goal, limb, G)
            piv = G[nodes, :3, 3]
            R = G[nodes, :3, :3] / np.linalg.norm(G[nodes, :3, :3], axis=1, keepdims=True)
            if f["kind"] == "dir":
                f["dB"] = np.array([n == f["node"] or an.anc(n, f["node"]) for n in nodes])
            else:
                f["dA"] = np.array([an.anc(n, f["nA"]) for n in nodes])
                f["dB"] = np.array([an.anc(n, f["nB"]) for n in nodes])
            f["t"] = t
            return {"piv": piv, "R": R, "feats": [f]}
        qs, err, it = solve(fk, weights)
        return mk(qs), err, angle_deg(f0["v"], t), it

    # -------------------------------------------------- candidates
    def variants(self, clip, frames, hw, base, goal, limb, spec, tears=None, n0=0, mirror=False, skip=None):
        """3-4 candidates: 50/100/150% of the way to the goal on the default chain, and 100% on the alternative chain
        (or 75% when there is none). Each is checked for new tears (tears(parts) -> (count, joints)); a tearing
        candidate is re-solved with the joints carrying the torn skin down-weighted, best score kept."""
        if goal not in GOALS:
            raise ValueError(f"goal must be one of {list(GOALS)}")
        limbs = [None]
        if goal in ("reach", "spread", "bend"):
            limb = self.an.find_limb(limb)
            limbs = [limb]
            if mirror:
                p = partner(limb)
                if p and p in self.an.limbs:
                    limbs.append(p)
        dflt, alt = self.chains(goal, limbs[0], clip)
        plan = [(k, dflt, f"{int(k * 100)}%") for k in STRENGTHS]
        plan.append((1.0, alt, f"100% {alt[2]}") if alt else (0.75, dflt, "75%"))
        out = []
        for k, ch, label in plan:
            sig = f"{label}|{ch[2]}"
            if skip and skip(k, ch[2]):
                out.append({"label": label, "strength": k, "chain": ch[2], "skipped": True})
                continue
            w = list(ch[1])
            best = None
            for attempt in range(3):
                parts, errs, start = [], [], []
                for lb in limbs:
                    jn, wn = (ch[0], w) if lb == limbs[0] else self._mirror_chain(ch, w, lb, goal, clip)
                    sp = spec
                    for fr in frames:
                        p, e, s0, _ = self.solve_frame(clip, fr, base + parts, goal, lb, sp, jn, wn, k, hw)
                        parts += p
                        errs.append(e)
                        start.append(s0)
                n, torn = tears(parts) if tears else (0, [])
                score = max(errs) + TEAR_PENALTY * max(0, n - n0)
                cand = {"label": label, "strength": k, "chain": ch[2], "parts": parts, "err": max(errs),
                        "turn": max(start), "tears": max(0, n - n0), "torn": torn, "score": score, "sig": sig,
                        "reweighted": attempt}
                if best is None or score < best["score"]:
                    best = cand
                if n <= n0 or not torn:
                    break
                names = [self.u.names[j] for j in ch[0]]
                hit = [i for i, b in enumerate(names) if b in torn]
                if not hit:
                    break
                for i in hit:
                    w[i] *= 0.3
            best["share"] = self.share(best["parts"])
            out.append(best)
        return out

    def _mirror_chain(self, ch, w, lb, goal, clip):
        nm = self.u.names
        js = []
        for j in ch[0]:
            p = partner(nm[j])
            js.append(nm.index(p) if p and p in nm else j)
        keep = [(j, x) for j, x in zip(js, w) if self._has_rot(clip, j)]
        return [j for j, _ in keep], [x for _, x in keep]

    @staticmethod
    def share(parts) -> str:
        tot = {}
        for p in parts:
            tot[p["bone"]] = max(tot.get(p["bone"], 0.0), abs(p["deg"]))
        return ", ".join(f"{b} {d:.0f}" for b, d in sorted(tot.items(), key=lambda x: -x[1])[:4]) or "no change"
