# Direct-State Adapter Dossiers

Status: source/static validated only unless a row below cites a later focused runtime record. These dossiers document the single implementation route for each family; they do not promote gameplay proof.

## Shared transaction and binding contract

- Dispatcher: `Homm3DirectStateIngressDispatcher` (routing-only) after surface normalization; adapters still commit through `BattleCombatTransactionManager` / `NativeCombatWriteGateway`.
- Surface normalizer: `Homm3BattleEventNativeAdapter` partials keyed by `Homm3DirectStateHookSurface` (`ingressWaveMap` in `homm3_adapter_manifest.json` lists all 15 adapters).
- Atomic owner: `BattleCombatTransactionManager`.
- Native writer: `NativeCombatWriteGateway` via `ICombatWriteBackend` (Live production / Model headless replay).
- Generation/family state: `Homm3BattleLocalLawState` direct-state partials.
- Hook owner: `Homm3RuntimeMechanicHooks` (thin shells only).
- Stable contract: `Homm3DirectStateAdapterManifest` plus `homm3_adapter_manifest.json`.
- Fixed caps: root work 64, depth 8, journal 64, fan-out 16, dirty identities 32, queue span 32.
- Event semantics: authoritative state exactly once; native gameplay invocation at most once; presentation-only retry tokens.
- Proof lanes stay separate: headless replay = `source-replay-validated`; mining = `ingress-shape-capture-only`; neither auto-promotes to user-visible gameplay proof.

### Damage-method argument dossier (mandatory for damage-triggered adapters)

The eight-argument `Unit` damage method is typed, but the managed args are not already battle-unit / ability identities:

| Arg | Role | Binding rule |
|-----|------|--------------|
| `__instance` | Damage receiver | Concrete `Hex.Session.Battle.Unit`; classifier and hex reads work directly. |
| `__0` | Attacker / caster | Generated `eab` interface. Must unwrap to `Unit` before `Classify` or SID lookup (Il2Cpp `Unit` wrap, FieldObject self via `BuffReceiverObjectMembers`, or law-owner registry pointer match). |
| `__1` / `__2` | Cast-source / dealer context | Ability name may live on either arg or behind `DamageCastSource.PrimaryDamageDealerGetters`. Match display text **and** lang-key forms (`Shoulder Check`, `*abilities_0*`, tokens containing `shoulder`). |
| `__3` | Committed damage `int` | Positive damage gate only after identity resolve. |

`DamageApplied` postfixes also require the typed damage **prefix** so Harmony `__state` is set `true`. A DamageApplied-only registration without that prefix silently no-ops.

Planning failure to avoid: equating “hook registered + unit SID selected” with “caster/ability binding works.” Silent early-return on unresolved identity is a contract violation; cap-log the reject. Live proof requires commit or named reject, not startup `PREPARED_MECHANICS` alone. Full narrative: `docs/runtime_mechanics_implementation_handoff.md` § Damage-hook identity binding.

## damage

- Exact producer: generated eight-argument `Hex.Session.Battle.Unit` damage method in `GameSymbols.BattleEventLaws.BattleUnitApplyDamage`.
- Direct write: `ref int` committed damage through `NativeCombatWriteGateway`. No journal opcode is recorded for the scalar path (pre-commit mutation; restore of `DamageScalar` is a no-op).
- Side-effect stores (M4 card `damage.side_effect.bfde_v1`, **equivalence-proven** 2026-07-20): `UnitData.bfde` writes `fullStacks(+0x34)` / `hpLastUnit(+0x40)`; `bfda`/`bfdf` readbacks; `Hex.bcxo`/`bcxn` = lastCorpse (**corpse_store only**, not occupancy). Symbols: `GameSymbols.DirectStateLaws.UnitDataSumHpWriteMembers` / `HexLastCorpse*Members`.
- Rollback: pre-commit scalar restoration plus one-shot unit/side consumption restoration.
- Proof: M4 bar-C field-delta for declared side-effect stores; DamageScalar gateway source-replay corroboration only. User-visible damage remains runtime-unvalidated for this expansion.

## cast

- Exact producer context: `CastAbilityEventArgs` constructor and typed `CastAbilityEventInfo`.
- State: per-caster committed cast count.
- Child work: `Homm3DirectCastRequest` carries one exact method/target/argument shape and drains outside the root lock.
- Proof: source/static validated; exact follow-up cast behavior is runtime-unvalidated.

## resource

- Focus binding: side energy manager through `GameSymbols.FocusLaws.SideEnergyManagerMembers`; authoritative energy slot through `GameSymbols.DirectStateLaws.FocusValueMembers`.
- Cooldown binding: the active Golden Era `eew`/`ObjectPublicObcfInStcfInObcnMacfUnique` `cfxk` slot maps to generated writable `field_Public_Int32_0`; unit ability `dxy`/`ObjectPublicObceInBoInceAbObELInUnique` maps its direct `ceit` cooldown to `_ceit_k__BackingField`. Activation preflights these direct storage members rather than depending on stale helper-method aliases.
- Operations: Focus grant/spend/set and cooldown set/reduce/increase/charges/cast-counter.
- Proof: prior Focus grant and cooldown read surfaces are decomp/live-bridge sourced; direct field mutation remains runtime-unvalidated.

