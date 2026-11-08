# Adventure AI sim — live map capture handoff

Date: 2026-08-02
Workspace: `V:\Games\Olden Era Playtest Tweak`
Active install: `V:\SteamLibrary\steamapps\common\Heroes of Might and Magic Olden Era - Golden Era`

Evidence in this handoff: **source/static** unless a line says otherwise.
Golden Era day-start Evaluate → bias apply: **runtime-unvalidated**.

Parent contracts:

- [`ai_external_sim_weight_bridge.md`](ai_external_sim_weight_bridge.md) — locked product shape
- [`ai_lookahead_requirements.md`](ai_lookahead_requirements.md) — mark-centric + omniscient L1
- [`ai_decision_logic_surface.md`](ai_decision_logic_surface.md) — native choke points

Prior chat leave-off: [AI sim + weight bridge](9aa506dd-a625-4e3a-bff7-4790cc815437) (2026-07-18 GUI / town / `frontier_hold`).

## One-sentence status

Offline `OldenAiSim` + score-bias bridge are source-wired; the live adapter now reads bounded full-map arrays, live hero pose, and session occupancy. **Golden Era startup/runtime behavior remains unvalidated.**

## Locked product shape (do not reopen)

| Decision | Choice |
|----------|--------|
| Where AI logic lives | Separate managed DLL `tools/olden_ai_sim` (`OldenAiSim`) — no Unity/Harmony/Hex refs |
| How it influences native AI | Bias multipliers on adventure task scores via Harmony postfix on `ffe.bjsj` |
| What native still owns | Candidate legality, path commit, enter-node (`fjp` / `fjj.bjxq`) |
| Planner state | Mark-centric + omniscient (fog-faithful is later) |
| Combat in the tree | L1 heuristic (`Σ stacks × unitValue`); not L2 `eeo` re-sim |

Flow:

```text
fjl.OnStartDay
  -> Homm3AdventureLookaheadState.TryCaptureFromLiveSide
  -> Homm3AiDriverBridge.TryCaptureAdventureLiveWorld
  -> TryValidateForSimulation / ToSimState
  → AdventureSimulator.Evaluate
  → bias cache
  → ffe.bjsj postfix multiplies __result when candidate matches bias key
```

Flags:

- `homm3_adventure_ai_weight_bridge.flag` — register hooks (log-only Evaluate OK)
- `homm3_adventure_ai_weight_apply.flag` — mutate native scores

Without apply: compare sim preferred target vs native scores in logs only.

## What is already built

### Offline sim (`tools/olden_ai_sim`)

- World model: pathing (Dijkstra; `MoveCost` sole cell-cost authority when length-matched), fight estimate, economy, beam search, stepper, town build/hire/garrison (provisional costs)
- Clipped import API: `AdventureSimMapImport.FromClippedPathability` + `.aisim` IO
- GUI workbench: Evaluate / step back-forward; scenario `frontier_hold` (24×16) with towns
- Isolation gate: `tools/validate_olden_ai_sim_contract.py`
- Offline smoke: `python tools/olden_ai_sim/smoke_offline.py`

### Mod bridge (source)

| File | Role |
|------|------|
| `Homm3AdventureLookaheadState.cs` | Live Side → planner DTO → `AdventureSimState` |
| `Homm3AdventureAiWeightBridge.cs` | Day-start Evaluate + `ffe.bjsj` bias |
| `Homm3AdventureAiDecisionProbe.cs` | Read-only day snapshot (separate flag) |
| `GameSymbols.AdventureAiDecision` | Signature/hint pins for day controller / Side / marks / task scorer |
| `Homm3AiDriverBridge.AdventureCapture.cs` | Native MapData + session DataHero/DataSquad/DataObject adapter |

### What live capture **does** fill today

From `Side` on day start:

- Side index / name
- `SideAiData` marks (city/hero/object/node/squads/…)
- Resources from `Side.res`
- Live occupancy from `Data.squads.list` plus known `Data.objects` joined to `MapData.objects`; marks remain planner aims

## Live capture slice now implemented

### What is captured from current source/static pins

The day-start bridge calls `Homm3AiDriverBridge.TryCaptureAdventureLiveWorld` after the side-only capture. The adapter reuses the existing AI-driver map/session readers and records:

- `MapData.sizeX` / `sizeZ`, `tilesMap`, `roadsMap`, and `waterMap`, retaining native row-major node ids (`node = z * sizeX + x`) under a hard `MaxLiveMapCells` cap. This first slice uses the bounded full grid rather than clipping/remapping, because preserving world node identity is safer until clipped bias-key mapping is proven.
- A conservative land-pathability projection: positive non-void terrain, not a known water terrain code, and `waterMap[node] == 0`. This is a source/static projection, not proof of the engine's hidden pathfinder or water-travel rules.
- `OldenTileMp.FillMoveCost` output from the captured Core tile/road arrays. The table and formula remain **provisional**; no apply claim may use it yet.
- Live `DataHero` rows resolved from session data, including `node`, `worldMovePoints`, `mana`, and party unit SID/stack rows. Missing pose data is not replaced with 1500 MP or node 0.
- Actual `DataSquads.list` rows classified as NPC/neutral, plus known active `Data.objects` rows joined through `idMapObject` to `MapData.objects` nodes. Unknown object SIDs and unproven hero army strength are skipped rather than assigned fake values.

