#!/usr/bin/env python3
"""Install Homecoming LocKit rows into Core.zip for all supported locales."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "experiments" / "campaign_port_poc"))

import homecoming_localization as loc  # noqa: E402

DEFAULT_CORE = (
    Path(r"V:\SteamLibrary\steamapps\common\Heroes of Might and Magic Olden Era - Golden Era")
    / "HeroesOldenEra_Data"
    / "StreamingAssets"
    / "Core.zip"
)
DEFAULT_OVERLAY = (
    ROOT
    / "artifacts"
    / "campaign_port_poc"
    / "homecoming_poc"
    / "raw_translation_map"
    / "core_overlay"
)


def fail(message: str) -> None:
    raise SystemExit(f"homecoming localization install failed: {message}")


def install_from_overlay(core_zip: Path, overlay_root: Path, backup_suffix: str) -> Path:
    if not core_zip.exists():
        fail(f"missing Core.zip: {core_zip}")
    if not overlay_root.is_dir():
        fail(f"missing lang overlay root: {overlay_root}")
    members: dict[str, Path] = {}
    for path in sorted((overlay_root / "Lang").rglob("*.json")):
        relative = path.relative_to(overlay_root).as_posix()
        if not relative.startswith("Lang/"):
            continue
        members[relative] = path
    required_files = loc.required_sids_by_file()
    for lang in loc.HOMECOMING_LANGS:
        for file_name in required_files:
            member = f"Lang/{lang}/texts/{file_name}"
            if member not in members:
                fail(f"lang overlay missing {member}")
    backup = core_zip.with_name(core_zip.name + backup_suffix)
    if backup.exists():
        fail(f"backup path already exists: {backup}")
    temp_dir = Path(tempfile.mkdtemp(prefix="homecoming_localization_core_", dir=str(core_zip.parent)))
    temp_zip = temp_dir / core_zip.name
    try:
        with zipfile.ZipFile(core_zip, "r") as source, zipfile.ZipFile(temp_zip, "w") as target:
            written = set()
            for item in source.infolist():
                if item.filename in members:
                    payload = members[item.filename].read_bytes()
                else:
                    payload = source.read(item.filename)
                replacement = zipfile.ZipInfo(item.filename, item.date_time)
                replacement.comment = item.comment
                replacement.extra = item.extra
                replacement.internal_attr = item.internal_attr
                replacement.external_attr = item.external_attr
                replacement.compress_type = item.compress_type
                target.writestr(replacement, payload)
                written.add(item.filename)
            for member, path in members.items():
                if member in written:
                    continue
                info = zipfile.ZipInfo(member)
                info.compress_type = zipfile.ZIP_DEFLATED
                target.writestr(info, path.read_bytes())
        shutil.copy2(core_zip, backup)
        shutil.move(str(temp_zip), core_zip)
        return backup
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def generate_overlay(core_zip: Path, overlay_root: Path) -> dict:
    overlay_root.mkdir(parents=True, exist_ok=True)
    return loc.write_lang_overlay(overlay_root, core_zip)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--core", type=Path, default=DEFAULT_CORE)
    parser.add_argument("--overlay-root", type=Path, default=DEFAULT_OVERLAY)
    parser.add_argument("--generate-only", action="store_true")
    parser.add_argument("--skip-generate", action="store_true")
    parser.add_argument("--backup-suffix")
    args = parser.parse_args()

    if not args.skip_generate:
        # Ensure remaining locale JSON exists before overlay write.
        translations_json = ROOT / "experiments" / "campaign_port_poc" / "homecoming_lang_translations.json"
        if not translations_json.is_file():
            build = ROOT / "experiments" / "campaign_port_poc" / "build_homecoming_lang_translations.py"
            import subprocess

            result = subprocess.run([sys.executable, str(build), str(args.core)], check=False)
            if result.returncode != 0:
                fail("build_homecoming_lang_translations.py failed")
            # Force reload after JSON write.
            loc._TRANSLATIONS = None  # type: ignore[attr-defined]
        manifest = generate_overlay(args.core, args.overlay_root)
        print(f"homecoming lang overlay generated: members={len(manifest.get('members') or [])}")
        if args.generate_only:
            return 0

    suffix = args.backup_suffix or ".backup-homecoming-localization-" + datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = install_from_overlay(args.core, args.overlay_root, suffix)
    print(f"homecoming localization installed: core={args.core} backup={backup}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
