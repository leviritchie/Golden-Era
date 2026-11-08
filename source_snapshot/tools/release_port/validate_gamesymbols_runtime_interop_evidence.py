#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GAME_SYMBOLS = ROOT / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod" / "GameSymbols.cs"
RUNTIME_MAP = ROOT / "experiments" / "cpp2il_readable_csharp" / "samples" / "latest_refresh" / "runtime_interop_map.json"

# Guard the battle-law ownership surface that caused repeated counterattack drift.
# These groups are runtime-reflection names, not prose decomp symbols. Every method/getter
# name here must exist in the generated interop map for the expected runtime type.
REQUIRED_GROUPS = {
    "BattleObjectBattleContextMembers": {
        "types": {
            "Hex.Session.Battle.FieldObject",
            "FieldObjectPublicAbstractObUnObcfcnObstcnUnHeUnique",
            "ObjectPublicObceInBoInceAbObELInUnique",
        },
        "allow_field_if_getter_exists": False,
    },
    "BattleContextTransferSideMembers": {
        "types": {"ObjectPublicPrcgObPrcgInTrPrcgInUnique"},
        "allow_field_if_getter_exists": True,
    },
    "BattleObjectHexMembers": {
        "types": {"FieldObjectPublicAbstractObUnObcfcnObstcnUnHeUnique", "Hex.Session.Battle.FieldObject"},
        "allow_field_if_getter_exists": False,
    },
    "HexOccupantMembers": {
        "types": {"Hex.Session.Battle.Hex"},
        "allow_field_if_getter_exists": True,
    },
}

RAW_DECOMP_NAMES_FORBIDDEN = {
    "BattleObjectBattleContextMembers": {"basa", "bcuk", "cfnp", "get_cfnp"},
    "BattleContextTransferSideMembers": {"cgle"},
    "BattleObjectHexMembers": {"bask", "bcux", "cfpm", "get_cfpm"},
    "HexOccupantMembers": {"bcya", "cfsc", "get_cfsc", "get__cfsc_k__BackingField", "<cfsc>k__BackingField"},
}

# Guard the HoMM3 fast-city-opening hook against silent obfuscation drift. The
# hook may keep older decomp names as tolerance, but these generated names must
# exist in GameSymbols and in the current runtime interop map.
REQUIRED_METHOD_SYMBOL_NAMES = {
    "CityFrameCount": {
        "types": {"ObjectPublicSicbInStcbOpSiETStBoUnique"},
        "required_names": {
            "Method_Public_Int32_EType_String_0",
            "Method_Public_Int32_EType_String_PDM_0",
            "Method_Public_Int32_EType_String_PDM_1",
            "Method_Public_Int32_EType_String_PDM_2",
        },
    },
    "OpeningFrameCount": {
        "types": {"ObjectPublicAbstractSealedIncbUnique"},
        "required_names": {
            "Method_Private_Static_Int32_EType_String_0",
            "Method_Private_Static_Int32_EType_String_PDM_0",
            "Method_Private_Static_Int32_EType_String_PDM_1",
            "Method_Private_Static_Int32_EType_String_PDM_2",
            "Method_Private_Static_Int32_EType_String_PDM_3",
        },
    },
}

REQUIRED_TYPE_HINTS = {
    "OpenTimeTrackerTypeHints": {"ObjectPublicSicbInStcbOpSiETStBoUnique"},
    "OpeningFacadeTypeHints": {"ObjectPublicAbstractSealedIncbUnique"},
}

STALE_SMOOTH_OPENING_NOTES_FORBIDDEN = {
    "startup registration still needs validation before marking proven",
}

# Marshal Suppressing Fire: live trap type + TrapConfig getter must stay pinned against
# generated Hex.dll interop metadata (opt-in expensive audit).
MARSHAL_SUPPRESSING_FIRE_TRAP_TYPE = "FieldObjectPublicObBoTrAcTrcg1AcHeUnUnique"
MARSHAL_SUPPRESSING_FIRE_TRAP_CONFIG = "_cgtl_k__BackingField"
MARSHAL_SUPPRESSING_FIRE_TRAP_CONFIG_GETTER = "get__cgtl_k__BackingField"


