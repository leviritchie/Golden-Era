"""Elemental body motion: continuous element-specific motion carried by ordinary bone rotation keys.

This generalises `cove_corkscrew.py` (the oceanid's corkscrew water, which stays as it is) into one rule per
element *mode*, with per-unit knobs in the unit config. Everything is baked into bone keys, so it survives the
GLB export and the bundle builder (local rotations; Hips also keys location/scale). A matching animated texture
flow for the unit-look comes from `tools/homm3_vfx/element_flow_scores.py`, which reads the same config
(`period`, the loop clips) so the texture cells step in phase with the geometry.

Config (unit json):
  "elementMotion": {
    "mode": "corkscrew" | "vortex" | "shimmer" | "coil" | "roil" | "grind" | "crackle" | "crystal",
    "period": 8,               # frames per cycle; a looping clip (cfg "loops", default Idle/Move) of N frames
                               # uses N / max(1, round(N / period)) so it closes exactly
    "carrier": {...},          # optional; the mode's default otherwise (see CARRIERS)
    "twist": {...}, "whirl": {...}, "sway": {...}, "jitter": {...}, "pulse": {...},   # override mode defaults
    "clipGain": {"Death": 0.5}
  }

Carriers (what the motion rides on):
  column  a new vertical chain Col_00..Col_{n-1} under `parent` (default Hips), from the parent joint straight
          down to the lowest affected vertex, created at after_skin. Every vertex below the parent joint gives
          the share it holds on `fromBones` (default [parent]) to the chain, spread by rest height (linear hats
          between link mid-heights, like cove_corkscrew's rebind), faded in over `blend` below the joint; arm or
          other weights are kept. For bodies whose lower part is a column/robe/tornado skinned to the hips.
  tail    the build's existing Tail_* chain (snake/mermaid tails).
  bones   no chain; only the skeleton's own bones (sway / jitter / pulse components).

Components (each optional; a mode is a named set of defaults, see MODES):
  twist   chain links turn about an axis ("vertical": world Z through each link head; "link": the link's own
          direction -- a roll wave along a lying tail) by deg * env(u) * sin(2 pi (i/p - waves*u)), u = 0 at the
          chain root, 1 at its end.
  whirl   chain centreline pulled toward a travelling wave with fixed link lengths: "helix" (world XY offset
          rotating CCW -- the corkscrew) or "lateral" (sideways in the plane of the link and world Z -- a slither).
  sway    listed skeleton bones rotate about their own rest axes by deg * [ax, ay, az] * sin(2 pi (i/p * cycles)
          - lag * k) (k = index in the list, so the wave travels up the list); children follow.
  jitter  listed bones take a deterministic random rotation (deg) that re-rolls every `step` frames and repeats
          every period: stepped 12 fps crackle. Children follow.
  pulse   Hips scales uniformly by 1 + amp * sin(2 pi i/p * cycles) about the Hips head; children follow.

Stages: after_skin (column carrier: bones + weights), after_pose (column bones follow their parent in every
pose, so the silhouette fit and shrink see them), before_keys (motion; the column bones are appended to the
keyed list). List this extension LAST so every other hook's pose changes come first.
Prints "HOOK ELEMENT ...".
"""
import json
import math
import random

