#!/usr/bin/env python3
"""Day-1 QuestScript Dialog starting-bonus choices for campaign missions.

HoMM3 campaign missions offer a choose-one starting bonus. StoryHub MissionVariant
payloads cannot express additive creature/item grants safely, so this module emits
a native Core multi-answer Dialog on StartTurn day 1 instead:

  prompt slide → answers → reward slides with native mapActions

Bonus catalogs are derived from H3C travel START_BONUS options (not hand lists).
Options that cannot map to a native grant are omitted; remaining choices are still
emitted. Grant verbs:

  RESOURCE       → GiveRes (sulfur→dust; rare/common expand to multiple resources)
  MONSTER        → GiveUnitHero
  ARTIFACT       → GiveItemHero
  SPELL_SCROLL   → GiveItemHero (mechanics-matched OE scroll item)
  SPELL          → AddSpellHero (mechanics-matched OE magic)
  PRIMARY_SKILL  → GiveStatsHero (offence/defence/spellPower/intelligence)
  BUILDING       → UnlockBuildingCity (requires mission start-city entity SID)
  SECONDARY_SKILL→ omitted (no stock dialog verb)

Hero targeting uses the mission's deterministic spawn.heroSid.

Proof boundary: source/static + generated-artifact. Runtime choice/grant remains
user-unvalidated until playtested.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from approach_cell.surface_emit import MAP_EVENT_GUARD_UNIT_BY_CREATURE_TYPE
from h3_building_to_oe import olden_unlock_for_vcmi_building
from h3_spell_to_oe_magic import spell_mapping_record
from h3c_starting_bonuses import (
    RESOURCE_COMMON,
    RESOURCE_RARE,
    starting_bonuses_for_mission,
)
from vanilla_stock.h3_artifact_stock_map import stock_item_sid_for_h3_artifact_id

_REPO_ROOT = Path(__file__).resolve().parents[2]

# H3 resource slot → GiveRes id. Sulfur has no OE resource; dust is the explicit proxy.
H3_RESOURCE_TO_GIVE_RES: dict[int, str] = {
    0: "wood",
    1: "mercury",
    2: "ore",
    3: "dust",  # sulfur proxy
    4: "crystals",
    5: "gemstones",
    6: "gold",
}

RARE_RESOURCES: tuple[str, ...] = ("mercury", "dust", "crystals", "gemstones")
COMMON_RESOURCES: tuple[str, ...] = ("wood", "ore")

# GiveStatsHero stock param names (campaign dialogs).
PRIMARY_STAT_PARAMS: tuple[tuple[str, str], ...] = (
    ("attack", "offence"),
    ("defense", "defence"),
    ("power", "spellPower"),
    ("knowledge", "intelligence"),
)

H3_SECONDARY_SKILL_NAMES: dict[int, str] = {
    0: "pathfinding",
    1: "archery",
    2: "logistics",
    3: "scouting",
    4: "diplomacy",
    5: "navigation",
    6: "leadership",
    7: "wisdom",
    8: "mysticism",
    9: "luck",
    10: "ballistics",
    11: "eagle_eye",
    12: "necromancy",
    13: "estates",
    14: "fire_magic",
    15: "air_magic",
    16: "water_magic",
    17: "earth_magic",
    18: "scholar",
    19: "tactics",
    20: "artillery",
    21: "learning",
    22: "offense",
    23: "armorer",
    24: "intelligence",
    25: "sorcery",
    26: "resistance",
    27: "first_aid",
}

DEFAULT_PROMPT = (
    "Before the campaign begins in earnest, choose one starting aid for your forces."
)

_BATCH_MANIFESTS: tuple[str, ...] = (
    "scenarios/roe_castle_campaign/batch_manifest.json",
    "scenarios/roe_remaining_campaigns/batch_manifest.json",
    "scenarios/ab_sod_campaigns/batch_manifest.json",
)


def dialog_sid_for_mission(mission_id: str) -> str:
    return f"{mission_id}_starting_bonus"


def counter_sid_for_mission(mission_id: str) -> str:
    return f"{mission_id}_starting_bonus_chosen"


def start_city_entity_sid(mission_id: str) -> str:
    """QuestScript / UnlockBuildingCity target for the human primary town."""
    return f"{mission_id}_start_city"


@lru_cache(maxsize=1)
def _mission_h3c_coords() -> dict[str, tuple[str, int]]:
    out: dict[str, tuple[str, int]] = {}
    for rel in _BATCH_MANIFESTS:
        path = _REPO_ROOT / rel
        if not path.is_file():
            continue
        doc = json.loads(path.read_text(encoding="utf-8-sig"))
        for row in doc.get("missions") or []:
            if not isinstance(row, dict):
                continue
            mission_id = str(row.get("missionId") or "").strip()
            entry = str(row.get("campaignEntry") or "").strip()
            block = row.get("blockIndex")
            if not mission_id or not entry or not isinstance(block, int):
                continue
            out[mission_id] = (entry, block)
    return out


def resolve_mission_h3c_source(
    mission_id: str,
    *,
    campaign_entry: str | None = None,
    block_index: int | None = None,
) -> tuple[str, int] | None:
    if campaign_entry and isinstance(block_index, int) and block_index > 0:
        return str(campaign_entry), int(block_index)
    return _mission_h3c_coords().get(mission_id)


def _unit_sid_for_creature(creature_id: int) -> str:
    sid = MAP_EVENT_GUARD_UNIT_BY_CREATURE_TYPE.get(int(creature_id))
    if not sid:
        raise KeyError(f"no OE unit SID for HoMM3 creature id {creature_id}")
    return sid


def _unit_label(unit_sid: str, count: int) -> str:
    # Prefer campaign-facing names for common upgrade SIDs.
    aliases = {
        "h3_monk_upg": "Zealot",
        "h3_pikeman_upg": "Halberdier",
        "h3_archer_upg": "Marksman",
        "h3_griffin_upg": "Royal Griffin",
        "h3_swordsman_upg": "Crusader",
        "h3_cavalier_upg": "Champion",
        "h3_angel_upg": "Archangel",
    }
    if unit_sid in aliases:
        return f"{count} {aliases[unit_sid]}"
    base = unit_sid
    if base.startswith("h3_"):
        base = base[3:]
    words = base.replace("_", " ").replace(" upg", "").strip()
    title = " ".join(part[:1].upper() + part[1:] for part in words.split())
    return f"{count} {title}"


def _artifact_label(item_sid: str, artifact_id: int) -> str:
    token = item_sid
    for prefix in ("homm3_artifact_", "artifact_"):
        if token.startswith(prefix):
            token = token[len(prefix) :]
            break
    if token.endswith("_artifact"):
        token = token[: -len("_artifact")]
    # Strip leading numeric catalog prefixes like 006_
    parts = token.split("_")
    if parts and parts[0].isdigit():
        parts = parts[1:]
    title = " ".join(part[:1].upper() + part[1:] for part in parts if part)
    return title or f"Artifact {artifact_id}"


def _resource_grants(resource_id: int, amount: int) -> list[dict[str, Any]]:
    if amount <= 0:
        raise ValueError(f"resource amount must be positive, got {amount}")
    if resource_id == RESOURCE_RARE:
        return [
            {"kind": "resource", "resource": name, "amount": amount}
            for name in RARE_RESOURCES
        ]
    if resource_id == RESOURCE_COMMON:
        return [
            {"kind": "resource", "resource": name, "amount": amount}
            for name in COMMON_RESOURCES
        ]
    resource = H3_RESOURCE_TO_GIVE_RES.get(int(resource_id))
    if not resource:
        raise KeyError(f"unmapped HoMM3 resource id {resource_id}")
    return [{"kind": "resource", "resource": resource, "amount": amount}]


def _resource_label(grants: list[dict[str, Any]]) -> str:
    parts = [f"{g['amount']} {str(g['resource']).title()}" for g in grants]
    if len(parts) == 1:
        return parts[0]
    if len(parts) == 2:
        return f"{parts[0]} and {parts[1]}"
    return ", ".join(parts[:-1]) + f", and {parts[-1]}"


def option_from_h3_bonus(
    bonus: dict[str, Any],
    *,
    index: int,
    start_city_sid: str | None,
) -> dict[str, Any]:
    """Translate one H3C CampaignBonus into a Day-1 dialog option."""
    kind = str(bonus.get("type") or "")
    option_id = f"{kind.lower()}_{index}"

    if kind == "RESOURCE":
        grants = _resource_grants(int(bonus["resource"]), int(bonus["amount"]))
        return {
            "id": option_id,
            "label": _resource_label(grants),
            "homm3": bonus,
            "grants": grants,
        }

    if kind == "MONSTER":
        unit_sid = _unit_sid_for_creature(int(bonus["creature"]))
        count = int(bonus["amount"])
        return {
            "id": option_id,
            "label": _unit_label(unit_sid, count),
            "homm3": bonus,
            "grants": [{"kind": "unit", "unitSid": unit_sid, "count": count}],
        }

    if kind == "ARTIFACT":
        artifact_id = int(bonus["artifact"])
        item_sid = stock_item_sid_for_h3_artifact_id(artifact_id)
        if not item_sid:
            raise KeyError(f"no OE item SID for HoMM3 artifact id {artifact_id}")
        return {
            "id": option_id,
            "label": _artifact_label(item_sid, artifact_id),
            "homm3": bonus,
            "grants": [{"kind": "item", "itemSid": item_sid}],
        }

    if kind == "SPELL_SCROLL":
        spell_id = int(bonus["spell"])
        mapping = spell_mapping_record(spell_id)
        item_sid = mapping["scrollItemSid"]
        magic = mapping["oeMagicSid"]
        short = magic.split("_magic_", 1)[-1].replace("_", " ")
        title = " ".join(part[:1].upper() + part[1:] for part in short.split())
        return {
            "id": option_id,
            "label": f"Scroll of {title}",
            "homm3": bonus,
            "spellMapping": mapping,
            "grants": [{"kind": "item", "itemSid": item_sid}],
        }

    if kind == "SPELL":
        spell_id = int(bonus["spell"])
        mapping = spell_mapping_record(spell_id)
        magic = mapping["oeMagicSid"]
        short = magic.split("_magic_", 1)[-1].replace("_", " ")
        title = " ".join(part[:1].upper() + part[1:] for part in short.split())
        return {
            "id": option_id,
            "label": f"Learn {title}",
            "homm3": bonus,
            "spellMapping": mapping,
            "grants": [{"kind": "spell", "magicSid": magic}],
        }

    if kind == "PRIMARY_SKILL":
        grants: list[dict[str, Any]] = []
        label_parts: list[str] = []
        for field, param in PRIMARY_STAT_PARAMS:
            amount = int(bonus.get(field) or 0)
            if amount <= 0:
                continue
            grants.append({"kind": "stat", "stat": param, "amount": amount})
            label_parts.append(f"+{amount} {param}")
        if not grants:
            raise ValueError(f"PRIMARY_SKILL bonus has no positive stats: {bonus}")
        return {
            "id": option_id,
            "label": ", ".join(label_parts),
            "homm3": bonus,
            "grants": grants,
        }

    if kind == "BUILDING":
        unlock = olden_unlock_for_vcmi_building(int(bonus["building"]))
        if not start_city_sid:
            raise ValueError(
                "BUILDING starting bonus requires startCityEntitySid "
                f"(UnlockBuildingCity target); building={unlock['vcmiBuildingName']}"
            )
        return {
            "id": option_id,
            # player_facing_building_label: "City Hall", not "Main level 3"
            "label": str(unlock["label"]),
            "homm3": bonus,
            "buildingMapping": unlock,
            "grants": [
                {
                    "kind": "building",
                    "buildingSid": unlock["buildingSid"],
                    "level": unlock["level"],
                    "cityEntitySid": start_city_sid,
                }
            ],
        }

    if kind == "SECONDARY_SKILL":
        skill_id = int(bonus["skill"])
        mastery = int(bonus["mastery"])
        skill_name = H3_SECONDARY_SKILL_NAMES.get(skill_id, f"skill_{skill_id}")
        raise ValueError(
            f"SECONDARY_SKILL starting bonus has no stock dialog grant verb "
            f"(need AddSkillHero or equivalent); skill={skill_name} mastery={mastery}. "
            "Fail-closed until a native skill-grant mapAction is proven."
        )

    raise ValueError(f"unsupported campaign bonus type {kind!r}: {bonus}")


def build_options_from_h3c(
    bonuses: list[dict[str, Any]],
    *,
    start_city_sid: str | None,
    mission_id: str | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Translate H3C bonuses, skipping options that cannot be emitted natively.

    Returns ``(emitted_options, omitted_records)``. Omitted entries keep the raw
    H3C bonus plus a clear reason — never silently drop without a record.
    """
    options: list[dict[str, Any]] = []
    omitted: list[dict[str, Any]] = []
    for index, bonus in enumerate(bonuses):
        try:
            options.append(
                option_from_h3_bonus(
                    bonus, index=index, start_city_sid=start_city_sid
                )
            )
        except (KeyError, ValueError) as exc:
            omitted.append(
                {
                    "index": index,
                    "homm3": dict(bonus) if isinstance(bonus, dict) else bonus,
                    "omitReason": str(exc),
                    "missionId": mission_id,
                }
            )
    return options, omitted


