#!/usr/bin/env python3
"""Painted-front bake of a fitted Meshy T2 building for the full-3D town lanes (faction-neutral, the one bake).

The Rampart lane's bake (rampart_t2_buildings.stage_split), coordinator rule 2026-09-29. It follows the lane's
current faction: set TOWN_FULL3D_FACTION before importing stronghold_full3d_*. Callers:
  screen-space method (painted_front / painted_split): t2_fortress/fortress_t2_buildings.py, factory_t2_stage.py,
    cove_t2_stage.py, stronghold_full3d_meshy.py, rampart_t2_buildings.py (Rampart, Dungeon), inferno_t2_integrate.py,
    town_full3d_t2_meshy.py (Necropolis, Bulwark);
  rest-geometry method (rest_geometry_split): castle_t2_buildings.py, tower_t2_stage.py.
2026-09-30: this module absorbed t2_painted_front.py (Cove / Stronghold), then the four remaining copies
(rampart_t2_buildings.stage_split, inferno_t2_integrate.stage_layer, town_full3d_t2_meshy.painted_front,
t2_rest_geometry.stage_painted_layer). Restaging one sample layer of each of the eleven factions gives byte-identical
staged files before and after (t2_bake_restage_check.py; artifacts/town_t2_bake_consolidation/). Where a lane's bake
differs by design it is a named keyword parameter below, with the lane's value at its call site; no lane's output moved.

1. subdivide_screen(cam, P, n, uv, f, max_px=SUBDIV_PX, rounds=6, seen=None, seen_super=SUPER, clip=CLIP_NEAR)
   Faces the rest camera draws are midpoint-split until no projected edge is longer than max_px, so the painted /
   Meshy split follows occlusion edges instead of whole Meshy faces. Lane values: max_px 4 (default), 8 (Rampart /
   Dungeon), 10 (Castle / Tower, rounds 8, seen = town_full3d_houses.rest_buffers at tex_k); seen_super 1
   (Necropolis / Bulwark test "drawn" at frame px); clip CLIP_DOME (Inferno's z-buffer near / far planes).

2. painted_front(sc, lid, L, mask, P, n, f, uv, tex_lin, **by-design parameters) -> {"front", "meshy", "sil", "rep"}
   A face is "front" when it is inside the painted rect and passes either visibility test:
   - it owns at least VISIBLE_MIN of its own rest px in the SUPER z-buffer; or
   - its centroid or any of its corners sits at the rest surface (VIS_TOL).
   Front faces are textured by the sprite at their rest screen position (uv = rest px in a crop at SUPER x the
   frame); outside the sprite mask they take the sprite's nearest inside px (sprite_fill), never Meshy colour; they are
   de-lit per px by the Hex/Lit irradiance of the smooth view normal (vertex -> rest camera) and ship with that normal,
   so the rest frame returns the painting. Every other face keeps the Meshy texture in its own UV layout with a
   per-channel gain matched (linear medians, GAIN_CLAMP) to the de-lit painting on the front faces. Both pieces are
   two-sided (T2 shells are open; the game culls back faces). "front" / "meshy" are add_bin arguments
   (P, n, uv, tris, linear albedo); "sil" is the body's rest silhouette at frame px (for a residual / skirt).
   The by-design parameters (default = the Fortress / Factory / Cove / Stronghold value; lane values):
   - mask: the sprite px that count as "inside" for sprite_fill (native px). stronghold_full3d_buildings.native_mask
     (Rampart, Dungeon, Inferno); the plate's opaque non-shadow alpha (Necropolis, Bulwark); the lane's own elsewhere.
   - zbuf: a (z, face id) rest buffer the caller already rendered for these P / f (Rampart's lean_normals needs it
     first); None renders it here.
   - clip: z-buffer near / far planes; CLIP_DOME for Inferno (its id buffer was drawn with the dome's planes).
   - sampler: "cv2" bilinear sprite lookup (cv2.remap, edge-replicated) or "scipy" (map_coordinates order 1, mode
     nearest; Necropolis / Bulwark). The two differ in the last bits (cv2 quantises the weights).
   - min_front_tris: fewer front faces than this is a failed fit (SystemExit). 1; 50 for Necropolis / Bulwark.
   - gain_guard: when the Meshy gain is measured at all: ("faces", 50) = more than 50 front faces own >= 4 painted
     px; ("px", 200) = more than 200 painted px (Rampart, Dungeon, Inferno, Castle, Tower). Else the gain is 1.
   - gain_dtype: np.float64, or np.float32 (Rampart, Dungeon, Inferno, Castle, Tower; the remainder texture is then
     the float32 product, which rounds differently from the float64 one).
   - meshy_albedo: the remainder's texture supplied by the caller, used as is (no gain; Necropolis / Bulwark bake
     their own colour-matched atlas with sun-bent normals). tex_lin is then unused.
   A body with fewer than min_front_tris front faces is a failed fit: SystemExit.

   painted_split(...) is painted_front plus the two add_bin calls under the caller's bin names (preview, front_max,
   meshy_max: the add_bin preview flag and texture caps).

3. rest_geometry_split(sc, lid, g, f, seed_bin, to_frame, ...) -- the Castle / Tower method, a different bake by
   design (not a parameter of painted_front: it differs in every step): rest-visible triangles (any rest px, or a
   depth-consistent sample: rest_visible) subdivided to subdiv_px and cut exactly at the painted rect
   (clip_to_painting); the painting WITH its background at tex_k, projected per texel over the whole mesh crop;
   de-lit by the seed relief's painting-derived normals with a floor relative to the median irradiance
   (light_floor x median); SL.back_fill outside the sprite; the rest Meshy (gain as above, guard ("px", 200),
   float32); plus Mesh_BodyRest from the seed where the sprite is left uncovered (seed_residual).

Also: outward (wind faces to their vertex normals), drawn_side, facing_rest (the seed-residual grazing filter),
two_sided, zbuffer, sprite_fill, sample, meshy_gain, remainder, seed_residual, tex_to_lin, vertex_normals.
uv is the trimesh / Unity convention (v up); tex_lin is linear float.
Proof tier: generated artifact.
"""
from __future__ import annotations

