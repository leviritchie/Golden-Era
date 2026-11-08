"""Ground a delivered GLB against its DEF: the one grounding stage (rule: tools/homm3_def_retarget/grounding.py).

    python tools/homm3_def_retarget_delivery/ground_glb.py apply <unit> [--glb P] [--out P]
    python tools/homm3_def_retarget_delivery/ground_glb.py check <glb...>

Why here and not in build_unit.py: every stage that moves the body vertically (build, emphasis, stride match, move
low-pass, densify) runs before this one, so the delivered GLB is what gets grounded, and a unit that is already built
is grounded without a new Blender build (2026-09-27: a build-time step was undone by emphasis on h3_ogre Death, whose
landed body went from 0.000 to -0.073 of its height).

Per Unit_ clip, on one coherent time grid (every sampler's keys; ground_check.glb_ground, LINEAR/STEP only):
  lows   the skinned lowest vertex per time relative to Unit_Idle time 0, as fractions of the Idle height;
  DEF    the DEF clip's opaque bottom-row curve (grounding.def_curve), placed on the grid by clip phase: a clip whose
         last key closes the loop (last pose == first) maps its end to DEF frame 0, any other clip its end to the last
         DEF frame;
  rule   grounding.offsets unchanged: (c) entry into the DEF's first-frame band, (b) Death eased onto the floor,
         (a) lift-only clamp to min(0, DEF bottom), with the joint entry where (c) alone would step the Hips out of
         the gate's band (every clip but Idle). Unit config "groundContact" exemptions (grounding.exemption).
Applied as a world +Y translation of every joint child of the skin's Root joint (the whole body; Root stays), written
as new translation keys on the grid for those nodes only, in the track's own interpolation (LINEAR or STEP: a 1-frame
clip's held pose stays held), except that a constant STEP track under a varying offset is written LINEAR (the same
curve before the offset; a stepped offset would snap the body key to key). Every other channel keeps its sampler (checked).
Refuses: an already grounded GLB, a translation channel it would rewrite that is neither LINEAR nor STEP, an unknown interpolation
anywhere (ground_check), a skin whose top joint is not one "Root", a loop-closed clip the offsets would open, a
stride-stamped Move whose offsets lift a planted sole off the floor at a stance key (planted_sole_lift_errors), and an
output that fails ground_check.
Stamps asset.extras.homm3DefRetargetDeliveryGround {sourceGlbSha256, exemption, per-clip deltas, defSource} and writes
<glb>.ground.json beside it with the source and output sha. fleet_rebuild.py runs it after stride match / low-pass /
densify and before look; freeze_slice.py requires the stamp on the look-delivered GLB.
Proof tier: generated artifact (offline GLB edit); runtime unproven.
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
import ground_check as GC  # noqa: E402
from ground_check import GR  # noqa: E402
import stride_match_glb as SM  # noqa: E402
from stride_match_glb import Glb, write_channels  # noqa: E402

STAMP = "homm3DefRetargetDeliveryGround"
SCHEMA = "homm3_def_retarget_delivery_ground.v1"
EPS = 1e-6
LOOP_TOL = 1e-4


def canonical_glb(unit: str) -> Path:
    return ROOT / "artifacts/homm3_def_retarget" / unit / f"{unit}_def_retarget.glb"


def body_nodes(g: Glb) -> tuple[int, list[int]]:
    """(Root joint, its joint children): the offset moves the children, so Root's own keys never change."""
    skins = {g.nodes[i]["skin"] for i, n in enumerate(g.nodes) if "skin" in n and "mesh" in n}
    if len(skins) != 1:
        raise SystemExit(f"expected one skin shared by the skinned meshes, found {sorted(skins)}")
    joints = set(g.json["skins"][skins.pop()]["joints"])
    tops = [j for j in joints if g.parent.get(j) not in joints]
    if len(tops) != 1 or g.names[tops[0]] != "Root":
        extra = " (the glTF exporter adds neutral_bone for vertices with no weights: they would not move with the "             "body; fix the build's weights)" if "neutral_bone" in [g.names[j] for j in tops] else ""
        raise SystemExit(f"the skin's top joint must be one 'Root', found {[g.names[j] for j in tops]}{extra}")
    kids = [c for c in g.nodes[tops[0]].get("children", []) if c in joints]
    if not kids:
        raise SystemExit("the Root joint has no joint children to ground")
    return tops[0], kids


