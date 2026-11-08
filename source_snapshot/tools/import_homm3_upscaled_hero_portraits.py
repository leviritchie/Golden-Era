#!/usr/bin/env python3
"""Import upscaled HoMM3 hero portrait batches from Downloads zips into homm3_hero_portraits_upscaled/.

Discovers all homm3_batch*.zip files, merges by batch number (higher-quality / newer variants win per file),
and writes PNGs with source alpha preserved (no matte strip, remapping, or canonical upscale).
"""

from __future__ import annotations

import argparse
import io
import json
import re
import shutil
import sys
import zipfile
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DOWNLOADS = Path.home() / "Downloads"
DEFAULT_ORIGINAL = (
    ROOT
    / "Heroes of Might & Magic Olden Era Playtest"
    / "OfflineUnlockMod"
    / "homm3_hero_portraits"
)
DEFAULT_OUT = (
    ROOT
    / "Heroes of Might & Magic Olden Era Playtest"
    / "OfflineUnlockMod"
    / "homm3_hero_portraits_upscaled"
)

SID_RE = re.compile(r"^homm3_([a-z]+)_hero_(\d+)\.png$", re.IGNORECASE)
BATCH_RE = re.compile(r"homm3_batch(\d+)", re.IGNORECASE)

# Higher score wins when multiple zips in the same batch provide the same hero file.
VARIANT_PRIORITY = (
    ("real_alpha", 60),
    ("corrected", 50),
    ("traditional_fix", 45),
    ("revised", 40),
    ("transparent", 30),
    ("upscaled", 10),
)


def expected_sids() -> list[str]:
    custom_factions = ROOT / "custom_factions"
    sids: list[str] = []
    for path in sorted(custom_factions.glob("homm3_*.json")):
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        faction = path.stem.removeprefix("homm3_")
        hero_count = int((data.get("heroes") or {}).get("count") or 18)
        sids.extend(f"homm3_{faction}_hero_{index}" for index in range(1, hero_count + 1))
    return sids


def variant_score(zip_name: str) -> int:
    lowered = zip_name.lower()
    score = 0
    for marker, value in VARIANT_PRIORITY:
        if marker in lowered:
            score = max(score, value)
    return score


def discover_batch_zips(downloads_dir: Path) -> dict[int, list[Path]]:
    batches: dict[int, list[Path]] = defaultdict(list)
    for zip_path in sorted(downloads_dir.glob("homm3_batch*.zip")):
        match = BATCH_RE.search(zip_path.name)
        if not match:
            continue
        batches[int(match.group(1))].append(zip_path)
    if not batches:
        raise FileNotFoundError(f"No homm3_batch*.zip files found in {downloads_dir}")
    return batches


def merge_zips(downloads_dir: Path) -> tuple[dict[str, tuple[str, bytes]], list[dict]]:
    """Merge every batch zip; within a batch, lower-priority/older zips first, best/newest last."""
    merged: dict[str, tuple[str, bytes]] = {}
    merge_log: list[dict] = []

    batches = discover_batch_zips(downloads_dir)
    for batch_num in sorted(batches):
        zip_paths = batches[batch_num]
        ordered = sorted(
            zip_paths,
            key=lambda path: (variant_score(path.name), path.stat().st_mtime),
        )
        for zip_path in ordered:
            with zipfile.ZipFile(zip_path) as zf:
                for name in zf.namelist():
                    if not name.lower().endswith(".png"):
                        continue
                    filename = Path(name).name
                    if not SID_RE.match(filename):
                        continue
                    previous = merged.get(filename)
                    merged[filename] = (zip_path.name, zf.read(name))
                    if previous and previous[0] != zip_path.name:
                        merge_log.append(
                            {
                                "file": filename,
                                "batch": batch_num,
                                "replaced": previous[0],
                                "winner": zip_path.name,
                            }
                        )
    return merged, merge_log


def corner_alpha_stats(img) -> dict:
    from PIL import Image

    rgba = img.convert("RGBA")
    w, h = rgba.size
    corners = [
        rgba.getpixel((0, 0)),
        rgba.getpixel((w - 1, 0)),
        rgba.getpixel((0, h - 1)),
        rgba.getpixel((w - 1, h - 1)),
    ]
    alphas = [c[3] for c in corners]
    return {
        "cornerAlphaMin": min(alphas),
        "cornerAlphaMax": max(alphas),
        "cornerAlphaMean": round(sum(alphas) / len(alphas), 2),
    }


