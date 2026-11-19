#!/usr/bin/env python3
"""Fail-closed gate for custom faction law trees: slot and icon must fit the law's effect.

Checks every core-enabled custom faction in a built ``Core.zip`` against
``custom_law_tree_layout.law_tree_problems``:

1. the tree is five lines of two groups, 2..4 laws per group, no law placed twice, and
   every placed law has a table row;
2. kingdom/hero laws sit in group 0 and army laws in group 1 (the vanilla columns);
3. Resource Riches I/II/III lead lines 0/2/4;
4. a law tied to one unit line is on a line of that tier's vanilla band;
5. every icon resolves: a live vanilla law icon, a unit of the faction that the law
   affects, or a shipped ``homm3_law_icons`` PNG;
6. resource, grant and astrology art is only on a law of that kind and such a law has
   that art; the art of a vanilla unit law is on no custom law;
7. no two placed laws have exactly the same bonuses (they would stack), except the pairs
   in ``PENDING_DUPLICATE_EFFECT_LAWS``, which are reported as warnings (none since
   2026-11-17).

Warnings (printed, not failing) are the design-decision cases: art from the other column,
laws in the table but not in the tree, shared icons and shared names.

``--propose`` prints the icon ``resolve_law_icons`` would pick for each law that fails
rule 6 or draws art from the other column. Icons are authored in
``custom_factions/law_overrides``; nothing is rewritten here.

Generated-artifact proof only: it reads the built data and does not show how the law
window draws. Runtime about 1 s.
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
import zipfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from validate_custom_faction_manifests import DEFAULT_MANIFEST_DIR, core_overlay_enabled, load_json  # noqa: E402
from custom_law_tree_layout import (  # noqa: E402
    custom_law_icon_keys,
    law_tree_problems,
    manifest_unit_lines,
    resolve_law_icons,
    vanilla_icon_owners,
    vanilla_law_tables,
)

DEFAULT_ICON_DIR = (
    ROOT / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod" / "homm3_law_icons"
)
ENGLISH_TEXT_PREFIX = "Lang/english/texts/"


def read_member(core: zipfile.ZipFile, member: str) -> Any:
    return json.loads(core.read(member).decode("utf-8-sig"))


def english_texts(core: zipfile.ZipFile) -> dict[str, str]:
    texts: dict[str, str] = {}
    for member in core.namelist():
        if not member.startswith(ENGLISH_TEXT_PREFIX) or not member.endswith(".json"):
            continue
        doc = read_member(core, member)
        if not isinstance(doc, dict):
            continue
        for key in ("tokens", "array"):
            for row in doc.get(key) or []:
                if isinstance(row, dict) and isinstance(row.get("sid"), str) and isinstance(row.get("text"), str):
                    texts[row["sid"]] = row["text"]
    return texts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--core", type=Path, required=True)
    parser.add_argument("--manifest-dir", type=Path, default=DEFAULT_MANIFEST_DIR)
    parser.add_argument("--icon-dir", type=Path, default=DEFAULT_ICON_DIR)
    parser.add_argument("--propose", action="store_true", help="Print replacement icons for the flagged laws.")
    parser.add_argument("--quiet-warnings", action="store_true", help="Print the warning count only.")
    args = parser.parse_args()

    if not args.icon_dir.is_dir():
        print(f"ERROR: custom law icon directory not found: {args.icon_dir}")
        return 1
    custom_icons = custom_law_icon_keys(args.icon_dir)
    checked = 0
    error_count = 0
    warning_count = 0
    with zipfile.ZipFile(args.core) as core:
        members = set(core.namelist())
        owners = vanilla_icon_owners(vanilla_law_tables(core))
        names = english_texts(core)
        for path in sorted(args.manifest_dir.glob("homm3_*.json")):
            manifest = load_json(path)
            if not isinstance(manifest, dict) or not core_overlay_enabled(manifest):
                continue
            faction_sid = str((manifest.get("identity") or {}).get("factionSid"))
            overlay = manifest.get("coreOverlay") or {}
            faction_member, laws_member = overlay.get("factionJson"), overlay.get("lawsTable")
            checked += 1
            if faction_member not in members or laws_member not in members:
                print(f"ERROR: {faction_sid}: Core.zip has no {faction_member} or {laws_member}")
                error_count += 1
                continue
            faction_doc = read_member(core, faction_member)
            faction_rows = faction_doc.get("array") if isinstance(faction_doc, dict) else None
            faction_row = faction_rows[0] if isinstance(faction_rows, list) and faction_rows else {}
            rows = [row for row in read_member(core, laws_member).get("array") or [] if isinstance(row, dict)]
            unit_lines = manifest_unit_lines(manifest)
            errors, warnings = law_tree_problems(
                faction_sid, faction_row.get("fractionLawsLines"), rows, owners, unit_lines, custom_icons, names
            )
            for message in errors:
                print(f"ERROR: {message}")
            if not args.quiet_warnings:
                for message in warnings:
                    print(f"warning: {message}")
            error_count += len(errors)
            warning_count += len(warnings)
            if args.propose:
                try:
                    changes, kept = resolve_law_icons(copy.deepcopy(rows), owners, unit_lines, {}, faction_sid)
                except RuntimeError as ex:
                    print(f"propose: {ex}")
                    continue
                for message in changes:
                    print(f"propose: {message}")
                for message in kept:
                    print(f"propose: no replacement, {message}")
    print(f"custom law tree layout: factions={checked} errors={error_count} warnings={warning_count}")
    if checked == 0:
        print(f"ERROR: no core-enabled custom faction manifests under {args.manifest_dir}")
        return 1
    return 1 if error_count else 0


if __name__ == "__main__":
    raise SystemExit(main())
