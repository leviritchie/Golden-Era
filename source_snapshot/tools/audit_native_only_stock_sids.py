#!/usr/bin/env python3
"""Audit HoMM3→Olden SIDs against stock (non-Golden-Era) Core.zip.

Produces an opt-in proof artifact. Does not emit maps or modify the GE Homecoming path.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
POC = REPO / "experiments" / "campaign_port_poc"
if str(POC) not in sys.path:
    sys.path.insert(0, str(POC))

import native_only_stock as native  # noqa: E402

DEFAULT_STOCK_CORE = Path(
    r"V:/SteamLibrary/steamapps/common/Heroes of Might and Magic Olden Era"
    r"/HeroesOldenEra_Data/StreamingAssets/Core.zip"
)
DEFAULT_GE_CORE = Path(
    r"V:/SteamLibrary/steamapps/common/Heroes of Might and Magic Olden Era - Golden Era"
    r"/HeroesOldenEra_Data/StreamingAssets/Core.zip"
)
DEFAULT_SUBSTITUTION = (
    REPO
    / "artifacts"
    / "campaign_port_poc"
    / "homecoming_poc"
    / "entity_substitutions"
    / "homecoming.olden_entity_substitution_map.json"
)
DEFAULT_OUT = (
    REPO / "artifacts" / "campaign_port_poc" / "native_only" / "homecoming.native_only_stock_audit.json"
)

HOMECOMING_SPAWN_FACTIONS = ("homm3_castle", "homm3_dungeon", "homm3_inferno")
HOMECOMING_SPAWN_HEROES = ("homm3_castle_hero_7", "homm3_inferno_hero_10")


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stock-core", type=Path, default=DEFAULT_STOCK_CORE)
    parser.add_argument("--ge-core", type=Path, default=DEFAULT_GE_CORE)
    parser.add_argument("--substitution-map", type=Path, default=DEFAULT_SUBSTITUTION)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    if not args.stock_core.is_file():
        raise SystemExit(f"stock Core.zip not found: {args.stock_core}")
    if not args.substitution_map.is_file():
        raise SystemExit(f"substitution map not found: {args.substitution_map}")

    stock_objects = native.load_core_object_ids(args.stock_core)
    stock_factions = native.load_core_faction_ids(args.stock_core)
    ge_objects = native.load_core_object_ids(args.ge_core) if args.ge_core.is_file() else set()

    substitution = json.loads(args.substitution_map.read_text(encoding="utf-8-sig"))
    histogram = substitution.get("replacementSidHistogram")
    if not isinstance(histogram, dict):
        raise SystemExit("substitution map missing replacementSidHistogram object")

    object_audit = native.audit_replacement_histogram(
        {str(k): int(v) for k, v in histogram.items()},
        stock_object_ids=stock_objects,
        extra_sids=native.KNOWN_EMIT_EXTRA_OBJECT_SIDS,
    )

    faction_rows = [
        native.classify_faction_sid(sid, stock_factions) for sid in HOMECOMING_SPAWN_FACTIONS
    ]
    ge_only_objects = sorted(ge_objects - stock_objects) if ge_objects else []

    # After proposed remaps, which substitution instances still block?
    post_remap_blocked = []
    for row in object_audit["rows"]:
        if row["action"] == "keep":
            continue
        if row["action"] == "remap":
            continue
        if row["count"] == 0 and row["sid"] not in native.STOCK_OBJECT_SID_BLOCKED:
            # extras with zero substitution hits still matter for emit policy
            if row["sid"] in native.KNOWN_EMIT_EXTRA_OBJECT_SIDS and row["action"] == "block":
                post_remap_blocked.append(row)
            continue
        if row["action"] == "block":
            post_remap_blocked.append(row)

    verdict = {
        "sceneryAndMostAdventureBuildings": "feasible_stock",
        "lossyPlayableWithTownCollapse": "conditionally_feasible",
        "faithfulHomm3FactionsUnitsHeroes": "impossible_without_golden_era",
        "boatsAsCurrentlyEmitted": "blocked_no_stock_boat_sid",
        "coreOverlayEmit": "forbidden_for_native_only",
    }

    blockers = [row["sid"] for row in post_remap_blocked]
    # Boat is the hard substitution blocker for Homecoming water objects.
    if "homm3_boat" in blockers or any(r["sid"] == "homm3_boat" for r in object_audit["blockedNonZero"]):
        loadable_after_remap = False
        loadable_reason = "homm3_boat_has_no_stock_objectconfig_fail_closed"
    elif any(r["action"] == "block" for r in faction_rows):
        loadable_after_remap = False
        loadable_reason = "spawn_faction_blocked"
    else:
        # Pathing blocker / extras may still appear at emit time.
        emit_extra_blocks = [
            sid
            for sid in native.KNOWN_EMIT_EXTRA_OBJECT_SIDS
            if native.classify_object_sid(sid, stock_objects)["action"] == "block"
        ]
        loadable_after_remap = len(emit_extra_blocks) == 0 and not object_audit["blockedNonZero"]
        loadable_reason = (
            "substitution_histogram_clear_after_remap"
            if loadable_after_remap
            else f"emit_extras_or_histogram_still_block:{emit_extra_blocks or [r['sid'] for r in object_audit['blockedNonZero']]}"
        )

    payload = {
        "schema": native.SCHEMA,
        "status": native.STATUS,
        "proofBoundary": (
            "source/static Core.zip inventory + generated-artifact substitution audit; "
            "no map emit; stock-install load unvalidated"
        ),
        "inputs": {
            "stockCore": str(args.stock_core),
            "geCore": str(args.ge_core) if args.ge_core.is_file() else None,
            "substitutionMap": str(args.substitution_map),
        },
        "coreInventory": {
            "stockObjectConfigCount": len(stock_objects),
            "geObjectConfigCount": len(ge_objects),
            "geOnlyObjectConfigCount": len(ge_only_objects),
            "geOnlyObjectConfigSample": ge_only_objects[:40],
            "stockFactionIds": sorted(stock_factions),
        },
        "verdict": verdict,
        "substitutionObjectAudit": object_audit,
        "spawnFactionAudit": faction_rows,
        "spawnHeroNote": {
            "heroes": list(HOMECOMING_SPAWN_HEROES),
            "status": "blocked_without_lossy_stock_hero_table",
            "reason": "stock_core_has_zero_homm3_hero_sids",
        },
        "unitNote": {
            "status": "blocked_without_lossy_stock_unit_table",
            "reason": "stock_core_has_zero_h3_unit_files_concrete_stacks_need_remap_or_random_squad",
        },
        "loadableAfterProposedObjectRemap": {
            "substitutionHistogramOnly": loadable_after_remap,
            "reason": loadable_reason,
            "remainingBlockedRows": post_remap_blocked,
        },
        "recommendedNextEmitFlags": {
            "emitPolicy.mode": "native_only_stock_core",
            "pathability.emitCoreOverlay": False,
            "spawn.factionSid": "human",
            "featuredCities.useStockCitySids": True,
            "forbidHomm3ObjectSids": True,
        },
        "planDoc": "docs/plans/2026-07-12-native-only-homm3-scenario-feasibility.md",
    }
    write_json(args.out, payload)
    print(f"wrote {args.out}")
    print(
        "stock_objects={stock} ge_only={ge_only} subst_keep={keep} subst_remap={remap} subst_block={block}".format(
            stock=len(stock_objects),
            ge_only=len(ge_only_objects),
            keep=object_audit["actionHistogram"].get("keep", 0),
            remap=object_audit["actionHistogram"].get("remap", 0),
            block=object_audit["actionHistogram"].get("block", 0),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
