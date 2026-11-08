#!/usr/bin/env python3
"""contact_v1 building depth on an already staged candidate (docs/homm3_town_building_contact_depth.md).

    set TOWN_FULL3D_FACTION=cove & set TOWN_FULL3D_CANDIDATE=pb_dfix
    python tools/homm3_town_scene_meshes/town_full3d_building_redepth.py apply

The candidate must pin <candidate>/work/building_depth.json {"mode": "contact_v1"} (opt-in; no pin = refused). The
staged candidate keeps its terrain, sky, periphery, near field, props and every repair method; only the building
layers move, and every move keeps the rest pose pixel-exact:
  * solid / relief layers: restaged by stronghold_full3d_buildings.stage_buildings on the contact_v1 depth.
  * Meshy T2 layers: ONE contact per layer, the Meshy body's own base (its lowest 2% of world height, projected at
    rest). contact_v1 (layer_depth contact_px) puts that contact on the terrain right under it; the Meshy pieces
    (Mesh_Body_<l>, Mesh_BodyM_<l>, Mesh_Body_<l>_hull) are scaled about the camera so their base sits at that depth
    (the projection of a scaling about the camera is unchanged), and the seed residual pieces (Mesh_BodyRest_<l>,
    Mesh_Body_<l>_rest, Mesh_Body_resid_<l>: the seed's front triangles, every vertex on its own pixel ray) take the
    contact_v1 depth at their own pixels, anchored at the same contact.
  * a residual / water triangle whose new depth spread exceeds stronghold_full3d_buildings.CUT_RATIO is sunk (its
    own copy of its three vertices at its farthest depth, same rays): no curtain is built across a depth step.
  * effects: a T2 layer's Fx bins and particle groups ride with its Meshy body (the same scale about the camera);
    a solid layer's Fx_ meshes keep their offset to the front (each vertex scaled by new / legacy front depth at its
    pixel) and its particle groups slide by that ratio at their own pixel.
  * rest occlusion (order_pass): where the HoMM3 art draws one sprite over another (both opaque) or over the
    terrain, its 3D layer must be the nearest surface there; layers are pulled nearer (scaled about the camera) in
    ascending HoMM3 z until it is, and the pass fails when a layer would need < ORDER_MIN_SCALE or stays hidden on
    more than ORDER_RESIDUAL_MAX of its own top px (re-rendered after the pulls, order_residual).
  * ground_rest: a pull's lift of a floor-lying ground part past the upright height is undone outside every other
    sprite (the pull stays where it decides the HoMM3 order).
Then the catalog (with its buildingDepth block), the preview and the see-through gate, as a building stage does.
Proof tier: generated artifact (offline); the Unity editor render re-measures independently.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import stronghold_full3d_common as SC  # noqa: E402
import stronghold_full3d_terrain as T  # noqa: E402
import stronghold_full3d_buildings as BL  # noqa: E402
import town_full3d_building_depth as BD  # noqa: E402
import town_full3d_building_seams as SEAMS  # noqa: E402
from town_full3d_building_depth import piece_role, is_meshy  # noqa: E402

MESHY_BASE_Q = 0.02          # share of the Meshy body's world height counted as its base


def to_world(sc, v):
    return sc.cpos + (np.asarray(v, np.float64) / sc.scale) @ sc.C.T


def scale_bin_about_camera(S, path: Path, b: dict, k: float) -> None:
    """Scale one staged bin about the camera (the prefab origin) by k: its vertices and, for a posed bin (a holder at
    b["pos"] / b["rot"] whose vertices are holder-local: a swing / spin / keyed card, a water sheet), its holder
    position too. p = pos + R v maps to k p = k pos + R (k v), so the projection is unchanged. Scaling the local
    vertices alone shrinks the card about its own pivot and leaves it at the old depth: the 2026-10-01 tower
    tbtwdw_0_2 pendulum (body pulled to 0.45x, swing card left 18 units behind it, hidden in game)."""
    v, n, uv, subs = S.read_bin(path)
    S.write_bin(path, np.asarray(v, np.float64) * k, n, uv, subs)
    if b.get("pos") is not None:
        b["pos"] = [float(x) * k for x in b["pos"]]


def posed_ride_check(S, rows: dict, seed_rows: dict, seed_stage: Path, out: dict) -> None:
    """Fail closed unless every posed bin of a Meshy layer rode with its body: holder pos / seed pos = the layer's own
    Meshy body vertices / seed vertices (both scaled about the camera; scale_bin_about_camera's contract, checked on
    the rows and bins actually written). seed_rows must be a fresh read: `rows` took the seed's row objects."""
    bad = []
    for lid, r in out.items():
        if not r["meshy"]:
            continue
        pk = S.PREFIX + lid
        posed = [b for b in rows[pk]["bins"] if b.get("pos") is not None]
        if not posed:
            continue
        body = next(b["name"] for b in rows[pk]["bins"] if piece_role(lid, b["name"], True) == "meshy")
        v0 = np.asarray(S.read_bin(seed_stage / pk / f"{body}.bytes")[0], np.float64)
        v1 = np.asarray(S.read_bin(S.STAGE / pk / f"{body}.bytes")[0], np.float64)
        k = float(np.median(np.linalg.norm(v1, axis=1) / np.maximum(np.linalg.norm(v0, axis=1), 1e-9)))
        seed = {b["name"]: b for b in seed_rows[pk]["bins"]}
        for b in posed:
            want = np.asarray(seed[b["name"]]["pos"], np.float64) * k
            if not np.allclose(np.asarray(b["pos"], np.float64), want, rtol=1e-3, atol=1e-3):
                bad.append((lid, b["name"], [round(float(x), 3) for x in b["pos"]], [round(float(x), 3) for x in want]))
    if bad:
        raise SystemExit(f"redepth: posed bins did not ride with their Meshy body (pos, want): {bad}")


