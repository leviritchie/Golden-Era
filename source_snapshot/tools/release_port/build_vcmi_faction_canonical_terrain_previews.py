#!/usr/bin/env python3
from __future__ import annotations

import json
import random
import struct
import subprocess
import zlib
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
LOD_PATH = ROOT / "vcmi" / "Data" / "H3sprite.lod"
DEFEXTRACT = ROOT / "tools" / "defextract_py3.py"
OUT_ROOT = ROOT / "artifacts" / "custom_biome_work" / "homm3_faction_terrain_sim"
DEFS_ROOT = OUT_ROOT / "defs"

# Canonical HoMM3 faction native terrain -> terrain DEF
FACTION_TERRAIN_DEF = {
    "homm3_castle": "grastl.def",      # Grass
    "homm3_rampart": "grastl.def",     # Grass
    "homm3_conflux": "grastl.def",     # Grass
    "homm3_tower": "snowtl.def",       # Snow
    "homm3_fortress": "swmptl.def",    # Swamp
    "homm3_inferno": "lavatl.def",     # Lava
    "homm3_necropolis": "dirttl.def",  # Dirt
    "homm3_stronghold": "rougtl.def",  # Rough
    "homm3_dungeon": "rocktl.def",     # Subterranean
    "homm3_cove": "swmptl.def",        # HotA Cove native terrain is Swamp
}


def extract_lod_member(lod_path: Path, member_name: str, out_path: Path) -> None:
    with lod_path.open("rb") as f:
        if f.read(4) != b"LOD\x00":
            raise RuntimeError(f"not a LOD file: {lod_path}")
        f.seek(8)
        total = struct.unpack("<I", f.read(4))[0]
        f.seek(92)
        target = member_name.lower()
        for _ in range(total):
            raw_name = struct.unpack("16s", f.read(16))[0]
            name = raw_name.split(b"\x00", 1)[0].decode("ascii", "ignore").lower()
            offset, size, _, csize = struct.unpack("<IIII", f.read(16))
            if name != target:
                continue
            f.seek(offset)
            data = zlib.decompress(f.read(csize)) if csize else f.read(size)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_bytes(data)
            return
    raise FileNotFoundError(f"{member_name} not found in {lod_path}")


def tile_mean_rgb(path: Path) -> tuple[float, float, float]:
    img = Image.open(path).convert("RGBA")
    px = img.load()
    w, h = img.size
    sr = sg = sb = n = 0
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            if a < 8:
                continue
            sr += r
            sg += g
            sb += b
            n += 1
    if n == 0:
        return (0.0, 0.0, 0.0)
    return (sr / n, sg / n, sb / n)


def tile_transition_score(path: Path) -> float:
    """Lower is better for base tiles; higher usually indicates transition edges."""
    img = Image.open(path).convert("RGBA")
    px = img.load()
    w, h = img.size
    if w < 6 or h < 6:
        return 0.0
    # 1px border ring vs center region.
    border = []
    center = []
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            if a < 8:
                continue
            if x == 0 or y == 0 or x == w - 1 or y == h - 1:
                border.append((r, g, b))
            elif 1 < x < w - 2 and 1 < y < h - 2:
                center.append((r, g, b))
    if not border or not center:
        return 0.0
    br = sum(c[0] for c in border) / len(border)
    bg = sum(c[1] for c in border) / len(border)
    bb = sum(c[2] for c in border) / len(border)
    cr = sum(c[0] for c in center) / len(center)
    cg = sum(c[1] for c in center) / len(center)
    cb = sum(c[2] for c in center) / len(center)
    # Color divergence between border and center (Euclidean RGB distance).
    return ((br - cr) ** 2 + (bg - cg) ** 2 + (bb - cb) ** 2) ** 0.5


def best_base_tile_paths(frame_paths: list[Path]) -> tuple[list[Path], dict[str, float]]:
    stats = [(p, *tile_mean_rgb(p), tile_transition_score(p)) for p in frame_paths]
    if not stats:
        return [], {}
    lum = [0.299 * r + 0.587 * g + 0.114 * b for _, r, g, b, _ in stats]
    avg = sum(lum) / len(lum)
    tr_scores = [t for _, _, _, _, t in stats]
    tr_avg = sum(tr_scores) / len(tr_scores)
    tr_cut = tr_avg * 1.10
    kept = [
        p
        for (p, r, g, b, t), l in zip(stats, lum)
        if (avg * 0.70 <= l <= avg * 1.35) and t <= tr_cut
    ]
    if not kept:
        kept = [p for p, _, _, _, t in stats if t <= tr_cut]
    if not kept:
        kept = [p for p, _, _, _, _t in stats]
    meta = {
        "avgLuma": avg,
        "avgTransitionScore": tr_avg,
        "transitionCutoff": tr_cut,
    }
    return kept, meta


