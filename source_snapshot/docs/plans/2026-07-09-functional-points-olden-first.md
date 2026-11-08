# Olden-First Functional Points (Homecoming)

Status: source/static + generated-artifact + validator implemented for Homecoming layered atlas. Runtime gameplay unvalidated.

## Goal

Drive Homecoming layered placement from **Olden-reachable interactables**, not cell-for-cell HoMM3 scenery/pathability identity.

Every play-relevant interactable becomes a **functional point** with:

1. An Olden visit / GATE anchor that satisfies the static marker and occupation contract and is not buried under another object's occupied footprint (for example, the Guardhouse map-event marker is in front of the approach rather than inside the barracks block).
2. An approach corridor that is pathable once declared **gate packs** (neutral stacks) are treated as cleared.
3. Fail-closed validators that reject maps where functional points fail static reachability, GATE/visit membership, occupation exclusion, or approach-cell requirements. Runtime click dispatch is not proven.

Geometric H3 mismatch grids remain diagnostics only; they are not the interactable success metric.

## Approach

### A. Catalogue

- Schema: `homm3.olden_functional_points.v1`
- Module: `experiments/campaign_port_poc/functional_points.py`
- Emit: `artifacts/campaign_port_poc/homecoming_poc/functional_points/homecoming.functional_points.json`
- Homecoming v1 membership: **closed category allowlist** — emit every instance of `map_event`, `town`, `dwelling`, `mine`, `pickup`, `portal` (extend explicitly later; no curator “play-critical” guesswork).
- Fields: `functionalPointId`, `missionId`, `sourceKey`, `layer`, `category`, `oldenSid`, `visitPolicy`, `approachFacing`, `gatePackIds`, `pathRoot` (`spawn` | `layer_entry` | portal FP id).

### B. Gate packs (overrides are input only)

- Checked-in overrides: `scenarios/homecoming_roe_castle/functional_points.gate_pack_overrides.json`
- Seed from existing same-or-adjacent visit/guard evidence; merge overrides at emit.
- Resolved `gatePackIds` are written into the emitted catalogue. Downstream reads the catalogue only.
- Ambiguous / empty → fail closed (no silent empty gates). **No** minimal-guard set solver.

### C. Layered atlas post-pass (one pass)

Reuse land-on SID / GATE policy and existing visit-GATE approach-lane clearing:

1. Relocate visit/GATE anchors (map-event markers out of host footprints; town GATE approaches left with a free approach cell).
2. Clear / reshape scenery **only** on that FP’s shared corridor cells (`pathRoot → visit/GATE`). Local conflict precedence: functional point wins over pad/absorb for those cells only. Footprint alignment stays otherwise.
3. Relocate declared gate-pack neutrals onto those corridor cells when current placement fails the contract.

Do **not** invent a separate scenery/topology engine or reopen zone_atlas choke graphs.

### D. Validation

- Shared helpers in `functional_points.py` used by emitter, post-pass, and `validate_homecoming_layered_atlas_map_contract.py`.
- Per FP: BFS from `pathRoot` with that FP’s `gatePackIds` treated as passable; visit cell must be GATE/visit and not under foreign occupation; towns need ≥1 free approach cell.
- Cost model: O(F · C) on layered grids. No pack-order progression graph. Do not re-run full cell/pathability catalogue regen as the FP gatekeeper.
- Underground FPs use first-class `pathRoot` of `layer_entry` or a portal FP.

### E. Build / docs

- MSBuild: wire into Homecoming layered contract path.
- This doc + one sentence in `docs/plans/2026-07-09-homm3-converter-semantic-coverage.md` that interactable completeness is the functional-point static accessibility contract, not geometric mismatch counts.

## Settled decisions

| Decision | Choice |
|---|---|
| Success metric | Functional-point static accessibility contract |
| Gate packs | Override-backed evidence lists at emit |
| Pads vs FP | FP corridor cells win locally; do not retire footprint_alignment |
| Delivery | Homecoming layered atlas only (schema reusable later) |
| Zone atlas / RMG | Out of scope |
| Land-on SIDs | Keep; move anchors |
| Combinatorial solvers | Forbidden (min-guard, pack sequencing) |

## Non-goals

- Pixel-perfect HoMM3 scenery clone
- Pathability-grid parity as a pass/fail metric
- RMG hybrid rewrite
- Inventing new SIDs unless an existing land-on/native SID cannot host the visit policy
- Loss budgets that mark blocked interactables “complete”

## Proof boundary

Implementation would land as source/static + generated-artifact + validator first. In-game join/pathing remains user-unvalidated until explicit playtest.
