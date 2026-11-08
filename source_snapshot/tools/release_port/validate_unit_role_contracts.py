#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from validate_custom_faction_manifests import DEFAULT_MANIFEST_DIR, Validation, load_json  # noqa: E402


DEFAULT_TAGS_PATH = ROOT / "custom_factions" / "unit_family_tags.json"
DEFAULT_CONTRACTS_PATH = ROOT / "custom_factions" / "unit_role_contracts.json"
ABILITY_OVERRIDES_DIR = ROOT / "custom_factions" / "ability_overrides"
ROLE_VALUES = {"yes", "no", "unknown"}
ROLE_FACTS = ("shooter", "melee")


def load_ability_role_index(_manifest_dir: Path) -> dict[str, dict[str, str]]:
    index: dict[str, dict[str, str]] = {}
    for path in sorted(ABILITY_OVERRIDES_DIR.glob("homm3_*.json")):
        doc = load_json(path)
        unit_overrides = doc.get("unitOverrides") if isinstance(doc, dict) else None
        if not isinstance(unit_overrides, dict):
            continue
        for sid, entry in sorted(unit_overrides.items()):
            if not isinstance(entry, dict):
                continue
            source_mechanic_id = entry.get("sourceMechanicId")
            branch_role = entry.get("branchRole")
            if isinstance(source_mechanic_id, str) and isinstance(branch_role, str):
                index[sid] = {
                    "sourceMechanicId": source_mechanic_id,
                    "branchRole": branch_role,
                    "sourceFile": str(path.relative_to(ROOT)),
                }
    return index


def resolve_role_contract(contracts: dict[str, Any], source_mechanic_id: str, branch_role: str) -> dict[str, str] | None:
    line_contracts = contracts.get("lineContracts")
    if not isinstance(line_contracts, dict):
        return None
    contract = line_contracts.get(source_mechanic_id)
    if not isinstance(contract, dict):
        return None

    resolved = {
        "shooter": contract.get("shooter", "unknown"),
        "melee": contract.get("melee", "unknown"),
    }
    branch_roles = contract.get("branchRoles")
    if isinstance(branch_roles, dict):
        branch_contract = branch_roles.get(branch_role)
        if isinstance(branch_contract, dict):
            for fact in ROLE_FACTS:
                if fact in branch_contract:
                    resolved[fact] = branch_contract[fact]
    return resolved


def validate_role_value(context: str, value: Any, validation: Validation) -> None:
    if value not in ROLE_VALUES:
        validation.error(f"{context}: role value must be one of {sorted(ROLE_VALUES)}, got {value!r}")


def validate_role_contracts(
    contracts: Any,
    tags: Any,
    ability_index: dict[str, dict[str, str]],
    validation: Validation,
    require_tag_alignment: bool = True,
) -> None:
    if not isinstance(contracts, dict):
        validation.error("unit role contracts root must be an object")
        return
    if contracts.get("schemaVersion") != 1:
        validation.error(f"unit role contracts schemaVersion must be 1, got {contracts.get('schemaVersion')!r}")

    line_contracts = contracts.get("lineContracts")
    if not isinstance(line_contracts, dict):
        validation.error("unit role contracts lineContracts must be an object")
        return

    known_source_ids = {entry["sourceMechanicId"] for entry in ability_index.values()}
    for source_id, contract in sorted(line_contracts.items()):
        if source_id not in known_source_ids:
            validation.error(f"{source_id}: no exact ability_overrides sourceMechanicId")
        if not isinstance(contract, dict):
            validation.error(f"{source_id}: contract must be an object")
            continue
        for fact in ROLE_FACTS:
            validate_role_value(f"{source_id}.{fact}", contract.get(fact, "unknown"), validation)
        branch_roles = contract.get("branchRoles")
        if branch_roles is not None and not isinstance(branch_roles, dict):
            validation.error(f"{source_id}.branchRoles must be an object when present")
        if isinstance(branch_roles, dict):
            known_branch_roles = {
                entry["branchRole"]
                for entry in ability_index.values()
                if entry["sourceMechanicId"] == source_id
            }
            for branch_role, branch_contract in sorted(branch_roles.items()):
                if branch_role not in known_branch_roles:
                    validation.error(f"{source_id}.{branch_role}: no exact ability_overrides branchRole")
                if not isinstance(branch_contract, dict):
                    validation.error(f"{source_id}.{branch_role}: branch contract must be an object")
                    continue
                for fact in ROLE_FACTS:
                    if fact in branch_contract:
                        validate_role_value(f"{source_id}.{branch_role}.{fact}", branch_contract[fact], validation)

    if not require_tag_alignment:
        return

    units = tags.get("units") if isinstance(tags, dict) else None
    if not isinstance(units, dict):
        validation.error("unit family tags units must be an object")
        return

    checked = 0
    for sid, role in sorted(ability_index.items()):
        expected = resolve_role_contract(contracts, role["sourceMechanicId"], role["branchRole"])
        if expected is None:
            continue
        entry = units.get(sid)
        if not isinstance(entry, dict):
            validation.error(f"{sid}: missing unit_family_tags entry for role contract")
            continue
        for fact in ROLE_FACTS:
            value = expected[fact]
            if value == "unknown":
                continue
            checked += 1
            actual = entry.get(fact)
            if actual != value:
                validation.error(
                    f"{sid}.{fact}: expected {value!r} from {role['sourceMechanicId']} "
                    f"/ {role['branchRole']}, got {actual!r}"
                )

    if checked == 0:
        validation.error("unit role contracts did not produce any concrete shooter/melee checks")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Validate source-authored unit role contracts against exact ability_overrides sourceMechanicId/branchRole "
            "metadata and unit_family_tags.json."
        )
    )
    parser.add_argument("--tags", type=Path, default=DEFAULT_TAGS_PATH)
    parser.add_argument("--contracts", type=Path, default=DEFAULT_CONTRACTS_PATH)
    parser.add_argument("--manifest-dir", type=Path, default=DEFAULT_MANIFEST_DIR)
    args = parser.parse_args()

    validation = Validation()
    contracts = load_json(args.contracts)
    tags = load_json(args.tags)
    ability_index = load_ability_role_index(args.manifest_dir)
    validate_role_contracts(contracts, tags, ability_index, validation)
    print(f"unit role contracts: {len(contracts.get('lineContracts', {})) if isinstance(contracts, dict) else 0} line contracts")
    print(f"ability override role index: {len(ability_index)} exact unit entries")
    print(f"errors: {validation.errors}")
    if validation.warnings:
        print(f"warnings: {validation.warnings}")
    return 1 if validation.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
