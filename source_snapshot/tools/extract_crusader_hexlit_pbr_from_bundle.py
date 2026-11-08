#!/usr/bin/env python3
"""Extract Hex/Lit normal + metallic-gloss maps from the shipped Crusader bundle.

The Aug 17 custom_units_castle_h3_crusader bundle addressable-assets the albedo
JPEG but not crusader_owned_skinned_normal.png / metallicgloss.png. The GLB
leftover Texture2D objects `normal` and `Baked_MetallicRoughness` are in the
bundle as unnamed dependencies. This writes the contracted PNG names with Unity
metallic-gloss packing (R=metallic, A=smoothness).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import UnityPy
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BUNDLE = (
    ROOT
    / "Heroes of Might & Magic Olden Era Playtest"
    / "OfflineUnlockMod"
    / "homm3_bundles"
    / "custom_units_castle_h3_crusader"
)
PLUGIN_OUT = (
    ROOT
    / "Heroes of Might & Magic Olden Era Playtest"
    / "OfflineUnlockMod"
    / "homm3_skinned_pbr"
    / "h3_crusader"
)
ARTIFACT_OUT = ROOT / "artifacts" / "crusader_pose_pipeline" / "gpu_cascade_skinned"
NORMAL_NAME = "crusader_owned_skinned_normal.png"
METAL_NAME = "crusader_owned_skinned_metallicgloss.png"


def pack_gltf_metallic_roughness_to_unity_metallic_gloss(image: Image.Image) -> Image.Image:
    import numpy as np

    pixels = np.asarray(image.convert("RGBA"), dtype=np.uint8)
    metal = pixels[..., 2]
    roughness = pixels[..., 1]
    packed = np.zeros_like(pixels)
    packed[..., 0] = metal
    packed[..., 1] = metal
    packed[..., 2] = metal
    packed[..., 3] = np.uint8(255) - roughness
    return Image.fromarray(packed, mode="RGBA")


def read_named_texture(env: UnityPy.Environment, name: str) -> Image.Image:
    matches = []
    for obj in env.objects:
        t = obj.type.name if hasattr(obj.type, "name") else str(obj.type)
        if t != "Texture2D":
            continue
        data = obj.read()
        if getattr(data, "m_Name", None) != name:
            continue
        image = data.image
        if image is None:
            raise SystemExit(f"Texture2D {name!r} decoded to no image")
        matches.append(image)
    if len(matches) != 1:
        raise SystemExit(f"expected exactly one Texture2D named {name!r}, found {len(matches)}")
    return matches[0]


def write_png(image: Image.Image, path: Path) -> dict[str, object]:
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, format="PNG", optimize=True)
    payload = path.read_bytes()
    return {
        "path": str(path),
        "width": int(image.size[0]),
        "height": int(image.size[1]),
        "mode": image.mode,
        "bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest().upper(),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--bundle", type=Path, default=DEFAULT_BUNDLE)
    args = ap.parse_args()
    bundle = args.bundle if args.bundle.is_absolute() else ROOT / args.bundle
    if not bundle.is_file():
        print(f"missing crusader bundle: {bundle}", file=sys.stderr)
        return 1

    env = UnityPy.load(str(bundle))
    normal = read_named_texture(env, "normal").convert("RGB")
    metal_src = read_named_texture(env, "Baked_MetallicRoughness")
    metal = pack_gltf_metallic_roughness_to_unity_metallic_gloss(metal_src)
    if normal.size != metal.size:
        print(f"normal {normal.size} != metallic-gloss {metal.size}", file=sys.stderr)
        return 1

    report = {
        "bundle": str(bundle),
        "sourceTextures": ["normal", "Baked_MetallicRoughness"],
        "packing": "gltf G=roughness B=metallic -> Unity R=metallic A=smoothness",
        "outputs": [],
    }
    for dest in (PLUGIN_OUT, ARTIFACT_OUT):
        report["outputs"].append(write_png(normal, dest / NORMAL_NAME))
        report["outputs"].append(write_png(metal, dest / METAL_NAME))

    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
