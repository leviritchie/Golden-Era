#!/usr/bin/env python3
"""One depth model per building: the Meshy body anchors its residual, and the building seam gate
(docs/homm3_town_building_seams.md).

The defect (2026-10-01, in game, installed rampart rx_layer_card_dfix): distant buildings broke into discrete layers
on a camera turn. A Meshy T2 layer ships two depth models side by side: the Meshy body (its own geometry, scaled about
the camera so its base sits on the contact) and the seed's residual (Mesh_BodyRest_<l> / *_rest / Mesh_Body_resid_<l>:
the sprite px the body leaves uncovered at rest) re-depthed per vertex from the sprite's own contact_v1 disparity
field. The two agree only at the contact. Everywhere else the residual sits in front of or behind the body it
borders, so on a pan the seam between them opens and the terrain shows through.

The rule (body_v1): the residual takes the body's depth. The body's rest front depth is rendered per native sprite px;
under the body the residual sits SEAM_BEHIND x behind that front (never z-fights it at rest), and every other px takes
the screened harmonic fill (SEAM_DECAY_DEFAULT) of the correction log(body / contact_v1), Dirichlet on the body and on
ground px further than SEAM_FLOOR_PX from it, so the field is continuous across the seam and returns to contact_v1's
floor away from the building. Residual triangles are never sunk (RESIDUAL_CUT_RATIO None: a sunk copy is a split
piece). Every vertex stays on its own pixel ray, so the rest pose is unchanged. Measured on rampart rx_layer_card_bgrp
(2026-10-01, hole-tested seam px, state full, sweep_left / right / high): contact_v1 1762 / 1972 / 2034 -> body_v1
85 / 84 / 81. Measured negatives, kept out: blurring or median-filtering the body correction (more seam splits), a
per-piece rigid correction (more splits and streak), the floor as a boundary right at the body's foot (the residual's
base triangles spanned the step and streaked, tbrmext0_rest 154 -> 1877 streak px at sweep_right), and sinking
residual triangles over a contact_v1 step (ray-ray splits 85 -> 188 at sweep_left).

The gate (seams_v1, building_depth.npz seam_*): every 4-adjacent rest px pair of one layer's own rest render that two
different pieces draw (bin x mesh-connected component), where at least one side is a residual ("ray") piece, is a
rest seam. Both sides' 3D points are projected at the vanilla camera's proof poses; the pair is split at a pose when
its screen distance grows by more than SEAM_OPEN_PX and the gap is see-through: the layer rendered alone at that pose
draws nothing at the pair's midpoint, or only a surface deeper than both sides by the validator's hole ratio
(seam_fill, the one rendered input; an opening the building's own surface fills, such as a stretched glue triangle,
is not a split). Meshy-Meshy pairs are the modelled body's own occlusion steps (the
body is closed geometry) and are not recorded. Solid-solid pairs are recorded and reported, not gated.
Proof tier: generated artifact (offline raster + projection). Not runtime proof.

Device (rest_seams / seams_for_build device=, else TOWN_FULL3D_DEVICE, default cuda; docs/town_gpu_kernels.md): cuda
renders every layer and proof pose from one town_gpu_kernels.Raster context (the 6 renders per layer reuse it; only
the layer's geometry is uploaded); cpu (a fresh TP.zbuffer context per render) is the reference. The adjacent-pair
search stays numpy on both: a torch port measured no faster per layer (2026-10-01) and would add torch's import. The
seam arrays are byte-identical (test_town_gpu_kernels.py). No silent fallback: cuda without a GL device fails.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import stronghold_full3d_common as SC  # noqa: E402
import stronghold_full3d_terrain as T  # noqa: E402

RESIDUAL_RULE = "body_v1"     # the default; the candidate pin's "residual" may name "contact_v1" (the pre-seams rule)
RESIDUAL_RULES = ("body_v2", "body_v1", "contact_v1")
# body_v2 (opt-in by pin, not the default; docs/homm3_town_building_seams.md "body_v2"): body_v1 with the field on a
# `sub` x finer grid than the native sprite px, residual vertices within `snapPx` frame px of the body blended onto its
# nearest rest px (sampled `snapSup` x the frame), and the residual mesh midpoint-subdivided `subdiv` times. Castle
# (2026-10-01): seams_v1 passes (87 split px, 0 failing layers, from 1094 / 13), but the residual's visible
# behind-streak at the review-board poses rises 68 -> 748 px (the subdivided border follows the body's steep
# silhouette depth), so the certificate's max goes 1701 -> 2037: a trade, not a fix
BODY_RULE_PARAMS = {"body_v1": {"sub": 1, "snapPx": 0.0, "snapSup": 1, "subdiv": 0},
                    "body_v2": {"sub": 4, "snapPx": 4.0, "snapSup": 4, "subdiv": 2}}
SEAM_BEHIND = 1.001          # a residual px under the body sits this far behind the body's rest front
RESIDUAL_CUT_RATIO = None     # body_v1 residual triangles are never sunk (a sunk copy is a split piece)
SEAM_DECAY_DEFAULT = 24.0    # native px: the body correction falls off as exp(-d / 24) into the residual (Rampart sweep 2026-10-01)
SEAM_FLOOR_PX = 16.0         # native px: ground further than this from the body keeps the floor; nearer, it moves with it
SEAM_SCHEMA = "seams_v2"           # off-frame corrected (validate_town_scene3d_contract)
SEAM_OPEN_PX = 2.0           # a rest seam pair whose screen distance grows by more than this (1080p px) is split
SEAM_POSES = ("cursor_left", "cursor_right", "sweep_left", "sweep_right", "sweep_high")
ROLE_CODE = {"ray": 0, "solid": 1, "meshy": 2}


# ------------------------------------------------------------------------------------------------ body_v1 depth
def residual_rule(pin: dict | None) -> str:
    """The residual rule a candidate pins (building_depth.json "residual"; default RESIDUAL_RULE). contact_v1 keeps
    the residual on the sprite's own contact_v1 field with BL.CUT_RATIO sinking (the rule before 2026-10-01)."""
    import os
    if os.environ.get("SEAM_RULE"):
        raise SystemExit("SEAM_RULE is retired: pin the residual rule in <candidate>/work/building_depth.json "
                         '("residual": "contact_v1" or "body_v1")')
    r = (pin or {}).get("residual", RESIDUAL_RULE)
    if r not in RESIDUAL_RULES:
        raise SystemExit(f"building_depth.json residual {r!r} must be one of {list(RESIDUAL_RULES)}")
    return r


