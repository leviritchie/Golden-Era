#!/usr/bin/env python3
"""Extract authentic HoMM3 crusader move frames (CCRUSD group 0).

The Golden Era ``custom_units_castle_h3_crusader`` bundle still carries the
battle ``Texture2D`` frames packed from ``CCRUSD.def``. Group 0 was RIFE'd
from 8 native 12 fps plates to 40 frames. This tool writes the **native**
eight (``00_0000``, ``00_0005``, …) — the HoMM3 move animation — not a
drawn-rectangle stand-in.

  python tools/homm3_depth_billboard/extract_ccrusd_move.py \
      --bundle /path/to/custom_units_castle_h3_crusader \
      --out-dir artifacts/depth_billboard/ccrusd_g00_native
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image

RIFE_GROUP0_COUNT = 40
NATIVE_GROUP0_COUNT = 8
NATIVE_STRIDE = 5
DEFAULT_PAD = 16
ALPHA_OPAQUE = 0.08
GOLDEN_ERA_BUNDLE_REL = (
    "payload/BepInEx/plugins/OfflineUnlockMod/homm3_bundles/"
    "custom_units_castle_h3_crusader"
)


def native_group0_texture_names(texture_names: list[str]) -> list[str]:
    """Return the 8 native DEF move plates from a RIFE-40 ``00_*`` name list."""
    group0 = sorted(name for name in texture_names if name.startswith("00_"))
    if len(group0) != RIFE_GROUP0_COUNT:
        raise ValueError(
            f"CCRUSD group 0 must have {RIFE_GROUP0_COUNT} RIFE frames, "
            f"got {len(group0)}: {group0[:8]}"
        )
    native = group0[::NATIVE_STRIDE]
    if len(native) != NATIVE_GROUP0_COUNT:
        raise ValueError(
            f"native CCRUSD group 0 must be {NATIVE_GROUP0_COUNT} plates, got {len(native)}"
        )
    return native


def union_opaque_bbox(
    frames: list[np.ndarray],
    *,
    pad: int = DEFAULT_PAD,
) -> tuple[int, int, int, int]:
    """Inclusive-exclusive crop box around every opaque pixel, plus padding."""
    if pad < 0:
        raise ValueError("pad must be >= 0")
    if not frames:
        raise ValueError("no frames")
    height, width = frames[0].shape[:2]
    ys: list[np.ndarray] = []
    xs: list[np.ndarray] = []
    for rgba in frames:
        if rgba.shape[:2] != (height, width):
            raise ValueError(f"frame size {rgba.shape[:2]} != {(height, width)}")
        mask = rgba[..., 3].astype(np.float32) / 255.0 > ALPHA_OPAQUE
        if not mask.any():
            raise ValueError("a CCRUSD frame has no opaque pixels")
        rows, cols = np.nonzero(mask)
        ys.append(rows)
        xs.append(cols)
    y0 = max(0, int(min(int(v.min()) for v in ys) - pad))
    x0 = max(0, int(min(int(v.min()) for v in xs) - pad))
    y1 = min(height, int(max(int(v.max()) for v in ys) + 1 + pad))
    x1 = min(width, int(max(int(v.max()) for v in xs) + 1 + pad))
    if y1 <= y0 or x1 <= x0:
        raise ValueError("empty CCRUSD crop box")
    return x0, y0, x1, y1


def crop_frames(
    frames: list[np.ndarray],
    box: tuple[int, int, int, int],
) -> list[np.ndarray]:
    x0, y0, x1, y1 = box
    return [frame[y0:y1, x0:x1].copy() for frame in frames]


def extract_group0_native_from_bundle(bundle: Path) -> tuple[list[str], list[np.ndarray]]:
    """Read native CCRUSD group-0 plates from a Unity asset bundle."""
    try:
        import UnityPy
    except ImportError as exc:
        raise RuntimeError(
            "UnityPy is required to read the crusader battle bundle. "
            "Install it in this environment before extracting CCRUSD frames."
        ) from exc
    bundle = Path(bundle)
    if not bundle.is_file():
        raise FileNotFoundError(f"crusader bundle is missing: {bundle}")
    env = UnityPy.load(str(bundle))
    textures: dict[str, np.ndarray] = {}
    for obj in env.objects:
        if obj.type.name != "Texture2D":
            continue
        data = obj.read()
        name = getattr(data, "m_Name", "") or ""
        if not name.startswith("00_"):
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
    names = native_group0_texture_names(list(textures))
    return names, [textures[name] for name in names]


def write_native_clip(
    frames: list[np.ndarray],
    names: list[str],
    out_dir: Path,
    *,
    crop: bool,
    pad: int,
    source_bundle: Path,
) -> dict:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    if any(out_dir.iterdir()):
        raise FileExistsError(f"refusing to write into a non-empty directory: {out_dir}")
    box = union_opaque_bbox(frames, pad=pad) if crop else (0, 0, frames[0].shape[1], frames[0].shape[0])
    cropped = crop_frames(frames, box)
    written = []
    for index, (name, rgba) in enumerate(zip(names, cropped)):
        dest = out_dir / f"{index}.png"
        Image.fromarray(rgba, "RGBA").save(dest)
        written.append(dest.name)
    manifest = {
        "schema": "homm3_ccrusd_native_move.v1",
        "def": "CCRUSD.def",
        "group": 0,
        "animation": "move",
        "nativeFrameCount": NATIVE_GROUP0_COUNT,
        "rifeFrameCount": RIFE_GROUP0_COUNT,
        "sourceFps": 12,
        "textureNames": names,
        "written": written,
        "cropBoxXYXY": list(box),
        "cropped": bool(crop),
        "sourceBundle": str(Path(source_bundle).resolve()),
        "note": (
            "Native HoMM3 crusader move plates from the Golden Era battle bundle. "
            "Not a synthetic stand-in. RIFE in-betweens are omitted (VDA policy)."
        ),
    }
    (out_dir / "ccrusd_native_move.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--no-crop", action="store_true")
    parser.add_argument("--pad", type=int, default=DEFAULT_PAD)
    args = parser.parse_args()
    names, frames = extract_group0_native_from_bundle(args.bundle)
    manifest = write_native_clip(
        frames,
        names,
        args.out_dir,
        crop=not args.no_crop,
        pad=args.pad,
        source_bundle=args.bundle,
    )
    print(json.dumps({"ok": True, "out": str(args.out_dir.resolve()), **manifest}, indent=2))


if __name__ == "__main__":
    main()
