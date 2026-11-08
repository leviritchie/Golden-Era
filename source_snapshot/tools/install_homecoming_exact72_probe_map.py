#!/usr/bin/env python3
"""Install the exact-72 Homecoming minimap probe into StreamingAssets/maps/ only.

No Core overlay merge. No Story_maps. Does not replace production Homecoming SIDs.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

MAP_SID = "h3_roe_castle_homecoming_exact72_probe"
DEFAULT_GAME_ROOT = Path(r"V:\SteamLibrary\steamapps\common\Heroes of Might and Magic Olden Era - Golden Era")
ARTIFACT_ROOT = Path("artifacts") / "campaign_port_poc" / "homecoming_poc" / "exact72_probe_map"
MAPS_ROOT_REL = Path("HeroesOldenEra_Data") / "StreamingAssets" / "maps"
STORY_MAPS_REL = MAPS_ROOT_REL / "Story_maps"
INSTALL_DESTINATION_POLICY = "maps_root_custom_only"


def fail(message: str) -> None:
    raise SystemExit(f"homecoming exact72 probe install failed: {message}")


def artifact_paths(repo_root: Path) -> tuple[Path, Path, Path]:
    root = repo_root / ARTIFACT_ROOT
    return (
        root / "maps" / f"{MAP_SID}.map",
        root / "maps" / f"{MAP_SID}.json",
        root / "install_manifest.json",
    )


def validate_artifact(repo_root: Path) -> None:
    validator = repo_root / "tools" / "validate_homecoming_exact72_probe_map_contract.py"
    result = subprocess.run(
        [sys.executable, str(validator), "--repo-root", str(repo_root), "--skip-generate"],
        check=False,
    )
    if result.returncode != 0:
        fail("exact72 probe contract validation failed before install")


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
                "exact72 probe must not live under Story_maps (forbid_story_maps)."
            )


def copy_map_payload(repo_root: Path, game_root: Path, backup_suffix: str) -> None:
    map_path, script_path, _ = artifact_paths(repo_root)
    if not map_path.is_file() or not script_path.is_file():
        fail("missing probe artifacts; run build_homecoming_exact72_probe_map.py first")
    maps_dir = game_root / MAPS_ROOT_REL
    maps_dir.mkdir(parents=True, exist_ok=True)
    installed_map = maps_dir / map_path.name
    installed_script = maps_dir / script_path.name
    backup_existing_file(installed_map, backup_suffix)
    backup_existing_file(installed_script, backup_suffix)
    shutil.copy2(map_path, installed_map)
    shutil.copy2(script_path, installed_script)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--game-root", type=Path, default=DEFAULT_GAME_ROOT)
    parser.add_argument("--skip-validate", action="store_true")
    args = parser.parse_args(argv)
    repo_root = args.repo_root.resolve()
    game_root = args.game_root.resolve()
    if not game_root.is_dir():
        fail(f"game root not found: {game_root}")

    if not args.skip_validate:
        validate_artifact(repo_root)

    assert_no_story_maps_copy(game_root)
    backup_suffix = f".exact72_probe_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    copy_map_payload(repo_root, game_root, backup_suffix)
    assert_no_story_maps_copy(game_root)

    installed_map = game_root / MAPS_ROOT_REL / f"{MAP_SID}.map"
    installed_script = game_root / MAPS_ROOT_REL / f"{MAP_SID}.json"
    if not installed_map.is_file() or not installed_script.is_file():
        fail("install readback missing maps/-root probe files")

    print(
        json_dumps(
            {
                "status": "ok",
                "policy": INSTALL_DESTINATION_POLICY,
                "mapSid": MAP_SID,
                "installedMap": str(installed_map),
                "installedScript": str(installed_script),
                "proofBoundary": "installed_payload_only_runtime_bounds_unproven",
            }
        )
    )
    return 0


def json_dumps(payload: dict) -> str:
    import json

    return json.dumps(payload, indent=2)


if __name__ == "__main__":
    raise SystemExit(main())
