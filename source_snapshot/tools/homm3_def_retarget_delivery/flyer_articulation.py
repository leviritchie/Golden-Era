"""Bone-level articulation of flyer (and walker) clips, measured by one rule for our GLBs and vanilla OE units.

    python tools/homm3_def_retarget_delivery/flyer_articulation.py glb <unit|path.glb> [...] [--json out]
    python tools/homm3_def_retarget_delivery/flyer_articulation.py vanilla --out <json>     (reads the install, read-only)

Why bones and not vertices: tools/homm3_def_retarget/articulation.py skins our meshes, but vanilla OE units only
ship their clips and skeletons in resources.assets; comparing the two needs one metric both can feed. Per clip,
from model-space bone rotations sampled over the clip:

  wingSwing   deg  the largest rotation, relative to frame 0, of any wing bone in the frame of the torso bone the
                   wing hangs from (0 = the wing only rides the body);
  wingRange   deg  peak-to-peak: the largest angle between any two samples of a wing bone's torso-relative rotation.
                   A flap whose frame 0 is mid-beat (a DEF Move is level, down, level, up) shows only half its stroke
                   to wingSwing; wingRange sees the whole stroke (vanilla Fly: 86.4 .. 179.7, ~= wingSwing there);
  wingFold    deg  multi-bone wings: the largest rotation of a chain's deepest bone relative to its root bone
                   (0 = the wing never bends; absent for one-bone wings);
  legSwing / armSwing  deg  the same as wingSwing for leg and arm bones, relative to the body bone;
  bodyRot     deg  the largest model-space rotation of the torso bone the wings hang from (the body bone for units
                   without wings) relative to frame 0: the "held toy" motion;
  toyRatio         bodyRot / max(wingSwing, legSwing, armSwing): > 1 means the body turns more than any limb;
  jitterP90        per bone, the share of its (parent-relative, detrended) rotation's spectral energy above
                   JITTER_CUTOFF_HZ; the 90th percentile over bones that move (jitterMedian, jitterWorst too).

Bone regions come from names: wing (*wing*), leg (upleg/leg/thigh/calf/foot/toe, and the mount rig's horse legs
HFL0/HFR/HHL/HHR), arm (shoulder/arm/hand/clavicle).
The torso a wing hangs from is its nearest non-wing ancestor; the body bone is the lowest bone that is an ancestor
of every leg and wing bone (Hips on our rigs). Proof tier: generated artifact (read-only measurement).
"""
from __future__ import annotations

import json
import hashlib
import math
import re
import struct
import sys
import zlib
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
GAME = Path(r"V:/SteamLibrary/steamapps/common/Heroes of Might and Magic Olden Era - Golden Era")
SAMPLE_HZ = 30.0
# Gate (tools/validate_homm3_owned_skinned_articulation_contract.py, freeze_slice.py), measured on Unit_Move.
# Vanilla OE 04.Fly over 15 distinct flyer clips (artifacts/homm3_def_retarget_delivery/_articulation/
# vanilla_reference.json): wingSwing min 84.9 / median 144.4, bodyRot / wingSwing max 0.42 / median 0.12;
# 01.Walk legSwing over 41 legged walkers >= 20.3 (the 5.7 / 10.1 rows are floating paragons/arbitrators).
# Floors sit below the vanilla minimum: a one-bone plank measures lower than a vanilla chain for the same beat.
GATE_CLIP = "Unit_Move"
WING_SWING_MIN = 60.0
# The wing floor applies to the whole stroke (wingRange, 2026-09-27). Which rule judges a unit's wings (wing_rule):
#   flatFloor        no DEF row: wingRange >= WING_SWING_MIN and wingSwing >= WING_SWING_MIN (a unit whose half-stroke
#                    from frame 0 is under the floor cannot pass on its peak-to-peak range alone);
#   defRow           a DEF-measured row (reference/def_wing_range.json): wingRange >= DEF_RANGE_SHARE x rangeDeg, in
#                    place of the flat floor. User-approved 2026-09-27 ("I approve the 80% wing beat concept"), so a
#                    small-flap DEF is matched to its own beat instead of a 60 deg floor it never reaches;
#   defRowUpperBound a row whose share of rangeDeg would fall under WING_SWING_MIN (a low-flap DEF, where the
#                    silhouette match is least certain) is judged on the stricter end of its bracket:
#                    wingRange >= DEF_RANGE_SHARE x boundsDeg[1].
# No row means no relaxation. A row without a bracket that contains rangeDeg is refused (fail closed).
DEF_RANGE_SHARE = 0.8
DEF_WING_RANGE = HERE / "reference" / "def_wing_range.json"
FLYER_TOY_MAX = 0.6  # h3_harpy (wing_chain, eye-passed 2026-09-25) measures 0.56 on its Mixamo Spine2
LEG_SWING_MIN = 15.0
LEG_KEYS = ("upleg", "leg", "thigh", "calf", "foot", "toe")
ARM_KEYS = ("shoulder", "arm", "hand", "clavicle")
# castle_mount HFL0.. / stronghold_quadruped FL1..RR3 / necropolis_horse HorseLFUp, HorseLFLow, HorseLFHoof ..
MOUNT_LEG = re.compile(r"^(H[FH][LR]\d+|[FR][LR][1-9]|Horse[LR][FH](Up|Low|Hoof))$")


# ---------------------------------------------------------------- quaternions (xyzw)
def qmul(a, b):
    ax, ay, az, aw = np.moveaxis(a, -1, 0)
    bx, by, bz, bw = np.moveaxis(b, -1, 0)
    return np.stack([aw * bx + ax * bw + ay * bz - az * by, aw * by - ax * bz + ay * bw + az * bx,
                     aw * bz + ax * by - ay * bx + az * bw, aw * bw - ax * bx - ay * by - az * bz], axis=-1)


def qinv(q):
    return q * np.array([-1.0, -1.0, -1.0, 1.0])


def qnorm(q):
    return q / np.maximum(np.linalg.norm(q, axis=-1, keepdims=True), 1e-12)


def qangle(q):
    return np.degrees(2 * np.arccos(np.clip(np.abs(qnorm(q)[..., 3]), 0, 1)))


def region(name: str) -> str | None:
    n = name.lower()
    if "wing" in n:
        return "wing"
    if any(k in n for k in LEG_KEYS) and "arm" not in n:
        return "leg"
    if MOUNT_LEG.match(name):
        return "leg"            # mount rigs: castle_mount HFL0..2 / HFR / HHL / HHR, stronghold_quadruped FL1..3 / FR / RL / RR,
                                # necropolis_horse Horse{LF,LH,RF,RH}{Up,Low,Hoof}
    if any(k in n for k in ARM_KEYS):
        return "arm"
    return None


