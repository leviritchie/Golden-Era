#!/usr/bin/env python3
"""Validate multilingual HoMM3 custom localization coverage in Core.zip."""

from __future__ import annotations

import argparse
import json
import re
import sys
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any

from analyze_core_overlay import DEFAULT_RELEASE_CORE
from multilingual_custom_lang import TEXT_FILES, canonical_custom_text_files_for_sid, custom_unit_ability_view_sids


PLACEHOLDER_RE = re.compile(r"\{\d+\}")
SUBSTANTIVE_ENGLISH_RE = re.compile(
    r"[.!?:;]|"
    r"\b(?:attack|damage|recruit|spell|hero|enemy|friendly|city|town|"
    r"creature|unit|basic|advanced|expert|command|specialist|upg\.)\b",
    re.IGNORECASE,
)


def read_json(zf: zipfile.ZipFile, name: str) -> Any:
    with zf.open(name) as handle:
        return json.loads(handle.read().decode("utf-8-sig"))


def tokens_by_sid(doc: Any) -> dict[str, str]:
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


def is_substantive_english(text: str) -> bool:
    return len(text) > 32 or bool(SUBSTANTIVE_ENGLISH_RE.search(text))


def lang_dirs(zf: zipfile.ZipFile) -> list[str]:
    return sorted(
        {
            entry.filename.split("/")[1]
            for entry in zf.infolist()
            if entry.filename.startswith("Lang/") and "/texts/" in entry.filename
        }
        - {"english"}
    )


def validate(core: Path, max_examples: int) -> int:
    missing = 0
    placeholder_mismatch = 0
    same_as_english = 0
    noncanonical = 0
    same_by_file: Counter[str] = Counter()
    same_by_lang: Counter[str] = Counter()
    examples: list[str] = []

    with zipfile.ZipFile(core) as zf:
        names = set(zf.namelist())
        langs = lang_dirs(zf)
        unit_ability_sids = custom_unit_ability_view_sids(zf, {})
        for file_name in TEXT_FILES:
            english_name = f"Lang/english/texts/{file_name}"
            if english_name not in names:
                continue
            english_rows = tokens_by_sid(read_json(zf, english_name))
            canonical_english = {
                sid: text
                for sid, text in english_rows.items()
                if file_name in canonical_custom_text_files_for_sid(sid, unit_ability_sids)
            }
            for sid in english_rows:
                allowed = canonical_custom_text_files_for_sid(sid, unit_ability_sids)
                if allowed and file_name not in allowed:
                    noncanonical += 1
                    if len(examples) < max_examples:
                        examples.append(f"noncanonical English row {english_name}: {sid}")

            for lang in langs:
                localized_name = f"Lang/{lang}/texts/{file_name}"
                localized_rows = tokens_by_sid(read_json(zf, localized_name)) if localized_name in names else {}
                for sid in localized_rows:
                    allowed = canonical_custom_text_files_for_sid(sid, unit_ability_sids)
                    if allowed and file_name not in allowed:
                        noncanonical += 1
                        if len(examples) < max_examples:
                            examples.append(f"noncanonical localized row {localized_name}: {sid}")

                for sid, english_text in canonical_english.items():
                    localized_text = localized_rows.get(sid)
                    if localized_text is None:
                        missing += 1
                        if len(examples) < max_examples:
                            examples.append(f"missing {localized_name}: {sid}")
                    elif sorted(PLACEHOLDER_RE.findall(english_text)) != sorted(PLACEHOLDER_RE.findall(localized_text)):
                        placeholder_mismatch += 1
                        if len(examples) < max_examples:
                            examples.append(f"placeholder mismatch {localized_name}: {sid}")
                    elif localized_text == english_text and is_substantive_english(english_text):
                        same_as_english += 1
                        same_by_file[file_name] += 1
                        same_by_lang[lang] += 1
                        if len(examples) < max_examples:
                            examples.append(f"same as English {localized_name}: {sid} = {english_text!r}")

    print(
        "Multilingual custom localization audit: "
        f"missing={missing} placeholder_mismatches={placeholder_mismatch} "
        f"same_as_english_substantive={same_as_english} noncanonical_rows={noncanonical}"
    )
    print("same_as_english_by_file=" + json.dumps(dict(same_by_file), sort_keys=True))
    print("same_as_english_by_lang=" + json.dumps(dict(same_by_lang), sort_keys=True))
    for example in examples:
        print("example: " + example)
    return 1 if missing or placeholder_mismatch or same_as_english or noncanonical else 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--core", type=Path, default=DEFAULT_RELEASE_CORE)
    parser.add_argument("--max-examples", type=int, default=40)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    core = args.core if args.core.is_absolute() else Path.cwd() / args.core
    if not core.is_file():
        print(f"Core.zip not found: {core}", file=sys.stderr)
        return 2
    return validate(core, args.max_examples)


if __name__ == "__main__":
    raise SystemExit(main())
