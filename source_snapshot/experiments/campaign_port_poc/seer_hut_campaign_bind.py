"""Bind decoded H3 Seer hut quests onto shared SeerQuestPlan compile."""

from __future__ import annotations

from typing import Any

from seer_hut_quest import (
    SeerHutQuestError,
    SeerMissionBringArtifacts,
    SeerMissionBringCreatures,
    SeerMissionBringResources,
    SeerMissionDefeatHero,
    SeerMissionDefeatSquad,
    SeerQuestPlan,
    SeerQuestTexts,
    SeerRewardArtifact,
    SeerRewardCreatures,
    SeerRewardExperience,
    SeerRewardHeroBuffDays,
    SeerRewardManaRestore,
    SeerRewardNone,
    SeerRewardPrimarySkill,
    SeerRewardResource,
    SeerRewardSecondarySkill,
    SeerRewardSpell,
    H3_PRIMARY_SKILL_TO_STAT,
    assert_supported_mission_type,
    assert_supported_reward_type,
    coalesce_seer_quest_texts,
    compile_seer_quest_subquests,
    compile_seer_quest_triggers,
    declared_counters_for_plan,
    seer_quest_id_for_source_key,
)
from seer_hut_substitutes import seer_hut_substitution
from campaign_starting_bonus import H3_SECONDARY_SKILL_NAMES
from vanilla_stock.h3_artifact_stock_map import require_item_sid_for_h3_artifact_id

# H3 secondary skill name → Olden skill SID (same vocabulary as placed-hero payloads).
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

# H3 resource ordinal → OE GiveRes / ResCounter SID (matches campaign_runtime_script).
H3_RESOURCE_SIDS = (
    "wood",
    "mercury",
    "ore",
    "dust",
    "crystals",
    "gemstones",
    "gold",
)


def _primary_quest_payload(entity: dict[str, Any]) -> dict[str, Any]:
    quests = entity.get("quests")
    repeatable = entity.get("repeatableQuests")
    if isinstance(repeatable, list) and repeatable:
        raise SeerHutQuestError(
            f"seer hut {entity.get('sourceKey')}: HotA repeatable quests are not supported in v1"
        )
    if isinstance(quests, list):
        if len(quests) != 1:
            raise SeerHutQuestError(
                f"seer hut {entity.get('sourceKey')}: HotA multi-quest count {len(quests)} "
                "is not supported in v1 (exactly one one-time quest required)"
            )
        quest = quests[0]
    else:
        quest = entity.get("quest")
    if not isinstance(quest, dict):
        raise SeerHutQuestError(
            f"seer hut {entity.get('sourceKey')}: missing decoded quest payload"
        )
    return quest


