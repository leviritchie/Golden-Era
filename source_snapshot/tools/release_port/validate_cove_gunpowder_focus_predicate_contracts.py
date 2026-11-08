#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
from validate_custom_faction_manifests import Validation, load_json  # noqa: E402

DEFAULT_CONTRACTS_PATH = ROOT / "custom_factions" / "cove_gunpowder_focus_predicate_contracts.json"
DEFAULT_INVENTORY_PATH = ROOT / "custom_factions" / "custom_law_effect_plan_inventory.json"
DEFAULT_UNIT_TAGS_PATH = ROOT / "custom_factions" / "unit_family_tags.json"
PREDICATES = (
    "RequiresGunpowderOrPirate",
    "RequiresFocusOrReload",
    "RequiresGunpowderOrRangedSupport",
    "RequiresFocusCredit",
)


def load_profiles(path: Path, predicate: str) -> list[dict[str, Any]]:
    inventory = load_json(path)
    rows = inventory.get("rows") if isinstance(inventory, dict) else None
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict) and predicate in (row.get("requiredPredicates") or [])]


def effect_keys(rows: list[dict[str, Any]]) -> set[str]:
    return {row["effectKey"] for row in rows if isinstance(row.get("effectKey"), str)}


def require_unit_fact(tags: Any, fact: str, value: str, validation: Validation) -> None:
    units = tags.get("units") if isinstance(tags, dict) else None
    if not isinstance(units, dict):
        validation.error("unit_family_tags.units must be an object")
        return
    matches = [sid for sid, row in units.items() if isinstance(row, dict) and row.get(fact) == value]
    if not matches:
        validation.error(f"unit_family_tags has no {fact}={value} entries")


