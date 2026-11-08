#!/usr/bin/env python3
"""Validate the HoMM3 Conflux Elemental Conjury Attack and Spell Power contract."""

from __future__ import annotations

import argparse
import importlib.util
import json
import pathlib
import sys
import zipfile
from typing import Any

CONFLUX_FACTION = "homm3_conflux"
CONFLUX_SKILL = "skill_faction_homm3_conflux"
ARCANE_CONDUIT = "sub_skill_faction_homm3_conflux_elemental_conjury_spell_power"
GREATER_CONJURY = "sub_skill_faction_homm3_conflux_elemental_conjury_expert_spell_tier"
STALE_SUMMON_ELEMENTALS_SUBSKILL_PREFIX = "sub_skill_faction_homm3_conflux_summon_elementals_"
EXPECTED_ELEMENTAL_LINE_RECEIVERS = (
    "h3_air_elemental",
    "h3_air_elemental_upg",
    "h3_air_elemental_upg_alt",
    "h3_water_elemental",
    "h3_water_elemental_upg",
    "h3_water_elemental_upg_alt",
    "h3_fire_elemental",
    "h3_fire_elemental_upg",
    "h3_fire_elemental_upg_alt",
    "h3_earth_elemental",
    "h3_earth_elemental_upg",
    "h3_earth_elemental_upg_alt",
    "h3_psychic_elemental",
    "h3_psychic_elemental_upg",
    "h3_psychic_elemental_upg_alt",
)
EXPECTED_FOCUS_SPELL_RECEIVERS = (
    "h3_air_elemental_upg",
    "h3_air_elemental_upg_alt",
    "h3_fire_elemental_upg",
    "h3_fire_elemental_upg_alt",
    "h3_earth_elemental_upg",
    "h3_earth_elemental_upg_alt",
)

def fail(message: str) -> None:
    print(f"homm3-conflux-focus-attack-spell-power-contract: {message}", file=sys.stderr)
    raise SystemExit(1)


def import_overlay(repo_root: pathlib.Path) -> Any:
    overlay_dir = repo_root / "tools" / "release_port"
    overlay_path = overlay_dir / "apply_release_core_overlay.py"
    if str(overlay_dir) not in sys.path:
        sys.path.insert(0, str(overlay_dir))
    spec = importlib.util.spec_from_file_location("homm3_conflux_focus_overlay", overlay_path)
    if spec is None or spec.loader is None:
        fail(f"cannot import {overlay_path}")
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as ex:  # noqa: BLE001 - validators should fail closed with source context.
        fail(f"cannot import overlay module: {ex}")
    return module


def read_json(core_zip: zipfile.ZipFile, overlay: dict[str, bytes], member: str) -> Any:
    try:
        raw = overlay[member] if member in overlay else core_zip.read(member)
    except KeyError:
        fail(f"candidate Core output is missing {member}")
    return json.loads(raw.decode("utf-8-sig"))


def first_array_item(doc: Any, member: str) -> dict[str, Any]:
    if isinstance(doc, dict) and isinstance(doc.get("array"), list) and doc["array"]:
        item = doc["array"][0]
        if isinstance(item, dict):
            return item
    fail(f"malformed generated Core row: {member}")


def row_by_id(rows: list[Any], row_id: str, member: str) -> dict[str, Any]:
    for row in rows:
        if isinstance(row, dict) and row.get("id") == row_id:
            return row
    fail(f"{member}: missing row id {row_id}")


def array_rows(doc: Any, member: str) -> list[Any]:
    rows = doc.get("array") if isinstance(doc, dict) else None
    if isinstance(rows, list):
        return rows
    fail(f"{member}: missing array rows")


def bonus_with_params(bonuses: Any, bonus_type: str, params: list[str]) -> dict[str, Any] | None:
    if not isinstance(bonuses, list):
        return None
    for bonus in bonuses:
        if isinstance(bonus, dict) and bonus.get("type") == bonus_type and bonus.get("parameters") == params:
            return bonus
    return None


def validate_receiver_bonus(
    bonuses: Any,
    expected_receivers: list[str],
    params: list[str],
    label: str,
    issues: list[str],
) -> None:
    bonus = bonus_with_params(bonuses, "unitStat", params)
    if bonus is None:
        issues.append(f"{label}: missing unitStat {params!r}")
        return
    receivers = bonus.get("receivers")
    if receivers != expected_receivers:
        issues.append(f"{label}: receivers={receivers!r}, expected {expected_receivers!r}")


