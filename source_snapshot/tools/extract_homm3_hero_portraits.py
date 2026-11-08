#!/usr/bin/env python3
"""Extract HoMM3 hero portraits from source assets and convert to PNG.

HoMM3 large hero portraits in H3bitmap.lod are named *.pcx, but the entries used
by the Complete data files are a compact custom payload: uint32 payload length,
uint32 width, uint32 height, width*height palette indices, then a 256-color RGB
palette. Do not feed these bytes to Pillow's PCX decoder; it produces confetti
for Tower portraits.

HotA/VCMI-only heroes use normal portraitLarge.png source files. Those are read
directly and normalized through the same 64x64 circular-alpha output path.
"""

import argparse
import json
import struct
import sys
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LOD_PATH = ROOT / "HoMM 3 Complete" / "Data" / "H3bitmap.lod"
DEFAULT_OUT_DIR = ROOT / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod" / "homm3_hero_portraits"
HOTA_HEROES_ROOT = ROOT / "vcmi" / "Mods" / "hota" / "mods" / "heroes" / "Content"
HOTA_COVE_ROOT = ROOT / "vcmi" / "Mods" / "hota" / "mods" / "cove" / "Content"


def lod_source(pcx_name, alias_of=None):
    return {"kind": "lod", "pcx": pcx_name.lower(), "aliasOf": alias_of}


def png_source(root, rel_path):
    return {"kind": "png", "root": root, "path": rel_path}


def hota_hero_png(faction, hero):
    return png_source(HOTA_HEROES_ROOT, f"sprites/hota/{faction}/heroes/{hero}/icons/portraitLarge.png")


def cove_hero_png(hero):
    return png_source(HOTA_COVE_ROOT, f"sprites/hota/cove/heroes/{hero}/icons/portraitLarge.png")


def add_rows(rows, faction, start_index, class_type, names, pcx_prefix, pcx_suffix):
    for offset, name in enumerate(names):
        rows.append(
            {
                "sid": f"homm3_{faction}_hero_{start_index + offset}",
                "name": name,
                "classType": class_type,
                "source": lod_source(f"hpl{pcx_prefix + offset:03d}{pcx_suffix}.pcx"),
            }
        )


HERO_MAP = []

add_rows(HERO_MAP, "castle", 1, "might", ["Orrin", "Valeska", "Edric", "Sylvia", "Lord Haart", "Sorsha", "Christian", "Tyris"], 0, "kn")
add_rows(HERO_MAP, "castle", 9, "magic", ["Rion", "Adela", "Cuthbert", "Adelaide", "Ingham", "Sanya", "Loynis", "Caitlin"], 8, "cl")
HERO_MAP.extend(
    [
        {"sid": "homm3_castle_hero_17", "name": "Catherine", "classType": "might", "source": lod_source("hpl128qc.pcx")},
        {"sid": "homm3_castle_hero_18", "name": "Roland", "classType": "might", "source": lod_source("hpl009sh.pcx")},
    ]
)

add_rows(HERO_MAP, "rampart", 1, "might", ["Mephala", "Ufretin", "Jenova", "Ryland", "Thorgrim", "Ivor", "Clancy", "Kyrre"], 16, "rn")
add_rows(HERO_MAP, "rampart", 9, "magic", ["Coronius", "Uland", "Elleshar", "Gem", "Malcom", "Melodia", "Alagar", "Aeris"], 24, "dr")
HERO_MAP.extend(
    [
        {"sid": "homm3_rampart_hero_17", "name": "Gelu", "classType": "might", "source": lod_source("hpl004sh.pcx")},
        {"sid": "homm3_rampart_hero_18", "name": "Ordwald", "classType": "magic", "source": lod_source("hpl132wl.pcx")},
    ]
)
add_rows(HERO_MAP, "tower", 1, "might", ["Piquedram", "Thane", "Josephine", "Neela", "Torosar", "Fafner", "Rissa", "Iona"], 32, "al")
add_rows(HERO_MAP, "tower", 9, "magic", ["Astral", "Halon", "Serena", "Daremyth", "Theodorus", "Solmyr", "Cyra", "Aine"], 40, "wz")
HERO_MAP.extend(
    [
        {"sid": "homm3_tower_hero_17", "name": "Dracon", "classType": "magic", "source": lod_source("hpl003sh.pcx")},
        {"sid": "homm3_tower_hero_18", "name": "Yog the Wizard", "classType": "magic", "source": lod_source("hpl136wi.pcx")},
    ]
)
add_rows(HERO_MAP, "inferno", 1, "might", ["Fiona", "Rashka", "Marius", "Ignatius", "Octavia", "Calh", "Pyre", "Nymus"], 48, "hr")
add_rows(HERO_MAP, "inferno", 9, "magic", ["Ayden", "Xyron", "Axsis", "Olema", "Calid", "Ash", "Zydar", "Xarfax"], 56, "dm")
HERO_MAP.extend(
    [
        {"sid": "homm3_inferno_hero_17", "name": "Xeron", "classType": "might", "source": lod_source("hpl131dm.pcx")},
        {"sid": "homm3_inferno_hero_18", "name": "Miseria", "classType": "magic", "source": hota_hero_png("inferno", "miseria")},
    ]
)

