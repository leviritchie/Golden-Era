#!/usr/bin/env python3
"""Load campaign batch manifests and resolve per-mission artifact paths."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import port_homecoming_poc as poc

BATCH_SCHEMA = "homm3.olden_campaign_batch_manifest.v1"


@dataclass(frozen=True)
class PathabilityPolicy:
    surface_gap_fill: bool = False
    emit_core_overlay: bool = False


@dataclass(frozen=True)
class CampaignMission:
    mission_id: str
    scenario_id: str
    campaign_entry: str
    block_index: int
    campaign_title: str
    artifact_root: Path
    map_sid: str
    title: str
    layer_ids: tuple[int, ...]
    underground_layers: frozenset[int]
    template_map_path: Path
    core_catalog_path: Path
    spawn_faction_sid: str
    spawn_hero_sid: str
    spawn_players_count: int
    pathability: PathabilityPolicy = field(default_factory=PathabilityPolicy)
    profile_path: Path | None = None
    reuse_existing_upstream: bool = False
    core_overlay_single_layer_root: str | None = None
    start_hero_contract: dict[str, Any] | None = None
    featured_cities: tuple[dict[str, Any], ...] = ()
    validation_expected_layer_counts: dict[int, int] | None = None
    # Optional raw_translation-only overrides (spawn/overlay/victory/etc.). Shared
    # defaults live in generate_campaign_raw_translation_profile.py.
    raw_translation: dict[str, Any] = field(default_factory=dict)

    @property
    def layered_ir_dir(self) -> Path:
        return self.artifact_root / "layered_ir"

    @property
    def layered_ir_path(self) -> Path:
        return self.layered_ir_dir / f"{self.mission_id}.layered_map_ir.json"

    @property
    def object_walk_path(self) -> Path:
        return self.layered_ir_dir / f"{self.mission_id}.object_walk.json"

    @property
    def object_port_manifest_path(self) -> Path:
        return self.layered_ir_dir / f"{self.mission_id}.object_port_manifest.json"

    @property
    def alignment_path(self) -> Path:
        return self.artifact_root / "olden_storage_alignment" / f"{self.mission_id}.olden_storage_alignment.json"

    @property
    def substitution_path(self) -> Path:
        return self.artifact_root / "entity_substitutions" / f"{self.mission_id}.olden_entity_substitution_map.json"

    @property
    def substitution_basename(self) -> str:
        return f"{self.mission_id}.olden_entity_substitution_map"

    @property
    def alignment_basename(self) -> str:
        return f"{self.mission_id}.olden_storage_alignment"

    @property
    def ir_basename(self) -> str:
        return self.mission_id


@dataclass(frozen=True)
class CampaignBatchManifest:
    schema: str
    title: str
    description: str
    template_map_path: Path
    core_catalog_path: Path
    default_spawn_faction_sid: str
    default_spawn_hero_sid: str
    default_spawn_players_count: int
    missions: tuple[CampaignMission, ...]
    manifest_path: Path


def _resolve_repo_path(raw: str, *, label: str) -> Path:
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError(f"{label} must be a non-empty path string")
    path = Path(raw)
    if not path.is_absolute():
        path = poc.ROOT / path
    return path


def load_batch_manifest(path: Path) -> CampaignBatchManifest:
    manifest_path = path if path.is_absolute() else poc.ROOT / path
    if not manifest_path.exists():
        raise FileNotFoundError(f"campaign batch manifest not found: {manifest_path}")
    raw = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    if not isinstance(raw, dict):
        raise ValueError(f"campaign batch manifest must be a JSON object: {manifest_path}")
    schema = raw.get("schema")
    if schema != BATCH_SCHEMA:
        raise ValueError(f"unsupported campaign batch schema {schema!r}; expected {BATCH_SCHEMA!r}")

    title = raw.get("title")
    description = raw.get("description")
    if not isinstance(title, str) or not isinstance(description, str):
        raise ValueError("batch manifest requires title and description strings")

    template_map_path = _resolve_repo_path(str(raw.get("templateMap")), label="templateMap")
    core_catalog_path = _resolve_repo_path(str(raw.get("coreCatalog")), label="coreCatalog")
    default_spawn = raw.get("defaultSpawn") if isinstance(raw.get("defaultSpawn"), dict) else {}
    default_spawn_faction_sid = str(default_spawn.get("factionSid") or "homm3_castle")
    default_spawn_hero_sid = str(default_spawn.get("heroSid") or "homm3_castle_hero_7")
    default_spawn_players_count = int(default_spawn.get("playersCount") or 1)

    missions_raw = raw.get("missions")
    if not isinstance(missions_raw, list) or not missions_raw:
        raise ValueError("batch manifest missions must be a non-empty array")

    missions: list[CampaignMission] = []
    seen_ids: set[str] = set()
    for index, row in enumerate(missions_raw):
        if not isinstance(row, dict):
            raise ValueError(f"missions[{index}] must be an object")
        mission_id = row.get("missionId")
        scenario_id = row.get("scenarioId")
        if not isinstance(mission_id, str) or not mission_id.strip():
            raise ValueError(f"missions[{index}].missionId is required")
        if mission_id in seen_ids:
            raise ValueError(f"duplicate missionId {mission_id!r}")
        seen_ids.add(mission_id)
        if not isinstance(scenario_id, str) or not scenario_id.strip():
            raise ValueError(f"missions[{index}].scenarioId is required")

        block_index = row.get("blockIndex")
        if not isinstance(block_index, int) or block_index <= 0:
            raise ValueError(f"missions[{index}].blockIndex must be a positive integer")

        layer_ids_raw = row.get("layerIds")
        if not isinstance(layer_ids_raw, list) or not layer_ids_raw:
            raise ValueError(f"missions[{index}].layerIds must be a non-empty integer array")
        layer_ids = tuple(sorted(set(int(layer) for layer in layer_ids_raw)))

        underground_raw = row.get("undergroundLayers") or []
        if not isinstance(underground_raw, list):
            raise ValueError(f"missions[{index}].undergroundLayers must be an array")
        underground_layers = frozenset(int(layer) for layer in underground_raw)

        pathability_raw = row.get("pathability") if isinstance(row.get("pathability"), dict) else {}
        pathability = PathabilityPolicy(
            surface_gap_fill=bool(pathability_raw.get("surfaceGapFill")),
            emit_core_overlay=bool(pathability_raw.get("emitCoreOverlay")),
        )

        validation_raw = row.get("validation") if isinstance(row.get("validation"), dict) else {}
        expected_counts_raw = validation_raw.get("expectedSourceLayerEntityCounts")
        validation_expected_layer_counts: dict[int, int] | None = None
        if isinstance(expected_counts_raw, dict) and expected_counts_raw:
            validation_expected_layer_counts = {int(key): int(value) for key, value in expected_counts_raw.items()}

        profile_path: Path | None = None
        if isinstance(row.get("profilePath"), str) and row.get("profilePath"):
            profile_path = _resolve_repo_path(str(row["profilePath"]), label=f"missions[{index}].profilePath")

        featured_cities = tuple(row.get("featuredCities") or [])
        start_hero_contract = row.get("startHeroContract") if isinstance(row.get("startHeroContract"), dict) else None
        raw_translation_raw = row.get("rawTranslation") if isinstance(row.get("rawTranslation"), dict) else {}

        missions.append(
            CampaignMission(
                mission_id=mission_id,
                scenario_id=scenario_id,
                campaign_entry=str(row.get("campaignEntry")),
                block_index=block_index,
                campaign_title=str(row.get("campaignTitle") or ""),
                artifact_root=_resolve_repo_path(str(row.get("artifactRoot")), label=f"missions[{index}].artifactRoot"),
                map_sid=str(row.get("mapSid")),
                title=str(row.get("title")),
                layer_ids=layer_ids,
                underground_layers=underground_layers,
                template_map_path=template_map_path,
                core_catalog_path=core_catalog_path,
                spawn_faction_sid=str((row.get("spawn") or {}).get("factionSid") or default_spawn_faction_sid),
                spawn_hero_sid=str((row.get("spawn") or {}).get("heroSid") or default_spawn_hero_sid),
                spawn_players_count=int((row.get("spawn") or {}).get("playersCount") or default_spawn_players_count),
                pathability=pathability,
                profile_path=profile_path,
                reuse_existing_upstream=bool(row.get("reuseExistingUpstream")),
                core_overlay_single_layer_root=row.get("coreOverlaySingleLayerRoot"),
                start_hero_contract=start_hero_contract,
                featured_cities=featured_cities,
                validation_expected_layer_counts=validation_expected_layer_counts,
                raw_translation=dict(raw_translation_raw),
            )
        )

    return CampaignBatchManifest(
        schema=schema,
        title=title,
        description=description,
        template_map_path=template_map_path,
        core_catalog_path=core_catalog_path,
        default_spawn_faction_sid=default_spawn_faction_sid,
        default_spawn_hero_sid=default_spawn_hero_sid,
        default_spawn_players_count=default_spawn_players_count,
        missions=tuple(missions),
        manifest_path=manifest_path.resolve(),
    )


def mission_by_id(manifest: CampaignBatchManifest, mission_id: str) -> CampaignMission:
    for mission in manifest.missions:
        if mission.mission_id == mission_id:
            return mission
    known = ", ".join(mission.mission_id for mission in manifest.missions)
    raise KeyError(f"unknown missionId {mission_id!r}; known missions: {known}")


def default_batch_manifest_path() -> Path:
    override = os.environ.get("CAMPAIGN_BATCH_MANIFEST")
    if isinstance(override, str) and override.strip():
        return Path(override)
    return poc.ROOT / "scenarios" / "roe_castle_campaign" / "batch_manifest.json"
