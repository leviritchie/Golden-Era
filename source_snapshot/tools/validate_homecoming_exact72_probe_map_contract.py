#!/usr/bin/env python3
"""Validate the standalone Homecoming exact-72 minimap probe contract."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

MAP_SID = "h3_roe_castle_homecoming_exact72_probe"
SOURCE_MAP_SID = "h3_roe_castle_homecoming_single_layer"
POLICY_ID = "crop_80_envelope_to_exact72_offset_4_4_mapview_ceil_5x5"
OUT_WIDTH = 72
OUT_HEIGHT = 72
MAP_VIEW_SEC_SIZE = 5
ENVELOPE_PADDING_BLOCKER_SID = "homm3_envelope_padding_blocker"
ARTIFACT_ROOT = Path("artifacts") / "campaign_port_poc" / "homecoming_poc" / "exact72_probe_map"
BUILDER = Path("experiments") / "campaign_port_poc" / "build_homecoming_exact72_probe_map.py"
INSTALLER = Path("tools") / "install_homecoming_exact72_probe_map.py"
MINIMAP_HOOK = (
    Path("Heroes of Might & Magic Olden Era Playtest")
    / "OfflineUnlockMod"
    / "Homm3CustomBiomeMinimapHook.cs"
)
GAME_SYMBOLS = (
    Path("Heroes of Might & Magic Olden Era Playtest") / "OfflineUnlockMod" / "GameSymbols.cs"
)
HOMECOMING_PROFILE = (
    Path("Heroes of Might & Magic Olden Era Playtest")
    / "OfflineUnlockMod"
    / "HomecomingMapProfile.cs"
)

REQUIRED_BUILDER_TOKENS = [
    f'MAP_SID = "{MAP_SID}"',
    f'SOURCE_MAP_SID = "{SOURCE_MAP_SID}"',
    f'POLICY_ID = "{POLICY_ID}"',
    "INPUT_WIDTH = 80",
    "CROP_OFFSET_X = 4",
    "OUT_WIDTH = 72",
    "MAP_VIEW_SEC_SIZE = (OUT_WIDTH + VIEW_SECTOR_SIZE - 1) // VIEW_SECTOR_SIZE",
    "does not auto-emit single_layer",
    '"homecomingMapProfileRegistered": False',
]

FORBIDDEN_BUILDER_TOKENS = [
    "Story_maps",
    "patch_core_zip",
]

REQUIRED_INSTALLER_TOKENS = [
    f'MAP_SID = "{MAP_SID}"',
    'INSTALL_DESTINATION_POLICY = "maps_root_custom_only"',
    "Story_maps",
]

FORBIDDEN_INSTALLER_TOKENS = [
    "patch_core_zip",
    "Core.zip",
    "Story_maps/",
]

REQUIRED_CS_TOKENS = [
    f'Exact72ProbeMapSid = "{MAP_SID}"',
    'mapSid=',
    "ReadMapSid",
    "ClampRectToMapBounds",
    "ref RectInt c",
]


def require(condition: bool, message: str, errors: list[str]) -> None:
    if not condition:
        errors.append(message)


def load_json(path: Path, errors: list[str]) -> dict[str, Any]:
    if not path.exists():
        errors.append(f"missing JSON: {path}")
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception as ex:
        errors.append(f"could not read {path}: {ex}")
        return {}
    if not isinstance(payload, dict):
        errors.append(f"JSON is not an object: {path}")
        return {}
    return payload


def require_tokens(path: Path, required: list[str], forbidden: list[str], label: str, errors: list[str]) -> None:
    if not path.is_file():
        errors.append(f"missing {label}: {path}")
        return
    text = path.read_text(encoding="utf-8")
    for token in required:
        require(token in text, f"{label} missing required token {token!r}", errors)
    for token in forbidden:
        require(token not in text, f"{label} has forbidden token {token!r}", errors)


def validate_installer_story_maps_ban(path: Path, errors: list[str]) -> None:
    if not path.is_file():
        return
    text = path.read_text(encoding="utf-8")
    require('INSTALL_DESTINATION_POLICY = "maps_root_custom_only"' in text, "installer must pin maps_root_custom_only", errors)
    require("forbid_story_maps" in text or "Story_maps" in text and "must not" in text.lower(), "installer must refuse Story_maps install", errors)
    require("patch_core_zip" not in text, "installer must not patch Core.zip", errors)
    require("zipfile" not in text, "installer must not open zip archives for Core merges", errors)


def validate_artifact(repo_root: Path, errors: list[str]) -> None:
    sys.path.insert(0, str(repo_root / "experiments" / "campaign_port_poc"))
    import port_homecoming_poc as poc  # noqa: WPS433

    root = repo_root / ARTIFACT_ROOT
    map_path = root / "maps" / f"{MAP_SID}.map"
    script_path = root / "maps" / f"{MAP_SID}.json"
    manifest_path = root / "install_manifest.json"
    require(map_path.is_file(), f"missing probe map {map_path}", errors)
    require(script_path.is_file(), f"missing probe script {script_path}", errors)
    manifest = load_json(manifest_path, errors)
    if not manifest:
        return
    require(manifest.get("mapSid") == MAP_SID, "manifest mapSid mismatch", errors)
    require(manifest.get("policyId") == POLICY_ID, "manifest policyId mismatch", errors)
    require(manifest.get("homecomingMapProfileRegistered") is False, "probe must stay profile-free", errors)
    require(manifest.get("installLane") == "maps_root_custom_only", "manifest installLane mismatch", errors)

    if not map_path.is_file():
        return
    container = poc.read_olden_map_container(map_path)
    meta = container.chunks[0]
    map_data = container.chunks[1]
    require(meta.get("sizeX") == OUT_WIDTH and meta.get("sizeZ") == OUT_HEIGHT, "meta size must be 72x72", errors)
    require(map_data.get("sizeX_") == OUT_WIDTH and map_data.get("sizeZ_") == OUT_HEIGHT, "MapData size must be 72x72", errors)
    expected = OUT_WIDTH * OUT_HEIGHT
    for key in ("tilesMap", "waterMap", "roadsMap", "levelsMap", "climbsMap", "customAreasPainting"):
        values = map_data.get(key)
        require(isinstance(values, list) and len(values) == expected, f"{key} must be length {expected}", errors)
    views = map_data.get("views")
    require(
        views
        == [
            {
                "name": "surface",
                "minSecX": 0,
                "minSecZ": 0,
                "secSizeX": MAP_VIEW_SEC_SIZE,
                "secSizeZ": MAP_VIEW_SEC_SIZE,
                "isUnderground": False,
                "stack": -1,
            }
        ],
        "views must be surface-only ceil 5x5 overhang",
        errors,
    )
    areas = map_data.get("areas")
    require(
        isinstance(areas, list)
        and len(areas) == 1
        and isinstance(areas[0], dict)
        and areas[0].get("nodes") == list(range(expected)),
        "areas must cover exact 72x72 nodes",
        errors,
    )
    objects = map_data.get("objects") or []
    require(isinstance(objects, list), "objects must be a list", errors)
    for group in objects:
        if not isinstance(group, dict):
            errors.append("object group must be an object")
            continue
        require(group.get("sid") != ENVELOPE_PADDING_BLOCKER_SID, "probe must not contain envelope padding blockers", errors)
        for node in group.get("nodes") or []:
            require(isinstance(node, int) and 0 <= node < expected, f"object node out of exact72 range: {node}", errors)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--skip-generate", action="store_true")
    args = parser.parse_args(argv)
    repo_root = args.repo_root.resolve()
    errors: list[str] = []

    builder = repo_root / BUILDER
    installer = repo_root / INSTALLER
    require_tokens(builder, REQUIRED_BUILDER_TOKENS, FORBIDDEN_BUILDER_TOKENS, "builder", errors)
    validate_installer_story_maps_ban(installer, errors)
    require_tokens(repo_root / GAME_SYMBOLS, [f'Exact72ProbeMapSid = "{MAP_SID}"'], [], "GameSymbols", errors)
    require_tokens(
        repo_root / MINIMAP_HOOK,
        [
            'mapSid=',
            "ReadMapSid",
            "ClampRectToMapBounds",
            "ref RectInt c",
            "EnsureApplied(config, mapData)",
            "MaxTileCodeInMap",
            "_sealedBiomsLengthByConfigId",
        ],
        [],
        "minimap hook",
        errors,
    )
    profile_text = (repo_root / HOMECOMING_PROFILE).read_text(encoding="utf-8") if (repo_root / HOMECOMING_PROFILE).is_file() else ""
    require(MAP_SID not in profile_text, "Exact72 probe SID must not be registered in HomecomingMapProfile", errors)

    if not args.skip_generate:
        result = subprocess.run([sys.executable, str(builder)], cwd=str(repo_root), check=False)
        if result.returncode != 0:
            errors.append("exact72 probe generate failed")
    validate_artifact(repo_root, errors)

    if errors:
        print("FAIL")
        for item in errors:
            print(f"- {item}")
        return 1
    print("PASS")
    print(f"- artifact {ARTIFACT_ROOT / 'maps' / (MAP_SID + '.map')}")
    print(f"- policy {POLICY_ID}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
