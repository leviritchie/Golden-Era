"""Core rows for the building pass (2026-11-22): Signal Beacon hero buff and two hidden store carriers.

The runtimes (Homm3CastleSignalBeaconRuntime, Homm3RampartWeeklyIncomeRuntime, Homm3DungeonManaVortexRuntime)
look these sids up by id; without the rows each one logs a warning and does nothing.
"""
from __future__ import annotations

import copy
from typing import Any

SIDE_BUFFS_PATH = "DB/logic_side_buffs/logic_side_buffs.json"
HERO_BUFFS_PATH = "DB/heroes_buffs/heroes_buffs.json"
BUFF_LANG_PATHS = ("Lang/english/texts/mapObjects.json", "Lang/english/texts/magic_buff.json")
STORE_SOURCE_SID = "heros_crypt_debuff_none"
BEACON_SOURCE_SID = "stable_buff"

BEACON_BUFF_SID = "homm3_signal_beacon_buff"
RAMPART_STORE_SID = "homm3_rampart_income_store"
IND_STORE_SID = "homm3_ind_town_building_store"

LANG_ROWS = [
    {"sid": f"{BEACON_BUFF_SID}_name", "text": "Signal Beacon"},
    {"sid": f"{BEACON_BUFF_SID}_description", "text": "+10% movement points (Signal Beacon)."},
    {"sid": f"{RAMPART_STORE_SID}_name", "text": "Weekly Income"},
    {"sid": f"{RAMPART_STORE_SID}_description", "text": "Weekly income records."},
    {"sid": f"{IND_STORE_SID}_name", "text": "Town Buildings"},
    {"sid": f"{IND_STORE_SID}_description", "text": "Town building records."},
]


def _find(rows: list[Any], sid: str) -> dict[str, Any]:
    base = next((r for r in rows if isinstance(r, dict) and r.get("id") == sid), None)
    if not isinstance(base, dict):
        raise RuntimeError(f"building pass: missing source row {sid}")
    return base


def _store_row(rows: list[Any], sid: str, hook: str) -> dict[str, Any]:
    row = copy.deepcopy(_find(rows, STORE_SOURCE_SID))
    row.update(
        {
            "id": sid,
            "name": f"{sid}_name",
            "description": f"{sid}_description",
            "hidden": True,
            "bonuses": [],
            "xHomm3RuntimeHook": hook,
        }
    )
    return row


def _beacon_row(rows: list[Any]) -> dict[str, Any]:
    row = copy.deepcopy(_find(rows, BEACON_SOURCE_SID))
    row.update(
        {
            "id": BEACON_BUFF_SID,
            "name": f"{BEACON_BUFF_SID}_name",
            "description": f"{BEACON_BUFF_SID}_description",
            "isPositive": True,
            "hidden": False,
            "bonuses": [{"type": "heroStat", "parameters": ["movementPerBonus", "0.10"]}],
        }
    )
    return row


def merge_building_pass_rows_into_overlay(release_zip, output, notes, helpers) -> None:
    """Fails closed: the town building runtimes need these rows."""
    read_doc = helpers["read_overlay_or_release_json"]
    write_json = helpers["write_json"]
    upsert = helpers["upsert_array_row"]
    dedupe = helpers["dedupe_array_rows_by_id"]

    def merge(path: str, build_rows) -> None:
        doc = read_doc(release_zip, output, path)
        if not isinstance(doc, dict) or not isinstance(doc.get("array"), list):
            raise RuntimeError(f"malformed building pass target {path}")
        changed = False
        for row in build_rows(doc["array"]):
            changed = upsert(doc, row) or changed
        changed = dedupe(doc) or changed
        if changed:
            output[path] = write_json(doc)
            notes.append(f"merge building pass rows into {path}")

    merge(
        SIDE_BUFFS_PATH,
        lambda rows: [
            _store_row(rows, RAMPART_STORE_SID, "Hidden, bonus-less carrier: Homm3RampartWeeklyIncomeRuntime keeps its weekly payment record here."),
            _store_row(rows, IND_STORE_SID, "Hidden, bonus-less carrier: Homm3DungeonManaVortexRuntime keeps its per-town records here."),
        ],
    )
    merge(HERO_BUFFS_PATH, lambda rows: [_beacon_row(rows)])
    for path in BUFF_LANG_PATHS:
        helpers["add_lang_overlay_rows"](release_zip, output, path, LANG_ROWS, notes)
