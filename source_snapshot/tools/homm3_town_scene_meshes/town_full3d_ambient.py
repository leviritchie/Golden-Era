#!/usr/bin/env python3
"""Full-3D town lane: ambient life (smoke, glows, embers, motes, mist, spindrift, soaring birds, bobbing bodies) placed
from a per-town spec, every effect anchored on the surface that is actually staged.

    TOWN_FULL3D_FACTION=tower TOWN_FULL3D_CANDIDATE=<cand> python town_full3d_ambient.py reanchor
    TOWN_FULL3D_FACTION=tower TOWN_FULL3D_CANDIDATE=<cand> python town_full3d_ambient.py stage [--spec <json>]
    TOWN_FULL3D_FACTION=tower TOWN_FULL3D_CANDIDATE=<cand> python town_full3d_ambient.py sheet   (authoring grid)

Why: town_full3d_fx measures effects on HoMM3 DEF frames and places them on the relief depth of its day. A later
re-depth of the bodies (the no-split MoGe bodies, contact seating, buildings-win) leaves them floating or buried, and a
town has DEFs for a handful of buildings only. Here every position comes from one query: the rest camera's ray through a
frame px, intersected with that prefab's own staged Mesh_* triangles (no z-buffer image, so canvas px outside the
1920x1080 frame -- an outpainted ring -- work as well). Re-running after any depth change re-anchors everything.

reanchor  every particle group / Fx_ bin that is not ours (Fx_Amb_*) slides along its rest ray (a uniform scale of its
          position, its scale, and an Fx_ bin's vertices: the rest projection is unchanged) to FRONT_PULL_M in front of
          its own prefab's surface under it. A group whose px hits nothing (a bolt over a roof) takes the depth of the
          first surface below it in its column (the roof it hangs over). Two-way, unlike town_t2_fx_occlusion.snap.
stage     drops this tool's previous Fx_Amb_* pieces and stages the spec's. Spec (town_full3d_factions/<f>_ambient.json):
              {"effects": [{"id": "forge", "layers": ["tbtwblak"], "kind": "glow", "px": [960, 600], ...}, ...]}
          px / sizes are rest-frame px (1920x1080; the outpainted ring is negative or beyond). "layers": prefabs whose
          surface carries the effect (one copy each, e.g. every upgrade level of a building); "environment" for the
          terrain. An anchor px that misses the surface snaps to the nearest hit within "snap" px (default 16); none
          FAILS. Kinds and their knobs: KINDS below (each knob documented in its function).
Particles use the faction's vanilla VfxUber materials (stronghold_full3d_fx.Mats); birds use a generated silhouette.
Proof tier: generated artifact; motion is seen in editor renders (particles) / in game.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import stronghold_full3d_common as SC  # noqa: E402
import stronghold_full3d_fx as SF  # noqa: E402
import stronghold_full3d_scene as S  # noqa: E402
import stronghold_full3d_terrain as T  # noqa: E402

FRONT_PULL_M = 0.6      # effects sit this far (painting m) in front of the surface they are anchored on
SNAP_PX = 16
TAG = "Fx_Amb_"


def unlink(p: Path):
    if p.exists():
        p.unlink()


# ------------------------------------------------------------------------------------------------ surface queries
class Surf:
    """A prefab's staged Mesh_* triangles (bins without pos/rot), queried by rest-camera rays through frame px."""

    def __init__(self, sc, rows: dict, key: str):
        self.sc, self.cam = sc, sc.cam
        Ps, Fs, off = [], [], 0
        for b in rows.get(key, {}).get("bins", []):
            if not b["name"].startswith("Mesh_") or b.get("pos") or b.get("rot"):
                continue
            v, _, _, subs = S.read_bin(S.STAGE / key / f"{b['name']}.bytes")
            Ps.append(sc.cpos + (np.asarray(v, np.float64) / sc.scale) @ sc.C.T)
            Fs.append(np.concatenate(subs).reshape(-1, 3) + off)
            off += len(v)
        if not Ps:
            raise SystemExit(f"ambient: {key} has no staged Mesh_* surface")
        self.P = np.concatenate(Ps)
        self.F = np.concatenate(Fs)
        px, py, zc = T.project(self.cam, self.P)
        tx, ty = px[self.F], py[self.F]
        ok = (zc[self.F] > 0).all(1)
        self.F, tx, ty = self.F[ok], tx[ok], ty[ok]
        self.bx0, self.bx1, self.by0, self.by1 = tx.min(1), tx.max(1), ty.min(1), ty.max(1)

    def cast(self, fx: float, fy: float):
        """Nearest hit (world point, forward depth) of the ray through frame px (fx, fy), or None."""
        sel = np.nonzero((self.bx0 <= fx) & (self.bx1 >= fx) & (self.by0 <= fy) & (self.by1 >= fy))[0]
        if not len(sel):
            return None
        o = self.cam["pos"]
        d = T.rays(self.cam, np.array([fx]), np.array([fy]))[0]
        a, b, c = (self.P[self.F[sel, k]] for k in range(3))
        e1, e2 = b - a, c - a
        p = np.cross(d, e2)
        det = (e1 * p).sum(1)
        good = np.abs(det) > 1e-12
        inv = np.where(good, 1 / np.where(good, det, 1), 0)
        s = o - a
        u = (s * p).sum(1) * inv
        q = np.cross(s, e1)
        v = (q * d).sum(1) * inv
        t = (e2 * q).sum(1) * inv
        hit = good & (u >= -1e-6) & (v >= -1e-6) & (u + v <= 1 + 1e-6) & (t > 0)
        if not hit.any():
            return None
        t = t[hit].min()
        w = o + d * t
        return w, float((w - o) @ self.cam["fwd"])

    def anchor(self, fx: float, fy: float, snap: float = SNAP_PX):
        """cast(), or the nearest px within `snap` that hits (rings outward); -> (world, z, (fx, fy)) or None."""
        h = self.cast(fx, fy)
        if h:
            return h[0], h[1], (fx, fy)
        for r in range(2, int(snap) + 1, 2):
            n = max(8, int(2 * math.pi * r / 2))
            for k in range(n):
                a = 2 * math.pi * k / n
                x, y = fx + r * math.cos(a), fy + r * math.sin(a)
                h = self.cast(x, y)
                if h:
                    return h[0], h[1], (x, y)
        return None

    def below(self, fx: float, fy: float, reach: float = 400):
        """The first surface straight below px (fx, fy) in its column (what a floating piece hangs over)."""
        for dy in range(0, int(reach), 3):
            h = self.cast(fx, fy + dy)
            if h:
                return h
        return None