def quat_to_mat(q) -> np.ndarray:
    x, y, z, w = (float(c) for c in q)
    return np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                     [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                     [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])


def bin_prefab_vertices(b: dict, v) -> np.ndarray:
    """A bin's vertices in the prefab frame (camera at the origin): holder-local vertices through pos / rot."""
    v = np.asarray(v, np.float64)
    if b.get("pos") is None:
        return v
    R = quat_to_mat(b["rot"]) if b.get("rot") is not None else np.eye(3)
    return v @ R.T + np.asarray(b["pos"], np.float64)


def z_at(L: dict, ld: dict):
    """Bilinear contact_v1 / legacy depth at frame px, the mask's nearest px outside it (front_surface's rule)."""
    from scipy.ndimage import map_coordinates
    m = ld["mask"]
    zf = BL._fill_nearest(np.where(m, ld["z"], 0.0), m)

    def at(px, py):
        u = np.asarray(px, np.float64) / SC.SCALE - L["x"] - 0.5
        v = np.asarray(py, np.float64) / SC.SCALE - L["y"] - 0.5
        return map_coordinates(zf, [v, u], order=1, mode="nearest")
    return at


def ray_redepth(sc, v, subs, at, cut_ratio: float | None = BL.CUT_RATIO):
    """Every vertex to the new depth at its own rest pixel; triangles spanning a depth step (cut_ratio; None: never)
    are sunk."""
    v = np.asarray(v, np.float64)
    px, py, zc = T.project(sc.cam, to_world(sc, v))
    zn = at(px, py)
    vn = v * (zn / zc)[:, None]
    extra_v, new_subs, sunk = [], [], 0
    base = len(vn)
    for t in subs:
        t = np.asarray(t, np.int64).reshape(-1, 3)
        zt_ = zn[t]
        cut = (zt_.max(1) / np.maximum(zt_.min(1), 1e-6) > cut_ratio) if cut_ratio else np.zeros(len(t), bool)
        keep = t[~cut]
        if cut.any():
            ct = t[cut].ravel()
            zmax = np.repeat(zt_[cut].max(1), 3)
            extra_v.append((ct, vn[ct] * (zmax / zn[ct])[:, None]))
            idx = base + np.arange(len(ct)).reshape(-1, 3)
            base += len(ct)
            keep = np.concatenate([keep, idx])
            sunk += int(cut.sum())
        new_subs.append(keep)
    src = np.concatenate([np.arange(len(vn))] + [c for c, _ in extra_v]) if extra_v else np.arange(len(vn))
    if extra_v:
        vn = np.concatenate([vn] + [p for _, p in extra_v])
    return vn, src, new_subs, sunk, (px, py, zc, zn)


def meshy_base(sc, L: dict, vs: list):
    """The Meshy pieces' base: native (row, col) of its lowest MESHY_BASE_Q of world height at rest, its depth.
    Measured negative (Cove 2026-10-01): anchoring the body at the sprite's own upright contact instead (the body's
    rest depth over the contact band) needed more and larger order_pass pulls (tbcvhal3 0.43x, tbcvtave 0.45x,
    tbcvhall 0.65x, tbcvpir2 0.62x behind the terrain) than this base (tbcvtave 0.56x, others >= 0.74x but the far
    tbcvcas3 / tbcvgmg4 ~0.4-0.5x), because the Cove fits' pseudo-ground covers that band nearer than the body."""
    V = np.concatenate([np.asarray(v, np.float64) for v in vs])
    P = to_world(sc, V)
    y = P[:, 1]
    lo = y.min()
    b = y <= lo + MESHY_BASE_Q * (y.max() - lo)
    px, py, zc = T.project(sc.cam, P[b])
    return (float(np.median(py)) / SC.SCALE - L["y"], float(np.median(px)) / SC.SCALE - L["x"],
            float(np.median(zc)), int(b.sum()))


ORDER_Q = 0.01               # share of a layer's own HoMM3-top px allowed to stay behind (raster edge noise)
ORDER_MARGIN = 1.002         # the pulled-forward layer clears what it covers by this ratio
ORDER_MIN_SCALE = 0.3        # a layer pulled nearer than this x its contact depth is refused (fail closed); Cove
                             # tbcvgmg4 (contact on the cap-clamped backdrop, 385 m) needs 0.49 to sit in front of tbcvsor2
ORDER_RESIDUAL_MAX = 0.02    # after the pass, no layer may stay behind something on more than this share of its top px
ORDER_GROUND_H_M = 0.5      # ground_rest: a vertex this close to the floor plane before a pull is floor-lying
GROUND_RAMP_PX = 64.0       # ground_rest: the return fades in over this rest screen distance (frame px) from the pull


