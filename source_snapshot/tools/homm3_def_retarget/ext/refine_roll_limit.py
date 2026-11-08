"""Cap castle_refine's frame-to-frame body roll on chosen clips.

castle_refine searches each frame's whole-body dx/dy/roll on its own (no smoothness term), so a collapsing body can
swing -20 -> 0 -> +13 degrees on consecutive Death frames (pose-follow trial A, 2026-09-27: Hips translation energy
above 4 Hz on Death rose from ~0.01 to ~0.13). This hook runs right after castle_refine and limits the roll step:
per clip, roll_t = clamp(roll_raw_t, roll_{t-1} - maxDelta, roll_{t-1} + maxDelta), starting from 0 before the
clip's first frame. The difference is applied to the same body bones castle_refine moved, as a rotation about the
camera axis through the refined hips, so the result equals castle_refine's transform with the capped roll.
The castle_refine log is rewritten with the capped roll (the searched value kept as rollRaw), so refine_carry
(listed after this hook) carries free prop bones with the capped transform.

Config (unit json): "refineRollLimit": {"clips": ["Death", "Hitted"], "maxDelta": 5.0}; in "extensions" after
"castle_refine" and before "refine_carry". A missing castle_refine log is refused.
Status (2026-09-27): MEASURED NEGATIVE, enabled on no unit. Pose-follow trials (goblin, orc berserker, ogre; Death,
with castle_refine |dy| <= 8, refine_roll_limit 5 deg, refine_carry) against the plain build:
  - unbounded warp (trial B/BA): Death IoU 0.34/0.19/0.33 -> 0.42/0.44/0.47 and the ratio-to-idle gate passed, but the
    render sheet showed the first pose held 4-5 frames then a one-frame collapse (freeze-then-pop; the freeze gate
    in flyer_articulation.freeze_check now fails it);
  - rate bounded to 0.5..2 (BA2): no held frames, but the mesh still stands while the DEF has crumpled and catches
    up late (goblin pops between frames 5 and 6; berserker ratio 0.48 < 0.6, Hips translation >4 Hz 0.37).
The capture's fall is a different motion from the DEF's hop-and-crumple; re-timing it cannot make it follow.
Kept for a future pose source that does follow the DEF; do not enable it for IoU alone.
Proof tier: generated artifact.
"""
import json
import math
import os


def before_keys(g):
    R = g["cfg"].get("refineRollLimit")
    if not R:
        return
    Matrix, Vector = g["Matrix"], g["Vector"]
    path = g["OUT"] + ".castle_refine.json"
    if not os.path.exists(path):
        raise SystemExit("refineRollLimit: no castle_refine log; list refine_roll_limit after castle_refine")
    md = float(R.get("maxDelta", 5.0))
    if md <= 0:
        raise SystemExit(f"refineRollLimit: maxDelta must be > 0, got {md}")
    clips = set(R.get("clips", ["Death", "Hitted"]))
    clip_of = {}
    for sg in json.load(open(g["MASTER"]))["segments"]:
        for t in range(sg["globalStart"], sg["globalEnd"]):
            clip_of[t] = (sg["contractSuffix"], sg["globalStart"])
    rub = set(g.get("RUBBLE_BONES", []))
    STATIC, TAILB = g["STATIC"], g["TAILB"]
    fwd = g["fwd_cam"]
    log = json.load(open(path))
    prev, seg, n_cap, worst = 0.0, None, 0, 0.0
    for e in log:
        c = clip_of.get(e["frame"])
        if c is None or c[0] not in clips:
            continue
        if c != seg:
            seg, prev = c, 0.0
        raw = float(e.get("rollRaw", e.get("roll", 0.0)))
        new = max(prev - md, min(prev + md, raw))
        if abs(new - raw) > 1e-6:
            A = g["posed_world"][e["frame"]]
            hv = A["Hips"].translation.copy()
            C = Matrix.Translation(hv) @ Matrix.Rotation(math.radians(new - raw), 4, fwd) @ Matrix.Translation(-hv)
            for n in list(A.keys()):
                if n != "Root" and n not in rub and n not in STATIC and n not in TAILB:
                    A[n] = C @ A[n]
            e["rollRaw"] = raw
            e["roll"] = round(new, 2)
            n_cap += 1
            worst = max(worst, abs(new - raw))
        prev = new
    json.dump(log, open(path, "w"), indent=0)
    if TAILB and n_cap:
        for t in range(g["T"]):
            g["solve_tail"](t)
    print("REFINE_ROLL_LIMIT clips", sorted(clips), "maxDelta", md, "frames capped", n_cap, "largest cut", round(worst, 2))