## status

- Identity: exact case-sensitive SID and receiver identity.
- Policy: `ManagerAuthoritativeNoNativeInventory`. There is no silent native-buff fallback.
- Operations: apply, refresh, tick, expire, remove.
- Composition: other direct-state families consume manager status state; native buff inventory is not treated as authoritative.
- Proof: source/static validated; status gameplay and presentation are runtime-unvalidated.

## movement

Status: **Product Shoulder Check redesigned 2026-07-20 to Schism Command: Fear shape** — native `teleport` via `arbitrator:abilities:1`, ordered enemy+hex cast, `distanceFromFirst=1`. Prior adjacent `push_unit` away and DS mid-damage `bfdi` pilots withdrawn for product. DS MovementPush pilot remains disabled. M3/M6 store cards remain diagnostic-only.

### Shoulder Check (one-hex shove) — decomp-primary recipe

Motivating intent: push **defender** one hex **away from attacker**.

**Product ownership (decomp):** config mechanic `push_unit` / `EMechType.PushUnit=37` → live factory `egd.bdpz` → `ehh` (`MechPushUnit`) → `ehh.bdpe` (dest; `pushInwards=false` → away) → `ejn`/`ejr` step queue → `enb.bfcr` → **`emz`** (world tween) → `UnitData.bfdi` (store commit). Do not strip `push_unit` for product. Do not treat store dual-readback CapLogs as user-visible shove (S45).

**Envelope:** adjacent single-target cast+damage (`attack_single_x100`, shootRange 1). Not Sticky Tongue hex-select pull. Donor `giant_frog:abilities:1` supplies Focus/cost/animation only; reshape replaces targeting + mechanics.

| Step | Live GE | Mono alias | Role | Product? |
|---|---|---|---|---|
| Mech factory | `egd.bdpz` case 37 | → `MechPushUnit` | Constructs `ehh` | **Required** |
| Dest apply | `ehh.bdpe` | `ApplyForReceiver` | Neighbours + `Hex.bcyf`; enqueue `ejn` | **Required** |
| Presentation | `ejn`→`enb.bfcr`→`emz` | PushUnitStep → tween | World position then `bfdi` at end | **Required** for visible shove |
| Commit owner | `UnitData.bfdi(Hex)` | `UnitData.set_hex` | Position + `fieldObjects` via `bcuo`/`bcyl`/`bcyn` | **Required** (native via `emz`) |
| DS mid-damage `bfdi` alone | — | — | Store coherence only | **Not product** |

**Withdrawn product path:** `stripForDirectState` + `diagnostic.bellwether_shoulder_check` MovementPush (store CapLog trusted as combat). Re-enable only as explicit store diagnostic.

**Readback map**

| Store | Mono alias | Reader |
|---|---|---|
| `edf+0x10` (via `bcuo` / `bcun`) | `FieldObjectData.hex_` | `ede.bcuh` / `CasterObject.get_hex` |
| `Hex.fieldObjects` (`+0x28`) via `bcyl`/`bcyn` | `AddFieldObject` / `RemoveObject` | Occupancy / blocking + `cfqg` (`+0x3A`) |
| `eda.cfia` via `bdhw`→`bcim` | Logic `OnUnitEndedMovement` | Mono subscribers: `BhDrawerHelper` / `BhGatesHelper` (live types open) |
| Dest gate | `Hex.bcyf` / `IsLockedForSide` | `blockedByMap` / `blockedFromAll` / `tempBlocked` + `fieldObjects` |
| `Hex.cfqf` (`+0x30`) | `lastCorpse` | Corpse / mod `_cfqf` reads — **not** push write target |

**Preconditions (fail closed)**

- Defender `Unit` / `UnitData` / position helper / `eep` non-null.
- Dest hex ≠ current helper hex (native `bfdi` no-ops when equal).
- Dest passable: `Hex.bcyf(side, ignoreUnits:false, alleg:2)` must be **false** (not locked); reject occupied-by-blocking-object for Shoulder Check unless a later claim proves stacking.
- Identity: native equality for Unit/Hex wraps (not `ReferenceEquals`).
- Lifecycle: not mid-`DamageApplied` as the design owner (donor/envelope mismatch); dest must be known before commit.

**Rollback**

- Prefer **one** journaled invoke of `UnitData.bfdi`. Native body is not a three-way atomic API if split: if step 2 (`bcuo`) runs and step 3 (`bdhw`) is skipped, helper/`fieldObjects` moved without post-publish.
- If expanding: snapshot before commit — old helper hex, old/new `fieldObjects` membership for the unit, and whether `bdhw` ran. On failure after `bcuo`, restore by `bcuo(oldHex)` (re-enter old list / leave new) then CapLog; do not invent a second write path.
- Do not claim CapLog “committed” unless readback of helper hex **and** `fieldObjects` membership agree.

