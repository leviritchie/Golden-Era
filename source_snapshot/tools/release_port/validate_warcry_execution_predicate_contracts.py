#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from validate_custom_faction_manifests import Validation, load_json  # noqa: E402


DEFAULT_CONTRACTS_PATH = ROOT / "custom_factions" / "warcry_execution_predicate_contracts.json"
DEFAULT_INVENTORY_PATH = ROOT / "custom_factions" / "custom_law_effect_plan_inventory.json"
DEFAULT_MANIFEST_PATH = ROOT / "custom_factions" / "homm3_stronghold.json"


def load_warcry_profiles(inventory_path: Path) -> list[dict[str, Any]]:
    inventory = load_json(inventory_path)
    rows = inventory.get("rows") if isinstance(inventory, dict) else None
    profiles: list[dict[str, Any]] = []
    if not isinstance(rows, list):
        return profiles
    for row in rows:
        if not isinstance(row, dict):
            continue
        predicates = row.get("requiredPredicates")
        if isinstance(predicates, list) and "RequiresWarcryExecution" in predicates:
            profiles.append(row)
    return profiles


def profile_effect_keys(profiles: list[dict[str, Any]]) -> set[str]:
    keys: set[str] = set()
    for row in profiles:
        effect_key = row.get("effectKey")
        if isinstance(effect_key, str):
            keys.add(effect_key)
    return keys


def validate_manifest_evidence(static_evidence: dict[str, Any], manifest: Any, validation: Validation) -> None:
    if not isinstance(manifest, dict):
        validation.error("Stronghold manifest root must be an object")
        return
    identity = manifest.get("identity")
    skills = manifest.get("skillsAndLaws")
    if not isinstance(identity, dict):
        validation.error("Stronghold manifest identity must be an object")
        identity = {}
    if not isinstance(skills, dict):
        validation.error("Stronghold manifest skillsAndLaws must be an object")
        skills = {}
    expected_faction = static_evidence.get("factionSid")
    expected_skill = static_evidence.get("factionSkillSid")
    expected_prefix = static_evidence.get("lawPrefix")
    if identity.get("factionSid") != expected_faction:
        validation.error(f"Stronghold manifest factionSid mismatch: expected {expected_faction!r}, got {identity.get('factionSid')!r}")
    if skills.get("factionSkillSid") != expected_skill:
        validation.error(f"Stronghold manifest factionSkillSid mismatch: expected {expected_skill!r}, got {skills.get('factionSkillSid')!r}")
    if skills.get("lawPrefix") != expected_prefix:
        validation.error(f"Stronghold manifest lawPrefix mismatch: expected {expected_prefix!r}, got {skills.get('lawPrefix')!r}")


