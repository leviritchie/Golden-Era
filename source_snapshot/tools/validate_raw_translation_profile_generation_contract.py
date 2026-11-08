#!/usr/bin/env python3
"""Fail-closed: Castle raw_translation profiles must match the centralized generator."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POC = ROOT / "experiments" / "campaign_port_poc"
if str(POC) not in sys.path:
    sys.path.insert(0, str(POC))

from campaign_mission import default_batch_manifest_path, load_batch_manifest  # noqa: E402
import generate_campaign_raw_translation_profile as raw_profile  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=default_batch_manifest_path())
    args = parser.parse_args()
    batch = load_batch_manifest(args.manifest.resolve())
    errors: list[str] = []
    for mission in batch.missions:
        expected = raw_profile.build_raw_translation_profile(batch, mission)
        expected_disk = {key: value for key, value in expected.items() if not str(key).startswith("_")}
        path = raw_profile.raw_profile_path_for_mission(mission)
        if not path.exists():
            errors.append(f"{mission.mission_id}: missing {path}")
            continue
        actual = json.loads(path.read_text(encoding="utf-8-sig"))
        actual_disk = {key: value for key, value in actual.items() if not str(key).startswith("_")}
        if actual_disk != expected_disk:
            # Identify drift keys for a clear fail message.
            keys = sorted(set(actual_disk) | set(expected_disk))
            drifted = [key for key in keys if actual_disk.get(key) != expected_disk.get(key)]
            errors.append(f"{mission.mission_id}: profile drift at keys {drifted}")
    if errors:
        print(json.dumps({"ok": False, "errors": errors}, indent=2))
        return 1
    print(
        json.dumps(
            {
                "ok": True,
                "missions": [mission.mission_id for mission in batch.missions],
                "generator": "generate_campaign_raw_translation_profile.py",
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
