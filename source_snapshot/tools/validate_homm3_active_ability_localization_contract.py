#!/usr/bin/env python3
"""Validate HoMM3 custom unit ability localization hygiene.

This contract checks player-facing active and passive unit ability text. It
virtually applies the source localization cleanup rows from the Core overlay to
the current generated Core artifact, then fails if a custom unit ability still
resolves to a raw token, exposes implementation terms, or uses known vague
placeholder wording instead of concrete quantities.
"""

from __future__ import annotations

import argparse
import ast
import json
import pathlib
import re
import sys
import zipfile
from typing import Any


FORBIDDEN_PLAYER_TERMS = re.compile(r"\b(native|exact|runtime|SID|donor|Core|deobf|tracing|validation|implementation)\b", re.IGNORECASE)
VAGUE_PLAYER_TERMS = re.compile(
    r"\b(partial|more effectively|restore health to an allied stack\.|slow an enemy\.|"
    r"pure magic damage\.|normal damage\.|damage debuff|powerful boon|Spend Focus)\b",
    re.IGNORECASE,
)
RAW_TOKEN_TEXT = re.compile(r"^[a-z0-9]+(?:_[a-z0-9]+)*_(?:name|description)$")
FOCUS_COST_TEXT = re.compile(r"\bSpend\s+(\d+)\s+Focus\b", re.IGNORECASE)
CUSTOM_VIEW_PATH = re.compile(r"^DB/units/units_views/(homm3_[^/]+|neutral)/(h3_[^/]+)_v\.json$")
SHARED_SOURCE_LOCALIZATION_SIDS = {
    "h3_common_ability_curse_description",
    "h3_common_ability_magnetic_slow_description",
}


def fail(message: str) -> None:
    print(f"homm3-active-ability-localization-contract: {message}", file=sys.stderr)
    raise SystemExit(1)


def first_array_item(doc: Any) -> dict[str, Any] | None:
    if isinstance(doc, dict) and isinstance(doc.get("array"), list) and doc["array"]:
        item = doc["array"][0]
        return item if isinstance(item, dict) else None
    if isinstance(doc, list) and doc:
        item = doc[0]
        return item if isinstance(item, dict) else None
    if isinstance(doc, dict):
        return doc
    return None


def extract_cleanup_rows(overlay_source: pathlib.Path) -> dict[str, str]:
    source = overlay_source.read_text(encoding="utf-8-sig")
    tree = ast.parse(source)
    rows_node: ast.AST | None = None
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "CUSTOM_ACTIVE_ABILITY_LOCALIZATION_ROWS":
                    rows_node = node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.target.id == "CUSTOM_ACTIVE_ABILITY_LOCALIZATION_ROWS":
                rows_node = node.value
    if rows_node is None:
        fail("apply_release_core_overlay.py must define CUSTOM_ACTIVE_ABILITY_LOCALIZATION_ROWS")
    try:
        raw_rows = ast.literal_eval(rows_node)
    except (SyntaxError, ValueError) as ex:
        fail(f"CUSTOM_ACTIVE_ABILITY_LOCALIZATION_ROWS must be a literal table: {ex}")
    if not isinstance(raw_rows, (list, tuple)) or not raw_rows:
        fail("CUSTOM_ACTIVE_ABILITY_LOCALIZATION_ROWS must be a non-empty row list")

    rows: dict[str, str] = {}
    for index, row in enumerate(raw_rows):
        if not isinstance(row, dict):
            fail(f"cleanup row {index} must be a dict")
        sid = row.get("sid")
        text = row.get("text")
        if not isinstance(sid, str) or not sid.strip():
            fail(f"cleanup row {index} is missing sid")
        if not isinstance(text, str) or not text.strip():
            fail(f"cleanup row {sid} is missing text")
        if sid in rows:
            fail(f"duplicate cleanup localization sid: {sid}")
        if RAW_TOKEN_TEXT.fullmatch(text):
            fail(f"cleanup row {sid} still uses raw token text {text!r}")
        if FORBIDDEN_PLAYER_TERMS.search(text):
            fail(f"cleanup row {sid} exposes implementation term in {text!r}")
        if VAGUE_PLAYER_TERMS.search(text):
            fail(f"cleanup row {sid} uses vague player-facing text {text!r}")
        rows[sid] = text
    return rows


def validate_shared_source_localization_rows(source_text: str) -> list[str]:
    """Catch conflicting shared-token definitions before the overlay merges rows."""
    tree = ast.parse(source_text)
    definitions: dict[str, list[tuple[str, int, str]]] = {}
    for node in tree.body:
        assignments: list[tuple[str, ast.AST]] = []
        if isinstance(node, ast.Assign):
            assignments.extend((target.id, node.value) for target in node.targets if isinstance(target, ast.Name))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            assignments.append((node.target.id, node.value))
        for constant_name, value_node in assignments:
            if not (constant_name.endswith("_LANG_ROWS") or constant_name.endswith("_LOCALIZATION_ROWS")):
                continue
            try:
                rows = ast.literal_eval(value_node)
            except (SyntaxError, ValueError):
                continue
            if not isinstance(rows, (list, tuple)):
                continue
            for row in rows:
                if not isinstance(row, dict):
                    continue
                sid = row.get("sid")
                text = row.get("text")
                if isinstance(sid, str) and sid in SHARED_SOURCE_LOCALIZATION_SIDS and isinstance(text, str):
                    definitions.setdefault(sid, []).append((constant_name, node.lineno, text))

    issues: list[str] = []
    for sid in sorted(SHARED_SOURCE_LOCALIZATION_SIDS):
        rows = definitions.get(sid, [])
        if not rows:
            issues.append(f"source localization row collections do not define {sid}")
            continue
        unique_texts = {text for _name, _line, text in rows}
        if len(unique_texts) > 1:
            sources = ", ".join(f"{name}:{line}" for name, line, _text in rows)
            issues.append(f"conflicting source definitions for {sid} before language-row merge ({sources})")
    return issues


