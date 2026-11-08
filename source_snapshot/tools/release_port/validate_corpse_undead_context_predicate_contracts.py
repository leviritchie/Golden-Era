#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
from validate_custom_faction_manifests import Validation, load_json  # noqa: E402

DEFAULT_CONTRACTS_PATH = ROOT / "custom_factions" / "corpse_undead_context_predicate_contracts.json"
DEFAULT_INVENTORY_PATH = ROOT / "custom_factions" / "custom_law_effect_plan_inventory.json"
PREDICATE = "RequiresCorpseOrUndeadContext"


def load_profiles(path: Path) -> list[dict[str, Any]]:
    rows = load_json(path).get("rows", [])
    return [r for r in rows if isinstance(r, dict) and PREDICATE in (r.get("requiredPredicates") or [])]


def keys(rows: list[dict[str, Any]]) -> set[str]:
    return {r["effectKey"] for r in rows if isinstance(r.get("effectKey"), str)}


def validate(doc: Any, profiles: list[dict[str, Any]], v: Validation) -> None:
    if not isinstance(doc, dict):
        v.error("contract root must be an object")
        return
    if doc.get("schemaVersion") != 1:
        v.error("schemaVersion must be 1")
    policy = doc.get("policy") if isinstance(doc.get("policy"), dict) else {}
    for k in ("effectKeysMustMatchRequiresCorpseOrUndeadContextProfiles", "necropolisOnly", "moraleFamilyOnly", "undeadIdentityIsNotCorpseAvailability", "runtimeProofStillRequiredForGameplay"):
        if policy.get(k) is not True:
            v.error(f"policy.{k} must be true")
    if doc.get("allowedEffectKeyPrefixes") != ["necropolis."]:
        v.error("allowedEffectKeyPrefixes must be ['necropolis.']")
    if sorted(doc.get("allowedFamilies") or []) != ["MoralePackage", "MoraleTrigger"]:
        v.error("allowedFamilies must be MoralePackage/MoraleTrigger")
    req = set(doc.get("requiredRuntimeProof") or [])
    for item in ("undead unit identity proof when undead context is used", "corpse availability or corpse value proof when corpse context is used", "friendly undead morale bonus exclusion proof"):
        if item not in req:
            v.error(f"requiredRuntimeProof missing {item!r}")
    contracts = doc.get("contracts")
    if not isinstance(contracts, dict) or not contracts:
        v.error("contracts must be a non-empty object")
        return
    expected = keys(profiles)
    for missing in sorted(expected - set(contracts)):
        v.error(f"{missing}: missing contract")
    for extra in sorted(set(contracts) - expected):
        v.error(f"{extra}: extra contract")
    for row in profiles:
        if row.get("factionSid") != "homm3_necropolis":
            v.error(f"{row.get('effectKey')}: must be Necropolis-only")
        if row.get("family") not in ("MoralePackage", "MoraleTrigger"):
            v.error(f"{row.get('effectKey')}: must be morale family")
    for effect_key, c in sorted(contracts.items()):
        if not isinstance(c, dict):
            v.error(f"{effect_key}: contract must be object")
            continue
        text = "\n".join(str(x).lower() for x in c.get("contextKinds", []) if isinstance(x, str))
        if "corpse" not in text or "undead" not in text:
            v.error(f"{effect_key}: contextKinds must include corpse and undead")
        forbidden = "\n".join(str(x).lower() for x in c.get("forbiddenSubstitutes", []) if isinstance(x, str))
        for phrase in ("undead classification counted as corpse availability", "friendly undead morale bonus counted as dread pressure", "generic death event counted as corpse context"):
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
    print(f"corpse/undead context predicate contracts: {len(doc.get('contracts', {})) if isinstance(doc, dict) else 0} contract(s)")
    print(f"{PREDICATE} effect keys: {len(keys(profiles))} unique key(s)")
    print(f"{PREDICATE} profile rows: {len(profiles)}")
    print(f"errors: {v.errors}")
    return 1 if v.errors else 0

if __name__ == "__main__":
    raise SystemExit(main())
