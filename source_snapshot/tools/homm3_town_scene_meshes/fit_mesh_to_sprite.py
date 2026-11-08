"""Register a Meshy building mesh to its HoMM3 town-screen sprite under the native city camera.

The pilot seated meshes by a rule (bounds bottom-centre on the sprite's bottom-centre pixel, height =
sprite height, yaw = face camera). That rule is wrong for a 3D object: the sprite's lowest pixel is
the footprint's *front* edge, not its centre, the model's front axis is arbitrary (Meshy), and a
sprite cut by the screen edge has a truncated box. This module instead searches yaw, scale and the
ground contact pixel so the mesh's projected silhouette matches the sprite's alpha mask, with the
object's base resting on the backdrop depth surface at the contact pixel.

Objective: F-beta (beta = 0.5, precision-weighted) between the projected silhouette and the sprite
alpha, both clipped to the frame. Precision-weighted because sprites carry painted ground skirts
(grass, river banks) that the mesh must not try to cover; those skirts are kept as projected 2D
pixels on the depth surface instead.

Coordinates: Unity world space (the camera comes from the installed cityHuman2 scene export). GLB
vertices are converted the way glTFast imports them (x negated). The returned transform is applied
to the glTFast-instantiated root as position, Euler(0, yaw, 0) and uniform scale.
Proof tier: generated artifact (the Unity render re-measures the silhouette independently).
"""
from __future__ import annotations

import math
from pathlib import Path

import cv2
import numpy as np


def load_glb_unity(path: Path) -> tuple[np.ndarray, np.ndarray]:
    import trimesh

    scene = trimesh.load(str(path), force="scene")
    mesh = scene.dump(concatenate=True)
    v = np.asarray(mesh.vertices, np.float64).copy()
    v[:, 0] *= -1.0  # glTFast: right-handed glTF -> left-handed Unity by negating x
    f = np.asarray(mesh.faces, np.int64)
    return v, f


def spire_knee(v: np.ndarray, axis_frac: float = 0.1) -> float:
    """Height (model units, same frame as v) above which only the tallest spire exists: the highest vertex
    farther than axis_frac x model width from the spire's axis (the axis is the xz centroid of the top 5%)."""
    lo, hi = v.min(0), v.max(0)
    y = v[:, 1]
    top = v[y > lo[1] + 0.95 * (hi[1] - lo[1])]
    d = np.linalg.norm(v[:, [0, 2]] - top[:, [0, 2]].mean(0), axis=1)
    return float(y[d > axis_frac * (hi[0] - lo[0])].max())


def knee_remap(v: np.ndarray, knee_y: float, knee_scale: float) -> np.ndarray:
    """Mesh surgery for an over-tall spire: heights above knee_y are compressed by knee_scale."""
    out = v.copy()
    m = out[:, 1] > knee_y
    out[m, 1] = knee_y + (out[m, 1] - knee_y) * knee_scale
    return out


def yaw_matrix(deg: float) -> np.ndarray:
    a = math.radians(deg)
    c, s = math.cos(a), math.sin(a)
    # Unity Quaternion.Euler(0, yaw, 0) applied to a column vector.
    return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])


