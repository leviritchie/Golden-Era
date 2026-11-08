# Custom Law No-Compromise Recovery Batches

This document tracks the recovery path from donor-effect compromise rows back to the original custom faction law vision. It is intentionally strict: donor rows may remain as temporary displayed/data-safe implementations, but they are not treated as the design target when they flatten faction identity.

Status labels:

- `proven`: confirmed by static decomp evidence and runtime behavior.
- `static evidence`: directly visible in decomp/ISIL/Core rows, but not runtime-proven in the mod.
- `probe required`: a native surface is plausible but must be proven before mutation.
- `blocked`: do not approximate; leave disabled until a single native-friendly solution exists.

## June 16 validation checkpoint: build/deploy and first static gate

Build validation:

- `dotnet build "Heroes of Might & Magic Olden Era Playtest\OfflineUnlockMod\OfflineUnlockMod.csproj" -c Release --no-restore -v:minimal -clp:ErrorsOnly -p:DeployPluginToGame=false` succeeded with 0 errors and 45 warnings.
- Earlier deploy build `dotnet build "Heroes of Might & Magic Olden Era Playtest\OfflineUnlockMod\OfflineUnlockMod.csproj" -c Release --no-restore -v:minimal -clp:ErrorsOnly` succeeded with 0 errors and 33 warnings.
- `homm3_custom_faction_law_diag.flag` was created in the Golden Era plugin root for startup registration logging. Startup registration visibility is now proven from a fresh deployed DLL: source and deployed SHA256 matched `292C9D6D8831D444522166E2FED577EEEA336847818B4368D148650FE66D8F3B`, and `BepInEx\LogOutput.log` lines 454-455 logged packet proof gate states plus no-compromise handler slots.

Non-strict static gate:

- `python tools/release_port/check_custom_law_no_compromise_static.py` now passes.
- Fixed debt: target matrix normalization, missing law index `19` target entries for Dungeon/Fortress/Rampart, packet gate drift, unit-family registry drift, and explicit compromise/runtime-debt notes for concrete non-final donor rows.
- The passing gate now includes hardened checks: all top-level C# sources are scanned for direct law/packet API usage, packet-gate generation fails on unmapped target family indices, and override rows must use explicit compromise/runtime-debt/packet language rather than vague donor-substitute wording.
- Remaining warnings are explicit missing override rows for `castle_6`, `cove_6`, `cove_25`, `fortress_25`, `tower_25`, `inferno_25`, and `necropolis_25`. Treat these as source-row coverage questions, not hidden fallback permission. `castle_34` is now covered by a supported donor compromise using `unitStat inComingBuffDuration +1` on Castle units; this is source-prepared and unvalidated.

Startup registration logs are proven, but no gameplay packet is proven. Do not consume packet-backed law state for gameplay until the relevant packet is promoted from reviewed runtime evidence.

## Batch 25: No-compromise target spec

Reason for batch: the current law override layer can display playable donor/native rows, but that makes it too easy for future work to mistake a temporary compromise for the original faction-law vision. The no-compromise target mechanics now have a dedicated authoring artifact.

Source slice added June 16:

- `custom_factions/custom_law_targets.json` records intended target mechanics by exact `fraction_law_homm3_<faction>_<index>` SID.
- Each target has an `implementationStatus`: `native-exact`, `needs-runtime`, `temporary-compromise`, or `blocked`.
- Resource Riches remains excluded because it is universal by design.
- Castle remains the vanilla baseline, with native-exact rows where the mechanic truly matches.
- The target spec now includes law index `15` as the lower spell-school/access row and maps it to the `spell-cooldown` packet. This closes the prior coverage gap where runtime constants and override files tracked index `15` but the no-compromise target packet list did not.
- `tools/release_port/validate_custom_law_targets.py` validates the spec shape, law SID pattern, family packets, supported statuses, Resource Riches exclusion, duplicate rows, and current override SID presence.
- The validator passes through the combined static gate. It proves only static authoring consistency; it does not prove gameplay readiness.
- `tools/release_port/validate_custom_law_runtime_index_coverage.py` validates that every `Homm3CustomFactionLawRuntime.KnownRuntimeLawIndices` index has a target family entry, and every target family index is known to runtime.
- The runtime-index coverage validator passes through the combined static gate. It proves only static coverage between target data and runtime constants.
- `tools/release_port/validate_custom_law_target_matrix.py` validates that every enabled custom faction manifest has exactly one target entry for every tracked target family.
- The target-matrix validator passes through the combined static gate after the law index `19` fixes. It proves only static matrix coverage.
- `tools/release_port/report_custom_law_target_coverage.py` emits a Markdown planning report from the target spec, grouped by implementation status and activation packet.
- The report script has not been run in this slice. It is intended to keep `temporary-compromise` and `needs-runtime` laws visible, not to prove implementation correctness.
- `tools/release_port/audit_custom_law_overrides_against_targets.py` audits current `custom_factions/law_overrides/*.json` rows against the target spec.
- The override audit script passes through the combined static gate after explicit compromise/runtime-debt notes were added to concrete non-final donor rows. It should fail if future tracked non-native-exact targets gain concrete `parametersPerLevel` rows without explicit compromise/runtime-debt notes, or if a tracked law-family override has no target entry.
- `custom_factions/custom_law_diag_profiles.json` now mirrors target packet names for `vision` and `counterattack` in addition to the existing packet profiles.
- `tools/release_port/validate_custom_law_diag_profiles.py` validates that every packet used by `custom_law_targets.json` has a matching diagnostic profile and that non-law-tree profiles include `homm3_custom_faction_law_diag.flag`.
- The diagnostic profile validator passes through the combined static gate. Passing proves only static flag-profile coverage, not runtime behavior.
- `custom_factions/custom_law_packet_proofs.json` records packet proof state. Every current packet is `runtime-unproven` with `gameplayAllowed=false`.
- `tools/release_port/validate_custom_law_packet_proofs.py` validates packet proof coverage and prevents `gameplayAllowed=true` unless the packet is `runtime-proven` with an evidence artifact recorded.
- The packet proof validator passes through the combined static gate. Passing proves only proof-ledger shape, not runtime behavior.
- `tools/release_port/promote_custom_law_packet_proof.py` provides the controlled path to promote one packet after reviewed runtime evidence. It requires an existing evidence artifact, scenario, flags, exact native symbols, consumed state, mutated state, docs-updated note, summary, and explicit `--confirm I_REVIEWED_RUNTIME_EVIDENCE`.
- The packet proof promotion tool has not been run in this slice. It edits only `custom_law_packet_proofs.json`; packet gate regeneration/check, build validation, and stale-doc cleanup remain separate required steps.
- `Homm3CustomLawPacketGate.cs` adds the runtime-side fail-closed API for packet-backed gameplay. It maps known custom law indices to packet names and currently denies every packet with the proof-ledger runtime-unproven reason.
- The runtime packet gate is build-validated and unconsumed by gameplay hooks in this slice. It now maps law index `15` to `spell-cooldown`; it mutates no native state and authorizes no mechanics.
- `Homm3CustomLawRuntimeGuard.cs` adds the combined runtime guard future hooks should call. It resolves active custom law/rank and then requires packet gameplay permission before returning an allowed law context.
- The combined guard is build-validated and currently always fails for packet-backed gameplay because every packet remains runtime-unproven.
- `Homm3CustomLawHandlerRegistry.cs` adds named handler slots for every tracked no-compromise law family. Future gameplay hooks should enter through a slot such as `counterattack.doctrine`, `reward.gold-economy`, or `spell.cooldown`; the registry verifies handler key, law index, and packet mapping before delegating to `Homm3CustomLawRuntimeGuard`.
- The handler registry is build-validated and mutates no native state. Since all packets remain runtime-unproven, every handler entry currently fails closed through the existing proof gate.
- `tools/release_port/audit_custom_law_runtime_guard_usage.py` audits custom law C# source files for direct `Homm3CustomFactionLawRuntime.TryResolveActiveKnownCustomLaw` or `Homm3CustomLawPacketGate.Is*GameplayAllowed` usage outside diagnostics/runtime infrastructure. It now treats `Homm3CustomLawHandlerRegistry.cs` as infrastructure and warns when gameplay files use the lower-level guard directly instead of a named handler slot.
- The runtime guard usage audit passes through the combined static gate. It proves only static source hygiene, not build or runtime behavior.
- `tools/release_port/validate_custom_law_handler_registry.py` validates that `Homm3CustomLawHandlerRegistry.cs` has exactly one named handler slot for every target family law index and that each slot uses the family-derived packet.
- The handler registry validator passes through the combined static gate. Passing proves only static handler-slot coverage, not build or runtime behavior.
- `Homm3CustomFactionLawRuntime.TryRegister(...)` now logs `Homm3CustomLawPacketGate.DescribeKnownProofStates()` and `Homm3CustomLawHandlerRegistry.DescribeHandlerSlots()` behind `homm3_custom_faction_law_diag.flag`, so runtime law diagnostics expose the current all-denied packet proof gate and compiled handler-slot map.
- The packet proof-state and handler-slot diagnostic snapshot is build-validated and startup-proven. It is only a visibility aid and does not consume packet or handler state for gameplay.
- `tools/release_port/generate_custom_law_packet_gate.py` generates or checks `Homm3CustomLawPacketGate.cs` from `custom_law_targets.json` plus `custom_law_packet_proofs.json`.
- `tools/release_port/generate_custom_law_packet_gate.py --check` is now part of the combined static gate and passes after regeneration.
- `tools/release_port/check_custom_law_no_compromise_static.py` runs target validation, diagnostic-profile validation, override-target audit, unit-family tag validation, and registry drift check as one fail-closed static gate.
- The static gate passes in this slice. It does not build the plugin, launch the game, mutate Core, review captures, or prove runtime behavior.
- `tools/release_port/generate_custom_law_implementation_queue.py` emits a Markdown or JSON implementation backlog from the target spec, ordered by packet/status/faction/law.
- The implementation queue generator has not been run in this slice. Generated output is planning evidence only and must not be treated as validation.
- `tools/release_port/report_custom_law_strict_candidate_rows.py` emits a Markdown planning report showing each target law's source bonus count, family-derived packet, and strict-candidate action.
- The strict candidate row report has not been run in this slice. It is intended to make the strip-or-implement queue explicit, not to prove behavior.
- `tools/release_port/check_custom_law_no_compromise_static.py --write-reports` can write `artifacts/custom_law_static/custom_law_target_coverage.md` and `artifacts/custom_law_static/custom_law_implementation_queue.md`, but only after all static checks pass.
- `tools/release_port/check_custom_law_no_compromise_static.py --write-reports` now also writes `artifacts/custom_law_static/custom_law_strict_candidate_rows.md`.
- The report-writing gate has not been run in this slice. Generated files under `artifacts/custom_law_static` are not runtime proof.
- `tools/release_port/validate_custom_law_strict_no_compromise_rows.py` adds a stricter candidate validator. It resolves packet names from target family definitions and fails closed if family/packet data is missing. In source mode, every non-`native-exact` target must have an explicit override row and that row must not contain concrete bonuses. In `--core` mode, generated Core target rows are inspected for concrete bonuses on non-final targets, and stripped non-final rows must have pending descriptions that name the target mechanic and packet.
- `tools/release_port/check_custom_law_no_compromise_static.py --strict-no-compromise-law-rows` adds that strict validator to the combined static gate. It is expected to fail while temporary donor compromises remain, and that failure is useful evidence rather than a regression.
- `tools/release_port/apply_release_core_overlay.py --strict-no-compromise-law-rows` runs strict source-row validation before overlay output generation and strict candidate-Core validation before release replacement.
- `tools/release_port/apply_release_core_overlay.py --strip-nonfinal-no-compromise-law-bonuses` strips concrete generated bonuses from non-`native-exact` target rows and stamps `xHomm3NoCompromiseStrictRows` so strict candidate output cannot hide donor effects.
- The same strict strip transform rewrites stripped law description tokens in `Lang/english/texts/factionLaws.json` to say the law is pending no-compromise implementation, name the target mechanic, and name the required packet. This prevents strict candidate rows from showing donor-effect text after their concrete bonuses are removed.
- When strict stripping is enabled, overlay source-row strict validation is skipped because playable source overrides may still contain temporary donor rows; candidate-Core strict validation still runs if `--strict-no-compromise-law-rows` is also enabled.
- The strict validator, strict combined-gate mode, strict overlay mode, and strict strip transform have not been run in this slice. They prove only absence of concrete donor/native bonuses on non-final target rows in the checked artifact, not gameplay behavior.
- `tools/release_port/apply_release_core_overlay.py --require-no-compromise-law-static` runs the combined no-compromise law static gate before overlay output generation and fails the overlay if law static hygiene fails.
- The overlay preflight flag has not been run in this slice. It is opt-in for now to avoid blocking unrelated overlay workflows before the static gate has been repaired and explicitly validated.
- `tools/release_port/apply_release_core_overlay.py` now stamps generated custom law rows with no-compromise target metadata when a target exists: `xHomm3NoCompromiseTarget`, `xHomm3NoCompromiseStatus`, `xHomm3NoCompromisePacket`, and `xHomm3NoCompromiseTargetMechanic`.
- The law row metadata stamping has not been run in this slice. It changes generated row traceability only; it does not change `parametersPerLevel`, law behavior, or runtime proof state.
- `tools/release_port/validate_custom_law_core_metadata.py --core <Core.zip>` validates post-overlay Core output for those `xHomm3NoCompromise*` metadata fields on every target-backed custom law row.
- The Core metadata validator has not been run in this slice. Passing it would prove metadata traceability in a specific Core.zip only, not law behavior or packet proof.
- `tools/release_port/apply_release_core_overlay.py --validate-no-compromise-law-core-metadata` runs that Core metadata validator against the candidate Core.zip after custom biome packing and before release Core replacement.
- The overlay metadata gate has not been run in this slice. It is opt-in and fail-closed for law-focused overlay runs, and it proves only generated row traceability in the candidate archive.