def load_runtime_map() -> dict:
    with RUNTIME_MAP.open("r", encoding="utf-8-sig") as f:
        return json.load(f)


def load_runtime_methods(data: dict | None = None) -> dict[str, set[str]]:
    payload = data if data is not None else load_runtime_map()
    methods: dict[str, set[str]] = {}
    for row in payload.get("types", []):
        runtime_type = row.get("runtime_type")
        if not runtime_type:
            continue
        names = {m.get("runtime_method") for m in row.get("methods", []) if m.get("runtime_method")}
        methods[runtime_type] = names
    return methods


def load_runtime_type_rows(data: dict | None = None) -> dict[str, dict]:
    payload = data if data is not None else load_runtime_map()
    rows: dict[str, dict] = {}
    for row in payload.get("types", []):
        runtime_type = row.get("runtime_type")
        if runtime_type:
            rows[runtime_type] = row
    return rows


def parse_group(source: str, group: str) -> list[str]:
    header = re.search(rf"internal\s+static\s+readonly\s+string\[\]\s+{re.escape(group)}\s*=", source)
    if not header:
        raise ValueError(f"missing GameSymbols group {group}")
    semi = source.find(";", header.end())
    if semi < 0:
        raise ValueError(f"unterminated GameSymbols group {group}")
    block = source[header.end():semi]
    return re.findall(r'"([^"]+)"', block)


def parse_method_symbol(source: str, symbol: str) -> list[str]:
    match = re.search(
        rf"internal\s+static\s+readonly\s+MethodSymbol\s+{re.escape(symbol)}\s*=\s*new\s*\((.*?)\);",
        source,
        re.S,
    )
    if not match:
        raise ValueError(f"missing or unterminated GameSymbols MethodSymbol {symbol}")
    names = re.findall(r'"([^"]+)"', match.group(1))
    if not names:
        raise ValueError(f"GameSymbols MethodSymbol {symbol} has no names")
    return names[1:]


def getter_for_field(name: str) -> str | None:
    if name.startswith("field_"):
        return "get_" + name
    if name.startswith("<") and name.endswith(">k__BackingField"):
        inner = name[1:].split(">", 1)[0]
        return f"get__{inner}_k__BackingField"
    return None


def validate_marshal_suppressing_fire(source: str, type_rows: dict[str, dict], errors: list[str]) -> None:
    try:
        type_hints = parse_group(source, "TrapRuntimeTypeHints")
        config_hints = parse_group(source, "InstanceTrapConfigMembers")
    except ValueError as exc:
        errors.append(str(exc))
        return

    if not type_hints or type_hints[0] != MARSHAL_SUPPRESSING_FIRE_TRAP_TYPE:
        errors.append(
            "TrapRuntimeTypeHints must lead with live Marshal trap type "
            f"'{MARSHAL_SUPPRESSING_FIRE_TRAP_TYPE}'"
        )
    if "ekh" not in type_hints:
        errors.append("TrapRuntimeTypeHints must retain legacy alias 'ekh'")
    if not config_hints or config_hints[0] != MARSHAL_SUPPRESSING_FIRE_TRAP_CONFIG:
        errors.append(
            "InstanceTrapConfigMembers must lead with "
            f"'{MARSHAL_SUPPRESSING_FIRE_TRAP_CONFIG}'"
        )

    row = type_rows.get(MARSHAL_SUPPRESSING_FIRE_TRAP_TYPE)
    if row is None:
        errors.append(
            f"Marshal Suppressing Fire trap type '{MARSHAL_SUPPRESSING_FIRE_TRAP_TYPE}' "
            "is not present in runtime interop map"
        )
        return

    init_matches = [
        method
        for method in row.get("methods", [])
        if method.get("runtime_method") == "Init"
        and method.get("return_type") == "System.Boolean"
        and method.get("parameter_count") == 6
    ]
    if not init_matches:
        errors.append(
            f"{MARSHAL_SUPPRESSING_FIRE_TRAP_TYPE}: missing six-argument Boolean Init "
            "in runtime interop map"
        )

    getter_matches = [
        method
        for method in row.get("methods", [])
        if method.get("runtime_method") == MARSHAL_SUPPRESSING_FIRE_TRAP_CONFIG_GETTER
        and method.get("return_type") == "Hex.Configs.TrapConfig"
        and method.get("parameter_count") == 0
    ]
    if not getter_matches:
        errors.append(
            f"{MARSHAL_SUPPRESSING_FIRE_TRAP_TYPE}: missing "
            f"{MARSHAL_SUPPRESSING_FIRE_TRAP_CONFIG_GETTER} TrapConfig getter "
            "in runtime interop map"
        )


