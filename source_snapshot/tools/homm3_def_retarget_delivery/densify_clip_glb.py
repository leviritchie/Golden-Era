"""Resample a DEF-retarget GLB clip onto more keys with a cubic spline, so a 4-frame DEF beat plays as a smooth
curve in Unity and reaches the peak its DEF keys already hold.

    python tools/homm3_def_retarget_delivery/densify_clip_glb.py apply <unit> [--glb P]
    python tools/homm3_def_retarget_delivery/densify_clip_glb.py check <glb...>

Why: the retarget exports one key per DEF frame. A griffin's Move is four DEF frames (level, down, level, up) plus
the loop key, and Unity interpolates linearly between them, so the flap is a zig-zag whose samples between keys
never reach the keyed amplitude (flyer_articulation.py sees 58.4 deg on a 65 deg key). Raising the keyed amplitude
to beat that would push the wing past what the DEF shows; more keys fix the curve instead.

Opt-in per unit config (tools/homm3_def_retarget/units/<unit>.json):
    "deliveryDensify": {"clips": ["Move"], "keysPerSpan": 3}
  clips        contract suffixes (Unit_<clip>) to resample
  keysPerSpan  new intervals per original key interval; every original key time is kept, so every keyed pose,
               including the flap peak, is reproduced exactly
Every LINEAR channel of the clip (rotation, translation, scale, morph weights) is resampled on the same grid.
A channel whose first and last key agree (a loop) uses a periodic spline; any other channel uses not-a-knot.
Rotations are splined per component on a sign-continuous quaternion track and renormalised. STEP channels (the
exporter's constant two-key holds) are left as they are; a CUBICSPLINE channel or an already densified GLB is
refused (fail closed); other clips are untouched.
Stamps asset.extras.homm3DefRetargetDeliveryDensify {clips, keysPerSpan, keysBefore/After, sourceGlbSha256}.
`check` re-reads a stamped GLB and fails when a clip's key count no longer matches its stamp.
The stamp is also the slice probe's record of which keys are DEF steps: ship_def_retarget_slice.py probe reads
only keys 0, keysPerSpan, 2*keysPerSpan, ... of a densified clip (the in-between keys hold spline-blended morph
weights) and refuses a unit whose config and stamp disagree, so keep the original keys on that stride.
Proof tier: generated artifact. Nothing here builds a bundle or touches the game.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
from scipy.interpolate import CubicSpline

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
from stride_match_glb import Glb  # noqa: E402

STAMP = "homm3DefRetargetDeliveryDensify"
UNITS = ROOT / "tools/homm3_def_retarget/units"
LOOP_TOL = 1e-4


def unit_spec(unit: str) -> dict | None:
    cfg = json.loads((UNITS / f"{unit}.json").read_text(encoding="utf-8"))
    spec = cfg.get("deliveryDensify")
    if spec is None:
        return None
    if not spec.get("clips") or int(spec.get("keysPerSpan", 0)) < 2:
        raise SystemExit(f"{unit}: deliveryDensify needs clips and keysPerSpan >= 2, got {spec}")
    return {"clips": list(spec["clips"]), "keysPerSpan": int(spec["keysPerSpan"])}


def dense_grid(kt: np.ndarray, per: int) -> np.ndarray:
    out = [kt[0]]
    for a, b in zip(kt[:-1], kt[1:]):
        out.extend(a + (b - a) * np.arange(1, per + 1) / per)
    return np.array(out)


def spline(kt: np.ndarray, kv: np.ndarray, grid: np.ndarray) -> np.ndarray:
    periodic = len(kt) >= 3 and np.allclose(kv[0], kv[-1], atol=LOOP_TOL)
    if periodic:
        kv = kv.copy()
        kv[-1] = kv[0]
    if len(kt) < 3:
        return np.stack([np.interp(grid, kt, kv[:, c]) for c in range(kv.shape[1])], axis=1)
    return CubicSpline(kt, kv, axis=0, bc_type="periodic" if periodic else "not-a-knot")(grid)


def densify_clip(g: Glb, name: str, per: int) -> dict:
    a = g.anim(name)
    if any(s.get("interpolation", "LINEAR") == "CUBICSPLINE" for s in a["samplers"]):
        raise SystemExit(f"{name}: CUBICSPLINE samplers cannot be densified")
    grids, before, after = {}, set(), set()
    new_input, new_output = {}, {}
    for si, s in enumerate(a["samplers"]):
        if s.get("interpolation", "LINEAR") != "LINEAR":
            continue
        kt = g.read(s["input"])[:, 0]
        kv = g.read(s["output"])
        before.add(len(kt))
        if len(kt) < 2:
            continue
        key = tuple(np.round(kt, 7))
        if key not in grids:
            grids[key] = dense_grid(kt, per)
        grid = grids[key]
        path = next(ch["target"]["path"] for ch in a["channels"] if ch["sampler"] == si)
        if path == "weights":
            n = kv.shape[0] // len(kt)
            dv = spline(kt, kv.reshape(len(kt), n), grid).reshape(-1, 1)
            dv = np.clip(dv, 0.0, 1.0)
        elif path == "rotation":
            q = kv.copy()
            for c in range(1, len(q)):
                if np.dot(q[c], q[c - 1]) < 0:
                    q[c] = -q[c]
            dv = spline(kt, q, grid)
            dv /= np.linalg.norm(dv, axis=1, keepdims=True)
        else:
            dv = spline(kt, kv, grid)
        typ = {1: "SCALAR", 3: "VEC3", 4: "VEC4"}[dv.shape[1]]
        new_input[si] = (key, grid)
        new_output[si] = (dv, typ)
        after.add(len(grid))
    shared = {}
    for si, (key, grid) in new_input.items():
        if key not in shared:
            shared[key] = g.append_accessor(grid.reshape(-1, 1), "SCALAR")
        a["samplers"][si]["input"] = shared[key]
        dv, typ = new_output[si]
        a["samplers"][si]["output"] = g.append_accessor(dv, typ)
    return {"keysBefore": sorted(before), "keysAfter": sorted(after)}


def canonical_glb(unit: str) -> Path:
    return ROOT / "artifacts/homm3_def_retarget" / unit / f"{unit}_def_retarget.glb"


def apply_bytes(unit: str, data: bytes, p: Path):
    """The densify stage on GLB bytes, in memory: a stage_sidecar.StageResult whose sidecar names `p` (the GLB it
    rewrites in place), or None when the unit config has no "deliveryDensify"."""
    spec = unit_spec(unit)
    if spec is None:
        return None
    g = Glb(data)
    src = g.raw
    if STAMP in g.json.get("asset", {}).get("extras", {}):
        raise SystemExit(f"{unit}: already densified")
    rep = {f"Unit_{c}": densify_clip(g, f"Unit_{c}", spec["keysPerSpan"]) for c in spec["clips"]}
    stamp = {"schema": "homm3_def_retarget_densify.v1", "tool": "tools/homm3_def_retarget_delivery/densify_clip_glb.py",
             "keysPerSpan": spec["keysPerSpan"], "clips": rep, "sourceGlbSha256": hashlib.sha256(src).hexdigest(),
             "proof": "generated artifact: clip keys resampled offline; not built into a bundle, not in game"}
    g.json.setdefault("asset", {}).setdefault("extras", {})[STAMP] = stamp
    out = g.to_bytes()
    import stage_sidecar
    osha = hashlib.sha256(out).hexdigest()
    return stage_sidecar.result(
        out, src, "densify", stage_sidecar.record("homm3_def_retarget_densify.v1", unit, p, stamp["sourceGlbSha256"], osha),
        {"unit": unit, "out": str(p), "glbSha256": osha, **stamp})


def cmd_apply(args) -> int:
    if unit_spec(args.unit) is None:
        print(json.dumps({"unit": args.unit, "skipped": "no deliveryDensify in the unit config"}))
        return 3
    p = Path(args.glb or canonical_glb(args.unit))
    r = apply_bytes(args.unit, p.read_bytes(), p)
    import stage_sidecar
    stage_sidecar.commit(p, r)
    print(json.dumps(r.report, indent=1))
    return 0


def check_glb(p: Path) -> dict:
    g = Glb.load(p)
    st = g.json.get("asset", {}).get("extras", {}).get(STAMP)
    if not st:
        return {"glb": str(p), "ok": False, "reason": f"no {STAMP} stamp"}
    bad = []
    for name, rec in st["clips"].items():
        n = sorted({len(g.read(s["input"])) for s in g.anim(name)["samplers"]
                    if s.get("interpolation", "LINEAR") == "LINEAR" and len(g.read(s["input"])) >= 2})
        if n != [x for x in rec["keysAfter"]]:
            bad.append(f"{name}: keys {n} != stamp {rec['keysAfter']}")
    return {"glb": str(p), "ok": not bad, "problems": bad}


def cmd_check(args) -> int:
    bad = 0
    for p in args.glbs:
        r = check_glb(Path(p))
        print(json.dumps(r))
        bad += not r["ok"]
    return 1 if bad else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("apply")
    s.add_argument("unit")
    s.add_argument("--glb", type=Path, help="GLB to rewrite in place (default: the canonical def_retarget GLB)")
    s = sub.add_parser("check")
    s.add_argument("glbs", nargs="+")
    args = ap.parse_args(argv)
    return {"apply": cmd_apply, "check": cmd_check}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
