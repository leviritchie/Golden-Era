"""Versioned, normalized configuration for procedural scenario generation."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping

from .model import Archetype, Difficulty, sha256_json


SCENARIO_PROFILE_SCHEMA = "homm3.procedural_scenario_profile.v1"
SUPPORTED_MAP_SIZES = frozenset((32, 48, 64))
_SID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_LOCALE_RE = re.compile(r"^[A-Za-z]{2,3}(?:[-_][A-Za-z0-9]{2,8})*$")


class ProfileError(ValueError):
    """Raised when a profile would require implicit normalization or fallback."""


class TextMode(str, Enum):
    NONE = "none"
    OPTIONAL = "optional"
    REQUIRED = "required"


@dataclass(frozen=True)
class EconomySettings:
    starting_gold: int = 4_000
    starting_wood: int = 8
    starting_ore: int = 8
    reward_multiplier: float = 1.0
    recurring_income_enabled: bool = False
    recurring_income_interval: int = 7
    recurring_income_gold: int = 1_000

    def normalized(self) -> "EconomySettings":
        _require_int("economy.startingGold", self.starting_gold, minimum=0)
        _require_int("economy.startingWood", self.starting_wood, minimum=0)
        _require_int("economy.startingOre", self.starting_ore, minimum=0)
        _require_number(
            "economy.rewardMultiplier", self.reward_multiplier, minimum=0.1, maximum=10.0
        )
        _require_bool("economy.recurringIncomeEnabled", self.recurring_income_enabled)
        _require_int(
            "economy.recurringIncomeInterval", self.recurring_income_interval, minimum=1
        )
        _require_int(
            "economy.recurringIncomeGold", self.recurring_income_gold, minimum=0
        )
        return EconomySettings(
            starting_gold=int(self.starting_gold),
            starting_wood=int(self.starting_wood),
            starting_ore=int(self.starting_ore),
            reward_multiplier=float(self.reward_multiplier),
            recurring_income_enabled=self.recurring_income_enabled,
            recurring_income_interval=int(self.recurring_income_interval),
            recurring_income_gold=int(self.recurring_income_gold),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "startingGold": self.starting_gold,
            "startingWood": self.starting_wood,
            "startingOre": self.starting_ore,
            "rewardMultiplier": self.reward_multiplier,
            "recurringIncomeEnabled": self.recurring_income_enabled,
            "recurringIncomeInterval": self.recurring_income_interval,
            "recurringIncomeGold": self.recurring_income_gold,
        }


@dataclass(frozen=True)
class DensitySettings:
    decision_spacing_min: int = 6
    decision_spacing_max: int = 10
    scenery_per_100_tiles: float = 60.0
    optional_gameplay_per_zone: float = 4.0

    def normalized(self) -> "DensitySettings":
        _require_int("density.decisionSpacingMin", self.decision_spacing_min, minimum=2)
        _require_int("density.decisionSpacingMax", self.decision_spacing_max, minimum=2)
        if self.decision_spacing_min > self.decision_spacing_max:
            raise ProfileError(
                "density.decisionSpacingMin must not exceed decisionSpacingMax"
            )
        _require_number(
            "density.sceneryPer100Tiles",
            self.scenery_per_100_tiles,
            minimum=0.0,
            maximum=70.0,
        )
        _require_number(
            "density.optionalGameplayPerZone",
            self.optional_gameplay_per_zone,
            minimum=0.0,
            maximum=5.0,
        )
        return DensitySettings(
            decision_spacing_min=int(self.decision_spacing_min),
            decision_spacing_max=int(self.decision_spacing_max),
            scenery_per_100_tiles=float(self.scenery_per_100_tiles),
            optional_gameplay_per_zone=float(self.optional_gameplay_per_zone),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "decisionSpacingMin": self.decision_spacing_min,
            "decisionSpacingMax": self.decision_spacing_max,
            "sceneryPer100Tiles": self.scenery_per_100_tiles,
            "optionalGameplayPerZone": self.optional_gameplay_per_zone,
        }


@dataclass(frozen=True)
class EventPolicy:
    turn_schedules_enabled: bool = True
    visit_events_enabled: bool = True
    squad_defeat_events_enabled: bool = True
    capture_events_enabled: bool = True
    resource_rewards_enabled: bool = True
    objective_progress_enabled: bool = True
    victory_contract: str = "explicit_single"
    seer_hut_count: int = 0

    def normalized(self) -> "EventPolicy":
        for name, value in (
            ("turnSchedulesEnabled", self.turn_schedules_enabled),
            ("visitEventsEnabled", self.visit_events_enabled),
            ("squadDefeatEventsEnabled", self.squad_defeat_events_enabled),
            ("captureEventsEnabled", self.capture_events_enabled),
            ("resourceRewardsEnabled", self.resource_rewards_enabled),
            ("objectiveProgressEnabled", self.objective_progress_enabled),
        ):
            _require_bool(f"eventPolicy.{name}", value)
        _require_int("eventPolicy.seerHutCount", self.seer_hut_count, minimum=0, maximum=8)
        if self.victory_contract != "explicit_single":
            raise ProfileError(
                "eventPolicy.victoryContract must be 'explicit_single'; "
                "alternate victory fallbacks are not supported"
            )
        return EventPolicy(
            turn_schedules_enabled=bool(self.turn_schedules_enabled),
            visit_events_enabled=bool(self.visit_events_enabled),
            squad_defeat_events_enabled=bool(self.squad_defeat_events_enabled),
            capture_events_enabled=bool(self.capture_events_enabled),
            resource_rewards_enabled=bool(self.resource_rewards_enabled),
            objective_progress_enabled=bool(self.objective_progress_enabled),
            victory_contract=self.victory_contract,
            seer_hut_count=int(self.seer_hut_count),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "turnSchedulesEnabled": self.turn_schedules_enabled,
            "visitEventsEnabled": self.visit_events_enabled,
            "squadDefeatEventsEnabled": self.squad_defeat_events_enabled,
            "captureEventsEnabled": self.capture_events_enabled,
            "resourceRewardsEnabled": self.resource_rewards_enabled,
            "objectiveProgressEnabled": self.objective_progress_enabled,
            "victoryContract": self.victory_contract,
            "seerHutCount": self.seer_hut_count,
        }


@dataclass(frozen=True)
class TextProviderSettings:
    mode: TextMode = TextMode.NONE
    endpoint: str | None = None
    model: str | None = None
    prompt_version: str = "procedural-flavor-v1"
    api_key_env: str = "OPENAI_API_KEY"
    timeout_seconds: float = 30.0

    def normalized(self) -> "TextProviderSettings":
        mode = _enum_value(TextMode, self.mode, "textProvider.mode")
        endpoint = _optional_trimmed(self.endpoint)
        model = _optional_trimmed(self.model)
        prompt_version = _require_text(
            "textProvider.promptVersion", self.prompt_version
        )
        api_key_env = _require_text("textProvider.apiKeyEnv", self.api_key_env)
        _require_number(
            "textProvider.timeoutSeconds",
            self.timeout_seconds,
            minimum=1.0,
            maximum=300.0,
        )
        if mode is not TextMode.NONE and (endpoint is None or model is None):
            raise ProfileError(
                "textProvider.endpoint and textProvider.model are required "
                "when textProvider.mode is optional or required"
            )
        return TextProviderSettings(
            mode=mode,
            endpoint=endpoint,
            model=model,
            prompt_version=prompt_version,
            api_key_env=api_key_env,
            timeout_seconds=float(self.timeout_seconds),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode.value,
            "endpoint": self.endpoint,
            "model": self.model,
            "promptVersion": self.prompt_version,
            "apiKeyEnv": self.api_key_env,
            "timeoutSeconds": self.timeout_seconds,
        }


@dataclass(frozen=True)
class TopologySettings:
    zone_count: int | None = None
    optional_loops_enabled: bool = True
    high_risk_side_areas_enabled: bool = True
    high_risk_side_area_count: int = 1
    neutral_city_count: int = 0

    def normalized(self) -> "TopologySettings":
        if self.zone_count is not None:
            _require_int("topology.zoneCount", self.zone_count, minimum=5, maximum=30)
        _require_bool("topology.optionalLoopsEnabled", self.optional_loops_enabled)
        _require_bool(
            "topology.highRiskSideAreasEnabled", self.high_risk_side_areas_enabled
        )
        _require_int(
            "topology.highRiskSideAreaCount",
            self.high_risk_side_area_count,
            minimum=0,
            maximum=5,
        )
        _require_int("topology.neutralCityCount", self.neutral_city_count, minimum=0, maximum=8)
        if (
            not self.high_risk_side_areas_enabled
            and self.high_risk_side_area_count != 0
        ):
            raise ProfileError(
                "topology.highRiskSideAreaCount must be 0 when high-risk side areas are disabled"
            )
        return self

    def to_dict(self) -> dict[str, Any]:
        return {
            "zoneCount": self.zone_count,
            "optionalLoopsEnabled": self.optional_loops_enabled,
            "highRiskSideAreasEnabled": self.high_risk_side_areas_enabled,
            "highRiskSideAreaCount": self.high_risk_side_area_count,
            "neutralCityCount": self.neutral_city_count,
        }


@dataclass(frozen=True)
class TerrainSettings:
    water_enabled: bool = False
    water_fraction: float = 0.0
    roads_enabled: bool = True
    road_biome: str = "dirt"
    elevation_enabled: bool = True
    elevation_fraction: float = 0.6

    def normalized(self) -> "TerrainSettings":
        _require_bool("terrain.waterEnabled", self.water_enabled)
        _require_number(
            "terrain.waterFraction", self.water_fraction, minimum=0.0, maximum=0.35
        )
        _require_bool("terrain.roadsEnabled", self.roads_enabled)
        _require_bool("terrain.elevationEnabled", self.elevation_enabled)
        _require_number(
            "terrain.elevationFraction",
            self.elevation_fraction,
            minimum=0.0,
            maximum=0.6,
        )
        if not self.elevation_enabled and self.elevation_fraction != 0.0:
            raise ProfileError(
                "terrain.elevationFraction must be 0 when terrain.elevationEnabled is false"
            )
        road_biome = _normalize_biome(self.road_biome)
        if self.water_enabled or self.water_fraction != 0.0:
            raise ProfileError(
                "water traversal is not proven for procedural surface maps; "
                "terrain.waterEnabled must be false and waterFraction must be 0"
            )
        return TerrainSettings(
            water_enabled=self.water_enabled,
            water_fraction=float(self.water_fraction),
            roads_enabled=self.roads_enabled,
            road_biome=road_biome,
            elevation_enabled=self.elevation_enabled,
            elevation_fraction=float(self.elevation_fraction),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "waterEnabled": self.water_enabled,
            "waterFraction": self.water_fraction,
            "roadsEnabled": self.roads_enabled,
            "roadBiome": self.road_biome,
            "elevationEnabled": self.elevation_enabled,
            "elevationFraction": self.elevation_fraction,
        }


@dataclass(frozen=True)
class ScenarioProfileV1:
    seed: int
    archetype: Archetype = Archetype.EXPLORATION
    map_size: int = 64
    player_faction: str = "homm3_castle"
    ai_factions: tuple[str, ...] = ("homm3_inferno",)
    ai_count: int = 1
    difficulty: Difficulty = Difficulty.NORMAL
    economy: EconomySettings = field(default_factory=EconomySettings)
    biomes: tuple[str, ...] = ("grass", "dirt")
    density: DensitySettings = field(default_factory=DensitySettings)
    event_policy: EventPolicy = field(default_factory=EventPolicy)
    locale: str = "en"
    text_provider: TextProviderSettings = field(default_factory=TextProviderSettings)
    topology: TopologySettings = field(default_factory=TopologySettings)
    terrain: TerrainSettings = field(default_factory=TerrainSettings)
    content_allowlist: tuple[str, ...] = ("city-spawner", "random-squad")
    scenario_id_prefix: str = "proc"
    schema: str = SCENARIO_PROFILE_SCHEMA

    @property
    def factions(self) -> tuple[str, ...]:
        return (self.player_faction,) + self.ai_factions

    def normalized(self) -> "ScenarioProfileV1":
        if self.schema != SCENARIO_PROFILE_SCHEMA:
            raise ProfileError(
                f"unsupported profile schema {self.schema!r}; "
                f"expected {SCENARIO_PROFILE_SCHEMA!r}"
            )
        _require_int("seed", self.seed, minimum=0, maximum=(1 << 63) - 1)
        archetype = _enum_value(Archetype, self.archetype, "archetype")
        if self.map_size not in SUPPORTED_MAP_SIZES:
            raise ProfileError(
                f"mapSize must be one of {sorted(SUPPORTED_MAP_SIZES)}; got {self.map_size!r}"
            )
        player_faction = _normalize_sid("playerFaction", self.player_faction)
        ai_factions = tuple(
            _normalize_sid(f"aiFactions[{index}]", value)
            for index, value in enumerate(self.ai_factions)
        )
        _require_int("aiCount", self.ai_count, minimum=0, maximum=7)
        if len(ai_factions) != self.ai_count:
            raise ProfileError(
                f"aiCount={self.ai_count} requires exactly {self.ai_count} aiFactions; "
                f"got {len(ai_factions)}"
            )
        if len(set((player_faction,) + ai_factions)) != 1 + len(ai_factions):
            raise ProfileError("playerFaction and aiFactions must contain unique SIDs")
        difficulty = _enum_value(Difficulty, self.difficulty, "difficulty")
        economy = self.economy.normalized()
        if not self.biomes:
            raise ProfileError("biomes must contain at least one biome")
        biomes = tuple(_normalize_biome(value) for value in self.biomes)
        if len(set(biomes)) != len(biomes):
            raise ProfileError("biomes must not contain duplicates")
        density = self.density.normalized()
        event_policy = self.event_policy.normalized()
        locale = _require_text("locale", self.locale).replace("_", "-")
        if not _LOCALE_RE.fullmatch(locale):
            raise ProfileError(f"locale is not a supported locale tag: {locale!r}")
        text_provider = self.text_provider.normalized()
        topology = self.topology.normalized()
        terrain = self.terrain.normalized()
        allowlist = tuple(
            sorted(
                {
                    _normalize_sid(f"contentAllowlist[{index}]", value)
                    for index, value in enumerate(self.content_allowlist)
                }
            )
        )
        scenario_id_prefix = _normalize_sid(
            "scenarioIdPrefix", self.scenario_id_prefix
        ).lower()
        if not re.fullmatch(r"proc(?:_[a-z0-9]+)*", scenario_id_prefix):
            raise ProfileError(
                "scenarioIdPrefix must stay in the reserved 'proc' namespace"
            )
        return ScenarioProfileV1(
            seed=int(self.seed),
            archetype=archetype,
            map_size=int(self.map_size),
            player_faction=player_faction,
            ai_factions=ai_factions,
            ai_count=int(self.ai_count),
            difficulty=difficulty,
            economy=economy,
            biomes=biomes,
            density=density,
            event_policy=event_policy,
            locale=locale,
            text_provider=text_provider,
            topology=topology,
            terrain=terrain,
            content_allowlist=allowlist,
            scenario_id_prefix=scenario_id_prefix,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "seed": self.seed,
            "archetype": self.archetype.value,
            "mapSize": self.map_size,
            "playerFaction": self.player_faction,
            "aiFactions": list(self.ai_factions),
            "aiCount": self.ai_count,
            "difficulty": self.difficulty.value,
            "economy": self.economy.to_dict(),
            "biomes": list(self.biomes),
            "density": self.density.to_dict(),
            "eventPolicy": self.event_policy.to_dict(),
            "locale": self.locale,
            "textProvider": self.text_provider.to_dict(),
            "topology": self.topology.to_dict(),
            "terrain": self.terrain.to_dict(),
            "contentAllowlist": list(self.content_allowlist),
            "scenarioIdPrefix": self.scenario_id_prefix,
        }

    @property
    def fingerprint(self) -> str:
        return sha256_json(self.normalized().to_dict())

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "ScenarioProfileV1":
        _reject_unknown(
            raw,
            {
                "schema",
                "seed",
                "archetype",
                "mapSize",
                "playerFaction",
                "aiFactions",
                "aiCount",
                "difficulty",
                "economy",
                "biomes",
                "density",
                "eventPolicy",
                "locale",
                "textProvider",
                "topology",
                "terrain",
                "contentAllowlist",
                "scenarioIdPrefix",
            },
            "profile",
        )
        if "seed" not in raw:
            raise ProfileError("profile.seed is required")
        defaults = cls(seed=0)
        economy = _nested_dataclass(
            raw.get("economy"), defaults.economy, EconomySettings, "economy"
        )
        density = _nested_dataclass(
            raw.get("density"), defaults.density, DensitySettings, "density"
        )
        event_policy = _nested_dataclass(
            raw.get("eventPolicy"),
            defaults.event_policy,
            EventPolicy,
            "eventPolicy",
        )
        text_provider = _nested_dataclass(
            raw.get("textProvider"),
            defaults.text_provider,
            TextProviderSettings,
            "textProvider",
        )
        topology = _nested_dataclass(
            raw.get("topology"), defaults.topology, TopologySettings, "topology"
        )
        terrain = _nested_dataclass(
            raw.get("terrain"), defaults.terrain, TerrainSettings, "terrain"
        )
        return cls(
            schema=raw.get("schema", SCENARIO_PROFILE_SCHEMA),
            seed=raw["seed"],
            archetype=raw.get("archetype", defaults.archetype),
            map_size=raw.get("mapSize", defaults.map_size),
            player_faction=raw.get("playerFaction", defaults.player_faction),
            ai_factions=tuple(raw.get("aiFactions", defaults.ai_factions)),
            ai_count=raw.get("aiCount", defaults.ai_count),
            difficulty=raw.get("difficulty", defaults.difficulty),
            economy=economy,
            biomes=tuple(raw.get("biomes", defaults.biomes)),
            density=density,
            event_policy=event_policy,
            locale=raw.get("locale", defaults.locale),
            text_provider=text_provider,
            topology=topology,
            terrain=terrain,
            content_allowlist=tuple(
                raw.get("contentAllowlist", defaults.content_allowlist)
            ),
            scenario_id_prefix=raw.get(
                "scenarioIdPrefix", defaults.scenario_id_prefix
            ),
        ).normalized()


_NESTED_KEY_MAP: dict[type[Any], dict[str, str]] = {
    EconomySettings: {
        "startingGold": "starting_gold",
        "startingWood": "starting_wood",
        "startingOre": "starting_ore",
        "rewardMultiplier": "reward_multiplier",
        "recurringIncomeEnabled": "recurring_income_enabled",
        "recurringIncomeInterval": "recurring_income_interval",
        "recurringIncomeGold": "recurring_income_gold",
    },
    DensitySettings: {
        "decisionSpacingMin": "decision_spacing_min",
        "decisionSpacingMax": "decision_spacing_max",
        "sceneryPer100Tiles": "scenery_per_100_tiles",
        "optionalGameplayPerZone": "optional_gameplay_per_zone",
    },
    EventPolicy: {
        "turnSchedulesEnabled": "turn_schedules_enabled",
        "visitEventsEnabled": "visit_events_enabled",
        "squadDefeatEventsEnabled": "squad_defeat_events_enabled",
        "captureEventsEnabled": "capture_events_enabled",
        "resourceRewardsEnabled": "resource_rewards_enabled",
        "objectiveProgressEnabled": "objective_progress_enabled",
        "victoryContract": "victory_contract",
        "seerHutCount": "seer_hut_count",
    },
    TextProviderSettings: {
        "mode": "mode",
        "endpoint": "endpoint",
        "model": "model",
        "promptVersion": "prompt_version",
        "apiKeyEnv": "api_key_env",
        "timeoutSeconds": "timeout_seconds",
    },
    TopologySettings: {
        "zoneCount": "zone_count",
        "optionalLoopsEnabled": "optional_loops_enabled",
        "highRiskSideAreasEnabled": "high_risk_side_areas_enabled",
        "highRiskSideAreaCount": "high_risk_side_area_count",
        "neutralCityCount": "neutral_city_count",
    },
    TerrainSettings: {
        "waterEnabled": "water_enabled",
        "waterFraction": "water_fraction",
        "roadsEnabled": "roads_enabled",
        "roadBiome": "road_biome",
        "elevationEnabled": "elevation_enabled",
        "elevationFraction": "elevation_fraction",
    },
}


def _nested_dataclass(
    raw: Any,
    defaults: Any,
    cls: type[Any],
    label: str,
) -> Any:
    if raw is None:
        return defaults
    if not isinstance(raw, Mapping):
        raise ProfileError(f"{label} must be an object")
    mapping = _NESTED_KEY_MAP[cls]
    _reject_unknown(raw, set(mapping), label)
    values = {
        attr: raw.get(key, getattr(defaults, attr)) for key, attr in mapping.items()
    }
    return cls(**values)


def _reject_unknown(raw: Mapping[str, Any], allowed: set[str], label: str) -> None:
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise ProfileError(f"{label} contains unknown fields: {unknown}")


def _enum_value(enum_type: type[Enum], value: Any, label: str) -> Any:
    if isinstance(value, enum_type):
        return value
    try:
        return enum_type(value)
    except (TypeError, ValueError) as ex:
        allowed = [member.value for member in enum_type]
        raise ProfileError(f"{label} must be one of {allowed}; got {value!r}") from ex


def _require_int(
    label: str,
    value: Any,
    *,
    minimum: int,
    maximum: int | None = None,
) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ProfileError(f"{label} must be an integer")
    if value < minimum or (maximum is not None and value > maximum):
        suffix = f"..{maximum}" if maximum is not None else " or greater"
        raise ProfileError(f"{label} must be {minimum}{suffix}; got {value}")


def _require_number(
    label: str,
    value: Any,
    *,
    minimum: float,
    maximum: float,
) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ProfileError(f"{label} must be a number")
    if not minimum <= float(value) <= maximum:
        raise ProfileError(f"{label} must be in [{minimum}, {maximum}]; got {value}")


def _require_bool(label: str, value: Any) -> None:
    if not isinstance(value, bool):
        raise ProfileError(f"{label} must be true or false")


def _require_text(label: str, value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProfileError(f"{label} must be a non-empty string")
    return value.strip()


def _optional_trimmed(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ProfileError("optional text fields must be null or non-empty strings")
    return value.strip()


def _normalize_sid(label: str, value: Any) -> str:
    sid = _require_text(label, value)
    if not _SID_RE.fullmatch(sid):
        raise ProfileError(f"{label} is not a valid SID: {sid!r}")
    return sid


def _normalize_biome(value: Any) -> str:
    biome = _require_text("biome", value).lower()
    if not re.fullmatch(r"[a-z][a-z0-9_-]*", biome):
        raise ProfileError(f"invalid biome name: {value!r}")
    return biome