# ---------------------------------------------------------------- the metric
def clip_metrics(names: list[str], parent: dict[int, int | None], local: dict[int, np.ndarray]) -> dict:
    """names[i], parent[i]; local[i]: (T, 4) local rotation of bone i per sample (rest for unanimated bones)."""
    n = len(names)
    order, seen = [], set()

    def visit(i):
        if i in seen:
            return
        p = parent.get(i)
        if p is not None:
            visit(p)
        seen.add(i)
        order.append(i)
    for i in range(n):
        visit(i)
    model = {}
    for i in order:
        p = parent.get(i)
        model[i] = local[i] if p is None else qnorm(qmul(model[p], local[i]))

    def ancestors(i):
        out, p = [], parent.get(i)
        while p is not None:
            out.append(p)
            p = parent.get(p)
        return out
    reg = {i: region(names[i]) for i in range(n)}

    def rel_swing(bones, ref_of):
        best = 0.0
        for i in bones:
            r = ref_of(i)
            if r is None:
                continue
            rel = qmul(qinv(model[r]), model[i])
            best = max(best, float(qangle(qmul(qinv(rel[:1]), rel)).max()))
        return round(best, 1)

    def rel_range(bones, ref_of):
        """Peak-to-peak: the largest angle between any two samples of a bone's reference-relative rotation."""
        best = 0.0
        for i in bones:
            r = ref_of(i)
            if r is None:
                continue
            rel = qmul(qinv(model[r]), model[i])
            best = max(best, float(qangle(qmul(qinv(rel)[:, None], rel[None, :])).max()))
        return round(best, 1)

    wings = [i for i in range(n) if reg[i] == "wing"]
    legs = [i for i in range(n) if reg[i] == "leg"]
    arms = [i for i in range(n) if reg[i] == "arm"]

    def torso_of(i):
        return next((a for a in ancestors(i) if reg[a] != "wing"), None)
    limbs = wings + legs
    body = None
    if limbs:
        common = set(ancestors(limbs[0]))
        for i in limbs[1:]:
            common &= set(ancestors(i))
        body = max(common, key=lambda a: len(ancestors(a)), default=None)
    out = {"wingBones": len(wings)}
    if wings:
        out["wingSwing"] = rel_swing(wings, torso_of)
        out["wingRange"] = rel_range(wings, torso_of)
        roots = [i for i in wings if reg.get(parent.get(i)) != "wing"]
        folds = []
        for r in roots:
            chain = [i for i in wings if r in ancestors(i)]
            if chain:
                deep = max(chain, key=lambda i: len(ancestors(i)))
                rel = qmul(qinv(model[r]), model[deep])
                folds.append(float(qangle(qmul(qinv(rel[:1]), rel)).max()))
        if folds:
            out["wingFold"] = round(max(folds), 1)
    if legs and body is not None:
        out["legSwing"] = rel_swing(legs, lambda i: body)
    if arms and body is not None:
        out["armSwing"] = rel_swing(arms, lambda i: body)
    torso = torso_of(wings[0]) if wings else body
    if torso is not None:
        out["bodyRot"] = round(float(qangle(qmul(qinv(model[torso][:1]), model[torso])).max()), 1)
        out["bodyBone"] = names[torso]
    limb = max([out.get(k, 0.0) for k in ("wingSwing", "legSwing", "armSwing")] + [1e-6])
    if "bodyRot" in out:
        out["toyRatio"] = round(out["bodyRot"] / limb, 2)
    return out


JITTER_CUTOFF_HZ = 4.0   # a walk/fly cycle's fundamental and first harmonics sit below this; wobble sits above
JITTER_MIN_TRAVEL = 5.0  # deg: a bone whose rotation spans less than this over the clip is not scored
# gate: 90th-percentile bone's share of motion energy above the cutoff. Vanilla OE (2026-09-26 read, 30 Hz):
# Walk p90-over-units 0.217 (median 0.071, max 0.98), Attack 0.30, Fly 0.036. Every fleet selection's Move measured
# at or under 0.31 (h3_storm_elemental, conflux_light) except two flyers already on the articulation debt list
# (0.449 battle griffin, 0.425 green dragon); the cap sits above the fleet so it catches a regression, not taste.
JITTER_P90_MAX = 0.35


def rotvec(q):
    """(T, 4) xyzw -> (T, 3) rotation vectors in degrees (shortest arc)."""
    q = np.where(q[:, 3:4] < 0, -q, q)
    s = np.linalg.norm(q[:, :3], axis=1)
    ang = 2 * np.degrees(np.arctan2(s, q[:, 3]))
    return q[:, :3] / np.maximum(s, 1e-12)[:, None] * ang[:, None]


def jitter_metrics(names: list[str], local: dict[int, np.ndarray], hz: float = SAMPLE_HZ) -> dict:
    """High-frequency share of each bone's own (parent-relative) rotation.

    Per scored bone: the rotation relative to its clip mean as a rotation vector, linearly detrended (so a
    one-shot clip's drift is not read as a spectrum), and the share of its spectral energy above
    JITTER_CUTOFF_HZ. A smooth swing puts almost all energy in the cycle's low harmonics; a pose-per-frame
    fit that wobbles or steps between sparse keys puts it high. Reports median / 90th percentile over bones
    whose rotation spans JITTER_MIN_TRAVEL degrees, and the worst bone."""
    shares = []
    for i, q in local.items():
        if len(q) < 8:
            continue
        m = q.mean(axis=0)
        m = m / max(np.linalg.norm(m), 1e-12)
        v = rotvec(qnorm(qmul(np.tile(qinv(m[None])[0], (len(q), 1)), q)))
        if float(np.ptp(v, axis=0).max()) < JITTER_MIN_TRAVEL:
            continue
        t = np.arange(len(v))
        v = v - (np.outer(t, (v[-1] - v[0]) / (len(v) - 1)) + v[0])   # end-to-end detrend: periodic for the FFT
        spec = (np.abs(np.fft.rfft(v, axis=0)) ** 2).sum(axis=1)
        f = np.fft.rfftfreq(len(v), 1.0 / hz)
        tot = float(spec[1:].sum())
        if tot <= 0:
            continue
        shares.append((float(spec[f > JITTER_CUTOFF_HZ].sum()) / tot, names[i]))
    if not shares:
        return {}
    r = np.array([x for x, _ in shares])
    worst = max(shares)
    return {"jitterMedian": round(float(np.median(r)), 4), "jitterP90": round(float(np.percentile(r, 90)), 4),
            "jitterWorst": round(worst[0], 4), "jitterWorstBone": worst[1], "jitterBones": len(shares)}


# Freeze gate (every clip, default on; 2026-09-27): a mesh pose held over FREEZE_RUN_MAX or more consecutive DEF
# frames while the DEF itself moves reads as a stall (and usually a pop after it). Pose-follow trial B held a death's
# first pose for 4-5 frames while its DEF hopped: better silhouette IoU, a worse death. "Same" = no bone turns more
# than FREEZE_EPS_DEG and no bone translates more than FREEZE_EPS_REL x the skeleton's summed rest offsets.
# DEF-relative, measured on the DEF's shape (docs/homm3_teleport_freeze_semantics.md): a held step is excused where
# the DEF itself holds or its body is gone. Only unexcused held steps count toward the run. Frames are the clip's key times on the DEF
# grid: the multi-key time set whose length is the DEF segment's frame count (or one more, a loop copy). A clip off
# that grid (emphasis keys, no DEF segment) is measured strictly on its sparsest multi-key set, nothing excused
# (defAligned false); a resampled clip (idle retime, 30 Hz) is measured on its pre-resample input (freeze_check).
FREEZE_RUN_MAX = 3
FREEZE_EPS_DEG = 0.05
FREEZE_EPS_REL = 1e-4
FREEZE_EPS_SCALE = 1e-4
# key spacing under this = a resample (idle retime: 1/30 s); a stride-matched Move keeps >= 1/12/1.6 = 0.052 s
FREEZE_MIN_SPACING_S = 0.045
MASTER_RUNS = ROOT / "artifacts/homm3_mocap_v2/full_set_mocap_idle0_v1/runs"
TELEPORT_EFFECT_WINDOWS = HERE / "reference/teleport_effect_windows.json"
# inferno_teleport.py keys the hidden body at 0.001. This only establishes invisibility for the exact
# source-pinned cloud windows; it never excuses a visible mesh or a held pose elsewhere.
TELEPORT_HIDDEN_SCALE_MAX = 0.0011


