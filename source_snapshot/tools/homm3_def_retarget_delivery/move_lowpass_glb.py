"""Low-pass a non-walker's Unit_Move rotations: the flier / strideExempt counterpart of strideMatch.highHarmonicKeep.

    python tools/homm3_def_retarget_delivery/move_lowpass_glb.py apply <unit> [--glb P]   (exit 3 = no moveLowPass)
    python tools/homm3_def_retarget_delivery/move_lowpass_glb.py check <glb...>

Why: stride_match_glb.py's highHarmonicKeep smooths only the channels its plant transform rewrites, and a HoMM3
flier or a strideExempt unit is never stride matched. A flier whose DEF Move is short (h3_genie_vizier: 5 frames,
a 0.417 s loop, fundamental 2.4 Hz) keeps the capture's own per-frame rotations, and the loop's second harmonic
(4.8 Hz) already sits above flyer_articulation.JITTER_CUTOFF_HZ, so the articulation gate reads it as jitter
(genie vizier p90 0.58, worst Head).

Opt-in per unit config (tools/homm3_def_retarget/units/<unit>.json), fail closed:
    "moveLowPass": {"highHarmonicKeep": k, "reason": "<why, with numbers>"}      0 < k < 1
Only for a HoMM3 flier (reference/homm3_fliers.json) or a strideExempt unit; a walker uses strideMatch instead.
Every looping LINEAR rotation channel of Unit_Move on the clip's key grid has its spectrum above the cutoff scaled
by k (stride_match_glb.keep_low_harmonics: sign-continuous, periodic over the loop key, renormalised). Other clips,
translations, scales, morph weights and STEP holds are untouched. A Move rotation channel that is on the key grid but
does not loop is refused. The gate is not changed: the result is measured again, and a k that leaves the gate
failing is still reported as failing by flyer_articulation.
Runs in fleet_rebuild.py after stride match and before densify (the DEF keys are smoothed, then splined).
Stamps asset.extras.homm3DefRetargetDeliveryMoveLowPass {highHarmonicKeep, reason, cutoffHz, channels,
jitterP90Before/After, sourceGlbSha256}; an already stamped GLB is refused.
Proof tier: generated artifact. Nothing here builds a bundle or touches the game.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
from flyer_articulation import JITTER_CUTOFF_HZ, glb_clips  # noqa: E402
from stride_match_glb import (MOVE, Glb, keep_low_harmonics, unit_flier, unit_stride_exempt,  # noqa: E402
                              write_channels)

STAMP = "homm3DefRetargetDeliveryMoveLowPass"
OPTION_KEYS = {"highHarmonicKeep", "reason"}


def unit_lowpass_options(unit: str) -> dict:
    """The unit config's "moveLowPass" ({} when absent); fail closed on anything else."""
    cfg = json.loads((ROOT / "tools/homm3_def_retarget/units" / f"{unit}.json").read_text(encoding="utf-8"))
    opt = cfg.get("moveLowPass")
    if opt is None:
        return {}
    if not isinstance(opt, dict) or set(opt) != OPTION_KEYS:
        raise SystemExit(f"{unit}: moveLowPass must be {{highHarmonicKeep, reason}}, got {opt}")
    k = opt["highHarmonicKeep"]
    if isinstance(k, bool) or not isinstance(k, (int, float)) or not 0.0 < float(k) < 1.0:
        raise SystemExit(f"{unit}: moveLowPass.highHarmonicKeep must be in (0, 1), got {k}")
    if not (isinstance(opt["reason"], str) and opt["reason"].strip()):
        raise SystemExit(f"{unit}: moveLowPass needs a non-empty reason")
    if not (unit_flier(unit) or unit_stride_exempt(unit)):
        raise SystemExit(f"{unit}: moveLowPass is for HoMM3 fliers and strideExempt units; a walker uses "
                         "strideMatch.highHarmonicKeep")
    return {"highHarmonicKeep": float(k), "reason": opt["reason"]}