def mpp(cam, z: float) -> float:
    """Painting metres per rest-frame px at forward depth z."""
    return 2 * z * math.tan(math.radians(cam["fov"]) / 2) / SC.H


# ------------------------------------------------------------------------------------------------ reanchor
def reanchor(sc, rows: dict) -> dict:
    rep = {}
    for key, row in rows.items():
        if key == S.ENV_KEY:
            continue
        groups = [g for g in row.get("particles") or [] if not g["name"].startswith(TAG)]
        fxb = [b for b in row.get("bins") or [] if b["name"].startswith("Fx_")]
        if not groups and not fxb:
            continue
        surf = Surf(sc, rows, key)

        def target(wp):
            px, py, z = T.project(sc.cam, wp[None])
            fx, fy, z = float(px[0]), float(py[0]), float(z[0])
            h = surf.anchor(fx, fy)
            how = "relief"
            if h is None:
                h = surf.below(fx, fy)
                how = "over"
                if h is None:
                    return None, z, how
                h = (h[0], h[1], (fx, fy))
            return h[1] - FRONT_PULL_M, z, how

        for g in groups:
            wp = sc.cpos + (np.asarray(g["pos"], np.float64) / sc.scale) @ sc.C.T   # prefab local -> world
            tz, z, how = target(wp)
            if tz is None:
                rep[g["name"]] = {"skipped": "no surface under it"}
                continue
            r = tz / z
            g["pos"] = [float(x) * r for x in g["pos"]]
            g["scale"] = float(g["scale"]) * r
            rep[g["name"]] = {"fromZ": round(z, 2), "toZ": round(tz, 2), "slide": round(r, 4), "how": how}
        for b in fxb:
            p = S.STAGE / key / f"{b['name']}.bytes"
            v, n, uv, subs = S.read_bin(p)
            import town_t2_fx_occlusion as OC
            c = OC.bin_centre(v, b)
            wp = sc.cpos + (np.asarray(c) / sc.scale) @ sc.C.T
            tz, z, how = target(wp)
            if tz is None:
                rep[b["name"]] = {"skipped": "no surface under it"}
                continue
            r = tz / z
            unlink(p)
            S.write_bin(p, np.asarray(v, np.float64) * r, n, uv, subs)
            if b.get("pos"):
                b["pos"] = [float(x) * r for x in b["pos"]]
            rep[b["name"]] = {"fromZ": round(z, 2), "toZ": round(tz, 2), "slide": round(r, 4), "how": how}
    return rep


