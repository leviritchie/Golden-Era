#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from validate_custom_faction_manifests import Validation, load_json  # noqa: E402


DEFAULT_CONTRACTS_PATH = ROOT / "custom_factions" / "avenger_mark_predicate_contracts.json"
DEFAULT_INVENTORY_PATH = ROOT / "custom_factions" / "custom_law_effect_plan_inventory.json"
DEFAULT_RAMPART_MANIFEST_PATH = ROOT / "custom_factions" / "homm3_rampart.json"


def load_avenger_profiles(inventory_path: Path) -> dict[str, dict[str, Any]]:
    inventory = load_json(inventory_path)
    rows = inventory.get("rows") if isinstance(inventory, dict) else None
    profiles: dict[str, dict[str, Any]] = {}
    if not isinstance(rows, list):
        return profiles
    for row in rows:
        if not isinstance(row, dict):
            continue
        predicates = row.get("requiredPredicates")
        if not isinstance(predicates, list) or "RequiresAvengerMark" not in predicates:
            continue
        effect_key = row.get("effectKey")
        if isinstance(effect_key, str):
            profiles[effect_key] = row
    return profiles


def validate_contracts(
    doc: Any,
    profiles: dict[str, dict[str, Any]],
    rampart_manifest: Any,
    validation: Validation,
) -> None:
    if not isinstance(doc, dict):
        validation.error("avenger mark predicate contracts root must be an object")
        return
    if doc.get("schemaVersion") != 1:
        validation.error(f"avenger mark predicate contracts schemaVersion must be 1, got {doc.get('schemaVersion')!r}")
    policy = doc.get("policy")
    if not isinstance(policy, dict):
        validation.error("policy must be an object")
    else:
        required_true = (
            "effectKeysMustMatchRequiresAvengerMarkProfiles",
            "rampartOnly",
            "forbidFactionMatchInference",
            "runtimeProofStillRequiredForGameplay",
        )
        for key in required_true:
            if policy.get(key) is not True:
                validation.error(f"policy.{key} must be true")
        if policy.get("allowCustomBattleLocalMarkRegistry") is not True:
            validation.error("policy.allowCustomBattleLocalMarkRegistry must be true")

    identity = doc.get("nativeIdentityEvidence")
    if not isinstance(identity, dict):
        validation.error("nativeIdentityEvidence must be an object")
    elif identity.get("expectedSkillName") != "Avenger":
        validation.error("nativeIdentityEvidence.expectedSkillName must be Avenger")

    manifest_skill_name = None
    if isinstance(rampart_manifest, dict):
        skills = rampart_manifest.get("skillsAndLaws")
        if isinstance(skills, dict):
            manifest_skill_name = skills.get("skillName")
    if manifest_skill_name != "Avenger":
        validation.error(f"homm3_rampart manifest skillName must be Avenger, got {manifest_skill_name!r}")

    required_runtime = doc.get("requiredRuntimeProof")
    if not isinstance(required_runtime, list) or not required_runtime:
        validation.error("requiredRuntimeProof must be a non-empty list")
    else:
        for item in required_runtime:
            if not isinstance(item, str) or not item:
                validation.error(f"requiredRuntimeProof entries must be non-empty strings, got {item!r}")
        if "custom battle-local Avenger mark state proof" not in required_runtime:
            validation.error("requiredRuntimeProof must include custom battle-local Avenger mark state proof")

    contracts = doc.get("contracts")
    if not isinstance(contracts, dict) or not contracts:
        validation.error("contracts must be a non-empty object")
        return

    expected_keys = set(profiles)
    actual_keys = set(contracts)
    for missing in sorted(expected_keys - actual_keys):
        validation.error(f"{missing}: missing Avenger mark predicate contract")
    for extra in sorted(actual_keys - expected_keys):
        validation.error(f"{extra}: Avenger mark predicate contract has no exact RequiresAvengerMark profile")

    for effect_key, profile in sorted(profiles.items()):
        if profile.get("factionSid") != "homm3_rampart":
            validation.error(f"{effect_key}: RequiresAvengerMark profile must be Rampart-only")

    for effect_key, contract in sorted(contracts.items()):
        if not isinstance(contract, dict):
            validation.error(f"{effect_key}: contract must be an object")
            continue
        for field in ("usage", "notes"):
            if not isinstance(contract.get(field), str) or not contract.get(field):
                validation.error(f"{effect_key}: {field} must be a non-empty string")
        forbidden = contract.get("forbiddenSubstitutes")
        if not isinstance(forbidden, list) or not forbidden:
            validation.error(f"{effect_key}: forbiddenSubstitutes must be a non-empty list")
        else:
            forbidden_text = "\n".join(str(item).lower() for item in forbidden if isinstance(item, str))
            if "faction-match inference" not in forbidden_text:
                validation.error(f"{effect_key}: forbiddenSubstitutes must forbid faction-match inference without custom Avenger mark state")
            for item in forbidden:
                if not isinstance(item, str) or not item:
                    validation.error(f"{effect_key}: forbiddenSubstitutes entries must be non-empty strings")
        notes = contract.get("notes")
        if isinstance(notes, str) and "proven" not in notes.lower():
            validation.error(f"{effect_key}: notes must state the proof boundary")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contracts", type=Path, default=DEFAULT_CONTRACTS_PATH)
    parser.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY_PATH)
    parser.add_argument("--rampart-manifest", type=Path, default=DEFAULT_RAMPART_MANIFEST_PATH)
    args = parser.parse_args()

    validation = Validation()
    doc = load_json(args.contracts)
    profiles = load_avenger_profiles(args.inventory)
    rampart_manifest = load_json(args.rampart_manifest)
    validate_contracts(doc, profiles, rampart_manifest, validation)
    print(f"avenger mark predicate contracts: {len(doc.get('contracts', {})) if isinstance(doc, dict) else 0} contract(s)")
    print(f"RequiresAvengerMark profiles: {len(profiles)} profile(s)")
    print(f"errors: {validation.errors}")
    if validation.warnings:
        print(f"warnings: {validation.warnings}")
    return 1 if validation.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
