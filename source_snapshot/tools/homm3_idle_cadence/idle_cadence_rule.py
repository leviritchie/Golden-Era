"""The one idle-cadence rule for DEF-retarget GLBs, its exceptions table, and the outlier detector.

Approved for the full roster by the user on 2026-09-25 (docs/homm3_idle_cadence.md).

Measured 2026-09-25 (artifacts/homm3_idle_cadence/):
- native Olden Era battle idles (104 `22.Idle` overrides of `_Battle_Unit_Anim_ctrl_v2`):
  loop 3.27 s median (p10 2.13, p90 7.61), one motion beat per 2.67 s median
  (p10 1.60, p90 5.03), mean local joint angular speed 14.3 deg/s median (p10 5.6, p90 28.3);
- our def_retarget `Unit_Idle` (257 GLBs): one DEF cycle keyed at 12 fps, loop 0.833 s median,
  one beat per loop, 31.5 deg/s median, smaller amplitude than native (5.6 vs 9.1 deg).

Rule: one global time scale = native median beat period / our median loop length
(2.667 / 0.833 = 3.2), applied to the idle key times with loop-periodic cubic easing
(retime_idle.py). Per-unit departures live ONLY in idle_exceptions.json (unit -> treatment +
reason). The detector below flags outliers mechanically; the rollout refuses any flagged unit
that has no table entry, so an outlier is never retimed by default without a recorded decision.

Input (pipeline order: def_retarget build -> emphasis -> idle retime -> unit look):
resolve_input(unit) is the ONE place the retime's input GLB is chosen. It is the unit's
def_retarget GLB as the unit-look lane resolves it (look.resolve_source): the superseded un-prebaked
original when the GLB on disk is look's stamped delivery, else the GLB itself. The emphasis pass
(docs/homm3_def_retarget_emphasis.md) delivers by replacing that build GLB, so its clips are what
this reads; emphasis_errors() pins that order against the emphasis stamp. Currency is keyed on anim_sha256 - a hash of every animation's channels, samplers and
accessor values - not on size/mtime: an emphasis rewrite of any clip makes a retimed output stale
(the rollout regenerates it, the validator fails it), while a look texture bake, which changes no
animation, does not.

Treatments (idle_exceptions.json "units"):
- "rule": the global factor, recorded because the detector flags the unit (reason says why the
  rule still stands, e.g. amplitude, not tempo, is the defect);
- "factor": a different global factor for this unit ("factor" key);
- "wingDecouple": body at the global factor, bones whose name contains any of "wingBones" (and
  their descendants) play their source loop "wingCycles" times over the stretched idle;
- "exclude": not retimed; the delivery keeps the source idle.
"""
from __future__ import annotations

import json
import os

import numpy as np

IDLE_CLIP = "Unit_Idle"
NATIVE_BEAT_PERIOD_S = 2.667
OURS_MEDIAN_LOOP_S = 0.833
IDLE_TIME_SCALE = 3.2
RESAMPLE_HZ = 30.0
EXCEPTIONS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "idle_exceptions.json")
TREATMENTS = {"rule", "factor", "wingDecouple", "exclude"}

# Detector thresholds, all from the native 22.Idle distribution (native_idles.json).
NATIVE_MIN_MEDIAN_AMP_DEG = 3.13       # quietest native idle's median-bone swing
NATIVE_P95_MEAN_SPEED = 41.82          # p95 over native idles of the median-bone mean speed
NATIVE_P95_PEAK_P90 = 330.7            # p95 over native idles of the p90-bone peak speed
FLUTTER_MIN_AMP_DEG = 15.0             # wing bones (p90) swing at least this much ...
FLUTTER_MIN_BEATS = 2                  # ... and beat at least twice per DEF idle loop


UPSTREAM_ANIMATION_STAGES = ("def_retarget build (tools/homm3_def_retarget)",
                             "emphasis (tools/homm3_def_retarget_emphasis; replaces the build GLB when delivered)")


