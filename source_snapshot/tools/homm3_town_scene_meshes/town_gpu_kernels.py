"""Full-3D towns: GPU kernels for the zero-streak certificate's per-pose analysis (torch CUDA + one moderngl context).

    import town_gpu_kernels as GK
    eng = GK.CertifyEngine(sc, P, UV, F, owner, names, texs, reveal_tol)   # geometry uploaded once
    z, fid = eng.raster(cam)                                               # == town_full3d_t2_paint.zbuffer(cam, P, F, sup=1)
    row, hits, masks = eng.pose(cam, min_area, want_masks=False)           # == town_full3d_zero_streak's CPU pose row

The CPU code in town_full3d_zero_streak.certify (device "cpu") is the reference. This path must reproduce it exactly:
every integer px count, component count, class / bin attribution and pass/fail (tests/test_town_gpu_kernels.py, wired
next to the town tests, compares the two on a real staged scene). docs/town_gpu_kernels.md.

What runs where (profile 2026-10-01, castle zs_v5 "full", 3.0 M faces, 1920x1080: about 2 s/pose on the CPU):
  GPU (torch, float64)  per-px reprojection into the rest frame (world_points + T.project + the reveal test), the
                        ground-ray floor test, the per-face texel Jacobian and its 2x2 singular values (closed form),
                        the drawn-face set (bincount, not np.unique's hash), streak / reveal / extension masks and the
                        per-bin px counts.
  GPU (moderngl)        one standalone context per engine: the vertex / index buffers are uploaded once and every pose
                        renders into the same framebuffer (the reference creates a context and uploads ~70 MB per pose).
  CPU                   scipy.ndimage.label of the behind mask and of the undrawn mask (~6 ms each; the components
                        are a sequential union-find, a GPU port would buy nothing), and the sparse per-component work.
Exactness. Float64 elementwise ops are correctly rounded on both devices, but the reference's `@` products go through
BLAS (FMA, its own summation order), so a GPU value may differ from the CPU one in the last ulp. Every discrete
decision is therefore taken with a margin: a px or face whose deciding value lies within EPS_REL of a threshold (or
is not finite) is re-decided by the reference formula on the CPU for that px / face only. The number re-decided is
kept in `CertifyEngine.redecided` (diagnostic; normally 0 or a handful per pose). There is no device fallback: a
missing CUDA device raises.
"""
from __future__ import annotations

import math
import os
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import stronghold_full3d_common as SC  # noqa: E402
import stronghold_full3d_terrain as T  # noqa: E402
import town_full3d_t2_paint as TP  # noqa: E402
import town_t2_streak_map as SM  # noqa: E402

W, H = SC.W, SC.H
EPS_REL = 1e-9          # margin around every threshold inside which the CPU reference re-decides
VRAM_CAP_GB = float(os.environ.get("TOWN_GPU_VRAM_CAP_GB", "8"))   # other agents share the 16 GB card


DEVICES = ("cpu", "cuda")


def resolve_device(device: str | None) -> str:
    """device, else TOWN_FULL3D_DEVICE, else cuda (the town lane's GPU default; cpu is each kernel's reference)."""
    d = device or os.environ.get("TOWN_FULL3D_DEVICE", "").strip() or "cuda"
    if d not in DEVICES:
        raise SystemExit(f"town_gpu_kernels: device {d!r} is not one of {DEVICES}")
    return d


def require_cuda():
    """torch with a CUDA device, capped at VRAM_CAP_GB. Raises (never falls back to the CPU)."""
    try:
        import torch
    except ImportError as e:  # pragma: no cover
        raise SystemExit(f"town_gpu_kernels: device 'cuda' needs torch ({e}); pass --device cpu for the reference") from e
    if not torch.cuda.is_available():
        raise SystemExit("town_gpu_kernels: device 'cuda' requested but torch sees no CUDA device "
                         "(pass --device cpu / TOWN_FULL3D_DEVICE=cpu for the CPU reference)")
    total = torch.cuda.get_device_properties(0).total_memory
    torch.cuda.set_per_process_memory_fraction(min(1.0, VRAM_CAP_GB * 2**30 / total), 0)
    return torch


