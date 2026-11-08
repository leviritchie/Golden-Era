#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from validate_custom_faction_manifests import Validation, load_json  # noqa: E402


DEFAULT_CONTRACTS_PATH = ROOT / "custom_factions" / "construct_classifier_predicate_contracts.json"
DEFAULT_INVENTORY_PATH = ROOT / "custom_factions" / "custom_law_effect_plan_inventory.json"
DEFAULT_MANIFEST_PATH = ROOT / "custom_factions" / "homm3_tower.json"
DEFAULT_UNIT_FAMILY_TAGS_PATH = ROOT / "custom_factions" / "unit_family_tags.json"


def load_construct_profiles(inventory_path: Path) -> list[dict[str, Any]]:
    inventory = load_json(inventory_path)
    rows = inventory.get("rows") if isinstance(inventory, dict) else None
    profiles: list[dict[str, Any]] = []
    if not isinstance(rows, list):
        return profiles
    for row in rows:
        if not isinstance(row, dict):
            continue
        predicates = row.get("requiredPredicates")
        if isinstance(predicates, list) and "RequiresConstructClassifier" in predicates:
            profiles.append(row)
    return profiles


def profile_effect_keys(profiles: list[dict[str, Any]]) -> set[str]:
    keys: set[str] = set()
    for row in profiles:
        effect_key = row.get("effectKey")
        if isinstance(effect_key, str):
            keys.add(effect_key)
    return keys


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


def construct_unit_sids(unit_tags: Any) -> set[str]:
    if not isinstance(unit_tags, dict):
        return set()
    units = unit_tags.get("units")
    if not isinstance(units, dict):
        return set()
    result: set[str] = set()
    for sid, facts in units.items():
        if isinstance(sid, str) and isinstance(facts, dict) and facts.get("construct") == "yes":
            result.add(sid)
    return result


