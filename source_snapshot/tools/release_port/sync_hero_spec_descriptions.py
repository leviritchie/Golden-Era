#!/usr/bin/env python3
"""Keep hero override specialization descriptions equal to the text the game shows.

The Core overlay derives each custom hero specialization description from its
bonus rows (describe_custom_specialization_bonus_row in
apply_release_core_overlay.py). That generated sentence replaces the
`specialization.descriptionText` stored in custom_factions/hero_overrides/*.json,
so a hand-written descriptionText only reaches the game for the few rows the
generator cannot describe.

This tool recomputes the generated sentence for every override and reports (or,
with --write, stores) it, so the override files, the ability editor and the wiki
all show what the game shows. Rows the generator cannot describe are listed as
hand-written: their descriptionText is the shipped text and must read well.

    python tools/release_port/sync_hero_spec_descriptions.py           # report drift, exit 1 if any
    python tools/release_port/sync_hero_spec_descriptions.py --write   # store generated text
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
import zipfile
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import apply_release_core_overlay as overlay  # noqa: E402


def load_core_spec_rows(core_path: Path) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    with zipfile.ZipFile(core_path) as core:
        for name in core.namelist():
            if not name.startswith("DB/heroes_specializations/") or not name.endswith(".json"):
                continue
            doc = json.loads(core.read(name).decode("utf-8-sig"))
            for row in doc.get("array") or []:
                if isinstance(row, dict) and isinstance(row.get("id"), str):
                    rows[row["id"]] = row
    return rows


def generated_text(hero_sid: str, spec: dict[str, Any], core_rows: dict[str, dict[str, Any]]) -> tuple[str | None, bool]:
    """Return (generated description or None, whether a Core row was found)."""
    core_row = core_rows.get(f"{hero_sid}_specialization")
    row = copy.deepcopy(core_row) if core_row else {}
    bonuses = spec.get("bonuses")
    if spec.get("mode") != "copy" and isinstance(bonuses, list) and bonuses:
        # The override owns these bonuses, so describe them even before the next Core install.
        row["bonuses"] = overlay.clean_custom_specialization_bonuses(hero_sid, bonuses)
    for override_key, row_key in (
        ("changeDisposition", "xHomm3ChangeDisposition"),
        ("masterfulSpellBaseSid", "xHomm3MasterfulSpellBaseSid"),
    ):
        if isinstance(spec.get(override_key), str) and spec[override_key].strip():
            row[row_key] = spec[override_key].strip()
    if not row.get("bonuses") and not row.get("xHomm3MasterfulSpellBaseSid"):
        return None, core_row is not None
    return overlay.describe_custom_specialization_bonus_row(row), core_row is not None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--core", type=Path, default=overlay.DEFAULT_RELEASE_CORE, help="Core.zip to read specialization rows from")
    parser.add_argument("--write", action="store_true", help="store the generated text in the override files")
    parser.add_argument("--list", action="store_true", help="print every specialization description")
    args = parser.parse_args()

    core_rows = load_core_spec_rows(args.core)
    drift = 0
    hand_written: list[tuple[str, str, str]] = []
    for path in sorted(overlay.HERO_OVERRIDE_DIR.glob("*.json")):
        raw = path.read_bytes()
        doc = json.loads(raw.decode("utf-8-sig"))
        changed = False
        for hero_sid, entry in (doc.get("heroOverrides") or {}).items():
            spec = entry.get("specialization") if isinstance(entry, dict) else None
            if not isinstance(spec, dict) or entry.get("enabled") is False:
                continue
            current = spec.get("descriptionText") if isinstance(spec.get("descriptionText"), str) else ""
            text, _found = generated_text(hero_sid, spec, core_rows)
            if text is None:
                hand_written.append((path.name, hero_sid, current))
                if args.list:
                    print(f"{hero_sid} [hand-written]: {current}")
                continue
            if args.list:
                print(f"{hero_sid}: {text}")
            if current.strip() != text:
                drift += 1
                if args.write:
                    spec["descriptionText"] = text
                    changed = True
                elif not args.list:
                    print(f"DRIFT {hero_sid}\n  override: {current}\n  in game:  {text}")
        if changed:
            newline = "\r\n" if b"\r\n" in raw else "\n"
            body = json.dumps(doc, indent=2, ensure_ascii=False) + "\n"
            bom = b"\xef\xbb\xbf" if raw.startswith(b"\xef\xbb\xbf") else b""
            path.write_bytes(bom + body.replace("\n", newline).encode("utf-8"))
            print(f"updated {path.name}")

    print(f"{drift} override description(s) {'rewritten' if args.write else 'differ from the generated text'}.")
    print(f"{len(hand_written)} hand-written description(s) ship as-is (the generator cannot describe their bonuses):")
    for file_name, hero_sid, current in hand_written:
        print(f"  {file_name}: {hero_sid}: {current}")
    return 0 if args.write or drift == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
