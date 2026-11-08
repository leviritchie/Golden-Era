#!/usr/bin/env python3
"""Compile placed H3 hero army/artifact/skill payloads into QuestScript grants.

Olden ``PropHero`` is identity-only (id / isDefined / heroSid). Native Story maps
deliver custom items/units/skills via ``GiveItemHero`` / ``GiveUnitHero`` /
``AddSkillHero`` keyed by heroSid (e.g. t_C7, c_M4, c_M10, ascension_to_the_throne).

``AddSkillHero`` params are ``[skillSid, heroSid]``; mastery is repeated calls
(basic=1, advanced=2, expert=3), matching shipped Story maps.

Artifact ownership on AI placed heroes: day-1 ``GiveItemHero`` onto Bot SIDs is
live-negative (Clone cannot see AI heroes; ``sharing: Ai`` has no native
GiveItemHero donor). Defeat loot is delivered as Clone ``HeroKill`` →
``GiveItemHero`` onto the human start hero SID (wiki: defeat rival → take
artifacts). Army/skills still use day-1 AI ``GiveUnitHero`` / ``AddSkillHero``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from campaign_starting_bonus import H3_SECONDARY_SKILL_NAMES
from campaign_victory import CAMPAIGN_VICTORY_ARTIFACT_ALIASES, CAMPAIGN_VICTORY_ARTIFACT_SETS
from vanilla_stock.h3_artifact_stock_map import require_item_sid_for_h3_artifact_id

# AB/SoD empty equipped slot. RoE u8 empty is 255.
_H3_EMPTY_ARTIFACT_IDS = frozenset({255, 65535, 0xFFFF})

# Combination artifacts stored as a single equipped id on placed heroes.
# Expand to component pieces (same family as victory TRANSPORTITEM 133).
_CAMPAIGN_HERO_ARTIFACT_SETS: dict[int, tuple[int, ...]] = {
    **CAMPAIGN_VICTORY_ARTIFACT_SETS,
    # Armor of the Damned (SoD combo id 132): skull/blackshard/rib/yawning-shield.
    132: (20, 8, 26, 14),
    # Elixir of Life (SoD combo id 131): ring of vitality + vial + ring of life.
    131: (94, 96, 95),
}

# H3 secondary skill name → Olden skill SID (native AddSkillHero vocabulary).
_H3_SKILL_NAME_TO_OLDEN_SID: dict[str, str] = {
    "pathfinding": "skill_logistic",
    "archery": "skill_assault",
    "logistics": "skill_logistic",
    "scouting": "skill_scouting",
    "diplomacy": "skill_diplomacy",
    "navigation": "skill_scouting",
    "leadership": "skill_leadership",
    "wisdom": "skill_wisdom",
    "mysticism": "skill_wisdom",
    "luck": "skill_luck",
    "ballistics": "skill_siege",
    "eagle_eye": "skill_mastery",
    "necromancy": "skill_faction_homm3_necropolis",
    "estates": "skill_economy",
    "fire_magic": "skill_magic_day",
    "air_magic": "skill_magic_space",
    "water_magic": "skill_magic_night",
    "earth_magic": "skill_magic_primal",
    "scholar": "skill_wisdom",
    "tactics": "skill_tactics",
    "artillery": "skill_siege",
    "learning": "skill_enlightenment",
    "offense": "skill_assault",
    "armorer": "skill_protection",
    "intelligence": "skill_wisdom",
    "sorcery": "skill_sorcery",
    "resistance": "skill_resistance",
    "first_aid": "skill_trainer",
}

# Spell Book is not a victory pickup; skip defeat-loot emit.
_SKIP_DEFEAT_LOOT_ARTIFACT_IDS = frozenset({0})


class PlacedHeroPayloadError(ValueError):
    """Fail-closed placed-hero payload planning/emit error."""


def prison_rescue_pending_counter_sid(mission_id: str, index: int) -> str:
    """Return the counter that arms one prison's deferred hero payload grant."""

    mission = str(mission_id or "").strip()
    if not mission:
        raise PlacedHeroPayloadError("prison rescue counter requires a mission id")
    if int(index) < 0:
        raise PlacedHeroPayloadError("prison rescue counter index must be non-negative")
    return f"{mission}_prison_rescue_payload_{int(index)}_pending"


