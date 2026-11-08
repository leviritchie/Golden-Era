#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PROFILE_SOURCE = ROOT / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod" / "Homm3CustomLawEffectProfiles.cs"
DEFAULT_JSON = ROOT / "custom_factions" / "custom_law_effect_plan_inventory.json"
DEFAULT_MD = ROOT / "docs" / "custom_law_effect_plan_inventory.md"
TARGETS_PATH = ROOT / "custom_factions" / "custom_law_targets.json"

EXPECTED_CUSTOM_FACTIONS = {
    "homm3_cove",
    "homm3_dungeon",
    "homm3_fortress",
    "homm3_rampart",
    "homm3_tower",
    "homm3_conflux",
    "homm3_inferno",
    "homm3_necropolis",
    "homm3_stronghold",
}

EXPECTED_FAMILIES = {
    "CounterattackDoctrine",
    "MoraleTrigger",
    "MoralePackage",
    "RewardEconomy",
    "Calendar",
    "Vision",
    "Construction",
    "TrainingDamage",
    "Formation",
    "SpellCooldown",
    "SpellSchool",
}

FAMILY_PACKET = {
    "CounterattackDoctrine": "counterattack",
    "MoraleTrigger": "morale",
    "MoralePackage": "morale",
    "RewardEconomy": "reward-result",
    "Calendar": "reward-result",
    "Vision": "vision",
    "Construction": "construction",
    "TrainingDamage": "committed-damage",
    "Formation": "battle-action",
    "SpellCooldown": "spell-cooldown",
    "SpellSchool": "spell-cooldown",
}

FAMILY_HANDLER = {
    "CounterattackDoctrine": "counterattack.doctrine",
    "MoraleTrigger": "morale.trigger",
    "MoralePackage": "morale.package",
    "RewardEconomy": "profile.HandlerKey",
    "Calendar": "reward.calendar",
    "Vision": "vision.reveal",
    "Construction": "construction.commit",
    "TrainingDamage": "damage.training",
    "Formation": "profile.HandlerKey",
    "SpellCooldown": "spell.cooldown",
    "SpellSchool": "profile.HandlerKey",
}

LAW_INDEX_PROFILE_REQUIREMENTS = {
    2: ("Vision", "vision.reveal"),
    6: ("TrainingDamage", "damage.training"),
    13: ("CounterattackDoctrine", "counterattack.doctrine"),
    15: ("SpellSchool", "spell.low"),
    18: ("Formation", "battle.melee-formation"),
    19: ("Formation", "battle.ranged-formation"),
    21: ("RewardEconomy", "reward.gold-economy"),
    22: ("MoralePackage", "morale.package"),
    25: ("MoraleTrigger", "morale.trigger"),
    27: ("SpellSchool", "spell.high"),
    28: ("Construction", "construction.commit"),
    33: ("Calendar", "reward.calendar"),
    34: ("SpellCooldown", "spell.cooldown"),
}


def fail(message: str) -> int:
    print(message, file=sys.stderr)
    return 1


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
    raise ValueError(f"unmatched brace at {open_index}")


def read_block_after(text: str, marker_start: int) -> tuple[str, int, int]:
    open_index = text.index("{", marker_start)
    close_index = find_matching_brace(text, open_index)
    return text[open_index + 1 : close_index], open_index, close_index


def split_top_level_csv(text: str) -> list[str]:
    parts: list[str] = []
    start = 0
    depth = 0
    in_string = False
    escaped = False
    for index, ch in enumerate(text):
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
        elif ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        elif ch == "," and depth == 0:
            parts.append(text[start:index].strip())
            start = index + 1
    tail = text[start:].strip()
    if tail:
        parts.append(tail)
    return parts


def parse_constants(source: str) -> dict[str, str]:
    constants: dict[str, str] = {}
    pattern = re.compile(r'internal\s+const\s+string\s+(\w+)\s*=\s*"([^"]+)";')
    for match in pattern.finditer(source):
        constants[match.group(1)] = match.group(2)
    return constants


