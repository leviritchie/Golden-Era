"""Parity + edit-math checks for the Haiku anim bench (seconds; run before trusting a change to anim_core / anim_gl).

    python tools/haiku_anim_bench/test_bench.py [--glb P]

1. GPU skin (anim_gl) == CPU reference skin (anim_core.skin_cpu) on edited Idle poses (max error / body height).
2. GPU edge stretch == CPU (patch_glb.edge_stretch's measure): same count past 2x up to float32 ties, same worst.
3. Edit math: Head pitch+ lowers the gaze at the centre frame, leaves frames past the half width untouched, and the
   loop wrap keeps the seam continuous.
4. Rig ops (rig.RigEditor): split / add / pivot / reparent keep the skinned pose (new joints are identity); the rig GLB
   (rig_glb.build_rig_glb) re-loads to the same joints and skin; a known-bad edit (Spine2 twist 60) opens a defect on the
   per-edge rule and the all-clip check (AnimGL.clip_defect_edges) sees it too.
5. Round 5: the DLS intent solver converges on a toy 3-joint chain and spreads the bend over it; a real-unit gaze
   intent converges and its parts reproduce the solved pose through the bench's edit math; the judge's order-swap rule
   (accept only when AFTER wins both orders); the item store's tabu survives a reload.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from anim_core import ROOT, Unit  # noqa: E402
from anim_gl import AnimGL  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--glb", default=str(ROOT / "artifacts/homm3_def_retarget/h3_roc/h3_roc_def_retarget.glb"))
    ap.add_argument("--unit", default="h3_roc")
    a = ap.parse_args()
    u = Unit(a.unit, Path(a.glb))
    g = AnimGL(u)
    clip = "Unit_Idle"
    e1 = u.make_edit(clip, "Head", 3, 2, [], axis="pitch", deg=20)
    e2 = u.make_edit(clip, "Hips", 0, 2, [e1], tr=[0.0, -0.03, 0.0])
    edits = [e1, e2]
    times = [u.frame_time(clip, f) for f in (0, 3, 5)]
    _, Jm, mw = u.pose(clip, times, edits)
    g.skin(Jm, mw)
    Pg = g.read_posed(len(times))
    Pc = u.skin_cpu(Jm, mw)
    err = float(np.abs(Pg - Pc).max()) / u.H
    cnt, worst = g.stretch(len(times))
    rc = u.edge_stretch_cpu(Pc)
    ccnt, cworst = (rc > 2.0).sum(1), rc.max(1)
    fails = []
    if err > 1e-5:
        fails.append(f"skin parity {err:.2e} of H > 1e-5")
    if np.abs(cnt - ccnt).max() > 2:
        fails.append(f"stretch count gpu {cnt} cpu {ccnt}")
    if np.abs(worst - cworst).max() > 1e-3 * cworst.max():
        fails.append(f"worst gpu {worst} cpu {cworst}")
    # edit math
    ft = [u.frame_time(clip, f) for f in range(u.clips[clip]["n"])]
    G0, _, _ = u.pose(clip, ft)
    G1, _, _ = u.pose(clip, ft, [e1])
    d0, d1 = u.gaze(G0)[1], u.gaze(G1)[1]
    if not d1[3, 1] < d0[3, 1] - 0.1:
        fails.append(f"pitch+ did not lower the gaze at the centre frame ({d0[3]} -> {d1[3]})")
    if np.abs(d1[6] - d0[6]).max() > 1e-9 or np.abs(d1[0] - d0[0]).max() > 1e-9:
        fails.append("an edit leaked past its half width")
    ew = u.make_edit(clip, "Head", 0, 2, [], axis="yaw", deg=15)
    c = u.clips[clip]
    Gs, _, _ = u.pose(clip, [c["start"], c["end"]], [ew])
    if np.abs(Gs[0] - Gs[1]).max() > 1e-6 and np.abs(G0[0] - u.pose(clip, [c["end"]])[0][0]).max() < 1e-6:
        fails.append("loop wrap: start and end keys differ after a frame-0 edit")
    nf, nmsg = net_checks(u)
    fails += nf
    print(nmsg)
    rig_fails, rig_msg = rig_checks(u, g, a)
    fails += rig_fails
    print(rig_msg)
    for fn in (toy_chain_checks, judge_checks, tabu_checks):
        f5, m5 = fn()
        fails += f5
        print(m5)
    f5, m5 = intent_unit_checks(u)
    fails += f5
    print(m5)
    print(f"skin parity {err:.2e} H; stretch gpu {cnt.tolist()} cpu {ccnt.tolist()} worst {np.round(worst, 4).tolist()} "
          f"cpu {np.round(cworst, 4).tolist()}; gaze y f3 {d0[3, 1]:.3f} -> {d1[3, 1]:.3f}")
    print("FAIL: " + "; ".join(fails) if fails else "OK")
    return 1 if fails else 0


def net_checks(u: Unit) -> tuple[list[str], str]:
    """Net stack: collapsing a stack (bumps, whole-clip, stacked axes, a root move) to one net offset per joint poses
    every grid key and DEF frame identically, and a bump added after the collapse composes the same way."""
    from anim_core import HW_ALL
    clip = "Unit_Move"
    ed = []
    for bone, ax, deg, f, hw in (("Hips", "pitch", 25, 0, HW_ALL), ("Hips", "pitch", -15, 2, 2), ("Neck", "roll", 30, 3, 1),
                                 ("Neck", "yaw", 20, 4, 3), ("Spine1", "pitch", 40, 0, 2)):
        ed.append(dict(u.make_edit(clip, bone, f, hw, ed, axis=ax, deg=deg), id=len(ed) + 1))
    ed.append(dict(u.make_edit(clip, "Hips", 1, 2, ed, tr=[0.0, 0.05, 0.0]), id=9))
    k = [100]

    def new_id():
        k[0] += 1
        return k[0]
    net = u.net_collapse(ed, {}, new_id)
    c = u.clips[clip]
    t = np.unique(np.r_[c["grid"], c["times"]])
    G0, _, _ = u.pose(clip, t, ed)
    G1, _, _ = u.pose(clip, t, net)
    d = float(np.abs(G0[..., :3, 3] - G1[..., :3, 3]).max() / u.H)
    extra = u.make_edit(clip, "Neck", 2, 2, net, axis="pitch", deg=-20)
    G2, _, _ = u.pose(clip, t, ed + [extra])
    G3, _, _ = u.pose(clip, t, net + [extra])
    d2 = float(np.abs(G2[..., :3, 3] - G3[..., :3, 3]).max() / u.H)
    fails = []
    if d > 1e-6 or d2 > 1e-6 or len(net) != 4:
        fails.append(f"net collapse parity {d:.1e} / {d2:.1e} H, {len(net)} nets (want 4)")
    return fails, f"net: {len(ed)} edits -> {len(net)} nets, parity {d:.1e} H, then a bump {d2:.1e} H"


def rig_checks(u: Unit, g: AnimGL, a) -> tuple[list[str], str]:
    import tempfile

    from rig import RigEditor
    from rig_glb import build_rig_glb
    fails, msg = [], []
    clip = "Unit_Move"
    g.setup_clip(clip)                       # pristine per-edge thresholds before any rig op
    t = np.asarray(u.clips[clip]["grid"], float)
    _, J0, m0 = u.pose(clip, t)
    Y0 = u.skin_cpu(J0, m0)
    rig = RigEditor(u)
    seqs = {"split": [{"do": "split", "bone": "WingL_01", "at": 0.5, "name": "t_split"}],
            "add": [{"do": "add", "parent": "Spine", "toward": "back", "size": 0.3, "name": "t_tail"}],
            "pivot": [{"do": "pivot", "bone": "Neck", "move": [0.0, 0.02 * u.H, 0.0]}],
            "reparent": [{"do": "reparent", "bone": "WingL_00", "parent": "Spine2"}]}
    for name, ops in seqs.items():
        rig.apply(ops)
        _, J1, m1 = u.pose(clip, t)
        d = float(np.abs(u.skin_cpu(J1, m1) - Y0).max() / u.H)
        msg.append(f"{name} drift {d:.4f} H")
        if d > 0.02:
            fails.append(f"rig {name} moved the skinned pose by {d:.4f} H")
    rig.apply(seqs["split"] + seqs["add"])
    raw = build_rig_glb(Path(a.glb).read_bytes(), u, rig).to_bytes()
    with tempfile.TemporaryDirectory() as td:
        pth = Path(td) / "rig.glb"
        pth.write_bytes(raw)
        v = Unit(a.unit, pth)
        _, J2, m2 = v.pose(clip, t)
        _, J1, m1 = u.pose(clip, t)
        d = float(np.abs(v.skin_cpu(J2, m2) - u.skin_cpu(J1, m1)).max() / u.H)
        msg.append(f"rig glb round trip {d:.1e} H, joints {len(v.jnames)}")
        if d > 1e-4 or "t_split" not in v.jnames or "t_tail" not in v.jnames:
            fails.append(f"rig GLB round trip {d:.1e} H / new joints missing")
    # round 3 region tools: sculpt (rest shape, GLB round trip), rebind (rigid), corrective (GPU = CPU, keyed weight)
    ctr = np.linalg.inv(u.scene.ibm[u.jnames.index("Neck")])[:3, 3].tolist()
    P0 = u.scene.P.copy()
    rig.apply([{"fix": "sculpt", "mode": "inflate", "amount": 0.02, "center": ctr, "radius": 0.15 * u.H}])
    mv = np.linalg.norm(u.scene.P - P0, axis=1)
    far = np.linalg.norm(P0 - np.asarray(ctr), axis=1) > 0.6 * u.H
    msg.append(f"sculpt moved {int((mv > 1e-7).sum())} verts, max {mv.max() / u.H:.3f} H, far {mv[far].max():.1e}")
    if not mv.max() > 0.01 * u.H or mv[far].max() > 1e-9:
        fails.append("sculpt: no move inside the region or a move outside it")
    raw = build_rig_glb(Path(a.glb).read_bytes(), u, rig).to_bytes()
    with tempfile.TemporaryDirectory() as td:
        pth = Path(td) / "rig.glb"
        pth.write_bytes(raw)
        v = Unit(a.unit, pth)
        d = float(np.abs(v.scene.P - u.scene.P).max() / u.H)
        msg.append(f"sculpt glb round trip {d:.1e} H")
        if d > 1e-5:
            fails.append(f"sculpt GLB round trip {d:.1e} H")
    rig.apply([{"fix": "rebind", "bone": "Head", "center": ctr, "radius": 0.1 * u.H}])
    D = rig.dense()
    inner = rig.region(ctr, 0.1 * u.H) > 0.99
    if not inner.any() or np.abs(D[inner, u.jnames.index("Head")] - 1).max() > 1e-6:
        fails.append("rebind: the region core is not fully on Head")
    clip_i = "Unit_Idle"
    node = u.names.index("Neck")
    G, _, _ = u.pose(clip_i, [u.frame_time(clip_i, 2)])
    pn = u.scene.parent[node]
    L = np.linalg.inv(G[0, pn]) @ G[0, node]
    from rig import mat_to_quat
    q = mat_to_quat(L[:3, :3] / np.linalg.norm(L[:3, :3], axis=0, keepdims=True)).tolist()
    rig.apply([{"fix": "corrective", "bone": "Neck", "qref": q, "mode": "inflate", "amount": 0.03, "center": ctr,
                "radius": 0.15 * u.H}])
    g.upload_rig()
    tt = [u.frame_time(clip_i, f) for f in (0, 2)]
    _, Jc, mc = u.pose(clip_i, tt)
    g.skin(Jc, mc)
    dgc = float(np.abs(g.read_posed(2) - u.skin_cpu(Jc, mc)).max() / u.H)
    msg.append(f"corrective weight f2 {mc[1, -1]:.2f}, GPU/CPU {dgc:.1e} H")
    if mc[1, -1] < 0.999 or dgc > 1e-5:
        fails.append(f"corrective: weight at its own pose {mc[1, -1]:.3f}, GPU/CPU {dgc:.1e} H")
    rig.apply([])
    g.upload_rig()
    bad = [u.make_edit(clip, "Spine2", 3, 2, [], axis="roll", deg=30)]     # one edit is capped at 30 deg: stack two
    bad.append(u.make_edit(clip, "Spine2", 3, 2, bad, axis="roll", deg=30))
    n0, n1 = g.clip_defect_edges(clip, []), g.clip_defect_edges(clip, bad)
    msg.append(f"defect edges clean {n0} -> Spine2 twist 60: {n1}")
    if n0 != 0 or n1 == 0:
        fails.append(f"defect rule: clean clip {n0} edges, known-bad edit {n1}")
    return fails, "rig: " + "; ".join(msg)


def _qmat(q):
    x, y, z, w = q
    return np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                     [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                     [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])


def toy_chain_checks() -> tuple[list[str], str]:
    """3 unit links along +Z; aim the root->tip line 60 deg up and 20 deg to the side; equal weights must converge
    under 0.3 deg and share the turn (no joint carries it all); weight 0 on a joint must keep it still."""
    from intent import angle_deg, dir_from, quat_angle_axis, solve
    target = dir_from(60.0, 20.0)
    fails, msg = [], []
    for weights in ([1.0, 1.0, 1.0], [1.0, 0.0, 1.0]):
        def fk(qs):
            R, p, piv, Rs = np.eye(3), np.zeros(3), [], []
            for q in qs:
                piv.append(p.copy())
                R = R @ _qmat(q)
                Rs.append(R.copy())
                p = p + R @ np.array([0, 0, 1.0])
            nj = len(qs)
            f = {"kind": "vec", "v": p - 0.0, "A": np.zeros(3), "B": p, "dA": np.zeros(nj, bool),
                 "dB": np.ones(nj, bool), "t": target}
            return {"piv": np.array(piv), "R": np.array(Rs), "feats": [f]}
        qs, err, it = solve(fk, weights)
        angs = [quat_angle_axis(q)[0] for q in qs]
        tip = fk(qs)["feats"][0]["v"]
        real = angle_deg(tip, target)
        msg.append(f"w{weights}: err {real:.2f} deg in {it} it, joint turns {[round(x, 1) for x in angs]}")
        if real > 0.3:
            fails.append(f"toy chain {weights}: did not converge ({real:.2f} deg)")
        if weights[1] == 0.0 and angs[1] > 1e-3:
            fails.append(f"toy chain: a zero-weight joint moved {angs[1]:.3f} deg")
        if weights[1] == 1.0 and max(angs) > 0.8 * sum(angs):
            fails.append(f"toy chain: one joint carries the whole turn {angs}")
    return fails, "toy DLS: " + "; ".join(msg)


def judge_checks() -> tuple[list[str], str]:
    """r_ab: 1 = BEFORE, 2 = AFTER; r_ba swapped. Accept only when AFTER wins both orders."""
    from r5_items import judge_verdict
    cases = [(("2", True), ("1", True), "accept", True, True), (("2", False), ("1", True), "accept", True, False),
             (("2", True), ("2", True), "split", False, False), (("1", True), ("1", True), "split", False, False),
             (("1", False), ("2", False), "worse", False, False), (("same", False), ("1", True), "same", False, False),
             (("2", True), ("same", True), "same", False, False), ((None, None), ("1", True), "same", False, False)]
    fails = []
    for (a, fa), (b, fb), v, acc, fx in cases:
        r = judge_verdict({"better": a, "fixed": fa} if a else None, {"better": b, "fixed": fb})
        if (r["verdict"], r["accept"], r["fixed"]) != (v, acc, fx):
            fails.append(f"judge {a}/{b}: got {r['verdict']} {r['accept']} {r['fixed']}, want {v} {acc} {fx}")
    return fails, f"judge order swap: {len(cases) - len(fails)}/{len(cases)} cases"


def tabu_checks() -> tuple[list[str], str]:
    """A rejected attempt becomes tabu, survives a reload (session rotation), matches a near-identical retry, and an
    accepted + fixed attempt closes the item; 'none' makes every strength of that intent tabu."""
    import tempfile
    from r5_items import ItemStore
    fails = []
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "items.json"
        s = ItemStore(p)
        it = s.add("Unit_Move", 2, "head", "looks at the ground", "BIG")
        att = {"goal": "gaze", "dir": "level forward", "strength": 1.0, "chain": "whole neck", "frames": [2],
               "what": "gaze level forward"}
        s.record(it["id"], att, {"verdict": "worse", "accept": False}, step=5)
        s2 = ItemStore(p)                                  # a new session / process
        if not s2.is_tabu(it["id"], dict(att, dir="Level  Forward")):
            fails.append("tabu lost on reload or not matched on a near-identical retry")
        if s2.is_tabu(it["id"], dict(att, dir="slightly up forward")):
            fails.append("tabu matched a different direction")
        att2 = dict(att, goal="trunk", dir="slightly up", chain="spine")
        s2.dismissed(it["id"], att2, step=6)
        if not ItemStore(p).is_tabu(it["id"], dict(att2, strength=1.5)):
            fails.append("'none' did not make the other strengths tabu")
        s2.record(it["id"], dict(att, dir="slightly up"), {"verdict": "accept", "accept": True}, fixed=True, step=7)
        s3 = ItemStore(p)
        if s3.get(it["id"])["status"] != "closed":
            fails.append("an accepted + fixed attempt did not close the item")
        n = len(s3.d["tabu"])
    return fails, f"tabu persistence: {n} tabu entries after reload, item closed by judge"


def intent_unit_checks(u: Unit) -> tuple[list[str], str]:
    """A gaze intent on the real unit converges and the edit parts reproduce the solved gaze through Unit.pose."""
    from intent import IntentSolver, angle_deg
    sv = IntentSolver(u)
    clip = "Unit_Idle"
    vs = sv.variants(clip, [2], 2, [], "gaze", None, {"dir": "slightly down forward"})
    fails, msg = [], []
    for v in vs:
        if v.get("skipped"):
            continue
        G = sv.pose_at(clip, 2, v["parts"])
        f = sv.feature("gaze", None, G)
        G0 = sv.pose_at(clip, 2, [])
        f0 = sv.feature("gaze", None, G0)
        msg.append(f"{v['label']} err {v['err']:.2f} turn {angle_deg(f0['v'], f['v']):.1f}")
        if v["err"] > 1.0:
            fails.append(f"unit gaze intent {v['label']}: err {v['err']:.2f} deg")
    return fails, f"{u.unit_id if hasattr(u, 'unit_id') else 'unit'} gaze intent: " + "; ".join(msg)


if __name__ == "__main__":
    raise SystemExit(main())
