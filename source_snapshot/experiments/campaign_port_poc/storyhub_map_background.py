"""Integer-scale + crop HoMM3 campaign hub backgrounds for Olden StoryHub MapImage.

Source: G*_BG at 800x600 (H3bitmap.lod PCX / extracted PNG).

HoMM3 embeds a near-black right-hand UI panel in these backgrounds (mission text
area). We keep only the painted map to the left of that panel.

Pipeline:
  1. detect / crop away the right black panel -> 456x600
  2. nearest-neighbor x2 -> 912x1200
  3. center-crop height -> 912x1080
  4. paste centered within the middle 2/3 of a 1920x1080 canvas
     (band x=320..1600; map paste x=504) so right-side UI does not clip art
"""
from __future__ import annotations

import struct
import zlib
from pathlib import Path

from PIL import Image

SOURCE_WIDTH = 800
SOURCE_HEIGHT = 600
SCALE = 2
REFERENCE_WIDTH = 1920
REFERENCE_HEIGHT = 1080
# Middle 2/3 of 1080p: keep map art away from right-side StoryHub UI chrome.
SAFE_CONTENT_WIDTH = (REFERENCE_WIDTH * 2) // 3  # 1280
SAFE_CONTENT_LEFT = (REFERENCE_WIDTH - SAFE_CONTENT_WIDTH) // 2  # 320
BLACK_PANEL_MAX_CHANNEL = 18
BLACK_PANEL_COLUMN_FRACTION = 0.90
MIN_MAP_WIDTH = 400
MAX_MAP_WIDTH = 520
EXPECTED_MAP_WIDTH = 456
SCALED_MAP_WIDTH = EXPECTED_MAP_WIDTH * SCALE  # 912
SCALED_MAP_HEIGHT = SOURCE_HEIGHT * SCALE  # 1200
MAP_HEIGHT_ON_CANVAS = REFERENCE_HEIGHT
CROP_TOP = (SCALED_MAP_HEIGHT - MAP_HEIGHT_ON_CANVAS) // 2  # 60
TARGET_WIDTH = REFERENCE_WIDTH
TARGET_HEIGHT = REFERENCE_HEIGHT
# Center the scaled map inside the middle-2/3 safe band.
MAP_PASTE_X = SAFE_CONTENT_LEFT + (SAFE_CONTENT_WIDTH - SCALED_MAP_WIDTH) // 2  # 504

# Hub SID → HoMM3 Complete *_BG PCX stem (H3bitmap.lod / H3ab_bmp.lod).
# Geography stems from CampText (Bracada/Islands/Krewlod/Nighon/Tatalia/Armageddon
# + SoD campaign names). Every live hub must map to a distinct bake.
DEFAULT_HUBS: dict[str, str] = {
    "homm3_01_roe_castle_good1": "G1_BG",
    "homm3_02_roe_castle_good2": "G2_BG",
    "homm3_03_roe_castle_good3": "G3_BG",
    "homm3_04_roe_dungeon_evil1": "E1_BG",
    "homm3_05_roe_necropolis_evil2": "E2_BG",
    "homm3_06_roe_neutral_neutral1": "N1_BG",
    "homm3_07_roe_rampart_secret1": "S1_BG",
    "homm3_08_roe_necropolis_secret": "SP_BG",
    "homm3_09_ab_conflux_ab": "AR_BG",
    "homm3_10_ab_dungeon_blood": "NI_BG",
    "homm3_11_ab_tower_slayer": "BR_BG",
    "homm3_12_ab_stronghold_festival": "KR_BG",
    "homm3_13_ab_fortress_fire": "TA_BG",
    "homm3_14_ab_castle_fool": "IS_BG",
    "homm3_15_sod_necropolis_sandro": "RN_BG",
    "homm3_16_sod_stronghold_crag": "HS_BG",
    "homm3_17_sod_stronghold_yog": "BB_BG",
    "homm3_18_sod_rampart_gem": "NB_BG",
    "homm3_19_sod_rampart_gelu": "EL_BG",
    "homm3_20_sod_necropolis_final": "UA_BG",
}


def fail(message: str) -> None:
    raise SystemExit(f"storyhub map background failed: {message}")


def read_h3_pcx(data: bytes) -> Image.Image:
    if len(data) < 12:
        fail("pcx blob too small")
    size, width, height = struct.unpack_from("<III", data, 0)
    if size == width * height:
        im = Image.frombytes("P", (width, height), data[12 : 12 + width * height])
        palette: list[int] = []
        base = 12 + width * height
        for i in range(256):
            offset = base + i * 3
            r, g, b = struct.unpack_from("<BBB", data, offset)
            palette.extend((r, g, b))
        im.putpalette(palette)
        return im.convert("RGB")
    if size == width * height * 3:
        return Image.frombytes("RGB", (width, height), data[12 : 12 + size])
    fail(f"unsupported h3 pcx size={size} {width}x{height}")