def resolve_starting_bonus(
    mission_id: str,
    *,
    hero_sid: str,
    mission_title: str | None = None,
    campaign_entry: str | None = None,
    block_index: int | None = None,
    start_city_sid: str | None = None,
) -> dict[str, Any] | None:
    """Return emit payload when the mission has H3C choose-one START_BONUS options.

    Options that cannot map to a native dialog grant are omitted; the dialog keeps
    the remaining choices. Returns None when fewer than one option survives.
    """
    coords = resolve_mission_h3c_source(
        mission_id,
        campaign_entry=campaign_entry,
        block_index=block_index,
    )
    if coords is None:
        return None
    entry, block = coords
    payload = starting_bonuses_for_mission(entry, block)
    if payload is None:
        return None

    hero = str(hero_sid or "").strip()
    if not hero:
        raise ValueError(
            f"{mission_id}: starting-bonus dialog requires deterministic spawn heroSid"
        )

    city_sid = str(start_city_sid or "").strip() or None
    # Always bind the deterministic start-city SID when any BUILDING option exists,
    # so emit can stamp propEntities even if the caller omitted the override.
    if city_sid is None and any(b.get("type") == "BUILDING" for b in payload["bonuses"]):
        city_sid = start_city_entity_sid(mission_id)

    options, omitted = build_options_from_h3c(
        payload["bonuses"],
        start_city_sid=city_sid,
        mission_id=mission_id,
    )
    if not options:
        return None
    for index, option in enumerate(options):
        option_id = str(option.get("id") or "").strip()
        label = str(option.get("label") or "").strip()
        grants = option.get("grants")
        if not option_id or not label:
            raise ValueError(f"{mission_id}: option {index} missing id/label")
        if not isinstance(grants, list) or not grants:
            raise ValueError(f"{mission_id}: option {option_id!r} has no grants")
        for grant in grants:
            _validate_grant(mission_id, option_id, grant)

    title = str(mission_title or mission_id).strip() or mission_id
    needs_start_city = any(
        grant.get("kind") == "building"
        for option in options
        for grant in (option.get("grants") or [])
    )
    h3c_count = len(payload["bonuses"])
    evidence = (
        f"{entry}#{block} {payload['mapName']} START_BONUS "
        f"({len(options)}/{h3c_count} options emitted"
    )
    if omitted:
        evidence += f"; omitted {len(omitted)}"
    evidence += ")"
    return {
        "schema": "homm3.olden_campaign_starting_bonus_dialog.v1",
        "missionId": mission_id,
        "dialogSid": dialog_sid_for_mission(mission_id),
        "counterSid": counter_sid_for_mission(mission_id),
        "heroSid": hero,
        "startCityEntitySid": city_sid if needs_start_city else None,
        "requiresStartCityEntity": needs_start_city,
        "title": title,
        "prompt": DEFAULT_PROMPT,
        "evidence": evidence,
        "h3c": {
            "campaignEntry": entry,
            "blockIndex": block,
            "mapName": payload["mapName"],
            "sourceOptionCount": h3c_count,
            "emittedOptionCount": len(options),
        },
        "options": options,
        "omittedOptions": omitted,
        "delivery": "questscript_start_turn_day1_dialog_answers_mapactions",
        "proofBoundary": (
            "source/static + generated-artifact; runtime choice/grant user-unvalidated"
        ),
    }


