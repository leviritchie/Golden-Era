#!/usr/bin/env python3
"""Install the Homecoming playable-shell QuickStart catalog entry into Core.zip."""

from __future__ import annotations

import argparse
import json
import shutil
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path


CORE_ENTRY = "DB/quickStart.json"
DEFAULT_MAP_SID = "h3_roe_castle_homecoming_poc"


def fail(message: str) -> None:
    raise SystemExit(f"homecoming quickStart catalog install failed: {message}")


def read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception as ex:
        fail(f"could not read JSON {path}: {ex}")


def validate_overlay(overlay: Path, map_sid: str) -> str:
    data = read_json(overlay)
    scenarios = data.get("scenarios")
    if not isinstance(scenarios, list):
        fail(f"overlay {overlay} does not contain a scenarios list")
    if scenarios.count(map_sid) != 1:
        fail(f"overlay scenarios must contain exactly one {map_sid!r}; found {scenarios.count(map_sid)}")
    if "Thirst_for_Power" not in scenarios:
        fail("overlay scenarios lost the native Thirst_for_Power anchor")
    return map_sid


def build_merged_quickstart_catalog(current: dict, map_sid: str) -> bytes:
    scenarios = current.get("scenarios")
    if not isinstance(scenarios, list) or "Thirst_for_Power" not in scenarios:
        fail("installed Core quickStart scenarios are missing the native Thirst_for_Power anchor")
    existing = scenarios.count(map_sid)
    if existing > 1:
        fail(f"installed Core quickStart scenarios already contain multiple {map_sid!r} entries")
    if existing == 1:
        return json.dumps(current, indent="\t", ensure_ascii=False).encode("utf-8") + b"\n"

    merged = dict(current)
    merged["scenarios"] = list(scenarios) + [map_sid]
    return json.dumps(merged, indent="\t", ensure_ascii=False).encode("utf-8") + b"\n"

def validate_payload_files(map_dir: Path, map_sid: str) -> None:
    missing = [path for path in (map_dir / f"{map_sid}.map", map_dir / f"{map_sid}.json") if not path.exists()]
    if missing:
        fail("missing installed Homecoming map payload: " + ", ".join(str(path) for path in missing))


def install(core_zip: Path, overlay: Path, map_dir: Path, map_sid: str, backup_suffix: str) -> Path:
    if not core_zip.exists():
        fail(f"missing Core.zip: {core_zip}")
    if not overlay.exists():
        fail(f"missing generated quickStart overlay: {overlay}")
    validate_payload_files(map_dir, map_sid)
    overlay_map_sid = validate_overlay(overlay, map_sid)

    with zipfile.ZipFile(core_zip, "r") as source:
        names = source.namelist()
        if CORE_ENTRY not in names:
            fail(f"{core_zip} does not contain {CORE_ENTRY}")
        current = json.loads(source.read(CORE_ENTRY).decode("utf-8-sig"))
        merged_quickstart = build_merged_quickstart_catalog(current, overlay_map_sid)

        temp_dir = Path(tempfile.mkdtemp(prefix="homecoming_quickstart_core_", dir=str(core_zip.parent)))
        temp_zip = temp_dir / core_zip.name
        try:
            with zipfile.ZipFile(temp_zip, "w") as target:
                for item in source.infolist():
                    payload = merged_quickstart if item.filename == CORE_ENTRY else source.read(item.filename)
                    replacement = zipfile.ZipInfo(item.filename, item.date_time)
                    replacement.comment = item.comment
                    replacement.extra = item.extra
                    replacement.internal_attr = item.internal_attr
                    replacement.external_attr = item.external_attr
                    replacement.compress_type = item.compress_type
                    target.writestr(replacement, payload)

            backup = core_zip.with_name(core_zip.name + backup_suffix)
            if backup.exists():
                fail(f"backup path already exists: {backup}")
            shutil.copy2(core_zip, backup)
            shutil.move(str(temp_zip), core_zip)
            return backup
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--core", required=True, type=Path)
    parser.add_argument("--overlay", required=True, type=Path)
    parser.add_argument("--map-dir", required=True, type=Path)
    parser.add_argument("--map-sid", default=DEFAULT_MAP_SID)
    parser.add_argument("--backup-suffix")
    args = parser.parse_args()

    suffix = args.backup_suffix or ".backup-homecoming-quickstart-catalog-" + datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = install(args.core, args.overlay, args.map_dir, args.map_sid, suffix)
    print(f"homecoming quickStart catalog installed: core={args.core} backup={backup} mapSid={args.map_sid}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
