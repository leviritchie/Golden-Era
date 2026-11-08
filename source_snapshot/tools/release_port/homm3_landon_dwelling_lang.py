#!/usr/bin/env python3
"""Mirror barracks_homm3_* map-object loc onto homm3_landon_barracks_* clones.

Campaign / RMG land-on dwellings use clone SIDs. UI title/description resolve via
LocKit ``mapObjects.json`` tokens keyed by the live object SID, so donor-only
rows leave land-on visits blank. Copy name/description(/narrative) from each
donor onto its landon clone across every Lang pack without overwriting
already-authored landon rows (e.g. Homecoming castle 1-5).
"""

from __future__ import annotations

import json
import sys
import zipfile
from pathlib import Path
from typing import Any, Callable

REPO_ROOT = Path(__file__).resolve().parents[2]
_CAMPAIGN_POC = REPO_ROOT / "experiments" / "campaign_port_poc"
if str(_CAMPAIGN_POC) not in sys.path:
    sys.path.insert(0, str(_CAMPAIGN_POC))

from homm3_external_dwelling_map import HOMM3_LANDON_BARRACKS_BY_DONOR  # noqa: E402

MAP_OBJECTS_TEXT = "mapObjects.json"
REQUIRED_SUFFIXES = ("_name", "_description")
OPTIONAL_SUFFIXES = ("_narrativeDescription",)
ALL_SUFFIXES = REQUIRED_SUFFIXES + OPTIONAL_SUFFIXES


def landon_barracks_pairs() -> dict[str, str]:
    return dict(HOMM3_LANDON_BARRACKS_BY_DONOR)


def _lang_dirs(release_zip: zipfile.ZipFile) -> list[str]:
    langs = {
        entry.filename.split("/")[1]
        for entry in release_zip.infolist()
        if entry.filename.startswith("Lang/") and "/texts/" in entry.filename
    }
    return sorted(langs)


def _read_overlay_or_zip(
    release_zip: zipfile.ZipFile,
    output: dict[str, bytes],
    name: str,
    read_json: Callable[[zipfile.ZipFile, str], Any],
) -> Any:
    if name in output:
        return json.loads(output[name].decode("utf-8-sig"))
    return read_json(release_zip, name)


def _tokens_by_sid(doc: Any) -> dict[str, str]:
    if not isinstance(doc, dict):
        return {}
    out: dict[str, str] = {}
    for section in ("tokens", "array"):
        rows = doc.get(section)
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            sid = row.get("sid")
            text = row.get("text")
            if isinstance(sid, str) and isinstance(text, str) and sid not in out:
                out[sid] = text
    return out


def mirror_landon_barracks_lang_rows(
    release_zip: zipfile.ZipFile,
    output: dict[str, bytes],
    notes: list[str],
    read_json: Callable[[zipfile.ZipFile, str], Any],
    write_json: Callable[[Any], bytes],
    upsert_lang_rows: Callable[[dict[str, Any], list[dict[str, str]]], bool],
    *,
    fail_closed_english: bool = True,
) -> None:
    """Ensure every landon barracks clone has title+description loc in all langs."""
    pairs = landon_barracks_pairs()
    langs = _lang_dirs(release_zip)
    if "english" not in langs:
        langs = ["english", *langs]

    english_name = f"Lang/english/texts/{MAP_OBJECTS_TEXT}"
    english_doc = _read_overlay_or_zip(release_zip, output, english_name, read_json)
    english_texts = _tokens_by_sid(english_doc)

    missing_donor: list[str] = []
    for donor, _landon in sorted(pairs.items()):
        for suffix in REQUIRED_SUFFIXES:
            if not str(english_texts.get(f"{donor}{suffix}") or "").strip():
                missing_donor.append(f"{donor}{suffix}")
    if missing_donor and fail_closed_english:
        preview = ", ".join(missing_donor[:12])
        more = f" (+{len(missing_donor) - 12} more)" if len(missing_donor) > 12 else ""
        raise RuntimeError(
            "landon barracks localization requires donor mapObjects rows before mirror: "
            f"{preview}{more}"
        )

    inserted_total = 0
    for lang in langs:
        lang_name = f"Lang/{lang}/texts/{MAP_OBJECTS_TEXT}"
        try:
            doc = _read_overlay_or_zip(release_zip, output, lang_name, read_json)
        except (KeyError, UnicodeDecodeError, json.JSONDecodeError):
            doc = {"tokens": [], "array": []}
        if not isinstance(doc, dict):
            doc = {"tokens": [], "array": []}
        existing = _tokens_by_sid(doc)
        rows: list[dict[str, str]] = []
        for donor, landon in pairs.items():
            for suffix in ALL_SUFFIXES:
                landon_sid = f"{landon}{suffix}"
                if str(existing.get(landon_sid) or "").strip():
                    continue
                donor_sid = f"{donor}{suffix}"
                # Prefer same-locale donor text. Do not English-fill other langs here —
                # that blocks multilingual sync from drafting/memory-translating.
                text = str(existing.get(donor_sid) or "").strip()
                if not text and lang == "english":
                    text = str(english_texts.get(donor_sid) or "").strip()
                if not text:
                    if suffix in OPTIONAL_SUFFIXES:
                        continue
                    if lang == "english" and fail_closed_english:
                        raise RuntimeError(f"missing donor text for {donor_sid}")
                    continue
                rows.append({"sid": landon_sid, "text": text})
        if rows and upsert_lang_rows(doc, rows):
            output[lang_name] = write_json(doc)
            inserted_total += len(rows)
            notes.append(f"mirror landon barracks mapObjects loc {lang} (+{len(rows)})")

    if inserted_total:
        notes.append(
            f"mirror landon barracks localization total rows inserted/updated={inserted_total} "
            f"pairs={len(pairs)} langs={len(langs)}"
        )