def validate_contracts(doc: Any, profiles: list[dict[str, Any]], manifest: Any, validation: Validation) -> None:
    if not isinstance(doc, dict):
        validation.error("Warcry execution predicate contracts root must be an object")
        return
    if doc.get("schemaVersion") != 1:
        validation.error(f"Warcry execution predicate contracts schemaVersion must be 1, got {doc.get('schemaVersion')!r}")
    policy = doc.get("policy")
    if not isinstance(policy, dict):
        validation.error("policy must be an object")
    else:
        required_true = (
            "effectKeysMustMatchRequiresWarcryExecutionProfiles",
            "strongholdOnly",
            "factionSkillSidMustMatchManifest",
            "warcryExecutionMustNotBeSubstitutedBySpellCast",
            "runtimeProofStillRequiredForGameplay",
        )
        for key in required_true:
            if policy.get(key) is not True:
                validation.error(f"policy.{key} must be true")

    static_evidence = doc.get("requiredStaticEvidence")
    if not isinstance(static_evidence, dict):
        validation.error("requiredStaticEvidence must be an object")
        static_evidence = {}
    else:
        expected = {
            "manifestPath": "custom_factions/homm3_stronghold.json",
            "factionSid": "homm3_stronghold",
            "factionSkillSid": "skill_faction_homm3_stronghold",
            "lawPrefix": "fraction_law_homm3_stronghold_",
        }
        for key, value in expected.items():
            if static_evidence.get(key) != value:
                validation.error(f"requiredStaticEvidence.{key} must be {value!r}")
    validate_manifest_evidence(static_evidence, manifest, validation)

    required_runtime = doc.get("requiredRuntimeProof")
    required_items = {
        "native Warcry execution event proof",
        "executing hero owner and side proof",
        "Warcry identity or row SID proof",
        "successful execution versus preview or failed execution proof",
        "Warcry cooldown read and mutation ordering proof",
        "battle timing and round interaction proof",
        "idempotent reward or tempo application proof",
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
        validation.error(f"{missing}: missing Warcry execution predicate contract")
    for extra in sorted(actual_keys - expected_keys):
        validation.error(f"{extra}: Warcry execution contract has no exact RequiresWarcryExecution profile")

    for row in profiles:
        effect_key = row.get("effectKey")
        if not isinstance(effect_key, str):
            validation.error(f"RequiresWarcryExecution profile has invalid effectKey {effect_key!r}")
            continue
        if not effect_key.startswith("stronghold."):
            validation.error(f"{effect_key}: RequiresWarcryExecution must remain Stronghold-only")

    for effect_key, contract in sorted(contracts.items()):
        if not isinstance(contract, dict):
            validation.error(f"{effect_key}: contract must be an object")
            continue
        warcry_kinds = contract.get("warcryKinds")
        if not isinstance(warcry_kinds, list) or not warcry_kinds:
            validation.error(f"{effect_key}: warcryKinds must be a non-empty list")
            warcry_kinds = []
        warcry_text = "\n".join(str(item).lower() for item in warcry_kinds if isinstance(item, str))
        if "warcry" not in warcry_text:
            validation.error(f"{effect_key}: warcryKinds must describe Warcry behavior")
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
            "spell cast counted as warcry execution",
            "hero ability level counted as warcry execution",
            "static faction skill ownership counted as execution",
        )
        for phrase in required_forbidden:
            if phrase not in forbidden_text:
                validation.error(f"{effect_key}: forbiddenSubstitutes must reject {phrase!r}")
        if effect_key.endswith("cooldown-tempo") and "cooldown mutation without successful warcry execution proof" not in forbidden_text:
            validation.error(f"{effect_key}: cooldown tempo must reject cooldown mutation without successful Warcry execution proof")
        if effect_key.endswith("school-replacement") and "magic school access counted as warcry execution" not in forbidden_text:
            validation.error(f"{effect_key}: school replacement must reject magic school access as Warcry execution")
        notes = contract.get("notes")
        if not isinstance(notes, str) or not notes:
            validation.error(f"{effect_key}: notes must be a non-empty string")
        elif "requires" not in notes.lower() or "warcry execution" not in notes.lower():
            validation.error(f"{effect_key}: notes must state required Warcry execution boundary")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contracts", type=Path, default=DEFAULT_CONTRACTS_PATH)
    parser.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY_PATH)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST_PATH)
    args = parser.parse_args()

    validation = Validation()
    doc = load_json(args.contracts)
    profiles = load_warcry_profiles(args.inventory)
    manifest = load_json(args.manifest)
    validate_contracts(doc, profiles, manifest, validation)
    print(f"Warcry execution predicate contracts: {len(doc.get('contracts', {})) if isinstance(doc, dict) else 0} contract(s)")
    print(f"RequiresWarcryExecution effect keys: {len(profile_effect_keys(profiles))} unique key(s)")
    print(f"RequiresWarcryExecution profile rows: {len(profiles)}")
    print(f"errors: {validation.errors}")
    if validation.warnings:
        print(f"warnings: {validation.warnings}")
    return 1 if validation.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())