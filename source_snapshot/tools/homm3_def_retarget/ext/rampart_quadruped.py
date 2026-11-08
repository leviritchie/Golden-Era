"""Rampart: four-legged bodies (unicorns, pegasi, centaur horse halves, dragons).

The DEF captures are human skeletons fitted to horse / dragon sprites (two unicorn captures even
used an Eagle skeleton build_unit.py cannot read), so their legs carry no usable motion. This
module drives the four-legged parts itself and fits the big body moves to the DEF silhouette.

Unit config key "quadruped":
  "staticCapture": true      ignore the capture: every bone starts at rest each frame (the unit
                             is driven only by this module, the core wings and the core refine).
                             The capture file is replaced by a static human pose of the DEF's
                             frame count, which also lets foreign (Eagle) capture skeletons build.
  "reset": [bone, ...]       bones put back to rest-relative-to-parent before the procedural pose
                             (a centaur's hips and hind legs); other bones keep the capture's
                             world rotation and are re-chained onto their parents.
  "resetClips": {clip: [bone, ...]}
                             the same reset, only in the named clips (a standing bird's legs in its
                             Hitted / Mouseover, whose donor capture drops one leg 0.04-0.11 of the
                             height through the floor while the DEF's bottom row stays on it: delta
                             retarget makes idle frame 0 the rest pose, so rest-relative-to-parent
                             is the Idle stance and the clip enters from it without a pop).
  "legs": [{"bones": [upper, middle, lower], "front": bool, "phase": 0|0.5}, ...]
                             leg chains; Move / MoveStart / MoveEnd get a trot (diagonal pairs
                             share a phase, one cycle per Move clip so the loop closes).
  "gait": {"swing": 24, "bendMid": 38, "bendLow": 25, "bob": 0.02}  (degrees, scene units)
  "tail": {"points": [[x,y,z], ...], "region": <box|segments+radius|sphere>, "parent": "Hips",
           "rootBlend": 1.0, "sway": 8, "lift": 4, "moveSway": 14}
                             a bone chain along the tail; vertices inside the region are weighted
                             along the chain (blend between neighbouring bones), the first
                             `rootBlend` segments easing into their heat weights; every clip sways
                             it in a travelling wave.
  "chains": [{"prefix": "QFL", "points": [...], "region": ..., "parent": "Spine", "rootBlend": 0.5}]
                             extra bone chains built and weighted like the tail (no sway), e.g. a
                             centaur's front horse legs; name their bones (<prefix>_00, _01, ...) in
                             "legs" to give them the trot. Chain bones are always reset to their
                             parent's frame, so they follow the horse body, not the capture.
  "settle": {"clips": ["Death"], "bones": ["Spine1", ...], "reach": 0.6}
                             in these clips the listed bones ease from the capture back to rest
                             relative to their parent, reaching rest at `reach` of the clip; children
                             keep their world rotation and are re-chained.
  "nod": {"bones": ["Neck"], "deg": 3}   idle head nod.
  "restYawDeg": 90           the Meshy mesh does not face -Y (h3_pristine_unicorn faces -X): after
                             skinning, turn the rest mesh, every rest bone and J about +Z so the unit
                             faces -Y like every other unit (this module's axes and the GLB assume it).
                             Joints, tail points and the tail region stay in the mesh's own frame.
  "fit": {"pitch": [-20, 75], "fold": 70, "side": 95, "sideClips": ["Death"],
          "foldLegs": [bones of each front leg's upper, middle], "lambda": 0.002,
          "endFrames": 2, "sideEnd": 85, "sideRampFrames": 0}
                             the last endFrames frames of a side clip are rolled >= sideEnd; with
                             sideRampFrames > 0 the frames before them get a minimum roll rising
                             linearly toward sideEnd, so the body does not snap onto its flank.
                             per-frame silhouette search (needs "silhouetteRefine" so the core
                             builds its skinning/splat helpers): body pitch about the hind feet
                             (rearing; negative about the front feet), front-leg fold, and in
                             sideClips a roll onto the flank about a ground line; each is baked
                             into the world poses before the actions are written.
  "fit": {..., "groundClips": ["Idle", "Mouseover", "Hitted", "Defence", "AttackFront"]}
                             opt-in: the fit's vertical screen offset dy is pinned to 0 in these clips,
                             so the body stays on the floor its posed feet stand on. For a flier whose
                             sprite sits higher in the DEF frame than the posed body, the free dy lifted
                             every ground clip +13..+18 px (h3_griffin line, 2026-09-29: Idle hovering
                             0.13 of the height above the floor while the DEF idle rears on the ground).
                             Flight stays in the clips not listed. Absent: the search is exactly as before.
  "fit": {..., "dyEase": {"MoveEnd": "out", "Death": "in"}}
                             opt-in, for clips that touch the ground at one end: the dy range shrinks
                             (smoothstep) to 0 at that end, "out" at the last frame (a landing: the free
                             fit had MoveEnd RISE 7 -> 15 px and end 0.22 of the height above the idle
                             floor), "in" at the first (Death starts from the stance: the fit had it enter
                             +9 px, its Hips 0.13 above Idle's). An "in" clip that is also a sideClip eases
                             its roll's upper limit the same way (it enters unrolled). Composes with the
                             sideClips end limits.
  "fit": {..., "dx": [-4, 4]}
                             opt-in: the fit's horizontal screen offset range in px (default [-40, 40]).
                             The free dx slid the whole body to follow the sprite's outline (h3_centaur_captain
                             Defence: -17 px, the Hips 0.14 of the height sideways while the DEF stands; user
                             2026-10-09: "too much full body rotation to cheat movements"). A narrow range keeps
                             the body where its feet stand; side-clip end frames keep their own limits.
  "fit": {..., "dxClips": {"AttackFront": [-31, -22]}}
                             opt-in: a per-clip dx range replacing "dx" for that clip (side-clip end frames keep
                             their own). For a unit whose whole fit sits at a constant screen offset (the diamond
                             dragon's Idle at -26 px), a window around that offset keeps a ground clip's body on
                             its feet instead of sliding it 40+ px to follow a lunge or a recoil (2026-10-10 lane-A,
                             the send-back rule: no whole-body translation standing in for part-body motion).
  "fit": {..., "pitchClips": {"Defence": [0, 0]}}
                             opt-in: a per-clip whole-body pitch range replacing "pitch" for that clip (side-clip
                             end frames keep their own). For clips whose DEF keeps the body planted while the
                             rider moves (a turn-away guard, a bow draw): the free pitch tipped the whole horse
                             10 deg to follow the rider's outline (h3_centaur_captain/ranger Defence, ranger
                             ShootFront, 2026-10-09 send-back).
"""
import json, math, os
import numpy
from mathutils import Matrix, Vector

