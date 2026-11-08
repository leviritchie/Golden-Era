# Homecoming: path holes, visit-gate clones, stack scaling

Status: historical July 8 installed-payload observation; runtime user-unvalidated. Current installed readiness must be re-proven with current validators.
Proof boundary at the time: source/static -> generated artifact -> validators -> installed payload. Runtime interaction and gameplay were not validated.

## Decisions

1. **Pad access protection:** abandon the 8-neighbor halo. Protect only HoMM3 visit cells and Olden GATE (`nodes==2`). Land-on clones put GATE on the real interact cell. A future enemy-gated pathability model is out of scope for this pass.
2. **Neutral stacks:** research HoMM3 `count==0` as CRTRAITS min–max guideline (VCMI). Improve scaling by emitting Olden **value budgets** (`count × squadValue` / nominal-tier × squadValue). Do **not** bake difficulty; keep `isIgnoreMultiply: false` so Olden `NeutralsDifficulty` scales at runtime.

## Workstreams

### A. Drop pad halo
- File: `experiments/campaign_port_poc/footprint_alignment.py`
- `access_protected_nodes_for_placement` returns `visit | gate` only.
- Regenerate; expect pathability mismatches to fall as scenery walls refill.

### B. Visit-gate ObjectConfig clones
- Pattern: `homm3_subterranean_gate_portal` (clone donor ObjectConfig + logic, new SID).
- New overlay generator for Homecoming land-on SIDs used with non-empty `templateVisitMask`.
- Priority:
  1. Towns: `homm3_castle_city` / `homm3_dungeon_city` — GATE near building center (not bottom corner).
  2. Guardhouse dwelling `barracks_homm3_castle_1` @ `0:18:34` + map event `0:18:35` reachable on GATE/visit cell.
  3. Remaining `barracks_homm3_castle_*`, then mines/stables/other visit-mask interactables used on Homecoming.
- Substitution routes Homecoming placements to clone SIDs; donors stay global.
- Validators pin Guardhouse event reachability and town GATE cells.

### C. Neutral stack value budgets
- Guideline: HoMM3 `count==0` → CRTRAITS-style default pool; use existing nominal-by-tier table as mid-pool proxy (not hardcoded per-creature CRTRAITS dump).
- Emit `requestedValue = round50(nominalTierCount × unit.squadValue)` for concrete typed stacks with `count==0`.
- Squad overlay `v` / `requiredValue` / `maxValue` use the same budget.
- Neutrals: `isIgnoreMultiply: false`. Recruitable/compliant keep ignore-multiply as today.
- Update single-layer/layered validators that currently require `_x1` / `requestedValue==1`.

### D. Prove
- Regenerate Homecoming layered atlas batch.
- Refresh catalogue / layered / regression baselines.
- Install to Golden Era; commit milestone.

## Follow-ups (not this pass)
- Enemy-defeat-aware pathability (which holes are intentional until a guard dies).
- Full CRTRAITS per-creature min/max tables if nominal-tier proxy proves too coarse in playtest.
