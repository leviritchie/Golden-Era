#!/usr/bin/env python3
"""buildingDepth catalog block + building depth audit (docs/homm3_town_building_contact_depth.md).

A staged building bin whose part above the floor reaches far deeper than it is wide is a depth streak: the legacy
per-column foot put the Cove waterfall's reflection at its foot and smeared the fall 70-155 m deep, and the stilt
houses / BodyRest residuals the same way. This module measures every building bin the way
tools/validate_town_scene3d_contract.py re-measures it:

    upright vertices  = camera-local vertices more than UPRIGHT_H_M above the painted floor plane (vertices lying on
                        the floor - reflections, decals, reeds - are ground, not depth) and not within UPRIGHT_H_M of
                        the staged terrain sampled under them (terrain_sample: ground on a hill above the plane is
                        ground too; walls buried in a terrain bump are not); the sample is sha-pinned to the stage
    uprightSpanM      = p98 - p2 of their forward depth (painting m)
    widthM            = (p98 - p2 of their azimuth) * their median forward depth
    spanOverWidth     = uprightSpanM / max(widthM, 0.5)
    a ray / solid bin fails when spanOverWidth > SPAN_OVER_WIDTH_MAX and uprightSpanM > SPAN_MIN_M; a layer that ships
    a ray / solid bin fails when its layer_depth reliefWindowShare > WINDOW_SHARE_MAX (the legacy relief window
    clipped most of the sprite, so the sprite's depth is the clamp, not the painting)
    Meshy-role bins (whole Meshy T2 models placed at their contact) are measured and recorded but exempt: their depth
    is the model's own geometry, not a per-pixel depth read.

Thresholds come from the 2026-10-01 survey (cove pb_v1 / bgd_v1 vs pb_dfix): every streak bin (tbcvnmp1/2, say1/2,
the *_rest residuals) is spanOverWidth 3.78-16 at 47-289 m span; every Meshy body and every contact_v1 bin is
<= 3.18, and the two above 3 span 15.5 m (tbcvhall_rest) - small residuals, not streaks.

write_catalog emits the block (and OUT/building_depth.npz with its sha256) only when the candidate pins
work/building_depth.json (opt-in per candidate); `audit` builds the same npz for any staged candidate into a scratch
folder and runs the validator's own check on it (how the pre-contract candidates are shown to fail).

    python town_full3d_building_depth.py audit --out V:/olden_port_work/depth_fix/audit_<town>_<cand>
Proof tier: generated artifact (offline mesh measurement). Not runtime proof.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import stronghold_full3d_common as SC  # noqa: E402
import stronghold_full3d_terrain as T  # noqa: E402

SCHEMA = "town_building_depth.v1"
NPZ = "building_depth.npz"
UPRIGHT_H_M = 2.0          # ground lying on terrain up to 2 m above the fitted floor plane is not upright (Cove tbcvhal3_rest at 1.0-1.3 m)
SPAN_OVER_WIDTH_MAX = 3.0
SPAN_MIN_M = 20.0
WINDOW_SHARE_MAX = 0.8
MAX_VERTS_PER_BIN = 20000
TERRAIN_CELL_M = 0.5       # terrain sample grid (painting m, in the floor plane)
TERRAIN_WALK_COS = 0.5     # terrain triangles steeper than 60 deg (depth-step walls) are not ground under a vertex
TERRAIN_MARGIN_M = 2.0


def piece_role(lid: str, name: str, meshy: bool) -> str:
    """fx | cloth | decal | solid | meshy | ray; anything else in a building prefab is refused (fail closed)."""
    if name.startswith("Fx_"):
        return "fx"
    if name == f"Mesh_Decal_{lid}":
        # town_full3d_sprite_decal.py: the sprite's paint on the environment's rest surface. Measured like a ray bin
        # (span / window), but it lies on the ground, not on the body: no building seam, no flap
        return "decal"
    if name.startswith(f"Mesh_Cloth_{lid}_b"):
        return "cloth"   # town_full3d_cloth.py: a copy of the layer's own rest-front faces, moved along their rays
    if not meshy:
        if name == f"Mesh_Body_{lid}" or name.startswith(f"Mesh_Body_{lid}_"):
            return "solid"
    else:
        # town_full3d_t2_meshy "painted front" lane (Necropolis): Mesh_Body_<l>_cloud is the installed relief's
        # triangles inside the layer's flat region on their rest rays (a residual), Mesh_Body_<l>_meshy the rest of
        # the Meshy body (its own atlas)
        if name in (f"Mesh_BodyRest_{lid}", f"Mesh_Body_{lid}_rest", f"Mesh_Body_resid_{lid}", f"Mesh_Body_{lid}_cloud"):
            return "ray"
        if name in (f"Mesh_Body_{lid}", f"Mesh_BodyM_{lid}", f"Mesh_Body_{lid}_hull", f"Mesh_Body_{lid}_meshy"):
            return "meshy"
        # Inferno T2 (inferno_t2_integrate): the seed's depth-solid triangles kept frontmost where the Meshy body
        # leaves the layer's painted mask uncovered at rest (ground paint: lava stream, pit rims), as in the
        # non-Meshy branch
        if name == f"Mesh_Body_{lid}_skirt":
            return "solid"
    raise SystemExit(f"buildingDepth: {lid}: piece {name} has no contact_v1 role (meshy={meshy})")


def is_meshy(rep_row: dict) -> bool:
    return str(rep_row.get("method", "")).startswith("meshy") or str(rep_row.get("kind", "")).startswith("meshy")


def read_vertices(path: Path) -> np.ndarray:
    b = path.read_bytes()
    nv, _ = struct.unpack_from("<ii", b, 0)
    return np.frombuffer(b, np.float32, nv * 3, 8).reshape(-1, 3).astype(np.float64)


def floor_local() -> tuple[np.ndarray, float]:
    """The painted floor plane in the prefab frame: n . (v / depthScale) = d, positive above."""
    cam = T.camera()
    fl = T.Floor(cam)
    C = np.stack([cam["right"], cam["up"], cam["fwd"]], 1)
    return np.asarray(fl.n @ C, np.float64), float(fl.d)


def upright_stats(v_local: np.ndarray, scale: float, n: np.ndarray, d: float, terrain: dict | None = None) -> dict:
    """The validator's measure (validate_town_scene3d_contract.building_upright_stats, called, not copied)."""
    return _V().building_upright_stats(v_local, scale, n, d, UPRIGHT_H_M, terrain)


