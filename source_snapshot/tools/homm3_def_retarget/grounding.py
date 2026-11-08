"""Ground contact against the DEF: the rule the ground stage applies (tools/homm3_def_retarget_delivery/ground_glb.py)
and the curve the delivery gate (homm3_def_retarget_delivery/ground_check.py) measures against. numpy only.

Why (scan of 79 frozen GLBs, 2026-09-27): 43 of 75 units sink their dead body below the floor (Death's last frame,
worst -0.24 of the unit's height), 9 leave it floating (+0.04 to +0.18), and 52 sink some other clip. Cause:
build_unit.pose_frame grounds the Hips on the capture's lowest JOINT scaled by mesh_leg / cap_leg, so a lying body
whose mesh extends below its joints sinks, and a mesh whose proportions differ from the capture's floats.

The DEF is the allowance, never a hand number. Per DEF frame, the opaque (alpha 255) plate's bottom row is measured
against the unit's Idle frame 0, as a fraction of that frame's opaque height (+ = above the Idle floor). The DEF's
dead bodies end 0.08-0.13 ABOVE the idle floor on screen (a lying body recedes into depth) and no DEF frame of the
scanned units goes below -0.04 except a real dip (h3_dwarf AttackFront lunge, -0.145).

Per clip, in the order applied, a vertical offset of the whole body (offsets()):
  (c) entry   the first frame's lowest vertex is brought inside [min(0, d0), max(0, d0)] (d0 the DEF's first-frame
              offset), the correction easing out (smoothstep) over the first third of the clip. A closed loop
              (loop=True: its closing key is its first pose) holds the correction for the whole clip instead, since
              its entry is also its exit and an eased entry would open the loop (h3_dwarf Move, 2026-09-27). A held
              pull-down goes no deeper than keeps every frame on its own floor min(0, d[k]): deeper, (a) lifts the
              frames it sank straight back and the loop carries a varying offset that lowers only its airborne frames
              (h3_amalek Move, 2026-09-28). Where that leaves the entry outside the gate's band, the gate refuses.
  (b) death   Death's last frame lands on the floor; the correction eases in (smoothstep) from the last DEF frame at
              the DEF's lowest bottom row (where the DEF starts rising) to the end. Skipped for shrinkOut / shatter,
              whose body leaves the frame (stamped reason).
  (a) clamp   no frame's lowest vertex below min(0, d[k]) (lift only): a jump keeps its air time, a lunge the DEF
              dips keeps its dip, and nothing is lifted above the floor.
  joint entry (c) moves the whole body, so it moves the Hips too. Where the gate also judges the Hips at the entry
              (hips0 given: the clip's first-frame Hips step from Idle, allow_hips its allowance, hips_allowance) and
              (c)'s offset would put the Hips outside it, the entry offset is instead the one nearest (c)'s inside BOTH
              gate bands -- feet within GROUND_TOL of [min(0, d0), max(0, d0)], Hips within allow_hips -- inset by
              the gate's measuring resolution GATE_RES; (a) is relaxed by the feet's remaining depth below min(0, d0),
              eased out like the entry (held in a closed loop), so it does not lift the Hips back out. No such offset
              (the two bands do not meet) leaves (c) as it is, and the gate refuses the unit. A clip (c) already
              lands inside the Hips band is unchanged. (2026-09-27: banshee / shadow_dragon AttackFront, black_dragon,
              ghost_dragon Mouseover / MoveStart enter with the feet 0.046-0.066 below the floor and the Hips at or
              above Idle; lifting the full sink stepped the Hips +0.046 to +0.103 out of the gate's band.)
Config "groundContact": {"exempt": "<reason>"} skips all three, {"deathExempt": "<reason>"} only (b) (see exemption()).
One implementation: the rule runs only as the delivery-GLB stage ground_glb.py (fleet_rebuild.py, after emphasis,
stride match, low-pass and densify), never in build_unit.py: a build-time step was undone by the emphasis stage
(2026-09-27 h3_ogre Death, 0.000 -> -0.073 of its height).
The build does use this module for one bound, not the rule: build_unit.py's silhouetteRefine may move the Hips
vertically only inside refine_dy_band at the frames judged_hips_frames names (the gate's entry rule, its scope).
Proof tier: generated artifact (offline GLB edit); runtime unproven.
"""
from __future__ import annotations

