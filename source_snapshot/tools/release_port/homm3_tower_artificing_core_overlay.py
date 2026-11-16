"""Core rows for the Tower Artificing faction skill (design: docs/homm3_tower_artificing.md).

Inputs are custom_factions/tower_artificing/artificing_policy.json and the generated
schematic_catalog.json (tools/tower_artificing/build_schematic_catalog.py). Rows:

- one dispellable, battle-long graft buff per graftable schematic (the passive's own data/actions/
  statOverrides, so the native buff system runs it and native purge removes it), plus one variant row per
  carrier for perUnit schematics (godslayer / duelist / phoenix; the runtime picks it by unit sid);
- the curated helper rows the grafts reference (`{graft}_*` aura/debuff/faction buffs, side buffs + infos,
  phoenix heart obstacles), each into the vanilla file of its kind;
- the Artificing world spell (a clone of the native Necromancer Will row with [mode] parameters;
  Homm3TowerArtificingRuntime intercepts the cast and opens the graft picker);
- visible hero map buffs for map grafts (`hero_buff` helpers: the native unit-set bonus, held while a carrier
  is in the army; Homm3TowerArtificingRuntime reconciles them);
- hidden hero map buffs that hold the ledger (essence bits, per-schematic source-tier bits, per-line
  graft slot bits), saved with the hero like the Dungeon Captives ledger.

All rows are always generated. Only `policy.enabled` grants the world spell through the faction skill and
renames the skill, so the rows stay inert while Artificing is disabled.
"""
from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
POLICY_PATH = REPO_ROOT / "custom_factions" / "tower_artificing" / "artificing_policy.json"
CATALOG_PATH = REPO_ROOT / "custom_factions" / "tower_artificing" / "schematic_catalog.json"
NECROMANCY_MAGIC_SID = "change_use_necromancy"
MAGIC_LANG_PATHS = ("Lang/english/texts/magic.json", "Lang/english/texts/magics.json")
MAGIC_LANG_ARGS_PATH = "Lang/args/magic.json"
COMBAT_BUFF_LANG_PATHS = ("Lang/english/texts/magic_buff.json", "Lang/english/texts/unitsBuff.json")
HERO_BUFF_LANG_PATH = "Lang/english/texts/mapObjects.json"
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


def make_graft_magic_row(policy: dict[str, Any], source_rows: list[Any]) -> dict[str, Any]:
    """Clone of the native Necromancer Will world magic; the runtime intercepts its [mode] parameters."""
    spell = policy["graftSpell"]
    base = next((r for r in source_rows if isinstance(r, dict) and r.get("id") == NECROMANCY_MAGIC_SID), None)
    if not isinstance(base, dict):
        raise RuntimeError(f"missing Artificing magic source {NECROMANCY_MAGIC_SID}")
    sid = spell["magicSid"]
    row = copy.deepcopy(base)
    row.update(
        {
            "id": sid,
            "name": f"{sid}_name",
            "icon": spell["icon"],
            "description": [f"{sid}_description"] * 4,
            "bonusDescriptions": [],
            "upEffectDescription": "",
            "manaCost": [0, 0, 0, 0],
            "upgradeCost": [0],
            "rank": 1,
            "school_": "neutral",
            "usedOnMap": True,
            "xHomm3RuntimeHook": (
                "Artificing reuses the native Necromancer Will world-magic handler; Homm3TowerArtificingRuntime "
                "intercepts the [mode] parameter row, suppresses the native toggle and opens the graft picker."
            ),
        }
    )
    world_magic = row.get("worldMagic")
    settings = world_magic.get("magicSettings") if isinstance(world_magic, dict) else None
    if not isinstance(settings, list) or not settings:
        raise RuntimeError(f"malformed Artificing magic source {NECROMANCY_MAGIC_SID}")
    world_magic["settingPerLevels"] = [0, 0, 0, 0]
    for setting in settings:
        if isinstance(setting, dict):
            setting["mechType"] = NECROMANCY_MAGIC_SID
            setting["parameters"] = [spell["mode"]]
            setting["usageLimit"] = -1
            setting["castInfoSid"] = f"{sid}_cast"
    return row