def validate_hero_focus_bonus(bonuses: Any, amount: str, label: str, issues: list[str]) -> None:
    if bonus_with_params(bonuses, "heroStat", ["startEnergyLevelsBonus", amount]) is None:
        issues.append(f"{label}: missing startEnergyLevelsBonus {amount}")


def validate_skill_row(skill_row: dict[str, Any], elemental_lines: list[str], focus_receivers: list[str], issues: list[str]) -> None:
    levels = skill_row.get("parametersPerLevel")
    if not isinstance(levels, list) or len(levels) != 3:
        issues.append(f"{CONFLUX_SKILL}: expected exactly 3 parametersPerLevel rows")
        return
    for index, amount in enumerate(("1", "2", "3"), start=1):
        level = levels[index - 1]
        bonuses = level.get("bonuses") if isinstance(level, dict) else None
        validate_hero_focus_bonus(bonuses, amount, f"{CONFLUX_SKILL}:level{index}", issues)
        validate_receiver_bonus(
            bonuses,
            elemental_lines,
            ["heroOffenceModifier", "0.50"],
            f"{CONFLUX_SKILL}:level{index}",
            issues,
        )
        validate_receiver_bonus(
            bonuses,
            elemental_lines,
            ["heroSpellPowerModifier", "0.50"],
            f"{CONFLUX_SKILL}:level{index}",
            issues,
        )
    level2_subskills = levels[1].get("subSkills") if isinstance(levels[1], dict) else None
    level3_subskills = levels[2].get("subSkills") if isinstance(levels[2], dict) else None
    if ARCANE_CONDUIT not in (level2_subskills or []):
        issues.append(f"{CONFLUX_SKILL}:level2 missing {ARCANE_CONDUIT}")
    if GREATER_CONJURY not in (level3_subskills or []):
        issues.append(f"{CONFLUX_SKILL}:level3 missing {GREATER_CONJURY}")
    focus_set = set(focus_receivers)
    if not focus_set.issubset(set(elemental_lines)):
        issues.append(f"{CONFLUX_SKILL}: focus receivers outside elemental-lines set: {sorted(focus_set - set(elemental_lines))!r}")


def validate_subskills(subskill_rows: list[Any], elemental_lines: list[str], focus_receivers: list[str], issues: list[str]) -> None:
    for row in subskill_rows:
        if not isinstance(row, dict):
            continue
        sid = row.get("id")
        if isinstance(sid, str) and sid.startswith(STALE_SUMMON_ELEMENTALS_SUBSKILL_PREFIX):
            issues.append(f"stale Summon Elementals subskill still present in Core overlay: {sid}")
    arcane = row_by_id(subskill_rows, ARCANE_CONDUIT, "DB/heroes_skills/sub_skills/sub_skills.json")
    validate_receiver_bonus(
        arcane.get("bonuses"),
        elemental_lines,
        ["heroOffenceModifier", "0.50"],
        ARCANE_CONDUIT,
        issues,
    )
    validate_receiver_bonus(
        arcane.get("bonuses"),
        elemental_lines,
        ["heroSpellPowerModifier", "0.50"],
        ARCANE_CONDUIT,
        issues,
    )
    greater = row_by_id(subskill_rows, GREATER_CONJURY, "DB/heroes_skills/sub_skills/sub_skills.json")
    validate_receiver_bonus(
        greater.get("bonuses"),
        focus_receivers,
        ["finalAbilityDamageBonusPercent", "1.0"],
        GREATER_CONJURY,
        issues,
    )