Policy:

- A `temporary-compromise` row is allowed to remain playable, but it is not the end state.
- A strict no-compromise candidate is different from the playable compromise path: non-`native-exact` rows must carry no concrete bonuses unless their packet is implemented and the target status is updated.
- Packet work should move laws toward `native-exact` or a proven runtime implementation.
- Do not add donor substitutes to satisfy `needs-runtime` targets unless the donor effect is an exact same-kind implementation and the target status is updated with evidence.
- Do not clear audit failures by deleting target rows or weakening statuses. Fix the row, add honest debt notes, or implement the packet.
- Use the static gate before claiming target/profile/override/unit-family hygiene, but keep runtime packet proof separate.
- Use the generated queue to pick the next packet batch; do not hand-maintain a competing implementation backlog.
- Refresh generated static reports only through the combined gate so stale or invalid target states do not produce authoritative-looking artifacts.
- Use `custom_law_strict_candidate_rows.md` to identify laws that must be stripped in strict candidates or replaced with packet-backed behavior; do not use it as proof that the strict candidate was built.
- Use `--strict-no-compromise-law-rows` only when intentionally checking the no-compromise candidate path. Do not use its expected failures as a reason to weaken target statuses or remove target rows.
- Use `--require-no-compromise-law-static` for law-focused overlay runs once the static gate is expected to pass. Do not treat that preflight as runtime proof.
- Use overlay `--strict-no-compromise-law-rows` only for strict candidate generation. It is not a replacement for implementing packet-backed mechanics; it is a guard against hidden donor effects surviving.
- Use `--strip-nonfinal-no-compromise-law-bonuses` only for strict candidate output. Stripped rows are intentionally unfinished and must not be described as implemented laws, even though their visible descriptions name the intended target mechanic.
- Core row metadata is traceability, not implementation. A row stamped `needs-runtime` or `temporary-compromise` must still be treated as unfinished until packet proof and gameplay implementation exist.
- After a law-focused overlay run, validate generated Core metadata with `validate_custom_law_core_metadata.py --core <Core.zip>` before using Core rows as evidence in later audits.
- Prefer adding `--validate-no-compromise-law-core-metadata` to law-focused overlay runs so missing row metadata stops the candidate before release replacement. Do not treat this as gameplay validation.
- Runtime law gameplay may only consume a packet after `custom_law_packet_proofs.json` records `proofStatus=runtime-proven`, `gameplayAllowed=true`, and a concrete evidence artifact.
- Packet promotion must use reviewed capture evidence. Do not promote from static decompilation, plausible reasoning, or an unreviewed raw log bundle.
- Do not treat missing target rows as out of scope. If the matrix validator fails, author an explicit target mechanic or explicitly remove the law family from the runtime target set with documentation.
- Future gameplay hooks must call `Homm3CustomLawPacketGate.IsGameplayAllowed(...)` or `IsLawIndexGameplayAllowed(...)` before mutating native state for a packet-backed law. A false result is not optional and must not be bypassed with donor rows.
- Prefer `Homm3CustomLawHandlerRegistry.TryEnterHandler(...)` in gameplay hooks. If a hook has not yet been assigned a named handler slot, use `Homm3CustomLawRuntimeGuard.TryResolveAllowedActiveLaw(...)` directly only as a temporary bridge and document the missing slot.
- Do not hand-promote packet proof state in C# only. Update the JSON proof ledger, regenerate/check the runtime gate, and document evidence.
- Do not silence runtime guard usage audit failures by renaming files or adding diagnostics suffixes to gameplay code. Either move the code through the named handler registry, use the combined guard only as a documented temporary bridge, or document why the file is truly diagnostic-only.
- Do not add a target law family without also adding a named handler registry slot and keeping the handler registry validator green.
- Diagnostic logs showing packet states or handler slots are not packet proof. They only show the currently compiled gate and handler-slot state.

## Batch 1: Counterstroke Doctrine

Reason for first batch: this family has the highest mismatch between the original faction-specific designs and the current donor-safe rows. It also provides a reusable combat event pipeline for later law families.

Current compromise layer:

- Castle uses native vanilla counterattack damage and remains the baseline.
- Inferno uses native extra counterattack charges and is effectively data-safe.
- Cove, Dungeon, Fortress, Necropolis, Stronghold, Tower, Conflux, and parts of Rampart are currently flattened into generic counterattack damage or counterattack-charge donor effects.

Target behavior:

- Castle `Shield Wall`: vanilla `+50%/+100%` counterattack damage. No custom hook expected.
- Cove `Boarding Hooks`: successful counterattacks generate `+1 Focus` for the Cove side.
- Dungeon `Outnumber`: counterattacks deal bonus damage only when the counterattacking stack has more living units than the attacker.
- Fortress `Thorned Hides`: successful counterattacks apply an Attack reduction debuff to the attacker.
- Rampart `Avenger's Reprisal`: counterattack bonus applies only against units marked by the real Avenger mechanic.
- Tower `Reactive Wards`: counterattack strength scales from the defending hero's Spell Power.
- Conflux `Elemental Backlash`: counterattacks deal an additional magic-damage component based on the counterattacking stack's strength.
- Inferno `Hellfire Reprisal`: native `+1` counterattack charge. No custom hook expected unless later design changes.
- Necropolis `Death Grip`: counterattack damage restores/reanimates the counterattacking stack by a percentage of dealt damage, clamped to its original stack size.
- Stronghold `Blood Feud`: each successful counterattack applies a stacking damage bonus to that stack for the rest of battle.

Static evidence gathered June 16:

- `Hex.Session.Battle.dxy` constructs `CastAbilityEventArgs` during ability execution and only calls `edb.bcry(object, BattleEventArgs)` when `CastDealerConfig.triggerCounter` is true.
- Current exact `dxy` methods with this trigger pattern are `bate`, `ldn`, and `cec`.
- `edb.bcry(object, BattleEventArgs)` is a concrete event dispatch surface for the triggered-counter path, not a final-damage surface by itself.
- `ell.bert(DamageUiParams,bool)` and `ell.hem(DamageUiParams,bool)` are current damage forecast/calculation candidates with `DamageUiParams`, but they are not accepted as gameplay mutation surfaces until runtime proof shows they participate in committed combat damage, not only UI forecasts.
- Existing native data rows support Castle-style `unitStat modifierSet outDmgMods counter_attack` and Inferno-style `unitStat numCounters`.

Source slice added June 16:

- `Homm3CounterstrokeDoctrineHook` registers only when `homm3_counterstroke_doctrine_diag.flag` is present.
- The hook patches exact request methods `dxy.bate`, `dxy.ldn`, and `dxy.cec`, plus exact dispatcher `edb.bcry`.
- The hook also patches exact damage-calculation candidates `ell.bert` and `ell.hem` for correlation logging only. These are still candidates, not accepted committed-damage surfaces.
- The hook logs bounded request/dispatch/damage-candidate diagnostics with shallow simple-member snapshots and active-law resolver snapshots of the exact hooked instance, args, and result so runtime proof can identify which wrapper carries actor identity and whether active law rank is visible in the same context. It does not mutate damage, buffs, Focus, law state, or stack state.
- `activeKnownCustomLawsFromThisObject=none-or-unresolved` means the exact resolver could not prove active law state from that specific object; it is not evidence that no law is active.
- `Homm3CustomFactionLawRuntime` now exposes `CounterstrokeDoctrineIndex = 13` and labels parsed custom law IDs in law-tree diagnostics, so `fraction_law_homm3_*_13` can be confirmed as the Counterstroke family before combat hooks consume law rank.
- If exact surfaces are not present, registration fails closed and custom Counterstroke laws remain disabled.
- Compile validation: `dotnet build "Heroes of Might & Magic Olden Era Playtest\OfflineUnlockMod\OfflineUnlockMod.csproj" -c Release --no-restore -v:minimal -clp:ErrorsOnly` succeeded with 0 errors and 45 warnings after the active-law resolver snapshot addition to Counterstroke traces. Runtime proof is still pending.
- Full deploy build note: `OfflineUnlockMod.csproj` now keeps loose `oldenera_factions\Assets\CustomUnits\homm3_lab` map/battle PNG sidecars out of default deploy builds via `DeployHomm3LooseLabPngSidecars=false`. This matches the documented May 20 release rule that runtime visuals are bundle-backed and loose PNG sidecars are not part of the public release payload. Set `-p:DeployHomm3LooseLabPngSidecars=true` only for legacy/source-side audits that intentionally need loose sidecars; do not create placeholder frames as a law-system workaround.
- Full deploy validation: `dotnet build "Heroes of Might & Magic Olden Era Playtest\OfflineUnlockMod\OfflineUnlockMod.csproj" -c Release --no-restore -v:minimal -clp:ErrorsOnly` succeeded with 0 errors after the loose sidecar deploy gate, proving the prior missing `h3_giant_upg` loose-frame copy error is gone.

Runtime proof procedure:

- Enable `homm3_counterstroke_doctrine_diag.flag`.
- Trigger a melee attack that causes a real counterattack.
- Capture the bounded log sequence for `request`, `dispatch`, and `damage-candidate` lines.
- With `homm3_custom_faction_law_diag.flag`, open a custom faction law tree and confirm the bind log parses index `13` as `Counterattack doctrine`; rank fields/getters are still diagnostic evidence only until proven.
- Confirm whether `activeKnownCustomLawsFromThisObject` proves active custom law rank from any Counterstroke request/dispatch/damage-candidate object in the same counterattack context; do not interpret `none-or-unresolved` as negative gameplay evidence.
- Treat `ell.bert`/`ell.hem` as implementation candidates only if they correlate with actual committed combat damage, not only hover/forecast UI.
- Use the shallow member snapshots only to choose the next exact field/getter probes. Do not implement gameplay from broad reflection snapshots directly.
- Do not enable faction-specific Counterstroke effects until the same trace also proves actor identity and active law rank.

## Batch 2: Economy and gold laws

Reason for second batch: economy/gold laws are lower-risk than battle mechanics and can collect useful proof from day-start/resource surfaces without requiring assistant-driven combat.

Target behavior:

- Castle `Prosperous Holdings`: keep native percent gold income as the vanilla baseline.
- Cove `Prize Shares`: grant bonus gold from plunder, treasure, creature banks, and defeated neutrals after real reward resolution.
- Dungeon economy law: reward conquest/underground clearing or mine/cave captures through committed reward/capture events.
- Fortress `Marsh Rights`: grant gold from defensive wins, native terrain control, or swamp structures. Start with defensive win and owned-structure day-start proof; terrain-control needs separate probing.
- Rampart `Preservation Tithe`: grant gold or astrology-style reward for low-loss wins or Avenger-marked enemy kills.
- Tower `Transmutation Ledger`: convert rare resources to gold or construction discounts through an explicit day-start/capped conversion path unless UI support proves an optional conversion flow.
- Necropolis `Mortuary Accounting`: generate gold from casualties/corpse sites, not visual corpse props.
- Stronghold `Spoils Ledger`: generate gold from aggression, neutral clearing, town/mine capture, or consecutive wins with idempotence.

Source slice added June 16:

- `Homm3CustomFactionEconomyLawDiagnostics` registers only when `homm3_custom_faction_economy_diag.flag` is present.
- The hook patches exact side day-start `dtj.OnStartDay()` and exact resource-add method candidates on `dti`.
- The hook logs bounded day-start/resource-add diagnostics with shallow simple-member snapshots. It does not grant or remove resources.
- The hook now attempts active custom law correlation on economy diagnostic instances and arguments only through `Homm3CustomFactionLawRuntime.TryResolveActiveKnownCustomLaw`; `activeKnownCustomLawsFromThisObject=none-or-unresolved` means the exact resolver could not prove active law state from that object, not that no law is active.
- The hook reuses centralized `GameSymbols.EconomyLaws` aliases for the same native side/resource surfaces proven by the existing Swashbuckler gold implementation.
- If exact surfaces are not present, registration fails closed and custom economy laws remain disabled.
- Build validation: `dotnet build "Heroes of Might & Magic Olden Era Playtest\OfflineUnlockMod\OfflineUnlockMod.csproj" -c Release --no-restore -v:minimal -clp:ErrorsOnly` succeeded with 0 errors after the first economy diagnostic hook addition, and again after the active-law correlation enrichment. Runtime proof is still pending.

Runtime proof procedure:

- Enable `homm3_custom_faction_economy_diag.flag`.
- Start or advance a day and confirm `side-start-day` logs show a stable side wrapper.
- Trigger ordinary gold/resource gains and confirm `resource-add` logs carry resource SID and amount.
- Confirm whether `activeKnownCustomLawsFromThisObject` proves active custom law rank from any economy diagnostic object in the same day-start/resource context; do not interpret `none-or-unresolved` as negative gameplay evidence.
- Do not implement Cove/Dungeon/Fortress/Rampart/Necropolis/Stronghold economy effects until reward/capture commit events are also proven; day-start/resource mutation alone is not reward classification proof.

## Batch 10: Reward commit and reward-source diagnostics

Reason for tenth batch: Batch 2 can observe generic resource mutations, but it cannot distinguish committed object rewards, optional reward sets, capture rewards, battle rewards, or day-start income. The no-compromise economy laws need exact reward identity and ordering before they can grant gold/resources without double-counting or silently firing from unrelated resource changes.

Target behavior:

