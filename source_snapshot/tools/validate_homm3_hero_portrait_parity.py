#!/usr/bin/env python3
"""Validate HoMM3 custom hero portrait parity across manifests, Core.zip, and plugin payloads.

Existence-only checks are not enough: a stale Golden Era plugin folder can keep old PNG
bytes while manifests still list the expected SIDs. When --deployed-plugin-root is set,
upscaled (and standard) portrait files must byte-match the source plugin payload.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PLUGIN_ROOT = (
    ROOT
    / "Heroes of Might & Magic Olden Era Playtest"
    / "OfflineUnlockMod"
)


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def manifest_factions(custom_factions: Path):
    for path in sorted(custom_factions.glob("homm3_*.json")):
        data = load_json(path)
        heroes = data.get("heroes") or {}
        sid = data.get("factionSid") or data.get("id") or path.stem
        hero_prefix = heroes.get("heroPrefix") or data.get("heroPrefix")
        icon_prefix = heroes.get("iconPrefix") or data.get("iconPrefix")
        hero_count = int(heroes.get("count") or 18)
        if not hero_prefix or not icon_prefix:
            yield path, sid, hero_prefix, icon_prefix, hero_count, "missing heroPrefix/iconPrefix"
        else:
            yield path, sid, hero_prefix, icon_prefix, hero_count, None


def expected_hero_sids(hero_prefix: str, hero_count: int) -> list[str]:
    return [f"{hero_prefix}{index}" for index in range(1, hero_count + 1)]


def validate_portrait_dir(label: str, portrait_dir: Path, factions, issues: list[str]) -> None:
    manifest_path = portrait_dir / "manifest.json"
    manifest_entries = {}
    if manifest_path.exists():
        manifest = load_json(manifest_path)
        manifest_entries = manifest.get("entries") or {}
    else:
        issues.append(f"{label}: missing manifest {manifest_path}")

    for _, faction_sid, hero_prefix, _, hero_count, prefix_issue in factions:
        if prefix_issue:
            issues.append(f"{label}: {faction_sid}: {prefix_issue}")
            continue
        for sid in expected_hero_sids(hero_prefix, hero_count):
            if not (portrait_dir / f"{sid}.png").exists():
                issues.append(f"{label}: {faction_sid}: missing {sid}.png")
            entry = manifest_entries.get(sid)
            if not isinstance(entry, dict):
                issues.append(f"{label}: {faction_sid}: missing manifest entry {sid}")
                continue
            if not str(entry.get("name") or "").strip():
                issues.append(f"{label}: {faction_sid}: manifest entry {sid} missing name")


def validate_portrait_bytes_match(
    label: str,
    source_dir: Path,
    deployed_dir: Path,
    factions,
    issues: list[str],
) -> None:
    if not source_dir.is_dir():
        issues.append(f"{label}: missing source portrait dir {source_dir}")
        return
    if not deployed_dir.is_dir():
        issues.append(f"{label}: missing deployed portrait dir {deployed_dir}")
        return

    mismatched = []
    for _, faction_sid, hero_prefix, _, hero_count, prefix_issue in factions:
        if prefix_issue:
            continue
        for sid in expected_hero_sids(hero_prefix, hero_count):
            source_png = source_dir / f"{sid}.png"
            deployed_png = deployed_dir / f"{sid}.png"
            if not source_png.is_file() or not deployed_png.is_file():
                continue
            if file_sha256(source_png) != file_sha256(deployed_png):
                mismatched.append(f"{faction_sid}:{sid}")

    if mismatched:
        sample = ", ".join(mismatched[:8])
        more = "" if len(mismatched) <= 8 else f" (+{len(mismatched) - 8} more)"
        issues.append(
            f"{label}: {len(mismatched)} portrait PNG(s) differ from source by content hash "
            f"(stale deploy). Examples: {sample}{more}. Redeploy OfflineUnlockMod "
            f"homm3_hero_portraits*_ folders after portrait promote."
        )


def validate_core(core_zip: Path, factions, issues: list[str]) -> None:
    if not core_zip:
        return
    if not core_zip.exists():
        issues.append(f"Core.zip not found: {core_zip}")
        return

    with zipfile.ZipFile(core_zip) as zf:
        names = set(zf.namelist())
        for _, faction_sid, hero_prefix, icon_prefix, hero_count, prefix_issue in factions:
            if prefix_issue:
                issues.append(f"Core.zip: {faction_sid}: {prefix_issue}")
                continue
            hero_dir = f"DB/heroes/{faction_sid}/"
            hero_files = sorted(
                name for name in names if name.startswith(hero_dir) and name.endswith(".json")
            )
            if len(hero_files) != hero_count:
                issues.append(f"Core.zip: {faction_sid}: expected {hero_count} hero files, found {len(hero_files)}")

            seen = set()
            for name in hero_files:
                data = json.loads(zf.read(name).decode("utf-8-sig"))
                rows = data.get("array") if isinstance(data, dict) else None
                if not rows:
                    issues.append(f"Core.zip: {name}: missing array row")
                    continue
                hero = rows[0]
                hero_id = hero.get("id")
                icon = hero.get("icon")
                match = re.search(r"(\d+)$", hero_id or "")
                if not match:
                    issues.append(f"Core.zip: {name}: hero id has no numeric suffix: {hero_id}")
                    continue
                index = int(match.group(1))
                seen.add(index)
                expected_id = f"{hero_prefix}{index}"
                expected_icon = f"{icon_prefix}{index}"
                if hero_id != expected_id:
                    issues.append(f"Core.zip: {name}: id {hero_id} expected {expected_id}")
                if icon != expected_icon:
                    issues.append(f"Core.zip: {name}: icon {icon} expected {expected_icon}")

            missing = sorted(set(range(1, hero_count + 1)) - seen)
            if missing:
                issues.append(f"Core.zip: {faction_sid}: missing hero indices {missing}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--custom-factions", type=Path, default=ROOT / "custom_factions")
    parser.add_argument("--plugin-root", type=Path, default=DEFAULT_PLUGIN_ROOT)
    parser.add_argument("--deployed-plugin-root", type=Path)
    parser.add_argument("--upscaled-portrait-dir", type=Path)
    parser.add_argument("--core-zip", type=Path)
    parser.add_argument(
        "--require-deployed-content-match",
        action="store_true",
        help="When --deployed-plugin-root is set, require PNG bytes to match source (default: on).",
    )
    parser.add_argument(
        "--skip-deployed-content-match",
        action="store_true",
        help="Only check deployed file existence/manifest entries (legacy; hides stale PNG bytes).",
    )
    args = parser.parse_args()

    factions = list(manifest_factions(args.custom_factions))
    issues: list[str] = []

    validate_portrait_dir("source", args.plugin_root / "homm3_hero_portraits", factions, issues)
    upscaled_dir = args.upscaled_portrait_dir
    if upscaled_dir is None:
        upscaled_dir = args.plugin_root / "homm3_hero_portraits_upscaled"
    if upscaled_dir.exists():
        validate_portrait_dir("upscaled", upscaled_dir, factions, issues)
    if args.deployed_plugin_root:
        validate_portrait_dir(
            "deployed",
            args.deployed_plugin_root / "homm3_hero_portraits",
            factions,
            issues,
        )
        deployed_upscaled = args.deployed_plugin_root / "homm3_hero_portraits_upscaled"
        if deployed_upscaled.exists():
            validate_portrait_dir("deployed-upscaled", deployed_upscaled, factions, issues)
        if not args.skip_deployed_content_match:
            validate_portrait_bytes_match(
                "deployed-content",
                args.plugin_root / "homm3_hero_portraits",
                args.deployed_plugin_root / "homm3_hero_portraits",
                factions,
                issues,
            )
            if upscaled_dir.exists():
                validate_portrait_bytes_match(
                    "deployed-upscaled-content",
                    upscaled_dir,
                    deployed_upscaled,
                    factions,
                    issues,
                )
    validate_core(args.core_zip, factions, issues)

    if issues:
        print("HoMM3 hero portrait parity FAILED")
        for issue in issues:
            print(f" - {issue}")
        return 1

    print(f"HoMM3 hero portrait parity OK for {len(factions)} factions")
    return 0


if __name__ == "__main__":
    sys.exit(main())
