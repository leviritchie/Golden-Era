"""Isolated HoMM3 creature-bank remapping for the raw_translation lane.

Default generation does not run this pass. When enabled, it remaps object-16
bank variants and Den of Thieves (object 97) after main raw placement and
before terrain/scenery randomization and the HoMM3 footprint-compatibility
repair pass.

Policy (source/static):
- Identify banks by template animation/subtype, not only object id 16.
- Choose among geometry-valid Olden candidates only.
- Prefer function match (unit bank / resource bank / scouting).
- Balance least-used among equally ranked candidates.
- Fail closed with per-placement rejections; never fall back to shady_den
  merely because that SID is available.

Custom exact-footprint SIDs for banks that have no native geometry match are
not invented here yet; those placements fail closed with an explicit reason.
"""

from __future__ import annotations

import copy
from collections import Counter
from dataclasses import dataclass
from typing import Any, Callable

from native_footprint_model import (
    NATIVE_CELL_PROJECTION_FAILURES,
    model_native_footprint,
    native_cell_projection_failure_reasons,
)


SCHEMA = "olden.raw_translation.homm3_bank_remapping.v1"
STATUS_APPLIED = "applied"
STATUS_NOOP = "no_changes_needed"
STATUS_FAILED = "failed_closed"
STATUS_DISABLED = "disabled"

SOURCE_OBJECT_CREATURE_BANK = 16
SOURCE_OBJECT_DEN_OF_THIEVES = 97

# Removable encounter families (not permanent buildings for later audits).
FUNCTION_UNIT_BANK = "guarded_unit_bank"
FUNCTION_RESOURCE_BANK = "guarded_resource_bank"
FUNCTION_SCOUTING = "scouting_information"

# Creature-reward donors (Core guarded_unit_banks).
UNIT_BANK_CANDIDATES: tuple[str, ...] = (
    "boreal_call",
    "jousting_range",
    "petrified_memorial",
    "point_of_balance",
    "ritual_pyre",
    "the_gorge",
    "underground_lair",
    "unforgotten_grave",
    "vanguard",
)

# Guarded resource banks ordered smallest footprint first.
RESOURCE_BANK_CANDIDATES: tuple[str, ...] = (
    # 2x2 / 1 OCC
    "abandoned_mansion",
    "black_tower",
    "mereas_shrine",
    # 3x3 / 4 OCC
    "abnormal_structure",
    "alvars_eye",
    "circle_of_life",
    "cursed_old_house",
    "iridescent_abbey",
    "legions_memorial",
    "overgrown_grave",
    "prismatic_lair",
    "raiders_camp",
    "shady_den",
    "testing_grounds",
    "troglodyte_throne",
    "twilight_bloom",
    "uncanny_rite",
    # 4x4 / 9 OCC
    "dragon_utopia",
    "research_laboratory",
    "unstable_ruins",
)

SCOUTING_CANDIDATES: tuple[str, ...] = (
    "watchtower",
)

