#!/usr/bin/env python3
"""Fail closed when StoryHub delayed hero unlocks disagree with mission spawns.

Native mainStory pattern:
- Only the first mission's hero sets ``isAvailableAtStart: true``
- Later protagonists omit the flag and receive ``UnlockHero`` on the prior
  mission node's ``onDoneActions`` before the next node activates
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def validate_payload_dir(payload_dir: Path) -> list[str]:
    errors: list[str] = []
    heroes_path = payload_dir / "heroes.json"
    story_path = payload_dir / "storyHub.json"
    if not heroes_path.is_file() or not story_path.is_file():
        return [f"missing heroes.json or storyHub.json under {payload_dir}"]
    heroes_doc = _load_json(heroes_path)
    story = _load_json(story_path)
    rows = heroes_doc.get("array") if isinstance(heroes_doc, dict) else None
    if not isinstance(rows, list) or not rows:
        return [f"{heroes_path}: heroes.array must be a non-empty list"]

    available_at_start = [
        str(row.get("id") or "")
        for row in rows
        if isinstance(row, dict) and row.get("isAvailableAtStart") is True
    ]
    if len(available_at_start) != 1:
        errors.append(
            f"{heroes_path}: expected exactly one isAvailableAtStart=true hero "
            f"(native delayed-unlock pattern); got {available_at_start!r}"
        )
    start_hero = available_at_start[0] if available_at_start else ""

    roster_ids = [
        str(row.get("id") or "")
        for row in rows
        if isinstance(row, dict) and str(row.get("id") or "").strip()
    ]
    # Heroes without the flag must be unlocked somewhere.
    locked = [sid for sid in roster_ids if sid != start_hero]
    unlocks: dict[str, str] = {}
    for node in story.get("nodes") or []:
        if not isinstance(node, dict):
            continue
        node_sid = str(node.get("sid") or "")
        for action in node.get("onDoneActions") or []:
            if not isinstance(action, dict) or action.get("type") != "UnlockHero":
                continue
            values = action.get("values") or []
            if not values:
                errors.append(f"{node_sid}: UnlockHero missing values")
                continue
            hero = str(values[0])
            unlocks[hero] = node_sid
    for sid in locked:
        if sid not in unlocks:
            errors.append(
                f"{sid}: listed in heroes.json without isAvailableAtStart but never "
                f"UnlockHero'd in storyHub onDoneActions"
            )
    for hero, node_sid in unlocks.items():
        if hero not in roster_ids:
            errors.append(
                f"{node_sid}: UnlockHero {hero!r} is not listed in heroes.json"
            )
        if hero == start_hero:
            errors.append(
                f"{node_sid}: UnlockHero {hero!r} is redundant (already available at start)"
            )
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "payload_dirs",
        nargs="+",
        type=Path,
        help="campaign_payload directories to validate",
    )
    args = parser.parse_args()
    errors: list[str] = []
    for path in args.payload_dirs:
        errors.extend(validate_payload_dir(path.resolve()))
    if errors:
        print("FAIL validate_storyhub_delayed_hero_unlock_contract")
        for err in errors:
            print(f"  - {err}")
        return 1
    print(
        json.dumps(
            {
                "ok": True,
                "payloadDirs": [str(p) for p in args.payload_dirs],
                "proofBoundary": "source/static StoryHub payload shape (native mainStory pattern)",
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