MODES = {
    # water column (nymph): the oceanid corkscrew
    "corkscrew": {"carrier": {"type": "tail"},
                  "twist": {"deg": 30, "waves": 0.75, "axis": "vertical", "env": [[0, 0], [0.35, 0.6], [0.8, 1], [1, 1]]},
                  "whirl": {"radius": 0.035, "turns": 1.0, "kind": "helix", "env": [[0, 0], [0.4, 1], [0.75, 0.5], [0.9, 0]]}},
    # tornado lower bodies (air / hurricane / storm): stronger twist toward the tip, two cycles per period
    # (pilot h3_air_elemental: 40 deg / 0.04 / two cycles per period tore +8% muted; these hold it to +1%)
    "vortex": {"carrier": {"type": "column", "links": 6, "blend": 0.15},
               "twist": {"deg": 35, "waves": 1.0, "axis": "vertical", "env": [[0, 0], [0.3, 0.5], [1, 1]]},
               "whirl": {"radius": 0.03, "turns": 1.5, "kind": "helix", "env": [[0, 0], [0.5, 0.7], [1, 1]]}},
    # robes of light (magic / psychic / astral): a slow breathing sway of the hem, one cycle, plus a faint pulse
    "shimmer": {"carrier": {"type": "column", "links": 5},
                "twist": {"deg": 6, "waves": 0.5, "axis": "vertical", "env": [[0, 0], [1, 1]]},
                "whirl": {"radius": 0.015, "turns": 0.5, "kind": "helix", "env": [[0, 0], [1, 1]]},
                "pulse": {"amp": 0.006}},
    # mermaid water (water elemental): a roll wave travelling down the tail plus a small slither
    "coil": {"carrier": {"type": "tail"},
             "twist": {"deg": 14, "waves": 1.0, "axis": "link", "env": [[0, 0.2], [1, 1]]},
             "whirl": {"radius": 0.012, "turns": 1.0, "kind": "lateral", "env": [[0, 0], [0.5, 1], [1, 1]]}},
    # fire / lava / magma: a slow roil that licks upward through the spine chain. The lava/magma DEF idles
    # hold their silhouette still (the magma's whole motion is a glow pulse), so the geometry share is small
    # and element_flow_scores.py carries the rest; a fire elemental's DEF moves (xor/area 0.11), so raise deg.
    "roil": {"carrier": {"type": "bones"},
             "sway": {"deg": 1.5, "axes": [1.0, 0.4, 0.7], "lag": 0.9,
                      "bones": ["Hips", "Spine", "Spine1", "Spine2", "Neck", "Head"]},
             "pulse": {"amp": 0.006}},
    # earth: near-rigid heavy grinding shift, one slow cycle
    "grind": {"carrier": {"type": "bones"},
              "sway": {"deg": 1.5, "axes": [0.3, 1.0, 0.5], "lag": 0.3, "bones": ["Hips", "Spine", "Spine1", "Spine2"]}},
    # energy / plasma: stepped crackle jitter plus a pulse
    "crackle": {"carrier": {"type": "bones"},
                "jitter": {"deg": 2.5, "step": 1, "bones": ["Spine1", "Spine2", "Neck", "Head", "LeftArm", "RightArm",
                                                            "LeftForeArm", "RightForeArm"]},
                "pulse": {"amp": 0.015, "cycles": 2}},
    # ice / frost: a crystalline body -- almost no geometry motion (the texture glints carry it)
    "crystal": {"carrier": {"type": "bones"},
                "pulse": {"amp": 0.004}},
}


def _interp(env, u):
    if u <= env[0][0]:
        return env[0][1]
    for (a, va), (b, vb) in zip(env, env[1:]):
        if u <= b:
            return va + (vb - va) * (u - a) / max(b - a, 1e-9)
    return env[-1][1]


def settings(cfg):
    """Mode defaults merged with the unit's overrides (one level deep per component)."""
    sp = cfg.get("elementMotion")
    if not sp:
        return None
    base = MODES[sp["mode"]]
    out = {"mode": sp["mode"], "period": float(sp.get("period", 8)), "clipGain": sp.get("clipGain", {"Death": 0.5})}
    for k in ("carrier", "twist", "whirl", "sway", "jitter", "pulse"):
        if k in base or k in sp:
            d = dict(base.get(k, {}))
            d.update(sp.get(k, {}))
            if d.get("off"):
                continue
            out[k] = d
    return out


def eff_period(P, suffix, N, loops):
    """Frames per cycle in this clip: a looping clip closes exactly on an integer number of cycles."""
    if suffix in loops and N > 1:
        return N / max(1, round(N / P))
    return P


def chain_names(g, st):
    c = st.get("carrier", {"type": "bones"})
    if c["type"] == "column":
        return g.get("_EM_CHAIN") or []
    if c["type"] == "tail":
        return list(g.get("TAILB") or [])
    return []


