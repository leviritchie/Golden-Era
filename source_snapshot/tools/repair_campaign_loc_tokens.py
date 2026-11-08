#!/usr/bin/env python3
"""Restore HoMM3 StoryHub campaign LocKit rows into Lang/*/texts/campaign.json tokens.

Root cause: tools/release_port/multilingual_custom_lang.py scrubbed campaign_* /
hub / mission title SIDs from ``tokens`` as noncanonical while leaving them in
``array``. BhCampaign.Init resolves ``campaign_<hubSid>`` via LocKit tokens, so
the Profiles campaign list showed ``LOC:campaign_…``.

This repair upserts allowed campaign.json SIDs from ``array`` into ``tokens`` for
every locale. Re-run after fixing canonical_custom_text_files_for_sid so a later
overlay sync will not scrub them again.
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
sys.path.insert(0, str(REPO_ROOT / "tools" / "release_port"))
from multilingual_custom_lang import (  # noqa: E402
    HOMM3_CAMPAIGN_HUB_SIDS,
    canonical_custom_text_files_for_sid,
)

DEFAULT_CORE = Path(
    r"V:/SteamLibrary/steamapps/common/"
    r"Heroes of Might and Magic Olden Era - Golden Era/"
    r"HeroesOldenEra_Data/StreamingAssets/Core.zip"
)


def fail(message: str) -> None:
    raise SystemExit(f"ERROR: {message}")


def belongs_in_campaign_json(sid: str) -> bool:
    if not isinstance(sid, str) or not sid:
        return False
    if sid.startswith("campaign_homm3_") or sid in HOMM3_CAMPAIGN_HUB_SIDS:
        return True
    allowed = canonical_custom_text_files_for_sid(sid)
    return "campaign.json" in allowed


def upsert_tokens_from_array(doc: dict[str, Any]) -> tuple[int, list[str]]:
    array_rows = doc.get("array")
    if not isinstance(array_rows, list):
        return 0, []
    tokens = doc.get("tokens")
    if not isinstance(tokens, list):
        tokens = []
        doc["tokens"] = tokens
    by_sid = {
        str(row.get("sid")): index
        for index, row in enumerate(tokens)
        if isinstance(row, dict) and isinstance(row.get("sid"), str)
    }
    inserted: list[str] = []
    for row in array_rows:
        if not isinstance(row, dict):
            continue
        sid = row.get("sid")
        text = row.get("text")
        if not isinstance(sid, str) or not isinstance(text, str):
            continue
        if not belongs_in_campaign_json(sid):
            continue
        if sid in by_sid:
            existing = tokens[by_sid[sid]]
            if isinstance(existing, dict) and existing.get("text") != text:
                existing["text"] = text
            continue
        by_sid[sid] = len(tokens)
        tokens.append({"sid": sid, "text": text})
        inserted.append(sid)
    return len(inserted), inserted


def repair_core(core_zip: Path, *, dry_run: bool) -> dict[str, Any]:
    if not core_zip.is_file():
        fail(f"missing Core.zip: {core_zip}")

    report: dict[str, Any] = {
        "schema": "homm3.campaign_loc_token_repair.v1",
        "coreZip": str(core_zip),
        "dryRun": dry_run,
        "members": {},
        "totalInserted": 0,
    }

    members: dict[str, bytes] = {}
    with zipfile.ZipFile(core_zip, "r") as source:
        for name in source.namelist():
            if not (name.startswith("Lang/") and name.endswith("/texts/campaign.json")):
                continue
            doc = json.loads(source.read(name).decode("utf-8-sig"))
            if not isinstance(doc, dict):
                fail(f"{name} is not a JSON object")
            inserted_count, inserted_sids = upsert_tokens_from_array(doc)
            report["members"][name] = {
                "inserted": inserted_count,
                "sample": inserted_sids[:12],
            }
            report["totalInserted"] += inserted_count
            if inserted_count:
                members[name] = (
                    json.dumps(doc, indent=2, ensure_ascii=False) + "\n"
                ).encode("utf-8")

        required = [
            f"campaign_{hub}" for hub in sorted(HOMM3_CAMPAIGN_HUB_SIDS)
        ]
        english = "Lang/english/texts/campaign.json"
        if english not in source.namelist() and english not in members:
            fail(f"missing {english}")
        english_doc = (
            json.loads(members[english].decode("utf-8-sig"))
            if english in members
            else json.loads(source.read(english).decode("utf-8-sig"))
        )
        token_sids = {
            str(row.get("sid"))
            for row in (english_doc.get("tokens") or [])
            if isinstance(row, dict)
        }
        missing = [sid for sid in required if sid not in token_sids]
        report["englishMissingCampaignTokensAfter"] = missing
        if missing:
            fail(
                "english campaign.json tokens still missing BhCampaign SIDs: "
                + ", ".join(missing)
            )

        if dry_run or not members:
            return report

        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup = core_zip.with_name(core_zip.name + f".campaign_loc_token_repair_backup_{stamp}")
        if backup.exists():
            fail(f"backup path already exists: {backup}")
        shutil.copy2(core_zip, backup)
        report["backup"] = str(backup)

        temp_dir = Path(tempfile.mkdtemp(prefix="campaign_loc_token_repair_", dir=str(core_zip.parent)))
        temp_zip = temp_dir / core_zip.name
        try:
            with zipfile.ZipFile(temp_zip, "w") as target:
                written: set[str] = set()
                for info in source.infolist():
                    name = info.filename
                    data = members[name] if name in members else source.read(name)
                    replacement = zipfile.ZipInfo(name, info.date_time)
                    replacement.comment = info.comment
                    replacement.extra = info.extra
                    replacement.internal_attr = info.internal_attr
                    replacement.external_attr = info.external_attr
                    replacement.compress_type = info.compress_type
                    target.writestr(replacement, data)
                    written.add(name)
                for name, data in members.items():
                    if name not in written:
                        target.writestr(name, data)
            shutil.move(str(temp_zip), str(core_zip))
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--core", type=Path, default=DEFAULT_CORE)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    report = repair_core(args.core.resolve(), dry_run=args.dry_run)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