# HoMM3 object-16 template animation → intentional source family.
# Keys are lowercase. Unknown bank animations fail closed (no silent shady_den).
BANK_FAMILIES: dict[str, dict[str, Any]] = {
    "avxbnk10.def": {
        "familyId": "cyclops_stockpile",
        "displayName": "Cyclops Stockpile",
        "function": FUNCTION_RESOURCE_BANK,
        "preferredCandidates": RESOURCE_BANK_CANDIDATES,
    },
    "avxbnk20.def": {
        "familyId": "dwarven_treasury",
        "displayName": "Dwarven Treasury",
        "function": FUNCTION_RESOURCE_BANK,
        "preferredCandidates": RESOURCE_BANK_CANDIDATES,
    },
    "avxbnk30.def": {
        "familyId": "griffin_conservatory",
        "displayName": "Griffin Conservatory",
        "function": FUNCTION_UNIT_BANK,
        "preferredCandidates": UNIT_BANK_CANDIDATES,
    },
    "avxbnk40.def": {
        "familyId": "imp_cache",
        "displayName": "Imp Cache",
        "function": FUNCTION_RESOURCE_BANK,
        "preferredCandidates": RESOURCE_BANK_CANDIDATES,
    },
    "avxbnk50.def": {
        "familyId": "medusa_stores",
        "displayName": "Medusa Stores",
        "function": FUNCTION_RESOURCE_BANK,
        "preferredCandidates": RESOURCE_BANK_CANDIDATES,
    },
    "avxbnk60.def": {
        "familyId": "naga_bank",
        "displayName": "Naga Bank",
        "function": FUNCTION_RESOURCE_BANK,
        "preferredCandidates": RESOURCE_BANK_CANDIDATES,
    },
    "avxbnk70.def": {
        "familyId": "dragon_fly_hive",
        "displayName": "Dragon Fly Hive",
        "function": FUNCTION_UNIT_BANK,
        # Prefer the smallest OE banks (2x2 / 1 OCC) before denser unit banks.
        "preferredCandidates": (
            "abandoned_mansion",
            "black_tower",
            "mereas_shrine",
        )
        + UNIT_BANK_CANDIDATES,
    },
    "avxbnk80.def": {
        "familyId": "wolf_raider_picket",
        "displayName": "Wolf Raider Picket",
        "function": FUNCTION_RESOURCE_BANK,
        "preferredCandidates": RESOURCE_BANK_CANDIDATES,
    },
    "avxbnk90.def": {
        "familyId": "experimental_shop",
        "displayName": "Experimental Shop",
        "function": FUNCTION_RESOURCE_BANK,
        "preferredCandidates": RESOURCE_BANK_CANDIDATES,
    },
    # Den of Thieves is not a creature bank.
    "avxdent.def": {
        "familyId": "den_of_thieves",
        "displayName": "Den of Thieves",
        "function": FUNCTION_SCOUTING,
        "preferredCandidates": SCOUTING_CANDIDATES,
    },
}


class Homm3BankRemappingError(RuntimeError):
    """Raised when bank remapping cannot complete without guessing."""

    def __init__(self, report: dict[str, Any]):
        self.report = report
        failures = report.get("failures") or []
        map_sid = report.get("mapSid") or "raw_translation"
        super().__init__(
            f"{map_sid}: H3 bank remapping failed closed for "
            f"{len(failures)} placement(s); first failure={failures[0] if failures else 'unknown'}"
        )


@dataclass(frozen=True)
class BankPlacement:
    object_id: int
    original_sid: str
    node: int
    rotation: int
    group_index: int
    instance_index: int
    entity: dict[str, Any]
    family: dict[str, Any]
    source_object_id: int
    animation: str
    subtype: int | None


@dataclass(frozen=True)
class CandidateEvaluation:
    sid: str
    accepted: bool
    reasons: tuple[str, ...]
    source_blocker_cells: frozenset[int]
    selected_blocker_cells: frozenset[int]
    source_gate_cells: frozenset[int]
    selected_gate_cells: frozenset[int]
    uncovered_source_blockers: frozenset[int]
    extra_open_blockers: frozenset[int]
    rank: tuple[int, int, int, str]


