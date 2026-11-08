"""Cove extension: a corkscrewing water column (oceanid) -- torsional wave + helical whirl on the Tail_* chain.

The oceanid's lower body is a column of water skinned to the snake-tail chain (Tail_00 at the waist down to the
ground; the last links lie on the ground under the foam flare). The DEF column boils in place; a texture-only flow
reads thin on the mesh, so this hook gives the column *geometric* volume motion, baked into ordinary bone
rotation keys (skinned-mesh animation: survives GLB export and the bundle builder, which keeps local rotations):

  twist  every link turns about the world vertical through its own head by
         theta(u, i) = twist.deg * envT(u) * sin(2 pi (i / period - twist.waves * u) + twist.phase)
         -- a torsional wave that travels down the column (u = 0 at the waist, 1 at the ground contact).
  whirl  the column centreline is pulled toward a rotating helix,
         off(u, i) = whirl.radius * envW(u) * (cos, sin)(2 pi (i / period - whirl.turns * u) + whirl.phase)
         (world XY), with fixed link lengths (follow-the-target, as build_unit's tail solve). The helix turns
         counter-clockwise seen from above and its crests travel down -- the corkscrew.

Both are periodic in the clip frame index i with `period` frames, so a looping clip whose frame count is a
multiple of `period` (Idle / Move: 8) closes exactly. Other clips restart the phase at their frame 0 (the
unit-look uvAtlas does the same). The upper body is untouched: the waist links get envT(0) = envW(0) = 0.
Scaled links (death shrink, cove_sink) are handled -- offsets scale with the link, so a hidden body stays hidden;
list this extension BEFORE cove_sink so the sink squashes the corkscrewed pose.

Config (all optional except the block itself; defaults shown):
  "coveCorkscrew": {
    "period": 8,                                   # frames per cycle (Idle clip length)
    "twist": {"deg": 18, "waves": 0.5, "phase": 0.0,
              "env": [[0, 0], [0.35, 0.6], [0.8, 1], [1, 1]]},     # piecewise-linear in u
    "whirl": {"radius": 0.025, "turns": 1.0, "phase": 0.0,
              "env": [[0, 0], [0.4, 1], [0.75, 0.5], [0.9, 0]]},
    "clipGain": {"Death": 0.5},                    # per contract suffix; default 1
    "groundZ": 0.08                                # links whose head is below this ride rigidly with the last
                                                   # column link (the foam flare turns as one piece, no shear)
    "rebindByHeight": true                         # after_skin: see below
  }

Column re-bind (after_skin, "rebindByHeight", default true). The surface-distance tail weights follow a centreline
that veers out along the ground under the flare, and the build cuts ~280 "fused-loop" edges where the sculpted
ridges wrap: neighbouring vertices at one height can belong to links far apart along the chain (Tail_03 next to
Tail_06). That is harmless while the chain moves rigidly, but any twist or bend *between* links tears those seams
(measured: 90-180 edges > 2x per idle frame with the corrective-smooth morphs muted, which is what a runtime that
drops morph curves shows). So each vertex's Tail_* share is re-spread over the *vertical* links by rest height
(linear hats between link mid-heights; above the first mid-height -> Tail_00, below the last -> the last column
link); its non-tail share (the waist blend onto Hips/arms) is kept. Ground links keep no vertices and ride along.
Split (cut) vertices at one position get identical weights, so the cuts stay closed.

Runs at after_skin and before_keys. Prints "HOOK COVE corkscrew ...".
"""
import json
import math


def _interp(env, u):
    if u <= env[0][0]:
        return env[0][1]
    for (a, va), (b, vb) in zip(env, env[1:]):
        if u <= b:
            f = (u - a) / max(b - a, 1e-9)
            return va + (vb - va) * f
    return env[-1][1]


def _column_links(TAILB, TPts, gz):
    return [k for k in range(len(TAILB)) if TPts[k].z >= gz]


