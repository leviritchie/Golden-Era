"""Shared HoMM3 town placement alignment for stock and land-on city SIDs.

Stock / non-landon cities: Olden GATE cell == one cell north of H3 visit.
Landon cities: Olden 3x3 footprint center == one cell north of the H3 town
body-center (block∪visit bbox). GATE stays south-center of that 3x3.

Why the north shift: VCMI/H3 visit sits on the south mask row (courtyard /
entrance). Centering the Olden 3x3 on raw body∪visit put GATE on that visit
cell and filled the courtyard — Homecoming SW then showed one beach cell
town→boat instead of VCMI's two. Shifting the building mass one cell north
leaves the H3 visit row open and restores the gap. (Boat 1x1 visit-align is
separate; do not reintroduce multi-tile BR boats.)

VCMI ``ObjectTemplate::readMap`` + ``visitablePos`` still define H3 visit; we
deliberately do not put Olden GATE on that cell for adventure-map mass parity.

Used by vanilla_stock and Golden Era / approach_cell emitters so both lanes
share one alignment rule. Relies on ``exact_homm3_footprint.derive_gate_aligned_node``
and does not import surface_emit (avoids circular imports / atlas globals).
"""

from __future__ import annotations

from typing import Any, Callable

import exact_homm3_footprint as exact_fp

POLICY = "town_gate_aligned_one_north_of_h3_visit"
LANDON_BODY_CENTER_POLICY = "landon_town_center_aligned_one_north_of_h3_body_center"

H3M_MASK_WIDTH = 8
H3M_MASK_HEIGHT = 6
H3M_MASK_ANCHOR_X = 7
H3M_MASK_ANCHOR_Y = 5


class TownGateAlignError(ValueError):
    """Fail-closed town GATE alignment error."""


def h3m_visit_mask_offsets(mask: Any) -> set[tuple[int, int]]:
    """Decode templateVisitMask bits to BR-relative (dx, dy) offsets (Y south)."""
    if not isinstance(mask, list) or len(mask) != H3M_MASK_HEIGHT:
        return set()
    offsets: set[tuple[int, int]] = set()
    for row_index, raw in enumerate(mask):
        if not isinstance(raw, int) or raw < 0 or raw > 255:
            raise TownGateAlignError(f"invalid H3 visit mask byte: {raw!r}")
        for col_index in range(H3M_MASK_WIDTH):
            if raw & (1 << col_index):
                offsets.add((col_index - H3M_MASK_ANCHOR_X, row_index - H3M_MASK_ANCHOR_Y))
    return offsets


def h3m_block_mask_offsets(mask: Any) -> set[tuple[int, int]]:
    """Decode templateBlockMask: bit 0 means blocked (VCMI / H3M convention)."""
    if not isinstance(mask, list) or len(mask) != H3M_MASK_HEIGHT:
        return set()
    offsets: set[tuple[int, int]] = set()
    for row_index, raw in enumerate(mask):
        if not isinstance(raw, int) or raw < 0 or raw > 255:
            raise TownGateAlignError(f"invalid H3 block mask byte: {raw!r}")
        for col_index in range(H3M_MASK_WIDTH):
            if (raw >> col_index) & 1 == 0:
                offsets.add((col_index - H3M_MASK_ANCHOR_X, row_index - H3M_MASK_ANCHOR_Y))
    return offsets


def town_visit_source_xy(entity: dict[str, Any]) -> tuple[int, int]:
    """Return the unique H3 source (x, y) of the town visit cell."""
    source_x = entity.get("sourceX", entity.get("x"))
    source_y = entity.get("sourceY", entity.get("y"))
    if not isinstance(source_x, int) or not isinstance(source_y, int):
        raise TownGateAlignError(
            f"town GATE align requires source coordinates: {entity.get('sourceKey') or entity.get('key')}"
        )
    offsets = h3m_visit_mask_offsets(entity.get("templateVisitMask"))
    if len(offsets) != 1:
        raise TownGateAlignError(
            f"town GATE align requires exactly one H3 visit cell for "
            f"{entity.get('sourceKey') or entity.get('key')}; got {sorted(offsets)}"
        )
    dx, dy = next(iter(offsets))
    return source_x + dx, source_y + dy


