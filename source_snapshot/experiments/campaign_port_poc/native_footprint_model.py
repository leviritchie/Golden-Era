"""Native ObjectConfig map-object footprint model.

The native ObjectConfig query projection is based on the current ``bvf``
disassembly. The ``nodes`` layer is used by raw-translation object emission
and the isolated HoMM3 compatibility pass. Generator rectangles and
presentation offsets remain separate audit candidates, not path blockers.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable


DEFAULT_WIDTH = 160
DEFAULT_HEIGHT = 80
MIRRORED_ROTATION = 10

# These are the only unresolved states that make native ``nodes`` cell
# projection unsafe. Generator-body and presentation-transform findings stay
# in the audit model because the current ``bvf`` path query reads ``nodes``.
NATIVE_CELL_PROJECTION_FAILURES = frozenset({
    "native_and_generator_size_missing",
    "native_size_missing_used_generator_size",
    "nodes_grid_shape_invalid",
    "rotation_semantics_unresolved",
})


def _positive_int(value: Any) -> int | None:
    return value if type(value) is int and value > 0 else None


def _legacy_cell(
    anchor_node: int,
    size_x: int,
    size_z: int,
    local_x: int,
    local_z: int,
    rotation: int,
    *,
    can_be_mirrored: bool,
    width: int,
    height: int,
) -> int | None:
    """Project a cell using the current raw_translation emitter convention."""
    if type(anchor_node) is not int or anchor_node < 0:
        return None
    anchor_x = anchor_node % width
    anchor_y = anchor_node // width
    placed_x = (
        size_x - 1 - local_x
        if rotation == MIRRORED_ROTATION and can_be_mirrored
        else local_x
    )
    grid_x = anchor_x + placed_x
    grid_y = anchor_y + (size_z - 1 - local_z)
    if not (0 <= grid_x < width and 0 <= grid_y < height):
        return None
    return grid_y * width + grid_x


def _project_legacy(
    anchor_node: int,
    size_x: int,
    size_z: int,
    local_cells: Iterable[tuple[int, int]],
    rotation: int,
    *,
    can_be_mirrored: bool,
    width: int,
    height: int,
) -> frozenset[int]:
    return frozenset(
        projected
        for local_x, local_z in local_cells
        if (projected := _legacy_cell(
            anchor_node,
            size_x,
            size_z,
            local_x,
            local_z,
            rotation,
            can_be_mirrored=can_be_mirrored,
            width=width,
            height=height,
        ))
        is not None
    )


def _native_orientation(rotation: int, can_be_mirrored: bool) -> str:
    if rotation == MIRRORED_ROTATION and can_be_mirrored:
        return "mirrored"
    if rotation in (0, MIRRORED_ROTATION):
        return "unmirrored"
    return "unresolved_rotation_unmirrored_candidate"


def _native_cell(
    anchor_node: int,
    local_x: int,
    local_z: int,
    *,
    size_x: int,
    pivot_x: int,
    pivot_z: int,
    flipped_offset: int,
    orientation: str,
    width: int,
    height: int,
) -> int | None:
    """Project one cell using the native ``bvf`` query formula.

    For the unmirrored helper, the base is ``anchor - (pivotX, -pivotZ)``.
    The mirrored helper replaces the X base with
    ``anchorX + flippedOffset - sizeX + pivotX``.  Both helpers walk local Z
    toward decreasing map Y and index ``nodes`` row-major without an invented
    collider or padding cell.
    """
    if type(anchor_node) is not int or anchor_node < 0:
        return None
    anchor_x = anchor_node % width
    anchor_y = anchor_node // width
    if orientation == "mirrored":
        base_x = anchor_x + flipped_offset - size_x + pivot_x
    else:
        base_x = anchor_x - pivot_x
    grid_x = base_x + local_x
    grid_y = anchor_y + pivot_z - local_z
    if not (0 <= grid_x < width and 0 <= grid_y < height):
        return None
    return grid_y * width + grid_x


def _project_native(
    anchor_node: int,
    size_x: int,
    size_z: int,
    local_cells: Iterable[tuple[int, int]],
    *,
    pivot_x: int,
    pivot_z: int,
    flipped_offset: int,
    orientation: str,
    width: int,
    height: int,
) -> frozenset[int]:
    return frozenset(
        projected
        for local_x, local_z in local_cells
        if (projected := _native_cell(
            anchor_node,
            local_x,
            local_z,
            size_x=size_x,
            pivot_x=pivot_x,
            pivot_z=pivot_z,
            flipped_offset=flipped_offset,
            orientation=orientation,
            width=width,
            height=height,
        ))
        is not None
    )


@dataclass(frozen=True)
class TransformEvidence:
    pivot_x: int
    pivot_z: int
    offset_x: float | None
    offset_z: float | None
    path_line_stop_radius: float | None
    has_nonzero_transform: bool
    runtime_cell_projection: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "pivotX": self.pivot_x,
            "pivotZ": self.pivot_z,
            "offsetX": self.offset_x,
            "offsetZ": self.offset_z,
            "pathLineStopRadius": self.path_line_stop_radius,
            "hasNonzeroTransform": self.has_nonzero_transform,
            "runtimeCellProjection": self.runtime_cell_projection,
        }


@dataclass(frozen=True)
class NativeFootprintModel:
    sid: str
    anchor_node: int
    rotation: int
    width: int
    height: int
    size_x: int | None
    size_z: int | None
    native_orientation: str
    grid_cells: frozenset[int]
    occupied_cells: frozenset[int]
    gate_cells: frozenset[int]
    legacy_occupied_cells: frozenset[int]
    generator_cells: frozenset[int]
    generator_local_cells: tuple[tuple[int, int], ...]
    transform: TransformEvidence
    unresolved: tuple[str, ...]

    @property
    def generator_only_cells(self) -> frozenset[int]:
        return self.generator_cells - self.occupied_cells

    @property
    def native_only_occupied_cells(self) -> frozenset[int]:
        return self.occupied_cells - self.legacy_occupied_cells

    @property
    def legacy_only_occupied_cells(self) -> frozenset[int]:
        return self.legacy_occupied_cells - self.occupied_cells

    @property
    def grid_nonoccupied_cells(self) -> frozenset[int]:
        return self.grid_cells - self.occupied_cells

    @property
    def static_candidate_cells(self) -> frozenset[int]:
        return self.occupied_cells | self.generator_cells

    @property
    def runtime_model_status(self) -> str:
        if self.native_orientation.startswith("unresolved_"):
            return "unresolved_rotation_candidate"
        if self.transform.offset_x not in (None, 0.0) or self.transform.offset_z not in (None, 0.0):
            return "unresolved_presentation_offset_semantics"
        if self.transform.path_line_stop_radius not in (None, 0.0):
            return "unresolved_path_line_stop_radius_semantics"
        if self.generator_local_cells:
            return "native_nodes_projected_generator_body_candidate"
        return "native_nodes_projected"

    def as_dict(self) -> dict[str, Any]:
        return {
            "sid": self.sid,
            "anchorNode": self.anchor_node,
            "anchor": {"x": self.anchor_node % self.width, "y": self.anchor_node // self.width},
            "rotation": self.rotation,
            "sizeX": self.size_x,
            "sizeZ": self.size_z,
            "nativeOrientation": self.native_orientation,
            "gridCells": sorted(self.grid_cells),
            "occupiedCells": sorted(self.occupied_cells),
            "gateCells": sorted(self.gate_cells),
            "legacyOccupiedCells": sorted(self.legacy_occupied_cells),
            "nativeOnlyOccupiedCells": sorted(self.native_only_occupied_cells),
            "legacyOnlyOccupiedCells": sorted(self.legacy_only_occupied_cells),
            "generatorCells": sorted(self.generator_cells),
            "generatorOnlyCells": sorted(self.generator_only_cells),
            "gridNonoccupiedCells": sorted(self.grid_nonoccupied_cells),
            "generatorLocalCells": [list(cell) for cell in self.generator_local_cells],
            "transform": self.transform.as_dict(),
            "runtimeModelStatus": self.runtime_model_status,
            "unresolved": list(self.unresolved),
        }


def native_cell_projection_failure_reasons(model: NativeFootprintModel) -> tuple[str, ...]:
    """Return unresolved states that make native node cells unsafe to emit.

    Generator-body and presentation-transform findings are intentionally
    excluded: current ``bvf`` path queries use ObjectConfig ``nodes`` and
    do not prove those separate layers to be blockers.
    """
    return tuple(
        reason
        for reason in model.unresolved
        if reason in NATIVE_CELL_PROJECTION_FAILURES
    )


def model_native_footprint(
    sid: str,
    config: dict[str, Any],
    anchor_node: int,
    rotation: int,
    *,
    width: int = DEFAULT_WIDTH,
    height: int = DEFAULT_HEIGHT,
) -> NativeFootprintModel:
    """Return native-query, legacy, and generator footprint evidence layers."""
    if not isinstance(config, dict):
        config = {}
    unresolved: list[str] = []
    raw_size_x = _positive_int(config.get("sizeX"))
    raw_size_z = _positive_int(config.get("sizeZ"))
    generator = config.get("generatorConfig")
    generator = generator if isinstance(generator, dict) else {}
    generator_size_x = _positive_int(generator.get("buildingSizeX"))
    generator_size_z = _positive_int(generator.get("buildingSizeZ"))
    size_x = raw_size_x
    size_z = raw_size_z
    if size_x is None or size_z is None:
        if generator_size_x is not None and generator_size_z is not None:
            size_x = generator_size_x
            size_z = generator_size_z
            unresolved.append("native_size_missing_used_generator_size")
        else:
            unresolved.append("native_and_generator_size_missing")

    nodes = config.get("nodes")
    nodes_valid = (
        size_x is not None
        and size_z is not None
        and isinstance(nodes, list)
        and len(nodes) == size_x * size_z
    )
    if not nodes_valid:
        unresolved.append("nodes_grid_shape_invalid")

    can_be_mirrored = config.get("canBeMirrored") is True
    native_orientation = _native_orientation(rotation, can_be_mirrored)
    if native_orientation.startswith("unresolved_"):
        unresolved.append("rotation_semantics_unresolved")
    pivot_x = config.get("pivotX") if type(config.get("pivotX")) is int else 0
    pivot_z = config.get("pivotZ") if type(config.get("pivotZ")) is int else 0
    flipped_offset = (
        config.get("flippedOffset") if type(config.get("flippedOffset")) is int else 0
    )
    if type(config.get("pivotX")) is not int or type(config.get("pivotZ")) is not int:
        unresolved.append("pivot_missing_or_invalid_defaulted_zero")
    if native_orientation == "mirrored" and type(config.get("flippedOffset")) is not int:
        # ObjectConfig.flippedOffset is a native int field. The native
        # constructor does not assign it, so an omitted config field has the
        # normal zero value rather than an unresolved projection.
        unresolved.append("flipped_offset_missing_or_invalid_defaulted_zero")

    all_local = (
        [(local_x, local_z) for local_z in range(size_z) for local_x in range(size_x)]
        if size_x is not None and size_z is not None
        else []
    )
    grid_cells = _project_native(
        anchor_node,
        size_x or 0,
        size_z or 0,
        all_local,
        pivot_x=pivot_x,
        pivot_z=pivot_z,
        flipped_offset=flipped_offset,
        orientation=native_orientation,
        width=width,
        height=height,
    )
    occupied_local = (
        [
            (local_x, local_z)
            for local_z in range(size_z or 0)
            for local_x in range(size_x or 0)
            if nodes[local_z * (size_x or 1) + local_x] == 1
        ]
        if nodes_valid
        else []
    )
    gate_local = (
        [
            (local_x, local_z)
            for local_z in range(size_z or 0)
            for local_x in range(size_x or 0)
            if nodes[local_z * (size_x or 1) + local_x] == 2
        ]
        if nodes_valid
        else []
    )
    occupied_cells = _project_native(
        anchor_node,
        size_x or 0,
        size_z or 0,
        occupied_local,
        pivot_x=pivot_x,
        pivot_z=pivot_z,
        flipped_offset=flipped_offset,
        orientation=native_orientation,
        width=width,
        height=height,
    )
    gate_cells = _project_native(
        anchor_node,
        size_x or 0,
        size_z or 0,
        gate_local,
        pivot_x=pivot_x,
        pivot_z=pivot_z,
        flipped_offset=flipped_offset,
        orientation=native_orientation,
        width=width,
        height=height,
    )
    legacy_occupied_cells = _project_legacy(
        anchor_node,
        size_x or 0,
        size_z or 0,
        occupied_local,
        rotation,
        can_be_mirrored=can_be_mirrored,
        width=width,
        height=height,
    )

    generator_local: list[tuple[int, int]] = []
    generator_cells: frozenset[int] = frozenset()
    if generator_size_x is not None and generator_size_z is not None:
        left_x = generator.get("buildingLeftBottomX", 0)
        left_z = generator.get("buildingLeftBottomZ", 0)
        if type(left_x) is not int or type(left_z) is not int:
            unresolved.append("generator_building_origin_missing_or_invalid")
            left_x = left_z = 0
        generator_local = [
            (left_x + local_x, left_z + local_z)
            for local_z in range(generator_size_z)
            for local_x in range(generator_size_x)
        ]
        if size_x is None or size_z is None:
            unresolved.append("generator_body_has_no_native_grid_origin")
        else:
            projection_left_x = left_x
            if native_orientation == "mirrored":
                projection_left_x = size_x - generator_size_x - left_x
            projection_local = [
                (projection_left_x + local_x, left_z + local_z)
                for local_z in range(generator_size_z)
                for local_x in range(generator_size_x)
            ]
            if any(
                local_x < 0
                or local_z < 0
                or local_x >= size_x
                or local_z >= size_z
                for local_x, local_z in projection_local
            ):
                unresolved.append("generator_body_outside_native_grid")
            generator_cells = _project_native(
                anchor_node,
                size_x,
                size_z,
                projection_local,
                pivot_x=pivot_x,
                pivot_z=pivot_z,
                flipped_offset=flipped_offset,
                orientation=native_orientation,
                width=width,
                height=height,
            )
            unresolved.append("generator_body_static_candidate_only")

    offset_x = config.get("offsetX")
    offset_z = config.get("offsetZ")
    path_line_stop_radius = config.get("pathLineStopRadius")
    has_nonzero_transform = any(
        isinstance(value, (int, float)) and value != 0
        for value in (pivot_x, pivot_z, offset_x, offset_z)
    )
    if (isinstance(offset_x, (int, float)) and offset_x != 0) or (
        isinstance(offset_z, (int, float)) and offset_z != 0
    ):
        unresolved.append("presentation_offset_cell_semantics_unresolved")
    if isinstance(path_line_stop_radius, (int, float)) and path_line_stop_radius != 0:
        unresolved.append("path_line_stop_radius_semantics_unresolved")
    transform = TransformEvidence(
        pivot_x=pivot_x,
        pivot_z=pivot_z,
        offset_x=float(offset_x) if isinstance(offset_x, (int, float)) else None,
        offset_z=float(offset_z) if isinstance(offset_z, (int, float)) else None,
        path_line_stop_radius=(
            float(path_line_stop_radius)
            if isinstance(path_line_stop_radius, (int, float))
            else None
        ),
        has_nonzero_transform=has_nonzero_transform,
        runtime_cell_projection=(
            "native_bvf_query_formula_with_unresolved_presentation_offset"
            if offset_x not in (None, 0, 0.0) or offset_z not in (None, 0, 0.0)
            else "native_bvf_query_formula"
        ),
    )
    return NativeFootprintModel(
        sid=sid,
        anchor_node=anchor_node,
        rotation=rotation,
        width=width,
        height=height,
        size_x=size_x,
        size_z=size_z,
        native_orientation=native_orientation,
        grid_cells=grid_cells,
        occupied_cells=occupied_cells,
        gate_cells=gate_cells,
        legacy_occupied_cells=legacy_occupied_cells,
        generator_cells=generator_cells,
        generator_local_cells=tuple(generator_local),
        transform=transform,
        unresolved=tuple(dict.fromkeys(unresolved)),
    )


def cell_xy(node: int, *, width: int = DEFAULT_WIDTH) -> tuple[int, int]:
    return node % width, node // width


def residual_cells(observed_cells: Iterable[int], candidate_cells: Iterable[int]) -> frozenset[int]:
    """Cells observed at runtime but absent from a static candidate layer."""
    return frozenset(observed_cells) - frozenset(candidate_cells)


def native_anchor_for_local_cell(
    config: dict[str, Any],
    *,
    local_x: int,
    local_z: int,
    target_node: int,
    rotation: int,
    width: int = DEFAULT_WIDTH,
    height: int = DEFAULT_HEIGHT,
) -> int:
    """Inverse of the native ``bvf`` projection: the map node that puts ``nodes`` cell
    (local_x, local_z) on ``target_node``.

    Fails closed (ValueError) when the config cannot be projected natively or the anchor
    falls outside the map; the caller must not substitute the legacy size-grid formula.
    """
    model = model_native_footprint(
        str(config.get("id") or ""), config, 0, rotation, width=width, height=height
    )
    failures = native_cell_projection_failure_reasons(model)
    if failures:
        raise ValueError(f"cannot invert native projection for {config.get('id')}: unresolved {', '.join(failures)}")
    size_x = model.size_x or 0
    pivot_x = model.transform.pivot_x
    pivot_z = model.transform.pivot_z
    flipped_offset = config.get("flippedOffset") if type(config.get("flippedOffset")) is int else 0
    target_x = target_node % width
    target_y = target_node // width
    if model.native_orientation == "mirrored":
        anchor_x = target_x - local_x - flipped_offset + size_x - pivot_x
    else:
        anchor_x = target_x - local_x + pivot_x
    anchor_y = target_y + local_z - pivot_z
    if not (0 <= anchor_x < width and 0 <= anchor_y < height):
        raise ValueError(
            f"native anchor for {config.get('id')} out of map: ({anchor_x},{anchor_y}) "
            f"target={target_node} local=({local_x},{local_z}) rotation={rotation}"
        )
    anchor = anchor_y * width + anchor_x
    placed = _native_cell(
        anchor,
        local_x,
        local_z,
        size_x=size_x,
        pivot_x=pivot_x,
        pivot_z=pivot_z,
        flipped_offset=flipped_offset,
        orientation=model.native_orientation,
        width=width,
        height=height,
    )
    if placed != target_node:
        raise ValueError(
            f"native anchor inverse failed for {config.get('id')}: anchor={anchor} placed={placed} target={target_node}"
        )
    return anchor
