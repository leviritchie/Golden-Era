"""Byte parity of the CS re-bake on CUDA (cs_torch.py) against the numpy reference (cs_numpy.py), on two real units.

  h3_griffin  patch_glb.patch_bytes on the retained base (artifacts/homm3_glb_patch/h3_griffin/base.glb): the patched GLB
              bytes and the csRebake record (parity, stretch, counts) must be identical on device cpu and cuda.
  h3_mummy    engine level on its retained base (no glbPatch): cs_numpy.offsets_batch over every CS_ target's key
              (cs_rekey_glb.target_times), with the COND_EDGE split on, and patch_glb.edge_stretch with the stored and
              the re-baked offsets: every array identical byte for byte.

A unit whose retained base is not staged is a SKIP (printed); a missing torch / CUDA device is a FAIL (no fallback).
Run: python tools/homm3_glb_patch/test_cs_device_parity.py [--unit U]
Gated by tools/validate_homm3_cs_bake_contract.py (full validation tier). Docs: docs/town_gpu_kernels.md, "CS re-bake".
"""
from __future__ import annotations

import argparse
import hashlib
import os
import sys
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "tools/homm3_def_retarget_delivery"))
import cs_numpy as CS  # noqa: E402
import patch_glb as PG  # noqa: E402

UNITS = ("h3_griffin", "h3_mummy")


def _base(unit: str) -> Path:
    return ROOT / "artifacts/homm3_glb_patch" / unit / "base.glb"


def _h(*arrays) -> str:
    h = hashlib.sha256()
    for a in arrays:
        a = np.ascontiguousarray(a)
        h.update(str((a.dtype.str, a.shape)).encode())
        h.update(a.tobytes())
    return h.hexdigest()


def _on(device: str, fn):
    old = os.environ.get("HOMM3_CS_DEVICE")
    os.environ["HOMM3_CS_DEVICE"] = device
    try:
        t = time.perf_counter()
        r = fn()
        return r, time.perf_counter() - t
    finally:
        if old is None:
            os.environ.pop("HOMM3_CS_DEVICE", None)
        else:
            os.environ["HOMM3_CS_DEVICE"] = old


def run_patch(unit: str, data: bytes):
    spec = PG.unit_config(unit)[PG.CONFIG_KEY]
    out, rec = PG.patch_bytes(unit, data, spec)
    return PG.sha(out), PG.canonical_sha(rec)


def run_engine(unit: str, data: bytes):
    import cs_rekey_glb as RK
    g = PG.Glb(data)
    body = PG.Body(g)
    times, _, _ = RK.target_times(g, body, unit)
    tis = sorted(times)
    Sk = RK.skin_at(g, body, times)
    Wn = body.W / np.maximum(body.W.sum(1, keepdims=True), 1e-9)
    weld = CS.Weld(body.V, body.J, Wn, body.F)
    cache = weld.rest_deltas(body.V[weld.rep])
    res = CS.offsets_batch(weld, body.V, body.J, Wn, [Sk[ti] for ti in tis], cache, CS.COND_EDGE * body.H)
    parts = []
    for (d, cond), ti in zip(res, tis):
        stored = g.read(body.targets[ti])
        parts += [d, cond, PG.edge_stretch(body, body.J, Wn, Sk[ti], stored), PG.edge_stretch(body, body.J, Wn, Sk[ti], d)]
    return _h(*parts), len(tis)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--unit", action="append", choices=UNITS)
    a = ap.parse_args(argv)
    fails = 0
    for unit in a.unit or UNITS:
        p = _base(unit)
        if not p.is_file():
            print(f"SKIP {unit}: no retained base {p}")
            continue
        data = p.read_bytes()
        fn = (lambda: run_patch(unit, data)) if PG.unit_config(unit).get(PG.CONFIG_KEY) else (lambda: run_engine(unit, data))
        cpu, tc = _on("cpu", fn)
        try:
            gpu, tg = _on("cuda", fn)
        except SystemExit as e:
            print(f"FAIL {unit}: cuda: {e}")
            fails += 1
            continue
        ok = cpu == gpu
        fails += not ok
        print(f"{'ok  ' if ok else 'FAIL'} {unit}: cs device parity {'identical' if ok else f'{cpu} != {gpu}'} "
              f"(cpu {tc:.1f} s, cuda {tg:.1f} s)")
    print(f"cs device parity: {'OK' if not fails else f'{fails} failed'}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
