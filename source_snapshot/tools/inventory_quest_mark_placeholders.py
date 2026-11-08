#!/usr/bin/env python3
"""Inventory fx_quest_mark_gold_01 placeholders from interactive_quest_object rows.

Scans RoE Castle + RoE remaining + AB/SoD campaign batch manifests. Emits a
markdown/JSON inventory of every seer-hut / border-gate / quest-guard / etc.
placeholder that the entity substitution map turns into a gold question mark.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


TYPE_LABELS: dict[int, str] = {
    36: "Grail",
    83: "Seer Hut",
    212: "Border Gate",
    215: "Quest Guard",
}

DEFAULT_MANIFESTS = (
    "scenarios/roe_castle_campaign/batch_manifest.json",
    "scenarios/roe_remaining_campaigns/batch_manifest.json",
    "scenarios/ab_sod_campaigns/batch_manifest.json",
)


def count_gold_quest_marks(map_path: Path, map_reader: Any) -> int:
    container = map_reader(map_path)
    total = 0
    for group in container.chunks[1].get("objects") or []:
        if group.get("sid") == "fx_quest_mark_gold_01":
            total += len(group.get("ids") or [])
    return total


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument(
        "--manifest",
        action="append",
        dest="manifests",
        help="Campaign batch manifest (repeatable). Default: RoE Castle + RoE remaining + AB/SoD.",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=None,
        help="Output directory (default: artifacts/campaign_port_poc/quest_mark_placeholder_inventory)",
    )
    args = parser.parse_args()
    repo_root = args.repo_root.resolve()
    sys.path.insert(0, str(repo_root / "experiments" / "campaign_port_poc"))
    import port_homecoming_poc as poc

    manifest_rels = args.manifests or list(DEFAULT_MANIFESTS)
    out_dir = (args.out_dir or (repo_root / "artifacts/campaign_port_poc/quest_mark_placeholder_inventory")).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    missions: list[dict[str, Any]] = []
    campaigns: set[str] = set()
    for rel in manifest_rels:
        path = (repo_root / rel).resolve()
        doc = json.loads(path.read_text(encoding="utf-8"))
        for mission in doc.get("missions") or []:
            if not isinstance(mission, dict):
                continue
            title = str(mission.get("campaignTitle") or "?")
            campaigns.add(title)
            missions.append(
                {
                    **mission,
                    "family": path.parent.name,
                    "manifest": str(path.relative_to(repo_root)),
                }
            )

    rows: list[dict[str, Any]] = []
    mission_summary: list[dict[str, Any]] = []
    missing_align: list[str] = []
    gold_mismatch: list[dict[str, Any]] = []
    payload_by_type: Counter[tuple[Any, str, Any]] = Counter()
    type_by_campaign: dict[str, Counter[tuple[Any, str]]] = defaultdict(Counter)

    for mission in missions:
        mission_id = str(mission["missionId"])
        artifact_root = Path(str(mission["artifactRoot"]))
        if not artifact_root.is_absolute():
            artifact_root = repo_root / artifact_root
        align_dir = artifact_root / "olden_storage_alignment"
        align_path = align_dir / f"{mission_id}.olden_storage_alignment.json"
        if not align_path.is_file() and align_dir.is_dir():
            cands = sorted(align_dir.glob("*.olden_storage_alignment.json"))
            align_path = cands[0] if cands else align_path
        if not align_path.is_file():
            missing_align.append(mission_id)
            continue

        align = json.loads(align_path.read_text(encoding="utf-8"))
        interactive = [
            entity
            for entity in (align.get("globalEntities") or [])
            if isinstance(entity, dict) and entity.get("category") == "interactive_quest_object"
        ]

        map_dir = artifact_root / "raw_translation_map" / "maps"
        maps = (
            [path for path in sorted(map_dir.glob("*.map")) if "pre_visual" not in path.name]
            if map_dir.is_dir()
            else []
        )
        gold = count_gold_quest_marks(maps[0], poc.read_olden_map_container) if maps else None

        type_counts: Counter[tuple[Any, str, Any]] = Counter()
        campaign_title = str(mission.get("campaignTitle") or "?")
        for entity in interactive:
            template_id = entity.get("templateObjectId")
            payload = entity.get("payloadKind")
            label = TYPE_LABELS.get(int(template_id), f"object {template_id}") if isinstance(template_id, int) else f"object {template_id}"
            key = (template_id, label, payload)
            type_counts[key] += 1
            payload_by_type[key] += 1
            type_by_campaign[campaign_title][(template_id, label)] += 1
            rows.append(
                {
                    "family": mission["family"],
                    "campaign": campaign_title,
                    "missionId": mission_id,
                    "title": mission.get("title") or mission_id,
                    "sourceKey": entity.get("sourceKey"),
                    "templateObjectId": template_id,
                    "templateSubtype": entity.get("templateSubtype"),
                    "payloadKind": payload,
                    "animation": entity.get("templateAnimation"),
                    "label": label,
                    "alignmentSid": entity.get("sid"),
                }
            )

        iq_n = len(interactive)
        if gold is not None and gold != iq_n:
            gold_mismatch.append(
                {"missionId": mission_id, "gold": gold, "interactiveQuestObjects": iq_n}
            )
        if iq_n:
            mission_summary.append(
                {
                    "family": mission["family"],
                    "campaign": campaign_title,
                    "missionId": mission_id,
                    "title": mission.get("title") or mission_id,
                    "count": iq_n,
                    "gold": gold,
                    "types": {
                        f"{tid}|{label}|{payload}": count
                        for (tid, label, payload), count in type_counts.items()
                    },
                }
            )

    lines: list[str] = [
        "# Gold quest-mark placeholder inventory",
        "",
        "Source/static + generated-artifact inventory of `fx_quest_mark_gold_01` placeholders",
        "emitted for `interactive_quest_object` (seer huts, border gates, quest guards, etc.).",
        "Map events are separate and use invisible Zone markers; they are not counted here.",
        "",
        f"- Campaigns scanned: {len(campaigns)}",
        f"- Missions scanned: {len(missions) - len(missing_align)}",
        f"- Placeholder instances: {len(rows)}",
        f"- Missions with ≥1 placeholder: {len(mission_summary)}",
        "",
        "## Global type totals",
        "",
        "| Count | H3 object | Label | payloadKind |",
        "| --- | --- | --- | --- |",
    ]
    for (tid, label, payload), count in sorted(
        payload_by_type.items(), key=lambda item: (-item[1], item[0][0] or 0)
    ):
        lines.append(f"| {count} | {tid} | {label} | {payload} |")

    lines.extend(["", "## By campaign", "", "| Campaign | Total | Breakdown |", "| --- | --- | --- |"])
    for camp in sorted(type_by_campaign):
        total = sum(type_by_campaign[camp].values())
        parts = ", ".join(
            f"{count}× {label}"
            for (_tid, label), count in sorted(type_by_campaign[camp].items(), key=lambda item: -item[1])
        )
        lines.append(f"| {camp} | {total} | {parts} |")

    lines.extend(["", "## By mission", ""])
    for camp in sorted({row["campaign"] for row in mission_summary}):
        lines.append(f"### {camp}")
        lines.append("")
        for summary in sorted(
            [row for row in mission_summary if row["campaign"] == camp],
            key=lambda row: row["missionId"],
        ):
            lines.append(f"#### {summary['missionId']} ({summary['count']})")
            lines.append("")
            lines.append("| Count | H3 object | What it is | payloadKind |")
            lines.append("| --- | --- | --- | --- |")
            agg: Counter[tuple[Any, str, Any]] = Counter()
            for row in rows:
                if row["missionId"] != summary["missionId"]:
                    continue
                agg[(row["templateObjectId"], row["label"], row["payloadKind"])] += 1
            for (tid, label, payload), count in sorted(
                agg.items(), key=lambda item: (-item[1], item[0][0] or 0)
            ):
                lines.append(f"| {count}× | object {tid} | {label} | {payload} |")
            lines.append("")
            lines.append("| sourceKey | subtype | animation |")
            lines.append("| --- | --- | --- |")
            for row in sorted(
                [item for item in rows if item["missionId"] == summary["missionId"]],
                key=lambda item: (item["templateObjectId"] or 0, item["sourceKey"] or ""),
            ):
                lines.append(
                    f"| `{row['sourceKey']}` | {row['templateSubtype']} | `{row['animation']}` |"
                )
            lines.append("")

    md_path = out_dir / "QUEST_MARK_PLACEHOLDER_INVENTORY.md"
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    json_path = out_dir / "quest_mark_placeholder_inventory.json"
    payload = {
        "proofBoundary": (
            "source/static alignment interactive_quest_object rows + generated map "
            "fx_quest_mark_gold_01 count cross-check; runtime gameplay unproven"
        ),
        "campaignCount": len(campaigns),
        "campaigns": sorted(campaigns),
        "missionCountScanned": len(missions) - len(missing_align),
        "placeholderInstanceCount": len(rows),
        "missionsWithPlaceholders": len(mission_summary),
        "missingAlignments": missing_align,
        "goldIqMismatches": gold_mismatch,
        "globalTypeTotals": [
            {
                "count": count,
                "templateObjectId": tid,
                "label": label,
                "payloadKind": payload,
            }
            for (tid, label, payload), count in sorted(
                payload_by_type.items(), key=lambda item: (-item[1], item[0][0] or 0)
            )
        ],
        "byCampaign": [
            {
                "campaign": camp,
                "total": sum(type_by_campaign[camp].values()),
                "breakdown": [
                    {"count": count, "templateObjectId": tid, "label": label}
                    for (tid, label), count in sorted(
                        type_by_campaign[camp].items(), key=lambda item: -item[1]
                    )
                ],
            }
            for camp in sorted(type_by_campaign)
        ],
        "byMission": mission_summary,
        "instances": rows,
    }
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    print(f"campaigns={len(campaigns)} missions_scanned={len(missions) - len(missing_align)}")
    print(f"placeholder_instances={len(rows)} missions_with_placeholders={len(mission_summary)}")
    print(f"missing_alignments={len(missing_align)} gold_iq_mismatches={len(gold_mismatch)}")
    print(f"wrote {md_path.relative_to(repo_root)}")
    print(f"wrote {json_path.relative_to(repo_root)}")
    print("\n## Global type totals")
    for (tid, label, payload), count in sorted(
        payload_by_type.items(), key=lambda item: (-item[1], item[0][0] or 0)
    ):
        print(f"| {count} | object {tid} | {label} | {payload} |")
    print("\n## By campaign")
    for camp in sorted(type_by_campaign):
        total = sum(type_by_campaign[camp].values())
        parts = ", ".join(
            f"{count}× {label}"
            for (_tid, label), count in sorted(type_by_campaign[camp].items(), key=lambda item: -item[1])
        )
        print(f"| {camp} | {total} | {parts} |")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
