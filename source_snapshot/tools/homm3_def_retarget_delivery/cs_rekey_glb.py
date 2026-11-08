"""Re-bake, in float64 numpy, the Corrective Smooth morphs of every clip a delivery stage re-keyed.

    python tools/homm3_def_retarget_delivery/cs_rekey_glb.py check <glb...>

Why (docs/homm3_cs_bake_float64.md, "stale Corrective Smooth morphs on re-keyed clips"): bake_cs.py bakes one CS_
morph target per key of each clip, at the export's poses. Stride match, Move low-pass and prop floor then rewrite bone
keys of Unit_Move (or the listed clips) and keep those targets, so a re-keyed clip plays morphs that belong to poses it
no longer has (h3_unicorn Move: 2396 edges past 2x, worst 68.0x stored, against 2303 / 11.4x recomputed at the delivered
poses). cs_numpy.py is the bake engine (bake_cs.py runs the same module inside Blender), so the delivery re-bakes those
targets here, on the GLB, at the delivered poses.

One stage, run in process by fleet_rebuild.fused_delivery_stages after prop floor and before ground (the last
non-rigid pose edit; ground is a whole-body translation and CS is invariant under a rigid motion of the skeleton).
apply_bytes(unit, data, reference, out):
  reference  the GLB bytes the pose-editing stages started from (the export, after the glb patch stage, which re-bakes
             its own targets);
  per target (patch_glb.target_poses: the key its weight is 1 on; for a densified clip only its original keys, every
             keysPerSpan-th, are candidates), the skin matrices at that key in the reference and in `data` are compared.
             T_j = Sk_new_j Sk_old_j^-1 over every joint that carries weight: all T_j the identity (within RIGID_TOL;
             translations / body height) = "unchanged"; all T_j one common rigid motion = "rigid" (deyaw; CS returns
             the same rest-space offsets); anything else re-keyed the pose, and the target is re-baked;
  parity     before a re-bake, numpy CS at the reference pose must reproduce the stored target (patch_glb's limits
             PARITY_P99_MAX / PARITY_MAX_MAX of the body height), so the re-bake is the stored bake's own engine;
  re-bake    cs_numpy offsets at the delivered pose (weld, smoothing, frames, fill, solve: the bake's rule) written over
             that target's accessor in place (dense, unshared; refused otherwise).
Records, per clip with CS targets: status "rebaked" (any target re-baked) / "rigid" / "unchanged", the counts, the worst
pose deviation and the stretch (edges past 2x / 3x, worst) of the stored and of the written targets at the delivered
poses -- in the bake record itself, asset.extras.homm3DefRetargetCsBake.rekey, and stamps
asset.extras.homm3DefRetargetDeliveryCsRekey {sourceGlbSha256, referenceGlbSha256, rebakedClips} for the delivery
chain (<glb>.cs_rekey.json sidecar). tools/validate_homm3_cs_bake_contract.py refuses a current-rule GLB that ran the
delivery chain without this record, or whose record misses a clip with CS targets or a clip a re-keying stage stamps.
None (skipped): a GLB without CS_ targets. Refuses: a GLB already stamped, a bake record that is not the current rule
(cs_numpy.BAKE_SCHEMA: re-run the full chain), a skin, mesh or stored target that differs from the reference (a stage
between them edited what this stage re-bakes against), a target on no candidate key or on several with not exactly one at its own frame (own_key), a missing clip that
the unit config does not skip (orphan_targets), a parity miss.
Proof tier: generated artifact. Nothing here builds a bundle or touches the game.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "tools/homm3_glb_patch"))
import cs_numpy as CS  # noqa: E402
import patch_glb as PG  # noqa: E402
import stage_sidecar  # noqa: E402
sys.path.insert(0, str(ROOT / "tools/homm3_def_retarget"))
import skip_def_groups  # noqa: E402
from stride_match_glb import Glb  # noqa: E402

STAMP = "homm3DefRetargetDeliveryCsRekey"
SCHEMA = "homm3_def_retarget_delivery_cs_rekey.v1"
REKEY = "rekey"                                   # key of the record inside the bake record (CS.BAKE_STAMP)
REKEY_SCHEMA = "homm3_def_retarget.cs_rekey.v1"
RIGID_TOL = 1e-5                                  # |T_j - T_ref| (rotation entries; translation / body height)
STATUSES = ("rebaked", "rigid", "unchanged")
DENSIFY = "homm3DefRetargetDeliveryDensify"
# the delivery stages that rewrite bone keys of named clips after the export (the validator's coverage rule)
REKEYING_STAGES = {"homm3DefRetargetDeliveryStrideMatch": lambda st: ["Unit_Move"],
                   "homm3DefRetargetDeliveryMoveLowPass": lambda st: ["Unit_Move"],
                   DENSIFY: lambda st: list((st.get("clips") or {})),
                   "homm3DefRetargetDeliveryPropFloor": lambda st: list((st.get("clips") or {}))}


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def clip_name(c: str) -> str:
    return c if c.startswith("Unit_") else f"Unit_{c}"


def rekeyed_clips(extras: dict) -> dict:
    """{clip: [stage stamps that re-key it]} from a GLB's delivery stamps."""
    out: dict = {}
    for k, f in REKEYING_STAGES.items():
        st = extras.get(k)
        if isinstance(st, dict):
            for c in f(st):
                out.setdefault(clip_name(c), []).append(k)
    return out


