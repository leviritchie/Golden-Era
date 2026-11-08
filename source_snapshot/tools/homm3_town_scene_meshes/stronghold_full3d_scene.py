#!/usr/bin/env python3
"""Stronghold full-3D town scene: stage (meshes + textures + Unity spec + v2 catalog), bundle, render, report.

    python tools/homm3_town_scene_meshes/stronghold_full3d_scene.py stage     # everything offline, no Unity
    python tools/homm3_town_scene_meshes/stronghold_full3d_scene.py preview   # moderngl preview of the default frame
    python tools/homm3_town_scene_meshes/stronghold_full3d_scene.py bundle    # Unity job via the Unity queue
    python tools/homm3_town_scene_meshes/stronghold_full3d_scene.py render    # editor renders via the Unity queue
    python tools/homm3_town_scene_meshes/stronghold_full3d_scene.py validate  # the shared town-scene contract

Method and assessment: docs/homm3_stronghold_full_3d_town.md. Sources: the original HoMM3 Stronghold background and
building sprites only (never the old 2D backdrop / its outpaint), monocular depth (stronghold_full3d_depth), the
vanilla Olden Era desert assets (stronghold_full3d_vanilla). No Meshy; no paid generation. Nothing is installed.
Scratch: artifacts/homm3_stronghold_full3d/ (STRONGHOLD_FULL3D_ROOT).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import struct
import sys
import time
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import stronghold_full3d_common as SC  # noqa: E402
import stronghold_full3d_terrain as T  # noqa: E402
import stronghold_full3d_ground as G  # noqa: E402

W, H, TW, TH = SC.W, SC.H, SC.TW, SC.TH
BUNDLE = SC.FP.BUNDLE
PREFIX = SC.FP.PREFIX
ASSET_ROOT = SC.FP.ASSET_ROOT
# TOWN_FULL3D_CANDIDATE=<name> (legacy name STRONGHOLD_FULL3D_CANDIDATE) redirects every output (bundle, Unity project, renders, review, work reports) to
# candidates/<name>/, so a candidate never overwrites the installed "before" in bundle/ and unity_project/. Inputs
# (depth/, vanilla/, the frame-depth cache) stay shared. `candidate-init` seeds a candidate from the base outputs.
_cand_new = os.environ.get("TOWN_FULL3D_CANDIDATE", "").strip()
_cand_old = os.environ.get("STRONGHOLD_FULL3D_CANDIDATE", "").strip()
if _cand_new and _cand_old and _cand_new != _cand_old:
    raise SystemExit(f"TOWN_FULL3D_CANDIDATE={_cand_new} and STRONGHOLD_FULL3D_CANDIDATE={_cand_old} disagree")
CANDIDATE = _cand_new or _cand_old
CAND = SC.DATA / "candidates" / CANDIDATE if CANDIDATE else SC.DATA
WORK = CAND / "work"
OUT = CAND / "bundle"              # bundle + catalog + coverage raster (the --catalog candidate folder)
UNITY_PROJECT = CAND / "unity_project"
STAGE = UNITY_PROJECT / ASSET_ROOT  # meshes + textures, staged straight into the dedicated Unity project
SHADER_DIR = "Assets/Homm3Conflux/Shaders"   # the bundle's FlowWater / VfxUber replicas (tools/.../unity/shaders)
ROWS = STAGE / "rows.json"         # every staged prefab's bins / particle groups (the Unity build spec's source)
RENDERS = CAND / "renders"
UNITY = Path(r"C:/Program Files/Unity/Hub/Editor/6000.0.66f2/Editor/Unity.exe")
UNITY_MODULES = ["animation", "assetbundle", "imageconversion", "imgui", "jsonserialize", "ui", "uielements",
                 "physics", "unitywebrequest", "particlesystem"]   # the Conflux lane's project, unchanged
WATER_SPEC_EL = 22.0   # deg: the fountains' fixed specular light, low over the far side (the Conflux river value)
TERRAIN_MIP_BIAS, TERRAIN_ANISO = -0.5, 8
SKY_AZ, SKY_EL = (-82.0, 82.0), (-16.0, 62.0)
# Key light: hand-set per painting (faction profile); the albedo bake divides by this rig, so the rest pose reproduces
# the painting whatever the direction; it only decides how the relief reads when the camera pans. toSun in camera
# axes (right, up, toward camera):
TO_SUN_CAM = SC.FP.TO_SUN_CAM
FILL = {"dir": [0.6777324471263626, -0.3420201433256687, 0.6509231517742006],
        "color": [0.8157023868276849, 0.8924743761761731, 1.074807850878832]}   # the Conflux lane's fill, unchanged


def rig_and_sun(cam: dict):
    import build_conflux_town3d_preview as B
    import build_conflux_town3d_preview as _b  # noqa: F401
    rig = B.city_rig(B.camera()["scene"])
    rig["fillDir"], rig["fillColor"] = FILL["dir"], FILL["color"]
    ts = np.array(TO_SUN_CAM, np.float64)
    to_sun = ts[0] * cam["right"] + ts[1] * cam["up"] - ts[2] * cam["fwd"]
    to_sun /= np.linalg.norm(to_sun)
    return rig, (-to_sun).astype(np.float32)


def write_bin(path: Path, v, n, uv, subs) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        f.write(struct.pack("<ii", len(v), len(subs)))
        f.write(np.asarray(v, np.float32).tobytes())
        f.write(np.asarray(n, np.float32).tobytes())
        f.write(np.asarray(uv, np.float32).tobytes())
        for s in subs:
            s = np.asarray(s, np.int32).ravel()
            f.write(struct.pack("<i", len(s)))
            f.write(s.tobytes())


def save_srgb(path: Path, lin: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray((G.lin_to_srgb(lin) * 255 + 0.5).astype(np.uint8)).save(path)


class Scene:
    """The painting world (Y up, painting metres) and its map to the prefab frame (camera units)."""

    def __init__(self):
        self.ctx = G.Ctx()
        self.cam = self.ctx.cam
        self.cpos = self.cam["pos"]
        self.C = np.stack([self.cam["right"], self.cam["up"], self.cam["fwd"]], 1)
        self.scale = T.DEPTH_SCALE
        self.rig, self.sun = rig_and_sun(self.cam)
        self.pieces: dict = {}        # prefabKey -> list of bin rows
        self.preview: list = []        # (name, P, n, uv, tris, img_srgb_uint8, unlit)
        self.report: dict = {}
        self.wall_edges: dict = {}     # layer id -> closing-wall near edges (k, 2, 3), prefab frame

    def local(self, w):
        return ((np.asarray(w, np.float64) - self.cpos) @ self.C) * self.scale

    def local_dir(self, d):
        return np.asarray(d, np.float64) @ self.C

    def add_bin(self, prefab: str, name: str, P, n, uv, tris, lin_or_srgb, kind="lit", srgb=False, max_size=4096,
                extra=None, preview=True):
        mesh = STAGE / prefab / f"{name}.bytes"
        tex = STAGE / prefab / f"{name}_albedo.png"
        write_bin(mesh, self.local(P), self.local_dir(n), uv, [tris])
        if srgb:
            tex.parent.mkdir(parents=True, exist_ok=True)
            Image.fromarray(np.asarray(lin_or_srgb, np.uint8)).save(tex)
            img = np.asarray(lin_or_srgb, np.uint8)
        else:
            save_srgb(tex, lin_or_srgb)
            img = np.asarray(Image.open(tex))
        row = {"name": name, "mesh": f"{ASSET_ROOT}/{prefab}/{name}.bytes",
               "texture": f"{ASSET_ROOT}/{prefab}/{name}_albedo.png", "kind": kind, "maxSize": max_size}
        if extra:
            row.update(extra)
        self.pieces.setdefault(prefab, []).append(row)
        if preview:
            self.preview.append((f"{prefab}/{name}", np.asarray(P, np.float32), np.asarray(n, np.float32),
                                 np.asarray(uv, np.float32), np.asarray(tris, np.int32), img, kind == "sky"))
        return row


# ------------------------------------------------------------------------------------------------ terrain stage
NORMAL_SIGMA_CELLS, NORMAL_VIEW_BIAS = 1.5, 0.35


def soften_normals(sc: Scene, grid: dict) -> np.ndarray:
    """Monocular-depth normals are noisy at the pixel scale; lit as they are, the de-lit albedo clips (grey blotches
    where a facet turned from the sun). Normals are blurred over NORMAL_SIGMA_CELLS grid cells and leaned toward
    up + the viewer by NORMAL_VIEW_BIAS (hand-set); the bake uses the same normals, so the rest pose is unchanged."""
    n = grid["n"].astype(np.float32)
    nb = cv2.GaussianBlur(n, (0, 0), NORMAL_SIGMA_CELLS)
    to_cam = sc.cpos - grid["P"]
    to_cam /= np.linalg.norm(to_cam, axis=-1, keepdims=True) + 1e-9
    bias = to_cam + np.array([0.0, 1.0, 0.0])
    bias /= np.linalg.norm(bias, axis=-1, keepdims=True)
    out = nb * (1 - NORMAL_VIEW_BIAS) + bias * NORMAL_VIEW_BIAS
    return out / (np.linalg.norm(out, axis=-1, keepdims=True) + 1e-9)

def terrain_state(sc: Scene) -> dict:
    """The measured terrain (rect depth, world field, frame extension, frame mesh, albedo baker), cached on sc."""
    import conflux_full3d_env as E
    if hasattr(sc, "terrain"):
        return sc.terrain
    rd = T.rect_depth(sc.cam)
    field, finfo = T.world_field(sc.cam, rd)
    fd = G.frame_depth(sc.ctx, rd, field)
    grid = E.terrain_mesh(sc.ctx, fd["zs"], grid=3)
    grid["n"] = soften_normals(sc, grid)
    baker = G.Baker(sc.ctx, fd, grid, rd["floor"], sc.rig, sc.sun, field)
    sc.terrain = {"rd": rd, "field": field, "finfo": finfo, "fd": fd, "grid": grid, "baker": baker,
                  "floor": rd["floor"], "cam": sc.cam}
    return sc.terrain


def stage_terrain(sc: Scene) -> dict:
    t0 = time.time()
    st = terrain_state(sc)
    rd, field, finfo, fd, grid, baker = (st[k] for k in ("rd", "field", "finfo", "fd", "grid", "baker"))
    P = grid["P"].reshape(-1, 3)
    n = grid["n"].reshape(-1, 3)
    fx, fy = grid["fx"].ravel(), grid["fy"].ravel()
    tris = grid["tris"]
    cy = fy[tris].mean(1)
    cx = fx[tris].mean(1)
    env = PREFIX + "environment"
    pieces = [("Mesh_Terrain", cy < G.NEAR_Y, (0, 0, W, G.NEAR_Y + 6), G.MAIN_SCALE),
              ("Mesh_TerrainNear_0", (cy >= G.NEAR_Y) & (cx < W / 2), (0, G.NEAR_Y - 6, W // 2 + 6, H), G.NEAR_SCALE),
              ("Mesh_TerrainNear_1", (cy >= G.NEAR_Y) & (cx >= W / 2), (W // 2 - 6, G.NEAR_Y - 6, W, H), G.NEAR_SCALE)]
    rep = []
    for name, sel, box, scale in pieces:
        t = tris[sel]
        used = np.unique(t)
        remap = np.full(len(P), -1)
        remap[used] = np.arange(len(used))
        x0, y0, x1, y1 = box
        uv = np.stack([(fx[used] - x0) / (x1 - x0), 1 - (fy[used] - y0) / (y1 - y0)], -1)
        lin = baker.bake(box, scale)
        sc.add_bin(env, name, P[used], n[used], uv, remap[t], lin,
                   extra={"mipBias": TERRAIN_MIP_BIAS, "aniso": TERRAIN_ANISO})
        rep.append({"name": name, "texelsPerPx": float(scale), "size": [lin.shape[1], lin.shape[0]],
                    "tris": int(len(t)), "box": list(box)})
    sc.report["terrain"] = {"calibration": rd["calib"], "backgroundDepth": rd["calib"]["backgroundDepth"], "floorTiltDeg": round(rd["floor"].tilt_deg, 2),
                            "camHeightAboveFloorM": round(float(rd["floor"].rel(sc.cam["pos"][None])[0]), 2),
                            "crossCheck": T.cross_check(rd["floor"], rd["sky"]), "field": finfo,
                            "extensionEscapedPx": fd["escaped"], "pieces": rep, "seconds": round(time.time() - t0, 1)}
    return sc.report["terrain"]


def stage_sky(sc: Scene) -> dict:
    """Camera-centred dome cap: the painted sky, directions outside it mirrored into the painted sky (no blur); with
    a profile SKY_PANO the composite instead (painted sky + periodic SD panorama, town_full3d_sky), drift or not."""
    from scipy.ndimage import binary_erosion
    rd = sc.terrain["rd"] if hasattr(sc, "terrain") else T.rect_depth(sc.cam)   # --parts sky alone
    up = np.array([0.0, 1.0, 0.0])
    f, r = T.heading(sc.cam)
    STW, STH = 4096, 2048
    az = np.radians(np.linspace(SKY_AZ[0], SKY_AZ[1], STW))
    el = np.radians(np.linspace(SKY_EL[1], SKY_EL[0], STH))
    # border_value 1 keeps the rect's own edge columns (as town_full3d_sky.painted_sky): eroding them away left the
    # last two columns with no sky row, so their mirror samples fell back to row 0 and drew a one-colour line at the
    # right frame edge (x = TW - 1; Stronghold v32 rest render, rows 25..100, 2026-09-28)
    sky_e = binary_erosion(rd["sky"], np.ones((3, 3), bool), iterations=2, border_value=1)
    rows = np.where(sky_e, np.arange(TH)[:, None], -1)
    above = np.maximum.accumulate(rows, axis=0)
    first = np.where(sky_e.any(0), np.argmax(sky_e, axis=0), 0)
    pl = np.asarray(SC.albedo_background().resize((TW * 2, TH * 2), Image.LANCZOS)).astype(np.float32)
    img = np.zeros((STH, STW, 3), np.float32)
    for r0 in range(0, STH, 256):
        E_, A = np.meshgrid(el[r0:r0 + 256], az, indexing="ij")
        d = np.cos(E_)[..., None] * (np.cos(A)[..., None] * f + np.sin(A)[..., None] * r) + np.sin(E_)[..., None] * up
        px, py, _ = T.project(sc.cam, sc.cam["pos"] + d)
        # mirror into the painted rect (at its right and bottom edges, and at 0)
        mx = np.where(px >= TW, 2 * (TW - 1) - px, px)
        mx = np.abs(mx)
        mx = np.where(mx >= TW, np.mod(mx, TW), mx)
        my = np.where(py >= TH, 2 * (TH - 1) - py, py)
        my = np.abs(my)
        mx, my = np.clip(mx, 0, TW - 1), np.clip(my, 0, TH - 1)
        xi, yi = mx.round().astype(int), my.round().astype(int)
        ya = above[yi, xi]
        ya = np.where(ya < 0, first[xi], ya)
        sy_ = np.where(sky_e[yi, xi], my, ya.astype(np.float64))
        u = np.clip(mx * 2 + 0.5, 0, TW * 2 - 1.001).astype(np.float32)
        v = np.clip(sy_ * 2 + 0.5, 0, TH * 2 - 1.001).astype(np.float32)
        img[r0:r0 + 256] = cv2.remap(pl, u, v, cv2.INTER_LINEAR)
    img = np.clip(img, 0, 255).astype(np.uint8)
    import town_full3d_sky as SKY
    if SKY.spec()["mode"] == "drift" or SKY.has_pano():
        # the composite (painted sky + periodic SD panorama) at the dome's own directions: no mirror fill, and a
        # drift band matches the dome at t = 0 (pano_spec fails closed when a drift has no SKY_PANO)
        img = SKY.composite(sc, np.degrees(az), np.degrees(el))
    GA, GE = 128, 64
    ga = np.radians(np.linspace(SKY_AZ[0], SKY_AZ[1], GA + 1))
    ge = np.radians(np.linspace(SKY_EL[1], SKY_EL[0], GE + 1))
    AA, EE = np.meshgrid(ga, ge)
    dd = np.cos(EE)[..., None] * (np.cos(AA)[..., None] * f + np.sin(AA)[..., None] * r) + np.sin(EE)[..., None] * up
    Pw = sc.cam["pos"] + dd * T.DOME_R
    uv = np.stack([(AA - ga[0]) / (ga[-1] - ga[0]), (EE - ge[-1]) / (ge[0] - ge[-1])], -1).reshape(-1, 2)
    nx_ = GA + 1
    j, i = np.meshgrid(np.arange(GE), np.arange(GA), indexing="ij")
    a = (j * nx_ + i).ravel()
    tris = np.concatenate([np.stack([a, a + 1, a + nx_], 1), np.stack([a + 1, a + nx_ + 1, a + nx_], 1)])
    sc.add_bin(PREFIX + "environment", "Sky_Dome", Pw.reshape(-1, 3), -dd.reshape(-1, 3), uv, tris, img, kind="sky",
               srgb=True)
    sc.report["sky"] = {"domeRadiusM": T.DOME_R, "domeUnits": round(T.DOME_R * sc.scale, 2), "azDeg": SKY_AZ,
                        "elDeg": SKY_EL, "texture": [STW, STH]}
    anim = SKY.spec()
    sc.report["sky"]["anim"] = {"mode": anim["mode"], "reason": anim["reason"]}
    if anim["mode"] == "drift":
        sc.report["sky"]["anim"] = SKY.stage_drift(sc, PREFIX + "environment", SKY_AZ, SKY_EL)
    return sc.report["sky"]


# ------------------------------------------------------------------------------------------------ preview
def preview(sc: Scene, out: Path, cams: dict | None = None, w=W, h=H) -> dict:
    import stronghold_full3d_preview as PV
    R = PV.Renderer(sc.rig, sc.sun, w, h)
    for name, P, n, uv, tris, img, unlit in sc.preview:
        R.add(name, P, n, uv, tris, img, unlit=unlit)
    shots = {}
    for k, cam in (cams or {"default": sc.cam}).items():
        a = R.render(cam, near=2.0, far=T.DOME_R * 1.2)
        p = out / f"{k}.png"
        p.parent.mkdir(parents=True, exist_ok=True)
        Image.fromarray(a).save(p)
        shots[k] = str(p)
    return shots


def pan_cams(sc: Scene) -> dict:
    """The vanilla camera's proof poses (conflux_town_camera_pan.proof_poses, 16:9) in the painting world."""
    import conflux_town_camera_pan as PAN
    out = {}
    for p in PAN.proof_poses():
        pos = sc.cpos + (np.asarray(p["pos"]) / sc.scale) @ sc.C.T
        f = np.asarray(p["fwd"]) @ sc.C.T
        u = np.asarray(p["up"]) @ sc.C.T
        f /= np.linalg.norm(f)
        u /= np.linalg.norm(u)
        r = np.cross(u, f)
        out[p["name"]] = {**sc.cam, "pos": pos, "fwd": f, "up": u, "right": r / np.linalg.norm(r)}
    return out


