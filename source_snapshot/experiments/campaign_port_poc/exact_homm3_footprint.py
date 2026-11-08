#!/usr/bin/env python3
"""HoMM3 traversal parity via scenery catalog match + functional mine clones/keep-donor + gap-fill.

Runtime-proven constraints:
- Resizing ObjectConfig (or 1x1 squad shrinks) breaks visuals/interaction.
- Rewriting functional `nodes` (GATE rings → sparse south-center GATE) breaks
  squads (`?`), structure approachability, and mirror-10 facing. Native
  ObjectConfig GATE/mirror layouts must be preserved.
- Scenery same-size clones that only clear extraneous OCC cells (keep sizeX/Z
  + prefab) are allowed only when the projected nodes fully occupy the donor
  size grid (no nodes==0 holes). Partial grids keep the donor mesh over H3-open
  cells and are forbidden (dirt_rock / pool sparsened clones).

Policy:
- Scenery: catalog SID with identical occupied footprint when one exists; else
  when the substituted donor OCC invents cells outside the H3 mask, prefer a
  1x1 rock catalog (rocks_1/rocks_2); refuse sparsened same-size clones (mesh
  overhang) and force a 1x1 primary (mountain_dirt_small_1 / rocks_*); same-size
  clone only when the H3 projection fills every cell of the donor size grid.
  Residual H3 blocked cells are gap-filled.
- Functional mines: clone the native mine ObjectConfig and mine-logic row on the
  donor size grid (never resize — that breaks the mine mesh); project H3 blocks
  onto that grid with a south-center GATE, sync generatorConfig so the 2x2
  building sits on that GATE like native mines, and gap-fill H3 blocks that do
  not fit. Preserve prefs / interaction fields; keep donor SID for property-family
  lookup via clone metadata.
- Other functional objects (incl. squads and towns): keep the donor SID and native
  nodes/prefs; GATE-align placement to the HoMM3 visit cell using the donor's native
  GATE; gap-fill uncovered H3 non-visit blocks.

MiniLM-free. Does not import surface_emit / approach_cell (callers pass helpers).
"""
from __future__ import annotations

import hashlib
import json
import zipfile
from dataclasses import dataclass
from typing import Any, Callable

import functional_emit_reservation as fer
import native_footprint_model as native_fp

SCHEMA = "homm3.olden_exact_footprint_overlay.v1"
CLONE_SID_PREFIX = "homm3_xfp_"
OVERLAY_OBJECT_MEMBER = "DB/map/objects/homecoming_exact_footprint_objects.json"
OVERLAY_MANIFEST_NAME = "homecoming_exact_footprint_overlay_manifest.json"
META_KEY = "homm3ExactFootprint"

# Never same-size clone these (special emit / infrastructure).
SKIP_CATEGORIES = frozenset({
    # hero_or_prison is NOT skipped: hero-spawner must keep_donor GATE-align to H3 visit.
    "campaign_briefing_script",
    "pathability_alignment_blocker",
    "emit_reservation_infrastructure",
    "block_parity_seal",
    "footprint_alignment_pad",
    "footprint_alignment_global_pad",
    "footprint_alignment_cluster",
    "boat_or_water_travel_object",
})

SKIP_SIDS = frozenset({
    "homm3_pathing_blocker",
    "homm3_envelope_padding_blocker",
    "homm3_boat",
    # Built-in spawn: native GATE-ring nodes are required for test/random_squad.
    # Placement uses GATE-on-visit emit in surface_emit (runtime stand follows emit).
    "random-squad",
})

# Land-on overlay SIDs are fine donors; logic aliases map to native logic rows.
LOGIC_DONOR_ALIASES: dict[str, str] = {
    "homm3_landon_castle_city": "homm3_castle_city",
    "homm3_landon_dungeon_city": "homm3_dungeon_city",
    "homm3_landon_barracks_castle_1": "barracks_homm3_castle_1",
    "homm3_landon_barracks_castle_2": "barracks_homm3_castle_2",
    "homm3_landon_barracks_castle_3": "barracks_homm3_castle_3",
    "homm3_landon_barracks_castle_4": "barracks_homm3_castle_4",
    "homm3_landon_barracks_castle_5": "barracks_homm3_castle_5",
    "homm3_landon_barracks_castle_6": "barracks_homm3_castle_6",
    "homm3_landon_barracks_castle_7": "barracks_homm3_castle_7",
    "homm3_landon_map_event_marker": "fx_quest_mark_gold_01",
}
# Mines have complete native ObjectConfigs and a separate object-logic catalog.
# They may be cloned so the interact GATE sits on the HoMM3 visit cell, but the
# ObjectConfig size must stay the donor size (resizing breaks the mine mesh) and
# generatorConfig must stay GATE-relative like the native 2x2 building rect.
MINE_SIDS = frozenset({
    "mine_crystals",
    "mine_gemstones",
    "mine_gold",
    "mine_mercury",
    "mine_ore",
    "mine_wood",
})
MINE_LOGIC_MEMBER = "DB/objects_logic/res_mines/mines.json"


def mine_generator_config_for_gate(
    donor_generator: dict[str, Any] | None,
    *,
    gate_x: int,
    gate_z: int,
) -> dict[str, Any]:
    """Place the native 2x2 mine mesh relative to the ObjectConfig GATE cell.

    Native mines use south-center GATE ``(1,2)`` on a 3x3 with
    ``buildingLeftBottom=(0,1)`` and ``buildingSize=2x2``. That is
    ``(gate_x - (sizeX-1), gate_z - (sizeZ-1))`` for the usual 2x2 body, i.e.
    ``(gate_x-1, gate_z-1)``. Clones that rewrite ``nodes`` must keep this
    GATE→mesh relationship or the building appears detached from the visit GATE.
    """
    if not isinstance(donor_generator, dict):
        raise ValueError("mine clone requires donor generatorConfig")
    size_x = int(donor_generator.get("buildingSizeX") or 0)
    size_z = int(donor_generator.get("buildingSizeZ") or 0)
    if size_x <= 0 or size_z <= 0:
        raise ValueError(
            f"mine generatorConfig missing buildingSize: {donor_generator!r}"
        )
    row = dict(donor_generator)
    row["buildingLeftBottomX"] = int(gate_x) - (size_x - 1)
    row["buildingLeftBottomZ"] = int(gate_z) - (size_z - 1)
    return row


