# Runtime Mechanics Implementation Handoff

Status: direct-state expansion is source-prepared, Golden Era compiled/deployed, inactive-startup proven, and aggregate manager/runtime activation stress proven. Validation must be read from the proof matrix below. User-visible combat behavior remains opt-in through diagnostic flag files and is runtime-unvalidated unless a focused record explicitly says otherwise.

## Purpose

`custom_factions/runtime_mechanics/` is the executable battle-mechanics lane. It is deliberately separate from design-only `source_mechanics` and from native ability/law payloads. Native rows may continue to provide UI, costs, and targeting, but they are not the gameplay implementation for runtime mechanics.

The current source lane contains a stable adapter manifest, bounded battle transaction manager, typed journal, direct native-write gateway, generation-owned family state, exact typed event contexts, and parameterized fixtures. This is not runtime behavior proof. Adventure/save persistence, multiplayer synchronization, and AI authoring remain out of scope.

## Runtime-mechanics ownership matrix

- `Homm3RuntimeMechanicRegistry`: parses, validates, compiles, and indexes immutable definitions.
- `Homm3BattleUnitLawOwnerRegistry`: owns exact-object sparse binding and delegates its `Unit.Init` registration request.
- `Homm3RuntimeMechanicHooks`: is the sole Harmony registration owner for `Unit.Init`, committed damage, movement commit, typed-event constructors, exact `eda` action/round dispatchers, and battle result; it deduplicates exact native targets. Hooks stay thin: `__state` / `ref int` / redirect skip only.
- `Homm3BattleEventNativeAdapter` surface partials: sole surface-keyed ingress normalizer (`DamageIngress`, `SurfaceIngress`) emitting `Homm3DirectStateIngressOutcome`.
- `Homm3DirectStateIngressDispatcher`: routing-only fan-out from normalized ingress to active adapters; cap-logs named rejects/failures.
- `Homm3BattleLocalLawState.RuntimeMechanics` plus focused direct-state partials: own unit/exact-battle-side state, generation publication, family ledgers, event tokens, and cleanup.
- `CustomCombatEffectManager`: dispatches compiled definitions and prepares typed mutations.
- `BattleCombatTransactionManager`: is the sole validation, root-budget, transaction, journal, rollback, correlation, and deferred-work owner.
- `NativeCombatWriteGateway`: is the sole production write owner. Behind it, `ICombatWriteBackend` selects Live (production) or Model (headless replay only). `CombatMutationApi` is a compatibility facade with no independent write route.
- `Homm3DirectStateAdapterManifest`: owns stable append-only `AdapterId`, operation, hook, journal, cap, reconciliation, fixture, and proof-family records. Manifest JSON also owns `ingressWaveMap` and `replayScenarios`.
- `Homm3RuntimeMechanicFixtureHarness`: owns common source fixture validation, model-backed headless replay (`TryRunHeadlessReplayScenarios` → `source-replay-validated` startup smoke only; never combat-proven), fault injection, dirty/retry counters, family proof labels, and the opt-in aggregate transaction stress. Root work/depth/journal/fan-out high-water values come from `BattleCombatTransactionManager`.
- `Homm3DirectStateIngressMining`: diagnostic-flag-gated ingress counters, bounded outcome ring, Harmony damage-surface patch readback, and evidence envelopes (`ingress-shape-capture-only`). Never mutates combat.
- `Homm3BattleResultSurface`: resolves the exact cleanup surface shared by production cleanup and the diagnostic probe.
- `Homm3SkeletalNecromancyProbe`: delegates its pre-result reward callback to the shared battle-result hook; it no longer owns a competing Harmony patch.
- `Homm3RuntimeLawFixtureAdapter`: resolves and caches only the diagnostic Castle law-index-6 fixture.

`Homm3TrainingDamageLawRuntime` remains dormant and must not invoke the runtime-mechanics manager. Registering it alongside `Homm3RuntimeMechanicHooks` would create a second committed-damage owner.

## Activation and failure behavior

1. Custom faction manifests load.
2. Runtime JSON is parsed and compiled locally.
3. Any invalid selected/enabled definition rejects the complete snapshot.
4. Only hook/native-write surfaces claimed by selected adapters are preflighted.
5. Shared `Unit.Init` registration is performed by the runtime-mechanics hook owner when any selected or packet-gated feature requires it.
6. The shared battle-result hook is registered once by the runtime-mechanics owner and also publishes the skeletal-necromancy pre-result callback.
7. The compiled snapshot is published last.

Failure removes only exact patches registered by the failed activation. Pre-existing shared Unit.Init/battle-result registrations and unrelated Harmony patches remain untouched. If cleanup or any selected adapter binding cannot register, the complete selected snapshot remains inactive. Duplicate result calls are rejected through the native `alreadyApplied` state rather than a process-lifetime object marker.

With no direct-state diagnostic flag present, no mechanics mutation hook or battle state is installed. The shared battle-result hook may still be present for the release skeletal-necromancy callback.

## Damage-hook identity binding (required)

