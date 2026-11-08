#!/usr/bin/env python3
"""Town full-3D: Kokon (local Qwen-Image 2.1 editor) back-fill on a staged candidate's EXISTING geometry
(docs/homm3_town_kokon_backfill.md). Texture-only: no vertex, uv or triangle is written, so every geometric gate of the
seed (zero-streak certificate, scene3d contract, LDI npz) holds by construction.

    TOWN_FULL3D_CANDIDATE=<c> python town_full3d_kokon_backfill.py --faction cove rebake  --extsrc <dir> [--pieces ...]
    TOWN_FULL3D_CANDIDATE=<c> python town_full3d_kokon_backfill.py --faction cove backfill --plate <png> [--plate ...]

rebake    the environment pieces outside the painted rect from a town_full3d_extsrc.v1 canvas (an outpaint), instead of
          the seed's extension. Each piece is rasterised in its own UV space on the GPU (moderngl: per-texel prefab
          position and normal), each texel's rest-frame px found by projection, and the canvas sampled there and
          de-lit by the lane's own Hex/Lit irradiance (conflux_full3d_env.light, the scene's rig and sun) exactly as
          stronghold_full3d_ground.Baker / stronghold_full3d_periphery.bake_piece do. Frame-affine terrain pieces
          (Mesh_Terrain, Mesh_TerrainNear_*): texels whose px is outside the painted rect take the canvas; every texel
          inside it is copied verbatim from the seed (byte-identical painting at rest). Periphery pieces (Mesh_Outer*):
          texels whose rest ray lands on the canvas outside the 1920x1080 frame take the canvas, feathered in from
          the canvas border (EXT_FEATHER_PX, the periphery's own rule); the rest is the seed's. The LDI back layers'
          texels that show at rest follow their main piece (so the cut cells still draw what the main piece did).
          Why not re-run the lane's bake: a profile with EXT_SKYLINE fits the terrain field (geometry) to the canvas
          skyline, so a new canvas would move the terrain; and the seed's canvas may no longer exist.
backfill  the LDI back layers' guessed texels (Mesh_Back_<piece>: hidden at rest by the main piece, less the
          PROTECT_TEXELS ring around every texel shown at rest - town_full3d_ldi.synth_back_texture's own mask;
          Mesh_Back_<piece>_Far: all hidden) are replaced by "plates": frame-registered images (1920x1080 or k x, the
          rest camera's image plane, frame px) in which an editor revealed what is behind each occluder. Several plates
          are composited in order (later plates win where their alpha / validity mask is set). The plate colour is
          de-lit by the back texel's own normal. quilt_fill's texels stay wherever no plate covers a texel.
          Every texel shown at rest, and the ring, is unchanged; so the rest frame is unchanged at mip 0.

Proof tier: generated artifact / offline render (town bench). GPU: moderngl (the UV raster); the per-texel colour math
is numpy on the rasterised maps (I/O-bound; a few seconds per piece).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import time
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

Image.MAX_IMAGE_PIXELS = None
TERRAIN = ("Mesh_Terrain", "Mesh_TerrainNear_0", "Mesh_TerrainNear_1")
EXT_FEATHER_PX = 60.0          # stronghold_full3d_periphery.EXT_FEATHER_PX (canvas px from its border)


def sha(p: Path) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def srgb_to_lin(x):
    x = np.asarray(x, np.float32)
    return np.where(x <= 0.04045, x / 12.92, ((x + 0.055) / 1.055) ** 2.4).astype(np.float32)


def lin_to_srgb(x):
    x = np.clip(np.asarray(x, np.float32), 0, 1)
    return np.where(x <= 0.0031308, x * 12.92, 1.055 * np.power(x, 1 / 2.4) - 0.055).astype(np.float32)


# ------------------------------------------------------------------------------------------------ GPU uv raster
class UVRaster:
    """moderngl: rasterise triangles in UV space (texel centres) with per-vertex attributes interpolated."""

    VS = """#version 330
in vec2 in_uv; in vec3 in_p; in vec3 in_n;
out vec3 v_p; out vec3 v_n;
void main(){ v_p = in_p; v_n = in_n; gl_Position = vec4(in_uv.x * 2.0 - 1.0, in_uv.y * 2.0 - 1.0, 0.0, 1.0); }"""
    FS = """#version 330