def _validate_grant(mission_id: str, option_id: str, grant: Any) -> None:
    if not isinstance(grant, dict):
        raise ValueError(f"{mission_id}/{option_id}: grant must be an object")
    kind = grant.get("kind")
    if kind == "resource":
        resource = str(grant.get("resource") or "").strip()
        amount = grant.get("amount")
        if not resource or not isinstance(amount, int) or amount <= 0:
            raise ValueError(f"{mission_id}/{option_id}: invalid resource grant")
        return
    if kind == "unit":
        unit_sid = str(grant.get("unitSid") or "").strip()
        count = grant.get("count")
        if not unit_sid or not isinstance(count, int) or count <= 0:
            raise ValueError(f"{mission_id}/{option_id}: invalid unit grant")
        return
    if kind == "item":
        item_sid = str(grant.get("itemSid") or "").strip()
        if not item_sid:
            raise ValueError(f"{mission_id}/{option_id}: invalid item grant")
        return
    if kind == "spell":
        magic_sid = str(grant.get("magicSid") or "").strip()
        if not magic_sid:
            raise ValueError(f"{mission_id}/{option_id}: invalid spell grant")
        return
    if kind == "stat":
        stat = str(grant.get("stat") or "").strip()
        amount = grant.get("amount")
        if not stat or not isinstance(amount, int) or amount == 0:
            raise ValueError(f"{mission_id}/{option_id}: invalid stat grant")
        return
    if kind == "building":
        building_sid = str(grant.get("buildingSid") or "").strip()
        level = grant.get("level")
        city = str(grant.get("cityEntitySid") or "").strip()
        if not building_sid or not isinstance(level, int) or level <= 0 or not city:
            raise ValueError(f"{mission_id}/{option_id}: invalid building grant")
        return
    raise ValueError(f"{mission_id}/{option_id}: unsupported grant kind {kind!r}")


