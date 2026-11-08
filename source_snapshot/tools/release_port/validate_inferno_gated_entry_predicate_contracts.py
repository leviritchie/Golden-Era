#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
from validate_custom_faction_manifests import Validation, load_json  # noqa: E402

DEFAULT_CONTRACTS_PATH = ROOT / "custom_factions" / "inferno_gated_entry_predicate_contracts.json"
DEFAULT_INVENTORY_PATH = ROOT / "custom_factions" / "custom_law_effect_plan_inventory.json"
PREDICATE = "RequiresGatedIdentity"


def load_profiles(path: Path) -> list[dict[str, Any]]:
    rows = load_json(path).get("rows", [])
    return [row for row in rows if isinstance(row, dict) and PREDICATE in (row.get("requiredPredicates") or [])]


def keys(rows: list[dict[str, Any]]) -> set[str]:
    return {row["effectKey"] for row in rows if isinstance(row.get("effectKey"), str)}


def validate(doc: Any, inventory_path: Path, v: Validation) -> None:
    if not isinstance(doc, dict):
        v.error("Inferno gated-entry predicate contracts root must be object")
        return
    if doc.get("schemaVersion") != 1:
        v.error("schemaVersion must be 1")
    policy = doc.get("policy") if isinstance(doc.get("policy"), dict) else {}
    for key in (
        "contractsMustMatchExactPredicateProfiles",
        "infernoOnly",
        "trainingDamageOnly",
        "gatedEntryIdentityRequired",
        "permanentRecruitedUnitSubstituteForbidden",
        "gatedOrSummonedUnitTagShortcutForbidden",
        "runtimeProofStillRequiredForGameplay",
    ):
        if policy.get(key) is not True:
            v.error(f"policy.{key} must be true")
    if sorted(doc.get("allowedFactions") or []) != ["homm3_inferno"]:
        v.error("allowedFactions must be exactly ['homm3_inferno']")
    required_runtime = set(doc.get("requiredRuntimeProof") or [])
    for item in (
        "gating spawn or entry transaction proof",
        "acting gated stack identity proof",
        "permanent recruited unit exclusion proof",
        "law-owner side correlation proof",
        "committed damage ordering proof",
        "idempotent per-entry or per-attack application proof",
    ):
        if item not in required_runtime:
            v.error(f"requiredRuntimeProof missing {item!r}")
    contracts = doc.get("contracts")
    if not isinstance(contracts, dict) or set(contracts) != {PREDICATE}:
        v.error(f"contracts must contain exactly {[PREDICATE]!r}")
        return
    profiles = load_profiles(inventory_path)
    contract = contracts[PREDICATE]
    expected_keys = keys(profiles)
    actual_keys = set(contract.get("requiredEffectKeys") or [])
    if actual_keys != expected_keys:
        v.error(f"{PREDICATE}: requiredEffectKeys {sorted(actual_keys)!r} must match exact profile keys {sorted(expected_keys)!r}")
    allowed_families = set(contract.get("allowedFamilies") or [])
    for row in profiles:
        effect_key = row.get("effectKey")
        if row.get("factionSid") != "homm3_inferno":
            v.error(f"{PREDICATE}/{effect_key}: must be Inferno-only")
        if row.get("family") not in allowed_families:
            v.error(f"{PREDICATE}/{effect_key}: family {row.get('family')!r} outside allowedFamilies")
        if row.get("packet") != "committed-damage":
            v.error(f"{PREDICATE}/{effect_key}: packet must remain committed-damage")
        boundary = str(row.get("evidenceBoundary") or "").lower()
        if "gating" not in boundary or "permanent recruited units must not be affected" not in boundary:
            v.error(f"{PREDICATE}/{effect_key}: evidenceBoundary must preserve Gating identity and permanent recruited exclusion")
    forbidden = "\n".join(str(x).lower() for x in (contract.get("forbiddenSubstitutes") or []) if isinstance(x, str))
    for phrase in (
        "inferno faction membership counted as gated entry identity",
        "gatedorsummoned unit tag counted as gated entry proof",
        "permanent recruited inferno unit counted as gated entry identity",
        "damage event without acting gated stack proof counted as gated identity",
    ):
        if phrase not in forbidden:
            v.error(f"{PREDICATE}: forbiddenSubstitutes missing {phrase!r}")
    semantics = set(contract.get("requiredRuntimeSemantics") or [])
    for item in (
        "gating spawn or entry identity",
        "acting gated stack identity",
        "permanent recruited unit exclusion",
        "law-owner side correlation",
        "committed damage ordering",
    ):
        if item not in semantics:
            v.error(f"{PREDICATE}: requiredRuntimeSemantics missing {item!r}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--contracts", type=Path, default=DEFAULT_CONTRACTS_PATH)
    ap.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY_PATH)
    args = ap.parse_args()
    v = Validation()
    doc = load_json(args.contracts)
    validate(doc, args.inventory, v)
    rows = load_profiles(args.inventory)
    print(f"Inferno gated-entry predicate contracts: {len(doc.get('contracts', {})) if isinstance(doc, dict) else 0} predicate contract(s)")
    print(f"{PREDICATE}: {len(keys(rows))} unique key(s), {len(rows)} profile row(s)")
    print(f"errors: {v.errors}")
    return 1 if v.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
