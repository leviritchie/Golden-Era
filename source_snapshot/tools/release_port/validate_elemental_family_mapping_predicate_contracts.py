#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from validate_custom_faction_manifests import Validation, load_json  # noqa: E402


DEFAULT_CONTRACTS_PATH = ROOT / "custom_factions" / "elemental_family_mapping_predicate_contracts.json"
DEFAULT_INVENTORY_PATH = ROOT / "custom_factions" / "custom_law_effect_plan_inventory.json"
DEFAULT_MANIFEST_PATH = ROOT / "custom_factions" / "homm3_conflux.json"
DEFAULT_UNIT_FAMILY_TAGS_PATH = ROOT / "custom_factions" / "unit_family_tags.json"


def load_profiles(inventory_path: Path) -> list[dict[str, Any]]:
    inventory = load_json(inventory_path)
    rows = inventory.get("rows") if isinstance(inventory, dict) else None
    profiles: list[dict[str, Any]] = []
    if not isinstance(rows, list):
        return profiles
    for row in rows:
        if not isinstance(row, dict):
            continue
        predicates = row.get("requiredPredicates")
        if isinstance(predicates, list) and "RequiresElementalFamilyMapping" in predicates:
            profiles.append(row)
    return profiles


def profile_effect_keys(profiles: list[dict[str, Any]]) -> set[str]:
    result: set[str] = set()
    for row in profiles:
        effect_key = row.get("effectKey")
        if isinstance(effect_key, str):
            result.add(effect_key)
    return result


def manifest_base_sids(manifest: Any) -> set[str]:
    if not isinstance(manifest, dict):
        return set()
    lines = manifest.get("unitLines")
    if not isinstance(lines, list):
        return set()
    result: set[str] = set()
    for line in lines:
        if isinstance(line, dict) and isinstance(line.get("baseSid"), str):
            result.add(line["baseSid"])
    return result


def elemental_unit_sids(unit_tags: Any) -> set[str]:
    if not isinstance(unit_tags, dict):
        return set()
    units = unit_tags.get("units")
    if not isinstance(units, dict):
        return set()
    result: set[str] = set()
    for sid, facts in units.items():
        if isinstance(sid, str) and isinstance(facts, dict) and facts.get("elemental") == "yes":
            result.add(sid)
    return result


def flatten_family_sids(families: Any) -> set[str]:
    result: set[str] = set()
    if not isinstance(families, dict):
        return result
    for values in families.values():
        if isinstance(values, list):
            for sid in values:
                if isinstance(sid, str):
                    result.add(sid)
    return result