def map_actions_for_option(
    *,
    mission_id: str,
    hero_sid: str,
    option: dict[str, Any],
    option_index: int,
) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    for grant in option.get("grants") or []:
        kind = grant.get("kind")
        if kind == "resource":
            actions.append(
                {
                    "a": "GiveRes",
                    "p": [str(grant["resource"]), str(int(grant["amount"]))],
                }
            )
        elif kind == "unit":
            actions.append(
                {
                    "a": "GiveUnitHero",
                    "p": [
                        str(grant["unitSid"]),
                        str(int(grant["count"])),
                        hero_sid,
                    ],
                }
            )
        elif kind == "item":
            actions.append(
                {
                    "a": "GiveItemHero",
                    "p": [str(grant["itemSid"]), hero_sid],
                }
            )
        elif kind == "spell":
            actions.append(
                {
                    "a": "AddSpellHero",
                    "p": [str(grant["magicSid"]), hero_sid],
                }
            )
        elif kind == "stat":
            actions.append(
                {
                    "a": "GiveStatsHero",
                    "p": [str(grant["stat"]), hero_sid, str(int(grant["amount"]))],
                }
            )
        elif kind == "building":
            actions.append(
                {
                    "a": "UnlockBuildingCity",
                    "p": [
                        str(grant["buildingSid"]),
                        str(int(grant["level"])),
                        str(grant["cityEntitySid"]),
                    ],
                }
            )
        else:
            raise ValueError(f"{mission_id}: unsupported grant kind {kind!r}")
    actions.append(
        {
            "a": "CounterSet",
            "p": [counter_sid_for_mission(mission_id), str(option_index + 1)],
        }
    )
    return actions


