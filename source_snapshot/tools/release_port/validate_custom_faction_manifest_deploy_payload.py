#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CSPROJ = ROOT / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod" / "OfflineUnlockMod.csproj"
EXPECTED_DEPLOY_INCLUDE = r'Include="$(MSBuildThisFileDirectory)..\..\custom_factions\**\homm3_*.json"'


def is_faction_manifest_name(path: Path) -> bool:
    return path.name.startswith("homm3_") and path.suffix.lower() == ".json"


def validate_csproj(csproj: Path) -> list[str]:
    errors: list[str] = []
    if not csproj.exists():
        return [f"missing csproj: {csproj}"]

    text = csproj.read_text(encoding="utf-8-sig")
    if EXPECTED_DEPLOY_INCLUDE not in text:
        errors.append(
            "DeployCustomFactionManifest must deploy only custom_factions/**/homm3_*.json; "
            "do not deploy support metadata such as custom_law_targets.json or custom_law_diag_profiles.json."
        )
    if r"custom_factions\**\*.json" in text:
        errors.append(
            "DeployCustomFactionManifest contains broad custom_factions/**/*.json pattern; "
            "this breaks startup because the runtime registry treats deployed JSONs as faction manifests."
        )
    return errors


def validate_deployed_dir(deployed_custom_factions: Path) -> list[str]:
    errors: list[str] = []
    if not deployed_custom_factions.exists():
        return [f"deployed custom_factions directory does not exist: {deployed_custom_factions}"]
    if not deployed_custom_factions.is_dir():
        return [f"deployed custom_factions path is not a directory: {deployed_custom_factions}"]

    for path in sorted(deployed_custom_factions.rglob("*.json")):
        if not is_faction_manifest_name(path):
            errors.append(
                "deployed non-manifest JSON under custom_factions: "
                + str(path)
                + " (only homm3_*.json faction manifests belong in the deployed registry input)"
            )
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Validate that custom faction manifest deployment is fail-closed and does not copy "
            "custom law support metadata into the runtime faction registry directory."
        )
    )
    parser.add_argument("--csproj", type=Path, default=DEFAULT_CSPROJ)
    parser.add_argument(
        "--deployed-custom-factions",
        type=Path,
        default=None,
        help="Optional deployed BepInEx/plugins/OfflineUnlockMod/custom_factions directory to inspect.",
    )
    args = parser.parse_args()

    errors = validate_csproj(args.csproj)
    if args.deployed_custom_factions is not None:
        errors.extend(validate_deployed_dir(args.deployed_custom_factions))

    print(f"csproj: {args.csproj}")
    if args.deployed_custom_factions is not None:
        print(f"deployed custom_factions: {args.deployed_custom_factions}")
    print(f"errors: {errors}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
