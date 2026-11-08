#!/usr/bin/env python3
"""Conflux town screen as a COMPLETE 3D scene: terrain, water, sky, vegetation, every building level, effects.

    python tools/homm3_town_scene_meshes/build_conflux_full3d_scene.py stage    # python: all geometry + textures + spec
    python tools/homm3_town_scene_meshes/build_conflux_full3d_scene.py bundle   # Unity job via the Unity queue: build the bundle
    python tools/homm3_town_scene_meshes/build_conflux_full3d_scene.py render   # Unity job via the Unity queue: state renders
    python tools/homm3_town_scene_meshes/build_conflux_full3d_scene.py report   # sheets vs HoMM3, catalog sha

Doc: docs/homm3_conflux_full_3d_town.md. Inventory: conflux_full3d_inventory.json (same folder).

Phase 2 (2026-09-27 user review). The ONLY references are the original HoMM3 Conflux town screen
(Conflux-in-background.png) and the HoMM3 building art (layers/*.png). The old runtime 2D backdrop, its outpaint and
every derivative of them (the 4k plate, conflux_plate_z.npy, conflux_composite_z.npy, the 1920 reference) are not
read. The environment is conflux_full3d_env.py; building footing is conflux_full3d_integration.py.

  * Mesh_Terrain   lit grid over the whole 16:9 frame. HoMM3 rect: Depth Anything V2 depth of the original,
                   calibrated to the registered buildings; extension: a ray-marched world heightmap (procedural right
                   valley wall, rivers carried on toward the camera), silhouette vertices snapped to the ridge line.
                   Albedo = the painting at full sharpness / Hex/Lit (HoMM3 rect), world-space crops of the painting
                   (extension), feathered and tone-matched across the seams.
  * Fx_Water       rivers / pond / waterfall, a bone-less SkinnedMeshRenderer with Homm3Conflux/FlowWater: UV1 =
                   (across, geodesic metres downstream from each river's mountain source), so the ripples run down
                   every river toward the camera.
  * Sky_Dome       camera-centred sphere cap from the painted HoMM3 sky (mirror-filled, no blur).
  * Mesh_Scatter_* Meshy conifers, bushes, boulders (stored once, one child per instance).
  * buildings      the registered meshes of the scene3d lane plus the new dwellings (tbeldw_1 air shrine refit to
                   face the camera, tbeldw_4 earth ring), mushrooms, and per layer a Mesh_Skirt_<layer>: the sprite's
                   painted footing (ledges, stairs, plinth, path) as a lit membrane from the building's foot to the
                   terrain, so no building floats or shows a cut base.
  * effects        (vanilla Olden Era style, the VfxUber replica on ParticleSystems; no ripped flipbooks)
                     tbeldw_6 pyre: base flames, a stretched flame column, a swirling fire cloud, violet smoke plumes,
                                    glows and embers over a Mesh_ rock anchor;
                     tbeldw_3 fire pit: the crater as a whole-sprite footing membrane, its painted lava animated by
                                    Homm3Conflux/Lava, flames / smoke / embers / glow;
                     tbeldw_5 portal: Homm3Conflux/Portal (differential spiral) instead of a rigidly spun disc;
                     tbelholy grail: moving aurora curtains (Homm3Conflux/Aurora) over a Mesh_ cairn anchor.
                   ParticleSystems and SkinnedMeshRenderers keep their bundle materials (the town runtime re-materials
                   MeshRenderers only), prewarm, loop and play on awake, so they also play in previews.
Everything is written in the reference camera frame, scaled by DEPTH_SCALE. The bundle is built in a dedicated
built-in-pipeline Unity project under the data root (default F:/homm3_conflux_full3d, CONFLUX_FULL3D_ROOT).
Unity runs only as jobs submitted to the Unity queue (tools/unity_queue; preflight incl. memgate). Nothing is deployed.
Proof tier: generated artifact / Unity-editor render. Not in-game.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_conflux_town3d_preview as B  # noqa: E402
import build_town_scene3d_bundle as S  # noqa: E402
import conflux_full3d_detail as D  # noqa: E402
import conflux_full3d_env as E  # noqa: E402
import conflux_full3d_integration as I  # noqa: E402
import conflux_full3d_nearfield as N5  # noqa: E402
import conflux_full3d_periphery as P6  # noqa: E402
import conflux_full3d_curtain as CU  # noqa: E402
import conflux_town_camera_pan as PAN  # noqa: E402
from fit_mesh_to_sprite import Fitter, load_glb_unity, yaw_matrix  # noqa: E402

ROOT = B.ROOT
DATA = Path(os.environ.get("CONFLUX_FULL3D_ROOT", "F:/homm3_conflux_full3d"))
# A new build root can reuse the read-only texture extracts without copying the prior Unity project or bundle.
SOURCE_DATA = Path(os.environ.get("CONFLUX_FULL3D_SOURCE_ROOT", str(DATA)))
WORK = DATA / "work2"
OUT = DATA / "bundle"
RENDERS = DATA / "renders"
PHASE1 = DATA / "phase1"
VANILLA_TEX = SOURCE_DATA / "vanilla_recipes" / "tex"
DETAIL_CACHE = SOURCE_DATA / "vanilla_terrain"  # phase 3: game terrain textures (read-only UnityPy extract)
# Close-up windows (frame px) for the phase-3 density check and sheets: the fort and the Altar of Air.
CLOSEUP_WINDOWS = {"fort": (600, 170, 1300, 470), "altar_of_air": (1040, 30, 1440, 300),
                   "near_field": (0, 760, 1920, 1016), "right_edge": (1600, 300, 1920, 760)}
PROJECT = DATA / "unity_project"
ASSET_ROOT = "Assets/Homm3TownScene3d/conflux_full3d"
IN_DIR = PROJECT / ASSET_ROOT
SHADER_DIR = "Assets/Homm3Conflux/Shaders"
UNITY_MODULES = ["animation", "assetbundle", "imageconversion", "imgui", "jsonserialize", "ui", "uielements",
                 "physics", "unitywebrequest", "particlesystem"]
BUNDLE = S.BUNDLE  # same bundle name: the candidate replaces the staged one when the coordinator installs it
REST_POSE_CATALOG_SCHEMA = "homm3_town_scene3d_catalog.v2"
PREFIX = "homm3_conflux3d_"
ENV_KEY = PREFIX + "environment"
MESHY = B.MESHY
W, H = B.W, B.H
TW, TH = B.TOWN_W, B.TOWN_H
GRID = 3                  # terrain grid step, frame px
SKY_Z = B.Z_FAR - 0.5
DOME_R = 185.0            # raw (pre-depthScale) sky dome radius: behind the farthest terrain
SEED = 20260926
# The phase-1 prefab-frame scale, kept so every registered building keeps its transform (and the runtime its far
# clip). Phase 1 derived it from the old composite depth; phase 2 no longer reads that file, so it is a constant.
DEPTH_SCALE = 0.5260094536051652

SKY, GRASS, FOREST, ROCK, SNOW, DIRT, WATER = range(7)

# New registrations (phase 1 fits; tbeldw_1 refit: the phase-1 fit faced the shrine's back to the camera, the
# facing audit of 2026-09-27 put its front at yaw ~180 against the HoMM3 art; every other building faced correctly).
NEW_FITS = {
    "tbeldw_1": {"mesh": "tbeldw_1", "yaws": list(range(150, 211, 5))},
    "tbeldw_4": {"mesh": "tbeldw_4"},
}
SHARED = {"tbeldw_1_2": "tbeldw_1", "tbeldw_4_2": "tbeldw_4"}
LAVA_LAYERS = ("tbeldw_3", "tbeldw_3_2")      # the fire pit: whole-sprite crater + animated lava, no Meshy plateau
PYRE_LAYERS = ("tbeldw_6", "tbeldw_6_2")
WATER_SPEC_EL = 22.0   # deg: elevation of the rivers' fixed specular light over the far side of the scene
# Phase 3b: the frame-registered terrain/footing bakes hold 2 texels per 1080p pixel, so plain trilinear sampling sits
# on mip 1 everywhere and averages away the detail the bake carries; a -1 bias samples mip 0 (bilinear, prefiltered
# bake), anisotropic filtering keeps the grazing near field sharp. Both serialize with the texture (runtime-safe).
TERRAIN_MIP_BIAS = -1.0
TERRAIN_ANISO = 8
LEDGE_LAYERS = ("tbeldw_1", "tbeldw_1_2")     # the Altar of Air: its slab gets a snow ledge down to the mountain
SKY_FX_LAYERS = PYRE_LAYERS + ("tbelholy",)   # no footing skirt: their sprites are sky and far peaks
MUSHROOM_LAYERS = ("tbeldw_0_2", "tbelhrd2")
STATES = {
    "start": ["tbelhall", "tbeldw_0", "tbeldw_1"],
    "mid": ["tbelhall_2", "tbelcstl", "tbelmage_2", "tbeltvrn", "tbelmark", "tbelsilo", "tbeldw_0_2", "tbeldw_1",
            "tbeldw_2", "tbeldw_3", "tbeldw_5"],
    "full": ["tbelhall_4", "tbelcstl_3", "tbelmage_4", "tbeltvrn", "tbelblak", "tbelmark", "tbelsilo", "tbelspec",
             "tbeldock", "tbelhrd2", "tbeldw_0_2", "tbeldw_1_2", "tbeldw_2_2", "tbeldw_3_2", "tbeldw_4_2",
             "tbeldw_5_2", "tbeldw_6_2", "tbelholy"],
}
TIME_FRAMES = [0.0, 1.0]  # editor render times (phase 4: t=0 and t=1 s) for the motion proof (flow, lava, aurora, portal, particles)


# ------------------------------------------------------------------------------------------------ helpers
srgb_to_lin, lin_to_srgb, lum, light, rays, project = E.srgb_to_lin, E.lin_to_srgb, E.lum, E.light, E.rays, E.project


def write_bin(path: Path, v, n, uv, subs) -> None:
    S.write_grid(path, np.asarray(v, np.float64), np.asarray(n, np.float32), np.asarray(uv, np.float32),
                 [np.asarray(s, np.int32).ravel() for s in subs])


class Ctx:
    def __init__(self):
        self.cam = B.camera()
        self.C, self.cpos = S.cam_basis(self.cam)
        bake = json.loads((B.WORK / "materials" / "bake_report.json").read_text(encoding="utf-8"))
        self.bake = bake
        self.rig = bake["rig"]
        self.sun = np.asarray(bake["keyLight"]["sunDir"], np.float32)
        self.spec = json.loads((B.WORK / "preview_spec.json").read_text(encoding="utf-8"))
        self.layers = {l["id"]: l for l in json.loads((B.REFS / "layers" / "positions.json").read_text())["layers"]}
        self.scale = DEPTH_SCALE
        self.rng = np.random.default_rng(SEED)
        self.z = None
        self.paint = None

    def set_env(self, fd: dict) -> None:
        """Depth for placement (sky = Z_FAR, the Fitter's convention) and the painting in frame layout."""
        self.z = np.where(np.isnan(fd["zs"]), B.Z_FAR, fd["zs"]).astype(np.float64)
        p = np.zeros((H, W, 3), np.uint8)
        p[:TH, :TW] = fd["paint"]
        self.paint = p

    def local(self, w):
        return ((np.asarray(w, np.float64) - self.cpos) @ self.C) * self.scale

    def local_dir(self, d):
        return np.asarray(d, np.float64) @ self.C

    def world_quat(self) -> list[float]:
        """Rotation of a holder whose local axes are the world axes, in the prefab (camera) frame."""
        return [float(x) for x in S.mat_to_quat(self.C.T)]

    def world_at(self, px, py, zmap=None):
        zmap = self.z if zmap is None else zmap
        xi = np.clip(np.round(px).astype(int), 0, W - 1)
        yi = np.clip(np.round(py).astype(int), 0, H - 1)
        return self.cpos + rays(self.cam, np.asarray(px, np.float64), np.asarray(py, np.float64)) * zmap[yi, xi][..., None]

    def m_per_px(self, zc: float) -> float:
        return 2 * zc * math.tan(math.radians(self.cam["fov"]) / 2) / H


# ------------------------------------------------------------------------------------------- classification
def classify(ctx: Ctx, fd: dict, cls_f: np.ndarray) -> np.ndarray:
    """Terrain classes for scatter: colour rules on the painting (HoMM3 rect), the albedo classes (extension)."""
    img = cv2.GaussianBlur(fd["paint"], (0, 0), 1.5)
    hsv = cv2.cvtColor(img, cv2.COLOR_RGB2HSV).astype(np.float32)
    h, s, v = hsv[..., 0] * 2, hsv[..., 1] / 255, hsv[..., 2]
    c = np.full((TH, TW), GRASS, np.uint8)
    green = (h >= 55) & (h <= 170) & (s > 0.18)
    c[green & (v < 72)] = FOREST
    rocky = (s < 0.30) | ((h < 50) & (v < 150))
    c[rocky & ~green] = ROCK
    c[(v > 165) & (s < 0.20)] = SNOW
    c[(h >= 18) & (h <= 45) & (s > 0.28) & (v > 120)] = DIRT
    c[(c == SNOW) & (np.arange(TH)[:, None] > 0.40 * H)] = GRASS
    cls = np.full((H, W), GRASS, np.uint8)
    cls[:TH, :TW] = c
    ext = cls_f != 255
    cls[ext] = np.array([GRASS, FOREST, ROCK, SNOW], np.uint8)[cls_f[ext]]
    one = np.stack([cv2.blur((cls == k).astype(np.float32), (7, 7)) for k in range(7)], 0)
    cls = one.argmax(0).astype(np.uint8)
    cls[fd["water"]] = WATER
    cls[np.isnan(fd["zs"])] = SKY
    return cls


# ------------------------------------------------------------------------------------------------ meshes
def load_glb_full(glb: Path):
    """Unity-frame vertices/normals/uv/faces of a Meshy GLB (x negated as glTFast does; winding reversed)."""
    import trimesh

    scene = trimesh.load(str(glb), force="scene")
    m = scene.dump(concatenate=True)
    v = np.asarray(m.vertices, np.float64).copy()
    n = np.asarray(m.vertex_normals, np.float64).copy()
    v[:, 0] *= -1
    n[:, 0] *= -1
    uv = np.asarray(m.visual.uv, np.float64).copy() if getattr(m.visual, "uv", None) is not None else np.zeros((len(v), 2))
    f = np.asarray(m.faces, np.int64)[:, ::-1].copy()
    return v, n, uv, f


def decimate(v, n, uv, f, target_tris: int):
    """Quadric decimation that keeps the surface closed and every triangle inside one UV chart.

    Phase 5: the old version simplified the GLB as exported (vertices duplicated along UV seams, so every seam was an
    open boundary the simplifier tore apart) and gave each new vertex the UV of its nearest source vertex, so
    triangles spanning two charts sampled across the atlas: at 900 triangles the bushes and boulders rendered as
    shattered shards. Now: weld by position, simplify, then per output triangle take the nearest source triangle and
    carry its UVs by barycentric projection of the three corners (corners unshared, so no chart mixing)."""
    import fast_simplification
    from scipy.spatial import cKDTree

    if len(f) <= target_tris:
        return v, n, uv, f
    key = np.round(v / (np.ptp(v, 0).max() * 1e-6 + 1e-12)).astype(np.int64)
    _, first, inv = np.unique(key, axis=0, return_index=True, return_inverse=True)
    vw = v[first]
    fw = inv.reshape(-1)[f]
    fw = fw[(fw[:, 0] != fw[:, 1]) & (fw[:, 1] != fw[:, 2]) & (fw[:, 0] != fw[:, 2])]
    v2, f2 = fast_simplification.simplify(vw.astype(np.float32), fw.astype(np.int32), 1 - target_tris / len(fw))
    v2 = v2.astype(np.float64)
    f2 = f2.astype(np.int64)
    cen = v[f].mean(1)
    _, near_f = cKDTree(cen).query(v2[f2].mean(1))
    src = f[near_f]                                    # (m, 3) source triangle per output triangle
    a, b_, c = v[src[:, 0]], v[src[:, 1]], v[src[:, 2]]
    e0, e1 = b_ - a, c - a
    d00, d01, d11 = (e0 * e0).sum(-1), (e0 * e1).sum(-1), (e1 * e1).sum(-1)
    den = np.where(np.abs(d00 * d11 - d01 * d01) < 1e-18, 1e-18, d00 * d11 - d01 * d01)
    out_v = v2[f2].reshape(-1, 3)
    rep = np.repeat(np.arange(len(f2)), 3)
    p = out_v - a[rep]
    d20, d21 = (p * e0[rep]).sum(-1), (p * e1[rep]).sum(-1)
    bv = np.clip((d11[rep] * d20 - d01[rep] * d21) / den[rep], -0.25, 1.25)
    bw = np.clip((d00[rep] * d21 - d01[rep] * d20) / den[rep], -0.25, 1.25)
    ua, ub, uc = uv[src[:, 0]][rep], uv[src[:, 1]][rep], uv[src[:, 2]][rep]
    out_uv = ua + (ub - ua) * bv[:, None] + (uc - ua) * bw[:, None]
    _, vi = cKDTree(v).query(out_v)
    return out_v, n[vi], out_uv, np.arange(len(out_v)).reshape(-1, 3)


def texture_transfer(tex_srgb: np.ndarray, ref_pixels: np.ndarray | None, gain_target: float | None,
                     rig, sun, normals: np.ndarray) -> np.ndarray:
    """Baked prop albedo: Lab mean/std transfer toward the painted pixels it stands for, then divided by the mean
    Hex/Lit irradiance of its camera-facing normals (the painted colours are lit colours)."""
    from skimage.color import lab2rgb, rgb2lab

    t = tex_srgb.astype(np.float32) / 255
    if ref_pixels is not None and len(ref_pixels) > 50:
        a = rgb2lab(t)
        rl = rgb2lab(ref_pixels.reshape(-1, 1, 3).astype(np.float32) / 255).reshape(-1, 3)
        am, asd = a.reshape(-1, 3).mean(0), a.reshape(-1, 3).std(0) + 1e-3
        rm, rsd = rl.mean(0), rl.std(0) + 1e-3
        k = np.clip(rsd / asd, 0.6, 1.4)
        a = (a - am) * k + am * 0.35 + rm * 0.65
        t = np.clip(lab2rgb(a), 0, 1).astype(np.float32)
    lin = srgb_to_lin(t)
    L = float(np.mean(lum(light(normals.astype(np.float32), rig, sun))))
    lin = lin / max(L, 1e-3)
    if gain_target is not None:
        lin *= gain_target
    mx = lin.max(-1, keepdims=True)
    lin = np.where(mx > 0.95, lin * 0.95 / np.maximum(mx, 1e-6), lin)
    return (lin_to_srgb(lin) * 255 + 0.5).astype(np.uint8)


def base_color(mesh: str, size: int = 1024) -> np.ndarray:
    im = Image.open(MESHY / mesh / B.MESH_ATTEMPT / "texture_0_base_color.png")
    im.draft("RGB", (size, size))
    return np.asarray(im.convert("RGB").resize((size, size), Image.LANCZOS))


# ---------------------------------------------------------------------------------------- registration
def sprite_alpha(ctx: Ctx, layer: str) -> np.ndarray:
    return B.layer_frame(ctx.layers[layer])


def fit_new(ctx: Ctx, layer: str, mesh: str, target: np.ndarray, yaws=None) -> dict:
    cache_p = WORK / "fits.json"
    cache = json.loads(cache_p.read_text(encoding="utf-8")) if cache_p.is_file() else {}
    glb = MESHY / mesh / B.MESH_ATTEMPT / "model.glb"
    key = (f"{layer}|{mesh}|{hashlib.sha1(glb.read_bytes()).hexdigest()[:12]}|{hashlib.sha1(target.tobytes()).hexdigest()[:12]}"
           f"|{hashlib.sha1(ctx.z.astype(np.float32).tobytes()).hexdigest()[:12]}|{yaws}")
    verts, faces = load_glb_unity(glb)
    if key in cache:
        return cache[key]
    fitter = Fitter(ctx.cam, ctx.z, (W, H), target, verts, faces, down=2)
    ys, xs = np.nonzero(target)
    bbox = (xs.min(), ys.min(), xs.max() + 1, ys.max() + 1)
    r = fitter.fit(bbox, **({"yaws": yaws} if yaws is not None else {}))
    lo, hi = verts.min(0), verts.max(0)
    c = np.array([(lo[0] + hi[0]) / 2, lo[1], (lo[2] + hi[2]) / 2])
    root = np.array(r["position"]) - yaw_matrix(r["yaw"]) @ (c * r["scale"])
    row = {k: v for k, v in r.items() if k != "silhouette"}
    row["rootPosition"] = root.tolist()
    row["layer"], row["mesh"] = layer, mesh
    cache[key] = row
    cache_p.parent.mkdir(parents=True, exist_ok=True)
    cache_p.write_text(json.dumps(cache, indent=1), encoding="utf-8")
    return row


_GLB_CACHE: dict = {}


def piece_row(ctx: Ctx, name: str, mesh: str, texture_rel: str, root, yaw, scale, stretch=1.0, knee_y=0.0,
              knee_s=0.0, rot: np.ndarray | None = None) -> dict:
    """A registered mesh baked into the prefab frame (glTF root frame, spire knee, vertical stretch, then
    root + R * (scale * v)), written as a Mesh_ bin. `_world` / `_faces` feed the footing skirt (popped later)."""
    if mesh not in _GLB_CACHE:
        _GLB_CACHE[mesh] = load_glb_full(MESHY / mesh / B.MESH_ATTEMPT / "model.glb")
    v, n, uv, f = (a.copy() for a in _GLB_CACHE[mesh])
    if 0 < knee_s < 1:
        hi = v[:, 1] > knee_y
        v[hi, 1] = knee_y + (v[hi, 1] - knee_y) * knee_s
        n[hi, 1] /= knee_s
    k = stretch if stretch > 0 else 1.0
    v[:, 1] *= k
    n[:, 1] /= k
    R = yaw_matrix(yaw) if rot is None else rot
    w = np.asarray(root) + (v * scale) @ R.T
    nl = (n @ R.T) @ ctx.C
    nl /= np.linalg.norm(nl, axis=1, keepdims=True) + 1e-12
    bname = "Mesh_" + name
    write_bin(IN_DIR / f"{bname}.bytes", ctx.local(w), nl, uv, [f])
    return {"name": bname, "mesh": f"{ASSET_ROOT}/{bname}.bytes", "texture": f"{ASSET_ROOT}/{texture_rel}",
            "kind": "lit", "maxSize": 1024, "_world": w, "_faces": f, "_uv": uv}


def place_xform(ctx: Ctx, world_base, yaw_deg: float, s: float) -> list[float]:
    """Instance transform in the prefab (camera) frame: pos3 + quat4 + uniform scale."""
    lp = ctx.C.T @ (np.asarray(world_base) - ctx.cpos) * ctx.scale
    q = S.mat_to_quat(ctx.C.T @ yaw_matrix(yaw_deg))
    return [float(x) for x in lp] + [float(x) for x in q] + [float(s * ctx.scale)]


# ------------------------------------------------------------------------------------------------ scatter
def exclusion_mask(ctx: Ctx) -> np.ndarray:
    """Union of every reachable building layer's sprite alpha (all levels): no prop may stand on a plot."""
    lm = json.loads((B.REFS / "layers" / "building_layer_map.json").read_text(encoding="utf-8-sig"))
    reach = {v for lv in lm["nativeLevels"].values() if isinstance(lv, dict) for v in lv.values()}
    m = np.zeros((H, W), bool)
    for lid in reach:
        if lid in SKY_FX_LAYERS:
            continue
        m |= B.layer_frame(ctx.layers[lid])[..., 3] > 40
    return cv2.dilate(m.astype(np.uint8), np.ones((15, 15), np.uint8)).astype(bool)


# Phase 3b: the bottom-right meadow extension (HoMM3 has no pixels there) gets HoMM3-style dressing: conifer groves
# framing the right edge, boulders along the river banks (no round bushes). The props are near the camera (9-20 m), so they
# use a finer decimation than the far scatter.
MEADOW_BOX = (1250, 690, 1920, 1080)   # frame px
MEADOW_PROPS = {
    "prop_conifer_a": {"where": "grove", "spacing": 1.0, "cap": 9, "h": (2.6, 3.8), "tris": 5000, "z": (8.0, 30.0)},
    "prop_conifer_b": {"where": "grove", "spacing": 0.9, "cap": 7, "h": (2.2, 3.2), "tris": 5000, "z": (8.0, 30.0)},
    "prop_boulders": {"where": "bank", "spacing": 1.6, "cap": 9, "h": (0.35, 0.8), "tris": 4000, "z": (9.0, 20.0)},
}


def meadow_dressing(ctx: Ctx, env: dict, zsf, ground_ok, flatish, water, town, taken: list) -> dict:
    x0, y0, x1, y1 = MEADOW_BOX
    box = np.zeros((H, W), bool)
    box[y0:y1, x0:x1] = True
    base = box & ~town & ground_ok & flatish
    sub = np.zeros((H, W), bool)
    sub[::2, ::2] = True
    bank = cv2.dilate(water.astype(np.uint8), np.ones((45, 45), np.uint8)).astype(bool)
    # Groves: soft blobs toward the right edge, away from the river (no round bushes: they read as green balls).
    gy, gx = np.mgrid[0:H, 0:W]
    grove = np.zeros((H, W), bool)
    for cx, cy, rx, ry in ((1840, 760, 110, 55), (1690, 705, 80, 35), (1880, 930, 60, 120)):
        grove |= ((gx - cx) / rx) ** 2 + ((gy - cy) / ry) ** 2 < 1
    grove &= ~bank
    rep = {}
    cand_px = {}
    for pname, cfg in MEADOW_PROPS.items():
        m = grove if cfg["where"] == "grove" else (bank & ~cv2.dilate(water.astype(np.uint8), np.ones((13, 13), np.uint8)).astype(bool))
        # Conifers stand on the slope toward the right cliffs too; boulders need a flat bank.
        b_ = base if cfg["where"] == "bank" else (box & ~town & ground_ok)
        cand = b_ & sub & m & (zsf > cfg["z"][0]) & (zsf < cfg["z"][1])
        cand_px[pname] = int(cand.sum())
        pts = poisson(ctx, cand, zsf, cfg["spacing"], cfg["cap"], taken)
        if not pts:
            rep[pname] = 0
            continue
        v, n, uv, f = load_glb_full(MESHY / pname / B.MESH_ATTEMPT / "model.glb")
        v, n, uv, f = decimate(v, n, uv, f, cfg["tris"])
        lo, hi = v.min(0), v.max(0)
        v = v - np.array([(lo[0] + hi[0]) / 2, lo[1], (lo[2] + hi[2]) / 2])
        mh = float(hi[1] - lo[1])
        write_bin(IN_DIR / f"{pname}_near.bytes", v, n, uv, [f])
        xf = []
        for w, _x, _y in pts:
            hgt = ctx.rng.uniform(*cfg["h"])
            xf += place_xform(ctx, w - np.array([0, 0.08 * hgt, 0]), float(ctx.rng.uniform(0, 360)), hgt / mh)
            if cfg["where"] == "grove":
                rep.setdefault("_bases", []).append((np.asarray(w, np.float64), float(hgt)))
        env["scatters"].append({"name": "Mesh_Scatter_" + pname.replace("prop_", "") + "_near",
                                "mesh": f"{ASSET_ROOT}/{pname}_near.bytes",
                                "texture": f"{ASSET_ROOT}/{pname}_albedo.png", "xforms": xf})
        rep[pname] = len(pts)
    rep["candidatePx"] = cand_px
    return rep


# Phase 5: near-field dressing, per square metre of ground at z = 8 m, falling as (8 / z) ** k (conflux_full3d_nearfield).
NEAR_DRESS = {"tufts": (45.0, 1.5), "flowers": (2.2, 1.5), "pebbles_bank": (10.0, 1.2), "pebbles_meadow": (0.25, 1.5),
              "rocks": (0.05, 1.0)}


def near_dressing(ctx: Ctx, env: dict, S5: dict, grid: dict, excl, front, cls, taken: list, grove_bases: list) -> dict:
    """Grass tufts, flower clumps, bank pebbles, near rocks and conifer roots as merged lit Mesh_ bins (one draw
    each), on the relieved ground (ctx.z), off plots / water / the assumed HUD strip; tall pieces also off the
    plots' screen corridor toward the camera (the conifer rule)."""
    rng = np.random.default_rng(SEED + 505)
    zmap = ctx.z
    wd, wl, water = S5["wd"], S5["wl"], S5["water"]
    sky = S5["sky"]
    hud = np.zeros((H, W), bool)
    hud[H - N5.HUD_BOTTOM_PX:] = True
    occupied = np.zeros((H, W), np.uint8)
    if taken:
        tp = np.asarray(taken)
        px, py, zc = project(ctx.cam, tp)
        for x_, y_, z_ in zip(px, py, zc):
            if 0 <= x_ < W and 0 <= y_ < H and z_ > 0:
                cv2.circle(occupied, (int(x_), int(y_)), max(2, int(0.45 / ctx.m_per_px(z_))), 1, -1)
    plots = cv2.dilate(excl.astype(np.uint8), np.ones((9, 9), np.uint8)).astype(bool)
    base = ~sky & ~plots & ~hud & ~occupied.astype(bool) & (zmap < N5.NEAR_DRESS_Z) & (S5["nf_s"][..., 1] > 0.7)
    grassy = (wl[..., 0] > 0.6) & (cls != SKY)
    rho = lambda a, k: (lambda z: a * (8.0 / np.maximum(z, 1.0)) ** k)  # noqa: E731
    sgn = N5.winding_sign(grid, ctx)
    rep: dict = {"windingSign": sgn, "hudBottomPx": N5.HUD_BOTTOM_PX, "meshyCredits": 0}

    def emit(name, v, n, uv, f, tex):
        write_bin(IN_DIR / f"{name}.bytes", ctx.local(v), ctx.local_dir(n), uv, [f])
        env["bins"].append({"name": name, "mesh": f"{ASSET_ROOT}/{name}.bytes", "texture": f"{ASSET_ROOT}/{tex}",
                            "kind": "lit", "maxSize": 1024})
        rep[name] = {"tris": int(len(f)), "verts": int(len(v))}

    # grass tufts
    # Tufts reach TUFT_Z on synthesised ground (the right-edge meadow sits at 30-45 m), smaller with distance.
    base_t = (~sky & ~plots & ~hud & ~occupied.astype(bool) & (zmap < N5.TUFT_Z) & (S5["nf_s"][..., 1] > 0.6)
              & ((zmap < N5.NEAR_DRESS_Z) | (S5["w_syn"] > 0.3)))
    rt = rho(*NEAR_DRESS["tufts"])
    tx, ty, tP, tz = N5.sample_sites(ctx, S5, zmap, base_t & grassy & (wd > 0.12),
                                     lambda z: np.maximum(rt(z), np.where(z > N5.NEAR_DRESS_Z, N5.TUFT_FLOOR, 0)), rng)
    site_col = N5._sample(S5["L0"], tx, ty)
    palette, cols = N5.kmeans_palette(site_col, N5.N_GRASS_COLS, rng)
    # Flowers in patches (world noise), each clump one colour of the Conflux elemental palette.
    Pf = S5["Pf"]
    patch = E.fbm(Pf[..., 0], Pf[..., 2], SEED + 61, 2.0, 2) > 0.58
    fx_, fy_, fP, fz = N5.sample_sites(ctx, S5, zmap, base & grassy & (wd > 0.3) & patch, rho(*NEAR_DRESS["flowers"]), rng)
    fcol = N5.FLOWER_COL0 + rng.integers(0, len(N5.FLOWERS_LIN), len(fP))
    # Pebbles: along the banks and just inside the water's edge, sparse in the meadow.
    edge_in = water & (distance_transform_edt_px(water) * ctx_m_px(ctx, zmap) < 0.25)
    bank_m = (~sky & ~plots & ~hud & (zmap < N5.NEAR_DRESS_Z) & ((~water & (wd > 0.02) & (wd < 1.1)) | edge_in))
    bx, by, bP, bz = N5.sample_sites(ctx, S5, zmap, bank_m, rho(*NEAR_DRESS["pebbles_bank"]), rng)
    mx_, my_, mP, mz = N5.sample_sites(ctx, S5, zmap, base & ~grassy & ~water, rho(*NEAR_DRESS["pebbles_meadow"]), rng)
    # Near rocks: few, larger, never in a plot's corridor toward the camera.
    rk = base & ~front & (zmap > 8.5) & (zmap < 16.0) & (wd > 0.4)
    rx_, ry_, rP, rz = N5.sample_sites(ctx, S5, zmap, rk, rho(*NEAR_DRESS["rocks"]), rng)
    if len(tP) == 0:
        raise SystemExit("near dressing: no grass tuft sites")
    # textures
    with Image.open(IN_DIR / "prop_conifer_a_albedo.png") as im:
        ca = E.srgb_to_lin(np.asarray(im.convert("RGB")).astype(np.float32) / 255).reshape(-1, 3)
    brown = (ca[:, 0] > ca[:, 1]) & (ca[:, 1] > ca[:, 2]) & (E.lum(ca) < 0.2)
    bark = np.median(ca[brown], 0) if brown.sum() > 200 else np.array([0.12, 0.07, 0.04], np.float32)
    stem = np.median(palette, 0) * 0.8
    Image.fromarray(N5.atlas(palette, stem, bark)).save(IN_DIR / "near_dressing_atlas.png")
    # Pebbles and near rocks take the scene's boulder colour (the Meshy prop_boulders albedo): the painting's rock
    # class colour is the shadowed cliff, and a first near rock tinted with it read as a black lump in the foreground.
    with Image.open(IN_DIR / "prop_boulders_albedo.png") as im:
        ba = E.srgb_to_lin(np.asarray(im.convert("RGB")).astype(np.float32) / 255).reshape(-1, 3)
    rock_c = np.median(ba[E.lum(ba) > 0.02], 0).astype(np.float32)
    bank_c = np.median(N5._sample(S5["L0"], bx, by), 0) if len(bx) else rock_c
    Image.fromarray(N5.pebble_texture(DETAIL_CACHE, rock_c * 1.15, 0.5 * (bank_c + rock_c))).save(IN_DIR / "near_pebbles.png")
    # geometry
    v, n, uv, f, want = N5.tufts(ctx, tP, tz, cols, rng)
    emit("Mesh_NearGrass", v, n, uv, N5.orient(v, f, want, sgn), "near_dressing_atlas.png")
    rep["Mesh_NearGrass"]["tufts"] = int(len(tP))
    if len(fP):
        v, n, uv, f, want = N5.flowers(ctx, fP, fz, fcol, N5.STEM_COL, rng)
        emit("Mesh_NearFlowers", v, n, uv, N5.orient(v, f, want, sgn), "near_dressing_atlas.png")
        rep["Mesh_NearFlowers"]["clumps"] = int(len(fP))
    pp = np.concatenate([bP, mP]) if len(mP) else bP
    pz = np.concatenate([bz, mz]) if len(mz) else bz
    if len(pp):
        v, n, uv, f, out = N5.pebbles(ctx, pp, pz, rng.uniform(0.025, 0.07, len(pp)), rng)
        emit("Mesh_NearPebbles", v, n, uv, N5.orient(v, f, out, sgn), "near_pebbles.png")
        rep["Mesh_NearPebbles"]["pebbles"] = int(len(pp))
    if len(rP):
        v, n, uv, f, out = N5.pebbles(ctx, rP, rz, rng.uniform(0.18, 0.34, len(rP)), rng, sink=0.3, level=3, rough=0.22,
                                      flat=(0.55, 0.85))
        emit("Mesh_NearRocks", v, n, uv, N5.orient(v, f, out, sgn), "near_pebbles.png")
        rep["Mesh_NearRocks"]["rocks"] = int(len(rP))
    near_groves = [(b, h) for b, h in grove_bases if project(ctx.cam, b[None])[2][0] < 30.0]
    r = N5.roots(ctx, near_groves, rng) if near_groves else None
    if r is not None:
        v, n, uv, f, out = r
        emit("Mesh_NearRoots", v, n, uv, N5.orient(v, f, out, sgn), "near_dressing_atlas.png")
        rep["Mesh_NearRoots"]["conifers"] = len(near_groves)
    # density check: sites per square metre by depth band (rises toward the camera by construction)
    allz = {"tufts": tz, "flowers": fz, "pebbles": pz, "rocks": rz}
    rep["sitesByDepth"] = {k: {f"{a}-{b}m": int(((z >= a) & (z < b)).sum()) for a, b in ((0, 12), (12, 18), (18, 26), (26, 60))}
                           for k, z in allz.items()}
    rep["paletteLinear"] = {"grassColumns": len(palette), "flowers": N5.FLOWERS_LIN, "bark": [round(float(c), 4) for c in bark]}
    return rep


def distance_transform_edt_px(mask: np.ndarray) -> np.ndarray:
    from scipy.ndimage import distance_transform_edt

    return distance_transform_edt(mask)


def ctx_m_px(ctx: Ctx, zmap: np.ndarray) -> np.ndarray:
    return 2 * zmap * math.tan(math.radians(ctx.cam["fov"]) / 2) / H


def poisson(ctx: Ctx, cand: np.ndarray, zs: np.ndarray, spacing: float, cap: int, taken: list) -> list:
    ys, xs = np.nonzero(cand)
    if len(xs) == 0:
        return []
    order = ctx.rng.permutation(len(xs))
    pts = []
    grid: dict = {}
    cell = spacing
    for p in taken:
        grid.setdefault((int(p[0] // cell), int(p[2] // cell)), []).append(p)
    for k in order:
        x, y = xs[k], ys[k]
        w = ctx.cpos + rays(ctx.cam, np.float64(x), np.float64(y)) * zs[y, x]
        gx_, gz_ = int(w[0] // cell), int(w[2] // cell)
        ok = True
        for dx in (-1, 0, 1):
            for dz in (-1, 0, 1):
                for q in grid.get((gx_ + dx, gz_ + dz), ()):
                    if (q[0] - w[0]) ** 2 + (q[2] - w[2]) ** 2 < spacing * spacing:
                        ok = False
                        break
                if not ok:
                    break
            if not ok:
                break
        if ok:
            grid.setdefault((gx_, gz_), []).append(w)
            pts.append((w, x, y))
            taken.append(w)
            if len(pts) >= cap:
                break
    return pts


# ------------------------------------------------------------------------------------------------ materials
def vtex(name: str) -> str:
    """A vanilla Olden Era VFX texture (noise / mask / lava, never a flipbook), copied into the project."""
    src = VANILLA_TEX / f"{name}.png"
    if not src.is_file():
        raise SystemExit(f"vanilla texture missing: {src}")
    (IN_DIR / "vfx").mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, IN_DIR / "vfx" / src.name)
    return f"{ASSET_ROOT}/vfx/{src.name}"


def tex(prop: str, path: str, st=(1, 1, 0, 0), clamp=False, srgb=True) -> dict:
    return {"prop": prop, "path": path, "st": [float(x) for x in (list(st) + [0, 0])[:4]] if len(st) == 2 else [float(x) for x in st],
            "clamp": clamp, "srgb": srgb}


def material(shader: str, textures=(), floats=None, colors=None, queue: int = 0) -> dict:
    return {"shader": f"{SHADER_DIR}/{shader}.shader", "textures": list(textures),
            "floats": [{"name": k, "value": float(v)} for k, v in (floats or {}).items()],
            "colors": [{"name": k, "rgba": [float(x) for x in v]} for k, v in (colors or {}).items()], "queue": queue}


def uber(noise1: str, noise2: str | None = None, mask: str | None = None, st1=(1, 1), st2=(1, 1), mn=0.0, mx=1.0,
         lerp=1.0, blend=1.0, color=1.0, speeds=(0, 0, 0, 0), cam_offset=0.0) -> dict:
    """The VfxUber replica with a vanilla material's parameters (materials.json)."""
    t = [tex("_Texture", vtex(noise1), st1, clamp=noise1.startswith(("glow", "smoke")))]
    if noise2:
        t.append(tex("_Texture2", vtex(noise2), st2))
    if mask:
        t.append(tex("_Mask", vtex(mask), clamp=True))
    return material("Homm3ConfluxVfxUber", t,
                    {"_Min": mn, "_Max": mx, "_Lerp": lerp, "_Multiply": 1.0, "_Blend": blend,
                     "_xSpeed01": speeds[0], "_ySpeed01": speeds[1], "_xSpeed02": speeds[2], "_ySpeed02": speeds[3],
                     "_UseTwo": 1.0 if noise2 else 0.0, "_CameraOffset": cam_offset,
                     "_UseCamOffset": 1.0 if cam_offset > 0 else 0.0},
                    {"_Color": [color, color, color, 1.0]})


def vanilla_mats() -> dict:
    return {
        # Map_fire_01_vfx: licking flame tongues.
        "fire1": uber("TileNoise_07_vfx", "TileNoise_19_vfx", "glow_18_vfx", (1, 2), (1, 2), 0.02, 0.3, 1.0, 1.0, 3.82, (1.0, 0, 0.5, 0)),
        # Map_fire_02_vfx: soft billowing fire.
        "fire2": uber("TileNoise_01_vfx", "TileNoise_21_vfx", "smoke_06_vfx", (1, 1), (1, 1), 0.0, 0.22, 1.0, 0.5, 5.99, (0.4, 0, 0.35, 0), 0.5),
        # Map_fire_02_vfx at lower intensity and more alpha: the pyre's flat cap keeps its orange/violet hue where
        # many particles overlap (the additive original blew out to pink-white).
        "cap": uber("TileNoise_01_vfx", "TileNoise_21_vfx", "smoke_06_vfx", (1, 1), (1, 1), 0.0, 0.22, 1.0, 0.85, 2.4, (0.4, 0, 0.35, 0), 0.5),
        # Wall_of_flame_fire_vfx: dense flame body for the column.
        "flame": uber("TileNoise_23_vfx", "TileNoise_23_vfx", "smoke_04_vfx", (0.6, 0.6), (0.5, 0.5), 0.0, 0.5, 1.0, 0.65, 8.47, (-0.1, 0, 0, 0)),
        # Map_smoke_01_vfx, alpha raised (0.3 -> 0.85) and intensity lowered so the plume occludes like thick smoke.
        "smoke": uber("TileNoise_24_vfx", "TileNoise_11_vfx", "glow_04_vfx", (2, 2), (1, 2), 0.0, 0.688, 1.0, 0.85, 1.3, (-0.02, -0.01, -0.01, 0.008), 1.0),
        # Glow_03_vfx.
        "glow": uber("glow_08_vfx", None, None, lerp=0.17, blend=0.2, color=5.99),
        # Paragon_glow_vfx for embers (bright points).
        "ember": uber("glow_10_vfx", None, None, lerp=1.0, blend=0.0, color=6.0),
    }


def psys(name: str, mat: dict, **kw) -> dict:
    d = {"name": name, "material": mat, "seed": int(hashlib.sha1(name.encode()).hexdigest()[:6], 16), "customUV": True,
         "maxParticles": 200, "shape": "sphere", "radius": 0.1}
    for k, v in kw.items():
        d[k] = [float(x) for x in v] if isinstance(v, (list, tuple)) else v
    return d


UP = [-90.0, 0.0, 0.0]  # cone shapes emit along local +z; this turns them to world up


def pyre_systems(h: float, R: float, M: dict) -> list[dict]:
    """tbeldw_6 (HoMM3 art): a thin twisting fire column rising from the peak into a wide, flat fire disc, orange at
    the heart and violet at the rim. Phase 3b: the column is narrow and swirls (strong orbital velocity, small
    radius); the cap is a flat disc of small particles carried outward (radial) while it turns, orange -> violet over
    their life, drawn with a saturated alpha-heavy fire material (`cap`) so overlap no longer blows out to pink."""
    fade = [0, 0, 0.12, 1, 0.65, 0.8, 1, 0]
    return [
        psys("glow_base", M["glow"], lifetime=[2.0, 2.4], speed=[0], size=[R * 0.4, R * 0.55], rate=1.6, maxParticles=6,
             radius=0.3, pos=[0, h * 0.1, 0], color=[1, 0.42, 0.12, 0.3], alphaKeys=[0, 0, 0.3, 1, 0.7, 1, 1, 0], customUV=False),
        psys("flames", M["fire1"], lifetime=[0.7, 1.1], speed=[h * 0.25, h * 0.4], size=[h * 0.06, h * 0.11], rate=60,
             maxParticles=110, shape="cone", radius=R * 0.08, angle=8, shapeRot=UP, renderMode=1, lengthScale=1.4,
             velocityScale=0.05, color=[1, 0.62, 0.22, 1], color2=[1, 0.45, 0.12, 1],
             colorKeys=[0, 1, 0.9, 0.5, 0.45, 1, 0.5, 0.15, 1, 0.8, 0.15, 0.08], alphaKeys=fade,
             sizeKeys=[0, 0.55, 0.3, 1, 1, 0.45], noise=h * 0.03, noiseFreq=0.6, noiseScroll=0.5),
        # The column: a narrow twisting rope of flame (orbital swirl round the axis, a slight noise wander).
        psys("column", M["flame"], lifetime=[1.4, 1.8], speed=[h * 0.6, h * 0.75], size=[h * 0.045, h * 0.075], rate=110,
             maxParticles=220, shape="cone", radius=R * 0.025, angle=1.5, shapeRot=UP, rotation=[0, 360], rotSpeed=[-90, 90],
             orbitalY=[3.2, 4.2], radial=[R * 0.012, R * 0.02], color=[1, 0.58, 0.16, 1], color2=[1, 0.44, 0.1, 1],
             colorKeys=[0, 1, 0.78, 0.35, 0.6, 1, 0.5, 0.14, 1, 0.95, 0.4, 0.1], alphaKeys=[0, 0, 0.1, 1, 0.85, 0.9, 1, 0],
             sizeKeys=[0, 0.8, 0.6, 1.0, 1, 1.2], noise=h * 0.012, noiseFreq=0.8, noiseScroll=0.6),
        # The cap: a wide flat disc (thin shell, small particles), born near the axis and carried out to the rim while
        # the disc turns; orange at the heart, violet at the rim.
        psys("cloud", M["cap"], lifetime=[3.0, 4.0], speed=[0.02, 0.08], size=[h * 0.14, h * 0.22], rate=130,
             maxParticles=500, radius=h * 0.04, radiusThickness=1, shapeScale=[1, 0.08, 1], pos=[0, h, 0],
             rotation=[0, 360], rotSpeed=[-25, 25], orbitalY=[0.35, 0.5], radial=[h * 0.12, h * 0.16],
             color=[1, 0.55, 0.14, 1], color2=[1, 0.45, 0.1, 1],
             colorKeys=[0, 1, 0.66, 0.2, 0.5, 1, 0.52, 0.12, 0.85, 1, 0.4, 0.2, 1, 0.7, 0.25, 0.7],
             alphaKeys=[0, 0, 0.12, 0.9, 0.75, 0.75, 1, 0], sizeKeys=[0, 0.6, 1, 1.2]),
        # The rim: violet particles on a ring just under the disc's edge (HoMM3's violet fringe round the orange).
        psys("rim", M["cap"], lifetime=[2.2, 3.0], speed=[0.02, 0.06], size=[h * 0.14, h * 0.22], rate=90,
             maxParticles=300, radius=h * 0.42, radiusThickness=0.2, shapeScale=[1, 0.1, 1], pos=[0, h * 0.985, 0],
             rotation=[0, 360], rotSpeed=[-20, 20], orbitalY=[0.35, 0.5], radial=[h * 0.015, h * 0.035],
             color=[0.62, 0.26, 0.86, 1], color2=[0.46, 0.18, 0.72, 1],
             colorKeys=[0, 0.9, 0.4, 0.55, 0.5, 0.62, 0.26, 0.86, 1, 0.42, 0.16, 0.66],
             alphaKeys=[0, 0, 0.2, 0.8, 0.7, 0.7, 1, 0], sizeKeys=[0, 0.7, 1, 1.15]),
        psys("glow_cloud", M["glow"], lifetime=[2.5, 3.0], speed=[0], size=[R * 1.6, R * 1.9], rate=0.9, maxParticles=4,
             radius=0.3, pos=[0, h, 0], color=[1, 0.45, 0.12, 0.12], alphaKeys=[0, 0, 0.3, 1, 0.7, 1, 1, 0], customUV=False),
        psys("smoke", M["smoke"], lifetime=[6.0, 8.0], speed=[0], size=[R * 0.5, R * 0.8], rate=3.5, maxParticles=40,
             radius=R * 0.9, radiusThickness=0.3, shapeScale=[1, 0.15, 1], pos=[0, h + R * 0.08, 0],
             velY=[h * 0.04, h * 0.08], velX=[0.3, 0.9], rotation=[0, 360], rotSpeed=[-10, 10],
             color=[0.3, 0.16, 0.36, 0.7], color2=[0.16, 0.1, 0.2, 0.7],
             alphaKeys=[0, 0, 0.25, 0.6, 0.75, 0.4, 1, 0], sizeKeys=[0, 0.6, 1, 1.6], sortingFudge=10),
        psys("embers", M["ember"], lifetime=[2.0, 3.5], speed=[h * 0.3, h * 0.55], size=[0.15, 0.32], rate=30,
             maxParticles=120, shape="cone", radius=R * 0.1, angle=20, shapeRot=UP, color=[1, 0.62, 0.22, 1],
             alphaKeys=[0, 0, 0.1, 1, 0.8, 1, 1, 0], noise=h * 0.1, noiseFreq=0.6, noiseScroll=0.3, customUV=False),
    ]


def lava_systems(Rl: float, M: dict) -> list[dict]:
    """tbeldw_3: flames licking off the lava, heat haze smoke, embers, a glow over the crater."""
    return [
        psys("glow", M["glow"], lifetime=[2.0, 2.4], speed=[0], size=[Rl * 1.8, Rl * 2.2], rate=1.6, maxParticles=6,
             radius=0.2, pos=[0, Rl * 0.15, 0], color=[1, 0.45, 0.12, 0.22], alphaKeys=[0, 0, 0.3, 1, 0.7, 1, 1, 0], customUV=False),
        psys("flames", M["fire1"], lifetime=[0.6, 1.0], speed=[0], velY=[Rl * 0.45, Rl * 0.9], size=[Rl * 0.25, Rl * 0.45],
             rate=22, maxParticles=50, radius=Rl * 0.7, radiusThickness=1, shapeScale=[1, 0.08, 1], renderMode=1,
             lengthScale=1.3, velocityScale=0.05, color=[1, 0.6, 0.2, 1], color2=[1, 0.42, 0.1, 1],
             colorKeys=[0, 1, 0.85, 0.45, 0.5, 1, 0.48, 0.12, 1, 0.75, 0.14, 0.06], alphaKeys=[0, 0, 0.15, 1, 0.65, 0.8, 1, 0],
             sizeKeys=[0, 0.5, 0.35, 1, 1, 0.4], noise=Rl * 0.08, noiseFreq=0.8, noiseScroll=0.5),
        psys("smoke", M["smoke"], lifetime=[3.0, 4.5], speed=[0], velY=[Rl * 0.3, Rl * 0.55], velX=[0.1, 0.4],
             size=[Rl * 0.8, Rl * 1.3], rate=3.2, maxParticles=24, radius=Rl * 0.5, radiusThickness=1,
             shapeScale=[1, 0.1, 1], pos=[0, Rl * 0.3, 0], rotation=[0, 360], rotSpeed=[-12, 12],
             color=[0.36, 0.26, 0.22, 0.6], color2=[0.24, 0.2, 0.2, 0.6], alphaKeys=[0, 0, 0.3, 0.6, 1, 0],
             sizeKeys=[0, 0.6, 1, 1.7], sortingFudge=10),
        psys("embers", M["ember"], lifetime=[1.5, 2.8], speed=[0], velY=[Rl * 0.6, Rl * 1.2], size=[0.08, 0.18], rate=14,
             maxParticles=50, radius=Rl * 0.6, radiusThickness=1, shapeScale=[1, 0.1, 1], color=[1, 0.6, 0.2, 1],
             alphaKeys=[0, 0, 0.1, 1, 0.8, 1, 1, 0], noise=Rl * 0.2, noiseFreq=0.7, noiseScroll=0.3, customUV=False),
    ]


def fx_group(ctx: Ctx, name: str, world_base, systems: list[dict]) -> dict:
    return {"name": name, "pos": [float(x) for x in ctx.local(world_base)], "rot": ctx.world_quat(),
            "scale": float(ctx.scale), "systems": systems}


def fxmesh_row(name: str, v_local, n_local, uv, tris, mat: dict, uv2=None, pos=None) -> dict:
    """An Fx_ mesh in the prefab frame (vertices relative to `pos`) drawn by a bone-less SkinnedMeshRenderer."""
    v_local = np.asarray(v_local, np.float64)
    write_bin(IN_DIR / f"{name}.bytes", v_local, n_local, uv, [tris])
    row = {"name": name, "mesh": f"{ASSET_ROOT}/{name}.bytes", "kind": "fxmesh", "material": mat,
           "pos": [float(x) for x in (pos if pos is not None else (0, 0, 0))], "rot": [0.0, 0.0, 0.0, 1.0]}
    if uv2 is not None:
        (IN_DIR / f"{name}_uv2.bytes").write_bytes(np.asarray(uv2, np.float32).tobytes())
        row["uv2"] = f"{ASSET_ROOT}/{name}_uv2.bytes"
    return row


def disc_polar(radius: float, rings: int = 8, seg: int = 96):
    """Camera-facing disc (prefab x/y plane) with rings, uv = 0.5 + 0.5 * (x, y) / radius."""
    V, UV = [np.zeros(3)], [np.array([0.5, 0.5])]
    for k in range(1, rings + 1):
        r = k / rings
        a = np.linspace(0, 2 * np.pi, seg, endpoint=False)
        V += list(np.stack([np.cos(a) * r * radius, np.sin(a) * r * radius, np.zeros(seg)], 1))
        UV += list(np.stack([0.5 + 0.5 * r * np.cos(a), 0.5 + 0.5 * r * np.sin(a)], 1))
    T = []
    for i in range(seg):  # centre fan, front toward the camera (-z)
        T.append([0, 1 + (i + 1) % seg, 1 + i])
    for k in range(1, rings):
        b0, b1 = 1 + (k - 1) * seg, 1 + k * seg
        for i in range(seg):
            j = (i + 1) % seg
            T += [[b0 + i, b0 + j, b1 + i], [b0 + j, b1 + j, b1 + i]]
    T = np.array(T)
    return np.array(V), np.array(UV), T


# ------------------------------------------------------------------------------------ phase 4: building animations
# Every Conflux town-screen building whose HoMM3 DEF has more than one frame (anims/metadata.json beside the layer
# sprites; frame counts cross-checked against H3sprite.lod) and what moves in it. The effects are vanilla-style
# (VfxUber replica particles, the bundle's FlowWater / Lava / Portal / Aurora shaders); nothing is a ripped flipbook.
ANIMS = B.REFS / "layers" / "anims"
ANIM_MOVES = {
    "tbelblak": "dark grey smoke billowing up from the forge chimney",
    "tbeldw_0": "the lantern's light flickering in its glass",
    "tbeldw_0_2": "the lantern's light flickering in its glass",
    "tbelhrd2": "the same lantern flicker (the horde art repeats the upgraded dwelling's lantern)",
    "tbeldw_1": "six crystals glinting in turn; a white shimmer in the shrine doorway",
    "tbeldw_1_2": "six crystals glinting in turn; a white shimmer in the shrine doorway",
    "tbeldw_2": "fountain: white water jets arcing from the central vase into the basin; splash and foam at the basin",
    "tbeldw_2_2": "fountain: white water jets arcing from the central vase into the basin; splash and foam at the basin",
    "tbeldw_3": "lava churning in the crater; glowing steps",
    "tbeldw_3_2": "lava churning in the crater; glowing steps",
    "tbeldw_4": "glittering bright points over the stone ring",
    "tbeldw_4_2": "glittering bright points over the stone ring and its spires",
    "tbeldw_5": "the orb swirling inside the portal ring",
    "tbeldw_5_2": "the orb swirling inside the portal ring",
    "tbeldw_6": "the fire column rising into a swirling fire cloud",
    "tbeldw_6_2": "the fire column rising into a swirling fire cloud",
    "tbelholy": "aurora curtains rippling across the sky",
}
# A layer whose moving pixels are another co-present layer's (same sprite position, same lantern): its effect is
# the other layer's pieces, not a doubled copy.
ANIM_SHARED = {"tbelhrd2": "tbeldw_0_2"}
ANIM_BASE_STATE = ["tbeldw_0", "tbeldw_1", "tbeldw_2", "tbeldw_3", "tbeldw_4", "tbeldw_5", "tbeldw_6"]


def def_frames(layer: str) -> int:
    meta = {m["id"]: m for m in json.loads((ANIMS / "metadata.json").read_text(encoding="utf-8"))}
    return len(meta[layer]["frames"]) if layer in meta else 1


def def_motion(ctx: Ctx, layer: str, thr: float = 20.0) -> np.ndarray:
    """The HoMM3 DEF's moving pixels in frame px: max |frame_k - frame_0| over the animated patches (0 = static)."""
    meta = {m["id"]: m for m in json.loads((ANIMS / "metadata.json").read_text(encoding="utf-8"))}
    out = np.zeros((H, W), np.float32)
    if layer not in meta:
        return out
    fr = [np.asarray(Image.open(ANIMS / layer / f).convert("RGBA")).astype(np.float32) for f in meta[layer]["frames"]]
    d = np.max([np.abs(f[..., :3] - fr[0][..., :3]).max(-1) * (f[..., 3] > 0) for f in fr[1:]], 0)
    d = np.where(d > thr, d, 0).astype(np.float32)
    big = cv2.resize(d, (round(d.shape[1] * B.SCALE), round(d.shape[0] * B.SCALE)), interpolation=cv2.INTER_NEAREST)
    L = ctx.layers[layer]
    dx, dy = round(L["x"] * B.SCALE), round(L["y"] * B.SCALE)
    x0, y0 = max(dx, 0), max(dy, 0)
    x1, y1 = min(dx + big.shape[1], W), min(dy + big.shape[0], H)
    out[y0:y1, x0:x1] = big[y0 - dy:y1 - dy, x0 - dx:x1 - dx]
    return out


def motion_parts(mot: np.ndarray, min_px: int = 60, join: int = 7) -> list[dict]:
    """Connected moving regions (frame px), largest first: centroid (motion-weighted), bbox, area."""
    m = cv2.dilate((mot > 0).astype(np.uint8), np.ones((join, join), np.uint8))
    n, lab_, st, _ = cv2.connectedComponentsWithStats(m)
    parts = []
    for i in range(1, n):
        sel = (lab_ == i) & (mot > 0)
        if sel.sum() < min_px:
            continue
        ys, xs = np.nonzero(sel)
        w_ = mot[sel]
        parts.append({"cx": float((xs * w_).sum() / w_.sum()), "cy": float((ys * w_).sum() / w_.sum()),
                      "bbox": [int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1], "area": int(sel.sum())})
    return sorted(parts, key=lambda p: -p["area"])


def snap_point(ctx: Ctx, md: np.ndarray, px: float, py: float, toward_cam: float = 0.0, r: int = 40):
    """World point on the building mesh under (px, py) (nearest covered pixel within r), pulled toward the camera."""
    xi, yi = int(round(px)), int(round(py))
    y0, y1, x0, x1 = max(0, yi - r), min(H, yi + r + 1), max(0, xi - r), min(W, xi + r + 1)
    win = md[y0:y1, x0:x1]
    fin = np.isfinite(win)
    if fin.any():
        yy, xx = np.nonzero(fin)
        k = int(np.argmin((yy + y0 - yi) ** 2 + (xx + x0 - xi) ** 2))
        z = float(win[yy[k], xx[k]])
    else:
        z = float(ctx.z[min(yi, H - 1), min(xi, W - 1)])
    return ctx.cpos + rays(ctx.cam, np.float64(px), np.float64(py)) * max(z - toward_cam, 0.5), z


def anim_mats() -> dict:
    return {
        # Glow_03_vfx tinted: soft warm light (lantern) and cool light (shrine doorway).
        "glow": uber("glow_08_vfx", None, None, lerp=0.17, blend=0.2, color=5.99),
        # Paragon_glow_vfx points: glints and sparkles.
        "glint": uber("glow_10_vfx", None, None, lerp=1.0, blend=0.0, color=6.0),
        # Map_smoke_01_vfx with a lower smoothstep ceiling (0.688 -> 0.3) and full alpha: chimney smoke is one thin
        # stream of particles, not the pyre's overlapping cloud, so each puff must be nearly opaque on its own.
        "smoke": uber("TileNoise_24_vfx", "TileNoise_11_vfx", "glow_04_vfx", (2, 2), (1, 2), 0.0, 0.3, 1.0, 1.0, 1.0,
                      (-0.02, -0.01, -0.01, 0.008), 1.0),
        # Spray / mist: a soft noisy blob, mostly alpha-blended white (VfxUber with the smoke mask).
        "spray": uber("TileNoise_07_vfx", None, "glow_04_vfx", (1, 1), (1, 1), 0.0, 0.45, 1.0, 0.75, 1.5, (0, -0.4, 0, 0)),
    }


def gravity_mod(ctx: Ctx, g_m: float) -> float:
    """ParticleSystem gravityModifier for g_m (m/s^2 in the scene's metres): the prefab frame is scaled by ctx.scale."""
    return g_m * ctx.scale / 9.81


def smoke_systems(ph: float, cr: float, A: dict) -> list[dict]:
    """tbelblak: a dark grey plume from the chimney mouth rising ph metres, widening as it climbs."""
    return [
        psys("plume", A["smoke"], lifetime=[3.2, 4.2], speed=[ph / 4.0, ph / 3.0], velX=[ph * 0.02, ph * 0.08],
             size=[cr * 1.8, cr * 2.6], rate=8, maxParticles=44, shape="cone", radius=cr * 0.45, angle=8,
             shapeRot=UP, rotation=[0, 360], rotSpeed=[-14, 14],
             color=[0.42, 0.42, 0.41, 1.0], color2=[0.32, 0.32, 0.31, 1.0],
             # VfxUber squares vertex alpha: keep the plume's alpha high so it survives up the whole column.
             alphaKeys=[0, 0, 0.1, 1, 0.55, 0.85, 1, 0], sizeKeys=[0, 0.5, 1, 2.6],
             noise=ph * 0.05, noiseFreq=0.5, noiseScroll=0.3, sortingFudge=10),
        psys("puffs", A["smoke"], lifetime=[1.2, 1.8], speed=[ph / 3.0, ph / 2.2], size=[cr * 1.0, cr * 1.5],
             rate=5, maxParticles=12, shape="cone", radius=cr * 0.35, angle=6, shapeRot=UP, rotation=[0, 360],
             rotSpeed=[-25, 25], color=[0.4, 0.4, 0.39, 1.0], alphaKeys=[0, 0, 0.2, 0.85, 1, 0],
             sizeKeys=[0, 0.6, 1, 1.4], sortingFudge=12),
    ]


def lantern_systems(s: float, A: dict) -> list[dict]:
    """tbeldw_0: a flickering warm light in the lantern glass (short overlapping glows of random strength)."""
    return [
        psys("flicker", A["glow"], lifetime=[0.12, 0.32], speed=[0], size=[s * 0.9, s * 1.35], rate=26, maxParticles=16,
             radius=s * 0.06, color=[1, 0.78, 0.36, 0.5], color2=[1, 0.62, 0.22, 0.25],
             alphaKeys=[0, 0, 0.25, 1, 0.6, 0.8, 1, 0], customUV=False),
        psys("core", A["glint"], lifetime=[0.2, 0.5], speed=[0], size=[s * 0.25, s * 0.42], rate=10, maxParticles=8,
             radius=s * 0.05, color=[1, 0.88, 0.58, 0.9], alphaKeys=[0, 0, 0.3, 1, 0.7, 0.8, 1, 0], customUV=False),
        psys("halo", A["glow"], lifetime=[1.6, 2.0], speed=[0], size=[s * 2.2, s * 2.6], rate=1.5, maxParticles=4,
             radius=s * 0.05, color=[1, 0.72, 0.3, 0.14], alphaKeys=[0, 0, 0.3, 1, 0.7, 1, 1, 0], customUV=False),
    ]


def glint_systems(tag: str, s: float, A: dict, rate: float, color, box=None) -> list[dict]:
    """A crystal / stone sparkle: bright points that swell and vanish (sizeKeys 0 -> 1 -> 0)."""
    shape = {"shape": "box", "shapeScale": list(box)} if box is not None else {"radius": s * 0.35}
    return [psys(f"glint_{tag}", A["glint"], lifetime=[0.25, 0.55], speed=[0], size=[s * 0.5, s * 1.0], rate=rate,
                 maxParticles=24, color=list(color) + [1.0], alphaKeys=[0, 0, 0.3, 1, 1, 0.2],
                 sizeKeys=[0, 0, 0.35, 1, 1, 0], rotation=[0, 360], customUV=False, **shape)]


def shimmer_systems(s: float, A: dict) -> list[dict]:
    """tbeldw_1 doorway: a cool white light that breathes, with slow motes drifting up."""
    return [
        psys("shimmer", A["glow"], lifetime=[0.8, 1.4], speed=[0], size=[s * 0.8, s * 1.2], rate=4, maxParticles=8,
             radius=s * 0.15, color=[0.86, 0.92, 1.0, 0.35], alphaKeys=[0, 0, 0.4, 1, 1, 0], customUV=False),
        psys("motes", A["glint"], lifetime=[0.8, 1.4], speed=[0], velY=[s * 0.3, s * 0.6], size=[s * 0.06, s * 0.12],
             rate=10, maxParticles=20, shape="box", shapeScale=[s * 0.6, s * 0.7, s * 0.2],
             color=[0.9, 0.95, 1.0, 1.0], alphaKeys=[0, 0, 0.3, 1, 1, 0], customUV=False),
    ]


def _superellipse(c, e1, e2, a, b, r, th, p=4.0):
    ct, st_ = np.cos(th), np.sin(th)
    x = np.sign(ct) * np.abs(ct) ** (2 / p) * a * r
    y = np.sign(st_) * np.abs(st_) ** (2 / p) * b * r
    return c + np.outer(x, e1) + np.outer(y, e2)


def basin_top(vw: np.ndarray, fw: np.ndarray) -> dict:
    """The fountain basin's water plane: the height carrying the most up-facing area, its footprint axes/extents."""
    tri = vw[fw]
    fn = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    area = np.linalg.norm(fn, axis=1) * 0.5
    ny = fn[:, 1] / (2 * area + 1e-12)
    cy = tri[:, :, 1].mean(1)
    ptp = float(np.ptp(vw[:, 1]))
    up = ny > 0.9
    bins = np.linspace(vw[:, 1].min(), vw[:, 1].max(), 81)
    hist, _ = np.histogram(cy[up], bins, weights=area[up])
    k = int(np.argmax(hist))
    y_top = float(np.average(cy[up & (cy >= bins[k]) & (cy <= bins[k + 1])], weights=area[up & (cy >= bins[k]) & (cy <= bins[k + 1])]))
    sel = up & (np.abs(cy - y_top) < 0.02 * ptp)
    cxz = tri[sel][:, :, [0, 2]].reshape(-1, 2)
    c = cxz.mean(0)
    u, sv, vt = np.linalg.svd(cxz - c, full_matrices=False)
    ax = vt
    pr = (cxz - c) @ ax.T
    lo, hi = np.percentile(pr, 2, 0), np.percentile(pr, 98, 0)
    mid = (lo + hi) / 2
    c = c + mid @ ax
    e1 = np.array([ax[0, 0], 0, ax[0, 1]])
    e2 = np.array([ax[1, 0], 0, ax[1, 1]])
    a_, b_ = float((hi - lo)[0] / 2), float((hi - lo)[1] / 2)
    # The basin wall: vertices in a ring just outside the floor; its top is the rim the water fills up to.
    pv = (vw[:, [0, 2]] - c) @ ax.T
    rn = np.hypot(pv[:, 0] / a_, pv[:, 1] / b_)
    ring = (rn > 0.95) & (rn < 1.45)
    y_rim = float(np.percentile(vw[ring, 1], 95)) if ring.sum() > 20 else y_top
    y_water = y_top + 0.85 * (y_rim - y_top)
    return {"centre": np.array([c[0], y_top, c[1]]), "e1": e1, "e2": e2, "a": a_, "b": b_, "yFloor": y_top,
            "yRim": y_rim, "yWater": y_water, "meshHeight": ptp, "upArea": float(area[sel].sum())}


def ribbon(ctx: Ctx, pts: np.ndarray, width: np.ndarray):
    """A camera-facing strip along a world polyline: (verts, normals, uv0 (across 0..1, along 0..1), uv1 metres, tris)."""
    n = len(pts)
    tg = np.gradient(pts, axis=0)
    tg /= np.linalg.norm(tg, axis=1, keepdims=True) + 1e-12
    view = pts - ctx.cpos
    side = np.cross(tg, view)
    side /= np.linalg.norm(side, axis=1, keepdims=True) + 1e-12
    nrm = -view / (np.linalg.norm(view, axis=1, keepdims=True) + 1e-12)
    arc = np.concatenate([[0], np.cumsum(np.linalg.norm(np.diff(pts, axis=0), axis=1))])
    v = np.concatenate([pts - side * width[:, None] / 2, pts + side * width[:, None] / 2])
    nn_ = np.concatenate([nrm, nrm])
    s = np.linspace(0, 1, n)
    uv = np.concatenate([np.stack([np.zeros(n), s], 1), np.stack([np.ones(n), s], 1)])
    uv1 = np.concatenate([np.stack([-width / 2, arc], 1), np.stack([width / 2, arc], 1)])
    i = np.arange(n - 1)
    tri = np.concatenate([np.stack([i, i + 1, i + n], 1), np.stack([i + 1, i + n + 1, i + n], 1)])
    return v, nn_, uv, uv1, tri


def fountain(ctx: Ctx, lid: str, vw, fw, md, sprite_rgba, A: dict, spec_l, sky_c) -> tuple[list, list, dict]:
    """tbeldw_2: a water surface in the dry basin (FlowWater, rings running outward), six water jets arcing from a
    central column into it (FlowWater ribbons, streaks running down each jet), splash where they land, light mist.
    Heights follow the HoMM3 DEF: jet apex ~24 sprite px above the basin water, vase mouth ~16."""
    bt = basin_top(vw, fw)
    c, e1, e2, a, b = bt["centre"], bt["e1"], bt["e2"], bt["a"] * 1.05, bt["b"] * 1.05
    y_w = bt["yWater"]
    c = np.array([c[0], y_w, c[2]])
    zc = float((c - ctx.cpos) @ ctx.cam["fwd"])
    mpp = ctx.m_per_px(zc)
    hj = 24 * B.SCALE * mpp          # jet apex over the water
    hv = 16 * B.SCALE * mpp          # vase mouth / column
    w0 = 2.4 * B.SCALE * mpp         # jet thickness at the mouth
    # --- basin water: superellipse disc on the plane, polar flow (rings run outward) ---------------------------
    rings, seg = 12, 72
    th = np.linspace(0, 2 * np.pi, seg, endpoint=False)
    V, UV0, UV1 = [c[None, :]], [np.array([[0.5, 0.5]])], [np.array([[0.0, 0.0]])]
    Rm = 0.5 * (a + b)
    for k in range(1, rings + 1):
        r = k / rings
        V.append(_superellipse(c, e1, e2, a, b, r, th))
        UV0.append(np.stack([0.5 + 0.5 * r * np.cos(th), 0.5 + 0.5 * r * np.sin(th)], 1))
        UV1.append(np.stack([th * Rm, np.full(seg, r * Rm)], 1))
    V, UV0, UV1 = np.concatenate(V), np.concatenate(UV0), np.concatenate(UV1)
    T = [[0, 1 + (i + 1) % seg, 1 + i] for i in range(seg)]
    for k in range(1, rings):
        b0, b1 = 1 + (k - 1) * seg, 1 + k * seg
        for i in range(seg):
            j = (i + 1) % seg
            T += [[b0 + i, b0 + j, b1 + i], [b0 + j, b1 + j, b1 + i]]
    T = np.array(T)
    # Water colour: the HoMM3 basin water (bluish / white pixels in the lower third of the sprite).
    rgb = sprite_rgba[..., :3].astype(np.float32)
    al = sprite_rgba[..., 3] > 127
    ys_, _ = np.nonzero(al)
    low = np.zeros_like(al)
    low[int(np.percentile(ys_, 60)):int(np.percentile(ys_, 92))] = True
    wat = al & low & (rgb[..., 2] > rgb[..., 0] + 8)
    wc = np.median(rgb[wat], 0) / 255 if wat.sum() > 20 else np.array([0.55, 0.68, 0.76])
    n_ = 128
    yy, xx = np.mgrid[0:n_, 0:n_]
    rr = np.hypot((xx + 0.5) / n_ * 2 - 1, (yy + 0.5) / n_ * 2 - 1)
    tint = np.zeros((n_, n_, 4), np.uint8)
    tint[..., :3] = (np.clip(wc, 0, 1) * 255).astype(np.uint8)
    tint[..., 3] = (np.clip(((1 - np.clip(rr, 0, 1)) * 20 + 2) / 22, 0, 1) * 255).astype(np.uint8)
    Image.fromarray(tint).save(IN_DIR / f"basin_tint_{lid}.png")
    colors = {"_SpecDir": [float(spec_l[0]), float(spec_l[1]), float(spec_l[2]), 0.0],
              "_SkyColor": [float(sky_c[0]), float(sky_c[1]), float(sky_c[2]), 1.0]}
    common = [tex("_Noise", vtex("TileNoise_23_vfx")), tex("_Noise2", vtex("TileNoise_07_vfx")),
              tex("_NormalMap", vtex("WaterNormal"), srgb=False)]
    basin_mat = material("Homm3ConfluxFlowWater", [tex("_MainTex", f"{ASSET_ROOT}/basin_tint_{lid}.png", clamp=True)] + common,
                         {"_ShoreRange": 22, "_ShoreOut": 2, "_Deep": 0.5, "_DeepPx": 10, "_Foam": 0.45, "_FoamPx": 2.5,
                          "_Feather": 2, "_Speed": Rm * 0.35, "_Scale": 2.2 / Rm, "_Stretch": 0.35, "_Ripple": 0.45,
                          "_NormalScale": 3.0 / Rm, "_Glint": 0.5}, colors)
    up = np.tile([0, 1.0, 0], (len(V), 1))
    bins = [fxmesh_row(f"Fx_Basin_{lid}", ctx.local(V), ctx.local_dir(up), UV0, T, basin_mat, uv2=UV1)]
    # --- jets: a central column and six arcs --------------------------------------------------------------------
    cam_r = np.array([ctx.cam["right"][0], 0, ctx.cam["right"][2]])
    cam_r /= np.linalg.norm(cam_r)
    cam_f = np.cross(cam_r, [0, 1.0, 0])
    polys, widths = [], []
    ns = 28
    s = np.linspace(0, 1, ns)
    col = c[None, :] + np.outer(s, [0, hv, 0])
    polys.append(col)
    widths.append(w0 * (1.5 - 0.4 * s))
    lands = []
    for az in (0, 60, 120, 180, 240, 300):
        d = math.cos(math.radians(az)) * cam_r + math.sin(math.radians(az)) * cam_f
        # the landing point on the superellipse rim direction, 70% out
        pa, pb = float(d @ e1), float(d @ e2)
        rho = 1.0 / max((abs(pa) / a) ** 4 + (abs(pb) / b) ** 4, 1e-9) ** 0.25
        L = rho * 0.72
        hor = np.outer(s, d * L)
        # rises from the vase mouth to the apex (s ~ 0.32), falls to the water at s = 1
        yv = np.where(s < 0.32, hv + (hj - hv) * np.sin(0.5 * np.pi * s / 0.32),
                      hj - hj * ((s - 0.32) / 0.68) ** 2)
        pts = np.array([c[0], y_w, c[2]]) + hor + np.outer(yv, [0, 1.0, 0])
        polys.append(pts)
        widths.append(w0 * (1.0 + 0.8 * s))
        lands.append(pts[-1])
    Vs, Ns, U0, U1, Ts = [], [], [], [], []
    off = 0
    for pts, wd in zip(polys, widths):
        v, nn_, uv, uv1, tri = ribbon(ctx, pts, wd)
        Vs.append(v); Ns.append(nn_); U0.append(uv); U1.append(uv1); Ts.append(tri + off)
        off += len(v)
    jt = np.zeros((4, 64, 4), np.uint8)
    u = (np.arange(64) + 0.5) / 64
    jt[..., 0], jt[..., 1], jt[..., 2] = 240, 248, 255
    jt[..., 3] = (np.clip(np.minimum(u, 1 - u) * 2 * 16 / 10, 0, 1) * 255).astype(np.uint8)[None, :]
    Image.fromarray(jt).save(IN_DIR / f"jet_tint_{lid}.png")
    jet_mat = material("Homm3ConfluxFlowWater", [tex("_MainTex", f"{ASSET_ROOT}/jet_tint_{lid}.png", clamp=True)] + common,
                       # Speed x scale must not be a whole number of noise tiles per second, or t = 1 s repeats t = 0.
                       {"_ShoreRange": 10, "_ShoreOut": 2, "_Deep": 0.0, "_DeepPx": 6, "_Foam": 0.9, "_FoamPx": 1.6,
                        "_Feather": 1.2, "_Speed": hj * 1.37, "_Scale": 2.5 / hj, "_Stretch": 6.0, "_Ripple": 0.9,
                        "_NormalScale": 2.5 / hj, "_Reflect": 0.1, "_Glint": 0.8, "_SpecStrength": 0.6}, colors)
    bins.append(fxmesh_row(f"Fx_FountainJets_{lid}", ctx.local(np.concatenate(Vs)), ctx.local_dir(np.concatenate(Ns)),
                           np.concatenate(U0), np.concatenate(Ts), jet_mat, uv2=np.concatenate(U1)))
    # --- splash where the jets land, mist over the fountain ---------------------------------------------------
    t_fall = 0.5
    v_up = hj * 0.35
    g_m = 2 * v_up / t_fall
    systems = []
    lift = np.array([0, max(bt["yRim"] - y_w, 0.0) + 0.3 * w0, 0])   # above the front rim, which hides the water line
    for i, lp in enumerate(lands):
        lp = lp + lift
        systems.append(psys(f"splash_{i}", A["spray"], lifetime=[0.4, 0.7], speed=[v_up * 0.6, v_up * 1.2],
                            size=[w0 * 2.5, w0 * 4.0], rate=30, maxParticles=30, shape="hemisphere", radius=w0 * 0.8,
                            shapeRot=UP, gravity=gravity_mod(ctx, g_m), pos=[float(x) for x in (lp - c)],
                            color=[0.92, 0.96, 1.0, 0.85], alphaKeys=[0, 0, 0.15, 1, 1, 0], sizeKeys=[0, 0.6, 1, 1.3],
                            rotation=[0, 360]))
    yaw_b = math.atan2(-float(e1[2]), float(e1[0]))   # the ring's local x along the basin's long axis
    systems.append(psys("foam_ring", A["spray"], lifetime=[0.6, 1.0], speed=[0], size=[w0 * 1.5, w0 * 2.6], rate=30,
                        maxParticles=36, shape="circle", radius=Rm * 0.66, radiusThickness=0.25, shapeRot=[90.0, 0, 0],
                        shapeScale=[a / Rm, b / Rm, 1], color=[0.94, 0.97, 1.0, 0.6], alphaKeys=[0, 0, 0.2, 1, 1, 0],
                        rotation=[0, 360], pos=[0, 0.002 * hj, 0],
                        rot=[0.0, math.sin(yaw_b / 2), 0.0, math.cos(yaw_b / 2)]))
    systems.append(psys("mist", A["spray"], lifetime=[2.0, 3.0], speed=[0], velY=[hj * 0.05, hj * 0.12],
                        size=[hj * 0.5, hj * 0.8], rate=3, maxParticles=10, radius=Rm * 0.5, radiusThickness=1,
                        shapeScale=[1, 0.2, 1], pos=[0, hj * 0.35, 0], color=[0.9, 0.95, 1.0, 0.18],
                        alphaKeys=[0, 0, 0.3, 1, 0.7, 0.8, 1, 0], sizeKeys=[0, 0.7, 1, 1.3], rotation=[0, 360],
                        rotSpeed=[-10, 10]))
    group = fx_group(ctx, f"Fx_FountainSpray_{lid}", c, systems)
    rep = {"basinCentre": [round(float(x), 3) for x in c], "basinHalfAxes": [round(a, 3), round(b, 3)],
           "jetApexM": round(hj, 3), "vaseM": round(hv, 3), "jetWidthM": round(w0, 3), "jets": len(polys) - 1,
           "waterColour": [round(float(x), 3) for x in wc], "floorY": round(bt["yFloor"], 3), "rimY": round(bt["yRim"], 3),
           "waterY": round(y_w, 3)}
    return bins, [group], rep


def building_animations(ctx: Ctx, prefabs: dict, mesh_geo: dict, spec_l, sky_c) -> dict:
    """Phase 4: the moving effect of every animated HoMM3 building DEF that no earlier section covers."""
    A = anim_mats()
    rep: dict = {}
    # Blacksmith: smoke from the chimney mouth (the mesh's highest vertices), plume height from the DEF.
    vw, fw, md = mesh_geo["tbelblak"]
    ymax, ptp = float(vw[:, 1].max()), float(np.ptp(vw[:, 1]))
    top = vw[vw[:, 1] >= ymax - 0.02 * ptp]
    mouth = np.array([np.median(top[:, 0]), ymax, np.median(top[:, 2])])
    cr = 0.5 * max(float(np.ptp(top[:, 0])), float(np.ptp(top[:, 2])), 1e-3)
    zc = float((mouth - ctx.cpos) @ ctx.cam["fwd"])
    mot = def_motion(ctx, "tbelblak")
    ys, xs = np.nonzero(mot)
    ph = float(ys.max() - ys.min()) * ctx.m_per_px(zc)
    cr = min(max(cr, 0.12 * ph), 0.3 * ph)
    prefabs["tbelblak"]["particles"].append(fx_group(ctx, "Fx_Smoke_tbelblak", mouth, smoke_systems(ph, cr, A)))
    mpx, mpy, _ = project(ctx.cam, mouth[None, :])
    rep["tbelblak"] = {"mouthWorld": [round(float(x), 3) for x in mouth], "plumeM": round(ph, 3), "mouthRadiusM": round(cr, 3),
                       "mouthPx": [round(float(mpx[0]), 1), round(float(mpy[0]), 1)],
                       "defPlumeBasePx": [round(float(np.median(xs[ys > ys.max() - 8])), 1), float(ys.max())]}
    # Lantern: a flickering glow in the glass (the DEF's largest moving part), both dwelling levels.
    lant = motion_parts(def_motion(ctx, "tbeldw_0"))[0]
    for lid in ("tbeldw_0", "tbeldw_0_2"):
        vw, fw, md = mesh_geo[lid]
        bw = lant["bbox"][2] - lant["bbox"][0]
        p0, z = snap_point(ctx, md, lant["cx"], lant["cy"])
        s = 0.55 * bw * ctx.m_per_px(z)
        p, _ = snap_point(ctx, md, lant["cx"], lant["cy"], toward_cam=s * 0.6)
        prefabs[lid]["particles"].append(fx_group(ctx, f"Fx_Lantern_{lid}", p, lantern_systems(s, A)))
        rep[lid] = {"glassPx": [round(lant["cx"], 1), round(lant["cy"], 1)], "sizeM": round(s, 3),
                    "world": [round(float(x), 3) for x in p]}
    # Altar of Air: glints on the six crystals, a shimmer in the doorway (DEF moving parts snapped onto the mesh).
    # Both levels use the base DEF's parts: the upgrade's doorway shimmer touches two crystals and merges with them.
    air_parts = motion_parts(def_motion(ctx, "tbeldw_1"), min_px=40, join=3)
    for lid in ("tbeldw_1", "tbeldw_1_2"):
        vw, fw, md = mesh_geo[lid]
        parts = air_parts
        base, zb = snap_point(ctx, md, parts[0]["cx"], parts[0]["cy"])
        systems = []
        info = []
        for i, pt in enumerate(parts[:8]):
            bw = pt["bbox"][2] - pt["bbox"][0] if i == 0 else math.sqrt(pt["area"])
            _, z = snap_point(ctx, md, pt["cx"], pt["cy"])
            s = bw * ctx.m_per_px(z)
            p, _ = snap_point(ctx, md, pt["cx"], pt["cy"], toward_cam=s * 0.5)
            if i == 0:
                sy = shimmer_systems(s, A)
            else:
                sy = glint_systems(str(i), s * 0.6, A, 2.5, (0.9, 0.96, 1.0))
            for q in sy:
                q["pos"] = [float(x) for x in (p - base)]
            systems += sy
            info.append({"kind": "doorway" if i == 0 else "crystal", "px": [round(pt["cx"], 1), round(pt["cy"], 1)],
                         "sizeM": round(s, 3)})
        prefabs[lid]["particles"].append(fx_group(ctx, f"Fx_AirGlints_{lid}", base, systems))
        rep[lid] = {"parts": info}
    # Altar of Water: basin water, jets, splash, mist.
    for lid in ("tbeldw_2", "tbeldw_2_2"):
        vw, fw, md = mesh_geo[lid]
        bins, groups, r = fountain(ctx, lid, vw, fw, md, sprite_alpha(ctx, lid), A, spec_l, sky_c)
        prefabs[lid]["bins"] += bins
        prefabs[lid]["particles"] += groups
        rep[lid] = r
    # Altar of Earth: sparkles over the moving region of the DEF, a box on the ring at mesh depth.
    for lid in ("tbeldw_4", "tbeldw_4_2"):
        vw, fw, md = mesh_geo[lid]
        mot = def_motion(ctx, lid)
        ys, xs = np.nonzero(mot)
        cx, cy = float(np.median(xs)), float(np.median(ys))
        p, z = snap_point(ctx, md, cx, cy)
        mpp = ctx.m_per_px(z)
        bw = float(np.percentile(xs, 95) - np.percentile(xs, 5)) * mpp
        bh = float(np.percentile(ys, 95) - np.percentile(ys, 5)) * mpp
        p, _ = snap_point(ctx, md, cx, cy, toward_cam=0.25 * bw)
        g = 5.5 * mpp
        prefabs[lid]["particles"].append(fx_group(ctx, f"Fx_EarthGlints_{lid}", p, glint_systems(
            "ring", g, A, 32, (0.95, 1.0, 0.9), box=(bw, bh, bw * 0.5))))
        rep[lid] = {"centrePx": [round(cx, 1), round(cy, 1)], "boxM": [round(bw, 3), round(bh, 3)], "glintM": round(g, 3)}
    return rep


def animation_audit(prefabs: dict, names_fn, animated_fn) -> dict:
    """Catalog block: every catalog layer whose HoMM3 DEF is animated, what moves, and our effect pieces."""
    out = {}
    for lid in sorted(prefabs):
        n = def_frames(lid)
        if n <= 1:
            continue
        if lid not in ANIM_MOVES:
            raise SystemExit(f"{lid}: DEF has {n} frames but no ANIM_MOVES entry")
        row = {"defFrames": n, "moves": ANIM_MOVES[lid]}
        if lid in ANIM_SHARED:
            row["sharedWith"] = ANIM_SHARED[lid]
            row["effects"] = animated_fn(prefabs[ANIM_SHARED[lid]])
        else:
            row["effects"] = animated_fn(prefabs[lid])
        if not row["effects"]:
            raise SystemExit(f"{lid}: DEF animated ({n} frames) but no Fx_ effect piece")
        out[lid] = row
    return out


# ------------------------------------------------------------------------------------------------ stage
def mesh_texel_density(ctx: Ctx, w: np.ndarray, uv: np.ndarray, f: np.ndarray, tex_px: float):
    """Per triangle: texture texels per 1080p screen pixel (sqrt of texel area / screen area), for triangles whose
    centroid is on screen. Returns (density, screen area)."""
    px, py, zc = project(ctx.cam, w)
    f = f[(zc[f] > 0.1).all(1)]
    a, b = px[f], py[f]
    sa = 0.5 * np.abs((a[:, 1] - a[:, 0]) * (b[:, 2] - b[:, 0]) - (a[:, 2] - a[:, 0]) * (b[:, 1] - b[:, 0]))
    t = uv[f]
    ta = 0.5 * np.abs((t[:, 1, 0] - t[:, 0, 0]) * (t[:, 2, 1] - t[:, 0, 1])
                      - (t[:, 2, 0] - t[:, 0, 0]) * (t[:, 1, 1] - t[:, 0, 1])) * tex_px * tex_px
    keep = (sa > 0.05) & (a.mean(1) >= 0) & (a.mean(1) < W) & (b.mean(1) >= 0) & (b.mean(1) < H)
    return np.sqrt(ta[keep] / sa[keep]), sa[keep]


def wquant(x: np.ndarray, w: np.ndarray, q: float) -> float:
    o = np.argsort(x)
    c = np.cumsum(w[o])
    return float(x[o][min(np.searchsorted(c, q * c[-1]), len(x) - 1)])


def _win(box) -> np.ndarray:
    m = np.zeros((H, W), bool)
    x0, y0, x1, y1 = box
    m[y0:y1, x0:x1] = True
    return m


LEGACY_MEADOW_TILE_M = 4.65  # phase 1-4 extension: the meadow_near painted crop's world tile width (stage report 4)


def texel_density_report(ctx: Ctx, prefabs: dict, zfill, nf, wts, dens_after, bake_scale: dict) -> dict:
    """Texels per 1080p screen pixel at the reference camera (area-weighted): building meshes (their own textures,
    capped at the bin maxSize) vs the terrain before phase 3 (the HoMM3-registered macro alone) and after (vanilla
    detail, capped by the bake's own texels per pixel)."""
    d_all, a_all, per, per_layer = [], [], {}, {}
    for lid, p in sorted(prefabs.items()):
        dl, al = [], []
        for b in p["bins"]:
            if "_uv" not in b:
                continue
            with Image.open(PROJECT / b["texture"]) as im:
                tex_px = min(max(im.size), b.get("maxSize", 1024))
            d, a = mesh_texel_density(ctx, b["_world"], b["_uv"], b["_faces"], tex_px)
            if len(d):
                per[b["name"]] = round(wquant(d, a, 0.5), 2)
                dl.append(d); al.append(a)
        if dl:
            per_layer[lid] = {"median": round(wquant(np.concatenate(dl), np.concatenate(al), 0.5), 2),
                              "screenPx": int(np.concatenate(al).sum())}
            d_all += dl; a_all += al
    d_all = np.concatenate(d_all); a_all = np.concatenate(a_all)
    t = math.tan(math.radians(ctx.cam["fov"]) / 2)
    m_px = 2 * zfill * t / H
    live = wts.sum(-1) > 0.01
    rect = np.zeros((H, W), bool)
    rect[:TH, :TW] = True
    before = np.zeros((H, W), np.float32)
    before[rect] = E.original().size[0] / TW  # the HoMM3 screen's own texels (800 across 1440)
    # Extension before phase 3: seamless crops of the painting tiled in world space; the meadow crop covers ~81 % of
    # it: its source pixels across its tile width, per screen pixel.
    ext = ~rect
    x0, _y0, x1, _y1 = E.CROPS["meadow_near"]
    before[ext] = np.minimum((x1 - x0) / LEGACY_MEADOW_TILE_M * m_px[ext], 2.0)

    def stat(arr, m):
        v = arr[m & live]
        return {"median": round(float(np.median(v)), 2), "p10": round(float(np.percentile(v, 10)), 2),
                "p90": round(float(np.percentile(v, 90)), 2)} if v.size else None
    Image.fromarray(np.clip(dens_after / 2.0 * 255, 0, 255).astype(np.uint8)).save(WORK / "texel_density_after.png")
    Image.fromarray(np.clip(before / 2.0 * 255, 0, 255).astype(np.uint8)).save(WORK / "texel_density_before.png")
    return {"unit": "texels per 1080p screen pixel at the cityHuman2 reference camera (area-weighted)",
            "buildings": {"median": round(wquant(d_all, a_all, 0.5), 2), "p10": round(wquant(d_all, a_all, 0.1), 2),
                          "p90": round(wquant(d_all, a_all, 0.9), 2), "perLayer": per_layer, "perPiece": per},
            "terrainBefore": {"townRect": stat(before, rect), "extension": stat(before, ext),
                              **{k: stat(before, _win(v)) for k, v in CLOSEUP_WINDOWS.items()}},
            "terrainAfter": {"townRect": stat(dens_after, rect), "extension": stat(dens_after, ext),
                             **{k: stat(dens_after, _win(v)) for k, v in CLOSEUP_WINDOWS.items()}},
            "bakeTexelsPerPixel": bake_scale,
            "note": "skirts (footing) carry the terrain's detail at 2x; terrain before = the macro's unique source "
                    "texels (the bake held them at 2 texels/px, i.e. upsampled)"}


def pan_render_specs() -> list[dict]:
    """Render the sampled pan extremes with the same aspect-dependent root scaling as the runtime v2 path."""
    poses = PAN.proof_poses()
    targets = (("", W, H, {p["name"] for p in poses}),
               ("_4096x2160", 4096, 2160, {"default", "sweep_left", "sweep_right"}),
               ("_21x9", 2560, 1080, {"default", "sweep_left", "sweep_right"}))
    out = []
    for suffix, w, h, names in targets:
        scale_x = (w / h) / (W / H)
        for p in poses:
            if p["name"] in names:
                out.append({"name": p["name"] + suffix, "state": "full", "pos": p["pos"], "fwd": p["fwd"],
                            "up": p["up"], "w": w, "h": h, "scaleX": scale_x, "scaleY": 1.0})
    return out


def ground_fields(ctx: Ctx, fd: dict, det) -> dict:
    """The frame's ground from one frame_depth: classes, splat weights, phase-5 maps, the relieved terrain grid (ridge
    curtains cut) and its depth. Leaves ctx on fd (set_env)."""
    ctx.set_env(fd)
    zs = fd["zs"]
    grid0 = E.terrain_mesh(ctx, zs, GRID)
    nf = E.frame_normals(grid0)
    zfill = E.filled_depth(zs)
    # Depth-derived normals wander pixel to pixel; the detail's projection weights and footprints take a smoothed
    # copy so the pattern does not smear where they do.
    nf_frame = cv2.GaussianBlur(nf.astype(np.float32), (0, 0), 4.0)
    nf_frame /= np.linalg.norm(nf_frame, axis=-1, keepdims=True) + 1e-9
    X = N5.ext_classes(ctx, fd, nf, zfill)
    cls = classify(ctx, fd, X["cls_f"])
    # Phase 3: vanilla terrain detail multiplied into the painted rect (conflux_full3d_detail).
    classes = {"SKY": SKY, "GRASS": GRASS, "FOREST": FOREST, "ROCK": ROCK, "SNOW": SNOW, "DIRT": DIRT}
    wts = D.splat_weights(ctx, cls, nf_frame, zfill, fd["water"], classes)
    if os.environ.get("CONFLUX_DETAIL_OFF") == "1":  # phase-2 look, only for before/after renders
        wts[:] = 0
    excl = exclusion_mask(ctx)
    # Phase 5 (conflux_full3d_nearfield): the extension's albedo is the vanilla terrain textures (the painting only as
    # low-frequency colour), blended into the rect over a noise-broken world band; relief in the near field; the
    # terrain split into near / right pieces baked at higher texel density.
    S5 = N5.prepare(ctx, fd, X, nf, nf_frame, wts, zfill, excl, det, DETAIL_CACHE)
    del X
    grid = E.terrain_mesh(ctx, N5.seam_depth(zs), GRID, disp=N5.relief_dz(ctx, S5))  # seam kink smoothed (shading)
    # Phase 6b: the grid's ridge curtains (triangles bridging a near ridge to the far slope along the rest rays) are
    # cut and a back layer continues the far surface under the ridge (conflux_full3d_curtain).
    back = CU.apply(ctx, grid)
    zrel = N5.frame_relief_depth(ctx, S5)
    return {"zs": zs, "zfill": zfill, "nf_frame": nf_frame, "cls": cls, "wts": wts, "excl": excl, "S5": S5,
            "grid": grid, "back": back, "zrel": zrel,
            "zplace": np.where(np.isnan(zs), B.Z_FAR, zrel).astype(np.float64)}


def stage() -> dict:
    ctx = Ctx()
    WORK.mkdir(parents=True, exist_ok=True)
    if IN_DIR.exists():
        shutil.rmtree(IN_DIR)
    IN_DIR.mkdir(parents=True)
    lm = json.loads((B.REFS / "layers" / "building_layer_map.json").read_text(encoding="utf-8-sig"))
    reach = sorted({v for lv in lm["nativeLevels"].values() if isinstance(lv, dict) for v in lv.values()})
    report: dict = {"schema": "homm3_conflux_full3d_stage.v2", "depthScale": ctx.scale, "reachable": reach,
                    "references": ["Conflux-in-background.png (HoMM3 town screen)", "layers/*.png (HoMM3 building art)"]}

    # --- environment -----------------------------------------------------------------------------
    det = D.Detail(DETAIL_CACHE)
    # Placement frame: the same ground with the river channels carved without the entry taper (conflux_full3d_env
    # entry_taper). Every scatter / dressing draw reads it, so the taper reshapes the rendered channel at the HoMM3
    # exits and leaves every prop where it was (a mask change anywhere shifts the shared draws of all later props).
    fd_place = E.frame_depth(ctx, WORK, taper=False)
    gp = ground_fields(ctx, fd_place, det)
    fd = E.frame_depth(ctx, WORK)
    g = ground_fields(ctx, fd, det)
    zs, zfill, nf_frame, cls, wts, excl, S5, grid, back, zrel = (
        g[k] for k in ("zs", "zfill", "nf_frame", "cls", "wts", "excl", "S5", "grid", "back", "zrel"))
    np.save(WORK / "phase5_zmap.npy", np.where(np.isnan(zs), np.inf, zrel).astype(np.float32))  # report metrics
    Image.fromarray(fd["water"].astype(np.uint8) * 255).save(WORK / "phase5_water.png")
    ctx.z = g["zplace"]  # props stand on the relieved ground
    # alb_lin: the macro (painting albedo in the rect, L0 in the extension) at frame resolution: the skirts feather
    # into it and take the same world-space detail afterwards.
    alb_lin = S5["alb_frame"]
    pieces = N5.split_terrain(grid)
    P = grid["P"].reshape(-1, 3)
    Nn = grid["n"].reshape(-1, 3)
    piece_rep = {}
    skip_main = lambda px, py: N5.piece_of(px, py) >= 0  # noqa: E731
    for nm, pc in pieces.items():
        texp = IN_DIR / ("terrain_albedo.png" if pc["id"] < 0 else f"{nm}_albedo.png")
        lin = N5.bake_window(ctx, S5, pc["box"], pc["scale"], skip=skip_main if pc["id"] < 0 else None)
        Image.fromarray((lin_to_srgb(lin) * 255 + 0.5).astype(np.uint8)).save(texp)
        del lin
        used, tris_p, uv_p = N5.piece_mesh(grid, pc)
        write_bin(IN_DIR / f"{nm}.bytes", ctx.local(P[used]), ctx.local_dir(Nn[used]), uv_p, [tris_p])
        piece_rep[nm] = {"frameBox": list(pc["box"]), "texelsPerPx": pc["scale"], "tris": int(len(tris_p)),
                         "verts": int(len(used)), "texture": texp.name}
    back_rep = {}
    for nm, (bP, bn, buv, bt) in CU.split_back(back, pieces, N5.piece_of, W, H).items():
        bname = "Mesh_Back_" + nm[len("Mesh_"):]
        write_bin(IN_DIR / f"{bname}.bytes", ctx.local(bP), ctx.local_dir(bn), buv, [bt])
        back_rep[bname] = {"tris": int(len(bt)), "verts": int(len(bP)), "texture": piece_rep[nm]["texture"], "of": nm}
    OUT.mkdir(parents=True, exist_ok=True)
    streak_npz = OUT / "terrain_streak.npz"
    np.savez_compressed(streak_npz, **CU.streak_arrays(ctx, grid, back))
    report["curtain"] = {**back["report"], "backPieces": back_rep, "file": streak_npz.name,
                         "sha256": hashlib.sha256(streak_npz.read_bytes()).hexdigest()}
    spl = np.clip(wts, 0, 1) @ np.array([[90, 170, 60], [170, 130, 80], [130, 130, 140], [245, 245, 255]], np.float32)
    Image.fromarray(np.clip(spl, 0, 255).astype(np.uint8)).save(WORK / "detail_splat.png")
    Image.fromarray((np.clip(S5["w_syn"], 0, 1) * 255).astype(np.uint8)).save(WORK / "phase5_synth_weight.png")
    Image.fromarray((np.clip(S5["rel"], 0, 1) * 255).astype(np.uint8)).save(WORK / "phase5_relief_weight.png")
    scale_map = np.full((H, W), N5.MAIN_SCALE, np.float32)
    yy, xx = np.mgrid[0:H, 0:W]
    pid = N5.piece_of(xx, yy)
    scale_map[(pid >= 0) & (pid < N5.NEAR_COLS)] = N5.NEAR_SCALE
    scale_map[pid == N5.NEAR_COLS] = N5.RIGHT_SCALE
    dens_after = N5.density_after(ctx, S5, D.density_map(ctx, det, zfill, nf_frame, wts, 99.0), scale_map)
    report["detail"] = {"sources": det.prov, "layers": {k: {"texture": v[0], "tileM": v[2], "strength": v[3],
                                                             "chroma": v[4]} for k, v in D.DETAIL_SOURCES.items()},
                        "levelStep": D.LEVEL_STEP, "levelGain": list(D.LEVEL_GAIN), "bankM": D.BANK_M}
    Image.fromarray((np.array([[120, 160, 230], [110, 170, 60], [30, 80, 40], [120, 105, 90], [240, 240, 250],
                               [200, 170, 110], [40, 110, 220]], np.uint8))[cls]).save(WORK / "terrain_classes.png")
    tot = sum(S5["W4share"].values()) or 1.0
    report["terrain"] = {"verts": int(len(P)), "tris": int(len(grid["tris"])), "snappedSilhouetteVerts": grid["snapped"],
                         "calibration": fd["calib"], "pieces": piece_rep,
                         "extensionClassShare": {k: round(v / tot, 3) for k, v in S5["W4share"].items()},
                         "classColoursLinear": S5["classColours"]}
    # Water: flow-mapped mesh.
    wm = E.water_mesh(ctx, fd, grid)
    Image.fromarray(wm["tint"]).save(IN_DIR / "water_tint.png")
    wP, wn, wuv, wtris, wflow = I.compact(wm["P"].reshape(-1, 3), wm["n"].reshape(-1, 3), grid["uv"], wm["tris"], wm["flow_uv"])
    # Phase 3b: vanilla river lighting (Mtl_River_Water / Hex/Sea): WaterNormal, a fixed specular direction (here a
    # light low over the far side of the scene, so the rivers glint toward the camera), a fresnel sky reflection.
    fwd_h = np.asarray(ctx.cam["fwd"], np.float64) * np.array([1, 0, 1])
    fwd_h /= np.linalg.norm(fwd_h) + 1e-9
    spec_w = fwd_h * math.cos(math.radians(WATER_SPEC_EL)) + np.array([0, 1, 0]) * math.sin(math.radians(WATER_SPEC_EL))
    spec_l = np.asarray(ctx.local_dir(spec_w[None, :]), np.float64).reshape(3)
    sky_px = fd["paint"][(cls[:TH, :TW] == SKY)] if (cls[:TH, :TW] == SKY).any() else np.array([[150, 180, 225]])
    sky_c = np.median(sky_px.reshape(-1, 3), 0) / 255.0
    water_mat = material("Homm3ConfluxFlowWater", [
        tex("_MainTex", f"{ASSET_ROOT}/water_tint.png", clamp=True),
        tex("_Noise", vtex("TileNoise_23_vfx")), tex("_Noise2", vtex("TileNoise_07_vfx")),
        tex("_NormalMap", vtex("WaterNormal"), srgb=False)],
        {"_ShoreRange": E.SHORE_RANGE, "_ShoreOut": E.SHORE_OUT, "_Deep": 0.7, "_DeepPx": 16, "_Foam": 0.22},
        {"_SpecDir": [float(spec_l[0]), float(spec_l[1]), float(spec_l[2]), 0.0],
         "_SkyColor": [float(sky_c[0]), float(sky_c[1]), float(sky_c[2]), 1.0]})
    env_bins = [fxmesh_row("Fx_Water", ctx.local(wP), ctx.local_dir(wn), wuv, wtris, water_mat, uv2=wflow)]
    vv = (np.mod(wm["vfull"], 4.0) / 4.0 * 255).astype(np.uint8)
    flowviz = np.asarray(Image.open(IN_DIR / "water_tint.png").convert("RGB")).copy()
    flowviz[~fd["water"]] = (flowviz[~fd["water"]] * 0.35).astype(np.uint8)
    flowviz[fd["water"]] = np.stack([vv, vv, 255 - vv], -1)[fd["water"]]
    Image.fromarray(flowviz).save(WORK / "flow_v.png")
    report["water"] = {"tris": int(len(wtris)), "sources": wm["sources"], "downstreamMaxM": round(wm["vMaxM"], 2),
                       "flowCheck": "flow_v.png: stripes = 4 m bands of the downstream coordinate; they advance from each "
                                    "river's mountain source toward the camera"}
    sky = E.sky_dome(ctx, fd, DOME_R)
    Image.fromarray(sky["img"]).save(IN_DIR / "sky_dome.png")
    write_bin(IN_DIR / "Sky_Dome.bytes", ctx.local(sky["P"]), ctx.local_dir(sky["n"]), sky["uv"], [sky["tris"]])
    env = {"key": ENV_KEY, "layerId": "environment", "pieces": [], "sprites": [], "discs": [], "scatters": [], "particles": [],
           "bins": [
               *[{"name": nm, "mesh": f"{ASSET_ROOT}/{nm}.bytes", "texture": f"{ASSET_ROOT}/{pr['texture']}",
                  "kind": "lit", "maxSize": 4096, "mipBias": TERRAIN_MIP_BIAS, "aniso": TERRAIN_ANISO}
                 for nm, pr in piece_rep.items()],
               *[{"name": nm, "mesh": f"{ASSET_ROOT}/{nm}.bytes", "texture": f"{ASSET_ROOT}/{pr['texture']}",
                  "kind": "lit", "maxSize": 4096, "mipBias": TERRAIN_MIP_BIAS, "aniso": TERRAIN_ANISO}
                 for nm, pr in back_rep.items()],
               {"name": "Sky_Dome", "mesh": f"{ASSET_ROOT}/Sky_Dome.bytes", "texture": f"{ASSET_ROOT}/sky_dome.png",
                "kind": "sky", "maxSize": 4096}] + env_bins}

    # --- scatter props -----------------------------------------------------------------------------
    town = np.zeros((H, W), bool)
    town[:TH, :TW] = True
    # Conifers never stand in front of a building (they would hide it): the plots' shadow toward the camera.
    front = cv2.dilate(excl.astype(np.uint8), np.ones((61, 1), np.uint8), anchor=(0, 0)).astype(bool)
    # Placement reads the placement frame (see fd_place); ctx.z returns to the rendered ground after near_dressing.
    ctx.z = gp["zplace"]
    zsf = ctx.z
    water = fd_place["water"]
    cls_r, cls = cls, gp["cls"]
    water_near = cv2.dilate(water.astype(np.uint8), np.ones((9, 9), np.uint8)).astype(bool)
    ground_ok = ~excl & ~water_near & (cls != SKY) & (zsf < 80)
    nfr = E.frame_normals(gp["grid"])
    flatish = nfr[..., 1] > math.cos(math.radians(38))
    sub = np.zeros((H, W), bool)
    sub[::3, ::3] = True
    bank = cv2.dilate(water.astype(np.uint8), np.ones((31, 31), np.uint8)).astype(bool) & ~water_near
    props = {
        "prop_conifer_a": {"cand": ground_ok & flatish & (cls == FOREST) & sub & (zsf > 22) & ~front, "spacing": 1.5,
                           "cap": 300, "h": (2.2, 3.6), "tris": 1200, "cls": FOREST},
        "prop_conifer_b": {"cand": None, "spacing": 1.5, "cap": 220, "h": (1.8, 3.0), "tris": 1200, "cls": FOREST},
        # Near the camera the decimated props read as low-poly clutter: nothing closer than 20 m (boulders 14 m).
        "prop_bush": {"cand": ground_ok & flatish & (((cls == GRASS) & bank) | (cls == FOREST)) & sub & (zsf > 20),
                      "spacing": 1.6, "cap": 110, "h": (0.5, 0.95), "tris": 900, "cls": GRASS},
        "prop_boulders": {"cand": ground_ok & flatish & ((cls == ROCK) | bank) & sub & (zsf > 14) & (zsf < 45),
                          "spacing": 2.4, "cap": 45, "h": (0.45, 1.1), "tris": 900, "cls": ROCK, "optional": True},
    }
    taken: list = []
    scat_rep = {}
    conifer_b_pts: list = []
    for pname, cfg in props.items():
        glb = MESHY / pname / B.MESH_ATTEMPT / "model.glb"
        v, n, uv, f = load_glb_full(glb)
        v, n, uv, f = decimate(v, n, uv, f, cfg["tris"])
        lo, hi = v.min(0), v.max(0)
        v = v - np.array([(lo[0] + hi[0]) / 2, lo[1], (lo[2] + hi[2]) / 2])  # base at 0, centred footprint
        mh = float(hi[1] - lo[1])
        write_bin(IN_DIR / f"{pname}.bytes", v, n, uv, [f])
        ref = ctx.paint[(cls == cfg["cls"]) & ground_ok & town].reshape(-1, 3)
        ref = ref[ctx.rng.choice(len(ref), min(len(ref), 20000), replace=False)] if len(ref) else None
        tex_ = texture_transfer(base_color(pname), ref, None, ctx.rig, ctx.sun, n[n[:, 1] > -0.2])
        Image.fromarray(tex_).resize((1024, 1024), Image.LANCZOS).save(IN_DIR / f"{pname}_albedo.png")
        if pname == "prop_conifer_b":
            pts = conifer_b_pts  # one joint Poisson draw for both conifers, variants alternate
        else:
            pts = poisson(ctx, cfg["cand"], zsf, cfg["spacing"],
                          cfg["cap"] + (props["prop_conifer_b"]["cap"] if pname == "prop_conifer_a" else 0), taken)
            if pname == "prop_conifer_a":
                pts, conifer_b_pts = pts[0::2], pts[1::2]
        xf = []
        for w, x, y in pts:
            hgt = ctx.rng.uniform(*cfg["h"])
            base = w - np.array([0, 0.08 * hgt, 0])  # sink the base so slopes never show a gap
            xf += place_xform(ctx, base, float(ctx.rng.uniform(0, 360)), hgt / mh)
        if not xf and not cfg.get("optional"):
            raise SystemExit(f"{pname}: no scatter positions")
        if xf:
            env["scatters"].append({"name": "Mesh_Scatter_" + pname.replace("prop_", ""), "mesh": f"{ASSET_ROOT}/{pname}.bytes",
                                    "texture": f"{ASSET_ROOT}/{pname}_albedo.png", "xforms": xf})
        scat_rep[pname] = {"instances": len(pts), "inExtension": int(sum(1 for _, x, y in pts if not town[y, x])),
                           "tris": int(len(f)), "verts": int(len(v))}
    report["scatter"] = scat_rep
    report["meadowDressing"] = meadow_dressing(ctx, env, zsf, ground_ok, flatish, water, town, taken)
    grove_bases = report["meadowDressing"].pop("_bases", [])
    # Phase 5: the near field's own geometry (grass tufts, flowers, pebbles, roots, near rocks).
    report["nearDressing"] = near_dressing(ctx, env, gp["S5"], gp["grid"], excl, front, cls, taken, grove_bases)
    ctx.z, cls = g["zplace"], cls_r
    gp_grid = gp["grid"]
    del gp

    # Bridge: registered against the painted footbridge box of the HoMM3 background.
    bx0, by0, bx1, by1 = (215, 292, 285, 318)
    box = np.zeros((H, W), np.uint8)
    box[round(by0 * B.SCALE):round(by1 * B.SCALE), round(bx0 * B.SCALE):round(bx1 * B.SCALE)] = 1
    stone = (lum(srgb_to_lin(ctx.paint.astype(np.float32) / 255)) > 0.18) & (cls != WATER)
    tgt = (box.astype(bool) & stone).astype(np.uint8)
    fb = fit_new(ctx, "bridge", "prop_bridge", tgt, yaws=list(range(-30, 31, 10)) + list(range(150, 211, 10)))
    vb, nb, _, _ = load_glb_full(MESHY / "prop_bridge" / B.MESH_ATTEMPT / "model.glb")
    Image.fromarray(texture_transfer(base_color("prop_bridge"), ctx.paint[box.astype(bool) & stone], None, ctx.rig, ctx.sun,
                                     nb[nb[:, 1] > -0.2])).save(IN_DIR / "prop_bridge_albedo.png")
    env["bins"].append(piece_row(ctx, "Bridge", "prop_bridge", "prop_bridge_albedo.png", fb["rootPosition"], fb["yaw"], fb["scale"]))
    report["bridge"] = {k: fb[k] for k in ("yaw", "scale", "iou", "worldHeight")}

    # --- phase 6: outer world for sampled town-camera pan paths (conflux_full3d_periphery) ---
    per = P6.build(sys.modules[__name__], ctx, fd, grid, S5, wm["vfull"], water_mat, taken, fd_place, gp_grid)
    env["bins"] += per["bins"]
    report["periphery"] = per["report"]

    # --- buildings ------------------------------------------------------------------------------------
    prefabs: dict[str, dict] = {}

    def prefab(layer: str) -> dict:
        return prefabs.setdefault(layer, {"key": PREFIX + layer, "layerId": layer, "pieces": [], "sprites": [],
                                          "discs": [], "bins": [], "scatters": [], "particles": []})
    lab = B.LAB / "data"
    for row in ctx.spec["meshes"]:
        name, layer, mesh = row["name"], row["layer"], row.get("mesh", row["name"])
        shutil.copy2(lab / row["baseColor"], IN_DIR / row["baseColor"])
        prefab(layer)["bins"].append(piece_row(ctx, name, mesh, row["baseColor"], row["rootPosition"], row["yaw"], row["scale"],
                                                 row.get("stretchY", 1.0), row.get("kneeY", 0.0), row.get("kneeScale", 0.0)))
    M = vanilla_mats()
    # Portal: the lane's disc geometry (from the ring's hole) with the differential-spiral shader.
    portal_rep = {}
    for pr in ctx.spec["projected"]:
        if pr["role"] == "hole" and pr.get("instance") in ("tbeldw_5_frame", "tbeldw_5_2"):
            tmp = WORK / "disc_tmp"
            tmp.mkdir(exist_ok=True)
            d = S.disc_from_hole(pr, ctx.C, ctx.cpos, ctx.cam, lab, tmp, ctx.scale, pr["instance"])
            dv, duv, dt = disc_polar(float(d["radius"]))
            pm = material("Homm3ConfluxPortal", [tex("_Noise", vtex("TileNoise_23_vfx")), tex("_Noise2", vtex("TileNoise_01_vfx"))])
            prefab(pr["layer"])["bins"].append(fxmesh_row(f"Fx_Portal_{pr['layer']}", dv, np.tile([0, 0, -1.0], (len(dv), 1)),
                                                          duv, dt, pm, pos=d["center"]))
            portal_rep[pr["layer"]] = {"radiusPrefab": round(float(d["radius"]), 4)}
    report["portal"] = portal_rep
    # New registered dwellings.
    fit_rep = {}
    for layer, cfg in NEW_FITS.items():
        rgba = sprite_alpha(ctx, layer)
        tgt = (rgba[..., 3] > 127).astype(np.uint8)
        r = dict(fit_new(ctx, layer, cfg["mesh"], tgt, cfg.get("yaws")))
        vr, _ = load_glb_unity(MESHY / cfg["mesh"] / B.MESH_ATTEMPT / "model.glb")
        lo_, hi_ = vr.min(0), vr.max(0)
        c_ = np.array([(lo_[0] + hi_[0]) / 2, lo_[1], (lo_[2] + hi_[2]) / 2])
        Rm = yaw_matrix(r["yaw"])
        # Terrain-embedded dwellings: their Meshy base (crag / rocky ring) sinks a little into the terrain.
        sink = 0.10 * float(np.ptp(vr[:, 1])) * r["scale"]
        root_ = np.asarray(r["position"]) - np.array([0, sink, 0]) - Rm @ (c_ * r["scale"])
        _, nn, _, _ = load_glb_full(MESHY / cfg["mesh"] / B.MESH_ATTEMPT / "model.glb")
        tex_ = texture_transfer(base_color(cfg["mesh"]), rgba[tgt.astype(bool)][:, :3], None, ctx.rig, ctx.sun, nn[nn[:, 1] > -0.2])
        Image.fromarray(tex_).save(IN_DIR / f"{cfg['mesh']}_full3d_albedo.png")
        for lid in [layer] + [k for k, v in SHARED.items() if v == layer]:
            prefab(lid)["bins"].append(piece_row(ctx, cfg["mesh"] if lid == layer else lid, cfg["mesh"],
                                                   f"{cfg['mesh']}_full3d_albedo.png", root_, r["yaw"], r["scale"], rot=Rm))
        fit_rep[layer] = {k: round(r[k], 4) if isinstance(r[k], float) else r[k] for k in ("yaw", "scale", "iou", "precision", "recall", "worldHeight")}
    report["fits"] = fit_rep

    # Mushroom clusters on the painted mushrooms (orange caps) of tbeldw_0_2 / tbelhrd2.
    mv, mn, muv, mf = load_glb_full(MESHY / "prop_mushrooms" / B.MESH_ATTEMPT / "model.glb")
    mv, mn, muv, mf = decimate(mv, mn, muv, mf, 3000)
    lo, hi = mv.min(0), mv.max(0)
    mv = mv - np.array([(lo[0] + hi[0]) / 2, lo[1], (lo[2] + hi[2]) / 2])
    mh = float(hi[1] - lo[1])
    write_bin(IN_DIR / "prop_mushrooms.bytes", mv, mn, muv, [mf])
    mush_rep = {}
    for layer in MUSHROOM_LAYERS:
        rgba = sprite_alpha(ctx, layer)
        hsv = cv2.cvtColor(rgba[..., :3], cv2.COLOR_RGB2HSV).astype(np.float32)
        orange = (hsv[..., 0] * 2 >= 12) & (hsv[..., 0] * 2 <= 42) & (hsv[..., 1] > 110) & (hsv[..., 2] > 110) & (rgba[..., 3] > 127)
        lantern = np.asarray(Image.open(B.WORK / "fits" / "fitmask_tbeldw_0.png").convert("L")) > 127
        orange &= ~cv2.dilate(lantern.astype(np.uint8), np.ones((9, 9), np.uint8)).astype(bool)
        blobs = cv2.dilate(orange.astype(np.uint8), np.ones((9, 9), np.uint8))
        nlab, labels, st, cen = cv2.connectedComponentsWithStats(blobs)
        xf = []
        ref = rgba[orange][:, :3]
        for i in range(1, nlab):
            x, y, w_, h_, area = st[i]
            if area < 60:
                continue
            bx, byy = x + w_ / 2, y + h_
            wpos = ctx.world_at(np.array(bx), np.array(min(byy + 0.2 * h_, H - 1)))
            zc = float((wpos - ctx.cpos) @ ctx.cam["fwd"])
            hgt = max(h_ * 1.25, 10) * ctx.m_per_px(zc)
            xf += place_xform(ctx, wpos - np.array([0, 0.05 * hgt, 0]), float(ctx.rng.uniform(0, 360)), hgt / mh)
        if xf:
            prefab(layer)["scatters"].append({"name": "Mesh_Mushrooms", "mesh": f"{ASSET_ROOT}/prop_mushrooms.bytes",
                                              "texture": f"{ASSET_ROOT}/prop_mushrooms_albedo.png", "xforms": xf})
        mush_rep[layer] = len(xf) // 8
        if layer == MUSHROOM_LAYERS[0]:
            tex_ = texture_transfer(base_color("prop_mushrooms"), ref, None, ctx.rig, ctx.sun, mn[mn[:, 1] > -0.2])
            Image.fromarray(tex_).resize((1024, 1024), Image.LANCZOS).save(IN_DIR / "prop_mushrooms_albedo.png")
    report["mushrooms"] = mush_rep

    # --- footing: every building layer's painted base as a lit membrane -----------------------------------
    for lid in LAVA_LAYERS:
        prefab(lid)
    skirt_rep = {}
    skirts = {}
    mesh_geo: dict[str, tuple] = {}
    bld_cov = np.zeros((H, W), bool)   # every building mesh's screen coverage (the sharpness check's building mask)
    for lid in sorted(prefabs):
        if lid in SKY_FX_LAYERS:
            continue
        p = prefabs[lid]
        rgba = sprite_alpha(ctx, lid)
        mesh_bins = [b for b in p["bins"] if "_world" in b]
        whole = lid in LAVA_LAYERS
        if mesh_bins:
            vw = np.concatenate([b["_world"] for b in mesh_bins])
            offs = np.cumsum([0] + [len(b["_world"]) for b in mesh_bins[:-1]])
            fw = np.concatenate([b["_faces"] + o for b, o in zip(mesh_bins, offs)])
            md = I.raster_depth(ctx.cam, vw, fw)
            bld_cov |= np.isfinite(md)
            mesh_geo[lid] = (vw, fw, md)   # phase 4: the building animations snap to this depth / geometry
        else:
            md = np.full((H, W), np.inf, np.float32)
        if lid in LEDGE_LAYERS:
            # The Altar of Air's mesh ends in a snow slab over a far slope: a ledge from the slab down to the slope.
            near = np.zeros((H, W), bool)
            if np.isfinite(md).any():
                yc, xc = np.nonzero(np.isfinite(md))
                near[max(0, yc.min() - 150):yc.max() + 150, max(0, xc.min() - 150):xc.max() + 150] = True
            snow_px = alb_lin[(cls == SNOW) & near]
            snow_lin = np.median(snow_px, 0) if len(snow_px) > 50 else np.array([0.62, 0.66, 0.74], np.float32)
            rock_px = alb_lin[(cls == ROCK) & near]
            if len(rock_px) > 50:
                # The lit crag faces (upper luminance half): the shadowed ones made the ledge a dark block under the slab.
                rl = rock_px @ np.array([0.2126, 0.7152, 0.0722], np.float32)
                rock_lin = np.median(rock_px[rl >= np.percentile(rl, 65)], 0)
            else:
                rock_lin = np.array([0.12, 0.12, 0.14], np.float32)
            sk = I.ledge(ctx, md, fd, alb_lin, snow_lin.astype(np.float32), rock_lin.astype(np.float32))
        else:
            sk = I.skirt(ctx, lid, rgba, md, fd, alb_lin, whole_sprite=whole)
        if sk is None:
            skirt_rep[lid] = None
            continue
        nm = f"Mesh_Skirt_{lid}"
        # Phase 3: the skirt texture at 2x with the same world-space detail as the terrain it feathers into.
        sx0, sy0, sx1, sy1 = sk["stats"]["bbox"]
        simg = cv2.resize(sk["img"], ((sx1 - sx0) * 2, (sy1 - sy0) * 2), interpolation=cv2.INTER_LINEAR)
        simg = D.apply_to_frame_texture(ctx, det, srgb_to_lin(simg.astype(np.float32) / 255), sx0, sy0, 2.0,
                                        np.where(np.isfinite(sk["z"]), sk["z"], zfill), nf_frame, wts,
                                        town_rect=(TW, TH))
        sk["img"] = (lin_to_srgb(simg) * 255 + 0.5).astype(np.uint8)
        Image.fromarray(sk["img"]).save(IN_DIR / f"{nm}_albedo.png")
        write_bin(IN_DIR / f"{nm}.bytes", ctx.local(sk["P"]), ctx.local_dir(sk["n"]), sk["uv"], [sk["tris"]])
        p["bins"].append({"name": nm, "mesh": f"{ASSET_ROOT}/{nm}.bytes", "texture": f"{ASSET_ROOT}/{nm}_albedo.png",
                          "kind": "lit", "maxSize": 2048, "mipBias": TERRAIN_MIP_BIAS, "aniso": TERRAIN_ANISO})
        skirts[lid] = sk
        skirt_rep[lid] = sk["stats"]
    report["footing"] = skirt_rep
    Image.fromarray(bld_cov.astype(np.uint8) * 255).save(WORK / "building_coverage.png")

    # --- fire pit: animated lava over the painted crater + flames, smoke, embers --------------------------
    lava_rep = {}
    for lid in LAVA_LAYERS:
        sk = skirts.get(lid)
        if sk is None:
            raise SystemExit(f"{lid}: the crater needs its footing membrane (EnsureLayer needs a Mesh_ piece)")
        rgba = sprite_alpha(ctx, lid)
        hsv = cv2.cvtColor(rgba[..., :3], cv2.COLOR_RGB2HSV).astype(np.float32)
        hot = ((hsv[..., 0] * 2 >= 5) & (hsv[..., 0] * 2 <= 58) & (hsv[..., 1] > 110) & (hsv[..., 2] > 140)
               & (rgba[..., 3] > 127) & sk["region"])
        hot = cv2.morphologyEx(hot.astype(np.uint8), cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8)).astype(bool)
        pm = I.patch_mesh(ctx, hot, sk["z"], 0.994)
        if pm is None:
            raise SystemExit(f"{lid}: no lava pixels found in the sprite")
        x0, y0, x1, y1 = pm["bbox"]
        Image.fromarray(rgba[y0:y1, x0:x1, :3]).save(IN_DIR / f"lava_paint_{lid}.png")
        mask_img = cv2.GaussianBlur(hot[y0:y1, x0:x1].astype(np.float32), (0, 0), 1.2)
        Image.fromarray((np.clip(mask_img, 0, 1) * 255).astype(np.uint8)).save(IN_DIR / f"lava_mask_{lid}.png")
        lm_ = material("Homm3ConfluxLava", [
            tex("_MainTex", f"{ASSET_ROOT}/lava_paint_{lid}.png", clamp=True),
            tex("_Mask", f"{ASSET_ROOT}/lava_mask_{lid}.png", clamp=True, srgb=False),
            tex("_Lava", vtex("lava_test_03_vfx")), tex("_Noise", vtex("TileNoise_23_vfx"))])
        lP, ln, luv, lt = I.compact(pm["P"], pm["n"], pm["uv"], pm["tris"])
        prefabs[lid]["bins"].append(fxmesh_row(f"Fx_Lava_{lid}", ctx.local(lP), ctx.local_dir(ln), luv, lt, lm_))
        ys_, xs_ = np.nonzero(hot)
        cx, cy = float(np.median(xs_)), float(np.median(ys_))
        cw = ctx.cpos + rays(ctx.cam, np.float64(cx), np.float64(cy)) * float(sk["z"][int(cy), int(cx)])
        zc = float((cw - ctx.cpos) @ ctx.cam["fwd"])
        Rl = 0.5 * float(np.percentile(xs_, 95) - np.percentile(xs_, 5)) * ctx.m_per_px(zc)
        prefabs[lid]["particles"].append(fx_group(ctx, f"Fx_FirePit_{lid}", cw, lava_systems(Rl, M)))
        lava_rep[lid] = {"lavaPx": int(hot.sum()), "radiusM": round(Rl, 2), "centreWorld": [round(x, 2) for x in cw]}
    report["lava"] = lava_rep

    # --- pyre (tbeldw_6): flame column into a fire cloud, over a rock anchor -------------------------------
    a6 = sprite_alpha(ctx, "tbeldw_6")[..., 3] > 127
    ys6, xs6 = np.nonzero(a6)
    ybot = ys6.max()
    base_px = float(np.median(xs6[ys6 > ybot - 12])), float(ybot)
    top_rows = ys6 < ys6.min() + 0.25 * (ys6.max() - ys6.min())
    cloud_px = float(np.median(xs6[top_rows])), float(np.median(ys6[top_rows]))
    cloud_w_px = float(np.percentile(xs6[top_rows], 97) - np.percentile(xs6[top_rows], 3))
    col = int(base_px[0])
    yb = int(base_px[1])
    while yb < H - 1 and ctx.z[yb, col] >= SKY_Z:
        yb += 1
    base_w = ctx.world_at(np.array(float(col)), np.array(float(yb)))
    zc6 = float((base_w - ctx.cpos) @ ctx.cam["fwd"])
    dcl = rays(ctx.cam, np.float64(cloud_px[0]), np.float64(cloud_px[1]))
    top_w = ctx.cpos + dcl * zc6 / float(dcl @ ctx.cam["fwd"])
    height6 = float(top_w[1] - base_w[1])
    r1 = 0.5 * cloud_w_px * ctx.m_per_px(zc6)
    Image.open(IN_DIR / "prop_boulders_albedo.png").save(IN_DIR / "prop_boulders_anchor_albedo.png")
    rv, _ = load_glb_unity(MESHY / "prop_boulders" / B.MESH_ATTEMPT / "model.glb")
    rlo, rhi = rv.min(0), rv.max(0)
    rc = np.array([(rlo[0] + rhi[0]) / 2, rlo[1], (rlo[2] + rhi[2]) / 2])
    rs = (r1 * 0.35) / max(rhi[0] - rlo[0], 1e-6)
    sink = 0.25 * float(rhi[1] - rlo[1]) * rs
    for lid in PYRE_LAYERS:
        p = prefab(lid)
        p["bins"].append(piece_row(ctx, "VentRock" if lid == "tbeldw_6" else "VentRock_2", "prop_boulders",
                                     "prop_boulders_anchor_albedo.png", base_w - np.array([0, sink, 0]) - yaw_matrix(0) @ (rc * rs), 0.0, rs))
        p["particles"].append(fx_group(ctx, f"Fx_Pyre_{lid}", base_w, pyre_systems(height6, r1, M)))
    report["pyre"] = {"baseWorld": base_w.tolist(), "height": height6, "cloudRadius": r1,
                      "systems": [s["name"] for s in pyre_systems(height6, r1, M)]}

    # --- grail (tbelholy): moving aurora curtains in the sky band of its sprite; cairn anchor below --------
    ah = sprite_alpha(ctx, "tbelholy")[..., 3] > 60
    ysh, xsh = np.nonzero(ah)
    x0, x1, y0, y1 = xsh.min(), xsh.max(), ysh.min(), ysh.max()
    dist = 150.0
    curt = []
    for k, (fx0, fx1, dz) in enumerate(((0.0, 0.55, 0.0), (0.3, 0.85, 8.0), (0.5, 1.0, -6.0))):
        xs_ = np.linspace(x0 + fx0 * (x1 - x0), x0 + fx1 * (x1 - x0), 60)
        tops, bots = [], []
        for i, xx in enumerate(xs_):
            wob = 6 * math.sin(i * 0.25 + k)
            for yy_, acc in ((y0, tops), (y1 + 30, bots)):
                d = rays(ctx.cam, np.float64(xx), np.float64(yy_))
                acc.append(ctx.cpos + d * (dist + dz + wob) / float(d @ ctx.cam["fwd"]))
        tops, bots = np.array(tops), np.array(bots)
        nn_ = len(xs_)
        v = np.concatenate([bots, tops])
        uv = np.concatenate([np.stack([np.linspace(0, 1, nn_), np.zeros(nn_)], 1), np.stack([np.linspace(0, 1, nn_), np.ones(nn_)], 1)])
        i = np.arange(nn_ - 1)
        tri = np.concatenate([np.stack([i, i + 1, i + nn_], 1), np.stack([i + 1, i + nn_ + 1, i + nn_], 1)])
        curt.append((v, uv + np.array([0.0, 0.0]), tri))
    V = np.concatenate([c[0] for c in curt])
    offs = np.cumsum([0] + [len(c[0]) for c in curt[:-1]])
    T = np.concatenate([c[2] + o for c, o in zip(curt, offs)])
    UV = np.concatenate([c[1] for c in curt])
    am = material("Homm3ConfluxAurora", [tex("_Noise", vtex("TileNoise_11_vfx")), tex("_Noise2", vtex("TileNoise_24_vfx"))])
    p = prefab("tbelholy")
    p["bins"].append(fxmesh_row("Fx_Aurora", ctx.local(V), np.tile([0, 0, -1.0], (len(V), 1)), UV, T, am))
    cx = int((x0 + x1) / 2)
    ycol = int(y1)
    while ycol < H - 1 and ctx.z[ycol, cx] >= SKY_Z:
        ycol += 1
    cairn_w = ctx.world_at(np.array(float(cx)), np.array(float(ycol + 30)))
    zc_c = float((cairn_w - ctx.cpos) @ ctx.cam["fwd"])
    cs = (10 * ctx.m_per_px(zc_c)) / max(rhi[1] - rlo[1], 1e-6)
    p["bins"].append(piece_row(ctx, "Cairn", "prop_boulders", "prop_boulders_anchor_albedo.png",
                                 cairn_w - np.array([0, 0.3 * (rhi[1] - rlo[1]) * cs, 0]) - yaw_matrix(30) @ (rc * cs), 30.0, cs))
    report["aurora"] = {"distance": dist, "cairnWorld": cairn_w.tolist(), "curtains": len(curt)}

    # --- phase 4: every animated HoMM3 building DEF gets a moving effect (audit in the catalog) ------------------
    report["buildingAnimations"] = building_animations(ctx, prefabs, mesh_geo, spec_l, sky_c)

    missing = [l for l in reach if l not in prefabs]
    if missing:
        raise SystemExit(f"reachable layers without a 3D prefab: {missing}")
    extra = [l for l in prefabs if l not in reach]
    if extra:
        raise SystemExit(f"prefabs for unreachable layers: {extra}")
    for lid, p in prefabs.items():
        if not any(b["name"].startswith("Mesh_") for b in p["bins"]) and not p["scatters"]:
            raise SystemExit(f"{lid}: no Mesh_ piece (the runtime's EnsureLayer needs one)")

    # --- texel density (phase 3 check) ---------------------------------------------------------------------
    report["texelDensity"] = texel_density_report(ctx, prefabs, zfill, nf_frame, wts, dens_after,
                                                  {nm: pr["texelsPerPx"] for nm, pr in piece_rep.items()})

    # --- spec + catalog --------------------------------------------------------------------------------
    OUT.mkdir(parents=True, exist_ok=True)
    all_prefabs = [env] + [prefabs[k] for k in sorted(prefabs)]
    for pf in all_prefabs:
        for b in pf["bins"]:
            b.pop("_world", None)
            b.pop("_faces", None)
            b.pop("_uv", None)
    unity_spec = {"bundleName": BUNDLE, "assetRoot": ASSET_ROOT, "outputPath": str(OUT.resolve()).replace("\\", "/"),
                  "prefabs": all_prefabs}
    (IN_DIR / "build_spec.json").write_text(json.dumps(unity_spec, indent=1), encoding="utf-8")
    bake = ctx.bake
    key_local = (ctx.C.T @ np.asarray(bake["keyLight"]["sunDir"])).tolist()
    fill = bake["fillLight"]

    def names(p):
        return ([x["name"] for x in p["pieces"]] + [x["name"] for x in p["bins"]] + [x["name"] for x in p["scatters"]]
                + [x["name"] for x in p.get("particles", [])])

    def animated(p):
        return [b["name"] for b in p["bins"] if b["kind"] == "fxmesh"] + [g["name"] for g in p.get("particles", [])]
    catalog = {
        "schema": REST_POSE_CATALOG_SCHEMA,
        "fraction": S.FRACTION,
        "bundle": BUNDLE,
        "runtimeLayout": "conflux_4k_outpaint_v1",
        "runtimeLayoutNote": "only the layer-position coordinate basis (positions.json); no plate pixels are drawn or read",
        "proofTier": "source-prepared candidate (stage only; bundle, editor render and runtime unproven)",
        "fullScene3d": True,
        "phase": 3,
        "backdrop": "hidden",
        # Phase 3: vanilla Olden Era terrain detail baked into the Mesh_ albedo (no runtime change).
        "terrainDetail": {"baked": "Mesh_ terrain + Mesh_Skirt_ albedo (Hex/Lit mainTexture)",
                          "sources": [{"layer": k, "texture": v[0], **det.prov[v[0]]}
                                      for k, v in D.DETAIL_SOURCES.items()],
                          "note": "tiling game textures multiplied over the HoMM3 macro colour; no AI upscale, "
                                  "outpaint or Meshy"},
        # Phase 3b: the rivers take the vanilla Olden Era river look (Mtl_River_Water, Hex/Sea) in the bundle's own
        # FlowWater shader: WaterNormal, fixed specular direction, fresnel sky reflection, depth tint, shore feather.
        "phaseRevision": "6b",
        "waterLook": {"shader": "Homm3Conflux/FlowWater", "vanillaMaterial": "Mtl_River_Water (Hex/Sea)",
                      "vanillaMaterialPathId": 4170,
                      "sources": [{"texture": "WaterNormal", "file": "resources.assets", "pathId": 6555,
                                   "sha256": hashlib.sha256((VANILLA_TEX / "WaterNormal.png").read_bytes()).hexdigest()}],
                      "shore": {"outPx": E.SHORE_OUT, "rangePx": E.SHORE_RANGE}},
        "terrainSampler": {"mipBias": TERRAIN_MIP_BIAS, "aniso": TERRAIN_ANISO,
                           "note": "serialized with the Mesh_ albedo textures; the runtime keeps mainTexture"},
        "references": report["references"],
        "referenceCamera": {"fov": ctx.cam["fov"], "aspect": W / H, "source": "cityHuman2 CityCamera/MainCamera",
                            "restPose": PAN.rest_pose_contract()},
        "depthScale": ctx.scale,
        "keyLight": {"cameraLocalDir": key_local, "note": "rotates the scene's directional sun; colour/intensity unchanged"},
        "fillLight": {"cameraLocalDir": (ctx.C.T @ np.asarray(fill["dir"])).tolist(), "linearColor": fill["color"], "shadows": False},
        "fog": "off",
        "environment": {"prefabKey": ENV_KEY, "pieces": names(env), "animated": animated(env),
                        "materials": {"Mesh_": "Hex/Lit (city donor rebind, no collider)", "Sky_": "unlit opaque",
                                      "Fx_": "bundle shader on a SkinnedMeshRenderer / ParticleSystemRenderer (the runtime "
                                             "re-materials MeshRenderers only, so these keep their shader)"}},
        "layers": [{"layerId": p["layerId"], "prefabKey": p["key"], "pieces": names(p), "sprites": [], "animated": animated(p)}
                   for p in (prefabs[k] for k in sorted(prefabs))],
        "layerDepths": [],
        "bundleShaders": ["Homm3Conflux/FlowWater", "Homm3Conflux/VfxUber", "Homm3Conflux/Lava", "Homm3Conflux/Portal",
                          "Homm3Conflux/Aurora"],
        # Phase 4: every catalog layer whose HoMM3 DEF has more than one frame, what moves, and its Fx_ pieces.
        "animationAudit": animation_audit(prefabs, names, animated),
        "animationAuditSource": "layers/anims/metadata.json (frame counts = H3sprite.lod DEF frames)",
        # Phase 5: the near field and the right edge (conflux_full3d_nearfield). The extension outside the HoMM3 rect
        # is synthesised from vanilla terrain textures; the painting only supplies low-frequency colour.
        "nearField": {
            "extensionAlbedo": {
                "sources": list(S5["synth"].prov.values()),
                "paintingRole": f"low-frequency colour only: the painting albedo blurred (Gaussian sigma {N5.L0_SIGMA_PX} "
                                f"px) inside the rect; outside it, per-class colours pulled toward the rect's edge "
                                f"colour (e-folding {N5.SEAM_TONE_M} m)",
                "paintedCrops": False},
            "seamBlend": {"space": "world", "bandM": N5.SEAM_BLEND_M, "noiseM": N5.SEAM_NOISE_M,
                          "minBandPx1080p": N5.SEAM_BLEND_PX, "toneM": N5.SEAM_TONE_M, "minTonePx1080p": N5.SEAM_TONE_PX,
                          "note": "the synthesised albedo ramps in over a world-distance band from the rect edge, "
                                  "broken by value noise; not along the frame rectangle"},
            "texturePieces": [{"name": nm, "texelsPerPx": pr["texelsPerPx"], "frameBox": pr["frameBox"],
                               "tris": pr["tris"]} for nm, pr in report["terrain"]["pieces"].items()],
            "buildingsTexelsPerPx": report["texelDensity"]["buildings"]["median"],
            "relief": {"ampM": N5.RELIEF_AMP, "bumpM": N5.RELIEF_BUMP, "moundM": N5.RELIEF_MOUND,
                       "fadeZ": list(N5.RELIEF_Z), "along": "camera ray (screen registration unchanged)"},
            "dressing": {k: v for k, v in report["nearDressing"].items() if k.startswith("Mesh_")},
            "sitesByDepth": report["nearDressing"].get("sitesByDepth"),
            "hudBottomPx": N5.HUD_BOTTOM_PX,
            "assumptions": ["HUD covers the bottom HUD_BOTTOM_PX of the 1080p frame (layout not measured)",
                            "no fly-path data exists; tall pieces keep off the plots' screen corridor toward the camera",
                            "game cull mode of the Hex/Lit donor unknown; dressing is wound like the terrain"],
            "meshyCredits": 0},
        # Phase 6: outer terrain, rivers and forest over the vanilla town camera's pan (conflux_full3d_periphery); the
        # validator raymarches the pan's rays against panCoverage (void = a ray that reaches neither ground nor sky).
        "periphery": {k: report["periphery"][k] for k in ("panSource", "vanillaReference", "mesh", "pieces", "water",
                                                          "scatter", "albedo", "registration", "meshyCredits")},
        "panCoverage": {"file": report["periphery"]["coverage"]["file"],
                        "sha256": report["periphery"]["coverage"]["sha256"],
                        "panJson": "tools/homm3_town_scene_meshes/vanilla_city_camera_pan.json",
                        "aspects": list(PAN.ASPECTS)},
        # Phase 6b: no shipped terrain triangle spans more than ratioCap in rest forward depth (the ridge curtains are
        # cut; the back layer continues the far surface under the ridge). The validator re-measures terrainStreak.
        "terrainStreak": {"file": report["curtain"]["file"], "sha256": report["curtain"]["sha256"],
                          "ratioCap": CU.RATIO_CAP, "cutTris": report["curtain"]["cutTris"],
                          "backPieces": sorted(report["curtain"]["backPieces"])},
    }
    (OUT / "catalog.json").write_text(json.dumps(catalog, indent=1) + "\n", encoding="utf-8")
    render_spec = {
        "cam": {"pos": ctx.cam["pos"].tolist(), "fwd": ctx.cam["fwd"].tolist(), "up": ctx.cam["up"].tolist(),
                "fov": ctx.cam["fov"], "w": W, "h": H},
        "sunDir": ctx.sun.tolist(), "rig": {k: ctx.rig[k] for k in ("sunColor", "ambSky", "ambEq", "ambGround")},
        "fill": {"dir": fill["dir"], "color": fill["color"]},
        "states": [{"name": n, "prefabs": [ENV_KEY] + [PREFIX + l for l in ls], "timed": n == "full"} for n, ls in STATES.items()]
                  + [{"name": "anim_base", "prefabs": [ENV_KEY] + [PREFIX + l for l in ANIM_BASE_STATE], "timed": True}],
        "sway": {"lateral": 2.5, "frames": 3},
        "timeFrames": TIME_FRAMES,
        # Phase 5: the user plays at 4096x2160; the near field is judged at 3840x2160 (same 16:9 frame).
        "hires": {"w": 3840, "h": 2160, "suffix": "4k", "states": ["full"], "sway": True},
        "outDir": str(RENDERS.resolve()).replace("\\", "/"),
        # Phase 6: sampled native pan extremes, with the runtime v2 root scale at each aspect.
        "panPoses": pan_render_specs(),
    }
    (WORK / "render_spec.json").write_text(json.dumps(render_spec, indent=1), encoding="utf-8")
    (WORK / "stage_report.json").write_text(json.dumps(report, indent=1, default=float), encoding="utf-8")
    print(json.dumps(report, indent=1, default=float))
    return report


# ------------------------------------------------------------------------------------------------ unity
def copy_editor():
    """The dedicated project: built-in modules only, the builder script, lab shaders, the delivery shaders."""
    (PROJECT / "Packages").mkdir(parents=True, exist_ok=True)
    manifest = {"dependencies": {f"com.unity.modules.{m}": "1.0.0" for m in UNITY_MODULES}}
    (PROJECT / "Packages" / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    editor = PROJECT / "Assets" / "Editor"
    editor.mkdir(parents=True, exist_ok=True)
    shutil.copy2(B.UNITY_SRC / "Homm3TownScene3dBundleBuild.cs", editor / "Homm3TownScene3dBundleBuild.cs")
    lab = PROJECT / "Assets" / "Homm3TownLab"
    lab.mkdir(parents=True, exist_ok=True)
    for sh in ("Homm3TownLabHexLit.shader", "Homm3TownLabUnlit.shader"):
        shutil.copy2(B.UNITY_SRC / sh, lab / sh)
    shaders = PROJECT / SHADER_DIR
    shaders.mkdir(parents=True, exist_ok=True)
    for sh in (B.UNITY_SRC / "shaders").glob("*.shader"):
        shutil.copy2(sh, shaders / sh.name)


# --unity-direct (main) is the explicit, loudly logged opt-out of the Unity queue.
UNITY_DIRECT = False


def unity(method: str, extra: list[str], log: Path, graphics: bool, output_dir: Path | None = None) -> int:
    """One Unity batch job through the Unity queue (tools/unity_queue, docs/unity_queue_runner.md)."""
    import importlib.util
    copy_editor()
    spec = importlib.util.spec_from_file_location("unity_queue", ROOT / "tools/unity_queue/unity_queue.py")
    uq = importlib.util.module_from_spec(spec)
    sys.modules["unity_queue"] = uq  # dataclasses resolve their module through sys.modules
    spec.loader.exec_module(uq)
    res = uq.launch(kind="town_conflux_full3d", method=method, args=[str(x) for x in extra], project=PROJECT, log=log,
                    inputs=[x for x in extra if Path(x).is_file()], output_dir=output_dir, graphics=graphics,
                    build_target="StandaloneWindows64", unity=B.UNITY, requester="build_conflux_full3d_scene",
                    direct=UNITY_DIRECT)
    rc = 0 if res["status"] == "ok" else (res.get("exitCode") or 1)
    print("unity", method, "rc", rc, "log", log, "job", res.get("id", "direct"))
    return rc


def bundle() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    rc = unity("Homm3TownScene3dBundleBuild.Run", ["-scene3dSpec", str((IN_DIR / "build_spec.json").resolve())],
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
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    spec["panPoses"] = pan_render_specs()
    spec_path.write_text(json.dumps(spec, indent=1), encoding="utf-8")
    if RENDERS.exists():
        shutil.rmtree(RENDERS)
    RENDERS.mkdir(parents=True)
    rc = unity("Homm3TownScene3dBundleBuild.RenderStates",
               ["-scene3dBundle", str((OUT / BUNDLE).resolve()), "-scene3dRender", str((WORK / "render_spec.json").resolve())],
               WORK / "unity_render.log", graphics=True, output_dir=RENDERS)
    if rc == 0:
        cat_path = OUT / "catalog.json"
        cat = json.loads(cat_path.read_text(encoding="utf-8"))
        cat["proofTier"] = "generated artifact (bundle built and editor-rendered offline; runtime unproven)"
        cat_path.write_text(json.dumps(cat, indent=1) + "\n", encoding="utf-8")
    return rc


# ------------------------------------------------------------------------------------------------ report
def homm3_reference(state: str) -> Image.Image:
    """The HoMM3 town screen for a state: the original background at frame layout with that state's building art
    composited, and the area outside the HoMM3 view (the 3D extension) shaded and labelled."""
    layers = {l["id"]: l for l in json.loads((B.REFS / "layers" / "positions.json").read_text())["layers"]}
    canvas = Image.new("RGBA", (W, H), (48, 48, 52, 255))
    canvas.paste(E.original().resize((TW, TH), Image.LANCZOS), (0, 0))
    for lid in STATES[state]:
        canvas.alpha_composite(Image.fromarray(B.layer_frame(layers[lid])))
    arr = np.asarray(canvas.convert("RGB")).copy()
    ext = np.ones((H, W), bool)
    ext[:TH, :TW] = False
    arr[ext] = (arr[ext] * 0.25 + np.array([48, 48, 52]) * 0.75).astype(np.uint8)
    im = Image.fromarray(arr)
    d = ImageDraw.Draw(im)
    try:
        font = ImageFont.truetype("arial.ttf", 28)
    except OSError:
        font = ImageFont.load_default()
    d.rectangle((0, TH, W, TH + 2), fill=(255, 200, 0))
    d.rectangle((TW, 0, TW + 2, TH), fill=(255, 200, 0))
    d.text((40, TH + 30), "outside the HoMM3 town view (800x374): built as 3D extension", fill=(255, 220, 120), font=font)
    return im


# Phase-3 close-ups (frame px): the terrain next to the fort and the Altar of Air, plus the other faces the detail
# covers (foreground meadow, right cliff, bottom-right meadow extension, mountain faces) and the pyre cloud.
PHASE3_CROPS = {"fort": CLOSEUP_WINDOWS["fort"], "altar_of_air": CLOSEUP_WINDOWS["altar_of_air"],
                "foreground_river": (900, 700, 1500, 1000), "right_cliff": (1500, 300, 1920, 700),
                "meadow_extension": (1400, 750, 1920, 1080), "mountain_faces": (0, 60, 700, 380),
                "pyre": (0, 0, 520, 300)}


def phase3_sheets(lab, font) -> list[str]:
    """Before (phase 2: macro only, CONFLUX_DETAIL_OFF=1 renders kept in renders_phase2) / after (vanilla detail)
    next to the HoMM3 reference; close-ups at 2x; the texel-density maps."""
    before = DATA / "renders_phase2"
    ref = homm3_reference("full")
    b = Image.open(before / "full3d_full.png")
    a = Image.open(RENDERS / "full3d_full.png")
    pw, ph = 960, 540
    sh = Image.new("RGB", (pw * 3, ph))
    for j, (im, t) in enumerate(((ref, "HoMM3 reference"), (b, "before (phase 2, installed look)"),
                                 (a, "after (current editor render)"))):
        sh.paste(lab(im, t, pw, ph), (j * pw, 0))
    sh.save(WORK / "phase3_before_after_sheet.png")
    cw, ch = 720, 420
    cs = Image.new("RGB", (cw * 3, ch * len(PHASE3_CROPS)))
    for i, (k, box) in enumerate(PHASE3_CROPS.items()):
        for j, (im, t) in enumerate(((ref, "HoMM3"), (b, "before"), (a, "after"))):
            cs.paste(lab(im.crop(box), f"{k}: {t}", cw, ch), (j * cw, i * ch))
    cs.save(WORK / "phase3_closeups_sheet.png")
    ds = Image.new("RGB", (pw * 2, ph))
    for j, (n, t) in enumerate((("texel_density_before.png", "terrain texels/px before (white = 2)"),
                                ("texel_density_after.png", "terrain texels/px after (white = 2)"))):
        ds.paste(lab(Image.open(WORK / n), t, pw, ph), (j * pw, 0))
    ds.save(WORK / "phase3_density_sheet.png")
    return [str(WORK / n) for n in ("phase3_before_after_sheet.png", "phase3_closeups_sheet.png",
                                    "phase3_density_sheet.png")]


# Phase-3b close-ups: the review's list (near field, bottom-right meadow + river mouth, bank blend, altar footing,
# pyre shape) plus the fort as the control.
PHASE3B_CROPS = {"foreground": (900, 700, 1500, 1000), "meadow_river_mouth": (1250, 690, 1920, 1080),
                 "water_banks": (300, 560, 900, 860), "altar_of_air": (1040, 30, 1440, 300), "pyre": (0, 0, 520, 300),
                 "fort": CLOSEUP_WINDOWS["fort"]}
PHASE3B_HF_WINDOWS = {"frame": (0, 0, W, H), "fort": (600, 170, 1300, 470), "altar_of_air": (1040, 30, 1440, 300),
                      "foreground": (900, 700, 1500, 1000), "meadow": (1300, 690, 1920, 1080),
                      "right_cliff": (1500, 300, 1920, 700)}


def phase3b_hf() -> dict:
    """Sharpness: mean |L - Gauss1.5(L)| of the render's 8-bit luminance, terrain (live splat minus building
    coverage, eroded) vs buildings (the building meshes' own coverage, eroded), phase 3 vs now."""
    def L(pth):
        return np.asarray(Image.open(pth).convert("L")).astype(np.float32)

    def hf(g):
        return np.abs(g - cv2.GaussianBlur(g, (0, 0), 1.5))
    hb, ha = hf(L(DATA / "renders_phase3" / "full3d_full.png")), hf(L(RENDERS / "full3d_full.png"))
    live = np.asarray(Image.open(WORK / "detail_splat.png").convert("L")) > 8
    cov = np.asarray(Image.open(WORK / "building_coverage.png").convert("L")) > 127
    bld = cv2.erode(cov.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
    terr = cv2.erode((live & ~(cv2.dilate(cov.astype(np.uint8), np.ones((15, 15), np.uint8)) > 0)).astype(np.uint8),
                     np.ones((5, 5), np.uint8)) > 0
    out = {"buildingsWholeFrame": round(float(ha[bld].mean()), 2)}
    for nm, (x0, y0, x1, y1) in PHASE3B_HF_WINDOWS.items():
        t, b_ = terr[y0:y1, x0:x1], bld[y0:y1, x0:x1]
        out[nm] = {"terrainPhase3": round(float(hb[y0:y1, x0:x1][t].mean()), 2),
                   "terrainNow": round(float(ha[y0:y1, x0:x1][t].mean()), 2),
                   "buildings": round(float(ha[y0:y1, x0:x1][b_].mean()), 2) if b_.sum() > 500 else None}
    (WORK / "phase3b_hf_energy.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    return out


def phase3b_sheets(lab) -> list[str]:
    """HoMM3 | phase 3 (renders_phase3, installed look) | phase 3b (current editor render) for start / mid / full,
    and the review's close-ups at the full state."""
    before = DATA / "renders_phase3"
    pw, ph = 960, 540
    sh = Image.new("RGB", (pw * 3, ph * len(STATES)))
    for i, st in enumerate(STATES):
        for j, (im, t) in enumerate(((homm3_reference(st), f"HoMM3: {st}"),
                                     (Image.open(before / f"full3d_{st}.png"), f"phase 3 (installed): {st}"),
                                     (Image.open(RENDERS / f"full3d_{st}.png"), f"phase 3b (editor render): {st}"))):
            sh.paste(lab(im, t, pw, ph), (j * pw, i * ph))
    sh.save(WORK / "phase3b_states_sheet.png")
    ref = homm3_reference("full")
    b = Image.open(before / "full3d_full.png")
    a = Image.open(RENDERS / "full3d_full.png")
    cw, ch = 720, 420
    cs = Image.new("RGB", (cw * 3, ch * len(PHASE3B_CROPS)))
    for i, (k, box) in enumerate(PHASE3B_CROPS.items()):
        for j, (im, t) in enumerate(((ref, "HoMM3"), (b, "phase 3"), (a, "phase 3b"))):
            cs.paste(lab(im.crop(box), f"{k}: {t}", cw, ch), (j * cw, i * ch))
    cs.save(WORK / "phase3b_closeups_sheet.png")
    return [str(WORK / n) for n in ("phase3b_states_sheet.png", "phase3b_closeups_sheet.png")]


def phase4_motion(font) -> tuple[list[str], dict]:
    """Phase 4 motion proof, one row per animated building: HoMM3 DEF frame 0 and a middle frame, our render at
    t = 0 and t = 1 s, and |t1 - t0| x4. motionPx counts crop pixels whose luminance changed by more than 10."""
    cat = json.loads((OUT / "catalog.json").read_text(encoding="utf-8"))
    audit = cat.get("animationAudit") or {}
    ctx_layers = {l["id"]: l for l in json.loads((B.REFS / "layers" / "positions.json").read_text())["layers"]}
    meta = {m["id"]: m for m in json.loads((ANIMS / "metadata.json").read_text(encoding="utf-8"))}
    ch = 300
    rows, stats = [], {}
    for lid, row in sorted(audit.items()):
        st = "anim_base" if lid in ANIM_BASE_STATE else "full"
        t0p, t1p = RENDERS / f"full3d_{st}_t0.png", RENDERS / f"full3d_{st}_t1.png"
        if not (t0p.is_file() and t1p.is_file()):
            raise SystemExit(f"phase 4 motion: missing {t0p.name} / {t1p.name} (run render)")
        L = ctx_layers[lid]
        al = B.layer_frame(L)[..., 3] > 0
        ys, xs = np.nonzero(al)
        up = {"tbelblak": 160, "tbeldw_6": 0, "tbeldw_6_2": 0}.get(lid, 30)
        box = (max(0, xs.min() - 30), max(0, ys.min() - up), min(W, xs.max() + 30), min(H, ys.max() + 30))
        a = Image.open(t0p).convert("RGB").crop(box)
        bb = Image.open(t1p).convert("RGB").crop(box)
        la = np.asarray(a.convert("L"), np.float32)
        lb = np.asarray(bb.convert("L"), np.float32)
        d = np.abs(la - lb)
        moving = int((d > 10).sum())
        dimg = Image.fromarray(np.clip(d * 4, 0, 255).astype(np.uint8))
        fr = meta[lid]["frames"]
        f0 = Image.open(ANIMS / lid / fr[0]).convert("RGBA")
        fk = f0.copy()
        fk.alpha_composite(Image.open(ANIMS / lid / fr[len(fr) // 2]).convert("RGBA"))
        s = ch / (box[3] - box[1])
        cw = max(120, int((box[2] - box[0]) * s))

        def cell(im, txt):
            im = im.convert("RGBA")
            bg = Image.new("RGBA", im.size, (24, 24, 24, 255))
            bg.alpha_composite(im)
            k = min(cw / im.size[0], ch / im.size[1])
            im = bg.convert("RGB").resize((max(1, int(im.size[0] * k)), max(1, int(im.size[1] * k))), Image.NEAREST
                                           if im.size[0] < 200 else Image.LANCZOS)
            c = Image.new("RGB", (cw, ch + 30), (0, 0, 0))
            c.paste(im, ((cw - im.size[0]) // 2, 30 + (ch - im.size[1]) // 2))
            ImageDraw.Draw(c).text((6, 3), txt, fill=(255, 255, 255), font=font)
            return c
        cells = [cell(f0, "HoMM3 f0"), cell(fk, f"HoMM3 f{len(fr) // 2}"), cell(a, "ours t=0"), cell(bb, "ours t=1 s"),
                 cell(dimg, "|t1-t0| x4")]
        r = Image.new("RGB", (sum(c.size[0] for c in cells), ch + 70), (0, 0, 0))
        x = 0
        for c in cells:
            r.paste(c, (x, 40))
            x += c.size[0]
        ImageDraw.Draw(r).text((6, 4), f"{lid} ({st}): {row['moves'][:70]} -> {', '.join(row['effects'])}; "
                                        f"moving px {moving}", fill=(255, 230, 0), font=font)
        rows.append(r)
        stats[lid] = {"state": st, "cropBox": [int(v) for v in box], "motionPx": moving,
                      "motionFrac": round(moving / d.size, 4)}
    paths = []
    for i in range(0, len(rows), 6):
        g = rows[i:i + 6]
        sh = Image.new("RGB", (max(r.size[0] for r in g), sum(r.size[1] for r in g)), (0, 0, 0))
        y = 0
        for r in g:
            sh.paste(r, (0, y))
            y += r.size[1]
        p = WORK / f"phase4_motion_sheet_{i // 6}.png"
        sh.save(p)
        paths.append(str(p))
    still = sorted(k for k, v in stats.items() if v["motionPx"] < 50)
    return paths, {"layers": stats, "withoutMotion": still}


# Phase 5: before = phase 4 (renders_phase4 at 1080p, renders_phase4_4k at 3840x2160: bundle ac8f215a, same camera);
# after = the current renders. Crops in 1080p frame coordinates (x2 on the 4K renders).
PHASE5_CROPS = {"bottom_band": (240, 740, 1100, 1080), "right_edge": (1480, 260, 1920, 760),
                "seam_corner": (1240, 520, 1680, 840)}
PHASE5_BANDS = {"far (z >= 45 m)": (45.0, 1e9), "mid (22-45 m)": (22.0, 45.0), "near (12-22 m)": (12.0, 22.0),
                "nearest (< 12 m)": (0.0, 12.0)}
PHASE5_SEAM_STRIP = 10   # px each side of the seam (1080p)
PHASE5_SEAM_SEG = 24     # px segments along it (1080p)


def _lum_png(pth: Path) -> np.ndarray:
    return np.asarray(Image.open(pth).convert("L")).astype(np.float32)


def _hf(g: np.ndarray) -> np.ndarray:
    return np.abs(g - cv2.GaussianBlur(g, (0, 0), 1.5))


def phase5_masks(k: int) -> dict:
    """Frame masks at k x 1080p: terrain and its near-field dressing (not sky, not water, not a building), buildings,
    per-pixel ground depth (metres, relieved)."""
    z = np.load(WORK / "phase5_zmap.npy")
    water = np.asarray(Image.open(WORK / "phase5_water.png").convert("L")) > 127
    cov = (np.asarray(Image.open(WORK / "building_coverage.png").convert("L")) > 127).astype(np.uint8)
    bld = cv2.erode(cov, np.ones((5, 5), np.uint8)) > 0
    terr = np.isfinite(z) & ~water & ~(cv2.dilate(cov, np.ones((15, 15), np.uint8)) > 0)
    terr = cv2.erode(terr.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
    up = (lambda a: np.repeat(np.repeat(a, k, 0), k, 1)) if k > 1 else (lambda a: a)
    return {"terr": up(terr), "bld": up(bld), "z": up(np.where(np.isfinite(z), z, 1e9))}


def phase5_hf(after: Path, before: Path, k: int) -> dict:
    """|L - Gauss1.5(L)| (8-bit luminance, sigma in the render's own pixels) per ground-depth band of the terrain
    and its dressing, the right edge, the phase-3b windows; against the buildings. before = phase 4."""
    m = phase5_masks(k)
    ha, hb = _hf(_lum_png(after)), _hf(_lum_png(before))

    def ent(sel):
        return {"before": round(float(hb[sel].mean()), 2), "after": round(float(ha[sel].mean()), 2), "px": int(sel.sum())}
    out = {"buildings": ent(m["bld"])}
    for nm, (z0, z1) in PHASE5_BANDS.items():
        out[nm] = ent(m["terr"] & (m["z"] >= z0) & (m["z"] < z1))
    re = m["terr"].copy()
    re[:, :1600 * k] = False
    out["right edge (x >= 1600)"] = ent(re)
    for nm, (x0, y0, x1, y1) in {**PHASE3B_HF_WINDOWS, **CLOSEUP_WINDOWS}.items():
        sel = np.zeros_like(m["terr"])
        sel[y0 * k:y1 * k, x0 * k:x1 * k] = True
        if (sel & m["terr"]).sum() > 500:
            out["window " + nm] = ent(sel & m["terr"])
    return out


def phase5_seam(pth: Path, k: int) -> dict:
    """Seam visibility along the HoMM3 rect's right edge (x = TW) and bottom edge (y = TH): per segment, the step in
    mean luminance across the line over the mean standard deviation of the strips either side, and the ratio of
    their high-frequency energy (outside / inside). Control: the same on lines 100 px inside the rect, where there is
    no seam. Medians over segments with >= 60 % terrain on both sides."""
    g = _lum_png(pth)
    hf = _hf(g)
    terr = phase5_masks(k)["terr"]
    s, seg = PHASE5_SEAM_STRIP * k, PHASE5_SEAM_SEG * k

    def line(vertical: bool, pos: int, hi: int):
        vis, hr = [], []
        for a in range(0, hi - seg + 1, seg):
            if vertical:
                A, B_ = (slice(a, a + seg), slice(pos - s, pos)), (slice(a, a + seg), slice(pos, pos + s))
            else:
                A, B_ = (slice(pos - s, pos), slice(a, a + seg)), (slice(pos, pos + s), slice(a, a + seg))
            ma, mb = terr[A], terr[B_]
            if ma.mean() < 0.6 or mb.mean() < 0.6:
                continue
            ga, gb = g[A][ma], g[B_][mb]
            vis.append(abs(ga.mean() - gb.mean()) / (0.5 * (ga.std() + gb.std()) + 1e-6))
            hr.append(hf[B_][mb].mean() / (hf[A][ma].mean() + 1e-6))
        return {"segments": len(vis), "stepOverStd": round(float(np.median(vis)), 3) if vis else None,
                "hfOutsideOverInside": round(float(np.median(hr)), 3) if hr else None}
    return {f"right seam x={TW}": line(True, TW * k, TH * k), f"bottom seam y={TH}": line(False, TH * k, TW * k),
            f"control x={TW - 100}": line(True, (TW - 100) * k, TH * k),
            f"control y={TH - 100}": line(False, (TH - 100) * k, TW * k)}


def phase5_sheets(lab) -> list:
    """Before (phase 4) | after (phase 5): crops of the bottom band, the right edge and the seam corner at 3840x2160
    (labelled sheet + 1:1 pairs), the whole frame at 1080p, and the parallax sway of the near field at 4K."""
    out = []
    b4k, a4k = DATA / "renders_phase4_4k" / "full3d_full_4k.png", RENDERS / "full3d_full_4k.png"
    if b4k.is_file():
        bi, ai = Image.open(b4k).convert("RGB"), Image.open(a4k).convert("RGB")
        cw, ch = 1100, 760
        sh = Image.new("RGB", (cw * 2, ch * len(PHASE5_CROPS)))
        for i, (nm, (x0, y0, x1, y1)) in enumerate(PHASE5_CROPS.items()):
            box = (x0 * 2, y0 * 2, x1 * 2, y1 * 2)
            for j, (im, t) in enumerate(((bi, "phase 4 (installed)"), (ai, "phase 5"))):
                sh.paste(lab(im.crop(box), f"{nm} @3840x2160: {t}", cw, ch), (j * cw, i * ch))
            w_, h_ = box[2] - box[0], box[3] - box[1]
            pair = Image.new("RGB", (w_ * 2 + 8, h_))
            pair.paste(bi.crop(box), (0, 0))
            pair.paste(ai.crop(box), (w_ + 8, 0))
            pair.save(WORK / f"phase5_{nm}_4k_1to1.png")
            out.append(str(WORK / f"phase5_{nm}_4k_1to1.png"))
        sh.save(WORK / "phase5_before_after_4k.png")
        out.insert(0, str(WORK / "phase5_before_after_4k.png"))
    b1 = DATA / "renders_phase4" / "full3d_full.png"
    if b1.is_file():
        sh = Image.new("RGB", (1920, 540))
        sh.paste(lab(Image.open(b1), "phase 4 (installed)", 960, 540), (0, 0))
        sh.paste(lab(Image.open(RENDERS / "full3d_full.png"), "phase 5 (editor render)", 960, 540), (960, 0))
        sh.save(WORK / "phase5_full_frame.png")
        out.append(str(WORK / "phase5_full_frame.png"))
    sway = [RENDERS / f"full3d_full_sway_{i}_4k.png" for i in range(3)]
    if all(p.is_file() for p in sway):
        y0, y1 = 1300, 2032
        rows = [Image.open(p).convert("RGB").crop((0, y0, 3840, y1)) for p in sway]
        rw, rh = 1920, (y1 - y0) // 2
        sh = Image.new("RGB", (rw, rh * 3))
        for i, r in enumerate(rows):
            sh.paste(lab(r, f"near field @3840x2160, camera sway frame {i} (lateral -2.5 / 0 / +2.5 m)", rw, rh), (0, i * rh))
        sh.save(WORK / "phase5_parallax_near.png")
        out.append(str(WORK / "phase5_parallax_near.png"))
    return out


def report() -> dict:
    try:
        font = ImageFont.truetype("arial.ttf", 26)
    except OSError:
        font = ImageFont.load_default()

    def lab(im, t, w, h):
        im = im.convert("RGB").resize((w, h), Image.LANCZOS)
        d = ImageDraw.Draw(im)
        d.rectangle((0, 0, w, 36), fill=(0, 0, 0))
        d.text((10, 4), t, fill=(255, 255, 255), font=font)
        return im
    pw, ph = 960, 540
    rows = []
    for st in STATES:
        ref = homm3_reference(st)
        ref.save(WORK / f"homm3_reference_{st}.png")
        p1 = PHASE1 / "renders" / f"full3d_{st}.png"
        p2 = RENDERS / f"full3d_{st}.png"
        cells = [lab(ref, f"HoMM3 reference: {st}", pw, ph),
                 lab(Image.open(p1) if p1.is_file() else Image.new("RGB", (W, H)), f"before (phase 1, installed): {st}", pw, ph),
                 lab(Image.open(p2), f"after (current editor render): {st}", pw, ph)]
        row = Image.new("RGB", (pw * 3, ph))
        for i, c in enumerate(cells):
            row.paste(c, (i * pw, 0))
        rows.append(row)
    sheet = Image.new("RGB", (pw * 3, ph * len(rows)))
    for i, r in enumerate(rows):
        sheet.paste(r, (0, i * ph))
    sheet.save(WORK / "phase2_before_after_sheet.png")
    # Close-ups the review named: fort, right cliff, fire pit, pyre, air shrine, rivers.
    crops = {"fort": (560, 150, 1320, 520), "right_cliff": (1300, 0, 1920, 560), "fire_pit": (140, 180, 420, 420),
             "pyre_aurora": (0, 0, 760, 330), "air_shrine_rivers": (0, 380, 960, 1080)}
    ref = homm3_reference("full")
    p1 = Image.open(PHASE1 / "renders" / "full3d_full.png") if (PHASE1 / "renders" / "full3d_full.png").is_file() else Image.new("RGB", (W, H))
    p2 = Image.open(RENDERS / "full3d_full.png")
    cw, ch = 640, 400
    cs = Image.new("RGB", (cw * 3, ch * len(crops)))
    for i, (k, box) in enumerate(crops.items()):
        for j, (im, t) in enumerate(((ref, "HoMM3"), (p1, "before"), (p2, "after"))):
            cs.paste(lab(im.crop(box), f"{k}: {t}", cw, ch), (j * cw, i * ch))
    cs.save(WORK / "phase2_closeups_sheet.png")
    # Motion proof: two effect times side by side (river flow, lava, portal, aurora, particles).
    tf = sorted(RENDERS.glob("full3d_full_t*.png"))
    if len(tf) >= 2:
        ms = Image.new("RGB", (pw * 2, ph * 2))
        for j, pth in enumerate(tf[:2]):
            ms.paste(lab(Image.open(pth), f"effects at t = {TIME_FRAMES[j]} s", pw, ph), (j * pw, 0))
        flow = Image.open(WORK / "flow_v.png")
        ms.paste(lab(flow, "flow coordinate (bands advance downstream, toward the camera)", pw, ph), (0, ph))
        a = np.asarray(Image.open(tf[0]).convert("L"), np.float32)
        b = np.asarray(Image.open(tf[1]).convert("L"), np.float32)
        diff = np.clip(np.abs(a - b) * 4, 0, 255).astype(np.uint8)
        ms.paste(lab(Image.fromarray(diff), "|t1 - t0| x4 (what moves)", pw, ph), (pw, ph))
        ms.save(WORK / "phase2_motion_sheet.png")
    sway = sorted(RENDERS.glob("full3d_full_sway_*.png"))
    if sway:
        sh = Image.new("RGB", (W * len(sway) // 2, H // 2))
        for i, p in enumerate(sway):
            sh.paste(Image.open(p).convert("RGB").resize((W // 2, H // 2)), (i * W // 2, 0))
        sh.save(WORK / "full3d_parallax_sheet.png")
    sheets3 = phase3_sheets(lab, font) if (DATA / "renders_phase2" / "full3d_full.png").is_file() else []
    hf3b = None
    if (DATA / "renders_phase3" / "full3d_full.png").is_file():
        sheets3 += phase3b_sheets(lab)
        hf3b = phase3b_hf()
    cat = json.loads((OUT / "catalog.json").read_text(encoding="utf-8"))
    out = {"bundle": str(OUT / BUNDLE), "catalog": str(OUT / "catalog.json"),
           "catalogSha256": hashlib.sha256((OUT / "catalog.json").read_bytes()).hexdigest(),
           "bundleSha256": cat.get("bundleSha256"), "bundleBytes": cat.get("bundleBytes"),
           "sheets": [str(WORK / n) for n in ("phase2_before_after_sheet.png", "phase2_closeups_sheet.png",
                                             "phase2_motion_sheet.png", "full3d_parallax_sheet.png")] + sheets3,
           "phase3bHfEnergy": hf3b}
    if (WORK / "phase5_zmap.npy").is_file() and (RENDERS / "full3d_full_4k.png").is_file():
        out["sheets"] += phase5_sheets(lab)
        b1, b4 = DATA / "renders_phase4" / "full3d_full.png", DATA / "renders_phase4_4k" / "full3d_full_4k.png"
        a1, a4 = RENDERS / "full3d_full.png", RENDERS / "full3d_full_4k.png"
        p5 = {"hf1080p": phase5_hf(a1, b1, 1), "hf4k": phase5_hf(a4, b4, 2),
              "seam": {"before1080p": phase5_seam(b1, 1), "after1080p": phase5_seam(a1, 1),
                       "before4k": phase5_seam(b4, 2), "after4k": phase5_seam(a4, 2)}}
        (WORK / "phase5_metrics.json").write_text(json.dumps(p5, indent=1), encoding="utf-8")
        out["phase5"] = p5
    if cat.get("animationAudit"):
        p4, m4 = phase4_motion(font)
        out["sheets"] += p4
        out["phase4Motion"] = m4
        (WORK / "phase4_motion.json").write_text(json.dumps(m4, indent=1), encoding="utf-8")
    print(json.dumps(out, indent=1))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("step", choices=["stage", "bundle", "render", "report"])
    ap.add_argument("--unity-direct", action="store_true",
                    help="bundle/render: launch Unity directly instead of submitting to the Unity queue (explicit, "
                         "logged opt-out; docs/unity_queue_runner.md)")
    a = ap.parse_args()
    global UNITY_DIRECT
    UNITY_DIRECT = a.unity_direct
    if a.step == "stage":
        stage()
    elif a.step == "bundle":
        return bundle()
    elif a.step == "render":
        return render()
    else:
        report()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