add_rows(HERO_MAP, "necropolis", 1, "might", ["Straker", "Vokial", "Moandor", "Charna", "Tamika", "Isra", "Clavius", "Galthran"], 64, "dk")
add_rows(HERO_MAP, "necropolis", 9, "magic", ["Septienna", "Aislinn", "Sandro", "Nimbus", "Thant", "Xsi", "Vidomina", "Nagash"], 72, "nc")
HERO_MAP.extend(
    [
        {"sid": "homm3_necropolis_hero_17", "name": "Finneas", "classType": "might", "source": lod_source("hpl133nc.pcx")},
        {"sid": "homm3_necropolis_hero_18", "name": "Haart Lich", "classType": "might", "source": lod_source("hpl006sh.pcx")},
    ]
)

add_rows(HERO_MAP, "dungeon", 1, "might", ["Lorelei", "Arlach", "Dace", "Ajit", "Damacon", "Gunnar", "Synca", "Shakti"], 80, "ov")
add_rows(HERO_MAP, "dungeon", 9, "magic", ["Alamar", "Jaegar", "Malekith", "Jeddite", "Geon", "Deemer", "Sephinroth", "Darkstorn"], 88, "wl")
HERO_MAP.extend(
    [
        {"sid": "homm3_dungeon_hero_17", "name": "Mutare", "classType": "magic", "source": lod_source("hpl007sh.pcx")},
        {"sid": "homm3_dungeon_hero_18", "name": "Mutare Drake", "classType": "magic", "source": lod_source("hpl008sh.pcx")},
    ]
)

# Keep the established Stronghold order because generated Stronghold Core rows
# already use this custom sequence.
HERO_MAP.extend(
    [
        {"sid": "homm3_stronghold_hero_1", "name": "Crag Hack", "classType": "might", "source": lod_source("hpl102br.pcx")},
        {"sid": "homm3_stronghold_hero_2", "name": "Gurnisson", "classType": "might", "source": lod_source("hpl097br.pcx")},
        {"sid": "homm3_stronghold_hero_3", "name": "Jabarkas", "classType": "might", "source": lod_source("hpl098br.pcx")},
        {"sid": "homm3_stronghold_hero_4", "name": "Shiva", "classType": "might", "source": lod_source("hpl099br.pcx")},
        {"sid": "homm3_stronghold_hero_5", "name": "Yog", "classType": "might", "source": lod_source("hpl096br.pcx")},
        {"sid": "homm3_stronghold_hero_6", "name": "Boragus", "classType": "might", "source": lod_source("hpl100br.pcx")},
        {"sid": "homm3_stronghold_hero_7", "name": "Oris", "classType": "magic", "source": lod_source("hpl110bm.pcx")},
        {"sid": "homm3_stronghold_hero_8", "name": "Krellion", "classType": "might", "source": lod_source("hpl101br.pcx")},
        {"sid": "homm3_stronghold_hero_9", "name": "Tyraxor", "classType": "might", "source": lod_source("hpl103br.pcx")},
        {"sid": "homm3_stronghold_hero_10", "name": "Gird", "classType": "magic", "source": lod_source("hpl104bm.pcx")},
        {"sid": "homm3_stronghold_hero_11", "name": "Vey", "classType": "magic", "source": lod_source("hpl105bm.pcx")},
        {"sid": "homm3_stronghold_hero_12", "name": "Gundula", "classType": "magic", "source": lod_source("hpl109bm.pcx")},
        {"sid": "homm3_stronghold_hero_13", "name": "Zubin", "classType": "magic", "source": lod_source("hpl108bm.pcx")},
        {"sid": "homm3_stronghold_hero_14", "name": "Terek", "classType": "magic", "source": lod_source("hpl107bm.pcx")},
        {"sid": "homm3_stronghold_hero_15", "name": "Dessa", "classType": "magic", "source": lod_source("hpl106bm.pcx")},
        {"sid": "homm3_stronghold_hero_16", "name": "Saurug", "classType": "magic", "source": lod_source("hpl111bm.pcx")},
        {"sid": "homm3_stronghold_hero_17", "name": "Kilgor", "classType": "might", "source": lod_source("hpl005sh.pcx")},
        {"sid": "homm3_stronghold_hero_18", "name": "Zog", "classType": "magic", "source": hota_hero_png("stronghold", "zog")},
    ]
)

