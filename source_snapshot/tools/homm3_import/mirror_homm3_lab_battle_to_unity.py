#!/usr/bin/env python3
"""Bulk-copy OfflineUnlockMod homm3_lab battle frames + authoring into Unity Assets/homm3_lab."""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LAB = (
    REPO_ROOT / "Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/homm3_lab"
)
DEFAULT_MANIFEST = Path(__file__).resolve().parent / "homm3_units_manifest.json"
BATTLE_BACKUP_DIR_NAME = "extracted_battle_source_12fps"
MAP_BACKUP_DIR_NAME = "extracted_map_source_10fps"
MAP_DONE_META = ".rife_map_done.json"


def manifest_sids(path: Path) -> list[str]:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    return sorted(
        {
            str(u.get("unitSid", "")).strip()
            for u in (data.get("units") or [])
            if str(u.get("unitSid", "")).strip()
        }
    )


def mirror_one(
    sid: str,
    lab_root: Path,
    unity_lab: Path,
    *,
    battle_only: bool,
    include_map: bool,
    map_only: bool,
) -> tuple[str, str]:
    src_unit = lab_root / sid
    dst_unit = unity_lab / sid
    has_battle = not map_only and (src_unit / "extracted_battle").is_dir()
    has_map = include_map and (src_unit / "extracted_map").is_dir()
    if not has_battle and not has_map:
        return sid, "skip-no-battle-or-map"
    dst_unit.mkdir(parents=True, exist_ok=True)
    if has_battle:
        src_battle = src_unit / "extracted_battle"
        dst_battle = dst_unit / "extracted_battle"
        if dst_battle.exists():
            shutil.rmtree(dst_battle)
        shutil.copytree(
            src_battle,
            dst_battle,
            ignore=shutil.ignore_patterns(BATTLE_BACKUP_DIR_NAME, "*.meta"),
        )
        for meta in dst_battle.rglob("*.meta"):
            meta.unlink(missing_ok=True)
    if has_map:
        src_map = src_unit / "extracted_map"
        dst_map = dst_unit / "extracted_map"
        if dst_map.exists():
            shutil.rmtree(dst_map)
        shutil.copytree(
            src_map,
            dst_map,
            ignore=shutil.ignore_patterns(MAP_BACKUP_DIR_NAME, MAP_DONE_META, "*.meta"),
        )
        src_done = src_map / MAP_DONE_META
        if src_done.is_file():
            shutil.copy2(src_done, dst_map / MAP_DONE_META)
        for meta in dst_map.rglob("*.meta"):
            meta.unlink(missing_ok=True)
    src_auth = src_unit / "authoring.json"
    if not battle_only and src_auth.is_file():
        shutil.copy2(src_auth, dst_unit / "authoring.json")
    return sid, "ok"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lab-root", type=Path, default=DEFAULT_LAB)
    ap.add_argument("--unity-project", type=Path, required=True)
    ap.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    ap.add_argument("--units", nargs="*", help="Default: all manifest unitSid with lab battle data")
    ap.add_argument("--unit-list", type=Path, help="Text file of unitSid rows")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--battle-only", action="store_true", help="Do not copy authoring.json")
    ap.add_argument(
        "--include-map",
        action="store_true",
        help="Also copy extracted_map/ (map RIFE pilot / full lab sync)",
    )
    ap.add_argument(
        "--map-only",
        action="store_true",
        help="Copy extracted_map + authoring only (skip battle tree)",
    )
    args = ap.parse_args()

    lab_root = args.lab_root.resolve()
    unity_lab = args.unity_project.resolve() / "Assets" / "CustomUnits" / "homm3_lab"
    if not unity_lab.parent.is_dir():
        print(f"Unity lab parent missing: {unity_lab.parent}", file=sys.stderr)
        return 1

    if args.unit_list:
        units = [
            line.strip()
            for line in args.unit_list.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
    else:
        units = args.units or manifest_sids(args.manifest)
    def unit_has_data(sid: str) -> bool:
        u = lab_root / sid
        if args.map_only:
            return (u / "extracted_map").is_dir()
        if args.include_map:
            return (u / "extracted_battle").is_dir() or (u / "extracted_map").is_dir()
        return (u / "extracted_battle").is_dir()

    units = [u for u in units if unit_has_data(u)]
    if not units:
        print("No units to mirror.", file=sys.stderr)
        return 1

    ok = 0
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futures = {
            pool.submit(
                mirror_one,
                sid,
                lab_root,
                unity_lab,
                battle_only=args.battle_only,
                include_map=args.include_map or args.map_only,
                map_only=args.map_only,
            ): sid
            for sid in units
        }
        for fut in as_completed(futures):
            sid, status = fut.result()
            if status == "ok":
                ok += 1
            else:
                print(f"  {sid}: {status}")

    what = "extracted_map" if args.map_only else "lab frames"
    if args.include_map and not args.map_only:
        what = "extracted_battle + extracted_map"
    elif not args.map_only:
        what = "extracted_battle"
    print(f"Mirrored {what} for {ok}/{len(units)} unit(s) -> {unity_lab}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