def build_dialog_entry(spec: dict[str, Any]) -> dict[str, Any]:
    """Build a structured Core dialog entry for generate_campaign_dialog_overlay."""
    mission_id = str(spec["missionId"])
    dialog_sid = str(spec["dialogSid"])
    title = str(spec["title"])
    prompt = str(spec["prompt"]).strip()
    hero_sid = str(spec["heroSid"])
    options = list(spec["options"])
    if not prompt:
        raise ValueError(f"{mission_id}: starting-bonus prompt is empty")

    answers: list[dict[str, Any]] = []
    reward_slides: list[dict[str, Any]] = []
    for index, option in enumerate(options):
        slide_id = f"opt_{index}"
        label = str(option["label"]).strip()
        answers.append(
            {
                "text": label,
                "actions": [{"a": "Go", "p": [slide_id]}],
            }
        )
        reward_slides.append(
            {
                "id": slide_id,
                "title": title,
                "text": f"Received: {label}",
                "mapActions": map_actions_for_option(
                    mission_id=mission_id,
                    hero_sid=hero_sid,
                    option=option,
                    option_index=index,
                ),
                "end": True,
                "resultDialog": "Interrupt",
            }
        )

    return {
        "id": dialog_sid,
        "kind": "starting_bonus_choice",
        "title": title,
        "slides": [
            {
                "id": "start",
                "title": title,
                "text": prompt,
                "answers": answers,
            },
            *reward_slides,
        ],
        "startingBonus": {
            "missionId": mission_id,
            "heroSid": hero_sid,
            "startCityEntitySid": spec.get("startCityEntitySid"),
            "optionIds": [str(option["id"]) for option in options],
            "delivery": spec.get("delivery"),
            "evidence": spec.get("evidence"),
            "h3c": spec.get("h3c"),
        },
    }


def attach_to_alignment_story(
    alignment_story: dict[str, Any],
    spec: dict[str, Any],
) -> dict[str, Any]:
    """Return a shallow-copied alignment story with startingBonus + counter."""
    out = dict(alignment_story)
    out["startingBonus"] = dict(spec)
    counters = [dict(row) for row in (out.get("counters") or []) if isinstance(row, dict)]
    counter_sid = str(spec["counterSid"])
    if not any(row.get("sid") == counter_sid for row in counters):
        counters.append({"sid": counter_sid, "value": 0})
    out["counters"] = counters
    return out


def catalog_entry(mission_id: str) -> dict[str, Any] | None:
    """Compatibility helper: resolve without hero (returns None / raises on bad H3C)."""
    coords = resolve_mission_h3c_source(mission_id)
    if coords is None:
        return None
    payload = starting_bonuses_for_mission(*coords)
    if payload is None:
        return None
    return {
        "missionId": mission_id,
        "evidence": f"{coords[0]}#{coords[1]} {payload['mapName']}",
        "prompt": DEFAULT_PROMPT,
        "h3cBonuses": payload["bonuses"],
    }
