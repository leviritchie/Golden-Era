#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
from validate_custom_faction_manifests import Validation, load_json  # noqa: E402

DEFAULT_CONTRACTS_PATH = ROOT / "custom_factions" / "protect_preserve_event_predicate_contracts.json"
DEFAULT_INVENTORY_PATH = ROOT / "custom_factions" / "custom_law_effect_plan_inventory.json"
DEFAULT_TAXONOMY_PATH = ROOT / "custom_factions" / "status_taxonomy_contracts.json"
PREDICATE = "RequiresProtectOrPreserveEvent"


def profiles(path: Path) -> list[dict[str, Any]]:
    rows = load_json(path).get("rows", [])
    return [row for row in rows if isinstance(row, dict) and PREDICATE in (row.get("requiredPredicates") or [])]


def keys(rows: list[dict[str, Any]]) -> set[str]:
    return {row["effectKey"] for row in rows if isinstance(row.get("effectKey"), str)}


def validate(doc: Any, inventory: Path, taxonomy: Any, v: Validation) -> None:
    if not isinstance(doc, dict):
        v.error("protect/preserve event predicate contracts root must be object")
        return
    if doc.get("schemaVersion") != 1:
        v.error("schemaVersion must be 1")
    policy = doc.get("policy") if isinstance(doc.get("policy"), dict) else {}
    for key in (
        "contractsMustMatchExactPredicateProfiles",
        "statusTaxonomyGroupMustExist",
        "coveredTagsMustMatchTaxonomyGroup",
        "actualEventOrderingStillRuntimeGated",
        "avengerAndKillLossRemainCompanionPredicates",
        "runtimeProofStillRequiredForGameplay",
    ):
        if policy.get(key) is not True:
            v.error(f"policy.{key} must be true")
    groups = taxonomy.get("predicateGroups") if isinstance(taxonomy, dict) else None
    if not isinstance(groups, dict):
        v.error("status taxonomy predicateGroups must be present")
        groups = {}
    contracts = doc.get("contracts")
    if not isinstance(contracts, dict) or set(contracts) != {PREDICATE}:
        v.error(f"contracts must contain exactly {[PREDICATE]!r}")
        return
    required_runtime = set(doc.get("requiredRuntimeProof") or [])
    for item in (
        "protect or preserve event identity proof",
        "protected or preserved ally receiver proof",
        "event ordering relative to kill/loss and Avenger mark proof",
        "law-owner side correlation proof",
        "morale package idempotence proof",
    ):
        if item not in required_runtime:
            v.error(f"requiredRuntimeProof missing {item!r}")
    rows = profiles(inventory)
    contract = contracts[PREDICATE]
    if set(contract.get("requiredEffectKeys") or []) != keys(rows):
        v.error(f"{PREDICATE}: requiredEffectKeys must match exact profile keys {sorted(keys(rows))!r}")
    allowed = set(contract.get("allowedFamilies") or [])
    for row in rows:
        if row.get("factionSid") != "homm3_rampart":
            v.error(f"{PREDICATE}/{row.get('effectKey')}: must be Rampart-only")
        if row.get("family") not in allowed:
            v.error(f"{PREDICATE}/{row.get('effectKey')}: family {row.get('family')!r} outside allowedFamilies")
        profile_preds = set(row.get("requiredPredicates") or [])
        for companion in contract.get("companionPredicates") or []:
            if companion not in profile_preds:
                v.error(f"{PREDICATE}: companion predicate {companion!r} missing from profile row {row.get('effectKey')}")
    group_name = contract.get("taxonomyGroup")
    group = groups.get(group_name) if isinstance(group_name, str) else None
    if not isinstance(group, dict):
        v.error(f"{PREDICATE}: taxonomyGroup {group_name!r} not found")
        group = {}
    if set(contract.get("requiredCoveredTags") or []) != set(group.get("coveredTags") or []):
        v.error(f"{PREDICATE}: requiredCoveredTags must exactly match taxonomy group coveredTags")
    if set(contract.get("requiredMissingTags") or []) != set(group.get("missingTags") or []):
        v.error(f"{PREDICATE}: requiredMissingTags must exactly match taxonomy group missingTags")
    forbidden = "\n".join(str(x).lower() for x in (contract.get("forbiddenSubstitutes") or []) if isinstance(x, str))
    for phrase in ("any positive status", "event ordering proof", "rampart faction membership", "avenger mark"):
        if phrase not in forbidden:
            v.error(f"{PREDICATE}: forbiddenSubstitutes missing {phrase!r}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--contracts", type=Path, default=DEFAULT_CONTRACTS_PATH)
    ap.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY_PATH)
    ap.add_argument("--taxonomy", type=Path, default=DEFAULT_TAXONOMY_PATH)
    args = ap.parse_args()
    v = Validation()
    doc = load_json(args.contracts)
    validate(doc, args.inventory, load_json(args.taxonomy), v)
    rows = profiles(args.inventory)
    print(f"protect/preserve event predicate contracts: {len(doc.get('contracts', {})) if isinstance(doc, dict) else 0} predicate contract(s)")
    print(f"{PREDICATE}: {len(keys(rows))} unique key(s), {len(rows)} profile row(s)")
    print(f"errors: {v.errors}")
    return 1 if v.errors else 0

if __name__ == "__main__":
    raise SystemExit(main())
