"""End-to-end deterministic graph-and-constraint scenario generation."""

from __future__ import annotations

import re
from typing import Iterable

from .catalog import CatalogBuildError, ContentCatalogSnapshot
from .events import (
    CaptureTrigger,
    CounterAction,
    CounterOperation,
    CounterTrigger,
    MechanicalEventSpec,
    ObjectiveProgressAction,
    ResourceAction,
    SquadDefeatTrigger,
    TurnTrigger,
    VictoryAction,
    VisitTrigger,
    compile_mechanical_events,
    mechanical_fingerprint,
)
from .layout import decision_distances, embed_progression_graph
from .model import (
    Archetype,
    ConstraintViolation,
    GENERATED_SCENARIO_IR_SCHEMA,
    GENERATOR_VERSION,
    GeneratedScenarioIR,
    GenerationFailure,
    GenerationProvenance,
    Placement,
    PlacementKind,
    ScenarioMetrics,
)
from .placement import PlacementRngStreams, place_scenario_content
from .profile import ScenarioProfileV1
from .rng import StageRngFactory
from .terrain import paint_surface_terrain
from .topology import build_progression_graph


def generate_scenario(
    profile: ScenarioProfileV1,
    catalog: ContentCatalogSnapshot,
    *,
    donor_hash: str,
) -> GeneratedScenarioIR:
    """Generate deterministic semantic mechanics; perform no I/O or text calls."""

    profile = profile.normalized()
    donor_hash = _require_hash("donor_hash", donor_hash)
    missing_allowlist = sorted(
        set(profile.content_allowlist) - set(catalog.allowlist)
    )
    if missing_allowlist:
        raise GenerationFailure(
            "catalog",
            (
                ConstraintViolation(
                    "catalog_allowlist_mismatch",
                    "catalog",
                    "catalog snapshot was not built with every profile allowlist SID",
                    (("sids", missing_allowlist),),
                ),
            ),
            seed=profile.seed,
        )
    try:
        catalog.require_factions(profile.factions)
        for biome in profile.biomes:
            catalog.terrain_for_biome(biome)
        catalog.terrain_for_biome(profile.terrain.road_biome)
    except CatalogBuildError as ex:
        raise GenerationFailure(
            "catalog",
            (
                ConstraintViolation(
                    "profile_content_unresolved",
                    "catalog",
                    str(ex),
                ),
            ),
            seed=profile.seed,
        ) from ex

    streams = StageRngFactory(
        profile.seed,
        generator_version=GENERATOR_VERSION,
        profile_hash=profile.fingerprint,
        donor_hash=donor_hash,
        catalog_hash=catalog.fingerprint,
    )
    topology = build_progression_graph(profile, streams.stream("topology"))
    layout = embed_progression_graph(
        topology,
        profile,
        streams.stream("layout"),
    )
    terrain = paint_surface_terrain(
        layout,
        profile,
        catalog,
        streams.stream("terrain"),
    )
    placements = place_scenario_content(
        topology,
        layout,
        terrain,
        profile,
        catalog,
        PlacementRngStreams(
            required=streams.stream("placement.required"),
            anchors=streams.stream("placement.anchors"),
            optional=streams.stream("placement.optional"),
            scenery=streams.stream("placement.scenery"),
        ),
    )
    scenario_id = _scenario_id(profile)
    map_sid = scenario_id
    placements, seer_triggers, seer_subquests, seer_dialogs = _attach_seer_huts(
        profile,
        placements,
        catalog,
        scenario_id=scenario_id,
    )
    events, declared_counters = _build_events(
        profile,
        topology.victory_zone_id,
        placements,
        scenario_id=scenario_id,
    )
    try:
        compile_mechanical_events(
            events,
            declared_counter_sids=declared_counters,
            require_explicit_victory=True,
        )
    except (TypeError, ValueError) as ex:
        raise GenerationFailure(
            "events",
            (
                ConstraintViolation(
                    "mechanical_event_contract",
                    "events",
                    str(ex),
                ),
            ),
            seed=profile.seed,
        ) from ex

    metrics = _metrics(profile, topology.zones, layout, placements)
    event_hash = mechanical_fingerprint(events)
    if seer_triggers:
        from .model import sha256_json

        event_hash = sha256_json(
            {
                "events": event_hash,
                "seerTriggers": list(seer_triggers),
                "seerSubQuests": list(seer_subquests),
            }
        )
    provenance = GenerationProvenance(
        generator_version=GENERATOR_VERSION,
        profile_hash=profile.fingerprint,
        catalog_hash=catalog.fingerprint,
        donor_hash=donor_hash,
        source_hashes=catalog.source_hashes,
        stage_seeds=tuple(
            (item.stage, item.seed) for item in streams.issued_seeds
        ),
        mechanical_hash=event_hash,
    )
    return GeneratedScenarioIR(
        scenario_id=scenario_id,
        map_sid=map_sid,
        seed=profile.seed,
        profile=profile,
        topology=topology,
        layout=layout,
        terrain=terrain,
        placements=placements,
        events=events,
        metrics=metrics,
        provenance=provenance,
        schema=GENERATED_SCENARIO_IR_SCHEMA,
        seer_script_triggers=seer_triggers,
        seer_script_subquests=seer_subquests,
        seer_dialog_plans=seer_dialogs,
    )


