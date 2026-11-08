"""Per-unit gate exceptions the user approved by name (unit config "gateExceptions"), pinned by magnitude.

    "gateExceptions": {"<gate>": {"<fault key>": {"value": <measured>, "reason": "<defect>; user-approved ..."}}}

gate is one of ground / freeze / articulation / stride, and the fault key is the key fleet_rebuild.gate_faults
compares runs by:
  ground        ground_check.fault_key, "<clip>:<check word>"            (Move:sinks, Death:dead, Hips steps ...)
  freeze        "<clip>:<check word>" of a flyer_articulation.freeze_check fault  (Unit_ShootFront:holds)
  articulation  the first word of a flyer_articulation.gate fault          (jittery, wings, body, legs)
  stride        slip / ratio of freeze_slice's stride gate (stride_match_glb.stride_faults_after)
value is the fault's measured number as the gate reports it (the first number after the key words; stride: the
slipRatio / requiredOverActual measure, 4 decimals). A fault is excused only while it is no worse than that pin at
the gate's own reporting precision: same sign and no larger magnitude, or for articulation wings / legs (a floor
whose shortfall grows as the number falls) no smaller. A listed key whose check passes is a stale exception and is a
fault itself, so the list only shrinks.

Only the gates read this (ground_check.ground_check, flyer_articulation.freeze_check / gate, the stride gate); no
build stage does, and no threshold moves. Anything malformed fails closed. Proof tier: source/static.
"""
from __future__ import annotations

import json
import math
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
UNITS = ROOT / "tools/homm3_def_retarget/units"
GATES = ("ground", "freeze", "articulation", "stride")
LOWER_IS_WORSE = {("articulation", "wings"), ("articulation", "legs")}
STRIDE_KEYS = ("slip", "ratio")
ONE_WORD = ("articulation", "stride")          # gates whose fault key is the fault's first word
_NUM = re.compile(r"[-+]?\d+(?:\.\d+)?")


def _parse(unit: str, raw) -> dict:
    """The validated table {gate: {key: {"value": float, "reason": str}}} ({} when the config has none)."""
    if raw is None:
        return {}
    where = f"{unit}: gateExceptions (tools/homm3_def_retarget_delivery/gate_exceptions.py)"
    if not isinstance(raw, dict) or not raw:
        raise SystemExit(f"{where} must be a non-empty object of gates, got {raw!r}")
    out = {}
    for gate, rows in raw.items():
        if gate not in GATES:
            raise SystemExit(f"{where}: unknown gate {gate!r} (one of {', '.join(GATES)})")
        if not isinstance(rows, dict) or not rows:
            raise SystemExit(f"{where}.{gate} must be a non-empty object of fault keys, got {rows!r}")
        out[gate] = {}
        for key, row in rows.items():
            ok_key = key in STRIDE_KEYS if gate == "stride" else (
                re.fullmatch(r"[A-Za-z_]+", key) if gate == "articulation" else re.fullmatch(r"[A-Za-z_]+:[A-Za-z]+", key))
            if not ok_key:
                raise SystemExit(f"{where}.{gate}: key {key!r} is not a {gate} fault key")
            if not isinstance(row, dict) or set(row) != {"value", "reason"}:
                raise SystemExit(f"{where}.{gate}.{key} must be exactly {{value, reason}}, got {row!r}")
            v, why = row["value"], row["reason"]
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
                raise SystemExit(f"{where}.{gate}.{key}: value must be the measured number, got {v!r}")
            if not (isinstance(why, str) and why.strip()):
                raise SystemExit(f"{where}.{gate}.{key}: needs a non-empty reason naming the defect")
            out[gate][key] = {"value": float(v), "reason": why}
    return out


def exceptions(unit: str | None, gate: str) -> dict:
    """{key: {"value", "reason"}} of one gate for one unit ({} for None, a unit without a config, or no entry)."""
    if gate not in GATES:
        raise SystemExit(f"gate_exceptions: unknown gate {gate!r}")
    if unit is None:
        return {}
    p = UNITS / f"{unit}.json"
    if not p.is_file():
        return {}
    return _parse(unit, json.loads(p.read_text(encoding="utf-8")).get("gateExceptions")).get(gate, {})


def fault_key(gate: str, fault: str) -> str:
    w = fault.split()
    return w[0].rstrip(":") if gate in ONE_WORD else f"{w[0]}:{w[1]}"


def fault_value(gate: str, fault: str) -> float | None:
    """The measured number of a fault: the first number after its key words (None when there is none)."""
    rest = " ".join(fault.split()[1 if gate in ONE_WORD else 2:])
    m = _NUM.search(rest)
    return float(m.group()) if m else None


def within(gate: str, key: str, value: float | None, pin: float) -> bool:
    """value no worse than pin (same sign, no larger magnitude; wings / legs: no smaller)."""
    if value is None:
        return False
    if (gate, key) in LOWER_IS_WORSE:
        return value >= pin
    return (value >= 0) == (pin >= 0) and abs(value) <= abs(pin)


def apply(unit: str | None, gate: str, faults: list[str]) -> tuple[list[str], list[dict]]:
    """(faults left, excused records). A pinned key whose fault is worse stays a fault (with its pin named); a pinned
    key with no fault at all becomes a stale-exception fault."""
    ex = exceptions(unit, gate)
    if not ex:
        return list(faults), []
    left, excused, seen = [], [], set()
    for f in faults:
        k = fault_key(gate, f)
        row = ex.get(k)
        if row is None:
            left.append(f)
            continue
        seen.add(k)
        v = fault_value(gate, f)
        if within(gate, k, v, row["value"]):
            excused.append({"key": k, "value": v, "pin": row["value"], "reason": row["reason"], "fault": f})
        else:
            left.append(f"{f} [worse than its gate exception pin {row['value']:g}]")
    left += [f"{k}: stale gate exception (the check passes; remove it from {unit}'s gateExceptions.{gate})"
             for k in ex if k not in seen]
    return left, excused


def stride_exceptions(unit: str) -> dict[str, tuple[float, str]]:
    """{"slip" | "ratio": (pinned measured value, reason)} for freeze_slice's stride gate ({} when none)."""
    return {k: (r["value"], r["reason"]) for k, r in exceptions(unit, "stride").items()}


def stride_faults_after(unit: str, slip: float, ratio: float, max_slip: float, max_ratio: float) -> list[str]:
    """freeze_slice's stride gate after the unit's exceptions: "slip <v>" / "ratio <v>" over the gate's limit and
    not excused by a pin at least that large (the measures are 4-decimal), a pinned one gone worse (its pin named),
    and a stale-exception fault per pinned key whose check passes. Empty = the gate passes."""
    raw = ([f"slip {slip}"] if slip > max_slip else []) + ([f"ratio {ratio}"] if ratio > max_ratio else [])
    return apply(unit, "stride", raw)[0]