import hashlib

import numpy as np

SCHEMA = "homm3_def_retarget_grounding.v1"
GROUND_TOL = 0.04   # the ground gate's tolerance (ground_check.py reads it from here); never widened
GATE_RES = 1e-4     # ground_check measures lows and hips0 rounded to 4 decimals: a joint entry keeps this far inside
DEATH_EXEMPT = {"shrinkOut": "shrinkOut: the body shrinks into a point, it never lies on the floor",
                "shatter": "shatter: the body breaks into rubble chunks with their own floor"}


def exemption(cfg: dict) -> dict:
    """{"all": reason | None, "death": reason | None} from a unit config's "groundContact" (default on).
    "grounding": false is NOT an exemption: it only turns off pose_frame's capture-joint Hips grounding (95 configs,
    quadrupeds and riders whose rig extension sets its own floor), and their feet still belong on the floor.
      "groundContact": {"exempt": "<reason>"}       skip (a)(b)(c) (a unit whose Idle floor is not its ground)
      "groundContact": {"deathExempt": "<reason>"}  skip only (b)
    shrinkOut / shatter skip (b) with a fixed reason. Anything else fails closed."""
    gc = cfg.get("groundContact", True)
    why, death = None, None
    if gc is not True:
        ok = isinstance(gc, dict) and len(gc) == 1 and set(gc) <= {"exempt", "deathExempt"}
        r = next(iter(gc.values())) if ok else None
        if not (ok and isinstance(r, str) and r.strip()):
            raise SystemExit(f"{cfg.get('unit')}: groundContact must be absent, {{\"exempt\": \"<reason>\"}} or "
                             f"{{\"deathExempt\": \"<reason>\"}}, got {gc!r} (tools/homm3_def_retarget/grounding.py)")
        why, death = gc.get("exempt"), gc.get("deathExempt")
    death = death or next((r for k, r in DEATH_EXEMPT.items() if cfg.get(k)), None)
    return {"all": why, "death": death}


def _rows(mask):
    r = np.where(mask.any(1))[0]
    return (int(r.min()), int(r.max())) if len(r) else (None, None)


def def_curve(ms: dict, opaque) -> dict:
    """DEF bottom/top-row curve per master segment. `opaque(png) -> bool HxW` (alpha 255: the DEF's ground shadow is
    alpha 64/128 and must not count as the body). Offsets are fractions of the Idle frame-0 opaque height,
    + = above the Idle floor / top. Stamped with the frames' byte hash so a gate can pin its source."""
    idle = next((s for s in ms["segments"] if s["contractSuffix"] == "Idle"), None)
    if idle is None:
        raise SystemExit("grounding: the master sequence has no Idle segment (the floor reference)")
    rows, h = {}, hashlib.sha1()
    for t, f in enumerate(ms["frames"]):
        with open(f["sourcePng"], "rb") as fh:
            h.update(fh.read())
    it, ib = _rows(opaque(ms["frames"][idle["globalStart"]]["sourcePng"]))
    if it is None or ib <= it:
        raise SystemExit("grounding: the DEF Idle frame 0 has no opaque body")
    H = float(ib - it)
    segs = []
    for s in ms["segments"]:
        bot, top = [], []
        for t in range(s["globalStart"], s["globalEnd"]):
            if t not in rows:
                rows[t] = _rows(opaque(ms["frames"][t]["sourcePng"]))
            a, b = rows[t]
            bot.append(None if b is None else round((ib - b) / H, 4))
            top.append(None if a is None else round((it - a) / H, 4))
        segs.append({"suffix": s["contractSuffix"], "globalStart": s["globalStart"], "frameCount": s["frameCount"],
                     "bottom": bot, "top": top})
    return {"schema": SCHEMA, "source": {"frames": len(ms["frames"]), "defFramesSha1": h.hexdigest(),
                                         "rule": "opaque (alpha 255) bottom/top row vs Idle frame 0, / its height"},
            "idleHeightPx": H, "segments": segs}