def native_grid_px(L: dict, shape) -> tuple[np.ndarray, np.ndarray]:
    mh, mw = shape
    ys, xs = np.mgrid[0:mh, 0:mw]
    return (L["x"] + xs + 0.5) * SC.SCALE, (L["y"] + ys + 0.5) * SC.SCALE


def body_front_native(cam: dict, L: dict, shape, P_world: np.ndarray, F: np.ndarray) -> np.ndarray:
    """The Meshy body's rest front depth (camera forward, painting m) at each native sprite px centre; inf where the
    body does not cover it."""
    import town_full3d_t2_paint as TP
    z, _ = TP.zbuffer(cam, P_world, F, sup=1)
    H, W = z.shape
    fx, fy = native_grid_px(L, shape)
    ix, iy = np.floor(fx).astype(np.int64), np.floor(fy).astype(np.int64)
    ok = (ix >= 0) & (ix < W) & (iy >= 0) & (iy < H)
    out = np.full(shape, np.inf)
    out[ok] = z[iy[ok], ix[ok]]
    return out


def sub_grid_px(L: dict, shape, sub: int) -> tuple[np.ndarray, np.ndarray]:
    """Frame px of the centres of a grid sub x finer than the native sprite grid (shape = the native grid's)."""
    mh, mw = shape
    ys, xs = np.mgrid[0:mh * sub, 0:mw * sub]
    return (L["x"] + (xs + 0.5) / sub) * SC.SCALE, (L["y"] + (ys + 0.5) / sub) * SC.SCALE


