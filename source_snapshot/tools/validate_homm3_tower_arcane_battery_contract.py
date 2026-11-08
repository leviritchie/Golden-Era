#!/usr/bin/env python3
"""Validate Tower Arcane Battery Core contract against an installed Core.zip."""

from __future__ import annotations

import argparse
import json
import sys
import zipfile
from typing import Any

TOWER_FACTION = "homm3_tower"
TOWER_SKILL = "skill_faction_homm3_tower"
ARCANE_BATTERY_ABILITY = "skill_faction_homm3_tower_ability_arcane_battery"
CHRONOMANCY_SUBSKILL = "sub_skill_faction_homm3_tower_arcane_battery_chronomancy"
CHRONOMANCY_HASTE_MAGIC_SID = "day_3_magic_haste"
CHRONOMANCY_SLOW_MAGIC_SID = "night_2_magic_web"
CHRONOMANCY_MANA_DISCOUNT = "-2"
BORROWED_TIME_ABILITY = "skill_faction_homm3_tower_ability_borrowed_time"
BORROWED_TIME_BUFF = "skill_faction_homm3_tower_ability_borrowed_time_effect"
BORROWED_TIME_BUFFS_PATH = "DB/buffs/sub_skills_battle_hero_ability_buffs.json"
BORROWED_TIME_END_TRIGGERS = {"unit_wait", "unit_skip", "unit_end_move", "unit_cast_ability"}
EXPECTED_ARCANE_BATTERY_FOCUS_BY_RANK = (2, 1, 0)
EXPECTED_SUBSKILLS = {
    "sub_skill_faction_homm3_tower_arcane_battery_arcane_curriculum",
    CHRONOMANCY_SUBSKILL,
    "sub_skill_faction_homm3_tower_arcane_battery_mana_well_aegis",
    "sub_skill_faction_homm3_tower_arcane_battery_remote_library",
    "sub_skill_faction_homm3_tower_arcane_battery_spell_economies",
    "sub_skill_faction_homm3_tower_arcane_battery_focused_study",
}
STALE_BOTTOMLESS_SUBSKILL_PREFIXES = (
    "sub_skill_faction_homm3_tower_arcane_curriculum",
    "sub_skill_faction_homm3_tower_arcane_battery_deep_reservoirs",
    "sub_skill_faction_homm3_tower_deep_reservoirs",
    "sub_skill_faction_homm3_tower_mana_well_aegis",
    "sub_skill_faction_homm3_tower_remote_library",
    "sub_skill_faction_homm3_tower_spell_economies",
    "sub_skill_faction_homm3_tower_focused_study",
)


def fail(message: str) -> None:
    print(f"homm3-tower-arcane-battery-contract: {message}", file=sys.stderr)
    raise SystemExit(1)


def read_json(zf: zipfile.ZipFile, name: str) -> Any:
    return json.loads(zf.read(name).decode("utf-8-sig"))