# ------------------------------------------------------------------------------------------------ kinds
class K:
    """One effect being staged: its anchor, metres per px there, the materials."""

    def __init__(self, sc, M, A, key, e, w, z, fpx):
        self.sc, self.M, self.A, self.key, self.e, self.w, self.z, self.fpx = sc, M, A, key, e, w, z, fpx
        self.m = mpp(sc.cam, z)

    def px(self, name, default):
        return float(self.e.get(name, default)) * self.m

    def col(self, default):
        return [float(x) for x in self.e.get("colour", default)]

    def op(self, default):
        """Vertex alpha for a linear opacity: VfxUber squares vertex alpha (vcol.a^2), so `alpha` in a spec is the
        opacity seen on screen, not the raw stream value."""
        return math.sqrt(float(self.e.get("alpha", default)))

    def group(self, name, systems, at=None):
        c = self.w if at is None else at
        return {"name": name, "pos": [float(x) for x in self.sc.local(c[None, :])[0]], "rot": [0.0, 0.0, 0.0, 1.0],
                "scale": float(self.sc.scale), "systems": systems}


def sqk(keys):
    """Alpha keys (t, a, ...) as linear opacity -> the vertex alpha VfxUber squares back."""
    return [math.sqrt(k) if i % 2 else k for i, k in enumerate(keys)]


def k_smoke(X: K, nm):
    """Chimney smoke. width (px, at the flue), rise (px, plume height), period (s), colour (sRGB 0..1), density."""
    w, h, per = X.px("width", 8), X.px("rise", 70), float(X.e.get("period", 3.0))
    v = h / per
    dens = float(X.e.get("density", 1.0))
    return [X.group(nm, [SF.psys("smoke", X.A["puff"], lifetime=[per * 0.85, per * 1.15], speed=[0],
                                 velY=[v * 0.8, v * 1.1], velX=[-v * 0.05, v * 0.3], size=[w * 4.5, w * 6.0],
                                 rate=round((8.0 / per + 2.0) * dens, 2), maxParticles=60, radius=w * 0.2,
                                 color=X.col([0.55, 0.54, 0.53]) + [X.op(min(0.6 * dens, 0.9))],
                                 alphaKeys=sqk([0, 0, 0.12, 1, 0.6, 0.6, 1, 0]), sizeKeys=[0, 0.4, 1, 2.2],
                                 rotation=[0, 360], rotSpeed=[-25, 25], noise=w * 0.6, noiseFreq=0.4,
                                 customUV=False)])]


FLICKER = {   # alpha keys (t, a) over one particle life: how the light breathes
    "fire": [0, 0, 0.1, 1, 0.3, 0.7, 0.55, 1, 0.8, 0.6, 1, 0],
    "candle": [0, 0, 0.15, 0.9, 0.4, 1, 0.6, 0.8, 0.85, 1, 1, 0],
    "breathe": [0, 0, 0.5, 1, 1, 0],
}


def k_glow(X: K, nm):
    """A light: size (px), colour, flicker (fire | candle | breathe), intensity (0..1), period (s, breathe)."""
    s = X.px("size", 18)
    fl = X.e.get("flicker", "fire")
    life = float(X.e.get("period", 0.5 if fl != "breathe" else 3.0))
    a = float(X.e.get("intensity", 0.45))
    return [X.group(nm, [SF.psys("glow", X.A["glow"], lifetime=[life * 0.7, life * 1.3], speed=[0],
                                 size=[s * 0.85, s * 1.15], rate=round(2.6 / life, 3), maxParticles=6,
                                 radius=s * 0.04, color=X.col([1.0, 0.62, 0.25]) + [a], alphaKeys=FLICKER[fl],
                                 customUV=False)])]