_STATE = {}


def _about(p, M3):
    return Matrix.Translation(p) @ M3.to_4x4() @ Matrix.Translation(-p)


class _NP:
    """numpy stand-in for build_unit's globals whose load() returns a static human capture."""
    def __init__(self, capture_path, T):
        self._cap, self._T = os.path.normcase(os.path.abspath(capture_path)), T

    def __getattr__(self, k):
        return getattr(numpy, k)

    def load(self, p, *a, **kw):
        if isinstance(p, str) and os.path.normcase(os.path.abspath(p)) == self._cap:
            J = {"Hips": (0, 0, 1.0), "Spine": (0, 0, 1.1), "Spine1": (0, 0, 1.2), "Spine2": (0, 0, 1.3),
                 "Neck": (0, 0, 1.45), "Head": (0, 0, 1.55), "HeadTop_End": (0, 0, 1.75)}
            for s, x in (("Left", 1), ("Right", -1)):
                J.update({s + "Shoulder": (0.05 * x, 0, 1.4), s + "Arm": (0.18 * x, 0, 1.4), s + "ForeArm": (0.2 * x, 0, 1.12),
                          s + "Hand": (0.21 * x, 0, 0.88), s + "UpLeg": (0.1 * x, 0, 1.0), s + "Leg": (0.1 * x, 0, 0.55),
                          s + "Foot": (0.1 * x, 0, 0.1), s + "ToeBase": (0.1 * x, -0.1, 0.02), s + "Toe_End": (0.1 * x, -0.2, 0.02)})
            names = list(J)
            P = numpy.tile(numpy.array([J[n] for n in names], float)[None], (self._T, 1, 1))
            return {"pred_position": P, "joint_names": numpy.array(["mixamorig:" + n for n in names])}
        return numpy.load(p, *a, **kw)


