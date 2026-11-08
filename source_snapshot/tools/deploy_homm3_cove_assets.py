#!/usr/bin/env python3
"""Audit the local HotA Cove source lane before Cove asset deployment.

This is intentionally an audit/manifest entry point, not a Unity bundle builder.
Cove is HotA-owned content, so future deployment should start from
vcmi/Mods/hota/mods/cove/Content and vcmi/Mods/hota/mods/cannon/Content instead
of falling back to HoMM3 Complete LOD-only extraction or native donor assets.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "custom_factions" / "homm3_cove.json"
COVE_CONTENT = ROOT / "vcmi" / "Mods" / "hota" / "mods" / "cove" / "Content"
CANNON_CONTENT = ROOT / "vcmi" / "Mods" / "hota" / "mods" / "cannon" / "Content"

HOTA_CREATURE_CONFIGS = {
    "h3_nymph": "nymph",
    "h3_oceanid": "oceanid",
    "h3_crew_mate": "crewmate",
    "h3_seaman": "seaman",
    "h3_pirate": "pirate",
    "h3_corsair": "corsair",
    "h3_sea_dog": "seadog",
    "h3_stormbird": "stormbird",
    "h3_ayssid": "ayssid",
    "h3_sea_witch": "seaWitch",
    "h3_sorceress": "sorceress",
    "h3_nix": "nix",
    "h3_nix_warrior": "nixWarrior",
    "h3_sea_serpent": "seaserpent",
    "h3_haspid": "haspid",
}

REQUIRED_COVE_FILES = [
    COVE_CONTENT / "config" / "hota" / "cove" / "faction.json",
    COVE_CONTENT / "config" / "hota" / "cove" / "dwellings.json",
    COVE_CONTENT / "config" / "hota" / "cove" / "spells" / "accurateShot.json",
    COVE_CONTENT / "config" / "hota" / "cove" / "town" / "town.json",
    COVE_CONTENT / "config" / "hota" / "cove" / "town" / "buildings.json",
    COVE_CONTENT / "config" / "hota" / "cove" / "town" / "structures.json",
    COVE_CONTENT / "data" / "hota" / "cove" / "town" / "background.png",
    COVE_CONTENT / "sprites" / "hota" / "cove" / "town" / "adventureMap" / "AVCcovz0.def",
    COVE_CONTENT / "sprites" / "hota" / "cove" / "town" / "townhall",
]

REQUIRED_COVE_AUDIO_FILES = [
    COVE_CONTENT / "sounds" / "hota" / "cove" / "creatures" / "pirate" / "PIRTSHOT.wav",
]

REQUIRED_CANNON_FILES = [
    CANNON_CONTENT / "config" / "hotaCannon" / "cannonCreature.json",
    CANNON_CONTENT / "config" / "hotaCannon" / "artillery.json",
    CANNON_CONTENT / "config" / "hotaCannon" / "cannonYard.json",
    CANNON_CONTENT / "config" / "hotaCannon" / "cannonSiegeShot.json",
    CANNON_CONTENT / "config" / "hotaCannon" / "cannonArtifact.json",
    CANNON_CONTENT / "sprites" / "hota" / "battle" / "SMCANNON.DEF",
    CANNON_CONTENT / "sprites" / "hota" / "battle" / "SMCANX.DEF",
    CANNON_CONTENT / "sprites" / "hota" / "map" / "cannonMap.def",
    CANNON_CONTENT / "sprites" / "hota" / "map" / "avcnbksm.def",
    CANNON_CONTENT / "sprites" / "hota" / "iconsLarge" / "cannonArtifact.png",
    CANNON_CONTENT / "sprites" / "hota" / "iconsLarge" / "cannonCreature.png",
    CANNON_CONTENT / "sprites" / "hota" / "iconsSmall" / "cannonArtifact.png",
    CANNON_CONTENT / "sprites" / "hota" / "iconsSmall" / "cannonCreature.png",
    CANNON_CONTENT / "sounds" / "hota" / "cannon" / "CANNSHOT.wav",
    CANNON_CONTENT / "sounds" / "hota" / "cannon" / "CANNKILL.wav",
    CANNON_CONTENT / "sounds" / "hota" / "cannon" / "CANNWNCE.wav",
]

PLUGIN_ROOT = ROOT / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod"
COVE_PAYLOAD_ROOT = PLUGIN_ROOT / "homm3_runtime_assets" / "cove" / "homm3_cove"
CANNON_PAYLOAD_ROOT = PLUGIN_ROOT / "homm3_runtime_assets" / "cannon" / "homm3_cove"
HOMM3_IMPORT_TABLE = PLUGIN_ROOT / "homm3_import.json"


def load_jsonc(path: Path) -> Any:
    text = path.read_text(encoding="utf-8-sig")
    text = re.sub(r"//.*", "", text)
    return json.loads(text)


def load_manifest() -> dict[str, Any]:
    return load_jsonc(MANIFEST)


def load_import_entries_by_sid() -> dict[str, dict[str, Any]]:
    if not HOMM3_IMPORT_TABLE.is_file():
        return {}
    table = load_jsonc(HOMM3_IMPORT_TABLE)
    entries = table.get("entries") if isinstance(table, dict) else None
    if not isinstance(entries, list):
        return {}
    result: dict[str, dict[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        game_sids = entry.get("gameUnitSids")
        if not isinstance(game_sids, list):
            continue
        for sid in game_sids:
            if isinstance(sid, str) and sid:
                result[sid] = entry
    return result


def import_lab_sid(entry: dict[str, Any]) -> str | None:
    pattern = re.compile(r"Assets[/\\]CustomUnits[/\\]homm3_lab[/\\]([^/\\]+)[/\\]")
    for key in ("battlePrefabAssetPath", "mapPrefabAssetPath"):
        value = entry.get(key)
        if not isinstance(value, str):
            continue
        match = pattern.search(value)
        if match:
            return match.group(1)
    return None


def relative(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT)).replace("\\", "/")
    except ValueError:
        return str(path)


def require_path(path: Path, missing: list[str]) -> None:
    if not path.exists():
        missing.append(relative(path))


def source_path(content_root: Path, vcmi_path: str, default_suffix: str | None = None) -> Path:
    normalized = vcmi_path.replace("\\", "/")
    if default_suffix and "." not in Path(normalized).name:
        normalized += default_suffix
    return content_root / "sprites" / normalized


def audit_creature_sources(missing: list[str]) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    config_root = COVE_CONTENT / "config" / "hota" / "cove" / "creatures"
    for custom_sid, config_key in HOTA_CREATURE_CONFIGS.items():
        config_path = config_root / f"{config_key}.json"
        require_path(config_path, missing)
        if not config_path.is_file():
            continue
        doc = load_jsonc(config_path)
        creature = doc.get(config_key)
        if not isinstance(creature, dict):
            missing.append(f"{relative(config_path)}: missing top-level {config_key!r}")
            continue
        graphics = creature.get("graphics") or {}
        row: dict[str, str] = {"config": relative(config_path)}
        for key in ("iconLarge", "iconSmall", "map", "animation"):
            value = graphics.get(key)
            if not isinstance(value, str) or not value:
                missing.append(f"{relative(config_path)}: graphics.{key} is missing")
                continue
            path = source_path(COVE_CONTENT, value)
            require_path(path, missing)
            row[key] = relative(path)
        result[custom_sid] = row
    return result


def audit_dwelling_sources(missing: list[str]) -> list[str]:
    dwellings_path = COVE_CONTENT / "config" / "hota" / "cove" / "dwellings.json"
    if not dwellings_path.is_file():
        missing.append(relative(dwellings_path))
        return []
    doc = load_jsonc(dwellings_path)
    rows: list[str] = []
    common = (doc.get("core:creatureGeneratorCommon") or {}).get("types") or {}
    for key, entry in common.items():
        template = ((entry or {}).get("templates") or {}).get("default") or {}
        animation = template.get("animation")
        if not isinstance(animation, str) or not animation:
            missing.append(f"{relative(dwellings_path)}: {key}.templates.default.animation is missing")
            continue
        path = source_path(COVE_CONTENT, animation, ".def")
        require_path(path, missing)
        rows.append(relative(path))
    return rows


def audit_town_sources(missing: list[str]) -> dict[str, Any]:
    for path in REQUIRED_COVE_FILES:
        require_path(path, missing)
    for path in REQUIRED_COVE_AUDIO_FILES:
        require_path(path, missing)
    townhall_dir = COVE_CONTENT / "sprites" / "hota" / "cove" / "town" / "townhall"
    townhall_icons = sorted(path.name for path in townhall_dir.glob("*.png")) if townhall_dir.is_dir() else []
    adventure_defs = sorted(
        path.name
        for path in (COVE_CONTENT / "sprites" / "hota" / "cove" / "town" / "adventureMap").glob("*.def")
    )
    return {
        "background": relative(COVE_CONTENT / "data" / "hota" / "cove" / "town" / "background.png"),
        "townhallIconCount": len(townhall_icons),
        "townAdventureMapDefs": adventure_defs,
    }


def audit_cannon_sources(missing: list[str]) -> dict[str, str]:
    for path in REQUIRED_CANNON_FILES:
        require_path(path, missing)
    return {path.stem: relative(path) for path in REQUIRED_CANNON_FILES}


def write_bytes_if_changed(path: Path, data: bytes) -> bool:
    if path.is_file() and path.read_bytes() == data:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return True


def write_text_if_changed(path: Path, text: str) -> bool:
    return write_bytes_if_changed(path, text.encode("utf-8"))


def deploy_cannon_payload() -> tuple[int, dict[str, Any]]:
    missing: list[str] = []
    audit_cannon_sources(missing)
    if missing:
        raise FileNotFoundError("missing Cannon source files: " + ", ".join(missing))

    changed = 0
    files: list[dict[str, str]] = []
    for source in REQUIRED_CANNON_FILES:
        rel = source.relative_to(CANNON_CONTENT)
        dest = CANNON_PAYLOAD_ROOT / rel
        if write_bytes_if_changed(dest, source.read_bytes()):
            changed += 1
        files.append(
            {
                "source": relative(source),
                "payload": str(dest.relative_to(PLUGIN_ROOT)).replace("\\", "/"),
            }
        )

    manifest = {
        "schemaVersion": 1,
        "factionSid": "homm3_cove",
        "sourceRoot": relative(CANNON_CONTENT),
        "payloadRoot": str(CANNON_PAYLOAD_ROOT.relative_to(PLUGIN_ROOT)).replace("\\", "/"),
        "files": files,
        "mechanicsStatus": "asset_only",
        "notes": [
            "This payload packages HotA Cannon config, sprites, icons, and sounds for later Cannoneering implementation.",
            "Do not treat the presence of these assets as a working Cannon mechanic; runtime behavior still needs user-guided mechanics work.",
        ],
    }
    if write_text_if_changed(CANNON_PAYLOAD_ROOT / "manifest.json", json.dumps(manifest, indent=2) + "\n"):
        changed += 1
    return changed, manifest


def deploy_cove_audio_payload() -> tuple[int, list[dict[str, str]]]:
    missing: list[str] = []
    for path in REQUIRED_COVE_AUDIO_FILES:
        require_path(path, missing)
    if missing:
        raise FileNotFoundError("missing Cove audio source files: " + ", ".join(missing))

    changed = 0
    files: list[dict[str, str]] = []
    for source in REQUIRED_COVE_AUDIO_FILES:
        rel = source.relative_to(COVE_CONTENT)
        dest = COVE_PAYLOAD_ROOT / rel
        if write_bytes_if_changed(dest, source.read_bytes()):
            changed += 1
        files.append(
            {
                "source": relative(source),
                "payload": str(dest.relative_to(PLUGIN_ROOT)).replace("\\", "/"),
            }
        )
    return changed, files


def expected_plugin_paths(manifest: dict[str, Any]) -> list[str]:
    paths: list[str] = []
    import_entries = load_import_entries_by_sid()
    for line in manifest["unitLines"]:
        variant_sids = line.get("variantSids") or {}
        for suffix in manifest["unitVariants"]:
            sid = variant_sids.get(suffix, line["baseSid"] + suffix)
            entry = import_entries.get(sid)
            bundle_name = entry.get("bundleName") if isinstance(entry, dict) else None
            lab_sid = import_lab_sid(entry) if isinstance(entry, dict) else None
            paths.extend(
                [
                    f"homm3_bundles/{bundle_name or 'custom_units_cove_' + sid}",
                    f"homm3_portraits/{sid}.png",
                    f"homm3_lab/{lab_sid or sid}/extracted_battle",
                ]
            )
    paths.extend(
        [
            "homm3_runtime_assets/faction_icons/homm3_cove/Icon_Faction_Cove.png",
            "homm3_runtime_assets/town_scene_refs/homm3_cove/Cove-in-background.png",
            "homm3_runtime_assets/town_scene_refs/homm3_cove/layers/positions.json",
            "homm3_runtime_assets/town_scene_refs/homm3_cove/building_icons/",
            "homm3_runtime_assets/map_object_refs/homm3_cove_city/",
            "homm3_runtime_assets/map_object_refs/homm3_cove_dwellings/",
            "homm3_runtime_assets/cove/homm3_cove/sounds/hota/cove/creatures/pirate/PIRTSHOT.wav",
            "homm3_runtime_assets/cannon/homm3_cove/manifest.json",
        ]
    )
    return paths


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plugin-root", type=Path, help="Optional deployed OfflineUnlockMod plugin root to audit.")
    parser.add_argument("--list-plugin-paths", action="store_true", help="Print expected Cove plugin payload paths.")
    parser.add_argument("--deploy-cove-audio", action="store_true", help="Deploy HotA Cove sidecar audio into the source plugin homm3_runtime_assets.")
    parser.add_argument("--deploy-cannon", action="store_true", help="Deploy HotA Cannon config/art/audio into the source plugin homm3_runtime_assets.")
    parser.add_argument("--json", action="store_true", help="Print the source audit as JSON.")
    args = parser.parse_args()

    manifest = load_manifest()
    expected = expected_plugin_paths(manifest)
    if args.list_plugin_paths:
        for path in expected:
            print(path)

    missing: list[str] = []
    audit = {
        "factionSid": manifest["identity"]["factionSid"],
        "sourceRoots": {
            "cove": relative(COVE_CONTENT),
            "cannon": relative(CANNON_CONTENT),
        },
        "creatures": audit_creature_sources(missing),
        "dwellings": audit_dwelling_sources(missing),
        "town": audit_town_sources(missing),
        "cannon": audit_cannon_sources(missing),
        "blockedDeploymentDebt": manifest["validation"]["allowedDebt"],
    }

    if args.deploy_cannon:
        changed, cannon_manifest = deploy_cannon_payload()
        audit["deployedCannonPayload"] = {
            "changedFiles": changed,
            "manifest": cannon_manifest,
        }
    if args.deploy_cove_audio:
        changed, files = deploy_cove_audio_payload()
        audit["deployedCoveAudioPayload"] = {
            "changedFiles": changed,
            "files": files,
        }

    plugin_missing: list[str] = []
    if args.plugin_root:
        plugin_missing = [path for path in expected if not (args.plugin_root / path).exists()]
        audit["pluginRoot"] = str(args.plugin_root)
        audit["missingPluginPaths"] = plugin_missing

    if args.json:
        print(json.dumps(audit, indent=2))
    else:
        if missing:
            for path in missing:
                print(f"MISSING SOURCE: {path}")
        else:
            print(
                "HoMM3 Cove HotA source lane is present: "
                f"{len(audit['creatures'])} creature configs, {len(audit['dwellings'])} dwellings, "
                f"{audit['town']['townhallIconCount']} townhall icons, Cannon config/art/audio checked."
            )
        if args.plugin_root:
            for path in plugin_missing:
                print(f"MISSING PLUGIN PAYLOAD: {args.plugin_root / path}")
            if plugin_missing:
                print(f"HoMM3 Cove plugin payload incomplete: {len(plugin_missing)} missing path(s).")
        if args.deploy_cannon:
            deployed = audit["deployedCannonPayload"]
            print(
                "HoMM3 Cove Cannon payload deployed: "
                f"{len(deployed['manifest']['files'])} source file(s), {deployed['changedFiles']} changed file(s)."
            )
        if args.deploy_cove_audio:
            deployed_audio = audit["deployedCoveAudioPayload"]
            print(
                "HoMM3 Cove audio payload deployed: "
                f"{len(deployed_audio['files'])} source file(s), {deployed_audio['changedFiles']} changed file(s)."
            )

    if missing:
        return 1
    if args.plugin_root and plugin_missing:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