def order_options() -> dict:
    """The candidate pin's optional "order" block (opt-in, docs/homm3_town_building_contact_depth.md "Near layers"):
    q (the terrain cap quantile, default ORDER_Q) and artSameDE (CIELAB; default None = off). A sprite px whose colour
    is within artSameDE of the background painting under it restates the background (Castle tbcsblak redraws the
    roof of the painted cottage in front of it, median dE 3.8): the HoMM3 art states no order against the terrain /
    environment there, and what the rest pose shows there is the same either way, so it neither caps a pull nor
    counts as residual."""
    pin = BL.building_depth_pin() or {}
    o = dict(pin.get("order") or {})
    bad = set(o) - {"q", "artSameDE", "layerShare"}
    if bad:
        raise SystemExit(f"redepth: building_depth.json order block has unknown keys {sorted(bad)}")
    q = float(o.get("q", ORDER_Q))
    if not (0.0 < q <= ORDER_RESIDUAL_MAX):
        raise SystemExit(f"redepth: order q {q} must be in (0, ORDER_RESIDUAL_MAX={ORDER_RESIDUAL_MAX}]")
    de = o.get("artSameDE")
    ls = o.get("layerShare", False)
    if not isinstance(ls, bool):
        raise SystemExit(f"redepth: order layerShare {ls!r} must be true or false")
    return {"q": q, "artSameDE": None if de is None else float(de), "layerShare": ls}


def art_same(lid: str, de_max: float | None) -> np.ndarray:
    """Rect px (TH, TW) where the layer's opaque sprite px is within de_max (CIELAB) of the background painting."""
    if de_max is None:
        return np.zeros((T.TH, T.TW), bool)
    from skimage.color import rgb2lab
    L = SC.layers()[lid]
    bg = SC.background_rgba()
    lb = rgb2lab(np.asarray(bg.convert("RGB"), np.float64) / 255.0)
    s = np.asarray(SC.sprite(L), np.float64)
    a = s[..., 3] > 127
    ls = rgb2lab(s[..., :3] / 255.0)
    same = np.zeros(lb.shape[:2], bool)
    ys, xs = np.nonzero(a)
    yy, xx = ys + int(L["y"]), xs + int(L["x"])
    ok = (yy >= 0) & (yy < lb.shape[0]) & (xx >= 0) & (xx < lb.shape[1])
    same[yy[ok], xx[ok]] = np.linalg.norm(ls[ys[ok], xs[ok]] - lb[yy[ok], xx[ok]], axis=1) < de_max
    fy, fx = np.mgrid[0:T.TH, 0:T.TW]
    return same[np.clip((fy / SC.SCALE).astype(int), 0, lb.shape[0] - 1),
                np.clip((fx / SC.SCALE).astype(int), 0, lb.shape[1] - 1)]


def homm3_top(lids: list[str]) -> tuple[np.ndarray, list[np.ndarray]]:
    """Rect px (TH, TW) -> index into lids of the top HoMM3 sprite (positions.json z order, alpha > 127), -1 none;
    and each layer's own opaque px (rect px)."""
    lays = SC.layers()
    bg = SC.background_rgba()
    top = np.full((bg.height, bg.width), -1, np.int32)
    fy, fx = np.mgrid[0:T.TH, 0:T.TW]
    ny = np.clip((fy / SC.SCALE).astype(int), 0, bg.height - 1)
    nx = np.clip((fx / SC.SCALE).astype(int), 0, bg.width - 1)
    own = [None] * len(lids)
    for i in sorted(range(len(lids)), key=lambda i: lays[lids[i]].get("z", 0)):
        L = lays[lids[i]]
        a = np.asarray(SC.sprite(L))[..., 3] > 127
        o = np.zeros((bg.height, bg.width), bool)
        ys, xs = np.nonzero(a)
        yy, xx = ys + int(L["y"]), xs + int(L["x"])
        ok = (yy >= 0) & (yy < bg.height) & (xx >= 0) & (xx < bg.width)
        top[yy[ok], xx[ok]] = i
        o[yy[ok], xx[ok]] = True
        own[i] = o[ny, nx]
    return top[ny, nx], own


def front_depth(sc, S, prefab: str, names: list[str]) -> np.ndarray:
    """Rest camera z (painting m) of the nearest of these staged bins per rect px, inf where none."""
    import town_full3d_t2_paint as TP
    Ps, Fs, n0 = [], [], 0
    for nm in names:
        v, _n, _uv, subs = S.read_bin(S.STAGE / prefab / f"{nm}.bytes")
        Ps.append(to_world(sc, v))
        Fs.append(np.concatenate([np.asarray(t, np.int64).reshape(-1, 3) for t in subs]) + n0)
        n0 += len(v)
    if not Ps:
        return np.full((T.TH, T.TW), np.inf)
    z, _ = TP.zbuffer(sc.cam, np.concatenate(Ps), np.concatenate(Fs), sup=1)
    return z[:T.TH, :T.TW]


