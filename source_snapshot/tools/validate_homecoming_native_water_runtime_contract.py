#!/usr/bin/env python3
"""Validate Homecoming native vanilla water tile baseline and traversal bridge registration."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image

MAP_SID = "h3_roe_castle_homecoming_single_layer"
LAYERED_ATLAS_MAP_SID = "h3_roe_castle_homecoming_layered_atlas"
VANILLA_WATER_VISUAL_DONOR_TILE_CODE = 18
DISPLAY_WATER_BEHAVIOR_DONOR_TILE_CODE = 18
DISPLAY_WATER_BEHAVIOR_DONOR_BIOME = "Water"
WATER_TILE_CODE = 18
WATER_SHORE_TILE_CODES_BY_EDGE = {
    "north": 19,
    "south": 20,
    "west": 21,
    "east": 22,
}
WATER_TILE_CODES = tuple([WATER_TILE_CODE, *WATER_SHORE_TILE_CODES_BY_EDGE.values()])
RETIRED_DISPLAY_WATER_TILE_CODES = {24, 25, 26, 27, 28}
RETIRED_DISPLAY_WATER_BIOME_IDS = {
    "display_water",
    "display_water_shore_north",
    "display_water_shore_south",
    "display_water_shore_west",
    "display_water_shore_east",
}
WATER_TILE_OVERLAY_STATUS = "retired_runtime_hook_did_not_apply"
WATER_TILE_OVERLAY_ARCHITECTURE = "retired_pathable_environment_object_visual_overlay"
WATER_TILE_OVERLAY_RUNTIME_VISUAL = "Homm3HomecomingWaterTileOverlayVisual"
WATER_TILE_OVERLAY_OBJECT_MEMBER = "DB/map/objects/homecoming_water_tile_overlays.json"
WATER_TILE_OVERLAY_DONOR_PREFAB = "environment/grass_1"
WATER_TILE_OVERLAY_ID_BASE = 910000
WATER_TILE_OVERLAY_IDENTITY_SCHEMA = "homm3.homecoming_water_tile_overlay_identity.v2"
WATER_TILE_OVERLAY_IDENTITY_RELATIVE = Path("homm3_runtime_assets") / "campaign_port" / "homecoming_water_tile_overlay_identity_manifest.json"
WATER_TILE_OVERLAY_SID_BY_TILE_CODE = {
    WATER_TILE_CODE: "homm3_homecoming_water_overlay_deep",
    WATER_SHORE_TILE_CODES_BY_EDGE["north"]: "homm3_homecoming_water_overlay_shore_north",
    WATER_SHORE_TILE_CODES_BY_EDGE["south"]: "homm3_homecoming_water_overlay_shore_south",
    WATER_SHORE_TILE_CODES_BY_EDGE["west"]: "homm3_homecoming_water_overlay_shore_west",
    WATER_SHORE_TILE_CODES_BY_EDGE["east"]: "homm3_homecoming_water_overlay_shore_east",
}
EXPECTED_WATER_TILE_OVERLAY_EMITTED_BY_TILE_CODE = {"18": 855, "19": 8, "20": 73, "21": 4, "22": 8}
EXPECTED_WATER_TILE_OVERLAY_EMITTED_COUNT = sum(EXPECTED_WATER_TILE_OVERLAY_EMITTED_BY_TILE_CODE.values())
EXPECTED_WATER_TILE_OVERLAY_MAP_SIDS = {MAP_SID, LAYERED_ATLAS_MAP_SID}
EXPECTED_WATER_TILE_OVERLAY_SID_HISTOGRAM = {
    WATER_TILE_OVERLAY_SID_BY_TILE_CODE[int(tile_code)]: count
    for tile_code, count in EXPECTED_WATER_TILE_OVERLAY_EMITTED_BY_TILE_CODE.items()
}
WATER_TILE_OVERLAY_VISUAL_CONTRACT = {
    "material": "sanitized_native_hex_lit_billboard_material_per_sid",
    "animation": "multi_frame_map_idle_texture_animator",
    "orientation": "flat_against_landscape",
    "mesh": "horizontal_quad",
    "cameraFacing": False,
}
RETIRED_RUNTIME_RELATIVE = Path("homm3_runtime_assets") / "campaign_port" / "homecoming_water_layer.json"
WATER_TRAVERSAL_PLAN_RELATIVE = Path("homm3_runtime_assets") / "campaign_port" / "homecoming_water_traversal_plan.json"
STALE_WATER_TEXTURE = Path("homm3_runtime_assets") / "custom_biomes" / "water" / "shore_sand.png"
WATER_REPORT = Path("homm3_runtime_assets") / "custom_biomes" / "water" / "water_terrain_report.json"
WATER_ANIMATION_DIR = Path("homm3_runtime_assets") / "custom_biomes" / "water_animation"
WATER_ANIMATION_MANIFEST = WATER_ANIMATION_DIR / "water_animation_manifest.json"
WATER_ANIMATION_SCHEMA = "homm3.homecoming_terrain_water_animation.v1"
WATER_ANIMATION_RENDERER = "Homm3TerrainWaterAnimator"
WATER_ANIMATION_NATIVE_BINDING = "terrain_renderer_packed_color_layers_texture_node_upload"
WATER_ANIMATION_FRAME_COUNT = 33
WATER_ANIMATION_FRAMES_PER_SECOND = 8.0
WATER_ANIMATION_KIND_BY_TILE_CODE = {
    18: "deep_ocean",
    19: "shoreline_north",
    20: "shoreline_south",
    21: "shoreline_west",
    22: "shoreline_east",
}
DEEP_WATER_TEXTURES = [
    Path("homm3_runtime_assets") / "custom_biomes" / "water" / "water1.png",
    Path("homm3_runtime_assets") / "custom_biomes" / "water" / "water2.png",
    Path("homm3_runtime_assets") / "custom_biomes" / "water" / "water3.png",
]
SHORELINE_TEXTURES = [
    (edge, Path("homm3_runtime_assets") / "custom_biomes" / f"water_shore_{edge}" / f"water_shore_{edge}_{index}.png")
    for edge in WATER_SHORE_TILE_CODES_BY_EDGE
    for index in range(1, 4)
]
BLUE_OCEAN_POLICY = "blue_ocean_only_no_rocks"
BLUE_OCEAN_COLOR_POLICY = "normalize_all_opaque_pixels_to_blue_ocean_palette"
SHORELINE_POLICY = "homm3_ocean_tileset_sandy_edge_frames"
SHORELINE_COLOR_POLICY = "preserve_homm3_sandy_ocean_edge_pixels"
SHORELINE_SOURCE_FRAMES_BY_EDGE = {
    "north": ("00_08.png", "00_09.png", "00_10.png", "00_11.png"),
    "south": ("00_08.png", "00_09.png", "00_10.png", "00_11.png"),
    "west": ("00_04.png", "00_05.png", "00_06.png", "00_07.png"),
    "east": ("00_04.png", "00_05.png", "00_06.png", "00_07.png"),
}
SHORELINE_SOURCE_TRANSFORM_BY_EDGE = {
    "north": "none",
    "south": "flip_y",
    "west": "none",
    "east": "flip_x",
}
BLUE_OCEAN_VARIANTS = ["blue_ocean_no_rocks_mix_1", "blue_ocean_no_rocks_mix_2", "blue_ocean_no_rocks_mix_3"]
SHORELINE_VARIANTS = [f"shoreline_{edge}_mix_{index}" for edge in WATER_SHORE_TILE_CODES_BY_EDGE for index in range(1, 4)]
MIN_BLUE_OCEAN_FRAME_COUNT = 6
MIN_SHORELINE_SOURCE_FRAME_COUNT = 4
MAX_SOURCE_ROCK_LIKE_RATIO = 0.0
OUTPUT_BLUE_MIN_RED_MARGIN = 40
OUTPUT_BLUE_MIN_GREEN_MARGIN = 40
TILE_SIZE = 32
SOURCE_TILE_GRID = 1
OUTPUT_SIZE = 512
TEXTURE_SCALE_POLICY = "one_homm3_tile_scaled_to_one_olden_tile_texture"
MIN_SHORELINE_EDGE_SAND_RATIO = 0.55
MAX_SHORELINE_OPPOSITE_EDGE_SAND_RATIO = 0.08
SHORELINE_BAND_RATIO = 0.25


def read_text(path: Path) -> str:
    if not path.is_file():
        raise SystemExit(f"missing required file: {path}")
    return path.read_text(encoding="utf-8-sig", errors="replace")


def read_json(path: Path) -> dict:
    if not path.is_file():
        raise SystemExit(f"missing required JSON: {path}")
    return json.loads(path.read_text(encoding="utf-8-sig"))


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def iter_image_pixels(image: Image.Image):
    getter = getattr(image, "get_flattened_data", None)
    if getter is not None:
        return getter()
    return image.getdata()


def is_sand_like_pixel(r: int, g: int, b: int, a: int) -> bool:
    return a > 0 and r > b + 18 and g > b - 4 and r > 82 and g > 68


def opposite_edge(edge: str) -> str:
    return {
        "north": "south",
        "south": "north",
        "west": "east",
        "east": "west",
    }[edge]


def edge_band_bounds(width: int, height: int, edge: str, band_ratio: float) -> tuple[range, range]:
    band_x = max(1, round(width * band_ratio))
    band_y = max(1, round(height * band_ratio))
    if edge == "north":
        return range(0, width), range(0, band_y)
    if edge == "south":
        return range(0, width), range(height - band_y, height)
    if edge == "west":
        return range(0, band_x), range(0, height)
    if edge == "east":
        return range(width - band_x, width), range(0, height)
    raise ValueError(f"unknown shoreline edge: {edge}")


def analyze_edge_band(image: Image.Image, edge: str) -> dict[str, object]:
    width, height = image.size
    x_range, y_range = edge_band_bounds(width, height, edge, SHORELINE_BAND_RATIO)
    opaque = 0
    sand_like = 0
    for y in y_range:
        for x in x_range:
            r, g, b, a = image.getpixel((x, y))
            if a == 0:
                continue
            opaque += 1
            if is_sand_like_pixel(r, g, b, a):
                sand_like += 1
    return {
        "edge": edge,
        "opaquePixelCount": opaque,
        "sandLikePixelCount": sand_like,
        "sandLikePixelRatio": 0.0 if opaque == 0 else sand_like / opaque,
    }


def audit_shoreline_texture(image: Image.Image, edge: str) -> dict[str, object]:
    tile_size = image.size[0] // SOURCE_TILE_GRID
    edge_pixels = 0
    edge_sand = 0
    opposite_pixels = 0
    opposite_sand = 0
    for tile_y in range(SOURCE_TILE_GRID):
        for tile_x in range(SOURCE_TILE_GRID):
            tile = image.crop((tile_x * tile_size, tile_y * tile_size, (tile_x + 1) * tile_size, (tile_y + 1) * tile_size))
            edge_audit = analyze_edge_band(tile, edge)
            opposite_audit = analyze_edge_band(tile, opposite_edge(edge))
            edge_pixels += int(edge_audit["opaquePixelCount"])
            edge_sand += int(edge_audit["sandLikePixelCount"])
            opposite_pixels += int(opposite_audit["opaquePixelCount"])
            opposite_sand += int(opposite_audit["sandLikePixelCount"])
    return {
        "edge": edge,
        "tileEdgeOpaquePixelCount": edge_pixels,
        "tileEdgeSandLikePixelCount": edge_sand,
        "tileEdgeSandLikePixelRatio": 0.0 if edge_pixels == 0 else edge_sand / edge_pixels,
        "tileOppositeEdgeOpaquePixelCount": opposite_pixels,
        "tileOppositeEdgeSandLikePixelCount": opposite_sand,
        "tileOppositeEdgeSandLikePixelRatio": 0.0 if opposite_pixels == 0 else opposite_sand / opposite_pixels,
    }


def validate_texture_scale_report(entry: dict[str, object]) -> None:
    require(entry.get("textureScalePolicy") == TEXTURE_SCALE_POLICY, f"water report texture scale policy mismatch: {entry}")
    require(entry.get("sourceTileSize") == TILE_SIZE, f"water report source tile size mismatch: {entry}")
    require(entry.get("sourceTilesPerOutputTexture") == SOURCE_TILE_GRID, f"water report source tile count mismatch: {entry}")
    require(entry.get("outputTextureSize") == OUTPUT_SIZE, f"water report output texture size mismatch: {entry}")
    require(entry.get("size") == [OUTPUT_SIZE, OUTPUT_SIZE], f"water report output image size mismatch: {entry}")


def validate_blue_ocean_report(report: object) -> None:
    require(isinstance(report, list) and len(report) == 15, "water terrain report must contain three deep-water rows plus twelve shoreline rows")
    variants = [entry.get("variant") for entry in report if isinstance(entry, dict)]
    require(variants == BLUE_OCEAN_VARIANTS + SHORELINE_VARIANTS, f"water terrain report variant list mismatch: {variants}")
    for entry in report:
        require(isinstance(entry, dict), f"water terrain report row must be an object: {entry}")
        if entry.get("kind") == "deep_ocean":
            require(entry.get("policy") == BLUE_OCEAN_POLICY, f"deep-water report policy mismatch: {entry}")
            frames = entry.get("blueOceanFrames")
            require(isinstance(frames, list) and len(frames) >= MIN_BLUE_OCEAN_FRAME_COUNT, f"water report missing blue-ocean frame list: {entry}")
            require(entry.get("blueOceanFrameCount") == len(frames), f"water report blue-ocean frame count mismatch: {entry}")
            validate_texture_scale_report(entry)
            require(entry.get("sourceTextureFrame") in frames, f"water report source texture frame must be one selected HoMM3 blue-ocean frame: {entry}")
            require(entry.get("cleanOceanFrameCount", 0) >= len(frames), f"water report clean-ocean frame count must cover selected frames: {entry}")
            require(entry.get("maxAllowedSourceRockLikeRatio") == MAX_SOURCE_ROCK_LIKE_RATIO, f"water report rock threshold mismatch: {entry}")
            require(entry.get("maxSelectedSourceRockLikeRatio", 1.0) <= MAX_SOURCE_ROCK_LIKE_RATIO, f"water report selected a rock-like source frame: {entry}")
            selected_metrics = entry.get("selectedFrameMetrics")
            require(isinstance(selected_metrics, list) and len(selected_metrics) == len(frames), f"water report selected-frame metrics mismatch: {entry}")
            for metric in selected_metrics:
                require(isinstance(metric, dict) and metric.get("rockLikeRatio", 1.0) <= MAX_SOURCE_ROCK_LIKE_RATIO, f"water report selected-frame metric is rock-like: {metric}")
            require(entry.get("colorPolicy") == BLUE_OCEAN_COLOR_POLICY, f"deep-water report color policy mismatch: {entry}")
            audit = entry.get("outputBlueOceanAudit")
            require(isinstance(audit, dict), f"water report missing output blue-ocean audit: {entry}")
            require(audit.get("nonBluePixelCount") == 0, f"water report allows non-blue output pixels: {audit}")
            rule = audit.get("blueDominanceRule")
            require(isinstance(rule, dict), f"water report missing blue dominance rule: {audit}")
            require(rule.get("minRedMargin") == OUTPUT_BLUE_MIN_RED_MARGIN, f"water report red-margin rule mismatch: {audit}")
            require(rule.get("minGreenMargin") == OUTPUT_BLUE_MIN_GREEN_MARGIN, f"water report green-margin rule mismatch: {audit}")
        elif entry.get("kind") == "shoreline_edge":
            edge = entry.get("edge")
            require(edge in WATER_SHORE_TILE_CODES_BY_EDGE, f"shoreline report edge mismatch: {entry}")
            require(entry.get("policy") == SHORELINE_POLICY, f"shoreline report policy mismatch: {entry}")
            require(entry.get("colorPolicy") == SHORELINE_COLOR_POLICY, f"shoreline report color policy mismatch: {entry}")
            require(entry.get("shorelineSourceFrameCount") == MIN_SHORELINE_SOURCE_FRAME_COUNT, f"shoreline report source frame count mismatch: {entry}")
            require(entry.get("shorelineSourceFrames") == list(SHORELINE_SOURCE_FRAMES_BY_EDGE[edge]), f"shoreline report source frames mismatch: {entry}")
            validate_texture_scale_report(entry)
            require(entry.get("outputSourceFrame") in entry.get("shorelineSourceFrames"), f"shoreline report output source frame must be one selected HoMM3 shoreline frame: {entry}")
            require(entry.get("sourceTransform") == SHORELINE_SOURCE_TRANSFORM_BY_EDGE[edge], f"shoreline report source transform mismatch: {entry}")
            metrics = entry.get("sourceFrameMetrics")
            require(isinstance(metrics, list) and len(metrics) == MIN_SHORELINE_SOURCE_FRAME_COUNT, f"shoreline report source-frame metrics mismatch: {entry}")
            for metric in metrics:
                require(isinstance(metric, dict), f"shoreline source-frame metric must be object: {metric}")
                edge_audit = metric.get("edgeAudit")
                opposite_audit = metric.get("oppositeEdgeAudit")
                require(isinstance(edge_audit, dict) and edge_audit.get("sandLikePixelRatio", 0.0) >= MIN_SHORELINE_EDGE_SAND_RATIO, f"shoreline source frame lacks sandy edge: {metric}")
                require(isinstance(opposite_audit, dict) and opposite_audit.get("sandLikePixelRatio", 1.0) <= MAX_SHORELINE_OPPOSITE_EDGE_SAND_RATIO, f"shoreline source frame has sandy opposite edge: {metric}")
            audit = entry.get("outputShorelineAudit")
            require(isinstance(audit, dict), f"shoreline report missing output audit: {entry}")
            require(audit.get("tileEdgeSandLikePixelRatio", 0.0) >= MIN_SHORELINE_EDGE_SAND_RATIO, f"shoreline report output lacks sandy edge: {audit}")
            require(audit.get("tileOppositeEdgeSandLikePixelRatio", 1.0) <= MAX_SHORELINE_OPPOSITE_EDGE_SAND_RATIO, f"shoreline report output has sandy opposite edge: {audit}")
        else:
            raise SystemExit(f"water terrain report row has unknown kind: {entry}")


def validate_blue_ocean_texture(path: Path) -> None:
    image = Image.open(path).convert("RGBA")
    require(list(image.size) == [OUTPUT_SIZE, OUTPUT_SIZE], f"native water texture must be {OUTPUT_SIZE}x{OUTPUT_SIZE}: {path} {image.size}")
    opaque = 0
    non_blue = 0
    for r, g, b, a in iter_image_pixels(image):
        if a == 0:
            continue
        opaque += 1
        if b < r + OUTPUT_BLUE_MIN_RED_MARGIN or b < g + OUTPUT_BLUE_MIN_GREEN_MARGIN:
            non_blue += 1
    require(opaque > 0, f"native water texture must contain opaque pixels: {path}")
    require(non_blue == 0, f"native water texture contains {non_blue} non-blue pixel(s): {path}")


def validate_shoreline_texture(path: Path, edge: str) -> None:
    image = Image.open(path).convert("RGBA")
    require(list(image.size) == [OUTPUT_SIZE, OUTPUT_SIZE], f"native shoreline water texture must be {OUTPUT_SIZE}x{OUTPUT_SIZE}: {path} {image.size}")
    opaque = sum(1 for _r, _g, _b, a in iter_image_pixels(image) if a != 0)
    require(opaque > 0, f"native shoreline water texture must contain opaque pixels: {path}")
    audit = audit_shoreline_texture(image, edge)
    require(audit["tileEdgeSandLikePixelRatio"] >= MIN_SHORELINE_EDGE_SAND_RATIO, f"native shoreline texture lacks sandy {edge} edge: {path} {audit}")
    require(audit["tileOppositeEdgeSandLikePixelRatio"] <= MAX_SHORELINE_OPPOSITE_EDGE_SAND_RATIO, f"native shoreline texture has sandy opposite edge: {path} {audit}")



def validate_water_animation_assets(plugin_dir: Path, source_plugin_dir: Path | None = None) -> None:
    manifest_path = plugin_dir / WATER_ANIMATION_MANIFEST
    manifest = read_json(manifest_path)
    require(manifest.get("schema") == WATER_ANIMATION_SCHEMA, f"water animation manifest schema mismatch: {manifest.get('schema')}")
    require(manifest.get("renderer") == WATER_ANIMATION_RENDERER, "water animation manifest must name the packed-terrain water animator")
    require(manifest.get("nativeBinding") == WATER_ANIMATION_NATIVE_BINDING, "water animation must bind through terrain renderer packed color layer uploads")
    require(manifest.get("sourceDef") == "Watrtl.def", f"water animation sourceDef mismatch: {manifest.get('sourceDef')}")
    require(manifest.get("frameCount") == WATER_ANIMATION_FRAME_COUNT, f"water animation frameCount mismatch: {manifest.get('frameCount')}")
    require(manifest.get("framesPerSecond") == WATER_ANIMATION_FRAMES_PER_SECOND, f"water animation fps mismatch: {manifest.get('framesPerSecond')}")
    require(manifest.get("textureScalePolicy") == TEXTURE_SCALE_POLICY, f"water animation scale policy mismatch: {manifest.get('textureScalePolicy')}")
    require(manifest.get("sourceTilesPerOutputTexture") == SOURCE_TILE_GRID, f"water animation source tile grid mismatch: {manifest.get('sourceTilesPerOutputTexture')}")
    require(manifest.get("outputTextureSize") == OUTPUT_SIZE, f"water animation output size mismatch: {manifest.get('outputTextureSize')}")
    sequences = manifest.get("tileCodeSequences")
    require(isinstance(sequences, dict), "water animation manifest must contain tileCodeSequences")
    require(set(sequences or {}) == {str(tile_code) for tile_code in WATER_TILE_CODES}, f"water animation tile code set mismatch: {sorted((sequences or {}).keys())}")
    for tile_code, expected_kind in WATER_ANIMATION_KIND_BY_TILE_CODE.items():
        sequence = sequences.get(str(tile_code)) if isinstance(sequences, dict) else None
        require(isinstance(sequence, dict), f"water animation sequence missing for tileCode={tile_code}")
        require(sequence.get("kind") == expected_kind, f"water animation kind mismatch for tileCode={tile_code}: {sequence}")
        require(sequence.get("tileCode") == tile_code, f"water animation tileCode mismatch: {sequence}")
        files = sequence.get("files")
        require(isinstance(files, list) and len(files) == WATER_ANIMATION_FRAME_COUNT, f"water animation files mismatch for tileCode={tile_code}: {files}")
        for index, rel_name in enumerate(files if isinstance(files, list) else []):
            frame = plugin_dir / WATER_ANIMATION_DIR / rel_name
            require(frame.is_file(), f"missing water animation frame: {frame}")
            if source_plugin_dir is not None:
                source = source_plugin_dir / WATER_ANIMATION_DIR / rel_name
                require(source.is_file(), f"missing source water animation frame: {source}")
                require(frame.read_bytes() == source.read_bytes(), f"deployed water animation frame does not match source: {rel_name}")
            with Image.open(frame) as image:
                require(list(image.size) == [OUTPUT_SIZE, OUTPUT_SIZE], f"water animation frame must be {OUTPUT_SIZE}x{OUTPUT_SIZE}: tileCode={tile_code} frame={index} {frame} {image.size}")
    if source_plugin_dir is not None:
        source_manifest = source_plugin_dir / WATER_ANIMATION_MANIFEST
        require(source_manifest.is_file(), f"missing source water animation manifest: {source_manifest}")
        require(manifest_path.read_bytes() == source_manifest.read_bytes(), f"deployed water animation manifest does not match source: {WATER_ANIMATION_MANIFEST}")

def validate_water_overlay_identity_manifest(plugin_dir: Path, source_plugin_dir: Path | None = None) -> None:
    manifest_path = plugin_dir / WATER_TILE_OVERLAY_IDENTITY_RELATIVE
    manifest = read_json(manifest_path)
    require(manifest.get("schema") == WATER_TILE_OVERLAY_IDENTITY_SCHEMA, f"water overlay identity schema mismatch: {manifest.get('schema')}")
    require(manifest.get("status") == WATER_TILE_OVERLAY_STATUS, f"water overlay identity status mismatch: {manifest}")
    require(manifest.get("architecture") == WATER_TILE_OVERLAY_ARCHITECTURE, f"water overlay identity architecture mismatch: {manifest}")
    require(manifest.get("runtimeVisual") == WATER_TILE_OVERLAY_RUNTIME_VISUAL, f"water overlay identity runtime visual mismatch: {manifest}")
    require(manifest.get("objectMember") == WATER_TILE_OVERLAY_OBJECT_MEMBER, f"water overlay identity object member mismatch: {manifest}")
    require(manifest.get("donorPrefab") == WATER_TILE_OVERLAY_DONOR_PREFAB, f"water overlay identity donor prefab mismatch: {manifest}")
    require(manifest.get("objectIdBase") == WATER_TILE_OVERLAY_ID_BASE, f"water overlay identity object id base mismatch: {manifest}")
    require(manifest.get("emittedCount") == EXPECTED_WATER_TILE_OVERLAY_EMITTED_COUNT, f"water overlay identity emitted count mismatch: {manifest}")
    require(manifest.get("objectSidsByTileCode") == {str(tile): sid for tile, sid in sorted(WATER_TILE_OVERLAY_SID_BY_TILE_CODE.items())}, f"water overlay identity SID map mismatch: {manifest}")
    require(manifest.get("visualContract") == WATER_TILE_OVERLAY_VISUAL_CONTRACT, f"water overlay identity visual contract mismatch: {manifest}")
    require(manifest.get("identityPolicy") == "runtime overlay instances resolve by donor-carrier generated map object id first and donor-carrier map-scoped node second, both scoped to recognized Homecoming map SIDs; donor prefab SID is never treated as an overlay SID", f"water overlay identity policy mismatch: {manifest}")
    require(manifest.get("nodeIdentityPolicy") == "node aliases are scoped by map SID and are only considered when the live object reports the registered donor carrier SID, because single-layer and layered-atlas node coordinates can overlap with different shore variants", f"water overlay node identity policy mismatch: {manifest}")
    object_ids_by_sid = manifest.get("objectIdsBySid")
    nodes_by_map_sid = manifest.get("nodesByMapSid")
    require(isinstance(object_ids_by_sid, dict), "water overlay identity manifest must contain objectIdsBySid")
    require(isinstance(nodes_by_map_sid, dict), "water overlay identity manifest must contain nodesByMapSid")
    expected_sids = set(WATER_TILE_OVERLAY_SID_BY_TILE_CODE.values())
    require(set(object_ids_by_sid or {}) == expected_sids, f"water overlay identity object SID keys mismatch: {object_ids_by_sid}")
    require(set(nodes_by_map_sid or {}) == EXPECTED_WATER_TILE_OVERLAY_MAP_SIDS, f"water overlay identity map SID keys mismatch: {nodes_by_map_sid}")
    all_ids: list[int] = []
    if isinstance(object_ids_by_sid, dict):
        for sid, expected_count in EXPECTED_WATER_TILE_OVERLAY_SID_HISTOGRAM.items():
            object_ids = object_ids_by_sid.get(sid)
            require(isinstance(object_ids, list) and all(isinstance(value, int) for value in object_ids), f"water overlay identity object ids for {sid} must be ints: {object_ids}")
            require(isinstance(object_ids, list) and len(object_ids) == expected_count, f"water overlay identity object id count mismatch for {sid}: {object_ids}")
            all_ids.extend(object_ids if isinstance(object_ids, list) else [])
    expected_ids = list(range(WATER_TILE_OVERLAY_ID_BASE, WATER_TILE_OVERLAY_ID_BASE + EXPECTED_WATER_TILE_OVERLAY_EMITTED_COUNT))
    require(sorted(all_ids) == expected_ids, f"water overlay identity object ids must be contiguous from {WATER_TILE_OVERLAY_ID_BASE}")
    require(len(set(all_ids)) == EXPECTED_WATER_TILE_OVERLAY_EMITTED_COUNT, "water overlay identity object ids must be unique")
    if isinstance(nodes_by_map_sid, dict):
        for map_sid in EXPECTED_WATER_TILE_OVERLAY_MAP_SIDS:
            nodes_by_sid = nodes_by_map_sid.get(map_sid)
            require(isinstance(nodes_by_sid, dict), f"water overlay identity nodes for map {map_sid} must be grouped by SID: {nodes_by_sid}")
            require(set(nodes_by_sid or {}) == expected_sids, f"water overlay identity node SID keys mismatch for map {map_sid}: {nodes_by_sid}")
            all_nodes: list[int] = []
            if isinstance(nodes_by_sid, dict):
                for sid, expected_count in EXPECTED_WATER_TILE_OVERLAY_SID_HISTOGRAM.items():
                    nodes = nodes_by_sid.get(sid)
                    require(isinstance(nodes, list) and all(isinstance(value, int) for value in nodes), f"water overlay identity nodes for {map_sid}/{sid} must be ints: {nodes}")
                    require(isinstance(nodes, list) and len(nodes) == expected_count, f"water overlay identity node count mismatch for {map_sid}/{sid}: {nodes}")
                    all_nodes.extend(nodes if isinstance(nodes, list) else [])
            require(len(set(all_nodes)) == EXPECTED_WATER_TILE_OVERLAY_EMITTED_COUNT, f"water overlay identity nodes must be unique inside map {map_sid}")
    if source_plugin_dir is not None:
        source_manifest = source_plugin_dir / WATER_TILE_OVERLAY_IDENTITY_RELATIVE
        require(source_manifest.is_file(), f"missing source water overlay identity manifest: {source_manifest}")
        require(manifest_path.read_bytes() == source_manifest.read_bytes(), f"deployed water overlay identity manifest does not match source: {WATER_TILE_OVERLAY_IDENTITY_RELATIVE}")


def expected_water_biome_rows() -> dict[str, dict[str, object]]:
    return {}


def validate_water_biome(plugin_dir: Path, source_plugin_dir: Path | None = None) -> None:
    definition = read_json(plugin_dir / "homm3_runtime_assets" / "custom_biomes" / "custom_biomes.json")
    rows = definition.get("biomes") if isinstance(definition, dict) else None
    require(isinstance(rows, list), "custom_biomes.json must contain biomes list")
    retired_rows = [
        row
        for row in rows
        if isinstance(row, dict)
        and (row.get("id") in RETIRED_DISPLAY_WATER_BIOME_IDS or row.get("tileCode") in RETIRED_DISPLAY_WATER_TILE_CODES)
    ]
    require(not retired_rows, f"display water tile codes 24-28 must be absent from custom_biomes.json, got {retired_rows}")
    if source_plugin_dir is not None:
        source_manifest = source_plugin_dir / "homm3_runtime_assets" / "custom_biomes" / "custom_biomes.json"
        deployed_manifest = plugin_dir / "homm3_runtime_assets" / "custom_biomes" / "custom_biomes.json"
        require(deployed_manifest.read_bytes() == source_manifest.read_bytes(), "deployed custom_biomes.json does not match source")

def validate_source(plugin_dir: Path) -> None:
    plugin = read_text(plugin_dir / "Plugin.cs")
    terrain = read_text(plugin_dir / "Homm3SwampAutumnTintProof.cs")
    workbench = read_text(plugin_dir / "Homm3LiveProbeWorkbench.cs")
    require("Homm3HomecomingWaterOverlayRuntime.TryRegister" not in plugin,
            "Plugin.cs must not register the retired Homecoming water overlay runtime")
    require("Homm3HomecomingWaterTraversalBridge.RegisterRequiredReleaseSafeSlice" in plugin,
            "Plugin.cs must register Homm3HomecomingWaterTraversalBridge for native vanilla water traversal")
    require("Homm3HomecomingNativeWaterMeshBridge.RegisterRequiredReleaseSafeSlice" in plugin,
            "Plugin.cs must register Homm3HomecomingNativeWaterMeshBridge for native waterMap mesh rebuild")
    require("Homm3HomecomingWaterPresentationBridge.RegisterRequiredReleaseSafeSlice" in plugin,
            "Plugin.cs must register Homm3HomecomingWaterPresentationBridge for path-preview depth xray")
    require("Homm3CampaignWaterEmptyTerrainCursorBridge.RegisterRequiredReleaseSafeSlice" in plugin,
            "Plugin.cs must register Homm3CampaignWaterEmptyTerrainCursorBridge for empty-terrain ValidPath remap")
    require("Homm3CampaignWaterCursorColorBridge" not in plugin,
            "Plugin.cs must not register the retired CursorColor Prefix bridge")
    require("Homm3CampaignWaterBoatCursorOverlay" not in plugin,
            "Plugin.cs must not register the retired LateUpdate boat-cursor overlay")
    overlay = read_text(plugin_dir / "Homm3HomecomingWaterPresentationOverlay.cs")
    path_xray = read_text(plugin_dir / "Homm3HomecomingWaterPathPreviewXRay.cs")
    presentation_bridge = read_text(plugin_dir / "Homm3HomecomingWaterPresentationBridge.cs")
    empty_terrain = read_text(plugin_dir / "Homm3CampaignWaterEmptyTerrainCursorBridge.cs")
    campaign_registry = read_text(plugin_dir / "RoeCastleCampaignMapRegistry.cs")
    game_symbols = read_text(plugin_dir / "GameSymbols.cs")
    require("homecoming_map_context_helpers_only" in overlay,
            "water presentation overlay file must be map-context helpers only")
    require("Homm3HomecomingWaterPresentationOverlayHost" not in overlay,
            "retired passable-water cursor overlay host must not be registered")
    require("OnGUI" not in overlay,
            "retired passable-water cursor overlay must not draw via OnGUI")
    require("validPath" not in overlay,
            "retired passable-water cursor overlay must not reference validPath cursor texture")
    require("passable_water_cursor_overlay" not in overlay,
            "passable-water cursor overlay architecture must remain retired")
    require("campaign_water_empty_terrain_bgud_validpath" in empty_terrain,
            "campaign water cursor must use erq.bgud empty-terrain ValidPath architecture")
    require("PrefixBgud" in empty_terrain,
            "campaign water cursor must Harmony-prefix erq.bgud")
    # The mapper is named by GameSymbols (scoped per build) and verified by its own native body. 25509697
    # dropped the ValidPathRed branch, so the verification needs ValidPath/ValidPathGray/InvalidTarget only.
    require("NativeBodyHasEmptyTerrainECursorImmediates" in empty_terrain
            and "GameSymbols.HomecomingWaterPresentation.EmptyTerrainCursorMapperMethodHints" in empty_terrain,
            "campaign water cursor must name the mapper through GameSymbols and verify it by ECursor immediates")
    require("ECursor.ValidPath" in empty_terrain,
            "campaign water cursor must apply ECursor.ValidPath for StoryHub water")
    require("RoeCastleCampaignMapRegistry.IsStoryHubPlayableMap" in empty_terrain,
            "campaign water cursor must gate on StoryHub playable map SIDs")
    require("HomecomingBoatTravel.IsOceanCell(tile, water, level)" in empty_terrain
            and "MapDataLevelsMapMembers" in empty_terrain,
            "campaign water cursor must gate on the native ocean cell (seabed tile 2 + waterMap 2 at levelsMap -1)")
    require("IsWaterTerrainTileCode" not in empty_terrain and "IsRetiredGoldenEraWaterTileCode" not in empty_terrain,
            "campaign water cursor must not gate on retired Golden Era water tile ids 18-22")
    require("ContainsRuntimeWaterNode" not in empty_terrain,
            "campaign water cursor must not reuse Homecoming surface-node rectangles")
    require("FindHoverController" not in empty_terrain and "LateUpdate" not in empty_terrain,
            "campaign water cursor must not LateUpdate-poll hover controllers")
    require("Homm3CampaignWaterBoatCursorHost" not in empty_terrain,
            "retired boat-cursor LateUpdate host must not remain")
    require("PostfixHoverECursor" not in empty_terrain and "PrefixCursorColor" not in empty_terrain,
            "campaign water cursor must not use retired ECursor/CursorColor interactable-path hooks")
    require("PrefixApplyCursorTexture" not in empty_terrain and "TryApplyBoatTextureToNativeCursor" not in empty_terrain,
            "campaign water cursor must not use boat Texture2D swap for this milestone")
    require("EmptyTerrainCursorOwnerTypeHints" in game_symbols and "CursorStackApplyMethodHints" in game_symbols,
            "GameSymbols must resolve erq empty-terrain owner and cir cursor stack apply")
    require("OnGUI" not in empty_terrain and "Cursor.visible" not in empty_terrain,
            "campaign water cursor must not rely on Unity Cursor.visible/OnGUI against OE software cursors")
    require("StoryHubPlayableMapSids" in game_symbols,
            "GameSymbols must list Roe Castle StoryHub playable map SIDs")
    require("h3_roe_castle_homecoming_raw_translation" in game_symbols
            and "h3_roe_castle_tunnels_and_troglodytes_raw_translation" in game_symbols,
            "StoryHub playable map SID allowlist must include Homecoming and Tunnels missions")
    require("IsStoryHubPlayableMap" in campaign_registry,
            "RoeCastleCampaignMapRegistry must expose StoryHub playable map SID gate")
    require(not (plugin_dir / "Homm3CampaignWaterBoatCursorOverlay.cs").is_file(),
            "retired Homm3CampaignWaterBoatCursorOverlay.cs must be removed")
    require(not (plugin_dir / "Homm3CampaignWaterCursorColorBridge.cs").is_file(),
            "retired Homm3CampaignWaterCursorColorBridge.cs must be removed")
    require("path_preview_depth_xray_on_drawer_refresh" in path_xray,
            "path preview xray must use drawer-scoped depth override architecture")
    require("Hex/Misc/Path" in path_xray and "Hex/Particles" in path_xray,
            "path preview xray must swap submerged path segments from Hex/Misc/Path to Hex/Particles")
    require("GetComponentsInChildren<Renderer>" in path_xray,
            "path preview xray must scope renderer walks to the active BhPathDrawer subtree")
    require("Resources.FindObjectsOfTypeAll" not in path_xray,
            "path preview xray must not scan the whole scene for renderers")
    require("PatchPathDrawerRefresh" in presentation_bridge and "PatchPathDrawerClear" in presentation_bridge,
            "water presentation bridge must patch BhPathDrawer refresh and clear for path-preview xray")
    require("PathDrawerExcludedRefreshMethodHints" in game_symbols,
            "path drawer refresh symbols must exclude per-frame Update/LateUpdate hooks")
    require("HarmonyPatch" not in overlay or "harmony.Patch" not in overlay,
            "water presentation overlay must not rely on native path/cursor Harmony patches")
    require("Homm3HomecomingNativeWaterMeshBridge.TryScheduleForMap" in terrain,
            "terrain prepare-map must defer Homecoming waterMap mesh rebuild until after prepare-map")
    require("IdentifyWaterSetter" in read_text(plugin_dir / "Homm3HomecomingNativeWaterMeshBridge.cs"),
            "native water mesh bridge must verify Map water setter before painting")
    require("Homm3HomecomingWaterTileOverlayVisual.RegisterRequired(harmony, log)" not in terrain,
            "native vanilla water must not register the retired object-overlay water visual")
    require("AppendNativeWaterMaterialBiomes" not in terrain,
            "terrain renderer must not append HoMM3 terrain water material biomes for tile codes 18-22")
    require("EnsureNativeWaterTerrainLookupEntries" in terrain,
            "terrain renderer lookup must seed native water terrain tile codes 18-22")
    require("AppendNativeWaterTerrainBiomesFromCatalog" in terrain,
            "terrain renderer must append native Water catalog biomes for tile codes 18-22")
    require("NativeWaterTerrainDonorTileCode" in terrain,
            "terrain renderer must keep deep-water tile code 18 for native water biome naming")
    require("NativeWaterTerrainSeabedDonorTileCode" in terrain,
            "terrain renderer must capture native Sand seabed donor tile code 2 for water terrain under the waterMap mesh")
    require("TryCaptureSandSeabedDonorBiomeFromTerrain" in terrain,
            "terrain renderer must capture Sand seabed textures for water tile codes 18-22")
    require("TrySynthesizeNativeWaterDonorBiomeFromBundledTerrainTextures" not in terrain,
            "terrain renderer must not synthesize bundled HoMM3 water PNGs as the seabed under the waterMap mesh")
    require("water1.png" not in terrain,
            "terrain renderer must not load bundled water1.png as the native water seabed")
    require("NativeWaterTerrainBiomeNameByTileCode" in terrain,
            "terrain renderer must map water tile codes 18-22 to unique Core.zip biome names for RMG")
    require("RegisterGenerateMapBiomeNameSanitize" in terrain,
            "terrain registration must always patch blc.GenerateMap for pre-RMG biome-name sanitize")
    require("Water Shore North" in terrain and "Water Shore South" in terrain,
            "terrain renderer unique water shore biome names must include Water Shore North/South")
    require((plugin_dir.parents[1] / "tools" / "repair_core_rmg_tile_biome_uniqueness.py").is_file()
            or (Path(__file__).resolve().parents[1] / "tools" / "repair_core_rmg_tile_biome_uniqueness.py").is_file(),
            "repo must keep tools/repair_core_rmg_tile_biome_uniqueness.py for Core.zip RMG tile biome repair")
    require("definition.MaterialAliasOnly" in terrain and "definition.MaterialDonorTileCode" in terrain,
            "terrain renderer lookup must support alias-only material donor tile codes")
    require("Homm3TerrainWaterAnimator.RegisterRequired(log)" not in terrain,
            "terrain registration must not activate the retired packed-terrain water animator")
    require("RequiresTerrainWaterAnimationBinding" in terrain,
            "terrain renderer must keep an explicit inactive water-animation gate")
    requires_index = terrain.find("private static bool RequiresTerrainWaterAnimationBinding(string source)")
    disabled_index = terrain.find("return false;", requires_index)
    require(requires_index >= 0 and disabled_index > requires_index,
            "RequiresTerrainWaterAnimationBinding must fail closed as inactive for native waterMap mesh visuals")
    require("bws water-mesh" in terrain or "waterMap bytes" in terrain,
            "terrain renderer must breadcrumb native waterMap mesh architecture")
    require("_currentMapNativeWaterTerrainTileCodes" in terrain,
            "terrain renderer must track active native water terrain tile codes for seabed lookup")
    for token in [
        "homecoming_water_traversal_state",
        "homecoming_water_traversal_apply",
        "Homm3HomecomingWaterTraversalBridge.TryDescribeStateForBridge",
        "Homm3HomecomingWaterTraversalBridge.TryApplyForBridge",
    ]:
        require(token not in workbench, f"live bridge must not expose retired Homecoming direct-state water traversal command: {token}")
    require(not (plugin_dir / RETIRED_RUNTIME_RELATIVE).exists(),
            f"retired Homecoming water overlay runtime asset must not exist: {plugin_dir / RETIRED_RUNTIME_RELATIVE}")
    require(not (plugin_dir / WATER_TILE_OVERLAY_IDENTITY_RELATIVE).exists(),
            f"retired Homecoming water tile overlay identity manifest must not exist: {plugin_dir / WATER_TILE_OVERLAY_IDENTITY_RELATIVE}")
    validate_water_biome(plugin_dir)

def validate_generator(repo_root: Path) -> None:
    scenario = read_text(repo_root / "experiments/campaign_port_poc/h3m_scenario_translation.py")
    # The layered-atlas lane is retired. Pin the ocean-basin invariant on the shared
    # raw_translation emitters (surface_emit defines it, layer_atlas applies it per layer).
    surface_emit = read_text(repo_root / "experiments/campaign_port_poc/approach_cell/surface_emit.py")
    layer_atlas = read_text(repo_root / "experiments/campaign_port_poc/approach_cell/layer_atlas.py")
    require("NATIVE_OCEAN_BASIN_LEVEL = -1" in scenario, "scenario translation must define native ocean basin level -1")
    require("NATIVE_OCEAN_BASIN_PERIMETER_CLIMB = 1" in scenario, "scenario translation must define native ocean perimeter climb 1")
    require("apply_native_ocean_basin_geometry" in surface_emit, "surface_emit must apply native ocean basin geometry")
    require("nativeOceanBasinGeometry" in surface_emit, "surface_emit must emit nativeOceanBasinGeometry metadata")
    require("apply_native_ocean_basin_geometry" in layer_atlas, "layer_atlas must apply native ocean basin geometry on surface layer")
    # Campaign ocean is the native basin on Sand tile 2 + waterMap 2 (campaign_ocean.py). The
    # Golden Era-only Water tile ids 18-22 and waterMap 18 are retired from every emitter.
    ocean = read_text(repo_root / "experiments/campaign_port_poc/campaign_ocean.py")
    require("OCEAN_TILE_CODE = 2" in ocean and "OCEAN_WATER_MAP_ID = 2" in ocean and "OCEAN_BASIN_LEVEL = -1" in ocean,
            "campaign_ocean must define the native ocean as Sand tile 2 + waterMap 2 at basin level -1")
    require("import campaign_ocean as ocean" in surface_emit and "OCEAN_TILE_CODE = ocean.OCEAN_TILE_CODE" in surface_emit,
            "surface_emit must take its ocean ids from campaign_ocean")
    for retired in ("NATIVE_WATER_TILE_CODE", "VANILLA_WATER_TILE_CODE", "DISPLAY_WATER_TILE_CODE", "project_ocean_tile_code"):
        require(retired not in surface_emit, f"surface_emit must not keep retired ocean symbol {retired}")
    builder = read_text(repo_root / "experiments/campaign_port_poc/raw_translation/build_raw_translation_map.py")
    require("campaign_ocean.map_ocean_errors(" in builder,
            "raw_translation builder must audit the MapData ocean before writing the container")
    game_symbols = read_text(repo_root / "Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/GameSymbols.cs")
    require("internal const int OceanSeabedTileCode = 2;" in game_symbols and "internal const int OceanWaterMapId = 2;" in game_symbols
            and "internal const int OceanBasinLevel = -1;" in game_symbols,
            "GameSymbols must pin the ocean seabed tile 2, ocean waterMap 2 and basin level -1")
    require("IsOceanCell(int tileCode, int waterId, int level)" in game_symbols,
            "GameSymbols.IsOceanCell must take the level: a Sand river channel is tile 2 + waterMap 2 at land level")
    require("IsWaterTerrainTileCode" not in game_symbols,
            "GameSymbols must not keep the retired IsWaterTerrainTileCode ocean predicate")
    plugin_dir = repo_root / "Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod"
    for name in ("Homm3HomecomingWaterTraversalBridge.cs", "Homm3HomecomingNativeWaterMeshBridge.cs"):
        text = read_text(plugin_dir / name)
        require("HomecomingBoatTravel.IsOceanCell(" in text, f"{name} must identify ocean cells by IsOceanCell(tile, water)")
        require("IsRetiredGoldenEraWaterTileCode" not in text, f"{name} must not key ocean behaviour on retired tile ids 18-22")

def validate_deployed(plugin_dir: Path, source_plugin_dir: Path) -> None:
    validate_water_biome(plugin_dir, source_plugin_dir)
    require(not (plugin_dir / RETIRED_RUNTIME_RELATIVE).exists(),
            f"deployed retired Homecoming water overlay runtime asset must not exist: {plugin_dir / RETIRED_RUNTIME_RELATIVE}")
    identity = plugin_dir / WATER_TILE_OVERLAY_IDENTITY_RELATIVE
    source_identity = source_plugin_dir / WATER_TILE_OVERLAY_IDENTITY_RELATIVE
    require(not identity.exists(), f"deployed retired Homecoming water tile overlay identity manifest must not exist: {identity}")
    require(not source_identity.exists(), f"source retired Homecoming water tile overlay identity manifest must not exist: {source_identity}")
    plan = plugin_dir / WATER_TRAVERSAL_PLAN_RELATIVE
    source_plan = source_plugin_dir / WATER_TRAVERSAL_PLAN_RELATIVE
    require(not plan.exists(), f"deployed retired Homecoming direct-state traversal plan must not exist: {plan}")
    require(not source_plan.exists(), f"source retired Homecoming direct-state traversal plan must not exist: {source_plan}")
    for flag_name in [
        "homm3_homecoming_playable_shell_launch.flag",
        "homm3_homecoming_quickstart_state_probe.flag",
        "homm3_homecoming_boat_travel_native_proof.flag",
    ]:
        require(not (plugin_dir / flag_name).exists(),
                f"deployed retired Homecoming runtime flag must not exist: {plugin_dir / flag_name}")
    require(not (plugin_dir / "Homm3CampaignWaterBoatCursorOverlay.cs").is_file(),
            "deployed retired boat-cursor overlay source must not exist")
    require(not (plugin_dir / "Homm3CampaignWaterCursorColorBridge.cs").is_file(),
            "deployed retired CursorColor bridge source must not exist")

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--plugin-dir", type=Path)
    parser.add_argument("--source-plugin-dir", type=Path)
    args = parser.parse_args()
    repo_root = args.repo_root.resolve()
    plugin_dir = (args.plugin_dir or (repo_root / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod")).resolve()
    source_plugin_dir = args.source_plugin_dir.resolve() if args.source_plugin_dir else None
    validate_source(plugin_dir if source_plugin_dir is None else source_plugin_dir)
    validate_generator(repo_root)
    if source_plugin_dir is not None:
        validate_deployed(plugin_dir, source_plugin_dir)
    print("Homecoming native vanilla water runtime contract OK")


if __name__ == "__main__":
    main()
