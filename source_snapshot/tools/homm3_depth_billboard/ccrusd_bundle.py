"""CCRUSD battle-bundle extract helpers for depth-billboard lanes."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from extract_ccrusd_move import (
    DEFAULT_PAD,
    NATIVE_STRIDE,
    crop_frames,
    union_opaque_bbox,
)

# Texture prefixes present on custom_units_castle_h3_crusader (billboard lane).
IDLE_SPEC: dict[str, Any] = {
    "group": 2,
    "prefix": "02",
    "name": "idle",
    "rifeCount": 40,
}
BUNDLE_ANIMATION_SPECS: list[dict[str, Any]] = [
    {"group": 0, "prefix": "00", "name": "move", "rifeCount": 40},
    {"group": 3, "prefix": "03", "name": "hitted", "rifeCount": 30},
    {"group": 5, "prefix": "05", "name": "death", "rifeCount": 30},
    {"group": 12, "prefix": "12", "name": "attack_front", "rifeCount": 35},
]


def load_bundle_texture_map(bundle: Path) -> dict[str, np.ndarray]:
    try:
        import UnityPy
    except ImportError as exc:
        raise RuntimeError(
            "UnityPy is required to read the crusader battle bundle."
        ) from exc
    bundle = Path(bundle)
    if not bundle.is_file():
        raise FileNotFoundError(f"crusader bundle is missing: {bundle}")
    textures: dict[str, np.ndarray] = {}
    env = UnityPy.load(str(bundle))
    for obj in env.objects:
        if obj.type.name != "Texture2D":
            continue
        data = obj.read()
        name = getattr(data, "m_Name", "") or ""
        if not name or "_" not in name:
            continue
        prefix = name.split("_", 1)[0]
        if not prefix.isdigit():
            continue
        image = data.image
        if image is None:
            raise RuntimeError(f"Texture2D {name} has no image pixels")
        rgba = np.asarray(image.convert("RGBA"), dtype=np.uint8)
        if int((rgba[..., 3] > 20).sum()) < 200:
            raise RuntimeError(
                f"Texture2D {name} is not a populated CCRUSD sprite "
                f"(opaque={int((rgba[..., 3] > 20).sum())})"
            )
        textures[name] = rgba
    if not textures:
        raise RuntimeError(f"no CCRUSD Texture2D frames in bundle: {bundle}")
    return textures


def native_texture_names(
    texture_names: list[str],
    prefix: str,
    rife_count: int,
) -> list[str]:
    group_names = sorted(name for name in texture_names if name.startswith(f"{prefix}_"))
    if len(group_names) != rife_count:
        raise ValueError(
            f"CCRUSD group {prefix} must have {rife_count} RIFE frames, "
            f"got {len(group_names)}"
        )
    native = group_names[::NATIVE_STRIDE]
    if not native:
        raise ValueError(f"CCRUSD group {prefix} produced no native plates")
    return native


def build_continuous_native_clip(
    bundle: Path,
    *,
    animation_specs: list[dict[str, Any]] | None = None,
    idle_spec: dict[str, Any] = IDLE_SPEC,
    pad: int = DEFAULT_PAD,
) -> tuple[list[np.ndarray], dict[str, Any]]:
    """One continuous native plate list: each animation, then one idle loop between."""
    textures = load_bundle_texture_map(bundle)
    texture_names = list(textures.keys())
    animations = animation_specs or BUNDLE_ANIMATION_SPECS

    idle_names = native_texture_names(
        texture_names, idle_spec["prefix"], int(idle_spec["rifeCount"])
    )
    idle_frames = [textures[name] for name in idle_names]

    segments: list[dict[str, Any]] = []
    all_frames: list[np.ndarray] = []

    for index, spec in enumerate(animations):
        names = native_texture_names(
            texture_names, spec["prefix"], int(spec["rifeCount"])
        )
        frames = [textures[name] for name in names]
        start = len(all_frames)
        all_frames.extend(frames)
        segments.append(
            {
                "group": int(spec["group"]),
                "name": str(spec["name"]),
                "startIndex": start,
                "frameCount": len(frames),
                "nativeFrameCount": len(frames),
                "textureNames": names,
            }
        )
        if index < len(animations) - 1:
            idle_start = len(all_frames)
            all_frames.extend(idle_frames)
            segments.append(
                {
                    "group": int(idle_spec["group"]),
                    "name": "idle",
                    "role": "separator",
                    "startIndex": idle_start,
                    "frameCount": len(idle_frames),
                    "nativeFrameCount": len(idle_frames),
                    "textureNames": list(idle_names),
                }
            )

    box = union_opaque_bbox(all_frames, pad=pad)
    cropped = crop_frames(all_frames, box)
    manifest: dict[str, Any] = {
        "schema": "homm3_ccrusd_continuous_native.v1",
        "def": "CCRUSD.def",
        "sourceFps": 12,
        "nativeStride": NATIVE_STRIDE,
        "totalFrameCount": len(cropped),
        "segments": segments,
        "cropBoxXYXY": list(box),
        "cropped": True,
        "pad": pad,
        "sourceBundle": str(Path(bundle).resolve()),
        "note": (
            "Authentic native DEF plates from the crusader billboard bundle. "
            "Animations are concatenated with one idle loop between each clip. "
            "RIFE in-betweens omitted (VDA policy)."
        ),
    }
    return cropped, manifest


def write_numbered_sprites(
    frames: list[np.ndarray],
    out_dir: Path,
    manifest: dict[str, Any],
    *,
    manifest_name: str = "ccrusd_continuous.json",
) -> dict[str, Any]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    if any(out_dir.iterdir()):
        raise FileExistsError(f"refusing to write into a non-empty directory: {out_dir}")
    written: list[str] = []
    for index, rgba in enumerate(frames):
        dest = out_dir / f"{index}.png"
        Image.fromarray(rgba, "RGBA").save(dest)
        written.append(dest.name)
    manifest = dict(manifest)
    manifest["written"] = written
    (out_dir / manifest_name).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest
