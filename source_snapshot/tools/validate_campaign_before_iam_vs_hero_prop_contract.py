#!/usr/bin/env python3
"""Fail-closed: BeforeIamVsHero.p must equal a propHeroes.heroSid on the same map.

Native OE arms colocated EVENT+hero dialogs by matching interruption.p[0] against
the fought hero's propHeroes.heroSid. Campaign stub SIDs (h3_campaign_placed_*)
and roster SIDs are both valid — they must simply agree with emit.

Scope: HUB_CONFIGS raw_translation map artifacts (and optionally installed
Story_maps h3_*_raw_translation maps). Vanilla c_M* maps are out of scope.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
POC = ROOT / "experiments" / "campaign_port_poc"
HUB_INSTALLER = ROOT / "tools" / "install_roe_castle_continuity_weave.py"
DEFAULT_STORY_MAPS = Path(
    r"V:/SteamLibrary/steamapps/common/Heroes of Might and Magic Olden Era - Golden Era"
    r"/HeroesOldenEra_Data/StreamingAssets/maps/Story_maps"
)


def _load_hub_configs(repo_root: Path) -> dict[str, Any]:
    installer = repo_root / "tools" / "install_roe_castle_continuity_weave.py"
    spec = importlib.util.spec_from_file_location("roe_castle_hub_installer", installer)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load HUB_CONFIGS from {installer}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    hubs = getattr(mod, "HUB_CONFIGS", None)
    if not isinstance(hubs, dict):
        raise RuntimeError(f"HUB_CONFIGS missing in {installer}")
    return hubs


def hub_configs_map_paths(repo_root: Path) -> list[tuple[str, Path]]:
    """Return (mapSid, artifact .map path) for every HUB_CONFIGS raw_translation install."""
    hubs = _load_hub_configs(repo_root)
    out: list[tuple[str, Path]] = []
    seen: set[Path] = set()
    for cfg in hubs.values():
        if not isinstance(cfg, dict):
            continue
        for install in cfg.get("mapInstalls") or []:
            if not isinstance(install, dict):
                continue
            map_sid = install.get("mapSid")
            artifact = install.get("artifact")
            if not isinstance(map_sid, str) or not isinstance(artifact, Path):
                continue
            maps_dir = (repo_root / artifact).resolve()
            if maps_dir.name != "maps":
                maps_dir = maps_dir / "maps" if (maps_dir / "maps").is_dir() else maps_dir
            map_path = maps_dir / f"{map_sid}.map"
            if map_path in seen:
                continue
            seen.add(map_path)
            out.append((map_sid, map_path))
    return out


def prop_hero_sids(map_chunk: dict[str, Any]) -> set[str]:
    props = map_chunk.get("objectsProperties") or {}
    if not isinstance(props, dict):
        return set()
    sids: set[str] = set()
    for row in props.get("propHeroes") or []:
        if not isinstance(row, dict):
            continue
        sid = row.get("heroSid")
        if isinstance(sid, str) and sid.strip():
            sids.add(sid.strip())
    return sids


def validate_map_container(
    *,
    label: str,
    container: Any,
    errors: list[str],
) -> dict[str, Any]:
    chunks = getattr(container, "chunks", None)
    if not isinstance(chunks, list) or len(chunks) < 4:
        errors.append(f"{label}: map must have map + QuestScript chunks")
        return {"label": label, "beforeIamVsHero": 0, "ok": False}
    map_chunk = chunks[1]
    runtime_chunk = chunks[3]
    if not isinstance(map_chunk, dict) or not isinstance(runtime_chunk, dict):
        errors.append(f"{label}: chunks[1] and chunks[3] must be objects")
        return {"label": label, "beforeIamVsHero": 0, "ok": False}

    hero_sids = prop_hero_sids(map_chunk)
    checked = 0
    for row in runtime_chunk.get("interruptions") or []:
        if not isinstance(row, dict) or row.get("interruption") != "BeforeIamVsHero":
            continue
        checked += 1
        target = (row.get("p") or [None])[0]
        interrupt_sid = str(row.get("sid") or "")
        if not isinstance(target, str) or not target.strip():
            errors.append(
                f"{label}: BeforeIamVsHero {interrupt_sid!r} missing non-empty p[0]"
            )
            continue
        if target not in hero_sids:
            errors.append(
                f"{label}: BeforeIamVsHero {interrupt_sid!r} p[0]={target!r} "
                f"not in propHeroes.heroSid ({sorted(hero_sids)})"
            )
    return {"label": label, "beforeIamVsHero": checked, "ok": True}


def validate_map_path(
    *,
    label: str,
    map_path: Path,
    map_reader: Any,
    errors: list[str],
) -> dict[str, Any] | None:
    if not map_path.is_file():
        errors.append(f"{label}: missing map artifact {map_path}")
        return None
    try:
        container = map_reader(map_path)
    except Exception as exc:  # pragma: no cover - diagnostic is the contract output
        errors.append(f"{label}: failed to read map {map_path}: {exc}")
        return None
    return validate_map_container(label=label, container=container, errors=errors)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Validate BeforeIamVsHero interruption targets against propHeroes.heroSid "
            "for HUB_CONFIGS raw_translation maps."
        )
    )
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    parser.add_argument(
        "--installed-story-maps",
        type=Path,
        default=None,
        help=(
            "Also validate installed h3_*_raw_translation.map under Story_maps "
            f"(default when flag present without path: {DEFAULT_STORY_MAPS})"
        ),
        nargs="?",
        const=DEFAULT_STORY_MAPS,
    )
    args = parser.parse_args()
    repo_root = args.repo_root.resolve()
    sys.path.insert(0, str(repo_root / "experiments" / "campaign_port_poc"))
    import port_homecoming_poc as poc  # noqa: WPS433

    errors: list[str] = []
    results: list[dict[str, Any]] = []

    for map_sid, map_path in hub_configs_map_paths(repo_root):
        result = validate_map_path(
            label=map_sid,
            map_path=map_path,
            map_reader=poc.read_olden_map_container,
            errors=errors,
        )
        if result is not None:
            results.append(result)

    if args.installed_story_maps is not None:
        story_maps = Path(args.installed_story_maps).resolve()
        if not story_maps.is_dir():
            errors.append(f"installed Story_maps dir missing: {story_maps}")
        else:
            for map_path in sorted(story_maps.glob("h3_*_raw_translation.map")):
                result = validate_map_path(
                    label=f"installed:{map_path.name}",
                    map_path=map_path,
                    map_reader=poc.read_olden_map_container,
                    errors=errors,
                )
                if result is not None:
                    results.append(result)

    if errors:
        print("Campaign BeforeIamVsHero-in-propHeroes contract FAIL")
        for error in errors:
            print(f"- {error}")
        return 1

    print("Campaign BeforeIamVsHero-in-propHeroes contract PASS")
    print(
        json.dumps(
            {
                "mapsChecked": len(results),
                "beforeIamVsHeroTotal": sum(r.get("beforeIamVsHero", 0) for r in results),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
