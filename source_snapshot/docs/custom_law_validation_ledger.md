# Custom Law Validation Ledger

This ledger tracks no-compromise faction law work that has been authored but not yet validated.

Validation states:

- `authored`: file exists or source changed.
- `static-unrun`: validator/build/check exists but has not been run.
- `build-pending`: C# source changed and needs compile validation.
- `runtime-unproven`: code or diagnostic exists but has not been proven in game.
- `proven`: update only after concrete build/runtime evidence is recorded.

## Current pending source validation

| Area | Files | State | Required next gate |
|---|---|---|---|
| Formation probe diagnostics | `Homm3BattleEventLawDiagnostics.cs` | `build-validated`, `runtime-unproven` | User-driven combat with `homm3_battle_event_law_diag.flag`. |
| Unit law classifier | `Homm3UnitLawClassifier.cs` | `build-validated`, `runtime-unproven` | Confirm `classifierEvidence={...}` logs in a relevant battle context. |
| Unit law family registry | `Homm3UnitLawFamilyRegistry.cs` | `build-validated`, `static-validated`, `runtime-unproven` | Registry drift check passes after regeneration. Runtime classifier/family usage is still unproven. |
| Runtime packet proof gate | `Homm3CustomLawPacketGate.cs` | `build-validated`, `static-validated`, `runtime-unproven` | Packet gate drift check passes after regeneration. All packet-backed gameplay remains denied until proof state is explicitly promoted. |
| Combined law runtime guard | `Homm3CustomLawRuntimeGuard.cs` | `build-validated`, `runtime-unproven` | Future packet-backed gameplay hooks should use this combined active-law/rank plus packet-proof guard or the handler registry seam. |
| Custom law handler registry seam | `Homm3CustomLawHandlerRegistry.cs` | `build-validated`, `static-validated`, `startup-proven`, `gameplay-unproven` | Startup registration logs handler slots through `homm3_custom_faction_law_diag.flag`; gameplay handler behavior remains blocked until packet proof promotion. |
| Packet proof-state and handler-slot law diagnostic snapshot | `Homm3CustomFactionLawRuntime.cs` | `build-validated`, `startup-proven`, `gameplay-unproven` | Golden Era startup log proves packet proof states are visible and all denied, and handler slots match the static registry. This is not packet gameplay proof. |
| Construction diagnostic surface map | `Homm3CustomConstructionLawDiagnostics.cs`, `GameSymbols.ConstructionLaws` | `build-validated`, `startup-proven`, `gameplay-unproven` | Golden Era startup log proves all 7 candidate trace patches register. A user-driven town build capture is still required before promoting the construction packet. |
| Bulwark/Factory law targets | `custom_factions/custom_law_targets.json` | `authored`, `static-unrun` | Author 26 faction-flavored target entries (13 tracked indexes x bulwark/factory; names/mechanics cannot be mirrored — existing families are faction-specific). `audit_custom_law_overrides_against_targets.py` currently fails with 26 no-target errors. Recorded 2026-09-19; do not mark native-exact until override rows carry real mechanics. |

Latest build validation:

- June 16: `dotnet build "Heroes of Might & Magic Olden Era Playtest\OfflineUnlockMod\OfflineUnlockMod.csproj" -c Release --no-restore -v:minimal -clp:ErrorsOnly -p:DeployPluginToGame=false` succeeded with 0 errors and 45 warnings after packet-gate and unit-family-registry regeneration.
- June 16: earlier deploy build `dotnet build "Heroes of Might & Magic Olden Era Playtest\OfflineUnlockMod\OfflineUnlockMod.csproj" -c Release --no-restore -v:minimal -clp:ErrorsOnly` succeeded with 0 errors and 33 warnings, and `homm3_custom_faction_law_diag.flag` was created in the Golden Era plugin root.
- June 16: fresh DLL deploy to Golden Era was startup-proven. Source and deployed SHA256 matched `292C9D6D8831D444522166E2FED577EEEA336847818B4368D148650FE66D8F3B`; `BepInEx\LogOutput.log` lines 454-455 logged packet proof gate states and no-compromise handler slots.
- June 17: construction diagnostic surface repair build `dotnet build "Heroes of Might & Magic Olden Era Playtest\OfflineUnlockMod\OfflineUnlockMod.csproj" -c Release --no-restore -v:minimal -clp:ErrorsOnly -p:DeployPluginToGame=false` succeeded with 0 errors and 45 warnings. Fresh Golden Era deploy SHA256 matched `C987FAC8FF0DC00EF23F2BED62B25B0EFD874C6523A0153ADDC82D2FA97B4F2D`.

Latest non-strict static gate result:

- June 16: `python tools/release_port/check_custom_law_no_compromise_static.py` now passes after normalizing target faction keys, adding missing law index `19` targets for Dungeon/Fortress/Rampart, regenerating `Homm3CustomLawPacketGate.cs`, regenerating `Homm3UnitLawFamilyRegistry.cs`, and marking concrete non-final donor rows with explicit temporary-compromise/runtime-debt notes.
- June 16: the passing static gate now uses the hardened checks: runtime guard usage scans every top-level C# source file, packet-gate generation fails on unmapped target family indices, and override notes must carry explicit compromise/runtime-debt/packet language rather than vague donor-substitute wording.
- Remaining warnings are explicit missing override rows for `castle_6`, `castle_34`, `cove_6`, `cove_25`, `fortress_25`, `tower_25`, `inferno_25`, and `necropolis_25`; these are source-row coverage questions, not hidden fallback permission.

## Current pending script validation

| Script | State | Required next gate |
|---|---|---|
| `tools/release_port/validate_custom_law_targets.py` | `static-unrun` | Run against `custom_factions/custom_law_targets.json` when validation is requested; passing it proves only target-spec shape and override SID presence, not gameplay readiness. |
| `tools/release_port/validate_custom_law_runtime_index_coverage.py` | `static-unrun` | Run against `custom_factions/custom_law_targets.json` and `Homm3CustomFactionLawRuntime.cs`; passing it proves target family/runtime-index coverage only, not build or runtime behavior. |
| `tools/release_port/validate_custom_law_target_matrix.py` | `static-validated` | June 16 direct run passed after normalizing target faction keys and adding missing law index `19` targets for Dungeon, Fortress, and Rampart. Passing it proves target matrix coverage only, not gameplay readiness. |
| `tools/release_port/report_custom_law_target_coverage.py` | `static-unrun` | Run after the target spec validates to emit a packet/status report; the report is planning evidence only, not gameplay proof. |
| `tools/release_port/generate_custom_law_implementation_queue.py` | `static-unrun` | Run after the target spec validates to emit a packet-ordered implementation backlog; generated output is planning evidence only. |
| `tools/release_port/report_custom_law_strict_candidate_rows.py` | `static-unrun` | Run after target/override data is reviewable to emit a strict-candidate report showing which non-final laws still have source bonuses and would need stripping or packet implementation. Packet names are resolved from the target family map. Planning evidence only. |
| `tools/release_port/audit_custom_law_overrides_against_targets.py` | `static-unrun` | Run after target validation to surface hidden compromise rows in `custom_factions/law_overrides`; failing rows are bookkeeping/code-hygiene debt, not runtime proof. |
| `tools/release_port/validate_custom_law_diag_profiles.py` | `static-unrun` | Run against `custom_factions/custom_law_diag_profiles.json` and `custom_factions/custom_law_targets.json`; passing it proves profile/packet coverage only, not runtime behavior. |
| `tools/release_port/validate_custom_law_packet_proofs.py` | `static-unrun` | Run against `custom_factions/custom_law_packet_proofs.json` and `custom_factions/custom_law_targets.json`; passing it proves proof-ledger coverage and gating shape only, not runtime behavior. |
| `tools/release_port/promote_custom_law_packet_proof.py` | `static-unrun` | Use only after reviewed runtime evidence; promotes one packet proof entry with required artifact/scenario/symbol/state/docs metadata. It does not regenerate C#, build, launch, or validate. |
| `tools/release_port/generate_custom_law_packet_gate.py --check` | `static-validated` | Combined static gate confirms checked-in `Homm3CustomLawPacketGate.cs` is in sync with target/proof JSON. Passing proves static sync only, not runtime behavior. |
| `tools/release_port/audit_custom_law_runtime_guard_usage.py` | `static-validated` | Combined static gate confirms no disallowed direct active-law/packet-gate usage in custom law C# sources. |
| `tools/release_port/validate_custom_law_handler_registry.py` | `static-validated` | Combined static gate confirms exactly one named handler slot for every target family law index and matching family packet. Static source hygiene only. |
| `tools/release_port/check_custom_law_no_compromise_static.py` | `static-validated` | June 16 non-strict run passed after target matrix, packet-gate drift, override-target audit, and unit-family registry drift fixes. It does not build, launch, mutate Core, or prove runtime behavior. |
| `tools/release_port/apply_release_core_overlay.py --require-no-compromise-law-static` | `static-unrun` | Optional overlay preflight that runs the combined no-compromise law static gate before building overlay output; fail-closed static hygiene only, not runtime proof. |
| `tools/release_port/apply_release_core_overlay.py` no-compromise law row metadata | `static-unrun` | Overlay law row generation now stamps target status/packet/mechanic metadata from `custom_law_targets.json`; overlay has not been run to prove output shape. |
| `tools/release_port/validate_custom_law_core_metadata.py --core <Core.zip>` | `static-unrun` | Post-overlay Core.zip validator for generated `xHomm3NoCompromise*` law row metadata. Passing it proves metadata presence only, not gameplay behavior. |
| `tools/release_port/apply_release_core_overlay.py --validate-no-compromise-law-core-metadata` | `static-unrun` | Optional candidate-Core overlay gate that runs `validate_custom_law_core_metadata.py --core <candidate Core.zip>` after biome packing and before release replacement. Passing it proves generated law metadata traceability only, not gameplay behavior or packet proof. |
| `tools/release_port/validate_custom_law_strict_no_compromise_rows.py` | `static-unrun` | Strict source/Core validator for no-compromise candidates. It resolves packet names from target families and fails if any non-`native-exact` target law still carries concrete bonuses, if source overrides are missing for non-final targets, or if stripped Core rows lack pending descriptions naming the target mechanic and packet. It is expected to fail while temporary donor compromises remain. |
| `tools/release_port/check_custom_law_no_compromise_static.py --strict-no-compromise-law-rows` | `static-unrun` | Optional combined-gate mode that adds the strict source-row compromise validator. This is intentionally separate from the default playable static gate. |
| `tools/release_port/apply_release_core_overlay.py --strict-no-compromise-law-rows` | `static-unrun` | Optional strict overlay mode that runs the strict validator against source law overrides before output generation and against the candidate Core.zip before release replacement. It is expected to fail while temporary donor compromises remain. |
| `tools/release_port/apply_release_core_overlay.py --strip-nonfinal-no-compromise-law-bonuses` | `static-unrun` | Optional strict-candidate transform that strips concrete bonuses from generated non-`native-exact` target law rows before candidate validation and rewrites stripped law descriptions as pending no-compromise implementations. It preserves source overrides but does not implement gameplay. |
| `tools/release_port/validate_unit_family_tags.py` | `static-validated` | Combined static gate validates `custom_factions/unit_family_tags.json`; current authored tag set is empty but valid. |
| `tools/release_port/generate_unit_family_registry.py` | `static-validated` | Registry was regenerated from the validated tag source. |
| `tools/release_port/check_unit_family_registry_drift.py` | `static-validated` | Combined static gate confirms generated registry is in sync with `custom_factions/unit_family_tags.json`. |
| `tools/release_port/sync_unit_family_tag_placeholders.py` | `static-unrun` | Run only when placeholder expansion is intentionally requested; it will author `unknown` entries. |
| `tools/release_port/custom_law_diag_flags.py` | `static-unrun` | Run only when preparing or clearing a user-driven runtime capture profile. |
| `tools/release_port/collect_custom_law_capture.py` | `static-unrun` | Run only after a user-driven runtime scenario to collect raw evidence logs into an artifact bundle. |
| `tools/release_port/analyze_construction_law_capture.py` | `authored`, `smoke-tested` | Mechanical checklist analyzer for construction packet captures. Current live log proves registration but exits non-zero because no town build interaction traces exist yet. |