def channel_snapshot(g: Glb) -> dict:
    """{(clip, node, path): (interpolation, times, values)} for every channel of every animation."""
    out = {}
    for a in g.json.get("animations", []):
        for ch in a["channels"]:
            s = a["samplers"][ch["sampler"]]
            out[(a["name"], ch["target"]["node"], ch["target"]["path"])] = (
                s.get("interpolation", "LINEAR"), g.read(s["input"]), g.read(s["output"]))
    return out


def loop_closed(g: Glb, clip: str, times: np.ndarray) -> bool:
    loc = g.sample_local(clip, np.array([times[0], times[-1]]))
    return len(times) > 2 and all(np.abs(v[0] - v[1]).max() <= LOOP_TOL for trs in loc.values() for v in trs)


def def_on_grid(bottom: list, times: np.ndarray, closed: bool) -> np.ndarray:
    d = GR._fill(bottom)
    n = len(d)
    if n == 1 or len(times) == 1:
        return np.full(len(times), float(d[0]))
    u = (times - times[0]) / (times[-1] - times[0])
    if closed:   # the closing key is DEF frame 0 again
        return np.interp(u * n, np.arange(n + 1), np.r_[d, d[0]])
    return np.interp(u * (n - 1), np.arange(n), d)


def planted_sole_lift_errors(g: Glb, times: np.ndarray, lows, s: np.ndarray, H: float) -> list[str]:
    """For a stride-stamped Unit_Move: every key where a planted chain's sole is on the floor before grounding (within
    GROUND_TOL) and the offsets lift it more than GROUND_TOL off it -- the clamp stood some other geometry on the floor
    and left the stride plant floating, so the delivered walk skates (2026-09-28 hota_bulwark_shaman: robe hem and shin
    lifted 0.13 onto the floor at 37 of 45 keys, stride slip 0.12 -> 0.765). Names the bone owning the lowest vertex."""
    st = g.json.get("asset", {}).get("extras", {}).get(SM.STAMP)
    if not st:
        return []
    body = SM.skin_body(g)
    mats = g.world(g.sample_local("Unit_Move", times))
    heights = SM.skin_heights(body, mats, range(len(times)))
    low = heights.min(1)
    dom = body["J"][np.arange(len(body["J"])), body["W"].argmax(1)]
    chains = {c["name"]: c for c in SM.chains_of(g)}
    bad = []
    masks = {name: SM.sole_of(g, body, chains[name])[1] for name in SM.planted_chains(st)}
    soles = np.logical_or.reduce(list(masks.values()))
    for name, mask in masks.items():
        # the sole in ground_check's frame: the key's lowest point plus the sole's height above it
        sole = np.asarray(lows, float) + (heights[:, mask].min(1) - low) / H
        after = sole + s
        hit = np.flatnonzero((sole <= GR.GROUND_TOL) & (after > GR.GROUND_TOL))
        if len(hit):
            k = int(hit[np.argmax(after[hit])])
            other = np.where(soles, np.inf, heights[k])    # the geometry the clamp stood on the floor: no plant's sole
            bad.append(f"Move: planted {name} sole lifted to +{after[k]:.3f} at key {k} ({len(hit)} stance keys): the lowest "
                       f"other point there is {g.names[int(dom[int(other.argmin())])]}-owned geometry")
    return bad


def plan(unit: str, glb: Path | bytes, g: Glb) -> tuple[dict, dict]:
    """({clip: (times, offsets in Idle-height fractions, info)}, context). `glb`: the GLB g was read from, as a path or
    its bytes."""
    ex = GR.exemption(GC.unit_config(unit))
    curve = GC.def_ground_curve(unit)
    can = GR.canonical(curve)
    meas = GC.glb_ground(glb)
    out = {}
    for c, m in sorted(meas["clips"].items()):
        seg = can.get(c)
        if seg is None:
            raise SystemExit(f"{unit}: {c} has no DEF segment to ground against")
        times = np.asarray(m["times"], float)
        clip = f"Unit_{c}"
        closed = loop_closed(g, clip, times)
        d = def_on_grid(seg["bottom"], times, closed)
        if ex["all"]:
            s, info = np.zeros(len(times)), {"exempt": ex["all"]}
        else:
            # the gate judges the Hips at every clip's first frame but Idle's (its reference): joint entry there
            judged = c != "Idle"
            s, info = GR.offsets(m["lows"], d, c == "Death", ex["death"], loop=closed,
                                 hips0=m["hips0"] if judged else None,
                                 allow_hips=GR.hips_allowance(seg["bottom"], seg["top"]) if judged else None)
        if closed and abs(s[0] - s[-1]) > LOOP_TOL:
            raise SystemExit(f"{unit}: grounding would open the {clip} loop (offset {s[0]:+.4f} at the first key, "
                             f"{s[-1]:+.4f} at the closing key; {info}); the rule has no loop form")
        if c == "Move" and not ex["all"]:
            lifted = planted_sole_lift_errors(g, times, m["lows"], s, meas["H"])
            if lifted:
                raise SystemExit(f"{unit}: grounding would float the stride plant: {'; '.join(lifted)}; fix the Move pose "
                                 "upstream (the ground rule stands the lowest geometry on the floor)")
        info.update({"keys": len(times), "loopClosed": closed, "maxLift": round(float(s.max()), 4),
                     "maxDrop": round(float(s.min()), 4)})
        out[c] = (times, s, info)
    return out, {"exemption": ex, "H": meas["H"], "defSource": curve["source"]}