# DEF shape evidence (2026-09-27). A source frame's body is its non-shadow silhouette: alpha == 255 (the extraction
# draws the HoMM3 shadow indices as black at alpha 64 / 128, and a colour-cycled or shimmering palette leaves alpha
# alone). Two measured states excuse a held mesh pose, and nothing else does:
#   DEF hold     every pair of source frames under one held mesh run has silhouettes within DEF_HOLD_PX of each other
#                (symmetric Hausdorff distance), i.e. the DEF's shape is unchanged apart from colour and one-pixel
#                contour dither. Whole-frame hashes read the enchanter's Mouseover glyph shimmer (1660 px of colour per
#                step, 53 px of alternating contour dither, spread 1.414) as motion.
#   body absent  the frame's silhouette above the ground band (the lowest DEF_GROUND_BAND of the unit's Idle frame 0
#                body height) is at most DEF_ABSENT_FRAC of Idle frame 0's: only a floor-level effect or ripple remains.
#                A held step between two such frames is excused only when the GLB proves the weighted body collapsed
#                (hidden_body_root audit, Hips scale <= TELEPORT_HIDDEN_SCALE_MAX at both frames); a visible mesh stays
#                a fault. The cutoffs and their margins over the 79 frozen deliveries are in the doc.
DEF_HOLD_PX = 1.4143           # sqrt(2): every contour pixel within one (diagonal) pixel of the other frame's shape
DEF_ABSENT_FRAC = 0.005        # absent frames measure 0; the lowest present frame in the frozen fleet 0.0127
DEF_GROUND_BAND = 0.25


class DefFrame:
    """One DEF source frame: RGBA hash, non-shadow silhouette (cropped) and whether its body is absent."""
    __slots__ = ("hash", "sil", "absent", "above")

    def __init__(self, hash_: str, sil: np.ndarray | None = None, absent: bool = False, above: int | None = None):
        self.hash, self.sil, self.absent, self.above = hash_, sil, absent, above


def as_def_frame(f) -> DefFrame:
    return f if isinstance(f, DefFrame) else DefFrame(str(f))


def silhouette_spread(frames: list) -> float:
    """Largest symmetric Hausdorff distance (px) between the silhouettes of any two frames (inf if one is unknown)."""
    from scipy import ndimage
    sils = [f.sil for f in frames]
    if any(m is None for m in sils):
        return math.inf
    worst = 0.0
    dts = [None if not m.any() else ndimage.distance_transform_edt(~m) for m in sils]
    for i in range(len(sils)):
        for j in range(i + 1, len(sils)):
            a, b = sils[i], sils[j]
            if not a.any() or not b.any():
                if a.any() != b.any():
                    return math.inf
                continue
            worst = max(worst, float(dts[j][a].max()), float(dts[i][b].max()))
    return worst


def def_frames(unit: str) -> dict:
    """{contract suffix: [per-frame DefFrame lists, one per segment]} from the unit's master sequence."""
    from PIL import Image
    p = MASTER_RUNS / unit / "linked_master/master_sequence/master_sequence.json"
    if not p.is_file():
        raise SystemExit(f"{unit}: no master sequence at {p} (the freeze gate needs the DEF frames)")
    ms = json.loads(p.read_text(encoding="utf-8"))
    raw: dict = {}

    def load(t):
        src = ms["frames"][t]["sourcePng"]
        if src not in raw:
            with Image.open(src) as im:
                a = np.asarray(im.convert("RGBA"))
            raw[src] = (hashlib.sha1(a.tobytes()).hexdigest(), a[..., 3] == 255)
        return raw[src]
    idle = [sg for sg in ms["segments"] if sg["contractSuffix"] == "Idle"]
    if not idle:
        raise SystemExit(f"{unit}: master sequence has no Idle segment (the body-absent reference is Idle frame 0)")
    ref = load(idle[0]["globalStart"])[1]
    rows = np.flatnonzero(ref.any(axis=1))
    if not len(rows):
        raise SystemExit(f"{unit}: Idle frame 0 has no opaque body")
    band_top = int(rows[-1] - DEF_GROUND_BAND * (rows[-1] - rows[0] + 1))
    ref_above = int(ref[:band_top].sum())
    if ref_above <= 0:
        raise SystemExit(f"{unit}: Idle frame 0 has no body above its ground band")
    out: dict = {}
    for sg in ms["segments"]:
        fs = []
        for t in range(sg["globalStart"], sg["globalEnd"]):
            h, m = load(t)
            above = int(m[:band_top].sum())
            fs.append(DefFrame(h, m, above <= DEF_ABSENT_FRAC * ref_above, above))
        out.setdefault(sg["contractSuffix"], []).append(fs)
    return out


def scale_magnitudes(js, acc, anim, node: int, times: np.ndarray):
    """(max |scale| per time, None) for one node's authored scale in one clip, or (None, why) if unauditable."""
    tracks = [anim["samplers"][ch["sampler"]] for ch in anim["channels"]
              if ch["target"]["node"] == node and ch["target"]["path"] == "scale"]
    if len(tracks) > 1:
        return None, f"{anim['name']} has duplicate scale tracks at node {node}"
    if tracks:
        s = tracks[0]
        if s.get("interpolation", "LINEAR") not in ("LINEAR", "STEP"):
            return None, f"{anim['name']} scale node {node} needs LINEAR or STEP interpolation"
        kt, kv = acc(s["input"])[:, 0], acc(s["output"])
        if (kv.shape != (len(kt), 3) or not np.all(np.isfinite(kt)) or
                not np.all(np.isfinite(kv)) or np.any(np.diff(kt) <= 0)):
            return None, f"{anim['name']} scale node {node} has invalid keys"
        if s.get("interpolation", "LINEAR") == "STEP":
            v = kv[np.clip(np.searchsorted(kt, times, side="right") - 1, 0, len(kt) - 1)]
        else:
            v = np.stack([np.interp(times, kt, kv[:, c]) for c in range(3)], axis=1)
    else:
        v = np.tile(js["nodes"][node].get("scale", [1, 1, 1]), (len(times), 1))
    mag = np.max(np.abs(v), axis=1)
    if not np.all(np.isfinite(mag)):
        return None, f"{anim['name']} has nonfinite scale at node {node}"
    return mag, None


