#!/usr/bin/env python3
"""Conflux 3D town prototype: stage a Unity preview of Meshy buildings in the native city camera.

    python tools/homm3_town_scene_meshes/build_conflux_town3d_preview.py stage    # plate, depth, fits, layers
    python tools/homm3_town_scene_meshes/build_conflux_town3d_preview.py unity    # memgate + unitylock + batch render
    python tools/homm3_town_scene_meshes/build_conflux_town3d_preview.py compose  # alignment report, sheets, mp4

Construction contract (v2; replaces the pilot's rule-based seating and camera-parallel cards, which is
why buildings and props slid out of alignment in the first camera-move video):
  * Camera: the native city camera exported from the installed cityHuman2 scene
    (export_stock_city_scene.py -> scene.json; FOV 47.6, pose unchanged).
  * Frame: the RUNTIME layout the plugin draws (positions.json coordinateBasis conflux_4k_outpaint_v1):
    the HoMM3 800x374 screen at x3.6 on a 3840x2160 canvas, top-left anchored (x 0-2880, y 0-1346), the
    rest outpainted. The preview frame is that canvas at 1920x1080 (x1.8 per HoMM3 px). The plate is the
    shipped homm3_conflux_background_upscaled_3840x2160.png; its bottom rows from SMEAR_START_FRAC are a
    smeared/mirrored strip, so their depth is edge-extended from the last good row. (Relay 1-3 renders up
    to commit 3fb46aa0ed used an 800 px -> 1920 px framing that the game does not use.)
  * One town STATE (one level per slot) drives both the HoMM3 reference composite and the 3D scene,
    so a mesh is never compared against another level's sprite.
  * Backdrop: the HoMM3 background (no buildings) projected from the camera onto its Depth Anything V2
    depth surface (relative disparity -> camera z in [Z_NEAR, Z_FAR]).
  * Buildings: each Meshy mesh is REGISTERED to its sprite (fit_mesh_to_sprite.Fitter): yaw, uniform
    scale and ground-contact pixel are searched so the projected silhouette matches the sprite alpha
    (precision-weighted F-beta), with the mesh base resting on the backdrop surface at the contact.
  * Only pixels VISIBLE in the HoMM3 composite are ever projected (their depth is that of the visible
    surface); pixels of a layer that a later-drawn layer hides are dropped.
  * Sprite pixels the mesh does not represent - painted ground skirts at the base and see-through
    holes such as the portal ring's surface - stay as projected 2D pixels ("skirts").
  * Terrain-embedded / sky layers (lava pit, earth ring, air shrine, firestorm, ext2 garden) are
    projected 2D pixels on a depth-displaced grid, not flat cards: their depth is Depth Anything V2 on
    the full composite, least-squares aligned to the backdrop's disparity on background-only pixels,
    so they stay glued to the terrain under camera motion.
Proof tier: generated artifact / Unity-editor render. Nothing here touches the game.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import shutil
import struct
import subprocess
import sys
from pathlib import Path

# Unity jobs go through the Unity queue (docs/unity_queue_runner.md): agents submit, not launch. --unity-direct is the
# explicit, loudly logged opt-out.
import importlib.util as _uq_ilu  # noqa: E402
_uq_spec = _uq_ilu.spec_from_file_location("unity_queue", Path(__file__).resolve().parents[1] / "unity_queue" / "unity_queue.py")
UQ = _uq_ilu.module_from_spec(_uq_spec)
sys.modules["unity_queue"] = UQ  # dataclasses resolve their module through sys.modules
_uq_spec.loader.exec_module(UQ)
UNITY_DIRECT = UQ.take_direct_flag()

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fit_mesh_to_sprite import Fitter, knee_remap, load_glb_unity, yaw_matrix  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
REFS = (ROOT / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod" / "homm3_runtime_assets"
        / "town_scene_refs" / "homm3_conflux")
WORK = ROOT / "artifacts" / "homm3_conflux_town3d"
STOCK = WORK / "stock_cityHuman2_export"
MESHY = ROOT / "artifacts" / "meshy_town_scene_meshes" / "homm3_conflux"
PROJECT = ROOT / "oldenera_factions"
LAB = PROJECT / "Assets" / "Homm3TownLab"
UNITY = Path(r"C:\Program Files\Unity\Hub\Editor\6000.0.66f2\Editor\Unity.exe")
UNITY_SRC = Path(__file__).resolve().parent / "unity"

W, H = 1920, 1080
RUNTIME_CANVAS_W, RUNTIME_UNIFORM_SCALE = 3840, 3.6  # positions.json coordinateBasis (conflux_4k_outpaint_v1)
SCALE = RUNTIME_UNIFORM_SCALE * W / RUNTIME_CANVAS_W  # HoMM3 town-screen px -> frame px (1.8)
TOWN_H = round(374 * SCALE)
TOWN_W = round(800 * SCALE)
SMEAR_START_FRAC = 0.921  # plate rows below this are vertical streaks (measured: gradient ratio drop)
RUNTIME_PLATE = "homm3_conflux_background_upscaled_3840x2160.png"
Z_NEAR, Z_FAR = 10.0, 160.0
MESH_ATTEMPT = "mesh_a1"
# The shown town state: one level per slot. "mesh" = registered Meshy mesh (optional column span of the
# sprite for a multi-object layer); no mesh = projected 2D layer (terrain-embedded or sky features that
# are planned for painted-image projection, never Meshy spend). Dwellings use their base level, the
# level the meshes were generated from. Grail and hidden hordes are excluded.
STATE = [
    {"layer": "tbelhall_4", "mesh": "tbelhall_4"},
    # Regen (relay 3; a1 was "tbelcstl_3"). fitBox = the keep crop the concept was made from: the sprite's
    # painted terrain below and left of the keep made the fit inflate the mesh over it.
    {"layer": "tbelcstl_3", "mesh": "tbelcstl_3_keep", "fitBox": (190, 0, 322, 120)},
    {"layer": "tbelmage_4", "mesh": "tbelmage_4"},
    {"layer": "tbeltvrn", "mesh": "tbeltvrn"},
    {"layer": "tbelblak", "mesh": "tbelblak"},
    {"layer": "tbelmark", "mesh": "tbelmark_a", "span": (0, 92)},
    {"layer": "tbelmark", "mesh": "tbelmark_b", "span": (108, 201)},
    {"layer": "tbelsilo", "mesh": "tbelsilo"},
    {"layer": "tbelspec", "mesh": "tbelspec"},
    {"layer": "tbeldock", "mesh": "tbeldock"},
    {"layer": "tbeldw_0", "mesh": "tbeldw_0"},
    {"layer": "tbeldw_2", "mesh": "tbeldw_2"},
    {"layer": "tbeldw_5", "mesh": "tbeldw_5_frame"},
    {"layer": "tbelext2"},
    {"layer": "tbeldw_1"},
    {"layer": "tbeldw_3"},
    {"layer": "tbeldw_4"},
    {"layer": "tbeldw_6"},
]
# Lower-tier town states (coordinator relay 2026-09-26, user-approved: a young town must look like the preview).
# Each is a whole town state composed, depth-estimated and rendered on its own, so a lower-level mesh is
# registered and skirted against the town it is shown in, never against the full town's composite. Entries use
# the STATE schema plus:
#   name      instance id (default: mesh), unique across all states; one instance per HoMM3 layer
#   fitLayer  register against this layer's sprite instead (the upgrade sprite repeats the base building and
#             adds painted ground, e.g. tbeldw_0_2's garden); the transform is then the base instance's
#   bakeAs    reuse this instance's baked texture (same mesh, same painted building pixels)
#   skirtFrac skirt band as a fraction of the fit box height (default SKIRT_BASE_FRAC)
# An entry whose instance already exists in an earlier state is shown, not re-emitted. Upgrade dwellings whose
# HoMM3 sprite is the base sprite (tbeldw_1..5 _2: mean |diff| 3-14 of 255, animation frame only) are the base
# mesh again with their own skirt. Sky/effect layers (tbeldw_6*, tbelholy) stay projected 2D.
VARIANT_STATES: dict[str, list[dict]] = {
    "level1": [
        {"layer": "tbelhall", "mesh": "tbelhall"},
        # fitBox = the fort without its painted terrain (as tbelcstl_3's keep box)
        {"layer": "tbelcstl", "mesh": "tbelcstl", "fitBox": (190, 40, 322, 120)},
        {"layer": "tbelmage", "mesh": "tbelmage"},
    ],
    "level2": [
        {"layer": "tbelhall_2", "mesh": "tbelhall_2"},
        # Regen from the keep crop (36 cr, conflux_lower_tier_2026-09-26). a1 stood on a full-footprint slab; the
        # interim cut of it (cut_ground_plate.py -> tbelcstl_2_noplate) read as a plain wall block.
        {"layer": "tbelcstl_2", "mesh": "tbelcstl_2_keep", "name": "tbelcstl_2", "fitBox": (190, 0, 322, 120)},
        {"layer": "tbelmage_2", "mesh": "tbelmage_2"},
        {"layer": "tbeldw_0_2", "mesh": "tbeldw_0", "name": "tbeldw_0_2", "fitLayer": "tbeldw_0",
         "bakeAs": "tbeldw_0", "skirtFrac": 1.0},
        {"layer": "tbeldw_2_2", "mesh": "tbeldw_2", "name": "tbeldw_2_2", "fitLayer": "tbeldw_2", "bakeAs": "tbeldw_2"},
        {"layer": "tbeldw_5_2", "mesh": "tbeldw_5_frame", "name": "tbeldw_5_2", "fitLayer": "tbeldw_5",
         "bakeAs": "tbeldw_5_frame"},
    ],
    "level3": [
        {"layer": "tbelmage_3", "mesh": "tbelmage_3"},
        {"layer": "tbelhrd2", "mesh": "tbeldw_0", "name": "tbelhrd2", "fitLayer": "tbeldw_0",
         "bakeAs": "tbeldw_0", "skirtFrac": 1.0, "slot": "tbeldw_0"},
    ],
}
# Slots a variant state does not list keep the full STATE's entry (same instance, shown again).
SKIRT_BASE_FRAC = 0.35   # skirt pixels: bottom 35% of the sprite box, or holes enclosed by the mesh
SKIRT_DILATE_PX = 6
GRID_STEP = 4
GRID_BREAK_RATIO = 1.3   # drop grid triangles spanning a depth discontinuity (max/min z)


def camera() -> dict:
    scene = json.loads((STOCK / "scene.json").read_text(encoding="utf-8"))
    m = np.array(scene["camera"]["m"]).reshape(4, 4).T
    right, up, fwd = (m[:3, i] / np.linalg.norm(m[:3, i]) for i in range(3))
    return {"pos": m[:3, 3], "right": right, "up": up, "fwd": fwd, "fov": float(scene["camera"]["fov"]),
            "scene": scene}


def ray(cam: dict, px: float, py: float) -> np.ndarray:
    t = math.tan(math.radians(cam["fov"]) / 2)
    nx = (px / W) * 2 - 1
    ny = 1 - (py / H) * 2
    return cam["fwd"] + cam["right"] * nx * t * (W / H) + cam["up"] * ny * t


def srgb_to_linear(c) -> np.ndarray:
    c = np.asarray(c, np.float64)
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def city_rig(scene: dict) -> dict:
    """The cityHuman2 light rig as the game evaluates it: linear colour space and
    lightsUseLinearIntensity=true (globalgamemanagers, static-asset), so sun = colour.linear * intensity;
    ambient = the RenderSettings trilight colours, linearised."""
    sun = next(l for l in scene["lights"] if l["type"] == 1)
    amb = scene["ambient"]
    return {"name": "city_linear",
            "sunColor": (srgb_to_linear(sun["color"][:3]) * sun["intensity"]).tolist(),
            "ambSky": srgb_to_linear(amb["sky"][:3]).tolist(),
            "ambEq": srgb_to_linear(amb["equator"][:3]).tolist(),
            "ambGround": srgb_to_linear(amb["ground"][:3]).tolist()}


# The pilot's preview light (arena MainLight 1.0 + flat arena ambient): kept only as a comparison render.
ARENA_RIG = {"name": "arena_legacy", "sunColor": [1, 0.905, 0.672], "ambSky": [0.347, 0.418, 0.591],
             "ambEq": [0.347, 0.418, 0.591], "ambGround": [0.347, 0.418, 0.591]}


def plate() -> Image.Image:
    """The shipped runtime backdrop at frame resolution (what the plugin shows behind the town)."""
    return Image.open(REFS / "mockups" / RUNTIME_PLATE).convert("RGB").resize((W, H), Image.LANCZOS)


def extend_smear(z: np.ndarray) -> np.ndarray:
    """Depth of the smeared bottom strip: edge-extend the last good row (the streaks carry no geometry)."""
    z = z.copy()
    r = int(SMEAR_START_FRAC * H)
    z[r:] = z[r - 1]
    return z


def depth(img: Image.Image) -> np.ndarray:
    import torch
    from transformers import AutoImageProcessor, AutoModelForDepthEstimation

    name = "depth-anything/Depth-Anything-V2-Base-hf"
    proc = AutoImageProcessor.from_pretrained(name)
    model = AutoModelForDepthEstimation.from_pretrained(name).to("cuda").eval()
    with torch.no_grad():
        out = model(**{k: v.to("cuda") for k, v in proc(images=img, return_tensors="pt").items()})
        pred = torch.nn.functional.interpolate(out.predicted_depth.unsqueeze(1), size=(H, W), mode="bicubic",
                                               align_corners=False)[0, 0].cpu().numpy()
    return pred


def disparity_to_z(d: np.ndarray, lo: float, hi: float) -> np.ndarray:
    """DA V2 relative output is disparity-like (larger = nearer). Map the plate's percentile range to 1/z."""
    r = np.clip((d - lo) / (hi - lo), 0, 1)
    inv = r * (1 / Z_NEAR - 1 / Z_FAR) + 1 / Z_FAR
    return 1.0 / inv


