#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from validate_custom_faction_manifests import Validation, load_json  # noqa: E402


DEFAULT_CONTRACTS_PATH = ROOT / "custom_factions" / "spell_cast_event_predicate_contracts.json"
DEFAULT_INVENTORY_PATH = ROOT / "custom_factions" / "custom_law_effect_plan_inventory.json"


def load_spell_cast_profiles(inventory_path: Path) -> dict[str, list[dict[str, Any]]]:
    inventory = load_json(inventory_path)
    rows = inventory.get("rows") if isinstance(inventory, dict) else None
    profiles: dict[str, list[dict[str, Any]]] = {}
    if not isinstance(rows, list):
        return profiles
    for row in rows:
        if not isinstance(row, dict):
            continue
        predicates = row.get("requiredPredicates")
        if not isinstance(predicates, list) or "RequiresSpellCastEvent" not in predicates:
            continue
        effect_key = row.get("effectKey")
        if isinstance(effect_key, str):
            profiles.setdefault(effect_key, []).append(row)
    return profiles


def validate_contracts(doc: Any, profiles: dict[str, list[dict[str, Any]]], validation: Validation) -> None:
    if not isinstance(doc, dict):
        validation.error("spell-cast event predicate contracts root must be an object")
        return
    if doc.get("schemaVersion") != 1:
        validation.error(f"spell-cast event predicate contracts schemaVersion must be 1, got {doc.get('schemaVersion')!r}")
    policy = doc.get("policy")
    if not isinstance(policy, dict):
        validation.error("policy must be an object")
    else:
        required_true = (
            "effectKeysMustMatchRequiresSpellCastEventProfiles",
            "genericAnySpellCastForbidden",
            "successfulCastMustBeSeparatedFromPreviewOrFailedCast",
            "heroCastMustBeSeparatedFromUnitAbilityCast",
            "spellSchoolOrSidClassificationMustUseExactTaxonomy",
            "runtimeProofStillRequiredForGameplay",
        )
        for key in required_true:
            if policy.get(key) is not True:
                validation.error(f"policy.{key} must be true")

    required_runtime = doc.get("requiredRuntimeProof")
    required_items = {
        "successful spell cast commit proof",
        "failed/preview cast exclusion proof",
        "caster law-owner correlation proof",
        "spell SID or school identity proof",
        "spell target/effect correlation proof",
        "cast-to-cooldown ordering proof",
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
        validation.error(f"{missing}: missing spell-cast event predicate contract")
    for extra in sorted(actual_keys - expected_keys):
        validation.error(f"{extra}: spell-cast event predicate contract has no exact RequiresSpellCastEvent profile")

    for effect_key, contract in sorted(contracts.items()):
        if not isinstance(contract, dict):
            validation.error(f"{effect_key}: contract must be an object")
            continue
        for field in ("castKinds", "correlationRequired", "forbiddenSubstitutes"):
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
        elif "proving" not in notes.lower() and "requires" not in notes.lower():
            validation.error(f"{effect_key}: notes must state the proof boundary")
        forbidden_text = "\n".join(
            str(item).lower() for item in contract.get("forbiddenSubstitutes", []) if isinstance(item, str)
        )
        if "any spell cast" not in forbidden_text:
            validation.error(f"{effect_key}: forbiddenSubstitutes must reject generic any-spell substitution")
        if "preview" not in forbidden_text and "spellbook open" not in forbidden_text:
            validation.error(f"{effect_key}: forbiddenSubstitutes must reject preview/open-spellbook substitution")
        cast_kinds = "\n".join(str(item).lower() for item in contract.get("castKinds", []) if isinstance(item, str))
        correlation = "\n".join(
            str(item).lower() for item in contract.get("correlationRequired", []) if isinstance(item, str)
        )
        if effect_key.startswith("tower.") and "tower law owner" not in correlation:
            validation.error(f"{effect_key}: Tower spell-cast contract must require Tower law owner correlation")
        if effect_key.startswith("inferno.") and not ("fire" in cast_kinds or "gating" in cast_kinds or "summon" in cast_kinds):
            validation.error(f"{effect_key}: Inferno spell-cast contract must include fire/gating/summon context")
        if effect_key.startswith("necropolis.") and "corpse" not in cast_kinds + correlation:
            validation.error(f"{effect_key}: Necropolis spell-cast contract must include corpse context")
        if effect_key.startswith("cove.") and "focus" not in correlation:
            validation.error(f"{effect_key}: Cove spell-cast contract must include Focus correlation")
        if effect_key.startswith("conflux.") and "elemental" not in cast_kinds + correlation:
            validation.error(f"{effect_key}: Conflux spell-cast contract must include elemental context")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contracts", type=Path, default=DEFAULT_CONTRACTS_PATH)
    parser.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY_PATH)
    args = parser.parse_args()

    validation = Validation()
    doc = load_json(args.contracts)
    profiles = load_spell_cast_profiles(args.inventory)
    validate_contracts(doc, profiles, validation)
    print(f"spell-cast event predicate contracts: {len(doc.get('contracts', {})) if isinstance(doc, dict) else 0} contract(s)")
    print(f"RequiresSpellCastEvent effect keys: {len(profiles)} unique key(s)")
    print(f"RequiresSpellCastEvent profile rows: {sum(len(rows) for rows in profiles.values())}")
    print(f"errors: {validation.errors}")
    if validation.warnings:
        print(f"warnings: {validation.warnings}")
    return 1 if validation.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