def parse_struct_fields_and_params(source: str) -> dict[str, dict[str, list[str]]]:
    structs: dict[str, dict[str, list[str]]] = {}
    for match in re.finditer(r"internal\s+readonly\s+struct\s+(\w+Profile)\b", source):
        struct_name = match.group(1)
        block, _open_index, _close_index = read_block_after(source, match.start())
        fields = re.findall(r"internal\s+readonly\s+[\w?<>]+\s+(\w+);", block)
        constructor_match = re.search(r"internal\s+" + re.escape(struct_name) + r"\s*\(", block)
        parameters: list[str] = []
        if constructor_match:
            param_start = block.index("(", constructor_match.start())
            depth = 0
            close_param = None
            for index in range(param_start, len(block)):
                if block[index] == "(":
                    depth += 1
                elif block[index] == ")":
                    depth -= 1
                    if depth == 0:
                        close_param = index
                        break
            if close_param is not None:
                raw_params = block[param_start + 1 : close_param]
                for raw_param in split_top_level_csv(raw_params):
                    left = raw_param.split("=", 1)[0].strip()
                    if not left:
                        continue
                    parameters.append(left.split()[-1].strip())
        structs[struct_name] = {
            "fields": fields,
            "parameters": parameters,
        }
    return structs


def camel_to_pascal(name: str) -> str:
    if not name:
        return name
    return name[0].upper() + name[1:]


def normalize_value(raw: str, constants: dict[str, str]) -> object:
    value = raw.strip()
    ternary = re.fullmatch(r'(\w+(?:\s*==\s*"[^"]+")?)\s*\?\s*"([^"]+)"\s*:\s*"([^"]+)"', value)
    if ternary:
        return {
            "ternaryCondition": ternary.group(1).strip(),
            "true": ternary.group(2),
            "false": ternary.group(3),
        }
    if value in constants:
        return constants[value]
    if value == "true":
        return True
    if value == "false":
        return False
    if value == "null":
        return None
    if re.fullmatch(r"-?\d+", value):
        return int(value)
    if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
        return bytes(value[1:-1], "utf-8").decode("unicode_escape")
    return {"symbol": value}


def invocation_end(text: str, open_paren: int) -> int:
    depth = 0
    in_string = False
    escaped = False
    for index in range(open_paren, len(text)):
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
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return index
    raise ValueError(f"unmatched invocation at {open_paren}")


def parse_profiles(source: str) -> dict[str, object]:
    constants = parse_constants(source)
    structs = parse_struct_fields_and_params(source)
    rows: list[dict[str, object]] = []
    parse_errors: list[str] = []

    method_pattern = re.compile(r"internal\s+static\s+bool\s+TryGet(\w+)Profile\s*\(")
    for method_match in method_pattern.finditer(source):
        family = method_match.group(1)
        method_body, method_open, _method_close = read_block_after(source, method_match.start())
        method_offset = method_open + 1
        search_start = 0
        while True:
            new_match = re.search(r"profile\s*=\s*new\s+(\w+Profile)\s*\(", method_body[search_start:])
            if not new_match:
                break
            absolute = search_start + new_match.start()
            profile_type = new_match.group(1)
            open_paren = search_start + new_match.end() - 1
            try:
                close_paren = invocation_end(method_body, open_paren)
            except ValueError as exc:
                parse_errors.append(str(exc))
                break
            args_text = method_body[open_paren + 1 : close_paren]
            args = split_top_level_csv(args_text)
            struct_info = structs.get(profile_type, {"parameters": [], "fields": []})
            parameters = list(struct_info.get("parameters", []))
            values: dict[str, object] = {}
            positional_index = 0
            for arg in args:
                if ":" in arg and re.match(r"^\w+\s*:", arg):
                    name, raw_value = arg.split(":", 1)
                    values[camel_to_pascal(name.strip())] = normalize_value(raw_value, constants)
                    continue
                if positional_index >= len(parameters):
                    parse_errors.append(f"{profile_type} has unmapped positional argument in {family}: {arg}")
                    positional_index += 1
                    continue
                values[camel_to_pascal(parameters[positional_index])] = normalize_value(arg, constants)
                positional_index += 1

            base_rows = expand_known_variants(values)
            source_line = source.count("\n", 0, method_offset + absolute) + 1
            for variant_values in base_rows:
                faction = variant_values.get("FactionSid")
                law_name = variant_values.get("LawName")
                effect_key = variant_values.get("EffectKey")
                rank = variant_values.get("Rank")
                if not isinstance(faction, str):
                    parse_errors.append(f"{family} profile at line {source_line} has unresolved faction {faction!r}")
                if not isinstance(law_name, str):
                    parse_errors.append(f"{family} profile at line {source_line} has unresolved law name {law_name!r}")
                if not isinstance(effect_key, str):
                    parse_errors.append(f"{family} profile at line {source_line} has unresolved effect key {effect_key!r}")

                required_predicates = sorted(
                    key for key, value in variant_values.items()
                    if key.startswith("Requires") and value is True
                )
                numeric_effects = {
                    key: value for key, value in sorted(variant_values.items())
                    if isinstance(value, int)
                    and not isinstance(value, bool)
                    and value != 0
                    and key not in {"Rank", "LawIndex"}
                }
                data_only = variant_values.get("DataOnly", False)
                evidence = variant_values.get("EvidenceBoundary")
                if not evidence:
                    evidence = "constructor default evidence boundary; inspect profile source before promoting gameplay"
                row = {
                    "family": family,
                    "packet": FAMILY_PACKET.get(family, "unknown"),
                    "handler": variant_values.get("HandlerKey", FAMILY_HANDLER.get(family, "unknown")),
                    "profileType": profile_type,
                    "factionSid": faction,
                    "lawName": law_name,
                    "effectKey": effect_key,
                    "rank": rank,
                    "dataOnly": data_only,
                    "requiredPredicates": required_predicates,
                    "numericEffects": numeric_effects,
                    "evidenceBoundary": evidence,
                    "sourceFile": str(PROFILE_SOURCE.relative_to(ROOT)).replace("\\", "/"),
                    "sourceLine": source_line,
                    "values": variant_values,
                }
                rows.append(row)
            search_start = close_paren + 1

    rows.sort(key=lambda row: (str(row["family"]), str(row["factionSid"]), str(row["effectKey"]), int(row["sourceLine"])))
    return {
        "schemaVersion": 1,
        "purpose": "Static inventory of source-prepared custom faction law effect profiles. This is not runtime proof and does not authorize gameplay mutation.",
        "source": str(PROFILE_SOURCE.relative_to(ROOT)).replace("\\", "/"),
        "familiesExpected": sorted(EXPECTED_FAMILIES),
        "customFactionsExpected": sorted(EXPECTED_CUSTOM_FACTIONS),
        "rows": rows,
        "parseErrors": parse_errors,
    }


