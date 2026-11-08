#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
from validate_custom_faction_manifests import Validation, load_json  # noqa: E402

DEFAULT_CONTRACTS_PATH = ROOT / "custom_factions" / "conflux_elemental_consumer_predicate_contracts.json"
DEFAULT_INVENTORY_PATH = ROOT / "custom_factions" / "custom_law_effect_plan_inventory.json"
DEFAULT_MAPPING_PATH = ROOT / "custom_factions" / "elemental_family_mapping_predicate_contracts.json"
DEFAULT_BUILDINGS_PATH = ROOT / "custom_factions" / "construction_building_category_contracts.json"
DEFAULT_UNIT_TAGS_PATH = ROOT / "custom_factions" / "unit_family_tags.json"
PREDICATES = ("RequiresElementalFamily", "RequiresElementalBuildingMapping")


def load_profiles(path: Path, predicate: str) -> list[dict[str, Any]]:
    rows = load_json(path).get("rows", [])
    return [row for row in rows if isinstance(row, dict) and predicate in (row.get("requiredPredicates") or [])]


def keys(rows: list[dict[str, Any]]) -> set[str]:
    return {row["effectKey"] for row in rows if isinstance(row.get("effectKey"), str)}


def count_fact(tags: Any, fact: str, value: str) -> int:
    units = tags.get("units") if isinstance(tags, dict) else None
    if not isinstance(units, dict):
        return 0
    return sum(1 for row in units.values() if isinstance(row, dict) and row.get(fact) == value)


def validate(doc: Any, inventory_path: Path, mapping: Any, buildings: Any, tags: Any, v: Validation) -> None:
    if not isinstance(doc, dict):
        v.error("Conflux elemental consumer predicate contracts root must be object")
        return
    if doc.get("schemaVersion") != 1:
        v.error("schemaVersion must be 1")
    policy = doc.get("policy") if isinstance(doc.get("policy"), dict) else {}
    for key in (
        "contractsMustMatchExactPredicateProfiles",
        "confluxOnly",
        "elementalFamilyMustUseAuthoredFamilyMap",
        "elementalBuildingMustUseBuildingCategoryContract",
        "themeOrNameInferenceForbidden",
        "runtimeProofStillRequiredForGameplay",
    ):
        if policy.get(key) is not True:
            v.error(f"policy.{key} must be true")
    if sorted(doc.get("allowedFactions") or []) != ["homm3_conflux"]:
        v.error("allowedFactions must be exactly ['homm3_conflux']")
    if count_fact(tags, "elemental", "yes") <= 0:
        v.error("unit_family_tags must contain elemental=yes facts")
    mapping_families = (((mapping.get("requiredStaticEvidence") or {}).get("requiredElementalFamilies") or {}) if isinstance(mapping, dict) else {})
    for family in ("air", "water", "fire", "earth", "psychic"):
        if family not in mapping_families:
            v.error(f"elemental family mapping contract missing family {family!r}")
    conflux_buildings = (((buildings.get("contracts") or {}).get("homm3_conflux") or {}).get("groups") or {}) if isinstance(buildings, dict) else {}
    elemental_group = conflux_buildings.get("elemental-building")
    if not isinstance(elemental_group, list) or not elemental_group:
        v.error("construction building category contracts must provide homm3_conflux elemental-building rows")
    required_runtime = set(doc.get("requiredRuntimeProof") or [])
    for item in (
        "battle unit SID to elemental family proof",
        "selected elemental family to stat-aspect proof",
        "committed damage ordering proof",
        "construction city owner proof",
        "construction building SID or row proof",
        "committed construction ordering proof",
        "law-owner side correlation proof",
        "idempotent per-hit or per-build application proof",
    ):
        if item not in required_runtime:
            v.error(f"requiredRuntimeProof missing {item!r}")
    contracts = doc.get("contracts")
    if not isinstance(contracts, dict) or set(contracts) != set(PREDICATES):
        v.error(f"contracts must contain exactly {list(PREDICATES)!r}")
        return
    for predicate in PREDICATES:
        profiles = load_profiles(inventory_path, predicate)
        contract = contracts[predicate]
        expected_keys = keys(profiles)
        actual_keys = set(contract.get("requiredEffectKeys") or [])
        if actual_keys != expected_keys:
            v.error(f"{predicate}: requiredEffectKeys {sorted(actual_keys)!r} must match exact profile keys {sorted(expected_keys)!r}")
        allowed_families = set(contract.get("allowedFamilies") or [])
        for row in profiles:
            effect_key = row.get("effectKey")
            if row.get("factionSid") != "homm3_conflux":
                v.error(f"{predicate}/{effect_key}: must be Conflux-only")
            if row.get("family") not in allowed_families:
                v.error(f"{predicate}/{effect_key}: family {row.get('family')!r} outside allowedFamilies")
        forbidden = "\n".join(str(x).lower() for x in (contract.get("forbiddenSubstitutes") or []) if isinstance(x, str))
        if predicate == "RequiresElementalFamily":
            for phrase in (
                "Conflux faction membership counted as elemental family",
                "any elemental unit counted without specific family identity",
                "building elemental category counted as unit elemental family",
            ):
                if phrase.lower() not in forbidden:
                    v.error(f"{predicate}: forbiddenSubstitutes missing {phrase!r}")
        if predicate == "RequiresElementalBuildingMapping":
            for phrase in (
                "Conflux town membership counted as elemental building mapping",
                "building display name or icon counted as elemental building mapping",
                "unit elemental family counted as building elemental mapping",
                "construction UI preview counted as committed elemental building mapping",
            ):
                if phrase.lower() not in forbidden:
                    v.error(f"{predicate}: forbiddenSubstitutes missing {phrase!r}")
        profile_preds = set().union(*(row.get("requiredPredicates") or [] for row in profiles)) if profiles else set()
        for companion in contract.get("companionPredicates", []):
            if companion not in profile_preds:
                v.error(f"{predicate}: companion predicate {companion!r} is not on profile rows")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--contracts", type=Path, default=DEFAULT_CONTRACTS_PATH)
    ap.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY_PATH)
    ap.add_argument("--mapping", type=Path, default=DEFAULT_MAPPING_PATH)
    ap.add_argument("--buildings", type=Path, default=DEFAULT_BUILDINGS_PATH)
    ap.add_argument("--unit-tags", type=Path, default=DEFAULT_UNIT_TAGS_PATH)
    args = ap.parse_args()
    v = Validation()
    doc = load_json(args.contracts)
    validate(doc, args.inventory, load_json(args.mapping), load_json(args.buildings), load_json(args.unit_tags), v)
    print(f"Conflux elemental consumer predicate contracts: {len(doc.get('contracts', {})) if isinstance(doc, dict) else 0} predicate contract(s)")
    for predicate in PREDICATES:
        rows = load_profiles(args.inventory, predicate)
        print(f"{predicate}: {len(keys(rows))} unique key(s), {len(rows)} profile row(s)")
    print(f"errors: {v.errors}")
    return 1 if v.errors else 0

if __name__ == "__main__":
    raise SystemExit(main())