def validate_view_ability_localization(
    member: str,
    slot_name: str,
    index: int,
    ability: dict[str, Any],
    language_rows: dict[str, str],
    issues: list[str],
) -> tuple[str | None, str | None]:
    resolved_fields: dict[str, str | None] = {}
    for field in ("name", "description"):
        resolved = resolve_text(ability.get(field), language_rows)
        resolved_fields[field] = resolved
        if resolved is None or not resolved.strip():
            issues.append(f"{member} {slot_name}[{index}] {field} is missing player-facing text")
            continue
        if RAW_TOKEN_TEXT.fullmatch(resolved):
            issues.append(f"{member} {slot_name}[{index}] {field} resolves to raw token {resolved!r}")
        if FORBIDDEN_PLAYER_TERMS.search(resolved):
            issues.append(f"{member} {slot_name}[{index}] {field} exposes implementation term in {resolved!r}")
        if field == "description" and VAGUE_PLAYER_TERMS.search(resolved):
            issues.append(f"{member} {slot_name}[{index}] {field} uses vague text {resolved!r}")
    return resolved_fields.get("name"), resolved_fields.get("description")


def read_units_ability_text(core_zip: zipfile.ZipFile) -> dict[str, str]:
    try:
        doc = json.loads(core_zip.read("Lang/english/texts/unitsAbility.json").decode("utf-8-sig"))
    except KeyError:
        fail("Core.zip is missing Lang/english/texts/unitsAbility.json")
    if not isinstance(doc, dict):
        fail("unitsAbility.json must be a JSON object")
    rows: dict[str, str] = {}
    for key in ("tokens", "array"):
        values = doc.get(key)
        if not isinstance(values, list):
            continue
        for row in values:
            if not isinstance(row, dict):
                continue
            sid = row.get("sid")
            text = row.get("text")
            if isinstance(sid, str) and isinstance(text, str):
                rows[sid] = text
    return rows


def resolve_text(value: Any, language_rows: dict[str, str]) -> str | None:
    if isinstance(value, str):
        return language_rows.get(value, value)
    if isinstance(value, list) and value:
        first = value[0]
        if isinstance(first, str):
            return language_rows.get(first, first)
    return None


def read_json_member(core_zip: zipfile.ZipFile, overlay: dict[str, bytes], member: str) -> Any:
    try:
        raw = overlay[member] if member in overlay else core_zip.read(member)
    except KeyError:
        fail(f"candidate Core output is missing {member}")
    try:
        return json.loads(raw.decode("utf-8-sig"))
    except (json.JSONDecodeError, UnicodeDecodeError) as ex:
        fail(f"cannot read candidate {member}: {ex}")


def read_json_member_or_none(core_zip: zipfile.ZipFile, overlay: dict[str, bytes], member: str) -> Any | None:
    try:
        raw = overlay[member] if member in overlay else core_zip.read(member)
    except KeyError:
        return None
    try:
        return json.loads(raw.decode("utf-8-sig"))
    except (json.JSONDecodeError, UnicodeDecodeError) as ex:
        fail(f"cannot read candidate {member}: {ex}")


def logic_member_for_view(member: str) -> str:
    return member.replace("DB/units/units_views/", "DB/units/units_logics/", 1).replace("_v.json", "_l.json")


def validate_active_description_contract(
    member: str,
    index: int,
    description: str,
    logic_ability: dict[str, Any] | None,
    issues: list[str],
) -> None:
    focus_match = FOCUS_COST_TEXT.search(description)
    if focus_match is not None:
        if logic_ability is None:
            issues.append(f"{member} abilities[{index}] description declares Focus cost but has no matching logic row")
        else:
            raw_energy = logic_ability.get("energyLevel")
            try:
                actual_energy = int(raw_energy)
            except (TypeError, ValueError):
                issues.append(f"{member} abilities[{index}] description declares Focus cost but logic energyLevel is {raw_energy!r}")
            else:
                expected_energy = int(focus_match.group(1))
                if actual_energy != expected_energy:
                    issues.append(
                        f"{member} abilities[{index}] description says Spend {expected_energy} Focus but logic energyLevel is {actual_energy}"
                    )
    if "without ending the turn" in description.lower():
        if logic_ability is None or logic_ability.get("actionCost") != 0:
            issues.append(f"{member} abilities[{index}] description says without ending the turn but logic actionCost is not 0")


def _nested_value(value: Any, path: tuple[str, ...]) -> Any:
    for key in path:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def _expect_equal(actual: Any, expected: Any, label: str, issues: list[str]) -> None:
    if actual != expected:
        issues.append(f"{label}: expected {expected!r}, got {actual!r}")


def _expect_terms(description: str | None, terms: tuple[str, ...], label: str, issues: list[str]) -> None:
    lowered = (description or "").lower()
    missing = [term for term in terms if term.lower() not in lowered]
    if missing:
        issues.append(f"{label}: description is missing {', '.join(repr(term) for term in missing)}")


def _buff_id(effect_row: Any, label: str, expected: str, issues: list[str]) -> None:
    actual = _nested_value(effect_row, ("damageDealer", "buff", "sid"))
    _expect_equal(actual, expected, f"{label} selected buff", issues)


def _view_description(
    view_item: dict[str, Any] | None,
    slot: str,
    index: int,
    language_rows: dict[str, str],
) -> str | None:
    rows = view_item.get(slot) if isinstance(view_item, dict) else None
    if not isinstance(rows, list) or index >= len(rows) or not isinstance(rows[index], dict):
        return None
    return resolve_text(rows[index].get("description"), language_rows)


def _buff_row(
    core_zip: zipfile.ZipFile,
    overlay: dict[str, bytes],
    member: str,
    buff_id: str,
    issues: list[str],
) -> dict[str, Any] | None:
    doc = read_json_member_or_none(core_zip, overlay, member)
    rows = doc.get("array") if isinstance(doc, dict) else None
    if isinstance(rows, list):
        for row in rows:
            if isinstance(row, dict) and row.get("id") == buff_id:
                return row
    issues.append(f"candidate Core is missing buff {buff_id!r} in {member}")
    return None


def _expect_description_percent(description: str | None, fraction: Any, label: str, issues: list[str]) -> None:
    try:
        percent = round(abs(float(fraction)) * 100)
    except (TypeError, ValueError):
        issues.append(f"{label}: configured percentage is not numeric ({fraction!r})")
        return
    if description is None or re.search(rf"\b{percent}\s*%", description) is None:
        issues.append(f"{label}: description does not state configured {percent}%")


def _expect_taunt_radius_text(description: str | None, radius: Any, label: str, issues: list[str]) -> None:
    try:
        expected_radius = int(radius)
    except (TypeError, ValueError):
        issues.append(f"{label}: configured taunt radius is not an integer ({radius!r})")
        return
    text = description or ""
    pattern = rf"\b{expected_radius}\s*[- ]?hex(?:es)?\b"
    if re.search(pattern, text, re.IGNORECASE) is None:
        issues.append(f"{label}: description does not state its configured {expected_radius}-hex radius")
    subject_pattern = rf"\ball enemies\b.{{0,80}}\bwithin a {expected_radius}\s*[- ]?hex(?:es)? radius\b.{{0,100}}\btarget only this stack\b"
    if re.search(subject_pattern, text, re.IGNORECASE) is None:
        issues.append(f"{label}: description does not state that nearby enemies are forced to target this stack")


def _expect_initial_attack_defense_text(description: str | None, label: str, issues: list[str]) -> None:
    if re.search(r"\binitially reduce (?:an enemy|the target)'s Attack and Defense by 3\b", description or "", re.IGNORECASE) is None:
        issues.append(f"{label}: description must state an initial -3 Attack and Defense reduction")


def _expect_behemoth_armor_pen_text(description: str | None, fraction: Any, label: str, issues: list[str]) -> None:
    _expect_description_percent(description, fraction, label, issues)
    _expect_terms(description, ("Defense",), label, issues)
    try:
        percent = round(abs(float(fraction)) * 100)
    except (TypeError, ValueError):
        return
    pattern = (
        rf"\b(?:attacks?\s+)?ignore\s+{percent}%\s+of\s+(?:the\s+)?enemy(?:'s)?\s+Defense\b|"
        rf"\bpenetrate\s+{percent}%\s+of\s+(?:the\s+)?enemy(?:'s)?\s+Defense\b"
    )
    if re.search(pattern, description or "", re.IGNORECASE) is None:
        issues.append(f"{label}: description must state that attacks ignore or penetrate {percent}% of enemy Defense")


def _validate_magnetic_slow_text(description: str | None, label: str, issues: list[str]) -> None:
    text = description or ""
    _expect_terms(text, ("Spend 1 Focus",), label, issues)
    if re.search(r"\b(?:reduce|decrease)\s+(?:an enemy's\s+)?Speed\s+and\s+Initiative\s+by\s+1\b", text, re.IGNORECASE) is None:
        issues.append(f"{label}: description must state that Speed and Initiative are reduced by 1")
    if re.search(r"\b\d+\s+rounds?\b", text, re.IGNORECASE):
        issues.append(f"{label}: description makes an unverified duration promise")


