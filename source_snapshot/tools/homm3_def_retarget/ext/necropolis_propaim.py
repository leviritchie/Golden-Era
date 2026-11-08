"""Necropolis: aim held props (swords, staffs, scythes) at the DEF prop by the silhouette residual.

The shared `silhouetteRefine.propAim` scores a prop swing by whole-body IoU, where a thin
blade moves the score by less than its angle penalty, so swords stayed where the capture
left them (flat behind the head while the DEF holds them raised). Here each frame's score
counts only DEF pixels the rest of the body does *not* explain (the residual, where the DEF
prop must be), minus prop pixels that fall outside the DEF silhouette, so the prop alone
decides. The swing about the camera axis is scanned over +-range degrees (full circle by
default; a symmetric staff wants less so it cannot flip end over end), with a tilt
toward/away from the camera, about the wrist; a small penalty keeps it near the previous
frame's answer. Runs at before_keys, after the whole-body refine (so dx/dy are baked in);
use it instead of `propAim` in silhouetteRefine.

Config: "propAimResidual": {"bones": ["RightHand"], "step": 5, "tilts": [-60,-30,0,30,60],
"range": 180, "outsideWeight": 0.5, "smooth": 0.0005, "bodyDilate": 2, "rigidMin": 0.99, "minGain": 0}.
minGain: a swing is applied only if it covers more than this many residual pixels beyond the unswung
prop (0, 0). Without it, where the DEF prop is hidden in front of the body the residual is empty
and the outside penalty alone wins by hiding the prop over the body (h3_lich_master attack end:
staff flung horizontal across the chest). debugFrames: [t...] saves resid/unswung/chosen masks
as <blend>.propaim_<t>.npy.
"""
import json
import math
import numpy as np
import bpy
from mathutils import Matrix, Vector


def _mask(path):
    img = bpy.data.images.load(path, check_existing=True)
    a = np.array(img.pixels[:]).reshape(img.size[1], img.size[0], 4)[::-1, :, 3] > 0.99
    bpy.data.images.remove(img)
    return a


def _dilate(m, r):
    g = m.copy()
    for _ in range(r):
        h = g.copy()
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            h |= np.roll(np.roll(g, dy, 0), dx, 1)
        g = h
    return g