def _region_test(reg):
    if reg.get("below"):
        # opt-in "below": [point, normal] half-space cut on top of the region (griffin beak: the lower mandible is
        # the part of the jaw box under the mouth-line plane that mouth_split surgery cut the mesh along)
        base = _region_test({k: v for k, v in reg.items() if k != "below"})
        c, n = Vector(reg["below"][0]), Vector(reg["below"][1])
        return lambda p: base(p) and (p - c).dot(n) < 0
    if reg.get("exclude"):
        base = _region_test({k: v for k, v in reg.items() if k != "exclude"})
        ex = [_region_test(e) for e in reg["exclude"]]
        return lambda p: base(p) and not any(e(p) for e in ex)
    if "segments" in reg:
        segs = [(Vector(a), Vector(b)) for a, b in reg["segments"]]; r = reg["radius"]
        def seg(p, a, b):
            ab = b - a; t = max(0.0, min(1.0, (p - a).dot(ab) / max(ab.dot(ab), 1e-12))); return (p - (a + ab * t)).length
        return lambda p: min(seg(p, a, b) for a, b in segs) < r
    if "sphere" in reg:
        c, r = Vector(reg["sphere"][0]), reg["sphere"][1]
        return lambda p: (p - c).length < r
    lo, hi = Vector(reg["box"][0]), Vector(reg["box"][1])
    return lambda p: all(lo[i] <= p[i] <= hi[i] for i in range(3))


def _rest_yaw(g, deg):
    import bpy
    Rz = Matrix.Rotation(math.radians(deg), 3, 'Z')
    body, rig = g["body"], g["rig"]
    for v in body.data.vertices:
        v.co = Rz @ v.co
    body.data.update()
    bpy.context.view_layer.objects.active = rig
    bpy.ops.object.mode_set(mode='EDIT')
    for b in rig.data.edit_bones:
        z = b.z_axis.copy()
        b.head, b.tail = Rz @ b.head, Rz @ b.tail
        b.align_roll(Rz @ z)
    bpy.ops.object.mode_set(mode='OBJECT')
    for k in list(g["J"]):
        g["J"][k] = tuple(Rz @ Vector(g["J"][k]))
    print("QUADRUPED rest yaw", deg)
    return Rz


def after_skin(g):
    cfg = g["cfg"]; Q = cfg.get("quadruped", {})
    Rz = _rest_yaw(g, Q["restYawDeg"]) if Q.get("restYawDeg") else Matrix.Identity(3)
    if Q.get("staticCapture"):
        T = len(json.load(open(g["MASTER"]))["frames"])
        g["np"] = _NP(g["CAPTURE"], T)
    chains = []
    if Q.get("tail"):
        _STATE["tail"] = _add_chain(g, "QTail", Q["tail"], Rz); chains += _STATE["tail"]
    for C in Q.get("chains", []):
        chains += _add_chain(g, C["prefix"], C, Rz)
    _STATE["chains"] = chains
    for SW in Q.get("segmentWeights", []):
        _segment_weights(g, SW, Rz)


def _segment_weights(g, SW, Rz):
    """quadruped.segmentWeights [{"bones": [b0, b1, ...], "points": [p1, ...], "region": ..., "blend": 0.02}]
    (authenticity rubric 3a, 2026-10-07, opt-in): bone heat smeared the griffin's Neck over the whole skull (2249
    Neck-dominant vertices up to the crown, the Head bone owned only the beak), so a head turn bent the beak off a
    still skull. Inside `region`, each vertex's total weight on `bones` is re-split by its coordinate along the
    straight axis points[0] -> points[-1]: below cut points[0] it belongs to b0, between cut k-1 and k to bk,
    above the last cut to the last bone (len(bones) == len(points) + 1), with a linear blend within `blend`
    (scene units) of each cut. Weight on other bones (shoulders, wings) is kept. Mesh frame like the tail."""
    body = g["body"]; vg = body.vertex_groups
    P = [numpy.array((Rz @ Vector(p))[:]) for p in SW["points"]]
    bones = SW["bones"]
    if len(bones) != len(P) + 1:
        raise SystemExit(f"segmentWeights: {len(bones)} bones need {len(bones) - 1} points, got {len(P)}")
    ax = P[-1] - P[0]; ax = ax / max(numpy.linalg.norm(ax), 1e-9)
    cuts = [float(p @ ax) for p in P]
    blend = float(SW.get("blend", 0.02))
    inside0 = _region_test(SW["region"]); Ri = Rz.inverted()
    gi = {x.index: x.name for x in vg}
    for b in bones:
        if b not in vg:
            vg.new(name=b)
    bset = set(bones); changed = 0
    for v in body.data.vertices:
        if not inside0(Ri @ v.co):
            continue
        row = {gi.get(x.group, vg[x.group].name): x.weight for x in v.groups if x.weight > 0}
        pool = sum(w for k, w in row.items() if k in bset)
        if pool < 1e-4:
            continue
        s = float(numpy.array(v.co[:]) @ ax)
        k = sum(1 for c in cuts if s > c)
        dist = {bones[k]: 1.0}
        for j, c in enumerate(cuts):                       # cut j separates bones[j] | bones[j+1]
            if abs(s - c) < blend:
                f = 0.5 * (1.0 + (s - c) / blend)          # share of the upper bone
                dist = {bones[j]: 1.0 - f, bones[j + 1]: f}
                break
        new = {kk: w for kk, w in row.items() if kk not in bset}
        for kk, f in dist.items():
            new[kk] = new.get(kk, 0.0) + f * pool
        top = sorted(new.items(), key=lambda kv: -kv[1])[:4]; tt = sum(w for _, w in top)
        for x in list(v.groups):
            vg[x.group].remove([v.index])
        for kk, w in top:
            if w > 1e-5:
                vg[kk].add([v.index], w / tt, 'REPLACE')
        changed += 1
    print("QUADRUPED segmentWeights", bones, "verts", changed)


