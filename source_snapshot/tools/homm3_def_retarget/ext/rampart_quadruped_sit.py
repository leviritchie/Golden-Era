"""Rampart quadrupeds that sit on their haunches in the DEF (griffins): a per-frame "sit" fit.

rampart_quadruped's silhouette fit pitches the whole body about the hind FEET with the legs rigid (a rear).
A HoMM3 griffin's idle / defence / hit frames instead sit: hind legs folded under, rear lowered to the
ground, chest pitched up ~45 deg with a talon raised. That pose is out of reach of the rigid pitch, so the fit
settles near level. This module adds the missing degree of freedom and must be listed BEFORE
rampart_quadruped in "extensions" (its before_keys runs first; the rigid fit then refines on top of the sit).

Unit config key "quadrupedSit" (the hind legs are quadruped.legs with front false):
  "clips": ["Idle", "Mouseover", "Hitted", "Defence"]   clips whose frames are fitted (others stay standing)
  "pitch": [0, 60]        chest-up pitch about the hind hip line, degrees
  "drop": [0, 0.25]       rear lowered by this much (scene units); the hind feet stay planted by two-bone IK
  "keep": ["QTail_00"]    subtrees that are lowered with the rear but not pitched (a tail would swing into
                          the ground)
  "yaw": -100             sprite-camera yaw of the fit (required: rampart_quadruped's own yaw search runs
                          after this module has changed frame 0, so pin both to the same value)
  "lambda": 0.002         temporal/size penalty per step, like rampart_quadruped's fit
  "counterPitch": {"bone": "Neck", "share": 1.0}
                          opt-in: turn this bone's subtree back down by share * the chest-up pitch about its own head,
                          so a mesh whose neck already stands upright at rest (the 2026-09-28 dragons) keeps its head
                          level instead of pointing the snout at the sky. Absent: pose exactly as before.
  "fixed": {"pitch": 45, "drop": 0.15}
                          use this pose instead of the silhouette search (the search cannot see the sit when
                          spread wings dominate the silhouette: on the royal griffin it kept every Idle frame
                          standing). With "fixed", the pose is weighted per clip:
  "easeOut": ["MoveStart", "Death"]   weight 1 -> 0 over the clip (rises out of the sit)
  "easeIn": ["MoveEnd"]               weight 0 -> 1 (settles back into the sit)
  "bracket": ["AttackFront"]          weight 1 at both ends, 0 at mid-clip (stands to strike, sits again)
  "tuck": {"clips": ["Move"], "easeIn": ["MoveStart"], "easeOut": ["MoveEnd"], "front": 80, "hind": 80}
                          flight pose: each quadruped.legs chain swings rigidly about its own root, front
                          legs reaching forward by "front" deg and hind legs trailing back by "hind" deg
                          (with only "deg", every leg trails back by it). "rigid": true first resets each
                          leg chain to its rest pose on its parent, so the capture's walk swing does not
                          swing the tucked legs back down (the DEF holds them still in flight). A flying griffin's legs hanging to the
                          ground read as a walk to stride_match_glb (Move floor within AIRBORNE_LIFT of
                          Idle's), which then retimes the wing beat to a ground cadence.
Writes <blend>.sitfit.json (per-frame pitch, drop, IoU; tuck weight). Uses the core's skin / def_mask helpers
("silhouetteRefine" must be present, as for rampart_quadruped's fit).
"""
import json, math
import numpy
from mathutils import Matrix, Vector

from rampart_quadruped import _about, _children, _subtree, _clip_of


def _rot_between(a, b):
    a = a.normalized(); b = b.normalized()
    return a.rotation_difference(b).to_matrix()


def _two_bone(H, K, A, T):
    """New knee for hip H reaching ankle target T, keeping the H-K-A bend plane."""
    l1, l2 = (K - H).length, (A - K).length
    d = T - H
    dist = max(1e-6, min(d.length, 0.999 * (l1 + l2)))
    u = d.normalized()
    a = (l1 * l1 - l2 * l2 + dist * dist) / (2 * dist)
    h = math.sqrt(max(l1 * l1 - a * a, 0.0))
    kp = (K - H) - u * (K - H).dot(u)
    if kp.length < 1e-6:
        kp = (K - H) - u * (K - H).dot(u) + Vector((0, -1e-3, 0))
    kp = (kp - u * kp.dot(u)).normalized()
    return H + u * a + kp * h, H + u * dist