def orphan_targets(target_names, clip_names, skipped: dict) -> dict:
    """{clip: [target indices]} of CS_ targets whose clip the export left out on purpose: the unit config's
    skipDefGroups (skip_def_groups.skipped_clips; export_glb.py does not ship that clip, bake_cs.py still baked its
    shape keys). A target naming any other missing clip is refused (2026-10-01 h3_vampire_prince: 7 CS_Unit_ShootFront
    targets, its shoot groups skipped, user-approved 2026-09-28)."""
    out: dict = {}
    for ti, name in enumerate(target_names):
        if not name.startswith("CS_"):
            raise SystemExit(f"morph target {name!r} is not a bake_cs target")
        clip = name[3:].rsplit("_", 1)[0]
        if clip in clip_names:
            continue
        if clip not in skipped:
            raise SystemExit(f"morph target {name} names no clip of the GLB")
        out.setdefault(clip, []).append(ti)
    return out


def on_keys(wcol: np.ndarray, cand: np.ndarray) -> np.ndarray:
    """The candidate keys a target's weight is 1 on."""
    return cand[wcol[cand] >= 0.999]


KEY_FPS = 12                                      # bake_cs names a target CS_<clip>_<frame:03d>; keys sit at frame/12 s
FRAME_TOL = 1e-4                                  # s


def own_key(name: str, clip: str, t: np.ndarray, on: np.ndarray) -> int:
    """The key a CS_ target was baked at, among the keys its weight is 1 on: one key -> that key; several -> the one
    at the target's own frame (its name's frame / KEY_FPS), exactly one or refused. Several keys happen on a one-frame
    clip: bake_cs keys the target at that frame only, the weight curve is constant, and the export samples the clip at
    a second key past its frame, where the rig is not that pose (2026-10-01 h3_wight / h3_walking_dead / h3_rot_zombie
    Unit_MoveEnd + MoveStart, h3_lich_master Unit_Idle: 2 keys 1/12 s apart, the second 0.004-0.009 H off the first;
    every target of six probed units, stride / densified / plain, sits on its frame/12 key). The other keys keep the
    stored weight; the record counts them (heldKeys)."""
    if len(on) == 1:
        return int(on[0])
    if len(on) == 0:
        raise SystemExit(f"target {name} is on at no key of {clip}")
    try:
        f = int(name.rsplit("_", 1)[1])
    except ValueError:
        raise SystemExit(f"target {name} is on at {len(on)} keys of {clip} and names no frame")
    hit = [int(k) for k in on if abs(float(t[k]) - f / KEY_FPS) <= FRAME_TOL]
    if len(hit) != 1:
        raise SystemExit(f"target {name} is on at {len(on)} keys of {clip} (t={np.round(t[on], 5).tolist()}), "
                         f"{len(hit)} of them at its frame {f} ({f / KEY_FPS:.5f} s; expected one)")
    return hit[0]


