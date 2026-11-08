#!/usr/bin/env python3
"""Fail-closed contract: Session.Loader map-load hang preflight.

Validates installed Golden Era Core.zip (+ optional overlays) and campaign maps
against the hang signatures in ``tools/map_load_preflight.py`` before launch.

Usage examples:
  python tools/validate_map_load_preflight_contract.py
  python tools/validate_map_load_preflight_contract.py --hub good2
  python tools/validate_map_load_preflight_contract.py --map-sid h3_roe_castle_steadwick_liberation_raw_translation
  python tools/validate_map_load_preflight_contract.py --list-signatures

Wire-up: continuity installer, Homecoming raw installer, MSBuild
ValidateMapLoadPreflightContract, and validate_roe_castle_campaign_continuity_contract.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any, Sequence

_TOOLS_DIR = Path(__file__).resolve().parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from map_load_preflight import (
    CoreZipIndex,
    CORE_ZIP_REL,
    STORY_MAPS_REL,
    collect_overlay_members,
    format_issues,
    hang_signature_checklist,
    run_installed_campaign_preflight,
)

DEFAULT_GAME_ROOT = Path(
    r"V:\SteamLibrary\steamapps\common\Heroes of Might and Magic Olden Era - Golden Era"
)


def load_hub_map_installs() -> dict[str, list[dict[str, Any]]]:
    """Derive preflight map checks from the continuity installer HUB_CONFIGS.

    Keeps RoE + AB/SoD hubs in one source of truth (install_roe_castle_continuity_weave).
    """
    install_path = _TOOLS_DIR / "install_roe_castle_continuity_weave.py"
    spec = importlib.util.spec_from_file_location(
        "install_roe_castle_continuity_weave", install_path
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load installer module from {install_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    hub_configs = getattr(module, "HUB_CONFIGS", None)
    if not isinstance(hub_configs, dict):
        raise RuntimeError("installer HUB_CONFIGS missing or invalid")

    out: dict[str, list[dict[str, Any]]] = {}
    for hub, cfg in hub_configs.items():
        if not isinstance(cfg, dict):
            continue
        hub_sid = str(cfg["hubSid"])
        missions = list(cfg.get("missions") or ())
        map_installs = list(cfg.get("mapInstalls") or [])
        if len(missions) != len(map_installs):
            raise RuntimeError(
                f"hub {hub!r}: missions ({len(missions)}) != mapInstalls ({len(map_installs)})"
            )
        rows: list[dict[str, Any]] = []
        for mission_file, row in zip(missions, map_installs):
            rows.append(
                {
                    "mapSid": str(row["mapSid"]),
                    "missionMember": f"campaigns/{hub_sid}/missions/{mission_file}",
                    "coreOverlay": Path(row["coreOverlay"]),
                }
            )
        out[str(hub)] = rows
    return out


HUB_MAP_INSTALLS = load_hub_map_installs()
ALL_HUB_CHOICES = tuple(sorted(HUB_MAP_INSTALLS))


def load_mission_from_core(
    core_zip: Path | CoreZipIndex, member: str
) -> dict[str, Any] | None:
    if isinstance(core_zip, CoreZipIndex):
        if member not in core_zip:
            return None
        return json.loads(core_zip.read(member).decode("utf-8-sig"))
    with CoreZipIndex(core_zip) as source:
        if member not in source:
            return None
        return json.loads(source.read(member).decode("utf-8-sig"))


def build_map_checks(
    repo_root: Path,
    game_root: Path,
    core_zip: Path | CoreZipIndex,
    *,
    hubs: Sequence[str],
    map_sid_filter: str | None,
    include_overlays: bool,
) -> tuple[list[dict[str, Any]], dict[str, bytes]]:
    overlay_roots: list[Path] = []
    checks: list[dict[str, Any]] = []
    for hub in hubs:
        for row in HUB_MAP_INSTALLS.get(hub, []):
            map_sid = row["mapSid"]
            if map_sid_filter and map_sid != map_sid_filter:
                continue
            mission_member = row["missionMember"]
            mission = load_mission_from_core(core_zip, mission_member)
            overlay = repo_root / row["coreOverlay"]
            if include_overlays and overlay.is_dir():
                overlay_roots.append(overlay)
            checks.append(
                {
                    "mapSid": map_sid,
                    "mapPath": game_root / STORY_MAPS_REL / f"{map_sid}.map",
                    "mission": mission,
                    "missionLabel": mission_member,
                }
            )
    members = collect_overlay_members(overlay_roots) if include_overlays else {}
    return checks, members


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--game-root", type=Path, default=DEFAULT_GAME_ROOT)
    parser.add_argument(
        "--hub",
        action="append",
        choices=ALL_HUB_CHOICES,
        default=None,
        help="StoryHub(s) to scan (default: all hubs present in Core).",
    )
    parser.add_argument("--map-sid", type=str, default=None)
    parser.add_argument(
        "--include-pending-overlays",
        action="store_true",
        help="Merge artifact core_overlay members into effective Core before checks.",
    )
    parser.add_argument(
        "--core-only",
        action="store_true",
        help="Only validate Meta/ObjectConfig integrity (skip map + StoryHub checks).",
    )
    parser.add_argument("--list-signatures", action="store_true")
    args = parser.parse_args()

    if args.list_signatures:
        print(json.dumps(hang_signature_checklist(), indent=2, ensure_ascii=False))
        return 0

    repo_root = args.repo_root.resolve()
    game_root = args.game_root.resolve()
    core_zip = game_root / CORE_ZIP_REL
    if not core_zip.is_file():
        print(f"map load preflight FAILED: missing Core.zip {core_zip}", file=sys.stderr)
        return 1

    hubs = list(args.hub) if args.hub else list(ALL_HUB_CHOICES)
    # Drop hubs whose campaign folder is absent unless explicitly requested.
    with CoreZipIndex(core_zip) as source:
        if not args.hub:
            names = source.names
            hubs = [
                hub
                for hub in hubs
                if any(
                    row["missionMember"] in names
                    for row in HUB_MAP_INSTALLS.get(hub, [])
                )
            ]

        if args.core_only:
            map_checks: list[dict[str, Any]] = []
            overlay_members: dict[str, bytes] = {}
        else:
            map_checks, overlay_members = build_map_checks(
                repo_root,
                game_root,
                source,
                hubs=hubs,
                map_sid_filter=args.map_sid,
                include_overlays=args.include_pending_overlays,
            )

        issues = run_installed_campaign_preflight(
            game_root=game_root,
            core_zip=core_zip,
            core_index=source,
            overlay_members=overlay_members,
            map_checks=map_checks,
            require_story_maps=not args.core_only,
        )
    text = format_issues(issues)
    if issues:
        print(text, file=sys.stderr)
        return 1
    print(text)
    print(f"  hubs={hubs or ['(core-only)']}")
    print(f"  mapChecks={len(map_checks)}")
    print(f"  signatures={len(hang_signature_checklist())}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