@dataclass
class PlacedHeroPayloadPlan:
    mission_id: str
    # Day-1 AI sharing: GiveUnitHero / AddSkillHero onto placed AI SIDs.
    actions: list[dict[str, Any]] = field(default_factory=list)
    # Clone HeroKill → GiveItemHero onto human start hero.
    defeat_loot: list[dict[str, Any]] = field(default_factory=list)
    # Prison ObjectInteractionAfter arms a deferred next-side-start grant so the
    # rescued hero has entered the human side before hero-targeted actions run.
    rescue_grants: list[dict[str, Any]] = field(default_factory=list)
    heroes: list[dict[str, Any]] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)


def entity_has_custom_payload(entity: dict[str, Any]) -> bool:
    """True when H3 payload carries army, artifacts, or secondary skills.

    Olden Era heroes intrinsically have a spell book, so H3 Spell Book (id 0)
    is never a grant/loot target. A hero whose only decoded artifact is that
    book does not need a starting artifact grant (corporeal_punishment Mot
    @0:63:66, valley_of_the_dragon_lords @0:8:67, a_thief_in_the_night
    @0:34:56). Do not treat raw ``hasArtifactSet`` alone as custom payload.

    Flag-set-but-empty-decode still returns True so the planner fails closed
    on a decode regression (``hasArtifactSet`` / ``hasGarrison`` with no
    nonempty decoded rows).
    """
    if int(entity.get("secondarySkillCount") or 0) > 0:
        return True
    skills = entity.get("secondarySkills") or []
    if isinstance(skills, list) and len(skills) > 0:
        return True

    if _nonempty_garrison_stacks(entity):
        return True
    if entity.get("hasGarrison"):
        # Flag set with empty stacks → decode regression; planner fails closed.
        return True

    if _planned_artifact_ids(entity):
        return True
    if entity.get("hasArtifactSet"):
        # Spell-book-only: nonempty decode, zero planned loot → not custom.
        # Empty decode with the flag set → decode regression → custom (fail).
        return not _nonempty_artifact_ids(entity)

    return False


def _nonempty_artifact_ids(entity: dict[str, Any]) -> list[int]:
    ids: list[int] = []
    for bucket in (entity.get("equippedArtifacts"), entity.get("backpackArtifacts")):
        if not isinstance(bucket, list):
            continue
        for raw in bucket:
            if not isinstance(raw, int):
                continue
            if raw in _H3_EMPTY_ARTIFACT_IDS:
                continue
            ids.append(int(raw))
    return ids


def _nonempty_garrison_stacks(entity: dict[str, Any]) -> list[dict[str, Any]]:
    stacks = entity.get("garrisonStacks") or []
    if not isinstance(stacks, list):
        return []
    out: list[dict[str, Any]] = []
    for row in stacks:
        if not isinstance(row, dict):
            continue
        try:
            creature_type = int(row["creatureType"])
            count = int(row["count"])
        except (KeyError, TypeError, ValueError):
            continue
        if count <= 0 or creature_type in (65535, 0xFFFF, -1):
            continue
        out.append({"creatureType": creature_type, "count": count})
    return out


def _expand_artifact_ids(artifact_id: int) -> list[int]:
    if artifact_id in _CAMPAIGN_HERO_ARTIFACT_SETS:
        return list(_CAMPAIGN_HERO_ARTIFACT_SETS[artifact_id])
    mapped = CAMPAIGN_VICTORY_ARTIFACT_ALIASES.get(int(artifact_id), int(artifact_id))
    return [int(mapped)]


def _item_sid_for_h3_artifact(artifact_id: int) -> str:
    return require_item_sid_for_h3_artifact_id(int(artifact_id))


def _planned_artifact_ids(entity: dict[str, Any]) -> list[int]:
    """Loot-eligible expanded artifact ids (same view as the grant/loot loops).

    Combo sets expand to component pieces; skip-listed ids (Spell Book) drop
    out. ``entity_has_custom_payload`` must judge payload through this lens so
    a spell-book-only hero is not flagged as carrying a custom payload.
    """
    ids: list[int] = []
    for artifact_id in _nonempty_artifact_ids(entity):
        for member_id in _expand_artifact_ids(artifact_id):
            if member_id in _SKIP_DEFEAT_LOOT_ARTIFACT_IDS:
                continue
            ids.append(member_id)
    return ids


def _olden_skill_sid(skill_id: int) -> str:
    name = H3_SECONDARY_SKILL_NAMES.get(int(skill_id))
    if not name:
        raise PlacedHeroPayloadError(f"unknown H3 secondary skill id={skill_id}")
    sid = _H3_SKILL_NAME_TO_OLDEN_SID.get(name)
    if not sid:
        raise PlacedHeroPayloadError(f"no Olden skill SID for H3 skill {name!r} (id={skill_id})")
    return sid