def layer_frame(L: dict, span: tuple[int, int] | None = None) -> np.ndarray:
    """The layer's sprite placed in the 1920x1080 frame (RGBA uint8), optionally one column span."""
    s = Image.open(REFS / "layers" / L["sprite"]).convert("RGBA")
    x_off = 0
    if span:
        s = s.crop((span[0], 0, span[1], s.height))
        x_off = span[0]
    s = s.resize((round(s.width * SCALE), round(s.height * SCALE)), Image.LANCZOS)
    canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    dx, dy = round((L["x"] + x_off) * SCALE), round(L["y"] * SCALE)
    if dx < 0:
        s = s.crop((-dx, 0, s.width, s.height))
        dx = 0
    canvas.alpha_composite(s, (dx, dy))
    return np.asarray(canvas)


def fit_target(layers: dict, s: dict, rgba: np.ndarray) -> np.ndarray:
    """The sprite pixels a mesh must match: alpha, limited to the entry's optional sprite-px fitBox."""
    target = (rgba[..., 3] > 127).astype(np.uint8)
    if s.get("fitBox"):  # sprite-px box the mesh depicts; the rest (painted terrain) stays a skirt
        L = layers[s["layer"]]
        bx0, by0, bx1, by1 = s["fitBox"]
        box = np.zeros_like(target)
        box[max(0, round((L["y"] + by0) * SCALE)):round((L["y"] + by1) * SCALE),
            max(0, round((L["x"] + bx0) * SCALE)):round((L["x"] + bx1) * SCALE)] = 1
        target &= box
    return target