def order_pass(sc, S, rows: dict, lids_by_state: dict) -> dict:
    """Rest occlusion: where a HoMM3 sprite is the top layer, its 3D layer must be the nearest surface - in front of
    the terrain (environment Mesh_ bins: no Fx_, Sky_ or Mesh_Prop_) and of every layer below it in the HoMM3 z order.
    Each state's layers are taken in ascending z; a layer whose own top px are covered (beyond ORDER_Q) is scaled about
    the camera (rest projection unchanged) just in front of what covers it. Layers are only ever pulled nearer, so a
    layer below never needs revisiting; a layer already settled by an earlier state keeps its scale (and is measured
    in the residual). contact_v1 places each layer on its own contact; this pass is what keeps the painting's
    occlusion where two contacts disagree with the HoMM3 draw order (Cove 2026-10-01: tbcvsmrk behind tbcvmark,
    tbcvtave behind tbcvhal3, the far castles behind the cap-clamped backdrop)."""
    env = [b["name"] for b in rows[S.ENV_KEY]["bins"] if b["name"].startswith("Mesh_")
           and not b["name"].startswith("Mesh_Prop_")]
    E = front_depth(sc, S, S.ENV_KEY, env)
    lays = SC.layers()
    scale, report, F = {}, {}, {}
    opt = order_options()

    def body(lid):
        return [b["name"] for b in rows[S.PREFIX + lid]["bins"] if not b["name"].startswith("Fx_")]

    def front(lid):
        if lid not in F:
            F[lid] = front_depth(sc, S, S.PREFIX + lid, body(lid))
        return F[lid]
    # one pass over every layer of every state in ascending HoMM3 z (ties: list order, as homm3_top draws them); a
    # layer's caps come from every state it is drawn in, so a layer shared by two states clears both
    states = {k: [l for l in v if S.PREFIX + l in rows] for k, v in lids_by_state.items()}
    tops = {k: homm3_top(v) for k, v in states.items()}
    glob = list(dict.fromkeys(l for v in states.values() for l in v))
    rank = {l: (lays[l].get("z", 0), n) for n, l in enumerate(glob)}
    for lid in sorted(glob, key=rank.get):
        caps, top_px, where = {}, 0, []
        for state, lids in states.items():
            if lid not in lids:
                continue
            top, own = tops[state]
            i = lids.index(lid)
            mine = (top == i) & np.isfinite(front(lid))
            if not mine.any():
                continue
            top_px += int(mine.sum())
            where.append(state)
            fl = F[lid][mine]
            e = np.where(art_same(lid, opt["artSameDE"])[mine], np.inf, E[mine])
            ok = np.isfinite(e)
            if ok.sum() >= 20:
                # the quantile runs over every top px (art-same px count as clear), so q is a share of the layer
                r_ = np.where(ok, e / fl, np.inf)
                caps["terrain"] = min(caps.get("terrain", 9.9), float(np.quantile(r_, opt["q"])) / ORDER_MARGIN)
            for j, m in enumerate(lids):
                # only where the HoMM3 art states the order: both sprites opaque, this one on top (a lower layer's
                # 3D body spilling past its own sprite - a Meshy silhouette - is that layer's fit, not an order fact)
                if m == lid or rank[m] > rank[lid]:
                    continue
                both = own[j][mine]
                if both.sum() < 20:
                    continue
                fm_ = front(m)[mine] * scale.get(m, 1.0)
                ok = np.isfinite(fm_) & both
                if ok.sum() >= 20:
                    if opt["layerShare"]:
                        # order.layerShare (opt-in): q is a share of the layer's own top px, as for the terrain cap
                        # (px where m does not overlap count as clear), so a tail of a few overlap px does not set
                        # the pull (fortress tbfrdw_0_2: 0.94% of its top px behind tbfrcstl_3 pulled it 0.69x)
                        r_ = np.where(ok, fm_ / fl, np.inf)
                        caps[m] = min(caps.get(m, 9.9), float(np.quantile(r_, opt["q"])) / ORDER_MARGIN)
                    else:
                        caps[m] = min(caps.get(m, 9.9), float(np.quantile(fm_[ok] / fl[ok], ORDER_Q)) / ORDER_MARGIN)
        if not top_px:
            continue
        s_ = min([1.0] + list(caps.values()))
        if s_ < ORDER_MIN_SCALE:
            worst = min(caps, key=caps.get)
            raise SystemExit(f"redepth order: {lid} would have to come {s_:.3f}x nearer to clear {worst} at its own "
                             f"HoMM3 px (its contact is far behind what the painting draws under it)")
        scale[lid] = s_
        report[lid] = {"states": where, "scale": round(s_, 4), "topPx": top_px,
                       "by": min(caps, key=caps.get) if s_ < 1.0 else None}
    return {"scale": scale, "layers": report}


