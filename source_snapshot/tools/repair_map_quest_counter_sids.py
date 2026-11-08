#!/usr/bin/env python3
"""Repair pack-suffix Counter* SID drift in installed/artifact Olden maps.

Alignment declares counters as ``{missionId}_started``. A buggy emit path wrote
quest CounterSet targets as ``{scenarioId}_started`` (e.g. ``*_ab_sod_started``).
Runtime then logs ``counter … dont found`` on briefing StartTurn.

This rewrites quest Counter* action/condition SIDs to match declared counters by
stripping known pack suffixes. Fail-closed when a reference cannot be uniquely
resolved. Prefer regenerating maps after ``mission_id_from_profile`` is fixed;
use this to unblock multi-hub testing without a full batch rebuild.

Usage:
  python tools/repair_map_quest_counter_sids.py --dry-run
  python tools/repair_map_quest_counter_sids.py --story-maps
  python tools/repair_map_quest_counter_sids.py --path path/to/map.map
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path
from typing import Any

_TOOLS = Path(__file__).resolve().parent
_REPO = _TOOLS.parent
_POC = _REPO / "experiments" / "campaign_port_poc"
if str(_POC) not in sys.path:
    sys.path.insert(0, str(_POC))
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

import campaign_runtime_script as campaign_script  # noqa: E402
import port_homecoming_poc as poc  # noqa: E402
from scenario_profile import KNOWN_SCENARIO_PACK_SUFFIXES  # noqa: E402

DEFAULT_STORY_MAPS = Path(
    r"V:\SteamLibrary\steamapps\common\Heroes of Might and Magic Olden Era - Golden Era"
    r"\HeroesOldenEra_Data\StreamingAssets\maps\Story_maps"
)


def _default_counter_row(sid: str, template: dict[str, Any] | None) -> dict[str, Any]:
    row = {
        "comment": "",
        "maxValue": 2147483647,
        "minValue": -2147483648,
        "sharing": "Clone",
        "sid": sid,
        "value": 0,
    }
    if isinstance(template, dict):
        for key in ("comment", "maxValue", "minValue", "sharing", "value"):
            if key in template:
                row[key] = template[key]
        row["sid"] = sid
    return row


def _strip_pack_suffix(sid: str) -> str | None:
    for suffix in KNOWN_SCENARIO_PACK_SUFFIXES:
        token = f"{suffix}_"
        if token in sid:
            return sid.replace(token, "_", 1)
    return None


def _rewrite_node(node: Any, declared: set[str], rewrites: dict[str, str]) -> int:
    changed = 0
    if isinstance(node, dict):
        kind_a = node.get("a")
        kind_c = node.get("c")
        params = node.get("p")
        if (
            (
                kind_a in campaign_script.COUNTER_ACTION_KINDS
                or kind_c in campaign_script.COUNTER_CONDITION_KINDS
            )
            and isinstance(params, list)
            and params
            and isinstance(params[0], str)
            and params[0]
        ):
            sid = params[0]
            if sid not in declared:
                stripped = _strip_pack_suffix(sid)
                target = stripped if stripped is not None else sid
                if target not in declared:
                    raise ValueError(
                        f"counter SID {sid!r} resolves to {target!r} which is "
                        f"not declared (synthesize counters before rewrite)"
                    )
                if target != sid:
                    params[0] = target
                    rewrites[sid] = target
                    changed += 1
                else:
                    raise ValueError(
                        f"counter SID {sid!r} is undeclared and has no pack suffix "
                        f"to rewrite"
                    )
        for value in node.values():
            changed += _rewrite_node(value, declared, rewrites)
    elif isinstance(node, list):
        for value in node:
            changed += _rewrite_node(value, declared, rewrites)
    return changed


def repair_map(path: Path, *, dry_run: bool = False) -> dict[str, Any]:
    container = poc.read_olden_map_container(path)
    if len(container.chunks) < 4 or not isinstance(container.chunks[3], dict):
        raise ValueError(f"{path}: missing quest chunk3")
    chunk3 = container.chunks[3]
    counters = list(chunk3.get("counters") or [])
    if not isinstance(counters, list):
        raise ValueError(f"{path}: counters must be a list")
    declared = {
        str(row.get("sid"))
        for row in counters
        if isinstance(row, dict) and isinstance(row.get("sid"), str) and row.get("sid")
    }
    quests = chunk3.get("quests") or []
    if not isinstance(quests, list):
        raise ValueError(f"{path}: quests must be a list")
    referenced = campaign_script.collect_referenced_counter_sids(quests)
    missing_before = sorted(referenced - declared)
    if not missing_before:
        return {
            "path": str(path),
            "changed": False,
            "rewrites": {},
            "synthesized": [],
            "missingBefore": [],
        }

    template = next((row for row in counters if isinstance(row, dict)), None)
    synthesized: list[str] = []
    for sid in missing_before:
        stripped = _strip_pack_suffix(sid)
        target = stripped if stripped is not None else sid
        if target in declared:
            continue
        counters.append(_default_counter_row(target, template))
        declared.add(target)
        synthesized.append(target)

    chunk3["counters"] = counters
    rewrites: dict[str, str] = {}
    changed = _rewrite_node(quests, declared, rewrites)
    referenced_after = campaign_script.collect_referenced_counter_sids(quests)
    still_missing = sorted(referenced_after - declared)
    if still_missing:
        raise ValueError(
            f"{path}: after rewrite still missing counter SIDs: {still_missing}"
        )

    if not dry_run and (changed or synthesized):
        map_sid = path.stem
        map_hash = hashlib.md5(map_sid.encode("utf-8")).hexdigest()
        poc.write_olden_map_container(path, container, map_hash)
        sidecar = path.with_suffix(".json")
        if sidecar.is_file():
            import json

            sidecar.write_text(
                json.dumps(
                    campaign_script.map_quest_sidecar_payload(chunk3),
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )

    return {
        "path": str(path),
        "changed": bool(changed or synthesized),
        "rewriteCount": changed,
        "rewrites": rewrites,
        "synthesized": synthesized,
        "missingBefore": missing_before,
    }


def iter_story_maps(root: Path) -> list[Path]:
    return sorted(
        path
        for path in root.glob("*_raw_translation.map")
        if path.is_file() and ".roe_castle_continuity_backup" not in path.name
    )


def iter_artifact_maps(repo_root: Path) -> list[Path]:
    root = repo_root / "artifacts" / "campaign_port_poc"
    if not root.is_dir():
        return []
    return sorted(
        path
        for path in root.glob("**/raw_translation_map/maps/*_raw_translation.map")
        if path.is_file()
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", type=Path, action="append", default=[])
    parser.add_argument(
        "--story-maps",
        action="store_true",
        help=f"Repair all *_raw_translation.map under {DEFAULT_STORY_MAPS}",
    )
    parser.add_argument(
        "--artifacts",
        action="store_true",
        help="Repair all raw_translation artifact maps under artifacts/campaign_port_poc",
    )
    parser.add_argument(
        "--story-maps-root",
        type=Path,
        default=DEFAULT_STORY_MAPS,
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    paths: list[Path] = list(args.path)
    if args.story_maps:
        paths.extend(iter_story_maps(args.story_maps_root))
    if args.artifacts:
        paths.extend(iter_artifact_maps(_REPO))
    # de-dupe while preserving order
    seen: set[str] = set()
    unique: list[Path] = []
    for path in paths:
        key = str(path.resolve()) if path.exists() else str(path)
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)
    paths = unique
    if not paths:
        parser.error("provide --path, --story-maps, and/or --artifacts")

    failures: list[str] = []
    repaired = 0
    clean = 0
    for path in paths:
        try:
            result = repair_map(path, dry_run=args.dry_run)
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{path}: {exc}")
            continue
        if result["changed"]:
            repaired += 1
            mode = "would rewrite" if args.dry_run else "rewrote"
            sample = list(result["rewrites"].items())[:3]
            synth = result.get("synthesized") or []
            extra = f" synth={synth[:3]}" if synth else ""
            print(f"{mode} {path.name}: {sample}{extra}")
        else:
            clean += 1

    print(
        f"maps={len(paths)} clean={clean} "
        f"{'would_repair' if args.dry_run else 'repaired'}={repaired} "
        f"failed={len(failures)}"
    )
    for row in failures[:20]:
        print(f"FAIL: {row}")
    if len(failures) > 20:
        print(f"FAIL: (+{len(failures) - 20} more)")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