def resolve_input(unit: str) -> tuple[str, str]:
    """(path, kind) of the GLB the idle retime reads for this unit; kind is 'glb' or 'superseded'.
    Delegates the stamp logic to the unit-look lane so both lanes agree on which file is the source."""
    import sys
    look_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "homm3_unit_look")
    if look_dir not in sys.path:
        sys.path.insert(0, look_dir)
    import look  # noqa: E402
    import spec  # noqa: E402
    data, kind = look.resolve_source(unit)          # raises look.StageError on a broken stamp
    if kind == "superseded":
        stamp = look.read_stamp(unit)
        return str(look.superseded_path(unit, stamp["sourceGlbSha256"])), kind
    return str(spec.glb_path(unit)), kind


EMPHASIS_EXTRAS_KEY = "homm3DefRetargetEmphasis"


def emphasis_expectation(unit: str):
    """The asset.extras the retime input must carry when the emphasis lane has delivered this unit
    (its stamp says 'emphasised'), else None. Reads artifacts/homm3_def_retarget_emphasis/<unit>/stamp.json."""
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    p = os.path.join(root, "artifacts", "homm3_def_retarget_emphasis", unit, "stamp.json")
    if not os.path.exists(p):
        return None
    with open(p, encoding="utf-8") as f:
        st = json.load(f)
    return st.get("glbExtras") if st.get("decision") == "emphasised" else None


def emphasis_errors(unit: str, js: dict) -> list[str]:
    """Pipeline order check: the retime input carries the emphasis stamp's extras when emphasis has
    delivered the unit. A missing or different stamp means the input predates the emphasis pass."""
    want = emphasis_expectation(unit)
    have = (js.get("asset", {}).get("extras") or {}).get(EMPHASIS_EXTRAS_KEY)
    if want is not None and have != want:
        return [f"{unit}: emphasis has delivered this unit but the retime input carries "
                f"{EMPHASIS_EXTRAS_KEY}={have!r}, not the stamp's glbExtras; the input predates the emphasis pass"]
    return []


def anim_sha256(js: dict, raw) -> str:
    """Hash of every animation (names, channel targets, interpolation, input/output accessor values).
    raw(i) -> packed bytes of accessor i. Independent of accessor numbering and buffer layout."""
    import hashlib
    h = hashlib.sha256()
    for an in js.get("animations", []):
        h.update(json.dumps([an.get("name"), [[c["sampler"], c["target"].get("node"), c["target"]["path"]]
                                             for c in an["channels"]]]).encode())
        for s in an["samplers"]:
            h.update(s.get("interpolation", "LINEAR").encode())
            for k in ("input", "output"):
                a = js["accessors"][s[k]]
                h.update(f"{a['componentType']}{a['type']}{a['count']}".encode())
                h.update(raw(s[k]))
    return h.hexdigest()


def describe() -> dict:
    return {"clip": IDLE_CLIP, "idleTimeScale": IDLE_TIME_SCALE, "resampleHz": RESAMPLE_HZ,
            "easing": "loop-periodic time-parameterised Catmull-Rom through every original key",
            "nativeBeatPeriodS": NATIVE_BEAT_PERIOD_S, "oursMedianLoopS": OURS_MEDIAN_LOOP_S,
            "exceptions": os.path.basename(EXCEPTIONS_PATH)}