import math

import cv2
import numpy as np
from PIL import Image

import stronghold_full3d_common as SC
import stronghold_full3d_ground as G
import stronghold_full3d_terrain as T

W, H, TW, TH = SC.W, SC.H, SC.TW, SC.TH
SUPER = 2              # z-buffer / sprite sampling resolution, x the 1920x1080 frame
SUBDIV_PX = 4.0        # rest px: longer projected edges of drawn faces are split
VISIBLE_MIN = 0.6      # share of its projected SUPER px a face must own
VIS_TOL = 0.005        # relative camera-z slack of the centroid / corner test
LIGHT_FLOOR = 0.03     # de-light divisor floor (linear irradiance)
GAIN_CLAMP = (0.5, 2.0)
GAIN_GUARD = ("faces", 50)
RESIDUAL_MIN_FACING = 0.35  # seed residual: |cos| of a kept triangle's normal against its rest view ray
CLIP_NEAR = (1.0, 5000.0)   # z-buffer near / far planes
CLIP_DOME = "dome"          # (2.0, dome radius x 1.2): town_full3d_houses.rest_buffers' planes (Inferno)


def tex_to_lin(tex: np.ndarray) -> np.ndarray:
    """A Meshy base-colour texture (uint8 sRGB) as linear float32."""
    return G.SC_srgb_to_lin(np.asarray(tex).astype(np.float32) / 255)


def _planes(clip):
    return (2.0, T.DOME_R * 1.2) if clip == CLIP_DOME else clip


def zbuffer(cam: dict, P: np.ndarray, f: np.ndarray, clip=CLIP_NEAR, sup: int = SUPER):
    """Camera z of the nearest surface per px at sup x the frame (inf where empty) and the face drawn there (-1 where
    empty). Rendered with moderngl, no culling."""
    import moderngl
    import stronghold_full3d_preview as PV
    near, far = _planes(clip)
    w, h = W * sup, H * sup
    ctx = moderngl.create_standalone_context()
    try:
        prog = ctx.program(vertex_shader="""
#version 330
uniform mat4 mvp; uniform vec3 cpos; uniform vec3 cfwd;
in vec3 in_pos; out float zc;
void main(){ gl_Position = mvp * vec4(in_pos, 1.0); zc = dot(in_pos - cpos, cfwd); }""",
                           fragment_shader="""
#version 330
in float zc; out vec4 o; void main(){ o = vec4(zc, float(gl_PrimitiveID), 0, 1); }""")
        fbo = ctx.framebuffer(color_attachments=[ctx.texture((w, h), 4, dtype="f4")],
                              depth_attachment=ctx.depth_texture((w, h)))
        vao = ctx.vertex_array(prog, [(ctx.buffer(np.asarray(P, np.float32).tobytes()), "3f", "in_pos")],
                               ctx.buffer(np.asarray(f, np.int32).tobytes()))
        mvp = PV.perspective(cam["fov"], W / H, near, far) @ PV.view(cam["pos"], cam["fwd"], cam["up"], cam["right"])
        fbo.use()
        ctx.clear(1e9, 0, 0, 0)
        ctx.enable(moderngl.DEPTH_TEST)
        prog["mvp"].write(mvp.T.astype(np.float32).tobytes())
        prog["cpos"].value = tuple(float(x) for x in cam["pos"])
        prog["cfwd"].value = tuple(float(x) for x in cam["fwd"])
        vao.render()
        buf = np.frombuffer(fbo.color_attachments[0].read(), np.float32).reshape(h, w, 4)[::-1]
        z = buf[..., 0].copy()
        fid = np.round(buf[..., 1]).astype(np.int64)
    finally:
        ctx.release()
    empty = z > 1e8
    z[empty] = np.inf
    fid[empty] = -1
    return z, fid


def drawn_side(cam: dict, P, f) -> np.ndarray:
    """+1 where the rest camera sees a face's own winding, -1 where it sees the reversed copy (two_sided), per face.
    The drawn copy, not the interpolated vertex normal, decides which normal the game shades a rest px with."""
    gn = np.cross(P[f[:, 1]] - P[f[:, 0]], P[f[:, 2]] - P[f[:, 0]])
    return np.where((gn * (cam["pos"] - P[f].mean(1))).sum(1) < 0, -1.0, 1.0)