def lowpass_move(g: Glb, keep: float) -> list[int]:
    """Scale Unit_Move's looping rotation channels above the cutoff by keep, in place; returns the nodes changed."""
    a = g.anim(MOVE)
    grid = g.key_grid(MOVE)
    targets, exact = {}, None
    for ch in a["channels"]:
        s = a["samplers"][ch["sampler"]]
        if ch["target"]["path"] != "rotation" or s.get("interpolation", "LINEAR") != "LINEAR":
            continue
        kt = g.read(s["input"])[:, 0]
        if len(kt) <= 2:
            continue
        if len(kt) != len(grid) or not np.allclose(kt, grid, atol=1e-5):
            raise SystemExit(f"{MOVE}: rotation channel of node {ch['target']['node']} is off the clip's key grid")
        v = np.array(g.read(s["output"]), float)
        if abs(abs(float(np.dot(v[0], v[-1]))) - 1.0) > 1e-4:
            raise SystemExit(f"{MOVE}: rotation channel of node {ch['target']['node']} does not loop "
                             "(last key != first); the periodic low-pass would put a seam in it")
        targets[(ch["target"]["node"], "rotation")] = v
        # the rewritten keys go back on the channels' own float32 times: key_grid rounds to 1e-6, and a grid one ULP
        # off the untouched channels doubles the clip's union grid for every later stage (2026-10-01 hota_cove_halcyon:
        # ground saw 59 Move times instead of 31, and the freeze gate read the clip as resampled)
        if exact is None:
            exact = kt
        elif not np.array_equal(kt, exact):
            raise SystemExit(f"{MOVE}: rotation channels disagree on their key times (node {ch['target']['node']})")
    if not targets:
        raise SystemExit(f"{MOVE}: no looping rotation channel to low-pass")
    keep_low_harmonics(targets, grid, float(grid[-1] - grid[0]), keep)
    write_channels(g, a, np.asarray(exact, np.float64), targets)
    return sorted(n for n, _ in targets)


def canonical_glb(unit: str) -> Path:
    return ROOT / "artifacts/homm3_def_retarget" / unit / f"{unit}_def_retarget.glb"


def apply_bytes(unit: str, data: bytes, p: Path):
    """The Move low-pass stage on GLB bytes, in memory: a stage_sidecar.StageResult whose sidecar names `p` (the GLB
    it rewrites in place), or None when the unit config has no "moveLowPass"."""
    opt = unit_lowpass_options(unit)
    if not opt:
        return None
    g = Glb(data)
    if STAMP in g.json.get("asset", {}).get("extras", {}):
        raise SystemExit(f"{unit}: Move already low-passed")
    src = g.raw
    before = glb_clips(src).get(MOVE, {}).get("jitterP90")
    nodes = lowpass_move(g, opt["highHarmonicKeep"])
    mid = g.to_bytes()
    after = glb_clips(mid).get(MOVE, {}).get("jitterP90")
    g2 = Glb(mid)
    g2.json.setdefault("asset", {}).setdefault("extras", {})[STAMP] = {
        "schema": "homm3_def_retarget_move_lowpass.v1", "tool": "tools/homm3_def_retarget_delivery/move_lowpass_glb.py",
        "clip": MOVE, "highHarmonicKeep": opt["highHarmonicKeep"], "reason": opt["reason"], "cutoffHz": JITTER_CUTOFF_HZ,
        "channels": len(nodes), "jitterP90Before": before, "jitterP90After": after,
        "sourceGlbSha256": hashlib.sha256(src).hexdigest(),
        "proof": "generated artifact: Move rotation keys low-passed offline; not built into a bundle, not in game"}
    out = g2.to_bytes()
    import stage_sidecar
    return stage_sidecar.result(
        out, src, "move_lowpass", stage_sidecar.record("homm3_def_retarget_move_lowpass.v1", unit, p,
                                                       hashlib.sha256(src).hexdigest(), hashlib.sha256(out).hexdigest()),
        {"unit": unit, "out": str(p), "highHarmonicKeep": opt["highHarmonicKeep"], "channels": len(nodes),
         "jitterP90Before": before, "jitterP90After": after})


def cmd_apply(args) -> int:
    if not unit_lowpass_options(args.unit):
        print(json.dumps({"unit": args.unit, "skipped": "no moveLowPass"}))
        return 3
    p = Path(args.glb or canonical_glb(args.unit))
    r = apply_bytes(args.unit, p.read_bytes(), p)
    import stage_sidecar
    stage_sidecar.commit(p, r)
    print(json.dumps(r.report))
    return 0


def cmd_check(args) -> int:
    bad = 0
    for p in args.glbs:
        st = Glb.load(Path(p)).json.get("asset", {}).get("extras", {}).get(STAMP)
        ok = bool(st) and 0.0 < float(st.get("highHarmonicKeep", 0)) < 1.0 and bool(str(st.get("reason", "")).strip())
        print(json.dumps({"glb": p, "ok": ok, "stamp": st}))
        bad += not ok
    return 1 if bad else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("apply")
    s.add_argument("unit")
    s.add_argument("--glb", type=Path, help="input GLB, rewritten in place (default: the canonical def_retarget GLB)")
    s = sub.add_parser("check")
    s.add_argument("glbs", nargs="+")
    args = ap.parse_args(argv)
    return cmd_apply(args) if args.cmd == "apply" else cmd_check(args)


if __name__ == "__main__":
    sys.exit(main())