def orbit_cam(sc: Scene, yaw_deg: float, pitch_deg: float = 0.0, target_depth: float = 130.0) -> dict:
    """Review orbit: the rest camera rotated about the floor point target_depth ahead (not a runtime pose)."""
    c = sc.cam
    fl = sc.terrain_floor if hasattr(sc, "terrain_floor") else None
    tgt = c["pos"] + c["fwd"] * target_depth
    R = PANR(yaw_deg, pitch_deg, c)
    off = R @ (c["pos"] - tgt)
    pos = tgt + off
    f = tgt - pos
    f /= np.linalg.norm(f)
    r = np.cross([0.0, 1.0, 0.0], f)
    r /= np.linalg.norm(r)
    u = np.cross(f, r)
    return {**c, "pos": pos, "fwd": f, "up": u, "right": r}


def PANR(yaw_deg, pitch_deg, c):
    from scipy.spatial.transform import Rotation
    ry = Rotation.from_rotvec(np.array([0.0, 1.0, 0.0]) * math.radians(yaw_deg))
    rx = Rotation.from_rotvec(np.asarray(c["right"]) * math.radians(pitch_deg))
    return (ry * rx).as_matrix()


def read_bin(path: Path):
    b = path.read_bytes()
    nv, ns = struct.unpack_from("<ii", b, 0)
    o = 8
    v = np.frombuffer(b, np.float32, nv * 3, o).reshape(-1, 3); o += nv * 12
    n = np.frombuffer(b, np.float32, nv * 3, o).reshape(-1, 3); o += nv * 12
    uv = np.frombuffer(b, np.float32, nv * 2, o).reshape(-1, 2); o += nv * 8
    subs = []
    for _ in range(ns):
        (c,) = struct.unpack_from("<i", b, o); o += 4
        subs.append(np.frombuffer(b, np.int32, c, o).reshape(-1, 3)); o += c * 4
    return v, n, uv, subs


