"""Authenticity board: every DEF frame of every clip next to the GLB the game ships, from three cameras.

    python tools/homm3_authenticity/board.py <unit> [--glb <path>] [--out <dir>] [--clips a,b] [--device cuda|cpu]

<unit> is a lab sid (homm3_import.json / delivery selections) or its retarget source unit (fleet_census.SOURCE_UNIT).
Default GLB: the frozen delivered_idle_retimed.glb of the unit's live delivery selection (sources.py); --glb renders
a candidate instead. DEF frames: the unit's linked master (master_sequence.json + the build's frames.json).
DEF frame i of a clip with n frames sits at t = start + i * step of the GLB clip, step = duration / m with
m = n - 1 (one-shot) or n + transitionKeys (Idle / Move loops: closing key + seam keys, frames.json "loops"),
so any retime the delivery applied (idle x3.2) is read from the GLB's own clip duration.

Rows per clip board: DEF | sprite (DEF-matched SpriteCam, same px scale as the DEF) | overlay (DEF-only red,
render-only blue, both grey; IoU) | battle (ortho, 40 deg elevation, azimuth -60 from glTF +Z) | preview
(perspective; UiConstants.UnitCamParams geometry + the fleet preview facing rule). One fixed camera box per clip.
Outputs (default V:/olden_port_work/authenticity/<unit>/boards/): clip_<clip>.png, clip_<clip>.gif, overview.png,
board.json. Torch on CUDA by default; --device cpu is the reference (test_board.py); no silent fallback.
Proof tier: generated artifact (offline render of the GLB; the in-game look is not proven by a board).
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import raster as R  # noqa: E402
import torch  # noqa: E402
from gltf_scene import Scene  # noqa: E402
from sources import ROOT, def_reference, load, preview_framing, sha256, shipped_glb, unit_ids  # noqa: E402
from spritecam import ry, sprite_camera, view_yawed  # noqa: E402,F401

SCHEMA = "homm3_authenticity_board.v1"
CELL_H = 200            # clip board: tallest clip box -> this many px (per view, unit-wide scale)
GIF_H = 180
OV_H = 96
GIF_FPS = 20
BG = (196, 198, 202)
DEF_ALPHA_BODY = 200    # DEF shadow pixels are black at alpha 64/128; the body is 255
# battle: tools/homm3_prebake/render_passes.py FACINGS["faces_right"], --elev 40 (unit-look lane)
BATTLE = {"elevDeg": 40.0, "azimuthDeg": -60.0}
# preview: UiConstants.UnitCamParams (angle 13.7, distance 25, yOffset 1.95; measure_owned_preview_framing.py) with the
# fleet facing rule (Homm3ImportVisuals.OwnedSkinnedOrientationYawFor; Homm3FacingProofRig.cs): model root yaw 22,
# Orientation 90 - (-60) = 150, body frame = Orientation * yaw(-60) -> body yaw 112 under a camera at -Z looking +Z,
# i.e. the camera sits 68 deg round to the unit's right from its front.
PREVIEW = {"elevDeg": 13.7, "azimuthDeg": -68.0, "distanceWorld": 25.0, "yOffsetWorld": 1.95}


def font(size: int):
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # pragma: no cover (Pillow < 10.1)
        return ImageFont.load_default()


# ------------------------------------------------------------------ cameras (glTF space: +Y up, unit faces +Z)
def _norm(v):
    v = np.asarray(v, np.float64)
    return v / np.linalg.norm(v)


def orbit_dirs(elev_deg: float, az_deg: float) -> dict:
    """Camera axes looking at the unit from azimuth az (from the unit's front +Z towards its left +X) and elevation."""
    a, e = math.radians(az_deg), math.radians(elev_deg)
    front, left, up = np.array([0, 0, 1.0]), np.array([1.0, 0, 0]), np.array([0, 1.0, 0])
    to_cam = (front * math.cos(a) + left * math.sin(a)) * math.cos(e) + up * math.sin(e)
    fwd = -_norm(to_cam)
    right = _norm(np.cross(fwd, up))
    return {"to_cam": _norm(to_cam), "fwd": fwd, "right": right, "up": np.cross(right, fwd)}


def with_box(cam: dict, x0: float, y0: float, w: int, h: int, zoom: float = 1.0) -> dict:
    """The same mapping, cropped to the box [x0, x0 + w) x [y0, y0 + h) of cam's pixel grid and scaled by zoom."""
    return dict(cam, cx=(cam["cx"] - x0) * zoom, cy=(cam["cy"] - y0) * zoom, scale=cam["scale"] * zoom,
                W=max(1, int(round(w * zoom))), H=max(1, int(round(h * zoom))))


def raw_extent(cam: dict, P: torch.Tensor) -> tuple[float, float, float, float]:
    """Pixel bbox (x0, y0, x1, y1) of every vertex of every frame P (B, N, 3) under cam."""
    xy, _ = R.project(cam, P)
    lo = xy.reshape(-1, 2).min(0).values.cpu().numpy()
    hi = xy.reshape(-1, 2).max(0).values.cpu().numpy()
    return float(lo[0]), float(lo[1]), float(hi[0]), float(hi[1])


# ------------------------------------------------------------------ masks and metrics
def mask_stats(m: np.ndarray) -> dict | None:
    ys, xs = np.nonzero(m)
    if len(xs) == 0:
        return None
    x0, x1, y0, y1 = int(xs.min()), int(xs.max()) + 1, int(ys.min()), int(ys.max()) + 1
    return {"bbox": [x0, y0, x1, y1], "w": x1 - x0, "h": y1 - y0, "wh": round((x1 - x0) / (y1 - y0), 4),
            "centroid": [float(xs.mean()) + 0.5, float(ys.mean()) + 0.5], "area": int(len(xs))}


def iou(a: np.ndarray, b: np.ndarray) -> float | None:
    u = np.logical_or(a, b).sum()
    return None if u == 0 else float(np.logical_and(a, b).sum() / u)


def crop(img: np.ndarray, x0: int, y0: int, w: int, h: int) -> np.ndarray:
    """img[y0:y0+h, x0:x0+w] with zero padding outside."""
    out = np.zeros((h, w) + img.shape[2:], img.dtype)
    H, W = img.shape[:2]
    sx0, sy0, sx1, sy1 = max(0, x0), max(0, y0), min(W, x0 + w), min(H, y0 + h)
    if sx1 > sx0 and sy1 > sy0:
        out[sy0 - y0:sy1 - y0, sx0 - x0:sx1 - x0] = img[sy0:sy1, sx0:sx1]
    return out


def similarity_fit(def_m: np.ndarray, ren_m: np.ndarray) -> dict | None:
    """Scale k and shift t (px) with k * x_render + t ~ x_def, from area and centroid (2D similarity, no rotation)."""
    a, b = mask_stats(def_m), mask_stats(ren_m)
    if not a or not b:
        return None
    k = math.sqrt(a["area"] / b["area"])
    t = [a["centroid"][i] - k * b["centroid"][i] for i in range(2)]
    return {"k": k, "t": t, "shiftPx": float(math.hypot(a["centroid"][0] - b["centroid"][0], a["centroid"][1] - b["centroid"][1])),
            "defH": a["h"]}


def apply_fit(cam: dict, fit: dict) -> dict:
    return dict(cam, cx=fit["k"] * cam["cx"] + fit["t"][0], cy=fit["k"] * cam["cy"] + fit["t"][1],
                scale=cam["scale"] * fit["k"])


class DefFrame:
    """One DEF PNG kept as its opaque bbox only (the canvas is mostly empty; 56 full 1008x870 frames are 200 MB)."""

    def __init__(self, path: str, cam: dict):
        im = np.asarray(Image.open(path).convert("RGBA"))
        if im.shape[1] != cam["W"] or im.shape[0] != cam["H"]:
            raise SystemExit(f"DEF frame {path} is {im.shape[1]}x{im.shape[0]}, the sprite camera is {cam['W']}x{cam['H']}")
        self.size = (im.shape[1], im.shape[0])
        st = mask_stats(im[..., 3] > 0)
        self.bbox = st["bbox"] if st else None
        self.data = im[self.bbox[1]:self.bbox[3], self.bbox[0]:self.bbox[2]].copy() if st else np.zeros((0, 0, 4), np.uint8)

    def crop(self, x0: int, y0: int, w: int, h: int) -> np.ndarray:
        if not self.bbox:
            return np.zeros((h, w, 4), np.uint8)
        return crop(self.data, x0 - self.bbox[0], y0 - self.bbox[1], w, h)

    def full(self) -> np.ndarray:
        return self.crop(0, 0, self.size[0], self.size[1])


# ------------------------------------------------------------------ image helpers
def to_pil(rgba: torch.Tensor, bg=BG) -> Image.Image:
    """Premultiplied RGBA float (H, W, 4) on any device -> RGB over bg."""
    a = rgba.detach().float().cpu().numpy()
    rgb = a[..., :3] + (1 - a[..., 3:4]) * (np.array(bg, np.float32) / 255.0)
    return Image.fromarray((rgb.clip(0, 1) * 255 + 0.5).astype(np.uint8))


def def_pil(rgba: np.ndarray, bg=BG) -> Image.Image:
    a = rgba.astype(np.float32) / 255.0
    rgb = a[..., :3] * a[..., 3:4] + (1 - a[..., 3:4]) * (np.array(bg, np.float32) / 255.0)
    return Image.fromarray((rgb * 255 + 0.5).astype(np.uint8))


def overlay_pil(dm: np.ndarray, rm: np.ndarray) -> Image.Image:
    o = np.empty(dm.shape + (3,), np.uint8)
    o[:] = BG
    o[dm & rm] = (120, 120, 120)
    o[dm & ~rm] = (215, 50, 50)
    o[~dm & rm] = (45, 110, 235)
    return Image.fromarray(o)


def fit_h(im: Image.Image, h: int, nearest=False) -> Image.Image:
    if im.height == h:
        return im
    w = max(1, round(im.width * h / im.height))
    return im.resize((w, h), Image.NEAREST if nearest else Image.LANCZOS)


# ------------------------------------------------------------------ main work
class Board:
    def __init__(self, a):
        self.t0 = time.perf_counter()
        self.a = a
        self.dev = R.resolve_device(a.device)
        self.lab, self.src = unit_ids(a.unit)
        self.notes: list[str] = []
        if a.glb:
            p = Path(a.glb).resolve()
            if not p.is_file():
                raise SystemExit(f"--glb {p} does not exist")
            self.sel = {"mode": "override", "path": p, "sha256": sha256(p), "selection": None, "row": None,
                        "albedo": None, "candidates": [], "notes": ["--glb override: a candidate, not the shipped GLB"]}
            try:
                shipped = shipped_glb(self.lab, self.src)
                self.sel["row"] = shipped["row"]
                self.sel["shippedForReference"] = {"path": str(shipped["path"]), "sha256": shipped["sha256"],
                                                   "mode": shipped["mode"]}
            except SystemExit as e:
                self.sel["notes"].append(f"no shipped GLB to compare: {e}")
        else:
            self.sel = shipped_glb(self.lab, self.src)
        for n in self.sel["notes"]:
            print("NOTE:", n, flush=True)
        self.ref = def_reference(self.src)
        self.notes += self.ref["notes"]
        defer = dict((self.sel.get("row") or {}).get("deferMeshes") or {})
        if defer:   # the game builds only the body SMR for these, so the board must not draw them either
            self.notes.append("deferMeshes (not shipped, not drawn): " + ", ".join(sorted(defer)))
        self.scene = Scene(self.sel["path"], body_name=self.src, skip_meshes=tuple(defer))
        if self.scene.alpha_mode != "OPAQUE":
            raise SystemExit(f"{self.sel['path']}: body material alphaMode {self.scene.alpha_mode}; the board renders "
                             "OPAQUE bodies only (extend raster.shade before trusting a masked render)")
        if self.sel.get("albedo"):
            im = Image.open(self.sel["albedo"]).convert("RGBA")
            if max(im.size) > 1024:
                s = 1024 / max(im.size)
                im = im.resize((round(im.size[0] * s), round(im.size[1] * s)), Image.LANCZOS)
            tex = np.asarray(im, np.float32) / 255.0
            self.albedo_note = f"{Path(self.sel['albedo']).relative_to(ROOT).as_posix()} (the selection's shipped basecolor)"
        else:
            tex = self.scene.texture_rgba(1024)
            self.albedo_note = f"GLB image {self.scene.image_index} (embedded base colour)"
        memtrace("scene")
        self.mesh = R.DeviceMesh(self.scene, self.dev, tex)
        memtrace("mesh")
        self.out = Path(a.out) if a.out else Path("V:/olden_port_work/authenticity") / self.lab / "boards"
        self.out.mkdir(parents=True, exist_ok=True)
        want = None
        if a.clips:
            want = {c.strip() for c in a.clips.split(",") if c.strip()}
        self.clips, self.missing = [], []
        for c in self.ref["clips"]:
            if want and not ({c["clip"], c["clip"][5:], c["clipKey"]} & want):
                continue
            if c["clip"] not in self.scene.anims:
                self.missing.append({"clipKey": c["clipKey"], "clip": c["clip"], "reason": "GLB has no such clip"})
                continue
            self.clips.append(c)
        defclips = {c["clip"] for c in self.ref["clips"]}
        self.glb_only = sorted(n for n in self.scene.anims if n.startswith("Unit_") and n not in defclips)
        if not self.clips:
            raise SystemExit(f"{self.lab}: no clip to board (missing: {self.missing})")

    # -------------------------------------------------- per clip data
    def timing(self, c: dict) -> dict:
        rng = self.scene.clip_range(c["clip"])
        n = len(c["frames"])
        tk = int((c.get("loop") or {}).get("transitionKeys", 0))
        m = (n - 1) + ((1 + tk) if c.get("loop") else 0)
        step = rng["duration"] / m if m > 0 else 1 / 12
        return {**rng, "n": n, "loop": bool(c.get("loop")), "transitionKeys": tk, "stepsInClip": m, "step": step,
                "stepOver12fps": round(step * 12, 4), "times": [rng["start"] + i * step for i in range(n)]}

    def skin(self, clip: str, times) -> tuple[torch.Tensor, torch.Tensor]:
        Jm, mw = self.scene.pose(clip, np.asarray(times, np.float64))
        return self.mesh.skin(Jm, mw)

    def render(self, cam, P, N, ss=2):
        return R.render(self.mesh, cam, P, N, ss)

    def rest_frame_check(self, cam: dict) -> dict | None:
        si = self.ref.get("spriteInfo")
        if not si or "bbox0" not in si:
            return None
        bx0, by0, bx1, by1 = si["bbox0"]
        P = self.scene.P
        xs, ys = P @ np.asarray(cam["right"]), P @ np.asarray(cam["up"])
        top, bot = cam["cy"] - cam["scale"] * ys.max(), cam["cy"] - cam["scale"] * ys.min()
        cx = cam["cx"] + cam["scale"] * (xs.max() + xs.min()) / 2
        err = {"topPx": round(float(top - by0), 3), "bottomPx": round(float(bot - by1), 3),
               "centreXPx": round(float(cx - (bx0 + bx1) / 2), 3)}
        m = max(abs(v) for v in err.values())
        return {**err, "maxErrPx": m, "tolPx": max(1.5, 0.01 * (by1 - by0)), "ok": m <= max(1.5, 0.01 * (by1 - by0))}

    # -------------------------------------------------- run
    def run(self) -> dict:
        sc0 = sprite_camera(self.ref["spritecam"], (self.scene.extras.get("homm3DefRetargetDeliveryDeyaw") or {}).get("yawDeg"))
        deyaw = (self.scene.extras.get("homm3DefRetargetDeliveryDeyaw") or {}).get("yawDeg")
        vy = getattr(self.a, "view_yaw", None)
        if vy:
            # DEF-view diagnostic: turn the sprite camera about world up like the pose fitters' view yaw (proj.py /
            # posefit.py rotate the SpriteCam forward by Rz(yaw) in Blender = ry(+yaw) in glTF). The build camera's
            # rest calibration no longer applies, so every clip falls back to its own frame-0 similarity fit.
            sc0 = view_yawed(sc0, vy)
        data = []
        for c in self.clips:
            tm = self.timing(c)
            P, N = self.skin(c["clip"], tm["times"])
            defs = [DefFrame(p, sc0) for p in c["frames"]]
            data.append({"c": c, "tm": tm, "P": P, "N": N, "defs": defs})
            memtrace(f"loaded {c['clip']}")

        # sprite camera check on the idle (first clip) frame 0, then per clip frame 0 fits
        def native_mask(cam, P, N):
            img = self.render(cam, P, N, ss=2)
            return (img[..., 3] >= 0.5).cpu().numpy()

        fits = {}
        for d in data:
            rm = native_mask(sc0, d["P"][:1], d["N"][:1])
            dm = d["defs"][0].full()[..., 3] >= DEF_ALPHA_BODY
            f = similarity_fit(dm, rm)
            fits[d["c"]["clip"]] = {"directIoU": iou(dm, rm), "fit": f}
        memtrace("fits")
        ref_clip = "Unit_Idle" if "Unit_Idle" in fits else data[0]["c"]["clip"]
        rf = fits[ref_clip]
        # Does the exported SpriteCam still describe this GLB's frame? build_unit.py calibrated it on the body's REST
        # vertices against idle frame 0's DEF bbox (sprite_info.json bbox0): pxPerUnit = bbox height / rest up-extent,
        # rest bottom on the bbox bottom, rest centre on the bbox centre. Re-deriving those three numbers from this
        # GLB's bind-pose mesh is a pose-independent check (poses are what the board judges, so frame-0 IoU / area
        # scale are reported but never decide the mapping: a patched pose that is smaller than the DEF must stay
        # visibly smaller).
        rest = None if vy else self.rest_frame_check(sc0)
        aligned = rest is not None and rest["ok"]
        diag = (f"{ref_clip} frame 0 IoU {rf['directIoU']:.3f}, area scale {rf['fit']['k']:.3f}, centroid shift "
                f"{rf['fit']['shiftPx']:.1f} px") if rf["fit"] else f"{ref_clip} frame 0 empty"
        sprite_note = ("exact: build_unit.py SpriteCam (spritecam.json) applied as exported"
                       + (f", turned with the deyaw stage's Ry(-{deyaw})" if deyaw else "")
                       + f"; rest-mesh calibration reproduced within {rest['maxErrPx']:.2f} px; diagnostic: {diag}") if aligned else (
            f"SpriteCam does not describe this GLB's rest frame ({rest}); every clip uses a 2D similarity (area scale + "
            f"centroid shift) fitted on its own frame 0; diagnostic: {diag}")
        if vy:
            sprite_note = (f"view yaw {vy:g}: SpriteCam turned about world up by {vy:g} deg (pose-fit convention), a DEF-view "
                           f"diagnostic for units whose build camera does not see them from the DEF's side; every clip uses a "
                           f"2D similarity fitted on its own frame 0, so size is normalised; diagnostic: {diag}")
        align_idle = bool(getattr(self.a, "align", "clip") == "idle" and not aligned and rf["fit"])
        if align_idle:
            # one mapping for the whole unit: every clip keeps its world placement relative to Idle frame 0, so a clip
            # whose frame 0 moves vertically (the delivery ground stage's entry, a takeoff) is judged in place instead
            # of re-centred on its own frame 0 (2026-10-07 h3_royal_griffin MoveStart: the per-clip fit hid a 0.11 H
            # frame-0 drop as a lift of every later frame)
            sprite_note += f"; --align idle: every clip uses {ref_clip} frame 0's similarity, placement relative to it is judged"
        if not aligned:
            print("NOTE:", sprite_note, flush=True)

        # unit-wide scales: sprite/DEF zoom, battle and preview px per unit
        bdirs = orbit_dirs(BATTLE["elevDeg"], BATTLE["azimuthDeg"])
        pdirs = orbit_dirs(PREVIEW["elevDeg"], PREVIEW["azimuthDeg"])
        pf = preview_framing(self.lab, (self.sel.get("row") or {}).get("gameSid"))
        idle = next((d for d in data if d["c"]["clip"] == "Unit_Idle"), data[0])
        feet = float(idle["P"][0, :, 1].min())
        if pf and pf.get("battleTarget") and pf.get("rawHeight"):
            k_world = pf["battleTarget"] / pf["rawHeight"]
            pv_note = (f"approximate: UiConstants.UnitCamParams (perspective, elevation {PREVIEW['elevDeg']}, distance "
                       f"{PREVIEW['distanceWorld']} world, look-at {PREVIEW['yOffsetWorld']} world above the feet) at the "
                       f"fleet preview facing (camera {-PREVIEW['azimuthDeg']:.0f} deg to the unit's right); world scale "
                       f"{k_world:.4f}/GLB unit from owned_preview_framing.json (battleTarget/rawHeight). FOV unknown: "
                       "the box is crop-normalised, so only the perspective and angle are game-like; yOffset is read "
                       "as the look-at height (unverified)")
        else:
            h = float(idle["P"][0, :, 1].max()) - feet
            k_world = 2.0 / max(h, 1e-6)
            pv_note = "approximate: no owned_preview_framing row; unit height normalised to 2.0 world units"
        target = np.array([0.0, feet + PREVIEW["yOffsetWorld"] / k_world, 0.0])
        eye = target + pdirs["to_cam"] * PREVIEW["distanceWorld"] / k_world
        bcam0 = {"kind": "ortho", "eye": [0.0, 0.0, 0.0], **{k: bdirs[k] for k in ("right", "up", "fwd")},
                 "scale": 1.0, "cx": 0.0, "cy": 0.0, "W": 1, "H": 1}
        pcam0 = {"kind": "persp", "eye": eye, **{k: pdirs[k] for k in ("right", "up", "fwd")},
                 "scale": 1.0, "cx": 0.0, "cy": 0.0, "W": 1, "H": 1}
        for d in data:
            cl = d["c"]["clip"]
            own = rf["fit"] if align_idle else fits[cl]["fit"]
            d["scam"] = sc0 if aligned else (apply_fit(sc0, own) if own else sc0)
            x0, y0, x1, y1 = raw_extent(d["scam"], d["P"])
            for df in d["defs"]:
                if df.bbox:
                    x0, y0, x1, y1 = min(x0, df.bbox[0]), min(y0, df.bbox[1]), max(x1, df.bbox[2]), max(y1, df.bbox[3])
            pad = 6
            d["sbox"] = (int(math.floor(x0)) - pad, int(math.floor(y0)) - pad,
                         int(math.ceil(x1 - x0)) + 2 * pad + 1, int(math.ceil(y1 - y0)) + 2 * pad + 1)
            for key, cam in (("bbox_b", bcam0), ("bbox_p", pcam0)):
                bx0, by0, bx1, by1 = raw_extent(cam, d["P"])
                padb = 0.04 * max(bx1 - bx0, by1 - by0)
                d[key] = (bx0 - padb, by0 - padb, bx1 - bx0 + 2 * padb, by1 - by0 + 2 * padb)
        zs = CELL_H / max(d["sbox"][3] for d in data)
        zb = CELL_H / max(d["bbox_b"][3] for d in data)
        zp = CELL_H / max(d["bbox_p"][3] for d in data)

        def view_cam(cam0, box, z, zoom=1.0):
            x0, y0, w, h = box
            return dict(cam0, cx=-x0 * z * zoom, cy=-y0 * z * zoom, scale=z * zoom,
                        W=max(1, int(math.ceil(w * z * zoom))), H=max(1, int(math.ceil(h * z * zoom))))

        clips_json, ov_blocks = {}, []
        for d in data:
            c, tm = d["c"], d["tm"]
            cl = c["clip"]
            sx0, sy0, sw, sh = d["sbox"]
            ss_native = max(2, min(8, math.ceil(2 * zs)))
            cam_hi = with_box(d["scam"], sx0, sy0, sw, sh, float(ss_native))   # integer supersample of the DEF px grid
            cam_b = view_cam(bcam0, d["bbox_b"], zb)
            cam_p = view_cam(pcam0, d["bbox_p"], zp)
            rows = {"DEF": [], "sprite": [], "overlay": [], "battle": [], "preview": []}
            frames_json = []
            for i in range(tm["n"]):
                Pi, Ni = d["P"][i:i + 1], d["N"][i:i + 1]
                hi = self.render(cam_hi, Pi, Ni, ss=1)                      # (sh*ss, sw*ss)
                rmask = (torch.nn.functional.avg_pool2d(hi[..., 3][None, None], ss_native)[0, 0] >= 0.5).cpu().numpy()
                dcrop = d["defs"][i].crop(sx0, sy0, sw, sh)
                dmask = dcrop[..., 3] >= DEF_ALPHA_BODY
                hh = max(1, round(sh * zs))
                rows["DEF"].append(fit_h(def_pil(dcrop), hh, nearest=True))
                rows["sprite"].append(fit_h(to_pil(hi), hh))
                rows["overlay"].append(fit_h(overlay_pil(dmask, rmask), hh, nearest=True))
                rows["battle"].append(to_pil(self.render(cam_b, Pi, Ni, ss=2)))
                rows["preview"].append(to_pil(self.render(cam_p, Pi, Ni, ss=2)))
                ds, rs = mask_stats(dmask), mask_stats(rmask)
                fr = {"i": i, "t": round(tm["times"][i], 5), "png": Path(c["frames"][i]).name,
                      "iou": None if iou(dmask, rmask) is None else round(iou(dmask, rmask), 4),
                      "def": ds and {k: ds[k] for k in ("w", "h", "wh", "centroid")},
                      "render": rs and {k: rs[k] for k in ("w", "h", "wh", "centroid")}}
                if ds and rs:
                    fr["whRatioRenderOverDef"] = round(rs["wh"] / ds["wh"], 4)
                    dx, dy = rs["centroid"][0] - ds["centroid"][0], rs["centroid"][1] - ds["centroid"][1]
                    fr["centroidOffsetPx"] = [round(dx, 2), round(dy, 2)]
                    fr["centroidOffsetOverDefH"] = [round(dx / ds["h"], 4), round(dy / ds["h"], 4)]
                frames_json.append(fr)
            ious = [f["iou"] for f in frames_json if f["iou"] is not None]
            self.write_clip_board(cl, c, tm, rows, frames_json)
            self.write_gif(d, with_box(d["scam"], sx0, sy0, sw, sh, 1.0), zs, cam_b)
            clips_json[cl] = {"clipKey": c["clipKey"], "defGroup": c["defGroup"], "defFrames": tm["n"],
                              "start": round(tm["start"], 5), "end": round(tm["end"], 5),
                              "duration": round(tm["duration"], 5), "loop": tm["loop"],
                              "transitionKeys": tm["transitionKeys"], "step": round(tm["step"], 5),
                              "stepOver12fps": tm["stepOver12fps"],
                              "spriteMapping": "exact" if aligned else ("similarityFitIdleFrame0" if align_idle else "similarityFitFrame0"),
                              "spriteFit": fits[cl], "spriteBoxPx": list(d["sbox"]),
                              "meanIoU": round(float(np.mean(ious)), 4) if ious else None,
                              "minIoU": round(float(np.min(ious)), 4) if ious else None, "frames": frames_json}
            ov_blocks.append((cl, tm, rows))
            memtrace(f"boarded {cl}")
            del d["P"], d["N"]
        self.write_overview(ov_blocks)
        return {"sprite": {"mode": "exact" if aligned else ("similarityFitIdleFrame0" if align_idle else "similarityFitFrame0"), "note": sprite_note,
                           "spritecam": self.ref["spritecamPath"].relative_to(ROOT).as_posix(), "deyawDeg": deyaw,
                           "viewYawDeg": vy,
                           "referenceClip": ref_clip, "restFrameCheck": rest, "displayZoom": round(zs, 4),
                           "silhouetteMask": f"DEF alpha >= {DEF_ALPHA_BODY} (shadows excluded) vs render coverage >= 0.5 at DEF px"},
                "battle": {"mode": "exact (same camera rule as the unit-look lane)",
                           "note": "tools/homm3_prebake/render_passes.py battle_faces_right: orthographic, elevation "
                                   f"{BATTLE['elevDeg']} deg, azimuth {BATTLE['azimuthDeg']} deg from glTF +Z (camera on the "
                                   "unit's right-front); one box per clip", **BATTLE},
                "preview": {"mode": "approximate", "note": pv_note, **PREVIEW, "worldPerGlbUnit": round(k_world, 5),
                            "eyeGlb": [round(float(x), 4) for x in eye]}}, clips_json

    # -------------------------------------------------- outputs
    def write_clip_board(self, cl, c, tm, rows, frames_json):
        f_lbl, f_hdr, f_title = font(15), font(13), font(17)
        lab_w = 92
        n = tm["n"]
        col_w = [max(rows[r][i].width for r in rows) + 6 for i in range(n)]
        row_h = {r: max(im.height for im in rows[r]) + 6 for r in rows}
        title_h, hdr_h = 46, 22
        W = lab_w + sum(col_w)
        H = title_h + hdr_h + sum(row_h.values())
        img = Image.new("RGB", (max(W, 900), H), (248, 248, 248))
        dr = ImageDraw.Draw(img)
        ious = [f["iou"] for f in frames_json if f["iou"] is not None]
        dr.text((8, 4), f"{self.lab}  {cl}  ({c['clipKey']}, {n} DEF frames)  step {tm['step']*1000:.0f} ms "
                        f"(x{tm['stepOver12fps']} of 12 fps)  clip {tm['start']:.3f}-{tm['end']:.3f} s"
                        f"{'  loop+' + str(tm['transitionKeys']) + ' seam keys' if tm['loop'] else ''}", fill=(0, 0, 0), font=f_title)
        dr.text((8, 25), f"GLB {self.sel['mode']}: {Path(self.sel['path']).name} {self.sel['sha256'][:12]}   "
                         f"IoU DEF vs sprite: mean {np.mean(ious) if ious else float('nan'):.3f} min {min(ious) if ious else float('nan'):.3f}   "
                         "overlay: red DEF only, blue render only", fill=(60, 60, 60), font=f_hdr)
        x = lab_w
        for i in range(n):
            dr.text((x + 3, title_h + 3), f"f{i} t={tm['times'][i]:.3f}", fill=(0, 0, 0), font=f_hdr)
            x += col_w[i]
        y = title_h + hdr_h
        for r, ims in rows.items():
            dr.text((6, y + row_h[r] // 2 - 8), r, fill=(0, 0, 0), font=f_lbl)
            x = lab_w
            for i, im in enumerate(ims):
                img.paste(im, (x + 3 + (col_w[i] - 6 - im.width) // 2, y + 3))
                if r == "overlay" and frames_json[i]["iou"] is not None:
                    dr.text((x + 5, y + 5), f"{frames_json[i]['iou']:.2f}", fill=(0, 0, 0), font=f_hdr)
                x += col_w[i]
            dr.line([(0, y + row_h[r] - 1), (W, y + row_h[r] - 1)], fill=(225, 225, 225))
            y += row_h[r]
        x = lab_w
        for i in range(n):
            dr.line([(x, title_h), (x, H)], fill=(225, 225, 225))
            x += col_w[i]
        img.save(self.out / f"clip_{cl}.png", optimize=True)

    def write_gif(self, d, cam_native, zs, cam_b):
        """DEF | sprite | battle at game timing: GLB sampled every 1/GIF_FPS s, DEF frame floor((t - start) / step)."""
        tm = d["tm"]
        span = tm["duration"] if tm["loop"] else tm["duration"] + tm["step"]
        nt = max(1, int(round(span * GIF_FPS)))
        ts = [tm["start"] + k / GIF_FPS for k in range(nt)]
        zg = GIF_H / CELL_H
        cs = dict(cam_native, cx=cam_native["cx"] * zs * zg, cy=cam_native["cy"] * zs * zg, scale=cam_native["scale"] * zs * zg,
                  W=max(1, round(cam_native["W"] * zs * zg)), H=max(1, round(cam_native["H"] * zs * zg)))
        cb = dict(cam_b, cx=cam_b["cx"] * zg, cy=cam_b["cy"] * zg, scale=cam_b["scale"] * zg,
                  W=max(1, round(cam_b["W"] * zg)), H=max(1, round(cam_b["H"] * zg)))
        sx0, sy0, sw, sh = d["sbox"]
        dcache = {}
        frames = []
        f = font(12)
        for k0 in range(0, nt, 16):
            P, N = self.skin(d["c"]["clip"], np.clip(ts[k0:k0 + 16], tm["start"], tm["end"]))
            for j in range(P.shape[0]):
                t = ts[k0 + j]
                di = min(int(math.floor((t - tm["start"]) / tm["step"] + 1e-6)), tm["n"] - 1)
                if di not in dcache:
                    dcache[di] = def_pil(d["defs"][di].crop(sx0, sy0, sw, sh)).resize((cs["W"], cs["H"]), Image.NEAREST)
                sp = to_pil(self.render(cs, P[j:j + 1], N[j:j + 1], ss=2))
                bt = to_pil(self.render(cb, P[j:j + 1], N[j:j + 1], ss=2))
                Hh = max(cs["H"], cb["H"]) + 16
                fr = Image.new("RGB", (cs["W"] * 2 + cb["W"] + 8, Hh), (248, 248, 248))
                fr.paste(dcache[di], (0, 16)); fr.paste(sp, (cs["W"] + 4, 16)); fr.paste(bt, (2 * cs["W"] + 8, 16))
                dr = ImageDraw.Draw(fr)
                dr.text((2, 1), f"DEF f{di}", fill=(0, 0, 0), font=f)
                dr.text((cs["W"] + 6, 1), f"sprite t={t:.2f}", fill=(0, 0, 0), font=f)
                dr.text((2 * cs["W"] + 10, 1), "battle", fill=(0, 0, 0), font=f)
                frames.append(fr.quantize(colors=255, method=Image.Quantize.MEDIANCUT))
            del P, N
        frames[0].save(self.out / f"clip_{d['c']['clip']}.gif", save_all=True, append_images=frames[1:],
                       duration=int(round(1000 / GIF_FPS)), loop=0, disposal=1)
        # Panel boxes [x, y, w, h] for reel.py (before/after reels cut the panels back out of this GIF).
        (self.out / f"clip_{d['c']['clip']}.gif.json").write_text(json.dumps({
            "fps": GIF_FPS, "def": [0, 16, cs["W"], cs["H"]], "sprite": [cs["W"] + 4, 16, cs["W"], cs["H"]],
            "battle": [2 * cs["W"] + 8, 16, cb["W"], cb["H"]], "tm": {k: tm[k] for k in ("start", "duration", "loop", "n")}}))

    def write_overview(self, blocks):
        f_lbl, f_t = font(13), font(15)
        tiles = []
        for cl, tm, rows in blocks:
            n = tm["n"]
            K = min(n, 6)
            idx = sorted(set(int(round(x)) for x in np.linspace(0, n - 1, K)))
            names = ("DEF", "sprite", "battle", "preview")
            cells = {r: [fit_h(rows[r][i], OV_H, nearest=(r == "DEF")) for i in idx] for r in names}
            cw = [max(cells[r][j].width for r in names) + 4 for j in range(len(idx))]
            lab_w, th = 58, 36
            W = lab_w + sum(cw)
            H = th + len(names) * (OV_H + 4)
            t = Image.new("RGB", (W, H), (248, 248, 248))
            dr = ImageDraw.Draw(t)
            dr.text((4, 2), f"{cl}  ({n} fr, step {tm['step']*1000:.0f} ms)", fill=(0, 0, 0), font=f_t)
            x = lab_w
            for j, i in enumerate(idx):
                dr.text((x + 2, 20), f"f{i}", fill=(70, 70, 70), font=f_lbl)
                x += cw[j]
            for ri, r in enumerate(names):
                y = th + ri * (OV_H + 4)
                dr.text((3, y + OV_H // 2 - 7), r, fill=(0, 0, 0), font=f_lbl)
                x = lab_w
                for j, im in enumerate(cells[r]):
                    t.paste(im, (x + (cw[j] - im.width) // 2, y))
                    x += cw[j]
            tiles.append(t)
        cols = 2
        colw = [max((tiles[i].width for i in range(c, len(tiles), cols)), default=0) for c in range(cols)]
        rowsH = [max(tiles[i].height for i in range(r, min(r + cols, len(tiles)))) for r in range(0, len(tiles), cols)]
        head = 30
        img = Image.new("RGB", (sum(colw) + 12 * cols, head + sum(rowsH) + 8 * len(rowsH)), (235, 235, 235))
        dr = ImageDraw.Draw(img)
        dr.text((6, 6), f"{self.lab} authenticity overview  GLB {self.sel['mode']} {Path(self.sel['path']).name} "
                        f"{self.sel['sha256'][:12]}" + (f"  MISSING: {', '.join(m['clip'] for m in self.missing)}" if self.missing else ""),
                fill=(0, 0, 0), font=f_t)
        y = head
        for r0, rh in zip(range(0, len(tiles), cols), rowsH):
            x = 6
            for c in range(cols):
                if r0 + c < len(tiles):
                    img.paste(tiles[r0 + c], (x, y))
                x += colw[c] + 12
            y += rh + 8
        if img.width > 1600:
            img = img.resize((1600, round(img.height * 1600 / img.width)), Image.LANCZOS)
        img.save(self.out / "overview.png", optimize=True)


def memtrace(tag: str) -> None:
    """HOMM3_AUTH_MEMTRACE=1: print peak / current RSS at a stage (profiling aid)."""
    if os.environ.get("HOMM3_AUTH_MEMTRACE"):
        import psutil
        mi = psutil.Process().memory_info()
        print(f"MEM {tag}: peak {getattr(mi, 'peak_wset', 0) / 2**20:.0f} MB rss {mi.rss / 2**20:.0f} MB", flush=True)


def peak_rss_mb() -> float | None:
    try:
        import psutil
        mi = psutil.Process().memory_info()
        v = getattr(mi, "peak_wset", None)
        if v is None:
            import resource  # noqa: PLC0415
            return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1)
        return round(v / 2 ** 20, 1)
    except Exception:  # pragma: no cover
        return None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("unit")
    ap.add_argument("--glb", help="render this candidate GLB instead of the shipped one")
    ap.add_argument("--out", help="output dir (default V:/olden_port_work/authenticity/<unit>/boards)")
    ap.add_argument("--clips", help="comma list: Unit_Idle / Idle / g02_idle")
    ap.add_argument("--device", default="cuda", choices=("cuda", "cpu"))
    ap.add_argument("--view-yaw", type=float, help="turn the sprite camera about world up by this many degrees (pose-fit "
                    "view yaw, e.g. -40 for the griffin line): a DEF-view diagnostic, size normalised per clip")
    ap.add_argument("--align", default="clip", choices=("clip", "idle"),
                    help="when the SpriteCam does not describe the GLB (--view-yaw): fit the 2D similarity on each clip's "
                         "own frame 0 (clip, default) or use Idle frame 0's for every clip (idle: judges vertical placement "
                         "across clips, e.g. ground-stage entries and takeoffs)")
    a = ap.parse_args(argv)
    b = Board(a)
    cams, clips = b.run()
    sel = b.sel
    rec = {"schema": SCHEMA, "unit": a.unit, "labSid": b.lab, "sourceUnit": b.src,
           "createdAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
           "glb": {"mode": sel["mode"], "path": str(Path(sel["path"]).resolve()), "sha256": sel["sha256"],
                   "selection": sel.get("selection"), "candidates": sel.get("candidates"), "notes": sel["notes"],
                   "shippedForReference": sel.get("shippedForReference"), "bodyNode": b.scene.body_name,
                   "notRendered": b.scene.other_meshes},
           "albedo": b.albedo_note,
           "def": {"master": b.ref["master"].relative_to(ROOT).as_posix(),
                   "framesJson": b.ref["framesJson"] and b.ref["framesJson"].relative_to(ROOT).as_posix(),
                   "skippedGroups": b.ref["skipped"], "notes": b.ref["notes"]},
           "cameras": cams, "clips": clips, "missingClips": b.missing, "glbOnlyClips": b.glb_only,
           "device": a.device}
    rec["perf"] = {"wallSeconds": round(time.perf_counter() - b.t0, 2), "peakRssMB": peak_rss_mb(),
                   "peakVramAllocatedMB": round(torch.cuda.max_memory_allocated() / 2 ** 20, 1) if a.device == "cuda" else None,
                   "peakVramReservedMB": round(torch.cuda.max_memory_reserved() / 2 ** 20, 1) if a.device == "cuda" else None,
                   "vramNote": "torch allocator peak; the CUDA context itself adds ~0.3-0.5 GB outside it"}
    (b.out / "board.json").write_text(json.dumps(rec, indent=1), encoding="utf-8")
    summ = {k: v["meanIoU"] for k, v in clips.items()}
    print(f"BOARD {b.lab} -> {b.out}  wall {rec['perf']['wallSeconds']} s  peak RSS {rec['perf']['peakRssMB']} MB  "
          f"VRAM reserved {rec['perf']['peakVramReservedMB']} MB  sprite {cams['sprite']['mode']}  meanIoU {summ}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
