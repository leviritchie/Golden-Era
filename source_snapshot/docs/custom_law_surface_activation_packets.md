# Custom Law Surface Activation Packets

This document converts the no-compromise readiness matrix into implementation packets. A packet is not gameplay approval. It is the minimum proof required before an agent may implement one class of custom law behavior.

Every packet must fail closed. If the required evidence is missing, the law stays disabled and logs a bounded diagnostic only when the relevant flag is enabled.

The target list in `custom_factions/custom_law_targets.json` is the source of truth for which current rows are native-exact, temporary compromises, or still runtime-required. Packet work should move entries out of `temporary-compromise` / `needs-runtime`; it must not add broader donor substitutes.

`tools/release_port/report_custom_law_target_coverage.py` can generate a status-by-packet planning report from that target list after static validation is requested. The generated report is only a queueing aid; it does not replace packet proof.

`tools/release_port/audit_custom_law_overrides_against_targets.py` can then audit current law override rows for hidden compromise debt. Audit failures should not be fixed by broad donor rows or by removing target entries; they should become packet work or explicit documented temporary compromise.

Diagnostic setup should use `custom_factions/custom_law_diag_profiles.json`. `tools/release_port/validate_custom_law_diag_profiles.py` checks that every packet named by the target spec has a same-named profile and captures active law/rank context. Static profile coverage still does not prove any native surface.

`tools/release_port/check_custom_law_no_compromise_static.py` is the combined static hygiene gate for target/profile/override/unit-family checks. Passing it is a prerequisite for clean packet work, not evidence that a packet is runtime-proven.

`tools/release_port/generate_custom_law_implementation_queue.py` can generate the packet-ordered implementation backlog from target statuses. Use it to choose packet batches after static validation; do not treat the generated queue as proof.

`tools/release_port/report_custom_law_strict_candidate_rows.py` can generate the strict-candidate strip/implement report, including source bonus counts for each target law.

The preferred path is `tools/release_port/check_custom_law_no_compromise_static.py --write-reports`, which writes coverage, queue, and strict-candidate row artifacts only after the static gate passes. Those artifacts are still planning aids, not packet proof.

For strict no-compromise candidates, `tools/release_port/check_custom_law_no_compromise_static.py --strict-no-compromise-law-rows` adds `validate_custom_law_strict_no_compromise_rows.py`. That optional check fails if non-`native-exact` target rows still carry concrete bonuses. This is expected while playable donor compromises remain.

Law-focused overlay runs can opt into `tools/release_port/apply_release_core_overlay.py --require-no-compromise-law-static` so Core generation fails before output if static target/profile/proof/override/unit-family hygiene is broken. This is still separate from runtime packet proof.

Strict candidate overlay runs can also opt into `tools/release_port/apply_release_core_overlay.py --strict-no-compromise-law-rows`, which checks both source overrides and the candidate Core archive for concrete bonuses on non-`native-exact` targets. This is expected to fail until temporary compromise rows are removed or packet-backed gameplay is implemented and documented.

If a strict candidate should preserve playable source overrides while removing hidden donor behavior from generated output, add `tools/release_port/apply_release_core_overlay.py --strip-nonfinal-no-compromise-law-bonuses`. This strips concrete bonuses from non-final target rows in the candidate archive and rewrites stripped descriptions as pending no-compromise implementations; it does not implement the intended packet behavior.

The strict Core validator also checks those pending descriptions. A non-final row with no concrete bonuses must not still display stale donor-effect text.

Generated custom law rows can carry `xHomm3NoCompromise*` metadata from the target spec. Treat those fields as traceability only; they do not activate packet behavior.

`tools/release_port/validate_custom_law_core_metadata.py --core <Core.zip>` can validate that a generated Core.zip actually contains those metadata fields for every target-backed custom law row. Passing it is Core traceability evidence only.