def load_staged_preview(sc: Scene, prefabs=None) -> None:
    """Preview rows from the staged bins (prefab frame -> painting world)."""
    sc.preview = []
    # the bins the build spec names (ROWS), not every .bytes on disk: a bin an earlier stage left behind is not built
    rows = json.loads(ROWS.read_text(encoding="utf-8")) if ROWS.is_file() else None
    for pdir in sorted(STAGE.iterdir()):
        if prefabs and pdir.name not in prefabs:
            continue
        named = None if rows is None else {b["name"] for b in rows.get(pdir.name, {}).get("bins", [])}
        for mb in sorted(pdir.glob("*.bytes")):
            if named is not None and mb.stem not in named:
                continue
            tex = mb.with_name(mb.stem + "_albedo.png")
            if not tex.is_file():
                continue
            v, n, uv, subs = read_bin(mb)
            if mb.stem == "Sky_Drift":
                # holder-local mesh: the staged row's rotation (t = 0) takes it to the prefab frame
                import town_full3d_sky as SKY
                v, n = SKY.holder_to_prefab(v, n, pdir.name)
            P = sc.cpos + (v.astype(np.float64) / sc.scale) @ sc.C.T
            nw = n.astype(np.float64) @ sc.C.T
            img = np.asarray(Image.open(tex))
            sc.preview.append((f"{pdir.name}/{mb.stem}", P.astype(np.float32), nw.astype(np.float32), uv,
                               np.concatenate(subs), img, mb.stem.startswith("Sky_")))


# ------------------------------------------------------------------------------------------------ rows / fx
def save_rows(sc: Scene, fx_rows: dict | None = None, periphery_prefab: str | None = None) -> dict:
    """Merge this run's staged rows into ROWS (by prefab, then by piece name): a partial stage keeps the rest."""
    rows = json.loads(ROWS.read_text(encoding="utf-8")) if ROWS.is_file() else {}
    if periphery_prefab is not None and periphery_prefab in rows:
        # a periphery stage emits every outer piece (Mesh_Outer*): one it no longer emits is not kept from an earlier
        # run (Bulwark 2026-09-29: a refit wall left the far ring's Mesh_OuterC2 empty, and the previous run's C2
        # sliver stayed in the bundle as a needle over the sky). Its staged files stay on disk, unreferenced.
        emitted = {b["name"] for b in sc.pieces.get(periphery_prefab, [])}
        row = rows[periphery_prefab]
        row["bins"] = [b for b in row["bins"] if not b["name"].startswith("Mesh_Outer") or b["name"] in emitted]
    for prefab, bins in sc.pieces.items():
        cur = {b["name"]: b for b in rows.setdefault(prefab, {"bins": [], "particles": []})["bins"]}
        cur.update({b["name"]: b for b in bins})
        rows[prefab]["bins"] = [cur[k] for k in sorted(cur)]
    if fx_rows is not None:
        # an fx stage covers every animated layer: a prefab it no longer names keeps no effects from an earlier run
        for prefab, row in rows.items():
            if prefab not in fx_rows:
                row["bins"] = [b for b in row["bins"] if not b["name"].startswith("Fx_")]
                row["particles"] = []
    for prefab, fx in (fx_rows or {}).items():
        row = rows.setdefault(prefab, {"bins": [], "particles": []})
        cur = {b["name"]: b for b in row["bins"] if not b["name"].startswith("Fx_")}
        cur.update({b["name"]: b for b in fx["bins"]})
        row["bins"] = [cur[k] for k in sorted(cur)]
        row["particles"] = fx["particles"]
    ROWS.parent.mkdir(parents=True, exist_ok=True)
    ROWS.write_text(json.dumps(rows, indent=1), encoding="utf-8")
    return rows


