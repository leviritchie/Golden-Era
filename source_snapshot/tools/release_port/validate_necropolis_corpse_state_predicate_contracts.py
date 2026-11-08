#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
from validate_custom_faction_manifests import Validation, load_json  # noqa: E402

DEFAULT_CONTRACTS_PATH = ROOT / "custom_factions" / "necropolis_corpse_state_predicate_contracts.json"
DEFAULT_INVENTORY_PATH = ROOT / "custom_factions" / "custom_law_effect_plan_inventory.json"
PREDICATES = (
    "RequiresCorpseConsumption",
    "RequiresCorpseCount",
    "RequiresCorpseOrBattleSiteData",
    "RequiresCorpseOrRaiseConsumption",
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
        v.error("Necropolis corpse-state predicate contracts root must be object")
        return
    if doc.get("schemaVersion") != 1:
        v.error("schemaVersion must be 1")
    policy = doc.get("policy") if isinstance(doc.get("policy"), dict) else {}
    for key in (
        "contractsMustMatchExactPredicateProfiles",
        "necropolisOnly",
        "corpseStatePredicatesAreNotCorpseContextProof",
        "corpseConsumptionRequiresCommittedConsumptionEvent",
        "corpseCountRequiresLogicalCountSource",
        "battleSiteRevealRequiresExplicitObjectOrStateEvidence",
        "raiseConsumptionRequiresSpellOrRaiseEventCorrelation",
        "runtimeProofStillRequiredForGameplay",
    ):
        if policy.get(key) is not True:
            v.error(f"policy.{key} must be true")
    required_runtime = set(string_list(doc.get("requiredRuntimeProof")))
    for item in (
        "active Necropolis law-owner side correlation proof",
        "logical corpse availability source proof",
        "committed corpse consumption event proof",
        "corpse count read timing proof",
        "raise or corpse-consuming spell commit proof",
        "corpse or battle-site object identity proof",
        "friendly versus enemy corpse ownership policy proof",
        "temporary summon or gated loss exclusion proof",
        "corpse accounting idempotence proof",
        "corpse state cleanup or lifecycle proof",
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
        if not isinstance(contract, dict):
            v.error(f"{predicate}: contract must be object")
            continue
        expected = keys(profiles)
        actual = set(string_list(contract.get("requiredEffectKeys")))
        if actual != expected:
            v.error(f"{predicate}: requiredEffectKeys {sorted(actual)!r} must match exact profile keys {sorted(expected)!r}")
        allowed_factions = set(string_list(contract.get("allowedFactions")))
        allowed_families = set(string_list(contract.get("allowedFamilies")))
        if allowed_factions != {"homm3_necropolis"}:
            v.error(f"{predicate}: allowedFactions must be exactly ['homm3_necropolis']")
        if not allowed_families:
            v.error(f"{predicate}: allowedFamilies must be non-empty")
        for row in profiles:
            effect_key = row.get("effectKey")
            if row.get("factionSid") != "homm3_necropolis":
                v.error(f"{predicate}/{effect_key}: must remain Necropolis-only")
            if row.get("family") not in allowed_families:
                v.error(f"{predicate}/{effect_key}: family {row.get('family')!r} outside allowedFamilies")
        semantics = "\n".join(item.lower() for item in string_list(contract.get("requiredRuntimeSemantics")))
        forbidden = "\n".join(item.lower() for item in string_list(contract.get("forbiddenSubstitutes")))
        if not semantics:
            v.error(f"{predicate}: requiredRuntimeSemantics must be non-empty")
        if not forbidden:
            v.error(f"{predicate}: forbiddenSubstitutes must be non-empty")
        if "necropolis law owner" not in semantics:
            v.error(f"{predicate}: requiredRuntimeSemantics must mention Necropolis law owner")
        for phrase in ("undead unit identity", "temporary summoned loss"):
            if phrase not in forbidden:
                v.error(f"{predicate}: forbiddenSubstitutes must reject {phrase!r}")
        if predicate == "RequiresCorpseConsumption":
            for token in ("committed corpse consumption", "successful", "cooldown"):
                if token not in semantics:
                    v.error(f"{predicate}: requiredRuntimeSemantics must mention {token}")
            for phrase in ("corpse availability counted as corpse consumption", "spell classification counted without corpse consumption"):
                if phrase not in forbidden:
                    v.error(f"{predicate}: forbiddenSubstitutes missing {phrase!r}")
        elif predicate == "RequiresCorpseCount":
            for token in ("corpse count", "temporary mana", "cleaned up"):
                if token not in semantics:
                    v.error(f"{predicate}: requiredRuntimeSemantics must mention {token}")
            for phrase in ("undead unit count counted as corpse count", "generic casualty count counted as corpse count without corpse-production policy"):
                if phrase not in forbidden:
                    v.error(f"{predicate}: forbiddenSubstitutes missing {phrase!r}")
        elif predicate == "RequiresCorpseOrBattleSiteData":
            for token in ("corpse site", "battle site", "reveal"):
                if token not in semantics:
                    v.error(f"{predicate}: requiredRuntimeSemantics must mention {token}")
            for phrase in ("visual corpse inference counted as corpse or battle-site data", "object icon counted without exact object sid or state proof"):
                if phrase not in forbidden:
                    v.error(f"{predicate}: forbiddenSubstitutes missing {phrase!r}")
        elif predicate == "RequiresCorpseOrRaiseConsumption":
            for token in ("committed corpse consumption", "committed raise", "calendar"):
                if token not in semantics:
                    v.error(f"{predicate}: requiredRuntimeSemantics must mention {token}")
            for phrase in ("raise-capable spell classification counted without committed raise or corpse consumption", "calendar day refresh counted without raise or corpse event"):
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
    print(f"Necropolis corpse-state predicate contracts: {len(doc.get('contracts', {})) if isinstance(doc, dict) else 0} predicate contract(s)")
    for predicate in PREDICATES:
        rows = load_profiles(args.inventory, predicate)
        print(f"{predicate}: {len(keys(rows))} unique key(s), {len(rows)} profile row(s)")
    print(f"errors: {v.errors}")
    return 1 if v.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
