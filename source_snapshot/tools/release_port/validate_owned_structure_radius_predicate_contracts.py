#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from validate_custom_faction_manifests import DEFAULT_MANIFEST_DIR, Validation, core_overlay_enabled, load_json  # noqa: E402


DEFAULT_CONTRACTS_PATH = ROOT / "custom_factions" / "owned_structure_radius_predicate_contracts.json"
DEFAULT_INVENTORY_PATH = ROOT / "custom_factions" / "custom_law_effect_plan_inventory.json"


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
        if isinstance(predicates, list) and "RequiresOwnedStructureRadius" in predicates:
            profiles.append(row)
    return profiles


def profile_effect_keys(profiles: list[dict[str, Any]]) -> set[str]:
    result: set[str] = set()
    for row in profiles:
        effect_key = row.get("effectKey")
        if isinstance(effect_key, str):
            result.add(effect_key)
    return result


def load_enabled_manifest_rows(manifest_dir: Path) -> dict[str, dict[str, str]]:
    rows: dict[str, dict[str, str]] = {}
    for path in sorted(manifest_dir.glob("homm3_*.json")):
        manifest = load_json(path)
        if not isinstance(manifest, dict) or not core_overlay_enabled(manifest):
            continue
        identity = manifest.get("identity") if isinstance(manifest.get("identity"), dict) else {}
        overlay = manifest.get("coreOverlay") if isinstance(manifest.get("coreOverlay"), dict) else {}
        faction_sid = identity.get("factionSid")
        if not isinstance(faction_sid, str):
            continue
        rows[faction_sid] = {
            "sourceFile": str(path.relative_to(ROOT)),
            "citySid": identity.get("citySid"),
            "directCityMapObject": overlay.get("directCityMapObject"),
            "directDwellingPrefix": overlay.get("directDwellingPrefix"),
        }
    return rows