def plan_placed_hero_payload_grants(
    *,
    mission_id: str,
    placed_heroes: list[dict[str, Any]],
    entities_by_id: dict[int, dict[str, Any]],
    creature_to_unit: Callable[[int], str | None],
) -> PlacedHeroPayloadPlan:
    """Plan army/skill day-1 AI grants and artifact defeat-loot for placed heroes."""

    plan = PlacedHeroPayloadPlan(mission_id=mission_id)
    for row in placed_heroes:
        if not isinstance(row, dict):
            continue
        object_id = row.get("objectId")
        hero_sid = row.get("heroSid")
        if not isinstance(object_id, int) or not isinstance(hero_sid, str) or not hero_sid:
            raise PlacedHeroPayloadError(
                f"{mission_id}: placed hero bind missing objectId/heroSid: {row}"
            )
        entity = entities_by_id.get(object_id)
        if entity is None:
            raise PlacedHeroPayloadError(
                f"{mission_id}: placed hero objectId={object_id} missing alignment entity"
            )
        source_key = str(entity.get("sourceKey") or row.get("sourceKey") or object_id)
        if not entity_has_custom_payload(entity):
            continue

        host_kind = str(row.get("hostKind") or "hero_spawner")
        is_prison = host_kind == "prison"
        prison_entity_sid = str(row.get("entitySid") or "").strip()
        if is_prison and not prison_entity_sid:
            raise PlacedHeroPayloadError(
                f"{mission_id}: prison placed hero {source_key} missing entitySid "
                "(needed for ObjectInteractionAfter rescue grants)"
            )

        hero_actions: list[dict[str, Any]] = []
        loot_rows: list[dict[str, Any]] = []
        rescue_actions: list[dict[str, Any]] = []
        artifact_ids = _nonempty_artifact_ids(entity)
        for artifact_id in artifact_ids:
            for member_id in _expand_artifact_ids(artifact_id):
                if member_id in _SKIP_DEFEAT_LOOT_ARTIFACT_IDS:
                    continue
                try:
                    item_sid = _item_sid_for_h3_artifact(member_id)
                except KeyError as exc:
                    raise PlacedHeroPayloadError(
                        f"{mission_id}: placed hero {source_key} artifact id={artifact_id} "
                        f"(member {member_id}): {exc}"
                    ) from exc
                if is_prison:
                    # H3 prison heroes carry backpack/equipped artifacts on the placed
                    # hero record. Grant onto the rescued heroSid so Kendal (etc.) joins
                    # with the HoMM3 inventory; ItemOwnSide still counts once they are on
                    # the human side.
                    rescue_actions.append(
                        {
                            "comment": (
                                f"prison rescue {source_key} artifact {artifact_id}"
                                + (f"→{member_id}" if member_id != artifact_id else "")
                            ),
                            "a": "GiveItemHero",
                            "p": [item_sid, hero_sid],
                        }
                    )
                else:
                    loot_rows.append(
                        {
                            "killedHeroSid": hero_sid,
                            "sourceKey": source_key,
                            "h3ArtifactId": int(member_id),
                            "itemSid": item_sid,
                            "comment": (
                                f"defeat loot {source_key} artifact {artifact_id}"
                                + (f"→{member_id}" if member_id != artifact_id else "")
                            ),
                        }
                    )

        for stack in _nonempty_garrison_stacks(entity):
            creature_type = int(stack["creatureType"])
            count = int(stack["count"])
            unit_sid = creature_to_unit(creature_type)
            if not unit_sid:
                raise PlacedHeroPayloadError(
                    f"{mission_id}: placed hero {source_key} garrison creatureType="
                    f"{creature_type} has no Olden unit SID"
                )
            grant = {
                "comment": f"placed hero {source_key} stack {unit_sid}x{count}",
                "a": "GiveUnitHero",
                "p": [unit_sid, str(count), hero_sid],
            }
            if is_prison:
                rescue_actions.append(grant)
            else:
                hero_actions.append(grant)

        skills = entity.get("secondarySkills") or []
        if not isinstance(skills, list):
            skills = []
        skill_grants = 0
        for skill_row in skills:
            if not isinstance(skill_row, dict):
                continue
            try:
                skill_id = int(skill_row["skillId"])
                level = int(skill_row["level"])
            except (KeyError, TypeError, ValueError) as exc:
                raise PlacedHeroPayloadError(
                    f"{mission_id}: placed hero {source_key} bad secondary skill row {skill_row}"
                ) from exc
            if level < 0 or level > 3:
                raise PlacedHeroPayloadError(
                    f"{mission_id}: placed hero {source_key} skill id={skill_id} "
                    f"level={level} out of 0..3"
                )
            skill_sid = _olden_skill_sid(skill_id)
            repeats = 3 if level == 3 else level + 1
            for _ in range(repeats):
                grant = {
                    "comment": f"placed hero {source_key} skill {skill_sid} L{level}",
                    "a": "AddSkillHero",
                    "p": [skill_sid, hero_sid],
                }
                if is_prison:
                    rescue_actions.append(grant)
                else:
                    hero_actions.append(grant)
                skill_grants += 1

        expected_skill_count = int(entity.get("secondarySkillCount") or 0)
        if expected_skill_count > 0 and skill_grants == 0:
            raise PlacedHeroPayloadError(
                f"{mission_id}: placed hero {source_key} secondarySkillCount="
                f"{expected_skill_count} but secondarySkills produced no AddSkillHero grants"
            )

        if is_prison:
            if not rescue_actions:
                raise PlacedHeroPayloadError(
                    f"{mission_id}: prison {source_key} flagged custom payload but "
                    f"produced no rescue grants"
                )
            plan.rescue_grants.append(
                {
                    "objectId": object_id,
                    "sourceKey": source_key,
                    "heroSid": hero_sid,
                    "entitySid": prison_entity_sid,
                    "actions": rescue_actions,
                }
            )
        else:
            if not hero_actions and not loot_rows:
                raise PlacedHeroPayloadError(
                    f"{mission_id}: placed hero {source_key} flagged custom payload but "
                    f"produced no GiveUnitHero/AddSkillHero grants or defeat loot"
                )
            plan.actions.extend(hero_actions)
            plan.defeat_loot.extend(loot_rows)

        plan.heroes.append(
            {
                "objectId": object_id,
                "sourceKey": source_key,
                "heroSid": hero_sid,
                "hostKind": host_kind,
                "artifactCount": len(artifact_ids),
                "defeatLootCount": 0 if is_prison else len(loot_rows),
                "rescueGrantCount": len(rescue_actions) if is_prison else 0,
                "stackCount": len(_nonempty_garrison_stacks(entity)),
                "skillGrantCount": skill_grants,
                "grantCount": len(rescue_actions) if is_prison else len(hero_actions),
            }
        )
        plan.evidence.append(
            f"{source_key} → {hero_sid} ({host_kind}): artifacts={len(artifact_ids)} "
            f"defeatLoot={0 if is_prison else len(loot_rows)} "
            f"rescueGrants={len(rescue_actions) if is_prison else 0} "
            f"stacks={len(_nonempty_garrison_stacks(entity))} "
            f"skillGrants={skill_grants} day1Grants={0 if is_prison else len(hero_actions)}"
        )

    if plan.actions:
        plan.evidence.append(f"total day1 AI grants={len(plan.actions)}")
    if plan.defeat_loot:
        plan.evidence.append(f"total HeroKill defeat loot items={len(plan.defeat_loot)}")
    if plan.rescue_grants:
        plan.evidence.append(
            f"total prison rescue grant hosts={len(plan.rescue_grants)} "
            f"actions={sum(len(row['actions']) for row in plan.rescue_grants)}"
        )
    return plan


