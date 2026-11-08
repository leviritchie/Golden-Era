"""Lengthen the walk stride of a DEF-retarget GLB so its planted feet keep up with OE's ground speed.

    python tools/homm3_def_retarget_delivery/stride_match_glb.py measure <unit> [--glb P]
    python tools/homm3_def_retarget_delivery/stride_match_glb.py apply <unit> [--glb P] [--out P] [--mode plant|gain]
    python tools/homm3_def_retarget_delivery/stride_match_glb.py check <glb...> [--max-slip 0.686]

Why: OE translates a battle unit at its view config's `moveSpeed` (world units / s) while it plays the Move clip
in place at 0.8 x battleSpeed (docs/homm3_stride_match.md). A HoMM3 walk retargeted from DEF frames sweeps its
feet backward far slower than that, so the feet slide forward over the ground: the unit shuffles. The user wants
longer strides, not slower units, so moveSpeed stays and the clip changes. The speed itself is a normalization decision:
a game sid adopted in custom_factions/unit_move_speed_normalization.json is matched to its class's target (the mean
moveSpeed of similar vanilla OE units, which the Core overlay also writes into its view row); any other unit to its
installed Core view row. The stamp records moveSpeedSource (user, 2026-09-28: normalize speed, adjust stride).

Transform (Unit_Move only; every other clip, the rest mesh, the skin and the morph keys are untouched):
  plant (default, plant_transform): every grounded foot keeps the source's step phase and gets a stance that sweeps
    backward at exactly ground speed on its own floor, centred under its hip, and a smooth lifted swing; legs are
    re-solved by two-bone IK, the pelvis sinks where a leg cannot reach (<= maxDrop x leg). A stance sweep is capped
    by maxExcursion x height and by the leg's reach; the stance is shortened first (to 0.30 of the cycle) and only
    then is the whole clip sped up, by at most maxCadence (1.6): a capped blend of longer stride and faster rate.
    Clearance: no planted chain goes below the Idle floor (its whole limb while it swings, its sole while it stands);
    a key that would is raised by its deficit and re-solved on the pose as written, and a limb still under after
    CLEARANCE_ITERS passes is refused (ground_glb would otherwise lift the loop and float the plant, its P2 refusal).
  gain (comparison only): scale each ankle's fore-aft offset by the stride ratio. It lengthens the stride but
    keeps the DEF foot sliding while low, so slip barely moves (swordsman 0.885 -> 0.866) or worsens (pikeman).
Fliers: whether a unit flies is a HoMM3 fact read from reference/homm3_fliers.json (build_homm3_flier_table.py:
the creature animating the unit's DEF has a FLYING bonus), never inferred from the Move. A flier is not stride
matched (`measure` reports it, `apply` exits 3); a unit missing from the table or unresolved there is refused.
A flier's normalized speed (a moveType "fly" class) is a speed decision only: its Move has no planted contact and OE
plays every Move clip at 0.8 x battleSpeed whatever moveSpeed is, so there is no wing cadence to match.
Legs: a walker's dedicated leg chains (humanoid UpLeg pair, Q*/HFL*/FL* mount or quadruped sets) are its walking
legs by construction, each planted on its own floor; a humanoid rig's arms count as front legs only beside UpLeg
legs and only where they reach the legs' floor band. A four-leg mount set (HFL*, FL*, Horse*) replaces the rider's humanoid
chains; Q* front legs join a humanoid rig's UpLeg hind legs (centaur).
A walker whose body has no legs at all (serpent, naga tail, floating elemental) is not inferred either: its unit
config must say so with "strideExempt": "<reason>", and the rig must then have no leg chain (`apply` exits 3).
A legged body that never touches the ground (the fire elemental floats) is exempted the same way, and its config
also names the leg chains it acknowledges ("strideExemptLegs": [...]), which must equal chains_of on the rig.
Refuses: a GLB already stride-matched, a walker whose rig has no leg chain and no strideExempt (chains_of must be
taught that rig), an exempt unit whose rig has legs, scaled chain bones, and a result whose slip got worse.
Per-unit smoothing (plant only), unit config "strideMatch": {"highHarmonicKeep": k, "reason": "<why>"} with 0 < k < 1:
every rewritten Move channel's spectrum above flyer_articulation.JITTER_CUTOFF_HZ is scaled by k before the keys are
written. A short Move sped up to the cadence cap puts a planted gait's own step harmonics above the articulation
gate's jitter cutoff (the nomad: a 0.26 s cycle, fundamental 3.8 Hz); k trades stride share for smoothness, and the
shortfall shows in residualRatio and slip, never in a loosened gate. The stamp records k, its reason, and
strideShareBelowFull. Any other key, a k outside (0, 1) or a missing reason is refused.
Per-unit pelvis drop (plant only), "strideMatch": {"maxDrop": d, "reason": "<why>"} with DEFAULT_MAX_DROP < d <= 0.35
(may be combined with highHarmonicKeep under one reason): the pelvis may sink up to d x leg length instead of 0.15.
A walker whose source Move keeps its legs near straight (the dwarf: legs 0.365 H, hip about one leg length above
the planted ankle) has no reach at the default drop, so its sweep stays at the source's and the cadence cap runs
out (dwarf residual ratio 1.82). The stamp's maxDrop is the effective value; an explicit --max-drop that disagrees
with the config is refused.
Body hold (plant only), "strideMatch": {"pelvisHold": p, "reason": "<why>"} with 0 <= p <= 0.04: the plant's pelvis
drop may sink the body at most p x body height below its source (fitted) keys. Reach, stance and the cadence are planned
exactly as without it (maxDrop, the unaided cadence), so stride and step rate stay the stride lane's; a leg that cannot
reach its planned target from the held pelvis straightens (two-bone reach clamp) at the stance's ends. For a mount whose
DEF carries the body level and high through the trot (h3_champion: the default drop sank the horse ~0.042 H).
The report records pelvisHoldOverHeight and the drop the hold removed.
Mount trot (plant only), "strideMatch": {"trotPhase": q, "reason": "<why>"} with 0 <= q < 1: the four horse legs
(HFL HFR HHL HHR, all planted) step as a diagonal trot read from the DEF Move: HFL and HHR start their stance at cycle
phase q, HFR and HHL at q + 0.5, each keeping its own stance fraction. Without it each leg keeps the source's phase,
which a fitted or procedural Move can leave out of pair (h3_champion: HFL's stance undetectable, read from its height).
Declared forelegs (plant only), "strideMatch": {"foreLegs": ["LeftArm", "RightArm"], "reason": "<why>"}: arm chains a
quadruped body on the humanoid rig walks on are planted from the first pass. grounded_chains judges an arm by its hand
joint, which on a hoofed foreleg hangs well above the hoof (h3_mighty_gorgon: 0.16-0.18 H over the Idle floor while
the hoof touches it), so the arm is never planted and its hoof dips under the planted hind soles (ground_glb P2).
A declared foreleg that is not in the floor band after the plant is refused like any planted chain that left it.
Leg drive (plant only), "strideMatch": {"legDeltas": "tools/homm3_def_retarget_delivery/stride_leg_deltas/<unit>.json"}:
after the plant, each named leg bone's Move keys turn about the body's lateral axis by a per-DEF-frame table (solved
from the unit's DEF keypoint tracks), DEF frame i at the board's clip start + i x cycle / n (move_clip_start, the
authenticity board's rule, so the turns cannot land a key off). The table's swingPower weights the turns by each chain's
swing phase from the plant (0 in stance), so planted hooves keep the plant's contact. Slip is re-measured with the
turns and refused like any other worse slip; the stamp records slip before/after the turns and the table sha.
Reported, not refused: a Move floor above the Idle floor (floorLiftFlag) and a leg that never comes down to the
lowest leg's floor (legFloorGap, x body height).
Stamps asset.extras.homm3DefRetargetDeliveryStrideMatch {mode, ratio, cadence, before/after slip, sourceGlbSha256}.
`check` re-measures a stamped GLB and fails above the vanilla walks' p75 slip or outside the stride ratio band.

World scale is the battle hex fit (battleHeightHexes x battleWorldHeightPerHex / skinned Idle-t0 height, the
rule of Homm3ImportVisuals.FitSkinnedBattleMesh); moveSpeed is move_speed_source (normalized target or Core view).
Proof tier: generated artifact. Nothing here builds a bundle or touches the game.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import struct
import sys
import zipfile
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.append(str(ROOT / "tools"))   # validate_unit_move_speed_normalization_contract (move_speed_source)
from gate_exceptions import stride_exceptions, stride_faults_after  # noqa: E402,F401  (freeze_slice's stride gate reads these)
import stride_gait as G  # noqa: E402

STAMP = "homm3DefRetargetDeliveryStrideMatch"
MOVE = "Unit_Move"
IDLE = "Unit_Idle"
GOLDEN = Path("V:/SteamLibrary/steamapps/common/Heroes of Might and Magic Olden Era - Golden Era")
CORE_ZIP = GOLDEN / "HeroesOldenEra_Data/StreamingAssets/Core.zip"
IMPORT = ROOT / "Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/homm3_import.json"
FORWARD = np.array([0.0, 0.0, 1.0])      # facing contract: Unit_Idle frame 0 faces glTF +Z
SAMPLES = 240                             # dense samples per Move cycle for measurement
DEFAULT_MAX_GAIN = 8.0                    # absolute gain cap (the excursion cap usually binds first)
DEFAULT_MAX_EXCURSION = 0.75              # foot fore-aft excursion / body height (vanilla humanoid p90 is 0.76)
DEFAULT_LIFT = 0.04                       # swing clearance arc / body height for a foot that shuffles
DEFAULT_MAX_DROP = 0.15                   # fraction of the chain's full length the pelvis may sink
GROUND_BAND = 0.06                        # chain is grounded if its lowest sample is within this x body of the floor
UPI = G.UP
AIRBORNE_LIFT = 0.05                      # a walker's Move floor this x body above its Idle floor is reported
FLIERS = HERE / "reference" / "homm3_fliers.json"         # build_homm3_flier_table.py
NATIVE = HERE / "reference" / "native_walk_stride.json"  # vanilla reference (measure_native_walk_stride.py)


def native_reference() -> dict:
    d = json.loads(NATIVE.read_text(encoding="utf-8"))
    return {"effectiveBattleSpeed": float(d["effectiveBattleSpeed"]), "slipP75": float(d["calibratedP75SlipRatio"]),
            "ratioBand": (min(u["calibrated"]["requiredOverActual"] for u in d["units"].values()),
                          max(u["calibrated"]["requiredOverActual"] for u in d["units"].values()))}


REF = native_reference()
PLAYBACK = G.MOVE_STATE_SPEED * REF["effectiveBattleSpeed"]
DEFAULT_MAX_SLIP = REF["slipP75"]         # check: pooled slip ratio no worse than the vanilla walks' 75th percentile
MAX_RATIO = 1.4                           # check: required/actual stride inside the vanilla band (0.78 .. 1.34)

CHAINS = (("LeftUpLeg", "LeftLeg", "LeftFoot", ("LeftToeBase",)),
          ("RightUpLeg", "RightLeg", "RightFoot", ("RightToeBase",)),
          ("LeftArm", "LeftForeArm", "LeftHand", ()),      # a humanoid-rigged quadruped's front legs; dropped when
          ("RightArm", "RightForeArm", "RightHand", ()))   # the rig has a dedicated leg set (a rider's arms are not legs)
ARM_CHAINS = ("LeftArm", "RightArm")
MOUNT_SETS = {"HFL", "HFR", "HHL", "HHR", "FL", "FR", "RL", "RR", "HorseLF", "HorseRF", "HorseLH", "HorseRH"}


STRIDE_OPTION_KEYS = {"highHarmonicKeep", "maxDrop", "pelvisHold", "trotPhase", "foreLegs", "swingLift", "swingCurl",
                      "legDeltas", "reason"}
STRIDE_KNOBS = ("highHarmonicKeep", "maxDrop", "pelvisHold", "trotPhase", "foreLegs", "swingLift", "swingCurl",
                "legDeltas")
LEG_DELTAS_DIR = "tools/homm3_def_retarget_delivery/stride_leg_deltas"   # strideMatch.legDeltas tables live here
LEG_DELTA_MAX = 180.0                          # strideMatch.legDeltas: most lateral-axis turn (deg) per DEF frame
MAX_DROP_RANGE = (DEFAULT_MAX_DROP, 0.35)      # strideMatch.maxDrop: above the default, at most this
PELVIS_HOLD_MAX = 0.04                         # strideMatch.pelvisHold: most body sink (x height) it may allow
TROT_DIAGONALS = (("HFL", "HHR"), ("HFR", "HHL"))   # strideMatch.trotPhase: the pair at q, the pair at q + 0.5
SWING_LIFT_RANGE = (0.04, 0.20)                # strideMatch.swingLift: swing hoof/foot arc height (x body height)
SWING_CURL_MAX = 120.0                         # strideMatch.swingCurl: most fetlock/ankle curl (deg) at mid swing


def unit_prop_bone(unit: str) -> str | None:
    """The unit config's propFloor.bone (None when the unit has no propFloor): prop_floor_glb.py owns that prop."""
    cfg = json.loads((ROOT / "tools/homm3_def_retarget/units" / f"{unit}.json").read_text(encoding="utf-8"))
    pf = cfg.get("propFloor")
    if pf is None:
        return None
    if not (isinstance(pf, dict) and isinstance(pf.get("bone"), str) and pf["bone"]):
        raise SystemExit(f"{unit}: propFloor needs a bone name")
    return pf["bone"]


