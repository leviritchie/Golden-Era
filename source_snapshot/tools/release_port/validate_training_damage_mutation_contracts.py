#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from validate_custom_faction_manifests import Validation, load_json  # noqa: E402


DEFAULT_CONTRACTS_PATH = ROOT / "custom_factions" / "training_damage_mutation_contracts.json"
DEFAULT_INVENTORY_PATH = ROOT / "custom_factions" / "custom_law_effect_plan_inventory.json"


def load_training_damage_profiles(inventory_path: Path) -> dict[str, dict[str, Any]]:
    inventory = load_json(inventory_path)
    rows = inventory.get("rows") if isinstance(inventory, dict) else None
    profiles: dict[str, dict[str, Any]] = {}
    if not isinstance(rows, list):
        return profiles
    for row in rows:
        if not isinstance(row, dict) or row.get("family") != "TrainingDamage":
            continue
        effect_key = row.get("effectKey")
        if isinstance(effect_key, str):
            profiles[effect_key] = row
    return profiles


def validate_contracts(doc: Any, profiles: dict[str, dict[str, Any]], validation: Validation) -> None:
    if not isinstance(doc, dict):
        validation.error("training damage mutation contracts root must be an object")
        return
    if doc.get("schemaVersion") != 1:
        validation.error(f"training damage mutation contracts schemaVersion must be 1, got {doc.get('schemaVersion')!r}")
    policy = doc.get("policy")
    if not isinstance(policy, dict) or policy.get("effectKeysMustMatchTrainingDamageProfiles") is not True:
        validation.error("training damage mutation contracts must require exact TrainingDamage effectKey coverage")

    allowed_value = doc.get("allowedMutationKinds")
    if not isinstance(allowed_value, list) or not allowed_value:
        validation.error("allowedMutationKinds must be a non-empty list")
        allowed: set[str] = set()
    else:
        allowed = set()
        for kind in allowed_value:
            if not isinstance(kind, str) or not kind:
                validation.error(f"allowedMutationKinds entry must be a non-empty string, got {kind!r}")
                continue
            if kind in allowed:
                validation.error(f"duplicate allowed mutation kind: {kind}")
            allowed.add(kind)

    contracts = doc.get("contracts")
    if not isinstance(contracts, dict) or not contracts:
        validation.error("contracts must be a non-empty object")
        return
    expected_keys = set(profiles)
    actual_keys = set(contracts)
    for missing in sorted(expected_keys - actual_keys):
        validation.error(f"{missing}: missing mutation contract for TrainingDamage profile")
    for extra in sorted(actual_keys - expected_keys):
        validation.error(f"{extra}: mutation contract has no exact TrainingDamage profile")

    for effect_key, contract in sorted(contracts.items()):
        if not isinstance(contract, dict):
            validation.error(f"{effect_key}: contract must be an object")
            continue
        kind = contract.get("mutationKind")
        if kind not in allowed:
            validation.error(f"{effect_key}: mutationKind {kind!r} is not allowed")
        for field in ("direction", "mutationPoint", "cleanup", "notes"):
            if not isinstance(contract.get(field), str) or not contract.get(field):
                validation.error(f"{effect_key}: {field} must be a non-empty string")
        required_runtime = contract.get("requiredRuntimeProof")
        if not isinstance(required_runtime, list) or not required_runtime:
            validation.error(f"{effect_key}: requiredRuntimeProof must be a non-empty list")
        else:
            for item in required_runtime:
                if not isinstance(item, str) or not item:
                    validation.error(f"{effect_key}: requiredRuntimeProof entries must be non-empty strings")
        numeric_inputs = contract.get("numericInputs")
        if not isinstance(numeric_inputs, list):
            validation.error(f"{effect_key}: numericInputs must be a list")
        profile = profiles.get(effect_key)
        if profile is None:
            continue
        values = profile.get("values") if isinstance(profile.get("values"), dict) else {}
        if kind in {"damage-percent-scalar", "attacker-damage-reduction", "gated-entry-damage-scalar"}:
            if "DamagePercentBonus" not in values:
                validation.error(f"{effect_key}: {kind} requires profile DamagePercentBonus")
        if kind == "target-stat-debuff" and "DefenseDebuffPerHit" not in values:
            validation.error(f"{effect_key}: target-stat-debuff requires profile DefenseDebuffPerHit")
        if kind == "temporary-resource-credit" and "TemporaryManaPerCorpse" not in values:
            validation.error(f"{effect_key}: temporary-resource-credit requires profile TemporaryManaPerCorpse")
        if kind == "wounded-speed-buff" and "SpeedDelta" not in values:
            validation.error(f"{effect_key}: wounded-speed-buff requires profile SpeedDelta")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contracts", type=Path, default=DEFAULT_CONTRACTS_PATH)
    parser.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY_PATH)
    args = parser.parse_args()

    validation = Validation()
    doc = load_json(args.contracts)
    profiles = load_training_damage_profiles(args.inventory)
    validate_contracts(doc, profiles, validation)
    print(f"training damage mutation contracts: {len(doc.get('contracts', {})) if isinstance(doc, dict) else 0} contract(s)")
    print(f"training damage profiles: {len(profiles)} profile(s)")
    print(f"errors: {validation.errors}")
    if validation.warnings:
        print(f"warnings: {validation.warnings}")
    return 1 if validation.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