def expand_known_variants(values: dict[str, object]) -> list[dict[str, object]]:
    ternary_items = {
        key: value for key, value in values.items()
        if isinstance(value, dict) and "ternaryCondition" in value
    }
    if not ternary_items:
        handler_key = values.get("HandlerKey")
        law_index = values.get("LawIndex")
        if handler_key == {"symbol": "handlerKey"} and law_index == {"symbol": "lawIndex"}:
            return [
                materialize_symbol_variant(values, {"HandlerKey": "spell.low", "LawIndex": 15, "PacketVariant": "spell-low"}),
                materialize_symbol_variant(values, {"HandlerKey": "spell.high", "LawIndex": 27, "PacketVariant": "spell-high"}),
            ]
        if handler_key == {"symbol": "handlerKey"}:
            return [
                materialize_symbol_variant(values, {"HandlerKey": "battle.melee-formation", "PacketVariant": "melee-formation"}),
                materialize_symbol_variant(values, {"HandlerKey": "battle.ranged-formation", "PacketVariant": "ranged-formation"}),
            ]
        return [materialize_symbol_variant(values, {})]

    conditions = sorted({str(value["ternaryCondition"]) for value in ternary_items.values()})
    if conditions == ["isCalendar"]:
        return [
            materialize_variant(values, "isCalendar", True, {"HandlerKey": "reward.calendar", "PacketVariant": "calendar"}),
            materialize_variant(values, "isCalendar", False, {"HandlerKey": "reward.gold-economy", "PacketVariant": "gold-economy"}),
        ]
    if conditions == ['handlerKey == "battle.ranged-formation"']:
        return [
            materialize_variant(
                values,
                'handlerKey == "battle.ranged-formation"',
                True,
                {"HandlerKey": "battle.ranged-formation", "PacketVariant": "ranged-formation"},
            ),
            materialize_variant(
                values,
                'handlerKey == "battle.ranged-formation"',
                False,
                {"HandlerKey": "battle.melee-formation", "PacketVariant": "melee-formation"},
            ),
        ]
    return [materialize_symbol_variant(values, {})]


def materialize_variant(
    values: dict[str, object],
    condition: str,
    branch: bool,
    extras: dict[str, object],
) -> dict[str, object]:
    materialized: dict[str, object] = {}
    branch_key = "true" if branch else "false"
    for key, value in values.items():
        if isinstance(value, dict) and value.get("ternaryCondition") == condition:
            materialized[key] = value[branch_key]
        else:
            materialized[key] = value
    materialized.update(extras)
    return materialize_symbol_variant(materialized, {})


