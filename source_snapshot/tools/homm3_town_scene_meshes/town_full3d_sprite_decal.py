#!/usr/bin/env python3
"""Full-3D towns: sprite ground decals, the painting a building's HoMM3 sprite lays on the environment.

Why (Castle zs_v7, 2026-10-01, the rest-paint term): in early build states the rest frame shows the environment where
the HoMM3 sprite paints. tbcscas2/3 paint the river at frame x 1356-1440; Mesh_BodyRest covers part of it and the
other 1229 px fall through to the grass terrain. tbcsdw_5 paints a wooden structure at x 683-779 that no building bin
draws, so Back_Terrain shows there. These are coverage gaps of the building seed, byte-identical across zs_v5..zs_v7.
They are not a streak, so the certificate never saw them.

Method (one pass, any town; the recipe's optional "decal" step, town_full3d_recipe.finish, before the repair rounds so
the rounds certify the new faces):
  1. per building layer L, the rest frame of the environment + L alone (TP.zbuffer). The decal px are those the
     environment draws (nearest face) where L's sprite covers the frame (alpha > ALPHA_MIN, inside the painted rect) and
     the environment's rest albedo differs in chromaticity from the HoMM3 painting of L over the bare background by
     more than the rest-paint term's own threshold (town_full3d_recipe.REST_PAINT_CHROMA / MIN_SUM). The deviation is
     opened 3x3 (as the term does) and dilated by DILATE_PX inside the sprite's alpha, so the decal edge is not a
     seam of environment paint.
     A layer's painted smoke / flame whose emitter is staged (the rest-paint term's fx exclusion masks) is not
     inside: the scene draws it as Fx, so it is never laid on the ground.
  2. geometry: one vertex per px centre on the environment surface the rest ray meets (its forward depth z), moved
     toward the camera along its own rest ray to z * (1 - EPS_REL * level). Every rest px keeps its position, so the
     rest frame shows the decal exactly where the sprite paints, and at a pose it moves with the ground under it.
     level is 1 + the highest level of the decals already laid under this one (layers in positions.json z order) that
     a build state shows together with it, so overlapping decals shown together never share a depth. A quad between four px centres is emitted when one of them is a decal px,
     all four are environment px, and their depths stay within DEPTH_JUMP of each other. A quad across a depth step
     would be a streak, so it is skipped and counted (the certificate measures the rest).
  3. albedo: the painting of L over the background times the environment's de-lighting ratio at that px
     (sum(env albedo) / sum(bare background painting), clamped to RATIO_CLAMP and box-smoothed). The chromaticity is
     the sprite's, and Hex/Lit shading under the environment's normals returns the painted brightness.
  2b. layerDepth (opt-in, the recipe's "decal": {"layerDepth": {}}): a decal px whose environment surface lies more
     than BEHIND_REL behind the layer's back (the 98th percentile forward depth of the px the layer draws at rest) is
     not ground under the building but a gap in the
     building seed with the far environment behind it (Cove zs_v1 2026-10-02: the hall's gable px fell through to the
     cliff 185-264 m out while the hall stands at 51-72 m; validate_town_scene3d_contract read Mesh_Decal_tbcvhall as
     a building depth streak, upright span 69.8 m over 15.3 m; a per-px rule, 25 % behind the layer's own surface
     there, left tbcvthgd's cliff px 175-181 m out behind a 141-156 m body). Its vertex goes on the same rest ray at the layer's
     depth instead (the layer's rest z-buffer, push-pull filled over the frame from the px the layer draws), facing
     the camera, so the rest px is unchanged and at a pose it moves with the building. A quad between a card px and a
     ground px crosses the depth step and is skipped like any other.
  4. the bin is Mesh_Decal_<L> in L's prefab (shown only when L is built; town_full3d_building_depth role "ray"), one
     texel per rest px over the decal's bounding box, with texels outside the decal filled by push-pull.

Proof tier: generated artifact (offline raster). Not runtime proof.
"""
from __future__ import annotations

import hashlib

import numpy as np