def validate_contracts(doc: Any, inventory_path: Path, unit_tags: Any, validation: Validation) -> None:
    if not isinstance(doc, dict):
        validation.error("Cove gunpowder/focus predicate contracts root must be an object")
        return
    if doc.get("schemaVersion") != 1:
        validation.error(f"schemaVersion must be 1, got {doc.get('schemaVersion')!r}")
    policy = doc.get("policy") if isinstance(doc.get("policy"), dict) else {}
    for key in (
        "allContractsMustMatchExactRequiresPredicateProfiles",
        "coveOnly",
        "gunpowderUsesAuthoredUnitFactsOnly",
        "pirateNameInferenceForbidden",
        "focusCreditRequiresCommittedCreditEvent",
        "reloadRequiresExactAbilityOrEventIdentity",
        "rangedSupportRequiresShooterRoleEvidence",
        "runtimeProofStillRequiredForGameplay",
    ):
        if policy.get(key) is not True:
            validation.error(f"policy.{key} must be true")
    if sorted(doc.get("allowedFactions") or []) != ["homm3_cove"]:
        validation.error("allowedFactions must be exactly ['homm3_cove']")
    required_runtime = set(doc.get("requiredRuntimeProof") or [])
    for item in (
        "battle unit SID to authored classifier correlation proof",
        "law-owner side correlation proof",
        "committed Focus credit event proof",
        "Focus recipient identity proof",
        "exact reload ability or event proof",
        "ranged support actor identity proof",
        "spell-cast to support/Focus ordering proof",
        "idempotent per-action application proof",
    ):
        if item not in required_runtime:
            validation.error(f"requiredRuntimeProof missing {item!r}")
    contracts = doc.get("contracts")
    if not isinstance(contracts, dict):
        validation.error("contracts must be an object")
        return
    if set(contracts) != set(PREDICATES):
        validation.error(f"contracts must contain exactly {list(PREDICATES)!r}")
    require_unit_fact(unit_tags, "gunpowder", "yes", validation)
    require_unit_fact(unit_tags, "shooter", "yes", validation)
    allowed_facts = set(unit_tags.get("allowedFacts") or []) if isinstance(unit_tags, dict) else set()
    if "pirate" in allowed_facts:
        validation.error("pirate fact unexpectedly exists; validator must be updated to require exact authored pirate evidence")
    for predicate in PREDICATES:
        profiles = load_profiles(inventory_path, predicate)
        expected_keys = effect_keys(profiles)
        contract = contracts.get(predicate)
        if not isinstance(contract, dict):
            validation.error(f"{predicate}: contract must be an object")
            continue
        actual_keys = set(contract.get("requiredEffectKeys") or [])
        if actual_keys != expected_keys:
            validation.error(f"{predicate}: requiredEffectKeys {sorted(actual_keys)!r} must match exact profile keys {sorted(expected_keys)!r}")
        allowed_families = set(contract.get("allowedFamilies") or [])
        if not allowed_families:
            validation.error(f"{predicate}: allowedFamilies must be non-empty")
        for row in profiles:
            effect_key = row.get("effectKey")
            if row.get("factionSid") != "homm3_cove":
                validation.error(f"{predicate}/{effect_key}: faction must be homm3_cove")
            if row.get("family") not in allowed_families:
                validation.error(f"{predicate}/{effect_key}: family {row.get('family')!r} not in allowedFamilies")
        forbidden = contract.get("forbiddenSubstitutes")
        if not isinstance(forbidden, list) or not forbidden:
            validation.error(f"{predicate}: forbiddenSubstitutes must be a non-empty list")
            forbidden = []
        forbidden_text = "\n".join(str(item).lower() for item in forbidden if isinstance(item, str))
        if predicate == "RequiresGunpowderOrPirate":
            for phrase in (
                "unit SID or display name containing pirate counted as pirate classifier",
                "Cove faction membership counted as gunpowder or pirate",
                "shooter role counted as gunpowder or pirate",
            ):
                if phrase.lower() not in forbidden_text:
                    validation.error(f"{predicate}: forbiddenSubstitutes missing {phrase!r}")
        if predicate == "RequiresFocusOrReload":
            for phrase in (
                "hero energy pool existence counted as Focus event",
                "ability config existence counted as reload event",
                "ranged attack counted as reload",
            ):
                if phrase.lower() not in forbidden_text:
                    validation.error(f"{predicate}: forbiddenSubstitutes missing {phrase!r}")
        if predicate == "RequiresGunpowderOrRangedSupport":
            for phrase in (
                "Space or Arcane school access counted as gunpowder or ranged support",
                "generic support spell counted as ranged support",
                "shooter role counted as gunpowder without gunpowder fact",
            ):
                if phrase.lower() not in forbidden_text:
                    validation.error(f"{predicate}: forbiddenSubstitutes missing {phrase!r}")
        if predicate == "RequiresFocusCredit":
            for phrase in (
                "hero energy pool existence counted as Focus credit",
                "Focus UI value counted without committed credit event",
                "spell cast event counted as Focus credit",
            ):
                if phrase.lower() not in forbidden_text:
                    validation.error(f"{predicate}: forbiddenSubstitutes missing {phrase!r}")
        profile_predicates_by_key: dict[str, set[str]] = {}
        for row in profiles:
            profile_predicates_by_key.setdefault(row.get("effectKey"), set()).update(row.get("requiredPredicates") or [])
        profile_predicates = set().union(*profile_predicates_by_key.values()) if profile_predicates_by_key else set()
        for companion in contract.get("companionPredicates", []):
            if companion not in profile_predicates:
                validation.error(f"{predicate}: companion predicate {companion!r} is not present on matching profile rows")
        notes = contract.get("notes")
        if not isinstance(notes, str) or not notes:
            validation.error(f"{predicate}: notes must be a non-empty string")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contracts", type=Path, default=DEFAULT_CONTRACTS_PATH)
    parser.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY_PATH)
    parser.add_argument("--unit-tags", type=Path, default=DEFAULT_UNIT_TAGS_PATH)
    args = parser.parse_args()
    validation = Validation()
    doc = load_json(args.contracts)
    unit_tags = load_json(args.unit_tags)
    validate_contracts(doc, args.inventory, unit_tags, validation)
    print(f"Cove gunpowder/focus predicate contracts: {len(doc.get('contracts', {})) if isinstance(doc, dict) else 0} predicate contract(s)")
    for predicate in PREDICATES:
        profiles = load_profiles(args.inventory, predicate)
        print(f"{predicate}: {len(effect_keys(profiles))} unique key(s), {len(profiles)} profile row(s)")
    print(f"errors: {validation.errors}")
    return 1 if validation.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
