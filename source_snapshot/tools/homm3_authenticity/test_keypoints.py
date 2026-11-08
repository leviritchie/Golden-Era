"""CPU reference vs CUDA parity of the DEF keypoint tracker (keypoints.py propagate).

    python tools/homm3_authenticity/test_keypoints.py        (or pytest)

Propagates h3_champion's marked keypoints (tools/homm3_authenticity/keypoints/h3_champion.json) from the even frames
of its idle and attack clips onto the odd ones (marks there hidden) on both devices, with the NCC matcher and, when the DINOv3 weights are cached locally, the
DINO matcher. Float32 on both: a score tie inside the +-12 px search window can resolve to a different integer offset,
and a flat score peak shifts the sub-pixel parabola fit (seen: up to 0.98 px on 2% of points), so the tolerances bound
the share of points that differ, the median and the worst difference rather than demanding bit equality.
Skips (exit 0 with SKIP) without a CUDA device. The kp file is only read, never written.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import keypoints as KP  # noqa: E402
import torch  # noqa: E402

UNIT = "h3_champion"
CLIPS = "g02_idle,g12_attack_front"
SAME_PX = 0.05          # a point "agrees" when CPU and CUDA land within this many DEF px
AGREE_MIN = 0.85        # share of tracked points that must agree (the rest differ in the sub-pixel parabola fit)
MEDIAN_TOL = 0.01       # median CPU/CUDA difference, DEF px
MAX_TOL = 1.5           # bounds a sub-pixel refit (seen 0.98 px); marking accuracy is ~1-2 px


def run(dev: str, matcher: str) -> dict:
    u = KP.Unit(UNIT)
    d = KP.load_kp(u.lab)
    clips = u.pick_clips(CLIPS)
    tr = KP.Tracker(u, dev, matcher)
    t0 = time.perf_counter()
    hide = {(ck, i) for ck in clips for i in range(u.n(ck)) if i % 2}       # odd frames re-tracked from even marks
    KP.propagate(u, d, clips, tr, hide=hide)
    out = {}
    for ck in clips:
        for i, f in d["clips"].get(ck, {"frames": {}})["frames"].items():
            for chain, src in f["src"].items():
                for k, s in enumerate(src):
                    if s == "t" and f["pts"][chain][k] is not None:
                        out[(ck, i, chain, k)] = f["pts"][chain][k]
    print(f"  {matcher}/{dev}: {len(out)} tracked points in {time.perf_counter() - t0:.1f} s")
    return out


def compare(matcher: str) -> None:
    a, b = run("cpu", matcher), run("cuda", matcher)
    assert a.keys() == b.keys(), f"{matcher}: CPU and CUDA tracked different point sets"
    assert a, f"{matcher}: nothing tracked (no marks in {UNIT}?)"
    dd = np.array([np.hypot(a[k][0] - b[k][0], a[k][1] - b[k][1]) for k in a])
    agree = float((dd <= SAME_PX).mean())
    print(f"  {matcher}: {len(dd)} points, agree<= {SAME_PX} px {agree:.1%}, median {np.median(dd):.4f} px, "
          f"max {dd.max():.2f} px")
    assert agree >= AGREE_MIN, f"{matcher}: only {agree:.1%} of points agree across devices"
    assert np.median(dd) <= MEDIAN_TOL, f"{matcher}: median CPU/CUDA difference {np.median(dd):.4f} px"
    assert dd.max() < MAX_TOL, f"{matcher}: a point differs {dd.max():.2f} px across devices"


def dino_cached() -> bool:
    try:
        from transformers import AutoConfig
        AutoConfig.from_pretrained(KP.DINO_MODEL, local_files_only=True)
        return True
    except Exception:
        return False


def test_tracker_parity():
    if not torch.cuda.is_available():
        print("SKIP: no CUDA device")
        return
    compare("ncc")
    if dino_cached():
        compare("dino")
    else:
        print(f"  dino: SKIP ({KP.DINO_MODEL} not cached locally)")


if __name__ == "__main__":
    test_tracker_parity()
    print("PASS")