def water_light(sc: Scene):
    """FlowWater's fixed specular direction (prefab frame) and reflected sky colour (the painting's sky)."""
    f = np.asarray(sc.cam["fwd"], np.float64) * np.array([1, 0, 1])
    f /= np.linalg.norm(f) + 1e-9
    spec_w = f * math.cos(math.radians(WATER_SPEC_EL)) + np.array([0, 1.0, 0]) * math.sin(math.radians(WATER_SPEC_EL))
    spec_l = sc.local_dir(spec_w[None, :])[0]
    rd = sc.terrain["rd"] if hasattr(sc, "terrain") else T.rect_depth(sc.cam)
    pl = np.asarray(SC.background_rgb().resize((TW, TH), Image.LANCZOS))
    sky_c = np.median(pl[rd["sky"]].reshape(-1, 3), 0) / 255.0
    return spec_l, sky_c, rd


# ------------------------------------------------------------------------------------------------ catalog / spec
ENV_KEY = PREFIX + "environment"
STATES = SC.FP.STATES   # HoMM3 build states for the editor renders (every layer is also its own prefab)
TIME_FRAMES = [0.0, 0.35, 1.0]
ORBITS = ((-18, 6), (18, 6), (0, 14))   # review orbit (yaw, pitch) deg about the floor point 130 m ahead


def vanilla_sources(names) -> list[dict]:
    prov = json.loads((SC.DATA / "vanilla" / "provenance.json").read_text(encoding="utf-8"))
    out = []
    for n in names:
        row = prov["tex"].get(n) or prov["vfx"].get(n)
        if row is None:
            raise SystemExit(f"catalog: no vanilla provenance for {n}")
        out.append({"texture": n, **{k: row[k] for k in ("file", "pathId", "sha256")}})
    return out


def pan_render_specs() -> list[dict]:
    import conflux_town_camera_pan as PAN
    poses = PAN.proof_poses()
    targets = (("", W, H, {p["name"] for p in poses}),
               ("_4096x2160", 4096, 2160, {"default", "sweep_left", "sweep_right"}),
               ("_21x9", 2560, 1080, {"default", "sweep_left", "sweep_right"}))
    out = []
    for suffix, w, h, names in targets:
        sx = (w / h) / (W / H)
        for p in poses:
            if p["name"] in names:
                out.append({"name": p["name"] + suffix, "state": "full", "pos": p["pos"], "fwd": p["fwd"], "up": p["up"],
                            "w": w, "h": h, "scaleX": sx, "scaleY": 1.0})
    return out


def orbit_render_specs(sc: Scene) -> list[dict]:
    """Review orbits (not runtime poses) as root-frame camera poses: offsets in camera units, like the pan poses."""
    out = []
    for yaw, pitch in ORBITS:
        c = orbit_cam(sc, yaw, pitch)
        out.append({"name": f"orbit_y{yaw:+d}_p{pitch:+d}", "state": "full",
                    "pos": [float(x) for x in sc.local(c["pos"][None, :])[0]],
                    "fwd": [float(x) for x in sc.local_dir(c["fwd"][None, :])[0]],
                    "up": [float(x) for x in sc.local_dir(c["up"][None, :])[0]], "w": W, "h": H, "scaleX": 1.0,
                    "scaleY": 1.0})
    return out


# top-level catalog keys write_catalog itself decides only when their opt-in input is present: never carried stale
CATALOG_OPTIONAL_OWNED = frozenset({"skyLook", "terrainStreak", "clothLook", "buildingDepth"})


