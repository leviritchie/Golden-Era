"""Castle: silhouette refinement with a dense (triangle-sampled) rasteriser.

Castle DEF canvases are large (e.g. 1008x870 with ~335 px per scene unit), so the built-in
`silhouetteRefine`, which splats *vertices* into the sprite, leaves the body full of holes and
a thin pike or bow shaft almost invisible; its prop swing then chases noise. This hook runs the
same kind of search (whole-body dx/dy/roll, extra wing spread, and a swing/tilt of rigid held
props about their hand) against a mask rasterised from points sampled over every triangle, on a
target downsampled by `scale`.

Config (unit json):  "extensions": ["castle_refine"],
  "castleRefine": {"params": ["dx","dy","roll","wing"], "limits": {...}, "propAim": ["RightHand"],
                   "scale": 0.5, "aimRange": 120, "aimSmooth": 0.0004,
                   "aimSlide": 0.3 (optional: the prop may also slide along its own axis, e.g. a pike thrust), "frames": "all"|[a,b]}
Units are sprite pixels at full DEF resolution (dx, dy) and degrees (roll, wing, aim).
Runs in before_keys (after wings/tail/deaths), so it must not be combined with shatter/shrinkOut
on the same frames (they hide the body; the IoU search is skipped for frames whose body is gone).
"""
import math, json
import numpy as np