def _attach_seer_huts(
    profile: ScenarioProfileV1,
    placements: tuple[Placement, ...],
    catalog: ContentCatalogSnapshot,
    *,
    scenario_id: str,
) -> tuple[
    tuple[Placement, ...],
    tuple[dict, ...],
    tuple[dict, ...],
    tuple[dict, ...],
]:
    count = int(profile.event_policy.seer_hut_count)
    if count <= 0:
        return placements, (), (), ()

    known_sids = {entry.sid for entry in catalog.entries}
    if "homm3_seer_hut" not in known_sids:
        raise GenerationFailure(
            "placement",
            (
                ConstraintViolation(
                    "seer_hut_objectconfig_missing",
                    "placement",
                    "eventPolicy.seerHutCount>0 requires homm3_seer_hut in the Core catalog",
                ),
            ),
            seed=profile.seed,
        )

    encounters = [item for item in placements if item.kind is PlacementKind.ENCOUNTER]
    hosts = [
        item
        for item in placements
        if item.kind in {PlacementKind.INTERACTABLE, PlacementKind.QUEST_GIVER}
    ]
    if len(encounters) < count or len(hosts) < count:
        raise GenerationFailure(
            "placement",
            (
                ConstraintViolation(
                    "seer_hut_hosts_unavailable",
                    "placement",
                    "seerHutCount requires at least that many encounters and interactable hosts",
                    (
                        ("seerHutCount", count),
                        ("encounters", len(encounters)),
                        ("hosts", len(hosts)),
                    ),
                ),
            ),
            seed=profile.seed,
        )

    import sys
    from pathlib import Path

    repo_campaign = Path(__file__).resolve().parents[1]
    if str(repo_campaign) not in sys.path:
        sys.path.insert(0, str(repo_campaign))
    from seer_hut_quest import (
        SeerMissionDefeatSquad,
        SeerQuestPlan,
        SeerQuestTexts,
        SeerRewardExperience,
        compile_seer_quest_subquests,
        compile_seer_quest_triggers,
    )

    rewritten: list[Placement] = []
    host_ids = {hosts[i].placement_id for i in range(count)}
    triggers: list[dict] = []
    subquests: list[dict] = []
    dialogs: list[dict] = []
    for item in placements:
        if item.placement_id not in host_ids:
            rewritten.append(item)
            continue
        rewritten.append(
            Placement(
                placement_id=item.placement_id,
                kind=PlacementKind.QUEST_GIVER,
                content_sid="homm3_seer_hut",
                origin=item.origin,
                node=item.node,
                zone_id=item.zone_id,
                footprint=item.footprint,
                interactive=True,
                risk_tier=item.risk_tier,
                metadata=item.metadata
                + (
                    ("seerQuest", True),
                    ("seerObjectSid", "homm3_seer_hut"),
                ),
            )
        )

    for index in range(count):
        hut = next(p for p in rewritten if p.placement_id == hosts[index].placement_id)
        squad = encounters[index]
        quest_id = f"{scenario_id}_seer_{index:02d}"
        plan = SeerQuestPlan(
            quest_id=quest_id,
            hut_entity_sid=hut.placement_id,
            state_counter_sid=f"{quest_id}_state",
            task_counter_sid=f"{quest_id}_task",
            mission=SeerMissionDefeatSquad(squad_sid=squad.placement_id),
            reward=SeerRewardExperience(
                amount=round(1000 * profile.economy.reward_multiplier)
            ),
            texts=SeerQuestTexts(
                first_visit="A seer asks you to defeat a nearby threat, then return.",
                next_visit="The seer waits for news that the threat is gone.",
                completed="The seer rewards your victory.",
            ),
            dialog_first_sid=f"{quest_id}_first",
            dialog_next_sid=f"{quest_id}_next",
            dialog_completed_sid=f"{quest_id}_completed",
        )
        triggers.extend(compile_seer_quest_triggers(plan))
        subquests.extend(compile_seer_quest_subquests(plan))
        dialogs.append(
            {
                "questId": quest_id,
                "dialogFirstSid": plan.dialog_first_sid,
                "dialogNextSid": plan.dialog_next_sid,
                "dialogCompletedSid": plan.dialog_completed_sid,
                "firstVisitText": plan.texts.first_visit,
                "nextVisitText": plan.texts.next_visit,
                "completedText": plan.texts.completed,
            }
        )
    return tuple(rewritten), tuple(triggers), tuple(subquests), tuple(dialogs)


