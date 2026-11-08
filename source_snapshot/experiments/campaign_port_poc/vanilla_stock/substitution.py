"""Stock projection of the copied Golden Era substitution table.

The table is consulted before the legacy stock mapper. Only replacement SIDs
that are not present in the stock Core are adjusted here; custom SIDs with no
explicit stock policy remain fail-closed.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import native_only_stock as native


SCHEMA = "homm3.vanilla_stock.copied_substitution_table.v1"


class StockSubstitutionTableError(ValueError):
    """Raised when the copied substitution table is malformed or unsafe."""


def _pair_for_record(record: dict[str, Any]) -> tuple[int, str]:
    try:
        template_id = int(record["templateObjectId"])
    except (KeyError, TypeError, ValueError) as ex:
        raise StockSubstitutionTableError(f"record has no valid templateObjectId: {record}") from ex
    return template_id, str(record.get("templateAnimation") or "")


def _kind_for(entry: dict[str, Any], sid: str) -> str:
    category = str(entry.get("category") or "")
    if category == "scenery_blocker":
        return "scenery"
    if category == "town" or sid in {
        "human_city",
        "nature_city",
        "demon_city",
        "undead_city",
        "dungeon_city",
        "random-city",
    }:
        return "town"
    if category == "map_event" or sid == "fx_quest_mark_gold_01":
        return "map_event"
    if category == "mine" or sid.startswith("mine_") or sid == "alchemy_lab":
        return "mine"
    if category in {"travel_link_candidate", "boat_or_water_travel_object"} or sid.startswith("portal"):
        return "portal"
    if category == "monster_stack" or sid == "random-squad":
        return "random_squad"
    if category == "external_dwelling" or sid.startswith("barracks_"):
        return "dwelling"
    if category == "resource_pickup" or sid.startswith("resource_"):
        return "resource"
    return "interactable"


@dataclass(frozen=True)
class StockSubstitutionTable:
    path: Path
    source_schema: str
    source_status: str
    source_artifact: str
    entries_by_pair: dict[tuple[int, str], dict[str, Any]]
    ambiguous_pairs: frozenset[tuple[int, str]]

    @property
    def entry_count(self) -> int:
        return len(self.entries_by_pair)

    def manifest(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA,
            "path": str(self.path),
            "sourceSchema": self.source_schema,
            "sourceStatus": self.source_status,
            "sourceArtifact": self.source_artifact,
            "entryCount": self.entry_count,
            "ambiguousTemplateAnimationCount": len(self.ambiguous_pairs),
            "customSidPolicy": "native_only_stock_explicit_remap_or_block",
            "proofBoundary": "copied_substitution_table_loaded_static_only",
        }

    def resolve(self, record: dict[str, Any], stock_object_ids: set[str]) -> dict[str, Any] | None:
        pair = _pair_for_record(record)
        if pair in self.ambiguous_pairs:
            return {
                "action": "miss",
                "reason": "copied_substitution_pair_ambiguous",
                "templateObjectId": pair[0],
                "templateAnimation": pair[1],
            }
        entry = self.entries_by_pair.get(pair)
        if entry is None:
            return None

        source_sid = str(entry["replacementSid"])
        classification = native.classify_object_sid(source_sid, stock_object_ids)
        action = classification.get("action")
        if action == "keep":
            replacement = source_sid
            custom_policy = "not_custom_stock_sid"
        elif action == "remap":
            replacement = str(classification["remappedSid"])
            custom_policy = "custom_sid_explicit_stock_remap"
        elif action == "block":
            return {
                "action": "omit",
                "reason": f"copied_substitution_custom_sid_blocked_{classification.get('reason')}",
                "customSid": source_sid,
                "ruleName": entry.get("ruleName"),
                "templateObjectId": pair[0],
                "templateAnimation": pair[1],
            }
        else:
            raise StockSubstitutionTableError(
                f"unsupported stock classification for copied replacement {source_sid!r}: {classification}"
            )

        if replacement not in stock_object_ids:
            raise StockSubstitutionTableError(
                f"copied substitution target is absent from stock Core: {source_sid!r} -> {replacement!r}"
            )

        decision: dict[str, Any] = {
            "action": "emit",
            "sid": replacement,
            "reason": f"copied_substitution_table_{entry.get('ruleName') or 'unlabeled'}",
            "kind": _kind_for(entry, replacement),
            "substitutionTableMatch": "template_animation",
            "substitutionSourceSid": source_sid,
            "substitutionCustomPolicy": custom_policy,
        }
        if decision["kind"] == "scenery":
            fill_sid = entry.get("footprintFillSid")
            if not isinstance(fill_sid, str) or fill_sid not in stock_object_ids:
                raise StockSubstitutionTableError(
                    f"scenery substitution {pair!r} has no stock footprintFillSid: {fill_sid!r}"
                )
            decision["footprintFillSid"] = fill_sid
            if "sourceBlockCount" in entry:
                decision["expectedSourceBlockCount"] = int(entry["sourceBlockCount"])
        if decision["kind"] == "town":
            decision["factionSid"] = {
                "human_city": "human",
                "nature_city": "nature",
                "demon_city": "demon",
                "undead_city": "undead",
                "dungeon_city": "dungeon",
            }.get(replacement)
        return decision


def load_substitution_table(path: Path) -> StockSubstitutionTable:
    if not path.is_file():
        raise StockSubstitutionTableError(f"copied substitution table not found: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as ex:
        raise StockSubstitutionTableError(f"cannot read copied substitution table {path}: {ex}") from ex
    if payload.get("schema") != SCHEMA:
        raise StockSubstitutionTableError(
            f"copied substitution table schema mismatch: {payload.get('schema')!r} != {SCHEMA!r}"
        )
    entries = payload.get("entries")
    if not isinstance(entries, list) or not entries:
        raise StockSubstitutionTableError("copied substitution table has no entries")

    candidates: dict[tuple[int, str], list[dict[str, Any]]] = defaultdict(list)
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("replacementSid"), str):
            raise StockSubstitutionTableError(f"invalid copied substitution row: {entry}")
        pair = _pair_for_record(entry)
        candidates[pair].append(entry)

    selected: dict[tuple[int, str], dict[str, Any]] = {}
    ambiguous: set[tuple[int, str]] = set()
    for pair, rows in candidates.items():
        replacements = {str(row["replacementSid"]) for row in rows}
        if len(replacements) > 1:
            ambiguous.add(pair)
            continue
        selected[pair] = rows[0]

    return StockSubstitutionTable(
        path=path,
        source_schema=str(payload.get("sourceSchema") or ""),
        source_status=str(payload.get("sourceStatus") or ""),
        source_artifact=str(payload.get("sourceArtifact") or ""),
        entries_by_pair=selected,
        ambiguous_pairs=frozenset(ambiguous),
    )
