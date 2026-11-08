"""Which units' DEFs carry persistent body fire, how much and where (volumetricFire calibration input).

For every unit-look spec: the DEF's standing group (2) is read and, per frame, the fire pixels are counted
with the volumetricFire rule (``opaque & luma >= minLuma & R - B >= minWarmth``). Warm colour alone also
flags gold and brown bodies, so a second test separates fire from warm paint: fire *flickers* in place, so
a fire pixel is also one whose colour changes between consecutive idle frames while it stays opaque
(``flicker``). ``defFireFraction`` is the mean over frames of fire px / opaque px; ``flickerFraction`` is
the mean over frame pairs of (fire & flickering & opaque in both) px / opaque px; the silhouette is split
into thirds by height (``bands``: top, middle, bottom share of the fire). Proof tier: generated artifact.

    python tools/homm3_unit_look/volfire_survey.py [--units a b ...] [--json out.json]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
import spec as S  # noqa: E402
import volfire  # noqa: E402

RULE = {"minLuma": 100, "minWarmth": 40}
FLICKER_RGB = 40          # summed |dRGB| between consecutive frames that counts as flicker


def survey(unit: str, rule=RULE, group=2, def_name=None) -> dict:
    dname = def_name or volfire.unit_frame_source(unit)
    n = volfire.group_len(dname, group)
    if not n:
        return {"unit": unit, "def": dname, "error": f"no group {group}"}
    frames = volfire.load_frames(dname, group, list(range(n)))
    ops = [f[..., 3] == 255 for f in frames]
    fires = [volfire.fire_mask(f, rule) for f in frames]
    frac = [float(fi.sum() / max(1, o.sum())) for fi, o in zip(fires, ops)]
    flick = []
    for i in range(n):
        j = (i + 1) % n
        both = ops[i] & ops[j]
        drgb = np.abs(frames[i][..., :3].astype(int) - frames[j][..., :3].astype(int)).sum(-1)
        flick.append(float((fires[i] & both & (drgb >= FLICKER_RGB)).sum() / max(1, ops[i].sum())))
    union = np.any(ops, 0)
    ys = np.nonzero(union.any(1))[0]
    y0, h = ys.min(), ys.max() - ys.min() + 1
    fsum = np.sum(fires, 0)
    bands = []
    for k in range(3):
        a, b = y0 + k * h // 3, y0 + (k + 1) * h // 3
        bands.append(float(fsum[a:b].sum()))
    tot = sum(bands) or 1.0
    return {"unit": unit, "def": dname, "idleFrames": n, "opaquePx": int(np.mean([o.sum() for o in ops])),
            "defFireFraction": round(float(np.mean(frac)), 3), "flickerFraction": round(float(np.mean(flick)), 3),
            "bands": [round(b / tot, 2) for b in bands]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--units", nargs="*")
    ap.add_argument("--json")
    a = ap.parse_args()
    units = a.units or sorted(p.stem for p in (S.ROOT / "tools/homm3_unit_look/units").glob("*.json"))
    rows = []
    for u in units:
        try:
            rows.append(survey(u))
        except Exception as ex:  # a unit without retarget frames or DEF is reported, not fatal
            rows.append({"unit": u, "error": f"{type(ex).__name__}: {ex}"})
    rows.sort(key=lambda r: -r.get("flickerFraction", -1))
    for r in rows:
        if "error" in r:
            print(f"{r['unit']:32s} ERROR {r['error']}")
        else:
            print(f"{r['unit']:32s} {Path(r['def']).name:14s} n={r['idleFrames']:2d} fire={r['defFireFraction']:.3f} "
                  f"flicker={r['flickerFraction']:.3f} bands(top/mid/bot)={r['bands']}")
    if a.json:
        Path(a.json).write_text(json.dumps(rows, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
