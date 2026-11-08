#!/usr/bin/env python3
"""Draft-translate campaign objective LocKit bullets into every Core.zip locale.

English ``*_main_goal_obj_*`` / related quest rows were inserted into all locales
as English placeholders. This tool uses the release-port translation memory +
draft translator (same path as ``build_homecoming_lang_translations.py``) and
upserts both ``tokens`` and ``array`` so LocKit does not show English or ``LOC:``.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "release_port"))
sys.path.insert(0, str(ROOT / "experiments" / "campaign_port_poc"))

from multilingual_custom_lang import (  # noqa: E402
    _draft_translate,
    _translation_memory,
)
import homecoming_localization as loc  # noqa: E402

DEFAULT_CORE = Path(
    r"V:/SteamLibrary/steamapps/common/Heroes of Might and Magic Olden Era - Golden Era"
    r"/HeroesOldenEra_Data/StreamingAssets/Core.zip"
)

OBJECTIVE_SID_RE = re.compile(
    r"(?i)^[a-z0-9_]+_(?:intro|main_goal|main_goal_desc|main_goal_obj_\d+)$"
)


def _read_json(zf: zipfile.ZipFile, name: str) -> Any:
    return json.loads(zf.read(name).decode("utf-8-sig"))


def _upsert_both_sections(doc: dict[str, Any], rows: dict[str, str]) -> tuple[int, int]:
    inserted = 0
    updated = 0
    if not isinstance(doc.get("tokens"), list):
        doc["tokens"] = []
    if not isinstance(doc.get("array"), list):
        doc["array"] = []
    for sid, text in rows.items():
        for section in ("tokens", "array"):
            section_rows = doc[section]
            replaced = False
            for index, row in enumerate(section_rows):
                if isinstance(row, dict) and row.get("sid") == sid:
                    if row.get("text") != text:
                        section_rows[index] = {"sid": sid, "text": text}
                        updated += 1
                    replaced = True
                    break
            if not replaced:
                section_rows.append({"sid": sid, "text": text})
                inserted += 1
    return inserted, updated


def _english_objective_rows(core: Path) -> dict[str, str]:
    # Prefer repo English catalog (includes newly generated bullets).
    rows = {
        sid: text
        for sid, text in loc.CUSTOM_MAPS_EN.items()
        if OBJECTIVE_SID_RE.fullmatch(sid)
    }
    with zipfile.ZipFile(core, "r") as zf:
        custom = _read_json(zf, "Lang/english/texts/customMaps.json")
        for section in ("tokens", "array"):
            for row in custom.get(section) or []:
                if not isinstance(row, dict):
                    continue
                sid = row.get("sid")
                text = row.get("text")
                if isinstance(sid, str) and OBJECTIVE_SID_RE.fullmatch(sid) and isinstance(text, str):
                    rows.setdefault(sid, text)
    if not rows:
        raise SystemExit("no campaign objective LocKit SIDs found")
    return rows


def translate_and_upsert(core: Path, *, backup: bool) -> dict[str, Any]:
    english_rows = _english_objective_rows(core)
    if backup:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        shutil.copy2(core, core.with_suffix(core.suffix + f".objective_translate_backup_{stamp}"))

    tmp = core.with_suffix(core.suffix + ".tmp_objective_translate")
    stats: dict[str, Any] = {
        "englishRows": len(english_rows),
        "locales": {},
    }
    with zipfile.ZipFile(core, "r") as zin:
        names = zin.namelist()
        member_payloads: dict[str, bytes] = {}
        for lang in loc.HOMECOMING_LANGS:
            member = f"Lang/{lang}/texts/customMaps.json"
            if member not in names:
                raise SystemExit(f"Core.zip missing {member}")
            doc = _read_json(zin, member)
            if lang == "english":
                localized_rows = dict(english_rows)
            else:
                memory = _translation_memory(zin, {}, lang, _read_json)
                # Authored packs win when present (fr/de + homecoming_lang_translations).
                authored: dict[str, str] = {}
                packs = loc.translations()
                pack = packs.get(lang) if isinstance(packs, dict) else None
                if isinstance(pack, dict):
                    file_pack = pack.get("customMaps.json")
                    if isinstance(file_pack, dict):
                        authored = {
                            sid: str(text)
                            for sid, text in file_pack.items()
                            if sid in english_rows and isinstance(text, str) and text.strip()
                            and text != english_rows[sid]
                        }
                localized_rows = {}
                for sid, english_text in english_rows.items():
                    # Prefer exact phrasebook hits over older glossary-only authored drafts.
                    from multilingual_custom_lang import _phrasebook_translate

                    phrasebook = _phrasebook_translate(lang, english_text)
                    if phrasebook:
                        localized_rows[sid] = phrasebook
                    elif sid in authored:
                        localized_rows[sid] = authored[sid]
                    else:
                        drafted = _draft_translate(lang, english_text, memory)
                        if not isinstance(drafted, str) or not drafted.strip():
                            raise SystemExit(f"empty draft for {lang}/{sid}")
                        localized_rows[sid] = drafted
            inserted, updated = _upsert_both_sections(doc, localized_rows)
            member_payloads[member] = json.dumps(doc, ensure_ascii=False, indent=2).encode("utf-8")
            same_as_english = sum(
                1
                for sid, text in localized_rows.items()
                if lang != "english" and text == english_rows[sid]
            )
            stats["locales"][lang] = {
                "inserted": inserted,
                "updated": updated,
                "sameAsEnglish": same_as_english,
            }

        with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED) as zout:
            for name in names:
                if name in member_payloads:
                    zout.writestr(name, member_payloads[name])
                else:
                    zout.writestr(name, zin.read(name))
    tmp.replace(core)
    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--core-zip", type=Path, default=DEFAULT_CORE)
    parser.add_argument("--no-backup", action="store_true")
    args = parser.parse_args()
    stats = translate_and_upsert(args.core_zip, backup=not args.no_backup)
    print(json.dumps(stats, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