def subdivide_screen(cam: dict, P, n, uv, f, max_px=SUBDIV_PX, rounds=6, seen=None, seen_super: int = SUPER,
                     clip=CLIP_NEAR):
    """Midpoint-split every face the rest camera draws whose longest projected edge exceeds max_px (n, uv
    interpolated; re-rasterised each round). seen(P, n, f) -> per-face bool replaces the drawn test (default: any
    px of the zbuffer at seen_super x the frame). Returns P, n, uv, f, report."""
    import trimesh
    P, n, uv, f = np.asarray(P, np.float64), np.asarray(n, np.float64), np.asarray(uv, np.float64), np.asarray(f)
    before = len(f)
    for _ in range(rounds):
        px, py, _z = T.project(cam, P)
        q = np.stack([px, py], 1)[f]
        e = np.stack([np.linalg.norm(q[:, 1] - q[:, 0], axis=1), np.linalg.norm(q[:, 2] - q[:, 1], axis=1),
                      np.linalg.norm(q[:, 0] - q[:, 2], axis=1)], 1).max(1)
        if seen is None:
            _zb, idb = zbuffer(cam, P, f, clip, seen_super)
            drawn = np.bincount(idb[idb >= 0], minlength=len(f)) > 0
        else:
            drawn = seen(P, n, f)
        big = np.nonzero((e > max_px) & drawn)[0]
        if not len(big):
            break
        attrs = np.concatenate([n, uv], 1)
        P, f, va = trimesh.remesh.subdivide(P, f, face_index=big, vertex_attributes={"a": attrs})
        n, uv = va["a"][:, :3], va["a"][:, 3:5]
    n /= np.linalg.norm(n, axis=1, keepdims=True) + 1e-12
    return P, n, uv, np.asarray(f), {"maxPx": max_px, "trisBefore": int(before), "trisAfter": int(len(f))}


def sprite_fill(L: dict, k: float, mask: np.ndarray) -> np.ndarray:
    """The sprite's sRGB colour at k x frame scale (0-1). Every px outside the mask (native px) is replaced by its
    nearest inside px: overshoot seen at rest carries the building's own colour pushed outward, never Meshy colour."""
    from scipy.ndimage import distance_transform_edt
    spr = SC.albedo_sprite(L)
    sw, sh = round(spr.width * SC.SCALE * k), round(spr.height * SC.SCALE * k)
    big = np.asarray(spr.resize((sw, sh), Image.LANCZOS)).astype(np.float32)[..., :3] / 255
    mk = cv2.resize(mask.astype(np.float32), (sw, sh), interpolation=cv2.INTER_LINEAR)
    inside = cv2.erode((mk > 0.5).astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool)
    if not inside.any():
        raise SystemExit(f"{L.get('id', '?')}: empty sprite mask")
    _, (iy, ix) = distance_transform_edt(~inside, return_indices=True)
    return big[iy, ix]


def outward(P, n, f):
    """Wind every face to its vertex normals' side (the lane's outward convention)."""
    gn = np.cross(P[f[:, 1]] - P[f[:, 0]], P[f[:, 2]] - P[f[:, 0]])
    flip = (gn * n[f].mean(1)).sum(1) < 0
    out = f.copy()
    out[flip] = out[flip][:, [0, 2, 1]]
    return out


def facing_rest(cam: dict, P, f, min_cos: float = RESIDUAL_MIN_FACING) -> np.ndarray:
    """Per-face bool: the face is seen at rest at |cos| >= min_cos. The seed residual is a depth relief; its grazing
    faces are the depth-slab sides that sweep into long streaks and black slabs off the rest pose (cv_t2 review),
    while covering almost no rest pixel."""
    a, b, c = P[f[:, 0]], P[f[:, 1]], P[f[:, 2]]
    nf = np.cross(b - a, c - a)
    v = (a + b + c) / 3 - np.asarray(cam["pos"], np.float64)
    cos = np.abs((nf * v).sum(1)) / (np.linalg.norm(nf, axis=1) * np.linalg.norm(v, axis=1) + 1e-12)
    return cos >= min_cos


def two_sided(P, n, uv, f):
    """Every triangle plus a reversed copy with negated normals: the game culls back faces and T2 meshes are open."""
    k = len(P)
    return (np.concatenate([P, P]), np.concatenate([n, -n]), np.concatenate([uv, uv]),
            np.concatenate([f, f[:, ::-1] + k]).astype(np.int32))


def remainder(P, n, uv, f, keep):
    """The faces keep as their own compact, two-sided piece (P, n, uv, tris)."""
    used = np.unique(f[keep])
    remap = np.full(len(P), -1)
    remap[used] = np.arange(len(used))
    return two_sided(P[used], n[used], uv[used], remap[f[keep]])