def freeze_metrics(js, acc, anim, idx: dict, extent: float, def_segs: list | None = None,
                   effect_window: dict | None = None, hidden_root: int | None = None,
                   scale_nodes: set[int] | None = None, body_audit: str | None = None) -> dict:
    """Longest run of identical consecutive frame poses in one clip, DEF-excused (see FREEZE_RUN_MAX).
    A clip densified by densify_clip_glb.py (asset.extras stamp) is measured on its original keys, which that tool
    keeps on the keysPerSpan stride."""
    chans = [(ch, anim["samplers"][ch["sampler"]]) for ch in anim["channels"]
             if ch["target"]["node"] in idx and ch["target"]["path"] in ("rotation", "translation", "scale")]
    if effect_window is not None:
        for ch in anim["channels"]:
            if ch["target"]["path"] != "scale" or ch["target"]["node"] not in (scale_nodes or set()):
                continue
            sampler = anim["samplers"][ch["sampler"]]
            node = ch["target"]["node"]
            if sampler.get("interpolation", "LINEAR") not in ("LINEAR", "STEP"):
                return {"freezeEvidence": f"{anim['name']} cloud scale node {node} needs LINEAR or STEP interpolation"}
            kt, kv = acc(sampler["input"])[:, 0], acc(sampler["output"])
            if (kv.shape != (len(kt), 3) or not np.all(np.isfinite(kt)) or
                    not np.all(np.isfinite(kv)) or np.any(np.diff(kt) <= 0)):
                return {"freezeEvidence": f"{anim['name']} cloud scale node {node} has invalid keys"}
    sets = {tuple(np.round(acc(s["input"])[:, 0], 5)) for _, s in chans}
    dens = (js.get("asset", {}).get("extras", {}).get("homm3DefRetargetDeliveryDensify") or {})
    if anim["name"] in dens.get("clips", {}):
        k = int(dens["keysPerSpan"])
        bad = [len(t) for t in sets if len(t) > 2 and (len(t) - 1) % k]
        if bad:
            return {"freezeResampled": f"densified x{k} but key sets {bad} are off that stride"}
        sets = {t[::k] if len(t) > 2 else t for t in sets}
    sets = sorted((k for k in sets if len(k) > 2), key=len)
    if not sets:
        return {"frames": 2 if chans else 0, "freezeRun": 1 if chans else 0, "rawFreezeRun": 1 if chans else 0}
    dh = None
    segs = [[as_def_frame(f) for f in h] for h in (def_segs or [])]
    cand = [(k, h) for h in sorted(segs, key=len, reverse=True) for k in sets if len(k) in (len(h), len(h) + 1)]
    if cand:
        times, dh = np.array(cand[0][0]), list(cand[0][1])
        if len(times) == len(dh) + 1:
            dh.append(dh[0])                     # the loop key repeats frame 0
    else:
        # keys off the DEF grid (emphasis adds keys; no DEF segment): measured strictly on the sparsest key set,
        # unless that set is a resample (idle retime, 1/30 s), which freeze_check measures on its input instead
        times = np.array(sets[0])
        if float(np.median(np.diff(times))) < FREEZE_MIN_SPACING_S:
            return {"freezeResampled": f"keys every {float(np.median(np.diff(times))):.3f} s ({len(times)} keys)"}
    ang = np.zeros(len(times) - 1); mov = np.zeros(len(times) - 1); scl = np.zeros(len(times) - 1)
    absent = np.array([f.absent for f in dh]) if dh is not None else np.zeros(len(times), bool)
    body_scale_counts = effect_window is not None or bool(absent.any())
    for ch, s in chans:
        if ch["target"]["path"] == "scale" and (not body_scale_counts or ch["target"]["node"] != hidden_root):
            continue
        kt, kv = acc(s["input"])[:, 0], acc(s["output"]).copy()
        if ch["target"]["path"] == "rotation":
            for c in range(1, len(kv)):
                if np.dot(kv[c], kv[c - 1]) < 0:
                    kv[c] = -kv[c]
        if ch["target"]["path"] == "scale" and s.get("interpolation", "LINEAR") == "STEP":
            v = kv[np.clip(np.searchsorted(kt, times, side="right") - 1, 0, len(kt) - 1)]
        else:
            v = np.stack([np.interp(times, kt, kv[:, c]) for c in range(kv.shape[1])], axis=1)
        if ch["target"]["path"] == "rotation":
            v = qnorm(v)
            d = np.abs(np.sum(v[1:] * v[:-1], axis=1)).clip(0, 1)
            ang = np.maximum(ang, 2 * np.degrees(np.arccos(d)))
        elif ch["target"]["path"] == "translation":
            mov = np.maximum(mov, np.linalg.norm(np.diff(v, axis=0), axis=1))
        else:
            scl = np.maximum(scl, np.max(np.abs(np.diff(v, axis=0)), axis=1))
    same = (ang < FREEZE_EPS_DEG) & (mov < FREEZE_EPS_REL * extent) & (scl < FREEZE_EPS_SCALE)
    excused = np.zeros_like(same) if dh is None else np.array([dh[i + 1].hash == dh[i].hash for i in range(len(same))])
    effect_steps = np.zeros_like(same)
    if effect_window is not None:
        if dh is None or len(times) != effect_window["frameCount"] or hidden_root is None or not scale_nodes:
            return {"freezeEvidence": f"{anim['name']} cloud window needs its DEF grid and audited scale hierarchy"}
        expected_times = np.arange(1, len(times) + 1) * effect_window["frameDurationS"]
        if not np.allclose(times, expected_times, rtol=0, atol=1e-4):
            return {"freezeEvidence": f"{anim['name']} cloud window keys are not on the pinned DEF time grid"}
        a, b = effect_window["frames"]
        hidden_scale = None
        for node in scale_nodes:
            tracks = [anim["samplers"][ch["sampler"]] for ch in anim["channels"]
                      if ch["target"]["node"] == node and ch["target"]["path"] == "scale"]
            if len(tracks) > 1:
                return {"freezeEvidence": f"{anim['name']} has duplicate scale tracks at node {node}"}
            if tracks:
                kt, kv = acc(tracks[0]["input"])[:, 0], acc(tracks[0]["output"])
                if tracks[0].get("interpolation", "LINEAR") == "STEP":
                    v = kv[np.clip(np.searchsorted(kt, times, side="right") - 1, 0, len(kt) - 1)]
                else:
                    v = np.stack([np.interp(times, kt, kv[:, c]) for c in range(3)], axis=1)
            else:
                v = np.tile(js["nodes"][node].get("scale", [1, 1, 1]), (len(times), 1))
            magnitudes = np.max(np.abs(v), axis=1)
            if not np.all(np.isfinite(magnitudes)):
                return {"freezeEvidence": f"{anim['name']} has nonfinite scale at node {node}"}
            if node == hidden_root:
                if not tracks:
                    return {"freezeEvidence": f"{anim['name']} cloud window needs animated Hips scale"}
                hidden_scale = magnitudes
            elif np.any(magnitudes[a:b + 1] > 1.0001):
                return {"freezeEvidence": f"{anim['name']} cloud window has an expanding scale at node {node}"}
        collapsed = hidden_scale <= TELEPORT_HIDDEN_SCALE_MAX
        effect_steps[a:b] = collapsed[a:b] & collapsed[a + 1:b + 1]
        if not np.all(collapsed[a:b + 1]):
            return {"freezeEvidence": f"{anim['name']} cloud window [{a},{b}] has visible weighted body scale "
                                      f"{float(hidden_scale[a:b + 1].max()):.6f}"}
        excused |= effect_steps
    # body absent (DEF_ABSENT_FRAC): a held step between two body-absent DEF frames is excused only on the collapsed
    # weighted body; an unauditable skin or scale is a reason in the fault, never an excuse
    absent_steps = np.zeros_like(same)
    absent_why = None
    pair = absent[:-1] & absent[1:]
    if pair.any():
        absent_why = body_audit or (None if hidden_root is not None and scale_nodes else "no audited Hips scale hierarchy")
        hid = None
        if absent_why is None:
            hid, absent_why = scale_magnitudes(js, acc, anim, hidden_root, times)
        expanding = np.zeros(len(times), bool)
        for node in sorted(scale_nodes or ()):
            if absent_why is not None or node == hidden_root:
                continue
            mag, absent_why = scale_magnitudes(js, acc, anim, node, times)
            if mag is not None:
                expanding |= mag > 1.0001
        if absent_why is None:
            if not any(ch["target"]["node"] == hidden_root and ch["target"]["path"] == "scale" for ch in anim["channels"]):
                absent_why = f"{anim['name']} has no animated Hips scale"
            else:
                col = (hid <= TELEPORT_HIDDEN_SCALE_MAX) & ~expanding
                absent_steps = pair & col[:-1] & col[1:]
        excused |= absent_steps
    # DEF hold (DEF_HOLD_PX): a held run whose DEF frames all keep one silhouette is the DEF holding too. Never between
    # body-absent frames: a still ripple does not license a visible body (only the collapse proof above does)
    hold_steps = np.zeros_like(same)
    if dh is not None:
        m, i = same & ~excused & ~pair, 0
        while i < len(m):
            if not m[i]:
                i += 1
                continue
            j = i
            while j + 1 < len(m) and m[j + 1]:
                j += 1
            if j - i + 2 >= FREEZE_RUN_MAX and silhouette_spread(dh[i:j + 2]) <= DEF_HOLD_PX:
                hold_steps[i:j + 1] = True
            i = j + 1
        excused |= hold_steps

    def longest(mask):
        best, at, run = 1, None, 1
        for i, s_ in enumerate(mask):
            run = run + 1 if s_ else 1
            if run > best:
                best, at = run, i + 2 - run
        return best, at
    best, at = longest(same & ~excused)
    out = {"frames": len(times), "freezeRun": best, "rawFreezeRun": longest(same)[0], "defAligned": dh is not None}
    if effect_window is not None:
        out["collapsedCloudStepsExcused"] = int(effect_steps.sum())
    if pair.any():
        out["bodyAbsentFrames"] = int(absent.sum())
        out["bodyAbsentStepsExcused"] = int(absent_steps.sum())
        if absent_why is not None and np.any(pair & same & ~excused):
            out["bodyAbsentEvidence"] = absent_why
    if hold_steps.any():
        out["defHoldStepsExcused"] = int(hold_steps.sum())
    if at is not None:
        out["freezeAtFrame"] = at
    return out


