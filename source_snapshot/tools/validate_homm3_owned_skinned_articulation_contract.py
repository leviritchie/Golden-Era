"""Owned skinned DEF-retarget deliveries must articulate: wings beat and legs swing, the body is not bounced like a toy.

    python tools/validate_homm3_owned_skinned_articulation_contract.py [-v]

For every built delivery GLB of every selection (tools/homm3_def_retarget_delivery/*.json,
<out>/<labSid>/delivered_idle_retimed.glb), Unit_Move is measured by
tools/homm3_def_retarget_delivery/flyer_articulation.py (bone rotations, one rule shared with the vanilla
reference) and gated by its `gate()`:
  * winged units, by the rule flyer_articulation.wing_rule() names (stamped in the notes): flatFloor (no row in
    tools/homm3_def_retarget_delivery/reference/def_wing_range.json): wingRange and wingSwing >= WING_SWING_MIN;
    defRow: wingRange >= DEF_RANGE_SHARE x the DEF-measured rangeDeg in place of the flat floor (user-approved
    2026-09-27); defRowUpperBound: a row whose share falls under the floor is judged on its bracket's upper end;
    body rotation / wing swing <= FLYER_TOY_MAX;
  * legged units without wings: leg swing relative to the body >= LEG_SWING_MIN;
  * move_rule() "teleportMove" (flier table movementTeleporting AND a 1-frame DEF Move) skips only the two swing
    floors above; jitter and the freeze gate (MoveStart/MoveEnd carry the vanish/appear) still apply.
Frozen deliveries that fail and were frozen before this gate are named, with a reason, in
tools/homm3_owned_skinned_articulation_debt.json, keyed by selection, labSid and the frozen idleRetimedGlbSha256:
a re-freeze changes the sha and is gated again, and an entry whose unit now passes or is gone fails (the list
only shrinks). freeze_slice.py refuses new freezes by the same gate.
Every clip of every frozen delivery also passes flyer_articulation.freeze_check (a pose held FREEZE_RUN_MAX or more
DEF frames while the DEF moves; the retimed Idle is measured on <out>/<labSid>/inputs/look_delivered.glb). It has no
debt list: a frozen stall is refrozen, never excused.
Every frozen delivery is measured by ground_check.ground_check (feet on the floor per clip, no Hips step beyond the
DEF, the dead body on the floor; DEF allowance from the DEF bottom-row curve, stamped with the DEF frames' sha1).
Deliveries frozen before that gate that fail it are pinned in tools/homm3_owned_skinned_ground_debt.json by
selection, labSid and idleRetimedGlbSha256 with the failing (clip, check, value) list measured at pinning: a current
fault outside that list fails, an entry whose unit now passes or was refrozen fails (the list only shrinks).
Proof tier: generated artifact (read-only measurement of built GLBs).
"""
from __future__ import annotations

import json
import os
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SELECTIONS = ROOT / "tools/homm3_def_retarget_delivery"
DEBT = ROOT / "tools/homm3_owned_skinned_articulation_debt.json"
GROUND_DEBT = ROOT / "tools/homm3_owned_skinned_ground_debt.json"
sys.path.insert(0, str(SELECTIONS))
from flyer_articulation import GATE_CLIP, freeze_check, gate, glb_clips, move_rule, teleport_reference_errors, wing_rule  # noqa: E402
from ground_check import fault_key, ground_check_cached, store_ground_cache  # noqa: E402
from fleet_census import SOURCE_UNIT  # noqa: E402


def source_unit(lab_sid: str) -> str:
    """The DEF retarget unit a lab sid is built from (its master sequence and configs live under that id)."""
    return SOURCE_UNIT.get(lab_sid, lab_sid)


def ground_rows(key, row, ground, gdebt, used, errors, notes):
    bad, rec = ground
    d = gdebt.get(key)
    if rec["exempt"]:
        notes.append(f"{key[0]}/{key[1]}: ground exempt ({rec['exempt']}), measured {len(rec['clips'])} clips")
    if not bad:
        if d:
            errors.append(f"{key[0]}/{key[1]}: passes the ground gate now; remove its ground debt entry")
            used.add(key)
        return
    if d and d.get("idleRetimedGlbSha256") == row["frozen"]["idleRetimedGlbSha256"]:
        used.add(key)
        extra = sorted({fault_key(b) for b in bad} - set(d["faults"]))
        if extra:
            errors.append(f"{key[0]}/{key[1]}: ground faults outside its debt entry: {extra}")
        else:
            notes.append(f"{key[0]}/{key[1]}: ground debt: {'; '.join(bad)}")
        return
    errors.append(f"{key[0]}/{key[1]}: off the ground (tools/homm3_def_retarget_delivery/ground_check.py): {'; '.join(bad)}")