def town_body_source_cells(entity: dict[str, Any]) -> set[tuple[int, int]]:
    """H3 source cells covered by the town body (block ∪ visit)."""
    source_x = entity.get("sourceX", entity.get("x"))
    source_y = entity.get("sourceY", entity.get("y"))
    if not isinstance(source_x, int) or not isinstance(source_y, int):
        raise TownGateAlignError(
            f"town body center requires source coordinates: {entity.get('sourceKey') or entity.get('key')}"
        )
    visits = h3m_visit_mask_offsets(entity.get("templateVisitMask"))
    blocks = h3m_block_mask_offsets(entity.get("templateBlockMask"))
    cells = {(source_x + dx, source_y + dy) for dx, dy in visits | blocks}
    if not cells:
        raise TownGateAlignError(
            f"town body center requires non-empty block∪visit for "
            f"{entity.get('sourceKey') or entity.get('key')}"
        )
    return cells


def town_body_center_source_xy(entity: dict[str, Any]) -> tuple[int, int]:
    """Placement center for Olden towns: one cell north of H3 body∪visit center.

    Raw integer center of block∪visit puts the south GATE on the H3 visit /
    courtyard row. Shift north so that row stays open (VCMI beach gap parity).
    """
    cells = town_body_source_cells(entity)
    xs = [x for x, _ in cells]
    ys = [y for _, y in cells]
    cx = (min(xs) + max(xs)) // 2
    cy = (min(ys) + max(ys)) // 2
    if cy < 1:
        raise TownGateAlignError(
            f"town body center north-shift out of bounds for "
            f"{entity.get('sourceKey') or entity.get('key')}: rawCenter=({cx},{cy})"
        )
    return cx, cy - 1


def town_gate_source_xy(entity: dict[str, Any]) -> tuple[int, int]:
    """H3 source cell where Olden GATE should land: one north of H3 visit."""
    visit_x, visit_y = town_visit_source_xy(entity)
    if visit_y < 1:
        raise TownGateAlignError(
            f"town GATE north-of-visit out of bounds for "
            f"{entity.get('sourceKey') or entity.get('key')}: visit=({visit_x},{visit_y})"
        )
    return visit_x, visit_y - 1


def olden_node_north_of(node: int, grid_width: int, grid_height: int) -> int:
    """Olden +Y is north (H3 Y-south atlas flip)."""
    x = node % grid_width
    y = node // grid_width
    north_y = y + 1
    if not (0 <= north_y < grid_height):
        raise TownGateAlignError(
            f"olden north-of-node out of bounds: node={node} -> ({x},{north_y})"
        )
    return north_y * grid_width + x


def is_town_city_sid(sid: str) -> bool:
    """True for Olden city ObjectConfig SIDs (stock or homm3 / landon)."""
    if not isinstance(sid, str) or not sid:
        return False
    if sid == "random-city":
        return True
    return sid.endswith("_city")


def is_landon_city_sid(sid: str) -> bool:
    """True for land-on visit-gate city clones (homm3_landon_*_city)."""
    return (
        isinstance(sid, str)
        and sid.startswith("homm3_landon_")
        and sid.endswith("_city")
    )


