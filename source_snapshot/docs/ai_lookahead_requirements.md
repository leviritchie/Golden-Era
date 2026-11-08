# Adventure Lookahead — What Would Actually Be Required

Date: 2026-07-11  
Evidence: **source/static** (Golden Era DummyDll ILSpy + Core.zip `DB/ai_world`).  
Runtime: **unvalidated**. Battle picker probes are out of scope here.

Parent catalog: [`ai_homm55_parity_investigation.md`](ai_homm55_parity_investigation.md).  
Pipeline map dumps: `tmp/ai_lookahead_decomp/`.

## What “lookahead” means here

Heroes 5.5 (Quantomas) evaluates **trees of hero actions across N future days**, then commits only the first real action. Depth is a budget knob.

Olden’s adventure AI is a **one-day JSON state machine**:

```
fcy side → fjj controller → fhk locator (AiConfig)
  → fjl.OnStartDay
    → fjm strategies (conditions + SideAiData marks)
      → fji / fjg.Invoke side-action batches
      → fih roles → ffe task candidates → ffe.bjsj score → fjp.bjzf pick
      → fjj.bjxq enter-node (movement commit)
```

There is **no** `lookahead` field, no world fork API, and **no** adventure call into battle simulation when choosing whether to fight. Fight willingness is `TaskInfo.fightMultipler` + `fda` army-value helpers + JSON conditions.

So a real lookahead system is **new software bolted onto** this pipeline, not a Core.zip toggle.

---

## Decision: three implementation tiers

| Tier | Name | Commit path | Combat model | Honesty vs 5.5 |
|------|------|-------------|--------------|----------------|
| **L0** | Pseudo-horizon | Keep native `fjl`; reshape marks/scores | None / existing `fightMultipler` | Calendar + bias only |
| **L1** | Heuristic search | Intercept day start / task pick; choose first action; let native execute | `fda.bjeg` + `squadValue` × stacks × `DifficultyAi` scalars | Search over abstract state; fight outcomes approximate |
| **L2** | Faithful re-sim | Same as L1, but combat edges call real auto-battle | `TransferBattle` + `efe.bdmo` → `eeo` step loop (`EPlayedType.Simulated`) | Closest to 5.5; expensive; Unity-thread-bound |

**User assumption (neutrals → autobattle):** L1 is the practical default; L2 is only for fights where heuristic error would change the plan (hero vs hero, town siege, or when L1 repeatedly mis-ranks).

## Locked design choice (2026-07-12)

**Mark-centric + omniscient** for the first forkable planner state.

| Axis | Choice | Meaning |
|------|--------|---------|
| State / actions | **Mark-centric** | Fork ≈ `SideAiData` aims + heroes/MP/army + resources + thin occupancy; actions change or advance marks, not free board moves |
| Information | **Omniscient** | Planner sees neutrals/towns/heroes without copying `Side.fogData.visibilityMap`; fog-faithful is an optional later fidelity pass |

Rationale: native adventure AI already routes intent through marks; omniscient avoids per-branch fog COW and scout-as-action branching. Day-0 commit prefers writing marks so native `fjl`/`ffe` still owns legality and pathing.

Out of scope until this slice works: entity-centric board search, fog-matched candidate sets, L2 `eeo` inside the tree.

### v1 shipped (2026-07-12) — observe + DTO only

| Artifact | Role |
|----------|------|
| `GameSymbols.AdventureAiDecision` | `fjl`/`fhk`/`Side`/`SideAiData` mark hints |
| `Homm3AdventureLookaheadState` | Cloneable mark-centric fork (`homm3.adventure.lookahead_state.v1`); no fog copy |
| `Homm3AdventureAiDecisionProbe` | Flag `homm3_adventure_ai_decision_probe.flag`; read-only `OnStartDay` postfix |
| `tools/validate_adventure_ai_lookahead_surface_contract.py` | Fail-closed static contract |

### Active product path (2026-07-18) — external sim + score weights

See [`ai_external_sim_weight_bridge.md`](ai_external_sim_weight_bridge.md).

- Separate managed lib: `tools/olden_ai_sim` (`OldenAiSim.dll`)
- Write path: Harmony on `ffe.bjsj` bias multipliers (not enter-node rewrite)
- Flags: `homm3_adventure_ai_weight_bridge.flag` / `homm3_adventure_ai_weight_apply.flag`

Runtime capture path (`fjl` → `cjwl` → `cofk` → `codp` → `Side.aiData`) and weight apply remain **runtime-unvalidated** until Golden Era smoke.

---

## L1 — Required work packages

### 1. Observation / injection choke points (Harmony)

Must resolve by **signature** (live interop renames short names):

| Priority | Type.method | Why |
|----------|-------------|-----|
| P0 | `fjl.OnStartDay()` | Day boundary; only safe place to run a planner before native commits |
| P0 | `fjp.bjzf(eta, fbq, float)` and/or `ffe.bjsj(...)` | Hero task pick / score — where “go fight X vs go to Y” is decided |
| P1 | `fjg.Invoke()` / `fji` batch runner | Side marks (`markEnemyHero…`, `selectAreaToExpand`) that bias later tasks |
| P1 | `fjj.bjxq(eta, int) → EEnterNodeResult` | Final movement commit; last chance to redirect |
| P2 | `Side.aiData` (`SideAiData`) | Planner can write marks instead of replacing the whole SM |

Without at least P0+P0 (day + task pick), you cannot replace decisions; you can only nudge JSON.

**Blocker:** DummyDll bodies are empty. Exact `OnStartDay` orchestration (strategy order, human-turn lock, multi-hero sequencing) needs ISIL/disasm before claiming a safe insert point.

### 2. Abstract world state (must build; no native clone)

Olden has **no** `Clone` / `Snapshot` / dry-run enter-node. A planner must maintain its **own** forkable state.

Minimal state for **one AI side, depth D days, branching factor K**:

| Bucket | Fields / sources |
|--------|------------------|
| Calendar | Day / week / month (drives `dayFromStart`, week sets) |
| `SideAiData` | All marks: `markedCity`, `markedHero`, `markedObject`, `markedNode`, `markedSquads`, `makredEnemyCity`, courier/upgrade cities, `markedAreaGuard`, `hardStrategy`, `areasReachable`/`areasLastOpen`, `blockedAreas`, `bannedAreas`/`bannedAreasMap`, `objectPerGame`/`objectPerWeek`, `buildingColdown`, hire/death flags |
| Economy | Resources, owned cities, build cooldown (`DifficultyAi.buildingColdown`) |
| Heroes | Per hero: node, remaining MP, army (`fbq` stacks), mana, role id |
| Map graph | Pathable neighbors, terrain MP cost, portals, fog (`DataFogOfWar` / AI scouting) |
| Objects | Neutrals (`DataSquad.startValue`, `isAutobattle`), mines, pickups, dwellings — at least for visible nodes |
| Enemies | Known enemy heroes/cities (fog-respecting or explicit cheat) |
| Difficulty | `valuesVsMobsMultiplier`, `heroPowerMultipler`, `blockAreaByEnemyMultiplier`, `tempStacksMultiplier`, `battleScript` |
| Strategy memory | Active `AiConfigStrategy` id + which action-batch phase completed |

**Cost reality:** state size × `K^D` (or beam width × D). Even with aggressive pruning this is the dominant engineering surface.

### 3. Action generator (candidate set)

Do **not** invent a free-form action language first. Reuse Olden’s native vocabulary:

**Side actions** (from Core `DB/ai_world/ai/*.json`):  
`buffSide`, `cityBuilder`, `cityHireGarnison`, `garisonUnitsUpgrade`, `learnFractionLaw`, `mark*`, `selectAreaToExpand`, `selectKeyObjectInFreeArea`, `removeWeakUnits`, `surrenderIfWeak`, …

**Hero tasks** (`EHeroAiTarget` / task JSON):  
`PickupObject`, `AttackHero`, `AttackHeroYolo`, `CaptureCity`, `HireUnits`, `TakeGarnison`, `AttackMarkedHero`, …

**Blocker:** SID → concrete `fjg` subclass mapping lives in native `fjh.bjvu` (only 6 subclasses `fja`–`fjf` in DummyDll; SIDs are **not** string-literal in `Hex.dll`). Planner can either:

- **A)** Generate abstract ops that mirror task targets and apply mark/move/fight transitions in the abstract state, or  
- **B)** Call native `Invoke` on a forked world (impossible without world fork).

**L1 requires A.** Mapping must be hand-built from JSON + observed `SideAiData` diffs (adventure probe), not assumed from DummyDll.

### 4. Transition model (how one action advances the fork)

For each candidate action, the abstract apply step must update:

1. **Movement:** path length vs MP (`TaskInfo.movePoints`, `ffb` area floats, `fjq`/`fev` path cache semantics — currently live-state only).  
2. **Interaction:** pickup / capture / hire effects on resources and army.  
3. **Combat edge:** see §5.  
4. **End of day:** regenerate MP, income, growth, `buildingColdown`, week clears — enough to make day N+1 conditions meaningful.

Anything omitted becomes systematic planner bias (e.g. ignoring income → undervalues cities).

### 5. Combat model under “neutrals autobattle”

| Fight class | Recommended L1 model | When to escalate to L2 |
|-------------|----------------------|------------------------|
| Neutral / map guard (`DataSquad.isAutobattle`) | Compare `fda.bjeg(army)` vs `startValue`/`squadValue`×count, scaled by `valuesVsMobsMultiplier` / `heroPowerMultipler`; apply expected losses from a fixed casualty curve | Heuristic flips win/loss vs live autobattle often enough to change plans |
| Player-facing auto-battle UI | Same as above for planning; live game still runs `EPlayedType.Simulated` | — |
| Enemy hero / town | Heuristic is weak | Prefer L2 or refuse deep plans that depend on that edge |

**There is no** `EstimateCombat` / `WillWin` API. In-battle `dye.batd` power helpers need live `Unit` lists inside `eeo` — not adventure-map callable.

**L2 combat (if needed):**

```
build TransferBattle (sides, seed, difficultyAi, playedType=Simulated)
efe.bdmo(TransferBattle, eds, controlledByAi, …) → eeo
eeo.Init(id, TransferBattle, controlledByAi: true, …)
step until BattleResultInfo / TransferSide stacks settle
eff.bdol(eeo, showNotification: false)  // only on the FORK, never live session
```

Static precedent: `BhUnitTest` harness (`docs/surface_xref_trees/native_battle_unit_test_harness_static_route.md`) — naming drifted (`eff.bdpj`/`eep` → current **`efe.bdmo`/`eeo`**). **Runtime-unvalidated.**

Constraints if L2 is used inside search:

- Must not mutate the live session (`eff.bdol` on real `eeo` is catastrophic).  
- Must run on Unity main thread; budget `sims_per_day_start`.  
- Must fix `randomSeed` for reproducibility.  
- Autobattle quality still depends on `DifficultyAi.battleScript` / `BattleAiParams` — separate from adventure lookahead.

### 6. Search algorithm + evaluation

| Piece | Requirement |
|-------|-------------|
| Search | Beam / best-first / limited DFS with depth `D` and width `W` (expose as mod knobs analogous to 5.5 depth) |
| Node eval | Weighted utility: towns owned, resources, hero army value (`fda`), map control, enemy threat, script `flatValue` alignment |
| Opponent model | At minimum: static enemies; better: one-ply “enemy takes obvious town/hero” |
| Fog policy | Match AI fog (`fjw`) **or** explicit omniscient cheat (label it) |
| Time budget | Cap wall-clock at day start; fail closed to native `fjl` if exceeded |
| Multi-hero | Joint assignment or sequential heroes with shared marks — native uses `stepOrder` / `valuesGiver`; planner must not ignore courier roles |

### 7. Commit bridge (apply only day-0 first action)

After search, map the winning root action back into something native will execute:

| Preferred | Mechanism |
|-----------|-----------|
| Soft | Write `SideAiData` marks + boost matching task scores so native pick converges |
| Hard | Harmony prefix on `fjp.bjzf` / `fjj.bjxq` forces the chosen target node / task |

Soft is safer (native still owns legality). Hard is more faithful to the plan but fights `NeedMoveFrame` / `fel` async movement.

### 8. Validation / fail-closed

- Adventure decision probe (read-only) logging: strategy id, marks, top-N `ffe` scores, chosen enter-node — **before** enabling planner.  
- Diff: planner choice vs native choice for N days (offline log).  
- Never enable L2 apply on live world.  
- Symbol contract + signature resolution (same pattern as battle surface).

---

## Effort sketch (honest)

| Package | Rough size | Depends on |
|---------|------------|------------|
| Adventure observation probe | Small | Signatures only |
| Abstract state + fork | Large | Domain model design |
| Action catalog from JSON + mark diffs | Medium | Probe traces |
| Transitions (move/economy/day) | Large | Path/MP fidelity |
| L1 combat curve | Small–medium | Calibration vs live autobattle |
| Search + eval + knobs | Medium | State/actions |
| Soft commit via marks | Small–medium | Eval quality |
| Hard commit Harmony | Medium | `fel`/`NeedMoveFrame` understanding |
| L2 isolated battle sim | Large | Threading + isolation proof |
| Opponent + fog fidelity | Medium–large | Optional later |

**Order that actually de-risks lookahead:**  
probe → mark/score soft steering (L0) → abstract state + L1 combat → search → soft commit → only then L2.

Skipping straight to “Quantomas port” without abstract state + L1 combat calibration will produce plans that native movement/combat refuse.

---

## What is *not* required (given autobattle neutrals)

- Battle `dyt.bavi` probes / in-combat policy work for the lookahead *planner* itself.  
- Shipping a lobby “lookahead depth” JSON field in Core (engine won’t read it).  
- Cloning `MapData` / full session objects if the abstract state covers planner-relevant facts.  
- Perfect spell-level combat for every neutral (L1 curve + occasional L2 is enough if calibrated).

---

## Biggest fail-closed blockers (today)

1. Empty DummyDll bodies for `fjl.OnStartDay` / `fjh.bjvu` — need ISIL before hard inject.  
2. No world fork — abstract state is mandatory.  
3. SID→`fjg` mapping opaque — build from JSON + runtime diffs.  
4. No headless `EstimateCombat` — choose L1 curve vs L2 `eeo` isolation.  
5. `NeedMoveFrame` async — hard redirects can desync mid-batch.  
6. Unity main-thread budget — depth×width×(optional sims) must be capped.

---

## Bottom line

A 5.5-style lookahead on Olden is a **planner process** that:

1. Runs at **`fjl.OnStartDay`**,  
2. Searches over an **abstract fork** of side/map/marks/heroes,  
3. Resolves fights with a **calibrated autobattle heuristic** (escalating to isolated `eeo` only when needed),  
4. Commits by **steering or forcing** the native task/move pick for day 0 only.

Until (2) and (3) exist, “lookahead depth” is not a feature — it is a wish. The cheapest proof of concept is L0/L1 soft steering with a tiny depth (D=2, narrow beam) against Homecoming neutrals, measured against native logs.
