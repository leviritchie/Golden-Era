"""Expand anatomy-group visit order into cascade search_bones + limit scales.

Within each anatomical group, bones stay in dependency (proximal→distal) order
from the group catalog. Group visit order may come from LLM-authored JSON or a
catalog transit default (no sprite authorship).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Sequence


CATALOG_TRANSIT_GROUP_VISIT_ORDER = (
    "wing_a",
    "wing_b",
    "trunk",
    "neck_head",
    "tail",
    "leg_a",
    "leg_b",
)

CATALOG_TRANSIT_ROTATION_SCALE_BY_GROUP = {
    "wing_a": 1.0,
    "wing_b": 1.0,
    "trunk": 0.55,
    "neck_head": 0.45,
    "tail": 0.35,
    "leg_a": 0.22,
    "leg_b": 0.22,
}

CATALOG_TRANSIT_PRIMARY_GROUPS = ("wing_a", "wing_b", "trunk")


def catalog_transit_anatomy_authored(*, clip: str = "roc_transit") -> dict[str, Any]:
    """Mesh-catalog transit importance order; not LLM sprite authorship."""
    return {
        "clip": str(clip),
        "method": "catalog_transit_importance",
        "rationale": (
            "Flyer transit: wings and trunk before neck/tail/legs; "
            "rotation scales limit distal spend."
        ),
        "groupVisitOrder": list(CATALOG_TRANSIT_GROUP_VISIT_ORDER),
        "rotationScaleByGroup": dict(CATALOG_TRANSIT_ROTATION_SCALE_BY_GROUP),
        "withinGroupOrder": "dependency",
    }


def anatomy_group_bone_names(
    *,
    groups_catalog: Mapping[str, Any],
    group_visit_order: Sequence[str],
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    groups = groups_catalog.get("groups") or {}
    spans: list[tuple[str, tuple[str, ...]]] = []
    for group_name in group_visit_order:
        entry = groups.get(str(group_name))
        if entry is None:
            raise ValueError(f"groupVisitOrder name missing from catalog: {group_name!r}")
        bones = tuple(str(b) for b in (entry.get("bonesDependencyOrder") or ()))
        if not bones:
            raise ValueError(f"anatomy group {group_name!r} has no bonesDependencyOrder")
        spans.append((str(group_name), bones))
    return tuple(spans)


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def expand_anatomy_order(
    *,
    groups_catalog: Mapping[str, Any],
    authored: Mapping[str, Any],
) -> dict[str, Any]:
    groups = groups_catalog.get("groups") or {}
    visit = [str(name) for name in (authored.get("groupVisitOrder") or ())]
    scales = authored.get("rotationScaleByGroup") or {}
    if not visit:
        raise ValueError("authored groupVisitOrder is empty")
    missing = [name for name in visit if name not in groups]
    if missing:
        raise ValueError(f"groupVisitOrder names missing from catalog: {missing}")
    unused = sorted(set(groups) - set(visit))
    if unused:
        raise ValueError(
            "every anatomy group must appear in groupVisitOrder; "
            f"missing {unused}"
        )

    search_bones: list[str] = []
    limit_overrides: list[tuple[str, float]] = []
    expanded_groups: dict[str, Any] = {}
    seen: set[str] = set()
    for group_name in visit:
        entry = groups[group_name]
        bones = [str(b) for b in (entry.get("bonesDependencyOrder") or ())]
        if not bones:
            raise ValueError(f"anatomy group {group_name!r} has no bonesDependencyOrder")
        dupes = [b for b in bones if b in seen]
        if dupes:
            raise ValueError(f"bone listed in multiple groups: {dupes}")
        raw_scale = scales.get(group_name)
        if raw_scale is None:
            raise ValueError(f"rotationScaleByGroup missing {group_name!r}")
        scale = float(raw_scale)
        if not (0.0 < scale <= 1.0):
            raise ValueError(
                f"rotationScaleByGroup[{group_name!r}] must be in (0, 1], got {scale}"
            )
        search_bones.extend(bones)
        for bone in bones:
            seen.add(bone)
            limit_overrides.append((bone, scale))
        expanded_groups[group_name] = {
            "bones": bones,
            "rotationScale": scale,
            "role": entry.get("role"),
        }

    return {
        "search_bones": tuple(search_bones),
        "include_unlisted_search_bones": False,
        "bone_order_mode": "dependency",
        "bone_limit_scale_overrides": tuple(limit_overrides),
        "groupVisitOrder": visit,
        "expandedGroups": expanded_groups,
        "rationale": authored.get("rationale"),
        "method": authored.get("method"),
    }


def expand_anatomy_order_paths(
    *,
    groups_path: Path,
    authored_path: Path,
) -> dict[str, Any]:
    groups_catalog = load_json(groups_path)
    authored = load_json(authored_path)
    payload = expand_anatomy_order(groups_catalog=groups_catalog, authored=authored)
    payload["groupsPath"] = str(groups_path).replace("\\", "/")
    payload["authoredPath"] = str(authored_path).replace("\\", "/")
    return payload


def cascade_kwargs_from_catalog_transit(
    *,
    groups_path: Path,
    clip: str = "roc_transit",
) -> dict[str, Any]:
    groups_catalog = load_json(groups_path)
    authored = catalog_transit_anatomy_authored(clip=clip)
    expanded = expand_anatomy_order(groups_catalog=groups_catalog, authored=authored)
    kwargs = cascade_kwargs_from_anatomy_order(expanded)
    kwargs["anatomy_groups_catalog_path"] = str(groups_path).replace("\\", "/")
    kwargs["anatomy_group_visit_order"] = tuple(authored["groupVisitOrder"])
    return kwargs


def cascade_kwargs_from_anatomy_order(expanded: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "search_bones": tuple(expanded["search_bones"]),
        "include_unlisted_search_bones": bool(
            expanded.get("include_unlisted_search_bones", False)
        ),
        "bone_order_mode": str(expanded.get("bone_order_mode") or "dependency"),
        "bone_limit_scale_overrides": tuple(expanded["bone_limit_scale_overrides"]),
    }