def write_catalog(sc: Scene, *, carry: str, drop=()) -> dict:
    """Unity build spec (STAGE/build_spec.json), render spec and the v2 catalog (OUT/catalog.json) from ROWS.
    carry (required, town_full3d_fork.catalog_carry): "previous" carries every block of the candidate's previous
    catalog this function does not produce (props, houses, ...; fails closed without a previous catalog); "fresh"
    writes a whole catalog and refuses if that would drop such blocks. drop: keys the caller re-decides itself."""
    import conflux_town_camera_pan as PAN
    import town_full3d_fork as FK
    prev_p = OUT / "catalog.json"
    try:
        previous = json.loads(prev_p.read_text(encoding="utf-8")) if prev_p.is_file() else None
    except (OSError, ValueError) as e:
        raise SystemExit(f"write_catalog: previous catalog {prev_p} is unreadable: {e}")
    rows = json.loads(ROWS.read_text(encoding="utf-8"))
    rep = json.loads((WORK / "stage_report.json").read_text(encoding="utf-8"))
    reach = SC.reachable_layers()
    missing = [l for l in reach if PREFIX + l not in rows] + ([] if ENV_KEY in rows else [ENV_KEY])
    if missing:
        raise SystemExit(f"catalog: prefabs not staged: {missing}")
    gone = [f"{k}/{b['name']}" for k, r in rows.items() for b in r["bins"]
            if not (STAGE / k / f"{b['name']}.bytes").is_file()]
    if gone:
        raise SystemExit(f"catalog: rows name bins with no staged .bytes (a stale row from an earlier stage): {gone}")
    prefabs = []
    for key in [ENV_KEY] + [PREFIX + l for l in reach]:
        r = rows[key]
        prefabs.append({"key": key, "layerId": "" if key == ENV_KEY else key[len(PREFIX):], "pieces": [], "sprites": [],
                        "discs": [], "bins": r["bins"], "scatters": [], "particles": r.get("particles", [])})
    spec = {"bundleName": BUNDLE, "assetRoot": ASSET_ROOT, "outputPath": str(OUT.resolve()).replace("\\", "/"),
            "prefabs": prefabs}
    # The Unity builder writes each bin's mesh / material to generated/<bin name>.asset|.mat and each particle
    # material to generated/<group>_<system>.mat: a name shared by two prefabs silently makes them share (the last
    # writer's) mesh. Every bin and group name must be unique across the bundle.
    seen: dict[str, str] = {}
    for p in prefabs:
        for nm in [b["name"] for b in p["bins"]] + [g["name"] for g in p["particles"]]:
            if nm in seen:
                raise SystemExit(f"catalog: bin/group name {nm} used by {seen[nm]} and {p['key']} (shared Unity asset)")
            seen[nm] = p["key"]
    (STAGE / "build_spec.json").write_text(json.dumps(spec, indent=1), encoding="utf-8")

    def names(p):
        return [b["name"] for b in p["bins"]] + [g["name"] for g in p["particles"]]

    def animated(p):
        return [b["name"] for b in p["bins"] if b["name"].startswith("Fx_")] + [g["name"] for g in p["particles"]]
    env = prefabs[0]
    fx = rep.get("fx") or {}
    key_local = sc.local_dir(np.asarray(sc.sun, np.float64)[None, :])[0]
    key_local /= np.linalg.norm(key_local)
    fill_local = sc.local_dir(np.asarray(FILL["dir"], np.float64)[None, :])[0]
    fill_local /= np.linalg.norm(fill_local)
    bld_tpp = float(np.median([b["texelsPerPx"] for b in rep["buildings"].values()]))
    floor_src = list(dict.fromkeys([n for n, _ in G.FLOOR_TEX] + [n for n, _ in G.ROCK_TEX]
                                   + [n for n, _ in G.FLOOR_STONES]))
    cov = rep["panCoverage"]
    catalog = {
        "schema": "homm3_town_scene3d_catalog.v2",
        "fraction": SC.FRACTION,
        "bundle": BUNDLE,
        "runtimeLayout": "conflux_4k_outpaint_v1",
        "runtimeLayoutNote": "only the layer-position coordinate basis (positions.json); no painted pixels are drawn "
                             "at runtime beyond the meshes' own albedo",
        "proofTier": "source-prepared candidate (stage only; bundle, editor render and runtime unproven)",
        "fullScene3d": True,
        "phase": 3,
        "backdrop": "hidden",
        "terrainDetail": {"baked": "Mesh_ terrain + Mesh_Outer* albedo (Hex/Lit mainTexture)",
                          "sources": [{"layer": n, **s} for n, s in zip(floor_src, vanilla_sources(floor_src))],
                          "note": "tiling game desert textures multiplied over the HoMM3 macro colour; no AI "
                                  "upscale, outpaint or Meshy"},
        "phaseRevision": "6",
        "waterLook": {"shader": "Homm3Conflux/FlowWater", "vanillaMaterial": "Mtl_River_Water (Hex/Sea)",
                      "vanillaMaterialPathId": 4170, "use": SC.FP.WATER_USE,
                      "sources": vanilla_sources(["WaterNormal"]), "shore": {"outPx": 2, "rangePx": 22}},
        "terrainSampler": {"mipBias": TERRAIN_MIP_BIAS, "aniso": TERRAIN_ANISO,
                           "note": "serialized with the Mesh_ albedo textures; the runtime keeps mainTexture"},
        "references": [f"{SC.FP.BACKGROUND} (HoMM3 town screen)", "layers/*.png (HoMM3 building art)",
                       "layers/anims/* (HoMM3 DEF frames, measured for the effects only)"],
        "referenceCamera": {"fov": float(sc.cam["fov"]), "aspect": W / H, "source": "cityHuman2 CityCamera/MainCamera",
                            "restPose": PAN.rest_pose_contract()},
        "depthScale": float(sc.scale),
        "keyLight": {"cameraLocalDir": [float(x) for x in key_local],
                     "note": "rotates the scene's directional sun; colour/intensity unchanged"},
        "fillLight": {"cameraLocalDir": [float(x) for x in fill_local], "linearColor": FILL["color"], "shadows": False},
        "fog": "off",
        "environment": {"prefabKey": ENV_KEY, "pieces": names(env), "animated": animated(env),
                        "materials": {"Mesh_": "Hex/Lit (city donor rebind, no collider)", "Sky_": "unlit opaque",
                                      "Fx_": "bundle shader on a SkinnedMeshRenderer / ParticleSystemRenderer, or the "
                                             "unlit transparent windmill disc (the runtime re-materials Mesh_ only)"}},
        "layers": [{"layerId": p["layerId"], "prefabKey": p["key"], "pieces": names(p), "sprites": [],
                    "animated": animated(p)} for p in prefabs[1:]],
        "layerDepths": [],
        "bundleShaders": ["Homm3Conflux/FlowWater", "Homm3Conflux/VfxUber"],
        "animationAudit": fx.get("audit", {}),
        "animationAuditSource": "layers/anims/metadata.json (frame counts = H3sprite.lod DEF frames; frames 1.. are the "
                                "moving patches, whose boxes place the effects)",
        "nearField": {
            "extensionAlbedo": {
                "sources": vanilla_sources(floor_src),
                "paintingRole": f"low-frequency colour only: the rect's edge colour toned out over {G.EDGE_TONE_M} m of "
                                f"world distance (blurred {G.EDGE_BLUR_PX} px) and the strata palettes measured in the "
                                f"painting; texture detail is the vanilla desert set",
                "paintedCrops": False},
            "seamBlend": {"space": "world", "bandM": G.SEAM_BAND_M, "depthSeamPx": G.SEAM_PX,
                          "note": "the synthesis ramps into the rect over a world-distance band from its edge"},
            "texturePieces": [{"name": pc["name"], "texelsPerPx": pc["texelsPerPx"], "frameBox": pc["box"],
                               "tris": pc["tris"]} for pc in rep["terrain"]["pieces"]],
            "buildingsTexelsPerPx": bld_tpp,
            "dressing": rep["nearField"]["dressing"],
            "density": rep["nearField"]["density"],
            "hudBottomPx": int(rep["nearField"]["hudBottomPx"]),
            "assumptions": ["HUD covers the bottom hudBottomPx of the 1080p frame (layout not measured)",
                            "rocks and pebbles are hand-set multiples of the counted scrub density"],
            "meshyCredits": 0},
        "periphery": {**{k: rep["periphery"][k] for k in ("panSource", "vanillaReference", "mesh", "pieces", "water",
                                                          "scatter", "albedo", "registration")}, "meshyCredits": 0},
        "panCoverage": {"file": cov["file"], "sha256": cov["sha256"],
                        "panJson": "tools/homm3_town_scene_meshes/vanilla_city_camera_pan.json",
                        "aspects": list(PAN.ASPECTS)},
        "effectsReport": fx.get("report", {}),
        "vanillaEffectTextures": fx.get("vanillaTextures", {}),
    }
    ssr = rep.get("ssrWater")
    if ssr:
        # opt-in SSR water (town_full3d_ssr_water.py stage, per candidate): the shader joins bundleShaders and the
        # catalog declares that it needs the camera depth texture (validate_town_scene3d_contract refuses an SSR
        # material without it; Homm3TownScene3d enables it while the scene is shown). Re-derived from the stage report
        # on every catalog rewrite, so a later stage cannot silently drop it while the bins still ship.
        env_bins = {b["name"] for b in rows[ENV_KEY]["bins"]}
        lost = [n for n in ssr["pieces"] if n not in env_bins]
        if lost:
            raise SystemExit(f"catalog: stage report ssrWater names {lost} but rows.json no longer stages them "
                             f"(an fx restage drops Fx_ bins): rerun town_full3d_ssr_water.py stage")
        catalog["waterLook"]["screenSpaceReflection"] = {
            "schema": ssr["schema"], "shader": ssr["shader"], "pieces": ssr["pieces"],
            "requiresCameraDepthTexture": bool(ssr["requiresCameraDepthTexture"]),
            "requiresCameraColorTexture": bool(ssr["requiresCameraColorTexture"]),
            "depthSource": ssr["depthSource"], "colorSource": ssr["colorSource"],
            "waterPx": ssr["waterPx"], "bakedReflections": ssr["bakedReflections"],
            "uprightSpriteReflections": ssr["uprightSpriteReflections"], "proofTier": ssr["proofTier"]}
        catalog["bundleShaders"].append(ssr["shader"])
    skyp = rep.get("skyPano")
    if skyp:
        # opt-in continuous sky (town_full3d_sky_continuous.py stage, per candidate): ONE Sky_ piece drawn by the
        # panorama shader; the runtime keeps its bundle material only for the piece skyLook declares, and
        # validate_town_scene3d_contract re-measures sky_continuity.npz. Re-derived from the stage report on every
        # catalog rewrite, so a later stage cannot silently drop it (or re-add a dome) while the panorama ships.
        sky_bins = sorted(b["name"] for b in rows[ENV_KEY]["bins"] if b["name"].startswith("Sky_"))
        if sky_bins != [skyp["piece"]]:
            raise SystemExit(f"catalog: stage report skyPano declares the one sky {skyp['piece']} but rows.json stages "
                             f"Sky_ bins {sky_bins}: rerun town_full3d_sky_continuous.py stage")
        npz = OUT / skyp["file"]
        if not npz.is_file() or hashlib.sha256(npz.read_bytes()).hexdigest() != skyp["sha256"]:
            raise SystemExit(f"catalog: stage report skyPano names {npz} (sha256 {skyp['sha256'][:12]}) but it is "
                             f"missing or differs: rerun town_full3d_sky_continuous.py stage")
        catalog["skyLook"] = {k: skyp[k] for k in ("schema", "shader", "piece", "file", "sha256", "panorama",
                                                   "painting", "limits", "reliefCut", "removed", "driftDegPerSec",
                                                   "proofTier")}
        catalog["environment"]["materials"]["Sky_"] = (f"{skyp['piece']}: bundle material kept ({skyp['shader']}, "
                                                       f"catalog skyLook); no other Sky_ piece")
        catalog["bundleShaders"].append(skyp["shader"])
    ldi = rep.get("ldi")
    if ldi:
        # phase 6b: the layered-depth back-fill (town_full3d_ldi.py apply) cut the terrain's ridge curtains and staged
        # Mesh_Back_* bins; the catalog declares them so validate_town_scene3d_contract re-measures terrain_streak.npz
        npz = OUT / ldi["file"]
        if not npz.is_file() or hashlib.sha256(npz.read_bytes()).hexdigest() != ldi["sha256"]:
            raise SystemExit(f"catalog: stage report ldi names {npz} (sha256 {ldi['sha256'][:12]}) but it is missing or "
                             f"differs: re-run town_full3d_ldi.py apply on a fresh seed")
        catalog["phaseRevision"] = "6b"
        catalog["terrainStreak"] = {
            "file": ldi["file"], "sha256": ldi["sha256"], "ratioCap": ldi["ratioCap"], "cutTris": ldi["cutTris"],
            "smearCutTris": ldi.get("smearCutTris", 0), "backPieces": ldi["backPieces"],
            "frame": ldi["frame"], "method": "town_full3d_ldi.v1 (docs/homm3_town_layered_depth_backfill.md)",
            "proofTier": ldi["proofTier"]}
    import town_full3d_cloth as CL
    cloth = CL.catalog_block(rows, rep)   # opt-in (stage report "cloth", town_full3d_cloth.py apply); None: unchanged
    if cloth is not None:
        catalog["clothLook"] = cloth
        catalog["animationAudit"] = CL.audit_rows(cloth, catalog["animationAudit"])
    import town_full3d_building_depth as BD
    bdepth = BD.catalog_block(STAGE, rows, rep, PREFIX, OUT)   # opt-in contact_v1 pin only (None: no block)
    if bdepth is not None:
        catalog["buildingDepth"] = bdepth
    import town_full3d_framing as FR
    framing = FR.catalog_block()          # profile FRAMING (None: the native rest framing, unchanged)
    if framing is not None:
        catalog["referenceCamera"]["framing"] = framing
    carried = FK.catalog_carry(catalog, previous, carry, owned=CATALOG_OPTIONAL_OWNED, drop=drop)
    if carried:
        print("write_catalog: carried from the previous catalog:", carried, flush=True)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "catalog.json").write_text(json.dumps(catalog, indent=1) + "\n", encoding="utf-8")
    rs = {"cam": {"pos": [float(x) for x in sc.cam["pos"]], "fwd": [float(x) for x in sc.cam["fwd"]],
                  "up": [float(x) for x in sc.cam["up"]], "fov": float(sc.cam["fov"]), "w": W, "h": H},
          "sunDir": [float(x) for x in sc.sun],
          "rig": {k: [float(v) for v in sc.rig[k]] for k in ("sunColor", "ambSky", "ambEq", "ambGround")},
          "fill": {"dir": FILL["dir"], "color": FILL["color"]},
          "states": [{"name": n, "prefabs": [ENV_KEY] + [PREFIX + l for l in ls], "timed": n in ("full", "anim")}
                     for n, ls in STATES.items()],
          "sway": {"lateral": 2.5, "frames": 3}, "timeFrames": TIME_FRAMES,
          "hires": {"w": 3840, "h": 2160, "suffix": "4k", "states": ["full"], "sway": False},
          "outDir": str(RENDERS.resolve()).replace("\\", "/"),
          "panPoses": pan_render_specs() + orbit_render_specs(sc)}
    if cloth is not None:
        rs["cloth"] = CL.render_spec(cloth)
    (WORK / "render_spec.json").write_text(json.dumps(rs, indent=1), encoding="utf-8")
    return catalog