Law-focused overlay runs can also opt into `tools/release_port/apply_release_core_overlay.py --validate-no-compromise-law-core-metadata`, which runs that validator against the candidate Core.zip after custom biome packing and before replacing the release archive. This is fail-closed metadata validation only, not runtime proof.

`custom_factions/custom_law_packet_proofs.json` is the proof-state gate for gameplay. A packet with `gameplayAllowed=false` must remain diagnostic/planning-only even if target specs, flag profiles, and static reports are valid. Spell-school/access rows at indices `15` and `27` both use the `spell-cooldown` packet because both need spellbook/cast-gate/cooldown proof before divergent runtime behavior.

After a user-driven capture has been reviewed, `tools/release_port/promote_custom_law_packet_proof.py` is the controlled helper for proof promotion. It must be given the evidence artifact and exact proof metadata; it does not replace review, regeneration, build validation, or docs updates.

`Homm3CustomLawPacketGate` mirrors the current all-false proof state at runtime so future hooks can fail closed before mutating native state. Packet proof promotion must update both the proof ledger and the runtime gate through an explicit reviewed change or generator.

Use `tools/release_port/generate_custom_law_packet_gate.py` to regenerate or `--check` the runtime gate from the proof ledger. Runtime packet proof must not be hand-edited only in C#.

When `homm3_custom_faction_law_diag.flag` is enabled, `Homm3CustomFactionLawRuntime` logs the compiled packet proof gate state. Treat that as visibility into current gating, not as proof that a packet is runtime-ready.

The same law diagnostic path logs the compiled `Homm3CustomLawHandlerRegistry` slot map. Treat that as deployed-map visibility only, not proof that a handler is implemented or runtime-ready.

Future gameplay hooks should use `Homm3CustomLawRuntimeGuard.TryResolveAllowedActiveLaw(...)` rather than separately checking active law state and packet proof state. A hook that cannot get an allowed law context must do nothing except optional bounded diagnostics.

`Homm3CustomLawHandlerRegistry.TryEnterHandler(...)` is the preferred future gameplay entry seam. It validates the named handler slot, law index, and packet mapping before calling the combined guard, so packet-specific hooks cannot drift into ad hoc gate checks.

`tools/release_port/audit_custom_law_runtime_guard_usage.py` statically checks for future source drift where gameplay code uses active law/rank or packet gate APIs directly instead of the handler/guard path. It also warns when gameplay files use the lower-level guard directly instead of a named handler slot. This is a source-hygiene check only.

`tools/release_port/validate_custom_law_handler_registry.py` statically checks that each target family has exactly one named handler slot and that the slot packet matches the family packet. This prevents target/handler drift before gameplay hooks are written.

## Packet template

Each implementation packet must name:

- `Law families`: the law families or faction laws this packet can unblock.
- `Native surface`: exact type/method/field symbols used by the hook.
- `Active rank`: how `Homm3CustomFactionLawRuntime` proves active faction, law SID, and rank in the same hook context.
- `State consumed`: exact state read by the law.
- `State mutated`: exact state changed by the law, or `none` for diagnostics.
- `Classifier facts`: any `Homm3UnitLawClassifier` facts consumed, including `Unknown` fail-closed behavior.
- `Idempotence key`: battle, day, reward, spell, construction, or stack key preventing duplicate effects.
- `Diagnostic flag`: flag that enables bounded evidence logs.
- `Runtime scenario`: exact user-driven scenario required to prove behavior.
- `Documentation update`: AGENTS/doc line to mark the surface proven or still unproven.

## Packet A: Active law/rank in consuming hook context

- `Law families`: all runtime custom laws.
- `Current status`: diagnostic-only.
- `Native surface`: current consumers include battle-event side contexts, buff/debuff receiver context, reward/result contexts, spell gate/cooldown contexts, economy day/resource contexts, and law-tree UI contexts.
- `Required proof`: the consuming hook object graph must resolve the expected custom faction, law SID, line/group, `level > 0`, and `wasApplied == true`.
- `Fail-closed rule`: `none-or-unresolved` is not proof that no law is active; it only disables that custom effect in that hook context.
- `Runtime scenario`: open a law tree with a known active custom law, then trigger the exact diagnostic context that would consume that law.

