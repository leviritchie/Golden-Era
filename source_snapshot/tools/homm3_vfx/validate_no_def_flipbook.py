"""Gate (wired into the OfflineUnlockMod build, target ValidateHomm3NoDefFlipbookContract, 2026-09-27): no shipped or selected unit may deliver HoMM3 DEF-ripped effect pixels.

    python tools/homm3_vfx/validate_no_def_flipbook.py

Decision 2026-09-27 (user): every HoMM3 effect looks bad in the engine and is replaced by a vanilla-style redesign
(docs/homm3_vanilla_style_effects_rollout.md). HoMM3 decides what an effect depicts and when it fires; it never supplies
the pixels. So a row of an active def_retarget delivery selection (tools/homm3_def_retarget_delivery/*.json, schema
homm3_def_retarget_delivery_selection.v1, no supersededBy) whose unit-look spec
(tools/homm3_unit_look/units/<labSid>.json) has a defFlipbook layer must be vfxAuthority vanilla_style (its spec then
supersedes every defFlipbook layer; tools/homm3_vfx/vanilla_style_fx.py check proves that), unless the unit is on the
debt list tools/homm3_vfx/vanilla_style/def_flipbook_debt.json.

The debt list only shrinks:
  * every entry must still be debt (an entry for a unit that is now vanilla_style, or has no defFlipbook layer, or is
    in no active selection, fails: remove it);
  * the entry count may not exceed DEBT_CEILING below, which is lowered in the same change that removes entries;
    adding debt needs an explicit edit of this file, reviewed like any contract change.
A frozen unit that is not on the list and still ships defFlipbook layers fails.

Proof tier: source/static over committed selections and specs. Says nothing about the in-game look.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SELECTIONS = ROOT / "tools/homm3_def_retarget_delivery"
LOOK_SPECS = ROOT / "tools/homm3_unit_look/units"
DEBT = ROOT / "tools/homm3_vfx/vanilla_style/def_flipbook_debt.json"
DEBT_SCHEMA = "homm3_def_flipbook_debt.v1"
DEBT_CEILING = 0   # lower this with every removal; never raise it to make a build pass


def flipbook_layers(unit: str) -> list[str]:
    p = LOOK_SPECS / f"{unit}.json"
    if not p.is_file():
        return []
    spec = json.loads(p.read_text(encoding="utf-8"))
    return [l["id"] for l in spec.get("vfx", {}).get("layers", []) if l.get("type") == "defFlipbook"]


def active_rows() -> dict[str, list[tuple[str, dict]]]:
    out: dict[str, list[tuple[str, dict]]] = {}
    for p in sorted(SELECTIONS.glob("*.json")):
        sel = json.loads(p.read_text(encoding="utf-8"))
        if sel.get("schema") != "homm3_def_retarget_delivery_selection.v1" or sel.get("supersededBy"):
            continue
        for row in sel.get("units", []):
            out.setdefault(row["labSid"], []).append((p.name, row))
    return out


def check() -> tuple[int, int]:
    debt_doc = json.loads(DEBT.read_text(encoding="utf-8"))
    if debt_doc.get("schema") != DEBT_SCHEMA:
        raise SystemExit(f"FAIL: {DEBT.name} schema {debt_doc.get('schema')!r} != {DEBT_SCHEMA}")
    debt = {e["unit"]: e for e in debt_doc["units"]}
    if len(debt) != len(debt_doc["units"]):
        raise SystemExit("FAIL: duplicate units in the debt list")
    if len(debt) > DEBT_CEILING:
        raise SystemExit(f"FAIL: debt list has {len(debt)} units, ceiling {DEBT_CEILING}; the list only shrinks")
    rows = active_rows()
    errors, paid = [], 0
    for unit, sel_rows in sorted(rows.items()):
        fb = flipbook_layers(unit)
        if not fb:
            continue
        for name, row in sel_rows:
            if row.get("vfxAuthority") == "vanilla_style":
                continue
            if unit not in debt:
                errors.append(f"{name}: {unit} ships defFlipbook layers {fb} without vfxAuthority vanilla_style and "
                              f"is not on {DEBT.name}")
    for unit, e in sorted(debt.items()):
        fb = flipbook_layers(unit)
        live = [r for _, r in rows.get(unit, []) if r.get("vfxAuthority") != "vanilla_style"]
        if not fb or not live:
            errors.append(f"{DEBT.name}: {unit} is no longer debt (defFlipbook layers {fb}, unit_look rows "
                          f"{len(live)}); remove it and lower DEBT_CEILING")
            paid += 1
        if not isinstance(e.get("plan"), str) or not e["plan"].strip():
            errors.append(f"{DEBT.name}: {unit} needs a plan (draft spec path or the reason it waits)")
    if errors:
        raise SystemExit("FAIL:\n  " + "\n  ".join(errors))
    return len(debt), sum(1 for u in rows if flipbook_layers(u))


if __name__ == "__main__":
    n, total = check()
    print(f"no-def-flipbook: ok debt={n}/{DEBT_CEILING} selectedUnitsWithFlipbooks={total} "
          "proof=source/static; in-game look unproven")
    sys.exit(0)