class Fitter:
    def __init__(self, cam: dict, z: np.ndarray, frame: tuple[int, int], target: np.ndarray,
                 verts: np.ndarray, faces: np.ndarray, down: int = 2):
        self.cam, self.z, self.W, self.H = cam, z, frame[0], frame[1]
        self.down = down
        self.t = math.tan(math.radians(cam["fov"]) / 2)
        self.target = target[::down, ::down] > 0  # frame-sized alpha mask
        ys, xs = np.nonzero(self.target)
        pad = 40 // down
        self.win = (max(0, xs.min() - pad), max(0, ys.min() - pad),
                    min(self.target.shape[1], xs.max() + pad + 1), min(self.target.shape[0], ys.max() + pad + 1))
        self.tgt = self.target[self.win[1]:self.win[3], self.win[0]:self.win[2]]
        # Normalise the model: base at y=0, footprint centred on the origin.
        lo, hi = verts.min(0), verts.max(0)
        self.v0 = verts - np.array([(lo[0] + hi[0]) / 2, lo[1], (lo[2] + hi[2]) / 2])
        self.v_raw = self.v0
        self.faces = faces
        self.model_h = float(hi[1] - lo[1])
        self.model_lo_y = float(lo[1])

    def ray(self, px: float, py: float) -> np.ndarray:
        c = self.cam
        nx = (px / self.W) * 2 - 1
        ny = 1 - (py / self.H) * 2
        return c["fwd"] + c["right"] * nx * self.t * (self.W / self.H) + c["up"] * ny * self.t

    def ground(self, px: float, py: float) -> np.ndarray:
        xi = int(np.clip(px, 0, self.W - 1))
        yi = int(np.clip(py, 0, self.H - 1))
        return self.cam["pos"] + self.ray(px, py) * float(self.z[yi, xi])

    def transform(self, yaw: float, scale: float, px: float, py: float,
                  stretch_y: float = 1.0) -> tuple[np.ndarray, np.ndarray]:
        # stretch_y scales the model's vertical axis before yaw; a yaw about Y commutes with it, so Unity
        # applies it as localScale (s, s * stretch_y, s).
        pos = self.ground(px, py)
        return pos, ((self.v0 * np.array([1.0, stretch_y, 1.0])) @ yaw_matrix(yaw).T) * scale + pos

    def project(self, w: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        c = self.cam
        d = w - c["pos"]
        zc = d @ c["fwd"]
        xc = d @ c["right"]
        yc = d @ c["up"]
        zc = np.maximum(zc, 1e-3)
        px = (xc / (zc * self.t * (self.W / self.H)) + 1) * 0.5 * self.W
        py = (1 - yc / (zc * self.t)) * 0.5 * self.H
        return np.stack([px, py], -1), zc

    def silhouette(self, w: np.ndarray, full: bool = False) -> np.ndarray:
        p, _ = self.project(w)
        p = p / self.down
        if full:
            shape, off = self.target.shape, np.array([0, 0])
        else:
            shape = self.tgt.shape
            off = np.array([self.win[0], self.win[1]])
        tri = np.round((p[self.faces] - off) * 4).astype(np.int32)  # 2 bits sub-pixel
        m = np.zeros(shape, np.uint8)
        cv2.fillPoly(m, list(tri), 1, lineType=cv2.LINE_8, shift=2)
        # fillPoly drops sub-pixel triangles (dense Meshy tessellation at half resolution), leaving a
        # stippled mask; drawing each triangle's outline too makes the coverage conservative-solid.
        cv2.polylines(m, list(tri), True, 1, thickness=1, lineType=cv2.LINE_8, shift=2)
        return m > 0

    def score(self, yaw, scale, px, py, beta=0.5, stretch_y=1.0) -> float:
        if scale <= 0:
            return 0.0
        _, w = self.transform(yaw, scale, px, py, stretch_y)
        s = self.silhouette(w)
        tp = float(np.logical_and(s, self.tgt).sum())
        if tp == 0:
            return 0.0
        prec = tp / float(s.sum())
        rec = tp / float(self.tgt.sum())
        b2 = beta * beta
        return (1 + b2) * prec * rec / (b2 * prec + rec)

    def fit(self, bbox_px: tuple[float, float, float, float], yaws=range(0, 360, 15)) -> dict:
        from scipy.optimize import minimize

        x0, y0, x1, y1 = bbox_px
        px0, py0 = (x0 + x1) / 2, y1 - 0.05 * (y1 - y0)
        zf = float(self.z[int(np.clip(py0, 0, self.H - 1)), int(np.clip(px0, 0, self.W - 1))])
        s0 = ((y1 - y0) / self.H * 2 * zf * self.t) / max(1e-6, self.model_h)

        def neg(p, yaw):
            return -self.score(yaw, p[0], p[1], p[2])

        best = None
        for yaw in yaws:
            r = minimize(neg, [s0, px0, py0], args=(yaw,), method="Nelder-Mead",
                         options={"xatol": 0.5, "fatol": 1e-4, "maxiter": 160,
                                  "initial_simplex": [[s0, px0, py0], [s0 * 1.25, px0, py0],
                                                      [s0, px0 + 25, py0], [s0, px0, py0 - 25]]})
            if best is None or r.fun < best[0]:
                best = (r.fun, yaw, r.x)
        yaw = best[1]
        p = best[2]
        for yaw_try in np.arange(yaw - 12, yaw + 12.1, 3):
            r = minimize(neg, p, args=(float(yaw_try),), method="Nelder-Mead",
                         options={"xatol": 0.25, "fatol": 1e-5, "maxiter": 200})
            if r.fun < best[0]:
                best = (r.fun, float(yaw_try), r.x)
        _, yaw, (scale, px, py) = best
        return self._result(yaw, scale, px, py, 1.0, -best[0])

    def refine_knee(self, base: dict, axis_frac: float = 0.1, lo: float = 0.3) -> dict:
        """Opt-in pass for a single over-tall spire (the castle minaret): keep the base fit and compress only
        the geometry above spire_knee() so the spire tip meets the sprite top. Everything below the knee (walls,
        side towers) is untouched, unlike a whole-body vertical squash."""
        from scipy.optimize import minimize_scalar

        ys = np.nonzero(self.target)[0]
        top_t = float(ys.min() * self.down)
        knee = spire_knee(self.v_raw, axis_frac)
        yaw, scale, (px, py) = base["yaw"], base["scale"], base["contactPx"]

        def top_for(c):
            self.v0 = knee_remap(self.v_raw, knee, c)
            return self.top_px(self.transform(yaw, scale, px, py)[1])

        r = minimize_scalar(lambda c: abs(top_for(c) - top_t), bounds=(lo, 1.0), method="bounded",
                            options={"xatol": 1e-3})
        c = float(r.x)
        off = top_for(c) - top_t
        out = self._result(yaw, scale, px, py, 1.0, self.score(yaw, scale, px, py))
        self.v0 = self.v_raw
        out.update({"kneeY": knee + self.model_lo_y, "kneeFrac": knee / self.model_h, "kneeScale": c,
                    "topOffsetPx": off, "baseFit": {a: base[a] for a in ("iou", "precision", "recall")}})
        return out

    def top_px(self, w: np.ndarray) -> float:
        return float(self.project(w)[0][:, 1].min())

    def refine_stretch(self, base: dict, lo: float = 0.75, hi: float = 1.45, top_weight: float = 1.0) -> dict:
        """Opt-in second pass for a mesh whose proportions differ from its sprite (the hall reads squat, the
        castle minaret overshoots): at the base yaw, search scale, contact pixel and a vertical stretch,
        maximising F-beta minus top_weight x |mesh top - sprite top| / sprite height. The top term exists
        because a thin spire or minaret is too few pixels for F-beta to see."""
        from scipy.optimize import minimize

        ys = np.nonzero(self.target)[0]
        top_t, h_t = float(ys.min() * self.down), float((ys.max() - ys.min() + 1) * self.down)
        yaw = base["yaw"]

        def obj(p):
            scale, px, py, k = p
            if not lo <= k <= hi:
                return 1.0
            _, w = self.transform(yaw, scale, px, py, k)
            return -(self.score(yaw, scale, px, py, stretch_y=k) - top_weight * abs(self.top_px(w) - top_t) / h_t)

        s0, (px0, py0) = base["scale"], base["contactPx"]
        best = None
        for k0 in sorted({min(hi, max(lo, v)) for v in (0.85, 1.0, 1.2)}):
            x0 = [s0, px0, py0, k0]
            dk = 0.1 if k0 + 0.1 <= hi else -0.1
            r = minimize(obj, x0, method="Nelder-Mead",
                         options={"xatol": 0.25, "fatol": 1e-5, "maxiter": 400,
                                  "initial_simplex": [x0, [s0 * 1.1, px0, py0, k0], [s0, px0 + 15, py0, k0],
                                                      [s0, px0, py0 - 15, k0], [s0, px0, py0, k0 + dk]]})
            if best is None or r.fun < best.fun:
                best = r
        scale, px, py, k = best.x
        out = self._result(yaw, scale, px, py, float(k), self.score(yaw, scale, px, py, stretch_y=k))
        _, w = self.transform(yaw, scale, px, py, k)
        out.update({"topOffsetPx": self.top_px(w) - top_t, "topWeight": top_weight,
                    "stretchBounds": [lo, hi], "baseFit": {a: base[a] for a in ("iou", "precision", "recall")}})
        return out

    def _result(self, yaw, scale, px, py, stretch_y, fbeta) -> dict:
        pos, w = self.transform(yaw, scale, px, py, stretch_y)
        full = self.silhouette(w, full=True)
        tgt = self.target
        inter = np.logical_and(full, tgt).sum()
        union = np.logical_or(full, tgt).sum()
        prec = inter / max(1, full.sum())
        rec = inter / max(1, tgt.sum())
        return {"yaw": float(yaw) % 360.0, "scale": float(scale), "position": [float(v) for v in pos],
                "contactPx": [float(px), float(py)], "fbeta": float(fbeta), "stretchY": float(stretch_y),
                "iou": float(inter / max(1, union)), "precision": float(prec), "recall": float(rec),
                "worldHeight": float(self.model_h * scale * stretch_y), "silhouette": full}
