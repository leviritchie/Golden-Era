#!/usr/bin/env python3
"""Build an event test checklist for every Complete Edition H3C campaign mission.

Covers all 20 official campaigns (8 RoE + 6 AB + 6 SoD) from local Complete LODs:
H3bitmap.lod and H3ab_bmp.lod. HotA Factory and H3HD are excluded.

Proof boundary: source/static live H3C decode → CampaignEventIR inventory only.
Does not prove generated emit, installed payload, or runtime event behavior.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

RESOURCE_NAMES = ("wood", "mercury", "ore", "sulfur", "crystal", "gems", "gold")

# Stable mission IDs already used by StoryHub / RoE manifests.
ROE_MISSION_ID_BY_KEY: dict[tuple[str, int], str] = {
    ("Good1.h3c", 1): "homecoming",
    ("Good1.h3c", 2): "guardian_angels",
    ("Good1.h3c", 3): "griffin_cliff",
    ("Good2.h3c", 1): "steadwick_liberation",
    ("Good2.h3c", 2): "deal_with_the_devil",
    ("Good2.h3c", 3): "neutral_affairs",
    ("Good2.h3c", 4): "tunnels_and_troglodytes",
    ("Good3.h3c", 1): "safe_passage",
    ("Good3.h3c", 2): "united_front",
    ("Good3.h3c", 3): "for_king_and_country",
    ("EVIL1.H3C", 1): "a_devilish_plan",
    ("EVIL1.H3C", 2): "groundbreaking",
    ("EVIL1.H3C", 3): "steadwicks_fall",
    ("Evil2.h3c", 1): "a_gryphons_heart",
    ("Evil2.h3c", 2): "season_of_harvest",
    ("Evil2.h3c", 3): "corporeal_punishment",
    ("Evil2.h3c", 4): "from_day_to_night",
    ("Secret.h3c", 1): "poison_fit_for_a_king",
    ("Secret.h3c", 2): "to_build_a_tunnel",
    ("Secret.h3c", 3): "kreegan_alliance",
    ("Secret.h3c", 4): "with_blinders_on",
    ("Secret1.h3c", 1): "the_grail",
    ("Secret1.h3c", 2): "independence",
    ("Secret1.h3c", 3): "the_road_home",
    ("Neutral1.h3c", 1): "neutral_1a",
    ("Neutral1.h3c", 2): "neutral_1b",
    ("Neutral1.h3c", 3): "neutral_1c",
}


@dataclass(frozen=True)
class CampaignSpec:
    expansion: str
    hub: str
    campaign_entry: str
    campaign_title: str


# Complete Edition official set: 20 campaigns. Source is Complete H3C, not H3HD.
COMPLETE_CAMPAIGNS: tuple[CampaignSpec, ...] = (
    CampaignSpec("roe", "good1", "Good1.h3c", "Long Live the Queen"),
    CampaignSpec("roe", "good2", "Good2.h3c", "Liberation"),
    CampaignSpec("roe", "good3", "Good3.h3c", "Song for the Father"),
    CampaignSpec("roe", "evil1", "EVIL1.H3C", "Dungeons and Devils"),
    CampaignSpec("roe", "evil2", "Evil2.h3c", "Long Live the King"),
    CampaignSpec("roe", "neutral1", "Neutral1.h3c", "Spoils of War"),
    CampaignSpec("roe", "secret1", "Secret1.h3c", "Seeds of Discontent"),
    CampaignSpec("roe", "secret", "Secret.h3c", "Specter of Power"),
    CampaignSpec("ab", "ab", "ab.h3c", "Armageddon's Blade"),
    CampaignSpec("ab", "blood", "blood.h3c", "Dragon's Blood"),
    CampaignSpec("ab", "slayer", "slayer.h3c", "Dragon Slayer"),
    CampaignSpec("ab", "festival", "festival.h3c", "Festival of Life"),
    CampaignSpec("ab", "fire", "fire.h3c", "Playing with Fire"),
    CampaignSpec("ab", "fool", "fool.h3c", "Foolhardy Waywardness"),
    CampaignSpec("sod", "sandro", "Sandro.h3c", "Rise of the Necromancer"),
    CampaignSpec("sod", "crag", "Crag.h3c", "Hack and Slash"),
    CampaignSpec("sod", "yog", "Yog.h3c", "Birth of a Barbarian"),
    CampaignSpec("sod", "gem", "Gem.h3c", "New Beginning"),
    CampaignSpec("sod", "gelu", "Gelu.h3c", "Elixir of Life"),
    CampaignSpec("sod", "final", "Final.h3c", "Unholy Alliance"),
)


def slugify_mission_id(display_name: str) -> str:
    text = display_name.strip().lower()
    text = text.replace("'", "").replace("'", "")
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return text.strip("_") or "mission"


def mission_id_for(campaign_entry: str, block_index: int, display_name: str) -> str:
    pinned = ROE_MISSION_ID_BY_KEY.get((campaign_entry, block_index))
    if pinned:
        return pinned
    return slugify_mission_id(display_name)


def fmt_resources(resources: Any) -> str:
    parts: list[str] = []
    for name, value in zip(RESOURCE_NAMES, resources or []):
        v = int(value or 0)
        if v:
            parts.append(f"{v:+d} {name}")
    return ", ".join(parts) if parts else "—"


def fmt_schedule(schedule: Any) -> str:
    if schedule is None:
        return "visit"
    day = schedule.trigger_day
    if schedule.is_repeating:
        return f"day {day}, every {schedule.next_occurrence}d"
    return f"day {day}"


def message_snippet(text: str, limit: int = 90) -> str:
    one = " ".join((text or "").split())
    if not one:
        return "(no message)"
    if len(one) <= limit:
        return one
    return one[: limit - 1] + "…"


def event_kind(event: Any) -> str:
    if event.scope.value == "map":
        return "guarded map" if event.has_guards else "unguarded map"
    if event.scope.value == "town":
        return "town timed"
    if event.is_player_briefing:
        return "briefing"
    if event.is_timed_resource_grant:
        return "timed resource"
    return "global timed"


def extra_effects(event: Any) -> str:
    bits: list[str] = []
    non_res = event.effects.non_resource_nonzero()
    if non_res:
        bits.append("non-resource: " + ", ".join(non_res))
    if event.has_guards:
        stacks = ", ".join(
            f"type{s.creature_type}x{s.count}" for s in event.guard_stacks
        )
        bits.append(f"guards: {stacks or 'empty'}")
    if event.remove_after_visit is False:
        bits.append("removeAfterVisit=false")
    elif event.remove_after_visit is True:
        bits.append("removeAfterVisit=true")
    if event.host.town_name:
        bits.append(f"town={event.host.town_name}")
    if event.readiness_blockers:
        bits.append("blockers: " + "; ".join(event.readiness_blockers))
    return " | ".join(bits)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument(
        "--json-out",
        type=Path,
        default=Path(
            "artifacts/campaign_port_poc/complete_campaign_event_test_inventory.v1.json"
        ),
    )
    parser.add_argument(
        "--md-out",
        type=Path,
        default=Path(
            "docs/plans/2026-07-16-complete-campaign-event-test-checklist.md"
        ),
    )
    args = parser.parse_args()
    repo_root = args.repo_root.resolve()
    sys.path.insert(0, str(repo_root / "experiments" / "campaign_port_poc"))

    import campaign_event_ir as event_ir
    import h3m_object_walk as walk_engine
    import port_homecoming_poc as poc
    from h3c_mission_source import load_h3c_block, resolve_h3c_lod_path

    if len(COMPLETE_CAMPAIGNS) != 20:
        raise SystemExit(
            f"expected 20 Complete campaigns; catalog has {len(COMPLETE_CAMPAIGNS)}"
        )

    mission_rows: list[dict[str, Any]] = []
    census_rows: list[Any] = []

    for campaign in COMPLETE_CAMPAIGNS:
        lod_path = resolve_h3c_lod_path(campaign.campaign_entry)
        compressed = poc.read_lod_entry(lod_path, campaign.campaign_entry)
        blocks = poc.split_concatenated_gzip_members(compressed)
        if len(blocks) < 2:
            raise SystemExit(
                f"{campaign.campaign_entry}: expected header + mission blocks; got {len(blocks)}"
            )
        mission_block_indexes = [block.index for block in blocks if block.index >= 1]
        print(
            f"OK campaign {campaign.campaign_entry}: "
            f"{len(mission_block_indexes)} missions from {lod_path.name}"
        )
        for block_index in mission_block_indexes:
            source = load_h3c_block(campaign.campaign_entry, block_index)
            display_name = (source.summary.title or "").strip() or f"block_{block_index}"
            mission_id = mission_id_for(
                campaign.campaign_entry, block_index, display_name
            )
            walk = walk_engine.walk_objects(
                source.h3m_data,
                source.summary,
                source.templates,
                walk_engine.make_source_metadata(
                    extra={
                        "campaignEntry": campaign.campaign_entry,
                        "blockIndex": block_index,
                        "missionId": mission_id,
                        "h3mSha256": source.h3m_sha256,
                        "lodPath": str(source.lod_path),
                    }
                ),
            )
            census = event_ir.build_mission_event_census_from_walk(
                mission_id=mission_id,
                campaign_entry=campaign.campaign_entry,
                block_index=block_index,
                h3m_sha256=source.h3m_sha256,
                walk=walk,
            )
            census_rows.append(census)
            mission_rows.append(
                {
                    "expansion": campaign.expansion,
                    "hub": campaign.hub,
                    "campaignEntry": campaign.campaign_entry,
                    "campaignTitle": campaign.campaign_title,
                    "blockIndex": block_index,
                    "missionId": mission_id,
                    "displayName": display_name,
                    "lodPath": str(source.lod_path),
                    "h3mVersion": int(source.summary.version),
                    "census": census,
                }
            )
            print(
                f"  OK {mission_id}: {len(census.events)} events "
                f"({display_name})"
            )

    batch = event_ir.BatchEventCensus(missions=tuple(census_rows))
    if len({row["campaignEntry"] for row in mission_rows}) != 20:
        raise SystemExit("campaign count drifted from Complete Edition set of 20")

    json_out = args.json_out if args.json_out.is_absolute() else repo_root / args.json_out
    json_out.parent.mkdir(parents=True, exist_ok=True)
    payload = batch.to_dict()
    payload["title"] = (
        "HoMM3 Complete Edition campaign event test inventory (20 campaigns)"
    )
    payload["proofBoundary"] = (
        "source/static live Complete H3C decode → EventIR; not runtime/gameplay proof"
    )
    payload["sourcePolicy"] = {
        "lodArchives": [
            str(poc.LOD_PATH),
            str(resolve_h3c_lod_path("ab.h3c")),
        ],
        "excluded": ["H3HD", "HotA Factory / HotA_lng.lod"],
        "campaignCount": 20,
        "missionCount": len(mission_rows),
        "eventCount": len(batch.events),
    }
    # Enrich mission dicts with display metadata.
    by_identity = {(m.mission_id, m.campaign_entry, m.block_index): m for m in census_rows}
    enriched_missions: list[dict[str, Any]] = []
    for row in mission_rows:
        census = row["census"]
        mission_dict = census.to_dict()
        mission_dict.update(
            {
                "expansion": row["expansion"],
                "hub": row["hub"],
                "campaignTitle": row["campaignTitle"],
                "displayName": row["displayName"],
                "lodPath": row["lodPath"],
                "h3mVersion": row["h3mVersion"],
            }
        )
        enriched_missions.append(mission_dict)
        _ = by_identity  # keep for clarity / future checks
    payload["missions"] = enriched_missions
    payload["missionCount"] = len(mission_rows)
    payload["eventCount"] = len(batch.events)
    payload["campaignCount"] = 20
    json_out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {json_out} ({payload['eventCount']} events)")

    # Markdown checklist
    lines: list[str] = [
        "# HoMM3 Complete Campaign Event Test Checklist",
        "",
        "Date: 2026-07-16",
        "",
        "Status: source/static inventory from live **HoMM3 Complete** H3C decode via "
        "`CampaignEventIR`. Not runtime or installed-payload proof.",
        "",
        "Scope: all **20** official Complete Edition campaigns "
        "(8 RoE + 6 Armageddon's Blade + 6 Shadow of Death), every global timed event, "
        "map EVENT object, and town event.",
        "",
        "Source LOD policy:",
        "",
        f"- RoE + SoD: `{poc.LOD_PATH}`",
        f"- AB: `{resolve_h3c_lod_path('ab.h3c')}`",
        "- Excluded: H3HD (incomplete expansion set), HotA Factory",
        "",
        "Machine inventory: "
        "`artifacts/campaign_port_poc/complete_campaign_event_test_inventory.v1.json`",
        "",
        "Regenerate:",
        "",
        "```powershell",
        "$env:PYTHONUTF8='1'",
        "python tools/build_roe_campaign_event_test_inventory.py --repo-root .",
        "```",
        "",
        "## How to use",
        "",
        "- Check off each event after confirming the listed Olden behavior in-game.",
        "- Identity key is `sourceIdentity` (stable for the same H3C).",
        "- Day numbers are H3 trigger days (`firstOccurrence + 1`). Map events fire on "
        "visit at `layer:x:y`.",
        "- Events with readiness blockers may still appear in IR while emit is incomplete.",
        "",
        "## Summary",
        "",
        "| Expansion | Campaign | Mission | Global | Map | Town | Total |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: |",
    ]

    total_events = 0
    for row in mission_rows:
        census = row["census"]
        total_events += len(census.events)
        lines.append(
            f"| {row['expansion']} | {row['campaignTitle']} | {row['displayName']} "
            f"(`{row['missionId']}`) | {census.global_count} | {census.map_count} | "
            f"{census.town_count} | {len(census.events)} |"
        )
    lines.append(
        f"| | **{len({r['campaignEntry'] for r in mission_rows})} campaigns / "
        f"{len(mission_rows)} missions** | | | | | **{total_events}** |"
    )
    lines.append("")

    current_campaign = None
    for row in mission_rows:
        if row["campaignTitle"] != current_campaign:
            current_campaign = row["campaignTitle"]
            lines.append(
                f"## {row['campaignTitle']} "
                f"(`{row['expansion']}` / `{row['campaignEntry']}`)"
            )
            lines.append("")
        census = row["census"]
        lines.append(f"### {row['displayName']} (`{row['missionId']}`)")
        lines.append("")
        lines.append(
            f"Source: `{row['campaignEntry']}` block {row['blockIndex']} · "
            f"H3M v{row['h3mVersion']} · {len(census.events)} events · "
            f"sha256 `{census.h3m_sha256[:12]}…` · LOD `{Path(row['lodPath']).name}`"
        )
        lines.append("")

        def sort_key(event: Any) -> tuple[Any, ...]:
            scope_ord = {"global": 0, "map": 1, "town": 2}[event.scope.value]
            day = event.schedule.trigger_day if event.schedule else 10**9
            return (scope_ord, day, event.source_key, event.source_identity)

        for event in sorted(census.events, key=sort_key):
            kind = event_kind(event)
            when = fmt_schedule(event.schedule)
            loc = ""
            if event.scope.value == "map":
                loc = f" @ `{event.source_key}`"
            elif event.scope.value == "town":
                loc = f" @ `{event.source_key}` ({event.host.town_name or 'town'})"
            name = event.name.strip() or "(unnamed)"
            msg = message_snippet(event.effects.message)
            extra = extra_effects(event)
            backend = (
                event.selected_backend.value if event.selected_backend else "none"
            )
            lines.append(f"- [ ] `{event.source_identity}`")
            lines.append(
                f"  - **{name}** · {kind} · {when}{loc} · "
                f"resources: {fmt_resources(event.effects.resources)}"
            )
            lines.append(f"  - message: {msg}")
            if extra:
                lines.append(f"  - notes: {extra}")
            lines.append(f"  - backend: {backend} ({event.backend_status.value})")
        lines.append("")

    md_out = args.md_out if args.md_out.is_absolute() else repo_root / args.md_out
    md_out.parent.mkdir(parents=True, exist_ok=True)
    md_out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {md_out}")
    print(
        f"TOTAL campaigns=20 missions={len(mission_rows)} events={total_events}"
    )

    # Replace the earlier RoE-only checklist with a pointer so links don't go stale.
    legacy = repo_root / "docs/plans/2026-07-16-roe-campaign-event-test-checklist.md"
    legacy.write_text(
        "\n".join(
            [
                "# RoE Campaign Event Test Checklist (superseded)",
                "",
                "This RoE-only checklist is superseded by the Complete Edition inventory:",
                "",
                "- [`2026-07-16-complete-campaign-event-test-checklist.md`]"
                "(2026-07-16-complete-campaign-event-test-checklist.md)",
                "",
                "That file covers all 20 Complete campaigns (RoE + AB + SoD) decoded from "
                "local Complete H3C LODs, not H3HD.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    print(f"Updated pointer at {legacy}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