def _mission_from_quest(
    quest: dict[str, Any],
    *,
    context: str,
    target_entity_sid: str | None,
) -> Any:
    mission_type = int(quest.get("missionType") or 0)
    assert_supported_mission_type(mission_type, context=context)
    if mission_type == 3:
        if not target_entity_sid:
            raise SeerHutQuestError(f"{context}: defeat-hero requires bound hero entity SID")
        return SeerMissionDefeatHero(hero_sid=target_entity_sid)
    if mission_type == 4:
        if not target_entity_sid:
            raise SeerHutQuestError(f"{context}: defeat-squad requires bound squad entity SID")
        return SeerMissionDefeatSquad(squad_sid=target_entity_sid)
    if mission_type == 5:
        artifact_ids = quest.get("requiredArtifacts")
        if not isinstance(artifact_ids, list) or not artifact_ids:
            single = quest.get("requiredArtifact")
            artifact_ids = [single] if single is not None else []
        if not artifact_ids:
            raise SeerHutQuestError(f"{context}: bring-artifacts mission has no artifact ids")
        item_sids = tuple(
            require_item_sid_for_h3_artifact_id(int(artifact_id))
            for artifact_id in artifact_ids
        )
        return SeerMissionBringArtifacts(item_sids=item_sids)
    if mission_type == 6:
        creatures = quest.get("requiredCreatures")
        if not isinstance(creatures, list) or not creatures:
            raise SeerHutQuestError(f"{context}: bring-creatures mission has no stacks")
        stacks: list[tuple[str, int]] = []
        for row in creatures:
            if not isinstance(row, dict):
                raise SeerHutQuestError(f"{context}: creature stack must be an object")
            creature_type = int(row["creatureType"])
            count = int(row["count"])
            unit_sid = row.get("unitSid")
            if not isinstance(unit_sid, str) or not unit_sid.strip():
                from approach_cell.surface_emit import h3_creature_type_to_unit_sid

                try:
                    unit_sid = h3_creature_type_to_unit_sid(
                        creature_type, context=context
                    )
                except ValueError as exc:
                    raise SeerHutQuestError(str(exc)) from exc
            stacks.append((unit_sid.strip(), count))
        return SeerMissionBringCreatures(stacks=tuple(stacks))
    if mission_type == 7:
        resources = quest.get("requiredResources")
        if not isinstance(resources, list) or len(resources) != 7:
            raise SeerHutQuestError(f"{context}: bring-resources requires 7 resource amounts")
        pairs: list[tuple[str, int]] = []
        for idx, amount in enumerate(resources):
            value = int(amount)
            if value > 0:
                pairs.append((H3_RESOURCE_SIDS[idx], value))
        if not pairs:
            raise SeerHutQuestError(f"{context}: bring-resources mission has no positive amounts")
        return SeerMissionBringResources(resources=tuple(pairs))
    raise SeerHutQuestError(f"{context}: unreachable mission type {mission_type}")


def _reward_from_quest(quest: dict[str, Any], *, context: str) -> Any:
    reward = quest.get("reward")
    if isinstance(reward, dict):
        reward_type_raw = reward.get("rewardType")
        # Substitute-only string kinds (seer_hut_substitutes) — never decoded from H3.
        if reward_type_raw == "hero_buff_days":
            buff_sid = str(reward.get("buffSid") or "").strip()
            if not buff_sid:
                raise SeerHutQuestError(f"{context}: hero_buff_days reward missing buffSid")
            days = int(reward.get("days") or 0)
            if days <= 0:
                raise SeerHutQuestError(f"{context}: hero_buff_days days must be positive")
            return SeerRewardHeroBuffDays(buff_sid=buff_sid, days=days)
        if reward_type_raw == "mana_restore":
            return SeerRewardManaRestore()
        if isinstance(reward_type_raw, str) and reward_type_raw.strip():
            raise SeerHutQuestError(
                f"{context}: unknown substitute reward kind {reward_type_raw!r}"
            )
    if not isinstance(reward, dict):
        reward_type = int(quest.get("rewardType") or 0)
        reward = {"rewardType": reward_type}
    reward_type = int(reward.get("rewardType") or 0)
    assert_supported_reward_type(reward_type, context=context)
    if reward_type == 0:
        return SeerRewardNone()
    if reward_type == 1:
        return SeerRewardExperience(amount=int(reward["experience"]))
    if reward_type == 5:
        resource_type = int(reward["resourceType"])
        if resource_type < 0 or resource_type >= len(H3_RESOURCE_SIDS):
            raise SeerHutQuestError(f"{context}: invalid reward resourceType {resource_type}")
        return SeerRewardResource(
            resource=H3_RESOURCE_SIDS[resource_type],
            amount=int(reward["resourceAmount"]),
        )
    if reward_type == 8:
        return SeerRewardArtifact(
            item_sid=require_item_sid_for_h3_artifact_id(int(reward["artifactId"]))
        )
    if reward_type == 6:
        skill_index = int(reward["primarySkill"])
        amount = int(reward["primarySkillAmount"])
        if skill_index < 0 or skill_index >= len(H3_PRIMARY_SKILL_TO_STAT):
            raise SeerHutQuestError(
                f"{context}: invalid primarySkill index {skill_index}"
            )
        if amount <= 0:
            raise SeerHutQuestError(f"{context}: primarySkillAmount must be positive")
        return SeerRewardPrimarySkill(
            stat=H3_PRIMARY_SKILL_TO_STAT[skill_index],
            amount=amount,
        )
    if reward_type == 7:
        skill_id = int(reward["secondarySkill"])
        mastery = int(reward["secondaryMastery"])
        name = H3_SECONDARY_SKILL_NAMES.get(skill_id)
        if not name:
            raise SeerHutQuestError(f"{context}: unknown H3 secondary skill id={skill_id}")
        skill_sid = _H3_SKILL_NAME_TO_OLDEN_SID.get(name)
        if not skill_sid:
            raise SeerHutQuestError(
                f"{context}: no Olden skill SID for H3 skill {name!r} (id={skill_id})"
            )
        return SeerRewardSecondarySkill(skill_sid=skill_sid, mastery=mastery)
    if reward_type == 9:
        spell_id = int(reward["spellId"])
        from h3_spell_to_oe_magic import spell_mapping_record

        try:
            mapping = spell_mapping_record(spell_id)
        except KeyError as exc:
            raise SeerHutQuestError(str(exc)) from exc
        return SeerRewardSpell(magic_sid=str(mapping["oeMagicSid"]))
    if reward_type == 10:
        unit_sid = reward.get("unitSid")
        if not isinstance(unit_sid, str) or not unit_sid.strip():
            creature_type = reward.get("creatureType")
            if not isinstance(creature_type, int):
                raise SeerHutQuestError(
                    f"{context}: creature reward missing creatureType/unitSid"
                )
            from approach_cell.surface_emit import h3_creature_type_to_unit_sid

            try:
                unit_sid = h3_creature_type_to_unit_sid(creature_type, context=context)
            except ValueError as exc:
                raise SeerHutQuestError(str(exc)) from exc
        return SeerRewardCreatures(
            unit_sid=unit_sid.strip(), count=int(reward["creatureCount"])
        )
    raise SeerHutQuestError(f"{context}: unreachable reward type {reward_type}")