def k_embers(X: K, nm):
    """Sparks rising off a fire: width (px), rise (px), colour, rate (/s)."""
    w, h = X.px("width", 10), X.px("rise", 50)
    life = float(X.e.get("life", 1.4))
    v = h / life
    return [X.group(nm, [SF.psys("embers", X.A["glint"], lifetime=[life * 0.6, life * 1.2], speed=[0],
                                 velY=[v * 0.6, v * 1.2], size=[X.m * 1.2, X.m * 2.4],
                                 rate=float(X.e.get("rate", 10)), maxParticles=40, shape="box",
                                 shapeScale=[w, w * 0.3, w * 0.3], color=X.col([1.0, 0.55, 0.18]) + [1.0],
                                 alphaKeys=[0, 0, 0.1, 1, 0.7, 0.8, 1, 0], sizeKeys=[0, 1, 1, 0.3],
                                 noise=w * 0.5, noiseFreq=1.2, customUV=False)])]


def k_glints(X: K, nm):
    """Sparkles twinkling over a box: w, h (px), colour, rate (/s), life (s), spark (px)."""
    w, h = X.px("w", 30), X.px("h", 30)
    life = float(X.e.get("life", 0.6))
    sp = X.px("spark", 2.2)
    rate = float(X.e.get("rate", 4))
    return [X.group(nm, [SF.psys("glints", X.A["glint"], lifetime=[life * 0.6, life * 1.2], speed=[0],
                                 size=[sp * 0.6, sp * 1.3], rate=rate, maxParticles=max(6, int(rate * life * 3)),
                                 shape="box", shapeScale=[w, h, min(w, h) * 0.2], color=X.col([1, 0.95, 0.8]) + [1.0],
                                 alphaKeys=[0, 0, 0.3, 1, 1, 0], sizeKeys=[0, 0, 0.35, 1, 1, 0], customUV=False)])]


def k_motes(X: K, nm):
    """Magic motes circling a point: radius (px), count (alive), period (s per orbit), colour, rise (px over a life)."""
    r = X.px("radius", 30)
    per = float(X.e.get("period", 6.0))
    n = int(X.e.get("count", 8))
    life = float(X.e.get("life", per * 1.5))
    rise = X.px("rise", 0) / life
    sp = X.px("spark", 3.0)
    return [X.group(nm, [SF.psys("motes", X.A["glint"], lifetime=[life * 0.8, life * 1.2], speed=[0],
                                 size=[sp * 0.6, sp * 1.2], rate=round(n / life, 3), maxParticles=n * 2,
                                 shape="circle", radius=r, radiusThickness=0.15, shapeRot=[90, 0, 0],
                                 orbitalY=[2 * math.pi / per * 0.9, 2 * math.pi / per * 1.1], velY=[rise * 0.7, rise],
                                 color=X.col([0.6, 0.85, 1.0]) + [1.0], alphaKeys=[0, 0, 0.15, 1, 0.5, 0.6, 0.75, 1, 1, 0],
                                 noise=r * 0.06, noiseFreq=0.6, customUV=False)])]


def k_mist(X: K, nm):
    """Low mist / cloud wisps drifting over a box: w, h (px), drift (px/s, +x = right), colour, alpha, count."""
    w, h = X.px("w", 200), X.px("h", 30)
    vx = X.px("drift", 4)
    life = float(X.e.get("life", 14))
    n = int(X.e.get("count", 6))
    sz = X.px("puff", max(float(X.e.get("h", 30)) * 1.6, 30))
    return [X.group(nm, [SF.psys("mist", X.A["spray"], lifetime=[life * 0.8, life * 1.2], speed=[0],
                                 velX=[vx * 0.7, vx * 1.3], size=[sz * 0.8, sz * 1.3], rate=round(n / life, 3),
                                 maxParticles=n * 2, shape="box", shapeScale=[w, h, h * 0.5],
                                 color=X.col([0.95, 0.97, 1.0]) + [X.op(0.4)],
                                 alphaKeys=sqk([0, 0, 0.3, 1, 0.7, 1, 1, 0]), sizeKeys=[0, 0.8, 1, 1.3],
                                 rotation=[0, 360], rotSpeed=[-6, 6])])]


