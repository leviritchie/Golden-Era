#!/usr/bin/env python3
"""Preflight/prepare the HoMM3 60 FPS dual-stream bulk RIFE run."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_LAB_ROOT = (
    REPO_ROOT / "Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/homm3_lab"
)
DEFAULT_MANIFEST = SCRIPT_DIR / "homm3_units_manifest.json"
DEFAULT_LOG_DIR = SCRIPT_DIR / "rife_production_logs"
BACKUP_DIR_NAME = "extracted_battle_source_12fps"
DONE_META_NAME = ".rife120_done.json"
DEFAULT_EXCLUDES = {"temple_griffon", "h3_fangarm"}


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def manifest_units(path: Path) -> list[str]:
    data = load_json(path)
    return [
        str(row.get("unitSid", "")).strip()
        for row in data.get("units", [])
        if str(row.get("unitSid", "")).strip()
    ]


def find_battle_manifest(battle_dir: Path) -> Path | None:
    for path in sorted(battle_dir.glob("*.json")):
        if path.name.startswith(".") or path.name.lower() == "manifest.json":
            continue
        try:
            data = load_json(path)
        except json.JSONDecodeError:
            continue
        if isinstance(data.get("sequences"), list):
            return path
    return None


def sequence_counts(manifest_path: Path) -> dict[int, int]:
    data = load_json(manifest_path)
    out: dict[int, int] = {}
    for seq in data.get("sequences", []):
        frames = [f for f in (seq.get("frames") or []) if str(f or "").strip()]
        if frames:
            out[int(seq.get("group", -1))] = len(frames)
    return out


def resolve_frame_path(battle_dir: Path, rel: str) -> Path:
    path = battle_dir / rel.replace("\\", "/")
    if path.is_file():
        return path
    parts = rel.replace("\\", "/").split("/")
    if len(parts) == 2:
        folder_name, file_name = parts
        folder = battle_dir / folder_name
        if not folder.is_dir():
            for candidate in battle_dir.iterdir():
                if candidate.is_dir() and candidate.name.lower() == folder_name.lower():
                    folder = candidate
                    break
        candidate = folder / file_name
        if candidate.is_file():
            return candidate
        if folder.is_dir():
            for file_candidate in folder.iterdir():
                if file_candidate.is_file() and file_candidate.name.lower() == file_name.lower():
                    return file_candidate
    return path


def missing_frame_files(manifest_path: Path) -> list[str]:
    battle_dir = manifest_path.parent
    data = load_json(manifest_path)
    missing: list[str] = []
    seen: set[str] = set()
    for seq in data.get("sequences", []):
        for rel_raw in seq.get("frames") or []:
            rel = str(rel_raw or "").strip()
            if not rel or rel in seen:
                continue
            seen.add(rel)
            if not resolve_frame_path(battle_dir, rel).is_file():
                missing.append(rel)
                if len(missing) >= 10:
                    return missing
    return missing


def expected_groups(counts: dict[int, int], sid: str) -> set[int]:
    needed: set[int] = set()
    for group in (2, 3, 5):
        if group in counts:
            needed.add(group)
    for group in (0, 1, 2):
        if group in counts:
            needed.add(group)
            break
    if sid in {"hota_cove_nymph", "hota_cove_oceanid", "hota_cove_nereid"} or (
        20 in counts and 21 in counts
    ):
        needed.update(g for g in (20, 21) if g in counts)
    needed.update(g for g in (11, 12, 13, 14, 15, 16) if g in counts)
    if 0 in needed and 1 in needed:
        needed.discard(1)
    return needed


def is_unity_running() -> bool:
    if os.name != "nt":
        return False
    try:
        out = subprocess.check_output(
            ["tasklist", "/FI", "IMAGENAME eq Unity.exe"],
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        return False
    return "Unity.exe" in out


def run_extract(unit: str, unity_project: Path) -> None:
    cmd = [
        sys.executable,
        str(SCRIPT_DIR / "extract_creature.py"),
        "--unit",
        unit,
        "--unity-project",
        str(unity_project),
    ]
    subprocess.run(cmd, cwd=str(REPO_ROOT), check=True)


def copy_unity_battle_to_offline(unit: str, unity_project: Path, lab_root: Path) -> None:
    src = unity_project / "Assets/CustomUnits/homm3_lab" / unit / "extracted_battle"
    dst = lab_root / unit / "extracted_battle"
    if not src.is_dir():
        raise FileNotFoundError(f"extract did not create {src}")
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)


def ensure_source_backup(unit_dir: Path, *, replace: bool = False) -> None:
    battle = unit_dir / "extracted_battle"
    backup = unit_dir / BACKUP_DIR_NAME
    if replace and backup.exists():
        shutil.rmtree(backup)
    if backup.is_dir():
        return
    if not battle.is_dir():
        raise FileNotFoundError(f"missing extracted_battle for {unit_dir.name}")
    shutil.copytree(battle, backup, ignore=shutil.ignore_patterns(DONE_META_NAME))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    ap.add_argument("--lab-root", type=Path, default=DEFAULT_LAB_ROOT)
    ap.add_argument("--log-dir", type=Path, default=DEFAULT_LOG_DIR)
    ap.add_argument("--target-fps", type=int, default=60)
    ap.add_argument("--write-unit-list", action="store_true")
    ap.add_argument("--extract-missing", action="store_true")
    ap.add_argument("--unity-project", type=Path)
    ap.add_argument("--fail-if-unity-running", action="store_true")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args()

    if args.fail_if_unity_running and is_unity_running():
        print("Unity.exe is running; stop it before the unattended batch.", file=sys.stderr)
        return 2

    lab_root = args.lab_root.resolve()
    units = [u for u in manifest_units(args.manifest.resolve()) if u not in DEFAULT_EXCLUDES]
    args.log_dir.mkdir(parents=True, exist_ok=True)
    list_path = args.log_dir / "manifest_eligible_no_temple_fangarm.txt"
    if args.write_unit_list:
        list_path.write_text("\n".join(units) + "\n", encoding="utf-8")

    missing_lab: list[str] = []
    missing_battle: list[str] = []
    missing_manifest: list[str] = []
    missing_backup: list[str] = []
    corrupt_backup: list[str] = []
    dense_reset_candidates: list[str] = []
    expected_total = 0

    for unit in units:
        unit_dir = lab_root / unit
        battle_dir = unit_dir / "extracted_battle"
        if not unit_dir.is_dir():
            missing_lab.append(unit)
            continue
        if not battle_dir.is_dir():
            missing_battle.append(unit)
            continue
        manifest_path = find_battle_manifest(battle_dir)
        needs_extract = manifest_path is None
        backup_manifest_before = find_battle_manifest(unit_dir / BACKUP_DIR_NAME)
        backup_missing_files_before = (
            missing_frame_files(backup_manifest_before) if backup_manifest_before is not None else []
        )
        if backup_missing_files_before:
            needs_extract = True
        if needs_extract:
            if args.extract_missing:
                if args.unity_project is None:
                    print("--extract-missing requires --unity-project", file=sys.stderr)
                    return 2
                reason = "missing sidecar" if manifest_path is None else "missing backup frames"
                print(f"extract {unit} ({reason})")
                run_extract(unit, args.unity_project.resolve())
                copy_unity_battle_to_offline(unit, args.unity_project.resolve(), lab_root)
                manifest_path = find_battle_manifest(battle_dir)
            if manifest_path is None:
                missing_manifest.append(unit)
                continue

        if args.extract_missing:
            ensure_source_backup(unit_dir, replace=bool(backup_missing_files_before))
        if not (unit_dir / BACKUP_DIR_NAME).is_dir():
            missing_backup.append(unit)

        counts = sequence_counts(manifest_path)
        backup_manifest = find_battle_manifest(unit_dir / BACKUP_DIR_NAME)
        if backup_manifest is not None:
            missing_files = missing_frame_files(backup_manifest)
            if missing_files:
                corrupt_backup.append(f"{unit}: " + ", ".join(missing_files[:3]))
        if backup_manifest is not None:
            backup_counts = sequence_counts(backup_manifest)
            for group, count in counts.items():
                source = backup_counts.get(group)
                if source and count > source * 2:
                    dense_reset_candidates.append(f"{unit}:g{group:02d} {source}->{count}")
                    break
            source_counts = backup_counts
        else:
            source_counts = counts
        for group in expected_groups(source_counts, unit):
            expected_total += source_counts[group] * max(1, args.target_fps // 12)

    print(f"eligible units: {len(units)}")
    print(f"unit list: {list_path if args.write_unit_list else '(not written)'}")
    print(f"expected interpolated frame total (used groups only): {expected_total}")
    for label, rows in (
        ("missing lab", missing_lab),
        ("missing extracted_battle", missing_battle),
        ("missing sidecar json", missing_manifest),
        ("missing source backup", missing_backup),
        ("source backups missing frame files", corrupt_backup),
        ("dense manifests with source backup (will reset)", dense_reset_candidates),
    ):
        print(f"{label}: {len(rows)}")
        if rows:
            print("  " + "\n  ".join(rows[:40]))

    if args.strict and (
        missing_lab
        or missing_battle
        or missing_manifest
        or missing_backup
        or corrupt_backup
    ):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