def validate_contracts(doc: Any, profiles: list[dict[str, Any]], manifest: Any, unit_tags: Any, validation: Validation) -> None:
    if not isinstance(doc, dict):
        validation.error("construct classifier predicate contracts root must be an object")
        return
    if doc.get("schemaVersion") != 1:
        validation.error(f"construct classifier predicate contracts schemaVersion must be 1, got {doc.get('schemaVersion')!r}")
    policy = doc.get("policy")
    if not isinstance(policy, dict):
        validation.error("policy must be an object")
    else:
        required_true = (
            "effectKeysMustMatchRequiresConstructClassifierProfiles",
            "towerOnly",
            "constructFactMustComeFromUnitFamilyTags",
            "towerConstructLinesMustMatchManifest",
            "runtimeProofStillRequiredForGameplay",
        )
        for key in required_true:
            if policy.get(key) is not True:
                validation.error(f"policy.{key} must be true")

    static_evidence = doc.get("requiredStaticEvidence")
    if not isinstance(static_evidence, dict):
        validation.error("requiredStaticEvidence must be an object")
        static_evidence = {}
    expected_paths = {
        "manifestPath": "custom_factions/homm3_tower.json",
        "unitFamilyTagsPath": "custom_factions/unit_family_tags.json",
        "factionSid": "homm3_tower",
        "requiredFact": "construct=yes",
    }
    for key, value in expected_paths.items():
        if static_evidence.get(key) != value:
            validation.error(f"requiredStaticEvidence.{key} must be {value!r}")

    identity = manifest.get("identity") if isinstance(manifest, dict) else None
    if not isinstance(identity, dict) or identity.get("factionSid") != "homm3_tower":
        validation.error("Tower manifest identity.factionSid must be homm3_tower")
    base_sids = manifest_base_sids(manifest)
    required_bases = static_evidence.get("requiredConstructBaseSids")
    if not isinstance(required_bases, list) or not required_bases:
        validation.error("requiredStaticEvidence.requiredConstructBaseSids must be a non-empty list")
        required_bases = []
    for sid in required_bases:
        if not isinstance(sid, str) or not sid:
            validation.error("requiredConstructBaseSids entries must be non-empty strings")
        elif sid not in base_sids:
            validation.error(f"required construct base SID {sid!r} is not present in Tower manifest unitLines")

    construct_sids = construct_unit_sids(unit_tags)
    required_units = static_evidence.get("requiredConstructUnitSids")
    if not isinstance(required_units, list) or not required_units:
        validation.error("requiredStaticEvidence.requiredConstructUnitSids must be a non-empty list")
        required_units = []
    for sid in required_units:
        if not isinstance(sid, str) or not sid:
            validation.error("requiredConstructUnitSids entries must be non-empty strings")
        elif sid not in construct_sids:
            validation.error(f"required construct unit SID {sid!r} is not marked construct=yes in unit_family_tags")
    extra_construct_sids = sorted(construct_sids - set(required_units))
    if extra_construct_sids:
        validation.error(f"unit_family_tags has unexpected construct=yes SID(s): {extra_construct_sids}")

    required_runtime = doc.get("requiredRuntimeProof")
    required_items = {
        "live battle stack unit SID proof",
        "hero party unit SID proof",
        "construct classifier reaches consuming hook proof",
        "spell cast to construct owner correlation proof",
        "temporary summon or duplicate-stack handling proof",
        "construct readiness state timing proof",
        "idempotent construct effect application proof",
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
        validation.error(f"{missing}: missing construct classifier predicate contract")
    for extra in sorted(actual_keys - expected_keys):
        validation.error(f"{extra}: construct classifier contract has no exact RequiresConstructClassifier profile")
    for row in profiles:
        effect_key = row.get("effectKey")
        if not isinstance(effect_key, str):
            validation.error(f"RequiresConstructClassifier profile has invalid effectKey {effect_key!r}")
        elif not effect_key.startswith("tower."):
            validation.error(f"{effect_key}: RequiresConstructClassifier must remain Tower-only")

    for effect_key, contract in sorted(contracts.items()):
        if not isinstance(contract, dict):
            validation.error(f"{effect_key}: contract must be an object")
            continue
        construct_kinds = contract.get("constructKinds")
        if not isinstance(construct_kinds, list) or not construct_kinds:
            validation.error(f"{effect_key}: constructKinds must be a non-empty list")
            construct_kinds = []
        construct_text = "\n".join(str(item).lower() for item in construct_kinds if isinstance(item, str))
        if "authored-tower-gargoyle-or-golem-line" not in construct_text:
            validation.error(f"{effect_key}: constructKinds must require authored Tower Gargoyle or Golem line")
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
            "tower faction membership counted as construct",
            "donor human unit identity counted as construct",
            "sid substring construct inference",
            "display-name construct inference",
            "any non-living unit counted as construct",
        )
        for phrase in required_forbidden:
            if phrase not in forbidden_text:
                validation.error(f"{effect_key}: forbiddenSubstitutes must reject {phrase!r}")
        notes = contract.get("notes")
        if not isinstance(notes, str) or not notes:
            validation.error(f"{effect_key}: notes must be a non-empty string")
        elif "requires" not in notes.lower() or "gargoyle or golem" not in notes.lower():
            validation.error(f"{effect_key}: notes must state required Gargoyle/Golem construct boundary")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contracts", type=Path, default=DEFAULT_CONTRACTS_PATH)
    parser.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY_PATH)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST_PATH)
    parser.add_argument("--unit-family-tags", type=Path, default=DEFAULT_UNIT_FAMILY_TAGS_PATH)
    args = parser.parse_args()

    validation = Validation()
    doc = load_json(args.contracts)
    profiles = load_construct_profiles(args.inventory)
    manifest = load_json(args.manifest)
    unit_tags = load_json(args.unit_family_tags)
    validate_contracts(doc, profiles, manifest, unit_tags, validation)
    print(f"construct classifier predicate contracts: {len(doc.get('contracts', {})) if isinstance(doc, dict) else 0} contract(s)")
    print(f"RequiresConstructClassifier effect keys: {len(profile_effect_keys(profiles))} unique key(s)")
    print(f"RequiresConstructClassifier profile rows: {len(profiles)}")
    print(f"authored construct=yes unit SIDs: {len(construct_unit_sids(unit_tags))}")
    print(f"errors: {validation.errors}")
    if validation.warnings:
        print(f"warnings: {validation.warnings}")
    return 1 if validation.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())