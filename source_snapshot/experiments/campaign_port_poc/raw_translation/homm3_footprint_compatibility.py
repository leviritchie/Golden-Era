"""Isolated HoMM3-versus-Olden static-footprint compatibility postpass.

This module deliberately runs on a candidate copy of the emitted objects. It
does not change the main translator's placement rules and does not touch
terrain. A caller commits the candidate only when every required repair is
resolved; otherwise the pass fails closed and the original objects are left
untouched.

HoMM3 land-on (visit-mask) cells are wildcards: each check may treat them as
closed or open, whichever is more permissive for that check.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, replace
from typing import Any, Callable, Iterable

import layered_objects
from native_footprint_model import (
    NATIVE_CELL_PROJECTION_FAILURES,
    model_native_footprint,
)
from surface_emit import entity_nonvisitable_block_offsets, source_visit_offsets


SCHEMA = "olden.raw_translation.homm3_footprint_compatibility.v1"
STATUS_APPLIED = "applied"
STATUS_APPLIED_WITH_UNRESOLVED = "applied_with_unresolved"
STATUS_NOOP = "no_changes_needed"
STATUS_DRY_RUN = "dry_run"
STATUS_FAILED = "failed_closed"
STATUS_DISABLED = "disabled"

NATIVE_CELL_UNRESOLVED_FIELDS = (
    NATIVE_CELL_PROJECTION_FAILURES
    | {"native_gate_projection_unavailable"}
)

KNOWN_H3_FOOTPRINT_STATUSES = frozenset({
    "source_h3_projected",
    "source_h3_projected_with_0_out_of_bounds_cells",
    "synthetic_h3_seal",
})


def _h3_footprint_status_is_known(status: str) -> bool:
    """Treat source cells clipped outside the active map as known absent cells."""
    if status in KNOWN_H3_FOOTPRINT_STATUSES:
        return True
    prefix = "source_h3_projected_with_"
    suffix = "_out_of_bounds_cells"
    if not status.startswith(prefix) or not status.endswith(suffix):
        return False
    count = status[len(prefix):-len(suffix)]
    return count.isdigit()

# The order is deterministic. The score still prefers shorter moves, then the
# move that best restores the H3 footprint, before using this order as a
# tie-breaker.
CARDINAL_DIRECTIONS: tuple[tuple[str, int, int], ...] = (
    ("north", 0, 1),
    ("east", 1, 0),
    ("south", 0, -1),
    ("west", -1, 0),
)
MAX_REPOSITION_STEPS = 2

H3_SEAL_SIDS = frozenset(
    {
        "homm3_pathing_blocker",
        "homm3_envelope_padding_blocker",
    }
)

NON_PERMANENT_INTERACT_SIDS = frozenset({
    "hero-spawner",
    "random-hero",
    "random-res",
    "homm3_boat",
    "homm3_flotsam_pickup",
})

# Exact-footprint mine clones retain the native ``Interact`` tag so their
# visual and resource logic continue to work. They are still resources, not
# permanent geometry for this pass. The donor metadata is the stable signal
# for both native mine rows and their generated clones.
NON_PERMANENT_EXACT_DONOR_PREFIXES = ("mine_",)


class Homm3FootprintCompatibilityError(RuntimeError):
    """Raised when a candidate cannot be repaired without guessing."""

    def __init__(self, report: dict[str, Any]):
        self.report = report
        failures = report.get("failures") or []
        map_sid = report.get("mapSid") or "raw_translation"
        super().__init__(
            f"{map_sid}: H3 footprint compatibility failed closed for "
            f"{len(failures)} building(s); first failure={failures[0] if failures else 'unknown'}"
        )


@dataclass(frozen=True)
class InstanceFootprint:
    object_id: int
    sid: str
    kind: str
    node: int
    rotation: int
    layer: int | None
    source_index: int | None
    h3_cells: frozenset[int]
    h3_land_on_cells: frozenset[int]
    h3_status: str
    native_gate_cells: frozenset[int]
    olden_cells: frozenset[int]
    native_model_status: str
    native_unresolved: tuple[str, ...]

    @property
    def h3_closed_cells(self) -> frozenset[int]:
        """Hard blockers plus land-on cells treated as optionally closed."""
        return frozenset(self.h3_cells | self.h3_land_on_cells)

    @property
    def is_scenery(self) -> bool:
        return self.kind == "scenery"

    @property
    def native_cell_unresolved(self) -> tuple[str, ...]:
        return tuple(
            reason
            for reason in self.native_unresolved
            if reason in NATIVE_CELL_UNRESOLVED_FIELDS
        )

    @property
    def h3_footprint_known(self) -> bool:
        return self.source_index is None or _h3_footprint_status_is_known(self.h3_status)


@dataclass(frozen=True)
class ContactIssue:
    blocker_id: int
    blocker_sid: str
    blocker_kind: str
    olden_contact_cells: frozenset[int]
    h3_contact_cells: frozenset[int]
    new_blocker_cells: frozenset[int]
    overlap_cells: frozenset[int]

    def as_dict(self) -> dict[str, Any]:
        return {
            "blockerObjectId": self.blocker_id,
            "blockerSid": self.blocker_sid,
            "blockerKind": self.blocker_kind,
            "oldenContactCells": sorted(self.olden_contact_cells),
            "h3ContactCells": sorted(self.h3_contact_cells),
            "newBlockerCells": sorted(self.new_blocker_cells),
            "overlapCells": sorted(self.overlap_cells),
        }


def _has_native_grid(config: dict[str, Any]) -> bool:
    size_x = config.get("sizeX")
    size_z = config.get("sizeZ")
    nodes = config.get("nodes")
    return (
        isinstance(size_x, int)
        and size_x > 0
        and isinstance(size_z, int)
        and size_z > 0
        and isinstance(nodes, list)
        and len(nodes) == size_x * size_z
    )


def _classify_config(sid: str, config: dict[str, Any]) -> str | None:
    """Return only permanent building/scenery blockers.

    Resource, artifact, meta, and army rows are intentionally excluded. The
    pass is about adventure-map geometry, not pickup or enemy interaction.
    """
    if sid in NON_PERMANENT_INTERACT_SIDS:
        return None
    if sid in H3_SEAL_SIDS or config.get("tag") == "Block":
        return "h3_seal"
    exact_meta = config.get("homm3ExactFootprint")
    donor_sid = exact_meta.get("donorSid") if isinstance(exact_meta, dict) else None
    if (
        sid.startswith(NON_PERMANENT_EXACT_DONOR_PREFIXES)
        or (
            isinstance(donor_sid, str)
            and donor_sid.startswith(NON_PERMANENT_EXACT_DONOR_PREFIXES)
        )
    ):
        return None
    if (
        isinstance(exact_meta, dict)
        and exact_meta.get("kind") == "scenery"
        and _has_native_grid(config)
    ):
        # Exact H3 scenery clones retain the donor ObjectConfig tag for
        # rendering, but their metadata keeps them out of the building lane.
        return "scenery"
    tag = config.get("tag")
    if tag in {"Resource", "Artifact", "meta", "Army"}:
        return None
    if tag == "Environment" and _has_native_grid(config):
        return "scenery"
    if tag == "Interact" and _has_native_grid(config):
        return "building"
    if tag == "Interact" and config.get("isInteractable") is True and isinstance(config.get("generatorConfig"), dict):
        return "building"
    return None


def _iter_object_instances(objects: list[dict[str, Any]]) -> Iterable[dict[str, Any]]:
    for group in objects:
        if not isinstance(group, dict):
            raise ValueError(f"malformed object group: {group!r}")
        sid = group.get("sid")
        ids = group.get("ids")
        nodes = group.get("nodes")
        rotations = group.get("rotations")
        levels = group.get("levels")
        if not isinstance(sid, str) or not all(isinstance(value, list) for value in (ids, nodes, rotations, levels)):
            raise ValueError(f"malformed object group for sid={sid!r}")
        if not (len(ids) == len(nodes) == len(rotations) == len(levels)):
            raise ValueError(
                f"malformed object group lengths for sid={sid!r}: "
                f"ids={len(ids)} nodes={len(nodes)} rotations={len(rotations)} levels={len(levels)}"
            )
        for index, object_id in enumerate(ids):
            if not isinstance(object_id, int) or not isinstance(nodes[index], int) or not isinstance(rotations[index], int):
                raise ValueError(f"malformed object instance for sid={sid!r}, index={index}")
            yield {
                "objectId": object_id,
                "sid": sid,
                "node": int(nodes[index]),
                "rotation": int(rotations[index]),
                "level": levels[index],
            }


def _project_h3_cells(
    entity: dict[str, Any] | None,
    *,
    layer_target_node: Callable[[int, int, int], int],
) -> tuple[frozenset[int], str]:
    if entity is None:
        return frozenset(), "synthetic_no_source"
    source_x = entity.get("sourceX")
    source_y = entity.get("sourceY")
    source_layer = entity.get("sourceLayer")
    mask = entity.get("templateBlockMask")
    if not isinstance(source_x, int) or not isinstance(source_y, int) or not isinstance(source_layer, int):
        return frozenset(), "source_coordinates_invalid"
    if not isinstance(mask, list) or len(mask) != 6:
        return frozenset(), "source_block_mask_missing_or_invalid"
    try:
        offsets = entity_nonvisitable_block_offsets(entity)
    except (TypeError, ValueError) as exc:
        return frozenset(), f"source_block_mask_error:{type(exc).__name__}"
    cells: set[int] = set()
    dropped = 0
    for dx, dy in offsets:
        try:
            cells.add(int(layer_target_node(source_layer, source_x + dx, source_y + dy)))
        except (ValueError, IndexError):
            dropped += 1
    if dropped:
        return frozenset(cells), f"source_h3_projected_with_{dropped}_out_of_bounds_cells"
    return frozenset(cells), "source_h3_projected"


def _project_h3_land_on_cells(
    entity: dict[str, Any] | None,
    *,
    layer_target_node: Callable[[int, int, int], int],
) -> frozenset[int]:
    """Project HoMM3 visit/land-on cells. These are wildcards for this pass."""
    if entity is None:
        return frozenset()
    source_x = entity.get("sourceX")
    source_y = entity.get("sourceY")
    source_layer = entity.get("sourceLayer")
    mask = entity.get("templateVisitMask")
    if not isinstance(source_x, int) or not isinstance(source_y, int) or not isinstance(source_layer, int):
        return frozenset()
    if not isinstance(mask, list) or len(mask) != 6:
        return frozenset()
    try:
        offsets = source_visit_offsets(entity)
    except (TypeError, ValueError):
        return frozenset()
    cells: set[int] = set()
    for dx, dy in offsets:
        try:
            cells.add(int(layer_target_node(source_layer, source_x + dx, source_y + dy)))
        except (ValueError, IndexError):
            continue
    return frozenset(cells)


def _h3_footprint_mismatched(instance: InstanceFootprint) -> bool:
    """True when Olden differs from H3 beyond land-on wildcard permissiveness.

    Land-on cells may be occupied (closed) or empty (open). Only true overhang
    beyond hard+land-on, or missing hard blocker cells on the building itself,
    count as a footprint mismatch.
    """
    olden = set(instance.olden_cells)
    hard = set(instance.h3_cells)
    closed = set(instance.h3_closed_cells)
    return bool(olden - closed) or bool(hard - olden)


def _translate_cells(cells: Iterable[int], *, dx: int, dy: int, width: int, height: int) -> frozenset[int] | None:
    translated: set[int] = set()
    for node in cells:
        x = node % width
        y = node // width
        nx = x + dx
        ny = y + dy
        if not (0 <= nx < width and 0 <= ny < height):
            return None
        translated.add(ny * width + nx)
    return frozenset(translated)


def _cardinal_contacts(a: Iterable[int], b: Iterable[int], *, width: int, height: int) -> frozenset[int]:
    b_set = set(b)
    contacts: set[int] = set()
    for node in a:
        x = node % width
        y = node // width
        for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
            if 0 <= nx < width and 0 <= ny < height:
                neighbor = ny * width + nx
                if neighbor in b_set:
                    contacts.add(neighbor)
    return frozenset(contacts)


def _extension_outward_contact_cells(
    *,
    olden_cells: frozenset[int],
    h3_cells: frozenset[int],
    other_cells: frozenset[int],
    width: int,
    height: int,
) -> frozenset[int]:
    """Return other-object cells that sit on the outer side of a new Olden blocker.

    A newly emitted blocker is an Olden occupied cell absent from the HoMM3
    footprint. When that overhang grows east of the H3 body, only an east-side
    neighbor counts; the same rule applies for west/north/south. Side-touching
    or inner-side neighbors of an overhang do not count as actionable contacts.
    """
    extra = set(olden_cells) - set(h3_cells)
    h3_set = set(h3_cells)
    # No H3 blockers means there is no extension axis from a source body, so
    # adjacency cannot be blamed on a newly emitted overhang.
    if not extra or not other_cells or not h3_set:
        return frozenset()
    other_set = set(other_cells)
    actionable: set[int] = set()
    for cell in extra:
        x = cell % width
        y = cell // width
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            if not _cell_extends_in_direction(
                start_x=x,
                start_y=y,
                dx=dx,
                dy=dy,
                h3_cells=h3_set,
                width=width,
                height=height,
            ):
                continue
            nx = x + dx
            ny = y + dy
            if not (0 <= nx < width and 0 <= ny < height):
                continue
            neighbor = ny * width + nx
            if neighbor in other_set:
                actionable.add(neighbor)
    return frozenset(actionable)


def _cell_extends_in_direction(
    *,
    start_x: int,
    start_y: int,
    dx: int,
    dy: int,
    h3_cells: set[int],
    width: int,
    height: int,
) -> bool:
    """True when direction ``(dx, dy)`` is the overhang axis from the H3 body.

    Cast a ray opposite the candidate direction. The cell extends that way only
    when the ray hits an H3 occupied cell on the same row/column. Empty gaps are
    allowed so move candidates still know they grew from the source body.
    """
    if not h3_cells:
        return False
    x = start_x - dx
    y = start_y - dy
    while 0 <= x < width and 0 <= y < height:
        if (y * width + x) in h3_cells:
            return True
        x -= dx
        y -= dy
    return False


def _same_layer(a: InstanceFootprint, b: InstanceFootprint) -> bool:
    """Only two known, equal atlas layers may interact."""
    return a.layer is not None and b.layer is not None and a.layer == b.layer


class _State:
    def __init__(
        self,
        *,
        objects: list[dict[str, Any]],
        global_entities: list[dict[str, Any]],
        native_object_configs: dict[str, dict[str, Any]],
        layer_target_node: Callable[[int, int, int], int],
        width: int,
        height: int,
        layer_resolver: Callable[[int], int | None] | None,
    ) -> None:
        self.objects = objects
        self.global_entities = global_entities
        self.native_object_configs = native_object_configs
        self.layer_target_node = layer_target_node
        self.width = width
        self.height = height
        self.layer_resolver = layer_resolver
        self.source_entities: dict[int, dict[str, Any]] = {}
        for entity in global_entities:
            source_index = entity.get("sourceIndex")
            if not isinstance(source_index, int):
                continue
            if source_index in self.source_entities:
                raise ValueError(f"duplicate H3 sourceIndex {source_index}")
            self.source_entities[source_index] = entity
        self.instances: dict[int, InstanceFootprint] = {}
        self.missing_native_configs: list[dict[str, Any]] = []
        self.skipped_synthetic_outside_layer_envelope: list[dict[str, Any]] = []
        self.h3_required_cells: frozenset[int] = frozenset()
        self.h3_land_on_cells: frozenset[int] = frozenset()
        self._layer_source_nodes: dict[int, frozenset[int]] = {}
        self._load_instances()

    def _source_layer_nodes(self, layer: int) -> frozenset[int]:
        """Return playable atlas cells for one H3 source layer."""
        cached = self._layer_source_nodes.get(layer)
        if cached is not None:
            return cached
        nodes: set[int] = set()
        for source_y in range(self.height):
            for source_x in range(self.width):
                try:
                    nodes.add(int(self.layer_target_node(layer, source_x, source_y)))
                except (IndexError, TypeError, ValueError):
                    continue
        if not nodes:
            raise ValueError(
                f"cannot derive playable atlas envelope for source layer {layer}"
            )
        result = frozenset(nodes)
        self._layer_source_nodes[layer] = result
        return result

    def _clip_native_cells_to_layer(
        self,
        cells: Iterable[int],
        layer: int,
    ) -> frozenset[int]:
        """Clip native footprint cells to the active H3 layer envelope."""
        playable = self._source_layer_nodes(layer)
        return frozenset(int(node) for node in cells if int(node) in playable)

    def _load_instances(self) -> None:
        for row in _iter_object_instances(self.objects):
            object_id = int(row["objectId"])
            if object_id in self.instances:
                raise ValueError(f"duplicate emitted object id {object_id}")
            sid = str(row["sid"])
            config = self.native_object_configs.get(sid)
            if not isinstance(config, dict):
                if object_id in self.source_entities:
                    self.missing_native_configs.append({
                        "objectId": object_id,
                        "sid": sid,
                    })
                continue
            kind = _classify_config(sid, config)
            if kind is None:
                continue
            node = int(row["node"])
            rotation = int(row["rotation"])
            source_entity = self.source_entities.get(object_id)
            source_layer = (
                source_entity.get("sourceLayer")
                if isinstance(source_entity, dict) and isinstance(source_entity.get("sourceLayer"), int)
                else None
            )
            layer = source_layer
            if layer is None and self.layer_resolver is not None:
                layer = self.layer_resolver(node)
                if layer is None and source_entity is None:
                    # Synthetic objects outside the active H3 layer envelope
                    # cannot cardinally touch a source-layer blocker. Keep
                    # them out of the comparison instead of inventing layer 0.
                    self.skipped_synthetic_outside_layer_envelope.append({
                        "objectId": object_id,
                        "sid": sid,
                        "node": node,
                        "reason": "synthetic_object_outside_active_layer_envelope",
                    })
                    continue
            elif layer is None:
                layer = 0
            if not isinstance(layer, int):
                raise ValueError(
                    f"cannot resolve source layer for object {object_id}: {layer!r}"
                )
            if kind == "h3_seal":
                olden_cells = frozenset({node})
                native_gate_cells = frozenset()
                model_status = "synthetic_h3_seal"
                unresolved: tuple[str, ...] = ()
                h3_cells = olden_cells
                h3_land_on_cells = frozenset()
                h3_status = "synthetic_h3_seal"
            else:
                model = model_native_footprint(
                    sid,
                    config,
                    node,
                    rotation,
                    width=self.width,
                    height=self.height,
                )
                olden_cells = self._clip_native_cells_to_layer(
                    model.occupied_cells,
                    layer,
                )
                native_gate_cells = self._clip_native_cells_to_layer(
                    model.gate_cells,
                    layer,
                )
                model_status = model.runtime_model_status
                unresolved = tuple(model.unresolved)
                if (
                    model.size_x is not None
                    and model.size_z is not None
                    and len(model.grid_cells) != model.size_x * model.size_z
                ):
                    unresolved = unresolved + ("native_grid_projection_out_of_bounds",)
                if kind == "building" and not native_gate_cells:
                    unresolved = unresolved + ("native_gate_projection_unavailable",)
                h3_cells, h3_status = _project_h3_cells(
                    source_entity,
                    layer_target_node=self.layer_target_node,
                )
                h3_land_on_cells = _project_h3_land_on_cells(
                    source_entity,
                    layer_target_node=self.layer_target_node,
                )
            self.instances[object_id] = InstanceFootprint(
                object_id=object_id,
                sid=sid,
                kind=kind,
                node=node,
                rotation=rotation,
                layer=layer,
                source_index=object_id if object_id in self.source_entities else None,
                h3_cells=h3_cells,
                h3_land_on_cells=h3_land_on_cells,
                h3_status=h3_status,
                olden_cells=olden_cells,
                native_gate_cells=native_gate_cells,
                native_model_status=model_status,
                native_unresolved=unresolved,
            )
        required: set[int] = set()
        land_on: set[int] = set()
        for instance in self.instances.values():
            if (
                instance.kind == "h3_seal"
                or (
                    instance.kind in {"building", "scenery"}
                    and instance.h3_status.startswith("source_h3_projected")
                )
            ):
                required.update(instance.h3_cells)
                land_on.update(instance.h3_land_on_cells)
        self.h3_required_cells = frozenset(required)
        self.h3_land_on_cells = frozenset(land_on)
    def blockers(self) -> Iterable[InstanceFootprint]:
        return (
            instance
            for instance in self.instances.values()
            if instance.kind in {"building", "scenery", "h3_seal"}
        )

    def update_node(self, object_id: int, node: int) -> None:
        instance = self.instances[object_id]
        translated = _translate_cells(
            instance.olden_cells,
            dx=(node % self.width) - (instance.node % self.width),
            dy=(node // self.width) - (instance.node // self.width),
            width=self.width,
            height=self.height,
        )
        if translated is None:
            raise ValueError(f"object {object_id} moved outside map bounds")
        self.instances[object_id] = replace(instance, node=node, olden_cells=translated)

    def remove(self, object_ids: set[int]) -> list[dict[str, Any]]:
        removed = layered_objects.remove_object_ids_from_groups(self.objects, object_ids)
        for object_id in object_ids:
            self.instances.pop(object_id, None)
        return removed

    def layer_for_node(self, node: int) -> int | None:
        return self.layer_resolver(node) if self.layer_resolver is not None else None

    def cells_in_layer(self, cells: Iterable[int], layer: int | None) -> bool:
        if layer is None or self.layer_resolver is None:
            return True
        return all(self.layer_resolver(cell) == layer for cell in cells)


def _scenery_is_new(instance: InstanceFootprint) -> bool:
    if not instance.is_scenery:
        return False
    if instance.source_index is None:
        return True
    return instance.h3_footprint_known and not instance.h3_cells


def _scenery_can_be_removed(
    state: _State,
    instance: InstanceFootprint,
    *,
    excluded_ids: set[int] | None = None,
    preserved_blocker_cells: Iterable[int] | None = None,
) -> tuple[bool, str]:
    excluded = excluded_ids or set()
    preserved = {int(cell) for cell in (preserved_blocker_cells or ())}
    if not instance.is_scenery:
        return False, "not_scenery"
    if instance.native_cell_unresolved:
        return False, "native_cell_footprint_unresolved"
    if (
        instance.source_index is not None
        and not instance.h3_footprint_known
    ):
        return False, "source_H3_footprint_unresolved"
    other_olden: set[int] = set()
    for other in state.blockers():
        if (
            other.object_id != instance.object_id
            and other.object_id not in excluded
            and _same_layer(instance, other)
        ):
            # Only blockers that remain in the Olden layout can preserve a
            # cell after this scenery instance is deleted. Another object's
            # H3 mask is evidence of what should be blocked, not occupancy.
            other_olden.update(other.olden_cells)
    required_cells = set(instance.h3_cells) & set(instance.olden_cells)
    covered_cells = other_olden | preserved
    if not required_cells <= covered_cells:
        return False, "would_remove_unique_H3_blocker_cell"
    if instance.source_index is None:
        return True, "synthetic_or_visual_only_scenery"
    if not instance.h3_cells:
        return True, "source_scenery_has_no_H3_blocker_cells_in_olden_footprint"
    if required_cells <= other_olden:
        return True, "H3_blocker_cells_redundantly_covered"
    return True, "H3_blocker_cells_preserved_by_other_permanent_blocker"


def _scenery_set_can_be_removed(
    state: _State,
    object_ids: set[int],
    *,
    excluded_ids: set[int] | None = None,
    preserved_blocker_cells: Iterable[int] | None = None,
) -> tuple[bool, str]:
    """Check a scenery deletion set against blockers left behind."""
    base_excluded = excluded_ids or set()
    for object_id in sorted(object_ids):
        instance = state.instances.get(object_id)
        if instance is None:
            return False, f"scenery_not_present:{object_id}"
        removable, reason = _scenery_can_be_removed(
            state,
            instance,
            excluded_ids=(object_ids - {object_id}) | base_excluded,
            preserved_blocker_cells=preserved_blocker_cells,
        )
        if not removable:
            return False, reason
    return True, "scenery_deletion_set_safe"

def _unwanted_contacts(
    state: _State,
    building: InstanceFootprint,
    *,
    olden_cells: frozenset[int] | None = None,
    excluded_ids: set[int] | None = None,
) -> list[ContactIssue]:
    excluded = excluded_ids or set()
    building_olden = olden_cells if olden_cells is not None else building.olden_cells
    issues: list[ContactIssue] = []
    for other in state.blockers():
        if other.object_id == building.object_id or other.object_id in excluded:
            continue
        if not _same_layer(building, other):
            continue
        olden_contact = _cardinal_contacts(
            building_olden,
            other.olden_cells,
            width=state.width,
            height=state.height,
        )
        olden_overlap = frozenset(set(building_olden) & set(other.olden_cells))
        if not olden_contact and not olden_overlap:
            continue
        # Land-on cells are wildcards: treat them as closed here so Olden
        # occupation of a visit cell is not an overhang, and H3 visit adjacency
        # still counts as an already-known neighbor relationship.
        building_closed = building.h3_closed_cells
        other_closed = other.h3_closed_cells
        h3_contact = _cardinal_contacts(
            building_closed,
            other_closed,
            width=state.width,
            height=state.height,
        )
        h3_overlap = frozenset(set(building_closed) & set(other_closed))
        # Only count adjacency on the outer face of newly emitted Olden blockers,
        # and only when that other object was not already an H3 neighbor.
        # Example: building grows one cell east → only a newly adjacent east-side
        # neighbor of that new cell is actionable; side/inner touches and shifted
        # contacts with already-adjacent H3 neighbors are ignored.
        outward_contact = _extension_outward_contact_cells(
            olden_cells=frozenset(building_olden),
            h3_cells=building_closed,
            other_cells=frozenset(other.olden_cells),
            width=state.width,
            height=state.height,
        )
        already_h3_neighbor = bool(h3_contact) or bool(h3_overlap)
        new_cells = frozenset() if already_h3_neighbor else frozenset(outward_contact)
        # A building may occupy a scenery cell when the scenery already
        # supplies the blocker. That overlap does not add a new blocked cell;
        # only overlaps with another building or a synthetic H3 seal remain a
        # compatibility issue here.
        if olden_overlap and not h3_overlap and other.kind != "scenery":
            new_cells = frozenset(set(new_cells) | set(olden_overlap))
        if new_cells:
            issues.append(
                ContactIssue(
                    blocker_id=other.object_id,
                    blocker_sid=other.sid,
                    blocker_kind=other.kind,
                    olden_contact_cells=olden_contact,
                    h3_contact_cells=h3_contact,
                    new_blocker_cells=new_cells,
                    overlap_cells=olden_overlap,
                )
            )
    return sorted(issues, key=lambda issue: (issue.blocker_kind, issue.blocker_id))


def _overlapping_blockers(
    state: _State,
    building: InstanceFootprint,
    olden_cells: frozenset[int],
    *,
    excluded_ids: set[int] | None = None,
) -> list[InstanceFootprint]:
    excluded = excluded_ids or set()
    overlaps: list[InstanceFootprint] = []
    for other in state.blockers():
        if other.object_id == building.object_id or other.object_id in excluded:
            continue
        if not _same_layer(building, other):
            continue
        if set(olden_cells) & set(other.olden_cells):
            overlaps.append(other)
    return sorted(overlaps, key=lambda instance: (instance.kind, instance.object_id))


def _unsafe_overlapping_blockers(
    state: _State,
    building: InstanceFootprint,
    olden_cells: frozenset[int],
    *,
    excluded_ids: set[int] | None = None,
) -> list[InstanceFootprint]:
    """Return overlaps that cannot be resolved by digging into scenery.

    Scenery is already a permanent blocker at its Olden cells, so a building
    footprint that overlaps it does not create another blocked cell there.
    Buildings and synthetic H3 seals are different: overlapping either would
    merge permanent objects in a way this isolated pass cannot justify.
    """
    return [
        instance
        for instance in _overlapping_blockers(
            state,
            building,
            olden_cells,
            excluded_ids=excluded_ids,
        )
        if not instance.is_scenery
    ]


def _candidate_node(state: _State, node: int, dx: int, dy: int) -> int | None:
    x = node % state.width
    y = node // state.width
    nx = x + dx
    ny = y + dy
    if not (0 <= nx < state.width and 0 <= ny < state.height):
        return None
    return ny * state.width + nx


def _unresolved_blockers_at(
    state: _State,
    building: InstanceFootprint,
    olden_cells: frozenset[int],
    *,
    excluded_ids: set[int] | None = None,
) -> list[InstanceFootprint]:
    excluded = excluded_ids or set()
    unresolved: list[InstanceFootprint] = []
    for other in state.blockers():
        if other.object_id == building.object_id or other.object_id in excluded:
            continue
        if not _same_layer(building, other) or other.h3_footprint_known:
            continue
        olden_contact = _cardinal_contacts(
            olden_cells,
            other.olden_cells,
            width=state.width,
            height=state.height,
        )
        olden_overlap = set(olden_cells) & set(other.olden_cells)
        if olden_contact or olden_overlap:
            unresolved.append(other)
    return sorted(unresolved, key=lambda instance: (instance.kind, instance.object_id))


def _unpreserved_h3_blocker_cells_after_move(
    state: _State,
    building: InstanceFootprint,
    translated: frozenset[int],
    *,
    excluded_ids: set[int] | None = None,
) -> frozenset[int]:
    """Find former H3 blocker cells that the final Olden layout would open."""
    excluded = excluded_ids or set()
    required = set(building.h3_cells) & set(building.olden_cells)
    if not required:
        return frozenset()
    covered = set(translated)
    for other in state.blockers():
        if (
            other.object_id != building.object_id
            and other.object_id not in excluded
            and _same_layer(building, other)
        ):
            covered.update(other.olden_cells)
    return frozenset(required - covered)

def _uncovered_extra_olden_cells_after_move(
    state: _State,
    building: InstanceFootprint,
    translated: frozenset[int],
    *,
    excluded_ids: set[int] | None = None,
) -> frozenset[int]:
    """Find moved building cells that would add a new permanent blocker.

    A native Olden cell is safe when it is already covered by another
    permanent Olden object, or when HoMM3 expects a permanent blocker at that
    cell. This is the check that permits a building to dig into scenery while
    rejecting a move onto an otherwise-open tile.
    """
    excluded = excluded_ids or set()
    covered_by_other_olden: set[int] = set()
    # Land-on wildcards may be treated as closed, so a move onto a visit cell is
    # not a newly uncovered Olden-only blocker.
    expected_h3: set[int] = set(state.h3_required_cells) | set(state.h3_land_on_cells)
    for other in state.blockers():
        if other.object_id == building.object_id or other.object_id in excluded:
            continue
        if not _same_layer(building, other):
            continue
        covered_by_other_olden.update(other.olden_cells)
    return frozenset(set(translated) - covered_by_other_olden - expected_h3)

def _final_blocker_union(state: _State) -> frozenset[int]:
    return frozenset(
        cell
        for instance in state.blockers()
        for cell in instance.olden_cells
    )


def _final_blocker_parity_delta(
    state: _State,
    affected_cells: Iterable[int],
) -> tuple[frozenset[int], frozenset[int]]:
    """Return final Olden-only and missing H3 cells in the changed region."""
    scope = {int(cell) for cell in affected_cells}
    if not scope:
        return frozenset(), frozenset()
    olden = _final_blocker_union(state)
    # Land-on wildcards: closed when judging extras, open when judging missing.
    expected_closed = set(state.h3_required_cells) | set(state.h3_land_on_cells)
    required_hard = set(state.h3_required_cells)
    return (
        frozenset((olden - expected_closed) & scope),
        frozenset((required_hard - olden) & scope),
    )

def _effective_contact_issues(
    state: _State,
    building: InstanceFootprint,
    *,
    olden_cells: frozenset[int] | None = None,
    excluded_ids: set[int] | None = None,
) -> list[ContactIssue]:
    """Return actionable outer-face contacts from newly emitted blockers.

    Only neighbors on the extension side of Olden-only occupied cells count.
    Side or inner touches of an overhang are ignored. Source scenery remains a
    diagnostic/repair target when it sits on that outer face. Only newly
    emitted scenery is eligible for deletion later in the ordered repair policy.
    """
    candidate_cells = olden_cells if olden_cells is not None else building.olden_cells
    return _unwanted_contacts(
        state,
        building,
        olden_cells=candidate_cells,
        excluded_ids=excluded_ids,
    )

def _move_candidates(
    state: _State,
    building: InstanceFootprint,
    *,
    allowed_removed_scenery: set[int] | None = None,
    max_steps: int = MAX_REPOSITION_STEPS,
) -> list[dict[str, Any]]:
    removed = allowed_removed_scenery or set()
    if max_steps < 1:
        raise ValueError(f"max_steps must be >= 1, got {max_steps}")
    candidates: list[dict[str, Any]] = []
    for direction_index, (direction, unit_dx, unit_dy) in enumerate(CARDINAL_DIRECTIONS):
        for step in range(1, max_steps + 1):
            dx = unit_dx * step
            dy = unit_dy * step
            node = _candidate_node(state, building.node, dx, dy)
            if node is None:
                continue
            candidate_layer = state.layer_for_node(node)
            if (
                building.layer is not None
                and state.layer_resolver is not None
                and candidate_layer != building.layer
            ):
                continue
            translated = _translate_cells(
                building.olden_cells,
                dx=dx,
                dy=dy,
                width=state.width,
                height=state.height,
            )
            if translated is None:
                continue
            if (
                building.layer is not None
                and not state.cells_in_layer(translated, building.layer)
            ):
                continue
            overlaps = _overlapping_blockers(
                state,
                building,
                translated,
                excluded_ids=removed,
            )
            unsafe_overlaps = _unsafe_overlapping_blockers(
                state,
                building,
                translated,
                excluded_ids=removed,
            )
            issues = _effective_contact_issues(
                state,
                building,
                olden_cells=translated,
                excluded_ids=removed,
            )
            unresolved_blockers = _unresolved_blockers_at(
                state,
                building,
                translated,
                excluded_ids=removed,
            )
            unpreserved_h3_blocker_cells = _unpreserved_h3_blocker_cells_after_move(
                state,
                building,
                translated,
                excluded_ids=removed,
            )
            uncovered_extra_olden_cells = _uncovered_extra_olden_cells_after_move(
                state,
                building,
                translated,
                excluded_ids=removed,
            )
            candidates.append(
                {
                    "direction": direction,
                    "directionIndex": direction_index,
                    "step": step,
                    "dx": dx,
                    "dy": dy,
                    "node": node,
                    "cells": translated,
                    "overlaps": overlaps,
                    "unsafeOverlaps": unsafe_overlaps,
                    "issues": issues,
                    "unresolvedBlockers": unresolved_blockers,
                    "unpreservedH3BlockerCells": unpreserved_h3_blocker_cells,
                    "uncoveredExtraOldenCells": uncovered_extra_olden_cells,
                    "valid": (
                        not unsafe_overlaps
                        and not issues
                        and not unresolved_blockers
                        and not unpreserved_h3_blocker_cells
                        and not uncovered_extra_olden_cells
                    ),
                    "footprintDifference": len(set(translated) ^ set(building.h3_closed_cells)),
                }
            )
    return candidates


def _move_is_clear(
    *,
    unsafe_overlaps: list[InstanceFootprint],
    issues: list[ContactIssue],
    unresolved_blockers: list[InstanceFootprint],
    unpreserved_h3_blocker_cells: frozenset[int],
    uncovered_extra_olden_cells: frozenset[int],
) -> bool:
    return (
        not unsafe_overlaps
        and not issues
        and not unresolved_blockers
        and not unpreserved_h3_blocker_cells
        and not uncovered_extra_olden_cells
    )


def _scenery_cleanup_for_candidate(
    state: _State,
    building: InstanceFootprint,
    candidate: dict[str, Any],
) -> set[int] | None:
    """Return any-size removable scenery set that makes ``candidate`` valid.

    Starts from scenery that overlaps or contacts the moved footprint, then
    expands until the move is clear or a non-removable obstruction remains.
    Buildings and non-removable scenery abort the candidate.
    """
    if candidate.get("unresolvedBlockers"):
        return None
    required: set[int] = set()
    while True:
        unsafe_overlaps = _unsafe_overlapping_blockers(
            state,
            building,
            candidate["cells"],
            excluded_ids=required,
        )
        issues = _effective_contact_issues(
            state,
            building,
            olden_cells=candidate["cells"],
            excluded_ids=required,
        )
        unresolved_blockers = _unresolved_blockers_at(
            state,
            building,
            candidate["cells"],
            excluded_ids=required,
        )
        unpreserved_h3 = _unpreserved_h3_blocker_cells_after_move(
            state,
            building,
            candidate["cells"],
            excluded_ids=required,
        )
        uncovered_extra = _uncovered_extra_olden_cells_after_move(
            state,
            building,
            candidate["cells"],
            excluded_ids=required,
        )
        if _move_is_clear(
            unsafe_overlaps=unsafe_overlaps,
            issues=issues,
            unresolved_blockers=unresolved_blockers,
            unpreserved_h3_blocker_cells=unpreserved_h3,
            uncovered_extra_olden_cells=uncovered_extra,
        ):
            if required:
                set_removable, _reason = _scenery_set_can_be_removed(
                    state,
                    required,
                    excluded_ids={building.object_id},
                    preserved_blocker_cells=candidate["cells"],
                )
                if not set_removable:
                    return None
            return required

        if unresolved_blockers or unpreserved_h3 or uncovered_extra:
            return None

        added = False
        obstructions = list(unsafe_overlaps)
        for issue in issues:
            blocker = state.instances.get(issue.blocker_id)
            if blocker is not None and blocker not in obstructions:
                obstructions.append(blocker)
        for blocker in obstructions:
            if blocker.object_id in required:
                continue
            if not blocker.is_scenery:
                return None
            removable, _reason = _scenery_can_be_removed(
                state,
                blocker,
                excluded_ids={building.object_id} | required,
                preserved_blocker_cells=candidate["cells"],
            )
            if not removable:
                return None
            required.add(blocker.object_id)
            added = True
        if not added:
            return None


def _candidate_report(candidate: dict[str, Any]) -> dict[str, Any]:
    rejection_reasons: list[str] = []
    if candidate.get("unsafeOverlaps"):
        rejection_reasons.append("unsafe_permanent_overlap")
    if candidate.get("issues"):
        rejection_reasons.append("unwanted_cardinal_contact")
    if candidate.get("unresolvedBlockers"):
        rejection_reasons.append("unresolved_blocker_footprint")
    if candidate.get("unpreservedH3BlockerCells"):
        rejection_reasons.append("unpreserved_h3_blocker_cell")
    if candidate.get("uncoveredExtraOldenCells"):
        rejection_reasons.append("new_uncovered_olden_blocker_cell")
    return {
        "direction": candidate["direction"],
        "step": candidate.get("step", 1),
        "node": candidate["node"],
        "occupiedCells": sorted(candidate["cells"]),
        "overlapBlockers": [
            {"objectId": instance.object_id, "sid": instance.sid, "kind": instance.kind}
            for instance in candidate["overlaps"]
        ],
        "unsafeOverlapBlockers": [
            {"objectId": instance.object_id, "sid": instance.sid, "kind": instance.kind}
            for instance in candidate.get("unsafeOverlaps", [])
        ],
        "unwantedContacts": [issue.as_dict() for issue in candidate["issues"]],
        "unresolvedH3BlockerCells": sorted(candidate.get("unpreservedH3BlockerCells") or []),
        "uncoveredExtraOldenCells": sorted(candidate.get("uncoveredExtraOldenCells") or []),
        "unresolvedBlockers": [
            {
                "objectId": instance.object_id,
                "sid": instance.sid,
                "kind": instance.kind,
                "h3Status": instance.h3_status,
            }
            for instance in candidate["unresolvedBlockers"]
        ],
        "footprintDifference": candidate["footprintDifference"],
        "rejectionReasons": rejection_reasons,
        "valid": candidate["valid"],
    }

def _apply_move(state: _State, object_id: int, node: int) -> None:
    for group in state.objects:
        ids = group.get("ids") or []
        if object_id not in ids:
            continue
        index = ids.index(object_id)
        nodes = group.get("nodes") or []
        if index >= len(nodes):
            raise ValueError(f"object {object_id} missing node slot")
        nodes[index] = node
        state.update_node(object_id, node)
        return
    raise ValueError(f"object {object_id} not found for move")


def _result_row(
    instance: InstanceFootprint,
    *,
    h3_matches_olden: bool,
    initial_issues: list[ContactIssue],
) -> dict[str, Any]:
    return {
        "objectId": instance.object_id,
        "sid": instance.sid,
        "sourceIndex": instance.source_index,
        "node": instance.node,
        "rotation": instance.rotation,
        "h3Cells": sorted(instance.h3_cells),
        "h3LandOnCells": sorted(instance.h3_land_on_cells),
        "oldenCells": sorted(instance.olden_cells),
        "nativeGateCells": sorted(instance.native_gate_cells),
        "footprintMatches": h3_matches_olden,
        "nativeModelStatus": instance.native_model_status,
        "nativeUnresolved": list(instance.native_unresolved),
        "initialUnwantedContacts": [issue.as_dict() for issue in initial_issues],
    }


def apply_homm3_footprint_compatibility(
    *,
    global_entities: list[dict[str, Any]],
    objects: list[dict[str, Any]],
    object_properties: dict[str, Any] | None,
    native_object_configs: dict[str, dict[str, Any]],
    layer_target_node: Callable[[int, int, int], int],
    width: int,
    height: int,
    map_sid: str,
    layer_resolver: Callable[[int], int | None] | None = None,
    dry_run: bool = False,
    raise_on_failure: bool = False,
) -> dict[str, Any]:
    """Repair only extra cardinal blockers around mismatched buildings.

    Runs the full ordered repair policy for every mismatched building. By
    default the pass is fail-open: successful repairs are committed even when
    some buildings remain unresolved, and those unresolved cases are reported
    without raising. Set ``raise_on_failure=True`` for the legacy fail-closed
    transaction that refuses to commit when any building is unresolved.
    """
    if width <= 0 or height <= 0:
        raise ValueError(f"invalid map dimensions: {width}x{height}")

    working_objects = copy.deepcopy(objects)
    working_properties = copy.deepcopy(object_properties) if object_properties is not None else None
    state = _State(
        objects=working_objects,
        global_entities=global_entities,
        native_object_configs=native_object_configs,
        layer_target_node=layer_target_node,
        width=width,
        height=height,
        layer_resolver=layer_resolver,
    )
    building_instances = sorted(
        (instance for instance in state.instances.values() if instance.kind == "building"),
        key=lambda instance: instance.object_id,
    )
    mismatched = [
        instance
        for instance in building_instances
        if instance.h3_status.startswith("source_h3_projected")
        and _h3_footprint_mismatched(instance)
    ]
    unresolved_h3_buildings = [
        instance
        for instance in building_instances
        if instance.source_index is not None and not instance.h3_footprint_known
    ]
    unresolved_native_instances = sorted(
        (
            instance
            for instance in state.instances.values()
            if instance.kind in {"building", "scenery"} and instance.native_cell_unresolved
        ),
        key=lambda instance: instance.object_id,
    )
    report: dict[str, Any] = {
        "schema": SCHEMA,
        "status": STATUS_DRY_RUN if dry_run else STATUS_NOOP,
        "mapSid": map_sid,
        "width": width,
        "height": height,
        "policy": (
            "mismatched_building_then_outer_face_of_new_olden_blocker_contacts_with_"
            "H3_land_on_wildcards_then_remove_new_scenery_then_up_to_2_tile_cardinal_"
            "reposition_allowing_scenery_dig_in_and_preserving_H3_hard_blockers_then_"
            "any_removable_scenery_cleanup"
        ),
        "maxRepositionSteps": MAX_REPOSITION_STEPS,
        "proofBoundary": (
            "H3 non-visitable block masks compared with native ObjectConfig nodes; "
            "H3 land-on/visit cells are wildcards (closed or open, whichever is more "
            "permissive); adjacency counts only on the outer face of newly emitted "
            "Olden blockers; resources and meta/enemy objects excluded; no global "
            "path search performed"
        ),
        "buildingCount": len(building_instances),
        "mismatchedBuildingCount": len(mismatched),
        "unresolvedH3BuildingCount": len(unresolved_h3_buildings),
        "unresolvedNativeCellInstanceCount": len(unresolved_native_instances),
        "deletedObjectIds": [],
        "movedBuildings": [],
        "unchangedMismatches": [],
        "repairs": [],
        "failures": [],
        "missingNativeConfigs": list(state.missing_native_configs),
        "skippedSyntheticOutsideLayerEnvelope": list(
            state.skipped_synthetic_outside_layer_envelope
        ),
    }

    for missing in state.missing_native_configs:
        report["failures"].append({
            "objectId": missing["objectId"],
            "sid": missing["sid"],
            "reason": "missing_native_object_config_for_emitted_source_object",
        })

    for unresolved in unresolved_native_instances:
        failure = _result_row(
            unresolved,
            h3_matches_olden=False,
            initial_issues=[],
        )
        failure.update({
            "reason": "cannot_compare_unresolved_native_cell_footprint",
            "nativeCellUnresolved": list(unresolved.native_cell_unresolved),
        })
        report["failures"].append(failure)

    for unresolved in unresolved_h3_buildings:
        failure = _result_row(
            unresolved,
            h3_matches_olden=False,
            initial_issues=[],
        )
        failure.update({
            "reason": "cannot_compare_invalid_H3_footprint",
            "h3Status": unresolved.h3_status,
        })
        report["failures"].append(failure)
    for original in mismatched:
        current = state.instances.get(original.object_id)
        if current is None:
            continue
        if current.native_cell_unresolved:
            continue
        if current.h3_status == "synthetic_h3_seal" or not current.h3_footprint_known:
            failure = _result_row(
                current,
                h3_matches_olden=False,
                initial_issues=[],
            )
            failure.update({
                "reason": "cannot_compare_invalid_H3_footprint",
                "h3Status": current.h3_status,
            })
            report["failures"].append(failure)
            continue
        initial_issues = _effective_contact_issues(state, current)
        if not initial_issues:
            unchanged = _result_row(
                current,
                h3_matches_olden=False,
                initial_issues=[],
            )
            unchanged["reason"] = "no_new_cardinal_contact"
            report["unchangedMismatches"].append(unchanged)
            continue
        unresolved_initial_blockers = _unresolved_blockers_at(state, current, current.olden_cells)
        if unresolved_initial_blockers:
            report["failures"].append(
                {
                    "objectId": current.object_id,
                    "sid": current.sid,
                    "reason": "cannot_compare_blocker_H3_footprint",
                    "unresolvedBlockers": [
                        {
                            "objectId": instance.object_id,
                            "sid": instance.sid,
                            "kind": instance.kind,
                            "h3Status": instance.h3_status,
                        }
                        for instance in unresolved_initial_blockers
                    ],
                    "contacts": [issue.as_dict() for issue in initial_issues],
                }
            )
            continue

        repair: dict[str, Any] = _result_row(
            current,
            h3_matches_olden=False,
            initial_issues=initial_issues,
        )

        # First remove scenery only when every in-map H3 blocker cell it owns
        # remains occupied by another permanent blocker. Check each deletion
        # against the current state so a deletion set cannot open a tile.
        first_delete_ids: set[int] = set()
        for issue in initial_issues:
            blocker = state.instances.get(issue.blocker_id)
            if blocker is None or not blocker.is_scenery or not _scenery_is_new(blocker):
                continue
            removable, _reason = _scenery_can_be_removed(
                state,
                blocker,
                excluded_ids={current.object_id},
            )
            if removable:
                first_delete_ids.add(blocker.object_id)
        if first_delete_ids:
            safe_first_delete_ids: set[int] = set()
            first_delete_reasons: dict[int, str] = {}
            for object_id in sorted(first_delete_ids):
                blocker = state.instances.get(object_id)
                if blocker is None:
                    continue
                removable, reason = _scenery_can_be_removed(
                    state,
                    blocker,
                    excluded_ids={current.object_id},
                )
                if not removable:
                    continue
                state.remove({object_id})
                if working_properties is not None:
                    layered_objects.remove_property_rows_for_object_ids(
                        working_properties,
                        {object_id},
                    )
                safe_first_delete_ids.add(object_id)
                first_delete_reasons[object_id] = reason
            first_delete_ids = safe_first_delete_ids
            if first_delete_ids:
                report["deletedObjectIds"].extend(sorted(first_delete_ids))
                repair["deletedNewScenery"] = [
                    {"objectId": object_id, "reason": first_delete_reasons[object_id]}
                    for object_id in sorted(first_delete_ids)
                ]
            current = state.instances.get(current.object_id)
            if current is None:
                raise ValueError(f"building disappeared during compatibility pass: {original.object_id}")
            remaining = _effective_contact_issues(state, current)
            if not remaining:
                repair["status"] = "repaired_by_new_scenery_delete"
                repair.update(_result_row(current, h3_matches_olden=False, initial_issues=initial_issues))
                report["repairs"].append(repair)
                continue
            initial_issues = remaining
        # Second, try an up-to-2-tile cardinal reposition without deleting scenery.
        candidates = _move_candidates(state, current)
        valid_moves = [candidate for candidate in candidates if candidate["valid"]]
        if valid_moves:
            chosen = min(
                valid_moves,
                key=lambda candidate: (
                    int(candidate["step"]),
                    candidate["footprintDifference"],
                    candidate["directionIndex"],
                ),
            )
            _apply_move(state, current.object_id, int(chosen["node"]))
            moved = state.instances[current.object_id]
            move_row = {
                "objectId": current.object_id,
                "sid": current.sid,
                "fromNode": current.node,
                "toNode": moved.node,
                "direction": chosen["direction"],
                "step": int(chosen["step"]),
                "reason": "cardinal_reposition_cleared_unwanted_blocker_contacts",
            }
            report["movedBuildings"].append(move_row)
            repair["status"] = "repaired_by_cardinal_reposition"
            repair["move"] = move_row
            repair.update(_result_row(moved, h3_matches_olden=False, initial_issues=initial_issues))
            report["repairs"].append(repair)
            continue

        # Third, for each 1- or 2-tile move, cull any removable scenery set that
        # makes the move valid. Prefer fewer culls, then shorter moves. Buildings
        # and non-removable blockers are never deleted by this pass.
        cleanup_options: list[tuple[tuple[int, int, int, int], dict[str, Any], set[int]]] = []
        for candidate in candidates:
            required_scenery = _scenery_cleanup_for_candidate(state, current, candidate)
            if required_scenery is None:
                continue
            cleanup_options.append(
                (
                    (
                        len(required_scenery),
                        int(candidate["step"]),
                        candidate["footprintDifference"],
                        candidate["directionIndex"],
                    ),
                    candidate,
                    required_scenery,
                )
            )
        if cleanup_options:
            _score, chosen, cleanup_ids = min(cleanup_options, key=lambda item: item[0])
            cleanup_reasons: dict[int, str] = {}
            for object_id in sorted(cleanup_ids):
                removable, reason = _scenery_can_be_removed(
                    state,
                    state.instances[object_id],
                    excluded_ids={current.object_id},
                    preserved_blocker_cells=chosen["cells"],
                )
                if not removable:
                    raise ValueError(f"scenery removability changed during compatibility pass: {object_id}")
                cleanup_reasons[object_id] = reason
            state.remove(cleanup_ids)
            if working_properties is not None:
                layered_objects.remove_property_rows_for_object_ids(working_properties, cleanup_ids)
            report["deletedObjectIds"].extend(sorted(cleanup_ids))
            _apply_move(state, current.object_id, int(chosen["node"]))
            moved = state.instances[current.object_id]
            move_row = {
                "objectId": current.object_id,
                "sid": current.sid,
                "fromNode": current.node,
                "toNode": moved.node,
                "direction": chosen["direction"],
                "step": int(chosen["step"]),
                "reason": "scenery_cleanup_then_cardinal_reposition",
                "deletedScenery": [
                    {"objectId": object_id, "reason": cleanup_reasons[object_id]}
                    for object_id in sorted(cleanup_ids)
                ],
            }
            report["movedBuildings"].append(move_row)
            repair["status"] = "repaired_by_scenery_cleanup_and_reposition"
            repair["move"] = move_row
            repair.update(_result_row(moved, h3_matches_olden=False, initial_issues=initial_issues))
            report["repairs"].append(repair)
            continue

        candidate_reports = [_candidate_report(candidate) for candidate in candidates]
        report["failures"].append(
            {
                "objectId": current.object_id,
                "sid": current.sid,
                "reason": "no_safe_scenery_delete_or_reposition",
                "h3Cells": sorted(current.h3_cells),
                "h3LandOnCells": sorted(current.h3_land_on_cells),
                "oldenCells": sorted(current.olden_cells),
                "h3Status": current.h3_status,
                "nativeModelStatus": current.native_model_status,
                "nativeUnresolved": list(current.native_unresolved),
                "unwantedContacts": [issue.as_dict() for issue in initial_issues],
                "candidateMoves": candidate_reports,
                "candidateRejectionReasons": [
                    {
                        "direction": candidate["direction"],
                        "step": candidate.get("step", 1),
                        "reasons": candidate["rejectionReasons"],
                    }
                    for candidate in candidate_reports
                ],
            }
        )

    report["deletedObjectIds"] = sorted(set(report["deletedObjectIds"]))
    has_failures = bool(report["failures"])
    has_repairs = bool(report["repairs"])
    if dry_run:
        report["status"] = STATUS_DRY_RUN
    elif has_failures and raise_on_failure:
        report["status"] = STATUS_FAILED
    elif has_failures:
        report["status"] = STATUS_APPLIED_WITH_UNRESOLVED
    elif has_repairs:
        report["status"] = STATUS_APPLIED
    else:
        report["status"] = STATUS_NOOP

    if has_failures:
        report["notification"] = (
            f"{'failed closed' if raise_on_failure else 'fail-open'}: "
            f"{len(report['failures'])} building(s) still have unwanted "
            "cardinal blockers or lack a trustworthy H3 footprint; "
            f"{len(report['repairs'])} repair(s) applied"
        )
        if raise_on_failure:
            raise Homm3FootprintCompatibilityError(report)
        if not dry_run:
            objects[:] = working_objects
            if object_properties is not None and working_properties is not None:
                object_properties.clear()
                object_properties.update(working_properties)
        return report

    if not dry_run:
        objects[:] = working_objects
        if object_properties is not None and working_properties is not None:
            object_properties.clear()
            object_properties.update(working_properties)
    report["notification"] = "compatibility pass completed without unresolved repairs"
    return report