def build_placed_hero_payload_quests(
    mission_id: str,
    plan: PlacedHeroPayloadPlan,
    *,
    start_turn_condition: Callable[[int], dict[str, Any]],
    human_hero_sid: str,
) -> list[dict[str, Any]]:
    """Build AI/defeat-loot quests plus deferred prison hero-payload quests.

    The prison interaction event is only the arming edge. Native prison release
    and hero transfer are allowed to finish before the next side start, where
    hero-targeted item/unit/skill actions run against the rescued SID.
    """

    if not isinstance(human_hero_sid, str) or not human_hero_sid.strip():
        raise PlacedHeroPayloadError(
            f"{mission_id}: human_hero_sid required for placed-hero defeat loot"
        )
    human_sid = human_hero_sid.strip()
    quests: list[dict[str, Any]] = []

    if plan.actions:
        actions = [
            {
                "comment": str(row.get("comment") or ""),
                "a": str(row["a"]),
                "p": list(row["p"]),
            }
            for row in plan.actions
        ]
        quests.append(
            {
                "sid": f"{mission_id}_placed_hero_payloads",
                "hidden": True,
                "main": False,
                "activeOnStart": True,
                "comment": (
                    f"{mission_id} H3 placed-hero army/skill StartTurn grants (AI sharing)"
                ),
                "sharing": "Ai",
                "name": "",
                "desc": "",
                "subQuests": [
                    {
                        "sid": f"{mission_id}_placed_hero_payloads_day1",
                        "activeOnStart": True,
                        "hidden": True,
                        "name": "",
                        "desc": "",
                        "comment": "",
                        "triggers": [
                            {
                                "comment": "placed hero army/skill grants day 1 (AI)",
                                "repeat": False,
                                "conditions": [start_turn_condition(1)],
                                "actions": actions,
                                "conditionsLogic": "And",
                            }
                        ],
                    }
                ],
                "subQuestGroups": [],
            }
        )

    for index, rescue in enumerate(plan.rescue_grants):
        entity_sid = str(rescue.get("entitySid") or "").strip()
        hero_sid = str(rescue.get("heroSid") or "").strip()
        source_key = str(rescue.get("sourceKey") or hero_sid)
        pending_counter_sid = prison_rescue_pending_counter_sid(mission_id, index)
        if not entity_sid or not hero_sid:
            raise PlacedHeroPayloadError(
                f"{mission_id}: prison rescue grant missing entitySid/heroSid: {rescue}"
            )
        actions = []
        for row in rescue.get("actions") or []:
            params = list(row["p"])
            actions.append(
                {
                    "comment": str(row.get("comment") or ""),
                    "a": str(row["a"]),
                    "p": params,
                }
            )
        if not actions:
            raise PlacedHeroPayloadError(
                f"{mission_id}: prison rescue {source_key} has empty actions"
            )
        quests.append(
            {
                "sid": f"{mission_id}_prison_rescue_payload_{index}",
                "hidden": True,
                "main": False,
                "activeOnStart": True,
                "comment": (
                    f"{mission_id} prison rescue grants for {source_key} ({hero_sid}) "
                    f"after {entity_sid} release"
                ),
                "sharing": "Clone",
                "name": "",
                "desc": "",
                "subQuests": [
                    {
                        "sid": f"{mission_id}_prison_rescue_payload_{index}_visit",
                        "activeOnStart": True,
                        "hidden": True,
                        "name": "",
                        "desc": "",
                        "comment": "",
                        "triggers": [
                            {
                                "comment": (
                                    f"ObjectInteractionAfter {entity_sid} arms "
                                    f"rescue payload for {hero_sid}"
                                ),
                                "repeat": False,
                                "conditions": [
                                    {
                                        "comment": "",
                                        "c": "ObjectInteractionAfter",
                                        "p": [entity_sid],
                                        "counter": 1,
                                    }
                                ],
                                "actions": [
                                    {
                                        "comment": (
                                            f"defer prison payload until next side start "
                                            f"for {hero_sid}"
                                        ),
                                        "a": "CounterSet",
                                        "p": [pending_counter_sid, "1"],
                                    }
                                ],
                                "conditionsLogic": "And",
                            },
                            {
                                "comment": (
                                    f"deferred prison payload for {hero_sid} "
                                    f"after {entity_sid} release"
                                ),
                                "repeat": False,
                                "conditions": [
                                    {
                                        "comment": "",
                                        "c": "CounterEqualityInDays",
                                        "p": [pending_counter_sid, "1"],
                                        "counter": 1,
                                    }
                                ],
                                "actions": [
                                    *actions,
                                    {
                                        "comment": "",
                                        "a": "CounterSet",
                                        "p": [pending_counter_sid, "0"],
                                    },
                                ],
                                "conditionsLogic": "And",
                            }
                        ],
                    }
                ],
                "subQuestGroups": [],
            }
        )

    loot_by_hero: dict[str, list[dict[str, Any]]] = {}
    for row in plan.defeat_loot:
        killed = str(row["killedHeroSid"])
        loot_by_hero.setdefault(killed, []).append(row)

    for index, (killed_sid, rows) in enumerate(sorted(loot_by_hero.items())):
        actions = [
            {
                "comment": str(row.get("comment") or ""),
                "a": "GiveItemHero",
                "p": [str(row["itemSid"]), human_sid],
            }
            for row in rows
        ]
        source_key = str(rows[0].get("sourceKey") or killed_sid)
        quests.append(
            {
                "sid": f"{mission_id}_placed_hero_defeat_loot_{index}",
                "hidden": True,
                "main": False,
                "activeOnStart": True,
                "comment": (
                    f"{mission_id} defeat loot from {source_key} ({killed_sid}) → {human_sid}"
                ),
                "sharing": "Clone",
                "name": "",
                "desc": "",
                "subQuests": [
                    {
                        "sid": f"{mission_id}_placed_hero_defeat_loot_{index}_kill",
                        "activeOnStart": True,
                        "hidden": True,
                        "name": "",
                        "desc": "",
                        "comment": "",
                        "triggers": [
                            {
                                "comment": f"HeroKill {killed_sid} defeat artifact loot",
                                "repeat": False,
                                "conditions": [
                                    {
                                        "comment": "",
                                        "c": "HeroKill",
                                        "p": [killed_sid],
                                        "counter": 1,
                                    }
                                ],
                                "actions": actions,
                                "conditionsLogic": "And",
                            }
                        ],
                    }
                ],
                "subQuestGroups": [],
            }
        )

    return quests


