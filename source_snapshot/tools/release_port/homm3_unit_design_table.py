"""Unit design tables: final stats, price and ability kit for h3_* units, one JSON per faction.

Source of truth: custom_factions/unit_designs/<faction>.json (plan: docs/unit_rebalance_plan_20261120.md).
A faction listed there is owned by this layer: after the older balance contract and upgrade-pair parity
have run, each listed unit's stats, gold, squadValue, expBonus and whole ability kit are rebuilt from the
table. Kits are lists of keyword invocations; every keyword below clones a vanilla row piece that already
ships in the release Core (donor named in the keyword), so nothing here invents a data shape.

Two entry points, both called from apply_release_core_overlay.build_overlay:
  add_design_lang_and_buffs  before the lang sync (English card text, buff rows)
  apply_design_units         after upgrade-pair parity (logic rows, view cards)
Validator: tools/validate_homm3_unit_design_table.py.
"""

from __future__ import annotations

import copy
import json
import re
import sys
import zipfile
from pathlib import Path
from typing import Any, Callable

REPO_ROOT = Path(__file__).resolve().parents[2]
DESIGN_DIR = REPO_ROOT / "custom_factions" / "unit_designs"
ABILITY_LANG = "Lang/english/texts/unitsAbility.json"
BUFF_LANG = "Lang/english/texts/unitsBuff.json"
STAT_KEYS = ("hp", "offence", "defence", "damageMin", "damageMax", "speed", "initiative")
# Stat keys the keyword library owns: reset on every listed unit, then set again by its kit.
OWNED_STAT_KEYS = ("damagePerHex", "overkillProtection", "maxOverwatchStrikes", "ignoreShootDmgBuff",
                   "outDmgModsByTargetTags", "inDmgModsByCasterTags", "maxInComingNegativeBuffDuration")
# Unit row tags this layer hands out after every kit is built (apply_design_tags):
#   CHARGER_TAG    every unit row in the Core whose stats carry damagePerHex (vanilla rows included)
#   CONSTRUCT_TAG  every unit row whose class profile holds the construct cast immunity
#   hatred tags    the rows a 'hatred' kit entry names as targets
CHARGER_TAG = "h3_kit_charger"
CONSTRUCT_TAG = "h3_kit_construct"
#   class tags     undead / demon / shooter / flyer rows (see _class_tags), for tag-keyed damage cards
UNDEAD_TAG, DEMON_TAG, SHOOTER_TAG, FLYER_TAG = "h3_kit_undead", "h3_kit_demon", "h3_kit_shooter", "h3_kit_flyer"
CLASS_TAGS = (UNDEAD_TAG, DEMON_TAG, SHOOTER_TAG, FLYER_TAG)
HATED_TARGETS: dict[str, set[str]] = {}
# View passive rows that describe the attack type or movement, not a kit entry: kept across the rebuild.
VIEW_MARKER_PASSIVES = (
    "h3_common_melee_attack_name",
    "h3_common_ranged_attack_name",
    "base_passive_flyer_name",
)
MELEE_PENALTY_TAG = "range_melee_alt_attack_damage"
FOCUS_BY_TIER = {1: (1, 2), 2: (1, 2), 3: (1, 2), 4: (1, 2), 5: (2, 3), 6: (2, 3), 7: (3, 3)}