**What not to call / ship**

- Mid-damage journaled `UnitData.bfdi` alone as product Shoulder Check (store ≠ view — S45).
- `Homm3DirectStateUnitHexNative.TryMoveUnitHex` helper+`cfqf` dual-write as production MovementPush.
- Method_N / ordinal event invent (`OnUnitChangedHex`, guessed `bcqv` mapping).
- Sticky Tongue hex-select pull envelope as Shoulder Check targeting.
- Direct `edf.bcuo` alone without `bdhv`/`bdhw` bracket.
- Direct `Hex.bcxo` / `_cfqf` pokes as occupancy ownership.

### Supporting notes

- Unit/Hex reads: `BattleObjectHexMembers`, `HexIndexMembers`, `HexXMembers`, `HexZMembers`. Neighbours: native Hex neighbour **fields** via `Homm3DirectStateHexNeighbourNative` / `HexNeighbourFieldMembers` (`_cfqh`…`_cfqm`). Do **not** Invoke Hex neighbour getters (live AccessViolation).
- Product shell: `restoreNativeMechanic` keeps `push_unit` `["false"]` under adjacent cast+damage reshape. `diagnostic.bellwether_shoulder_check` MovementPush stays **disabled**.
- DS cards `movement.commit.bfdi_v1` / interim dest remain store/diagnostic tooling; MovementPush/Teleport ungates are for manager relocate tests, not Bellwether product presentation.
- Mono→live pin table: `experiments/direct_state_movement_trace/mono_live_pin_table.md`.
- Pull remains CapLogged unsupported.
- Proof: native push chain source/static (S22–S27); `emz.bfbe` tweens world then calls `bfdi` (asm); product combat live-positive pending after Core overlay regen with restored mechanic.

## lifecycle

- Summon: construct exact runtime type, invoke exact `Init` shape, and insert into a journaled owner collection.
- Trap: manager-authoritative armed/triggered/despawned record keyed by stable battle-generation ID.
- Corpse: manager-authoritative create/consume record with unit, hex, owner side, and death sequence.
- Raise: one capacity-reserved transaction composes corpse consumption and summon creation; it is not a separate adapter.
- Proof: source/static validated; native view/side/occupancy reconciliation remains runtime-unvalidated.

## nestedDamage

- Redirection: pre-commit receiver map; the original call is skipped and the exact eight-argument damage method is invoked at most once on the redirect target. Failed invocation does not fall back to the original target.
- Reflection/splash: bounded post-primary `Homm3DirectDamageRequest` child work sharing the root budget.
- Recursion: a thread-scoped redirection guard prevents redirect loops while the root depth/work caps bound child chains.
- Journal: none (same pre-commit scalar lane as damage; do not claim `DamageScalar` entries).
- Proof: source/static validated; ordering against destruction remains runtime-unvalidated.

## kill

- Exact producer context: `ObjectDestroyedEventArgs`.
- State: append-only generation-scoped kill records plus independently identified ally-death records.
- Events: correlation tokens are claimed transactionally before any at-most-once native invocation.
- Corpse eligibility composes with the lifecycle family.
- Proof: source/static validated; kill/reflection/corpse ordering remains runtime-unvalidated.

## action

- State/write: bounded native queue list snapshot, insert, and remove through `NativeCombatWriteGateway`.
- Trigger: exact Golden Era `eda` action-start/action-end dispatchers (event slots 5/6) carry typed base `BattleEventArgs`; the specialized EventArgs classes assumed by the initial source slice do not exist in the active interop.
- Identity: `actionQueue` has a stable AdapterId separate from `turnOrder`.
- Proof: source/static validated; authoritative queue member binding and derived-view refresh remain runtime-unvalidated.

## turnOrder

- State/write: bounded list reorder/splice with one snapshot and a maximum span of 32.
- Trigger: exact Golden Era `eda` round-start/round-end dispatchers (event slots 8/9) carry typed base `BattleEventArgs`.
- Symbols: action-entry type/unit/turn-state and battle-logic queue candidates are centralized under `GameSymbols.DirectStateLaws`.
- Proof: source/static validated; current Golden Era authoritative queue ownership remains runtime-unvalidated.

## aura

- State: manager-owned aura definition, source, side, radius, effect SID, and unique member identities.
- Reconciliation: movement/spawn/death/round typed contexts mark bounded dirty identities; membership replacement is atomic and capped at 32.
- Effects: auras compose existing typed mutations and do not invoke native propagators.
- Proof: source/static validated; live membership and presentation remain runtime-unvalidated.

## Conflict and cleanup audit

`Homm3DirectStateConflictAudit` reads Harmony patch ownership before any claimed target is patched. A competing prefix, postfix, transpiler, or finalizer names its owner and rejects the complete selected snapshot. `Homm3SkeletalNecromancyProbe` publishes through the runtime-mechanics-owned shared battle-result prefix rather than owning a competing patch. Every exact battle-result cleanup clears root correlations, child queues, event tokens, dirty sets, family ledgers, and the runtime generation.
