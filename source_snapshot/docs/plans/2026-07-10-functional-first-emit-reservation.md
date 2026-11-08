# Functional-first emit reservation

**Status:** source/static + generated-artifact + validator-target-validated (layered + approach_cell + raw); runtime burial clearance user-unvalidated.

## Goal

Emit functional objects first and reserve HoMM3 visit ∪ non-visitable block so scenery cannot place occupied blockers on those cells. Native OCC and Olden GATE rings are **not** reserved — keep-donor GATE-align and chest/gold GATE rings invent markers on cells HoMM3 hard-blocks with mountains, and reserving them omitted true blocking scenery (empty holes). Functional anchors stay on HoMM3 source-footprint alignment (`no_functional_shift`).

## Why GATE rings are not reserved

Native pickups use a GATE ring around an occupied center. Only the H3 visit cell must stay clear for interaction. The other GATE cells often sit on H3 mountain/tree block masks; reserving the full ring (or skipping gap-fill on GATE) left walkable empty tiles inside H3 walls.

## Module

`experiments/campaign_port_poc/functional_emit_reservation.py`

- MiniLM-free and import-acyclic (no `footprint_alignment` / substitution map).
- Owns canonical `is_scenery_placement`, pad categories, and suppressible SID frozenset.
- Policy: `functional_first_h3_visit_block_scenery_omit_only`.
- `RESERVED_SIZE_GRID_NODE_VALUES = {}` (size-grid reservation retired).

## Two named cell sets

| Set | Meaning | Used for |
|-----|---------|----------|
| `functional_reserved` | H3 visit ∪ H3 non-visitable block | Scenery emit omit, pad refusal, validators |
| `access_protected` | visit ∪ GATE only | Existing pad-access semantics (`visit_gate_only`) |

Pads consult `functional_reserved` in addition to `global_blocked ∪ access_protected`.

Gap-fill coverage for functionals is only `OCC ∩ (H3 visit ∪ H3 block)`; scenery uses full OCC. Residual H3 blocks are sealed even when an Olden GATE marker sits on that cell.

## Callers

- `build_homecoming_single_layer_map.build_surface_objects` (layered inherits)
- `approach_cell/surface_emit.build_surface_objects` (emit-reservation only; no footprint_alignment spine)
- raw_translation via approach_cell emit policy (`apply_functional_emit_reservation`)

Scenery policy at emit: **omit-only** when occupied ∩ reserved ≠ ∅.