def canonical(curve: dict) -> dict:
    """{suffix: segment} keeping the longest segment per suffix (build_unit writes that one as the Unit_ clip)."""
    out = {}
    for s in curve["segments"]:
        if s["suffix"] not in out or s["frameCount"] > out[s["suffix"]]["frameCount"]:
            out[s["suffix"]] = s
    return out


def _fill(d):
    """None (an empty DEF frame, e.g. a vanished death) takes its nearest measured neighbour; all None -> zeros."""
    d = list(d)
    idx = [i for i, v in enumerate(d) if v is not None]
    if not idx:
        return np.zeros(len(d))
    return np.array([d[min(idx, key=lambda j: abs(j - i))] if v is None else v for i, v in enumerate(d)], float)


def _smooth(x):
    x = np.clip(x, 0.0, 1.0)
    return x * x * (3 - 2 * x)


def hips_allowance(bottom, top) -> float:
    """The gate's allowed |Hips step from Idle frame 0| at a clip's first frame (fraction of the Idle height), from the
    DEF clip's bottom and top rows: GROUND_TOL + max(|bottom[0]|, |top[0]|)."""
    return GROUND_TOL + max(abs(float(_fill(bottom)[0])), abs(float(_fill(top)[0])))


def joint_entry(L0: float, d0: float, e: float, hips0: float, allow_hips: float) -> float | None:
    """The entry offset nearest e that puts the first frame inside both gate bands (feet: GROUND_TOL around
    [min(0, d0), max(0, d0)]; Hips: |hips0 + offset| <= allow_hips), each inset by GATE_RES; None if they do not meet."""
    a = max(min(0.0, d0) - GROUND_TOL - L0, -allow_hips - hips0) + GATE_RES
    b = min(max(0.0, d0) + GROUND_TOL - L0, allow_hips - hips0) - GATE_RES
    return float(np.clip(e, a, b)) if a <= b else None