def freeze_gate(clips: dict) -> list[str]:
    """Freeze faults over every clip of one glb_clips() result (empty = passes). A resampled clip is a fault here;
    freeze_check measures it on the pre-resample input instead."""
    bad = []
    for c, m in sorted(clips.items()):
        if m.get("freezeEvidence"):
            bad.append(f"{c} not measured: {m['freezeEvidence']}")
        elif m.get("freezeResampled"):
            bad.append(f"{c} not measured: {m['freezeResampled']}")
        elif m.get("freezeRun", 0) >= FREEZE_RUN_MAX:
            why = f" (body-absent frames not excused: {m['bodyAbsentEvidence']})" if m.get("bodyAbsentEvidence") else ""
            bad.append(f"{c} holds one pose for {m['freezeRun']} frames from frame {m.get('freezeAtFrame')} while the "
                       f"DEF moves (max {FREEZE_RUN_MAX - 1}){why}")
    return bad


def freeze_check(unit: str, glb: Path, pre_resample: Path | None = None) -> tuple[list[str], dict]:
    """Freeze gate for a delivered GLB against its DEF. A clip resampled off the DEF grid (idle retime) is measured
    on pre_resample (the slice's inputs/look_delivered.glb); a missing or also-resampled input fails closed.
    Returns (faults, {clip: {"glb": measured path name, ...metrics}})."""
    dh = def_frames(unit)
    effect_windows = teleport_effect_windows(unit)
    main = glb_clips(glb, dh, effect_windows)
    pre = None
    rec, bad = {}, []
    for c, m in sorted(main.items()):
        src = glb
        if m.get("freezeResampled"):
            if pre is None:
                if pre_resample is None or not Path(pre_resample).is_file():
                    bad.append(f"{c} is resampled ({m['freezeResampled']}) and its pre-resample input "
                               f"{pre_resample} is missing")
                    rec[c] = {"glb": None, **m}
                    continue
                pre = glb_clips(Path(pre_resample), dh, effect_windows)
            src, m = Path(pre_resample), pre.get(c, {"freezeResampled": "clip absent from the pre-resample input"})
        rec[c] = {"glb": src.name, **{k: v for k, v in m.items() if k.startswith(("freeze", "rawFreeze", "frames", "defAligned", "collapsedCloud", "defHold", "bodyAbsent"))}}
        bad += [f"{b} [{src.name}]" for b in freeze_gate({c: m})]
    from gate_exceptions import apply as gate_exceptions  # the unit's user-approved, value-pinned exceptions
    bad, excused = gate_exceptions(unit, "freeze", bad)
    for x in excused:
        rec.setdefault(x["key"].split(":")[0], {})["gateException"] = x
    return bad, rec


def def_wing_row(unit: str | None) -> dict | None:
    """The unit's DEF wing-range row, checked: {rangeDeg, boundsDeg [lo, hi]} with lo <= rangeDeg <= hi."""
    if unit is None:
        return None
    row = json.loads(DEF_WING_RANGE.read_text(encoding="utf-8"))["units"].get(unit)
    if row is None:
        return None
    b = row.get("boundsDeg")
    if not (isinstance(b, list) and len(b) == 2 and float(b[0]) <= float(row["rangeDeg"]) <= float(b[1])):
        raise SystemExit(f"{unit}: {DEF_WING_RANGE.name} row needs boundsDeg [lo, hi] around rangeDeg, got {row}")
    return row


def def_wing_range(unit: str | None) -> float | None:
    row = def_wing_row(unit)
    return None if row is None else float(row["rangeDeg"])


def wing_rule(unit: str | None) -> tuple[str, float | None]:
    """(rule, required wingRange or None for flatFloor) that judges this unit's wings; see the note at DEF_RANGE_SHARE."""
    row = def_wing_row(unit)
    if row is None:
        return "flatFloor", None
    if DEF_RANGE_SHARE * float(row["rangeDeg"]) < WING_SWING_MIN:
        return "defRowUpperBound", round(DEF_RANGE_SHARE * float(row["boundsDeg"][1]), 1)
    return "defRow", round(DEF_RANGE_SHARE * float(row["rangeDeg"]), 1)


FLIERS_TABLE = HERE / "reference" / "homm3_fliers.json"


def move_rule(unit: str | None) -> str:
    """"teleportMove" when the unit's DEF has no Move to swing, else "standard".

    teleportMove needs BOTH: the flier table row (reference/homm3_fliers.json) lists flyingSubtypes
    movementTeleporting, and every Move segment of the unit's master sequence (its DEF Move) is exactly 1 frame
    (h3_devil / h3_arch_devil / h3_arch_demon: MoveStart 14 frames vanish, Move 1, MoveEnd 10 appear). It skips only
    the Move swing floors (wing and leg); jitter and every other check stay, and the freeze gate still measures
    MoveStart / MoveEnd, the clips that carry the motion. A DEF-relative exemption like strideExempt for legless
    units, not a relaxation of any unit that walks or flaps in its DEF. A teleporter whose master sequence is
    missing is refused; one whose DEF Move has more frames is judged by the standard rule."""
    if unit is None:
        return "standard"
    row = json.loads(FLIERS_TABLE.read_text(encoding="utf-8"))["units"].get(unit) or {}
    if "movementTeleporting" not in (row.get("flyingSubtypes") or []):
        return "standard"
    p = MASTER_RUNS / unit / "linked_master/master_sequence/master_sequence.json"
    if not p.is_file():
        raise SystemExit(f"{unit}: movementTeleporting but no master sequence at {p} to show its DEF Move frame count")
    counts = [sg["frameCount"] for sg in json.loads(p.read_text(encoding="utf-8"))["segments"] if sg["contractSuffix"] == "Move"]
    return "teleportMove" if counts and all(c == 1 for c in counts) else "standard"


