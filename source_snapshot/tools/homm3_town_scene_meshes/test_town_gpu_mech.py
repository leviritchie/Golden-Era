"""Parity test: town_full3d_mech.fit_wheel, --device cpu (reference) vs cuda (town_gpu_mech hub grid + cpu re-score).

On Factory tbfacas3's right-hand cog (rect 140, 24, 176, 66; the fx_mech test's wheel) and on the left-hand rect that
is refused as a wheel: the same chosen parameters (hub, q, psi, step, N, the fit report) and byte-identical outputs
(disc texture, front card, plate); the refusal is raised on both devices with the same message. No CUDA -> fails.
Run: python tools/homm3_town_scene_meshes/test_town_gpu_mech.py
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import numpy as np

os.environ["TOWN_FULL3D_FACTION"] = "factory"
sys.path.insert(0, str(Path(__file__).resolve().parent))

import stronghold_full3d_common as SC  # noqa: E402
import town_full3d_fx as FX            # noqa: E402
import town_full3d_mech as MECH        # noqa: E402


def run(F, rect, lid, device):
    MECH._CACHE.clear()
    t = time.time()
    try:
        return MECH.fit_wheel(F, rect, lid, {}, device=device), time.time() - t
    except SystemExit as e:
        return f"SystemExit: {e}", time.time() - t


def main() -> int:
    import town_gpu_kernels as GK
    GK.require_cuda()
    lm = FX.layer_meta(SC.anim_frames())
    F = FX.def_frames(lm, "tbfacas3")
    fails = []
    for rect in ((140, 24, 176, 66), (38, 24, 66, 64)):
        a, ta = run(F, rect, "tbfacas3", "cpu")
        b, tb = run(F, rect, "tbfacas3", "cuda")
        if isinstance(a, str) or isinstance(b, str):
            ok = a == b
            what = a if isinstance(a, str) else "fit"
        else:
            ok = a.keys() == b.keys()
            for k in a:
                x, y = a[k], b[k]
                same = (x is None and y is None) or (isinstance(x, np.ndarray) and isinstance(y, np.ndarray)
                                                      and x.dtype == y.dtype and x.tobytes() == y.tobytes()) \
                    or (not isinstance(x, np.ndarray) and x == y)
                if not same:
                    ok = False
                    fails.append(f"rect {rect}: {k} differs")
            what = f"hub {a['fit']['hubPx']} step {a['fit']['stepDeg']} N {a['fit']['symmetryN']}"
        print(f"rect {rect}: {'identical' if ok else 'DIFF'} ({what[:90]})  cpu {ta:.1f}s cuda {tb:.1f}s")
        if not ok and not fails:
            fails.append(f"rect {rect}: cpu {str(a)[:80]} vs cuda {str(b)[:80]}")
    for f in fails:
        print("FAIL:", f)
    print("OK" if not fails else "FAILED")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