def _add_chain(g, prefix, TC, Rz):
    """Bone chain along TC['points'] (mesh frame), parented to TC['parent'] (Hips); vertices inside
    TC['region'] are weighted along it (see the module docstring, \"tail\")."""
    import bpy
    rig, body, eb_names = g["rig"], g["body"], []
    pts = [Rz @ Vector(p) for p in TC["points"]]
    par = TC.get("parent", "Hips")
    bpy.context.view_layer.objects.active = rig
    bpy.ops.object.mode_set(mode='EDIT')
    eb = rig.data.edit_bones
    for k in range(len(pts) - 1):
        n = f"{prefix}_{k:02d}"; b = eb.new(n); b.head, b.tail = pts[k], pts[k + 1]; b.roll = 0
        b.parent = eb[par] if k == 0 else eb[f"{prefix}_{k - 1:02d}"]; eb_names.append(n)
    # opt-in "reparent": existing bones (the griffin's Head) re-hung under the chain's last bone, so a neck
    # segment inserted between Neck and Head carries the head (authenticity rubric 3a, 2026-10-07)
    for rb in TC.get("reparent", []):
        eb[rb].use_connect = False; eb[rb].parent = eb[eb_names[-1]]
    bpy.ops.object.mode_set(mode='OBJECT')
    names = g["bone_names"]
    at = names.index(par) + 1 if TC.get("reparent") else len(names)   # parents before children (pose loops)
    for k, n in enumerate(eb_names):
        body.vertex_groups.new(name=n)
        names.insert(at + k, n); g["parent_of"][n] = par if k == 0 else eb_names[k - 1]
        g["DRIVE_SRC"][n] = "Hips"          # rigid with the hips in pose_frame; this module moves it
    for rb in TC.get("reparent", []):
        g["parent_of"][rb] = eb_names[-1]
    inside0 = _region_test(TC["region"]); Ri = Rz.inverted()
    inside = lambda p: inside0(Ri @ p)
    P = numpy.array([p[:] for p in pts]); NT = len(eb_names)
    RB = TC.get("rootBlend", 1.0)
    SB = TC.get("blend")
    vg = body.vertex_groups; n_t = 0
    for v in body.data.vertices:
        if not inside(v.co):
            continue
        p = numpy.array(v.co[:]); best = (1e9, 0.0)
        for k in range(NT):
            a, b = P[k], P[k + 1]; ab = b - a
            t = float(numpy.clip((p - a) @ ab / max(ab @ ab, 1e-12), 0, 1))
            d = float(numpy.linalg.norm(p - (a + t * ab)))
            if d < best[0]:
                best = (d, k + t)
        u = best[1]
        if SB is not None:
            # opt-in "blend" (segment units): each segment owns its vertices, linear blend only within SB of a
            # joint, so a talon / tail joint folds cleanly instead of smearing over whole segments (tear gate)
            k = min(int(u), NT - 1); fr = u - k; w = numpy.zeros(NT); w[k] = 1.0
            if k > 0 and fr < SB:
                f = 0.5 * (1 - fr / SB); w[k], w[k - 1] = 1 - f, f
            elif k < NT - 1 and 1 - fr < SB:
                f = 0.5 * (1 - (1 - fr) / SB); w[k], w[k + 1] = 1 - f, f
        else:
            w = numpy.maximum(0, 1 - numpy.abs(u - (numpy.arange(NT) + 0.5)))
            if u < 0.5:
                w[0] = 1.0
            if u > NT - 0.5:
                w[-1] = 1.0
        w /= w.sum()
        keep = max(0.0, 1.0 - u / RB) if RB > 0 else 0.0     # ease into the heat weights at the root
        for x in list(v.groups):
            x.weight *= keep
        for k in numpy.nonzero(w > 1e-4)[0]:
            vg[eb_names[k]].add([v.index], float(w[k]) * (1 - keep), 'REPLACE')
        # glTF skins carry at most 4 influences: keep the 4 largest, renormalised
        gs = sorted(((x.weight, x.group) for x in v.groups if x.weight > 0), reverse=True)
        for w_, gi_ in gs[4:]:
            vg[gi_].remove([v.index])
        tot = sum(w_ for w_, _ in gs[:4])
        for w_, gi_ in gs[:4]:
            vg[gi_].add([v.index], w_ / tot, 'REPLACE')
        n_t += 1
    print("QUADRUPED chain", prefix, "bones", NT, "verts", n_t)
    return eb_names