def _build_events(
    profile: ScenarioProfileV1,
    victory_zone_id: str,
    placements: tuple[Placement, ...],
    *,
    scenario_id: str,
) -> tuple[tuple[MechanicalEventSpec, ...], tuple[str, ...]]:
    policy = profile.event_policy
    objectives = tuple(
        item for item in placements if item.kind is PlacementKind.OBJECTIVE
    )
    encounters = tuple(
        item for item in placements if item.kind is PlacementKind.ENCOUNTER
    )
    ai_settlements = tuple(
        item for item in placements if item.kind is PlacementKind.AI_SETTLEMENT
    )
    if objectives and (
        not policy.visit_events_enabled or not policy.objective_progress_enabled
    ):
        raise GenerationFailure(
            "events",
            (
                ConstraintViolation(
                    "objective_events_disabled",
                    "events",
                    "selected archetype requires visit and objective-progress events",
                ),
            ),
            seed=profile.seed,
        )
    if profile.archetype is Archetype.CONQUEST and not policy.capture_events_enabled:
        raise GenerationFailure(
            "events",
            (
                ConstraintViolation(
                    "capture_events_disabled",
                    "events",
                    "conquest requires capture events",
                ),
            ),
            seed=profile.seed,
        )
    if profile.economy.recurring_income_enabled:
        raise GenerationFailure(
            "events",
            (
                ConstraintViolation(
                    "recurring_schedule_unproven",
                    "events",
                    "recurring-income interval compilation has no proven native backend",
                ),
            ),
            seed=profile.seed,
        )

    events: list[MechanicalEventSpec] = []
    declared_counters: set[str] = set()
    objective_counter = f"{scenario_id}_objectives_completed"
    if objectives:
        declared_counters.add(objective_counter)
    objective_counter_sids: tuple[str, ...] = tuple(
        str(dict(item.metadata).get("counterSid"))
        for item in objectives
        if dict(item.metadata).get("counterSid")
    )
    declared_counters.update(objective_counter_sids)

    if policy.turn_schedules_enabled:
        actions = []
        if profile.economy.starting_gold:
            actions.append(ResourceAction("gold", profile.economy.starting_gold))
        if profile.economy.starting_wood:
            actions.append(ResourceAction("wood", profile.economy.starting_wood))
        if profile.economy.starting_ore:
            actions.append(ResourceAction("ore", profile.economy.starting_ore))
        if actions:
            events.append(
                MechanicalEventSpec(
                    event_id=f"{scenario_id}_starting_resources",
                    triggers=(TurnTrigger(1),),
                    actions=tuple(actions),
                    title="Starting resources",
                )
            )

    for index, placement in enumerate(objectives):
        actions: list[object] = [
            CounterAction(
                objective_counter,
                1,
                CounterOperation.PLUS,
            )
        ]
        objective_counter_sid = str(dict(placement.metadata).get("counterSid") or "")
        if objective_counter_sid and objective_counter_sid != objective_counter:
            actions.append(CounterAction(objective_counter_sid, 1, CounterOperation.PLUS))
        actions.append(ObjectiveProgressAction(f"{scenario_id}_objective_{index:02d}"))
        if policy.resource_rewards_enabled:
            actions.append(
                ResourceAction(
                    "gold",
                    round(
                        (500 + placement.risk_tier * 250)
                        * profile.economy.reward_multiplier
                    ),
                )
            )
        objective_triggers: list[CounterTrigger | VisitTrigger] = [VisitTrigger(placement.placement_id)]
        if profile.archetype is Archetype.OBJECTIVE_CHAIN and index > 0:
            previous_counter_sid = str(
                dict(objectives[index - 1].metadata).get("counterSid") or ""
            )
            if not previous_counter_sid:
                raise GenerationFailure(
                    "events",
                    (
                        ConstraintViolation(
                            "objective_chain_counter_missing",
                            "events",
                            "objective-chain objectives require ordered counter SIDs",
                            (("objectiveIndex", index),),
                        ),
                    ),
                    seed=profile.seed,
                )
            objective_triggers.insert(0, CounterTrigger(previous_counter_sid, 1))
        events.append(
            MechanicalEventSpec(
                event_id=f"{scenario_id}_objective_event_{index:02d}",
                triggers=tuple(objective_triggers),
                actions=tuple(actions),
                title=f"Objective {index + 1}",
                objective_label=f"Complete objective {index + 1}",
            )
        )

    if policy.squad_defeat_events_enabled:
        for index, placement in enumerate(encounters):
            actions = ()
            if policy.resource_rewards_enabled:
                actions = (
                    ResourceAction(
                        "gold",
                        round(
                            (250 + placement.risk_tier * 200)
                            * profile.economy.reward_multiplier
                        ),
                    ),
                )
            if not actions:
                continue
            events.append(
                MechanicalEventSpec(
                    event_id=f"{scenario_id}_encounter_event_{index:03d}",
                    triggers=(SquadDefeatTrigger(placement.placement_id),),
                    actions=actions,
                    title="Encounter cleared",
                )
            )

    if (
        profile.archetype is not Archetype.CONQUEST
        and policy.capture_events_enabled
        and ai_settlements
    ):
        for index, placement in enumerate(ai_settlements):
            actions: tuple[object, ...] = ()
            if policy.resource_rewards_enabled:
                actions = (
                    ResourceAction(
                        "gold",
                        round(
                            (750 + placement.risk_tier * 250)
                            * profile.economy.reward_multiplier
                        ),
                    ),
                )
            if actions:
                events.append(
                    MechanicalEventSpec(
                        event_id=f"{scenario_id}_capture_event_{index:02d}",
                        triggers=(CaptureTrigger(placement.placement_id),),
                        actions=actions,
                        title=f"Stronghold {index + 1} captured",
                    )
                )

    if profile.archetype is Archetype.CONQUEST:
        victory_placements = tuple(
            placement
            for placement in ai_settlements
            if placement.zone_id == victory_zone_id
        )
        if len(victory_placements) != 1:
            raise GenerationFailure(
                "events",
                (
                    ConstraintViolation(
                        "conquest_victory_target_missing",
                        "events",
                        "conquest requires exactly one AI settlement in the victory zone",
                    ),
                ),
                seed=profile.seed,
            )
        for index, placement in enumerate(ai_settlements):
            if placement is victory_placements[0]:
                actions = (VictoryAction(f"{scenario_id}_victory"),)
                title = "Final stronghold captured"
            else:
                actions = (
                    ObjectiveProgressAction(
                        f"{scenario_id}_capture_objective_{index:02d}"
                    ),
                )
                title = f"Stronghold {index + 1} captured"
            events.append(
                MechanicalEventSpec(
                    event_id=f"{scenario_id}_capture_event_{index:02d}",
                    triggers=(CaptureTrigger(placement.placement_id),),
                    actions=actions,
                    title=title,
                    objective_label=title,
                )
            )
    else:
        if not objectives:
            raise GenerationFailure(
                "events",
                (
                    ConstraintViolation(
                        "victory_objectives_missing",
                        "events",
                        "exploration and objective-chain scenarios require objectives",
                    ),
                ),
                seed=profile.seed,
            )
        events.append(
            MechanicalEventSpec(
                event_id=f"{scenario_id}_victory_event",
                triggers=(CounterTrigger(objective_counter, len(objectives)),),
                actions=(VictoryAction(f"{scenario_id}_victory"),),
                title="Scenario complete",
                objective_label="Complete all objectives",
            )
        )
    return tuple(events), tuple(sorted(declared_counters))


