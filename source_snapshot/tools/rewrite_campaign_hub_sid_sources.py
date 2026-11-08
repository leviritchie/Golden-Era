#!/usr/bin/env python3
"""Rewrite legacy StoryHub hub SIDs to play-order SIDs in repo source files."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tools"))
from homm3_campaign_hub_sid_order import rewrite_hub_sid_text  # noqa: E402

# Scoped paths only — do not rewrite unrelated mission map SIDs or whole artifacts/.
SOURCE_GLOBS = (
    "tools/install_roe_castle_continuity_weave.py",
    "tools/generate_ab_sod_installer_hub_configs.py",
    "tools/generate_ab_sod_localization_and_policies.py",
    "tools/validate_roe_castle_campaign_continuity_contract.py",
    "tools/repair_campaign_loc_tokens.py",
    "tools/release_port/multilingual_custom_lang.py",
    "tools/wire_ab_sod_video_policies.py",
    "scenarios/roe_castle_campaign/continuity_carry_policy*.json",
    "scenarios/ab_sod_campaigns/continuity_carry_policy*.json",
    "scenarios/ab_sod_campaigns/hub_index.v1.json",
    "scenarios/ab_sod_campaigns/ab_sod_delivery_status.v1.json",
    "scenarios/ab_sod_campaigns/installer_hub_configs.fragment.py",
    "experiments/campaign_port_poc/build_roe_castle_continuity_weave.py",
    "experiments/campaign_port_poc/storyhub_map_background.py",
    "Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/Homm3CampaignContinuityContract.cs",
    "Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/Homm3StoryHubMapBackgroundHook.cs",
)


def iter_targets(repo: Path) -> list[Path]:
    found: list[Path] = []
    for pattern in SOURCE_GLOBS:
        found.extend(sorted(repo.glob(pattern)))
    # unique preserve order
    seen: set[Path] = set()
    out: list[Path] = []
    for path in found:
        if path in seen or not path.is_file():
            continue
        seen.add(path)
        out.append(path)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    repo = args.repo_root.resolve()
    changed: list[str] = []
    for path in iter_targets(repo):
        original = path.read_text(encoding="utf-8")
        rewritten = rewrite_hub_sid_text(original)
        if rewritten == original:
            continue
        changed.append(str(path.relative_to(repo)))
        if not args.dry_run:
            path.write_text(rewritten, encoding="utf-8", newline="\n")
    print(f"changed={len(changed)} dry_run={args.dry_run}")
    for row in changed:
        print(f"  {row}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