- Cove `Prize Shares` should grant bonus gold only after real treasure/plunder/creature-bank/neutral-clear rewards are committed.
- Dungeon conquest/economy laws should classify committed underground/cave/mine rewards rather than generic gold changes.
- Fortress defensive/structure economy laws need to distinguish committed map rewards from daily economy and future battle-result rewards.
- Rampart preservation/Avenger reward laws need committed battle/reward ordering before low-loss or marked-target bonuses.
- Necropolis corpse/gold laws must not trigger from every resource mutation; they need committed reward or battle-result identity.
- Stronghold spoils laws need aggressive capture/neutral-clear reward identity with idempotence.

Static evidence gathered June 16:

- Existing Tower Bottomless Knowledge production code already patches the exact reward-set apply surface `czy` / `ObjectPrivateviVoaAc172b8058viUnique.Method_Public_Void_Hero_DataRewardSet_PDM_0` with `(Hero, DataRewardSet)` arguments for Mana Well Aegis filtering.
- Diffable Cpp2IL also names the same reward applier method `czy.vji(Hero, DataRewardSet)`.
- `DataRewardSet` exposes exact descriptive fields `showType`, `applyType`, `cancelType`, `cost`, `cantCompleteApplying`, `rewards`, `id`, `heroId`, `objectId`, `label`, and `selectionWindowType`.
- `DataReward` exposes exact descriptive fields `stringRewardType`, `rewardType`, `rewardShowType`, `applyRewardFloating`, `rewardIcon`, `rewardName`, `rewardDesc`, `rewardNotificationDesc`, and `parameters`.
- `DataRewardSets.bfus(DataRewardSet)` and `DataRewardSets.bfut(DataRewardSet)` are exact queue/remove candidates. They are not accepted as committed reward application by themselves.
- `ECmd.RewardSetApply = 98` exists as command evidence, but this slice does not patch command dispatch.

Source slice added June 16:

- `Homm3RewardCommitLawDiagnostics` registers only when `homm3_reward_commit_law_diag.flag` is present.
- The hook patches only exact reward-set apply names from centralized `GameSymbols.RewardCommitLaws`: `Method_Public_Void_Hero_DataRewardSet_PDM_0` and readable `vji`, if present on exact `czy`.
- The hook patches only exact `DataRewardSets.bfus` and `DataRewardSets.bfut` queue/remove candidates.
- The hook logs bounded reward-set id, heroId, objectId, label, apply/show/cancel types, and summarized reward item fields.
- The hook now attempts active custom law correlation on the reward applier/list owner, arguments, and reward set only through `Homm3CustomFactionLawRuntime.TryResolveActiveKnownCustomLaw`; `activeKnownCustomLawsFromThisObject=none-or-unresolved` means the exact resolver could not prove active law state from that object, not that no law is active.
- It does not grant/remove resources, mutate rewards, mutate law state, infer reward classification, or infer law state from heroId/objectId/labels.
- If exact methods are absent, registration fails closed and reward/capture economy laws remain disabled.
- Build validation: `dotnet build "Heroes of Might & Magic Olden Era Playtest\OfflineUnlockMod\OfflineUnlockMod.csproj" -c Release --no-restore -v:minimal -clp:ErrorsOnly` succeeded with 0 errors after the first reward commit diagnostic hook addition, and again after the active-law correlation enrichment. Runtime proof is still pending.

Runtime proof procedure:

- Enable `homm3_reward_commit_law_diag.flag`; optionally also enable `homm3_custom_faction_economy_diag.flag` to correlate reward application with resource additions.
- Pick up a loose reward, claim an object reward, resolve a selectable reward if available, and capture/clear a rewarding map object.
- Confirm whether `reward-set-queued`, `reward-set-removed`, and `reward-set-apply` logs fire in a stable order, and whether `heroId`, `objectId`, `label`, `rewardType`, `stringRewardType`, and `parameters` identify the reward source strongly enough for faction law classification.
- Confirm whether `activeKnownCustomLawsFromThisObject` proves active custom law rank from any reward object in the same committed reward context; do not interpret `none-or-unresolved` as negative gameplay evidence.
- Confirm idempotence boundaries: a single committed reward must correspond to exactly one future custom-law opportunity, even if it queues/removes UI choices or emits multiple resource additions.
- Do not implement reward/capture economy laws until runtime proof establishes committed apply ordering and source identity. Do not classify reward laws from generic `resource-add` alone.

Probe gates before gameplay mutation:

- Prove the exact runtime event order from `dxy` trigger-counter request to actual counterattack execution.
- Prove defender/counterattacker identity and attacker/original target identity on the event payload.
- Prove where committed damage is finalized, distinct from forecast-only UI calculation.
- Prove a side/hero/law-rank resolver can answer active faction law state inside battle without UI state.
- Prove native mutation surfaces for Focus, battle buffs/debuffs, HP restoration/revive, and extra magic damage before enabling the faction-specific effects that need them.

## Batch 3: Construction laws

Reason for third batch: construction laws are central to faction identity but must not be implemented from UI-only guesses. This batch traces exact generated town/building methods so later work can distinguish selected-building UI, displayed cost, charged cost, build validation, and committed construction.

Target behavior:

- Castle `Civic Engineers`: keep native `constructionDailyLimit([1])` as the vanilla baseline.
- Cove `Harbor Rush`: one extra market/tavern/cannon/pirate-infrastructure build per day; eligible buildings cost 20% less gold.
- Dungeon `Excavation Crews`: mine/cave/external-dwelling capture grants a side-scoped token for the next Dungeon dwelling build/upgrade as extra construction.
- Rampart `Living Groves`: dwellings mature after construction; matured dwelling upgrade can be an extra construction with reduced wood cost.
- Tower `Grand Workshop`: one extra magical/construct building per day with a gold surcharge.
- Inferno `Blood Mortar`: one extra building per day by sacrificing garrison creatures worth enough to cover the law's sacrifice threshold.
- Necropolis `Reanimated Masonry`: extra dwelling/converter construction by spending deathworks credit from casualties/captured dwellings; start with credit only.

Static evidence gathered June 16 and repaired June 17:

- Current decomp evidence exposes `Hex.Session.City.BhBuildingsManager.bajs(dwc,bool)`, `bajt(string)`, and `baju()` as building-manager candidate methods. Golden Era runtime interop registers them as exact state/lookup/refresh trace patches through centralized symbols and signature matching.
- Current decomp evidence exposes `Hex.UI.City.BhUIBuildingSession.tuc(int,int) -> int` and `tud(bfh)` as building-session candidate methods. `tuc` is a cost-like integer candidate by signature and owner only; runtime ordering must prove what it returns.
- Current decomp evidence exposes `Hex.UI.City.BhBuildingView.trr(fbs,dwc,int)` and `UpdateView()` as building-view context surfaces.
- `GameSymbols.ReleaseTownUi` already centralizes building data/model/config SID, level, and constructed-state names for UI context, but these remain UI/read surfaces until commit proof exists.

Source slice added June 16:

- `Homm3CustomConstructionLawDiagnostics` registers only when `homm3_custom_construction_law_diag.flag` is present.
- The hook patches only the exact methods listed above through centralized `GameSymbols.ConstructionLaws`, accepting a method only by centralized name hint or one unique exact signature match. Signature matching also checks `GameMember.ReadObfuscatedName(parameterType)` so decomp names such as `dwc`, `bfh`, and `fbs` match runtime interop type names without broad fallback.
- The hook logs bounded shallow context for building-manager, building-session, and building-view candidates. It does not alter construction limits, costs, resources, garrison creatures, building state, or law state.
- The hook now attempts active custom law correlation on construction diagnostic instances, arguments, and results only through `Homm3CustomFactionLawRuntime.TryResolveActiveKnownCustomLaw`; `activeKnownCustomLawsFromThisObject=none-or-unresolved` means the exact resolver could not prove active law state from that object, not that no law is active.
- If exact methods are absent, registration fails closed and custom construction laws remain disabled.
- Build validation: `dotnet build "Heroes of Might & Magic Olden Era Playtest\OfflineUnlockMod\OfflineUnlockMod.csproj" -c Release --no-restore -v:minimal -clp:ErrorsOnly` succeeded with 0 errors after the first construction diagnostic hook addition, and again after the active-law correlation enrichment. June 17 repair build with `-p:DeployPluginToGame=false` succeeded with 0 errors and 45 warnings.
- Startup registration proof: Golden Era launched with `homm3_custom_faction_law_diag.flag` and `homm3_custom_construction_law_diag.flag`; deployed DLL hash matched `C987FAC8FF0DC00EF23F2BED62B25B0EFD874C6523A0153ADDC82D2FA97B4F2D`; `BepInEx\LogOutput.log` lines 459-466 prove all 7 exact construction trace patches registered. This is surface-registration proof only, not construction packet gameplay proof.

Runtime proof procedure:

- Enable `homm3_custom_construction_law_diag.flag`.
- Open a custom-faction town building screen.
- Select an unbuilt building, observe logged `building-view-bind-candidate`, `building-session-select-candidate`, and any `building-session-cost-candidate` lines.
- Build a legal building and compare the event ordering around `buildings-manager-state-candidate`, `buildings-manager-refresh-candidate`, resource-add logs from `homm3_custom_faction_economy_diag.flag`, and visible UI refresh.
- Confirm whether `activeKnownCustomLawsFromThisObject` proves active custom law rank from any construction diagnostic object in the same selected/build context; do not interpret `none-or-unresolved` as negative gameplay evidence.
- Do not treat any single UI line as a construction commit. The minimum acceptable proof for gameplay mutation is a stable ordered sequence that identifies selected building SID/level, displayed cost, charged cost/resource mutation, and final constructed-state change.

## Batch 4: Spellbook, school access, and spell-cast diagnostics

Reason for fourth batch: spell-school and cooldown laws need exact spellbook/cast-gate knowledge before Tower, Conflux, Necropolis, Inferno, and Stronghold can recover their original designs. This slice traces exact spellbook data/UI and spell-cast event factories, but intentionally does not claim a cooldown storage or cast-gate surface yet.

Target behavior:

- Castle and other exact static school rows should continue using native `magicSchoolSet` data where the design is simple school access.
- Tower `Prepared Artifice` and `Overclocked Spellworks` need real spellbook reuse, prepared-charge, and cooldown proof before implementation.
- Conflux dynamic school/cooldown laws need runtime school/effective-access logic based on elemental-family state.
- Necropolis corpse-fuel cooldowns, Inferno sacrificial casting, Cove reload credits, Rampart Avenger patience, Dungeon debuff-kill resets, Fortress enemy cooldown penalties, and Stronghold Warcry cooldowns all need proven cast/cooldown gates and trigger sources.

Static evidence gathered June 16:

- Diffable Cpp2IL exposes `Hex.Session.Data.HeroMagics.bfxw(string) -> MagicData`, `bfxx(HeroMagics)`, and `bfxy() -> int` as hero spell-list candidates.
- Diffable Cpp2IL exposes `Hex.Session.Data.DataMagics.bftu(string) -> MagicData` and `bftw(string) -> int` as global spell-data lookup/index candidates.
- Diffable Cpp2IL exposes `Hex.Session.UI.BhMagicBookView.Init(dva)`, `Show()`, private `UpdateView(int,BhMagicBookPageView,int)`, filter methods `zhq(EMagicType)`, `zhs/zht/zhu(ESchool)`, and `zhy(int,int)` as spellbook UI/view candidates.
- Diffable Cpp2IL exposes `Hex.Session.Battle.CastMagicEventArgs.bctq(eir,eew,int[])` and `bcts(eir,eew,List,List)` as battle spell-cast event factories.
- `CastMagicEventArgs` fields include `casterSide`, target/affected hex lists, `attackedObjects`, and `castedMagic`; this is event construction evidence, not proof of committed cast/cooldown application.
- No exact stored-cooldown, effective-cooldown, or cast-gate mutation surface is proven in this slice. `HeroAbilityEndCdEventArgs` exists, but that is hero-ability cooldown evidence and not accepted as spell cooldown proof.

Source slice added June 16:

- `Homm3SpellbookLawDiagnostics` registers only when `homm3_spellbook_law_diag.flag` is present.
- The hook patches only exact methods listed above through centralized `GameSymbols.SpellbookLaws`.
- The hook logs bounded spellbook data, spellbook UI, and cast-event factory context. It does not alter spell access, spellbook rows, cooldown state, cast gates, mana, battle events, or law state.
- The hook now attempts active custom law correlation on spellbook diagnostic instances, arguments, and results only through `Homm3CustomFactionLawRuntime.TryResolveActiveKnownCustomLaw`; `activeKnownCustomLawsFromThisObject=none-or-unresolved` means the exact resolver could not prove active law state from that object, not that no law is active.
- If exact methods are absent, registration fails closed and custom spellbook/cooldown laws remain disabled.
- Build validation: `dotnet build "Heroes of Might & Magic Olden Era Playtest\OfflineUnlockMod\OfflineUnlockMod.csproj" -c Release --no-restore -v:minimal -clp:ErrorsOnly` succeeded with 0 errors after the first spellbook diagnostic hook addition, and again after the active-law correlation enrichment. Runtime proof is still pending.

Runtime proof procedure:

- Enable `homm3_spellbook_law_diag.flag`.
- Open a hero spellbook and switch school/type filters; expect `magic-book-init`, `magic-book-show`, `magic-book-update-view`, `magic-book-type-filter`, and `magic-book-school-filter` logs.
- Select/cast a battle spell in user-driven combat; expect one of the `cast-magic-*-factory` logs if these are on the real event path.
- Correlate `HeroMagics` and `DataMagics` lookup logs with the visible spellbook and cast event. Do not fabricate spellbook entries or dynamic school access until this correlation is proven.
- Confirm whether `activeKnownCustomLawsFromThisObject` proves active custom law rank from any spellbook diagnostic object in the same spellbook/cast context; do not interpret `none-or-unresolved` as negative gameplay evidence.
- Do not implement cooldown reductions, credits, resets, enemy cooldown penalties, or once-per-round spell reuse until a separate runtime trace proves stored cooldown, effective cooldown, and native cast gate ordering.

