#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
from validate_custom_faction_manifests import Validation, load_json  # noqa: E402

DEFAULT_CONTRACTS_PATH = ROOT / "custom_factions" / "combat_scalar_state_predicate_contracts.json"
DEFAULT_INVENTORY_PATH = ROOT / "custom_factions" / "custom_law_effect_plan_inventory.json"
PREDICATES = (
    "RequiresHeroSpellPower",
    "RequiresPositiveMoraleValue",
    "RequiresWoundedUnit",
    "RequiresSeparateMagicDamageSurface",
)


def load_profiles(path: Path, predicate: str) -> list[dict[str, Any]]:
    rows = load_json(path).get("rows", [])
    return [row for row in rows if isinstance(row, dict) and predicate in (row.get("requiredPredicates") or [])]


def keys(rows: list[dict[str, Any]]) -> set[str]:
    return {row["effectKey"] for row in rows if isinstance(row.get("effectKey"), str)}


def string_list(value: Any) -> list[str]:
    return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []


def validate(doc: Any, inventory_path: Path, v: Validation) -> None:
    if not isinstance(doc, dict):
        v.error("combat scalar/state predicate contracts root must be object")
        return
    if doc.get("schemaVersion") != 1:
        v.error("schemaVersion must be 1")
    policy = doc.get("policy") if isinstance(doc.get("policy"), dict) else {}
    for key in (
        "contractsMustMatchExactPredicateProfiles",
        "combatScalarPredicatesAreNotAdjacentEventProof",
        "heroSpellPowerRequiresDefendingHeroStatRead",
        "positiveMoraleRequiresCurrentPositiveMoraleValue",
        "woundedUnitRequiresLiveHealthThreshold",
        "separateMagicDamageRequiresDistinctDamageComponent",
        "runtimeProofStillRequiredForGameplay",
    ):
        if policy.get(key) is not True:
            v.error(f"policy.{key} must be true")
    required_runtime = set(string_list(doc.get("requiredRuntimeProof")))
    for item in (
        "active law-owner side correlation proof",
        "battle unit identity proof",
        "hero stat owner and timing proof",
        "current positive morale value proof",
        "live health and max-health threshold proof",
        "separate magic damage component proof",
        "physical damage folding exclusion proof",
        "post-mitigation damage ordering proof",
        "turn-order or stat refresh safety proof",
        "idempotent per-hit or per-refresh application proof",
    ):
        if item not in required_runtime:
            v.error(f"requiredRuntimeProof missing {item!r}")
    contracts = doc.get("contracts")
    if not isinstance(contracts, dict) or set(contracts) != set(PREDICATES):
        v.error(f"contracts must contain exactly {list(PREDICATES)!r}")
        return
    expected_factions = {
        "RequiresHeroSpellPower": "homm3_tower",
        "RequiresPositiveMoraleValue": "homm3_castle",
        "RequiresWoundedUnit": "homm3_stronghold",
        "RequiresSeparateMagicDamageSurface": "homm3_conflux",
    }
    expected_families = {
        "RequiresHeroSpellPower": {"CounterattackDoctrine"},
        "RequiresPositiveMoraleValue": {"TrainingDamage"},
        "RequiresWoundedUnit": {"TrainingDamage"},
        "RequiresSeparateMagicDamageSurface": {"CounterattackDoctrine"},
    }
    for predicate in PREDICATES:
        profiles = load_profiles(inventory_path, predicate)
        contract = contracts[predicate]
        if not isinstance(contract, dict):
            v.error(f"{predicate}: contract must be object")
            continue
        expected = keys(profiles)
        actual = set(string_list(contract.get("requiredEffectKeys")))
        if actual != expected:
            v.error(f"{predicate}: requiredEffectKeys {sorted(actual)!r} must match exact profile keys {sorted(expected)!r}")
        allowed_factions = set(string_list(contract.get("allowedFactions")))
        allowed_families = set(string_list(contract.get("allowedFamilies")))
        if allowed_factions != {expected_factions[predicate]}:
            v.error(f"{predicate}: allowedFactions must be exactly {[expected_factions[predicate]]!r}")
        if allowed_families != expected_families[predicate]:
            v.error(f"{predicate}: allowedFamilies must be exactly {sorted(expected_families[predicate])!r}")
        for row in profiles:
            effect_key = row.get("effectKey")
            if row.get("factionSid") != expected_factions[predicate]:
                v.error(f"{predicate}/{effect_key}: factionSid {row.get('factionSid')!r} outside expected faction")
            if row.get("family") not in expected_families[predicate]:
                v.error(f"{predicate}/{effect_key}: family {row.get('family')!r} outside allowedFamilies")
        semantics = "\n".join(item.lower() for item in string_list(contract.get("requiredRuntimeSemantics")))
        forbidden = "\n".join(item.lower() for item in string_list(contract.get("forbiddenSubstitutes")))
        if not semantics:
            v.error(f"{predicate}: requiredRuntimeSemantics must be non-empty")
        if not forbidden:
            v.error(f"{predicate}: forbiddenSubstitutes must be non-empty")
        if "law owner" not in semantics:
            v.error(f"{predicate}: requiredRuntimeSemantics must mention law owner")
        if "faction membership" not in forbidden:
            v.error(f"{predicate}: forbiddenSubstitutes must reject faction membership")
        if predicate == "RequiresHeroSpellPower":
            for token in ("spell power", "defending", "counterattack"):
                if token not in semantics:
                    v.error(f"{predicate}: requiredRuntimeSemantics must mention {token}")
            for phrase in ("hero skill flag counted as hero spell power value", "attacking hero stat counted for defender reactive ward"):
                if phrase not in forbidden:
                    v.error(f"{predicate}: forbiddenSubstitutes missing {phrase!r}")
        elif predicate == "RequiresPositiveMoraleValue":
            for token in ("positive morale", "damage", "current"):
                if token not in semantics:
                    v.error(f"{predicate}: requiredRuntimeSemantics must mention {token}")
            for phrase in ("morale roll animation counted as positive morale value", "non-positive morale counted as positive morale value"):
                if phrase not in forbidden:
                    v.error(f"{predicate}: forbiddenSubstitutes missing {phrase!r}")
        elif predicate == "RequiresWoundedUnit":
            for token in ("wounded", "health", "speed"):
                if token not in semantics:
                    v.error(f"{predicate}: requiredRuntimeSemantics must mention {token}")
            for phrase in ("damage taken event counted as wounded state without current health proof", "dead or dying unit counted as wounded unit"):
                if phrase not in forbidden:
                    v.error(f"{predicate}: forbiddenSubstitutes missing {phrase!r}")
        elif predicate == "RequiresSeparateMagicDamageSurface":
            for token in ("separate magic damage", "physical", "attribution"):
                if token not in semantics:
                    v.error(f"{predicate}: requiredRuntimeSemantics must mention {token}")
            for phrase in ("physical counterattack damage scalar counted as separate magic damage", "magic config row counted without runtime damage component proof"):
                if phrase not in forbidden:
                    v.error(f"{predicate}: forbiddenSubstitutes missing {phrase!r}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--contracts", type=Path, default=DEFAULT_CONTRACTS_PATH)
    ap.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY_PATH)
    args = ap.parse_args()
    v = Validation()
    doc = load_json(args.contracts)
    validate(doc, args.inventory, v)
    print(f"combat scalar/state predicate contracts: {len(doc.get('contracts', {})) if isinstance(doc, dict) else 0} predicate contract(s)")
    for predicate in PREDICATES:
        rows = load_profiles(args.inventory, predicate)
        print(f"{predicate}: {len(keys(rows))} unique key(s), {len(rows)} profile row(s)")
    print(f"errors: {v.errors}")
    return 1 if v.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
