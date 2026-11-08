#!/usr/bin/env python3
"""Validate the June 24 HoMM3 custom unit active redesign contract."""

from __future__ import annotations

import argparse
import importlib.util
import json
import pathlib
import re
import sys
import zipfile
from typing import Any

TARGETS: dict[str, dict[str, Any]] = {
    "h3_archer_upg_alt": {"faction":"homm3_castle","kind":"unit","source":["crossbowman","abilities",0],"rank":2,"energy":2,"cd":2,"icon":"skill_tactics","buff":"crossbowman_buff_1","duration":2,"forbid":["attack_defense_debuff"]},
    "h3_archer_upg": {"faction":"homm3_castle","kind":"unit","source":["crossbowman_upg_alt","abilities",1],"rank":1,"energy":1,"cd":1,"icon":"sub_skill_assault_1_icon","buff":"crossbowman_debuff","duration":1,"statDmgMult":0.5,"forbid":["crossbowman_buff"]},
    "h3_cavalier_upg": {"faction":"homm3_castle","kind":"unit","source":["godslayer","abilities",0],"rank":1,"energy":1,"cd":1,"icon":"sub_skill_assault_1_icon","statDmgMult":1.0,"forbid":["Champion's Break","attack_defense_debuff","magic_shorten_shadow_effect_icon"]},
    "h3_cavalier_upg_alt": {"faction":"homm3_castle","kind":"unit","source":["arbitrator","abilities",1],"rank":2,"energy":2,"cd":2,"icon":"skill_tactics","mech":"teleport","forbid":["Lancer's Opening","attack_defense_debuff","magic_shorten_shadow_effect_icon"]},
    "h3_angel_upg_alt": {"faction":"homm3_castle","kind":"spell","spell":"space_16_magic_reality_distortion","spellLevel":2,"dealerIndex":1,"rank":5,"energy":3,"cd":3,"icon":"sub_skill_faction_homm3_ability_reality_distortion","buff":"magic_reality_distortion_effect_1","duration":1,"forbid":["bless_spell","magic_favorable_wind_effect_icon"]},
    "h3_nymph_upg_alt": {"faction":"homm3_cove","kind":"spell","spell":"day_1_magic_healing_water","spellLevel":1,"dealerIndex":0,"rank":1,"energy":1,"cd":2,"charges":2,"icon":"sub_skill_faction_homm3_ability_healing_water","mech":"heal","mechValues":["50","1","5","without respawn"],"forbid":["mirth","kitten_horn_buff_icon"]},
    "h3_sea_serpent_upg_alt": {"faction":"homm3_cove","kind":"unit","source":["aqualotl_upg_alt","abilities",1],"rank":2,"energy":2,"cd":2,"icon":"wasp_debuff_icon","buff":"aqualotl_debuff_1","duration":3,"forbid":["poison_decay","curse","fearsome","magic_fatal_decay_effect_icon","magic_unnatural_calm_effect_icon","magic_nairas_kiss_effect_icon"]},
    "h3_medusa_upg_alt": {"faction":"homm3_dungeon","kind":"unit","source":["medusa","abilities",0],"rank":1,"energy":1,"cd":1,"icon":"skill_tactics","attack":"move","forbid":["stone_gaze","neutral_magic_second_sight"]},
    "h3_minotaur": {"faction":"homm3_dungeon","count":0,"forbid":["bless_spell","magic_favorable_wind_effect_icon"]},
    "h3_minotaur_upg": {"faction":"homm3_dungeon","kind":"unit","source":["minos_upg","abilities",0],"rank":2,"energy":2,"cd":2,"icon":"skill_tactics","buff":"minos_buff","duration":1,"forbid":["bless_spell","magic_favorable_wind_effect_icon"]},
    "h3_minotaur_upg_alt": {"faction":"homm3_dungeon","kind":"unit","source":["ent_upg_alt","abilities",1],"rank":2,"energy":2,"cd":2,"icon":"skill_tactics","buff":"ent_taunt_buff","duration":1,"forbid":["bless_spell","magic_favorable_wind_effect_icon","ent_wisp_buff"]},
    "h3_gnoll_upg_alt": {"faction":"homm3_fortress","kind":"spell","spell":"day_5_magic_shorten_shadow","spellLevel":1,"dealerIndex":0,"rank":1,"energy":1,"cd":2,"icon":"sub_skill_faction_homm3_ability_shorten_shadow","buff":"magic_shorten_shadow_effect_0","duration":1,"forbid":["curse","magic_unnatural_calm_effect_icon"]},
    "h3_basilisk_upg_alt": {"faction":"homm3_fortress","kind":"unit","source":["succubus","abilities",0],"rank":1,"energy":1,"cd":2,"icon":"wasp_debuff_icon","buff":"succubus_debuff_1","duration":2,"forbid":["stone_gaze","neutral_magic_second_sight"]},
    "h3_gorgon_upg_alt": {"faction":"homm3_fortress","kind":"unit","source":["black_dragon","abilities",0],"rank":3,"energy":3,"cd":3,"icon":"skill_tactics","buff":"black_dragon_buff","duration":2,"forbid":["acid_debuff","poison_decay","crossbowman_debuff_icon","magic_fatal_decay_effect_icon"]},
    "h3_wyvern_upg": {"faction":"homm3_fortress","kind":"unit","source":["druid","abilities",1],"rank":2,"energy":2,"cd":2,"icon":"wasp_debuff_icon","buff":"druid_bees","duration":3,"statDmgMult":0.0,"forbid":["poison_sting","magic_fatal_decay_effect_icon"]},
    "h3_wyvern_upg_alt": {"faction":"homm3_fortress","kind":"unit","source":["black_dragon_upg_alt","abilities",1],"rank":5,"energy":2,"cd":2,"icon":"sub_skill_assault_1_icon","mech":"push_unit","forbid":["thunderbolt","primal_1_magic_thunderbolt","black_dragon_buff"]},
    "h3_imp_upg": {"faction":"homm3_inferno","kind":"spell","spell":"space_3_magic_energyze","spellLevel":1,"dealerIndex":0,"rank":1,"energy":1,"cd":2,"icon":"sub_skill_faction_homm3_ability_energize","mech":"add_energy","mechValues":["levels","ally","1","0","1"],"forbid":["mana_transfer","magic_inner_light_effect_icon"]},
    "h3_efreeti_upg_alt": {"faction":"homm3_inferno","kind":"spell","spell":"day_14_magic_vengeance","spellLevel":2,"dealerIndex":1,"rank":4,"energy":3,"cd":3,"icon":"sub_skill_faction_homm3_ability_vengeance","buff":"magic_vengeance_effect_0","duration":3,"forbid":["misfortune"]},
    "h3_black_knight_upg_alt": {"faction":"homm3_necropolis","kind":"spell","spell":"night_11_magic_vulnerability","spellLevel":2,"dealerIndex":1,"rank":4,"energy":2,"cd":2,"icon":"sub_skill_faction_homm3_ability_vulnerability","buff":"magic_vulnerability_effect_1","duration":1,"forbid":["curse","magic_unnatural_calm_effect_icon"]},
    "h3_bone_dragon_upg_alt": {"faction":"homm3_necropolis","kind":"spell","spell":"night_14_magic_nairas_kiss","spellLevel":2,"dealerIndex":1,"rank":5,"energy":2,"cd":2,"icon":"sub_skill_faction_homm3_ability_nairas_kiss","buff":"magic_nairas_kiss_effect_1","duration":1,"forbid":["death_stare","neutral_magic_second_sight"]},
    "h3_silver_pegasus": {"faction":"homm3_rampart","kind":"unit","source":["aqualotl_upg","abilities",1],"rank":2,"energy":1,"cd":1,"icon":"skill_tactics","attack":"end_move_attack","count":2,"index":1,"forbid":["aqualotl_wisp_buff"]},
    "h3_gold_pegasus_upg_alt": {"faction":"homm3_rampart","kind":"unit","source":["succubus_upg","abilities",1],"rank":3,"energy":3,"cd":3,"icon":"skill_tactics","mech":"side_buff","count":2,"index":1,"forbid":[]},
    "h3_pristine_unicorn_upg_alt": {"faction":"homm3_rampart","kind":"spell","spell":"day_12_magic_radiant_armor","spellLevel":2,"dealerIndex":1,"rank":4,"energy":3,"cd":3,"icon":"sub_skill_faction_homm3_ability_radiant_armor","buff":"magic_radiant_armor_effect_1","duration":1,"forbid":["blind","neutral_magic_second_sight"]},
    "h3_gargoyle_upg_alt": {"faction":"homm3_tower","kind":"spell","spell":"space_8_magic_carapace","spellLevel":1,"dealerIndex":0,"rank":2,"energy":2,"cd":2,"icon":"sub_skill_faction_homm3_ability_carapace","buff":"magic_carapace_effect_0","duration":1,"buffCharges":1,"forbid":["stunning_blow","wasp_debuff_icon"]},
    "h3_golem_upg_alt": {"faction":"homm3_tower","kind":"spell","spell":"night_2_magic_web","spellLevel":1,"dealerIndex":0,"rank":2,"energy":2,"cd":2,"icon":"sub_skill_faction_homm3_ability_web","buff":"magic_web_effect_0","duration":1,"forbid":["magnetic_slow","skill_tactics","magic_nairas_kiss_effect_icon"]},
    "h3_mage": {"faction":"homm3_tower","kind":"spell","spell":"night_10_magic_silence","spellLevel":1,"dealerIndex":0,"rank":3,"energy":2,"cd":2,"icon":"sub_skill_faction_homm3_ability_silence","buff":"magic_silence_effect","duration":1,"forbid":["magic_arrow","ice_bolt","lightning","weakness_ray","bless_spell","skill_tactics"]},
    "h3_mage_upg_alt": {"faction":"homm3_tower","kind":"spell","spell":"night_10_magic_silence","spellLevel":1,"dealerIndex":0,"rank":3,"energy":2,"cd":2,"icon":"sub_skill_faction_homm3_ability_silence","buff":"magic_silence_effect","duration":1,"forbid":["magic_arrow","ice_bolt","lightning","weakness_ray","bless_spell","skill_tactics"]},
    "h3_genie": {"faction":"homm3_tower","kind":"unit","source":["arbitrator","abilities",0],"rank":2,"energy":2,"cd":2,"icon":"skill_tactics","mech":"teleport","forbid":["bless_spell","magic_favorable_wind_effect_icon"]},
    "h3_genie_upg": {"faction":"homm3_tower","kind":"unit","source":["angel","abilities",0],"rank":1,"energy":1,"cd":2,"icon":"skill_tactics","mech":"transfer_buffs","forbid":["boon_ability","bless_spell","magic_favorable_wind_effect_icon"]},
    "h3_genie_upg_alt": {"faction":"homm3_tower","kind":"unit","source":["arbitrator_upg_alt","abilities",0],"rank":2,"energy":2,"cd":2,"icon":"skill_tactics","mech":"swap_units","forbid":["misfortune","side_buff_disable_magic_book"]},
    "h3_giant_upg_alt": {"faction":"homm3_tower","kind":"spell","spell":"day_15_magic_judgement","spellLevel":1,"dealerIndex":0,"rank":5,"energy":3,"cd":3,"icon":"sub_skill_faction_homm3_ability_judgement","forbid":["thunderbolt","primal_1_magic_thunderbolt"]},
    "h3_hydra_upg_alt": {"faction":"homm3_fortress","kind":"spell","spell":"primal_14_magic_hksmillas_rampage","spellLevel":1,"dealerIndex":0,"rank":5,"energy":3,"cd":3,"icon":"sub_skill_faction_homm3_ability_hksmillas_rampage","buff":"magic_hksmillas_rampage_effect_0","duration":1,"forbid":["stunning_blow","wasp_debuff_icon"]},
}