## Batch 5: Adventure vision and reveal diagnostics

Reason for fifth batch: adventure vision laws are required for faction-specific scouting, object reveals, and later reward/capture classification. This slice traces exact fog-read, map-magic registry, and native magic-vision object descriptor surfaces without mutating visibility.

Target behavior:

- Cove `Sea Charts`: reveal treasure caches, pirate hideouts, creature banks, and high-value neutral camps near owned Cove structures.
- Fortress `Marsh Sense`: owned Fortress towns/dwellings/swamp structures reveal nearby enemy heroes at turn start.
- Rampart `Avenger's Trail`: reveal real Avenger-marked or favored enemy hero/army state without creating a second mark registry.
- Tower `Observatory Network`: owned Tower towns/observatories reveal artifacts and small nearby regions.
- Conflux `Planar Attunement`: reveal elemental shrines/dwellings/magic sites tied to the current dominant elemental family.
- Inferno `Hellgate Omens`: reveal existing Pocket Dimensions, teleporters, Inferno dwellings, and summoning sites only.
- Necropolis `Gravesight`: reveal graveyards, recent battle/corpse sites, undead dwellings, and corpse-rich logical locations only if such data exists.
- Stronghold `War Scouts`: reveal weaker neutral stacks from real native stack strength/intention data, not text labels.

Static evidence gathered June 16:

- Diffable Cpp2IL exposes `Hex.Session.Data.DataFogOfWar.bfri(int,int)` as fog map initialization, `bfrj(int) -> bool` as a visibility/hidden read candidate, and `bfrl() -> int` as a fog count/stat candidate.
- ISIL shows `DataFogOfWar.bfri` allocates and sizes the `visibilityMap`; it is not a reveal API.
- ISIL shows `DataFogOfWar.bfrj` reads `visibilityMap[index]` and returns a boolean, but the exact visible-vs-hidden polarity must be runtime-correlated before gameplay uses it.
- Diffable Cpp2IL exposes `Hex.Session.Data.MapMagics.bgca(string)` / `bgcb(string)` as map-magic add/lookup candidates.
- Diffable Cpp2IL exposes native `Hex.Map.MapVisionObjectDesc` factories: `City(int)`, `Hero(int)`, `Item(int)`, `okz(int)` for squad-like classification, and `ola(string)` for by-SID classification.
- No exact fog write/reveal API, object ownership event, structure-radius reveal loop, neutral strength classifier, or active-law turn-start resolver is proven in this slice.

Source slice added June 16:

- `Homm3AdventureVisionLawDiagnostics` registers only when `homm3_adventure_vision_law_diag.flag` is present.
- The hook patches only exact methods listed above through centralized `GameSymbols.AdventureVisionLaws`.
- The hook logs bounded fog, map-magic, and map-vision descriptor context plus active-law resolver snapshots for instances, arguments, and results. It does not mutate fog, reveal tiles, create map vision objects, change map magic counters, or consume law state.
- `activeKnownCustomLawsFromThisObject=none-or-unresolved` means the exact resolver could not prove active law state from that specific object; it is not evidence that no law is active.
- If exact methods are absent, registration fails closed and custom adventure vision laws remain disabled.
- Build validation: `dotnet build "Heroes of Might & Magic Olden Era Playtest\OfflineUnlockMod\OfflineUnlockMod.csproj" -c Release --no-restore -v:minimal -clp:ErrorsOnly` succeeded with 0 errors and 45 warnings after the active-law resolver snapshot addition. Runtime proof is still pending.

Runtime proof procedure:

- Enable `homm3_adventure_vision_law_diag.flag`.
- Load an adventure map and move a hero or reveal ordinary terrain; confirm `fog-initialize`, `fog-visibility-read`, and/or `fog-count-candidate` logs with bounded output.
- Use any native magic-vision/reveal spell or object, if available, and confirm whether `map-vision-*` descriptor logs appear for cities, heroes, items, squads, or by-SID objects.
- Trigger or inspect map magic usage and confirm whether `map-magic-add` / `map-magic-lookup` logs represent real reveal spell usage or only data lookup.
- Do not implement reveal laws until a separate exact native write/reveal API is proven and object classification/ownership/law-rank inputs are runtime-correlated in the same trace.

## Batch 6: Battle event law diagnostics

Reason for sixth batch: morale, formation, and training laws need real battle event surfaces instead of donor stat rows. This slice traces exact event payload construction and proven dispatcher names without mutating combat state.

Target behavior:

- Formation laws need real unit position, ranged/melee context, first-volley/first-melee timing, and owning side/faction correlation.
- Training laws need committed damage, death, cast, spawn, and resource/mana ordering before any stat or damage mutation.
- Morale laws need a true morale-success/failure or additional-action surface; energy updates may be related, but are not accepted as a substitute without runtime proof.

Static evidence gathered June 16:

- Diffable Cpp2IL declares battle event payloads for `UnitPosChangedEventArgs`, `UnitStartedMovementEventArgs`, `ObjectTookDamageEventArgs`, `ObjectDestroyedEventArgs`, `EnergyUpdateEventArgs`, `EnergyUpdatedByMechEventArgs`, and `SideUsedEnergyEventArgs`.
- `BattleEventArgs` declares exact base fields `target` and `roundNumber`.
- `UnitPosChangedEventArgs` declares exact field `targetHex`.
- `UnitStartedMovementEventArgs` declares exact fields `moveTime`, `startTime`, `pathLength`, `id`, `moveType`, and `path`.
- `ObjectTookDamageEventArgs` declares exact fields `caster`, `castSource`, `damageReceiver`, `dealer`, `damage`, `stacksDestroyed`, `immuneToDamage`, `cumulative`, and `fromMech`.
- `ObjectDestroyedEventArgs` declares exact fields `castSource`, `caster`, `destroyedObject`, and `isTimeout`.
- `CastAbilityEventArgs` declares exact fields `attackedObjects`, `attackedHexes`, `abilityID`, `abilityName`, `caster`, and `immuneObjectsOut`.
- `AbilityID` declares exact fields `abilityType` and `indexInArray`; static enum labels show `DefaultAttack`, `CounterAttack`, `AlternativeAttack`, and `Ability`.
- `AbilityLogicConfig` declares exact classification/config fields including `rank`, `cd`, `charges`, `energyLevel`, `dontUseEnergy`, serialized `attackType_`, serialized `castType_`, `moveType`, `actionCost`, and exact attack-type getter candidates `cndd` / `rod`.
- `CastDealerConfig` declares exact classification fields including `attackPatternSid`, `triggerCounter`, `sideCastType`, damage ranges, shoot-range/shoot-damage fields, serialized target/damage/selection fields, and getter candidates for damage/target/multitarget enums.
- `Hex.Session.Battle.Hex` declares exact coordinate fields `index`, `x`, and `z`, plus an exact current occupant backing field/getter.
- `Hex.Session.Battle.Unit` declares exact config/data members for `UnitLogicConfig`, `UnitViewConfig`, and `UnitData`; `UnitLogicConfig` exposes `baseSid`, `upgradeSid`, `fraction`, and `tier`.
- `Hex.Session.Battle.Unit.bbgw(eab,eac,dzx,int,EMechType,bool,float,bool)` is the exact current concrete Unit damage-apply candidate. Static declaration alone does not prove committed ordering, but it is a stronger candidate than forecast surfaces such as `ell.bert` / `ell.hem`.
- Battle objects expose side access through exact `basa()` via the `eab` / `edk` interfaces; this is side identity evidence only until the active-law resolver proves it can resolve `DataFractionLaws` from that object at runtime.
- ISIL shows damage/destruction paths constructing `ObjectTookDamageEventArgs` / `ObjectDestroyedEventArgs`.
- ISIL shows damage/destruction dispatch calls through exact names `eda.bcjc` and `edb.bcso`.
- Energy event args are observed by battle UI listeners, but this is not gameplay mutation proof.

Source slice added June 16:

- `Homm3BattleEventLawDiagnostics` registers only when `homm3_battle_event_law_diag.flag` is present.
- The hook patches exact event-arg constructors, including `CastAbilityEventArgs`, and exact dispatcher names through centralized `GameSymbols.BattleEventLaws`.
- The June 16 committed-damage slice also patches exact `Unit.bbgw(...)` as `damage-apply-candidate` under the same diagnostic flag.
- The hook logs bounded event instance, exact event fields, cast ability identity, ability/dealer classification context, unit config context, hex coordinates/path endpoints, simple payload fields, arguments, and native obfuscated type names.
- When an exact battle side is readable from a battle object, the hook calls `Homm3CustomFactionLawRuntime.TryResolveActiveKnownCustomLaw` for `KnownRuntimeLawIndices` and logs a bounded `activeKnownCustomLaws` summary if exact active custom laws can be proven.
- If no active known custom law is proven in a battle side context, the diagnostic logs `none-or-unresolved`; this must not be interpreted as proof that no law is active.
- `GameSymbols.BattleEventLaws` now centralizes the exact battle event, Unit, UnitLogicConfig, UnitViewConfig, Hex, and battle-object member names used by the diagnostic enrichment.
- It does not mutate battle state, energy, morale, position, damage, death, action queue, or law state.
- Build validation: `dotnet build "Heroes of Might & Magic Olden Era Playtest\OfflineUnlockMod\OfflineUnlockMod.csproj" -c Release --no-restore -v:minimal -clp:ErrorsOnly` succeeded with 0 errors after the original battle-event diagnostic hook addition. The June 16 event-context enrichment, damage-apply candidate addition, attack/cast classification enrichment, and battle-side active-law summary also build-validated with 0 errors. Runtime proof is still pending.

Runtime proof procedure:

- Enable `homm3_battle_event_law_diag.flag`.
- Enter user-driven combat and perform movement, attacks, kills, ability/spell use, and any morale/energy-changing action available.
- Confirm which event constructors and dispatchers appear, their ordering, and whether enriched payloads expose usable unit SID/base/upgrade/faction/tier, side, hex index/x/z, movement path, damage receiver, damage amount, destroyed object, and round context.
- Confirm whether `CastAbilityEventArgs.abilityID.abilityType`, `AbilityLogicConfig.attackType_` / `cndd`, and `CastDealerConfig.sideCastType` / `attackPatternSid` correlate with visible default attacks, counterattacks, alternate attacks, ranged attacks, melee attacks, spells, and hero abilities.
- Confirm whether `damage-apply-candidate` appears before the corresponding `object-took-damage` constructor/dispatch and whether the receiver/caster/dealer/damage values correlate with visible committed damage, not hover/forecast UI.
- Confirm whether battle side contexts report expected `activeKnownCustomLaws` for the currently open/custom faction and whether index/rank/faction/family match the visible law tree. If logs say `none-or-unresolved`, inspect law-tree diagnostics before treating the side context as unusable.
- Treat UnitLogicConfig and Hex fields as implementation candidates only after live logs prove they correspond to the visible attacker/defender/moved stack in the same event ordering.
- Treat attack/cast classification values as implementation candidates only after live logs prove their mapping for each visible action type. Do not infer first-volley, ranged/melee, counterattack, or hero-ability semantics from static enum names alone.
- Do not implement formation, training, counterstroke damage mutation, or morale mutation until the event trace is correlated with active law rank, owning side/faction, committed damage ordering, and the intended visible combat behavior.

## Batch 11: Battle result commit diagnostics

Reason for eleventh batch: several no-compromise laws need committed post-battle facts rather than combat animations, forecast UI, or generic reward/resource events. Necropolis corpse economy, Stronghold spoils, Rampart low-loss rewards, Fortress defensive rewards, Dungeon conquest rewards, and Cove neutral-clear plunder all need a stable post-battle identity surface.

Target behavior:

- Necropolis corpse/death economy laws should read real enemy losses, corpse eligibility, winning side, and hero/faction identity after combat resolution.
- Stronghold spoils laws should trigger from committed wins/captures/neutral clears, not from every gold/resource mutation.
- Rampart preservation laws should measure actual losses from the starting transfer side to the resolved transfer side.
- Fortress defensive reward laws should eventually distinguish attacker/defender/winner and owned structure context.
- Dungeon and Cove reward laws should correlate battle-result wins with later reward/capture events without double counting.

Static evidence gathered June 16:

- Existing Skeletal Necromancy production code already patches exact battle-result world-apply surface `eff.bdol(eep,bool)` / generated `ObjectPublicDi2InObcfLi1cnObcfUnique.Method_Public_Void_ObjectPublicPrcfInPrcfSiBoPrcfInUnique_Boolean_0`.
- Existing centralized symbols identify battle logic transfer fields for `transferBattle`, `startedTransferBattle`, `BattleResultInfo`, `appliedToWorld`, and `id`.
- Existing production code reads `BattleResultInfo.winnerIndex`, loser indices, `TransferBattle.sides`, `TransferSide.hero`, and `TransferSide.units` to compute Necropolis skeleton rewards.
- This is strong static/native evidence for post-battle identity, but law integration still needs runtime proof that the diagnostic ordering and active law-rank access line up with user-visible result application.

Source slice added June 16:

- `Homm3BattleResultLawDiagnostics` registers only when `homm3_battle_result_law_diag.flag` is present.
- The hook patches only the exact battle-result apply names through centralized `GameSymbols.BattleResultLaws`.
- The hook logs bounded pre/post apply summaries: battle id, applied flag, winner index, loser indices, started/after side counts, side hero SIDs, unit counts, total stacks, and per-side lost stack summaries.
- The hook now attempts active custom law correlation on the battle logic, started/after transfer battles, and started/after transfer sides only through `Homm3CustomFactionLawRuntime.TryResolveActiveKnownCustomLaw`; `none-or-unresolved` means the exact resolver could not prove active law state from that object, not that no law is active.
- It does not mutate transfer sides, grant units/resources, alter battle results, alter rewards, or consume law state.
- If the exact surface is absent, registration fails closed and post-battle law gameplay remains disabled.
- Build validation: `dotnet build "Heroes of Might & Magic Olden Era Playtest\OfflineUnlockMod\OfflineUnlockMod.csproj" -c Release --no-restore -v:minimal -clp:ErrorsOnly` succeeded with 0 errors after the first battle-result diagnostic hook addition, and again after the active-law correlation enrichment. Runtime proof is still pending.

