"""Core rows for the Tower Artificing faction skill (design: docs/homm3_tower_artificing.md).

Inputs are custom_factions/tower_artificing/artificing_policy.json and the generated
schematic_catalog.json (tools/tower_artificing/build_schematic_catalog.py). Rows:

- one dispellable, battle-long graft buff per graftable schematic (the passive's own data/actions/
  statOverrides, so the native buff system runs it and native purge removes it), plus one variant row per
  carrier for perUnit schematics (godslayer / duelist / phoenix; the runtime picks it by unit sid);
- the curated helper rows the grafts reference (`{graft}_*` aura/debuff/faction buffs, side buffs + infos,
  phoenix heart obstacles), each into the vanilla file of its kind;
- the Transcribe hero action and its 1-round marker buff (Homm3TowerArtificingRuntime watches the
  marker being added to learn which unit was transcribed);
- visible hero map buffs for map grafts (`hero_buff` helpers: the native unit-set bonus, held while a carrier
  is in the army; Homm3TowerArtificingRuntime reconciles them);
- hidden hero map buffs that hold the ledger (essence bits, per-schematic source-tier bits, per-line
  graft slot bits), saved with the hero like the Dungeon Captives ledger.

All rows are always generated. Only `policy.enabled` grants Transcribe through the faction skill and
renames the skill, so the rows stay inert until the runtime has an in-game check.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
POLICY_PATH = REPO_ROOT / "custom_factions" / "tower_artificing" / "artificing_policy.json"
CATALOG_PATH = REPO_ROOT / "custom_factions" / "tower_artificing" / "schematic_catalog.json"
TRANSCRIBE_BUFFS_PATH = "DB/buffs/sub_skills_battle_hero_ability_buffs.json"
HERO_ABILITIES_PATH = "DB/heroes_abilities/heroes_abilities_base/hero_abilities.json"
COMBAT_BUFF_LANG_PATHS = ("Lang/english/texts/magic_buff.json", "Lang/english/texts/unitsBuff.json")
HERO_BUFF_LANG_PATH = "Lang/english/texts/mapObjects.json"
HERO_SKILLS_LANG_PATH = "Lang/english/texts/heroSkills.json"
PAYLOAD_KEYS = ("data", "actions", "statOverrides")
# Helper rows (catalog `helpers`): buffs go with the graft buffs; the rest into the vanilla file of their kind.
HELPER_PATHS = {
    "buff": None,
    "side_buff": "DB/side_buffs/side_buff_base/side_buffs_skills.json",
    "side_buff_info": "DB/side_buffs/side_buff_infos/side_buff_infos_skills.json",
    "obstacle": "DB/field_objects/obstacles/obstacles_units.json",
    "hero_buff": "DB/heroes_buffs/heroes_buffs.json",
}
# Grafts that act out of battle or add abilities: their battle buff is a label, so dispelling it changes nothing.
MAP_RUNTIME_KEYS = ("heroBuff", "dailyGold", "abilities")
GRAFT_ICON = "magic_favorable_wind_effect_icon"
LEDGER_ICON = "skill_faction_homm3_tower"


def load_policy() -> dict[str, Any]:
    return json.loads(POLICY_PATH.read_text(encoding="utf-8"))


def load_catalog() -> dict[str, Any]:
    return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))


def artificing_enabled() -> bool:
    return bool(load_policy().get("enabled"))


def graftable_schematics(catalog: dict[str, Any]) -> list[dict[str, Any]]:
    return [row for row in catalog["schematics"] if row.get("graftable")]


def make_graft_buff_rows(policy: dict[str, Any], catalog: dict[str, Any]) -> list[dict[str, Any]]:
    """One row per graftable schematic, plus one per perUnit variant (same text, the carrier's own payload)."""
    graft = policy["graftBuff"]
    rows = []
    for schematic in graftable_schematics(catalog):
        sid = schematic["graftBuffSid"]
        base: dict[str, Any] = {
            "id": sid,
            "aiValue": 4000,
            "aiValuePerDuration": 0,
            "infinite": graft["infinite"],
            "icon": GRAFT_ICON,
            "name_": f"{sid}_name",
            "description_": f"{sid}_desc",
            "tags": ["positive", "homm3_tower_artificing_graft"],
            "isPositive": True,
            "addition": graft["addition"],
            "canDispel": graft["canDispel"],
            "xHomm3SourceSchematic": schematic["key"],
        }
        payload = {k: v for k, v in schematic["payload"].items() if k in PAYLOAD_KEYS}
        rows.append({**base, **payload})
        for variant in schematic.get("variants") or []:
            merged = {**payload, **{k: v for k, v in variant["payload"].items() if k in PAYLOAD_KEYS}}
            rows.append({**base, "id": variant["buffSid"], **merged, "xHomm3GraftCarrier": variant["unitSid"]})
    return rows


def make_helper_rows(catalog: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Curated extra rows by kind. Helper buffs share their graft's text and default to swap + dispellable."""
    out: dict[str, list[dict[str, Any]]] = {kind: [] for kind in HELPER_PATHS}
    for schematic in graftable_schematics(catalog):
        sid = schematic["graftBuffSid"]
        for helper in schematic.get("helpers") or []:
            row = dict(helper["row"])
            if helper["kind"] == "buff":
                positive = bool(row.get("isPositive"))
                row = {
                    "id": row["id"],
                    "aiValue": 0,
                    "aiValuePerDuration": 0,
                    "dontMimic": True,
                    "icon": GRAFT_ICON,
                    "name_": f"{sid}_name",
                    "description_": f"{sid}_desc",
                    "tags": ["positive" if positive else "negative", "homm3_tower_artificing_graft_helper"],
                    "addition": "swap",
                    "canDispel": True,
                    **row,
                    "xHomm3SourceSchematic": schematic["key"],
                }
            elif helper["kind"] == "side_buff":
                row = {"canDispel": False, **row}
            elif helper["kind"] == "hero_buff":
                # isDispellable: native hero-buff Remove drops only dispellable configs, and the reconcile must remove it.
                row = {
                    "id": row["id"],
                    "icon": LEDGER_ICON,
                    "name": f"{row['id']}_name",
                    "description": f"{row['id']}_desc",
                    "additionType": "LeftNew",
                    "isPositive": True,
                    "hidden": False,
                    "isDispellable": True,
                    **row,
                }
            out[helper["kind"]].append(row)
    return out


def make_transcribe_effect_buff_row(policy: dict[str, Any]) -> dict[str, Any]:
    transcribe = policy["transcribe"]
    sid = transcribe["effectBuffSid"]
    return {
        "id": sid,
        "aiValue": 0,
        "aiValuePerDuration": 0,
        "dontMimic": True,
        "maxDuration": 1,
        "icon": transcribe["effectIcon"],
        "name_": f"{sid}_name",
        "description_": f"{sid}_description",
        "tags": ["homm3_tower_artificing_transcribe"],
        "isPositive": False,
        "addition": "duration",
        "canDispel": False,
        "data": {"stats": {}},
    }


def make_transcribe_hero_ability(policy: dict[str, Any]) -> dict[str, Any]:
    """Native buff_ability shape (Borrowed Time donor) with an any-side single target."""
    transcribe = policy["transcribe"]
    sid = transcribe["abilitySid"]
    target_params = {
        "targetTags": ["unit"],
        "castTarget_": transcribe["castTarget"],
        "targetCondition_": "alive",
        "selection": "object",
    }
    return {
        "id": sid,
        "levels": [
            {
                "aiValue": 0,
                "name": f"{sid}_name",
                "description": f"{sid}_description",
                "icon": transcribe["icon"],
                "casterEffect": "magic/Prefabs_vfx/Heroes/hero_nature_book_ability_hex",
                "attackTimeBefore": 0.3,
                "attackTimeAfter": 1.5,
                "cd": transcribe["cooldown"],
                "charges": -1,
                "energyLevel": transcribe["focus"],
                "useExpandTooltip": "false",
                "attackType_": "cast",
                "damageDealer": {
                    "tags": ["ability", "buff_ability"],
                    "attackPatternSid": "attack_single_buff",
                    "castTargetParams": dict(target_params),
                    "affectTargetParams": dict(target_params),
                    "damageTarget_": "none",
                    "buffTarget_": transcribe["castTarget"],
                    "buff": {"sid": transcribe["effectBuffSid"], "duration": 1},
                },
            }
        ],
        "xHomm3ImplementedMechanics": (
            "Transcribe (Artificing): marks any living stack with a 1-round marker buff. "
            "Homm3TowerArtificingRuntime sees the marker added and writes that unit's graftable "
            "schematics into the caster's Schematic Book. aiValue 0: AI heroes do not cast it."
        ),
    }


def ledger_buff_sids(policy: dict[str, Any], catalog: dict[str, Any]) -> list[str]:
    ledger = policy["ledger"]
    sids = [f"{ledger['essenceBitPrefix']}{bit}" for bit in range(policy["essence"]["bits"])]
    for schematic in graftable_schematics(catalog):
        sids += [f"{ledger['schematicBitPrefix']}{schematic['index']}_bit_{bit}" for bit in range(ledger["schematicTierBits"])]
    for line in range(ledger["lines"]):
        for slot in range(ledger["maxSlots"]):
            sids += [f"{ledger['graftBitPrefix']}l{line}_s{slot}_bit_{bit}" for bit in range(ledger["graftIndexBits"])]
    return sids


def make_ledger_hero_buff_rows(policy: dict[str, Any], catalog: dict[str, Any]) -> list[dict[str, Any]]:
    # Hidden and bonus-less. isDispellable must stay true: native hero-buff Remove only drops dispellable
    # configs (Homm3DungeonCaptivesRuntime.SetBuff), so a non-dispellable bit could never be cleared.
    return [
        {
            "id": sid,
            "icon": LEDGER_ICON,
            "name": "homm3_tower_artificing_ledger_name",
            "description": "homm3_tower_artificing_ledger_description",
            "additionType": "LeftNew",
            "isPositive": True,
            "hidden": True,
            "isDispellable": True,
            "bonuses": [],
        }
        for sid in ledger_buff_sids(policy, catalog)
    ]


def combat_buff_lang_rows(policy: dict[str, Any], catalog: dict[str, Any]) -> list[dict[str, str]]:
    effect = policy["transcribe"]["effectBuffSid"]
    rows = [
        {"sid": f"{effect}_name", "text": "Transcribed"},
        {"sid": f"{effect}_description", "text": "An Artificer copied this creature's passive abilities into a Schematic Book."},
    ]
    for schematic in graftable_schematics(catalog):
        description = schematic.get("graftDescription")
        if not isinstance(description, str) or re.search(r"\{\d+\}", description):
            raise RuntimeError(f"graftable schematic {schematic['key']} has no resolved graftDescription: {description!r}")
        map_graft = any((schematic.get("runtime") or {}).get(k) for k in MAP_RUNTIME_KEYS)
        suffix = "(Artificing graft.)" if map_graft else "(Artificing graft; can be dispelled.)"
        rows += [
            {"sid": f"{schematic['graftBuffSid']}_name", "text": f"Graft: {schematic['displayName']}"},
            {"sid": f"{schematic['graftBuffSid']}_desc", "text": f"{description} {suffix}"},
        ]
    return rows


def hero_buff_lang_rows(catalog: dict[str, Any]) -> list[dict[str, str]]:
    rows = [
        {"sid": "homm3_tower_artificing_ledger_name", "text": "Artificing Ledger"},
        {"sid": "homm3_tower_artificing_ledger_description", "text": "Arcane Essence, Schematic Book and graft records."},
    ]
    for schematic in graftable_schematics(catalog):
        for helper in schematic.get("helpers") or []:
            if helper["kind"] == "hero_buff":
                sid = helper["row"]["id"]
                rows += [
                    {"sid": f"{sid}_name", "text": f"Graft: {schematic['displayName']}"},
                    {"sid": f"{sid}_desc", "text": f"{schematic['graftDescription']} (Artificing graft.)"},
                ]
    return rows


def hero_skill_lang_rows(policy: dict[str, Any]) -> list[dict[str, str]]:
    transcribe = policy["transcribe"]
    sid = transcribe["abilitySid"]
    return [
        {"sid": f"{sid}_name", "text": "Transcribe"},
        {
            "sid": f"{sid}_description",
            "text": "Copy the passive abilities of target creature, friend or foe, into this hero's Schematic Book.",
        },
    ]


def faction_skill_levels(policy: dict[str, Any]) -> list[list[dict[str, Any]]]:
    sid = policy["transcribe"]["abilitySid"]
    return [[{"type": "heroBattleAbility", "parameters": [sid, "0"]}] for _ in range(3)]


def faction_skill_texts(policy: dict[str, Any]) -> tuple[str, str]:
    slots = policy["graftSlotsByRank"]
    implemented = (
        "Artificing: every rank grants the Transcribe hero action. Won battles add Arcane Essence per defeated "
        "enemy creature by tier; essence buys grafts of Schematic Book passives onto Tower unit lines "
        f"({slots[0]}/{slots[1]}/{slots[2]} per line at Basic/Advanced/Expert). Homm3TowerArtificingRuntime "
        "owns the ledger and applies grafts as dispellable battle buffs at battle start. Runtime unproven."
    )
    source_difference = (
        "Artificing replaces Arcane Battery. Grafts are native buff rows carrying the source passive's own "
        "mechanics, so they can be purged."
    )
    return implemented, source_difference


def faction_skill_lang(policy: dict[str, Any]) -> tuple[str, str, list[str]]:
    slots = policy["graftSlotsByRank"]
    description = (
        "Tower heroes Transcribe creature passives, friend or foe, into a Schematic Book, and spend Arcane Essence "
        "from won battles to graft them onto Tower units. Grafts are battle buffs and can be dispelled."
    )
    rank_descs = [
        f"Transcribe (2 Focus) copies a creature's passives. Up to {count} graft{'s' if count != 1 else ''} per Tower unit line."
        for count in slots
    ]
    return policy["factionSkillName"], description, rank_descs


def merge_tower_artificing_into_overlay(release_zip, output, notes, helpers) -> None:
    """helpers: read_overlay_or_release_json, write_json, upsert_array_row, dedupe_array_rows_by_id,
    add_lang_overlay_rows (passed in to avoid importing the overlay module)."""
    policy = load_policy()
    catalog = load_catalog()
    read_doc = helpers["read_overlay_or_release_json"]
    write_json = helpers["write_json"]
    upsert = helpers["upsert_array_row"]
    dedupe = helpers["dedupe_array_rows_by_id"]
    add_lang = helpers["add_lang_overlay_rows"]

    def merge_rows(path: str, rows: list[dict[str, Any]], label: str) -> None:
        doc = read_doc(release_zip, output, path)
        if not isinstance(doc, dict) or not isinstance(doc.get("array"), list):
            raise RuntimeError(f"malformed homm3_tower Artificing target {path}")
        changed = False
        for row in rows:
            changed = upsert(doc, row) or changed
        changed = dedupe(doc) or changed
        if changed:
            output[path] = write_json(doc)
            notes.append(f"merge homm3_tower Artificing {label} ({len(rows)} rows) into {path}")

    # Load-bearing for the runtime: fail closed (no warn-and-continue), like Dungeon Captives.
    helpers_by_kind = make_helper_rows(catalog)
    merge_rows(policy["graftBuff"]["path"], make_graft_buff_rows(policy, catalog) + helpers_by_kind.pop("buff"), "graft buffs")
    for kind, rows in helpers_by_kind.items():
        if rows:
            merge_rows(HELPER_PATHS[kind], rows, f"graft {kind} helpers")
    merge_rows(TRANSCRIBE_BUFFS_PATH, [make_transcribe_effect_buff_row(policy)], "Transcribe marker buff")
    merge_rows(HERO_ABILITIES_PATH, [make_transcribe_hero_ability(policy)], "Transcribe hero action")
    merge_rows(policy["ledger"]["heroBuffsPath"], make_ledger_hero_buff_rows(policy, catalog), "ledger hero buffs")
    for path in COMBAT_BUFF_LANG_PATHS:
        add_lang(release_zip, output, path, combat_buff_lang_rows(policy, catalog), notes)
    add_lang(release_zip, output, HERO_BUFF_LANG_PATH, hero_buff_lang_rows(catalog), notes)
    add_lang(release_zip, output, HERO_SKILLS_LANG_PATH, hero_skill_lang_rows(policy), notes)
