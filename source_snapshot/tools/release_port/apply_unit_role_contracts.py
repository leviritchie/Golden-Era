#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "release_port"))

from validate_unit_role_contracts import (  # noqa: E402
    DEFAULT_CONTRACTS_PATH,
    DEFAULT_TAGS_PATH,
    load_ability_role_index,
    load_json,
    resolve_role_contract,
    validate_role_contracts,
)

sys.path.insert(0, str(ROOT / "tools"))
from validate_custom_faction_manifests import DEFAULT_MANIFEST_DIR, Validation  # noqa: E402


ROLE_FACTS = ("shooter", "melee")


def write_json(path: Path, doc: dict[str, Any]) -> None:
    path.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Apply exact sourceMechanicId/branchRole unit role contracts to custom_factions/unit_family_tags.json. "
            "This is static source authoring only, not runtime proof."
        )
    )
    parser.add_argument("--tags", type=Path, default=DEFAULT_TAGS_PATH)
    parser.add_argument("--contracts", type=Path, default=DEFAULT_CONTRACTS_PATH)
    parser.add_argument("--manifest-dir", type=Path, default=DEFAULT_MANIFEST_DIR)
    parser.add_argument("--check", action="store_true", help="Fail if tags would change instead of writing them.")
    args = parser.parse_args()

    tags = load_json(args.tags)
    contracts = load_json(args.contracts)
    ability_index = load_ability_role_index(args.manifest_dir)

    validation = Validation()
    validate_role_contracts(contracts, tags, ability_index, validation, require_tag_alignment=False)
    if validation.errors:
        for error in validation.errors:
            print(f"error: {error}", file=sys.stderr)
        return 1

    updated = json.loads(json.dumps(tags))
    updated["validationState"] = (
        "Conservative ontology facts are authored for exact custom unit SIDs. Shooter/melee facts are populated "
        "only when backed by custom_factions/unit_role_contracts.json joined through exact ability_overrides "
        "sourceMechanicId and branchRole metadata. These facts are not runtime-proven."
    )
    units = updated.get("units")
    if not isinstance(units, dict):
        print("error: unit tags document has no units object", file=sys.stderr)
        return 1

    applied = 0
    for sid, role in sorted(ability_index.items()):
        entry = units.get(sid)
        if not isinstance(entry, dict):
            continue
        resolved = resolve_role_contract(contracts, role["sourceMechanicId"], role["branchRole"])
        if resolved is None:
            continue
        for fact in ROLE_FACTS:
            value = resolved[fact]
            if value != "unknown" and entry.get(fact) != value:
                entry[fact] = value
                applied += 1

    before = json.dumps(tags, indent=2, ensure_ascii=False) + "\n"
    after = json.dumps(updated, indent=2, ensure_ascii=False) + "\n"
    if args.check:
        if before != after:
            print("error: unit role contracts are not applied to unit_family_tags.json", file=sys.stderr)
            return 1
        print("unit role contracts are already applied")
        return 0

    write_json(args.tags, updated)
    print(f"applied {applied} shooter/melee fact updates from {args.contracts} to {args.tags}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