def k_spindrift(X: K, nm):
    """Snow blown off a ridge: width (px of ridge), reach (px the plume travels), dir [dx, dy] (screen, y down),
    gust (s between bursts)."""
    w, reach = X.px("width", 40), X.px("reach", 120)
    dx, dy = X.e.get("dir", [1, -0.15])
    life = float(X.e.get("life", 3.5))
    v = reach / life
    nd = math.hypot(dx, dy) or 1
    return [X.group(nm, [SF.psys("drift", X.A["spray"], lifetime=[life * 0.7, life * 1.2], speed=[0],
                                 velX=[v * dx / nd * 0.7, v * dx / nd * 1.2], velY=[-v * dy / nd * 0.7, -v * dy / nd * 1.2],
                                 size=[w * 0.35, w * 0.6], rate=float(X.e.get("rate", 3)), maxParticles=30,
                                 shape="box", shapeScale=[w, w * 0.15, w * 0.3],
                                 color=X.col([1, 1, 1]) + [X.op(0.55)],
                                 alphaKeys=sqk([0, 0, 0.15, 1, 0.6, 0.5, 1, 0]), sizeKeys=[0, 0.5, 1, 2.2],
                                 rotation=[0, 360], rotSpeed=[-30, 30], noise=w * 0.1, noiseFreq=0.5)])]


def bird_png(path: Path):
    """A soaring raptor silhouette seen from below/side (wings in a shallow M), white on black, 128 x 64."""
    import cv2
    from PIL import Image
    im = np.zeros((64, 128), np.uint8)
    pts = np.array([[4, 30], [24, 22], [46, 24], [60, 34], [64, 38], [68, 34], [82, 24], [104, 22], [124, 30],
                    [104, 28], [84, 32], [70, 42], [64, 46], [58, 42], [44, 32], [24, 28]], np.int32)
    cv2.fillPoly(im, [pts], 255)
    cv2.ellipse(im, (64, 40), (5, 8), 0, 0, 360, 255, -1)
    im = cv2.GaussianBlur(im, (0, 0), 0.8)
    path.parent.mkdir(parents=True, exist_ok=True)
    unlink(path)
    Image.fromarray(np.dstack([im] * 3)).save(path)


def k_birds(X: K, nm):
    """Soaring birds circling: radius (px), count, period (s per circle), span (px wingspan), colour (dark),
    out (share of the anchor depth the flock sits in front of its surface)."""
    pth = S.STAGE / X.key / "amb_bird.png"
    bird_png(pth)
    asset = f"{S.ASSET_ROOT}/{X.key}/amb_bird.png"
    mat = X.M.material("Homm3ConfluxVfxUber", [X.M.tex("_Texture", asset, clamp=True),
                                               X.M.tex("_Mask", asset, clamp=True)],
                       {"_Min": 0.05, "_Max": 0.5, "_Lerp": 1.0, "_Multiply": 1.0, "_Blend": 1.0, "_xSpeed01": 0,
                        "_ySpeed01": 0, "_xSpeed02": 0, "_ySpeed02": 0, "_UseTwo": 0.0, "_CameraOffset": 0.0,
                        "_UseCamOffset": 0.0}, {"_Color": X.col([0.12, 0.11, 0.1]) + [1.0]})
    r = X.px("radius", 60)
    per = float(X.e.get("period", 16))
    n = int(X.e.get("count", 3))
    span = X.px("span", 7)
    life = per * 1.6
    # a soar: wings held, now and then tilting (span shrinks as the bird banks) -- 8 keys at most per curve
    tilt = [0, 1, 0.2, 1, 0.3, 0.75, 0.4, 1, 0.65, 1, 0.75, 0.7, 0.85, 1, 1, 1]
    return [X.group(nm, [SF.psys("birds", mat, lifetime=[life * 0.9, life * 1.1], speed=[0], size=[span * 0.85, span],
                                 sizeY=[span * 0.5, span * 0.55], sizeKeys=tilt, rate=round(n / life, 3),
                                 maxParticles=n * 2, shape="circle", radius=r, radiusThickness=0.3,
                                 shapeRot=[90, 0, 0], orbitalY=[2 * math.pi / per * 0.85, 2 * math.pi / per * 1.15],
                                 velY=[-X.m * 0.4, X.m * 0.4], color=[1, 1, 1, 1],
                                 alphaKeys=[0, 0, 0.08, 1, 0.92, 1, 1, 0], customUV=False)])]


KINDS = {"smoke": k_smoke, "glow": k_glow, "embers": k_embers, "glints": k_glints, "motes": k_motes, "mist": k_mist,
         "spindrift": k_spindrift, "birds": k_birds}