def after_skin(g):
    sp = g["cfg"].get("coveCorkscrew")
    TAILB = g.get("TAILB") or []
    if not sp or not TAILB or not sp.get("rebindByHeight", True):
        return
    body, TPts = g["body"], g["TPts"]
    col = _column_links(TAILB, TPts, sp.get("groundZ", 0.08))
    mids = [0.5 * (TPts[k].z + TPts[k + 1].z) for k in col]      # descending heights
    gidx = {vg.name: vg.index for vg in body.vertex_groups}
    tail_ids = {gidx[b] for b in TAILB}
    moved = 0
    for v in body.data.vertices:
        share = sum(ge.weight for ge in v.groups if ge.group in tail_ids)
        if share <= 1e-6:
            continue
        z = v.co.z
        w = [0.0] * len(col)
        if z >= mids[0]:
            w[0] = 1.0
        elif z <= mids[-1]:
            w[-1] = 1.0
        else:
            for j in range(len(col) - 1):
                if mids[j + 1] <= z <= mids[j]:
                    f = (mids[j] - z) / max(mids[j] - mids[j + 1], 1e-9)
                    w[j], w[j + 1] = 1 - f, f
                    break
        for b in TAILB:
            body.vertex_groups[b].remove([v.index])
        for j, k in enumerate(col):
            if w[j] > 1e-4:
                body.vertex_groups[TAILB[k]].add([v.index], share * w[j], 'REPLACE')
        moved += 1
    print("HOOK COVE corkscrew rebind by height: verts", moved, "column links", [TAILB[k] for k in col])


def before_keys(g):
    sp = g["cfg"].get("coveCorkscrew")
    TAILB = g.get("TAILB") or []
    if not sp or not TAILB:
        return
    Matrix, Vector = g["Matrix"], g["Vector"]
    pw, TPts = g["posed_world"], g["TPts"]
    P = float(sp.get("period", 8))
    tw = {"deg": 18.0, "waves": 0.5, "phase": 0.0, "env": [[0, 0], [0.35, 0.6], [0.8, 1], [1, 1]]}
    tw.update(sp.get("twist", {}))
    wh = {"radius": 0.025, "turns": 1.0, "phase": 0.0, "env": [[0, 0], [0.4, 1], [0.75, 0.5], [0.9, 0]]}
    wh.update(sp.get("whirl", {}))
    gain = sp.get("clipGain", {"Death": 0.5})
    gz = sp.get("groundZ", 0.08)

    n = len(TAILB)
    L = [(TPts[k + 1] - TPts[k]).length for k in range(n)]
    ztop = TPts[0].z
    zbot = min(p.z for p in TPts)
    # u by rest height of each chain point (0 = waist, 1 = ground); the ground links all sit near u = 1
    U = [min(1.0, max(0.0, (ztop - p.z) / max(ztop - zbot, 1e-6))) for p in TPts]
    Z = Vector((0, 0, 1))
    stats = {"maxTwistDeg": 0.0, "maxWhirl": 0.0}

    segs = json.load(open(g["MASTER"]))["segments"]
    for s in segs:
        gn = gain.get(s["contractSuffix"], 1.0)
        if gn == 0:
            continue
        for i, t in enumerate(range(s["globalStart"], s["globalEnd"])):
            A = pw[t]
            ph = 2 * math.pi * i / P
            heads = [A[b].translation.copy() for b in TAILB]
            ends = [A[b] @ Vector((0, L[k], 0)) for k, b in enumerate(TAILB)]
            scl = [A[b].to_3x3().col[1].length for b in TAILB]
            new_head = heads[0].copy()
            C = None
            for k, b in enumerate(TAILB):
                if C is not None and TPts[k].z < gz:
                    A[b] = C @ A[b]        # ground links ride rigidly with the last column link (no foot shear)
                    continue
                d = ends[k] - heads[k]
                # whirl target for this link's end (the head of the next link)
                uk1 = U[k + 1]
                a = ph - 2 * math.pi * wh["turns"] * uk1 + wh["phase"]
                r = gn * wh["radius"] * _interp(wh["env"], uk1) * scl[k]
                tgt = ends[k] + Vector((r * math.cos(a), r * math.sin(a), 0.0))
                nd = tgt - new_head
                Rb = d.rotation_difference(nd).to_matrix() if nd.length > 1e-9 and d.length > 1e-9 else Matrix.Identity(3)
                um = 0.5 * (U[k] + U[k + 1])
                th = gn * math.radians(tw["deg"]) * _interp(tw["env"], um) * math.sin(ph - 2 * math.pi * tw["waves"] * um + tw["phase"])
                Rt = Matrix.Rotation(th, 3, Z)
                R = (Rt @ Rb).to_4x4()
                C = Matrix.Translation(new_head) @ R @ Matrix.Translation(-heads[k])
                A[b] = C @ A[b]
                stats["maxTwistDeg"] = max(stats["maxTwistDeg"], abs(math.degrees(th)))
                stats["maxWhirl"] = max(stats["maxWhirl"], abs(r))
                new_head = A[b] @ Vector((0, L[k], 0))
    print("HOOK COVE corkscrew period", P, "twist", tw["deg"], "whirl", wh["radius"],
          "max twist deg %.1f max whirl %.4f" % (stats["maxTwistDeg"], stats["maxWhirl"]))