## Current pending runtime proof

| Surface | Diagnostic flag | State | Required user-driven proof |
|---|---|---|---|
| Active law/rank resolver | `homm3_custom_faction_law_diag.flag` | `runtime-unproven` in consuming hooks | Active/applied law rows correlate with side object in the exact hook context. |
| Construction candidate chain | `construction` profile | `surface-registration-proven`, `packet-runtime-unproven` | Startup proves all 7 construction diagnostic patches and 2 economy diagnostic patches register. Use `docs/custom_law_construction_capture_instructions.md`; user-driven build capture must show displayed cost, charged cost, eligibility, build commit, resource mutation, active rank, and constructed state agree. |
| Battle action/formations | `homm3_battle_event_law_diag.flag` | `runtime-unproven` | Visible melee/ranged/first-action/adjacency scenarios match logged action and `formationProbe` evidence. |
| Committed damage | `homm3_battle_event_law_diag.flag` | `runtime-unproven` | `damage-apply-candidate` and `ObjectTookDamageEventArgs` match visible committed damage and death ordering. |
| Buff/debuff/status | `homm3_buff_debuff_law_diag.flag` | `runtime-unproven` | Buff SID, receiver, caster/source, duration, stacking, and active rank correlate. |
| Focus/Energy | `homm3_focus_law_diag.flag` | `runtime-unproven` | Native storage, UI, and cast/ability availability remain synchronized. |
| Spell cooldown/cast gate | `homm3_spell_cooldown_law_diag.flag`, `homm3_spell_cast_gate_law_diag.flag` | `runtime-unproven` | Cooldown storage, gate result, spellbook UI, and execution agree. |
| Reward/result/economy | `homm3_reward_commit_law_diag.flag`, `homm3_battle_result_law_diag.flag`, optional `homm3_custom_faction_economy_diag.flag` | `runtime-unproven` | Reward/result source identity and idempotent commit ordering are proven. |
| Morale trigger | `homm3_morale_trigger_law_diag.flag` | `runtime-unproven` | Roll result, visible extra/failure action, queue ordering, and active rank correlate. |

## Current diagnostic flag profile tooling