def load_exceptions(path: str = EXCEPTIONS_PATH) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def table_errors(table: dict) -> list[str]:
    errs = []
    if set(table) - {"schema", "note", "units"} or table.get("schema") != "homm3_idle_cadence.exceptions.v1":
        errs.append("exceptions table: bad schema or unknown top-level keys")
    for unit, e in table.get("units", {}).items():
        allowed = {"treatment", "reason", "flags", "factor", "wingBones", "wingCycles"}
        if set(e) - allowed:
            errs.append(f"{unit}: unknown keys {sorted(set(e) - allowed)}")
        t = e.get("treatment")
        if t not in TREATMENTS:
            errs.append(f"{unit}: unknown treatment {t!r}")
        if not str(e.get("reason", "")).strip():
            errs.append(f"{unit}: empty reason")
        if t == "factor" and not (isinstance(e.get("factor"), (int, float)) and 1.0 <= e["factor"] <= 6.0):
            errs.append(f"{unit}: factor treatment needs 1.0 <= factor <= 6.0")
        if t != "factor" and "factor" in e:
            errs.append(f"{unit}: 'factor' only belongs to the factor treatment")
        if t == "wingDecouple":
            if not (isinstance(e.get("wingCycles"), int) and 2 <= e["wingCycles"] <= 8):
                errs.append(f"{unit}: wingDecouple needs an integer wingCycles in 2..8")
            if not (isinstance(e.get("wingBones"), list) and e["wingBones"] and all(isinstance(b, str) and b for b in e["wingBones"])):
                errs.append(f"{unit}: wingDecouple needs a non-empty wingBones list")
        elif "wingCycles" in e or "wingBones" in e:
            errs.append(f"{unit}: wingCycles/wingBones only belong to wingDecouple")
        if not isinstance(e.get("flags", []), list):
            errs.append(f"{unit}: flags must be a list")
    return errs


def treatment_for(unit: str, table: dict) -> dict:
    e = table.get("units", {}).get(unit)
    if e is None:
        return {"treatment": "rule", "factor": IDLE_TIME_SCALE, "wingCycles": None, "source": "rule"}
    t = e["treatment"]
    return {"treatment": t, "factor": e.get("factor", IDLE_TIME_SCALE) if t == "factor" else IDLE_TIME_SCALE,
            "wingCycles": e.get("wingCycles"), "wingBones": e.get("wingBones"), "flags": e.get("flags", []),
            "reason": e["reason"], "source": "exceptions"}


def wing_nodes(js: dict, patterns: list[str]) -> list[int]:
    """Node indices whose name contains any pattern (case-insensitive), plus their descendants."""
    pats = [p.lower() for p in patterns]
    hit = {i for i, n in enumerate(js["nodes"]) if any(p in n.get("name", "").lower() for p in pats)}
    stack = list(hit)
    while stack:
        for c in js["nodes"][stack.pop()].get("children", []):
            if c not in hit:
                hit.add(c); stack.append(c)
    return sorted(hit)


def cycles_for(js: dict, tr: dict) -> dict:
    if tr["treatment"] != "wingDecouple":
        return {}
    nodes = wing_nodes(js, tr["wingBones"])
    if not nodes:
        raise KeyError(f"wingDecouple: no node matches {tr['wingBones']}")
    return {n: tr["wingCycles"] for n in nodes}


def detect(rots: dict, length: float) -> tuple[list[str], dict]:
    """Outlier classes for one source idle ({bone: (T,4)} at 60 Hz). Returns (flags, metrics)."""
    from idle_metrics import cadence
    allm = cadence(rots, length)
    wing = {k: v for k, v in rots.items() if "wing" in k.lower()}
    wm = cadence(wing, length) if wing else None
    flags = []
    if allm["movingBones"] == 0:
        flags.append("static")
    else:
        if allm["amplitudeDeg"]["p90"] < NATIVE_MIN_MEDIAN_AMP_DEG:
            flags.append("nearStatic")
        if allm["angSpeedDegS"]["median"] / IDLE_TIME_SCALE > NATIVE_P95_MEAN_SPEED or \
                allm["peakAngSpeedDegS"]["p90"] / IDLE_TIME_SCALE > NATIVE_P95_PEAK_P90:
            flags.append("fastAfterRule")
    if wm and wm["movingBones"] and wm["amplitudeDeg"]["p90"] >= FLUTTER_MIN_AMP_DEG and wm["beats"] >= FLUTTER_MIN_BEATS:
        flags.append("wingFlutter")
    return flags, {"all": allm, "wing": wm}


def required_decision(flags: list[str]) -> bool:
    return bool(flags)