def write_grid(path: Path, verts: np.ndarray, uvs: np.ndarray, faces: np.ndarray) -> None:
    v = np.asarray(verts, np.float32)
    with open(path, "wb") as f:
        f.write(struct.pack("<ii", len(v), 1))
        f.write(v.tobytes())
        f.write(np.tile(np.array([0, 1, 0], np.float32), (len(v), 1)).tobytes())
        f.write(np.asarray(uvs, np.float32).tobytes())
        f.write(struct.pack("<i", faces.size))
        f.write(np.asarray(faces, np.int32).ravel().tobytes())


def projected_grid(cam: dict, z: np.ndarray, rect: tuple[int, int, int, int], bias: float,
                   break_ratio: float | None = GRID_BREAK_RATIO) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Camera-projected grid over a frame rect, each vertex pushed to depth z*bias along its pixel ray."""
    x0, y0, x1, y1 = rect
    xs = np.unique(np.r_[np.arange(x0, x1, GRID_STEP), x1])
    ys = np.unique(np.r_[np.arange(y0, y1, GRID_STEP), y1])
    gx, gy = np.meshgrid(xs, ys)
    zz = z[np.clip(gy, 0, H - 1), np.clip(gx, 0, W - 1)] * bias
    t = math.tan(math.radians(cam["fov"]) / 2)
    nx = (gx / W) * 2 - 1
    ny = 1 - (gy / H) * 2
    d = (cam["fwd"][None, None] + cam["right"][None, None] * (nx * t * W / H)[..., None]
         + cam["up"][None, None] * (ny * t)[..., None])
    verts = (cam["pos"][None, None] + d * zz[..., None]).reshape(-1, 3)
    uvs = np.stack([(gx - x0) / max(1, x1 - x0), 1 - (gy - y0) / max(1, y1 - y0)], -1).reshape(-1, 2)
    n = len(xs)
    j, i = np.meshgrid(np.arange(len(ys) - 1), np.arange(n - 1), indexing="ij")
    a = (j * n + i).ravel()
    tris = np.concatenate([np.stack([a, a + 1, a + n], 1), np.stack([a + 1, a + n + 1, a + n], 1)])
    if break_ratio:
        zf = zz.ravel()[tris]
        tris = tris[zf.max(1) / zf.min(1) <= break_ratio]
    return verts, uvs, tris


def emit_projected(cam: dict, z: np.ndarray, rgba: np.ndarray, name: str, bias: float, lab: Path) -> dict | None:
    ys, xs = np.nonzero(rgba[..., 3] > 8)
    if len(xs) == 0:
        return None
    rect = (max(0, xs.min() - 2), max(0, ys.min() - 2), min(W, xs.max() + 3), min(H, ys.max() + 3))
    crop = rgba[rect[1]:rect[3], rect[0]:rect[2]]
    Image.fromarray(crop).save(lab / "data" / f"proj_{name}.png")
    v, uv, f = projected_grid(cam, z, rect, bias)
    write_grid(lab / "data" / f"proj_{name}.bytes", v, uv, f)
    return {"name": name, "mesh": f"proj_{name}.bytes", "texture": f"proj_{name}.png",
            "rectPx": [int(r) for r in rect], "pixels": int((crop[..., 3] > 127).sum())}


# Proportion fixes (relay 3 step 2), no new Meshy spend. The hall mesh reads squat against HoMM3's tall
# palace: a fitted vertical stretch plus a top-edge term. The castle's central minaret overshot its sprite
# top by 58 px (a thin spire is too few pixels for F-beta to see); a whole-body squash to fix it cost IoU
# (0.501 -> 0.455) by shortening the walls, so the castle instead gets knee surgery: only geometry above
# the side towers (the minaret) is compressed.
# The regenerated castle (tbelcstl_3_keep) needs no surgery (top within 8 px); the knee mode stays for a1.
STRETCH_FIT = {"tbelhall_4": {"mode": "stretch", "lo": 1.0, "hi": 1.45},
               "tbelcstl_3": {"mode": "knee", "axis_frac": 0.1},
               # Lower-level mage towers (relay 2026-09-26): the uniform fit stops short of the dome and spire
               # (pre-spend probe IoU 0.58-0.60, mesh top below the sprite top); same stretch pass as the hall.
               "tbelmage": {"mode": "stretch", "lo": 1.0, "hi": 1.45},
               "tbelmage_2": {"mode": "stretch", "lo": 1.0, "hi": 1.45},
               "tbelmage_3": {"mode": "stretch", "lo": 1.0, "hi": 1.45}}


# Optional yaw search windows (degrees) for meshes whose silhouette is near-symmetric front/back. None is
# needed now: the regenerated castle's yaw 210 is its front (gate, dome, teal towers); what looked like a
# back view was the terrain-inflated scale, fixed by its fitBox.
YAW_WINDOW: dict[str, tuple[int, int]] = {}


def fit_cached(key: str, fitter: Fitter, bbox, stretch: dict | None = None,
               yaw_window: tuple[int, int] | None = None) -> dict:
    cache_p = WORK / "fits" / "fits.json"
    cache = json.loads(cache_p.read_text(encoding="utf-8")) if cache_p.is_file() else {}
    if yaw_window:
        key += f"|yaw:{yaw_window[0]}..{yaw_window[1]}"
    base_key = key
    if stretch:
        key += "|stretch:" + json.dumps(stretch, sort_keys=True)
    if key in cache:
        r = dict(cache[key])
        r.setdefault("stretchY", 1.0)
        v = fitter.v0
        if "kneeY" in r:
            fitter.v0 = knee_remap(fitter.v_raw, r["kneeY"] - fitter.model_lo_y, r["kneeScale"])
        _, w = fitter.transform(r["yaw"], r["scale"], *r["contactPx"], r["stretchY"])
        r["silhouette"] = fitter.silhouette(w, full=True)
        fitter.v0 = v
        return r
    if stretch and base_key in cache:
        r = dict(cache[base_key])
    else:
        r = fitter.fit(bbox, **({"yaws": range(yaw_window[0], yaw_window[1] + 1, 15)} if yaw_window else {}))
    if stretch:
        opts = {k: v for k, v in stretch.items() if k != "mode"}
        r = fitter.refine_knee(r, **opts) if stretch["mode"] == "knee" else fitter.refine_stretch(r, **opts)
    cache_p.parent.mkdir(parents=True, exist_ok=True)
    cache[key] = {k: v for k, v in r.items() if k != "silhouette"}
    cache_p.write_text(json.dumps(cache, indent=1), encoding="utf-8")
    return r


def slot_of(s: dict) -> str:
    """Town slot of a state entry: the layer without its level suffix (tbelhall_4 -> tbelhall)."""
    if s.get("slot"):
        return s["slot"]
    m = re.fullmatch(r"(tbeldw_\d+)(?:_\d+)?", s["layer"])  # dwellings: tbeldw_<tier>[_<upgrade>]
    return m.group(1) if m else re.sub(r"_\d+$", "", s["layer"])


def inst_of(s: dict) -> str:
    return s.get("name", s.get("mesh", s["layer"]))


def town_states() -> dict[str, list[dict]]:
    """The full STATE first, then each variant: the full state with the variant's slots replaced."""
    out = {"full": STATE}
    for sname, entries in VARIANT_STATES.items():
        slots = {slot_of(e) for e in entries}
        out[sname] = [s for s in STATE if slot_of(s) not in slots] + list(entries)
    return out


