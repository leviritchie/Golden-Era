"""Pure-Python policy and statistics for Meshy post-rig rigidization.

The Blender driver owns scene and vertex-group operations.  This module keeps
the decision policy independent of Blender so it can be tested on synthetic
weights and reused by batch validators.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from typing import Iterable, Mapping, Sequence


SCHEMA = "meshy_rigidization_config.v1"
REPORT_SCHEMA = "meshy_rigidization_report.v1"


@dataclass(frozen=True)
class RigidizationConfig:
    """Conservative defaults for an arbitrary Meshy auto-rig.

    A region is frozen only when the existing Meshy weights already provide a
    decisive owner.  Soft/flexible regions are left untouched.  That makes
    this a post-rig correction rather than a second rigging system.
    """

    seed_min_top_weight: float = 0.55
    accept_min_dominant_share: float = 0.78
    accept_min_dominant_margin: float = 0.20
    accept_min_mean_top_weight: float = 0.62
    accept_min_single_bone_fraction: float = 0.35
    ambiguous_min_dominant_share: float = 0.64
    ambiguous_min_mean_top_weight: float = 0.50
    ambiguous_max_dominant_margin: float = 0.10
    min_part_vertices: int = 24
    # A connected region larger than this is more likely body surface than a
    # rigid accessory.  Conservative by design; false rigidization is worse
    # than leaving a part flexible for a later explicit rule.
    max_part_fraction: float = 0.30
    max_ambiguous_parts: int = 0
    weight_epsilon: float = 1e-5
    audit_weight_tolerance: float = 1e-4
    audit_source_hash: bool = True

    def validate(self) -> None:
        for name in (
            "seed_min_top_weight",
            "accept_min_dominant_share",
            "accept_min_dominant_margin",
            "accept_min_mean_top_weight",
            "accept_min_single_bone_fraction",
            "ambiguous_min_dominant_share",
            "ambiguous_min_mean_top_weight",
            "ambiguous_max_dominant_margin",
        ):
            value = float(getattr(self, name))
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be in [0, 1], got {value}")
        if self.min_part_vertices < 1:
            raise ValueError("min_part_vertices must be positive")
        if not 0.0 < self.max_part_fraction <= 1.0:
            raise ValueError("max_part_fraction must be in (0, 1]")
        if self.max_ambiguous_parts < 0:
            raise ValueError("max_ambiguous_parts must be non-negative")
        if self.weight_epsilon <= 0.0:
            raise ValueError("weight_epsilon must be positive")
        if self.audit_weight_tolerance < 0.0:
            raise ValueError("audit_weight_tolerance must be non-negative")

    def to_dict(self) -> dict:
        self.validate()
        return {"schema": SCHEMA, **asdict(self)}

    @classmethod
    def from_mapping(cls, raw: Mapping[str, object] | None) -> "RigidizationConfig":
        if raw is None:
            config = cls()
            config.validate()
            return config
        schema = raw.get("schema")
        if schema not in (None, SCHEMA):
            raise ValueError(f"unsupported rigidization config schema: {schema!r}")
        allowed = {field.name for field in fields(cls)}
        unknown = sorted(set(raw) - allowed - {"schema"})
        if unknown:
            raise ValueError(f"unknown rigidization config fields: {unknown}")
        values = {name: raw[name] for name in allowed if name in raw}
        config = cls(**values)
        config.validate()
        return config


@dataclass(frozen=True)
class ComponentStats:
    """Weight statistics for one same-owner connected region."""

    component_id: int
    vertex_count: int
    mesh_vertex_fraction: float
    dominant_bone: str | None
    dominant_share: float
    second_share: float
    dominant_margin: float
    mean_top_weight: float
    single_bone_fraction: float
    total_weight_mean: float
    centroid: tuple[float, float, float]
    material_ids: tuple[int, ...]


@dataclass(frozen=True)
class ComponentDecision:
    component_id: int
    classification: str
    owner_bone: str | None
    confidence: float
    reason: str


def _normalise_weights(weights: Mapping[str, float], epsilon: float) -> dict[str, float]:
    positive = {
        str(name): float(value)
        for name, value in weights.items()
        if float(value) > epsilon
    }
    total = sum(positive.values())
    if total <= epsilon:
        return {}
    return {name: value / total for name, value in positive.items()}


def connected_components(
    vertex_count: int,
    edges: Iterable[tuple[int, int]],
    *,
    labels: Sequence[str | None],
    seed_top_weights: Sequence[float],
    min_seed_top_weight: float,
) -> list[list[int]]:
    """Build regions from Meshy's existing dominant-owner labels.

    We deliberately do not merge vertices by distance here.  A geometric
    weld can accidentally join a hand-held prop to the body; topology and the
    existing skin labels are safer evidence for the first automatic pass.
    """
    if len(labels) != vertex_count or len(seed_top_weights) != vertex_count:
        raise ValueError("labels and seed_top_weights must match vertex_count")
    parent = list(range(vertex_count))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left: int, right: int) -> None:
        root_left = find(left)
        root_right = find(right)
        if root_left != root_right:
            parent[root_right] = root_left

    for left, right in edges:
        if not 0 <= left < vertex_count or not 0 <= right < vertex_count:
            raise ValueError(f"edge index outside vertex range: {(left, right)}")
        owner = labels[left]
        if (
            owner is not None
            and owner == labels[right]
            and seed_top_weights[left] >= min_seed_top_weight
            and seed_top_weights[right] >= min_seed_top_weight
        ):
            union(left, right)

    components: dict[int, list[int]] = {}
    for index, owner in enumerate(labels):
        if owner is None or seed_top_weights[index] < min_seed_top_weight:
            continue
        components.setdefault(find(index), []).append(index)
    return sorted(components.values(), key=lambda values: (min(values), len(values)))


def component_stats(
    component_id: int,
    indices: Sequence[int],
    vertex_weights: Sequence[Mapping[str, float]],
    positions: Sequence[Sequence[float]],
    material_ids: Sequence[int] | None = None,
    *,
    epsilon: float = 1e-5,
) -> ComponentStats:
    if not indices:
        raise ValueError("component cannot be empty")
    if len(vertex_weights) != len(positions):
        raise ValueError("vertex_weights and positions must have the same length")
    mats = material_ids or [0] * len(vertex_weights)
    if len(mats) != len(vertex_weights):
        raise ValueError("material_ids must match vertex count")

    mass: dict[str, float] = {}
    top_values: list[float] = []
    single_count = 0
    total_weight_values: list[float] = []
    points = []
    component_materials = set()
    for index in indices:
        normalised = _normalise_weights(vertex_weights[index], epsilon)
        if normalised:
            ordered = sorted(normalised.items(), key=lambda pair: (-pair[1], pair[0]))
            top_name, top_weight = ordered[0]
            top_values.append(top_weight)
            if top_weight >= 1.0 - epsilon:
                single_count += 1
            second_weight = ordered[1][1] if len(ordered) > 1 else 0.0
            del second_weight
            for name, value in normalised.items():
                mass[name] = mass.get(name, 0.0) + value
        else:
            top_values.append(0.0)
        total_weight_values.append(sum(float(v) for v in vertex_weights[index].values()))
        points.append(tuple(float(value) for value in positions[index]))
        component_materials.add(int(mats[index]))

    vertex_count = len(indices)
    mass_total = sum(mass.values())
    ordered_mass = sorted(mass.items(), key=lambda pair: (-pair[1], pair[0]))
    dominant_bone = ordered_mass[0][0] if ordered_mass else None
    dominant_share = ordered_mass[0][1] / mass_total if ordered_mass and mass_total else 0.0
    second_share = ordered_mass[1][1] / mass_total if len(ordered_mass) > 1 and mass_total else 0.0
    dominant_margin = max(0.0, dominant_share - second_share)
    centroid = tuple(sum(point[axis] for point in points) / vertex_count for axis in range(3))
    return ComponentStats(
        component_id=int(component_id),
        vertex_count=vertex_count,
        mesh_vertex_fraction=0.0,
        dominant_bone=dominant_bone,
        dominant_share=float(dominant_share),
        second_share=float(second_share),
        dominant_margin=float(dominant_margin),
        mean_top_weight=float(sum(top_values) / vertex_count),
        single_bone_fraction=float(single_count / vertex_count),
        total_weight_mean=float(sum(total_weight_values) / vertex_count),
        centroid=centroid,
        material_ids=tuple(sorted(component_materials)),
    )


def with_mesh_fraction(stats: ComponentStats, total_vertices: int) -> ComponentStats:
    if total_vertices <= 0:
        raise ValueError("total_vertices must be positive")
    return ComponentStats(
        **{
            **asdict(stats),
            "mesh_vertex_fraction": float(stats.vertex_count / total_vertices),
        }
    )


def classify_component(stats: ComponentStats, config: RigidizationConfig) -> ComponentDecision:
    config.validate()
    if stats.dominant_bone is None:
        return ComponentDecision(
            stats.component_id,
            "preserve_unweighted",
            None,
            0.0,
            "no armature weights",
        )
    if stats.vertex_count < config.min_part_vertices:
        return ComponentDecision(
            stats.component_id,
            "preserve_too_small",
            None,
            0.0,
            f"{stats.vertex_count} vertices below min_part_vertices",
        )
    if stats.mesh_vertex_fraction > config.max_part_fraction:
        return ComponentDecision(
            stats.component_id,
            "preserve_large_region",
            None,
            0.0,
            "large region is more likely body surface than an accessory",
        )

    confidence = min(
        1.0,
        max(
            0.0,
            0.35 * stats.dominant_share
            + 0.25 * stats.dominant_margin
            + 0.25 * stats.mean_top_weight
            + 0.15 * stats.single_bone_fraction,
        ),
    )
    if (
        stats.dominant_share >= config.accept_min_dominant_share
        and stats.dominant_margin >= config.accept_min_dominant_margin
        and stats.mean_top_weight >= config.accept_min_mean_top_weight
        and stats.single_bone_fraction >= config.accept_min_single_bone_fraction
    ):
        return ComponentDecision(
            stats.component_id,
            "freeze_rigid_candidate",
            stats.dominant_bone,
            confidence,
            "existing Meshy weights provide a decisive single owner",
        )
    if (
        stats.dominant_share >= config.ambiguous_min_dominant_share
        and stats.mean_top_weight >= config.ambiguous_min_mean_top_weight
        and stats.dominant_margin <= config.ambiguous_max_dominant_margin
    ):
        return ComponentDecision(
            stats.component_id,
            "ambiguous_rigid_candidate",
            stats.dominant_bone,
            confidence,
            "region looks rigid-like but its attachment owner is not decisive",
        )
    return ComponentDecision(
        stats.component_id,
        "preserve_flexible",
        None,
        confidence,
        "existing weights indicate a deformable or mixed region",
    )


def validate_config_payload(raw: Mapping[str, object]) -> RigidizationConfig:
    """Validate a JSON payload and return its normalized policy."""
    return RigidizationConfig.from_mapping(raw)


def _max_axis_delta(left: Sequence[object], right: Sequence[object]) -> float:
    if len(left) != len(right):
        return float("inf")
    return max(abs(float(a) - float(b)) for a, b in zip(left, right))


def armature_signature_diffs(
    expected: Sequence[Mapping[str, object]],
    actual: Sequence[Mapping[str, object]],
    *,
    tolerance: float = 1e-3,
) -> list[str]:
    """Describe hierarchy/rest mismatches. Bones are matched by name, not list order."""
    expected_rows = list(expected)
    actual_rows = list(actual)
    expected_by_name = {str(row["name"]): row for row in expected_rows}
    actual_by_name = {str(row["name"]): row for row in actual_rows}
    diffs: list[str] = []
    if len(expected_by_name) != len(expected_rows):
        diffs.append("expected signature has duplicate bone names")
    if len(actual_by_name) != len(actual_rows):
        diffs.append("actual signature has duplicate bone names")
    missing = sorted(set(expected_by_name) - set(actual_by_name))
    extra = sorted(set(actual_by_name) - set(expected_by_name))
    if missing:
        diffs.append(f"missing bones: {missing}")
    if extra:
        diffs.append(f"extra bones: {extra}")
    for name in sorted(set(expected_by_name) & set(actual_by_name)):
        left = expected_by_name[name]
        right = actual_by_name[name]
        if left.get("parent") != right.get("parent"):
            diffs.append(f"{name} parent {left.get('parent')!r} -> {right.get('parent')!r}")
        for key in ("head", "tail"):
            left_axes = left[key]
            right_axes = right[key]
            if not isinstance(left_axes, Sequence) or not isinstance(right_axes, Sequence) or isinstance(left_axes, (str, bytes)) or isinstance(right_axes, (str, bytes)):
                diffs.append(f"{name} {key} is not a numeric sequence")
                continue
            delta = _max_axis_delta(left_axes, right_axes)
            if delta > tolerance:
                diffs.append(f"{name} {key} delta {delta:.6g} exceeds {tolerance}")
    return diffs


def armature_signatures_match(
    expected: Sequence[Mapping[str, object]],
    actual: Sequence[Mapping[str, object]],
    *,
    tolerance: float = 1e-3,
) -> bool:
    return not armature_signature_diffs(expected, actual, tolerance=tolerance)
