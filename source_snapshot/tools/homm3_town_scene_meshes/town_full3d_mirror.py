#!/usr/bin/env python3
"""Town full-3D: mirrored-back closure of terrain masses (experiment; companion of town_full3d_ldi).

The depth-mapped terrain is one sheet: a ridge's crest is joined to the far ground behind it by a curtain that runs
along the rest camera's rays. The layered-depth pass (town_full3d_ldi) cuts that curtain and continues the far ground
under the ridge. This pass adds what a solid ridge would have between the two: its hidden back half, assumed to be the
mirror image of its visible front half.

Mirror plane: per rest ray, the crest's own forward depth zc (the near end of the nearest cut). A front vertex at depth
z gets a copy at 2*zc - z on the same rest ray, so the copy keeps the vertex's screen position and uv and the back
face shows the ridge's own texels mirrored about the crest, with no texture synthesis. The copy never goes past the
continued far ground (the LDI's zb raster, less CLEAR); a triangle whose three copies all hit that limit is dropped, as
it would lie on the far ground. The crest depth is smoothed in inverse depth so neighbouring crests do not tear the
sheet. The winding is reversed so the closed ridge faces outward. The mirror keeps the front's own normal: the texels
already carry the painting's shading, and relighting them with the reflected normal (--normals reflect) darkened the
back twice and drew a dark saw-tooth rim along every crest at the sweeps (fa_v8_mirror v1 review).

Every mirror triangle's front copy stays in the main surface and is nearer on the same rays, so the rest frame is
unchanged by construction; the pass checks that with an id render. Triangles over the validator's depth-ratio cap are
dropped and counted.

    TOWN_FULL3D_CANDIDATE=<ldi candidate> python town_full3d_mirror.py --faction factory apply --orig fa_v4

--orig names the candidate that holds the original terrain bins (the LDI candidate's main bins have the cuts removed).
Writes Mesh_Back_<piece>_Mirror bins (texture: a verbatim copy of the piece's own albedo) and a "mirror" section in the stage
report. Proof tier: generated artifact / offline render.
"""
from __future__ import annotations

import argparse
import shutil
import json
import sys
from pathlib import Path

import numpy as np
from scipy.ndimage import distance_transform_edt

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import town_full3d_ldi as L  # noqa: E402

CLEAR = 1.004        # a mirror copy stays this factor in front of the continued far ground
SMOOTH_PX = 24.0     # crest depth smoothing (inverse depth, px)
REACH_GAIN = 1.0     # the mirror band reaches this many times the LDI band under the near side of a cut
NORMALS = "front"   # "front" (the front vertex's own normal) or "reflect" (reflected across the rest ray's normal plane)
FRONT_TOL = 1.02     # a front vertex is at most this factor behind its crest (the ridge's own face)