def load_designs() -> dict[str, dict[str, Any]]:
    designs: dict[str, dict[str, Any]] = {}
    for path in sorted(DESIGN_DIR.glob("*.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        if doc.get("schemaVersion") != 1:
            raise RuntimeError(f"{path.name}: unsupported unit design schemaVersion {doc.get('schemaVersion')!r}")
        faction = doc.get("faction")
        if not isinstance(faction, str) or path.stem != faction:
            raise RuntimeError(f"{path.name}: 'faction' must equal the file name")
        designs[faction] = doc
    return designs


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def kit_sids(unit_sid: str, entry: dict[str, Any]) -> tuple[str, str]:
    """Card text sids for a kit entry: own text (name/text) or an existing vanilla pair (nameSid/descSid)."""
    if "nameSid" in entry:
        return entry["nameSid"], entry["descSid"]
    base = f"h3_kit_ability_{unit_sid[3:]}_{slug(entry['name'])}"  # "_ability" routes the row to unitsAbility.json in the lang sync
    return base + "_name", base + "_description"


def design_lang_rows(designs: dict[str, dict[str, Any]]) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    ability_rows: list[dict[str, str]] = []
    buff_rows: list[dict[str, str]] = []
    for doc in designs.values():
        for unit_sid, unit in doc["units"].items():
            for entry in unit["kit"]:
                if "name" in entry and "text" in entry:
                    name_sid, desc_sid = kit_sids(unit_sid, entry)
                    ability_rows.append({"sid": name_sid, "text": entry["name"]})
                    ability_rows.append({"sid": desc_sid, "text": entry["text"]})
        for buff in doc.get("buffs", []):
            buff_rows.append({"sid": buff["id"] + "_name", "text": buff["name"]})
            buff_rows.append({"sid": buff["id"] + "_description", "text": buff["text"]})
    return ability_rows, buff_rows


def _deep_set(target: dict[str, Any], patch: dict[str, Any]) -> None:
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict) and key != "data":
            _deep_set(target[key], value)
        else:
            target[key] = copy.deepcopy(value)


def add_design_lang_and_buffs(
    release_zip: zipfile.ZipFile,
    output: dict[str, bytes],
    notes: list[str],
    *,
    read_overlay_or_release_json: Callable[..., Any],
    write_json: Callable[[Any], bytes],
    upsert_array_row: Callable[..., bool],
    add_lang_overlay_rows: Callable[..., None],
) -> None:
    designs = load_designs()
    ability_rows, buff_lang_rows = design_lang_rows(designs)
    add_lang_overlay_rows(release_zip, output, ABILITY_LANG, ability_rows, notes)
    add_lang_overlay_rows(release_zip, output, BUFF_LANG, buff_lang_rows, notes)
    buff_index = _buff_index(release_zip, output, read_overlay_or_release_json)
    count = 0
    for doc in designs.values():
        target = doc["buffFile"]
        buff_doc = read_overlay_or_release_json(release_zip, output, target)
        for spec in doc.get("buffs", []):
            donor = buff_index.get(spec["cloneOf"])
            if donor is None:
                raise RuntimeError(f"unit design buff {spec['id']}: donor buff {spec['cloneOf']!r} not found")
            row = copy.deepcopy(donor)
            row["id"] = spec["id"]
            row["name_"] = spec["id"] + "_name"
            row["description_"] = spec["id"] + "_description"
            _deep_set(row, spec.get("set", {}))
            upsert_array_row(buff_doc, row)
            count += 1
        output[target] = write_json(buff_doc)
    notes.append(f"unit design tables: {len(ability_rows) // 2} card text pair(s), {count} buff row(s)")


LAW_OVERRIDE_DIR = REPO_ROOT / "custom_factions" / "law_overrides"


LAW_BUFF_INFOS_PATH = "DB/side_buffs/bonus_buff_infos/buff_infos.json"


def add_law_buffs(
    release_zip: zipfile.ZipFile,
    output: dict[str, bytes],
    notes: list[str],
    *,
    read_overlay_or_release_json: Callable[..., Any],
    write_json: Callable[[Any], bytes],
    upsert_array_row: Callable[..., bool],
    add_lang_overlay_rows: Callable[..., None],
) -> None:
    """Buff rows faction laws grant (law_overrides "lawBuffs", law pass 2026-11-21).

    Each spec {"id", "cloneOf", "set"?, "name", "text", "buffFile"?, "duration"?, "charges"?} clones a Core buff like the unit tables do; a law
    bonus `battleSubskillBonus unit_buff <id>` hands it to the law's receivers. buffFile defaults to the faction's
    unit design buff file.
    """
    designs = load_designs()
    buff_index = _buff_index(release_zip, output, read_overlay_or_release_json)
    lang_rows: list[dict[str, str]] = []
    count = 0
    for path in sorted(LAW_OVERRIDE_DIR.glob("*.json")):
        doc = json.loads(path.read_text(encoding="utf-8-sig"))
        specs = doc.get("lawBuffs") or []
        if not specs:
            continue
        default_file = designs.get(path.stem, {}).get("buffFile")
        for spec in specs:
            target = spec.get("buffFile") or default_file
            if not target:
                raise RuntimeError(f"{path.name} lawBuffs {spec.get('id')}: no buffFile")
            donor = buff_index.get(spec["cloneOf"])
            if donor is None:
                raise RuntimeError(f"{path.name} lawBuffs {spec['id']}: donor buff {spec['cloneOf']!r} not found")
            buff_doc = read_overlay_or_release_json(release_zip, output, target)
            row = copy.deepcopy(donor)
            row["id"] = spec["id"]
            row["name_"] = spec["id"] + "_name"
            row["description_"] = spec["id"] + "_description"
            _deep_set(row, spec.get("set", {}))
            upsert_array_row(buff_doc, row)
            output[target] = write_json(buff_doc)
            buff_index[spec["id"]] = row
            # The law bonus `unit_buff <id>` names a bonus_buff_infos row (vanilla fraction_law_demon_6_bonus ->
            # fraction_law_demon_6_unit_bonus); the info row shares the buff's id. duration/charges per spec.
            info_doc = read_overlay_or_release_json(release_zip, output, LAW_BUFF_INFOS_PATH)
            upsert_array_row(info_doc, {
                "id": spec["id"],
                "sid": spec["id"],
                "duration": int(spec.get("duration", 1)),
                "charges": int(spec.get("charges", 1)),
                "allegiance": spec.get("allegiance", "ally"),
            })
            output[LAW_BUFF_INFOS_PATH] = write_json(info_doc)
            lang_rows.append({"sid": spec["id"] + "_name", "text": spec["name"]})
            lang_rows.append({"sid": spec["id"] + "_description", "text": spec["text"]})
            count += 1
    if lang_rows:
        add_lang_overlay_rows(release_zip, output, BUFF_LANG, lang_rows, notes)
    notes.append(f"law buffs: {count} buff row(s) from law_overrides lawBuffs")


def _buff_index(release_zip: zipfile.ZipFile, output: dict[str, bytes], read_json_fn: Callable[..., Any]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    names = {n for n in release_zip.namelist() if n.startswith("DB/buffs/") and n.endswith(".json")}
    names |= {n for n in output if n.startswith("DB/buffs/") and n.endswith(".json")}
    for name in sorted(names):
        doc = read_json_fn(release_zip, output, name)
        for row in (doc.get("array") or []) if isinstance(doc, dict) else []:
            if isinstance(row, dict) and isinstance(row.get("id"), str):
                index[row["id"]] = row
    return index


class _Ctx:
    def __init__(self, release_zip: zipfile.ZipFile, output: dict[str, bytes], read_json_fn: Callable[..., Any]) -> None:
        self.release_zip = release_zip
        self.output = output
        self.read = read_json_fn
        self.paths: dict[str, str] = {}
        for name in list(release_zip.namelist()) + list(output):
            if name.startswith("DB/units/units_") and name.endswith(".json"):
                self.paths[name.rsplit("/", 1)[1]] = name
        self.buffs = _buff_index(release_zip, output, read_json_fn)

    def path(self, sid: str, kind: str) -> str:
        key = f"{sid}_{kind}.json"
        if key not in self.paths:
            raise RuntimeError(f"unit design: no {kind} row file for {sid}")
        return self.paths[key]

    def donor(self, sid: str, kind: str = "l") -> dict[str, Any]:
        doc = self.read(self.release_zip, self.output, self.path(sid, kind))
        return copy.deepcopy(doc["array"][0])

    def require_buff(self, sid: str, owner: str) -> None:
        if sid not in self.buffs:
            raise RuntimeError(f"{owner}: kit references missing buff {sid!r}")


def _card(unit_sid: str, entry: dict[str, Any], default_icon: str) -> dict[str, Any]:
    name_sid, desc_sid = kit_sids(unit_sid, entry)
    return {"name": name_sid, "description": desc_sid, "icon": entry.get("icon", default_icon)}


def _ability_card(unit_sid: str, entry: dict[str, Any], ability_type: str, icon: str, animation: int, **extra: Any) -> dict[str, Any]:
    card = _card(unit_sid, entry, icon)
    card.update({"abilityType": ability_type, "animationIndex": animation, "useExpandTooltip": "false"})
    card.update(extra)
    return card


def _envelope(ability: dict[str, Any], entry: dict[str, Any]) -> None:
    ability["energyLevel"] = entry["focus"]
    ability["rank"] = entry["focus"]
    ability["cd"] = entry["cd"]
    ability.setdefault("selfMechanics", [])


def _set_buff(dealer: dict[str, Any], entry: dict[str, Any], target: str) -> None:
    if "buff" in entry:
        dealer["buffTarget_"] = target
        dealer["buff"] = {"sid": entry["buff"], "duration": entry["duration"]}
    else:
        dealer.pop("buffTarget_", None)
        dealer.pop("buff", None)


def _in_dmg_list(logic: dict[str, Any]) -> list[dict[str, Any]]:
    mods = logic["stats"].setdefault("inDmgMods", {"list": []})
    return mods.setdefault("list", [])


# --- keywords -----------------------------------------------------------------------------------
# Each takes (ctx, sid, logic, view, entry) and edits the rows in place.

def kw_gallop(ctx, sid, logic, view, entry):  # donor: sunlight_cavalry stats.damagePerHex
    logic["stats"]["damagePerHex"] = entry["v"]
    view["passives"].append(_card(sid, entry, "sub_skill_assault_1_icon"))


def kw_resist(ctx, sid, logic, view, entry):  # donors: esquire / animated_armor / dragon stats.inDmgMods
    mods = _in_dmg_list(logic)
    for mod in [entry, *entry.get("also", []), *entry.get("weak", [])]:  # weak: positive v, damage taken goes up
        mods.append({"t": mod["t"], "v": mod["v"]})
    view["passives"].append(_card(sid, entry, "sub_skill_resistance_1_icon"))


def kw_counters(ctx, sid, logic, view, entry):  # donors: griffin (2), griffin_upg (999) stats.numCounters
    logic["stats"]["numCounters"] = entry["n"]
    view["passives"].append(_card(sid, entry, "skill_tactics"))


def kw_overkill(ctx, sid, logic, view, entry):  # donor: godslayer_upg stats.overkillProtection
    logic["stats"]["overkillProtection"] = 1
    view["passives"].append(_card(sid, entry, "sub_skill_resistance_1_icon"))


def kw_no_retaliation(ctx, sid, logic, view, entry):  # donor: dragon_upg default attack triggerCounter false
    for attack in logic["defaultAttacks"]:
        attack["damageDealer"]["triggerCounter"] = False
    view["passives"].append({"name": "base_passive_noncounter_name", "description": "base_passive_noncounter_description", "icon": "assassin_buff_icon"})


def kw_double_strike(ctx, sid, logic, view, entry):  # donors: esquire_upg (melee), crossbowman_upg (shoot)
    shoot = entry["mode"] == "shoot"
    logic["passives"].append({"data": {"sequenceEffect": "add_attack_after_counter_shoot" if shoot else "add_attack_after_counter_melee"}})
    key = "base_passive_double_strike_ranged_attack" if shoot else "base_passive_double_strike"
    view["passives"].append({"name": key + "_name", "description": key + "_description", "icon": "sub_skill_siege_2_icon" if shoot else "sub_skill_assault_2_icon"})


def kw_sharpshooter(ctx, sid, logic, view, entry):  # donor: crossbowman_upg stats.ignoreShootDmgBuff
    logic["stats"]["ignoreShootDmgBuff"] = True
    view["passives"].append({"name": "base_passive_sharpshooter_name", "description": "base_passive_sharpshooter_description", "icon": "crossbowman_buff_icon"})


def kw_skirmisher(ctx, sid, logic, view, entry):  # donors: halfling, trick_demon (unpenalised melee on a shooter)
    for bucket in ("alternativeAttacks", "counterAttacks"):
        for attack in logic.get(bucket, []):
            dealer = attack["damageDealer"]
            dealer["statDmgMult"] = 1.0
            dealer["tags"] = [tag for tag in dealer.get("tags", []) if tag != MELEE_PENALTY_TAG]
    card = _card(sid, entry, "sub_skill_assault_1_icon")
    view["passives"].append(card)
    for alt in view.get("alternativeAttacks", []):
        alt["description"] = card["description"]


def kw_magic_damper(ctx, sid, logic, view, entry):  # donor: succubus passive sideModifiers manaCostBonus
    logic["passives"].append({"data": {"sideModifiers": [{"tag": "h3_kit_magic_damper", "power": entry["v"], "heroStat": {"manaCostBonus": entry["v"]}, "target": "enemy"}]}})
    view["passives"].append(_card(sid, entry, "magic_nairas_kiss_effect_icon"))


def kw_aura(ctx, sid, logic, view, entry):  # donors: esquire_upg_alt (ranged, allynoself), inquisitor_upg (magic, ally)
    if "aura" in logic:
        raise RuntimeError(f"{sid}: a unit has one aura slot; kit asks for two")
    logic["aura"] = {
        "radius": entry["radius"],
        "tag": f"h3_kit_aura_{slug(entry['name'])}",
        "target": entry["target"],
        "power": int(round(abs(entry["v"]) * 100)),
        "data": {"stats": {"inDmgMods": {"list": [{"t": entry["t"], "v": entry["v"]}]}}},
    }
    view["passives"].append(_card(sid, entry, "sub_skill_resistance_1_icon"))


def kw_on_hit_buff(ctx, sid, logic, view, entry):  # donor: ent default/counter attack with ent_root
    ctx.require_buff(entry["buff"], sid)
    if "escalate" in entry:  # the plugin swaps a repeat application for this buff (Homm3UnitKitRuntime)
        ctx.require_buff(entry["escalate"]["to"], sid)
        if entry["escalate"].get("unless"):
            ctx.require_buff(entry["escalate"]["unless"], sid)
    for bucket in ("defaultAttacks", "counterAttacks"):
        for attack in logic[bucket]:
            _set_buff(attack["damageDealer"], entry, "enemy")
    view["passives"].append(_card(sid, entry, "skill_tactics"))


def kw_spell_immunity(ctx, sid, logic, view, entry):  # donor: dragon passive immunities magic_level
    level = str(entry["level"])
    for passive in logic["passives"]:
        for immunity in passive.get("data", {}).get("immunities", []):
            if immunity.get("type") == "magic_level":
                immunity["tags"] = [level]
                break
        else:
            continue
        break
    else:
        logic["passives"].append({"data": {"immunities": [{"type": "magic_level", "tags": [level]}, {"type": "cast", "tags": ["dragon_immunities"]}]}})
    view["passives"].append({"name": f"base_passive_immunity_magic_{level}_name", "description": f"base_passive_immunity_magic_{level}_description", "icon": "sub_skill_resistance_1_icon"})


def kw_card(ctx, sid, logic, view, entry):  # card line for a mechanic the row already has (e.g. breath pattern)
    view["passives"].append(_card(sid, entry, "sub_skill_assault_2_icon"))


def _when_damaged(ctx, sid, logic, view, entry, donor_action: dict[str, Any], icon: str) -> None:
    ctx.require_buff(entry["buff"], sid)
    donor_action["damageDealer"]["buff"] = {"sid": entry["buff"], "duration": entry["duration"]}
    logic["passives"].append({"actions": [donor_action]})
    view["passives"].append(_card(sid, entry, icon))


def kw_when_damaged_self_buff(ctx, sid, logic, view, entry):  # donor: hydra passive 0 (self buff on damage taken)
    _when_damaged(ctx, sid, logic, view, entry, ctx.donor("hydra")["passives"][0]["actions"][0], "hydra_selfbuff_icon")


def kw_when_damaged_adjacent_debuff(ctx, sid, logic, view, entry):  # donor: hydra_upg passive 0 action 2 (Poisonous Blood)
    action = ctx.donor("hydra_upg")["passives"][0]["actions"][2]
    if action["damageDealer"].get("attackPatternSid") != "attack_swirl_x1_x100":
        raise RuntimeError("hydra_upg passive layout changed; Poisonous Blood action not at index 2")
    _when_damaged(ctx, sid, logic, view, entry, action, "magic_shorten_shadow_effect_icon")


def kw_alt_swirl(ctx, sid, logic, view, entry):  # donor: hydra alternative attack 0 (Whirlwind Strike)
    attack = ctx.donor("hydra")["alternativeAttacks"][0]
    dealer = attack["damageDealer"]
    dealer["tags"] = [tag for tag in dealer["tags"] if tag != "armed_ability_hydra"]
    dealer["statDmgMult"] = entry["mult"]
    logic["alternativeAttacks"] = [attack]
    view["alternativeAttacks"] = [_ability_card(sid, entry, "Ability_type_attack_alt", "sub_skill_assault_2_icon", 0, infoDescription="ability_no_energy", canShowOnUI=True)]


def kw_melee_strike(ctx, sid, logic, view, entry):  # donors: godslayer ability 0; sunlight_cavalry_upg_alt ability 0 (return)
    ability = ctx.donor("sunlight_cavalry_upg_alt" if entry.get("return") else "godslayer")["abilities"][0]
    _envelope(ability, entry)
    dealer = ability["damageDealer"]
    dealer["statDmgMult"] = entry.get("mult", 1.0)
    if "counter" in entry:
        dealer["triggerCounter"] = entry["counter"]
    if "buff" in entry:
        ctx.require_buff(entry["buff"], sid)
    _set_buff(dealer, entry, "enemy")
    if "selfBuff" in entry:
        # Drawback on the user: a hidden passive fires when this unit casts an ability (assassin_upg's own-attack
        # trigger, condition value "ability" as hero sub-skills use it). The rebuild requires a single active.
        own = entry["selfBuff"]
        ctx.require_buff(own["buff"], sid)
        action = ctx.donor("assassin_upg")["passives"][0]["actions"][0]
        conditions = action.get("triggerConditions") or []
        if action.get("trigger") != "unit_cast_ability" or len(conditions) != 1 or conditions[0].get("checkFunction") != "ability_and_allegiance":
            raise RuntimeError("assassin_upg passive layout changed; own-cast trigger not at passives[0].actions[0]")
        conditions[0]["values"] = ["self", "ability"]
        action["damageDealer"]["buff"] = {"sid": own["buff"], "duration": own["duration"]}
        logic["passives"].append({"actions": [action]})
    logic["abilities"].append(ability)
    view["abilities"].append(_ability_card(sid, entry, "Ability_type_attack_mod", "sub_skill_assault_2_icon", 0))


def kw_shot(ctx, sid, logic, view, entry):  # donors: elf_tracker ability 0 (own shot + ability tags), crossbowman_upg_alt ability 1 (debuff shot)
    default = logic["defaultAttacks"][0]
    if default.get("attackType_") != "shoot":
        raise RuntimeError(f"{sid}: 'shot' keyword on a unit whose default attack does not shoot")
    dealer = copy.deepcopy(default["damageDealer"])
    dealer["tags"] = list(dict.fromkeys([*dealer.get("tags", []), "ability", "debuff_ability" if "buff" in entry else "armed_ability"]))
    dealer["statDmgMult"] = entry["mult"]
    dealer["triggerCounter"] = entry["counter"]
    if "buff" in entry:
        ctx.require_buff(entry["buff"], sid)
    _set_buff(dealer, entry, "enemy")
    ability = {"attackType_": "shoot", "damageDealer": dealer}
    _envelope(ability, entry)
    logic["abilities"].append(ability)
    shot_view = view["defaultAttacks"][0]
    extra = {key: shot_view[key] for key in ("projectile", "projectileSpeed", "trajectory") if key in shot_view}
    view["abilities"].append(_ability_card(sid, entry, "Ability_type_attack_mod", "sub_skill_siege_2_icon", 1, **extra))


def kw_reach_strike(ctx, sid, logic, view, entry):  # donor: trick_demon_upg ability 0 (Long Reach, attackType range)
    ability = ctx.donor("trick_demon_upg")["abilities"][0]
    _envelope(ability, entry)
    if "buff" in entry:
        ctx.require_buff(entry["buff"], sid)
    _set_buff(ability["damageDealer"], entry, "enemy")
    logic["abilities"].append(ability)
    view["abilities"].append(_ability_card(sid, entry, "Ability_type_attack_mod", "sub_skill_assault_2_icon", 0))


def kw_self_buff(ctx, sid, logic, view, entry):  # donor: ent_upg_alt ability 1 (free self buff, instacast)
    ctx.require_buff(entry["buff"], sid)
    ability = ctx.donor("ent_upg_alt")["abilities"][1]
    _envelope(ability, entry)
    _set_buff(ability["damageDealer"], entry, "self")
    logic["abilities"].append(ability)
    view["abilities"].append(_ability_card(sid, entry, "Ability_type_buff", "skill_tactics", 2, infoDescription="ability_no_turn"))


def kw_revive(ctx, sid, logic, view, entry):  # donor: lich ability 0 (Rewind Death) + lightweaver_upg non-living immunity tags
    ability = ctx.donor("lich")["abilities"][0]
    _envelope(ability, entry)
    ability["charges"] = entry["charges"]
    dealer = ability["damageDealer"]
    dealer["tags"] = list(dict.fromkeys([*dealer["tags"], "undead_immunities", "embodiment_immunities", "construct_immunities"]))
    dealer["targetMechanics"] = [{"mech": "revive", "values": list(entry["values"])}]
    logic["abilities"].append(ability)
    view["abilities"].append(_ability_card(sid, entry, "Ability_type_special", "magic_healing_water_effect_icon", 2, excaptionInTooltip="description_effect_undead_embodiment_construct_immunities"))


def kw_mass_dispel(ctx, sid, logic, view, entry):  # donor: lightweaver_upg ability 1, dispel half only
    ability = ctx.donor("lightweaver_upg")["abilities"][1]
    _envelope(ability, entry)
    dealer = ability["damageDealer"]
    dealer["tags"] = [tag for tag in dealer["tags"] if tag != "heal_ability"]
    dealer["targetMechanics"] = [mech for mech in dealer["targetMechanics"] if mech.get("mech") == "dispel"]
    if len(dealer["targetMechanics"]) != 1:
        raise RuntimeError("lightweaver_upg ability 1 no longer carries exactly one dispel mechanic")
    logic["abilities"].append(ability)
    view["abilities"].append(_ability_card(sid, entry, "Ability_type_special", "magic_inner_light_effect_icon", 2, excaptionInTooltip="description_effect_undead_embodiment_construct_immunities"))


def kw_landing(ctx, sid, logic, view, entry):  # donor: black_dragon_upg_alt ability 1 (Dragonflight)
    ability = ctx.donor("black_dragon_upg_alt")["abilities"][1]
    _envelope(ability, entry)
    dealer = ability["damageDealer"]
    if entry["enemiesOnly"]:
        dealer["damageTarget_"] = "enemy"
    if not entry["push"]:
        dealer["targetMechanics"] = []
    logic["abilities"].append(ability)
    donor_view = ctx.donor("black_dragon_upg_alt", "v")["abilities"][1]
    view["abilities"].append(_ability_card(sid, entry, "Ability_type_movement", "magic_favorable_wind_effect_icon", 2, startTpTime=donor_view["startTpTime"], endTpTime=donor_view["endTpTime"]))


# --- composed keywords: native keys in combinations no shipped unit uses (each needs one in-game proof) ---

def kw_effect_immunity(ctx, sid, logic, view, entry):  # effect-tag immunity (qilin: movementNegative; here mind effects)
    logic["passives"].append({"data": {"immunities": [{"type": "effect", "tags": list(entry["tags"])}]}})
    view["passives"].append(_card(sid, entry, "sub_skill_resistance_1_icon"))


def runtime_mirror(entry: dict[str, Any]) -> bool:
    """A runtime rule that powers another card of the unit (abilityOnly, card false, or no text of its own): the other
    card describes it, so it adds no passive card."""
    return entry.get("k") == "runtime" and (bool(entry.get("abilityOnly")) or entry.get("card") is False or "text" not in entry)


def kw_runtime(ctx, sid, logic, view, entry):  # plugin-side rule (Homm3UnitKitRuntime, table Homm3UnitKitRules.g.cs)
    if runtime_mirror(entry):
        return
    view["passives"].append(_card(sid, entry, "sub_skill_assault_2_icon"))


def kw_stat_aura(ctx, sid, logic, view, entry):  # aura carrying plain stats (e.g. enemies within 1: speed -1)
    if "aura" in logic:
        raise RuntimeError(f"{sid}: a unit has one aura slot; kit asks for two")
    logic["aura"] = {
        "radius": entry["radius"],
        "tag": f"h3_kit_aura_{slug(entry['name'])}",
        "target": entry["target"],
        "power": entry.get("power", 1),
        "data": {"stats": copy.deepcopy(entry["stats"])},
    }
    view["passives"].append(_card(sid, entry, "magic_web_effect_icon"))


def kw_start_buff(ctx, sid, logic, view, entry):  # battle-long self buff, granted like qilin's start_battle passive
    ctx.require_buff(entry["buff"], sid)
    action = ctx.donor("qilin")["passives"][1]["actions"][0]
    if action.get("trigger") != "start_battle":
        raise RuntimeError("qilin passive layout changed; start_battle action not at passives[1]")
    action["damageDealer"]["buffTarget_"] = "self"
    action["damageDealer"]["buff"] = {"sid": entry["buff"], "duration": -1}
    logic["passives"].append({"actions": [action]})
    view["passives"].append(_card(sid, entry, entry.get("icon", "sub_skill_tactics_4_defence_buff_icon")))


def kw_rally(ctx, sid, logic, view, entry):  # free action: buff every ally within 1 (minos_upg_alt rumble, allies instead of enemies)
    ctx.require_buff(entry["buff"], sid)
    ability = ctx.donor("minos_upg_alt")["abilities"][1]
    dealer = ability["damageDealer"]
    if dealer.get("attackPatternSid") != "attack_rumble_x1_x100":
        raise RuntimeError("minos_upg_alt ability 1 is no longer the rumble-from-self cast")
    _envelope(ability, entry)
    ability["actionCost"] = 0
    dealer["tags"] = ["ability", "buff_ability"]
    dealer["affectTargetParams"]["castTarget_"] = "allynoself"
    _set_buff(dealer, entry, "ally")
    logic["abilities"].append(ability)
    view["abilities"].append(_ability_card(sid, entry, "Ability_type_buff", "skill_tactics", 2, infoDescription="ability_no_turn"))


def kw_swap(ctx, sid, logic, view, entry):  # swap_units (arbitrator_upg_alt): first pick is this unit, second an ally in range
    ability = ctx.donor("arbitrator_upg_alt")["abilities"][0]
    dealer = ability["damageDealer"]
    if [m.get("mech") for m in dealer.get("targetMechanics", [])] != ["swap_units"]:
        raise RuntimeError("arbitrator_upg_alt ability 0 no longer carries swap_units")
    _envelope(ability, entry)
    ability.pop("actionCost", None)
    for key in ("castTargetParams", "affectTargetParams"):
        dealer[key]["castTarget_"] = "self"
    for key in ("orderedCastParams", "orderedAffectParams"):
        dealer[key][0]["castTarget_"] = "allynoself"
        dealer[key][0]["distanceFromFirst"] = entry["range"]
    logic["abilities"].append(ability)
    view["abilities"].append(_ability_card(sid, entry, "Ability_type_movement", "magic_favorable_wind_effect_icon", 2))


def kw_breath_strike(ctx, sid, logic, view, entry):  # the unit's own breath shape on a strike-and-return ability
    ability = ctx.donor("sunlight_cavalry_upg_alt")["abilities"][0]
    if not ability.get("returnToStartAfterAttack"):
        raise RuntimeError("sunlight_cavalry_upg_alt ability 0 no longer returns to its start hex")
    _envelope(ability, entry)
    dealer = ability["damageDealer"]
    own = logic["defaultAttacks"][0]["damageDealer"]
    for key in ("attackPatternSid", "castTargetParams", "affectTargetParams", "damageTarget_"):
        dealer[key] = copy.deepcopy(own[key])
    dealer["statDmgMult"] = entry.get("mult", 1.0)
    dealer["triggerCounter"] = False
    logic["abilities"].append(ability)
    view["abilities"].append(_ability_card(sid, entry, "Ability_type_attack_mod", "sub_skill_assault_2_icon", 0))


def kw_swirl_strike(ctx, sid, logic, view, entry):  # hydra's whirlwind shape as a Focus ability at full damage
    ability = ctx.donor("hydra")["alternativeAttacks"][0]
    dealer = ability["damageDealer"]
    if dealer.get("attackPatternSid") != "attack_swirl_with_target_x100":
        raise RuntimeError("hydra alternative attack 0 is no longer the whirlwind")
    ability.pop("dontUseEnergy", None)
    _envelope(ability, entry)
    dealer["tags"] = ["ability", *[tag for tag in dealer["tags"] if tag != "armed_ability_hydra"]]
    dealer["statDmgMult"] = entry["mult"]
    dealer["triggerCounter"] = False
    logic["abilities"].append(ability)
    view["abilities"].append(_ability_card(sid, entry, "Ability_type_attack_mod", "sub_skill_assault_2_icon", 0))


def kw_dive(ctx, sid, logic, view, entry):  # jump at one enemy unit (lava_larva's unit-targeted jump) and strike it
    donor = ctx.donor("lava_larva")["abilities"][1]
    cast = donor["damageDealer"]["castTargetParams"]
    if donor.get("attackType_") != "jump" or cast.get("selection") != "hexOrObject":
        raise RuntimeError("lava_larva ability 1 is no longer the unit-targeted jump")
    cast["castTarget_"] = "enemy"
    affect = donor["damageDealer"]["affectTargetParams"]
    affect["castTarget_"] = "enemy"
    ability = {
        "attackType_": "jump",
        "damageDealer": {
            "shootRange": entry["range"],
            "tags": ["ability", "armed_ability", "movement_ability", "normal_damage", "basic_attack", "melee_attack"],
            "triggerCounter": False,
            "attackPatternSid": "attack_single_x100",
            "castTargetParams": cast,
            "affectTargetParams": affect,
            "damageTarget_": "enemy",
            "damageType_": "normal",
            "statDmgMult": entry["mult"],
            "targetMechanics": [],
        },
    }
    _envelope(ability, entry)
    logic["abilities"].append(ability)
    jump = ctx.donor("gorilla", "v")["abilities"][0]
    timings = {key: jump[key] for key in ("jumpPrepareTime", "jumpFlyTime", "jumpEndTime", "damageTimeOffset", "jumpMaxHeight")}
    view["abilities"].append(_ability_card(sid, entry, "Ability_type_attack", "magic_favorable_wind_effect_icon", 0, **timings))


def kw_cleanse(ctx, sid, logic, view, entry):  # lightweaver_upg's dispel on one ally within range, not the whole army
    ability = ctx.donor("lightweaver_upg")["abilities"][1]
    _envelope(ability, entry)
    dealer = ability["damageDealer"]
    dealer["tags"] = [tag for tag in dealer["tags"] if tag != "heal_ability"]
    dealer["targetMechanics"] = [mech for mech in dealer["targetMechanics"] if mech.get("mech") == "dispel"]
    if len(dealer["targetMechanics"]) != 1:
        raise RuntimeError("lightweaver_upg ability 1 no longer carries exactly one dispel mechanic")
    dealer.pop("multitargetType", None)
    dealer["shootRange"] = entry["range"]
    for key in ("castTargetParams", "affectTargetParams"):
        dealer[key]["castTarget_"] = "allynoself"
        dealer[key]["selection"] = "object"
    logic["abilities"].append(ability)
    view["abilities"].append(_ability_card(sid, entry, "Ability_type_special", "magic_inner_light_effect_icon", 2, excaptionInTooltip="description_effect_undead_embodiment_construct_immunities"))


# --- rules the first all-faction pass could only wish for (2026-11-21) ---

def kw_hatred(ctx, sid, logic, view, entry):  # donor: dragon_hunter stats.outDmgModsByTargetTags ("dragon")
    mods = logic["stats"].setdefault("outDmgModsByTargetTags", {"list": []})
    mods.setdefault("list", []).append({"t": entry["tag"], "v": entry["v"]})
    HATED_TARGETS.setdefault(entry["tag"], set()).update(entry["targets"])
    view["passives"].append(_card(sid, entry, "sub_skill_assault_1_icon"))


def kw_brace(ctx, sid, logic, view, entry):  # dragon_hunter's inDmgModsByCasterTags slot, against CHARGER_TAG rows
    mods = logic["stats"].setdefault("inDmgModsByCasterTags", {"list": []})
    mods.setdefault("list", []).append({"t": CHARGER_TAG, "v": entry["v"]})
    view["passives"].append(_card(sid, entry, "sub_skill_resistance_1_icon"))


def kw_short_debuffs(ctx, sid, logic, view, entry):  # donor: sub_skill_resistance_3_alt unitStat maxInComingNegativeBuffDuration
    logic["stats"]["maxInComingNegativeBuffDuration"] = entry["rounds"]
    view["passives"].append(_card(sid, entry, "sub_skill_resistance_3_icon"))


def kw_army_stat(ctx, sid, logic, view, entry):  # donors: olgoi / avatar_of_war globalPassives (whole side, strongest only)
    logic.setdefault("globalPassives", []).append({
        "tag": f"h3_kit_army_{slug(entry['name'])}", "target": entry["target"], "power": entry.get("power", 1),
        "data": {"stats": copy.deepcopy(entry["stats"])}})
    view["passives"].append(_card(sid, entry, "sub_skill_tactics_4_defence_buff_icon"))


def kw_corpse_ward(ctx, sid, logic, view, entry):
    """While the unit lives, corpses of its side cannot be consumed (the disablers every undead row carries).

    globalPassives (olgoi) carrying data.disablers by mechanic, the pair magic_fatal_decay_effect_0 puts on one
    unit. A globalPassives block with disablers ships on no vanilla row: needs its in-game proof.
    """
    logic.setdefault("globalPassives", []).append({
        "tag": "h3_kit_corpse_ward", "target": entry.get("target", "ally"), "power": 1,
        "data": {"disablers": [{"mech": mech} for mech in entry["mechs"]]}})
    view["passives"].append(_card(sid, entry, "magic_fatal_decay_effect_icon"))


def kw_always_return(ctx, sid, logic, view, entry):  # donor: assassin / sunlight_cavalry_upg_alt AbilityLogicConfig.returnToStartAfterAttack
    melee = [a for a in logic.get("defaultAttacks", []) if a.get("attackType_") == "melee"]
    if not melee:
        raise RuntimeError(f"{sid}: always_return requires at least one melee default attack")
    for attack in melee:
        attack["returnToStartAfterAttack"] = True
    view["passives"].append(_card(sid, entry, "magic_favorable_wind_effect_icon"))


def kw_reflect(ctx, sid, logic, view, entry):  # donor: ent_upg_alt passive (Crystal Thorns), flat values as black_dragon_buff
    action = None
    for passive in ctx.donor("ent_upg_alt")["passives"]:
        for candidate in passive.get("actions", []):
            mechs = candidate.get("damageDealer", {}).get("targetMechanics", [])
            if candidate.get("trigger") == "unit_took_damage" and [m.get("mech") for m in mechs] == ["revenge_damage"]:
                action = candidate
    if action is None:
        raise RuntimeError("ent_upg_alt no longer carries the revenge_damage passive")
    action["damageDealer"]["targetMechanics"] = [{
        "mech": "revenge_damage", "values": ["flat", "magic_pure", "0", str(entry["perCreature"]), "1", "10", "melee"],
        "additionalValues": ["magic_damage"]}]
    logic["passives"].append({"actions": [action]})
    view["passives"].append(_card(sid, entry, "magic_vengeance_effect_icon"))


def kw_keep_ability(ctx, sid, logic, view, entry):  # resolved in _rebuild_unit (needs the pre-reset rows)
    raise RuntimeError("keep_ability is handled by the rebuild, not dispatched")


KEYWORDS: dict[str, Callable[..., None]] = {
    name[3:]: fn for name, fn in list(globals().items()) if name.startswith("kw_") and callable(fn)
}
ACTIVE_KEYWORDS = {"melee_strike", "shot", "reach_strike", "self_buff", "revive", "mass_dispel", "landing", "keep_ability",
                   "rally", "swap", "breath_strike", "swirl_strike", "dive", "cleanse"}


def _load_extensions() -> None:
    """Per-faction keyword modules: tools/release_port/unit_design_keywords/<faction>.py.

    Each module defines kw_<name>(ctx, sid, logic, view, entry) functions and, optionally, ACTIVE = {names} for
    keywords that add an active ability. Names must be new: a module cannot replace a shared keyword.
    """
    import importlib.util
    folder = Path(__file__).resolve().parent / "unit_design_keywords"
    for path in sorted(folder.glob("*.py")):
        if path.name.startswith("_"):
            continue
        spec = importlib.util.spec_from_file_location(f"unit_design_keywords_{path.stem}", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        for name, fn in vars(module).items():
            if name.startswith("kw_") and callable(fn):
                if name[3:] in KEYWORDS:
                    raise RuntimeError(f"{path.name}: keyword {name[3:]!r} already exists")
                KEYWORDS[name[3:]] = fn
        ACTIVE_KEYWORDS.update(getattr(module, "ACTIVE", ()))


def _rebuild_unit(ctx: _Ctx, sid: str, unit: dict[str, Any], logic: dict[str, Any], view: dict[str, Any]) -> None:
    old_abilities = list(zip(logic.get("abilities", []), view.get("abilities", [])))
    if len(logic.get("abilities", [])) != len(view.get("abilities", [])):
        raise RuntimeError(f"{sid}: logic and view ability counts differ before the design rebuild")
    stats = logic["stats"]
    for key in STAT_KEYS:
        stats[key] = unit["stats"][key]
    for key in OWNED_STAT_KEYS:
        stats.pop(key, None)
    stats["numCounters"] = 1
    stats["inDmgMods"] = {"list": []}
    logic.pop("aura", None)
    logic.pop("globalPassives", None)
    # Immunity / class-profile passives stay; sequence effects, side modifiers and triggered actions are kit-owned.
    logic["passives"] = [
        p for p in logic.get("passives", [])
        if isinstance(p, dict) and "actions" not in p
        and not ({"sequenceEffect", "sideModifiers", "stats"} & set(p.get("data", {})))
    ]
    logic["abilities"] = []
    shooter = logic["defaultAttacks"][0].get("attackType_") == "shoot"
    for attack in logic["defaultAttacks"]:
        attack["damageDealer"]["triggerCounter"] = True
        attack.pop("returnToStartAfterAttack", None)
    for bucket in ("defaultAttacks", "counterAttacks"):
        for attack in logic[bucket]:
            attack["damageDealer"].pop("buff", None)
            attack["damageDealer"].pop("buffTarget_", None)
    if shooter:
        for bucket in ("alternativeAttacks", "counterAttacks"):
            for attack in logic.get(bucket, []):
                dealer = attack["damageDealer"]
                dealer["statDmgMult"] = 0.5
                if MELEE_PENALTY_TAG not in dealer["tags"]:
                    dealer["tags"].append(MELEE_PENALTY_TAG)
        for alt in view.get("alternativeAttacks", []):
            alt["description"] = "h3_common_alt_attack_melee_half_description"
    else:
        logic["alternativeAttacks"] = []
        view["alternativeAttacks"] = []
    view["passives"] = [p for p in view.get("passives", []) if isinstance(p, dict) and p.get("name") in VIEW_MARKER_PASSIVES]
    view["abilities"] = []
    for entry in unit["kit"]:
        keyword = entry["k"]
        if keyword == "keep_ability":
            kept = [(l, v) for l, v in old_abilities if v.get("name") == entry["view"]]
            if len(kept) != 1:
                raise RuntimeError(f"{sid}: keep_ability {entry['view']!r} matched {len(kept)} existing abilities")
            logic["abilities"].append(kept[0][0])
            view["abilities"].append(kept[0][1])
            continue
        if keyword not in KEYWORDS:
            raise RuntimeError(f"{sid}: unknown kit keyword {keyword!r}")
        KEYWORDS[keyword](ctx, sid, logic, view, entry)
    if any("selfBuff" in entry for entry in unit["kit"]) and len(logic["abilities"]) != 1:
        raise RuntimeError(f"{sid}: a selfBuff drawback fires on any ability cast, so the unit must have exactly one active")
    gold_rows = [row for row in logic["unitCost"]["costResArray"] if row.get("name") == "gold"]
    if len(gold_rows) != 1:
        raise RuntimeError(f"{sid}: expected exactly one gold cost row")
    gold_rows[0]["cost"] = unit["gold"]
    logic["squadValue"] = unit["squadValue"]
    # The June balance recommendation no longer describes this row.
    logic.pop("xHomm3BalanceRecommendation20260625", None)
    logic["xHomm3UnitDesign"] = {"source": f"custom_factions/unit_designs/{logic['fraction']}.json", "role": unit["role"]}


def kit_size(unit: dict[str, Any]) -> int:
    return len(unit["kit"])


def check_design(doc: dict[str, Any], lines: list[tuple[str, str, str]]) -> list[str]:
    """Static rules that need no Core: lines are (base, upg, alt) sids from the faction manifest."""
    errors: list[str] = []
    units = doc["units"]
    listed = {sid for line in lines for sid in line}
    for sid in sorted(set(units) ^ listed):
        errors.append(f"{sid}: listed in only one of design table / manifest unit lines")
    for base, upg, alt in lines:
        if not all(sid in units for sid in (base, upg, alt)):
            continue
        b, u, a = units[base], units[upg], units[alt]
        if (u["gold"], u["squadValue"]) != (a["gold"], a["squadValue"]):
            errors.append(f"{upg}/{alt}: upgrade and alternate must share gold and squadValue")
        differing = [key for key in STAT_KEYS if u["stats"][key] != a["stats"][key]]
        if len(differing) < 3:
            errors.append(f"{upg}/{alt}: alternates differ in only {len(differing)} stat(s) {differing}; need at least 3")
        # A body that is no better in any stat is allowed: the stronger kit is what it pays for. Whether the two
        # sides are an even trade is measured on effective output (unit_power_model, pair gap in the validator).
        for sid, row in ((upg, u), (alt, a)):
            below = [key for key in STAT_KEYS if row["stats"][key] < b["stats"][key]]
            if below:
                errors.append(f"{sid}: {below} below base {base}")
            if kit_size(row) <= kit_size(b):
                errors.append(f"{sid}: kit ({kit_size(row)}) must be larger than base kit ({kit_size(b)})")
        if {u["role"], a["role"]} != {"striker", "ward"} and doc.get("requireRolePair", True):
            errors.append(f"{upg}/{alt}: roles must be one of each trade side, got {u['role']}/{a['role']}")
    chance = re.compile(r"\bchance\b|\d+% (?:to|of the time)|\bmay\b|\bsometimes\b|\brandom", re.IGNORECASE)
    for sid, unit in units.items():
        if unit["stats"]["damageMin"] > unit["stats"]["damageMax"]:
            errors.append(f"{sid}: damageMin above damageMax")
        for entry in unit["kit"]:
            text = entry.get("text", "")
            if chance.search(text):
                errors.append(f"{sid}: kit text reads as chance-based: {text!r}")
            if "—" in text or "–" in text:
                errors.append(f"{sid}: kit text uses a dash character: {text!r}")
    return errors


# Rows as they were before the design rebuild, for later overlay steps that address a unit's old abilities,
# passives or cards by position (Conflux fusion signatures pick curated pieces that way).
PRE_DESIGN_ROWS: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}


def apply_design_units(
    release_zip: zipfile.ZipFile,
    output: dict[str, bytes],
    notes: list[str],
    *,
    read_overlay_or_release_json: Callable[..., Any],
    write_json: Callable[[Any], bytes],
    expected_exp_bonus: Callable[[int, int, str], int],
    ensure_unit_view_card_icons: Callable[[dict[str, Any]], int],
) -> None:
    designs = load_designs()
    ctx = _Ctx(release_zip, output, read_overlay_or_release_json)
    HATED_TARGETS.clear()
    count = 0
    for faction, doc in designs.items():
        for sid, unit in doc["units"].items():
            logic_path, view_path = ctx.path(sid, "l"), ctx.path(sid, "v")
            # A row no earlier overlay step touched is still only in the release archive: read through.
            logic_doc = read_overlay_or_release_json(release_zip, output, logic_path)
            view_doc = read_overlay_or_release_json(release_zip, output, view_path)
            logic, view = logic_doc["array"][0], view_doc["array"][0]
            if logic.get("fraction") != faction:
                raise RuntimeError(f"{sid}: row faction {logic.get('fraction')!r} is not {faction}")
            PRE_DESIGN_ROWS[sid] = (copy.deepcopy(logic), copy.deepcopy(view))
            _rebuild_unit(ctx, sid, unit, logic, view)
            logic["expBonus"] = expected_exp_bonus(logic["tier"], logic["squadValue"], sid)
            ensure_unit_view_card_icons(view)
            output[logic_path] = write_json(logic_doc)
            output[view_path] = write_json(view_doc)
            count += 1
    tagged = apply_design_tags(ctx, write_json)
    notes.append(f"unit design tables: rebuilt stats, price and kit for {count} unit(s) in {len(designs)} faction(s); row tags {tagged}")


def _class_tags(row: dict[str, Any]) -> dict[str, bool]:
    """Creature-class tags for tag-keyed kit cards (Smite, Raider, Wind Reader, Bedrock). Vanilla rows carry undead /
    demon; h3 rows do not, so their faction stands in. Shooters and flyers are read from the row itself."""
    tags = set(row.get("tags") or [])
    attacks = row.get("defaultAttacks") or [{}]
    return {
        UNDEAD_TAG: "undead" in tags or row.get("fraction") == "homm3_necropolis",
        DEMON_TAG: "demon" in tags or row.get("fraction") == "homm3_inferno",
        SHOOTER_TAG: isinstance(attacks[0], dict) and attacks[0].get("attackType_") == "shoot",
        FLYER_TAG: row["stats"].get("moveType") == "fly",
    }


def apply_design_tags(ctx: _Ctx, write_json: Callable[[Any], bytes]) -> dict[str, int]:
    """Unit row tags the tag-keyed damage mods need, on every unit row in the Core (vanilla rows included)."""
    hated: dict[str, list[str]] = {}
    for tag, sids in HATED_TARGETS.items():
        for target in sids:
            hated.setdefault(target, []).append(tag)
    counts = {CHARGER_TAG: 0, CONSTRUCT_TAG: 0, "hatred": 0}
    seen: set[str] = set()
    for key, path in sorted(ctx.paths.items()):
        if "/units_logics/" not in path:
            continue
        doc = ctx.read(ctx.release_zip, ctx.output, path)
        rows = doc.get("array") if isinstance(doc, dict) else None
        changed = False
        for row in rows or []:
            if not isinstance(row, dict) or not isinstance(row.get("stats"), dict):
                continue
            add: list[str] = []
            if (row["stats"].get("damagePerHex") or 0) > 0:
                add.append(CHARGER_TAG)
                counts[CHARGER_TAG] += 1
            construct = any(
                immunity.get("type") == "cast" and "construct_immunities" in (immunity.get("tags") or [])
                for passive in row.get("passives", []) if isinstance(passive, dict)
                for immunity in (passive.get("data") or {}).get("immunities", []))
            if construct:
                add.append(CONSTRUCT_TAG)
                counts[CONSTRUCT_TAG] += 1
            for tag in sorted(hated.get(row.get("id"), [])):
                add.append(tag)
                counts["hatred"] += 1
            for tag, qualifies in _class_tags(row).items():
                if qualifies:
                    add.append(tag)
                    counts[tag] = counts.get(tag, 0) + 1
            seen.add(row.get("id"))
            tags = row.setdefault("tags", [])
            # This pass owns these tags outright: a row can inherit one from a donor row tagged by an earlier
            # build (the overlay builds over the installed Core), so drop any the row does not qualify for.
            owned = {CHARGER_TAG, CONSTRUCT_TAG, *HATED_TARGETS, *CLASS_TAGS}
            stale = [tag for tag in tags if tag in owned and tag not in add]
            if stale:
                row["tags"] = tags = [tag for tag in tags if tag not in stale]
                changed = True
            for tag in add:
                if tag not in tags:
                    tags.append(tag)
                    changed = True
        if changed:
            ctx.output[path] = write_json(doc)
    missing = sorted(set(hated) - seen)
    if missing:
        raise RuntimeError(f"unit design hatred targets with no unit row: {missing}")
    return counts


sys.modules.setdefault("homm3_unit_design_table", sys.modules[__name__])
_load_extensions()