def sample(img, x, y, how: str = "cv2"):
    """Bilinear lookup of (h, w, c) img at px coords (texel centres at +0.5), edge-replicated. how: "cv2"
    (cv2.remap, quantised weights) or "scipy" (map_coordinates order 1)."""
    if how == "scipy":
        from scipy.ndimage import map_coordinates
        return np.stack([map_coordinates(img[..., c], [y - 0.5, x - 0.5], order=1, mode="nearest")
                         for c in range(img.shape[2])], -1)
    if how != "cv2":
        raise ValueError(how)
    n = len(x)
    k = 4096
    m = -(-n // k)
    pad = m * k - n
    X = np.concatenate([x - 0.5, np.full(pad, -10.0)]).astype(np.float32).reshape(m, k)
    Y = np.concatenate([y - 0.5, np.full(pad, -10.0)]).astype(np.float32).reshape(m, k)
    return np.stack([cv2.remap(np.ascontiguousarray(img[..., c]), X, Y, cv2.INTER_LINEAR,
                               borderMode=cv2.BORDER_REPLICATE).ravel()[:n] for c in range(img.shape[2])], 1)


def meshy_gain(tid, vals, nF: int, uv, f, tex_lin, guard=GAIN_GUARD, clamp=GAIN_CLAMP, dtype=np.float64):
    """Per-channel gain of the Meshy texture onto the de-lit painting: the median over faces owning >= 4 painted px
    (tid: the face of each painted px, vals: its linear albedo) of the painted mean, over the median Meshy texel at
    those faces' uv centroids, clamped. guard ("faces", n) / ("px", n): the gain is 1 unless more than n such faces /
    painted px exist."""
    kind, n_min = guard
    cnt = np.bincount(tid, minlength=nF).astype(np.float64)
    ok = cnt >= 4
    if {"faces": int(ok.sum()), "px": len(tid)}[kind] <= n_min:
        return np.ones(3, np.float32)
    sums = np.stack([np.bincount(tid, weights=vals[:, k], minlength=nF) for k in range(3)], 1)
    pm = sums[ok] / cnt[ok, None]
    mh, mw = tex_lin.shape[:2]
    uc = uv[f[ok]].mean(1)
    mx = np.clip((uc[:, 0] % 1.0) * mw, 0, mw - 1).astype(int)
    my = np.clip((1 - uc[:, 1] % 1.0) * mh, 0, mh - 1).astype(int)
    return np.clip(np.median(pm, 0) / np.maximum(np.median(tex_lin[my, mx], 0), 1e-4), *clamp).astype(dtype)


def painted_front(sc, lid: str, L: dict, mask: np.ndarray, P, n, f, uv, tex_lin, *, zbuf=None, clip=CLIP_NEAR,
                  sampler: str = "cv2", min_front_tris: int = 1, gain_guard=GAIN_GUARD, gain_dtype=np.float64,
                  meshy_albedo=None) -> dict:
    """See the module docstring (P, n, f already subdivided)."""
    import conflux_full3d_env as E
    zb, idb = zbuffer(sc.cam, P, f, clip) if zbuf is None else zbuf
    nF = len(f)
    counts = np.bincount(idb[idb >= 0], minlength=nF).astype(np.float64)
    px, py, z = T.project(sc.cam, P)
    q = np.stack([px, py], 1)[f] * SUPER
    area = 0.5 * np.abs((q[:, 1, 0] - q[:, 0, 0]) * (q[:, 2, 1] - q[:, 0, 1])
                        - (q[:, 1, 1] - q[:, 0, 1]) * (q[:, 2, 0] - q[:, 0, 0]))
    inside = (px[f].max(1) < TW) & (py[f].max(1) < TH) & (px[f].min(1) >= 0) & (py[f].min(1) >= 0)
    share = counts / np.maximum(area, 1e-6)
    # Sub-px faces miss px centres at random, so the owned share alone speckles the split; a face whose centroid or
    # any corner is at the rest surface is front as well (Meshy shells come in near-coincident layers)
    cq = q.mean(1)
    cxi = np.clip(cq[:, 0].astype(int), 0, zb.shape[1] - 1)
    cyi = np.clip(cq[:, 1].astype(int), 0, zb.shape[0] - 1)
    vis = z[f].mean(1) <= zb[cyi, cxi] * (1 + VIS_TOL)
    for c in range(3):
        vx = np.clip(q[:, c, 0].astype(int), 0, zb.shape[1] - 1)
        vy = np.clip(q[:, c, 1].astype(int), 0, zb.shape[0] - 1)
        vis |= z[f[:, c]] <= zb[vy, vx] * (1 + VIS_TOL)
    front = ((share >= VISIBLE_MIN) | vis) & inside
    # the side the rest camera sees of each face: the drawn copy carries the view normal
    fside = drawn_side(sc.cam, P, f)
    ys, xs = np.nonzero(idb >= 0)
    t = idb[ys, xs]
    a, b, c = q[t, 0], q[t, 1], q[t, 2]
    pp = np.stack([xs + 0.5, ys + 0.5], 1)
    v0, v1, v2 = b - a, c - a, pp - a
    d00 = (v0 * v0).sum(1); d01 = (v0 * v1).sum(1); d11 = (v1 * v1).sum(1)  # noqa: E702
    d20 = (v2 * v0).sum(1); d21 = (v2 * v1).sum(1)  # noqa: E702
    den = d00 * d11 - d01 * d01
    den = np.where(np.abs(den) < 1e-12, 1e-12, den)
    bv = (d11 * d20 - d01 * d21) / den
    bw = (d00 * d21 - d01 * d20) / den
    bary = np.clip(np.stack([1 - bv - bw, bv, bw], 1), 0, 1)
    bary /= bary.sum(1, keepdims=True) + 1e-12
    # the painted front is shaded with the smooth view normal (vertex -> rest camera), not the Meshy normal: the
    # painting already carries its shading, and a de-light through creased normals leaves the crease's jump
    tc = np.asarray(sc.cam["pos"], np.float64) - P
    tc /= np.linalg.norm(tc, axis=1, keepdims=True) + 1e-12
    nrm = (tc[f[t]] * bary[..., None]).sum(1)
    nrm /= np.linalg.norm(nrm, axis=1, keepdims=True) + 1e-12
    fv = front[t]
    rep = {"trisBaked": int(nF), "frontTris": int(front.sum()), "meshyTris": int((~front).sum()),
           "frontPxShare": round(float(fv.mean()), 4) if len(fv) else 0.0, "texelsPerPx": float(SUPER)}
    need = max(int(min_front_tris), 1)
    if int(front.sum()) < need:
        raise SystemExit(f"{lid}: {int(front.sum())} faces of the body are seen at rest, fewer than {need} "
                         f"(fit failed?)")
    fq = q[front].reshape(-1, 2)
    bx0, by0 = max(int(np.floor(fq[:, 0].min())) - 2, 0), max(int(np.floor(fq[:, 1].min())) - 2, 0)
    bx1, by1 = min(int(np.ceil(fq[:, 0].max())) + 3, W * SUPER), min(int(np.ceil(fq[:, 1].max())) + 3, H * SUPER)
    tw_, th_ = bx1 - bx0, by1 - by0
    spr = G.SC_srgb_to_lin(sprite_fill(L, SUPER, mask))
    cy, cx = np.mgrid[by0:by1, bx0:bx1]
    paint = sample(spr, (cx + 0.5 - L["x"] * SC.SCALE * SUPER).ravel(),
                   (cy + 0.5 - L["y"] * SC.SCALE * SUPER).ravel(), sampler).reshape(th_, tw_, 3)
    alb = np.zeros((th_, tw_, 3), np.float32)
    got = np.zeros((th_, tw_), bool)
    sel = fv & (xs >= bx0) & (xs < bx1) & (ys >= by0) & (ys < by1)
    lx, ly = xs[sel] - bx0, ys[sel] - by0
    Lr = E.light(nrm[sel].astype(np.float32), sc.rig, sc.sun)
    raw = paint[ly, lx] / np.maximum(Lr, LIGHT_FLOOR)
    alb[ly, lx] = np.clip(raw, 0, 1)
    got[ly, lx] = True
    from scipy.ndimage import distance_transform_edt
    _, (iy, ix) = distance_transform_edt(~got, return_indices=True)
    alb = alb[iy, ix]
    rep.update({"paintTex": [tw_, th_], "paintedPx": int(sel.sum()),
                "delitClippedShare": round(float((raw > 1).any(-1).mean()), 4) if len(raw) else 0.0})
    if meshy_albedo is None:
        gain = meshy_gain(t[sel], alb[ly, lx], nF, uv, f, tex_lin, gain_guard, GAIN_CLAMP, gain_dtype)
        rep["meshyGainLin"] = np.round(gain, 3).tolist()
        mtex = np.clip(tex_lin * gain, 0, 1).astype(np.float32)
    else:
        mtex = meshy_albedo
    res = {"sil": cv2.resize(np.isfinite(zb).astype(np.uint8), (W, H), interpolation=cv2.INTER_AREA) > 0,
           "front": None, "meshy": None, "rep": rep}
    used = np.unique(f[front])
    remap = np.full(len(P), -1)
    remap[used] = np.arange(len(used))
    fuv = np.stack([(px[used] * SUPER - bx0) / tw_, 1 - (py[used] * SUPER - by0) / th_], 1)
    ff = remap[f[front]].copy()
    back = fside[front] < 0
    ff[back] = ff[back][:, ::-1]
    res["front"] = (*two_sided(P[used], tc[used], fuv, ff), alb)
    if (~front).any():
        res["meshy"] = (*remainder(P, n, uv, f, ~front), mtex)
    return res


def painted_split(sc, lid: str, L: dict, mask: np.ndarray, P, n, f, uv, tex_lin, front_name: str, meshy_name: str,
                  meshy_max: int = 2048, front_max: int = 4096, preview: bool = True, **by_design) -> dict:
    """painted_front (by_design: its keyword parameters), then stage front_name (painted) and meshy_name (Meshy
    remainder) into sc. Returns the report."""
    import stronghold_full3d_scene as S
    res = painted_front(sc, lid, L, mask, P, n, f, uv, tex_lin, **by_design)
    prefab = S.PREFIX + lid
    sc.add_bin(prefab, front_name, *res["front"], max_size=front_max, preview=preview)
    if res["meshy"] is not None:
        sc.add_bin(prefab, meshy_name, *res["meshy"], max_size=meshy_max, preview=preview)
    return res["rep"]


# ------------------------------------------------------------------------------------------------ seed residual
def seed_residual(sc, prefab: str, name: str, resid: np.ndarray, P0, n0, uv0, t0, albedo_png,
                  preview: bool = True) -> int:
    """The seed body's front triangles (cos > 0.05 toward the rest eye) whose rest centroid falls in resid (frame
    px, dilated 3x3), staged as name with the seed's own sRGB texture; returns their count."""
    rx, ry, _ = T.project(sc.cam, P0)
    cx, cy = rx[t0].mean(1), ry[t0].mean(1)
    fn0 = np.cross(P0[t0[:, 1]] - P0[t0[:, 0]], P0[t0[:, 2]] - P0[t0[:, 0]])
    vw = sc.cam["pos"] - P0[t0].mean(1)
    fr = (fn0 * vw).sum(-1) / (np.linalg.norm(fn0, axis=1) * np.linalg.norm(vw, axis=1) + 1e-12) > 0.05
    rdm = cv2.dilate(resid.astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool)
    ok = (cx >= 0) & (cy >= 0) & (cx < W) & (cy < H)
    inr = np.zeros(len(t0), bool)
    inr[ok] = rdm[cy[ok].astype(int), cx[ok].astype(int)]
    sel = fr & inr
    if sel.any():
        used = np.unique(t0[sel])
        remap = np.full(len(P0), -1)
        remap[used] = np.arange(len(used))
        img = np.asarray(Image.open(albedo_png).convert("RGB"))
        sc.add_bin(prefab, name, P0[used], n0[used], uv0[used], remap[t0[sel]], img, srgb=True, preview=preview)
    return int(sel.sum())


# ------------------------------------------------------------------------------------------------ rest geometry
def clip_to_painting(V, F, uv, N, cam) -> tuple:
    """Cut the mesh at the painted rect's frame lines (x = 0, x = TW, y = 0, y = TH at the rest camera). The fit lets
    a frame-cut building (hall and tavern at the left edge, the mage guild levels at the right) continue past the
    cut, but that continuation is geometry the painting never shows, and town_full3d_framing refuses a candidate whose
    buildings leave the visible region at the framed rest (first t2_v1 stage: tbcshal3 / tbcstvrn to x -0.018,
    tbcsmage to 0.919 > HUD 0.90, only their Mesh_BodyM vertices). The seed ends at the same lines. Each line is a
    plane through the camera, so (px - line) * depth is linear in the world point and the edge split is exact."""
    for axis, line, sign in ((0, 0.0, 1.0), (0, float(TW), -1.0), (1, 0.0, 1.0), (1, float(TH), -1.0)):
        px, py, zc = T.project(cam, V)
        d = sign * ((px if axis == 0 else py) - line) * zc          # >= 0 keeps
        ins = d[F] >= 0
        n_in = ins.sum(1)
        keep = [F[n_in == 3]]
        newV, newUV, newN = [V], [uv], [N]
        nV = len(V)

        def cut(a, b):
            nonlocal nV
            t = (d[a] / (d[a] - d[b]))[:, None]
            newV.append(V[a] + t * (V[b] - V[a]))
            newUV.append(uv[a] + t * (uv[b] - uv[a]))
            nn = N[a] + t * (N[b] - N[a])
            newN.append(nn / (np.linalg.norm(nn, axis=1, keepdims=True) + 1e-12))
            idx = np.arange(nV, nV + len(a))
            nV += len(a)
            return idx
        for want in (1, 2):
            sel = F[n_in == want]
            if not len(sel):
                continue
            si = ins[n_in == want]
            # rotate each triangle (keeping its winding) so the odd vertex is first
            odd = np.argmax(si if want == 1 else ~si, axis=1)
            r = np.stack([sel[np.arange(len(sel)), (odd + j) % 3] for j in range(3)], 1)
            a, b, cc = r[:, 0], r[:, 1], r[:, 2]
            ab, ac = cut(a, b), cut(a, cc)
            if want == 1:
                keep.append(np.stack([a, ab, ac], 1))
            else:
                keep.append(np.stack([ab, b, cc], 1))
                keep.append(np.stack([ab, cc, ac], 1))
        V, uv, N = np.concatenate(newV), np.concatenate(newUV), np.concatenate(newN)
        F = np.concatenate(keep).astype(F.dtype)
    used = np.unique(F)
    remap = np.full(len(V), -1, np.int64)
    remap[used] = np.arange(len(used))
    return V[used], remap[F].astype(F.dtype), uv[used], N[used]


def rest_visible(cam, V, F, own, k: int, eps_rel: float = 2e-3, eps_abs: float = 0.02) -> np.ndarray:
    """Triangles the rest camera sees, by depth consistency rather than by pixel hits. T2 smart-topology meshes are
    mostly slivers (hall after subdivision: median 0.27 px^2 for a 2.7 px long edge), which fall between the id
    buffer's sample points: counting hits at 2x left 40% of the 1x rest frame to Meshy texels. A triangle is visible
    when any of four sample points (centroid, vertices pulled 20% inward) lies on the surface the id buffer shows at
    its pixel: on the owner's plane within eps (the owner is itself, a coplanar neighbour, or no triangle at all at a
    silhouette), never behind it."""
    c = np.asarray(cam["pos"], np.float64)
    h, w = own.shape
    fn = np.cross(V[F[:, 1]] - V[F[:, 0]], V[F[:, 2]] - V[F[:, 0]])
    cen = V[F].mean(1)
    vis = np.zeros(len(F), bool)
    for Q in [cen] + [0.8 * V[F[:, i]] + 0.2 * cen for i in range(3)]:
        sx, sy, _ = T.project(cam, Q)
        ix, iy = np.floor(sx * k).astype(np.int64), np.floor(sy * k).astype(np.int64)
        inb = (ix >= 0) & (iy >= 0) & (ix < w) & (iy < h)
        o = np.full(len(F), -1, np.int64)
        o[inb] = own[iy[inb], ix[inb]]
        d = Q - c
        dist = np.linalg.norm(d, axis=1)
        dr = d / dist[:, None]
        oo = np.clip(o, 0, len(F) - 1)
        den = (fn[oo] * dr).sum(-1)
        t = (fn[oo] * (V[F[oo, 0]] - c)).sum(-1) / np.where(np.abs(den) < 1e-12, 1e-12, den)
        on = np.abs(den) > 1e-12
        vis |= inb & ((o < 0) | (o == np.arange(len(F))) | (on & (dist <= t + eps_abs + eps_rel * t)))
    return vis


def vertex_normals(V, F):
    fn = np.cross(V[F[:, 1]] - V[F[:, 0]], V[F[:, 2]] - V[F[:, 0]])
    vn = np.zeros_like(V)
    for k in range(3):
        np.add.at(vn, F[:, k], fn)
    fl = np.linalg.norm(fn, axis=1, keepdims=True)
    vn /= np.linalg.norm(vn, axis=1, keepdims=True) + 1e-12
    return vn, fn / (fl + 1e-12)


def rest_geometry_split(sc, lid: str, g: dict, f: dict, seed_bin, to_frame, *, tex_k: int = 2,
                        subdiv_px: float = 10.0, subdiv_rounds: int = 8, light_floor: float = 0.35,
                        gain_clamp=GAIN_CLAMP, gain_guard=("px", 200), gain_dtype=np.float32,
                        meshy_tex_max: int = 2048, resid_min_px: int = 20) -> dict:
    """The Castle / Tower bake (module docstring 3; castle_t2_buildings / tower_t2_stage module docstrings): replace
    the layer's body by up to three lit bins: Mesh_Body_<l> (rest-visible triangles, painting projected, de-lit by the
    seed's painting-derived normals), Mesh_BodyM_<l> (the rest, Meshy texture gain-matched), Mesh_BodyRest_<l> (the
    seed's front triangles over sprite px the mesh leaves uncovered). g: the placed model (V, F, uv, N, tex) in the
    painting world; f: its fit.json; seed_bin(lid, sc) -> (P, n, uv, tris, albedo path); to_frame(lid, native mask)
    -> frame mask. Was t2_rest_geometry.stage_painted_layer (moved 2026-09-30, staged bytes unchanged)."""
    import conflux_full3d_env as E
    import stronghold_full3d_scene as S
    import stronghold_full3d_solids as SL
    import town_full3d_houses as HS
    k = tex_k

    def seen_fn(V_, N_, F_):
        i_, _ = HS.rest_buffers(sc, [(V_, N_, F_, 0)], W * k, H * k)
        o_ = np.round(i_).astype(np.int64)
        return np.bincount(o_[o_ >= 0].ravel(), minlength=len(F_)) > 0

    V, vn, uvm, F, _srep = subdivide_screen(sc.cam, g["V"], g["N"], g["uv"], g["F"], subdiv_px, subdiv_rounds,
                                            seen=seen_fn)
    nclip = len(F)
    V, F, uvm, vn = clip_to_painting(V, F, uvm, vn, sc.cam)
    _, fn = vertex_normals(V, F)
    L = SC.layers()[lid]
    idb, _ = HS.rest_buffers(sc, [(V, vn, F, 0)], W * k, H * k)
    own = np.round(idb).astype(np.int64)
    nT = len(F)
    counts = np.bincount(own[own >= 0].ravel(), minlength=nT)
    px, py, _ = T.project(sc.cam, V)
    tq = np.stack([px, py], 1)[F]
    view = sc.cam["pos"] - V[F].mean(1)
    view /= np.linalg.norm(view, axis=-1, keepdims=True)
    facing = (fn * view).sum(-1)
    inside = (tq[:, :, 0].max(1) < TW) & (tq[:, :, 1].max(1) < TH) & (tq.min((1, 2)) >= 0)
    # painted = visible at rest, whatever the facing: T2 meshes carry open single-sided parts (posts, railings,
    # eaves) whose back faces are what the rest camera sees; leaving them to Meshy broke the rest frame (hall: 12.5%
    # of covered px were back-facing). Grazing faces still take the painting: at rest it is exact.
    # any rest px or a depth-consistent sample (rest_visible): visible triangles are <= subdiv_px after
    # subdivide_screen, so a partly hidden one carries at most a few px of its occluder's paint, whereas a share
    # threshold (counts / area) is noise on slivers and left the painted body speckled with Meshy texels at rest
    front = ((counts > 0) | rest_visible(sc.cam, V, F, own, k)) & inside
    # painted source: the HoMM3 background with this layer's static plate, x1.8 then tex_k
    bg = SC.albedo_background(carve=False).convert("RGBA")
    bg.alpha_composite(SC.albedo_sprite(L), (int(L["x"]), int(L["y"])))
    paint = np.asarray(bg.convert("RGB").resize((TW * k, TH * k), Image.LANCZOS)).astype(np.float32) / 255
    # the sprite's own px (alpha, not the body cut: a painted skirt under the mesh is still this building's paint)
    spr_a = np.zeros((H, W), bool)
    spr_a |= to_frame(lid, np.asarray(SC.sprite(L))[..., 3] > 8)
    spr_k = cv2.resize(spr_a.astype(np.uint8), (W * k, H * k), interpolation=cv2.INTER_NEAREST).astype(bool)
    bx0, by0 = max(int(math.floor(px.min())) - 3, 0), max(int(math.floor(py.min())) - 3, 0)
    bx1, by1 = min(int(math.ceil(px.max())) + 4, TW), min(int(math.ceil(py.max())) + 4, TH)
    sl = (slice(by0 * k, by1 * k), slice(bx0 * k, bx1 * k))
    crop = G.SC_srgb_to_lin(paint[sl])
    idc = own[sl]
    # Painted body shading normals come from the seed's painting-derived surface, not from Meshy's geometry: T2
    # normals disagree with the painting's lighting (open gables, recessed colonnade), and wherever light(n) fell
    # below light_floor the de-light saturated and the rest frame rendered darker than the paint (hall: mean |diff|
    # 13.9 / 255 against the seed at rest). With the seed's field the rest frame is as exact as the seed's.
    P0, n0, _uv0, t0, _alb0 = seed_bin(lid, sc)
    sid, snb = HS.rest_buffers(sc, [(P0, n0, t0, 0)], W * k, H * k)
    have = sid >= 0
    if not have.any():
        raise SystemExit(f"{lid}: the seed body covers no rest px; no painting normals to shade the projection with")
    from scipy import ndimage
    _, (fy, fx) = ndimage.distance_transform_edt(~have, return_indices=True)
    snb = snb[fy, fx]
    fi = np.nonzero(front)[0]
    Fb = F[fi]
    Vb = V[Fb].reshape(-1, 3)
    bxp, byp = px[Fb].ravel(), py[Fb].ravel()
    nseed = snb[np.clip((byp * k).astype(np.int64), 0, H * k - 1), np.clip((bxp * k).astype(np.int64), 0, W * k - 1)]
    nseed = nseed / (np.linalg.norm(nseed, axis=1, keepdims=True) + 1e-12)
    Tb = np.arange(len(Vb)).reshape(-1, 3)
    # the Unity-visible copy of a back-facing triangle is its reversed copy (two_sided negates): pre-negate so the
    # copy the rest camera sees carries the seed normal
    Nb = np.where(np.repeat(facing[fi] < 0, 3)[:, None], -nseed, nseed)
    _, nbv = HS.rest_buffers(sc, [(Vb, nseed, Tb, 0)], W * k, H * k)
    nc = nbv[sl]
    mine_front = (idc >= 0) & front[np.clip(idc, 0, nT - 1)]
    Lr = E.light((nc / (np.linalg.norm(nc, axis=-1, keepdims=True) + 1e-9)).astype(np.float32), sc.rig, sc.sun)
    lm = Lr.mean(-1)
    ref = lm[mine_front] if mine_front.any() else lm.ravel()
    floor = light_floor * float(np.median(ref))
    raw = crop / np.maximum(Lr, floor)
    alb = np.clip(raw, 0, 1).astype(np.float32)
    paint_ok = mine_front & spr_k[sl]
    clipped = float((raw[paint_ok] > 1).any(-1).mean()) if paint_ok.any() else 0.0
    ftile = SL.back_fill(alb, paint_ok, erode_tx=0, blur_tx=0) if paint_ok.any() else alb
    ftile[paint_ok] = alb[paint_ok]
    th_, tw_ = ftile.shape[:2]
    # Meshy texture, gain-matched to the de-lit painting on the projected triangles (linear medians per channel)
    mt = tex_to_lin(g["tex"])
    if max(mt.shape[:2]) > meshy_tex_max:
        mt = cv2.resize(mt, (meshy_tex_max, meshy_tex_max), interpolation=cv2.INTER_AREA)
    yy, xx = np.nonzero(paint_ok)
    gain = meshy_gain(idc[yy, xx], alb[yy, xx], nT, uvm, F, mt, gain_guard, gain_clamp, gain_dtype)
    mtex = np.clip(mt * gain, 0, 1).astype(np.float32)
    prefab = S.PREFIX + lid
    rep = {"meshFrom": f["meshFrom"], "fit": {k_: round(f[k_], 3) for k_ in ("iou", "precision", "recall", "fbeta",
                                                                               "stretchY", "yaw", "worldHeight")},
           "tris": int(nT), "trisBeforeFrameClip": int(nclip), "frontTris": int(front.sum()),
           "meshyTris": int((~front).sum()), "paintedTexels": int(paint_ok.sum()),
           "overshootTexels": int((mine_front & ~spr_k[sl]).sum()), "paintTex": [tw_, th_],
           "meshyTex": [mt.shape[1], mt.shape[0]], "meshyGainLin": np.round(gain, 3).tolist(),
           "delitClippedShare": round(clipped, 4), "texelsPerPx": float(tex_k)}
    if front.any():
        u = (bxp - bx0) * k / tw_
        v = 1 - (byp - by0) * k / th_
        sc.add_bin(prefab, f"Mesh_Body_{lid}", *two_sided(Vb, Nb, np.stack([u, v], 1), Tb), ftile, preview=False)
    if (~front).any():
        sc.add_bin(prefab, f"Mesh_BodyM_{lid}", *remainder(V, vn, uvm, F, ~front), mtex,
                   max_size=meshy_tex_max, preview=False)
    # residual: sprite px (alpha, skirts included) the mesh leaves uncovered at rest -> the seed's front triangles
    import stronghold_full3d_buildings as BL
    tgt = spr_a.copy()
    tgt &= to_frame(lid, BL.native_mask(L))
    cover = cv2.resize((own >= 0).astype(np.uint8), (W, H), interpolation=cv2.INTER_AREA) > 0
    resid = tgt & ~cover
    resid[TH:] = False
    resid[:, TW:] = False
    n_, lab_, st_, _ = cv2.connectedComponentsWithStats(resid.astype(np.uint8), connectivity=8)
    keep = np.zeros(n_, bool)
    keep[1:] = st_[1:, cv2.CC_STAT_AREA] >= resid_min_px
    resid = keep[lab_]
    rep["spritePx"] = int(tgt[:TH, :TW].sum())
    rep["residualPx"] = int(resid.sum())
    rep["residualTris"] = 0
    if resid.sum():
        P0, n0, uv0, t0, albp = seed_bin(lid, sc)
        rep["residualTris"] = seed_residual(sc, prefab, f"Mesh_BodyRest_{lid}", resid, P0, n0, uv0, t0, albp,
                                            preview=False)
    return rep