def before_keys(g):
    cfg = g["cfg"]; Q = cfg.get("quadruped", {}); S = cfg.get("quadrupedSit")
    if not S or not g.get("REFINE"):
        return
    if S.get("yaw") is None:
        raise SystemExit("quadrupedSit.yaw is required (pin the sprite-camera yaw)")
    skin, def_mask = g["skin"], g["def_mask"]
    posed_world, rest, parent_of, ms_frames = g["posed_world"], g["rest"], g["parent_of"], g["ms_frames"]
    RUB = set(g.get("RUBBLE_BONES", []))
    info = _clip_of(g["MASTER"])
    ch = _children(parent_of)
    clips = set(S.get("clips", ["Idle", "Mouseover", "Hitted", "Defence"]))
    lo_p, hi_p = S.get("pitch", [0, 60]); lo_d, hi_d = S.get("drop", [0, 0.25]); lam = S.get("lambda", 0.002)
    hind = [L["bones"] for L in Q.get("legs", []) if not L.get("front")]
    if not hind:
        raise SystemExit("quadrupedSit needs quadruped.legs with front false (the hind legs)")
    hind_sub = set()
    for c in hind:
        hind_sub |= set(_subtree(ch, c[0]))
    keep = set()
    for b in S.get("keep", []):
        if b in parent_of or b in rest:
            keep |= set(_subtree(ch, b))
    CP = S.get("counterPitch")
    lat0 = Vector((1, 0, 0))
    SW, SH = g["SW"], g["SH"]; bx0, by0, bx1, by1 = g["bx0"], g["by0"], g["bx1"], g["by1"]

    f = Matrix.Rotation(math.radians(S["yaw"]), 3, Vector((0, 0, 1))) @ g["fwd_cam"]
    r = f.cross(Vector((0, 0, 1))).normalized(); u = r.cross(f).normalized()
    V0 = numpy.array([v.co[:] for v in g["body"].data.vertices])
    xs, ys = V0 @ numpy.array(r), V0 @ numpy.array(u)
    s_ = (by1 - by0) / (ys.max() - ys.min()); oy = by1 + s_ * ys.min(); ox = (bx0 + bx1) / 2 - s_ * (xs.max() + xs.min()) / 2
    R_, U_ = numpy.array(r), numpy.array(u)

    def splat(P):
        x = numpy.round(ox + s_ * (P @ R_)).astype(int); y = numpy.round(oy - s_ * (P @ U_)).astype(int)
        ok = (x >= 1) & (x < SW - 1) & (y >= 1) & (y < SH - 1)
        m = numpy.zeros((SH, SW), bool); m[y[ok], x[ok]] = True
        o = m.copy()
        for dy_, dx_ in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (-1, -1), (1, -1), (-1, 1)):
            o |= numpy.roll(numpy.roll(m, dy_, 0), dx_, 1)
        return o

    def iou(A, target):
        m = splat(skin(A)); return (m & target).sum() / max((m | target).sum(), 1)

    def apply(A, pitch, drop):
        if abs(pitch) < 1e-6 and abs(drop) < 1e-6:
            return dict(A)
        A = dict(A)
        heads = [A[c[0]].translation.copy() for c in hind]
        piv = sum(heads, Vector()) / len(heads)
        lat = (A["Hips"].to_3x3() @ rest["Hips"].to_3x3().inverted()) @ lat0
        M = _about(piv, Matrix.Rotation(math.radians(-pitch), 3, lat))       # chest up (faces -Y)
        down = Matrix.Translation(Vector((0, 0, -drop)))
        feet = {c[0]: A[c[2]].translation.copy() for c in hind}
        for n in list(A):
            if n == "Root" or n in RUB or n in hind_sub:
                continue
            A[n] = down @ (A[n] if n in keep else M @ A[n])
        if CP and CP["bone"] in A:
            Mc = _about(A[CP["bone"]].translation.copy(), Matrix.Rotation(math.radians(pitch * CP.get("share", 1.0)), 3, lat))
            for n in _subtree(ch, CP["bone"]):
                if n in A and n not in keep and n not in RUB:
                    A[n] = Mc @ A[n]
        for c in hind:
            up_, mid, low = c[0], c[1], c[2]
            H0, K0, A0 = A[up_].translation.copy(), A[mid].translation.copy(), A[low].translation.copy()
            H1 = (down @ M) @ H0
            K1, A1 = _two_bone(H1, K0 + (H1 - H0), A0 + (H1 - H0), feet[up_])
            q1 = _rot_between(K0 - H0, K1 - H1)
            q2 = _rot_between(A0 - K0, A1 - K1)
            low_sub, mid_sub = set(_subtree(ch, low)), set(_subtree(ch, mid))
            for n in _subtree(ch, up_):
                if n in low_sub:            # the foot keeps its world rotation, planted where it stood
                    A[n] = Matrix.Translation(A1 - A0) @ A[n]
                elif n in mid_sub:          # shin: rotated onto the new knee->ankle direction
                    A[n] = Matrix.Translation(K1) @ q2.to_4x4() @ Matrix.Translation(-K0) @ A[n]
                else:                       # thigh: moved with the lowered rear, rotated onto hip->knee
                    A[n] = Matrix.Translation(H1) @ q1.to_4x4() @ Matrix.Translation(-H0) @ A[n]
        return A

    TK = S.get("tuck")

    def tuck(A, w):
        A = dict(A)
        Rh = A["Hips"].to_3x3() @ rest["Hips"].to_3x3().inverted()
        lat, back = Rh @ lat0, Rh @ Vector((0, 1, 0))          # the body faces -Y: legs trail toward +Y
        for L in Q.get("legs", []):
            c = L["bones"]
            # front legs reach forward, hind legs trail back ("deg" alone: every leg trails back)
            deg = w * TK.get("front" if L.get("front") else "hind", TK.get("deg", 50))
            way = -1.0 if (L.get("front") and "front" in TK) else 1.0
            if TK.get("rigid"):       # drop the capture's own leg swing: the chain rides its parent as at rest
                p0 = parent_of.get(c[0])
                P = A[p0] @ rest[p0].inverted() if p0 in A and p0 in rest else Matrix.Identity(4)
                for n in _subtree(ch, c[0]):
                    if n in rest:
                        A[n] = P @ rest[n]
            piv = A[c[0]].translation.copy(); foot = A[c[2]].translation
            best = None
            for sg in (1, -1):
                M = _about(piv, Matrix.Rotation(math.radians(sg * deg), 3, lat))
                s = way * ((M @ foot) - foot).dot(back)
                if best is None or s > best[0]:
                    best = (s, M)
            for n in _subtree(ch, c[0]):
                A[n] = best[1] @ A[n]
        return A

    def ease(clip, x, full, e_out, e_in, brk=()):
        return (1.0 if clip in full else
                0.5 + 0.5 * math.cos(math.pi * x) if clip in e_out else
                0.5 - 0.5 * math.cos(math.pi * x) if clip in e_in else
                0.5 + 0.5 * math.cos(2 * math.pi * x) if clip in brk else 0.0)

    tlog = []
    if TK:
        for t, A in enumerate(posed_world):
            clip, ci, cn = info.get(t, ("Idle", 0, 1))
            w = ease(clip, ci / max(cn - 1, 1), set(TK.get("clips", ["Move"])), TK.get("easeOut", []), TK.get("easeIn", []))
            if w > 0.0:
                A.update(tuck(A, w))
                tlog.append({"frame": t, "clip": clip, "tuckWeight": round(w, 3)})

    prev = {"pitch": 0.0, "drop": 0.0}
    steps = {"pitch": 10.0, "drop": 0.03}
    lim = {"pitch": (lo_p, hi_p), "drop": (lo_d, hi_d)}
    log = []
    FX = S.get("fixed")
    for t, A in enumerate(posed_world):
        clip, ci, cn = info.get(t, ("Idle", 0, 1))
        if FX:
            w = ease(clip, ci / max(cn - 1, 1), clips, S.get("easeOut", []), S.get("easeIn", []), S.get("bracket", []))
            if w <= 0.0:
                continue
            target = def_mask(ms_frames[t]["sourcePng"])
            base = float(iou(A, target))
            A.update(apply(A, FX["pitch"] * w, FX["drop"] * w))
            log.append({"frame": t, "clip": clip, "weight": round(w, 3), "pitch": round(FX["pitch"] * w, 1),
                        "drop": round(FX["drop"] * w, 3), "iouStanding": round(base, 3), "iou": round(float(iou(A, target)), 3)})
            continue
        if clip not in clips:
            prev = {"pitch": 0.0, "drop": 0.0}
            continue
        target = def_mask(ms_frames[t]["sourcePng"])

        def score(p):
            return (iou(apply(A, p["pitch"], p["drop"]), target)
                    - lam * sum(abs(p[k] - prev[k]) / steps[k] for k in p) - lam * 0.5 * sum(abs(p[k]) / steps[k] for k in p))
        cands = [dict(prev), {"pitch": 0.0, "drop": 0.0}] + [
            {"pitch": float(a), "drop": float(d)} for a in range(int(lo_p), int(hi_p) + 1, 10)
            for d in numpy.linspace(lo_d, hi_d, 5)]
        best = max(cands, key=score); bs = score(best)
        for sc in (1.0, 0.5, 0.25):
            improved = True
            while improved:
                improved = False
                for k in ("pitch", "drop"):
                    for sg in (1, -1):
                        c = dict(best); c[k] = max(lim[k][0], min(lim[k][1], c[k] + sg * steps[k] * sc))
                        v = score(c)
                        if v > bs + 1e-6:
                            bs, best, improved = v, c, True
        prev = dict(best)
        base = float(iou(A, target))
        A.update(apply(A, best["pitch"], best["drop"]))
        log.append({"frame": t, "clip": clip, "pitch": round(best["pitch"], 1), "drop": round(best["drop"], 3),
                    "iouStanding": round(base, 3), "iou": round(float(iou(A, target)), 3)})
    json.dump({"yaw": S["yaw"], "frames": log, "tuck": tlog},open(g["OUT"] + ".sitfit.json", "w"), indent=0)
    if log:
        print("QUADRUPED sit fit", len(log), "frames, mean IoU", round(float(numpy.mean([x["iouStanding"] for x in log])), 3),
              "->", round(float(numpy.mean([x["iou"] for x in log])), 3))
