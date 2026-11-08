# Mono → Live GE pin table (movement / occupancy)

Status: **static commit-store dossier finished** (Iteration 11 — 2026-07-20; Grok Phase 2 accept-with-fixes; **no Phase 3**). Stores + dest + publish field closed. Not gameplay proof. Not permission to re-enable MovementPush.

## Evidence roots

| Root | Role |
|---|---|
| `tmp/mono_demo_battle_semantic_index.txt` | Mono demo type/field/method names |
| `experiments/cpp2il_readable_csharp/samples/latest_refresh/demo_hex_*interest*.json` | Mono interest metadata (MechPushUnit / PushUnitStep / StepQueueProcessor present) |
| `experiments/cpp2il_readable_csharp/samples/latest_refresh/mono_deobf_semantic_map.json` | Broad map: `Hex`/`UnitData` strong-static by exact name; **MechPushUnit / PushUnitStep / StepQueueProcessor absent** from mapped rows (obfuscated live types) |
| `tools/il2cpp_out_20260719_golden_era/dump.cs` | Live GE DummyDll dump (fields, RVAs) |
| `experiments/direct_state_movement_trace/*.asm.txt` | Live GameAssembly Capstone |

## Pin table

| # | Mono (demo) | Live GE | Evidence label | Notes |
|---|---|---|---|---|
| 1 | `Hex.AddFieldObject(FieldObject)` | `Hex.bcyl(FieldObject)` RVA `0x1F33BA0` | **source/static** + **xref** | Declaration ordinal after corpse helpers; body adds to `fieldObjects` (`+0x28`) and may set `cfqg` (`+0x3A`). Called from `edf.bcuo`. |
| 1b | `Hex.RemoveObject(FieldObject)` | `Hex.bcyn(FieldObject)` RVA `0x1F33CB0` | **source/static** + **xref** | Sibling of `bcyl`; leave path inside `edf.bcuo`. |
| 1c | `Hex.OnRevive(Unit)` | `Hex.bcym(Unit)` RVA `0x1F33C90` | **source/static** (signature+ordinal) | Between add/remove; **not** push occupancy. Prior “clear-if-match occupant” reading is corpse/revive-shaped. |
| 1d | `Hex.IsLockedForSide(int, bool, ETargetAllegiance)` | `Hex.bcyf` RVA `0x1F334B0` | **source/static** (sig+body) | ORs `blockedFromAll`/`blockedByMap`/`tempBlocked` + `fieldObjects` virtual blockers. Push path: `true` → reject dest. |
| 2 | `UnitData.get_hex` / `set_hex` | `UnitData.bfdh` / `bfdi(Hex)` RVA `0x2078360` | **source/static** + **xref** | Tail methods before `.ctor`. `bfdi` body: `eep.bdhv` → `edf.bcuo` → `eep.bdhw`. |
| 2b | `FieldObjectData.get_hex` / `set_hex` | `edf.bcun` / `edf.bcuo(Hex)` RVA `0x1F055B0` | **source/static** | Field shape: `hex_`/`owner`/`position`/`isSummon`/`spawnedInBattle` ↔ `cfnq`/`cfnr`/`cfns`/`cfnt`/`cfnu`. |
| 2c | `CasterObject.get_hex` | `ede.bcuh()` | **source/static** / **xref** | Reads helper hex (`edf+0x10`); used by `bdhw` after store. |
| 3 | `MechPushUnit` | `ehh` | **source/static** | Factory case 37; fields 2×bool + 2×`List<Unit>` + `Dict<int,Hex>` + `List<Hex>` match `cgfy`/`cgfz`/`cgga`/`cggb`/`cggc`/`cggd`. |
| 3a | `MechPushUnit.pushInwards` | `ehh.cgfy` (`+0x28`) | **source/static** | Init store + `bdpe` use: direction scale −1.0 vs +1.0. |
| 3b | `MechPushUnit.skipCenter` | `ehh.cgfz` (`+0x29`) | **source/static** | Init store + `bdpe` use: only with `pushInwards` when dist metric `== 1` → `unitsToRemove`. |
| 3c | `MechPushUnit.ApplyForReceiver` | `ehh.bdpe` RVA `0x1FD4AC0` | **source/static** | Dest compute + enqueue only; no position store. |
| 3d | `MechPushUnit.Init(string[])` | `ehh.Init` RVA `0x1FD4740` (dup `izh`) | **source/static** | Body walked; two bool parses only. |
| 4 | `PushUnitStep` | `ejn` | **shape-static** | Fields `hexesToPushTo`/`walkers` ↔ `cgqv`/`cgqw`; `Begin`/`Process` ↔ `bdyi`/`bdyj`. Not uniform with `bcyl`/`bfdi` store-pin strength. |
| 4b | `StepQueueProcessor` | `ejr` | **shape-static** | Fields `turnSteps`/`cutBuffer`/`currentStep`/`OnFinishProcessing`/`processing` ↔ `cgrh`/`cgri`/`cgrj`/`cgrk`/`cgrl`. |
| 4c | `StepQueueProcessor.Push` | `ejr.bdyq(ejt, Unit)` | **shape-static** | Enqueue from `ehh.bdpe`. `InsertImmediate` ↔ `bdyr` remains **hypothesis**. |
| 5 | `BattleLogicEvents` | `eda` | **source/static** (shape) + GameSymbols | EventHandler prefix + 3 bools; action/round slot correlation. |
| 5v | `BattleViewEvents` | `edb` | **source/static** (shape) | 3 `ProfilerMarker`s + EventHandlers incl. `HotkeyAbilityArgs`. |
| 5a | `BattleLogicEvents.OnUnitChangedHex` | `eda.cfhz` (`+0xB8`) | **ordinal-inferred** | **Not** on `bdhw`/`bfdi` publish path. Prior `edb.cfkg` pin **withdrawn** (W11). Do not teach dump-era `cfkg`↔ChangedHex as live truth. |
| 5a′ | *(was)* `OnUnitChangedHex` → `edb.cfkg` | — | **contradicted** (live GE) | `edb.cfkg` ≈ View `OnCrit` (ordinal 21). |
| 5b | `BattleViewEvents.OnUnitPosChanged` / `UnitPosChanged` | *(view hub; not `bdhw` path)* | **hypothesis** vs live field | Mono view index 44; `bdhw` builds plain `BattleEventArgs`, not `UnitPosChangedEventArgs`. |
| 5c | `BattleLogicEvents.OnUnitStartedMovement` / walk start | `enb.bfcp` → `UnitStartedMovementEventArgs` | **source/static** | Push `ejn.bdyi` uses `enb.bfcr`/`emz` instead — **no** this event at Begin. |
| 5d | Push/walk **commit** publish | `eep.bdhw` → `eda.bcim` → `eda.cfia` (`+0xC0`) | **required** (call) + **ordinal-inferred** (name) | Mono name: Logic **`OnUnitEndedMovement`**. Solid ≠ ChangedHex / View PosChanged. Do not label ordinal-strong. |
| 5e | Logic `OnUnitEndedMovement` subscribers (mono) | `BhDrawerHelper` / `BhGatesHelper` handlers | **mono-index** | Live obfuscated type pins **open**. |
| 6 | Mono `Hex` Unit occupant property | **None** | **source/static** (live-negative for “occupant property”) | Mono fields: `fieldObjects`, `lastCorpse`, flags, neighbours. No `Unit` occupant. |
| 6b | `Hex.lastCorpse` get/set | `Hex.cfqf` / `bcxn`/`bcxo` (`+0x30`) | **source/static** (ordinal+type); M4 bar-C field-delta target as **corpse_store only** | First methods on live `Hex`. **Not** the push occupancy store. |
| 7 | `UnitData.set_sumHp` / stack write | `UnitData.bfde(int)` RVA `0x20781D0` (`bfdd` same VA) | **source/static** (ISIL); M4 field-delta | Writes `fullStacks(+0x34)`, `hpLastUnit(+0x40)`, clears flag `+0x50` on `<=0` |
| 7b | `UnitData.allStacks` / alive | `bfda()` / `bfdf()` | **source/static** (ISIL); M4 readback | Composition matches mono `allStacks` / living predicate |
| 6c | Live dual-write of `_cfqf` as occupancy | — | **live-negative** + **contradicted** | Push path never writes `cfqf`; DS recipe must use `bfdi` → `bcyn`/`bcyl` on `fieldObjects`. |