def extract_lod_pcx(lod_path: Path, entry_name: str) -> Image.Image:
    data = lod_path.read_bytes()
    if data[:4] != b"LOD\0":
        fail(f"not an LOD file: {lod_path}")
    total = struct.unpack_from("<I", data, 8)[0]
    want = entry_name.lower().encode("ascii")
    off = 92
    for _ in range(total):
        raw = data[off : off + 16]
        off += 16
        nul = raw.find(b"\0")
        name = raw[:nul] if nul >= 0 else raw
        name = name.lower()
        o, size, _u, csize = struct.unpack_from("<IIII", data, off)
        off += 16
        if name != want:
            continue
        blob = data[o : o + (csize if csize else size)]
        if csize:
            blob = zlib.decompress(blob)
        return read_h3_pcx(blob)
    fail(f"{entry_name} not found in {lod_path}")


def load_source_bg(
    *,
    prefix: str,
    storyhub_visual_dir: Path,
    lod_path: Path | None,
) -> Image.Image:
    png = storyhub_visual_dir / f"{prefix}.png"
    if png.is_file():
        im = Image.open(png).convert("RGB")
    elif lod_path is not None and lod_path.is_file():
        im = extract_lod_pcx(lod_path, f"{prefix}.pcx")
    else:
        fail(
            f"missing source for {prefix}: expected {png}"
            + (f" or LOD entry in {lod_path}" if lod_path else "")
        )
    if im.size != (SOURCE_WIDTH, SOURCE_HEIGHT):
        fail(f"{prefix} source size {im.size[0]}x{im.size[1]} != {SOURCE_WIDTH}x{SOURCE_HEIGHT}")
    return im


def detect_map_width(source: Image.Image) -> int:
    """Return exclusive right X of painted map content (left of the black UI panel)."""
    pixels = source.load()
    width, height = source.size
    dark_cols: list[float] = []
    for x in range(width):
        dark = 0
        for y in range(height):
            r, g, b = pixels[x, y][:3]
            if max(r, g, b) < BLACK_PANEL_MAX_CHANNEL:
                dark += 1
        dark_cols.append(dark / height)

    edge = None
    for x in range(width):
        if dark_cols[x] < BLACK_PANEL_COLUMN_FRACTION:
            continue
        window = dark_cols[x : min(width, x + 24)]
        if window and sum(window) / len(window) >= BLACK_PANEL_COLUMN_FRACTION:
            edge = x
            break
    if edge is None:
        fail("could not detect right black UI panel in source background")
    if edge < MIN_MAP_WIDTH or edge > MAX_MAP_WIDTH:
        fail(f"detected map width {edge} outside [{MIN_MAP_WIDTH}, {MAX_MAP_WIDTH}]")
    if edge != EXPECTED_MAP_WIDTH:
        fail(
            f"detected map width {edge} != pinned EXPECTED_MAP_WIDTH {EXPECTED_MAP_WIDTH}; "
            "update the pin only after confirming the new crop against live StoryHub"
        )
    return edge


def bake_newmap_canvas(source: Image.Image) -> Image.Image:
    if source.size != (SOURCE_WIDTH, SOURCE_HEIGHT):
        fail(f"bake input size {source.size[0]}x{source.size[1]} != {SOURCE_WIDTH}x{SOURCE_HEIGHT}")
    map_width = detect_map_width(source)
    map_only = source.crop((0, 0, map_width, SOURCE_HEIGHT))
    nearest = getattr(Image, "Resampling", Image).NEAREST if hasattr(Image, "Resampling") else Image.NEAREST
    scaled_w = map_width * SCALE
    scaled_h = SOURCE_HEIGHT * SCALE
    scaled = map_only.resize((scaled_w, scaled_h), resample=nearest)
    cropped = scaled.crop((0, CROP_TOP, scaled_w, CROP_TOP + MAP_HEIGHT_ON_CANVAS))
    if cropped.size[0] > SAFE_CONTENT_WIDTH:
        fail(
            f"scaled map width {cropped.size[0]} exceeds safe middle-2/3 width {SAFE_CONTENT_WIDTH}"
        )
    paste_x = SAFE_CONTENT_LEFT + (SAFE_CONTENT_WIDTH - cropped.size[0]) // 2
    if paste_x != MAP_PASTE_X and cropped.size[0] == SCALED_MAP_WIDTH:
        fail(f"paste x {paste_x} != pinned MAP_PASTE_X {MAP_PASTE_X}")
    canvas = Image.new("RGB", (TARGET_WIDTH, TARGET_HEIGHT), (0, 0, 0))
    canvas.paste(cropped, (paste_x, 0))
    if canvas.size != (TARGET_WIDTH, TARGET_HEIGHT):
        fail(f"canvas produced {canvas.size}, expected {TARGET_WIDTH}x{TARGET_HEIGHT}")
    return canvas


def output_filename(prefix: str) -> str:
    return f"{prefix}_{TARGET_WIDTH}x{TARGET_HEIGHT}.png"


def bake_prefix_to_path(
    *,
    prefix: str,
    storyhub_visual_dir: Path,
    out_dir: Path,
    lod_path: Path | None,
) -> Path:
    source = load_source_bg(
        prefix=prefix,
        storyhub_visual_dir=storyhub_visual_dir,
        lod_path=lod_path,
    )
    canvas = bake_newmap_canvas(source)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / output_filename(prefix)
    canvas.save(out_path, format="PNG")
    return out_path
