#!/usr/bin/env python3
"""Rename StoryHub hub SIDs to zero-padded play-order names in Core.zip.

Native Profiles campaign list order follows alphabetical hub SID / folder name.
``homm3_01_…``–``homm3_20_…`` sorts into Complete Edition play order.

Rewrites:
  - campaigns/<legacy>/ → campaigns/<play>/
  - storyHub.json (and other campaign JSON) hub sid fields
  - Lang/*/texts/campaign.json token SIDs (hub, campaign_<hub>, hub_title)
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tools"))
from homm3_campaign_hub_sid_order import (  # noqa: E402
    LEGACY_TO_PLAY_ORDER,
    PLAY_ORDER_HUB_SIDS,
    rewrite_hub_sid_text,
)

DEFAULT_CORE = Path(
    r"V:/SteamLibrary/steamapps/common/"
    r"Heroes of Might and Magic Olden Era - Golden Era/"
    r"HeroesOldenEra_Data/StreamingAssets/Core.zip"
)


def fail(message: str) -> None:
    raise SystemExit(f"ERROR: {message}")


def rewrite_json_bytes(raw: bytes) -> bytes:
    text = raw.decode("utf-8-sig")
    rewritten = rewrite_hub_sid_text(text)
    if rewritten == text:
        return raw
    # Preserve object shape via round-trip only when JSON; else text rewrite.
    try:
        doc = json.loads(rewritten)
    except json.JSONDecodeError:
        return (rewritten if rewritten.endswith("\n") else rewritten + "\n").encode("utf-8")
    return (json.dumps(doc, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def rewrite_campaign_lang_doc(doc: dict[str, Any]) -> dict[str, Any]:
    for key in ("tokens", "array"):
        rows = doc.get(key)
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            sid = row.get("sid")
            if isinstance(sid, str):
                row["sid"] = rewrite_hub_sid_text(sid)
    return doc


def migrate_member_name(name: str) -> str:
    for legacy, play in sorted(
        LEGACY_TO_PLAY_ORDER.items(), key=lambda item: len(item[0]), reverse=True
    ):
        old_prefix = f"campaigns/{legacy}/"
        new_prefix = f"campaigns/{play}/"
        if name.startswith(old_prefix):
            return new_prefix + name[len(old_prefix) :]
        if name == f"campaigns/{legacy}" or name == f"campaigns/{legacy}/":
            return f"campaigns/{play}/"
    return name


def migrate_core(core_zip: Path, *, dry_run: bool) -> dict[str, Any]:
    if not core_zip.is_file():
        fail(f"missing Core.zip: {core_zip}")

    report: dict[str, Any] = {
        "schema": "homm3.campaign_hub_sid_play_order_migrate.v1",
        "coreZip": str(core_zip),
        "dryRun": dry_run,
        "renamedCampaignMembers": 0,
        "rewrittenMembers": 0,
        "hubsPresentLegacy": [],
        "hubsPresentPlayOrder": [],
    }

    with zipfile.ZipFile(core_zip, "r") as source:
        names = source.namelist()
        legacy_present = sorted(
            {
                legacy
                for legacy in LEGACY_TO_PLAY_ORDER
                if any(n.startswith(f"campaigns/{legacy}/") for n in names)
            }
        )
        play_present = sorted(
            {
                play
                for play in PLAY_ORDER_HUB_SIDS
                if any(n.startswith(f"campaigns/{play}/") for n in names)
            }
        )
        report["hubsPresentLegacy"] = legacy_present
        report["hubsPresentPlayOrder"] = play_present

        if play_present and not legacy_present:
            report["status"] = "already_migrated"
            return report
        if not legacy_present:
            fail("no legacy or play-order campaign hubs found in Core.zip")

        planned: dict[str, bytes] = {}
        for info in source.infolist():
            name = info.filename
            if info.is_dir():
                continue
            data = source.read(name)
            new_name = migrate_member_name(name)
            if new_name != name:
                report["renamedCampaignMembers"] += 1

            if name.startswith("Lang/") and name.endswith("/texts/campaign.json"):
                doc = json.loads(data.decode("utf-8-sig"))
                if not isinstance(doc, dict):
                    fail(f"{name} is not a JSON object")
                rewritten = rewrite_campaign_lang_doc(doc)
                data = (json.dumps(rewritten, indent=2, ensure_ascii=False) + "\n").encode(
                    "utf-8"
                )
                report["rewrittenMembers"] += 1
            elif new_name.startswith("campaigns/") and name.endswith(".json"):
                new_data = rewrite_json_bytes(data)
                if new_data != data:
                    report["rewrittenMembers"] += 1
                data = new_data

            planned[new_name] = data

        # Collision check
        if len(planned) != len({migrate_member_name(n) for n in names if not n.endswith("/")}):
            # directories aside; verify no two sources map to same target file
            targets: dict[str, str] = {}
            for name in names:
                if name.endswith("/"):
                    continue
                target = migrate_member_name(name)
                if target in targets and targets[target] != name:
                    fail(f"rename collision: {targets[target]!r} and {name!r} → {target!r}")
                targets[target] = name

        english = "Lang/english/texts/campaign.json"
        if english not in planned:
            fail(f"missing {english}")
        eng = json.loads(planned[english].decode("utf-8-sig"))
        token_sids = {
            row.get("sid")
            for row in (eng.get("tokens") or [])
            if isinstance(row, dict)
        }
        missing = [
            f"campaign_{hub}"
            for hub in PLAY_ORDER_HUB_SIDS
            if hub in {
                LEGACY_TO_PLAY_ORDER[legacy]
                for legacy in legacy_present
            }
            and f"campaign_{hub}" not in token_sids
        ]
        # Only require hubs we actually migrated
        migrated_play = [LEGACY_TO_PLAY_ORDER[legacy] for legacy in legacy_present]
        missing = [f"campaign_{hub}" for hub in migrated_play if f"campaign_{hub}" not in token_sids]
        report["englishMissingCampaignTokensAfter"] = missing
        if missing:
            fail("english campaign.json tokens missing after rewrite: " + ", ".join(missing))

        # Alpha-sort sanity: migrated play SIDs must sort as play order among themselves
        sorted_play = sorted(migrated_play)
        expected = [hub for hub in PLAY_ORDER_HUB_SIDS if hub in migrated_play]
        report["alphaOrderOk"] = sorted_play == expected
        if sorted_play != expected:
            fail(f"alpha order mismatch: {sorted_play!r} != {expected!r}")

        if dry_run:
            report["status"] = "dry_run_ok"
            return report

        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup = core_zip.with_name(
            core_zip.name + f".hub_sid_play_order_backup_{stamp}"
        )
        if backup.exists():
            fail(f"backup path already exists: {backup}")
        shutil.copy2(core_zip, backup)
        report["backup"] = str(backup)

        temp_dir = Path(
            tempfile.mkdtemp(prefix="hub_sid_play_order_", dir=str(core_zip.parent))
        )
        temp_zip = temp_dir / core_zip.name
        try:
            with zipfile.ZipFile(temp_zip, "w") as target:
                # Write in play-order-friendly member order: stock members first,
                # then campaigns sorted by new hub sid.
                campaign_items = sorted(
                    (n, d) for n, d in planned.items() if n.startswith("campaigns/homm3_")
                )
                other_items = sorted(
                    (n, d) for n, d in planned.items() if not n.startswith("campaigns/homm3_")
                )
                for name, data in other_items + campaign_items:
                    target.writestr(name, data)
            shutil.move(str(temp_zip), str(core_zip))
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

        report["status"] = "migrated"
        return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--core", type=Path, default=DEFAULT_CORE)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    report = migrate_core(args.core.resolve(), dry_run=args.dry_run)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