def _children(parent_of):
    ch = {}
    for b, p in parent_of.items():
        ch.setdefault(p, []).append(b)
    return ch


def _subtree(ch, b):
    out = [b]; i = 0
    while i < len(out):
        out += ch.get(out[i], []); i += 1
    return out


def _clip_of(master):
    segs = json.load(open(master))["segments"]
    info = {}
    for s in segs:
        for i, t in enumerate(range(s["globalStart"], s["globalEnd"])):
            info[t] = (s["contractSuffix"], i, s["frameCount"])
    return info


def after_pose(g):
    cfg = g["cfg"]; Q = cfg.get("quadruped", {})
    rest, parent_of, bone_names, posed_world = g["rest"], g["parent_of"], g["bone_names"], g["posed_world"]
    info = _clip_of(g["MASTER"])
    ch = _children(parent_of)
    reset = set(Q.get("reset", [])) | set(_STATE.get("chains", []))   # chains follow their parent, not the capture
    lat0 = Vector((1, 0, 0))
    G = dict({"swing": 24, "bendMid": 38, "bendLow": 25, "bob": 0.02}, **Q.get("gait", {}))
    TC = Q.get("tail", {}); tail = _STATE.get("tail", [])
    nod = Q.get("nod", {"bones": ["Neck"], "deg": 3})
    reset_clips = {c: set(bs) for c, bs in Q.get("resetClips", {}).items()}
    for t, A in enumerate(posed_world):
        clip, i, n = info.get(t, ("Idle", 0, 1))
        reset_t = reset | reset_clips.get(clip, set())
        # re-chain: reset bones to rest-relative-to-parent, others keep world rotation
        for b in bone_names:
            p = parent_of[b]
            if p not in A:
                continue
            head = A[p] @ (rest[p].inverted() @ rest[b].translation)
            if b in reset_t:
                A[b] = A[p] @ rest[p].inverted() @ rest[b]
            else:
                A[b] = Matrix.Translation(head) @ A[b].to_3x3().to_4x4()
        ST = Q.get("settle")
        if ST and clip in ST.get("clips", ["Death"]):
            # ease the captured bones back to rest-relative-to-parent over the clip (a centaur's human
            # torso would otherwise fold under the horse when the fit rolls the body onto its flank)
            wgt = min(1.0, (i + 1) / max(1, n * ST.get("reach", 0.6)))
            for b in ST["bones"]:
                p = parent_of[b]
                if b not in A or p not in A:
                    continue
                R_rest = (A[p] @ rest[p].inverted() @ rest[b]).to_quaternion()
                q = A[b].to_quaternion().slerp(R_rest, wgt)
                A[b] = Matrix.Translation(A[b].translation) @ q.to_matrix().to_4x4()
                for c in _subtree(ch, b)[1:]:
                    pc = parent_of[c]
                    A[c] = Matrix.Translation(A[pc] @ (rest[pc].inverted() @ rest[c].translation)) @ A[c].to_3x3().to_4x4()
        amp = {"Move": 1.0}.get(clip, 0.0)
        if clip == "MoveStart":
            amp = (i + 1) / (n + 1)
        if clip == "MoveEnd":
            amp = 1 - (i + 1) / (n + 1)
        ph = 2 * math.pi * i / max(n, 1)
        lat = (A["Hips"].to_3x3() @ rest["Hips"].to_3x3().inverted()) @ lat0

        def rot(b, deg, axis):
            if abs(deg) < 1e-6 or b not in A:
                return
            M = _about(A[b].translation.copy(), Matrix.Rotation(math.radians(deg), 3, axis))
            for c in _subtree(ch, b):
                A[c] = M @ A[c]
        if amp > 0:
            for L in Q.get("legs", []):
                bs = L["bones"]; f = ph + 2 * math.pi * L.get("phase", 0.0)
                sgn = 1 if L.get("front") else -1
                rot(bs[0], -G["swing"] * amp * math.sin(f), lat)
                lift = max(0.0, math.cos(f)) * amp
                if len(bs) > 1:
                    rot(bs[1], sgn * G["bendMid"] * lift, lat)
                if len(bs) > 2:
                    rot(bs[2], -sgn * G["bendLow"] * lift, lat)
            bob = G["bob"] * amp * abs(math.sin(ph))
            for b in list(A):
                if b != "Root":
                    A[b] = Matrix.Translation(Vector((0, 0, bob))) @ A[b]
        if clip in ("Idle", "Mouseover"):
            for b in nod.get("bones", []):
                rot(b, nod.get("deg", 3) * math.sin(ph), lat)
        if tail:
            sway = TC.get("moveSway", 14) if amp > 0 else TC.get("sway", 8)
            for k, b in enumerate(tail):
                w = (k + 1) / len(tail)
                rot(b, sway * w * math.sin(ph - 0.7 * k) / len(tail) * 2, Vector((0, 0, 1)))
                rot(b, TC.get("lift", 4) * w * math.sin(ph - 0.7 * k + 1.0) / len(tail) * 2, lat)
    print("QUADRUPED pose", len(posed_world), "frames")