def unit_stride_options(unit: str) -> dict:
    """The unit config's "strideMatch" options ({} when absent); fail closed on anything but a documented knob.
    Knobs: highHarmonicKeep in (0, 1); maxDrop in (DEFAULT_MAX_DROP, MAX_DROP_RANGE[1]]; pelvisHold in
    [0, PELVIS_HOLD_MAX]; trotPhase in [0, 1); foreLegs a non-empty list of distinct ARM_CHAINS names. At least one knob
    and a non-empty reason are required."""
    cfg = json.loads((ROOT / "tools/homm3_def_retarget/units" / f"{unit}.json").read_text(encoding="utf-8"))
    opt = cfg.get("strideMatch")
    if opt is None:
        return {}
    if not isinstance(opt, dict) or set(opt) - STRIDE_OPTION_KEYS or not any(k in opt for k in STRIDE_KNOBS):
        raise SystemExit(f"{unit}: strideMatch must be {{highHarmonicKeep / maxDrop / foreLegs, reason}}, got {opt}")
    if not (isinstance(opt.get("reason"), str) and opt["reason"].strip()):
        raise SystemExit(f"{unit}: strideMatch needs a non-empty reason")
    out = {"reason": opt["reason"]}
    if "highHarmonicKeep" in opt:
        k = opt["highHarmonicKeep"]
        if isinstance(k, bool) or not isinstance(k, (int, float)) or not 0.0 < float(k) < 1.0:
            raise SystemExit(f"{unit}: strideMatch.highHarmonicKeep must be in (0, 1), got {k}")
        out["highHarmonicKeep"] = float(k)
    if "maxDrop" in opt:
        d = opt["maxDrop"]
        if isinstance(d, bool) or not isinstance(d, (int, float)) or not MAX_DROP_RANGE[0] < float(d) <= MAX_DROP_RANGE[1]:
            raise SystemExit(f"{unit}: strideMatch.maxDrop must be in ({MAX_DROP_RANGE[0]}, {MAX_DROP_RANGE[1]}], got {d}")
        out["maxDrop"] = float(d)
    if "pelvisHold" in opt:
        v = opt["pelvisHold"]
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not 0.0 <= float(v) <= PELVIS_HOLD_MAX:
            raise SystemExit(f"{unit}: strideMatch.pelvisHold must be in [0, {PELVIS_HOLD_MAX}], got {v}")
        out["pelvisHold"] = float(v)
    if "trotPhase" in opt:
        v = opt["trotPhase"]
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not 0.0 <= float(v) < 1.0:
            raise SystemExit(f"{unit}: strideMatch.trotPhase must be in [0, 1), got {v}")
        out["trotPhase"] = float(v)
    if "foreLegs" in opt:
        fl = opt["foreLegs"]
        if not (isinstance(fl, list) and fl and len(set(fl)) == len(fl) and set(fl) <= set(ARM_CHAINS)):
            raise SystemExit(f"{unit}: strideMatch.foreLegs must be a non-empty list of distinct {list(ARM_CHAINS)}, "
                             f"got {fl}")
        out["foreLegs"] = sorted(fl)
    if "swingLift" in opt:
        v = opt["swingLift"]
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not SWING_LIFT_RANGE[0] < float(v) <= SWING_LIFT_RANGE[1]:
            raise SystemExit(f"{unit}: strideMatch.swingLift must be in ({SWING_LIFT_RANGE[0]}, {SWING_LIFT_RANGE[1]}], got {v}")
        out["swingLift"] = float(v)
    if "swingCurl" in opt:
        v = opt["swingCurl"]
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not 0.0 < float(v) <= SWING_CURL_MAX:
            raise SystemExit(f"{unit}: strideMatch.swingCurl must be in (0, {SWING_CURL_MAX}], got {v}")
        out["swingCurl"] = float(v)
    if "legDeltas" in opt:
        v = opt["legDeltas"]
        if not (isinstance(v, str) and v.startswith(LEG_DELTAS_DIR + "/") and v.endswith(".json") and ".." not in v):
            raise SystemExit(f"{unit}: strideMatch.legDeltas must be a {LEG_DELTAS_DIR}/<name>.json path, got {v}")
        out["legDeltas"] = v
    return out


def load_leg_deltas(rel: str) -> tuple[dict, str]:
    """A strideMatch.legDeltas table: {"deltasDeg": {bone: [deg per DEF Move frame, n >= 2]}, "swingPower": p?}; every
    bone the same frame count, finite, within LEG_DELTA_MAX. Returns (deltas, sha256 of the file, swingPower)."""
    raw = (ROOT / rel).read_bytes()
    tab = json.loads(raw)
    d = tab.get("deltasDeg") if isinstance(tab, dict) else None
    if not (isinstance(d, dict) and d):
        raise SystemExit(f"{rel}: legDeltas table needs a non-empty deltasDeg map")
    ns = set()
    for b, v in d.items():
        a = np.asarray(v, float)
        if a.ndim != 1 or len(a) < 2 or not np.all(np.isfinite(a)) or np.abs(a).max() > LEG_DELTA_MAX:
            raise SystemExit(f"{rel}: deltasDeg[{b}] must be >= 2 finite degrees within +-{LEG_DELTA_MAX}")
        ns.add(len(a))
    if len(ns) != 1:
        raise SystemExit(f"{rel}: every deltasDeg row needs the same DEF frame count, got {sorted(ns)}")
    sp = tab.get("swingPower")
    if sp is not None and (isinstance(sp, bool) or not isinstance(sp, (int, float)) or not 0.0 < float(sp) <= 4.0):
        raise SystemExit(f"{rel}: swingPower must be in (0, 4] or absent, got {sp}")
    return d, hashlib.sha256(raw).hexdigest(), None if sp is None else float(sp)


def move_clip_start(g: Glb, name: str = None) -> tuple[float, float]:
    """(start, end) of a clip by the authenticity board's rule (tools/homm3_authenticity/gltf_scene.clip_range): start
    is the most common first-key time over its channels (a stage that prepends a 0 s key to a few channels does not
    move the DEF grid), end the last key of any channel. legDeltas places DEF frame i at start + i * (end-start) / n,
    so the deltas land on the frames the board compares against (an off-by-one-key start shakes the loop seam)."""
    a = g.anim(name or MOVE)
    firsts = [round(float(g.read(a["samplers"][c["sampler"]]["input"])[0, 0]), 5) for c in a["channels"]]
    vals, cnt = np.unique(firsts, return_counts=True)
    end = max(float(g.read(s["input"])[-1, 0]) for s in a["samplers"])
    return float(vals[np.argmax(cnt)]), end


def apply_leg_deltas(g: Glb, deltas: dict, forward, plant: dict | None = None, swing_power: float | None = None) -> dict:
    """strideMatch.legDeltas, after the plant (which rewrites the leg chains, so earlier keys cannot reach them):
    post-multiply each named bone's Move rotation keys by a turn about the body's lateral axis (forward x up, in the
    bone's rest frame), the per-DEF-frame degrees interpolated circularly over the loop. In place; returns a report.
    swing_power (table "swingPower"): weight each bone's turn by its chain's swing phase from the plant report
    (`plant[<chain>]` phase0/stanceFraction on phase = t / clip end, the plant's own clock): 0 through the stance,
    sin(pi wf) ** swing_power in the swing, so the planted hoof keeps the plant's contact (no skate) and the DEF leg
    shape is carried where the hoof is in the air. None turns every key (skates a planted gait)."""
    from scipy.spatial.transform import Rotation as Rot
    a = g.anim(MOVE)
    idx = {n: i for i, n in enumerate(g.names)}
    missing = sorted(set(deltas) - set(idx))
    if missing:
        raise SystemExit(f"strideMatch.legDeltas: bones {missing} are not in the rig")
    rest = g.world({i: [np.array([g.rest(i)[0]]), np.array([g.rest(i)[1]]), np.array([g.rest(i)[2]])]
                    for i in range(len(g.nodes))})
    fwd = np.asarray(forward, float).copy(); fwd[1] = 0.0; fwd /= np.linalg.norm(fwd)
    lat = np.cross(fwd, [0.0, 1.0, 0.0]); lat /= np.linalg.norm(lat)
    t0, t1 = move_clip_start(g)
    dur = t1 - t0
    targets = {}
    for bn, dl in deltas.items():
        j = idx[bn]
        chain = bn.rstrip("0123456789")
        Wr = rest[j][0, :3, :3]; Wr = Wr / np.linalg.norm(Wr, axis=0)
        ax = Wr.T @ lat; ax /= np.linalg.norm(ax)
        ch = next((c for c in a["channels"] if c["target"]["node"] == j and c["target"]["path"] == "rotation"), None)
        grid = g.key_grid(MOVE) if ch is None else g.read(a["samplers"][ch["sampler"]]["input"])[:, 0]
        q = g.sample_local(MOVE, grid)[j][1]
        d = np.asarray(dl, float); n = len(d); p = (grid - t0) / dur * n
        k = np.floor(p).astype(int); u = p - k
        dd = d[k % n] * (1 - u) + d[(k + 1) % n] * u
        if swing_power is not None:
            pr = (plant or {}).get(chain)
            if not (isinstance(pr, dict) and "phase0" in pr and "stanceFraction" in pr):
                raise SystemExit(f"strideMatch.legDeltas: swingPower needs the plant's phase of chain {chain} ({bn})")
            beta = float(pr["stanceFraction"]); uu = (grid / t1 - float(pr["phase0"])) % 1.0
            wf = np.where(uu < beta, 0.0, (uu - beta) / (1.0 - beta))
            dd = dd * np.where(uu < beta, 0.0, np.sin(np.pi * wf) ** swing_power)
        targets[(j, "rotation")] = (grid, (Rot.from_quat(q) * Rot.from_rotvec(ax[None, :] * np.radians(dd)[:, None])).as_quat())
    for key, (grid, v) in targets.items():
        write_channels(g, a, grid, {key: v})
    return {"bones": sorted(deltas), "swingPower": swing_power, "frames": len(next(iter(deltas.values()))), "clipStart": round(t0, 5),
            "clipEnd": round(t1, 5), "lateralAxis": [round(float(x), 5) for x in lat]}


