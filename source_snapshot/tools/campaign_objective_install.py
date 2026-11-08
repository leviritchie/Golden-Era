#!/usr/bin/env python3
"""Install-time campaign objective quest-UI + LocKit helpers.

Continuity weave copies artifact maps and merges Lang overlays into Core.zip.
Those artifacts historically lacked quest-log bullets / translated ``*_main_goal_obj_*``
rows, so a weave install stomped live surgical patches.

Callers must:
1. Rewrite each installed Story_maps ``.map`` via ``apply_objective_bullets_to_map``
2. Inject English + phrasebook LocKit rows into overlay members before Core merge
3. Fail closed in post-install verify when bullets/SIDs are missing
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
_TOOLS = Path(__file__).resolve().parent
_EXP = ROOT / "experiments" / "campaign_port_poc"
_RELEASE = _TOOLS / "release_port"
for path in (_TOOLS, _EXP, _RELEASE):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from campaign_objective_text import objective_obj_sid  # noqa: E402
from patch_campaign_objective_quest_ui import patch_map_file  # noqa: E402
import homecoming_localization as loc  # noqa: E402
import multilingual_custom_lang as mcl  # noqa: E402
import port_homecoming_poc as poc  # noqa: E402


def apply_objective_bullets_to_map(map_path: Path) -> dict[str, Any]:
    """Fail-closed rewrite of one installed/artifact map. No backup (installer owns backups)."""
    return patch_map_file(map_path, backup=False)


def lockit_rows_from_patch_report(report: dict[str, Any]) -> dict[str, str]:
    mission_id = str(report["missionId"])
    bullets = list(report.get("bullets") or [])
    if not bullets:
        raise ValueError(f"{mission_id}: patch report has no bullets")
    rows: dict[str, str] = {}
    for index, bullet in enumerate(bullets, start=1):
        rows[objective_obj_sid(mission_id, index)] = str(bullet)
        if index == 1:
            rows[f"{mission_id}_main_goal_desc"] = str(bullet)
    # Keep title/intro from the English catalog when present.
    for sid in (f"{mission_id}_main_goal", f"{mission_id}_intro"):
        if sid in loc.CUSTOM_MAPS_EN:
            rows[sid] = loc.CUSTOM_MAPS_EN[sid]
    return rows


def localized_objective_text(lang: str, english_text: str) -> str:
    if lang == "english":
        return english_text
    phrasebook = mcl._phrasebook_translate(lang, english_text)
    if phrasebook:
        return phrasebook
    drafted = mcl._draft_translate(lang, english_text, {})
    if isinstance(drafted, str) and drafted.strip():
        return drafted.strip()
    return english_text


def build_localized_lockit_rows(lang: str, english_rows: dict[str, str]) -> dict[str, str]:
    return {
        sid: localized_objective_text(lang, text) for sid, text in english_rows.items()
    }


def inject_objective_lockit_into_overlay_members(
    overlay_members: dict[str, bytes],
    english_rows: dict[str, str],
) -> dict[str, Any]:
    """Merge objective SIDs into Lang/*/texts/customMaps.json overlay members."""
    if not english_rows:
        return {"langs": 0, "sids": 0}
    from map_load_preflight import merge_lang_sid_catalog_bytes

    # Force phrasebook reload so install picks up campaign_objective_bullets.json.
    mcl._PHRASEBOOK_EXACT = None
    mcl._PHRASEBOOK_TEMPLATES = None

    touched = 0
    for lang in loc.HOMECOMING_LANGS:
        member = f"Lang/{lang}/texts/customMaps.json"
        localized = build_localized_lockit_rows(lang, english_rows)
        rows = [{"sid": sid, "text": text} for sid, text in localized.items()]
        payload = (
            json.dumps({"tokens": rows, "array": list(rows)}, indent=2, ensure_ascii=False)
            + "\n"
        ).encode("utf-8")
        if member in overlay_members:
            overlay_members[member] = merge_lang_sid_catalog_bytes(
                overlay_members[member], payload
            )
        else:
            overlay_members[member] = payload
        touched += 1
    return {"langs": touched, "sids": len(english_rows)}


def assert_map_has_objective_bullets(map_path: Path) -> None:
    container = poc.read_olden_map_container(map_path)
    if len(container.chunks) < 4 or not isinstance(container.chunks[3], dict):
        raise ValueError(f"{map_path.name}: missing quest chunk[3]")
    quests = container.chunks[3].get("quests")
    if not isinstance(quests, list):
        raise ValueError(f"{map_path.name}: quests is not a list")
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
        raise ValueError(f"{map_path.name}: no main_goal quest")
    if main.get("desc") not in (None, ""):
        # New contract: parent desc stays null; bullets carry attributes.
        raise ValueError(
            f"{map_path.name}: main_goal.desc must be null for bullet UI "
            f"(got {main.get('desc')!r})"
        )
    subs = main.get("subQuests") or []
    if not isinstance(subs, list) or not subs:
        raise ValueError(f"{map_path.name}: main_goal has no subQuests")
    first = subs[0]
    if not isinstance(first, dict):
        raise ValueError(f"{map_path.name}: first subQuest is not an object")
    name = first.get("name")
    if not isinstance(name, str) or not name.endswith("_main_goal_obj_1"):
        raise ValueError(
            f"{map_path.name}: first visible subQuest name must be "
            f"* _main_goal_obj_1 LocKit SID (got {name!r})"
        )
    if name == "" or first.get("desc") == "":
        raise ValueError(f"{map_path.name}: empty subQuest name/desc would show LOC:")


def assert_core_has_objective_sids(
    core_zip: Path, required_sids: set[str]
) -> None:
    import zipfile

    if not required_sids:
        return
    with zipfile.ZipFile(core_zip, "r") as zf:
        member = "Lang/english/texts/customMaps.json"
        if member not in zf.namelist():
            raise ValueError(f"Core.zip missing {member}")
        doc = json.loads(zf.read(member).decode("utf-8-sig"))
        present: set[str] = set()
        for section in ("tokens", "array"):
            for row in doc.get(section) or []:
                if isinstance(row, dict) and isinstance(row.get("sid"), str):
                    present.add(str(row["sid"]))
        missing = sorted(sid for sid in required_sids if sid not in present)
        if missing:
            raise ValueError(
                "Core.zip english customMaps missing objective LocKit SIDs after install:\n- "
                + "\n- ".join(missing[:20])
                + (f"\n- ... ({len(missing)} total)" if len(missing) > 20 else "")
            )
