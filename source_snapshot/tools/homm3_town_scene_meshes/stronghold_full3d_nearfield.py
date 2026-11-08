"""Stronghold full-3D: near-field dressing of the frame extension (the default frame outside the HoMM3 rect).

The vanilla default frame is 1920x1080; the HoMM3 screen covers its top-left 1440x673 (x1.8). The rest -- a 407 px
band under the painting and a 480 px column right of it -- is synthesised ground (stronghold_full3d_ground). A bare
synthesis reads as smooth sand, where the painting's floor is dotted with dark scrub and stones. This module places
vanilla Olden Era meshes there at the painting's own measured dressing density:

  * density  olive scrub blobs counted in the painting's nearest floor rows (rect rows ROWS_MEASURE), divided by the
             world floor area those pixels cover (footprint of each pixel on the measured terrain): instances / m^2.
             Rocks and pebbles are hand-set multiples of it (ROCK_PER_SCRUB, PEBBLE_PER_SCRUB): the painting's stones
             are too small to count reliably at 800x374.
  * kinds    scrub: vanilla Dead_thorns_01 with its texture re-tinted to the painting's measured scrub ramp;
             rocks: vanilla Rock_desert_new_01..03 with their own textures toned to the painting's floor colour
             (per-channel median match); pebbles: vanilla Des_Rock_02, toned the same, 0.25-0.6 m.
  * where    floor pixels of the extension (height above the floor < REL_MAX m, slope < SLOPE_MAX), above the HUD
             (bottom HUD_PX rows); every instance's box must project wholly outside the HoMM3 rect, so the painting
             stays untouched.
Bins: Mesh_Near_scrub, Mesh_Near_rocks_<k>, Mesh_Near_pebbles (environment prefab).
Proof tier: generated artifact.
"""
from __future__ import annotations

import math

import cv2
import numpy as np

import stronghold_full3d_common as SC
import stronghold_full3d_terrain as T
import stronghold_full3d_ground as G
import stronghold_full3d_periphery as PP

W, H, TW, TH = SC.W, SC.H, SC.TW, SC.TH
SEED = 2207
HUD_PX = 64
ROWS_MEASURE = (560, 673)     # frame rows of the rect's nearest floor (HoMM3 y 311-374)
REL_MAX, SLOPE_MAX = 2.5, 22.0
ROCK_PER_SCRUB, PEBBLE_PER_SCRUB = 0.35, 1.5
SCRUB_M, ROCK_M, PEBBLE_M = (1.2, 2.8), (0.7, 2.4), (0.25, 0.6)
NEAR_ROCKS, PEBBLE = SC.FP.NEAR_ROCKS, SC.FP.PEBBLE


def pixel_area(P: np.ndarray) -> np.ndarray:
    dx = np.zeros_like(P)
    dy = np.zeros_like(P)
    dx[:, :-1] = P[:, 1:] - P[:, :-1]
    dy[:-1] = P[1:] - P[:-1]
    return np.linalg.norm(np.cross(dx, dy), axis=-1)


def measured_density(baker, floor) -> dict:
    p = cv2.resize(T.painting(), (TW, TH), interpolation=cv2.INTER_AREA).astype(np.int32) \
        if T.painting().shape[:2] != (TH, TW) else T.painting().astype(np.int32)
    r, g, b = p[..., 0], p[..., 1], p[..., 2]
    olive = ((g > r + 2) & (g > b + 12)).astype(np.uint8)
    y0, y1 = ROWS_MEASURE
    band = np.zeros_like(olive)
    band[y0:y1] = 1
    rel = floor.rel(baker.P[:TH, :TW].astype(np.float64))
    fl = (rel < REL_MAX) & ~baker.fd["sky"][:TH, :TW] & band.astype(bool)
    n, lab, stats, _ = cv2.connectedComponentsWithStats(olive * fl.astype(np.uint8), 8)
    blobs = int(((stats[1:, cv2.CC_STAT_AREA] >= 3)).sum())
    area = float(pixel_area(baker.P[:TH, :TW].astype(np.float64))[fl].sum())
    if blobs < 5 or area <= 0:
        raise SystemExit(f"nearfield: density measurement failed (blobs={blobs}, area={area:.0f} m2)")
    return {"scrubBlobs": blobs, "floorAreaM2": round(area, 1), "scrubPerM2": blobs / area,
            "rows": list(ROWS_MEASURE)}


