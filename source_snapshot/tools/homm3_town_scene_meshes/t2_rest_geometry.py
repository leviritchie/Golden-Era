"""Faction-neutral fit pieces of the Meshy T2 building lane shared by castle_t2_buildings.py and tower_t2_stage.py
(docs/homm3_castle_t2_town_buildings.md, docs/homm3_tower_t2_town_buildings.md). Moved verbatim from
castle_t2_buildings.py (2026-09-29); the caller sets TOWN_FULL3D_FACTION before importing (stronghold_full3d_common
reads it at import).

RectFitter         fit_mesh_to_sprite.Fitter scored inside the painted rect only (frame-cut buildings may continue).
quadrant_fit       coarse yaw over the full circle, best fit per 90 deg quadrant (Meshy re-poses buildings).

The bake that was here (stage_painted_layer with subdivide_screen, clip_to_painting, rest_visible, two_sided,
vertex_normals) moved to town_full3d_t2_paint (rest_geometry_split), the one T2 bake, on 2026-09-30; restaging
tbcstvrn (Castle t2_v1) and tbtwtvrn (Tower tw_t2) gives byte-identical staged files (t2_bake_restage_check.py).

Proof tier: generated artifact.
"""
from __future__ import annotations

import numpy as np

import stronghold_full3d_common as SC
from fit_mesh_to_sprite import Fitter

W, H, TW, TH = SC.W, SC.H, SC.TW, SC.TH


class RectFitter(Fitter):
    """Fitter whose objective sees only the painted rect: px past the painting's right / bottom edge are neither
    precision nor recall (a frame-cut sprite has no px there)."""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        d = self.down
        valid = np.zeros(self.target.shape, bool)
        valid[:TH // d, :TW // d] = True
        self.valid_full = valid
        self.valid = valid[self.win[1]:self.win[3], self.win[0]:self.win[2]]

    def score(self, yaw, scale, px, py, beta=0.5, stretch_y=1.0) -> float:
        if scale <= 0:
            return 0.0
        _, w = self.transform(yaw, scale, px, py, stretch_y)
        s = self.silhouette(w) & self.valid
        tp = float(np.logical_and(s, self.tgt).sum())
        if tp == 0:
            return 0.0
        prec = tp / float(s.sum())
        rec = tp / float(self.tgt.sum())
        b2 = beta * beta
        return (1 + b2) * prec * rec / (b2 * prec + rec)

    def _result(self, yaw, scale, px, py, stretch_y, fbeta) -> dict:
        out = super()._result(yaw, scale, px, py, stretch_y, fbeta)
        full = out["silhouette"] & self.valid_full
        inter = np.logical_and(full, self.target).sum()
        out.update({"iou": float(inter / max(1, np.logical_or(full, self.target).sum())),
                    "precision": float(inter / max(1, full.sum())), "recall": float(inter / max(1, self.target.sum())),
                    "silhouetteOutsideRectPx": int((out["silhouette"] & ~self.valid_full).sum() * self.down ** 2)})
        return out



def quadrant_fit(fz, bbox, step: float = 15.0) -> dict:
    """Silhouette fit (fz.score, Nelder-Mead over scale and contact px, as Fitter.fit's coarse pass) at every yaw
    step over the full circle, no local refine; returns {quadrant centre (0/90/180/270): best coarse fit} with
    yaw, scale, contactPx and fbeta. Meshy T2 re-poses the building, so neither the camera ray nor a window about it
    settles the facing, and the silhouette is near-symmetric under 180 deg: the quadrant is chosen afterwards (by eye
    from a panel, or the best F0.5), then refined with Fitter.fit(yaws=[yaw])."""
    from scipy.optimize import minimize
    x0, y0, x1, y1 = bbox
    px0, py0 = (x0 + x1) / 2, y1 - 0.05 * (y1 - y0)
    zf = float(fz.z[int(np.clip(py0, 0, fz.H - 1)), int(np.clip(px0, 0, fz.W - 1))])
    s0 = ((y1 - y0) / fz.H * 2 * zf * fz.t) / max(1e-6, fz.model_h)
    out: dict = {}
    for yaw in np.arange(0.0, 360.0, step):
        r = minimize(lambda p: -fz.score(yaw, p[0], p[1], p[2]), [s0, px0, py0], method="Nelder-Mead",
                     options={"xatol": 0.5, "fatol": 1e-4, "maxiter": 160,
                              "initial_simplex": [[s0, px0, py0], [s0 * 1.25, px0, py0],
                                                  [s0, px0 + 25, py0], [s0, px0, py0 - 25]]})
        q = int(((yaw + 45) % 360) // 90) * 90
        if q not in out or -r.fun > out[q]["fbeta"]:
            out[q] = {"yaw": float(yaw), "scale": float(r.x[0]), "contactPx": [float(r.x[1]), float(r.x[2])],
                      "fbeta": float(-r.fun)}
    return out
