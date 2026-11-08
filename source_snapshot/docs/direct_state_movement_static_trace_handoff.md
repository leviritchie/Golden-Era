# Handoff: Direct-State Movement — Static Write-Body Trace Only

Status: **static commit-store dossier finished** (2026-07-20 Iteration 11 — Grok Phase 2 accept-with-fixes; **no Phase 3**). Stores + dest + publish field closed. Not gameplay proof. Not permission to ship MovementPush.

**What “finished” means here:** commit-store recipe + hub identity + dest predicate + `bdpe` bool uses + publish call/offset (`bdhw`→`eda.bcim`→`cfia`) are closed as a static dossier. English event names for `cfia`/`cfhz` remain **ordinal-inferred** (not ordinal-strong).

**Still open (not blocking this closeout; not Phase 3 static research):**

1. `emz` necessity for user-visible shove beyond `bfdi` store coherence (S45) — runtime.
2. Whether `eda.cfhz` (`OnUnitChangedHex`) fires on any push/walk path (not via `bdhw`).
3. Live obfuscated subscriber types for Logic `OnUnitEndedMovement` (mono: `BhDrawerHelper` / `BhGatesHelper`).
4. Ordinal drift risk on English names (`eda` live 53 handlers vs mono 49).
5. Optional: mono `UnitData.set_hex` IL parity; full `ejr` method-name map.

MovementPush remains gated. No readiness / live-positive claim.

Audience: the next agent may use the transaction recipe in `docs/direct_state_adapter_dossiers.md` § movement (claims S31–S45) as the **commit-store** owner. Do **not** treat this as permission to ship MovementPush; runtime proof remains required. Do **not** reopen donor restore.

## Why this handoff exists

Multiple iterations failed by **instruction drift**: agents treated “find native names” or “restore a Core donor” as the product, or treated partial field writes as success because CapLogs agreed with themselves.

The direct-state manager exists so custom mechanics can **own** battle mutations from a **connected write body**, without gambling on whether a donor envelope, bool packing, or timing happens to fire correctly. A native family that “exists in Core” and still fails in combat is exactly why the manager exists — not a reason to keep guessing at donors.

**User live-negative (2026-07-19):** restoring Bellwether `push_unit` on Golden Era Core did **not** deliver the intended shove. Treat donor restore as a failed experiment for this ability, not as the default path.

## Strict scope (in) — done; static research closed

1. Static tracing toward a direct-state **transaction recipe** (GE-pinned entry, ordered stores, readback, closure / named gaps).
2. Findings in `docs/battle_state_logic_map.md` + dossier section.
3. Obfuscated names only referenced as dump/DummyDll pins (no new scattered feature symbols required this pass).
4. **Iteration 9:** mono→live pin table under `experiments/direct_state_movement_trace/mono_live_pin_table.md`.
5. **Iteration 10:** `eda`/`edb` hub identity; `eda.cfia`≈`OnUnitEndedMovement` (ordinal-inferred); `ehh.bdpe` bool uses; `Hex.bcyf`=`IsLockedForSide`.
6. **Iteration 11:** Grok Phase 2 accept-with-fixes verified; historical `edb`≈Logic / `cfkg`↔ChangedHex docs bannered; handoff marked static-finished.

## Strict scope (out) — still out

- Re-enabling MovementPush / implementing combat writes (unless user expands scope after a runtime pass).
- Method_N event invent; mid-damage hex mutation; donor restore as primary solution.
- Claiming readiness or user-visible shove from static work alone.
- Further static Phase 3 research agenda (declined after Phase 2 review).

## Non-negotiable proof bar (connected write body)

Still required before shipping. Static work closed the **store** chain and dest/publish field identity; **runtime behavior proven** remains future work.

## Already known + closed this pass