def mirror_piece(v, n, uv, tris, fov, poses) -> dict | None:
    v = np.asarray(v, np.float64)
    n = np.asarray(n, np.float64)
    tris = np.asarray(tris, np.int64)
    out = L.layer_piece(v, n, uv, tris, fov, poses)
    if out is None:
        return None
    fx, fy, z = L.project(v, fov)
    xi, yi = L._pix(fx, fy)
    ct = out["cut"]
    zmax = z[ct].max(1, keepdims=True)
    zmin = z[ct].min(1, keepdims=True)
    near_v = z[ct] < np.sqrt(zmax * zmin)
    crest = np.zeros(len(v), bool)
    crest[ct[near_v]] = True
    far_side = out["vertex"]["B"]
    crest &= ~far_side
    # crest raster: the nearest crest's depth per pixel, smoothed in inverse depth
    Cimg = np.zeros((L.H, L.W), bool)
    Cimg[yi[crest], xi[crest]] = True
    Cz = np.full((L.H, L.W), np.inf)
    np.minimum.at(Cz, (yi[crest], xi[crest]), z[crest])
    dist, (bi, bj) = distance_transform_edt(~Cimg, return_indices=True)
    zc_img = Cz[bi, bj]
    s_inv = L._blur(1.0 / zc_img, SMOOTH_PX)
    zc_s = 1.0 / np.maximum(s_inv, 1e-9)
    zc = np.minimum(zc_s[yi, xi], zc_img[yi, xi] * FRONT_TOL)
    dc = dist[yi, xi]
    reach = REACH_GAIN * out["report"]["extPx"]
    zb = out["rasters"]["zb"][yi, xi]
    front = (dc <= reach) & ~far_side & (z <= zc * FRONT_TOL)
    zm = 2.0 * zc - z
    lim = zb / CLEAR
    zm = np.maximum(zm, z * L.BEHIND)
    clamped = zm >= lim
    zm = np.where(clamped, np.maximum(lim, z * L.BEHIND), zm)
    N = np.int64(len(v))

    def key(t):
        return (t[:, 0] * N + t[:, 1]) * N + t[:, 2]
    cut_mask = np.isin(key(tris), key(ct))
    cand = front[tris].all(1) & ~cut_mask & ~clamped[tris].all(1)
    mt = tris[cand]
    r = L.depth_ratio(zm, mt)
    over = r > L.RATIO_CAP + 1e-6
    mt = mt[~over]
    used = np.unique(mt)
    remap = np.full(len(v), -1, np.int64)
    remap[used] = np.arange(len(used))
    vm = v[used] * (zm[used] / z[used])[:, None]
    d = v[used] / np.linalg.norm(v[used], axis=1, keepdims=True)
    nu = n[used]
    nm = nu - 2.0 * (nu * d).sum(1, keepdims=True) * d if NORMALS == "reflect" else nu
    tm = remap[mt][:, [0, 2, 1]]
    depth_gain = (zm[used] - z[used]) / z[used]
    rep = {"cutTris": int(len(ct)), "crestVerts": int(crest.sum()), "frontVerts": int(front.sum()),
           "mirrorTris": int(len(tm)), "mirrorVerts": int(len(used)), "droppedOverCap": int(over.sum()),
           "clampedVerts": int(clamped[used].sum()), "reachPx": round(float(reach), 1),
           "backDepthGainP50": round(float(np.median(depth_gain)), 4) if len(used) else 0.0,
           "backDepthGainP95": round(float(np.percentile(depth_gain, 95)), 4) if len(used) else 0.0,
           "maxRatio": round(float(L.depth_ratio(vm[:, 2], tm).max()), 4) if len(tm) else 0.0}
    return {"mirror": (vm, nm, np.asarray(uv, np.float64)[used], tm), "report": rep}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["apply"])
    ap.add_argument("--faction", required=True)
    ap.add_argument("--orig", required=True, help="candidate holding the original (uncut) terrain bins")
    ap.add_argument("--pieces", default="Mesh_Terrain,Mesh_TerrainNear_0,Mesh_TerrainNear_1")
    ap.add_argument("--normals", choices=["front", "reflect"], default="front")
    a = ap.parse_args()
    globals()["NORMALS"] = a.normals
    import stronghold_full3d_common as SC
    import stronghold_full3d_scene as S
    if not S.CANDIDATE:
        raise SystemExit("mirror apply: set TOWN_FULL3D_CANDIDATE (the shipped outputs are never rewritten)")
    sc = S.Scene()
    fov = float(sc.cam["fov"])
    poses = L.local_poses(sc, S)
    pdir = S.STAGE / S.ENV_KEY
    if list(pdir.glob("Mesh_Back_*_Mirror.bytes")):
        raise SystemExit(f"mirror: {pdir} already carries mirror bins (re-seed the candidate)")
    odir = SC.DATA / "candidates" / a.orig / "unity_project" / S.ASSET_ROOT / S.ENV_KEY
    rows = json.loads(S.ROWS.read_text(encoding="utf-8"))
    env_rows = {b["name"]: b for b in rows[S.ENV_KEY]["bins"]}
    rep = {"schema": "town_full3d_mirror.v1", "orig": a.orig, "fov": fov, "poses": len(poses), "pieces": {}}
    for name in [p for p in a.pieces.split(",") if p]:
        v, n, uv, subs = L.read_bin(odir / f"{name}.bytes")
        tris = np.concatenate(subs).astype(np.int64)
        res = mirror_piece(v, n, uv, tris, fov, poses)
        if res is None or not len(res["mirror"][3]):
            rep["pieces"][name] = {"mirrorTris": 0}
            print(name, "no mirror", flush=True)
            continue
        vm, nm, uvm, tm = res["mirror"]
        # rest identity: the mirror copies are hidden behind the current main surface at the rest pose
        mv, _mn, _muv, msubs = L.read_bin(pdir / f"{name}.bytes")
        pid, _ = L.id_render([(mv, np.concatenate(msubs)), (vm, tm)], fov)
        shown = int((pid == 1).sum())
        mname = f"Mesh_Back_{name[len('Mesh_'):]}_Mirror"
        L.write_bin(pdir / f"{mname}.bytes", vm, nm, uvm, tm)
        # the piece's own albedo, copied verbatim (every staged bin carries its own <stem>_albedo.png)
        shutil.copy2(pdir / f"{name}_albedo.png", pdir / f"{mname}_albedo.png")
        row = dict(env_rows[name])
        row.update({"name": mname, "mesh": row["mesh"].replace(f"/{name}.bytes", f"/{mname}.bytes"),
                    "texture": row["texture"].replace(f"/{name}_albedo.png", f"/{mname}_albedo.png")})
        env_rows[mname] = row
        rep["pieces"][name] = {**res["report"], "mirrorPiece": mname, "restShownPx": shown}
        print(name, json.dumps(rep["pieces"][name]), flush=True)
    rows[S.ENV_KEY]["bins"] = [env_rows[k] for k in sorted(env_rows)]
    S.ROWS.write_text(json.dumps(rows, indent=1), encoding="utf-8")
    sr_path = S.WORK / "stage_report.json"
    sr = json.loads(sr_path.read_text(encoding="utf-8"))
    sr["mirror"] = {**rep, "proofTier": "generated artifact / offline render"}
    sr_path.write_text(json.dumps(sr, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