def target_times(g: Glb, body: PG.Body, unit: str | None = None) -> tuple[dict, dict, dict]:
    """({target index: (clip, key time)}, {target index: [every key time it is on]} for targets on at several keys,
    {clip: [target indices]} orphans): the key each CS_ target's weight is 1 on. A densified clip (its stamp's
    keysPerSpan) only offers its original keys, every keysPerSpan-th (the spline between them blends the weights).
    A target on at several keys resolves to its own frame's key (own_key); orphans (orphan_targets) must be weight 0
    in every shipped clip."""
    dens = (g.json.get("asset", {}).get("extras") or {}).get(DENSIFY) or {}
    per = {clip_name(c): int(dens["keysPerSpan"]) for c in (dens.get("clips") or {})}
    clips = {a["name"]: a for a in g.json.get("animations", [])}
    orphans = orphan_targets(body.target_names, clips, skip_def_groups.skipped_clips(unit) if unit else {})
    orphan_ti = sorted(ti for v in orphans.values() for ti in v)
    by_clip: dict = {}
    for ti, name in enumerate(body.target_names):
        if ti not in orphan_ti:
            by_clip.setdefault(name[3:].rsplit("_", 1)[0], []).append(ti)
    if orphan_ti:
        for cn, a in clips.items():
            for c in a["channels"]:
                if c["target"]["path"] == "weights" and c["target"]["node"] == body.node:
                    s_ = a["samplers"][c["sampler"]]
                    w_ = g.read(s_["output"]).reshape(len(g.read(s_["input"])), -1)
                    if np.abs(w_[:, orphan_ti]).max() > 1e-6:
                        raise SystemExit(f"{cn} plays a CS_ target of a skipped clip ({sorted(orphans)})")
    out, held = {}, {}
    for clip, tis in by_clip.items():
        a = clips[clip]
        ch = [c for c in a["channels"] if c["target"]["path"] == "weights" and c["target"]["node"] == body.node]
        if len(ch) != 1:
            raise SystemExit(f"{clip}: {len(ch)} morph weight channels on the body")
        s = a["samplers"][ch[0]["sampler"]]
        t = g.read(s["input"])[:, 0]
        w = g.read(s["output"]).reshape(len(t), -1)
        k = per.get(clip, 1)
        if k > 1 and (len(t) - 1) % k:
            raise SystemExit(f"{clip}: {len(t)} weight keys are not a densified grid of keysPerSpan {k}")
        cand = np.arange(0, len(t), k)
        for ti in tis:
            on = on_keys(w[:, ti], cand)
            kk = own_key(body.target_names[ti], clip, t, on)
            out[ti] = (clip, float(t[kk]))
            if len(on) > 1:
                held[ti] = [float(t[x]) for x in on if int(x) != kk]
    return out, held, orphans


def skin_at(g: Glb, body: PG.Body, times: dict) -> dict:
    """{target index: per skin joint 4x4 skin matrix at the target's key}, sampled once per clip."""
    out, per_clip = {}, {}
    for ti, (c, t) in times.items():
        per_clip.setdefault(c, []).append((ti, t))
    for c, lst in per_clip.items():
        mats = g.world(g.sample_local(c, np.array([t for _, t in lst])))
        M = np.stack([mats[j] for j in body.joints], 1) @ body.ibm[None]
        for k, (ti, _) in enumerate(lst):
            out[ti] = M[k]
    return out


def clip_skin(g: Glb, body: PG.Body, clip: str, ts) -> np.ndarray:
    """(keys, joints, 4, 4) skin matrices of one clip at the given key times."""
    mats = g.world(g.sample_local(clip, np.asarray(ts, float)))
    return np.stack([mats[j] for j in body.joints], 1) @ body.ibm[None]


def pose_change(S0: np.ndarray, S1: np.ndarray, used: np.ndarray, ref: int, H: float) -> tuple[float, float]:
    """(deviation from the identity, deviation from one common rigid motion) over the weighted joints."""
    T = S1[used] @ np.linalg.inv(S0[used])
    sc = np.array([1.0, 1.0, 1.0, 1.0 / H])[None, None, :]   # translation column relative to the body height
    ident = float(np.abs((T - np.eye(4)[None]) * sc).max())
    rigid = float(np.abs((T - T[ref][None]) * sc).max())
    return ident, rigid


