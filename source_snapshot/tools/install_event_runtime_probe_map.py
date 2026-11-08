#!/usr/bin/env python3
"""Install the Event Runtime Probe into StreamingAssets/maps/ and merge Core overlay.

Policy: maps_root_custom_only (no Story_maps). Merges probe dialog + quickStart
overlay members into Core.zip. Does not replace campaign Story maps.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import zipfile
from datetime import datetime
from pathlib import Path

MAP_SID = "h3_event_runtime_probe"
DEFAULT_GAME_ROOT = Path(r"V:\SteamLibrary\steamapps\common\Heroes of Might and Magic Olden Era - Golden Era")
ARTIFACT_ROOT = Path("artifacts") / "campaign_port_poc" / "event_runtime_probe"
MAPS_ROOT_REL = Path("HeroesOldenEra_Data") / "StreamingAssets" / "maps"
STORY_MAPS_REL = MAPS_ROOT_REL / "Story_maps"
CORE_ZIP_REL = Path("HeroesOldenEra_Data") / "StreamingAssets" / "Core.zip"
INSTALL_DESTINATION_POLICY = "maps_root_custom_only"


def fail(message: str) -> None:
    raise SystemExit(f"event runtime probe install failed: {message}")


def artifact_paths(repo_root: Path) -> tuple[Path, Path, Path, Path]:
    root = repo_root / ARTIFACT_ROOT
    return (
        root / "maps" / f"{MAP_SID}.map",
        root / "maps" / f"{MAP_SID}.json",
        root / "install_manifest.json",
        root / "core_overlay",
    )


def validate_artifact(repo_root: Path) -> None:
    validator = repo_root / "tools" / "validate_event_runtime_probe_map_contract.py"
    result = subprocess.run(
        [sys.executable, str(validator), "--repo-root", str(repo_root), "--skip-generate"],
        check=False,
    )
    if result.returncode != 0:
        fail("event runtime probe contract validation failed before install")


def backup_existing_file(path: Path, backup_suffix: str) -> Path | None:
    if not path.exists():
        return None
    backup = path.with_name(path.name + backup_suffix)
    if backup.exists():
        fail(f"backup path already exists: {backup}")
    shutil.copy2(path, backup)
    return backup


def assert_no_story_maps_copy(game_root: Path) -> None:
    story = game_root / STORY_MAPS_REL
    for name in (f"{MAP_SID}.map", f"{MAP_SID}.json"):
        path = story / name
        if path.exists():
            fail(
                f"refuse Story_maps install / leftover: {path}. "
                "event runtime probe must not live under Story_maps."
            )


def copy_map_payload(repo_root: Path, game_root: Path, backup_suffix: str) -> None:
    map_path, script_path, _, _ = artifact_paths(repo_root)
    if not map_path.is_file() or not script_path.is_file():
        fail("missing probe artifacts; run build_event_runtime_probe_map.py first")
    maps_dir = game_root / MAPS_ROOT_REL
    maps_dir.mkdir(parents=True, exist_ok=True)
    installed_map = maps_dir / map_path.name
    installed_script = maps_dir / script_path.name
    backup_existing_file(installed_map, backup_suffix)
    backup_existing_file(installed_script, backup_suffix)
    shutil.copy2(map_path, installed_map)
    shutil.copy2(script_path, installed_script)


def merge_core_overlay(repo_root: Path, game_root: Path, backup_suffix: str) -> list[str]:
    _, _, _, overlay_root = artifact_paths(repo_root)
    if not overlay_root.is_dir():
        fail(f"missing core overlay: {overlay_root}")
    core_zip = game_root / CORE_ZIP_REL
    if not core_zip.is_file():
        fail(f"missing Core.zip: {core_zip}")
    backup_existing_file(core_zip, backup_suffix)

    members: list[str] = []
    for path in sorted(overlay_root.rglob("*")):
        if not path.is_file():
            continue
        member = path.relative_to(overlay_root).as_posix()
        members.append(member)

    if not members:
        fail("core overlay contains no files")

    tmp = core_zip.with_suffix(".zip.tmp_event_probe")
    if tmp.exists():
        tmp.unlink()
    with zipfile.ZipFile(core_zip, "r") as src, zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED) as dst:
        skip = set(members)
        for info in src.infolist():
            if info.filename in skip:
                continue
            dst.writestr(info, src.read(info.filename))
        for member in members:
            payload = (overlay_root / member).read_bytes()
            dst.writestr(member, payload)
    tmp.replace(core_zip)
    return members


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--game-root", type=Path, default=DEFAULT_GAME_ROOT)
    parser.add_argument("--skip-validate", action="store_true")
    parser.add_argument("--skip-core", action="store_true", help="Install map only (dialogs will be missing)")
    args = parser.parse_args(argv)
    repo_root = args.repo_root.resolve()
    game_root = args.game_root.resolve()
    if not game_root.is_dir():
        fail(f"game root not found: {game_root}")

    if not args.skip_validate:
        validate_artifact(repo_root)

    assert_no_story_maps_copy(game_root)
    backup_suffix = f".event_probe_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    copy_map_payload(repo_root, game_root, backup_suffix)
    merged: list[str] = []
    if not args.skip_core:
        merged = merge_core_overlay(repo_root, game_root, backup_suffix)
    assert_no_story_maps_copy(game_root)

    print(
        json.dumps(
            {
                "ok": True,
                "mapSid": MAP_SID,
                "installDestinationPolicy": INSTALL_DESTINATION_POLICY,
                "mapsDir": str(game_root / MAPS_ROOT_REL),
                "coreMembersMerged": merged,
                "proofBoundary": "installed payload copied; runtime event behavior still user-unvalidated",
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