def offsets(lows, d_bottom, death: bool, death_exempt: str | None, loop: bool = False,
            hips0: float | None = None, allow_hips: float | None = None) -> tuple[np.ndarray, dict]:
    """Per-frame offsets (fractions of the unit height, + = up) for one clip segment. lows: the skinned lowest vertex
    per frame relative to the Idle frame-0 floor (fractions); d_bottom: the DEF bottom-row curve of the same frames;
    hips0 / allow_hips: the first frame's Hips step from Idle and the gate's allowance there (joint entry), or None
    where the gate does not judge the Hips."""
    L = np.asarray(lows, float)
    d = _fill(d_bottom)
    n = len(L)
    s = np.zeros(n)
    info = {}
    # (c) entry
    lo, hi = min(0.0, d[0]), max(0.0, d[0])
    e = float(np.clip(L[0], lo, hi) - L[0])
    relax = 0.0
    if hips0 is not None and abs(hips0 + e) > allow_hips:
        j = joint_entry(float(L[0]), float(d[0]), e, float(hips0), float(allow_hips))
        if j is None:
            info["entryJoint"] = "infeasible: the feet and Hips bands do not meet"
        else:
            info["entryJoint"] = {"from": round(e, 4), "hipsStep": round(float(hips0 + j), 4),
                                  "allowHips": round(float(allow_hips), 4)}
            e = j
            relax = max(0.0, lo - (L[0] + e))
    if n > 1 and not loop:
        w = 1 - _smooth(np.arange(n) / max(1.0, n / 3.0))
    else:
        w = np.ones(n)
        if e < 0 and "entryJoint" not in info:
            # a held (closed-loop) pull-down moves every frame: it goes no deeper than keeps each frame on its own
            # floor, else (a) lifts the frames it sank straight back and the loop carries a varying offset that
            # lowers only its airborne frames (2026-09-28 h3_amalek Move: entry -0.024 held, 34 frames clamped
            # back, the swing feet dropped and the stride-planted slip went 0.066 -> 0.254)
            # ... but never so little that the first frame stays above the gate's own entry band: a flier's bobbing
            # loop reaches its floor mid-cycle only, so the limit alone left it entering high (2026-09-28
            # h3_spectral_dragon Move: limited -0.1286 -> -0.0085, entry +0.377 > +0.297); there the pull-down goes
            # to the band's top (inset by GATE_RES) and (a) lifts only the frames that sink
            bound = -float(np.min(L - np.minimum(0.0, d)))    # the deepest offset that sinks no frame
            if bound > e:
                # the least pull-down that enters the band -- both of the gate's first-frame bands where it judges
                # the Hips (joint entry's upper edge; h3_horned_demon Move entered the feet band, not the Hips')
                top = hi + GROUND_TOL - float(L[0])
                if hips0 is not None:
                    top = min(top, allow_hips - hips0)
                top -= GATE_RES
                lim = min(min(0.0, bound), top)
                info["entryLimited"] = {"from": round(e, 4), "by": "held pull-down keeps every frame on its floor"
                                        if lim == min(0.0, bound) else "held pull-down to the entry band's top"}
                e = max(e, lim)
    if abs(e) > 1e-6:
        s += e * w
        info["entry"] = round(e, 4)
        if loop:
            info["entryHeld"] = "closed loop"
    # (b) death lands on the floor
    if death:
        if death_exempt:
            info["deathExempt"] = death_exempt
        elif n > 1:
            ks = int(max(i for i in range(n) if d[i] <= d.min() + 0.01))
            ks = min(ks, n - 2)
            delta = -(L[-1] + s[-1])
            k = np.arange(n)
            s += delta * _smooth((k - ks) / float(n - 1 - ks)) * (k > ks)
            info["deathLand"] = round(float(delta), 4)
            info["deathEaseFrom"] = ks
    # (a) no sink below the DEF's own floor at that frame
    floor = np.minimum(0.0, d) - relax * w     # relaxed only by a joint entry's remaining feet depth
    if relax > 0:
        info["clampRelaxed"] = round(relax, 4)
    lift = np.maximum(0.0, floor - (L + s))
    s += lift
    if lift.max() > 1e-6:
        info["clampLiftMax"] = round(float(lift.max()), 4)
        info["clampFrames"] = int((lift > 1e-6).sum())
    return s, info


def judged_hips_frames(curve: dict, cfg: dict) -> dict:
    """{global master frame: allowed |Hips step from Idle frame 0|, as fractions of the Idle height} for exactly the
    frames the ground gate judges the Hips at (ground_check: each canonical clip's first frame, allowance GROUND_TOL +
    max(|DEF bottom row|, |DEF top row|) there), with the gate's exemptions: none for a "groundContact": {"exempt"} unit.
    Idle's first frame is the reference itself. Every other frame is not judged, so the refine stays free there."""
    if exemption(cfg)["all"]:
        return {}
    out = {}
    for c, s in canonical(curve).items():
        if c == "Idle":
            continue
        out[s["globalStart"]] = hips_allowance(s["bottom"], s["top"])
    return out


def refine_dy_band(hips_z: float, idle_hips_z: float, height: float, allow: float, up_z: float,
                   px_per_unit: float) -> tuple[float, float]:
    """The sprite-space vertical (px, + = up the screen) a silhouette refine may add at one frame so its Hips stays
    within `allow` * `height` of the refined Idle frame 0's Hips (`idle_hips_z`); `hips_z` is the frame's Hips height
    before the refine, `up_z` the camera up vector's world-vertical part. build_unit.py's silhouetteRefine searches dy
    only inside this band: the DEF's rows are the evidence for a vertical move, and an IoU gain is not (2026-09-27
    hota_cove_stormbird MoveStart/MoveEnd lifted +0.09 / +0.12 of its height where the DEF's first frames stay down)."""
    if up_z <= 0 or px_per_unit <= 0 or height <= 0:
        raise SystemExit(f"grounding.refine_dy_band: degenerate camera or height (up_z {up_z}, px/unit {px_per_unit}, "
                         f"height {height})")
    k = px_per_unit / up_z
    return (-allow * height - hips_z + idle_hips_z) * k, (allow * height - hips_z + idle_hips_z) * k

