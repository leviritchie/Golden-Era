#!/usr/bin/env python3
"""Validate the June 25 HoMM3 custom unit balance adjustment contract."""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import pathlib
import re
import sys
import zipfile
from typing import Any

EXPECTED_ENTRY_COUNT = 211
BALANCE_CONTRACT = pathlib.Path("custom_factions/contracts/homm3_unit_balance_adjustments_20260625.json")
RECOMMENDATION_DOC = pathlib.Path("docs/homm3_custom_unit_balance_recommendations_20260625.md")
SNAPSHOT_CSV = pathlib.Path("artifacts/balance_audit_20260625/custom_rows_named.csv")
STAT_KEYS = {"hp", "offence", "defence", "damageMin", "damageMax", "initiative", "speed", "squadValue"}
FACTION_SIDS = {
    "Neutral Custom Unit": "neutral",
    "Castle": "homm3_castle",
    "Rampart": "homm3_rampart",
    "Tower": "homm3_tower",
    "Inferno": "homm3_inferno",
    "Necropolis": "homm3_necropolis",
    "Dungeon": "homm3_dungeon",
    "Stronghold": "homm3_stronghold",
    "Fortress": "homm3_fortress",
    "Cove": "homm3_cove",
    "Conflux": "homm3_conflux",
}


def fail(message: str) -> None:
    print(f"homm3-unit-balance-adjustment-contract: {message}", file=sys.stderr)
    raise SystemExit(1)