SCHEMA = "town_full3d_sprite_decal.v1"
PIECE = "Mesh_Decal_"
ALPHA_MIN = 0.5
DILATE_PX = 2
EPS_REL = 0.004
DEPTH_JUMP = 0.05
RATIO_CLAMP = (0.25, 4.0)
BEHIND_REL = 0.05          # layerDepth: environment this far (ratio of forward depth) behind the layer's back
RATIO_SMOOTH_PX = 9
MAX_SIZE = 4096


def fail(msg: str):
    raise SystemExit(f"sprite decal: {msg}")


def frame_layer(SC, S, lid: str):
    """(alpha HxW float 0..1, rgb HxW x3 float: the painting of the layer over the bare background) in frame px."""
    from PIL import Image
    L = SC.layers()[lid]
    bg = SC.background_rgba()
    spr = Image.new("RGBA", bg.size, (0, 0, 0, 0))
    spr.alpha_composite(SC.sprite(L), (int(L["x"]), int(L["y"])))
    a = np.zeros((SC.H, SC.W), np.float32)
    a[:SC.TH, :SC.TW] = np.asarray(spr.split()[3].resize((SC.TW, SC.TH), Image.LANCZOS), np.float32) / 255.0
    return a, np.asarray(S.homm3_reference([lid]), np.float32)


