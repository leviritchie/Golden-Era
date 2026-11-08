#!/usr/bin/env python3
"""Build the Factory town painted-upscale experiment.

This lane deliberately separates:

* static building layers, which may be painted-upscaled;
* animation frame directories, which remain byte-for-byte untouched;
* the existing Factory background plate, whose non-black source rectangle is
  preserved and whose old black right/bottom regions are outpainted.

The runtime compositor uses the reference rectangles in positions.json, so
the layer outputs are padded back to each source sprite's original canvas
before they are installed.  That prevents a transparent source margin from
silently becoming a position or scale change.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter


ROOT = Path(__file__).resolve().parents[1]
MOD = ROOT / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod"
SCENE = MOD / "homm3_runtime_assets" / "town_scene_refs" / "homm3_factory"
LAYERS = SCENE / "layers"
PILOT = ROOT / "artifacts" / "factory_town_upscale_pilot"
POSITIONS = LAYERS / "positions.json"
ANIM_METADATA = LAYERS / "anims" / "metadata.json"
ASSET_MANIFEST = MOD / "homm3_runtime_assets" / "hota_factory_bulwark_asset_manifest.json"
BACKGROUND_NAME = "homm3_factory_background_upscaled_3840x2160.png"
BACKGROUND_TARGET = (3840, 2160)
AUTHENTIC_SOURCE_RECT = (0, 0, 1440, 673)
PLATE = (20, 243, 14)
STATIC_MAX_SIDE = 1024


def load_pilot_manifest() -> dict:
    return json.loads((PILOT / "pilot_manifest.json").read_text(encoding="utf-8"))


def animated_ids() -> set[str]:
    return {
        str(row["id"])
        for row in json.loads(ANIM_METADATA.read_text(encoding="utf-8"))
        if row.get("id")
    }


def key_generated_image(ai: Image.Image, original: Image.Image) -> Image.Image:
    sys.path.insert(0, str(ROOT / "tools"))
    import hero_portrait_touchup_pilot as hpp

    if hpp.looks_plate_color(ai, PLATE):
        cleaned = hpp.key_chroma_plate(ai, PLATE)
    elif hpp.looks_near_black_void(ai):
        cleaned = hpp.key_near_black_void(ai, original)
    else:
        cleaned, _ = hpp.prepass_portrait(ai, original)
        if hpp.looks_plate_color(cleaned, PLATE):
            cleaned = hpp.key_chroma_plate(cleaned, PLATE)
        if hpp.looks_near_black_void(cleaned):
            cleaned = hpp.key_near_black_void(cleaned, original)
    return cleaned.convert("RGBA")


def alpha_bbox(image: Image.Image) -> tuple[int, int, int, int] | None:
    alpha = np.asarray(image.convert("RGBA"))[:, :, 3]
    ys, xs = np.where(alpha > 24)
    if len(xs) == 0:
        return None
    return int(xs.min()), int(ys.min()), int(xs.max() + 1), int(ys.max() + 1)


def target_canvas_size(source_size: tuple[int, int]) -> tuple[int, int]:
    width, height = source_size
    if width >= height:
        return STATIC_MAX_SIDE, max(1, round(STATIC_MAX_SIDE * height / width))
    return max(1, round(STATIC_MAX_SIDE * width / height)), STATIC_MAX_SIDE


def fit_ai_into_source_canvas(
    cleaned: Image.Image, original: Image.Image
) -> Image.Image:
    """Preserve the source canvas and alpha-bounds layout around the AI art."""
    source_box = alpha_bbox(original)
    generated_box = alpha_bbox(cleaned)
    if source_box is None or generated_box is None:
        raise RuntimeError("source or generated layer has no visible pixels")

    target_width, target_height = target_canvas_size(original.size)
    source_scale_x = target_width / original.width
    source_scale_y = target_height / original.height
    target_box = tuple(
        round(value * scale)
        for value, scale in zip(
            source_box,
            (source_scale_x, source_scale_y, source_scale_x, source_scale_y),
        )
    )
    generated = cleaned.crop(generated_box)
    generated = generated.resize(
        (max(1, target_box[2] - target_box[0]), max(1, target_box[3] - target_box[1])),
        Image.Resampling.LANCZOS,
    )
    result = Image.new("RGBA", (target_width, target_height), (0, 0, 0, 0))
    result.alpha_composite(generated, (target_box[0], target_box[1]))
    pixels = np.asarray(result).copy()
    pixels[pixels[:, :, 3] < 8, :3] = 0
    return Image.fromarray(pixels, "RGBA")


def write_review(
    sid: str, original: Image.Image, lanczos: Image.Image, ai: Image.Image, final: Image.Image
) -> None:
    cell = 256

    def fit(image: Image.Image) -> Image.Image:
        image = image.convert("RGBA")
        image.thumbnail((cell, cell), Image.Resampling.LANCZOS)
        canvas = Image.new("RGBA", (cell, cell), (32, 32, 32, 255))
        canvas.alpha_composite(image, ((cell - image.width) // 2, (cell - image.height) // 2))
        return canvas

    strip = Image.new("RGBA", (cell * 4, cell), (32, 32, 32, 255))
    for index, image in enumerate((original, lanczos, ai, final)):
        strip.alpha_composite(fit(image), (cell * index, 0))
    (PILOT / "review").mkdir(parents=True, exist_ok=True)
    strip.convert("RGB").save(PILOT / "review" / f"{sid}__review.png")


def process_layers(manifest: dict, *, fallback_ids: set[str]) -> None:
    animated = animated_ids()
    for row in manifest["staticLayers"]:
        sid = str(row["id"])
        source = PILOT / "original" / str(row["sprite"])
        if sid in animated:
            row["status"] = "excluded_animated"
            continue
        if not source.is_file():
            raise RuntimeError(f"missing Factory source layer: {source}")
        original = Image.open(source).convert("RGBA")
        lanczos = original.resize(target_canvas_size(original.size), Image.Resampling.LANCZOS)
        ai_path = PILOT / "ai" / f"{sid}.png"
        if sid in fallback_ids:
            final = lanczos
            row["generation"] = "source-preserving-lanczos-fallback"
            ai = original
        else:
            if not ai_path.is_file():
                raise RuntimeError(f"missing generated Factory layer: {ai_path}")
            ai = Image.open(ai_path).convert("RGBA")
            final = fit_ai_into_source_canvas(key_generated_image(ai, original), original)
            row["generation"] = "painted-upscale-with-source-canvas-preservation"
        if final.getbbox() is None:
            raise RuntimeError(f"empty Factory layer after processing: {sid}")
        final_path = PILOT / "final" / f"{sid}.png"
        final.save(final_path)
        write_review(sid, original, lanczos, ai, final)
        row.update(
            status="postpassed",
            finalPath=f"final/{sid}.png",
            finalSize=list(final.size),
            sourceSize=list(original.size),
            animated=False,
        )


def _lowpass_rgba(arr: np.ndarray, radius: float) -> np.ndarray:
    image = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), "RGBA")
    return np.asarray(image.filter(ImageFilter.GaussianBlur(radius))).astype(np.float32)


def compose_background(manifest: dict) -> Path:
    """Compose Factory 4K background from AI outpaint with fresh MAD shift + gradual blur.

    Preferred source is terrain_v6b (building-continuation outpaint). Shift is
    remeasured against the authentic plate for that AI frame — never reused from
    another generation. No texture quilting.
    """
    import sys

    sys.path.insert(0, str(ROOT / "tools"))
    from preview_factory_realign_outpaint import compose as recipe_compose
    from preview_factory_realign_outpaint import find_mad_shift

    preferred = PILOT / "ai" / "factory_background_outpaint_terrain_v6b.png"
    fallbacks = [
        PILOT / "ai" / "factory_background_outpaint_terrain_v6.png",
        PILOT / "ai" / "factory_background_outpaint_terrain_v5.png",
        PILOT / "ai" / "factory_background_outpaint_mockup_only.png",
    ]
    generated_path = preferred if preferred.is_file() else next((p for p in fallbacks if p.is_file()), None)
    if generated_path is None:
        raise RuntimeError(f"missing Factory background generation: {preferred}")

    source = Image.open(PILOT / "original" / "background_mock_1920x1080.png").convert("RGBA")
    x0, y0, x1, y1 = AUTHENTIC_SOURCE_RECT
    if source.size != (1920, 1080):
        raise RuntimeError(f"unexpected Factory mockup size: {source.size}")
    iw = BACKGROUND_TARGET[0] * (x1 - x0) // 1920
    ih = BACKGROUND_TARGET[1] * (y1 - y0) // 1080
    auth_img = source.crop((x0, y0, x1, y1)).resize((iw, ih), Image.Resampling.LANCZOS)
    auth = np.asarray(auth_img).astype(np.float32)
    auth_g = np.asarray(auth_img.convert("L"), np.float32)
    ai = Image.open(generated_path).convert("RGBA").resize(BACKGROUND_TARGET, Image.Resampling.LANCZOS)
    align = find_mad_shift(auth_img, auth_g, ai, iw, ih)
    tx, ty = int(align["tx"]), int(align["ty"])
    label = "install_compose"
    # recipe_compose writes under preview_align_v5; also save canonical final path.
    composed = recipe_compose(generated_path, auth, iw, ih, tx, ty, label)
    final_path = PILOT / "final" / "homm3_factory_background_3840x2160.png"
    composed.save(final_path)
    manifest["background"] = {
        "sourceMockup": "original/background_mock_1920x1080.png",
        "generatedOutpaint": generated_path.as_posix(),
        "final": "final/homm3_factory_background_3840x2160.png",
        "size": list(BACKGROUND_TARGET),
        "preservedSourceRect": list(AUTHENTIC_SOURCE_RECT),
        "generatedOnlyFor": "right/bottom extension regions",
        "composeMethod": "fresh_mad_shift_fill_progressive_blur",
        "pasteTx": tx,
        "pasteTy": ty,
        "alignMad": align["mad"],
        "alignZeroMad": align["zero_mad"],
        "progBlurInsetPx": 72,
        "progBlurSeamR": 2,
        "progBlurMaxR": 16,
        "progBlurFalloffPx": 1400,
    }
    return final_path


def update_positions() -> None:
    data = json.loads(POSITIONS.read_text(encoding="utf-8"))
    basis = data.get("coordinateBasis") or {}
    reference_canvas = basis.get("referenceCanvas") or {}
    if int(reference_canvas.get("w", 0)) == 3840 and int(reference_canvas.get("h", 0)) == 2160:
        return
    if int(reference_canvas.get("w", 0)) != 1920 or int(reference_canvas.get("h", 0)) != 1080:
        raise RuntimeError(f"unexpected Factory coordinate basis: {reference_canvas}")
    for row in data.get("layers", []):
        for key in ("x", "y", "reference_x", "reference_y", "reference_w", "reference_h"):
            if key in row:
                row[key] = row[key] * 2
    basis["referenceCanvas"] = {"w": 3840, "h": 2160}
    plate = basis.get("referencePlate") or {}
    for key in ("x", "y", "w", "h"):
        if key in plate:
            plate[key] = plate[key] * 2
    basis["referencePlate"] = plate
    basis["uniformScale"] = 3.6
    basis["xScale"] = 3.6
    basis["yScale"] = 3.6
    basis["source"] = (
        "vcmi-top-left-800x374-on-3840x2160-factory-4k-outpaint-"
        "source-plate-preserved-right-bottom-generated"
    )
    basis["runtimeLayout"] = "factory_4k_outpaint_v1"
    data["coordinateBasis"] = basis
    POSITIONS.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def promote_live(manifest: dict, background: Path) -> None:
    backup_root = PILOT / "live_backups"
    for row in manifest["staticLayers"]:
        sid = str(row["id"])
        if sid in animated_ids():
            continue
        final = PILOT / "final" / f"{sid}.png"
        live = LAYERS / str(row["sprite"])
        if not final.is_file():
            raise RuntimeError(f"missing final Factory layer for install: {final}")
        backup = backup_root / live.name
        backup.parent.mkdir(parents=True, exist_ok=True)
        if live.is_file() and not backup.is_file():
            shutil.copy2(live, backup)
        shutil.copy2(final, live)
    live_background = SCENE / "mockups" / BACKGROUND_NAME
    backup_background = backup_root / live_background.name
    if live_background.is_file() and not backup_background.is_file():
        shutil.copy2(live_background, backup_background)
    shutil.copy2(background, live_background)
    manifest["liveBackground"] = str(live_background.relative_to(ROOT)).replace("\\", "/")


def update_runtime_asset_manifest(manifest: dict) -> None:
    if not ASSET_MANIFEST.is_file():
        raise RuntimeError(f"missing shared runtime asset manifest: {ASSET_MANIFEST}")
    asset_manifest = json.loads(ASSET_MANIFEST.read_text(encoding="utf-8"))
    rows_by_path = {
        str(row["path"]): row
        for row in asset_manifest.get("files", [])
        if isinstance(row, dict) and row.get("path")
    }
    paths = [POSITIONS]
    paths.extend(LAYERS / str(row["sprite"]) for row in manifest["staticLayers"] if not row.get("animated"))
    paths.append(SCENE / "mockups" / BACKGROUND_NAME)
    for path in paths:
        if not path.is_file():
            raise RuntimeError(f"cannot hash missing promoted Factory asset: {path}")
        relative = path.relative_to(ROOT).as_posix()
        data = path.read_bytes()
        rows_by_path[relative] = {
            "path": relative,
            "length": len(data),
            "sha256": hashlib.sha256(data).hexdigest().upper(),
        }
    asset_manifest["files"] = sorted(rows_by_path.values(), key=lambda row: row["path"])
    proof_boundary = asset_manifest.setdefault("proofBoundary", {})
    proof_boundary["townAndHeroPresentation"] = (
        "generated Factory/Bulwark presentation assets validated; "
        "startup and user-visible runtime unvalidated"
    )
    ASSET_MANIFEST.write_text(json.dumps(asset_manifest, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--fallback-id",
        action="append",
        default=[],
        help="Use a source-preserving Lanczos output for this ID instead of AI output.",
    )
    parser.add_argument("--install", action="store_true")
    args = parser.parse_args()

    manifest = load_pilot_manifest()
    process_layers(manifest, fallback_ids=set(args.fallback_id))
    final_background = compose_background(manifest)
    update_positions()
    if args.install:
        promote_live(manifest, final_background)
        update_runtime_asset_manifest(manifest)
    manifest["coordinateBasisUpdated"] = True
    (PILOT / "pilot_manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    print(
        f"Factory scene prepared: {len(manifest['staticLayers'])} source rows, "
        f"{len(animated_ids())} animation IDs excluded, background={final_background}"
    )
    if args.install:
        print("Factory source assets promoted; run the established dotnet deploy target to copy them into Golden Era.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