### Fail-closed behavior

`TryValidateForSimulation` requires a live map, exact arrays, live occupancy traversal, at least one hero, and a valid pose for every captured hero. The weight bridge clears any previous bias cache when capture or readiness fails. Log-only mode can evaluate a complete capture with the provisional movement table for diagnostics; the apply flag additionally refuses while `MoveCostProvisional` is true. Capture failures are logged as `FAILED_CLOSED`; there is no synthetic all-pathable grid and no placeholder hero path in the live bridge.

### Remaining uncertainty

The following are still not native/runtime-proven:

- The conservative land projection is not the engine's internal pathability array.
- The `OldenTileMp` formula has not been matched to the live movement consumer.
- Data-object SID classification covers only known town/mine/pickup/neutral vocabulary; unknowns are intentionally omitted.
- Party rows contain SIDs and counts, but per-stack engine value / army strength is not yet pinned.
- Full-grid capture is bounded, but no clipped-window identity remap is attempted.

### Target capture contract

Per AI side day start:

1. Resolve live map arrays and preserve world node ids under the cell cap.
2. Resolve each live hero row and reject incomplete node/MP pose data.
3. Walk live session squads and object rows; join map-object IDs to nodes; do not synthesize mark occupancy.
4. Build pathability and provisional movement costs before `ToSimState` / `Evaluate`.
5. Keep score mutation behind both the apply flag and a fresh readiness result; clear stale biases on any failed capture.

Performance bar: the adapter walks bounded native arrays and sparse session lists. It does not reflect per-cell Unity objects or remap the full grid.

### Ask-when-uncertain (do not invent)

Stop and ask / decomp-prove before guessing:

- Exact live pathability / move-cost arrays and how node index maps to xz
- Whether `worldMovePoints` consumer formula matches provisional `OldenTileMp` (`stepMp = round(100 * penalty / 0.4)`)
- Whether `ffe.bjsj` candidate identity (`cjqs` / `cjqt` / `fcp` / world-object id) is enough to key biases after clipped remapping
- Army strength: `fda.bjeg` vs `squadValue` × count

Use the `decomp-search` skill for branching native reads.

## Recommended next sequence

1. **Run validator/build checks** and inspect the generated plugin against the active Golden Era target.
2. **Golden Era startup smoke** (first runtime proof tier after source):
   - Deploy plugin + `OldenAiSim.dll`
   - Bridge flag only → logs `HoMM3 adventure AI weight bridge day` with non-synthetic grid dims and real hero nodes
   - Then apply flag → score multiply lines; confirm bias keys hit live candidates
3. Only after startup evidence: exercise a day-start capture and compare real hero nodes, map dimensions, occupancy counts, and task-key hits.
4. Only after runtime evidence: tune beam knobs / town costs against Core-proven numbers.

Do **not** start by rewriting enter-node or building L2 combat re-sim.

## Proof boundaries

| Claim | Status |
|-------|--------|
| Sim isolation + offline evaluate/GUI/`frontier_hold` | source/static (+ offline smoke when run) |
| Weight bridge registration / `bjsj` postfix source | source/static |
| Live marks/resources/hero-id capture code path | source/static; **runtime-unvalidated** |
| Live MapData arrays / conservative pathability / provisional MoveCost | source/static; **runtime-unvalidated** |
| Live hero pose and session occupancy adapter | source/static; **runtime-unvalidated** |
| Bias apply changes AI play | **unvalidated** |

Do not promote documentation to “deployed” or “runtime proven” without Golden Era log evidence.

## Key paths

```text
docs/ai_external_sim_weight_bridge.md
docs/ai_lookahead_requirements.md
docs/ai_decision_logic_surface.md
tools/olden_ai_sim/                  # OldenAiSim library + gui + tests
tools/validate_olden_ai_sim_contract.py
tools/validate_adventure_ai_lookahead_surface_contract.py
OfflineUnlockMod/Homm3AdventureLookaheadState.cs
OfflineUnlockMod/Homm3AdventureAiWeightBridge.cs
OfflineUnlockMod/Homm3AiDriverBridge.AdventureCapture.cs
OfflineUnlockMod/GameSymbols.cs      # AdventureAiDecision section
```

## Non-goals for this handoff slice

Fog-faithful search, Core-proven town build trees, spellbooks, L2 `eeo` combat inside the tree, rewriting `fjg.Invoke` / enter-node, replacing the JSON adventure state machine wholesale.