def validate_contracts(doc: Any, profiles: list[dict[str, Any]], manifest: Any, unit_tags: Any, validation: Validation) -> None:
    if not isinstance(doc, dict):
        validation.error("elemental family mapping predicate contracts root must be an object")
        return
    if doc.get("schemaVersion") != 1:
        validation.error(f"elemental family mapping predicate contracts schemaVersion must be 1, got {doc.get('schemaVersion')!r}")
    policy = doc.get("policy")
    if not isinstance(policy, dict):
        validation.error("policy must be an object")
    else:
        required_true = (
            "effectKeysMustMatchRequiresElementalFamilyMappingProfiles",
            "confluxOnly",
            "familyMappingMustComeFromConfluxManifestAndUnitFamilyTags",
            "pixieAndFirebirdAreNotElementalFamilyMappings",
            "runtimeProofStillRequiredForGameplay",
        )
        for key in required_true:
            if policy.get(key) is not True:
                validation.error(f"policy.{key} must be true")

    static_evidence = doc.get("requiredStaticEvidence")
    if not isinstance(static_evidence, dict):
        validation.error("requiredStaticEvidence must be an object")
        static_evidence = {}
    expected_scalars = {
        "manifestPath": "custom_factions/homm3_conflux.json",
        "unitFamilyTagsPath": "custom_factions/unit_family_tags.json",
        "factionSid": "homm3_conflux",
        "requiredFact": "elemental=yes",
    }
    for key, value in expected_scalars.items():
        if static_evidence.get(key) != value:
            validation.error(f"requiredStaticEvidence.{key} must be {value!r}")

    identity = manifest.get("identity") if isinstance(manifest, dict) else None
    if not isinstance(identity, dict) or identity.get("factionSid") != "homm3_conflux":
        validation.error("Conflux manifest identity.factionSid must be homm3_conflux")
    base_sids = manifest_base_sids(manifest)
    families = static_evidence.get("requiredElementalFamilies")
    expected_family_names = {"air", "water", "fire", "earth", "psychic"}
    if not isinstance(families, dict) or set(families) != expected_family_names:
        validation.error(f"requiredElementalFamilies must contain exactly {sorted(expected_family_names)}")
        families = {}
    elemental_sids = elemental_unit_sids(unit_tags)
    mapped_sids = flatten_family_sids(families)
    for family_name, values in sorted(families.items()):
        if not isinstance(values, list) or len(values) != 3:
            validation.error(f"requiredElementalFamilies.{family_name} must list exactly three variant SIDs")
            continue
        base_sid = values[0] if values else None
        if not isinstance(base_sid, str) or base_sid not in base_sids:
            validation.error(f"requiredElementalFamilies.{family_name}[0] must be a Conflux manifest base SID")
        for sid in values:
            if not isinstance(sid, str) or not sid:
                validation.error(f"requiredElementalFamilies.{family_name} entries must be non-empty strings")
            elif sid not in elemental_sids:
                validation.error(f"{sid}: required elemental family SID is not marked elemental=yes in unit_family_tags")
    if mapped_sids != elemental_sids:
        validation.error(f"mapped elemental family SIDs must equal authored elemental=yes SIDs; missing={sorted(elemental_sids - mapped_sids)}, extra={sorted(mapped_sids - elemental_sids)}")
    excluded = static_evidence.get("excludedConfluxBaseSids")
    if not isinstance(excluded, list) or sorted(excluded) != ["h3_firebird", "h3_pixie"]:
        validation.error("excludedConfluxBaseSids must be exactly ['h3_pixie', 'h3_firebird']")
    else:
        for sid in excluded:
            if sid not in base_sids:
                validation.error(f"excluded base SID {sid!r} is not present in Conflux manifest")
            if sid in elemental_sids:
                validation.error(f"excluded base SID {sid!r} must not be marked elemental=yes")

    required_runtime = doc.get("requiredRuntimeProof")
    required_items = {
        "active elemental family selection proof",
        "live battle stack or party unit SID proof",
        "spell school or spell SID to elemental family correlation proof",
        "object SID or category to elemental family correlation proof",
        "day phase to elemental family correlation proof",
        "law owner to selected family correlation proof",
        "idempotent family-specific effect application proof",
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
    expected_keys = profile_effect_keys(profiles)
    actual_keys = set(contracts)
    for missing in sorted(expected_keys - actual_keys):
        validation.error(f"{missing}: missing elemental family mapping predicate contract")
    for extra in sorted(actual_keys - expected_keys):
        validation.error(f"{extra}: elemental family mapping contract has no exact RequiresElementalFamilyMapping profile")
    for row in profiles:
        effect_key = row.get("effectKey")
        if not isinstance(effect_key, str):
            validation.error(f"RequiresElementalFamilyMapping profile has invalid effectKey {effect_key!r}")
        elif not effect_key.startswith("conflux."):
            validation.error(f"{effect_key}: RequiresElementalFamilyMapping must remain Conflux-only")

    for effect_key, contract in sorted(contracts.items()):
        if not isinstance(contract, dict):
            validation.error(f"{effect_key}: contract must be an object")
            continue
        mapping_kinds = contract.get("mappingKinds")
        if not isinstance(mapping_kinds, list) or not mapping_kinds:
            validation.error(f"{effect_key}: mappingKinds must be a non-empty list")
            mapping_kinds = []
        mapping_text = "\n".join(str(item).lower() for item in mapping_kinds if isinstance(item, str))
        if "explicit-conflux-elemental-family-map" not in mapping_text:
            validation.error(f"{effect_key}: mappingKinds must require explicit Conflux elemental family map")
        companion = contract.get("companionPredicates")
        if not isinstance(companion, list):
            validation.error(f"{effect_key}: companionPredicates must be a list")
            companion = []
        matching_profiles = [row for row in profiles if row.get("effectKey") == effect_key]
        profile_preds = set()
        for row in matching_profiles:
            predicates = row.get("requiredPredicates")
            if isinstance(predicates, list):
                profile_preds.update(predicates)
        for predicate in companion:
            if not isinstance(predicate, str) or not predicate:
                validation.error(f"{effect_key}: companionPredicates entries must be non-empty strings")
            elif predicate not in profile_preds:
                validation.error(f"{effect_key}: companion predicate {predicate!r} is not present on the profile row")
        forbidden = contract.get("forbiddenSubstitutes")
        if not isinstance(forbidden, list) or not forbidden:
            validation.error(f"{effect_key}: forbiddenSubstitutes must be a non-empty list")
            forbidden = []
        forbidden_text = "\n".join(str(item).lower() for item in forbidden if isinstance(item, str))
        required_forbidden = (
            "conflux faction membership counted as elemental family mapping",
            "any elemental unit counted without family identity",
            "pixie counted as elemental family mapping",
            "firebird counted as elemental family mapping",
            "sid substring elemental inference",
        )
        for phrase in required_forbidden:
            if phrase not in forbidden_text:
                validation.error(f"{effect_key}: forbiddenSubstitutes must reject {phrase!r}")
        notes = contract.get("notes")
        if not isinstance(notes, str) or not notes:
            validation.error(f"{effect_key}: notes must be a non-empty string")
        elif "requires" not in notes.lower() or "explicit authored elemental family mapping" not in notes.lower():
            validation.error(f"{effect_key}: notes must state explicit authored elemental family mapping boundary")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contracts", type=Path, default=DEFAULT_CONTRACTS_PATH)
    parser.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY_PATH)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST_PATH)
    parser.add_argument("--unit-family-tags", type=Path, default=DEFAULT_UNIT_FAMILY_TAGS_PATH)
    args = parser.parse_args()

    validation = Validation()
    doc = load_json(args.contracts)
    profiles = load_profiles(args.inventory)
    manifest = load_json(args.manifest)
    unit_tags = load_json(args.unit_family_tags)
    validate_contracts(doc, profiles, manifest, unit_tags, validation)
    print(f"elemental family mapping predicate contracts: {len(doc.get('contracts', {})) if isinstance(doc, dict) else 0} contract(s)")
    print(f"RequiresElementalFamilyMapping effect keys: {len(profile_effect_keys(profiles))} unique key(s)")
    print(f"RequiresElementalFamilyMapping profile rows: {len(profiles)}")
    print(f"authored elemental=yes unit SIDs: {len(elemental_unit_sids(unit_tags))}")
    print(f"errors: {validation.errors}")
    if validation.warnings:
        print(f"warnings: {validation.warnings}")
    return 1 if validation.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())