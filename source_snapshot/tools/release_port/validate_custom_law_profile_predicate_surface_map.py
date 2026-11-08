#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INVENTORY = ROOT / "custom_factions" / "custom_law_effect_plan_inventory.json"
DEFAULT_MATRIX = ROOT / "custom_factions" / "gameplay_surface_evidence_matrix.json"
DEFAULT_MAP = ROOT / "custom_factions" / "custom_law_profile_predicate_surface_map.json"

ALLOWED_STATUSES = {"mapped", "partial", "missing", "rejected"}


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8-sig") as handle:
        return json.load(handle)


def inventory_predicates(inventory: Any) -> set[str]:
    result: set[str] = set()
    rows = inventory.get("rows") if isinstance(inventory, dict) else None
    if not isinstance(rows, list):
        raise ValueError("effect plan inventory has no rows list")
    for row in rows:
        if not isinstance(row, dict):
            continue
        predicates = row.get("requiredPredicates")
        if not isinstance(predicates, list):
            continue
        for predicate in predicates:
            if isinstance(predicate, str) and predicate:
                result.add(predicate)
    return result


def surface_ids(matrix: Any) -> set[str]:
    surfaces = matrix.get("surfaces") if isinstance(matrix, dict) else None
    if not isinstance(surfaces, dict):
        raise ValueError("gameplay surface evidence matrix has no surfaces object")
    return {str(key) for key in surfaces}


def validate(map_doc: Any, predicates: set[str], surfaces: set[str]) -> list[str]:
    errors: list[str] = []
    if not isinstance(map_doc, dict):
        return ["predicate surface map root must be an object"]
    if map_doc.get("schemaVersion") != 1:
        errors.append("schemaVersion must be 1")
    entries = map_doc.get("predicates")
    if not isinstance(entries, dict):
        return errors + ["predicates must be an object"]
    mapped = {str(key) for key in entries}
    missing = sorted(predicates - mapped)
    extra = sorted(mapped - predicates)
    if missing:
        errors.append("predicate surface map missing predicates: " + ", ".join(missing))
    if extra:
        errors.append("predicate surface map has predicates not used by inventory: " + ", ".join(extra))
    for predicate in sorted(mapped & predicates):
        entry = entries.get(predicate)
        if not isinstance(entry, dict):
            errors.append(f"{predicate}: entry must be an object")
            continue
        status = entry.get("status")
        if status not in ALLOWED_STATUSES:
            errors.append(f"{predicate}: status must be one of {sorted(ALLOWED_STATUSES)}, got {status!r}")
        refs = entry.get("surfaceIds")
        if not isinstance(refs, list):
            errors.append(f"{predicate}: surfaceIds must be a list")
            continue
        if status in {"mapped", "partial"} and not refs:
            errors.append(f"{predicate}: status={status} requires at least one surfaceId")
        if status in {"missing", "rejected"} and refs:
            errors.append(f"{predicate}: status={status} must not carry surfaceIds")
        for index, surface_id in enumerate(refs):
            if not isinstance(surface_id, str) or not surface_id:
                errors.append(f"{predicate}: surfaceIds[{index}] must be a non-empty string")
            elif surface_id not in surfaces:
                errors.append(f"{predicate}: surfaceId does not exist in gameplay matrix: {surface_id}")
        notes = entry.get("notes")
        if not isinstance(notes, str) or not notes.strip():
            errors.append(f"{predicate}: notes must explain the mapping boundary")
        if status == "mapped" and isinstance(notes, str) and "unproven" in notes.lower():
            errors.append(f"{predicate}: status=mapped must not describe an unproven runtime dependency; use partial")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate source-prepared law profile predicates are traceable to gameplay surface evidence entries."
    )
    parser.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY)
    parser.add_argument("--matrix", type=Path, default=DEFAULT_MATRIX)
    parser.add_argument("--map", type=Path, default=DEFAULT_MAP)
    args = parser.parse_args()

    try:
        predicates = inventory_predicates(load_json(args.inventory))
        surfaces = surface_ids(load_json(args.matrix))
        errors = validate(load_json(args.map), predicates, surfaces)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"profile predicate surface map validation failed: {exc}")
        return 1
    if errors:
        print("profile predicate surface map validation failed:")
        for error in errors:
            print(f"  - {error}")
        return 1
    print(f"profile predicate surface map validation passed ({len(predicates)} predicate(s))")
    print("Note: static surface traceability does not prove runtime law behavior.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
