#!/usr/bin/env python3
"""Align continuity_carry_policy handoff.levelCap to H3M levelLimit.

Updates every scenarios/**/continuity_carry_policy*.json so each handoff's
levelCap equals the fromMission H3M header levelLimit (0 = unlimited).

Also refreshes sourceTextProven provenance for the level-cap clause when the
value changes, preserving strongest-N and other handoff fields.

Proof boundary: source/static H3M decode. Does not regenerate maps.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "experiments" / "campaign_port_poc"))

from campaign_hero_level_cap import (  # noqa: E402
    handoff_level_cap_for_from_mission,
    source_text_for_level_cap,
)


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def align_policy(path: Path, *, dry_run: bool) -> dict:
    policy = json.loads(path.read_text(encoding="utf-8-sig"))
    handoffs = policy.get("handoffs")
    if not isinstance(handoffs, list):
        return {"path": str(path), "changed": False, "error": "missing handoffs[]"}

    changes: list[dict] = []
    for handoff in handoffs:
        if not isinstance(handoff, dict):
            continue
        from_id = handoff.get("fromMissionId")
        if not isinstance(from_id, str) or not from_id:
            continue
        expected = handoff_level_cap_for_from_mission(from_id, repo_root=ROOT)
        got = handoff.get("levelCap")
        proven = str(handoff.get("sourceTextProven") or "")
        expected_proven = source_text_for_level_cap(expected, from_mission_id=from_id)
        stale_proven = (
            "pending briefing parse" in proven.lower()
            or "approximate" in proven.lower()
            or "exact binary decode still open" in proven.lower()
            or "evil1-like defaults" in proven.lower()
        )
        # Keep richly proven Homecoming-style briefing quotes when the cap already matches.
        keep_briefing_quote = (
            got == expected
            and "limited to" in proven.lower()
            and not stale_proven
        )
        if got == expected and (keep_briefing_quote or proven == expected_proven):
            continue
        handoff["levelCap"] = expected
        if not keep_briefing_quote:
            handoff["sourceTextProven"] = expected_proven
        changes.append(
            {
                "fromMissionId": from_id,
                "toMissionId": handoff.get("toMissionId"),
                "before": got,
                "after": expected,
                "previousSourceTextProven": proven,
                "sourceTextProven": handoff.get("sourceTextProven"),
            }
        )

    if changes and not dry_run:
        _write_json(path, policy)
    return {
        "path": str(path.relative_to(ROOT)).replace("\\", "/"),
        "changed": bool(changes),
        "changes": changes,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    reports = []
    for path in sorted((ROOT / "scenarios").rglob("continuity_carry_policy*.json")):
        reports.append(align_policy(path, dry_run=bool(args.dry_run)))

    changed = [row for row in reports if row.get("changed")]
    print(
        json.dumps(
            {
                "ok": True,
                "dryRun": bool(args.dry_run),
                "policies": len(reports),
                "changedPolicies": len(changed),
                "reports": reports,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