## Packet B: Battle action classification

- `Law families`: melee/ranged formations, first-volley effects, shooter/melee split laws, Cove gunpowder attacks, Stronghold melee/ranged laws.
- `Current status`: diagnostic-only.
- `Native surface`: `CastAbilityEventArgs`, `AbilityID`, `AbilityLogicConfig`, `CastDealerConfig`, and `formationProbe`.
- `State consumed`: ability ID/type/index, ability/dealer classification fields, caster, attacked objects, attacked hexes, caster/target hex distance candidate.
- `Classifier facts`: no shooter/melee fact may be consumed until runtime logs prove the action classifier in the same event.
- `Required proof`: visible melee, ranged, counterattack, special ability, and first attack actions must correlate with raw fields consistently.
- `Fail-closed rule`: do not infer ranged/melee from `shootRange`, `attackType_`, or adjacency alone until proven.

## Packet C: Battle geometry and formation predicates

- `Law families`: formation laws, isolated target laws, adjacency protection, boxed/flanked enemies, Hellpack adjacency, Hunter Pairs.
- `Current status`: diagnostic-only.
- `Native surface`: Hex `index/x/z`, battle object hex, attacked hexes, movement path, `formationProbe`.
- `State consumed`: caster hex, target hexes, path first/last, occupant evidence if exact.
- `Required proof`: user-visible adjacency, non-adjacency, movement into adjacency, large-unit footprint, and blocked/occupied-neighbor cases.
- `Fail-closed rule`: axial distance candidate is not native topology proof; facing and footprint remain missing until proven.

## Packet D: Committed damage mutation

- `Law families`: training damage, counterstroke damage, lifesteal/reanimation, Conflux extra magic damage, Dungeon isolated damage, Fortress mitigation/debuff-on-hit.
- `Current status`: diagnostic-only.
- `Native surface`: exact `Unit.bbgw(...)` candidate plus `ObjectTookDamageEventArgs` ordering.
- `State consumed`: caster/source/receiver/dealer, final damage, stacks destroyed, damage type/mechanic.
- `State mutated`: damage only after exact committed-damage mutation semantics are proven.
- `Required proof`: visible committed damage and death results match the candidate payload before and after event dispatch.
- `Fail-closed rule`: forecast surfaces do not authorize mutation.

## Packet E: Buff/debuff/status identity

- `Law families`: Fortress poison/slow, Dungeon disable/debuff exploitation, Rampart Avenger, Tower calibration buffs, Conflux elemental buffs.
- `Current status`: diagnostic-only.
- `Native surface`: exact `dzv.bbgf`, `dzv.bbfn`, `dzv.bbfl` and receiver context.
- `State consumed`: buff SID, level, duration/rounds/turns, caster/source/target, receiver side/object/hex.
- `State mutated`: buff add/refresh/remove only after ownership, duration, stacking, and target identity are proven.
- `Classifier facts`: Avenger-marked uses explicit Rampart mark buff SIDs; other status categories need exact SIDs or native categories.
- `Fail-closed rule`: do not treat any negative buff as poison/slow/disable without exact SID/category evidence.

## Packet F: Focus/Energy storage

- `Law families`: Cove Focus gain/spend, reload credits, Focus-triggered cooldowns.
- `Current status`: diagnostic-only.
- `Native surface`: Energy/Focus event constructors, hero ability UI/bind contexts, native storage still unproven.
- `State consumed`: current Focus, Focus delta, source mechanic/action, side/hero identity.
- `State mutated`: Focus storage only after UI, storage, and cast/ability eligibility stay synchronized.
- `Fail-closed rule`: UI energy labels are not storage proof.

## Packet G: Spell cooldown and cast gate

