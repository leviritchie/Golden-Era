#!/usr/bin/env python3
"""Validate the HoMM3 custom-biome runtime renderer contract.

The custom terrain renderer must support rectangular native MapData envelopes.
Layered atlas maps are 160x80, so inferring a square packed color layer from
array length silently rejects valid terrain layers and can leave the map black.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import time
import zipfile
from pathlib import Path
from typing import Any

from PIL import Image


PLUGIN_DIR = Path("Heroes of Might & Magic Olden Era Playtest") / "OfflineUnlockMod"
RENDERER_SOURCE = "Homm3SwampAutumnTintProof.cs"
SYMBOLS_SOURCE = "GameSymbols.cs"
WATER_OVERLAY_SOURCE = "Homm3HomecomingWaterTileOverlayVisual.cs"
MAP_OBJECT_HOOK_SOURCE = "Homm3MapObjectUnitVisualHook.cs"
IMPORT_VISUALS_SOURCE = "Homm3ImportVisuals.cs"
TERRAIN_LOOKUP_HELPER_SOURCE = "Homm3TerrainMaterialLookup.cs"
TERRAIN_LOOKUP_FIXTURE_PROJECT = Path("tools") / "tests" / "homm3_terrain_material_lookup_fixture" / "Homm3TerrainMaterialLookupFixture.csproj"
TERRAIN_LOOKUP_FIXTURE_TIMEOUT_SECONDS = 60
WATER_TILE_OVERLAY_VISUAL_CONTRACT = {
    "material": "sanitized_native_hex_lit_billboard_material_per_sid",
    "animation": "multi_frame_map_idle_texture_animator",
    "orientation": "flat_against_landscape",
    "mesh": "horizontal_quad",
    "cameraFacing": False,
}
CUSTOM_BIOME_MANIFEST = Path("homm3_runtime_assets") / "custom_biomes" / "custom_biomes.json"
VOID_TEXTURE_DIR = Path("homm3_runtime_assets") / "custom_biomes" / "void"
VOID_REPORT_NAME = "void_terrain_report.json"
VOID_TEXTURE_FILES = ["dirt_ground1.png", "dirt_ground2.png", "dirt_ground3.png"]
VOID_BIOME_ID = "void"
VOID_BIOME_NAME = "Void"
VOID_TEXTURE_RELATIVE_DIR = "homm3_runtime_assets/custom_biomes/void"
VOID_TILE_ID = 23
VOID_DONOR_BIOME = "Dirt"
VOID_DONOR_TILE_ID = 7
VOID_VARIANT = "void_black"
VOID_CORE_TILE_PENALTY = 0.4
FACTORY_BIOME_ID = "foundry"
FACTORY_BIOME_NAME = "Foundry"
FACTORY_TILE_ID = 29
FACTORY_DONOR_BIOME = "Sand"
BULWARK_BIOME_ID = "permafrost"
BULWARK_BIOME_NAME = "Permafrost"
BULWARK_TILE_ID = 30
BULWARK_DONOR_BIOME = "Snow"
CORE_TILES_MEMBER = "DB/map/tiles/tiles.json"
RETIRED_WATER_PACK_ROWS = {
    "Water": 18,
    "Water Shore North": 19,
    "Water Shore South": 20,
    "Water Shore West": 21,
    "Water Shore East": 22,
}
DISPLAY_WATER_TILE_ROWS = {
    "display_water": (24, "Display Water"),
    "display_water_shore_north": (25, "Display Water Shore North"),
    "display_water_shore_south": (26, "Display Water Shore South"),
    "display_water_shore_west": (27, "Display Water Shore West"),
    "display_water_shore_east": (28, "Display Water Shore East"),
}
VANILLA_WATER_VISUAL_DONOR_TILE_CODE = 18
DISPLAY_WATER_BEHAVIOR_DONOR_TILE_CODE = 2

REQUIRED_RENDERER_TOKENS = {
    "packed layer width state": "_currentMapPackedLayerWidth",
    "packed layer height state": "_currentMapPackedLayerHeight",
    "MapData dimension reader": "TryReadMapDataDimensions(",
    "active shape resolver": "TryResolveCurrentPackedLayerShape(",
    "rectangular shape value": "PackedLayerShape",
    "rectangular build signature": "BuildPackedColorLayer(Texture2D texture, PackedLayerShape shape)",
    "rectangular validation signature": "PackedColorLayerMatchesTexture(object layerObject, Texture2D texture, PackedLayerShape shape",
    "prepare-prefix scope refresh": "SetActiveMapVisualSlotScope(__0, \"terrain renderer prepare-map prefix\")",
    "rectangular expected-length check": "expectedLength = (long)_currentMapPackedLayerWidth * _currentMapPackedLayerHeight",
    "custom packed color seam": "BuildTerrainPackedColorLayer",
}

FORBIDDEN_RENDERER_TOKENS = {
    "square layer sqrt inference": "Math.Sqrt(layerLength)",
    "square layer rejection": "side * side != layerLength",
    "square build signature": "BuildPackedColorLayer(Texture2D texture, int side)",
    "square validation signature": "PackedColorLayerMatchesTexture(object layerObject, Texture2D texture, int side",
    "old non-square rejection log": "non-square packed color layer",
}

REQUIRED_SYMBOL_TOKENS = {
    "MapData sizeX member resolver": "MapDataSizeXMembers",
    "MapData sizeZ member resolver": "MapDataSizeZMembers",
    "native sizeX field name": '"sizeX_"',
    "native sizeZ field name": '"sizeZ_"',
    "native terrain texture-node uploader": "RendererUploadTextureNodes",
    "native terrain texture-node uploader id": "terrain.material.renderer.uploadTextureNodes",
    "native terrain texture-node uploader generated name": "Method_Private_Void_Map_0",
}


def require(condition: bool, message: str, errors: list[str]) -> None:
    if not condition:
        errors.append(message)


def read_text(path: Path, errors: list[str]) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception as exc:  # noqa: BLE001 - validator should report all file-read failures uniformly.
        errors.append(f"failed to read {path}: {exc}")
        return ""


def read_json(path: Path, errors: list[str]) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception as exc:  # noqa: BLE001 - validator should report all file-read failures uniformly.
        errors.append(f"failed to read JSON {path}: {exc}")
        return None


def validate_terrain_lookup_reconciliation(repo_root: Path, renderer: str, errors: list[str]) -> None:
    helper_path = repo_root / PLUGIN_DIR / TERRAIN_LOOKUP_HELPER_SOURCE
    helper = read_text(helper_path, errors)
    fixture_project_path = repo_root / TERRAIN_LOOKUP_FIXTURE_PROJECT
    fixture_project = read_text(fixture_project_path, errors)
    require("internal static class Homm3TerrainMaterialLookup" in helper, "terrain lookup helper type is missing", errors)
    require("internal static void Replace(" in helper, "terrain lookup helper Replace method is missing", errors)
    require(TERRAIN_LOOKUP_HELPER_SOURCE in fixture_project, "behavior fixture must compile the production terrain lookup helper source", errors)

    prefix_start = renderer.find("private static void PrefixRendererPrepareMap(")
    prefix_seed = renderer.find(
        'SeedRendererLookupDictionary(__instance, "terrain renderer prepare-map prefix", _currentMapCustomVisualTileCodes);',
        prefix_start,
    )
    prefix_custom_gate = renderer.find("if (HasActiveMapCustomVisualTileCodes())", prefix_start)
    require(prefix_start >= 0, "renderer PrepareMap prefix is missing", errors)
    require(prefix_seed >= 0 and prefix_custom_gate > prefix_seed,
            "renderer lookup replacement must run before the custom-tile branch so stock and water-only maps are reconciled too", errors)

    seed_start = renderer.find("private static void SeedRendererLookupDictionary(")
    seed_end = renderer.find("private static int FindBiomeIndex(", seed_start)
    seed_body = renderer[seed_start:seed_end] if seed_start >= 0 and seed_end > seed_start else ""
    expected_lookup_tokens = {
        "current biome table lookup construction": "expected.Add(biome.tileCode, slot);",
        "custom material alias registration": "ResolveAliasDonorMaterialSlot(expected, definition)",
        "declared alias target row override": "expected[definition.TileCode] = biomeIndex;",
        "current native-water mapping": "EnsureNativeWaterTerrainLookupEntries(expected, terrain, source);",
        "validated full dictionary replacement": "Homm3TerrainMaterialLookup.Replace(expected, biomes.Length, materialLookup.Value.Clear, materialLookup.Value.Add);",
    }
    for label, token in expected_lookup_tokens.items():
        require(token in seed_body, f"renderer lookup reconciliation missing {label}: {token}", errors)
    require("ResolveRendererLookupMaterialSlot" not in renderer,
            "renderer must not retain the stale-renderer-first material slot resolver after complete-snapshot reconciliation", errors)
    replacement = seed_body.find("Homm3TerrainMaterialLookup.Replace(expected, biomes.Length, materialLookup.Value.Clear, materialLookup.Value.Add);")
    vector_capacity_prerequisite = seed_body.find('if (!EnsureTerrainGlobalVectorArrayCapacity(source + " renderer lookup"))')
    vector_capacity_prerequisite_end = seed_body.find("var rendererKey =", vector_capacity_prerequisite)
    vector_capacity_prerequisite_body = (
        seed_body[vector_capacity_prerequisite:vector_capacity_prerequisite_end]
        if vector_capacity_prerequisite >= 0 and vector_capacity_prerequisite_end > vector_capacity_prerequisite
        else ""
    )
    require(
        "throw new InvalidOperationException(" in vector_capacity_prerequisite_body
        and "cannot replace terrain renderer lookup via" in vector_capacity_prerequisite_body
        and "return;" not in vector_capacity_prerequisite_body
        and replacement > vector_capacity_prerequisite_end,
        "renderer lookup seeding must fail closed on packed-vector prerequisite failure before lookup replacement",
        errors,
    )
    expected_build = seed_body.find("expected.Add(biome.tileCode, slot);")
    alias_donor = seed_body.find("ResolveAliasDonorMaterialSlot(expected, definition)")
    alias_override_guard = seed_body.find("if (definition.MaterialAliasOnly)", alias_donor)
    alias_override = seed_body.find("expected[definition.TileCode] = biomeIndex;", alias_override_guard)
    non_alias_conflict_check = seed_body.find("else if (expected.TryGetValue(definition.TileCode, out var existing))", alias_override)
    water_build = seed_body.find("EnsureNativeWaterTerrainLookupEntries(expected, terrain, source);")
    require(expected_build >= 0 and alias_donor > expected_build and alias_override_guard > alias_donor
            and alias_override > alias_override_guard and non_alias_conflict_check > alias_override
            and water_build > alias_override and replacement > water_build,
            "renderer lookup must be replaced only after the current biome, alias, and water snapshot is complete", errors)

    apply_start = renderer.find("private static void Apply(SoTerrainMaterial terrain, string source, bool force = false)")
    apply_end = renderer.find("\n\tprivate static ", apply_start + 1)
    apply_body = renderer[apply_start:apply_end] if apply_start >= 0 and apply_end > apply_start else ""
    marker_guard = apply_body.find("if (definition.MaterialAliasOnly || activeVisualDefinitions.Length == 0)")
    marker_guard_continue = apply_body.find("continue;", marker_guard)
    marker_texture_apply = apply_body.find("ApplyTextures(marker,")
    require(marker_guard >= 0 and marker_guard_continue > marker_guard and marker_texture_apply > marker_guard_continue,
            "stock-only terrain compaction must skip custom-map donor marker textures before applying them", errors)
    active_visual_scope = apply_body.find("var activeVisualDefinitions = ResolveActiveMapVisualDefinitions();")
    native_water_append_guard = apply_body.find("if (activeVisualDefinitions.Length > 0)")
    native_water_append = apply_body.find("AppendNativeWaterTerrainBiomesFromCatalog(activeBiomes, source);", native_water_append_guard)
    unique_biome_names = apply_body.find("EnsureUniqueBiomeNamesForRmg(activeBiomes, source);")
    native_water_append_is_guarded = (
        native_water_append_guard >= 0
        and native_water_append >= 0
        and apply_body[native_water_append_guard:native_water_append].strip() == "if (activeVisualDefinitions.Length > 0)"
        and apply_body.count("AppendNativeWaterTerrainBiomesFromCatalog(activeBiomes, source);") == 1
    )
    require(active_visual_scope >= 0 and native_water_append_guard > active_visual_scope
            and native_water_append > native_water_append_guard and unique_biome_names > native_water_append
            and native_water_append_is_guarded,
            "native water catalog rows must only be appended when active custom visual definitions exist", errors)

    if not helper_path.is_file() or not fixture_project_path.is_file():
        return
    started_at = time.perf_counter()
    try:
        result = subprocess.run(
            [
                "dotnet",
                "run",
                "--project",
                str(fixture_project_path),
                "--configuration",
                "Release",
                "--verbosity",
                "quiet",
            ],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
            timeout=TERRAIN_LOOKUP_FIXTURE_TIMEOUT_SECONDS,
        )
    except FileNotFoundError as exc:
        elapsed_ms = (time.perf_counter() - started_at) * 1000
        errors.append(f"terrain lookup behavior fixture could not start dotnet after {elapsed_ms:.1f}ms: {exc}")
        return
    except subprocess.TimeoutExpired:
        elapsed_ms = (time.perf_counter() - started_at) * 1000
        errors.append(
            f"terrain lookup behavior fixture timed out after {TERRAIN_LOOKUP_FIXTURE_TIMEOUT_SECONDS}s "
            f"(elapsed {elapsed_ms:.1f}ms)"
        )
        return
    elapsed_ms = (time.perf_counter() - started_at) * 1000
    if result.returncode != 0:
        output = "\n".join(part.strip() for part in (result.stdout, result.stderr) if part and part.strip())
        errors.append(
            f"terrain lookup behavior fixture failed (exit={result.returncode}, elapsed={elapsed_ms:.1f}ms): "
            f"{output[-3000:]}"
        )
        return
    fixture_output = result.stdout.strip()
    print(f"terrain lookup behavior fixture: {fixture_output}; validatorSubprocessElapsedMs={elapsed_ms:.1f}")


def normalize_asset_path(value: Any) -> str:
    return str(value).replace("\\", "/")


def validate_water_shore_pack_registration(repo_root: Path, errors: list[str]) -> None:
    packer_path = repo_root / "tools" / "release_port" / "apply_custom_biome_pack.py"
    packer = read_text(packer_path, errors)
    for biome_name, tile_id in RETIRED_WATER_PACK_ROWS.items():
        require(not (f'"target": "{biome_name}"' in packer and f'"tileId": {tile_id}' in packer), f"custom biome Core packer must not override vanilla/display water tile {tile_id} ({biome_name})", errors)
    require('"target": "Foundry", "source": "Sand", "faction": "homm3_factory", "tileId": 29}' in packer, "custom biome Core packer must register Foundry tile 29 for Factory from Sand", errors)
    require('"target": "Permafrost", "source": "Snow", "faction": "homm3_bulwark", "tileId": 30}' in packer, "custom biome Core packer must register Permafrost tile 30 for Bulwark from Snow", errors)


def validate_factory_bulwark_manifest(plugin_dir: Path, errors: list[str]) -> None:
    manifest_path = plugin_dir / CUSTOM_BIOME_MANIFEST
    manifest = read_json(manifest_path, errors)
    biomes = manifest.get("biomes") if isinstance(manifest, dict) else None
    require(isinstance(biomes, list), f"custom biome manifest must contain biomes list: {manifest_path}", errors)
    if not isinstance(biomes, list):
        return
    by_id = {row.get("id"): row for row in biomes if isinstance(row, dict)}
    for biome_id, name, tile_id, donor in (
        (FACTORY_BIOME_ID, FACTORY_BIOME_NAME, FACTORY_TILE_ID, FACTORY_DONOR_BIOME),
        (BULWARK_BIOME_ID, BULWARK_BIOME_NAME, BULWARK_TILE_ID, BULWARK_DONOR_BIOME),
    ):
        row = by_id.get(biome_id)
        require(isinstance(row, dict), f"custom biome manifest must contain {name} row id={biome_id!r}", errors)
        if not isinstance(row, dict):
            continue
        require(row.get("enabled") is True, f"{name} custom biome must be enabled: {row}", errors)
        require(row.get("name") == name, f"{name} custom biome name mismatch: {row}", errors)
        require(row.get("tileCode") == tile_id, f"{name} custom biome tileCode mismatch: {row}", errors)
        require(row.get("materialDonorName") == donor, f"{name} custom biome material donor mismatch: {row}", errors)
        require(row.get("materialAliasOnly") is False, f"{name} custom biome must use real Sand/Snow texture copies, not materialAliasOnly: {row}", errors)

def validate_void_asset_builder(repo_root: Path, errors: list[str]) -> None:
    builder_path = repo_root / "tools" / "release_port" / "build_custom_biome_assets.py"
    builder = read_text(builder_path, errors)
    require('"id": "void", "name": "Void", "tileCode": 23, "donor": "Dirt", "soundDonor": "Dirt", "variant": "void_black"' in builder, "custom biome asset builder must register Void tile 23 from Dirt with the void_black transform", errors)
    require('"id": "foundry", "name": "Foundry", "tileCode": 29, "donor": "Sand", "soundDonor": "Sand", "variant": "copy"' in builder, "custom biome asset builder must register Foundry tile 29 as a Sand copy clone for Factory", errors)
    require('"id": "permafrost", "name": "Permafrost", "tileCode": 30, "donor": "Snow", "soundDonor": "Snow", "variant": "copy"' in builder, "custom biome asset builder must register Permafrost tile 30 as a Snow copy clone for Bulwark", errors)
    require('if variant == "void_black":' in builder, "custom biome asset builder must implement the void_black transform", errors)
    require('return 0, 0, 0, a' in builder, "void_black transform must force RGB to black while preserving alpha", errors)


def validate_void_manifest(plugin_dir: Path, errors: list[str]) -> None:
    manifest_path = plugin_dir / CUSTOM_BIOME_MANIFEST
    manifest = read_json(manifest_path, errors)
    biomes = manifest.get("biomes") if isinstance(manifest, dict) else None
    require(isinstance(biomes, list), f"custom biome manifest must contain biomes list: {manifest_path}", errors)
    if not isinstance(biomes, list):
        return
    rows = [row for row in biomes if isinstance(row, dict) and row.get("id") == VOID_BIOME_ID]
    require(len(rows) == 1, f"custom biome manifest must contain exactly one Void row, found {len(rows)}", errors)
    if not rows:
        return
    row = rows[0]
    require(row.get("enabled") is True, f"Void custom biome must be enabled: {row}", errors)
    require(row.get("name") == VOID_BIOME_NAME, f"Void custom biome name mismatch: {row}", errors)
    require(row.get("tileCode") == VOID_TILE_ID, f"Void custom biome tileCode mismatch: {row}", errors)
    require(row.get("materialDonorName") == VOID_DONOR_BIOME, f"Void custom biome material donor mismatch: {row}", errors)
    require(row.get("materialDonorTileCode") == VOID_DONOR_TILE_ID, f"Void custom biome material donor tile mismatch: {row}", errors)
    require(row.get("soundDonorTileCode") == VOID_DONOR_TILE_ID, f"Void custom biome sound donor tile mismatch: {row}", errors)
    require(row.get("materialAliasOnly") is False, f"Void custom biome must use real black textures, not a material alias: {row}", errors)
    require(normalize_asset_path(row.get("textureAssetDir")) == VOID_TEXTURE_RELATIVE_DIR, f"Void custom biome texture dir mismatch: {row}", errors)
    require(row.get("textureFiles") == VOID_TEXTURE_FILES, f"Void custom biome texture file list mismatch: {row}", errors)




def validate_display_water_manifest(plugin_dir: Path, errors: list[str]) -> None:
    manifest_path = plugin_dir / CUSTOM_BIOME_MANIFEST
    manifest = read_json(manifest_path, errors)
    biomes = manifest.get("biomes") if isinstance(manifest, dict) else None
    require(isinstance(biomes, list), f"custom biome manifest must contain biomes list: {manifest_path}", errors)
    if not isinstance(biomes, list):
        return
    retired_ids = set(DISPLAY_WATER_TILE_ROWS)
    retired_tile_codes = {tile_code for tile_code, _name in DISPLAY_WATER_TILE_ROWS.values()}
    retired_rows = [
        row
        for row in biomes
        if isinstance(row, dict) and (row.get("id") in retired_ids or row.get("tileCode") in retired_tile_codes)
    ]
    require(not retired_rows, f"custom biome manifest must not contain retired display-water Sand alias rows 24-28: {retired_rows}", errors)
def validate_black_texture(path: Path, errors: list[str]) -> None:
    if not path.is_file():
        errors.append(f"missing Void texture asset: {path}")
        return
    try:
        with Image.open(path) as image:
            rgba = image.convert("RGBA")
            extrema = rgba.getextrema()
    except Exception as exc:  # noqa: BLE001 - validator should report all file-read failures uniformly.
        errors.append(f"failed to inspect Void texture {path}: {exc}")
        return
    require(extrema[0] == (0, 0) and extrema[1] == (0, 0) and extrema[2] == (0, 0), f"Void texture must be pure black RGB: {path} extrema={extrema}", errors)
    require(extrema[3][1] > 0, f"Void texture must not be fully transparent: {path} alpha={extrema[3]}", errors)


def validate_void_assets(plugin_dir: Path, errors: list[str]) -> None:
    texture_dir = plugin_dir / VOID_TEXTURE_DIR
    for file_name in VOID_TEXTURE_FILES:
        validate_black_texture(texture_dir / file_name, errors)
    report = read_json(texture_dir / VOID_REPORT_NAME, errors)
    require(isinstance(report, list) and len(report) == len(VOID_TEXTURE_FILES), f"Void terrain report must have one row per texture: {texture_dir / VOID_REPORT_NAME}", errors)
    if not isinstance(report, list):
        return
    report_names = sorted(Path(str(row.get("output", ""))).name for row in report if isinstance(row, dict))
    require(report_names == sorted(VOID_TEXTURE_FILES), f"Void terrain report output files mismatch: {report_names}", errors)
    for row in report:
        if not isinstance(row, dict):
            errors.append(f"Void terrain report row must be an object: {row}")
            continue
        require(row.get("variant") == VOID_VARIANT, f"Void terrain report must document void_black transform: {row}", errors)
        require(row.get("changedPixels", 0) > 0, f"Void terrain report must prove pixels were changed to black: {row}", errors)
        require(row.get("size") == [512, 512], f"Void terrain report must preserve native terrain texture size: {row}", errors)


def infer_game_core_zip(plugin_dir: Path) -> Path | None:
    for parent in plugin_dir.parents:
        candidate = parent / "HeroesOldenEra_Data" / "StreamingAssets" / "Core.zip"
        if candidate.exists():
            return candidate
    return None


def validate_void_core_row(core_zip: Path, errors: list[str]) -> None:
    if not core_zip.is_file():
        errors.append(f"Void Core.zip validation target is missing: {core_zip}")
        return
    try:
        with zipfile.ZipFile(core_zip) as core:
            tiles_doc = json.loads(core.read(CORE_TILES_MEMBER).decode("utf-8-sig"))
    except Exception as exc:  # noqa: BLE001 - validator should report all file-read failures uniformly.
        errors.append(f"failed to read {CORE_TILES_MEMBER} from {core_zip}: {exc}")
        return
    rows = tiles_doc.get("array") if isinstance(tiles_doc, dict) else None
    require(isinstance(rows, list), f"{CORE_TILES_MEMBER} must contain array rows in {core_zip}", errors)
    if not isinstance(rows, list):
        return
    matches = [row for row in rows if isinstance(row, dict) and row.get("id") == VOID_TILE_ID]
    require(len(matches) == 1, f"Core.zip must contain exactly one Void tile id {VOID_TILE_ID}, found {len(matches)}", errors)
    if not matches:
        return
    row = matches[0]
    require(row.get("biome") == VOID_BIOME_NAME, f"Void Core tile biome mismatch: {row}", errors)
    require(row.get("name") == f"tiles_{VOID_TILE_ID}", f"Void Core tile name mismatch: {row}", errors)
    require(row.get("penalty") == VOID_CORE_TILE_PENALTY, f"Void Core tile penalty mismatch: {row}", errors)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--plugin-dir", type=Path)
    parser.add_argument("--core", type=Path, help="Optional installed Core.zip to validate terrain tile registration")
    args = parser.parse_args()

    repo_root = args.repo_root.resolve()
    plugin_dir = args.plugin_dir.resolve() if args.plugin_dir else repo_root / PLUGIN_DIR
    source_plugin_dir = repo_root / PLUGIN_DIR
    renderer_path = source_plugin_dir / RENDERER_SOURCE
    symbols_path = source_plugin_dir / SYMBOLS_SOURCE

    errors: list[str] = []
    renderer = read_text(renderer_path, errors)
    symbols = read_text(symbols_path, errors)
    overlay_visual = read_text(source_plugin_dir / WATER_OVERLAY_SOURCE, errors)
    map_object_hook = read_text(source_plugin_dir / MAP_OBJECT_HOOK_SOURCE, errors)
    import_visuals = read_text(source_plugin_dir / IMPORT_VISUALS_SOURCE, errors)

    validate_terrain_lookup_reconciliation(repo_root, renderer, errors)
    for label, token in REQUIRED_RENDERER_TOKENS.items():
        require(token in renderer, f"renderer missing {label}: {token}", errors)
    for label, token in FORBIDDEN_RENDERER_TOKENS.items():
        require(token not in renderer, f"renderer must not contain {label}: {token}", errors)
    for label, token in REQUIRED_SYMBOL_TOKENS.items():
        require(token in symbols, f"GameSymbols missing {label}: {token}", errors)
    require("terrain.material.renderer.buildMap" not in symbols,
            "GameSymbols must not keep the ambiguous terrain renderer buildMap symbol; Method_Private_Void_Map_0 belongs only to texture-node upload", errors)
    require("Homm3HomecomingWaterTileOverlayVisual.RegisterRequired(harmony, log)" not in renderer,
            "renderer registration must not register the retired Homecoming water object overlay visual", errors)
    require("Homm3TerrainWaterAnimator.RegisterRequired(log)" not in renderer,
            "renderer registration must not activate the retired packed-terrain water animator", errors)
    require("var waterAnimationRequired = RequiresTerrainWaterAnimationBinding(source);" in renderer,
            "renderer rebuild path must keep an explicit water-animation gate", errors)
    require("if (waterAnimationRequired && map != null && textureNodeUploadMethod != null)" in renderer,
            "terrain water animation binding calls must be gated by waterAnimationRequired", errors)
    requires_index = renderer.find("private static bool RequiresTerrainWaterAnimationBinding(string source)")
    require(requires_index >= 0,
            "RequiresTerrainWaterAnimationBinding must exist for native water tile animation", errors)
    disabled_index = renderer.find("return false;", requires_index)
    require(disabled_index > requires_index,
            "RequiresTerrainWaterAnimationBinding must remain inactive for native waterMap mesh visuals", errors)
    require("AppendNativeWaterMaterialBiomes" not in renderer,
            "renderer must not append HoMM3 terrain water material biomes for tile codes 18-22", errors)
    require("AppendNativeWaterTerrainBiomesFromCatalog" in renderer,
            "renderer must append native Water catalog biomes for tile codes 18-22", errors)
    require("NativeWaterTerrainDonorTileCode" in renderer,
            "renderer must keep deep-water tile code 18 for native water biome naming", errors)
    require("NativeWaterTerrainSeabedDonorTileCode" in renderer,
            "renderer must capture native Sand seabed donor tile code 2 for water terrain under the waterMap mesh", errors)
    require("TryCaptureSandSeabedDonorBiomeFromTerrain" in renderer,
            "renderer must capture Sand seabed textures for water tile codes 18-22", errors)
    require("TrySynthesizeNativeWaterDonorBiomeFromBundledTerrainTextures" not in renderer,
            "renderer must not synthesize bundled HoMM3 water PNGs as the seabed under the waterMap mesh", errors)
    require("ResolveAliasDonorMaterialSlot" in renderer,
            "renderer must resolve alias donor slots from always-present native terrain biomes", errors)
    require("TrySynthesizeDisplayWaterDonorBiome" not in renderer,
            "renderer must not synthesize packaged-texture Water donor fallbacks", errors)
    require("EnsureNativeWaterTerrainLookupEntries" in renderer,
            "renderer must seed native water terrain tile codes 18-22 into the material lookup", errors)
    require("displayWaterAlias=" in renderer,
            "renderer must log whether display-water alias tiles are present during map scope resolution", errors)
    require("if (!_registered || !IsKnownSid(sid))" in overlay_visual,
            "retired water tile overlay visual must remain inert unless explicitly registered", errors)
    require("Homm3HomecomingWaterTileOverlayVisual.TryApply(root, sid, Plugin.LogSource)" in map_object_hook,
            "map object visual hook must keep the legacy inert water-overlay TryApply signature", errors)
    retired_overlay_tokens = [
        "ManifestNativeBinding",
        "ValidateRequiredVisualContract",
        "IdentityManifestName",
        "LoadRequiredIdentityManifest()",
        "objectIdsBySid",
        "nodesByMapSid",
        "_sidByObjectId",
        "_sidByNodeByMapSid",
        "ResolveOverlaySid",
        "IdentityDonorCarrierSid",
        "Homm3WaterTileOverlayRendererSuppressionState",
        "Homm3WaterTileOverlayDonorSuppressor",
        "ClassInjector.RegisterTypeInIl2Cpp",
        "TryApply(root, sid, objectId",
        "PlacedObjectIdFields",
        "PlacedObjectNodeFields",
    ]
    combined_overlay_hook = overlay_visual + "\n" + map_object_hook
    for token in retired_overlay_tokens:
        require(token not in combined_overlay_hook, f"display-only water must not retain retired object-overlay identity/suppressor token: {token}", errors)
    for forbidden in [
        "Homm3MapBillboardCameraFacing",
        "Sprites/Default",
        "Unlit",
        "keepRevealed: true",
        "RegisterTerrainPackedColorLayerBinding",
        "CopyTerrainTextureToArraySlot",
    ]:
        require(forbidden not in overlay_visual, f"water tile overlay visual must not use retired/debug terrain or camera-facing token: {forbidden}", errors)
    material_helper_index = overlay_visual.find("private static Material GetOrCreateOverlayMaterial")
    material_create_index = overlay_visual.find("EsquirePikemanVisuals.CreateSanitizedHexLitMapBillboardMaterial")
    require(material_helper_index >= 0 and material_create_index > material_helper_index,
            "water overlay visual must create Hex/Lit overlay materials inside the shared per-SID material helper", errors)
    for forbidden in [
        "GameSymbols.TerrainMaterial.RendererBuildMap",
        "harmony.Patch(rendererBuildMap",
        "PrefixRendererBuildMapValidate",
        "PostfixRendererBuildMapRebuild",
        "map != null || textureNodeUploadMethod != null",
        "RegisterTerrainWaterAnimationBinding(renderer, rendererType, \"terrain renderer registration validation\")",
        "water animation binding skipped",
    ]:
        require(forbidden not in renderer, f"renderer must not retain retired or partial water animation hook token: {forbidden}", errors)
    validate_water_shore_pack_registration(repo_root, errors)
    validate_void_asset_builder(repo_root, errors)
    validate_void_manifest(plugin_dir, errors)
    validate_factory_bulwark_manifest(plugin_dir, errors)
    validate_display_water_manifest(plugin_dir, errors)
    validate_void_assets(plugin_dir, errors)
    core_zip = args.core.resolve() if args.core else infer_game_core_zip(plugin_dir)
    if core_zip is not None:
        validate_void_core_row(core_zip, errors)
    require("CustomBiomePackedSlotCapacity = 32" in symbols, "GameSymbols must size CustomBiomePackedSlotCapacity to cover Foundry/Permafrost tile codes 29-30", errors)

    require("TryReadMapDataDimensions(mapData, raw, out width, out height, out reason)" in renderer, "renderer must derive active packed-layer dimensions from MapData plus tilesMap length", errors)
    require("layer[(y * shape.Width) + x]" in renderer, "renderer packed color layer construction must index rectangular dimensions", errors)
    require("active map packed layer dimensions were unresolved" in renderer, "renderer must fail closed when active packed-layer dimensions are unknown", errors)

    if errors:
        print("HoMM3 custom-biome runtime contract FAIL")
        for error in errors:
            print(f"- {error}")
        return 1
    print("HoMM3 custom-biome runtime contract PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
