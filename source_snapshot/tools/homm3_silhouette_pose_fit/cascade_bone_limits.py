"""Per-bone rotation-limit scales for the GPU cascade.

``joint_limit_deg`` is one number for the whole skeleton, and the only
per-bone rule is the depth-based proximal shrink. That cannot express
"this chain may swing far, that chain may not", which is what a unit with
one high-motion appendage needs: an angel's wings sweep across a large
part of the silhouette every frame, and without a per-chain limit the
solver is free to splay the legs 150 degrees to cover pixels the wings
should have covered.

Scales multiply ``joint_limit_deg`` per node, so 0.3 with a 150 degree
limit caps that node at 45 degrees. An override replaces the depth rule
for that node; it is not multiplied with it, so the configured number is
the limit actually used.
"""
from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence


def validate_bone_limit_scale_overrides(
    overrides: Iterable[Sequence] | Mapping[str, float] | None,
) -> tuple[tuple[str, float], ...]:
    """Return normalized (bone name, scale) pairs, or raise.

    Accepts a mapping or an iterable of pairs so a notebook literal, a
    JSON round-trip (list of lists), and a dataclass tuple all validate
    the same way.
    """
    if overrides is None:
        return ()
    if isinstance(overrides, Mapping):
        items: list[tuple] = [(name, value) for name, value in overrides.items()]
    else:
        items = []
        for entry in overrides:
            if isinstance(entry, str) or not isinstance(entry, Sequence):
                raise ValueError(
                    "bone_limit_scale_overrides entries must be (bone name, scale) pairs, "
                    f"got {entry!r}"
                )
            if len(entry) != 2:
                raise ValueError(
                    "bone_limit_scale_overrides entries must have exactly two items "
                    f"(bone name, scale), got {list(entry)!r}"
                )
            items.append((entry[0], entry[1]))
    resolved: list[tuple[str, float]] = []
    seen: set[str] = set()
    for raw_name, raw_scale in items:
        if not isinstance(raw_name, str) or not raw_name:
            raise ValueError(
                f"bone_limit_scale_overrides bone name must be a non-empty string, got {raw_name!r}"
            )
        if raw_name in seen:
            raise ValueError(
                f"bone_limit_scale_overrides lists {raw_name!r} more than once; "
                "one bone gets one limit"
            )
        scale = float(raw_scale)
        if not math.isfinite(scale) or not 0.0 < scale <= 1.0:
            raise ValueError(
                f"bone_limit_scale_overrides scale for {raw_name!r} must be in (0, 1], got {raw_scale!r}"
            )
        seen.add(raw_name)
        resolved.append((raw_name, scale))
    return tuple(resolved)


def resolve_bone_limit_scales(
    *,
    node_names: Sequence[str],
    node_depths: Sequence[int],
    proximal_depth: int,
    proximal_scale: float,
    overrides: Iterable[Sequence] | Mapping[str, float] | None = (),
) -> tuple[float, ...]:
    """Return one limit scale per GLB node.

    Depth 0 is the armature root and is never shrunk by the proximal rule.
    An unknown override name is a config error, not a skipped entry: a
    typo would otherwise leave the bone at the full limit and look like
    the override simply did not help.
    """
    if len(node_names) != len(node_depths):
        raise ValueError(
            "node_names and node_depths must be the same length: "
            f"names={len(node_names)} depths={len(node_depths)}"
        )
    proximal_depth = int(proximal_depth)
    if proximal_depth < 0:
        raise ValueError("proximal_depth must be non-negative")
    proximal_scale = float(proximal_scale)
    if not math.isfinite(proximal_scale) or not 0.0 < proximal_scale <= 1.0:
        raise ValueError("proximal_scale must be in (0, 1]")
    pairs = validate_bone_limit_scale_overrides(overrides)
    known = set(node_names)
    unknown = [name for name, _ in pairs if name not in known]
    if unknown:
        raise ValueError(
            "bone_limit_scale_overrides names are not nodes in this GLB: "
            f"{unknown}"
        )
    by_name = dict(pairs)
    scales: list[float] = []
    for name, depth in zip(node_names, node_depths):
        if name in by_name:
            scales.append(float(by_name[name]))
            continue
        depth = int(depth)
        scales.append(proximal_scale if 0 < depth <= proximal_depth else 1.0)
    return tuple(scales)