# ----------------------------------------------------------------------------- column carrier
def after_skin(g):
    st = settings(g["cfg"])
    if not st or st["carrier"]["type"] != "column":
        return
    import bpy
    from mathutils import Vector
    c = st["carrier"]
    body, rig, J = g["body"], g["rig"], g["J"]
    par = c.get("parent", "Hips")
    frm = set(c.get("fromBones", [par]))
    n = int(c.get("links", 6))
    top = Vector(J[par])
    ax, ay = c.get("axis", [top.x, top.y])
    blend = c.get("blend", 0.08)
    gname = {vg.index: vg.name for vg in body.vertex_groups}
    aff = [v for v in body.data.vertices if v.co.z < top.z and any(gname[ge.group] in frm and ge.weight > 1e-4 for ge in v.groups)]
    if not aff:
        print("HOOK ELEMENT column: no vertices below", par)
        return
    bot = c.get("bottomZ", min(v.co.z for v in aff))
    zs = [top.z + (bot - top.z) * k / n for k in range(n + 1)]
    names = [f"Col_{k:02d}" for k in range(n)]
    bpy.context.view_layer.objects.active = rig
    bpy.ops.object.mode_set(mode='EDIT')
    eb = rig.data.edit_bones
    for k, nm in enumerate(names):
        b = eb.new(nm)
        b.head, b.tail = Vector((ax, ay, zs[k])), Vector((ax, ay, zs[k + 1]))
        b.roll = 0
        b.parent = eb[par] if k == 0 else eb[names[k - 1]]
    bpy.ops.object.mode_set(mode='OBJECT')
    for nm in names:
        body.vertex_groups.new(name=nm)
    mids = [0.5 * (zs[k] + zs[k + 1]) for k in range(n)]
    moved = 0
    for v in aff:
        z = v.co.z
        f = min(1.0, max(0.0, (top.z - z) / max(blend, 1e-6)))
        share = 0.0
        for ge in list(v.groups):
            nm = gname[ge.group]
            if nm in frm:
                take = ge.weight * f
                share += take
                body.vertex_groups[nm].add([v.index], ge.weight - take, 'REPLACE')
        if share <= 1e-6:
            continue
        w = [0.0] * n
        if z >= mids[0]:
            w[0] = 1.0
        elif z <= mids[-1]:
            w[-1] = 1.0
        else:
            for j in range(n - 1):
                if mids[j + 1] <= z <= mids[j]:
                    t = (mids[j] - z) / max(mids[j] - mids[j + 1], 1e-9)
                    w[j], w[j + 1] = 1 - t, t
                    break
        for j, nm in enumerate(names):
            if w[j] > 1e-4:
                body.vertex_groups[nm].add([v.index], share * w[j], 'REPLACE')
        moved += 1
    g["_EM_CHAIN"] = names
    g["_EM_COL"] = {"parent": par, "zs": zs, "axis": [ax, ay]}
    for k, nm in enumerate(names):
        g["parent_of"][nm] = par if k == 0 else names[k - 1]
    print("HOOK ELEMENT column", names[0], "..", names[-1], "under", par, "z %.3f -> %.3f" % (top.z, bot), "verts", moved)


def after_pose(g):
    st = settings(g["cfg"])
    if not st or not g.get("_EM_CHAIN"):
        return
    rest, pw, parent_of = g["rest"], g["posed_world"], g["parent_of"]
    for A in pw:
        for nm in g["_EM_CHAIN"]:
            p = parent_of[nm]
            A[nm] = A[p] @ rest[p].inverted() @ rest[nm]


# ----------------------------------------------------------------------------- motion
def _chain_motion(g, st, A, chain, rest_pts, ph_of, gn, stats):
    Matrix, Vector = g["Matrix"], g["Vector"]
    tw, wh = st.get("twist"), st.get("whirl")
    n = len(chain)
    L = [(rest_pts[k + 1] - rest_pts[k]).length for k in range(n)]
    cum = [0.0]
    for x in L:
        cum.append(cum[-1] + x)
    U = [c / max(cum[-1], 1e-9) for c in cum]
    Z = Vector((0, 0, 1))
    heads = [A[b].translation.copy() for b in chain]
    ends = [A[b] @ Vector((0, L[k], 0)) for k, b in enumerate(chain)]
    scl = [A[b].to_3x3().col[1].length for b in chain]
    new_head = heads[0].copy()
    for k, b in enumerate(chain):
        d = ends[k] - heads[k]
        tgt = ends[k]
        if wh:
            uk1 = U[k + 1]
            a = ph_of(wh) - 2 * math.pi * wh.get("turns", 1.0) * uk1 + wh.get("phase", 0.0)
            r = gn * wh["radius"] * _interp(wh["env"], uk1) * scl[k]
            if wh.get("kind", "helix") == "helix":
                off = Vector((r * math.cos(a), r * math.sin(a), 0.0))
            else:
                side = d.cross(Z)
                side = side.normalized() if side.length > 1e-9 else Vector((1, 0, 0))
                off = side * (r * math.sin(a))
            tgt = ends[k] + off
            stats["maxWhirl"] = max(stats["maxWhirl"], abs(r))
        nd = tgt - new_head
        Rb = d.rotation_difference(nd).to_matrix() if nd.length > 1e-9 and d.length > 1e-9 else Matrix.Identity(3)
        R = Rb
        if tw:
            um = 0.5 * (U[k] + U[k + 1])
            th = gn * math.radians(tw["deg"]) * _interp(tw["env"], um) * math.sin(
                ph_of(tw) - 2 * math.pi * tw.get("waves", 0.5) * um + tw.get("phase", 0.0))
            axis = Z if tw.get("axis", "vertical") == "vertical" else (Rb @ d).normalized()
            R = Matrix.Rotation(th, 3, axis) @ Rb
            stats["maxTwistDeg"] = max(stats["maxTwistDeg"], abs(math.degrees(th)))
        C = Matrix.Translation(new_head) @ R.to_4x4() @ Matrix.Translation(-heads[k])
        A[b] = C @ A[b]
        new_head = A[b] @ Vector((0, L[k], 0))