def _substituted_quest(
    quest: dict[str, Any],
    substitution: dict[str, Any],
) -> dict[str, Any]:
    """Overlay the hand-crafted substitute onto the decoded H3 quest."""

    effective = dict(quest)
    mission_override = substitution.get("mission")
    if isinstance(mission_override, dict):
        # The substitute payload fully specifies the new mission; drop every
        # H3 mission-shaped key so stale decode fields cannot leak through.
        for key in (
            "missionType",
            "experienceLevel",
            "primarySkills",
            "requiredHeroId",
            "targetAbsodId",
            "requiredArtifacts",
            "requiredArtifact",
            "requiredCreatures",
            "requiredResources",
        ):
            effective.pop(key, None)
        effective.update(mission_override)
    if "reward" in substitution:
        effective["reward"] = substitution["reward"]
    return effective


def plan_from_seer_entity(
    entity: dict[str, Any],
    *,
    hut_entity_sid: str,
    target_entity_sid: str | None = None,
    mission_id: str | None = None,
) -> SeerQuestPlan:
    source_key = str(entity.get("sourceKey") or entity.get("sourceIndex") or "seer")
    context = f"seer:{source_key}"
    quest = _primary_quest_payload(entity)
    quest_id = seer_quest_id_for_source_key(source_key)
    state_counter = f"{quest_id}_state"

    substitution = (
        seer_hut_substitution(mission_id, source_key) if mission_id is not None else None
    )

    try:
        mission = _mission_from_quest(
            quest, context=context, target_entity_sid=target_entity_sid
        )
        reward = _reward_from_quest(quest, context=context)
    except (SeerHutQuestError, ValueError, KeyError):
        # SeerHutQuestError: unsupported type / unbound SID; ValueError/KeyError:
        # decode misses (unmapped artifact or creature ids, e.g. the SoD combo
        # artifacts the port catalog deliberately excludes).
        if substitution is None:
            raise
        # The H3 quest cannot port natively; apply the hand-crafted substitute.
        effective = _substituted_quest(quest, substitution)
        substitute_context = f"{context} substitute"
        mission = _mission_from_quest(
            effective, context=substitute_context, target_entity_sid=target_entity_sid
        )
        reward = _reward_from_quest(effective, context=substitute_context)
    else:
        if substitution is not None:
            raise SeerHutQuestError(
                f"{context}: stale seer substitute for ({mission_id}, {source_key}); "
                "the native path already ports this quest. Delete the registry entry "
                "in seer_hut_substitutes.py instead of shadowing the native port."
            )

    substitution_note = None
    if substitution is not None:
        substitution_note = (
            f"original: {substitution.get('original')}; "
            f"rationale: {substitution.get('rationale')}"
        )

    substitute_texts = substitution.get("texts") if substitution is not None else None
    if isinstance(substitute_texts, dict):
        # Hand-written dialog replaces H3 texts that described the original
        # (unportable) mission; every slot must be authored, no partial fill.
        texts = SeerQuestTexts(
            first_visit=str(substitute_texts.get("first_visit") or "").strip(),
            next_visit=str(substitute_texts.get("next_visit") or "").strip(),
            completed=str(substitute_texts.get("completed") or "").strip(),
        )
        if not texts.first_visit or not texts.next_visit or not texts.completed:
            raise SeerHutQuestError(
                f"{context}: substitute texts must author all three dialog slots"
            )
    else:
        texts = coalesce_seer_quest_texts(
            SeerQuestTexts(
                first_visit=str(quest.get("firstVisitText") or ""),
                next_visit=str(quest.get("nextVisitText") or ""),
                completed=str(quest.get("completedText") or ""),
            ),
            mission,
            reward,
        )

    task_counter = None
    if isinstance(mission, (SeerMissionDefeatHero, SeerMissionDefeatSquad)):
        task_counter = f"{quest_id}_task"
    return SeerQuestPlan(
        quest_id=quest_id,
        hut_entity_sid=hut_entity_sid,
        state_counter_sid=state_counter,
        task_counter_sid=task_counter,
        mission=mission,
        reward=reward,
        texts=texts,
        dialog_first_sid=f"{quest_id}_first",
        dialog_next_sid=f"{quest_id}_next",
        dialog_completed_sid=f"{quest_id}_completed",
        last_day=quest.get("lastDay") if isinstance(quest.get("lastDay"), int) else None,
        substitution_note=substitution_note,
    )


def compile_seer_entity_script(
    entity: dict[str, Any],
    *,
    hut_entity_sid: str,
    target_entity_sid: str | None = None,
    mission_id: str | None = None,
) -> tuple[tuple[dict[str, Any], ...], tuple[str, ...], SeerQuestPlan]:
    plan = plan_from_seer_entity(
        entity,
        hut_entity_sid=hut_entity_sid,
        target_entity_sid=target_entity_sid,
        mission_id=mission_id,
    )
    return compile_seer_quest_triggers(plan), declared_counters_for_plan(plan), plan


def compile_seer_entity_subquests(
    entity: dict[str, Any],
    *,
    hut_entity_sid: str,
    target_entity_sid: str | None = None,
    mission_id: str | None = None,
) -> tuple[tuple[dict[str, Any], ...], tuple[str, ...], SeerQuestPlan]:
    """Compile a Seer entity with visit conditions isolated by subquest stage."""

    plan = plan_from_seer_entity(
        entity,
        hut_entity_sid=hut_entity_sid,
        target_entity_sid=target_entity_sid,
        mission_id=mission_id,
    )
    return (
        compile_seer_quest_subquests(plan),
        declared_counters_for_plan(plan),
        plan,
    )
