"""Frozen emit/terrain policy packs for approach_cell vs raw_translation.

Defaults match approach_cell. Raw selects RAW_TRANSLATION_EMIT_POLICY as a unit.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class EmitPolicyPack:
    """Unit policy for scenery-omit / terrain clearance bake-ins.

    Size-mismatch geometry (land-on GATE, solid-square scenery, BR→Olden node
    shift) stays on for every pack unless exact_homm3_footprints replaces it.
    Those live in surface_emit / exact_homm3_footprint placement code.
    """

    name: str
    apply_functional_emit_reservation: bool = True
    suppress_exact_anchor_scenery: bool = True
    suppress_underground_payloadless_scenery: bool = True
    apply_underground_tunnel_clearance: bool = True
    # When True: scenery catalog-matches identical footprints (else solid-square);
    # functionals keep donor ObjectConfig; landon/single_gate GATE-align to H3 visit;
    # gate_ring pivot-centers on visit; uncovered H3 blocks use visible gap-fill.
    # Never rewrite functional nodes or resize ObjectConfig.
    exact_homm3_footprints: bool = False
    # When True (raw only): after visit-on-GATE ∩ mine-clear fails for resource_*/chest
    # gate rings, try Chebyshev-1 neighbor interact cells (cardinal then diagonal).
    # Policy name: pickup_gate_ring_nearby_range_fallback_v1. Never reshapes mines.
    pickup_range_fallback_when_strict_fails: bool = False

    def to_manifest(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "policy": f"emit_policy_pack_{self.name}",
            **{key: value for key, value in asdict(self).items() if key != "name"},
        }


APPROACH_CELL_EMIT_POLICY = EmitPolicyPack(name="approach_cell")

RAW_TRANSLATION_EMIT_POLICY = EmitPolicyPack(
    name="raw_translation",
    apply_functional_emit_reservation=True,
    suppress_exact_anchor_scenery=False,
    suppress_underground_payloadless_scenery=False,
    # Same Chebyshev-2 rock→burrow shoulder as layered/approach_cell: H3 rock is
    # projected as levelsMap=1 cliffs, and 1-tile corridors lose 2x2 clearance to
    # adjacent elevation unless the shoulder is flattened to Burrow.
    apply_underground_tunnel_clearance=True,
    exact_homm3_footprints=True,
    pickup_range_fallback_when_strict_fails=True,
)

# Shape-class placement: landon/single_gate → GATE-marker-align; gate_ring →
# GATE-on-visit emit (runtime stand follows emit; GATE cells are markers only).
# Not footprint_alignment.py.
RAW_TRANSLATION_BR_NODE_SHIFT_POLICY = (
    "shape_class_gate_align_or_gate_on_visit_plus_visible_gap_fill_scenery_catalog_or_solid_square"
)
