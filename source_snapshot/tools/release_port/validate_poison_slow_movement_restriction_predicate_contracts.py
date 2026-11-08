#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
from validate_custom_faction_manifests import Validation, load_json  # noqa: E402

DEFAULT_CONTRACTS_PATH = ROOT / "custom_factions" / "poison_slow_movement_restriction_predicate_contracts.json"
DEFAULT_INVENTORY_PATH = ROOT / "custom_factions" / "custom_law_effect_plan_inventory.json"
PREDICATE = "RequiresPoisonSlowMovementRestriction"


def load_profiles(path: Path) -> list[dict[str, Any]]:
    inventory = load_json(path)
    rows = inventory.get("rows") if isinstance(inventory, dict) else None
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict) and PREDICATE in (row.get("requiredPredicates") or [])]


def profile_effect_keys(rows: list[dict[str, Any]]) -> set[str]:
    return {row["effectKey"] for row in rows if isinstance(row.get("effectKey"), str)}


def validate_contracts(doc: Any, profiles: list[dict[str, Any]], validation: Validation) -> None:
    if not isinstance(doc, dict):
        validation.error("poison/slow/movement-restriction predicate contracts root must be an object")
        return
    if doc.get("schemaVersion") != 1:
        validation.error(f"schemaVersion must be 1, got {doc.get('schemaVersion')!r}")
    policy = doc.get("policy") if isinstance(doc.get("policy"), dict) else {}
    for key in (
        "effectKeysMustMatchRequiresPoisonSlowMovementRestrictionProfiles",
        "spellSchoolFamilyOnly",
        "fortressOnly",
        "poisonSlowMovementRestrictionRequired",
        "genericNegativeStatusSubstituteForbidden",
        "classificationAloneIsNotLiveStatusProof",
        "runtimeProofStillRequiredForGameplay",
    ):
        if policy.get(key) is not True:
            validation.error(f"policy.{key} must be true")
    if sorted(doc.get("allowedFactions") or []) != ["homm3_fortress"]:
        validation.error("allowedFactions must be exactly ['homm3_fortress']")
    if doc.get("allowedFamily") != "SpellSchool":
        validation.error("allowedFamily must be SpellSchool")
    required_runtime = set(doc.get("requiredRuntimeProof") or [])
    for item in (
        "hero spell cast commit proof",
        "affected target identity proof",
        "live poison status query proof",
        "live slow status query proof",
        "live movement restriction status query proof",
        "status owner and receiver correlation proof",
        "spell taxonomy to live status ordering proof",
        "law-owner side correlation proof",
        "idempotent status extension application proof",
    ):
        if item not in required_runtime:
            validation.error(f"requiredRuntimeProof missing {item!r}")
    contracts = doc.get("contracts")
    if not isinstance(contracts, dict) or not contracts:
        validation.error("contracts must be a non-empty object")
        return
    expected = profile_effect_keys(profiles)
    for missing in sorted(expected - set(contracts)):
        validation.error(f"{missing}: missing contract")
    for extra in sorted(set(contracts) - expected):
        validation.error(f"{extra}: contract has no exact {PREDICATE} profile")
    for row in profiles:
        effect_key = row.get("effectKey")
        if row.get("family") != "SpellSchool":
            validation.error(f"{effect_key}: {PREDICATE} must remain SpellSchool")
        if row.get("factionSid") != "homm3_fortress":
            validation.error(f"{effect_key}: faction must be homm3_fortress")
        predicates = set(row.get("requiredPredicates") or [])
        for companion in ("RequiresNativeTerrainOrAdjacency", "RequiresSpellCastEvent"):
            if companion not in predicates:
                validation.error(f"{effect_key}: profile missing companion predicate {companion}")
    for effect_key, contract in sorted(contracts.items()):
        if not isinstance(contract, dict):
            validation.error(f"{effect_key}: contract must be an object")
            continue
        kinds = contract.get("requiredStatusOrSpellKinds")
        if not isinstance(kinds, list) or not kinds:
            validation.error(f"{effect_key}: requiredStatusOrSpellKinds must be a non-empty list")
            kinds = []
        kind_text = "\n".join(str(item).lower() for item in kinds if isinstance(item, str))
        for token in ("poison", "slow", "movement-restriction"):
            if token not in kind_text:
                validation.error(f"{effect_key}: requiredStatusOrSpellKinds must include {token!r}")
        forbidden = contract.get("forbiddenSubstitutes")
        if not isinstance(forbidden, list) or not forbidden:
            validation.error(f"{effect_key}: forbiddenSubstitutes must be a non-empty list")
            forbidden = []
        forbidden_text = "\n".join(str(item).lower() for item in forbidden if isinstance(item, str))
        for phrase in (
            "generic negative status counted as poison slow movement restriction",
            "spell taxonomy classification counted without live target status or committed spell effect proof",
            "terrain or adjacency predicate counted as poison slow movement restriction",
        ):
            if phrase not in forbidden_text:
                validation.error(f"{effect_key}: forbiddenSubstitutes missing {phrase!r}")
        profile_preds = set().union(*(row.get("requiredPredicates") or [] for row in profiles if row.get("effectKey") == effect_key))
        for predicate in contract.get("companionPredicates", []):
            if predicate not in profile_preds:
                validation.error(f"{effect_key}: companion predicate {predicate!r} is not present on profile rows")
        notes = contract.get("notes")
        if not isinstance(notes, str) or "live" not in notes.lower() or "static" not in notes.lower():
            validation.error(f"{effect_key}: notes must state static/live boundary")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contracts", type=Path, default=DEFAULT_CONTRACTS_PATH)
    parser.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY_PATH)
    args = parser.parse_args()
    validation = Validation()
    doc = load_json(args.contracts)
    profiles = load_profiles(args.inventory)
    validate_contracts(doc, profiles, validation)
    print(f"poison/slow/movement-restriction predicate contracts: {len(doc.get('contracts', {})) if isinstance(doc, dict) else 0} contract(s)")
    print(f"{PREDICATE} effect keys: {len(profile_effect_keys(profiles))} unique key(s)")
    print(f"{PREDICATE} profile rows: {len(profiles)}")
    print(f"errors: {validation.errors}")
    return 1 if validation.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