def main() -> int:
    if not GAME_SYMBOLS.exists():
        print(f"missing GameSymbols.cs: {GAME_SYMBOLS}", file=sys.stderr)
        return 1
    if not RUNTIME_MAP.exists():
        print(f"missing runtime interop map: {RUNTIME_MAP}", file=sys.stderr)
        return 1
    source = GAME_SYMBOLS.read_text(encoding="utf-8-sig")
    runtime_map = load_runtime_map()
    runtime_methods = load_runtime_methods(runtime_map)
    type_rows = load_runtime_type_rows(runtime_map)
    errors: list[str] = []
    for group, rule in REQUIRED_GROUPS.items():
        try:
            names = parse_group(source, group)
        except ValueError as exc:
            errors.append(str(exc))
            continue
        forbidden = RAW_DECOMP_NAMES_FORBIDDEN.get(group, set())
        for name in names:
            if name in forbidden:
                errors.append(f"{group}: raw/stale decomp name '{name}' is not allowed without generated interop evidence")
                continue
            found = any(name in runtime_methods.get(type_name, set()) for type_name in rule["types"])
            if not found and rule.get("allow_field_if_getter_exists"):
                getter = getter_for_field(name)
                found = bool(getter) and any(getter in runtime_methods.get(type_name, set()) for type_name in rule["types"])
            if not found:
                type_list = ", ".join(sorted(rule["types"]))
                errors.append(f"{group}: '{name}' is not present in generated interop methods for expected type(s): {type_list}")

    for symbol, rule in REQUIRED_METHOD_SYMBOL_NAMES.items():
        try:
            names = set(parse_method_symbol(source, symbol))
        except ValueError as exc:
            errors.append(str(exc))
            continue
        missing_from_source = sorted(rule["required_names"] - names)
        for name in missing_from_source:
            errors.append(f"{symbol}: required generated runtime method name '{name}' is missing from GameSymbols.cs")
        for name in sorted(rule["required_names"]):
            found = any(name in runtime_methods.get(type_name, set()) for type_name in rule["types"])
            if not found:
                type_list = ", ".join(sorted(rule["types"]))
                errors.append(f"{symbol}: required generated runtime method name '{name}' is not present in runtime interop type(s): {type_list}")

    for group, required_types in REQUIRED_TYPE_HINTS.items():
        try:
            names = set(parse_group(source, group))
        except ValueError as exc:
            errors.append(str(exc))
            continue
        missing_from_source = sorted(required_types - names)
        for type_name in missing_from_source:
            errors.append(f"{group}: required generated runtime type name '{type_name}' is missing from GameSymbols.cs")
        for type_name in sorted(required_types):
            if type_name not in runtime_methods:
                errors.append(f"{group}: required generated runtime type name '{type_name}' is not present in runtime interop map")

    lower_source = source.lower()
    for note in STALE_SMOOTH_OPENING_NOTES_FORBIDDEN:
        if note in lower_source:
            errors.append(f"GameSymbols.cs contains stale SmoothOpening note: {note}")

    validate_marshal_suppressing_fire(source, type_rows, errors)

    if errors:
        print("GameSymbols runtime interop evidence validation failed:", file=sys.stderr)
        for error in errors:
            print(" - " + error, file=sys.stderr)
        return 1
    print("GameSymbols runtime interop evidence validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