def quat(R: np.ndarray) -> list[float]:
    m = R
    t = np.trace(m)
    if t > 0:
        s = math.sqrt(t + 1) * 2
        w, x, y, z = 0.25 * s, (m[2, 1] - m[1, 2]) / s, (m[0, 2] - m[2, 0]) / s, (m[1, 0] - m[0, 1]) / s
    else:
        i = int(np.argmax(np.diag(m)))
        if i == 0:
            s = math.sqrt(1 + m[0, 0] - m[1, 1] - m[2, 2]) * 2
            w, x, y, z = (m[2, 1] - m[1, 2]) / s, 0.25 * s, (m[0, 1] + m[1, 0]) / s, (m[0, 2] + m[2, 0]) / s
        elif i == 1:
            s = math.sqrt(1 + m[1, 1] - m[0, 0] - m[2, 2]) * 2
            w, x, y, z = (m[0, 2] - m[2, 0]) / s, (m[0, 1] + m[1, 0]) / s, 0.25 * s, (m[1, 2] + m[2, 1]) / s
        else:
            s = math.sqrt(1 + m[2, 2] - m[0, 0] - m[1, 1]) * 2
            w, x, y, z = (m[1, 0] - m[0, 1]) / s, (m[0, 2] + m[2, 0]) / s, (m[1, 2] + m[2, 1]) / s, 0.25 * s
    return [float(x), float(y), float(z), float(w)]


def bob(sc, rows: dict, key: str, e: dict) -> dict:
    """A whole body rides up and down (a skyship on its balloons): the body bin gets a holder whose local z is world
    up (its vertices pre-rotated by the inverse, so the rest pose is unchanged) and keyed poses: z = amp sin, x = a
    small sway, a gentle rock about the holder's y. amp (px at the body's depth), period (s), sway (share of amp),
    rockDeg."""
    row = rows[key]
    name = e.get("bin") or next(b["name"] for b in row["bins"] if b["name"].startswith("Mesh_Body"))
    b = next(b for b in row["bins"] if b["name"] == name)
    p = S.STAGE / key / f"{name}.bytes"
    v, n, uv, subs = S.read_bin(p)
    v = np.asarray(v, np.float64)
    if b.get("rot") and not b.get(TAG + "bob"):
        raise SystemExit(f"ambient: {key}/{name} already has a pose; bob needs a free body bin")
    if b.get(TAG + "bob"):              # re-stage: undo our previous holder first
        R0 = np.asarray(b[TAG + "bob"]["R"])
        v = v @ R0.T
        n = np.asarray(n) @ R0.T
    up = sc.local_dir(np.array([0.0, 1.0, 0.0]))
    zc = up / np.linalg.norm(up)
    xc = np.cross([0.0, 0.0, 1.0], zc)
    xc /= np.linalg.norm(xc)
    yc = np.cross(zc, xc)
    R = np.stack([xc, yc, zc], 1)             # holder local -> prefab local
    wc = sc.cpos + (v.mean(0) / sc.scale) @ sc.C.T
    zf = float((wc - sc.cam["pos"]) @ sc.cam["fwd"])
    amp = float(e.get("amp", 6)) * mpp(sc.cam, zf) * sc.scale
    per = float(e.get("period", 7.0))
    sway = float(e.get("sway", 0.35))
    rock = float(e.get("rockDeg", 1.2))
    keys = []
    for i in range(8):
        a = 2 * math.pi * i / 8
        keys += [amp * sway * math.cos(a), amp * math.sin(a), rock * math.sin(a + 0.8)]
    unlink(p)
    S.write_bin(p, v @ R, np.asarray(n) @ R, uv, subs)
    b.update({"pos": [0.0, 0.0, 0.0], "rot": quat(R), "keyPeriod": per, "keyPose": [round(k, 5) for k in keys],
              TAG + "bob": {"R": R.tolist()}})
    return {"bin": name, "ampPx": e.get("amp", 6), "periodS": per, "depthM": round(zf, 1)}


def fxmesh_bin(sc, key: str, m: dict) -> dict:
    """A kind's shader mesh (an aurora curtain): m = {"fxmesh": name (Fx_Amb_*), "v": world vertices (n, 3), "uv": (n, 2),
    "tris": (k, 3), "material": SF.Mats material, optional "uv2": (n, 2)} -> an fxmesh bin row (prefab frame; drawn by
    a bone-less SkinnedMeshRenderer, which the runtime leaves its own material)."""
    name = m["fxmesh"]
    if not name.startswith(TAG):
        raise SystemExit(f"ambient: fxmesh {name} must be named {TAG}*")
    v = sc.local(np.asarray(m["v"], np.float64))
    n = np.tile([0.0, 0.0, -1.0], (len(v), 1))
    p = S.STAGE / key / f"{name}.bytes"
    unlink(p)
    S.write_bin(p, v, n, np.asarray(m["uv"], np.float32), [np.asarray(m["tris"], np.int32)])
    row = {"name": name, "mesh": f"{S.ASSET_ROOT}/{key}/{name}.bytes", "kind": "fxmesh", "material": m["material"],
           "pos": [0.0, 0.0, 0.0], "rot": [0.0, 0.0, 0.0, 1.0]}
    if m.get("uv2") is not None:
        p2 = S.STAGE / key / f"{name}_uv2.bytes"
        unlink(p2)
        p2.write_bytes(np.asarray(m["uv2"], np.float32).tobytes())
        row["uv2"] = f"{S.ASSET_ROOT}/{key}/{name}_uv2.bytes"
    return row


