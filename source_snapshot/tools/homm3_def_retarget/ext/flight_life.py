"""Secondary body motion for a flier whose body is otherwise held rigid (hook module for build_unit.py; list
"flight_life" in "extensions" AFTER "wing_chain", config key "flightLife").

Why: a quadruped flier built with quadruped.staticCapture and a rigid flight tuck (h3_royal_griffin,
h3_battle_griffin) moves only its wings and tail. Measured on the delivered GLBs (2026-09-27): Move bodyRot 0,
legSwing 0, neck/head 0; Idle every bone but a 3 deg nod and the tail at rest, wings held spread. The vanilla OE
griffin, for comparison, is Fly body 14.1 / legs 54.8 / arms 36.8 and Idle body 4.8 / wings 45 / arms 12
(artifacts/homm3_def_retarget_delivery/_articulation/vanilla_reference.json). The user called the installed
griffin "very stiff" (2026-09-27) while the articulation gate passed it: the gate has no floor on a flier's
body, limb or idle motion.

Each entry is a periodic rotation of one bone's subtree (children ride along, so the finished wing chains,
which wing_chain parents to the spine, ride the body's pitch and heave) or a body heave. It must run after
wing_chain: that module's "steady" step blends each Move frame's hips rotation to the clip mean and would
erase a body pitch applied before it.
  "flightLife": {"moves": [
     {"clips": ["Move"], "bone": "Hips", "axis": "lat", "deg": 6, "phase": 45, "cycles": 1},
     {"clips": ["Move"], "heave": 0.03, "phase": 90},
     ...]}
  clips   DEF clip suffixes. MoveStart / MoveEnd listed with Move ramp the amplitude in / out (as the
          quadruped trot does); any other listed clip plays at full amplitude.
  bone    the subtree root, rotated about its own posed head.
  axis    "lat" (the body's left-right axis: Hips rest X carried by the posed Hips), "up" (world Z) or
          "fwd" (the body's long axis: Hips rest Y carried by the posed Hips).
  deg     amplitude, degrees: value = deg * sin(2 pi cycles i / n + phase), i the frame index within the
          clip segment and n its DEF frame count, so every loop closes on the DEF's own frame count.
  offset  optional, degrees (default 0): a constant bias added to the wave, value = offset + deg * sin(...), with
          the same MoveStart / MoveEnd ramp, so a limb can hold a flight tuck (hind legs trailing) and swing
          about it. Added 2026-09-29 for the dragons' Move, whose legs otherwise hang straight down (reads as
          standing); absent = the original wave, bit for bit.
  ease    optional {clip: "in" | "out" | "bracket"} for clips NOT in "clips": the entry's amplitude follows the
          quadrupedSit fixed-pose weight curve there (out 1 -> 0, in 0 -> 1, bracket 1 at both ends and 0 mid-clip),
          so a pose held through the sit clips (the griffins' raised Idle wings) leaves and re-enters with the sit
          instead of popping. Added 2026-09-29 (griffin review: wings spread flat behind the sitting body read as
          lying prone; the DEF idle holds them raised). Absent = as before.
  keys    optional [[x, value], ...] with x in [0, 1] of the clip (x = i / (n - 1)), first x 0 and last x 1, in place of
          deg / phase / cycles / offset: an authored one-shot curve (cubic Hermite through the keys, Catmull-Rom
          tangents, flat at both ends), value in degrees for a bone or scene units for a heave (then "heave": 1).
          For a clip whose beat is a single arc, not a wave: the griffins' AttackFront rears and then lunges
          down and forward onto the target in DEF timing (main review 2026-09-29: v4 held one pose). The listed
          clips play it at full amplitude; ease applies as above. Absent = as before.
  heave   instead of bone/axis/deg: world-Z translation of the whole unit (scene units) with the same wave.
Phases are in the clip's own cycle: h3_royal_griffin's wing_chain Move flap is 53 sin(ph + 180) - 7, so the
downstroke runs 270 -> 90 and a lift peaking at 90 lands at its end.
Fails closed: an unknown key, clip-less entry, missing bone or bad axis is refused.
Proof tier: generated artifact (offline build).
"""
import json
import math

from mathutils import Matrix, Vector

KEYS = {"clips", "bone", "axis", "deg", "heave", "phase", "cycles", "offset", "ease", "keys"}
EASES = {"in", "out", "bracket"}


def _clip_of(master):
    info = {}
    for s in json.load(open(master))["segments"]:
        for i, t in enumerate(range(s["globalStart"], s["globalEnd"])):
            info[t] = (s["contractSuffix"], i, s["frameCount"])
    return info


def _subtree(parent_of, b):
    ch = {}
    for c, p in parent_of.items():
        ch.setdefault(p, []).append(c)
    out = [b]
    i = 0
    while i < len(out):
        out += ch.get(out[i], [])
        i += 1
    return out


def _keys_ok(k):
    try:
        xs = [float(x) for x, _ in k]
        [float(v) for _, v in k]
    except (TypeError, ValueError):
        return False
    return len(k) >= 2 and xs[0] == 0 and xs[-1] == 1 and all(a < b for a, b in zip(xs, xs[1:]))


