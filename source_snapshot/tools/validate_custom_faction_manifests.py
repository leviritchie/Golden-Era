#!/usr/bin/env python3
"""Validate HoMM3 custom faction manifests against current source maps.

This is the first registry-refactor guard. It does not mutate Core.zip or the
plugin payload; it checks that the new manifest source of truth matches the
current runtime donor maps and records donor collisions explicitly.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import math
import re
import sys
import zipfile
from collections import defaultdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))
from homm3_specialization_icon_keys import specialization_icon_key_for_kind
from validate_homm3_factory_bulwark_core_skill_contract import EXACT_SKILL_TEXT as FACTORY_BULWARK_EXACT_SKILL_TEXT
DEFAULT_MANIFEST_DIR = ROOT / "custom_factions"
DEFAULT_SOURCE_MECHANICS_DIR = DEFAULT_MANIFEST_DIR / "source_mechanics"
DEFAULT_HERO_OVERRIDE_DIR = DEFAULT_MANIFEST_DIR / "hero_overrides"
DEFAULT_ABILITY_OVERRIDE_DIR = DEFAULT_MANIFEST_DIR / "ability_overrides"
REGISTRY_SOURCE = ROOT / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod" / "Homm3CustomFactionRegistry.cs"
BUILDING_ICON_SPRITE_CACHE = (
    ROOT / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod" / "Homm3StrongholdBuildingIconSpriteCache.cs"
)
HOMM3_IMPORT_TABLE = ROOT / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod" / "homm3_import.json"
HOMM3_BUNDLE_PAYLOAD_CONTRACT = DEFAULT_MANIFEST_DIR / "contracts" / "homm3_bundle_payload_contract.json"
OFFLINE_PLUGIN_ROOT = ROOT / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod"
HOMM3_LAB_ASSET_RE = re.compile(r"Assets[/\\]CustomUnits[/\\]homm3_lab[/\\](?P<lab_sid>[^/\\]+)[/\\]")
VCMI_FORTRESS_TOWN_CONFIG = ROOT / "vcmi" / "Mods" / "third-upgrades" / "content" / "config" / "town-screen" / "fortress" / "factions.json"
_CORE_NAME_CACHE: dict[str, set[str]] = {}
_CORE_BYTES_CACHE: dict[str, dict[str, bytes]] = {}
_CORE_JSON_CACHE: dict[tuple[str, str], Any | None] = {}

VARIANT_LABELS = {
    "": "base",
    "_upg": "upgrade",
    "_upg_alt": "alternate_upgrade",
}
CUSTOM_BIOME_FACTIONS = {
    "Swamp": "homm3_fortress",
    "Tundra": "homm3_tower",
    "Hills": "homm3_rampart",
    "Wasteland": "homm3_stronghold",
    "Tropical": "homm3_cove",
    "Greenlands": "homm3_conflux",
    "Curselands": "homm3_necropolis",
    "Burrow": "homm3_dungeon",
    "Valleys": "homm3_castle",
    "Molten": "homm3_inferno",
    "Foundry": "homm3_factory",
    "Permafrost": "homm3_bulwark",
}
# Campaign ocean is native Sand tile 2 + waterMap 2 (experiments/campaign_port_poc/campaign_ocean.py),
# so the Golden Era-only "Water" tile 18 is no longer a required custom terrain row.
CUSTOM_TERRAIN_ONLY_BIOMES = {
    "Void": "Dirt",
}
CUSTOM_TERRAIN_ONLY_TILE_IDS = {
    "Void": 23,
}
FACTORY_4K_COORDINATE_BASIS_SOURCE = (
    "vcmi-top-left-800x374-on-3840x2160-factory-4k-outpaint-"
    "source-plate-preserved-right-bottom-generated"
)
HOMM3_CUSTOM_TOWN_BUILDINGS_CONSTRUCTION_SID = "homm3_custom_town_buildings_construction"
CUSTOM_TOWN_4K_FACTIONS = {
    "homm3_bulwark",
    "homm3_castle",
    "homm3_conflux",
    "homm3_cove",
    "homm3_dungeon",
    "homm3_factory",
    "homm3_fortress",
    "homm3_inferno",
    "homm3_necropolis",
    "homm3_rampart",
    "homm3_stronghold",
    "homm3_tower",
}
CUSTOM_BIOME_ARENA_DONORS = {
    "Swamp": "Grass",
    "Tundra": "Snow",
    "Hills": "Grass",
    "Wasteland": "Sand",
    "Tropical": "Sand",
    "Greenlands": "Grass",
    "Curselands": "Deathland",
    "Burrow": "Dirt",
    "Valleys": "Grass",
    "Molten": "Lava",
    "Foundry": "Sand",
    "Permafrost": "Snow",
    "Void": "Dirt",
}
RELEASE_BIOMES = {"Grass", "Sand", "Snow", "Autumn", "Dirt", "Lava", "Deathland"} | set(CUSTOM_BIOME_FACTIONS) | set(CUSTOM_TERRAIN_ONLY_BIOMES)
FORTRESS_THIRD_UPGRADE_ONLY_LAYERS = {
    "extraCapitol",
    "horde2",
    "dwellingUp2Lvl1",
    "dwellingUp2Lvl2",
    "dwellingUp2Lvl3",
    "dwellingUp2Lvl4",
    "dwellingUp2Lvl5",
    "dwellingUp2Lvl6",
    "dwellingUp2Lvl7",
}
FORTRESS_CORE_STRUCTURE_IDS = {
    "extraAnimation",
    "mageGuild1",
    "mageGuild2",
    "mageGuild3",
    "tavern",
    "shipyard",
    "fort",
    "citadel",
    "castle",
    "villageHall",
    "townHall",
    "cityHall",
    "capitol",
    "marketplace",
    "resourceSilo",
    "blacksmith",
    "special1",
    "horde1",
    "horde1Upgr",
    "ship",
    "special2",
    "special3",
    "grail",
    "dwellingLvl1",
    "dwellingLvl2",
    "dwellingLvl3",
    "dwellingLvl4",
    "dwellingLvl5",
    "dwellingLvl6",
    "dwellingLvl7",
    "dwellingUpLvl1",
    "dwellingUpLvl2",
    "dwellingUpLvl3",
    "dwellingUpLvl4",
    "dwellingUpLvl5",
    "dwellingUpLvl6",
    "dwellingUpLvl7",
}
FORTRESS_TOA_ALT_NAMES_BY_TIER = {
    1: "Gnoll Shaman",
    2: "Lizard Assassin",
    3: "Damsel Fly",
    4: "Basilisk Flamespitter",
    5: "Corrosive Gorgon",
    6: "Paokai",
    7: "Ruinous Hydra",
}
FORTRESS_TOA_ALT_STATS_BY_SID = {
    "h3_gnoll_upg_alt": {"hp": 6, "offence": 3, "defence": 7, "damageMin": 2, "damageMax": 3, "initiative": 5, "speed": 5, "cost": {"gold": 70}, "squadValue": 100},
    "h3_lizardman_upg_alt": {"hp": 15, "offence": 8, "defence": 6, "damageMin": 3, "damageMax": 5, "initiative": 8, "speed": 8, "ammo": 24, "cost": {"gold": 170}, "squadValue": 250},
    "h3_serpent_fly_upg_alt": {"hp": 20, "offence": 9, "defence": 9, "damageMin": 2, "damageMax": 5, "initiative": 11, "speed": 11, "cost": {"gold": 240}, "squadValue": 312},
    "h3_basilisk_upg_alt": {"hp": 40, "offence": 14, "defence": 10, "damageMin": 6, "damageMax": 10, "initiative": 7, "speed": 7, "cost": {"gold": 400}, "squadValue": 750},
    "h3_gorgon_upg_alt": {"hp": 70, "offence": 14, "defence": 14, "damageMin": 12, "damageMax": 16, "initiative": 7, "speed": 7, "cost": {"gold": 600}, "squadValue": 1040},
    "h3_wyvern_upg_alt": {"hp": 80, "offence": 14, "defence": 14, "damageMin": 14, "damageMax": 18, "initiative": 10, "speed": 10, "cost": {"gold": 1300}, "squadValue": 1950},
    "h3_hydra_upg_alt": {"hp": 220, "offence": 18, "defence": 24, "damageMin": 25, "damageMax": 45, "initiative": 10, "speed": 10, "cost": {"gold": 4000, "mercury": 2}, "squadValue": 6800},
}
FORTRESS_TOA_ALT_BEHAVIOR_BY_SID = {
    "h3_lizardman_upg_alt": {"abilities": ("poison_dot",), "forbiddenKeys": ("doubleRanged", "noRangePenalty")},
    "h3_serpent_fly_upg_alt": {"abilities": ("dispel_positive",)},
    "h3_gorgon_upg_alt": {"abilities": ("acid_debuff",), "forbiddenKeys": ("numCounters",)},
    "h3_wyvern_upg_alt": {"abilities": ()},
}
RELEASE_CORE_OVERLAY = ROOT / "tools" / "release_port" / "apply_release_core_overlay.py"
GENERIC_TOWN_LAYER_IDS = {
    "main",
    "bank",
    "wall",
    "tavern",
    "market",
    "artifactMarket",
    "magicGuild",
    "treasury",
    "resourceDepot",
    "resourceDepotLevel2",
    "trainingRange",
    "intelligenceAcademy",
    "goldenCalf",
}
EXPECTED_HOMM3_CITY_SCENE_BY_FACTION = {
    # All release custom factions share the spare owned cityFactory / EScene 26 world.
    "homm3_bulwark": "cityFactory",
    "homm3_castle": "cityFactory",
    "homm3_conflux": "cityFactory",
    "homm3_cove": "cityFactory",
    "homm3_dungeon": "cityFactory",
    "homm3_factory": "cityFactory",
    "homm3_fortress": "cityFactory",
    "homm3_inferno": "cityFactory",
    "homm3_necropolis": "cityFactory",
    "homm3_rampart": "cityFactory",
    "homm3_stronghold": "cityFactory",
    "homm3_tower": "cityFactory",
}

class Validation:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def error(self, message: str) -> None:
        self.errors.append(message)

    def warn(self, message: str) -> None:
        self.warnings.append(message)


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8-sig") as f:
        return json.load(f)


def load_jsonc(path: Path) -> Any:
    text = path.read_text(encoding="utf-8-sig")
    text = re.sub(r"//.*", "", text)
    return json.loads(text)


def load_manifests(manifest_dir: Path) -> list[tuple[Path, dict[str, Any]]]:
    manifests: list[tuple[Path, dict[str, Any]]] = []
    for path in sorted(manifest_dir.glob("homm3_*.json")):
        data = load_json(path)
        identity = data.get("identity") if isinstance(data, dict) else None
        if not isinstance(identity, dict) or not isinstance(identity.get("factionSid"), str):
            # Skip non-faction catalogs such as tools/homm3_import/faction_concepts/homm3_neutral.json.
            continue
        manifests.append((path, data))
    return manifests


def release_promotion_blocked(manifest: dict[str, Any]) -> bool:
    validation = manifest.get("validation") or {}
    return validation.get("releasePromotionBlocked") is True


def core_overlay_enabled(manifest: dict[str, Any]) -> bool:
    validation = manifest.get("validation") or {}
    value = validation.get("coreOverlayEnabled")
    if isinstance(value, bool):
        return value
    return not release_promotion_blocked(manifest)


def report_release_gap(manifest: dict[str, Any], v: Validation, message: str) -> None:
    if release_promotion_blocked(manifest):
        v.warn(message)
    else:
        v.error(message)


def manifest_validation_status(manifest: dict[str, Any]) -> str:
    validation = manifest.get("validation") or {}
    status = validation.get("status", "release_ready")
    return status if isinstance(status, str) and status else "release_ready"


def manifest_is_scaffold(manifest: dict[str, Any]) -> bool:
    return manifest_validation_status(manifest) in {"scaffold", "asset_pending", "basic_enabled"}


def manifest_requires_runtime_mirror(manifest: dict[str, Any]) -> bool:
    validation = manifest.get("validation") or {}
    return validation.get("runtimeMirrorRequired", True) is not False


def report_missing_release_surface(manifest: dict[str, Any], v: Validation, message: str) -> None:
    if manifest_is_scaffold(manifest) or release_promotion_blocked(manifest):
        v.warn(message)
    else:
        v.error(message)


def unit_sid_for_variant(line: dict[str, Any], suffix: str) -> str:
    variant_sids = line.get("variantSids")
    if isinstance(variant_sids, dict):
        sid = variant_sids.get(suffix)
        if isinstance(sid, str) and sid:
            return sid
    return line["baseSid"] + suffix


def additional_recruitment_lines(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    value = manifest.get("additionalRecruitmentLines")
    if not isinstance(value, list):
        return []
    return [line for line in value if isinstance(line, dict)]


def all_unit_lines(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    primary = manifest.get("unitLines")
    primary_lines = [line for line in primary if isinstance(line, dict)] if isinstance(primary, list) else []
    return primary_lines + additional_recruitment_lines(manifest)


def expand_units(manifest: dict[str, Any]) -> dict[str, str]:
    variants = manifest.get("unitVariants", ["", "_upg", "_upg_alt"])
    expanded: dict[str, str] = {}
    for line in all_unit_lines(manifest):
        donor_base = line["donorBaseSid"]
        for suffix in variants:
            custom_sid = unit_sid_for_variant(line, suffix)
            donor_sid = donor_base + suffix
            expanded[custom_sid] = donor_sid
    return expanded


def parse_registry_unit_lines(path: Path) -> dict[str, tuple[str | None, str, str | None, dict[str, str]]]:
    text = path.read_text(encoding="utf-8-sig")
    line_re = re.compile(r"new\s+UnitLine\((?P<body>.*?)\)", re.S)
    result: dict[str, tuple[str | None, str, str | None, dict[str, str]]] = {}
    for match in line_re.finditer(text):
        body = match.group("body")
        strings = re.findall(r'"([^"]*)"', body)
        if len(strings) < 3 or not strings[0].startswith("h3_"):
            continue
        custom_base = strings[0]
        donor_faction = strings[1]
        donor_base = strings[2]
        donor_prefab = None
        if len(strings) > 3 and "upgradeSid:" not in body and "alternateUpgradeSid:" not in body:
            donor_prefab = strings[3]
        named_prefab = re.search(r'donorPrefabBaseSid:\s*"(?P<value>[^"]+)"', body)
        if named_prefab:
            donor_prefab = named_prefab.group("value")
        variant_sids = {"": custom_base}
        for suffix, name in (("_upg", "upgradeSid"), ("_upg_alt", "alternateUpgradeSid")):
            named_variant = re.search(rf'{name}:\s*"(?P<value>[^"]+)"', body)
            if named_variant:
                variant_sids[suffix] = named_variant.group("value")
        result[custom_base] = (donor_faction, donor_base, donor_prefab, variant_sids)
    return result


def parse_registry_source(path: Path) -> dict[str, str]:
    expanded: dict[str, str] = {}
    for custom_base, (_donor_faction, donor_base, _donor_prefab, variant_sids) in parse_registry_unit_lines(path).items():
        for suffix in VARIANT_LABELS:
            expanded[variant_sids.get(suffix, custom_base + suffix)] = donor_base + suffix
    return expanded


def validate_manifest_shape(path: Path, manifest: dict[str, Any], v: Validation) -> None:
    identity = manifest.get("identity") or {}
    faction_sid = identity.get("factionSid", path.stem)
    city_sid = identity.get("citySid")
    if not faction_sid:
        v.error(f"{path}: identity.factionSid is required")
    if not city_sid:
        v.error(f"{path}: identity.citySid is required")
    if manifest.get("schemaVersion") != 1:
        v.error(f"{path}: schemaVersion must be 1")

    unit_lines = manifest.get("unitLines")
    if not isinstance(unit_lines, list) or len(unit_lines) != 7:
        v.error(f"{faction_sid}: expected exactly 7 unitLines")
        return

    variants = manifest.get("unitVariants", [])
    if variants != ["", "_upg", "_upg_alt"]:
        v.error(f"{faction_sid}: unitVariants must be ['', '_upg', '_upg_alt']")

    tiers = [line.get("tier") for line in unit_lines]
    if tiers != list(range(1, 8)):
        v.error(f"{faction_sid}: unitLines tiers must be 1..7 in order, got {tiers}")

    donor_faction = identity.get("donorFactionSid")
    for line in unit_lines:
        line_donor_faction = line.get("donorFactionSid", donor_faction)
        if not isinstance(line_donor_faction, str) or not line_donor_faction:
            v.error(f"{faction_sid}: unit line tier {line.get('tier')} must resolve a donorFactionSid")
        if not line.get("baseSid") or not line.get("donorBaseSid"):
            v.error(f"{faction_sid}: unit line tier {line.get('tier')} must declare baseSid and donorBaseSid")
        donor_prefab_base = line.get("donorPrefabBaseSid")
        if donor_prefab_base is not None and (not isinstance(donor_prefab_base, str) or not donor_prefab_base):
            v.error(f"{faction_sid}: unit line tier {line.get('tier')} donorPrefabBaseSid must be a non-empty string when present")
        if "names" in line:
            names = line.get("names")
            if not isinstance(names, list) or len(names) != len(variants) or any(not isinstance(name, str) or not name for name in names):
                v.error(f"{faction_sid}: unit line tier {line.get('tier')} names must be {len(variants)} non-empty strings")
            elif faction_sid == "homm3_fortress":
                expected_alt_name = FORTRESS_TOA_ALT_NAMES_BY_TIER.get(line.get("tier"))
                alt_name = names[variants.index("_upg_alt")] if "_upg_alt" in variants else None
                upg_name = names[variants.index("_upg")] if "_upg" in variants else None
                if expected_alt_name is not None and alt_name != expected_alt_name:
                    v.error(
                        f"{faction_sid}: unit line tier {line.get('tier')} _upg_alt name must match "
                        f"Tears of Ashan source name {expected_alt_name!r}, got {alt_name!r}"
                    )
                if upg_name == alt_name:
                    v.error(
                        f"{faction_sid}: unit line tier {line.get('tier')} _upg_alt name must not duplicate "
                        f"the standard upgrade name {upg_name!r}"
                    )
        variant_sids = line.get("variantSids")
        if variant_sids is not None:
            if not isinstance(variant_sids, dict):
                v.error(f"{faction_sid}: unit line tier {line.get('tier')} variantSids must be an object when present")
            else:
                for suffix, sid in variant_sids.items():
                    if suffix not in variants:
                        v.error(f"{faction_sid}: unit line tier {line.get('tier')} variantSids has unknown suffix {suffix!r}")
                    if not isinstance(sid, str) or not sid:
                        v.error(f"{faction_sid}: unit line tier {line.get('tier')} variantSids.{suffix} must be a non-empty string")

    additional = manifest.get("additionalRecruitmentLines")
    if additional is None:
        additional = []
    elif not isinstance(additional, list):
        v.error(f"{faction_sid}: additionalRecruitmentLines must be a list when present")
        additional = []

    primary_buildings = {f"Build_Tier_{tier}" for tier in range(1, 8)}
    primary_slots = {f"Tier_{tier}" for tier in range(1, 8)}
    direct_prefix = ((manifest.get("coreOverlay") or {}).get("directDwellingPrefix") or "")
    primary_dwellings = {f"{direct_prefix}{tier}" for tier in range(1, 8)}
    seen_line_ids: set[str] = set()
    seen_buildings = set(primary_buildings)
    seen_slots = set(primary_slots)
    seen_dwellings = set(primary_dwellings)
    seen_images = set((manifest.get("runtime") or {}).get("dwellingBillboardImages") or [])
    for index, line in enumerate(additional):
        label = f"{faction_sid}: additionalRecruitmentLines[{index}]"
        if not isinstance(line, dict):
            v.error(f"{label} must be an object")
            continue
        tier = line.get("tier")
        if isinstance(tier, bool) or not isinstance(tier, int) or tier < 1 or tier > 7:
            v.error(f"{label}.tier must be an integer from 1 through 7")
        for key in ("lineId", "baseSid", "donorBaseSid", "recruitmentSlotSid", "cityBuildingSid", "directDwellingSid", "donorDwellingSid", "dwellingBillboardImage"):
            if not isinstance(line.get(key), str) or not line[key].strip():
                v.error(f"{label}.{key} must be a non-empty string")
        donor_faction = line.get("donorFactionSid", identity.get("donorFactionSid"))
        if not isinstance(donor_faction, str) or not donor_faction:
            v.error(f"{label} must resolve a donorFactionSid")
        names = line.get("names")
        if not isinstance(names, list) or len(names) != len(variants) or any(not isinstance(name, str) or not name for name in names):
            v.error(f"{label}.names must be {len(variants)} non-empty strings")
        variant_sids = line.get("variantSids")
        if variant_sids is not None:
            if not isinstance(variant_sids, dict):
                v.error(f"{label}.variantSids must be an object when present")
            else:
                for suffix, sid in variant_sids.items():
                    if suffix not in variants:
                        v.error(f"{label}.variantSids has unknown suffix {suffix!r}")
                    if not isinstance(sid, str) or not sid:
                        v.error(f"{label}.variantSids.{suffix} must be a non-empty string")
        line_id = line.get("lineId")
        if isinstance(line_id, str):
            if not re.fullmatch(r"[a-z][a-z0-9_]*", line_id):
                v.error(f"{label}.lineId must be a lowercase manifest identifier")
            if line_id in seen_line_ids:
                v.error(f"{label}.lineId duplicates {line_id}")
            seen_line_ids.add(line_id)
        recruitment_slot = line.get("recruitmentSlotSid")
        if isinstance(recruitment_slot, str):
            if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", recruitment_slot):
                v.error(f"{label}.recruitmentSlotSid must be a native scene-slot identifier")
            if recruitment_slot in seen_slots:
                v.error(f"{label}.recruitmentSlotSid duplicates {recruitment_slot}")
            seen_slots.add(recruitment_slot)
        building_sid = line.get("cityBuildingSid")
        if isinstance(building_sid, str):
            if not re.fullmatch(r"Build_[A-Za-z0-9_]+", building_sid):
                v.error(f"{label}.cityBuildingSid must be a Build_* SID")
            if building_sid in seen_buildings:
                v.error(f"{label}.cityBuildingSid duplicates {building_sid}")
            seen_buildings.add(building_sid)
        direct_dwelling_sid = line.get("directDwellingSid")
        if isinstance(direct_dwelling_sid, str):
            if not direct_dwelling_sid.startswith("barracks_"):
                v.error(f"{label}.directDwellingSid must be a barracks_* SID")
            if direct_dwelling_sid in seen_dwellings:
                v.error(f"{label}.directDwellingSid duplicates {direct_dwelling_sid}")
            seen_dwellings.add(direct_dwelling_sid)
        donor_dwelling_sid = line.get("donorDwellingSid")
        if isinstance(donor_dwelling_sid, str) and not donor_dwelling_sid.startswith("barracks_"):
            v.error(f"{label}.donorDwellingSid must be a barracks_* SID")
        image_name = line.get("dwellingBillboardImage")
        if isinstance(image_name, str):
            if image_name.split("/", 1)[0].lower().startswith("avw"):
                v.error(f"{label}.dwellingBillboardImage must be a dwelling/generator frame, not AVW")
            if image_name in seen_images:
                v.error(f"{label}.dwellingBillboardImage duplicates {image_name}")
            seen_images.add(image_name)

    for line in all_unit_lines(manifest):
        branch_family = line.get("branchFamily")
        if branch_family is not None and (not isinstance(branch_family, str) or not branch_family.strip()):
            v.error(f"{faction_sid}: unit line {line.get('baseSid')!r} branchFamily must be a non-empty string when present")
        if faction_sid == "homm3_factory" and branch_family not in {"natural", "industrial"}:
            v.error(
                f"{faction_sid}: unit line {line.get('baseSid')!r} branchFamily must be exactly 'natural' or 'industrial'"
            )

    recruitment = manifest.get("recruitmentBaseSids")
    expected_recruitment = [line.get("baseSid") for line in unit_lines]
    if recruitment != expected_recruitment:
        v.error(f"{faction_sid}: recruitmentBaseSids must match unitLines baseSid order")

    expanded = expand_units(manifest)
    expected_expanded = (7 + len(additional)) * len(variants)
    if len(expanded) != expected_expanded:
        v.error(f"{faction_sid}: expected {expected_expanded} expanded unit mappings, got {len(expanded)}")

    squad_replacements = (manifest.get("squadTree") or {}).get("unitReplacements", {})
    if not isinstance(squad_replacements, dict):
        v.error(f"{faction_sid}: squadTree.unitReplacements must be an object when present")
    else:
        for source_sid, target_sid in squad_replacements.items():
            if not isinstance(source_sid, str) or not source_sid:
                v.error(f"{faction_sid}: squadTree.unitReplacements keys must be non-empty strings")
            if not isinstance(target_sid, str) or not target_sid:
                v.error(f"{faction_sid}: squadTree.unitReplacements values must be non-empty strings")
            elif target_sid not in expanded:
                v.error(f"{faction_sid}: squadTree.unitReplacements target {target_sid} is not one of the manifest unit SIDs")

    release_scaffold = manifest.get("releaseScaffold", {})
    if not isinstance(release_scaffold, dict):
        v.error(f"{faction_sid}: releaseScaffold must be an object when present")
    elif release_scaffold:
        for key in ("biome", "citySceneName", "factionIcon", "factionLawIcon", "lawIcon"):
            if not isinstance(release_scaffold.get(key), str) or not release_scaffold.get(key):
                v.error(f"{faction_sid}: releaseScaffold.{key} must be a non-empty string")
        expected_city_scene_name = EXPECTED_HOMM3_CITY_SCENE_BY_FACTION.get(faction_sid)
        if expected_city_scene_name is not None and release_scaffold.get("citySceneName") != expected_city_scene_name:
            v.error(
                f"{faction_sid}: releaseScaffold.citySceneName must be the expected city scene identity "
                f"{expected_city_scene_name!r}, got {release_scaffold.get('citySceneName')!r}"
            )
        biome = release_scaffold.get("biome")
        if isinstance(biome, str) and biome not in RELEASE_BIOMES:
            v.error(f"{faction_sid}: releaseScaffold.biome {biome!r} is not a known release biome")

    search_tokens = manifest.get("searchTokens", [])
    if not isinstance(search_tokens, list):
        v.error(f"{faction_sid}: searchTokens must be a list when present")
    else:
        seen_tokens: set[str] = set()
        for token in search_tokens:
            if not isinstance(token, str) or not token:
                v.error(f"{faction_sid}: searchTokens entries must be non-empty strings")
                continue
            if token in seen_tokens:
                v.error(f"{faction_sid}: duplicate searchTokens entry {token}")
            seen_tokens.add(token)

    heroes = manifest.get("heroes") or {}
    if heroes.get("count") not in (16, 18):
        v.error(f"{faction_sid}: heroes.count must be 16 or 18")
    if heroes.get("specializationsRequired") is not True:
        v.error(f"{faction_sid}: heroes.specializationsRequired must be true")
    if "names" in heroes:
        hero_names = heroes.get("names")
        if not isinstance(hero_names, list) or len(hero_names) != heroes.get("count") or any(not isinstance(name, str) or not name for name in hero_names):
            v.error(f"{faction_sid}: heroes.names must contain one non-empty string per hero")

    overlay = manifest.get("coreOverlay") or {}
    for key in ("factionJson", "cityLogic", "lawsTable", "squadTree", "heroSubClasses", "heroSpecializations"):
        if not overlay.get(key):
            v.error(f"{faction_sid}: coreOverlay.{key} is required")
    if overlay.get("directCityMapObject") != city_sid:
        v.error(f"{faction_sid}: coreOverlay.directCityMapObject must match identity.citySid")
    direct_dwelling_prefix = overlay.get("directDwellingPrefix")
    if not isinstance(direct_dwelling_prefix, str) or not direct_dwelling_prefix.startswith("barracks_") or not direct_dwelling_prefix.endswith("_"):
        v.error(f"{faction_sid}: coreOverlay.directDwellingPrefix must be a barracks prefix ending in '_'")

    runtime = manifest.get("runtime")
    if not isinstance(runtime, dict):
        v.error(f"{faction_sid}: runtime must be an object")
        runtime = {}
    for key in ("displayName", "description"):
        value = runtime.get(key)
        if not isinstance(value, str) or not value.strip():
            v.error(f"{faction_sid}: runtime.{key} must be a non-empty string")
    if runtime.get("customToDonorSource") != "manifest":
        v.error(f"{faction_sid}: runtime.customToDonorSource must be manifest")
    if runtime.get("allowGlobalDonorReverseLookup") is not False:
        v.error(f"{faction_sid}: runtime.allowGlobalDonorReverseLookup must be false")
    if runtime.get("reverseDonorLookup") != "context_required":
        v.error(f"{faction_sid}: runtime.reverseDonorLookup must be context_required")
    city_map_height = runtime.get("cityMapBillboardHeight")
    if not isinstance(city_map_height, (int, float)) or city_map_height <= 0:
        v.error(f"{faction_sid}: runtime.cityMapBillboardHeight must be a positive number")
    dwelling_images = runtime.get("dwellingBillboardImages")
    if not isinstance(dwelling_images, list) or len(dwelling_images) != 7:
        v.error(f"{faction_sid}: runtime.dwellingBillboardImages must contain seven tier image directory names")
    else:
        seen_images: set[str] = set()
        for image_name in dwelling_images:
            if not isinstance(image_name, str) or not image_name.strip():
                v.error(f"{faction_sid}: runtime.dwellingBillboardImages entries must be non-empty strings")
                continue
            folder_name = image_name.split("/", 1)[0].lower()
            if folder_name.startswith("avw"):
                v.error(f"{faction_sid}: runtime.dwellingBillboardImages entry {image_name} is a wandering-creature AVW frame; use a dwelling/generator map-object frame such as AVG* or a source-declared mapObjects/dwellings DEF")
            if image_name in seen_images:
                v.error(f"{faction_sid}: duplicate runtime.dwellingBillboardImages entry {image_name}")
            seen_images.add(image_name)
    donor_prefixes = runtime.get("dwellingDonorPrefixes")
    if not isinstance(donor_prefixes, list) or not donor_prefixes:
        v.error(f"{faction_sid}: runtime.dwellingDonorPrefixes must list context-gated donor barracks prefixes")
    else:
        seen_prefixes: set[str] = set()
        for prefix in donor_prefixes:
            if not isinstance(prefix, str) or not prefix.startswith("barracks_") or not prefix.endswith("_"):
                v.error(f"{faction_sid}: invalid dwelling donor prefix {prefix!r}")
                continue
            if prefix in seen_prefixes:
                v.error(f"{faction_sid}: duplicate dwelling donor prefix {prefix}")
            seen_prefixes.add(prefix)

    assets = manifest.get("assets") or {}
    for key in ("factionIcon", "factionCard", "cityIcon"):
        asset_path = assets.get(key)
        if not asset_path:
            v.error(f"{faction_sid}: assets.{key} is required")
            continue
        resolved = ROOT / asset_path
        if not resolved.is_file():
            report_missing_release_surface(manifest, v, f"{faction_sid}: assets.{key} file is missing: {asset_path}")
    dwelling_folder = assets.get("dwellingBillboardFolder")
    if not isinstance(dwelling_folder, str) or not dwelling_folder:
        v.error(f"{faction_sid}: assets.dwellingBillboardFolder is required")
    else:
        resolved_folder = ROOT / dwelling_folder
        if not resolved_folder.is_dir():
            report_missing_release_surface(manifest, v, f"{faction_sid}: assets.dwellingBillboardFolder directory is missing: {dwelling_folder}")
        else:
            billboard_frames = sorted(resolved_folder.glob("*.dir/00_00.png"))
            required_frame_count = 7 + len(additional_recruitment_lines(manifest))
            if len(billboard_frames) < required_frame_count:
                report_missing_release_surface(
                    manifest,
                    v,
                    f"{faction_sid}: assets.dwellingBillboardFolder must contain at least {required_frame_count} direct dwelling "
                    f"00_00.png frames, got {len(billboard_frames)}"
                )
            for index, line in enumerate(additional_recruitment_lines(manifest)):
                image_path = resolved_folder / line["dwellingBillboardImage"]
                if not image_path.is_file():
                    report_missing_release_surface(
                        manifest,
                        v,
                        f"{faction_sid}: additionalRecruitmentLines[{index}].dwellingBillboardImage is missing: {image_path}",
                    )
    validate_homm3_town_asset_root(ROOT, manifest, v, deployed=False)


def load_python_literal_constants(path: Path, constant_names: set[str], v: Validation) -> dict[str, Any | None]:
    try:
        module = ast.parse(path.read_text(encoding="utf-8"))
    except OSError as exc:
        v.error(f"could not read {path}: {exc}")
        return {name: None for name in constant_names}
    except SyntaxError as exc:
        v.error(f"could not parse {path}: {exc}")
        return {name: None for name in constant_names}

    values: dict[str, Any | None] = {}
    found: set[str] = set()
    for node in module.body:
        if not isinstance(node, ast.Assign):
            continue
        matching_names = {
            target.id
            for target in node.targets
            if isinstance(target, ast.Name) and target.id in constant_names and target.id not in found
        }
        if not matching_names:
            continue
        found.update(matching_names)
        try:
            value = ast.literal_eval(node.value)
        except (ValueError, SyntaxError) as exc:
            for constant_name in sorted(matching_names):
                v.error(f"{path.name}: {constant_name} must remain a literal validator-readable constant: {exc}")
                values[constant_name] = None
            continue
        for constant_name in matching_names:
            values[constant_name] = value
    for constant_name in sorted(constant_names - found):
        v.error(f"{path.name}: missing validator-required constant {constant_name}")
        values[constant_name] = None
    return values


def validate_fortress_core_generator_toa_overlay(v: Validation) -> None:
    constants = load_python_literal_constants(
        RELEASE_CORE_OVERLAY,
        {
            "FORTRESS_UNIT_TARGET_STATS",
            "FORTRESS_UNIT_DISPLAY_NAMES",
            "FORTRESS_UNIT_VARIANT_BEHAVIOR_OVERRIDES",
        },
        v,
    )
    stats = constants.get("FORTRESS_UNIT_TARGET_STATS")
    display_names = constants.get("FORTRESS_UNIT_DISPLAY_NAMES")
    behaviors = constants.get("FORTRESS_UNIT_VARIANT_BEHAVIOR_OVERRIDES")
    if not isinstance(stats, dict) or not isinstance(display_names, dict) or not isinstance(behaviors, dict):
        return
    expected_names_by_sid = {
        sid: FORTRESS_TOA_ALT_NAMES_BY_TIER[tier]
        for tier, sid in enumerate(FORTRESS_TOA_ALT_STATS_BY_SID.keys(), start=1)
    }
    for custom_sid, expected_name in expected_names_by_sid.items():
        if display_names.get(custom_sid) != expected_name:
            v.error(
                f"fortress generator: {custom_sid} display name must match Tears of Ashan "
                f"source name {expected_name!r}, got {display_names.get(custom_sid)!r}"
            )
    for custom_sid, expected_stats in FORTRESS_TOA_ALT_STATS_BY_SID.items():
        row = stats.get(custom_sid)
        if not isinstance(row, dict):
            v.error(f"fortress generator: missing target stats for {custom_sid}")
            continue
        for key, expected_value in expected_stats.items():
            if row.get(key) != expected_value:
                v.error(
                    f"fortress generator: {custom_sid} target stat {key} must match Tears of Ashan "
                    f"{expected_value!r}, got {row.get(key)!r}"
                )
    for custom_sid, expected_behavior in FORTRESS_TOA_ALT_BEHAVIOR_BY_SID.items():
        row = behaviors.get(custom_sid)
        if not isinstance(row, dict):
            v.error(f"fortress generator: missing behavior override for {custom_sid}")
            continue
        if "abilities" in expected_behavior and row.get("abilities", ()) != expected_behavior["abilities"]:
            v.error(
                f"fortress generator: {custom_sid} abilities must be {expected_behavior['abilities']!r}, "
                f"got {row.get('abilities', ())!r}"
            )
        for key in expected_behavior.get("forbiddenKeys", ()):
            if key in row:
                v.error(f"fortress generator: {custom_sid} must not retain stale third-upgrade behavior key {key!r}")


def validate_homm3_town_asset_root(base: Path, manifest: dict[str, Any], v: Validation, deployed: bool) -> None:
    faction_sid = manifest["identity"]["factionSid"]
    assets = manifest.get("assets") or {}
    town_folder = resolve_manifest_asset_path(base, assets.get("townSceneFolder"), deployed)
    icon_folder = resolve_manifest_asset_path(base, assets.get("buildingIconFolder"), deployed)
    label = "deployed plugin" if deployed else "source"

    if town_folder is None:
        v.error(f"{faction_sid}: assets.townSceneFolder is required")
        return
    if not town_folder.is_dir():
        v.error(f"{faction_sid}: {label} townSceneFolder is missing: {town_folder}")
        return

    layers = town_folder / "layers"
    positions_path = layers / "positions.json"
    building_map_path = layers / "building_layer_map.json"
    for required in (positions_path, building_map_path):
        if not required.is_file():
            v.error(f"{faction_sid}: {label} town layer file is missing: {required}")

    if positions_path.is_file():
        try:
            positions = load_json(positions_path)
            layer_entries = positions.get("layers")
            if not isinstance(layer_entries, list) or not layer_entries:
                v.error(f"{faction_sid}: {label} positions.json must contain a non-empty layers array")
            else:
                basis = positions.get("coordinateBasis")
                valid_basis_sources = {
                    "vcmi-top-left-800x374-on-black-800x600-town-plate-uniform-scale-left-aligned"
                }
                if faction_sid in CUSTOM_TOWN_4K_FACTIONS:
                    short = faction_sid.removeprefix("homm3_")
                    valid_basis_sources.add(
                        f"vcmi-top-left-800x374-on-3840x2160-{short}-4k-outpaint-"
                        "source-plate-preserved-right-bottom-generated"
                    )
                if faction_sid == "homm3_factory":
                    valid_basis_sources.add(FACTORY_4K_COORDINATE_BASIS_SOURCE)
                if not isinstance(basis, dict) or basis.get("source") not in valid_basis_sources:
                    v.error(f"{faction_sid}: {label} positions.json missing prebaked HoMM3 town coordinateBasis")
                if faction_sid == "homm3_fortress":
                    validate_fortress_positions_against_vcmi(faction_sid, label, positions_path, layer_entries, v)
                for entry in layer_entries:
                    if not isinstance(entry, dict) or not isinstance(entry.get("id"), str) or not entry["id"]:
                        v.error(f"{faction_sid}: {label} positions.json has a layer without an id")
                        continue
                    layer_id = entry["id"]
                    sprite_name = entry.get("sprite")
                    if not isinstance(sprite_name, str) or not sprite_name:
                        sprite_name = f"{layer_id}.png"
                    if not (layers / sprite_name).is_file():
                        v.error(f"{faction_sid}: {label} town layer PNG is missing: {layers / sprite_name}")
                    for key in ("reference_x", "reference_y", "reference_w", "reference_h"):
                        if not isinstance(entry.get(key), (int, float)):
                            v.error(f"{faction_sid}: {label} positions.json layer {layer_id} missing numeric prebaked {key}")
        except json.JSONDecodeError as ex:
            v.error(f"{faction_sid}: {label} positions.json is invalid JSON: {ex}")

    if building_map_path.is_file():
        try:
            building_map = load_json(building_map_path).get("buildingLayerIds")
            if not isinstance(building_map, dict):
                v.error(f"{faction_sid}: {label} building_layer_map.json must contain buildingLayerIds")
            else:
                layer_ids = set()
                if positions_path.is_file():
                    try:
                        positions = load_json(positions_path)
                        for entry in positions.get("layers") or []:
                            if isinstance(entry, dict) and isinstance(entry.get("id"), str):
                                layer_ids.add(entry["id"])
                    except json.JSONDecodeError:
                        pass
                if faction_sid == "homm3_fortress":
                    validate_fortress_building_map_against_vcmi(faction_sid, label, building_map_path, building_map, layer_ids, v)
                for required_sid in ("Build_Main", "Build_Tier_1", "Build_Tier_2", "Build_Tier_3", "Build_Tier_4", "Build_Tier_5", "Build_Tier_6", "Build_Tier_7"):
                    if required_sid not in building_map:
                        v.error(f"{faction_sid}: {label} building_layer_map.json missing {required_sid}")
        except json.JSONDecodeError as ex:
            v.error(f"{faction_sid}: {label} building_layer_map.json is invalid JSON: {ex}")

    if faction_sid != "homm3_fortress":
        return

    if icon_folder is None:
        v.error(f"{faction_sid}: assets.buildingIconFolder is required")
        return
    if not icon_folder.is_dir():
        v.error(f"{faction_sid}: {label} buildingIconFolder is missing: {icon_folder}")
        return

    source_maps = sorted(icon_folder.glob("*_source_map.json"))
    if not source_maps:
        v.error(f"{faction_sid}: {label} buildingIconFolder has no *_source_map.json")
        return
    try:
        source_map = load_json(source_maps[0])
        folder = source_map.get("folder")
        mapping = source_map.get("map")
        if not isinstance(folder, str) or not folder:
            v.error(f"{faction_sid}: {label} building icon source map must declare folder")
            return
        frame_root = icon_folder / folder
        if not frame_root.is_dir():
            v.error(f"{faction_sid}: {label} building icon frame folder is missing: {frame_root}")
            return
        if not isinstance(mapping, dict) or not mapping:
            v.error(f"{faction_sid}: {label} building icon source map must contain a non-empty map")
            return
        for building_sid, levels in mapping.items():
            if not isinstance(levels, dict) or not levels:
                v.error(f"{faction_sid}: {label} building icon map for {building_sid} must contain levels")
                continue
            for level, value in levels.items():
                if isinstance(value, str):
                    frame_folder = frame_root
                    filename = value
                elif isinstance(value, dict):
                    filename = value.get("file")
                    custom_folder = value.get("folder")
                    frame_folder = icon_folder / custom_folder if isinstance(custom_folder, str) and custom_folder else frame_root
                else:
                    filename = None
                    frame_folder = frame_root
                if not isinstance(filename, str) or not filename:
                    v.error(f"{faction_sid}: {label} building icon map {building_sid}:{level} has an invalid filename")
                    continue
                if not (frame_folder / filename).is_file():
                    v.error(f"{faction_sid}: {label} building icon PNG is missing: {frame_folder / filename}")
    except json.JSONDecodeError as ex:
        v.error(f"{faction_sid}: {label} building icon source map is invalid JSON: {ex}")


def load_vcmi_fortress_structures(v: Validation) -> dict[str, dict[str, Any]]:
    if not VCMI_FORTRESS_TOWN_CONFIG.is_file():
        v.warn(f"homm3_fortress: VCMI Fortress town-screen config is missing: {VCMI_FORTRESS_TOWN_CONFIG}")
        return {}
    try:
        doc = load_jsonc(VCMI_FORTRESS_TOWN_CONFIG)
    except json.JSONDecodeError as ex:
        v.error(f"{VCMI_FORTRESS_TOWN_CONFIG}: invalid JSON/JSONC: {ex}")
        return {}
    structures = (((doc.get("core:fortress") or {}).get("town") or {}).get("structures") or {})
    if not isinstance(structures, dict):
        v.error(f"{VCMI_FORTRESS_TOWN_CONFIG}: missing core:fortress.town.structures")
        return {}
    result: dict[str, dict[str, Any]] = {}
    for structure_id, value in structures.items():
        if isinstance(structure_id, str) and isinstance(value, dict) and isinstance(value.get("x"), int) and isinstance(value.get("y"), int):
            result[structure_id] = value
    return result


def vcmi_base_fortress_structures(structures: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {sid: data for sid, data in structures.items() if sid not in FORTRESS_THIRD_UPGRADE_ONLY_LAYERS}


def validate_fortress_positions_against_vcmi(
    faction_sid: str,
    label: str,
    positions_path: Path,
    layer_entries: list[Any],
    v: Validation,
) -> None:
    vcmi_structures = load_vcmi_fortress_structures(v)
    if not vcmi_structures:
        return
    vcmi_base = vcmi_base_fortress_structures(vcmi_structures)
    valid_structures = set(vcmi_structures) | FORTRESS_CORE_STRUCTURE_IDS
    positioned: dict[str, dict[str, Any]] = {}
    all_xy_zero = True
    generic_ids: list[str] = []
    unknown_structures: list[str] = []

    for entry in layer_entries:
        if not isinstance(entry, dict):
            continue
        layer_id = entry.get("id")
        if not isinstance(layer_id, str) or not layer_id:
            continue
        structure = entry.get("structure")
        if isinstance(structure, str) and structure:
            positioned[structure] = entry
            if structure not in valid_structures:
                unknown_structures.append(structure)
        positioned[layer_id] = entry
        if entry.get("x") != 0 or entry.get("y") != 0:
            all_xy_zero = False
        if layer_id in GENERIC_TOWN_LAYER_IDS:
            generic_ids.append(layer_id)

    if generic_ids:
        v.error(f"{faction_sid}: {label} positions.json uses generic/non-Fortress layer ids despite VCMI Fortress structures: {', '.join(sorted(generic_ids))}")
    if unknown_structures:
        v.error(f"{faction_sid}: {label} positions.json has structures not present in local VCMI Fortress/core source data: {', '.join(sorted(set(unknown_structures)))}")
    if vcmi_base and all_xy_zero:
        v.error(f"{faction_sid}: {label} positions.json is all-zero even though local VCMI Fortress base placement exists in {VCMI_FORTRESS_TOWN_CONFIG}")
    if vcmi_base:
        positioned_base = sorted(set(positioned) & set(vcmi_base))
        if not positioned_base:
            v.error(
                f"{faction_sid}: {label} positions.json is third-upgrade-only; local VCMI Fortress base placement exists "
                f"for {', '.join(sorted(vcmi_base))}"
            )
        missing_base = sorted(set(vcmi_base) - set(positioned))
        if missing_base:
            v.error(f"{faction_sid}: {label} positions.json missing VCMI Fortress base placement rows: {', '.join(missing_base)}")

    for layer_id, entry in positioned.items():
        vcmi_entry = vcmi_structures.get(layer_id)
        if not vcmi_entry:
            continue
        for axis in ("x", "y", "z"):
            expected = vcmi_entry.get(axis, 0)
            actual = entry.get(axis, 0)
            if actual != expected:
                v.error(
                    f"{faction_sid}: {label} positions.json layer {layer_id} {axis}={actual!r} does not match "
                    f"local VCMI Fortress {axis}={expected!r}"
                )


def validate_fortress_building_map_against_vcmi(
    faction_sid: str,
    label: str,
    building_map_path: Path,
    building_map: dict[str, Any],
    layer_ids: set[str],
    v: Validation,
) -> None:
    vcmi_structures = load_vcmi_fortress_structures(v)
    if not vcmi_structures:
        return
    vcmi_base = vcmi_base_fortress_structures(vcmi_structures)
    mapped_layer_ids = {value for value in building_map.values() if isinstance(value, str)}
    if mapped_layer_ids & GENERIC_TOWN_LAYER_IDS:
        v.error(
            f"{faction_sid}: {label} building_layer_map.json uses generic/non-Fortress layer ids despite VCMI Fortress structures: "
            f"{', '.join(sorted(mapped_layer_ids & GENERIC_TOWN_LAYER_IDS))}"
        )
    unknown_ids = sorted(mapped_layer_ids - layer_ids)
    if unknown_ids:
        v.error(f"{faction_sid}: {label} building_layer_map.json maps to ids not present in positions.json: {', '.join(unknown_ids)}")
    positioned_structures: set[str] = set()
    try:
        positions = load_json(building_map_path.parent / "positions.json")
        for entry in positions.get("layers") or []:
            if isinstance(entry, dict) and isinstance(entry.get("structure"), str):
                positioned_structures.add(entry["structure"])
    except (json.JSONDecodeError, OSError):
        pass
    if vcmi_base and mapped_layer_ids and positioned_structures and positioned_structures <= FORTRESS_THIRD_UPGRADE_ONLY_LAYERS:
        v.error(
            f"{faction_sid}: {label} building_layer_map.json is third-upgrade-only; local VCMI Fortress base placement exists "
            f"for {', '.join(sorted(vcmi_base))}"
        )


def resolve_manifest_asset_path(base: Path, path: str | None, deployed: bool) -> Path | None:
    if not path:
        return None
    if deployed:
        relative = manifest_relative_plugin_path(path)
        return base / relative if relative else None
    return ROOT / path


def validate_cross_manifest(manifests: list[tuple[Path, dict[str, Any]]], v: Validation) -> dict[str, str]:
    faction_sids: set[str] = set()
    city_sids: set[str] = set()
    direct_dwelling_sids: set[str] = set()
    all_units: dict[str, str] = {}
    donor_to_custom: dict[str, list[tuple[str, str]]] = defaultdict(list)
    donor_prefix_to_faction: dict[str, list[str]] = defaultdict(list)

    for path, manifest in manifests:
        identity = manifest["identity"]
        faction_sid = identity["factionSid"]
        city_sid = identity["citySid"]
        if faction_sid in faction_sids:
            v.error(f"duplicate factionSid {faction_sid}")
        faction_sids.add(faction_sid)
        if city_sid in city_sids:
            v.error(f"duplicate citySid {city_sid}")
        city_sids.add(city_sid)

        direct_prefix = (manifest.get("coreOverlay") or {}).get("directDwellingPrefix") or ""
        manifest_dwellings = [f"{direct_prefix}{tier}" for tier in range(1, 8)]
        manifest_dwellings.extend(
            line["directDwellingSid"] for line in additional_recruitment_lines(manifest) if isinstance(line.get("directDwellingSid"), str)
        )
        for dwelling_sid in manifest_dwellings:
            if dwelling_sid in direct_dwelling_sids:
                v.error(f"duplicate direct dwelling SID {dwelling_sid}")
            direct_dwelling_sids.add(dwelling_sid)
        for custom_sid, donor_sid in expand_units(manifest).items():
            if custom_sid in all_units:
                v.error(f"duplicate custom unit SID {custom_sid}")
            all_units[custom_sid] = donor_sid
            donor_to_custom[donor_sid].append((faction_sid, custom_sid))
        for prefix in (manifest.get("runtime") or {}).get("dwellingDonorPrefixes") or []:
            if isinstance(prefix, str):
                donor_prefix_to_faction[prefix].append(faction_sid)

    for donor_sid, custom_refs in sorted(donor_to_custom.items()):
        factions = {faction_sid for faction_sid, _ in custom_refs}
        if len(factions) > 1:
            for path, manifest in manifests:
                faction_sid = manifest["identity"]["factionSid"]
                if faction_sid in factions and manifest.get("runtime", {}).get("reverseDonorLookup") != "context_required":
                    v.error(f"{faction_sid}: donor collision on {donor_sid} requires context_required reverse lookup")
            refs = ", ".join(f"{faction}:{custom}" for faction, custom in custom_refs)
            v.warn(f"donor collision requires context: {donor_sid} -> {refs}")

    for donor_prefix, factions in sorted(donor_prefix_to_faction.items()):
        unique_factions = sorted(set(factions))
        if len(unique_factions) <= 1:
            continue
        for path, manifest in manifests:
            faction_sid = manifest["identity"]["factionSid"]
            if faction_sid not in unique_factions:
                continue
            runtime = manifest.get("runtime", {})
            if runtime.get("reverseDonorLookup") != "context_required" or runtime.get("allowGlobalDonorReverseLookup") is not False:
                v.error(f"{faction_sid}: shared donor dwelling prefix {donor_prefix} requires context_required lookup only")
        v.warn(f"donor dwelling prefix collision requires city context: {donor_prefix} -> {', '.join(unique_factions)}")

    return all_units


def validate_building_icon_runtime_source_map_parser(v: Validation) -> None:
    """Pin the runtime source-map parser to object-valued {folder, file} icon entries.

    Python validators already accept those entries. The live Fortress black town was a
    C# regex that only read string filenames, then PrefixSpriteResolver threw.
    """
    if not BUILDING_ICON_SPRITE_CACHE.is_file():
        v.error(f"{BUILDING_ICON_SPRITE_CACHE}: missing building-icon sprite cache")
        return
    text = BUILDING_ICON_SPRITE_CACHE.read_text(encoding="utf-8-sig")
    required = (
        "AddMappedFilesFromMapObject",
        "AddMappedFilesFromExplicitFiles",
        "TryParseSourceMappedFile(",
        'root["explicitFiles"]',
        'obj["file"]',
        'obj["folder"]',
        "JObject.Parse(token.ToString())",
    )
    for token in required:
        if token not in text:
            v.error(
                f"{BUILDING_ICON_SPRITE_CACHE}: missing building-icon source-map parser contract token: {token}"
            )
    if r"[^{}]*" in text:
        v.error(
            f"{BUILDING_ICON_SPRITE_CACHE}: must not parse source-map level objects with a "
            r"[^{}]* regex; that skips {folder, file} grail/icon entries and blacks owned towns"
        )


def validate_source_maps(expected: dict[str, str], manifests: list[tuple[Path, dict[str, Any]]], v: Validation) -> None:
    registry_text = REGISTRY_SOURCE.read_text(encoding="utf-8-sig")
    registry_map = parse_registry_source(REGISTRY_SOURCE)
    registry_lines = parse_registry_unit_lines(REGISTRY_SOURCE)

    dynamic_registry_tokens = (
        "internal static int InitializeFromManifestDirectory",
        "var definition = LoadManifest(manifestPath);",
        "foreach (var line in definition.AllUnitLines)",
        'OptionalArray(root, "additionalRecruitmentLines", manifestPath)',
        "CustomToDonor = BuildCustomToDonor();",
    )
    for token in dynamic_registry_tokens:
        if token not in registry_text:
            v.error(f"{REGISTRY_SOURCE}: missing dynamic manifest registry contract token: {token}")


    registry_base_sids = set(registry_lines)
    embedded_expected: dict[str, str] = {}
    embedded_manifests: list[tuple[Path, dict[str, Any]]] = []
    for manifest_path, manifest in manifests:
        faction_sid = manifest["identity"]["factionSid"]
        if not manifest_requires_runtime_mirror(manifest):
            v.warn(f"{faction_sid}: manifest validation.status={manifest_validation_status(manifest)!r}; runtime registry mirror is not required yet")
            continue

        manifest_base_sids = {
            line["baseSid"]
            for line in all_unit_lines(manifest)
            if isinstance(line.get("baseSid"), str) and line.get("baseSid")
        }
        embedded_base_sids = manifest_base_sids & registry_base_sids
        if embedded_base_sids and embedded_base_sids != manifest_base_sids:
            missing_base_sids = sorted(manifest_base_sids - embedded_base_sids)
            v.error(
                f"{REGISTRY_SOURCE}: {faction_sid} has a partial embedded registry mirror; "
                f"missing base SIDs {missing_base_sids}. Embed the complete manifest or rely wholly on dynamic loading."
            )
            continue
        if manifest_base_sids and embedded_base_sids == manifest_base_sids:
            embedded_expected.update(expand_units(manifest))
            embedded_manifests.append((manifest_path, manifest))

    if registry_map != embedded_expected:
        missing = sorted(set(embedded_expected) - set(registry_map))
        extra = sorted(set(registry_map) - set(embedded_expected))
        mismatched = sorted(k for k in embedded_expected.keys() & registry_map.keys() if embedded_expected[k] != registry_map[k])
        if missing:
            v.error(f"{REGISTRY_SOURCE}: missing embedded manifest unit mappings: {missing}")
        if extra:
            v.error(f"{REGISTRY_SOURCE}: extra embedded unit mappings not in manifests: {extra}")
        for key in mismatched:
            v.error(f"{REGISTRY_SOURCE}: {key} donor {registry_map[key]!r} != manifest {embedded_expected[key]!r}")

    for manifest_path, manifest in embedded_manifests:
        faction_sid = manifest["identity"]["factionSid"]
        default_donor_faction = manifest["identity"].get("donorFactionSid")
        for line in all_unit_lines(manifest):
            base_sid = line.get("baseSid")
            donor_faction = line.get("donorFactionSid", default_donor_faction)
            donor_base = line.get("donorBaseSid")
            donor_prefab = line.get("donorPrefabBaseSid")
            registry_line = registry_lines.get(base_sid)
            if not registry_line:
                continue
            registry_donor_faction, registry_donor_base, registry_donor_prefab, _registry_variant_sids = registry_line
            if registry_donor_faction != donor_faction:
                v.error(f"{REGISTRY_SOURCE}: {base_sid} donor faction {registry_donor_faction!r} != manifest {donor_faction!r}")
            if registry_donor_base != donor_base:
                v.error(f"{REGISTRY_SOURCE}: {base_sid} donor base {registry_donor_base!r} != manifest {donor_base!r}")
            if (registry_donor_prefab or donor_prefab) and (registry_donor_prefab or registry_donor_base) != (donor_prefab or donor_base):
                v.error(
                    f"{REGISTRY_SOURCE}: {base_sid} donor prefab base "
                    f"{(registry_donor_prefab or registry_donor_base)!r} != manifest {(donor_prefab or donor_base)!r}"
                )
        for value_name, value in (
            ("identity.factionSid", manifest["identity"].get("factionSid")),
            ("identity.citySid", manifest["identity"].get("citySid")),
            ("heroes.heroPrefix", (manifest.get("heroes") or {}).get("heroPrefix")),
            ("heroes.iconPrefix", (manifest.get("heroes") or {}).get("iconPrefix")),
            ("assets.factionIcon", manifest_relative_plugin_path((manifest.get("assets") or {}).get("factionIcon"))),
            ("assets.factionCard", manifest_relative_plugin_path((manifest.get("assets") or {}).get("factionCard"))),
            ("assets.cityIcon", manifest_relative_plugin_path((manifest.get("assets") or {}).get("cityIcon"))),
            ("assets.dwellingBillboardFolder", manifest_relative_plugin_path((manifest.get("assets") or {}).get("dwellingBillboardFolder"))),
            ("coreOverlay.directDwellingPrefix", (manifest.get("coreOverlay") or {}).get("directDwellingPrefix")),
        ):
            if value and value not in registry_text:
                v.error(f"{REGISTRY_SOURCE}: missing {faction_sid} {value_name} from {manifest_path.name}: {value}")
        for prefix in (manifest.get("runtime") or {}).get("dwellingDonorPrefixes") or []:
            if prefix and prefix not in registry_text:
                v.error(f"{REGISTRY_SOURCE}: missing {faction_sid} runtime.dwellingDonorPrefixes from {manifest_path.name}: {prefix}")


def validate_homm3_import_table(manifests: list[tuple[Path, dict[str, Any]]], v: Validation) -> None:
    if not HOMM3_IMPORT_TABLE.is_file():
        v.error(f"missing HoMM3 import table: {HOMM3_IMPORT_TABLE}")
        return
    try:
        table = load_json(HOMM3_IMPORT_TABLE)
    except json.JSONDecodeError as ex:
        v.error(f"{HOMM3_IMPORT_TABLE}: invalid JSON: {ex}")
        return

    entries = table.get("entries") if isinstance(table, dict) else None
    if not isinstance(entries, list):
        v.error(f"{HOMM3_IMPORT_TABLE}: entries must be a list")
        return

    # battleHeightHexes (per entry) x battleWorldHeightPerHex (table) is the HoMM3-proportional
    # battle size read by Homm3ImportVisuals.FitSkinnedBattleMesh. Any entry declaring a height
    # requires the table constant; both must be finite positive numbers, or the runtime would
    # silently drop back to the donor-height fit.
    per_hex = table.get("battleWorldHeightPerHex")
    if per_hex is not None and not (isinstance(per_hex, (int, float)) and not isinstance(per_hex, bool) and math.isfinite(per_hex) and per_hex > 0):
        v.error(f"{HOMM3_IMPORT_TABLE}: battleWorldHeightPerHex must be a finite positive number, got {per_hex!r}")
    elif per_hex is not None:
        # The absolute battle size (and, through the map ratio, the map size) of every owned-skinned
        # unit. Calibrated against stock Olden Era units of the same creature by
        # tools/homm3_import/measure_native_battle_height.py; it must equal that artifact's median over
        # >=20 stock/HoMM3 pairs. A hand-edited value is a magic constant (1.3 was one: ~1.33x stock).
        height_artifact = ROOT / "tools" / "homm3_import" / "native_battle_height.json"
        try:
            measured_h = json.loads(height_artifact.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as ex:
            v.error(f"{height_artifact}: unreadable native battle height artifact: {ex}")
        else:
            if measured_h.get("schema") != "native_battle_height.v1" or int(measured_h.get("measuredPairs") or 0) < 20:
                v.error(f"{height_artifact}: expected schema native_battle_height.v1 with >=20 measured pairs")
            elif abs(float(measured_h.get("median")) - float(per_hex)) > 5e-4:
                v.error(f"{HOMM3_IMPORT_TABLE}: battleWorldHeightPerHex {per_hex} != measured median {measured_h.get('median')} in {height_artifact}; rerun measure_native_battle_height.py --write")

    # Adventure-map squads fit to battleHeightHexes x battleWorldHeightPerHex x this native ratio
    # (Homm3ImportVisuals.ApplySkinnedAdventureMapVisualScale). It is measured from the stock
    # <unit>_map / <unit> prefab pairs by tools/homm3_import/measure_native_map_battle_scale.py and
    # must equal that artifact's median; a hand-edited value is a magic constant.
    map_ratio = table.get("adventureMapToBattleHeightRatio")
    if per_hex is not None:
        if not (isinstance(map_ratio, (int, float)) and not isinstance(map_ratio, bool) and math.isfinite(map_ratio) and 0 < map_ratio < 1):
            v.error(f"{HOMM3_IMPORT_TABLE}: adventureMapToBattleHeightRatio must be a finite number in (0,1) when battleWorldHeightPerHex is set, got {map_ratio!r}")
        else:
            scale_artifact = ROOT / "tools" / "homm3_import" / "native_map_battle_scale.json"
            try:
                measured = json.loads(scale_artifact.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as ex:
                v.error(f"{scale_artifact}: unreadable native map/battle scale artifact: {ex}")
            else:
                if measured.get("schema") != "native_map_battle_scale.v1" or int(measured.get("measuredPairs") or 0) < 20:
                    v.error(f"{scale_artifact}: expected schema native_map_battle_scale.v1 with >=20 measured pairs")
                elif abs(float(measured.get("median")) - float(map_ratio)) > 5e-4:
                    v.error(f"{HOMM3_IMPORT_TABLE}: adventureMapToBattleHeightRatio {map_ratio} != measured median {measured.get('median')} in {scale_artifact}; rerun measure_native_map_battle_scale.py --write")

    entries_by_sid: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            v.error(f"{HOMM3_IMPORT_TABLE}: entry {index} must be an object")
            continue
        if "battleHeightHexes" in entry:
            hexes = entry["battleHeightHexes"]
            if not (isinstance(hexes, (int, float)) and not isinstance(hexes, bool) and math.isfinite(hexes) and hexes > 0):
                v.error(f"{HOMM3_IMPORT_TABLE}: entry {index} ({entry.get('battleResPath')}) battleHeightHexes must be a finite positive number, got {hexes!r}")
            if per_hex is None:
                v.error(f"{HOMM3_IMPORT_TABLE}: entry {index} ({entry.get('battleResPath')}) declares battleHeightHexes but the table has no battleWorldHeightPerHex")
        # A reviewed size verdict on top of the DEF-measured hex height (write_battle_height_hexes.py keeps it across
        # re-measures; measure_native_battle_height.py calibrates on the measured value). All four fields together,
        # a reason, a modest factor, and battleHeightHexes == round(measured x scale, 3): never a bare hand-edited height.
        size_keys = ("battleHeightScale", "battleHeightScaleReason", "battleHeightHexesMeasured")
        if any(k in entry for k in size_keys):
            where = f"{HOMM3_IMPORT_TABLE}: entry {index} ({entry.get('battleResPath')})"
            missing = [k for k in size_keys + ("battleHeightHexes",) if k not in entry]
            scale, measured_hx = entry.get("battleHeightScale"), entry.get("battleHeightHexesMeasured")
            if missing:
                v.error(f"{where} battle size verdict is missing {missing}")
            elif not str(entry.get("battleHeightScaleReason") or "").strip():
                v.error(f"{where} battleHeightScale needs a non-empty battleHeightScaleReason")
            elif not (isinstance(scale, (int, float)) and not isinstance(scale, bool) and 0.7 <= scale <= 1.3):
                v.error(f"{where} battleHeightScale {scale!r} outside [0.7, 1.3]")
            elif not (isinstance(measured_hx, (int, float)) and measured_hx > 0):
                v.error(f"{where} battleHeightHexesMeasured must be a positive number, got {measured_hx!r}")
            elif abs(float(entry["battleHeightHexes"]) - round(measured_hx * scale, 3)) > 5e-4:
                v.error(f"{where} battleHeightHexes {entry['battleHeightHexes']} != round(battleHeightHexesMeasured "
                        f"{measured_hx} x battleHeightScale {scale}, 3)")
        prefab = str(entry.get("battlePrefabAssetPath") or "").replace("\\", "/")
        if "/OwnedSkinned/" in prefab and "battleHeightHexes" not in entry:
            v.error(f"{HOMM3_IMPORT_TABLE}: entry {index} ({entry.get('battleResPath')}) owned-skinned prefab is missing battleHeightHexes")
        retired = [k for k in ("battleMoveStrideBindUnits", "battleMoveCycleSeconds", "battleStrideMatch") if k in entry]
        if retired:
            v.error(f"{HOMM3_IMPORT_TABLE}: entry {index} ({entry.get('battleResPath')}) carries retired {retired}: the runtime "
                    "no longer lowers moveSpeed to a measured stride; ground speed is the normalized Core view row "
                    "(custom_factions/unit_move_speed_normalization.json) and the Move is stride matched to it")
        game_sids = entry.get("gameUnitSids")
        if not isinstance(game_sids, list):
            continue
        for sid in game_sids:
            if isinstance(sid, str) and sid:
                entries_by_sid[sid].append(entry)

    for manifest_path, manifest in manifests:
        faction_sid = manifest["identity"]["factionSid"]
        for custom_sid, donor_sid in expand_units(manifest).items():
            sid_entries = entries_by_sid.get(custom_sid, [])
            if not sid_entries:
                report_missing_release_surface(
                    manifest,
                    v,
                    f"{HOMM3_IMPORT_TABLE}: missing gameUnitSids entry for {faction_sid}:{custom_sid} (donor {donor_sid})",
                )
                continue
            if len(sid_entries) > 1:
                v.error(f"{HOMM3_IMPORT_TABLE}: duplicate gameUnitSids entries for {faction_sid}:{custom_sid}")
                continue
            entry = sid_entries[0]
            for key in ("battleResPath", "mapResPath", "bundleName", "battlePrefabAssetPath", "mapPrefabAssetPath", "battlePresentationResPath", "mapShellResPath"):
                value = entry.get(key)
                if not isinstance(value, str) or not value:
                    v.error(f"{HOMM3_IMPORT_TABLE}: {faction_sid}:{custom_sid} entry must declare non-empty {key}")
            if entry.get("swapAdventureMap") is not True:
                v.error(f"{HOMM3_IMPORT_TABLE}: {faction_sid}:{custom_sid} must set swapAdventureMap=true for map-unit billboard replacement")
            map_res = entry.get("mapResPath")
            if isinstance(map_res, str) and custom_sid not in map_res:
                v.error(f"{HOMM3_IMPORT_TABLE}: {faction_sid}:{custom_sid} mapResPath should include the custom SID, got {map_res!r}")
            lab_sid = lab_sid_from_import_entry(entry)
            if lab_sid:
                expected_audio = f"HOMM3_{lab_sid}_"
                actual_audio = entry.get("audioStemPrefix")
                if actual_audio and actual_audio != expected_audio:
                    v.error(
                        f"{HOMM3_IMPORT_TABLE}: {faction_sid}:{custom_sid} audioStemPrefix must match homm3_lab SID "
                        f"{expected_audio!r}, got {actual_audio!r}"
                    )

        validate_variant_import_asset_identity(faction_sid, manifest, entries_by_sid, v)


def unit_view_config_path(units_res_path: str | None) -> str | None:
    if not isinstance(units_res_path, str) or not units_res_path.strip():
        return None
    path = units_res_path.strip().replace("\\", "/")
    if path.endswith(".prefab"):
        path = path[: -len(".prefab")]
    if path.startswith("units/"):
        path = path[len("units/") :]
    return path


def load_homm3_import_map_meshes(v: Validation) -> dict[str, str]:
    if not HOMM3_IMPORT_TABLE.is_file():
        return {}
    try:
        table = load_json(HOMM3_IMPORT_TABLE)
    except json.JSONDecodeError as ex:
        v.error(f"{HOMM3_IMPORT_TABLE}: invalid JSON: {ex}")
        return {}
    entries = table.get("entries") if isinstance(table, dict) else None
    if not isinstance(entries, list):
        return {}
    result: dict[str, str] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        map_mesh = unit_view_config_path(entry.get("mapResPath"))
        if not map_mesh:
            continue
        for sid in entry.get("gameUnitSids") or []:
            if isinstance(sid, str) and sid:
                result.setdefault(sid, map_mesh)
    return result


def load_homm3_import_skinned_preview_meshes(v: Validation) -> dict[str, dict[str, str]]:
    """Game SID → mesh/mapMesh when both import prefabs are OwnedSkinned."""
    if not HOMM3_IMPORT_TABLE.is_file():
        return {}
    try:
        table = load_json(HOMM3_IMPORT_TABLE)
    except json.JSONDecodeError as ex:
        v.error(f"{HOMM3_IMPORT_TABLE}: invalid JSON: {ex}")
        return {}
    entries = table.get("entries") if isinstance(table, dict) else None
    if not isinstance(entries, list):
        return {}
    result: dict[str, dict[str, str]] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        battle_prefab = str(entry.get("battlePrefabAssetPath") or "").replace("\\", "/")
        map_prefab = str(entry.get("mapPrefabAssetPath") or "").replace("\\", "/")
        if "/OwnedSkinned/" not in battle_prefab or "/OwnedSkinned/" not in map_prefab:
            continue
        mesh = unit_view_config_path(entry.get("battleResPath"))
        map_mesh = unit_view_config_path(entry.get("mapResPath"))
        if not mesh or not map_mesh:
            v.error(
                f"{HOMM3_IMPORT_TABLE}: OwnedSkinned row missing battleResPath/mapResPath: {battle_prefab}"
            )
            continue
        for sid in entry.get("gameUnitSids") or []:
            if isinstance(sid, str) and sid:
                result[sid] = {"mesh": mesh, "mapMesh": map_mesh}
    return result


def load_homm3_import_shell_paths(v: Validation) -> tuple[dict[str, str], dict[str, str]]:
    if not HOMM3_IMPORT_TABLE.is_file():
        return {}, {}
    try:
        table = load_json(HOMM3_IMPORT_TABLE)
    except json.JSONDecodeError as ex:
        v.error(f"{HOMM3_IMPORT_TABLE}: invalid JSON: {ex}")
        return {}, {}
    entries = table.get("entries") if isinstance(table, dict) else None
    if not isinstance(entries, list):
        return {}, {}
    battle_by_sid: dict[str, str] = {}
    map_by_sid: dict[str, str] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        battle_path = unit_view_config_path(entry.get("battlePresentationResPath"))
        map_path = unit_view_config_path(entry.get("mapShellResPath"))
        for sid in entry.get("gameUnitSids") or []:
            if not isinstance(sid, str) or not sid:
                continue
            if battle_path:
                battle_by_sid.setdefault(sid, battle_path)
            if map_path:
                map_by_sid.setdefault(sid, map_path)
    return battle_by_sid, map_by_sid


UNSAFE_CUSTOM_UNIT_VIEW_MESHES = {
    "Nature/1Prefabs/phoenix_upg_alt": "Current Steam native prefab emits repeated particle acceleration errors during custom battle drawer construction; use Nature/1Prefabs/phoenix_upg as the donor shell for custom rows.",
}


def load_core_unit_view_prefab_paths(core: Path) -> tuple[set[str], set[str]]:
    mesh_paths: set[str] = set()
    map_mesh_paths: set[str] = set()
    for member in core_member_names(core, "DB/units/units_views/", "_v.json"):
        item = first_array_item(read_core_json(core, member))
        if not isinstance(item, dict):
            continue
        mesh = unit_view_config_path(item.get("mesh"))
        map_mesh = unit_view_config_path(item.get("mapMesh"))
        if mesh:
            mesh_paths.add(mesh)
        if map_mesh:
            map_mesh_paths.add(map_mesh)
    return mesh_paths, map_mesh_paths


def distinct_alternate_expected(line: dict[str, Any], variants: list[str]) -> bool:
    if "_upg" not in variants or "_upg_alt" not in variants:
        return False
    names = line.get("names")
    if isinstance(names, list) and len(names) == len(variants):
        try:
            return str(names[variants.index("_upg_alt")]).strip().lower() != str(names[variants.index("_upg")]).strip().lower()
        except (ValueError, IndexError):
            return False
    return True


def single_entry_for_sid(entries_by_sid: dict[str, list[dict[str, Any]]], sid: str) -> dict[str, Any] | None:
    entries = entries_by_sid.get(sid) or []
    return entries[0] if len(entries) == 1 else None


def validate_variant_import_asset_identity(
    faction_sid: str,
    manifest: dict[str, Any],
    entries_by_sid: dict[str, list[dict[str, Any]]],
    v: Validation,
) -> None:
    variants = manifest.get("unitVariants", ["", "_upg", "_upg_alt"])
    if "_upg" not in variants or "_upg_alt" not in variants:
        return

    for line in all_unit_lines(manifest):
        if not distinct_alternate_expected(line, variants):
            continue
        if not isinstance(line.get("baseSid"), str) or not line.get("baseSid"):
            continue
        upg_sid = unit_sid_for_variant(line, "_upg")
        alt_sid = unit_sid_for_variant(line, "_upg_alt")
        upg_entry = single_entry_for_sid(entries_by_sid, upg_sid)
        alt_entry = single_entry_for_sid(entries_by_sid, alt_sid)
        if upg_entry is None or alt_entry is None:
            continue

        upg_bundle = upg_entry.get("bundleName")
        alt_bundle = alt_entry.get("bundleName")
        if isinstance(upg_bundle, str) and isinstance(alt_bundle, str) and upg_bundle == alt_bundle:
            v.error(
                f"{HOMM3_IMPORT_TABLE}: {faction_sid}:{alt_sid} declares a distinct alternate upgrade but reuses "
                f"{upg_sid} bundleName {alt_bundle!r}"
            )

        upg_lab = lab_sid_from_import_entry(upg_entry)
        alt_lab = lab_sid_from_import_entry(alt_entry)
        if upg_lab and alt_lab and upg_lab == alt_lab:
            v.error(
                f"{HOMM3_IMPORT_TABLE}: {faction_sid}:{alt_sid} declares a distinct alternate upgrade but reuses "
                f"{upg_sid} homm3_lab source {alt_lab!r}"
            )


def load_homm3_import_entries_by_sid(v: Validation) -> dict[str, dict[str, Any]]:
    if not HOMM3_IMPORT_TABLE.is_file():
        v.error(f"missing HoMM3 import table: {HOMM3_IMPORT_TABLE}")
        return {}
    try:
        table = load_json(HOMM3_IMPORT_TABLE)
    except json.JSONDecodeError as ex:
        v.error(f"{HOMM3_IMPORT_TABLE}: invalid JSON: {ex}")
        return {}
    entries = table.get("entries") if isinstance(table, dict) else None
    if not isinstance(entries, list):
        v.error(f"{HOMM3_IMPORT_TABLE}: entries must be a list")
        return {}

    result: dict[str, dict[str, Any]] = {}
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            continue
        game_sids = entry.get("gameUnitSids")
        if not isinstance(game_sids, list):
            continue
        for sid in game_sids:
            if not isinstance(sid, str) or not sid:
                continue
            if sid in result:
                v.error(f"{HOMM3_IMPORT_TABLE}: duplicate gameUnitSids entries for {sid}")
            else:
                result[sid] = entry
    return result



def load_homm3_bundle_payload_contract(v: Validation) -> dict[str, dict[str, Any]]:
    if not HOMM3_BUNDLE_PAYLOAD_CONTRACT.is_file():
        v.error(f"missing HoMM3 bundle payload contract: {HOMM3_BUNDLE_PAYLOAD_CONTRACT}")
        return {}
    try:
        doc = load_json(HOMM3_BUNDLE_PAYLOAD_CONTRACT)
    except json.JSONDecodeError as ex:
        v.error(f"{HOMM3_BUNDLE_PAYLOAD_CONTRACT}: invalid JSON: {ex}")
        return {}
    bundles = doc.get("bundles") if isinstance(doc, dict) else None
    if not isinstance(bundles, dict):
        v.error(f"{HOMM3_BUNDLE_PAYLOAD_CONTRACT}: bundles must be an object")
        return {}
    if not bundles:
        v.error(f"{HOMM3_BUNDLE_PAYLOAD_CONTRACT}: bundles must contain at least one authoritative payload row")
        return {}
    result: dict[str, dict[str, Any]] = {}
    for name, row in bundles.items():
        if not isinstance(name, str) or not name:
            v.error(f"{HOMM3_BUNDLE_PAYLOAD_CONTRACT}: bundle contract name must be a non-empty string")
            continue
        if not isinstance(row, dict):
            v.error(f"{HOMM3_BUNDLE_PAYLOAD_CONTRACT}: contract row for {name} must be an object")
            continue
        length = row.get("length")
        sha256 = row.get("sha256")
        if not isinstance(length, int) or length <= 0:
            v.error(f"{HOMM3_BUNDLE_PAYLOAD_CONTRACT}: contract row for {name} has invalid length {length!r}")
            continue
        if not isinstance(sha256, str) or not re.fullmatch(r"[0-9A-Fa-f]{64}", sha256):
            v.error(f"{HOMM3_BUNDLE_PAYLOAD_CONTRACT}: contract row for {name} has invalid sha256 {sha256!r}")
            continue
        result[name] = {"length": length, "sha256": sha256.upper()}
    return result


def referenced_homm3_bundle_names(import_entries: dict[str, dict[str, Any]]) -> set[str]:
    names: set[str] = set()
    for entry in import_entries.values():
        bundle_name = entry.get("bundleName")
        if isinstance(bundle_name, str) and bundle_name:
            names.add(bundle_name)
    return names


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def validate_homm3_bundle_payload_contract(
    import_entries: dict[str, dict[str, Any]],
    v: Validation,
    *,
    plugin_root: Path | None = None,
    bundle_name_prefixes: list[str] | None = None,
) -> None:
    contract = load_homm3_bundle_payload_contract(v)
    if not contract:
        return

    referenced = {
        name
        for name in referenced_homm3_bundle_names(import_entries)
        if not bundle_name_prefixes or any(name.startswith(prefix) for prefix in bundle_name_prefixes)
    }
    for bundle_name in sorted(referenced):
        if bundle_name not in contract:
            v.error(
                f"{HOMM3_BUNDLE_PAYLOAD_CONTRACT}: missing contract for import-table bundle {bundle_name}; "
                "update this contract intentionally after rebuilding the authoritative custom_units_* payload"
            )

    if plugin_root is None:
        return

    bundle_dir = plugin_root / "homm3_bundles"
    if not bundle_dir.is_dir():
        v.error(f"deployed HoMM3 bundle directory is missing: {bundle_dir}")
        return

    contracted_names = {
        name
        for name in contract
        if not bundle_name_prefixes or any(name.startswith(prefix) for prefix in bundle_name_prefixes)
    }
    for bundle_name in sorted(contracted_names):
        expected = contract[bundle_name]
        bundle_path = bundle_dir / bundle_name
        if not bundle_path.is_file():
            v.error(f"deployed HoMM3 bundle contract target is missing: {bundle_path}")
            continue
        actual_length = bundle_path.stat().st_size
        if actual_length != expected["length"]:
            v.error(
                f"deployed HoMM3 bundle {bundle_name} length mismatch: got {actual_length}, "
                f"expected {expected['length']} from {HOMM3_BUNDLE_PAYLOAD_CONTRACT}"
            )
            continue
        actual_hash = sha256_file(bundle_path)
        if actual_hash != expected["sha256"]:
            v.error(
                f"deployed HoMM3 bundle {bundle_name} sha256 mismatch: got {actual_hash}, "
                f"expected {expected['sha256']} from {HOMM3_BUNDLE_PAYLOAD_CONTRACT}"
            )

    for bundle_path in sorted(bundle_dir.iterdir()):
        if not bundle_path.is_file() or bundle_path.name.endswith(".manifest"):
            continue
        if bundle_name_prefixes and not any(bundle_path.name.startswith(prefix) for prefix in bundle_name_prefixes):
            continue
        if bundle_path.name not in contracted_names:
            v.error(
                f"deployed HoMM3 bundle payload contains uncontracted non-manifest file: {bundle_path}; "
                "remove stale bundle leftovers or update the authoritative contract intentionally"
            )


def lab_sid_from_import_entry(entry: dict[str, Any]) -> str | None:
    for key in ("mapPrefabAssetPath", "battlePrefabAssetPath"):
        value = entry.get(key)
        if not isinstance(value, str):
            continue
        match = HOMM3_LAB_ASSET_RE.search(value)
        if match:
            return match.group("lab_sid")
    return None


def validate_deployed_idle_clip_contract(
    plugin_root: Path,
    manifest: dict[str, Any],
    custom_sid: str,
    entry: dict[str, Any],
    v: Validation,
) -> None:
    faction_sid = manifest["identity"]["factionSid"]
    bundle_name = entry.get("bundleName")
    if not isinstance(bundle_name, str) or not bundle_name:
        report_missing_release_surface(manifest, v, f"{faction_sid}:{custom_sid}: import entry is missing bundleName for recruitment idle clip contract")
        return

    bundle_path = plugin_root / "homm3_bundles" / bundle_name
    if not bundle_path.is_file():
        report_missing_release_surface(manifest, v, f"{faction_sid}:{custom_sid}: deployed bundle is missing: {bundle_path}")
        return
    if bundle_path.stat().st_size <= 0:
        report_missing_release_surface(manifest, v, f"{faction_sid}:{custom_sid}: deployed bundle is empty: {bundle_path}")
        return

    lab_sid = lab_sid_from_import_entry(entry)
    if not lab_sid:
        report_missing_release_surface(manifest, v, f"{faction_sid}:{custom_sid}: import entry does not identify a homm3_lab sid for recruitment idle clip contract")
        return

    manifest_path = plugin_root / "homm3_lab" / lab_sid / "Generated" / "BillboardAnim" / "array_battle_manifest.json"
    if not manifest_path.is_file():
        report_missing_release_surface(manifest, v, f"{faction_sid}:{custom_sid}: deployed array_battle_manifest.json is missing: {manifest_path}")
        return

    try:
        data = load_json(manifest_path)
    except json.JSONDecodeError as ex:
        report_missing_release_surface(manifest, v, f"{faction_sid}:{custom_sid}: deployed array_battle_manifest.json is invalid JSON: {manifest_path}: {ex}")
        return

    if not isinstance(data, dict):
        report_missing_release_surface(manifest, v, f"{faction_sid}:{custom_sid}: deployed array_battle_manifest.json root must be an object: {manifest_path}")
        return

    frame_count = data.get("frameCount")
    chunk_size = data.get("arrayChunkSize")
    array_count = data.get("arrayCount")
    if not isinstance(frame_count, int) or frame_count <= 1:
        report_missing_release_surface(manifest, v, f"{faction_sid}:{custom_sid}: array_battle_manifest.json has invalid frameCount: {frame_count!r}")
        return
    if not isinstance(chunk_size, int) or chunk_size <= 0:
        report_missing_release_surface(manifest, v, f"{faction_sid}:{custom_sid}: array_battle_manifest.json has invalid arrayChunkSize: {chunk_size!r}")
        return
    if not isinstance(array_count, int) or array_count <= 0:
        report_missing_release_surface(manifest, v, f"{faction_sid}:{custom_sid}: array_battle_manifest.json has invalid arrayCount: {array_count!r}")
        return

    clips = data.get("clips")
    if not isinstance(clips, list):
        report_missing_release_surface(manifest, v, f"{faction_sid}:{custom_sid}: array_battle_manifest.json clips must be a list")
        return

    idle_clip = None
    for clip in clips:
        if isinstance(clip, dict) and str(clip.get("name") or "").lower() == "22.idle":
            idle_clip = clip
            break
    if idle_clip is None:
        report_missing_release_surface(manifest, v, f"{faction_sid}:{custom_sid}: array_battle_manifest.json is missing 22.Idle clip")
        return

    indices = idle_clip.get("indices")
    if not isinstance(indices, list) or len(indices) <= 1:
        report_missing_release_surface(manifest, v, f"{faction_sid}:{custom_sid}: 22.Idle clip must have at least two frame indices")
        return

    for index in indices:
        if not isinstance(index, int):
            report_missing_release_surface(manifest, v, f"{faction_sid}:{custom_sid}: 22.Idle clip has non-integer frame index: {index!r}")
            return
        if index < 0 or index >= frame_count:
            report_missing_release_surface(manifest, v, f"{faction_sid}:{custom_sid}: 22.Idle frame index {index} is outside frameCount={frame_count}")
            return
        if index // chunk_size >= array_count:
            report_missing_release_surface(manifest, v, f"{faction_sid}:{custom_sid}: 22.Idle frame index {index} exceeds arrayCount={array_count} with arrayChunkSize={chunk_size}")
            return


def validate_deployed_map_array_manifest_contract(
    plugin_root: Path,
    manifest: dict[str, Any],
    custom_sid: str,
    entry: dict[str, Any],
    v: Validation,
) -> None:
    """Adventure-map units must ship array_map_manifest.json (Texture2DArray / slice-to-Hex/Lit contract).

    Missing sidecars force the map-frame transplant fallback. That path is only visible when the
    runtime creates a synthetic flat MeshRenderer; the preferred contract remains map_array assets.
    """
    if entry.get("swapAdventureMap") is not True:
        return
    faction_sid = manifest["identity"]["factionSid"]
    lab_sid = lab_sid_from_import_entry(entry)
    if not lab_sid:
        report_missing_release_surface(
            manifest,
            v,
            f"{faction_sid}:{custom_sid}: import entry does not identify a homm3_lab sid for map-array contract",
        )
        return
    manifest_path = plugin_root / "homm3_lab" / lab_sid / "Generated" / "MapBillboard" / "array_map_manifest.json"
    if not manifest_path.is_file():
        report_missing_release_surface(
            manifest,
            v,
            f"{faction_sid}:{custom_sid}: deployed array_map_manifest.json is missing: {manifest_path} "
            f"(enable mapTexture2DArray=1 and rebuild Homm3BillboardAnimatorBuild map arrays)",
        )
        return
    try:
        data = load_json(manifest_path)
    except json.JSONDecodeError as ex:
        report_missing_release_surface(
            manifest,
            v,
            f"{faction_sid}:{custom_sid}: deployed array_map_manifest.json is invalid JSON: {manifest_path}: {ex}",
        )
        return
    if not isinstance(data, dict):
        report_missing_release_surface(
            manifest,
            v,
            f"{faction_sid}:{custom_sid}: deployed array_map_manifest.json root must be an object: {manifest_path}",
        )
        return
    clips = data.get("clips")
    if not isinstance(clips, list) or not clips:
        report_missing_release_surface(
            manifest,
            v,
            f"{faction_sid}:{custom_sid}: array_map_manifest.json clips must be a non-empty list",
        )
        return
    if not any(isinstance(clip, dict) and str(clip.get("name") or "") == "MapIdle" for clip in clips):
        report_missing_release_surface(
            manifest,
            v,
            f"{faction_sid}:{custom_sid}: array_map_manifest.json is missing MapIdle clip",
        )


def portrait_anim_source_matches_lab_sid(source_manifest: str, lab_sid: str) -> bool:
    normalized = source_manifest.replace("\\", "/")
    if "/homm3_lab/" not in normalized:
        return True
    return f"/homm3_lab/{lab_sid}/" in normalized


def extracted_battle_has_idle_frames(extracted: Path) -> bool:
    if any(extracted.glob("*.dir/02_*.png")):
        return True
    for manifest_path in extracted.glob("*.json"):
        try:
            doc = load_json(manifest_path)
        except json.JSONDecodeError:
            continue
        for sequence in doc.get("sequences") or []:
            if sequence.get("group") != 2:
                continue
            for frame in sequence.get("frames") or []:
                if isinstance(frame, str) and (manifest_path.parent / frame.replace("\\", "/")).is_file():
                    return True
    return False


def validate_homm3_runtime_asset_payload(plugin_root: Path, v: Validation, label: str) -> None:
    runtime_assets = plugin_root / "homm3_runtime_assets"
    if not runtime_assets.is_dir():
        v.error(f"{label} compact HoMM3 runtime asset payload is missing: {runtime_assets}")
        return


    definition_path = runtime_assets / "custom_biomes" / "custom_biomes.json"
    if not definition_path.is_file():
        v.error(f"{label} custom biome definition file is missing: {definition_path}")
        return
    try:
        doc = load_json(definition_path)
    except json.JSONDecodeError as ex:
        v.error(f"{label} custom biome definition file is invalid JSON: {ex}")
        return
    biomes = doc.get("biomes")
    if not isinstance(biomes, list) or not biomes:
        v.error(f"{label} custom biome definition file must contain a non-empty biomes array")
        return

    for index, biome in enumerate(biomes, start=1):
        if not isinstance(biome, dict):
            v.error(f"{label} custom biome definition row {index} must be an object")
            continue
        biome_id = biome.get("id") if isinstance(biome.get("id"), str) else f"row {index}"
        material_alias_only = bool(biome.get("materialAliasOnly"))
        texture_files = biome.get("textureFiles")
        for field_name in ("textureAssetDir", "markerTextureAssetDir"):
            asset_dir = biome.get(field_name)
            if asset_dir is None:
                continue
            if not isinstance(asset_dir, str) or not asset_dir:
                v.error(f"{label} custom biome {biome_id} has invalid {field_name}: {asset_dir!r}")
                continue
            normalized = asset_dir.replace("\\", "/")
            if "reference_pack" in normalized or "homm3_portrait_anims" in normalized:
                v.error(f"{label} custom biome {biome_id} {field_name} must not use retired payload path: {asset_dir}")
            if not normalized.startswith("homm3_runtime_assets/"):
                v.error(f"{label} custom biome {biome_id} {field_name} must resolve inside homm3_runtime_assets: {asset_dir}")
        texture_asset_dir = biome.get("textureAssetDir")
        if material_alias_only:
            continue
        if not isinstance(texture_asset_dir, str) or not texture_asset_dir:
            v.error(f"{label} custom biome {biome_id} is missing textureAssetDir")
            continue
        if not isinstance(texture_files, list) or not texture_files:
            v.error(f"{label} custom biome {biome_id} is missing textureFiles")
            continue
        for filename in texture_files:
            if not isinstance(filename, str) or not filename:
                v.error(f"{label} custom biome {biome_id} has invalid texture filename: {filename!r}")
                continue
            texture_path = plugin_root / texture_asset_dir.replace("\\", "/") / filename
            if not texture_path.is_file():
                v.error(f"{label} custom biome {biome_id} texture is missing: {texture_path}")
        marker_asset_dir = biome.get("markerTextureAssetDir")
        if isinstance(marker_asset_dir, str) and marker_asset_dir:
            for filename in texture_files:
                if not isinstance(filename, str) or not filename:
                    continue
                marker_path = plugin_root / marker_asset_dir.replace("\\", "/") / filename
                if not marker_path.is_file():
                    v.error(f"{label} custom biome {biome_id} marker texture is missing: {marker_path}")

def validate_plugin_payload(
    plugin_root: Path,
    manifests: list[tuple[Path, dict[str, Any]]],
    v: Validation,
    *,
    require_homm3_lab_sidecars: bool = False,
    bundle_name_prefixes: list[str] | None = None,
) -> None:
    if not plugin_root.exists():
        v.error(f"plugin root does not exist: {plugin_root}")
        return

    for retired in ("homm3_portrait_anims", "reference_pack"):
        retired_path = plugin_root / retired
        if retired_path.exists():
            v.error(f"retired loose runtime payload must not be deployed: {retired_path}")

    runtime_assets = plugin_root / "homm3_runtime_assets"
    if not runtime_assets.is_dir():
        v.error(f"compact HoMM3 runtime asset payload is missing: {runtime_assets}")
    town_prefab_bundle = plugin_root / "homm3_town_prefabs" / "homm3_town_prefabs"
    if not town_prefab_bundle.is_file():
        v.error(f"HoMM3 town prefab bundle is missing: {town_prefab_bundle}")
    validate_homm3_runtime_asset_payload(plugin_root, v, "deployed plugin")

    import_entries = load_homm3_import_entries_by_sid(v)
    validate_homm3_bundle_payload_contract(
        import_entries,
        v,
        plugin_root=plugin_root,
        bundle_name_prefixes=bundle_name_prefixes,
    )
    for _manifest_path, manifest in manifests:
        faction_sid = manifest["identity"]["factionSid"]
        validate_deployed_manifest_assets(plugin_root, manifest, v)
        validate_homm3_town_asset_root(plugin_root, manifest, v, deployed=True)
        deployed_anim_source_by_sid: dict[str, str] = {}
        for custom_sid in expand_units(manifest):
            entry = import_entries.get(custom_sid)
            if entry is None:
                continue

            bundle_name = entry.get("bundleName")
            if isinstance(bundle_name, str) and bundle_name:
                bundle_path = plugin_root / "homm3_bundles" / bundle_name
                if not bundle_path.is_file():
                    report_missing_release_surface(manifest, v, f"{faction_sid}:{custom_sid}: deployed bundle is missing: {bundle_path}")
                elif bundle_path.stat().st_size <= 0:
                    report_missing_release_surface(manifest, v, f"{faction_sid}:{custom_sid}: deployed bundle is empty: {bundle_path}")
            validate_deployed_idle_clip_contract(plugin_root, manifest, custom_sid, entry, v)
            validate_deployed_map_array_manifest_contract(plugin_root, manifest, custom_sid, entry, v)

            portrait_path = plugin_root / "homm3_portraits" / f"{custom_sid}.png"
            if not portrait_path.is_file():
                report_missing_release_surface(manifest, v, f"{faction_sid}:{custom_sid}: deployed portrait is missing: {portrait_path}")


            lab_sid = lab_sid_from_import_entry(entry)
            if not lab_sid:
                report_missing_release_surface(manifest, v, f"{faction_sid}:{custom_sid}: import entry does not identify a homm3_lab sid")
                continue

            if not require_homm3_lab_sidecars:
                continue

            extracted = plugin_root / "homm3_lab" / lab_sid / "extracted_battle"
            if not extracted.is_dir():
                report_missing_release_surface(manifest, v, f"{faction_sid}:{custom_sid}: deployed extracted_battle root is missing: {extracted}")
                continue
            if not any(extracted.glob("*.dir/*.png")):
                report_missing_release_surface(manifest, v, f"{faction_sid}:{custom_sid}: deployed extracted_battle PNG frames are missing under {extracted}")
            if not extracted_battle_has_idle_frames(extracted):
                report_missing_release_surface(manifest, v, f"{faction_sid}:{custom_sid}: deployed idle group 2 frames are missing under {extracted}")



def validate_deployed_manifest_assets(plugin_root: Path, manifest: dict[str, Any], v: Validation) -> None:
    faction_sid = manifest["identity"]["factionSid"]
    assets = manifest.get("assets") or {}
    for key in ("factionIcon", "factionCard", "cityIcon"):
        relative = manifest_relative_plugin_path(assets.get(key))
        if not relative:
            v.error(f"{faction_sid}: assets.{key} is required")
            continue
        deployed_path = plugin_root / relative
        if not deployed_path.is_file():
            report_missing_release_surface(manifest, v, f"{faction_sid}: deployed assets.{key} is missing: {deployed_path}")

    dwelling_folder = manifest_relative_plugin_path(assets.get("dwellingBillboardFolder"))
    dwelling_images = (manifest.get("runtime") or {}).get("dwellingBillboardImages")
    if not dwelling_folder:
        v.error(f"{faction_sid}: assets.dwellingBillboardFolder is required")
        return
    if not isinstance(dwelling_images, list):
        v.error(f"{faction_sid}: runtime.dwellingBillboardImages must be a list")
        return
    for index, image_name in enumerate(dwelling_images, start=1):
        if not isinstance(image_name, str) or not image_name.strip():
            v.error(f"{faction_sid}: runtime.dwellingBillboardImages[{index}] must be a non-empty string")
            continue
        deployed_path = plugin_root / dwelling_folder / manifest_relative_plugin_path(image_name)
        if not deployed_path.is_file():
            report_missing_release_surface(
                manifest,
                v,
                f"{faction_sid}: deployed runtime.dwellingBillboardImages[{index}] is missing: {deployed_path}",
            )
    for index, line in enumerate(additional_recruitment_lines(manifest)):
        image_name = line.get("dwellingBillboardImage")
        if not isinstance(image_name, str) or not image_name.strip():
            v.error(f"{faction_sid}: additionalRecruitmentLines[{index}].dwellingBillboardImage must be a non-empty string")
            continue
        deployed_path = plugin_root / dwelling_folder / manifest_relative_plugin_path(image_name)
        if not deployed_path.is_file():
            report_missing_release_surface(
                manifest,
                v,
                f"{faction_sid}: deployed additionalRecruitmentLines[{index}].dwellingBillboardImage is missing: {deployed_path}",
            )



def validate_deployed_variant_anim_identity(
    faction_sid: str,
    manifest: dict[str, Any],
    deployed_anim_source_by_sid: dict[str, str],
    v: Validation,
) -> None:
    variants = manifest.get("unitVariants", ["", "_upg", "_upg_alt"])
    for line in all_unit_lines(manifest):
        if not distinct_alternate_expected(line, variants):
            continue
        if not isinstance(line.get("baseSid"), str) or not line.get("baseSid"):
            continue
        upg_sid = unit_sid_for_variant(line, "_upg")
        alt_sid = unit_sid_for_variant(line, "_upg_alt")
        upg_source = deployed_anim_source_by_sid.get(upg_sid)
        alt_source = deployed_anim_source_by_sid.get(alt_sid)
        if upg_source and alt_source and upg_source == alt_source:
            v.error(
                f"{faction_sid}:{alt_sid}: deployed portrait animation source matches {upg_sid}; "
                f"distinct alternate upgrades must have their own sourceManifest ({alt_source})"
            )


def manifest_relative_plugin_path(path: str | None) -> str | None:
    if not path:
        return None
    marker = "Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/"
    relative = path.split(marker, 1)[1] if marker in path else path
    return relative.rstrip("/\\")


def core_has_member(core: Path, member: str) -> bool:
    if core.is_dir():
        if member.endswith("/"):
            return (core / member).is_dir()
        return (core / member).exists()
    key = str(core.resolve())
    names = _CORE_NAME_CACHE.get(key)
    if names is None:
        with zipfile.ZipFile(core, "r") as zf:
            names = set(zf.namelist())
        _CORE_NAME_CACHE[key] = names
    if member.endswith("/"):
        return any(name.startswith(member) for name in names)
    return member in names


def read_core_json(core: Path, member: str) -> Any | None:
    cache_key = (str(core.resolve()), member)
    if cache_key in _CORE_JSON_CACHE:
        return _CORE_JSON_CACHE[cache_key]
    try:
        if core.is_dir():
            value = load_json(core / member)
        else:
            key = str(core.resolve())
            members = _CORE_BYTES_CACHE.get(key)
            if members is None:
                with zipfile.ZipFile(core, "r") as zf:
                    names = zf.namelist()
                    members = {name: zf.read(name) for name in names if name.endswith(".json")}
                _CORE_BYTES_CACHE[key] = members
                _CORE_NAME_CACHE.setdefault(key, set(names))
            value = json.loads(members[member].decode("utf-8-sig"))
    except (FileNotFoundError, KeyError, json.JSONDecodeError, UnicodeDecodeError, zipfile.BadZipFile):
        value = None
    _CORE_JSON_CACHE[cache_key] = value
    return value


def core_member_names(core: Path, prefix: str, suffix: str = "") -> list[str]:
    try:
        if core.is_dir():
            base = core / prefix
            if not base.exists():
                return []
            pattern = f"*{suffix}" if suffix else "*"
            return [path.relative_to(core).as_posix() for path in base.rglob(pattern) if path.is_file()]
        key = str(core.resolve())
        names = _CORE_NAME_CACHE.get(key)
        if names is None:
            with zipfile.ZipFile(core, "r") as zf:
                names = set(zf.namelist())
            _CORE_NAME_CACHE[key] = names
        return [name for name in names if name.startswith(prefix) and (not suffix or name.endswith(suffix))]
    except (FileNotFoundError, zipfile.BadZipFile):
        return []


def first_array_item(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    array = value.get("array")
    if not isinstance(array, list) or not array or not isinstance(array[0], dict):
        return None
    return array[0]


def validate_custom_hero_start_skills(
    manifest: dict[str, Any],
    faction_sid: str,
    hero_sid: str,
    hero_member: str,
    hero_item: dict[str, Any],
    expected_override_start_skills: list[dict[str, Any]] | None,
    v: Validation,
) -> None:
    start_skills = hero_item.get("startSkills")
    if not isinstance(start_skills, list):
        v.error(f"{faction_sid}: core hero row {hero_member} must have explicit startSkills")
        return
    actual_rows: list[dict[str, Any]] = []
    for index, row in enumerate(start_skills, start=1):
        if not isinstance(row, dict) or not isinstance(row.get("sid"), str):
            v.error(f"{faction_sid}: core hero row {hero_member} startSkills[{index}] must have a string sid")
            continue
        skill_level = parse_start_skill_level(row.get("skillLevel"), f"{faction_sid}: core hero row {hero_member} startSkills[{index}]", v)
        if skill_level is None:
            continue
        actual_rows.append({"sid": row["sid"], "skillLevel": skill_level})

    expected_faction_skill_sid = f"skill_faction_{faction_sid}"
    faction_skill_sid = (manifest.get("skillsAndLaws") or {}).get("factionSkillSid")
    if faction_skill_sid != expected_faction_skill_sid:
        v.error(
            f"{faction_sid}: manifest skillsAndLaws.factionSkillSid must be {expected_faction_skill_sid!r}, "
            f"got {faction_skill_sid!r}"
        )
        return

    faction_rows = [row for row in actual_rows if row["sid"].startswith("skill_faction_")]
    if len(faction_rows) != 1:
        v.error(
            f"{faction_sid}: core hero row {hero_member} must have exactly one faction start skill "
            f"{faction_skill_sid!r}, got {[row['sid'] for row in faction_rows]!r}"
        )
    elif faction_rows[0]["sid"] != faction_skill_sid:
        v.error(
            f"{faction_sid}: core hero row {hero_member} faction start skill must be "
            f"{faction_skill_sid!r}, got {faction_rows[0]['sid']!r}"
        )
    elif faction_rows[0]["skillLevel"] != 1:
        v.error(
            f"{faction_sid}: core hero row {hero_member} faction start skill {faction_skill_sid!r} "
            f"must have skillLevel 1, got {faction_rows[0]['skillLevel']!r}"
        )
    if actual_rows and actual_rows[0]["sid"] != faction_skill_sid:
        v.error(
            f"{faction_sid}: core hero row {hero_member} startSkills[1] must be manifest faction skill "
            f"{faction_skill_sid!r}, got {actual_rows[0]['sid']!r}"
        )

    non_faction_rows = [row for row in actual_rows if not row["sid"].startswith("skill_faction_")]
    if len(non_faction_rows) > 1:
        v.error(
            f"{faction_sid}: core hero row {hero_member} must have at most one non-faction HoMM3 start skill, "
            f"got {[row['sid'] for row in non_faction_rows]!r}"
        )
    for row in non_faction_rows:
        if row["skillLevel"] != 1:
            v.error(
                f"{faction_sid}: core hero row {hero_member} non-faction start skill {row['sid']!r} "
                f"must be Basic (skillLevel 1); Advanced/Expert grants a free subskill and reads as a "
                f"third starting skill, got skillLevel={row['skillLevel']}"
            )
    if len(actual_rows) > 2:
        v.error(
            f"{faction_sid}: core hero row {hero_member} startSkills must be faction + at most one secondary, "
            f"got {actual_rows!r}"
        )
    if expected_override_start_skills is not None and non_faction_rows != expected_override_start_skills:
        v.error(
            f"{faction_sid}:{hero_sid}: core hero row {hero_member} non-faction startSkills must match hero_overrides exactly; "
            f"expected {expected_override_start_skills!r}, got {non_faction_rows!r}"
        )

def parse_start_skill_level(value: Any, context: str, v: Validation) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.isdigit():
            return int(stripped)
    v.error(f"{context} must have an integer skillLevel, got {value!r}")
    return None

def clean_start_skill_signature(rows: Any, faction_sid: str, hero_sid: str, source: str, v: Validation) -> list[dict[str, Any]] | None:
    if not isinstance(rows, list):
        return None
    clean: list[dict[str, Any]] = []
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, dict) or not isinstance(row.get("sid"), str):
            v.error(f"{faction_sid}:{hero_sid}: {source} startSkills[{index}] must have a string sid")
            continue
        sid = row["sid"]
        if sid.startswith("skill_faction_"):
            v.error(
                f"{faction_sid}:{hero_sid}: {source} startSkills[{index}] must omit faction skill {sid!r}; "
                "the Core overlay derives it from skillsAndLaws.factionSkillSid"
            )
            continue
        skill_level = parse_start_skill_level(row.get("skillLevel"), f"{faction_sid}:{hero_sid}: {source} startSkills[{index}]", v)
        if skill_level is None:
            continue
        if skill_level != 1:
            v.error(
                f"{faction_sid}:{hero_sid}: {source} startSkills[{index}] non-faction skill {sid!r} must be Basic "
                f"(skillLevel 1); Advanced/Expert grants a free subskill and reads as a third starting skill, "
                f"got skillLevel={skill_level}"
            )
        clean.append({"sid": sid, "skillLevel": skill_level})
    if len(clean) > 1:
        v.error(
            f"{faction_sid}:{hero_sid}: {source} startSkills must contain at most one HoMM3 source skill; "
            f"the Core overlay prepends the unique faction skill"
        )
    return clean

def hero_override_start_skill_signatures(
    manifest: dict[str, Any],
    hero_override_dir: Path,
    v: Validation,
) -> dict[str, list[dict[str, Any]]]:
    faction_sid = manifest["identity"]["factionSid"]
    doc = load_optional_json(hero_override_dir / f"{faction_sid}.json", v, f"{faction_sid} hero override")
    if not isinstance(doc, dict):
        return {}
    overrides = doc.get("heroOverrides")
    if not isinstance(overrides, dict):
        return {}
    result: dict[str, list[dict[str, Any]]] = {}
    for hero_sid, entry in overrides.items():
        if not isinstance(hero_sid, str) or not isinstance(entry, dict) or entry.get("enabled") is False:
            continue
        if "startSkills" not in entry:
            continue
        signature = clean_start_skill_signature(entry.get("startSkills"), faction_sid, hero_sid, "hero override", v)
        if signature is not None:
            result[hero_sid] = signature
    return result


def lang_token_set(core: Path, member: str) -> set[str]:
    doc = read_core_json(core, member)
    rows = None
    if isinstance(doc, dict):
        rows = doc.get("tokens")
        if not isinstance(rows, list):
            rows = doc.get("array")
    result: set[str] = set()
    if isinstance(rows, list):
        for row in rows:
            if isinstance(row, dict) and isinstance(row.get("sid"), str):
                result.add(row["sid"])
    return result


def lang_token_text_map(core: Path, member: str) -> dict[str, str]:
    doc = read_core_json(core, member)
    rows = None
    if isinstance(doc, dict):
        rows = doc.get("tokens")
        if not isinstance(rows, list):
            rows = doc.get("array")
    result: dict[str, str] = {}
    if isinstance(rows, list):
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get("sid"), str):
                continue
            text_parts = [
                str(value)
                for key, value in row.items()
                if key != "sid" and isinstance(value, (str, int, float, bool))
            ]
            result[row["sid"]] = "\n".join(text_parts)
    return result


SOURCE_MECHANICS_STATUSES = {"exact", "substituted", "changed", "runtime-pending", "absent"}
SOURCE_MECHANICS_SURFACES = {"building", "faction_skill", "unit_ability", "unit_passive", "runtime"}
DESIGN_DEBT_KEY_RE = re.compile(r"debt|trace|sourceDifferences|xHomm3SourceDifference", re.IGNORECASE)
DESIGN_DEBT_TEXT_RE = re.compile(r"\b(debt|trace_required|trace required|blocked|awaiting verified|unverified|mvp|proxy)\b", re.IGNORECASE)


def hero_specialization_unique_bonus_signature(row: dict[str, Any]) -> str:
    unique_bonuses: list[dict[str, Any]] = []
    for bonus in row.get("bonuses") or []:
        if not isinstance(bonus, dict):
            continue
        if bonus.get("type") == "heroBattleAbility" and bonus.get("parameters") in (
            ["skill_mage_ability", "0"],
            ["skill_warrior_ability", "0"],
            ["attack_siege_ability", "0"],
        ):
            continue
        if bonus.get("type") == "heroStat" and (bonus.get("parameters") or [None])[0] == "magicSchoolSet":
            continue
        unique_bonuses.append(bonus)
    return json.dumps(unique_bonuses, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def default_specialization_common_bonuses(class_type: Any) -> list[dict[str, Any]]:
    ability_sid = "skill_mage_ability" if class_type == "magic" else "skill_warrior_ability"
    return [
        {"type": "heroBattleAbility", "parameters": [ability_sid, "0"]},
        {"type": "heroBattleAbility", "battleType": "forCity", "receiverRole": "attacker", "parameters": ["attack_siege_ability", "0"]},
        {"type": "heroStat", "parameters": ["magicSchoolSet", "neutral", "1", "0"]},
        {"activationLevel": 4, "type": "heroStat", "parameters": ["magicSchoolSet", "neutral", "2", "0"]},
        {"activationLevel": 8, "type": "heroStat", "parameters": ["magicSchoolSet", "neutral", "3", "0"]},
        {"activationLevel": 12, "type": "heroStat", "parameters": ["magicSchoolSet", "neutral", "4", "0"]},
    ]


def specialization_has_required_common_bonuses(row: dict[str, Any], class_type: Any) -> bool:
    bonuses = row.get("bonuses") if isinstance(row, dict) else None
    if not isinstance(bonuses, list):
        return False
    signatures = {json.dumps(bonus, sort_keys=True, ensure_ascii=False, separators=(",", ":")) for bonus in bonuses if isinstance(bonus, dict)}
    return all(
        json.dumps(bonus, sort_keys=True, ensure_ascii=False, separators=(",", ":")) in signatures
        for bonus in default_specialization_common_bonuses(class_type)
    )


def hero_specialization_qualitative_axes(row: dict[str, Any]) -> set[str]:
    axes: set[str] = set()
    for bonus in row.get("bonuses") or []:
        if not isinstance(bonus, dict):
            continue
        bonus_type = bonus.get("type")
        params = bonus.get("parameters") or []
        if not isinstance(params, list) or not params:
            continue
        key = params[0]
        if bonus_type == "sideRes":
            axes.add("economy")
        if key in {"movementPerBonus", "roadPerBonus", "movementBonus", "movementRestoreBonus"}:
            axes.add("travel_speed")
        if key in {"landscapePenaltyPerBonus", "movementAfterBattleBonus"}:
            axes.add("terrain_mobility")
        if key in {"viewRadius", "enableEnemyHeroInfo", "enableSquadCounts"}:
            axes.add("reconnaissance")
        if key in {"moral", "additionalActionChanceModifier"}:
            axes.add("morale_command")
        if key in {"luck", "crit", "critChanceModifier"}:
            axes.add("luck_critical")
        if key in {"magicAttackPerBonus", "spellPower", "spellPowerPer"}:
            axes.add("spell_pressure")
        if key in {"manaBonusPercent", "manaRestoreBonusPercent", "manaCostBonusPercent", "manaCostBonus", "magicUsageLimitBonus", "magicCastsPerRound"}:
            axes.add("mana_casting")
        if key in {"enableTactics", "tacticsPlacementSize", "banTactics", "enableEnemyVisionInTactics"}:
            axes.add("deployment_tactics")
        if key in {"startEnergyLevelsBonus", "energyLevelsPerRoundBonus", "energyPerRoundBonus"}:
            axes.add("focus_economy")
        if bonus_type == "unitStat" and len(params) >= 4 and params[0] == "modifierSet":
            if params[1] == "outDmgMods":
                dmg_type = str(params[2]) if len(params) >= 3 else ""
                if dmg_type in {"range_attack", "shoot_attack"}:
                    axes.add("army_ranged_offense")
                elif dmg_type == "basic_attack":
                    axes.add("army_melee_offense")
                else:
                    axes.add("army_offense")
            if params[1] == "inDmgMods":
                axes.add("army_defense")
    return axes


def load_optional_json(path: Path, v: Validation, label: str) -> Any | None:
    if not path.exists():
        v.error(f"missing {label} {path}")
        return None
    try:
        return load_json(path)
    except json.JSONDecodeError as exc:
        v.error(f"invalid {label} JSON {path}: {exc}")
        return None


def validate_hero_override_specializations(
    core: Path,
    manifest: dict[str, Any],
    v: Validation,
    hero_override_dir: Path = DEFAULT_HERO_OVERRIDE_DIR,
) -> None:
    faction_sid = manifest["identity"]["factionSid"]
    doc = load_optional_json(hero_override_dir / f"{faction_sid}.json", v, f"{faction_sid} hero override")
    if not isinstance(doc, dict):
        return
    overrides = doc.get("heroOverrides")
    if not isinstance(overrides, dict):
        v.error(f"{faction_sid}: hero override must contain heroOverrides object")
        return
    spec_member = (manifest.get("coreOverlay") or {}).get("heroSpecializations")
    if not isinstance(spec_member, str):
        v.error(f"{faction_sid}: manifest coreOverlay.heroSpecializations is missing")
        return
    spec_doc = read_core_json(core, spec_member)
    spec_rows = (spec_doc or {}).get("array") if isinstance(spec_doc, dict) else None
    specs_by_id = {row.get("id"): row for row in spec_rows if isinstance(row, dict)} if isinstance(spec_rows, list) else {}
    bonus_signatures: dict[str, list[str]] = {}
    icons: dict[str, list[str]] = {}
    rows_by_hero: dict[str, dict[str, Any]] = {}
    qualitative_axes: dict[str, list[str]] = {}
    expected_count = int((manifest.get("heroes") or {}).get("count") or 0)
    for index in range(1, expected_count + 1):
        hero_sid = f"{faction_sid}_hero_{index}"
        entry = overrides.get(hero_sid)
        if not isinstance(entry, dict) or entry.get("enabled") is False:
            v.error(f"{faction_sid}:{hero_sid}: enabled hero is missing hero override")
            continue
        spec = entry.get("specialization")
        if not isinstance(spec, dict):
            v.error(f"{faction_sid}:{hero_sid}: hero override specialization must be an object")
            continue
        mode = spec.get("mode")
        if mode not in {"custom", "copy", "changed"}:
            v.error(f"{faction_sid}:{hero_sid}: release hero specialization mode must be custom, copy, or changed, got {mode!r}")
        for key in ("sourceSpecId", "nameText", "descriptionText", "iconKey"):
            if not isinstance(spec.get(key), str) or not spec[key].strip():
                v.error(f"{faction_sid}:{hero_sid}: specialization {key} must be non-empty")
        if not isinstance(spec.get("sourceSpecialtyKey"), str) or not spec["sourceSpecialtyKey"].strip():
            v.error(f"{faction_sid}:{hero_sid}: specialization sourceSpecialtyKey must be non-empty")
        source_specialty_key = spec.get("sourceSpecialtyKey")
        if isinstance(source_specialty_key, str) and source_specialty_key.startswith("creature:"):
            creature_icon = source_specialty_key.split(":", 1)[1].strip()
            if spec.get("iconKey") != creature_icon:
                v.error(f"{faction_sid}:{hero_sid}: creature specialization iconKey must be the source creature sid {creature_icon!r}")
        elif isinstance(source_specialty_key, str) and source_specialty_key.startswith("skill:"):
            skill_kind = source_specialty_key.split(":", 1)[1].strip()
            expected_skill_icon = specialization_icon_key_for_kind(skill_kind)
            if spec.get("iconKey") != expected_skill_icon:
                v.error(
                    f"{faction_sid}:{hero_sid}: skill specialization iconKey must be {expected_skill_icon!r} for {source_specialty_key!r}, got {spec.get('iconKey')!r}"
                )
            creature_icon = None
        else:
            creature_icon = None
        bonuses = spec.get("bonuses")
        if mode in {"custom", "changed"} and (not isinstance(bonuses, list) or not bonuses):
            v.error(f"{faction_sid}:{hero_sid}: {mode} specialization must contain concrete bonuses")
        if mode == "changed" and not isinstance(spec.get("changeDisposition"), str):
            v.error(f"{faction_sid}:{hero_sid}: changed specialization must name changeDisposition")
        row = specs_by_id.get(f"{hero_sid}_specialization")
        if not isinstance(row, dict):
            v.error(f"{faction_sid}:{hero_sid}: live Core specialization row is missing")
            continue
        if creature_icon and row.get("icon") != creature_icon:
            v.error(f"{faction_sid}:{hero_sid}: live creature specialization icon must be {creature_icon!r}")
        hero_doc = read_core_json(core, f"DB/heroes/{faction_sid}/{hero_sid}.json")
        hero_rows = (hero_doc or {}).get("array") if isinstance(hero_doc, dict) else None
        hero_row = next((item for item in hero_rows if isinstance(item, dict)), None) if isinstance(hero_rows, list) else None
        hero_class_type = hero_row.get("classType") if isinstance(hero_row, dict) else None
        if not specialization_has_required_common_bonuses(row, hero_class_type):
            v.error(f"{faction_sid}:{hero_sid}: live specialization must preserve native hero ability and magic-school common bonuses")
        rows_by_hero[hero_sid] = row
        bonus_signature = hero_specialization_unique_bonus_signature(row)
        bonus_signatures.setdefault(bonus_signature, []).append(hero_sid)
        icon = row.get("icon")
        if isinstance(icon, str) and icon.strip():
            icons.setdefault(icon, []).append(hero_sid)
        if spec.get("changeDisposition") == "explicit_masterful_spell_variant":
            source_spec_id = spec.get("sourceSpecId")
            if isinstance(source_spec_id, str) and row.get("xHomm3SourceSpecId") != source_spec_id:
                v.error(f"{faction_sid}:{hero_sid}: live masterful specialization xHomm3SourceSpecId must match hero override")
            source_specialty_key = spec.get("sourceSpecialtyKey")
            if isinstance(source_specialty_key, str) and row.get("xHomm3SourceSpecialtyKey") != source_specialty_key:
                v.error(f"{faction_sid}:{hero_sid}: live masterful specialization xHomm3SourceSpecialtyKey must match hero override")
            if row.get("xHomm3ChangeDisposition") != "explicit_masterful_spell_variant":
                v.error(f"{faction_sid}:{hero_sid}: live specialization xHomm3ChangeDisposition must match hero override")
            base_sid = spec.get("masterfulSpellBaseSid")
            special_sid = spec.get("masterfulSpellSpecialSid")
            if not isinstance(base_sid, str) or not base_sid:
                v.error(f"{faction_sid}:{hero_sid}: hero override masterful specialization must record masterfulSpellBaseSid")
            if not isinstance(special_sid, str) or not special_sid:
                v.error(f"{faction_sid}:{hero_sid}: hero override masterful specialization must record masterfulSpellSpecialSid")
            if isinstance(base_sid, str) and row.get("xHomm3MasterfulSpellBaseSid") != base_sid:
                v.error(f"{faction_sid}:{hero_sid}: live masterful specialization base sid must match hero override")
            if isinstance(special_sid, str) and row.get("xHomm3MasterfulSpellSpecialSid") != special_sid:
                v.error(f"{faction_sid}:{hero_sid}: live masterful specialization special sid must match hero override")
            if isinstance(base_sid, str) and row.get("icon") != base_sid:
                v.error(f"{faction_sid}:{hero_sid}: masterful specialization icon must be the base spell icon key")
            bonuses = row.get("bonuses") or []
            expected_bonus = {"type": "heroMagicReplace", "parameters": [base_sid, special_sid]}
            if isinstance(base_sid, str) and isinstance(special_sid, str) and expected_bonus not in bonuses:
                v.error(f"{faction_sid}:{hero_sid}: custom masterful specialization bonuses must include heroMagicReplace({base_sid}, {special_sid})")
            if isinstance(base_sid, str):
                start_magics = hero_row.get("startMagics") if isinstance(hero_row, dict) else None
                known_start_magics = [
                    item.get("sidConfig")
                    for item in start_magics or []
                    if isinstance(item, dict) and isinstance(item.get("sidConfig"), str)
                ]
                if base_sid not in known_start_magics:
                    v.error(f"{faction_sid}:{hero_sid}: masterful specialist must start with base spell {base_sid}")
                unrelated_start_magics = [
                    sid
                    for sid in known_start_magics
                    if sid != base_sid and not sid.startswith("change_")
                ]
                if unrelated_start_magics:
                    v.error(f"{faction_sid}:{hero_sid}: masterful specialist has unrelated donor startMagics {unrelated_start_magics}")
            hero_info_text = lang_token_text_map(core, "Lang/english/texts/heroInfo.json")
            name_token = row.get("name")
            desc_token = row.get("desc")
            if isinstance(name_token, str) and isinstance(spec.get("nameText"), str) and hero_info_text.get(name_token) != spec["nameText"]:
                v.error(f"{faction_sid}:{hero_sid}: masterful specialization name text must match hero override")
            if isinstance(desc_token, str) and isinstance(spec.get("descriptionText"), str) and hero_info_text.get(desc_token) != spec["descriptionText"]:
                v.error(f"{faction_sid}:{hero_sid}: masterful specialization description text must match hero override")
            continue
        source_spec_id = spec.get("sourceSpecId")
        if isinstance(source_spec_id, str) and row.get("xHomm3SourceSpecId") != source_spec_id:
            v.error(f"{faction_sid}:{hero_sid}: live specialization xHomm3SourceSpecId must match hero override")
        source_specialty_key = spec.get("sourceSpecialtyKey")
        if isinstance(source_specialty_key, str) and row.get("xHomm3SourceSpecialtyKey") != source_specialty_key:
            v.error(f"{faction_sid}:{hero_sid}: live specialization xHomm3SourceSpecialtyKey must match hero override")
        if isinstance(mode, str) and row.get("xHomm3SpecializationMode") != mode:
            v.error(f"{faction_sid}:{hero_sid}: live specialization xHomm3SpecializationMode must match hero override")
        change_disposition = spec.get("changeDisposition")
        if mode == "changed" and isinstance(change_disposition, str) and row.get("xHomm3ChangeDisposition") != change_disposition:
            v.error(f"{faction_sid}:{hero_sid}: live specialization xHomm3ChangeDisposition must match hero override")
        expected_icon = spec.get("iconKey")
        if isinstance(expected_icon, str) and expected_icon.strip():
            live_icon = row.get("icon")
            if live_icon != expected_icon.strip():
                v.error(
                    f"{faction_sid}:{hero_sid}: live specialization icon must be {expected_icon.strip()!r}, got {live_icon!r}"
                )
        if row.get("xHomm3HeroOverride") is not True:
            v.error(f"{faction_sid}:{hero_sid}: live specialization must set xHomm3HeroOverride=true from hero_overrides")
        if (
            mode == "changed"
            and row.get("xHomm3ChangeDisposition") == "explicit_changed_olden_era_specialist"
            and isinstance(source_spec_id, str)
            and not source_spec_id.endswith("_specialist")
        ):
            axes = hero_specialization_qualitative_axes(row)
            if not axes:
                v.error(f"{faction_sid}:{hero_sid}: generated non-creature specialization must have a qualitative gameplay axis")
            for axis in axes:
                qualitative_axes.setdefault(axis, []).append(hero_sid)
    def same_source_specialty(duplicates: list[str]) -> bool:
        keys = {
            row.get("xHomm3SourceSpecialtyKey")
            for hero_sid in duplicates
            for row in [rows_by_hero.get(hero_sid)]
            if isinstance(row, dict)
        }
        return len(keys) == 1 and all(isinstance(key, str) and key.strip() for key in keys)

    def same_masterful_proxy(duplicates: list[str]) -> bool:
        keys = {
            row.get("xHomm3MasterfulSpellBaseSid")
            for hero_sid in duplicates
            for row in [rows_by_hero.get(hero_sid)]
            if isinstance(row, dict)
        }
        return len(keys) == 1 and all(isinstance(key, str) and key.strip() for key in keys)

    def distinct_source_specialties(duplicates: list[str]) -> bool:
        keys: list[str] = []
        for hero_sid in duplicates:
            row = rows_by_hero.get(hero_sid)
            if not isinstance(row, dict):
                return False
            key = row.get("xHomm3SourceSpecialtyKey")
            if not isinstance(key, str) or not key.strip():
                return False
            keys.append(key.strip())
        return len(set(keys)) == len(keys)

    for duplicates in bonus_signatures.values():
        if len(duplicates) > 1:
            if same_source_specialty(duplicates) or same_masterful_proxy(duplicates):
                continue
            v.error(f"{faction_sid}: duplicate live hero specialization bonuses for {', '.join(duplicates)}")
    for icon, duplicates in icons.items():
        if len(duplicates) > 1:
            if (
                same_source_specialty(duplicates)
                or same_masterful_proxy(duplicates)
                or distinct_source_specialties(duplicates)
            ):
                continue
            v.error(f"{faction_sid}: duplicate live hero specialization icon {icon!r} for {', '.join(duplicates)}")
    for axis, duplicates in qualitative_axes.items():
        if len(duplicates) > 1:
            if same_source_specialty(duplicates) or same_masterful_proxy(duplicates):
                continue
            v.error(f"{faction_sid}: duplicate generated non-creature hero specialization gameplay axis {axis!r} for {', '.join(duplicates)}")


def validate_unit_branch_roles(
    core: Path,
    manifest: dict[str, Any],
    v: Validation,
    ability_override_dir: Path = DEFAULT_ABILITY_OVERRIDE_DIR,
) -> None:
    faction_sid = manifest["identity"]["factionSid"]
    doc = load_optional_json(ability_override_dir / f"{faction_sid}.json", v, f"{faction_sid} ability override")
    if not isinstance(doc, dict):
        return
    overrides = doc.get("unitOverrides")
    if not isinstance(overrides, dict):
        v.error(f"{faction_sid}: ability override must contain unitOverrides object")
        return
    for custom_sid in expand_units(manifest):
        row = overrides.get(custom_sid)
        if not isinstance(row, dict):
            v.error(f"{faction_sid}:{custom_sid}: live city-hire unit has no ability override row")
            continue
        for key in ("branchRole", "sourceMechanicId", "decisionTest"):
            if not isinstance(row.get(key), str) or not row[key].strip():
                v.error(f"{faction_sid}:{custom_sid}: ability override {key} must be non-empty")
        for member_kind in ("units_logics", "units_views"):
            member = f"DB/units/{member_kind}/{faction_sid}/{custom_sid}_{'l' if member_kind == 'units_logics' else 'v'}.json"
            item = first_array_item(read_core_json(core, member))
            if not isinstance(item, dict):
                v.error(f"{faction_sid}:{custom_sid}: live Core {member_kind} row is missing")
                continue
            if row.get("branchRole") and item.get("xHomm3BranchRole") != row.get("branchRole"):
                v.error(f"{faction_sid}:{custom_sid}: live {member_kind} xHomm3BranchRole must match ability override")
            if row.get("sourceMechanicId") and item.get("xHomm3SourceMechanic") != row.get("sourceMechanicId"):
                v.error(f"{faction_sid}:{custom_sid}: live {member_kind} xHomm3SourceMechanic must match ability override")
            if row.get("decisionTest") and item.get("xHomm3DecisionTest") != row.get("decisionTest"):
                v.error(f"{faction_sid}:{custom_sid}: live {member_kind} xHomm3DecisionTest must match ability override")


def load_source_mechanics_contract(source_mechanics_dir: Path, faction_sid: str, v: Validation) -> dict[str, Any] | None:
    path = source_mechanics_dir / f"{faction_sid}.json"
    if not path.exists():
        v.error(f"{faction_sid}: missing source mechanics contract {path}")
        return None
    try:
        doc = load_json(path)
    except json.JSONDecodeError as exc:
        v.error(f"{faction_sid}: invalid source mechanics JSON {path}: {exc}")
        return None
    if not isinstance(doc, dict):
        v.error(f"{faction_sid}: source mechanics contract must be an object")
        return None
    if doc.get("factionSid") != faction_sid:
        v.error(f"{faction_sid}: source mechanics factionSid must match manifest")
    mechanics = doc.get("mechanics")
    if not isinstance(mechanics, list):
        v.error(f"{faction_sid}: source mechanics contract must contain mechanics[]")
        return doc
    seen: set[str] = set()
    for index, mechanic in enumerate(mechanics):
        if not isinstance(mechanic, dict):
            v.error(f"{faction_sid}: source mechanic at index {index} must be an object")
            continue
        mechanic_id = mechanic.get("id")
        if not isinstance(mechanic_id, str) or not mechanic_id:
            v.error(f"{faction_sid}: source mechanic at index {index} needs a non-empty id")
        elif mechanic_id in seen:
            v.error(f"{faction_sid}: duplicate source mechanic id {mechanic_id!r}")
        else:
            seen.add(mechanic_id)
        status = mechanic.get("status")
        if status not in SOURCE_MECHANICS_STATUSES:
            v.error(f"{faction_sid}:{mechanic_id}: status must be one of {sorted(SOURCE_MECHANICS_STATUSES)}, got {status!r}")
        surface = mechanic.get("surface")
        if surface not in SOURCE_MECHANICS_SURFACES:
            v.error(f"{faction_sid}:{mechanic_id}: unsupported source mechanics surface {surface!r}")
        rows = mechanic.get("currentRows")
        if rows is not None and (not isinstance(rows, list) or any(not isinstance(row, str) for row in rows)):
            v.error(f"{faction_sid}:{mechanic_id}: currentRows must be a list of row SIDs")
        if status in {"exact", "substituted"} and not rows:
            v.error(f"{faction_sid}:{mechanic_id}: {status} mechanics must name currentRows")
        if status == "changed" and rows:
            v.error(f"{faction_sid}:{mechanic_id}: changed source mechanics must not name currentRows")
        if status == "changed" and not isinstance(mechanic.get("changeDisposition"), str):
            v.error(f"{faction_sid}:{mechanic_id}: changed source mechanics must name changeDisposition")
        if status == "runtime-pending" and rows:
            v.error(f"{faction_sid}:{mechanic_id}: runtime-pending source mechanics must not name currentRows")
        if status == "runtime-pending" and not isinstance(mechanic.get("changeDisposition"), str):
            v.error(f"{faction_sid}:{mechanic_id}: runtime-pending source mechanics must name changeDisposition")
        if status == "runtime-pending" and not isinstance(mechanic.get("validationOwner"), str):
            v.error(f"{faction_sid}:{mechanic_id}: runtime-pending source mechanics must name validationOwner")
        if status == "absent" and rows:
            v.error(f"{faction_sid}:{mechanic_id}: absent source mechanics must not name currentRows")
        if status == "absent" and not isinstance(mechanic.get("changeDisposition"), str):
            v.error(f"{faction_sid}:{mechanic_id}: absent source mechanics must name changeDisposition")
        if status == "absent" and not isinstance(mechanic.get("validationOwner"), str):
            v.error(f"{faction_sid}:{mechanic_id}: absent source mechanics must name validationOwner")
        forbidden = mechanic.get("forbiddenPlayerText")
        if status == "substituted" and not (isinstance(forbidden, list) and forbidden):
            v.error(f"{faction_sid}:{mechanic_id}: substituted mechanics must list forbiddenPlayerText")
        if status in {"changed", "runtime-pending", "absent"} and not rows and not (isinstance(forbidden, list) and forbidden):
            v.error(f"{faction_sid}:{mechanic_id}: {status} mechanics without currentRows must list forbiddenPlayerText")
        text_tokens = mechanic.get("playerTextTokens")
        if text_tokens is not None and (not isinstance(text_tokens, list) or any(not isinstance(token, str) for token in text_tokens)):
            v.error(f"{faction_sid}:{mechanic_id}: playerTextTokens must be a list of exact localization token SIDs")
        if status == "exact" and not isinstance(mechanic.get("validationOwner"), str):
            v.warn(f"{faction_sid}:{mechanic_id}: exact source mechanic should name validationOwner")
    return doc


def city_row_text_tokens(row: dict[str, Any]) -> list[str]:
    tokens: list[str] = []
    for key in ("names", "descriptions", "narrativeDescriptions"):
        value = row.get(key)
        if isinstance(value, str):
            tokens.append(value)
        elif isinstance(value, list):
            tokens.extend(item for item in value if isinstance(item, str))
    return tokens


def english_text_tokens(core: Path) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    for member in core_member_names(core, "Lang/english/texts/", ".json"):
        result[member] = lang_token_text_map(core, member)
    return result


def validate_source_mechanics_contract(
    core: Path,
    source_mechanics_dir: Path,
    manifest: dict[str, Any],
    city_doc: Any,
    v: Validation,
    *,
    strict_metadata: bool = False,
) -> None:
    faction_sid = manifest["identity"]["factionSid"]
    contract = load_source_mechanics_contract(source_mechanics_dir, faction_sid, v)
    if not isinstance(contract, dict):
        return
    mechanics = contract.get("mechanics")
    if not isinstance(mechanics, list):
        return
    city_rows = {row["sid"]: row for row in collect_city_building_config_rows(city_doc)}
    mechanics_by_id = {
        mechanic.get("id"): mechanic
        for mechanic in mechanics
        if isinstance(mechanic, dict) and isinstance(mechanic.get("id"), str)
    }
    mechanics_by_row: dict[str, dict[str, Any]] = {}
    for mechanic in mechanics_by_id.values():
        if mechanic.get("surface") != "building":
            continue
        rows = mechanic.get("currentRows")
        if not isinstance(rows, list):
            continue
        for building_sid in rows:
            if building_sid in mechanics_by_row:
                v.error(f"{faction_sid}:{building_sid}: source mechanics row is claimed by multiple contracts")
                continue
            mechanics_by_row[building_sid] = mechanic
            if building_sid not in city_rows:
                v.error(f"{faction_sid}:{mechanic.get('id')}: currentRows references missing city building {building_sid}")

    for building_sid, row in city_rows.items():
        source_id = row.get("xHomm3SourceMechanic")
        if isinstance(source_id, str):
            if source_id not in mechanics_by_id:
                v.error(f"{faction_sid}:{building_sid}: xHomm3SourceMechanic {source_id!r} has no matching source contract")
            expected = mechanics_by_row.get(building_sid)
            if expected is None:
                v.error(f"{faction_sid}:{building_sid}: xHomm3SourceMechanic {source_id!r} is not assigned to this currentRows entry")
            elif source_id != expected.get("id"):
                v.error(f"{faction_sid}:{building_sid}: xHomm3SourceMechanic must be {expected.get('id')!r}, got {source_id!r}")
        expected = mechanics_by_row.get(building_sid)
        if expected is None:
            continue
        expected_id = expected.get("id")
        expected_status = expected.get("status")
        if row.get("xHomm3SourceMechanic") is None:
            message = f"{faction_sid}:{building_sid}: source mechanic metadata missing for {expected_id!r}"
            if strict_metadata:
                v.error(message)
            else:
                v.warn(message)
        elif row.get("xHomm3MechanicsStatus") != expected_status:
            v.error(
                f"{faction_sid}:{building_sid}: xHomm3MechanicsStatus must be "
                f"{expected_status!r}, got {row.get('xHomm3MechanicsStatus')!r}",
            )
        if expected_status == "exact":
            if not isinstance(row.get("xHomm3MechanicsSource"), str):
                v.error(f"{faction_sid}:{building_sid}: exact source mechanic must carry xHomm3MechanicsSource")
            if not isinstance(row.get("xHomm3ImplementedMechanics"), str):
                v.error(f"{faction_sid}:{building_sid}: exact source mechanic must carry xHomm3ImplementedMechanics")
            has_bonus_payload = (isinstance(row.get("bonuses"), list) and bool(row.get("bonuses"))) or (
                isinstance(row.get("parametersPerLevel"), list) and bool(row.get("parametersPerLevel"))
            )
            if not has_bonus_payload:
                v.error(f"{faction_sid}:{building_sid}: exact source mechanic must emit concrete building bonus or level data")

    text_by_member = english_text_tokens(core)
    for mechanic in mechanics_by_id.values():
        if mechanic.get("surface") != "building":
            continue
        if mechanic.get("status") not in {"substituted", "changed"}:
            continue
        forbidden = mechanic.get("forbiddenPlayerText")
        if not isinstance(forbidden, list):
            continue
        text_tokens: set[str] = set()
        declared_tokens = mechanic.get("playerTextTokens")
        if isinstance(declared_tokens, list):
            text_tokens.update(token for token in declared_tokens if isinstance(token, str))
        rows = mechanic.get("currentRows")
        if isinstance(rows, list):
            for building_sid in rows:
                row = city_rows.get(building_sid)
                if row is not None:
                    text_tokens.update(city_row_text_tokens(row))
        if mechanic.get("status") == "changed" and not isinstance(rows, list):
            for row in city_rows.values():
                text_tokens.update(city_row_text_tokens(row))
        for token in sorted(text_tokens):
            found = False
            for member, tokens in text_by_member.items():
                if token not in tokens:
                    continue
                found = True
                lowered = tokens[token].lower()
                for phrase in forbidden:
                    if isinstance(phrase, str) and phrase.lower() in lowered:
                        v.error(
                            f"{faction_sid}:{mechanic.get('id')}: player-facing token {member}:{token!r} "
                            f"claims blocked/trace-required text {phrase!r}",
                        )
            if not found:
                v.error(f"{faction_sid}:{mechanic.get('id')}: playerTextTokens entry {token!r} was not found in Lang/english/texts/*.json")
        if not text_tokens:
            v.error(f"{faction_sid}:{mechanic.get('id')}: substitute/change text guard has no exact playerTextTokens or currentRows")

        if not isinstance(rows, list):
            continue
        for building_sid in rows:
            row = city_rows.get(building_sid)
            if row is None:
                continue
            for token in city_row_text_tokens(row):
                if token not in text_tokens:
                    v.error(f"{faction_sid}:{mechanic.get('id')}: city row {building_sid} text token {token!r} is not listed in playerTextTokens")


def validate_no_design_debt_value(value: Any, v: Validation, path: str) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if isinstance(key, str) and DESIGN_DEBT_KEY_RE.search(key):
                v.error(f"{path}: design-debt key is not allowed in final custom Core output: {key!r}")
            validate_no_design_debt_value(child, v, child_path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            validate_no_design_debt_value(child, v, f"{path}[{index}]")
    elif isinstance(value, str) and DESIGN_DEBT_TEXT_RE.search(value):
        v.error(f"{path}: design-debt text is not allowed in final custom Core output: {value!r}")


def validate_no_design_debt(core: Path, manifests: list[tuple[Path, dict[str, Any]]], v: Validation) -> None:
    custom_factions = {
        manifest["identity"]["factionSid"]
        for _path, manifest in manifests
        if core_overlay_enabled(manifest)
    }
    neutral_support_unit_members = {
        "DB/units/units_logics/neutral/h3_fangarm_l.json",
        "DB/units/units_views/neutral/h3_fangarm_v.json",
    }
    try:
        release_port_dir = ROOT / "tools" / "release_port"
        if str(release_port_dir) not in sys.path:
            sys.path.insert(0, str(release_port_dir))
        from homm3_neutral_catalog import catalog_units, load_homm3_neutral_catalog, unit_logic_path, unit_view_path

        neutral_catalog = load_homm3_neutral_catalog()
        for unit in catalog_units(neutral_catalog):
            sid = str(unit["sid"])
            neutral_support_unit_members.add(unit_logic_path(sid, neutral_catalog))
            neutral_support_unit_members.add(unit_view_path(sid, neutral_catalog))
    except Exception as ex:
        v.warn(f"homm3_neutral catalog not loaded for Core member checks: {ex}")
    prefixes = tuple(f"DB/units/units_logics/{faction}/" for faction in custom_factions) + tuple(
        f"DB/units/units_views/{faction}/" for faction in custom_factions
    )
    members = [
        "DB/heroes_abilities/heroes_abilities_base/hero_abilities.json",
        "DB/heroes_skills/skills/skills.json",
        "DB/heroes_skills/sub_skills/sub_skills.json",
        "Lang/english/texts/cities.json",
        "Lang/english/texts/unitsAbility.json",
        "Lang/english/texts/heroInfo.json",
        "Lang/english/texts/heroSkills.json",
    ]
    for _path, manifest in manifests:
        if not core_overlay_enabled(manifest):
            continue
        overlay = manifest["coreOverlay"]
        for key in ("factionJson", "cityLogic", "lawsTable", "squadTree", "heroSubClasses", "heroSpecializations"):
            member = overlay.get(key)
            if isinstance(member, str):
                members.append(member)
    members.extend(core_member_names(core, "DB/units/units_logics/", ".json"))
    members.extend(core_member_names(core, "DB/units/units_views/", ".json"))
    members.extend(sorted(neutral_support_unit_members))
    seen: set[str] = set()
    for member in members:
        if member in seen:
            continue
        seen.add(member)
        if (
            prefixes
            and member.startswith(("DB/units/units_logics/", "DB/units/units_views/"))
            and not member.startswith(prefixes)
            and member not in neutral_support_unit_members
        ):
            continue
        doc = read_core_json(core, member)
        if doc is not None:
            validate_no_design_debt_value(doc, v, member)


def load_building_icon_source_levels(manifest: dict[str, Any]) -> dict[str, set[int]]:
    assets = manifest.get("assets") or {}
    icon_folder = resolve_manifest_asset_path(ROOT, assets.get("buildingIconFolder"), deployed=False)
    if icon_folder is None or not icon_folder.is_dir():
        return {}
    for source_map_path in sorted(icon_folder.glob("*_source_map.json")):
        try:
            source_map = load_json(source_map_path)
        except json.JSONDecodeError:
            continue
        mapping = source_map.get("map")
        result: dict[str, set[int]] = {}
        if isinstance(mapping, dict):
            for building_sid, levels in mapping.items():
                if not isinstance(building_sid, str) or not isinstance(levels, dict):
                    continue
                parsed = {
                    int(level)
                    for level in levels
                    if isinstance(level, str) and level.isdigit() and int(level) > 0
                }
                if parsed:
                    result[building_sid] = parsed
        frames = source_map.get("frames")
        if isinstance(frames, list):
            for frame in frames:
                if not isinstance(frame, dict):
                    continue
                building_sid = frame.get("oldenEraSid")
                level = frame.get("oldenEraLevel")
                if isinstance(building_sid, str) and isinstance(level, int) and level > 0:
                    result.setdefault(building_sid, set()).add(level)
        if result:
            return result
    return {}


def collect_city_building_rows(value: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if isinstance(value, dict):
        if isinstance(value.get("sid"), str) and value["sid"].startswith("Build_"):
            rows.append(value)
        for item in value.values():
            rows.extend(collect_city_building_rows(item))
    elif isinstance(value, list):
        for item in value:
            rows.extend(collect_city_building_rows(item))
    return rows


def is_city_building_config_row(row: dict[str, Any]) -> bool:
    return isinstance(row.get("sid"), str) and row["sid"].startswith("Build_") and (
        isinstance(row.get("parametersPerLevel"), list)
        or isinstance(row.get("icons"), list)
        or isinstance(row.get("names"), list)
        or isinstance(row.get("descriptions"), list)
    )


def collect_city_building_config_rows(value: Any) -> list[dict[str, Any]]:
    return [row for row in collect_city_building_rows(value) if is_city_building_config_row(row)]


def validate_additional_recruitment_city_rows(manifest: dict[str, Any], city_doc: Any, v: Validation) -> None:
    additional = additional_recruitment_lines(manifest)
    if not additional:
        return
    faction_sid = manifest["identity"]["factionSid"]
    variants = manifest.get("unitVariants", ["", "_upg", "_upg_alt"])
    city_rows = {row.get("sid"): row for row in collect_city_building_config_rows(city_doc)}
    for index, line in enumerate(additional):
        building_sid = line["cityBuildingSid"]
        row = city_rows.get(building_sid)
        if not isinstance(row, dict):
            report_missing_release_surface(manifest, v, f"{faction_sid}: core missing additional city recruitment building {building_sid}")
            continue
        if row.get("sceneSlot") != line["recruitmentSlotSid"]:
            v.error(
                f"{faction_sid}: core additional building {building_sid} sceneSlot must be "
                f"{line['recruitmentSlotSid']!r}, got {row.get('sceneSlot')!r}"
            )
        units_hire = row.get("unitsHire")
        units = units_hire.get("units") if isinstance(units_hire, dict) else None
        expected_sids = [unit_sid_for_variant(line, suffix) for suffix in variants]
        actual_sids = units[0].get("sids") if isinstance(units, list) and len(units) == 1 and isinstance(units[0], dict) else None
        if actual_sids != expected_sids:
            v.error(
                f"{faction_sid}: core additional building {building_sid} unitsHire must bind {expected_sids!r}, "
                f"got {actual_sids!r}"
            )


def validate_city_building_presentation(
    core: Path,
    manifest: dict[str, Any],
    city_doc: Any,
    v: Validation,
) -> None:
    faction_sid = manifest["identity"]["factionSid"]
    prefix = f"{faction_sid}_building_"
    source_levels = load_building_icon_source_levels(manifest)
    city_tokens = lang_token_set(core, "Lang/english/texts/cities.json")
    for row in collect_city_building_rows(city_doc):
        building_sid = row["sid"]
        if isinstance(building_sid, str) and building_sid.startswith("Build_Tier_"):
            for level_index, level in enumerate(row.get("parametersPerLevel") or [], start=1):
                if not isinstance(level, dict):
                    continue
                for prev in level.get("prevBuildings") or []:
                    if isinstance(prev, dict) and prev.get("sid") == "Build_Wall":
                        v.error(
                            f"{faction_sid}:{building_sid}:{level_index}: creature dwelling must not require Fort/Build_Wall"
                        )
        for icon in row.get("icons") or []:
            if not isinstance(icon, str) or not icon.startswith(prefix):
                continue
            if not source_levels:
                continue
            body = icon[len(prefix):]
            marker = body.rfind("_level_")
            if marker <= 0:
                v.error(f"{faction_sid}:{building_sid}: building icon key is malformed: {icon!r}")
                continue
            icon_building_sid = body[:marker]
            try:
                level = int(body[marker + len("_level_"):])
            except ValueError:
                v.error(f"{faction_sid}:{building_sid}: building icon key has invalid level: {icon!r}")
                continue
            levels = source_levels.get(icon_building_sid)
            if not levels:
                v.error(f"{faction_sid}:{building_sid}: building icon key {icon!r} has no source-map entry")
            elif level not in levels and 1 not in levels:
                v.error(f"{faction_sid}:{building_sid}: building icon key {icon!r} has no level {level} or level 1 source-map fallback")

        for field in ("names", "descriptions", "narrativeDescriptions"):
            for token in row.get(field) or []:
                if isinstance(token, str) and token.startswith("Homm3") and token not in city_tokens:
                    v.error(f"{faction_sid}:{building_sid}: city building {field} token {token!r} is missing from Lang/english/texts/cities.json")


def attack_rows(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        return [value]
    return []


def unit_has_shoot_attack(logic_item: dict[str, Any]) -> bool:
    return any(attack.get("attackType_") == "shoot" for attack in attack_rows(logic_item.get("defaultAttacks")))


def validate_ranged_attack_contract(
    faction_sid: str,
    custom_sid: str,
    logic_item: dict[str, Any],
    view_item: dict[str, Any],
    v: Validation,
) -> None:
    if not unit_has_shoot_attack(logic_item):
        return
    for attack in attack_rows(logic_item.get("defaultAttacks")):
        if attack.get("attackType_") != "shoot":
            continue
        dealer = attack.get("damageDealer")
        shoot_range = dealer.get("shootRange") if isinstance(dealer, dict) else None
        if shoot_range != -1:
            v.error(f"{faction_sid}:{custom_sid}: ranged default attack must use shootRange=-1, got {shoot_range!r}")

    melee_views = [
        attack
        for attack in attack_rows(view_item.get("alternativeAttacks"))
        if attack.get("abilityType") == "Ability_type_attack_alt"
    ]
    if not melee_views:
        v.error(f"{faction_sid}:{custom_sid}: ranged unit view must expose a melee alternative with Ability_type_attack_alt")
        return
    for attack in melee_views:
        if attack.get("infoDescription") != "ability_no_energy":
            v.error(f"{faction_sid}:{custom_sid}: ranged melee alternative must declare infoDescription='ability_no_energy'")


def validate_unit_attack_view_parity(
    faction_sid: str,
    custom_sid: str,
    logic_item: dict[str, Any],
    view_item: dict[str, Any],
    v: Validation,
) -> None:
    for key in ("defaultAttacks", "alternativeAttacks", "counterAttacks", "abilities"):
        logic_rows = logic_item.get(key)
        view_rows = view_item.get(key)
        if not isinstance(logic_rows, list) or not isinstance(view_rows, list):
            continue
        if len(view_rows) < len(logic_rows):
            v.error(
                f"{faction_sid}:{custom_sid}: core unit view {key} has {len(view_rows)} row(s), "
                f"but logic has {len(logic_rows)}; release dxr.Init indexes matching view rows"
            )


def validate_core_unit_attack_view_parity(core: Path, v: Validation) -> None:
    logic_by_sid: dict[str, tuple[str, dict[str, Any]]] = {}
    view_by_sid: dict[str, tuple[str, dict[str, Any]]] = {}
    for member in core_member_names(core, "DB/units/units_logics/", ".json"):
        doc = read_core_json(core, member)
        rows = doc.get("array") if isinstance(doc, dict) else None
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            sid = row.get("id") or row.get("sid")
            if isinstance(sid, str):
                logic_by_sid[sid] = (member, row)
    for member in core_member_names(core, "DB/units/units_views/", ".json"):
        doc = read_core_json(core, member)
        rows = doc.get("array") if isinstance(doc, dict) else None
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            sid = row.get("id") or row.get("sid")
            if isinstance(sid, str):
                view_by_sid[sid] = (member, row)

    for sid, (logic_member, logic_item) in sorted(logic_by_sid.items()):
        view_entry = view_by_sid.get(sid)
        if view_entry is None:
            continue
        view_member, view_item = view_entry
        for key in ("defaultAttacks", "alternativeAttacks", "counterAttacks", "abilities"):
            logic_rows = logic_item.get(key)
            view_rows = view_item.get(key)
            if not isinstance(logic_rows, list) or not isinstance(view_rows, list):
                continue
            if len(view_rows) < len(logic_rows):
                v.error(
                    f"{sid}: {view_member} {key} has {len(view_rows)} row(s), "
                    f"but {logic_member} has {len(logic_rows)}; release dxr.Init indexes matching view rows"
                )


FORTRESS_DONOR_MECHANIC_TOKENS = (
    "griffin_",
    "qilin_",
    "wisp_",
    "minos_",
    "angel_",
    "hydra_passive_",
    "hydra_ability_",
    "hydra_buff",
    "armed_ability_hydra",
)
REQUIRED_UNIT_STAT_FIELDS = ("hp", "offence", "defence", "damageMin", "damageMax", "speed")
REQUIRED_UNIT_STAT_MODIFIER_SETS = ("inDmgMods", "outDmgMods")
BAD_RESOURCE_ALIASES = {"crystal", "gems", "sulfur"}
BAD_HERO_STAT_FIELDS = {"finalAbilityDamageBonusPercent", "abilityEnergyLevelsCostBonus"}
HOMM3_COVE_GROUNDSIGHT_SOURCE_MAGIC_PATH = "DB/magics/world_primal_magics.json"
HOMM3_COVE_TREASURE_HUNTING_MAGIC_PATH = "DB/magics/world_neutral_magics.json"
HOMM3_COVE_TREASURE_HUNTING_MAGIC_SIDS = (
    "homm3_cove_treasure_hunting_1",
    "homm3_cove_treasure_hunting_2",
    "homm3_cove_treasure_hunting_3",
)
HOMM3_SKILL_GRANTED_MAGIC_TREE_KEYS = ("learnCost",)
HOMM3_PRIMAL_MAGIC_EXPECTED_RANKS = {
    "primal_1_magic_thunderbolt": 1,
    "primal_2_magic_thick_hide": 1,
    "primal_3_magic_wean": 1,
    "primal_17_magic_groundsight": 1,
    "primal_4_magic_fire_globe": 2,
    "primal_5_magic_crystal_crown": 2,
    "primal_6_magic_ice_bolt": 2,
    "primal_7_magic_wall_of_flame": 3,
    "primal_8_magic_cave_in": 3,
    "primal_9_magic_earths_rage": 3,
    "primal_16_magic_stone_fangs": 3,
    "primal_10_magic_primordial_purity": 4,
    "primal_12_magic_chain_lightning": 4,
    "primal_13_magic_avalanche": 4,
    "primal_18_magic_primordial_chaos": 4,
    "primal_11_magic_armageddon": 5,
    "primal_14_magic_hksmillas_rampage": 5,
    "primal_15_magic_summon_primal_remnant": 5,
}

def validate_homm3_primal_magic_tier_contract(core: Path, v: Validation) -> None:
    rows_by_id: dict[str, dict[str, Any]] = {}
    for member in (
        "DB/magics/battle_primal_magics.json",
        "DB/magics/world_primal_magics.json",
    ):
        doc = read_core_json(core, member)
        rows = (doc or {}).get("array") if isinstance(doc, dict) else None
        if not isinstance(rows, list):
            v.error(f"Primal Magic tier contract: malformed or missing {member}")
            continue
        for row in rows:
            if isinstance(row, dict) and isinstance(row.get("id"), str):
                rows_by_id[row["id"]] = row
    for spell_sid, expected_rank in HOMM3_PRIMAL_MAGIC_EXPECTED_RANKS.items():
        row = rows_by_id.get(spell_sid)
        if not isinstance(row, dict):
            v.error(f"Primal Magic tier contract: missing vanilla spell {spell_sid!r}")
            continue
        if row.get("school_") != "primal":
            v.error(f"Primal Magic tier contract: {spell_sid} must remain school_='primal', got {row.get('school_')!r}")
        if row.get("rank") != expected_rank:
            v.error(f"Primal Magic tier contract: {spell_sid} must be rank {expected_rank}, got {row.get('rank')!r}")
        if "learnCost" not in row:
            v.error(f"Primal Magic tier contract: {spell_sid} must remain researchable with learnCost")
    unexpected_primal_research_rows = [
        sid
        for sid, row in rows_by_id.items()
        if sid not in HOMM3_PRIMAL_MAGIC_EXPECTED_RANKS
        and isinstance(row, dict)
        and row.get("school_") == "primal"
        and "rank" in row
        and "learnCost" in row
    ]
    if unexpected_primal_research_rows:
        v.error(f"Primal Magic tier contract: unexpected researchable Primal spell row(s): {unexpected_primal_research_rows!r}")
    unexpected_cove_rows = [sid for sid in rows_by_id if sid.startswith("homm3_cove_treasure_hunting")]
    if unexpected_cove_rows:
        v.error(f"Primal Magic tier contract: Cove Treasure Hunting variants must not occupy Primal spell tiers: {unexpected_cove_rows!r}")

def validate_custom_faction_skill_bonus(
    faction_sid: str,
    skill_sid: str,
    context: str,
    bonus: dict[str, Any],
    custom_units: set[str],
    core: Path,
    v: Validation,
    hero_abilities: set[str] | None = None,
) -> None:
    parameters = bonus.get("parameters")
    if not isinstance(parameters, list) or not parameters:
        return
    bonus_type = bonus.get("type")
    if bonus_type == "heroStat" and parameters[0] in BAD_HERO_STAT_FIELDS:
        v.error(f"{faction_sid}: faction skill {skill_sid} {context} uses UnitStat field {parameters[0]!r} as heroStat")
    if bonus_type == "heroBattleAbility" and isinstance(parameters[0], str) and hero_abilities is not None:
        hero_abilities.add(parameters[0])
    if bonus_type == "unitStat":
        receivers = bonus.get("receivers")
        if isinstance(receivers, list):
            for receiver in receivers:
                if receiver not in custom_units:
                    v.error(f"{faction_sid}: faction skill {skill_sid} {context} has unknown unitStat receiver {receiver!r}")
                    continue
                member = f"DB/units/units_logics/{faction_sid}/{receiver}_l.json"
                if not core_has_member(core, member):
                    v.error(f"{faction_sid}: faction skill {skill_sid} {context} receiver {receiver!r} has no unit logic row {member}")



def validate_homm3_cove_treasure_hunting_magic_contract(
    core: Path,
    faction_sid: str,
    skill_row: dict[str, Any],
    v: Validation,
) -> None:
    if faction_sid != "homm3_cove":
        return
    levels = skill_row.get("parametersPerLevel")
    if not isinstance(levels, list) or len(levels) != len(HOMM3_COVE_TREASURE_HUNTING_MAGIC_SIDS):
        v.error(
            "homm3_cove: Treasure Hunting must have exactly "
            f"{len(HOMM3_COVE_TREASURE_HUNTING_MAGIC_SIDS)} skill levels, got "
            f"{len(levels) if isinstance(levels, list) else levels!r}"
        )
        levels = levels if isinstance(levels, list) else []
    magic_doc = read_core_json(core, HOMM3_COVE_TREASURE_HUNTING_MAGIC_PATH)
    magic_rows = (magic_doc or {}).get("array") if isinstance(magic_doc, dict) else None
    rows_by_id = {row.get("id"): row for row in magic_rows if isinstance(row, dict)} if isinstance(magic_rows, list) else {}
    primal_doc = read_core_json(core, HOMM3_COVE_GROUNDSIGHT_SOURCE_MAGIC_PATH)
    primal_rows = (primal_doc or {}).get("array") if isinstance(primal_doc, dict) else None
    if isinstance(primal_rows, list):
        stale_primal_sids = [row.get("id") for row in primal_rows if isinstance(row, dict) and row.get("id") in HOMM3_COVE_TREASURE_HUNTING_MAGIC_SIDS]
        if stale_primal_sids:
            v.error(f"homm3_cove: Treasure Hunting skill-granted magic rows must not live in Primal research table: {stale_primal_sids!r}")
    for level_index, expected_sid in enumerate(HOMM3_COVE_TREASURE_HUNTING_MAGIC_SIDS, start=1):
        level = levels[level_index - 1] if level_index <= len(levels) else None
        if not isinstance(level, dict):
            v.error(f"homm3_cove: Treasure Hunting level {level_index} must be an object granting {expected_sid!r}")
            continue
        level_grants = [
            bonus.get("parameters", [None])[0]
            for bonus in level.get("bonuses") or []
            if isinstance(bonus, dict)
            and bonus.get("type") == "heroMagicAddition"
            and isinstance(bonus.get("parameters"), list)
            and bonus.get("parameters")
        ]
        if level_grants != [expected_sid]:
            v.error(f"homm3_cove: Treasure Hunting level {level_index} must grant only {expected_sid!r}, got {level_grants!r}")
    for index, magic_sid in enumerate(HOMM3_COVE_TREASURE_HUNTING_MAGIC_SIDS):
        row = rows_by_id.get(magic_sid)
        if not isinstance(row, dict):
            v.error(f"homm3_cove: missing skill-granted Treasure Hunting world magic row {magic_sid!r}")
            continue
        if row.get("xHomm3SkillGrantedOnly") is not True:
            v.error(f"homm3_cove: {magic_sid} must be marked xHomm3SkillGrantedOnly=true")
        for key in HOMM3_SKILL_GRANTED_MAGIC_TREE_KEYS:
            if key in row:
                v.error(f"homm3_cove: {magic_sid} must not carry tree/learn key {key!r}")
        if row.get("school_") != "neutral":
            v.error(f"homm3_cove: {magic_sid} must use neutral magic school so it cannot enter Primal spell research")
        if row.get("usedOnMap") is not True:
            v.error(f"homm3_cove: {magic_sid} must remain a world-map magic row")
        if row.get("manaCost") != [0, 0, 0, 0]:
            v.error(f"homm3_cove: {magic_sid} must remain 0-mana at all levels")
        world_magic = row.get("worldMagic")
        expected_settings = [index, index, index, index]
        if not isinstance(world_magic, dict):
            v.error(f"homm3_cove: {magic_sid} must have worldMagic Groundsight payload")
            continue
        if world_magic.get("settingPerLevels") != expected_settings:
            v.error(f"homm3_cove: {magic_sid} must pin Groundsight settingPerLevels to {expected_settings!r}")
        magic_settings = world_magic.get("magicSettings")
        if not isinstance(magic_settings, list) or len(magic_settings) != 3:
            v.error(f"homm3_cove: {magic_sid} must keep exactly three native Groundsight magicSettings")
            continue
        for setting_index, setting in enumerate(magic_settings):
            if not isinstance(setting, dict) or setting.get("mechType") != "groundsight":
                v.error(f"homm3_cove: {magic_sid} worldMagic.magicSettings[{setting_index}] must use native groundsight")
                continue
            parameters = setting.get("parameters")
            if parameters != [str(setting_index)]:
                v.error(f"homm3_cove: {magic_sid} worldMagic.magicSettings[{setting_index}] parameters must be {[str(setting_index)]!r}, got {parameters!r}")
    for magic_path in core_member_names(core, "DB/magics/", ".json"):
        if magic_path == HOMM3_COVE_TREASURE_HUNTING_MAGIC_PATH:
            continue
        doc = read_core_json(core, magic_path)
        rows = (doc or {}).get("array") if isinstance(doc, dict) else None
        if not isinstance(rows, list):
            continue
        duplicate_sids = [row.get("id") for row in rows if isinstance(row, dict) and row.get("id") in HOMM3_COVE_TREASURE_HUNTING_MAGIC_SIDS]
        if duplicate_sids:
            v.error(f"homm3_cove: Treasure Hunting skill-granted magic rows must not be duplicated in {magic_path}: {duplicate_sids!r}")


def validate_global_custom_subskill_rows(subskill_rows: list[Any], v: Validation) -> None:
    for row in subskill_rows:
        if not isinstance(row, dict):
            continue
        subskill_sid = row.get("id")
        if not isinstance(subskill_sid, str) or not subskill_sid.startswith("sub_skill_faction_homm3_"):
            continue
        for bonus_index, bonus in enumerate(row.get("bonuses") or [], start=1):
            if not isinstance(bonus, dict):
                continue
            parameters = bonus.get("parameters")
            if (
                bonus.get("type") == "heroStat"
                and isinstance(parameters, list)
                and parameters
                and parameters[0] in BAD_HERO_STAT_FIELDS
            ):
                v.error(f"{subskill_sid}: bonus {bonus_index} uses UnitStat field {parameters[0]!r} as heroStat")


def json_contains_token(value: Any, tokens: tuple[str, ...]) -> str | None:
    text = json.dumps(value, ensure_ascii=False)
    lower = text.lower()
    for token in tokens:
        if token.lower() in lower:
            return token
    return None


def json_contains_string_token(value: Any, tokens: tuple[str, ...]) -> str | None:
    if isinstance(value, str):
        lower = value.lower()
        for token in tokens:
            token_lower = token.lower()
            if lower == token_lower or (token_lower.endswith("_") and lower.startswith(token_lower)):
                return token
        return None
    if isinstance(value, dict):
        for item in value.values():
            match = json_contains_string_token(item, tokens)
            if match:
                return match
    if isinstance(value, list):
        for item in value:
            match = json_contains_string_token(item, tokens)
            if match:
                return match
    return None


def validate_unit_logic_stats(
    manifest: dict[str, Any],
    faction_sid: str,
    custom_sid: str,
    tier: int | None,
    logic_item: dict[str, Any],
    v: Validation,
) -> None:
    stats = logic_item.get("stats")
    if not isinstance(stats, dict):
        v.error(f"{faction_sid}:{custom_sid}: core unit logic must have stats object")
        return

    for field in REQUIRED_UNIT_STAT_FIELDS:
        if not isinstance(stats.get(field), (int, float)):
            v.error(f"{faction_sid}:{custom_sid}: core unit logic stats.{field} must be numeric, got {stats.get(field)!r}")

    for field in REQUIRED_UNIT_STAT_MODIFIER_SETS:
        modifier_set = stats.get(field)
        if not (isinstance(modifier_set, dict) and isinstance(modifier_set.get("list"), list)):
            v.error(f"{faction_sid}:{custom_sid}: core unit logic stats.{field} must be an initialized modifier-set object")

    damage_min = stats.get("damageMin")
    damage_max = stats.get("damageMax")
    if isinstance(damage_min, (int, float)) and isinstance(damage_max, (int, float)):
        if damage_min > damage_max:
            v.error(f"{faction_sid}:{custom_sid}: core unit logic damageMin {damage_min} exceeds damageMax {damage_max}")
        if tier in {1, 2} and damage_max > 12:
            v.error(f"{faction_sid}:{custom_sid}: tier {tier} damageMax {damage_max} is suspiciously high")

    audit = logic_item.get("xHomm3ImplementationAudit")
    if isinstance(audit, dict):
        stats_source = audit.get("statsSource")
        if isinstance(stats_source, str) and stats_source.startswith("missing source stat row"):
            report_missing_release_surface(manifest, v, f"{faction_sid}:{custom_sid}: {stats_source}")

    unit_cost = logic_item.get("unitCost")
    cost_rows = unit_cost.get("costResArray") if isinstance(unit_cost, dict) else None
    if isinstance(cost_rows, list):
        for cost in cost_rows:
            if not isinstance(cost, dict):
                continue
            resource = cost.get("name")
            if resource in BAD_RESOURCE_ALIASES:
                v.error(f"{faction_sid}:{custom_sid}: unitCost uses noncanonical resource alias {resource!r}")


def collect_json_sid_values(value: Any, result: set[str]) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if key == "sid" and isinstance(child, str):
                result.add(child)
            collect_json_sid_values(child, result)
    elif isinstance(value, list):
        for child in value:
            collect_json_sid_values(child, result)


def manifest_donor_unit_sid_for_variant(line: dict[str, Any], suffix: str) -> str | None:
    variant_sids = line.get("donorVariantSids")
    if isinstance(variant_sids, dict):
        sid = variant_sids.get(suffix)
        if isinstance(sid, str) and sid:
            return sid
    donor_base = line.get("donorBaseSid")
    if isinstance(donor_base, str) and donor_base:
        return donor_base + suffix
    return None


def manifest_donor_unit_sids(manifest: dict[str, Any]) -> set[str]:
    variants = manifest.get("unitVariants", ["", "_upg", "_upg_alt"])
    result: set[str] = set()
    for line in all_unit_lines(manifest):
        for suffix in variants:
            sid = manifest_donor_unit_sid_for_variant(line, suffix)
            if sid:
                result.add(sid)
    return result


# Fortress Hunting Grounds trophy meter; must match apply_release_core_overlay.py
# HOMM3_FORTRESS_HUNTING_GROUNDS_* and Homm3FortressHuntingGroundsHook.CapByLevel.
FORTRESS_HUNTING_GROUNDS_CAPS = {1: 8, 2: 7, 3: 6}
FORTRESS_HUNTING_GROUNDS_MILESTONES = {
    1: ((3, 1, 0), (6, 1, 1)),
    2: ((2, 1, 0), (5, 1, 1)),
    3: ((2, 1, 0), (4, 1, 1), (6, 2, 1)),
}
FORTRESS_HUNTING_GROUNDS_HOOK = (
    ROOT / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod" / "Homm3FortressHuntingGroundsHook.cs"
)


def validate_fortress_hunting_grounds_rows(core: Path, skill_sid: str, row: dict[str, Any], v: Validation) -> None:
    """Hunting Grounds: ranks carry no static enemy penalty; 21 trophy hero buffs carry the creeping penalty."""
    label = "homm3_fortress: Hunting Grounds"
    try:
        hook_text = FORTRESS_HUNTING_GROUNDS_HOOK.read_text(encoding="utf-8-sig")
    except OSError:
        hook_text = ""
    if "CapByLevel = { 0, 8, 7, 6 }" not in hook_text or '"homm3_fortress_trophies_"' not in hook_text:
        v.error(f"{label}: {FORTRESS_HUNTING_GROUNDS_HOOK.name} must declare CapByLevel = {{ 0, 8, 7, 6 }} and the homm3_fortress_trophies_ prefix")
    for index, level in enumerate(row.get("parametersPerLevel") or [], start=1):
        for bonus in (level.get("bonuses") or []) if isinstance(level, dict) else []:
            if (
                isinstance(bonus, dict)
                and bonus.get("receiverAllegiance") == "enemy"
                and isinstance(bonus.get("parameters"), list)
                and bonus["parameters"][:1] in (["initiative"], ["speed"])
            ):
                v.error(f"{label}: rank {index} must not carry a static enemy {bonus['parameters'][0]} penalty (trophy buffs own it)")
    buffs_doc = read_core_json(core, "DB/heroes_buffs/heroes_buffs.json")
    buffs = {
        b.get("id"): b
        for b in (buffs_doc.get("array") if isinstance(buffs_doc, dict) else None) or []
        if isinstance(b, dict) and isinstance(b.get("id"), str)
    }
    map_text = lang_token_text_map(core, "Lang/english/texts/mapObjects.json")
    if map_text.get("homm3_fortress_trophies_buff_name") != "Hunting Grounds Trophies":
        v.error(f"{label}: mapObjects lang homm3_fortress_trophies_buff_name must be 'Hunting Grounds Trophies'")
    for lvl, cap in FORTRESS_HUNTING_GROUNDS_CAPS.items():
        for n in range(1, cap + 1):
            sid = f"homm3_fortress_trophies_{lvl}_{n}"
            buff = buffs.get(sid)
            if buff is None:
                v.error(f"{label}: Core heroes_buffs missing trophy buff {sid}")
                continue
            if buff.get("isDispellable") is not True or buff.get("hidden") is not False:
                v.error(f"{label}: {sid} must be visible and isDispellable=true (native Remove needs it)")
            ini = spd = 0
            for threshold, i, sp in FORTRESS_HUNTING_GROUNDS_MILESTONES[lvl]:
                if n >= threshold:
                    ini, spd = i, sp
            expected = []
            if ini:
                expected.append(["initiative", f"-{ini}"])
            if spd:
                expected.append(["speed", f"-{spd}"])
            actual = [
                b.get("parameters")
                for b in buff.get("bonuses") or []
                if isinstance(b, dict) and b.get("type") == "unitStat" and b.get("receiverAllegiance") == "enemy"
            ]
            if actual != expected or len(buff.get("bonuses") or []) != len(expected):
                v.error(f"{label}: {sid} enemy bonuses must be {expected!r}, got {buff.get('bonuses')!r}")
            text = map_text.get(f"{sid}_description") or ""
            if not text.startswith(f"Trophies {n}/{cap}") or ("restock: used" in text) != (n == cap):
                v.error(f"{label}: {sid}_description must start 'Trophies {n}/{cap}' and say 'restock: used' only at the cap")
    skill_text = lang_token_text_map(core, "Lang/english/texts/heroSkills.json")
    for token, expected_name in (
        (f"{skill_sid}_name", "Hunting Grounds"),
        (f"{skill_sid}_name_1", "Basic Hunting Grounds"),
        (f"{skill_sid}_name_2", "Advanced Hunting Grounds"),
        (f"{skill_sid}_name_3", "Expert Hunting Grounds"),
    ):
        if skill_text.get(token) != expected_name:
            v.error(f"{label}: {token} must be {expected_name!r}, got {skill_text.get(token)!r}")


def validate_custom_faction_skill_row(
    core: Path,
    manifest: dict[str, Any],
    skills_by_id: dict[str, dict[str, Any]],
    subskills_by_id: dict[str, dict[str, Any]],
    v: Validation,
) -> None:
    faction_sid = manifest["identity"]["factionSid"]
    expected_skill_sid = f"skill_faction_{faction_sid}"
    skill_sid = (manifest.get("skillsAndLaws") or {}).get("factionSkillSid")
    if skill_sid != expected_skill_sid:
        v.error(f"{faction_sid}: manifest skillsAndLaws.factionSkillSid must be {expected_skill_sid!r}, got {skill_sid!r}")
        return
    row = skills_by_id.get(skill_sid)
    if not isinstance(row, dict):
        report_missing_release_surface(manifest, v, f"{faction_sid}: core missing faction skill row {skill_sid}")
        return
    if faction_sid == "homm3_fortress":
        validate_fortress_hunting_grounds_rows(core, skill_sid, row, v)
    exact_text = FACTORY_BULWARK_EXACT_SKILL_TEXT.get(faction_sid)
    if exact_text is not None:
        expected_name, expected_desc, expected_rank_descs = exact_text
        expected_tokens = {
            f"{skill_sid}_name": expected_name,
            f"{skill_sid}_desc": expected_desc,
            **{f"{skill_sid}_name_{index}": f"{rank} {expected_name}" for index, rank in enumerate(("Basic", "Advanced", "Expert"), start=1)},
            **{f"{skill_sid}_desc_{index}": text for index, text in enumerate(expected_rank_descs, start=1)},
        }
        text_by_token = lang_token_text_map(core, "Lang/english/texts/heroSkills.json")
        for token, expected_text in expected_tokens.items():
            if text_by_token.get(token) != expected_text:
                v.error(f"{faction_sid}: exact faction-skill text {token} must be {expected_text!r}, got {text_by_token.get(token)!r}")
        if row.get("name") != f"{skill_sid}_name" or row.get("desc") != f"{skill_sid}_desc":
            v.error(f"{faction_sid}: exact faction skill row must reference its owned name/description tokens")
        levels = row.get("parametersPerLevel")
        if not isinstance(levels, list) or len(levels) != 3:
            v.error(f"{faction_sid}: exact faction skill row must contain exactly three rank rows")
        else:
            for index, level in enumerate(levels, start=1):
                expected_icon = skill_sid if index == 1 else f"{skill_sid}_{index}"
                if not isinstance(level, dict):
                    v.error(f"{faction_sid}: faction skill rank {index} must be an object")
                    continue
                if level.get("icon") != expected_icon:
                    v.error(f"{faction_sid}: faction skill rank {index} icon must be {expected_icon!r}")
                if level.get("name") != f"{skill_sid}_name_{index}" or level.get("desc") != f"{skill_sid}_desc_{index}":
                    v.error(f"{faction_sid}: faction skill rank {index} must reference exact owned rank text")
                # Match the working HoMM3 faction-skill load contract (Dungeon shape):
                # ignoreFractionsCount at every rank, empty Basic subSkills, and exactly
                # three Advanced/Expert subSkill SIDs that resolve in sub_skills.json.
                # Factory Expert may also grant Field Triage via heroBattleAbility.
                bonuses = level.get("bonuses")
                has_ignore = (
                    isinstance(bonuses, list)
                    and any(
                        isinstance(bonus, dict)
                        and bonus.get("type") == "unitBoolStat"
                        and bonus.get("parameters") == ["ignoreFractionsCount", "true"]
                        for bonus in bonuses
                    )
                )
                if not has_ignore:
                    v.error(
                        f"{faction_sid}: runtime-owned faction skill rank {index} must carry "
                        "unitBoolStat ignoreFractionsCount=true like working faction skills"
                    )
                if faction_sid == "homm3_factory" and index == 3:
                    has_field_triage = (
                        isinstance(bonuses, list)
                        and any(
                            isinstance(bonus, dict)
                            and bonus.get("type") == "heroBattleAbility"
                            and isinstance(bonus.get("parameters"), list)
                            and bonus.get("parameters")
                            and bonus["parameters"][0] == "skill_faction_homm3_factory_ability_field_triage"
                            for bonus in bonuses
                        )
                    )
                    if not has_field_triage:
                        v.error(
                            f"{faction_sid}: Expert Split Assembly must grant "
                            "skill_faction_homm3_factory_ability_field_triage"
                        )
                subskills = level.get("subSkills")
                if index == 1:
                    if subskills != []:
                        v.error(f"{faction_sid}: faction skill Basic rank must keep empty subSkills like working factions")
                else:
                    if not isinstance(subskills, list) or len(subskills) != 3:
                        v.error(
                            f"{faction_sid}: faction skill rank {index} must expose exactly three "
                            "subSkill SIDs like every working HoMM3 faction skill"
                        )
                        continue
                    for subskill_sid in subskills:
                        if not isinstance(subskill_sid, str) or subskill_sid not in subskills_by_id:
                            v.error(
                                f"{faction_sid}: faction skill rank {index} subSkill {subskill_sid!r} "
                                "must resolve in DB/heroes_skills/sub_skills/sub_skills.json"
                            )
                        else:
                            sub_row = subskills_by_id[subskill_sid]
                            bonuses = sub_row.get("bonuses")
                            runtime_owned = isinstance(sub_row.get("xHomm3RuntimeHook"), str) and sub_row.get("xHomm3RuntimeHook")
                            if runtime_owned:
                                if not isinstance(bonuses, list):
                                    v.error(
                                        f"{faction_sid}: runtime-owned subSkill {subskill_sid!r} "
                                        "must ship a bonuses array (may be empty)"
                                    )
                            elif not isinstance(bonuses, list) or not bonuses:
                                v.error(
                                    f"{faction_sid}: subSkill {subskill_sid!r} must ship non-empty bonuses "
                                    "matching the working native-terrain subskill contract"
                                )
    contract = load_source_mechanics_contract(DEFAULT_SOURCE_MECHANICS_DIR, faction_sid, v)
    if isinstance(contract, dict) and isinstance(contract.get("mechanics"), list):
        skill_contracts = [
            mechanic
            for mechanic in contract["mechanics"]
            if isinstance(mechanic, dict)
            and mechanic.get("surface") == "faction_skill"
            and isinstance(mechanic.get("currentRows"), list)
            and skill_sid in mechanic["currentRows"]
        ]
        if len(skill_contracts) > 1:
            v.error(f"{faction_sid}: faction skill {skill_sid} is claimed by multiple source mechanics contracts")
        elif skill_contracts:
            mechanic = skill_contracts[0]
            if row.get("xHomm3SourceMechanic") != mechanic.get("id"):
                v.error(f"{faction_sid}: faction skill {skill_sid} must carry xHomm3SourceMechanic {mechanic.get('id')!r}")
            if row.get("xHomm3MechanicsStatus") != mechanic.get("status"):
                v.error(f"{faction_sid}: faction skill {skill_sid} must carry xHomm3MechanicsStatus {mechanic.get('status')!r}")
            forbidden = mechanic.get("forbiddenPlayerText")
            text_tokens = [row.get("name"), row.get("desc")]
            hero_ability_doc = read_core_json(core, "DB/heroes_abilities/heroes_abilities_base/hero_abilities.json")
            hero_abilities_by_id = {
                ability.get("id"): ability
                for ability in (hero_ability_doc.get("array") if isinstance(hero_ability_doc, dict) else []) or []
                if isinstance(ability, dict) and isinstance(ability.get("id"), str)
            }
            for level in row.get("parametersPerLevel") or []:
                if not isinstance(level, dict):
                    continue
                text_tokens.extend([level.get("name"), level.get("desc")])
                for subskill_sid in level.get("subSkills") or []:
                    if isinstance(subskill_sid, str):
                        forbidden_sid_tokens = mechanic.get("forbiddenSidTokens")
                        if isinstance(forbidden_sid_tokens, list):
                            for token in forbidden_sid_tokens:
                                if isinstance(token, str) and token and token in subskill_sid:
                                    v.error(
                                        f"{faction_sid}: faction skill {skill_sid} still references forbidden SID token "
                                        f"{token!r} via subSkill {subskill_sid!r}"
                                    )
                    subskill = subskills_by_id.get(subskill_sid) if isinstance(subskill_sid, str) else None
                    if isinstance(subskill, dict):
                        text_tokens.extend([subskill.get("name"), subskill.get("desc")])
                for bonus in level.get("bonuses") or []:
                    if not isinstance(bonus, dict) or bonus.get("type") != "heroBattleAbility":
                        continue
                    params = bonus.get("parameters")
                    ability_sid = params[0] if isinstance(params, list) and params else None
                    ability = hero_abilities_by_id.get(ability_sid) if isinstance(ability_sid, str) else None
                    if isinstance(ability, dict):
                        for ability_level in ability.get("levels") or []:
                            if isinstance(ability_level, dict):
                                text_tokens.extend([ability_level.get("name"), ability_level.get("description")])
            if isinstance(forbidden, list):
                text_by_token = lang_token_text_map(core, "Lang/english/texts/heroSkills.json")
                text_by_token.update(lang_token_text_map(core, "Lang/english/texts/heroInfo.json"))
                text_by_token.update(lang_token_text_map(core, "Lang/english/texts/unitsAbility.json"))
                for token in text_tokens:
                    if not isinstance(token, str):
                        continue
                    text = text_by_token.get(token)
                    if not isinstance(text, str):
                        v.error(f"{faction_sid}: faction skill source contract token {token!r} was not found in heroSkills.json or heroInfo.json")
                        continue
                    lowered = text.lower()
                    for phrase in forbidden:
                        if isinstance(phrase, str) and phrase.lower() in lowered:
                            v.error(f"{faction_sid}: faction skill {skill_sid} player text still claims forbidden source phrase {phrase!r}")
        if faction_sid == "homm3_bulwark" and not skill_contracts:
            pending = [mechanic for mechanic in contract["mechanics"] if isinstance(mechanic, dict) and mechanic.get("id") == "bulwark.runes"]
            if len(pending) != 1 or pending[0].get("status") != "runtime-pending":
                v.error("homm3_bulwark: unclaimed Runes Core row requires one runtime-pending bulwark.runes contract")
            if row.get("xHomm3ImplementedMechanics") or row.get("xHomm3SourceMechanic") or row.get("xHomm3MechanicsStatus"):
                v.error("homm3_bulwark: runtime-pending Runes Core row must not claim implemented/source-current mechanics metadata")

    validate_homm3_cove_treasure_hunting_magic_contract(core, faction_sid, row, v)
    custom_units = set(expand_units(manifest))
    referenced_subskills: set[str] = set()
    for level_index, level in enumerate(row.get("parametersPerLevel") or [], start=1):
        if not isinstance(level, dict):
            v.error(f"{faction_sid}: faction skill {skill_sid} level {level_index} must be an object")
            continue
        bonuses = level.get("bonuses")
        if not isinstance(bonuses, list):
            v.error(f"{faction_sid}: faction skill {skill_sid} level {level_index} must have bonuses list")
            continue
        hero_abilities: set[str] = set()
        for bonus in bonuses:
            if not isinstance(bonus, dict):
                continue
            validate_custom_faction_skill_bonus(faction_sid, skill_sid, f"level {level_index}", bonus, custom_units, core, v, hero_abilities)
        subskills = level.get("subSkills")
        if isinstance(subskills, list):
            for subskill_sid in subskills:
                if isinstance(subskill_sid, str) and subskill_sid:
                    referenced_subskills.add(subskill_sid)
        if faction_sid == "homm3_inferno":
            required_pair = {"skill_faction_demon_ability", "skill_faction_demon_ability_1"}
            if hero_abilities & required_pair and not required_pair <= hero_abilities:
                v.error(f"{faction_sid}: faction skill {skill_sid} level {level_index} must keep the native Demon summon/activate ability pair together")
    for subskill_sid in sorted(referenced_subskills):
        subskill = subskills_by_id.get(subskill_sid)
        if not isinstance(subskill, dict):
            v.error(f"{faction_sid}: faction skill {skill_sid} references missing subskill {subskill_sid!r}")
            continue
        for bonus_index, bonus in enumerate(subskill.get("bonuses") or [], start=1):
            if isinstance(bonus, dict):
                validate_custom_faction_skill_bonus(
                    faction_sid,
                    skill_sid,
                    f"subskill {subskill_sid} bonus {bonus_index}",
                    bonus,
                    custom_units,
                    core,
                    v,
                )


def validate_custom_squad_tree(core: Path, manifest: dict[str, Any], v: Validation) -> None:
    faction_sid = manifest["identity"]["factionSid"]
    prefix = manifest["coreOverlay"].get("squadTree")
    if not isinstance(prefix, str) or not prefix:
        return
    donor_sids = manifest_donor_unit_sids(manifest)
    if not donor_sids:
        return
    for member in core_member_names(core, prefix, ".json"):
        doc = read_core_json(core, member)
        if doc is None:
            continue
        sid_values: set[str] = set()
        collect_json_sid_values(doc, sid_values)
        for donor_sid in sorted(donor_sids & sid_values):
            v.error(f"{faction_sid}: generated squad {member} still references donor unit sid {donor_sid!r}")


def validate_biomes_info(core: Path, v: Validation) -> None:
    doc = read_core_json(core, "DB/biomes_info.json")
    mapping = doc.get("fractionsByBiome") if isinstance(doc, dict) else None
    rows = mapping.get("data") if isinstance(mapping, dict) else None
    if not isinstance(rows, list):
        return
    seen: set[str] = set()
    for row in rows:
        key = row.get("key") if isinstance(row, dict) else None
        if not isinstance(key, str):
            continue
        if key in seen:
            v.error(f"DB/biomes_info.json contains duplicate biome key {key!r}")
        seen.add(key)


def validate_custom_biome_pack(core: Path, v: Validation) -> None:
    tiles_doc = read_core_json(core, "DB/map/tiles/tiles.json")
    waters_doc = read_core_json(core, "DB/map/waters/waters.json")
    generator_doc = read_core_json(core, "generator/generator_config.json")
    environment_doc = read_core_json(core, "generator/generator_environment_assets.json")
    biomes_doc = read_core_json(core, "DB/biomes_info.json")
    obstructions_doc = read_core_json(core, "DB/arenas/arenas_obstructions_configs/test_obstructions.json")
    if not all(isinstance(doc, dict) for doc in (tiles_doc, waters_doc, generator_doc, environment_doc, biomes_doc, obstructions_doc)):
        v.error("custom biome pack validation could not read required Core terrain documents")
        return

    tile_rows = [
        row
        for row in tiles_doc.get("array", [])
        if isinstance(row, dict)
    ]
    tiles = {
        row.get("biome"): row
        for row in tile_rows
        if isinstance(row.get("biome"), str)
    }
    for biome, expected_id in CUSTOM_TERRAIN_ONLY_TILE_IDS.items():
        owners = [row.get("biome") for row in tile_rows if row.get("id") == expected_id]
        if owners != [biome]:
            v.error(f"custom biome pack tile id {expected_id} must belong only to {biome!r}, got {owners!r}")
    waters_by_name = {
        row.get("name"): row
        for row in waters_doc.get("array", [])
        if isinstance(row, dict) and isinstance(row.get("name"), str)
    }
    water_for_biome = {
        row.get("key"): row.get("val")
        for row in generator_doc.get("waterForBiome", [])
        if isinstance(row, dict) and isinstance(row.get("key"), str)
    }
    environment_sids = {
        row.get("sid")
        for row in environment_doc.get("biomes", [])
        if isinstance(row, dict) and isinstance(row.get("sid"), str)
    }
    biome_to_faction = {
        row.get("key"): row.get("val")
        for row in (biomes_doc.get("fractionsByBiome") or {}).get("data", [])
        if isinstance(row, dict) and isinstance(row.get("key"), str)
    }
    obstruction_rows = [
        row
        for row in obstructions_doc.get("array", [])
        if isinstance(row, dict)
    ]

    faction_biomes: dict[str, str] = {}
    for member in core_member_names(core, "DB/fractions/", ".json"):
        doc = read_core_json(core, member)
        rows = doc.get("array") if isinstance(doc, dict) else None
        if not isinstance(rows, list):
            continue
        for row in rows:
            if isinstance(row, dict) and isinstance(row.get("id"), str) and isinstance(row.get("biome"), str):
                faction_biomes[row["id"]] = row["biome"]

    custom_biomes = sorted(set(CUSTOM_BIOME_FACTIONS) | set(CUSTOM_TERRAIN_ONLY_BIOMES))
    for biome in custom_biomes:
        faction = CUSTOM_BIOME_FACTIONS.get(biome)
        terrain_only = biome in CUSTOM_TERRAIN_ONLY_BIOMES
        expected_tile_id = CUSTOM_TERRAIN_ONLY_TILE_IDS.get(biome)
        if expected_tile_id is None:
            tile = tiles.get(biome)
        else:
            tile = next((row for row in tile_rows if row.get("biome") == biome and row.get("id") == expected_tile_id), None)
        if not isinstance(tile, dict):
            v.error(f"custom biome pack missing DB/map/tiles row for {biome!r}")
            continue
        expected_water = "water " + biome.lower()
        water = waters_by_name.get(expected_water)
        if not isinstance(water, dict):
            v.error(f"custom biome pack missing DB/map/waters row named {expected_water!r}")
        elif water.get("id") != tile.get("id"):
            v.error(f"custom biome pack water id for {biome!r} must match tile id {tile.get('id')!r}, got {water.get('id')!r}")
        if water_for_biome.get(biome) != expected_water:
            v.error(f"custom biome pack generator waterForBiome {biome!r} must be {expected_water!r}, got {water_for_biome.get(biome)!r}")
        if biome not in environment_sids:
            v.error(f"custom biome pack missing generator_environment_assets biome {biome!r}")
        if terrain_only:
            if biome_to_faction.get(biome) is not None:
                v.error(f"terrain-only custom biome {biome!r} must not map to a faction, got {biome_to_faction.get(biome)!r}")
        else:
            if biome_to_faction.get(biome) != faction:
                v.error(f"custom biome pack DB/biomes_info.json must map {biome!r} to {faction!r}, got {biome_to_faction.get(biome)!r}")
            if faction_biomes.get(faction) != biome:
                v.error(f"custom biome pack faction {faction!r} must use biome {biome!r}, got {faction_biomes.get(faction)!r}")
        donor = CUSTOM_BIOME_ARENA_DONORS.get(biome)
        for row in obstruction_rows:
            pairs = ((row.get("models") or {}).get("keyValuePairs") if isinstance(row.get("models"), dict) else None)
            if not isinstance(pairs, list):
                continue
            by_key = {pair.get("key"): pair.get("value") for pair in pairs if isinstance(pair, dict)}
            if biome not in by_key:
                v.error(f"custom biome pack obstruction {row.get('id')!r} missing model row for biome {biome!r}")
            elif donor in by_key and by_key[biome] != by_key[donor]:
                v.error(
                    f"custom biome pack obstruction {row.get('id')!r} biome {biome!r} "
                    f"must clone donor {donor!r} models"
                )


def validate_upgrade_base_sid_chain(
    core: Path,
    manifest: dict[str, Any],
    v: Validation,
) -> None:
    faction_sid = manifest["identity"]["factionSid"]
    if faction_sid in {"homm3_stronghold", "homm3_tower"}:
        return
    variants = manifest.get("unitVariants", ["", "_upg", "_upg_alt"])
    for line in all_unit_lines(manifest):
        previous_sid: str | None = None
        for suffix in variants:
            custom_sid = unit_sid_for_variant(line, suffix)
            member = f"DB/units/units_logics/{faction_sid}/{custom_sid}_l.json"
            item = first_array_item(read_core_json(core, member))
            if not isinstance(item, dict):
                previous_sid = custom_sid
                continue
            expected_base = previous_sid
            actual_base = item.get("baseSid")
            if expected_base is None:
                if actual_base not in (None, ""):
                    v.error(f"{faction_sid}:{custom_sid}: base unit baseSid must be empty, got {actual_base!r}")
            elif actual_base != expected_base:
                v.error(f"{faction_sid}:{custom_sid}: upgraded unit baseSid must be {expected_base!r}, got {actual_base!r}")
            previous_sid = custom_sid


def validate_custom_city_scene_name(manifest: dict[str, Any], city_doc: Any, v: Validation) -> None:
    faction_sid = manifest["identity"]["factionSid"]
    item = first_array_item(city_doc)
    if item is None:
        return
    expected_scene_name = (manifest.get("releaseScaffold") or {}).get("citySceneName")
    if not isinstance(expected_scene_name, str) or not expected_scene_name:
        v.error(f"{faction_sid}: releaseScaffold.citySceneName is required for city row validation")
        return
    if item.get("sceneName") != expected_scene_name:
        v.error(f"{faction_sid}: city row sceneName must be {expected_scene_name!r}, got {item.get('sceneName')!r}")

CITY_FACTORY_DONOR_CITY_MEMBER = "DB/objects_logic/cities/human_city.json"


def validate_owned_world_city_scene_slots(core: Path, manifest: dict[str, Any], city_doc: Any, v: Validation) -> None:
    """Owned cityFactory worlds are the cityHuman2 donor graph: native BhBuildingsManager finds a
    building's slot by the cityHuman2 slot string, so every building the vanilla human_city row
    places must carry that same sceneSlot. A donor-city slot string (nature_city "Build_Main")
    binds nothing and parks the town presentation forever (Conflux, 2026-09-26)."""
    faction_sid = manifest["identity"]["factionSid"]
    scene_name = (manifest.get("releaseScaffold") or {}).get("citySceneName")
    if scene_name != "cityFactory":
        return
    donor = read_core_json(core, CITY_FACTORY_DONOR_CITY_MEMBER)
    if donor is None:
        v.error(f"{faction_sid}: cannot check cityFactory sceneSlots; core lacks {CITY_FACTORY_DONOR_CITY_MEMBER}")
        return
    expected = {
        row["sid"]: row["sceneSlot"]
        for row in collect_city_building_config_rows(donor)
        if isinstance(row.get("sceneSlot"), str)
    }
    if not expected:
        v.error(f"{faction_sid}: {CITY_FACTORY_DONOR_CITY_MEMBER} has no sceneSlot rows")
        return
    for row in collect_city_building_config_rows(city_doc):
        sid = row.get("sid")
        want = expected.get(sid)
        if want is not None and row.get("sceneSlot") != want:
            v.error(
                f"{faction_sid}: cityFactory building {sid} sceneSlot must be the cityHuman2 slot {want!r}, "
                f"got {row.get('sceneSlot')!r} (rerun tools/release_port/apply_release_core_overlay.py)"
            )


def validate_faction_presentation_row(core: Path, manifest: dict[str, Any], v: Validation) -> None:
    faction_sid = manifest["identity"]["factionSid"]
    overlay = manifest.get("coreOverlay") or {}
    member = overlay.get("factionJson")
    if not isinstance(member, str) or not member:
        return
    item = first_array_item(read_core_json(core, member))
    if item is None:
        report_missing_release_surface(manifest, v, f"{faction_sid}: core missing or malformed faction row {member}")
        return
    identity = manifest.get("identity") or {}
    scaffold = manifest.get("releaseScaffold") or {}
    expected = {
        "id": faction_sid,
        "name": identity.get("displayNameToken"),
        "desc": identity.get("descriptionToken"),
        "narrativeDesc": identity.get("descriptionToken"),
    }
    if isinstance(scaffold, dict) and scaffold:
        expected.update(
            {
                "biome": scaffold.get("biome"),
                "icon": scaffold.get("factionIcon"),
                "iconFractionLaws": scaffold.get("factionLawIcon"),
            }
        )
    for key, expected_value in expected.items():
        if expected_value and item.get(key) != expected_value:
            v.error(f"{faction_sid}: faction row {key} must be {expected_value!r}, got {item.get(key)!r}")

    city_names = item.get("cityNames")
    if isinstance(city_names, list) and city_names:
        expected_prefix = f"{identity.get('citySid')}_name_"
        for token in city_names:
            if isinstance(token, str) and token.startswith(expected_prefix):
                break
        else:
            v.error(f"{faction_sid}: faction row cityNames must include {expected_prefix}*, got {city_names!r}")

    donor_fraction = identity.get("donorFactionSid")
    donor_city = identity.get("donorCitySid")
    donor_tokens = tuple(
        token
        for token in (
            f"{donor_fraction}_name" if isinstance(donor_fraction, str) else None,
            f"{donor_city}_name" if isinstance(donor_city, str) else None,
            f"fraction_law_{donor_fraction}_" if isinstance(donor_fraction, str) else None,
        )
        if token
    )
    leaked = json_contains_string_token(item, donor_tokens)
    if leaked:
        v.error(f"{faction_sid}: faction row leaks donor presentation token {leaked!r}")


def validate_custom_town_siege_wall_construction(core: Path, v: Validation) -> None:
    """Require custom-town presets to expose a constructed native siege wall."""
    matches: list[tuple[str, dict[str, Any]]] = []
    for member in core_member_names(core, "DB/buildings_constructions/", ".json"):
        doc = read_core_json(core, member)
        rows = doc.get("array") if isinstance(doc, dict) else None
        if not isinstance(rows, list):
            continue
        matches.extend(
            (member, row)
            for row in rows
            if isinstance(row, dict)
            and row.get("id") == HOMM3_CUSTOM_TOWN_BUILDINGS_CONSTRUCTION_SID
        )
    if len(matches) != 1:
        v.error(
            "custom town siege-wall construction preset must occur exactly once in Core "
            f"(found {len(matches)})"
        )
        return
    member, preset = matches[0]
    buildings = preset.get("buildings")
    wall_rows = (
        [row for row in buildings if isinstance(row, dict) and row.get("sid") == "Build_Wall"]
        if isinstance(buildings, list)
        else []
    )
    if len(wall_rows) != 1:
        v.error(f"{member}: custom town siege-wall preset must contain exactly one Build_Wall row")
        return
    wall = wall_rows[0]
    level = wall.get("level")
    if (
        wall.get("isConstructed") is not True
        or isinstance(level, bool)
        or not isinstance(level, int)
        or level < 1
    ):
        v.error(
            f"{member}: custom town Build_Wall must be constructed at level >= 1 "
            f"(got isConstructed={wall.get('isConstructed')!r}, level={level!r})"
        )


def validate_core_members(
    core: Path,
    manifests: list[tuple[Path, dict[str, Any]]],
    v: Validation,
    source_mechanics_dir: Path = DEFAULT_SOURCE_MECHANICS_DIR,
    hero_override_dir: Path = DEFAULT_HERO_OVERRIDE_DIR,
    ability_override_dir: Path = DEFAULT_ABILITY_OVERRIDE_DIR,
    *,
    strict_source_mechanics_metadata: bool = True,
    no_design_debt: bool = False,
) -> None:
    if not core.exists():
        v.error(f"core path does not exist: {core}")
        return
    validate_custom_town_siege_wall_construction(core, v)
    validate_homm3_primal_magic_tier_contract(core, v)
    data_doc = read_core_json(core, "DB/data.json")
    data_factions = set()
    data_available_factions = set()
    if isinstance(data_doc, dict):
        data_factions = {sid for sid in data_doc.get("fractions") or [] if isinstance(sid, str)}
        data_available_factions = {sid for sid in data_doc.get("availableFractions") or [] if isinstance(sid, str)}
    skill_doc = read_core_json(core, "DB/heroes_skills/skills/skills.json")
    skill_rows = (skill_doc or {}).get("array") if isinstance(skill_doc, dict) else None
    skills_by_id = {row.get("id"): row for row in skill_rows if isinstance(row, dict)} if isinstance(skill_rows, list) else {}
    subskill_doc = read_core_json(core, "DB/heroes_skills/sub_skills/sub_skills.json")
    subskill_rows = (subskill_doc or {}).get("array") if isinstance(subskill_doc, dict) else None
    subskills_by_id = {row.get("id"): row for row in subskill_rows if isinstance(row, dict)} if isinstance(subskill_rows, list) else {}
    if isinstance(subskill_rows, list):
        validate_global_custom_subskill_rows(subskill_rows, v)
    expected_map_mesh_by_sid = load_homm3_import_map_meshes(v)
    skinned_preview_by_sid = load_homm3_import_skinned_preview_meshes(v)
    battle_shell_by_sid, map_shell_by_sid = load_homm3_import_shell_paths(v)
    core_unit_mesh_paths, core_unit_map_mesh_paths = load_core_unit_view_prefab_paths(core)
    validate_biomes_info(core, v)
    validate_custom_biome_pack(core, v)
    validate_core_unit_attack_view_parity(core, v)
    if no_design_debt:
        validate_no_design_debt(core, manifests, v)
    for _path, manifest in manifests:
        faction_sid = manifest["identity"]["factionSid"]
        if not core_overlay_enabled(manifest):
            for key, values in (("fractions", data_factions), ("availableFractions", data_available_factions)):
                if faction_sid in values:
                    v.error(f"{faction_sid}: core-disabled or release-blocked faction must not be advertised in DB/data.json {key}")
            continue
        for key, values in (("fractions", data_factions), ("availableFractions", data_available_factions)):
            if faction_sid not in values:
                v.error(f"{faction_sid}: core-enabled faction is missing from DB/data.json {key}")
        overlay = manifest["coreOverlay"]
        optional_keys = set(overlay.get("optionalCoreKeys", []))
        for key in ("factionJson", "cityLogic", "lawsTable", "squadTree", "heroSubClasses", "heroSpecializations"):
            member = overlay[key]
            if not core_has_member(core, member):
                if key in optional_keys:
                    v.warn(f"{faction_sid}: core missing optional current-debt {key} member {member}")
                else:
                    report_missing_release_surface(manifest, v, f"{faction_sid}: core missing {key} member {member}")
        validate_faction_presentation_row(core, manifest, v)
        city_doc = read_core_json(core, overlay["cityLogic"])
        if city_doc is not None:
            validate_custom_city_scene_name(manifest, city_doc, v)
            validate_owned_world_city_scene_slots(core, manifest, city_doc, v)
            validate_city_building_presentation(core, manifest, city_doc, v)
            validate_additional_recruitment_city_rows(manifest, city_doc, v)
            validate_source_mechanics_contract(
                core,
                source_mechanics_dir,
                manifest,
                city_doc,
                v,
                strict_metadata=strict_source_mechanics_metadata,
            )
        validate_custom_faction_skill_row(core, manifest, skills_by_id, subskills_by_id, v)
        validate_custom_squad_tree(core, manifest, v)
        validate_upgrade_base_sid_chain(core, manifest, v)
        validate_hero_override_specializations(core, manifest, v, hero_override_dir)
        validate_unit_branch_roles(core, manifest, v, ability_override_dir)
        tier_by_sid = {
            unit_sid_for_variant(line, suffix): line.get("tier")
            for line in all_unit_lines(manifest)
            for suffix in manifest.get("unitVariants", ["", "_upg", "_upg_alt"])
        }
        for custom_sid in expand_units(manifest):
            member = f"DB/units/units_views/{faction_sid}/{custom_sid}_v.json"
            item = first_array_item(read_core_json(core, member))
            if item is None:
                report_missing_release_surface(manifest, v, f"{faction_sid}:{custom_sid}: core missing or malformed unit view {member}")
                continue
            if item.get("id") != custom_sid:
                v.error(f"{faction_sid}:{custom_sid}: core unit view id must be {custom_sid!r}, got {item.get('id')!r}")
            mesh_path = item.get("mesh")
            skinned_preview = skinned_preview_by_sid.get(custom_sid)
            if skinned_preview:
                if mesh_path != skinned_preview["mesh"]:
                    v.error(
                        f"{faction_sid}:{custom_sid}: OwnedSkinned unit view mesh must be "
                        f"{skinned_preview['mesh']!r}, got {mesh_path!r}"
                    )
            elif not isinstance(mesh_path, str) or mesh_path.startswith("homm3_import/") or mesh_path.startswith("units/homm3_import/"):
                v.error(f"{faction_sid}:{custom_sid}: core unit view mesh must remain a donor prefab path, got {mesh_path!r}")
            elif mesh_path in UNSAFE_CUSTOM_UNIT_VIEW_MESHES:
                v.error(f"{faction_sid}:{custom_sid}: core unit view mesh {mesh_path!r} is unsafe for custom rows: {UNSAFE_CUSTOM_UNIT_VIEW_MESHES[mesh_path]}")
            expected_map_mesh = expected_map_mesh_by_sid.get(custom_sid)
            map_mesh = unit_view_config_path(item.get("mapMesh"))
            if expected_map_mesh:
                if map_mesh != expected_map_mesh:
                    v.error(
                        f"{faction_sid}:{custom_sid}: core unit view mapMesh must be synthetic import path "
                        f"{expected_map_mesh!r}, got {item.get('mapMesh')!r}",
                    )
            elif not isinstance(item.get("mapMesh"), str) or str(item.get("mapMesh")).startswith(("homm3_import/", "units/homm3_import/")):
                v.error(f"{faction_sid}:{custom_sid}: core unit view mapMesh has no matching import-table entry, got {item.get('mapMesh')!r}")
            battle_shell = battle_shell_by_sid.get(custom_sid)
            if battle_shell and battle_shell not in core_unit_mesh_paths:
                v.error(f"{faction_sid}:{custom_sid}: homm3_import battlePresentationResPath {battle_shell!r} is not a live Core UnitView mesh path")
            elif battle_shell in UNSAFE_CUSTOM_UNIT_VIEW_MESHES:
                v.error(f"{faction_sid}:{custom_sid}: homm3_import battlePresentationResPath {battle_shell!r} is unsafe for custom rows: {UNSAFE_CUSTOM_UNIT_VIEW_MESHES[battle_shell]}")
            map_shell = map_shell_by_sid.get(custom_sid)
            if map_shell and map_shell not in core_unit_map_mesh_paths:
                v.error(f"{faction_sid}:{custom_sid}: homm3_import mapShellResPath {map_shell!r} is not a live Core UnitView mapMesh path")
            logic_member = f"DB/units/units_logics/{faction_sid}/{custom_sid}_l.json"
            logic_item = first_array_item(read_core_json(core, logic_member))
            if logic_item is None:
                report_missing_release_surface(manifest, v, f"{faction_sid}:{custom_sid}: core missing or malformed unit logic {logic_member}")
            else:
                tier = tier_by_sid.get(custom_sid)
                validate_unit_logic_stats(
                    manifest,
                    faction_sid,
                    custom_sid,
                    tier if isinstance(tier, int) else None,
                    logic_item,
                    v,
                )
                expected_biome = (manifest.get("releaseScaffold") or {}).get("biome") or manifest["identity"].get("nativeBiome")
                if isinstance(expected_biome, str) and logic_item.get("nativeBiome") != expected_biome:
                    v.error(f"{faction_sid}:{custom_sid}: core unit logic nativeBiome must be {expected_biome!r}, got {logic_item.get('nativeBiome')!r}")
                validate_unit_attack_view_parity(faction_sid, custom_sid, logic_item, item, v)
                validate_ranged_attack_contract(faction_sid, custom_sid, logic_item, item, v)
            if faction_sid == "homm3_fortress":
                token = json_contains_token(
                    {
                        "abilities": item.get("abilities"),
                        "passives": item.get("passives"),
                        "defaultAttacks": item.get("defaultAttacks"),
                        "alternativeAttacks": item.get("alternativeAttacks"),
                        "counterAttacks": item.get("counterAttacks"),
                    },
                    FORTRESS_DONOR_MECHANIC_TOKENS,
                )
                if token:
                    v.error(f"{faction_sid}:{custom_sid}: core unit view leaks donor mechanic token {token!r}")
                if logic_item is None:
                    v.error(f"{faction_sid}:{custom_sid}: core missing or malformed unit logic {logic_member}")
                else:
                    token = json_contains_token(
                        {
                            "abilities": logic_item.get("abilities"),
                            "passives": logic_item.get("passives"),
                            "globalPassives": logic_item.get("globalPassives"),
                            "defaultAttacks": logic_item.get("defaultAttacks"),
                            "alternativeAttacks": logic_item.get("alternativeAttacks"),
                            "counterAttacks": logic_item.get("counterAttacks"),
                        },
                        FORTRESS_DONOR_MECHANIC_TOKENS,
                    )
                    if token:
                        v.error(f"{faction_sid}:{custom_sid}: core unit logic leaks donor mechanic token {token!r}")

        heroes = manifest.get("heroes") or {}
        hero_prefix = heroes.get("heroPrefix")
        hero_count = heroes.get("count")
        override_start_skills = hero_override_start_skill_signatures(manifest, hero_override_dir, v)
        if isinstance(hero_prefix, str) and isinstance(hero_count, int):
            for index in range(1, hero_count + 1):
                hero_sid = f"{hero_prefix}{index}"
                hero_member = f"DB/heroes/{faction_sid}/{hero_sid}.json"
                hero_item = first_array_item(read_core_json(core, hero_member))
                if hero_item is None:
                    report_release_gap(manifest, v, f"{faction_sid}: core missing hero row {hero_member}")
                    continue
                if hero_item.get("id") != hero_sid:
                    v.error(f"{faction_sid}: core hero row {hero_member} id must be {hero_sid!r}, got {hero_item.get('id')!r}")
                if hero_item.get("fraction") != faction_sid:
                    v.error(f"{faction_sid}: core hero row {hero_member} fraction must be {faction_sid!r}, got {hero_item.get('fraction')!r}")
                expected_biome = (manifest.get("releaseScaffold") or {}).get("biome") or manifest["identity"].get("nativeBiome")
                if isinstance(expected_biome, str) and hero_item.get("nativeBiome") != expected_biome:
                    v.error(f"{faction_sid}: core hero row {hero_member} nativeBiome must be {expected_biome!r}, got {hero_item.get('nativeBiome')!r}")
                start_squad = hero_item.get("startSquad")
                if not isinstance(start_squad, list) or not start_squad:
                    v.error(f"{faction_sid}: core hero row {hero_member} must have a non-empty startSquad")
                validate_custom_hero_start_skills(
                    manifest,
                    faction_sid,
                    hero_sid,
                    hero_member,
                    hero_item,
                    override_start_skills.get(hero_sid),
                    v,
                )

        map_doc = read_core_json(core, "DB/map/objects/4_interactables.json")
        map_rows = (map_doc or {}).get("array") if isinstance(map_doc, dict) else None
        map_by_id = {row.get("id"): row for row in map_rows if isinstance(row, dict)} if isinstance(map_rows, list) else {}
        map_ids = set(map_by_id)
        direct_city = overlay.get("directCityMapObject") or manifest["identity"].get("citySid")
        if direct_city not in map_ids:
            report_missing_release_surface(manifest, v, f"{faction_sid}: core missing direct city map object {direct_city}")
        else:
            donor_city = manifest["identity"].get("donorCitySid")
            donor_row = map_by_id.get(donor_city)
            direct_row = map_by_id.get(direct_city)
            donor_prefs = donor_row.get("prefs") if isinstance(donor_row, dict) else None
            direct_prefs = direct_row.get("prefs") if isinstance(direct_row, dict) else None
            if isinstance(donor_prefs, list) and donor_prefs and direct_prefs != donor_prefs:
                report_release_gap(
                    manifest,
                    v,
                    f"{faction_sid}: core direct city map object {direct_city} prefs must clone donor {donor_city} prefs {donor_prefs!r}, got {direct_prefs!r}",
                )
            if isinstance(direct_row, dict):
                nodes = direct_row.get("nodes")
                expected_nodes = [1, 1, 1, 1, 1, 1, 1, 2, 1]
                gen = direct_row.get("generatorConfig") if isinstance(direct_row.get("generatorConfig"), dict) else {}
                if nodes != expected_nodes:
                    v.error(
                        f"{faction_sid}: core direct city map object {direct_city} must use bottom-center GATE "
                        f"nodes={expected_nodes!r} (index 7); got {nodes!r}"
                    )
                if (
                    direct_row.get("canBeMirrored") is not False
                    or gen.get("buildingLeftBottomX") != 1
                    or gen.get("buildingLeftBottomZ") != 2
                    or gen.get("buildingSizeX") != 1
                    or gen.get("buildingSizeZ") != 1
                ):
                    v.error(
                        f"{faction_sid}: core direct city map object {direct_city} must use bottom-center "
                        f"generatorConfig LeftBottom (1,2) 1x1 with canBeMirrored=false; got "
                        f"canBeMirrored={direct_row.get('canBeMirrored')!r} generatorConfig={gen!r}"
                    )
        direct_prefix = overlay.get("directDwellingPrefix")
        for tier in range(1, 8):
            direct_dwelling = f"{direct_prefix}{tier}"
            if direct_dwelling not in map_ids:
                report_missing_release_surface(manifest, v, f"{faction_sid}: core missing direct dwelling map object {direct_dwelling}")

        for index, line in enumerate(additional_recruitment_lines(manifest)):
            direct_dwelling = line["directDwellingSid"]
            direct_row = map_by_id.get(direct_dwelling)
            if not isinstance(direct_row, dict):
                report_missing_release_surface(manifest, v, f"{faction_sid}: core missing additional dwelling map object {direct_dwelling}")
                continue
            expected_prefs = [f"barracks/{line['donorDwellingSid']}"]
            if direct_row.get("prefs") != expected_prefs:
                v.error(
                    f"{faction_sid}: core additional dwelling {direct_dwelling} prefs must bind explicit donor "
                    f"{expected_prefs!r}, got {direct_row.get('prefs')!r}"
                )

        hires_doc = read_core_json(core, "DB/objects_logic/hires/barracks.json")
        hire_rows = (hires_doc or {}).get("array") if isinstance(hires_doc, dict) else None
        hire_by_id = {row.get("id"): row for row in hire_rows if isinstance(row, dict)} if isinstance(hire_rows, list) else {}
        hire_ids = set(hire_by_id)
        for tier in range(1, 8):
            direct_dwelling = f"{direct_prefix}{tier}"
            if direct_dwelling not in hire_ids:
                report_missing_release_surface(manifest, v, f"{faction_sid}: core missing direct dwelling hire row {direct_dwelling}")


        variants = manifest.get("unitVariants", ["", "_upg", "_upg_alt"])
        for index, line in enumerate(additional_recruitment_lines(manifest)):
            direct_dwelling = line["directDwellingSid"]
            row = hire_by_id.get(direct_dwelling)
            if not isinstance(row, dict):
                report_missing_release_surface(manifest, v, f"{faction_sid}: core missing additional dwelling hire row {direct_dwelling}")
                continue
            if row.get("fraction") != faction_sid:
                v.error(
                    f"{faction_sid}: core additional dwelling {direct_dwelling} fraction must be {faction_sid!r}, "
                    f"got {row.get('fraction')!r}"
                )
            units_data = row.get("unitsData")
            units = units_data.get("units") if isinstance(units_data, dict) else None
            expected_sids = [unit_sid_for_variant(line, suffix) for suffix in variants]
            actual_sids = units[0].get("sids") if isinstance(units, list) and len(units) == 1 and isinstance(units[0], dict) else None
            if actual_sids != expected_sids:
                v.error(
                    f"{faction_sid}: core additional dwelling {direct_dwelling} unitsData must bind {expected_sids!r}, "
                    f"got {actual_sids!r}"
                )


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest-dir", type=Path, default=DEFAULT_MANIFEST_DIR)
    parser.add_argument("--source-mechanics-dir", type=Path, default=DEFAULT_SOURCE_MECHANICS_DIR)
    parser.add_argument("--hero-override-dir", type=Path, default=DEFAULT_HERO_OVERRIDE_DIR)
    parser.add_argument("--ability-override-dir", type=Path, default=DEFAULT_ABILITY_OVERRIDE_DIR)
    parser.add_argument("--core", type=Path, help="Optional Core.zip or extracted Core directory to validate required members.")
    parser.add_argument("--plugin-root", type=Path, help="Optional deployed OfflineUnlockMod plugin directory to validate runtime payload assets.")
    parser.add_argument(
        "--neutral-band-target",
        choices=("golden_era", "steam_25509697", "steam_25672315"),
        default="golden_era",
        help=(
            "Game build the --core is for; selects the pinned native neutral tier bands "
            "(validate_homm3_neutral_catalog_contract.NATIVE_TIER_BANDS_BY_TARGET). Default golden_era."
        ),
    )
    parser.add_argument(
        "--allow-missing-source-mechanics-metadata",
        action="store_true",
        help="Downgrade missing xHomm3SourceMechanic/xHomm3MechanicsStatus on live city rows to warnings.",
    )
    parser.add_argument(
        "--no-design-debt",
        action="store_true",
        help="Reject custom Core rows and localization that still carry design-debt keys or text.",
    )
    parser.add_argument(
        "--require-homm3-lab-sidecars",
        action="store_true",
        help="Also require deployed homm3_lab extracted_battle sidecars. Release runtime no longer needs these loose PNG trees by default.",
    )
    parser.add_argument(
        "--bundle-name-prefix",
        action="append",
        default=[],
        help="Limit deployed bundle payload checks to names starting with this prefix; repeatable.",
    )
    args = parser.parse_args(argv)

    v = Validation()
    manifests = load_manifests(args.manifest_dir)
    if not manifests:
        v.error(f"no manifests found in {args.manifest_dir}")

    try:
        release_port_dir = ROOT / "tools" / "release_port"
        if str(release_port_dir) not in sys.path:
            sys.path.insert(0, str(release_port_dir))
        from validate_homm3_neutral_catalog_contract import validate_catalog as validate_neutral_catalog
        from homm3_neutral_catalog import load_homm3_neutral_catalog as load_neutral_catalog

        validate_neutral_catalog(load_neutral_catalog(), v)
    except Exception as ex:
        v.error(f"homm3_neutral catalog validation failed to run: {ex}")

    for path, manifest in manifests:
        validate_manifest_shape(path, manifest, v)
    validate_fortress_core_generator_toa_overlay(v)
    validate_homm3_runtime_asset_payload(OFFLINE_PLUGIN_ROOT, v, "source")

    expected = validate_cross_manifest(manifests, v)
    validate_building_icon_runtime_source_map_parser(v)
    validate_source_maps(expected, manifests, v)
    validate_homm3_import_table(manifests, v)
    validate_homm3_bundle_payload_contract(load_homm3_import_entries_by_sid(v), v)
    if args.core:
        validate_core_members(
            args.core,
            manifests,
            v,
            args.source_mechanics_dir,
            hero_override_dir=args.hero_override_dir,
            ability_override_dir=args.ability_override_dir,
            strict_source_mechanics_metadata=not args.allow_missing_source_mechanics_metadata,
            no_design_debt=args.no_design_debt,
        )
        try:
            release_port_dir = ROOT / "tools" / "release_port"
            if str(release_port_dir) not in sys.path:
                sys.path.insert(0, str(release_port_dir))
            tools_dir = ROOT / "tools"
            if str(tools_dir) not in sys.path:
                sys.path.insert(0, str(tools_dir))
            from validate_homm3_landon_dwelling_localization_contract import (
                validate_landon_dwelling_localization,
            )

            for err in validate_landon_dwelling_localization(args.core.resolve()):
                v.error(err)
        except Exception as ex:
            v.error(f"landon dwelling localization validation failed to run: {ex}")
        try:
            from validate_homm3_neutral_catalog_contract import validate_neutral_kits_in_core
            from homm3_neutral_catalog import load_homm3_neutral_catalog as load_neutral_catalog_for_core

            validate_neutral_kits_in_core(
                args.core.resolve(),
                load_neutral_catalog_for_core(),
                v,
                band_target=args.neutral_band_target,
            )
        except Exception as ex:
            v.error(f"homm3_neutral OE kit Core validation failed to run: {ex}")
        try:
            from validate_unit_battle_ai_contract import validate_unit_battle_ai_in_core

            for err in validate_unit_battle_ai_in_core(args.core.resolve()):
                v.error(err)
        except Exception as ex:
            v.error(f"unit battle-ai Core validation failed to run: {ex}")
    if args.plugin_root:
        validate_plugin_payload(
            args.plugin_root,
            manifests,
            v,
            require_homm3_lab_sidecars=args.require_homm3_lab_sidecars,
            bundle_name_prefixes=args.bundle_name_prefix,
        )

    for warning in v.warnings:
        print(f"WARN: {warning}")
    for error in v.errors:
        print(f"ERROR: {error}")

    if v.errors:
        print(f"custom faction manifest validation failed: {len(v.errors)} error(s), {len(v.warnings)} warning(s)")
        return 1
    print(f"custom faction manifest validation passed: {len(manifests)} manifest(s), {len(expected)} unit mapping(s), {len(v.warnings)} warning(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