PRESERVED_TARGETS: dict[str, dict[str, Any]] = {
    "h3_cavalier": {"faction":"homm3_castle","count":1,"rank":1,"energy":2,"cd":2,"icon":"magic_shorten_shadow_effect_icon","attack":"melee","buff":"magic_shorten_shadow_effect_1","duration":2,"statDmgMult":0.75},
    "h3_angel_upg": {"faction":"homm3_castle","count":1,"rank":4,"energy":2,"cd":-1,"charges":1,"icon":"magic_healing_water_effect_icon","name":"h3_castle_ability_rewind_life_name","mech":"revive","mechValues":["100","1","20","until start amount"]},
}

PASSIVE_ICON_TARGETS: dict[str, dict[str, Any]] = {
    "h3_nymph:passives:1": {"faction":"homm3_cove","sid":"h3_nymph","index":1,"icon":"space_6_magic_blink","custom":False},
    "h3_troglodyte_upg_alt:passives:1": {"faction":"homm3_dungeon","sid":"h3_troglodyte_upg_alt","index":1,"icon":"space_6_magic_blink","custom":False},
    "h3_harpy_upg:passives:0": {"faction":"homm3_dungeon","sid":"h3_harpy_upg","index":0,"icon":"sub_skill_assault_1_icon","custom":False},
    "h3_harpy_upg:passives:2": {"faction":"homm3_dungeon","sid":"h3_harpy_upg","index":2,"icon":"assassin_buff_icon","custom":False},
    "h3_harpy_upg:passives:3": {"faction":"homm3_dungeon","sid":"h3_harpy_upg","index":3,"icon":"assassin_buff_icon","custom":False},
    "h3_wight:passives:0": {"faction":"homm3_necropolis","sid":"h3_wight","index":0,"icon":"sub_skill_assault_1_icon","custom":False},
    "h3_wight:passives:2": {"faction":"homm3_necropolis","sid":"h3_wight","index":2,"icon":"magic_healing_water_effect_icon","custom":False},
    "h3_wight_upg:passives:2": {"faction":"homm3_necropolis","sid":"h3_wight_upg","index":2,"icon":"magic_healing_water_effect_icon","custom":False},
    "h3_wight_upg_alt:passives:2": {"faction":"homm3_necropolis","sid":"h3_wight_upg_alt","index":2,"icon":"magic_healing_water_effect_icon","custom":False},
}

