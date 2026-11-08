#!/usr/bin/env python3
"""Mine QuestScript / propActions vocabulary from shipped Golden Era .map files."""

from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import port_homecoming_poc as poc

SCHEMA = "homm3.olden_quest_script_vocabulary.v1"
DEFAULT_ARTIFACT = poc.ROOT / "artifacts" / "olden_quest_script_vocabulary" / "olden_quest_script_vocabulary.v1.json"


@dataclass(frozen=True)
class MapScanRoots:
    story_maps_dir: Path
    skirmish_maps_dir: Path

    @classmethod
    def golden_era_default(cls) -> MapScanRoots:
        maps_dir = poc.OLDEN_MAPS_DIR
        return cls(
            story_maps_dir=maps_dir / "Story_maps",
            skirmish_maps_dir=maps_dir,
        )


PORT_MAP_NAME_PREFIXES = ("h3_roe_castle_",)


def is_port_generated_map(path: Path) -> bool:
    return any(path.name.startswith(prefix) for prefix in PORT_MAP_NAME_PREFIXES)


def iter_map_paths(roots: MapScanRoots) -> list[Path]:
    # StoryHub campaign ports install under Story_maps/ (native StartInfo path) but must
    # not pollute the vanilla story vocabulary / CounterEquals contract.
    story_paths = sorted(
        path
        for path in (roots.story_maps_dir.glob("*.map") if roots.story_maps_dir.is_dir() else [])
        if not is_port_generated_map(path)
    )
    skirmish_paths = sorted(
        path
        for path in roots.skirmish_maps_dir.glob("*.map")
        if path.parent.name != "Story_maps" and not is_port_generated_map(path)
    )
    return story_paths + skirmish_paths


def iter_quest_triggers(chunk3: dict[str, Any]) -> Iterable[dict[str, Any]]:
    for quest in chunk3.get("quests") or []:
        if not isinstance(quest, dict):
            continue
        stacks: list[Any] = list(quest.get("subQuests") or [])
        for group in quest.get("subQuestGroups") or []:
            if isinstance(group, dict):
                stacks.extend(group.get("subQuests") or [])
        for sub in stacks:
            if not isinstance(sub, dict):
                continue
            for trigger in sub.get("triggers") or []:
                if isinstance(trigger, dict):
                    yield trigger


def mine_map_container(path: Path, container: poc.OldenMapContainer) -> dict[str, Any]:
    if len(container.chunks) < 4 or not isinstance(container.chunks[3], dict):
        raise ValueError(f"map has no QuestScript chunk: {path}")
    chunk3 = container.chunks[3]
    map_data = container.chunks[1] if len(container.chunks) > 1 else {}
    props = map_data.get("objectsProperties") if isinstance(map_data, dict) else {}
    props = props if isinstance(props, dict) else {}

    conditions: Counter[str] = Counter()
    actions: Counter[str] = Counter()
    condition_shapes: Counter[str] = Counter()
    action_shapes: Counter[str] = Counter()
    counter_operators: Counter[str] = Counter()
    prop_action_rows = 0
    prop_action_nonempty = 0
    prop_action_inner_actions: Counter[str] = Counter()

    for trigger in iter_quest_triggers(chunk3 if isinstance(chunk3, dict) else {}):
        for cond in trigger.get("conditions") or []:
            if not isinstance(cond, dict):
                continue
            name = str(cond.get("c") or "?")
            conditions[name] += 1
            params = cond.get("p") or []
            if isinstance(params, list):
                condition_shapes[f"{name}:{len(params)}"] += 1
                if name == "Counter" and len(params) >= 3:
                    counter_operators[str(params[1])] += 1
        for act in trigger.get("actions") or []:
            if not isinstance(act, dict):
                continue
            name = str(act.get("a") or "?")
            actions[name] += 1
            params = act.get("p") or []
            if isinstance(params, list):
                action_shapes[f"{name}:{len(params)}"] += 1

    for family in ("propActionsBefore", "propActionsAfter"):
        for row in props.get(family) or []:
            if not isinstance(row, dict):
                continue
            prop_action_rows += 1
            inner = row.get("actions") or []
            if inner:
                prop_action_nonempty += 1
                for item in inner:
                    if isinstance(item, dict):
                        prop_action_inner_actions[str(item.get("a") or "?")] += 1

    return {
        "map": str(path),
        "mapName": path.name,
        "source": "story" if path.parent.name == "Story_maps" else "skirmish",
        "conditionHistogram": dict(conditions),
        "actionHistogram": dict(actions),
        "conditionShapeHistogram": dict(condition_shapes),
        "actionShapeHistogram": dict(action_shapes),
        "counterOperatorHistogram": dict(counter_operators),
        "propActionRows": prop_action_rows,
        "propActionNonemptyRows": prop_action_nonempty,
        "propActionInnerActionHistogram": dict(prop_action_inner_actions),
    }


