#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INVENTORY = ROOT / "custom_factions" / "custom_law_effect_plan_inventory.json"
DEFAULT_PLANNER = ROOT / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod" / "Homm3CustomLawEffectPlans.cs"

FAMILY_METHOD = {
    "Calendar": ("TryPlanCalendarEffect", "DescribeCalendarPredicates"),
    "Construction": ("TryPlanConstructionEffect", "DescribeConstructionPredicates"),
    "CounterattackDoctrine": ("TryPlanCounterattackDoctrineEffect", "DescribeCounterattackPredicates"),
    "Formation": ("TryPlanFormationEffect", "DescribeFormationPredicates"),
    "MoralePackage": ("TryPlanMoralePackageEffect", "DescribeMoralePackagePredicates"),
    "MoraleTrigger": ("TryPlanMoraleTriggerEffect", "DescribeMoraleTriggerPredicates"),
    "RewardEconomy": ("TryPlanRewardEconomyEffect", "DescribeRewardEconomyPredicates"),
    "SpellCooldown": ("TryPlanSpellCooldownEffect", "DescribeSpellCooldownPredicates"),
    "SpellSchool": ("TryPlanSpellSchoolEffect", "DescribeSpellSchoolPredicates"),
    "TrainingDamage": ("TryPlanTrainingDamageEffect", "DescribeTrainingDamagePredicates"),
    "Vision": ("TryPlanVisionEffect", "DescribeVisionPredicates"),
}

ALLOWED_UNDESCRIBED_PREDICATES = {
    # These are materialized by inventory as explicit predicate requirements but
    # currently live as action context in the planner rather than named profile
    # boolean fields on the corresponding profile type.
    "UsesNegativeCandidate",
    "UsesPositiveCandidate",
}


class ValidationError(ValueError):
    pass


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8-sig") as handle:
        return json.load(handle)


def find_matching_brace(text: str, open_index: int) -> int:
    depth = 0
    in_string = False
    escaped = False
    for index in range(open_index, len(text)):
        ch = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return index
    raise ValidationError(f"unmatched brace at {open_index}")


def method_body(source: str, method_name: str) -> str:
    match = re.search(
        r"\b(?:internal|private)\s+static\s+[\w<>]+\s+"
        + re.escape(method_name)
        + r"\s*\(",
        source,
    )
    if not match:
        raise ValidationError(f"planner method missing: {method_name}")
    open_brace = source.find("{", match.end())
    if open_brace < 0:
        raise ValidationError(f"planner method has no body: {method_name}")
    close_brace = find_matching_brace(source, open_brace)
    return source[open_brace + 1 : close_brace]


def inventory_family_predicates(inventory: Any) -> dict[str, set[str]]:
    if not isinstance(inventory, dict):
        raise ValidationError("effect plan inventory root must be an object")
    rows = inventory.get("rows")
    if not isinstance(rows, list):
        raise ValidationError("effect plan inventory has no rows list")
    families: dict[str, set[str]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        family = row.get("family")
        if not isinstance(family, str) or not family:
            raise ValidationError(f"inventory row missing family: {row!r}")
        predicates = row.get("requiredPredicates")
        if not isinstance(predicates, list):
            raise ValidationError(f"{family}: inventory row missing requiredPredicates list")
        target = families.setdefault(family, set())
        for predicate in predicates:
            if not isinstance(predicate, str) or not predicate:
                raise ValidationError(f"{family}: invalid predicate {predicate!r}")
            target.add(predicate)
    return families


def validate(inventory_path: Path, planner_path: Path) -> list[str]:
    families = inventory_family_predicates(load_json(inventory_path))
    source = planner_path.read_text(encoding="utf-8-sig")
    errors: list[str] = []

    extra = sorted(set(families) - set(FAMILY_METHOD))
    missing = sorted(set(FAMILY_METHOD) - set(families))
    if extra:
        errors.append("inventory has families without planner mapping: " + ", ".join(extra))
    if missing:
        errors.append("planner mapping has families absent from inventory: " + ", ".join(missing))

    for family in sorted(set(families) & set(FAMILY_METHOD)):
        try_method, describe_method = FAMILY_METHOD[family]
        try:
            try_body = method_body(source, try_method)
            describe_body = method_body(source, describe_method)
        except ValidationError as exc:
            errors.append(f"{family}: {exc}")
            continue
        if "mutation=disabled" not in source:
            errors.append("planner source must retain mutation=disabled string in plan output")
        if "new ProfileEffectPlan" not in try_body and family not in {"TrainingDamage", "Formation", "CounterattackDoctrine"}:
            errors.append(f"{family}: {try_method} must construct ProfileEffectPlan")
        if family in {"TrainingDamage", "Formation", "CounterattackDoctrine"} and "new " not in try_body:
            errors.append(f"{family}: {try_method} must construct a typed plan")
        for predicate in sorted(families[family]):
            if predicate in ALLOWED_UNDESCRIBED_PREDICATES:
                if predicate not in try_body and predicate not in describe_body:
                    errors.append(f"{family}: allowed context predicate {predicate} is not referenced by planner")
                continue
            if f"profile.{predicate}" not in describe_body:
                errors.append(f"{family}: inventory predicate {predicate} is not described by {describe_method}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate source-prepared effect profiles have non-mutating planner and predicate-description coverage."
    )
    parser.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY)
    parser.add_argument("--planner", type=Path, default=DEFAULT_PLANNER)
    args = parser.parse_args()

    try:
        errors = validate(args.inventory, args.planner)
    except (OSError, json.JSONDecodeError, ValidationError) as exc:
        print(f"custom law effect planner coverage validation failed: {exc}")
        return 1
    if errors:
        print("custom law effect planner coverage validation failed:")
        for error in errors:
            print(f"  - {error}")
        return 1
    print(f"custom law effect planner coverage validation passed ({len(FAMILY_METHOD)} family planner(s))")
    print("Note: static planner coverage does not prove runtime event reachability, mutation safety, or gameplay behavior.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
