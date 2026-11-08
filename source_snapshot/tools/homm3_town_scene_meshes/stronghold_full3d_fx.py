"""Stronghold full-3D: the animated HoMM3 buildings as vanilla-style effects (no ripped flipbooks, no Meshy).

Every reachable layer whose HoMM3 DEF has more than one frame (layers/anims/metadata.json) gets Fx_ pieces in its own
prefab. The DEF is read only to MEASURE: frame 0 is the whole sprite, frames 1.. are the moving patches (their alpha
boxes are the animated rects), so where / how big / how fast come from the art:

  * extraCapitol_1..3  two fountains each. Basin water = the convex hull of the blue patch pixels on the basin's own
                       relief, pulled toward the camera (every vertex is a ray through a hull pixel, so the rest pose
                       covers exactly the painted water; a level plane was rejected, see fountain()) and drawn with the bundle's FlowWater (vanilla WaterNormal; rings run outward). Jet apex
                       = the highest white pixel of any frame, measured on the vertical through the basin centre. The
                       plume and the falling bell are VfxUber-replica particles under real gravity (apex h -> v0 =
                       sqrt(2 g h)); splash ring and mist on the water.
  * dwellingUp2Lvl6_2  a four-sailed windmill on the cave roof. Hub, radius, direction and speed are measured from the
                       frames (rotation fit frame k -> k+1: ~8.5 deg / 100 ms, counter-clockwise on screen). The sails
                       are cut from frame 0 against the per-pixel median of all frames (the median is the sail-free
                       background, which also replaces the sails in the building's static texture: static_plate) and
                       spun as an unlit Fx_ disc facing the camera.
  * dwellingUp2Lvl7_2  the blue lightning in the rock cleft: a camera-facing VfxUber particle whose mask is the union
                       of the DEF's bolt pixels, crackling through fast-scrolling vanilla noise, a blue glow flicker
                       and sparks.
Materials are the Conflux lane's VfxUber / FlowWater replicas with vanilla parameters; noise, glow and WaterNormal are
vanilla Olden Era textures (stronghold_full3d_vanilla, provenance.json). `spray` uses smoke_06 as its mask where the
Conflux recipe used glow_04 (not extracted here).
Proof tier: generated artifact; motion is only seen in editor renders / in game.
"""
from __future__ import annotations

import hashlib
import json
import math
import shutil

import cv2
import numpy as np
from PIL import Image

import stronghold_full3d_common as SC
import stronghold_full3d_terrain as T

ANIMS = SC.REFS / "layers" / "anims"
VFX_SRC = SC.DATA / "vanilla" / "vfx"
G_M = 9.81
UP = [-90.0, 0.0, 0.0]            # cone shapes emit along local +z; this turns them to world up
WIND_THR = 20                     # RGB step from the median background that counts as sail
FRONT_PULL_M = 0.6                # effects sit this far in front of the relief they belong to
WATER_PULL_M = 0.3                # the basin water sits this far in front of its basin's relief


# ------------------------------------------------------------------------------------------------ DEF reading
def frames(lid: str) -> list[np.ndarray]:
    meta = SC.anim_frames()[lid]
    return [np.asarray(Image.open(ANIMS / lid / f).convert("RGBA")) for f in meta["frames"]]


def patches(lid: str) -> list[tuple[int, int, int, int]]:
    """The DEF's animated rects (native sprite px x0, y0, x1, y1): alpha boxes of the moving patches in frames 1..."""
    from scipy import ndimage
    F = frames(lid)
    a = np.zeros(F[0].shape[:2], bool)
    for f in F[1:]:
        a |= f[..., 3] > 0
    lab, _ = ndimage.label(a)
    out = []
    for s in ndimage.find_objects(lab):
        if (s[0].stop - s[0].start) * (s[1].stop - s[1].start) > 50:
            out.append((s[1].start, s[0].start, s[1].stop, s[0].stop))
    if not out:
        raise SystemExit(f"fx: {lid}: no animated patch in its DEF")
    return sorted(out)


def static_plate(L: dict):
    """The sprite the relief is textured with: the windmill's sails replaced by the frames' median (they spin as Fx)."""
    spr = SC.sprite(L)
    if L["id"] != "dwellingUp2Lvl6_2":
        return spr
    x0, y0, x1, y1 = patches(L["id"])[0]
    F = np.stack([f[y0:y1, x0:x1, :3] for f in frames(L["id"])]).astype(np.float32)
    a = np.asarray(spr).copy()
    a[y0:y1, x0:x1, :3] = np.median(F, 0).round().astype(np.uint8)
    return Image.fromarray(a)


