#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
from validate_custom_faction_manifests import Validation, load_json  # noqa: E402

DEFAULT_CONTRACTS_PATH = ROOT / "custom_factions" / "dynamic_elemental_family_predicate_contracts.json"
DEFAULT_INVENTORY_PATH = ROOT / "custom_factions" / "custom_law_effect_plan_inventory.json"
DEFAULT_MAPPING_PATH = ROOT / "custom_factions" / "elemental_family_mapping_predicate_contracts.json"
DEFAULT_UNIT_TAGS_PATH = ROOT / "custom_factions" / "unit_family_tags.json"
PREDICATE = "RequiresDynamicElementalFamily"


def load_profiles(path: Path) -> list[dict[str, Any]]:
    rows = load_json(path).get("rows", [])
    return [row for row in rows if isinstance(row, dict) and PREDICATE in (row.get("requiredPredicates") or [])]


def keys(rows: list[dict[str, Any]]) -> set[str]:
    return {row["effectKey"] for row in rows if isinstance(row.get("effectKey"), str)}


def count_fact(tags: Any, fact: str, value: str) -> int:
    units = tags.get("units") if isinstance(tags, dict) else None
    if not isinstance(units, dict):
        return 0
    return sum(1 for row in units.values() if isinstance(row, dict) and row.get(fact) == value)


def validate(doc: Any, profiles: list[dict[str, Any]], mapping: Any, tags: Any, v: Validation) -> None:
    if not isinstance(doc, dict):
        v.error("dynamic elemental family predicate contracts root must be object")
        return
    if doc.get("schemaVersion") != 1:
        v.error("schemaVersion must be 1")
    policy = doc.get("policy") if isinstance(doc.get("policy"), dict) else {}
    for key in (
        "effectKeysMustMatchRequiresDynamicElementalFamilyProfiles",
        "confluxOnly",
        "spellSchoolFamilyOnly",
        "dynamicSelectionMustUseExplicitElementalFamilyMap",
        "staticSchoolProxySubstituteForbidden",
        "runtimeProofStillRequiredForGameplay",
    ):
        if policy.get(key) is not True:
            v.error(f"policy.{key} must be true")
    if sorted(doc.get("allowedFactions") or []) != ["homm3_conflux"]:
        v.error("allowedFactions must be exactly ['homm3_conflux']")
    if doc.get("allowedFamily") != "SpellSchool":
        v.error("allowedFamily must be SpellSchool")
    if count_fact(tags, "elemental", "yes") <= 0:
        v.error("unit_family_tags must contain elemental=yes facts")
    mapping_families = (((mapping.get("requiredStaticEvidence") or {}).get("requiredElementalFamilies") or {}) if isinstance(mapping, dict) else {})
    for family in ("air", "water", "fire", "earth", "psychic"):
        if family not in mapping_families:
            v.error(f"elemental family mapping contract missing family {family!r}")
    required_runtime = set(doc.get("requiredRuntimeProof") or [])
    for item in (
        "dominant elemental family computation proof",
        "live army or battle stack unit SID proof",
        "elemental family to spell school selection proof",
        "spell cast owner and law-owner correlation proof",
        "static magicSchoolSet proxy exclusion proof",
        "spellbook access or cooldown ordering proof",
        "idempotent dynamic family application proof",
    ):
        if item not in required_runtime:
            v.error(f"requiredRuntimeProof missing {item!r}")
    contracts = doc.get("contracts")
    if not isinstance(contracts, dict) or set(contracts) != keys(profiles):
        v.error(f"contracts must match exact profile keys {sorted(keys(profiles))!r}")
        return
    for row in profiles:
        effect_key = row.get("effectKey")
        if row.get("factionSid") != "homm3_conflux":
            v.error(f"{effect_key}: must be Conflux-only")
        if row.get("family") != "SpellSchool":
            v.error(f"{effect_key}: must remain SpellSchool")
        if "RequiresSpellCastEvent" not in (row.get("requiredPredicates") or []):
            v.error(f"{effect_key}: must keep spell-cast companion predicate")
    for effect_key, contract in sorted(contracts.items()):
        forbidden = "\n".join(str(x).lower() for x in (contract.get("forbiddenSubstitutes") or []) if isinstance(x, str))
        for phrase in (
            "static magicSchoolSet row counted as dynamic elemental family",
            "Conflux faction membership counted as dynamic elemental family",
            "any elemental unit counted without family dominance computation",
        ):
            if phrase.lower() not in forbidden:
                v.error(f"{effect_key}: forbiddenSubstitutes missing {phrase!r}")
        profile_preds = set().union(*(row.get("requiredPredicates") or [] for row in profiles if row.get("effectKey") == effect_key))
        for companion in contract.get("companionPredicates", []):
            if companion not in profile_preds:
                v.error(f"{effect_key}: companion predicate {companion!r} is not on profile rows")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--contracts", type=Path, default=DEFAULT_CONTRACTS_PATH)
    ap.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY_PATH)
    ap.add_argument("--mapping", type=Path, default=DEFAULT_MAPPING_PATH)
    ap.add_argument("--unit-tags", type=Path, default=DEFAULT_UNIT_TAGS_PATH)
    args = ap.parse_args()
    v = Validation()
    doc = load_json(args.contracts)
    profiles = load_profiles(args.inventory)
    validate(doc, profiles, load_json(args.mapping), load_json(args.unit_tags), v)
    print(f"dynamic elemental family predicate contracts: {len(doc.get('contracts', {})) if isinstance(doc, dict) else 0} contract(s)")
    print(f"{PREDICATE} effect keys: {len(keys(profiles))} unique key(s)")
    print(f"{PREDICATE} profile rows: {len(profiles)}")
    print(f"errors: {v.errors}")
    return 1 if v.errors else 0

if __name__ == "__main__":
    raise SystemExit(main())