def validate_audited_effect_contracts(
    core_zip: zipfile.ZipFile,
    overlay: dict[str, bytes],
    unit_rows: dict[str, tuple[str, dict[str, Any], dict[str, Any] | None]],
    language_rows: dict[str, str],
    issues: list[str],
) -> None:
    """Pin corrected text to selected packed-config rows without asserting runtime outcomes."""
    def unit(member: str) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        row = unit_rows.get(member)
        if row is None:
            issues.append(f"candidate Core is missing audited unit view {member}")
            return None, None
        return row[1], row[2]

    def slot_row(logic: dict[str, Any] | None, slot: str, index: int, label: str) -> dict[str, Any] | None:
        rows = logic.get(slot) if isinstance(logic, dict) else None
        if not isinstance(rows, list) or index >= len(rows) or not isinstance(rows[index], dict):
            issues.append(f"{label}: candidate logic is missing {slot}[{index}]")
            return None
        return rows[index]

    def ability_cost(row: dict[str, Any] | None, expected: int, label: str) -> None:
        if row is not None:
            _expect_equal(row.get("energyLevel"), expected, f"{label} Focus cost", issues)

    # These selected records are the source of the corresponding visible magnitudes.
    mummy_view, mummy_logic = unit("DB/units/units_views/neutral/h3_mummy_v.json")
    mummy = slot_row(mummy_logic, "abilities", 0, "Mummy Curse")
    ability_cost(mummy, 1, "Mummy Curse")
    _buff_id(mummy, "Mummy Curse", "magic_unnatural_calm_effect_1_special", issues)
    if mummy is not None:
        _expect_equal(_nested_value(mummy, ("damageDealer", "buff", "duration")), 2, "Mummy Curse configured duration", issues)
    curse = _buff_row(core_zip, overlay, "DB/buffs/buffs_night_magics.json", "magic_unnatural_calm_effect_1_special", issues)
    curse_mods = _nested_value(curse, ("data", "stats", "outDmgMods", "list"))
    normal_damage = next((row.get("v") for row in curse_mods if isinstance(row, dict) and row.get("t") == "normal_damage"), None) if isinstance(curse_mods, list) else None
    _expect_equal(normal_damage, -0.2, "Mummy Curse configured normal-damage modifier", issues)
    _expect_equal(_nested_value(curse, ("data", "alwaysMinDmg")), True, "Mummy Curse minimum-damage flag", issues)
    mummy_text = _view_description(mummy_view, "abilities", 0, language_rows)
    _expect_terms(mummy_text, ("Spend 1 Focus", "20%", "normal damage", "minimum damage", "2 rounds"), "Mummy Curse", issues)
    if re.search(r"\breduce an enemy's normal damage by 20%", mummy_text or "", re.IGNORECASE) is None:
        issues.append("Mummy Curse: description does not state the configured outgoing normal-damage reduction")
    if re.search(r"\bforce minimum damage\b", mummy_text or "", re.IGNORECASE) is None:
        issues.append("Mummy Curse: description does not state the configured minimum-damage effect")

    enchanter_view, enchanter_logic = unit("DB/units/units_views/neutral/h3_enchanter_v.json")
    slow = slot_row(enchanter_logic, "abilities", 1, "Enchanter Magnetic Slow")
    ability_cost(slow, 1, "Enchanter Magnetic Slow")
    _buff_id(slow, "Enchanter Magnetic Slow", "magic_nairas_kiss_slow_effect", issues)
    slow_buff = _buff_row(core_zip, overlay, "DB/buffs/buffs_night_magics.json", "magic_nairas_kiss_slow_effect", issues)
    _expect_equal(_nested_value(slow_buff, ("data", "stats", "speed")), -1, "Magnetic Slow configured Speed modifier", issues)
    _expect_equal(_nested_value(slow_buff, ("data", "stats", "initiative")), -1, "Magnetic Slow configured Initiative modifier", issues)
    _validate_magnetic_slow_text(_view_description(enchanter_view, "abilities", 1, language_rows), "Enchanter Magnetic Slow", issues)

    shorten_shadow = _buff_row(core_zip, overlay, "DB/buffs/buffs_day_magics.json", "magic_shorten_shadow_effect_1", issues)
    _expect_equal(_nested_value(shorten_shadow, ("data", "stats", "offence")), -3, "Attack/Defense debuff configured Attack modifier", issues)
    _expect_equal(_nested_value(shorten_shadow, ("data", "stats", "defence")), -3, "Attack/Defense debuff configured Defense modifier", issues)
    for faction, unit_sid, label in (
        ("homm3_castle", "h3_cavalier", "Cavalier Sapping Strike"),
        ("homm3_necropolis", "h3_walking_dead", "Shambling Grasp"),
        ("homm3_necropolis", "h3_walking_dead_upg", "Zombie Clutch"),
    ):
        member = f"DB/units/units_views/{faction}/{unit_sid}_v.json"
        view, logic = unit(member)
        ability = slot_row(logic, "abilities", 0, label)
        _buff_id(ability, label, "magic_shorten_shadow_effect_1", issues)
        text = _view_description(view, "abilities", 0, language_rows)
        _expect_terms(text, ("initial", "Attack", "Defense", "3"), label, issues)
        _expect_initial_attack_defense_text(text, label, issues)

    radiant_view, radiant_logic = unit("DB/units/units_views/homm3_rampart/h3_pristine_unicorn_upg_alt_v.json")
    radiant = slot_row(radiant_logic, "abilities", 0, "Radiant Armor")
    _buff_id(radiant, "Radiant Armor", "magic_radiant_armor_effect_1", issues)
    radiant_buff = _buff_row(core_zip, overlay, "DB/buffs/buffs_day_magics.json", "magic_radiant_armor_effect_1", issues)
    radiant_fraction = _nested_value(radiant_buff, ("data", "stats", "inAllDmgMod"))
    _expect_equal(radiant_fraction, -0.25, "Radiant Armor configured incoming-damage modifier", issues)
    radiant_text = _view_description(radiant_view, "abilities", 0, language_rows)
    _expect_description_percent(radiant_text, radiant_fraction, "Radiant Armor", issues)
    if re.search(r"\breduce incoming damage to an allied stack by 25%", radiant_text or "", re.IGNORECASE) is None:
        issues.append("Radiant Armor: description does not state the configured reduction to allied incoming damage")

    taunt_view, taunt_logic = unit("DB/units/units_views/homm3_dungeon/h3_minotaur_upg_alt_v.json")
    taunt = slot_row(taunt_logic, "abilities", 0, "Earthshatter")
    _buff_id(taunt, "Earthshatter", "ent_taunt_buff", issues)
    taunt_buff = _buff_row(core_zip, overlay, "DB/buffs/units_buffs_nature.json", "ent_taunt_buff", issues)
    radius = _nested_value(taunt_buff, ("data", "stats", "tauntRadius"))
    _expect_equal(radius, 2, "Earthshatter configured taunt radius", issues)
    _expect_taunt_radius_text(_view_description(taunt_view, "abilities", 0, language_rows), radius, "Earthshatter", issues)

    goblin_view, goblin_logic = unit("DB/units/units_views/homm3_stronghold/h3_goblin_upg_v.json")
    counters = _nested_value(goblin_logic, ("stats", "numCounters"))
    _expect_equal(counters, 2, "Stronghold Goblin Alert I configured counters per round", issues)
    passive_text = " ".join(
        filter(None, (_view_description(goblin_view, "passives", index, language_rows) for index in range(len(goblin_view.get("passives", [])))))
    ) if isinstance(goblin_view, dict) and isinstance(goblin_view.get("passives"), list) else ""
    if re.search(r"counterattack.{0,30}(?:twice|2)", passive_text, re.IGNORECASE) is None:
        issues.append("Stronghold Goblin Alert I: passive text does not disclose two counterattacks per round")

    for unit_sid, expected_fraction in (("h3_behemoth", 0.4), ("h3_behemoth_upg", 0.8), ("h3_behemoth_upg_alt", 0.6)):
        member = f"DB/units/units_views/homm3_stronghold/{unit_sid}_v.json"
        view, logic = unit(member)
        passives = logic.get("passives") if isinstance(logic, dict) else None
        armor_pen = next(
            (_nested_value(row, ("data", "stats", "armorPen")) for row in passives if isinstance(row, dict) and _nested_value(row, ("data", "stats", "armorPen")) is not None),
            None,
        ) if isinstance(passives, list) else None
        _expect_equal(armor_pen, expected_fraction, f"{unit_sid} configured armor penetration", issues)
        view_passives = view.get("passives") if isinstance(view, dict) else None
        armor_name = f"{unit_sid}_passive_1_name"
        armor_text = next(
            (_view_description(view, "passives", index, language_rows) for index, row in enumerate(view_passives) if isinstance(row, dict) and row.get("name") == armor_name),
            None,
        ) if isinstance(view_passives, list) else None
        _expect_behemoth_armor_pen_text(armor_text, expected_fraction, f"{unit_sid} Armor Rend", issues)
        if armor_text is not None and re.search(r"\benemy(?:'s)?\s+Attack\b", armor_text, re.IGNORECASE):
            issues.append(f"{unit_sid} Armor Rend: description incorrectly names Attack")

    dragon_view, dragon_logic = unit("DB/units/units_views/homm3_fortress/h3_wyvern_upg_alt_v.json")
    dragon = slot_row(dragon_logic, "abilities", 0, "Dragonflight")
    _expect_equal(_nested_value(dragon, ("damageDealer", "damageTarget_")), "all", "Dragonflight configured damage target", issues)
    _expect_equal(_nested_value(dragon, ("damageDealer", "affectTargetParams", "castTarget_")), "noself", "Dragonflight configured affected target", issues)
    _expect_terms(_view_description(dragon_view, "abilities", 0, language_rows), ("all nearby creatures", "including allies"), "Dragonflight", issues)

    dragonfly_view, dragonfly_logic = unit("DB/units/units_views/homm3_fortress/h3_serpent_fly_upg_v.json")
    dispel = slot_row(dragonfly_logic, "abilities", 0, "Dragon Fly Weakening Dispel")
    _expect_equal(_nested_value(dispel, ("damageDealer", "statDmgMult")), 0.5, "Dragon Fly Weakening Dispel damage multiplier", issues)
    _expect_equal(_nested_value(dispel, ("damageDealer", "damageType_")), "normal", "Dragon Fly Weakening Dispel damage type", issues)
    _expect_terms(_view_description(dragonfly_view, "abilities", 0, language_rows), ("strike for 50% normal damage",), "Dragon Fly Weakening Dispel", issues)

    ironclad_view, ironclad_logic = unit("DB/units/units_views/homm3_factory/h3_dreadnought_upg_alt_v.json")
    ironclad = slot_row(ironclad_logic, "abilities", 0, "Ironclad Fortress Mode")
    _buff_id(ironclad, "Ironclad Fortress Mode", "magic_carapace_effect_0", issues)
    if ironclad is not None:
        _expect_equal(_nested_value(ironclad, ("damageDealer", "buff", "duration")), 1, "Ironclad Fortress Mode configured duration", issues)
    ironclad_text = _view_description(ironclad_view, "abilities", 0, language_rows) or ""
    _expect_terms(ironclad_text, ("Carapace", "barrier"), "Ironclad Fortress Mode", issues)
    if re.search(r"\b(stationary|bunker|immobile|immobilized|cannot move)\b", ironclad_text, re.IGNORECASE):
        issues.append("Ironclad Fortress Mode: description promises an unconfigured movement lock")

    fairy_view, fairy_logic = unit("DB/units/units_views/neutral/h3_faerie_dragon_v.json")
    _expect_equal(_nested_value(fairy_logic, ("stats", "moveType")), "fly", "Faerie Dragon configured move type", issues)
    fairy_passives = fairy_view.get("passives") if isinstance(fairy_view, dict) else None
    if not isinstance(fairy_passives, list) or not any(
        isinstance(row, dict) and row.get("name") == "base_passive_flyer_name" for row in fairy_passives
    ):
        issues.append("Faerie Dragon: configured flight has no standard Flying passive card")
    if isinstance(fairy_passives, list) and any(
        isinstance(row, dict) and row.get("name") == "base_passive_blink_name" for row in fairy_passives
    ):
        issues.append("Faerie Dragon: unsupported donor Blink passive card remains")

    weakness_units = {
        "h3_sea_witch": ("magic_unnatural_calm_effect_0", "homm3_cove_disrupting_ray_effect_0", 15, -3),
        "h3_sorceress": ("magic_unnatural_calm_effect_1", "homm3_cove_disrupting_ray_effect_1", 20, -4),
        "h3_sea_witch_upg_alt": ("magic_unnatural_calm_effect_0", "homm3_cove_disrupting_ray_effect_0", 15, -3),
    }
    for unit_sid, (weakness_sid, ray_sid, percent, defence_penalty) in weakness_units.items():
        member = f"DB/units/units_views/homm3_cove/{unit_sid}_v.json"
        view, logic = unit(member)
        attacks = logic.get("defaultAttacks") if isinstance(logic, dict) else None
        attack_rows = attacks if isinstance(attacks, list) else [attacks] if isinstance(attacks, dict) else []
        ranged = next((row for row in attack_rows if isinstance(row, dict) and row.get("attackType_") in {"shoot", "range"}), None)
        if ranged is None:
            issues.append(f"{unit_sid} Weakening Shot: candidate has no configured ranged default attack")
        else:
            dealer = ranged.get("damageDealer") if isinstance(ranged.get("damageDealer"), dict) else {}
            _expect_equal(_nested_value(dealer, ("buff", "sid")), weakness_sid, f"{unit_sid} Weakening Shot selected buff", issues)
            _expect_equal(_nested_value(dealer, ("buff", "duration")), 3, f"{unit_sid} Weakening Shot configured duration", issues)
            _expect_equal(dealer.get("buffTarget_"), "enemy", f"{unit_sid} Weakening Shot configured target", issues)
        weakness_buff = _buff_row(core_zip, overlay, "DB/buffs/buffs_night_magics.json", weakness_sid, issues)
        mods = _nested_value(weakness_buff, ("data", "stats", "outDmgMods", "list"))
        normal_damage = next((row.get("v") for row in mods if isinstance(row, dict) and row.get("t") == "normal_damage"), None) if isinstance(mods, list) else None
        _expect_equal(normal_damage, -percent / 100, f"{unit_sid} Weakening Shot configured normal-damage modifier", issues)
        ray_buff = _buff_row(core_zip, overlay, "DB/buffs/buffs_night_magics.json", ray_sid, issues)
        _expect_equal(_nested_value(ray_buff, ("data", "stats", "defence")), defence_penalty, f"{unit_sid} repeated Weakening Shot Defense modifier", issues)
        _expect_equal(ray_buff.get("infinite") if isinstance(ray_buff, dict) else None, True, f"{unit_sid} repeated Weakening Shot configured infinite flag", issues)
        _expect_equal(ray_buff.get("addition") if isinstance(ray_buff, dict) else None, "data", f"{unit_sid} repeated Weakening Shot configured addition mode", issues)
        passives = view.get("passives") if isinstance(view, dict) else None
        weakness_index = next((index for index, row in enumerate(passives) if isinstance(row, dict) and row.get("name") == "h3_common_passive_after_shot_weakness_name"), -1) if isinstance(passives, list) else -1
        weakness_text = _view_description(view, "passives", weakness_index, language_rows) if weakness_index >= 0 else None
        label = f"{unit_sid} Weakening Shot"
        _expect_description_percent(weakness_text, -percent / 100, label, issues)
        _expect_terms(weakness_text, ("3 rounds", "normal damage", "Disrupting Ray", "Defense reduction stacks"), label, issues)
        if re.search(rf"\breduce the target's normal damage by {percent}%", weakness_text or "", re.IGNORECASE) is None:
            issues.append(f"{label}: description does not state the configured outgoing normal-damage reduction")
        if re.search(r"\balready\s+affected by Weakness\b", weakness_text or "", re.IGNORECASE) is None:
            issues.append(f"{label}: description does not state the already-affected target condition")
        if re.search(rf"\breducing its Defense by\s+{abs(defence_penalty)}\b", weakness_text or "", re.IGNORECASE) is None:
            issues.append(f"{label}: description does not state the configured -{abs(defence_penalty)} Defense fallback")

    forbidden_tower_cards = {
        "h3_gargoyle_upg_alt": {"h3_gargoyle_upg_alt_ability_name"},
        "h3_genie": {"h3_genie_ability_2_name"},
        "h3_genie_upg": {"h3_genie_ability_2_name", "h3_genie_upg_ability_1_name"},
        "h3_genie_upg_alt": {"h3_genie_upg_alt_ability_name"},
        "h3_giant_upg": {"h3_giant_upg_ability_2_name"},
        "h3_giant_upg_alt": {"h3_giant_upg_alt_ability_name"},
        "h3_mage_upg_alt": {"h3_mage_upg_alt_ability_name"},
    }
    for unit_sid, forbidden_names in forbidden_tower_cards.items():
        member = f"DB/units/units_views/homm3_tower/{unit_sid}_v.json"
        view, _logic = unit(member)
        if not isinstance(view, dict):
            continue
        for slot in ("abilities", "passives", "alternativeAttacks"):
            rows = view.get(slot)
            if isinstance(rows, list):
                for index, row in enumerate(rows):
                    if isinstance(row, dict) and row.get("name") in forbidden_names:
                        issues.append(f"{member} {slot}[{index}] retains unsupported Tower card {row['name']}")