def residual_field(cam: dict, L: dict, ld: dict, P_world: np.ndarray, F: np.ndarray, sub: int = 1,
                   snap: float = 0.0, ss: int = 1):
    """body_v1 on a grid sub x finer than the native sprite grid: the body's rest front, contact_v1's field (bilinear,
    as z_at reads it) and its ground / mask (nearest native px) sampled at the sub-grid centres, decay and floor
    distances scaled to stay the same in native px. Returns at(px, py) (frame px -> depth, bilinear on the sub grid)
    and the body_anchor report (with "sub")."""
    import town_full3d_t2_paint as TP
    import stronghold_full3d_buildings as BL
    from scipy.ndimage import map_coordinates
    shape = ld["mask"].shape
    fx, fy = sub_grid_px(L, shape, sub)
    z, _ = TP.zbuffer(cam, P_world, F, sup=1)
    H, W = z.shape
    ix, iy = np.floor(fx).astype(np.int64), np.floor(fy).astype(np.int64)
    ok = (ix >= 0) & (ix < W) & (iy >= 0) & (iy < H)
    zb = np.full(fx.shape, np.inf)
    zb[ok] = z[iy[ok], ix[ok]]
    m = ld["mask"] & np.isfinite(ld["z"])
    zf = BL._fill_nearest(np.where(m, ld["z"], 0.0), m)
    u = fx / SC.SCALE - L["x"] - 0.5
    v = fy / SC.SCALE - L["y"] - 0.5
    zs = map_coordinates(zf, [v, u], order=1, mode="nearest")
    ni = np.clip(np.floor(fy / SC.SCALE - L["y"]).astype(np.int64), 0, shape[0] - 1)
    nj = np.clip(np.floor(fx / SC.SCALE - L["x"]).astype(np.int64), 0, shape[1] - 1)
    g = None if ld.get("ground") is None else np.asarray(ld["ground"], bool)[ni, nj]
    lds = {"z": zs, "mask": np.ones(zs.shape, bool), "ground": g}
    out, rep = body_anchor(lds, zb, decay_px=SEAM_DECAY_DEFAULT * sub, floor_px=SEAM_FLOOR_PX * sub)
    rep = {**rep, "sub": int(sub), "decayPx": SEAM_DECAY_DEFAULT, "floorPx": SEAM_FLOOR_PX}
    zo = out["z"]
    snap = float(snap); ss = int(ss)
    if snap > 0:
        from scipy import ndimage as ndi
        zsn = z if ss == 1 else TP.zbuffer(cam, P_world, F, sup=ss)[0]
        cov = np.isfinite(zsn)
        dist, (jy, jx) = ndi.distance_transform_edt(~cov, return_indices=True)
        dist = dist / ss
        rep["snapPx"] = snap; rep["snapSup"] = ss

    def at(px, py):
        px = np.asarray(px, np.float64); py = np.asarray(py, np.float64)
        uu = px / SC.SCALE * sub - L["x"] * sub - 0.5
        vv = py / SC.SCALE * sub - L["y"] * sub - 0.5
        zf_ = map_coordinates(zo, [vv, uu], order=1, mode="nearest")
        if snap <= 0:
            return zf_
        xi = np.clip(np.floor(px * ss).astype(np.int64), 0, W * ss - 1)
        yi = np.clip(np.floor(py * ss).astype(np.int64), 0, H * ss - 1)
        dd = dist[yi, xi]
        zn = zsn[jy[yi, xi], jx[yi, xi]] * SEAM_BEHIND
        w = np.clip((snap - dd) / max(snap - 1.0, 1e-6), 0.0, 1.0)
        w = np.where(np.isfinite(zn), w, 0.0)
        zn = np.where(np.isfinite(zn), zn, zf_)
        return np.exp((1 - w) * np.log(zf_) + w * np.log(zn))

    return at, rep