@dataclass(frozen=True)
class SameSizeFootprint:
    size_x: int
    size_z: int
    nodes: tuple[int, ...]
    gate_config_x: int | None
    gate_config_z: int | None
    in_grid_block_count: int
    overflow_block_count: int
    kind: str

    @property
    def shape_key(self) -> str:
        return f"{self.size_x}x{self.size_z}:{','.join(str(n) for n in self.nodes)}"


def prefer_gate_local(size_x: int, size_z: int) -> tuple[int, int]:
    """South-edge center GATE — matches land-on approachability for 3x3."""
    if size_x <= 0 or size_z <= 0:
        raise ValueError(f"invalid donor size for GATE local: {size_x}x{size_z}")
    return size_x // 2, size_z - 1


def classify_object_config_shape(config: dict[str, Any], sid: str | None = None) -> str:
    """Classify ObjectConfig into geometric shape vocabulary (§2).

    Returns one of: landon | single_gate | gate_ring | solid | other.

    GATE cells (nodes==2) are interaction markers only; they do not occupy or
    claim map cells. gate_ring describes the node pattern only. Callers choose
    pickup versus permanent-building placement from config semantics because a
    native generator building can share the same ring geometry as a pickup.
    """
    resolved = sid if isinstance(sid, str) and sid else str(config.get("id") or "")
    if resolved.startswith("homm3_landon_"):
        return "landon"
    # Scorched-earth subterranean portal: OCC + multiple GATE markers. Still
    # GATE-align the preferred south-east marker to the H3 visit (not gate_ring
    # center-pivot, which would put visit on OCC).
    if resolved == "homm3_subterranean_gate_portal":
        return "single_gate"
    # Seer hut reuses wise_owl's 2x2 OCC+3 GATE donor mesh, but must GATE-align
    # like a single interact marker: otherwise BR placement leaves a GATE on
    # adjacent river waterMap while the H3 visit cell sits outside the donor body.
    if resolved == "homm3_seer_hut":
        return "single_gate"
    size = donor_size(config)
    nodes = config.get("nodes")
    if size is None or not isinstance(nodes, list) or len(nodes) != size[0] * size[1]:
        return "other"
    gate_count = sum(1 for value in nodes if int(value) == 2)
    occupied_count = sum(1 for value in nodes if int(value) == 1)
    # Resource/item/chest: 8 GATE markers + 1 center occupied. Squads: 8 markers + open center.
    if gate_count >= 4 and occupied_count <= 1:
        return "gate_ring"
    if gate_count == 1:
        return "single_gate"
    if gate_count == 0 and occupied_count > 0:
        return "solid"
    return "other"


def uses_native_building_anchor_policy(config: dict[str, Any]) -> bool:
    """Return whether node is a native structure anchor, not a pickup emit.

    Interactable generator objects can share a 3x3 one-OCC/eight-GATE shape
    with resource rings. Their map node is the native pivot/body anchor;
    resource/meta/army rows stay on the pickup/enemy placement path.
    """
    if not isinstance(config, dict):
        return False
    tag = config.get("tag")
    if tag in {"Resource", "Artifact", "meta", "Army"}:
        return False
    # Environment scenery is handled by the isolated compatibility pass.
    # Do not promote unresolved scenery defaults into the main emitter.
    return tag == "Interact" and isinstance(config.get("generatorConfig"), dict)


