"""Measure our DEF-retarget idle cadence from built GLBs (read-only).

    python tools/homm3_idle_cadence/measure_glb_idles.py --out artifacts/homm3_idle_cadence/ours_idles.json [unit ...]
    python tools/homm3_idle_cadence/measure_glb_idles.py --glb path/to/x.glb --out x.json

Default set: every artifacts/homm3_def_retarget/<unit>/<unit>_def_retarget.glb. Measures the
`Unit_Idle` animation with the same `idle_metrics.cadence` rule as the native extractor. Also
records the key count and key spacing, so the DEF frame rate the clip was baked at is visible.
In game the clip plays through the native base controller's idle state (speed 1.0 x
`battleSlowIdle`, the same multiplier native idles get); the plugin does not rescale battle
idle playback, so the GLB length is the in-game loop period at battleSlowIdle = 1.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from glb_anim import accessor, animation, read_glb, sample_rotations  # noqa: E402
from idle_metrics import cadence, summarize  # noqa: E402

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
CLIP = "Unit_Idle"


def measure(path: str, clip: str = CLIP) -> dict:
    js, bn = read_glb(path)
    an = animation(js, clip)
    s0 = max(an["samplers"], key=lambda s: js["accessors"][s["input"]]["count"])
    keys = accessor(js, bn, s0["input"])[:, 0]
    rots, length = sample_rotations(js, bn, clip)
    m = cadence(rots, length)
    steps = np.diff(keys)
    return {"glb": os.path.relpath(path, ROOT).replace("\\", "/"), "clip": clip, "keys": int(len(keys)),
            "keyStepS": round(float(np.median(steps)), 4) if len(steps) else None,
            "interpolation": s0.get("interpolation", "LINEAR"), **m}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("units", nargs="*")
    ap.add_argument("--glb", action="append", default=[])
    ap.add_argument("--clip", default=CLIP)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    paths = list(args.glb)
    if not paths:
        units = args.units or sorted(os.path.basename(os.path.dirname(p)) for p in glob.glob(
            os.path.join(ROOT, "artifacts/homm3_def_retarget/*/*_def_retarget.glb")))
        paths = [os.path.join(ROOT, f"artifacts/homm3_def_retarget/{u}/{u}_def_retarget.glb") for u in units]
    rows, errors = [], []
    for p in paths:
        try:
            r = measure(p, args.clip)
        except Exception as e:  # recorded, not hidden: a unit without Unit_Idle is listed as an error
            errors.append({"glb": p, "error": f"{type(e).__name__}: {e}"})
            print("ERR", p, e, flush=True)
            continue
        rows.append(r)
        print(r["glb"], r["lengthS"], r["keys"], r["beats"], r["angSpeedDegS"], flush=True)
    rep = {"schema": "homm3_idle_cadence.ours.v1", "clip": args.clip,
           "summary": {k: summarize(rows, k) for k in ("lengthS", "beats", "beatPeriodS", "angSpeedDegS",
                                                        "peakAngSpeedDegS", "amplitudeDeg", "keys")},
           "clips": rows, "errors": errors}
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    json.dump(rep, open(args.out, "w"), indent=1)
    print(json.dumps(rep["summary"], indent=1))


if __name__ == "__main__":
    main()