Typed damage Harmony arguments are **not** already-usable battle units or ability identity. A registered damage prefix/postfix plus a selected unit SID is **not** sufficient wiring proof.

Hard lessons from the gated Bellwether Shoulder Check pilot (2026-07-19):

1. Damage `__0` is the generated attacker interface (`eab` / `InterfacePublicAbstractbaObbbUnInbbUnObbbObUnique`). `Homm3UnitLawClassifier` reports `identitySource=unresolved` until the arg is unwrapped to a concrete `Hex.Session.Battle.Unit` (Il2Cpp wrap, FieldObject self, or registered-unit pointer match). Do not `Classify(__0)` as if it were `Unit`.
2. Ability / cast identity is **not** reliably on `__1`. Resolve from the cast-source and dealer args (`__1` and `__2`, plus `DamageCastSource.PrimaryDamageDealerGetters` when needed). Exact `"Shoulder Check"` equality alone is insufficient: runtime may surface a lang key (`*abilities_0*`, tokens containing `shoulder`).
3. Silent early-return is forbidden on this path. Rejects must cap-log an explicit reason via `Homm3DirectStateIngressDispatcher.CapLogOutcome` (`HoMM3 direct-state ingress rejected: …`). `Homm3RuntimeMechanicFixtureHarness.RecordFailure` alone is not operator-visible proof.
4. Family proof gate: one qualifying live hit must produce either a commit log or a named fail-closed reject. Startup `PREPARED_MECHANICS=1` / hook registration only proves activation, not argument binding.

Any new adapter that keys off committed damage must document its damage-arg dossier (caster resolve, ability/cast resolve, reject logging) in `docs/direct_state_adapter_dossiers.md` before claiming the slice is wired.

5. `DamageApplied` postfixes consume Harmony `__state`. A DamageApplied-only adapter must still register the typed damage prefix so `__state` is initialized to `true`. Without that prefix, `__state` defaults to `false` and the postfix returns immediately with no logs (Bellwether movement pilot, 2026-07-19).

## Diagnostic fixtures

### Unit fixture

- Flag: `homm3_runtime_mechanic_unit_pilot.flag`
- Unit: `h3_pikeman`
- Behavior: the first qualifying outgoing committed-damage call per battle receives `+1`, then its exact-object unit slot is consumed.

The `+1` is standalone runtime behavior. No donor/native ability row supplies it.

### Law/side/battle fixture

- Flag: `homm3_runtime_mechanic_law_pilot.flag`
- Activation: `homm3_castle`, law index `6`
- Behavior: the first qualifying outgoing committed-damage call for the exact active-law side receives `+1`, consumes a side slot, and increments a battle-generation counter.

This is an activation/state fixture only. It does not implement or replace Battle Readiness; that law's displayed Focus behavior remains native-data-driven.

The damage flags can be selected independently. Aggregate fixtures are bounded by the root work/journal/fan-out caps rather than a global mutual-exclusion rule.

### Direct-state family fixtures

Every adapter row has one stable flag in `homm3_adapter_manifest.json`; the manifest and fixture JSON are build-exhaustive.

- `damage`: flat committed-damage transformation.
- `cast`: committed cast counting and bounded cast-chain work.
- `resource`: Focus grant/spend/set and cooldown/charge/cast-counter state.
- `status`: exact-SID apply/refresh/tick/expire/remove.
- `movement`: push/pull/teleport/immobility, including gated Bellwether Shoulder Check.
- `lifecycle`: summon, trap, corpse, and corpse-consume-plus-summon composition.
- `nestedDamage`: redirection/reflection/splash child work sharing the root budget.
- `kill`: exact kill and ally-death records with claimed event tokens.
- `action`: bounded extra-action queue insertion/removal.
- `turnOrder`: independently identified bounded reorder/splice.
- `aura`: manager-owned definitions and bounded dirty membership.

Each row also declares one reconciliation policy in the stable manifest. The direct-state family slices are source/static validated and Golden Era compiled; all family behavior remains runtime-unvalidated.

The Bellwether override uses Schism T6 Arbitrator **Command: Fear** (`arbitrator:abilities:1`): native `teleport` via ordered unit+hex targeting, reshaped to `distanceFromFirst=1`. This replaces the failed adjacent `push_unit` away envelope. The DS `diagnostic.bellwether_shoulder_check` MovementPush pilot stays **disabled**.

### Aggregate stress fixture

- Flag: `homm3_runtime_aggregate_pilot.flag`.
- Test-only deployed fixture: all 16 diagnostic definitions are selected under one flag; the checked-in per-family flags remain unchanged.
- Runtime result on 2026-07-19: all 15 stable adapters preflighted and 16 distinct native hook targets registered.
- Transaction result: 14 begun, 2 committed, 12 rolled back; depth `8`, journal `64`, fan-out `16`, and root-work `64` high-water.
- Bounded state result: dirty hexes `32`, dirty units `32`, presentation retries `2`, and one intentional pre-commit fault injection.
- Cleanup result: two consecutive cleanup passes advanced generation `1 → 2 → 3` and left statuses, auras, dirty identities, retries, and fault counters empty.