def before_keys(g):
    cfg = g["cfg"]
    pc = cfg.get("propAimResidual")
    if not pc:
        return
    posed_world, rest, body = g["posed_world"], g["rest"], g["body"]
    ox, oy, s_px, SW, SH = g["ox"], g["oy"], g["s_px"], g["SW"], g["SH"]
    R_, U_, Fw = np.array(g["right"]), np.array(g["up"]), np.array(g["fwd_cam"])
    frames = json.load(open(g["MASTER"]))["frames"]
    V0 = np.array([v.co[:] for v in body.data.vertices]); Vh = np.c_[V0, np.ones(len(V0))]
    names = list(posed_world[0].keys()); col = {n: i for i, n in enumerate(names)}
    gname = {gr.index: gr.name for gr in body.vertex_groups}
    Wm = np.zeros((len(V0), len(names)))
    for v in body.data.vertices:
        for gr in v.groups:
            if gname[gr.group] in col:
                Wm[v.index, col[gname[gr.group]]] += gr.weight
    Wm /= np.maximum(Wm.sum(1, keepdims=True), 1e-9)
    restinv = {n: np.array(rest[n].inverted()) for n in names}

    def skin(A, rows):
        out = np.zeros((rows.sum(), 3)); Vr = Vh[rows]; Wr = Wm[rows]
        for n, i in col.items():
            w = Wr[:, i]
            if w.max() <= 0:
                continue
            out += w[:, None] * (Vr @ (np.array(A[n]) @ restinv[n]).T)[:, :3]
        return out

    def splat(P, dil=1):
        x = np.round(ox + s_px * (P @ R_)).astype(int); y = np.round(oy - s_px * (P @ U_)).astype(int)
        ok = (x >= 0) & (x < SW) & (y >= 0) & (y < SH)
        m = np.zeros((SH, SW), bool); m[y[ok], x[ok]] = True
        return _dilate(m, dil)

    step = pc.get("step", 5); rng = pc.get("range", 180); tilts = pc.get("tilts", [-60, -30, 0, 30, 60])
    wout, lam = pc.get("outsideWeight", 0.5), pc.get("smooth", 0.0005)
    log = {}
    for hb in pc.get("bones", []):
        rows = Wm[:, col[hb]] >= pc.get("rigidMin", 0.99)
        # the prop is the far part of the rigid hand region (the fist itself stays put)
        other = ~rows
        prev = (0.0, 0.0); log[hb] = []
        for t in range(len(posed_world)):
            A = posed_world[t]
            if A[hb].to_3x3().determinant() < 1e-6:          # body hidden (shatter / shrink)
                log[hb].append(None); continue
            target = _mask(frames[t]["sourcePng"])
            bodym = splat(skin(A, other), pc.get("bodyDilate", 2))
            resid = target & ~bodym
            Pp = skin(A, rows); piv = np.array(A[hb].translation)
            pdir = Pp.mean(0) - piv
            best = None; zero_sc = None
            for a2 in tilts:
                ax2 = np.cross(Fw, pdir); ax2 /= max(np.linalg.norm(ax2), 1e-9)
                R2 = np.array(Matrix.Rotation(math.radians(a2), 3, Vector(tuple(ax2))))
                Q = (Pp - piv) @ R2.T
                for a1 in range(-rng, rng + 1, step):
                    R1 = np.array(Matrix.Rotation(math.radians(a1), 3, Vector(tuple(Fw))))
                    m = splat(Q @ R1.T + piv)
                    d1 = abs((a1 - prev[0] + 180) % 360 - 180); d2 = abs(a2 - prev[1])
                    hit = int((m & resid).sum())
                    sc = hit - wout * (m & ~target).sum() - lam * m.sum() * (d1 + d2)
                    if a1 == 0 and a2 == 0:
                        zero_sc = hit
                    if best is None or sc > best[0]:
                        best = (sc, a1, a2, hit)
            if pc.get("minGain", 0) > 0 and zero_sc is not None and best[3] - zero_sc <= pc["minGain"]:
                best = (0, 0, 0, zero_sc)
            _, a1, a2, _ = best; prev = (a1, a2)
            if t in pc.get("debugFrames", []):          # resid (red), unswung prop (green), chosen prop (blue)
                R1 = np.array(Matrix.Rotation(math.radians(a1), 3, Vector(tuple(Fw))))
                ax2_ = np.cross(Fw, pdir); ax2_ /= max(np.linalg.norm(ax2_), 1e-9)
                R2 = np.array(Matrix.Rotation(math.radians(a2), 3, Vector(tuple(ax2_))))
                img = np.zeros(target.shape + (3,), np.uint8); img[target] = 60
                img[resid, 0] = 255; img[splat(Pp), 1] = 255; img[splat((Pp - piv) @ R2.T @ R1.T + piv), 2] = 255
                np.save(g["OUT"] + f".propaim_{t:03d}.npy", img)
            ax2 = np.cross(Fw, pdir); ax2 /= max(np.linalg.norm(ax2), 1e-9)
            pv = Vector(tuple(piv))
            Rw = (Matrix.Translation(pv) @ Matrix.Rotation(math.radians(a1), 4, Vector(tuple(Fw)))
                  @ Matrix.Rotation(math.radians(a2), 4, Vector(tuple(ax2))) @ Matrix.Translation(-pv))
            A[hb] = Rw @ A[hb]
            log[hb].append([a1, a2])
    json.dump(log, open(g["OUT"] + ".propaim.json", "w"))
    print("PROPAIM", {k: sum(1 for x in v if x) for k, v in log.items()})