def apply_offsets(g: Glb, offsets: dict, H: float) -> list[str]:
    """Add offsets * H to the world height of Root's joint children, in place; returns the clips changed."""
    root, kids = body_nodes(g)
    changed = []
    for c, (times, s, _) in offsets.items():
        if np.abs(s).max() <= EPS:
            continue
        clip = f"Unit_{c}"
        a = g.anim(clip)
        interp = {k: "LINEAR" for k in kids}   # a node with no translation channel holds its rest: LINEAR is exact
        for ch in a["channels"]:
            if ch["target"]["node"] in kids and ch["target"]["path"] == "translation":
                it = a["samplers"][ch["sampler"]].get("interpolation", "LINEAR")
                if it not in ("LINEAR", "STEP"):
                    raise SystemExit(f"{clip}: {g.names[ch['target']['node']]} translation is {it}; ground_glb keeps "
                                     "LINEAR and STEP tracks only")
                if it == "STEP" and np.abs(np.diff(g.read(a["samplers"][ch["sampler"]]["output"]), axis=0)).max(
                        initial=0.0) <= EPS and np.abs(np.diff(s)).max(initial=0.0) > EPS:
                    # a constant STEP track (the exporter's held rest translation, two equal keys) is exactly
                    # the same curve as LINEAR; the offset is not constant, so writing it STEP would snap the body
                    # from key to key and leave an N-key STEP Unit_Idle that retime_idle rightly refuses
                    # (2026-09-28 hota_cove_oceanid Hips.translation: 2-key STEP -> 10-key STEP)
                    it = "LINEAR"
                interp[ch["target"]["node"]] = it
        local = g.sample_local(clip, times)
        wm = g.world(local)
        lin = wm[root][:, :3, :3]
        dy = np.zeros((len(times), 3))
        dy[:, 1] = s * H
        dl = np.linalg.solve(lin, dy[:, :, None])[:, :, 0]
        for it in sorted(set(interp.values())):   # a STEP track stays STEP (held poses), keyed on the same grid
            write_channels(g, a, times, {(k, "translation"): local[k][0] + dl for k in kids if interp[k] == it}, it)
        changed.append(clip)
    return changed