def materialize_symbol_variant(values: dict[str, object], extras: dict[str, object]) -> dict[str, object]:
    materialized = dict(values)
    materialized.update(extras)
    for key, value in list(materialized.items()):
        if value == {"symbol": "isCalendar"}:
            materialized[key] = materialized.get("PacketVariant") == "calendar"
        elif value == {"symbol": "!isCalendar"}:
            materialized[key] = materialized.get("PacketVariant") != "calendar"
        elif value == {"symbol": 'handlerKey == "battle.ranged-formation"'}:
            materialized[key] = materialized.get("HandlerKey") == "battle.ranged-formation"
        elif value == {"symbol": "handlerKey"}:
            materialized[key] = materialized.get("HandlerKey")
        elif value == {"symbol": "lawIndex"}:
            materialized[key] = materialized.get("LawIndex")
    return materialized


def validate_inventory(inventory: dict[str, object]) -> list[str]:
    errors: list[str] = []
    rows = inventory.get("rows")
    if not isinstance(rows, list):
        return ["inventory rows must be a list"]
    if inventory.get("parseErrors"):
        errors.extend(str(error) for error in inventory["parseErrors"])

    seen_families = {str(row.get("family")) for row in rows if isinstance(row, dict)}
    missing_families = EXPECTED_FAMILIES - seen_families
    if missing_families:
        errors.append("missing profile families: " + ", ".join(sorted(missing_families)))

    coverage: dict[str, set[str]] = {family: set() for family in EXPECTED_FAMILIES}
    for row in rows:
        if not isinstance(row, dict):
            errors.append(f"row is not an object: {row!r}")
            continue
        family = str(row.get("family"))
        faction = row.get("factionSid")
        effect_key = row.get("effectKey")
        law_name = row.get("lawName")
        packet = row.get("packet")
        evidence = row.get("evidenceBoundary")
        if family in coverage and isinstance(faction, str):
            coverage[family].add(faction)
        if faction == "homm3_castle":
            continue
        if not isinstance(faction, str) or faction not in EXPECTED_CUSTOM_FACTIONS:
            errors.append(f"{family} row has unexpected faction: {faction!r}")
        if packet == "unknown":
            errors.append(f"{family}/{faction} has unknown packet")
        if not isinstance(effect_key, str) or not effect_key:
            errors.append(f"{family}/{faction} missing effect key")
        if not isinstance(law_name, str) or not law_name:
            errors.append(f"{family}/{faction} missing law name")
        if not isinstance(evidence, str) or not evidence:
            errors.append(f"{family}/{faction}/{effect_key} missing evidence boundary")
        haystack = " ".join(str(row.get(key, "")) for key in ("lawName", "effectKey", "evidenceBoundary"))
        if "edict" in haystack.lower():
            errors.append(f"{family}/{faction}/{effect_key} contains banned placeholder term Edict")
        if "fallback" in haystack.lower():
            errors.append(f"{family}/{faction}/{effect_key} contains banned fallback wording")
        numeric = row.get("numericEffects")
        if isinstance(numeric, dict) and numeric.get("DamagePercentBonus") == 5:
            errors.append(f"{family}/{faction}/{effect_key} uses banned generic +5 damage profile")

    for family, factions in sorted(coverage.items()):
        missing = EXPECTED_CUSTOM_FACTIONS - factions
        if missing:
            errors.append(f"{family} missing custom factions: " + ", ".join(sorted(missing)))

    return errors


