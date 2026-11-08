#!/usr/bin/env python3
"""Apply a terrain-stage change to an already staged candidate as a delta, without restaging the rest of its terrain.

    TOWN_FULL3D_FACTION=castle TOWN_FULL3D_CANDIDATE=<target> python town_full3d_carve_delta.py apply \
        --before <cand> --after <cand> [--pieces Mesh_Terrain,Mesh_TerrainNear_0,Mesh_TerrainNear_1]

Why: the houses lane's silhouette carve left a pit under every modelled house (town_full3d_houses.py, CARVE pit cap,
2026-10-01). The fix is in the carve, so the terrain must be restaged. But a delivered lineage's terrain was staged by
older lane code. Restaging it today changes much more than the pit: Castle props_v1, restaged with the pit cap
disabled, moves 13958 TerrainNear_1 vertices by up to 0.9 m and changes 599k Mesh_Terrain texels, from unrelated
lane changes since. Everything anchored to that terrain (building contact depth, cloth, props, the mv3 fills) would
move with it.

The delta keeps the delivered terrain and carries only what the fix changes:
  * before / after are two scratch candidates whose terrain was staged with today's code from one seed, the fix
    off (before) and on (after). Their pieces must have the same topology and uv; this fails closed otherwise.
  * Each target vertex is matched to a before/after vertex by its uv (a uv shared by several before vertices, at the
    grid's seams, is never matched; a vertex the fix changes may not have one). A terrain piece's uv is an affine map of its
    rest px, so the match is exact float32 equality. The target vertex must also lie on the same rest ray (within
    RAY_TOL).
  * A vertex the fix moved is scaled about the camera by |after| / |before|. Its rest px is unchanged, so the rest
    frame does not move. It also takes the after normal.
  * A texel whose after albedo differs from the before albedo takes the after texel. The terrain albedo is the
    painting de-lit by the normals, so the texels under the moved geometry are re-lit by its new normals.
  * Every other vertex, normal and texel of the target stays bit-identical.
Target: an unlayered candidate. The LDI must run after the delta (recipe ldi.fromPreLdi false on a seed that went
through town_full3d_ldi.py unlayer), so it fails on a candidate that still carries an ldi section.

Device: CPU only. The work is a few vector ops over about 10^5 vertices and one texture compare per piece, all
dominated by file I/O (under 2 s per piece). There are no rasters, ray casts or per-texel filters to port.

Records stage_report.json "terrainDelta". Proof tier: generated artifact (offline).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import stronghold_full3d_common as SC  # noqa: E402
from town_full3d_ldi import read_bin, write_bin  # noqa: E402

RAY_TOL = 1e-4          # a matched target vertex lies on the before vertex's rest ray (1 - cos of the angle)
PIECES = ("Mesh_Terrain", "Mesh_TerrainNear_0", "Mesh_TerrainNear_1")


def fail(msg: str) -> None:
    raise SystemExit(f"carve delta: {msg}")


def env_dir(cand: str) -> Path:
    return (SC.DATA / "candidates" / cand / "unity_project" / "Assets" / "Homm3TownScene3d" / SC.FACTION
            / (SC.FP.PREFIX + "environment"))


def _uv_key(uv: np.ndarray) -> np.ndarray:
    u = np.ascontiguousarray(uv.astype(np.float32)).view(np.uint32).astype(np.uint64)
    return (u[:, 0] << np.uint64(32)) | u[:, 1]


def piece_delta(name: str, tdir: Path, bdir: Path, adir: Path) -> dict:
    vt, nt, ut, st = read_bin(tdir / f"{name}.bytes")
    vb, nb, ub, sb = read_bin(bdir / f"{name}.bytes")
    va, na, ua, sa = read_bin(adir / f"{name}.bytes")
    if len(vb) != len(va) or not np.array_equal(ub, ua) or not all(np.array_equal(x, y) for x, y in zip(sb, sa)):
        fail(f"{name}: before and after differ in topology or uv (the delta needs one grid)")
    vb64, va64 = vb.astype(np.float64), va.astype(np.float64)
    moved = (vb != va).any(1)
    nmoved = (nb != na).any(1)
    need = moved | nmoved
    kb = _uv_key(ub)
    _, inv, cnt = np.unique(kb, return_inverse=True, return_counts=True)
    dup = cnt[inv] > 1                     # uv shared by several vertices (the grid's seams): never matched
    if (dup & need).any():
        fail(f"{name}: {int((dup & need).sum())} vertices the fix changes share their uv with another vertex")
    uniq = np.flatnonzero(~dup)
    order = uniq[np.argsort(kb[uniq])]
    kt = _uv_key(ut)
    pos = np.clip(np.searchsorted(kb[order], kt), 0, len(order) - 1)
    hit = kb[order][pos] == kt
    j = order[pos]
    # every before vertex the fix touched must be in the target (an unmatched one is part of the fix not carried)
    tj = np.zeros(len(vb), bool)
    tj[j[hit]] = True
    lost = int((need & ~tj).sum())
    if lost:
        fail(f"{name}: {lost} vertices the fix changes have no target vertex with their uv")
    sel = hit & need[j]
    i, jj = np.flatnonzero(sel), j[sel]
    vt64 = vt.astype(np.float64)
    rt = np.linalg.norm(vt64[i], axis=1)
    rb = np.linalg.norm(vb64[jj], axis=1)
    ra = np.linalg.norm(va64[jj], axis=1)
    cos = (vt64[i] * vb64[jj]).sum(1) / np.maximum(rt * rb, 1e-12)
    off = 1 - cos
    if len(i) and off.max() > RAY_TOL:
        fail(f"{name}: a target vertex is off its before vertex's rest ray (1 - cos {off.max():.2e} > {RAY_TOL})")
    vnew = vt.copy()
    mv = moved[jj]
    vnew[i[mv]] = (vt64[i[mv]] * (ra[mv] / rb[mv])[:, None]).astype(np.float32)
    nnew = nt.copy()
    nn = nmoved[jj]
    nnew[i[nn]] = na[jj[nn]]
    # the albedo: the texels the fix changes
    tb = np.asarray(Image.open(bdir / f"{name}_albedo.png"))
    ta = np.asarray(Image.open(adir / f"{name}_albedo.png"))
    tt = np.asarray(Image.open(tdir / f"{name}_albedo.png"))
    if tb.shape != ta.shape or tt.shape != tb.shape:
        fail(f"{name}: albedo sizes differ ({tt.shape} target, {tb.shape} before, {ta.shape} after)")
    tm = (tb != ta).any(-1) if tb.ndim == 3 else tb != ta
    tex = tt.copy()
    tex[tm] = ta[tm]
    write_bin(tdir / f"{name}.bytes", vnew, nnew, ut, np.concatenate(st))
    if tm.any():
        Image.fromarray(tex).save(tdir / f"{name}_albedo.png")
    rel_seed = np.abs(rt[mv] / rb[mv] - 1) if mv.any() else np.zeros(0)
    return {"verts": int(len(vt)), "vertsMoved": int(mv.sum()), "normalsChanged": int(nn.sum()),
            "texelsChanged": int(tm.sum()), "maxRatio": round(float(np.max(ra[mv] / rb[mv])), 4) if mv.any() else 1.0,
            "minRatio": round(float(np.min(ra[mv] / rb[mv])), 4) if mv.any() else 1.0,
            # how far the target's own depth at the moved vertices is from today's before depth (the seed's terrain
            # is older lane code): the delta is a ratio, so this is the share it is applied off
            "targetVsBeforeDepthRelMax": round(float(rel_seed.max()), 4) if len(rel_seed) else 0.0,
            "targetVsBeforeDepthRelP95": round(float(np.quantile(rel_seed, 0.95)), 4) if len(rel_seed) else 0.0}


def apply(target: str, before: str, after: str, pieces) -> dict:
    tdir, bdir, adir = env_dir(target), env_dir(before), env_dir(after)
    rp = SC.DATA / "candidates" / target / "work" / "stage_report.json"
    sr = json.loads(rp.read_text(encoding="utf-8"))
    if sr.get("ldi"):
        fail(f"{target} still carries an ldi section: unlayer it first (town_full3d_ldi.py unlayer), the LDI runs "
             "after the delta")
    if "terrainDelta" in sr:
        fail(f"{target} already carries a terrainDelta (re-seed the candidate)")
    before_sha = {p: hashlib.sha256((tdir / f"{p}.bytes").read_bytes()).hexdigest() for p in pieces}
    out = {p: piece_delta(p, tdir, bdir, adir) for p in pieces}
    rep = {"schema": "town_full3d_terrain_delta.v1", "before": before, "after": after,
           "houses": os.environ.get("TOWN_FULL3D_HOUSES", ""), "targetSha256Before": before_sha,
           "targetSha256After": {p: hashlib.sha256((tdir / f"{p}.bytes").read_bytes()).hexdigest() for p in pieces},
           "pieces": out, "proofTier": "generated artifact (offline)"}
    sr["terrainDelta"] = rep
    rp.write_text(json.dumps(sr, indent=1), encoding="utf-8")
    return rep


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["apply"])
    ap.add_argument("--before", required=True)
    ap.add_argument("--after", required=True)
    ap.add_argument("--pieces", default=",".join(PIECES))
    a = ap.parse_args()
    target = os.environ.get("TOWN_FULL3D_CANDIDATE", "")
    if not target or target in (a.before, a.after):
        fail("set TOWN_FULL3D_CANDIDATE to the target (not the before / after candidate)")
    print(json.dumps(apply(target, a.before, a.after, [p for p in a.pieces.split(",") if p]), indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
