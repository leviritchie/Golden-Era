#!/usr/bin/env python3
"""Validate the mined Olden QuestScript vocabulary artifact."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
POC_DIR = REPO_ROOT / "experiments" / "campaign_port_poc"
if str(POC_DIR) not in sys.path:
    sys.path.insert(0, str(POC_DIR))

import olden_quest_script_vocabulary as vocab  # noqa: E402

EXPECTED_UNIQUE_CONDITIONS = 48
EXPECTED_UNIQUE_ACTIONS = 70
EXPECTED_COUNTER_EQUALS_IN_VANILLA = 0
MIN_OBJECT_INTERACTION_AFTER = 6
MIN_COUNTER_WITH_EQUALS = 400


def require(condition: bool, message: str, errors: list[str]) -> None:
    if not condition:
        errors.append(message)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument(
        "--artifact",
        type=Path,
        default=None,
        help="defaults to repo artifacts/olden_quest_script_vocabulary/olden_quest_script_vocabulary.v1.json",
    )
    args = parser.parse_args()
    repo_root = args.repo_root.resolve()
    artifact_path = (args.artifact or repo_root / "artifacts" / "olden_quest_script_vocabulary" / "olden_quest_script_vocabulary.v1.json").resolve()
    errors: list[str] = []

    require(artifact_path.exists(), f"missing vocabulary artifact: {artifact_path}", errors)
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1

    stored = json.loads(artifact_path.read_text(encoding="utf-8"))
    require(stored.get("schema") == vocab.SCHEMA, f"schema mismatch: {stored.get('schema')}", errors)

    recomputed = vocab.mine_vocabulary()
    require(
        stored.get("conditionHistogram") == recomputed.get("conditionHistogram"),
        "conditionHistogram drift; rerun tools/mine_olden_quest_script_vocabulary.py",
        errors,
    )
    require(
        stored.get("actionHistogram") == recomputed.get("actionHistogram"),
        "actionHistogram drift; rerun tools/mine_olden_quest_script_vocabulary.py",
        errors,
    )
    require(
        stored.get("counterOperatorHistogram") == recomputed.get("counterOperatorHistogram"),
        "counterOperatorHistogram drift; rerun tools/mine_olden_quest_script_vocabulary.py",
        errors,
    )
    require(
        stored.get("mapCount") == recomputed.get("mapCount"),
        f"mapCount drift: stored={stored.get('mapCount')} recomputed={recomputed.get('mapCount')}",
        errors,
    )

    require(
        stored.get("storyConditionHistogram") == recomputed.get("storyConditionHistogram"),
        "storyConditionHistogram drift; rerun tools/mine_olden_quest_script_vocabulary.py",
        errors,
    )
    story_cond = stored.get("storyConditionHistogram") or {}
    require(len(story_cond) >= EXPECTED_UNIQUE_CONDITIONS, f"expected >= {EXPECTED_UNIQUE_CONDITIONS} story conditions, got {len(story_cond)}", errors)
    require(
        int(story_cond.get("CounterEquals", 0)) == EXPECTED_COUNTER_EQUALS_IN_VANILLA,
        f"story-map corpus must not use CounterEquals; found {story_cond.get('CounterEquals')}",
        errors,
    )
    cond_hist = stored.get("conditionHistogram") or {}
    action_hist = stored.get("actionHistogram") or {}
    require(len(cond_hist) >= EXPECTED_UNIQUE_CONDITIONS, f"expected >= {EXPECTED_UNIQUE_CONDITIONS} total conditions, got {len(cond_hist)}", errors)
    require(len(action_hist) >= EXPECTED_UNIQUE_ACTIONS, f"expected >= {EXPECTED_UNIQUE_ACTIONS} actions, got {len(action_hist)}", errors)
    require(
        int(story_cond.get("ObjectInteractionAfter", 0)) >= MIN_OBJECT_INTERACTION_AFTER,
        f"expected >= {MIN_OBJECT_INTERACTION_AFTER} ObjectInteractionAfter samples in story maps",
        errors,
    )
    counter_ops = stored.get("counterOperatorHistogram") or {}
    require(int(counter_ops.get("=", 0)) >= MIN_COUNTER_WITH_EQUALS, f"expected >= {MIN_COUNTER_WITH_EQUALS} Counter '=' operators", errors)
    require(
        stored.get("portingNotes", {}).get("canonicalCounterCondition", {}).get("c") == "Counter",
        "portingNotes.canonicalCounterCondition must document Counter",
        errors,
    )

    if errors:
        print("VALIDATION FAILED", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1

    print(f"OK: {artifact_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
