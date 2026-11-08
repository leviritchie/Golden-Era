#!/usr/bin/env python3
"""Deploy source-backed runtime card/icon art for remaining HoMM3 factions."""

from __future__ import annotations

import argparse
import json
import struct
import zlib
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
OFFLINE = ROOT / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod"
RUNTIME_ASSETS = OFFLINE / "homm3_runtime_assets"
H3BITMAP_LOD = ROOT / "HoMM 3 Complete" / "Data" / "H3bitmap.lod"
COVE_BACKGROUND = ROOT / "vcmi" / "Mods" / "hota" / "mods" / "cove" / "Content" / "data" / "hota" / "cove" / "town" / "background.png"
COVE_ICON_SOURCE = ROOT / "faction_icons" / "homm3_cove" / "skull-and-cross-bones-openclipart-56041.png"

BACKDROP_ENTRIES = {
    "homm3_castle": ("TBcsback.pcx", "Castle-in-background.png", "Icon_Faction_Castle.png"),
    "homm3_dungeon": ("tbdnback.pcx", "Dungeon-in-background.png", "Icon_Faction_Dungeon.png"),
    "homm3_rampart": ("tbrmback.pcx", "Rampart-in-background.png", "Icon_Faction_Rampart.png"),
    "homm3_conflux": ("TBELBack.pcx", "Conflux-in-background.png", "Icon_Faction_Conflux.png"),
    "homm3_inferno": ("tbinback.pcx", "Inferno-in-background.png", "Icon_Faction_Inferno.png"),
    "homm3_necropolis": ("tbncback.pcx", "Necropolis-in-background.png", "Icon_Faction_Necropolis.png"),
}

ICON_SOURCE_BY_FACTION = {
    "homm3_castle": ROOT / "faction_icons" / "Haven_H6_banner.webp",
    "homm3_dungeon": ROOT / "faction_icons" / "Dungeon_logo_H6.webp",
    "homm3_rampart": ROOT / "faction_icons" / "rampart.webp",
    "homm3_conflux": ROOT / "faction_icons" / "conflux.webp",
    "homm3_inferno": ROOT / "faction_icons" / "Inferno_H6_banner.webp",
    "homm3_necropolis": ROOT / "faction_icons" / "Necropolis_H6_banner.webp",
}

NEGATIVE_ICON_FACTIONS = {"homm3_cove", "homm3_necropolis"}
COVE_FILES = ("homm3_cove", "Cove-in-background.png", "Icon_Faction_Cove.png")


def extract_lod_entry(lod_path: Path, want_name: str) -> bytes:
    want = want_name.lower().encode("ascii")
    data = lod_path.read_bytes()
    if data[:4] != b"LOD\0":
        raise RuntimeError(f"not an LOD archive: {lod_path}")
    total = struct.unpack_from("<I", data, 8)[0]
    offset = 92
    rows = []
    for _ in range(total):
        raw = data[offset : offset + 16]
        offset += 16
        nul = raw.find(b"\0")
        name = (raw[:nul] if nul >= 0 else raw).lower()
        file_offset, file_size, _unused, file_csize = struct.unpack_from("<IIII", data, offset)
        offset += 16
        rows.append((name, file_offset, file_size, file_csize))

    for name, file_offset, file_size, file_csize in rows:
        if name != want:
            continue
        blob = data[file_offset : file_offset + file_csize] if file_csize else data[file_offset : file_offset + file_size]
        return zlib.decompress(blob) if file_csize else blob
    raise FileNotFoundError(f"{want_name} not found in {lod_path}")


def decode_h3_backdrop_payload(blob: bytes) -> Image.Image:
    if len(blob) < 12:
        raise RuntimeError("HoMM3 backdrop payload is too short")
    payload_len, width, height = struct.unpack_from("<III", blob, 0)
    expected = 12 + (width * height * 3)
    if payload_len != width * height * 3 or len(blob) < expected:
        raise RuntimeError(
            f"unexpected HoMM3 backdrop payload: payload={payload_len} size={width}x{height} bytes={len(blob)}"
        )
    src = blob[12:expected]
    rgb = bytearray(len(src))
    for index in range(0, len(src), 3):
        rgb[index] = src[index + 2]
        rgb[index + 1] = src[index + 1]
        rgb[index + 2] = src[index]
    return Image.frombytes("RGB", (width, height), bytes(rgb)).convert("RGBA")


def write_image_if_changed(image: Image.Image, path: Path) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    image.save(tmp, format="PNG")
    changed = not path.exists() or path.read_bytes() != tmp.read_bytes()
    if changed:
        tmp.replace(path)
    else:
        tmp.unlink()
    return changed