def teleport_effect_windows(unit: str) -> dict:
    """Exact source-reviewed cloud windows in which the authored teleport hides the body.

    This is not a changed-pixel heuristic: the window must equal the unit's authored vanish/reappear bounds, its
    original DEF PNGs and opaque-all effect masks must match the pinned bytes, and freeze_metrics separately
    verifies that the delivered weighted body is collapsed on every excused frame.
    """
    cfg_path = ROOT / "tools/homm3_def_retarget/units" / f"{unit}.json"
    ref = json.loads(TELEPORT_EFFECT_WINDOWS.read_text(encoding="utf-8"))
    if ref.get("schema") != "homm3_def_teleport_effect_windows.v1":
        raise SystemExit(f"{TELEPORT_EFFECT_WINDOWS.name}: wrong schema")
    row = ref["units"].get(unit)
    cfg = json.loads(cfg_path.read_text(encoding="utf-8")) if cfg_path.is_file() else {}
    tp = cfg.get("teleport")
    if tp is None and row is None:
        return {}
    if tp is None or row is None:
        raise SystemExit(f"{unit}: authored teleport and {TELEPORT_EFFECT_WINDOWS.name} row must both exist")
    if move_rule(unit) != "teleportMove":
        raise SystemExit(f"{unit}: cloud-window evidence needs movementTeleporting and a one-frame DEF Move")
    if (not isinstance(tp, dict) or set(tp) != {"out", "in"} or
            any(not isinstance(tp.get(k), list) or len(tp[k]) != 3 for k in ("out", "in")) or
            tp["out"][0] != "MoveStart" or tp["in"][0] != "MoveEnd" or
            any(not isinstance(x, int) for x in (*tp["out"][1:], *tp["in"][1:]))):
        raise SystemExit(f"{unit}: teleport out/in config does not name exact MoveStart/MoveEnd frame bounds")
    if not (0 <= tp["out"][1] < tp["out"][2] and 0 < tp["in"][1] < tp["in"][2]):
        raise SystemExit(f"{unit}: teleport vanish/reappear bounds are invalid")

    ms = json.loads((MASTER_RUNS / unit / "linked_master/master_sequence/master_sequence.json").read_text(encoding="utf-8"))
    if (not isinstance(ms.get("sourceFrameMs"), (int, float)) or not math.isfinite(ms["sourceFrameMs"]) or
            ms["sourceFrameMs"] <= 0 or abs(ms["sourceFrameMs"] - ref.get("sourceFrameMs", 0)) > 1e-6):
        raise SystemExit(f"{unit}: master DEF frame cadence differs from {TELEPORT_EFFECT_WINDOWS.name}")
    mask_dir = (ROOT / row["effectMaskDir"]).resolve()
    if not mask_dir.is_relative_to(ROOT.resolve()):
        raise SystemExit(f"{unit}: effect mask directory escapes the repository")
    from PIL import Image
    windows = {}
    for clip, bounds in (("MoveStart", tp["out"]), ("MoveEnd", tp["in"])):
        segs = [s for s in ms["segments"] if s["contractSuffix"] == clip]
        if len(segs) != 1:
            raise SystemExit(f"{unit}: {clip} needs one DEF segment for cloud-window evidence, got {len(segs)}")
        seg = segs[0]
        frames = [bounds[2], seg["frameCount"] - 1] if clip == "MoveStart" else [0, bounds[1] - 1]
        pinned = row.get(clip) or {}
        if (pinned.get("defGroup") != seg["defGroup"] or pinned.get("frames") != frames or
                frames[0] < 0 or frames[1] >= seg["frameCount"] or frames[0] >= frames[1]):
            raise SystemExit(f"{unit}: {clip} cloud window differs from authored teleport/DEF bounds")
        source_shas, mask_shas = [], []
        for i in range(frames[0], frames[1] + 1):
            f = ms["frames"][seg["globalStart"] + i]
            src = Path(f["sourcePng"])
            mask = mask_dir / f"{seg['defGroup']:02}_{i:02}.png"
            if src.stem != mask.stem or not src.is_file() or not mask.is_file():
                raise SystemExit(f"{unit}: {clip} frame {i} lacks its matching source PNG/effect mask")
            sh = hashlib.sha256(src.read_bytes()).hexdigest()
            if sh != f["sourceSha256"]:
                raise SystemExit(f"{unit}: {clip} frame {i} source PNG differs from its master sequence")
            source_shas.append(sh)
            mask_shas.append(hashlib.sha256(mask.read_bytes()).hexdigest())
            with Image.open(src) as im, Image.open(mask) as mk:
                alpha = np.asarray(im.convert("RGBA"))[..., 3]
                opaque_all = np.asarray(mk.convert("L")) > 0
            if opaque_all.shape != alpha.shape or not np.any(opaque_all) or not np.array_equal(opaque_all, alpha == 255):
                raise SystemExit(f"{unit}: {clip} frame {i} mask is not the source's opaque fire-cloud sprite")
        if (hashlib.sha256("".join(source_shas).encode()).hexdigest() != pinned.get("sourceSetSha256") or
                hashlib.sha256("".join(mask_shas).encode()).hexdigest() != pinned.get("effectMaskSetSha256")):
            raise SystemExit(f"{unit}: {clip} source/effect-mask pins changed; review the DEF cloud frames before updating")
        windows[f"Unit_{clip}"] = {"frames": frames, "frameCount": seg["frameCount"],
                                   "frameDurationS": ms["sourceFrameMs"] / 1000.0}
    return windows


def teleport_reference_errors() -> list[str]:
    """Build-time static gate, including configured units not currently frozen in a selection."""
    ref = json.loads(TELEPORT_EFFECT_WINDOWS.read_text(encoding="utf-8"))
    cfg_dir = ROOT / "tools/homm3_def_retarget/units"
    configured = {p.stem for p in cfg_dir.glob("*.json") if json.loads(p.read_text(encoding="utf-8")).get("teleport")}
    errors = []
    for unit in sorted(configured | set(ref["units"])):
        try:
            teleport_effect_windows(unit)
        except (SystemExit, KeyError, ValueError, OSError) as exc:
            errors.append(f"{unit}: {exc}")
    return errors


def gate(m: dict, unit: str | None = None) -> list[str]:
    """Under-articulation faults of one Unit_Move measurement (empty = passes). unit: the lab sid, for its DEF
    wing range (reference/def_wing_range.json); wing_rule(unit) names the rule that judged the wings and
    move_rule(unit) whether the Move swing floors apply at all (teleportMove skips them; jitter stays)."""
    bad = []
    teleport = move_rule(unit) == "teleportMove"
    if m.get("wingBones") and not teleport:
        w = m.get("wingSwing", 0.0)
        rng = m.get("wingRange", w)
        rule, need = wing_rule(unit)
        if rule == "flatFloor":
            if rng < WING_SWING_MIN:
                bad.append(f"wings beat {rng} deg peak to peak relative to the torso (flatFloor {WING_SWING_MIN:.0f}; "
                           "vanilla Fly min 86.4)")
            elif w < WING_SWING_MIN:
                bad.append(f"wings swing {w} deg from frame 0 (flatFloor {WING_SWING_MIN:.0f}) and {rng} deg peak to peak; "
                           f"a peak-to-peak pass needs the DEF's measured range in {DEF_WING_RANGE.name}")
        elif rng < need:
            bad.append(f"wings beat {rng} deg peak to peak, under {rule} {need} ({DEF_RANGE_SHARE} x the DEF's "
                       f"{'upper bound' if rule == 'defRowUpperBound' else 'range'})")
        toy = m.get("bodyRot", 0.0) / max(w, 1e-6)
        if toy > FLYER_TOY_MAX:
            bad.append(f"body turns {toy:.2f}x the wing swing (bodyRot {m.get('bodyRot')}; cap {FLYER_TOY_MAX}; vanilla Fly max 0.42)")
    elif not teleport and "legSwing" in m and m["legSwing"] < LEG_SWING_MIN:
        bad.append(f"legs swing {m['legSwing']} deg relative to the body (floor {LEG_SWING_MIN:.0f}; vanilla Walk min 20.3)")
    if m.get("jitterP90", 0.0) > JITTER_P90_MAX:
        bad.append(f"jittery: {m['jitterP90']:.2f} of the p90 bone's motion is above {JITTER_CUTOFF_HZ:.0f} Hz "
                   f"(worst {m.get('jitterWorstBone')}; cap {JITTER_P90_MAX}; vanilla Walk p90 0.22)")
    from gate_exceptions import apply as gate_exceptions  # the unit's user-approved, value-pinned exceptions
    return gate_exceptions(unit, "articulation", bad)[0]


# ---------------------------------------------------------------- our GLBs
def read_glb(path: Path | bytes):
    """(json, accessor reader) of a GLB file, or of a GLB's bytes (an in-memory delivery stage's output)."""
    b = bytes(path) if isinstance(path, (bytes, bytearray)) else Path(path).read_bytes()
    if isinstance(path, (bytes, bytearray)):
        path = "<in-memory GLB>"
    jl = struct.unpack_from("<I", b, 12)[0]
    js = json.loads(b[20:20 + jl])
    binc = b[28 + jl:]

    def acc(i):
        a = js["accessors"][i]
        bv = js["bufferViews"][a["bufferView"]]
        w = {"SCALAR": 1, "VEC3": 3, "VEC4": 4}[a["type"]]
        if a.get("componentType") != 5126 or bv.get("byteStride", 4 * w) != 4 * w:
            raise SystemExit(f"{path}: accessor {i} is not tightly packed float")
        return np.frombuffer(binc, dtype="<f4", count=w * a["count"],
                             offset=bv.get("byteOffset", 0) + a.get("byteOffset", 0)).reshape(a["count"], w).astype(float)
    return js, acc


