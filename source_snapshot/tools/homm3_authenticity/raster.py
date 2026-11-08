"""Torch kernels for the authenticity board: morph + linear-blend skinning, projection, a z-buffered triangle
rasteriser and textured Lambert shading. One code path for both devices: ``cuda`` is the default and ``cpu`` is the
reference (test_board.py compares them). A missing CUDA device raises; nothing falls back silently.

Rasteriser: every (triangle, pixel-centre-in-its-bbox) pair is enumerated in chunks, tested with edge functions,
and the nearest fragment per pixel wins through one ``scatter_reduce_(amin)`` over an int64 key
(float32 depth bits << 32 | triangle id; depth is kept positive, so its IEEE bits order like the value). The id in
the low bits makes the winner deterministic on both devices. Perspective-correct interpolation of depth, UV and
normals. Alpha is coverage (the body materials are OPAQUE; any other alpha mode is refused by board.py).
"""
from __future__ import annotations

import os

import numpy as np
import torch
import torch.nn.functional as TF

VRAM_CAP_GB = float(os.environ.get("HOMM3_AUTH_VRAM_CAP_GB", "2"))
MAX_PAIRS = int(os.environ.get("HOMM3_AUTH_MAX_PAIRS", str(1 << 22)))
I64_MAX = torch.iinfo(torch.int64).max


def resolve_device(device: str) -> torch.device:
    if device == "cpu":
        return torch.device("cpu")
    if device != "cuda":
        raise SystemExit(f"authenticity board: device {device!r} is not cuda or cpu")
    if not torch.cuda.is_available():
        raise SystemExit("authenticity board: --device cuda requested but torch sees no CUDA device "
                         "(pass --device cpu for the reference path)")
    dev = torch.device("cuda", torch.cuda.current_device())
    total = torch.cuda.get_device_properties(dev).total_memory
    torch.cuda.set_per_process_memory_fraction(min(1.0, VRAM_CAP_GB * 2 ** 30 / total), dev)
    return dev


class DeviceMesh:
    """Rest geometry, skin and morphs of a gltf_scene.Scene on one device (float32)."""

    def __init__(self, scene, dev: torch.device, texture: np.ndarray):
        f32 = torch.float32
        self.dev = dev
        self.P = torch.as_tensor(scene.P, dtype=f32, device=dev)
        self.N = torch.as_tensor(scene.N, dtype=f32, device=dev)
        self.UV = torch.as_tensor(scene.UV, dtype=f32, device=dev)
        self.J = torch.as_tensor(scene.J, dtype=torch.int64, device=dev)
        self.W = torch.as_tensor(scene.W, dtype=f32, device=dev)
        self.F = torch.as_tensor(scene.F, dtype=torch.int64, device=dev)
        self.morphs = torch.as_tensor(scene.morphs, dtype=f32, device=dev)          # (M, N, 3)
        self.tex = torch.as_tensor(texture, dtype=f32, device=dev).permute(2, 0, 1)[None].contiguous()  # (1, 4, H, W)
        self.color_factor = torch.as_tensor(scene.base_color_factor, dtype=f32, device=dev)

    def skin(self, Jm: np.ndarray, mw: np.ndarray, chunk: int = 8) -> tuple[torch.Tensor, torch.Tensor]:
        """Jm (B, J, 4, 4) global@IBM, mw (B, M) -> world positions (B, N, 3) and normals (B, N, 3)."""
        Jm_t = torch.as_tensor(Jm, dtype=torch.float32, device=self.dev)
        mw_t = torch.as_tensor(mw, dtype=torch.float32, device=self.dev)
        outP, outN = [], []
        for b0 in range(0, Jm_t.shape[0], chunk):
            J = Jm_t[b0:b0 + chunk]
            B = J.shape[0]
            rest = self.P[None].expand(B, -1, -1)
            if self.morphs.shape[0]:
                # morph weights are sparse per pose (a corrective key is 0 -> 1 -> 0 around its own frame): sum only the
                # active targets, elementwise (no cuBLAS: its handle alone costs ~350 MB of host RSS)
                rest = rest.clone()
                w = mw_t[b0:b0 + chunk]
                for bi, m in torch.nonzero(w.abs() > 1e-7).cpu().tolist():
                    rest[bi] += w[bi, m] * self.morphs[m]
            M = torch.zeros((B, self.P.shape[0], 3, 4), dtype=torch.float32, device=self.dev)
            for k in range(self.J.shape[1]):
                M = M + self.W[None, :, k, None, None] * J[:, self.J[:, k], :3, :]
            p = (M[..., :3] * rest[:, :, None, :]).sum(-1) + M[..., 3]
            n = (M[..., :3] * self.N[None, :, None, :]).sum(-1)
            n = n / n.norm(dim=-1, keepdim=True).clamp_min(1e-12)
            outP.append(p)
            outN.append(n)
        return torch.cat(outP), torch.cat(outN)


