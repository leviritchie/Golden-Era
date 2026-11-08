#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
from validate_custom_faction_manifests import Validation, load_json  # noqa: E402

DEFAULT_CONTRACTS_PATH = ROOT / "custom_factions" / "fortress_status_context_predicate_contracts.json"
DEFAULT_INVENTORY_PATH = ROOT / "custom_factions" / "custom_law_effect_plan_inventory.json"
DEFAULT_TAXONOMY_PATH = ROOT / "custom_factions" / "status_taxonomy_contracts.json"
PREDICATES = ("RequiresDebuffedAttacker", "RequiresEnemySlowPoisonMireState")


def load_profiles(path: Path, predicate: str) -> list[dict[str, Any]]:
    rows = load_json(path).get("rows", [])
    return [row for row in rows if isinstance(row, dict) and predicate in (row.get("requiredPredicates") or [])]


def keys(rows: list[dict[str, Any]]) -> set[str]:
    return {row["effectKey"] for row in rows if isinstance(row.get("effectKey"), str)}


def validate(doc: Any, inventory_path: Path, taxonomy: Any, v: Validation) -> None:
    if not isinstance(doc, dict):
        v.error("Fortress status context predicate contracts root must be object")
        return
    if doc.get("schemaVersion") != 1:
        v.error("schemaVersion must be 1")
    policy = doc.get("policy") if isinstance(doc.get("policy"), dict) else {}
    for key in (
        "contractsMustMatchExactPredicateProfiles",
        "fortressOnly",
        "statusTaxonomyRequired",
        "taxonomyClassificationAloneIsNotLiveState",
        "mireStateRemainsRuntimeOnly",
        "runtimeProofStillRequiredForGameplay",
    ):
        if policy.get(key) is not True:
            v.error(f"policy.{key} must be true")
    if sorted(doc.get("allowedFactions") or []) != ["homm3_fortress"]:
        v.error("allowedFactions must be exactly ['homm3_fortress']")
    groups = set((taxonomy.get("predicateGroups") or {}).keys()) if isinstance(taxonomy, dict) else set()
    allowed_tags = set(taxonomy.get("allowedTags") or []) if isinstance(taxonomy, dict) else set()
    for group in ("negativeStatusPredicate", "poisonSlowMovementRestriction", "enemySlowPoisonMireState"):
        if group not in groups:
            v.error(f"status taxonomy missing predicate group {group!r}")
    for tag in ("negative", "poison", "slow", "movement_restriction"):
        if tag not in allowed_tags:
            v.error(f"status taxonomy missing allowed tag {tag!r}")
    enemy_group = ((taxonomy.get("predicateGroups") or {}).get("enemySlowPoisonMireState") or {}) if isinstance(taxonomy, dict) else {}
    if "mire" not in str(enemy_group.get("missingTags", "")).lower():
        v.error("status taxonomy enemySlowPoisonMireState must explicitly leave mire missing")
    required_runtime = set(doc.get("requiredRuntimeProof") or [])
    for item in (
        "attacker battle unit identity proof",
        "live attacker negative status query proof",
        "outgoing committed damage ordering proof",
        "enemy side versus law-owner side proof",
        "live enemy poison status query proof",
        "live enemy slow or movement-restriction status query proof",
        "mire terrain or state proof",
        "cooldown mutation or penalty ordering proof",
        "idempotent per-hit or per-cooldown application proof",
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
        expected = keys(profiles)
        actual = set(contract.get("requiredEffectKeys") or [])
        if actual != expected:
            v.error(f"{predicate}: requiredEffectKeys {sorted(actual)!r} must match exact profile keys {sorted(expected)!r}")
        allowed_families = set(contract.get("allowedFamilies") or [])
        for row in profiles:
            effect_key = row.get("effectKey")
            if row.get("factionSid") != "homm3_fortress":
                v.error(f"{predicate}/{effect_key}: must be Fortress-only")
            if row.get("family") not in allowed_families:
                v.error(f"{predicate}/{effect_key}: family {row.get('family')!r} outside allowedFamilies")
        status_groups = contract.get("requiredStatusGroups") or []
        for group in status_groups:
            if group not in groups:
                v.error(f"{predicate}: unknown requiredStatusGroup {group!r}")
        forbidden = "\n".join(str(x).lower() for x in (contract.get("forbiddenSubstitutes") or []) if isinstance(x, str))
        if predicate == "RequiresDebuffedAttacker":
            for phrase in (
                "status taxonomy classification counted as live debuffed attacker",
                "target debuff counted as attacker debuff",
                "damage event counted without attacker status query proof",
            ):
                if phrase not in forbidden:
                    v.error(f"{predicate}: forbiddenSubstitutes missing {phrase!r}")
        if predicate == "RequiresEnemySlowPoisonMireState":
            for phrase in (
                "status taxonomy classification counted as live enemy slow poison mire state",
                "friendly slow or poison status counted as enemy army state",
                "mire inferred from swamp flavor text or law name",
                "spell cooldown row counted without enemy state proof",
            ):
                if phrase not in forbidden:
                    v.error(f"{predicate}: forbiddenSubstitutes missing {phrase!r}")
            semantics = "\n".join(str(x).lower() for x in (contract.get("requiredRuntimeSemantics") or []) if isinstance(x, str))
            for token in ("poison", "slow", "mire"):
                if token not in semantics:
                    v.error(f"{predicate}: requiredRuntimeSemantics must mention {token}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--contracts", type=Path, default=DEFAULT_CONTRACTS_PATH)
    ap.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY_PATH)
    ap.add_argument("--taxonomy", type=Path, default=DEFAULT_TAXONOMY_PATH)
    args = ap.parse_args()
    v = Validation()
    doc = load_json(args.contracts)
    validate(doc, args.inventory, load_json(args.taxonomy), v)
    print(f"Fortress status context predicate contracts: {len(doc.get('contracts', {})) if isinstance(doc, dict) else 0} predicate contract(s)")
    for predicate in PREDICATES:
        rows = load_profiles(args.inventory, predicate)
        print(f"{predicate}: {len(keys(rows))} unique key(s), {len(rows)} profile row(s)")
    print(f"errors: {v.errors}")
    return 1 if v.errors else 0

if __name__ == "__main__":
    raise SystemExit(main())