def hidden_body_root(path: Path, js: dict) -> tuple[int, set[int]]:
    """The scale node that collapses every weighted body vertex, or fail closed.

    The authored teleport scales Hips. A root-only scale stamp is not enough: every nonzero skin influence of
    every mesh must live below Hips in the GLB hierarchy, so a detached body/prop cannot be excused by it.
    """
    if len(js.get("skins", [])) != 1:
        raise SystemExit(f"{path}: teleport cloud needs exactly one body skin")
    skin = js["skins"][0]
    joints = skin["joints"]
    hips = [j for j in joints if js["nodes"][j].get("name") == "Hips"]
    if len(hips) != 1:
        raise SystemExit(f"{path}: teleport cloud needs one skinned Hips node")
    descendants, pending = set(), hips[:]
    while pending:
        node = pending.pop()
        if node not in descendants:
            descendants.add(node)
            pending.extend(js["nodes"][node].get("children", []))
    covered = np.array([j in descendants for j in joints], dtype=bool)
    blob = bytes(path) if isinstance(path, (bytes, bytearray)) else None   # an in-memory GLB (read_glb's bytes)
    if blob is not None:
        path = "<in-memory GLB>"
        header = blob[:16]
    else:
        with path.open("rb") as f:
            header = f.read(16)
    json_length = struct.unpack_from("<I", header, 12)[0]

    def accessor_data(ai: int, dtype: str, width: int) -> np.ndarray:
        a = js["accessors"][ai]
        bv = js["bufferViews"][a["bufferView"]]
        size = np.dtype(dtype).itemsize
        if (a.get("sparse") or bv.get("buffer", 0) != 0 or
                bv.get("byteStride", width * size) != width * size):
            raise SystemExit(f"{path}: teleport cloud cannot audit skin accessor {ai}")
        offset = 28 + json_length + bv.get("byteOffset", 0) + a.get("byteOffset", 0)
        if blob is not None:
            data = blob[offset:offset + a["count"] * width * size]
        else:
            with path.open("rb") as f:
                f.seek(offset)
                data = f.read(a["count"] * width * size)
        if len(data) != a["count"] * width * size:
            raise SystemExit(f"{path}: short skin accessor {ai}")
        return np.frombuffer(data, dtype=dtype).reshape(a["count"], width)

    def vec4(ai: int, types: dict) -> np.ndarray:
        a = js["accessors"][ai]
        dtype = types.get(a.get("componentType"))
        if a.get("type") != "VEC4" or dtype is None:
            raise SystemExit(f"{path}: teleport cloud cannot audit skin accessor {ai}")
        return accessor_data(ai, dtype, 4)

    ibm = skin.get("inverseBindMatrices")
    if ibm is not None:
        a = js["accessors"][ibm]
        if a.get("type") != "MAT4" or a.get("componentType") != 5126 or a.get("count") != len(joints):
            raise SystemExit(f"{path}: teleport cloud cannot audit inverse bind matrices")
        mats = accessor_data(ibm, "<f4", 16).reshape(-1, 4, 4)
        if not np.all(np.isfinite(mats)) or np.any(np.linalg.svd(mats[:, :3, :3], compute_uv=False)[:, 0] > 1.0001):
            raise SystemExit(f"{path}: teleport cloud inverse bind matrix can expand the collapsed body")

    mesh_nodes = [i for i, n in enumerate(js["nodes"]) if "mesh" in n]
    if not mesh_nodes or any(js["nodes"][i].get("skin") != 0 for i in mesh_nodes):
        raise SystemExit(f"{path}: teleport cloud has an unskinned or foreign-skin mesh")
    for ni in mesh_nodes:
        node = js["nodes"][ni]
        primitives = js["meshes"][node["mesh"]].get("primitives")
        if not primitives:
            raise SystemExit(f"{path}: teleport cloud mesh has no auditable primitives")
        for prim in primitives:
            attrs = prim["attributes"]
            if "POSITION" not in attrs or js["accessors"][attrs["POSITION"]].get("count", 0) <= 0:
                raise SystemExit(f"{path}: teleport cloud mesh has no auditable vertices")
            vertex_count = js["accessors"][attrs["POSITION"]]["count"]
            slots = sorted(int(k.removeprefix("JOINTS_")) for k in attrs if k.startswith("JOINTS_"))
            if not slots or slots != list(range(len(slots))) or {f"WEIGHTS_{s}" for s in slots} != {k for k in attrs if k.startswith("WEIGHTS_")}:
                raise SystemExit(f"{path}: teleport cloud has unaudited joint/weight attributes")
            total = None
            for slot in slots:
                j = vec4(attrs[f"JOINTS_{slot}"], {5121: "u1", 5123: "<u2", 5125: "<u4"})
                w = vec4(attrs[f"WEIGHTS_{slot}"], {5126: "<f4"})
                if j.shape != w.shape or len(j) != vertex_count or np.any(j >= len(joints)) or not np.all(np.isfinite(w)) or np.any(w < 0):
                    raise SystemExit(f"{path}: teleport cloud has invalid skin weights")
                if np.any((w > 1e-6) & ~covered[j]):
                    raise SystemExit(f"{path}: teleport cloud has weighted body vertices outside the Hips subtree")
                total = w.sum(axis=1) if total is None else total + w.sum(axis=1)
            if np.any(np.abs(total - 1.0) > 1e-3):
                raise SystemExit(f"{path}: teleport cloud has vertices with incomplete skin weights")
    parent = {}
    for pi, node in enumerate(js["nodes"]):
        for child in node.get("children", []):
            if child in parent:
                raise SystemExit(f"{path}: teleport cloud node {child} has multiple parents")
            parent[child] = pi
    scale_nodes = set()
    for node in [*joints, *mesh_nodes]:
        while node is not None and node not in scale_nodes:
            scale_nodes.add(node)
            node = parent.get(node)
    if any("matrix" in js["nodes"][node] for node in scale_nodes):
        raise SystemExit(f"{path}: teleport cloud has a matrix transform in the weighted body's scale hierarchy")
    return hips[0], scale_nodes


def glb_clips(path: Path | bytes, def_hashes: dict | None = None, effect_windows: dict | None = None) -> dict:
    """Per Unit_* clip metrics. def_hashes (def_frames()) makes the freeze metric DEF-relative. `path` may be the
    GLB's bytes (move_lowpass_glb measures its in-memory result)."""
    js, acc = read_glb(path)
    hidden_root, scale_nodes, body_audit = None, None, None
    if effect_windows:
        hidden_root, scale_nodes = hidden_body_root(path, js)
    elif any(getattr(f, "absent", False) for segs in (def_hashes or {}).values() for seg in segs for f in seg):
        try:            # only a body-absent hold needs it; a failed audit is that hold's stated reason, not a crash
            hidden_root, scale_nodes = hidden_body_root(path, js)
        except SystemExit as e:
            body_audit = str(e)
    joints = js["skins"][0]["joints"]
    idx = {j: k for k, j in enumerate(joints)}
    names = [js["nodes"][j].get("name", str(j)) for j in joints]
    parent = {}
    for j in joints:
        parent[idx[j]] = None
    for pi, node in enumerate(js["nodes"]):
        for c in node.get("children", []):
            if c in idx and pi in idx:
                parent[idx[c]] = idx[pi]
    rest = {idx[j]: np.array(js["nodes"][j].get("rotation", [0, 0, 0, 1]), float) for j in joints}
    extent = max(1e-6, sum(float(np.linalg.norm(js["nodes"][j].get("translation", [0, 0, 0]))) for j in joints))
    out = {}
    for a in js.get("animations", []):
        if not a["name"].startswith("Unit_"):
            continue
        chans = [(ch, a["samplers"][ch["sampler"]]) for ch in a["channels"]
                 if ch["target"]["path"] == "rotation" and ch["target"]["node"] in idx]
        if not chans:
            continue
        t0 = min(acc(s["input"])[0, 0] for _, s in chans)
        t1 = max(acc(s["input"])[-1, 0] for _, s in chans)
        times = np.linspace(t0, t1, max(2, int(round((t1 - t0) * SAMPLE_HZ)) + 1))
        local = {k: np.tile(rest[k], (len(times), 1)) for k in rest}
        for ch, s in chans:
            kt, kv = acc(s["input"])[:, 0], acc(s["output"])
            for c in range(1, len(kv)):
                if np.dot(kv[c], kv[c - 1]) < 0:
                    kv[c] = -kv[c]
            local[idx[ch["target"]["node"]]] = qnorm(np.stack([np.interp(times, kt, kv[:, c]) for c in range(4)], axis=1))
        out[a["name"]] = clip_metrics(names, parent, local)
        out[a["name"]].update(jitter_metrics(names, local))
        segs = None if def_hashes is None else def_hashes.get(a["name"][len("Unit_"):], [])
        out[a["name"]].update(freeze_metrics(js, acc, a, idx, extent, segs,
                                              (effect_windows or {}).get(a["name"]), hidden_root, scale_nodes,
                                              body_audit))
    return out


