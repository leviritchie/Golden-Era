#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / 'artifacts' / 'custom_law_static' / 'custom_law_handoff_unique_texts.json'
FRAGMENTS = [
    ROOT / 'artifacts' / 'custom_law_static' / 'custom_law_phrasebook_central.json',
    ROOT / 'artifacts' / 'custom_law_static' / 'custom_law_phrasebook_cyrillic.json',
    ]
OUT = ROOT / 'tools' / 'release_port' / 'localization_phrasebooks' / 'custom_law_runtime_completion_20260619.json'
ALLOWED_LANGS = {
    'BRportugese', 'czech', 'french', 'german', 'hungarian', 'italian',
    'japanese', 'korean', 'polish', 'russian', 'spanish', 'turkish',
    'ukrainian', 'zhCN', 'zhTW',
}


def load_json(path: Path):
    with path.open('r', encoding='utf-8-sig') as handle:
        return json.load(handle)


def main() -> int:
    source_rows = load_json(SOURCE)
    expected = {
        (row['kind'], row['text'])
        for row in source_rows
        if str(row.get('text', '')).startswith('Hard case disabled:')
    }
    merged: dict[tuple[str, str], dict[str, str]] = {}
    skipped: list[str] = []
    errors: list[str] = []
    fragment_counts: dict[str, int] = {}
    for path in FRAGMENTS:
        if not path.is_file():
            skipped.append(f'missing fragment {path.name}')
            continue
        data = load_json(path)
        fragment_counts[path.name] = 0
        for entry in data.get('entries', []):
            english = entry.get('english')
            category = entry.get('category')
            kind = 'name' if category == 'custom_law_name' else 'description' if category == 'custom_law_description' else None
            key = (kind, english)
            if kind is None or key not in expected:
                skipped.append(str(english))
                continue
            translations = entry.get('translations')
            if not isinstance(translations, dict):
                errors.append(f'{path.name}: missing translations for {english!r}')
                continue
            clean: dict[str, str] = {}
            for lang, value in translations.items():
                if lang not in ALLOWED_LANGS:
                    errors.append(f'{path.name}: unexpected language {lang!r} for {english!r}')
                    continue
                if not isinstance(value, str) or not value.strip():
                    continue
                if value == english:
                    continue
                clean[lang] = value
            if not clean:
                errors.append(f'{path.name}: no usable translations for {english!r}')
                continue
            merged.setdefault(key, {}).update(clean)
            fragment_counts[path.name] += 1
    if errors:
        for error in errors[:200]:
            print('ERROR:', error)
        return 1
    entries = []
    languages = sorted({lang for translations in merged.values() for lang in translations})
    for kind, text in sorted(merged, key=lambda item: (item[0], item[1])):
        entries.append({
            'category': 'custom_law_name' if kind == 'name' else 'custom_law_description',
            'matchType': 'exact',
            'english': text,
            'translations': dict(sorted(merged[(kind, text)].items())),
        })
    payload = {
        'schema': 'homm3_release_phrasebook_v1',
        'source': [
            'custom_factions/custom_law_localization_handoff.json',
            'artifacts/custom_law_static/custom_law_handoff_unique_texts.json',
            'gpt-5.4-mini translation subagent central/cyrillic partial batches 2026-06-19',
        ],
        'languages': languages,
        'entries': entries,
        'knownPartial': {
            'reason': 'This phrasebook contains exact-match translations completed by valid GPT-5.4 mini central and Cyrillic subagent batches. Romance and CJK fragments require repair before integration; missing locale/text pairs remain queued in custom_factions/custom_law_localization_handoff.json.',
            'fragmentCounts': fragment_counts,
            'exactHardCaseDescriptionsMerged': len(entries),
            'skippedNonExactEnglishKeys': skipped,
        },
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'wrote {OUT} with {len(entries)} exact entries across {len(languages)} language(s); skipped={len(skipped)}')
    print('languages=' + ','.join(languages))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

