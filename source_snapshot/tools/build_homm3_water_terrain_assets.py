#!/usr/bin/env python3
"""Generate the HoMM3 water terrain runtime textures from VCMI H3sprite.lod."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
H3SPRITE_LOD = ROOT / "vcmi" / "Data" / "H3sprite.lod"
LOD_EXTRACT = ROOT / "tools" / "lod_extract_entry_py3.py"
DEF_EXTRACT = ROOT / "tools" / "defextract_py3.py"
WORK_ROOT = ROOT / "artifacts" / "campaign_port_poc" / "homecoming_poc" / "water_terrain_work"
OUT_ROOT = (
    ROOT
    / "Heroes of Might & Magic Olden Era Playtest"
    / "OfflineUnlockMod"
    / "homm3_runtime_assets"
    / "custom_biomes"
    / "water"
)
ANIMATION_ROOT = OUT_ROOT.parent / "water_animation"

DEF_NAME = "Watrtl.def"
TEXTURE_NAMES = ("water1.png", "water2.png", "water3.png")
SHORELINE_EDGES = ("north", "south", "west", "east")
SHORELINE_TEXTURE_NAMES = {
    edge: tuple(f"water_shore_{edge}_{index}.png" for index in range(1, 4))
    for edge in SHORELINE_EDGES
}
TILE_SIZE = 32
SOURCE_TILE_GRID = 1
OUTPUT_SIZE = 512
TEXTURE_SCALE_POLICY = "one_homm3_tile_scaled_to_one_olden_tile_texture"
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
MIN_BLUE_OCEAN_FRAME_COUNT = 6
MIN_SHORELINE_SOURCE_FRAME_COUNT = 4
MAX_SHORELINE_SAND_RATIO = 0.08
MIN_WATER_LIKE_RATIO = 0.55
MAX_SOURCE_ROCK_LIKE_RATIO = 0.0
OUTPUT_BLUE_MIN_RED_MARGIN = 40
OUTPUT_BLUE_MIN_GREEN_MARGIN = 40
MIN_SHORELINE_EDGE_SAND_RATIO = 0.55
MAX_SHORELINE_OPPOSITE_EDGE_SAND_RATIO = 0.08
SHORELINE_BAND_RATIO = 0.25
ANIMATION_SCHEMA = "homm3.homecoming_terrain_water_animation.v1"
ANIMATION_MANIFEST_NAME = "water_animation_manifest.json"
ANIMATION_FRAME_COUNT = 33
ANIMATION_FRAMES_PER_SECOND = 8.0
ANIMATION_SOURCE_SEQUENCE_POLICY = "cycle_selected_homm3_water_and_shore_source_frames_to_33_step_native_terrain_loop"
ANIMATION_TILE_CODES = {
    "deep_ocean": 18,
    "shoreline_north": 19,
    "shoreline_south": 20,
    "shoreline_west": 21,
    "shoreline_east": 22,
}


def run(args: list[str]) -> None:
    subprocess.run(args, check=True)


def load_frames(frame_dir: Path) -> list[Path]:
    frames = sorted(frame_dir.glob("*.png"))
    if len(frames) != 33:
        raise RuntimeError(f"expected 33 water terrain frames from {DEF_NAME}, got {len(frames)}")
    return frames


def iter_image_pixels(image: Image.Image):
    getter = getattr(image, "get_flattened_data", None)
    if getter is not None:
        return getter()
    return image.getdata()

def clamp(value: float) -> int:
    return max(0, min(255, round(value)))


def is_rock_like_pixel(r: int, g: int, b: int) -> bool:
    saturation = max(r, g, b) - min(r, g, b)
    gray_rock = saturation <= 30 and max(r, g, b) <= 160 and min(r, g, b) >= 24
    brown_rock = r >= g + 8 and r >= b + 12 and 55 <= r <= 170 and 40 <= g <= 145 and b <= 125
    return gray_rock or brown_rock


def is_sand_like_pixel(r: int, g: int, b: int, a: int) -> bool:
    return a > 0 and r > b + 18 and g > b - 4 and r > 82 and g > 68


def is_water_like_pixel(r: int, g: int, b: int, a: int) -> bool:
    return a > 0 and b >= r + 8 and b >= g - 8


def analyze_frame(path: Path) -> dict[str, object]:
    image = Image.open(path).convert("RGBA")
    opaque = [pixel for pixel in iter_image_pixels(image) if pixel[3] > 0]
    if not opaque:
        return {
            "path": path,
            "opaquePixelCount": 0,
            "sandLikeRatio": 1.0,
            "waterLikeRatio": 0.0,
            "rockLikeRatio": 1.0,
        }
    sand_like = 0
    water_like = 0
    rock_like = 0
    for r, g, b, a in opaque:
        if is_sand_like_pixel(r, g, b, a):
            sand_like += 1
        if is_water_like_pixel(r, g, b, a):
            water_like += 1
        if is_rock_like_pixel(r, g, b):
            rock_like += 1
    opaque_count = len(opaque)
    return {
        "path": path,
        "opaquePixelCount": opaque_count,
        "sandLikeRatio": sand_like / opaque_count,
        "waterLikeRatio": water_like / opaque_count,
        "rockLikeRatio": rock_like / opaque_count,
    }


def is_clean_ocean_frame(stats: dict[str, object]) -> bool:
    return (
        float(stats["sandLikeRatio"]) <= MAX_SHORELINE_SAND_RATIO
        and float(stats["waterLikeRatio"]) >= MIN_WATER_LIKE_RATIO
    )


def select_blue_ocean_frames(frames: list[Path]) -> tuple[list[dict[str, object]], list[dict[str, object]], list[dict[str, object]]]:
    frame_stats = [analyze_frame(frame) for frame in frames]
    clean = [stats for stats in frame_stats if is_clean_ocean_frame(stats)]
    if len(clean) < 6:
        raise RuntimeError(
            f"expected at least 6 clean ocean frames from {DEF_NAME}, got {len(clean)}; "
            "refusing to generate water textures with baked shoreline pixels"
        )
    blue_ocean = [stats for stats in clean if float(stats["rockLikeRatio"]) <= MAX_SOURCE_ROCK_LIKE_RATIO]
    if len(blue_ocean) < MIN_BLUE_OCEAN_FRAME_COUNT:
        raise RuntimeError(
            f"expected at least {MIN_BLUE_OCEAN_FRAME_COUNT} blue-ocean-only frames from {DEF_NAME}, got {len(blue_ocean)}; "
            "refusing to generate water textures with rock-colored source pixels"
        )
    rejected_rock = [stats for stats in clean if stats not in blue_ocean]
    return clean, blue_ocean, rejected_rock


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
    water_like = 0
    for y in y_range:
        for x in x_range:
            r, g, b, a = image.getpixel((x, y))
            if a == 0:
                continue
            opaque += 1
            if is_sand_like_pixel(r, g, b, a):
                sand_like += 1
            if is_water_like_pixel(r, g, b, a):
                water_like += 1
    return {
        "edge": edge,
        "opaquePixelCount": opaque,
        "sandLikePixelCount": sand_like,
        "sandLikePixelRatio": 0.0 if opaque == 0 else sand_like / opaque,
        "waterLikePixelCount": water_like,
        "waterLikePixelRatio": 0.0 if opaque == 0 else water_like / opaque,
    }


def transform_shoreline_frame(image: Image.Image, transform: str) -> Image.Image:
    if transform == "none":
        return image
    if transform == "flip_x":
        return image.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
    if transform == "flip_y":
        return image.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
    raise ValueError(f"unknown shoreline source transform: {transform}")


def select_shoreline_frames(frames: list[Path], edge: str) -> list[dict[str, object]]:
    by_name = {path.name: path for path in frames}
    expected_names = SHORELINE_SOURCE_FRAMES_BY_EDGE[edge]
    missing = [name for name in expected_names if name not in by_name]
    if missing:
        raise RuntimeError(f"missing HoMM3 shoreline source frame(s) for {edge}: {missing}")
    transform = SHORELINE_SOURCE_TRANSFORM_BY_EDGE[edge]
    selected: list[dict[str, object]] = []
    for name in expected_names:
        path = by_name[name]
        image = transform_shoreline_frame(Image.open(path).convert("RGBA"), transform)
        edge_audit = analyze_edge_band(image, edge)
        opposite_audit = analyze_edge_band(image, opposite_edge(edge))
        if edge_audit["sandLikePixelRatio"] < MIN_SHORELINE_EDGE_SAND_RATIO:
            raise RuntimeError(f"HoMM3 shoreline source frame {name} lacks sandy {edge} edge after {transform}: {edge_audit}")
        if opposite_audit["sandLikePixelRatio"] > MAX_SHORELINE_OPPOSITE_EDGE_SAND_RATIO:
            raise RuntimeError(f"HoMM3 shoreline source frame {name} has sandy opposite edge after {transform}: {opposite_audit}")
        selected.append(
            {
                "name": name,
                "path": path,
                "transform": transform,
                "edgeAudit": edge_audit,
                "oppositeEdgeAudit": opposite_audit,
            }
        )
    if len(selected) < MIN_SHORELINE_SOURCE_FRAME_COUNT:
        raise RuntimeError(f"expected at least {MIN_SHORELINE_SOURCE_FRAME_COUNT} shoreline source frames for {edge}, got {len(selected)}")
    return selected


def normalize_pixel_to_blue_ocean(r: int, g: int, b: int, a: int) -> tuple[int, int, int, int]:
    if a == 0:
        return r, g, b, a
    luminance = ((r * 0.2126) + (g * 0.7152) + (b * 0.0722)) / 255.0
    value = (max(r, g, b) / 255.0 * 0.55) + (luminance * 0.45)
    return (
        clamp(10 + value * 50),
        clamp(69 + value * 115),
        clamp(128 + value * 108),
        a,
    )


def normalize_image_to_blue_ocean(image: Image.Image) -> tuple[Image.Image, int]:
    pixels = image.load()
    width, height = image.size
    changed = 0
    for y in range(height):
        for x in range(width):
            old = pixels[x, y]
            new = normalize_pixel_to_blue_ocean(*old)
            if new != old:
                pixels[x, y] = new
                changed += 1
    return image, changed


def audit_shoreline_output(image: Image.Image, edge: str) -> dict[str, object]:
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


def audit_blue_ocean_output(image: Image.Image) -> dict[str, object]:
    opaque = 0
    non_blue = 0
    for r, g, b, a in iter_image_pixels(image):
        if a == 0:
            continue
        opaque += 1
        if b < r + OUTPUT_BLUE_MIN_RED_MARGIN or b < g + OUTPUT_BLUE_MIN_GREEN_MARGIN:
            non_blue += 1
    return {
        "opaquePixelCount": opaque,
        "nonBluePixelCount": non_blue,
        "nonBluePixelRatio": 0.0 if opaque == 0 else non_blue / opaque,
        "blueDominanceRule": {
            "minRedMargin": OUTPUT_BLUE_MIN_RED_MARGIN,
            "minGreenMargin": OUTPUT_BLUE_MIN_GREEN_MARGIN,
        },
    }


def rounded_frame_stats(stats: dict[str, object]) -> dict[str, object]:
    path = stats["path"]
    return {
        "name": path.name if isinstance(path, Path) else str(path),
        "sandLikeRatio": round(float(stats["sandLikeRatio"]), 6),
        "waterLikeRatio": round(float(stats["waterLikeRatio"]), 6),
        "rockLikeRatio": round(float(stats["rockLikeRatio"]), 6),
    }


def build_sheet(frames: list[Path], variant_index: int) -> tuple[Image.Image, int, dict[str, object], str]:
    frame_path = frames[variant_index % len(frames)]
    frame = Image.open(frame_path).convert("RGBA")
    frame, changed_pixels = normalize_image_to_blue_ocean(frame)
    image = frame.resize((OUTPUT_SIZE, OUTPUT_SIZE), Image.Resampling.NEAREST)
    return image, changed_pixels, audit_blue_ocean_output(image), frame_path.name



def build_shoreline_sheet(
    selected_frames: list[dict[str, object]], variant_index: int, edge: str
) -> tuple[Image.Image, dict[str, object], dict[str, object]]:
    selected = selected_frames[variant_index % len(selected_frames)]
    frame = Image.open(selected["path"]).convert("RGBA")
    frame = transform_shoreline_frame(frame, str(selected["transform"]))
    image = frame.resize((OUTPUT_SIZE, OUTPUT_SIZE), Image.Resampling.NEAREST)
    return image, audit_shoreline_output(image, edge), selected


def animation_frame_name(kind: str, index: int) -> str:
    return f"{kind}/{kind}_{index:02d}.png"


def build_animation_manifest(
    frames: list[Path],
    blue_ocean_frames: list[Path],
    shoreline_frames_by_edge: dict[str, list[dict[str, object]]],
) -> dict[str, object]:
    if ANIMATION_ROOT.exists():
        shutil.rmtree(ANIMATION_ROOT)
    ANIMATION_ROOT.mkdir(parents=True)
    sequences: dict[str, dict[str, object]] = {}

    deep_files: list[str] = []
    for index in range(ANIMATION_FRAME_COUNT):
        frame_path = blue_ocean_frames[index % len(blue_ocean_frames)]
        frame = Image.open(frame_path).convert("RGBA")
        frame, changed_pixels = normalize_image_to_blue_ocean(frame)
        image = frame.resize((OUTPUT_SIZE, OUTPUT_SIZE), Image.Resampling.NEAREST)
        audit = audit_blue_ocean_output(image)
        if audit["nonBluePixelCount"] != 0:
            raise RuntimeError(f"deep-water animation frame failed blue audit index={index}: {audit}")
        rel = animation_frame_name("deep_ocean", index)
        out_path = ANIMATION_ROOT / rel
        out_path.parent.mkdir(parents=True, exist_ok=True)
        image.save(out_path)
        deep_files.append(rel)
    sequences[str(ANIMATION_TILE_CODES["deep_ocean"])] = {
        "kind": "deep_ocean",
        "tileCode": ANIMATION_TILE_CODES["deep_ocean"],
        "files": deep_files,
        "sourceFrames": [path.name for path in blue_ocean_frames],
        "colorPolicy": BLUE_OCEAN_COLOR_POLICY,
        "sourceFramePolicy": "cycle_selected_blue_ocean_frames",
    }

    for edge in SHORELINE_EDGES:
        kind = f"shoreline_{edge}"
        selected_frames = shoreline_frames_by_edge[edge]
        files: list[str] = []
        for index in range(ANIMATION_FRAME_COUNT):
            image, output_audit, output_source_frame = build_shoreline_sheet(selected_frames, index, edge)
            if output_audit["tileEdgeSandLikePixelRatio"] < MIN_SHORELINE_EDGE_SAND_RATIO:
                raise RuntimeError(f"shoreline animation sandy edge audit failed for {edge} index={index}: {output_audit}")
            if output_audit["tileOppositeEdgeSandLikePixelRatio"] > MAX_SHORELINE_OPPOSITE_EDGE_SAND_RATIO:
                raise RuntimeError(f"shoreline animation opposite-edge audit failed for {edge} index={index}: {output_audit}")
            rel = animation_frame_name(kind, index)
            out_path = ANIMATION_ROOT / rel
            out_path.parent.mkdir(parents=True, exist_ok=True)
            image.save(out_path)
            files.append(rel)
        sequences[str(ANIMATION_TILE_CODES[kind])] = {
            "kind": kind,
            "edge": edge,
            "tileCode": ANIMATION_TILE_CODES[kind],
            "files": files,
            "sourceFrames": [str(frame["name"]) for frame in selected_frames],
            "sourceTransform": SHORELINE_SOURCE_TRANSFORM_BY_EDGE[edge],
            "colorPolicy": SHORELINE_COLOR_POLICY,
            "sourceFramePolicy": "cycle_selected_shoreline_edge_frames",
        }

    manifest = {
        "schema": ANIMATION_SCHEMA,
        "renderer": "Homm3TerrainWaterAnimator",
        "nativeBinding": "terrain_renderer_packed_color_layers_texture_node_upload",
        "sourceLod": str(H3SPRITE_LOD),
        "sourceDef": DEF_NAME,
        "sourceFrameCount": len(frames),
        "frameCount": ANIMATION_FRAME_COUNT,
        "framesPerSecond": ANIMATION_FRAMES_PER_SECOND,
        "sourceSequencePolicy": ANIMATION_SOURCE_SEQUENCE_POLICY,
        "textureScalePolicy": TEXTURE_SCALE_POLICY,
        "sourceTileSize": TILE_SIZE,
        "sourceTilesPerOutputTexture": SOURCE_TILE_GRID,
        "outputTextureSize": OUTPUT_SIZE,
        "tileCodeSequences": sequences,
    }
    (ANIMATION_ROOT / ANIMATION_MANIFEST_NAME).write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest



def main() -> int:
    for path in (H3SPRITE_LOD, LOD_EXTRACT, DEF_EXTRACT):
        if not path.is_file():
            raise FileNotFoundError(path)

    if WORK_ROOT.exists():
        shutil.rmtree(WORK_ROOT)
    WORK_ROOT.mkdir(parents=True)

    def_path = WORK_ROOT / "defs" / DEF_NAME.lower()
    run([sys.executable, str(LOD_EXTRACT), str(H3SPRITE_LOD), DEF_NAME, str(def_path)])
    run([sys.executable, str(DEF_EXTRACT), str(def_path), str(WORK_ROOT)])

    frames = load_frames(WORK_ROOT / "watrtl.dir")
    clean_frame_stats, blue_ocean_frame_stats, rejected_rock_stats = select_blue_ocean_frames(frames)
    blue_ocean_frames = [stats["path"] for stats in blue_ocean_frame_stats if isinstance(stats["path"], Path)]
    shoreline_frames_by_edge = {edge: select_shoreline_frames(frames, edge) for edge in SHORELINE_EDGES}
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    shoreline_roots = {edge: OUT_ROOT.parent / f"water_shore_{edge}" for edge in SHORELINE_EDGES}
    for stale_name in ("water1.png", "water2.png", "water3.png", "shore_sand.png"):
        stale_path = OUT_ROOT / stale_name
        if stale_path.exists():
            stale_path.unlink()
    for edge, root in shoreline_roots.items():
        root.mkdir(parents=True, exist_ok=True)
        for stale_path in root.glob("water_shore_*.png"):
            stale_path.unlink()
    animation_manifest = build_animation_manifest(frames, blue_ocean_frames, shoreline_frames_by_edge)

    report_entries = []
    for index, texture_name in enumerate(TEXTURE_NAMES):
        out_path = OUT_ROOT / texture_name
        image, changed_pixels, output_audit, source_texture_frame = build_sheet(blue_ocean_frames, index)
        if output_audit["nonBluePixelCount"] != 0:
            raise RuntimeError(f"blue ocean normalization failed for {texture_name}: {output_audit}")
        variant = f"blue_ocean_no_rocks_mix_{index + 1}"
        image.save(out_path)
        report_entries.append(
            {
                "sourceLod": str(H3SPRITE_LOD),
                "sourceDef": DEF_NAME,
                "output": str(out_path),
                "policy": BLUE_OCEAN_POLICY,
                "kind": "deep_ocean",
                "variant": variant,
                "colorPolicy": BLUE_OCEAN_COLOR_POLICY,
                "textureScalePolicy": TEXTURE_SCALE_POLICY,
                "sourceTileSize": TILE_SIZE,
                "sourceTilesPerOutputTexture": SOURCE_TILE_GRID,
                "outputTextureSize": OUTPUT_SIZE,
                "sourceTextureFrame": source_texture_frame,
                "sourceFrameCount": len(frames),
                "cleanOceanFrameCount": len(clean_frame_stats),
                "cleanOceanFrames": [rounded_frame_stats(stats)["name"] for stats in clean_frame_stats],
                "blueOceanFrameCount": len(blue_ocean_frame_stats),
                "blueOceanFrames": [rounded_frame_stats(stats)["name"] for stats in blue_ocean_frame_stats],
                "selectedFrameMetrics": [rounded_frame_stats(stats) for stats in blue_ocean_frame_stats],
                "rejectedCleanOceanRockFrames": [rounded_frame_stats(stats) for stats in rejected_rock_stats],
                "maxAllowedSourceRockLikeRatio": MAX_SOURCE_ROCK_LIKE_RATIO,
                "maxSelectedSourceRockLikeRatio": max(round(float(stats["rockLikeRatio"]), 6) for stats in blue_ocean_frame_stats),
                "normalizedSourcePixels": changed_pixels,
                "outputBlueOceanAudit": output_audit,
                "size": list(image.size),
            }
        )

    for edge in SHORELINE_EDGES:
        for index, texture_name in enumerate(SHORELINE_TEXTURE_NAMES[edge]):
            out_path = shoreline_roots[edge] / texture_name
            selected_frames = shoreline_frames_by_edge[edge]
            image, output_audit, output_source_frame = build_shoreline_sheet(selected_frames, index, edge)
            if output_audit["tileEdgeSandLikePixelRatio"] < MIN_SHORELINE_EDGE_SAND_RATIO:
                raise RuntimeError(f"shoreline sandy edge audit failed for {texture_name}: {output_audit}")
            if output_audit["tileOppositeEdgeSandLikePixelRatio"] > MAX_SHORELINE_OPPOSITE_EDGE_SAND_RATIO:
                raise RuntimeError(f"shoreline opposite-edge audit failed for {texture_name}: {output_audit}")
            variant = f"shoreline_{edge}_mix_{index + 1}"
            image.save(out_path)
            report_entries.append(
                {
                    "sourceLod": str(H3SPRITE_LOD),
                    "sourceDef": DEF_NAME,
                    "output": str(out_path),
                    "policy": SHORELINE_POLICY,
                    "kind": "shoreline_edge",
                    "edge": edge,
                    "variant": variant,
                    "colorPolicy": SHORELINE_COLOR_POLICY,
                    "textureScalePolicy": TEXTURE_SCALE_POLICY,
                    "sourceTileSize": TILE_SIZE,
                    "sourceTilesPerOutputTexture": SOURCE_TILE_GRID,
                    "outputTextureSize": OUTPUT_SIZE,
                    "outputSourceFrame": str(output_source_frame["name"]),
                    "sourceFrameCount": len(frames),
                    "shorelineSourceFrameCount": len(selected_frames),
                    "shorelineSourceFrames": [str(frame["name"]) for frame in selected_frames],
                    "sourceTransform": SHORELINE_SOURCE_TRANSFORM_BY_EDGE[edge],
                    "minShorelineEdgeSandLikePixelRatio": MIN_SHORELINE_EDGE_SAND_RATIO,
                    "maxShorelineOppositeEdgeSandLikePixelRatio": MAX_SHORELINE_OPPOSITE_EDGE_SAND_RATIO,
                    "sourceFrameMetrics": [
                        {
                            "name": str(frame["name"]),
                            "transform": str(frame["transform"]),
                            "edgeAudit": frame["edgeAudit"],
                            "oppositeEdgeAudit": frame["oppositeEdgeAudit"],
                        }
                        for frame in selected_frames
                    ],
                    "outputShorelineAudit": output_audit,
                    "size": list(image.size),
                }
            )

    report_path = OUT_ROOT / "water_terrain_report.json"
    report_path.write_text(json.dumps(report_entries, indent=2), encoding="utf-8")
    print(
        f"Generated {len(TEXTURE_NAMES)} single-tile HoMM3 deep-water textures "
        f"and {sum(len(names) for names in SHORELINE_TEXTURE_NAMES.values())} single-tile shoreline textures, "
        f"plus {ANIMATION_FRAME_COUNT} native terrain animation frames for {len(animation_manifest['tileCodeSequences'])} water tile codes -> {OUT_ROOT.parent}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
