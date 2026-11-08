#!/usr/bin/env python3
"""Patch installed campaign maps so quest-log objectives use LocKit bullets.

Vanilla Story maps put checklist text on each visible subquest ``name`` SID.
Our ports previously stuffed the full H3 objective into parent ``desc`` (menu-clipped
to 172 chars) and left the capture subquest ``name``/``desc`` empty, which shows as
``LOC:`` under the truncated journal entry.

This tool:
1. Splits each map's main-goal ``comment`` (full unclipped objective) into bullets
2. Rewrites the gzipped ``.map`` quest script accordingly (via length-prefixed
   Olden map container codec — never binary-splice into a chunk)
3. Upserts matching ``main_goal_obj_*`` rows into Core.zip ``customMaps.json``

Source/static + installed-payload update only; runtime quest UI remains user-validated.

IMPORTANT: Olden ``.map`` files are gzip of length-prefixed JSON chunks. Replacing
bytes inside a chunk without updating that chunk's varint length corrupts the
container (truncated JSON → “map invalid”). Always use read/write_olden_map_container.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "experiments" / "campaign_port_poc"))

import port_homecoming_poc as poc  # noqa: E402
from campaign_objective_text import (  # noqa: E402
    objective_obj_sid,
    split_objective_bullets,
)

DEFAULT_STORY_MAPS = Path(
    r"V:/SteamLibrary/steamapps/common/Heroes of Might and Magic Olden Era - Golden Era"
    r"/HeroesOldenEra_Data/StreamingAssets/maps/Story_maps"
)
DEFAULT_CORE_ZIP = Path(
    r"V:/SteamLibrary/steamapps/common/Heroes of Might and Magic Olden Era - Golden Era"
    r"/HeroesOldenEra_Data/StreamingAssets/Core.zip"
)


def _rewrite_main_goal(quest: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    mission_prefix = str(quest.get("sid") or "")
    if not mission_prefix.endswith("_main_goal"):
        raise ValueError(f"not a main_goal quest: {mission_prefix!r}")
    mission_id = mission_prefix[: -len("_main_goal")]
    objective_text = str(quest.get("comment") or "").strip()
    bullets = split_objective_bullets(objective_text)
    if not bullets:
        raise ValueError(f"{mission_id}: empty objective comment; cannot build bullets")

    existing = list(quest.get("subQuests") or [])
    primary = None
    for row in existing:
        if isinstance(row, dict) and str(row.get("sid") or "").endswith("_main_goal_capture"):
            primary = row
            break
    if primary is None and existing:
        primary = existing[0] if isinstance(existing[0], dict) else None
    primary_triggers = list((primary or {}).get("triggers") or [])

    new_subs: list[dict[str, Any]] = []
    for index, _bullet in enumerate(bullets, start=1):
        is_primary = index == 1
        new_subs.append(
            {
                "sid": (
                    f"{mission_id}_main_goal_capture"
                    if is_primary
                    else f"{mission_id}_main_goal_obj_{index}"
                ),
                "activeOnStart": True,
                "hidden": False,
                "name": objective_obj_sid(mission_id, index),
                "desc": None,
                "comment": "",
                "triggers": list(primary_triggers) if is_primary else [],
            }
        )

    updated = dict(quest)
    updated["desc"] = None
    updated["subQuests"] = new_subs
    return updated, bullets


def _quest_list_from_chunk3(chunk3: dict[str, Any]) -> list[dict[str, Any]]:
    quests = chunk3.get("quests")
    if not isinstance(quests, list):
        raise ValueError("chunk[3].quests is not a list")
    return quests


def patch_map_file(map_path: Path, *, backup: bool) -> dict[str, Any]:
    """Rewrite main-goal quest UI via the Olden map container codec (fail-closed)."""
    container = poc.read_olden_map_container(map_path)
    if len(container.chunks) < 4 or not isinstance(container.chunks[3], dict):
        raise ValueError(f"{map_path.name}: missing quest script chunk[3]")

    chunk3 = dict(container.chunks[3])
    quests = list(_quest_list_from_chunk3(chunk3))

    main_index = None
    for index, quest in enumerate(quests):
        if not isinstance(quest, dict):
            continue
        if quest.get("main") is True or str(quest.get("sid") or "").endswith("_main_goal"):
            main_index = index
            break
    if main_index is None:
        raise ValueError(f"{map_path.name}: no main_goal quest")

    updated_main, bullets = _rewrite_main_goal(quests[main_index])
    quests[main_index] = updated_main
    chunk3["quests"] = quests

    meta = container.chunks[0] if isinstance(container.chunks[0], dict) else {}
    hash_sum = str(meta.get("hashSum") or "")
    if not hash_sum:
        raise ValueError(f"{map_path.name}: meta.hashSum missing; refuse rewrite")

    new_chunks = list(container.chunks)
    new_chunks[3] = chunk3
    new_container = poc.OldenMapContainer(
        version=container.version,
        prefix_suffix=container.prefix_suffix,
        chunks=new_chunks,
    )

    if backup:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = map_path.with_suffix(map_path.suffix + f".objective_bullets_backup_{stamp}")
        shutil.copy2(map_path, backup_path)

    poc.write_olden_map_container(map_path, new_container, hash_sum)

    # Round-trip proof: refuse to leave an unreadable map behind.
    verify = poc.read_olden_map_container(map_path)
    if len(verify.chunks) < 4 or not isinstance(verify.chunks[3], dict):
        raise ValueError(f"{map_path.name}: post-write quest chunk unreadable")

    mission_id = str(updated_main["sid"])[: -len("_main_goal")]
    return {
        "map": str(map_path),
        "missionId": mission_id,
        "bulletCount": len(bullets),
        "bullets": bullets,
    }


def upsert_core_lockit(core_zip: Path, rows: dict[str, str], *, backup: bool) -> dict[str, int]:
    if backup:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        shutil.copy2(core_zip, core_zip.with_suffix(core_zip.suffix + f".objective_bullets_backup_{stamp}"))

    tmp = core_zip.with_suffix(core_zip.suffix + ".tmp_objective_bullets")
    inserted = 0
    updated = 0
    touched_members = 0
    with zipfile.ZipFile(core_zip, "r") as zin:
        names = zin.namelist()
        member_payloads: dict[str, bytes] = {}
        for name in names:
            if not name.startswith("Lang/") or not name.endswith("/texts/customMaps.json"):
                continue
            custom = json.loads(zin.read(name).decode("utf-8-sig"))
            by_sid: dict[str, dict[str, Any]] = {}
            for section in ("tokens", "array"):
                rows_list = custom.get(section)
                if not isinstance(rows_list, list):
                    if section == "tokens":
                        rows_list = []
                        custom["tokens"] = rows_list
                    else:
                        continue
                for row in rows_list:
                    if isinstance(row, dict) and isinstance(row.get("sid"), str):
                        by_sid[str(row["sid"])] = row
            if not isinstance(custom.get("tokens"), list):
                custom["tokens"] = []
            if not isinstance(custom.get("array"), list):
                custom["array"] = []
            for sid, text in rows.items():
                existing = by_sid.get(sid)
                if existing is not None and existing.get("text") == text:
                    for section in ("tokens", "array"):
                        section_rows = custom[section]
                        if not any(
                            isinstance(row, dict) and row.get("sid") == sid
                            for row in section_rows
                        ):
                            section_rows.append({"sid": sid, "text": text})
                            inserted += 1
                    continue
                if existing is not None:
                    updated += 1
                else:
                    inserted += 1
                for section in ("tokens", "array"):
                    section_rows = custom[section]
                    replaced = False
                    for index, row in enumerate(section_rows):
                        if isinstance(row, dict) and row.get("sid") == sid:
                            section_rows[index] = {"sid": sid, "text": text}
                            replaced = True
                            break
                    if not replaced:
                        section_rows.append({"sid": sid, "text": text})
                by_sid[sid] = {"sid": sid, "text": text}
            member_payloads[name] = json.dumps(custom, ensure_ascii=False, indent=2).encode("utf-8")
            touched_members += 1
        if not member_payloads:
            raise ValueError(f"{core_zip}: no Lang/*/texts/customMaps.json members")

        with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED) as zout:
            for name in names:
                if name in member_payloads:
                    zout.writestr(name, member_payloads[name])
                else:
                    zout.writestr(name, zin.read(name))
    tmp.replace(core_zip)
    return {
        "inserted": inserted,
        "updated": updated,
        "totalRows": len(rows),
        "members": touched_members,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--story-maps", type=Path, default=DEFAULT_STORY_MAPS)
    parser.add_argument("--core-zip", type=Path, default=DEFAULT_CORE_ZIP)
    parser.add_argument(
        "--mission",
        action="append",
        default=[],
        help="Optional missionId filter (repeatable). Default: all h3_*_raw_translation maps.",
    )
    parser.add_argument("--skip-core", action="store_true")
    parser.add_argument("--no-backup", action="store_true")
    args = parser.parse_args()

    maps = sorted(args.story_maps.glob("h3_*_raw_translation.map"))
    if not maps:
        raise SystemExit(f"no campaign maps under {args.story_maps}")

    wanted = set(args.mission or [])
    reports: list[dict[str, Any]] = []
    lockit_rows: dict[str, str] = {}

    for map_path in maps:
        try:
            container = poc.read_olden_map_container(map_path)
        except Exception as exc:
            print(f"SKIP {map_path.name}: unreadable map container ({exc})")
            continue
        if len(container.chunks) < 4 or not isinstance(container.chunks[3], dict):
            print(f"SKIP {map_path.name}: missing quest chunk[3]")
            continue
        try:
            quests = _quest_list_from_chunk3(container.chunks[3])
        except ValueError as exc:
            print(f"SKIP {map_path.name}: {exc}")
            continue
        main = next(
            (
                q
                for q in quests
                if isinstance(q, dict)
                and (q.get("main") is True or str(q.get("sid") or "").endswith("_main_goal"))
            ),
            None,
        )
        if main is None:
            print(f"SKIP {map_path.name}: no main_goal")
            continue
        mission_id = str(main["sid"])[: -len("_main_goal")]
        if wanted and mission_id not in wanted:
            continue
        report = patch_map_file(map_path, backup=not args.no_backup)
        reports.append(report)
        for index, bullet in enumerate(report["bullets"], start=1):
            lockit_rows[objective_obj_sid(mission_id, index)] = bullet
            if index == 1:
                lockit_rows[f"{mission_id}_main_goal_desc"] = bullet
        print(
            f"OK {map_path.name}: {report['bulletCount']} bullets "
            f"({mission_id})"
        )

    if not reports:
        raise SystemExit("no maps patched")

    if not args.skip_core:
        stats = upsert_core_lockit(args.core_zip, lockit_rows, backup=not args.no_backup)
        print(
            f"Core.zip customMaps: inserted={stats['inserted']} "
            f"updated={stats['updated']} rows={stats['totalRows']} "
            f"members={stats['members']}"
        )

    print(f"Patched {len(reports)} maps")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
