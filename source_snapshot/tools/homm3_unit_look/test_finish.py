"""finish.py (look B, "vanilla philosophy"): properties on a synthetic unit, and CPU reference vs CUDA parity.

    python tools/homm3_unit_look/test_finish.py        (or pytest)

The synthetic unit is a lat-long UV sphere on a 256 texture with a DEF-like target frame; no repo artifacts are read.
Parity: CUDA and CPU round differently (FMA, reduction order), and the grade is a grid argmin, so the fitted
parameters must agree exactly and the textures within a small tolerance. Without CUDA the parity part prints SKIP.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import torch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import finish as FN  # noqa: E402

F64 = torch.float64


def sphere(dev, nu=48, nv=24):
    us, vs = np.linspace(0, 1, nu + 1), np.linspace(0, 1, nv + 1)
    U, Vv = np.meshgrid(us, vs)
    th, ph = U * 2 * np.pi, Vv * np.pi
    P = np.stack([np.sin(ph) * np.cos(th), 1.0 - np.cos(ph) * -1.0 + 0.2 * np.sin(3 * th) * np.sin(ph) ** 2,
                  np.sin(ph) * np.sin(th)], -1).reshape(-1, 3)
    P[:, 1] = -np.cos(ph).reshape(-1) + 1.0 + 0.15 * (np.sin(3 * th) * np.sin(ph) ** 2).reshape(-1)  # bumpy: crevices
    N = P - np.array([0, 1.0, 0])
    N /= np.linalg.norm(N, axis=1, keepdims=True)
    UV = np.stack([U, Vv], -1).reshape(-1, 2) * 0.9 + 0.05            # gutters around the island
    F = []
    for j in range(nv):
        for i in range(nu):
            a, b, c, d = j * (nu + 1) + i, j * (nu + 1) + i + 1, (j + 1) * (nu + 1) + i, (j + 1) * (nu + 1) + i + 1
            F += [[a, c, b], [b, c, d]]
    t = lambda x, dt=F64: torch.as_tensor(np.asarray(x), dtype=dt, device=dev)  # noqa: E731
    g = {"V": t(P), "N": t(N), "UV": t(UV), "F": t(F, torch.int64), "Vbind": t(P), "Nbind": t(N)}
    return g


def texture(dev, size=256):
    rng = np.random.default_rng(5)
    y, x = np.mgrid[0:size, 0:size] / size
    base = np.stack([0.25 + 0.4 * x, 0.2 + 0.3 * y, 0.15 + 0.1 * np.sin(6 * x)], -1)
    tex = np.clip(base * (0.6 + 0.8 * rng.random((size, size, 1))), 0, 1)
    tex[(x < 0.04) | (x > 0.96) | (y < 0.04) | (y > 0.96)] = 0.0       # black gutters, like a delivered A
    return torch.as_tensor(tex, dtype=torch.float32, device=dev)


def def_frame():
    rng = np.random.default_rng(9)
    im = np.zeros((96, 96, 4), np.uint8)
    yy, xx = np.mgrid[0:96, 0:96]
    m = (yy - 48) ** 2 + (xx - 48) ** 2 < 36 ** 2
    im[m, :3] = np.clip(rng.normal([120, 100, 70], 35, (int(m.sum()), 3)), 0, 255).astype(np.uint8)
    im[m, 3] = 255
    return im


def masks(dev, size=256):
    y, x = np.mgrid[0:size, 0:size] / size
    metal = ((x > 0.55) & (x < 0.8) & (y > 0.3) & (y < 0.6)).astype(np.float32)
    prot = ((x > 0.15) & (x < 0.35) & (y > 0.55) & (y < 0.8)).astype(np.float32)
    return torch.as_tensor(prot, device=dev), torch.as_tensor(metal, device=dev)


def run(dev):
    torch.manual_seed(0)
    g = sphere(dev)
    A = texture(dev)
    prot, metal = masks(dev)
    B, lg = FN.finish_vanilla(A, g, def_frame(), protect=prot, metal=metal)
    return A, B, lg, prot, metal


def test_properties():
    dev = torch.device("cpu")
    assert float(FN.vwrap(torch.tensor([1.0]))[0]) == 1.0 and float(FN.vwrap(torch.tensor([1.25]))[0]) == 0.25
    # grade: soft toe holds the floor, white stays white, chroma lift keeps hue
    lab = torch.tensor([[0.0, 0, 0], [100.0, 0, 0], [50.0, 20, -10]], dtype=F64)
    gr = FN.grade(lab, 1.0, 1.0, 1.3)
    assert abs(float(gr[0, 0]) - FN.FLOOR) < 1e-6 and abs(float(gr[1, 0]) - 100) < 1e-6
    assert abs(float(torch.atan2(gr[2, 2], gr[2, 1]) - torch.atan2(lab[2, 2], lab[2, 1]))) < 1e-9
    assert float(torch.hypot(gr[2, 1], gr[2, 2])) > float(torch.hypot(lab[2, 1], lab[2, 2]))
    # hue-binned chroma ceiling: a texel is lifted at most to its hue's DEF C95, never reduced below its own C
    dl = torch.tensor([[60.0, 20 * np.cos(h), 20 * np.sin(h)] for h in np.linspace(0.2, 0.4, 50)] +
                      [[60.0, 50 * np.cos(h), 50 * np.sin(h)] for h in np.linspace(4.2, 4.4, 50)], dtype=F64)
    ceil = FN.hue_ceiling(dl)
    skin = torch.tensor([[50.0, 15 * np.cos(0.3), 15 * np.sin(0.3)], [50.0, 30 * np.cos(0.3), 30 * np.sin(0.3)]], dtype=F64)
    gc = FN.grade(skin, 1.0, 1.0, 2.2, ceil)
    c = torch.hypot(gc[:, 1], gc[:, 2])
    assert float(c[0]) <= 20 + 1e-6 and float(c[0]) > 15 and abs(float(c[1]) - 30) < 1e-6, c
    # box blur matches scipy's uniform_filter (reflect) on a random image
    from scipy import ndimage
    x = np.random.default_rng(1).random((37, 41))
    ref = ndimage.uniform_filter(x, size=7, mode="reflect")
    assert np.abs(FN.box(torch.as_tensor(x), 3).numpy() - ref).max() < 1e-12
    A, B, lg, prot, metal = run(dev)
    Lb = FN.srgb_to_lab(B.to(F64))[..., 0]
    att, m1k = FN.uv_attrs(sphere(dev), torch.zeros((sphere(dev)["V"].shape[0], 3), dtype=F64), FN.ATTR_SIZE)
    m = torch.nn.functional.interpolate(m1k[None, None].float(), size=A.shape[:2], mode="nearest")[0, 0] > 0.5
    # black floor and filled gutters
    assert float(Lb[m].min()) >= FN.FLOOR * 0.85 - 0.6, float(Lb[m].min())
    assert float((B[~m].max(-1).values < 0.03).float().mean()) < 0.01
    # regions keep A exactly (up to 8-bit rounding of the linear blend)
    pm = (prot > 0.99) & m
    assert float((B[pm] - A[pm]).abs().max()) < 2e-3
    # metal keeps its fine band (detail not halved); the rest is halved then re-held at 0.5x
    LA = FN.srgb_to_lab(A.to(F64))[..., 0]

    def fine(L, sel):
        return float((L - FN.box(L, 2))[sel].std())
    mm = (metal > 0.5) & m & ~pm
    rest = (metal < 0.5) & m & ~pm
    assert fine(Lb, mm) / fine(LA, mm) > 0.8 * fine(Lb, rest) / fine(LA, rest) + 0.2, (fine(Lb, mm), fine(LA, mm))
    assert lg["r_L_up_B"] >= 0.199 or lg["toplit_bound_hit"]     # k >= 0: an A already above 0.20 stays
    assert lg["metalTexelShare"] > 0 and lg["protectedTexelShare"] > 0
    # metal hue (step 6): a green-tinted A over neutral-grey source metal comes out neutral; a coloured source texel
    # under the same Meshy mask (cloth Meshy marked metallic) keeps the graded hue
    At = A.clone()
    At[..., 1] = (At[..., 1] + 0.12).clamp(0, 1)                     # the v7c tint: green cast on everything
    src = torch.full_like(A, 0.35)                                     # neutral grey source
    y, x = torch.meshgrid(torch.arange(256), torch.arange(256), indexing="ij")
    redcloth = (x > 140) & (x < 200) & (y > 160) & (y < 200)
    src[redcloth] = torch.tensor([0.55, 0.15, 0.12])                   # coloured source under the metal mask
    hm = ((x > 100) & (x < 220) & (y > 140) & (y < 220)).float()
    Bh, lh = FN.finish_vanilla(At, sphere(dev), def_frame(), hue_src=src, hue_mask=hm)
    Bn, _ = FN.finish_vanilla(At, sphere(dev), def_frame())
    sel = (hm > 0.5) & m & ~redcloth
    sel[150:220, 135:205] = False                                      # away from the cloth's blur edge
    abh = FN.srgb_to_lab(Bh[sel].to(F64))[:, 1:].norm(dim=-1).mean()
    abn = FN.srgb_to_lab(Bn[sel].to(F64))[:, 1:].norm(dim=-1).mean()
    assert float(abh) < 0.35 * float(abn), (float(abh), float(abn))
    rc = redcloth & m
    rc[:, :145] = False; rc[:, 195:] = False; rc[:165] = False; rc[195:] = False
    assert float((Bh[rc] - Bn[rc]).abs().max()) < 0.02, float((Bh[rc] - Bn[rc]).abs().max())
    Lh, Ln = FN.srgb_to_lab(Bh[sel].to(F64))[:, 0], FN.srgb_to_lab(Bn[sel].to(F64))[:, 0]
    assert float((Lh - Ln).abs().mean()) < 1.0                       # lightness is B's
    assert lh["metalHueTexelShare"] > 0
    # neutral guard (step 7): with no metal mask, a green-tinted A over a neutral-grey source does not drift to green
    # (a* >= source a* - 0.5), a coloured source texel keeps the full grade, and the warm b* drift is kept
    Bg, lgd = FN.finish_vanilla(At, sphere(dev), def_frame(), hue_src=src)
    labg, labn = FN.srgb_to_lab(Bg.to(F64)), FN.srgb_to_lab(Bn.to(F64))
    ng = m & ~redcloth
    ng[150:220, 135:205] = False
    assert float(labn[..., 1][ng].mean()) < -2.0, float(labn[..., 1][ng].mean())          # the fixture does tint green
    assert float(labg[..., 1][ng].min()) > -0.5, float(labg[..., 1][ng].min())
    assert float((labg[..., 2][ng] - labn[..., 2][ng]).abs().mean()) < 0.5        # b* (warm/cool) kept (sRGB round trip)
    assert float((Bg[rc] - Bn[rc]).abs().max()) < 0.02
    assert lgd["neutralGuardTexelShare"] > 0.5 and "metalHueTexelShare" not in lgd
    print("properties OK", {k: lg[k] for k in ("grade_k", "grade_gamma", "chroma_scale", "toplit_k", "render_B_L_p5_p50_p95")})


def test_accent_floor():
    # step 8: a dark DEF body pulls the grade down; A's bright patch (bone/blade) keeps >= 0.85x its L*, while the
    # dark body follows the same (k, gamma) as without the floor
    dev = torch.device("cpu")
    g = sphere(dev)
    A = texture(dev) * 0.6
    size = A.shape[0]
    y, x = torch.meshgrid(torch.arange(size), torch.arange(size), indexing="ij")
    patch = (x > 60) & (x < 120) & (y > 70) & (y < 130)
    A[patch] = torch.tensor([0.85, 0.83, 0.78])
    d = def_frame()
    d[..., :3] = (d[..., :3].astype(np.float32) * 0.35).astype(np.uint8)      # necropolis-dark target
    keep = FN.ACCENT_KEEP
    try:
        FN.ACCENT_KEEP = 0.0
        Bn, ln = FN.finish_vanilla(A, g, d)
    finally:
        FN.ACCENT_KEEP = keep
    Bf, lf = FN.finish_vanilla(A, g, d)
    assert (lf["grade_k"], lf["grade_gamma"]) == (ln["grade_k"], ln["grade_gamma"])   # fit unchanged
    LA, Ln, Lf = (FN.srgb_to_lab(t.to(F64))[..., 0] for t in (A, Bn, Bf))
    inner = patch & (x > 66) & (x < 114) & (y > 76) & (y < 124)
    assert float(Ln[inner].mean()) < 0.8 * float(LA[inner].mean()), "fixture should darken the patch"
    assert float(Lf[inner].mean()) >= FN.ACCENT_KEEP * float(LA[inner].mean()) - 2.0, (float(Lf[inner].mean()),
                                                                                          float(LA[inner].mean()))
    dark = (LA < 35) & (LA > 5) & ~patch
    dark[patch.roll(8, 0) | patch.roll(-8, 0) | patch.roll(8, 1) | patch.roll(-8, 1)] = False
    assert float((Lf[dark] - Ln[dark]).abs().mean()) < 1.0, float((Lf[dark] - Ln[dark]).abs().mean())
    assert lf["accentTexelShare"] > 0 and lf["accent_dL_mean"] > 2
    print("accent floor OK", {"patch A/B0/B8": [round(float(t[inner].mean()), 1) for t in (LA, Ln, Lf)]})


def test_parity():
    if not torch.cuda.is_available():
        print("SKIP parity: no CUDA device")
        return
    _, Bc, lc, _, _ = run(torch.device("cpu"))
    _, Bg, lg, _, _ = run(FN.device("cuda"))
    for k in ("grade_k", "grade_gamma", "chroma_scale", "grade_bound_hit", "toplit_bound_hit"):
        assert lc[k] == lg[k], (k, lc[k], lg[k])
    assert abs(lc["toplit_k"] - lg["toplit_k"]) < 1e-3
    d = (Bc - Bg.cpu()).abs()
    assert float(d.mean()) < 1e-4 and float(d.max()) < 2e-2, (float(d.mean()), float(d.max()))
    print("parity OK: mean |dB|", float(d.mean()), "max", float(d.max()))


if __name__ == "__main__":
    test_properties()
    test_accent_floor()
    test_parity()
