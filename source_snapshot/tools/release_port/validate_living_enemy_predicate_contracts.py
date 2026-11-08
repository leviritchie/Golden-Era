#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
from validate_custom_faction_manifests import Validation, load_json  # noqa: E402

DEFAULT_CONTRACTS_PATH = ROOT / "custom_factions" / "living_enemy_predicate_contracts.json"
DEFAULT_INVENTORY_PATH = ROOT / "custom_factions" / "custom_law_effect_plan_inventory.json"
DEFAULT_UNIT_TAGS_PATH = ROOT / "custom_factions" / "unit_family_tags.json"
PREDICATE = "RequiresLivingEnemyPredicate"


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


def validate(doc: Any, profiles: list[dict[str, Any]], tags: Any, v: Validation) -> None:
    if not isinstance(doc, dict):
        v.error("living enemy predicate contracts root must be object")
        return
    if doc.get("schemaVersion") != 1:
        v.error("schemaVersion must be 1")
    policy = doc.get("policy") if isinstance(doc.get("policy"), dict) else {}
    for key in (
        "effectKeysMustMatchRequiresLivingEnemyPredicateProfiles",
        "necropolisOnly",
        "formationFamilyOnly",
        "livingUsesAuthoredUnitFactsOnly",
        "undeadOppositeMustNotBeUsedAsEnemyProof",
        "runtimeProofStillRequiredForGameplay",
    ):
        if policy.get(key) is not True:
            v.error(f"policy.{key} must be true")
    if sorted(doc.get("allowedFactions") or []) != ["homm3_necropolis"]:
        v.error("allowedFactions must be exactly ['homm3_necropolis']")
    if doc.get("allowedFamily") != "Formation":
        v.error("allowedFamily must be Formation")
    if count_fact(tags, "living", "yes") <= 0:
        v.error("unit_family_tags must contain living=yes facts")
    if count_fact(tags, "undead", "yes") <= 0:
        v.error("unit_family_tags must contain undead=yes facts for opposite-classifier guard")
    required_runtime = set(doc.get("requiredRuntimeProof") or [])
    for item in (
        "battle unit SID to authored living classifier correlation proof",
        "target side is enemy of law-owner side proof",
        "target stack identity proof",
        "living target is affected stack proof",
        "negative status application target correlation proof",
        "law-owner side correlation proof",
        "idempotent per-action application proof",
    ):
        if item not in required_runtime:
            v.error(f"requiredRuntimeProof missing {item!r}")
    contracts = doc.get("contracts")
    if not isinstance(contracts, dict) or not contracts:
        v.error("contracts must be non-empty object")
        return
    expected = keys(profiles)
    if set(contracts) != expected:
        v.error(f"contracts keys {sorted(contracts)!r} must match exact profile keys {sorted(expected)!r}")
    for row in profiles:
        effect_key = row.get("effectKey")
        if row.get("factionSid") != "homm3_necropolis":
            v.error(f"{effect_key}: must be Necropolis-only")
        if row.get("family") != "Formation":
            v.error(f"{effect_key}: must remain Formation")
        if "RequiresNegativeStatusPredicate" not in (row.get("requiredPredicates") or []):
            v.error(f"{effect_key}: must keep negative-status companion predicate")
    for effect_key, contract in sorted(contracts.items()):
        facts = contract.get("requiredStaticFacts") or []
        if "unit_family_tags.living=yes" not in facts:
            v.error(f"{effect_key}: requiredStaticFacts must include unit_family_tags.living=yes")
        forbidden = "\n".join(str(x).lower() for x in (contract.get("forbiddenSubstitutes") or []) if isinstance(x, str))
        for phrase in (
            "non-undead counted as living enemy without authored living fact",
            "enemy side counted as living enemy without unit sid proof",
            "negative status predicate counted as living enemy predicate",
        ):
            if phrase not in forbidden:
                v.error(f"{effect_key}: forbiddenSubstitutes missing {phrase!r}")
        profile_preds = set().union(*(row.get("requiredPredicates") or [] for row in profiles if row.get("effectKey") == effect_key))
        for companion in contract.get("companionPredicates", []):
            if companion not in profile_preds:
                v.error(f"{effect_key}: companion predicate {companion!r} is not on profile rows")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--contracts", type=Path, default=DEFAULT_CONTRACTS_PATH)
    ap.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY_PATH)
    ap.add_argument("--unit-tags", type=Path, default=DEFAULT_UNIT_TAGS_PATH)
    args = ap.parse_args()
    v = Validation()
    doc = load_json(args.contracts)
    profiles = load_profiles(args.inventory)
    validate(doc, profiles, load_json(args.unit_tags), v)
    print(f"living enemy predicate contracts: {len(doc.get('contracts', {})) if isinstance(doc, dict) else 0} contract(s)")
    print(f"{PREDICATE} effect keys: {len(keys(profiles))} unique key(s)")
    print(f"{PREDICATE} profile rows: {len(profiles)}")
    print(f"errors: {v.errors}")
    return 1 if v.errors else 0

if __name__ == "__main__":
    raise SystemExit(main())
