#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
from validate_custom_faction_manifests import Validation, load_json  # noqa: E402

DEFAULT_CONTRACTS_PATH = ROOT / "custom_factions" / "dungeon_target_state_predicate_contracts.json"
DEFAULT_INVENTORY_PATH = ROOT / "custom_factions" / "custom_law_effect_plan_inventory.json"
PREDICATES = ("RequiresIsolatedTarget", "RequiresTargetOutnumbered")


def load_profiles(path: Path, predicate: str) -> list[dict[str, Any]]:
    rows = load_json(path).get("rows", [])
    return [row for row in rows if isinstance(row, dict) and predicate in (row.get("requiredPredicates") or [])]


def keys(rows: list[dict[str, Any]]) -> set[str]:
    return {row["effectKey"] for row in rows if isinstance(row.get("effectKey"), str)}


def validate(doc: Any, inventory_path: Path, v: Validation) -> None:
    if not isinstance(doc, dict):
        v.error("Dungeon target-state predicate contracts root must be object")
        return
    if doc.get("schemaVersion") != 1:
        v.error("schemaVersion must be 1")
    policy = doc.get("policy") if isinstance(doc.get("policy"), dict) else {}
    for key in ("contractsMustMatchExactPredicateProfiles", "dungeonOnly", "isolatedTargetRequiresCurrentBoardGeometry", "outnumberedTargetRequiresLiveStackComparison", "genericAdjacencyOrArmySizeSubstituteForbidden", "runtimeProofStillRequiredForGameplay"):
        if policy.get(key) is not True:
            v.error(f"policy.{key} must be true")
    if sorted(doc.get("allowedFactions") or []) != ["homm3_dungeon"]:
        v.error("allowedFactions must be exactly ['homm3_dungeon']")
    required_runtime = set(doc.get("requiredRuntimeProof") or [])
    for item in ("current action target identity proof", "current target board coordinate proof", "complete adjacent-neighbor scan proof", "isolated target predicate truth table proof", "acting or law-owner stack identity proof", "target stack count proof", "live count comparison timing proof", "counterattack or doctrine action correlation proof", "committed damage ordering proof", "law-owner side correlation proof", "idempotent per-action application proof"):
        if item not in required_runtime:
            v.error(f"requiredRuntimeProof missing {item!r}")
    contracts = doc.get("contracts")
    if not isinstance(contracts, dict) or set(contracts) != set(PREDICATES):
        v.error(f"contracts must contain exactly {list(PREDICATES)!r}")
        return
    for predicate in PREDICATES:
        profiles = load_profiles(inventory_path, predicate)
        contract = contracts[predicate]
        expected = keys(profiles)
        actual = set(contract.get("requiredEffectKeys") or [])
        if actual != expected:
            v.error(f"{predicate}: requiredEffectKeys {sorted(actual)!r} must match exact profile keys {sorted(expected)!r}")
        allowed_families = set(contract.get("allowedFamilies") or [])
        for row in profiles:
            effect_key = row.get("effectKey")
            if row.get("factionSid") != "homm3_dungeon":
                v.error(f"{predicate}/{effect_key}: must be Dungeon-only")
            if row.get("family") not in allowed_families:
                v.error(f"{predicate}/{effect_key}: family {row.get('family')!r} outside allowedFamilies")
        forbidden = "\n".join(str(x).lower() for x in (contract.get("forbiddenSubstitutes") or []) if isinstance(x, str))
        semantics = "\n".join(str(x).lower() for x in (contract.get("requiredRuntimeSemantics") or []) if isinstance(x, str))
        if predicate == "RequiresIsolatedTarget":
            for token in ("target", "geometry"):
                if token not in semantics:
                    v.error(f"{predicate}: requiredRuntimeSemantics must mention {token}")
            for phrase in ("any non-adjacent target counted as isolated without full neighbor scan", "global enemy count counted as target isolation", "damage event counted without target geometry proof"):
                if phrase not in forbidden:
                    v.error(f"{predicate}: forbiddenSubstitutes missing {phrase!r}")
        if predicate == "RequiresTargetOutnumbered":
            for token in ("target", "stack", "count"):
                if token not in semantics:
                    v.error(f"{predicate}: requiredRuntimeSemantics must mention {token}")
            for phrase in ("smaller army counted as target outnumbered", "lower tier counted as target outnumbered", "global friendly/enemy unit counts counted as target outnumbered", "counterattack event counted without target stack count proof"):
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
    print(f"Dungeon target-state predicate contracts: {len(doc.get('contracts', {})) if isinstance(doc, dict) else 0} predicate contract(s)")
    for predicate in PREDICATES:
        rows = load_profiles(args.inventory, predicate)
        print(f"{predicate}: {len(keys(rows))} unique key(s), {len(rows)} profile row(s)")
    print(f"errors: {v.errors}")
    return 1 if v.errors else 0

if __name__ == "__main__":
    raise SystemExit(main())