def compose_state(layers: dict, state: list[dict]):
    """HoMM3 reference composite of one town state, per-layer draw rank, hidden-pixel masks, alpha coverage."""
    rank = {lid: i for i, lid in enumerate(sorted({s["layer"] for s in state},
                                                   key=lambda k: (layers[k]["z"], layers[k]["order"])))}
    ref = plate().convert("RGBA")
    covered = np.zeros((H, W), bool)
    alphas = {}
    for lid in sorted(rank, key=rank.get):
        full = layer_frame(layers[lid])
        ref.alpha_composite(Image.fromarray(full))
        alphas[lid] = full[..., 3] > 127
        covered |= full[..., 3] > 8
    # Pixels of a layer hidden under a later-drawn layer: their composite depth belongs to the layer on
    # top, so they must never be projected (a sprite's painted ground under the portal was projected at
    # the portal's depth and drew over the 3D ring).
    hidden = {}
    for lid in rank:
        h = np.zeros((H, W), bool)
        for other, a in alphas.items():
            if rank[other] > rank[lid]:
                h |= a
        hidden[lid] = h
    return ref, rank, hidden, covered


def stage() -> dict:
    cam = camera()
    WORK.mkdir(parents=True, exist_ok=True)
    (WORK / "fits").mkdir(exist_ok=True)
    layers = {l["id"]: l for l in json.loads((REFS / "layers" / "positions.json").read_text())["layers"]}
    states = town_states()
    img = plate()
    img.save(WORK / "conflux_plate_1920.png")

    # The full state's composite defines the depth alignment and the shipped layerDepths, as before.
    refs = {name: compose_state(layers, st) for name, st in states.items()}
    ref, _, _, covered = refs["full"]
    ref.convert("RGB").save(WORK / "homm3_conflux_reference_1920.png")
    for name in states:
        if name != "full":
            refs[name][0].convert("RGB").save(WORK / f"homm3_conflux_reference_{name}_1920.png")

    # Depth: plate (backdrop surface) and each state's composite (projected layers), aligned to the plate.
    cache = WORK / "fits" / "disparity.npz"
    sig = hashlib.sha1(np.asarray(ref).tobytes()).hexdigest()
    if cache.is_file() and str(np.load(cache)["sig"]) == sig:
        dd = np.load(cache)
        d_plate, d_comp = dd["plate"], dd["comp"]
    else:
        d_plate, d_comp = depth(img), depth(ref.convert("RGB"))
        np.savez_compressed(cache, plate=d_plate, comp=d_comp, sig=sig)
    lo, hi = np.percentile(d_plate, 1), np.percentile(d_plate, 99.5)
    z = extend_smear(disparity_to_z(d_plate, lo, hi))

    def aligned_z(d_c: np.ndarray, cov: np.ndarray) -> tuple[np.ndarray, dict]:
        bgm = ~cv2.dilate(cov.astype(np.uint8), np.ones((17, 17), np.uint8)).astype(bool)
        bgm[TOWN_H:] = False
        bgm[:, TOWN_W:] = False  # align on HoMM3-authored background only
        A = np.stack([d_c[bgm], np.ones(bgm.sum())], 1)
        (g_a, g_b), *_ = np.linalg.lstsq(A, d_plate[bgm], rcond=None)
        al = g_a * d_c + g_b
        res_ = float(np.median(np.abs(al[bgm] - d_plate[bgm])) / (hi - lo))
        zz = extend_smear(disparity_to_z(al, lo, hi))
        # A painted layer lies on or in front of the terrain it is painted on, never behind it. Depth Anything reads
        # some painted ground features as hollows (the tbeldw_3 lava crater: 86% of its pixels came out behind the
        # plate surface), and the backdrop surface then hid them in every preview render. Clamp to the plate.
        behind = zz > z
        return np.minimum(zz, z), {"gain": float(g_a), "offset": float(g_b), "bgPixels": int(bgm.sum()),
                                   "medianResidualOfRange": res_, "clampedToPlatePixels": int(behind.sum())}

    z_comp, depth_align = aligned_z(d_comp, covered)
    np.save(WORK / "conflux_plate_z.npy", z.astype(np.float32))
    np.save(WORK / "conflux_composite_z.npy", z_comp.astype(np.float32))
    for nm, zz in (("conflux_plate_z_viz.png", z), ("conflux_composite_z_viz.png", z_comp)):
        Image.fromarray((255 * (1 - (zz - Z_NEAR) / (Z_FAR - Z_NEAR))).clip(0, 255).astype(np.uint8)).save(WORK / nm)
    z_states = {"full": z_comp}
    align_states = {"full": depth_align}
    for name in states:
        if name == "full":
            continue
        sref, _, _, scov = refs[name]
        c_p = WORK / "fits" / f"disparity_{name}.npz"
        ssig = hashlib.sha1(np.asarray(sref).tobytes()).hexdigest()
        if c_p.is_file() and str(np.load(c_p)["sig"]) == ssig:
            sd = np.load(c_p)["comp"]
        else:
            sd = depth(sref.convert("RGB"))
            np.savez_compressed(c_p, comp=sd, sig=ssig)
        z_states[name], align_states[name] = aligned_z(sd, scov)

    lab = LAB
    if (lab / "data").exists():
        shutil.rmtree(lab / "data")
    (lab / "data").mkdir(parents=True)
    v, uv, f = projected_grid(cam, z, (0, 0, W, H), 1.0, break_ratio=None)
    write_grid(lab / "data" / "conflux_backdrop_surface.bytes", v, uv, f)
    shutil.copy2(WORK / "conflux_plate_1920.png", lab / "data" / "conflux_plate_1920.png")

    from scipy.ndimage import binary_fill_holes

    meshes, projected, fits = [], [], []
    by_inst: dict[str, dict] = {}
    for sname, state in states.items():
        _, rank, hidden, _ = refs[sname]
        zc_state = z_states[sname]
        tag = "" if sname == "full" else f"__{sname}"
        for s in state:
            L = layers[s["layer"]]
            if "mesh" not in s:
                # Projected 2D layer, emitted per state (its depth and hidden pixels depend on the state).
                rgba = layer_frame(L, s.get("span")).copy()
                rgba[..., 3] = np.where(hidden[s["layer"]], 0, rgba[..., 3])
                row = emit_projected(cam, zc_state, rgba, s["layer"] + tag, 0.995 - 0.001 * rank[s["layer"]], lab)
                if row:
                    row.update({"role": "layer", "layer": s["layer"], "states": [sname]})
                    projected.append(row)
                continue
            inst = inst_of(s)
            if inst in by_inst:  # same instance as an earlier state: shown here too, never re-emitted
                by_inst[inst]["states"].append(sname)
                for pr in projected:
                    if pr.get("instance") == inst:
                        pr["states"].append(sname)
                continue
            name = s["mesh"]
            src = MESHY / name / MESH_ATTEMPT
            glb = src / "model.glb"
            if not glb.is_file():
                raise SystemExit(f"{name}: {glb} missing")
            rgba = layer_frame(L, s.get("span"))
            fit_s = dict(s, layer=s["fitLayer"]) if s.get("fitLayer") else s
            target = fit_target(layers, fit_s, layer_frame(layers[fit_s["layer"]], s.get("span")))
            verts, faces = load_glb_unity(glb)
            fitter = Fitter(cam, z, (W, H), target, verts, faces, down=2)
            ys, xs = np.nonzero(target)
            bbox = (xs.min(), ys.min(), xs.max() + 1, ys.max() + 1)
            key = f"{name}|{hashlib.sha1(glb.read_bytes()).hexdigest()[:12]}|{hashlib.sha1(target.tobytes()).hexdigest()[:12]}"
            r = fit_cached(key, fitter, bbox, STRETCH_FIT.get(name), YAW_WINDOW.get(name))
            # Unity root transform: world = rootPos + R * (s * v); the fitter placed R * s * (v - c) + pos.
            lo_v, hi_v = verts.min(0), verts.max(0)
            c = np.array([(lo_v[0] + hi_v[0]) / 2, lo_v[1], (lo_v[2] + hi_v[2]) / 2])
            k = r.get("stretchY", 1.0)
            root = np.array(r["position"]) - yaw_matrix(r["yaw"]) @ (c * np.array([1.0, k, 1.0]) * r["scale"])
            if not (lab / "data" / f"{name}.glb").is_file():
                shutil.copy2(glb, lab / "data" / f"{name}.glb")
                shutil.copy2(src / "texture_0_base_color.png", lab / "data" / f"{name}_base_color.png")
            owner = s.get("bakeAs", inst)
            baked = WORK / "materials" / f"{owner}_hexlit_base.png"
            if baked.is_file():  # bake_town_materials.py output (material/lighting pass)
                shutil.copy2(baked, lab / "data" / f"{owner}_hexlit_base.png")
            row_m = {"name": inst, "mesh": name, "layer": s["layer"], "glb": f"{name}.glb",
                     "baseColor": f"{owner}_hexlit_base.png" if baked.is_file() else f"{name}_base_color.png",
                     "rawBaseColor": f"{name}_base_color.png", "bakeAs": owner, "states": [sname],
                     "fitLayer": fit_s["layer"], "fitBox": list(s["fitBox"]) if s.get("fitBox") else None,
                     "span": list(s["span"]) if s.get("span") else None,
                     "rootPosition": [float(x) for x in root], "yaw": r["yaw"], "scale": r["scale"],
                     "stretchY": k, **({"kneeY": r["kneeY"], "kneeScale": r["kneeScale"]} if "kneeY" in r else {})}
            meshes.append(row_m)
            by_inst[inst] = row_m
            sil = cv2.resize(r["silhouette"].astype(np.uint8), (W, H), interpolation=cv2.INTER_NEAREST).astype(bool)
            Image.fromarray((sil * 255).astype(np.uint8)).save(WORK / "fits" / f"fitmask_{inst}.png")
            # Skirt: sprite pixels the mesh does not represent, limited to the ground band and enclosed holes.
            grown = cv2.dilate(sil.astype(np.uint8), np.ones((2 * SKIRT_DILATE_PX + 1,) * 2, np.uint8)).astype(bool)
            holes = binary_fill_holes(sil) & ~sil
            band = np.zeros((H, W), bool)
            band[int(bbox[3] - s.get("skirtFrac", SKIRT_BASE_FRAC) * (bbox[3] - bbox[1])):, :] = True
            visible = (rgba[..., 3] > 8) & ~hidden[s["layer"]]
            skirt = rgba.copy()
            skirt[..., 3] = np.where(visible & ~grown & band, skirt[..., 3], 0)
            srow = emit_projected(cam, zc_state, skirt, f"skirt_{inst}", 0.996, lab)
            if srow:
                srow.update({"role": "skirt", "layer": s["layer"], "instance": inst, "states": [sname]})
                projected.append(srow)
            # Enclosed holes (the portal surface inside the ring) are a separate part at the mesh's own camera
            # depth, so they move with the frame instead of the terrain (the stand-in for the animated disc).
            hole = rgba.copy()
            hole[..., 3] = np.where(visible & holes, hole[..., 3], 0)
            zc = float(np.dot(np.array(r["position"]) - cam["pos"], cam["fwd"]))
            hrow = emit_projected(cam, np.full((H, W), zc, np.float32), hole, f"hole_{inst}", 1.0, lab)
            if hrow and hrow["pixels"] > 200:
                hrow.update({"role": "hole", "layer": s["layer"], "instance": inst, "states": [sname]})
                projected.append(hrow)
            fits.append({"name": inst, "mesh": name, "layer": s["layer"], "state": sname,
                         "yaw": round(r["yaw"], 1), "scale": round(r["scale"], 4),
                         "stretchY": round(k, 4), "topOffsetPx": round(r["topOffsetPx"], 1) if "topOffsetPx" in r else None,
                         "worldHeight": round(r["worldHeight"], 2), "contactPx": [round(x, 1) for x in r["contactPx"]],
                         "fitIoU": round(r["iou"], 4), "fitPrecision": round(r["precision"], 4),
                         "fitRecall": round(r["recall"], 4), "fitFbeta": round(r["fbeta"], 4),
                         "skirtPixels": srow["pixels"] if srow else 0,
                         "holePixels": hrow["pixels"] if hrow and hrow["pixels"] > 200 else 0, "spritePixels": int(target.sum())})
            print(json.dumps(fits[-1]), flush=True)

    stock = lab / "stock"
    if stock.exists():
        shutil.rmtree(stock)
    shutil.copytree(STOCK, stock)
    scene = cam["scene"]
    sun = next(l for l in scene["lights"] if l["type"] == 1)
    sm = np.array(sun["m"]).reshape(4, 4).T
    city_sun = (sm[:3, 2] / np.linalg.norm(sm[:3, 2])).tolist()
    bake_rep = WORK / "materials" / "bake_report.json"
    bake = json.loads(bake_rep.read_text(encoding="utf-8")) if bake_rep.is_file() else {}
    key_sun = bake["keyLight"]["sunDir"] if bake else None
    spec = {
        "schema": "homm3_conflux_town3d_preview.v2",
        "frame": [W, H],
        "camera": {"pos": cam["pos"].tolist(), "fwd": cam["fwd"].tolist(), "up": cam["up"].tolist(),
                   "fov": cam["fov"]},
        # Buildings are lit by the key light fitted to the painting when the material bake exists (the
        # town scene sets its directional light to it); the stock render keeps the cityHuman2 sun.
        "sunDir": key_sun if key_sun is not None else city_sun,
        "stockSunDir": city_sun,
        # Fill light the bake divided by (second directional light; absent = none).
        "fill": bake.get("fillLight") or {"dir": [0, -1, 0], "color": [0, 0, 0]},
        "fog": scene["fog"],
        "rig": city_rig(scene),
        "stockRigs": [ARENA_RIG, city_rig(scene)],
        "backdrop": {"mesh": "conflux_backdrop_surface.bytes", "texture": "conflux_plate_1920.png"},
        # Town states: "full" is the shipped preview (conflux3d_default.png); the others are lower-level towns.
        "states": list(states),
        "meshes": meshes,
        "projected": projected,
        "stockScene": "stock/scene.json",
        "outDir": str((WORK / "unity_out").resolve()).replace("\\", "/"),
        "orbit": {"frames": 48, "lateral": 3.0, "dolly": 4.0},
    }
    out = WORK / "unity_out"
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    (lab / "data" / "spec.json").write_text(json.dumps(spec, indent=1), encoding="utf-8")
    (WORK / "preview_spec.json").write_text(json.dumps(spec, indent=1), encoding="utf-8")
    stage_rep = {"schema": "homm3_conflux_town3d_stage.v3", "state": STATE, "variantStates": VARIANT_STATES,
                 "depthAlign": depth_align, "depthAlignByState": align_states,
                 "fits": fits, "projected": [{k: p[k] for k in ("name", "role", "layer", "pixels")} for p in projected]}
    (WORK / "fits" / "stage_report.json").write_text(json.dumps(stage_rep, indent=1, default=list), encoding="utf-8")
    for f in UNITY_SRC.glob("*"):
        dest = (PROJECT / "Assets" / "Editor" / f.name) if f.suffix == ".cs" else (lab / f.name)
        shutil.copy2(f, dest)
    return {"meshes": len(meshes), "projected": len(projected), "depthAlign": stage_rep["depthAlign"]}