def run_in_memory_contract_fixtures() -> None:
    shared = "h3_common_ability_curse_description"
    conflict_source = (
        f"FIRST_LANG_ROWS = [{{'sid': {shared!r}, 'text': 'first'}}]\n"
        f"SECOND_LOCALIZATION_ROWS = [{{'sid': {shared!r}, 'text': 'second'}}]\n"
        "STRONG_VANILLA_LANG_ROWS = [{'sid': 'h3_common_ability_magnetic_slow_description', 'text': 'slow'}]\n"
    )
    source_issues = validate_shared_source_localization_rows(conflict_source)
    if not any("conflicting source definitions" in issue for issue in source_issues):
        fail("in-memory fixture did not reject a conflicting shared localization token")

    slow_ok: list[str] = []
    _validate_magnetic_slow_text("Spend 1 Focus to reduce an enemy's Speed and Initiative by 1.", "fixture", slow_ok)
    if slow_ok:
        fail("in-memory fixture rejected Magnetic Slow's configured effect wording")
    slow_issues: list[str] = []
    _validate_magnetic_slow_text("Spend 1 Focus to reduce Speed and Initiative by 2.", "fixture", slow_issues)
    if not slow_issues:
        fail("in-memory fixture did not reject Magnetic Slow's wrong configured magnitude")
    slow_direction_issues: list[str] = []
    _validate_magnetic_slow_text("Spend 1 Focus to increase an enemy's Speed and Initiative by 1.", "fixture", slow_direction_issues)
    if not slow_direction_issues:
        fail("in-memory fixture did not reject Magnetic Slow's wrong modifier direction")

    direction_issues: list[str] = []
    _expect_initial_attack_defense_text("Initially increase an enemy's Attack and Defense by 3.", "fixture", direction_issues)
    if not direction_issues:
        fail("in-memory fixture did not reject Attack/Defense text with the wrong direction")
    armor_direction_issues: list[str] = []
    _expect_behemoth_armor_pen_text("Attacks increase 40% of enemy Defense.", 0.4, "fixture", armor_direction_issues)
    if not armor_direction_issues:
        fail("in-memory fixture did not reject Armor Rend text with the wrong modifier direction")

    release_port = pathlib.Path(__file__).resolve().parent / "release_port"
    if str(release_port) not in sys.path:
        sys.path.insert(0, str(release_port))
    from multilingual_custom_lang import (  # noqa: PLC0415
        _remove_noncanonical_custom_rows,
        canonical_custom_text_files_for_sid,
        custom_unit_ability_view_sids,
    )
    import io

    fixture_member = "DB/units/units_views/homm3_fixture/h3_fixture_v.json"
    fixture_doc = {
        "array": [{"abilities": [{"name": "h3_unlisted_unit_skill_name", "description": "h3_unlisted_unit_skill_description"}]}]
    }
    fixture_bytes = json.dumps(fixture_doc).encode("utf-8")
    fixture_core = io.BytesIO()
    with zipfile.ZipFile(fixture_core, "w") as fixture_zip:
        fixture_zip.writestr(fixture_member, fixture_bytes)
        fixture_zip.writestr("placeholder", b"")
    fixture_core.seek(0)
    with zipfile.ZipFile(fixture_core) as fixture_zip:
        unit_ability_sids = custom_unit_ability_view_sids(fixture_zip, {})
    for sid in ("h3_unlisted_unit_skill_name", "h3_unlisted_unit_skill_description"):
        if canonical_custom_text_files_for_sid(sid, unit_ability_sids) != {"unitsAbility.json"}:
            fail(f"in-memory fixture did not route view-consumed SID {sid} to unitsAbility.json")
    wrong_file = {"tokens": [{"sid": "h3_unlisted_unit_skill_description", "text": "fixture"}]}
    right_file = {"tokens": [{"sid": "h3_unlisted_unit_skill_description", "text": "fixture"}]}
    if _remove_noncanonical_custom_rows(wrong_file, "units.json", unit_ability_sids) != 1 or wrong_file["tokens"]:
        fail("in-memory fixture did not scrub an arbitrary view-consumed SID from the wrong text file")
    if _remove_noncanonical_custom_rows(right_file, "unitsAbility.json", unit_ability_sids) != 0:
        fail("in-memory fixture scrubbed a view-consumed SID from its canonical text file")
    if canonical_custom_text_files_for_sid("h3_fixture_unit_title", unit_ability_sids) != {"units.json"}:
        fail("in-memory fixture changed unit-title localization ownership")

    view_issues: list[str] = []
    validate_view_ability_localization(
        "DB/units/units_views/neutral/h3_fangarm_v.json",
        "abilities",
        0,
        {"name": "h3_fangarm_hypnotic_strike_name", "description": "h3_fangarm_hypnotic_strike_description"},
        {},
        view_issues,
    )
    if sum("resolves to raw token" in issue for issue in view_issues) != 2:
        fail("in-memory fixture did not reject unresolved Fangarm name/description keys")

    coefficient_buff = {"data": {"stats": {"inAllDmgMod": -0.30}}}
    coefficient_issues: list[str] = []
    _expect_description_percent("Reduce incoming damage by 25%.", _nested_value(coefficient_buff, ("data", "stats", "inAllDmgMod")), "fixture", coefficient_issues)
    if not coefficient_issues:
        fail("in-memory fixture did not reject a description that disagrees with the packed buff coefficient")

    radius_issues: list[str] = []
    _expect_taunt_radius_text("Enemies must attack this unit until round end.", 2, "fixture", radius_issues)
    if not radius_issues:
        fail("in-memory fixture did not reject a taunt description that omits configured radius")