def preserved_errors(before: dict, after: dict, rewritten: set) -> list[str]:
    bad = []
    for k, (it, t, v) in before.items():
        if (k[0], k[1]) in rewritten and k[2] == "translation":
            continue
        if k not in after:
            bad.append(f"{k} channel dropped")
            continue
        it2, t2, v2 = after[k]
        if it2 != it or t2.shape != t.shape or v2.shape != v.shape or not (np.array_equal(t, t2) and np.array_equal(v, v2)):
            bad.append(f"{k} sampler changed")
    return bad + [f"{k} channel added" for k in set(after) - set(before)
                  if not ((k[0], k[1]) in rewritten and k[2] == "translation")]


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def apply_bytes(unit: str, data: bytes, p: Path, out: Path | None = None):
    """The ground stage on GLB bytes, in memory: a stage_sidecar.StageResult whose sidecar names `p` as source and
    `out` (default p) as output, as the CLI writes it. The output is ground_check-ed as bytes, never from disk."""
    args = argparse.Namespace(unit=unit)
    p = Path(p)
    out = Path(out or p)
    g = Glb(data)
    if STAMP in g.json.get("asset", {}).get("extras", {}):
        raise SystemExit(f"{args.unit}: {p.name} is already grounded ({STAMP}); ground the GLB its stages just wrote")
    src = g.raw
    offsets, ctx = plan(args.unit, src, g)
    before = channel_snapshot(g)
    root, kids = body_nodes(g)
    changed = apply_offsets(g, offsets, ctx["H"])
    bad = preserved_errors(before, channel_snapshot(g), {(c, k) for c in changed for k in kids})
    if bad:
        raise SystemExit(f"{args.unit}: ground_glb changed channels it does not own: {bad[:6]}")
    clips = {c: info for c, (_, _, info) in offsets.items()}
    g.json.setdefault("asset", {}).setdefault("extras", {})[STAMP] = {
        "schema": SCHEMA, "tool": "tools/homm3_def_retarget_delivery/ground_glb.py",
        "rule": "tools/homm3_def_retarget/grounding.py offsets", "sourceGlbSha256": sha(src),
        "exemption": ctx["exemption"], "idleHeight": ctx["H"], "defSource": ctx["defSource"],
        "movedNodes": [g.names[k] for k in kids], "clipsChanged": changed, "clips": clips,
        "proof": "generated artifact: vertical body offsets on the delivered GLB; not built into a bundle, not in game"}
    data = g.to_bytes()
    try:
        gbad, rec = GC.ground_check(args.unit, data)
    except SystemExit as e:
        gbad, rec = [str(e)], {}
    if gbad:
        # the rule's own record for every failing clip, so a refusal can be diagnosed without the (discarded) input
        named = {c: i for c, i in clips.items() if any(b.startswith(f"{c} ") for b in gbad)}
        m_in = GC.glb_ground(src)["clips"]
        for c, i in named.items():
            t, s, _ = offsets[c]
            named[c] = dict(i, lowsIn=[round(float(x), 4) for x in m_in[c]["lows"]],
                            hips0In=round(float(m_in[c]["hips0"]), 4), offsets=[round(float(x), 4) for x in s])
        raise SystemExit(f"{args.unit}: grounded GLB still fails ground_check: {'; '.join(gbad)}; "
                         f"rule record {json.dumps(named, sort_keys=True)}")
    side = {"schema": SCHEMA, "unit": args.unit, "sourceGlb": str(p), "sourceGlbSha256": sha(src),
            "outputGlb": str(out), "outputGlbSha256": sha(data), "clipsChanged": changed, "clips": clips,
            "groundCheck": rec.get("clips")}
    import stage_sidecar
    return stage_sidecar.result(data, src, "ground", side, {
        "unit": args.unit, "out": str(out), "clipsChanged": changed,
        "clips": {c: {k: v for k, v in i.items() if k not in ("keys", "loopClosed")} for c, i in clips.items()}})


def cmd_apply(args) -> int:
    p = Path(args.glb or canonical_glb(args.unit))
    out = Path(args.out or p)
    r = apply_bytes(args.unit, p.read_bytes(), p, out)
    import stage_sidecar
    stage_sidecar.commit(out, r)
    print(json.dumps(r.report))
    return 0


def stamp_errors(js: dict) -> list[str]:
    st = js.get("asset", {}).get("extras", {}).get(STAMP)
    if not isinstance(st, dict):
        return [f"no {STAMP} stamp (fleet_rebuild.py runs ground_glb.py apply)"]
    bad = []
    if st.get("schema") != SCHEMA:
        bad.append(f"{STAMP} schema {st.get('schema')!r} != {SCHEMA}")
    if not (isinstance(st.get("sourceGlbSha256"), str) and len(st["sourceGlbSha256"]) == 64):
        bad.append(f"{STAMP} has no sourceGlbSha256")
    if not isinstance(st.get("clips"), dict) or not st["clips"]:
        bad.append(f"{STAMP} records no clips")
    return bad


def cmd_check(args) -> int:
    bad = 0
    for p in args.glbs:
        errs = stamp_errors(Glb.load(Path(p)).json)
        print(json.dumps({"glb": p, "ok": not errs, "errors": errs}))
        bad += bool(errs)
    return 1 if bad else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("apply")
    s.add_argument("unit")
    s.add_argument("--glb", type=Path, help="input GLB (default: the canonical def_retarget GLB)")
    s.add_argument("--out", type=Path, help="output GLB (default: rewrite the input in place)")
    s = sub.add_parser("check")
    s.add_argument("glbs", nargs="+")
    args = ap.parse_args(argv)
    return cmd_apply(args) if args.cmd == "apply" else cmd_check(args)


if __name__ == "__main__":
    sys.exit(main())
