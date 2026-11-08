#!/usr/bin/env python3
"""Fail-closed contract for campaign-port custom-game menu LocKit shells.

Pins evidence-backed vanilla English budgets and requires every registered map SID
to resolve through LocKit SIDs (no literal engineering prose, no LOC: placeholders).
"""

from __future__ import annotations

import argparse
import json
import sys
import zipfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "experiments" / "campaign_port_poc"))

import homecoming_localization as loc  # noqa: E402
import scenario_menu_shell as menu  # noqa: E402

DEFAULT_CORE = (
    Path(r"V:\SteamLibrary\steamapps\common\Heroes of Might and Magic Olden Era - Golden Era")
    / "HeroesOldenEra_Data"
    / "StreamingAssets"
    / "Core.zip"
)


def fail(message: str) -> None:
    raise SystemExit(f"campaign-port scenario menu contract failed: {message}")


def require(condition: bool, message: str, errors: list[str]) -> None:
    if not condition:
        errors.append(message)


def load_custom_maps_sids(core_zip: Path) -> set[str]:
    with zipfile.ZipFile(core_zip, "r") as zf:
        doc = json.loads(zf.read("Lang/english/texts/customMaps.json").decode("utf-8-sig"))
    sids: set[str] = set()
    for section in ("tokens", "array"):
        for row in doc.get(section) or []:
            if isinstance(row, dict) and isinstance(row.get("sid"), str):
                sids.add(row["sid"])
    return sids


def validate_english_budgets(errors: list[str]) -> None:
    try:
        loc.assert_menu_shell_localization_contract()
    except ValueError as exc:
        errors.append(str(exc))
        return
    for map_sid, (title_sid, desc_sid) in sorted(menu.MENU_SHELL_BY_MAP_SID.items()):
        title = loc.CUSTOM_MAPS_EN[title_sid]
        desc = loc.CUSTOM_MAPS_EN[desc_sid]
        require(
            len(title) <= menu.VANILLA_MENU_TITLE_MAX_CHARS,
            f"{map_sid} title {title_sid!r} len={len(title)} exceeds vanilla max "
            f"{menu.VANILLA_MENU_TITLE_MAX_CHARS}",
            errors,
        )
        require(
            len(desc) <= menu.VANILLA_MENU_DESC_MAX_CHARS,
            f"{map_sid} desc {desc_sid!r} len={len(desc)} exceeds vanilla max "
            f"{menu.VANILLA_MENU_DESC_MAX_CHARS}",
            errors,
        )


def validate_required_sids_present_in_packs(errors: list[str]) -> None:
    required = set(loc.required_sids_by_file()["customMaps.json"])
    menu_sids = {
        sid
        for pair in menu.MENU_SHELL_BY_MAP_SID.values()
        for sid in pair
    }
    missing_required = sorted(menu_sids - required)
    require(
        not missing_required,
        f"menu LocKit SIDs missing from required customMaps catalog: {missing_required}",
        errors,
    )
    # Non-English packs must include every required customMaps SID.
    try:
        packs = loc.translations()
    except Exception as exc:  # noqa: BLE001 - surface pack load failures fail-closed
        errors.append(f"failed loading Homecoming locale packs: {exc}")
        return
    for lang, pack in sorted(packs.items()):
        file_pack = pack.get("customMaps.json")
        if not isinstance(file_pack, dict):
            errors.append(f"{lang}: missing customMaps.json pack")
            continue
        missing = sorted(required - set(file_pack))
        require(not missing, f"{lang}: customMaps pack missing SIDs {missing}", errors)


def validate_optional_artifact_maps(repo_root: Path, errors: list[str]) -> None:
    # raw_translation is the only campaign map generation lane, so it is the only
    # artifact map whose menu shell must resolve.
    candidates = [
        repo_root
        / "artifacts"
        / "campaign_port_poc"
        / "homecoming_poc"
        / "raw_translation_map"
        / "maps"
        / "h3_roe_castle_homecoming_raw_translation.map",
    ]
    import port_homecoming_poc as poc  # noqa: WPS440

    for path in candidates:
        if not path.is_file():
            continue
        container = poc.read_olden_map_container(path)
        meta = container.chunks[0]
        map_data = container.chunks[1]
        map_sid = str(map_data.get("fileMapName") or path.stem)
        menu.validate_menu_shell_fields(
            meta,
            map_data,
            map_sid,
            errors,
            context=f"artifact {path.relative_to(repo_root).as_posix()}",
        )


def validate_installed_core_has_menu_sids(core_zip: Path, errors: list[str]) -> None:
    if not core_zip.is_file():
        errors.append(f"missing Core.zip for installed LocKit check: {core_zip}")
        return
    present = load_custom_maps_sids(core_zip)
    required = {
        sid
        for pair in menu.MENU_SHELL_BY_MAP_SID.values()
        for sid in pair
    }
    missing = sorted(required - present)
    require(
        not missing,
        "installed Core.zip Lang/english/texts/customMaps.json missing menu SIDs "
        f"(would show LOC: placeholders): {missing}",
        errors,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    parser.add_argument("--core-zip", type=Path, default=DEFAULT_CORE)
    parser.add_argument(
        "--require-installed-core",
        action="store_true",
        help="Also fail if live Core.zip is missing any menu LocKit SIDs.",
    )
    args = parser.parse_args()
    errors: list[str] = []
    validate_english_budgets(errors)
    validate_required_sids_present_in_packs(errors)
    validate_optional_artifact_maps(args.repo_root.resolve(), errors)
    if args.require_installed_core:
        validate_installed_core_has_menu_sids(args.core_zip.resolve(), errors)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        fail(f"{len(errors)} error(s)")
    print(
        "campaign-port scenario menu contract OK: "
        f"maps={len(menu.MENU_SHELL_BY_MAP_SID)} "
        f"titleMax={menu.VANILLA_MENU_TITLE_MAX_CHARS} "
        f"descMax={menu.VANILLA_MENU_DESC_MAX_CHARS}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