def subdivide(v, n, uv, subs, levels: int):
    """Uniform midpoint subdivision (1 -> 4, levels times) of every triangle of every submesh. Shared edges share
    their midpoint, so the mesh stays crack-free and keeps its winding. New vertices average their edge's position and
    UV and take the normalised mean normal. Returns v, n, uv, subs ((-1, 3) index arrays per submesh)."""
    V_ = np.asarray(v, np.float64); N_ = np.asarray(n, np.float64); U_ = np.asarray(uv, np.float64)
    T = [np.asarray(t, np.int64).reshape(-1, 3) for t in subs]
    for _ in range(int(levels)):
        allt = np.concatenate(T) if T else np.zeros((0, 3), np.int64)
        k = len(allt)
        e = np.sort(np.concatenate([allt[:, [0, 1]], allt[:, [1, 2]], allt[:, [2, 0]]]), 1)
        ue, inv = np.unique(e, axis=0, return_inverse=True)
        inv = inv.ravel()
        nv = len(V_)
        nn = N_[ue[:, 0]] + N_[ue[:, 1]]
        nn = nn / np.maximum(np.linalg.norm(nn, axis=1, keepdims=True), 1e-9)
        V_ = np.concatenate([V_, 0.5 * (V_[ue[:, 0]] + V_[ue[:, 1]])])
        N_ = np.concatenate([N_, nn])
        U_ = np.concatenate([U_, 0.5 * (U_[ue[:, 0]] + U_[ue[:, 1]])])
        mab, mbc, mca = nv + inv[:k], nv + inv[k:2 * k], nv + inv[2 * k:]
        out, o = [], 0
        for t in T:
            m = len(t)
            a, b, c = t[:, 0], t[:, 1], t[:, 2]
            ab, bc, ca = mab[o:o + m], mbc[o:o + m], mca[o:o + m]
            out.append(np.stack([np.stack([a, ab, ca], 1), np.stack([ab, b, bc], 1), np.stack([ca, bc, c], 1),
                                 np.stack([ab, bc, ca], 1)], 1).reshape(-1, 3))
            o += m
        T = out
    return V_, N_, U_, T


def harmonic_fill(val: np.ndarray, known: np.ndarray, decay_px: float | None = None) -> np.ndarray:
    """Laplace fill of val over ~known (4-neighbour, Neumann at the grid edge, Dirichlet on known). decay_px: the
    screened fill (L + 1/decay_px^2) u = 0, which falls off as exp(-distance / decay_px) away from known."""
    from scipy.sparse import coo_matrix
    from scipy.sparse.linalg import spsolve
    h, w = val.shape
    unk = ~known
    if not unk.any():
        return val.astype(np.float64).copy()
    idx = -np.ones((h, w), np.int64)
    idx[unk] = np.arange(int(unk.sum()))
    n = int(unk.sum())
    rows, cols, data = [], [], []
    rhs = np.zeros(n)
    deg = np.zeros(n)
    uy, ux = np.nonzero(unk)
    me = idx[uy, ux]
    for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1)):
        ny, nx = uy + dy, ux + dx
        inb = (ny >= 0) & (ny < h) & (nx >= 0) & (nx < w)
        deg += inb
        nyc, nxc = np.clip(ny, 0, h - 1), np.clip(nx, 0, w - 1)
        ku = inb & unk[nyc, nxc]
        rows.append(me[ku]); cols.append(idx[nyc[ku], nxc[ku]]); data.append(-np.ones(int(ku.sum())))
        kk = inb & known[nyc, nxc]
        np.add.at(rhs, me[kk], val[nyc[kk], nxc[kk]])
    if decay_px:
        deg = deg + 1.0 / float(decay_px) ** 2
    rows.append(me); cols.append(me); data.append(deg)
    A = coo_matrix((np.concatenate(data), (np.concatenate(rows), np.concatenate(cols))), shape=(n, n)).tocsr()
    out = val.astype(np.float64).copy()
    out[unk] = spsolve(A, rhs)
    return out