def load_json(path: pathlib.Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception as ex:  # noqa: BLE001 - validators should fail closed with source text.
        fail(f"cannot read JSON {path}: {ex}")


def load_snapshot(repo_root: pathlib.Path) -> tuple[dict[tuple[str, str], dict[str, str]], dict[str, dict[str, str]]]:
    by_faction_name: dict[tuple[str, str], dict[str, str]] = {}
    by_sid: dict[str, dict[str, str]] = {}
    path = repo_root / SNAPSHOT_CSV
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                by_faction_name[(row["faction"], row["name"])] = row
                by_sid[row["id"]] = row
    except Exception as ex:  # noqa: BLE001
        fail(f"cannot read snapshot CSV {path}: {ex}")
    return by_faction_name, by_sid


def parse_recommendations(repo_root: pathlib.Path) -> list[dict[str, Any]]:
    by_faction_name, by_sid = load_snapshot(repo_root)
    path = repo_root / RECOMMENDATION_DOC
    text = path.read_text(encoding="utf-8-sig")
    rows: list[dict[str, Any]] = []
    current_faction = ""
    current_tier = 0
    for line in text.splitlines():
        match = re.match(r"^## (.+?) - (.+)$", line)
        if match:
            current_faction = match.group(1)
            continue
        if line == "## Neutral Custom Unit":
            current_faction = "Neutral Custom Unit"
            current_tier = 5
            continue
        match = re.match(r"^### Tier (\d+) - (.+)$", line)
        if match:
            current_tier = int(match.group(1))
            continue
        match = re.match(r"^- ([^:]+): (.+?) Implementation target: (.+)$", line)
        if not match:
            continue
        unit_name = match.group(1).strip()
        faction_sid = FACTION_SIDS.get(current_faction)
        if faction_sid is None:
            fail(f"unknown faction header {current_faction!r}")
        snapshot = by_faction_name.get((faction_sid, unit_name))
        if snapshot is None and unit_name == "Fangarm":
            snapshot = by_sid.get("h3_fangarm")
        if snapshot is None:
            fail(f"recommendation row has no current snapshot mapping: {faction_sid}|{unit_name}")
        rows.append(
            {
                "unitSid": snapshot["id"],
                "factionSid": faction_sid,
                "tier": current_tier,
                "unitName": unit_name,
                "recommendation": match.group(2).strip(),
                "implementationTarget": match.group(3).strip(),
            }
        )
    return rows


def validate_contract_source(repo_root: pathlib.Path) -> list[dict[str, Any]]:
    contract_path = repo_root / BALANCE_CONTRACT
    doc = load_json(contract_path)
    if not isinstance(doc, dict) or doc.get("schemaVersion") != 1:
        fail("balance contract must be an object with schemaVersion=1")
    entries = doc.get("entries")
    if not isinstance(entries, list):
        fail("balance contract must contain entries[]")
    if len(entries) != EXPECTED_ENTRY_COUNT:
        fail(f"balance contract has {len(entries)} entries, expected {EXPECTED_ENTRY_COUNT}")
    expected_rows = parse_recommendations(repo_root)
    expected_by_sid = {row["unitSid"]: row for row in expected_rows}
    seen: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            fail("balance contract entry is not an object")
        unit_sid = entry.get("unitSid")
        if not isinstance(unit_sid, str) or not unit_sid:
            fail("balance contract entry is missing unitSid")
        if unit_sid in seen:
            fail(f"duplicate balance contract entry for {unit_sid}")
        seen.add(unit_sid)
        expected = expected_by_sid.get(unit_sid)
        if expected is None:
            fail(f"balance contract entry {unit_sid} does not correspond to a recommendation row")
        for key in ("factionSid", "tier", "unitName", "recommendation", "implementationTarget"):
            if entry.get(key) != expected[key]:
                fail(f"{unit_sid}: contract {key} does not match recommendation document")
        overrides = entry.get("statOverrides")
        if overrides is not None and (not isinstance(overrides, dict) or not overrides):
            fail(f"{unit_sid}: statOverrides must be a non-empty object when present")
        for key, value in (overrides or {}).items():
            if key == "cost":
                if not isinstance(value, dict) or not value:
                    fail(f"{unit_sid}: cost override must be a non-empty object")
                for resource, amount in value.items():
                    if not isinstance(resource, str) or not isinstance(amount, int) or amount < 0:
                        fail(f"{unit_sid}: invalid cost override entry {resource!r}={amount!r}")
                continue
            if key not in STAT_KEYS:
                fail(f"{unit_sid}: unsupported stat override key {key!r}")
            if not isinstance(value, int) or value < 0:
                fail(f"{unit_sid}: stat override {key} must be a non-negative integer")
        if isinstance(overrides, dict) and overrides.get("damageMin", 0) > overrides.get("damageMax", 999999):
            fail(f"{unit_sid}: damageMin override exceeds damageMax")
        mechanics = entry.get("mechanicOverrides")
        if mechanics is not None:
            if not isinstance(mechanics, dict) or not mechanics:
                fail(f"{unit_sid}: mechanicOverrides must be a non-empty object when present")
            force_ai = mechanics.get("forceAi")
            if force_ai is not None and force_ai not in {"melee_type", "range_type"}:
                fail(f"{unit_sid}: unsupported forceAi {force_ai!r}")
            modifiers = mechanics.get("statModifiers")
            if modifiers is not None:
                if not isinstance(modifiers, list) or not modifiers:
                    fail(f"{unit_sid}: statModifiers must be a non-empty list when present")
                for modifier in modifiers:
                    if not isinstance(modifier, dict):
                        fail(f"{unit_sid}: stat modifier is not an object")
                    if modifier.get("set") not in {"inDmgMods", "outDmgMods"}:
                        fail(f"{unit_sid}: stat modifier set must be inDmgMods/outDmgMods")
                    if not isinstance(modifier.get("tag"), str) or not modifier.get("tag"):
                        fail(f"{unit_sid}: stat modifier tag is missing")
                    if not isinstance(modifier.get("value"), (int, float)):
                        fail(f"{unit_sid}: stat modifier value must be numeric")
            view_passives = mechanics.get("viewPassives")
            if view_passives is not None:
                if not isinstance(view_passives, list) or not view_passives:
                    fail(f"{unit_sid}: viewPassives must be a non-empty list when present")
                for passive in view_passives:
                    if not isinstance(passive, dict) or not isinstance(passive.get("name"), str) or not isinstance(passive.get("description"), str):
                        fail(f"{unit_sid}: view passive must include name and description")
            remove_view_passives = mechanics.get("removeViewPassives")
            if remove_view_passives is not None:
                if not isinstance(remove_view_passives, list) or not remove_view_passives or not all(isinstance(item, str) and item for item in remove_view_passives):
                    fail(f"{unit_sid}: removeViewPassives must be a non-empty string list when present")
        evidence = entry.get("evidenceChecks")
        if evidence is not None:
            if not isinstance(evidence, dict) or not evidence:
                fail(f"{unit_sid}: evidenceChecks must be a non-empty object when present")
            view_abilities = evidence.get("viewAbilities")
            if view_abilities is not None:
                if not isinstance(view_abilities, list) or not view_abilities or not all(isinstance(item, str) and item for item in view_abilities):
                    fail(f"{unit_sid}: evidenceChecks.viewAbilities must be a non-empty string list")
            phoenix_rebirth = evidence.get("phoenixRebirth")
            if phoenix_rebirth is not None and phoenix_rebirth is not True:
                fail(f"{unit_sid}: evidenceChecks.phoenixRebirth must be true when present")
            logic_buffs = evidence.get("logicAbilityBuffs")
            if logic_buffs is not None:
                if not isinstance(logic_buffs, list) or not logic_buffs:
                    fail(f"{unit_sid}: evidenceChecks.logicAbilityBuffs must be a non-empty list")
                for requirement in logic_buffs:
                    if not isinstance(requirement, dict):
                        fail(f"{unit_sid}: logic ability buff evidence must be an object")
                    if not isinstance(requirement.get("buff"), str) or not requirement.get("buff"):
                        fail(f"{unit_sid}: logic ability buff evidence is missing buff")
                    if not isinstance(requirement.get("duration"), int):
                        fail(f"{unit_sid}: logic ability buff evidence duration must be an integer")
                    if not isinstance(requirement.get("mechanic"), str) or not requirement.get("mechanic"):
                        fail(f"{unit_sid}: logic ability buff evidence is missing mechanic")
        status = entry.get("implementationStatus")
        if status is not None:
            if not isinstance(status, dict) or status.get("kind") not in {"preservedCurrent", "blockedNativeContract"}:
                fail(f"{unit_sid}: implementationStatus.kind must be preservedCurrent or blockedNativeContract")
            if not isinstance(status.get("reason"), str) or not status.get("reason"):
                fail(f"{unit_sid}: implementationStatus.reason must be a non-empty string")
        if not isinstance(overrides, dict) and not isinstance(mechanics, dict) and not isinstance(evidence, dict) and not isinstance(status, dict):
            fail(f"{unit_sid}: balance contract row has no stat, mechanic, evidence, or explicit implementation status")
    if seen != set(expected_by_sid):
        missing = sorted(set(expected_by_sid) - seen)
        fail(f"balance contract is missing recommendation rows: {missing[:8]}")
    return entries


def import_overlay(repo_root: pathlib.Path) -> Any:
    overlay_dir = repo_root / "tools" / "release_port"
    overlay_path = overlay_dir / "apply_release_core_overlay.py"
    if str(overlay_dir) not in sys.path:
        sys.path.insert(0, str(overlay_dir))
    spec = importlib.util.spec_from_file_location("homm3_balance_overlay", overlay_path)
    if spec is None or spec.loader is None:
        fail(f"cannot import {overlay_path}")
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as ex:  # noqa: BLE001
        fail(f"cannot import overlay module: {ex}")
    return module


def build_candidate_overlay(repo_root: pathlib.Path, core_path: pathlib.Path) -> dict[str, bytes]:
    module = import_overlay(repo_root)
    try:
        overlay, _notes = module.build_overlay(core_path)
    except Exception as ex:  # noqa: BLE001
        fail(f"cannot build candidate Core overlay in memory: {ex}")
    if not isinstance(overlay, dict):
        fail("build_overlay did not return an overlay dictionary")
    return overlay


def read_json_member(core_zip: zipfile.ZipFile, overlay: dict[str, bytes], member: str) -> Any:
    try:
        raw = overlay[member] if member in overlay else core_zip.read(member)
    except KeyError:
        fail(f"candidate Core output is missing {member}")
    return json.loads(raw.decode("utf-8-sig"))


def first_array_item(doc: Any, member: str) -> dict[str, Any]:
    if isinstance(doc, dict) and isinstance(doc.get("array"), list) and doc["array"]:
        row = doc["array"][0]
        if isinstance(row, dict):
            return row
    fail(f"malformed generated Core row: {member}")


def logic_member_by_sid(core_zip: zipfile.ZipFile, overlay: dict[str, bytes]) -> dict[str, str]:
    result: dict[str, str] = {}
    for member in sorted(set(core_zip.namelist()) | set(overlay)):
        if not member.startswith("DB/units/units_logics/") or not member.endswith("_l.json"):
            continue
        sid = pathlib.PurePosixPath(member).name.removesuffix("_l.json")
        result[sid] = member
    return result


def view_member_by_sid(core_zip: zipfile.ZipFile, overlay: dict[str, bytes]) -> dict[str, str]:
    result: dict[str, str] = {}
    for member in sorted(set(core_zip.namelist()) | set(overlay)):
        if not member.startswith("DB/units/units_views/") or not member.endswith("_v.json"):
            continue
        sid = pathlib.PurePosixPath(member).name.removesuffix("_v.json")
        result[sid] = member
    return result


def damage_modifier_map(stats: dict[str, Any], mod_set: str) -> dict[str, float]:
    mods = stats.get(mod_set)
    rows = mods.get("list") if isinstance(mods, dict) else None
    result: dict[str, float] = {}
    if isinstance(rows, list):
        for row in rows:
            if isinstance(row, dict) and isinstance(row.get("t"), str) and isinstance(row.get("v"), (int, float)):
                result[row["t"]] = float(row["v"])
    return result


def view_passive_names(row: dict[str, Any]) -> set[str]:
    result: set[str] = set()
    passives = row.get("passives")
    if isinstance(passives, list):
        for passive in passives:
            if isinstance(passive, dict) and isinstance(passive.get("name"), str):
                result.add(passive["name"])
    return result


def view_ability_names(row: dict[str, Any]) -> set[str]:
    result: set[str] = set()
    abilities = row.get("abilities")
    if isinstance(abilities, list):
        for ability in abilities:
            if isinstance(ability, dict) and isinstance(ability.get("name"), str):
                result.add(ability["name"])
    return result


def logic_has_phoenix_rebirth(row: dict[str, Any], unit_sid: str) -> bool:
    expected_obstacle = f"{unit_sid}_phoenix_heart"
    passives = row.get("passives")
    if not isinstance(passives, list):
        return False
    for passive in passives:
        if not isinstance(passive, dict):
            continue
        actions = passive.get("actions")
        if not isinstance(actions, list):
            continue
        for action in actions:
            if not isinstance(action, dict) or action.get("trigger") != "unit_died":
                continue
            dealer = action.get("damageDealer")
            mechanics = dealer.get("targetMechanics") if isinstance(dealer, dict) else None
            if not isinstance(mechanics, list):
                continue
            for mechanic in mechanics:
                values = mechanic.get("values") if isinstance(mechanic, dict) else None
                if mechanic.get("mech") == "spawn_object" and isinstance(values, list) and len(values) >= 2 and values[0] == "obstacle" and values[1] == expected_obstacle:
                    return True
    return False


def obstacle_rebirth_targets(core_zip: zipfile.ZipFile, overlay: dict[str, bytes]) -> dict[str, str]:
    member = "DB/field_objects/obstacles/obstacles_units.json"
    doc = read_json_member(core_zip, overlay, member)
    rows = doc.get("array") if isinstance(doc, dict) else None
    if not isinstance(rows, list):
        fail(f"{member}: malformed obstacle rows")
    result: dict[str, str] = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("id"), str):
            continue
        mechanic = row.get("onTimeoutMechanic")
        values = mechanic.get("values") if isinstance(mechanic, dict) else None
        if isinstance(values, list) and len(values) >= 2 and isinstance(values[1], str):
            result[row["id"]] = values[1]
    return result


