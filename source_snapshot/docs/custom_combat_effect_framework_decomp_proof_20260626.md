# Custom Combat Effect Framework Design Proof

Status: design proof retained for provenance. The current executable implementation is source/static validated and Golden Era build-target proven, but runtime-unvalidated; ownership and proof status are authoritative in `docs/runtime_mechanics_implementation_handoff.md`.

Correction: this mod already has many native combat effects and packet surfaces proven or partially proven. The missing capability is not another donor/native-effect route. The missing capability is a non-native custom effect manager that can apply arbitrary code-defined transformations through controlled mutation points.

## Target Capability

The framework should let us define effects in code, then apply them through a single manager-owned pipeline:

1. A proven native hook, packet, or event surface enters the manager.
2. The manager builds a typed combat context from the native objects already available.
3. Registered custom effects inspect that context.
4. Matching effects return explicit transformation requests.
5. A central mutation API applies those requests to native state or current packet values.
6. The manager records ordering, logs proof details, and handles duration/cleanup where applicable.

Native layer is carrier/state host. Custom manager owns behavior.

## Design Boundary

One problem, one solution:

- Native donor effects must not be used as the gameplay implementation for custom effects.
- Proven native packet/event surfaces may be used as entry points.
- Effect behavior must live in code-owned effect definitions.
- Direct writes must go through `CombatMutationApi` or an equivalent central mutation layer.
- Obfuscated/native names stay centralized in `GameSymbols` and existing law/runtime symbol classes.
- Unsupported transformations fail closed; no broad fallback scans, stale aliases, or donor substitution.

The framework should not try to prove that every native surface exists again. It should reuse already-proven surfaces and focus proof effort on manager ordering, transformation semantics, and safe mutation/cleanup.

## Proposed Core Types

### `CustomCombatEffectManager`

Owns battle-scoped and packet-scoped custom effect execution.

Responsibilities:

- Register effect definitions.
- Receive native packet/event/hook calls.
- Build `CombatEffectContext`.
- Select matching effects.
- Sequence transformations deterministically.
- Dispatch writes through `CombatMutationApi`.
- Track temporary state and cleanup obligations.
- Emit proof logs for every applied or skipped transformation.

### `ICustomCombatEffect`

Code-defined behavior unit. Effects should not write native fields directly.

Suggested shape:

- `EffectId`
- `SupportedTriggers`
- `CanApply(context)`
- `BuildTransformations(context)`

The effect returns transformations; the manager applies them. That keeps behavior definition separate from write mechanics.

### `CombatEffectContext`

Typed read view of the current combat state.

Possible fields:

- Battle or battle-logic object if available.
- Source/caster object.
- Target/receiver object.
- Current side/law/effect owner where known.
- Current packet type.
- Current ability/spell/effect identifiers.
- Damage, heal, status, movement, energy, or summon packet details.
- Runtime proof tags for which native route produced the context.

### `CombatTransformation`

Explicit mutation request. Examples:

- Modify current damage by fixed amount or percentage.
- Override current packet flags.
- Add a temporary stat modifier tracked by manager state.
- Apply a code-owned status marker.
- Alter cooldown/energy/mana values through a proven adapter.
- Spawn or remove a combat object through a proven native route.

The transformation object should name the exact write family it needs. Unsupported write families fail closed.

### `CombatMutationApi`

The only native-write layer.

Responsibilities:

- Validate that the current trigger supports the requested transformation.
- Apply the exact native write or packet mutation.
- Log before/after values.
- Reject stale symbols, donor behavior, and route mismatch.
- Register cleanup work for temporary mutations.

## Entry Point Model

The framework should support multiple proven entry points, but each entry point should be explicitly registered as a trigger family. This avoids turning `edb` or any other broad event mechanism into a hidden fallback bus.

Initial trigger families can be grouped like this:

- `DamageApplying`: existing exact current `Hex.Session.Battle.Unit` generated damage-apply method.
- `DamageObserved`: `ObjectTookDamageEventArgs` dispatch/constructor evidence.
- `AbilityChanged`: `ChangeAbilityEventArgs` / `dxy` change event factories.
- `AbilityCastObserved`: `CastAbilityEventArgs` / cast-magic visual and ability surfaces.
- `BuffObserved`: `BuffEventArgs` native event-context route.
- `BattleStarted`: only after start-battle dispatch route is proven, not just shell presence.
- `ObjectLifecycle`: object spawned/destroyed/revived routes after each route is promoted.

A trigger being registered does not mean every transformation is legal there. The mutation API decides whether a requested write is valid for the current trigger.

## First Implementation Slice

The first slice should prove the non-native manager, not another native effect.

Recommended first slice:

1. Add the manager, context, transformation, and mutation API shells.
2. Register exactly one trigger family using an already-proven narrow native surface.
3. Add one code-owned proof effect that returns a simple transformation.
4. Have `CombatMutationApi` apply only that one transformation family.
5. Add a validator that rejects native writes from effect classes and rejects donor-effect gameplay implementation.
6. Keep the feature behind an explicit diagnostic/proof flag until runtime-proven.

A damage packet remains a practical first trigger because it has an exact current generated method and existing law-runtime history, but it is not the point of the framework. The point is proving that arbitrary code-owned transformations can be selected, sequenced, applied, and logged without native donor behavior.

## Validator Contract Needed

Any implementation should add a build/deploy validator that enforces:

- No effect class writes native fields or calls native mutation methods directly.
- All writes go through `CombatMutationApi`.
- New trigger families declare their exact symbol source and proof status.
- Stale generated/decomp aliases are rejected where current runtime names are known.
- Broad event dispatch cannot be used as a catch-all mutation trigger.
- Donor/native effect SIDs may be used for UI/activation only, not as custom gameplay behavior.
- Temporary transformations have explicit cleanup or explicit permanent-scope documentation.

## Current Evidence Reuse

The framework can reuse these existing evidence families rather than reproving them from scratch:

- Current generated `Hex.Session.Battle.Unit` damage-apply method in `GameSymbols.BattleEventLaws.BattleUnitApplyDamage`.
- Battle event payload shells under `tmp/cpp2il_experiment/out_dev_diffable_cs/DiffableCs/Hex/Hex/Session/Battle/*EventArgs.cs`.
- Current runtime interop metadata under `artifacts/runtime_symbol_contracts/current_runtime_interop_map.json`.
- Existing battle-event diagnostics and law-runtime packet work.
- Existing buff/debuff diagnostics as observation/status-read evidence, while keeping positive status commit separate until proven.

## Implemented Source Slice

The current slice evolves the prototype into a declarative, battle-scoped runtime:

- `custom_factions/runtime_mechanics/homm3_state_pilots.json` is the executable contract.
- `Homm3RuntimeMechanicRegistry` validates and compiles the selected definition atomically.
- `Homm3RuntimeMechanicHooks` owns the exact typed committed-damage prefix and production cleanup hook.
- `Homm3BattleLocalLawState.RuntimeMechanics` owns exact-object unit state, side state, battle counters, and generation cleanup.
- `CustomCombatEffectManager` returns one typed `PreparedDamageMutation`.
- `CombatMutationApi` remains the sole `ref int` damage writer.
- `Homm3TrainingDamageLawRuntime` no longer invokes the manager.

The authoritative ownership matrix, flags, lifecycle, and current proof boundaries are in `docs/runtime_mechanics_implementation_handoff.md`.

## Proof Status

- Native surface evidence: reused from the exact current Unit damage and battle-result symbols.
- Declarative manager and state architecture: source/static validated.
- Unit, side, and battle state fixtures: source/static validated.
- Static validator coverage: both focused validators pass and are wired into every normal build.
- Golden Era build target: passed with deployment disabled.
- Deploy/startup/runtime/user-visible behavior: unproven.