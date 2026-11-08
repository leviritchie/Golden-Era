#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
from validate_custom_faction_manifests import Validation, load_json  # noqa: E402

DEFAULT_CONTRACTS_PATH = ROOT / "custom_factions" / "forward_movement_kill_predicate_contracts.json"
DEFAULT_INVENTORY_PATH = ROOT / "custom_factions" / "custom_law_effect_plan_inventory.json"
PREDICATE = "RequiresForwardMovementOrKill"


def load_profiles(path: Path) -> list[dict[str, Any]]:
    rows = load_json(path).get("rows", [])
    return [row for row in rows if isinstance(row, dict) and PREDICATE in (row.get("requiredPredicates") or [])]


def keys(rows: list[dict[str, Any]]) -> set[str]:
    return {row["effectKey"] for row in rows if isinstance(row.get("effectKey"), str)}


def validate(doc: Any, profiles: list[dict[str, Any]], v: Validation) -> None:
    if not isinstance(doc, dict):
        v.error("forward movement/kill predicate contracts root must be object")
        return
    if doc.get("schemaVersion") != 1:
        v.error("schemaVersion must be 1")
    policy = doc.get("policy") if isinstance(doc.get("policy"), dict) else {}
    for key in (
        "effectKeysMustMatchRequiresForwardMovementOrKillProfiles",
        "strongholdOnly",
        "formationFamilyOnly",
        "forwardMovementRequiresBoardDirectionProof",
        "killRequiresCommittedKillProof",
        "negativeStatusSubstituteForbidden",
        "runtimeProofStillRequiredForGameplay",
    ):
        if policy.get(key) is not True:
            v.error(f"policy.{key} must be true")
    if sorted(doc.get("allowedFactions") or []) != ["homm3_stronghold"]:
        v.error("allowedFactions must be exactly ['homm3_stronghold']")
    if doc.get("allowedFamily") != "Formation":
        v.error("allowedFamily must be Formation")
    required_runtime = set(doc.get("requiredRuntimeProof") or [])
    for item in (
        "acting stack identity proof",
        "law-owner side correlation proof",
        "battle board coordinate before action proof",
        "battle board coordinate after action proof",
        "forward direction relative to opposing side proof",
        "committed kill event proof",
        "kill victim identity proof",
        "negative status application target correlation proof",
        "idempotent per-action application proof",
    ):
        if item not in required_runtime:
            v.error(f"requiredRuntimeProof missing {item!r}")
    contracts = doc.get("contracts")
    if not isinstance(contracts, dict) or set(contracts) != keys(profiles):
        v.error(f"contracts must match exact profile keys {sorted(keys(profiles))!r}")
        return
    for row in profiles:
        effect_key = row.get("effectKey")
        if row.get("factionSid") != "homm3_stronghold":
            v.error(f"{effect_key}: must be Stronghold-only")
        if row.get("family") != "Formation":
            v.error(f"{effect_key}: must remain Formation")
        if "RequiresNegativeStatusPredicate" not in (row.get("requiredPredicates") or []):
            v.error(f"{effect_key}: must keep negative-status companion predicate")
    for effect_key, contract in sorted(contracts.items()):
        kinds = "\n".join(str(x).lower() for x in (contract.get("requiredEventKinds") or []) if isinstance(x, str))
        if "forward" not in kinds or "kill" not in kinds:
            v.error(f"{effect_key}: requiredEventKinds must include forward movement and committed kill")
        forbidden = "\n".join(str(x).lower() for x in (contract.get("forbiddenSubstitutes") or []) if isinstance(x, str))
        for phrase in (
            "any movement counted as forward movement",
            "attack action counted as forward movement without coordinate delta proof",
            "kill preview or lethal damage estimate counted as committed kill",
            "negative status predicate counted as forward movement or kill",
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
    args = ap.parse_args()
    v = Validation()
    doc = load_json(args.contracts)
    profiles = load_profiles(args.inventory)
    validate(doc, profiles, v)
    print(f"forward movement/kill predicate contracts: {len(doc.get('contracts', {})) if isinstance(doc, dict) else 0} contract(s)")
    print(f"{PREDICATE} effect keys: {len(keys(profiles))} unique key(s)")
    print(f"{PREDICATE} profile rows: {len(profiles)}")
    print(f"errors: {v.errors}")
    return 1 if v.errors else 0

if __name__ == "__main__":
    raise SystemExit(main())