def measure(unit: str, glb: Path) -> tuple[list[str], dict | None, tuple[list[str], dict], dict]:
    """Per-unit GLB work (freeze gate, ground gate, the gated clip's metrics), run in a worker process: it is pure
    measurement of one built GLB and dominates the runtime, so units fan out across cores. Fresh ground-cache
    entries come back to the parent, the cache file's only writer."""
    fbad, _ = freeze_check(unit, glb, glb.parent / "inputs/look_delivered.glb")
    try:
        gbad, grec, fresh = ground_check_cached(unit, glb, persist=False)
    except SystemExit as e:      # e.g. "grounding": false without its stated reason: a fault, pinnable as debt
        gbad, grec, fresh = [f"config {e}"], {"exempt": None}, {}
    return fbad, glb_clips(glb).get(GATE_CLIP), (gbad, grec), fresh


def main() -> int:
    verbose = "-v" in sys.argv
    errors: list[str] = []
    notes: list[str] = []
    errors += [f"teleport effect reference: {e}" for e in teleport_reference_errors()]
    debt = json.loads(DEBT.read_text(encoding="utf-8"))
    entries = {(d["selection"], d["labSid"]): d for d in debt["entries"]}
    gdebt = {(d["selection"], d["labSid"]): d for d in json.loads(GROUND_DEBT.read_text(encoding="utf-8"))["entries"]}
    used, gused = set(), set()
    rows = []
    for sel_path in sorted(SELECTIONS.glob("*.json")):
        sel = json.loads(sel_path.read_text(encoding="utf-8"))
        if sel.get("schema") != "homm3_def_retarget_delivery_selection.v1":
            continue
        for row in sel["units"]:
            key = (sel_path.stem, row["labSid"])
            glb = ROOT / sel["out"] / row["labSid"] / "delivered_idle_retimed.glb"
            if not glb.is_file():
                notes.append(f"{key[0]}/{key[1]}: not built yet")
                continue
            rows.append((key, glb, row))
    workers = max(1, min(8, (os.cpu_count() or 2) - 2))
    with ProcessPoolExecutor(max_workers=workers) as pool:
        measured = list(pool.map(measure, [source_unit(r["labSid"]) for _, _, r in rows], [g for _, g, _ in rows],
                                 chunksize=4))
    store_ground_cache({k: v for *_, fresh in measured for k, v in fresh.items()})
    for (key, glb, row), (fbad, m, ground, _) in zip(rows, measured):
        errors += [f"{key[0]}/{key[1]}: frozen pose while the DEF moves: {b}" for b in fbad]
        ground_rows(key, row, ground, gdebt, gused, errors, notes)
        if m is None:
            errors.append(f"{key[0]}/{key[1]}: no {GATE_CLIP} clip to measure")
            continue
        bad = gate(m, source_unit(row["labSid"]))
        wr = f" wingRule={wing_rule(source_unit(row['labSid']))}" if m.get("wingBones") else ""
        wr += f" moveRule={move_rule(source_unit(row['labSid']))}"
        notes.append(f"{key[0]}/{key[1]}: {m}{wr}")
        d = entries.get(key)
        if not bad:
            if d:
                errors.append(f"{key[0]}/{key[1]}: passes the gate now; remove its debt entry")
                used.add(key)
            continue
        if d and d.get("idleRetimedGlbSha256") == row["frozen"]["idleRetimedGlbSha256"]:
            used.add(key)
            notes.append(f"{key[0]}/{key[1]}: debt ({d['status']}): {'; '.join(bad)}")
            continue
        errors.append(f"{key[0]}/{key[1]}: under-articulated {GATE_CLIP}: {'; '.join(bad)}")
    for key in set(entries) - used:
        errors.append(f"debt entry {key[0]}/{key[1]} names no current failing frozen delivery; remove it")
    for key in set(gdebt) - gused:
        errors.append(f"ground debt entry {key[0]}/{key[1]} names no current failing frozen delivery; remove it")
    if verbose or errors:
        for n in notes:
            print("  " + n)
    if errors:
        for e in errors:
            print("FAIL " + e)
        return 1
    print(f"homm3 owned skinned articulation contract OK ({len(notes)} checks, {len(used)} debt entries, "
          f"{len(gused)} ground debt entries)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
