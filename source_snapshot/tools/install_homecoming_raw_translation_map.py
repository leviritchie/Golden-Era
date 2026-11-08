#!/usr/bin/env python3
"""Install the Homecoming raw_translation map — the default scenario payload.

Install destination (fail-closed, one path only):
  StreamingAssets/maps/Story_maps/

Native campaign maps (c_M*, t_*) live only under Story_maps/. Installing the same
mapSid into both maps/ and Story_maps/ registers QuestScript twice, so every
StartTurn Dialog (day briefings) plays twice. Player.log evidence: each
homecoming_briefing_* Start dialog fires exactly twice under dual install.

This installer mirrors tools/install_roe_castle_continuity_weave.py (Story_maps only)
and removes any stale maps/-root copy of the same SID on install.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

MAP_SID = "h3_roe_castle_homecoming_raw_translation"
DEFAULT_GAME_ROOT = Path(r"V:\SteamLibrary\steamapps\common\Heroes of Might and Magic Olden Era - Golden Era")
ARTIFACT_ROOT = Path("artifacts") / "campaign_port_poc" / "homecoming_poc" / "raw_translation_map"
CORE_ZIP_REL = Path("HeroesOldenEra_Data") / "StreamingAssets" / "Core.zip"
# StoryHub StartInfo resolves mapSid under Story_maps/ (native c_M*/t_* layout).
# Dual install into maps/ + Story_maps/ double-fires QuestScript Dialogs — never both.
MAPS_ROOT_REL = Path("HeroesOldenEra_Data") / "StreamingAssets" / "maps"
STORY_MAPS_REL = MAPS_ROOT_REL / "Story_maps"
INSTALL_DESTINATION_POLICY = "story_maps_only_forbid_maps_root_duplicate"
QUICKSTART_MEMBER = "DB/quickStart.json"


def fail(message: str) -> None:
    raise SystemExit(f"homecoming raw_translation install failed: {message}")


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def artifact_paths(repo_root: Path) -> tuple[Path, Path, Path, Path]:
    root = repo_root / ARTIFACT_ROOT
    return (
        root / "maps" / f"{MAP_SID}.map",
        root / "maps" / f"{MAP_SID}.json",
        root / "core_overlay",
        root / "install_manifest.json",
    )


def validate_artifact(repo_root: Path) -> None:
    validator = repo_root / "tools" / "validate_homecoming_raw_translation_map_contract.py"
    # Skip installed dual-SID check here: this installer is what removes the stale
    # maps/-root copy. assert_no_dual_install runs after copy_map_payload.
    result = subprocess.run(
        [
            sys.executable,
            str(validator),
            "--repo-root",
            str(repo_root),
            "--skip-generate",
            "--skip-installed-dual-check",
        ],
        check=False,
    )
    if result.returncode != 0:
        fail("raw_translation contract validation failed before install")


def backup_existing_file(path: Path, backup_suffix: str, *, quarantine_dir: Path) -> Path | None:
    """Copy ``path`` into quarantine_dir; never leave SID*.map/json backups under maps/."""
    if not path.exists():
        return None
    quarantine_dir.mkdir(parents=True, exist_ok=True)
    backup = quarantine_dir / (path.name + backup_suffix)
    if backup.exists():
        fail(f"backup path already exists: {backup}")
    shutil.copy2(path, backup)
    return backup


def maps_backup_quarantine(game_root: Path, backup_suffix: str) -> Path:
    # Keep install backups outside StreamingAssets/maps so foldercache / loaders
    # cannot treat SID.map.* / SID.json.* litter as a second map script source.
    stamp = backup_suffix.lstrip(".")
    return (
        game_root
        / "HeroesOldenEra_Data"
        / "StreamingAssets"
        / f"_map_install_backups_{stamp}"
    )


def remove_maps_root_duplicate(game_root: Path, backup_suffix: str) -> list[str]:
    """Backup+delete maps/-root copies so QuestScript cannot register twice."""
    maps_root = game_root / MAPS_ROOT_REL
    quarantine = maps_backup_quarantine(game_root, backup_suffix)
    removed: list[str] = []
    for name in (f"{MAP_SID}.map", f"{MAP_SID}.json"):
        path = maps_root / name
        if not path.is_file():
            continue
        backup_existing_file(path, backup_suffix, quarantine_dir=quarantine)
        path.unlink()
        removed.append(str(path))
    return removed


def assert_no_dual_install(game_root: Path) -> None:
    maps_root = game_root / MAPS_ROOT_REL
    story = game_root / STORY_MAPS_REL
    root_map = maps_root / f"{MAP_SID}.map"
    root_json = maps_root / f"{MAP_SID}.json"
    story_map = story / f"{MAP_SID}.map"
    if (root_map.is_file() or root_json.is_file()) and story_map.is_file():
        fail(
            f"dual mapSid install forbidden ({INSTALL_DESTINATION_POLICY}): "
            f"both {root_map} and {story_map} exist; QuestScript Dialogs would play twice"
        )


def copy_map_payload(repo_root: Path, game_root: Path, backup_suffix: str) -> list[str]:
    map_path, script_path, _overlay, manifest_path = artifact_paths(repo_root)
    for required in (map_path, script_path, manifest_path):
        if not required.exists():
            fail(f"missing generated artifact: {required}")

    removed = remove_maps_root_duplicate(game_root, backup_suffix)

    maps_dir = game_root / STORY_MAPS_REL
    maps_dir.mkdir(parents=True, exist_ok=True)
    quarantine = maps_backup_quarantine(game_root, backup_suffix)
    backup_existing_file(maps_dir / map_path.name, backup_suffix, quarantine_dir=quarantine)
    backup_existing_file(maps_dir / script_path.name, backup_suffix, quarantine_dir=quarantine)
    shutil.copy2(map_path, maps_dir / map_path.name)
    shutil.copy2(script_path, maps_dir / script_path.name)

    sys.path.insert(0, str(repo_root / "tools"))
    from map_load_preflight import (
        rewrite_map_file_expand_meta_random_res,
    )

    rewrite_map_file_expand_meta_random_res(maps_dir / map_path.name)

    assert_no_dual_install(game_root)
    return removed


def patch_core_overlay_and_quickstart(repo_root: Path, game_root: Path, backup_suffix: str) -> str:
    _map_path, _script_path, overlay_root, _manifest = artifact_paths(repo_root)
    core_zip = game_root / CORE_ZIP_REL
    if not core_zip.exists():
        fail(f"missing Core.zip: {core_zip}")
    if not overlay_root.is_dir():
        fail(f"missing core_overlay: {overlay_root}")

    # Reuse shared Meta hang scrub / aliases / boat ObjectConfig + post-install preflight.
    sys.path.insert(0, str(repo_root / "tools"))
    from map_load_preflight import (  # noqa: WPS433
        apply_loader_hang_core_guards,
        format_issues,
        run_installed_campaign_preflight,
    )

    overlay_members: dict[str, bytes] = {}
    for path in sorted(overlay_root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(overlay_root).as_posix()
        if relative.endswith("_overlay_manifest.json"):
            continue
        if relative == "quickStart.json":
            overlay_members["DB/quickStart.json"] = path.read_bytes()
            continue
        if not (relative.startswith("DB/") or relative.startswith("Lang/")):
            continue
        overlay_members[relative] = path.read_bytes()
    if "DB/quickStart.json" not in overlay_members:
        fail("raw_translation core overlay missing DB/quickStart.json")

    backup = core_zip.with_name(core_zip.name + backup_suffix)
    if backup.exists():
        fail(f"backup path already exists: {backup}")
    temp_dir = Path(tempfile.mkdtemp(prefix="homecoming_raw_translation_core_", dir=str(core_zip.parent)))
    temp_zip = temp_dir / core_zip.name
    try:
        with zipfile.ZipFile(core_zip, "r") as source:
            qs = json.loads(source.read(QUICKSTART_MEMBER).decode("utf-8-sig"))
            scenarios = list(qs.get("scenarios") or [])
            if MAP_SID not in scenarios:
                scenarios.append(MAP_SID)
            qs["scenarios"] = scenarios
            overlay_members[QUICKSTART_MEMBER] = (
                json.dumps(qs, indent=2, ensure_ascii=False) + "\n"
            ).encode("utf-8")

            try:
                guard_report = apply_loader_hang_core_guards(source, overlay_members)
            except ValueError as exc:
                fail(str(exc))

            with zipfile.ZipFile(temp_zip, "w") as target:
                written = set()
                for item in source.infolist():
                    if item.filename in overlay_members:
                        data = overlay_members[item.filename]
                    else:
                        data = source.read(item.filename)
                    replacement = zipfile.ZipInfo(item.filename, item.date_time)
                    replacement.comment = item.comment
                    replacement.extra = item.extra
                    replacement.internal_attr = item.internal_attr
                    replacement.external_attr = item.external_attr
                    replacement.compress_type = item.compress_type
                    target.writestr(replacement, data)
                    written.add(item.filename)
                for member, data in overlay_members.items():
                    if member in written:
                        continue
                    target.writestr(member, data)
        shutil.copy2(core_zip, backup)
        shutil.copy2(temp_zip, core_zip)
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

    issues = run_installed_campaign_preflight(
        game_root=game_root,
        core_zip=core_zip,
        map_checks=[
            {
                "mapSid": MAP_SID,
                "mapPath": game_root / STORY_MAPS_REL / f"{MAP_SID}.map",
            }
        ],
    )
    if issues:
        fail(format_issues(issues))
    scrubbed = len(guard_report.get("scrubbedOrphanXfpLogic") or [])
    return f"patched_overlay_and_quickstart scrubbedXfp={scrubbed}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--game-root", type=Path, default=DEFAULT_GAME_ROOT)
    args = parser.parse_args()
    repo_root = args.repo_root.resolve()
    game_root = args.game_root.resolve()
    validate_artifact(repo_root)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_suffix = f".homecoming_raw_translation_backup_{stamp}"
    removed = copy_map_payload(repo_root, game_root, backup_suffix)
    action = patch_core_overlay_and_quickstart(repo_root, game_root, backup_suffix)
    removed_note = f" removedMapsRootDuplicates={len(removed)}" if removed else ""
    print(
        "homecoming raw_translation installed: "
        f"gameRoot={game_root} coreZipAction={action} mapSid={MAP_SID} "
        f"destination=Story_maps policy={INSTALL_DESTINATION_POLICY}{removed_note} "
        "(raw_translation is the only campaign map generation lane)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
