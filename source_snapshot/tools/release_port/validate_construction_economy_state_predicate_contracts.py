#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
from validate_custom_faction_manifests import Validation, load_json  # noqa: E402

DEFAULT_CONTRACTS_PATH = ROOT / "custom_factions" / "construction_economy_state_predicate_contracts.json"
DEFAULT_INVENTORY_PATH = ROOT / "custom_factions" / "custom_law_effect_plan_inventory.json"
PREDICATES = (
    "RequiresCaptureToken",
    "RequiresCaptureOrOwnershipTransfer",
    "RequiresPersistentMatureDwellingState",
    "RequiresGarrisonSacrifice",
    "RequiresDeathworksCredit",
    "RequiresRareResourceBalance",
)


def load_profiles(path: Path, predicate: str) -> list[dict[str, Any]]:
    rows = load_json(path).get("rows", [])
    return [row for row in rows if isinstance(row, dict) and predicate in (row.get("requiredPredicates") or [])]


def keys(rows: list[dict[str, Any]]) -> set[str]:
    return {row["effectKey"] for row in rows if isinstance(row.get("effectKey"), str)}


def _string_list(value: Any) -> list[str]:
    return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []


def validate(doc: Any, inventory_path: Path, v: Validation) -> None:
    if not isinstance(doc, dict):
        v.error("construction/economy state predicate contracts root must be object")
        return
    if doc.get("schemaVersion") != 1:
        v.error("schemaVersion must be 1")
    policy = doc.get("policy") if isinstance(doc.get("policy"), dict) else {}
    for key in (
        "contractsMustMatchExactPredicateProfiles",
        "transactionStatePredicatesAreNotNativeGameplayProof",
        "constructionPredicatesRequireCommittedConstructionProof",
        "rewardPredicatesRequireCommittedRewardOrOwnershipProof",
        "customLedgerPredicatesRequireExplicitSideScopedLedgerProof",
        "uiPreviewOrStaticReadSubstituteForbidden",
        "runtimeProofStillRequiredForGameplay",
    ):
        if policy.get(key) is not True:
            v.error(f"policy.{key} must be true")
    required_runtime = set(_string_list(doc.get("requiredRuntimeProof")))
    for item in (
        "active law-owner side correlation proof",
        "committed construction transaction proof",
        "committed reward or ownership transition proof",
        "displayed and charged cost parity proof where costs change",
        "side-scoped custom ledger read/write proof",
        "persistent state save/load or lifecycle proof",
        "idempotent per-transaction application proof",
        "transaction cancellation/preview exclusion proof",
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
        actual = set(_string_list(contract.get("requiredEffectKeys")))
        if actual != expected:
            v.error(f"{predicate}: requiredEffectKeys {sorted(actual)!r} must match exact profile keys {sorted(expected)!r}")
        allowed_factions = set(_string_list(contract.get("allowedFactions")))
        allowed_families = set(_string_list(contract.get("allowedFamilies")))
        if not allowed_factions:
            v.error(f"{predicate}: allowedFactions must be non-empty")
        if not allowed_families:
            v.error(f"{predicate}: allowedFamilies must be non-empty")
        for row in profiles:
            effect_key = row.get("effectKey")
            if row.get("factionSid") not in allowed_factions:
                v.error(f"{predicate}/{effect_key}: factionSid {row.get('factionSid')!r} outside allowedFactions")
            if row.get("family") not in allowed_families:
                v.error(f"{predicate}/{effect_key}: family {row.get('family')!r} outside allowedFamilies")
        semantics = "\n".join(item.lower() for item in _string_list(contract.get("requiredRuntimeSemantics")))
        forbidden = "\n".join(item.lower() for item in _string_list(contract.get("forbiddenSubstitutes")))
        if not semantics:
            v.error(f"{predicate}: requiredRuntimeSemantics must be non-empty")
        if not forbidden:
            v.error(f"{predicate}: forbiddenSubstitutes must be non-empty")
        for token in ("owner", "law owner"):
            if token not in semantics:
                v.error(f"{predicate}: requiredRuntimeSemantics must mention {token!r}")
        if "ui" not in forbidden and "preview" not in forbidden and "display" not in forbidden:
            v.error(f"{predicate}: forbiddenSubstitutes must reject UI/preview/display substitution")
        if predicate == "RequiresCaptureToken":
            for token in ("capture token", "consumed", "construction"):
                if token not in semantics:
                    v.error(f"{predicate}: requiredRuntimeSemantics must mention {token}")
            for phrase in ("building allowlist alone counted as a capture token", "ordinary ownership read counted without a transfer event"):
                if phrase not in forbidden:
                    v.error(f"{predicate}: forbiddenSubstitutes missing {phrase!r}")
        elif predicate == "RequiresCaptureOrOwnershipTransfer":
            for token in ("ownership transfer", "committed", "reward"):
                if token not in semantics:
                    v.error(f"{predicate}: requiredRuntimeSemantics must mention {token}")
            for phrase in ("map object owned by dungeon counted without transfer timing", "mine income tick counted as capture reward"):
                if phrase not in forbidden:
                    v.error(f"{predicate}: forbiddenSubstitutes missing {phrase!r}")
        elif predicate == "RequiresPersistentMatureDwellingState":
            for token in ("mature", "persistent", "dwelling"):
                if token not in semantics:
                    v.error(f"{predicate}: requiredRuntimeSemantics must mention {token}")
            for phrase in ("building allowlist alone counted as mature dwelling state", "any rampart dwelling counted as mature"):
                if phrase not in forbidden:
                    v.error(f"{predicate}: forbiddenSubstitutes missing {phrase!r}")
        elif predicate == "RequiresGarrisonSacrifice":
            for token in ("sacrifice", "garrison", "unit"):
                if token not in semantics:
                    v.error(f"{predicate}: requiredRuntimeSemantics must mention {token}")
            for phrase in ("garrison existence counted as sacrifice", "displayed cost discount counted without unit removal"):
                if phrase not in forbidden:
                    v.error(f"{predicate}: forbiddenSubstitutes missing {phrase!r}")
        elif predicate == "RequiresDeathworksCredit":
            for token in ("credit", "ledger", "construction"):
                if token not in semantics:
                    v.error(f"{predicate}: requiredRuntimeSemantics must mention {token}")
            for phrase in ("corpse count alone counted as deathworks credit", "building allowlist alone counted as credit"):
                if phrase not in forbidden:
                    v.error(f"{predicate}: forbiddenSubstitutes missing {phrase!r}")
        elif predicate == "RequiresRareResourceBalance":
            for token in ("rare-resource", "resource", "balance"):
                if token not in semantics:
                    v.error(f"{predicate}: requiredRuntimeSemantics must mention {token}")
            for phrase in ("resource primitive existence counted as rare-resource balance", "gold balance counted as rare resource"):
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
    print(f"construction/economy state predicate contracts: {len(doc.get('contracts', {})) if isinstance(doc, dict) else 0} predicate contract(s)")
    for predicate in PREDICATES:
        rows = load_profiles(args.inventory, predicate)
        print(f"{predicate}: {len(keys(rows))} unique key(s), {len(rows)} profile row(s)")
    print(f"errors: {v.errors}")
    return 1 if v.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