def validate_target_coverage(inventory: dict[str, object], targets_path: Path) -> list[str]:
    if not targets_path.exists():
        return [f"missing custom law targets file: {targets_path}"]
    try:
        targets_doc = json.loads(targets_path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        return [f"failed to parse custom law targets: {exc}"]
    rows = inventory.get("rows", [])
    if not isinstance(rows, list):
        return ["inventory rows must be available before target coverage validation"]
    index: set[tuple[str, str, str, str]] = set()
    rows_by_family_faction: dict[tuple[str, str], list[str]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        family = str(row.get("family"))
        faction_sid = str(row.get("factionSid"))
        handler = str(row.get("handler"))
        law_name = str(row.get("lawName"))
        index.add((faction_sid, family, handler, law_name))
        rows_by_family_faction.setdefault((faction_sid, family), []).append(law_name)

    errors: list[str] = []
    targets = targets_doc.get("targets") if isinstance(targets_doc, dict) else None
    if not isinstance(targets, list):
        return ["custom law targets must contain a targets list"]
    for target in targets:
        if not isinstance(target, dict):
            errors.append(f"target row is not an object: {target!r}")
            continue
        status = target.get("implementationStatus")
        if status == "native-exact":
            continue
        faction = target.get("faction")
        law_index = target.get("lawIndex")
        name = target.get("name")
        if not isinstance(faction, str) or not isinstance(law_index, int) or not isinstance(name, str):
            errors.append(f"target row has invalid faction/lawIndex/name: {target!r}")
            continue
        requirement = LAW_INDEX_PROFILE_REQUIREMENTS.get(law_index)
        if requirement is None:
            errors.append(f"homm3_{faction} law {law_index}: no profile requirement mapping")
            continue
        family, handler = requirement
        faction_sid = f"homm3_{faction}"
        key = (faction_sid, family, handler, name)
        if key not in index:
            available = sorted(set(rows_by_family_faction.get((faction_sid, family), [])))
            errors.append(
                f"{target.get('lawSid', faction_sid + ':' + str(law_index))}: "
                f"no matching effect profile for family={family} handler={handler} name={name!r}; "
                f"available for faction/family={available}"
            )
    return errors


def render_markdown(inventory: dict[str, object], errors: list[str]) -> str:
    rows = inventory["rows"]
    lines = [
        "# Custom Law Effect Plan Inventory",
        "",
        "Generated from `Homm3CustomLawEffectProfiles.cs`.",
        "",
        "Boundary: this is source-prepared static inventory only. It does not prove runtime event reachability, active law/rank resolution, ordering, idempotence, UI synchronization, or Harmony safety.",
        "",
        f"- Rows: {len(rows)}",
        f"- Validation errors: {len(errors)}",
        f"- Target coverage errors: {len(inventory.get('targetCoverageErrors', []))}",
        "",
    ]
    if errors:
        lines.append("## Validation errors")
        lines.append("")
    target_errors = inventory.get("targetCoverageErrors", [])
    if target_errors:
        lines.append("## Target coverage errors")
        lines.append("")
        for error in target_errors:
            lines.append(f"- {error}")
        lines.append("")
        for error in errors:
            lines.append(f"- {error}")
        lines.append("")

    by_family: dict[str, list[dict[str, object]]] = {}
    for row in rows:
        by_family.setdefault(str(row["family"]), []).append(row)
    for family in sorted(by_family):
        lines.append(f"## {family}")
        lines.append("")
        lines.append("| Faction | Law | Effect key | Rank | Packet | Handler | Data-only | Predicates | Numeric effects | Boundary |")
        lines.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
        for row in by_family[family]:
            predicates = ", ".join(str(value) for value in row["requiredPredicates"]) or "-"
            numeric = ", ".join(f"{key}={value}" for key, value in row["numericEffects"].items()) or "-"
            lines.append(
                "| "
                + " | ".join(
                    [
                        str(row["factionSid"]),
                        str(row["lawName"]).replace("|", "\\|"),
                        str(row["effectKey"]),
                        str(row["rank"]),
                        str(row["packet"]),
                        str(row["handler"]).replace("|", "\\|"),
                        str(row["dataOnly"]),
                        predicates,
                        numeric,
                        str(row["evidenceBoundary"]).replace("|", "\\|"),
                    ]
                )
                + " |"
            )
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-json", type=Path, default=None)
    parser.add_argument("--out-md", type=Path, default=None)
    parser.add_argument("--write-defaults", action="store_true")
    args = parser.parse_args()

    if not PROFILE_SOURCE.exists():
        return fail(f"missing profile source: {PROFILE_SOURCE}")
    source = PROFILE_SOURCE.read_text(encoding="utf-8")
    inventory = parse_profiles(source)
    errors = validate_inventory(inventory)
    target_coverage_errors = validate_target_coverage(inventory, TARGETS_PATH)
    errors.extend(target_coverage_errors)
    inventory["validationErrors"] = errors
    inventory["targetCoverageErrors"] = target_coverage_errors
    inventory["validationState"] = "source-prepared-static-only" if not errors else "invalid"

    out_json = args.out_json
    out_md = args.out_md
    if args.write_defaults:
        out_json = out_json or DEFAULT_JSON
        out_md = out_md or DEFAULT_MD

    if out_json:
        out_json.parent.mkdir(parents=True, exist_ok=True)
        out_json.write_text(json.dumps(inventory, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if out_md:
        out_md.parent.mkdir(parents=True, exist_ok=True)
        out_md.write_text(render_markdown(inventory, errors) + "\n", encoding="utf-8")

    if errors:
        print("custom law effect plan inventory validation failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1

    print(f"custom law effect plan inventory ok: {len(inventory['rows'])} profile rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
