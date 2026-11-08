#!/usr/bin/env python3
"""Fail-closed: every custom land-on barracks dwelling has title+description in all langs.

Land-on clones use ``homm3_landon_barracks_*`` SIDs. LocKit resolves
``{sid}_name`` / ``{sid}_description`` from ``Lang/*/texts/mapObjects.json``
``tokens`` (array alone is not enough). Donor ``barracks_homm3_*`` rows are
also required so the overlay mirror has a source text.
"""

from __future__ import annotations

import argparse
import json
import sys
import zipfile
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
RELEASE_PORT = REPO_ROOT / "tools" / "release_port"
if str(RELEASE_PORT) not in sys.path:
    sys.path.insert(0, str(RELEASE_PORT))

from analyze_core_overlay import DEFAULT_RELEASE_CORE  # noqa: E402
from homm3_landon_dwelling_lang import (  # noqa: E402
    REQUIRED_SUFFIXES,
    landon_barracks_pairs,
)


def _tokens_by_sid(doc: Any) -> dict[str, str]:
    if not isinstance(doc, dict):
        return {}
    rows = doc.get("tokens")
    if not isinstance(rows, list):
        return {}
    return {
        str(row.get("sid")): str(row.get("text") or "")
        for row in rows
        if isinstance(row, dict) and isinstance(row.get("sid"), str)
    }


def _lang_dirs(zf: zipfile.ZipFile) -> list[str]:
    return sorted(
        {
            entry.filename.split("/")[1]
            for entry in zf.infolist()
            if entry.filename.startswith("Lang/") and "/texts/mapObjects.json" in entry.filename
        }
    )


def validate_landon_dwelling_localization(core: Path, *, max_examples: int = 40) -> list[str]:
    errors: list[str] = []
    pairs = landon_barracks_pairs()
    if not pairs:
        return ["landon barracks donor map is empty"]

    with zipfile.ZipFile(core) as zf:
        names = set(zf.namelist())
        langs = _lang_dirs(zf)
        if "english" not in langs:
            errors.append("Core.zip missing Lang/english/texts/mapObjects.json")
            return errors

        lang_tokens: dict[str, dict[str, str]] = {}
        for lang in langs:
            member = f"Lang/{lang}/texts/mapObjects.json"
            if member not in names:
                errors.append(f"missing {member}")
                continue
            lang_tokens[lang] = _tokens_by_sid(json.loads(zf.read(member).decode("utf-8-sig")))

        english = lang_tokens.get("english") or {}
        examples = 0
        for donor, landon in sorted(pairs.items()):
            for suffix in REQUIRED_SUFFIXES:
                donor_sid = f"{donor}{suffix}"
                landon_sid = f"{landon}{suffix}"
                donor_text = str(english.get(donor_sid) or "").strip()
                if not donor_text:
                    if examples < max_examples:
                        errors.append(f"english tokens missing donor {donor_sid}")
                        examples += 1
                    elif examples == max_examples:
                        errors.append("... additional donor/landon localization errors truncated")
                        examples += 1
                    continue
                for lang, tokens in lang_tokens.items():
                    text = str(tokens.get(landon_sid) or "").strip()
                    if not text:
                        if examples < max_examples:
                            errors.append(f"{lang} tokens missing {landon_sid}")
                            examples += 1
                        elif examples == max_examples:
                            errors.append("... additional donor/landon localization errors truncated")
                            examples += 1
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--core", type=Path, default=DEFAULT_RELEASE_CORE)
    parser.add_argument("--max-examples", type=int, default=40)
    args = parser.parse_args(argv)
    core = args.core.resolve()
    if not core.is_file():
        print(f"ERROR: Core.zip not found: {core}")
        return 1
    errors = validate_landon_dwelling_localization(core, max_examples=args.max_examples)
    if errors:
        for err in errors:
            print(f"ERROR: {err}")
        print(f"landon dwelling localization validation failed: {len(errors)} error(s)")
        return 1
    pairs = landon_barracks_pairs()
    with zipfile.ZipFile(core) as zf:
        langs = _lang_dirs(zf)
    print(
        "landon dwelling localization validation passed: "
        f"{len(pairs)} dwellings x {len(REQUIRED_SUFFIXES)} fields x {len(langs)} languages"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