| Step | Live GE | Mono alias | Role |
|---|---|---|---|
| Config | `push_unit` → `EMechType.PushUnit = 37` | same asset spelling | Asset spelling |
| Factory | `egd.bdpz` jump table case 37 | → **`ehh`** = `MechPushUnit` | Constructs **`ehh`** |
| Init bools | `ehh.cgfy`/`cgfz` | `pushInwards`/`skipCenter` | Parsed in `ehh.Init`; **uses in `bdpe` closed** (S43) |
| Apply | `ehh.bdpe` | `ApplyForReceiver` | Dest via neighbours + `Hex.bcyf`; **no** direct position store |
| Dest gate | `Hex.bcyf` | `IsLockedForSide` | Map/all/temp blocked + `fieldObjects` |
| Queue | `ejn` + `ejr.bdyq` | `PushUnitStep` / `StepQueueProcessor.Push` (**shape-static**) | Step queue |
| Begin | `ejn.bdyi` → `enb.bfcr` → `emz` | not walk `UnitStartedMovement` | Presentation path |
| Commit | `UnitData.bfdi(Hex)` | `UnitData.set_hex` | Ordered: `eep.bdhv` → **`edf.bcuo`** → `eep.bdhw` |
| Position store | `edf.bcuo(Hex)` | `FieldObjectData.set_hex` | Stores `edf+0x10`; leave/enter via **`Hex.bcyn`/`bcyl`** |
| List occupancy | `bcyn` / `bcyl` | `RemoveObject` / `AddFieldObject` | **Closed** push-path occupancy |
| Notify / publish | `bdhv` / `bdhw` → `eda.bcim`→`cfia` | leave/enter listeners; Logic **`OnUnitEndedMovement`** (ordinal-inferred) | Not occupant writers |
| Hubs | `eda` / `edb` | `BattleLogicEvents` / `BattleViewEvents` | Distinct (S40) |
| Unit field `cfqf`/`bcxo` | `Hex+0x30` | mono **`lastCorpse`** | **Not** occupancy; not on push path |

**Withdrawn:** vacated-enemy-hex (S5); Method_N invent; MovementPush dual-write substitute (W3); PushUnit as `bdom` (W7); donor restore as product (W8); occupancy inside `bdhv`/`bdhw` or via `bcxo` (W9); `cfqf` as Unit occupant (W10); live `OnUnitChangedHex`=`edb.cfkg` (W11).

## Deliverable answers (dossier)

Full write-up: `docs/direct_state_adapter_dossiers.md` § movement. Pins: `experiments/direct_state_movement_trace/mono_live_pin_table.md`.

1. **Minimal ordered store set:** invoke `UnitData.bfdi(dest)` on the defender (or expand `bdhv(old) → bcuo(dest) → bdhw(new)`). Inside `bcuo`: `bcyn` → helper store → `bcyl`.
2. **Required vs hypothesis:** required = `bfdi` / that triad + `fieldObjects` updates + `bdhw`→`cfia` call/offset. Hypothesis = English name certainty under ordinal drift; `emz` for user-visible shove; live subscriber type pins; whether `cfhz` fires.
3. **Preconditions:** non-null Unit/`UnitData`/helper/`eep`; dest ≠ current; dest not `IsLockedForSide`; no illegal stack; native identity equality; not mid-damage as design owner.
4. **Rollback:** prefer one journaled `bfdi` invoke. If split and `bcuo` succeeded without `bdhw`, restore with `bcuo(oldHex)` and CapLog — no second silent write path.
5. **What not to call:** helper+`cfqf` dual-write; Method_N publish; donor restore; `edf.bcuo` alone; `Hex.bcxo` pokes as ownership.

## Static lane status

**Static commit-store dossier finished.** Remaining items above are runtime / English-name / optional parity — not a further static research phase.

Do not treat dump-era `docs/edb_dxy_mono_xref_surface_mapping.md` (`edb`≈Logic, `cfkg`↔ChangedHex) as live GE movement publish truth; see banner there + battle map S40–S45 / W11.

## Current tree state (unchanged gates)

- `Homm3DirectStateAdapters.TryMove` still gates `MovementPush` / `MovementTeleport`.
- `Homm3DirectStateUnitHexNative.TryMoveUnitHex` remains incomplete dual-write — do not route production push through it.
- Disasm artifacts: `experiments/direct_state_movement_trace/`.

## Success criteria for *this* handoff

- [x] Commit-store recipe closed: another agent can target journaled `UnitData.bfdi` (or `bdhv`→`bcuo`→`bdhw`) without rediscovering dual-write / `cfqf` pitfalls.
- [x] Phase 2 static agenda closed (hubs, `cfia` name as ordinal-inferred, `bdpe` bools, dest predicate).
- [x] Static commit-store dossier finished (stores + dest + publish field); remaining = runtime/`emz`/ordinal English names only.
- [x] No CapLog “committed” claim, no Core donor “fix,” no readiness language.
- [x] Contradiction pass recorded (iteration 8–11; W8/W9/W10/W11).
- [x] Mono→live pin table left as reusable package.
- [x] No Phase 3 static agenda (Grok Phase 2 accept-with-fixes).

## Next handoff (runtime only — when user expands scope)

Implement journaled `UnitData.bfdi` (or full triad) behind the existing gate; prove helper + `fieldObjects` readback; then decide `emz` necessity for user-visible shove. Still fail closed until live-positive. Do not reopen donor restore.
