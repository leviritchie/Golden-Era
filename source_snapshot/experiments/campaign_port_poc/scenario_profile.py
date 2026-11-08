#!/usr/bin/env python3
"""Load scenario profiles for generic HoMM3-to-Olden layered atlas generation."""

from __future__ import annotations

import argparse
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import port_homecoming_poc as poc

PROFILE_SCHEMA = "homm3.olden_layered_atlas_scenario_profile.v1"

# Pack suffixes appended to batch missionId when forming scenarioId.
# mission_id_from_profile must strip these so quest Counter* SIDs match
# alignment-declared counters (which use bare missionId).
KNOWN_SCENARIO_PACK_SUFFIXES: tuple[str, ...] = (
    "_ab_sod",
    "_roe_castle",
    "_roe_dungeon",
    "_roe_inferno",
    "_roe_necropolis",
    "_roe_neutral",
    "_roe_rampart",
)

# Multi-token mapSid faction prefixes (must beat generic h3_<faction>_<slug>).
_MAP_SID_FACTION_PREFIXES: tuple[str, ...] = (
    "h3_roe_castle_",
    "h3_roe_dungeon_",
    "h3_roe_inferno_",
    "h3_roe_necropolis_",
    "h3_roe_neutral_",
    "h3_roe_rampart_",
)

# raw_translation is the only campaign map generation lane. Retired suffixes stay
# listed so mission_id parsing keeps working on historical mapSids that a user may
# still have on disk; nothing generates them any more.
_MAP_SID_LANE_SUFFIXES: tuple[str, ...] = (
    "_raw_translation",
    "_layered_atlas",
    "_approach_cell",
    "_zone_atlas",
)


def mission_id_from_profile(profile: Any) -> str:
    """Return bare batch missionId slug used for quest/counter SIDs.

    Alignment builds counters as ``{missionId}_started``. Emit must use the same
    slug. Returning raw ``scenarioId`` (e.g. ``bashing_skulls_ab_sod``) makes
    CounterSet target ``*_ab_sod_started`` while declared counters stay short —
    runtime ``counter … dont found`` on every briefing.

    Prefer ``scenarioId`` pack-suffix stripping first: it is the batch missionId
    contract. MapSid faction-prefix parsing is a fallback only — e.g.
    ``h3_roe_neutral_1a`` must not become ``1a`` when scenarioId is
    ``neutral_1a_roe_neutral``.
    """
    map_sid = getattr(profile, "map_sid", None)
    scenario_id = getattr(profile, "scenario_id", None)
    if not isinstance(map_sid, str) or not map_sid.strip():
        raise ValueError("mission_id_from_profile requires profile.map_sid")
    if not isinstance(scenario_id, str) or not scenario_id.strip():
        raise ValueError("mission_id_from_profile requires profile.scenario_id")

    for suffix in KNOWN_SCENARIO_PACK_SUFFIXES:
        if scenario_id.endswith(suffix):
            slug = scenario_id[: -len(suffix)]
            if slug:
                return slug

    for lane in _MAP_SID_LANE_SUFFIXES:
        if not map_sid.endswith(lane):
            continue
        body = map_sid[: -len(lane)]
        for prefix in _MAP_SID_FACTION_PREFIXES:
            if body.startswith(prefix):
                slug = body[len(prefix) :]
                if slug:
                    return slug
        if body.startswith("h3_") and "_" in body[3:]:
            slug = body[3:].split("_", 1)[1]
            if slug:
                return slug
        break

    # Unknown pack suffix — fail closed rather than emit mismatched Counter SIDs.
    if re.search(r"_(ab_sod|roe_[a-z0-9]+|hota_[a-z0-9]+)$", scenario_id):
        raise ValueError(
            f"mission_id_from_profile cannot strip pack suffix from scenarioId "
            f"{scenario_id!r} (mapSid={map_sid!r}); extend KNOWN_SCENARIO_PACK_SUFFIXES"
        )
    return scenario_id


