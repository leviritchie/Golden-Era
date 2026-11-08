"""Articulated whip: a bone chain along a held whip (Inferno pit fiends; hook for build_unit.py).

The `props` cut binds a whip rigidly to the hand, so the coil only swings as one piece and can never lash out
straight the way the HoMM3 DEF whip cracks forward (pit fiend / pit lord g12 attack, the whip flung up in g05
death). This hook puts the whip on a chain of bones that follows its traced centreline:

  "whipChain": {"parent": "RightHand", "prop": "whip", "bones": 10,
                "grip": 0.12, "gripBlend": 0.10, "radius": 0.09}

  prop      the `props` entry whose "segments" polyline (hand first, Blender body axes) the chain follows
  bones     chain length; the polyline from `grip` (arc length from the hand end) to its far end is cut into
            this many equal bones Whip_00 .. Whip_NN, each parented to the one before, Whip_00 to `parent`
  grip      arc length kept on the hand (the grip inside the fist); the whip eases from the hand onto Whip_00
            over the next `gripBlend`
  radius    only vertices within this distance of the polyline are re-weighted
  prefix    optional bone-name prefix (default "Whip"). The same chain serves a tail: a `props` entry bound to
            "Hips" along the tail's centreline, "parent": "Hips", "prefix": "Tail" (h3_vermin, 2026-10-10)

Weights (before_keys): a vertex bound rigidly to `parent` (weight >= 0.99, i.e. cut free by the props region) and within
`radius` of the polyline is projected to its nearest polyline point (arc length s) and weighted by linear hat
functions centred on the bone mid-points, so neighbouring bones blend and a bend never opens a crack (no edge
split). Vertices before the grip keep the hand. Each vertex has at most 2 bones from the chain plus the hand.

Motion: after_pose makes every chain bone follow its parent rigidly in every frame (the whip behaves exactly as
the rigid prop did until something keys it); before_keys registers the chain on the free-bone list so it is
keyed. Clip-specific whip motion (the forward lash, the death fling) comes from the GLB patch lane
(keyRotations on Whip_* from a DEF fit), so the rig stays one build.

Hooks: after_skin (bones), after_pose (chain follows the hand), before_keys (chain re-derived from the final hand
pose after silhouetteRefine's propAim, which fits the still hand-rigid whip; then the weights; then keying).
"""
import numpy as np
from mathutils import Vector


def _spec(g):
    return g["cfg"].get("whipChain")


def _polyline(g, s):
    prop = next(p for p in g["cfg"].get("props", []) if p.get("name") == s.get("prop", "whip"))
    pts = [prop["segments"][0][0]] + [b for _, b in prop["segments"]]
    P = np.array(pts, float)
    L = np.r_[0.0, np.cumsum(np.linalg.norm(np.diff(P, axis=0), axis=1))]
    return P, L


def _at(P, L, s):
    k = int(np.clip(np.searchsorted(L, s) - 1, 0, len(P) - 2))
    f = (s - L[k]) / max(L[k + 1] - L[k], 1e-12)
    return P[k] + (P[k + 1] - P[k]) * f


def _names(s):
    pre = s.get("prefix", "Whip")
    return [f"{pre}_{k:02d}" for k in range(int(s["bones"]))]


def after_skin(g):
    s = _spec(g)
    if not s:
        return
    bpy = g["bpy"]; rig = g["rig"]; body = g["body"]
    P, L = _polyline(g, s)
    n = int(s["bones"]); grip = float(s.get("grip", 0.12)); gb = float(s.get("gripBlend", 0.10))
    R = float(s.get("radius", 0.09)); par = s.get("parent", "RightHand")
    cuts = np.linspace(grip, L[-1], n + 1)
    names = _names(s)
    bpy.context.view_layer.objects.active = rig
    bpy.ops.object.mode_set(mode='EDIT')
    eb = rig.data.edit_bones
    for k, nm in enumerate(names):
        b = eb.new(nm); b.head = Vector(_at(P, L, cuts[k])); b.tail = Vector(_at(P, L, cuts[k + 1])); b.roll = 0
        b.parent = eb[par] if k == 0 else eb[names[k - 1]]
    bpy.ops.object.mode_set(mode='OBJECT')
    for nm in names:
        if nm not in body.vertex_groups:
            body.vertex_groups.new(name=nm)
    print("WHIPCHAIN bones", n, "length", round(float(L[-1] - grip), 3))