def stretch(body: PG.Body, Wn, Sk, D) -> tuple[int, int, float]:
    r = PG.edge_stretch(body, body.J, Wn, Sk, D)
    return int((r > 2).sum()), int((r > 3).sum()), float(r.max())


def apply_bytes(unit: str, data: bytes, reference: bytes, out: Path):
    t0 = time.perf_counter()
    g = Glb(data)
    ex = g.json.setdefault("asset", {}).setdefault("extras", {})
    if STAMP in ex:
        raise SystemExit(f"{unit}: already re-keyed ({STAMP})")
    body = PG.Body(g)
    if not any(n.startswith("CS_") for n in body.target_names):
        return None
    bake = ex.get(CS.BAKE_STAMP)
    if not isinstance(bake, dict) or bake.get("schema") != CS.BAKE_SCHEMA:
        raise SystemExit(f"{unit}: the CS morphs are not a {CS.BAKE_SCHEMA} bake ({(bake or {}).get('schema')}); run "
                         f"the unit's full chain (fleet_rebuild.py {unit})")
    if REKEY in bake:
        raise SystemExit(f"{unit}: the bake record already carries a {REKEY} record")
    g0 = Glb(reference)
    b0 = PG.Body(g0)
    for what, x, y in (("POSITION", b0.V, body.V), ("JOINTS_0", b0.J, body.J), ("WEIGHTS_0", b0.W, body.W),
                       ("indices", b0.F, body.F), ("inverse bind", b0.ibm, body.ibm)):
        if x.shape != y.shape or not np.array_equal(x, y):
            raise SystemExit(f"{unit}: {what} differs from the reference export; a stage between them edited the skin")
    if b0.target_names != body.target_names or b0.jnames != body.jnames:
        raise SystemExit(f"{unit}: morph target or joint names differ from the reference export")
    sparse = [body.target_names[i] for i, a in enumerate(body.targets) if "sparse" in g.json["accessors"][a]]
    if sparse:
        raise SystemExit(f"{unit}: {len(sparse)} CS_ targets are sparse accessors (an export before export_glb.py's dense "
                         f"targets); run the unit's full chain")
    stored = [g.read(a) for a in body.targets]
    for ti, a in enumerate(b0.targets):
        if not np.array_equal(g0.read(a), stored[ti]):
            raise SystemExit(f"{unit}: stored target {body.target_names[ti]} differs from the reference export")
    (T0, H0, O0), (T1, H1, O1) = target_times(g0, b0, unit), target_times(g, body, unit)
    if set(T0) != set(T1) or set(H0) != set(H1) or O0 != O1:
        raise SystemExit(f"{unit}: the CS_ targets' keys / holds / orphans differ from the reference export")
    S0, S1 = skin_at(g0, b0, T0), skin_at(g, body, T1)
    Wn = body.W / np.maximum(body.W.sum(1, keepdims=True), 1e-9)
    wsum = np.bincount(body.J.ravel(), Wn.ravel(), len(body.joints))
    used = np.flatnonzero(wsum > 0)
    ref = int(np.argmax(wsum[used]))
    # the other keys a held target is on at (own_key): recorded with how far their pose is from the target's own
    held_dev = {ti: max(pose_change(S1[ti], m, used, ref, body.H)[0] for m in clip_skin(g, body, T1[ti][0], ts))
                for ti, ts in H1.items()}
    status, dev = {}, {}
    for ti in T1:
        ident, rigid = pose_change(S0[ti], S1[ti], used, ref, body.H)
        status[ti] = "unchanged" if ident <= RIGID_TOL else "rigid" if rigid <= RIGID_TOL else "rebaked"
        dev[ti] = ident if status[ti] == "unchanged" else rigid
    todo = sorted(ti for ti, s in status.items() if s == "rebaked")
    parity = None
    new = {}
    if todo:
        weld = CS.Weld(body.V, body.J, Wn, body.F)
        cache = weld.rest_deltas(body.V[weld.rep], *CS.bake_smoothing(bake))   # the bake's own iterations / factor
        excl = ((g.json.get("asset", {}).get("extras") or {}).get(CS.BAKE_STAMP) or {}).get("excludeBones") or []
        weld.set_exclusion(CS.exclusion_share(body.J, Wn, body.jnames, excl)[weld.rep] if excl else None)
        old = CS.offsets_batch(weld, body.V, body.J, Wn, [S0[ti] for ti in todo], cache, 0.0)
        err = np.concatenate([np.linalg.norm(o[0] - stored[ti], axis=1) for o, ti in zip(old, todo)])
        parity = {"p99OverHeight": round(float(np.percentile(err, 99)) / body.H, 9),
                  "maxOverHeight": round(float(err.max()) / body.H, 9), "targets": len(todo)}
        if parity["p99OverHeight"] > PG.PARITY_P99_MAX or parity["maxOverHeight"] > PG.PARITY_MAX_MAX:
            raise SystemExit(f"{unit}: numpy CS at the reference poses does not reproduce the stored targets "
                             f"({parity}); refusing to re-bake with a different engine than the bake's")
        for (d, _), ti in zip(CS.offsets_batch(weld, body.V, body.J, Wn, [S1[ti] for ti in todo], cache, 0.0), todo):
            new[ti] = d
    clips: dict = {}
    for ti, (c, _) in sorted(T1.items()):
        r = clips.setdefault(c, {"targets": 0, "rebaked": 0, "rigid": 0, "unchanged": 0, "maxPoseDeviation": 0.0,
                                 "stretchStored": [0, 0, 0.0], "stretchWritten": [0, 0, 0.0]})
        r["targets"] += 1
        r[status[ti]] += 1
        r["maxPoseDeviation"] = max(r["maxPoseDeviation"], dev[ti])
        for key, D in (("stretchStored", stored[ti]), ("stretchWritten", new.get(ti, stored[ti]))):
            a, b, w = stretch(body, Wn, S1[ti], D)
            r[key] = [r[key][0] + a, r[key][1] + b, max(r[key][2], w)]
    for ti, ts in H1.items():
        r = clips[T1[ti][0]]
        r["heldKeys"] = r.get("heldKeys", 0) + len(ts)
        r["heldKeyMaxPoseDeviation"] = float(f"{max(r.get('heldKeyMaxPoseDeviation', 0.0), held_dev[ti]):.3g}")
    for c, r in clips.items():
        r["status"] = "rebaked" if r["rebaked"] else "rigid" if r["rigid"] else "unchanged"
        r["maxPoseDeviation"] = float(f"{r['maxPoseDeviation']:.3g}")
        for key in ("stretchStored", "stretchWritten"):
            r[key][2] = round(r[key][2], 3)
    refs = PG.accessor_refs(g)
    for ti, d in new.items():
        PG.overwrite(g, body.targets[ti], d, refs)
    rebaked = sorted(c for c, r in clips.items() if r["status"] == "rebaked")
    src, rsha = sha(data), sha(reference)
    bake[REKEY] = {"schema": REKEY_SCHEMA, "tool": "tools/homm3_def_retarget_delivery/cs_rekey_glb.py",
                   "engine": CS.BAKE_ENGINE, "sourceGlbSha256": src, "referenceGlbSha256": rsha, "rigidTol": RIGID_TOL,
                   "stagesRekeying": rekeyed_clips(ex), "parity": parity, "clips": clips,
                   **({"orphans": {c: {"targets": len(v), "reason": "clip not exported (unit config skipDefGroups); "
                                       "targets kept, weight 0 in every shipped clip, not re-baked"}
                                   for c, v in O1.items()}} if O1 else {})}
    ex[STAMP] = {"schema": SCHEMA, "tool": "tools/homm3_def_retarget_delivery/cs_rekey_glb.py", "sourceGlbSha256": src,
                 "referenceGlbSha256": rsha, "rebakedClips": rebaked,
                 "proof": "generated artifact: CS morphs re-baked in numpy at the delivered poses; not in a bundle, "
                          "not in game"}
    res = g.to_bytes()
    side = {**stage_sidecar.record(SCHEMA, unit, out, src, sha(res)), "referenceGlbSha256": rsha,
            "rebakedClips": rebaked, "seconds": round(time.perf_counter() - t0, 2),
            "clips": {c: {k: r[k] for k in ("status", "targets", "rebaked", "stretchStored", "stretchWritten")}
                      for c, r in clips.items()}}
    return stage_sidecar.result(res, data, "cs_rekey", side, {
        "unit": unit, "rebakedClips": rebaked, "parity": parity, "seconds": side["seconds"],
        "stretch": {c: [clips[c]["stretchStored"], clips[c]["stretchWritten"]] for c in rebaked}})