in vec3 v_p; in vec3 v_n;
layout(location=0) out vec4 o_p; layout(location=1) out vec4 o_n;
void main(){ o_p = vec4(v_p, 1.0); o_n = vec4(v_n, 1.0); }"""

    def __init__(self):
        import moderngl
        self.mgl = moderngl
        self.ctx = moderngl.create_standalone_context(require=330)
        self.prog = self.ctx.program(vertex_shader=self.VS, fragment_shader=self.FS)

    def render(self, uv, P, n, tris, w: int, h: int):
        """-> (P map h x w x 3, n map h x w x 3, covered h x w bool); row 0 = texture top (PIL orientation)."""
        with self.ctx:          # another standalone context (town_full3d_ldi.rest_depth) may be current
            return self._render(uv, P, n, tris, w, h)

    def _render(self, uv, P, n, tris, w: int, h: int):
        ctx = self.ctx
        idx = np.asarray(tris, np.int32).ravel()
        vb = np.concatenate([np.asarray(uv, np.float32), np.asarray(P, np.float32), np.asarray(n, np.float32)], 1)
        vbo = ctx.buffer(vb.astype(np.float32).tobytes())
        ibo = ctx.buffer(idx.tobytes())
        vao = ctx.vertex_array(self.prog, [(vbo, "2f 3f 3f", "in_uv", "in_p", "in_n")], ibo)
        out_p, out_n = np.zeros((h, w, 4), np.float32), np.zeros((h, w, 4), np.float32)
        TILE = 4096
        for y0 in range(0, h, TILE):
            for x0 in range(0, w, TILE):
                tw, th = min(TILE, w - x0), min(TILE, h - y0)
                ta, tb = ctx.texture((tw, th), 4, dtype="f4"), ctx.texture((tw, th), 4, dtype="f4")
                fbo = ctx.framebuffer(color_attachments=[ta, tb])
                fbo.use()
                fbo.clear(0, 0, 0, 0)
                # GL rows run bottom-up: texture v=0 is the image bottom; the tile's viewport in full-texture px
                ctx.viewport = (-x0, -(h - y0 - th), w, h)
                vao.render(self.mgl.TRIANGLES)
                for tex, dst in ((ta, out_p), (tb, out_n)):
                    a = np.frombuffer(tex.read(), np.float32).reshape(th, tw, 4)[::-1]
                    dst[y0:y0 + th, x0:x0 + tw] = a
                fbo.release(); ta.release(); tb.release()
        vao.release(); vbo.release(); ibo.release()
        cov = out_p[..., 3] > 0.5
        return out_p[..., :3], out_n[..., :3], cov


# ------------------------------------------------------------------------------------------------ scene context
class Ctx:
    def __init__(self, cand_stage: Path):
        import stronghold_full3d_scene as S
        import stronghold_full3d_common as SC
        import conflux_full3d_env as E
        self.S, self.SC, self.E = S, SC, E
        self.sc = S.Scene()
        self.cam = self.sc.cam
        self.C = self.sc.C
        self.scale = self.sc.scale
        self.rig, self.sun = self.sc.rig, self.sc.sun
        self.W, self.H, self.TW, self.TH = SC.W, SC.H, SC.TW, SC.TH
        self.env = cand_stage / (SC.FP.PREFIX + "environment")
        self.t = math.tan(math.radians(self.cam["fov"]) / 2)

    def frame_px(self, Pl):
        """prefab-local (camera axes x depth scale) -> rest-frame px (x, y) and forward depth."""
        x, y, z = Pl[..., 0], Pl[..., 1], Pl[..., 2]
        zs = np.where(z > 1e-6, z, np.nan)
        px = (x / (zs * self.t * self.W / self.H) + 1) * 0.5 * self.W
        py = (1 - y / (zs * self.t)) * 0.5 * self.H
        return px, py, z

    def light(self, nl):
        """Hex/Lit irradiance for prefab-local normals (rotated back to world, as the bake saw them)."""
        nw = nl @ self.C.T
        nw = nw / (np.linalg.norm(nw, axis=-1, keepdims=True) + 1e-9)
        return self.E.light(nw.astype(np.float32), self.rig, self.sun).astype(np.float32)


def read_bin(path: Path):
    import town_full3d_ldi as L
    v, n, uv, subs = L.read_bin(path)
    return v, n, uv, np.concatenate(subs).astype(np.int64)


def load_canvas(extsrc: Path, faction: str):
    man = json.loads((extsrc / "manifest.json").read_text(encoding="utf-8"))
    if man.get("schema") != "town_full3d_extsrc.v1" or man.get("faction") != faction:
        raise SystemExit(f"{extsrc}: not a town_full3d_extsrc.v1 canvas for {faction}")
    if sha(extsrc / man["file"]) != man["sha256"]:
        raise SystemExit(f"{extsrc}: {man['file']} sha256 differs from its manifest")
    img = np.asarray(Image.open(extsrc / man["file"]).convert("RGB")).astype(np.float32) / 255
    return srgb_to_lin(img), int(man["canvasX"][0]), int(man.get("scale", 1)), man


def sample_canvas(lin, cx0, k, px, py):
    sx = ((px - cx0 + 0.5) * k - 0.5).astype(np.float32)
    sy = ((py + 0.5) * k - 0.5).astype(np.float32)
    out = np.zeros(px.shape + (3,), np.float32)
    # cv2.remap is limited to 32767 px per map side; do it in row bands
    for r0 in range(0, px.shape[0], 2048):
        out[r0:r0 + 2048] = cv2.remap(lin, sx[r0:r0 + 2048], sy[r0:r0 + 2048], cv2.INTER_LINEAR,
                                      borderMode=cv2.BORDER_REPLICATE)
    return out


# ------------------------------------------------------------------------------------------------ rebake
def rebake(cx: Ctx, extsrc: Path, pieces: list[str], faction: str) -> dict:
    lin, cx0, k, man = load_canvas(extsrc, faction)
    wc = lin.shape[1] // k
    rr = UVRaster()
    rep = {"extsrc": str(extsrc), "extsrcSha256": man["sha256"], "pieces": {}}
    new_main = {}
    for name in pieces:
        t0 = time.time()
        mb, tp = cx.env / f"{name}.bytes", cx.env / f"{name}_albedo.png"
        v, n, uv, tris = read_bin(mb)
        old = np.asarray(Image.open(tp).convert("RGB"))
        h, w = old.shape[:2]
        Pm, Nm, cov = rr.render(uv, v, n, tris, w, h)
        px, py, z = cx.frame_px(Pm)
        ok = cov & np.isfinite(px) & (z > 0)
        L = cx.light(Nm)
        if name in TERRAIN or name.startswith("Mesh_Terrain"):
            # outside the painted rect, inside the canvas
            sel = ok & ((px >= cx.TW) | (py >= cx.TH) | (px < 0)) & (px >= cx0) & (px < cx0 + wc) & (py < cx.H)
            wgt = sel.astype(np.float32)
            inrect = ok & (px >= 0) & (px < cx.TW) & (py >= 0) & (py < cx.TH)
        else:
            cxp, cyp = px - cx0, py
            d = np.minimum.reduce([cxp, wc - 1 - cxp, cyp, cx.H - 1 - cyp])
            outside = (px < 0) | (px >= cx.W)
            sel = ok & outside & (d >= 0)
            wgt = np.where(sel, np.clip(d / EXT_FEATHER_PX, 0, 1), 0).astype(np.float32)
            inrect = None
        samp = sample_canvas(lin, cx0, k, np.where(ok, px, 0), np.where(ok, py, 0))
        alb = np.clip(samp / np.maximum(L, 0.02), 0, 1)
        old_lin = srgb_to_lin(old.astype(np.float32) / 255)
        mix = old_lin * (1 - wgt[..., None]) + alb * wgt[..., None]
        new = (lin_to_srgb(mix) * 255 + 0.5).astype(np.uint8)
        new = np.where((wgt > 0)[..., None], new, old)          # untouched texels: the seed's bytes
        prep = {"size": [w, h], "covered": int(cov.sum()), "replaced": int((wgt > 0).sum()),
                "seconds": None}
        if inrect is not None and inrect.any():
            # method check: the painting de-lit by our rasterised normals vs the seed's rect texels
            S = cx.SC
            big = srgb_to_lin(np.asarray(S.background_rgb().resize((S.TW * 4, S.TH * 4), Image.LANCZOS)
                                         ).astype(np.float32) / 255)
            pr = cv2.remap(big, ((px + 0.5) * 4 - 0.5).astype(np.float32), ((py + 0.5) * 4 - 0.5).astype(np.float32),
                           cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
            rec = (lin_to_srgb(np.clip(pr / np.maximum(L, 0.02), 0, 1)) * 255 + 0.5)
            dd = np.abs(rec - old.astype(np.float32)).mean(-1)[inrect]
            prep["rectReconstruction"] = {"meanAbs": round(float(dd.mean()), 2),
                                          "p90": round(float(np.percentile(dd, 90)), 2),
                                          "note": "painting / our irradiance vs the seed's rect texels (not written)"}
        Image.fromarray(new).save(tp)
        new_main[name] = new
        prep["seconds"] = round(time.time() - t0, 1)
        rep["pieces"][name] = prep
        print(name, json.dumps(prep), flush=True)
    # LDI back layers: texels shown at rest follow their (re-baked) main piece
    rep["backFollow"] = follow_back_layers(cx, new_main)
    return rep


def ldi_crops(cx: Ctx) -> dict:
    sr = json.loads((cx.S.WORK / "stage_report.json").read_text(encoding="utf-8"))
    ldi = sr.get("ldi") or {}
    out = {}
    for main, p in (ldi.get("pieces") or {}).items():
        if "backPiece" in p:
            out[p["backPiece"]] = (main, tuple(p["texture"]["cropTexels"]), False)
        if "stopPiece" in p:
            out[p["stopPiece"]] = (main, tuple(p["stopTexture"]["cropTexels"]), True)
    return out


def back_masks(cx: Ctx, back: str, main: str, box, stop: bool):
    """synth_back_texture's own masks, recomputed on the staged bins: (fill, shown, A affine, crop shape)."""
    import town_full3d_ldi as L
    fov = cx.cam["fov"]
    vm, nm, uvm, tm = read_bin(cx.env / f"{main}.bytes")
    vb, nb, uvb, tb = read_bin(cx.env / f"{back}.bytes")
    zmain = L.rest_depth(vm, tm, fov)
    if stop:
        bname = back[:-len("_Far")]
        vk, _, _, tk = read_bin(cx.env / f"{bname}.bytes")
        zmain = np.minimum(zmain, L.rest_depth(vk, tk, fov))
    zback = L.rest_depth(vb, tb, fov)
    fx, fy, _ = L.project(vb, fov)
    A, res = L.uv_affine(uvb.astype(np.float64), fx, fy)
    tex = np.asarray(Image.open(cx.env / f"{back}_albedo.png").convert("RGB"))
    th, tw = tex.shape[:2]
    jj, ii = np.meshgrid(np.arange(tw) + 0.5, np.arange(th) + 0.5)
    u, vv = jj / tw, 1 - ii / th
    gx = A[0, 0] * u + A[0, 1] * vv + A[0, 2]
    gy = A[1, 0] * u + A[1, 1] * vv + A[1, 2]
    hh, ww = zback.shape
    xi = np.clip(np.floor(gx), 0, ww - 1).astype(np.int64)
    yi = np.clip(np.floor(gy), 0, hh - 1).astype(np.int64)
    zm, zk = zmain[yi, xi], zback[yi, xi]
    has = np.isfinite(zk)
    hidden = has & (zm < zk / 1.0005)
    shown = has & ~hidden
    kp = 2 * L.PROTECT_TEXELS + 1
    protect = cv2.dilate(shown.astype(np.uint8), np.ones((kp, kp), np.uint8)) > 0
    return {"fill": hidden & ~protect, "shown": shown, "protect": protect, "gx": gx, "gy": gy, "tex": tex,
            "uvResidualPx": float(res), "vb": vb, "nb": nb, "uvb": uvb, "tb": tb}


