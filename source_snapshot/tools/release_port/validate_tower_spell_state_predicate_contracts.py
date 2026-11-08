#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
from validate_custom_faction_manifests import Validation, load_json  # noqa: E402

DEFAULT_CONTRACTS_PATH = ROOT / "custom_factions" / "tower_spell_state_predicate_contracts.json"
DEFAULT_INVENTORY_PATH = ROOT / "custom_factions" / "custom_law_effect_plan_inventory.json"
PREDICATES = (
    "RequiresCastGateOverride",
    "RequiresCooldownMutation",
    "RequiresOverclockCredit",
    "RequiresSpellbookReuseState",
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
        v.error("Tower spell-state predicate contracts root must be object")
        return
    if doc.get("schemaVersion") != 1:
        v.error("schemaVersion must be 1")
    policy = doc.get("policy") if isinstance(doc.get("policy"), dict) else {}
    for key in (
        "contractsMustMatchExactPredicateProfiles",
        "towerOnly",
        "spellStatePredicatesAreNotCooldownProof",
        "castGateRequiresCommittedCastGateAndUiSyncProof",
        "cooldownMutationMustNotUseRejectedAbsoluteSetter",
        "overclockCreditRequiresExplicitSideScopedLedger",
        "spellbookReuseRequiresCommittedPreparedState",
        "runtimeProofStillRequiredForGameplay",
    ):
        if policy.get(key) is not True:
            v.error(f"policy.{key} must be true")
    rejected = "\n".join(item.lower() for item in string_list(doc.get("rejectedHypotheses")))
    for phrase in (
        "eew.bdmh(int32) absolute cooldown setter",
        "spellbook open or preview counted as cast gate override",
        "hero energy pool existence counted as overclock credit",
        "spellbook collection membership counted as prepared reuse state",
    ):
        if phrase not in rejected:
            v.error(f"rejectedHypotheses missing {phrase!r}")
    required_runtime = set(string_list(doc.get("requiredRuntimeProof")))
    for item in (
        "active Tower law-owner side correlation proof",
        "successful committed spell cast proof",
        "spell cooldown read timing proof",
        "safe cooldown decrement or mutation proof that does not use the rejected absolute setter",
        "cast gate override proof for otherwise blocked one-cooldown spells",
        "spellbook UI synchronization proof after cast-gate or cooldown mutation",
        "side-scoped overclock credit ledger read/write proof",
        "prepared spellbook reuse state creation and consumption proof",
        "spellbook preview/open/cancel exclusion proof",
        "idempotent per-cast or per-day application proof",
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
        if allowed_factions != {"homm3_tower"}:
            v.error(f"{predicate}: allowedFactions must be exactly ['homm3_tower']")
        if not allowed_families:
            v.error(f"{predicate}: allowedFamilies must be non-empty")
        for row in profiles:
            effect_key = row.get("effectKey")
            if row.get("factionSid") != "homm3_tower":
                v.error(f"{predicate}/{effect_key}: must remain Tower-only")
            if row.get("family") not in allowed_families:
                v.error(f"{predicate}/{effect_key}: family {row.get('family')!r} outside allowedFamilies")
        semantics = "\n".join(item.lower() for item in string_list(contract.get("requiredRuntimeSemantics")))
        forbidden = "\n".join(item.lower() for item in string_list(contract.get("forbiddenSubstitutes")))
        if not semantics:
            v.error(f"{predicate}: requiredRuntimeSemantics must be non-empty")
        if not forbidden:
            v.error(f"{predicate}: forbiddenSubstitutes must be non-empty")
        if "tower law owner" not in semantics:
            v.error(f"{predicate}: requiredRuntimeSemantics must mention Tower law owner")
        for phrase in ("spellbook preview", "tower faction membership"):
            if phrase not in forbidden:
                v.error(f"{predicate}: forbiddenSubstitutes must reject {phrase!r}")
        if predicate == "RequiresCastGateOverride":
            for token in ("cast gate override", "overclock credit", "successful cast"):
                if token not in semantics:
                    v.error(f"{predicate}: requiredRuntimeSemantics must mention {token}")
            for phrase in ("spellbook open counted as cast gate override", "cooldown preview counted as committed cast permission"):
                if phrase not in forbidden:
                    v.error(f"{predicate}: forbiddenSubstitutes missing {phrase!r}")
        elif predicate == "RequiresCooldownMutation":
            for token in ("cooldown mutation", "celestial calculus", "eew.bdmh(int32)"):
                if token not in semantics:
                    v.error(f"{predicate}: requiredRuntimeSemantics must mention {token}")
            for phrase in ("eew.bdmh(int32) absolute cooldown setter", "cooldown read counted as cooldown mutation"):
                if phrase not in forbidden:
                    v.error(f"{predicate}: forbiddenSubstitutes missing {phrase!r}")
        elif predicate == "RequiresOverclockCredit":
            for token in ("credit", "ledger", "hero"):
                if token not in semantics:
                    v.error(f"{predicate}: requiredRuntimeSemantics must mention {token}")
            for phrase in ("hero energy pool existence counted as overclock credit", "global overclock flag without hero or side correlation"):
                if phrase not in forbidden:
                    v.error(f"{predicate}: forbiddenSubstitutes missing {phrase!r}")
        elif predicate == "RequiresSpellbookReuseState":
            for token in ("prepared spellbook reuse state", "successful spell cast", "reuse consumption"):
                if token not in semantics:
                    v.error(f"{predicate}: requiredRuntimeSemantics must mention {token}")
            for phrase in ("spellbook collection membership counted as prepared reuse state", "native school access counted as prepared reuse state"):
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
    print(f"Tower spell-state predicate contracts: {len(doc.get('contracts', {})) if isinstance(doc, dict) else 0} predicate contract(s)")
    for predicate in PREDICATES:
        rows = load_profiles(args.inventory, predicate)
        print(f"{predicate}: {len(keys(rows))} unique key(s), {len(rows)} profile row(s)")
    print(f"errors: {v.errors}")
    return 1 if v.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
