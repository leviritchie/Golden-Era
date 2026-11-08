#!/usr/bin/env python3
"""Turn an authored anatomy-order file into per-bone rotation limits.

The authored files under ``llm_authored/`` carry a per-anatomy-group rotation scale
-- for h3_roc: wings 1.0, trunk 0.55, neck/head 0.45, tail 0.35, legs 0.22, with the
stated reason that "legs stay tucked and must not steal silhouette budget from the
wings". Until now those files recorded intent only; their own ``proof`` field said
"authored intent only until cascade run consumes search_bones +
bone_limit_scale_overrides". This module is what consumes them.

Why the limits matter, measured rather than assumed
--------------------------------------------------
On h3_roc ``idle_start_move_end`` with a flat 150 degree limit on every joint, the
tracker rotated the leg root ``Bone_007`` to 143 degrees during the flight frames.
Legs own 1.5-3.3% of the mesh vertices each and are tucked out of sight while the
bird flies, so the silhouette pays nothing for flailing them. The consequences were
measurable: leg-into-tail contact (``Bone_008~Bone_013``) became the largest
remaining self-intersection, and the leg snap-back produced a 110 degree
single-frame pose jump where an ordinary frame moves 2-6 degrees.

A rotation scale is a multiplier on ``joint_limit_deg``, so 0.22 with a 150 degree
limit caps a leg joint at 33 degrees -- enough to tuck, not enough to invert.

Fails closed: an unknown group, an unknown bone, or a missing file raises. Silently
skipping an unresolvable entry would hand back a weaker policy than the one the
author wrote, under the same name.

Proof tier: source/static resolution of authored intent.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(r"V:/Games/Olden Era Playtest Tweak")


def node_names_from_mesh(mesh: Path) -> tuple[str, ...]:
    """Node names of a GLB without building a GPU experiment.

    Limits must be resolved *before* the experiment is constructed, since they are
    part of its config, so the bone-existence check cannot use the experiment.
    """
    from roc_geometric_proxy import load_asset

    asset = load_asset(Path(mesh).resolve(), decode_images=False)
    return tuple(str(node.name) for node in asset.nodes)


def load_anatomy_groups(path: Path) -> dict[str, list[str]]:
    """Group name -> bones, from an anatomy-groups file."""
    if not path.is_file():
        raise FileNotFoundError(f"anatomy groups file not found: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    groups = payload.get("groups")
    if not isinstance(groups, dict) or not groups:
        raise ValueError(f"{path} has no 'groups' map")
    resolved: dict[str, list[str]] = {}
    for name, entry in groups.items():
        bones = entry.get("bonesDependencyOrder")
        if not isinstance(bones, list) or not bones:
            raise ValueError(f"{path} group {name!r} has no bonesDependencyOrder")
        resolved[str(name)] = [str(bone) for bone in bones]
    return resolved


def bone_limit_overrides_from_anatomy_order(
    *,
    anatomy_order_path: Path,
    node_names: Sequence[str],
    anatomy_groups_path: Path | None = None,
    only_groups: Sequence[str] | None = None,
) -> tuple[tuple[tuple[str, float], ...], dict[str, Any]]:
    """Resolve ``rotationScaleByGroup`` into ``bone_limit_scale_overrides`` pairs.

    ``only_groups`` restricts the policy to named groups. Applying every scale at once
    is not always best: on h3_roc the full policy clamped trunk to 82.5 deg and
    neck/head to 67.5 deg as well as the legs, which pushed the search into the
    unclamped wings and made frame-to-frame motion far worse (mean per-joint step
    10.45 deg against 2.74 deg, peak 177.8 deg). Clamping only the groups that
    actually lack silhouette evidence keeps the benefit without that cost -- the same
    targeted-beats-global result already measured on h3_angel.

    Returns the pairs plus a provenance record, so a solved clip can state which
    authored file shaped its limits instead of carrying unexplained numbers.
    """
    if not anatomy_order_path.is_file():
        raise FileNotFoundError(f"anatomy order file not found: {anatomy_order_path}")
    order = json.loads(anatomy_order_path.read_text(encoding="utf-8"))
    scales = order.get("rotationScaleByGroup")
    if not isinstance(scales, dict) or not scales:
        raise ValueError(f"{anatomy_order_path} has no 'rotationScaleByGroup'")

    groups_path = anatomy_groups_path
    if groups_path is None:
        recorded = order.get("anatomyGroupsPath")
        if not recorded:
            raise ValueError(
                f"{anatomy_order_path} does not record anatomyGroupsPath; pass "
                "anatomy_groups_path explicitly rather than guessing which groups "
                "these scales refer to"
            )
        groups_path = ROOT / str(recorded)
    groups = load_anatomy_groups(Path(groups_path))

    unknown_groups = sorted(set(scales) - set(groups))
    if unknown_groups:
        raise ValueError(
            f"{anatomy_order_path} scales groups absent from {groups_path}: "
            f"{unknown_groups}"
        )

    selected = None if only_groups is None else [str(name) for name in only_groups]
    if selected is not None:
        unknown_selected = sorted(set(selected) - set(scales))
        if unknown_selected:
            raise ValueError(
                f"requested groups have no scale in {anatomy_order_path}: "
                f"{unknown_selected}; available: {sorted(scales)}"
            )

    known_nodes = set(str(name) for name in node_names)
    pairs: list[tuple[str, float]] = []
    per_group: dict[str, Any] = {}
    for group, raw_scale in scales.items():
        scale = float(raw_scale)
        if not 0.0 < scale <= 1.0:
            raise ValueError(
                f"rotation scale for {group!r} must be in (0, 1], got {raw_scale!r}"
            )
        bones = groups[str(group)]
        missing = [bone for bone in bones if bone not in known_nodes]
        if missing:
            raise ValueError(
                f"anatomy group {group!r} names bones absent from this GLB: {missing}"
            )
        if scale == 1.0 or (selected is not None and str(group) not in selected):
            # Recorded even when not applied, so the report shows the whole authored
            # policy alongside the part of it this run actually used.
            per_group[str(group)] = {"scale": scale, "bones": bones, "applied": False}
            continue
        for bone in bones:
            pairs.append((bone, scale))
        per_group[str(group)] = {"scale": scale, "bones": bones, "applied": True}

    duplicates = sorted({name for name, _ in pairs if [n for n, _ in pairs].count(name) > 1})
    if duplicates:
        raise ValueError(
            "the same bone appears in more than one anatomy group, so its limit is "
            f"ambiguous: {duplicates}"
        )

    provenance = {
        "anatomyOrderPath": str(anatomy_order_path).replace("\\", "/"),
        "anatomyGroupsPath": str(groups_path).replace("\\", "/"),
        "rationale": order.get("rationale"),
        "perGroup": per_group,
        "overrideCount": len(pairs),
        "appliedGroups": sorted(
            name for name, entry in per_group.items() if entry["applied"]
        ),
    }
    return tuple(pairs), provenance