def keep_low_harmonics(targets: dict, grid: np.ndarray, clip_seconds: float, keep: float) -> None:
    """Scale each periodic channel's spectrum above the articulation jitter cutoff by `keep` (in place).
    The grid's last key repeats the first; rotations are made sign-continuous first and renormalised after."""
    from flyer_articulation import JITTER_CUTOFF_HZ
    m = len(grid) - 1
    hz = np.arange(m // 2 + 1) / clip_seconds
    for key, arr in list(targets.items()):
        v = np.array(arr, float)
        if key[1] == "rotation":
            for i in range(1, len(v)):
                if np.dot(v[i], v[i - 1]) < 0:
                    v[i] = -v[i]
        sp = np.fft.rfft(v[:m], axis=0)
        sp[hz > JITTER_CUTOFF_HZ] *= keep
        w = np.fft.irfft(sp, n=m, axis=0)
        w = np.vstack([w, w[:1]])
        if key[1] == "rotation":
            w /= np.linalg.norm(w, axis=1, keepdims=True)
        targets[key] = w


def unit_stride_exempt(unit: str) -> str | None:
    """A legless walker's declared reason (unit config "strideExempt"); None for a legged unit."""
    cfg = json.loads((ROOT / "tools/homm3_def_retarget/units" / f"{unit}.json").read_text(encoding="utf-8"))
    why = cfg.get("strideExempt")
    if why is not None and not (isinstance(why, str) and why.strip()):
        raise SystemExit(f"{unit}: strideExempt must be a non-empty reason string")
    if why and unit_flier(unit):
        raise SystemExit(f"{unit}: strideExempt on a HoMM3 flier: fliers are never stride matched, drop the exemption")
    return why


def check_exempt_rig(unit: str, g: "Glb", why: str) -> list[str]:
    """An exempt unit's rig: no leg chain, or exactly the chains its config acknowledges in strideExemptLegs."""
    cfg = json.loads((ROOT / "tools/homm3_def_retarget/units" / f"{unit}.json").read_text(encoding="utf-8"))
    legs = [c["name"] for c in chains_of(g)]
    ack = cfg.get("strideExemptLegs", [])
    if sorted(legs) != sorted(ack):
        raise SystemExit(f"{unit}: strideExempt ({why}) but the rig's leg chains {legs} are not the acknowledged "
                         f"strideExemptLegs {ack}")
    return legs


def unit_flier(unit: str) -> bool:
    """HoMM3 flier class from the committed table; fail closed on a missing or unresolved unit."""
    t = json.loads(FLIERS.read_text(encoding="utf-8"))["units"]
    rec = t.get(unit)
    if rec is None or rec.get("flier") is None:
        raise SystemExit(f"{unit}: not classified in {FLIERS.name} ({(rec or {}).get('evidence', 'missing')}); "
                         "rerun build_homm3_flier_table.py or settle it in its MANUAL table")
    return bool(rec["flier"])


# --------------------------------------------------------------------------------------------------------- GLB I/O
class Glb:
    def __init__(self, data: bytes):
        self.raw = bytes(data)
        jl = struct.unpack_from("<I", data, 12)[0]
        self.json = json.loads(data[20:20 + jl])
        bl = struct.unpack_from("<I", data, 20 + jl)[0]
        self.bin = bytearray(data[20 + jl + 8:20 + jl + 8 + bl])
        self.nodes = self.json["nodes"]
        self.names = [n.get("name") for n in self.nodes]
        self.parent = {c: i for i, n in enumerate(self.nodes) for c in n.get("children", [])}

    @classmethod
    def load(cls, p: Path) -> "Glb":
        return cls(Path(p).read_bytes())

    def to_bytes(self) -> bytes:
        js = json.dumps(self.json, separators=(",", ":")).encode("utf-8")
        js += b" " * ((4 - len(js) % 4) % 4)
        bn = bytes(self.bin) + b"\0" * ((4 - len(self.bin) % 4) % 4)
        self.json["buffers"][0]["byteLength"] = len(bn)
        js = json.dumps(self.json, separators=(",", ":")).encode("utf-8")
        js += b" " * ((4 - len(js) % 4) % 4)
        out = struct.pack("<III", 0x46546C67, 2, 12 + 8 + len(js) + 8 + len(bn))
        return out + struct.pack("<II", len(js), 0x4E4F534A) + js + struct.pack("<II", len(bn), 0x004E4942) + bn

    def read(self, ai: int) -> np.ndarray:
        a = self.json["accessors"][ai]
        if "sparse" in a:
            raise ValueError(f"accessor {ai} is sparse")
        bv = self.json["bufferViews"][a["bufferView"]]
        w = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}[a["type"]]
        dt = {5126: "<f4", 5123: "<u2", 5121: "u1", 5125: "<u4"}[a["componentType"]]
        size = np.dtype(dt).itemsize
        stride = bv.get("byteStride", size * w)
        off = bv.get("byteOffset", 0) + a.get("byteOffset", 0)
        if stride == size * w:
            arr = np.frombuffer(self.bin, dtype=dt, count=a["count"] * w, offset=off).reshape(a["count"], w)
        else:
            arr = np.stack([np.frombuffer(self.bin, dtype=dt, count=w, offset=off + i * stride)
                            for i in range(a["count"])])
        arr = arr.astype(np.float64)
        if a.get("normalized") and a["componentType"] != 5126:
            arr = arr / {5121: 255.0, 5123: 65535.0}[a["componentType"]]
        return arr

    def append_accessor(self, arr: np.ndarray, typ: str) -> int:
        arr = np.ascontiguousarray(arr, dtype="<f4")
        while len(self.bin) % 4:
            self.bin.append(0)
        off = len(self.bin)
        self.bin += arr.tobytes()
        self.json["bufferViews"].append({"buffer": 0, "byteOffset": off, "byteLength": arr.nbytes})
        acc = {"bufferView": len(self.json["bufferViews"]) - 1, "componentType": 5126, "count": int(arr.shape[0]),
               "type": typ}
        if typ == "SCALAR":
            acc["min"] = [float(arr.min())]; acc["max"] = [float(arr.max())]
        self.json["accessors"].append(acc)
        return len(self.json["accessors"]) - 1

    def anim(self, name: str) -> dict:
        for a in self.json.get("animations", []):
            if a.get("name") == name:
                return a
        raise KeyError(name)

    def rest(self, i: int):
        n = self.nodes[i]
        if "matrix" in n:
            raise ValueError(f"node {n.get('name')} uses a matrix")
        return (np.array(n.get("translation", [0, 0, 0]), float), np.array(n.get("rotation", [0, 0, 0, 1]), float),
                np.array(n.get("scale", [1, 1, 1]), float))

    def key_grid(self, name: str) -> np.ndarray:
        a = self.anim(name)
        ts = set()
        for s in a["samplers"]:
            if s.get("interpolation", "LINEAR") == "LINEAR":
                ts.update(np.round(self.read(s["input"])[:, 0], 6).tolist())
        return np.array(sorted(ts))

    def clip_end(self, name: str) -> float:
        a = self.anim(name)
        return max(float(self.read(s["input"]).max()) for s in a["samplers"])

    def sample_local(self, name: str, times: np.ndarray) -> dict[int, list[np.ndarray]]:
        """Local TRS of every node at times (Unity clamps before the first / after the last key)."""
        n = len(times)
        out = {}
        for i in range(len(self.nodes)):
            t, r, s = self.rest(i)
            out[i] = [np.tile(t, (n, 1)), np.tile(r, (n, 1)), np.tile(s, (n, 1))]
        a = self.anim(name)
        slot = {"translation": 0, "rotation": 1, "scale": 2}
        for ch in a["channels"]:
            path = ch["target"]["path"]
            if path not in slot:
                continue
            smp = a["samplers"][ch["sampler"]]
            kt = self.read(smp["input"])[:, 0]
            kv = self.read(smp["output"])
            interp = smp.get("interpolation", "LINEAR")
            if interp == "CUBICSPLINE":
                raise ValueError("CUBICSPLINE keys are not supported")
            tc = np.clip(times, kt[0], kt[-1])
            j = np.clip(np.searchsorted(kt, tc, side="right") - 1, 0, len(kt) - 1)
            j1 = np.minimum(j + 1, len(kt) - 1)
            span = np.where(j1 > j, kt[j1] - kt[j], 1.0)
            u = np.where(j1 > j, (tc - kt[j]) / span, 0.0)
            if interp == "STEP":
                v = kv[j]
            elif path == "rotation":
                v = G.qslerp(kv[j], kv[j1], u)
            else:
                v = kv[j] + (kv[j1] - kv[j]) * u[:, None]
            out[ch["target"]["node"]][slot[path]] = v
        return out

    def world(self, local: dict[int, list[np.ndarray]]):
        """World position, rotation (xyzw) and 4x4 matrices of every node."""
        mats: dict[int, np.ndarray] = {}

        def m(i):
            if i in mats:
                return mats[i]
            t, r, s = local[i]
            mm = np.zeros((len(t), 4, 4))
            mm[:, :3, :3] = G.qmat(r) * s[:, None, :]
            mm[:, :3, 3] = t
            mm[:, 3, 3] = 1.0
            p = self.parent.get(i)
            mats[i] = mm if p is None else m(p) @ mm
            return mats[i]

        for i in range(len(self.nodes)):
            m(i)
        return mats


def world_rot(mats, i):
    r = mats[i][:, :3, :3]
    sc = np.linalg.norm(r, axis=1)
    return G.mat_q(r / sc[:, None, :])


# ------------------------------------------------------------------------------------------------ unit parameters
def body_height(g: Glb) -> float:
    """Y extent of the skinned body at Unit_Idle's first key (FitSkinnedBattleMesh measures this, merged renderers)."""
    t0 = np.array([float(g.read(g.anim(IDLE)["samplers"][0]["input"])[0, 0])])
    mats = g.world(g.sample_local(IDLE, t0))
    lo, hi = np.inf, -np.inf
    for ni, n in enumerate(g.nodes):
        if "mesh" not in n:
            continue
        skin = g.json["skins"][n["skin"]] if "skin" in n else None
        for p in g.json["meshes"][n["mesh"]]["primitives"]:
            v = g.read(p["attributes"]["POSITION"])
            vh = np.c_[v, np.ones(len(v))]
            if skin is None:
                w = (mats[ni][0] @ vh.T).T[:, :3]
            else:
                ibm = g.read(skin["inverseBindMatrices"]).reshape(-1, 4, 4).transpose(0, 2, 1)
                jm = np.stack([mats[j][0] for j in skin["joints"]]) @ ibm
                js = g.read(p["attributes"]["JOINTS_0"]).astype(np.int64)
                ws = g.read(p["attributes"]["WEIGHTS_0"])
                ws = ws / np.maximum(ws.sum(1, keepdims=True), 1e-9)
                w = np.zeros((len(v), 3))
                for k in range(js.shape[1]):
                    w += ws[:, k:k + 1] * np.einsum("vij,vj->vi", jm[js[:, k]], vh)[:, :3]
            lo, hi = min(lo, w[:, 1].min()), max(hi, w[:, 1].max())
    if not np.isfinite(hi - lo) or hi - lo <= 1e-6:
        raise SystemExit("no measurable skinned height at Unit_Idle frame 0")
    return float(hi - lo)


def rubble_nodes(names: list, parent: dict) -> set:
    """Node ids of the death shatter's rubble: a node named *rubble* (build_unit.py's RubbleRoot) and every node under
    it (its Chunk_NN bones, which own the _Rubble mesh's vertices at weight 1 and hold it collapsed at the Root origin
    in every clip but Death). A name test alone misses the chunks: 2026-09-27 h3_skeleton_warrior and h3_banshee
    measured their floor on a collapsed chunk, which pinned the ground stage's entry to it instead of the body."""
    out = set()
    for i in range(len(names)):
        j = i
        while j is not None:
            if "rubble" in (names[j] or "").lower():
                out.add(i)
                break
            j = parent.get(j)
    return out


def skin_body(g: Glb) -> dict:
    """The skinned body for vertex heights: homogeneous rest positions, joint indices into mats (node ids) and
    normalised weights, rubble-owned vertices dropped (ground_check.glb_ground's floor rule)."""
    V, J, W = [], [], []
    for n in g.nodes:
        if "mesh" not in n or "skin" not in n:
            continue
        skin = g.json["skins"][n["skin"]]
        ibm = g.read(skin["inverseBindMatrices"]).reshape(-1, 4, 4).transpose(0, 2, 1)
        joints = np.array(skin["joints"])
        rn = rubble_nodes(g.names, g.parent)
        rub = np.array([j in rn for j in joints])
        for p in g.json["meshes"][n["mesh"]]["primitives"]:
            v = g.read(p["attributes"]["POSITION"])
            js = g.read(p["attributes"]["JOINTS_0"]).astype(np.int64)
            ws = g.read(p["attributes"]["WEIGHTS_0"])
            ws = ws / np.maximum(ws.sum(1, keepdims=True), 1e-9)
            keep = ~(rub[js] & (ws > 0.5)).any(1)
            vh = np.c_[v, np.ones(len(v))][keep]
            # bind-space positions per influence: ibm applied once, the frame's world matrix per sample
            V.append(np.einsum("vkij,vj->vki", ibm[js[keep]], vh))
            J.append(joints[js[keep]])
            W.append(ws[keep])
    if not V:
        raise SystemExit("no skinned mesh to measure the floor on")
    return {"B": np.concatenate(V), "J": np.concatenate(J), "W": np.concatenate(W)}


def skin_heights(body: dict, mats, frames, mask=None) -> np.ndarray:
    """(len(frames), n) world heights of the body's vertices (or the masked ones) at the given sample indices."""
    B, J, W = body["B"], body["J"], body["W"]
    if mask is not None:
        B, J, W = B[mask], J[mask], W[mask]
    out = np.zeros((len(frames), len(B)))
    for fi, k in enumerate(frames):
        up = np.stack([mats[n][k, UPI, :] for n in range(len(mats))])      # each node's world up row
        out[fi] = np.einsum("vk,vki,vki->v", W, up[J], B)
    return out


def import_row(unit: str) -> dict:
    """The homm3_import.json row a retarget unit ships as: its lab sid (battlePrefabAssetPath's folder, e.g.
    h3_champion) or, for rows keyed by game sid, its battleResPath leaf. Lab sid and game sid differ for
    renamed rows (h3_champion ships as h3_cavalier_upg), so both are tried and a miss is fatal. A retarget unit
    that ships under another lab sid (fleet_census.SOURCE_UNIT: h3_boar_rider builds the toa_boar_rider row) is
    looked up by that lab sid too; an alias that matches no row is still a miss."""
    from fleet_census import SOURCE_UNIT
    t = json.loads(IMPORT.read_text(encoding="utf-8-sig"))
    names = [unit] + sorted(lab for lab, src in SOURCE_UNIT.items() if src == unit)
    for name in names:
        for key in (lambda e: str(e.get("battlePrefabAssetPath") or "").split("/")[3:4],
                    lambda e: [str(e.get("battleResPath") or "").rsplit("/", 1)[-1]]):
            rows = [e for e in t["entries"] if name in key(e)]
            if rows:
                return {**rows[0], "_battleWorldHeightPerHex": t.get("battleWorldHeightPerHex")}
    raise SystemExit(f"{unit}: no homm3_import.json row by lab sid or battleResPath (tried {names})")


def move_speed_source(sid: str) -> dict:
    """The ground speed a walker's Move is matched to, and where it comes from.
    A game sid adopted in custom_factions/unit_move_speed_normalization.json takes its class's pinned target (the
    mean moveSpeed of its vanilla OE references; the Core overlay writes the same value into the view row), so the
    stride is fitted to a normalized speed and the speed is never lowered to the stride. Any other unit takes its
    installed Core view row. Two adopted game sids of one lab unit with different targets are refused."""
    from validate_unit_move_speed_normalization_contract import adopted_targets
    ids = [sid] + [g for g in import_row(sid).get("gameUnitSids", []) if g != sid]
    table = adopted_targets()
    hits = {g: table[g] for g in ids if g in table}
    if len({h["targetMoveSpeed"] for h in hits.values()}) > 1:
        raise SystemExit(f"{sid}: game sids {sorted(hits)} have different normalized move speeds")
    if hits:
        g, h = next(iter(hits.items()))
        return {"moveSpeed": h["targetMoveSpeed"], "source": f"normalized:{h['class']}", "gameSid": g, "refs": h["refs"]}
    return {"moveSpeed": core_view_move_speed(sid, ids), "source": "coreView"}


def view_move_speed(sid: str) -> float:
    return move_speed_source(sid)["moveSpeed"]


def core_view_move_speed(sid: str, ids: list[str]) -> float:
    with zipfile.ZipFile(CORE_ZIP) as z:
        for want in ids:
            for n in z.namelist():
                if n.startswith("DB/units/units_views/") and n.endswith(f"/{want}_v.json"):
                    for v in json.loads(z.read(n).decode("utf-8-sig")).get("array", []):
                        if isinstance(v, dict) and v.get("id") == want and v.get("moveSpeed") is not None:
                            return float(v["moveSpeed"])
    raise SystemExit(f"{sid}: no units_views moveSpeed for {ids} in {CORE_ZIP}")


def hex_target_height(sid: str) -> float:
    e = import_row(sid)
    if not e.get("battleHeightHexes") or not e.get("_battleWorldHeightPerHex"):
        raise SystemExit(f"{sid}: import row has no battleHeightHexes (or no battleWorldHeightPerHex)")
    return float(e["battleHeightHexes"]) * float(e["_battleWorldHeightPerHex"])