def legacy_best_base_tile_paths(frame_paths: list[Path]) -> list[Path]:
    stats = [(p, *tile_mean_rgb(p)) for p in frame_paths]
    if not stats:
        return []
    lum = [0.299 * r + 0.587 * g + 0.114 * b for _, r, g, b in stats]
    avg = sum(lum) / len(lum)
    kept = [p for (p, r, g, b), l in zip(stats, lum) if l >= avg * 0.70 and l <= avg * 1.35]
    return kept or [p for p, _, _, _ in stats]


def build_sim(tile_paths: list[Path], out_256: Path, out_512: Path, seed: int) -> None:
    rng = random.Random(seed)
    tiles = [Image.open(p).convert("RGBA") for p in tile_paths]
    tw, th = tiles[0].size
    cols = 256 // tw
    rows = 256 // th
    canvas = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
    for y in range(rows):
        for x in range(cols):
            t = rng.choice(tiles)
            canvas.paste(t, (x * tw, y * th), t)
    out_256.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out_256)
    canvas.resize((512, 512), Image.Resampling.NEAREST).save(out_512)


def select_frame_range(frame_paths: list[Path], start_idx: int, end_idx: int) -> list[Path]:
    selected: list[Path] = []
    for p in frame_paths:
        stem = p.stem  # e.g. 00_57
        parts = stem.split("_")
        if len(parts) != 2:
            continue
        try:
            idx = int(parts[1])
        except ValueError:
            continue
        if start_idx <= idx <= end_idx:
            selected.append(p)
    return selected


def ensure_def_frames(def_name: str) -> tuple[Path, Path]:
    def_path = DEFS_ROOT / def_name
    terrain_dir = OUT_ROOT / f"{def_name[:-4]}.dir"
    terrain_json = OUT_ROOT / f"{def_name[:-4]}.json"
    if not def_path.exists():
        extract_lod_member(LOD_PATH, def_name, def_path)
    if not terrain_dir.exists() or not terrain_json.exists():
        subprocess.check_call(["python", str(DEFEXTRACT), str(def_path), str(OUT_ROOT)], cwd=str(ROOT))
    return terrain_dir, terrain_json


def run() -> None:
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, dict[str, object]] = {}
    for faction, def_name in FACTION_TERRAIN_DEF.items():
        terrain_dir, terrain_json = ensure_def_frames(def_name)
        data = json.loads(terrain_json.read_text(encoding="utf-8"))
        frames: list[Path] = []
        for seq in data.get("sequences", []):
            for rel in seq.get("frames", []):
                p = OUT_ROOT / rel
                if p.exists():
                    frames.append(p)
        base_frames, filter_meta = best_base_tile_paths(frames)
        range_frames = select_frame_range(frames, 49, 68)
        all_frames = frames[:]
        out_raw_256 = OUT_ROOT / f"{faction}_sim_raw_all_256.png"
        out_raw_512 = OUT_ROOT / f"{faction}_sim_raw_all_512_nn2x.png"
        build_sim(all_frames, out_raw_256, out_raw_512, seed=((hash(faction) ^ 0xABCDEF) & 0xFFFFFFFF))
        if not range_frames:
            range_frames = all_frames
        out_range_256 = OUT_ROOT / f"{faction}_sim_range49_68_256.png"
        out_range_512 = OUT_ROOT / f"{faction}_sim_range49_68_512_nn2x.png"
        build_sim(range_frames, out_range_256, out_range_512, seed=((hash(faction) ^ 0x4972) & 0xFFFFFFFF))
        out_256 = OUT_ROOT / f"{faction}_sim_base_256.png"
        out_512 = OUT_ROOT / f"{faction}_sim_base_512_nn2x.png"
        build_sim(base_frames, out_256, out_512, seed=(hash(faction) & 0xFFFFFFFF))
        manifest[faction] = {
            "terrainDef": def_name,
            "frameCount": len(frames),
            "baseFrameCount": len(base_frames),
            "range49to72FrameCount": len(range_frames),
            "filterMeta": filter_meta,
            "previewRawAll256": str(out_raw_256),
            "previewRawAll512": str(out_raw_512),
            "previewRange49to68_256": str(out_range_256),
            "previewRange49to68_512": str(out_range_512),
            "preview256": str(out_256),
            "preview512": str(out_512),
            "framesDir": str(terrain_dir),
        }
    (OUT_ROOT / "faction_preview_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    run()