def project(cam: dict, P: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
    """P (..., 3) world -> pixel xy (..., 2) (x right, y down; pixel i covers [i, i+1)) and view depth (..., )."""
    dev = P.device
    eye = torch.as_tensor(cam["eye"], dtype=torch.float32, device=dev)
    r = torch.as_tensor(cam["right"], dtype=torch.float32, device=dev)
    u = torch.as_tensor(cam["up"], dtype=torch.float32, device=dev)
    f = torch.as_tensor(cam["fwd"], dtype=torch.float32, device=dev)
    d = P - eye
    z = (d * f).sum(-1)
    dr, du = (d * r).sum(-1), (d * u).sum(-1)
    if cam["kind"] == "ortho":
        x = cam["cx"] + cam["scale"] * dr
        y = cam["cy"] - cam["scale"] * du
    else:
        zz = z.clamp_min(1e-6)
        x = cam["cx"] + cam["scale"] * dr / zz
        y = cam["cy"] - cam["scale"] * du / zz
    return torch.stack([x, y], -1), z


def _edges(v: torch.Tensor, px: torch.Tensor, py: torch.Tensor, area: torch.Tensor):
    """Barycentric weights of pixel centres (px, py) in screen triangles v (K, 3, 2) of signed area `area`."""
    x0, y0, x1, y1, x2, y2 = v[:, 0, 0], v[:, 0, 1], v[:, 1, 0], v[:, 1, 1], v[:, 2, 0], v[:, 2, 1]
    w0 = ((x1 - px) * (y2 - py) - (x2 - px) * (y1 - py)) / area
    w1 = ((x2 - px) * (y0 - py) - (x0 - px) * (y2 - py)) / area
    w2 = ((x0 - px) * (y1 - py) - (x1 - px) * (y0 - py)) / area
    return w0, w1, w2


def rasterize(xy: torch.Tensor, z: torch.Tensor, F: torch.Tensor, W: int, H: int, persp: bool) -> torch.Tensor:
    """Nearest-fragment triangle id per pixel (H*W,), -1 where empty. z must be > 0 (callers offset ortho depth)."""
    dev = xy.device
    v = xy[F]                                            # (T, 3, 2)
    zt = z[F]
    area = (v[:, 1, 0] - v[:, 0, 0]) * (v[:, 2, 1] - v[:, 0, 1]) - (v[:, 2, 0] - v[:, 0, 0]) * (v[:, 1, 1] - v[:, 0, 1])
    x0 = torch.ceil(v[..., 0].min(1).values - 0.5).clamp_min(0).to(torch.int64)
    x1 = torch.floor(v[..., 0].max(1).values - 0.5).clamp_max(W - 1).to(torch.int64)
    y0 = torch.ceil(v[..., 1].min(1).values - 0.5).clamp_min(0).to(torch.int64)
    y1 = torch.floor(v[..., 1].max(1).values - 0.5).clamp_max(H - 1).to(torch.int64)
    valid = (x1 >= x0) & (y1 >= y0) & (area.abs() > 1e-12) & (zt > 0).all(1)
    bw = (x1 - x0 + 1).clamp_min(0)
    cnt = torch.where(valid, bw * (y1 - y0 + 1).clamp_min(0), torch.zeros_like(bw))
    buf = torch.full((H * W,), I64_MAX, dtype=torch.int64, device=dev)
    cs = torch.cumsum(cnt, 0).cpu().numpy()             # chunk bounds on the host (a few ints per render)
    total = int(cs[-1]) if len(cs) else 0
    a = 0
    while total and a < len(cs):
        base = int(cs[a - 1]) if a else 0
        b = int(np.searchsorted(cs, base + MAX_PAIRS, side="right"))
        b = max(b, a + 1)
        c = cnt[a:b]
        n = int(cs[b - 1]) - base
        if n:
            tri = torch.repeat_interleave(torch.arange(a, b, device=dev), c)
            start = torch.cumsum(c, 0) - c
            off = torch.arange(n, device=dev) - torch.repeat_interleave(start, c)
            px = x0[tri] + off % bw[tri]
            py = y0[tri] + torch.div(off, bw[tri], rounding_mode="floor")
            w0, w1, w2 = _edges(v[tri], px.float() + 0.5, py.float() + 0.5, area[tri])
            ins = (w0 >= 0) & (w1 >= 0) & (w2 >= 0)
            tri, px, py, w0, w1, w2 = tri[ins], px[ins], py[ins], w0[ins], w1[ins], w2[ins]
            zz = zt[tri]
            if persp:
                depth = 1.0 / (w0 / zz[:, 0] + w1 / zz[:, 1] + w2 / zz[:, 2])
            else:
                depth = w0 * zz[:, 0] + w1 * zz[:, 1] + w2 * zz[:, 2]
            depth = depth.clamp_min(1e-30).contiguous()
            key = (depth.view(torch.int32).to(torch.int64) << 32) | tri
            buf.scatter_reduce_(0, py * W + px, key, reduce="amin")
        a = b
    return torch.where(buf == I64_MAX, torch.full_like(buf, -1), buf & 0xFFFFFFFF)


def shade(mesh: DeviceMesh, cam: dict, xy: torch.Tensor, z: torch.Tensor, Nw: torch.Tensor, tid: torch.Tensor,
          W: int, H: int, ambient: float = 0.42, diffuse: float = 0.68) -> torch.Tensor:
    """RGBA (H, W, 4) float32: textured Lambert (light from the camera's upper left), alpha = coverage."""
    dev = xy.device
    out = torch.zeros((H * W, 4), dtype=torch.float32, device=dev)
    pix = torch.nonzero(tid >= 0)[:, 0]
    if pix.numel() == 0:
        return out.view(H, W, 4)
    t = tid[pix]
    Fi = mesh.F[t]                                        # (K, 3)
    v = xy[Fi]
    area = (v[:, 1, 0] - v[:, 0, 0]) * (v[:, 2, 1] - v[:, 0, 1]) - (v[:, 2, 0] - v[:, 0, 0]) * (v[:, 1, 1] - v[:, 0, 1])
    px = (pix % W).float() + 0.5
    py = torch.div(pix, W, rounding_mode="floor").float() + 0.5
    w = torch.stack(_edges(v, px, py, area), -1).clamp_min(0)
    if cam["kind"] == "persp":
        w = w / z[Fi].clamp_min(1e-6)
    w = w / w.sum(-1, keepdim=True).clamp_min(1e-12)
    uv = (w[..., None] * mesh.UV[Fi]).sum(1)
    n = (w[..., None] * Nw[Fi]).sum(1)
    n = n / n.norm(dim=-1, keepdim=True).clamp_min(1e-12)
    f = torch.as_tensor(cam["fwd"], dtype=torch.float32, device=dev)
    r = torch.as_tensor(cam["right"], dtype=torch.float32, device=dev)
    u = torch.as_tensor(cam["up"], dtype=torch.float32, device=dev)
    n = torch.where((n * f).sum(-1, keepdim=True) > 0, -n, n)          # two-sided: face the camera
    L = -0.38 * r + 0.55 * u - 0.74 * f
    L = L / L.norm()
    lam = ambient + diffuse * (n * L).sum(-1).clamp_min(0)
    g = torch.stack([torch.remainder(uv[:, 0], 1.0) * 2 - 1, torch.remainder(uv[:, 1], 1.0) * 2 - 1], -1)
    alb = TF.grid_sample(mesh.tex, g[None, None], mode="bilinear", padding_mode="border", align_corners=False)[0, :, 0].T
    rgb = (alb[:, :3] * mesh.color_factor[:3]) * lam[:, None]
    out[pix] = torch.cat([rgb.clamp(0, 1), torch.ones_like(lam)[:, None]], -1)
    return out.view(H, W, 4)


def render(mesh: DeviceMesh, cam: dict, P: torch.Tensor, Nw: torch.Tensor, ss: int = 1) -> torch.Tensor:
    """One frame: RGBA (H, W, 4) float32 on the device, box-filtered down from an ss x ss supersample."""
    if P.dim() == 3:
        if P.shape[0] != 1:
            raise ValueError("render takes one frame")
        P, Nw = P[0], Nw[0]
    W, H = cam["W"] * ss, cam["H"] * ss
    c = dict(cam, cx=cam["cx"] * ss, cy=cam["cy"] * ss, scale=cam["scale"] * ss)
    xy, z = project(c, P)
    if c["kind"] == "ortho":
        z = z - z.min() + 1.0
    tid = rasterize(xy, z, mesh.F, W, H, c["kind"] == "persp")
    img = shade(mesh, c, xy, z, Nw, tid, W, H)
    if ss > 1:
        img = TF.avg_pool2d(img.permute(2, 0, 1)[None], ss)[0].permute(1, 2, 0)
    return img