def body_anchor(ld: dict, zb: np.ndarray, behind: float = SEAM_BEHIND, decay_px: float | None = SEAM_DECAY_DEFAULT,
                floor_px: float = SEAM_FLOOR_PX) -> tuple[dict, dict]:
    """body_v1: the residual's depth field from the Meshy body's rest front zb (body_front_native). The correction
    log(body x behind / contact_v1) is known on the body's px and filled over the rest of the sprite grid (decay_px:
    None = harmonic, the body's depth carried everywhere; a length = screened, it falls off to the residual's own
    contact_v1 depth). Ground px further than floor_px (native px) from the body are a second boundary (correction 0:
    they keep contact_v1's floor depth); ground nearer the body moves with it, so the floor between the body and its
    own far floor is a gentle blend rather than a step at the body's foot. The result is applied to the contact_v1
    field. Returns an ld for town_full3d_building_redepth.z_at (finite on the whole sprite grid) and its report. Fails
    closed when the body covers none of the sprite grid (nothing to anchor to)."""
    from scipy import ndimage as ndi
    import stronghold_full3d_buildings as BL
    cover = np.isfinite(zb)
    m = ld["mask"] & np.isfinite(ld["z"])
    if not cover.any() or not m.any():
        raise SystemExit("body_anchor: the Meshy body covers no px of its sprite grid at rest")
    zc = BL._fill_nearest(np.where(m, ld["z"], 0.0), m)
    c = np.where(cover, np.log(np.where(cover, zb, 1.0) * behind) - np.log(np.maximum(zc, 1e-6)), 0.0)
    ground = np.asarray(ld["ground"], bool) if ld.get("ground") is not None else np.zeros(zb.shape, bool)
    g = ground & ~cover & m
    far = g & (ndi.distance_transform_edt(~cover) > float(floor_px))
    u = harmonic_fill(np.where(far, 0.0, c), cover | far, decay_px)
    z = np.where(far, zc, zc * np.exp(u))
    up = m & ~ground & ~cover
    k_ = z[up] / zc[up]
    kg = z[g & ~far] / zc[g & ~far]
    rep = {"rule": RESIDUAL_RULE, "behind": behind, "decayPx": decay_px, "floorPx": float(floor_px),
           "bodyPx": int(cover.sum()), "residualUprightPx": int(up.sum()), "groundPx": int(g.sum()),
           "groundNearBodyPx": int((g & ~far).sum()),
           "shiftMedian": round(float(np.median(k_)), 4) if up.any() else None,
           "shiftP5P95": [round(float(x), 4) for x in np.percentile(k_, [5, 95])] if up.any() else None,
           "groundShiftP5P95": [round(float(x), 4) for x in np.percentile(kg, [5, 95])] if len(kg) else None}
    return {**ld, "z": z, "mask": np.ones(zb.shape, bool)}, rep


# ------------------------------------------------------------------------------------------------ rest seams
def _components(f: np.ndarray, n: int) -> np.ndarray:
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components
    if not len(f):
        return np.zeros(0, np.int64)
    A = coo_matrix((np.ones(len(f) * 2), (np.r_[f[:, 0], f[:, 1]], np.r_[f[:, 1], f[:, 2]])), shape=(n, n))
    return connected_components(A, directed=False)[1][f[:, 0]]


def local_cam(sc, cam: dict) -> dict:
    """A painting-world camera in the prefab frame (camera-rest local, x depthScale): the frame building_depth.npz P
    is stored in."""
    C = np.asarray(sc.C, np.float64)
    return {"pos": ((np.asarray(cam["pos"], np.float64) - sc.cpos) @ C) * sc.scale,
            "fwd": np.asarray(cam["fwd"], np.float64) @ C, "up": np.asarray(cam["up"], np.float64) @ C,
            "right": np.asarray(cam["right"], np.float64) @ C, "fov": float(cam["fov"])}


def rest_seams(sc, S, rows: dict, rep: dict, lids: list[str], device: str | None = None, load=None,
               faces: bool = False) -> dict:
    """The npz seam_* arrays: per layer (rendered alone at rest), every 4-adjacent px pair drawn by two different
    pieces with at least one non-Meshy side; endpoints in the prefab frame. Plus the proof poses (prefab frame).
    device: cpu (the reference) or cuda (town_gpu_kernels; the same arrays). load(key, bin name): the bin's
    (prefab-local vertices, faces) from memory (the recipe's Stage, town_full3d_recipe.seam_weld), or None to read the
    staged file. faces: also the drawing face of each side, seam_face_bin (n, 2) into seam_face_bins ("key/bin") and
    seam_face (n, 2) local face index (not part of the npz)."""
    import town_gpu_kernels as GK
    ras = GK.Raster() if GK.resolve_device(device) == "cuda" else None
    try:
        return _rest_seams(sc, S, rows, rep, lids, ras, load, faces)
    finally:
        if ras is not None:
            ras.release()


