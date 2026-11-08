#!/usr/bin/env python3
"""Restore campaign video softsub LocKit rows into Lang/*/texts/cinematic.json tokens.

Root cause: tools/release_port/multilingual_custom_lang.py scrubbed
``homm3_roe_*_video_N`` / ``homm3_absod_*_video_N`` SIDs from ``tokens`` as
noncanonical (misclassified as customMaps / faction rows) while leaving them in
English ``array``. LocKit resolves softsub SIDs from ``tokens``, so PlayVideo
showed ``LOC:homm3_…_video_N``.

This repair:
  1. Upserts softsub rows from English ``array`` into English ``tokens``.
  2. Mirrors those English softsub rows into every other locale's ``tokens`` and
     ``array`` (English text draft) so non-English no longer shows LOC: either.

Re-run after fixing canonical_custom_text_files_for_sid so a later overlay sync
will not scrub them again.
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
    CAMPAIGN_VIDEO_SOFTSUB_SID_RE,
    canonical_custom_text_files_for_sid,
)

DEFAULT_CORE = Path(
    r"V:/SteamLibrary/steamapps/common/"
    r"Heroes of Might and Magic Olden Era - Golden Era/"
    r"HeroesOldenEra_Data/StreamingAssets/Core.zip"
)
DEFAULT_VIDEO_DIR = DEFAULT_CORE.parent / "video"


def fail(message: str) -> None:
    raise SystemExit(f"ERROR: {message}")


def is_campaign_video_softsub_sid(sid: str) -> bool:
    if not isinstance(sid, str) or not sid:
        return False
    if not CAMPAIGN_VIDEO_SOFTSUB_SID_RE.match(sid):
        return False
    return "cinematic.json" in canonical_custom_text_files_for_sid(sid)


def _rows_by_sid(rows: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(rows, list):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        sid = row.get("sid")
        if isinstance(sid, str) and sid:
            out[sid] = row
    return out


def _upsert_section(
    doc: dict[str, Any],
    section: str,
    softsub_rows: list[dict[str, str]],
) -> tuple[int, int]:
    rows = doc.get(section)
    if not isinstance(rows, list):
        rows = []
        doc[section] = rows
    by_sid = {
        str(row.get("sid")): index
        for index, row in enumerate(rows)
        if isinstance(row, dict) and isinstance(row.get("sid"), str)
    }
    inserted = 0
    updated = 0
    for row in softsub_rows:
        sid = row["sid"]
        text = row["text"]
        if sid in by_sid:
            existing = rows[by_sid[sid]]
            if isinstance(existing, dict) and existing.get("text") != text:
                existing["text"] = text
                updated += 1
            continue
        by_sid[sid] = len(rows)
        rows.append({"sid": sid, "text": text})
        inserted += 1
    return inserted, updated


def collect_sidecar_softsub_sids(video_dir: Path) -> set[str]:
    if not video_dir.is_dir():
        fail(f"missing video dir: {video_dir}")
    needed: set[str] = set()
    for path in sorted(video_dir.glob("*.mp4.json")):
        if path.name.startswith("Campaign_"):
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        for cue in data.get("subtitles") or []:
            if not isinstance(cue, dict):
                continue
            sid = cue.get("sid")
            if isinstance(sid, str) and is_campaign_video_softsub_sid(sid):
                needed.add(sid)
    return needed


def softsub_rows_from_english(doc: dict[str, Any]) -> list[dict[str, str]]:
    """Prefer array text (survived scrub), fall back to tokens."""
    by_sid: dict[str, str] = {}
    for section in ("array", "tokens"):
        for sid, row in _rows_by_sid(doc.get(section)).items():
            if not is_campaign_video_softsub_sid(sid):
                continue
            text = row.get("text")
            if isinstance(text, str) and text.strip() and sid not in by_sid:
                by_sid[sid] = text
    return [{"sid": sid, "text": by_sid[sid]} for sid in sorted(by_sid)]


def repair_core(
    core_zip: Path,
    *,
    video_dir: Path,
    dry_run: bool,
) -> dict[str, Any]:
    if not core_zip.is_file():
        fail(f"missing Core.zip: {core_zip}")

    needed = collect_sidecar_softsub_sids(video_dir)
    report: dict[str, Any] = {
        "schema": "homm3.cinematic_softsub_loc_token_repair.v1",
        "coreZip": str(core_zip),
        "videoDir": str(video_dir),
        "dryRun": dry_run,
        "sidecarSoftsubSids": len(needed),
        "members": {},
        "totalInserted": 0,
        "totalUpdated": 0,
    }
    if not needed:
        fail("no campaign video softsub SIDs found under video/*.mp4.json")

    members: dict[str, bytes] = {}
    with zipfile.ZipFile(core_zip, "r") as source:
        english_name = "Lang/english/texts/cinematic.json"
        if english_name not in source.namelist():
            fail(f"missing {english_name}")
        english_doc = json.loads(source.read(english_name).decode("utf-8-sig"))
        if not isinstance(english_doc, dict):
            fail(f"{english_name} is not a JSON object")

        softsub_rows = softsub_rows_from_english(english_doc)
        present = {row["sid"] for row in softsub_rows}
        missing_source = sorted(needed - present)
        report["englishSoftsubRowsAvailable"] = len(softsub_rows)
        report["missingSoftsubSourceInEnglish"] = missing_source[:40]
        if missing_source:
            fail(
                "English cinematic.json has no text for softsub SIDs referenced by "
                f"sidecars ({len(missing_source)} missing); sample: "
                + ", ".join(missing_source[:12])
            )

        cinematic_members = [
            name
            for name in source.namelist()
            if name.startswith("Lang/") and name.endswith("/texts/cinematic.json")
        ]
        if english_name not in cinematic_members:
            cinematic_members.append(english_name)

        for name in sorted(cinematic_members):
            doc = (
                english_doc
                if name == english_name
                else json.loads(source.read(name).decode("utf-8-sig"))
            )
            if not isinstance(doc, dict):
                fail(f"{name} is not a JSON object")
            inserted_tokens, updated_tokens = _upsert_section(doc, "tokens", softsub_rows)
            inserted_array, updated_array = _upsert_section(doc, "array", softsub_rows)
            inserted = inserted_tokens + inserted_array
            updated = updated_tokens + updated_array
            report["members"][name] = {
                "insertedTokens": inserted_tokens,
                "updatedTokens": updated_tokens,
                "insertedArray": inserted_array,
                "updatedArray": updated_array,
            }
            report["totalInserted"] += inserted
            report["totalUpdated"] += updated
            if inserted or updated or name == english_name:
                # Always rewrite english so tokens are materialized even if counts
                # were already partially correct after a prior partial repair.
                members[name] = (
                    json.dumps(doc, indent=2, ensure_ascii=False) + "\n"
                ).encode("utf-8")
                if name == english_name:
                    english_doc = doc

        token_sids = {
            str(row.get("sid"))
            for row in (english_doc.get("tokens") or [])
            if isinstance(row, dict)
        }
        missing_after = sorted(needed - token_sids)
        report["englishMissingSoftsubTokensAfter"] = missing_after
        if missing_after:
            fail(
                "english cinematic.json tokens still missing softsub SIDs: "
                + ", ".join(missing_after[:12])
            )

        # Fail closed: allowlist must classify softsubs as cinematic-only.
        bad = [
            sid
            for sid in sorted(needed)[:20]
            if canonical_custom_text_files_for_sid(sid) != {"cinematic.json"}
        ]
        report["allowlistMismatches"] = bad
        if bad:
            fail(
                "canonical_custom_text_files_for_sid must map softsub SIDs to "
                f"cinematic.json only; bad sample: {bad[:5]}"
            )

        if dry_run:
            return report
        if not members:
            return report

        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup = core_zip.with_name(
            core_zip.name + f".cinematic_softsub_loc_token_repair_backup_{stamp}"
        )
        if backup.exists():
            fail(f"backup path already exists: {backup}")
        shutil.copy2(core_zip, backup)
        report["backup"] = str(backup)

        temp_dir = Path(
            tempfile.mkdtemp(
                prefix="cinematic_softsub_loc_token_repair_",
                dir=str(core_zip.parent),
            )
        )
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
    parser.add_argument("--video-dir", type=Path, default=DEFAULT_VIDEO_DIR)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    report = repair_core(
        args.core.resolve(),
        video_dir=args.video_dir.resolve(),
        dry_run=args.dry_run,
    )
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
