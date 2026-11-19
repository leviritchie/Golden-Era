#!/usr/bin/env python3
"""Validate the HoMM3 Conflux Elemental Fusion faction-skill contract on a candidate Core.

The file name and CLI are kept from the Elemental Conjury validator (csproj and
tools/port_current/run_core_validators.py call it). Checks, on the in-memory overlay:

- skill_faction_homm3_conflux: every rank grants the homm3_conflux_elemental_fusion world spell and
  carries no Elemental Conjury Focus/Attack/Spell Power bonuses; Advanced/Expert keep 3 subskills each;
- the world spell row (Necromancer Will clone, [mode] parameters, mana 10, usage limit 1) + Lang rows;
- subskills: no stale Summon Elementals rows; Stable Bond/Perfect Fusion target exactly the 105 fused units;
- elemental Focus casts: spell-effect Focus receivers, per-creature damage for Thunderbolt/Chain
  Lightning/Fireball, Blinding Strike 115%;
- no starting Focus (stats.startEnergy) on the 15 elementals or any fused unit unless the unit is in
  START_ENERGY_ALLOWLIST (owner 2026-11-16: no family catch-all; each entry needs a carded passive);
- the 105 fused unit rows: present, stat rule against the final parents, Lang names, never pooled.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import pathlib
import sys
import zipfile
from typing import Any

CONFLUX_FACTION = "homm3_conflux"
CONFLUX_SKILL = "skill_faction_homm3_conflux"
SPELL_SID = "homm3_conflux_elemental_fusion"
SPELL_MEMBER = "DB/magics/world_neutral_magics.json"
# sid -> startEnergy. Empty by owner decision 2026-11-16. Add a unit only together with a visible passive
# card on it that states the starting Focus ("Brings N Focus at the start of battle").
START_ENERGY_ALLOWLIST: dict[str, int] = {}
SUBSKILLS_MEMBER = "DB/heroes_skills/sub_skills/sub_skills.json"
FUSED_DEFENSE = "sub_skill_faction_homm3_conflux_elemental_conjury_spell_power"
FUSED_ATTACK = "sub_skill_faction_homm3_conflux_elemental_conjury_expert_spell_tier"
STALE_SUMMON_ELEMENTALS_SUBSKILL_PREFIX = "sub_skill_faction_homm3_conflux_summon_elementals_"
RETIRED_CONJURY_STATS = ("heroOffenceModifier", "heroSpellPowerModifier", "heroIntelligenceModifier", "finalAbilityDamageBonusPercent")
EXPECTED_SUBSKILLS = {
    2: [
        "sub_skill_faction_homm3_conflux_elemental_conjury_native_terrain",
        "sub_skill_faction_homm3_conflux_elemental_conjury_focus_charge",
        FUSED_DEFENSE,
    ],
    3: [
        "sub_skill_faction_homm3_conflux_elemental_conjury_expert_focus_charge",
        "sub_skill_faction_homm3_conflux_elemental_conjury_pathfinding",
        FUSED_ATTACK,
    ],
}
EXPECTED_FOCUS_SPELL_RECEIVERS = (
    "h3_air_elemental_upg",
    "h3_air_elemental_upg_alt",
    "h3_fire_elemental_upg",
    "h3_fire_elemental_upg_alt",
    "h3_earth_elemental_upg",
    "h3_earth_elemental_upg_alt",
)
# (unit, ability index): (minStackDmg, maxStackDmg) with statDmgMult 0 and zero base damage.
EXPECTED_PER_CREATURE_CASTS = {
    ("h3_air_elemental_upg", 0): (11, 12),  # Storm: Thunderbolt
    ("h3_fire_elemental_upg_alt", 0): (28, 29),  # Plasma: Chain Lightning
    ("h3_earth_elemental_upg", 0): (16, 17),  # Magma: Fireball
}
ICE_BLINDING_STRIKE = ("h3_water_elemental_upg", 0, 1.15)


def fail(message: str) -> None:
    print(f"homm3-conflux-elemental-fusion-contract: {message}", file=sys.stderr)
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


def lang_text(doc: Any) -> dict[str, str]:
    """Lang text rows from both sections: vanilla Lang uses ``tokens``; Golden Era Cores also carry ``array``."""
    out: dict[str, str] = {}
    if isinstance(doc, dict):
        for section in ("tokens", "array"):
            for row in doc.get(section) or []:
                if isinstance(row, dict) and isinstance(row.get("sid"), str) and isinstance(row.get("text"), str):
                    out[row["sid"]] = row["text"]
    return out


def unit_row(core_zip, overlay, sid: str, kind: str) -> dict[str, Any]:
    member = f"DB/units/units_{kind}/{CONFLUX_FACTION}/{sid}_{'l' if kind == 'logics' else 'v'}.json"
    return first_array_item(read_json(core_zip, overlay, member), member)


def validate_skill_row(skill_row: dict[str, Any], issues: list[str]) -> None:
    levels = skill_row.get("parametersPerLevel")
    if not isinstance(levels, list) or len(levels) != 3:
        issues.append(f"{CONFLUX_SKILL}: expected exactly 3 parametersPerLevel rows")
        return
    for index, level in enumerate(levels, start=1):
        bonuses = level.get("bonuses") if isinstance(level, dict) else None
        grants = [
            b for b in bonuses or []
            if isinstance(b, dict) and b.get("type") == "heroMagicAddition" and b.get("parameters") == [SPELL_SID, "false"]
        ]
        if len(grants) != 1:
            issues.append(f"{CONFLUX_SKILL}:level{index}: expected one heroMagicAddition [{SPELL_SID}, false], found {len(grants)}")
        for bonus in bonuses or []:
            params = bonus.get("parameters") if isinstance(bonus, dict) else None
            if isinstance(params, list) and params and params[0] in RETIRED_CONJURY_STATS + ("startEnergyLevelsBonus",):
                issues.append(f"{CONFLUX_SKILL}:level{index}: retired Elemental Conjury bonus {params!r}")
        if index in EXPECTED_SUBSKILLS:
            subskills = level.get("subSkills") if isinstance(level, dict) else None
            if list(subskills or []) != EXPECTED_SUBSKILLS[index]:
                issues.append(f"{CONFLUX_SKILL}:level{index}: subSkills={subskills!r}, expected {EXPECTED_SUBSKILLS[index]!r}")


def validate_spell(spell_row: dict[str, Any], issues: list[str]) -> None:
    if spell_row.get("manaCost") != [0, 0, 0, 0]:
        issues.append(f"{SPELL_SID}: manaCost={spell_row.get('manaCost')!r}, expected [0, 0, 0, 0]")
    if spell_row.get("usedOnMap") is not True:
        issues.append(f"{SPELL_SID}: usedOnMap must be true")
    world = spell_row.get("worldMagic")
    settings = world.get("magicSettings") if isinstance(world, dict) else None
    if not isinstance(settings, list) or not settings:
        issues.append(f"{SPELL_SID}: missing worldMagic.magicSettings")
        return
    for setting in settings:
        if setting.get("mechType") != "change_use_necromancy":
            issues.append(f"{SPELL_SID}: mechType={setting.get('mechType')!r}, expected change_use_necromancy")
        if setting.get("parameters") != [SPELL_SID]:
            issues.append(f"{SPELL_SID}: parameters={setting.get('parameters')!r}, expected [{SPELL_SID!r}]")
        if setting.get("usageLimit") != -1:
            issues.append(f"{SPELL_SID}: usageLimit={setting.get('usageLimit')!r}, expected -1 (unlimited)")


def validate_subskills(subskill_rows: list[Any], fused_sids: list[str], issues: list[str]) -> None:
    for row in subskill_rows:
        sid = row.get("id") if isinstance(row, dict) else None
        if isinstance(sid, str) and sid.startswith(STALE_SUMMON_ELEMENTALS_SUBSKILL_PREFIX):
            issues.append(f"stale Summon Elementals subskill still present in Core overlay: {sid}")
    for level_sids in EXPECTED_SUBSKILLS.values():
        for sid in level_sids:
            row = row_by_id(subskill_rows, sid, SUBSKILLS_MEMBER)
            for bonus in row.get("bonuses") or []:
                params = bonus.get("parameters") if isinstance(bonus, dict) else None
                if isinstance(params, list) and params and params[0] in RETIRED_CONJURY_STATS:
                    issues.append(f"{sid}: retired Elemental Conjury bonus {params!r}")
    for sid, stat in ((FUSED_DEFENSE, "defence"), (FUSED_ATTACK, "offence")):
        row = row_by_id(subskill_rows, sid, SUBSKILLS_MEMBER)
        match = [b for b in row.get("bonuses") or [] if isinstance(b, dict) and (b.get("parameters") or [None])[0] == stat]
        if len(match) != 1 or match[0].get("receivers") != fused_sids:
            issues.append(f"{sid}: expected one unitStat {stat} bonus whose receivers are the 105 fused units")


def spell_focus_receivers(core_zip, overlay, unit_sids: list[str], issues: list[str]) -> list[str]:
    result: list[str] = []
    for sid in unit_sids:
        logic = unit_row(core_zip, overlay, sid, "logics")
        view = unit_row(core_zip, overlay, sid, "views")
        logic_abilities = logic.get("abilities") if isinstance(logic.get("abilities"), list) else []
        view_abilities = view.get("abilities") if isinstance(view.get("abilities"), list) else []
        for index, ability in enumerate(logic_abilities):
            selection = ability.get("xHomm3SpellEffectSelection") if isinstance(ability, dict) else None
            if not isinstance(selection, dict):
                continue
            if sid not in result:
                result.append(sid)
            if ability.get("energyLevel", 0) <= 0:
                issues.append(f"{sid}: spell-effect Focus action {index} has no positive energyLevel")
            if selection.get("effectiveSpellPower") is not None:
                issues.append(f"{sid}: spell-effect Focus action {index} hardcodes effectiveSpellPower")
            marker = ability.get("xHomm3AbilityOverride")
            if not isinstance(marker, dict) or not isinstance(marker.get("sourceSpellEffectKey"), str):
                issues.append(f"{sid}: spell-effect Focus action {index} is missing sourceSpellEffectKey marker")
            if index >= len(view_abilities) or view_abilities[index].get("xHomm3SpellEffectSelection") != selection:
                issues.append(f"{sid}: spell-effect Focus action {index} has no matching view selection")
    return result


def validate_elemental_casts(core_zip, overlay, issues: list[str]) -> None:
    for (sid, index), (low, high) in EXPECTED_PER_CREATURE_CASTS.items():
        abilities = unit_row(core_zip, overlay, sid, "logics").get("abilities") or []
        dealer = abilities[index].get("damageDealer") if index < len(abilities) else None
        got = {k: (dealer or {}).get(k) for k in ("statDmgMult", "minBaseDmg", "maxBaseDmg", "minStackDmg", "maxStackDmg")}
        if got != {"statDmgMult": 0.0, "minBaseDmg": 0, "maxBaseDmg": 0, "minStackDmg": low, "maxStackDmg": high}:
            issues.append(f"{sid}:abilities:{index}: per-creature cast fields {got!r}, expected statDmgMult 0, base 0, stack {low}-{high}")
    sid, index, mult = ICE_BLINDING_STRIKE
    abilities = unit_row(core_zip, overlay, sid, "logics").get("abilities") or []
    dealer = abilities[index].get("damageDealer") if index < len(abilities) else None
    if not isinstance(dealer, dict) or dealer.get("statDmgMult") != mult:
        issues.append(f"{sid}:abilities:{index}: Blinding Strike statDmgMult {(dealer or {}).get('statDmgMult')!r}, expected {mult}")


def validate_start_energy(core_zip, overlay, sids: list[str], issues: list[str]) -> None:
    for sid in sids:
        got = int(unit_row(core_zip, overlay, sid, "logics").get("stats", {}).get("startEnergy") or 0)
        expected = START_ENERGY_ALLOWLIST.get(sid, 0)
        if got != expected:
            issues.append(f"{sid}: startEnergy={got}, expected {expected} (no elemental/fusion starting Focus outside START_ENERGY_ALLOWLIST)")


def half_up(value: float) -> int:
    return int(math.floor(value + 0.5))


def validate_fused_units(core_zip, overlay, fusion_module, issues: list[str]) -> int:
    config = fusion_module.load_config()
    units = fusion_module.load_units()["units"]
    names = lang_text(read_json(core_zip, overlay, "Lang/english/texts/units.json"))
    checked = 0
    for pair in config["pairs"]:
        sid = pair["fused"]
        try:
            logic = unit_row(core_zip, overlay, sid, "logics")
            view = unit_row(core_zip, overlay, sid, "views")
        except SystemExit:
            issues.append(f"{sid}: fused unit rows missing")
            continue
        host = unit_row(core_zip, overlay, pair["host"], "logics")["stats"]
        guest = unit_row(core_zip, overlay, pair["guest"], "logics")["stats"]
        stats = logic.get("stats") or {}
        faster = guest if (guest["speed"], guest["initiative"]) > (host["speed"], host["initiative"]) else host
        expected = {
            "hp": host["hp"] + guest["hp"],
            "damageMin": half_up(0.9 * (host["damageMin"] + guest["damageMin"])),
            "damageMax": half_up(0.9 * (host["damageMax"] + guest["damageMax"])),
            "offence": max(host["offence"], guest["offence"]) + 1,
            "defence": max(host["defence"], guest["defence"]) + 1,
            "speed": faster["speed"],
            "initiative": faster["initiative"],
        }
        for key, value in expected.items():
            if stats.get(key) != value:
                issues.append(f"{sid}: stats.{key}={stats.get(key)!r}, expected {value}")
        if logic.get("squadValue") != units[sid]["squadValue"]:
            issues.append(f"{sid}: squadValue={logic.get('squadValue')!r}, expected {units[sid]['squadValue']}")
        for key in ("upgradeSid", "baseSid"):
            if key in logic:
                issues.append(f"{sid}: fused unit must not carry {key}")
        marker = logic.get(fusion_module.FUSED_UNIT_MARKER)
        if not isinstance(marker, dict) or marker.get("poolEligible") is not False:
            issues.append(f"{sid}: missing {fusion_module.FUSED_UNIT_MARKER} marker with poolEligible false")
        if names.get(f"{sid}_name") != pair["name"]:
            issues.append(f"{sid}: Lang units.json name {names.get(sid + '_name')!r}, expected {pair['name']!r}")
        if len(logic.get("abilities") or []) != len(view.get("abilities") or []):
            issues.append(f"{sid}: logic/view ability counts differ")
        checked += 1
    return checked


def validate_language_rows(core_zip, overlay, issues: list[str]) -> None:
    skills = lang_text(read_json(core_zip, overlay, "Lang/english/texts/heroSkills.json"))
    checks = {
        "skill_faction_homm3_conflux_name": ("Elemental Fusion",),
        "skill_faction_homm3_conflux_desc": ("Elemental Fusion", "permanently"),
        "skill_faction_homm3_conflux_desc_1": ("Air", "Water", "Fire", "36", "10 mana", "90%", "permanent"),
        "skill_faction_homm3_conflux_desc_2": ("Earth", "66"),
        "skill_faction_homm3_conflux_desc_3": ("Psychic", "105"),
        f"{FUSED_DEFENSE}_desc": ("Fused", "Defense"),
        f"{FUSED_ATTACK}_desc": ("Fused", "Attack"),
    }
    for sid, required in checks.items():
        text = skills.get(sid)
        if not isinstance(text, str):
            issues.append(f"heroSkills localization missing {sid}")
            continue
        for token in required:
            if token.lower() not in text.lower():
                issues.append(f"{sid}: text {text!r} missing {token!r}")
        if "conjury" in text.lower():
            issues.append(f"{sid}: text still names Elemental Conjury")
    magic = lang_text(read_json(core_zip, overlay, "Lang/english/texts/magic.json"))
    if magic.get(f"{SPELL_SID}_name") != "Elemental Fusion":
        issues.append(f"magic.json {SPELL_SID}_name={magic.get(SPELL_SID + '_name')!r}")
    if not magic.get(f"{SPELL_SID}_description"):
        issues.append(f"magic.json missing {SPELL_SID}_description")


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
    fusion_module = module.conflux_fusion
    manifest = module.load_custom_faction_manifest(CONFLUX_FACTION)
    unit_sids = list(module.manifest_unit_sids(manifest))
    issues: list[str] = []
    if list(module.HOMM3_CONFLUX_ELEMENTAL_FOCUS_SPELL_RECEIVERS) != list(EXPECTED_FOCUS_SPELL_RECEIVERS):
        issues.append("HOMM3_CONFLUX_ELEMENTAL_FOCUS_SPELL_RECEIVERS drifted from the expected spell-effect Focus receivers")
    fused_sids = fusion_module.fused_unit_sids()
    try:
        overlay, _notes = module.build_overlay(core_path)
    except Exception as ex:  # noqa: BLE001
        fail(f"cannot build candidate Core overlay in memory: {ex}")
    with zipfile.ZipFile(core_path) as core_zip:
        skill_row = row_by_id(array_rows(read_json(core_zip, overlay, "DB/heroes_skills/skills/skills.json"), "skills.json"), CONFLUX_SKILL, "skills.json")
        validate_skill_row(skill_row, issues)
        validate_spell(row_by_id(array_rows(read_json(core_zip, overlay, SPELL_MEMBER), SPELL_MEMBER), SPELL_SID, SPELL_MEMBER), issues)
        validate_subskills(array_rows(read_json(core_zip, overlay, SUBSKILLS_MEMBER), SUBSKILLS_MEMBER), fused_sids, issues)
        actual_focus_receivers = spell_focus_receivers(core_zip, overlay, unit_sids, issues)
        if actual_focus_receivers != list(EXPECTED_FOCUS_SPELL_RECEIVERS):
            issues.append(f"spell-effect Focus receivers={actual_focus_receivers!r}, expected {list(EXPECTED_FOCUS_SPELL_RECEIVERS)!r}")
        validate_elemental_casts(core_zip, overlay, issues)
        start_energy_sids = sorted(set(fusion_module.elemental_sids()) | set(fused_sids))
        validate_start_energy(core_zip, overlay, start_energy_sids, issues)
        checked = validate_fused_units(core_zip, overlay, fusion_module, issues)
        validate_language_rows(core_zip, overlay, issues)
    if issues:
        for issue in issues[:100]:
            print(issue, file=sys.stderr)
        if len(issues) > 100:
            print(f"... {len(issues) - 100} more", file=sys.stderr)
        fail(f"Conflux Elemental Fusion contract has {len(issues)} issue(s)")
    print(
        "homm3-conflux-elemental-fusion-contract: validated the Elemental Fusion skill/spell/subskill rows, "
        f"{len(EXPECTED_FOCUS_SPELL_RECEIVERS)} spell-effect Focus receivers, per-creature elemental casts, "
        f"{len(start_energy_sids)} elemental/fused startEnergy rows ({len(START_ENERGY_ALLOWLIST)} allow-listed) and {checked} fused unit rows"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