UNIT_VIEW_CARD_BUCKETS = ("passives", "abilities", "defaultAttacks", "alternativeAttacks", "counterAttacks")


CUSTOM_ICON_TARGETS: dict[str, dict[str, Any]] = {
    "h3_pikeman_upg": {"faction":"homm3_castle","icon":"sub_skill_faction_homm3_ability_halberd_hook"},
    "h3_pikeman_upg_alt": {"faction":"homm3_castle","icon":"sub_skill_faction_homm3_ability_execute"},
    "h3_air_elemental_upg": {"faction":"homm3_conflux","icon":"sub_skill_faction_homm3_ability_thunderbolt"},
    "h3_air_elemental_upg_alt": {"faction":"homm3_conflux","icon":"sub_skill_faction_homm3_ability_haste"},
    "h3_fire_elemental_upg": {"faction":"homm3_conflux","icon":"sub_skill_faction_homm3_ability_jumpstart"},
    "h3_fire_elemental_upg_alt": {"faction":"homm3_conflux","icon":"sub_skill_faction_homm3_ability_chain_lightning"},
    "h3_earth_elemental_upg": {"faction":"homm3_conflux","icon":"sub_skill_faction_homm3_ability_fireball"},
    "h3_earth_elemental_upg_alt": {"faction":"homm3_conflux","icon":"sub_skill_faction_homm3_ability_firewall"},
    "h3_troglodyte_upg_alt": {"faction":"homm3_dungeon","icon":"sub_skill_faction_homm3_ability_transport"},
    "h3_walking_dead_upg": {"faction":"homm3_necropolis","icon":"sub_skill_faction_homm3_ability_zombie_clutch"},
    "h3_walking_dead_upg_alt": {"faction":"homm3_necropolis","icon":"sub_skill_faction_homm3_ability_rotting_ray"},
    "h3_wight_upg_alt": {"faction":"homm3_necropolis","icon":"sub_skill_faction_homm3_ability_psychic_scream"},
}


