"""Rename collision Auditor (namespace/simple-name rejects + recovered-name uniqueness)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from olden_cs_recovery.paths import PACKAGE_ROOT
from olden_cs_recovery.renamer.mono_map import MonoSemanticMap, RejectedCollision


RENAME_MAP_DIR = PACKAGE_ROOT / "rename_map"
RENAME_MAP_ENTRIES_DIR = RENAME_MAP_DIR / "entries"
RENAME_MAP_INDEX_PATH = RENAME_MAP_DIR / "index.json"


@dataclass
class CollisionVerdict:
    ok: bool
    reason: str | None = None
    rejected: RejectedCollision | None = None


def load_rename_index() -> dict[str, Any]:
    if not RENAME_MAP_INDEX_PATH.is_file():
        return {
            "schema_version": 1,
            "by_current_type": {},
            "by_recovered_full": {},
            "by_recovered_simple": {},
        }
    try:
        data = json.loads(RENAME_MAP_INDEX_PATH.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"FAIL: cannot load rename_map index {RENAME_MAP_INDEX_PATH}: {exc}") from exc
    if not isinstance(data, dict):
        raise SystemExit(f"FAIL: rename_map index root must be object: {RENAME_MAP_INDEX_PATH}")
    data.setdefault("by_current_type", {})
    data.setdefault("by_recovered_full", {})
    data.setdefault("by_recovered_simple", {})
    return data


def write_rename_index(index: dict[str, Any]) -> Path:
    RENAME_MAP_DIR.mkdir(parents=True, exist_ok=True)
    tmp = RENAME_MAP_INDEX_PATH.with_suffix(RENAME_MAP_INDEX_PATH.suffix + ".tmp")
    tmp.write_text(json.dumps(index, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(RENAME_MAP_INDEX_PATH)
    return RENAME_MAP_INDEX_PATH


def check_proposal(
    *,
    mono_map: MonoSemanticMap,
    current_type_name: str,
    proposed_mono_full: str | None,
    index: dict[str, Any] | None = None,
    require_unique_simple: bool = True,
) -> CollisionVerdict:
    """
    Reject unsafe renames:
    1. Pair already tracked in Mono rejectedSimpleNameCollisions.
    2. Two different current types would claim the same recovered full name.
    3. Same recovered simple name claimed by two current types (unsafe unless identical full).
    """
    if not proposed_mono_full:
        return CollisionVerdict(ok=True, reason=None)

    rejected = mono_map.is_rejected_pair(mono_full=proposed_mono_full, deobf_full=current_type_name)
    if rejected is not None:
        return CollisionVerdict(
            ok=False,
            reason=(
                f"Mono map rejectedSimpleNameCollisions forbids "
                f"{proposed_mono_full!r} <-> {current_type_name!r}: {rejected.reason}"
            ),
            rejected=rejected,
        )

    # Also reject if simple-name collision list tracks this deobf type against this mono simple.
    mono_simple = proposed_mono_full.rsplit(".", 1)[-1]
    for row in mono_map.rejected_for_simple_name(mono_simple):
        if row.deobf_full == current_type_name and row.mono_full == proposed_mono_full:
            return CollisionVerdict(
                ok=False,
                reason=f"Rejected simple-name collision: {row.reason}",
                rejected=row,
            )

    idx = index if index is not None else load_rename_index()
    by_full = idx.get("by_recovered_full") or {}
    existing_current = by_full.get(proposed_mono_full)
    if existing_current and existing_current != current_type_name:
        return CollisionVerdict(
            ok=False,
            reason=(
                f"Recovered name {proposed_mono_full!r} already accepted/proposed for "
                f"current type {existing_current!r}; refusing second owner {current_type_name!r}"
            ),
        )

    by_current = idx.get("by_current_type") or {}
    prior = by_current.get(current_type_name)
    if prior and prior.get("proposed_mono_type_name") not in (None, proposed_mono_full):
        return CollisionVerdict(
            ok=False,
            reason=(
                f"Current type {current_type_name!r} already mapped to "
                f"{prior.get('proposed_mono_type_name')!r}; refusing {proposed_mono_full!r}"
            ),
        )

    if require_unique_simple:
        by_simple = idx.get("by_recovered_simple") or {}
        owners = by_simple.get(mono_simple) or []
        for owner in owners:
            if owner.get("current_type_name") == current_type_name:
                continue
            if owner.get("proposed_mono_type_name") == proposed_mono_full:
                continue
            # Different full names sharing a simple name is unsafe without Auditor override.
            return CollisionVerdict(
                ok=False,
                reason=(
                    f"Recovered simple name {mono_simple!r} already used by "
                    f"{owner.get('current_type_name')!r} -> {owner.get('proposed_mono_type_name')!r}; "
                    f"refusing {current_type_name!r} -> {proposed_mono_full!r}"
                ),
            )

    return CollisionVerdict(ok=True)


def register_in_index(
    index: dict[str, Any],
    *,
    current_type_name: str,
    proposed_mono_full: str | None,
    decision: str,
    method_id: str,
) -> dict[str, Any]:
    """Update in-memory index after a non-skipped rename decision."""
    if decision in ("skipped",) or not proposed_mono_full:
        return index
    if decision == "collision-rejected":
        return index

    entry = {
        "current_type_name": current_type_name,
        "proposed_mono_type_name": proposed_mono_full,
        "decision": decision,
        "method_id": method_id,
    }
    index.setdefault("by_current_type", {})[current_type_name] = entry
    index.setdefault("by_recovered_full", {})[proposed_mono_full] = current_type_name
    simple = proposed_mono_full.rsplit(".", 1)[-1]
    bucket = index.setdefault("by_recovered_simple", {}).setdefault(simple, [])
    # Dedup by current_type_name
    bucket = [b for b in bucket if b.get("current_type_name") != current_type_name]
    bucket.append(entry)
    index["by_recovered_simple"][simple] = bucket
    return index


def audit_rename_collisions(*, mono_map: MonoSemanticMap | None = None) -> dict[str, Any]:
    """
    Auditor pass over rename_map/entries + index.

    Fails closed: reports collisions; does not invent resolutions.
    """
    from olden_cs_recovery.renamer.mono_map import load_mono_map

    mmap = mono_map or load_mono_map()
    index = load_rename_index()
    problems: list[dict[str, Any]] = []

    # Full-name uniqueness
    owners: dict[str, list[str]] = {}
    for current, meta in (index.get("by_current_type") or {}).items():
        full = meta.get("proposed_mono_type_name")
        if not full:
            continue
        owners.setdefault(full, []).append(current)
    for full, currents in owners.items():
        if len(set(currents)) > 1:
            problems.append(
                {
                    "kind": "duplicate_recovered_full",
                    "proposed_mono_type_name": full,
                    "current_types": sorted(set(currents)),
                }
            )

    # Rejected pairs that somehow got into the index
    for current, meta in (index.get("by_current_type") or {}).items():
        full = meta.get("proposed_mono_type_name")
        if not full:
            continue
        rejected = mmap.is_rejected_pair(mono_full=full, deobf_full=current)
        if rejected is not None:
            problems.append(
                {
                    "kind": "mono_rejected_pair",
                    "current_type_name": current,
                    "proposed_mono_type_name": full,
                    "reason": rejected.reason,
                }
            )

    # Entry files vs index consistency
    if RENAME_MAP_ENTRIES_DIR.is_dir():
        for path in sorted(RENAME_MAP_ENTRIES_DIR.glob("*.json")):
            try:
                entry = json.loads(path.read_text(encoding="utf-8-sig"))
            except (OSError, json.JSONDecodeError) as exc:
                problems.append({"kind": "entry_load_error", "path": str(path), "error": str(exc)})
                continue
            if entry.get("decision") == "collision-rejected":
                continue
            full = entry.get("proposed_mono_type_name")
            current = entry.get("current_type_name")
            if full and current:
                verdict = check_proposal(
                    mono_map=mmap,
                    current_type_name=current,
                    proposed_mono_full=full,
                    index=index,
                )
                # check_proposal against index that already contains self should be ok;
                # only flag when ok is False for a different reason than self-map.
                if not verdict.ok and "already accepted/proposed for current type" not in (verdict.reason or ""):
                    # Re-check ignoring self in a copy
                    idx_copy = json.loads(json.dumps(index))
                    idx_copy.get("by_recovered_full", {}).pop(full, None)
                    simple = full.rsplit(".", 1)[-1]
                    idx_copy["by_recovered_simple"][simple] = [
                        b
                        for b in (idx_copy.get("by_recovered_simple") or {}).get(simple, [])
                        if b.get("current_type_name") != current
                    ]
                    idx_copy.get("by_current_type", {}).pop(current, None)
                    verdict2 = check_proposal(
                        mono_map=mmap,
                        current_type_name=current,
                        proposed_mono_full=full,
                        index=idx_copy,
                    )
                    if not verdict2.ok:
                        problems.append(
                            {
                                "kind": "entry_collision",
                                "path": str(path),
                                "reason": verdict2.reason,
                            }
                        )

    return {
        "ok": len(problems) == 0,
        "problem_count": len(problems),
        "problems": problems,
        "index_path": str(RENAME_MAP_INDEX_PATH),
        "mono_map_path": str(mmap.path),
    }