| Artifact | State | Notes |
|---|---|---|
| `custom_factions/custom_law_targets.json` | `authored` | No-compromise target mechanics for custom faction laws. This is the intended destination, not proof that current donor rows implement those mechanics. |
| `custom_factions/custom_law_targets.json` law index 15 coverage | `authored`, `static-unrun` | Lower spell-school/access row is now tracked by the target spec and maps to the `spell-cooldown` packet; static validation has not been run. |
| `tools/release_port/validate_custom_law_runtime_index_coverage.py` | `authored`, `static-unrun` | Fails if `Homm3CustomFactionLawRuntime.KnownRuntimeLawIndices` and `custom_law_targets.json` family indices diverge. |
| `tools/release_port/validate_custom_law_target_matrix.py` | `authored`, `static-validated` | Treats target `faction` as the canonical bare HoMM3 key derived from enabled manifest SIDs (`homm3_castle` -> `castle`) and validates law SID shape against that key. June 16 direct run passed after adding missing law index `19` targets. |
| `tools/release_port/report_custom_law_target_coverage.py` | `authored`, `static-unrun` | Emits a Markdown planning report from target statuses and packets so `temporary-compromise` and `needs-runtime` rows stay visible between batches. |
| `tools/release_port/generate_custom_law_implementation_queue.py` | `authored`, `static-unrun` | Emits Markdown or JSON implementation backlog entries from target statuses, packets, and next-action policy. |
| `tools/release_port/report_custom_law_strict_candidate_rows.py` | `authored`, `static-unrun` | Emits Markdown planning rows for strict candidate output: source bonus count, family-derived packet, and action (`keep-native-row`, `strip-generated-bonuses-or-implement-packet`, `strict-placeholder-ready`, or `strict-source-missing-row`). |
| `tools/release_port/audit_custom_law_overrides_against_targets.py` | `authored`, `static-unrun` | Audits current override rows against target statuses and requires explicit notes when a non-native-exact target still has concrete `parametersPerLevel` rows. |
| `custom_factions/custom_law_diag_profiles.json` | `authored` | Named flag profiles for law-tree, vision, counterattack, construction, battle-action, committed-damage, buff-status, Focus, spell-cooldown, reward-result, and morale captures. |
| `tools/release_port/validate_custom_law_diag_profiles.py` | `authored`, `static-unrun` | Confirms every packet named by `custom_law_targets.json` has a matching diagnostic profile and that non-law-tree profiles include active law/rank diagnostics. |
| `custom_factions/custom_law_packet_proofs.json` | `authored` | Packet proof-state ledger; all current packet entries are runtime-unproven and gameplayAllowed=false. |
| `tools/release_port/validate_custom_law_packet_proofs.py` | `authored`, `static-unrun` | Confirms every packet named by `custom_law_targets.json` has proof state and that gameplayAllowed cannot be true without runtime-proven evidence artifact metadata. |
| `tools/release_port/promote_custom_law_packet_proof.py` | `authored`, `static-unrun` | Controlled proof promotion helper requiring existing evidence artifact plus explicit scenario, flags, native symbols, consumed state, mutated state, docs updated, and confirmation text. |
| `tools/release_port/generate_custom_law_packet_gate.py` | `authored`, `static-validated` | `--check` passes through the combined static gate after regeneration. Static sync only; not runtime proof. |
| `Homm3CustomLawPacketGate.cs` | `authored`, `build-validated`, `static-validated`, `runtime-unproven` | Runtime-side fail-closed API compiles and is in sync with target/proof JSON. All packet-backed gameplay is still denied until proof state is explicitly promoted. |
| `Homm3CustomLawRuntimeGuard.cs` | `authored`, `build-validated` | Combined guard that returns active law state only after both active law/rank resolution and packet gameplay permission succeed. |
| `Homm3CustomLawHandlerRegistry.cs` | `authored`, `build-validated`, `static-validated`, `startup-proven`, `gameplay-unproven` | Named handler-slot seam for future gameplay hooks. Static handler registry validator passed and startup log lists the expected slots; gameplay behavior remains packet-blocked. |
| `tools/release_port/audit_custom_law_runtime_guard_usage.py` | `authored`, `static-validated` | Static source audit passes through the combined static gate. It permits diagnostics/runtime infrastructure, treats `Homm3CustomLawHandlerRegistry.cs` as infrastructure, errors on direct active-law/packet-gate use outside the guard path, and warns when gameplay files use the lower-level guard instead of a named handler slot. |
| `tools/release_port/validate_custom_law_handler_registry.py` | `authored`, `static-validated` | Static source validator passes through the combined static gate, comparing target family law indices and packets to `Homm3CustomLawHandlerRegistry.KnownHandlerSlots`. |
| `Homm3CustomFactionLawRuntime.cs` packet proof-state and handler-slot log | `authored`, `build-validated`, `startup-proven`, `gameplay-unproven` | Existing law diagnostics print `Homm3CustomLawPacketGate.DescribeKnownProofStates()` and `Homm3CustomLawHandlerRegistry.DescribeHandlerSlots()` when `homm3_custom_faction_law_diag.flag` is enabled. Golden Era startup log lines 454-455 prove both are visible and all packets remain denied. |
| `tools/release_port/check_custom_law_no_compromise_static.py` | `authored`, `static-validated` | Single-command static gate now passes for no-compromise law target/spec/profile/override/unit-family hygiene; optional report mode writes `artifacts/custom_law_static/custom_law_target_coverage.md`, `custom_law_implementation_queue.md`, and `custom_law_strict_candidate_rows.md` after a passing static gate. |
| `tools/release_port/apply_release_core_overlay.py` no-compromise law preflight | `authored`, `static-unrun` | New opt-in `--require-no-compromise-law-static` flag fails overlay before output generation if the static law gate fails. |
| `tools/release_port/apply_release_core_overlay.py` no-compromise law row metadata | `authored`, `static-unrun` | Generated custom law rows receive `xHomm3NoCompromiseTarget`, `xHomm3NoCompromiseStatus`, `xHomm3NoCompromisePacket`, and `xHomm3NoCompromiseTargetMechanic` when target data exists. |
| `tools/release_port/validate_custom_law_core_metadata.py` | `authored`, `static-unrun` | Validates a generated Core.zip contains no-compromise target metadata on every target-backed custom law row. |
| `tools/release_port/apply_release_core_overlay.py` no-compromise law Core metadata gate | `authored`, `static-unrun` | New opt-in `--validate-no-compromise-law-core-metadata` flag validates the candidate Core.zip with `validate_custom_law_core_metadata.py` before release replacement. It has not been run and is metadata traceability only. |
| `tools/release_port/validate_custom_law_strict_no_compromise_rows.py` | `authored`, `static-unrun` | Fails strict no-compromise source rows when non-`native-exact` targets have concrete bonuses or lack explicit override rows; with `--core`, it inspects generated Core.zip target rows for concrete non-final bonuses and verifies stripped descriptions are visibly pending with family-derived packet names. |
| `tools/release_port/check_custom_law_no_compromise_static.py --strict-no-compromise-law-rows` | `authored`, `static-unrun` | Optional strict mode for the combined static gate. It is expected to fail until temporary donor compromises are removed or implemented as proven packets. |
| `tools/release_port/apply_release_core_overlay.py` strict no-compromise law rows | `authored`, `static-unrun` | New opt-in `--strict-no-compromise-law-rows` flag runs strict source validation before overlay generation and strict candidate-Core validation before release replacement. |
| `tools/release_port/apply_release_core_overlay.py` strict non-final row stripping | `authored`, `static-unrun` | New opt-in `--strip-nonfinal-no-compromise-law-bonuses` flag removes generated concrete bonuses from non-final target rows, stamps `xHomm3NoCompromiseStrictRows`, and rewrites stripped law description tokens to pending text that names the target mechanic and packet. |
| `tools/release_port/custom_law_diag_flags.py` | `static-unrun` | Requires explicit `--plugin-root`; can list/apply/clear profile flags. |
| `tools/release_port/collect_custom_law_capture.py` | `static-unrun` | Requires explicit `--game-root`; copies logs and metadata only, does not review proof. |

