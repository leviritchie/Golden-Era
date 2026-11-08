#!/usr/bin/env python3
"""Merge objective-bullet translation packs into a LocKit phrasebook + Core.zip."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ART = ROOT / "artifacts" / "campaign_port_poc"
ENGLISH = ART / "objective_bullet_english_unique.json"
PACKS = (
    ART / "objective_bullet_translations_romance.json",
    ART / "objective_bullet_translations_central.json",
    ART / "objective_bullet_translations_slavic_cjk.json",
)
PHRASEBOOK = (
    ROOT
    / "tools"
    / "release_port"
    / "localization_phrasebooks"
    / "campaign_objective_bullets.json"
)


def merge_packs() -> dict:
    english = json.loads(ENGLISH.read_text(encoding="utf-8"))
    if not isinstance(english, list) or len(english) != 222:
        raise SystemExit(f"expected 222 english strings, got {type(english)}/{getattr(english, '__len__', lambda: '?')()}")

    merged: dict[str, dict[str, str]] = {text: {} for text in english}
    for path in PACKS:
        if not path.is_file():
            raise SystemExit(f"missing translation pack: {path}")
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise SystemExit(f"{path.name}: expected object")
        missing = [text for text in english if text not in data]
        if missing:
            raise SystemExit(f"{path.name}: missing {len(missing)} english keys, e.g. {missing[0]!r}")
        for text in english:
            row = data[text]
            if not isinstance(row, dict):
                raise SystemExit(f"{path.name}: bad row for {text!r}")
            for lang, value in row.items():
                if not isinstance(lang, str) or not isinstance(value, str) or not value.strip():
                    raise SystemExit(f"{path.name}: bad {lang!r} for {text!r}")
                if value.strip() == text:
                    continue
                merged[text][lang] = value.strip()

    entries = []
    for text in english:
        if not merged[text]:
            raise SystemExit(f"no translations for {text!r}")
        entries.append(
            {
                "matchType": "exact",
                "english": text,
                "translations": merged[text],
            }
        )
    return {
        "schema": "homm3_release_phrasebook_v1",
        "source": [
            "campaign objective quest-log bullets",
            "composer-2.5 translation packs",
        ],
        "entries": entries,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply-core", action="store_true", help="also upsert translated rows into Core.zip")
    parser.add_argument("--no-backup", action="store_true")
    args = parser.parse_args()

    book = merge_packs()
    PHRASEBOOK.parent.mkdir(parents=True, exist_ok=True)
    PHRASEBOOK.write_text(json.dumps(book, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {PHRASEBOOK} entries={len(book['entries'])}")

    if args.apply_core:
        sys.path.insert(0, str(ROOT / "tools"))
        from translate_campaign_objective_lockit import translate_and_upsert, DEFAULT_CORE

        # Force phrasebook reload in case module was imported earlier in-process.
        import multilingual_custom_lang as mcl

        mcl._PHRASEBOOK_EXACT = None
        mcl._PHRASEBOOK_TEMPLATES = None
        stats = translate_and_upsert(DEFAULT_CORE, backup=not args.no_backup)
        print(json.dumps(stats, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
