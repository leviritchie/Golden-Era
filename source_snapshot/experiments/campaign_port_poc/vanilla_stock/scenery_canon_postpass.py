"""Explicit stock-only scenery diversify post-pass for vanilla_stock.

Inspired by raw_translation visual_scenery_canon_postpass, but restricted to the
stock Core catalog and never remaps GE tiles. Disabled by default; enable with
``apply_stock_scenery_canon_postpass(..., enabled=True)`` or the emit CLI flag.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

SCHEMA = "homm3.vanilla_stock.scenery_canon_postpass.v1"
STATUS_APPLIED = "applied"
STATUS_SKIPPED = "skipped_by_flag"
PROOF_BOUNDARY = "generated_artifact_runtime_unvalidated"

# Prefix families that may diversify among stock siblings with identical OCC.
DIVERSIFY_FAMILY_PREFIXES: tuple[str, ...] = (
    "mountain_dirt_small_",
    "mountain_green_small_",
    "mountain_snow_small_",
    "mountain_dead_small_",
    "mountain_lava_small_",
    "mountain_water_small_",
    "mountain_desert_",
    "pinetree_",
    "pinetree_snow_",
    "tree_dead_",
    "tree_dirt_",
    "tree_lava_",
    "grass_",
    "grass_stones_",
    "dirt_stones_",
    "snow_stones_",
    "flowers_",
    "cactus_",
    "bush_",
)


class VanillaStockSceneryPostpassError(ValueError):
    """Fail-closed stock scenery post-pass error."""


def _occ_fingerprint(config: dict[str, Any]) -> tuple[Any, ...]:
    """Stable ObjectConfig occupancy fingerprint for swap eligibility."""
    cells = config.get("cells") or config.get("Cells") or []
    if not isinstance(cells, list):
        cells = []
    normalized = []
    for cell in cells:
        if not isinstance(cell, dict):
            continue
        normalized.append(
            (
                int(cell.get("x") or cell.get("X") or 0),
                int(cell.get("y") or cell.get("Y") or 0),
                str(cell.get("type") or cell.get("Type") or ""),
            )
        )
    normalized.sort()
    return (
        int(config.get("width") or config.get("Width") or 0),
        int(config.get("height") or config.get("Height") or 0),
        tuple(normalized),
    )


def _family_prefix(sid: str) -> str | None:
    for prefix in DIVERSIFY_FAMILY_PREFIXES:
        if sid.startswith(prefix):
            return prefix
    return None


def apply_stock_scenery_canon_postpass(
    *,
    objects: list[dict[str, Any]],
    stock_object_configs: dict[str, dict[str, Any]],
    stock_object_ids: set[str],
    enabled: bool,
) -> dict[str, Any]:
    """Diversify scenery SIDs within same-OCC stock families. No-op when disabled."""
    if not enabled:
        return {
            "schema": SCHEMA,
            "status": STATUS_SKIPPED,
            "policy": "vanilla_stock_scenery_diversify_opt_in",
            "swappedCount": 0,
            "proofBoundary": PROOF_BOUNDARY,
        }

    # Build fingerprint → candidate stock SIDs per family prefix.
    candidates_by_key: dict[tuple[str, tuple[Any, ...]], list[str]] = defaultdict(list)
    for sid, config in stock_object_configs.items():
        if sid not in stock_object_ids:
            continue
        if any(token in sid.lower() for token in ("homm3_", "h3_", "golden_era")):
            continue
        prefix = _family_prefix(sid)
        if prefix is None or not isinstance(config, dict):
            continue
        key = (prefix, _occ_fingerprint(config))
        candidates_by_key[key].append(sid)
    for key in candidates_by_key:
        candidates_by_key[key] = sorted(set(candidates_by_key[key]))

    swaps: list[dict[str, Any]] = []
    for group in objects:
        sid = group.get("sid")
        if not isinstance(sid, str):
            continue
        prefix = _family_prefix(sid)
        if prefix is None:
            continue
        config = stock_object_configs.get(sid)
        if not isinstance(config, dict):
            raise VanillaStockSceneryPostpassError(f"missing stock config for scenery {sid}")
        key = (prefix, _occ_fingerprint(config))
        options = candidates_by_key.get(key) or []
        if len(options) < 2:
            continue
        ids = group.get("ids") or []
        if not ids:
            continue
        # Deterministic round-robin across instances in this group.
        new_groups: dict[str, dict[str, list[Any]]] = {}
        nodes = group.get("nodes") or []
        rotations = group.get("rotations") or []
        levels = group.get("levels") or []
        for index, object_id in enumerate(ids):
            replacement = options[index % len(options)]
            if replacement == sid:
                # Keep original SID bucket.
                bucket = new_groups.setdefault(
                    sid,
                    {"ids": [], "nodes": [], "rotations": [], "levels": []},
                )
            else:
                if replacement not in stock_object_ids:
                    raise VanillaStockSceneryPostpassError(
                        f"scenery diversify selected non-stock SID {replacement}"
                    )
                bucket = new_groups.setdefault(
                    replacement,
                    {"ids": [], "nodes": [], "rotations": [], "levels": []},
                )
                swaps.append(
                    {
                        "objectId": int(object_id),
                        "fromSid": sid,
                        "toSid": replacement,
                    }
                )
            bucket["ids"].append(object_id)
            bucket["nodes"].append(nodes[index] if index < len(nodes) else 0)
            bucket["rotations"].append(rotations[index] if index < len(rotations) else 0)
            if levels:
                bucket["levels"].append(levels[index] if index < len(levels) else 0.0)
        # Rewrite this group in place when all stay on one SID; otherwise expand.
        if len(new_groups) == 1 and sid in new_groups:
            continue
        group.clear()
        # Leave a placeholder; caller rebuilds from collected expansion below.
        group["_expanded"] = new_groups

    # Flatten expansions into the objects list.
    rebuilt: list[dict[str, Any]] = []
    for group in objects:
        expanded = group.get("_expanded") if isinstance(group, dict) else None
        if not isinstance(expanded, dict):
            rebuilt.append(group)
            continue
        for sid, payload in sorted(expanded.items()):
            rebuilt.append(
                {
                    "sid": sid,
                    "ids": list(payload["ids"]),
                    "nodes": list(payload["nodes"]),
                    "rotations": list(payload["rotations"]),
                    "levels": list(payload["levels"]) if payload["levels"] else [0.0] * len(payload["ids"]),
                }
            )
    objects[:] = rebuilt

    # Fail closed on GE leaks.
    for group in objects:
        sid = str(group.get("sid") or "")
        if any(token in sid.lower() for token in ("homm3_", "h3_", "golden_era")):
            raise VanillaStockSceneryPostpassError(f"GE SID leak after scenery postpass: {sid}")
        if sid and sid not in stock_object_ids:
            raise VanillaStockSceneryPostpassError(f"non-stock SID after scenery postpass: {sid}")

    return {
        "schema": SCHEMA,
        "status": STATUS_APPLIED,
        "policy": "vanilla_stock_scenery_diversify_same_occ",
        "swappedCount": len(swaps),
        "examples": swaps[:40],
        "proofBoundary": PROOF_BOUNDARY,
    }