## Rules for updating this ledger

- After a build succeeds, change only the relevant `build-pending` rows to build-validated and include the exact command.
- After a script check succeeds, record the command and the artifact checked.
- After runtime proof, record the exact flag set, scenario, observed log evidence, and whether the surface is still diagnostic-only or ready for a gameplay packet.
- Do not remove pending rows silently.
- Do not mark a surface proven because a related surface was proven.

## 2026-06-20 Fortress candidate-surface pilot setup

Status: setup-proven, gameplay-runtime-unproven.

- Corrected Golden Era deployment path: `OfficialDeobfBuild=true` writes the current DLL to `Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/bin/Debug/netstandard2.1`, not `bin/Release/netstandard2.1`. Deployed DLL length after correction: `3232256` bytes.
- Live bridge status now advertises `custom_law_candidate_surface_status`; direct bridge call returns candidate surface counters for battle-action and morale plus registration strings for committed-damage, counterattack, spell-cooldown, reward-result, and Rampart Avenger marker.
- Broadened `ai_buy_law` setup helper: it now accepts any syntactically valid custom faction law SID, then still requires exact native law wrapper lookup and native `canApply` before invoking native apply. This is a test setup route, not gameplay fallback behavior.
- Fortress setup in current runtime bought the relevant runtime rows: `fraction_law_homm3_fortress_6` rank 1, `13` rank 1, `18` rank 1, `19` rank 2, `22` rank 2, and `25` rank 3. `fraction_law_homm3_fortress_34` failed exact native wrapper lookup and is not present/testable in the Fortress native law tree for this pilot.
- Candidate counters before combat: battle-action observed/applied/failed all `0`; morale observed/applied/unimplemented/failed all `0`; committed-damage, counterattack, spell-cooldown, reward-result, and Rampart Avenger marker all report startup registrations only.

UI navigation note: Computer Use can launch and screenshot the visible game window, but this session has no reliable mouse-hover primitive exposed through the helper API. Use visible screenshots plus AI bridge setup for pre-combat state; manual player piloting remains the reliable route for combat action sequencing.