def stage(sc, rows: dict, spec: dict) -> dict:
    M = SF.Mats(S.STAGE, S.ASSET_ROOT, S.SHADER_DIR)
    A = M.standard()
    # chimney puffs: a soft smoke sprite in a round falloff, alpha-blended with no noise threshold -- the spray recipe's
    # TileNoise cut leaves nothing of a puff a few px wide, and its 0.75 blend washes grey smoke out against snow
    A["puff"] = M.uber("smoke_06_vfx", None, "glow_08_vfx", mn=0.0, mx=0.3, lerp=1.0, blend=1.0, color=1.0)
    for key, row in rows.items():
        row["particles"] = [g for g in row.get("particles") or [] if not g["name"].startswith(TAG)]
        if row.get("bins"):
            row["bins"] = [b for b in row["bins"] if not b["name"].startswith(TAG)]
    surfs: dict = {}
    rep = {}
    kinds = dict(KINDS)
    misses: list[str] = []     # every anchor that misses is reported together, then the stage FAILS
    # a town's own kinds (its lava drips, swamp bubbles ...): town_full3d_factions/<f>_ambient_kinds.py exporting
    # KINDS = {"name": fn(X: K, nm) -> [particle systems]}, written like the kinds above (import town_full3d_ambient
    # for K / sqk / SF); a kind that proves general moves here
    kp = HERE / "town_full3d_factions" / f"{SC.FACTION}_ambient_kinds.py"
    if kp.is_file():
        import importlib.util
        ks = importlib.util.spec_from_file_location(f"{SC.FACTION}_ambient_kinds", kp)
        km = importlib.util.module_from_spec(ks)
        ks.loader.exec_module(km)
        kinds.update(km.KINDS)
    for e in spec["effects"]:
        for lid in e["layers"]:
            key = S.ENV_KEY if lid == "environment" else S.PREFIX + lid
            if key not in rows:
                raise SystemExit(f"ambient: {e['id']}: no staged prefab {key}")
            nm = f"{TAG}{e['id']}_{lid}"
            if e["kind"] == "bob":
                rep[nm] = bob(sc, rows, key, e)
                continue
            if e["kind"] not in kinds:
                raise SystemExit(f"ambient: {e['id']}: unknown kind {e['kind']} (kinds: {sorted(kinds)} + bob)")
            if key not in surfs:
                surfs[key] = Surf(sc, rows, key)
            fx, fy = e["px"]
            h = surfs[key].anchor(fx, fy, float(e.get("snap", SNAP_PX)))
            if h is None:
                bb = surfs[key]
                misses.append(f"{e['id']}: px {e['px']} hits no {key[len(S.PREFIX):]} surface within "
                              f"{e.get('snap', SNAP_PX)} px (surface bbox x {bb.bx0.min():.0f}..{bb.bx1.max():.0f}, "
                              f"y {bb.by0.min():.0f}..{bb.by1.max():.0f})")
                continue
            w, z, used = h
            out = float(e.get("out", 0.0))           # birds and wisps hang in front of their surface
            pull = FRONT_PULL_M + out * z
            d = T.rays(sc.cam, np.array([used[0]]), np.array([used[1]]))[0]
            d = d / (d @ sc.cam["fwd"])
            w = sc.cam["pos"] + d * (z - pull)
            X = K(sc, M, A, key, e, w, z - pull, used)
            row = rows[key]
            for out_ in kinds[e["kind"]](X, nm):
                if "fxmesh" in out_:
                    row.setdefault("bins", []).append(fxmesh_bin(sc, key, out_))
                else:
                    row.setdefault("particles", []).append(out_)
            rep[nm] = {"kind": e["kind"], "px": [round(used[0], 1), round(used[1], 1)], "zM": round(z - pull, 2),
                       "snappedPx": round(math.hypot(used[0] - fx, used[1] - fy), 1)}
    if misses:
        raise SystemExit("ambient: anchors missed their surface:\n  " + "\n  ".join(misses))
    return {"report": rep, "vanillaTextures": M.sources}


