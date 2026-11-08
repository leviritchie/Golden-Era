#!/usr/bin/env python3
"""Emit a mined QuestScript vocabulary artifact from Golden Era .map files."""

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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=vocab.DEFAULT_ARTIFACT,
        help="artifact JSON output path",
    )
    args = parser.parse_args()
    out_path = args.output.resolve()
    payload = vocab.mine_vocabulary()
    vocab.write_vocabulary_artifact(out_path, payload)
    summary = {
        "output": str(out_path),
        "mapCount": payload["mapCount"],
        "uniqueConditions": len(payload["conditionHistogram"]),
        "uniqueActions": len(payload["actionHistogram"]),
        "counterEqualsInVanilla": payload["portingNotes"]["counterEqualsObservedInVanillaMaps"],
        "objectInteractionAfterCount": payload["portingNotes"]["visitMapEventConditionCount"],
    }
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
