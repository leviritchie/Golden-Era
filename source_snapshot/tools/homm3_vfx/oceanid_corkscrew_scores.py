"""Oceanid corkscrew water: un-lit uvAtlas scores whose pattern turns with the column (unit-look source).

Pairs with the retarget hook `tools/homm3_def_retarget/ext/cove_corkscrew.py`, which gives the water column a
torsional wave and a counter-clockwise helical whirl (period 8 frames). The F2 flow atlas it replaces moved its
bands and speckle straight *down* the column at 2 DEF px/frame -- a flat scroll that reads thin on a twisting
column. Here every feature lives in the column's own helical frame and the whole pattern *rotates*
counter-clockwise (seen from above, Blender +Z) about the column axis, so the surface motion follows the twist:

  cylindrical coords about the column axis: alpha (CCW angle, Blender frame), h (height, glTF y)
  pattern F(alpha, h) is periodic in alpha with period 2 pi / REPEATS, so cell k = F(alpha - k * Omega, h) with
  Omega = 2 pi / (REPEATS * LOOP) closes exactly after LOOP = 8 cells (one retarget period).

Score terms (rank-mapped per region onto the DEF palette by the unit-look runner, so only the order matters):
  band    helical ridges, same handedness as the whirl (alpha rises with height), warped by periodic noise:
          rotating them CCW makes the crests travel down the column (the barber-pole corkscrew)
  sheet   broad, slow periodic noise in the helical frame: large coherent sheets of light/dark water (thickness)
  cavity  static mesh-curvature term: grooves of the sculpted column rank dark, crests light -- baked volume
          that rides with the geometry (it rotates with the twist because it is on the surface)
  speck   a small re-rolled share (the DEF's boil) + 1-px-ish highlights that travel with the pattern
Foam (the flare at the base): the same rotation (whirlpool) with a larger boil share.

Writes artifacts/homm3_vfx_experiments/oceanid/look/corkscrew_scores.npz (same keys/layout as flow2_scores.npz:
'scores' (cells, H, W) in [0, 1], top-down glTF UV, plus the region masks and palettes copied from flow2).
Proof tier: generated artifact.

    python tools/homm3_vfx/oceanid_corkscrew_scores.py [--repeats 3] [--preview]
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "tools/homm3_prebake"))
from glb_io import Glb  # noqa: E402
from oceanid_water_lab import DEF_PX_UNITS, SRC_GLB, load_mesh, rasterise  # noqa: E402

LOOK = ROOT / "artifacts/homm3_vfx_experiments/oceanid/look"
OUT = LOOK / "corkscrew_scores.npz"
BASE = LOOK / "flow2_scores.npz"   # region masks + DEF palettes (same mesh, same UV, same N)
LOOP = 8


def hash2(ix, iy, seed):
    v = (ix * 73856093) ^ (iy * 19349663) ^ (seed * 2654435761)
    v = (v ^ (v >> 13)) * 1274126177
    return ((v ^ (v >> 16)) & 0xFFFF) / 65535.0


def wrap_noise(a, b, na, cb, seed):
    """Value noise in [0,1] on (a, b): a in [0,1) wraps with `na` lattice cells, b lattice spacing `cb`."""
    qa, qb = a * na, b / cb
    ia, ib = np.floor(qa).astype(np.int64), np.floor(qb).astype(np.int64)
    fa, fb = qa - ia, qb - ib
    fa, fb = fa * fa * (3 - 2 * fa), fb * fb * (3 - 2 * fb)
    out = 0
    for da in (0, 1):
        for db in (0, 1):
            w = (fa if da else 1 - fa) * (fb if db else 1 - fb)
            out = out + w * hash2((ia + da) % na, ib + db, seed)
    return out


def curvature_tex(P, UV, I, N, tri_mask):
    """Signed mean-curvature proxy per texel: + on crests, - in grooves (welded uniform Laplacian, smoothed)."""
    key = np.round(P / 1e-5).astype(np.int64)
    _, weld, inv = np.unique(key, axis=0, return_index=True, return_inverse=True)
    inv = inv.reshape(-1)
    Pw = P[weld]
    F = inv[I]
    nv = len(Pw)
    fn = np.cross(Pw[F[:, 1]] - Pw[F[:, 0]], Pw[F[:, 2]] - Pw[F[:, 0]])
    vn = np.zeros_like(Pw)
    for c in range(3):
        np.add.at(vn, F[:, c], fn)
    vn /= np.linalg.norm(vn, axis=1, keepdims=True) + 1e-12
    E = np.concatenate([F[:, [0, 1]], F[:, [1, 2]], F[:, [2, 0]]])
    E = np.concatenate([E, E[:, ::-1]])
    deg = np.bincount(E[:, 0], minlength=nv).astype(np.float64)
    acc = np.zeros_like(Pw)
    np.add.at(acc, E[:, 0], Pw[E[:, 1]])
    lap = acc / np.maximum(deg, 1)[:, None] - Pw
    k = -(lap * vn).sum(1)             # > 0 convex (crest), < 0 concave (groove)
    for _ in range(4):                  # smooth to a few DEF px
        s = np.zeros(nv)
        np.add.at(s, E[:, 0], k[E[:, 1]])
        k = 0.5 * k + 0.5 * s / np.maximum(deg, 1)
    kv = k[inv]
    # rasterise the per-vertex value by abusing rasterise's position interpolation on a 3-vector
    Pk = np.stack([kv, kv, kv], 1)
    tex, cov = rasterise(Pk, UV, I, tri_mask, N)
    return tex[..., 0], cov


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repeats", type=int, default=3, help="pattern repeats around the column (rotation per loop = 360/repeats)")
    ap.add_argument("--pitch-defpx", type=float, default=22.0, help="helical band vertical period (DEF px)")
    ap.add_argument("--band-turns", type=int, default=1, help="band phase turns per angular repeat (helix steepness)")
    ap.add_argument("--flow-defpx", type=float, default=0.0, help="extra straight-down drift per frame (must tile: pitch*n/LOOP)")
    ap.add_argument("--w", default="0.42,0.22,0.24,0.12", help="weights band,sheet,cavity,speck")
    ap.add_argument("--seed", type=int, default=11)
    ap.add_argument("--preview", action="store_true", help="also write a grey preview strip of the cells")
    a = ap.parse_args()
    wb, wsh, wc, wsp = (float(x) for x in a.w.split(","))

    base = np.load(BASE)
    N = base["scores"].shape[1]
    cov_c, cov_f, pad = base["column"], base["foam"], base["pad"]
    cov = cov_c | cov_f

    glb = Glb(SRC_GLB)
    P, UV, I, water, foam = load_mesh(glb)
    tri_w = water[I].all(1)
    pos, pcov = rasterise(P, UV, I, tri_w, N)
    curv, ccov = curvature_tex(P, UV, I, N, tri_w)

    # column axis (glTF x, z) = median of the mid-column water vertices
    y = P[:, 1]
    mid = water & (y > 0.25) & (y < 0.7)
    cx, cz = float(np.median(P[mid, 0])), float(np.median(P[mid, 2]))
    gx, gy, gz = pos[..., 0], pos[..., 1], pos[..., 2]
    alpha = np.arctan2(-(gz - cz), gx - cx)          # Blender CCW angle (Blender y = -glTF z)
    a01 = (alpha / (2 * math.pi)) % 1.0               # [0,1) around the column
    h = gy
    pitch = a.pitch_defpx * DEF_PX_UNITS
    R = a.repeats

    # curvature rank in [0,1] over the water (only its order within the region matters)
    cr = np.zeros_like(curv)
    m = ccov & cov
    cr[m] = np.argsort(np.argsort(curv[m])) / max(1, m.sum() - 1)

    def cell(k):
        # rotate the pattern CCW by k * Omega: sample at alpha - k*Omega; Omega = (1/R)/LOOP of a turn
        ak = (a01 * R - k / LOOP) % 1.0                 # helical-frame angle, one unit = one angular repeat
        hk = h + k * a.flow_defpx * DEF_PX_UNITS        # optional straight-down drift
        warp = wrap_noise(ak, hk, 3, pitch * 1.2, a.seed + 5) - 0.5
        # same handedness as the whirl: constant phase along alpha rising with height
        band = 0.5 + 0.5 * np.sin(2 * math.pi * (a.band_turns * ak - hk / pitch + 0.55 * warp))
        sheet = 0.6 * wrap_noise(ak, hk, 2, pitch * 1.6, a.seed + 21) + 0.4 * wrap_noise(ak, hk, 4, pitch * 0.8, a.seed + 22)
        fine = wrap_noise(ak, hk, 12, pitch * 0.18, a.seed + 31)
        rng = np.random.default_rng(a.seed * 100 + k)
        boil = ndimage.gaussian_filter(rng.random(h.shape), 1.2)
        boil = (boil - boil.min()) / (np.ptp(boil) + 1e-9)
        sc = wb * band + wsh * sheet + wc * cr + wsp * (0.5 * fine + 0.5 * boil)
        # foam: same rotation, more boil
        sf = 0.35 * band + 0.15 * sheet + 0.15 * cr + 0.35 * boil
        s = np.where(cov_f, sf, sc)
        # travelling highlights (crest-locked): the top few % of fine x band on the crests
        hl_src = fine * band * (0.5 + cr)
        hl = np.zeros_like(cov)
        for reg, frac in ((cov_c, 0.045), (cov_f, 0.08)):
            if reg.any():
                hl |= reg & (hl_src > np.quantile(hl_src[reg], 1 - frac))
        return s + 10.0 * hl

    near = ndimage.distance_transform_edt(~cov, return_distances=False, return_indices=True)
    cells = [np.clip(cell(k) / 11.0, 0, 1)[near[0], near[1]] for k in range(LOOP)]
    sc = np.stack(cells).astype(np.float16)
    np.savez_compressed(OUT, scores=sc, column=cov_c, foam=cov_f, pad=pad,
                        paletteColumn=base["paletteColumn"], paletteFoam=base["paletteFoam"])
    meta = {"schema": "oceanid_corkscrew_scores.v1", "loop": LOOP, "repeats": R,
            "rotationDegPerFrame": 360.0 / R / LOOP, "pitchDefPx": a.pitch_defpx, "bandTurns": a.band_turns,
            "flowDefPxPerFrame": a.flow_defpx, "weights": {"band": wb, "sheet": wsh, "cavity": wc, "speck": wsp},
            "axisGltfXZ": [cx, cz], "seed": a.seed, "pairsWith": "tools/homm3_def_retarget/ext/cove_corkscrew.py"}
    (LOOK / "corkscrew_scores.json").write_text(json.dumps(meta, indent=1))
    print("wrote", OUT, json.dumps(meta))
    if a.preview:
        strip = np.concatenate([(c * 255).astype(np.uint8)[::2, ::2] for c in cells], 1)
        Image.fromarray(strip).save(LOOK / "corkscrew_scores_preview.png")


if __name__ == "__main__":
    main()