# ------------------------------------------------------------------------------------------------------- analysis
def chains_of(g: Glb) -> list[dict]:
    idx = {n: i for i, n in enumerate(g.names)}
    out = []
    for hip, knee, ank, toes in CHAINS:
        if hip in idx and knee in idx and ank in idx:
            out.append({"name": hip, "joints": (idx[hip], idx[knee], idx[ank]),
                        "contact": [idx[x] for x in toes if x in idx] + [idx[ank]]})
    for n in g.names:
        m = re.fullmatch(r"(Q[A-Z]{1,3})_00", n or "")
        if m and f"{m.group(1)}_01" in idx and f"{m.group(1)}_02" in idx:
            b = m.group(1)
            out.append({"name": b, "joints": (idx[f"{b}_00"], idx[f"{b}_01"], idx[f"{b}_02"]),
                        "contact": [idx[f"{b}_02"]]})
    for b in ("HFL", "HFR", "HHL", "HHR"):   # the def-retarget mount rig's horse legs (cavalier line, centaur body)
        if all(f"{b}{k}" in idx for k in range(3)):
            out.append({"name": b, "joints": (idx[f"{b}0"], idx[f"{b}1"], idx[f"{b}2"]), "contact": [idx[f"{b}2"]]})
    for b in ("HorseLF", "HorseRF", "HorseLH", "HorseRH"):   # necropolis_horse (black/dread knight, dreadtaur):
        if all(f"{b}{k}" in idx for k in ("Up", "Low", "Hoof")):   # two leg bones + the unweighted hoof leaf
            out.append({"name": b, "joints": (idx[f"{b}Up"], idx[f"{b}Low"], idx[f"{b}Hoof"]), "contact": [idx[f"{b}Hoof"]]})
        elif f"{b}Up" in idx and f"{b}Low" in idx:
            raise SystemExit(f"{b}: necropolis horse leg without its {b}Hoof end effector (rebuild with the current "
                             "necropolis_horse ext)")
    for b in ("FL", "FR", "RL", "RR"):       # stronghold_quadruped mount legs (wolf rider line), top -> paw
        if all(f"{b}{k}" in idx for k in range(1, 4)):
            out.append({"name": b, "joints": (idx[f"{b}1"], idx[f"{b}2"], idx[f"{b}3"]), "contact": [idx[f"{b}3"]]})
    names = {c["name"] for c in out}
    if names & MOUNT_SETS:                                   # a whole four-leg mount body: the rider is not legs
        out = [c for c in out if c["name"] in MOUNT_SETS]
    elif not names - set(ARM_CHAINS):                         # arms alone are arms (naga, medusa, elemental);
        out = []                                             # Q* front legs join a humanoid rig's UpLeg hind legs
    for c in out:   # the three joints must be one parent chain
        h, k, a = c["joints"]
        if g.parent.get(k) != h or g.parent.get(a) != k:
            raise SystemExit(f"chain {c['name']} is not a hip-knee-ankle parent chain")
    return out


def grounded_chains(chains: list[dict], low: dict[str, float], height: float,
                    include: frozenset = frozenset()) -> tuple[list[dict], float]:
    """Walking chains of a walker: every dedicated leg, plus arms that reach the legs' floor band.
    low: each chain's lowest contact height over the Move cycle. Returns (chains, legs' floor).
    include: arm chains apply() must plant although the SOURCE Move keeps them above the band: measure() found them
    inside it after the pelvis drop (cmd_apply iterates until the planted set equals the scored set)."""
    legs = [c for c in chains if c["name"] not in ARM_CHAINS]
    if not legs:
        raise SystemExit("walker has no leg chain chains_of recognises: teach it this rig (or declare strideExempt)")
    unknown = set(include) - {c["name"] for c in chains}
    if unknown:
        raise SystemExit(f"plant set names chains this rig does not have: {sorted(unknown)}")
    floor = min(low[c["name"]] for c in legs)
    return legs + [c for c in chains if c["name"] in ARM_CHAINS and (low[c["name"]] <= floor + GROUND_BAND * height
                                                                     or c["name"] in include)], floor


def sole_of(g: Glb, body: dict, chain: dict) -> tuple[int, np.ndarray]:
    """(node, vertex mask) of a chain's sole: the vertices weighted >= 0.5 to its ankle's subtree, or, for a
    zero-weight contact leaf, to the lowest weighted ancestor's subtree inside the chain -- the surface
    plant_transform stands on the Idle floor."""
    h, _, an = chain["joints"]
    node = an
    while True:
        nodes = {node} | {i for i in range(len(g.nodes)) if _descends(g, i, node)}
        mask = (body["W"] * np.isin(body["J"], list(nodes))).sum(1) >= 0.5
        if mask.any() or node == h:
            break
        node = g.parent[node]
    if not mask.any():
        raise SystemExit(f"chain {chain['name']}: no vertex is weighted to any bone of the chain from "
                         f"{g.names[an]} up to {g.names[h]}; cannot put the foot on the floor")
    return node, mask


def planted_chains(stamp: dict) -> list[str]:
    """The chains apply planted: transform.plantedChains, or (stamps before 2026-09-27) the transform report's keys."""
    tr = stamp.get("transform") or {}
    got = tr.get("plantedChains", list(tr.get("chains", {})))
    if not got:
        raise SystemExit("stride stamp records no planted chains")
    return list(got)


def cycle_times(g: Glb, n: int = SAMPLES):
    end = g.clip_end(MOVE)
    return np.arange(n) * end / n, end


def contact_traj(g: Glb, mats, chain) -> np.ndarray:
    """Per sample, the lowest of the chain's contact points (toe or ankle)."""
    pts = np.stack([mats[i][:, :3, 3] for i in chain["contact"]])      # (k, N, 3)
    lowest = np.argmin(pts[:, :, 1].min(axis=1))
    return pts[lowest]


def measure(g: Glb, move_speed: float, world_scale: float, height: float, *, flier: bool,
            planted: frozenset | None = None) -> dict:
    """flier: the HoMM3 class (unit_flier); a stride-stamped GLB is a walker by construction.
    planted: the chains apply planted (default: the stamp's plantedChains, none on an unstamped GLB). A planted chain
    is in the floor band when its SOLE is -- the surface the plant stood on the Idle floor -- since its contact joint
    sits a chain-specific height above it (hota_factory_armadillo's paw joints 0.08-0.11 H, its legs' 0.03 H: a
    correctly planted paw left the joint band and the unit was refused at every maxDrop, 2026-09-27). Every other
    chain is judged by its contact joint as before."""
    if flier:
        return {"airborne": True, "flier": True, "reason": "HoMM3 flier (reference/homm3_fliers.json): no ground stride"}
    times, end = cycle_times(g)
    mats = g.world(g.sample_local(MOVE, times))
    chains = chains_of(g)
    trajs = {c["name"]: contact_traj(g, mats, c) for c in chains}
    st = g.json.get("asset", {}).get("extras", {}).get(STAMP)
    if planted is None:
        planted = frozenset(planted_chains(st)) if st else frozenset()
    low = {k: float(t[:, 1].min()) for k, t in trajs.items()}
    joint_walk, floor = grounded_chains(chains, low, height)
    on_sole = set()
    if planted - {c["name"] for c in joint_walk}:
        body = skin_body(g)
        leg_sole = min(float(skin_heights(body, mats, range(len(times)), sole_of(g, body, c)[1]).min())
                       for c in chains if c["name"] not in ARM_CHAINS)
        for c in chains:
            if c["name"] in planted and c["name"] in ARM_CHAINS:
                sl = float(skin_heights(body, mats, range(len(times)), sole_of(g, body, c)[1]).min())
                if sl <= leg_sole + GROUND_BAND * height:
                    on_sole.add(c["name"])
    walk = [c for c in chains if c in joint_walk or c["name"] in on_sole]
    t0 = np.array([float(g.read(g.anim(IDLE)["samplers"][0]["input"])[0, 0])])
    imats = g.world(g.sample_local(IDLE, t0))
    idle_floor = min(float(contact_traj(g, imats, c)[:, 1].min()) for c in walk)
    grounded = [c["name"] for c in walk]
    res = {"moveFloorAboveIdleFloor": round((floor - idle_floor) / height, 4), "chains": [c["name"] for c in chains],
           "grounded": grounded, "bodyHeight": round(height, 4)}
    res["floorLiftFlag"] = bool(floor - idle_floor > AIRBORNE_LIFT * height)   # reported, not a class
    res["legFloorGap"] = round(max(float(trajs[k][:, 1].min()) - floor for k in grounded) / height, 4)
    if len(grounded) < 2:
        raise SystemExit(f"walker has fewer than two walking chains ({grounded} of {res['chains']}): "
                         "teach chains_of this rig")
    if st:
        planted = planted_chains(st)
        if set(grounded) != set(planted):
            raise SystemExit(f"stride-matched Move scores chains {sorted(grounded)} but apply planted {sorted(planted)}: "
                             "a chain scored for slip was never planted (or one planted left the floor band)")
    res["airborne"] = False
    res["flier"] = False
    res.update(G.analyze({k: trajs[k] for k in grounded}, end, height, world_scale, move_speed, forward=FORWARD,
                         playback=PLAYBACK))
    return res


# ---------------------------------------------------------------------------------------------------------- apply
def write_channels(g: Glb, a: dict, grid: np.ndarray, targets: dict, interpolation: str = "LINEAR") -> None:
    """Point every (node, path) channel in `targets` at a new sampler on `grid` (LINEAR unless told otherwise); add
    missing channels; drop samplers nothing reads any more (the exporter's shared accessors stay, other clips may
    read them)."""
    tin = g.append_accessor(grid.astype(np.float32)[:, None], "SCALAR")

    def acc(path, v):
        if path == "rotation":   # sign-continuous keys so Unity's per-component curves do not flip
            v = v.copy()
            for i in range(1, len(v)):
                if np.dot(v[i], v[i - 1]) < 0:
                    v[i] = -v[i]
        return g.append_accessor(v.astype(np.float32), "VEC4" if path == "rotation" else "VEC3")

    done = set()
    for ch in a["channels"]:
        key = (ch["target"]["node"], ch["target"]["path"])
        if key in targets:
            a["samplers"].append({"input": tin, "output": acc(key[1], targets[key]), "interpolation": interpolation})
            ch["sampler"] = len(a["samplers"]) - 1
            done.add(key)
    for node, path in sorted(set(targets) - done):
        a["samplers"].append({"input": tin, "output": acc(path, targets[(node, path)]), "interpolation": interpolation})
        a["channels"].append({"sampler": len(a["samplers"]) - 1, "target": {"node": node, "path": path}})
    used = sorted({ch["sampler"] for ch in a["channels"]})
    remap = {old: new for new, old in enumerate(used)}
    a["samplers"] = [a["samplers"][i] for i in used]
    for ch in a["channels"]:
        ch["sampler"] = remap[ch["sampler"]]