- `Law families`: Tower overclock, Conflux aspect cooldowns, Inferno sacrificial casting, Necropolis corpse fuel, Cove reload drills, spell school non-static effects.
- `Current status`: diagnostic-only.
- `Native surface`: `eew` cooldown storage candidates and `eex`/`eew` cast-gate candidates.
- `State consumed`: spell SID/index, school, current cooldown, same-spell/same-school counters, mana/rank gate, selected spell.
- `State mutated`: cooldown/cast permissions only when spellbook UI, cast gate, and execution agree.
- `Fail-closed rule`: do not override gate results directly unless the native state edit is proven.

## Packet H: Reward, battle result, and economy commit

- `Law families`: Cove prize shares, Stronghold spoils, Rampart low-loss rewards, Necropolis corpse/gold, Fortress defensive rewards.
- `Current status`: diagnostic-only.
- `Native surface`: reward-set apply/queue/remove and battle-result world-apply surfaces.
- `State consumed`: hero, side, object/reward ID, winner/loser transfer sides, loss deltas, reward items.
- `State mutated`: resources/units only at committed, idempotent reward/result point.
- `Idempotence key`: reward set ID, battle ID/result applied flag, day/hero/object as appropriate.
- `Fail-closed rule`: generic resource-add logs are not reward classification proof.

## Packet I: Construction cost, eligibility, and commit

- `Law families`: construction discounts, extra build, faction-specific building category laws.
- `Current status`: diagnostic-only.
- `Native surface`: exact diagnostic candidates are centralized in `GameSymbols.ConstructionLaws`, including building manager, building session, and building view methods; they are not yet proven as a full display/charge/commit chain.
- `State consumed`: city, building SID/category, displayed cost, charged cost, eligibility, current day/build state.
- `State mutated`: cost/eligibility/build count only when all native UI and commit surfaces agree.
- `Diagnostic flag`: `homm3_custom_construction_law_diag.flag`.
- `Fail-closed rule`: a UI-only discount or charge-only discount is invalid.

## Packet J: Gating, summon, and temporary stack identity

- `Law families`: Inferno Gating laws, summon-adjacent laws, sacrifice/gated-loss laws, temporary summon interactions.
- `Current status`: blocked.
- `Native surface`: visual spawn identity work exists but is not law-ready lifetime proof.
- `State consumed`: exact source ability/spell, spawned stack SID, owner side, temporary/gated lifetime, loss/despawn reason.
- `State mutated`: gated-entry buffs, sacrifice credits, adjacency effects only after exact gameplay lifetime surface is proven.
- `Fail-closed rule`: battle visual replacement identity is not gameplay identity.

## Packet K: Corpse and temporary mana state

- `Law families`: Necropolis corpse economy, Corpse Wisdom, Death Magic, Death Moon, Corpse Fuel, Mortuary Accounting.
- `Current status`: blocked.
- `Native surface`: no logical corpse count, consumption, temporary mana, or cleanup surface proven.
- `State consumed`: corpse-eligible deaths, corpse value, battlefield/result corpse pool, hero mana state.
- `State mutated`: corpse pool and mana only when storage, consumption, UI, and cleanup semantics are proven.
- `Fail-closed rule`: battle losses and corpse visuals are not corpse economy state.

## Packet L: Morale roll and action queue effects

- `Law families`: Castle morale scaling, Cove Crew Nerve, Dungeon terror exploitation, Rampart Defender's Grace, construct/undead morale replacement ideas.
- `Current status`: diagnostic-only.
- `Native surface`: exact positive/negative morale roll candidates on `eep`.
- `State consumed`: unit, morale stats, roll result, side, current action/turn state.
- `State mutated`: extra action/failure/queue effects only after visible action queue ordering is proven.
- `Fail-closed rule`: morale animation or stat presence alone is not a trigger proof.

## Next recommended source batches

1. Use `docs/custom_law_runtime_capture_checklist.md` for user-driven diagnostic captures.
2. Build-validate the accumulated diagnostic/classifier source changes when the user permits validation.
3. Pick one packet to prove at runtime with user help before implementing any gameplay mutation.
