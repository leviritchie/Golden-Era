#!/usr/bin/env python3
"""Parity: the zero-streak certificate on the GPU (town_gpu_kernels) reproduces the CPU reference exactly.

    python tools/homm3_town_scene_meshes/test_town_gpu_kernels.py [--case castle/zs_v8 ...] [--state full] [--loop 4]

On real staged scenes (default CASES: castle zs_v8, the base of the installed zs_v8_bok1, and the failing rx_ldi_zone_old_nfix;
state "full") it certifies the proof poses,
sweep_fwd and --loop sweep samples with device cpu and device cuda and requires, byte for byte: the report JSON (every
pose row: px counts, component counts, class / bin attribution; the summary and pass), the faces_out map the recipe's
repair acts on, the saved overlay PNGs, and the rest / pose z-buffers of town_gpu_kernels.Raster against
town_full3d_t2_paint.zbuffer; and the building seam arrays (town_full3d_building_seams.rest_seams, every layer
with a stage_report row) from both devices, byte for byte. A candidate not staged on this machine is reported SKIP (artifacts/ is not in git);
a missing CUDA device FAILS (the certificate's default device is cuda). Gate: tools/validate_town_zero_streak_contract.py.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRATCH = Path(os.environ.get("TOWN_GPU_PARITY_SCRATCH", "V:/olden_port_work/gpu_offload/parity"))


def run(a) -> int:
    sys.path.insert(0, str(HERE))
    import numpy as np
    import stronghold_full3d_common as SC
    import stronghold_full3d_scene as S
    import town_full3d_t2_paint as TP
    import town_full3d_zero_streak as ZS
    import town_gpu_kernels as GK
    import town_t2_streak_map as SM
    if not S.ROWS.is_file():
        print(f"SKIP {a.faction}/{a.candidate}: not staged on this machine ({S.ROWS})")
        return 0
    GK.require_cuda()
    sc = S.Scene()
    rows = json.loads(S.ROWS.read_text(encoding="utf-8"))
    keys = [S.ENV_KEY] + [S.PREFIX + l for l in SC.FP.STATES[a.state]]
    P, UV, F, owner, names, texs = SM.load_bins(sc, rows, keys)
    cams = ZS.reachable_cams(sc, a.loop)
    sky = ZS.load_sky(sc, rows, keys)          # the restSky refinement of the ground-hole term is compared too
    errs = []
    ras = GK.Raster(P, F)
    try:
        for k in ("default", "sweep_fwd"):
            zg, fg = ras.render(cams[k])
            zc, fc = TP.zbuffer(cams[k], P, F, sup=1)
            if not (np.array_equal(zg, zc) and np.array_equal(fg, fc)):
                errs.append(f"Raster != TP.zbuffer at {k}")
    finally:
        ras.release()
    reps, hits, secs = {}, {}, {}
    for dev in ("cpu", "cuda"):
        out = SCRATCH / f"{a.faction}_{a.candidate}_{a.state}_{dev}"
        shutil.rmtree(out, ignore_errors=True)
        out.mkdir(parents=True)
        hits[dev] = {}
        t = time.time()
        reps[dev] = ZS.certify(sc, P, UV, F, owner, names, texs, cams, out=out, save_worst=3, faces_out=hits[dev],
                               device=dev, sky=sky)
        secs[dev] = time.time() - t
    if json.dumps(reps["cpu"]) != json.dumps(reps["cuda"]):
        for pose in reps["cpu"]["poses"]:
            if json.dumps(reps["cpu"]["poses"][pose]) != json.dumps(reps["cuda"]["poses"].get(pose)):
                errs.append(f"pose {pose}: cpu {json.dumps(reps['cpu']['poses'][pose])} != "
                            f"cuda {json.dumps(reps['cuda']['poses'].get(pose))}")
        errs.append("report JSON differs")
    if hits["cpu"] != hits["cuda"]:
        errs.append(f"faces_out differs ({len(hits['cpu'])} vs {len(hits['cuda'])} faces)")
    dc, dg = (SCRATCH / f"{a.faction}_{a.candidate}_{a.state}_{d}" for d in ("cpu", "cuda"))
    pc, pg = sorted(p.name for p in dc.glob("*.png")), sorted(p.name for p in dg.glob("*.png"))
    if pc != pg or any((dc / n).read_bytes() != (dg / n).read_bytes() for n in pc):
        errs.append(f"overlay PNGs differ ({pc} vs {pg})")
    import town_full3d_building_seams as SEAMS
    srep = json.loads((S.WORK / "stage_report.json").read_text(encoding="utf-8"))
    lids = sorted(k[len(S.PREFIX):] for k in rows if k.startswith(S.PREFIX) and k != S.ENV_KEY
                  and k[len(S.PREFIX):] in (srep.get("buildings") or {}))
    sarr = {}
    for dev in ("cpu", "cuda"):
        t = time.time()
        sarr[dev] = SEAMS.rest_seams(sc, S, rows, srep, lids, device=dev)
        secs["seams_" + dev] = time.time() - t
    a_, b_ = sarr["cpu"], sarr["cuda"]
    if a_.keys() != b_.keys() or any(a_[k].dtype != b_[k].dtype or a_[k].shape != b_[k].shape
                                     or a_[k].tobytes() != b_[k].tobytes() for k in a_):
        errs.append("rest_seams arrays differ between cpu and cuda")
    print(f"seams: {len(lids)} layers, {len(a_['seam_a'])} pairs; cpu {secs['seams_cpu']:.1f} s, "
          f"cuda {secs['seams_cuda']:.1f} s")
    # repair.seamWeld's form: faces=True (each side's drawing face) and load= (the recipe's in-memory Stage), here fed
    # the staged files' own arrays: the seam arrays must equal faces=False / file reads, and the face arrays must
    # agree between the devices
    def _load(k, name):
        v, _, _, subs = S.read_bin(S.STAGE / k / f"{name}.bytes")
        return np.asarray(v), np.concatenate(subs).reshape(-1, 3).astype(np.int64)
    farr = {dev: SEAMS.rest_seams(sc, S, rows, srep, lids, device=dev, load=_load, faces=True) for dev in ("cpu", "cuda")}
    for dev in ("cpu", "cuda"):
        if any(farr[dev][k].tobytes() != sarr[dev][k].tobytes() for k in sarr[dev]):
            errs.append(f"rest_seams(faces=True, load=) seam arrays differ from the file read ({dev})")
    if farr["cpu"]["seam_face_bins"] != farr["cuda"]["seam_face_bins"] or any(
            farr["cpu"][k].tobytes() != farr["cuda"][k].tobytes() for k in ("seam_face_bin", "seam_face")):
        errs.append("rest_seams face arrays differ between cpu and cuda")
    for e in errs:
        print("FAIL", e)
    print(f"{a.faction}/{a.candidate} state {a.state}: {len(cams)} poses, {len(F)} faces; cpu {secs['cpu']:.1f} s, "
          f"cuda {secs['cuda']:.1f} s; pass {reps['cpu']['summary']['pass']}, "
          f"maxVisibleBehindPx {reps['cpu']['summary']['maxVisibleBehindPx']}, faces_out {len(hits['cpu'])}")
    if errs:
        return 1
    shutil.rmtree(dc, ignore_errors=True)
    shutil.rmtree(dg, ignore_errors=True)
    print("town gpu kernels parity OK")
    return 0


# a passing scene (the installed castle candidate) and a failing one (visible behind components, so the component,
# attribution and faces_out paths carry real data: 1707 px, 200 faces at these poses on 2026-10-01)
CASES = ("castle/zs_v8", "castle/rx_ldi_zone_old_nfix")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--case", action="append", help="faction/candidate (repeatable; default: %s)" % ", ".join(CASES))
    ap.add_argument("--state", default="full")
    ap.add_argument("--loop", type=int, default=4)
    ap.add_argument("--inner", default="", help=argparse.SUPPRESS)
    a = ap.parse_args()
    if a.inner:
        a.faction, a.candidate = a.inner.split("/", 1)
        return run(a)
    rc = 0
    for case in a.case or CASES:
        env = {**os.environ, "TOWN_FULL3D_FACTION": case.split("/", 1)[0], "TOWN_FULL3D_CANDIDATE": case.split("/", 1)[1]}
        env.pop("STRONGHOLD_FULL3D_CANDIDATE", None)
        env.pop("TOWN_FULL3D_DEVICE", None)
        rc |= subprocess.run([sys.executable, str(Path(__file__).resolve()), "--inner", case, "--state", a.state,
                              "--loop", str(a.loop)], env=env).returncode
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