def candidates(baker, field, floor, rng, per_m2: float):
    """Poisson draws over the extension's floor pixels, weighted by each pixel's world footprint."""
    P = baker.P.astype(np.float64)
    area = pixel_area(P)
    ys, xs = np.mgrid[0:H, 0:W]
    ext = ((xs >= TW) | (ys >= TH)) & (ys < H - HUD_PX) & ~baker.fd["sky"]
    rel = floor.rel(P.reshape(-1, 3)).reshape(H, W)
    nrm = field.normal(P[..., 0], P[..., 2], eps=1.0)
    slope = np.degrees(np.arccos(np.clip(nrm[..., 1], -1, 1)))
    ok = ext & (rel < REL_MAX) & (slope < SLOPE_MAX) & np.isfinite(area)
    lam = np.where(ok, area * per_m2, 0.0)
    k = rng.poisson(lam)
    iy, ix = np.nonzero(k)
    reps = k[iy, ix]
    iy, ix = np.repeat(iy, reps), np.repeat(ix, reps)
    fx, fy = ix + rng.uniform(0, 1, len(ix)), iy + rng.uniform(0, 1, len(iy))
    zf = baker.zf[iy, ix]
    B = baker.ctx.cpos + T.rays(baker.ctx.cam, fx, fy) * zf[:, None]
    B[:, 1] = field.height(B[:, 0], B[:, 2])
    return B, fy


def outside_rect(cam, base, hgt, rad) -> np.ndarray:
    ok = np.ones(len(base), bool)
    for dx in (-1, 1):
        for dz in (-1, 1):
            for dy in (0, 1):
                c = base + np.stack([dx * rad, dy * hgt, dz * rad], 1)
                px, py, zc = T.project(cam, c)
                ok &= (zc > 0.5) & ((px > TW + 1) | (py > TH + 1))
    return ok


def build(sc, prefix_env: str, state: dict) -> dict:
    import stronghold_full3d_vanilla as V
    cam, field, floor, baker = (state[k] for k in ("cam", "field", "floor", "baker"))
    rng = np.random.default_rng(SEED)
    nd = SC.FP.PERIPHERY_SCATTER["nearDensity"]
    if nd["source"] == "measured":
        dens = measured_density(baker, floor)
    elif nd["source"] == "profile":
        # the olive-blob rule counts every grass pixel on a meadow: the profile names the density instead
        dens = {"scrubBlobs": None, "floorAreaM2": None, "scrubPerM2": float(nd["perM2"]), "rows": list(ROWS_MEASURE),
                "source": f"profile PERIPHERY_SCATTER.nearDensity: {nd['reason']}"}
    else:
        raise SystemExit(f"nearfield: PERIPHERY_SCATTER.nearDensity.source {nd['source']!r} is not measured / profile")
    target = PP.floor_target(baker, floor)     # the painting's de-lit floor colour: the rocks' tone target
    rows = {}

    def place(name, meshes, texs, per_m2, size_rng, hfrac, max_size):
        B, fy = candidates(baker, field, floor, rng, per_m2)
        s = rng.uniform(*size_rng, len(B))
        ok = outside_rect(cam, B, hfrac * s, 0.55 * s)
        which = rng.integers(0, len(meshes), len(B))
        yaw = rng.uniform(0, 360, len(B))
        for k, (mname, img) in enumerate(zip(meshes, texs)):
            sel = ok & (which == k)
            if not sel.any():
                continue
            v, n, uv, f = PP.load_vanilla(mname)
            diam = float(max(np.ptp(v[:, 0]), np.ptp(v[:, 2])))
            Vv, Nn, UV, Fc = PP.merge((v, n, uv, f), B[sel], yaw[sel], s[sel] / diam, field)
            nm = name if len(meshes) == 1 else f"{name}_{k}"
            sc.add_bin(prefix_env, nm, Vv, Nn, UV, Fc, img, srgb=True, max_size=max_size)
            rows[nm] = {"instances": int(sel.sum()), "tris": int(len(Fc)), "mesh": mname,
                        "sizeM": list(size_rng), "perM2": round(per_m2, 5), "candidates": int(len(B)),
                        "outsideRect": int(ok.sum())}

    if PP.SCATTER_POLICY["scrub"]["required"]:
        scrub_tex = PP.retint(V.tex(PP.SCRUB_TEX), PP.scrub_palette(baker, cam))
        place("Mesh_Near_scrub", [PP.SCRUB_MESH], [scrub_tex], dens["scrubPerM2"], SCRUB_M, 0.55, 512)
    rock_tex = [PP.tone_to(V.tex(PP.ROCK_MESHES[m]), target) for m in NEAR_ROCKS]
    place("Mesh_Near_rocks", list(NEAR_ROCKS), rock_tex, dens["scrubPerM2"] * ROCK_PER_SCRUB, ROCK_M, 0.7, 1024)
    place("Mesh_Near_pebbles", [PEBBLE], [PP.tone_to(V.tex(PP.ROCK_MESHES[PEBBLE]), target)],
          dens["scrubPerM2"] * PEBBLE_PER_SCRUB, PEBBLE_M, 0.7, 512)
    if not rows:
        raise SystemExit("nearfield: no dressing placed")
    return {"dressing": rows, "density": dens, "rockToneTargetLinear": np.round(target, 4).tolist(),
            "hudBottomPx": HUD_PX}