def follow_back_layers(cx: Ctx, new_main: dict) -> dict:
    rep = {}
    for back, (main, box, stop) in ldi_crops(cx).items():
        if main not in new_main:
            continue
        x0, y0, x1, y1 = box
        tex = np.asarray(Image.open(cx.env / f"{back}_albedo.png").convert("RGB")).copy()
        crop_new = new_main[main][y0:y1, x0:x1]
        if crop_new.shape != tex.shape:
            raise SystemExit(f"{back}: crop {box} of {main} is {crop_new.shape}, texture is {tex.shape}")
        m = back_masks(cx, back, main, box, stop)
        keep = ~m["fill"]                       # every texel the LDI copied verbatim follows the main piece
        changed = keep & np.any(tex != crop_new, -1)
        tex[keep] = crop_new[keep]
        Image.fromarray(tex).save(cx.env / f"{back}_albedo.png")
        rep[back] = {"verbatimFollowed": int(keep.sum()), "changed": int(changed.sum()), "fill": int(m["fill"].sum())}
        print(back, json.dumps(rep[back]), flush=True)
    return rep


# ------------------------------------------------------------------------------------------------ backfill
def load_plate(path: Path):
    """A frame-registered plate: RGB(A) at k x 1920x1080 (k integer); alpha (or a sibling <stem>_mask.png, white =
    valid) marks where the plate is meant to be used. -> (lin k x frame, valid, k)."""
    im = Image.open(path)
    rgba = np.asarray(im.convert("RGBA")).astype(np.float32) / 255
    h, w = rgba.shape[:2]
    k = w // 1920
    if k < 1 or w != 1920 * k or h != 1080 * k:
        raise SystemExit(f"{path}: {w}x{h} is not k x 1920x1080")
    valid = rgba[..., 3] > 0.5
    mp = path.with_name(path.stem + "_mask.png")
    if mp.is_file():
        valid &= np.asarray(Image.open(mp).convert("L")) > 127
    return srgb_to_lin(rgba[..., :3]), valid, k


