#!/usr/bin/env python3
"""Fail-closed: shared town-roster HoMM3 heroes must not sit in DataInc.campaignHeroes.

Native Quick Play / custom-game hero select omits SIDs listed in DB/data.json
``campaignHeroes``. Continuity-hub installs historically appended StoryHub
protagonists (Crag Hack, Christian, Yog, …) into that list even though those
SIDs are normal ``DB/heroes/homm3_*/`` roster rows — which removed them from
Quick Play. Campaign-only stubs without a roster file may remain listed.

This is distinct from ``replace_hota`` late-slot *name* swaps (Mullich→Catherine):
those change which identity occupies slot 17/18; they do not remove early roster
heroes such as ``homm3_stronghold_hero_1``.

Usage:
  python tools/validate_homm3_campaign_heroes_roster_separation_contract.py
  python tools/validate_homm3_campaign_heroes_roster_separation_contract.py --core-zip <path>
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import zipfile
from pathlib import Path

DEFAULT_CORE_ZIP = Path(
    r"V:\SteamLibrary\steamapps\common\Heroes of Might and Magic Olden Era - Golden Era"
    r"\HeroesOldenEra_Data\StreamingAssets\Core.zip"
)

_ROSTER_HERO_MEMBER_RE = re.compile(
    r"^DB/heroes/(homm3_[^/]+)/(homm3_.+_hero_\d+)\.json$"
)


def collect_roster_sids(source: zipfile.ZipFile) -> set[str]:
    sids: set[str] = set()
    for name in source.namelist():
        match = _ROSTER_HERO_MEMBER_RE.match(name.replace("\\", "/"))
        if match:
            sids.add(match.group(2))
    return sids


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Refuse shared roster SIDs inside DB/data.json campaignHeroes."
    )
    parser.add_argument("--core-zip", type=Path, default=DEFAULT_CORE_ZIP)
    args = parser.parse_args()
    core_zip: Path = args.core_zip
    if not core_zip.is_file():
        print(f"FAIL: Core.zip not found: {core_zip}", file=sys.stderr)
        return 2

    with zipfile.ZipFile(core_zip, "r") as source:
        if "DB/data.json" not in source.namelist():
            print("FAIL: Core.zip missing DB/data.json", file=sys.stderr)
            return 2
        data = json.loads(source.read("DB/data.json").decode("utf-8-sig"))
        roster = collect_roster_sids(source)
        campaign_heroes = list(data.get("campaignHeroes") or [])
        leaked = sorted(sid for sid in campaign_heroes if sid in roster)

    if leaked:
        print(
            "FAIL: DB/data.json campaignHeroes lists shared town-roster SIDs "
            "(native Quick Play hides them from hero select):",
            file=sys.stderr,
        )
        for sid in leaked:
            print(f"  - {sid}", file=sys.stderr)
        print(
            "Scrub via continuity installer or remove those SIDs from campaignHeroes. "
            "Keep campaign-only stubs that have no DB/heroes row.",
            file=sys.stderr,
        )
        return 1

    print(
        "OK: campaignHeroes has no shared HoMM3 roster SIDs "
        f"(campaignHeroes={len(campaign_heroes)}, rosterHeroes={len(roster)})."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