def mine_vocabulary(*, roots: MapScanRoots | None = None) -> dict[str, Any]:
    scan_roots = roots or MapScanRoots.golden_era_default()
    per_map: list[dict[str, Any]] = []
    aggregate_conditions: Counter[str] = Counter()
    aggregate_actions: Counter[str] = Counter()
    story_conditions: Counter[str] = Counter()
    story_actions: Counter[str] = Counter()
    aggregate_condition_shapes: Counter[str] = Counter()
    aggregate_action_shapes: Counter[str] = Counter()
    aggregate_counter_ops: Counter[str] = Counter()
    aggregate_prop_inner: Counter[str] = Counter()
    examples: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for path in iter_map_paths(scan_roots):
        try:
            container = poc.read_olden_map_container(path)
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError, OSError) as exc:
            # Vocabulary mining must not brick plugin builds when a Story_maps
            # payload is truncated/corrupt; map-load preflight owns that gate.
            print(
                f"olden_quest_script_vocabulary: skip unreadable map {path.name}: {exc}",
                file=sys.stderr,
            )
            continue
        if len(container.chunks) < 4 or not isinstance(container.chunks[3], dict):
            continue
        row = mine_map_container(path, container)
        per_map.append(row)
        aggregate_conditions.update(row["conditionHistogram"])
        aggregate_actions.update(row["actionHistogram"])
        if row["source"] == "story":
            story_conditions.update(row["conditionHistogram"])
            story_actions.update(row["actionHistogram"])
        aggregate_condition_shapes.update(row["conditionShapeHistogram"])
        aggregate_action_shapes.update(row["actionShapeHistogram"])
        aggregate_counter_ops.update(row["counterOperatorHistogram"])
        aggregate_prop_inner.update(row["propActionInnerActionHistogram"])

        for trigger in iter_quest_triggers(container.chunks[3]):
            for cond in trigger.get("conditions") or []:
                if not isinstance(cond, dict):
                    continue
                name = str(cond.get("c") or "?")
                if len(examples[name]) < 3:
                    examples[name].append(
                        {
                            "map": path.name,
                            "condition": cond,
                            "triggerComment": trigger.get("comment"),
                            "actions": (trigger.get("actions") or [])[:4],
                        }
                    )

    return {
        "schema": SCHEMA,
        "status": "generated_artifact_validated_runtime_unvalidated",
        "scanRoots": {
            "storyMapsDir": str(scan_roots.story_maps_dir),
            "skirmishMapsDir": str(scan_roots.skirmish_maps_dir),
        },
        "mapCount": len(per_map),
        "storyMapCount": sum(1 for row in per_map if row["source"] == "story"),
        "skirmishMapCount": sum(1 for row in per_map if row["source"] == "skirmish"),
        "conditionHistogram": dict(aggregate_conditions.most_common()),
        "actionHistogram": dict(aggregate_actions.most_common()),
        "storyConditionHistogram": dict(story_conditions.most_common()),
        "storyActionHistogram": dict(story_actions.most_common()),
        "conditionShapeHistogram": dict(aggregate_condition_shapes.most_common()),
        "actionShapeHistogram": dict(aggregate_action_shapes.most_common()),
        "counterOperatorHistogram": dict(aggregate_counter_ops.most_common()),
        "propActionInnerActionHistogram": dict(aggregate_prop_inner.most_common()),
        "portingNotes": {
            "canonicalCounterCondition": {
                "c": "Counter",
                "p": ["counter_sid", "=", "value"],
                "counter": 1,
            },
            "counterEqualsObservedInVanillaMaps": story_conditions.get("CounterEquals", 0),
            "counterEqualsObservedInPortMapsExcludedFromVanillaBaseline": True,
            "visitMapEventCondition": "ObjectInteractionAfter",
            "visitMapEventConditionCount": aggregate_conditions.get("ObjectInteractionAfter", 0),
            "preVisitCondition": "ObjectInteractionBefore",
            "timedDayCondition": "CounterEqualityInDays",
        },
        "examples": {key: value for key, value in sorted(examples.items())},
        "perMap": per_map,
    }


def write_vocabulary_artifact(path: Path, payload: dict[str, Any] | None = None, *, roots: MapScanRoots | None = None) -> Path:
    doc = payload or mine_vocabulary(roots=roots)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path
