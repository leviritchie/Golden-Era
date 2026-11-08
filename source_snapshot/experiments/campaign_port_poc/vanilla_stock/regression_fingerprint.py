"""Stable golden fingerprints for vanilla_stock regression maps.

Fingerprints intentionally omit absolute paths, object-id lists, and verbose
row dumps so intentional emit refactors that preserve semantics stay quiet,
while ownership, victory, event, omit, and access-count drift fails closed.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


SCHEMA = "homm3.vanilla_stock.regression_fingerprint.v1"


class VanillaStockFingerprintError(ValueError):
    pass


def _as_int(value: Any, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise VanillaStockFingerprintError(f"{field} must be int, got {type(value).__name__}")
    return value


def _sorted_int_keys(mapping: Any) -> dict[str, Any]:
    if not isinstance(mapping, dict):
        return {}
    items: list[tuple[int, Any]] = []
    for key, value in mapping.items():
        try:
            items.append((int(key), value))
        except (TypeError, ValueError):
            continue
    return {str(k): v for k, v in sorted(items)}


def _sorted_owner_lists(mapping: Any) -> dict[str, list[int]]:
    out: dict[str, list[int]] = {}
    for key, value in _sorted_int_keys(mapping).items():
        if not isinstance(value, list):
            raise VanillaStockFingerprintError(f"h3ColorToFinalOwners[{key}] must be a list")
        owners = sorted(int(x) for x in value)
        out[key] = owners
    return out


def _histogram(mapping: Any) -> dict[str, int]:
    if not isinstance(mapping, dict):
        return {}
    out: dict[str, int] = {}
    for key, value in mapping.items():
        out[str(key)] = _as_int(value, field=f"histogram[{key}]")
    return dict(sorted(out.items()))


def extract_regression_fingerprint(
    *,
    scenario_id: str,
    map_sid: str,
    era: str,
    format_version: int | None,
    manifest: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(manifest, dict):
        raise VanillaStockFingerprintError("manifest must be an object")
    if str(manifest.get("mapSid") or "") != map_sid:
        raise VanillaStockFingerprintError(
            f"manifest mapSid {manifest.get('mapSid')!r} != expected {map_sid!r}"
        )

    ownership = manifest.get("ownershipContract") or {}
    if not isinstance(ownership, dict):
        raise VanillaStockFingerprintError("ownershipContract missing")
    renumber = ownership.get("ownerRenumber") or {}
    if not isinstance(renumber, dict):
        raise VanillaStockFingerprintError("ownerRenumber missing")
    ai_split = ownership.get("aiOwnerFactionSplit") or {}
    if not isinstance(ai_split, dict):
        ai_split = {}
    orphan_ai = ownership.get("orphanAiNeutralTownBind") or {}
    orphan_playable = ownership.get("orphanPlayableNeutralTownBind") or {}
    if not isinstance(orphan_ai, dict):
        orphan_ai = {}
    if not isinstance(orphan_playable, dict):
        orphan_playable = {}

    victory = manifest.get("victory") or {}
    if not isinstance(victory, dict):
        raise VanillaStockFingerprintError("victory missing")
    objects = manifest.get("objects") or {}
    if not isinstance(objects, dict):
        raise VanillaStockFingerprintError("objects missing")
    events = manifest.get("events") or {}
    if not isinstance(events, dict):
        events = {}
    timed = manifest.get("timedEvents") or {}
    if not isinstance(timed, dict):
        timed = {}
    access = manifest.get("accessContract") or {}
    if not isinstance(access, dict):
        access = {}
    portal_clear = access.get("subterraneanPortalGateClear") or {}
    town_clear = access.get("townGateSouthApproachClear") or {}
    if not isinstance(portal_clear, dict):
        portal_clear = {}
    if not isinstance(town_clear, dict):
        town_clear = {}
    scenery = manifest.get("sceneryFootprints") or {}
    if not isinstance(scenery, dict):
        scenery = {}
    serialization = manifest.get("serializationShape") or {}
    if not isinstance(serialization, dict):
        serialization = {}

    raw_spawns = manifest.get("spawns")
    if isinstance(raw_spawns, dict):
        spawn_list = raw_spawns.get("spawns") or []
    elif isinstance(raw_spawns, list):
        spawn_list = raw_spawns
    else:
        spawn_list = []
    spawn_rows: list[dict[str, Any]] = []
    for row in spawn_list:
        if not isinstance(row, dict):
            continue
        spawn_rows.append(
            {
                "owner": _as_int(row.get("owner"), field="spawn.owner"),
                "spawnType": _as_int(row.get("spawnType"), field="spawn.spawnType"),
                "factionSid": str(row.get("factionSid") or row.get("faction") or ""),
                "isHeroDefined": bool(row.get("isHeroDefined")),
                "isCityDefined": bool(row.get("isCityDefined")),
            }
        )
    spawn_rows.sort(key=lambda r: (r["owner"], r["spawnType"], r["factionSid"]))

    omitted_reward_kinds = sorted(
        {
            str(gap.get("reason") or gap.get("gap") or gap.get("kind") or "unknown")
            for gap in (events.get("omittedRewardGaps") or [])
            if isinstance(gap, dict)
        }
    )
    timed_omitted_kinds = sorted(
        {
            str(gap.get("reason") or gap.get("gap") or gap.get("kind") or "unknown")
            for gap in (timed.get("omittedGaps") or [])
            if isinstance(gap, dict)
        }
    )

    players_count = _as_int(
        ownership.get("playersCount", renumber.get("playersCount")),
        field="playersCount",
    )
    human_owner = _as_int(
        ownership.get("humanOldenOwner", renumber.get("humanOldenOwner")),
        field="humanOldenOwner",
    )

    return {
        "schema": SCHEMA,
        "id": scenario_id,
        "mapSid": map_sid,
        "era": era,
        "formatVersion": format_version,
        "sourceSize": manifest.get("sourceSize"),
        "sourceLayers": manifest.get("sourceLayers"),
        "playersCount": players_count,
        "humanOwner": human_owner,
        "h3ColorToFinalOwners": _sorted_owner_lists(ownership.get("h3ColorToFinalOwners")),
        "ownerRenumberMapping": {
            str(k): _as_int(v, field=f"ownerRenumber[{k}]")
            for k, v in _sorted_int_keys(renumber.get("ownerMapping")).items()
        },
        "factionSplitRemappedObjectCount": len(ai_split.get("remappedObjectIds") or []),
        "demotedMixedFactionCityCount": len(ai_split.get("demotedMixedFactionCities") or []),
        "orphanAiBoundCount": _as_int(orphan_ai.get("boundCount") or 0, field="orphanAiBoundCount"),
        "orphanPlayableBoundCount": _as_int(
            orphan_playable.get("boundCount") or 0,
            field="orphanPlayableBoundCount",
        ),
        "victoryMode": str(victory.get("mode") or ""),
        "mineEntityCount": victory.get("mineEntityCount"),
        "playableFinalOwners": sorted(int(x) for x in (victory.get("playableFinalOwners") or [])),
        "humanFinalOwners": sorted(int(x) for x in (victory.get("humanFinalOwners") or [])),
        "defeatAllEnemiesEnabled": bool(victory.get("defeatAllEnemiesEnabled")),
        "spawnRows": spawn_rows,
        "eventCount": events.get("eventCount"),
        "unguardedEventCount": events.get("unguardedCount"),
        "guardedEventCount": events.get("guardedCount"),
        "giveResActionCount": events.get("giveResActionCount") or 0,
        "omittedRewardGapKinds": omitted_reward_kinds,
        "timedBriefingCount": timed.get("briefingCount"),
        "timedGrantCount": timed.get("timedGrantCount"),
        "timedOmittedGapKinds": timed_omitted_kinds,
        "emittedInstanceCount": objects.get("emittedInstanceCount"),
        "cityCount": objects.get("cityCount"),
        "portalCount": objects.get("portalCount"),
        "mineCount": objects.get("mineCount"),
        "mapEventCount": objects.get("mapEventCount"),
        "randomSquadCount": objects.get("randomSquadCount"),
        "randomItemCount": objects.get("randomItemCount"),
        "omitReasonHistogram": _histogram(objects.get("omitReasonHistogram")),
        "accessPortalClearedCount": _as_int(
            portal_clear.get("clearedObjectCount") or 0,
            field="accessPortalClearedCount",
        ),
        "accessTownApproachClearedCount": _as_int(
            town_clear.get("clearedApproachCount") or 0,
            field="accessTownApproachClearedCount",
        ),
        "sceneryFootprintPlacementCount": scenery.get("placementCount"),
        "objectsPropertiesKeys": list(serialization.get("objectsPropertiesKeys") or []),
        "campaignInfoPreserved": bool(serialization.get("campaignInfoPreserved")),
    }


def load_fingerprint(path: Path) -> dict[str, Any]:
    doc = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(doc, dict) or doc.get("schema") != SCHEMA:
        raise VanillaStockFingerprintError(f"unsupported fingerprint schema: {path}")
    return doc


def write_fingerprint(path: Path, fingerprint: dict[str, Any]) -> None:
    if fingerprint.get("schema") != SCHEMA:
        raise VanillaStockFingerprintError(f"refusing to write non-{SCHEMA} fingerprint")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(fingerprint, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def diff_fingerprints(expected: dict[str, Any], actual: dict[str, Any]) -> list[str]:
    """Return human-readable field diffs; empty means equal."""

    def walk(prefix: str, left: Any, right: Any, out: list[str]) -> None:
        if type(left) is not type(right) and not (
            isinstance(left, (int, float)) and isinstance(right, (int, float))
        ):
            out.append(f"{prefix}: type {type(left).__name__} != {type(right).__name__}")
            return
        if isinstance(left, dict):
            left_keys = set(left)
            right_keys = set(right)
            for key in sorted(left_keys - right_keys):
                out.append(f"{prefix}.{key}: missing in actual")
            for key in sorted(right_keys - left_keys):
                out.append(f"{prefix}.{key}: unexpected in actual")
            for key in sorted(left_keys & right_keys):
                walk(f"{prefix}.{key}", left[key], right[key], out)
            return
        if isinstance(left, list):
            if len(left) != len(right):
                out.append(f"{prefix}: list length {len(left)} != {len(right)}")
                return
            for index, (a, b) in enumerate(zip(left, right)):
                walk(f"{prefix}[{index}]", a, b, out)
            return
        if left != right:
            out.append(f"{prefix}: {left!r} != {right!r}")

    diffs: list[str] = []
    walk("fingerprint", expected, actual, diffs)
    return diffs


def extract_from_artifact_dir(
    *,
    scenario_id: str,
    map_sid: str,
    era: str,
    format_version: int | None,
    artifact_dir: Path,
) -> dict[str, Any]:
    manifest_path = artifact_dir / f"{map_sid}.manifest.json"
    if not manifest_path.is_file():
        raise VanillaStockFingerprintError(f"missing manifest: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    return extract_regression_fingerprint(
        scenario_id=scenario_id,
        map_sid=map_sid,
        era=era,
        format_version=format_version,
        manifest=manifest,
    )