def normalize_animation(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip().lower()


def resolve_bank_family(
    *,
    template_object_id: Any,
    template_animation: Any,
) -> dict[str, Any] | None:
    """Return the intentional source family for a bank/den placement, or None."""
    if template_object_id not in (SOURCE_OBJECT_CREATURE_BANK, SOURCE_OBJECT_DEN_OF_THIEVES):
        return None
    animation = normalize_animation(template_animation)
    family = BANK_FAMILIES.get(animation)
    if family is None:
        return None
    if (
        template_object_id == SOURCE_OBJECT_DEN_OF_THIEVES
        and family["function"] != FUNCTION_SCOUTING
    ):
        return None
    if (
        template_object_id == SOURCE_OBJECT_CREATURE_BANK
        and family["function"] == FUNCTION_SCOUTING
    ):
        return None
    return family


def _h3_block_mask_offsets(mask: Any) -> set[tuple[int, int]]:
    """Decode H3M block mask: clear bit = blocked (VCMI / surface_emit convention)."""
    if not isinstance(mask, list) or len(mask) != 6:
        return set()
    offsets: set[tuple[int, int]] = set()
    for row_index, raw in enumerate(mask):
        if not isinstance(raw, int) or raw < 0 or raw > 255:
            raise ValueError(f"invalid H3M block mask byte: {raw!r}")
        for col_index in range(8):
            if (raw >> col_index) & 1 == 0:
                offsets.add((col_index - 7, row_index - 5))
    return offsets


def _h3_visit_mask_offsets(mask: Any) -> set[tuple[int, int]]:
    """Decode H3M visit mask: set bit = visitable (VCMI / surface_emit convention)."""
    if not isinstance(mask, list) or len(mask) != 6:
        return set()
    offsets: set[tuple[int, int]] = set()
    for row_index, raw in enumerate(mask):
        if not isinstance(raw, int) or raw < 0 or raw > 255:
            raise ValueError(f"invalid H3M visit mask byte: {raw!r}")
        for col_index in range(8):
            if raw & (1 << col_index):
                offsets.add((col_index - 7, row_index - 5))
    return offsets


def source_block_offsets(entity: dict[str, Any]) -> set[tuple[int, int]]:
    return _h3_block_mask_offsets(entity.get("templateBlockMask"))


def source_visit_offsets(entity: dict[str, Any]) -> set[tuple[int, int]]:
    return _h3_visit_mask_offsets(entity.get("templateVisitMask"))


def source_nonvisitable_block_offsets(entity: dict[str, Any]) -> set[tuple[int, int]]:
    return source_block_offsets(entity) - source_visit_offsets(entity)


def _project_offsets(
    entity: dict[str, Any],
    offsets: set[tuple[int, int]],
    *,
    layer_target_node: Callable[[int, int, int], int],
) -> tuple[frozenset[int], list[str]]:
    source_x = entity.get("sourceX")
    source_y = entity.get("sourceY")
    source_layer = entity.get("sourceLayer")
    if not isinstance(source_x, int) or not isinstance(source_y, int):
        return frozenset(), ["source_coordinates_invalid"]
    if not isinstance(source_layer, int):
        source_layer = 0
    cells: set[int] = set()
    reasons: list[str] = []
    out_of_bounds = 0
    for dx, dy in offsets:
        try:
            cells.add(layer_target_node(source_layer, source_x + dx, source_y + dy))
        except (ValueError, TypeError):
            out_of_bounds += 1
    if out_of_bounds:
        reasons.append(f"source_offset_out_of_bounds_count={out_of_bounds}")
    return frozenset(cells), reasons


def evaluate_candidate(
    *,
    sid: str,
    config: dict[str, Any] | None,
    entity: dict[str, Any],
    anchor_node: int,
    rotation: int,
    width: int,
    height: int,
    layer_target_node: Callable[[int, int, int], int],
) -> CandidateEvaluation:
    reasons: list[str] = []
    source_blockers, block_reasons = _project_offsets(
        entity,
        source_nonvisitable_block_offsets(entity),
        layer_target_node=layer_target_node,
    )
    source_all_block, all_block_reasons = _project_offsets(
        entity,
        source_block_offsets(entity),
        layer_target_node=layer_target_node,
    )
    source_gates, gate_reasons = _project_offsets(
        entity,
        source_visit_offsets(entity),
        layer_target_node=layer_target_node,
    )
    reasons.extend(block_reasons)
    reasons.extend(all_block_reasons)
    reasons.extend(gate_reasons)

    empty = frozenset()
    if config is None:
        return CandidateEvaluation(
            sid=sid,
            accepted=False,
            reasons=tuple(reasons + ["missing_native_object_config"]),
            source_blocker_cells=source_blockers,
            selected_blocker_cells=empty,
            source_gate_cells=source_gates,
            selected_gate_cells=empty,
            uncovered_source_blockers=source_blockers,
            extra_open_blockers=empty,
            rank=(10_000, 10_000, 10_000, sid),
        )

    model = model_native_footprint(
        sid,
        config,
        anchor_node,
        rotation,
        width=width,
        height=height,
    )
    projection_failures = native_cell_projection_failure_reasons(model)
    selected_blockers = frozenset(model.occupied_cells)
    selected_gates = frozenset(model.gate_cells)
    if projection_failures:
        reasons.extend(f"native_projection:{reason}" for reason in projection_failures)

    uncovered = source_blockers - selected_blockers
    # A native OCC cell is only allowed when HoMM3 already blocks that cell
    # (block mask includes visit and non-visit cells for bank envelopes).
    extra_open = selected_blockers - source_all_block
    if uncovered:
        reasons.append("uncovered_source_nonvisitable_blockers")
    if extra_open:
        reasons.append("extra_blockers_on_source_passable_cells")
    if projection_failures:
        reasons.append("unsafe_native_projection")

    accepted = not uncovered and not extra_open and not projection_failures
    rank = (
        len(uncovered),
        len(extra_open),
        len(selected_blockers),
        sid,
    )
    return CandidateEvaluation(
        sid=sid,
        accepted=accepted,
        reasons=tuple(dict.fromkeys(reasons)),
        source_blocker_cells=source_blockers,
        selected_blocker_cells=selected_blockers,
        source_gate_cells=source_gates,
        selected_gate_cells=selected_gates,
        uncovered_source_blockers=uncovered,
        extra_open_blockers=extra_open,
        rank=rank,
    )


def _iter_instances(objects: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for group_index, group in enumerate(objects):
        if not isinstance(group, dict):
            raise ValueError(f"malformed object group: {group!r}")
        sid = group.get("sid")
        ids = group.get("ids")
        nodes = group.get("nodes")
        rotations = group.get("rotations")
        levels = group.get("levels")
        if not isinstance(sid, str) or not all(
            isinstance(value, list) for value in (ids, nodes, rotations, levels)
        ):
            raise ValueError(f"malformed object group for sid={sid!r}")
        if not (len(ids) == len(nodes) == len(rotations) == len(levels)):
            raise ValueError(f"malformed object group lengths for sid={sid!r}")
        for instance_index, object_id in enumerate(ids):
            if not isinstance(object_id, int):
                raise ValueError(f"malformed object id for sid={sid!r}")
            rows.append(
                {
                    "objectId": object_id,
                    "sid": sid,
                    "node": int(nodes[instance_index]),
                    "rotation": int(rotations[instance_index]),
                    "level": levels[instance_index],
                    "groupIndex": group_index,
                    "instanceIndex": instance_index,
                }
            )
    return rows


def _entity_lookup(global_entities: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    out: dict[int, dict[str, Any]] = {}
    for entity in global_entities:
        source_index = entity.get("sourceIndex")
        if not isinstance(source_index, int):
            continue
        if source_index in out:
            raise ValueError(f"duplicate sourceIndex {source_index}")
        out[source_index] = entity
    return out


def collect_bank_placements(
    *,
    objects: list[dict[str, Any]],
    global_entities: list[dict[str, Any]],
) -> tuple[list[BankPlacement], list[dict[str, Any]]]:
    """Identify bank/den source placements already emitted onto the map."""
    entities = _entity_lookup(global_entities)
    placements: list[BankPlacement] = []
    unknown: list[dict[str, Any]] = []
    for row in _iter_instances(objects):
        entity = entities.get(row["objectId"])
        if entity is None:
            continue
        template_object_id = entity.get("templateObjectId")
        if template_object_id not in (
            SOURCE_OBJECT_CREATURE_BANK,
            SOURCE_OBJECT_DEN_OF_THIEVES,
        ):
            continue
        animation = normalize_animation(entity.get("templateAnimation"))
        family = resolve_bank_family(
            template_object_id=template_object_id,
            template_animation=animation,
        )
        if family is None:
            unknown.append(
                {
                    "objectId": row["objectId"],
                    "sid": row["sid"],
                    "templateObjectId": template_object_id,
                    "templateAnimation": entity.get("templateAnimation"),
                    "templateSubtype": entity.get("templateSubtype"),
                    "reason": "unknown_or_unmapped_bank_animation",
                }
            )
            continue
        subtype = entity.get("templateSubtype")
        placements.append(
            BankPlacement(
                object_id=row["objectId"],
                original_sid=row["sid"],
                node=row["node"],
                rotation=row["rotation"],
                group_index=row["groupIndex"],
                instance_index=row["instanceIndex"],
                entity=entity,
                family=family,
                source_object_id=int(template_object_id),
                animation=animation,
                subtype=int(subtype) if isinstance(subtype, int) else None,
            )
        )
    placements.sort(key=lambda item: item.object_id)
    return placements, unknown


def _local_occupied_cells(config: dict[str, Any]) -> list[tuple[int, int]]:
    size_x = config.get("sizeX")
    size_z = config.get("sizeZ")
    nodes = config.get("nodes")
    if (
        not isinstance(size_x, int)
        or not isinstance(size_z, int)
        or not isinstance(nodes, list)
        or len(nodes) != size_x * size_z
    ):
        return []
    return [
        (index % size_x, index // size_x)
        for index, value in enumerate(nodes)
        if int(value) == 1
    ]


def _trial_anchors_for_candidate(
    *,
    placement: BankPlacement,
    config: dict[str, Any],
    width: int,
    height: int,
    layer_target_node: Callable[[int, int, int], int],
) -> list[int]:
    """Return deterministic anchor trials: current emit node, then OCC-on-source-blocker."""
    anchors = [placement.node]
    pivot_x = int(config.get("pivotX") or 0)
    pivot_z = int(config.get("pivotZ") or 0)
    locals_occ = _local_occupied_cells(config)
    if len(locals_occ) != 1:
        # Multi-OCC banks keep the H3 source anchor; only re-try current node.
        return anchors
    local_x, local_z = locals_occ[0]
    source_layer = placement.entity.get("sourceLayer")
    if not isinstance(source_layer, int):
        source_layer = 0
    entity = placement.entity
    offsets = source_nonvisitable_block_offsets(entity)
    if not offsets:
        # Visit-only banks: pin the single OCC onto the visit cell when present.
        offsets = source_visit_offsets(entity)
    for dx, dy in sorted(offsets):
        source_x = entity.get("sourceX")
        source_y = entity.get("sourceY")
        if not isinstance(source_x, int) or not isinstance(source_y, int):
            continue
        # Reverse unmirrored native projection for rotation 0:
        # cell = (anchor_x - pivot_x + local_x, anchor_y + pivot_z - local_z)
        target_x = source_x + dx
        target_y = source_y + dy
        anchor_x = target_x - local_x + pivot_x
        anchor_y = target_y + local_z - pivot_z
        if not (0 <= anchor_x < width and 0 <= anchor_y < height):
            continue
        try:
            trial = layer_target_node(source_layer, anchor_x, anchor_y)
        except (ValueError, TypeError):
            continue
        if trial not in anchors:
            anchors.append(trial)
    return anchors


def assign_bank_sid(
    *,
    placement: BankPlacement,
    usage: Counter[str],
    configs: dict[str, dict[str, Any]],
    width: int,
    height: int,
    layer_target_node: Callable[[int, int, int], int],
) -> tuple[str | None, list[dict[str, Any]], CandidateEvaluation | None, int | None]:
    evaluations: list[CandidateEvaluation] = []
    best_by_sid: dict[str, tuple[CandidateEvaluation, int]] = {}
    for sid in placement.family["preferredCandidates"]:
        config = configs.get(sid)
        if config is None:
            evaluation = evaluate_candidate(
                sid=sid,
                config=None,
                entity=placement.entity,
                anchor_node=placement.node,
                rotation=placement.rotation,
                width=width,
                height=height,
                layer_target_node=layer_target_node,
            )
            evaluations.append(evaluation)
            continue
        trial_anchors = _trial_anchors_for_candidate(
            placement=placement,
            config=config,
            width=width,
            height=height,
            layer_target_node=layer_target_node,
        )
        best_for_sid: CandidateEvaluation | None = None
        best_anchor = placement.node
        for trial_anchor in trial_anchors:
            evaluation = evaluate_candidate(
                sid=sid,
                config=config,
                entity=placement.entity,
                anchor_node=trial_anchor,
                rotation=placement.rotation,
                width=width,
                height=height,
                layer_target_node=layer_target_node,
            )
            if best_for_sid is None or evaluation.rank < best_for_sid.rank:
                best_for_sid = evaluation
                best_anchor = trial_anchor
            if evaluation.accepted:
                # Prefer accepted anchors with lowest rank; keep scanning for parity equals.
                break
        assert best_for_sid is not None
        evaluations.append(best_for_sid)
        best_by_sid[sid] = (best_for_sid, best_anchor)

    accepted = [
        (item, best_by_sid[item.sid][1])
        for item in evaluations
        if item.accepted and item.sid in best_by_sid
    ]
    if not accepted:
        return None, [
            {
                "sid": item.sid,
                "accepted": False,
                "reasons": list(item.reasons),
                "sourceBlockerCells": sorted(item.source_blocker_cells),
                "selectedBlockerCells": sorted(item.selected_blocker_cells),
                "sourceGateCells": sorted(item.source_gate_cells),
                "selectedGateCells": sorted(item.selected_gate_cells),
                "uncoveredSourceBlockers": sorted(item.uncovered_source_blockers),
                "extraOpenBlockers": sorted(item.extra_open_blockers),
            }
            for item in evaluations
        ], None, None

    # Geometry first, then deterministic least-used among equals.
    best_geometry = min(item.rank[:3] for item, _anchor in accepted)
    tier = [(item, anchor) for item, anchor in accepted if item.rank[:3] == best_geometry]
    tier.sort(key=lambda pair: (usage[pair[0].sid], pair[0].sid))
    chosen, chosen_anchor = tier[0]
    return chosen.sid, [
        {
            "sid": item.sid,
            "accepted": item.accepted,
            "reasons": list(item.reasons),
            "sourceBlockerCells": sorted(item.source_blocker_cells),
            "selectedBlockerCells": sorted(item.selected_blocker_cells),
            "sourceGateCells": sorted(item.source_gate_cells),
            "selectedGateCells": sorted(item.selected_gate_cells),
            "uncoveredSourceBlockers": sorted(item.uncovered_source_blockers),
            "extraOpenBlockers": sorted(item.extra_open_blockers),
            "selected": item.sid == chosen.sid,
            "anchorNode": best_by_sid[item.sid][1] if item.sid in best_by_sid else None,
        }
        for item in evaluations
    ], chosen, chosen_anchor


def _rewrite_object_sids(
    objects: list[dict[str, Any]],
    rewrites: list[dict[str, Any]],
) -> None:
    """Move/re-anchor instances according to remapping assignments."""
    if not rewrites:
        return
    by_id = {int(row["objectId"]): row for row in rewrites}
    # Extract instances from their original groups.
    moved: list[dict[str, Any]] = []
    for group in objects:
        ids = group["ids"]
        keep_ids: list[int] = []
        keep_nodes: list[int] = []
        keep_rotations: list[int] = []
        keep_levels: list[Any] = []
        for index, object_id in enumerate(ids):
            rewrite = by_id.get(int(object_id))
            if rewrite is None:
                keep_ids.append(object_id)
                keep_nodes.append(group["nodes"][index])
                keep_rotations.append(group["rotations"][index])
                keep_levels.append(group["levels"][index])
                continue
            target_sid = rewrite["selectedSid"]
            target_node = int(rewrite.get("anchorNode", group["nodes"][index]))
            if target_sid == group["sid"] and target_node == group["nodes"][index]:
                keep_ids.append(object_id)
                keep_nodes.append(group["nodes"][index])
                keep_rotations.append(group["rotations"][index])
                keep_levels.append(group["levels"][index])
                continue
            moved.append(
                {
                    "objectId": int(object_id),
                    "sid": target_sid,
                    "node": target_node,
                    "rotation": group["rotations"][index],
                    "level": group["levels"][index],
                }
            )
        group["ids"] = keep_ids
        group["nodes"] = keep_nodes
        group["rotations"] = keep_rotations
        group["levels"] = keep_levels

    # Drop empty groups; append/reuse target groups stably by sid string order.
    objects[:] = [group for group in objects if group["ids"]]
    groups_by_sid = {group["sid"]: group for group in objects if isinstance(group.get("sid"), str)}
    for item in sorted(moved, key=lambda row: row["objectId"]):
        sid = item["sid"]
        group = groups_by_sid.get(sid)
        if group is None:
            group = {
                "sid": sid,
                "ids": [],
                "nodes": [],
                "rotations": [],
                "levels": [],
            }
            objects.append(group)
            groups_by_sid[sid] = group
        group["ids"].append(item["objectId"])
        group["nodes"].append(item["node"])
        group["rotations"].append(item["rotation"])
        group["levels"].append(item["level"])


def ensure_bank_candidate_configs(
    configs: dict[str, dict[str, Any]],
    *,
    core_zip_path: str | Any | None = None,
) -> list[str]:
    """Load any missing bank/scouting candidate ObjectConfigs into ``configs``."""
    needed = sorted(
        set(UNIT_BANK_CANDIDATES)
        | set(RESOURCE_BANK_CANDIDATES)
        | set(SCOUTING_CANDIDATES)
    )
    missing = [sid for sid in needed if sid not in configs]
    if not missing:
        return []
    if core_zip_path is None:
        return missing
    import core_zip_cache  # local import keeps the module usable offline fixtures

    all_rows = core_zip_cache.map_object_configs_by_id(core_zip_path)
    still_missing: list[str] = []
    for sid in missing:
        row = all_rows.get(sid)
        if not isinstance(row, dict):
            still_missing.append(sid)
            continue
        configs[sid] = copy.deepcopy(row)
    return still_missing


def apply_homm3_bank_remapping(
    *,
    global_entities: list[dict[str, Any]],
    objects: list[dict[str, Any]],
    native_object_configs: dict[str, dict[str, Any]],
    layer_target_node: Callable[[int, int, int], int],
    width: int,
    height: int,
    map_sid: str,
    core_zip_path: str | Any | None = None,
    raise_on_failure: bool = True,
) -> dict[str, Any]:
    """Remap bank placements on a candidate object list.

    Commits to ``objects`` only when every identified bank placement receives a
    geometry-valid assignment. Unknown animations and zero-valid-candidate cases
    fail closed.
    """
    if width <= 0 or height <= 0:
        raise ValueError(f"invalid map dimensions: {width}x{height}")

    working_objects = copy.deepcopy(objects)
    missing_configs = ensure_bank_candidate_configs(
        native_object_configs,
        core_zip_path=core_zip_path,
    )
    placements, unknown = collect_bank_placements(
        objects=working_objects,
        global_entities=global_entities,
    )

    report: dict[str, Any] = {
        "schema": SCHEMA,
        "status": STATUS_NOOP,
        "mapSid": map_sid,
        "width": width,
        "height": height,
        "policy": (
            "animation_family_then_function_then_blocker_parity_then_least_used; "
            "no_shady_den_fallback; custom_exact_sid_not_auto_emitted"
        ),
        "proofBoundary": (
            "source/static bank identity + geometry assignment only; "
            "reward-logic rows and runtime encounter remain unproven"
        ),
        "placementCount": len(placements),
        "assignments": [],
        "failures": [],
        "unknownBanks": unknown,
        "missingCandidateConfigs": missing_configs,
        "selectedSidHistogram": {},
        "originalSidHistogram": {},
    }

    for missing in missing_configs:
        report["failures"].append(
            {
                "reason": "missing_native_object_config_for_bank_candidate",
                "sid": missing,
            }
        )
    for row in unknown:
        report["failures"].append(
            {
                **row,
                "reason": "unknown_or_unmapped_bank_animation",
            }
        )

    usage: Counter[str] = Counter()
    rewrites: list[dict[str, Any]] = []
    original_hist: Counter[str] = Counter()

    for placement in placements:
        original_hist[placement.original_sid] += 1
        selected_sid, evaluations, chosen, chosen_anchor = assign_bank_sid(
            placement=placement,
            usage=usage,
            configs=native_object_configs,
            width=width,
            height=height,
            layer_target_node=layer_target_node,
        )
        if selected_sid is None or chosen is None or chosen_anchor is None:
            report["failures"].append(
                {
                    "objectId": placement.object_id,
                    "sourceObjectId": placement.source_object_id,
                    "templateAnimation": placement.animation,
                    "templateSubtype": placement.subtype,
                    "sourceBankName": placement.family["displayName"],
                    "sourceFunction": placement.family["function"],
                    "originalSid": placement.original_sid,
                    "reason": "no_geometry_valid_native_candidate",
                    "nextStep": (
                        "create_dedicated_custom_sid_with_exact_h3_footprint_"
                        "and_separate_reward_logic"
                    ),
                    "rejectedCandidates": evaluations,
                    "sourceCoordinates": {
                        "x": placement.entity.get("sourceX"),
                        "y": placement.entity.get("sourceY"),
                        "layer": placement.entity.get("sourceLayer"),
                    },
                }
            )
            continue

        usage[selected_sid] += 1
        assignment = {
            "objectId": placement.object_id,
            "sourceObjectId": placement.source_object_id,
            "templateAnimation": placement.animation,
            "templateSubtype": placement.subtype,
            "sourceBankName": placement.family["displayName"],
            "sourceFunction": placement.family["function"],
            "originalSid": placement.original_sid,
            "selectedSid": selected_sid,
            "anchorNode": chosen_anchor,
            "originalAnchorNode": placement.node,
            "rewardLogicSid": selected_sid,
            "assignmentKind": "native",
            "reason": (
                "function_and_blocker_parity_match;least_used_among_equal_geometry"
                if selected_sid != placement.original_sid or chosen_anchor != placement.node
                else "existing_sid_already_geometry_valid"
            ),
            "sourceBlockerCells": sorted(chosen.source_blocker_cells),
            "selectedBlockerCells": sorted(chosen.selected_blocker_cells),
            "sourceGateCells": sorted(chosen.source_gate_cells),
            "selectedGateCells": sorted(chosen.selected_gate_cells),
            "candidates": evaluations,
        }
        report["assignments"].append(assignment)
        if selected_sid != placement.original_sid or chosen_anchor != placement.node:
            rewrites.append(assignment)

    report["originalSidHistogram"] = dict(original_hist.most_common())
    report["selectedSidHistogram"] = dict(usage.most_common())

    if report["failures"]:
        report["status"] = STATUS_FAILED
        if raise_on_failure:
            raise Homm3BankRemappingError(report)
        return report

    if not rewrites and not report["assignments"]:
        report["status"] = STATUS_NOOP
        return report

    _rewrite_object_sids(working_objects, rewrites)
    # Commit only after every placement resolved.
    objects[:] = working_objects
    report["status"] = STATUS_APPLIED if rewrites else STATUS_NOOP
    report["rewrittenCount"] = len(rewrites)
    return report
