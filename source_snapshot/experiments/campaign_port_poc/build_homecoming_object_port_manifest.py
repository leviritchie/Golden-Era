#!/usr/bin/env python3
"""Build a Homecoming object portability manifest from the validated object walk.

The manifest does not emit an Olden map. It classifies decoded H3M records into
explicit port buckets so the next playable-map pass has a concrete worklist.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import h3m_object_registry as h3obj
import port_homecoming_poc as poc

OUT_ROOT = poc.OUT_ROOT / "layered_ir"
IR_PATH = OUT_ROOT / "homecoming.layered_map_ir.json"
WALK_PATH = OUT_ROOT / "homecoming.object_walk.json"
MANIFEST_PATH = OUT_ROOT / "homecoming.object_port_manifest.json"
VALIDATION_PATH = OUT_ROOT / "object_port_manifest_validation_report.json"
REPORT_PATH = OUT_ROOT / "OBJECT_PORT_MANIFEST_REPORT.md"

TOWN_ID = 98
EVENT_ID = 26
SIGN_ID = 91
CAVE_ID = h3obj.OBJECT_SUBTERRANEAN_GATE
WHIRLPOOL_ID = h3obj.OBJECT_WHIRLPOOL
BOAT_ID = 8
HERO_ID = 34
PRISON_ID = 62
MONSTER_IDS = h3obj.MONSTER_OBJECT_IDS
CREATURE_GENERATOR_IDS = h3obj.FIXED_CREATURE_GENERATOR_IDS
ARTIFACT_IDS = h3obj.ARTIFACT_OBJECT_IDS
RESOURCE_IDS = {76, 79}
MINE_IDS = {42, 53}
SCHOLAR_ID = 81
WITCH_HUT_ID = 113
SEER_HUT_ID = h3obj.OBJECT_SEER_HUT
GARRISON_IDS = {h3obj.OBJECT_GARRISON, h3obj.OBJECT_GARRISON2}
QUEST_GUARD_ID = h3obj.OBJECT_QUEST_GUARD
SHRINE_IDS = {
    h3obj.OBJECT_SHRINE_INCANTATION,
    h3obj.OBJECT_SHRINE_GESTURE,
    h3obj.OBJECT_SHRINE_THOUGHT,
}
RANDOM_HERO_ID = h3obj.OBJECT_RANDOM_HERO
RANDOM_DWELLING_IDS = h3obj.RANDOM_DWELLING_IDS

PAYLOAD_KIND_PORT_BUCKETS: dict[str, dict[str, Any]] = {
    "seer_hut": {
        "category": "interactive_quest_object",
        "triggerPort": "portable_to_seer_hut_questscript",
        "oldenRequirement": "homm3_seer_hut ObjectConfig + SeerQuest FSM (missions 3-7)",
    },
    "garrison": {
        "category": "garrison",
        "triggerPort": "combat_interaction_not_ported_in_map_trigger_slice",
        "oldenRequirement": "garrison object SID mapping",
        "ignoredByCurrentScope": True,
    },
    "quest_guard": {
        "category": "interactive_quest_object",
        "triggerPort": "quest_interaction_not_ported_in_map_trigger_slice",
        "oldenRequirement": "quest-guard object SID mapping",
        "blockingReason": "quest-guard chains are outside the current map-geometry/event-trigger scope",
    },
    "border_gate": {
        "category": "interactive_quest_object",
        "triggerPort": "border_gate_keymaster_or_quest_not_ported_in_map_trigger_slice",
        "oldenRequirement": "border-gate object SID mapping (classic keymaster subtypes 0-7 or quest)",
        "blockingReason": "border-gate unlock/quest chains are outside the current map-geometry/event-trigger scope",
    },
    "random_dwelling": {
        "category": "external_dwelling",
        "triggerPort": "recruitment_interaction_portable_via_native_homm3_barracks_mapping",
        "oldenRequirement": "random dwelling must resolve to a native HoMM3 barracks SID at map-build time",
    },
    "random_hero": {
        "category": "hero_or_prison",
        "triggerPort": "hero/prison mechanics ignored_current_scope",
        "oldenRequirement": "random hero placeholder must resolve before emission",
    },
    "hero_placeholder": {
        "category": "hero_or_prison",
        "triggerPort": "hero/prison mechanics ignored_current_scope",
        "oldenRequirement": "hero placeholder must resolve before emission",
    },
    "shrine": {
        "category": "interactive_reward_object",
        "triggerPort": "reward_interaction_not_ported_in_map_trigger_slice",
        "oldenRequirement": "shrine object SID mapping",
        "blockingReason": "shrine rewards are outside the current map-geometry/event-trigger scope",
    },
    "pandoras_box": {
        "category": "interactive_reward_object",
        "triggerPort": "reward_interaction_not_ported_in_map_trigger_slice",
        "oldenRequirement": "pandora's box object SID mapping",
        "blockingReason": "pandora rewards are outside the current map-geometry/event-trigger scope",
    },
    "spell_scroll": {
        "category": "artifact_pickup",
        "triggerPort": "pickup_interaction_not_ported_in_map_trigger_slice",
        "oldenRequirement": "spell-scroll object SID mapping",
    },
    "grail": {
        "category": "interactive_reward_object",
        "triggerPort": "victory_condition_not_ported_in_map_trigger_slice",
        "oldenRequirement": "grail object SID mapping and win-condition wiring",
        "blockingReason": "grail victory wiring is outside the current map-geometry slice",
    },
    "abandoned_mine": {
        "category": "mine",
        "triggerPort": "ownership/economy mechanics ignored_current_scope",
        "oldenRequirement": "emit as mine_gold (HoMM3 abandoned mine → capturable gold mine)",
    },
    "ocean_bottle": {
        "category": "readable_sign_or_bottle",
        "triggerPort": "interaction_text_portable_if_readable_object_mapping_exists",
        "oldenRequirement": "ocean-bottle readable object SID mapping",
    },
    "shipyard": {
        "category": "interactive_utility_object",
        "triggerPort": "boat_purchase_interaction_not_ported_in_map_trigger_slice",
        "oldenRequirement": "shipyard object SID mapping",
        "blockingReason": "shipyard boat purchase is outside the current map-geometry/event-trigger scope",
        "ignoredByCurrentScope": True,
    },
    "lighthouse": {
        "category": "interactive_utility_object",
        "triggerPort": "ownership_interaction_not_ported_in_map_trigger_slice",
        "oldenRequirement": "lighthouse object SID mapping",
        "ignoredByCurrentScope": True,
    },
    "witch_hut": {
        "category": "interactive_reward_object",
        "triggerPort": "reward_interaction_not_ported_in_map_trigger_slice",
        "oldenRequirement": "witch-hut object SID mapping",
        "ignoredByCurrentScope": True,
    },
    "scholar": {
        "category": "interactive_reward_object",
        "triggerPort": "reward_interaction_not_ported_in_map_trigger_slice",
        "oldenRequirement": "scholar object SID mapping",
        "ignoredByCurrentScope": True,
    },
    "sign": {
        "category": "readable_sign_or_bottle",
        "triggerPort": "interaction_text_portable_if_readable_object_mapping_exists",
        "oldenRequirement": "sign readable object SID mapping",
    },
}


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def load_inputs() -> tuple[dict[str, Any], dict[str, Any]]:
    if not IR_PATH.exists():
        raise FileNotFoundError(f"missing layered IR: {IR_PATH}")
    if not WALK_PATH.exists():
        raise FileNotFoundError(f"missing object walk: {WALK_PATH}")
    ir = json.loads(IR_PATH.read_text(encoding="utf-8"))
    walk = json.loads(WALK_PATH.read_text(encoding="utf-8"))
    walk_validation = walk.get("validation") or {}
    if walk_validation.get("result") != "PASS":
        raise ValueError(f"object walk must pass before portability classification: {walk_validation}")
    table = walk.get("objectTable") or {}
    if not table.get("complete"):
        raise ValueError("object walk is incomplete; refusing to classify partial object table")
    declared = table.get("declaredCount")
    decoded = table.get("decodedCount")
    if declared != decoded:
        # Some RoE maps declare trailing slots that are actually the global timed-event
        # table (Steadwick). Allow only when the walker explicitly stopped at events.
        if not table.get("stoppedAtPostObjectGlobalTimedEvents"):
            raise ValueError(
                "object walk decodedCount != declaredCount without stoppedAtPostObjectGlobalTimedEvents; "
                "refusing to classify partial object table"
            )
        if int(table.get("declaredDecodedDelta") or 0) != int(declared) - int(decoded):
            raise ValueError("object walk declaredDecodedDelta does not match declared-decoded delta")
    return ir, walk


def classify_record(record: dict[str, Any]) -> dict[str, Any]:
    oid = record["templateObjectId"]
    base = {
        "sourceIndex": record["index"],
        "sourceKey": record["key"],
        "recordOffset": record["recordOffset"],
        "templateAnimation": record["templateAnimation"],
        "templateBlockMask": record.get("templateBlockMask"),
        "templateVisitMask": record.get("templateVisitMask"),
        "templateObjectId": oid,
        "payloadKind": record.get("payloadKind"),
    }
    for key in [
        "templateSubtype",
        "identifier",
        "count",
        "character",
        "hasMessage",
        "message",
        "artifact",
        "guardResources",
        "neverFlees",
        "notGrowingTeam",
        "owner",
        "ownerEncoding",
        "generatorFamily",
        "payloadDecoderEvidence",
        "heroType",
        "name",
        "experience",
        "hasName",
        "hasGarrison",
        "hasArtifactSet",
        "secondarySkills",
        "secondarySkillCount",
        "garrisonStacks",
        "formation",
        "equippedArtifacts",
        "backpackArtifacts",
        "backpackArtifactCount",
        "patrolRadius",
        "hasCustomBuildings",
        "builtBuildingsMask",
        "forbiddenBuildingsMask",
        "hasFort",
        "obligatorySpells",
        "availableSpells",
        "townEventCount",
        "townEvents",
        "alignment",
        "amount",
        "isRandomResource",
        "messageAndGuards",
        "playersMask",
        "computerActivate",
        "removeAfterVisit",
        "boxContent",
    ]:
        if key in record:
            base[key] = record[key]
    if oid == TOWN_ID:
        name = record.get("name")
        base.update({
            "name": name,
            "category": "town",
            "geometryPort": "coordinate_portable",
            "oldenRequirement": "town entity/object SID mapping",
            "townState": {
                "owner": record.get("owner"),
                "hasGarrison": record.get("hasGarrison"),
                "garrisonStacks": record.get("garrisonStacks"),
                "formation": record.get("formation"),
                "hasCustomBuildings": record.get("hasCustomBuildings"),
                "builtBuildingsMask": record.get("builtBuildingsMask"),
                "forbiddenBuildingsMask": record.get("forbiddenBuildingsMask"),
                "hasFort": record.get("hasFort"),
                "obligatorySpells": record.get("obligatorySpells"),
                "availableSpells": record.get("availableSpells"),
                "townEventCount": record.get("townEventCount"),
                "townEvents": record.get("townEvents"),
                "alignment": record.get("alignment"),
            },
        })
        if name == "Terraneus":
            base.update({
                "triggerRole": "primary_victory_capture_target",
                "triggerPort": "portable_to_ObjectCaptureEntity_if_entity_is_emitted",
                "blockingReason": "faithful placement still requires layer-aware map runtime because Terraneus is underground",
            })
        else:
            base.update({"triggerRole": "none_decoded", "triggerPort": "not_required_for_primary_objective"})
        return base
    if oid == EVENT_ID:
        box_content = record.get("boxContent") or {}
        message_and_guards = box_content.get("messageAndGuards") or {}
        message = message_and_guards.get("message")
        base.update({
            "category": "map_event",
            "geometryPort": "coordinate_portable",
            "message": message,
            "triggerFields": {
                "playersMask": record.get("playersMask"),
                "computerActivate": record.get("computerActivate"),
                "humanActivate": record.get("humanActivate", True),
                "removeAfterVisit": record.get("removeAfterVisit"),
                "hasMessage": message_and_guards.get("hasMessage"),
                "hasGuards": message_and_guards.get("hasGuards"),
                "guardStacks": message_and_guards.get("guardStacks"),
                "rewardCounts": box_content.get("rewardCounts"),
                "rewards": box_content.get("rewards"),
            },
            "triggerPort": "text_players_mask_computer_activation_and_remove_after_visit_portable_if_event_tile_object_or_custom_trigger_exists",
            "oldenRequirement": "event tile object SID or custom layer-aware trigger component",
        })
        return base
    if oid == SIGN_ID:
        base.update({
            "category": "readable_sign_or_bottle",
            "geometryPort": "coordinate_portable",
            "message": record.get("message"),
            "triggerPort": "interaction_text_portable_if_readable_object_mapping_exists",
            "oldenRequirement": "readable adventure object SID mapping",
        })
        return base
    if oid in (CAVE_ID, WHIRLPOOL_ID):
        base.update({
            "category": "travel_link_candidate",
            "geometryPort": "coordinate_portable",
            "triggerPort": "blocked_for_faithful_map",
            "blockingReason": "requires layer-aware travel graph and destination pairing; native Olden multi-layer map loading is missing",
        })
        return base
    if oid == BOAT_ID:
        base.update({
            "category": "boat_or_water_travel_object",
            "geometryPort": "coordinate_portable",
            "triggerPort": "not_a_script_trigger",
            "blockingReason": "Olden water/boat travel object mapping not validated in this pass",
        })
        return base
    if oid in MONSTER_IDS:
        base.update({
            "category": "monster_stack",
            "geometryPort": "coordinate_portable",
            "triggerPort": "combat_interaction_not_ported_in_map_trigger_slice",
            "ignoredByCurrentScope": True,
        })
        return base
    if oid in CREATURE_GENERATOR_IDS:
        base.update({
            "category": "external_dwelling",
            "geometryPort": "coordinate_portable",
            "triggerPort": "recruitment_interaction_portable_via_native_homm3_barracks_mapping",
            "oldenRequirement": "exact native HoMM3 barracks SID mapping",
        })
        return base
    if oid in ARTIFACT_IDS:
        base.update({
            "category": "artifact_pickup",
            "geometryPort": "coordinate_portable",
            "triggerPort": "pickup_interaction_not_ported_in_map_trigger_slice",
            "oldenRequirement": "artifact object SID mapping",
        })
        return base
    if oid in RESOURCE_IDS:
        base.update({
            "category": "resource_pickup",
            "geometryPort": "coordinate_portable",
            "triggerPort": "pickup_interaction_not_ported_in_map_trigger_slice",
            "oldenRequirement": "resource object SID mapping",
        })
        return base
    if oid in MINE_IDS:
        base.update({
            "category": "mine", "geometryPort": "coordinate_portable", "triggerPort": "ownership/economy mechanics ignored_current_scope", "oldenRequirement": "mine object SID mapping"
        })
        return base
    if oid == SCHOLAR_ID:
        base.update({
            "category": "interactive_reward_object",
            "geometryPort": "coordinate_portable",
            "triggerPort": "reward_interaction_not_ported_in_map_trigger_slice",
            "oldenRequirement": "scholar/reward object SID mapping",
            "rewardTypeRaw": record.get("bonusTypeRaw"),
            "rewardId": record.get("bonusId"),
            "blockingReason": "scholar rewards are outside the current map-geometry/event-trigger scope",
        })
        return base

    if oid in (HERO_ID, PRISON_ID):
        base.update({
            "category": "hero_or_prison", "geometryPort": "coordinate_portable", "triggerPort": "hero/prison mechanics ignored_current_scope", "oldenRequirement": "hero/prison object SID mapping"
        })
        return base
    if oid == WITCH_HUT_ID:
        base.update({
            "category": "interactive_reward_object",
            "geometryPort": "coordinate_portable",
            "triggerPort": "reward_interaction_not_ported_in_map_trigger_slice",
            "oldenRequirement": "witch-hut/reward object SID mapping",
            "allowedSkillsCount": len(record.get("allowedSkills") or []),
            "blockingReason": "witch-hut rewards are outside the current map-geometry/event-trigger scope",
        })
        return base
    if oid == SEER_HUT_ID:
        base.update({
            "category": "interactive_quest_object",
            "geometryPort": "coordinate_portable",
            "triggerPort": "portable_to_seer_hut_questscript",
            "oldenRequirement": "homm3_seer_hut ObjectConfig + SeerQuest FSM (missions 3-7)",
            "quest": record.get("quest"),
            "quests": record.get("quests"),
            "repeatableQuests": record.get("repeatableQuests"),
            "payloadKind": "seer_hut",
        })
        return base
    if oid in GARRISON_IDS:
        base.update({
            "category": "garrison",
            "geometryPort": "coordinate_portable",
            "triggerPort": "combat_interaction_not_ported_in_map_trigger_slice",
            "oldenRequirement": "garrison object SID mapping",
            "ignoredByCurrentScope": True,
        })
        return base
    if oid == QUEST_GUARD_ID:
        base.update({
            "category": "interactive_quest_object",
            "geometryPort": "coordinate_portable",
            "triggerPort": "quest_interaction_not_ported_in_map_trigger_slice",
            "oldenRequirement": "quest-guard object SID mapping",
            "quest": record.get("quest"),
            "blockingReason": "quest-guard chains are outside the current map-geometry/event-trigger scope",
        })
        return base
    if oid == h3obj.OBJECT_BORDER_GATE:
        base.update({
            "category": "interactive_quest_object",
            "geometryPort": "coordinate_portable",
            "triggerPort": "border_gate_keymaster_or_quest_not_ported_in_map_trigger_slice",
            "oldenRequirement": "border-gate object SID mapping (classic keymaster subtypes 0-7 or quest)",
            "quest": record.get("quest"),
            "classicKeymasterStyle": record.get("classicKeymasterStyle"),
            "templateSubtype": record.get("templateSubtype"),
            "blockingReason": "border-gate unlock/quest chains are outside the current map-geometry/event-trigger scope",
        })
        return base
    if oid in SHRINE_IDS:
        base.update({
            "category": "interactive_reward_object",
            "geometryPort": "coordinate_portable",
            "triggerPort": "reward_interaction_not_ported_in_map_trigger_slice",
            "oldenRequirement": "shrine object SID mapping",
            "spellId": record.get("spellId"),
            "blockingReason": "shrine rewards are outside the current map-geometry/event-trigger scope",
        })
        return base
    if oid == RANDOM_HERO_ID:
        base.update({
            "category": "hero_or_prison",
            "geometryPort": "coordinate_portable",
            "triggerPort": "hero/prison mechanics ignored_current_scope",
            "oldenRequirement": "random hero placeholder must resolve before emission",
        })
        return base
    if oid in RANDOM_DWELLING_IDS:
        base.update({
            "category": "external_dwelling",
            "geometryPort": "coordinate_portable",
            "triggerPort": "recruitment_interaction_portable_via_native_homm3_barracks_mapping",
            "oldenRequirement": "random dwelling must resolve to a native HoMM3 barracks SID at map-build time",
        })
        return base
    if oid == h3obj.OBJECT_ROE_CAMPAIGN_BRIEFING or record.get("syntheticHeader"):
        payload_kind = record.get("payloadKind")
        if payload_kind in {
            "roe_campaign_briefing",
            "roe_campaign_briefing_gap",
            "roe_campaign_briefing_zero_block",
        }:
            base.update({
                "category": "campaign_briefing_script",
                "geometryPort": "not_placed_on_map",
                "emitToMap": False,
                "triggerPort": "portable_to_runtime_quest_triggers",
                "lastDay": record.get("lastDay"),
                "firstVisitText": record.get("firstVisitText"),
                "nextVisitText": record.get("nextVisitText"),
                "completedText": record.get("completedText"),
                "rewardType": record.get("rewardType"),
                "gapBytes": record.get("gapBytes"),
                "zeroBlockBytes": record.get("zeroBlockBytes"),
            })
            return base

    payload_kind = record.get("payloadKind")
    payload_bucket = PAYLOAD_KIND_PORT_BUCKETS.get(payload_kind) if isinstance(payload_kind, str) else None
    if payload_bucket is not None:
        base.update({"geometryPort": "coordinate_portable", **payload_bucket})
        return base

    if record.get("payloadKind") == "explicit_no_payload":
        base.update({
            "category": "payloadless_object_unclassified_for_current_scope",
            "geometryPort": "coordinate_portable",
            "triggerPort": "not_classified_in_current_map_event_slice",
            "ignoredByCurrentScope": True,
            "oldenRequirement": "explicit object-id policy before emission, interaction, or omission",
            "blockingReason": "the source walker proved only that this object id has no per-instance payload; it did not prove static/non-interactive behavior",
        })
        return base
    raise ValueError(f"unclassified object id {oid} at {record.get('recordOffset')}")


def validate_manifest(manifest: dict[str, Any], *, validation_profile: str = "homecoming") -> dict[str, Any]:
    errors: list[str] = []
    records = manifest["records"]
    source_count = manifest["sourceObjectCount"]
    if len(records) != source_count:
        errors.append(f"record list length {len(records)} does not match sourceObjectCount {source_count}")
    category_total = sum(manifest.get("categoryCounts", {}).values())
    if category_total != len(records):
        errors.append(f"categoryCounts total {category_total} does not match record list length {len(records)}")
    source_indices = [item["sourceIndex"] for item in records]
    by_index = set(source_indices)
    if len(by_index) != source_count:
        errors.append("manifest does not classify every decoded source object exactly once")
    expected_indices = set(range(source_count))
    if by_index != expected_indices:
        missing = sorted(expected_indices - by_index)[:10]
        extra = sorted(by_index - expected_indices)[:10]
        errors.append(f"source index coverage mismatch; missing={missing} extra={extra}")
    if any(item.get("category") == "static_or_native_generic_object" for item in records):
        errors.append("static_or_native_generic_object is forbidden; payloadless objects are not proven static")
    terraneus: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    if validation_profile == "homecoming":
        terraneus = [item for item in records if item.get("name") == "Terraneus"]
        if len(terraneus) != 1:
            errors.append(f"expected exactly one Terraneus classification, found {len(terraneus)}")
        else:
            target = terraneus[0]
            if target.get("triggerPort") != "portable_to_ObjectCaptureEntity_if_entity_is_emitted":
                errors.append("Terraneus capture trigger portability classification is missing")
            if target.get("sourceKey") != "1:35:35" or target.get("templateObjectId") != TOWN_ID or target.get("category") != "town":
                errors.append("Terraneus classification does not match the decoded underground town object")
        events = [item for item in records if item.get("category") == "map_event"]
        if len(events) != 1:
            errors.append(f"expected exactly one decoded map event, found {len(events)}")
        else:
            event = events[0]
            fields = event.get("triggerFields") or {}
            if event.get("sourceKey") != "0:18:35" or event.get("templateObjectId") != EVENT_ID:
                errors.append("map event classification does not match the decoded Guardhouse event object")
            for required_key in ("playersMask", "computerActivate", "removeAfterVisit", "hasMessage", "hasGuards", "rewardCounts"):
                if required_key not in fields:
                    errors.append(f"map event triggerFields missing {required_key}")
            if fields.get("playersMask") != 255 or fields.get("computerActivate") is not True or fields.get("removeAfterVisit") is not True:
                errors.append("map event trigger activation fields do not match decoded H3M payload")
            reward_counts = fields.get("rewardCounts") or {}
            for reward_key in ("skills", "artifacts", "spells", "creatures"):
                if reward_counts.get(reward_key) != 0:
                    errors.append(f"map event rewardCounts.{reward_key} expected 0, found {reward_counts.get(reward_key)}")
        expected_creature_generators = {
            "0:18:34": ("AVGpike0.def", 56),
            "0:65:48": ("AVGpike0.def", 56),
            "0:15:45": ("AVGcros0.def", 57),
            "0:59:31": ("AVGgrff0.def", 25),
            "0:19:26": ("AVGmonk0.def", 35),
            "0:45:25": ("AVGswor0.def", 58),
        }
        by_key = {item.get("sourceKey"): item for item in records}
        for source_key, expected in expected_creature_generators.items():
            item = by_key.get(source_key)
            if item is None:
                errors.append(f"creature generator missing from manifest: {source_key}")
                continue
            actual = (item.get("templateAnimation"), item.get("templateSubtype"))
            if actual != expected:
                errors.append(f"creature generator payload mismatch for {source_key}: {actual} != {expected}")
            if item.get("templateObjectId") != h3obj.OBJECT_CREATURE_GENERATOR_1 or item.get("payloadKind") != "creature_generator" or item.get("category") != "external_dwelling":
                errors.append(f"creature generator classification mismatch for {source_key}: id={item.get('templateObjectId')} payload={item.get('payloadKind')} category={item.get('category')}")
            if item.get("generatorFamily") != "creature_generator_1" or item.get("owner") != 255 or item.get("ownerEncoding") != "h3m_readPlayer32":
                errors.append(f"creature generator owner/family mismatch for {source_key}: family={item.get('generatorFamily')} owner={item.get('owner')} ownerEncoding={item.get('ownerEncoding')}")
        expected_start_stacks = {
            "0:64:58": ("AvWLCrs.def", 2, 0, True),
            "0:63:57": ("AvWLCrs.def", 2, 0, True),
            "0:66:57": ("AvWPike.def", 0, 0, True),
            "0:65:58": ("AvWPike.def", 0, 0, True),
        }
        for source_key, expected in expected_start_stacks.items():
            item = by_key.get(source_key)
            if item is None:
                errors.append(f"start recruitable stack missing from manifest: {source_key}")
                continue
            actual = (item.get("templateAnimation"), item.get("templateSubtype"), item.get("character"), item.get("neverFlees"))
            if actual != expected:
                errors.append(f"start recruitable stack payload mismatch for {source_key}: {actual} != {expected}")
    misclassified_creature_generators = [
        item for item in records
        if item.get("templateObjectId") in h3obj.FIXED_CREATURE_GENERATOR_IDS and (item.get("payloadKind") == "artifact" or item.get("category") == "artifact_pickup")
    ]
    if misclassified_creature_generators:
        errors.append(f"fixed creature generators must not be classified as artifact_pickup: {len(misclassified_creature_generators)} rows")
    random_hero_artifacts = [
        item for item in records
        if item.get("templateObjectId") == h3obj.OBJECT_RANDOM_HERO and (item.get("payloadKind") == "artifact" or item.get("category") == "artifact_pickup")
    ]
    if random_hero_artifacts:
        errors.append(f"random hero object id 70 must not be classified as artifact_pickup: {len(random_hero_artifacts)} rows")
    if manifest.get("silentFallbacksUsed") is not False:
        errors.append("silentFallbacksUsed must be false")
    return {
        "schema": "homm3.homecoming_object_port_manifest.validation.v0",
        "result": "PASS" if not errors else "FAIL",
        "errors": errors,
        "warnings": [],
        "checkedInvariants": {
            "classifiedRecords": len(records),
            "sourceObjectCount": source_count,
            "categoryCountTotal": category_total,
            "uniqueSourceIndices": len(by_index),
            "terraneusMatches": len(terraneus),
            "mapEvents": len(events),
            "monsterObjectIds": sorted(h3obj.MONSTER_OBJECT_IDS),
            "artifactObjectIds": sorted(h3obj.ARTIFACT_OBJECT_IDS),
            "fixedCreatureGeneratorIds": sorted(h3obj.FIXED_CREATURE_GENERATOR_IDS),
            "randomDwellingIdsKnownUnsupported": sorted(h3obj.RANDOM_DWELLING_IDS),
        },
    }


def write_report(manifest: dict[str, Any], validation: dict[str, Any]) -> None:
    counts = manifest["categoryCounts"]
    lines = [
        "# Homecoming Object Port Manifest",
        "",
        f"Validation: {validation['result']}",
        f"Classified source objects: {manifest['sourceObjectCount']}",
        "",
        "## Category Counts",
        "",
    ]
    for key in sorted(counts):
        lines.append(f"- `{key}`: {counts[key]}")
    lines.extend([
        "",
        "## Primary Trigger",
        "",
        "Terraneus capture is structurally portable to `ObjectCaptureEntity` only after an Olden entity is emitted for the underground town at `1:35:35`. Faithful placement remains blocked by missing layer-aware map runtime.",
        "",
        "## Map Event",
        "",
    ])
    for item in manifest["records"]:
        if item.get("category") == "map_event":
            fields = item.get("triggerFields") or {}
            rewards = fields.get("rewardCounts") or {}
            lines.append(f"- `{item['sourceKey']}`: {item.get('message')}")
            lines.append(f"  - playersMask={fields.get('playersMask')} computerActivate={fields.get('computerActivate')} removeAfterVisit={fields.get('removeAfterVisit')} hasGuards={fields.get('hasGuards')}")
            lines.append(f"  - rewardCounts: skills={rewards.get('skills')} artifacts={rewards.get('artifacts')} spells={rewards.get('spells')} creatures={rewards.get('creatures')}")
    lines.extend([
        "",
        "## Blocking Runtime Gap",
        "",
        "The manifest classifies source geometry, decoded event trigger fields, and unresolved object-policy work only. It does not emit an Olden `.map`; exact Homecoming layout still requires layer-aware map storage/rendering/travel plus explicit Olden object SID mappings.",
    ])
    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def update_ir(ir: dict[str, Any], manifest: dict[str, Any], validation: dict[str, Any]) -> None:
    ir["objectInstances"]["portManifest"] = {
        "artifact": str(MANIFEST_PATH),
        "validationResult": validation["result"],
        "classifiedRecords": manifest["sourceObjectCount"],
        "categoryCounts": manifest["categoryCounts"],
        "primaryBlockingFeature": "missing_layer_aware_olden_map_runtime",
    }
    write_json(IR_PATH, ir)


def main() -> int:
    ir, walk = load_inputs()
    records = [classify_record(record) for record in walk["records"]]
    counts = dict(sorted(Counter(item["category"] for item in records).items()))
    by_layer = defaultdict(int)
    for item in records:
        layer = int(str(item["sourceKey"]).split(":", 1)[0])
        by_layer[str(layer)] += 1
    manifest = {
        "schema": "homm3.homecoming_object_port_manifest.v0",
        "source": walk["source"],
        "sourceObjectCount": len(walk["records"]),
        "categoryCounts": counts,
        "layerCounts": dict(sorted(by_layer.items())),
        "records": records,
        "silentFallbacksUsed": False,
    }
    validation = validate_manifest(manifest)
    manifest["validation"] = validation
    write_json(MANIFEST_PATH, manifest)
    write_json(VALIDATION_PATH, validation)
    update_ir(ir, manifest, validation)
    write_report(manifest, validation)
    print(f"validation={validation['result']} classified={len(records)} categories={len(counts)}")
    return 0 if validation["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