def fail(message: str) -> None:
    print(f"homm3-unit-ability-redesign-contract: {message}", file=sys.stderr)
    raise SystemExit(1)


def import_overlay(repo_root: pathlib.Path) -> Any:
    overlay_dir = repo_root / "tools" / "release_port"
    overlay = overlay_dir / "apply_release_core_overlay.py"
    if str(overlay_dir) not in sys.path:
        sys.path.insert(0, str(overlay_dir))
    spec = importlib.util.spec_from_file_location("homm3_redesign_overlay", overlay)
    if spec is None or spec.loader is None:
        fail(f"cannot import {overlay}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def read_json(core: zipfile.ZipFile, overlay: dict[str, bytes], name: str) -> Any:
    raw = overlay[name] if name in overlay else core.read(name)
    return json.loads(raw.decode("utf-8-sig"))


def first(doc: Any) -> dict[str, Any]:
    if isinstance(doc, dict) and isinstance(doc.get("array"), list) and doc["array"]:
        row = doc["array"][0]
        if isinstance(row, dict):
            return row
    fail("malformed generated Core row")


def mechanics(row: dict[str, Any]) -> list[dict[str, Any]]:
    dealer = row.get("damageDealer") if isinstance(row, dict) else None
    values = dealer.get("targetMechanics") if isinstance(dealer, dict) else None
    return [m for m in values or [] if isinstance(m, dict)]



def expected_common_unit_view_icon(row: dict[str, Any], module: Any) -> str | None:
    name = row.get("name")
    if not isinstance(name, str):
        return None
    mapped = module.UNIT_VIEW_ICON_BY_NAME.get(name)
    if mapped:
        return mapped
    if name.startswith("base_passive_immunity_magic_"):
        return "sub_skill_resistance_1_icon"
    return None


def validate_all_common_unit_view_icons(
    sid: str,
    view: dict[str, Any],
    module: Any,
    repo_root: pathlib.Path,
) -> list[str]:
    issues: list[str] = []
    for bucket in UNIT_VIEW_CARD_BUCKETS:
        rows = view.get(bucket)
        if not isinstance(rows, list):
            continue
        for index, row in enumerate(rows):
            if not isinstance(row, dict):
                continue
            expected_icon = expected_common_unit_view_icon(row, module)
            if expected_icon is None:
                continue
            actual_icon = row.get("icon")
            if actual_icon != expected_icon:
                issues.append(f"{sid}:{bucket}:{index}: icon={actual_icon!r}, expected central common icon {expected_icon!r} for {row.get('name')!r}")
            if str(expected_icon).startswith("sub_skill_faction_homm3_ability_"):
                icon_file = repo_root / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod" / "homm3_skill_icons" / f"{expected_icon}.png"
                if not icon_file.is_file():
                    issues.append(f"{sid}:{bucket}:{index}: missing packaged HoMM ability icon file {icon_file}")
    return issues

def language_rows(doc: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if isinstance(doc, dict):
        for key in ("tokens", "array"):
            values = doc.get(key)
            if isinstance(values, list):
                rows.extend(row for row in values if isinstance(row, dict))
    elif isinstance(doc, list):
        rows.extend(row for row in doc if isinstance(row, dict))
    return rows


def load_english_texts(core: zipfile.ZipFile, overlay: dict[str, bytes]) -> dict[str, str]:
    texts: dict[str, str] = {}
    names = set(core.namelist()) | set(overlay)
    for name in names:
        if not name.startswith("Lang/english/texts/") or not name.endswith(".json"):
            continue
        doc = read_json(core, overlay, name)
        for row in language_rows(doc):
            sid = row.get("sid")
            value = row.get("text")
            if isinstance(sid, str) and isinstance(value, str):
                texts[sid] = value
    return texts


def normalize_text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    value = re.sub(r"<[^>]+>", "", value)
    value = value.replace("\u00a0", " ")
    return re.sub(r"\s+", " ", value).strip().lower()


def card_display_key(row: dict[str, Any], bucket: str, texts: dict[str, str], *, description: bool) -> tuple[str, str] | tuple[str, str, str]:
    name_key = row.get("name")
    desc_key = row.get("description")
    name_text = texts.get(name_key, name_key if isinstance(name_key, str) else "")
    if not description:
        return (bucket, normalize_text(name_text))
    desc_text = texts.get(desc_key, desc_key if isinstance(desc_key, str) else "")
    return (bucket, normalize_text(name_text), normalize_text(desc_text))


def first_array_item_or_none(doc: Any) -> dict[str, Any] | None:
    if isinstance(doc, dict) and isinstance(doc.get("array"), list) and doc["array"]:
        row = doc["array"][0]
        return row if isinstance(row, dict) else None
    if isinstance(doc, list) and doc:
        row = doc[0]
        return row if isinstance(row, dict) else None
    return doc if isinstance(doc, dict) else None


def satisfies_explicit_custom_icon_target(row: dict[str, Any]) -> bool:
    sid = row.get("sid")
    spec = CUSTOM_ICON_TARGETS.get(sid) if isinstance(sid, str) else None
    if not isinstance(spec, dict):
        return False
    return (
        row.get("path") == f"DB/units/units_views/{spec['faction']}/{sid}_v.json"
        and row.get("bucket") == "abilities"
        and row.get("index") == 0
        and row.get("icon") == spec["icon"]
    )


def validate_semantic_vanilla_icon_matches(
    core: zipfile.ZipFile,
    overlay: dict[str, bytes],
    module: Any,
) -> tuple[list[str], dict[str, int]]:
    texts = load_english_texts(core, overlay)
    custom_factions = {m["identity"]["factionSid"] for m in module.CUSTOM_FACTION_MANIFESTS if module.manifest_core_overlay_enabled(m)}
    custom_sids: set[str] = set()
    for manifest in module.CUSTOM_FACTION_MANIFESTS:
        if module.manifest_core_overlay_enabled(manifest):
            custom_sids.update(module.manifest_unit_sids(manifest))

    names = {name for name in core.namelist() if name.startswith("DB/units/units_views/") and name.endswith("_v.json")}
    names.update(name for name in overlay if name.startswith("DB/units/units_views/") and name.endswith("_v.json"))

    custom_rows: list[dict[str, Any]] = []
    all_rows: list[dict[str, Any]] = []
    for name in sorted(names):
        parts = name.split("/")
        faction = parts[3] if len(parts) > 4 else ""
        item = first_array_item_or_none(read_json(core, overlay, name))
        if not isinstance(item, dict):
            raise SystemExit(f"{name}: expected unit view JSON object or non-empty array")
        sid = str(item.get("sid") or pathlib.Path(name).stem.removesuffix("_v"))
        is_custom = faction in custom_factions or sid in custom_sids or faction.startswith("homm3_")
        for bucket in UNIT_VIEW_CARD_BUCKETS:
            rows = item.get(bucket)
            if not isinstance(rows, list):
                continue
            for index, row in enumerate(rows):
                if not isinstance(row, dict):
                    continue
                record = {
                    "path": name,
                    "sid": sid,
                    "bucket": bucket,
                    "index": index,
                    "name": row.get("name"),
                    "description": row.get("description"),
                    "icon": row.get("icon") or "",
                    "exact": card_display_key(row, bucket, texts, description=True),
                    "name_key": card_display_key(row, bucket, texts, description=False),
                }
                all_rows.append(record)
                if is_custom:
                    custom_rows.append(record)

    reference_exact: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    reference_name: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in all_rows:
        if not row["icon"]:
            continue
        reference_exact.setdefault(row["exact"], []).append(row)
        reference_name.setdefault(row["name_key"], []).append(row)

    issues: list[str] = []
    exact_matched = 0
    name_matched = 0
    name_ambiguous = 0
    for row in custom_rows:
        matches = [match for match in reference_exact.get(row["exact"], []) if match is not row]
        icons = {match["icon"] for match in matches if match["icon"]}
        if len(icons) == 1:
            exact_matched += 1
            expected = next(iter(icons))
            if row["icon"] != expected:
                issues.append(f"{row['sid']}:{row['bucket']}:{row['index']}: semantic reference text icon={row['icon']!r}, expected {expected!r} for {row['name']!r}/{row['description']!r}")
            continue
        name_matches = [match for match in reference_name.get(row["name_key"], []) if match is not row]
        name_icons = {match["icon"] for match in name_matches if match["icon"]}
        if len(name_icons) == 1:
            if satisfies_explicit_custom_icon_target(row):
                continue
            name_matched += 1
            expected = next(iter(name_icons))
            if row["icon"] != expected:
                issues.append(f"{row['sid']}:{row['bucket']}:{row['index']}: semantic reference name icon={row['icon']!r}, expected {expected!r} for visible name {row['name']!r}; description did not uniquely match another explicit-icon row")
        elif len(name_icons) > 1:
            name_ambiguous += 1
    return issues, {
        "custom_rows": len(custom_rows),
        "exact_matched": exact_matched,
        "name_matched": name_matched,
        "name_ambiguous": name_ambiguous,
    }


def validate_passive_icon_target(target: str, spec: dict[str, Any], view: dict[str, Any], repo_root: pathlib.Path) -> list[str]:
    issues: list[str] = []
    passives = view.get("passives")
    index = spec["index"]
    if not isinstance(passives, list) or index < 0 or index >= len(passives):
        return [f"{target}: missing passive index {index}"]
    row = passives[index]
    if not isinstance(row, dict):
        return [f"{target}: passive row must be an object"]
    expected_icon = spec["icon"]
    icon = row.get("icon")
    if icon != expected_icon:
        issues.append(f"{target}: passive icon={icon!r}, expected {expected_icon!r}")
    is_custom = bool(spec.get("custom"))
    if is_custom:
        if not str(expected_icon).startswith("sub_skill_faction_homm3_ability_"):
            issues.append(f"{target}: custom passive must use packaged HoMM ability key, found {expected_icon!r}")
        icon_file = repo_root / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod" / "homm3_skill_icons" / f"{expected_icon}.png"
        if not icon_file.is_file():
            issues.append(f"{target}: missing packaged HoMM passive icon file {icon_file}")
    elif str(icon or "").startswith("sub_skill_faction_homm3_ability_"):
        issues.append(f"{target}: common native passive must not use a custom HoMM ability icon key")
    return issues


def validate_custom_icon_target(sid: str, spec: dict[str, Any], view: dict[str, Any], repo_root: pathlib.Path) -> list[str]:
    issues: list[str] = []
    abilities = view.get("abilities")
    if not isinstance(abilities, list) or not abilities:
        return [f"{sid}: custom icon target must have at least one active view row"]
    row = abilities[0]
    if not isinstance(row, dict):
        return [f"{sid}: custom icon target active view row must be an object"]
    expected_icon = spec["icon"]
    if row.get("icon") != expected_icon:
        issues.append(f"{sid}: custom active icon={row.get('icon')!r}, expected HoMM reference icon {expected_icon!r}")
    icon_file = repo_root / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod" / "homm3_skill_icons" / f"{expected_icon}.png"
    if not icon_file.is_file():
        issues.append(f"{sid}: missing packaged HoMM ability icon file {icon_file}")
    if not str(expected_icon).startswith("sub_skill_faction_homm3_ability_"):
        issues.append(f"{sid}: custom active icon must use packaged HoMM ability key, found {expected_icon!r}")
    return issues


def validate_explicit_custom_icon_precedence_fixtures(repo_root: pathlib.Path) -> None:
    for sid, spec in CUSTOM_ICON_TARGETS.items():
        path = f"DB/units/units_views/{spec['faction']}/{sid}_v.json"
        expected_row = {
            "path": path,
            "sid": sid,
            "bucket": "abilities",
            "index": 0,
            "icon": spec["icon"],
        }
        if not satisfies_explicit_custom_icon_target(expected_row):
            fail(f"{sid}: in-memory fixture rejected its configured explicit custom icon target")
        if satisfies_explicit_custom_icon_target({**expected_row, "icon": "__wrong_icon__"}):
            fail(f"{sid}: in-memory fixture accepted a mismatched explicit custom icon")

        accepted_issues = validate_custom_icon_target(
            sid, spec, {"abilities": [{"icon": spec["icon"]}]}, repo_root
        )
        if any(f"{sid}: custom active icon=" in issue for issue in accepted_issues):
            fail(f"{sid}: in-memory fixture rejected the configured icon in the exact target check")
        mismatched_issues = validate_custom_icon_target(
            sid, spec, {"abilities": [{"icon": "__wrong_icon__"}]}, repo_root
        )
        if not any(f"{sid}: custom active icon=" in issue for issue in mismatched_issues):
            fail(f"{sid}: in-memory fixture did not reject a mismatched icon in the exact target check")


def validate_preserved_target(sid: str, spec: dict[str, Any], logic: dict[str, Any], view: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    abilities_l = logic.get("abilities")
    abilities_v = view.get("abilities")
    if not isinstance(abilities_l, list) or not isinstance(abilities_v, list):
        return [f"{sid}: preserved abilities must be lists"]
    expected_count = spec["count"]
    if len(abilities_l) != expected_count or len(abilities_v) != expected_count:
        return [f"{sid}: preserved active count logic/view={len(abilities_l)}/{len(abilities_v)}, expected {expected_count}"]
    if expected_count == 0:
        return issues
    index = int(spec.get("index", 0))
    if index < 0 or index >= expected_count:
        return [f"{sid}: target active index {index} outside active count {expected_count}"]
    lrow, vrow = abilities_l[index], abilities_v[index]
    if not isinstance(lrow, dict) or not isinstance(vrow, dict):
        return [f"{sid}: preserved active row must be an object"]
    for field, expected in (("rank", spec["rank"]), ("energyLevel", spec["energy"]), ("cd", spec["cd"])):
        if lrow.get(field) != expected:
            issues.append(f"{sid}: preserved {field}={lrow.get(field)!r}, expected {expected!r}")
    if "charges" in spec and lrow.get("charges") != spec["charges"]:
        issues.append(f"{sid}: preserved charges={lrow.get('charges')!r}, expected {spec['charges']!r}")
    if spec.get("attack") and lrow.get("attackType_") != spec["attack"]:
        issues.append(f"{sid}: preserved attackType_={lrow.get('attackType_')!r}, expected {spec['attack']!r}")
    if vrow.get("icon") != spec["icon"]:
        issues.append(f"{sid}: preserved icon={vrow.get('icon')!r}, expected {spec['icon']!r}")
    if spec.get("name") and vrow.get("name") != spec["name"]:
        issues.append(f"{sid}: preserved name={vrow.get('name')!r}, expected {spec['name']!r}")
    dealer = lrow.get("damageDealer") if isinstance(lrow.get("damageDealer"), dict) else {}
    buff = dealer.get("buff") if isinstance(dealer.get("buff"), dict) else None
    if "buff" in spec:
        if not buff or buff.get("sid") != spec["buff"]:
            issues.append(f"{sid}: preserved buff={buff!r}, expected sid {spec['buff']!r}")
        elif buff.get("duration") != spec["duration"]:
            issues.append(f"{sid}: preserved buff duration={buff.get('duration')!r}, expected {spec['duration']!r}")
    if "statDmgMult" in spec and dealer.get("statDmgMult") != spec["statDmgMult"]:
        issues.append(f"{sid}: preserved statDmgMult={dealer.get('statDmgMult')!r}, expected {spec['statDmgMult']!r}")
    if "mech" in spec:
        found = next((m for m in mechanics(lrow) if m.get("mech") == spec["mech"]), None)
        if not found:
            issues.append(f"{sid}: preserved missing target mechanic {spec['mech']!r}")
        elif found.get("values") != spec.get("mechValues"):
            issues.append(f"{sid}: preserved mechanic values={found.get('values')!r}, expected {spec.get('mechValues')!r}")
    return issues


def validate_target(sid: str, spec: dict[str, Any], logic: dict[str, Any], view: dict[str, Any], repo_root: pathlib.Path) -> list[str]:
    issues: list[str] = []
    abilities_l = logic.get("abilities")
    abilities_v = view.get("abilities")
    if not isinstance(abilities_l, list) or not isinstance(abilities_v, list):
        return [f"{sid}: abilities must be lists"]
    expected_count = spec.get("count", 1)
    if len(abilities_l) != expected_count or len(abilities_v) != expected_count:
        return [f"{sid}: active count logic/view={len(abilities_l)}/{len(abilities_v)}, expected {expected_count}"]
    serialized = json.dumps({"logic": abilities_l, "view": abilities_v}, ensure_ascii=False).lower()
    for forbidden in spec.get("forbid", []):
        token = str(forbidden).replace("*", "").lower()
        if token and token in serialized:
            issues.append(f"{sid}: forbidden legacy token remains active: {forbidden}")
    if expected_count == 0:
        return issues
    index = int(spec.get("index", 0))
    if index < 0 or index >= expected_count:
        return [f"{sid}: target active index {index} outside active count {expected_count}"]
    lrow, vrow = abilities_l[index], abilities_v[index]
    if not isinstance(lrow, dict) or not isinstance(vrow, dict):
        return [f"{sid}: active row must be an object"]
    for field, expected in (("rank", spec["rank"]), ("energyLevel", spec["energy"]), ("cd", spec["cd"])):
        if lrow.get(field) != expected:
            issues.append(f"{sid}: {field}={lrow.get(field)!r}, expected {expected!r}")
    if "charges" in spec:
        if lrow.get("charges") != spec["charges"]:
            issues.append(f"{sid}: charges={lrow.get('charges')!r}, expected {spec['charges']!r}")
    elif "charges" in lrow:
        issues.append(f"{sid}: charges should be unset, found {lrow.get('charges')!r}")
    if spec.get("attack") and lrow.get("attackType_") != spec["attack"]:
        issues.append(f"{sid}: attackType_={lrow.get('attackType_')!r}, expected {spec['attack']!r}")
    expected_icon = spec.get("icon")
    if vrow.get("icon") != expected_icon:
        issues.append(f"{sid}: icon={vrow.get('icon')!r}, expected vanilla donor icon {expected_icon!r}")
    if spec.get("kind") == "unit" and str(vrow.get("icon") or "").startswith("sub_skill_faction_homm3_ability_"):
        issues.append(f"{sid}: copied native unit-special must not use a HoMM custom icon key")
    if isinstance(expected_icon, str) and expected_icon.startswith("sub_skill_faction_homm3_ability_"):
        icon_file = repo_root / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod" / "homm3_skill_icons" / f"{expected_icon}.png"
        if not icon_file.is_file():
            issues.append(f"{sid}: missing packaged HoMM ability icon file {icon_file}")
    marker = lrow.get("xHomm3AbilityOverride")
    if not isinstance(marker, dict):
        issues.append(f"{sid}: missing xHomm3AbilityOverride marker")
    elif spec.get("kind") == "unit":
        source = spec["source"]
        got = [marker.get("sourceUnitSid"), marker.get("sourceSlotKind"), marker.get("sourceSlotIndex")]
        if got != source:
            issues.append(f"{sid}: source marker={got!r}, expected {source!r}")
    elif spec.get("kind") == "spell":
        sel = lrow.get("xHomm3SpellEffectSelection")
        if not isinstance(sel, dict):
            issues.append(f"{sid}: missing spell effect selection marker")
        else:
            for key, expected in (("spellSid", spec["spell"]), ("spellLevel", spec["spellLevel"]), ("dealerIndex", spec["dealerIndex"])):
                if sel.get(key) != expected:
                    issues.append(f"{sid}: spell {key}={sel.get(key)!r}, expected {expected!r}")
    dealer = lrow.get("damageDealer") if isinstance(lrow.get("damageDealer"), dict) else {}
    buff = dealer.get("buff") if isinstance(dealer.get("buff"), dict) else None
    if "buff" in spec:
        if not buff or buff.get("sid") != spec["buff"]:
            issues.append(f"{sid}: buff={buff!r}, expected sid {spec['buff']!r}")
        elif "duration" in spec and buff.get("duration") != spec["duration"]:
            issues.append(f"{sid}: buff duration={buff.get('duration')!r}, expected {spec['duration']!r}")
        if "buffCharges" in spec and buff and buff.get("charges") != spec["buffCharges"]:
            issues.append(f"{sid}: buff charges={buff.get('charges')!r}, expected {spec['buffCharges']!r}")
    if "statDmgMult" in spec and dealer.get("statDmgMult") != spec["statDmgMult"]:
        issues.append(f"{sid}: statDmgMult={dealer.get('statDmgMult')!r}, expected {spec['statDmgMult']!r}")
    if "mech" in spec:
        found = next((m for m in mechanics(lrow) if m.get("mech") == spec["mech"]), None)
        if not found:
            issues.append(f"{sid}: missing target mechanic {spec['mech']!r}")
        elif "mechValues" in spec and found.get("values") != spec["mechValues"]:
            issues.append(f"{sid}: mechanic values={found.get('values')!r}, expected {spec['mechValues']!r}")
    return issues


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=pathlib.Path, required=True)
    parser.add_argument("--core", type=pathlib.Path, default=None)
    args = parser.parse_args()
    repo_root = args.repo_root.resolve()
    core_path = args.core or pathlib.Path(r"V:\SteamLibrary\steamapps\common\Heroes of Might and Magic Olden Era - Golden Era\HeroesOldenEra_Data\StreamingAssets\Core.zip")
    if not core_path.is_file():
        fail(f"missing source Core.zip: {core_path}")
    validate_explicit_custom_icon_precedence_fixtures(repo_root)
    module = import_overlay(repo_root)
    overlay, _notes = module.build_overlay(core_path)
    issues: list[str] = []
    with zipfile.ZipFile(core_path) as core:
        for sid, spec in TARGETS.items():
            faction = spec["faction"]
            logic = first(read_json(core, overlay, f"DB/units/units_logics/{faction}/{sid}_l.json"))
            view = first(read_json(core, overlay, f"DB/units/units_views/{faction}/{sid}_v.json"))
            issues.extend(validate_target(sid, spec, logic, view, repo_root))
        for sid, spec in PRESERVED_TARGETS.items():
            faction = spec["faction"]
            logic = first(read_json(core, overlay, f"DB/units/units_logics/{faction}/{sid}_l.json"))
            view = first(read_json(core, overlay, f"DB/units/units_views/{faction}/{sid}_v.json"))
            issues.extend(validate_preserved_target(sid, spec, logic, view))
        for sid, spec in CUSTOM_ICON_TARGETS.items():
            faction = spec["faction"]
            view = first(read_json(core, overlay, f"DB/units/units_views/{faction}/{sid}_v.json"))
            issues.extend(validate_custom_icon_target(sid, spec, view, repo_root))
        for target, spec in PASSIVE_ICON_TARGETS.items():
            faction = spec["faction"]
            sid = spec["sid"]
            view = first(read_json(core, overlay, f"DB/units/units_views/{faction}/{sid}_v.json"))
            issues.extend(validate_passive_icon_target(target, spec, view, repo_root))
        custom_unit_view_count = 0
        for manifest in module.CUSTOM_FACTION_MANIFESTS:
            if not module.manifest_core_overlay_enabled(manifest):
                continue
            faction = manifest["identity"]["factionSid"]
            for sid in module.manifest_unit_sids(manifest):
                view = first(read_json(core, overlay, f"DB/units/units_views/{faction}/{sid}_v.json"))
                issues.extend(validate_all_common_unit_view_icons(sid, view, module, repo_root))
                custom_unit_view_count += 1
        semantic_issues, semantic_stats = validate_semantic_vanilla_icon_matches(core, overlay, module)
        issues.extend(semantic_issues)
    if issues:
        for issue in issues[:100]:
            print(issue, file=sys.stderr)
        if len(issues) > 100:
            print(f"... {len(issues) - 100} more", file=sys.stderr)
        fail(f"custom unit ability redesign has {len(issues)} issue(s)")
    print(f"homm3-unit-ability-redesign-contract: validated {len(TARGETS)} redesigned, {len(PRESERVED_TARGETS)} preserved, {len(CUSTOM_ICON_TARGETS)} custom-active-icon, {len(PASSIVE_ICON_TARGETS)} passive-icon, {custom_unit_view_count} common-icon unit packages, and semantic vanilla-icon rows custom={semantic_stats['custom_rows']} exact={semantic_stats['exact_matched']} name={semantic_stats['name_matched']} ambiguous-name={semantic_stats['name_ambiguous']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