def validate_contracts(doc: Any, profiles: list[dict[str, Any]], manifest_rows: dict[str, dict[str, str]], validation: Validation) -> None:
    if not isinstance(doc, dict):
        validation.error("owned-structure radius predicate contracts root must be an object")
        return
    if doc.get("schemaVersion") != 1:
        validation.error(f"owned-structure radius predicate contracts schemaVersion must be 1, got {doc.get('schemaVersion')!r}")
    policy = doc.get("policy")
    if not isinstance(policy, dict):
        validation.error("policy must be an object")
    else:
        required_true = (
            "effectKeysMustMatchRequiresOwnedStructureRadiusProfiles",
            "ownedStructureMustComeFromEnabledFactionManifest",
            "citySidMustMatchDirectCityMapObject",
            "dwellingPrefixMustBeExactManifestPrefix",
            "runtimeProofStillRequiredForGameplay",
        )
        for key in required_true:
            if policy.get(key) is not True:
                validation.error(f"policy.{key} must be true")

    static_evidence = doc.get("requiredStaticEvidence")
    if not isinstance(static_evidence, dict):
        validation.error("requiredStaticEvidence must be an object")
        static_evidence = {}
    if static_evidence.get("manifestDir") != "custom_factions":
        validation.error("requiredStaticEvidence.manifestDir must be custom_factions")
    required_fields = static_evidence.get("requiredFields")
    expected_fields = [
        "identity.factionSid",
        "identity.citySid",
        "coreOverlay.directCityMapObject",
        "coreOverlay.directDwellingPrefix",
    ]
    if not isinstance(required_fields, list) or sorted(required_fields) != sorted(expected_fields):
        validation.error(f"requiredStaticEvidence.requiredFields must be exactly {expected_fields!r}")
    required_factions = static_evidence.get("requiredFactionSids")
    expected_factions = ["homm3_cove", "homm3_fortress", "homm3_necropolis", "homm3_tower"]
    if not isinstance(required_factions, list) or sorted(required_factions) != sorted(expected_factions):
        validation.error(f"requiredStaticEvidence.requiredFactionSids must be exactly {expected_factions!r}")
        required_factions = []
    for faction_sid in required_factions:
        row = manifest_rows.get(faction_sid)
        if row is None:
            validation.error(f"{faction_sid}: missing enabled manifest row")
            continue
        city_sid = row.get("citySid")
        direct_city = row.get("directCityMapObject")
        dwelling_prefix = row.get("directDwellingPrefix")
        if not isinstance(city_sid, str) or not city_sid:
            validation.error(f"{faction_sid}: identity.citySid must be a non-empty string")
        if direct_city != city_sid:
            validation.error(f"{faction_sid}: directCityMapObject {direct_city!r} must match citySid {city_sid!r}")
        if not isinstance(dwelling_prefix, str) or not dwelling_prefix:
            validation.error(f"{faction_sid}: directDwellingPrefix must be a non-empty string")

    required_runtime = doc.get("requiredRuntimeProof")
    required_items = {
        "runtime adventure object SID proof",
        "runtime structure owner side proof",
        "law owner side to structure owner side correlation proof",
        "structure map coordinate proof",
        "radius distance metric proof",
        "target object coordinate and filter proof",
        "idempotent radius scan and reveal application proof",
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
        validation.error(f"{missing}: missing owned-structure radius predicate contract")
    for extra in sorted(actual_keys - expected_keys):
        validation.error(f"{extra}: owned-structure radius contract has no exact RequiresOwnedStructureRadius profile")

    for row in profiles:
        effect_key = row.get("effectKey")
        if not isinstance(effect_key, str):
            validation.error(f"RequiresOwnedStructureRadius profile has invalid effectKey {effect_key!r}")
        elif not any(effect_key.startswith(prefix) for prefix in ("cove.", "fortress.", "necropolis.", "tower.")):
            validation.error(f"{effect_key}: RequiresOwnedStructureRadius is outside expected faction scope")
        if row.get("family") != "Vision":
            validation.error(f"{effect_key}: RequiresOwnedStructureRadius must remain in Vision family")

    for effect_key, contract in sorted(contracts.items()):
        if not isinstance(contract, dict):
            validation.error(f"{effect_key}: contract must be an object")
            continue
        origin_kinds = contract.get("originKinds")
        if not isinstance(origin_kinds, list) or not origin_kinds:
            validation.error(f"{effect_key}: originKinds must be a non-empty list")
            origin_kinds = []
        origin_text = "\n".join(str(item).lower() for item in origin_kinds if isinstance(item, str))
        if "owned-custom-city-or-dwelling-radius" not in origin_text:
            validation.error(f"{effect_key}: originKinds must require owned custom city or dwelling radius")
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
            "donor faction city counted as owned structure",
            "display-name structure inference",
            "sid substring structure inference",
            "structure proximity without owner proof",
        )
        for phrase in required_forbidden:
            if phrase not in forbidden_text:
                validation.error(f"{effect_key}: forbiddenSubstitutes must reject {phrase!r}")
        if "without radius proof" not in forbidden_text:
            validation.error(f"{effect_key}: forbiddenSubstitutes must reject target scans without radius proof")
        notes = contract.get("notes")
        if not isinstance(notes, str) or not notes:
            validation.error(f"{effect_key}: notes must be a non-empty string")
        elif "requires" not in notes.lower() or "runtime owner proof" not in notes.lower() or "radius" not in notes.lower():
            validation.error(f"{effect_key}: notes must state runtime owner and radius boundary")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contracts", type=Path, default=DEFAULT_CONTRACTS_PATH)
    parser.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY_PATH)
    parser.add_argument("--manifest-dir", type=Path, default=DEFAULT_MANIFEST_DIR)
    args = parser.parse_args()

    validation = Validation()
    doc = load_json(args.contracts)
    profiles = load_profiles(args.inventory)
    manifest_rows = load_enabled_manifest_rows(args.manifest_dir)
    validate_contracts(doc, profiles, manifest_rows, validation)
    print(f"owned-structure radius predicate contracts: {len(doc.get('contracts', {})) if isinstance(doc, dict) else 0} contract(s)")
    print(f"RequiresOwnedStructureRadius effect keys: {len(profile_effect_keys(profiles))} unique key(s)")
    print(f"RequiresOwnedStructureRadius profile rows: {len(profiles)}")
    print(f"enabled manifest structure rows: {len(manifest_rows)}")
    print(f"errors: {validation.errors}")
    if validation.warnings:
        print(f"warnings: {validation.warnings}")
    return 1 if validation.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())