def chroma_dev(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    sa, sb = a.sum(-1), b.sum(-1)
    return np.abs(a / np.maximum(sa, 1e-6)[..., None] - b / np.maximum(sb, 1e-6)[..., None]).max(-1) * 100


def plan(S, SC, T, TP, sc, stage, rows: dict, layers_of: dict, env: tuple, chroma: float, min_sum: float,
         fx_masks: dict | None = None, layer_depth: bool = False) -> dict:
    """{lid: bin dict for Stage.bins + texture + report}; layers_of: the build states ({state: [layers]});
    env = rest_colour(env alone): (rgb, normal, ok, z); fx_masks: {lid: HxW bool frame px} of the layer's painted
    smoke / flame whose emitter is staged (town_full3d_recipe.rest_paint_fx_masks): the scene draws that paint as Fx,
    so it is never laid on the ground as a decal (Factory zs_v2, 2026-10-02: tbfablak / tbfaup_3 plumes)."""
    import cv2
    import town_full3d_ldi as L
    import town_full3d_zero_streak as ZS
    rgb_env, nrm_env, env_ok, z_env = env
    if any(b["name"].startswith(PIECE) for r in rows.values() for b in r["bins"]):
        fail("the candidate already stages Mesh_Decal_ bins (re-seed it)")
    lays = SC.layers()
    bg = np.asarray(S.homm3_reference([]), np.float32)
    rect = np.zeros((SC.H, SC.W), bool)
    rect[:SC.TH, :SC.TW] = True
    ratio = rgb_env.sum(-1) / np.maximum(bg.sum(-1), 1e-6)
    good = env_ok & (bg.sum(-1) > min_sum) & (rgb_env.sum(-1) > min_sum)
    ratio = np.clip(np.where(good, ratio, 1.0), *RATIO_CLAMP).astype(np.float32)
    w = cv2.blur(good.astype(np.float32), (RATIO_SMOOTH_PX,) * 2)
    ratio = np.where(w > 1e-3, cv2.blur(ratio * good, (RATIO_SMOOTH_PX,) * 2) / np.maximum(w, 1e-3), 1.0)
    wp = ZS.world_points(sc.cam, np.where(env_ok, z_env, np.nan))
    layer_ids = sorted({l for ls in layers_of.values() for l in ls})
    shown_with = {l: set() for l in layer_ids}     # layers some build state shows together (upgrades never are)
    for ls in layers_of.values():
        for l in ls:
            shown_with[l] |= set(ls) - {l}
    placed = {}                                     # lid -> (mask, level)
    out, rep = {}, {}
    for lid in sorted(layer_ids, key=lambda l: (lays[l].get("z", 0), l)):
        key = S.PREFIX + lid
        if key not in rows:
            fail(f"build states name {lid}, which the candidate does not stage")
        alpha, ref = frame_layer(SC, S, lid)
        P, UV, F, owner, names, _, fmap = stage.arrays([S.ENV_KEY, key])
        _, fid = TP.zbuffer(sc.cam, P, F, sup=1)
        env_own = np.asarray([n.startswith("environment/") for n in names])
        envpx = (fid >= 0) & env_own[owner[np.maximum(fid, 0)]] & env_ok
        inside = rect & (alpha > ALPHA_MIN)
        fxm = (fx_masks or {}).get(lid)
        fx_px = 0
        if fxm is not None:
            fx_px = int((inside & fxm).sum())
            inside &= ~fxm
        dev = (chroma_dev(rgb_env, ref) > chroma) & (rgb_env.sum(-1) > min_sum) & (ref.sum(-1) > min_sum)
        core = cv2.morphologyEx((inside & envpx & dev).astype(np.uint8), cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
        if not core.any():
            rep[lid] = {"decalPx": 0, "fxExcludedPx": fx_px}
            continue
        k = 2 * DILATE_PX + 1
        mask = cv2.dilate(core, np.ones((k, k), np.uint8)).astype(bool) & inside & envpx
        ys, xs = np.nonzero(mask)
        x0, y0 = max(int(xs.min()) - 1, 0), max(int(ys.min()) - 1, 0)
        x1, y1 = min(int(xs.max()) + 2, SC.W), min(int(ys.max()) + 2, SC.H)
        tw, th = x1 - x0, y1 - y0
        if max(tw, th) > MAX_SIZE:
            fail(f"{lid}: decal box {tw}x{th} exceeds {MAX_SIZE} texels")
        lv = 1 + max([lo for o, (mo, lo) in placed.items() if o in shown_with[lid] and (mo & mask).any()] or [0])
        placed[lid] = (mask, lv)
        zc, lay_card = z_env, np.zeros_like(mask)
        if layer_depth:
            zc, lay_card, n_lay = layer_card_depth(TP, sc, P, F, owner, names, z_env, mask, L)
        # quads between px centres (x, y)..(x+1, y+1) of the box
        m = mask[y0:y1, x0:x1]
        e = envpx[y0:y1, x0:x1]
        z = np.where(e, zc[y0:y1, x0:x1], np.nan)
        q_any = m[:-1, :-1] | m[1:, :-1] | m[:-1, 1:] | m[1:, 1:]
        q_env = e[:-1, :-1] & e[1:, :-1] & e[:-1, 1:] & e[1:, 1:]
        zs = np.stack([z[:-1, :-1], z[1:, :-1], z[:-1, 1:], z[1:, 1:]])
        zs = np.where(np.isnan(zs), 1.0, zs)            # non-environment corners: q_env drops those quads
        jump = zs.max(0) / np.maximum(zs.min(0), 1e-9) - 1
        q_ok = q_any & q_env & (jump <= DEPTH_JUMP)
        skipped = int((q_any & ~q_ok).sum())
        qy, qx = np.nonzero(q_ok)
        if not len(qy):
            rep[lid] = {"decalPx": int(core.sum()), "quads": 0, "quadsSkipped": skipped, "fxExcludedPx": fx_px}
            continue
        used = np.zeros_like(m)
        for dy, dx in ((0, 0), (1, 0), (0, 1), (1, 1)):
            used[qy + dy, qx + dx] = True
        vid = -np.ones(m.shape, np.int64)
        vy, vx = np.nonzero(used)
        vid[vy, vx] = np.arange(len(vy))
        cpos = sc.cam["pos"]
        Wv = wp[y0 + vy, x0 + vx]
        card = np.zeros(len(vy), bool)
        if layer_depth:
            card = lay_card[y0 + vy, x0 + vx]
            Wv[card] = ZS.world_points(sc.cam, np.where(lay_card, zc, np.nan))[y0 + vy[card], x0 + vx[card]]
        Wv = cpos + (Wv - cpos) * (1 - EPS_REL * lv)
        V = sc.local(Wv)
        Nw = nrm_env[y0 + vy, x0 + vx].astype(np.float64)
        if card.any():
            to_cam = cpos - Wv[card]
            Nw[card] = to_cam / np.maximum(np.linalg.norm(to_cam, axis=1, keepdims=True), 1e-12)
        N = sc.local_dir(Nw)
        UVv = np.stack([(vx + 0.5) / tw, 1 - (vy + 0.5) / th], 1)
        a, b, c, d = vid[qy, qx], vid[qy + 1, qx], vid[qy, qx + 1], vid[qy + 1, qx + 1]
        Fq = np.concatenate([np.stack([a, b, c], 1), np.stack([c, b, d], 1)])
        tex = ref[y0:y1, x0:x1] * ratio[y0:y1, x0:x1, None]
        tex = L.push_pull(tex.astype(np.float32), m)
        name = f"{PIECE}{lid}"
        path = S.STAGE / key / f"{name}.bytes"
        out[lid] = {"key": key, "name": name, "path": path, "v": V, "n": N, "uv": UVv, "f": Fq.astype(np.int64),
                    "sid": np.zeros(len(Fq), np.int32), "nsub": 1, "tex": (tw, th), "dirty": True,
                    "albedo": np.clip(tex, 0, 255).astype(np.uint8)}
        rep[lid] = {"decalPx": int(core.sum()), "maskPx": int(m.sum()), "box": [x0, y0, tw, th], "level": lv,
                    "quads": int(len(qy)), "quadsSkipped": skipped, "verts": int(len(V)),
                    "fxExcludedPx": fx_px}
        if layer_depth:
            rep[lid]["layerDepthVerts"] = int(card.sum())
            rep[lid]["layerDrawnPx"] = n_lay
    return {"bins": out, "report": {"schema": SCHEMA, "spec": {"alphaMin": ALPHA_MIN, "dilatePx": DILATE_PX,
                                                               **({"layerDepth": {"behindRel": BEHIND_REL}}
                                                                  if layer_depth else {}),
                                                               "epsRel": EPS_REL, "depthJump": DEPTH_JUMP,
                                                               "chroma": chroma, "minSum": min_sum},
                                    "byLayer": rep, "layers": sorted(out)}}


def layer_card_depth(TP, sc, P, F, owner, names, z_env, mask, L) -> tuple:
    """layerDepth: (forward-depth map with the layer's depth on the mask px whose environment lies more than BEHIND_REL
    behind it, those px, the layer's drawn px count). The layer's depth: its own staged faces (not the environment,
    not decals, not Fx) rasterised alone at rest, push-pull filled from the px they draw (L.push_pull)."""
    own = np.asarray([not n.startswith("environment/") and "/Mesh_" in n and "/Mesh_Decal_" not in n
                      for n in names])
    Fl = F[own[owner]]
    if not len(Fl):
        return z_env, np.zeros_like(mask), 0
    zl, fl = TP.zbuffer(sc.cam, P, Fl, sup=1)
    drawn = (fl >= 0) & np.isfinite(zl)
    if not drawn.any():
        return z_env, np.zeros_like(mask), 0
    zf = L.push_pull(np.where(drawn, zl, 0.0).astype(np.float32), drawn)[..., 0].astype(np.float64)
    back = float(np.percentile(zl[drawn], 98))
    card = mask & np.isfinite(z_env) & (z_env > back * (1 + BEHIND_REL))
    if card.any() and not (np.isfinite(zf[card]).all() and (zf[card] > 0).all()):
        fail("layerDepth: the layer's filled depth is not positive and finite on every card px")
    return np.where(card, zf, z_env), card, int(drawn.sum())


def apply(S, stage, rows: dict, planned: dict) -> list:
    """Append the planned bins to the Stage, save their albedo and add their rows (Stage.write writes the meshes)."""
    from PIL import Image
    added = []
    for lid, b in sorted(planned["bins"].items()):
        img = b.pop("albedo")
        b["path"].parent.mkdir(parents=True, exist_ok=True)
        tp = b["path"].with_name(f"{b['name']}_albedo.png")
        Image.fromarray(img).save(tp)
        stage.bins.append(b)
        rows[b["key"]]["bins"] = sorted(rows[b["key"]]["bins"] + [{
            "name": b["name"], "mesh": f"{S.ASSET_ROOT}/{b['key']}/{b['name']}.bytes",
            "texture": f"{S.ASSET_ROOT}/{b['key']}/{b['name']}_albedo.png", "kind": "lit",
            "maxSize": MAX_SIZE}], key=lambda r: r["name"])
        planned["report"]["byLayer"][lid]["albedoSha256"] = hashlib.sha256(tp.read_bytes()).hexdigest()
        added.append(f"{b['key']}/{b['name']}")
    return added