def _bone_motion(g, st, A, i, p, gn, stats, order):
    """sway / jitter / pulse on skeleton bones, children following (parent-first order)."""
    Matrix, Euler = g["Matrix"], __import__("mathutils").Euler
    rest, parent_of = g["rest"], g["parent_of"]
    loc = {}
    sw = st.get("sway")
    if sw:
        cyc = sw.get("cycles", 1)
        ax = sw.get("axes", [1, 0, 0])
        for k, b in enumerate(sw["bones"]):
            s = math.sin(2 * math.pi * cyc * i / p - sw.get("lag", 0.5) * k)
            c2 = math.sin(2 * math.pi * cyc * i / p - sw.get("lag", 0.5) * k + 1.7)
            deg = gn * sw["deg"] * sw.get("scale", {}).get(b, 1.0)
            e = (math.radians(deg * ax[0] * s), math.radians(deg * ax[1] * c2), math.radians(deg * ax[2] * s * c2 * 2))
            loc[b] = Euler(e).to_matrix().to_4x4()
            stats["maxSwayDeg"] = max(stats["maxSwayDeg"], deg)
    jt = st.get("jitter")
    if jt:
        step = max(1, int(jt.get("step", 1)))
        slot = int((i % max(1, round(p))) // step)
        for b in jt["bones"]:
            rnd = random.Random(f"{b}:{slot}:{jt.get('seed', 3)}")
            e = [math.radians(gn * jt["deg"] * (2 * rnd.random() - 1)) for _ in range(3)]
            M = Euler(e).to_matrix().to_4x4()
            loc[b] = loc[b] @ M if b in loc else M
        stats["jitterDeg"] = jt["deg"]
    pu = st.get("pulse")
    if pu:
        s = 1 + gn * pu["amp"] * math.sin(2 * math.pi * pu.get("cycles", 1) * i / p)
        S = Matrix.Diagonal((s, s, s, 1.0))
        loc["Hips"] = loc["Hips"] @ S if "Hips" in loc else S
        stats["pulse"] = pu["amp"]
    if not loc:
        return
    old = {n: A[n].copy() for n in order}
    D = {}
    for n in order:
        par = parent_of.get(n)
        if par in D:
            A[n] = D[par] @ A[n]
        if n in loc and n in A:
            A[n] = A[n] @ loc[n]
        if par in D or n in loc:
            D[n] = A[n] @ old[n].inverted()


def before_keys(g):
    st = settings(g["cfg"])
    if not st:
        return
    Vector = g["Vector"]
    pw, rest, parent_of = g["posed_world"], g["rest"], g["parent_of"]
    chain = chain_names(g, st)
    if g.get("_EM_CHAIN"):
        after_pose(g)      # re-follow: later stages (refine, tilt clamps, shrink) moved the parent after after_pose
    if chain:
        if st["carrier"]["type"] == "tail":
            TP = g["TPts"]
            rest_pts = [Vector(TP[k]) for k in range(len(chain) + 1)]
        else:
            zs, (ax, ay) = g["_EM_COL"]["zs"], g["_EM_COL"]["axis"]
            rest_pts = [Vector((ax, ay, z)) for z in zs]
    # parent-first order over the posed bones that have parents
    order, seen = [], {"Root"}
    names = [n for n in pw[0] if n != "Root" and n in parent_of]
    while len(order) < len(names):
        prog = False
        for n in names:
            if n not in seen and parent_of[n] in seen | {None}:
                order.append(n); seen.add(n); prog = True
        if not prog:
            order += [n for n in names if n not in seen]
            break
    loops = g.get("LOOPS", ["Idle", "Move"])
    stats = {"maxTwistDeg": 0.0, "maxWhirl": 0.0, "maxSwayDeg": 0.0}
    segs = json.load(open(g["MASTER"]))["segments"]
    for s in segs:
        gn = st["clipGain"].get(s["contractSuffix"], 1.0)
        if gn == 0:
            continue
        N = s["frameCount"]
        p = eff_period(st["period"], s["contractSuffix"], N, loops)
        for i, t in enumerate(range(s["globalStart"], s["globalEnd"])):
            A = pw[t]
            _bone_motion(g, st, A, i, p, gn, stats, order)
            if chain:
                _chain_motion(g, st, A, chain, rest_pts, lambda comp: 2 * math.pi * comp.get("cycles", 1) * i / p, gn, stats)
    if g.get("_EM_CHAIN"):
        for nm in g["_EM_CHAIN"]:
            g["FLAIL"].append((nm, None, None, None))    # the keyed list is built from FLAIL names after this hook
    print("HOOK ELEMENT", st["mode"], "period", st["period"], "carrier", st["carrier"]["type"], "chain", len(chain),
          {k: round(v, 4) if isinstance(v, float) else v for k, v in stats.items()})
