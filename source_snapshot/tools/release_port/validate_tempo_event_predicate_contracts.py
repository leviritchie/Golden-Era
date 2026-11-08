#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
from validate_custom_faction_manifests import Validation, load_json  # noqa: E402

DEFAULT_CONTRACTS_PATH = ROOT / "custom_factions" / "tempo_event_predicate_contracts.json"
DEFAULT_INVENTORY_PATH = ROOT / "custom_factions" / "custom_law_effect_plan_inventory.json"
PREDICATES = (
    "RequiresFirstVolley",
    "RequiresFocusEvent",
    "RequiresWarcryOrRageEvent",
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
        v.error("tempo event predicate contracts root must be object")
        return
    if doc.get("schemaVersion") != 1:
        v.error("schemaVersion must be 1")
    policy = doc.get("policy") if isinstance(doc.get("policy"), dict) else {}
    for key in (
        "contractsMustMatchExactPredicateProfiles",
        "tempoPredicatesAreNotGenericLifecycleProof",
        "firstVolleyRequiresFirstQualifyingCommittedAction",
        "focusEventRequiresCommittedFocusGenerationOrSpend",
        "warcryOrRageRequiresExplicitTempoEvent",
        "runtimeProofStillRequiredForGameplay",
    ):
        if policy.get(key) is not True:
            v.error(f"policy.{key} must be true")
    required_runtime = set(string_list(doc.get("requiredRuntimeProof")))
    for item in (
        "active law-owner side correlation proof",
        "battle start and round ordering proof",
        "acting unit identity proof",
        "first qualifying action discriminator proof",
        "committed ranged attack or volley proof",
        "committed Focus generation or spend event proof",
        "Focus recipient and owner correlation proof",
        "committed Warcry execution or Rage tempo event proof",
        "damage/kill companion event ordering proof for Rage",
        "idempotent per-battle, per-round, or per-event application proof",
    ):
        if item not in required_runtime:
            v.error(f"requiredRuntimeProof missing {item!r}")
    contracts = doc.get("contracts")
    if not isinstance(contracts, dict) or set(contracts) != set(PREDICATES):
        v.error(f"contracts must contain exactly {list(PREDICATES)!r}")
        return
    expected = {
        "RequiresFirstVolley": ("homm3_cove", "Formation"),
        "RequiresFocusEvent": ("homm3_cove", "Calendar"),
        "RequiresWarcryOrRageEvent": ("homm3_stronghold", "MoralePackage"),
    }
    for predicate in PREDICATES:
        profiles = load_profiles(inventory_path, predicate)
        contract = contracts[predicate]
        if not isinstance(contract, dict):
            v.error(f"{predicate}: contract must be object")
            continue
        actual_keys = set(string_list(contract.get("requiredEffectKeys")))
        expected_keys = keys(profiles)
        if actual_keys != expected_keys:
            v.error(f"{predicate}: requiredEffectKeys {sorted(actual_keys)!r} must match exact profile keys {sorted(expected_keys)!r}")
        faction, family = expected[predicate]
        if set(string_list(contract.get("allowedFactions"))) != {faction}:
            v.error(f"{predicate}: allowedFactions must be exactly {[faction]!r}")
        if set(string_list(contract.get("allowedFamilies"))) != {family}:
            v.error(f"{predicate}: allowedFamilies must be exactly {[family]!r}")
        for row in profiles:
            effect_key = row.get("effectKey")
            if row.get("factionSid") != faction:
                v.error(f"{predicate}/{effect_key}: factionSid {row.get('factionSid')!r} outside expected faction")
            if row.get("family") != family:
                v.error(f"{predicate}/{effect_key}: family {row.get('family')!r} outside expected family")
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
        if predicate == "RequiresFirstVolley":
            for token in ("first qualifying", "committed", "first-volley"):
                if token not in semantics:
                    v.error(f"{predicate}: requiredRuntimeSemantics must mention {token}")
            for phrase in ("passive all-ranged bonus counted as first volley", "any ranged attack counted as first volley without first-action state"):
                if phrase not in forbidden:
                    v.error(f"{predicate}: forbiddenSubstitutes missing {phrase!r}")
        elif predicate == "RequiresFocusEvent":
            for token in ("committed focus", "recipient", "storm omens"):
                if token not in semantics:
                    v.error(f"{predicate}: requiredRuntimeSemantics must mention {token}")
            for phrase in ("hero energy pool existence counted as focus event", "focus ui value counted as committed focus event"):
                if phrase not in forbidden:
                    v.error(f"{predicate}: forbiddenSubstitutes missing {phrase!r}")
        elif predicate == "RequiresWarcryOrRageEvent":
            for token in ("committed stronghold warcry", "rage", "damage/kill"):
                if token not in semantics:
                    v.error(f"{predicate}: requiredRuntimeSemantics must mention {token}")
            for phrase in ("morale animation counted as warcry or rage event", "static warcry skill ownership counted as warcry execution"):
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
    print(f"tempo event predicate contracts: {len(doc.get('contracts', {})) if isinstance(doc, dict) else 0} predicate contract(s)")
    for predicate in PREDICATES:
        rows = load_profiles(args.inventory, predicate)
        print(f"{predicate}: {len(keys(rows))} unique key(s), {len(rows)} profile row(s)")
    print(f"errors: {v.errors}")
    return 1 if v.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
