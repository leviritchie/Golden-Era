"""Inferno hook: keep a quadruped's hind feet planted where its DEF keeps them (before_keys).

Why (h3_hell_hound, 2026-10-02): the hell hound's DEF Hitted and Death open on the Idle stance with all four paws on
the floor, and the hound then rears up pivoting on its hind paws. The capture plus silhouetteRefine's whole-body roll
(18-24 degrees about the camera axis through the Hips on the first Hitted frames) instead swings one hind leg down
through the floor (LeftToeBase 0.16 of the body height under the Idle floor at Hitted frame 0, 0.10 at Death frame 0)
and lifts the other. ground_glb.py can only lift the whole body, which steps the Hips +0.09 / +0.12 above Idle at the
clip's entry, so the ground gate refused the unit (joint entry infeasible) and the hound never left the legacy lane.

Rule: in the named clips, at each listed DEF frame k with weight w_k, each hind leg chain (upper, lower, foot) is
two-bone IK'd so the ankle moves from its own position toward the same point at the Idle frame-0 ankle height
(horizontal position kept: the paw is planted where the pose puts it, not dragged), by w_k. Bone lengths are kept and
the knee stays on its own side of the hip-ankle line. The foot's world rotation is slerped toward its Idle frame-0
world rotation by w_k (a planted paw lies flat), and every bone under the foot follows it rigidly. Frames past the
list are untouched.

Config (unit json), listed in "extensions" after inferno_capture:
  "hindPlant": {"legs": [["LeftUpLeg", "LeftLeg", "LeftFoot"], ["RightUpLeg", "RightLeg", "RightFoot"]],
                "clips": {"Hitted": [1, 1, ...], "Death": [1, 1, 0.5]}}
  Clip keys are master-sequence contract suffixes; each list holds per-DEF-frame weights in [0, 1].
Proof tier: build-time pose edit, judged by the unit's own ground / freeze / articulation gates; nothing here is a gate.
"""
import json
import math


def before_keys(g):
    cfg = g["cfg"].get("hindPlant")
    if not cfg:
        return
    if set(cfg) - {"legs", "clips", "reason"}:
        raise SystemExit(f"hindPlant: unknown keys {sorted(set(cfg) - {'legs', 'clips', 'reason'})}")
    Matrix, Vector = g["Matrix"], g["Vector"]
    posed, parent_of = g["posed_world"], g["parent_of"]
    ms = json.load(open(g["MASTER"]))
    segs = {}
    for s in ms["segments"]:
        k = s["contractSuffix"]
        if k not in segs or s["frameCount"] > segs[k]["frameCount"]:
            segs[k] = s
    if "Idle" not in segs:
        raise SystemExit("hindPlant: the master sequence has no Idle segment")
    A0 = posed[segs["Idle"]["globalStart"]]
    legs = cfg["legs"]
    for chain in legs:
        if len(chain) != 3 or any(b not in A0 for b in chain):
            raise SystemExit(f"hindPlant: leg chain {chain} must name three posed bones")

    def descendants(b):
        out, stack = [], [b]
        while stack:
            p = stack.pop()
            for c, par in parent_of.items():
                if par == p and c in A0:
                    out.append(c); stack.append(c)
        return out

    report = {}
    for clip, ws in cfg["clips"].items():
        if clip not in segs:
            raise SystemExit(f"hindPlant: clip {clip} is not a master-sequence segment")
        s = segs[clip]
        if len(ws) > s["frameCount"] or any(not 0.0 <= float(w) <= 1.0 for w in ws):
            raise SystemExit(f"hindPlant: {clip} weights must be <= {s['frameCount']} values in [0, 1]")
        rows = []
        for k, w in enumerate(ws):
            w = float(w)
            if w <= 0:
                continue
            A = posed[s["globalStart"] + k]
            for up, lo, ft in legs:
                H = A[up].translation.copy(); K = A[lo].translation.copy(); F = A[ft].translation.copy()
                z0 = A0[ft].translation.z
                T = F.copy(); T.z = F.z + (z0 - F.z) * w
                l1, l2 = (K - H).length, (F - K).length
                d_vec = T - H
                d = min(max(d_vec.length, abs(l1 - l2) + 1e-5), (l1 + l2) * 0.999)
                u = d_vec.normalized()
                n = (K - H).cross(F - H)
                if n.length < 1e-8:
                    raise SystemExit(f"hindPlant: {clip} frame {k} {up}: straight leg, no knee plane")
                n.normalize()
                a = math.acos(max(-1.0, min(1.0, (l1 * l1 + d * d - l2 * l2) / (2 * l1 * d))))
                cands = [H + (Matrix.Rotation(sg * a, 3, n) @ u) * l1 for sg in (1, -1)]
                K2 = min(cands, key=lambda c: (c - K).length)
                T2 = H + u * d
                old = {b: A[b].copy() for b in [up, lo, ft] + descendants(ft)}
                R1 = (K - H).rotation_difference(K2 - H).to_matrix().to_4x4()
                M1 = Matrix.Translation(H) @ R1 @ Matrix.Translation(-H)
                A[up] = M1 @ old[up]
                lo1 = M1 @ old[lo]
                F1 = (M1 @ old[ft]).translation
                R2 = (F1 - K2).rotation_difference(T2 - K2).to_matrix().to_4x4()
                M2 = Matrix.Translation(K2) @ R2 @ Matrix.Translation(-K2)
                A[lo] = M2 @ lo1
                ft_chain = M2 @ M1 @ old[ft]
                loc, q, sc = ft_chain.decompose()
                q0 = A0[ft].decompose()[1]
                q2 = q.slerp(q0, w)
                A[ft] = Matrix.LocRotScale(T2, q2, sc)
                for b in descendants(ft):
                    A[b] = A[ft] @ old[ft].inverted() @ old[b]
                rows.append({"frame": k, "bone": ft, "w": w, "ankleDz": round(T2.z - F.z, 4),
                             "reachClamped": d < d_vec.length - 1e-6})
        report[clip] = rows
    print("HINDPLANT", json.dumps({c: len(r) for c, r in report.items()}),
          json.dumps([r for c in report.values() for r in c if r["reachClamped"]]))