def town_gate_footprint(config: dict[str, Any], sid: str) -> exact_fp.SameSizeFootprint:
    """Footprint with native GATE local for visit alignment (fail if no single GATE)."""
    # Ensure classify sees the SID (landon prefix / single_gate).
    cfg = dict(config)
    if not cfg.get("id"):
        cfg["id"] = sid
    footprint = exact_fp.footprint_from_donor_config(cfg)
    if footprint.gate_config_x is None or footprint.gate_config_z is None:
        # Stock cities are single_gate; if classify missed, take the unique nodes==2 cell.
        size_x, size_z = footprint.size_x, footprint.size_z
        gates = [
            (i % size_x, i // size_x)
            for i, value in enumerate(footprint.nodes)
            if int(value) == 2
        ]
        if len(gates) != 1:
            raise TownGateAlignError(
                f"town SID {sid} needs exactly one GATE marker for visit alignment; "
                f"found {gates} nodes={list(footprint.nodes)}"
            )
        gate_x, gate_z = gates[0]
        footprint = exact_fp.SameSizeFootprint(
            size_x=size_x,
            size_z=size_z,
            nodes=footprint.nodes,
            gate_config_x=gate_x,
            gate_config_z=gate_z,
            in_grid_block_count=footprint.in_grid_block_count,
            overflow_block_count=footprint.overflow_block_count,
            kind=footprint.kind,
        )
    return footprint


def align_town_emit_node(
    *,
    entity: dict[str, Any],
    replacement_sid: str,
    native_config: dict[str, Any],
    visit_node: int,
    default_node: int,
    grid_width: int,
    grid_height: int,
    rotation: int = 0,
    body_center_node: int | None = None,
) -> tuple[int, dict[str, Any]]:
    """Place city for adventure-map play.

    Land-on cities: center the 3x3 one cell north of H3 body center.
    Other city SIDs: GATE cell equals one cell north of H3 visit.
    """
    if not is_town_city_sid(replacement_sid):
        raise TownGateAlignError(f"not a town city SID: {replacement_sid}")
    footprint = town_gate_footprint(native_config, replacement_sid)
    if is_landon_city_sid(replacement_sid):
        return align_landon_town_emit_node(
            entity=entity,
            replacement_sid=replacement_sid,
            footprint=footprint,
            native_config=native_config,
            body_center_node=body_center_node,
            visit_node=visit_node,
            default_node=default_node,
            grid_width=grid_width,
            grid_height=grid_height,
            rotation=rotation,
        )
    # Stock / non-landon: GATE on the cell north of H3 visit (courtyard open).
    gate_target_node = olden_node_north_of(visit_node, grid_width, grid_height)
    node, evidence = exact_fp.derive_gate_aligned_node(
        visit_node=gate_target_node,
        footprint=footprint,
        native_config=native_config,
        grid_width=grid_width,
        grid_height=grid_height,
        default_node=default_node,
        rotation=rotation,
        can_be_mirrored=native_config.get("canBeMirrored") is True,
    )
    evidence = dict(evidence)
    evidence["policy"] = POLICY
    evidence["reason"] = "town_gate_one_north_of_h3_visit_courtyard_open"
    evidence["decision"] = "align_olden_node_so_gate_equals_one_north_of_h3_visit"
    evidence["replacementSid"] = replacement_sid
    source_x = entity.get("sourceX", entity.get("x"))
    source_y = entity.get("sourceY", entity.get("y"))
    if isinstance(source_x, int) and isinstance(source_y, int):
        evidence["sourceAnchor"] = [source_x, source_y]
    visit_x = visit_node % grid_width
    visit_y = visit_node // grid_width
    emit_x = node % grid_width
    emit_y = node // grid_width
    evidence["nodeDelta"] = [emit_x - (default_node % grid_width), emit_y - (default_node // grid_width)]
    evidence["visitNode"] = visit_node
    evidence["gateTargetNode"] = gate_target_node
    evidence["emitNode"] = node
    # Verify GATE lands on north-of-visit with the projection the anchor was derived from.
    gate_x = footprint.gate_config_x
    gate_z = footprint.gate_config_z
    assert gate_x is not None and gate_z is not None
    gate_node = exact_fp.project_config_local_cell(
        native_config,
        anchor_node=node,
        local_x=gate_x,
        local_z=gate_z,
        size_x=footprint.size_x,
        size_z=footprint.size_z,
        grid_width=grid_width,
        grid_height=grid_height,
        rotation=rotation,
        can_be_mirrored=native_config.get("canBeMirrored") is True,
    )
    if gate_node != gate_target_node:
        raise TownGateAlignError(
            f"town GATE alignment failed for {entity.get('sourceKey') or entity.get('key')}: "
            f"visit={visit_node} gateTarget={gate_target_node} gateNode={gate_node} emit={node} "
            f"gateLocal=({gate_x},{gate_z}) sid={replacement_sid}"
        )
    evidence["gateNodes"] = [gate_node]
    evidence["visitSource"] = list(town_visit_source_xy(entity))
    evidence["gateSource"] = list(town_gate_source_xy(entity))
    return node, evidence


def align_landon_town_emit_node(
    *,
    entity: dict[str, Any],
    replacement_sid: str,
    footprint: exact_fp.SameSizeFootprint,
    native_config: dict[str, Any],
    body_center_node: int | None,
    visit_node: int,
    default_node: int,
    grid_width: int,
    grid_height: int,
    rotation: int = 0,
) -> tuple[int, dict[str, Any]]:
    """Center land-on 3x3 one north of H3 body center; GATE stays south-center."""
    if body_center_node is None:
        raise TownGateAlignError(
            f"landon city {replacement_sid} requires body_center_node for "
            f"{entity.get('sourceKey') or entity.get('key')}"
        )
    if footprint.size_x < 1 or footprint.size_z < 1:
        raise TownGateAlignError(f"invalid landon footprint for {replacement_sid}")
    # Geometric center of the ObjectConfig grid (config local).
    center_config_x = footprint.size_x // 2
    center_config_z = footprint.size_z // 2
    center_x = body_center_node % grid_width
    center_y = body_center_node // grid_width
    mirrored = rotation == 10 and native_config.get("canBeMirrored") is True
    can_be_mirrored = native_config.get("canBeMirrored") is True
    try:
        node, projection = exact_fp.anchor_for_config_local_cell(
            native_config,
            local_x=center_config_x,
            local_z=center_config_z,
            target_node=body_center_node,
            size_x=footprint.size_x,
            size_z=footprint.size_z,
            grid_width=grid_width,
            grid_height=grid_height,
            rotation=rotation,
            can_be_mirrored=can_be_mirrored,
        )
    except ValueError as exc:
        raise TownGateAlignError(
            f"landon body-center emit failed for {entity.get('sourceKey') or entity.get('key')}: "
            f"center={body_center_node} sid={replacement_sid}: {exc}"
        ) from exc
    emit_x = node % grid_width
    emit_y = node // grid_width
    gate_x = footprint.gate_config_x
    gate_z = footprint.gate_config_z
    assert gate_x is not None and gate_z is not None

    def _project(local_x: int, local_z: int) -> int | None:
        return exact_fp.project_config_local_cell(
            native_config,
            anchor_node=node,
            local_x=local_x,
            local_z=local_z,
            size_x=footprint.size_x,
            size_z=footprint.size_z,
            grid_width=grid_width,
            grid_height=grid_height,
            rotation=rotation,
            can_be_mirrored=can_be_mirrored,
        )

    gate_node = _project(gate_x, gate_z)
    if gate_node is None:
        raise TownGateAlignError(
            f"landon GATE out of bounds for {entity.get('sourceKey') or entity.get('key')}: "
            f"anchor={node} sid={replacement_sid}"
        )
    placed_center = _project(center_config_x, center_config_z)
    if placed_center != body_center_node:
        raise TownGateAlignError(
            f"landon body-center verify failed for {entity.get('sourceKey') or entity.get('key')}: "
            f"wanted={body_center_node} placed={placed_center}"
        )
    body_sx, body_sy = town_body_center_source_xy(entity)
    evidence: dict[str, Any] = {
        "policy": LANDON_BODY_CENTER_POLICY,
        "reason": "landon_town_center_one_north_of_h3_body_center_courtyard_open",
        "decision": "align_olden_3x3_center_one_north_of_h3_body_gate_south_center",
        "replacementSid": replacement_sid,
        "visitNode": visit_node,
        "bodyCenterNode": body_center_node,
        "emitNode": node,
        "gateNodes": [gate_node],
        "bodyCenterSource": [body_sx, body_sy],
        "visitSource": list(town_visit_source_xy(entity)),
        "gateSource": list(town_gate_source_xy(entity)),
        "nativeFootprint": {
            "width": footprint.size_x,
            "height": footprint.size_z,
            "gateLocal": [gate_x, gate_z],
            "centerLocal": [center_config_x, center_config_z],
            "kind": footprint.kind,
            "mirrored": mirrored,
            "anchorProjection": projection,
        },
        "nodeDelta": [emit_x - (default_node % grid_width), emit_y - (default_node // grid_width)],
    }
    source_x = entity.get("sourceX", entity.get("x"))
    source_y = entity.get("sourceY", entity.get("y"))
    if isinstance(source_x, int) and isinstance(source_y, int):
        evidence["sourceAnchor"] = [source_x, source_y]
    return node, evidence


def align_town_emit_node_via_atlas(
    *,
    entity: dict[str, Any],
    replacement_sid: str,
    native_config: dict[str, Any],
    atlas_target_node: Callable[[int, int, int], int],
    layer: int,
    atlas_width: int,
    atlas_height: int,
    rotation: int = 0,
) -> tuple[int, dict[str, Any]]:
    """Vanilla/atlas variant: map H3 visit / body center through ``atlas.target_node``."""
    visit_sx, visit_sy = town_visit_source_xy(entity)
    source_x = int(entity.get("sourceX", entity.get("x")))
    source_y = int(entity.get("sourceY", entity.get("y")))
    default_node = atlas_target_node(layer, source_x, source_y)
    visit_node = atlas_target_node(layer, visit_sx, visit_sy)
    body_center_node = None
    if is_landon_city_sid(replacement_sid):
        body_sx, body_sy = town_body_center_source_xy(entity)
        body_center_node = atlas_target_node(layer, body_sx, body_sy)
    return align_town_emit_node(
        entity=entity,
        replacement_sid=replacement_sid,
        native_config=native_config,
        visit_node=visit_node,
        default_node=default_node,
        grid_width=atlas_width,
        grid_height=atlas_height,
        rotation=rotation,
        body_center_node=body_center_node,
    )
