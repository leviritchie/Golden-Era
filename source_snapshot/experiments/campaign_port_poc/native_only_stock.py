#!/usr/bin/env python3
"""Stock-native (non-Golden-Era) SID policy for opt-in HoMM3 scenario emits.

"Stock-native" means SIDs present in base Olden Core.zip ObjectConfig / factions /
heroes / units — not zone-atlas "native" (non-landon) which still uses homm3_* SIDs.

This module is intentionally fail-closed and side-effect free: remaps are explicit,
unmapped GE SIDs stay blocked, and emit wiring stays opt-in.
"""

from __future__ import annotations

import json
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

SCHEMA = "homm3.native_only_stock_audit.v1"
STATUS = "audit_only_emit_unwired_runtime_unvalidated"

# Lossy town/dwelling remaps for the GE SIDs Homecoming currently emits.
# Factions without a stock counterpart are omitted here on purpose (fail-closed).
STOCK_OBJECT_SID_REMAP: dict[str, str] = {
    "homm3_landon_castle_city": "human_city",
    "homm3_castle_city": "human_city",
    "homm3_landon_dungeon_city": "dungeon_city",
    "homm3_dungeon_city": "dungeon_city",
    "homm3_necropolis_city": "undead_city",
    "homm3_inferno_city": "demon_city",
    "homm3_rampart_city": "nature_city",
    "homm3_landon_barracks_castle_1": "barracks_human_1",
    "homm3_landon_barracks_castle_2": "barracks_human_2",
    "homm3_landon_barracks_castle_3": "barracks_human_3",
    "homm3_landon_barracks_castle_4": "barracks_human_4",
    "homm3_landon_barracks_castle_5": "barracks_human_5",
    "barracks_homm3_castle_1": "barracks_human_1",
    "barracks_homm3_castle_2": "barracks_human_2",
    "barracks_homm3_castle_3": "barracks_human_3",
    "barracks_homm3_castle_4": "barracks_human_4",
    "barracks_homm3_castle_5": "barracks_human_5",
    "barracks_homm3_castle_6": "barracks_human_6",
    "barracks_homm3_castle_7": "barracks_human_7",
    "barracks_homm3_dungeon_1": "barracks_dungeon_1",
    "barracks_homm3_dungeon_2": "barracks_dungeon_2",
    "barracks_homm3_dungeon_3": "barracks_dungeon_3",
    "barracks_homm3_dungeon_4": "barracks_dungeon_4",
    "barracks_homm3_dungeon_5": "barracks_dungeon_5",
    "barracks_homm3_dungeon_6": "barracks_dungeon_6",
    "barracks_homm3_dungeon_7": "barracks_dungeon_7",
    "homm3_landon_map_event_marker": "fx_quest_mark_gold_01",
    "homm3_subterranean_gate_portal": "portal_5",
    "homm3_flotsam_pickup": "resource_wood",
    "homm3_random_resource_pickup": "random-res",
}

# Explicit blocks: no honest stock ObjectConfig exists yet (or identity cannot be preserved).
STOCK_OBJECT_SID_BLOCKED: dict[str, str] = {
    "homm3_boat": "stock_core_has_no_boat_objectconfig",
    "homm3_pathing_blocker": "pathing_overlay_requires_ge_or_stock_scenery_policy_rewrite",
    "homm3_envelope_padding_blocker": "envelope_blocker_is_ge_overlay_only",
}

STOCK_FACTION_SID_REMAP: dict[str, str] = {
    "homm3_castle": "human",
    "homm3_dungeon": "dungeon",
    "homm3_necropolis": "undead",
    "homm3_inferno": "demon",
    "homm3_rampart": "nature",
}

STOCK_FACTION_SID_BLOCKED: dict[str, str] = {
    "homm3_tower": "no_stock_faction_counterpart",
    "homm3_stronghold": "no_stock_faction_counterpart",
    "homm3_fortress": "no_stock_faction_counterpart",
    "homm3_conflux": "no_stock_faction_counterpart",
    "homm3_cove": "no_stock_faction_counterpart",
}

# Known emit SIDs that appear outside the substitution histogram (overlays / travel).
KNOWN_EMIT_EXTRA_OBJECT_SIDS: tuple[str, ...] = (
    "homm3_subterranean_gate_portal",
    "homm3_random_resource_pickup",
    "homm3_pathing_blocker",
    "homm3_boat",
    "homm3_flotsam_pickup",
)


def load_core_object_ids(core_zip: Path) -> set[str]:
    ids: set[str] = set()
    with zipfile.ZipFile(core_zip) as archive:
        for member in archive.namelist():
            if not (member.startswith("DB/map/objects/") and member.endswith(".json")):
                continue
            payload = json.loads(archive.read(member).decode("utf-8-sig"))
            rows = payload.get("array") if isinstance(payload, dict) else None
            if not isinstance(rows, list):
                continue
            for row in rows:
                if isinstance(row, dict) and isinstance(row.get("id"), str):
                    ids.add(row["id"])
    return ids