def _V():
    if str(HERE.parent) not in sys.path:
        sys.path.insert(0, str(HERE.parent))
    import validate_town_scene3d_contract as V
    return V


def _bin_tris(path: Path) -> tuple[np.ndarray, np.ndarray]:
    b = path.read_bytes()
    nv, ns = struct.unpack_from("<ii", b, 0)
    v = np.frombuffer(b, np.float32, nv * 3, 8).reshape(-1, 3).astype(np.float64)
    o = 8 + nv * 32
    tris = []
    for _ in range(ns):
        (c,) = struct.unpack_from("<i", b, o)
        o += 4
        tris.append(np.frombuffer(b, np.int32, c, o).reshape(-1, 3))
        o += c * 4
    return v, (np.concatenate(tris) if tris else np.zeros((0, 3), np.int32))


def terrain_sample(env_dir: Path, pts_m: np.ndarray, n: np.ndarray, d: float, scale: float) -> tuple[dict, dict]:
    """The staged terrain pieces' walkable height above the floor plane, max per TERRAIN_CELL_M cell of the floor
    plane, over the building vertices' footprint (+ TERRAIN_MARGIN_M): the npz terrain_* arrays and the block's
    terrainSample (pieces + sha256 the validator re-checks against the stage). Triangles steeper than
    TERRAIN_WALK_COS (depth-step walls, cliff faces) are not ground under anything. Triangles are rasterised by
    barycentric samples at half a cell, so a far, stretched depth-mesh triangle still covers every cell it spans."""
    V = _V()
    pieces, sha = V.building_terrain_pieces_sha(env_dir)
    if not pieces:
        raise SystemExit(f"buildingDepth: {env_dir} stages no terrain piece (Mesh_Terrain* / Mesh_Back_Terrain*)")
    n = np.asarray(n, np.float64)
    e1 = np.array([1.0, 0.0, 0.0]) - n[0] * n
    e1 /= np.linalg.norm(e1)
    e2 = np.cross(n, e1)
    a, b = pts_m @ e1, pts_m @ e2
    o = np.array([a.min() - TERRAIN_MARGIN_M, b.min() - TERRAIN_MARGIN_M])
    W = int(np.ceil((a.max() + TERRAIN_MARGIN_M - o[0]) / TERRAIN_CELL_M))
    H = int(np.ceil((b.max() + TERRAIN_MARGIN_M - o[1]) / TERRAIN_CELL_M))
    grid = np.full(H * W, -np.inf)
    for nm in pieces:
        v, t = _bin_tris(env_dir / f"{nm}.bytes")
        P = (v / scale)[t]                                         # (T, 3, 3)
        nn = np.cross(P[:, 1] - P[:, 0], P[:, 2] - P[:, 0])
        ln = np.linalg.norm(nn, axis=1)
        walk = np.abs(nn @ n) >= TERRAIN_WALK_COS * np.maximum(ln, 1e-12)
        pa, pb = P @ e1, P @ e2
        inside = (pa.max(1) >= o[0]) & (pa.min(1) <= o[0] + W * TERRAIN_CELL_M) & \
                 (pb.max(1) >= o[1]) & (pb.min(1) <= o[1] + H * TERRAIN_CELL_M)
        P = P[walk & inside & (ln > 0)]
        if not len(P):
            continue
        ea, eb = P @ e1, P @ e2
        edge = np.max(np.hypot(ea - np.roll(ea, 1, 1), eb - np.roll(eb, 1, 1)), 1)
        m = np.clip(np.ceil(edge / (TERRAIN_CELL_M * 0.5)), 1, 512).astype(np.int64)
        for mm in np.unique(m):
            Q = P[m == mm]
            ii, jj = np.mgrid[0:mm + 1, 0:mm + 1]
            keep = ii + jj <= mm
            w1, w2 = ii[keep] / mm, jj[keep] / mm
            w0 = 1 - w1 - w2
            step = max(1, 2_000_000 // len(w0))
            for k in range(0, len(Q), step):
                q = Q[k:k + step]
                S = (w0[None, :, None] * q[:, None, 0] + w1[None, :, None] * q[:, None, 1]
                     + w2[None, :, None] * q[:, None, 2]).reshape(-1, 3)
                ci = np.floor((S @ e1 - o[0]) / TERRAIN_CELL_M).astype(np.int64)
                cj = np.floor((S @ e2 - o[1]) / TERRAIN_CELL_M).astype(np.int64)
                ok = (ci >= 0) & (cj >= 0) & (ci < W) & (cj < H)
                np.maximum.at(grid, cj[ok] * W + ci[ok], (S @ n - d)[ok])
    grid = np.where(np.isfinite(grid), grid, np.nan).reshape(H, W).astype(np.float32)
    arrays = {"terrain_grid": grid, "terrain_origin": o, "terrain_cell": np.float64(TERRAIN_CELL_M),
              "terrain_e1": e1, "terrain_e2": e2, "terrain_sha": np.array(sha)}
    try:
        rel = Path(env_dir).resolve().relative_to(HERE.parents[1].resolve()).as_posix()
    except ValueError:
        raise SystemExit(f"buildingDepth: terrain stage {env_dir} is outside the repo (the validator resolves it there)")
    block = {"pieces": pieces, "sha256": sha, "stageDir": rel, "cellM": TERRAIN_CELL_M, "walkCos": TERRAIN_WALK_COS,
             "rule": "upright = more than uprightHeightM above the floor plane and not within uprightHeightM of the highest "
                     "walkable terrain in its cell",
             "coveredCells": int(np.isfinite(grid).sum()), "cells": int(grid.size)}
    return arrays, block


def build(stage: Path, rows: dict, rep: dict, prefix: str, out_dir: Path, mode: str) -> dict:
    """Write out_dir/building_depth.npz and return the catalog block (measured, not yet judged)."""
    n, d = floor_local()
    scale = float(T.DEPTH_SCALE)
    names, roles, lids, pts, idx = [], [], [], [], []
    bins, layers = [], {}
    for key, r in rows.items():
        if not key.startswith(prefix) or key == prefix + "environment":
            continue
        lid = key[len(prefix):]
        brow = (rep.get("buildings") or {}).get(lid)
        if brow is None:
            raise SystemExit(f"buildingDepth: prefab {key} has no stage_report.buildings row")
        meshy = is_meshy(brow)
        aud = brow.get("depthAudit") or {}
        shipped = []
        for b in r["bins"]:
            role = piece_role(lid, b["name"], meshy)
            if role == "fx":
                continue
            v = read_vertices(stage / key / f"{b['name']}.bytes")
            step = max(1, int(np.ceil(len(v) / MAX_VERTS_PER_BIN)))
            vs = v[::step]
            names.append(b["name"]); roles.append(role); lids.append(lid)
            pts.append(vs.astype(np.float32)); idx.append(np.full(len(vs), len(names) - 1, np.int32))
            bins.append({"name": b["name"], "layerId": lid, "role": role})
            shipped.append(role)
        if "reliefWindowShare" not in aud and "windowShare" not in aud:
            raise SystemExit(f"buildingDepth: {lid}: stage report row lacks depthAudit (restage the layer)")
        layers[lid] = {"mode": aud.get("mode", "?"), "reliefWindowShare": float(aud.get("reliefWindowShare", 0.0)),
                       "spanOverWidthLayer": aud.get("spanOverWidth"), "zContactM": aud.get("zContactM"),
                       "roles": sorted(set(shipped))}
    P = np.concatenate(pts) if pts else np.zeros((0, 3), np.float32)
    I = np.concatenate(idx) if idx else np.zeros(0, np.int32)
    # the ground under the buildings: the same staged terrain pieces the candidate bundles
    tarr, tblock = terrain_sample(stage / (prefix + "environment"), P.astype(np.float64) / scale, n, d, scale) \
        if len(P) else ({}, None)
    terrain = tarr or None
    for i, bb in enumerate(bins):
        # the declared stats are measured on the stored (subsampled) vertices: the validator recomputes them
        bb.update(upright_stats(P[I == i], scale, n, d, terrain))
    # building seams (town_full3d_building_seams): one building's pieces must not come apart at the proof poses
    import town_full3d_building_seams as SEAMS
    sarr, sblock = SEAMS.seams_for_build(rows, rep, sorted(set(lids)))
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / NPZ
    # written whole then renamed, so a reader never sees (or hashes) a half-written npz
    tmp = out_dir / (NPZ + ".tmp.npz")
    np.savez_compressed(tmp, P=P, bin=I, names=np.array(names), roles=np.array(roles), layers=np.array(lids),
                        floor_n=n, floor_d=np.float64(d), depth_scale=np.float64(scale), **tarr, **sarr)
    import os
    os.replace(tmp, path)
    return {"schema": SCHEMA, "mode": mode, "file": NPZ, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "uprightHeightM": UPRIGHT_H_M, "spanOverWidthMax": SPAN_OVER_WIDTH_MAX, "spanMinM": SPAN_MIN_M,
            "windowShareMax": WINDOW_SHARE_MAX, "exemptRoles": {"meshy": "whole Meshy model at its contact"},
            "bins": bins, "layers": layers, **({"terrainSample": tblock} if tblock else {}), "seams": sblock,
            "method": "contact_v1 (docs/homm3_town_building_contact_depth.md)" if mode == "contact_v1" else mode,
            "proofTier": "generated artifact (offline mesh measurement); not runtime proof"}


def catalog_block(stage: Path, rows: dict, rep: dict, prefix: str, out_dir: Path) -> dict | None:
    """write_catalog's hook: the block only for a candidate that pins contact_v1 (opt-in)."""
    import stronghold_full3d_buildings as BL
    pin = BL.building_depth_pin()
    if pin is None:
        return None
    bd = rep.get("buildingDepth") or {}
    if bd.get("mode") != "contact_v1":
        raise SystemExit("buildingDepth: the candidate pins contact_v1 but its stage report was not re-depthed "
                         "(run town_full3d_building_redepth.py apply)")
    return build(stage, rows, rep, prefix, out_dir, "contact_v1")


def audit(out_dir: Path) -> int:
    """Any staged candidate (pinned or not): the npz + block in out_dir, judged by the validator's own check."""
    import stronghold_full3d_scene as S
    rows = json.loads(S.ROWS.read_text(encoding="utf-8"))
    rep = json.loads((S.WORK / "stage_report.json").read_text(encoding="utf-8"))
    for lid, b in (rep.get("buildings") or {}).items():
        if "depthAudit" not in b:      # a pre-contract stage report: re-measure the layer's depth read
            import stronghold_full3d_buildings as BL
            Ls = SC.layers()
            if lid in Ls:
                b["depthAudit"] = BL.depth_audit(BL.layer_depth(lid, Ls[lid], T.rect_depth(T.camera())))
    mode = (rep.get("buildingDepth") or {}).get("mode", "legacy")
    block = build(S.STAGE, rows, rep, S.PREFIX, out_dir, mode)
    (out_dir / "building_depth_block.json").write_text(json.dumps(block, indent=1, default=float), encoding="utf-8")
    sys.path.insert(0, str(HERE.parent))
    import validate_town_scene3d_contract as V
    fails = V.building_depth_failures(block, out_dir)
    for f in fails:
        print("FAIL", f)
    print(json.dumps({"bins": len(block["bins"]), "failures": len(fails)}))
    return 1 if fails else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["audit"])
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    return audit(Path(a.out))


if __name__ == "__main__":
    raise SystemExit(main())
