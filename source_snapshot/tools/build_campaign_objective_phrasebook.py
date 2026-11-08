#!/usr/bin/env python3
"""Build an exact phrasebook for campaign objective LocKit bullets via OpenAI.

Writes ``localization_phrasebooks/campaign_objective_bullets.json`` so
``_draft_translate`` / Core.zip locale upserts can stop leaving English prose.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "experiments" / "campaign_port_poc"))

import homecoming_localization as loc  # noqa: E402

OUT = (
    ROOT
    / "tools"
    / "release_port"
    / "localization_phrasebooks"
    / "campaign_objective_bullets.json"
)

OBJECTIVE_SID_RE = re.compile(
    r"(?i)^[a-z0-9_]+_(?:main_goal_obj_\d+|main_goal_desc)$"
)

TARGET_LANGS = [lang for lang in loc.HOMECOMING_LANGS if lang != "english"]

LANG_LABELS = {
    "BRportugese": "Brazilian Portuguese",
    "czech": "Czech",
    "french": "French",
    "german": "German",
    "hungarian": "Hungarian",
    "italian": "Italian",
    "japanese": "Japanese",
    "korean": "Korean",
    "polish": "Polish",
    "russian": "Russian",
    "spanish": "Spanish",
    "turkish": "Turkish",
    "ukrainian": "Ukrainian",
    "zhCN": "Simplified Chinese",
    "zhTW": "Traditional Chinese",
}


def unique_objective_texts() -> list[str]:
    texts = sorted(
        {
            text
            for sid, text in loc.CUSTOM_MAPS_EN.items()
            if OBJECTIVE_SID_RE.fullmatch(sid) and isinstance(text, str) and text.strip()
        },
        key=lambda value: (len(value), value),
    )
    if not texts:
        raise SystemExit("no objective texts found in CUSTOM_MAPS_EN")
    return texts


def translate_batch(client, lang: str, batch: list[str]) -> dict[str, str]:
    label = LANG_LABELS[lang]
    payload = {str(index): text for index, text in enumerate(batch)}
    prompt = (
        f"Translate each Heroes of Might and Magic campaign objective line into {label}.\n"
        "Return ONLY a JSON object mapping the same string keys to translated strings.\n"
        "Keep proper names (Catherine, Gelu, Terraneus, Highcastle, Sandro, Mutare, etc.).\n"
        "Do not add quotes around the whole JSON in markdown. No commentary.\n"
        f"Input JSON:\n{json.dumps(payload, ensure_ascii=False)}"
    )
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        temperature=0.2,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a professional game localizer for Heroes of Might and Magic. "
                    "Output valid JSON only."
                ),
            },
            {"role": "user", "content": prompt},
        ],
    )
    content = response.choices[0].message.content or ""
    content = content.strip()
    if content.startswith("```"):
        content = re.sub(r"^```(?:json)?\s*", "", content)
        content = re.sub(r"\s*```$", "", content)
    data = json.loads(content)
    if not isinstance(data, dict):
        raise SystemExit(f"{lang}: expected JSON object, got {type(data).__name__}")
    out: dict[str, str] = {}
    for index, english in enumerate(batch):
        key = str(index)
        if key not in data or not isinstance(data[key], str) or not data[key].strip():
            raise SystemExit(f"{lang}: missing translation for index {index}: {english!r}")
        out[english] = data[key].strip()
    return out


def build_phrasebook(texts: list[str], *, batch_size: int, sleep_s: float) -> dict:
    from openai import OpenAI

    client = OpenAI()
    # english -> {lang: translation}
    by_english: dict[str, dict[str, str]] = {text: {} for text in texts}
    for lang in TARGET_LANGS:
        print(f"translating {lang} ({len(texts)} strings)...", flush=True)
        for start in range(0, len(texts), batch_size):
            batch = texts[start : start + batch_size]
            translated = translate_batch(client, lang, batch)
            for english, value in translated.items():
                if value != english:
                    by_english[english][lang] = value
            print(f"  {lang}: {min(start + batch_size, len(texts))}/{len(texts)}", flush=True)
            if sleep_s > 0:
                time.sleep(sleep_s)
    entries = []
    for english in texts:
        translations = by_english[english]
        if not translations:
            continue
        entries.append(
            {
                "matchType": "exact",
                "english": english,
                "translations": translations,
            }
        )
    return {
        "schema": "homm3_release_phrasebook_v1",
        "source": [
            "campaign objective quest-log bullets",
            "openai gpt-4o-mini batch translation",
        ],
        "entries": entries,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-size", type=int, default=15)
    parser.add_argument("--sleep", type=float, default=0.2)
    parser.add_argument("--limit", type=int, default=0, help="optional debug limit")
    args = parser.parse_args()
    texts = unique_objective_texts()
    if args.limit > 0:
        texts = texts[: args.limit]
    book = build_phrasebook(texts, batch_size=max(1, args.batch_size), sleep_s=max(0.0, args.sleep))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(book, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUT} entries={len(book['entries'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