def before_keys(g):
    cfg = g["cfg"]; Q = cfg.get("quadruped", {}); F = Q.get("fit")
    if not F or not g.get("REFINE"):
        return
    skin, def_mask = g["skin"], g["def_mask"]
    posed_world, rest, parent_of, ms_frames = g["posed_world"], g["rest"], g["parent_of"], g["ms_frames"]
    RUB = set(g.get("RUBBLE_BONES", []))
    WINGS = g.get("WINGS", [])
    info = _clip_of(g["MASTER"])
    ch = _children(parent_of)
    lo_p, hi_p = F.get("pitch", [-20, 75]); fold_max = F.get("fold", 70); side_max = F.get("side", 95)
    side_clips = set(F.get("sideClips", ["Death"])); lam = F.get("lambda", 0.002)
    ground_clips = set(F.get("groundClips", []))
    pitch_clips = {c: tuple(v) for c, v in F.get("pitchClips", {}).items()}
    dx_clips = {c: tuple(v) for c, v in F.get("dxClips", {}).items()}
    if ground_clips & side_clips:
        raise SystemExit(f"quadruped.fit.groundClips {sorted(ground_clips & side_clips)} are also sideClips (their dy is set there)")
    dy_ease = dict(F.get("dyEase", {}))
    if set(dy_ease) & ground_clips or not set(dy_ease.values()) <= {"in", "out"}:
        raise SystemExit(f"quadruped.fit.dyEase {dy_ease}: values must be in/out and clips not in groundClips")
    fold_legs = F.get("foldLegs", [])
    wing_max = F.get("wing", 0) if WINGS else 0
    hind = [L["bones"] for L in Q.get("legs", []) if not L.get("front")]
    front = [L["bones"] for L in Q.get("legs", []) if L.get("front")]
    lat0 = Vector((1, 0, 0))
    SW, SH = g["SW"], g["SH"]; bx0, by0, bx1, by1 = g["bx0"], g["by0"], g["bx1"], g["by1"]

    # own sprite camera: the core camera looks at the unit almost from the front, which suits a
    # standing human but foreshortens a horse or dragon to a column; the yaw that best matches
    # idle frame 0 is searched here and used for this fit only (renders/metrics keep the core one)
    def cam(yaw):
        f = Matrix.Rotation(math.radians(yaw), 3, Vector((0, 0, 1))) @ g["fwd_cam"]
        r = f.cross(Vector((0, 0, 1))).normalized(); u = r.cross(f).normalized()
        V0 = numpy.array([v.co[:] for v in g["body"].data.vertices])
        xs, ys = V0 @ numpy.array(r), V0 @ numpy.array(u)
        s = (by1 - by0) / (ys.max() - ys.min()); oy = by1 + s * ys.min(); ox = (bx0 + bx1) / 2 - s * (xs.max() + xs.min()) / 2
        return numpy.array(r), numpy.array(u), s, ox, oy

    def splat(P, C):
        R_, U_, s, ox, oy = C
        x = numpy.round(ox + s * (P @ R_)).astype(int); y = numpy.round(oy - s * (P @ U_)).astype(int)
        ok = (x >= 1) & (x < SW - 1) & (y >= 1) & (y < SH - 1)
        m = numpy.zeros((SH, SW), bool); m[y[ok], x[ok]] = True
        o = m.copy()
        for dy_, dx_ in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (-1, -1), (1, -1), (-1, 1)):
            o |= numpy.roll(numpy.roll(m, dy_, 0), dx_, 1)
        return o

    def feet(A, chains):
        return [A[c[-1]] @ Vector((0, g["rig"].data.bones[c[-1]].length, 0)) for c in chains]

    def apply(A, p, C):
        A = dict(A)
        lat = (A["Hips"].to_3x3() @ rest["Hips"].to_3x3().inverted()) @ lat0
        f = p.get("fold", 0.0)
        if f:
            for chain in fold_legs:
                for k, b in enumerate(chain[:2]):
                    M = _about(A[b].translation.copy(), Matrix.Rotation(math.radians(-f if k == 0 else 1.6 * f), 3, lat))
                    for c in _subtree(ch, b):
                        A[c] = M @ A[c]
        if p.get("wing"):
            for w in WINGS:
                n = w["bone"]; ax = rest[n].to_3x3().inverted() @ Vector((0, 1, 0))
                A[n] = A[n] @ Matrix.Rotation(math.radians(p["wing"]) * w["sign"], 4, ax)
        body = [n for n in A if n != "Root" and n not in RUB]
        if p.get("pitch"):
            fs = feet(A, hind if p["pitch"] > 0 else front) or [A["Hips"].translation.copy()]
            piv = sum(fs, Vector()) / len(fs); piv.z = 0.0
            M = _about(piv, Matrix.Rotation(math.radians(-p["pitch"]), 3, lat))   # nose up (faces -Y)
            for n in body:
                A[n] = M @ A[n]
        if p.get("side"):
            c = A["Hips"].translation
            ax = (A["Hips"].to_3x3() @ rest["Hips"].to_3x3().inverted()) @ Vector((0, 1, 0))
            piv = Vector((c.x + F.get("sideOffset", 0.25), c.y, 0.0))
            M = _about(piv, Matrix.Rotation(math.radians(p["side"]), 3, ax))   # onto the +X flank
            for n in body:
                A[n] = M @ A[n]
        if p.get("dx") or p.get("dy"):
            r = Vector(tuple(C[0])); r.z = 0; r.normalize()
            Tm = Matrix.Translation(r * (p.get("dx", 0) / C[2]) + Vector((0, 0, p.get("dy", 0) / C[2])))
            for n in body:
                A[n] = Tm @ A[n]
        return A

    def iou(P, target, C):
        m = splat(P, C); return (m & target).sum() / max((m | target).sum(), 1)

    t0 = def_mask(ms_frames[0]["sourcePng"]); P0 = skin(posed_world[0])
    yaw = F.get("yaw")
    if yaw is None:
        yaw = max(range(-180, 180, 5), key=lambda y_: iou(P0, t0, cam(y_)))
    C = cam(yaw)
    prev = {"pitch": 0.0, "fold": 0.0, "side": 0.0, "dx": 0.0, "dy": 0.0, "wing": 0.0}
    dx_lim = tuple(F.get("dx", [-40, 40]))
    lim = {"pitch": (lo_p, hi_p), "fold": (0, fold_max), "side": (0, side_max), "dx": dx_lim, "dy": (-60, 80), "wing": (-wing_max, wing_max)}
    steps = {"pitch": 10, "fold": 10, "side": 10, "dx": 4, "dy": 4, "wing": 15}
    log = []
    for t, A in enumerate(posed_world):
        clip, ci, cn = info.get(t, ("Idle", 0, 1))
        target = def_mask(ms_frames[t]["sourcePng"])
        # the DEF death ends lying on the flank: the last `endFrames` frames of a side clip must
        # be rolled at least `sideEnd` degrees and near level (the fixed-yaw fit alone stops short)
        lim["side"] = (0, side_max); lim["pitch"] = pitch_clips.get(clip, (lo_p, hi_p)); lim["dy"] = (-60, 80)
        lim["dx"] = dx_clips.get(clip, dx_lim)
        ne = F.get("endFrames", 2)
        if clip in side_clips and ci >= cn - ne:
            lim["side"] = (F.get("sideEnd", 85), side_max); lim["pitch"] = (-10, 10); lim["dy"] = (-40, 5)
            lim["dx"] = (-40, 40)   # the body lies where the fall carried it
        elif clip in side_clips and ci >= cn - ne - F.get("sideRampFrames", 0):
            # ease into the forced roll: minimum side grows linearly over the ramp frames
            k = ci - (cn - ne - F.get("sideRampFrames", 0)) + 1
            lim["side"] = (F.get("sideEnd", 85) * k / (F["sideRampFrames"] + 1), side_max)
        if clip in ground_clips:
            lim["dy"] = (0.0, 0.0)
        elif clip in dy_ease and cn > 1:
            # the dy range shrinks to 0 at the clip's grounded end: "out" lands (free -> 0), "in" leaves the ground
            s = ci / (cn - 1); s = s * s * (3 - 2 * s)
            f = (1 - s) if dy_ease[clip] == "out" else s
            lo_dy, hi_dy = lim["dy"]
            lim["dy"] = (min(0.0, max(lo_dy, -60 * f)), max(0.0, min(hi_dy, 80 * f)))
            if dy_ease[clip] == "in" and clip in side_clips:
                # entering from the stance also means entering unrolled (h3_battle_griffin Death: a free roll of 30
                # at key 0 put its Hips 0.07 of the height above Idle's; the DEF death's first frame is the stance)
                lo_s, hi_s = lim["side"]
                lim["side"] = (lo_s, max(lo_s, hi_s * f))
        keys = ["pitch", "dx", "dy"] + (["fold"] if fold_legs and fold_max else []) + (["side"] if clip in side_clips else []) + (["wing"] if wing_max else [])
        def score(p):
            return (iou(skin(apply(A, p, C)), target, C) - lam * sum(abs(p[k] - prev.get(k, 0)) / steps[k] for k in p)
                    - lam * 0.5 * sum(abs(p[k]) / steps[k] for k in p))
        cur = {k: (prev[k] if (k != "side" or clip in side_clips) else 0.0) for k in keys}
        cands = [dict(cur), {k: 0.0 for k in keys}] + [dict(cur, pitch=float(a)) for a in range(int(lo_p), int(hi_p) + 1, 10)]
        if "side" in keys:
            cands += [dict(cur, side=float(s_), pitch=float(a)) for s_ in range(0, int(side_max) + 1, 15) for a in (-10, 10, 30)]
        cands = [{k: max(lim[k][0], min(lim[k][1], v)) for k, v in c.items()} for c in cands]
        best = max(cands, key=score); bs = score(best)
        for sc_ in (1.0, 0.5, 0.25, 0.1):
            improved = True
            while improved:
                improved = False
                for k in keys:
                    for sg in (1, -1):
                        c = dict(best); c[k] = max(lim[k][0], min(lim[k][1], c[k] + sg * steps[k] * sc_))
                        s_ = score(c)
                        if s_ > bs + 1e-6:
                            bs, best, improved = s_, c, True
        prev = dict(prev, **best)
        A.update(apply(A, best, C))
        log.append({"frame": t, "clip": clip, **{k: round(v, 1) for k, v in best.items()}, "iou": round(float(iou(skin(A), target, C)), 3)})
    json.dump({"yaw": yaw, "frames": log}, open(g["OUT"] + ".quadfit.json", "w"), indent=0)
    print("QUADRUPED fit yaw", yaw, "mean IoU (own camera)", round(float(numpy.mean([r["iou"] for r in log])), 3))