def logic_ability_satisfies(row: dict[str, Any], requirement: dict[str, Any]) -> bool:
    abilities = row.get("abilities")
    if not isinstance(abilities, list):
        return False
    for ability in abilities:
        if not isinstance(ability, dict):
            continue
        dealer = ability.get("damageDealer")
        if not isinstance(dealer, dict):
            continue
        buff = dealer.get("buff")
        if not isinstance(buff, dict) or buff.get("sid") != requirement["buff"] or buff.get("duration") != requirement["duration"]:
            continue
        mechanics = dealer.get("targetMechanics")
        if isinstance(mechanics, list) and any(isinstance(item, dict) and item.get("mech") == requirement["mechanic"] for item in mechanics):
            return True
    return False


def cost_map(row: dict[str, Any]) -> dict[str, int]:
    unit_cost = row.get("unitCost") if isinstance(row, dict) else None
    values = unit_cost.get("costResArray") if isinstance(unit_cost, dict) else None
    result: dict[str, int] = {}
    if isinstance(values, list):
        for item in values:
            if isinstance(item, dict) and isinstance(item.get("name"), str) and isinstance(item.get("cost"), int):
                result[item["name"]] = item["cost"]
    return result


def validate_upgrade_alt_cost_parity(
    core_zip: zipfile.ZipFile,
    overlay: dict[str, bytes],
    logic_members: dict[str, str],
) -> None:
    """Fail if any h3_*_upg / h3_*_upg_alt sibling pair has unequal unitCost."""
    mismatches: list[str] = []
    for alt_sid, alt_member in sorted(logic_members.items()):
        if not alt_sid.startswith("h3_") or not alt_sid.endswith("_upg_alt"):
            continue
        upg_sid = alt_sid[: -len("_alt")]
        upg_member = logic_members.get(upg_sid)
        if upg_member is None:
            continue
        upg_row = first_array_item(read_json_member(core_zip, overlay, upg_member), upg_member)
        alt_row = first_array_item(read_json_member(core_zip, overlay, alt_member), alt_member)
        upg_cost = cost_map(upg_row)
        alt_cost = cost_map(alt_row)
        if upg_cost != alt_cost:
            mismatches.append(f"{upg_sid}={upg_cost!r} vs {alt_sid}={alt_cost!r}")
    if mismatches:
        preview = "; ".join(mismatches[:8])
        fail(f"h3 upgrade/alt cost parity broken ({len(mismatches)} lines): {preview}")


