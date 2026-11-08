# Custom Law Runtime Capture Checklist

This checklist standardizes user-driven runtime evidence collection for the no-compromise faction law project.

Do not treat any capture as proof unless the log shows the exact consuming context, active custom law/rank, and the native state required by the relevant activation packet.

## General rules

- Test one law surface at a time when possible.
- Keep unrelated diagnostic flags disabled unless the scenario explicitly needs correlation across systems.
- Use `custom_factions/custom_law_diag_profiles.json` as the named flag profile list.
- Profile names should match packet names from `custom_factions/custom_law_targets.json`; `tools/release_port/validate_custom_law_diag_profiles.py` can check static profile coverage when validation is requested.
- `tools/release_port/custom_law_diag_flags.py` can list, apply, or clear those profiles when given an explicit `--plugin-root`; this tool is opt-in and should not be run without an intended runtime capture.
- Use profile `all-runtime-law-surfaces` only for broad pilot passes where one run should capture as many surfaces as possible. It is intentionally noisy and does not prove any packet by itself; review still has to isolate exact hook context, active law/rank, consumed state, mutated state, and visible behavior before promotion. June 17 note: this broad profile intentionally excludes `homm3_focus_law_diag.flag` after a user-piloted combat crash showed recursive `BhHeroAbilitiesView` Focus diagnostic binding; test Focus separately after that diagnostic is narrowed.
- `tools/release_port/collect_custom_law_capture.py` can copy logs into a timestamped evidence bundle after a scenario; this tool does not review or prove the logs.
- After reviewing a capture, use `tools/release_port/promote_custom_law_packet_proof.py` only if the packet evidence is strong enough to permit gameplay. The promotion tool requires scenario, flags, exact native symbols, consumed state, mutated state, docs-updated metadata, and an existing evidence artifact.
- Capture `BepInEx/LogOutput.log`, `BepInEx/ErrorLog.log`, `Player.log`, and the exact in-game scenario notes.
- Record faction, active law name/rank, hero, units involved, round/day, and visible outcome.
- A `none-or-unresolved` active-law result disables the effect; it is not proof that no law is active.
- A classifier result of `unknown` disables family-dependent effects; it is not proof that the unit lacks that family.

## Baseline law/rank capture

Flags:

- `homm3_custom_faction_law_diag.flag`

Scenario:

- Open a custom faction law tree.
- Select a faction with at least one known active custom law.
- Capture logs for applied and unapplied law rows.

Required evidence:

- Faction SID.
- Generated law SID.
- Law index/family.
- Rank/level.
- `wasApplied == true` for active rows.
- Unapplied rows absent from active-law summaries.

## Battle action and formation capture

Flags:

- `homm3_battle_event_law_diag.flag`

Scenario:

- Perform one ordinary melee attack.
- Perform one ordinary ranged attack.
- Perform one first action/first volley candidate.
- Move into adjacency and attack.
- Attack a non-adjacent target.
- Include at least one large or multi-hex unit case if available.

Required evidence:

- `CastAbilityEventArgs` context.
- `abilityID`, `abilityType`, and `indexInArray`.
- `AbilityLogicConfig` raw classification fields.
- `CastDealerConfig` raw classification fields.
- `formationProbe.observedFirstForCaster`.
- `formationProbe.minHexDistanceCandidate`.
- `formationProbe.adjacentCandidate`.
- Caster and target unit SID/faction/tier evidence.
- Active law/rank from the same side/context if the law would consume it.

## Committed damage capture

Flags:

- `homm3_battle_event_law_diag.flag`

Scenario:

- Perform a visible damaging melee attack.
- Perform a visible damaging ranged attack.
- Kill at least one stack.
- Trigger a counterattack if the surface being tested depends on counterattack.

Required evidence:

- `damage-apply-candidate` payload.
- `ObjectTookDamageEventArgs` payload.
- Caster/source/receiver/dealer identity.
- Damage amount and stacks destroyed.
- Visible result matching the logged payload.
- Ordering between apply candidate and event dispatch.

## Buff/debuff/status capture

Flags:

- `homm3_buff_debuff_law_diag.flag`
- Add `homm3_battle_event_law_diag.flag` only when action correlation is needed.

Scenario:

- Apply a known buff.
- Apply a known debuff.
- Apply poison/slow/disable if testing Fortress or Dungeon laws.
- Apply Rampart Avenger mark if testing Rampart laws.

Required evidence:

- Exact buff SID.
- Add/query/list surface hit.
- Receiver object/side/hex.
- Caster/source if available.
- Duration/turns/rounds/level.
- Stacking or refresh behavior if repeated.
- Active law/rank from the same receiver or battle context if consumed.

## Focus/Energy capture

Flags:

- `homm3_focus_law_diag.flag`
- Add `homm3_battle_event_law_diag.flag` when the trigger is an attack/counterattack.

Scenario:

- Use an ability that spends Focus/Energy.
- Trigger a Focus-gain candidate if available.
- Open the relevant ability UI before and after use.

Required evidence:

- Native Focus/Energy event payload.
- UI ability energy/cooldown fields.
- Side/hero identity.
- Storage mutation evidence, if any.
- UI and cast eligibility staying synchronized.

## Spell cooldown and cast-gate capture

Flags:

- `homm3_spell_cooldown_law_diag.flag`
- `homm3_spell_cast_gate_law_diag.flag`

Scenario:

- Cast a ready battle spell.
- Attempt to recast while on cooldown.
- Trigger same-school or same-spell restrictions if possible.
- Open the spellbook before and after casting.

Required evidence:

- Spell identity/index/school.
- Cooldown storage before/after.
- Gate return values for ready and blocked states.
- Spellbook visible state matching gate/storage state.
- Active law/rank from the same caster/side context if consumed.

## Reward, result, and economy capture

Flags:

- `homm3_reward_commit_law_diag.flag`
- `homm3_battle_result_law_diag.flag`
- `homm3_custom_faction_economy_diag.flag` only for day/resource correlation.

Scenario:

- Collect a map reward.
- Capture or clear a reward object.
- Finish a battle with clear winner/loser losses.
- End/start a day if daily economy is relevant.

Required evidence:

- Reward-set ID and apply/queue/remove ordering.
- Hero/side/object identity.
- Reward item list.
- Battle result winner/loser transfer-side deltas.
- Idempotence key preventing duplicate grants.
- Active law/rank in the same reward/result context.

## Construction capture

Flags:

- `homm3_custom_construction_law_diag.flag`
- Add `homm3_custom_faction_economy_diag.flag` only when correlating charged resources.

Scenario:

- Open city construction UI.
- Compare displayed cost and eligibility.
- Build an affected structure.
- Confirm charged resources and final built state.

Required evidence:

- City SID/faction.
- Building SID/category.
- Displayed cost.
- Charged cost.
- Eligibility result.
- Build commit result.
- Same-day build state.
- Ordering around building view bind, building session select/cost, building manager state/refresh, resource mutation, and final constructed-state change.

## Gating, summon, and temporary stack capture

Flags:

- Use future Gating/summon law diagnostic flag after the exact surface exists.
- Do not use battle visual diagnostics as gameplay proof.

Scenario:

- Summon or gate a temporary stack.
- Observe ownership, entry timing, lifetime, death/despawn, and loss accounting.

Required evidence:

- Source ability/spell.
- Spawned stack SID.
- Owner side.
- Temporary/gated state source.
- Lifetime/despawn/death reason.
- Whether battle result counts losses.

## Corpse and mana capture

Flags:

- Use future corpse/mana law diagnostic flag after the exact surface exists.
- Add battle result and spell cooldown diagnostics only for correlation.

Scenario:

- Kill living and nonliving stacks.
- Finish battle with different casualty profiles.
- Trigger corpse spend or corpse-to-mana candidate only after a surface exists.

Required evidence:

- Corpse-eligible deaths.
- Corpse pool or logical corpse state.
- Consumption event.
- Hero mana before/after.
- Cleanup timing.
- Cooldown or spell effect interaction if consumed.

## Morale capture

Flags:

- `homm3_morale_trigger_law_diag.flag`
- Add battle-event diagnostics for action correlation.

Scenario:

- Trigger positive morale.
- Trigger negative morale if possible.
- Observe whether the action queue grants or removes an action.

Required evidence:

- Roll candidate method.
- Unit and morale stat context.
- Boolean roll result.
- Visible extra-action or failure behavior.
- Action queue ordering.
- Active law/rank in the same unit/side context.

## After a successful proof

- Store raw evidence with `tools/release_port/collect_custom_law_capture.py` or an equivalent manually named bundle.
- Update `AGENTS.md` from runtime-unproven to proven, with exact scenario and log evidence.
- Update the relevant batch in `docs/custom_law_no_compromise_batches.md`.
- Update `docs/custom_law_surface_activation_packets.md` if the packet boundary changes.
- Only then implement the smallest gameplay slice for that proven surface.