## 2026-06-20 Candidate surface counter bridge setup

Status: source-prepared and build-proven; deploy blocked by the currently running Golden Era process locking the plugin DLL.

Changes prepared:
- Added Homm3CandidateSurfaceRuntimeCounters as a central structured counter for already-emitted candidate-law runtime diagnostics.
- Wired the counter into committed-damage, counterattack, squadValue economy, Rampart Avenger marker sync, spell-cooldown, and visual-marker runtime LogLimited paths.
- Extended custom_law_candidate_surface_status to return candidateCounters alongside the existing battle-action, morale, and registration surfaces.

Validation:
- Golden Era build passed with 44 warnings and 0 errors.
- Deployment to the Golden Era plugin DLL was attempted and failed because the running game holds OfflineUnlockMod.dll open. The deployed DLL is still the previous build until the game is closed and the Debug OfficialDeobf DLL is copied.

Runtime implication:
- The current running session can still provide old coarse counters and logs, but it will not expose candidateCounters until restart after deploy.


## 2026-06-20 Combat pilot UI controls

Status: user-validated navigation guidance for future runtime pilots.

Combat movement and attack rules:
- Clicking an empty hex/space in combat moves the active unit there, if the hex is inside the active unit's green movement area.
- The green area is the active unit's actual legal movement range.
- Clicking an enemy unit along the edge of the hex you want to attack from commits an attack from that direction.
- The correct attack hover is shown by a sword icon pointing in the attack direction.
- A yellow radius while hovering a unit is not the active unit's movement range. It shows where the hovered unit could move.

Pilot implication:
- For melee attack/counterattack tests, move only inside the green range, then hover/click the enemy from the intended adjacent edge and confirm the sword-direction icon before committing.
- Do not treat yellow hover radius as reachable movement for the active unit.


## 2026-06-20 Combat pilot control notes

Status: user-observed / pilot guidance.

- Clicking an empty combat hex/space moves the active unit.
- The green area is the active unit's legal movement area.
- A yellow radius appears when hovering a unit; it shows where the hovered unit could move, not where the active unit can move.
- To melee attack, click the enemy unit along the edge of the hex you want to attack from.
- The sword cursor pointing in the attack direction confirms that the hover target is an attack, not movement.

Testing implication: future melee/counterattack pilots should explicitly hover the target edge until the sword cursor appears, then click, and should not interpret yellow hover radii as legal movement for the active unit.

## 2026-06-20 Fortress candidate-surface pilot setup refresh

Status: setup-proven, gameplay-runtime-unproven.

Bridge evidence:
- AI bridge status was fresh in `worldLight` and advertised `ai_observe`, `ai_grant_law_points`, `ai_buy_law`, and `ai_start_match`; `ai_open_town` and `ai_start_combat` remain absent.
- Live bridge status was fresh in `worldLight` and `custom_law_candidate_surface_status` returned the deployed `candidateCounters` field.
- Repeated `ai_grant_law_points` calls are required because the setup helper effectively grants in bounded batches. The last grant observed `beforeLawPoints=117` and `afterLawPoints=127` with `nativeLevelUpInvoked=true`.

Native law setup result:
- Bought Fortress rank-1 laws in native row order through `fraction_law_homm3_fortress_31`, raising spent points to 98 and unlocking deeper rows.
- Target runtime rows active for this pilot:
  - `fraction_law_homm3_fortress_6` rank 1, spent points 17.
  - `fraction_law_homm3_fortress_13` rank 1, spent points 37.
  - `fraction_law_homm3_fortress_18` rank 1, spent points 52.
  - `fraction_law_homm3_fortress_19` rank 2, spent points 101.
  - `fraction_law_homm3_fortress_22` rank 2, spent points 103.
  - `fraction_law_homm3_fortress_25` rank 3, spent points 105.
- Higher-rank attempts for `6`, `13`, and `18` were rejected by native `canApply=false` with `cost=-1`, consistent with those rows being maxed at rank 1 in the native tree for this build.
- `fraction_law_homm3_fortress_34` still fails exact native wrapper lookup and is not testable through the current Fortress tree state. Treat this as a data/tree availability issue to investigate separately, not as a combat surface proof.

Pre-combat counter state:
- `candidateCounters` was empty immediately after setup, which is expected before combat/reward/spell events.
- Registrations remained present: battle-action exact dispatcher patch, morale exact patches, committed-damage prefix, counterattack change-event patches, spell-cooldown add-cooldown prefix/postfix, reward-result prefix, and Rampart Avenger postfix.

Next pilot:
- Start or enter a Fortress combat.
- Trigger at least one normal melee attack that receives a counterattack.
- Trigger one ranged attack if a shooter turn appears.
- Trigger positive morale if practical.
- After each cluster, poll `custom_law_candidate_surface_status` and inspect `candidateCounters` instead of relying on broad logs.

## 2026-06-20 Computer-driven Fortress combat entry attempt

Status: partial-runtime-observed, action-commit-blocked.

