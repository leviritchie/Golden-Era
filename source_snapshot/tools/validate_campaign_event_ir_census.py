#!/usr/bin/env python3
"""Fail-closed source census for CampaignEventIR across RoE Castle missions.

Proof boundary: source/static live H3C decode → EventIR inventory only.
Does not prove generated emit, installed payload, or runtime event behavior.

Default mode requires delivery readiness (currently expected to FAIL until
backends are proven). Use --census-only to validate complete IR inventory
without requiring proven backends.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def require(condition: bool, message: str, errors: list[str]) -> None:
    if not condition:
        errors.append(message)


def _verify_field_fidelity(
    *,
    mission_census: Any,
    walk: dict[str, Any],
    errors: list[str],
) -> None:
    mission_id = mission_census.mission_id
    by_identity = {event.source_identity: event for event in mission_census.events}

    gte = walk.get("globalTimedEvents") or {}
    for raw in gte.get("events") or []:
        index = int(raw["index"])
        identity = f"{mission_id}:global:{index}"
        event = by_identity.get(identity)
        require(event is not None, f"{identity}: missing from EventIR census", errors)
        if event is None:
            continue
        require(
            event.audience.players_mask == int(raw["playersMask"]),
            f"{identity}: playersMask mismatch {event.audience.players_mask} != {raw['playersMask']}",
            errors,
        )
        require(
            event.schedule is not None
            and event.schedule.first_occurrence == int(raw["firstOccurrence"])
            and event.schedule.next_occurrence == int(raw["nextOccurrence"]),
            f"{identity}: schedule mismatch",
            errors,
        )
        require(
            event.effects.message == str(raw.get("message") or ""),
            f"{identity}: message mismatch",
            errors,
        )
        require(
            list(event.effects.resources) == list(raw.get("resources") or [0] * 7),
            f"{identity}: resources mismatch",
            errors,
        )

    for record in walk.get("records") or []:
        if record.get("payloadKind") == "event":
            source_key = str(record["key"])
            identity = f"{mission_id}:map:{source_key}"
            event = by_identity.get(identity)
            require(event is not None, f"{identity}: missing from EventIR census", errors)
            if event is None:
                continue
            box = record.get("boxContent") or {}
            mg = box.get("messageAndGuards") or {}
            rewards = box.get("rewards") or {}
            require(
                event.audience.players_mask == int(record["playersMask"]),
                f"{identity}: playersMask mismatch",
                errors,
            )
            require(
                event.audience.computer_eligible == bool(record.get("computerActivate")),
                f"{identity}: computerActivate mismatch",
                errors,
            )
            require(
                event.audience.human_eligible == bool(record.get("humanActivate", True)),
                f"{identity}: humanActivate mismatch",
                errors,
            )
            require(
                event.remove_after_visit == bool(record.get("removeAfterVisit")),
                f"{identity}: removeAfterVisit mismatch",
                errors,
            )
            require(
                event.has_guards == bool(mg.get("hasGuards")),
                f"{identity}: hasGuards mismatch",
                errors,
            )
            require(
                event.effects.message == str(mg.get("message") or ""),
                f"{identity}: message mismatch",
                errors,
            )
            require(
                list(event.effects.resources) == list((rewards.get("resources") or [0] * 7)),
                f"{identity}: resources mismatch",
                errors,
            )
            if event.has_guards:
                decoded_stacks = [
                    (s.creature_type, s.count)
                    for s in event.guard_stacks
                ]
                raw_stacks = []
                for stack in mg.get("guardStacks") or []:
                    creature_type = int(stack["creatureType"])
                    count = int(stack["count"])
                    if count > 0 and creature_type not in {0xFF, 0xFFFF}:
                        raw_stacks.append((creature_type, count))
                require(
                    decoded_stacks == raw_stacks,
                    f"{identity}: guardStacks mismatch {decoded_stacks} != {raw_stacks}",
                    errors,
                )

        for event_index, town_event in enumerate(record.get("townEvents") or []):
            town_key = str(record["key"])
            identity = f"{mission_id}:town:{town_key}:event:{event_index}"
            event = by_identity.get(identity)
            require(event is not None, f"{identity}: missing from EventIR census", errors)
            if event is None:
                continue
            require(
                event.audience.players_mask == int(town_event["players"]),
                f"{identity}: players mask mismatch",
                errors,
            )
            require(
                event.schedule is not None
                and event.schedule.first_occurrence == int(town_event["firstOccurrence"])
                and event.schedule.next_occurrence == int(town_event["nextOccurrence"]),
                f"{identity}: schedule mismatch",
                errors,
            )
            require(
                list(event.effects.resources) == list(town_event.get("resources") or [0] * 7),
                f"{identity}: resources mismatch",
                errors,
            )
            require(
                event.host.town_name == (str(record.get("name") or "") or None),
                f"{identity}: town host name mismatch",
                errors,
            )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument(
        "--manifest",
        default="scenarios/roe_castle_campaign/batch_manifest.json",
        help="Batch manifest relative to repo root",
    )
    parser.add_argument(
        "--census-only",
        action="store_true",
        help="Validate complete IR inventory/field fidelity without requiring delivery-ready backends",
    )
    parser.add_argument(
        "--json-out",
        type=Path,
        default=None,
        help="Optional path to write the full batch census JSON",
    )
    args = parser.parse_args()
    repo_root = args.repo_root.resolve()
    sys.path.insert(0, str(repo_root / "experiments" / "campaign_port_poc"))

    import campaign_event_ir as event_ir
    import h3m_object_walk as walk_engine
    from campaign_mission import load_batch_manifest
    from h3c_mission_source import load_h3c_block

    errors: list[str] = []
    manifest = load_batch_manifest((repo_root / args.manifest).resolve())
    mission_summaries: list[dict[str, Any]] = []
    batch_missions: list[Any] = []

    for mission in manifest.missions:
        mission_id = mission.mission_id
        expected = event_ir.EXPECTED_EVENT_CENSUS.get(mission_id)
        if expected is None:
            errors.append(f"{mission_id}: missing EXPECTED_EVENT_CENSUS pin")
            continue

        source = load_h3c_block(mission.campaign_entry, mission.block_index)
        walk = walk_engine.walk_objects(
            source.h3m_data,
            source.summary,
            source.templates,
            walk_engine.make_source_metadata(
                extra={
                    "campaignEntry": mission.campaign_entry,
                    "blockIndex": mission.block_index,
                    "missionId": mission_id,
                    "h3mSha256": source.h3m_sha256,
                }
            ),
        )
        census = event_ir.build_mission_event_census_from_walk(
            mission_id=mission_id,
            campaign_entry=mission.campaign_entry,
            block_index=mission.block_index,
            h3m_sha256=source.h3m_sha256,
            walk=walk,
        )
        batch_missions.append(census)

        require(
            census.global_count == expected["global"],
            f"{mission_id}: expected {expected['global']} global events; got {census.global_count}",
            errors,
        )
        require(
            census.map_count == expected["map"],
            f"{mission_id}: expected {expected['map']} map events; got {census.map_count}",
            errors,
        )
        require(
            census.town_count == expected["town"],
            f"{mission_id}: expected {expected['town']} town events; got {census.town_count}",
            errors,
        )
        require(
            census.player_briefing_count == expected["playerBriefings"],
            f"{mission_id}: expected {expected['playerBriefings']} player briefings; "
            f"got {census.player_briefing_count}",
            errors,
        )
        require(
            census.timed_resource_grant_count == expected["timedResourceGrants"],
            f"{mission_id}: expected {expected['timedResourceGrants']} timed resource grants; "
            f"got {census.timed_resource_grant_count}",
            errors,
        )

        # No decoded source event may be absent from IR.
        decoded_global = int((walk.get("globalTimedEvents") or {}).get("eventCount") or 0)
        decoded_map = sum(1 for row in (walk.get("records") or []) if row.get("payloadKind") == "event")
        decoded_town = sum(len(row.get("townEvents") or []) for row in (walk.get("records") or []))
        require(
            len(census.events) == decoded_global + decoded_map + decoded_town,
            f"{mission_id}: IR event count {len(census.events)} != decoded "
            f"{decoded_global}+{decoded_map}+{decoded_town}",
            errors,
        )

        _verify_field_fidelity(mission_census=census, walk=walk, errors=errors)

        # Audience sides must be zero-based H3 identities in IR.
        for event in census.events:
            for index in event.audience.zero_based_player_indices:
                require(
                    0 <= index <= 7,
                    f"{event.source_identity}: zero-based player index out of range: {index}",
                    errors,
                )
            derived = tuple(
                i for i in range(8) if event.audience.players_mask & (1 << i)
            )
            require(
                event.audience.zero_based_player_indices == derived,
                f"{event.source_identity}: zero-based indices drift from players_mask",
                errors,
            )

        mission_summaries.append(
            {
                "missionId": mission_id,
                "counts": {
                    "total": len(census.events),
                    "global": census.global_count,
                    "map": census.map_count,
                    "town": census.town_count,
                    "playerBriefings": census.player_briefing_count,
                    "timedResourceGrants": census.timed_resource_grant_count,
                },
                "readinessBlockerCount": len(census.readiness_blockers),
                "sampleBlockers": list(census.readiness_blockers[:8]),
            }
        )

    batch = event_ir.BatchEventCensus(missions=tuple(batch_missions))
    if args.json_out is not None:
        out_path = args.json_out if args.json_out.is_absolute() else repo_root / args.json_out
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(batch.to_dict(), indent=2) + "\n", encoding="utf-8")

    delivery_ready = len(batch.readiness_blockers) == 0
    if not args.census_only and not delivery_ready:
        errors.append(
            f"delivery readiness FAIL: {len(batch.readiness_blockers)} blocker(s) across "
            f"{len(batch.events)} events (use --census-only for inventory-only PASS)"
        )
        for blocker in batch.readiness_blockers[:20]:
            errors.append(f"  blocker: {blocker}")
        if len(batch.readiness_blockers) > 20:
            errors.append(f"  blocker: ... +{len(batch.readiness_blockers) - 20} more")

    if errors:
        print("Campaign EventIR census contract FAIL")
        for error in errors:
            print(f"- {error}")
        return 1

    mode = "census-only" if args.census_only else "delivery-ready"
    print(f"Campaign EventIR census contract PASS ({mode})")
    print(
        json.dumps(
            {
                "manifest": args.manifest,
                "mode": mode,
                "missionCount": len(mission_summaries),
                "eventCount": len(batch.events),
                "readinessBlockerCount": len(batch.readiness_blockers),
                "missions": mission_summaries,
                "proofBoundary": (
                    "source/static live H3C decode → CampaignEventIR inventory and "
                    "field fidelity; delivery backends remain unproven unless "
                    "readinessBlockerCount is 0"
                ),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
