#!/usr/bin/env python3
"""Fail-closed validation for generated Factory and Bulwark runtime assets."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from build_hota_factory_bulwark_runtime_assets import (  # noqa: E402
    ASSET_MANIFEST,
    BUILD_OUT,
    CONTRACT,
    HERO_MAP,
    IMPORT_TABLE,
    PLUGIN,
    PORTRAITS,
    RUNTIME,
    SKILL_ICONS,
    SPECS,
    UPSCALED_PORTRAITS,
    expected_import_rows,
    validate_active_manifest_contract,
)


IMPORT_OWNERSHIP_KEYS = (
    "battleResPath",
    "mapResPath",
    "battlePresentationResPath",
    "mapShellResPath",
    "swapAdventureMap",
    "bundleName",
    "battlePrefabAssetPath",
    "mapPrefabAssetPath",
    "audioStemPrefix",
    "gameUnitSids",
    "xHomm3FactoryBulwarkOwned",
)


def import_ownership_view(row: dict) -> dict:
    """Factory/Bulwark ownership only. Battle hex/stride sizing is a different contract."""
    return {key: row.get(key) for key in IMPORT_OWNERSHIP_KEYS}


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def validate_png(errors: list[str], path: Path, size: tuple[int, int] | None = None) -> None:
    if not path.is_file():
        errors.append(f"missing PNG: {path}")
        return
    try:
        with Image.open(path) as image:
            image.load()
            if image.format != "PNG":
                errors.append(f"not encoded as PNG: {path}")
            if size and image.size != size:
                errors.append(f"PNG size {image.size} != {size}: {path}")
    except OSError as ex:
        errors.append(f"unreadable PNG {path}: {ex}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plugin-root", default=str(PLUGIN))
    args = parser.parse_args()
    plugin_root = Path(args.plugin_root).resolve()
    import_table = plugin_root / "homm3_import.json"
    portraits = plugin_root / PORTRAITS.relative_to(PLUGIN)
    upscaled_portraits = plugin_root / UPSCALED_PORTRAITS.relative_to(PLUGIN)
    hero_map = plugin_root / HERO_MAP.relative_to(PLUGIN)
    runtime = plugin_root / RUNTIME.relative_to(PLUGIN)
    skill_icons = plugin_root / SKILL_ICONS.relative_to(PLUGIN)
    asset_manifest = plugin_root / ASSET_MANIFEST.relative_to(PLUGIN)

    errors: list[str] = []
    for spec in SPECS:
        try:
            validate_active_manifest_contract(spec)
        except (FileNotFoundError, KeyError, TypeError, ValueError) as ex:
            errors.append(str(ex))
    expected_rows = expected_import_rows()
    # 45 since 2026-09-29: h3_sandworm_larva was retired (no Core unit; d1921a2510) and must not return.
    if len(expected_rows) != 45:
        errors.append(f"active Factory/Bulwark ownership row count {len(expected_rows)} != 45")
    if any("h3_sandworm_larva" in (row.get("gameUnitSids") or []) for row in expected_rows):
        errors.append("retired h3_sandworm_larva is back in the Factory/Bulwark ownership rows")
    expected_by_sid = {row["gameUnitSids"][0]: row for row in expected_rows}
    actual_by_sid = {}
    for row in load_json(import_table).get("entries") or []:
        for sid in row.get("gameUnitSids") or []:
            if sid not in expected_by_sid:
                continue
            if sid in actual_by_sid:
                errors.append(f"duplicate import-table SID: {sid}")
            actual_by_sid[sid] = row
    if set(actual_by_sid) != set(expected_by_sid):
        errors.append(
            f"import-table SID mismatch missing={sorted(set(expected_by_sid)-set(actual_by_sid))} "
            f"extra={sorted(set(actual_by_sid)-set(expected_by_sid))}"
        )
    for sid, expected in expected_by_sid.items():
        if import_ownership_view(actual_by_sid.get(sid) or {}) != expected:
            errors.append(f"import-table row mismatch: {sid}")

    contract = load_json(CONTRACT).get("bundles") or {}
    for row in expected_rows:
        name = row["bundleName"]
        built = BUILD_OUT / name
        if not built.is_file():
            errors.append(f"missing built bundle: {built}")
            continue
        data = built.read_bytes()
        wanted = {"length": len(data), "sha256": hashlib.sha256(data).hexdigest().upper()}
        if contract.get(name) != wanted:
            errors.append(f"bundle ownership mismatch: {name}")

    portrait_entries = load_json(portraits / "manifest.json").get("entries") or {}
    upscaled_entries = load_json(upscaled_portraits / "manifest.json").get("entries") or {}
    expected_heroes = set()
    expected_map_frames = {
        *{f"{group:02d}_00.png" for group in range(5)},
        *{f"{group:02d}_{frame:02d}.png" for group in range(5, 10) for frame in range(8)},
    }
    for spec in SPECS:
        town_root = runtime / "town_scene_refs" / spec.sid
        validate_png(errors, runtime / "faction_icons" / spec.sid / f"Icon_Faction_{spec.key.title()}.png", (256, 256))
        validate_png(errors, runtime / "town_hud_icons" / spec.sid / "fort_available.png", (128, 128))
        for rank in range(1, 4):
            suffix = "" if rank == 1 else f"_{rank}"
            validate_png(errors, skill_icons / f"skill_faction_{spec.sid}{suffix}.png", (128, 128))
        for row in expected_rows:
            if not str(row.get("bundleName", "")).startswith(f"custom_units_{spec.key}_"):
                continue
            for sid in row.get("gameUnitSids") or []:
                if not isinstance(sid, str) or not sid:
                    continue
                validate_png(errors, plugin_root / "homm3_portraits" / f"{sid}.png", None)
        validate_png(errors, town_root / f"{spec.key.title()}-in-background.png", (800, 374))
        for path in (
            town_root / "layers" / "positions.json",
            town_root / "layers" / "building_layer_map.json",
            town_root / "building_icons" / "townhall_source_map.json",
        ):
            if not path.is_file():
                errors.append(f"missing town contract: {path}")
        city = runtime / "map_object_refs" / f"{spec.sid}_city"
        dwellings = runtime / "map_object_refs" / f"{spec.sid}_dwellings"
        if len(list(city.glob("*.dir/00_00.png"))) != 1:
            errors.append(f"{spec.sid}: expected one city billboard first frame")
        expected_dwelling_count = 8 if spec.key == "factory" else 7
        if len(spec.dwellings) != expected_dwelling_count or len(list(dwellings.glob("*.dir/00_00.png"))) != expected_dwelling_count:
            errors.append(f"{spec.sid}: expected {expected_dwelling_count} dwelling billboards")
        if spec.key == "factory":
            layer_map = load_json(town_root / "layers" / "building_layer_map.json")
            icon_map = load_json(town_root / "building_icons" / "townhall_source_map.json")
            expected_layers = {"1": "tbfadw_7", "2": "tbfaup_7"}
            expected_icons = {"1": "00_37.png", "2": "00_45.png"}
            if (layer_map.get("levels") or {}).get("Build_Factory_Gantry") != expected_layers:
                errors.append("homm3_factory: Gantry layer mapping mismatch")
            if "dwellingLvl8" in (layer_map.get("sourceOnlyUnmappedHallSlots") or []) or "dwellingUpLvl8" in (layer_map.get("sourceOnlyUnmappedHallSlots") or []):
                errors.append("homm3_factory: Gantry remains source-only/unmapped")
            if (icon_map.get("map") or {}).get("Build_Factory_Gantry") != expected_icons:
                errors.append("homm3_factory: Gantry townhall icon mapping mismatch")
            placement_ids = {row.get("id") for row in (load_json(town_root / "layers" / "positions.json").get("layers") or [])}
            for layer_id in expected_layers.values():
                if layer_id not in placement_ids:
                    errors.append(f"homm3_factory: missing Gantry placement {layer_id}")
                validate_png(errors, town_root / "layers" / f"{layer_id}.png")
        for number, hero in enumerate(spec.active_heroes, 1):
            sid = f"{spec.sid}_hero_{number}"
            expected_heroes.add(sid)
            validate_png(errors, portraits / f"{sid}.png", (64, 64))
            validate_png(errors, upscaled_portraits / f"{sid}.png", (1254, 1254))
            expected_class = "might" if number <= 8 else "magic"
            for label, entries, size in (("standard", portrait_entries, [64, 64]), ("upscaled", upscaled_entries, [1254, 1254])):
                entry = entries.get(sid)
                if (not isinstance(entry, dict) or entry.get("classType") != expected_class
                        or entry.get("name") != hero.replace("_", " ").title() or entry.get("size") != size):
                    errors.append(f"{label} portrait metadata mismatch: {sid}")
        for class_type, _source_class, _member in spec.hero_classes:
            folder = hero_map / f"{spec.sid}_{class_type}"
            if {path.name for path in folder.glob("*.png")} != expected_map_frames:
                errors.append(f"hero map frame set mismatch: {folder}")

    for prefix in ("homm3_factory_hero_", "homm3_bulwark_hero_"):
        actual = {key for key in portrait_entries if key.startswith(prefix)}
        wanted = {key for key in expected_heroes if key.startswith(prefix)}
        if actual != wanted or len(actual) != 16:
            errors.append(f"active portrait roster mismatch: {prefix}")

    if not asset_manifest.is_file():
        errors.append(f"missing generated asset manifest: {asset_manifest}")
    else:
        manifest = load_json(asset_manifest)
        if "unvalidated" not in str((manifest.get("proofBoundary") or {}).get("mechanics", "")):
            errors.append("asset manifest lost the unvalidated mechanics proof boundary")
        source_rows = {row.get("factionSid"): row for row in manifest.get("sources") or []}
        if set(source_rows) != {spec.sid for spec in SPECS}:
            errors.append("asset manifest source faction set mismatch")
        for spec in SPECS:
            row = source_rows.get(spec.sid) or {}
            expected_source = {
                "factionSid": spec.sid,
                "archive": spec.archive.relative_to(ROOT).as_posix(),
                "sha256": hashlib.sha256(spec.archive.read_bytes()).hexdigest().upper(),
                "factionIconSource": spec.icon,
                "skillIconSources": list(spec.skill_icons),
                "activeHeroes": list(spec.active_heroes),
                "excludedHeroes": [{"id": hero, "reason": reason} for hero, reason in spec.excluded_heroes],
            }
            if row != expected_source:
                errors.append(f"asset manifest pinned source mismatch: {spec.sid}")
        expected_sids = sorted(expected_by_sid)
        if manifest.get("importGameUnitSids") != expected_sids:
            errors.append("asset manifest import ownership mismatch")
        source_plugin_rel = PLUGIN.relative_to(ROOT)
        for row in manifest.get("files") or []:
            try:
                relative = Path(row["path"]).relative_to(source_plugin_rel)
            except ValueError:
                errors.append(f"manifest target is outside plugin payload: {row.get('path')}")
                continue
            path = plugin_root / relative
            if not path.is_file():
                errors.append(f"manifest target missing: {path}")
                continue
            data = path.read_bytes()
            if len(data) != row["length"] or hashlib.sha256(data).hexdigest().upper() != row["sha256"]:
                errors.append(f"manifest hash mismatch: {path}")

    if errors:
        print("Factory/Bulwark runtime asset validation FAILED", file=sys.stderr)
        for error in errors:
            print(f" - {error}", file=sys.stderr)
        return 1
    print(f"Factory/Bulwark runtime asset validation passed under {plugin_root}: {len(expected_rows)} unit rows, 32 active heroes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