class Raster:
    """TP.zbuffer (sup=1, CLIP_NEAR) from one context: same shader, same matrices, byte-identical output. The geometry
    is uploaded once (load() swaps it, e.g. per building layer) and every pose renders into the same framebuffer. The
    colour target holds the two channels the reference reads (z, primitive id) as RG32F, half the reference's readback."""

    def __init__(self, P: np.ndarray | None = None, F: np.ndarray | None = None, clip=TP.CLIP_NEAR):
        import moderngl
        import stronghold_full3d_preview as PV
        self._PV = PV
        self._moderngl = moderngl
        self.near, self.far = TP._planes(clip)
        self.ctx = moderngl.create_standalone_context()
        ctx = self.ctx
        self.prog = ctx.program(vertex_shader="""
#version 330
uniform mat4 mvp; uniform vec3 cpos; uniform vec3 cfwd;
in vec3 in_pos; out float zc;
void main(){ gl_Position = mvp * vec4(in_pos, 1.0); zc = dot(in_pos - cpos, cfwd); }""",
                                fragment_shader="""
#version 330
in float zc; out vec4 o; void main(){ o = vec4(zc, float(gl_PrimitiveID), 0, 1); }""")
        self.fbo = ctx.framebuffer(color_attachments=[ctx.texture((W, H), 2, dtype="f4")],
                                   depth_attachment=ctx.depth_texture((W, H)))
        self.vao = self._vbo = self._ibo = None
        if P is not None:
            self.load(P, F)

    def load(self, P: np.ndarray, F: np.ndarray) -> None:
        """Upload (replace) the geometry: world-space vertices P and triangles F."""
        with self.ctx:
            for o in (self.vao, self._vbo, self._ibo):
                if o is not None:
                    o.release()
            self._vbo = self.ctx.buffer(np.asarray(P, np.float32).tobytes())
            self._ibo = self.ctx.buffer(np.asarray(F, np.int32).tobytes())
            self.vao = self.ctx.vertex_array(self.prog, [(self._vbo, "3f", "in_pos")], self._ibo)

    def render(self, cam: dict, fid: bool = True):
        """(z, fid) as TP.zbuffer(cam, P, F, sup=1) returns them; fid=False skips the face ids (returns z, None)."""
        PV = self._PV
        mvp = PV.perspective(cam["fov"], W / H, self.near, self.far) @ PV.view(cam["pos"], cam["fwd"], cam["up"],
                                                                             cam["right"])
        # another standalone context (TP.zbuffer between two renders) leaves this one not current: re-bind every time
        with self.ctx:
            self.fbo.use()
            self.ctx.clear(1e9, 0, 0, 0)
            self.ctx.enable(self._moderngl.DEPTH_TEST)
            self.prog["mvp"].write(mvp.T.astype(np.float32).tobytes())
            self.prog["cpos"].value = tuple(float(x) for x in cam["pos"])
            self.prog["cfwd"].value = tuple(float(x) for x in cam["fwd"])
            self.vao.render()
            raw = self.fbo.color_attachments[0].read()
        buf = np.frombuffer(raw, np.float32).reshape(H, W, 2)[::-1]
        z = buf[..., 0].copy()
        empty = z > 1e8
        z[empty] = np.inf
        if not fid:
            return z, None
        f = np.round(buf[..., 1]).astype(np.int64)
        f[empty] = -1
        return z, f

    def release(self):
        self.ctx.release()


def _near(v, thr, torch):
    """|v - thr| within EPS_REL of the scale, or v not finite."""
    return ~torch.isfinite(v) | ((v - thr).abs() <= EPS_REL * torch.clamp(v.abs(), min=1.0))


def _near_int(v, torch):
    """v within EPS_REL of an integer (a truncation / bound decision), or not finite."""
    return ~torch.isfinite(v) | ((v - torch.round(v)).abs() <= EPS_REL * torch.clamp(v.abs(), min=1.0))