# ------------------------------------------------------------------------------------------------ geometry
class Place:
    """Native sprite px -> painting world on the layer's own relief depth."""

    def __init__(self, sc, L: dict, ld: dict):
        import stronghold_full3d_buildings as BL
        self.sc, self.L, self.cam = sc, L, sc.cam
        ok = np.isfinite(ld["z"])
        self.z = BL._fill_nearest(np.where(ok, ld["z"], 0.0), ok)

    def frame_px(self, sx, sy):
        return (self.L["x"] + np.asarray(sx, np.float64)) * SC.SCALE, (self.L["y"] + np.asarray(sy, np.float64)) * SC.SCALE

    def ray(self, sx, sy):
        fx, fy = self.frame_px(sx, sy)
        return T.rays(self.cam, fx, fy)

    def world(self, sx, sy, pull=0.0):
        xi = np.clip(np.asarray(sx, np.float64).astype(int), 0, self.z.shape[1] - 1)
        yi = np.clip(np.asarray(sy, np.float64).astype(int), 0, self.z.shape[0] - 1)
        z = self.z[yi, xi] - pull
        return self.cam["pos"] + self.ray(np.asarray(sx) + 0.5, np.asarray(sy) + 0.5) * np.asarray(z)[..., None]

    def world_smooth(self, sx, sy, pull=0.0):
        """world() with the depth sampled bilinearly (sx, sy: native px, pixel centres at +0.5)."""
        mx = (np.asarray(sx, np.float32) - 0.5).reshape(1, -1)
        my = (np.asarray(sy, np.float32) - 0.5).reshape(1, -1)
        z = cv2.remap(self.z.astype(np.float32), mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE).ravel()
        return self.cam["pos"] + self.ray(sx, sy) * (z.astype(np.float64) - pull)[:, None]

    def m_per_px(self, zc: float) -> float:
        """Painting metres per NATIVE HoMM3 px at forward depth zc."""
        return 2 * zc * math.tan(math.radians(self.cam["fov"]) / 2) / SC.H * SC.SCALE


def mat_to_quat(m: np.ndarray) -> list[float]:
    import build_town_scene3d_bundle as BB
    return [float(x) for x in BB.mat_to_quat(np.asarray(m, np.float64))]


# ------------------------------------------------------------------------------------------------ materials
class Mats:
    def __init__(self, stage, asset_root: str, shader_dir: str):
        self.stage, self.root, self.shader_dir = stage, asset_root, shader_dir
        self.sources: dict = {}

    def vtex(self, name: str) -> str:
        src = VFX_SRC / f"{name}.png"
        if not src.is_file():
            raise SystemExit(f"fx: vanilla texture missing: {src} (run stronghold_full3d_vanilla)")
        (self.stage / "vfx").mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, self.stage / "vfx" / src.name)
        self.sources[name] = hashlib.sha256(src.read_bytes()).hexdigest()
        return f"{self.root}/vfx/{src.name}"

    @staticmethod
    def tex(prop, path, st=(1, 1, 0, 0), clamp=False, srgb=True):
        st = list(st) + [0, 0] if len(st) == 2 else list(st)
        return {"prop": prop, "path": path, "st": [float(x) for x in st[:4]], "clamp": clamp, "srgb": srgb}

    def material(self, shader, textures=(), floats=None, colors=None, queue=0):
        return {"shader": f"{self.shader_dir}/{shader}.shader", "textures": list(textures),
                "floats": [{"name": k, "value": float(v)} for k, v in (floats or {}).items()],
                "colors": [{"name": k, "rgba": [float(x) for x in v]} for k, v in (colors or {}).items()], "queue": queue}

    def uber(self, noise1, noise2=None, mask=None, st1=(1, 1), st2=(1, 1), mn=0.0, mx=1.0, lerp=1.0, blend=1.0,
             color=(1.0, 1.0, 1.0, 1.0), speeds=(0, 0, 0, 0), mask_path=None):
        t = [self.tex("_Texture", self.vtex(noise1), st1, clamp=noise1.startswith(("glow", "smoke")))]
        if noise2:
            t.append(self.tex("_Texture2", self.vtex(noise2), st2))
        if mask or mask_path:
            t.append(self.tex("_Mask", mask_path or self.vtex(mask), clamp=True))
        col = [color] * 3 + [1.0] if isinstance(color, (int, float)) else list(color)
        return self.material("Homm3ConfluxVfxUber", t,
                             {"_Min": mn, "_Max": mx, "_Lerp": lerp, "_Multiply": 1.0, "_Blend": blend,
                              "_xSpeed01": speeds[0], "_ySpeed01": speeds[1], "_xSpeed02": speeds[2],
                              "_ySpeed02": speeds[3], "_UseTwo": 1.0 if noise2 else 0.0, "_CameraOffset": 0.0,
                              "_UseCamOffset": 0.0}, {"_Color": col})

    def standard(self) -> dict:
        return {
            # Conflux anim_mats "spray" (vanilla spray / mist recipe), smoke_06 as the soft mask.
            "spray": self.uber("TileNoise_07_vfx", None, "smoke_06_vfx", mn=0.0, mx=0.45, lerp=1.0, blend=0.75,
                               color=1.5, speeds=(0, -0.4, 0, 0)),
            # Glow_03_vfx.
            "glow": self.uber("glow_08_vfx", lerp=0.17, blend=0.2, color=5.99),
            # Paragon_glow_vfx points.
            "glint": self.uber("glow_10_vfx", lerp=1.0, blend=0.0, color=6.0),
        }