def footprint_from_donor_config(config: dict[str, Any]) -> SameSizeFootprint:
    """Native donor size/nodes with a preferred GATE for visit-aligned placement.

    GATE preference applies to landon / single_gate only (buildings/portals whose
    interact marker should sit on the H3 visit). GATE-ring donors keep gateConfig
    unset so callers pivot the center (occupied body or open squad center) onto
    the H3 visit — markers orbit and do not claim cells.
    """
    size = donor_size(config)
    if size is None:
        raise ValueError(f"donor config missing usable size for footprint: {config.get('id')!r}")
    size_x, size_z = size
    raw_nodes = config.get("nodes")
    if isinstance(raw_nodes, list) and len(raw_nodes) == size_x * size_z:
        nodes = tuple(int(n) for n in raw_nodes)
    else:
        nodes = tuple(0 for _ in range(size_x * size_z))
    resolved_sid = str(config.get("id") or "")
    shape = classify_object_config_shape(config, resolved_sid)
    gates = [(i % size_x, i // size_x) for i, value in enumerate(nodes) if value == 2]
    gate_x = gate_z = None
    if shape in {"single_gate", "landon"} and gates:
        preferred = prefer_gate_local(size_x, size_z)
        if preferred in gates:
            gate_x, gate_z = preferred
        elif len(gates) == 1:
            gate_x, gate_z = gates[0]
        else:
            gate_x, gate_z = max(gates, key=lambda cell: (cell[1], -abs(cell[0] - (size_x // 2))))
    return SameSizeFootprint(
        size_x=size_x,
        size_z=size_z,
        nodes=nodes,
        gate_config_x=gate_x,
        gate_config_z=gate_z,
        in_grid_block_count=sum(1 for value in nodes if value == 1),
        overflow_block_count=0,
        kind="functional",
    )


def same_size_nodes_from_h3(
    *,
    size_x: int,
    size_z: int,
    block_offsets: set[tuple[int, int]],
    visit_offsets: set[tuple[int, int]],
    kind: str,
) -> SameSizeFootprint:
    """Project H3 BR-relative masks onto a fixed donor size grid.

    Functional with a unique visit: GATE sits at south-center; H3 cells are
    projected relative to that visit. Scenery / no-visit: BR maps to the
    south-east corner of the donor grid (land-on BR convention).
    """
    if kind not in {"scenery", "functional"}:
        raise ValueError(f"unsupported same-size footprint kind: {kind!r}")
    if size_x <= 0 or size_z <= 0:
        raise ValueError(f"invalid donor size: {size_x}x{size_z}")

    visits = set(visit_offsets) if kind == "functional" else set()
    blocks = set(block_offsets)
    nodes = [0] * (size_x * size_z)
    overflow = 0
    in_grid_blocks = 0

    if kind == "functional" and len(visits) == 1:
        visit_dx, visit_dy = next(iter(visits))
        gate_x, gate_z = prefer_gate_local(size_x, size_z)
        nodes[gate_z * size_x + gate_x] = 2
        for dx, dy in blocks:
            if (dx, dy) in visits:
                continue
            cx = gate_x + (dx - visit_dx)
            cz = gate_z + (dy - visit_dy)
            if 0 <= cx < size_x and 0 <= cz < size_z:
                idx = cz * size_x + cx
                if nodes[idx] != 2:
                    nodes[idx] = 1
                    in_grid_blocks += 1
            else:
                overflow += 1
        return SameSizeFootprint(
            size_x=size_x,
            size_z=size_z,
            nodes=tuple(nodes),
            gate_config_x=gate_x,
            gate_config_z=gate_z,
            in_grid_block_count=in_grid_blocks,
            overflow_block_count=overflow,
            kind=kind,
        )

    # Scenery or functional without a unique visit: BR at SE of donor grid.
    br_x, br_z = size_x - 1, size_z - 1
    for dx, dy in blocks:
        cx = br_x + dx
        cz = br_z + dy
        if 0 <= cx < size_x and 0 <= cz < size_z:
            nodes[cz * size_x + cx] = 1
            in_grid_blocks += 1
        else:
            overflow += 1
    # Multi-visit functional without unique visit: mark all in-grid visits as GATE.
    gate_x = gate_z = None
    if kind == "functional" and visits:
        for dx, dy in visits:
            cx = br_x + dx
            cz = br_z + dy
            if 0 <= cx < size_x and 0 <= cz < size_z:
                nodes[cz * size_x + cx] = 2
                gate_x, gate_z = cx, cz
    return SameSizeFootprint(
        size_x=size_x,
        size_z=size_z,
        nodes=tuple(nodes),
        gate_config_x=gate_x,
        gate_config_z=gate_z,
        in_grid_block_count=in_grid_blocks,
        overflow_block_count=overflow,
        kind=kind,
    )


def functional_clone_grid_size(
    donor_size_value: tuple[int, int],
    *,
    block_offsets: set[tuple[int, int]],
    visit_offsets: set[tuple[int, int]],
) -> tuple[int, int]:
    """Choose the smallest donor-sized-or-larger grid that fits an H3 mask."""
    if len(visit_offsets) != 1:
        raise ValueError(
            f"functional exact footprint requires one visit cell; got {sorted(visit_offsets)}"
        )
    visit_dx, visit_dy = next(iter(visit_offsets))
    size_x, size_z = donor_size_value
    relative_cells = {
        (dx - visit_dx, dy - visit_dy)
        for dx, dy in (set(block_offsets) | set(visit_offsets))
    }
    for _ in range(64):
        gate_x, gate_z = prefer_gate_local(size_x, size_z)
        if all(
            0 <= gate_x + dx < size_x and 0 <= gate_z + dy < size_z
            for dx, dy in relative_cells
        ):
            return size_x, size_z
        if any(not (0 <= gate_x + dx < size_x) for dx, _dy in relative_cells):
            size_x += 1
        if any(not (0 <= gate_z + dy < size_z) for _dx, dy in relative_cells):
            size_z += 1
    raise ValueError(
        f"functional exact footprint grid did not converge: donor={donor_size_value} "
        f"blocks={sorted(block_offsets)} visits={sorted(visit_offsets)}"
    )


def clone_sid_for(donor_sid: str, footprint: SameSizeFootprint) -> str:
    digest = hashlib.sha1(
        f"samesize|{footprint.kind}|{donor_sid}|{footprint.shape_key}".encode("utf-8")
    ).hexdigest()[:12]
    return f"{CLONE_SID_PREFIX}{footprint.kind[0]}_{digest}"


def apply_same_size_clone(
    donor_row: dict[str, Any],
    *,
    donor_sid: str,
    clone_sid: str,
    footprint: SameSizeFootprint,
    allow_size_change: bool = False,
) -> dict[str, Any]:
    if donor_row.get("id") != donor_sid:
        raise ValueError(
            f"same-size clone donor id mismatch for {clone_sid}: "
            f"expected {donor_sid!r}, found {donor_row.get('id')!r}"
        )
    size_x = donor_row.get("sizeX")
    size_z = donor_row.get("sizeZ")
    if (
        not allow_size_change
        and (size_x != footprint.size_x or size_z != footprint.size_z)
    ):
        raise ValueError(
            f"same-size clone must preserve donor size for {clone_sid}: "
            f"donor={size_x}x{size_z} footprint={footprint.size_x}x{footprint.size_z}"
        )
    if allow_size_change:
        raise ValueError(
            f"size-changing exact footprint clones are forbidden (breaks visuals): {clone_sid}"
        )
    row = json.loads(json.dumps(donor_row, ensure_ascii=False))
    row["id"] = clone_sid
    if (
        footprint.kind == "scenery"
        and any(int(n) == 0 for n in footprint.nodes)
        and any(int(n) == 1 for n in footprint.nodes)
    ):
        raise ValueError(
            f"same-size scenery clone forbidden for mesh overhang: {clone_sid} "
            f"donor={donor_sid} shape={footprint.shape_key} "
            f"(open cells inside donor size keep the donor mesh over H3-open tiles)"
        )
    row["nodes"] = list(footprint.nodes)
    row["canBeMirrored"] = False
    if (
        donor_sid in MINE_SIDS
        and footprint.kind == "functional"
        and footprint.gate_config_x is not None
        and footprint.gate_config_z is not None
    ):
        row["generatorConfig"] = mine_generator_config_for_gate(
            donor_row.get("generatorConfig")
            if isinstance(donor_row.get("generatorConfig"), dict)
            else None,
            gate_x=footprint.gate_config_x,
            gate_z=footprint.gate_config_z,
        )
    # Do not invent gateInsideObject. Preserve donor flag; GATE markers are not
    # occupancy and Resource-style rings must not become "visit inside object".
    row[META_KEY] = {
        "schema": "homm3.exact_footprint_meta.v1",
        "mode": "same_size_nodes_plus_overflow_blockers",
        "kind": footprint.kind,
        "donorSid": donor_sid,
        "gateConfig": (
            [footprint.gate_config_x, footprint.gate_config_z]
            if footprint.gate_config_x is not None and footprint.gate_config_z is not None
            else None
        ),
        "inGridBlockCount": footprint.in_grid_block_count,
        "overflowBlockCount": footprint.overflow_block_count,
        "shapeKey": footprint.shape_key,
    }
    return row


def is_exact_footprint_sid(sid: str) -> bool:
    return isinstance(sid, str) and sid.startswith(CLONE_SID_PREFIX)


def is_scenery_exact_footprint_clone_sid(sid: str) -> bool:
    """True for scenery same-size clones (`homm3_xfp_s_*`); functional clones use `_f_`."""
    return isinstance(sid, str) and sid.startswith(f"{CLONE_SID_PREFIX}s_")


def footprint_spec_from_config(config: dict[str, Any]) -> SameSizeFootprint | None:
    meta = config.get(META_KEY)
    if not isinstance(meta, dict):
        return None
    mode = meta.get("mode")
    if mode not in {
        None,
        "same_size_nodes_plus_overflow_blockers",
    }:
        return None
    nodes = config.get("nodes")
    size_x = config.get("sizeX")
    size_z = config.get("sizeZ")
    if not isinstance(size_x, int) or not isinstance(size_z, int) or not isinstance(nodes, list):
        return None
    gate = meta.get("gateConfig")
    gate_x = gate_z = None
    if isinstance(gate, list) and len(gate) == 2:
        gate_x, gate_z = int(gate[0]), int(gate[1])
    elif 2 in nodes:
        idx = nodes.index(2)
        gate_x, gate_z = idx % size_x, idx // size_x
    return SameSizeFootprint(
        size_x=size_x,
        size_z=size_z,
        nodes=tuple(int(n) for n in nodes),
        gate_config_x=gate_x,
        gate_config_z=gate_z,
        in_grid_block_count=int(meta.get("inGridBlockCount") or sum(1 for n in nodes if n == 1)),
        overflow_block_count=int(meta.get("overflowBlockCount") or 0),
        kind=str(meta.get("kind") or "functional"),
    )


def is_scenery_entity(entity: dict[str, Any], donor_sid: str) -> bool:
    return (
        entity.get("category") == "payloadless_object_unclassified_for_current_scope"
        and donor_sid in fer.SUPPRESSIBLE_SOURCE_SCENERY_SIDS
    )


def should_skip_entity(entity: dict[str, Any], donor_sid: str) -> bool:
    if fer.is_infrastructure_sid(donor_sid) or donor_sid in SKIP_SIDS:
        return True
    if is_exact_footprint_sid(donor_sid):
        return True
    category = str(entity.get("category") or "")
    if category in SKIP_CATEGORIES:
        return True
    return False


def donor_size(config: dict[str, Any]) -> tuple[int, int] | None:
    size_x = config.get("sizeX")
    size_z = config.get("sizeZ")
    if isinstance(size_x, int) and isinstance(size_z, int) and size_x > 0 and size_z > 0:
        nodes = config.get("nodes")
        if nodes is not None and (not isinstance(nodes, list) or len(nodes) != size_x * size_z):
            return None
        return size_x, size_z
    return None


def occupied_br_offsets_from_config(config: dict[str, Any]) -> frozenset[tuple[int, int]]:
    size = donor_size(config)
    nodes = config.get("nodes")
    if size is None or not isinstance(nodes, list):
        return frozenset()
    size_x, size_z = size
    br_cx, br_cz = size_x - 1, size_z - 1
    out: set[tuple[int, int]] = set()
    for cz in range(size_z):
        for cx in range(size_x):
            if nodes[cz * size_x + cx] != 1:
                continue
            out.add((cx - br_cx, cz - br_cz))
    return frozenset(out)


def scenery_family_prefix(sid: str | None) -> str | None:
    """Coarse family used to keep catalog remaps inside the same blocking scenery line."""
    if not isinstance(sid, str) or not sid:
        return None
    lower = sid.lower()
    for prefix in (
        "mountain_snow",
        "mountain_dead",
        "mountain_dirt",
        "mountain_desert",
        "mountain_lava",
        "mountain_water",
        "mountain_green",
        "pinetree_snow",
        "tree_dead",
        "tree_dirt",
        "tree_lava",
        "tree_autumn",
        "pinetree",
        "pool_snow",
        "pool_dead",
        "pool_dirt",
        "pool_desert",
        "pool_lava",
        "pool",
        # Plate/rock lines must not collapse into bare "dirt"/"snow"/"lava" and
        # remap onto flowers/stones with coincidentally matching OCC.
        "dirt_rock",
        "dirt_volcanic_rock",
        "dirt_stones",
        "dirt_strange_flower",
        "desert_dune",
        "desert_cracked_stones",
        "lava_ground",
        "lava_stones",
        "snow_grassy_hill",
        "snow_rock_hill",
        "snow_stones",
        "dead_sculls_bones_hill",
        "crystal_trail",
        "rocks",
    ):
        if lower.startswith(prefix):
            return prefix
    return lower.split("_", 1)[0] if "_" in lower else lower


# 1-cell rock donors used when dirt/volcanic rock substitutions are OE-larger
# or when a same-size clone would leave mesh-overhang holes in the donor grid.
ONE_CELL_ROCK_DONORS = ("rocks_1", "rocks_2")
ROCK_LIKE_DONOR_PREFIXES = (
    "dirt_rock",
    "rocks_",
    "dirt_volcanic_rock",
    "snow_rock_hill",
)
POOL_LIKE_DONOR_PREFIXES = (
    "pool_",
    "pool",
)


def is_mountain_tree_scenery_sid(sid: str) -> bool:
    lower = sid.lower()
    return lower.startswith(("mountain_", "tree_", "pinetree"))


def is_rock_like_scenery_sid(sid: str) -> bool:
    lower = sid.lower()
    return any(lower.startswith(prefix) for prefix in ROCK_LIKE_DONOR_PREFIXES)


def is_pool_like_scenery_sid(sid: str) -> bool:
    lower = sid.lower()
    if lower in {"pool", "pool_small", "pool_big"}:
        return True
    return any(lower.startswith(prefix) for prefix in POOL_LIKE_DONOR_PREFIXES)


def scenery_clone_has_mesh_overhang(footprint: SameSizeFootprint) -> bool:
    """True when donor size grid mixes occupied and open cells.

    Same-size clones keep the donor prefab/mesh. Open nodes inside that size are
    still covered by the mesh, so pathing/visuals invent blocks on H3-open cells
    (2-tile H3 rock → dirt_rock_1 2x2 mesh). Forbidden for scenery.
    """
    has_open = any(int(value) == 0 for value in footprint.nodes)
    has_occupied = any(int(value) == 1 for value in footprint.nodes)
    return has_open and has_occupied


def find_catalog_scenery_match(
    *,
    block_offsets: set[tuple[int, int]],
    configs: dict[str, dict[str, Any]],
    preferred_donor: str,
) -> str | None:
    target = frozenset(block_offsets)
    preferred_family = scenery_family_prefix(preferred_donor)
    candidates = sorted(fer.SUPPRESSIBLE_SOURCE_SCENERY_SIDS & set(configs))
    if preferred_donor in candidates:
        candidates.remove(preferred_donor)
        candidates.insert(0, preferred_donor)
    # Same-family only: do not remap mountain_snow_* onto mountain_green_* just because
    # the occupied mask matches — that erases DEF families into wrong biomes / holes.
    matches = [
        sid
        for sid in candidates
        if occupied_br_offsets_from_config(configs[sid]) == target
        and (preferred_family is None or scenery_family_prefix(sid) == preferred_family)
    ]
    if not matches:
        return None
    if preferred_donor in matches:
        return preferred_donor
    return matches[0]


def find_rock_1x1_primary_catalog_match(
    *,
    block_offsets: set[tuple[int, int]],
    configs: dict[str, dict[str, Any]],
    preferred_donor: str,
) -> str | None:
    """Prefer rocks_1/rocks_2 when an oversized rock donor would mesh-overhang.

    Primary plant is always 1x1; residual H3 block cells are sealed by gap-fill
    (same pattern as mountain/tree 1x1 sizing).
    """
    if not block_offsets or not is_rock_like_scenery_sid(preferred_donor):
        return None
    for sid in ONE_CELL_ROCK_DONORS:
        config = configs.get(sid)
        if config is None:
            continue
        occupied = occupied_br_offsets_from_config(config)
        if len(occupied) == 1:
            return sid
    return None


# Back-compat alias for callers/tests that used the 1-cell-only name.
find_one_cell_rock_catalog_match = find_rock_1x1_primary_catalog_match


def donor_invents_blocks_outside_h3(
    *,
    donor_config: dict[str, Any],
    block_offsets: set[tuple[int, int]],
) -> bool:
    """True when Core donor OCC cells are not a subset of the H3 block mask."""
    donor_offsets = occupied_br_offsets_from_config(donor_config)
    return bool(donor_offsets - frozenset(block_offsets))


@dataclass
class ExactFootprintEntry:
    source_key: str
    source_index: int
    donor_sid: str
    result_sid: str
    kind: str
    action: str  # catalog_match | same_size_clone | keep_donor
    footprint: SameSizeFootprint | None


@dataclass
class ExactFootprintRegistry:
    by_source_index: dict[int, ExactFootprintEntry]
    clone_rows: dict[str, dict[str, Any]]
    logic_clones: list[dict[str, Any]]
    stats: dict[str, Any]


def build_exact_footprint_registry(
    entities: list[dict[str, Any]],
    *,
    resolve_donor: Callable[[dict[str, Any]], str | None],
    block_offsets_for: Callable[[dict[str, Any]], set[tuple[int, int]]],
    visit_offsets_for: Callable[[dict[str, Any]], set[tuple[int, int]]],
    configs: dict[str, dict[str, Any]],
    core_zip_path: str | Any,
    in_source_bounds: Callable[[dict[str, Any]], bool],
) -> ExactFootprintRegistry:
    by_source_index: dict[int, ExactFootprintEntry] = {}
    clone_rows: dict[str, dict[str, Any]] = {}
    logic_clones: list[dict[str, Any]] = []
    stats = {
        "sceneryCatalogMatch": 0,
        "sceneryNoCatalogSolidSquare": 0,
        "sceneryClone": 0,
        "functionalSameSizeClone": 0,
        "functionalMineClone": 0,
        "functionalKeepDonor": 0,
        "functionalSkippedNoSize": 0,
        "skipped": 0,
        "uniqueCloneSids": 0,
    }
    logic_index: dict[str, tuple[str, dict[str, Any]]] | None = None
    logic_clone_sids: set[str] = set()


    for entity in entities:
        if not in_source_bounds(entity):
            continue
        source_index = entity.get("sourceIndex")
        if not isinstance(source_index, int):
            raise ValueError(f"entity missing sourceIndex for exact footprint: {entity.get('sourceKey')}")
        donor_sid = resolve_donor(entity)
        if donor_sid is None:
            continue
        if should_skip_entity(entity, donor_sid):
            stats["skipped"] += 1
            continue
        if donor_sid not in configs:
            raise ValueError(
                f"exact footprint missing donor config for {entity.get('sourceKey')}: {donor_sid}"
            )
        scenery = is_scenery_entity(entity, donor_sid)

        if scenery:
            blocks = set(block_offsets_for(entity))
            catalog = find_catalog_scenery_match(
                block_offsets=blocks,
                configs=configs,
                preferred_donor=donor_sid,
            )
            if catalog is not None:
                # Multi-tile mountain meshes overhang ObjectConfig OCC onto H3-open
                # neighbors — refuse catalog and fall through to 1x1 sizing.
                catalog_fp = footprint_from_donor_config(configs[catalog])
                catalog_occ = (
                    sum(1 for value in catalog_fp.nodes if int(value) == 1)
                    if catalog_fp is not None
                    else 0
                )
                if catalog_occ > 1 and str(catalog).startswith("mountain_"):
                    catalog = None
            if catalog is not None:
                by_source_index[source_index] = ExactFootprintEntry(
                    source_key=str(entity.get("sourceKey") or ""),
                    source_index=source_index,
                    donor_sid=donor_sid,
                    result_sid=catalog,
                    kind="scenery",
                    action="catalog_match",
                    footprint=None,
                )
                stats["sceneryCatalogMatch"] += 1
                continue

            # Mountains/trees keep the solid-square / forced-1x1 path — multi-tile
            # meshes overhang OCC even when nodes are sparsened.
            if is_mountain_tree_scenery_sid(donor_sid):
                stats["sceneryNoCatalogSolidSquare"] += 1
                continue

            donor_config = configs[donor_sid]
            if not donor_invents_blocks_outside_h3(
                donor_config=donor_config, block_offsets=blocks
            ):
                # Donor OCC ⊆ H3 mask: keep donor + gap-fill residual (solid-square
                # may still size pools when a full square fits).
                stats["sceneryNoCatalogSolidSquare"] += 1
                continue

            # OE-larger donor: prefer a 1x1 rock primary (any H3 block count), else
            # same-size clone only when H3 fills the entire donor grid. Never keep
            # the oversized donor and never sparsify a mesh over open cells.
            smaller = find_rock_1x1_primary_catalog_match(
                block_offsets=blocks,
                configs=configs,
                preferred_donor=donor_sid,
            )
            if smaller is not None:
                by_source_index[source_index] = ExactFootprintEntry(
                    source_key=str(entity.get("sourceKey") or ""),
                    source_index=source_index,
                    donor_sid=donor_sid,
                    result_sid=smaller,
                    kind="scenery",
                    action="catalog_match",
                    footprint=None,
                )
                stats["sceneryCatalogMatch"] += 1
                continue

            size = donor_size(donor_config)
            if size is None:
                raise ValueError(
                    f"exact footprint OE-larger scenery missing donor size for "
                    f"{entity.get('sourceKey')}: {donor_sid}"
                )
            size_x, size_z = size
            footprint = same_size_nodes_from_h3(
                size_x=size_x,
                size_z=size_z,
                block_offsets=blocks,
                visit_offsets=set(),
                kind="scenery",
            )
            clone_occ = sum(1 for value in footprint.nodes if int(value) == 1)
            if clone_occ > len(blocks):
                raise ValueError(
                    f"exact footprint scenery clone OCC {clone_occ} exceeds H3 "
                    f"block count {len(blocks)} for {entity.get('sourceKey')} "
                    f"donor={donor_sid}"
                )
            if scenery_clone_has_mesh_overhang(footprint):
                # Sparsened same-size clones keep the donor mesh over H3-open cells
                # (dirt_rock / pool / snow_grassy_hill / dune). Never emit those
                # clones; plant a true 1x1 primary and seal residuals via gap-fill.
                # Pathable H3 (0 blocks) must not invent OCC via a 1x1 primary.
                if not blocks:
                    stats["sceneryNoCatalogSolidSquare"] += 1
                    continue
                one_by_one = None
                for sid in ("mountain_dirt_small_1", "rocks_1", "rocks_2"):
                    config = configs.get(sid)
                    if config is None:
                        continue
                    if len(occupied_br_offsets_from_config(config)) == 1:
                        one_by_one = sid
                        break
                if one_by_one is None:
                    raise ValueError(
                        f"exact footprint scenery mesh overhang for "
                        f"{entity.get('sourceKey')} donor={donor_sid}: no 1x1 "
                        f"primary (mountain_dirt_small_1/rocks_1/rocks_2) in catalog"
                    )
                by_source_index[source_index] = ExactFootprintEntry(
                    source_key=str(entity.get("sourceKey") or ""),
                    source_index=source_index,
                    donor_sid=donor_sid,
                    result_sid=one_by_one,
                    kind="scenery",
                    action="catalog_match",
                    footprint=None,
                )
                stats["sceneryCatalogMatch"] += 1
                continue
            if blocks and footprint.in_grid_block_count == 0:
                raise ValueError(
                    f"exact footprint cannot project H3 blocks onto donor grid for "
                    f"{entity.get('sourceKey')} donor={donor_sid} "
                    f"size={size_x}x{size_z} blocks={sorted(blocks)} "
                    f"overflow={footprint.overflow_block_count}"
                )
            # Pathable H3 (0 blocks) → zero-OCC same-size clone (crystal_trail /
            # hole→pool). Non-empty H3 that partially overflows is OK only when
            # every in-grid cell is occupied (no mesh overhang holes).
            clone_sid = clone_sid_for(donor_sid, footprint)
            if clone_sid not in clone_rows:
                clone_rows[clone_sid] = apply_same_size_clone(
                    donor_config,
                    donor_sid=donor_sid,
                    clone_sid=clone_sid,
                    footprint=footprint,
                )
            by_source_index[source_index] = ExactFootprintEntry(
                source_key=str(entity.get("sourceKey") or ""),
                source_index=source_index,
                donor_sid=donor_sid,
                result_sid=clone_sid,
                kind="scenery",
                action="same_size_clone",
                footprint=footprint,
            )
            stats["sceneryClone"] += 1
            continue

        size = donor_size(configs[donor_sid])
        if size is None:
            stats["functionalSkippedNoSize"] += 1
            continue
        if donor_sid in MINE_SIDS:
            blocks = set(block_offsets_for(entity))
            visits = set(visit_offsets_for(entity))
            if len(visits) != 1:
                raise ValueError(
                    f"exact footprint mine requires exactly one HoMM3 visit cell for "
                    f"{entity.get('sourceKey')}: visits={sorted(visits)}"
                )
            # Never grow the ObjectConfig: resizing detaches the mine mesh from GATE.
            # H3 blocks that do not fit the donor grid are sealed by gap-fill.
            size_x, size_z = size
            footprint = same_size_nodes_from_h3(
                size_x=size_x,
                size_z=size_z,
                block_offsets=blocks,
                visit_offsets=visits,
                kind="functional",
            )
            expected_blocks = blocks - visits
            fitted = len(expected_blocks) - footprint.overflow_block_count
            if footprint.in_grid_block_count != fitted:
                raise ValueError(
                    f"exact footprint mine cannot represent the HoMM3 mask for "
                    f"{entity.get('sourceKey')}: donor={donor_sid} "
                    f"size={size_x}x{size_z} blocks={sorted(blocks)} visits={sorted(visits)} "
                    f"inGrid={footprint.in_grid_block_count} fitted={fitted} "
                    f"overflow={footprint.overflow_block_count}"
                )
            clone_sid = clone_sid_for(donor_sid, footprint)
            if clone_sid not in clone_rows:
                clone_rows[clone_sid] = apply_same_size_clone(
                    configs[donor_sid],
                    donor_sid=donor_sid,
                    clone_sid=clone_sid,
                    footprint=footprint,
                )
            if logic_index is None:
                logic_index = _load_logic_index(core_zip_path)
            _maybe_queue_logic_clone(
                donor_sid=donor_sid,
                clone_sid=clone_sid,
                logic_index=logic_index,
                logic_clones=logic_clones,
                logic_clone_sids=logic_clone_sids,
            )
            by_source_index[source_index] = ExactFootprintEntry(
                source_key=str(entity.get("sourceKey") or ""),
                source_index=source_index,
                donor_sid=donor_sid,
                result_sid=clone_sid,
                kind="functional",
                action="same_size_clone",
                footprint=footprint,
            )
            stats["functionalSameSizeClone"] += 1
            stats["functionalMineClone"] += 1
            continue


        # Never rewrite functional ObjectConfig nodes. Keep native Resource/item/chest
        # donors as-is. Placement plants node on a GATE at the H3 visit (native map
        # pattern). propResParams use value=0. Do not clone to GATE-only 1x1.
        footprint = footprint_from_donor_config(configs[donor_sid])
        by_source_index[source_index] = ExactFootprintEntry(
            source_key=str(entity.get("sourceKey") or ""),
            source_index=source_index,
            donor_sid=donor_sid,
            result_sid=donor_sid,
            kind="functional",
            action="keep_donor",
            footprint=footprint,
        )
        stats["functionalKeepDonor"] += 1

    stats["uniqueCloneSids"] = len(clone_rows)
    stats["uniqueLogicClones"] = len(logic_clones)
    # Compat aliases for older validator/manifest readers.
    stats["functionalClone"] = stats["functionalSameSizeClone"]
    return ExactFootprintRegistry(
        by_source_index=by_source_index,
        clone_rows=clone_rows,
        logic_clones=logic_clones,
        stats=stats,
    )


def _load_logic_index(core_zip_path: str | Any) -> dict[str, tuple[str, dict[str, Any]]]:
    index: dict[str, tuple[str, dict[str, Any]]] = {}
    with zipfile.ZipFile(core_zip_path) as core:
        for name in core.namelist():
            if not (name.startswith("DB/objects_logic/") and name.endswith(".json")):
                continue
            doc = json.loads(core.read(name).decode("utf-8-sig"))
            rows = doc.get("array") if isinstance(doc, dict) else None
            if not isinstance(rows, list):
                continue
            for row in rows:
                if isinstance(row, dict) and isinstance(row.get("id"), str):
                    index.setdefault(row["id"], (name, row))
    return index


# Resource / camp logic is keyed for native SIDs (resource_gold, camp_fire_1, …).
# Cloning those rows under homm3_xfp_* ids without matching ObjectConfig makes
# Session.Loader resolve Meta map objects that do not exist → ArgumentNullException
# and an infinite Loader retry (observed on Steadwick's Liberation).
_FORBIDDEN_LOGIC_CLONE_MEMBERS = frozenset(
    {
        # Meta catalogs: Loader resolves these logic ids as map-object SIDs.
        "DB/objects_logic/res/resources.json",
        "DB/objects_logic/res/resources_camps.json",
        "DB/objects_logic/chests/chests.json",
        "DB/objects_logic/chests/camp_fire.json",
        "DB/objects_logic/chests/scroll_box.json",
        "DB/objects_logic/chests/enchanted_scroll_box.json",
        "DB/objects_logic/chests/mythic_scroll_box.json",
        "DB/objects_logic/chests/pandora_box.json",
    }
)


def _maybe_queue_logic_clone(
    *,
    donor_sid: str,
    clone_sid: str,
    logic_index: dict[str, tuple[str, dict[str, Any]]],
    logic_clones: list[dict[str, Any]],
    logic_clone_sids: set[str],
) -> None:
    if clone_sid in logic_clone_sids:
        return
    logic_sid = LOGIC_DONOR_ALIASES.get(donor_sid, donor_sid)
    hit = logic_index.get(logic_sid)
    if hit is None:
        if donor_sid in MINE_SIDS:
            raise ValueError(
                f"mine exact footprint requires logic row for {donor_sid!r} "
                f"in {MINE_LOGIC_MEMBER}"
            )
        return
    member, donor_row = hit
    if donor_sid in MINE_SIDS and member != MINE_LOGIC_MEMBER:
        raise ValueError(
            f"mine exact footprint logic drift for {donor_sid!r}: "
            f"expected {MINE_LOGIC_MEMBER}, found {member}"
        )
    if member in _FORBIDDEN_LOGIC_CLONE_MEMBERS:
        raise ValueError(
            f"exact footprint must not clone resource/camp logic for {clone_sid!r} "
            f"(donor={logic_sid!r} member={member}); orphan logic ids hang Session.Loader "
            f"via Meta map object lookup. Keep native resource_* / camp_fire donors."
        )
    clone_row = json.loads(json.dumps(donor_row, ensure_ascii=False))
    clone_row["id"] = clone_sid
    logic_clones.append({
        "member": member,
        "donorSid": logic_sid,
        "cloneSid": clone_sid,
        "row": clone_row,
    })
    logic_clone_sids.add(clone_sid)


def inject_registry_into_configs(
    configs: dict[str, dict[str, Any]],
    valid_ids: set[str],
    registry: ExactFootprintRegistry,
) -> None:
    for sid, row in registry.clone_rows.items():
        configs[sid] = row
        valid_ids.add(sid)


def ensure_scenery_catalog_configs(
    configs: dict[str, dict[str, Any]],
    *,
    core_zip_path: str | Any,
) -> None:
    missing = sorted(fer.SUPPRESSIBLE_SOURCE_SCENERY_SIDS - set(configs))
    if not missing:
        return
    want = set(missing)
    with zipfile.ZipFile(core_zip_path) as core:
        for name in core.namelist():
            if not want:
                break
            if not (name.startswith("DB/map/objects/") and name.endswith(".json")):
                continue
            doc = json.loads(core.read(name).decode("utf-8-sig"))
            rows = doc.get("array") if isinstance(doc, dict) else None
            if not isinstance(rows, list):
                continue
            for row in rows:
                if isinstance(row, dict) and row.get("id") in want:
                    configs[row["id"]] = row
                    want.discard(row["id"])
    still_missing = sorted(want)
    if still_missing:
        raise ValueError(
            "exact footprint scenery catalog missing Core ObjectConfig rows: "
            + ", ".join(still_missing[:20])
        )


def remap_replacement_sid(
    entity: dict[str, Any],
    donor_sid: str,
    registry: ExactFootprintRegistry | None,
) -> tuple[str, str | None]:
    if registry is None:
        return donor_sid, None
    source_index = entity.get("sourceIndex")
    if not isinstance(source_index, int):
        return donor_sid, None
    entry = registry.by_source_index.get(source_index)
    if entry is None:
        return donor_sid, None
    if entry.donor_sid != donor_sid:
        raise ValueError(
            f"exact footprint donor drift for {entity.get('sourceKey')}: "
            f"resolve={donor_sid!r} registry_donor={entry.donor_sid!r}"
        )
    if entry.action == "catalog_match":
        return entry.result_sid, "exact_homm3_footprint_scenery_catalog"
    if entry.action == "same_size_clone":
        return entry.result_sid, "exact_homm3_traversal_same_size_clone"
    if entry.action == "clone":
        # Legacy action name — treat as same-size.
        return entry.result_sid, "exact_homm3_traversal_same_size_clone"
    return donor_sid, "exact_homm3_footprint_keep_donor"


def anchor_for_config_local_cell(
    native_config: dict[str, Any],
    *,
    local_x: int,
    local_z: int,
    target_node: int,
    size_x: int,
    size_z: int,
    grid_width: int,
    grid_height: int,
    rotation: int = 0,
    can_be_mirrored: bool = False,
) -> tuple[int, str]:
    """Map node that puts ObjectConfig ``nodes`` cell (local_x, local_z) on ``target_node``.

    Objects the emitter models natively (``uses_native_building_anchor_policy``: occupancy
    and GATE come from the native pivot projection) are anchored by the inverse of that
    same projection, so the anchor and the occupancy agree. Everything else keeps the
    size-grid convention its occupancy uses. Returns (node, projection name).
    """
    if uses_native_building_anchor_policy(native_config):
        node = native_fp.native_anchor_for_local_cell(
            native_config,
            local_x=local_x,
            local_z=local_z,
            target_node=target_node,
            rotation=rotation,
            width=grid_width,
            height=grid_height,
        )
        return node, "native_pivot_projection"
    target_x = target_node % grid_width
    target_y = target_node // grid_width
    mirrored = rotation == 10 and can_be_mirrored
    placed_dx = size_x - 1 - local_x if mirrored else local_x
    anchor_x = target_x - placed_dx
    anchor_y = target_y - (size_z - 1 - local_z)
    if not (0 <= anchor_x < grid_width and 0 <= anchor_y < grid_height):
        raise ValueError(
            f"size-grid anchor out of bounds: ({anchor_x},{anchor_y}) target={target_node} "
            f"local=({local_x},{local_z}) size={size_x}x{size_z} rotation={rotation} mirrored={mirrored}"
        )
    return anchor_y * grid_width + anchor_x, "legacy_size_grid"


def project_config_local_cell(
    native_config: dict[str, Any],
    *,
    anchor_node: int,
    local_x: int,
    local_z: int,
    size_x: int,
    size_z: int,
    grid_width: int,
    grid_height: int,
    rotation: int = 0,
    can_be_mirrored: bool = False,
) -> int | None:
    """Forward projection matching ``anchor_for_config_local_cell`` (None when off-map)."""
    if uses_native_building_anchor_policy(native_config):
        model = native_fp.model_native_footprint(
            str(native_config.get("id") or ""), native_config, anchor_node, rotation,
            width=grid_width, height=grid_height,
        )
        failures = native_fp.native_cell_projection_failure_reasons(model)
        if failures:
            raise ValueError(f"cannot project native cells for {native_config.get('id')}: unresolved {', '.join(failures)}")
        return native_fp._native_cell(
            anchor_node,
            local_x,
            local_z,
            size_x=model.size_x or 0,
            pivot_x=model.transform.pivot_x,
            pivot_z=model.transform.pivot_z,
            flipped_offset=native_config.get("flippedOffset") if type(native_config.get("flippedOffset")) is int else 0,
            orientation=model.native_orientation,
            width=grid_width,
            height=grid_height,
        )
    mirrored = rotation == 10 and can_be_mirrored
    x = anchor_node % grid_width + (size_x - 1 - local_x if mirrored else local_x)
    y = anchor_node // grid_width + (size_z - 1 - local_z)
    if not (0 <= x < grid_width and 0 <= y < grid_height):
        return None
    return y * grid_width + x


def derive_gate_aligned_node(
    *,
    visit_node: int,
    footprint: SameSizeFootprint,
    native_config: dict[str, Any],
    grid_width: int,
    grid_height: int,
    default_node: int,
    rotation: int = 0,
    can_be_mirrored: bool = False,
) -> tuple[int, dict[str, Any]]:
    if footprint.gate_config_x is None or footprint.gate_config_z is None:
        raise ValueError("GATE-aligned placement requires gateConfig on same-size footprint")
    gate_x = footprint.gate_config_x
    gate_z = footprint.gate_config_z
    mirrored = rotation == 10 and can_be_mirrored
    try:
        node, projection = anchor_for_config_local_cell(
            native_config,
            local_x=gate_x,
            local_z=gate_z,
            target_node=visit_node,
            size_x=footprint.size_x,
            size_z=footprint.size_z,
            grid_width=grid_width,
            grid_height=grid_height,
            rotation=rotation,
            can_be_mirrored=can_be_mirrored,
        )
    except ValueError as exc:
        raise ValueError(
            f"same-size GATE-aligned anchor failed: visit={visit_node} gate=({gate_x},{gate_z}) "
            f"size={footprint.size_x}x{footprint.size_z} rotation={rotation} mirrored={mirrored}: {exc}"
        ) from exc
    if projection == "native_pivot_projection":
        model = native_fp.model_native_footprint(
            str(native_config.get("id") or ""), native_config, node, rotation,
            width=grid_width, height=grid_height,
        )
        if visit_node not in model.gate_cells:
            raise ValueError(
                f"native GATE alignment failed for {native_config.get('id')}: visit={visit_node} "
                f"not in native gate cells {sorted(model.gate_cells)} (anchor={node})"
            )
    evidence = {
        "policy": "exact_homm3_traversal_keep_donor_gate_aligned",
        "reason": "native_donor_gate_equals_h3_visit",
        "decision": "align_olden_node_so_gate_equals_h3_visit",
        "anchorProjection": projection,
        "nativeFootprint": {
            "width": footprint.size_x,
            "height": footprint.size_z,
            "cellCount": footprint.in_grid_block_count,
            "source": "exact_homm3_keep_donor_native_nodes",
            "gateLocal": [gate_x, gate_z],
            "overflowBlockCount": footprint.overflow_block_count,
            "kind": footprint.kind,
            "mirrored": mirrored,
        },
        "node": node,
        "visitNode": visit_node,
        "sourceAnchorNode": default_node,
    }
    return node, evidence
