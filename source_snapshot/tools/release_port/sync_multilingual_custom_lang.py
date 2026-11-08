#!/usr/bin/env python3
"""Apply multilingual custom HoMM3 localization sync to a release Core.zip."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import zipfile
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from analyze_core_overlay import DEFAULT_RELEASE_CORE, normalize_name
from multilingual_custom_lang import (
    TEXT_FILES,
    canonical_custom_text_files_for_sid,
    custom_unit_ability_view_sids,
    sync_multilingual_custom_lang_rows,
)


PLACEHOLDER_RE = re.compile(r"\{\d+\}")
STEAM_GOLDEN_ERA_CORE = (
    Path("V:/SteamLibrary/steamapps/common/Heroes of Might and Magic Olden Era - Golden Era")
    / "HeroesOldenEra_Data"
    / "StreamingAssets"
    / "Core.zip"
)
SUBSTANTIVE_ENGLISH_RE = re.compile(
    r"[.!?:;]|"
    r"\b(?:attack|damage|recruit|spell|hero|enemy|friendly|city|town|"
    r"creature|unit|basic|advanced|expert|command|specialist|upg\.)\b",
    re.IGNORECASE,
)


def read_json(zf: zipfile.ZipFile, name: str) -> Any:
    with zf.open(name) as handle:
        return json.loads(handle.read().decode("utf-8-sig"))


def write_json(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent="\t") + "\n").encode("utf-8")


def upsert_lang_rows_into_list(doc: dict[str, Any], key: str, rows: list[dict[str, Any]], *, create: bool) -> bool:
    tokens = doc.get(key)
    if not isinstance(tokens, list):
        if not create:
            return False
        tokens = []
        doc[key] = tokens
    by_sid: dict[str, int] = {}
    deduped: list[Any] = []
    changed = False
    for token in tokens:
        if not isinstance(token, dict):
            deduped.append(token)
            continue
        sid = token.get("sid")
        if isinstance(sid, str) and sid in by_sid:
            changed = True
            continue
        if isinstance(sid, str):
            by_sid[sid] = len(deduped)
        deduped.append(token)
    if len(deduped) != len(tokens):
        tokens[:] = deduped
    for row in rows:
        sid = row["sid"]
        if sid in by_sid:
            index = by_sid[sid]
            if tokens[index] != row:
                tokens[index] = row
                changed = True
        else:
            by_sid[sid] = len(tokens)
            tokens.append(row)
            changed = True
    return changed


def upsert_lang_rows(doc: dict[str, Any], rows: list[dict[str, Any]]) -> bool:
    # Keep tokens and array synchronized — combat buff UI may read either list.
    changed = upsert_lang_rows_into_list(doc, "tokens", rows, create=True)
    changed = upsert_lang_rows_into_list(doc, "array", rows, create=False) or changed
    return changed


def _read_overlay_or_zip(release_zip: zipfile.ZipFile, overlay: dict[str, bytes], name: str) -> Any:
    if name in overlay:
        return json.loads(overlay[name].decode("utf-8-sig"))
    return read_json(release_zip, name)


def _tokens_by_sid(doc: Any) -> dict[str, str]:
    if not isinstance(doc, dict):
        return {}
    tokens = doc.get("tokens")
    if not isinstance(tokens, list):
        return {}
    return {
        str(row.get("sid")): str(row.get("text"))
        for row in tokens
        if isinstance(row, dict) and row.get("sid") and isinstance(row.get("text"), str)
    }


def _substantive(text: str) -> bool:
    return len(text) > 32 or bool(SUBSTANTIVE_ENGLISH_RE.search(text))


def audit_overlay(release_zip: zipfile.ZipFile, overlay: dict[str, bytes]) -> tuple[int, int, int, Counter[str], Counter[str]]:
    langs = sorted(
        {
            entry.filename.split("/")[1]
            for entry in release_zip.infolist()
            if entry.filename.startswith("Lang/") and "/texts/" in entry.filename
        }
        - {"english"}
    )
    missing = 0
    placeholder_mismatch = 0
    same_substantive = 0
    same_by_file: Counter[str] = Counter()
    same_by_lang: Counter[str] = Counter()
    names = set(release_zip.namelist()) | set(overlay)
    unit_ability_sids = custom_unit_ability_view_sids(release_zip, overlay)

    for file_name in TEXT_FILES:
        english_name = f"Lang/english/texts/{file_name}"
        if english_name not in names:
            continue
        english_rows = {
            sid: text
            for sid, text in _tokens_by_sid(_read_overlay_or_zip(release_zip, overlay, english_name)).items()
            if file_name in canonical_custom_text_files_for_sid(sid, unit_ability_sids)
        }
        if not english_rows:
            continue
        for lang in langs:
            localized_name = f"Lang/{lang}/texts/{file_name}"
            localized_rows = (
                _tokens_by_sid(_read_overlay_or_zip(release_zip, overlay, localized_name))
                if localized_name in names
                else {}
            )
            for sid, english_text in english_rows.items():
                localized_text = localized_rows.get(sid)
                if localized_text is None:
                    missing += 1
                elif sorted(PLACEHOLDER_RE.findall(english_text)) != sorted(PLACEHOLDER_RE.findall(localized_text)):
                    placeholder_mismatch += 1
                elif localized_text == english_text and _substantive(english_text):
                    same_substantive += 1
                    same_by_file[file_name] += 1
                    same_by_lang[lang] += 1

    return missing, placeholder_mismatch, same_substantive, same_by_file, same_by_lang


def rewrite_zip(core: Path, overlay: dict[str, bytes], dry_run: bool) -> Path | None:
    if dry_run or not overlay:
        return None
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    tmp_zip = core.with_name(core.name + ".tmp-multilingual-lang-" + timestamp)
    backup = core.with_name(core.name + ".backup-multilingual-lang-" + timestamp)
    try:
        with zipfile.ZipFile(core, "r") as src, zipfile.ZipFile(tmp_zip, "w", compression=zipfile.ZIP_DEFLATED) as dst:
            written = set()
            for info in src.infolist():
                name = normalize_name(info.filename)
                if info.is_dir():
                    dst.writestr(info, b"")
                    continue
                if name in overlay:
                    dst.writestr(name, overlay[name])
                else:
                    dst.writestr(info, src.read(info.filename))
                written.add(name)
            for name, data in sorted(overlay.items()):
                if name not in written:
                    dst.writestr(name, data)
        shutil.copy2(core, backup)
        shutil.move(str(tmp_zip), core)
        return backup
    finally:
        if tmp_zip.exists():
            tmp_zip.unlink()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--core", type=Path, default=STEAM_GOLDEN_ERA_CORE if STEAM_GOLDEN_ERA_CORE.is_file() else DEFAULT_RELEASE_CORE)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--audit",
        action="store_true",
        help="Report custom localization coverage after applying the candidate overlay in memory. Implies --dry-run.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.audit:
        args.dry_run = True
    core = args.core if args.core.is_absolute() else Path.cwd() / args.core
    overlay: dict[str, bytes] = {}
    notes: list[str] = []
    with zipfile.ZipFile(core, "r") as release_zip:
        sync_multilingual_custom_lang_rows(release_zip, overlay, notes, read_json, write_json, upsert_lang_rows)
        if args.audit:
            missing, placeholder_mismatch, same_substantive, same_by_file, same_by_lang = audit_overlay(
                release_zip, overlay
            )
            print(
                "Audit after candidate overlay: "
                f"missing={missing} placeholder_mismatches={placeholder_mismatch} "
                f"same_as_english_substantive={same_substantive}"
            )
            print("same_as_english_by_file=" + json.dumps(dict(same_by_file), sort_keys=True))
            print("same_as_english_by_lang=" + json.dumps(dict(same_by_lang), sort_keys=True))
    print(f"Prepared {len(overlay)} multilingual Lang member update(s).")
    for note in notes[:80]:
        print(note)
    if len(notes) > 80:
        print(f"... {len(notes) - 80} more")
    backup = rewrite_zip(core, overlay, args.dry_run)
    if args.dry_run:
        print("Dry run only; Core.zip was not modified.")
    elif backup:
        print(f"Updated {core}")
        print(f"Backup: {backup}")
    else:
        print("No multilingual localization changes needed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