def _curve(k, x):
    """Cubic Hermite through keys [[x, v], ...], Catmull-Rom tangents, zero slope at the ends."""
    xs = [float(a) for a, _ in k]
    vs = [float(b) for _, b in k]
    j = max(0, min(len(xs) - 2, next((q for q in range(len(xs) - 1) if x <= xs[q + 1]), len(xs) - 2)))
    x0, x1, v0, v1 = xs[j], xs[j + 1], vs[j], vs[j + 1]

    def slope(q):
        if q == 0 or q == len(xs) - 1:
            return 0.0
        return (vs[q + 1] - vs[q - 1]) / (xs[q + 1] - xs[q - 1])

    h = x1 - x0
    u = (x - x0) / h
    return ((2 * u**3 - 3 * u**2 + 1) * v0 + (u**3 - 2 * u**2 + u) * h * slope(j)
            + (-2 * u**3 + 3 * u**2) * v1 + (u**3 - u**2) * h * slope(j + 1))


def _check(g, moves):
    for m in moves:
        if "keys" in m and (set(m) & {"deg", "phase", "cycles", "offset"} or not _keys_ok(m["keys"])):
            raise SystemExit(f"flightLife: keys replace deg/phase/cycles/offset and run [[0, v], ..., [1, v]]: {m}")
        bad = set(m) - KEYS
        if bad or not m.get("clips"):
            raise SystemExit(f"flightLife: bad entry {m} (unknown {sorted(bad)} or no clips)")
        if "heave" in m:
            if "bone" in m or "deg" in m or "offset" in m:
                raise SystemExit(f"flightLife: a heave entry takes no bone/deg: {m}")
            continue
        if m.get("bone") not in g["rest"]:
            raise SystemExit(f"flightLife: bone {m.get('bone')} is not in the rig")
        if m.get("axis") not in ("lat", "up", "fwd"):
            raise SystemExit(f"flightLife: axis must be lat/up/fwd, got {m.get('axis')}")
        if not isinstance(m.get("deg", 0 if "keys" in m else None), (int, float)) or not isinstance(m.get("offset", 0), (int, float)):
            raise SystemExit(f"flightLife: deg / offset must be numbers: {m}")
        ez = m.get("ease", {})
        if not isinstance(ez, dict) or not set(ez.values()) <= EASES or set(ez) & set(m["clips"]):
            raise SystemExit(f"flightLife: ease must map clips NOT in 'clips' to in/out/bracket: {m}")


def before_keys(g):
    F = g["cfg"].get("flightLife")
    if not F:
        return
    moves = F.get("moves", [])
    if set(F) - {"moves"} or not moves:
        raise SystemExit(f"flightLife: expected {{\"moves\": [...]}}, got keys {sorted(F)}")
    _check(g, moves)
    ex = list(g["cfg"].get("extensions", []))
    if "wing_chain" in ex and ex.index("wing_chain") > ex.index("flight_life"):
        raise SystemExit("flightLife: list flight_life after wing_chain in extensions (see the module doc)")
    rest, parent_of = g["rest"], g["parent_of"]
    info = _clip_of(g["MASTER"])
    subs = {m["bone"]: _subtree(parent_of, m["bone"]) for m in moves if "bone" in m}
    lat0, fwd0 = Vector((1, 0, 0)), Vector((0, 1, 0))
    R_hips_rest_inv = rest["Hips"].to_3x3().inverted()
    peak = {}
    for t, A in enumerate(g["posed_world"]):
        clip, i, n = info.get(t, ("Idle", 0, 1))
        for m in moves:
            clips = m["clips"]
            ez = m.get("ease", {})
            if clip in clips:
                amp = 1.0
            elif clip in ez:
                # the quadrupedSit weight curve (x = i / (n - 1)): a pose held in the sit clips follows the sit out/in
                x = i / max(n - 1, 1)
                amp = {"out": 0.5 + 0.5 * math.cos(math.pi * x), "in": 0.5 - 0.5 * math.cos(math.pi * x),
                       "bracket": 0.5 + 0.5 * math.cos(2 * math.pi * x)}[ez[clip]]
            elif clip == "MoveStart" and "Move" in clips:
                amp = (i + 1) / (n + 1)
            elif clip == "MoveEnd" and "Move" in clips:
                amp = 1 - (i + 1) / (n + 1)
            else:
                continue
            ph = 2 * math.pi * m.get("cycles", 1) * i / max(n, 1) + math.radians(m.get("phase", 0.0))
            w = amp * (_curve(m["keys"], i / max(n - 1, 1)) if "keys" in m else math.sin(ph))
            key = (m.get("bone", "heave"), m.get("axis", "z"))
            if "heave" in m:
                dz = m["heave"] * w
                for b in list(A):
                    if b != "Root":
                        A[b] = Matrix.Translation(Vector((0, 0, dz))) @ A[b]
                peak[key] = max(peak.get(key, 0.0), abs(dz))
                continue
            Rh = A["Hips"].to_3x3() @ R_hips_rest_inv
            axis = {"lat": Rh @ lat0, "fwd": Rh @ fwd0, "up": Vector((0, 0, 1))}[m["axis"]].normalized()
            deg = (w if "keys" in m else m["deg"] * w) + amp * m.get("offset", 0.0)
            piv = A[m["bone"]].translation.copy()
            M = Matrix.Translation(piv) @ Matrix.Rotation(math.radians(deg), 4, axis) @ Matrix.Translation(-piv)
            for c in subs[m["bone"]]:
                if c in A:
                    A[c] = M @ A[c]
            peak[key] = max(peak.get(key, 0.0), abs(deg))
    print("FLIGHT_LIFE", {f"{k[0]}:{k[1]}": round(v, 3) for k, v in peak.items()})