## DS recipe implication (static)

Minimal connected commit remains: invoke `UnitData.bfdi(dest)` (or ordered `bdhv` → `bcuo` → `bdhw`). Occupancy = **list** mutators `bcyn`/`bcyl`, not `cfqf`/`bcxo`. Dual-write helper+`cfqf` stays forbidden. Publish field = `eda.cfia` via `bdhw`→`bcim` (English name ordinal-inferred: Logic `OnUnitEndedMovement`).

## Remaining hypotheses (ordered; not Phase 3)

1. `emz` necessity for user-visible shove beyond `bfdi` store coherence (S45) — **runtime**.
2. Whether any path raises `eda.cfhz` (`OnUnitChangedHex`) on push/walk (not via `bdhw`).
3. Live type pins for `OnUnitEndedMovement` subscribers (`BhDrawerHelper` / `BhGatesHelper` or other).
4. Ordinal drift on English names (`eda` live 53 EventHandlers vs mono Logic 49).
5. Optional: mono `UnitData.set_hex` IL parity; full `ejr` method-name map beyond `Push`/`bdyq`.

MovementPush stays gated. No readiness claim.

## Related asm artifacts

- `Hex_bcyl.asm.txt`, `Hex_bcyn.asm.txt`, `Hex_bcxo.asm.txt`, `Hex_bcyf.asm.txt` *(Iteration 10)*
- `edf_bcuo.asm.txt`, `UnitData_bfdi.asm.txt`
- `eep_bdhv.asm.txt`, `eep_bdhw.asm.txt`, `eda_bcim.asm.txt`
- `ehh_Init.asm.txt`, `ehh_bdpe.asm.txt` *(Iteration 10)*
- `emz_bfbe.asm.txt`
