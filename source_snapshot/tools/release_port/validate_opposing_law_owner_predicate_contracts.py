#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
from validate_custom_faction_manifests import Validation, load_json  # noqa: E402

DEFAULT_CONTRACTS_PATH = ROOT / "custom_factions" / "opposing_law_owner_predicate_contracts.json"
DEFAULT_INVENTORY_PATH = ROOT / "custom_factions" / "custom_law_effect_plan_inventory.json"
PREDICATE = "RequiresOpposingLawOwner"


def load_profiles(path: Path) -> list[dict[str, Any]]:
    return [r for r in load_json(path).get("rows", []) if isinstance(r, dict) and PREDICATE in (r.get("requiredPredicates") or [])]


def keys(rows: list[dict[str, Any]]) -> set[str]:
    return {r["effectKey"] for r in rows if isinstance(r.get("effectKey"), str)}


def validate(doc: Any, profiles: list[dict[str, Any]], v: Validation) -> None:
    if not isinstance(doc, dict):
        v.error("contract root must be object")
        return
    if doc.get("schemaVersion") != 1:
        v.error("schemaVersion must be 1")
    policy = doc.get("policy") if isinstance(doc.get("policy"), dict) else {}
    for k in ("effectKeysMustMatchRequiresOpposingLawOwnerProfiles", "moraleTriggerFamilyOnly", "opposingLawOwnerRequired", "unitOwnedMoraleGateSubstituteForbidden", "runtimeProofStillRequiredForGameplay"):
        if policy.get(k) is not True:
            v.error(f"policy.{k} must be true")
    if sorted(doc.get("allowedFactions") or []) != ["homm3_dungeon", "homm3_necropolis"]:
        v.error("allowedFactions must be Dungeon/Necropolis")
    if doc.get("allowedFamily") != "MoraleTrigger":
        v.error("allowedFamily must be MoraleTrigger")
    req = set(doc.get("requiredRuntimeProof") or [])
    for item in ("triggering unit side proof", "opposing side law owner proof", "active opposing law and rank proof", "positive friendly morale candidate exclusion proof"):
        if item not in req:
            v.error(f"requiredRuntimeProof missing {item!r}")
    contracts = doc.get("contracts")
    if not isinstance(contracts, dict) or not contracts:
        v.error("contracts must be non-empty object")
        return
    expected = keys(profiles)
    for missing in sorted(expected - set(contracts)):
        v.error(f"{missing}: missing contract")
    for extra in sorted(set(contracts) - expected):
        v.error(f"{extra}: extra contract")
    for row in profiles:
        if row.get("family") != "MoraleTrigger":
            v.error(f"{row.get('effectKey')}: must be MoraleTrigger")
        if row.get("factionSid") not in ("homm3_dungeon", "homm3_necropolis"):
            v.error(f"{row.get('effectKey')}: faction outside expected scope")
        if (row.get("values") or {}).get("UsesPositiveCandidate") is not False:
            v.error(f"{row.get('effectKey')}: must reject positive candidate")
    for effect_key, c in sorted(contracts.items()):
        if not isinstance(c, dict):
            v.error(f"{effect_key}: contract must be object")
            continue
        text = "\n".join(str(x).lower() for x in c.get("ownerKinds", []) if isinstance(x, str))
        if "opposing" not in text or "law-owner" not in text:
            v.error(f"{effect_key}: ownerKinds must include opposing law-owner")
        forbidden = "\n".join(str(x).lower() for x in c.get("forbiddenSubstitutes", []) if isinstance(x, str))
        for phrase in ("triggering unit owner counted as opposing law owner", "friendly law owner counted for enemy failure trigger", "positive morale candidate counted for opposing law owner"):
            if phrase not in forbidden:
                v.error(f"{effect_key}: forbiddenSubstitutes missing {phrase!r}")
        profile_preds = set().union(*(r.get("requiredPredicates") or [] for r in profiles if r.get("effectKey") == effect_key))
        for p in c.get("companionPredicates", []):
            if p not in profile_preds:
                v.error(f"{effect_key}: companion predicate {p!r} not on profile")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--contracts", type=Path, default=DEFAULT_CONTRACTS_PATH)
    ap.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY_PATH)
    args = ap.parse_args()
    v = Validation()
    doc = load_json(args.contracts)
    profiles = load_profiles(args.inventory)
    validate(doc, profiles, v)
    print(f"opposing law owner predicate contracts: {len(doc.get('contracts', {})) if isinstance(doc, dict) else 0} contract(s)")
    print(f"{PREDICATE} effect keys: {len(keys(profiles))} unique key(s)")
    print(f"{PREDICATE} profile rows: {len(profiles)}")
    print(f"errors: {v.errors}")
    return 1 if v.errors else 0

if __name__ == "__main__":
    raise SystemExit(main())