def magic_lang_rows(policy: dict[str, Any]) -> list[dict[str, str]]:
    sid = policy["graftSpell"]["magicSid"]
    return [
        {"sid": f"{sid}_name", "text": "Artificing"},
        {
            "sid": f"{sid}_description",
            "text": (
                "Open the Schematic Book and spend Arcane Essence to graft a learned creature passive onto a "
                "Tower unit line. Free; usable any time on the adventure map."
            ),
        },
        {"sid": f"{sid}_cast", "text": "The Schematic Book opens."},
    ]


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
    rows: list[dict[str, str]] = []
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


def faction_skill_levels(policy: dict[str, Any]) -> list[list[dict[str, Any]]]:
    sid = policy["graftSpell"]["magicSid"]
    return [[{"type": "heroMagicAddition", "parameters": [sid, "false"]}] for _ in range(3)]


def faction_skill_texts(policy: dict[str, Any]) -> tuple[str, str]:
    slots = policy["graftSlotsByRank"]
    chances = policy["observation"]["chanceByRank"]
    implemented = (
        "Artificing: at the end of every battle (fought or auto-resolved) the hero rolls once per distinct "
        f"graftable passive in the enemy army ({chances[0]}/{chances[1]}/{chances[2]}% by rank) to write it into the "
        "Schematic Book. Won battles add Arcane Essence per defeated enemy creature by tier. Every rank grants the "
        "Artificing world spell, whose picker spends essence on grafts of Schematic Book passives onto Tower unit "
        f"lines ({slots[0]}/{slots[1]}/{slots[2]} per line at Basic/Advanced/Expert). Homm3TowerArtificingRuntime "
        "owns the ledger and applies grafts as dispellable battle buffs at battle start."
    )
    source_difference = (
        "Artificing replaces Arcane Battery. Grafts are native buff rows carrying the source passive's own "
        "mechanics, so they can be purged."
    )
    return implemented, source_difference


def faction_skill_lang(policy: dict[str, Any]) -> tuple[str, str, list[str]]:
    slots = policy["graftSlotsByRank"]
    chances = policy["observation"]["chanceByRank"]
    description = (
        "After each battle, Tower heroes may learn the passive abilities of enemy creatures into a Schematic Book. "
        "Defeated enemies yield Arcane Essence, spent with the Artificing spell to graft learned passives onto "
        "Tower units. Grafts are battle buffs and can be dispelled. Artificing can be accessed through a world map "
        "spell."
    )
    # User 2026-11-13: the Chronomancy / Borrowed Time hint is redundant (the subskill describes itself); dropped
    # from the skill and rank texts.
    rank_descs = [
        f"{chance}% chance per enemy passive to learn it after each battle. "
        f"Up to {count} graft{'s' if count != 1 else ''} per Tower unit line."
        for chance, count in zip(chances, slots)
    ]
    return policy["factionSkillName"], description, rank_descs


def merge_tower_artificing_into_overlay(release_zip, output, notes, helpers) -> None:
    """helpers: read_overlay_or_release_json, write_json, upsert_array_row, dedupe_array_rows_by_id,
    add_lang_overlay_rows, add_lang_args_overlay_rows (passed in to avoid importing the overlay module)."""
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
    magic_path = policy["graftSpell"]["path"]
    magic_doc = read_doc(release_zip, output, magic_path)
    if not isinstance(magic_doc, dict) or not isinstance(magic_doc.get("array"), list):
        raise RuntimeError(f"malformed homm3_tower Artificing magic source {magic_path}")
    merge_rows(magic_path, [make_graft_magic_row(policy, magic_doc["array"])], "graft world spell")
    merge_rows(policy["ledger"]["heroBuffsPath"], make_ledger_hero_buff_rows(policy, catalog), "ledger hero buffs")
    for path in COMBAT_BUFF_LANG_PATHS:
        add_lang(release_zip, output, path, combat_buff_lang_rows(policy, catalog), notes)
    add_lang(release_zip, output, HERO_BUFF_LANG_PATH, hero_buff_lang_rows(catalog), notes)
    for path in MAGIC_LANG_PATHS:
        add_lang(release_zip, output, path, magic_lang_rows(policy), notes)
    helpers["add_lang_args_overlay_rows"](
        release_zip, output, MAGIC_LANG_ARGS_PATH, [{"sid": row["sid"], "args": []} for row in magic_lang_rows(policy)], notes
    )