Runtime proof procedure:

- Enable `homm3_battle_result_law_diag.flag`; optionally also enable `homm3_reward_commit_law_diag.flag` and `homm3_custom_faction_economy_diag.flag` to correlate post-battle apply with reward/resource events.
- Enter user-driven combat and finish a battle with losses on at least one side.
- Confirm `pre-apply` and `post-apply` logs show stable battle id, winner, losers, hero SIDs, and loss deltas matching the visible battle result.
- Confirm whether `appliedToWorld` flips between pre/post and whether logs fire exactly once per committed battle result.
- Confirm whether `battleLogicLaws`, `startedBattleLaws`, `afterBattleLaws`, `startedLaws`, or `afterLaws` prove active custom law rank in the same result context; do not interpret `none-or-unresolved` as negative gameplay evidence.
- Do not implement corpse/spoils/low-loss/defensive-win laws until this proof also identifies how to reach active custom law rank for the winning or relevant side in this hook context.

## Batch 12: Focus/Energy diagnostics

Reason for twelfth batch: Cove and Stronghold no-compromise laws reference Focus as a real universal mechanic. Cove needs Focus gain from counterattacks and likely Focus/reload/cannon interactions; Stronghold Warcry work has historically needed to avoid being blocked by Focus costs. Existing code can see UI Focus markers and some hero ability energy fields, but a safe law implementation needs native storage mutation and synchronization proof.

Target behavior:

- Cove `Boarding Hooks` should add real Focus exactly once after a committed counterattack, not just display a marker or mutate a UI field.
- Cove cannon/reload laws should spend or refund real Focus only if native ability gates and UI agree.
- Stronghold Warcry laws should use real Warcry availability/cooldown behavior without accidental Focus-cost fallbacks.
- Any Focus law must synchronize native state, ability availability, event logs, and visible battle UI.

Static evidence gathered June 16:

- Custom unit ability data uses `energyLevel` / `dontUseEnergy`, and battle ability UI code displays Focus markers from `energyLevel`.
- Release hero ability code observes `configEnergyLevel`, `energyLevel`, `cd`, `castsPerBattleLeft`, and `charges` on native ability objects, but the old Warcry normalization path is quarantined and should not become a law implementation.
- Centralized battle event symbols expose `EnergyUpdateEventArgs`, `EnergyUpdatedByMechEventArgs`, and `SideUsedEnergyEventArgs` constructors. These are event payload evidence, not storage mutation proof.
- No exact Focus storage add/set/spend API is proven yet.

Source slice added June 16:

- `Homm3FocusLawDiagnostics` registers only when `homm3_focus_law_diag.flag` is present.
- The hook patches exact Energy/Focus event constructors and release hero ability bind/container surfaces through centralized `GameSymbols.FocusLaws` and existing current Warcry hero ability bind symbols.
- The hook logs bounded event/ability context including energy/cost/cooldown/charge/cast fields when visible, plus active-law resolver snapshots for event/UI instances and arguments.
- `activeKnownCustomLawsFromThisObject=none-or-unresolved` means the exact resolver could not prove active law state from that specific object; it is not evidence that no law is active.
- It does not grant Focus, spend Focus, normalize Warcry costs, change ability availability, mutate event payloads, or consume law state.
- If exact surfaces are absent, registration fails closed and Focus law gameplay remains disabled.
- Build validation: `dotnet build "Heroes of Might & Magic Olden Era Playtest\OfflineUnlockMod\OfflineUnlockMod.csproj" -c Release --no-restore -v:minimal -clp:ErrorsOnly` succeeded with 0 errors and 45 warnings after the active-law resolver snapshot addition. Runtime proof is still pending.

Runtime proof procedure:

- Enable `homm3_focus_law_diag.flag`; optionally also enable `homm3_battle_event_law_diag.flag` and `homm3_counterstroke_doctrine_diag.flag` for combat correlation.
- Enter user-driven combat with units or hero abilities that visibly use Focus/Energy.
- Use a Focus-cost ability and observe whether `side-used-energy`, `energy-update`, or `energy-updated-by-mech` logs correlate with visible Focus changes.
- Open or refresh hero ability UI and confirm whether the bind/container logs expose the same Focus cost and availability data the player sees.
- Confirm whether `activeKnownCustomLawsFromThisObject` proves active custom law rank from any Focus diagnostic object in the same energy/ability context; do not interpret `none-or-unresolved` as negative gameplay evidence.
- Do not implement Focus gain/spend laws until a later proof identifies the exact native storage mutation API and proves the visible UI and native gates synchronize after mutation.

## Batch 13: Buff/debuff diagnostics

Reason for thirteenth batch: Fortress poison/slow laws, Dungeon debuff/disable laws, Fortress counterattack debuffs, Cove after-shot variants, and several training laws need real native buff/debuff application. Donor stat rows are not enough, and generic buff guessing would create silent mechanics drift.

Target behavior:

- Fortress `Thorned Hides` should apply the intended Attack debuff only to the original attacker after a real counterattack.
- Fortress poison/slow laws should apply native poison/slow-style effects with proven duration, target identity, and stacking semantics.
- Dungeon disable/debuff laws should use real buff state and trigger only from committed qualifying events.
- Rampart Avenger-marked laws should observe the exact Rampart Avenger mark buff state rather than generic Vulnerability, target faction, or a custom registry.
- Cove repeated debuff behavior should remain on the existing exact Cove after-shot route, not a broad buff rewrite.

Static evidence gathered June 16:

- Current readable Cpp2IL/ISIL evidence already recorded in agent notes identifies `dzv.bbgf(string,int,int,eab,int,bool) -> dzt` as the current native buff-add path.
- Current by-SID presence check is `dzv.bbfn(string) -> bool`.
- Current by-SID list candidate is `dzv.bbfl(string) -> List`.
- Current readable Cpp2IL proves `dzv` stores its receiver in exact field `ceqy`, initialized by `byl(dzr _buffReceiver, eep logic)` / `Init(dzr _buffReceiver, eep logic)`.
- `dzr` exposes exact receiver accessors `basa() -> eir`, `bbdp() -> FieldObject`, `bbds() -> dzv`, and `bbdu() -> int`; `ede` implements `dzr`, and `Unit` / `Sentry` inherit `ede`.
- `dzt` buff payload carries `target`, and `BuffEventArgs` carries `buffReceiver`; this supports observing receiver identity without reverse-scanning battle objects.
- Older names such as `bbdx`, `bbcb`, and `bber` are compatibility history for the Cove after-shot production hook, but this law diagnostic intentionally starts with the current exact names only.

Source slice added June 16:

- `Homm3BuffDebuffLawDiagnostics` registers only when `homm3_buff_debuff_law_diag.flag` is present.
- The hook patches exact current buff manager add/query/list surfaces through centralized `GameSymbols.BuffDebuffLaws`.
- The hook logs bounded manager, argument, and result context including obvious buff payload fields when readable.
- The hook logs exact `dzv.ceqy` receiver context when present, including exact receiver side/object/hex/id accessors; it does not reverse-scan units or battle objects to infer ownership.
- The hook now explicitly labels centralized Rampart Avenger mark buff SIDs when they appear in buff-add/query/list arguments or readable buff payload fields.
- The hook now attempts active custom law correlation on the buff manager, result, exact receiver, and readable nested objects only through `Homm3CustomFactionLawRuntime.TryResolveActiveKnownCustomLaw`; `activeKnownCustomLawsFromThisObject=none-or-unresolved` means the exact resolver could not prove a law from that object, not that no law is active.
- It does not add, remove, rewrite, or query buffs for gameplay; it only observes native calls that already happen.
- If exact surfaces are absent, registration fails closed and buff/debuff law gameplay remains disabled.
- Build validation: `dotnet build "Heroes of Might & Magic Olden Era Playtest\OfflineUnlockMod\OfflineUnlockMod.csproj" -c Release --no-restore -v:minimal -clp:ErrorsOnly` succeeded with 0 errors after the first buff/debuff diagnostic hook addition, and again after the exact receiver/Avenger-label enrichment. Runtime proof is still pending.

Runtime proof procedure:

- Enable `homm3_buff_debuff_law_diag.flag`; optionally also enable `homm3_battle_event_law_diag.flag`, `homm3_counterstroke_doctrine_diag.flag`, and `homm3_focus_law_diag.flag` for correlation.
- Enter user-driven combat and trigger a native poison, slow, Weakness, Disrupting Ray, or other visible buff/debuff.
- Confirm `buff-add`, `buff-has-by-sid`, and/or `buff-list-by-sid` logs identify SID, duration-like values, caster/source, and target/buff manager ownership.
- Confirm `buffReceiver.ceqy` and/or `dzt.target` identify the intended receiver for `bbgf`, `bbfn`, and `bbfl`; do not infer ownership from reverse scans or unrelated battle objects.
- Confirm stacking semantics by applying the same debuff more than once where safe.
- Confirm any active-law correlation in the same buff trace is resolver-proven; do not interpret `activeKnownCustomLawsFromThisObject=none-or-unresolved` as negative gameplay evidence.
- Do not implement Fortress/Dungeon/Cove/Rampart buff laws until runtime proof identifies the target receiver/side owner, duration fields, stack/refresh behavior, and active custom law rank in the hook context.

## Batch 14: Morale roll and extra-action boundary

Reason for fourteenth batch: several original no-compromise laws reference morale as a trigger, not merely as a flat stat. The current data layer can safely express `heroStat moral`, `unitStat moral`, and native morale/luck buff rows, but that is not the same thing as detecting a committed morale success, morale failure, or extra action.

Target behavior:

- Castle `Righteous Zeal` can remain data-safe where it exactly matches vanilla morale and vanilla morale-trigger rows.
- Cove `Crew Nerve` should eventually reward actual momentum events such as kills, plunder, cannon hits, or surviving ranged fire; it must not be reduced to a permanent morale row if the trigger is supposed to matter.
- Dungeon `Terror Exploitation` needs an enemy morale-failure or negative-status trigger, not a generic friendly morale bonus.
- Fortress `Cold-Blooded Endurance` should be implemented through hit-taking, poison/slow, or other proven endurance events rather than fake morale cheering.
- Rampart `Defender's Grace` needs protection, preservation, favored-enemy, or Avenger-mark correlation; generic morale/luck data rows are only temporary donor-safe display rows.
- Conflux mixed-element resonance and Necropolis/Tower construct-undead morale replacement rules must not be inferred from ordinary living morale rows.

Static evidence gathered June 16:

- Narrow source search found existing mod references to morale only as design text, `Homm3CustomFactionLawRuntime` family labels, Warcry data names, and data-safe stat/buff generation.
- Refreshed bounded decomp search found exact current positive morale-roll candidate `eep.bdhu(Unit, Random) -> bool`; ISIL shows it checks `PromoToolsConfig.disableMorale`, unit data/flags, `UnitStat.moral > 0`, morale distribution probability, a `Random` roll, then constructs/dispatches a `BattleEventArgs`-typed event on success.
- The same decomp pass found exact current negative morale candidate `eep.grw(Unit, Random, bool) -> bool`; ISIL shows it checks `UnitStat.moral < 0`, unit morale gate flags, morale distribution probability, a `Random` roll, and optionally constructs/dispatches a `BattleEventArgs`-typed event depending on the bool parameter.
- `eep.bdhu` has static call sites inside larger battle action-processing methods that also inspect `eep.EStatus` (`Wait`, `Played`, `Ended`), making it the best current candidate for morale extra-action scheduling. Static evidence still does not prove the exact repeated-turn mutation or runtime ordering.
- Static constants also expose `EEffectType.Moral`, `EEffectType.Dismoral`, `battle_log_squad_moral`, `battle_log_squad_antimoral`, and visual strings `morale` / `dismoraled`; these are UI/log/effect evidence only, not scheduling proof.
- Current overlay data uses `heroStat moral`, `unitStat moral`, morale/luck buff rows, and Stronghold Warcry global-buff rows; these are payload/stat surfaces, not morale-roll event surfaces.
- Existing Batch 6 battle-event diagnostics can observe movement, damage, destruction, and energy/focus-like events. Energy updates remain only correlation evidence and are not accepted as proof of morale success/failure or extra-action behavior.
- Existing Batch 13 buff/debuff diagnostics can later support morale-adjacent buffs such as Mirth, Despair, Dread Aura, Warcry, or morale/luck debuffs, but buff application is not itself proof that a morale roll happened.

Source slice added June 16:

- `GameSymbols.MoraleTriggerLaws` centralizes the exact `eep` battle logic type, `bdhu` positive morale roll, `grw` negative morale candidate, and exact Unit/UnitStat snapshot members used by the diagnostic.
- `Homm3MoraleTriggerLawDiagnostics` registers only when `homm3_morale_trigger_law_diag.flag` is present.
- The hook patches only exact `eep.bdhu(Unit, Random) -> bool` and `eep.grw(Unit, Random, bool) -> bool`; if those signatures are absent, registration fails closed and morale-trigger gameplay remains disabled.
- The hook logs bounded method, bool result, unit/stat/gate context, arguments, and active-law resolver snapshots through `Homm3CustomFactionLawRuntime.TryResolveActiveKnownCustomLaw`.
- `activeKnownCustomLawsFromThisObject=none-or-unresolved` means the exact resolver could not prove active law state from that specific object; it is not evidence that no law is active.
- It does not mutate morale rolls, random state, extra actions, turn scheduling, battle events, unit state, or law state.
- Existing data-safe morale rows may remain where the desired law is flat morale or where Castle intentionally mirrors vanilla; they must not be described as implementation of custom trigger laws.
- Build validation: `dotnet build "Heroes of Might & Magic Olden Era Playtest\OfflineUnlockMod\OfflineUnlockMod.csproj" -c Release --no-restore -v:minimal -clp:ErrorsOnly` succeeded with 0 errors and 45 warnings after the morale-trigger diagnostic hook addition. Runtime proof is still pending.

