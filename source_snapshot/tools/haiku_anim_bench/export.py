#!/usr/bin/env python3
"""Bake the bench's KEPT changes into a new GLB inside the experiment folder (export is NOT install).

    python tools/haiku_anim_bench/export.py [--unit h3_roc] [--name haiku] [--draft]

1. Rig state (kept mesh/rig ops: new joints, pivots, re-parenting, skin weights, rest shape, CS exclusion) replayed
   over work.glb by rig.RigEditor and written by rig_glb.build_rig_glb (new nodes/joints/IBMs, JOINTS_0/WEIGHTS_0,
   POSITION/NORMAL and morph targets if they changed, new joints' constant channels in every clip).
2. Pose edits baked by patch_glb's own op_key_rotations / op_key_translations (same semantics as the patch lane).
3. Parity (bench pose with the edits vs. the baked GLB, joints by name and skinned vertices) and the gate on EVERY clip
   (rig/weight changes touch all clips): the bench's per-edge rule (no edge past max(2x, 1.05 x its own original
   max) over the clip's key grid) and the lane's count/worst rule. A failing export is written only with --draft, as
   <unit>_<name>_DRAFT.glb; the final export must pass.
Writes V:/olden_port_work/haiku_anim/<unit>/export/: the GLB, lane_root/... key tables, glbpatch_ops_<name>.json,
export_report_<name>.json (incl. which kept ops the glbPatch lane can express today). Never writes outside it.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from anim_core import SCRATCH, Unit, gate_verdict, load_json  # noqa: E402

import patch_glb as PG  # noqa: E402  (anim_core put tools/homm3_glb_patch on sys.path)
from rig import EXPRESSIBLE, RigEditor  # noqa: E402
from rig_glb import build_rig_glb  # noqa: E402
from stride_match_glb import Glb, write_channels  # noqa: E402


def tables(u: Unit, edits: list[dict]) -> tuple[dict, dict]:
    """Per clip/bone grid-key offsets: anim_core.Unit.offsets (stack order, loop-seam bridge)."""
    rot, tr = {}, {}
    for clip in sorted({e["clip"] for e in edits}):
        grid = u.clips[clip]["grid"]
        rq, td = u.offsets(clip, edits)
        if rq:
            rot[clip] = {b: {"times": [float(x) for x in grid], "quat": np.round(q, 8).tolist()} for b, q in rq.items()}
        if td:
            tr[clip] = {b: {"times": [float(x) for x in grid], "delta": np.round(d, 8).tolist()} for b, d in td.items()}
    return rot, tr


def edge_max(u: Unit, clip: str, edges, edits=()) -> tuple[np.ndarray, dict]:
    """CPU per-edge max stretch over the clip's key grid (+ the lane's count/worst summary)."""
    grid = u.clips[clip]["grid"]
    _, Jm, mw = u.pose(clip, grid, list(edits))
    Y = u.skin_cpu(Jm, mw)
    rl = np.maximum(np.linalg.norm(u.scene.P[edges[:, 0]] - u.scene.P[edges[:, 1]], axis=1), 1e-9)
    r = np.linalg.norm(Y[:, edges[:, 0]] - Y[:, edges[:, 1]], axis=2) / rl
    return r.max(0), {"edgesOver2x": int((r > PG.STRETCH_RATIO).sum()), "worst": round(float(r.max()), 3)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--unit", default="h3_roc")
    ap.add_argument("--name", default="haiku")
    ap.add_argument("--stack", default=None, help="stack.json to export (default: the live one)")
    ap.add_argument("--draft", action="store_true", help="write the GLB even if the gate fails (as *_DRAFT.glb)")
    a = ap.parse_args()
    work = SCRATCH / a.unit
    st = load_json(Path(a.stack) if a.stack else work / "stack.json", None)
    if not st or not (st.get("kept") or st.get("mops")):
        raise SystemExit("no kept changes in the stack")
    kept, mops = st.get("kept", []), st.get("mops", [])
    out = work / "export"
    lane_root = out / "lane_root"            # mirrors the repo layout, so the lane's own loaders run unmodified
    tdir = lane_root / PG.KEY_ROT_DIR
    tdir.mkdir(parents=True, exist_ok=True)
    base = Unit(a.unit, work / "work.glb")   # pristine reference for the gate
    u = Unit(a.unit, work / "work.glb")
    rig = RigEditor(u)
    reps_rig = rig.apply([{k: v for k, v in m.items() if k not in ("id", "why")} for m in mops]) if mops else []
    rot, tr = tables(u, kept)
    stem = f"{a.unit}_{a.name}"
    ops = []
    if rot:
        raw = json.dumps({"schema": PG.KEY_ROT_SCHEMA, "unit": a.unit, "source": "haiku_anim_bench", "clips": rot},
                         indent=1).encode()
        (tdir / f"{stem}.json").write_bytes(raw)
        ops.append({"op": "keyRotations", "table": f"{PG.KEY_ROT_DIR}/{stem}.json", "sha256": PG.sha(raw),
                    "regrid": True, "note": "haiku_anim_bench kept edits"})
    if tr:
        raw = json.dumps({"schema": PG.KEY_TR_SCHEMA, "unit": a.unit, "source": "haiku_anim_bench", "clips": tr},
                         indent=1).encode()
        (tdir / f"{stem}_tr.json").write_bytes(raw)
        ops.append({"op": "keyTranslations", "table": f"{PG.KEY_ROT_DIR}/{stem}_tr.json", "sha256": PG.sha(raw),
                    "regrid": True, "note": "haiku_anim_bench kept root edits"})
    def fresh():
        return build_rig_glb((work / "work.glb").read_bytes(), u, rig) if mops else Glb((work / "work.glb").read_bytes())
    g = fresh()
    reps, real_root, lane_refused = [], PG.ROOT, None
    PG.ROOT = lane_root
    try:
        for op in ops:
            reps.append(PG.op_key_rotations(g, op) if op["op"] == "keyRotations" else PG.op_key_translations(g, op, u.H))
    except (Exception, SystemExit) as e:  # noqa: BLE001  (the lane raises SystemExit on its limits; big free-form edits can pass the lane's per-key table limits)
        lane_refused = f"{type(e).__name__}: {e}"
    finally:
        PG.ROOT = real_root
    if lane_refused:
        # direct bake: the bench's own edited channels (same math the bench and viewer use), written per clip
        g = fresh()
        anims = {an.get("name"): an for an in g.json.get("animations", [])}
        for clip in sorted({e["clip"] for e in kept}):
            base_ch = u.scene.channels[clip]
            groups = {}
            for path, nd, ti, vo, it in u.edited_channels(clip, kept):
                if any(ch[2] is ti and ch[3] is vo for ch in base_ch):
                    continue
                groups.setdefault((np.asarray(ti).tobytes(), it), (ti, {}))[1][(nd, path)] =                     np.asarray(vo, np.float64).reshape(len(ti), -1)
            for (_, it), (ti, targets) in groups.items():
                write_channels(g, anims[clip], np.asarray(ti, np.float64), targets, it)
        g = Glb(g.to_bytes())
        reps = [{"directBake": True, "laneRefused": lane_refused}]
    tmp = out / f"{stem}.tmp.glb"
    tmp.write_bytes(g.to_bytes())

    # parity + gate on every clip: the baked GLB must pose exactly like the bench (rig state + edits on the fly)
    v = Unit(a.unit, tmp)
    par, gates, ok = {}, {}, True
    E = base.edges
    for clip in sorted(u.clips):
        c = u.clips[clip]
        t = np.linspace(c["start"], c["end"], 3 * c["n"])
        Gb, Jb, mb = u.pose(clip, t, kept)
        Gx, Jx, mx = v.pose(clip, t, [])
        jn = [n for n in u.jnames if n in v.names]
        ib, ix = [u.names.index(n) for n in jn], [v.names.index(n) for n in jn]
        jerr = float(np.abs(Gb[:, ib, :3, 3] - Gx[:, ix, :3, 3]).max() / u.H)
        verr = float(np.abs(u.skin_cpu(Jb[::3], mb[::3]) - v.skin_cpu(Jx[::3], mx[::3])).max() / u.H)
        par[clip] = {"joints": round(jerr, 8), "vertices": round(verr, 8)}
        b_e, b_s = edge_max(base, clip, E)
        o_e, o_s = edge_max(v, clip, E)
        thr = np.where(b_e > PG.STRETCH_RATIO, b_e * 1.05, PG.STRETCH_RATIO)
        new = int((o_e > thr).sum())
        lane = gate_verdict(b_s, o_s)
        gates[clip] = {"newDefectEdges": new, "laneGate": lane["ok"], "laneWhy": lane["why"], "base": b_s, "out": o_s}
        ok &= new == 0 and lane["ok"] and jerr < 1e-4 and verr < 1e-3
    final = out / (f"{stem}.glb" if ok else f"{stem}_DRAFT.glb")
    if ok or a.draft:
        tmp.replace(final)
    else:
        tmp.unlink()
    expr = [{"op": {k: v2 for k, v2 in m.items() if k not in ("why",)}, "glbPatch": EXPRESSIBLE[m.get("fix") or m.get("do")],
             "laneOp": r.get("laneOp")} for m, r in zip(mops, reps_rig)]
    rep = {"glb": str(final) if (ok or a.draft) else None, "passed": ok,
           "sha256": hashlib.sha256(final.read_bytes()).hexdigest() if (ok or a.draft) else None,
           "ops": ops, "lane": reps, "laneRefused": lane_refused, "rigOps": reps_rig, "laneExpressibility": expr, "newJoints": rig.new_joints,
           "parityMaxErrOverH": par, "gate": gates, "kept": kept, "mops": mops,
           "caveats": ["no CS re-bake (the baked CS morphs are the original clip's)", "no DEF_Master sync",
                       "not installed; tables live in the experiment folder"]}
    (out / f"export_report_{a.name}.json").write_text(json.dumps(rep, indent=1), encoding="utf-8")
    (out / f"glbpatch_ops_{a.name}.json").write_text(json.dumps(ops, indent=1), encoding="utf-8")
    print(json.dumps({"glb": rep["glb"], "passed": ok, "parity": par,
                      "gate": {k: (g2["newDefectEdges"], g2["laneGate"]) for k, g2 in gates.items()},
                      "newJoints": rig.new_joints, "ops": [o["op"] for o in ops],
                      "laneRefused": lane_refused}, indent=1))
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