def _metrics(
    profile: ScenarioProfileV1,
    zones: Iterable[object],
    layout: object,
    placements: tuple[Placement, ...],
) -> ScenarioMetrics:
    area = profile.map_size * profile.map_size
    gameplay_count = sum(
        item.kind is not PlacementKind.SCENERY for item in placements
    )
    scenery_count = len(placements) - gameplay_count
    distances = decision_distances(layout)
    return ScenarioMetrics(
        zone_count=len(tuple(zones)),
        route_cell_count=len(layout.route_cells),
        gameplay_placement_count=gameplay_count,
        scenery_placement_count=scenery_count,
        gameplay_density_per_100_tiles=round(gameplay_count * 100.0 / area, 6),
        scenery_density_per_100_tiles=round(scenery_count * 100.0 / area, 6),
        decision_spacing_min=min(distances),
        decision_spacing_max=max(distances),
        decision_spacing_mean=round(sum(distances) / len(distances), 6),
        high_risk_zone_count=sum(
            getattr(zone, "role", None).value == "high_risk" for zone in zones
        ),
    )


def _scenario_id(profile: ScenarioProfileV1) -> str:
    archetype = profile.archetype.value
    return f"{profile.scenario_id_prefix}_{archetype}_{profile.seed}_{profile.fingerprint[:8]}"


def _require_hash(label: str, value: object) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Fa-f0-9]{64}", value):
        raise ValueError(f"{label} must be a 64-character SHA-256 hex digest")
    return value.lower()