add_rows(HERO_MAP, "fortress", 1, "might", ["Bron", "Drakon", "Wystan", "Tazar", "Alkin", "Korbac", "Gerwulf", "Broghild"], 112, "bs")
add_rows(HERO_MAP, "fortress", 9, "magic", ["Mirlanda", "Rosic", "Voy", "Verdish", "Merist", "Styg", "Andra", "Tiva"], 120, "wh")
HERO_MAP.extend(
    [
        {"sid": "homm3_fortress_hero_17", "name": "Adrienne", "classType": "magic", "source": lod_source("hpl000sh.pcx")},
        {"sid": "homm3_fortress_hero_18", "name": "Kinkeria", "classType": "magic", "source": hota_hero_png("fortress", "kinkeria")},
    ]
)
add_rows(HERO_MAP, "conflux", 1, "might", ["Pasis", "Thunar", "Ignissa", "Lacus", "Monere", "Erdamon", "Fiur", "Kalt"], 0, "pl")
add_rows(HERO_MAP, "conflux", 9, "magic", ["Luna", "Brissa", "Ciele", "Labetha", "Inteus", "Aenain", "Gelare", "Grindan"], 0, "el")

for index, hero in enumerate(
    [
        ("corkes", "Corkes", "might"),
        ("jeremy", "Jeremy", "might"),
        ("illor", "Illor", "might"),
        ("elmore", "Elmore", "might"),
        ("derek", "Derek", "might"),
        ("leena", "Leena", "might"),
        ("anabel", "Anabel", "might"),
        ("cassiopeia", "Cassiopeia", "might"),
        ("casmetra", "Casmetra", "magic"),
        ("eovacius", "Eovacius", "magic"),
        ("spint", "Spint", "magic"),
        ("andal", "Andal", "magic"),
        ("manfred", "Manfred", "magic"),
        ("zilare", "Zilare", "magic"),
        ("astra", "Astra", "magic"),
        ("dargem", "Dargem", "magic"),
        ("balfour", "Balfour", "magic"),
        ("miriam", "Miriam", "might"),
    ],
    start=1,
):
    config_name, hero_name, class_type = hero
    HERO_MAP.append(
        {
            "sid": f"homm3_cove_hero_{index}",
            "name": hero_name,
            "classType": class_type,
            "source": cove_hero_png(config_name),
        }
    )

DEBT_NOTES = [
    "Conflux remains at 16 unique roster heroes; AB multi-protagonist hub still needs per-mission hero binding beyond a single hub heroSid.",
    "Castle slots 17-18 are now Catherine/Roland (campaign leads) instead of HotA Sir Mullich/Beatrice.",
    "Inferno slot 17 is Xeron instead of HotA Athe; Miseria retained as slot 18.",
    "Stronghold slot 17 is Kilgor instead of HotA Gruezak; Zog retained as slot 18.",
    "Necropolis slots 17-18 are Finneas/Haart Lich instead of HotA Boyd/Ranloo.",
    "Fortress slot 18 uses HotA Kinkeria so Adrienne can occupy slot 17 under the 16-or-18 validator.",
    "General Kendal and Bidley/Tark remain portrait-only / excluded until a free castle or cove slot policy is chosen.",
    "Cove local HotA configs bidley and tark remain intentionally not emitted because custom_factions/homm3_cove.json excludes them from the 18-slot manifest.",
]


