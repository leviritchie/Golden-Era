#!/usr/bin/env python3
"""Scrub stale custom_maps/*AbSod dialog JSON from Golden Era Core.zip.

These folders reuse primary dialog ids without portrait avatars. Zip/load order
then last-wins the empty copy over the planned portrait-bearing dialog.

Optionally merges refreshed primary dialog JSON from mission core_overlay trees.
"""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from install_roe_castle_continuity_weave import (  # noqa: E402
    DEFAULT_GAME_ROOT,
    CORE_ZIP_REL,
    is_stale_absod_dialog_member,
)


def merge_overlay_dialogs(overlay: Path, members: dict[str, bytes]) -> int:
    dialog_root = overlay / "DB" / "dialogs" / "dialogs" / "custom_maps"
    if not dialog_root.is_dir():
        raise FileNotFoundError(f"missing dialog overlay: {dialog_root}")
    added = 0
    for path in dialog_root.rglob("*.json"):
        if "AbSod" in path.parts:
            continue
        rel = path.relative_to(overlay).as_posix()
        members[rel] = path.read_bytes()
        added += 1
    return added


def _hub_config_overlays(repo_root: Path) -> list[Path]:
    import importlib.util

    installer = repo_root / "tools" / "install_roe_castle_continuity_weave.py"
    spec = importlib.util.spec_from_file_location(
        "install_roe_castle_continuity_weave", installer
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load continuity installer: {installer}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    out: list[Path] = []
    seen: set[Path] = set()
    for hub in (getattr(mod, "HUB_CONFIGS", None) or {}).values():
        if not isinstance(hub, dict):
            continue
        for install in hub.get("mapInstalls") or []:
            if not isinstance(install, dict):
                continue
            overlay = (repo_root / Path(str(install.get("coreOverlay") or ""))).resolve()
            if overlay in seen:
                continue
            seen.add(overlay)
            out.append(overlay)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--game-root", type=Path, default=DEFAULT_GAME_ROOT)
    ap.add_argument(
        "--overlay",
        action="append",
        default=[],
        type=Path,
        help="core_overlay root whose primary dialog JSON should replace Core members",
    )
    ap.add_argument(
        "--all-hub-configs",
        action="store_true",
        help="Merge primary dialogs from every continuity HUB_CONFIGS core_overlay",
    )
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    core_zip = args.game_root / CORE_ZIP_REL
    if not core_zip.is_file():
        print(f"missing Core.zip: {core_zip}", file=sys.stderr)
        return 1

    overlays = [path.resolve() for path in args.overlay]
    if args.all_hub_configs:
        overlays.extend(_hub_config_overlays(ROOT))
    # Dedupe preserving order.
    deduped: list[Path] = []
    seen: set[Path] = set()
    for overlay in overlays:
        if overlay in seen:
            continue
        seen.add(overlay)
        deduped.append(overlay)
    if not deduped:
        print("no overlays selected; pass --overlay and/or --all-hub-configs", file=sys.stderr)
        return 1

    replacements: dict[str, bytes] = {}
    overlay_count = 0
    for overlay in deduped:
        overlay_count += merge_overlay_dialogs(overlay, replacements)

    suffix = datetime.now().strftime(".absod_dialog_scrub_%Y%m%d_%H%M%S")
    backup = core_zip.with_name(core_zip.name + suffix)
    if backup.exists():
        print(f"backup already exists: {backup}", file=sys.stderr)
        return 1

    scrubbed = 0
    with zipfile.ZipFile(core_zip, "r") as source:
        for name in source.namelist():
            if is_stale_absod_dialog_member(name):
                scrubbed += 1

    print(
        f"will scrub {scrubbed} AbSod dialog members; "
        f"replace/add {overlay_count} primary dialog files from {len(deduped)} overlay(s)"
    )
    if args.dry_run:
        return 0

    temp_dir = Path(tempfile.mkdtemp(prefix="absod_dialog_scrub_", dir=str(core_zip.parent)))
    temp_zip = temp_dir / core_zip.name
    try:
        with zipfile.ZipFile(core_zip, "r") as source, zipfile.ZipFile(temp_zip, "w") as target:
            written: set[str] = set()
            for info in source.infolist():
                name = info.filename
                if is_stale_absod_dialog_member(name):
                    continue
                data = replacements.get(name, source.read(name))
                replacement = zipfile.ZipInfo(name, info.date_time)
                replacement.comment = info.comment
                replacement.extra = info.extra
                replacement.internal_attr = info.internal_attr
                replacement.external_attr = info.external_attr
                replacement.compress_type = info.compress_type
                target.writestr(replacement, data)
                written.add(name)
            for name, data in replacements.items():
                if name not in written:
                    target.writestr(name, data)
        shutil.copy2(core_zip, backup)
        shutil.copy2(temp_zip, core_zip)
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

    print(f"PASS scrubbed={scrubbed} overlays={overlay_count} backup={backup}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