Setup:
- Fortress runtime target rows remained active from the prior AI bridge setup.
- Computer Use clicked the visible hostile stack west of the selected Fortress hero on the adventure map.
- First click revealed an attack/encounter preview for an `Impossible Battle` stack of 20-49 enemies.
- Follow-up click plotted a route to the hostile stack; clicking the route endpoint opened the pre-battle `DEFEAT` preview.
- Clicking `BATTLE!` entered manual combat and reached the tactics phase, then the combat phase.

Observed runtime evidence:
- Live bridge candidate status during combat showed registrations intact.
- `candidateCounters` moved from empty to `unknown.observed=108`, `unknown.failed=88`, `unknown.skipped=20`.
- Last recorded message: `HoMM3 counterattack doctrine mutation skipped: native ability type is not CounterAttack: Ability index=0`.
- This proves combat callbacks are reaching candidate-law runtime logging, but the new structured classifier is too narrow and is bucketing known counterattack-doctrine diagnostic messages under `unknown`.

UI/action issue:
- In combat, Computer Use could produce a visible ranged targeting line and damage preview against an enemy stack, but repeated clicks did not commit the shot.
- Treat this as a Computer-driven combat-click limitation until we identify the exact commit gesture. Manual hover/click remains more reliable for combat actions.

Next engineering action:
- Broaden `Homm3CandidateSurfaceRuntimeCounters` classification for known runtime diagnostic families, especially `counterattack doctrine mutation skipped`, so failed/skipped candidate hooks are attributed to their intended surface instead of `unknown`.
- Continue runtime proof after classifier cleanup or with manual player action clusters.

## 2026-06-20 Combat targeting preview correction

Status: user-validated navigation guidance; source classifier fix build-proven, deploy-pending.

UI correction:
- A hover/target preview line or damage preview does not mean the active unit is currently in range to perform the attack.
- The active unit's green ground aura is the authority for what the currently active unit can actually reach or do.
- Yellow hover information and target previews describe the hovered/targeted unit or potential action information, not necessarily a commit-ready action.

Pilot implication:
- Future Computer-driven combat tests must not treat a ranged preview line as proof that the attack can be executed.
- For attack commits, first verify that the active unit's green aura supports the destination/attack state; otherwise the preview may remain non-committing.

Diagnostic classifier update:
- Broadened `Homm3CandidateSurfaceRuntimeCounters` classification for known runtime diagnostics: counterattack doctrine mutation/correlation, battle owner registry hits, battle-event diagnostics, training-damage skips/allowed gates, Fortress receiver reduction, formation gates, and morale diagnostics.
- Build command passed: `dotnet build "Heroes of Might & Magic Olden Era Playtest\OfflineUnlockMod\OfflineUnlockMod.csproj" --no-restore -p:OfficialDeobfBuild=true -v:q` with 44 warnings and 0 errors.
- Deployment is still pending because the running game has the old DLL loaded. This classifier update will not affect live `candidateCounters` until restart/deploy.

## 2026-06-20 Classifier fix deployed and Fortress setup restored

Status: deploy-proven, setup-proven, gameplay-runtime-unproven for the new classifier build.

Deployment:
- Closed the running Golden Era process to release the plugin DLL lock.
- Copied rebuilt `OfflineUnlockMod.dll` to the Golden Era BepInEx plugin directory.
- Deployed DLL length: `3239424` bytes.
- Relaunched Golden Era visibly; AI bridge and live bridge both reached `ready` on `startMenu`, then the AI bridge started a Fortress match and the game reached `worldLight`.

Setup notes:
- One `ai_grant_law_points` request timed out during/after match loading, but later state showed it had applied in the background: subsequent grants began at `beforeLawPoints=10`.
- Additional grants raised law points to `120`.
- Native AI law buying restored the Fortress target setup on the deployed classifier build:
  - `fraction_law_homm3_fortress_6` active rank 1.
  - `fraction_law_homm3_fortress_13` active rank 1.
  - `fraction_law_homm3_fortress_18` active rank 1.
  - `fraction_law_homm3_fortress_19` active current level 1 after the targeted rank-2 request; the earlier row-order rank-1 request failed before line 4 was visible.
  - `fraction_law_homm3_fortress_22` active rank 2.
  - `fraction_law_homm3_fortress_25` active rank 3.
- `candidateCounters` was empty before combat, confirming a clean counter baseline on the deployed classifier build.

Next pilot:
- Enter combat and trigger damage/counterattack/morale again. The next `custom_law_candidate_surface_status` should now categorize known diagnostics under specific keys instead of `unknown`.

## 2026-06-20 Adventure-map encounter commit attempts

Status: Computer-driven route partially falsified; native/decomp route needed.

Observed UI behavior:
- Clicking a nearby hostile stack shows a lethal battle preview.
- Repeated target clicks can show preview/path information, but do not reliably commit movement or combat from Computer Use.
- Clicking the bottom-right green checkmark while the preview is visible dismissed the preview instead of committing the encounter.
- Pressing `Return` while the preview is visible did not commit the encounter.