def validate_no_negative_upgrade_cost_delta(core_zip: zipfile.ZipFile, overlay: dict[str, bytes]) -> None:
    """Fail if any upgrade in the candidate Core costs less than a unit it upgrades from, in any resource."""
    tools_dir = pathlib.Path(__file__).resolve().parent
    if str(tools_dir) not in sys.path:
        sys.path.insert(0, str(tools_dir))
    from validate_unit_upgrade_cost_delta_contract import unit_rows_from_members, upgrade_cost_delta_errors

    members = set(core_zip.namelist()) | set(overlay)
    units, errors = unit_rows_from_members(members, lambda m: overlay[m] if m in overlay else core_zip.read(m))
    errors += upgrade_cost_delta_errors(units)
    if errors:
        fail(f"negative upgrade cost delta ({len(errors)}): " + "; ".join(errors[:8]))


def validate_candidate_core(repo_root: pathlib.Path, core_path: pathlib.Path, entries: list[dict[str, Any]]) -> None:
    overlay = build_candidate_overlay(repo_root, core_path)
    with zipfile.ZipFile(core_path) as core_zip:
        logic_members = logic_member_by_sid(core_zip, overlay)
        view_members = view_member_by_sid(core_zip, overlay)
        obstacle_targets = obstacle_rebirth_targets(core_zip, overlay)
        validate_upgrade_alt_cost_parity(core_zip, overlay, logic_members)
        validate_no_negative_upgrade_cost_delta(core_zip, overlay)
        for entry in entries:
            overrides = entry.get("statOverrides")
            mechanics = entry.get("mechanicOverrides")
            evidence = entry.get("evidenceChecks")
            status = entry.get("implementationStatus")
            unit_sid = entry["unitSid"]
            member = logic_members.get(unit_sid)
            if member is None:
                fail(f"{unit_sid}: no generated unit logic row found in candidate Core")
            row = first_array_item(read_json_member(core_zip, overlay, member), member)
            stats = row.get("stats")
            if not isinstance(stats, dict):
                fail(f"{unit_sid}: candidate unit logic row has no stats object")
            marker = row.get("xHomm3BalanceRecommendation20260625")
            if isinstance(status, dict) and status.get("kind") == "blockedNativeContract" and isinstance(mechanics, dict):
                fail(f"{unit_sid}: blocked native-contract row must not ship mechanicOverrides")
            if (isinstance(overrides, dict) or isinstance(mechanics, dict)) and not isinstance(marker, dict):
                fail(f"{unit_sid}: candidate row is missing balance recommendation marker")
            if isinstance(overrides, dict):
                for key, value in overrides.items():
                    if key == "cost":
                        actual_cost = cost_map(row)
                        if actual_cost != value:
                            fail(
                                f"{unit_sid}: candidate cost={actual_cost!r}, expected exact override {value!r}"
                            )
                    elif key == "squadValue":
                        if row.get("squadValue") != value:
                            fail(f"{unit_sid}: candidate squadValue={row.get('squadValue')!r}, expected {value!r}")
                    elif stats.get(key) != value:
                        fail(f"{unit_sid}: candidate stats.{key}={stats.get(key)!r}, expected {value!r}")
            if isinstance(mechanics, dict):
                force_ai = mechanics.get("forceAi")
                if isinstance(force_ai, str) and row.get("ai") != force_ai:
                    fail(f"{unit_sid}: candidate ai={row.get('ai')!r}, expected {force_ai!r}")
                for modifier in mechanics.get("statModifiers") or []:
                    mod_set = modifier["set"]
                    tag = modifier["tag"]
                    expected_value = float(modifier["value"])
                    actual = damage_modifier_map(stats, mod_set).get(tag)
                    if actual != expected_value:
                        fail(f"{unit_sid}: candidate stats.{mod_set}[{tag!r}]={actual!r}, expected {expected_value!r}")
                view_passives = mechanics.get("viewPassives")
                remove_view_passives = mechanics.get("removeViewPassives")
                if isinstance(view_passives, list) or isinstance(remove_view_passives, list):
                    view_member = view_members.get(unit_sid)
                    if view_member is None:
                        fail(f"{unit_sid}: no generated unit view row found in candidate Core")
                    view_row = first_array_item(read_json_member(core_zip, overlay, view_member), view_member)
                    names = view_passive_names(view_row)
                    if isinstance(view_passives, list):
                        for passive in view_passives:
                            if passive["name"] not in names:
                                fail(f"{unit_sid}: candidate view passives missing {passive['name']!r}")
                    if isinstance(remove_view_passives, list):
                        for passive_name in remove_view_passives:
                            if passive_name in names:
                                fail(f"{unit_sid}: candidate view passives still include removed passive {passive_name!r}")
            if isinstance(evidence, dict):
                required_abilities = evidence.get("viewAbilities")
                if isinstance(required_abilities, list):
                    view_member = view_members.get(unit_sid)
                    if view_member is None:
                        fail(f"{unit_sid}: no generated unit view row found in candidate Core")
                    view_row = first_array_item(read_json_member(core_zip, overlay, view_member), view_member)
                    names = view_ability_names(view_row)
                    for ability_name in required_abilities:
                        if ability_name not in names:
                            fail(f"{unit_sid}: candidate view abilities missing {ability_name!r}")
                if evidence.get("phoenixRebirth") is True:
                    view_member = view_members.get(unit_sid)
                    if view_member is None:
                        fail(f"{unit_sid}: no generated unit view row found in candidate Core")
                    view_row = first_array_item(read_json_member(core_zip, overlay, view_member), view_member)
                    if "phoenix_passive_2_name" not in view_passive_names(view_row):
                        fail(f"{unit_sid}: candidate view passives missing native Phoenix rebirth card")
                    if not logic_has_phoenix_rebirth(row, unit_sid):
                        fail(f"{unit_sid}: candidate logic passives missing native Phoenix rebirth spawn_object scaffold")
                    obstacle_id = f"{unit_sid}_phoenix_heart"
                    if obstacle_targets.get(obstacle_id) != unit_sid:
                        fail(f"{unit_sid}: candidate phoenix-heart obstacle {obstacle_id!r} targets {obstacle_targets.get(obstacle_id)!r}")
                required_logic_buffs = evidence.get("logicAbilityBuffs")
                if isinstance(required_logic_buffs, list):
                    for requirement in required_logic_buffs:
                        if not logic_ability_satisfies(row, requirement):
                            fail(f"{unit_sid}: candidate logic abilities missing buff/mechanic evidence {requirement!r}")