def stride_transform(g: Glb, gain: float, max_drop: float, height: float, lift: float = 0.0,
                     include: frozenset = frozenset()):
    """Rewrite the grounded chains' Move keys for stride gain `gain`. Returns a report."""
    a = g.anim(MOVE)
    grid = g.key_grid(MOVE)
    loc = g.sample_local(MOVE, grid)
    mats = g.world(loc)
    chains = chains_of(g)
    # walking chains, judged on the dense cycle as in measure()
    dtimes, _ = cycle_times(g)
    dmats = g.world(g.sample_local(MOVE, dtimes))
    dtraj = {c["name"]: contact_traj(g, dmats, c) for c in chains}
    chains, floor = grounded_chains(chains, {k: float(t[:, 1].min()) for k, t in dtraj.items()}, height, include)
    for c in chains:
        for j in c["joints"]:
            for s in (loc[j][2], g.rest(j)[2]):
                if np.any(np.abs(np.asarray(s) - 1.0) > 1e-3):
                    raise SystemExit(f"chain bone {g.names[j]} is scaled; the IK assumes unit scale")
    hips = g.names.index("Hips")
    f = FORWARD
    plan = []
    drop = np.zeros(len(grid))
    lifted = {}
    for c in chains:
        h, k, an = c["joints"]
        H, K, A = (mats[i][:, :3, 3] for i in (h, k, an))
        C = contact_traj(g, mats, c)
        zbar = float((dtraj[c["name"]] @ f).mean())      # time-weighted cycle mean of the contact point
        delta = ((gain - 1.0) * ((C @ f) - zbar))[:, None] * f
        # swing lift: where the lengthened foot travels forward it must clear the floor, or it skates forward
        # (a DEF march in place barely lifts). Only raises a foot that is lower than the lift arc.
        z2 = (C + delta) @ f
        cyc = len(grid) - 1 if np.allclose(z2[0], z2[-1]) else len(grid)   # closing copy of frame 0
        fwd = np.zeros(len(grid), bool)
        zc = z2[:cyc]
        fwd[:cyc] = (np.roll(zc, -1) - np.roll(zc, 1)) > 1e-4 * height
        floor_c = floor if c["name"] in include else float(dtraj[c["name"]][:, G.UP].min())
        dy = np.zeros(len(grid))
        i = 0
        runs = []
        while i < cyc:            # contiguous forward runs on the cyclic key ring
            if fwd[i] and not fwd[(i - 1) % cyc]:
                j = i
                run = []
                while fwd[j % cyc] and len(run) < cyc:
                    run.append(j % cyc); j += 1
                runs.append(run)
            i += 1
        if fwd[:cyc].all():
            runs = [list(range(cyc))]
        for run in runs:
            m = len(run)
            for jj, key in enumerate(run):
                arc = floor_c + lift * height * np.sin(np.pi * (jj + 1) / (m + 1))
                dy[key] = max(0.0, arc - float(C[key, G.UP]))
        if cyc < len(grid):
            dy[-1] = dy[0]
        delta[:, G.UP] += dy
        lifted[c["name"]] = round(float(dy.max()), 5)
        target = A + delta
        l = np.linalg.norm(K - H, axis=1) + np.linalg.norm(A - K, axis=1)
        reach = np.maximum(0.999 * l, np.linalg.norm(A - H, axis=1))
        dv = target - H
        hz = np.linalg.norm(dv[:, [0, 2]], axis=1)
        need = -dv[:, 1] - np.sqrt(np.maximum(reach ** 2 - hz ** 2, 0.0))
        drop = np.maximum(drop, np.clip(need, 0.0, max_drop * float(l.mean())))
        plan.append((c, target, l))
    # pelvis drop: Hips translation keys (parent linear part inverted)
    new_hips_t = None
    if drop.max() > 1e-6:
        p = g.parent.get(hips)
        pm = mats[p][:, :3, :3] if p is not None else np.tile(np.eye(3), (len(grid), 1, 1))
        dw = np.zeros((len(grid), 3)); dw[:, 1] = -drop
        new_hips_t = loc[hips][0] + np.einsum("nij,nj->ni", np.linalg.inv(pm), dw)
        loc[hips][0] = new_hips_t
        mats = g.world(loc)
    new_rot = {}
    report_chains = {}
    for c, target, l in plan:
        h, k, an = c["joints"]
        H, K, A = (mats[i][:, :3, 3] for i in (h, k, an))
        rh, rk, ra = (world_rot(mats, i) for i in (h, k, an))
        # rest-pose bend direction for straight frames
        rest_l = {i: g.rest(i) for i in (h, k, an)}
        pole_fb = G.qrot(rh, rest_l[k][0]) - np.sum(G.qrot(rh, rest_l[k][0]) * (A - H), axis=1)[:, None] * (A - H) \
            / np.maximum(np.sum((A - H) ** 2, axis=1), 1e-12)[:, None]
        K2, A2, clamped = G.two_bone_ik(H, K, A, target, pole_fb)
        q1 = G.q_between(K - H, K2 - H)
        rh2 = G.qnorm(G.qmul(q1, rh))
        q2 = G.q_between(G.qrot(q1, A - K), A2 - K2)
        rk2 = G.qnorm(G.qmul(q2, G.qmul(q1, rk)))
        ph = g.parent[h]
        rp = world_rot(mats, ph)
        new_rot[h] = G.qmul(G.qconj(rp), rh2)
        new_rot[k] = G.qmul(G.qconj(rh2), rk2)
        new_rot[an] = G.qmul(G.qconj(rk2), ra)
        report_chains[c["name"]] = {"reachClampedKeys": int(clamped.sum()), "swingLift": lifted[c["name"]],
                                    "firstKeyAnkleShift": round(float(np.linalg.norm(target[0] - A[0])), 4),
                                    "maxAnkleShift": round(float(np.linalg.norm(target - A, axis=1).max()), 4)}
    targets = {(i, "rotation"): v for i, v in new_rot.items()}
    if new_hips_t is not None:
        targets[(hips, "translation")] = new_hips_t
    write_channels(g, a, grid, targets)
    return {"chains": report_chains, "plantedChains": [c["name"] for c, _, _ in plan], "keys": int(len(grid)),
            "maxPelvisDrop": round(float(drop.max()), 5),
            "maxPelvisDropOverHeight": round(float(drop.max()) / height, 4)}


BETA_MIN, BETA_MAX = 0.30, 0.75           # plant: stance fraction of the cycle (below ~0.5 a biped has a flight phase)
REACH_MARGIN = 0.995                      # plant: planned stance keeps the ankle inside this x leg length
REACH_PERCENTILE = 10                     # plant: leg reach is this percentile over the cycle's hip heights
SWING_LIFT_OF_SWEEP = 0.10                # plant: swing clearance at least this x the foot's sweep
DEFAULT_MAX_CADENCE = 1.6                 # plant: most the Move clip may be sped up where the legs cannot reach
CLEARANCE_TOL = 1e-5                      # plant: a planted limb may sit this x height below the Idle floor (float noise)
CLEARANCE_ITERS = 12                      # plant: clearance raise/re-solve passes before refusing
CLEARANCE_MIN_GAIN = 0.25                 # plant: a raise is scaled by 1 / (the lift the previous raise bought per unit
#   raised), that measured gain floored here (so one pass raises at most 4x the deficit left)


def paired(name: str) -> str | None:
    if "Left" in name:
        return name.replace("Left", "Right")
    if "Right" in name:
        return name.replace("Right", "Left")
    m = re.fullmatch(r"(Q[A-Z]*)([LR])", name)
    return m.group(1) + {"L": "R", "R": "L"}[m.group(2)] if m else None


