#!/usr/bin/env python3
"""Render loopable 1080p town-scene animations from HoMM3 town reference layers.

Breadcrumb: this is an offline compositor for preview/export media only. It does
not validate in-game Unity animation timing or UI masking; verify generated loops
visually before treating them as final promotional captures.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import imageio_ffmpeg
from PIL import Image, ImageDraw, ImageFilter, ImageFont


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE_ROOT = (
    REPO_ROOT
    / "Heroes of Might & Magic Olden Era Playtest"
    / "OfflineUnlockMod"
    / "homm3_runtime_assets"
    / "town_scene_refs"
)
DEFAULT_OUTPUT_ROOT = REPO_ROOT / "artifacts" / "homm3_town_loops"
HOMM3_FACTIONS = [
    "homm3_castle",
    "homm3_rampart",
    "homm3_tower",
    "homm3_inferno",
    "homm3_necropolis",
    "homm3_dungeon",
    "homm3_stronghold",
    "homm3_fortress",
    "homm3_conflux",
    "homm3_cove",
]
OUTPUT_SIZE = (1920, 1080)
DEFAULT_FRAME_MS = 100
FULL_WIDTH_FIT_FACTIONS = {"homm3_rampart"}
EXCLUDED_PREVIEW_STRUCTURES = {"grail"}
DEFAULT_SECONDS = 6.0
DEFAULT_FORMAT = "mp4"


@dataclass(frozen=True)
class Layer:
    layer_id: str
    structure: str
    sprite: str
    x: int
    y: int
    z: int
    order: int
    hidden: bool


@dataclass(frozen=True)
class Anim:
    frame_rate_ms: int
    frames: tuple[str, ...]


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def find_background(faction_dir: Path) -> Path:
    backgrounds = sorted(faction_dir.glob("*-in-background.png"))
    if not backgrounds:
        backgrounds = sorted(p for p in faction_dir.glob("*.png") if "background" in p.name.lower())
    if len(backgrounds) != 1:
        names = ", ".join(p.name for p in backgrounds) or "none"
        raise RuntimeError(f"{faction_dir.name}: expected one background PNG, found {names}")
    return backgrounds[0]


def load_layers(faction_dir: Path) -> tuple[tuple[Layer, ...], int, int]:
    doc = load_json(faction_dir / "layers" / "positions.json")
    layers = []
    for raw in doc["layers"]:
        layers.append(
            Layer(
                layer_id=str(raw["id"]),
                structure=str(raw.get("structure") or ""),
                sprite=str(raw.get("sprite") or f"{raw['id']}.png"),
                x=int(raw["x"]),
                y=int(raw["y"]),
                z=int(raw.get("z", 0)),
                order=int(raw.get("order", 0)),
                hidden=bool(raw.get("hidden", False)),
            )
        )
    # Match runtime: render only layers with explicit placement rows.


    if "canvas_w" in doc and "canvas_h" in doc:
        return tuple(layers), int(doc["canvas_w"]), int(doc["canvas_h"])
    with Image.open(find_background(faction_dir)) as background:
        return tuple(layers), int(background.width), int(background.height)


def load_anims(faction_dir: Path) -> dict[str, Anim]:
    path = faction_dir / "layers" / "anims" / "metadata.json"
    if not path.is_file():
        return {}
    result: dict[str, Anim] = {}
    for raw in load_json(path):
        frames = tuple(str(frame) for frame in raw.get("frames") or ())
        if frames:
            result[str(raw["id"])] = Anim(int(raw.get("frameRateMs", DEFAULT_FRAME_MS)), frames)
    return result



def vcmi_structure_group_and_rank(structure: str) -> tuple[str, int] | None:
    """Mirror VCMI town-screen grouping for fully-built preview selection.

    VCMI groups built structures by CBuilding::getBase() and draws only the
    farthest built upgrade in each group. The exported layer metadata carries
    VCMI structure identifiers, so keep this as an explicit structure map
    instead of deriving visual state from Olden Era Build_* mappings.
    """

    if structure in ("fort", "citadel", "castle"):
        return "fort", {"fort": 0, "citadel": 1, "castle": 2}[structure]
    if structure in ("villageHall", "townHall", "cityHall", "capitol"):
        return "villageHall", {"villageHall": 0, "townHall": 1, "cityHall": 2, "capitol": 3}[structure]
    if structure.startswith("mageGuild"):
        suffix = structure.removeprefix("mageGuild")
        if suffix.isdigit():
            return "mageGuild1", int(suffix) - 1

    dwelling_match = re.fullmatch(r"dwelling(Up2|Up)?Lvl([1-7])", structure)
    if dwelling_match:
        tier = dwelling_match.group(2)
        upgrade = dwelling_match.group(1)
        rank = {"": 0, "Up": 1, "Up2": 2}[upgrade or ""]
        return f"dwellingLvl{tier}", rank

    horde_match = re.fullmatch(r"horde([12])(Upgr)?", structure)
    if horde_match:
        # HoMM3 horde structures upgrade the level-1 dwelling chain.
        rank = {"1": 1, "2": 3}[horde_match.group(1)]
        if horde_match.group(2):
            rank += 1
        return "dwellingLvl1", rank

    if structure in ("shipyard", "ship"):
        return "shipyard", {"shipyard": 0, "ship": 1}[structure]

    return None


def fully_upgraded_layer_ids(faction_dir: Path, layers: tuple[Layer, ...]) -> set[str]:
    """Select structures the way VCMI's fully-built town screen does."""

    selected: set[str] = set()
    grouped: dict[str, tuple[int, int, Layer]] = {}
    for layer in layers:
        if layer.structure in EXCLUDED_PREVIEW_STRUCTURES:
            continue
        grouping = vcmi_structure_group_and_rank(layer.structure)
        if grouping is None:
            selected.add(layer.layer_id)
            continue
        group, rank = grouping
        previous = grouped.get(group)
        candidate = (rank, layer.order, layer)
        if previous is None or candidate[:2] > previous[:2]:
            grouped[group] = candidate

    selected.update(layer.layer_id for _rank, _order, layer in grouped.values())
    return selected


