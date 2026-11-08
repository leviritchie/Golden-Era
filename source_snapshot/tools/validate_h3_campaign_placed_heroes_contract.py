#!/usr/bin/env python3
"""Fail-closed: H3 campaign placed stubs stay out of roster / in campaignHeroes."""

from __future__ import annotations

import argparse
import json
import sys
import zipfile
from pathlib import Path

DEFAULT_CORE_ZIP = Path(
    r"V:\SteamLibrary\steamapps\common\Heroes of Might and Magic Olden Era - Golden Era"
    r"\HeroesOldenEra_Data\StreamingAssets\Core.zip"
)
DEFAULT_OVERLAY = (
    Path(__file__).resolve().parents[1]
    / "artifacts"
    / "campaign_port_poc"
    / "h3_campaign_placed_heroes_overlay"
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--core-zip", type=Path, default=DEFAULT_CORE_ZIP)
    parser.add_argument("--overlay-root", type=Path, default=DEFAULT_OVERLAY)
    args = parser.parse_args()
    if not args.core_zip.is_file():
        print(f"FAIL: Core.zip missing: {args.core_zip}", file=sys.stderr)
        return 2
    catalog_path = args.overlay_root / "DB" / "h3_campaign_placed_heroes_catalog.json"
    if not catalog_path.is_file():
        print(
            f"FAIL: campaign placed overlay catalog missing: {catalog_path} "
            "(run experiments/campaign_port_poc/h3_campaign_placed_heroes.py)",
            file=sys.stderr,
        )
        return 1
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    stubs = [str(s) for s in (catalog.get("campaignHeroes") or []) if isinstance(s, str)]
    if not stubs:
        print("FAIL: catalog campaignHeroes empty", file=sys.stderr)
        return 1

    with zipfile.ZipFile(args.core_zip, "r") as zf:
        names = set(zf.namelist())
        data = json.loads(zf.read("DB/data.json").decode("utf-8-sig"))
        campaign_heroes = {
            str(s) for s in (data.get("campaignHeroes") or []) if isinstance(s, str)
        }
        missing_files = [
            sid for sid in stubs if f"DB/heroes/campaign/{sid}.json" not in names
        ]
        missing_list = [sid for sid in stubs if sid not in campaign_heroes]
        leaked_roster = [
            sid
            for sid in stubs
            if any(
                n.startswith(f"DB/heroes/homm3_") and n.endswith(f"/{sid}.json")
                for n in names
            )
        ]

    errors: list[str] = []
    if missing_files:
        errors.append(
            "Core missing campaign hero rows:\n- " + "\n- ".join(missing_files)
        )
    if missing_list:
        errors.append(
            "DB/data.json campaignHeroes missing stubs:\n- " + "\n- ".join(missing_list)
        )
    if leaked_roster:
        errors.append(
            "stubs incorrectly also present as homm3 roster rows:\n- "
            + "\n- ".join(leaked_roster)
        )
    if errors:
        print("FAIL:\n" + "\n".join(errors), file=sys.stderr)
        return 1
    print(f"OK: {len(stubs)} h3 campaign placed stubs in Core campaignHeroes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
