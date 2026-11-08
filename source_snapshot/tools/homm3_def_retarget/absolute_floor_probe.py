"""Absolute-floor probe for a delivered DEF-retarget GLB: how far each clip's skinned body goes below the world floor.

    python tools/homm3_def_retarget/absolute_floor_probe.py <unit|path.glb> [...] [--clips Unit_Idle,...] [--json out.json]

Why (2026-09-29, griffin / dragon polish): the fleet's ground gate (homm3_def_retarget_delivery/ground_check.py)
measures every clip against Unit_Idle key 0's own lowest vertex. A unit whose Idle key 0 is itself sunk or
floating is its own reference, so it passes. Measured on the accepted green dragon: every ground clip had its feet
and tail 0.08-0.12 of its height below y = 0, and ground_check passed. This probe reports the other half: per
Unit_ clip, the lowest skinned vertex (rubble-owned vertices excluded, as ground_check) relative to the WORLD floor
y = 0 (glTF +Y up), as a fraction of the Idle key-0 height. At the worst key it also names the bones that own the
vertices below -tol, so a tail curl dipping can be told from feet sinking.

Report only: it never fails a build (exit 0 with a report; exit 1 only when a GLB cannot be read). It is NOT wired
into fleet_rebuild / freeze as a gate. The fleet-wide debt is sized first (main, 2026-09-29).
Proof tier: generated artifact (read-only measurement of built GLBs).
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "tools/homm3_def_retarget_delivery"))

DEFAULT_TOL = 0.01          # fraction of the Idle key-0 height; below -tol a vertex counts as under the floor


def dominant_owners(J: np.ndarray, W: np.ndarray, names: list[str], mask: np.ndarray, top: int = 6) -> dict:
    """{bone: vertex count} over the masked vertices, each vertex counted for its highest-weight joint."""
    if not mask.any():
        return {}
    dom = J[mask, np.argmax(W[mask], axis=1)]
    return dict(Counter(names[int(j)] for j in dom).most_common(top))


def clip_floor(lows_abs: list[float], H: float) -> dict:
    """Worst (lowest) key of one clip: {"minAbs": fraction of H below/above y = 0, "worstKey": index}."""
    k = int(np.argmin(lows_abs))
    return {"minAbs": round(float(lows_abs[k]) / H, 4), "worstKey": k}


def resolve(arg: str) -> tuple[str, Path]:
    p = Path(arg)
    if p.suffix.lower() == ".glb":
        return p.stem.replace("_def_retarget", "").replace("_idle_retimed", ""), p
    return arg, ROOT / "artifacts/homm3_def_retarget" / arg / f"{arg}_def_retarget.glb"


def probe(glb: Path, clips: list[str] | None = None, tol: float = DEFAULT_TOL) -> dict:
    from def_wing_calibrate import Rig
    from stride_match_glb import Glb, rubble_nodes

    g = Glb.load(glb)
    rubble = rubble_nodes(g.names, g.parent)

    def samples(clip):
        anim = g.anim(clip)
        times = np.unique(np.concatenate([g.read(anim["samplers"][ch["sampler"]]["input"])[:, 0]
                                          for ch in anim["channels"]]))
        return g.world(g.sample_local(clip, times)), times

    def skinned(rig, wm, k):
        jm = np.stack([wm[j][k] for j in rig.joints])
        rub = np.array([j in rubble for j in rig.joints])
        keep = ~(rub[rig.J] * (rig.W > 0.5)).any(1)
        return rig.skin(jm), keep

    ri = Rig(glb, "Unit_Idle")
    iw, it = samples("Unit_Idle")
    V0, keep0 = skinned(ri, iw, 0)
    y0 = V0[keep0, 1]
    H = float(y0.max() - y0.min())
    out = {"glb": str(glb), "idleHeight": round(H, 4), "idleFloorAbs": round(float(y0.min()) / H, 4),
           "tol": tol, "clips": {}}
    names = [a["name"] for a in ri.js["animations"] if a["name"].startswith("Unit_")]
    for c in (clips or names):
        if c not in names:
            out["clips"][c] = {"missing": True}
            continue
        r = ri if c == "Unit_Idle" else Rig(glb, c)
        wm, times = (iw, it) if c == "Unit_Idle" else samples(c)
        lows = []
        for k in range(len(times)):
            V, keep = skinned(r, wm, k)
            lows.append(float(V[keep, 1].min()))
        rec = clip_floor(lows, H)
        V, keep = skinned(r, wm, rec["worstKey"])
        rec["below"] = dominant_owners(r.J, r.W, r.names, keep & (V[:, 1] < -tol * H))
        out["clips"][c] = rec
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("units", nargs="+", help="unit id (its canonical delivered GLB) or a .glb path")
    ap.add_argument("--clips", default="", help="comma list of Unit_ clips (default: every Unit_ clip)")
    ap.add_argument("--tol", type=float, default=DEFAULT_TOL)
    ap.add_argument("--json")
    a = ap.parse_args(argv)
    clips = [c for c in a.clips.split(",") if c] or None
    rep = {}
    for arg in a.units:
        unit, glb = resolve(arg)
        if not glb.is_file():
            print(f"{unit}: no GLB at {glb}", file=sys.stderr)
            return 1
        rep[unit] = probe(glb, clips, a.tol)
        print(f"{unit}  idle floor {rep[unit]['idleFloorAbs']:+.4f} of H={rep[unit]['idleHeight']}")
        for c, r in rep[unit]["clips"].items():
            if r.get("missing"):
                print(f"  {c:18s} missing")
                continue
            print(f"  {c:18s} minAbs {r['minAbs']:+.4f}  key {r['worstKey']:3d}  below: {r['below']}")
    if a.json:
        Path(a.json).write_text(json.dumps({"schema": "homm3_def_retarget.absolute_floor.v1",
                                            "proof": "generated artifact (read-only); report only, not a gate",
                                            "units": rep}, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