def psys(name: str, mat: dict, **kw) -> dict:
    d = {"name": name, "material": mat, "seed": int(hashlib.sha1(name.encode()).hexdigest()[:6], 16), "customUV": True,
         "maxParticles": 200, "shape": "sphere", "radius": 0.1}
    for k, v in kw.items():
        d[k] = [float(x) for x in v] if isinstance(v, (list, tuple)) else v
    return d


def _prefix() -> str:
    import stronghold_full3d_scene as S
    return S.PREFIX


def write_mesh(sc, prefab: str, name: str, v_local, n_local, uv, tris):
    import stronghold_full3d_scene as S
    S.write_bin(S.STAGE / prefab / f"{name}.bytes", v_local, n_local, uv, [tris])
    return f"{S.ASSET_ROOT}/{prefab}/{name}.bytes"


# ------------------------------------------------------------------------------------------------ fountains
def fountain(sc, M: Mats, A: dict, P: Place, lid: str, k: int, rect, F: list, spec_l, sky_c) -> tuple[dict, dict, dict]:
    prefab = _prefix() + lid
    x0, y0, x1, y1 = rect
    f0 = F[0][y0:y1, x0:x1].astype(np.int32)
    r_, g_, b_ = f0[..., 0], f0[..., 1], f0[..., 2]
    blue = (b_ > r_ + 20) & (b_ > 110) & (f0[..., 3] > 0)
    blue[: (y1 - y0) // 3] = False                      # water lies in the lower part of the patch
    ys, xs = np.nonzero(blue)
    if len(ys) < 30:
        raise SystemExit(f"fx: {lid} fountain {k}: {len(ys)} water px")
    hull = cv2.convexHull(np.stack([xs, ys], 1).astype(np.int32))
    wm = np.zeros(blue.shape, np.uint8)
    cv2.fillConvexPoly(wm, hull, 1)
    wm = wm.astype(bool) & (F[0][y0:y1, x0:x1, 3] > 0)
    wc = np.median(f0[blue][:, :3], 0) / 255.0
    # Water surface ON the basin's own relief, pulled WATER_PULL_M toward the camera. A level plane was measured and
    # rejected: the HoMM3 art draws the basin from a steeper view than the measured camera (about 12 deg above the
    # floor there), so a level plane through the painted ellipse stretches to 20-36 m deep. Every vertex is still a
    # ray through the hull, so the rest pose covers exactly the painted water.
    Pw = P.world(xs + x0, ys + y0)
    st = 0.5
    gx = np.arange(0, wm.shape[1] + st, st)
    gy = np.arange(0, wm.shape[0] + st, st)
    GX, GY = np.meshgrid(gx, gy)
    cx_, cy_ = (GX[:-1, :-1] + st / 2), (GY[:-1, :-1] + st / 2)
    inside = wm[np.clip(cy_.astype(int), 0, wm.shape[0] - 1), np.clip(cx_.astype(int), 0, wm.shape[1] - 1)]
    V = P.world_smooth(GX.ravel() + x0, GY.ravel() + y0, pull=WATER_PULL_M)
    nx = len(gx)
    iy, ix = np.nonzero(inside)
    a = iy * nx + ix
    tris = np.concatenate([np.stack([a, a + 1, a + nx], 1), np.stack([a + 1, a + nx + 1, a + nx], 1)])
    used = np.unique(tris)
    remap = -np.ones(len(V), int)
    remap[used] = np.arange(len(used))
    V, tris = V[used], remap[tris]
    sx_v, sy_v = (GX.ravel() + x0)[used], (GY.ravel() + y0)[used]
    cp = P.cam["pos"]
    to_cam = cp - V.mean(0)
    cr = np.cross(V[tris[:, 1]] - V[tris[:, 0]], V[tris[:, 2]] - V[tris[:, 0]])
    flip = cr @ to_cam < 0
    tris[flip] = tris[flip][:, [0, 2, 1]]
    # the painted ellipse in screen px (centre, half-axes), metres at the basin's depth for the flow/ripple scale
    hx, hy = xs + x0 + 0.5, ys + y0 + 0.5
    ecx, ecy = float((hx.min() + hx.max()) / 2), float((hy.min() + hy.max()) / 2)
    eax, eay = float((hx.max() - hx.min()) / 2 + 0.5), float((hy.max() - hy.min()) / 2 + 0.5)
    c = P.world_smooth(np.array([ecx]), np.array([ecy]), pull=WATER_PULL_M)[0]
    zc = float((c - cp) @ P.cam["fwd"])
    mpp = P.m_per_px(zc)
    ax = np.array([eax, eay]) * mpp
    en = np.stack([(sx_v - ecx) / eax, (sy_v - ecy) / eay], 1)
    rr = np.hypot(en[:, 0], en[:, 1])
    th = np.arctan2(en[:, 1], en[:, 0])
    Rm = float(ax.mean())
    uv0 = np.stack([0.5 + 0.5 * np.clip(en[:, 0], -1, 1), 0.5 + 0.5 * np.clip(en[:, 1], -1, 1)], 1)
    uv1 = np.stack([th * Rm, rr * Rm], 1)
    n_ = 128
    yy, xx = np.mgrid[0:n_, 0:n_]
    rad = np.hypot((xx + 0.5) / n_ * 2 - 1, (yy + 0.5) / n_ * 2 - 1)
    tint = np.zeros((n_, n_, 4), np.uint8)
    tint[..., :3] = (np.clip(wc, 0, 1) * 255).astype(np.uint8)
    tint[..., 3] = (np.clip(((1 - np.clip(rad, 0, 1)) * 20 + 2) / 22, 0, 1) * 255).astype(np.uint8)
    import stronghold_full3d_scene as S
    tint_p = S.STAGE / prefab / f"basin_tint_{k}.png"
    tint_p.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(tint).save(tint_p)
    common = [M.tex("_Noise", M.vtex("TileNoise_23_vfx")), M.tex("_Noise2", M.vtex("TileNoise_07_vfx")),
              M.tex("_NormalMap", M.vtex("WaterNormal"), srgb=False)]
    colors = {"_SpecDir": [float(spec_l[0]), float(spec_l[1]), float(spec_l[2]), 0.0],
              "_SkyColor": [float(sky_c[0]), float(sky_c[1]), float(sky_c[2]), 1.0]}
    mat = M.material("Homm3ConfluxFlowWater", [M.tex("_MainTex", f"{S.ASSET_ROOT}/{prefab}/basin_tint_{k}.png", clamp=True)]
                     + common,
                     {"_ShoreRange": 22, "_ShoreOut": 2, "_Deep": 0.5, "_DeepPx": 10, "_Foam": 0.45, "_FoamPx": 2.5,
                      "_Feather": 2, "_Speed": Rm * 0.35, "_Scale": 2.2 / Rm, "_Stretch": 0.35, "_Ripple": 0.45,
                      "_NormalScale": 3.0 / Rm, "_Glint": 0.5}, colors)
    name = f"Fx_Basin_{k}_{lid}"
    up = np.tile([0, 1.0, 0], (len(V), 1))
    mesh = write_mesh(sc, prefab, name, sc.local(V), sc.local_dir(up), uv0, tris)
    uv2p = S.STAGE / prefab / f"{name}_uv2.bytes"
    uv2p.write_bytes(np.asarray(uv1, np.float32).tobytes())
    basin = {"name": name, "mesh": mesh, "kind": "fxmesh", "material": mat, "pos": [0.0, 0.0, 0.0],
             "rot": [0.0, 0.0, 0.0, 1.0], "uv2": f"{S.ASSET_ROOT}/{prefab}/{name}_uv2.bytes"}
    # jet: highest white pixel of any frame, on the vertical through the basin centre
    white = np.zeros(blue.shape, bool)
    for f in F:
        p = f[y0:y1, x0:x1].astype(np.int32)
        white |= (p[..., :3].min(-1) > 175) & (p[..., 3] > 0)
    wy, wx = np.nonzero(white)
    if len(wy) < 10:
        raise SystemExit(f"fx: {lid} fountain {k}: no jet pixels")
    apex_y = float(np.percentile(wy, 1)) + y0
    jet_x = float(np.median(wx[wy < np.percentile(wy, 30)])) + x0
    ra = P.ray(jet_x + 0.5, apex_y + 0.5)
    ra = ra / np.linalg.norm(ra)
    # closest point on the vertical line {c + s*up} to the apex ray
    w0 = cp - c
    b = ra[1]
    d_, e_ = ra @ w0, w0[1]
    s = (e_ - b * d_) / max(1 - b * b, 1e-6)
    h = float(max(s, 0.5))
    v0 = math.sqrt(2 * G_M * h)
    zc = float((c - cp) @ P.cam["fwd"])
    mpp = P.m_per_px(zc)
    wj = 3.0 * mpp                        # jet thickness: ~3 HoMM3 px
    gmod = G_M * sc.scale / 9.81
    t_up = v0 / G_M
    systems = [
        # the central plume: a narrow cone of fast droplets reaching the painted apex and falling back
        psys(f"plume_{k}", A["spray"], lifetime=[2 * t_up * 0.9, 2 * t_up * 1.0], speed=[v0 * 0.93, v0 * 1.0],
             size=[wj * 0.8, wj * 1.6], rate=90, maxParticles=260, shape="cone", radius=wj * 0.3, angle=3,
             shapeRot=UP, gravity=gmod, renderMode=1, lengthScale=1.2, velocityScale=0.04,
             color=[0.93, 0.97, 1.0, 1.0], alphaKeys=[0, 0, 0.1, 1, 0.85, 0.9, 1, 0], sizeKeys=[0, 0.6, 1, 1.4],
             sortingFudge=-2),
        # the bell: water spilling outward from the crown into the basin
        psys(f"bell_{k}", A["spray"], lifetime=[1.6 * t_up, 1.9 * t_up], speed=[v0 * 0.62, v0 * 0.72],
             size=[wj * 1.0, wj * 1.8], rate=70, maxParticles=260, shape="cone", radius=wj * 0.4, angle=22,
             shapeRot=UP, gravity=gmod, rotation=[0, 360], color=[0.9, 0.95, 1.0, 0.9],
             alphaKeys=[0, 0, 0.15, 1, 0.8, 0.8, 1, 0], sizeKeys=[0, 0.5, 1, 1.5]),
        # splash ring where the bell lands, and mist over the basin
        psys(f"splash_{k}", A["spray"], lifetime=[0.4, 0.7], speed=[v0 * 0.08, v0 * 0.16], size=[wj * 1.5, wj * 2.6],
             rate=40, maxParticles=40, shape="circle", radius=Rm * 0.55, radiusThickness=0.3, shapeRot=[90.0, 0, 0],
             gravity=gmod, color=[0.94, 0.97, 1.0, 0.8], alphaKeys=[0, 0, 0.2, 1, 1, 0], rotation=[0, 360]),
        psys(f"mist_{k}", A["spray"], lifetime=[2.0, 3.0], speed=[0], velY=[h * 0.05, h * 0.12],
             size=[h * 0.35, h * 0.6], rate=3, maxParticles=10, radius=Rm * 0.5, radiusThickness=1,
             shapeScale=[1, 0.2, 1], pos=[0, h * 0.4, 0], color=[0.9, 0.95, 1.0, 0.16],
             alphaKeys=[0, 0, 0.3, 1, 0.7, 0.8, 1, 0], sizeKeys=[0, 0.7, 1, 1.3], rotation=[0, 360], rotSpeed=[-10, 10]),
    ]
    group = {"name": f"Fx_FountainSpray_{k}_{lid}", "pos": [float(x) for x in sc.local(c[None, :])[0]],
             "rot": mat_to_quat(sc.C.T), "scale": float(sc.scale), "systems": systems}
    # the basin water check: plane depth vs the relief depth at the water pixels
    zr = (Pw - cp) @ P.cam["fwd"]
    zw = (P.world_smooth(xs + x0 + 0.5, ys + y0 + 0.5, pull=WATER_PULL_M) - cp) @ P.cam["fwd"]
    rep = {"rect": list(rect), "waterPx": int(len(ys)), "waterColourSrgb": [round(float(x), 3) for x in wc],
           "basinCentreM": [round(float(x), 2) for x in c], "basinHalfAxesPx": [round(eax, 1), round(eay, 1)],
           "basinHalfAxesScreenM": [round(float(x), 3) for x in ax],
           "waterInFrontOfReliefShare": round(float((zw <= zr - 0.5 * WATER_PULL_M).mean()), 3),
           "jetApexM": round(h, 3), "jetApexPx": [round(jet_x, 1), round(apex_y, 1)], "v0MperS": round(v0, 2),
           "basinTris": int(len(tris))}
    return basin, group, rep


# ------------------------------------------------------------------------------------------------ windmill
def windmill(sc, P: Place, lid: str, rect, F: list, meas: dict | None = None, frame_ms: float | None = None,
             off=(0, 0)) -> tuple[dict, dict]:
    """A spinning disc on rect (DEF px). Without `meas` the hub, radius, sail mask and per-frame steps are measured here
    (the Stronghold sail-vs-median fit) and the frame time is read by layer id: that path is Stronghold's and unchanged.
    A caller with its own measurement (town_full3d_fx.fit_spin: {"cx", "cy", "rad", "sail", "steps", "fit"}, rect-local
    px) passes it with the DEF's own frame time `frame_ms` and the DEF-in-sprite offset `off` (sprite px = DEF px -
    off), so a crosswalked DEF is timed and placed by its own row."""
    import stronghold_full3d_scene as S
    prefab = _prefix() + lid
    x0, y0, x1, y1 = rect
    if meas is None:
        Fs = np.stack([f[y0:y1, x0:x1, :3] for f in F]).astype(np.float32)
        bg = np.median(Fs, 0)
        sd = Fs.std(0).mean(-1)
        ys, xs = np.nonzero(sd > 12)
        w = sd[sd > 12]
        cx, cy = float(np.average(xs, weights=w)), float(np.average(ys, weights=w))
        rad = float(np.percentile(np.hypot(xs - cx, ys - cy), 99)) + 1.0
        sail = np.abs(Fs[0] - bg).max(-1) > WIND_THR
        sail = cv2.morphologyEx(sail.astype(np.uint8), cv2.MORPH_CLOSE, np.ones((2, 2), np.uint8)).astype(bool)
        # rotation per frame (screen degrees, + = counter-clockwise) from the frame k -> k+1 fits
        steps = []
        for k in range(len(F) - 1):
            a0 = (np.abs(Fs[k] - bg).max(-1) > WIND_THR).astype(np.float32)
            a1 = (np.abs(Fs[k + 1] - bg).max(-1) > WIND_THR).astype(np.float32)
            best = max((float((cv2.warpAffine(a0, cv2.getRotationMatrix2D((cx, cy), ang, 1), a0.shape[::-1]) * a1).sum()),
                        ang) for ang in np.arange(-45, 45.25, 0.5))
            steps.append(best[1])
    else:
        cx, cy, rad, sail, steps = (float(meas["cx"]), float(meas["cy"]), float(meas["rad"]),
                                    np.asarray(meas["sail"], bool), list(meas["steps"]))
    step = float(np.median(steps))
    frame_s = (SC.anim_frames()[lid]["frameRateMs"] if frame_ms is None else frame_ms) / 1000.0
    period = abs(360.0 / step * frame_s)
    # sail texture: square around the hub, alpha = sail mask (soft edge), colour = frame 0
    n = 2 * int(math.ceil(rad)) + 2
    up = 8
    tex = np.zeros((n * up, n * up, 4), np.uint8)
    ox, oy = cx - n / 2, cy - n / 2
    M = np.float32([[1, 0, -ox], [0, 1, -oy]]) * np.float32([[up], [up]])
    rgb = cv2.warpAffine(F[0][y0:y1, x0:x1, :3], M, (n * up, n * up), flags=cv2.INTER_CUBIC)
    al = cv2.warpAffine(sail.astype(np.float32), M, (n * up, n * up), flags=cv2.INTER_LINEAR)
    al = cv2.GaussianBlur(al, (0, 0), up * 0.4)
    yy, xx = np.mgrid[0:n * up, 0:n * up]
    inside = np.hypot((xx + 0.5) / up - n / 2, (yy + 0.5) / up - n / 2) <= rad
    tex[..., :3] = rgb
    tex[..., 3] = (np.clip((al - 0.25) / 0.5, 0, 1) * inside * 255).astype(np.uint8)
    name = f"Fx_WindmillSails_{lid}"
    tp = S.STAGE / prefab / f"{name}_albedo.png"
    tp.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(tex).save(tp)
    # disc: holder at the hub, local Y along the view ray. Unity (left-handed): a positive spin about an axis pointing
    # AWAY from the camera reads counter-clockwise on screen (as a 2D sprite's +z rotation does).
    hub = P.world(np.array([cx + x0 - off[0]]), np.array([cy + y0 - off[1]]), pull=FRONT_PULL_M)[0]
    hub_l = sc.local(hub[None, :])[0]
    view = hub_l / np.linalg.norm(hub_l)            # camera -> hub, prefab frame (camera at the origin)
    Y = view if step > 0 else -view
    Xa = np.array([1.0, 0, 0]) - Y * Y[0]
    Xa /= np.linalg.norm(Xa)
    Z = np.cross(Xa, Y)                              # right-handed basis for the quaternion (det +1)
    R = np.stack([Xa, Y, Z], 1)
    zc = float((hub - P.cam["pos"]) @ P.cam["fwd"])
    r_units = rad * P.m_per_px(zc) * sc.scale
    seg = 48
    ang = np.linspace(0, 2 * np.pi, seg, endpoint=False)
    # holder-local disc in the x/z plane; texture u along screen right (+x), v along screen up
    zs_up = np.sign(Z @ np.array([0, 1.0, 0])) or 1.0
    Vl = np.concatenate([[[0, 0, 0]], np.stack([np.cos(ang), np.zeros(seg), np.sin(ang) * zs_up], 1) * r_units])
    uv = np.concatenate([[[0.5, 0.5]], np.stack([0.5 + 0.5 * np.cos(ang), 0.5 + 0.5 * np.sin(ang)], 1)])
    tris = np.array([[0, 1 + i, 1 + (i + 1) % seg] for i in range(seg)])
    toward_cam_local = R.T @ (-view)
    cr = np.cross(Vl[tris[:, 1]] - Vl[tris[:, 0]], Vl[tris[:, 2]] - Vl[tris[:, 0]])
    flip = cr @ toward_cam_local < 0
    tris[flip] = tris[flip][:, [0, 2, 1]]
    nrm = np.tile(toward_cam_local, (len(Vl), 1))
    S.write_bin(S.STAGE / prefab / f"{name}.bytes", Vl, nrm, uv, [tris])
    row = {"name": name, "mesh": f"{S.ASSET_ROOT}/{prefab}/{name}.bytes",
           "texture": f"{S.ASSET_ROOT}/{prefab}/{name}_albedo.png", "kind": "fx", "maxSize": 512,
           "pos": [float(x) for x in hub_l], "rot": mat_to_quat(R), "spinPeriod": round(period, 3)}
    rep = {"rect": list(rect), "hubPx": [round(cx + x0, 1), round(cy + y0, 1)], "radiusPx": round(rad, 1),
           "stepDegPerFrame": steps, "stepMedianDeg": step, "screenSense": "ccw" if step > 0 else "cw",
           "periodSec": round(period, 3), "radiusUnits": round(r_units, 4), "sailPx": int(sail.sum())}
    if meas is not None:
        rep.update({"fit": meas.get("fit"), "frameMs": frame_ms, "defOffset": [int(off[0]), int(off[1])]})
    return row, rep


# ------------------------------------------------------------------------------------------------ lightning
def lightning(sc, M: Mats, A: dict, P: Place, lid: str, rect, F: list) -> tuple[dict, dict]:
    import stronghold_full3d_scene as S
    prefab = _prefix() + lid
    x0, y0, x1, y1 = rect
    bolt = np.zeros((y1 - y0, x1 - x0), np.float32)
    for f in F:
        p = f[y0:y1, x0:x1].astype(np.int32)
        b = (p[..., 2] > 170) & (p[..., 2] > p[..., 0] + 30) & (p[..., 3] > 0)
        core = (p[..., :3].min(-1) > 200) & (p[..., 3] > 0)
        bolt += (b | core)
    bolt /= len(F)
    ys, xs = np.nonzero(bolt > 0)
    if len(ys) < 40:
        raise SystemExit(f"fx: {lid}: {len(ys)} bolt px")
    cx, cy = (x1 - x0) / 2, (y1 - y0) / 2
    n = max(x1 - x0, y1 - y0)
    up = 4
    m = np.zeros((n * up, n * up), np.float32)
    ox, oy = (n - (x1 - x0)) / 2, (n - (y1 - y0)) / 2
    big = cv2.resize(np.clip(bolt * 1.6, 0, 1), ((x1 - x0) * up, (y1 - y0) * up), interpolation=cv2.INTER_LINEAR)
    m[int(oy * up):int(oy * up) + big.shape[0], int(ox * up):int(ox * up) + big.shape[1]] = big
    m = cv2.GaussianBlur(m, (0, 0), up * 0.5)
    mp = S.STAGE / prefab / "bolt_mask.png"
    mp.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray((np.clip(m / max(m.max(), 1e-6), 0, 1) * 255).astype(np.uint8)).save(mp)
    ctr = P.world(np.array([cx + x0]), np.array([cy + y0]), pull=FRONT_PULL_M)[0]
    zc = float((ctr - P.cam["pos"]) @ P.cam["fwd"])
    size = n * P.m_per_px(zc)
    bolt_mat = M.uber("TileNoise_19_vfx", "TileNoise_23_vfx", mask_path=f"{S.ASSET_ROOT}/{prefab}/bolt_mask.png",
                      st1=(2, 1), st2=(1, 2), mn=0.05, mx=0.35, lerp=1.0, blend=0.3,
                      color=(0.55, 0.85, 1.6, 1.0), speeds=(1.7, 0.3, -1.3, 0.9))
    systems = [
        psys("bolt", bolt_mat, lifetime=[0.12, 0.3], speed=[0], size=[size, size], rate=9, maxParticles=3,
             radius=0.001, color=[1, 1, 1, 1], alphaKeys=[0, 0, 0.1, 1, 0.7, 1, 1, 0]),
        psys("glow", A["glow"], lifetime=[0.15, 0.4], speed=[0], size=[size * 0.9, size * 1.2], rate=7, maxParticles=5,
             radius=size * 0.05, color=[0.45, 0.75, 1.0, 0.35], alphaKeys=[0, 0, 0.2, 1, 0.6, 0.7, 1, 0],
             customUV=False),
        psys("sparks", A["glint"], lifetime=[0.1, 0.25], speed=[0], size=[size * 0.03, size * 0.07], rate=18,
             maxParticles=12, shape="box", shapeScale=[size * 0.7, size * 0.5, 0.2], color=[0.75, 0.9, 1.0, 1.0],
             alphaKeys=[0, 0, 0.3, 1, 1, 0], sizeKeys=[0, 0, 0.35, 1, 1, 0], customUV=False),
    ]
    # billboards need no orientation; the box shape is laid out in the camera frame (identity in the prefab frame)
    group = {"name": f"Fx_Lightning_{lid}", "pos": [float(x) for x in sc.local(ctr[None, :])[0]], "rot": [0.0, 0.0, 0.0, 1.0],
             "scale": float(sc.scale), "systems": systems}
    rep = {"rect": list(rect), "boltPx": int(len(ys)), "sizeM": round(size, 3), "centreDepthM": round(zc, 2)}
    return group, rep


# ------------------------------------------------------------------------------------------------ stage
MOVES = {
    "extraCapitol": "two fountains: a tall white plume from each vase falling back as a bell into its blue basin",
    "dwellingUp2Lvl6_2": "the four-sailed windmill on the cave roof turns (counter-clockwise, ~8.5 deg per frame)",
    "dwellingUp2Lvl7_2": "blue lightning crackles in the cleft between the rock spires",
}


def stage(sc, rd: dict, spec_l, sky_c) -> dict:
    """Fx_ rows per animated reachable layer; returns {"rows": {prefab: {bins, particles}}, "audit", "report"}."""
    import stronghold_full3d_buildings as BL
    import stronghold_full3d_scene as S
    M = Mats(S.STAGE, S.ASSET_ROOT, S.SHADER_DIR)
    A = M.standard()
    lays = SC.layers()
    meta = SC.anim_frames()
    rows, audit, rep = {}, {}, {}
    for lid in SC.reachable_layers():
        nf = len(meta.get(lid, {}).get("frames") or [])
        if nf <= 1:
            continue
        L = lays[lid]
        P = Place(sc, L, BL.layer_depth(lid, L, rd))
        F = frames(lid)
        rects = patches(lid)
        prefab = _prefix() + lid
        bins, groups, r = [], [], {}
        if lid.startswith("extraCapitol"):
            for k, rect in enumerate(rects):
                b, g, rr = fountain(sc, M, A, P, lid, k, rect, F, spec_l, sky_c)
                bins.append(b)
                groups.append(g)
                r[f"fountain_{k}"] = rr
            moves = MOVES["extraCapitol"]
        elif lid == "dwellingUp2Lvl6_2":
            b, r["windmill"] = windmill(sc, P, lid, rects[0], F)
            bins.append(b)
            moves = MOVES[lid]
        elif lid == "dwellingUp2Lvl7_2":
            g, r["lightning"] = lightning(sc, M, A, P, lid, rects[0], F)
            groups.append(g)
            moves = MOVES[lid]
        else:
            raise SystemExit(f"fx: {lid}: animated DEF ({nf} frames) without an effect recipe")
        rows[prefab] = {"bins": bins, "particles": groups}
        audit[lid] = {"defFrames": nf, "moves": moves, "effects": [b["name"] for b in bins] + [g["name"] for g in groups],
                      "defRects": [list(x) for x in rects], "frameRateMs": meta[lid]["frameRateMs"]}
        rep[lid] = r
        print("fx", lid, json.dumps(r)[:600], flush=True)
    return {"rows": rows, "audit": audit, "report": rep, "vanillaTextures": M.sources}