def ground_rest(sc, S, rows: dict, lids_by_state: dict, scale: dict, meshy_lids: set, body_keeps: bool = False) -> dict:
    """After the pulls: a pulled ray / solid piece's floor-lying vertices (within ORDER_GROUND_H_M of the floor plane
    before the pull, and lifted by it past BD.UPRIGHT_H_M) go back to their unpulled depth - capped just in front of
    the rendered terrain - wherever their rest px lies outside every other layer's own HoMM3 sprite. There no other building can occlude them or be occluded
    by them, so the HoMM3 order the pull exists for is untouched and the ground part lies on the floor instead of
    floating by the pull (tower tbtwdw_0_2 at 0.64x: its deck rose 7 m and measured 21 m deep over 4.8 m). Inside
    another sprite they keep the pull (the measured floor-keep negative in order_residual). The return fades in over
    GROUND_RAMP_PX from the vertices that keep the pull (ground_ramp_v1), so the piece stays one surface. Each vertex
    stays on its own pixel ray, so the rest pose is unchanged; the residual is re-measured after. Measured
    (2026-10-01, see-through seam pairs): the earlier tear (mixed triangles on their own pulled copies) opened fortress
    ssr_dfix tbfrmage_3 / tbfrmark / tbfrsilo / tbfrtvrn by p99 70-120 px; the ramp closes them, but on a deep pull
    its skirt counts as upright span (tbfrblak at 0.61x: resid span/width 5.28 torn -> 8.38 ramped). A return that
    also frees px whose lower-z-order layers stay behind the floor (instead of every other sprite's px) was measured:
    tbfrblak 8.38 -> 5.08 but tbfrdw_0_2 3.37 -> 3.89, so it is not kept."""
    env = [b["name"] for b in rows[S.ENV_KEY]["bins"] if b["name"].startswith("Mesh_")
           and not b["name"].startswith("Mesh_Prop_")]
    E = front_depth(sc, S, S.ENV_KEY, env)
    fn_, fd = BD.floor_local()
    other: dict[str, np.ndarray] = {}
    for lids in lids_by_state.values():
        lids = [l for l in lids if S.PREFIX + l in rows]
        _, own = homm3_top(lids)
        for i, lid in enumerate(lids):
            o = np.zeros_like(own[i])
            for j in range(len(lids)):
                if j != i:
                    o |= own[j]
            other[lid] = other[lid] | o if lid in other else o
    rep = {}
    for lid, k in scale.items():
        if k >= 1.0 or lid not in other:
            continue
        pk = S.PREFIX + lid
        meshy = lid in meshy_lids
        moved = total = 0
        work, keep_xy = [], []
        for b in rows[pk]["bins"]:
            role = piece_role(lid, b["name"], meshy)
            path = S.STAGE / pk / f"{b['name']}.bytes"
            if role == "meshy" and body_keeps:
                # ground_ramp_v2 (with body_v2): the Meshy body keeps the pull: the ramp fades in from it too, or the residual's floor would step
                # off the body's foot (castle tbcshal3 at 0.89x: its foot seam split at sweep_right)
                vm = np.asarray(S.read_bin(path)[0], np.float64)
                pxm, pym, _ = T.project(sc.cam, to_world(sc, vm))
                keep_xy.append(np.stack([pxm, pym], 1))
            if role not in ("ray", "solid"):
                continue
            v, n, uv, subs = S.read_bin(path)
            v = np.asarray(v, np.float64)
            h0 = (v / k / T.DEPTH_SCALE) @ fn_ - fd
            px, py, zc = T.project(sc.cam, to_world(sc, v))
            xi = np.clip(np.round(px).astype(int), 0, T.TW - 1)
            yi = np.clip(np.round(py).astype(int), 0, T.TH - 1)
            inr = (px >= 0) & (px < T.TW) & (py >= 0) & (py < T.TH)
            h1 = (v / T.DEPTH_SCALE) @ fn_ - fd
            # only where the pull stood the ground up past the gate's upright height: a pull of a few % lifts it
            # under a metre, and returning it there only splits the piece (rampart tbrmdw_0_2 at 0.97x: 6065
            # vertices returned, Cull Back see-through 2396 -> 3799 px over the sweeps and orbits)
            sel = (h0 < ORDER_GROUND_H_M) & (h1 > BD.UPRIGHT_H_M) & inr & ~other[lid][yi, xi]
            e = E[yi, xi]
            zt = np.minimum(zc / k, np.where(np.isfinite(e), e / ORDER_MARGIN, np.inf))
            sel &= zt > zc
            total += len(v)
            keep_xy.append(np.stack([px[~sel], py[~sel]], 1))
            work.append((path, v, n, uv, subs, px, py, zc, zt, sel))
        keep = np.concatenate(keep_xy) if keep_xy else np.zeros((0, 2))
        tree = None
        for path, v, n, uv, subs, px, py, zc, zt, sel in work:
            if sel.any():
                moved += int(sel.sum())
                # ground_ramp_v1 (docs/homm3_town_building_seams.md): the return fades in over GROUND_RAMP_PX of rest
                # screen distance from every vertex of the layer that keeps the pull (its Meshy body included), so
                # the building stays one surface. Measured negative (rampart rx_layer_card_bgrp 2026-10-01): the
                # mixed triangles kept the pull on their own vertex copies, and those copies came apart from the
                # returned floor at the sweeps (tbrmhal3 117, tbrmext0 69 split seam px).
                from scipy.spatial import cKDTree
                w = np.zeros(len(v))
                if len(keep):
                    tree = cKDTree(keep) if tree is None else tree
                    d, _ = tree.query(np.stack([px[sel], py[sel]], 1))
                    w[sel] = np.clip(d / GROUND_RAMP_PX, 0.0, 1.0)
                else:
                    w[sel] = 1.0
                zn = zc * np.exp(w * np.log(np.where(sel, zt, zc) / zc))
                vn = v * (zn / zc)[:, None]
                S.write_bin(path, vn, n, uv, subs)
        rep[lid] = {"groundRest": moved, "groundRestRule": "ground_ramp_v2" if body_keeps else "ground_ramp_v1", "rampPx": GROUND_RAMP_PX, "verts": total}
    return rep