def unity() -> int:
    log = WORK / "unity_out" / "unity.log"
    cmd = [str(UNITY), "-batchmode", "-quit", "-projectPath", str(PROJECT),
           "-executeMethod", "Homm3ConfluxTown3dPreview.Run", "-logFile", str(log)]
    rc = UQ.run_cmd(cmd, kind="conflux_town3d_preview", direct=UNITY_DIRECT).returncode
    print("unity rc", rc, "log", log)
    return rc


def label(img: Image.Image, text: str, size: int = 34) -> Image.Image:
    img = img.copy()
    d = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("arial.ttf", size)
    except OSError:
        font = ImageFont.load_default()
    d.rectangle((0, 0, img.width, size + 16), fill=(0, 0, 0))
    d.text((14, 8), text, fill=(255, 255, 255), font=font)
    return img


def mask_metrics(mask: np.ndarray, target: np.ndarray) -> dict:
    inter = float((mask & target).sum())
    union = float((mask | target).sum())
    out = {"iou": inter / max(1.0, union), "precision": inter / max(1.0, mask.sum()),
           "recall": inter / max(1.0, target.sum())}
    if mask.any():
        my, mx = np.nonzero(mask)
        ty, tx = np.nonzero(target)
        out["centroidOffsetPx"] = [float(mx.mean() - tx.mean()), float(my.mean() - ty.mean())]
        out["bboxOffsetPx"] = {"left": int(mx.min() - tx.min()), "top": int(my.min() - ty.min()),
                               "right": int(mx.max() - tx.max()), "bottom": int(my.max() - ty.max())}
    return out


