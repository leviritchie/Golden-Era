"""Shared Seer's Hut QuestScript compile for procedural and campaign ports.

Confirmed product shape (Steadwick user-visible proven): four SubQuest stages with
single-event triggers — offer / incomplete / ready / complete. Never AND
``ObjectInteractionBefore`` with Counter / ItemOwnSide / CounterEqualityInDays.
Operational contract: ``docs/homm3_seer_hut_questscript.md``.

v1 missions (stock Golden Era QuestScript evidence):
  3 defeat hero, 4 defeat stack, 5 bring artifacts, 6 bring creatures, 7 bring resources

Unsupported in v1 (fail closed): XP-level / primary-skill / be-hero / be-color
missions, mana/morale/luck rewards, HotA multi/repeatable.
v1 rewards: 0 none (intentional empty prize), 1 XP, 5 resource, 6 primary skill,
7 secondary skill, 8 artifact, 9 spell, 10 creatures.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Mapping, Sequence

HOMM3_SEER_HUT_SID = "homm3_seer_hut"
SUPPORTED_MISSION_TYPES = frozenset({3, 4, 5, 6, 7})
SUPPORTED_REWARD_TYPES = frozenset({0, 1, 5, 6, 7, 8, 9, 10})

# H3 primary skill index → GiveStatsHero stock param (campaign_starting_bonus).
H3_PRIMARY_SKILL_TO_STAT: tuple[str, ...] = (
    "offence",
    "defence",
    "spellPower",
    "intelligence",
)

# HoMM3 GENRLTXT Seer Hut Variant 1 English (when map custom strings are empty).
_RESOURCE_DISPLAY = {
    "wood": "Wood",
    "mercury": "Mercury",
    "ore": "Ore",
    "dust": "Sulfur",
    "crystals": "Crystal",
    "gemstones": "Gems",
    "gold": "Gold",
}


class SeerHutQuestError(ValueError):
    """Fail-closed Seer hut quest compile or decode error."""


@dataclass(frozen=True)
class SeerMissionDefeatHero:
    hero_sid: str


@dataclass(frozen=True)
class SeerMissionDefeatSquad:
    squad_sid: str


@dataclass(frozen=True)
class SeerMissionBringArtifacts:
    item_sids: tuple[str, ...]


@dataclass(frozen=True)
class SeerMissionBringCreatures:
    # (unit_sid, count)
    stacks: tuple[tuple[str, int], ...]


@dataclass(frozen=True)
class SeerMissionBringResources:
    # (resource_sid, amount)
    resources: tuple[tuple[str, int], ...]


SeerMission = (
    SeerMissionDefeatHero
    | SeerMissionDefeatSquad
    | SeerMissionBringArtifacts
    | SeerMissionBringCreatures
    | SeerMissionBringResources
)


@dataclass(frozen=True)
class SeerRewardExperience:
    amount: int


@dataclass(frozen=True)
class SeerRewardNone:
    """H3 reward type 0 — complete the quest and take payment, grant nothing.

    Authoring choice on stock maps (wiki: Target 12 Griffins; Here There Be
    Pirates resource sink). Not a decode miss.
    """

    pass


@dataclass(frozen=True)
class SeerRewardResource:
    resource: str
    amount: int


@dataclass(frozen=True)
class SeerRewardArtifact:
    item_sid: str


@dataclass(frozen=True)
class SeerRewardCreatures:
    unit_sid: str
    count: int


@dataclass(frozen=True)
class SeerRewardSecondarySkill:
    """H3 reward type 7 — grant a secondary skill at mastery 0..3 via AddSkillHero repeats."""

    skill_sid: str
    mastery: int


@dataclass(frozen=True)
class SeerRewardPrimarySkill:
    """H3 reward type 6 — grant one primary stat via GiveStatsHero."""

    stat: str
    amount: int


@dataclass(frozen=True)
class SeerRewardSpell:
    """H3 reward type 9 — teach a mechanics-matched OE magic via AddSpellHero."""

    magic_sid: str


@dataclass(frozen=True)
class SeerRewardHeroBuffDays:
    """Hand-crafted substitute reward — grant a stock hero buff for N days.

    Not an H3 reward type. Used by ``seer_hut_substitutes`` for H3 morale rewards
    (type 3), which OE QuestScript has no direct grant action for. Stock evidence:
    ``AddBuffHeroDays [buffSid, heroSid, days]`` appears in Core dialogs
    (M5Q7_dial6, M6Q7_dial1/2); M5Q7_dial6 proves the empty-heroSid fallthrough to
    the interacting hero. ``campaign_morale_buff`` (DB/heroes_buffs) grants
    heroStat moral +3; stock M6 rows use days=999 as the permanent-quest marker.
    """

    buff_sid: str
    days: int


@dataclass(frozen=True)
class SeerRewardManaRestore:
    """Hand-crafted substitute reward — refill the visiting hero's mana to full.

    Not an H3 reward type. Used by ``seer_hut_substitutes`` for H3 mana rewards
    (type 2): H3 granted +N spell points; OE has no proven interacting-hero mana
    donor (``vanilla_stock/victory_events.py`` names ChangeManaHero proven only
    with a named hero entity SID). Emits ``ChangeManaHero ["", "100"]`` — stock
    rows use [heroSid, percent] (M5_galthran_dial1 "0"; Fun and Graves
    fun_resurrection_completed "100"), and the empty heroSid rides the same
    ConInteract selectedHero fallthrough as AddSkillHero/GiveStatsHero/AddBuffHeroDays.
    Proof tier: generated artifact; empty-hero ChangeManaHero runtime unproven.
    """


SeerReward = (
    SeerRewardNone
    | SeerRewardExperience
    | SeerRewardResource
    | SeerRewardArtifact
    | SeerRewardCreatures
    | SeerRewardSecondarySkill
    | SeerRewardPrimarySkill
    | SeerRewardSpell
    | SeerRewardHeroBuffDays
    | SeerRewardManaRestore
)


@dataclass(frozen=True)
class SeerQuestTexts:
    first_visit: str
    next_visit: str
    completed: str


@lru_cache(maxsize=1)
def _artifact_names_by_sid() -> dict[str, str]:
    try:
        from vanilla_stock.h3_artifact_stock_map import catalog_rows
    except ImportError:
        return {}
    out: dict[str, str] = {}
    for row in catalog_rows():
        sid = str(row.get("sid") or "").strip()
        name = str(row.get("name") or "").strip()
        if sid and name:
            out[sid] = name
    return out


def _sid_display_name(sid: str) -> str:
    text = str(sid or "").strip()
    if not text:
        return "unknown"
    known = _artifact_names_by_sid().get(text)
    if known:
        return known
    if text in _RESOURCE_DISPLAY:
        return _RESOURCE_DISPLAY[text]
    slug = text
    for prefix in ("homm3_artifact_", "homm3_unit_", "homm3_"):
        if slug.startswith(prefix):
            slug = slug[len(prefix) :]
            break
    # Drop leading numeric catalog ids: 048_ladybird_of_luck → ladybird_of_luck
    parts = slug.split("_")
    if parts and parts[0].isdigit():
        parts = parts[1:]
    words = [part for part in parts if part]
    if not words:
        return text
    small = {"of", "the", "and", "a", "an"}
    titled: list[str] = []
    for index, word in enumerate(words):
        if index > 0 and word.lower() in small:
            titled.append(word.lower())
        else:
            titled.append(word[:1].upper() + word[1:].lower())
    return " ".join(titled)


def _join_names(names: Sequence[str]) -> str:
    items = [str(name).strip() for name in names if str(name).strip()]
    if not items:
        raise SeerHutQuestError("cannot format Seer dialog with an empty name list")
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return f"{items[0]} and {items[1]}"
    return ", ".join(items[:-1]) + f", and {items[-1]}"


def default_seer_quest_texts(mission: SeerMission, reward: SeerReward) -> SeerQuestTexts:
    """Stock HoMM3 seer wording when the map left first/next/completed strings empty.

    Campaign AB maps often ship empty custom strings; vanilla fills GENRLTXT templates.
    OE has no those templates for ``homm3_seer_hut``, so emit the English Variant 1 text
    with mission names resolved from catalog SIDs.
    """

    del reward  # reward is named in completion only for some vanilla lines; keep signature stable
    if isinstance(mission, SeerMissionBringArtifacts):
        target = _join_names(_sid_display_name(sid) for sid in mission.item_sids)
        return SeerQuestTexts(
            first_visit=(
                "Long ago, powerful wizards were able to create magical artifacts, but "
                "time has caused us to forget how to make new items. I would like to "
                "learn these techniques myself, but I need one of these artifacts first "
                f"to see how it was done. If you could bring me, the {target}, you would "
                "be well rewarded."
            ),
            next_visit=(
                f"Nothing, eh? I'm sure you will find the {target} soon. Please keep looking."
            ),
            completed=(
                "Ah, exactly what I needed! Here is the reward I promised. You still wish "
                f"to trade the {target}, yes?"
            ),
        )
    if isinstance(mission, SeerMissionBringCreatures):
        target = _join_names(
            f"{count} {_sid_display_name(unit_sid)}" for unit_sid, count in mission.stacks
        )
        return SeerQuestTexts(
            first_visit=(
                "I am an agent for an emperor of a distant land. Recently, his armies have "
                f"fallen on hard times. If you could bring {target} to me, I could pay you "
                "handsomely."
            ),
            next_visit=(
                f"No luck in finding the {target}? Please hurry, the empire depends on you."
            ),
            completed=(
                f"At last, the {target} that will save our empire! Here is your payment. "
                "Are they ready to depart?"
            ),
        )
    if isinstance(mission, SeerMissionBringResources):
        target = _join_names(
            f"{amount} {_sid_display_name(resource)}"
            for resource, amount in mission.resources
        )
        return SeerQuestTexts(
            first_visit=(
                "I am researching a way to turn base metals into gold, but I am short of "
                f"materials for my workshop. If you could bring me {target}, I would be "
                "most grateful."
            ),
            next_visit=(
                f"Oh my, that's simply not enough. I need {target}. I'll never complete it "
                "with what you have."
            ),
            completed=(
                f"Finally! Here, give the {target} to me, and I'll give you this in return."
            ),
        )
    if isinstance(mission, SeerMissionDefeatHero):
        target = _sid_display_name(mission.hero_sid)
        return SeerQuestTexts(
            first_visit=(
                f"I was once rich and famous, but {target} the terrible was my downfall. "
                "I lost my lands, I lost my title, and I lost my family. Please, bring the "
                "villain to justice."
            ),
            next_visit=(
                f"Oh, I wish you brought better news. It aches my heart that {target} still "
                "roams free."
            ),
            completed=(
                f"I thought the day would never come! {target} is no more. Please, will you "
                "accept this reward?"
            ),
        )
    if isinstance(mission, SeerMissionDefeatSquad):
        target = _sid_display_name(mission.squad_sid)
        return SeerQuestTexts(
            first_visit=(
                f"{target} are menacing this land. If you could be so bold as to defeat "
                "them, I would reward you richly."
            ),
            next_visit=(
                f"Don't lose heart. Defeating the {target} is a difficult task, but you "
                "will surely succeed."
            ),
            completed=(
                f"At last, you defeated the {target}, and the countryside is safe again! "
                "Are you ready to accept the reward?"
            ),
        )
    raise SeerHutQuestError(f"unsupported mission type for default texts: {type(mission)!r}")


def coalesce_seer_quest_texts(
    texts: SeerQuestTexts,
    mission: SeerMission,
    reward: SeerReward,
) -> SeerQuestTexts:
    """Keep non-empty map custom strings; fill any blank slot from GENRLTXT defaults."""

    defaults = default_seer_quest_texts(mission, reward)
    first = str(texts.first_visit or "").strip() or defaults.first_visit
    next_visit = str(texts.next_visit or "").strip() or defaults.next_visit
    completed = str(texts.completed or "").strip() or defaults.completed
    if not first or not next_visit or not completed:
        raise SeerHutQuestError("Seer quest dialog texts resolved empty after defaults")
    return SeerQuestTexts(first_visit=first, next_visit=next_visit, completed=completed)


@dataclass(frozen=True)
class SeerQuestPlan:
    """One one-time Seer hut quest bound to a persistent host entity."""

    quest_id: str
    hut_entity_sid: str
    state_counter_sid: str
    mission: SeerMission
    reward: SeerReward
    texts: SeerQuestTexts
    task_counter_sid: str | None = None
    dialog_first_sid: str | None = None
    dialog_next_sid: str | None = None
    dialog_completed_sid: str | None = None
    last_day: int | None = None
    # Set by seer_hut_substitutes when a hand-crafted substitute replaces an
    # unsupported H3 mission/reward. Emitted into the story row so future readers
    # of the generated map can see why it differs from the H3 original.
    substitution_note: str | None = None


def _require_sid(value: str, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SeerHutQuestError(f"{field} must be a non-empty SID")
    return value.strip()


def seer_quest_id_for_source_key(source_key: str) -> str:
    value = str(source_key or "").strip()
    if not value:
        raise SeerHutQuestError("seer source_key must be a non-empty string")
    return f"seer_{value.replace(':', '_')}"


def _counter_condition(counter_sid: str, value: int) -> dict[str, Any]:
    # Counter listens to CounterChanged only — it is not a state poll.
    # Never AND it with ObjectInteractionBefore in the same trigger.
    return {
        "comment": "",
        "c": "Counter",
        "p": [counter_sid, "=", str(value)],
        "counter": 1,
    }


def _counter_set(counter_sid: str, value: int) -> dict[str, Any]:
    return {"comment": "", "a": "CounterSet", "p": [counter_sid, str(value)]}


def _subquest_activate(quest_id: str, stage_sid: str) -> dict[str, Any]:
    return {
        "comment": "",
        "a": "SubQuestActivate",
        "p": [quest_id, stage_sid],
    }


def _subquest_deactivate(quest_id: str, stage_sid: str) -> dict[str, Any]:
    # SubQuestDone only marks data.done; it does not stop listening.
    # Vanilla maps (Fun_and_Graves, song_of_murmurwood) use SubQuestDeactivate.
    return {
        "comment": "",
        "a": "SubQuestDeactivate",
        "p": [quest_id, stage_sid],
    }


def _subquest_done(quest_id: str, stage_sid: str) -> dict[str, Any]:
    return {
        "comment": "",
        "a": "SubQuestDone",
        "p": [quest_id, stage_sid],
    }


def _visit(entity_sid: str) -> dict[str, Any]:
    return {
        "comment": "",
        # Matches PropertyEntity.sid from propEntities (not objects[].sid /
        # sidConfig). Decomp: ConInteractQuestObjectBefore compares propEntity.sid.
        "c": "ObjectInteractionBefore",
        "p": [entity_sid],
        "counter": 1,
    }


def _dialog(dialog_sid: str) -> dict[str, Any]:
    return {"comment": "", "a": "Dialog", "p": [dialog_sid]}


def _item_own_side(item_sid: str, op: str, amount: int) -> dict[str, Any]:
    return {
        "comment": "",
        "c": "ItemOwnSide",
        "p": [item_sid, op, str(amount)],
        "counter": 1,
    }


def _unit_own_side(unit_sid: str, op: str, amount: int) -> dict[str, Any]:
    return {
        "comment": "",
        "c": "UnitOwnSide",
        "p": [unit_sid, op, str(amount)],
        "counter": 1,
    }


def _res_counter(resource: str, op: str, amount: int) -> dict[str, Any]:
    return {
        "comment": "",
        "c": "ResCounter",
        "p": [resource, op, str(amount)],
        "counter": 1,
    }


def _mission_complete_conditions(plan: SeerQuestPlan) -> list[dict[str, Any]]:
    mission = plan.mission
    if isinstance(mission, SeerMissionDefeatHero):
        if not plan.task_counter_sid:
            raise SeerHutQuestError(f"{plan.quest_id}: defeat-hero requires task_counter_sid")
        return [_counter_condition(plan.task_counter_sid, 1)]
    if isinstance(mission, SeerMissionDefeatSquad):
        if not plan.task_counter_sid:
            raise SeerHutQuestError(f"{plan.quest_id}: defeat-squad requires task_counter_sid")
        return [_counter_condition(plan.task_counter_sid, 1)]
    if isinstance(mission, SeerMissionBringArtifacts):
        if not mission.item_sids:
            raise SeerHutQuestError(f"{plan.quest_id}: bring-artifacts requires item SIDs")
        return [_item_own_side(sid, ">", 0) for sid in mission.item_sids]
    if isinstance(mission, SeerMissionBringCreatures):
        if not mission.stacks:
            raise SeerHutQuestError(f"{plan.quest_id}: bring-creatures requires stacks")
        return [
            _unit_own_side(unit_sid, ">=", count) for unit_sid, count in mission.stacks
        ]
    if isinstance(mission, SeerMissionBringResources):
        if not mission.resources:
            raise SeerHutQuestError(f"{plan.quest_id}: bring-resources requires resources")
        return [
            _res_counter(resource, ">=", amount)
            for resource, amount in mission.resources
        ]
    raise SeerHutQuestError(f"{plan.quest_id}: unsupported mission type {type(mission)!r}")


def _mission_consume_actions(plan: SeerQuestPlan) -> list[dict[str, Any]]:
    mission = plan.mission
    if isinstance(mission, (SeerMissionDefeatHero, SeerMissionDefeatSquad)):
        return []
    if isinstance(mission, SeerMissionBringArtifacts):
        return [
            {"comment": "", "a": "RemoveItem", "p": [item_sid]}
            for item_sid in mission.item_sids
        ]
    if isinstance(mission, SeerMissionBringCreatures):
        return [
            {
                "comment": "",
                "a": "RemoveUnitHero",
                "p": [unit_sid, str(count)],
            }
            for unit_sid, count in mission.stacks
        ]
    if isinstance(mission, SeerMissionBringResources):
        return [
            {
                "comment": "",
                "a": "RemoveRes",
                "p": [resource, str(amount)],
            }
            for resource, amount in mission.resources
        ]
    raise SeerHutQuestError(f"{plan.quest_id}: unsupported mission type {type(mission)!r}")


def _reward_actions(plan: SeerQuestPlan) -> list[dict[str, Any]]:
    reward = plan.reward
    if isinstance(reward, SeerRewardNone):
        return []
    if isinstance(reward, SeerRewardExperience):
        if reward.amount <= 0:
            raise SeerHutQuestError(f"{plan.quest_id}: XP reward must be positive")
        return [{"comment": "", "a": "GiveExpHero", "p": [str(reward.amount)]}]
    if isinstance(reward, SeerRewardResource):
        if reward.amount <= 0:
            raise SeerHutQuestError(f"{plan.quest_id}: resource reward must be positive")
        return [
            {
                "comment": "",
                "a": "GiveRes",
                "p": [reward.resource, str(reward.amount)],
            }
        ]
    if isinstance(reward, SeerRewardArtifact):
        return [{"comment": "", "a": "GiveItemHero", "p": [reward.item_sid]}]
    if isinstance(reward, SeerRewardCreatures):
        if reward.count <= 0:
            raise SeerHutQuestError(f"{plan.quest_id}: creature reward count must be positive")
        return [
            {
                "comment": "",
                "a": "GiveUnitHero",
                "p": [reward.unit_sid, str(reward.count)],
            }
        ]
    if isinstance(reward, SeerRewardSecondarySkill):
        if reward.mastery < 0 or reward.mastery > 3:
            raise SeerHutQuestError(
                f"{plan.quest_id}: secondary skill mastery must be 0..3, got {reward.mastery}"
            )
        # AddSkillHero requires [skillSid, heroSid]; empty heroSid falls through to
        # the interacting selectedHero (ConInteract path). Mastery repeats match
        # placed-hero payload policy (level 3 → 3 grants; else level+1).
        repeats = 3 if reward.mastery == 3 else reward.mastery + 1
        return [
            {
                "comment": f"seer secondary skill {reward.skill_sid} mastery {reward.mastery}",
                "a": "AddSkillHero",
                "p": [reward.skill_sid, ""],
            }
            for _ in range(repeats)
        ]
    if isinstance(reward, SeerRewardPrimarySkill):
        if reward.amount <= 0:
            raise SeerHutQuestError(f"{plan.quest_id}: primary skill amount must be positive")
        if reward.stat not in H3_PRIMARY_SKILL_TO_STAT:
            raise SeerHutQuestError(
                f"{plan.quest_id}: unknown primary stat {reward.stat!r}"
            )
        # GiveStatsHero stock params: [stat, heroSid, amount]. Empty heroSid → selectedHero.
        return [
            {
                "comment": f"seer primary skill {reward.stat} +{reward.amount}",
                "a": "GiveStatsHero",
                "p": [reward.stat, "", str(reward.amount)],
            }
        ]
    if isinstance(reward, SeerRewardSpell):
        if not reward.magic_sid.strip():
            raise SeerHutQuestError(f"{plan.quest_id}: spell reward missing magic SID")
        return [
            {
                "comment": f"seer spell {reward.magic_sid}",
                "a": "AddSpellHero",
                "p": [reward.magic_sid, ""],
            }
        ]
    if isinstance(reward, SeerRewardHeroBuffDays):
        if not reward.buff_sid.strip():
            raise SeerHutQuestError(f"{plan.quest_id}: hero-buff reward missing buff SID")
        if reward.days <= 0:
            raise SeerHutQuestError(f"{plan.quest_id}: hero-buff days must be positive")
        return [
            {
                "comment": f"seer hero buff {reward.buff_sid} for {reward.days} days",
                "a": "AddBuffHeroDays",
                "p": [reward.buff_sid, "", str(reward.days)],
            }
        ]
    if isinstance(reward, SeerRewardManaRestore):
        return [
            {
                "comment": "seer mana substitute: refill visiting hero to 100%",
                "a": "ChangeManaHero",
                "p": ["", "100"],
            }
        ]
    raise SeerHutQuestError(f"{plan.quest_id}: unsupported reward type {type(reward)!r}")


def _ready_stage_conditions(plan: SeerQuestPlan) -> list[dict[str, Any]]:
    """Single-event-family conditions that mean the Seer task is satisfiable.

    These must not be ANDed with ObjectInteractionBefore. QuestScript AND latches
    each condition on its own event and deactivates it until the whole AND is
    done — mixing visit + Counter/ItemOwnSide therefore deadlocks.
    """

    mission = plan.mission
    if isinstance(mission, (SeerMissionDefeatHero, SeerMissionDefeatSquad)):
        if isinstance(mission, SeerMissionDefeatHero):
            return [
                {
                    "comment": "",
                    "c": "HeroKill",
                    "p": [mission.hero_sid],
                    "counter": 1,
                }
            ]
        return [
            {
                "comment": "",
                "c": "SquadKill",
                "p": [mission.squad_sid],
                "counter": 1,
            }
        ]
    return _mission_complete_conditions(plan)


def _stage_row(
    *,
    quest_id: str,
    stage_sid: str,
    active_on_start: bool,
    comment: str,
    triggers: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "questSid": quest_id,
        "sid": stage_sid,
        "activeOnStart": active_on_start,
        "hidden": True,
        "name": "",
        "desc": "",
        "comment": comment,
        "triggers": triggers,
    }


def compile_seer_quest_subquests(plan: SeerQuestPlan) -> tuple[dict[str, Any], ...]:
    """Compile the Seer FSM into four SubQuest stages with single-event triggers.

    OE QuestScript conditions are event latches, not state polls. ANDing
    ``ObjectInteractionBefore`` with ``Counter`` / ``ItemOwnSide`` /
    ``CounterEqualityInDays`` deadlocks (each listens to a different event;
    a lone Done deactivates that listener while waiting for the others).

    Stage ownership (vanilla SubQuestActivate / SubQuestDeactivate):
    - offer (active): visit → first dialog, deactivate offer, activate incomplete+ready
    - incomplete: visit → interim dialog (repeat)
    - ready: mission-complete event(s) → deactivate incomplete+ready, activate complete
    - complete: visit → exchange + rewards
    """

    _require_sid(plan.quest_id, field="quest_id")
    hut = _require_sid(plan.hut_entity_sid, field="hut_entity_sid")
    state = _require_sid(plan.state_counter_sid, field="state_counter_sid")
    dialog_first = plan.dialog_first_sid or f"{plan.quest_id}_first"
    dialog_next = plan.dialog_next_sid or f"{plan.quest_id}_next"
    dialog_done = plan.dialog_completed_sid or f"{plan.quest_id}_completed"

    offer_sid = f"{plan.quest_id}_offer"
    incomplete_sid = f"{plan.quest_id}_incomplete"
    ready_sid = f"{plan.quest_id}_ready"
    complete_sid = f"{plan.quest_id}_complete"

    offer = {
        "comment": f"{plan.quest_id}_offer",
        "repeat": False,
        "conditionsLogic": "And",
        "conditions": [_visit(hut)],
        "actions": [
            _dialog(dialog_first),
            _counter_set(state, 1),
            _subquest_deactivate(plan.quest_id, offer_sid),
            _subquest_activate(plan.quest_id, incomplete_sid),
            _subquest_activate(plan.quest_id, ready_sid),
            _subquest_done(plan.quest_id, offer_sid),
        ],
    }

    incomplete = {
        "comment": f"{plan.quest_id}_incomplete",
        "repeat": True,
        "conditionsLogic": "And",
        "conditions": [_visit(hut)],
        "actions": [_dialog(dialog_next)],
    }

    ready = {
        "comment": f"{plan.quest_id}_ready",
        "repeat": False,
        "conditionsLogic": "And",
        "conditions": _ready_stage_conditions(plan),
        "actions": [
            _counter_set(state, 2),
            _subquest_deactivate(plan.quest_id, incomplete_sid),
            _subquest_deactivate(plan.quest_id, ready_sid),
            _subquest_activate(plan.quest_id, complete_sid),
            _subquest_done(plan.quest_id, ready_sid),
        ],
    }

    complete = {
        "comment": f"{plan.quest_id}_complete",
        "repeat": False,
        "conditionsLogic": "And",
        "conditions": [_visit(hut)],
        "actions": [
            *_mission_consume_actions(plan),
            *_reward_actions(plan),
            _dialog(dialog_done),
            _counter_set(state, 3),
            _subquest_deactivate(plan.quest_id, complete_sid),
            _subquest_done(plan.quest_id, complete_sid),
        ],
    }

    if isinstance(plan.mission, (SeerMissionDefeatHero, SeerMissionDefeatSquad)):
        if not plan.task_counter_sid:
            raise SeerHutQuestError(f"{plan.quest_id}: defeat mission requires task_counter_sid")
        # Stamp the task counter on the same kill event that opens completion.
        ready["actions"] = [
            _counter_set(plan.task_counter_sid, 1),
            *ready["actions"],
        ]

    return (
        _stage_row(
            quest_id=plan.quest_id,
            stage_sid=offer_sid,
            active_on_start=True,
            comment=f"{plan.quest_id} Seer offer stage",
            triggers=[offer],
        ),
        _stage_row(
            quest_id=plan.quest_id,
            stage_sid=incomplete_sid,
            active_on_start=False,
            comment=f"{plan.quest_id} Seer interim stage",
            triggers=[incomplete],
        ),
        _stage_row(
            quest_id=plan.quest_id,
            stage_sid=ready_sid,
            active_on_start=False,
            comment=f"{plan.quest_id} Seer task-ready watcher",
            triggers=[ready],
        ),
        _stage_row(
            quest_id=plan.quest_id,
            stage_sid=complete_sid,
            active_on_start=False,
            comment=f"{plan.quest_id} Seer completion stage",
            triggers=[complete],
        ),
    )


def compile_seer_quest_triggers(plan: SeerQuestPlan) -> tuple[dict[str, Any], ...]:
    """Compatibility view: flatten the event-isolated Seer subquest triggers."""

    return tuple(
        trigger
        for subquest in compile_seer_quest_subquests(plan)
        for trigger in subquest["triggers"]
    )


def declared_counters_for_plan(plan: SeerQuestPlan) -> tuple[str, ...]:
    counters = [plan.state_counter_sid]
    if plan.task_counter_sid:
        counters.append(plan.task_counter_sid)
    return tuple(counters)


def assert_supported_mission_type(mission_type: int, *, context: str) -> None:
    if mission_type not in SUPPORTED_MISSION_TYPES:
        raise SeerHutQuestError(
            f"{context}: unsupported Seer mission type {mission_type}; "
            f"v1 allows {sorted(SUPPORTED_MISSION_TYPES)}"
        )


def assert_supported_reward_type(reward_type: int, *, context: str) -> None:
    if reward_type not in SUPPORTED_REWARD_TYPES:
        raise SeerHutQuestError(
            f"{context}: unsupported Seer reward type {reward_type}; "
            f"v1 allows {sorted(SUPPORTED_REWARD_TYPES)}"
        )


def homm3_seer_hut_object_row() -> dict[str, Any]:
    """ObjectConfig for the custom Seer hut (wise_owl donor footprint; billboard replaces mesh).

    Must match stock ``wise_owl`` size/nodes. A prior 3x2 H3-mask ObjectConfig with a 2x2
    interactable prefab failed closed at runtime (no map-object Init / invisible host).

    Placement: ``exact_homm3_footprint.classify_object_config_shape`` treats this SID as
    ``single_gate`` so emit GATE-aligns the preferred south-east marker onto the H3 visit
    cell (wise_owl's 3 GATE markers would otherwise classify as ``other`` and keep BR
    placement on river water).
    """

    return {
        "id": HOMM3_SEER_HUT_SID,
        "tag": "Interact",
        "isInteractable": True,
        "prefs": ["interactive/wise_owl"],
        "canBeMirrored": False,
        "selectionUiPrefabID": "1x1",
        "pivotX": 0,
        "pivotZ": 0,
        "sizeX": 2,
        "sizeZ": 2,
        "offsetX": 0,
        "offsetZ": 0,
        # Match DB/map/objects/4_interactables.json wise_owl exactly.
        "nodes": [1, 2, 2, 2],
        "gateInsideObject": True,
        "proceduralEligible": True,
        "generatorConfig": {
            "buildingSizeX": 1,
            "buildingSizeZ": 1,
            "buildingLeftBottomX": 0,
            "buildingLeftBottomZ": 0,
            "buildingInteractionLayout": 0,
        },
    }


def homm3_seer_hut_event_bank_doc() -> dict[str, Any]:
    """Minimal objects_logic shell so OE registers an Interact visit cursor.

    ObjectConfig alone is not enough: without an event-bank row the adventure cursor
    treats the host like non-building scenery (red circle). Empty ``rewards: []`` is
    forbidden (ObjEventBank/RewardSetConfig IndexOutOfRange on Steadwick). Use the
    proven campaign no-op pattern (MovePointsAdditionReward 0, Invisible), then let
    QuestScript own dialog/rewards; ``EntityActionsOff`` only after quest complete.
    """

    return {
        "array": [
            {
                "id": HOMM3_SEER_HUT_SID,
                "tooltipVisitType": "NoRewardAndScouting",
                "variantRerollType": "None",
                "visitorsResetType": "None",
                "visitType": "Unlimited",
                "variants": [
                    {
                        "rollChance": 100,
                        "value": 0,
                        "guardUnits": [],
                        "rewardSet": {
                            "rewardSetShowType": "Invisible",
                            "rewardSetApplyType": "ForAll",
                            "rewardSetCancelType": "CancelAndDelete",
                            "rewards": [
                                {
                                    "rewardType": "MovePointsAdditionReward",
                                    "rewardShowType": "Invisible",
                                    "applyRewardFloating": True,
                                    "rewardIcon": "default",
                                    "rewardName": "default",
                                    "rewardDesc": "default",
                                    "rewardNotificationDesc": "default",
                                    "parameters": ["0"],
                                }
                            ],
                        },
                    }
                ],
            }
        ]
    }