def _world_points_px(cam, z, ys, xs):
    """ZS.world_points evaluated at the px (ys, xs) only, same element formula (numpy, the reference)."""
    t = math.tan(math.radians(cam["fov"]) / 2)
    xn = ((xs + 0.5) / W * 2 - 1) * t * W / H
    yn = (1 - (ys + 0.5) / H * 2) * t
    d = (cam["fwd"][None] + xn[..., None] * cam["right"][None] + yn[..., None] * cam["up"][None])
    return cam["pos"][None] + d * np.where(np.isfinite(z), z, 0)[..., None]


# ------------------------------------------------------------------------------------------------ shared helpers
# For other lanes' continuous measurements (mv3 stretch / warp causes, texel fusion weights): float64 on the GPU,
# equal to the numpy formulas within a few ulps (no exactness margin: callers that threshold must keep their own).
def singular_values_2x2(J, device: str = "cuda"):
    """(s1 >= s2) of a batch of 2x2 matrices (..., 2, 2), closed form, as numpy float64. np.linalg.svd(J,
    compute_uv=False) to ~1e-15 relative (s2 of a near-singular J to ~1e-15 * s1 absolute)."""
    torch = require_cuda() if device == "cuda" else None
    if torch is None:
        raise SystemExit(f"town_gpu_kernels.singular_values_2x2: device {device!r}; use np.linalg.svd for the CPU")
    t = torch.as_tensor(np.asarray(J, np.float64), device="cuda")
    a, b, c, d = t[..., 0, 0], t[..., 0, 1], t[..., 1, 0], t[..., 1, 1]
    E, Fq, G, Hq = (a + d) / 2, (a - d) / 2, (c + b) / 2, (c - b) / 2
    Q, R = torch.sqrt(E * E + Hq * Hq), torch.sqrt(Fq * Fq + G * G)
    return (Q + R).cpu().numpy(), (Q - R).abs().cpu().numpy()


def project_points(cam: dict, p, device: str = "cuda"):
    """T.project(cam, p) on the GPU for a large point set (..., 3): (px, py, zc) as numpy float64."""
    torch = require_cuda() if device == "cuda" else None
    if torch is None:
        raise SystemExit(f"town_gpu_kernels.project_points: device {device!r}; use T.project for the CPU")
    q = torch.as_tensor(np.asarray(p, np.float64), device="cuda")
    v = lambda k: torch.as_tensor(np.asarray(cam[k], np.float64), device="cuda")
    d = q - v("pos")
    dot = lambda u: d[..., 0] * u[0] + d[..., 1] * u[1] + d[..., 2] * u[2]
    zc = dot(v("fwd"))
    t = math.tan(math.radians(cam["fov"]) / 2)
    px = (dot(v("right")) / (zc * t * W / H) + 1) * 0.5 * W
    py = (1 - dot(v("up")) / (zc * t)) * 0.5 * H
    return px.cpu().numpy(), py.cpu().numpy(), zc.cpu().numpy()

