#!/usr/bin/env python3
"""Copy extracted_map/ (and optional authoring.json) from Unity homm3_lab into OfflineUnlockMod lab."""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OFFLINE_LAB = (
    REPO_ROOT / "Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/homm3_lab"
)
MAP_BACKUP = "extracted_map_source_10fps"
MAP_DONE = ".rife_map_done.json"


def sync_one(
    sid: str, unity_lab: Path, offline_lab: Path, *, copy_authoring: bool
) -> tuple[str, str]:
    src_unit = unity_lab / sid
    dst_unit = offline_lab / sid
    src_map = src_unit / "extracted_map"
    if not src_map.is_dir():
        return sid, "skip-no-map"
    dst_unit.mkdir(parents=True, exist_ok=True)
    dst_map = dst_unit / "extracted_map"
    if dst_map.exists():
        shutil.rmtree(dst_map)
    shutil.copytree(
        src_map,
        dst_map,
        ignore=shutil.ignore_patterns(MAP_BACKUP, MAP_DONE, "*.meta"),
    )
    src_done = src_map / MAP_DONE
    if src_done.is_file():
        shutil.copy2(src_done, dst_map / MAP_DONE)
    if copy_authoring:
        src_auth = src_unit / "authoring.json"
        if src_auth.is_file():
            shutil.copy2(src_auth, dst_unit / "authoring.json")
    return sid, "ok"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--unity-project", type=Path, required=True)
    ap.add_argument("--offline-lab", type=Path, default=DEFAULT_OFFLINE_LAB)
    ap.add_argument("--units", nargs="+", required=True)
    ap.add_argument(
        "--copy-authoring",
        action="store_true",
        help="Also copy authoring.json (mapFlipBookFps is updated after RIFE)",
    )
    args = ap.parse_args()

    unity_lab = args.unity_project.resolve() / "Assets" / "CustomUnits" / "homm3_lab"
    offline_lab = args.offline_lab.resolve()
    if not unity_lab.is_dir():
        print(f"Missing Unity lab: {unity_lab}", file=sys.stderr)
        return 1

    ok = 0
    for sid in args.units:
        sid, status = sync_one(
            sid.strip(),
            unity_lab,
            offline_lab,
            copy_authoring=args.copy_authoring,
        )
        print(f"  {sid}: {status}")
        if status == "ok":
            ok += 1
    print(f"Synced map lab data for {ok}/{len(args.units)} unit(s) -> {offline_lab}")
    return 0 if ok == len(args.units) else 1


if __name__ == "__main__":
    raise SystemExit(main())