def spell_focus_receivers(core_zip: zipfile.ZipFile, overlay: dict[str, bytes], unit_sids: list[str], issues: list[str]) -> list[str]:
    result: list[str] = []
    for sid in unit_sids:
        logic_member = f"DB/units/units_logics/{CONFLUX_FACTION}/{sid}_l.json"
        view_member = f"DB/units/units_views/{CONFLUX_FACTION}/{sid}_v.json"
        logic = first_array_item(read_json(core_zip, overlay, logic_member), logic_member)
        view = first_array_item(read_json(core_zip, overlay, view_member), view_member)
        logic_abilities = logic.get("abilities")
        view_abilities = view.get("abilities")
        if not isinstance(logic_abilities, list):
            logic_abilities = []
        if not isinstance(view_abilities, list):
            view_abilities = []
        for index, ability in enumerate(logic_abilities):
            if not isinstance(ability, dict):
                continue
            selection = ability.get("xHomm3SpellEffectSelection")
            if not isinstance(selection, dict):
                continue
            if sid not in result:
                result.append(sid)
            if ability.get("energyLevel", 0) <= 0:
                issues.append(f"{sid}: spell-effect Focus action {index} has no positive energyLevel")
            if selection.get("effectiveSpellPower") is not None:
                issues.append(f"{sid}: spell-effect Focus action {index} hardcodes effectiveSpellPower instead of inheriting heroSpellPowerModifier")
            marker = ability.get("xHomm3AbilityOverride")
            source_key = marker.get("sourceSpellEffectKey") if isinstance(marker, dict) else None
            if not isinstance(marker, dict) or not isinstance(source_key, str):
                issues.append(f"{sid}: spell-effect Focus action {index} is missing sourceSpellEffectKey marker")
            if index >= len(view_abilities) or not isinstance(view_abilities[index], dict):
                issues.append(f"{sid}: spell-effect Focus action {index} has no matching view ability")
                continue
            view_ability = view_abilities[index]
            view_selection = view_ability.get("xHomm3SpellEffectSelection")
            if view_selection != selection:
                issues.append(f"{sid}: view spell-effect selection {view_selection!r} does not match logic {selection!r}")
    return result


def validate_language_rows(lang_rows: list[Any], issues: list[str]) -> None:
    text_by_sid = {row.get("sid"): row.get("text") for row in lang_rows if isinstance(row, dict)}
    checks = {
        "skill_faction_homm3_conflux_desc": ("Attack", "Spell Power", "Focus"),
        "skill_faction_homm3_conflux_desc_1": ("50%", "Attack", "Spell Power"),
        "skill_faction_homm3_conflux_desc_2": ("50%", "Attack", "Spell Power"),
        "skill_faction_homm3_conflux_desc_3": ("50%", "Attack", "Spell Power", "elemental", "Phoenix", "Knowledge"),
        "sub_skill_faction_homm3_conflux_elemental_conjury_spell_power_desc": ("100%", "Attack", "Spell Power"),
        "sub_skill_faction_homm3_conflux_elemental_conjury_expert_spell_tier_desc": ("Elemental Focus abilities", "100%"),
    }
    for sid, required in checks.items():
        text = text_by_sid.get(sid)
        if not isinstance(text, str):
            issues.append(f"heroSkills localization missing {sid}")
            continue
        lowered = text.lower()
        for token in required:
            if token.lower() not in lowered:
                issues.append(f"{sid}: text {text!r} missing {token!r}")


def validate_source_shape(repo_root: pathlib.Path, issues: list[str]) -> None:
    source = (repo_root / "tools" / "release_port" / "apply_release_core_overlay.py").read_text(encoding="utf-8-sig")
    required = [
        "HOMM3_CONFLUX_ELEMENTAL_FOCUS_SPELL_RECEIVERS",
        "HOMM3_CONFLUX_ELEMENTAL_CONJURY_SUBSKILLS_BY_LEVEL",
        "HOMM3_CONFLUX_ELEMENTAL_CONJURY_STALE_SUBSKILL_IDS",
        'unit_stat_bonus(elemental_lines, "heroOffenceModifier", "0.50")',
        'unit_stat_bonus(elemental_lines, "heroSpellPowerModifier", "0.50")',
        'unit_stat_bonus(spell_units, "finalAbilityDamageBonusPercent", "1.0")',
        "Elemental-line Focus abilities apply 50% of hero Attack and 50% of hero Spell Power.",
        "Arcane Conduit raises both to 100%.",
        "elemental and Phoenix-line creatures gain 15% of hero Knowledge as extra power.",
        "sub_skill_faction_homm3_conflux_elemental_conjury_spell_power",
        "sub_skill_faction_homm3_conflux_elemental_conjury_expert_spell_tier",
    ]
    for snippet in required:
        if snippet not in source:
            issues.append(f"overlay source is missing Conflux Attack/Spell Power contract snippet: {snippet}")
    if "HOMM3_CONFLUX_SUMMON_ELEMENTALS_SUBSKILLS_BY_LEVEL" in source:
        issues.append("overlay source still defines HOMM3_CONFLUX_SUMMON_ELEMENTALS_SUBSKILLS_BY_LEVEL")
    if "make_homm3_conflux_summon_elementals_subskills" in source:
        issues.append("overlay source still defines make_homm3_conflux_summon_elementals_subskills")
    # Active (non-stale) rows must not keep the old summon_elementals SID token.
    for line in source.splitlines():
        stripped = line.strip()
        if "summon_elementals" not in stripped:
            continue
        if stripped.startswith("#"):
            continue
        if "HOMM3_CONFLUX_ELEMENTAL_CONJURY_STALE_" in stripped:
            continue
        if '"sub_skill_faction_homm3_conflux_summon_elementals_' in stripped:
            # Allowed only inside the stale-ID set values.
            continue
        if "Former Summon Elementals" in stripped:
            continue
        if "Renamed from Summon Elementals" in stripped:
            continue
        issues.append(f"overlay source still uses summon_elementals outside stale-ID quarantine: {stripped}")


