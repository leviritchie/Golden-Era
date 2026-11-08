#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from validate_custom_faction_manifests import Validation, load_json  # noqa: E402


DEFAULT_CONTRACTS_PATH = ROOT / "custom_factions" / "geometry_predicate_contracts.json"
DEFAULT_INVENTORY_PATH = ROOT / "custom_factions" / "custom_law_effect_plan_inventory.json"


def load_geometry_profiles(inventory_path: Path) -> dict[str, list[dict[str, Any]]]:
    inventory = load_json(inventory_path)
    rows = inventory.get("rows") if isinstance(inventory, dict) else None
    profiles: dict[str, list[dict[str, Any]]] = {}
    if not isinstance(rows, list):
        return profiles
    for row in rows:
        if not isinstance(row, dict):
            continue
        predicates = row.get("requiredPredicates")
        if not isinstance(predicates, list) or "RequiresGeometryPredicate" not in predicates:
            continue
        effect_key = row.get("effectKey")
        if isinstance(effect_key, str):
            profiles.setdefault(effect_key, []).append(row)
    return profiles


def validate_contracts(doc: Any, profiles: dict[str, list[dict[str, Any]]], validation: Validation) -> None:
    if not isinstance(doc, dict):
        validation.error("geometry predicate contracts root must be an object")
        return
    if doc.get("schemaVersion") != 1:
        validation.error(f"geometry predicate contracts schemaVersion must be 1, got {doc.get('schemaVersion')!r}")
    policy = doc.get("policy")
    if not isinstance(policy, dict):
        validation.error("policy must be an object")
    else:
        required_true = (
            "effectKeysMustMatchRequiresGeometryPredicateProfiles",
            "genericPositionBonusForbidden",
            "meleeAndRangedFormationRowsMustShareExactEffectKeySemantics",
            "geometryMustBeCorrelatedToCurrentActionPayload",
            "runtimeProofStillRequiredForGameplay",
        )
        for key in required_true:
            if policy.get(key) is not True:
                validation.error(f"policy.{key} must be true")

    required_runtime = doc.get("requiredRuntimeProof")
    required_items = {
        "current action actor hex proof",
        "current action target hex proof",
        "adjacency and line/range predicate proof",
        "multi-target/area target discriminator proof",
        "melee versus ranged action classifier proof",
        "geometry-to-law-owner idempotence proof",
    }
    if not isinstance(required_runtime, list) or not required_runtime:
        validation.error("requiredRuntimeProof must be a non-empty list")
    else:
        actual_items = {item for item in required_runtime if isinstance(item, str)}
        for missing in sorted(required_items - actual_items):
            validation.error(f"requiredRuntimeProof missing {missing!r}")
        for item in required_runtime:
            if not isinstance(item, str) or not item:
                validation.error(f"requiredRuntimeProof entries must be non-empty strings, got {item!r}")

    contracts = doc.get("contracts")
    if not isinstance(contracts, dict) or not contracts:
        validation.error("contracts must be a non-empty object")
        return

    expected_keys = set(profiles)
    actual_keys = set(contracts)
    for missing in sorted(expected_keys - actual_keys):
        validation.error(f"{missing}: missing geometry predicate contract")
    for extra in sorted(actual_keys - expected_keys):
        validation.error(f"{extra}: geometry predicate contract has no exact RequiresGeometryPredicate profile")

    for effect_key, rows in sorted(profiles.items()):
        handlers = {row.get("handler") for row in rows}
        if handlers != {"battle.melee-formation", "battle.ranged-formation"}:
            validation.error(
                f"{effect_key}: geometry profile rows must cover exactly melee and ranged formation handlers, "
                f"got {sorted(str(h) for h in handlers)}"
            )

    for effect_key, contract in sorted(contracts.items()):
        if not isinstance(contract, dict):
            validation.error(f"{effect_key}: contract must be an object")
            continue
        for field in ("geometryKinds", "correlationRequired", "forbiddenSubstitutes"):
            value = contract.get(field)
            if not isinstance(value, list) or not value:
                validation.error(f"{effect_key}: {field} must be a non-empty list")
                continue
            for item in value:
                if not isinstance(item, str) or not item:
                    validation.error(f"{effect_key}: {field} entries must be non-empty strings")
        notes = contract.get("notes")
        if not isinstance(notes, str) or not notes:
            validation.error(f"{effect_key}: notes must be a non-empty string")
        elif "requires proving" not in notes.lower():
            validation.error(f"{effect_key}: notes must state the proof boundary with 'requires proving'")
        forbidden_text = "\n".join(str(item).lower() for item in contract.get("forbiddenSubstitutes", []) if isinstance(item, str))
        if "any adjacent" not in forbidden_text and "any shooter" not in forbidden_text:
            validation.error(f"{effect_key}: forbiddenSubstitutes must reject generic adjacency/position substitution")
        geometry_text = "\n".join(str(item).lower() for item in contract.get("geometryKinds", []) if isinstance(item, str))
        correlation_text = "\n".join(str(item).lower() for item in contract.get("correlationRequired", []) if isinstance(item, str))
        if effect_key.startswith("dungeon.") and not ("boxed" in geometry_text and "flanked" in geometry_text):
            validation.error(f"{effect_key}: Dungeon geometry contract must include boxed and flanked target semantics")
        if effect_key.startswith("fortress.") and "defensive" not in geometry_text:
            validation.error(f"{effect_key}: Fortress geometry contract must include defensive-line semantics")
        if effect_key.startswith("inferno.") and not ("gated" in geometry_text and "entry" in correlation_text):
            validation.error(f"{effect_key}: Inferno geometry contract must include gated entry correlation")
        if effect_key.startswith("rampart.") and not ("shooter" in geometry_text and "avenger" in correlation_text):
            validation.error(f"{effect_key}: Rampart geometry contract must include shooter and Avenger context")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contracts", type=Path, default=DEFAULT_CONTRACTS_PATH)
    parser.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY_PATH)
    args = parser.parse_args()

    validation = Validation()
    doc = load_json(args.contracts)
    profiles = load_geometry_profiles(args.inventory)
    validate_contracts(doc, profiles, validation)
    print(f"geometry predicate contracts: {len(doc.get('contracts', {})) if isinstance(doc, dict) else 0} contract(s)")
    print(f"RequiresGeometryPredicate effect keys: {len(profiles)} unique key(s)")
    print(f"RequiresGeometryPredicate profile rows: {sum(len(rows) for rows in profiles.values())}")
    print(f"errors: {validation.errors}")
    if validation.warnings:
        print(f"warnings: {validation.warnings}")
    return 1 if validation.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