@dataclass(frozen=True)
class StartHeroContract:
    source_layer: int
    hero_type: int
    owner: int
    payload_kind: str
    template_animation: str
    template_object_id: int
    source_key: str | None = None
    source_index: int | None = None

    def matches_entity(self, entity: dict[str, Any]) -> bool:
        expected = {
            "sourceLayer": self.source_layer,
            "heroType": self.hero_type,
            "owner": self.owner,
            "payloadKind": self.payload_kind,
            "templateAnimation": self.template_animation,
            "templateObjectId": self.template_object_id,
        }
        if {key: entity.get(key) for key in expected} != expected:
            return False
        if self.source_key is not None and entity.get("sourceKey") != self.source_key:
            return False
        if self.source_index is not None and entity.get("sourceIndex") != self.source_index:
            return False
        return True


@dataclass(frozen=True)
class FeaturedCityContract:
    source_key: str
    object_id: int
    name: str
    replacement_sid: str
    faction_sid: str
    custom_city_name: str
    buildings_ban_sid: str = "default_buildings_ban"
    buildings_construction_sid: str = "rich_buildings_construction"
    buildings_settings_sid: str = "default_buildings_settings"


@dataclass(frozen=True)
class TerrainPolicy:
    """Terrain projection overrides for layered atlas emit."""

    # When False (default), HoMM3 underground ocean tiles become walkable Burrow land
    # with pond scenery instead of native water traversal. Set True only for missions
    # that require designed underground boat travel (Blood of the Dragon Father).
    preserve_underground_ocean: bool = False


@dataclass(frozen=True)
class PathabilityPolicy:
    surface_gap_fill: bool = True
    emit_core_overlay: bool = True


@dataclass(frozen=True)
class CoreOverlayPolicy:
    """Core overlay emission policy.

    ``emit_fresh`` is the only supported mode: every mission emits its own overlay.
    The retired ``inherit_single_layer_artifact`` mode copied the single_layer lane's
    overlay and is rejected fail-closed by the generator.
    """

    mode: str = "emit_fresh"


@dataclass(frozen=True)
class ValidationSnapshot:
    expected_source_layer_entity_counts: dict[int, int] | None = None


@dataclass(frozen=True)
class VictoryContract:
    victory_type: str
    allow_normal_victory: bool
    source_keys: tuple[str, ...]
    expected_emitted_sid: str


@dataclass(frozen=True)
class ZoneAtlasPolicy:
    """Optional choke-graph zone atlas emit policy (generic; not mission-specific)."""

    enabled: bool = False
    seed: int = 20260709
    choke_width_threshold: int = 3
    enable_interior_jitter: bool = True
    max_interior_moves: int = 64
    skip_landon_overlay: bool = True
    use_native_interactable_sids: bool = True
    have_custom_areas: bool = True


@dataclass(frozen=True)
class ScenarioProfile:
    schema: str
    scenario_id: str
    map_sid: str
    title: str
    description: str
    artifact_root: Path
    alignment_path: Path
    substitution_path: Path
    core_catalog_path: Path
    template_map_path: Path
    source_width: int
    source_height: int
    layer_ids: tuple[int, ...]
    underground_layers: frozenset[int]
    spawn_faction_sid: str
    spawn_hero_sid: str
    spawn_players_count: int
    start_hero_contract: StartHeroContract
    featured_cities: tuple[FeaturedCityContract, ...] = ()
    pathability: PathabilityPolicy = field(default_factory=PathabilityPolicy)
    terrain: TerrainPolicy = field(default_factory=TerrainPolicy)
    core_overlay: CoreOverlayPolicy = field(default_factory=CoreOverlayPolicy)
    validation: ValidationSnapshot = field(default_factory=ValidationSnapshot)
    known_gaps: tuple[str, ...] = ()
    runtime_script_comment: str = "Layered atlas runtime script generated from scenario profile."
    output_subdir: str = "layered_atlas_map"
    zone_atlas: ZoneAtlasPolicy = field(default_factory=ZoneAtlasPolicy)
    victory_contract: VictoryContract | None = None
    # inputs.batchManifest: the campaign batch this profile was generated for (the batch worker
    # refuses a profile bound to another manifest).
    batch_manifest_path: Path | None = None

    @property
    def output_root(self) -> Path:
        return self.artifact_root / self.output_subdir


def _resolve_repo_path(raw: str, *, label: str) -> Path:
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError(f"{label} must be a non-empty path string")
    path = Path(raw)
    if not path.is_absolute():
        path = poc.ROOT / path
    return path


