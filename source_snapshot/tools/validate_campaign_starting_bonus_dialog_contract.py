#!/usr/bin/env python3
"""Validate Day-1 starting-bonus Dialog wiring from H3C-derived catalogs.

Pins:
  - H3C START_BONUS decode for Homecoming / Razor Claw / Guardian Angels
  - mechanics spell map for Prayer → Arina's Touch scroll
  - generated QuestScript day-1 Dialog + mapActions for installed pilots

Runtime choice/grant remains user-unvalidated.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]

PILOTS: tuple[dict[str, Any], ...] = (
    {
        "missionId": "homecoming",
        "mapSid": "h3_roe_castle_homecoming_raw_translation",
        "artifactRoot": Path("artifacts/campaign_port_poc/homecoming_poc/raw_translation_map"),
        "heroSid": "homm3_castle_hero_7",
        "expectKinds": ("resource", "unit", "item"),
    },
    {
        "missionId": "razor_claw",
        "mapSid": "h3_stronghold_razor_claw_raw_translation",
        "artifactRoot": Path(
            "artifacts/campaign_port_poc/ab_sod_campaigns/razor_claw/raw_translation_map"
        ),
        "heroSid": "homm3_stronghold_hero_17",
        "expectKinds": ("unit", "unit", "unit"),
    },
)


def require(condition: bool, message: str, errors: list[str]) -> None:
    if not condition:
        errors.append(message)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def campaign_dialog_folder_name(mission_id: str) -> str:
    parts = [part for part in mission_id.replace("-", "_").split("_") if part]
    return "".join(part[:1].upper() + part[1:] for part in parts) or mission_id


def absolute_day1_has_bonus_dialog(chunk3: dict[str, Any], mission_id: str, dialog_sid: str) -> bool:
    intro_sid = f"{mission_id}_intro"
    for quest in chunk3.get("quests") or []:
        if not isinstance(quest, dict) or quest.get("sid") != intro_sid:
            continue
        for sub in quest.get("subQuests") or []:
            for trigger in sub.get("triggers") or []:
                conds = trigger.get("conditions") or []
                if not conds or conds[0].get("c") != "StartTurn":
                    continue
                params = conds[0].get("p") or []
                if len(params) < 2:
                    continue
                week = int(params[0])
                day = int(params[1])
                absolute = (week - 1) * 7 + day
                if absolute != 1:
                    continue
                actions = trigger.get("actions") or []
                if any(
                    action.get("a") == "Dialog" and (action.get("p") or [None])[0] == dialog_sid
                    for action in actions
                ):
                    return True
    return False


def validate_static_catalog(repo_root: Path, errors: list[str]) -> None:
    sys.path.insert(0, str(repo_root / "experiments" / "campaign_port_poc"))
    import campaign_starting_bonus as starting_bonus  # type: ignore
    import h3_spell_to_oe_magic as spell_map  # type: ignore

    home = starting_bonus.resolve_starting_bonus(
        "homecoming", hero_sid="homm3_castle_hero_7"
    )
    require(home is not None, "homecoming: expected H3C START_BONUS catalog", errors)
    if home:
        labels = [str(o["label"]) for o in home["options"]]
        require(
            any("Pikeman" in label for label in labels),
            f"homecoming: expected Pikemen option, got {labels}",
            errors,
        )
        require(
            any("First Aid" in label for label in labels),
            f"homecoming: expected First Aid Tent option, got {labels}",
            errors,
        )

    razor = starting_bonus.resolve_starting_bonus(
        "razor_claw", hero_sid="homm3_stronghold_hero_17"
    )
    require(razor is not None, "razor_claw: expected H3C START_BONUS catalog", errors)

    angels = starting_bonus.resolve_starting_bonus(
        "guardian_angels", hero_sid="homm3_castle_hero_0"
    )
    require(angels is not None, "guardian_angels: expected H3C START_BONUS catalog", errors)
    if angels:
        scroll = next(
            (
                option
                for option in angels["options"]
                if any(g.get("kind") == "item" and "arinas_hymn" in str(g.get("itemSid")) for g in option["grants"])
            ),
            None,
        )
        require(
            scroll is not None,
            "guardian_angels: Prayer scroll must map to Arina's Touch scroll item",
            errors,
        )
        mapping = spell_map.spell_mapping_record(48)
        require(
            mapping["oeMagicSid"] == "day_9_magic_arinas_hymn",
            f"spell 48 (prayer) must map to day_9_magic_arinas_hymn, got {mapping}",
            errors,
        )

    # Unmapped options are omitted; missions still emit the remaining choices.
    reduced = starting_bonus.resolve_starting_bonus(
        "safe_passage", hero_sid="homm3_castle_hero_0"
    )
    require(reduced is not None, "safe_passage: expected reduced START_BONUS catalog", errors)
    if reduced:
        require(
            len(reduced["options"]) == 2,
            f"safe_passage: expected 2 emitted options after omitting Logistics, got {len(reduced['options'])}",
            errors,
        )
        require(
            len(reduced.get("omittedOptions") or []) == 1,
            f"safe_passage: expected 1 omitted option, got {reduced.get('omittedOptions')}",
            errors,
        )
    harvest = starting_bonus.resolve_starting_bonus(
        "season_of_harvest", hero_sid="homm3_necropolis_hero_0"
    )
    require(harvest is not None, "season_of_harvest: expected reduced START_BONUS catalog", errors)
    if harvest:
        require(
            len(harvest["options"]) == 1,
            f"season_of_harvest: expected 1 emitted option after omitting horde buildings, got {len(harvest['options'])}",
            errors,
        )

    # BUILDING answers must use classic hall names, not "Main level N" (hero-level misread).
    for mission_id, hero_sid, expected_label in (
        ("groundbreaking", "homm3_dungeon_hero_0", "City Hall"),
        ("culling_the_weak", "homm3_dungeon_hero_0", "City Hall"),
        ("gathering_the_legion", "homm3_necropolis_hero_0", "City Hall"),
        ("final_peace", "homm3_necropolis_hero_0", "City Hall"),
    ):
        building_bonus = starting_bonus.resolve_starting_bonus(
            mission_id, hero_sid=hero_sid
        )
        require(
            building_bonus is not None,
            f"{mission_id}: expected START_BONUS catalog with building option",
            errors,
        )
        if not building_bonus:
            continue
        labels = [str(option["label"]) for option in building_bonus["options"]]
        require(
            expected_label in labels,
            f"{mission_id}: expected building answer {expected_label!r}, got {labels}",
            errors,
        )
        require(
            not any(label.startswith("Main level") for label in labels),
            f"{mission_id}: must not emit ambiguous Main level N labels, got {labels}",
            errors,
        )


def validate_pilot(repo_root: Path, pilot: dict[str, Any], errors: list[str]) -> None:
    sys.path.insert(0, str(repo_root / "experiments" / "campaign_port_poc"))
    import campaign_starting_bonus as starting_bonus  # type: ignore
    import port_homecoming_poc as poc  # type: ignore

    mission_id = str(pilot["missionId"])
    map_sid = str(pilot["mapSid"])
    hero_sid = str(pilot["heroSid"])
    root = repo_root / pilot["artifactRoot"]
    map_path = root / "maps" / f"{map_sid}.map"
    require(map_path.is_file(), f"{mission_id}: missing map {map_path}", errors)
    if not map_path.is_file():
        return

    spec = starting_bonus.resolve_starting_bonus(
        mission_id,
        hero_sid=hero_sid,
        mission_title=mission_id,
    )
    require(spec is not None, f"{mission_id}: catalog missing", errors)
    if spec is None:
        return
    dialog_sid = str(spec["dialogSid"])
    counter_sid = str(spec["counterSid"])

    chunk3 = poc.read_olden_map_container(map_path).chunks[3]
    require(isinstance(chunk3, dict), f"{mission_id}: map chunk 3 missing", errors)
    if not isinstance(chunk3, dict):
        return

    require(
        absolute_day1_has_bonus_dialog(chunk3, mission_id, dialog_sid),
        f"{mission_id}: day-1 StartTurn must Dialog {dialog_sid!r}",
        errors,
    )
    counter = next(
        (
            row
            for row in (chunk3.get("counters") or [])
            if isinstance(row, dict) and row.get("sid") == counter_sid
        ),
        None,
    )
    require(counter is not None, f"{mission_id}: missing counter {counter_sid}", errors)

    folder = campaign_dialog_folder_name(mission_id)
    dialog_path = (
        root
        / "core_overlay"
        / "DB"
        / "dialogs"
        / "dialogs"
        / "custom_maps"
        / folder
        / f"{dialog_sid}.json"
    )
    require(dialog_path.is_file(), f"{mission_id}: missing dialog overlay {dialog_path}", errors)
    if not dialog_path.is_file():
        return
    dialog_doc = read_json(dialog_path)
    dialogs = dialog_doc.get("array") if isinstance(dialog_doc, dict) else None
    require(
        isinstance(dialogs, list) and dialogs,
        f"{mission_id}: dialog overlay array empty",
        errors,
    )
    if not isinstance(dialogs, list) or not dialogs:
        return
    slides = {
        slide.get("id"): slide
        for slide in (dialogs[0].get("slides") or [])
        if isinstance(slide, dict)
    }
    start = slides.get("start")
    require(isinstance(start, dict), f"{mission_id}: dialog missing start slide", errors)
    if not isinstance(start, dict):
        return
    answers = start.get("answers") or []
    require(
        isinstance(answers, list) and len(answers) == len(spec["options"]),
        f"{mission_id}: expected {len(spec['options'])} answers, got {len(answers) if isinstance(answers, list) else answers!r}",
        errors,
    )
    for index, option in enumerate(spec["options"]):
        slide_id = f"opt_{index}"
        reward = slides.get(slide_id)
        require(isinstance(reward, dict), f"{mission_id}: missing reward slide {slide_id}", errors)
        if not isinstance(reward, dict):
            continue
        map_actions = reward.get("mapActions") or []
        expected = starting_bonus.map_actions_for_option(
            mission_id=mission_id,
            hero_sid=hero_sid,
            option=option,
            option_index=index,
        )
        require(
            map_actions == expected,
            f"{mission_id}: {slide_id} mapActions mismatch\n  got={map_actions}\n  expected={expected}",
            errors,
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    args = parser.parse_args()
    errors: list[str] = []
    validate_static_catalog(args.repo_root, errors)
    for pilot in PILOTS:
        validate_pilot(args.repo_root, pilot, errors)
    if errors:
        print("FAIL: campaign starting-bonus dialog contract")
        for error in errors:
            print(f"  - {error}")
        return 1
    print("OK: campaign starting-bonus dialog contract")
    print("  - static H3C catalogs (homecoming, razor_claw, guardian_angels Prayer→Arina)")
    for pilot in PILOTS:
        print(f"  - pilot artifact {pilot['missionId']} ({pilot['mapSid']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