def build_placed_hero_payload_quest(
    mission_id: str,
    plan: PlacedHeroPayloadPlan,
    *,
    start_turn_condition: Callable[[int], dict[str, Any]],
    human_hero_sid: str | None = None,
) -> dict[str, Any] | None:
    """Compatibility wrapper: return the first quest or None.

    Prefer ``build_placed_hero_payload_quests`` (army + defeat loot).
    """
    if human_hero_sid is None:
        raise PlacedHeroPayloadError(
            f"{mission_id}: human_hero_sid required for placed-hero payload quests"
        )
    quests = build_placed_hero_payload_quests(
        mission_id,
        plan,
        start_turn_condition=start_turn_condition,
        human_hero_sid=human_hero_sid,
    )
    return quests[0] if quests else None


def assert_script_covers_placed_hero_payloads(
    script_chunk: dict[str, Any],
    plan: PlacedHeroPayloadPlan,
    *,
    human_hero_sid: str | None = None,
) -> None:
    """Fail closed if planned grants / defeat loot / prison rescue rows are missing."""

    expected_actions: list[dict[str, Any]] = list(plan.actions)
    needs_human = bool(plan.defeat_loot or plan.rescue_grants)
    if needs_human:
        if not isinstance(human_hero_sid, str) or not human_hero_sid.strip():
            raise PlacedHeroPayloadError(
                f"{plan.mission_id}: assert rescue/defeat loot requires human_hero_sid"
            )
        human_sid = human_hero_sid.strip()
        for row in plan.defeat_loot:
            expected_actions.append(
                {
                    "a": "GiveItemHero",
                    "p": [str(row["itemSid"]), human_sid],
                }
            )
        for rescue in plan.rescue_grants:
            for row in rescue.get("actions") or []:
                expected_actions.append(
                    {"a": str(row["a"]), "p": list(row["p"])}
                )
        blob = str(script_chunk)
        for killed in sorted({str(r["killedHeroSid"]) for r in plan.defeat_loot}):
            if "HeroKill" not in blob or killed not in blob:
                raise PlacedHeroPayloadError(
                    f"{plan.mission_id}: QuestScript missing HeroKill for {killed}"
                )
        for rescue in plan.rescue_grants:
            entity_sid = str(rescue.get("entitySid") or "")
            if entity_sid and entity_sid not in blob:
                raise PlacedHeroPayloadError(
                    f"{plan.mission_id}: QuestScript missing prison rescue entity {entity_sid}"
                )

    if not expected_actions:
        return
    blob_actions: list[dict[str, Any]] = []

    def walk(obj: Any) -> None:
        if isinstance(obj, dict):
            if isinstance(obj.get("a"), str) and isinstance(obj.get("p"), list):
                blob_actions.append(obj)
            for value in obj.values():
                walk(value)
        elif isinstance(obj, list):
            for value in obj:
                walk(value)

    walk(script_chunk)
    missing: list[str] = []
    for expected in expected_actions:
        verb = str(expected["a"])
        params = list(expected["p"])
        if not any(
            str(row.get("a")) == verb and list(row.get("p") or []) == params
            for row in blob_actions
        ):
            missing.append(f"{verb}{params}")
    if missing:
        raise PlacedHeroPayloadError(
            f"{plan.mission_id}: QuestScript missing placed-hero grants: {missing[:12]}"
        )