def order_residual(sc, S, rows: dict, lids_by_state: dict, report: dict) -> None:
    """Per state, the share of each ordered layer's own HoMM3-top px where something else is nearest, measured on the
    staged bins after the pulls were written (re-rendered, not predicted from the scales). Measured negative (2026-10-01):
    leaving a pulled ray / solid piece's floor-lying vertices on the floor plane (so a pull does not lift its ground
    part) hid them behind terrain that stands above the plane - rampart tbrmdw_4_2 3.7%, castle tbcsdock 46% residual;
    moving them only to just in front of the rendered terrain instead left them behind the layers the pull was
    clearing (rampart tbrmdw_1_2 behind tbrmhrd1) and tore pulled bodies off their own ground (Cove tbcvgmg4_rest
    201 m deep at 0.49x). A pull is one rigid scale of the whole layer."""
    env = [b["name"] for b in rows[S.ENV_KEY]["bins"] if b["name"].startswith("Mesh_")
           and not b["name"].startswith("Mesh_Prop_")]
    E = front_depth(sc, S, S.ENV_KEY, env)
    lays = SC.layers()
    states = {k: [l for l in v if S.PREFIX + l in rows] for k, v in lids_by_state.items()}
    glob = list(dict.fromkeys(l for v in states.values() for l in v))
    rank = {l: (lays[l].get("z", 0), n) for n, l in enumerate(glob)}
    opt = order_options()
    F = {l: front_depth(sc, S, S.PREFIX + l, [b["name"] for b in rows[S.PREFIX + l]["bins"]
                                              if not b["name"].startswith("Fx_")]) for l in glob}
    for state, lids in states.items():
        top, own = homm3_top(lids)
        for i, lid in enumerate(lids):
            if lid not in report:
                continue
            mine = (top == i) & np.isfinite(F[lid])
            if not mine.any():
                continue
            zl = F[lid][mine]
            hid = np.isfinite(E[mine]) & (E[mine] < zl) & ~art_same(lid, opt["artSameDE"])[mine]
            for j, m in enumerate(lids):
                if j == i or rank[m] > rank[lid]:
                    continue
                hid |= own[j][mine] & (F[m][mine] < zl)
            report[lid]["residual_" + state] = round(float(hid.mean()), 4)


