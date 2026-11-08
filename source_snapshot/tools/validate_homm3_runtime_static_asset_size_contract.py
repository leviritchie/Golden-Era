#!/usr/bin/env python3
"""Fail-closed: live plugin static image sizes and startup lazy-decode policies stay within contract.

High-res masters under artifacts/static_asset_painted_upscale/final are intentionally exempt.
The reverse is checked too: a unit that has a painted master must ship it at the contract
size, so a raw 58x64 interface frame can never silently replace painted art. Startup town
preflight validates source files and metadata only; textures and music bundles are not decoded
there. Legacy town-layer prefab prewarming is not an active call path and is not used here.
Full-3D city scene bundles retain Homm3TownScene3d's existing loading path, including
its separate eager main-menu payload validation; this gate does not remove that prewarm.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "artifacts" / "static_asset_painted_upscale" / "RUNTIME_SIZE_CONTRACT.json"
DEFAULT_PLUGIN = (
    ROOT
    / "Heroes of Might & Magic Olden Era Playtest"
    / "OfflineUnlockMod"
)
INT32_MIN = -(1 << 31)
INT32_MAX = (1 << 31) - 1
_INT32_INTEGER_TEXT = re.compile(r"^[\x09-\x0D\x20]*([+-]?[0-9]+)[\x09-\x0D\x20]*$")


def parse_int32_text(value: object) -> int | None:
    """Match Int32.TryParse(NumberStyles.Integer): ASCII digits, sign, whitespace, and range."""
    if not isinstance(value, str):
        return None
    match = _INT32_INTEGER_TEXT.fullmatch(value)
    if match is None:
        return None
    try:
        parsed = int(match.group(1), 10)
    except ValueError:
        return None
    return parsed if INT32_MIN <= parsed <= INT32_MAX else None


def is_json_int32(value: object) -> bool:
    return type(value) is int and parse_int32_text(str(value)) is not None


def is_single_directory_component(value: object) -> bool:
    if not isinstance(value, str) or not value.strip() or value in {".", ".."}:
        return False
    if Path(value).is_absolute() or Path(value).name != value or "/" in value or "\\" in value:
        return False
    return not any(ord(char) < 32 or char in '<>:"|?*' for char in value)


def validate_animation_id_path_fixture(issues: list[str]) -> None:
    cases = (
        ("dwelling_01", True),
        ("../other", False),
        ("/absolute", False),
        (r"C:\absolute", False),
    )
    for value, expected in cases:
        if is_single_directory_component(value) is not expected:
            issues.append(f"animation ID path fixture failed for {value!r}")


def fail(msg: str) -> None:
    print(f"FAIL: {msg}", file=sys.stderr)


def load_contract(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def check_max_side(path: Path, max_side: int, issues: list[str], label: str) -> None:
    try:
        with Image.open(path) as im:
            w, h = im.size
    except Exception as ex:  # noqa: BLE001 - fail closed with path context
        issues.append(f"{label}: unreadable {path}: {ex}")
        return
    if max(w, h) > max_side:
        issues.append(f"{label}: {path} is {w}x{h} (max side {max(w, h)} > contract {max_side})")


def check_painted_not_downgraded(portraits: Path, masters: Path, max_side: int, issues: list[str]) -> int:
    """Every live portrait with a painted master must be that master at min(max_side, master side)."""
    checked = 0
    for master in sorted(masters.glob("h3_*.png")):
        live = portraits / master.name
        if not live.is_file():
            continue
        with Image.open(master) as m:
            want = min(max_side, max(m.size))
        with Image.open(live) as im:
            got = im.size
        checked += 1
        if got != (want, want):
            issues.append(
                f"unit-portrait: {live} is {got[0]}x{got[1]} but has painted master {master} "
                f"(expected {want}x{want}; run tools/generate_homm3_interface_portraits.py or "
                f"tools/downsample_homm3_runtime_static_assets.py)"
            )
    return checked


def validate_plugin(plugin: Path, contract: dict, issues: list[str]) -> None:
    unit = contract["runtime"]["unitPortraits"]
    bb = contract["runtime"]["mapBillboardPrimaryFrames"]
    unit_max = int(unit["maxSidePx"])
    bb_max = int(bb["maxSidePx"])

    portraits = plugin / unit["liveRelativeDir"]
    if not portraits.is_dir():
        issues.append(f"missing live portraits dir: {portraits}")
    else:
        files = sorted(portraits.glob(unit.get("glob", "h3_*.png")))
        if not files:
            issues.append(f"no unit portraits under {portraits}")
        for path in files:
            check_max_side(path, unit_max, issues, "unit-portrait")
        masters = ROOT / contract["masters"]["unitPortraits"].rsplit("/", 1)[0]
        if masters.is_dir():
            n = check_painted_not_downgraded(portraits, masters, unit_max, issues)
            print(f"painted-master downgrade check: {n} portrait(s) against {masters}")
        else:
            print(f"painted-master downgrade check skipped: masters dir absent ({masters})")

    refs = plugin / bb["liveRelativeDir"]
    if not refs.is_dir():
        issues.append(f"missing map_object_refs dir: {refs}")
    else:
        frames = sorted(refs.rglob("00_00.png"))
        if not frames:
            issues.append(f"no billboard 00_00.png under {refs}")
        for path in frames:
            check_max_side(path, bb_max, issues, "billboard-00_00")


def validate_preloader_policy(repo_root: Path, issues: list[str]) -> None:
    """Static guard: main-menu preloader must not call decode prewarm for portraits/billboards."""
    preloader = (
        repo_root
        / "Heroes of Might & Magic Olden Era Playtest"
        / "OfflineUnlockMod"
        / "Homm3RuntimeManifestPreloader.cs"
    )
    if not preloader.is_file():
        issues.append(f"missing preloader source: {preloader}")
        return
    text = preloader.read_text(encoding="utf-8")
    forbidden = [
        "PrewarmRequiredStaticPortraitSprites()",
        "PrewarmIntoNativeCatalogOrFail(",
        "Homm3StrongholdDwellingMapBillboard.PrewarmManifestTextures(",
        "Homm3CustomTownMapBillboard.PrewarmManifestTextures(",
    ]
    for needle in forbidden:
        if needle in text:
            issues.append(
                "Homm3RuntimeManifestPreloader.cs still invokes decode prewarm '"
                + needle
                + "'; main-menu path must validate files only (lazy decode on first need)."
            )
    required = [
        "ValidateRequiredStaticPortraitFilesOrFail",
        "ValidateRequiredDialogPortraitFilesOrFail",
        "ValidateManifestTexturePathsOrFail",
    ]
    for needle in required:
        if needle not in text:
            issues.append(
                f"Homm3RuntimeManifestPreloader.cs missing validate-only call '{needle}'"
            )


def required_region(source: str, start_marker: str, end_marker: str, label: str, issues: list[str]) -> str:
    start = source.find(start_marker)
    if start < 0:
        issues.append(f"{label}: missing source marker '{start_marker}'")
        return ""
    end = source.find(end_marker, start + len(start_marker))
    if end < 0:
        issues.append(f"{label}: missing end marker '{end_marker}'")
        return ""
    return source[start:end]


def csharp_string_array(source: str, marker: str, label: str, issues: list[str]) -> set[str]:
    start = source.find(marker)
    opening = source.find("{", start + len(marker)) if start >= 0 else -1
    closing = source.find("};", opening + 1) if opening >= 0 else -1
    if start < 0 or opening < 0 or closing < 0:
        issues.append(f"{label}: cannot locate the source string array")
        return set()

    values: set[str] = set()
    for line in source[opening + 1 : closing].splitlines():
        line = line.strip().rstrip(",")
        if line.startswith('"') and line.endswith('"'):
            value = line[1:-1]
            if value:
                values.add(value)
    if not values:
        issues.append(f"{label}: source string array is empty or malformed")
    return values


def load_town_route_inputs(repo_root: Path, issues: list[str]) -> tuple[list[str], set[str], bool, bool, bool]:
    """Read the same manifest registry, owned-SID list, and source config inputs used by the plugin."""
    registry_path = repo_root / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod" / "Homm3CustomFactionRegistry.cs"
    symbols_path = repo_root / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod" / "GameSymbols.cs"
    registry_source = registry_path.read_text(encoding="utf-8") if registry_path.is_file() else ""
    symbols_source = symbols_path.read_text(encoding="utf-8") if symbols_path.is_file() else ""
    if not registry_source:
        issues.append(f"missing registry source for town route selection: {registry_path}")
    if not symbols_source:
        issues.append(f"missing GameSymbols source for town route selection: {symbols_path}")

    population = required_region(
        registry_source,
        "ReleaseUiPresentationEnabledFactionSids.Clear();",
        "return Factions.Length;",
        "release UI faction registry population",
        issues,
    )
    if "foreach (var faction in Factions)" not in population or "ReleaseUiPresentationEnabledFactionSids.Add(faction.FactionSid);" not in population:
        issues.append("release UI registry must derive enabled SIDs from the loaded faction manifests")

    manifest_root = repo_root / "custom_factions"
    manifest_paths = sorted(manifest_root.glob("homm3_*.json"))
    if not manifest_paths:
        issues.append(f"no runtime faction manifests found under {manifest_root}")
    faction_sids: list[str] = []
    for manifest_path in manifest_paths:
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as ex:
            issues.append(f"{manifest_path}: cannot read registry faction SID: {ex}")
            continue
        identity = manifest.get("identity") if isinstance(manifest, dict) else None
        faction_sid = identity.get("factionSid") if isinstance(identity, dict) else None
        if not isinstance(faction_sid, str) or not faction_sid.startswith("homm3_"):
            issues.append(f"{manifest_path}: identity.factionSid must be a HoMM3 faction SID")
            continue
        faction_sids.append(faction_sid)
    if len(set(faction_sids)) != len(faction_sids):
        issues.append("custom_factions manifests contain duplicate faction SIDs")

    owner_marker = "internal static readonly string[] OwnedCityWorldFactionSids"
    owner_region = required_region(symbols_source, owner_marker, "internal static bool IsOwnedCityWorldFaction", "owned city world faction list", issues)
    owned_sids = csharp_string_array(owner_region, owner_marker, "owned city world faction list", issues) if owner_region else set()

    config_path = repo_root / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod" / "config.json"
    config = {}
    try:
        loaded = json.loads(config_path.read_text(encoding="utf-8"))
        if not isinstance(loaded, dict):
            raise ValueError("config root must be an object")
        config = loaded
    except (OSError, json.JSONDecodeError, ValueError) as ex:
        issues.append(f"town route source config is unavailable or invalid at {config_path}: {ex}")

    def config_bool(name: str, default: bool) -> bool:
        value = config.get(name, default)
        if type(value) is not bool:
            issues.append(f"{config_path}: {name} must be a JSON boolean")
            return False
        return value

    release_ui = config_bool("homm3ReleaseSafeCityTownUi", True)
    factory_replace = config_bool("homm3FactoryCitySceneReplace", False)
    town_scene_3d = config_bool("homm3TownScene3d", False)
    return faction_sids, owned_sids, release_ui, factory_replace, town_scene_3d


def catalog_is_full_scene_3d(plugin_root: Path, faction: str, issues: list[str]) -> bool | None:
    catalog_path = plugin_root / "homm3_runtime_assets" / "town_scene_refs" / faction / "catalog.json"
    try:
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as ex:
        issues.append(f"{faction}: configured owned town route requires a readable scene catalog at {catalog_path}: {ex}")
        return None
    if not isinstance(catalog, dict):
        issues.append(f"{faction}: scene catalog root must be an object: {catalog_path}")
        return None
    value = catalog.get("fullScene3d")
    if value is None:
        return False
    if type(value) is bool:
        return value
    if isinstance(value, str) and value.casefold() in {"true", "false"}:
        return value.casefold() == "true"
    issues.append(f"{faction}: scene catalog fullScene3d must be a boolean: {catalog_path}")
    return None


def validate_town_presentation_asset_sources(repo_root: Path, plugin_root: Path, issues: list[str]) -> None:
    """Exercise source-only town checks for the routes selected by the checked-in config."""
    validate_animation_id_path_fixture(issues)
    faction_sids, owned_sids, release_ui, factory_replace, town_scene_3d = load_town_route_inputs(repo_root, issues)
    if not faction_sids:
        return

    legacy_sids: list[str] = []
    full_scene_3d_sids: list[str] = []
    for faction in faction_sids:
        if not release_ui:
            continue
        if factory_replace and town_scene_3d and faction in owned_sids:
            catalog_full_3d = catalog_is_full_scene_3d(plugin_root, faction, issues)
            if catalog_full_3d is None or catalog_full_3d:
                if catalog_full_3d:
                    full_scene_3d_sids.append(faction)
                continue
        legacy_sids.append(faction)

    town_root = plugin_root / "homm3_runtime_assets" / "town_scene_refs"
    print(
        "town source gate route selection: "
        f"registry={len(faction_sids)}, legacy={len(legacy_sids)}, fullScene3d={len(full_scene_3d_sids)}, "
        f"releaseUi={release_ui}, factoryReplace={factory_replace}, townScene3d={town_scene_3d}, "
        f"config={repo_root / 'Heroes of Might & Magic Olden Era Playtest' / 'OfflineUnlockMod' / 'config.json'} "
        "(repository/plugin config, not installed launcher config)"
    )

    for faction in legacy_sids:
        faction_dir = town_root / faction
        faction = faction_dir.name
        layer_root = faction_dir / "layers"
        positions_path = layer_root / "positions.json"
        map_path = layer_root / "building_layer_map.json"
        metadata_path = layer_root / "anims" / "metadata.json"
        backdrop_path = faction_dir / "mockups" / f"{faction}_background_mock_1920x1080.png"
        for path in (backdrop_path, positions_path, map_path, metadata_path):
            if not path.is_file():
                issues.append(f"{faction}: required town presentation source is missing: {path}")
        if not backdrop_path.is_file() or not positions_path.is_file() or not map_path.is_file() or not metadata_path.is_file():
            continue

        try:
            positions = json.loads(positions_path.read_text(encoding="utf-8"))
            layer_map = json.loads(map_path.read_text(encoding="utf-8"))
            animation_rows = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as ex:
            issues.append(f"{faction}: town presentation JSON is invalid: {ex}")
            continue

        layer_rows = positions.get("layers") if isinstance(positions, dict) else None
        if not isinstance(layer_rows, list) or not layer_rows:
            issues.append(f"{faction}: positions.json must contain a non-empty layers array")
            continue

        placements: dict[str, dict] = {}
        for index, row in enumerate(layer_rows):
            if not isinstance(row, dict):
                issues.append(f"{faction}: positions.json layer entry {index} is not an object")
                continue
            layer_id = row.get("id")
            if not isinstance(layer_id, str) or not layer_id.strip():
                issues.append(f"{faction}: positions.json layer entry {index} has no id")
                continue
            key = layer_id.casefold()
            if key in placements:
                issues.append(f"{faction}: positions.json has duplicate layer id {layer_id}")
                continue
            placements[key] = row
            if any(not is_json_int32(row.get(axis)) for axis in ("x", "y", "z")):
                issues.append(f"{faction}: positions.json layer {layer_id} has invalid Int32 x/y/z coordinates")
            if any(type(row.get(bound)) not in (int, float) for bound in ("reference_x", "reference_y", "reference_w", "reference_h")):
                issues.append(f"{faction}: positions.json layer {layer_id} lacks numeric reference bounds")

            hidden = row.get("hidden") is True or str(row.get("hidden", "")).casefold() == "true"
            if hidden:
                continue
            sprite = row.get("sprite")
            if not isinstance(sprite, str) or not sprite.strip():
                issues.append(f"{faction}: visible town layer {layer_id} has no sprite declaration")
                continue
            sprite_path = (layer_root / sprite).resolve()
            try:
                sprite_path.relative_to(layer_root.resolve())
            except ValueError:
                issues.append(f"{faction}: town layer {layer_id} sprite escapes its source root: {sprite}")
                continue
            if not sprite_path.is_file():
                issues.append(f"{faction}: town layer {layer_id} sprite is missing: {sprite_path}")

        if not isinstance(layer_map, dict):
            issues.append(f"{faction}: building_layer_map.json root must be an object")
            continue
        building_ids = layer_map.get("buildingLayerIds", layer_map.get("map"))
        if not isinstance(building_ids, dict) or not building_ids:
            issues.append(f"{faction}: building_layer_map.json must contain non-empty buildingLayerIds")
            continue
        if any(not isinstance(building, str) or not building.strip() or not isinstance(layer_id, str) or not layer_id.strip()
               for building, layer_id in building_ids.items()):
            issues.append(f"{faction}: buildingLayerIds contains an empty or non-string mapping")
            continue

        # Check source metadata shape only. `nativeLevels` belongs to the separate
        # cityFactory/Castle-parity contract; neither schema is joined to positions here.
        source_levels = layer_map.get("levels")
        if source_levels is not None and not isinstance(source_levels, dict):
            issues.append(f"{faction}: building_layer_map.json levels must be an object when present")
            source_levels = None
        elif source_levels is not None and not source_levels:
            issues.append(f"{faction}: building_layer_map.json levels object must be non-empty when present")
        for building, levels in (source_levels or {}).items():
            if not isinstance(building, str) or not building.strip() or not isinstance(levels, dict) or not levels:
                issues.append(f"{faction}: levels contains an invalid or empty building mapping")
                continue
            for level_text, layer_id in levels.items():
                level = parse_int32_text(level_text)
                if level is None or level <= 0 or not isinstance(layer_id, str) or not layer_id.strip():
                    issues.append(f"{faction}: levels entry {building} level {level_text} has an invalid layer id")

        if not isinstance(animation_rows, list) or not animation_rows:
            issues.append(f"{faction}: anims/metadata.json must contain a non-empty array")
            continue
        animation_ids: set[str] = set()
        for index, row in enumerate(animation_rows):
            if not isinstance(row, dict):
                issues.append(f"{faction}: animation metadata entry {index} is not an object")
                continue
            anim_id = row.get("id")
            frames = row.get("frames")
            if not isinstance(anim_id, str) or not anim_id.strip() or anim_id.casefold() in animation_ids:
                issues.append(f"{faction}: animation metadata entry {index} has a missing or duplicate id")
                continue
            animation_ids.add(anim_id.casefold())
            if not isinstance(frames, list) or not frames:
                issues.append(f"{faction}: animation {anim_id} must declare a non-empty frames array")
                continue
            if not is_single_directory_component(anim_id):
                issues.append(f"{faction}: animation ID must be one directory component: {anim_id!r}")
                continue
            anim_root = (layer_root / "anims").resolve()
            frame_dir = (anim_root / anim_id).resolve()
            if frame_dir == anim_root or anim_root not in frame_dir.parents:
                issues.append(f"{faction}: animation directory escapes its animation root: {anim_id!r}")
                continue
            if not frame_dir.is_dir():
                issues.append(f"{faction}: animation directory is missing: {frame_dir}")
                continue
            for frame in frames:
                if not isinstance(frame, str) or not frame.strip():
                    issues.append(f"{faction}: animation {anim_id} has an empty frame path")
                    continue
                if Path(frame).is_absolute() or frame.startswith(("/", "\\")) or (len(frame) > 1 and frame[1] == ":"):
                    issues.append(f"{faction}: animation {anim_id} frame path is rooted: {frame!r}")
                    continue
                frame_path = (frame_dir / frame).resolve()
                if frame_path == frame_dir or frame_dir not in frame_path.parents:
                    issues.append(f"{faction}: animation {anim_id} frame escapes its source directory: {frame}")
                    continue
                if not frame_path.is_file():
                    issues.append(f"{faction}: animation {anim_id} frame is missing: {frame_path}")


def validate_city_presentation_preflight_policy(repo_root: Path, plugin_root: Path, issues: list[str]) -> None:
    """Pin startup to source checks while preserving the existing first-use loaders."""
    plugin_dir = repo_root / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod"
    plugin_path = plugin_dir / "Plugin.cs"
    layers_path = plugin_dir / "Homm3StrongholdTownLayers.cs"
    animations_path = plugin_dir / "Homm3StrongholdTownAnimPlayer.cs"
    music_path = plugin_dir / "Homm3StrongholdCityMusic.cs"
    for path in (plugin_path, layers_path, animations_path, music_path):
        if not path.is_file():
            issues.append(f"missing city presentation source: {path}")
    if any(not path.is_file() for path in (plugin_path, layers_path, animations_path, music_path)):
        return

    plugin = plugin_path.read_text(encoding="utf-8")
    layers = layers_path.read_text(encoding="utf-8")
    animations = animations_path.read_text(encoding="utf-8")
    music = music_path.read_text(encoding="utf-8")

    if "ValidateCustomCityPresentationSourcesOrFail(Log, cfg)" not in plugin:
        issues.append("Plugin.Load must run ValidateCustomCityPresentationSourcesOrFail")
    if "PrewarmCustomCityPresentationAssets" in plugin:
        issues.append("Plugin.cs still names the removed all-faction city presentation prewarm")

    startup = required_region(
        plugin,
        "internal static void ValidateCustomCityPresentationSourcesOrFail(ManualLogSource log, LauncherConfig cfg)",
        "\n\tprivate static bool UsesConfiguredFullScene3dTownRoute",
        "Plugin city presentation source validation",
        issues,
    )
    for needle in (
        "if (cfg.Homm3ReleaseSafeCityTownUi)",
        "Homm3CustomFactionRegistry.EnumerateReleaseUiPresentationFactionSids()",
        "UsesConfiguredFullScene3dTownRoute(cfg, fraction)",
        "fullScene3dRoutes++",
        "GetCityBackdropPath(fraction)",
        "File.Exists(path)",
        "Homm3StrongholdTownLayers.ValidateFactionAssetSourcesOrFail(fraction)",
        "Homm3StrongholdTownAnimPlayer.ValidateFactionAnimationSourcesOrFail(fraction)",
        "Homm3StrongholdTownBuildEffects.PrewarmBuildEffects(log)",
        "buildEffectsPrewarmStatus",
    ):
        if needle not in startup:
            issues.append(f"Plugin city presentation source validation missing '{needle}'")
    for forbidden in (
        "LoadCityBackdropTexture(",
        "PrewarmTownMusic(",
        "PrewarmFactionAssets(",
        "PrewarmFactionAnimations(",
        "TryPrewarmTownPrefabAsset(",
        "LoadTownLayerTexture(",
        "EnsureClipLoaded(",
        "LoadAsset<",
        "ValidateTownMusicBundlePathOrFail(",
    ):
        if forbidden in startup:
            issues.append(f"Plugin city presentation startup validation must not call '{forbidden}'")
    for line in startup.splitlines():
        if "issues.Add" in line and "buildEffectsPrewarmStatus" in line:
            issues.append("optional build-effect WAV load status must not become a startup failure")

    if "PrewarmFactionAssets(" in plugin or "PrewarmFactionAnimations(" in plugin or "PrewarmTownMusic(" in plugin:
        issues.append("Plugin.cs must not call all-faction city texture, animation, or music prewarm")

    full_3d_route = required_region(
        plugin,
        "private static bool UsesConfiguredFullScene3dTownRoute",
        "\n\tinternal static void RecordCityOpenStart",
        "configured full-3D city route selector",
        issues,
    )
    for needle in (
        "cfg.Homm3FactoryCitySceneReplace",
        "cfg.Homm3TownScene3d",
        "Homm3CustomFactionRegistry.IsReleaseUiPresentationEnabledFactionSid(fraction)",
        "GameSymbols.FactoryCityScene.IsOwnedCityWorldFaction(fraction)",
        "Homm3TownScene3d.TryGetCatalog(fraction, out var catalog)",
        "catalog.FullScene3d",
        "configured Factory full-3D town route has no scene catalog",
    ):
        if needle not in full_3d_route:
            issues.append(f"configured full-3D city route selector missing '{needle}'")

    layer_validation = required_region(
        layers,
        "internal static int ValidateFactionAssetSourcesOrFail",
        "\n\tinternal static int PrewarmFactionAssets(\n\t\tstring fraction,",
        "town layer source validation",
        issues,
    )
    for needle in (
        "ResolveTownLayerRootRelativePath(fraction)",
        'Path.Combine(layerRoot, "positions.json")',
        "GetLayerPlacements(fraction, requireValidMetadata: true)",
        "GetBuildingLayerIds(fraction, requireValidMetadata: true)",
        "GetBuildingLayerLevels(fraction)",
        "placement.Hidden",
        "ResolveExistingPath(relativePath, logMissing: false)",
    ):
        if needle not in layer_validation:
            issues.append(f"town layer source validation missing existing parser/resolver call '{needle}'")
    for forbidden in ("LoadTownLayerTexture(", "PrewarmFactionAnimations(", "TryPrewarmTownPrefabAsset(", "AssetBundle.LoadFromFile("):
        if forbidden in layer_validation:
            issues.append(f"town layer source validation must not decode/load assets via '{forbidden}'")

    for needle in (
        'jroot["levels"]',
        "This map feeds the legacy dynamic layer resolver; nativeLevels belongs to the owned city scene join.",
        "buildingLevels.Properties()",
        "requireValidMetadata",
    ):
        if needle not in layers:
            issues.append(f"town presentation runtime parser missing strict source-metadata behavior '{needle}'")

    animation_validation = required_region(
        animations,
        "internal static int ValidateFactionAnimationSourcesOrFail",
        "\n\tinternal static int PrewarmFactionAnimations",
        "town animation source validation",
        issues,
    )
    for needle in (
        "GetMetadata(fraction, requireValidMetadata: true)",
        "IsSingleDirectoryComponent(animId)",
        "ResolveAnimationDirectory(layerRoot, animId)",
        "ResolveContainedChildPath(frameDir, frameName)",
        "File.Exists(path)",
    ):
        if needle not in animation_validation:
            issues.append(f"town animation source validation missing '{needle}'")
    for forbidden in ("GetOrLoadFrames(", "LoadFrameTexture(", "AssetBundle.LoadFromFile("):
        if forbidden in animation_validation:
            issues.append(f"town animation source validation must not decode/load assets via '{forbidden}'")

    animation_first_use = required_region(
        animations,
        "private void InitializeFrames(",
        "\n\tprivate static string BuildFrameCacheKey",
        "town animation first-use directory resolution",
        issues,
    )
    for needle in ("ResolveAnimationDirectory(_layerRootRelativePath, animId)", "BuildFrameCacheKey(animId, frameDir, arr)"):
        if needle not in animation_first_use:
            issues.append(f"town animation first-use loader missing safe path call '{needle}'")

    animation_path_helpers = required_region(
        animations,
        "private static string ResolveAnimationDirectory(",
        "\n\tprivate static string GetTextureStamp",
        "town animation containment helpers",
        issues,
    )
    for needle in (
        "IsSingleDirectoryComponent(animId)",
        "ResolveExistingDirectory(Path.Combine(layerRootRelativePath, AnimFolderName))",
        "ResolveContainedChildPath(animRoot, animId)",
        "Path.GetFullPath(rootDirectory)",
        "candidate.StartsWith(rootPrefix, StringComparison.OrdinalIgnoreCase)",
    ):
        if needle not in animation_path_helpers:
            issues.append(f"town animation containment helpers missing '{needle}'")
    if animations.count("ResolveContainedChildPath(frameDir, frameName)") < 3:
        issues.append("animation validation, cache-key generation, and frame loading must share frame-path containment")

    music_presence = required_region(
        music,
        "public static bool HasTownMusicBundle",
        "\n\tpublic static void EnsureTownMusicPlaying",
        "optional town music presence guard",
        issues,
    )
    for needle in ("TryNormalizeFactionSid(factionSid, out var normalized)", "File.Exists(ResolveBundlePath(normalized))"):
        if needle not in music_presence:
            issues.append(f"optional town music presence guard missing '{needle}'")
    if "ValidateTownMusicBundlePathOrFail" in music or "ValidateTownMusicBundlePathOrFail" in plugin:
        issues.append("missing optional town music bundles must not become a startup failure")
    music_loader = required_region(
        music,
        "static bool EnsureClipLoaded(CityMusicEntry entry)",
        "\n\tstatic bool TryReloadClipAssetsFromLiveBundle",
        "optional town music first-use loader",
        issues,
    )
    if "bundle missing" not in music_loader or "return false;" not in music_loader:
        issues.append("missing optional town music bundle must remain a nonfatal first-use result")

    build_sound = required_region(
        layers,
        "internal void PlayBuildSound()",
        "\n\tinternal void BeginSessionFadeRelease",
        "town build-effect optional playback policy",
        issues,
    )
    if "_buildClip == null || !_buildClip" not in build_sound or "return;" not in build_sound:
        issues.append("town build-effect playback must remain a no-op when its optional clip is unavailable")

    validate_town_presentation_asset_sources(repo_root, plugin_root, issues)

    if "LoadCityBackdropTexture(backdropPath)" not in plugin:
        issues.append("city backdrop demand loader is missing from ApplyCustomCityBackdrop")
    if "LoadTownLayerTexture(fraction, layerId, placement)" not in layers:
        issues.append("town static layer demand loader is missing from UpdateLayerImages")
    if "Homm3StrongholdTownAnimPlayer.TryAttach" not in layers or "GetOrLoadFrames(" not in animations:
        issues.append("town animation demand loader is missing from the active layer update path")
    if "EnsureClipLoaded(entry)" not in music:
        issues.append("town music demand loader is missing from EnsureTownMusicPlaying")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--plugin-root", type=Path, default=DEFAULT_PLUGIN)
    ap.add_argument("--contract", type=Path, default=CONTRACT_PATH)
    ap.add_argument("--repo-root", type=Path, default=ROOT)
    ap.add_argument("--skip-preloader-policy", action="store_true")
    args = ap.parse_args()

    if not args.contract.is_file():
        fail(f"missing contract {args.contract}")
        return 2
    contract = load_contract(args.contract)
    issues: list[str] = []
    validate_plugin(args.plugin_root.resolve(), contract, issues)
    if not args.skip_preloader_policy:
        validate_preloader_policy(args.repo_root.resolve(), issues)
        validate_city_presentation_preflight_policy(args.repo_root.resolve(), args.plugin_root.resolve(), issues)

    if issues:
        for issue in issues[:40]:
            fail(issue)
        if len(issues) > 40:
            fail(f"... and {len(issues) - 40} more")
        print(f"FAIL: {len(issues)} runtime static asset size contract violation(s)", file=sys.stderr)
        return 1

    print(
        "OK: runtime static asset size contract "
        f"(portraits maxSide<={contract['runtime']['unitPortraits']['maxSidePx']}, "
        f"billboard 00_00 maxSide<={contract['runtime']['mapBillboardPrimaryFrames']['maxSidePx']}, "
        "main-menu and town validate-only startup policy)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