Runtime proof procedure:

- Enable `homm3_morale_trigger_law_diag.flag`; optionally also enable `homm3_battle_event_law_diag.flag` for event-order correlation.
- In user-driven combat, correlate the hook with visible positive morale extra-action, negative morale failure if available, side/unit identity, active law rank, and action queue state.
- Confirm whether `result=true` on `positive-morale-roll` lines corresponds to the visible extra action/repeated turn, and whether `result=true` on `negative-morale-roll` lines corresponds to any visible dismorale/failure behavior.
- Confirm whether `activeKnownCustomLawsFromThisObject` proves active custom law rank from any morale diagnostic object in the same roll context; do not interpret `none-or-unresolved` as negative gameplay evidence.
- Do not use `SideUsedEnergyEventArgs`, `EnergyUpdatedByMechEventArgs`, or generic action/turn logs as a substitute for morale proof unless a later exact native call chain proves they are downstream of the morale roll.
- Do not implement `Crew Nerve`, `Terror Exploitation`, `Defender's Grace`, or similar morale-trigger laws from generic `heroStat moral`, `unitStat moral`, or buff rows alone.

## Batch 15: Rampart Avenger mark identity

Reason for fifteenth batch: many Rampart no-compromise laws depend on “Avenger-marked” enemies. This must mean one concrete mark state. A second registry, faction-match guess, or generic vulnerability check would make Rampart laws drift away from the unique faction skill.

Target behavior:

- `Avenger's Trail` should reveal or track enemies through the same Avenger mark state used by the Rampart faction skill, not through independent scouting rows.
- `Avenger's Tutelage`, `Avenger's Reprisal`, `Hunter Pairs`, `Preservation Tithe`, `Defender's Grace`, `Druidic Oath`, and `Avenger's Patience` must key off the exact Avenger mark if they mention marked/favored enemies.
- If a law wants generic Vulnerability, Despair, Weakness, or Dread Aura behavior, it should say that explicitly and not call it Avenger mark behavior.

Static evidence gathered June 16:

- Current generated Rampart faction-skill data defines `skill_faction_homm3_rampart_ability_avenger` as a custom hero battle ability.
- That ability applies Rampart-owned negative buff rows:
  - `skill_faction_homm3_rampart_ability_avenger_rank_1_effect`
  - `skill_faction_homm3_rampart_ability_avenger_rank_2_effect`
  - `skill_faction_homm3_rampart_ability_avenger_rank_3_effect`
  - `skill_faction_homm3_rampart_ability_avenger_rank_2_decay_effect`
- The Rank 1/2/3 rows are all-damage vulnerability marks; the decay variant also applies heal-lock/max-HP reduction through native buff data.
- Narrow latest-readable-Cpp2IL search found no named native `Avenger` or favored-enemy runtime surface.
- The only native-looking `MarkedTarget` type found is `Hex.Session.Data.MarkedTarget`, owned by `SideAiData` and adjacent AI/world targeting helpers (`markedAreaGuard`, `markedSquads`, `markedObject`, `markedCity`, etc.). It is not accepted as Rampart Avenger evidence.
- Existing Batch 13 buff/debuff diagnostics are the correct proof route for observing Avenger buff application, ownership, duration, and by-SID lookup behavior.

Source slice added June 16:

- `GameSymbols.RampartAvengerLaws` now centralizes the Rampart Avenger ability SID, the four supported Avenger mark buff SIDs, and their diagnostic label mapping.
- `Homm3BuffDebuffLawDiagnostics` annotates those exact SIDs as `rampart-avenger-mark:*` during buff-add/query/list traces.
- No gameplay hook was added in this batch.
- No custom Avenger mark registry was added.
- No native `MarkedTarget` symbol was added because current evidence points to AI/session targeting, not Rampart battle marks.

Runtime proof procedure:

- Enable `homm3_buff_debuff_law_diag.flag`; optionally also enable `homm3_focus_law_diag.flag` to correlate Avenger Focus cost and `homm3_battle_event_law_diag.flag` for combat context.
- In user-driven combat, cast the Rampart Avenger hero ability at each available rank/subskill combination.
- Confirm the buff-add diagnostics label one of the centralized `GameSymbols.RampartAvengerLaws.MarkBuffSids` as `rampart-avenger-mark:*` on the intended enemy target, with expected duration and stacking/refresh behavior.
- Confirm `buff-has-by-sid` or `buff-list-by-sid` can observe the same Avenger mark on the target manager without scanning unrelated vulnerability buffs.
- Confirm any active-law correlation in the same buff trace is resolver-proven; do not interpret `activeKnownCustomLawsFromThisObject=none-or-unresolved` as negative gameplay evidence.
- Do not implement Rampart marked-enemy law predicates until this exact buff ownership and lookup path is runtime-proven.
- Do not use `Hex.Session.Data.MarkedTarget`, generic Vulnerability, or faction matchup as a substitute for Avenger mark state.

## Batch 16: Known runtime law-family constants

Reason for sixteenth batch: custom hooks should ask for active law rank through one stable runtime vocabulary. Hard-coded numeric law IDs spread across hooks are easy to misread, especially because donor unit/tier law rows are not globally stable.

Target behavior:

- Every future runtime hook should use `Homm3CustomFactionLawRuntime` constants for globally stable law families instead of embedding numeric indices.
- The active-law resolver should continue to fail closed for unknown, donor-specific, or purely data-only law slots.
- Resource Riches remains outside this runtime list because it is intentionally universal and balance-unified.
- Donor unit/tier law slots remain outside this runtime list because the vanilla donor topology uses different indices per faction family.

Static evidence gathered June 16:

- The current technical proposal identifies the stable runtime-needed families as sight, primary-stat training, counterstroke, spell school access, formations, gold income, morale/morale-trigger, extra construction, astrology/calendar, and spell cooldown.
- `docs/custom_law_technical_implementation_proposals.md` explicitly warns that unit/tier law indices vary by donor family and must not be assumed globally.
- Generated custom law override files include index `17`, but current docs show this slot can mean unit growth/stat laws, `Resource Riches II`, or temporary placeholder edict rows depending on donor/faction topology. It is therefore not a safe globally stable runtime family.

Source slice added June 16:

- `Homm3CustomFactionLawRuntime` now centralizes constants for the globally stable runtime law indices:
  - `2` hero sight radius
  - `6` hero primary-stat training
  - `13` counterattack doctrine
  - `15` and `27` spell school access
  - `18` and `19` melee/ranged formations
  - `21` gold income percent
  - `22` and `25` morale/morale-trigger
  - `28` extra construction
  - `33` astrology/calendar income
  - `34` spell cooldown modifier
- `KnownRuntimeLawIndices` is now the single resolver scan list used by law-tree diagnostics, battle-event side-context diagnostics, and buff/debuff receiver/context diagnostics.
- The registration log now says variable donor unit/tier law slots and Resource Riches are intentionally excluded.
- No gameplay hook was added or enabled.

Runtime proof procedure:

- Enable `homm3_custom_faction_law_diag.flag`.
- Open custom faction law trees and confirm active-law diagnostics still report the expected known runtime families with correct faction SID, law SID, index, rank, line/group, and `wasApplied`.
- Do not add index `17`, `20`, or other donor/topology-specific slots to `KnownRuntimeLawIndices` unless the generator topology is reverified and the slot is promoted to a globally stable runtime family.
- Future hooks must consume these constants only after the relevant hook surface separately proves side/law/rank correlation.

## Batch 7: Spell cooldown storage diagnostics

Reason for seventh batch: spell cooldown laws cannot be implemented from spellbook UI state. This slice targets native battle-spell logic/pool surfaces that appear to own stored cooldown and effective cooldown calculation.

Target behavior:

- Law row `34` should eventually implement faction-specific cooldown reductions, credits, resets, enemy penalties, and once-per-round reuse through real cooldown storage and cast gates.
- Tower, Conflux, Necropolis, Inferno, Stronghold, and several conditional faction laws require this proof before custom runtime implementation.

Static evidence gathered June 16:

- Diffable Cpp2IL exposes global type `eew` as a battle spell logic object with spell SID/config getters, `BattleMagicConfig` getter, and numeric field `cfxk`.
- ISIL shows `eew.bdmd()` reads the spell's `BattleMagicConfig.cd`, stored `cfxk`, per-school cooldown data, and `HeroStat.magicCdBonus`, then clamps the result. This is an effective-cooldown candidate.
- ISIL shows `eew.bdmg()` decrements `cfxk` and clamps at zero.
- ISIL shows `eew.bdmh(int)` sets `cfxk` with a zero clamp.
- ISIL shows `eew.bdmi(int)` adds to `cfxk` only when current `cfxk` is zero.
- Diffable/ISIL expose global type `eex` as a battle spell pool/manager with `eew[]`, `Init(drr,eir)`, and `bdnj(int,bool)`.
- ISIL shows `eex.bdnj(int,bool)` iterates `eew[]` and shifts each spell's `cfxk`, including a boolean path that appears to force a minimum of `1` for positive existing cooldowns.

Source slice added June 16:

- `Homm3SpellCooldownLawDiagnostics` registers only when `homm3_spell_cooldown_law_diag.flag` is present.
- The hook patches only exact `eew.bdmd`, `eew.bdmg`, `eew.bdmh`, `eew.bdmi`, `eex.Init(drr,eir)`, and `eex.bdnj(int,bool)` through centralized `GameSymbols.SpellCooldownLaws`.
- The hook logs bounded spell logic/pool context, simple cooldown-like fields, arguments, result values, and native obfuscated type names.
- The hook now attempts active custom law correlation on cooldown diagnostic instances, arguments, and results only through `Homm3CustomFactionLawRuntime.TryResolveActiveKnownCustomLaw`; `activeKnownCustomLawsFromThisObject=none-or-unresolved` means the exact resolver could not prove active law state from that object, not that no law is active.
- It does not mutate cooldowns, cast gates, spellbook rows, mana, battle events, UI state, or law state.
- Build validation: `dotnet build "Heroes of Might & Magic Olden Era Playtest\OfflineUnlockMod\OfflineUnlockMod.csproj" -c Release --no-restore -v:minimal -clp:ErrorsOnly` succeeded with 0 errors after the first spell cooldown diagnostic hook addition, and again after the active-law correlation enrichment. Runtime proof is still pending.

Runtime proof procedure:

- Enable `homm3_spell_cooldown_law_diag.flag`.
- Enter user-driven combat with a hero who can cast battle spells.
- Open the spellbook before and after casting a spell; confirm `effective-cooldown`, `cooldown-mutation`, and/or `spell-pool` logs correlate with visible cooldown changes.
- Advance rounds/turns and confirm whether `eex.bdnj` or `eew.bdmg` is the actual cooldown tick path.
- Try a native cooldown-modifying law/bonus if available and confirm whether `HeroStat.magicCdBonus` flows through `eew.bdmd`.
- Confirm whether `activeKnownCustomLawsFromThisObject` proves active custom law rank from any cooldown diagnostic object in the same cast/cooldown context; do not interpret `none-or-unresolved` as negative gameplay evidence.
- Do not implement cooldown credits, resets, reuse, or enemy cooldown penalties until a live proof also identifies the cast gate that refuses/accepts a spell based on these values and confirms spellbook UI synchronization follows native state.

## Batch 8: Spell cast-gate diagnostics

Reason for eighth batch: Batch 7 identified spell cooldown storage/effective-cooldown candidates, but implementation still needs the native gate that actually refuses or allows casting. This slice traces exact boolean gates without changing their result.

Target behavior:

- Cooldown credits, spell reuse, and conditional cooldown resets must eventually pass through the same native gate the game uses for ordinary spell casting.
- If a law grants an exception, it must update native state in a way that spellbook UI, mana checks, rank checks, same-spell counters, and cast execution all agree.

Static evidence gathered June 16:

- ISIL shows `eew.basy()` returns false when `cfxk >= 1` and then checks side/hero spell state. This is a cooldown-readiness gate candidate.
- ISIL shows `eew.base(eir)` combines caster-side state, spell rank limits, stored cooldown (`cfxk`), and additional hero/spell checks. This is the strongest full cast-eligibility candidate found so far.
- ISIL shows `eew` calls `eex.bdnm(string, ESchool)`, and `eex.bdnm(...)` checks hero magic counter state, spell/school disable flags, same-school/same-spell per-round limits, and ignore-limit hero stat flags.
- ISIL shows `eex.bdnn(int)` selects or validates an indexed `eew` through `bdnp(...)` and stores the selected spell in `cfxv`; this is a spell-selection gate candidate, not cast proof by itself.
- `eew.bata()` is a constant false implementation and is intentionally not traced as a useful gate.

Source slice added June 16:

- `Homm3SpellCastGateLawDiagnostics` registers only when `homm3_spell_cast_gate_law_diag.flag` is present.
- The hook patches only exact boolean methods `eew.basy`, `eew.base(eir)`, `eex.bdnm(string, ESchool)`, and `eex.bdnn(int)` through centralized `GameSymbols.SpellCastGateLaws`.
- The hook logs bounded gate context, simple spell/cooldown fields, arguments, return values, and native obfuscated type names.
- The hook now attempts active custom law correlation on cast-gate diagnostic instances and arguments only through `Homm3CustomFactionLawRuntime.TryResolveActiveKnownCustomLaw`; `activeKnownCustomLawsFromThisObject=none-or-unresolved` means the exact resolver could not prove active law state from that object, not that no law is active.
- It does not mutate gate results, cooldown state, spellbook rows, mana, same-spell counters, battle events, UI state, or law state.
- Build validation: `dotnet build "Heroes of Might & Magic Olden Era Playtest\OfflineUnlockMod\OfflineUnlockMod.csproj" -c Release --no-restore -v:minimal -clp:ErrorsOnly` succeeded with 0 errors after the first spell cast-gate diagnostic hook addition, and again after the active-law correlation enrichment. Runtime proof is still pending.