def _rest_seams(sc, S, rows: dict, rep: dict, lids: list[str], ras, load=None, faces: bool = False) -> dict:
    import town_full3d_t2_paint as TP
    from town_full3d_building_depth import piece_role, is_meshy
    cam = sc.cam
    A_, B_, L_, R_, H_ = [], [], [], [], []
    FB_, FL_, fbins = [], [], []
    names = []
    poses_w = {p: c for p, c in S.pan_cams(sc).items() if p in SEAM_POSES}
    if sorted(poses_w) != sorted(SEAM_POSES):
        raise SystemExit(f"rest_seams: proof poses {sorted(poses_w)} != {sorted(SEAM_POSES)}")
    for li, lid in enumerate(lids):
        k = S.PREFIX + lid
        meshy = is_meshy(rep["buildings"][lid])
        Ps, Fs, comp, role, fbin, flf = [], [], [], [], [], []
        off = coff = 0
        for b in rows[k]["bins"]:
            r = piece_role(lid, b["name"], meshy)
            # cloth (town_full3d_cloth.py): a moving copy of rest-front faces held in front of its backing on purpose;
            # its own gate is check_cloth_look, so it is no building seam
            # decal (town_full3d_sprite_decal.py): sprite paint lying on the environment's ground, not on the body
            if r in ("fx", "cloth", "decal") or b.get("kind", "lit") != "lit" or b.get("pos") is not None or b.get("rot") is not None:
                continue
            got = load(k, b["name"]) if load is not None else None
            if got is None:
                v, _, _, subs = S.read_bin(S.STAGE / k / f"{b['name']}.bytes")
                f = np.concatenate(subs).reshape(-1, 3).astype(np.int64)
            else:
                v, f = got
            c = _components(f, len(v))
            if faces:
                fbin.append(np.full(len(f), len(fbins), np.int32)); flf.append(np.arange(len(f), dtype=np.int64))
                fbins.append(f"{k}/{b['name']}")
            Ps.append(sc.cpos + (np.asarray(v, np.float64) / sc.scale) @ sc.C.T)
            Fs.append(f + off); comp.append(c + coff); role.append(np.full(len(f), ROLE_CODE[r]))
            off += len(v); coff += int(c.max()) + 1 if len(c) else 0
        names.append(lid)
        if not Fs:
            continue
        P = np.concatenate(Ps); F = np.concatenate(Fs); comp = np.concatenate(comp); role = np.concatenate(role)
        if faces:
            fbin, flf = np.concatenate(fbin), np.concatenate(flf)
        if ras is None:
            z, fid = TP.zbuffer(cam, P, F, sup=1)
            zpose = {p_: TP.zbuffer(poses_w[p_], P, F, sup=1)[0] for p_ in SEAM_POSES}
        else:
            ras.load(P, F)
            z, fid = ras.render(cam)
            zpose = {p_: ras.render(poses_w[p_], fid=False)[0] for p_ in SEAM_POSES}
        H, W = z.shape
        vis = fid >= 0
        fs = np.where(vis, fid, 0)
        pc = np.where(vis, comp[fs], -1)
        pr = np.where(vis, role[fs], -1)
        for dy, dx in ((0, 1), (1, 0)):
            a = (slice(0, H - dy), slice(0, W - dx)); bb = (slice(dy, H), slice(dx, W))
            m = vis[a] & vis[bb] & (pc[a] != pc[bb]) & ~((pr[a] == 2) & (pr[bb] == 2))
            ya, xa = np.nonzero(m)
            if not len(ya):
                continue
            yb, xb = ya + dy, xa + dx
            A_.append(_px_world(cam, xa, ya, z[ya, xa], W, H)); B_.append(_px_world(cam, xb, yb, z[yb, xb], W, H))
            L_.append(np.full(len(ya), li, np.int32))
            R_.append(np.stack([pr[ya, xa], pr[yb, xb]], 1).astype(np.int8))
            if faces:
                fa_, fb_ = fid[ya, xa], fid[yb, xb]
                FB_.append(np.stack([fbin[fa_], fbin[fb_]], 1)); FL_.append(np.stack([flf[fa_], flf[fb_]], 1))
            # what the layer alone draws at the pair's midpoint at each proof pose (the validator's hole test)
            fill = np.full((len(ya), len(SEAM_POSES)), np.inf, np.float32)
            for pi, pose in enumerate(SEAM_POSES):
                zp = zpose[pose]
                hp, wp = zp.shape
                qa = T.project(poses_w[pose], A_[-1]); qb = T.project(poses_w[pose], B_[-1])
                mx = np.floor(0.5 * (qa[0] + qb[0])).astype(np.int64)
                my = np.floor(0.5 * (qa[1] + qb[1])).astype(np.int64)
                ok = (mx >= 0) & (mx < wp) & (my >= 0) & (my < hp)
                fill[ok, pi] = zp[my[ok], mx[ok]] * float(sc.scale)
            H_.append(fill)
    C = np.asarray(sc.C, np.float64)
    to_l = lambda w: (((w - sc.cpos) @ C) * sc.scale).astype(np.float32)
    pc_ = {p: local_cam(sc, c) for p, c in poses_w.items()}
    cat = lambda xs, shape, dt: np.concatenate(xs) if xs else np.zeros(shape, dt)
    extra = {"seam_face_bin": cat(FB_, (0, 2), np.int32), "seam_face": cat(FL_, (0, 2), np.int64),
             "seam_face_bins": list(fbins)} if faces else {}
    return extra | {"seam_a": to_l(cat(A_, (0, 3), np.float64)), "seam_b": to_l(cat(B_, (0, 3), np.float64)),
            "seam_layer": cat(L_, (0,), np.int32), "seam_roles": cat(R_, (0, 2), np.int8),
            "seam_fill": cat(H_, (0, len(SEAM_POSES)), np.float32),
            "seam_layers": np.array(names), "seam_pose_names": np.array(list(SEAM_POSES)),
            "seam_pose_pos": np.array([pc_[p]["pos"] for p in SEAM_POSES]),
            "seam_pose_fwd": np.array([pc_[p]["fwd"] for p in SEAM_POSES]),
            "seam_pose_up": np.array([pc_[p]["up"] for p in SEAM_POSES]),
            "seam_pose_right": np.array([pc_[p]["right"] for p in SEAM_POSES]),
            "seam_fov": np.float64(cam["fov"]), "seam_frame": np.array([SC.W, SC.H], np.int32)}