def validate_overlay_source(repo_root: pathlib.Path) -> None:
    source = (repo_root / "tools" / "release_port" / "apply_release_core_overlay.py").read_text(encoding="utf-8-sig")
    required = [
        "HOMM3_UNIT_BALANCE_ADJUSTMENTS_PATH",
        "def load_homm3_unit_balance_adjustments()",
        "def apply_homm3_unit_balance_logic_adjustment(item: dict[str, Any], custom_sid: str) -> bool:",
        "HOMM3_UNIT_BALANCE_ADJUSTMENTS = load_homm3_unit_balance_adjustments()",
        "apply_homm3_unit_balance_logic_adjustment(item, custom_sid)",
        "xHomm3BalanceRecommendation20260625",
        "mechanicOverrides",
        "def merge_homm3_balance_cost_override(item: dict[str, Any], custom_sid: str, cost: dict[str, Any]) -> bool:",
        "Replace unitCost.costResArray with the exact override map.",
    ]
    for snippet in required:
        if snippet not in source:
            fail(f"overlay source is missing required balance contract snippet: {snippet}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=pathlib.Path, default=pathlib.Path(__file__).resolve().parents[1])
    parser.add_argument("--core-zip", type=pathlib.Path, default=None)
    args = parser.parse_args()

    repo_root = args.repo_root.resolve()
    core_path = args.core_zip.resolve() if args.core_zip else repo_root / "artifacts" / "core_overlay_work" / "Core.zip"
    if not core_path.is_file():
        fail(f"Core.zip not found: {core_path}")
    validate_overlay_source(repo_root)
    entries = validate_contract_source(repo_root)
    validate_candidate_core(repo_root, core_path, entries)
    print("HoMM3 unit balance adjustment contract validated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