Runtime proof procedure:

- Enable `homm3_spell_cast_gate_law_diag.flag`; optionally also enable `homm3_spell_cooldown_law_diag.flag` to correlate storage and gate traces.
- Enter user-driven combat with a hero who can cast battle spells.
- Open the spellbook, select a ready spell, cast it, then attempt to select/cast it again while it is cooling down.
- Confirm which gate returns `true` for ready spells and `false` for cooldown-blocked spells.
- Confirm whether `activeKnownCustomLawsFromThisObject` proves active custom law rank from any gate diagnostic object in the same cast/cooldown context; do not interpret `none-or-unresolved` as negative gameplay evidence.
- Confirm whether rank, mana, same-spell, same-school, and spellbook UI disabled states are represented in `eew.base(eir)` and/or `eex.bdnm(...)`.
- Do not override any gate result until a later proof shows the minimal native state edit that makes both the gate and visible UI agree.

## Batch 9: Active custom law/rank resolver

Reason for ninth batch: every runtime mechanic needs the same active law/rank answer. Without a shared resolver, later hooks would duplicate fragile reflection or quietly guess from faction names.

Target behavior:

- Runtime law hooks should ask one shared helper whether a known custom law is active and at which rank.
- The helper must fail closed when faction, law row, rank, or applied-state evidence is missing.
- Gameplay hooks must not infer active law state from donor effects, UI labels, row order alone, or faction ownership alone.

Static evidence gathered June 16:

- Diffable Cpp2IL exposes `Hex.Session.Data.Side.fractionLaws` and `Side.fraction`.
- `DataFractionLaws` exposes exact fields `fraction`, `list`, and `spentPoints`.
- `DataFractionLaw` exposes exact fields `sid`, `line`, `group`, `level`, and `wasApplied`.
- Logic `dtj` exposes a data-side getter/field (`ymo` / `<ccng>k__BackingField`) and a `FractionLaws` getter/field (`ymw` / `<ccnl>k__BackingField`).
- Logic `FractionLaws` wraps `DataFractionLaws` in exact field `ccew`.
- UI law runtime `dqp` still remains useful for diagnostics but is not the source of truth for gameplay law state.

Source slice added June 16:

- `Homm3CustomFactionLawRuntime.TryResolveActiveKnownCustomLaw(object sideOrLawOwner, int lawIndex, out ActiveLawState state)` was added as the shared fail-closed resolver.
- The resolver follows only centralized exact members in `GameSymbols.CustomFactionLawRuntime`.
- It supports `DataFractionLaws`, data `Side`, logic `dtj`, and logic `FractionLaws` owners through exact fields/getters.
- It requires a custom faction SID, expected generated law SID, matching `DataFractionLaw`, `level > 0`, `wasApplied == true`, and exact line/group fields.
- It returns rank/faction/law/family metadata in `ActiveLawState`.
- The existing law-tree diagnostic logs now include a bounded `activeCustomLaws=[...]` summary when the resolver succeeds.
- Battle-event diagnostics also reuse this resolver for exact battle side contexts and log `activeKnownCustomLaws=[...]` or `none-or-unresolved`; see Batch 6 for the runtime-unproven side/event correlation boundary.
- Buff/debuff diagnostics reuse this resolver for exact buff-manager receiver context and readable logged objects, logging `activeKnownCustomLawsFromThisObject=[...]` or `none-or-unresolved`; see Batch 13 for the runtime-unproven buff receiver/law correlation boundary.
- Build validation: `dotnet build "Heroes of Might & Magic Olden Era Playtest\OfflineUnlockMod\OfflineUnlockMod.csproj" -c Release --no-restore -v:minimal -clp:ErrorsOnly` succeeded with 0 errors after the active law/rank resolver addition. Runtime proof is still pending.

Runtime proof procedure:

- Enable `homm3_custom_faction_law_diag.flag`.
- Open a custom faction law tree and confirm the bind logs include expected active custom laws with correct faction SID, law SID, law index, rank, line/group, and family.
- Test at least one custom faction with an unapplied law row; that law must not appear as active.
- Do not let gameplay hooks consume this resolver until runtime logs prove it correlates with the visible law tree and with the side object available in the intended hook context.

Fail-closed implementation rule:

- If any required surface is missing, ambiguous, only forecast/UI-backed, or cannot correlate side/faction/law rank in the same native context, that faction's custom law effect remains disabled and logs a bounded diagnostic when the relevant diagnostic flag is enabled. Do not substitute generic damage, generic vulnerability, generic stat rows, charge increases, or donor effects as a fallback.

Acceptance criteria:

- Castle and Inferno remain exact native rows.
- A successful Cove counterattack increases real Focus exactly once.
- A Dungeon counterattack only receives its bonus when the counterattacker's current living stack count is higher than the attacker's current living stack count.
- A Fortress counterattack applies the intended Attack debuff to the original attacker only after a real counterattack.
- Rampart checks the real Avenger mark state rather than target faction, unit SID, or donor tags.
- Tower scaling reads the defending hero's current Spell Power and applies only to counterattack damage.
- Conflux extra damage is represented as a separate magic-damage component if and only if a real committed-damage surface supports that shape.
- Necropolis restoration uses final damage dealt, restores only the counterattacking stack, and clamps to original battle stack size.
- Stronghold stacking bonus is battle-scoped, per stack, and increments once per successful counterattack.

## Batch 17: Training and formation readiness boundary

Reason for seventeenth batch: Hero primary-stat training and melee/ranged formation laws are the next large implementation target after generic combat diagnostics. They share many probe needs: committed damage, attack classification, unit identity, battle geometry, buffs/debuffs, spellcast events, Gating/summon identity, corpse/mana state, and turn-order effects. Existing diagnostics expose useful raw context, but they do not yet prove enough to mutate gameplay safely.

Target behavior:

- Family 2 `Hero primary-stat training` should implement conditional faction effects such as morale-scaled damage, gunpowder debuffs, isolated-target damage, negative-status mitigation, Avenger vulnerability, spellcast calibration buffs, elemental-family buffs, gated-entry damage, corpse mana, and wounded-unit speed without flattening them into generic stats.
- Family 4 `Melee and ranged formations` should implement faction-specific formation behavior such as adjacency protection, first-volley bonuses, boxed/flanked enemy bonuses, Bog Line status pressure, Avenger-mark shooter exploitation, construct readiness, mixed-element composition, Gating/teleport adjacency, death auras, and forward-movement aggression.
- Castle may keep exact native/static formation rows where they truly match vanilla behavior.
- Any faction effect that depends on first-volley, adjacency, facing, isolated enemies, family composition, Gating/summon identity, corpse count, mana mutation, or turn-order speed must remain disabled until its exact probe is proven.

Current diagnostic coverage:

- `Homm3BattleEventLawDiagnostics` logs exact battle event construction/dispatch, `CastAbilityEventArgs`, ability ID/type/index, `AbilityLogicConfig` fields, `CastDealerConfig` fields, attacked objects/hexes, movement path, object-damage payload fields, destruction payload fields, Unit logic/view/data SID/faction/tier, Hex `index/x/z`, and battle-side active-law resolver snapshots.
- `Homm3BattleEventLawDiagnostics` also patches exact `Unit.bbgw(...)` as `damage-apply-candidate`, which is stronger than forecast-only candidates but remains runtime-unproven for committed damage ordering and payload semantics.
- `Homm3BuffDebuffLawDiagnostics` traces exact buff add/query/list surfaces, receiver context, payload fields, Rampart Avenger mark labels, and active-law resolver snapshots.
- `Homm3MoraleTriggerLawDiagnostics` traces exact positive/negative morale roll candidates and unit stat/gate context, useful for Castle morale-scaling training but not a substitute for committed damage proof.
- `Homm3FocusLawDiagnostics`, spellbook/cast-gate/cooldown diagnostics, and reward/battle-result diagnostics cover adjacent systems but do not prove formation predicates by themselves.

Readiness matrix:

| Probe surface | Current status | Boundary |
|---|---|---|
| Active law/rank in battle context | Partial | Resolver snapshots exist on battle-side and several exact objects, but runtime correlation remains unproven. |
| First-volley / first attack state | Missing | No per-stack first-volley key or exact native first-attack owner has been identified. |
| Battle geometry | Partial | Hex coordinates and paths are logged; no proven `Homm3BattleGeometry` helper exists for adjacency, isolation, boxed-in, flank, distance, or protection predicates. |
| Adjacency / facing | Mostly missing | Coordinates may support adjacency later; facing/orientation is not diagnostic-proven for laws. |
| Ranged/melee classification | Partial | Ability/dealer classification fields are logged, but runtime meaning of ranged/melee/long-reach predicates is not proven enough for mutation. |
| Unit family/custom SID classification | Partial | Unit SID/faction/tier are visible; family classifiers such as gunpowder, construct, elemental, living/undead, gated, summoned, shooter, and melee-protector are not centralized/proven for laws. |
| Damage mutation point | Partial | `Unit.bbgw(...)` is the best current candidate, but committed-damage ordering, target identity, and safe mutation semantics remain unproven. |
| Successful hero spellcast hook | Partial | Cast events and spellbook/cast-gate traces exist; Tower spellcast-to-unit buff behavior needs ordering proof. |
| Gating/summon identity | Missing for laws | Existing visual/spawn work is not a law-ready proof of temporary gated stack identity and lifetime. |
| Corpse/mana state | Missing | No logical corpse count, corpse consumption, temporary mana mutation, or cleanup surface is proven. |
| Turn-order speed refresh | Missing | No initiative/turn queue/speed refresh mutation surface is proven. |
| Buff/debuff application | Partial | Exact buff surfaces exist, but ownership, duration, stacking, and law-rank correlation need runtime proof. |

Source slice added June 16:

- No gameplay hook was added for training or formation laws in this batch.
- `Homm3BattleEventLawDiagnostics` remains the current shared combat-context diagnostic for these families.
- The diagnostic now adds a bounded `formationProbe={...}` summary on exact `CastAbilityEventArgs` contexts. It reports observed per-caster cast sequence, whether this is the first observed cast for that caster in the diagnostic window, caster hex, target hex count, axial-distance candidate from logged Hex `x/z`, and `adjacentCandidate=true/false` when coordinates are readable.
- The first-cast and adjacency fields are explicitly diagnostic candidates, not native first-volley or formation proof. They exist to help compare logs against visible combat actions before any gameplay predicate is written.
- Do not implement training or formation gameplay from broad `BattleEventArgs`, UI forecast, or static enum-name evidence alone.

Runtime proof procedure:

- Enable `homm3_battle_event_law_diag.flag`; optionally combine with `homm3_buff_debuff_law_diag.flag`, `homm3_morale_trigger_law_diag.flag`, `homm3_focus_law_diag.flag`, and spell diagnostics depending on the faction being tested.
- In user-driven combat, capture attacks, ranged attacks, first attacks, movement into adjacency, kills, spellcasts, debuff applications, and status-marked targets.
- Confirm whether logged ability/dealer classification, unit SID/faction/tier, attacked objects/hexes, Hex coordinates, `formationProbe.observedFirstForCaster`, `formationProbe.minHexDistanceCandidate`, and `formationProbe.adjacentCandidate` consistently match the visible action before any predicate is implemented.
- Do not implement first-volley, adjacency protection, isolated-target damage, formation bonuses, spellcast-to-unit buffs, corpse mana, Gating-entry buffs, or speed/turn-order effects until the relevant exact surface and active law-rank access are proven in the same native context.

## Batch 18: Unit-family classifier readiness boundary

Reason for eighteenth batch: many no-compromise laws depend on unit families rather than raw unit SIDs or faction names. Examples include Cove gunpowder lines, Tower constructs, Conflux elemental families, Necropolis undead/corpse economy, Inferno gated or summoned stacks, Rampart Avenger-marked targets, Fortress living targets for poison/slow pressure, and Stronghold melee aggression. These must not be implemented as donor stat rows, SID substring checks, visual mesh guesses, or broad fallback tags.

Target behavior:

- Runtime law code should eventually ask one centralized classifier for unit-family facts in the current native context.
- The classifier must fail closed when a family fact is unavailable or only inferred from donor identity.
- Unit classification must be explicit enough to distinguish custom unit identity from donor unit identity after overlay consolidation.
- Classifier results used for gameplay must be proven in the same context that consumes them: battle action, damage, buff/debuff, spellcast, spawn/summon, reward, battle-result, or law-tree context.

Classifier categories required by intended law designs:

| Classifier | Needed for |
|---|---|
| Gunpowder / firearm / crew | Cove training, Cove formations, Cove counterattack/debuff variants. |
| Shooter / ranged / melee | Castle/Cove/Rampart/Stronghold formation laws, first-volley laws, protector laws, melee aggression laws. |
| Construct / machine | Tower training/formations/counterstroke and morale-replacement ideas. |
| Elemental family | Conflux training/formations/counterstroke and elemental-composition laws. |
| Undead / living / nonliving | Necropolis corpse, reanimation, morale replacement, Fortress poison/slow legality, Inferno sacrifice legality. |
| Gated / summoned / temporary | Inferno Gating laws, Conflux summon-adjacent laws, custom summon visual/lifetime interactions. |
| Corpse-producing / corpse-eligible | Necropolis corpse economy and corpse-to-mana laws. |
| Avenger-marked | Rampart target exploitation laws; currently tracked as buff identity, not unit family. |
| Custom unit line / faction-owned line | Faction-specific unit laws where donor identity must not leak into classification. |