def _require_dict(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def load_scenario_profile(path: Path) -> ScenarioProfile:
    profile_path = path if path.is_absolute() else poc.ROOT / path
    if not profile_path.exists():
        raise FileNotFoundError(f"scenario profile not found: {profile_path}")
    raw = json.loads(profile_path.read_text(encoding="utf-8-sig"))
    if not isinstance(raw, dict):
        raise ValueError(f"scenario profile must be a JSON object: {profile_path}")
    schema = raw.get("schema")
    if schema != PROFILE_SCHEMA:
        raise ValueError(f"unsupported scenario profile schema {schema!r} in {profile_path}; expected {PROFILE_SCHEMA!r}")

    scenario_id = raw.get("scenarioId")
    map_sid = raw.get("mapSid")
    title = raw.get("title")
    description = raw.get("description")
    if not all(isinstance(value, str) and value.strip() for value in (scenario_id, map_sid, title, description)):
        raise ValueError(f"scenario profile missing scenarioId/mapSid/title/description: {profile_path}")

    artifact_root_raw = os.environ.get("HOMECOMING_POC_ARTIFACT_ROOT")
    if isinstance(artifact_root_raw, str) and artifact_root_raw.strip():
        artifact_root = _resolve_repo_path(artifact_root_raw, label="HOMECOMING_POC_ARTIFACT_ROOT")
    else:
        artifact_root = _resolve_repo_path(str(raw.get("artifactRoot")), label="artifactRoot")
    inputs = _require_dict(raw.get("inputs"), "inputs")
    alignment_path = _resolve_repo_path(str(inputs.get("alignment")), label="inputs.alignment")
    substitution_path = _resolve_repo_path(str(inputs.get("substitutionMap")), label="inputs.substitutionMap")
    core_catalog_path = _resolve_repo_path(
        str(inputs.get("coreCatalog") or "artifacts/campaign_port_poc/olden_entity_catalog/olden_core_map_valid_entity_catalog.json"),
        label="inputs.coreCatalog",
    )
    template_map_path = _resolve_repo_path(
        str(inputs.get("templateMap") or str(poc.PLAYABLE_TEMPLATE_MAP.relative_to(poc.ROOT)).replace("\\", "/")),
        label="inputs.templateMap",
    )
    batch_manifest_raw = inputs.get("batchManifest")
    batch_manifest_path = (
        _resolve_repo_path(str(batch_manifest_raw), label="inputs.batchManifest")
        if batch_manifest_raw
        else None
    )

    envelope = _require_dict(raw.get("sourceEnvelope"), "sourceEnvelope")
    source_width = envelope.get("width")
    source_height = envelope.get("height")
    if not isinstance(source_width, int) or not isinstance(source_height, int) or source_width <= 0 or source_height <= 0:
        raise ValueError(f"sourceEnvelope.width/height must be positive integers: {profile_path}")

    layers = _require_dict(raw.get("layers"), "layers")
    layer_ids_raw = layers.get("layerIds")
    if not isinstance(layer_ids_raw, list) or not layer_ids_raw or not all(isinstance(layer, int) for layer in layer_ids_raw):
        raise ValueError(f"layers.layerIds must be a non-empty integer array: {profile_path}")
    if len(set(layer_ids_raw)) != len(layer_ids_raw):
        raise ValueError(f"layers.layerIds must not contain duplicates: {profile_path}")
    if 0 not in layer_ids_raw:
        raise ValueError(f"layers.layerIds must include surface layer 0: {profile_path}")
    layer_ids = tuple(layer_ids_raw)
    underground_raw = layers.get("undergroundLayers") or []
    if not isinstance(underground_raw, list) or not all(isinstance(layer, int) for layer in underground_raw):
        raise ValueError(f"layers.undergroundLayers must be an integer array: {profile_path}")
    if len(set(underground_raw)) != len(underground_raw):
        raise ValueError(f"layers.undergroundLayers must not contain duplicates: {profile_path}")
    if set(underground_raw) - set(layer_ids):
        raise ValueError(f"layers.undergroundLayers must be a subset of layers.layerIds: {profile_path}")
    underground_layers = frozenset(underground_raw)

    spawn = _require_dict(raw.get("spawn"), "spawn")
    spawn_faction_sid = spawn.get("factionSid")
    spawn_hero_sid = spawn.get("heroSid")
    spawn_players_count = spawn.get("playersCount", 1)
    if not isinstance(spawn_faction_sid, str) or not spawn_faction_sid:
        raise ValueError(f"spawn.factionSid is required: {profile_path}")
    if not isinstance(spawn_hero_sid, str) or not spawn_hero_sid:
        raise ValueError(f"spawn.heroSid is required: {profile_path}")
    if not isinstance(spawn_players_count, int) or spawn_players_count <= 0:
        raise ValueError(f"spawn.playersCount must be a positive integer: {profile_path}")

    start_hero = _require_dict(raw.get("startHeroContract"), "startHeroContract")
    if int(start_hero["sourceLayer"]) not in layer_ids:
        raise ValueError(f"startHeroContract.sourceLayer is not declared by layers.layerIds: {profile_path}")
    start_hero_contract = StartHeroContract(
        source_layer=int(start_hero["sourceLayer"]),
        hero_type=int(start_hero["heroType"]),
        owner=int(start_hero["owner"]),
        payload_kind=str(start_hero["payloadKind"]),
        template_animation=str(start_hero["templateAnimation"]),
        template_object_id=int(start_hero["templateObjectId"]),
        source_key=(str(start_hero["sourceKey"]) if start_hero.get("sourceKey") is not None else None),
        source_index=(int(start_hero["sourceIndex"]) if start_hero.get("sourceIndex") is not None else None),
    )

    featured_cities: list[FeaturedCityContract] = []
    for index, row in enumerate(raw.get("featuredCities") or []):
        if not isinstance(row, dict):
            raise ValueError(f"featuredCities[{index}] must be an object")
        featured_cities.append(
            FeaturedCityContract(
                source_key=str(row["sourceKey"]),
                object_id=int(row["objectId"]),
                name=str(row["name"]),
                replacement_sid=str(row["replacementSid"]),
                faction_sid=str(row["factionSid"]),
                custom_city_name=str(row.get("customCityName") or row["name"]),
                buildings_ban_sid=str(row.get("buildingsBanSid") or "default_buildings_ban"),
                buildings_construction_sid=str(row.get("buildingsConstructionSid") or "rich_buildings_construction"),
                buildings_settings_sid=str(row.get("buildingsSettingsSid") or "default_buildings_settings"),
            )
        )

    pathability_raw = raw.get("pathability") if isinstance(raw.get("pathability"), dict) else {}
    pathability = PathabilityPolicy(
        surface_gap_fill=bool(pathability_raw.get("surfaceGapFill", True)),
        emit_core_overlay=bool(pathability_raw.get("emitCoreOverlay", True)),
    )

    terrain_raw = raw.get("terrain") if isinstance(raw.get("terrain"), dict) else {}
    terrain = TerrainPolicy(
        preserve_underground_ocean=bool(terrain_raw.get("preserveUndergroundOcean", False)),
    )

    core_overlay_raw = raw.get("coreOverlay") if isinstance(raw.get("coreOverlay"), dict) else {}
    if "singleLayerArtifactRoot" in core_overlay_raw:
        raise ValueError(
            "coreOverlay.singleLayerArtifactRoot is retired with the single_layer lane; "
            "remove it and use coreOverlay.mode emit_fresh"
        )
    core_overlay = CoreOverlayPolicy(mode=str(core_overlay_raw.get("mode") or "emit_fresh"))

    validation_raw = raw.get("validation") if isinstance(raw.get("validation"), dict) else {}
    expected_counts = validation_raw.get("expectedSourceLayerEntityCounts")
    expected_source_layer_entity_counts: dict[int, int] | None = None
    if isinstance(expected_counts, dict) and expected_counts:
        expected_source_layer_entity_counts = {int(key): int(value) for key, value in expected_counts.items()}
    validation = ValidationSnapshot(expected_source_layer_entity_counts=expected_source_layer_entity_counts)

    victory_contract: VictoryContract | None = None
    victory_raw = raw.get("victoryContract")
    if victory_raw is not None:
        victory_obj = _require_dict(victory_raw, "victoryContract")
        victory_type = victory_obj.get("type")
        allow_normal_victory = victory_obj.get("allowNormalVictory")
        source_keys_raw = victory_obj.get("sourceKeys")
        expected_emitted_sid = victory_obj.get("expectedEmittedSid")
        if victory_type != "TAKEDWELLINGS":
            raise ValueError(f"victoryContract.type must be TAKEDWELLINGS: {profile_path}")
        if not isinstance(allow_normal_victory, bool):
            raise ValueError(f"victoryContract.allowNormalVictory must be boolean: {profile_path}")
        if (
            not isinstance(source_keys_raw, list)
            or not source_keys_raw
            or not all(isinstance(key, str) and key for key in source_keys_raw)
        ):
            raise ValueError(f"victoryContract.sourceKeys must be a non-empty string array: {profile_path}")
        if len(set(source_keys_raw)) != len(source_keys_raw):
            raise ValueError(f"victoryContract.sourceKeys must not contain duplicates: {profile_path}")
        if not isinstance(expected_emitted_sid, str) or not expected_emitted_sid:
            raise ValueError(f"victoryContract.expectedEmittedSid must be a non-empty string: {profile_path}")
        victory_contract = VictoryContract(
            victory_type=victory_type,
            allow_normal_victory=allow_normal_victory,
            source_keys=tuple(source_keys_raw),
            expected_emitted_sid=expected_emitted_sid,
        )

    known_gaps_raw = raw.get("knownGaps") or []
    if not isinstance(known_gaps_raw, list) or not all(isinstance(item, str) for item in known_gaps_raw):
        raise ValueError(f"knownGaps must be a string array when present: {profile_path}")

    runtime_script_comment = raw.get("runtimeScriptComment")
    if runtime_script_comment is not None and not isinstance(runtime_script_comment, str):
        raise ValueError(f"runtimeScriptComment must be a string when present: {profile_path}")

    output_subdir = raw.get("outputSubdir") or "layered_atlas_map"
    if not isinstance(output_subdir, str) or not output_subdir.strip():
        raise ValueError(f"outputSubdir must be a non-empty string when present: {profile_path}")

    zone_raw = raw.get("zoneAtlas") if isinstance(raw.get("zoneAtlas"), dict) else {}
    zone_atlas = ZoneAtlasPolicy(
        enabled=bool(zone_raw.get("enabled", False)),
        seed=int(zone_raw.get("seed", 20260709)),
        choke_width_threshold=int(zone_raw.get("chokeWidthThreshold", 3)),
        enable_interior_jitter=bool(zone_raw.get("enableInteriorJitter", True)),
        max_interior_moves=int(zone_raw.get("maxInteriorMoves", 64)),
        skip_landon_overlay=bool(zone_raw.get("skipLandonOverlay", True)),
        use_native_interactable_sids=bool(zone_raw.get("useNativeInteractableSids", True)),
        have_custom_areas=bool(zone_raw.get("haveCustomAreas", True)),
    )

    return ScenarioProfile(
        schema=PROFILE_SCHEMA,
        scenario_id=scenario_id,
        map_sid=map_sid,
        title=title,
        description=description,
        artifact_root=artifact_root,
        alignment_path=alignment_path,
        substitution_path=substitution_path,
        core_catalog_path=core_catalog_path,
        template_map_path=template_map_path,
        source_width=source_width,
        source_height=source_height,
        layer_ids=layer_ids,
        underground_layers=underground_layers,
        spawn_faction_sid=spawn_faction_sid,
        spawn_hero_sid=spawn_hero_sid,
        spawn_players_count=spawn_players_count,
        start_hero_contract=start_hero_contract,
        featured_cities=tuple(featured_cities),
        pathability=pathability,
        terrain=terrain,
        core_overlay=core_overlay,
        validation=validation,
        known_gaps=tuple(known_gaps_raw),
        runtime_script_comment=str(runtime_script_comment or "Layered atlas runtime script generated from scenario profile."),
        output_subdir=str(output_subdir).strip(),
        zone_atlas=zone_atlas,
        victory_contract=victory_contract,
        batch_manifest_path=batch_manifest_path,
    )