def fit_icon(source: Image.Image) -> Image.Image:
    rgba = source.convert("RGBA")
    canvas = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
    scale = min(232 / rgba.width, 232 / rgba.height)
    size = (round(rgba.width * scale), round(rgba.height * scale))
    fitted = rgba.resize(size, Image.Resampling.LANCZOS)
    canvas.alpha_composite(fitted, ((256 - size[0]) // 2, (256 - size[1]) // 2))
    return canvas


def invert_icon_colors(icon: Image.Image) -> Image.Image:
    rgba = icon.convert("RGBA")
    r, g, b, a = rgba.split()
    rgb = Image.merge("RGB", (r, g, b))
    inverted = Image.eval(rgb, lambda value: 255 - value).convert("RGBA")
    inverted.putalpha(a)
    return inverted


def build_faction_icon(faction_sid: str, source: Image.Image) -> tuple[Image.Image, bool]:
    icon = fit_icon(source)
    if faction_sid not in NEGATIVE_ICON_FACTIONS:
        return icon, False
    return invert_icon_colors(icon), True


def deploy_lod_backdrops() -> tuple[int, dict[str, dict[str, str]]]:
    changed = 0
    manifest: dict[str, dict[str, str]] = {}
    if not H3BITMAP_LOD.is_file():
        raise FileNotFoundError(H3BITMAP_LOD)
    for faction_sid, (lod_entry, card_name, icon_name) in BACKDROP_ENTRIES.items():
        icon_source = ICON_SOURCE_BY_FACTION[faction_sid]
        if not icon_source.is_file():
            raise FileNotFoundError(icon_source)

        card = decode_h3_backdrop_payload(extract_lod_entry(H3BITMAP_LOD, lod_entry))
        icon = Image.open(icon_source).convert("RGBA")
        card_path = RUNTIME_ASSETS / "town_scene_refs" / faction_sid / card_name
        icon_path = RUNTIME_ASSETS / "faction_icons" / faction_sid / icon_name
        fitted_icon, inverted = build_faction_icon(faction_sid, icon)
        changed += int(write_image_if_changed(card, card_path))
        changed += int(write_image_if_changed(fitted_icon, icon_path))
        manifest[faction_sid] = {
            "townCard": str(card_path.relative_to(ROOT)).replace("\\", "/"),
            "factionIcon": str(icon_path.relative_to(ROOT)).replace("\\", "/"),
            "source": str(H3BITMAP_LOD.relative_to(ROOT)).replace("\\", "/") + ":" + lod_entry,
            "iconSource": str(icon_source.relative_to(ROOT)).replace("\\", "/"),
            "iconNote": "Icon is fitted from root faction_icons artwork; the town card remains the HoMM3 backdrop."
            + (" Colors are inverted for dark-background readability." if inverted else ""),
        }
    return changed, manifest


def deploy_cove() -> tuple[int, dict[str, dict[str, str]]]:
    faction_sid, card_name, icon_name = COVE_FILES
    if not COVE_BACKGROUND.is_file():
        raise FileNotFoundError(COVE_BACKGROUND)
    if not COVE_ICON_SOURCE.is_file():
        raise FileNotFoundError(COVE_ICON_SOURCE)
    card = Image.open(COVE_BACKGROUND).convert("RGBA")
    icon = Image.open(COVE_ICON_SOURCE).convert("RGBA")
    card_path = RUNTIME_ASSETS / "town_scene_refs" / faction_sid / card_name
    icon_path = RUNTIME_ASSETS / "faction_icons" / faction_sid / icon_name
    fitted_icon, inverted = build_faction_icon(faction_sid, icon)
    changed = int(write_image_if_changed(card, card_path))
    changed += int(write_image_if_changed(fitted_icon, icon_path))
    return changed, {
        faction_sid: {
            "townCard": str(card_path.relative_to(ROOT)).replace("\\", "/"),
            "factionIcon": str(icon_path.relative_to(ROOT)).replace("\\", "/"),
            "source": str(COVE_BACKGROUND.relative_to(ROOT)).replace("\\", "/"),
            "iconSource": str(COVE_ICON_SOURCE.relative_to(ROOT)).replace("\\", "/"),
            "iconNote": "Icon is a transparent OpenClipart/PublicDomainVectors skull-and-crossbones fitted to 256x256."
            + (" Colors are inverted for dark-background readability." if inverted else ""),
        }
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-cove", action="store_true")
    args = parser.parse_args()

    changed, manifest = deploy_lod_backdrops()
    if not args.skip_cove:
        cove_changed, cove_manifest = deploy_cove()
        changed += cove_changed
        manifest.update(cove_manifest)

    manifest_path = RUNTIME_ASSETS / "remaining_faction_runtime_asset_manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps({"schemaVersion": 1, "sources": manifest}, indent=2) + "\n"
    if not manifest_path.exists() or manifest_path.read_text(encoding="utf-8") != text:
        manifest_path.write_text(text, encoding="utf-8")
        changed += 1
    print(f"Remaining-faction runtime card/icon files changed: {changed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())