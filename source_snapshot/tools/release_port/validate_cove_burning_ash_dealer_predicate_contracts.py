#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
from validate_custom_faction_manifests import Validation, load_json  # noqa: E402

DEFAULT_CONTRACTS_PATH = ROOT / "custom_factions" / "cove_burning_ash_dealer_predicate_contracts.json"
DEFAULT_INVENTORY_PATH = ROOT / "custom_factions" / "custom_law_effect_plan_inventory.json"
DEFAULT_UNIT_TAGS_PATH = ROOT / "custom_factions" / "unit_family_tags.json"
PREDICATES = ("RequiresGunpowderDealer",)


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


def validate(doc: Any, inventory_path: Path, tags: Any, v: Validation) -> None:
    if not isinstance(doc, dict):
        v.error("Cove Burning Ash dealer predicate contracts root must be object")
        return
    if doc.get("schemaVersion") != 1:
        v.error("schemaVersion must be 1")
    policy = doc.get("policy") if isinstance(doc.get("policy"), dict) else {}
    for key in (
        "contractsMustMatchExactPredicateProfiles",
        "coveOnly",
        "trainingDamageFamilyOnly",
        "gunpowderUsesAuthoredUnitFactsOnly",        "nameOrSidInferenceForbidden",
        "customAshStateAvoidsNativeBuffMutation",
        "runtimeProofStillRequiredForGameplay",
    ):
        if policy.get(key) is not True:
            v.error(f"policy.{key} must be true")
    if sorted(doc.get("allowedFactions") or []) != ["homm3_cove"]:
        v.error("allowedFactions must be exactly ['homm3_cove']")
    if doc.get("allowedFamily") != "TrainingDamage":
        v.error("allowedFamily must be TrainingDamage")
    if count_fact(tags, "gunpowder", "yes") <= 0:
        v.error("unit_family_tags must contain gunpowder=yes facts")
    allowed_facts = set(tags.get("allowedFacts") or []) if isinstance(tags, dict) else set()
    for unsupported in ("cannon", "pirate", "dealer"):
        if unsupported in allowed_facts:
            v.error(f"unexpected unit_family_tags fact {unsupported!r}; update contract before using it")
    required_runtime = set(doc.get("requiredRuntimeProof") or [])
    for item in (
        "attacker battle unit SID proof",
        "attacker unit SID to authored gunpowder classifier proof",
        "committed positive damage event proof",
        "target stack identity proof",
        "custom battle-local ash state proof",
        "law-owner side correlation proof",
        "idempotent per-hit application proof",
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
        for row in profiles:
            effect_key = row.get("effectKey")
            if row.get("factionSid") != "homm3_cove":
                v.error(f"{predicate}/{effect_key}: must be Cove-only")
            if row.get("family") != "TrainingDamage":
                v.error(f"{predicate}/{effect_key}: must remain TrainingDamage")
        forbidden = "\n".join(str(x).lower() for x in (contract.get("forbiddenSubstitutes") or []) if isinstance(x, str))
        if predicate == "RequiresGunpowderDealer":
            for phrase in (
                "unit SID or display name containing gunpowder counted as gunpowder dealer",
                "Cove faction membership counted as gunpowder dealer",
                "shooter role counted as gunpowder dealer",
            ):
                if phrase.lower() not in forbidden:
                    v.error(f"{predicate}: forbiddenSubstitutes missing {phrase!r}")
            facts = contract.get("requiredStaticFacts") or []
            if "unit_family_tags.gunpowder=yes" not in facts:
                v.error(f"{predicate}: requiredStaticFacts must include unit_family_tags.gunpowder=yes")

        profile_preds = set().union(*(row.get("requiredPredicates") or [] for row in profiles)) if profiles else set()
        for companion in contract.get("companionPredicates", []):
            if companion not in profile_preds:
                v.error(f"{predicate}: companion predicate {companion!r} is not on profile rows")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--contracts", type=Path, default=DEFAULT_CONTRACTS_PATH)
    ap.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY_PATH)
    ap.add_argument("--unit-tags", type=Path, default=DEFAULT_UNIT_TAGS_PATH)
    args = ap.parse_args()
    v = Validation()
    doc = load_json(args.contracts)
    validate(doc, args.inventory, load_json(args.unit_tags), v)
    print(f"Cove Burning Ash dealer predicate contracts: {len(doc.get('contracts', {})) if isinstance(doc, dict) else 0} predicate contract(s)")
    for predicate in PREDICATES:
        rows = load_profiles(args.inventory, predicate)
        print(f"{predicate}: {len(keys(rows))} unique key(s), {len(rows)} profile row(s)")
    print(f"errors: {v.errors}")
    return 1 if v.errors else 0

if __name__ == "__main__":
    raise SystemExit(main())