def row_by_id(rows: list[Any], sid: str, source: str) -> dict[str, Any]:
    for row in rows:
        if isinstance(row, dict) and row.get("id") == sid:
            return row
    fail(f"missing row {sid} in {source}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--core", required=True, help="Path to installed Core.zip")
    args = parser.parse_args()

    with zipfile.ZipFile(args.core) as zf:
        skills = read_json(zf, "DB/heroes_skills/skills/skills.json")
        subskills = read_json(zf, "DB/heroes_skills/sub_skills/sub_skills.json")
        abilities = read_json(zf, "DB/heroes_abilities/heroes_abilities_base/hero_abilities.json")
        lang = read_json(zf, "Lang/english/texts/heroSkills.json")
        borrowed_buffs = read_json(zf, BORROWED_TIME_BUFFS_PATH)
        buff_lang = read_json(zf, "Lang/english/texts/magic_buff.json")

    skill_rows = skills.get("array") if isinstance(skills, dict) else skills
    subskill_rows = subskills.get("array") if isinstance(subskills, dict) else subskills
    ability_rows = abilities.get("array") if isinstance(abilities, dict) else abilities
    if not isinstance(skill_rows, list) or not isinstance(subskill_rows, list) or not isinstance(ability_rows, list):
        fail("malformed Core skill/subskill/ability arrays")

    skill = row_by_id(skill_rows, TOWER_SKILL, "skills.json")
    levels = skill.get("parametersPerLevel")
    if not isinstance(levels, list) or len(levels) != 3:
        fail(f"{TOWER_SKILL} must have exactly 3 parametersPerLevel rows")

    for index, level in enumerate(levels):
        if not isinstance(level, dict):
            fail(f"{TOWER_SKILL} level {index + 1} is malformed")
        bonuses = level.get("bonuses")
        if not isinstance(bonuses, list) or not bonuses:
            fail(f"{TOWER_SKILL} level {index + 1} missing bonuses")
        expected = {"type": "heroBattleAbility", "parameters": [ARCANE_BATTERY_ABILITY, str(index)]}
        if expected not in bonuses:
            fail(f"{TOWER_SKILL} level {index + 1} missing heroBattleAbility {ARCANE_BATTERY_ABILITY}/{index}")
        for bonus in bonuses:
            if isinstance(bonus, dict) and bonus.get("type") == "heroStat":
                params = bonus.get("parameters") or []
                if params and params[0] == "manaRestoreBonusPercent":
                    fail(f"{TOWER_SKILL} still has Bottomless Knowledge manaRestoreBonusPercent at level {index + 1}")

    expected_by_level = {
        2: (
            "sub_skill_faction_homm3_tower_arcane_battery_arcane_curriculum",
            CHRONOMANCY_SUBSKILL,
            "sub_skill_faction_homm3_tower_arcane_battery_mana_well_aegis",
        ),
        3: (
            "sub_skill_faction_homm3_tower_arcane_battery_remote_library",
            "sub_skill_faction_homm3_tower_arcane_battery_spell_economies",
            "sub_skill_faction_homm3_tower_arcane_battery_focused_study",
        ),
    }
    for level_index, expected_subs in expected_by_level.items():
        observed = levels[level_index - 1].get("subSkills") or []
        if set(observed) != set(expected_subs):
            fail(f"{TOWER_SKILL} level {level_index} subSkills={observed!r} expected={list(expected_subs)!r}")

    for sid in EXPECTED_SUBSKILLS:
        row_by_id(subskill_rows, sid, "sub_skills.json")

    chronomancy = row_by_id(subskill_rows, CHRONOMANCY_SUBSKILL, "sub_skills.json")
    chronomancy_bonuses = chronomancy.get("bonuses") or []
    expected_magic_additions = {
        (CHRONOMANCY_HASTE_MAGIC_SID, "false"),
        (CHRONOMANCY_SLOW_MAGIC_SID, "false"),
    }
    observed_magic_additions = {
        tuple(b.get("parameters") or [])
        for b in chronomancy_bonuses
        if isinstance(b, dict) and b.get("type") == "heroMagicAddition"
    }
    if observed_magic_additions != expected_magic_additions:
        fail(
            f"{CHRONOMANCY_SUBSKILL} heroMagicAddition rows must grant "
            f"{sorted(expected_magic_additions)!r}, found {sorted(observed_magic_additions)!r}"
        )
    expected_cost_rows = {
        ("magicCostSidSet", CHRONOMANCY_HASTE_MAGIC_SID, CHRONOMANCY_MANA_DISCOUNT, "0"),
        ("magicCostSidSet", CHRONOMANCY_SLOW_MAGIC_SID, CHRONOMANCY_MANA_DISCOUNT, "0"),
    }
    observed_cost_rows = {
        tuple(b.get("parameters") or [])
        for b in chronomancy_bonuses
        if isinstance(b, dict)
        and b.get("type") == "heroStat"
        and (b.get("parameters") or [None])[0] == "magicCostSidSet"
    }
    if observed_cost_rows != expected_cost_rows:
        fail(
            f"{CHRONOMANCY_SUBSKILL} magicCostSidSet rows must be "
            f"{sorted(expected_cost_rows)!r}, found {sorted(observed_cost_rows)!r}"
        )

    expected_borrowed_grant = {"type": "heroBattleAbility", "parameters": [BORROWED_TIME_ABILITY, "0"]}
    if expected_borrowed_grant not in chronomancy_bonuses:
        fail(f"{CHRONOMANCY_SUBSKILL} must grant heroBattleAbility {BORROWED_TIME_ABILITY}/0")
    borrowed = row_by_id(ability_rows, BORROWED_TIME_ABILITY, "hero_abilities.json")
    borrowed_levels = borrowed.get("levels") or []
    if len(borrowed_levels) != 1 or not isinstance(borrowed_levels[0], dict):
        fail(f"{BORROWED_TIME_ABILITY} must have exactly one level")
    bt = borrowed_levels[0]
    if bt.get("energyLevel") != 2 or bt.get("cd") != 3:
        fail(f"{BORROWED_TIME_ABILITY} must cost 2 Focus with cd 3, found energyLevel={bt.get('energyLevel')!r} cd={bt.get('cd')!r}")
    bt_dealer = bt.get("damageDealer") or {}
    if (bt_dealer.get("castTargetParams") or {}).get("castTarget_") != "ally" or bt_dealer.get("buffTarget_") != "ally":
        fail(f"{BORROWED_TIME_ABILITY} must target a friendly stack")
    if (bt_dealer.get("buff") or {}) != {"sid": BORROWED_TIME_BUFF, "duration": 1}:
        fail(f"{BORROWED_TIME_ABILITY} must apply {BORROWED_TIME_BUFF} for duration 1")
    buff_rows = borrowed_buffs.get("array") if isinstance(borrowed_buffs, dict) else None
    if not isinstance(buff_rows, list):
        fail(f"malformed {BORROWED_TIME_BUFFS_PATH}")
    buff = row_by_id(buff_rows, BORROWED_TIME_BUFF, BORROWED_TIME_BUFFS_PATH)
    if buff.get("maxDuration") != 1 or buff.get("infinite"):
        fail(f"{BORROWED_TIME_BUFF} must be a finite maxDuration=1 buff")
    initiative = ((buff.get("data") or {}).get("stats") or {}).get("initiative")
    if not isinstance(initiative, int) or initiative < 50:
        fail(f"{BORROWED_TIME_BUFF} must grant a large Initiative bonus, found {initiative!r}")
    end_triggers = {
        m.get("trigger")
        for m in buff.get("mechanics") or []
        if isinstance(m, dict) and m.get("mech") == "zero_duration_on_damage" and m.get("values") == ["self"]
    }
    if end_triggers != BORROWED_TIME_END_TRIGGERS:
        fail(f"{BORROWED_TIME_BUFF} own-turn dispel triggers must be {sorted(BORROWED_TIME_END_TRIGGERS)!r}, found {sorted(t for t in end_triggers if t)!r}")

    stale_exact = set(STALE_BOTTOMLESS_SUBSKILL_PREFIXES)
    for row in subskill_rows:
        if not isinstance(row, dict):
            continue
        sid = row.get("id")
        if isinstance(sid, str) and sid in stale_exact:
            fail(f"stale Bottomless Knowledge subskill still present in Core: {sid}")

    ability = row_by_id(ability_rows, ARCANE_BATTERY_ABILITY, "hero_abilities.json")
    ability_levels = ability.get("levels")
    if not isinstance(ability_levels, list) or len(ability_levels) < len(EXPECTED_ARCANE_BATTERY_FOCUS_BY_RANK):
        fail(f"{ARCANE_BATTERY_ABILITY} missing levels")
    for index, expected_focus in enumerate(EXPECTED_ARCANE_BATTERY_FOCUS_BY_RANK):
        level = ability_levels[index]
        if not isinstance(level, dict):
            fail(f"{ARCANE_BATTERY_ABILITY} level {index} malformed")
        if level.get("energyLevel") != expected_focus:
            fail(
                f"{ARCANE_BATTERY_ABILITY} level {index} energyLevel must be {expected_focus}, "
                f"found {level.get('energyLevel')!r}"
            )
    level0 = ability_levels[0]
    if level0.get("cd") != 1:
        fail(f"{ARCANE_BATTERY_ABILITY} cd must be 1")
    dealer = level0.get("damageDealer") or {}
    mechs = dealer.get("targetMechanics") or []
    if not any(isinstance(m, dict) and m.get("mech") == "refresh_spell_book" for m in mechs):
        fail(f"{ARCANE_BATTERY_ABILITY} must include native refresh_spell_book")

    tokens = lang.get("tokens") if isinstance(lang, dict) else None
    if not isinstance(tokens, list):
        fail("malformed english heroSkills lang tokens")
    by_sid = {row.get("sid"): row.get("text") for row in tokens if isinstance(row, dict)}
    name = by_sid.get(f"{TOWER_SKILL}_name")
    if name != "Arcane Battery":
        fail(f"{TOWER_SKILL}_name must be 'Arcane Battery', found {name!r}")
    ability_name = by_sid.get(f"{ARCANE_BATTERY_ABILITY}_name")
    if ability_name != "Arcane Battery":
        fail(f"{ARCANE_BATTERY_ABILITY}_name must be 'Arcane Battery', found {ability_name!r}")
    expected_ability_desc = "Once per round, refresh spellbook use this round."
    ability_desc = by_sid.get(f"{ARCANE_BATTERY_ABILITY}_description") or ""
    if ability_desc != expected_ability_desc:
        fail(f"{ARCANE_BATTERY_ABILITY}_description must be {expected_ability_desc!r}, found {ability_desc!r}")
    expected_rank_descs = (
        "Spend 2 Focus once per round to refresh spellbook use this round. "
        "At Advanced, pick Chronomancy to gain Borrowed Time (+100 Initiative to a friendly stack).",
        "Spend 1 Focus once per round to refresh spellbook use this round. "
        "Pick Chronomancy to gain Borrowed Time (+100 Initiative to a friendly stack).",
        "Spend 0 Focus once per round to refresh spellbook use this round.",
    )
    for index, expected_rank_desc in enumerate(expected_rank_descs, start=1):
        rank_desc = by_sid.get(f"{TOWER_SKILL}_desc_{index}") or ""
        if rank_desc != expected_rank_desc:
            fail(f"{TOWER_SKILL}_desc_{index} must be {expected_rank_desc!r}, found {rank_desc!r}")
    skill_desc = by_sid.get(f"{TOWER_SKILL}_desc") or ""
    if "Bottomless Knowledge" in skill_desc:
        fail(f"{TOWER_SKILL}_desc still mentions Bottomless Knowledge")
    forbidden_cd_claims = (
        "clear all of your spell cooldowns",
        "clear all of their spell cooldowns",
        "per-spell cooldown",
        "all of your spell cooldowns",
        "all of their spell cooldowns",
    )
    for claim in forbidden_cd_claims:
        if claim in ability_desc.lower() or claim in skill_desc.lower():
            fail(f"Arcane Battery player text must not claim per-spell CD wipe ({claim!r})")

    for sid in (f"{BORROWED_TIME_ABILITY}_name", f"{BORROWED_TIME_ABILITY}_description"):
        if not by_sid.get(sid):
            fail(f"missing english heroSkills text {sid}")
    buff_tokens = buff_lang.get("tokens") if isinstance(buff_lang, dict) else None
    buff_by_sid = {r.get("sid"): r.get("text") for r in buff_tokens or [] if isinstance(r, dict)}
    for sid in (f"{BORROWED_TIME_BUFF}_name", f"{BORROWED_TIME_BUFF}_description"):
        if not buff_by_sid.get(sid):
            fail(f"missing english magic_buff text {sid}")
    if "Borrowed Time" not in (by_sid.get(f"{CHRONOMANCY_SUBSKILL}_desc") or ""):
        fail(f"{CHRONOMANCY_SUBSKILL}_desc must mention Borrowed Time")
    # Borrowed Time is gated behind the rank-2 Chronomancy pick, so the Basic-rank tooltip a fresh Tower
    # hero shows must point at it; otherwise playtesters see no sign of the faction action at all.
    if "Chronomancy" not in skill_desc or "Borrowed Time" not in skill_desc:
        fail(f"{TOWER_SKILL}_desc must say the Chronomancy pick adds Borrowed Time")

    print("homm3-tower-arcane-battery-contract: PASS")


if __name__ == "__main__":
    main()