def fit_center_crop(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    target_w, target_h = size
    scale = max(target_w / image.width, target_h / image.height)
    scaled = image.resize((math.ceil(image.width * scale), math.ceil(image.height * scale)), Image.Resampling.LANCZOS)
    left = (scaled.width - target_w) // 2
    top = (scaled.height - target_h) // 2
    return scaled.crop((left, top, left + target_w, top + target_h))


def fit_full_width_on_cover(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    target_w, target_h = size
    cover = fit_center_crop(image, size).filter(ImageFilter.GaussianBlur(16))
    scale = target_w / image.width
    foreground_h = round(image.height * scale)
    foreground = image.resize((target_w, foreground_h), Image.Resampling.LANCZOS)
    top = (target_h - foreground_h) // 2
    cover.paste(foreground, (0, top))
    return cover


def fit_output_frame(image: Image.Image, faction: str) -> Image.Image:
    if faction in FULL_WIDTH_FIT_FACTIONS:
        return fit_full_width_on_cover(image, OUTPUT_SIZE)
    return fit_center_crop(image, OUTPUT_SIZE)


def paste_native_layer(canvas: Image.Image, layer_image: Image.Image, layer: Layer) -> None:
    canvas.alpha_composite(layer_image, (layer.x, layer.y))


def paste_native_layer_frame(
    canvas: Image.Image,
    faction_dir: Path,
    layer: Layer,
    anims: dict[str, Anim],
    frame_index: int,
) -> None:
    base = Image.open(faction_dir / "layers" / layer.sprite).convert("RGBA")
    paste_native_layer(canvas, base, layer)

    anim = anims.get(layer.layer_id)
    if anim:
        frame_name = anim.frames[frame_index % len(anim.frames)]
        frame = Image.open(faction_dir / "layers" / "anims" / layer.layer_id / frame_name).convert("RGBA")
        paste_native_layer(canvas, frame, layer)


def render_native_vcmi_frame(
    faction_dir: Path,
    layers: tuple[Layer, ...],
    selected_ids: set[str],
    anims: dict[str, Anim],
    frame_index: int,
) -> Image.Image:
    background = Image.open(find_background(faction_dir)).convert("RGBA")
    if background.size != (800, 374):
        raise RuntimeError(f"{faction_dir.name}: expected VCMI town background 800x374, got {background.size}")
    canvas = background.copy()
    rendered_ids: set[str] = set()
    for layer in sorted((layer for layer in layers if layer.layer_id in selected_ids), key=lambda item: (item.z, item.order)):
        if layer.layer_id in rendered_ids:
            continue
        rendered_ids.add(layer.layer_id)
        paste_native_layer_frame(canvas, faction_dir, layer, anims, frame_index)
    return canvas

def remove_if_exists(path: Path) -> None:
    if path.exists():
        path.unlink()


def save_mp4(frames: list[Image.Image], output_path: Path, fps: int) -> None:
    remove_if_exists(output_path)
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    cmd = [
        ffmpeg,
        "-y",
        "-f",
        "rawvideo",
        "-vcodec",
        "rawvideo",
        "-pix_fmt",
        "rgb24",
        "-s",
        f"{frames[0].width}x{frames[0].height}",
        "-r",
        str(fps),
        "-i",
        "-",
        "-an",
        "-vcodec",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        "-crf",
        "18",
        str(output_path),
    ]
    with subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE) as proc:
        assert proc.stdin is not None
        for frame in frames:
            proc.stdin.write(frame.tobytes())
        proc.stdin.close()
        stderr = proc.stderr.read().decode("utf-8", errors="replace") if proc.stderr else ""
        code = proc.wait()
    if code != 0:
        raise RuntimeError(f"ffmpeg failed for {output_path}: {stderr[-2000:]}")


def save_webp(frames: list[Image.Image], output_path: Path) -> None:
    remove_if_exists(output_path)
    frames[0].save(
        output_path,
        save_all=True,
        append_images=frames[1:],
        duration=DEFAULT_FRAME_MS,
        loop=0,
        quality=88,
        method=4,
    )


def render_faction(faction: str, source_root: Path, output_root: Path, seconds: float, output_format: str) -> dict[str, Any]:
    faction_dir = source_root / faction
    if not faction_dir.is_dir():
        raise RuntimeError(f"{faction}: missing source directory {faction_dir}")
    layers, canvas_w, canvas_h = load_layers(faction_dir)
    anims = load_anims(faction_dir)
    selected_ids = fully_upgraded_layer_ids(faction_dir, layers)
    frame_count = max(1, round(seconds * 1000 / DEFAULT_FRAME_MS))

    frames = [
        fit_output_frame(render_native_vcmi_frame(faction_dir, layers, selected_ids, anims, index), faction).convert("RGB")
        for index in range(frame_count)
    ]

    output_root.mkdir(parents=True, exist_ok=True)
    media_path = output_root / f"{faction}_fully_upgraded_1080p.{output_format}"
    png_path = output_root / f"{faction}_fully_upgraded_1080p_first_frame.png"
    remove_if_exists(png_path)
    frames[0].save(png_path, optimize=True)
    if output_format == "mp4":
        save_mp4(frames, media_path, fps=round(1000 / DEFAULT_FRAME_MS))
    elif output_format == "webp":
        save_webp(frames, media_path)
    else:
        raise RuntimeError(f"unsupported output format: {output_format}")

    return {
        "faction": faction,
        "media": str(media_path),
        "firstFrame": str(png_path),
        "frames": frame_count,
        "frameRateMs": DEFAULT_FRAME_MS,
        "selectedLayers": len(selected_ids),
        "animatedSelectedLayers": len(selected_ids.intersection(anims.keys())),
        "coordinateBasis": "native VCMI 800x374 town-screen coordinates, center-cropped or full-width fit to 1920x1080",
        "fitMode": "full-width-on-cover" if faction in FULL_WIDTH_FIT_FACTIONS else "center-crop",
        "animationCompositing": "static layer plus animation overlay",
        "excludedPreviewStructures": sorted(EXCLUDED_PREVIEW_STRUCTURES),
        "source": str(faction_dir),
    }


def write_contact_sheet(results: list[dict[str, Any]], output_root: Path) -> Path:
    thumbs = []
    for result in results:
        image = Image.open(result["firstFrame"]).convert("RGB")
        image.thumbnail((480, 270), Image.Resampling.LANCZOS)
        thumbs.append((result["faction"], image.copy()))

    columns = 2
    rows = math.ceil(len(thumbs) / columns)
    label_h = 34
    sheet = Image.new("RGB", (columns * 480, rows * (270 + label_h)), (24, 24, 24))
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default()
    for index, (faction, thumb) in enumerate(thumbs):
        x = (index % columns) * 480
        y = (index // columns) * (270 + label_h)
        sheet.paste(thumb, (x, y))
        draw.rectangle((x, y + 270, x + 480, y + 270 + label_h), fill=(16, 16, 16))
        draw.text((x + 12, y + 280), faction, fill=(230, 230, 230), font=font)

    path = output_root / "homm3_town_loops_contact_sheet.png"
    sheet.save(path, optimize=True)
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=DEFAULT_SOURCE_ROOT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--seconds", type=float, default=DEFAULT_SECONDS)
    parser.add_argument("--format", choices=("mp4", "webp"), default=DEFAULT_FORMAT)
    parser.add_argument("--faction", action="append", choices=HOMM3_FACTIONS)
    args = parser.parse_args()

    factions = args.faction or HOMM3_FACTIONS
    results = []
    for faction in factions:
        print(f"rendering {faction}...", flush=True)
        results.append(render_faction(faction, args.source_root, args.output_root, args.seconds, args.format))
    contact_sheet = write_contact_sheet(results, args.output_root)
    manifest = {
        "format": args.format,
        "size": {"width": OUTPUT_SIZE[0], "height": OUTPUT_SIZE[1]},
        "loop": True,
        "durationSeconds": args.seconds,
        "sourceRoot": str(args.source_root),
        "contactSheet": str(contact_sheet),
        "results": results,
        "validation": "source-rendered only; visually inspect before treating as final capture",
    }
    manifest_path = args.output_root / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    for result in results:
        print(
            f"{result['faction']}: {result['frames']} frames, "
            f"{result['selectedLayers']} layers, {result['animatedSelectedLayers']} animated -> {result['media']}"
        )
    print(f"manifest: {manifest_path}")
    print(f"contact sheet: {contact_sheet}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
