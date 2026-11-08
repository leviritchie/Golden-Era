#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
from validate_custom_faction_manifests import Validation, load_json  # noqa: E402

DEFAULT_CONTRACTS_PATH = ROOT / "custom_factions" / "vision_map_edge_predicate_contracts.json"
DEFAULT_INVENTORY_PATH = ROOT / "custom_factions" / "custom_law_effect_plan_inventory.json"
PREDICATES = (
    "RequiresRoadTerrain",
    "RequiresReadOnlyTooltipPreview",
    "RequiresExistingMapObjectClasses",
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
        v.error("vision map-edge predicate contracts root must be object")
        return
    if doc.get("schemaVersion") != 1:
        v.error("schemaVersion must be 1")
    policy = doc.get("policy") if isinstance(doc.get("policy"), dict) else {}
    for key in (
        "contractsMustMatchExactPredicateProfiles",
        "visionMapEdgePredicatesAreNotFogMutationProof",
        "roadTerrainRequiresNativeTerrainRead",
        "readOnlyTooltipPreviewMustRemainNonGameplay",
        "existingMapObjectClassesMustNotFabricateMechanics",
        "runtimeProofStillRequiredForGameplay",
    ):
        if policy.get(key) is not True:
            v.error(f"policy.{key} must be true")
    required_runtime = set(string_list(doc.get("requiredRuntimeProof")))
    for item in (
        "active law-owner side correlation proof",
        "adventure hero position proof",
        "native road terrain or road flag read proof",
        "read-only tooltip preview boundary proof",
        "native neutral data source proof when preview displays neutral intention",
        "existing map object runtime identity proof",
        "object class allowlist proof",
        "fog reveal mutation ordering proof where reveal is used",
        "map refresh and idempotence proof",
        "nonexistent mechanic fabrication exclusion proof",
    ):
        if item not in required_runtime:
            v.error(f"requiredRuntimeProof missing {item!r}")
    contracts = doc.get("contracts")
    if not isinstance(contracts, dict) or set(contracts) != set(PREDICATES):
        v.error(f"contracts must contain exactly {list(PREDICATES)!r}")
        return
    expected_factions = {
        "RequiresRoadTerrain": "homm3_castle",
        "RequiresReadOnlyTooltipPreview": "homm3_dungeon",
        "RequiresExistingMapObjectClasses": "homm3_inferno",
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
        if allowed_families != {"Vision"}:
            v.error(f"{predicate}: allowedFamilies must be exactly ['Vision']")
        for row in profiles:
            effect_key = row.get("effectKey")
            if row.get("factionSid") != expected_factions[predicate]:
                v.error(f"{predicate}/{effect_key}: factionSid {row.get('factionSid')!r} outside expected faction")
            if row.get("family") != "Vision":
                v.error(f"{predicate}/{effect_key}: family must remain Vision")
            values = row.get("values")
            if not isinstance(values, dict):
                v.error(f"{predicate}/{effect_key}: values must be object")
            else:
                for key in ("TriggerContext",):
                    if not isinstance(values.get(key), str) or not values.get(key):
                        v.error(f"{predicate}/{effect_key}: values.{key} must remain explicit")
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
        if predicate == "RequiresRoadTerrain":
            for token in ("native road", "hero coordinates", "always-on"):
                if token not in semantics and token not in forbidden:
                    v.error(f"{predicate}: semantics/forbidden text must mention {token}")
            for phrase in ("always-on view radius counted as road terrain", "road-looking map art counted as road terrain"):
                if phrase not in forbidden:
                    v.error(f"{predicate}: forbiddenSubstitutes missing {phrase!r}")
        elif predicate == "RequiresReadOnlyTooltipPreview":
            for token in ("read-only", "not mutate", "neutral stack identity"):
                if token not in semantics:
                    v.error(f"{predicate}: requiredRuntimeSemantics must mention {token}")
            for phrase in ("read-only tooltip preview counted as gameplay mutation", "tooltip text parsed as native neutral data"):
                if phrase not in forbidden:
                    v.error(f"{predicate}: forbiddenSubstitutes missing {phrase!r}")
        elif predicate == "RequiresExistingMapObjectClasses":
            for token in ("existing runtime map objects", "object allowlist", "must not create"):
                if token not in semantics:
                    v.error(f"{predicate}: requiredRuntimeSemantics must mention {token}")
            for phrase in ("fabricated teleport mechanic counted as existing map object class", "fabricated ocean travel mechanic counted as existing map object class"):
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
    print(f"vision map-edge predicate contracts: {len(doc.get('contracts', {})) if isinstance(doc, dict) else 0} predicate contract(s)")
    for predicate in PREDICATES:
        rows = load_profiles(args.inventory, predicate)
        print(f"{predicate}: {len(keys(rows))} unique key(s), {len(rows)} profile row(s)")
    print(f"errors: {v.errors}")
    return 1 if v.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
