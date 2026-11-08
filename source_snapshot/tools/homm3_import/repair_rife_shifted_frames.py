#!/usr/bin/env python3
"""Repair dense RIFE frames when remove_old_frame_files deleted the first N outputs.

After a re-interpolation bug, groups can have only frames {group}_{sourceCount:04d}.png
through {group}_{outputCount-1:04d}.png on disk while the manifest expects 0000..N-1.
This renames down by sourceCount and pads the tail by duplicating the last frame.
"""
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LAB = (
    REPO_ROOT / "Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/homm3_lab"
)
DONE_META_NAME = ".rife120_done.json"


def find_battle_manifest(battle_dir: Path) -> Path | None:
    for path in sorted(battle_dir.glob("*.json")):
        if path.name.startswith(".") or path.name.lower() == "manifest.json":
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
        except json.JSONDecodeError:
            continue
        if isinstance(data.get("sequences"), list):
            return path
    return None


def repair_group(
    battle_dir: Path,
    dir_name: str,
    group_id: int,
    *,
    source_count: int,
    output_count: int,
    dry_run: bool,
) -> bool:
    group_dir = battle_dir / dir_name
    if not group_dir.is_dir():
        return False
    prefix = f"{group_id:02d}_"
    existing = sorted(group_dir.glob(f"{prefix}*.png"))
    if not existing:
        return False
    first_idx = int(existing[0].stem.split("_", 1)[1])
    if first_idx == 0 and len(existing) >= output_count:
        return False
    if first_idx != source_count:
        print(
            f"  group {group_id}: skip (first={first_idx}, expected shift={source_count})"
        )
        return False
    have = len(existing)
    need = output_count
    if have + first_idx != need:
        print(f"  group {group_id}: WARN have={have} first={first_idx} need={need}")
    print(f"  group {group_id}: shift {have} frames down by {first_idx}, pad to {need}")
    if dry_run:
        return True
    temp_dir = group_dir / f".repair_g{group_id:02d}_tmp"
    if temp_dir.exists():
        shutil.rmtree(temp_dir)
    temp_dir.mkdir()
    for i, src in enumerate(existing):
        dst = temp_dir / f"{prefix}{i:04d}.png"
        shutil.move(src, dst)
    for i in range(have, need):
        dst = temp_dir / f"{prefix}{i:04d}.png"
        shutil.copy2(temp_dir / f"{prefix}{have - 1:04d}.png", dst)
    for path in temp_dir.glob("*.png"):
        shutil.move(path, group_dir / path.name)
    temp_dir.rmdir()
    return True


def repair_unit(unit_sid: str, lab_root: Path, *, dry_run: bool) -> int:
    battle_dir = lab_root / unit_sid / "extracted_battle"
    meta_path = battle_dir / DONE_META_NAME
    if not meta_path.is_file():
        print(f"  skip {unit_sid}: no {DONE_META_NAME}")
        return 0
    meta = json.loads(meta_path.read_text(encoding="utf-8-sig"))
    groups = meta.get("groups") or {}
    manifest_path = find_battle_manifest(battle_dir)
    manifest = (
        json.loads(manifest_path.read_text(encoding="utf-8-sig"))
        if manifest_path
        else None
    )
    fixed = 0
    for key, info in sorted(groups.items(), key=lambda kv: int(kv[0])):
        if not info.get("interpolated"):
            continue
        group_id = int(key)
        source_count = int(info.get("sourceCount") or 0)
        output_count = int(info.get("outputCount") or 0)
        dir_name = str(info.get("dir") or "").strip()
        if not dir_name or source_count <= 0 or output_count <= 0:
            continue
        if repair_group(
            battle_dir,
            dir_name,
            group_id,
            source_count=source_count,
            output_count=output_count,
            dry_run=dry_run,
        ):
            fixed += 1
            if manifest and manifest_path:
                for seq in manifest.get("sequences") or []:
                    if int(seq.get("group", -1)) != group_id:
                        continue
                    seq["frames"] = [
                        f"{dir_name}\\{group_id:02d}_{i:04d}.png"
                        for i in range(output_count)
                    ]
    if manifest and manifest_path and fixed and not dry_run:
        manifest_path.write_text(json.dumps(manifest, indent=4) + "\n", encoding="utf-8")
    return fixed


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lab-root", type=Path, default=DEFAULT_LAB)
    ap.add_argument("--units", nargs="+", required=True)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    total = 0
    for sid in args.units:
        print(sid)
        total += repair_unit(sid, args.lab_root.resolve(), dry_run=args.dry_run)
    print(f"Repaired {total} group(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
