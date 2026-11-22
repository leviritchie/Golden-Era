"""Single owner of h3_* UnitView attackTimeBefore / attackTimeAfter (the attack contact and projectile release).

Native battle code applies melee damage or launches the projectile ``attackTimeBefore[animationIndex]`` seconds
into the attack state and ends the attack ``attackTimeAfter[animationIndex]`` later. h3_* rows inherited both arrays
from their Olden Era donors, whose clips have nothing to do with the DEF-retargeted clips that ship (centaur line:
hit at 1.23 s on a 0.667 s clip, ranger arrow at 2.34 s on a 1.083 s shot). The measured times live in
custom_factions/contracts/homm3_attack_timing.json (tools/homm3_def_retarget_delivery/attack_timing.py); this pass
writes them into every slot a row's default/alternative/counter attacks use, with the slot -> clip map of the owned
skinned lab build (0 -> Unit_AttackFront, 1 -> Unit_ShootFront, else Unit_AttackFront). Fused Conflux rows use
their host's clips. Slots no attack uses keep their values. Runs after assign_homm3_attack_animation_slots.
Validator: tools/validate_homm3_attack_timing.py.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

REPO_ROOT = Path(__file__).resolve().parents[2]
TIMING_TABLE = REPO_ROOT / "custom_factions" / "contracts" / "homm3_attack_timing.json"
SCHEMA = "homm3_attack_timing.v1"
ATTACK_LISTS = ("defaultAttacks", "alternativeAttacks", "counterAttacks")


def load_table(path: Path = TIMING_TABLE) -> dict[str, Any]:
    doc = json.loads(path.read_text(encoding="utf-8"))
    if doc.get("schema") != SCHEMA:
        raise RuntimeError(f"{path}: schema {doc.get('schema')!r} != {SCHEMA}")
    return doc


def attacks(value: Any) -> list[dict]:
    if isinstance(value, list):
        return [a for a in value if isinstance(a, dict)]
    return [value] if isinstance(value, dict) else []


def slot_clip(clips: dict[str, Any], index: int) -> dict[str, Any]:
    if index == 1 and "Unit_ShootFront" in clips:
        return clips["Unit_ShootFront"]
    return clips["Unit_AttackFront"]


def timing_unit(doc: dict[str, Any], sid: str) -> dict[str, Any] | None:
    units = doc["units"]
    return units.get(sid) or units.get(doc.get("fusionHosts", {}).get(sid, ""))


def expected_slots(doc: dict[str, Any], row: dict[str, Any]) -> dict[int, tuple[float, float]] | None:
    """animationIndex -> (before, after) for every slot the row's attacks use; None when the row is not measured."""
    unit = timing_unit(doc, str(row.get("id", "")))
    if unit is None:
        return None
    out = {}
    for key in ATTACK_LISTS:
        for a in attacks(row.get(key)):
            idx = int(a.get("animationIndex", 0))
            c = slot_clip(unit["clips"], idx)
            out[idx] = (float(c["hit"]), float(c["after"]))
    return out


def assign_homm3_attack_timings(
    output: dict[str, bytes], notes: list[str], write_json: Callable[[Any], bytes]
) -> None:
    doc = load_table()
    changed_rows, unmeasured = 0, []
    for name in sorted(output):
        if not (name.startswith("DB/units/units_views/") and name.endswith("_v.json")
                and Path(name).name.startswith("h3_")):
            continue
        view = json.loads(output[name].decode("utf-8-sig"))
        changed = False
        for row in view.get("array") or []:
            if not isinstance(row, dict) or not str(row.get("id", "")).startswith("h3_"):
                continue
            slots = expected_slots(doc, row)
            if slots is None:
                unmeasured.append(str(row.get("id")))
                continue
            before = list(row.get("attackTimeBefore") or [])
            after = list(row.get("attackTimeAfter") or [])
            for idx, (b, a) in slots.items():
                while len(before) <= idx:
                    before.append(before[-1] if before else b)
                while len(after) <= idx:
                    after.append(after[-1] if after else a)
                before[idx], after[idx] = b, a
            if before != row.get("attackTimeBefore") or after != row.get("attackTimeAfter"):
                row["attackTimeBefore"], row["attackTimeAfter"] = before, after
                changed = True
                changed_rows += 1
        if changed:
            output[name] = write_json(view)
    notes.append(f"time h3_* attack contact/shot release from the shipped clips: {changed_rows} view row(s) changed"
                 + (f"; unmeasured (donor timings kept): {', '.join(sorted(unmeasured))}" if unmeasured else ""))
