#!/usr/bin/env python3
"""Remove leftover #14F30E chroma-plate green from painted unit portrait masters.

Why: the original key (_punch_pockets.py) only punched plate pockets that were NOT
connected to the border, so pockets reaching the exterior through a thin plate
corridor survived (demon, gog), and its despill left green fringe rims and green
bleed inside translucent areas (smoke, wings, manes). Lanczos to the 512 runtime
size then sharpens that fringe back toward neon.

Per master (artifacts/static_asset_painted_upscale/final/h3_*.png):
  1. punch: any visible near-plate pixel -> alpha 0, connected or not;
  2. edge despill: plate-hued green within EDGE_PX of transparency;
  3. interior despill: plate-hued green anywhere, except units whose art is
     genuinely green (NATURAL_GREEN), where only a stricter near-plate band is
     despilled.
Then the 512 runtime copy in OfflineUnlockMod/homm3_portraits is rewritten with
the same bytes recipe as generate_homm3_interface_portraits.py.
"""
from __future__ import annotations

import argparse
import io
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage as ndi

ROOT = Path(__file__).resolve().parents[1]
UPSCALE = ROOT / "artifacts" / "static_asset_painted_upscale"
MASTERS = UPSCALE / "final"
CONTRACT = UPSCALE / "RUNTIME_SIZE_CONTRACT.json"
PORTRAITS = ROOT / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod" / "homm3_portraits"

PLATE = np.array((0x14, 0xF3, 0x0E), dtype=np.float32)
PUNCH_DIST = 56.0
SPILL_DIST = 100.0
NATURAL_SPILL_DIST = 70.0
EDGE_PX = 6

# Creatures whose painted art contains real saturated greens (skin, scales,
# leaves, plumage, camo, wool). Interior greens are left alone on these.
NATURAL_GREEN = frozenset(
    {
        "h3_couatl", "h3_couatl_upg", "h3_couatl_upg_alt", "h3_crimson_couatl",
        "h3_serpent_fly", "h3_serpent_fly_upg", "h3_serpent_fly_upg_alt",
        "h3_elf_wardancer", "h3_elf_wardancer_upg", "h3_elf_wardancer_upg_alt",
        "h3_mountain_ram_upg_alt",
        "h3_lizardman", "h3_lizardman_upg", "h3_lizardman_upg_alt",
        "h3_dendroid_guard", "h3_dendroid_soldier", "h3_dendroid_shaman", "h3_dendroid_shaman_upg_alt",
        "h3_medusa", "h3_medusa_upg", "h3_medusa_upg_alt",
        "h3_walking_dead", "h3_walking_dead_upg", "h3_walking_dead_upg_alt",
        "h3_goblin", "h3_goblin_upg", "h3_goblin_upg_alt",
        "h3_green_dragon", "h3_green_dragon_upg", "h3_green_dragon_upg_alt",
        "h3_hydra", "h3_hydra_upg", "h3_hydra_upg_alt",
        "h3_wyvern", "h3_wyvern_upg", "h3_wyvern_upg_alt",
        "h3_basilisk", "h3_basilisk_upg", "h3_basilisk_upg_alt",
        "h3_wood_elf", "h3_grand_elf", "h3_sharpshooter",
        "h3_griffin_upg", "h3_griffin_upg_alt",
    }
)


# White / translucent subjects (smoke, bone, mane, wings) where the plate bled
# through as a pale green tint: also despill light greens off the plate hue.
PALE_TINT = frozenset(
    {
        "h3_genie", "h3_genie_upg", "h3_genie_upg_alt",
        "h3_bone_dragon_upg", "h3_bone_dragon_upg_alt",
        "h3_air_elemental", "h3_air_elemental_upg", "h3_air_elemental_upg_alt",
        "h3_war_unicorn", "h3_pristine_unicorn_upg_alt", "h3_silver_pegasus",
        "h3_sorceress", "h3_sea_witch", "h3_sea_witch_upg_alt",
    }
)
PALE_MIN_G = 150
PALE_MIN_EXCESS = 12
# Grey/white subjects with no green detail at all: dark plate streaks go too.
PALE_MIN_G_BY_SID = {"h3_bone_dragon_upg": 60, "h3_bone_dragon_upg_alt": 60, "h3_air_elemental": 60}


def plate_dist(rgb: np.ndarray) -> np.ndarray:
    return np.linalg.norm(rgb - PLATE, axis=2)


def plate_hue(rgb: np.ndarray) -> np.ndarray:
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    return (g >= 140) & (g >= r + 40) & (g >= b + 40)