def validate_generated_receiver_sets(generated_elemental_lines: list[str], generated_focus_receivers: list[str], issues: list[str]) -> None:
    expected_elemental_lines = list(EXPECTED_ELEMENTAL_LINE_RECEIVERS)
    expected_focus_receivers = list(EXPECTED_FOCUS_SPELL_RECEIVERS)
    if generated_elemental_lines != expected_elemental_lines:
        issues.append(f"generated elemental-line receivers={generated_elemental_lines!r}, expected {expected_elemental_lines!r}")
    if generated_focus_receivers != expected_focus_receivers:
        issues.append(f"generated spell-effect Focus receivers={generated_focus_receivers!r}, expected {expected_focus_receivers!r}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=pathlib.Path, required=True)
    parser.add_argument("--core", type=pathlib.Path, required=True)
    args = parser.parse_args()

    repo_root = args.repo_root.resolve()
    core_path = args.core.resolve()
    if not core_path.is_file():
        fail(f"missing source Core.zip: {core_path}")

    module = import_overlay(repo_root)
    manifest = module.load_custom_faction_manifest(CONFLUX_FACTION)
    generated_elemental_lines = (
        module.manifest_line_receivers(manifest, 2)
        + module.manifest_line_receivers(manifest, 3)
        + module.manifest_line_receivers(manifest, 4)
        + module.manifest_line_receivers(manifest, 5)
        + module.manifest_line_receivers(manifest, 6)
    )
    generated_focus_receivers = list(module.HOMM3_CONFLUX_ELEMENTAL_FOCUS_SPELL_RECEIVERS)
    elemental_lines = list(EXPECTED_ELEMENTAL_LINE_RECEIVERS)
    focus_receivers = list(EXPECTED_FOCUS_SPELL_RECEIVERS)
    unit_sids = list(module.manifest_unit_sids(manifest))
    issues: list[str] = []
    validate_source_shape(repo_root, issues)
    validate_generated_receiver_sets(generated_elemental_lines, generated_focus_receivers, issues)
    try:
        overlay, _notes = module.build_overlay(core_path)
    except Exception as ex:  # noqa: BLE001
        fail(f"cannot build candidate Core overlay in memory: {ex}")
    with zipfile.ZipFile(core_path) as core_zip:
        skills_doc = read_json(core_zip, overlay, "DB/heroes_skills/skills/skills.json")
        skill_row = row_by_id(array_rows(skills_doc, "DB/heroes_skills/skills/skills.json"), CONFLUX_SKILL, "DB/heroes_skills/skills/skills.json")
        validate_skill_row(skill_row, elemental_lines, focus_receivers, issues)
        subskills_doc = read_json(core_zip, overlay, "DB/heroes_skills/sub_skills/sub_skills.json")
        validate_subskills(array_rows(subskills_doc, "DB/heroes_skills/sub_skills/sub_skills.json"), elemental_lines, focus_receivers, issues)
        actual_focus_receivers = spell_focus_receivers(core_zip, overlay, unit_sids, issues)
        if actual_focus_receivers != focus_receivers:
            issues.append(f"spell-effect Focus receivers={actual_focus_receivers!r}, expected {focus_receivers!r}")
        lang_doc = read_json(core_zip, overlay, "Lang/english/texts/heroSkills.json")
        validate_language_rows(array_rows(lang_doc, "Lang/english/texts/heroSkills.json"), issues)
    if issues:
        for issue in issues[:100]:
            print(issue, file=sys.stderr)
        if len(issues) > 100:
            print(f"... {len(issues) - 100} more", file=sys.stderr)
        fail(f"Conflux focus Attack and Spell Power contract has {len(issues)} issue(s)")
    print(
        "homm3-conflux-focus-attack-spell-power-contract: "
        f"validated {len(elemental_lines)} elemental-line receivers, {len(focus_receivers)} spell-effect Focus receivers, "
        "50% Attack/Spell Power faction-skill inheritance, Arcane Conduit 100% Attack/Spell Power inheritance, and Greater Conjury focus damage bonus rows"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
