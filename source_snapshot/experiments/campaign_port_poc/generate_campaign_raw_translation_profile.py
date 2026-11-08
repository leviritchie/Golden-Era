#!/usr/bin/env python3
"""Generate raw_translation scenario profiles from the campaign batch manifest.

Defaults are centralized here. Per-mission `rawTranslation` blocks in the batch
manifest carry only true overrides (Homecoming spawn split, Griffin victory
targets, etc.); anything that merely restates a default belongs here instead.

`raw_translation` is the only campaign map generation lane. The `mapSid` in the
batch manifest is expected to be the shipped `*_raw_translation` SID.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import port_homecoming_poc as poc
from campaign_mission import (
    CampaignBatchManifest,
    CampaignMission,
    default_batch_manifest_path,
    load_batch_manifest,
    mission_by_id,
)
from campaign_hub_spawn import resolve_campaign_hub_spawn
from campaign_profile_derive import (
    expected_layer_entity_counts,
    infer_campaign_spawn_hero_sid,
    infer_start_hero_contract,
    layer_ids_from_h3c,
    map_sid_to_raw_translation,
    title_to_raw_translation,
    rel_repo,
)
from h3c_mission_source import load_h3c_block

PROFILE_SCHEMA = "homm3.olden_layered_atlas_scenario_profile.v1"
OUTPUT_SUBDIR = "raw_translation_map"

# Shared raw_translation defaults (not copied into every mission JSON by hand).
DEFAULT_PATHABILITY = {
    "surfaceGapFill": False,
    "emitCoreOverlay": True,
}
DEFAULT_CORE_OVERLAY = {"mode": "emit_fresh"}
DEFAULT_KNOWN_GAPS = (
    "Raw translation is the only campaign map generation lane; the StoryHub continuity "
    "installer ships this SID. Layered-atlas, approach-cell, zone-atlas and single-layer "
    "lanes are retired.",
    "emit_fresh core overlay for every mission; no lane inherits another lane's overlay.",
    "Emit-only: land-on GATE clones, HoMM3 block-mask solid-square mountain/tree sizing, "
    "and BR-to-Olden multi-tile node shift are the only placement transforms.",
    "Forbidden: block parity pads, accessibility repair, mountain merge, local "
    "approach-cell clears, spawn unbury, sign omit-as-policy, stray-water GATE clears, "
    "boat/decoration extras, functional emit scenery omit, exact-anchor scenery suppress, "
    "UG scenery suppress, footprint_alignment, functional_points.",
    "UG tunnel clearance ON when underground layers exist "
    "(chebyshev_two_tile_elevation_shoulder_rock_to_burrow_clearance): H3 rock projects as "
    "levelsMap=1 cliffs, so thin corridors would lose 2x2 clearance without the shoulder. "
    "Runtime UG traversal remains user-unvalidated.",
    "Gate-face mirror rotation ON for eligible single-GATE footprints.",
    "Pickup range fallback ON (pickup_gate_ring_nearby_range_fallback_v1).",
    "Occupied stacks and buried visits are intentional diagnostics of honest 1:1 "
    "translation; they are not fail-closed contract failures.",
    "Signs keep source placements when substitution emits them; no fx_quest_mark_* omit policy.",
    "Hero hire: HoMM3-authentic multi-hero (heroCountMin=1, heroCountMax=8). "
    "Per-mission H3M levelLimit drives enableCustomHeroMaxLevel/customHeroMaxLevel "
    "(0 = unlimited). Cities keep default_buildings_ban so tavern is not banned.",
    "Per-placement three-way ground truth is emitted as "
    "<missionId>.raw_translation_placement_ground_truth.json (HoMM3 object + substitution "
    "mapping + Olden sid/node/occupied).",
    "Underground HoMM3 ocean terrain is converted to walkable Burrow land with pond scenery "
    "(pool_dirt_small_1 / pool_dirt_big_1) unless terrain.preserveUndergroundOcean is set.",
    "Runtime clickability, pathing, and hole-free playtest remain user-unvalidated.",
)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def raw_profile_path_for_mission(mission: CampaignMission) -> Path:
    return poc.ROOT / "scenarios" / mission.scenario_id / "raw_translation.profile.json"


def _overrides(mission: CampaignMission) -> dict[str, Any]:
    raw = mission.raw_translation if isinstance(mission.raw_translation, dict) else {}
    return dict(raw)


def build_raw_translation_profile(
    batch: CampaignBatchManifest,
    mission: CampaignMission,
) -> dict[str, Any]:
    overrides = _overrides(mission)
    source = load_h3c_block(mission.campaign_entry, mission.block_index)
    h3c_layer_ids, h3c_underground, size = layer_ids_from_h3c(mission)

    # Prefer H3C geometry; allow explicit override only when debugging a mismatch.
    layer_ids = list(overrides.get("layerIds") or h3c_layer_ids or mission.layer_ids)
    underground = list(
        overrides.get("undergroundLayers")
        if overrides.get("undergroundLayers") is not None
        else sorted(h3c_underground if h3c_underground else mission.underground_layers)
    )
    envelope_size = int(overrides.get("sourceSize") or size)

    start_hero = overrides.get("startHeroContract")
    if not isinstance(start_hero, dict):
        start_hero = infer_start_hero_contract(mission)
    if start_hero is None:
        raise ValueError(
            f"mission {mission.mission_id} has no startHeroContract override and none could be inferred"
        )
    start_hero = {key: value for key, value in start_hero.items() if not str(key).startswith("_")}

    map_sid = str(overrides.get("mapSid") or map_sid_to_raw_translation(mission.map_sid))
    title = str(overrides.get("title") or title_to_raw_translation(mission.title))
    spawn_override = overrides.get("spawn") if isinstance(overrides.get("spawn"), dict) else {}
    hub_spawn = resolve_campaign_hub_spawn(mission.mission_id)
    spawn_players = int(
        spawn_override.get("playersCount")
        if "playersCount" in spawn_override
        else overrides.get("playersCount")
        if overrides.get("playersCount") is not None
        else mission.spawn_players_count
    )
    # Prefer explicit mission override, then H3M-derived playable start, then
    # StoryHub carry-policy spawn, then batch default. Never invent from title.
    derived_spawn = None
    try:
        derived_spawn = infer_campaign_spawn_hero_sid(mission)
    except ValueError as exc:
        if not spawn_override.get("heroSid") or not spawn_override.get("factionSid"):
            raise ValueError(
                f"{mission.mission_id}: H3M spawn inference failed; provide explicit "
                f"spawn.heroSid and spawn.factionSid instead of falling back: {exc}"
            ) from exc
        derived_spawn = None
    if spawn_override.get("heroSid"):
        spawn_hero = str(spawn_override["heroSid"])
    elif derived_spawn is not None:
        spawn_hero = str(derived_spawn["heroSid"])
    elif hub_spawn is not None:
        spawn_hero = str(hub_spawn["heroSid"])
    else:
        spawn_hero = str(mission.spawn_hero_sid)
    if (
        derived_spawn is not None
        and hub_spawn is not None
        and str(hub_spawn["heroSid"]) != str(derived_spawn["heroSid"])
        and not spawn_override.get("heroSid")
    ):
        raise ValueError(
            f"{mission.mission_id}: carry-policy/hub spawn {hub_spawn['heroSid']!r} "
            f"disagrees with H3M-derived {derived_spawn['heroSid']!r} "
            f"({derived_spawn.get('evidence')}). Fix continuity_carry_policy / "
            "HUB_CONFIGS.campaignHeroSid; do not use narrative campaign titles."
        )
    if spawn_override.get("factionSid"):
        spawn_faction = str(spawn_override["factionSid"])
    elif derived_spawn is not None:
        from campaign_hub_spawn import faction_sid_from_hero_sid

        spawn_faction = faction_sid_from_hero_sid(spawn_hero)
    elif hub_spawn is not None:
        spawn_faction = str(hub_spawn["factionSid"])
    else:
        spawn_faction = str(mission.spawn_faction_sid)

    pathability = dict(DEFAULT_PATHABILITY)
    if isinstance(overrides.get("pathability"), dict):
        pathability.update(overrides["pathability"])

    core_overlay = dict(DEFAULT_CORE_OVERLAY)
    if isinstance(overrides.get("coreOverlay"), dict):
        core_overlay = dict(overrides["coreOverlay"])

    known_gaps = list(DEFAULT_KNOWN_GAPS)
    extra_gaps = overrides.get("knownGaps") or []
    if not isinstance(extra_gaps, list) or not all(isinstance(item, str) for item in extra_gaps):
        raise ValueError(f"{mission.mission_id}: rawTranslation.knownGaps must be a string array")
    if bool(overrides.get("replaceKnownGaps")):
        known_gaps = list(extra_gaps)
    else:
        for gap in extra_gaps:
            if gap not in known_gaps:
                known_gaps.append(gap)

    featured_cities = overrides.get("featuredCities")
    if featured_cities is None:
        featured_cities = list(mission.featured_cities)

    profile: dict[str, Any] = {
        "schema": PROFILE_SCHEMA,
        "scenarioId": mission.scenario_id,
        "mapSid": map_sid,
        "title": title,
        "description": (
            overrides.get("description")
            or (
                f"Parallel {source.summary.title} emit-only raw_translation map "
                f"(same pipeline class as Homecoming). Runtime gameplay remains user-unvalidated."
            )
        ),
        "artifactRoot": rel_repo(mission.artifact_root, poc.ROOT),
        "outputSubdir": OUTPUT_SUBDIR,
        "inputs": {
            "alignment": rel_repo(mission.alignment_path, poc.ROOT),
            "substitutionMap": rel_repo(mission.substitution_path, poc.ROOT),
            "batchManifest": rel_repo(batch.manifest_path, poc.ROOT),
            "coreCatalog": rel_repo(batch.core_catalog_path, poc.ROOT),
            "templateMap": str(batch.template_map_path),
        },
        "sourceEnvelope": {
            "width": envelope_size,
            "height": envelope_size,
        },
        "layers": {
            "layerIds": layer_ids,
            "undergroundLayers": underground,
        },
        "spawn": {
            "factionSid": spawn_faction,
            "heroSid": spawn_hero,
            "playersCount": spawn_players,
        },
        "startHeroContract": start_hero,
        "pathability": pathability,
        "knownGaps": known_gaps,
        "runtimeScriptComment": (
            overrides.get("runtimeScriptComment")
            or f"{mission.mission_id} raw-translation runtime script generated from campaign alignment story."
        ),
        "coreOverlay": core_overlay,
        "_generatedBy": "generate_campaign_raw_translation_profile.py",
        "_generationNote": (
            "Defaults are centralized; only batch_manifest rawTranslation overrides are mission-specific."
        ),
    }

    if featured_cities:
        profile["featuredCities"] = list(featured_cities)

    victory = overrides.get("victoryContract")
    if isinstance(victory, dict):
        profile["victoryContract"] = victory

    terrain_override = overrides.get("terrain")
    if isinstance(terrain_override, dict) and terrain_override:
        profile["terrain"] = dict(terrain_override)

    counts = expected_layer_entity_counts(mission)
    if counts:
        profile["validation"] = {
            "expectedSourceLayerEntityCounts": {
                str(key): int(value) for key, value in sorted(counts.items())
            }
        }

    # Strip generator metadata before schema consumers that reject unknown keys? 
    # scenario_profile.load is permissive of unknown top-level keys only if we don't
    # pass them... Actually load_scenario_profile only reads known keys, so extra
    # keys are fine. Keep _generatedBy for provenance.

    return profile


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=default_batch_manifest_path())
    parser.add_argument("--mission", action="append", dest="missions", help="missionId (repeatable; default: all)")
    parser.add_argument("--force", action="store_true", help="overwrite existing raw_translation profiles")
    parser.add_argument(
        "--check",
        action="store_true",
        help="compare generated profiles to on-disk profiles without writing",
    )
    args = parser.parse_args()
    batch = load_batch_manifest(args.manifest.resolve())
    selected = list(args.missions) if args.missions else [mission.mission_id for mission in batch.missions]

    mismatches: list[str] = []
    written: list[str] = []
    for mission_id in selected:
        mission = mission_by_id(batch, mission_id)
        out_path = raw_profile_path_for_mission(mission)
        profile = build_raw_translation_profile(batch, mission)
        # Consumers should ignore provenance keys; keep them only in check/write copies.
        disk_profile = {key: value for key, value in profile.items() if not str(key).startswith("_")}

        if args.check:
            if not out_path.exists():
                mismatches.append(f"{mission_id}: missing on-disk profile {out_path}")
                continue
            existing = json.loads(out_path.read_text(encoding="utf-8-sig"))
            existing_cmp = {key: value for key, value in existing.items() if not str(key).startswith("_")}
            if existing_cmp != disk_profile:
                mismatches.append(f"{mission_id}: profile drift versus generator")
            continue

        if out_path.exists() and not args.force:
            print(f"keeping existing profile for {mission_id}: {out_path} (pass --force to overwrite)")
            continue
        write_json(out_path, disk_profile)
        written.append(mission_id)
        print(f"wrote {out_path}")

    if args.check:
        if mismatches:
            print(json.dumps({"ok": False, "mismatches": mismatches}, indent=2))
            return 1
        print(json.dumps({"ok": True, "checked": selected}, indent=2))
        return 0

    print(json.dumps({"ok": True, "written": written, "kept": [m for m in selected if m not in written]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
