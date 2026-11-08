#!/usr/bin/env python3
"""Fail-closed contract: campaign town names must never be coordinate placeholders.

Root cause: H3M town objects without a custom name (``hasName`` false) used to
fall back to ``f"Town {sourceKey}"`` at PropCity emit, surfacing in-game as
``Town 0:29:6`` via ``*_city_name_town_0_29_6`` LocKit SIDs. HoMM3 itself
assigns a random unused per-faction pool name (``TownName.txt``) in that case;
the port now does the deterministic build-time equivalent via
``experiments/campaign_port_poc/h3_town_name_pool.assign_default_town_names``
(wired into ``build_layered_objects`` / approach_cell ``generate_map``), and
the PropCity emitter fails closed on any town that still has no name.

This validator pins the deployed-payload state:

1. No installed raw_translation ``.map`` ``propCities.customCityName`` may use
   the coordinate pattern ``*_city_name_town_<layer>_<x>_<y>``, and no installed
   english ``cities.json`` row may carry ``Town <layer>:<x>:<y>`` display text.
2. Every ``*_city_name_*`` SID referenced by an installed raw_translation map
   must resolve in the installed english ``cities.json`` (array ∪ tokens);
   missing rows render as player-visible ``LOC:`` placeholders.

Wired into ``tools/install_roe_castle_continuity_weave.py`` (installed-payload
gate alongside map-load preflight). Safe to run standalone anytime.
"""

from __future__ import annotations

import argparse
import gzip
import json
import re
import sys
import zipfile
from pathlib import Path
from typing import Any

SCHEMA = "homm3.campaign_town_name_contract.v1"
DEFAULT_GAME_ROOT = Path(
    r"V:\SteamLibrary\steamapps\common\Heroes of Might and Magic Olden Era - Golden Era"
)
CORE_ZIP_REL = Path("HeroesOldenEra_Data") / "StreamingAssets" / "Core.zip"
STORY_MAPS_REL = Path("HeroesOldenEra_Data") / "StreamingAssets" / "maps" / "Story_maps"

COORDINATE_SID_RE = re.compile(r"_city_name_town_\d+_\d+_\d+$")
COORDINATE_TEXT_RE = re.compile(r"^Town \d+:\d+:\d+$")
CUSTOM_CITY_NAME_RE = re.compile(rb'"customCityName":"([^"]+)"')


def prune_coordinate_city_rows_from_catalog_bytes(raw: bytes) -> tuple[bytes, int]:
    """Drop retired coordinate-placeholder city SIDs from a lang catalog blob.

    ``*_city_name_town_<layer>_<x>_<y>`` rows are the removed
    ``f"Town {sourceKey}"`` fallback bug class (h3_town_name_pool); no
    legitimate row can match the pattern. Lang merges are upsert-only, so
    installed catalogs keep stale rows forever unless they are pruned during
    the Core.zip rewrite. Unparseable blobs pass through unchanged.
    """
    try:
        doc = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return raw, 0
    if not isinstance(doc, dict):
        return raw, 0
    removed = 0
    for section in ("tokens", "array"):
        rows = doc.get(section)
        if not isinstance(rows, list):
            continue
        kept = [
            row
            for row in rows
            if not (
                isinstance(row, dict)
                and isinstance(row.get("sid"), str)
                and COORDINATE_SID_RE.search(row["sid"])
            )
        ]
        removed += len(rows) - len(kept)
        if len(kept) != len(rows):
            doc[section] = kept
    if not removed:
        return raw, 0
    return (json.dumps(doc, indent=2, ensure_ascii=False) + "\n").encode("utf-8"), removed


def read_map_bytes(map_path: Path) -> bytes:
    raw = map_path.read_bytes()
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    return raw


def city_name_sids_in_map(map_path: Path) -> list[str]:
    return [
        match.decode("utf-8", "replace")
        for match in CUSTOM_CITY_NAME_RE.findall(read_map_bytes(map_path))
    ]


def english_city_lang_rows(core_zip: Path) -> dict[str, str]:
    with zipfile.ZipFile(core_zip, "r") as source:
        doc = json.loads(source.read("Lang/english/texts/cities.json").decode("utf-8-sig"))
    rows: dict[str, str] = {}
    for section in ("array", "tokens"):
        for row in doc.get(section) or []:
            if isinstance(row, dict) and isinstance(row.get("sid"), str):
                rows.setdefault(row["sid"], str(row.get("text") or ""))
    return rows


def validate_installed_town_names(*, game_root: Path, core_zip: Path) -> list[str]:
    """Return contract violations for the installed campaign payload (empty = ok)."""
    issues: list[str] = []
    story_maps = game_root / STORY_MAPS_REL
    if not story_maps.is_dir():
        return [f"installed Story_maps directory missing: {story_maps}"]
    if not core_zip.is_file():
        return [f"installed Core.zip missing: {core_zip}"]

    lang_rows = english_city_lang_rows(core_zip)

    coordinate_text_sids = sorted(
        sid for sid, text in lang_rows.items() if COORDINATE_TEXT_RE.match(text.strip())
    )
    for sid in coordinate_text_sids:
        issues.append(
            f"installed cities.json row {sid!r} still carries coordinate display text "
            f"{lang_rows[sid]!r}; regenerate the mission with the HoMM3 pool assignment"
        )

    map_count = 0
    city_row_count = 0
    for map_path in sorted(story_maps.glob("h3_*_raw_translation.map")):
        map_count += 1
        for sid in city_name_sids_in_map(map_path):
            city_row_count += 1
            if COORDINATE_SID_RE.search(sid):
                issues.append(
                    f"{map_path.name}: propCities.customCityName {sid!r} is a coordinate "
                    "placeholder; unnamed H3M towns must be named via "
                    "h3_town_name_pool.assign_default_town_names at build time"
                )
            if "_city_name_" in sid and sid not in lang_rows:
                issues.append(
                    f"{map_path.name}: propCities.customCityName {sid!r} has no row in "
                    "installed Lang/english/texts/cities.json (would render as LOC:)"
                )
    if map_count == 0:
        issues.append(f"no h3_*_raw_translation.map payloads found under {story_maps}")
    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game-root", type=Path, default=DEFAULT_GAME_ROOT)
    parser.add_argument("--core-zip", type=Path, default=None)
    args = parser.parse_args()
    game_root = args.game_root.resolve()
    core_zip = (args.core_zip or (game_root / CORE_ZIP_REL)).resolve()

    issues = validate_installed_town_names(game_root=game_root, core_zip=core_zip)
    if issues:
        print(f"campaign town-name contract FAILED ({len(issues)} issue(s)):")
        for issue in issues:
            print(f"- {issue}")
        return 1
    print(f"campaign town-name contract ok (schema {SCHEMA})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
