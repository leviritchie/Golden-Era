"""recolor.py: colour maths vs skimage, and CUDA vs the CPU reference on small fixtures.

    python tools/homm3_unit_look/test_recolor.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import torch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import recolor as rc  # noqa: E402


def fixtures():
    rng = np.random.default_rng(7)
    rgb = rng.random((64, 64, 3))
    yy, xx = np.mgrid[:96, :96]
    ma = ((yy - 48) ** 2 / 30 ** 2 + (xx - 46) ** 2 / 20 ** 2) < 1
    mb = ((yy - 50) ** 2 / 27 ** 2 + (xx - 49) ** 2 / 18 ** 2) < 1
    uv = rng.random((40, 2))
    tris = rng.integers(0, 40, (30, 3))
    vals = rng.random((40, 3))
    return rgb, ma, mb, uv, tris, vals


def run(dev: str):
    rgb, ma, mb, uv, tris, vals = fixtures()
    lab = rc.rgb2lab(torch.tensor(rgb, device=dev))
    back = rc.lab2rgb(lab)
    rules = [{"class": "dark", "L_lt": 30}, {"class": "warm", "a_ge": 10, "C_ge": 20}]
    cls = rc.classify(lab.reshape(-1, 3), rules, "other")
    al = rc.align(torch.tensor(ma, device=dev), torch.tensor(mb, device=dev))
    img, cov = rc.raster(uv, tris, vals, 32, dev, chunk=7)
    filled = rc.nearest_fill(img, cov)
    return lab.cpu().numpy(), back.cpu().numpy(), cls, al, img.cpu().numpy(), cov.cpu().numpy(), filled.cpu().numpy()


def main() -> int:
    from skimage import color
    rgb = fixtures()[0]
    cpu = run("cpu")
    assert np.abs(cpu[0] - color.rgb2lab(rgb)).max() < 1e-2, "rgb2lab differs from skimage"
    assert np.abs(cpu[1] - rgb).max() < 1e-6, "lab2rgb does not invert rgb2lab"
    assert cpu[3][3] > 0.9, f"align IoU too low: {cpu[3]}"
    assert cpu[5].any() and (cpu[6][~cpu[5]] != 0).any(), "nearest fill left uncovered texels empty"
    if not torch.cuda.is_available():
        print("test_recolor: CPU checks OK (no CUDA: parity skipped)")
        return 0
    gpu = run("cuda")
    for i, name in ((0, "lab"), (1, "rgb"), (4, "raster"), (6, "fill")):
        assert np.abs(cpu[i] - gpu[i]).max() < 1e-6, f"CPU/CUDA {name} differ"
    assert (cpu[2] == gpu[2]).all(), "CPU/CUDA classify differ"
    assert (cpu[5] == gpu[5]).all(), "CPU/CUDA coverage differ"
    assert np.allclose(cpu[3], gpu[3], atol=1e-9), f"CPU/CUDA align differ {cpu[3]} {gpu[3]}"
    print("test_recolor: OK (skimage Lab, CPU/CUDA parity)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
