#!/usr/bin/env python3
"""Replace custom law runtime-debt rows with native-data law effects.

This is a source hygiene tool for the June 21 native-data law pass. It removes
runtime-only claims from custom faction law overrides and gives every enabled
custom law row a concrete Core-native bonus shape instead.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
LAW_OVERRIDE_DIR = ROOT / "custom_factions" / "law_overrides"
TARGETS_PATH = ROOT / "custom_factions" / "custom_law_targets.json"
MANIFEST_DIR = ROOT / "custom_factions"

FACTION_SCHOOL = {
    "homm3_castle": "day",
    "homm3_conflux": "primal",
    "homm3_cove": "space",
    "homm3_dungeon": "night",
    "homm3_fortress": "primal",
    "homm3_inferno": "primal",
    "homm3_necropolis": "night",
    "homm3_rampart": "primal",
    "homm3_stronghold": "day",
    "homm3_tower": "space",
}

FAMILY_TEXT = {
    2: ("Scouting", "Your hero gains increased sight range."),
    6: ("Drill", "Friendly units deal increased damage."),
    13: ("Counterstroke", "Friendly units deal increased counterattack damage."),
    15: ("Lesser Spell School", "Your heroes gain access to the faction's lower spell school package."),
    18: ("Melee Formation", "Friendly units deal more melee damage and take less melee damage."),
    19: ("Ranged Formation", "Friendly units deal more ranged damage and take less ranged damage."),
    21: ("Gold Economy", "Gold income is increased."),
    22: ("Morale", "Your hero gains Morale."),
    25: ("Extra Action", "Friendly units gain additional-action chance."),
    27: ("Greater Spell School", "Your heroes gain access to the faction's higher spell school package."),
    28: ("Construction", "Your towns gain an additional daily construction allowance."),
    31: ("Native Mastery", "Friendly units gain native combat bonuses."),
    32: ("Native Mastery", "Friendly units gain Speed and Initiative."),
    33: ("Calendar", "Astrology progress is increased."),
    34: ("Buff Duration", "Positive effects on friendly units last longer."),
}


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8-sig") as handle:
        return json.load(handle)


def write_json(path: Path, value: Any) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, indent=2, ensure_ascii=False)
        handle.write("\n")


def manifest_unit_sids(faction_sid: str) -> list[str]:
    manifest = load_json(MANIFEST_DIR / f"{faction_sid}.json")
    result: list[str] = []
    for line in manifest.get("unitLines", []):
        if not isinstance(line, dict):
            continue
        base = line.get("baseSid")
        if isinstance(base, str) and base not in result:
            result.append(base)
        variants = line.get("variantSids")
        if isinstance(variants, dict):
            for sid in variants.values():
                if isinstance(sid, str) and sid not in result:
                    result.append(sid)
    return result


def cost_rows(row: dict[str, Any], fallback_levels: int) -> list[int]:
    levels = row.get("parametersPerLevel")
    if not isinstance(levels, list) or not levels:
        return [3] * fallback_levels
    costs: list[int] = []
    for level in levels:
        cost = level.get("cost") if isinstance(level, dict) else None
        costs.append(cost if isinstance(cost, int) else 3)
    return costs


def bonus(type_: str, parameters: list[str], receivers: list[str] | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {"type": type_, "parameters": parameters}
    if receivers is not None:
        result["receivers"] = receivers
    return result


def levels_from_bonuses(costs: list[int], per_level: list[list[dict[str, Any]]]) -> list[dict[str, Any]]:
    if len(costs) != len(per_level):
        costs = [3] * len(per_level)
    return [{"cost": cost, "bonuses": bonuses} for cost, bonuses in zip(costs, per_level)]


def scalar_values(level_count: int, one: str = "0.10") -> list[str]:
    if level_count <= 1:
        return [one]
    if level_count == 2:
        return ["0.05", "0.10"]
    return ["0.05", "0.10", "0.15"][:level_count]


def native_levels(faction_sid: str, index: int, row: dict[str, Any], receivers: list[str]) -> list[dict[str, Any]]:
    costs = cost_rows(row, 1)
    level_count = max(1, len(costs))
    school = FACTION_SCHOOL[faction_sid]

    if index == 2:
        values = ["2", "4", "6"][:level_count] if level_count >= 3 else ["2", "4"][:level_count]
        return levels_from_bonuses(costs, [[bonus("heroStat", ["viewRadius", value])] for value in values])
    if index == 6:
        return levels_from_bonuses(
            costs,
            [[bonus("unitStat", ["outAllDmgMod", value], receivers)] for value in scalar_values(level_count)],
        )
    if index == 13:
        values = ["0.50", "1.00"][:level_count] if level_count > 1 else ["0.50"]
        return levels_from_bonuses(
            costs,
            [[bonus("unitStat", ["modifierSet", "outDmgMods", "counter_attack", value], receivers)] for value in values],
        )
    if index == 15:
        return levels_from_bonuses(costs[:1], [[bonus("heroStat", ["magicSchoolSet", school, "0", "1"])]])
    if index == 18:
        per_level: list[list[dict[str, Any]]] = []
        for value in scalar_values(level_count):
            per_level.append(
                [
                    bonus("unitStat", ["modifierSet", "outDmgMods", "melee_attack", value], receivers),
                    bonus("unitStat", ["modifierSet", "inDmgMods", "melee_attack", f"-{value}"], receivers),
                ]
            )
        return levels_from_bonuses(costs, per_level)
    if index == 19:
        per_level = []
        for value in scalar_values(level_count):
            per_level.append(
                [
                    bonus("unitStat", ["modifierSet", "outDmgMods", "shoot_attack", value], receivers),
                    bonus("unitStat", ["modifierSet", "inDmgMods", "shoot_attack", f"-{value}"], receivers),
                ]
            )
        return levels_from_bonuses(costs, per_level)
    if index == 21:
        values = ["0.10", "0.20"][:level_count] if level_count > 1 else ["0.10"]
        return levels_from_bonuses(costs, [[bonus("sideStat", ["resPercentIncrementSet", "gold", value])] for value in values])
    if index == 22:
        values = ["1", "2", "3"][:level_count]
        return levels_from_bonuses(costs, [[bonus("heroStat", ["moral", value])] for value in values])
    if index == 25:
        values = ["0.01", "0.02", "0.03"][:level_count]
        return levels_from_bonuses(costs, [[bonus("unitStat", ["additionalActionChanceModifier", value], receivers)] for value in values])
    if index == 27:
        return levels_from_bonuses(costs[:1], [[bonus("heroStat", ["magicSchoolSet", school, "5", "0"])]])
    if index == 28:
        values = ["1", "2", "3"][:level_count]
        return levels_from_bonuses(costs, [[bonus("constructionDailyLimit", [value])] for value in values])
    if index == 31:
        return levels_from_bonuses(
            costs[:1],
            [[
                bonus("unitStat", ["outAllDmgMod", "0.10"], receivers),
                bonus("unitStat", ["modifierSet", "inDmgMods", "magic_damage", "-0.10"], receivers),
            ]],
        )
    if index == 32:
        return levels_from_bonuses(
            costs[:1],
            [[bonus("unitStat", ["speed", "1"], receivers), bonus("unitStat", ["initiative", "1"], receivers)]],
        )
    if index == 33:
        values = ["250", "500", "750"][:level_count]
        return levels_from_bonuses(costs, [[bonus("astrologyExp", [value])] for value in values])
    if index == 34:
        values = ["1", "2", "3"][:level_count]
        return levels_from_bonuses(
            costs,
            [[bonus("unitStat", ["inComingBuffDuration", value], receivers)] for value in values],
        )
    raise ValueError(f"unsupported law index {index}")


def rewrite_override_file(path: Path) -> int:
    doc = load_json(path)
    overrides = doc.get("lawOverrides")
    if not isinstance(overrides, dict):
        raise ValueError(f"{path}: missing lawOverrides")
    faction_sid = path.stem
    receivers = manifest_unit_sids(faction_sid)
    changed = 0
    for sid, row in sorted(overrides.items()):
        if not isinstance(row, dict) or row.get("enabled") is not True:
            continue
        match = re.search(r"_(\d+)$", sid)
        if not match:
            continue
        index = int(match.group(1))
        if index not in FAMILY_TEXT:
            continue
        family_label, desc = FAMILY_TEXT[index]
        new_row = dict(row)
        new_row["descriptionText"] = desc
        new_row["parametersPerLevel"] = native_levels(faction_sid, index, row, receivers)
        new_row["notes"] = (
            "Native-data replacement 2026-06-21: this row uses only Core-native law bonuses. "
            "Speculative plugin gameplay mutators for custom laws are disabled until revalidated individually."
        )
        for key in list(new_row):
            if key.startswith("xHomm3NoCompromise"):
                del new_row[key]
        overrides[sid] = new_row
        changed += 1
    write_json(path, doc)
    return changed


def rewrite_targets() -> int:
    doc = load_json(TARGETS_PATH)
    targets = doc.get("targets")
    if not isinstance(targets, list):
        raise ValueError(f"{TARGETS_PATH}: missing targets")
    doc["purpose"] = (
        "Source-of-truth list for custom faction law rows after the June 21 native-data replacement pass. "
        "The original runtime packet ambitions are not represented as active gameplay unless a row is later "
        "revalidated and explicitly promoted."
    )
    doc["validationState"] = (
        "Source-prepared June 21: all listed custom law rows are expected to use Core-native bonus rows only; "
        "overlay/build/runtime smoke still required."
    )
    doc.setdefault("policy", {})["donorRows"] = "disabled for active custom laws; native Core bonus rows only"
    changed = 0
    for target in targets:
        if not isinstance(target, dict):
            continue
        index = target.get("lawIndex")
        if not isinstance(index, int) or index not in FAMILY_TEXT:
            continue
        _label, desc = FAMILY_TEXT[index]
        target["targetMechanic"] = desc
        target["implementationStatus"] = "native-exact"
        changed += 1
    write_json(TARGETS_PATH, doc)
    return changed


def main() -> int:
    total = 0
    for path in sorted(LAW_OVERRIDE_DIR.glob("homm3_*.json")):
        count = rewrite_override_file(path)
        total += count
        print(f"{path.relative_to(ROOT)}: rewrote {count} law rows")
    print(f"{TARGETS_PATH.relative_to(ROOT)}: rewrote {rewrite_targets()} target rows")
    print(f"total law rows rewritten: {total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