def candidate_members(core_zip: zipfile.ZipFile, overlay: dict[str, bytes]) -> list[str]:
    names = set(core_zip.namelist())
    names.update(overlay)
    return sorted(names)


def import_overlay_module(repo_root: pathlib.Path) -> Any:
    overlay_dir = repo_root / "tools" / "release_port"
    overlay_source = overlay_dir / "apply_release_core_overlay.py"
    if not overlay_source.is_file():
        fail(f"missing overlay source: {overlay_source}")
    if str(overlay_dir) not in sys.path:
        sys.path.insert(0, str(overlay_dir))
    import importlib.util

    spec = importlib.util.spec_from_file_location("homm3_active_ability_overlay_contract", overlay_source)
    if spec is None or spec.loader is None:
        fail(f"cannot import overlay source: {overlay_source}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def build_candidate_overlay(repo_root: pathlib.Path, core_path: pathlib.Path) -> dict[str, bytes]:
    module = import_overlay_module(repo_root)
    try:
        overlay, _notes = module.build_overlay(core_path)
    except Exception as ex:  # noqa: BLE001 - contract should fail closed with source error text.
        fail(f"cannot build candidate Core overlay in memory: {ex}")
    if not isinstance(overlay, dict):
        fail("build_overlay did not return an overlay dictionary")
    return overlay


def validate_core(repo_root: pathlib.Path, core_path: pathlib.Path) -> None:
    if not core_path.is_file():
        fail(f"missing release Core.zip for candidate build: {core_path}")
    issues: list[str] = []
    checked = 0
    overlay = build_candidate_overlay(repo_root, core_path)
    with zipfile.ZipFile(core_path) as core_zip:
        lang_doc = read_json_member(core_zip, overlay, "Lang/english/texts/unitsAbility.json")
        if not isinstance(lang_doc, dict):
            fail("candidate unitsAbility.json must be a JSON object")
        language_rows: dict[str, str] = {}
        for key in ("tokens", "array"):
            values = lang_doc.get(key)
            if not isinstance(values, list):
                continue
            for row in values:
                if not isinstance(row, dict):
                    continue
                sid = row.get("sid")
                text = row.get("text")
                if isinstance(sid, str) and isinstance(text, str):
                    language_rows[sid] = text
        unit_rows: dict[str, tuple[str, dict[str, Any], dict[str, Any] | None]] = {}
        for member in candidate_members(core_zip, overlay):
            match = CUSTOM_VIEW_PATH.match(member)
            if not match:
                continue
            _faction_sid, _unit_file_sid = match.groups()
            doc = read_json_member(core_zip, overlay, member)
            item = first_array_item(doc)
            if item is None:
                continue
            logic_item: dict[str, Any] | None = None
            logic_doc = read_json_member_or_none(core_zip, overlay, logic_member_for_view(member))
            if logic_doc is not None:
                logic_item = first_array_item(logic_doc)
            logic_abilities = logic_item.get("abilities") if isinstance(logic_item, dict) else []
            if not isinstance(logic_abilities, list):
                logic_abilities = []
            unit_rows[member] = (logic_member_for_view(member), item, logic_item)
            for slot_name in ("abilities", "passives", "alternativeAttacks"):
                rows = item.get(slot_name)
                if not isinstance(rows, list):
                    continue
                for index, ability in enumerate(rows):
                    if not isinstance(ability, dict):
                        continue
                    checked += 1
                    _name, description = validate_view_ability_localization(
                        member, slot_name, index, ability, language_rows, issues
                    )
                    if slot_name == "abilities" and description is not None:
                        logic_ability = logic_abilities[index] if index < len(logic_abilities) and isinstance(logic_abilities[index], dict) else None
                        validate_active_description_contract(member, index, description, logic_ability, issues)
        validate_audited_effect_contracts(core_zip, overlay, unit_rows, language_rows, issues)
    if checked == 0:
        fail("no custom unit ability rows were checked")
    if issues:
        for issue in issues[:80]:
            print(issue, file=sys.stderr)
        if len(issues) > 80:
            print(f"... {len(issues) - 80} more", file=sys.stderr)
        fail(f"custom unit ability localization has {len(issues)} issue(s)")
    print(f"custom unit ability localization passed: unit_views={len(unit_rows)} cards={checked}")


def validate_overlay_call(overlay_source: pathlib.Path) -> None:
    source = overlay_source.read_text(encoding="utf-8-sig")
    if "def add_custom_active_ability_localization_rows" not in source:
        fail("missing add_custom_active_ability_localization_rows")
    if "add_custom_active_ability_localization_rows(release_zip, output, notes)" not in source:
        fail("build_overlay must apply the custom active ability localization cleanup rows")
    if source.find("apply_custom_ability_overrides_to_custom_unit_rows(release_zip, output, notes)") > source.find(
        "add_custom_active_ability_localization_rows(release_zip, output, notes)"
    ):
        fail("localization cleanup must run after custom ability override generation")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=pathlib.Path, default=pathlib.Path(__file__).resolve().parents[1])
    parser.add_argument("--core-zip", type=pathlib.Path, default=None)
    parser.add_argument("--run-fixtures", action="store_true")
    args = parser.parse_args()

    repo_root = args.repo_root.resolve()
    overlay_source = repo_root / "tools" / "release_port" / "apply_release_core_overlay.py"
    core_path = args.core_zip.resolve() if args.core_zip else repo_root / "artifacts" / "core_overlay_work" / "Core.zip"
    if not overlay_source.is_file():
        fail(f"missing overlay source: {overlay_source}")
    source_issues = validate_shared_source_localization_rows(overlay_source.read_text(encoding="utf-8-sig"))
    if source_issues:
        for issue in source_issues:
            print(issue, file=sys.stderr)
        fail(f"shared source localization has {len(source_issues)} issue(s)")
    validate_overlay_call(overlay_source)
    extract_cleanup_rows(overlay_source)
    if args.run_fixtures:
        run_in_memory_contract_fixtures()
    validate_core(repo_root, core_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