def compose() -> dict:
    out = WORK / "unity_out"
    media = WORK / "media"
    media.mkdir(exist_ok=True)
    spec = json.loads((WORK / "preview_spec.json").read_text(encoding="utf-8"))
    stage_rep = json.loads((WORK / "fits" / "stage_report.json").read_text(encoding="utf-8"))
    layers = {l["id"]: l for l in json.loads((REFS / "layers" / "positions.json").read_text())["layers"]}
    ref = np.asarray(Image.open(WORK / "homm3_conflux_reference_1920.png").convert("RGB")).astype(np.int16)
    render = np.asarray(Image.open(out / "conflux3d_default.png").convert("RGB")).astype(np.int16)

    rows, masks = [], {}
    for mrow in spec["meshes"]:
        name = mrow["name"]
        fit_s = {"layer": mrow.get("fitLayer") or mrow["layer"], "fitBox": mrow.get("fitBox")}
        target = fit_target(layers, fit_s, layer_frame(layers[fit_s["layer"]], mrow.get("span"))) > 0
        m = np.asarray(Image.open(out / f"mask_{name}.png").convert("L")) > 127
        masks[name] = (m, target)
        fit = next(f for f in stage_rep["fits"] if f["name"] == name)
        mm = mask_metrics(m, target)
        rows.append({"name": name, "mesh": mrow.get("mesh", name), "layer": mrow["layer"],
                     "states": mrow.get("states") or ["full"], "unityIoU": round(mm["iou"], 4),
                     "unityPrecision": round(mm["precision"], 4), "unityRecall": round(mm["recall"], 4),
                     "centroidOffsetPx": [round(v, 1) for v in mm.get("centroidOffsetPx", [float("nan")] * 2)],
                     "bboxOffsetPx": mm.get("bboxOffsetPx"), "fitIoU": fit["fitIoU"], "yaw": fit["yaw"],
                     "worldHeight": fit["worldHeight"], "skirtPixels": fit["skirtPixels"],
                     "spritePixels": fit["spritePixels"]})
    town = np.zeros((H, W), bool)
    town[:TOWN_H, :TOWN_W] = True
    by_state = {}
    state_imgs = {}
    for st in spec.get("states") or ["full"]:
        ref_p = WORK / ("homm3_conflux_reference_1920.png" if st == "full" else f"homm3_conflux_reference_{st}_1920.png")
        ren_p = out / ("conflux3d_default.png" if st == "full" else f"conflux3d_{st}.png")
        r_ = np.asarray(Image.open(ref_p).convert("RGB")).astype(np.int16)
        u_ = np.asarray(Image.open(ren_p).convert("RGB")).astype(np.int16)
        d_ = np.abs(u_ - r_).mean(-1)
        un = np.zeros((H, W), bool)
        st_rows = [r for r in rows if st in r["states"]]
        for r in st_rows:
            m, t = masks[r["name"]]
            un |= m | t
        by_state[st] = {"meanIoU": round(float(np.mean([r["unityIoU"] for r in st_rows])), 4),
                        "meanAbsDiffTownRGB": round(float(d_[town].mean()), 2),
                        "meanAbsDiffBuildingsRGB": round(float(d_[un & town].mean()), 2),
                        "meshes": [r["name"] for r in st_rows]}
        state_imgs[st] = (r_.astype(np.uint8), u_.astype(np.uint8), st_rows)
    diff = np.abs(render - ref).mean(-1)
    union = np.zeros(diff.shape, bool)
    for r in rows:
        if "full" in r["states"]:
            m, t = masks[r["name"]]
            union |= m | t
    report = {"schema": "homm3_conflux_town3d_alignment.v1",
              "proof": "Unity-editor render (preview Hex/Lit replica), default native camera pose; not in-game",
              "method": "per-mesh white-on-black Unity mask render vs the HoMM3 sprite alpha in the same frame mapping",
              "meanIoU": round(float(np.mean([r["unityIoU"] for r in rows if "full" in r["states"]])), 4),
              "meanAbsDiffTownRGB": round(float(diff[town].mean()), 2),
              "meanAbsDiffBuildingsRGB": round(float(diff[union & town].mean()), 2),
              "depthAlign": stage_rep["depthAlign"], "byState": by_state, "buildings": rows}
    (media / "conflux_town3d_alignment.json").write_text(json.dumps(report, indent=1), encoding="utf-8")

    # Overlay: render with HoMM3 sprite outlines (green) and Unity mesh-mask outlines (magenta).
    ov = np.asarray(Image.open(out / "conflux3d_default.png").convert("RGB")).copy()
    for name, (m, t) in masks.items():
        if not any(r["name"] == name and "full" in r["states"] for r in rows):
            continue
        for mask, col in ((t, (40, 255, 40)), (m, (255, 40, 255))):
            cs, _ = cv2.findContours(mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
            cv2.drawContours(ov, cs, -1, col, 2)
    ovi = Image.fromarray(ov)
    d = ImageDraw.Draw(ovi)
    try:
        font = ImageFont.truetype("arial.ttf", 22)
    except OSError:
        font = ImageFont.load_default()
    for r in rows:
        if "full" not in r["states"]:
            continue
        t = masks[r["name"]][1]
        ys, xs = np.nonzero(t)
        d.text((int(xs.min()) + 4, max(54, int(ys.min()) + 2)), f"{r['name']} IoU {r['unityIoU']:.2f}",
               fill=(255, 255, 0), font=font, stroke_width=2, stroke_fill=(0, 0, 0))
    ovi.save(media / "conflux_town3d_alignment_overlay.png")
    heat = cv2.applyColorMap(np.clip(diff * 2, 0, 255).astype(np.uint8), cv2.COLORMAP_INFERNO)[..., ::-1]
    Image.fromarray(heat).save(media / "conflux_town3d_alignment_diff.png")

    panels = [
        (Image.fromarray(ref.astype(np.uint8)), "HoMM3 Conflux town screen (same state, same frame mapping)"),
        (Image.open(out / "conflux3d_default.png").convert("RGB"), "Unity v2: registered Meshy meshes + depth-projected layers"),
        (ovi, "Overlay: HoMM3 sprite outline (green) vs Unity mesh mask (magenta)"),
        (Image.fromarray(heat), f"|Unity - HoMM3| (mean {report['meanAbsDiffTownRGB']:.1f} RGB over the town area)"),
    ]
    sheet = Image.new("RGB", (W * 2, H * 2))
    for i, (im, t) in enumerate(panels):
        sheet.paste(label(im.resize((W, H)), t), ((i % 2) * W, (i // 2) * H))
    sheet.save(media / "conflux_town3d_side_by_side.png")
    sheet.resize((W, H), Image.LANCZOS).save(media / "conflux_town3d_side_by_side_small.png")
    # Town states (lower-level towns): HoMM3 | Unity per state, with that state's mesh outlines.
    for st, (r_, u_, st_rows) in state_imgs.items():
        if st == "full":
            continue
        ov_s = u_.copy()
        for r in st_rows:
            m, t = masks[r["name"]]
            for mask, col in ((t, (40, 255, 40)), (m, (255, 40, 255))):
                cs, _ = cv2.findContours(mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
                cv2.drawContours(ov_s, cs, -1, col, 2)
        sh = Image.new("RGB", (W * 3, H))
        bs = by_state[st]
        sh.paste(label(Image.fromarray(r_), f"HoMM3 Conflux, town state {st}"), (0, 0))
        sh.paste(label(Image.fromarray(u_), f"Unity {st}: mean IoU {bs['meanIoU']:.2f}, |diff| {bs['meanAbsDiffTownRGB']:.1f}"), (W, 0))
        sh.paste(label(Image.fromarray(ov_s), "sprite outline (green) vs mesh mask (magenta)"), (2 * W, 0))
        sh.resize((W * 3 // 2, H // 2), Image.LANCZOS).save(media / f"conflux_town3d_{st}_side_by_side.png")
        # Close-up of the town area, HoMM3 above Unity.
        crop = (0, 0, TOWN_W, TOWN_H)
        cu = Image.new("RGB", (TOWN_W, TOWN_H * 2))
        cu.paste(label(Image.fromarray(r_).crop(crop), f"HoMM3 {st}", 28), (0, 0))
        cu.paste(label(Image.fromarray(u_).crop(crop), f"Unity {st}", 28), (0, TOWN_H))
        cu.save(media / f"conflux_town3d_{st}_town_closeup.png")
    extra = Image.new("RGB", (W * 2, H))
    extra.paste(label(Image.open(out / "conflux3d_meshes_only.png").convert("RGB"), "Unity v2: meshes on the backdrop only (no 2D layers or skirts)"), (0, 0))
    extra.paste(label(Image.open(out / "stock_cityHuman2.png").convert("RGB"), "Stock Olden Era cityHuman2 (native camera, Hex/Lit replica)"), (W, 0))
    extra.resize((W, H // 2), Image.LANCZOS).save(media / "conflux_town3d_meshes_only_vs_stock.png")
    raw_p = out / "conflux3d_default_raw.png"
    if raw_p.is_file():
        # Material pass: HoMM3 | raw Meshy base colour | baked base colour, full frame + close-ups.
        views = [(Image.fromarray(ref.astype(np.uint8)), "HoMM3"),
                 (Image.open(raw_p).convert("RGB"), "raw Meshy base colour (city rig)"),
                 (Image.open(out / "conflux3d_default.png").convert("RGB"), "material pass (city rig, key light)")]
        crops = [(0, 270, 540, 570), (420, 135, 795, 420), (960, 150, 1440, 480), (720, 480, 1050, 675)]
        cw = 640
        rows = [[label(v.crop((0, 0, W, H)).resize((cw, 360)), t, 18) for v, t in views]]
        for c in crops:
            ch = round(cw * (c[3] - c[1]) / (c[2] - c[0]))
            rows.append([v.crop(c).resize((cw, ch), Image.LANCZOS) for v, _ in views])
        hh = sum(r[0].height for r in rows)
        sheet_m = Image.new("RGB", (cw * 3, hh))
        y = 0
        for r in rows:
            for i, im in enumerate(r):
                sheet_m.paste(im, (i * cw, y))
            y += r[0].height
        sheet_m.save(media / "conflux_town3d_materials.png")
    ff = shutil.which("ffmpeg")
    video = None
    if ff and list(out.glob("orbit_*.png")):
        video = media / "conflux_town3d_camera_move.mp4"
        subprocess.run([ff, "-y", "-loglevel", "error", "-framerate", "24", "-i", str(out / "orbit_%03d.png"),
                        "-pix_fmt", "yuv420p", "-vf", "scale=1280:-2", str(video)], check=True)
    return {"meanIoU": report["meanIoU"], "meanAbsDiffTownRGB": report["meanAbsDiffTownRGB"], "byState": by_state,
            "video": str(video) if video else None}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("step", choices=["stage", "unity", "compose"])
    a = ap.parse_args()
    if a.step == "stage":
        print(json.dumps(stage(), indent=1))
    elif a.step == "unity":
        return unity()
    else:
        print(json.dumps(compose(), indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
