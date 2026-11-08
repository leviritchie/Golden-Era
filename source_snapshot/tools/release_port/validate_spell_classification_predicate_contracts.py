#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
from validate_custom_faction_manifests import Validation, load_json  # noqa: E402

DEFAULT_CONTRACTS_PATH = ROOT / "custom_factions" / "spell_classification_predicate_contracts.json"
DEFAULT_INVENTORY_PATH = ROOT / "custom_factions" / "custom_law_effect_plan_inventory.json"
DEFAULT_TAXONOMY_PATH = ROOT / "custom_factions" / "spell_taxonomy_contracts.json"
PREDICATES = ("RequiresMovementStormSeaClassification", "RequiresNightCurseClassification", "RequiresSupportBlessingClassification")


def profiles(path: Path, predicate: str) -> list[dict[str, Any]]:
    rows = load_json(path).get("rows", [])
    return [row for row in rows if isinstance(row, dict) and predicate in (row.get("requiredPredicates") or [])]


def keys(rows: list[dict[str, Any]]) -> set[str]:
    return {row["effectKey"] for row in rows if isinstance(row.get("effectKey"), str)}


def validate(doc: Any, inventory: Path, taxonomy: Any, v: Validation) -> None:
    if not isinstance(doc, dict):
        v.error("spell classification predicate contracts root must be object")
        return
    if doc.get("schemaVersion") != 1:
        v.error("schemaVersion must be 1")
    policy = doc.get("policy") if isinstance(doc.get("policy"), dict) else {}
    for key in (
        "contractsMustMatchExactPredicateProfiles",
        "spellTaxonomyGroupsMustExist",
        "coveredTagsMustMatchTaxonomyGroups",
        "missingTagsMustRemainExplicit",
        "oceanTravelInferenceForbidden",
        "genericSchoolMatchForbidden",
        "runtimeProofStillRequiredForGameplay",
    ):
        if policy.get(key) is not True:
            v.error(f"policy.{key} must be true")
    groups = taxonomy.get("predicateGroups") if isinstance(taxonomy, dict) else None
    if not isinstance(groups, dict):
        v.error("spell taxonomy predicateGroups must be present")
        groups = {}
    contracts = doc.get("contracts")
    if not isinstance(contracts, dict) or set(contracts) != set(PREDICATES):
        v.error(f"contracts must contain exactly {list(PREDICATES)!r}")
        return
    required_runtime = set(doc.get("requiredRuntimeProof") or [])
    for item in (
        "spell runtime identity proof",
        "spell taxonomy lookup proof in the consuming packet",
        "caster law-owner correlation proof",
        "cooldown read/mutation ordering proof",
        "spellbook UI preview exclusion proof",
        "idempotent per-spell application proof",
    ):
        if item not in required_runtime:
            v.error(f"requiredRuntimeProof missing {item!r}")
    for predicate in PREDICATES:
        rows = profiles(inventory, predicate)
        contract = contracts[predicate]
        actual = set(contract.get("requiredEffectKeys") or [])
        expected = keys(rows)
        if actual != expected:
            v.error(f"{predicate}: requiredEffectKeys {sorted(actual)!r} must match exact profile keys {sorted(expected)!r}")
        allowed = set(contract.get("allowedFamilies") or [])
        for row in rows:
            if row.get("family") not in allowed:
                v.error(f"{predicate}/{row.get('effectKey')}: family {row.get('family')!r} outside allowedFamilies")
            profile_preds = set(row.get("requiredPredicates") or [])
            for companion in contract.get("companionPredicates") or []:
                if companion not in profile_preds:
                    v.error(f"{predicate}: companion predicate {companion!r} missing from profile row {row.get('effectKey')}")
        group_name = contract.get("taxonomyGroup")
        group = groups.get(group_name) if isinstance(group_name, str) else None
        if not isinstance(group, dict):
            v.error(f"{predicate}: taxonomyGroup {group_name!r} not found")
            group = {}
        covered = set(contract.get("requiredCoveredTags") or [])
        missing = set(contract.get("requiredMissingTags") or [])
        if covered != set(group.get("coveredTags") or []):
            v.error(f"{predicate}: requiredCoveredTags must exactly match taxonomy group coveredTags")
        if missing != set(group.get("missingTags") or []):
            v.error(f"{predicate}: requiredMissingTags must exactly match taxonomy group missingTags")
        forbidden = "\n".join(str(x).lower() for x in (contract.get("forbiddenSubstitutes") or []) if isinstance(x, str))
        if "substring" not in forbidden:
            v.error(f"{predicate}: forbiddenSubstitutes must reject SID substring inference")
        if "cooldown preview" not in forbidden:
            v.error(f"{predicate}: forbiddenSubstitutes must reject cooldown preview substitutes")
        if predicate == "RequiresMovementStormSeaClassification" and "ocean travel" not in forbidden:
            v.error(f"{predicate}: forbiddenSubstitutes must reject ocean travel inference")
        if predicate == "RequiresSupportBlessingClassification" and "morale" not in "\n".join(missing).lower() + forbidden:
            v.error(f"{predicate}: morale gap must remain explicit")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--contracts", type=Path, default=DEFAULT_CONTRACTS_PATH)
    ap.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY_PATH)
    ap.add_argument("--taxonomy", type=Path, default=DEFAULT_TAXONOMY_PATH)
    args = ap.parse_args()
    v = Validation()
    doc = load_json(args.contracts)
    validate(doc, args.inventory, load_json(args.taxonomy), v)
    print(f"spell classification predicate contracts: {len(doc.get('contracts', {})) if isinstance(doc, dict) else 0} predicate contract(s)")
    for predicate in PREDICATES:
        rows = profiles(args.inventory, predicate)
        print(f"{predicate}: {len(keys(rows))} unique key(s), {len(rows)} profile row(s)")
    print(f"errors: {v.errors}")
    return 1 if v.errors else 0

if __name__ == "__main__":
    raise SystemExit(main())