def apply(dry: bool = False) -> int:
    import stronghold_full3d_scene as S
    if BL.building_depth_pin() is None:
        raise SystemExit("redepth: the candidate has no work/building_depth.json contact_v1 pin (opt-in per candidate)")
    import shutil
    pin = BL.building_depth_pin()
    seed = pin.get("seed")
    if not seed:
        raise SystemExit("redepth: the pin must name its seed candidate (\"seed\": the candidate whose staged building "
                         "prefabs every apply starts from, so a re-run never compounds)")
    sd = SC.DATA / "candidates" / seed
    seed_stage = sd / "unity_project" / S.ASSET_ROOT
    seed_rows = json.loads((seed_stage / "rows.json").read_text(encoding="utf-8"))
    seed_rep = json.loads((sd / "work" / "stage_report.json").read_text(encoding="utf-8"))
    sc = S.Scene()
    rd = T.rect_depth(sc.cam)
    rp = S.WORK / "stage_report.json"
    rep = json.loads(rp.read_text(encoding="utf-8"))
    rows = json.loads(S.ROWS.read_text(encoding="utf-8"))
    if not dry:
        # every building prefab (bins, textures, rows, report row) back to the seed's before the contact_v1 pass
        for lid in SC.reachable_layers():
            pk = S.PREFIX + lid
            if pk not in seed_rows or lid not in seed_rep["buildings"]:
                raise SystemExit(f"redepth: seed {seed} has no staged {pk}")
            shutil.rmtree(S.STAGE / pk, ignore_errors=True)
            shutil.copytree(seed_stage / pk, S.STAGE / pk)
            rows[pk] = seed_rows[pk]
            rep["buildings"][lid] = seed_rep["buildings"][lid]
        sw = sd / "work" / "closing_walls.npz"
        if sw.is_file():
            shutil.copy2(sw, S.WORK / "closing_walls.npz")
    lays = SC.layers()
    rrule = SEAMS.residual_rule(BL.building_depth_pin())
    solids: dict[str, list[str]] = {}
    out = {}
    for lid in SC.reachable_layers():
        pk = S.PREFIX + lid
        rr = rep["buildings"].get(lid)
        if rr is None or pk not in rows:
            raise SystemExit(f"redepth: {lid} is reachable but not staged / reported")
        L = lays[lid]
        meshy = is_meshy(rr)
        bins = rows[pk]["bins"]
        roles = {b["name"]: piece_role(lid, b["name"], meshy) for b in bins}
        r = {"meshy": meshy}
        if not meshy:
            solids.setdefault(rr.get("method", "solid"), []).append(lid)
            ld = BL.layer_depth(lid, L, rd, mode="contact_v1")
            leg = BL.layer_depth(lid, L, rd, mode="legacy")
            at_n, at_o = z_at(L, ld), z_at(L, leg)
            for b in bins:
                if roles[b["name"]] != "fx":
                    continue
                path = S.STAGE / pk / f"{b['name']}.bytes"
                v, n, uv, subs = S.read_bin(path)
                if b.get("pos") is not None:
                    # a posed card is rigid about its holder: one ratio, at its pivot
                    px, py, _ = T.project(sc.cam, to_world(sc, np.asarray(b["pos"], np.float64)[None, :]))
                    k = at_n(px, py) / np.maximum(at_o(px, py), 1e-6)
                    if not dry:
                        scale_bin_about_camera(S, path, b, float(k[0]))
                else:
                    px, py, zc = T.project(sc.cam, to_world(sc, v))
                    k = at_n(px, py) / np.maximum(at_o(px, py), 1e-6)
                    if not dry:
                        S.write_bin(path, np.asarray(v, np.float64) * k[:, None], n, uv, subs)
                r.setdefault("fx", {})[b["name"]] = [round(float(np.median(k)), 4), round(float(k.min()), 4),
                                                     round(float(k.max()), 4)]
            for g in rows[pk].get("particles", []):
                w = to_world(sc, np.asarray(g["pos"], np.float64)[None, :])
                px, py, _ = T.project(sc.cam, w)
                k = float(at_n(px, py)[0] / max(at_o(px, py)[0], 1e-6))
                g["pos"] = [float(x) * k for x in g["pos"]]
                g["scale"] = float(g["scale"]) * k
                r.setdefault("particles", {})[g["name"]] = round(k, 4)
        else:
            mv = [S.read_bin(S.STAGE / pk / f"{b['name']}.bytes")[0] for b in bins if roles[b["name"]] == "meshy"]
            if not mv:
                raise SystemExit(f"redepth: {lid} is a Meshy layer without a Meshy piece")
            row_m, col_m, z_m, nb = meshy_base(sc, L, mv)
            ld = BL.layer_depth(lid, L, rd, mode="contact_v1", contact_px=(row_m, col_m))
            z_c = float(ld["audit"]["zContactM"])
            f = z_c / z_m
            at_n = z_at(L, ld)
            r.update({"meshyBase": {"row": round(row_m, 1), "col": round(col_m, 1), "zM": round(z_m, 2), "verts": nb},
                      "zContactM": round(z_c, 2), "meshyScale": round(f, 4)})
            # body_v1 (town_full3d_building_seams): the residual takes the scaled Meshy body's own depth, one depth
            # model per building; contact_v1's disparity field left it off the body and the seam opened on a pan
            if rrule in SEAMS.BODY_RULE_PARAMS:
                bp = SEAMS.BODY_RULE_PARAMS[rrule]
                Pm, Fm, o = [], [], 0
                for b in bins:
                    if roles[b["name"]] == "meshy" and b.get("pos") is None:
                        v_, _, _, s_ = S.read_bin(S.STAGE / pk / f"{b['name']}.bytes")
                        Pm.append(to_world(sc, np.asarray(v_, np.float64) * f))
                        Fm.append(np.concatenate(s_).reshape(-1, 3).astype(np.int64) + o)
                        o += len(v_)
                if rrule == "body_v1":
                    zb = SEAMS.body_front_native(sc.cam, L, ld["mask"].shape, np.concatenate(Pm), np.concatenate(Fm))
                    ld_r, r["residualDepth"] = SEAMS.body_anchor(ld, zb)
                    at_r = z_at(L, ld_r)
                else:
                    at_r, rd_ = SEAMS.residual_field(sc.cam, L, ld, np.concatenate(Pm), np.concatenate(Fm),
                                                     bp["sub"], bp["snapPx"], bp["snapSup"])
                    r["residualDepth"] = {**rd_, "rule": rrule, **bp}
                cut = SEAMS.RESIDUAL_CUT_RATIO
            else:
                r["residualDepth"] = {"rule": "contact_v1", "cutRatio": BL.CUT_RATIO}
                at_r, cut = at_n, BL.CUT_RATIO
            for b in bins:
                role = roles[b["name"]]
                path = S.STAGE / pk / f"{b['name']}.bytes"
                if role in ("meshy", "fx"):
                    if not dry:
                        scale_bin_about_camera(S, path, b, f)
                    continue
                v, n, uv, subs = S.read_bin(path)
                if role == "ray" and SEAMS.BODY_RULE_PARAMS.get(rrule, {}).get("subdiv"):
                    v, n, uv, subs = SEAMS.subdivide(v, n, uv, subs, SEAMS.BODY_RULE_PARAMS[rrule]["subdiv"])
                if role == "ray":
                    vn, src, ns, sunk, _ = ray_redepth(sc, v, subs, at_r, cut)
                    if not dry:
                        S.write_bin(path, vn, np.asarray(n)[src], np.asarray(uv)[src], ns)
                    r.setdefault("ray", {})[b["name"]] = {"verts": int(len(v)), "sunkTris": sunk}
            for g in rows[pk].get("particles", []):
                g["pos"] = [float(x) * f for x in g["pos"]]
                g["scale"] = float(g["scale"]) * f
            r["particles"] = len(rows[pk].get("particles", []))
        r["depthAudit"] = BL.depth_audit(ld)
        out[lid] = r
        print(lid, json.dumps({k: v for k, v in r.items() if k not in ("fx", "particles", "ray")})[:500], flush=True)
    if dry:
        print(json.dumps({"dry": True, "solids": solids}))
        return 0
    S.ROWS.write_text(json.dumps(rows, indent=1), encoding="utf-8")
    # solid / relief layers: the building stage itself on the contact_v1 depth
    for method, lids in solids.items():
        BL.stage_buildings(sc, rd, S.PREFIX, lids, method=method)
        for lid, row in sc.report["buildings"].items():
            rep["buildings"][lid] = {**row, "contactDepth": {k: v for k, v in out[lid].items() if k != "depthAudit"}}
        sc.report["buildings"] = {}
    for lid, r in out.items():
        if r["meshy"]:
            rep["buildings"][lid]["contactDepth"] = {k: v for k, v in r.items() if k != "depthAudit"}
            rep["buildings"][lid]["depthAudit"] = r["depthAudit"]
    rep["buildingDepth"] = {"mode": "contact_v1", "pin": BL.building_depth_pin(),
                            "tool": "town_full3d_building_redepth.py apply",
                            "proofTier": "generated artifact (offline restage); editor render pending"}
    rp.write_text(json.dumps(rep, indent=1, default=lambda o: o.tolist() if hasattr(o, "tolist") else str(o)),
                  encoding="utf-8")
    S.save_rows(sc)
    # rest occlusion in HoMM3 draw order (order_pass): whole layers scaled about the camera, bins + particle groups
    rows = json.loads(S.ROWS.read_text(encoding="utf-8"))
    reach = set(SC.reachable_layers())
    by_state = {k: [l for l in v if l in reach] for k, v in S.STATES.items()}
    op = order_pass(sc, S, rows, by_state)
    for lid, k in op["scale"].items():
        if k >= 1.0:
            continue
        pk = S.PREFIX + lid
        for b in rows[pk]["bins"]:
            scale_bin_about_camera(S, S.STAGE / pk / f"{b['name']}.bytes", b, k)
        for g in rows[pk].get("particles", []):
            g["pos"] = [float(x) * k for x in g["pos"]]
            g["scale"] = float(g["scale"]) * k
    S.ROWS.write_text(json.dumps(rows, indent=1), encoding="utf-8")
    posed_ride_check(S, rows, json.loads((seed_stage / "rows.json").read_text(encoding="utf-8")), seed_stage, out)
    for lid, g in ground_rest(sc, S, rows, by_state, op["scale"], {l for l, r in out.items() if r["meshy"]},
                              body_keeps=rrule == "body_v2").items():
        op["layers"][lid].update(g)
    order_residual(sc, S, rows, by_state, op["layers"])
    bad = {l: r for l, r in op["layers"].items()
           if any(v > ORDER_RESIDUAL_MAX for kk, v in r.items() if kk.startswith("residual_"))}
    rep = json.loads(rp.read_text(encoding="utf-8"))
    rep["buildingDepth"]["restOrder"] = {"layers": op["layers"], "q": order_options()["q"],
                                         "artSameDE": order_options()["artSameDE"],
                                         "layerShare": order_options()["layerShare"], "margin": ORDER_MARGIN,
                                         "residualMax": ORDER_RESIDUAL_MAX, "failing": sorted(bad)}
    for lid, r in op["layers"].items():
        if lid in rep["buildings"]:
            rep["buildings"][lid].setdefault("contactDepth", {})["orderScale"] = r["scale"]
    rp.write_text(json.dumps(rep, indent=1, default=lambda o: o.tolist() if hasattr(o, "tolist") else str(o)),
                  encoding="utf-8")
    print(json.dumps({"restOrder": {l: r for l, r in op["layers"].items() if r["scale"] < 1.0}}), flush=True)
    if bad:
        raise SystemExit(f"redepth order: layers still drawn behind something at their own HoMM3 px: {bad}")
    wf = S.WORK / "closing_walls.npz"
    edges = dict(np.load(wf)) if wf.is_file() else {}
    edges.update(sc.wall_edges)
    np.savez(wf, **edges)
    # every other block of the candidate's own catalog (the props block from town_t2_props stage, ...) is carried
    S.write_catalog(sc, carry="previous")
    S.load_staged_preview(sc)
    print(S.preview(sc, S.WORK / "preview"))
    st = S.see_through_report(sc)
    (S.WORK / "see_through.json").write_text(json.dumps(st, indent=1), encoding="utf-8")
    rep = json.loads(rp.read_text(encoding="utf-8"))
    rep["seeThrough"] = {k: st[k] for k in ("metric", "totalPx", "mode", "baseline", "worse")}
    rp.write_text(json.dumps(rep, indent=1), encoding="utf-8")
    print(json.dumps({"seeThrough": rep["seeThrough"]}))
    S.cull_gate_or_exit(st)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["apply", "dry"])
    a = ap.parse_args()
    return apply(dry=a.cmd == "dry")


if __name__ == "__main__":
    raise SystemExit(main())