def _px_world(cam, x, y, z, W, H):
    t = np.tan(np.radians(cam["fov"]) / 2)
    xn = ((x + 0.5) / W * 2 - 1) * t * W / H
    yn = (1 - (y + 0.5) / H * 2) * t
    d = (np.asarray(cam["fwd"])[None] + xn[:, None] * np.asarray(cam["right"])[None]
         + yn[:, None] * np.asarray(cam["up"])[None])
    return np.asarray(cam["pos"])[None] + d * np.asarray(z, np.float64)[:, None]


def applied_rule(rep: dict) -> str | None:
    """The residual rule the stage report records for its Meshy layers (contactDepth.residualDepth.rule); fails
    closed when layers disagree. None: no Meshy layer was redepthed."""
    rules = {((b.get("contactDepth") or {}).get("residualDepth") or {}).get("rule")
             for b in (rep.get("buildings") or {}).values() if (b.get("contactDepth") or {}).get("meshy")}
    if len(rules) > 1:
        raise SystemExit(f"seams: the stage report mixes residual rules {sorted(map(str, rules))}")
    return next(iter(rules), None)


def seams_for_build(rows: dict, rep: dict, lids: list[str], device: str | None = None) -> tuple[dict, dict]:
    """building_depth.build's hook: the npz seam_* arrays and the block's seams entry (measured with the validator's
    own building_seam_stats, not judged here)."""
    import stronghold_full3d_scene as S
    if str(HERE.parent) not in sys.path:
        sys.path.insert(0, str(HERE.parent))
    import validate_town_scene3d_contract as V
    sc = S.Scene()
    arr = rest_seams(sc, S, rows, rep, lids, device)
    st = V.building_seam_stats(arr)
    block = {"schema": SEAM_SCHEMA, "openPx": V.BUILDING_SEAM_OPEN_PX, "splitShareMax": V.BUILDING_SEAM_SPLIT_MAX,
             "splitMinPairs": V.BUILDING_SEAM_SPLIT_MIN_PAIRS, "poses": list(SEAM_POSES),
             "residualRule": applied_rule(rep), "layers": st,
             "holeRatio": V.BUILDING_SEAM_HOLE_RATIO,
             "rule": "rest-adjacent px of one layer drawn by two pieces with a residual side; split = at some proof "
                     "pose its screen distance grows by more than openPx and the layer alone draws nothing at the "
                     "midpoint, or only something more than holeRatio x deeper than both sides (a see-through gap); "
                     "seams_v2: a pose counts only where the pair's midpoint is on its screen, and pairs on screen at "
                     "no proof pose are counted apart as residualUnmeasured"}
    return arr, block
