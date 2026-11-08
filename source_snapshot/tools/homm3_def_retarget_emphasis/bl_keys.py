"""Blender helpers for the emphasis pass: read a built unit's rotation keys, write emphasised ones back.

Library for bl_deliver.py; also a CLI for inspection:
  blender -b <unit.blend> -P bl_keys.py -- dump <keys.npz>

dump() returns, for the <unit>_DEF_Master action (one key per DEF frame, Blender frames 1..T):
  names      bones that carry rotation_quaternion keys
  Q          (T, B, 4) local quaternions (w, x, y, z) as keyed
  head       (T, B, 3) armature-space bone heads, evaluated per frame (drift checks)
  hipsScale  (T,) Hips pose scale (shatter / shrink deaths hide the body at ~0 scale)
  allNames / allParent / restQ   every bone's parent and armature-space rest rotation
write(Q0, Q2, names, segments) rewrites the Master action's rotation keys and every Unit_<clip>
action whose keys match a Master range of Q0 on every bone (the longest segment per clip, as
build_unit.py writes them; loop-transition keys appended after that range are left alone).
"""
import json, re, sys
import bpy
import numpy as np


def rig():
    return next(o for o in bpy.data.objects if o.type == 'ARMATURE')


def master():
    return next(a for a in bpy.data.actions if a.name.endswith("_DEF_Master"))


def fcurves(act):
    if hasattr(act, "layers") and act.layers:
        from bpy_extras import anim_utils
        slot = next(s for s in act.slots if s.target_id_type == 'OBJECT')
        cb = anim_utils.action_get_channelbag_for_slot(act, slot)
        return list(cb.fcurves) if cb else []
    return list(act.fcurves)


def quat_curves(act):
    out = {}
    for fc in fcurves(act):
        m = re.fullmatch(r'pose\.bones\["(.+)"\]\.rotation_quaternion', fc.data_path)
        if m:
            out.setdefault(m.group(1), [None] * 4)[fc.array_index] = fc
    return {k: v for k, v in out.items() if all(v)}


def use_master():
    ad = rig().animation_data; m = master()
    ad.action = m
    if m.slots:
        ad.action_slot = next(s for s in m.slots if s.target_id_type == 'OBJECT')


def dump():
    r = rig(); mq = quat_curves(master())
    names = [b.name for b in r.data.bones if b.name in mq]
    sc = bpy.context.scene
    T = sc.frame_end - sc.frame_start + 1
    Q = np.zeros((T, len(names), 4))
    for j, n in enumerate(names):
        for c in range(4):
            fc = mq[n][c]
            vals = {int(round(k.co[0])): k.co[1] for k in fc.keyframe_points}
            for t in range(T):
                Q[t, j, c] = vals.get(t + 1, fc.evaluate(t + 1))
    use_master()
    head = np.zeros((T, len(names), 3)); hs = np.ones(T)
    for t in range(T):
        sc.frame_set(t + 1)
        for j, n in enumerate(names):
            head[t, j] = r.pose.bones[n].head[:]
        if "Hips" in r.pose.bones:
            hs[t] = float(np.mean(r.pose.bones["Hips"].matrix.to_scale()[:]))
    allb = [b.name for b in r.data.bones]
    return {"names": np.array(names), "Q": Q, "head": head, "hipsScale": hs, "allNames": np.array(allb),
            "allParent": np.array([r.data.bones[n].parent.name if r.data.bones[n].parent else "" for n in allb]),
            "restQ": np.array([r.data.bones[n].matrix_local.to_quaternion()[:] for n in allb])}


def _write_range(act, Q2, pn, t0, n_frames):
    qc = quat_curves(act); nk = 0
    for j, b in enumerate(pn):
        if b not in qc:
            continue
        prev = None
        for i in range(n_frames):
            q = Q2[t0 + i, j].copy(); fr = i + 1 if act is not master() else t0 + i + 1
            if prev is not None and float(np.dot(prev, q)) < 0:
                q = -q                                    # one hemisphere, as build_unit.py keys
            prev = q
            for c in range(4):
                kps = [k for k in qc[b][c].keyframe_points if int(round(k.co[0])) == fr]
                if not kps:
                    raise RuntimeError(f"EMPH no key {act.name} {b} frame {fr}")
                kps[0].co[1] = float(q[c]); nk += 1
        for c in range(4):
            qc[b][c].update()
    return nk


def write(Q0, Q2, names, segments):
    pn = [str(x) for x in names]
    n_master = _write_range(master(), Q2, pn, 0, Q2.shape[0])
    report = {}
    for act in bpy.data.actions:
        if not act.name.startswith("Unit_"):
            continue
        qc = quat_curves(act)
        common = [b for b in pn if b in qc]
        if not common:
            continue
        AK = [np.array([[k.co[1] for k in qc[b][c].keyframe_points] for c in range(4)]).T for b in common]
        nka = min(len(x) for x in AK)
        best = None
        for key, a, b in segments:
            n = b - a
            if n > nka:
                continue
            d = max(np.abs(np.abs(np.sum(AK[i][:n] * Q0[a:b, pn.index(bn)], axis=1)) - 1).max() for i, bn in enumerate(common))
            if d < 1e-5 and (best is None or n > best[1]):
                best = (a, n)
        if best is None:
            report[act.name] = "no matching master range"
            continue
        if np.abs(Q2[best[0]:best[0] + best[1]] - Q0[best[0]:best[0] + best[1]]).max() > 0:
            _write_range(act, Q2, pn, best[0], best[1])
            report[act.name] = {"masterStart": best[0], "frames": best[1], "rewritten": True}
        else:
            report[act.name] = {"masterStart": best[0], "frames": best[1], "rewritten": False}
    return n_master, report


if __name__ == "__main__" and "--" in sys.argv:
    argv = sys.argv[sys.argv.index("--") + 1:]
    if argv[0] == "dump":
        np.savez(argv[1], **dump())
        print("EMPH_DUMP", argv[1])