def backfill(cx: Ctx, plates: list[Path], only: list[str] | None) -> dict:
    rr = UVRaster()
    pl = [load_plate(p) for p in plates]
    rep = {"plates": [{"path": str(p), "sha256": sha(p)} for p in plates], "pieces": {}}
    for back, (main, box, stop) in ldi_crops(cx).items():
        if only and back not in only:
            continue
        t0 = time.time()
        m = back_masks(cx, back, main, box, stop)
        tex = m["tex"].copy()
        th, tw = tex.shape[:2]
        _, Nm, cov = rr.render(m["uvb"], m["vb"], m["nb"], m["tb"], tw, th)
        L = cx.light(Nm)
        col = np.zeros((th, tw, 3), np.float32)
        got = np.zeros((th, tw), bool)
        for lin, valid, k in pl:
            sx = ((m["gx"]) * k - 0.5).astype(np.float32)
            sy = ((m["gy"]) * k - 0.5).astype(np.float32)
            xi = np.clip(np.round(sx), 0, valid.shape[1] - 1).astype(np.int64)
            yi = np.clip(np.round(sy), 0, valid.shape[0] - 1).astype(np.int64)
            inb = (m["gx"] >= 0) & (m["gx"] < 1920) & (m["gy"] >= 0) & (m["gy"] < 1080)
            v = inb & valid[yi, xi]
            s = np.zeros((th, tw, 3), np.float32)
            for r0 in range(0, th, 2048):
                s[r0:r0 + 2048] = cv2.remap(lin, sx[r0:r0 + 2048], sy[r0:r0 + 2048], cv2.INTER_LINEAR,
                                            borderMode=cv2.BORDER_REPLICATE)
            col = np.where(v[..., None], s, col)
            got |= v
        use = m["fill"] & got & cov
        alb = np.clip(col / np.maximum(L, 0.02), 0, 1)
        new = (lin_to_srgb(alb) * 255 + 0.5).astype(np.uint8)
        tex[use] = new[use]
        if np.any(tex[~m["fill"]] != m["tex"][~m["fill"]]):
            raise SystemExit(f"{back}: a non-fill texel changed (rest frame would move)")
        Image.fromarray(tex).save(cx.env / f"{back}_albedo.png")
        r = {"fill": int(m["fill"].sum()), "plated": int(use.sum()), "quiltKept": int((m["fill"] & ~use).sum()),
             "shownAtRest": int(m["shown"].sum()), "uvResidualPx": round(m["uvResidualPx"], 4),
             "seconds": round(time.time() - t0, 1)}
        rep["pieces"][back] = r
        print(back, json.dumps(r), flush=True)
    return rep