This proves the manager transaction, rollback, cap, hook-deduplication, and repeated-cleanup paths inside a live Golden Era process. It does not prove user-visible native combat outcomes for any family.

## Performance contract

- Zero selected mechanics: no mechanics-owned hooks or battle state.
- Typed damage dispatch names all eight native arguments, uses `ref int __3`, and does not request Harmony `object[]`.
- One decrement-only root budget bounds work, journal entries, depth, fan-out, queue span, and unique dirty identities.
- Journal/work capacity is reserved before writes; rollback uses typed opcodes rather than callbacks.
- Authoritative state is committed exactly once. Native gameplay event tokens are claimed before at-most-once invocation; only presentation reconciliation is retryable.
- Native callbacks and deferred child work are published/drained outside the transaction lock.
- Runtime ledger entries are allocated only after an enabled adapter begins authoritative state.
- Unit consumed/generation checks use memory-safe publication and are rechecked under the shared lock.
- Law activation resolves to exact `Data.Side` once per exact battle-side object and generation, then caches `Unknown`, `Present`, `Absent`, or `Failed`.
- Side consumption and the diagnostic counter are keyed by the exact battle-side object, so an abandoned battle cannot suppress a later battle that receives a new native side object.
- Logging is capped and occurs after mutation/lock release.

No zero-allocation claim is made for a committed direct-state transaction: the current bounded transaction and typed snapshot objects allocate. The typed Harmony damage argument path itself avoids `object[]`; the shared `Unit.Init` postfix still receives `object[]`.

## Proof boundaries

- Adapter JSON/source contract: passed on 2026-07-19.
- JSON, framework ownership, and direct-state invariant validators: passed on 2026-07-19 and remain wired into normal builds.
- Headless replay contract (`tools/run_direct_state_replay.py`): source-replay-validated only; covers every manifest operation plus fixed occupancy/queue/rollback/fault/budget cases; does **not** promote user-visible gameplay proof.
- Movement write path: **fail-closed / not shipping.** In-tree `Homm3DirectStateUnitHexNative` / `TryCommitUnitHexMove` can satisfy local verify-after-commit but is live-negative for coherent battle movement. Prefer native `push_unit` (`EMechType.PushUnit`) / step queue once live-positive; see `docs/battle_state_logic_map.md` § Direct-state manager verdict. `BattleLogic` `Unit_Hex_0` remains retired (no-publish).
- Ingress normalization: DamageApplied requires typed prefix/`__state` pairing; Bellwether-named production symbols deleted; MovementPush routes via generic `damageApplied` ingress.
- Golden Era compile: passed on 2026-07-19 through `OfficialDeobfBuild=true` against the active Golden Era install (51 existing warnings, 0 errors).
- Direct-state family source/static slices: passed manifest, dispatch, reconciliation-policy, sole-hook/write-owner, bounded queue, and centralized-symbol checks on 2026-07-19.
- Bellwether donor-shell source contract: passed; generated Core readback passed on 2026-07-19 (`push_unit` stripped, shell metadata stamped).
- Bellwether movement-pilot startup: passed on 2026-07-19 with `homm3_runtime_movement_pilot.flag` (`PREPARED_MECHANICS=1`, chainloader complete). Live Shoulder Check then failed closed silently until damage-arg unwrap + reject logging; combat push behavior remains runtime-unvalidated.
- Installed/deployed readback: passed for plugin DLL, adapter manifest, and fixture JSON on 2026-07-19.
- Inactive startup: passed; valid manifest reported `VALID_NO_SELECTED_MECHANICS` and the chainloader completed.
- Malformed-manifest startup: passed; missing `adapters` rejected the complete mechanics snapshot while the chainloader completed.
- Aggregate all-family startup registration: passed; 15 adapters/16 definitions preflighted and 16 distinct targets registered without a mechanics error.
- Aggregate transaction/rollback/cap fixture: passed with the high-water values recorded above.
- Two-cleanup generation fixture: passed with generation `1 → 2 → 3` and empty post-cleanup manager state.
- Ingress mining evidence (`direct_state_ingress_evidence` / `homm3_direct_state_ingress_mining.flag`): source-prepared and Golden Era compiled/deployed on 2026-07-19; session record at `artifacts/direct_state_ingress_mining/session_20260719_mining_record.json` (ingress-shape-capture-only). Live envelope requires a game reload so the bridge advertises the new command; never combat mutation; does **not** auto-promote to gameplay proof.
- Runtime unit fixture: unproven.
- Runtime law/side/battle fixture: unproven.
- Runtime family native-binding activation: passed in the aggregate startup capture.
- Runtime family user-visible combat effects: unproven.
- User-visible gameplay: unproven.

Promotion beyond this boundary requires focused combat records for once-only native application, Bellwether blocked/edge/occupied/death/footprint cases, family event ordering, and user-visible outcomes.