def stance_phase(z: np.ndarray, y: np.ndarray) -> dict:
    """Stance of one contact point from its source cycle (uniform phase samples, no end duplicate): the longest
    cyclic run where it moves backward (-f), after a short circular smoothing. Returns phase0, beta, sweep."""
    n = len(z)
    w = max(1, n // 24)
    zs = np.convolve(np.r_[z[-w:], z, z[:w]], np.ones(2 * w + 1) / (2 * w + 1), mode="same")[w:w + n]
    dz = np.roll(zs, -1) - zs
    back = dz < 0
    best, start = 0, 0
    if back.all():
        best, start = n, 0
    elif back.any():
        k0 = int(np.argmin(back))              # a forward sample: runs never wrap past it
        for off in range(n):
            i = (k0 + off) % n
            if back[i] and not back[(i - 1) % n]:
                run = 0
                while back[(i + run) % n] and run < n:
                    run += 1
                if run > best:
                    best, start = run, i
    idx = (start + np.arange(best)) % n
    return {"phase0": start / n, "beta": best / n, "sweep": float(-dz[idx].sum()) if best else 0.0,
            "yMinPhase": float(np.argmin(y)) / n}


def _descends(g: Glb, i: int, anc: int) -> bool:
    p = g.parent.get(i)
    while p is not None:
        if p == anc:
            return True
        p = g.parent.get(p)
    return False


def retime_clip(g: Glb, name: str, cadence: float) -> None:
    """Play `name` `cadence` times faster: every sampler gets a new, scaled input accessor (the exporter shares key
    time arrays between clips, so the originals are never edited in place)."""
    a = g.anim(name)
    made: dict[int, int] = {}
    for sm in a["samplers"]:
        i = sm["input"]
        if i not in made:
            made[i] = g.append_accessor((g.read(i)[:, 0] / cadence).astype(np.float32)[:, None], "SCALAR")
        sm["input"] = made[i]


MOUNT_ROOT_SWING = 0.3                    # plant: a horse leg's root may slide fore-aft on the Hips this x leg length
MOUNT_ROOT_SMOOTH = 3                     # plant: circular half-window (keys) the root slide is averaged over
MOUNT_CHAIN = re.compile(r"^(H[FH][LR]|Horse[LR][FH])$")  # plant: horse legs (castle_mount, necropolis_horse) slide
POLE_WEAK = 0.15                          # plant: a knee this close (x thigh) to the hip->ankle line has no bend of its own
POLE_SMOOTH = 2                           # plant: circular half-window (keys) the knee direction is averaged over


def knee_pole(Hs, Ks, As, ref):
    """Per-key knee direction for the IK, consistent over the cycle. The source's own bend plane is kept where the
    knee is clearly bent and bends the chain's usual way; a nearly straight frame (a horse's legs, a planted biped)
    or one bending the other way takes the chain's mean bend `ref`, and the result is averaged over a few keys
    (the Move cycle wraps). Without this a straight source frame's noise flips the knee and the hoof between keys
    (the cavalier's HHL2 read 0.47 jitter)."""
    ha = As - Hs
    ha = ha / np.maximum(np.linalg.norm(ha, axis=1), 1e-12)[:, None]
    kp = (Ks - Hs) - np.sum((Ks - Hs) * ha, axis=1)[:, None] * ha
    thigh = np.linalg.norm(Ks - Hs, axis=1)
    ref = np.asarray(ref, float) / max(float(np.linalg.norm(ref)), 1e-12)
    bent = (np.linalg.norm(kp, axis=1) >= POLE_WEAK * thigh) & (kp @ ref > 0.0)
    d = np.where(bent[:, None], kp / np.maximum(np.linalg.norm(kp, axis=1), 1e-12)[:, None], ref[None, :])
    n = len(d)
    last_is_first = n > 1 and np.allclose(d[0], d[-1])
    m = n - 1 if last_is_first else n
    acc = sum(np.roll(d[:m], s, axis=0) for s in range(-POLE_SMOOTH, POLE_SMOOTH + 1))
    out = np.array(d)
    out[:m] = acc / np.maximum(np.linalg.norm(acc, axis=1), 1e-12)[:, None]
    if last_is_first:
        out[-1] = out[0]
    return out


def root_swing(chain_name: str) -> float:
    """Fore-aft slide the chain's root may take, x leg length. Horse legs only: their source legs stand nearly
    straight, so two-bone reach alone cannot sweep the stance OE's ground speed needs (the justiciar's hind leg has
    none), and a horse's stride comes from the scapula / pelvis swing anyway. 0.3 passed every gate with the least
    new stretch at the shoulders (0.4 added 32 edges past 2x); a biped or quadruped chain never slides."""
    return MOUNT_ROOT_SWING if MOUNT_CHAIN.match(chain_name) else 0.0


def root_slide(g: Glb, mats, src, chain: dict, target: np.ndarray, f: np.ndarray) -> np.ndarray:
    """Per-key fore-aft root offset (world, along f) covering what the leg's reach cannot: the part of the target's
    fore-aft distance from the hip beyond sqrt((0.99 l)^2 - dy^2 - lat^2), at most root_swing x l, smoothed
    circularly (peaks kept, then averaged) so the root does not jerk. Zero for a chain that does not slide."""
    smax_frac = root_swing(chain["name"])
    n = len(target)
    if smax_frac <= 0.0:
        return np.zeros(n)
    h, k, a = chain["joints"]
    l = float(np.linalg.norm(src[k][:, :3, 3] - src[h][:, :3, 3], axis=1).mean()
              + np.linalg.norm(src[a][:, :3, 3] - src[k][:, :3, 3], axis=1).mean())
    dv = target - mats[h][:, :3, 3]
    dz = dv @ f
    up = np.zeros(3); up[UPI] = 1.0
    lat = np.linalg.norm(dv - np.outer(dz, f) - np.outer(dv[:, UPI], up), axis=1)
    r = np.sqrt(np.maximum((0.99 * l) ** 2 - dv[:, UPI] ** 2 - lat ** 2, 0.0))
    sh = np.sign(dz) * np.clip(np.abs(dz) - r, 0.0, smax_frac * l)
    m = n - 1                                       # the grid's last key repeats the first (the cycle wraps)
    win = range(-MOUNT_ROOT_SMOOTH, MOUNT_ROOT_SMOOTH + 1)
    out = np.array(sh)
    acc = sum(np.roll(sh[:m], s) for s in win) / len(win)
    out[:m] = np.where(np.abs(sh[:m]) > np.abs(acc), sh[:m], acc)
    acc = sum(np.roll(out[:m], s) for s in win) / len(win)
    out[:m] = acc
    out[-1] = out[0]
    return out


def plant_transform(g: Glb, ground_rate: float, max_drop: float, height: float, max_excursion: float,
                    lift: float, max_cadence: float = DEFAULT_MAX_CADENCE, _cadence: float = 1.0,
                    harmonic_keep: float | None = None, include: frozenset = frozenset(),
                    prop_bone: str | None = None, pelvis_hold: float | None = None,
                    trot_phase: float | None = None, swing_curl: float | None = None) -> dict:
    """Plant-constrained stride synthesis (the default `apply` mode). ground_rate: body units the ground moves under
    the unit per second of clip time (moveSpeed / (playback x worldScale)).

    Every grounded foot is re-timed on the source's own step phase and given a stance that sweeps backward exactly
    at ground speed on its own floor, centred under its hip, then a smooth swing forward that clears the floor. The
    body (Hips down to the leg roots) keeps its keys; each leg is solved by two-bone IK in the source frame's bend
    plane, the ankle keeps the source world rotation, and the pelvis sinks where a leg cannot reach (<= max_drop x
    leg length). A stance sweep is capped by max_excursion x height and by the leg's own reach at that pelvis drop:
    the stance is shortened first (down to BETA_MIN), and only if the shortest stance still outruns the shortest
    leg is the whole Move clip sped up, by at most max_cadence (the capped blend of stride and rate).
    harmonic_keep (unit config strideMatch.highHarmonicKeep): scale the rewritten channels' spectra above the
    articulation jitter cutoff by this factor before writing (keep_low_harmonics); None leaves them as solved.
    prop_bone (unit config propFloor.bone): the vertices weighted more than 0.5 to it are prop_floor_glb.py's to
    clear (it tilts the prop after this stage), so the body clearance does not lift the pelvis for them.
    Leg keys are read at the source phase ts = t0 + (t/L)(L - t0), which removes the 1/12 s hold the exporter leaves
    before a DEF Move's first key (the body keeps it)."""
    a = g.anim(MOVE)
    L = g.clip_end(MOVE)
    stride_req = ground_rate * L
    t0 = min(float(g.read(sm["input"])[0, 0]) for sm in a["samplers"])
    n_keys = 4 * max(1, int(round(L * 12 * _cadence)))
    grid = np.linspace(0.0, L, n_keys + 1)
    phase = grid / L
    ts = t0 + phase * (L - t0)
    loc = g.sample_local(MOVE, grid)
    src_loc = g.sample_local(MOVE, ts)
    mats = g.world(loc)
    src = g.world(src_loc)
    dm = g.world(g.sample_local(MOVE, t0 + np.arange(SAMPLES) / SAMPLES * (L - t0)))
    chains = chains_of(g)
    dtraj = {c["name"]: contact_traj(g, dm, c) for c in chains}
    chains, floor = grounded_chains(chains, {k: float(t[:, UPI].min()) for k, t in dtraj.items()}, height, include)
    for c in chains:
        for j in c["joints"]:
            for sc in (loc[j][2], src_loc[j][2], g.rest(j)[2]):
                if np.any(np.abs(np.asarray(sc) - 1.0) > 1e-3):
                    raise SystemExit(f"chain bone {g.names[j]} is scaled; the IK assumes unit scale")
    # the floor is the Idle floor (ground_check's reference: the lowest skinned vertex at Unit_Idle's first key), and a
    # planted foot stands ON it: its own lowest vertex, not its contact joint, is what touches it
    body = skin_body(g)
    ti = np.array([float(g.read(g.anim(IDLE)["samplers"][0]["input"])[0, 0])])
    idle_floor = float(skin_heights(body, g.world(g.sample_local(IDLE, ti)), [0]).min())
    f = FORWARD
    st = {c["name"]: stance_phase(dtraj[c["name"]] @ f, dtraj[c["name"]][:, UPI]) for c in chains}
    top = max(v["sweep"] for v in st.values())
    ok = {k: 0.25 <= v["beta"] <= 0.85 and top > 1e-6 and v["sweep"] >= 0.25 * top for k, v in st.items()}
    cap = max_excursion * height
    trot = {}
    if trot_phase is not None:
        names = {c["name"] for c in chains}
        need4 = {n for pair in TROT_DIAGONALS for n in pair}
        if not need4 <= names:
            raise SystemExit(f"strideMatch.trotPhase: the trot needs planted {sorted(need4)}, planted {sorted(names)}")
        for k, pair in enumerate(TROT_DIAGONALS):
            for n in pair:
                trot[n] = (trot_phase + 0.5 * k) % 1.0
    legs = []
    for c in chains:                        # pass 1: phase, reach, geometry
        nm = c["name"]
        pr = paired(nm)
        if nm in trot:
            src_beta = st[nm]["beta"] if ok[nm] else (st[pr]["beta"] if pr in ok and ok[pr] else 0.6)
            ph0, beta, how = trot[nm], src_beta, "trotPhase"
        elif ok[nm]:
            ph0, beta, how = st[nm]["phase0"], st[nm]["beta"], "own"
        elif pr in ok and ok[pr]:
            ph0, beta, how = (st[pr]["phase0"] + 0.5) % 1.0, st[pr]["beta"], f"paired:{pr}"
        else:
            ph0, beta, how = (st[nm]["yMinPhase"] - 0.3) % 1.0, 0.6, "heightMin"
        h, k, an = c["joints"]
        C = contact_traj(g, src, c)
        off = mats[h][:, :3, 3] - src[h][:, :3, 3]          # the source leg, carried to the body's hip at t
        Hs = src[h][:, :3, 3] + off
        Ks = src[k][:, :3, 3] + off
        As = src[an][:, :3, 3] + off
        foot = As - (C + off)                                # ankle relative to its contact point (source pose)
        l = np.linalg.norm(Ks - Hs, axis=1) + np.linalg.norm(As - Ks, axis=1)
        Cd = dtraj[nm]
        # stance floor per key: the contact-point height that puts this foot's lowest vertex on the Idle floor. The
        # foot keeps its source world rotation (and its toes their source keys), so its sole sits sole(t) below the
        # contact point exactly as in the source frame. (Before 2026-09-28 the stance floor was the chain's own lowest
        # source contact height, which left a sinking source Move sunk: h3_boar_rider hind hooves -0.053 H.)
        # A zero-weight contact leaf (HorseXXHoof, 0cde3981fb) owns no vertex: the sole is then the lowest weighted
        # ancestor's subtree inside the chain (the lower leg that carries the hoof), named in the report. The IK
        # turns that bone, so its sole is the source frame's, carried with the contact point (ground_glb checks it).
        sole_node, fmask = sole_of(g, body, c)
        sole = skin_heights(body, src, range(len(grid)), fmask).min(1) - C[:, UPI]
        floor_c = idle_floor - sole
        xc = Cd.mean(axis=0) - (Cd.mean(axis=0) @ f) * f
        xc[UPI] = 0.0
        # reach: fore-aft distance from the hip a planted ankle can take with the pelvis sunk by the allowed drop
        rel = xc + foot - Hs
        rel[:, UPI] = 0.0
        lat = np.linalg.norm(rel - (rel @ f)[:, None] * f, axis=1)
        dy = Hs[:, UPI] - max_drop * l - (floor_c + foot[:, UPI])
        rk = np.sqrt(np.maximum((REACH_MARGIN * l) ** 2 - dy ** 2 - lat ** 2, 0.0))
        R = float(np.percentile(rk, REACH_PERCENTILE))
        legs.append(dict(c=c, nm=nm, how=how, ph0=ph0, beta_src=beta, C=C, Hs=Hs, Ks=Ks, As=As, foot=foot, l=l,
                         floor_c=floor_c, sole_from=g.names[sole_node], floor_shift=float(np.mean(floor_c)) - float(Cd[:, UPI].min()), xc=xc, cap=min(cap, max(2.0 * R + 2.0 * root_swing(nm) * float(l.mean()), st[nm]["sweep"])), R=R,
                         zc=float(np.mean(Hs @ f - foot @ f))))
    need = max(stride_req * BETA_MIN / max(lg["cap"], 1e-9) for lg in legs)
    if _cadence == 1.0 and need > 1.0 + 1e-3 and max_cadence > 1.0:
        cad = float(min(need, max_cadence))
        retime_clip(g, MOVE, cad)
        rep = plant_transform(g, ground_rate, max_drop, height, max_excursion, lift, max_cadence, _cadence=cad,
                              harmonic_keep=harmonic_keep, include=include, prop_bone=prop_bone,
                              pelvis_hold=pelvis_hold, trot_phase=trot_phase, swing_curl=swing_curl)
        rep["cadence"] = round(cad, 4)
        rep["cadenceNeeded"] = round(need, 4)
        return rep
    plan, report, drop = [], {}, np.zeros(len(grid))
    curl_w = {}                              # strideMatch.swingCurl: per-key swing weight sin(pi wf) of each chain
    for lg in legs:                         # pass 2: foot targets and pelvis drop
        nm = lg["nm"]
        beta = float(np.clip(lg["beta_src"], BETA_MIN, BETA_MAX))
        sweep = stride_req * beta
        if sweep > lg["cap"]:               # shorten the stance first: a quicker plant keeps the foot still
            beta = max(BETA_MIN, lg["cap"] / stride_req)
            sweep = min(stride_req * beta, lg["cap"])
        u = (phase - lg["ph0"]) % 1.0
        stance = u < beta
        ws = np.where(stance, u / beta, 0.0)
        wf = np.where(stance, 0.0, (u - beta) / (1.0 - beta))
        smooth = wf * wf * (3.0 - 2.0 * wf)
        zc = lg["zc"]
        z = np.where(stance, zc + sweep * (0.5 - ws), zc - sweep * 0.5 + sweep * smooth)
        lift_h = max(lift * height, SWING_LIFT_OF_SWEEP * sweep)
        arc = lg["floor_c"] + lift_h * np.sqrt(np.sin(np.pi * wf))
        y = np.where(stance, lg["floor_c"], np.maximum(lg["C"][:, UPI], arc))
        T = lg["xc"][None, :] + z[:, None] * f[None, :]
        T[:, UPI] = y
        target = T + lg["foot"]
        dv = target - lg["Hs"]
        hz = np.linalg.norm(dv[:, [0, 2]], axis=1)
        nd = -dv[:, UPI] - np.sqrt(np.maximum((0.999 * lg["l"]) ** 2 - hz ** 2, 0.0))
        drop = np.maximum(drop, np.clip(nd, 0.0, max_drop * float(lg["l"].mean())))
        plan.append((lg["c"], target, stance))
        curl_w[lg["c"]["name"]] = np.where(stance, 0.0, np.sin(np.pi * wf))
        report[nm] = {"phaseFrom": lg["how"], "phase0": round(lg["ph0"], 3), "stanceFraction": round(beta, 3),
                      "sweepOverHeight": round(sweep / height, 4),
                      "reachSweepCapOverHeight": round(2 * lg["R"] / height, 4),
                      "sourceSweepOverHeight": round(st[nm]["sweep"] / height, 4),
                      "legOverHeight": round(float(lg["l"].mean()) / height, 4),
                      "swingLiftOverHeight": round(lift_h / height, 4),
                      "strideDeliveredOverRequired": round(sweep / beta / stride_req, 4),
                      "stanceFloorShiftOverHeight": round(lg["floor_shift"] / height, 4),
                      "soleFrom": lg["sole_from"]}
    hips = g.names.index("Hips")
    targets = {}
    lg_len = {lg["nm"]: float(lg["l"].mean()) for lg in legs}
    hp = g.parent.get(hips)
    hips_pm_inv = np.linalg.inv(mats[hp][:, :3, :3] if hp is not None else np.tile(np.eye(3), (len(grid), 1, 1)))
    hips_base = np.array(loc[hips][0], float)

    def set_pelvis(offset):
        """Hips translation = its keys + `offset` (world up, per key); the drop below, the clearance lift later."""
        nonlocal mats
        dw = np.zeros((len(grid), 3)); dw[:, UPI] = offset
        loc[hips][0] = hips_base + np.einsum("nij,nj->ni", hips_pm_inv, dw)
        if np.any(np.abs(offset) > 1e-9):
            targets[(hips, "translation")] = loc[hips][0]
        else:
            targets.pop((hips, "translation"), None)
        mats = g.world(loc)

    held_drop = 0.0
    if pelvis_hold is not None:              # strideMatch.pelvisHold: the body stays near its fitted height
        held_drop = float(np.maximum(drop - pelvis_hold * height, 0.0).max())
        drop = np.minimum(drop, pelvis_hold * height)
    if drop.max() > 1e-6:
        set_pelvis(-drop)
    slides = {}
    for c, target, _ in plan:               # horse legs: slide the root where the leg cannot reach
        sh = root_slide(g, mats, src, c, target, f)
        if np.any(sh != 0.0):
            h = c["joints"][0]
            pm = mats[g.parent[h]][:, :3, :3]
            loc[h][0] = loc[h][0] + np.einsum("nij,nj->ni", np.linalg.inv(pm), np.outer(sh, f))
            targets[(h, "translation")] = loc[h][0]
            slides[c["name"]] = sh
    if slides:
        mats = g.world(loc)
    slot = {"translation": 0, "rotation": 1, "scale": 2}

    def solve(c, target):
        """Leg keys that put the chain's ankle on `target` (hip, knee, ankle rotations and the foot's own children)."""
        h, k, an = c["joints"]
        off = mats[h][:, :3, 3] - src[h][:, :3, 3]
        Hs, Ks, As = (src[i][:, :3, 3] + off for i in (h, k, an))
        rh, rk, ra = (world_rot(src, i) for i in (h, k, an))
        if swing_curl and c["name"] in curl_w:   # swing: the foot curls back (hoof/toe up behind the leg), 0 at stance
            ax = np.cross(np.eye(3)[UPI], f)
            ax = ax / np.linalg.norm(ax)
            ang = np.radians(swing_curl) * curl_w[c["name"]]
            qc = np.concatenate([ax[None, :] * np.sin(ang / 2)[:, None], np.cos(ang / 2)[:, None]], axis=1)
            ra = G.qnorm(G.qmul(qc, ra))
        # a straight source frame has no bend plane of its own: bend it the way the chain's bent frames do
        ha = (As - Hs) / np.maximum(np.linalg.norm(As - Hs, axis=1), 1e-12)[:, None]
        kp = (Ks - Hs) - np.sum((Ks - Hs) * ha, axis=1)[:, None] * ha
        mean_bend = kp.sum(axis=0)
        pole_fb = mean_bend / np.linalg.norm(mean_bend) if np.linalg.norm(mean_bend) > 1e-6 else f
        K2, A2, clamped = G.two_bone_ik(Hs, Ks, As, target, pole_fb, pole_dir=knee_pole(Hs, Ks, As, pole_fb))
        q1 = G.q_between(Ks - Hs, K2 - Hs)
        rh2 = G.qnorm(G.qmul(q1, rh))
        q2 = G.q_between(G.qrot(q1, As - Ks), A2 - K2)
        rk2 = G.qnorm(G.qmul(q2, G.qmul(q1, rk)))
        rp = world_rot(mats, g.parent[h])
        out = {(h, "rotation"): G.qmul(G.qconj(rp), rh2), (k, "rotation"): G.qmul(G.qconj(rh2), rk2),
               (an, "rotation"): G.qmul(G.qconj(rk2), ra)}
        # the foot's own children (toes, hoof) follow the source phase too
        kids = {i for i in range(len(g.nodes)) if _descends(g, i, an)}
        for ch in a["channels"]:
            nd, pth = ch["target"]["node"], ch["target"]["path"]
            if nd in kids and pth in slot:
                out[(nd, pth)] = src_loc[nd][slot[pth]]
        return out, clamped, A2

    def written(tg):
        """The channels as write_channels will write them (the harmonic trim included)."""
        tg = {key: np.array(v, float) for key, v in tg.items()}
        if harmonic_keep is not None:
            keep_low_harmonics(tg, grid, L, harmonic_keep)
        return tg

    solved = {}
    for c, target, _ in plan:
        solved[c["name"]] = solve(c, target)
    # clearance (2026-09-28): no planted chain goes below the Idle floor -- its whole limb (the hip's subtree, >= 0.5)
    # while it swings, its knee's subtree (>= 0.5: shin and foot) while it stands (2026-10-01: stance was judged by
    # its sole alone until hota_cove_corsair's RightLeg shin flesh sat 0.001 H under the floor its sole stood on and
    # ground_glb P2 refused the lifted plant; a standing thigh is the body clearance's, below). ground_glb stands the Move's lowest geometry on the floor, so any dip
    # lifts the whole loop and a foot near the floor band leaves it (P2 refused h3_hell_hound and
    # hota_cove_swashbuckler for stance soles 0.001-0.002 H under the floor: the sole is sized on the source pose and
    # its vertices' partial shin weights follow the IK). Measured on the pose as written (harmonic trim included); the
    # ankle target is raised by the deficit and re-solved, and a chain still under after CLEARANCE_ITERS is refused.
    # A chain that never dips keeps its keys bit for bit.
    limbs = {}
    for c, _, stance in plan:
        top = c["joints"][0]
        sub = [top] + [i for i in range(len(g.nodes)) if _descends(g, i, top)]
        limb = (body["W"] * np.isin(body["J"], sub)).sum(1) >= 0.5
        knee = c["joints"][1]
        ksub = [knee] + [i for i in range(len(g.nodes)) if _descends(g, i, knee)]
        shin = (body["W"] * np.isin(body["J"], ksub)).sum(1) >= 0.5
        limbs[c["name"]] = (limb, shin, stance)
    # body clearance (2026-10-01): every vertex the limb pass does not hold (a swinging limb, a standing shin) and no
    # tail owns (tail_clearance curls those) stays on or above the Idle floor too: raising an ankle cannot lift a
    # standing thigh or a hem that rides the pelvis. ground_glb stands the Move's lowest geometry
    # on the floor, so a robe hem under it lifts the planted soles off it (P2 refused hota_cove_sorceress: hem
    # vertices -0.057 H under the planted soles, the source Move's body already riding low). A deficit is cleared by
    # lifting the pelvis at that key (eating the plant's drop first, then above the source keys) and re-solving every
    # leg on it; the same secant step as the limb raise. Still under after CLEARANCE_ITERS: refused.
    tail_sub = set()
    for i, n in enumerate(g.names):
        if n and "Tail" in n:
            tail_sub.update([i] + [j for j in range(len(g.nodes)) if _descends(g, j, i)])
    tail_owned = (body["W"] * np.isin(body["J"], sorted(tail_sub))).sum(1) >= 0.5 if tail_sub \
        else np.zeros(len(body["W"]), bool)
    # a propFloor prop is cleared by prop_floor_glb.py's tilt after this stage, never by the pelvis (2026-10-01
    # h3_mummy: the staff foot on LeftHand dipped 0.028 H under the floor, the body clearance lifted the pelvis
    # 0.073 H on every Move key and the planted feet lost their reach, slip 0.82 against the 0.686 gate)
    if prop_bone is not None:
        if prop_bone not in g.names:
            raise SystemExit(f"propFloor.bone {prop_bone!r} is not a node of the rig")
        prop_owned = (body["W"] * (body["J"] == g.names.index(prop_bone))).sum(1) > 0.5
        tail_owned = tail_owned | prop_owned
    held = np.zeros((len(grid), len(body["W"])), bool)
    for c, _, stance in plan:
        limb, shin, _ = limbs[c["name"]]
        held |= np.where(stance[:, None], shin[None, :], limb[None, :])
    free = ~held & ~tail_owned[None, :]
    lift = np.zeros(len(grid))
    lift_step = np.zeros(len(grid))
    lift_d = np.zeros(len(grid))
    raise_by = {c["name"]: np.zeros(len(grid)) for c, _, _ in plan}
    # secant step (2026-09-30): a reach-clamped key lifts only part of each raise, so raising by the deficit alone
    # shrinks it geometrically and never reaches the tolerance (h3_basilisk RightArm: 3 clamped keys, 0.0003 H left
    # after 12 passes; h3_greater_basilisk 0.0001 H after 16). Each key's next raise is its deficit divided by the
    # lift its previous raise actually bought per unit raised. The first raise and a key that clears are unchanged.
    last_step = {c["name"]: np.zeros(len(grid)) for c, _, _ in plan}
    last_d = {c["name"]: np.zeros(len(grid)) for c, _, _ in plan}
    tol = CLEARANCE_TOL * height
    for it in range(CLEARANCE_ITERS + 1):
        tg = dict(targets)
        for nm, (kt, _, _) in solved.items():
            tg.update(kt)
        tw = written(tg)
        lw = {i: list(v) for i, v in loc.items()}
        for (nd, pth), v in tw.items():
            lw[nd][slot[pth]] = v
        hw = skin_heights(body, g.world(lw), range(len(grid))) - idle_floor
        worst = {}
        for c, target, stance in plan:
            limb, shin, _ = limbs[c["name"]]
            lo = np.where(stance, hw[:, shin].min(1), hw[:, limb].min(1))
            d = np.maximum(0.0, -lo)
            if d.max() > tol:
                worst[c["name"]] = (float(d.max()), int(d.argmax()))
                if it < CLEARANCE_ITERS:
                    nm = c["name"]
                    stepped = last_step[nm] > 0.0
                    gain = np.ones(len(grid))
                    gain[stepped] = (last_d[nm][stepped] - d[stepped]) / last_step[nm][stepped]
                    step = d / np.clip(gain, CLEARANCE_MIN_GAIN, 1.0)
                    last_step[nm], last_d[nm] = step, d
                    raise_by[nm] += step
                    t2 = target.copy()
                    t2[:, UPI] += raise_by[c["name"]]
                    solved[c["name"]] = solve(c, t2)
        lo_free = np.where(free, hw, np.inf).min(1)
        d = np.maximum(0.0, -np.where(np.isfinite(lo_free), lo_free, 0.0))
        if d.max() > tol:
            worst["body"] = (float(d.max()), int(d.argmax()))
            if it < CLEARANCE_ITERS:
                stepped = lift_step > 0.0
                gain = np.ones(len(grid))
                gain[stepped] = (lift_d[stepped] - d[stepped]) / lift_step[stepped]
                step = d / np.clip(gain, CLEARANCE_MIN_GAIN, 1.0)
                lift_step, lift_d = step, d
                lift += step
                set_pelvis(lift - drop)
                for c, target, _ in plan:
                    t2 = target.copy()
                    t2[:, UPI] += raise_by[c["name"]]
                    solved[c["name"]] = solve(c, t2)
        if not worst:
            break
    else:
        raise SystemExit("stride plant: a planted limb stays below the Idle floor after "
                         f"{CLEARANCE_ITERS} clearance passes: " + ", ".join(
                             f"{nm} {d / height:.4f} H at key {k}" for nm, (d, k) in sorted(worst.items())))
    for c, _, _ in plan:
        kt, clamped, A2 = solved[c["name"]]
        targets.update(kt)
        an = c["joints"][2]
        report[c["name"]]["reachClampedKeys"] = int(clamped.sum())
        if c["name"] in slides:
            l_mean = float(lg_len[c["name"]])
            report[c["name"]]["rootSlideMaxOverLeg"] = round(float(np.abs(slides[c["name"]]).max()) / l_mean, 4)
        report[c["name"]]["firstKeyAnkleShiftOverHeight"] = round(
            float(np.linalg.norm(A2[0] - mats[an][0, :3, 3])) / height, 4)
        if raise_by[c["name"]].max() > 0.0:
            report[c["name"]]["clearanceRaiseMaxOverHeight"] = round(float(raise_by[c["name"]].max()) / height, 5)
            report[c["name"]]["clearanceRaisedKeys"] = int((raise_by[c["name"]] > 0.0).sum())
    tail_rep = tail_clearance(g, body, loc, targets, written, slot, grid, idle_floor, CLEARANCE_TOL * height)
    if harmonic_keep is not None:
        keep_low_harmonics(targets, grid, L, harmonic_keep)
    write_channels(g, a, grid, targets)
    rep = {"mode": "plant", "chains": report, "plantedChains": [c["name"] for c, _, _ in plan], "keys": int(len(grid)),
           "cadence": round(_cadence, 4),
           "clipSeconds": round(L, 5), "sourceFirstKey": round(t0, 5),
           "strideRequiredOverHeight": round(stride_req / height, 4),
           "maxPelvisDropOverHeight": round(float(drop.max()) / height, 4)}
    if pelvis_hold is not None:
        rep["pelvisHoldOverHeight"] = pelvis_hold
        rep["pelvisDropHeldOverHeight"] = round(held_drop / height, 4)
    if trot_phase is not None:
        rep["trotPhase"] = trot_phase
    if lift.max() > 0.0:
        rep["bodyClearance"] = {"pelvisLiftMaxOverHeight": round(float(lift.max()) / height, 5),
                                "liftedKeys": int((lift > 0.0).sum())}
    if tail_rep:
        rep["tailCurl"] = tail_rep
    return rep


TAIL_CURL_MAX_DEG = 60.0                  # plant: most a tail root may be curled up to clear the Idle floor
TAIL_CURL_PASSES = 4                      # plant: curl re-solves on the pose as written
TAIL_CURL_SPREAD = 8                      # plant: the curl is widened over 1/this of the cycle on each side


def tail_clearance(g: Glb, body: dict, loc: dict, targets: dict, written, slot: dict, grid: np.ndarray,
                   idle_floor: float, tol: float) -> dict:
    """Tail clearance (2026-09-28): a floor-length tail rides with the hips, so the Move's own body bob and the plant's
    pelvis drop push it through the Idle floor the stance soles now stand on; ground_glb then stands the tail on the
    floor and refuses the plant (P2: h3_unicorn / h3_war_unicorn QTail_02 0.04-0.08 H under the soles, the source
    Move's tail already 0.02 H under the Idle floor with the hips bobbing 0.06 below Idle; h3_centaur_captain 0.04 H).
    Each tail root (a node named *Tail* whose parent is not) is curled about the world lateral axis at its own head,
    per key, by the least angle that keeps every vertex its subtree owns (weight >= 0.5) on or above the Idle floor,
    measured on the pose as written (harmonic trim included). The angle curve is widened by a raised-cosine max-filter
    over 1/TAIL_CURL_SPREAD of the cycle on each side, so the curl eases in and out instead of stepping. A tail that
    never dips keeps its keys bit for bit; one still under at TAIL_CURL_MAX_DEG is refused. Mutates targets."""
    names = g.names
    roots = [i for i, n in enumerate(names) if n and "Tail" in n
             and not (g.parent.get(i) is not None and "Tail" in (names[g.parent[i]] or ""))]
    out = {}
    n = len(grid)
    cyc = n - 1 if n > 1 else 1                  # grid[0] and grid[-1] are the same phase of the loop
    half = max(1, cyc // TAIL_CURL_SPREAD)
    win = 0.5 + 0.5 * np.cos(np.pi * np.arange(-half, half + 1) / (half + 1))
    lat = np.array([1.0, 0.0, 0.0])              # FORWARD x UP: the body's pitch axis
    for r in roots:
        p = g.parent.get(r)
        if p is None:
            continue
        sub = [r] + [i for i in range(len(g.nodes)) if _descends(g, i, r)]
        mask = (body["W"] * np.isin(body["J"], sub)).sum(1) >= 0.5
        if not mask.any():
            continue

        def pose(theta, base):
            """World mats with the root's local rotation curled by theta (radians, per key) from `base`."""
            tg = written(targets)
            lw = {i: list(v) for i, v in loc.items()}
            for (nd, pth), v in tg.items():
                lw[nd][slot[pth]] = v
            if np.any(theta != 0.0):
                mats0 = g.world(lw)
                qp = world_rot(mats0, p)
                qa = np.c_[np.outer(np.sin(theta / 2.0), lat), np.cos(theta / 2.0)]
                lw[r][1] = G.qnorm(G.qmul(G.qconj(qp), G.qmul(qa, G.qmul(qp, base))))
            return g.world(lw)

        def low(mats):
            return skin_heights(body, mats, range(n), mask).min(1) - idle_floor

        # 2026-10-11 h3_dread_knight: the curl is solved on the pose as written but composed onto the source
        # rotation, so stages that write() re-applies after it (strideMatch legDeltas) can leave a few mm under the
        # floor; re-solve on the as-written pose (each pass adds to the curl, aiming half a tolerance inside so it
        # does not creep up on the boundary from below), the same floor test on the result
        curls, final = [], None
        for _pass in range(TAIL_CURL_PASSES):
            base = np.array(written(targets).get((r, "rotation"), loc[r][1]), float)
            d0 = low(pose(np.zeros(n), base))
            if d0.min() >= -tol:
                if not curls:
                    break           # never dips: keys bit for bit
                final = d0
                break
            d00 = d0 if not curls else d00
            test = np.radians(10.0)
            dip = d0 < -tol
            up = low(pose(np.full(n, test), base))[dip].sum() >= low(pose(np.full(n, -test), base))[dip].sum()
            sgn = 1.0 if up else -1.0
            top = np.radians(TAIL_CURL_MAX_DEG)
            if np.any(low(pose(np.where(dip, sgn * top, 0.0), base))[dip] < -tol):
                raise SystemExit(f"stride plant: tail {names[r]} stays below the Idle floor curled {TAIL_CURL_MAX_DEG} deg "
                                 f"(deepest {-d0.min():.4f})")
            lo_, hi_ = np.zeros(n), np.where(dip, top, 0.0)
            for _ in range(18):
                mid = 0.5 * (lo_ + hi_)
                ok = low(pose(sgn * mid, base)) >= (-tol if _pass == 0 else -0.5 * tol)   # re-solves aim inside
                hi_ = np.where(dip & ok, mid, hi_)
                lo_ = np.where(dip & ~ok, mid, lo_)
            need = hi_[:cyc]
            th = np.zeros(cyc)
            for j, w in zip(range(-half, half + 1), win):
                th = np.maximum(th, np.roll(need, j) * w)
            th = np.r_[th, th[:1]] if n > cyc else th
            theta = sgn * th
            final = low(pose(theta, base))
            if final.min() < -tol:
                raise SystemExit(f"stride plant: tail {names[r]} curl leaves it {-final.min():.4f} under the Idle floor")
            qp = world_rot(pose(np.zeros(n), base), p)                     # parent frame is unchanged by the curl
            qa = np.c_[np.outer(np.sin(theta / 2.0), lat), np.cos(theta / 2.0)]
            src_q = np.array(targets.get((r, "rotation"), loc[r][1]), float)
            targets[(r, "rotation")] = G.qnorm(G.qmul(G.qconj(qp), G.qmul(qa, G.qmul(qp, src_q))))
            curls.append(theta)
        if not curls:
            continue
        final = low(pose(np.zeros(n), np.array(written(targets)[(r, "rotation")], float)))
        if final.min() < -tol:
            raise SystemExit(f"stride plant: tail {names[r]} curl (as written) leaves it {-final.min():.4f} under the "
                             "Idle floor")
        theta = np.sum(curls, 0); d0 = d00
        out[names[r]] = {"curlDeg": round(float(np.degrees(np.abs(theta).max())), 2),
                         "curledKeys": int((np.abs(theta) > 0.0).sum()), "sign": int(sgn),
                         "sourceDipOverFloor": round(float(d0.min()), 5)}
    return out


def unit_inputs(unit: str, glb: Path | None, move_speed: float | None, data: bytes | None = None):
    """(glb path, Glb, height, world scale, moveSpeed); the flier class is unit_flier(unit). `data`: the GLB's bytes
    in memory (an earlier delivery stage's output); `glb` then only names it."""
    p = glb or ROOT / "artifacts/homm3_def_retarget" / unit / f"{unit}_def_retarget.glb"
    g = Glb(data) if data is not None else Glb.load(p)
    h = body_height(g)
    scale = hex_target_height(unit) / h
    ms = move_speed if move_speed is not None else view_move_speed(unit)
    return p, g, h, scale, ms


def cmd_measure(args) -> int:
    p, g, h, scale, ms = unit_inputs(args.unit, args.glb, args.move_speed)
    why = unit_stride_exempt(args.unit)
    if why:
        res = {"unit": args.unit, "glb": str(p), "strideExempt": why, "chains": [c["name"] for c in chains_of(g)]}
    else:
        res = {"unit": args.unit, "glb": str(p), **measure(g, ms, scale, h, flier=unit_flier(args.unit))}
    res["stamp"] = g.json.get("asset", {}).get("extras", {}).get(STAMP)
    print(json.dumps(res, indent=1))
    return 0


def _apply_once(args, g: Glb, h: float, scale: float, ms: float, ratio: float, before: dict, include: frozenset):
    """One stride rewrite of g's Move, in place. Returns (transform report, gain)."""
    gain = None
    if args.mode == "plant":
        gain = None
        ground_rate = ms / (PLAYBACK * scale)          # body units the ground moves per second of clip time
        opt = unit_stride_options(args.unit)
        if "maxDrop" in opt:
            if args.max_drop != DEFAULT_MAX_DROP and args.max_drop != opt["maxDrop"]:
                raise SystemExit(f"{args.unit}: --max-drop {args.max_drop} disagrees with strideMatch.maxDrop {opt['maxDrop']}")
            args.max_drop = opt["maxDrop"]
        if "swingLift" in opt:
            args.lift = opt["swingLift"]
        rep = plant_transform(g, ground_rate, args.max_drop, h, args.max_excursion, args.lift, args.max_cadence,
                              harmonic_keep=opt.get("highHarmonicKeep"), include=include,
                              prop_bone=unit_prop_bone(args.unit), pelvis_hold=opt.get("pelvisHold"),
                              trot_phase=opt.get("trotPhase"), swing_curl=opt.get("swingCurl"))
        for k in STRIDE_KNOBS:
            if k in opt:
                rep[k] = opt[k]
        if opt:
            rep["strideMatchReason"] = opt["reason"]
    else:
        if unit_stride_options(args.unit):
            raise SystemExit(f"{args.unit}: strideMatch options apply to --mode plant only")
        # caps: an absolute gain, and the lengthened foot excursion no longer than vanilla's (native p90, per height)
        exc = max(v["excursion"] for v in before["limbs"].values())
        exc_cap = args.max_excursion * h / max(exc, 1e-9)
        gain = float(np.clip(ratio, 1.0 / args.max_gain, min(args.max_gain, exc_cap)))
        rep = stride_transform(g, gain, args.max_drop, h, args.lift, include=include)
        rep["excursionCapGain"] = round(exc_cap, 3)
    return rep, gain


def apply_bytes(args, data: bytes | None = None):
    """The stride-match stage, in memory: (StageResult, None) or (None, skip report) for a strideExempt unit or a
    HoMM3 flier. `args` is this module's parsed `apply` arguments (build_parser); `data` the input GLB's bytes (None:
    read args.glb or the canonical GLB). The sidecar names args.out or the input path, as the CLI writes it."""
    p, g, h, scale, ms = unit_inputs(args.unit, args.glb, args.move_speed, data)
    src = g.raw
    if STAMP in g.json.get("asset", {}).get("extras", {}):
        raise SystemExit(f"{args.unit}: already stride-matched")
    why = unit_stride_exempt(args.unit)
    if why:
        check_exempt_rig(args.unit, g, why)
        return None, {"unit": args.unit, "skipped": f"strideExempt: {why}"}
    before = measure(g, ms, scale, h, flier=unit_flier(args.unit))
    if before.get("flier"):
        return None, {"unit": args.unit, "skipped": before.get("reason"), "before": before}
    ratio = before["requiredOverActual"]
    # the plant set is chosen on the source Move (grounded_chains); a pelvis drop can bring an arm chain (a
    # quadruped's foreleg) into measure()'s floor band, where it is scored for slip without having been planted.
    # Re-plan from the source with it planted until the planted set equals the scored set; fail closed otherwise.
    # strideMatch.foreLegs: arm chains the unit config declares are front legs (a quadruped body on the humanoid rig)
    # are planted from the first pass; the source Move's hand joint can sit well above its own hoof (h3_mighty_gorgon)
    declared = frozenset(unit_stride_options(args.unit).get("foreLegs", ())) if args.mode == "plant" else frozenset()
    include: frozenset = declared
    for it in range(4):
        g = Glb(src)
        rep, gain = _apply_once(args, g, h, scale, ms, ratio, before, include)
        g2 = Glb(g.to_bytes())
        after = measure(g2, ms, scale, h, flier=False, planted=frozenset(rep["plantedChains"]))
        planted, scored = set(rep["plantedChains"]), set(after["grounded"])
        if scored == planted:
            break
        if not scored - planted:
            raise SystemExit(f"{args.unit}: planted {sorted(planted)} but only {sorted(scored)} are in the floor band "
                             "after the drop (a planted chain left the floor)")
        include = frozenset(include | scored)
    else:
        raise SystemExit(f"{args.unit}: plant set did not converge (planted {sorted(planted)}, scored {sorted(scored)})")
    rep["plantIterations"] = it + 1
    legd = unit_stride_options(args.unit).get("legDeltas") if args.mode == "plant" else None
    if legd:   # strideMatch.legDeltas: DEF-keypoint leg turns on top of the plant; slip is re-measured with them
        deltas, dsha, swp = load_leg_deltas(legd)
        plant_slip = after["slipRatio"]
        rep["legDeltas"] = {"table": legd, "sha256": dsha,
                            **apply_leg_deltas(g2, deltas, before["forwardAxis"], rep.get("chains"), swp)}
        g2 = Glb(g2.to_bytes())
        after = measure(g2, ms, scale, h, flier=False, planted=frozenset(rep["plantedChains"]))
        rep["legDeltas"].update(slipRatioPlant=plant_slip, slipRatioWithDeltas=after["slipRatio"])
        print(f"{args.unit}: legDeltas slip {plant_slip} (plant) -> {after['slipRatio']}", file=sys.stderr)
    if declared:
        rep["plantedDeclaredForeLegs"] = sorted(declared)
    if include - declared:
        rep["plantedAfterDrop"] = sorted(include - declared - set(before["grounded"]))
    if after["slipRatio"] > before["slipRatio"]:
        raise SystemExit(f"{args.unit}: stride match made slip worse ({before['slipRatio']} -> {after['slipRatio']})")
    stamp = {"schema": "homm3_def_retarget_stride_match.v1", "tool": "tools/homm3_def_retarget_delivery/stride_match_glb.py",
             "clip": MOVE, "moveSpeed": ms,
             "moveSpeedSource": "override:--move-speed" if args.move_speed is not None else move_speed_source(args.unit)["source"],
             "worldScale": round(scale, 5), "bodyHeight": round(h, 5),
             "requiredOverActual": ratio, "mode": args.mode, "gain": None if gain is None else round(gain, 4), "maxGain": args.max_gain, "maxDrop": args.max_drop,
             "residualRatio": after["requiredOverActual"], "slipRatioBefore": before["slipRatio"],
             "slipRatioAfter": after["slipRatio"], "transform": rep, "sourceGlbSha256": hashlib.sha256(src).hexdigest(),
             "proof": "generated artifact: Move keys rewritten offline; not built into a bundle, not in game"}
    if args.mode == "plant" and rep.get("highHarmonicKeep") is not None:
        stamp["strideShareBelowFull"] = {"residualRatio": after["requiredOverActual"],
                                         "why": rep["strideMatchReason"]}
    g2.json.setdefault("asset", {}).setdefault("extras", {})[STAMP] = stamp
    final = g2.to_bytes()
    out = args.out or p
    import stage_sidecar
    osha = hashlib.sha256(final).hexdigest()
    return stage_sidecar.result(
        final, src, "stride_match", stage_sidecar.record("homm3_def_retarget_stride_match.v1", args.unit, out,
                                                         stamp["sourceGlbSha256"], osha),
        {"unit": args.unit, "out": str(out), "glbSha256": osha, "before": before, "after": after,
         **{k: stamp[k] for k in ("mode", "gain", "requiredOverActual")}, "transform": rep}), None


def cmd_apply(args) -> int:
    res, skipped = apply_bytes(args)
    if res is None:
        print(json.dumps(skipped, indent=1) if "before" in skipped else json.dumps(skipped))
        return 3
    import stage_sidecar
    stage_sidecar.commit(args.out or res.sidecar["outputGlb"], res)
    print(json.dumps(res.report, indent=1))
    return 0


def check_glb(p: Path, max_slip: float) -> dict:
    """Re-measure a stride-matched GLB with the moveSpeed / scale its stamp recorded."""
    g = Glb.load(p)
    st = g.json.get("asset", {}).get("extras", {}).get(STAMP)
    if not st:
        raise SystemExit(f"{p}: not stride-matched (no {STAMP} stamp)")
    res = measure(g, st["moveSpeed"], st["worldScale"], st["bodyHeight"], flier=False)   # stamped = walker
    ok = (not res.get("airborne")) and res["slipRatio"] <= max_slip and res["requiredOverActual"] <= MAX_RATIO
    return {"glb": str(p), "ok": ok, "slipRatio": res.get("slipRatio"), "maxSlip": max_slip, "maxRatio": MAX_RATIO,
            "requiredOverActual": res.get("requiredOverActual"), "stampSlipRatioAfter": st["slipRatioAfter"]}


def gate_faults(unit: str, glb: Path) -> list[str]:
    """freeze_slice's stride gate on one GLB, as fault words: "slip" (pooled slip ratio over DEFAULT_MAX_SLIP) and
    "ratio" (required/actual stride over MAX_RATIO), measured at move_speed_source (normalized or Core view) and hex scale; a flier or a
    strideExempt unit (its rig checked) has none. A measurement that refuses raises, as it does at freeze."""
    _, g, h, scale, ms = unit_inputs(unit, Path(glb), None)
    why = unit_stride_exempt(unit)
    if why:
        check_exempt_rig(unit, g, why)
        return []
    res = measure(g, ms, scale, h, flier=unit_flier(unit))
    if res.get("airborne"):
        return []
    return [f.split()[0].rstrip(":") for f in
            stride_faults_after(unit, res["slipRatio"], res["requiredOverActual"], DEFAULT_MAX_SLIP, MAX_RATIO)]


def cmd_check(args) -> int:
    bad = 0
    for p in args.glbs:
        r = check_glb(Path(p), args.max_slip)
        print(json.dumps(r, default=lambda o: o.item() if hasattr(o, "item") else str(o)))
        bad += not r["ok"]
    return 1 if bad else 0


def build_parser() -> argparse.ArgumentParser:
    """The CLI's parser; fleet_rebuild.py parses ["apply", <unit>] with it, so the fused stage runs on the same defaults."""
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("measure", "apply"):
        s = sub.add_parser(name)
        s.add_argument("unit")
        s.add_argument("--glb", type=Path, help="input GLB (default: the canonical def_retarget GLB, in place)")
        s.add_argument("--move-speed", type=float, help="override the normalized / Core view moveSpeed (stamped as override)")
        if name == "apply":
            s.add_argument("--out", type=Path, help="output GLB (default: overwrite the input, like deyaw_glb.py)")
            s.add_argument("--mode", choices=("plant", "gain"), default="plant")
            s.add_argument("--max-gain", type=float, default=DEFAULT_MAX_GAIN)
            s.add_argument("--max-cadence", type=float, default=DEFAULT_MAX_CADENCE)
            s.add_argument("--max-drop", type=float, default=DEFAULT_MAX_DROP)
            s.add_argument("--max-excursion", type=float, default=DEFAULT_MAX_EXCURSION)
            s.add_argument("--lift", type=float, default=DEFAULT_LIFT)
    s = sub.add_parser("check")
    s.add_argument("glbs", nargs="+")
    s.add_argument("--max-slip", type=float, default=DEFAULT_MAX_SLIP)
    return ap


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return {"measure": cmd_measure, "apply": cmd_apply, "check": cmd_check}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