Conclusion:
- Computer Use can identify hostile encounter targets and preview battles, but cannot yet reliably commit an adventure-map encounter through the currently known click/key sequence.
- Future progress should use decomp/live bridge evidence to expose a native-friendly adventure-map interaction or combat setup command rather than continuing blind UI attempts.

## 2026-06-20 Combat targeting preview correction

Status: user-proven UI behavior note.

- Showing a hover/attack preview does not prove the enemy is in attack range for the active unit.
- The active unit's green ground aura is the authority for where the currently active unit can move or attack from.
- Yellow aura/radius shown while hovering a unit belongs to the hovered unit, not necessarily the active unit.
- Practical implication for Computer Use pilots: do not infer legal attack range from preview alone; use green reachable tiles for active-unit movement/attack setup.

## 2026-06-20 Adventure-map movement exhaustion note

Status: user-proven UI behavior note.

- Failed hostile-encounter commits can be caused by the active hero being out of movement, even when hover previews or route previews still appear.
- Do not treat non-committing hostile clicks as a combat setup or bridge failure until current hero movement is checked.
- Practical implication: future Computer/AI pilots should either start from a fresh-turn hero with movement, use a bridge/AI command to advance/setup movement when available, or select a reachable encounter before attempting combat entry.

## 2026-06-20 Faux-combat validation strategy note

Status: planning note; not runtime-proven.

- A pure code-only faux combat can validate our own law predicates, arithmetic, idempotence, and state containers, but it cannot prove native Olden Era hook surfaces such as committed damage, morale action, counterattack identity, spell cooldown, reward result, or battle result dispatch.
- Autobattle is likely useful as a driver for an already-created native battle, not as evidence that a full battle can be instantiated safely from the main menu without session/map state. This remains unproven until decomp/live bridge evidence identifies a native battle setup entrypoint.
- Practical validation split: use a code harness for deterministic law logic tests, and use a native bridge/autobattle driver for surface proof against real battle/session objects.

## 2026-06-20 Mono demo semantic reference discovery

Status: static-reference-discovered; not yet mapped to current deobf runtime.

- The Steam demo at `V:\SteamLibrary\steamapps\common\Heroes of Might & Magic Olden Era Demo` is a Mono build with managed assemblies under `HeroesOE_Data\Managed`.
- `Hex.dll` is readable managed code/metadata and contains high-value semantic anchors missing from the current obfuscated/deobf workflow.
- A reusable metadata index was generated at `tmp\mono_demo_battle_semantic_index.txt` with 20,416 battle/law/resource/reward/magic semantic rows.
- Strong discovered anchors include `Hex.Session.Battle.BattleLogicEvents`, `BattleEventArgs`, `BattleEventArgsChecker`, `BattleEventManager`, `BattleAi`, `BattleInput`, `Affect`, `Ability`, `BattleCompletionUtility`, battle-log message classes, `Hex.Events.EaBattleSimulateStarted`, battle-result events, and `Hex.CustomBattle.BhSessionCustomBattle` with `GenTransferBattle`, `FillTransferBattle`, `StartBattle`, and `BtnStartBattle`.
- This does not prove those exact names or APIs still exist in the current Golden Era build. It does provide a much stronger semantic map for finding equivalent obfuscated/current surfaces and for designing a native law validation harness.

## 2026-06-20 Mono-to-current shape/xref matching pass

Status: static-candidate-improved; current-runtime proof still required.

- Generated focused Mono fingerprints at `tmp\mono_demo_critical_battle_fingerprints.json` for critical demo types: `BattleLogicEvents`, `BattleEventArgs`, `BattleEventArgsChecker`, `BattleEventManager`, `Affect`, `Ability`, `AttackStep`, `BattleAi`, `BattleInput`, `BattleCompletionUtility`, `BhSessionCustomBattle`, `Loader`, and `BhUnitTest`.
- Current DiffableCs targeted xref matching found `Hex\edb.cs` as the current battle-event-hub candidate: it has the same large family of `object, BattleEventArgs` dispatch methods and event subscription helpers matching the demo `BattleLogicEvents` shape.
- Current `Hex\dxy.cs` is the current ability/cast/cooldown candidate cluster matching the demo `Ability` shape: methods include cooldown-like setters/incrementers, cast methods, `ChangeAbilityEventArgs` producers, charges, and validity checks.
- Current `Hex\dbg.cs` is a high-value transfer-battle/session setup helper candidate: it contains many `TransferBattle` and `TransferSide` methods and public static entrypoints, matching the demo custom-battle/test setup architecture.
- Current `BhUnitTest.cs` still exists and contains obfuscated equivalents of demo `GenTransferBattle` and `FillTransferBattle`, returning `TransferBattle` and `TransferSide`. This is the strongest current-build lead for a deterministic native battle setup harness.
- This pass improves candidate matching accuracy by using collective shape/xref rather than isolated names. It does not yet prove exact event ordinal mapping, battle setup safety, or law outcome correctness.