# ------------------------------------------------------------------------------------------------ detail (upscale)
def detail(cx: Ctx, upscaled: Path, pieces: list[str], tol: float) -> dict:
    """In-rect texels the lane took verbatim from the painting (painting / irradiance reproduces them within tol)
    gain the detail of an upscaled painting: new = old + (rec(upscaled) - rec(native LANCZOS)), in linear light.
    Texels the lane synthesised (under-building carve fills, LDI-protected edits) fail the tol test and stay. This
    deliberately changes the rest frame (sharper painting) - an A/B, not a byte-identical step."""
    S = cx.SC
    nat = srgb_to_lin(np.asarray(S.background_rgb().resize((S.TW * 4, S.TH * 4), Image.LANCZOS)).astype(np.float32) / 255)
    up = srgb_to_lin(np.asarray(Image.open(upscaled).convert("RGB").resize((S.TW * 4, S.TH * 4), Image.LANCZOS)
                                ).astype(np.float32) / 255)
    rr = UVRaster()
    rep = {"upscaled": str(upscaled), "upscaledSha256": sha(upscaled), "tol": tol, "pieces": {}}
    new_main = {}
    for name in pieces:
        tp = cx.env / f"{name}_albedo.png"
        v, n, uv, tris = read_bin(cx.env / f"{name}.bytes")
        old = np.asarray(Image.open(tp).convert("RGB"))
        h, w = old.shape[:2]
        Pm, Nm, cov = rr.render(uv, v, n, tris, w, h)
        px, py, z = cx.frame_px(Pm)
        ok = cov & np.isfinite(px) & (z > 0)
        inrect = ok & (px >= 0) & (px < cx.TW) & (py >= 0) & (py < cx.TH)
        L = np.maximum(cx.light(Nm), 0.02)
        mx = ((np.where(ok, px, 0) + 0.5) * 4 - 0.5).astype(np.float32)
        my = ((np.where(ok, py, 0) + 0.5) * 4 - 0.5).astype(np.float32)
        rn = np.clip(cv2.remap(nat, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE) / L, 0, 1)
        ru = np.clip(cv2.remap(up, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE) / L, 0, 1)
        verb = inrect & (np.abs(lin_to_srgb(rn) * 255 - old.astype(np.float32)).mean(-1) <= tol)
        nl = np.clip(srgb_to_lin(old.astype(np.float32) / 255) + (ru - rn), 0, 1)
        new = np.where(verb[..., None], (lin_to_srgb(nl) * 255 + 0.5).astype(np.uint8), old)
        Image.fromarray(new).save(tp)
        new_main[name] = new
        rep["pieces"][name] = {"inRect": int(inrect.sum()), "detailed": int(verb.sum())}
        print(name, json.dumps(rep["pieces"][name]), flush=True)
    rep["backFollow"] = follow_back_layers(cx, new_main)
    return rep


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("rebake")
    p.add_argument("--extsrc", required=True)
    p.add_argument("--pieces", default="Mesh_Terrain,Mesh_TerrainNear_0,Mesh_TerrainNear_1,Mesh_OuterL0,Mesh_OuterL1,"
                                        "Mesh_OuterL2,Mesh_OuterC0,Mesh_OuterR0,Mesh_OuterR1,Mesh_OuterR2")
    p = sub.add_parser("backfill")
    p.add_argument("--plate", action="append", required=True)
    p.add_argument("--only")
    p = sub.add_parser("detail")
    p.add_argument("--upscaled", required=True)
    p.add_argument("--pieces", default="Mesh_Terrain")
    p.add_argument("--tol", type=float, default=12.0)
    a, _ = ap.parse_known_args()
    import stronghold_full3d_scene as S
    if not S.CANDIDATE:
        raise SystemExit("set TOWN_FULL3D_CANDIDATE")
    cx = Ctx(S.STAGE)
    if a.cmd == "rebake":
        rep = rebake(cx, Path(a.extsrc), a.pieces.split(","), S.SC.FACTION)
    elif a.cmd == "detail":
        rep = detail(cx, Path(a.upscaled), a.pieces.split(","), a.tol)
    else:
        rep = backfill(cx, [Path(x) for x in a.plate], a.only.split(",") if a.only else None)
    rp = S.WORK / "stage_report.json"
    sr = json.loads(rp.read_text(encoding="utf-8"))
    kb = sr.setdefault("kokonBackfill", {"schema": "town_full3d_kokon_backfill.v1",
                                         "proofTier": "generated artifact / offline render"})
    kb[a.cmd] = rep
    rp.write_text(json.dumps(sr, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