def glb_path(arg: str) -> Path:
    p = Path(arg)
    if p.suffix == ".glb":
        return p if p.is_absolute() else ROOT / p
    return ROOT / "artifacts/homm3_def_retarget" / arg / f"{arg}_def_retarget.glb"


# ---------------------------------------------------------------- vanilla OE (read-only)
VANILLA_ROLES = {"04.Fly": "Fly", "01.Walk": "Walk", "22.Idle": "Idle", "14.Attack": "Attack", "20.Damage": "Damage",
                 "05.Fly_Start": "FlyStart", "06.Fly_End": "FlyEnd"}


def euler_zxy_to_q(e):
    x, y, z = np.radians(e[:, 0]) / 2, np.radians(e[:, 1]) / 2, np.radians(e[:, 2]) / 2
    qx = np.stack([np.sin(x), 0 * x, 0 * x, np.cos(x)], 1)
    qy = np.stack([0 * y, np.sin(y), 0 * y, np.cos(y)], 1)
    qz = np.stack([0 * z, 0 * z, np.sin(z), np.cos(z)], 1)
    return qnorm(qmul(qy, qmul(qx, qz)))


def vanilla(out_path: Path) -> dict:
    import UnityPy
    sys.path.insert(0, str(ROOT / "tools/homm3_idle_cadence"))
    from measure_native_idles import BASE_CTRL, continuity_error, decode_streamed, eval_streamed  # noqa: E402
    env = UnityPy.load(str(GAME / "HeroesOldenEra_Data/resources.assets"))
    byid = {o.path_id: o for o in env.objects}
    anim_go = {}
    for o in env.objects:
        if o.type.name == "Animator":
            a = o.read_typetree()
            anim_go.setdefault(a["m_Controller"]["m_PathID"], []).append(a["m_GameObject"]["m_PathID"])

    def hierarchy(go_id):
        go = byid[go_id].read_typetree()
        tr_id = next(c["component"]["m_PathID"] for c in go["m_Component"] if byid[c["component"]["m_PathID"]].type.name == "Transform")
        names, parent, rest, paths = [], {}, {}, {}

        def walk(tid, par, path):
            t = byid[tid].read_typetree()
            for c in t["m_Children"]:
                ct = byid[c["m_PathID"]].read_typetree()
                nm = byid[ct["m_GameObject"]["m_PathID"]].peek_name()
                i = len(names)
                names.append(nm)
                parent[i] = par
                q = ct["m_LocalRotation"]
                rest[i] = np.array([q["x"], q["y"], q["z"], q["w"]], float)
                p = nm if not path else path + "/" + nm
                paths[zlib.crc32(p.encode("utf-8"))] = i
                walk(c["m_PathID"], i, p)
        walk(tr_id, None, "")
        return names, parent, rest, paths

    def decode(tt, paths, n_bones, rest):
        mc = tt["m_MuscleClip"]
        start, stop = float(mc["m_StartTime"]), float(mc["m_StopTime"])
        data = mc["m_Clip"]["data"]
        sc, dc, cc = data["m_StreamedClip"], data["m_DenseClip"], data["m_ConstantClip"]["data"]
        n_s, n_d = int(sc["curveCount"]), int(dc["m_CurveCount"])
        times = np.linspace(start, stop, max(2, int(round((stop - start) * SAMPLE_HZ)) + 1))
        streamed = decode_streamed(sc["data"]) if sc["data"] else {}
        if max((continuity_error(k) for k in streamed.values()), default=0.0) > 0.05:
            raise ValueError("streamed decode discontinuity")
        dense = np.asarray(dc["m_SampleArray"], float)
        if n_d:
            dense = dense.reshape(int(dc["m_FrameCount"]), n_d)
            dt = float(dc["m_BeginTime"]) + np.arange(dense.shape[0]) / float(dc["m_SampleRate"])

        def curve(i):
            if i < n_s:
                k = streamed.get(i)
                return eval_streamed(k, times) if k else np.zeros(len(times))
            i -= n_s
            if i < n_d:
                return np.interp(times, dt, dense[:, i])
            return np.full(len(times), float(cc[i - n_d]))
        local = {i: np.tile(rest[i], (len(times), 1)) for i in range(n_bones)}
        ci, bound, missed = 0, 0, 0
        for b in tt["m_ClipBindingConstant"]["genericBindings"]:
            if b["typeID"] != 4:
                ci += 1
                continue
            size = 4 if b["attribute"] == 2 else 3
            i = paths.get(int(b["path"]))
            if b["attribute"] in (2, 4):
                if i is None:
                    missed += 1
                else:
                    v = np.stack([curve(ci + k) for k in range(size)], 1)
                    local[i] = qnorm(v) if size == 4 else euler_zxy_to_q(v)
                    bound += 1
            ci += size
        return local, round(stop - start, 3), bound, missed

    units = []
    for o in env.objects:
        if o.type.name != "AnimatorOverrideController":
            continue
        tt = o.read_typetree()
        b = byid.get(tt["m_Controller"]["m_PathID"])
        if b is None or b.peek_name() != BASE_CTRL:
            continue
        clips = {}
        for c in tt["m_Clips"]:
            a, ov = byid.get(c["m_OriginalClip"]["m_PathID"]), byid.get(c["m_OverrideClip"]["m_PathID"])
            if a is not None and ov is not None and a.peek_name() in VANILLA_ROLES:
                clips[VANILLA_ROLES[a.peek_name()]] = ov
        gos = anim_go.get(o.path_id, [])
        if not gos:
            continue
        names, parent, rest, paths = hierarchy(gos[0])
        row = {"controller": o.peek_name(), "prefab": byid[gos[0]].peek_name(),
               "wingBones": sum(region(n) == "wing" for n in names), "clips": {}}
        for role, ov in sorted(clips.items()):
            try:
                local, length, bound, missed = decode(ov.read_typetree(), paths, len(names), rest)
            except Exception as e:  # noqa: BLE001 (one clip's decode fault is recorded, not hidden)
                row["clips"][role] = {"error": repr(e)}
                continue
            m = clip_metrics(names, parent, local)
            m.update(jitter_metrics(names, local))
            row["clips"][role] = {"clip": ov.peek_name(), "lengthS": length, "boundRotations": bound,
                                  "unboundRotations": missed, **m}
        units.append(row)
        print(row["controller"], row["wingBones"], {k: (v.get("wingSwing"), v.get("bodyRot")) for k, v in row["clips"].items()}, flush=True)
    rep = {"schema": "homm3_flyer_articulation.vanilla.v1", "source": str(GAME / "HeroesOldenEra_Data/resources.assets"),
           "sampleHz": SAMPLE_HZ, "units": units}
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(rep, indent=1) + "\n", encoding="utf-8")
    return rep


def main() -> int:
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return 2
    if args[0] == "vanilla":
        vanilla(ROOT / args[args.index("--out") + 1])
        return 0
    jo = None
    if "--json" in args:
        i = args.index("--json")
        jo = args[i + 1]
        args = args[:i] + args[i + 2:]
    res = {}
    for u in args[1:]:
        res[u] = glb_clips(glb_path(u))
        for c, m in res[u].items():
            print(f"{u:24s} {c:16s} {m}", flush=True)
    if jo:
        Path(jo).write_text(json.dumps(res, indent=1) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