def load_core_faction_ids(core_zip: Path) -> set[str]:
    ids: set[str] = set()
    with zipfile.ZipFile(core_zip) as archive:
        for member in archive.namelist():
            if not (member.startswith("DB/fractions/") and member.endswith(".json")):
                continue
            payload = json.loads(archive.read(member).decode("utf-8-sig"))
            rows = payload.get("array") if isinstance(payload, dict) else None
            if not isinstance(rows, list):
                continue
            for row in rows:
                if isinstance(row, dict) and isinstance(row.get("id"), str):
                    ids.add(row["id"])
    return ids


def classify_object_sid(sid: str, stock_object_ids: set[str]) -> dict[str, Any]:
    if not isinstance(sid, str) or not sid:
        return {"sid": sid, "class": "invalid", "action": "block", "reason": "empty_sid"}
    if sid.startswith("homm3_pathing_visual_"):
        return {
            "sid": sid,
            "class": "ge_pathing_visual_clone",
            "action": "block",
            "reason": "pathing_visual_clones_require_ge_overlay_or_scenery_policy_rewrite",
        }
    if sid in STOCK_OBJECT_SID_BLOCKED:
        return {
            "sid": sid,
            "class": "ge_blocked",
            "action": "block",
            "reason": STOCK_OBJECT_SID_BLOCKED[sid],
        }
    if sid in stock_object_ids:
        return {"sid": sid, "class": "stock", "action": "keep", "reason": "present_in_stock_core"}
    remapped = STOCK_OBJECT_SID_REMAP.get(sid)
    if remapped is not None:
        if remapped not in stock_object_ids:
            return {
                "sid": sid,
                "class": "ge_remap_target_missing",
                "action": "block",
                "reason": f"remap_target_missing_from_stock:{remapped}",
                "remappedSid": remapped,
            }
        return {
            "sid": sid,
            "class": "ge_remappable",
            "action": "remap",
            "reason": "explicit_lossy_stock_remap",
            "remappedSid": remapped,
        }
    if "homm3" in sid or sid.startswith("h3_"):
        return {
            "sid": sid,
            "class": "ge_unmapped",
            "action": "block",
            "reason": "ge_or_h3_sid_without_stock_remap",
        }
    return {
        "sid": sid,
        "class": "unknown_not_in_stock",
        "action": "block",
        "reason": "sid_absent_from_stock_objectconfig",
    }


def classify_faction_sid(sid: str, stock_faction_ids: set[str]) -> dict[str, Any]:
    if sid in stock_faction_ids:
        return {"sid": sid, "class": "stock", "action": "keep", "reason": "present_in_stock_core"}
    if sid in STOCK_FACTION_SID_BLOCKED:
        return {
            "sid": sid,
            "class": "ge_blocked",
            "action": "block",
            "reason": STOCK_FACTION_SID_BLOCKED[sid],
        }
    remapped = STOCK_FACTION_SID_REMAP.get(sid)
    if remapped is not None:
        if remapped not in stock_faction_ids:
            return {
                "sid": sid,
                "class": "ge_remap_target_missing",
                "action": "block",
                "reason": f"remap_target_missing_from_stock:{remapped}",
                "remappedSid": remapped,
            }
        return {
            "sid": sid,
            "class": "ge_remappable",
            "action": "remap",
            "reason": "explicit_lossy_stock_faction_remap",
            "remappedSid": remapped,
        }
    return {
        "sid": sid,
        "class": "unknown_not_in_stock",
        "action": "block",
        "reason": "faction_absent_from_stock_core",
    }


def apply_object_remap(sid: str | None) -> str | None:
    if not isinstance(sid, str):
        return sid
    if sid in STOCK_OBJECT_SID_BLOCKED:
        return None
    return STOCK_OBJECT_SID_REMAP.get(sid, sid)


def audit_replacement_histogram(
    histogram: dict[str, int],
    *,
    stock_object_ids: set[str],
    extra_sids: Iterable[str] | None = None,
) -> dict[str, Any]:
    counts = Counter({str(sid): int(count) for sid, count in histogram.items() if isinstance(sid, str)})
    for sid in extra_sids or ():
        counts[str(sid)] += 0

    rows: list[dict[str, Any]] = []
    class_counts: Counter[str] = Counter()
    action_counts: Counter[str] = Counter()
    instance_by_action: Counter[str] = Counter()
    for sid, count in sorted(counts.items(), key=lambda item: (-item[1], item[0])):
        row = classify_object_sid(sid, stock_object_ids)
        row["count"] = count
        rows.append(row)
        class_counts[str(row["class"])] += 1
        action_counts[str(row["action"])] += 1
        instance_by_action[str(row["action"])] += count

    blocked = [row for row in rows if row["action"] == "block" and row["count"] > 0]
    remappable = [row for row in rows if row["action"] == "remap"]
    return {
        "distinctSidCount": len(rows),
        "instanceCount": sum(counts.values()),
        "classHistogram": dict(class_counts),
        "actionHistogram": dict(action_counts),
        "instanceActionHistogram": dict(instance_by_action),
        "blockedNonZero": blocked,
        "remappable": remappable,
        "rows": rows,
    }