def extract_from_lod(lod_path, want_name_lower):
    """Extract a single entry from a Heroes III .lod archive.
    Each entry is 32 bytes total: 16 bytes filename + 16 bytes metadata, interleaved."""
    data = lod_path.read_bytes()
    if data[:4] != b"LOD\0":
        return None
    total = struct.unpack_from("<I", data, 8)[0]
    off = 92  # header size
    entry_stride = 32  # 16 bytes name + 16 bytes metadata per entry

    files = []
    for _ in range(total):
        raw = data[off : off + 16]
        off += 16
        nul = raw.find(b"\x00")
        name = (raw[:nul] if nul >= 0 else raw).decode("ascii", errors="replace").lower()
        file_off, file_size, _u, file_csize = struct.unpack_from("<IIII", data, off)
        off += 16
        files.append((name, file_off, file_size, file_csize))

    for name, file_off, file_size, file_csize in files:
        if name != want_name_lower:
            continue
        # Found it
        if file_csize and file_csize != file_size:
            blob = data[file_off : file_off + file_csize]
            try:
                blob = zlib.decompress(blob)
            except zlib.error:
                blob = data[file_off : file_off + file_size]
        else:
            blob = data[file_off : file_off + file_size]
        return blob
    return None


def apply_circular_alpha(img):
    """Pad the HoMM3 portrait to a square and mask transparent circular corners."""
    from PIL import Image, ImageDraw

    source = img.convert("RGBA")
    side = max(source.size)
    canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    canvas.alpha_composite(source, ((side - source.width) // 2, (side - source.height) // 2))

    scale = 4
    mask = Image.new("L", (side * scale, side * scale), 0)
    draw = ImageDraw.Draw(mask)
    inset = scale
    draw.ellipse((inset, inset, side * scale - inset - 1, side * scale - inset - 1), fill=255)
    resample = getattr(Image.Resampling, "LANCZOS", Image.LANCZOS)
    mask = mask.resize((side, side), resample)

    alpha = canvas.getchannel("A")
    alpha = Image.composite(alpha, Image.new("L", (side, side), 0), mask)
    canvas.putalpha(alpha)
    return canvas


def decode_h3_portrait_payload(data):
    """Decode HoMM3's custom large-portrait payload into a Pillow image."""
    from PIL import Image

    if len(data) < 12:
        return None
    payload_len, width, height = struct.unpack_from("<III", data, 0)
    if width < 1 or width > 256 or height < 1 or height > 256:
        return None
    pixel_len = width * height
    expected = 12 + pixel_len + 768
    if payload_len != pixel_len or len(data) < expected:
        return None

    pixels = data[12 : 12 + pixel_len]
    palette = data[12 + pixel_len : 12 + pixel_len + 768]
    rgba = bytearray(pixel_len * 4)
    for i, idx in enumerate(pixels):
        po = idx * 3
        ro = i * 4
        rgba[ro] = palette[po]
        rgba[ro + 1] = palette[po + 1]
        rgba[ro + 2] = palette[po + 2]
        rgba[ro + 3] = 255
    return Image.frombytes("RGBA", (width, height), bytes(rgba))


def pcx_to_png(pcx_bytes, out_path):
    """Convert HoMM3 portrait bytes to circular-alpha PNG."""
    img = decode_h3_portrait_payload(pcx_bytes)
    if img is None:
        return False, "unsupported HoMM3 portrait payload"

    return image_to_png(img, out_path)


def png_to_png(source_path, out_path):
    """Normalize a source PNG to the circular-alpha hero portrait contract."""
    from PIL import Image

    with Image.open(source_path) as img:
        return image_to_png(img, out_path)


def image_to_png(img, out_path):
    """Resize/pad source art to 64x64 and write circular-alpha PNG."""
    from PIL import Image

    source_size = img.size
    img = apply_circular_alpha(img)
    if img.size != (64, 64):
        resample = getattr(Image.Resampling, "LANCZOS", Image.LANCZOS)
        img = img.resize((64, 64), resample)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path, "PNG")
    return True, {"sourceSize": source_size, "size": img.size, "circularAlpha": True}


def describe_source(source):
    if source["kind"] == "lod":
        return source["pcx"]
    try:
        return str(source["path"])
    except KeyError:
        return str(source)


def source_manifest_value(source):
    if source["kind"] == "lod":
        return {"kind": "lod", "pcx": source["pcx"]}
    root = source["root"]
    try:
        root_value = str(root.resolve().relative_to(ROOT))
    except ValueError:
        root_value = str(root)
    return {"kind": "png", "root": root_value, "path": source["path"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lod", type=Path, default=DEFAULT_LOD_PATH, help="Path to H3bitmap.lod")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT_DIR, help="Output directory for source PNGs")
    args = parser.parse_args()
    lod_path = args.lod
    out_dir = args.out

    if not lod_path.exists():
        print(f"ERROR: LOD not found: {lod_path}", file=sys.stderr)
        return 1

    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        manifest_source = str(lod_path.resolve().relative_to(ROOT))
    except ValueError:
        manifest_source = str(lod_path)
    manifest = {
        "sources": {
            "lod": manifest_source,
            "hotaHeroes": str(HOTA_HEROES_ROOT.resolve().relative_to(ROOT)) if HOTA_HEROES_ROOT.exists() else str(HOTA_HEROES_ROOT),
            "hotaCove": str(HOTA_COVE_ROOT.resolve().relative_to(ROOT)) if HOTA_COVE_ROOT.exists() else str(HOTA_COVE_ROOT),
        },
        "entries": {},
        "debt": DEBT_NOTES,
        "missing": [],
    }
    ok = 0

    for row_index, row in enumerate(HERO_MAP, start=1):
        sid = row["sid"]
        hero_name = row["name"]
        class_type = row["classType"]
        source = row["source"]
        source_desc = describe_source(source)
        sys.stdout.write(f"  [{row_index:3d}] {sid:28s} <- {source_desc} ")
        sys.stdout.flush()

        png_path = out_dir / f"{sid}.png"
        source_info = source_manifest_value(source)
        if source["kind"] == "lod":
            pcx_bytes = extract_from_lod(lod_path, source["pcx"])
            if pcx_bytes is None:
                print("MISSING")
                manifest["missing"].append({"sid": sid, "name": hero_name, "source": source_info, "reason": "lod_entry_missing"})
                continue
            success, info = pcx_to_png(pcx_bytes, png_path)
        elif source["kind"] == "png":
            source_path = source["root"] / source["path"]
            if not source_path.exists():
                print("MISSING")
                manifest["missing"].append({"sid": sid, "name": hero_name, "source": source_info, "reason": "png_source_missing"})
                continue
            success, info = png_to_png(source_path, png_path)
        else:
            print("FAIL: unknown source kind")
            manifest["missing"].append({"sid": sid, "name": hero_name, "source": source_info, "reason": "unknown_source_kind"})
            continue

        if success:
            source_note = f", alias of {source['aliasOf']}" if source.get("aliasOf") else ""
            print(f"OK ({info['size'][0]}x{info['size'][1]}, circular alpha{source_note})")
            manifest["entries"][sid] = {
                "source": source_info,
                "name": hero_name,
                "classType": class_type,
                "sourceSize": list(info["sourceSize"]),
                "size": list(info["size"]),
                "circularAlpha": True,
            }
            if source.get("aliasOf"):
                manifest["entries"][sid]["sourceAliasOf"] = source["aliasOf"]
            ok += 1
        else:
            print(f"FAIL: {info}")
            manifest["missing"].append({"sid": sid, "name": hero_name, "source": source_info, "reason": str(info)})

    manifest_path = out_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent="\t"),
        encoding="utf-8",
    )
    print(f"\nExtracted {ok}/{len(HERO_MAP)} portraits")
    if manifest["missing"]:
        print(f"Missing/unmapped: {len(manifest['missing'])}")
    print(f"Output: {out_dir}")
    print(f"Manifest: {manifest_path}")
    return 0 if ok == len(HERO_MAP) else 1


if __name__ == "__main__":
    raise SystemExit(main())