def before_keys(g):
    cfg = g["cfg"]; R = cfg.get("castleRefine")
    if not R:
        return
    bpy = g["bpy"]; Matrix = g["Matrix"]; Vector = g["Vector"]
    body, rest, posed_world, T = g["body"], g["rest"], g["posed_world"], g["T"]
    WINGS, STATIC, TAILB = g["WINGS"], g["STATIC"], g["TAILB"]
    RUB = set(g.get("RUBBLE_BONES", []))
    fwd_cam, right, up = g["fwd_cam"], g["right"], g["up"]
    SC = R.get("scale", 0.5)
    s_px, ox, oy = g["s_px"] * SC, g["ox"] * SC, g["oy"] * SC
    SW, SH = int(round(g["SW"] * SC)), int(round(g["SH"] * SC))
    PARAMS_ALL = R.get("params", [])
    # per-clip body params, e.g. {"Death": ["dx", "dy", "roll"]}: keep a collapsing body on its DEF spot
    clip_of = {}
    for sg in json.load(open(g["MASTER"]))["segments"]:
        for t_ in range(sg["globalStart"], sg["globalEnd"]):
            clip_of[t_] = sg["contractSuffix"]
    lim = {"dx": 40, "dy": 60, "roll": 45, "wing": 60}; lim.update(R.get("limits", {}))

    names_all = [n for n in posed_world[0].keys() if n not in RUB]
    col = {n: i for i, n in enumerate(names_all)}
    me = body.data
    V0 = np.array([v.co[:] for v in me.vertices]); Vh = np.c_[V0, np.ones(len(V0))]
    gname = {gr.index: gr.name for gr in body.vertex_groups}
    Wm = np.zeros((len(V0), len(names_all)))
    for v in me.vertices:
        for gr in v.groups:
            n = gname[gr.group]
            if n in col:
                Wm[v.index, col[n]] += gr.weight
    Wm /= np.maximum(Wm.sum(1, keepdims=True), 1e-9)
    restinv = {n: np.array(rest[n].inverted()) for n in names_all}

    # dense surface samples: each triangle gets points in proportion to its rest area in pixels
    me.calc_loop_triangles()
    tri = np.array([lt.vertices[:] for lt in me.loop_triangles])
    a_px = 0.5 * np.linalg.norm(np.cross(V0[tri[:, 1]] - V0[tri[:, 0]], V0[tri[:, 2]] - V0[tri[:, 0]]), axis=1) * s_px ** 2
    # long thin triangles (a pike shaft) need samples along their length, not by area alone
    e_px = np.max([np.linalg.norm(V0[tri[:, i]] - V0[tri[:, (i + 1) % 3]], axis=1) for i in range(3)], axis=0) * s_px
    ns = np.clip(np.ceil(np.maximum(a_px / 0.6, e_px / 0.8)), 1, 400).astype(int)
    rng = np.random.default_rng(3)
    ti = np.repeat(np.arange(len(tri)), ns)
    u = rng.random((len(ti), 2)); m = u.sum(1) > 1; u[m] = 1 - u[m]
    bw = np.c_[1 - u.sum(1), u]
    TI = tri[ti]
    class _B:   # barycentric sample operator (Blender's Python has no scipy)
        def __matmul__(self, X):
            X = np.asarray(X)
            if X.ndim == 1:
                return (bw * X[TI]).sum(1)
            return bw[:, 0:1] * X[TI[:, 0]] + bw[:, 1:2] * X[TI[:, 1]] + bw[:, 2:3] * X[TI[:, 2]]
    Bs = _B()
    print("CASTLE_REFINE samples", len(ti), "canvas", SW, SH)

    R_ = np.array(right); U_ = np.array(up); Fw = np.array(fwd_cam)

    def skin(A):
        out = np.zeros((len(V0), 3))
        for n, i in col.items():
            w = Wm[:, i]
            if w.max() <= 0:
                continue
            out += w[:, None] * (Vh @ (np.array(A[n]) @ restinv[n]).T)[:, :3]
        return out

    def raster(S):
        x = np.round(ox + s_px * (S @ R_)).astype(int); y = np.round(oy - s_px * (S @ U_)).astype(int)
        ok = (x >= 0) & (x < SW) & (y >= 0) & (y < SH)
        m = np.zeros((SH, SW), bool); m[y[ok], x[ok]] = True
        return m

    TOL = R.get("aimTolerance", 2)
    def dilate(m, r):
        out = m.copy()
        for dy_ in range(-r, r + 1):
            for dx_ in range(-r, r + 1):
                if dy_ or dx_:
                    out |= np.roll(np.roll(m, dy_, 0), dx_, 1)
        return out

    def rot_about(axis, ang, pivot):
        Rm = np.array(Matrix.Rotation(ang, 3, Vector(tuple(axis))))
        return lambda P: (P - pivot) @ Rm.T + pivot

    ms_frames = json.load(open(g["MASTER"]))["frames"]
    def def_mask(path):
        img = bpy.data.images.load(path, check_existing=True)
        a = np.array(img.pixels[:]).reshape(img.size[1], img.size[0], 4)[::-1, :, 3]
        bpy.data.images.remove(img)
        yi = np.minimum((np.arange(SH) + 0.5) / SC, a.shape[0] - 1).astype(int)
        xi = np.minimum((np.arange(SW) + 0.5) / SC, a.shape[1] - 1).astype(int)
        return a[yi][:, xi] > 0.5

    wing_rows = {w["bone"]: Wm[:, col[w["bone"]]] > 0.5 for w in WINGS}
    wing_srows = {k: np.asarray(Bs @ r.astype(float)).ravel() > 0.5 for k, r in wing_rows.items()}
    steps = {"dx": [8, 4, 2, 1], "dy": [8, 4, 2, 1], "roll": [8, 4, 2, 1], "wing": [32, 12, 6, 2]}
    lam = R.get("penalty", 0.0015)
    prev = {}; prev_aim = {}
    frames = range(T) if R.get("frames", "all") == "all" else range(*R["frames"])
    body_bones = [n for n in names_all if n != "Root" and n not in STATIC and n not in TAILB]
    log = []
    for t in frames:
        A = posed_world[t]
        Sv = skin(A); S = Bs @ Sv
        if np.ptp(S, axis=0).max() < 1e-3:       # body hidden (death stage)
            continue
        target = def_mask(ms_frames[t]["sourcePng"])
        entry = {"frame": t}
        PARAMS = R.get("clipParams", {}).get(clip_of.get(t), PARAMS_ALL)
        for k in PARAMS:
            prev.setdefault(k, 0.0)
        prev = {k: prev[k] for k in PARAMS}
        if R.get("debug") and t in R["debug"]:
            np.savez(g["OUT"] + f".dbg{t}.npz", mask=raster(S), target=target)
        if PARAMS:
            hips = np.array(A["Hips"].translation)
            wp = {w["bone"]: (np.array(A[w["bone"]].translation),
                              np.array(A[w["bone"]].to_3x3() @ (rest[w["bone"]].to_3x3().inverted() @ Vector((0, 1, 0)))))
                  for w in WINGS}
            def apply(p):
                P = S.copy()
                if p.get("wing"):
                    for w in WINGS:
                        piv, ax = wp[w["bone"]]; rows = wing_srows[w["bone"]]
                        P[rows] = rot_about(ax, math.radians(p["wing"]) * w["sign"], piv)(P[rows])
                if p.get("roll"):
                    P = rot_about(Fw, math.radians(p["roll"]), hips)(P)
                return P + R_ * p.get("dx", 0.0) / g["s_px"] + U_ * p.get("dy", 0.0) / g["s_px"]
            def score(p):
                mm = raster(apply(p)); return (mm & target).sum() / max((mm | target).sum(), 1) - lam * sum(abs(v) for v in p.values())
            cur = dict(prev); best = score(cur); base = score({k: 0.0 for k in PARAMS})
            for level in range(4):
                improved = True
                while improved:
                    improved = False
                    for k in PARAMS:
                        for sgn in (1, -1):
                            c = dict(cur); c[k] = max(-lim[k], min(lim[k], c[k] + sgn * steps[k][level])); sc_ = score(c)
                            if sc_ > best + 1e-6:
                                best, cur, improved = sc_, c, True
            prev = cur
            entry.update({k: round(v, 2) for k, v in cur.items()}); entry["iouGain"] = round(best - base, 3)
            Tm = Matrix.Translation(Vector(tuple(R_ * cur.get("dx", 0.0) / g["s_px"] + U_ * cur.get("dy", 0.0) / g["s_px"])))
            if cur.get("roll"):
                hv = Vector(tuple(hips))
                Tm = Tm @ Matrix.Translation(hv) @ Matrix.Rotation(math.radians(cur["roll"]), 4, fwd_cam) @ Matrix.Translation(-hv)
            for n in body_bones:
                A[n] = Tm @ A[n]
            if cur.get("wing"):
                for w in WINGS:
                    n = w["bone"]; axis_l = rest[n].to_3x3().inverted() @ Vector((0, 1, 0))
                    A[n] = A[n] @ Matrix.Rotation(math.radians(cur["wing"]) * w["sign"], 4, axis_l)
        for ab in R.get("propAim", []):
            if t in g.get("propHeld", {}).get(ab, ()):   # a hook already placed this prop (castle_mount lanceLie)
                continue
            rows = Wm[:, col[ab]] > 0.99
            if not rows.any():
                continue
            srows = np.asarray(Bs @ rows.astype(float)).ravel() > 0.999
            if R.get("aimFromRest"):
                # the capture has no usable wrist rotation: start the prop from its rest world
                # orientation carried by the body's own lean (Spine2), placed at the hand
                lean = A["Spine2"].to_3x3() @ rest["Spine2"].to_3x3().inverted()
                A[ab] = Matrix.Translation(A[ab].translation) @ (lean @ rest[ab].to_3x3()).to_4x4()
            Sv = skin(A); S = Bs @ Sv
            piv = np.array(A[ab].translation)
            rest_mask = raster(S[~srows]); PS = S[srows]
            pdir = PS.mean(0) - piv
            ax2 = np.cross(Fw, pdir); ax2 /= max(np.linalg.norm(ax2), 1e-9)
            pa = prev_aim.get(ab, {"aim1": 0.0, "aim2": 0.0})
            AR = R.get("aimRange", 120); sm = R.get("aimSmooth", 0.0004)
            SLD = R.get("aimSlide", 0.0); pa.setdefault("slide", 0.0)
            pdn = pdir / max(np.linalg.norm(pdir), 1e-9)
            def rotm(q):
                return (np.array(Matrix.Rotation(math.radians(q["aim2"]), 3, Vector(tuple(ax2))))
                        @ np.array(Matrix.Rotation(math.radians(q["aim1"]), 3, fwd_cam)))
            def prot(q):
                Rm = rotm(q)
                return (PS - piv + pdn * q.get("slide", 0.0)) @ Rm.T + piv
            # IoU rewards hiding a thin prop inside the body; score only the prop pixels outside the
            # body: gain where they cover DEF pixels the body leaves unexplained, lose where they miss
            # (with a few pixels' tolerance: a thin shaft a little to one side must still count)
            # Only DEF pixels well clear of the body count ("free"): the strips where the body itself
            # is misfit would otherwise pull the prop onto them. Out-of-plane tilt (aim2) is penalised
            # more, since foreshortening a prop toward the camera is a cheap way to shorten it.
            away = ~dilate(rest_mask, R.get("aimBodyMargin", 6))
            free = target & away; nfree = max(free.sum(), 1); tgt_d = dilate(target, TOL)
            def pscore(q):
                pm = raster(prot(q)) & away
                hit = (dilate(pm, TOL) & free).sum(); miss = (pm & ~tgt_d).sum()
                return ((hit - 0.5 * miss) / nfree - 0.0001 * abs(q["aim1"]) - 0.0005 * abs(q["aim2"])
                        - sm * (abs(q["aim1"] - pa["aim1"]) + abs(q["aim2"] - pa["aim2"]) + 60 * abs(q.get("slide", 0) - pa["slide"]))
                        - 0.003 * abs(q.get("slide", 0)))
            sl0 = [0.0] if not SLD else [-SLD, -SLD / 2, 0.0, SLD / 2, SLD]
            cands = [dict(pa)] + [{"aim1": float(a1), "aim2": float(a2), "slide": sl} for a1 in range(-AR, AR + 1, 10)
                                  for a2 in np.linspace(-R.get("aimTilt", 30), R.get("aimTilt", 30), 5) for sl in sl0]
            if R.get("debug") and t in R["debug"]:
                np.savez(g["OUT"] + f".dbgaim{t}.npz", S=S, srows=srows, piv=piv, ax2=ax2, Fw=Fw, pdn=pdn, target=target,
                         R_=R_, U_=U_, cam=np.array([s_px, ox, oy, SW, SH]))
            q = max(cands, key=pscore); qb = pscore(q)
            keys = ("aim1", "aim2", "slide") if SLD else ("aim1", "aim2")
            for st in (6, 3, 1):
                improved = True
                while improved:
                    improved = False
                    for k in keys:
                        for sgn in (1, -1):
                            c = dict(q)
                            if k == "slide":
                                c[k] = max(-SLD, min(SLD, c[k] + sgn * st * SLD / 24))
                            else:
                                lk = AR if k == "aim1" else R.get("aimTilt", 30)
                                c[k] = max(-lk, min(lk, c[k] + sgn * st))
                            sc_ = pscore(c)
                            if sc_ > qb + 1e-6:
                                qb, q, improved = sc_, c, True
            prev_aim[ab] = q
            Rw = (Matrix.Translation(Vector(tuple(piv))) @ Matrix.Rotation(math.radians(q["aim2"]), 4, Vector(tuple(ax2)))
                  @ Matrix.Rotation(math.radians(q["aim1"]), 4, fwd_cam) @ Matrix.Translation(-Vector(tuple(piv)))
                  @ Matrix.Translation(Vector(tuple(pdn * q.get("slide", 0.0)))))
            A[ab] = Rw @ A[ab]
            entry[ab] = {k: round(v, 1) for k, v in q.items()}
        log.append(entry)
    json.dump(log, open(g["OUT"] + ".castle_refine.json", "w"), indent=0)
    if TAILB:
        for t in range(T):
            g["solve_tail"](t)
    print("CASTLE_REFINE frames", len(log), "mean gain", round(float(np.mean([e.get("iouGain", 0) for e in log] or [0])), 3))