def _weights(g, s):
    body = g["body"]
    P, L = _polyline(g, s)
    n = int(s["bones"]); grip = float(s.get("grip", 0.12)); gb = float(s.get("gripBlend", 0.10))
    R = float(s.get("radius", 0.09)); par = s.get("parent", "RightHand")
    cuts = np.linspace(grip, L[-1], n + 1)
    names = _names(s)
    gi = {vg.name: vg.index for vg in body.vertex_groups}
    hand = gi[par]
    centres = (cuts[:-1] + cuts[1:]) / 2
    A, B = P[:-1], P[1:]; AB = B - A; ab2 = np.maximum((AB * AB).sum(1), 1e-12)
    moved = 0
    for v in body.data.vertices:
        w = {gg.group: gg.weight for gg in v.groups if gg.weight > 1e-6}
        tot = sum(w.values())
        if tot <= 0 or w.get(hand, 0.0) / tot < 0.99:
            continue
        p = np.array(v.co[:])
        t = np.clip(((p - A) * AB).sum(1) / ab2, 0, 1)
        d = np.linalg.norm(A + AB * t[:, None] - p, axis=1)
        k = int(np.argmin(d))
        if d[k] > R:
            continue
        sv = L[k] + t[k] * (L[k + 1] - L[k])
        if sv <= grip:
            continue
        on = min(1.0, (sv - grip) / gb) if gb > 0 else 1.0
        cw = np.zeros(n)
        if sv <= centres[0]:
            cw[0] = 1.0
        elif sv >= centres[-1]:
            cw[-1] = 1.0
        else:
            j = int(np.searchsorted(centres, sv) - 1)
            f = (sv - centres[j]) / (centres[j + 1] - centres[j])
            cw[j], cw[j + 1] = 1 - f, f
        for gid in list(w):
            body.vertex_groups[gid].remove([v.index])
        if on < 1.0:
            body.vertex_groups[hand].add([v.index], 1.0 - on, 'REPLACE')
        for j in np.nonzero(cw > 1e-6)[0]:
            body.vertex_groups[gi[names[j]]].add([v.index], float(cw[j] * on), 'REPLACE')
        moved += 1
    print("WHIPCHAIN verts", moved)
    return moved


def after_pose(g):
    s = _spec(g)
    if not s:
        return
    rest = g["rest"]; parent_of = g["parent_of"]; par = s.get("parent", "RightHand")
    names = _names(s)
    for k, nm in enumerate(names):
        rest[nm] = g["rig"].data.bones[nm].matrix_local.copy()
        parent_of[nm] = par if k == 0 else names[k - 1]
    for A in g["posed_world"]:
        for nm in names:
            p = parent_of[nm]
            A[nm] = A[p] @ rest[p].inverted() @ rest[nm]


def before_keys(g):
    s = _spec(g)
    if not s:
        return
    # silhouetteRefine's propAim swings the hand (it fits the vertices rigid on the hand: the whip, still unweighted
    # to the chain here), so the chain is re-derived from the final hand pose, and only then does the whip move onto
    # it. The chain rides the hand rigidly, so every skinned position is unchanged by the re-weighting.
    rest = g["rest"]; parent_of = g["parent_of"]
    for A in g["posed_world"]:
        for nm in _names(s):
            p = parent_of[nm]
            A[nm] = A[p] @ rest[p].inverted() @ rest[nm]
    if not _weights(g, s):
        raise SystemExit("whipChain: no whip vertex moved onto the chain (check prop / radius)")
    g["RUBBLE_BONES"].extend(_names(s))   # keyed with location + scale (free-bone list), like propBones
    print("WHIPCHAIN keyed", len(_names(s)))
