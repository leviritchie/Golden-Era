#!/usr/bin/env python3
"""Fail-closed: continuity carry-policy handoff.levelCap must match H3M levelLimit.

Scans scenarios/**/continuity_carry_policy*.json. Each handoff.fromMissionId's
levelCap must equal the Complete LOD H3M header levelLimit (0 = unlimited).

Wired into OfflineUnlockMod BeforeBuild via ValidateCampaignHeroLevelCapContract.
Proof boundary: source/static. Does not prove runtime Olden customHeroMaxLevel.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "experiments" / "campaign_port_poc"))

from campaign_hero_level_cap import validate_handoff_level_cap  # noqa: E402

SCHEMA = "homm3.olden_campaign_continuity_carry_policy.v1"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    args = parser.parse_args()
    repo_root = args.repo_root.resolve()

    errors: list[str] = []
    checked = 0
    for path in sorted((repo_root / "scenarios").rglob("continuity_carry_policy*.json")):
        policy = json.loads(path.read_text(encoding="utf-8-sig"))
        rel = str(path.relative_to(repo_root)).replace("\\", "/")
        if policy.get("schema") != SCHEMA:
            errors.append(f"{rel}: unsupported schema {policy.get('schema')!r}")
            continue
        handoffs = policy.get("handoffs")
        if not isinstance(handoffs, list) or not handoffs:
            errors.append(f"{rel}: missing handoffs[]")
            continue
        for handoff in handoffs:
            if not isinstance(handoff, dict):
                errors.append(f"{rel}: handoff is not an object")
                continue
            checked += 1
            for issue in validate_handoff_level_cap(handoff, repo_root=repo_root):
                errors.append(f"{rel}: {issue}")

    if errors:
        print("Campaign hero level-cap contract FAILED:")
        for issue in errors:
            print(f"  - {issue}")
        return 1

    print(
        "Campaign hero level-cap contract passed "
        f"(handoffs checked={checked}; H3M levelLimit alignment)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