Current diagnostic coverage:

- `Homm3BattleEventLawDiagnostics` logs Unit logic/view/data config snapshots with SID, faction, and tier when exact members are available.
- The same battle diagnostic logs raw `AbilityLogicConfig` and `CastDealerConfig` classification fields such as `attackType_`, `castType_`, `moveType`, `attackPatternSid`, `triggerCounter`, `sideCastType`, `shootRange`, `shootThreshold`, `shootDmgBuff`, and `runDmgBuff`; these are classification evidence, not gameplay-ready ranged/melee proof.
- `Homm3BuffDebuffLawDiagnostics` can label known Rampart Avenger mark buff SIDs and log receiver context, but that only proves buff identity when the exact buff surface fires.
- `Homm3BattleResultLawDiagnostics` and reward diagnostics can expose transfer/loss/reward context, but no corpse-producing or corpse-consumption classifier is proven.
- Spawn/battle-visual work carries useful custom summon identity lessons, but visual replacement identity is not sufficient proof of gated/summoned gameplay lifetime for laws.

Missing or runtime-unproven:

- `Homm3UnitLawClassifier` exists as a fail-closed boundary, but no exact native family enum, generated Core field, or custom-owned family table is proven as a source for family facts.
- No exact native family enum or data table has been proven as the authoritative source for undead, construct, elemental family, living/nonliving, gunpowder, corpse eligibility, or custom-line classification.
- Ranged/melee is only partially visible through raw ability/dealer fields and must be correlated in combat before use.
- Gated/summoned/temporary stack state is not proven for law gameplay, even if visual spawn identity is partially understood elsewhere.
- Corpse-producing and corpse-consumption state is not proven.
- Donor unit config data cannot be trusted as family evidence for custom units unless the custom overlay writes and verifies the intended custom family field.

Read-only audit findings added June 16:

- Existing checked-in code provides partial diagnostic exposure for Unit SID/faction/tier, raw attack/dealer classification candidates, hex/distance/adjacency candidates, buff SID payloads, and Rampart Avenger mark buff SIDs.
- Existing checked-in code does not provide centralized or proven classifiers for undead, construct, elemental, gunpowder, living, corpse-producing, or gated/summoned/temporary unit state.
- `GameSymbols.BattleEventLaws` currently exposes `CastAbilityEventArgs`, `Unit`, `Unit.bbgw`, attacked object/hex members, `AbilityID` type/index members, `AbilityLogicConfig` fields, `CastDealerConfig` fields, Unit config SID/faction/tier fields, and Hex `x/z` fields. These are diagnostic evidence only.
- `GameSymbols.BuffDebuffLaws` and `Homm3BuffDebuffLawDiagnostics` expose buff SID payload and receiver context, plus known Rampart Avenger mark labels through `GameSymbols.RampartAvengerLaws`. They do not classify general negative status, living, undead, elemental, construct, or gunpowder families.
- `Homm3CustomFactionLawRuntime` resolves active law/rank for known law family indices but intentionally does not classify units.

Classifier-dependent intended laws:

| Classifier dependency | Intended laws blocked until proven |
|---|---|
| Elemental family | Conflux `Planar Attunement`, `Elemental Aspect`, `Elemental Conjunction`, `Planar Calendar`, and `Aspect Cooldowns`. |
| Construct | Tower `Battle Automata`; Tower `Grand Workshop` if it distinguishes magical/construct buildings. |
| Gunpowder / Cannon / Pirate / shooter | Cove `Burning Ash`, `Boarding Parties`, `Gun Decks`, `Storm Omens`, `Reload Drills`; Rampart `Hunter Pairs`; Tower `Battle Automata`; Stronghold `Warband Crush`. |
| Melee / ranged split | The whole melee/ranged formations family, especially Cove `Boarding Parties`, Rampart `Hunter Pairs`, and Stronghold `Warband Crush`. |
| Gated / summoned / temporary | Inferno `Infernal Ascension`, `Hellpack Assault`, `Infernal Signs`, and `Sacrificial Casting`. |
| Living / undead | Necropolis `Gravesight`, Necropolis `Death March`, and any construct/undead morale-replacement behavior. |
| Corpse / casualty / corpse-producing | Necropolis `Gravesight`, `Corpse Wisdom`, `Death Magic`, `Death Moon`, and `Corpse Fuel`. |
| Avenger-marked status | Rampart `Avenger's Trail`, `Avenger's Tutelage`, `Avenger's Reprisal`, `Hunter Pairs`, `Preservation Tithe`, `Druidic Oath`, and `Avenger's Patience`. |
| Poison/slow/disabled/debuffed status | Fortress `Hidebound Drill`, `Bog Line`, `Witch Signs`, `Bog Hex`; Dungeon `Kill Corridors`, `Cruel Momentum`, `Deep Portents`; Dungeon `Predator's Instruction` additionally depends on isolated-enemy geometry. |

Allowed next diagnostic work:

- Add a central, diagnostic-only classifier helper that reports `unknown` unless it can read an exact custom-owned table or exact native family field.
- Add a static Core-overlay audit that lists every custom unit's intended family tags from the source manifest/overlay and checks whether those tags are actually represented in generated Core rows.
- Add battle diagnostics that print classifier evidence next to Unit SID/faction/tier, but only as `classifierEvidence`, not as a gameplay predicate.
- Add spawn/summon diagnostics for Gating and temporary stacks only if they patch exact native surfaces and do not reuse visual-only identity as gameplay truth.

Source slice added June 16:

- `Homm3UnitLawClassifier` was added as the shared fail-closed classifier boundary.
- The helper may report exact unit identity evidence already available from current Unit logic/view config fields, including SID, faction, and tier.
- Every family fact currently reports `unknown`: gunpowder, shooter, melee, construct, elemental, undead, living, gated/summoned, and corpse-producing.
- The helper now exposes a typed `Classification` result and `Fact` enum (`Unknown`, `Yes`, `No`) so future gameplay hooks cannot justify parsing diagnostics or treating missing evidence as false.
- The helper now exposes `HasIdentity(...)` and `RequireFact(...)` so future gameplay hooks have one fail-closed gate and one diagnostic failure reason for `Unknown` or `No` facts.
- `Homm3UnitLawFamilyRegistry` was added as an intentionally empty custom-owned registry seam. It is the only approved place to add authored custom-family facts after a source-of-truth audit; an empty registry means no current behavior change.
- `Homm3BattleEventLawDiagnostics` now prints `classifierEvidence={...}` next to battle-object unit context so user-driven combat logs can show what exact identity evidence was present in the same native object graph.
- No gameplay hook consumes this classifier yet, and no family-dependent law should consume it until a future batch proves an exact native or custom-owned family source.
- Build validation is pending for this source slice.

Metadata-source audit note:

- A bounded search of likely custom metadata and overlay paths found implementation-side SID lists, law override SID lists, ability tags, projectile tables, and source mechanic text, but did not identify an authoritative custom unit-family metadata table.
- Ability-level tags such as `melee_attack`, overlay constants such as shooter guard SID lists, and law override unit SID arrays are not accepted as unit-family source of truth for runtime law classification.
- Until an authored family table is created or a native family field is proven, the registry remains empty and all family facts remain `Unknown`.
- `custom_factions/unit_family_tags.json` was added as a template-only source-of-truth candidate. It contains no unit entries and therefore authorizes no runtime family facts.
- `docs/homm3_unit_family_classifier_source.md` records the accepted source path, rejected inference sources, and validation requirements before any family fact may affect gameplay.
- `tools/release_port/validate_unit_family_tags.py` was added to validate the template and any future authored entries against enabled custom faction unit SIDs, allowed fact names, allowed values, and explicit `unknown` values for unproven facts.
- `tools/release_port/generate_unit_family_registry.py` was added as the only approved generator from validated `unit_family_tags.json` to `Homm3UnitLawFamilyRegistry.cs`; it has not been run in this slice.
- `tools/release_port/sync_unit_family_tag_placeholders.py` was added as an unrun authoring aid that can add exact custom unit SID entries with every fact set to `unknown`. Placeholder entries are review scaffolding only and authorize no runtime behavior.
- `tools/release_port/check_unit_family_registry_drift.py` was added as an unrun integrity check that validates the tag file and compares checked-in `Homm3UnitLawFamilyRegistry.cs` against generator output. Passing it would prove only static registry sync, not runtime law readiness.

Forbidden implementation shortcuts:

- Do not infer undead/construct/elemental/gunpowder/living from unit SID substrings, display names, donor faction, donor unit tier, icon path, visual prefab, animation folder, or law text.
- Do not treat `shootRange`, `shootThreshold`, or `attackType_` enum text as a proven ranged/melee classifier until combat logs correlate it with visible actions.
- Do not use broad fallback tags such as "all Cove shooters are gunpowder" or "all Tower units are constructs"; those erase the law design.
- Do not implement corpse, Gating, summon, or temporary-stack laws from battle-visual replacement state.

Runtime proof procedure:

- Enable the relevant family diagnostic flag after it exists; until then use `homm3_battle_event_law_diag.flag`, `homm3_buff_debuff_law_diag.flag`, and result/reward diagnostics only as correlation inputs.
- In user-driven combat, test at least one normal living unit, one custom gunpowder/crew unit, one construct candidate, one elemental candidate, one undead candidate, one gated/summoned stack, and one shooter/melee contrast.
- Confirm that the same exact classifier evidence is available in the eventual consuming hook context before enabling any gameplay effect.

## Batch 19: No-compromise law readiness matrix

Reason for nineteenth batch: the project now has enough diagnostic boundaries that implementation risk is drifting from missing code to scattered decision-making. Future batches need one planning artifact that says which law families are native/static only, diagnostic-only, or blocked by specific missing surfaces.

Source slice added June 16:

- `docs/custom_law_no_compromise_readiness_matrix.md` records cross-cutting blockers, law-family readiness, faction-specific blockers, and the activation rule for moving any law into gameplay implementation.
- The matrix does not authorize new gameplay.
- The matrix explicitly keeps Resource Riches unified and Castle native/static-only where exact.
- The matrix treats every family-dependent custom mechanic as disabled until active law/rank, native hook context, classifier facts, diagnostics, and user-driven runtime scenarios are named.

## Batch 20: Surface activation packets

Reason for twentieth batch: the readiness matrix identifies blockers, but future implementation agents need a uniform packet format before converting diagnostics into gameplay. This prevents ad hoc hook-specific rules and keeps fail-closed behavior central.

Source slice added June 16:

- `docs/custom_law_surface_activation_packets.md` defines the required packet template for activating any law surface.
- It adds packets for active law/rank, battle action classification, geometry/formations, committed damage, buff/debuff identity, Focus, spell cooldown/cast gate, reward/result/economy, construction, Gating/summon identity, corpse/mana, and morale/action queue effects.
- The packet document does not authorize gameplay implementation.
- A law remains disabled unless its packet can name exact native symbols, active rank source, consumed/mutated state, classifier facts, idempotence key, diagnostic flag, runtime scenario, and documentation update.

## Batch 21: Runtime capture checklist

Reason for twenty-first batch: the activation packets define what must be proven, but user-driven testing needs a repeatable checklist so logs capture the exact evidence future implementation packets require.

Source slice added June 16:

- `docs/custom_law_runtime_capture_checklist.md` defines capture scenarios and required log evidence for law/rank, battle action/formations, committed damage, buff/debuff/status, Focus, spell cooldown/cast gate, reward/result/economy, construction, Gating/summon, corpse/mana, and morale.
- The checklist does not authorize gameplay implementation.
- The checklist explicitly treats `none-or-unresolved` law state and `classifier unknown` as fail-closed diagnostic results.

## Batch 22: Validation ledger

Reason for twenty-second batch: accumulated diagnostic, classifier, and tooling work must not be mistaken for build-validated or runtime-proven behavior.

Source slice added June 16:

- `docs/custom_law_validation_ledger.md` records authored but unvalidated C# changes, unrun scripts, and runtime-unproven diagnostic surfaces.
- The ledger is documentation-only and does not run validation.
- Future build, script, and runtime proof passes should update this ledger with exact commands and evidence rather than overwriting AGENTS notes ad hoc.

## Batch 23: Diagnostic flag profiles

Reason for twenty-third batch: the runtime capture checklist needs reproducible flag sets so user-driven proof captures can be prepared without hand-copying flag names.

Source slice added June 16:

- `custom_factions/custom_law_diag_profiles.json` defines named diagnostic profiles for law-tree, construction, battle-action, committed-damage, buff-status, Focus, spell-cooldown, reward-result, and morale captures.
- `tools/release_port/custom_law_diag_flags.py` can list, apply, or clear those profile flags when given an explicit `--plugin-root`.
- The script has not been run and does not start the game.
- Applying a profile only creates diagnostic `.flag` files; it does not prove any surface or authorize gameplay.

## Batch 24: Runtime capture bundler

Reason for twenty-fourth batch: user-driven runtime captures need a consistent raw-evidence bundle so later proof reviews can trace logs, profiles, and scenario notes without relying on thread memory.

Source slice added June 16:

- `tools/release_port/collect_custom_law_capture.py` was added as an opt-in log/artifact bundler.
- It requires explicit `--game-root` and `--scenario`.
- It copies `BepInEx/LogOutput.log`, `BepInEx/ErrorLog.log`, optional `Player.log`, and optional extra logs into `artifacts/custom_law_captures/<timestamp>_<scenario>/`.
- It writes `scenario_notes.md` and `capture_manifest.json` with `proofStatus=raw-unreviewed`.
- It has not been run and does not review or prove any surface.
