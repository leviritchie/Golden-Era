"""Parity test: town terrain bake + raymarch, --device cpu (reference) vs cuda (town_gpu_terrain).

  1. raymarch: a strided sample of the frame-extension pixels, byte-identical;
  2. bake_piece with the reference's own detail layers uploaded (layers="cpu"): every periphery piece, byte-identical;
  3. the GPU detail-layer blur (layers="gpu", the production cuda path) against cv2.GaussianBlur: per-layer max relative
     difference <= LAYER_REL_TOL, and the baked piece after the delivered sRGB encode (stronghold_full3d_scene.save_srgb)
     differs by at most SRGB_MAX_CODE code value on at most SRGB_MAX_FRAC of the channels.
Pieces are baked at 1/SCALE of their size per axis (same theta / rho range; --full for production size).
No CUDA -> fails (never skips). Exit 0 = pass.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

LAYER_REL_TOL = 1e-5       # float64 conv vs cv2's float32 accumulation: measured ~1e-7, bound with headroom
SRGB_MAX_CODE = 1          # sRGB 8-bit code value
SRGB_MAX_FRAC = 1e-3       # of the channels


def same(a, b) -> bool:
    a, b = np.asarray(a), np.asarray(b)
    return a.dtype == b.dtype and a.shape == b.shape and a.tobytes() == b.tobytes()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--full", action="store_true", help="bake pieces at production size")
    ap.add_argument("--scale", type=int, default=4)
    ap.add_argument("--ray-stride", type=int, default=5)
    a = ap.parse_args()
    np.savez_compressed = lambda *x, **k: None      # the test never writes the terrain caches
    import stronghold_full3d_scene as S
    import stronghold_full3d_periphery as PP
    import stronghold_full3d_ground as G
    import stronghold_full3d_terrain as T
    import town_gpu_terrain as GT
    GT.require_cuda()
    fails = []
    st = S.terrain_state(S.Scene())
    cam, field, floor, fd, grid, baker = (st[k] for k in ("cam", "field", "floor", "fd", "grid", "baker"))
    if baker.gs is not None:
        fails.append("TOWN_FULL3D_GROUNDSRC is set; the cuda bake refuses it, unset it for this test")

    ys, xs = np.mgrid[0:T.H, 0:T.W]
    ext = (xs >= T.TW) | (ys >= T.TH)
    px, py = xs[ext][::a.ray_stride] + 0.5, ys[ext][::a.ray_stride] + 0.5
    t0 = time.time(); r_cpu = T.raymarch(cam, field, px, py, device="cpu")
    t1 = time.time(); r_gpu = T.raymarch(cam, field, px, py, device="cuda"); t2 = time.time()
    ok = same(r_cpu, r_gpu)
    print(f"raymarch {len(px)} rays: {'identical' if ok else 'DIFF'}  cpu {t1 - t0:.2f}s cuda {t2 - t1:.2f}s")
    if not ok:
        fails.append("raymarch not byte-identical")

    hc = PP.cam_height(floor, cam)
    mesh = PP.polar_mesh(cam, field, PP.frame_depth_grid(grid, cam), fd["sky"])
    pcs = PP.piece_layout(mesh, hc)
    names = sorted({nm for nm, _ in G.FLOOR_TEX} | {nm for nm, _ in G.ROCK_TEX})
    for nm in names:
        ref = G.detail_layer(nm)
        got = GT.dn(GT.detail_layer(nm, "gpu"))
        rel = float(np.max(np.abs(got.astype(np.float64) - ref) / np.maximum(np.abs(ref), 1e-6)))
        print(f"layer {nm}: max rel {rel:.2e}")
        if not (got.shape == ref.shape and got.dtype == ref.dtype and rel <= LAYER_REL_TOL):
            fails.append(f"detail layer {nm}: rel {rel:.2e} > {LAYER_REL_TOL} or shape/dtype")
    tc = tg = 0.0
    for pc in pcs:
        if not a.full:
            pc = dict(pc, size=[max(8, pc["size"][0] // a.scale), max(8, pc["size"][1] // a.scale)])
        t0 = time.time(); ref = PP.bake_piece(baker, field, floor, cam, pc, device="cpu")
        t1 = time.time(); exact = GT.bake_piece(baker, field, floor, cam, pc, layers="cpu")
        t2 = time.time(); prod = PP.bake_piece(baker, field, floor, cam, pc, device="cuda"); t3 = time.time()
        tc += t1 - t0; tg += t3 - t2
        ok = same(ref, exact)
        e8 = lambda x: (G.lin_to_srgb(x) * 255 + 0.5).astype(np.uint8)
        d = np.abs(e8(ref).astype(int) - e8(prod).astype(int))
        print(f"piece {pc['name']} {pc['size']}: layers=cpu {'identical' if ok else 'DIFF'}; layers=gpu sRGB max {d.max()} "
              f"frac {np.mean(d > 0):.2e}  cpu {t1 - t0:.1f}s cuda {t3 - t2:.1f}s")
        if not ok:
            fails.append(f"piece {pc['name']}: cuda bake (reference layers) not byte-identical")
        if d.max() > SRGB_MAX_CODE or np.mean(d > 0) > SRGB_MAX_FRAC:
            fails.append(f"piece {pc['name']}: sRGB diff max {d.max()} frac {np.mean(d > 0):.2e} over bound")
    print(f"bake total cpu {tc:.1f}s cuda {tg:.1f}s")
    for f in fails:
        print("FAIL:", f)
    print("OK" if not fails else "FAILED")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