def record_errors(extras: dict, n_clip_targets: dict) -> list[str]:
    """Why a current-rule GLB's re-key record does not cover its delivery ([] = it does). n_clip_targets: {clip: CS_
    targets}. The validator calls this for every v3 GLB that ran the delivery chain (a ground stamp)."""
    bake = extras.get(CS.BAKE_STAMP) or {}
    rk, st = bake.get(REKEY), extras.get(STAMP)
    if not isinstance(rk, dict) or not isinstance(st, dict):
        return [f"no CS re-key record ({CS.BAKE_STAMP}.{REKEY} and {STAMP}): the delivery stages ran on stale morphs; "
                "re-run the unit's chain (fleet_rebuild.py)"]
    bad = []
    if rk.get("schema") != REKEY_SCHEMA or st.get("schema") != SCHEMA:
        bad.append(f"re-key schema {rk.get('schema')!r} / {st.get('schema')!r}")
    if rk.get("sourceGlbSha256") != st.get("sourceGlbSha256") or not rk.get("sourceGlbSha256"):
        bad.append("the re-key record and the stage stamp name different sources")
    clips = rk.get("clips") or {}
    orphans = rk.get("orphans") or {}
    for c, n in n_clip_targets.items():
        if c in orphans and c not in clips:
            if (orphans[c] or {}).get("targets") != n:
                bad.append(f"{c}: orphan record counts {(orphans[c] or {}).get('targets')} targets, the GLB has {n}")
            continue
        r = clips.get(c)
        if not isinstance(r, dict) or r.get("status") not in STATUSES:
            bad.append(f"{c}: no re-key status")
        elif r.get("targets") != n or r["rebaked"] + r["rigid"] + r["unchanged"] != n:
            bad.append(f"{c}: re-key record counts {r.get('targets')} targets, the GLB has {n}")
        elif (r["status"] == "rebaked") != (r["rebaked"] > 0):
            bad.append(f"{c}: status {r['status']} with {r['rebaked']} re-baked targets")
    for c, stages in rekeyed_clips(extras).items():
        if c in n_clip_targets and c not in clips:
            bad.append(f"{c} is re-keyed by {', '.join(stages)} but has no re-key status")
    if sorted(c for c, r in clips.items() if isinstance(r, dict) and r.get("status") == "rebaked") != \
            sorted(st.get("rebakedClips") or []):
        bad.append("the stage stamp's rebakedClips disagree with the bake record")
    return bad


def clip_targets(js: dict) -> dict:
    out: dict = {}
    for m in js.get("meshes", []):
        for t in (m.get("extras") or {}).get("targetNames") or []:
            if str(t).startswith("CS_"):
                c = str(t)[3:].rsplit("_", 1)[0]
                out[c] = out.get(c, 0) + 1
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("check")
    s.add_argument("glbs", nargs="+")
    a = ap.parse_args(argv)
    bad = 0
    for p in a.glbs:
        js = Glb.load(Path(p)).json
        e = record_errors(js.get("asset", {}).get("extras") or {}, clip_targets(js))
        rk = ((js.get("asset", {}).get("extras") or {}).get(CS.BAKE_STAMP) or {}).get(REKEY) or {}
        print(json.dumps({"glb": p, "ok": not e, "errors": e,
                          "clips": {c: [r.get("status"), r.get("stretchStored"), r.get("stretchWritten")]
                                    for c, r in (rk.get("clips") or {}).items()}}))
        bad += bool(e)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