def process_hero(sid: str, zip_name: str, payload: bytes) -> tuple[bytes, dict]:
    from PIL import Image

    with Image.open(io.BytesIO(payload)) as img:
        source_mode = img.mode
        source_size = img.size
        rgba = img.convert("RGBA")
        out_buf = io.BytesIO()
        rgba.save(out_buf, format="PNG")

        meta = {
            "sid": sid,
            "sourceZip": zip_name,
            "sourceMode": source_mode,
            "sourceSize": list(source_size),
            "outputSize": list(rgba.size),
            "transform": "passthrough",
            **corner_alpha_stats(rgba),
        }
        return out_buf.getvalue(), meta


def write_manifest_copy(original_dir: Path, out_dir: Path) -> None:
    src = original_dir / "manifest.json"
    dst = out_dir / "manifest.json"
    if not src.exists():
        raise FileNotFoundError(f"Missing source manifest: {src}")
    manifest = json.loads(src.read_text(encoding="utf-8-sig"))
    manifest["upscaledImport"] = {
        "source": "import_homm3_upscaled_hero_portraits.py",
        "originalPortraitDir": "homm3_hero_portraits",
        "transform": "passthrough",
        "note": "PNG alpha is taken from the merged batch zip as-is.",
    }
    dst.write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--downloads-dir", type=Path, default=DEFAULT_DOWNLOADS)
    parser.add_argument("--original-portraits-dir", type=Path, default=DEFAULT_ORIGINAL)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    merged, merge_log = merge_zips(args.downloads_dir)

    expected = expected_sids()
    missing = [sid for sid in expected if f"{sid}.png" not in merged]
    if missing:
        print("Import FAILED: missing heroes after zip merge:", file=sys.stderr)
        for sid in missing:
            print(f"  - {sid}.png", file=sys.stderr)
        return 1

    extra = sorted(set(merged) - {f"{sid}.png" for sid in expected})
    if extra:
        print(f"Note: ignoring {len(extra)} stale portrait(s) from zip merge outside the current roster")
        for name in extra:
            merged.pop(name, None)

    report_entries: list[dict] = []
    non_rgba: list[str] = []

    if not args.dry_run:
        if args.out_dir.exists():
            shutil.rmtree(args.out_dir)
        args.out_dir.mkdir(parents=True, exist_ok=True)

    for sid in expected:
        filename = f"{sid}.png"
        zip_name, payload = merged[filename]
        if args.dry_run:
            report_entries.append({"sid": sid, "sourceZip": zip_name, "dryRun": True})
            continue

        png_bytes, meta = process_hero(sid, zip_name, payload)
        (args.out_dir / filename).write_bytes(png_bytes)
        report_entries.append(meta)
        if meta["sourceMode"] != "RGBA":
            non_rgba.append(sid)

    if not args.dry_run:
        write_manifest_copy(args.original_portraits_dir, args.out_dir)

    report = {
        "heroCount": len(expected),
        "transform": "passthrough",
        "nonRgbaSources": non_rgba,
        "zipOverrides": merge_log,
        "entries": report_entries,
    }
    report_path = args.out_dir / "import_report.json"
    if not args.dry_run:
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(f"HoMM3 upscaled hero import OK: {len(expected)} heroes (passthrough)")
    print(f"  Zip file overrides within batch: {len(merge_log)}")
    if non_rgba:
        print(f"  WARNING: {len(non_rgba)} hero(es) still RGB in winning zip (no alpha channel):")
        for sid in non_rgba[:10]:
            entry = next(item for item in report_entries if item["sid"] == sid)
            print(f"    - {sid}: {entry['sourceZip']}")
        if len(non_rgba) > 10:
            print(f"    ... and {len(non_rgba) - 10} more")
    if args.dry_run:
        print("  (dry run — no files written)")
    else:
        print(f"  Output: {args.out_dir}")
        print(f"  Report: {report_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