class CertifyEngine:
    def __init__(self, sc, P, UV, F, owner, names, texs, reveal_tol: float, sky=None):
        torch = require_cuda()
        self.torch = torch
        self.dev = torch.device("cuda", 0)
        self.sc, self.reveal_tol = sc, float(reveal_tol)
        self.P, self.UV, self.F, self.owner, self.texs = P, UV, F, owner, texs        # CPU copies: re-decisions
        self.names = names
        self.nF, self.nB = len(F), len(names)
        f64 = dict(dtype=torch.float64, device=self.dev)
        self.tP = torch.as_tensor(np.asarray(P, np.float64), **f64)
        self.tUV = torch.as_tensor(np.asarray(UV, np.float64), **f64)
        self.tF = torch.as_tensor(np.asarray(F, np.int64), device=self.dev)
        self.tOwner = torch.as_tensor(np.asarray(owner, np.int64), device=self.dev)
        self.tTex = torch.as_tensor(np.asarray(texs, np.float64), **f64)
        self.raster_ = Raster(P, F)
        self.z0_np, fid_rest = self.raster_.render(sc.cam)
        self.fid_rest_np = fid_rest
        self.tFidRest = torch.as_tensor(fid_rest, device=self.dev)
        import town_full3d_zero_streak as ZS
        em = ZS.env_frame_faces(names, owner, F)                 # the background frame (ZS.ground_split)
        if sky is not None and not em.any():
            raise SystemExit("zero-streak: the restSky refinement needs the background frame: no environment/ bin")
        self.fid_env_np = None
        if em.any():
            r_env = Raster(P, np.asarray(F)[em])
            try:
                self.fid_env_np = r_env.render(sc.cam)[1]
            finally:
                r_env.release()
        self.tFidEnv = None if self.fid_env_np is None else torch.as_tensor(self.fid_env_np, device=self.dev)
        self.sky_r = Raster(sky[0], sky[1]) if sky is not None else None          # restSky: the static Sky_ bins
        self.rest_cnt = np.bincount(fid_rest[fid_rest >= 0], minlength=self.nF)
        self.tRestCnt = torch.as_tensor(self.rest_cnt, device=self.dev)
        self.tz0 = torch.as_tensor(self.z0_np, device=self.dev)                   # float32, inf where empty
        ys, xs = np.mgrid[0:H, 0:W]
        self.ys = torch.as_tensor(ys, dtype=torch.float64, device=self.dev)       # exact ints, as numpy promotes them
        self.xs = torch.as_tensor(xs, dtype=torch.float64, device=self.dev)
        self.floor = T.Floor(sc.cam)
        self.redecided = {"faces": 0, "revealPx": 0, "groundPx": 0, "groundSplitPx": 0}

    def raster(self, cam):
        return self.raster_.render(cam)

    def release(self):
        self.raster_.release()
        if self.sky_r is not None:
            self.sky_r.release()
        torch = self.torch
        for k in ("tP", "tUV", "tF", "tOwner", "tTex", "tz0", "ys", "xs", "tFidRest", "tFidEnv"):
            setattr(self, k, None)
        torch.cuda.empty_cache()

    # ---------------------------------------------------------------------------------------------- primitives
    def _v3(self, a):
        return self.torch.as_tensor(np.asarray(a, np.float64), dtype=self.torch.float64, device=self.dev)

    def _dot3(self, d, v):
        return d[..., 0] * float(v[0]) + d[..., 1] * float(v[1]) + d[..., 2] * float(v[2])

    def _project(self, cam, p):
        """T.project on the GPU (dot products in a fixed order: within ulps of the BLAS reference)."""
        d = p - self._v3(cam["pos"])
        zc = self._dot3(d, cam["fwd"])
        t = math.tan(math.radians(cam["fov"]) / 2)
        px = (self._dot3(d, cam["right"]) / (zc * t * W / H) + 1) * 0.5 * W
        py = (1 - self._dot3(d, cam["up"]) / (zc * t)) * 0.5 * H
        return px, py, zc

    def _world_points(self, cam, zz):
        """ZS.world_points (zz: the depth with non-finite already zeroed, any float dtype)."""
        t = math.tan(math.radians(cam["fov"]) / 2)
        xn = ((self.xs + 0.5) / W * 2 - 1) * t * W / H
        yn = (1 - (self.ys + 0.5) / H * 2) * t
        d = self._v3(cam["fwd"]) + xn[..., None] * self._v3(cam["right"]) + yn[..., None] * self._v3(cam["up"])
        return self._v3(cam["pos"]) + d * zz[..., None]

    def _face_streak(self, cam, faces):
        """Streak decision per drawn face (SM.face_stretch thresholds); borderline faces re-decided by the reference."""
        torch = self.torch
        f = self.tF[faces]
        px, py, _ = self._project(cam, self.tP[f.reshape(-1)])
        sp = torch.stack([px, py], 1).reshape(-1, 3, 2)
        wh = self.tTex[self.tOwner[faces]]
        tp = self.tUV[f.reshape(-1)].reshape(-1, 3, 2) * wh[:, None, :]
        dS = torch.stack([sp[:, 1] - sp[:, 0], sp[:, 2] - sp[:, 0]], 2)
        dT = torch.stack([tp[:, 1] - tp[:, 0], tp[:, 2] - tp[:, 0]], 2)
        det = dT[:, 0, 0] * dT[:, 1, 1] - dT[:, 0, 1] * dT[:, 1, 0]
        ok = det.abs() > 1e-9
        sdet = torch.where(ok, det, torch.ones_like(det))
        i00, i11 = dT[:, 1, 1] / sdet, dT[:, 0, 0] / sdet
        i01, i10 = -dT[:, 0, 1] / sdet, -dT[:, 1, 0] / sdet
        a = dS[:, 0, 0] * i00 + dS[:, 0, 1] * i10
        b = dS[:, 0, 0] * i01 + dS[:, 0, 1] * i11
        c = dS[:, 1, 0] * i00 + dS[:, 1, 1] * i10
        d = dS[:, 1, 0] * i01 + dS[:, 1, 1] * i11
        E, Fq, G, Hq = (a + d) / 2, (a - d) / 2, (c + b) / 2, (c - b) / 2
        Q, R = torch.sqrt(E * E + Hq * Hq), torch.sqrt(Fq * Fq + G * G)
        s1, s2 = Q + R, (Q - R).abs()
        s1 = torch.where(ok, s1, torch.full_like(s1, 1e3))
        s2 = torch.clamp(torch.where(ok, s2, torch.ones_like(s2)), min=1e-6)
        ratio = s1 / s2
        hit = (s1 >= SM.S1_MIN) & (ratio >= SM.ANISO_MIN)
        # margins: the det gate, both thresholds, the 1e-6 clamp of s2 (it moves the ratio), non-finite values
        border = (_near(det.abs(), 1e-9, torch) | _near(s1, SM.S1_MIN, torch) | _near(ratio, SM.ANISO_MIN, torch)
                  | _near(s2, 1e-6, torch))
        if border.any():
            bf = faces[border].cpu().numpy()
            c1, c2 = SM.face_stretch(cam, self.P, self.UV, self.F, self.owner, self.texs, bf)
            hit[border] = torch.as_tensor((c1 >= SM.S1_MIN) & (c1 / c2 >= SM.ANISO_MIN), device=self.dev)
            self.redecided["faces"] += len(bf)
        return hit

    def _unseen_face(self, nr, fid0, tob, classes, min_area: int, faces_out: dict | None):
        """ZS.unseen_face (the reference) on the GPU: the mask, the component areas and the attribution in torch;
        only scipy's label runs on the CPU (a sequential union-find, as for the behind mask). Integer ops only."""
        from scipy.ndimage import label
        torch = self.torch
        m = nr & (self.tRestCnt[fid0] == 0)
        if not bool(m.any()):
            return 0, {}, {}
        lab_np, n = label(m.cpu().numpy())
        lab = torch.as_tensor(lab_np, device=self.dev)
        areas = torch.bincount(lab.reshape(-1), minlength=n + 1)
        keep = areas >= min_area
        keep[0] = False
        big = keep[lab]
        if faces_out is not None and bool(big.any()):
            fc = torch.bincount(fid0[big], minlength=self.nF)
            fv = torch.nonzero(fc).reshape(-1)
            for a, c in zip(fv.cpu().numpy().tolist(), fc[fv].cpu().numpy().tolist()):
                faces_out[a] = faces_out.get(a, 0) + c
        cnt = torch.bincount(tob[big], minlength=self.nB).cpu().numpy()
        by_cls, by_bin = {}, {}
        for i in np.flatnonzero(cnt):
            by_bin[self.names[i]] = int(cnt[i])
            by_cls[classes[i]] = by_cls.get(classes[i], 0) + int(cnt[i])
        return (int(big.sum()), dict(sorted(by_cls.items(), key=lambda kv: -kv[1])),
                dict(sorted(by_bin.items(), key=lambda kv: -kv[1])[:12]))

    def _ground_split(self, cam, ground, tz):
        """ZS.ground_split (the reference) on the GPU for every ground-hole px: the floor hit point projected into the
        rest frame; px whose truncation / depth decision lies within EPS_REL are re-decided by the reference. ->
        (row counts, ground with the sky-covered restSky px removed)."""
        import town_full3d_zero_streak as ZS
        torch = self.torch
        sc = self.sc
        cov_np = None
        if self.sky_r is not None:
            cov_np = self.sky_r.render(cam)[1] >= 0
        gy, gx = torch.nonzero(ground, as_tuple=True)
        if not len(gy):
            return {"groundRestSkyPx": 0, "groundRestSkyEnvPx": 0, "groundHiddenPx": 0,
                    "groundRestSkyUncoveredPx": 0}, ground
        ys, xs = gy.to(torch.float64), gx.to(torch.float64)
        t = math.tan(math.radians(cam["fov"]) / 2)
        xn = ((xs + 0.5) / W * 2 - 1) * t * W / H
        yn = (1 - (ys + 0.5) / H * 2) * t
        d = self._v3(cam["fwd"])[None] + xn[:, None] * self._v3(cam["right"])[None] + yn[:, None] * self._v3(cam["up"])[None]
        d = d / torch.sqrt(d[:, 0] * d[:, 0] + d[:, 1] * d[:, 1] + d[:, 2] * d[:, 2])[:, None]
        nd = self._dot3(d, self.floor.n)
        th = (self.floor.d - float(self.floor.n @ (cam["pos"] - sc.cam["pos"]))) / \
            torch.where(nd.abs() > 1e-12, nd, torch.full_like(nd, 1e-12))
        px, py, zc = self._project(sc.cam, self._v3(cam["pos"])[None] + d * th[:, None])
        ins = (zc > 0) & (px >= 0) & (px < W) & (py >= 0) & (py < H)
        xi = torch.clamp(torch.where(torch.isnan(px), torch.zeros_like(px), px).to(torch.int64), 0, W - 1)
        yi = torch.clamp(torch.where(torch.isnan(py), torch.zeros_like(py), py).to(torch.int64), 0, H - 1)
        fr = self.tFidRest[yi, xi]
        z0 = self.tz0[yi, xi]
        sky_state = ins & (fr < 0)
        sky_any = sky_state if self.tFidEnv is None else ins & (self.tFidEnv[yi, xi] < 0)
        cov = torch.zeros_like(ins) if cov_np is None else torch.as_tensor(cov_np, device=self.dev)[gy, gx]
        rs = sky_state & cov
        rs_env = sky_any & ~sky_state & cov
        hid = ins & ~sky_any & (fr >= 0) & (z0 < zc)
        border = (_near_int(px, torch) | _near_int(py, torch) | _near(zc, 0.0, torch) | _near(nd.abs(), 1e-12, torch)
                  | (torch.isfinite(z0) & _near(zc, z0.to(torch.float64), torch)))
        if border.any():
            bi = torch.nonzero(border).reshape(-1)
            yb, xb = gy[bi].cpu().numpy(), gx[bi].cpu().numpy()
            r1, r2, r3, r4 = ZS.ground_split(sc, cam, self.floor, yb, xb, self.fid_rest_np, self.z0_np, cov_np,
                                             self.fid_env_np)
            rs[bi] = torch.as_tensor(r1, device=self.dev)
            sky_any[bi] = torch.as_tensor(r2, device=self.dev)
            hid[bi] = torch.as_tensor(r3, device=self.dev)
            rs_env[bi] = torch.as_tensor(r4, device=self.dev)
            self.redecided["groundSplitPx"] += len(yb)
        ground = ground.clone()
        ex = rs | rs_env
        ground[gy[ex], gx[ex]] = False
        c = torch.stack([rs.sum(), rs_env.sum(), hid.sum(), (sky_any & ~ex).sum()]).cpu().numpy().tolist()
        return {"groundRestSkyPx": c[0], "groundRestSkyEnvPx": c[1], "groundHiddenPx": c[2],
                "groundRestSkyUncoveredPx": c[3]}, ground

    # ---------------------------------------------------------------------------------------------- one pose
    def pose(self, cam, min_area: int, classes, want_masks: bool = False, unseen_out: dict | None = None):
        """(row, (face ids, px counts) of the visible behind px, masks for the overlay or None) for one pose."""
        from scipy.ndimage import label
        torch = self.torch
        sc = self.sc
        z_np, fid_np = self.raster(cam)
        vis_np = fid_np >= 0
        tz = torch.as_tensor(z_np, device=self.dev)
        tfid = torch.as_tensor(fid_np, device=self.dev)
        vis = tfid >= 0
        fidv = tfid[vis]
        faces = torch.nonzero(torch.bincount(fidv, minlength=self.nF)).reshape(-1)       # == np.unique(fid[vis])
        lut = torch.zeros(self.nF, dtype=torch.bool, device=self.dev)
        lut[faces[self._face_streak(cam, faces)]] = True
        fid0 = torch.where(vis, tfid, torch.zeros_like(tfid))
        streak = vis & lut[fid0]
        # ---- revealed: reproject every drawn px into the rest frame
        zz = torch.where(torch.isfinite(tz), tz, torch.zeros_like(tz))
        wp = self._world_points(cam, zz)
        px, py, zc = self._project(sc.cam, wp)
        inside = vis & (zc > 0) & (px >= 0) & (px < W) & (py >= 0) & (py < H)
        xi = torch.clamp(torch.where(torch.isnan(px), torch.zeros_like(px), px).to(torch.int64), 0, W - 1)
        yi = torch.clamp(torch.where(torch.isnan(py), torch.zeros_like(py), py).to(torch.int64), 0, H - 1)
        thr = self.tz0[yi, xi] * (1 + self.reveal_tol)                                   # float32, as the reference
        revealed = inside & (zc > thr)
        border = vis & (_near_int(px, torch) | _near_int(py, torch) | _near(zc, 0.0, torch)
                        | (torch.isfinite(thr) & _near(zc, thr.to(torch.float64), torch)))
        if border.any():
            yb, xb = (v.cpu().numpy() for v in torch.nonzero(border, as_tuple=True))
            wpb = _world_points_px(cam, z_np[yb, xb], yb, xb)
            qx, qy, qz = T.project(sc.cam, wpb)
            ins = (qz > 0) & (qx >= 0) & (qx < W) & (qy >= 0) & (qy < H)
            qxi = np.clip(np.nan_to_num(qx, nan=0).astype(np.int64), 0, W - 1)
            qyi = np.clip(np.nan_to_num(qy, nan=0).astype(np.int64), 0, H - 1)
            rev = ins & (qz > self.z0_np[qyi, qxi] * (1 + self.reveal_tol))
            ib, jb = torch.as_tensor(yb, device=self.dev), torch.as_tensor(xb, device=self.dev)
            inside[ib, jb] = torch.as_tensor(ins, device=self.dev)
            revealed[ib, jb] = torch.as_tensor(rev, device=self.dev)
            self.redecided["revealPx"] += len(yb)
        extension = vis & ~inside
        behind = streak & revealed
        nr = streak & ~revealed & ~extension
        # ---- ground: undrawn px whose pose ray meets the painted floor plane inside the far cap
        nvis = ~vis
        ground = torch.zeros_like(vis)
        if bool(nvis.any()):
            pos = self._v3(cam["pos"])
            one = torch.where(vis, torch.zeros_like(tz, dtype=torch.float64), torch.ones_like(tz, dtype=torch.float64))
            dw = self._world_points(cam, one) - pos
            nrm = torch.sqrt(dw[..., 0] * dw[..., 0] + dw[..., 1] * dw[..., 1] + dw[..., 2] * dw[..., 2])
            dw = dw / torch.clamp(nrm, min=1e-12)[..., None]
            nd = self._dot3(dw, self.floor.n)
            off = float(self.floor.n @ (cam["pos"] - sc.cam["pos"]))
            t_hit = (self.floor.d - off) / torch.where(nd.abs() > 1e-12, nd, torch.full_like(nd, 1e-12))
            ground = nvis & (t_hit > 0) & (t_hit < T.FAR_CAP_M)
            gb = nvis & (_near(t_hit, 0.0, torch) | _near(t_hit, float(T.FAR_CAP_M), torch)
                         | _near(nd.abs(), 1e-12, torch))
            if gb.any():
                yb, xb = (v.cpu().numpy() for v in torch.nonzero(gb, as_tuple=True))
                one_np = np.ones(len(yb))
                dwb = _world_points_px(cam, one_np, yb, xb) - cam["pos"][None]
                dwb /= np.maximum(np.linalg.norm(dwb, axis=-1, keepdims=True), 1e-12)
                ndb = dwb @ self.floor.n
                tb = (self.floor.d - off) / np.where(np.abs(ndb) > 1e-12, ndb, 1e-12)
                ground[torch.as_tensor(yb, device=self.dev), torch.as_tensor(xb, device=self.dev)] = \
                    torch.as_tensor((tb > 0) & (tb < T.FAR_CAP_M), device=self.dev)
                self.redecided["groundPx"] += len(yb)
        g_split, ground = self._ground_split(cam, ground, tz)
        # ---- components (CPU: scipy label on the bool masks)
        behind_np = behind.cpu().numpy()
        lab, nlab = label(behind_np)
        areas = np.bincount(lab.ravel())[1:] if nlab else np.zeros(0, np.int64)
        big = np.flatnonzero(areas >= min_area) + 1
        keep = np.zeros(nlab + 1, bool)
        keep[big] = True
        visible = keep[lab]
        el, nel = label(~vis_np)
        top = np.unique(np.r_[el[0], el[:, 0], el[:, -1]])
        ktop = np.zeros(nel + 1, bool)
        ktop[top] = True
        enclosed = (~vis_np) & ~ktop[el]
        # ---- attribution
        fv_all = fid_np[visible]
        fv, cv = np.unique(fv_all, return_counts=True)
        by_bin_cnt = np.bincount(self.owner[fv_all], minlength=self.nB)
        tob = self.tOwner[fid0]
        nr_cnt = torch.bincount(tob[nr], minlength=self.nB).cpu().numpy()
        by_cls, by_bin = {}, {}
        for i in np.flatnonzero(by_bin_cnt):
            npx = int(by_bin_cnt[i])
            by_bin[self.names[i]] = npx
            by_cls[classes[i]] = by_cls.get(classes[i], 0) + npx
        nr_cls = {}
        for i in np.flatnonzero(nr_cnt):
            nr_cls[classes[i]] = nr_cls.get(classes[i], 0) + int(nr_cnt[i])
        uf, uf_cls, uf_bin = self._unseen_face(nr, fid0, tob, classes, min_area, unseen_out)
        cnt = torch.stack([streak.sum(), revealed.sum(), extension.sum(), behind.sum(), nr.sum(),
                           (streak & extension).sum(), ground.sum()]).cpu().numpy().tolist()
        row = {"streakPx": cnt[0], "revealedPx": cnt[1], "extensionPx": cnt[2],
               "behindPx": cnt[3], "visibleBehindPx": int(visible.sum()),
               "visibleBehindComponents": int(len(big)),
               "largestComponentPx": int(areas.max()) if len(areas) else 0,
               "streakNotRevealedPx": cnt[4],
               "streakExtensionPx": cnt[5],
               "enclosedHolePx": int(enclosed.sum()), "groundHolePx": cnt[6], **g_split,
               "streakNotRevealedByClass": dict(sorted(nr_cls.items(), key=lambda kv: -kv[1])),
               "visibleBehindByClass": dict(sorted(by_cls.items(), key=lambda kv: -kv[1])),
               "visibleBehindTopBins": dict(sorted(by_bin.items(), key=lambda kv: -kv[1])[:12]),
               "unseenFacePx": uf, "unseenFaceByClass": uf_cls, "unseenFaceTopBins": uf_bin}
        masks = None
        if want_masks:
            ob = np.where(vis_np, self.owner[np.where(vis_np, fid_np, 0)], -1)
            masks = {"vis": vis_np, "ob": ob, "revealed": revealed.cpu().numpy(), "streak": streak.cpu().numpy(),
                     "visible": visible, "behind": behind_np, "enclosed": enclosed, "ground": ground.cpu().numpy()}
        return row, (fv, cv), masks