# ------------------------------------------------------------------------------------------------ unity
def copy_editor() -> None:
    """The dedicated project: built-in modules only, the builder script, lab shaders, the delivery shaders."""
    src = HERE / "unity"
    (UNITY_PROJECT / "Packages").mkdir(parents=True, exist_ok=True)
    manifest = {"dependencies": {f"com.unity.modules.{m}": "1.0.0" for m in UNITY_MODULES}}
    (UNITY_PROJECT / "Packages" / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    editor = UNITY_PROJECT / "Assets" / "Editor"
    editor.mkdir(parents=True, exist_ok=True)
    # unlink first: candidates seeded with `cp -al` share these files with their parent, and copy2 writes in place
    (editor / "Homm3TownScene3dBundleBuild.cs").unlink(missing_ok=True)
    shutil.copy2(src / "Homm3TownScene3dBundleBuild.cs", editor / "Homm3TownScene3dBundleBuild.cs")
    lab = UNITY_PROJECT / "Assets" / "Homm3TownLab"
    lab.mkdir(parents=True, exist_ok=True)
    for sh in ("Homm3TownLabHexLit.shader", "Homm3TownLabUnlit.shader"):
        shutil.copy2(src / sh, lab / sh)
    shaders = UNITY_PROJECT / SHADER_DIR
    shaders.mkdir(parents=True, exist_ok=True)
    for sh in ("Homm3ConfluxFlowWater.shader", "Homm3ConfluxVfxUber.shader"):
        shutil.copy2(src / "shaders" / sh, shaders / sh)
    # opt-in delivery shaders: copied only when the candidate's build spec references them, so a town that never
    # staged SSR water builds exactly as before
    spec_path = STAGE / "build_spec.json"
    spec_text = spec_path.read_text(encoding="utf-8") if spec_path.is_file() else ""
    for sh in ("Homm3TownSsrWater.shader", "Homm3TownSkyPanorama.shader", "Homm3TownAurora.shader"):
        if f"{SHADER_DIR}/{sh}" in spec_text:
            shutil.copy2(src / "shaders" / sh, shaders / sh)


def _unity_queue():
    import importlib.util
    spec = importlib.util.spec_from_file_location("unity_queue", SC.ROOT / "tools/unity_queue/unity_queue.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["unity_queue"] = mod  # dataclasses resolve their module through sys.modules
    spec.loader.exec_module(mod)
    return mod


# --unity-direct (main) is the explicit, loudly logged opt-out of the queue; importers never set it.
UNITY_DIRECT = False


def unity(method: str, extra: list[str], log: Path, graphics: bool, output_dir: Path | None = None) -> int:
    """One Unity batch job, submitted to the Unity queue (tools/unity_queue, docs/unity_queue_runner.md): the runner
    batches it with other queued jobs on this candidate's project and runs the game-process / V: space / memgate /
    launch-guard preflight before the launch. The job's slice of the launch log is copied to `log`."""
    copy_editor()
    res = _unity_queue().launch(kind="town_full3d", method=method, args=[str(x) for x in extra], project=UNITY_PROJECT,
                                log=log, inputs=[x for x in extra if Path(x).is_file()], output_dir=output_dir,
                                graphics=graphics, build_target="StandaloneWindows64", unity=UNITY,
                                requester=f"stronghold_full3d_scene {SC.FACTION} {CANDIDATE or 'base'}",
                                direct=UNITY_DIRECT)
    rc = 0 if res["status"] == "ok" else (res.get("exitCode") or 1)
    print("unity", method, "rc", rc, "log", log, "job", res.get("id", "direct"))
    return rc


def bundle() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    # The Unity builder reads build_spec.json; a rows.json edited after the last write_catalog (an effect re-tune, a
    # prop restage) would silently ship the older spec. Refuse instead (fix: rerun the tool's catalog step).
    rows = json.loads(ROWS.read_text(encoding="utf-8"))
    spec = json.loads((STAGE / "build_spec.json").read_text(encoding="utf-8"))
    stale = [p["key"] for p in spec["prefabs"] if p["key"] not in rows
             or p["bins"] != rows[p["key"]]["bins"] or p["particles"] != rows[p["key"]].get("particles", [])]
    if stale:
        raise SystemExit(f"bundle: build_spec.json is older than rows.json for {stale[:6]} ({len(stale)}); rewrite "
                         f"the catalog (e.g. town_t2_anim_pass.py catalog) before bundling")
    rc = unity("Homm3TownScene3dBundleBuild.Run", ["-scene3dSpec", str((STAGE / "build_spec.json").resolve())],
               OUT / "unity_bundle.log", graphics=False, output_dir=OUT)
    if rc:
        return rc
    b = OUT / BUNDLE
    cat = json.loads((OUT / "catalog.json").read_text(encoding="utf-8"))
    cat["bundleBytes"] = b.stat().st_size
    cat["bundleSha256"] = hashlib.sha256(b.read_bytes()).hexdigest()
    cat["proofTier"] = "generated artifact (bundle built offline; editor render and runtime unproven)"
    (OUT / "catalog.json").write_text(json.dumps(cat, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({"bundle": str(b), "bytes": cat["bundleBytes"], "sha256": cat["bundleSha256"]}))
    return 0


def render() -> int:
    spec_path = WORK / "render_spec.json"
    if RENDERS.exists():
        shutil.rmtree(RENDERS)
    RENDERS.mkdir(parents=True)
    rc = unity("Homm3TownScene3dBundleBuild.RenderStates",
               ["-scene3dBundle", str((OUT / BUNDLE).resolve()), "-scene3dRender", str(spec_path.resolve())],
               WORK / "unity_render.log", graphics=True, output_dir=RENDERS)
    if rc == 0:
        cat_path = OUT / "catalog.json"
        cat = json.loads(cat_path.read_text(encoding="utf-8"))
        cat["proofTier"] = "generated artifact (bundle built and editor-rendered offline; runtime unproven)"
        cat_path.write_text(json.dumps(cat, indent=1) + "\n", encoding="utf-8")
    return rc


# ------------------------------------------------------------------------------------------------ review sheets
REVIEW = CAND / "review"
VANILLA_PAN = SC.ROOT / "artifacts" / "homm3_conflux_full3d_phase6" / "work6" / "vanilla_pan"


def homm3_reference(layers: list[str]) -> Image.Image:
    """The HoMM3 town screen for a build state: the original background with those building sprites (positions.json
    z order), at x1.8 in the top-left of the 1920x1080 frame; the rest of the frame is black (HoMM3 has nothing there)."""
    lays = SC.layers()
    bg = SC.background_rgba()
    for L in sorted((lays[l] for l in layers), key=lambda L: L.get("z", 0)):
        bg.alpha_composite(SC.sprite(L), (int(L["x"]), int(L["y"])))
    frame = Image.new("RGB", (W, H), (0, 0, 0))
    frame.paste(bg.convert("RGB").resize((TW, TH), Image.LANCZOS), (0, 0))
    return frame


def review() -> int:
    """One folder of review sheets (+ manifest with sha256) from the editor renders; labels say what each panel is."""
    from PIL import ImageDraw
    if not (RENDERS / "render_report.txt").is_file():
        raise SystemExit("review: no editor renders (run render first)")
    if REVIEW.exists():
        shutil.rmtree(REVIEW)
    REVIEW.mkdir(parents=True)

    def lab(img: Image.Image, text: str) -> Image.Image:
        img = img.convert("RGB")
        d = ImageDraw.Draw(img)
        d.rectangle((0, 0, min(img.width, 14 + 9 * len(text)), 26), fill=(0, 0, 0))
        d.text((6, 6), text, fill=(255, 255, 255))
        return img

    def row(imgs, h=540):
        imgs = [i.resize((round(i.width * h / i.height), h), Image.LANCZOS) for i in imgs]
        out = Image.new("RGB", (sum(i.width for i in imgs) + 8 * (len(imgs) - 1), h), (40, 40, 40))
        x = 0
        for i in imgs:
            out.paste(i, (x, 0))
            x += i.width + 8
        return out

    def col(rows):
        w = max(r.width for r in rows)
        out = Image.new("RGB", (w, sum(r.height for r in rows) + 8 * (len(rows) - 1)), (40, 40, 40))
        y = 0
        for r in rows:
            out.paste(r, (0, y))
            y += r.height + 8
        return out

    def rimg(name):
        p = RENDERS / name
        if not p.is_file():
            raise SystemExit(f"review: render {p.name} missing")
        return Image.open(p)

    sheets = {}
    for st in ("full", "start", "anim"):
        ref = homm3_reference(STATES[st])
        ref.save(REVIEW / f"homm3_{st}.png")
        sheets[f"01_homm3_vs_3d_{st}.png"] = row([lab(ref, f"HoMM3 original ({st}), x1.8 top-left; black = no HoMM3 art"),
                                                  lab(rimg(f"full3d_{st}.png"), f"3D default frame ({st}), editor render")])
    sheets["02_default_4k.png"] = lab(rimg("full3d_full_4k.png"), "3D default frame 3840x2160 (editor render)")
    ts = [f"full3d_anim_t{i}.png" for i in range(len(TIME_FRAMES))]
    sheets["03_effects_time.png"] = col([row([lab(rimg(t), f"effects t={TIME_FRAMES[i]} s") for i, t in enumerate(ts)],
                                             h=420)])
    pans = []
    for base in ("default", "cursor_left", "cursor_right", "sweep_left", "sweep_right", "sweep_high"):
        v = VANILLA_PAN / f"vanilla_{base}.png"
        cells = [lab(rimg(f"pan_{base}.png"), f"{SC.FP.LABEL} 3D pan {base} 16:9")]
        if v.is_file():
            cells.append(lab(Image.open(v), f"vanilla cityHuman2 {base} (Conflux lane moderngl approximation)"))
        pans.append(row(cells, h=400))
    sheets["04_pan_16x9_vs_vanilla.png"] = col(pans)
    for suf, label in (("_4096x2160", "4096x2160"), ("_21x9", "21:9 2560x1080")):
        sheets[f"05_pan_extremes{suf}.png"] = col([row([lab(rimg(f"pan_{b}{suf}.png"), f"{b} {label}")], h=460)
                                                   for b in ("sweep_left", "default", "sweep_right")])
    orbits = [f"pan_orbit_y{y:+d}_p{p:+d}.png" for y, p in ORBITS]
    sheets["06_orbits.png"] = col([row([lab(rimg(o), o[4:-4] + " (review orbit, not a runtime pose)")], h=540)
                                   for o in orbits])
    man = {}
    for name, img in sheets.items():
        img.save(REVIEW / name)
    for p in sorted(REVIEW.glob("*.png")):
        man[p.name] = {"sha256": hashlib.sha256(p.read_bytes()).hexdigest(), "bytes": p.stat().st_size}
    for p in sorted(RENDERS.glob("*.png")):
        man["renders/" + p.name] = {"sha256": hashlib.sha256(p.read_bytes()).hexdigest(), "bytes": p.stat().st_size}
    (REVIEW / "manifest.json").write_text(json.dumps({"proofTier": "generated artifact (editor renders; not in-game)",
                                                      "renders": str(RENDERS), "files": man}, indent=1), encoding="utf-8")
    print(json.dumps({k: v["sha256"][:12] for k, v in man.items() if "/" not in k}, indent=1))
    return 0


def see_through_report(sc: Scene) -> dict:
    """Building px the game's back-face culling drops (town_full3d_cull) for the full state at the rest pose, the render
    sway, the vanilla pan proof poses and the review orbits, plus the no-worse-than-baseline gate verdict."""
    import town_full3d_cull as CULL
    full = {ENV_KEY} | {PREFIX + l for l in STATES["full"]}
    load_staged_preview(sc, full)
    pieces = [(name, P, n, uv, tris) for name, P, n, uv, tris, _img, _unlit in sc.preview]
    cams = {"rest": sc.cam}
    for lat in (-2.5, 2.5):
        cams[f"sway{lat:+g}"] = {**sc.cam, "pos": np.asarray(sc.cam["pos"]) + np.asarray(sc.cam["right"]) * lat / sc.scale}
    cams.update({f"pan_{k}": v for k, v in pan_cams(sc).items()})
    cams.update({f"orbit_y{y:+d}_p{p:+d}": orbit_cam(sc, y, p) for y, p in ORBITS})
    poses = CULL.see_through(pieces, cams, W, H, 2.0, T.DOME_R * 1.2)
    verdict = CULL.gate(SC.FACTION, poses)
    return {"metric": "building px lost to Unity Cull Back (offline id render, generated artifact)",
            "poses": poses, "totalPx": sum(v["seeThroughPx"] for v in poses.values()), **verdict}


def cull_gate_or_exit(rep: dict) -> None:
    if rep["worse"]:
        raise SystemExit(f"see-through gate: worse than baseline {rep['baseline']} at "
                         + ", ".join(f"{p} {b} -> {m}" for p, (b, m) in rep["worse"].items()))


def candidate_init(seed_from: str = "") -> int:
    """Seed candidates/<name>/ from the base outputs: the Unity project (staged env / fx / building bins, Library) and
    the stage report. Refuses to overwrite an existing candidate (delete it deliberately first)."""
    if not CANDIDATE:
        raise SystemExit("candidate-init: set TOWN_FULL3D_CANDIDATE=<name>")
    if CAND.exists():
        raise SystemExit(f"candidate-init: {CAND} exists")
    base = SC.DATA / "candidates" / seed_from if seed_from else SC.DATA
    if not (base / "unity_project").is_dir():
        raise SystemExit(f"candidate-init: no unity_project under {base}")
    shutil.copytree(base / "unity_project", UNITY_PROJECT, ignore=shutil.ignore_patterns("Temp", "Logs", "*.csproj",
                                                                                         "*.sln"))
    # the copied build spec still names the seed's bundle folder: a `bundle` run would overwrite the seed's bundle
    spec_p = STAGE / "build_spec.json"
    if spec_p.is_file():
        spec = json.loads(spec_p.read_text(encoding="utf-8"))
        spec["outputPath"] = str(OUT.resolve()).replace("\\", "/")
        spec_p.write_text(json.dumps(spec, indent=1), encoding="utf-8")
    WORK.mkdir(parents=True)
    shutil.copy2(base / "work" / "stage_report.json", WORK / "stage_report.json")
    OUT.mkdir(parents=True)
    shutil.copy2(base / "bundle" / "pan_coverage.npz", OUT / "pan_coverage.npz")
    # the seed's own review (per-layer metrics / sheets) is not copied: each candidate is reviewed against its seed.
    # Its pins (building depth / seams, prop placement, closing walls) and its catalog blocks are, fail-closed
    # (town_full3d_fork.py): without them a fork silently drops its seed's buildingDepth and props blocks
    import town_full3d_fork as FK
    fork = FK.fork_seed_state(base, WORK, OUT) if seed_from else {}
    print(json.dumps({"candidate": str(CAND), "seededFrom": str(base), **fork}))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["candidate-init", "stage", "preview", "catalog", "bundle", "render", "review",
                                    "validate", "cull"])
    ap.add_argument("--faction", default=SC.FACTION,
                    help="town_full3d_factions/<key>.py (default stronghold); read before any module import")
    ap.add_argument("--only", default="")
    ap.add_argument("--cams", default="default", choices=["default", "pan", "orbit", "all"])
    ap.add_argument("--parts", default="terrain,sky,buildings,periphery,nearfield,fx")
    ap.add_argument("--building-method", default="relief", choices=["relief", "solid", "solid_parts"],
                    help="relief: the installed extrude-to-flat-back shells; solid: ground/upright split + width-driven "
                         "closed volumes; solid_parts: solid with part separation at depth steps on the layers in "
                         "stronghold_full3d_solids.PARTS_LAYERS (docs/homm3_town_depth_building_solids.md)")
    ap.add_argument("--back-fill", action="store_true",
                    help="solid methods: edge-filled back texture on the layers in "
                         "stronghold_full3d_solids.BACK_FILL_LAYERS")
    ap.add_argument("--carry", default="fresh", choices=["fresh", "previous"],
                    help="stage / catalog: how the rewritten catalog meets the previous one (town_full3d_fork."
                         "catalog_carry): fresh refuses to drop another lane's block (props, houses), previous "
                         "carries them")
    ap.add_argument("--seed-from", default="",
                    help="candidate-init: seed from candidates/<name> instead of the base outputs")
    ap.add_argument("--unity-direct", action="store_true",
                    help="bundle/render: launch Unity directly instead of submitting to the Unity queue (explicit, "
                         "logged opt-out; docs/unity_queue_runner.md)")
    args = ap.parse_args()
    global UNITY_DIRECT
    UNITY_DIRECT = args.unity_direct
    if args.cmd == "candidate-init":
        return candidate_init(args.seed_from)
    if args.cmd == "preview":
        sc = Scene()
        only = [x for x in args.only.split(",") if x] or None
        load_staged_preview(sc, only)
        cams = {"default": sc.cam}
        if args.cams in ("pan", "all"):
            cams.update(pan_cams(sc))
        if args.cams in ("orbit", "all"):
            cams.update({f"orbit_{y:+d}": orbit_cam(sc, y) for y in (-35, -15, 15, 35)})
        print(preview(sc, WORK / "preview", cams))
        return 0
    if args.cmd == "catalog":
        sc = Scene()
        cat = write_catalog(sc, carry=args.carry)
        print("catalog", OUT / "catalog.json", "layers", len(cat["layers"]), "env", len(cat["environment"]["pieces"]))
        return 0
    if args.cmd == "bundle":
        return bundle()
    if args.cmd == "render":
        return render()
    if args.cmd == "review":
        return review()
    if args.cmd == "cull":
        # the see-through metric on an already staged candidate (work/see_through.json; exits non-zero when worse)
        rep = see_through_report(Scene())
        (WORK / "see_through.json").write_text(json.dumps(rep, indent=1), encoding="utf-8")
        print(json.dumps({k: rep[k] for k in ("totalPx", "mode", "baseline", "worse")}))
        cull_gate_or_exit(rep)
        return 0
    if args.cmd == "validate":
        import subprocess
        return subprocess.run([sys.executable, str(SC.ROOT / "tools" / "validate_town_scene3d_contract.py"),
                               "--catalog", str(OUT / "catalog.json")]).returncode
    if args.cmd == "stage":
        import stronghold_full3d_buildings as BL
        sc = Scene()
        parts = set(args.parts.split(","))
        if "terrain" in parts:
            print(json.dumps(stage_terrain(sc), indent=1)[:3000])
        if "sky" in parts:
            print(json.dumps(stage_sky(sc)))
        if "buildings" in parts:
            rd = sc.terrain["rd"] if hasattr(sc, "terrain") else T.rect_depth(sc.cam)
            only = [x for x in args.only.split(",") if x] or None
            BL.stage_buildings(sc, rd, PREFIX, only, method=args.building_method, back_fill=args.back_fill)
        if "periphery" in parts:
            import stronghold_full3d_periphery as PP
            res = PP.build(sc, PREFIX + "environment", terrain_state(sc), OUT, T.DOME_R, SKY_AZ, SKY_EL)
            sc.report["periphery"] = res["periphery"]
            sc.report["panCoverage"] = res["coverage"]
            print(json.dumps({k: v for k, v in res["periphery"].items() if k != "pieces"}, indent=1)[:4000])
        if "nearfield" in parts:
            import stronghold_full3d_nearfield as NF
            sc.report["nearField"] = NF.build(sc, PREFIX + "environment", terrain_state(sc))
            print(json.dumps(sc.report["nearField"], indent=1)[:3000])
        fx_rows = None
        if "fx" in parts and SC.FP.FX_MODULE is None:
            print("fx: profile FX_MODULE is None (no animated-building effects module); fx part skipped")
        elif "fx" in parts:
            import importlib
            FX = importlib.import_module(SC.FP.FX_MODULE)
            spec_l, sky_c, rd = water_light(sc)
            res = FX.stage(sc, rd, spec_l, sky_c)
            fx_rows = res["rows"]
            sc.report["fx"] = {k: res[k] for k in ("audit", "report", "vanillaTextures")}
        save_rows(sc, fx_rows, PREFIX + "environment" if "periphery" in parts else None)
        rp = WORK / "stage_report.json"
        old = json.loads(rp.read_text(encoding="utf-8")) if rp.is_file() else {}
        if args.only and "buildings" in sc.report and isinstance(old.get("buildings"), dict):
            sc.report["buildings"] = {**old["buildings"], **sc.report["buildings"]}
        old.update(json.loads(json.dumps(sc.report, default=lambda o: o.tolist() if hasattr(o, "tolist") else str(o))))
        rp.write_text(json.dumps(old, indent=1), encoding="utf-8")
        if "buildings" in parts:
            wf = WORK / "closing_walls.npz"
            edges = dict(np.load(wf)) if (args.only and wf.is_file()) else {}
            edges.update(sc.wall_edges)
            np.savez(wf, **edges)
        write_catalog(sc, carry=args.carry)
        load_staged_preview(sc)
        shots = preview(sc, WORK / "preview")
        print(shots)
        if "buildings" in parts:
            # stage-path gate: a building stage may not see through more than the installed baseline at any pose
            rep = see_through_report(sc)
            (WORK / "see_through.json").write_text(json.dumps(rep, indent=1), encoding="utf-8")
            old = json.loads(rp.read_text(encoding="utf-8"))
            old["seeThrough"] = {k: rep[k] for k in ("metric", "totalPx", "mode", "baseline", "worse")}
            rp.write_text(json.dumps(old, indent=1), encoding="utf-8")
            print(json.dumps({"seeThrough": old["seeThrough"]}))
            cull_gate_or_exit(rep)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