# ------------------------------------------------------------------------------------------------ authoring sheet
def sheet(sc, rows: dict) -> dict:
    """Authoring aid for a spec: the rest render with a rest-px grid (labels every 100 px) and every prefab's staged
    surface outlined and named, as work/ambient_sheet.jpg plus 2x quadrant crops ambient_sheet_q<0-3>.jpg; returns
    each prefab's surface bbox in rest px (what `px` in a spec is measured in)."""
    from PIL import Image, ImageDraw
    src = S.RENDERS / "full3d_full.png"
    im = Image.open(src).convert("RGB").resize((SC.W, SC.H), Image.LANCZOS) if src.is_file() else         Image.new("RGB", (SC.W, SC.H), (40, 40, 40))
    d = ImageDraw.Draw(im)
    for g in range(0, SC.W + 1, 50):
        d.line([(g, 0), (g, SC.H)], fill=(255, 255, 0) if g % 100 == 0 else (110, 110, 40), width=1)
    for g in range(0, SC.H + 1, 50):
        d.line([(0, g), (SC.W, g)], fill=(255, 255, 0) if g % 100 == 0 else (110, 110, 40), width=1)
    for g in range(0, SC.W, 100):
        for y in (2, 540, 1066):
            d.text((g + 2, y), str(g), fill=(255, 0, 255))
    for g in range(100, SC.H, 100):
        for x in (2, 960, 1880):
            d.text((x, g + 2), str(g), fill=(255, 0, 255))
    rep = {}
    for i, key in enumerate(k for k in rows if k != S.ENV_KEY):
        try:
            sf = Surf(sc, rows, key)
        except SystemExit:
            continue
        x0, x1 = float(np.percentile(sf.bx0, 1)), float(np.percentile(sf.bx1, 99))
        y0, y1 = float(np.percentile(sf.by0, 1)), float(np.percentile(sf.by1, 99))
        col = tuple(int(c) for c in (np.array([(i * 97) % 255, (i * 57 + 120) % 255, (i * 151 + 60) % 255]) | 64))
        d.rectangle([x0, y0, x1, y1], outline=col, width=2)
        d.text((x0 + 3, y0 + 3), key[len(S.PREFIX):], fill=col)
        rep[key[len(S.PREFIX):]] = [round(x0), round(y0), round(x1), round(y1)]
    out = S.WORK / "ambient_sheet.jpg"
    unlink(out)
    im.save(out, quality=88)
    for q, (x, y) in enumerate(((0, 0), (SC.W // 2, 0), (0, SC.H // 2), (SC.W // 2, SC.H // 2))):
        qp = S.WORK / f"ambient_sheet_q{q}.jpg"
        unlink(qp)
        im.crop((x, y, x + SC.W // 2, y + SC.H // 2)).resize((SC.W, SC.H), Image.LANCZOS).save(qp, quality=88)
    return {"render": str(src), "sheet": str(out), "prefabBboxRestPx": rep}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["reanchor", "stage", "sheet"])
    ap.add_argument("--spec")
    a = ap.parse_args()
    sc = S.Scene()
    rows = json.loads(S.ROWS.read_text(encoding="utf-8"))
    if a.cmd == "sheet":
        print(json.dumps(sheet(sc, rows), indent=1))
        return 0
    if a.cmd == "reanchor":
        rep = reanchor(sc, rows)
    else:
        sp = Path(a.spec) if a.spec else HERE / "town_full3d_factions" / f"{SC.FACTION}_ambient.json"
        rep = stage(sc, rows, json.loads(sp.read_text(encoding="utf-8")))
    unlink(S.ROWS)
    S.ROWS.write_text(json.dumps(rows, indent=1), encoding="utf-8")
    out = S.STAGE.parents[2] / ".." / "work" / f"ambient_{a.cmd}.json"
    out = Path(os.path.normpath(out))
    out.parent.mkdir(parents=True, exist_ok=True)
    unlink(out)
    out.write_text(json.dumps(rep, indent=1), encoding="utf-8")
    print(json.dumps(rep)[:3000])
    print("wrote", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
