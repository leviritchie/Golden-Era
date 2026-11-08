#!/usr/bin/env python3
"""Merge vanilla_stock optional event dialog DB members into an installed Core.zip.

Fail-closed: overlay members must exist; Core.zip is rewritten with those members
replaced/added. A sibling backup is created once per Core path.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import zipfile
from pathlib import Path
from typing import Any


def _overlay_members(overlay_dir: Path) -> dict[str, bytes]:
    db_root = overlay_dir / "DB"
    if not db_root.is_dir():
        raise SystemExit(f"overlay DB root missing: {db_root}")
    members: dict[str, bytes] = {}
    for path in sorted(db_root.rglob("*.json")):
        rel = path.relative_to(overlay_dir).as_posix()
        members[rel] = path.read_bytes()
    if not members:
        raise SystemExit(f"overlay has no JSON members under {db_root}")
    return members


def install_dialog_overlay(*, overlay_dir: Path, core_zip: Path) -> dict[str, Any]:
    if not core_zip.is_file():
        raise SystemExit(f"Core.zip not found: {core_zip}")
    members = _overlay_members(overlay_dir)
    backup = core_zip.with_suffix(core_zip.suffix + ".bak_vanilla_stock_event_dialogs")
    if not backup.is_file():
        shutil.copy2(core_zip, backup)

    tmp = core_zip.with_suffix(core_zip.suffix + ".tmp_vanilla_stock_dialogs")
    if tmp.exists():
        tmp.unlink()
    with zipfile.ZipFile(core_zip, "r") as src, zipfile.ZipFile(
        tmp, "w", compression=zipfile.ZIP_DEFLATED
    ) as dst:
        replaced = 0
        for info in src.infolist():
            name = info.filename.replace("\\", "/")
            if name in members:
                dst.writestr(name, members[name])
                replaced += 1
                members.pop(name)
            else:
                dst.writestr(info, src.read(info.filename))
        added = 0
        for name, payload in sorted(members.items()):
            dst.writestr(name, payload)
            added += 1
    tmp.replace(core_zip)

    with zipfile.ZipFile(core_zip, "r") as verify:
        names = {n.replace("\\", "/") for n in verify.namelist()}
    missing = sorted(set(_overlay_members(overlay_dir)) - names)
    if missing:
        raise SystemExit(f"Core.zip missing overlay members after install: {missing[:8]}")

    return {
        "coreZip": str(core_zip),
        "backup": str(backup),
        "replaced": replaced,
        "added": added,
        "memberCount": replaced + added,
        "result": "PASS",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--overlay-dir", type=Path, required=True)
    parser.add_argument("--core-zip", type=Path, required=True)
    args = parser.parse_args(argv)
    report = install_dialog_overlay(overlay_dir=args.overlay_dir, core_zip=args.core_zip)
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