def clean(rgba: np.ndarray, natural: bool, pale: bool = False, pale_min_g: int = PALE_MIN_G) -> tuple[np.ndarray, dict]:
    out = rgba.astype(np.float32).copy()
    rgb = out[..., :3]
    alpha = out[..., 3]
    d = plate_dist(rgb)
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    chroma = (g >= 160) & (g >= r + 50) & (g >= b + 50) & ((r + b) < 180)
    visible = alpha > 8

    punch = (d < PUNCH_DIST) & chroma & visible
    edge = ndi.binary_dilation((alpha < 128) | punch, iterations=EDGE_PX)
    hue = plate_hue(rgb) & visible & ~punch
    spill_edge = hue & edge & (d < SPILL_DIST)
    spill_int = hue & ~edge & (d < (NATURAL_SPILL_DIST if natural else SPILL_DIST))
    spill_pale = np.zeros_like(spill_int)
    if pale:
        spill_pale = visible & ~punch & ~spill_edge & ~spill_int & (g >= pale_min_g) & (
            g >= np.maximum(r, b) + PALE_MIN_EXCESS
        )
    spill = spill_edge | spill_int | spill_pale

    # Weighted despill: pull G down to max(R,B), return a little of the excess
    # to R/B so smoke and highlights keep their brightness.
    limit = np.maximum(r, b)
    excess = np.clip(g - limit, 0, None)
    w = np.clip((SPILL_DIST - d) / 40.0, 0.0, 1.0) * (spill_edge | spill_int)
    w = np.where(spill_pale, 1.0, w)
    g_new = g - w * excess
    r_new = np.clip(r + w * excess * 0.3, 0, 255)
    b_new = np.clip(b + w * excess * 0.3, 0, 255)
    out[..., 0], out[..., 1], out[..., 2] = r_new, g_new, b_new

    out[punch, 3] = 0
    out[out[..., 3] == 0, :3] = 0
    stats = {
        "punched": int(punch.sum()),
        "despillEdge": int(spill_edge.sum()),
        "despillInterior": int(spill_int.sum()),
        "despillPale": int(spill_pale.sum()),
    }
    return np.clip(np.rint(out), 0, 255).astype(np.uint8), stats


def runtime_bytes(master: Image.Image, max_side: int) -> bytes:
    side = min(max_side, master.width)
    im = master
    if im.size != (side, side):
        im = im.resize((side, side), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "PNG", optimize=True)
    return buf.getvalue()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--sid", action="append", help="limit to these sids")
    ap.add_argument("--backup-dir", type=Path, default=None)
    args = ap.parse_args()

    max_side = int(json.loads(CONTRACT.read_text())["runtime"]["unitPortraits"]["maxSidePx"])
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = args.backup_dir or (UPSCALE / f"live_backups_green_sweep_{stamp}")
    masters = sorted(MASTERS.glob("h3_*.png"))
    if args.sid:
        masters = [m for m in masters if m.stem in set(args.sid)]
    report = []
    for path in masters:
        sid = path.stem
        rgba = np.asarray(Image.open(path).convert("RGBA"))
        fixed, stats = clean(rgba, sid in NATURAL_GREEN, sid in PALE_TINT, PALE_MIN_G_BY_SID.get(sid, PALE_MIN_G))
        changed = not np.array_equal(fixed, rgba)
        stats.update(sid=sid, natural=sid in NATURAL_GREEN, changed=changed)
        report.append(stats)
        if not changed or args.dry_run:
            continue
        backup.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, backup / path.name)
        rt = PORTRAITS / path.name
        if rt.is_file():
            (backup / "runtime").mkdir(exist_ok=True)
            shutil.copy2(rt, backup / "runtime" / path.name)
        img = Image.fromarray(fixed, "RGBA")
        img.save(path, optimize=True)
        if rt.is_file():
            rt.write_bytes(runtime_bytes(img, max_side))
    changed = [r for r in report if r["changed"]]
    summary = {
        "generatedUtc": stamp,
        "dryRun": args.dry_run,
        "backup": None if args.dry_run else str(backup.relative_to(ROOT)).replace("\\", "/"),
        "mastersScanned": len(report),
        "mastersChanged": len(changed),
        "entries": sorted(changed, key=lambda r: -(r["punched"] + r["despillEdge"] + r["despillInterior"] + r["despillPale"])),
    }
    if not args.dry_run:
        (UPSCALE / "GREEN_SWEEP_REPORT.json").write_text(json.dumps(summary, indent=1))
    for r in summary["entries"][:40]:
        print(f'{r["sid"]:34s} punch={r["punched"]:6d} edge={r["despillEdge"]:5d} int={r["despillInterior"]:6d}{" natural" if r["natural"] else ""}')
    print(f'changed {len(changed)}/{len(report)}' + ("" if args.dry_run else f' backup={summary["backup"]}'))
    return 0


if __name__ == "__main__":
    sys.exit(main())
