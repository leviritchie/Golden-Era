# Golden Era Campaign Event Translation Review Handoff

Date: 2026-07-15

Status: review complete. Milestone 1 (EventIR census) and milestone 2 (static backends) are in-tree. Emit now compiles zero-based sides, exact propSquads, CounterEqualityInDays recurrence, town grants, Guardhouse persistent-host binding, and SquadInteraction/SquadKill phases. Delivery readiness remains fail-closed until runtime proof.

## Milestone Progress

Landed (source/static + generated-artifact):

- `experiments/campaign_port_poc/campaign_event_ir/` — IR model, census, audience encoders, backend compilers
- Emit: zero-based `propActions.sides`, no `computerActivate`, exact `propSquads.unitProps`, avalanche `repeat`/`isDelete` independence, Guardhouse persistent host without DeleteEntity, StartTurn+`CounterEqualityInDays` recurrence, Terraneus town grants, SquadInteraction→Dialog + SquadKill→GiveRes
- Validators: `validate_campaign_event_ir_census.py`, updated `validate_campaign_event_policy_contract.py`

```powershell
python tools/validate_campaign_event_ir_census.py --repo-root . --census-only
# PASS: complete IR inventory + field fidelity

python tools/validate_campaign_event_policy_contract.py --repo-root .
# PASS: source/static + generated shape for new backends

python tools/validate_campaign_event_ir_census.py --repo-root .
# FAIL: delivery readiness (expected until runtime proof)
```

Next: focused runtime matrix from the acceptance table (Griffin wood day 125, avalanche re-fire, guarded pre-battle dialog, Guardhouse dwelling, Terraneus weekly wood). Use the Event Runtime Probe map for fast iteration instead of full campaign missions.

## Scope And Proof Boundary

This review covers the current `raw_translation` path for all seven RoE Castle campaign missions. It follows global timed events, map EVENT objects, and town events from live H3C decode through alignment, map properties, QuestScript, Core dialogs, validators, and the continuity installer. The current dirty worktree and generated artifacts were authoritative for translated output; the active Golden Era install supplied presumed-stock vanilla specimens only; current Cpp2IL output supplied static schema evidence.

These are source/static and generated-artifact findings. No event behavior was exercised in gameplay and installed event/Core readback was not performed. The current validator pass is not runtime or delivery proof.

## Executive Conclusion

The decoder is substantially stronger than the emitter. It already preserves schedule, player mask, human/computer eligibility, message, exact guards, rewards, removal, and town attachment. The delivery pipeline then loses or rewrites several of those fields.

The current output is not event-equivalent to the H3 campaign:

1. Griffin Cliff's recurring wood grant silently stops after day 120.
2. Homecoming's weekly Terraneus town event is decoded and then omitted.
3. Unguarded map-event `sides` values are one-based although the native property is zero-based; `computerActivate` is an unsupported property; guarded events drop audience fields entirely.
4. The non-removing Griffin avalanche is emitted non-repeating while its marker persists. This conflicts with source lifetime and is likely to leave an inert marker, but that runtime consequence is unproven.
5. Guarded messages move from before combat to after victory, while exact H3 stacks become budget-generated squads.
6. Homecoming's Guardhouse binding is skipped. A one-line type fix could then delete the persistent dwelling host.

`Campaign event policy contract PASS` proves live global-event count/partition checks plus the current generated shape. It does not prove field equivalence.

## Current Pipeline

1. `h3c_mission_source.py` loads the campaign mission.
2. `h3m_object_walk.py` decodes map EVENT payloads and town events; `h3m_global_events.py` decodes the post-object timed-event table.
3. `build_homecoming_object_port_manifest.py` preserves map-event trigger fields. Town events remain nested in town state.
4. `build_campaign_alignment.py` delegates story construction to `campaign_runtime_script.py`.
5. `approach_cell/surface_emit.py` emits properties. `raw_translation/build_raw_translation_map.py` converts unguarded events to type-1 invisible markers and guarded events to physical `random-squad` hosts.
6. `campaign_runtime_script.py` emits QuestScript and Core dialogs.
7. `validate_campaign_event_policy_contract.py` compares live decode, alignment, and generated maps. The continuity installer does not run it.

Current runtime shapes:

- Briefing: same-day dialogs under one `StartTurn("1", day)` trigger.
- Timed resource: one non-repeating `StartTurn(side, day)` per selected side and expanded occurrence through day 120.
- Unguarded EVENT: type-1 marker, before-interaction Dialog, optional deletion, and `ObjectInteractionAfter` QuestScript for reward/state.
- Guarded EVENT: `random-squad` plus `SquadKill -> Dialog/reward/state/delete`.
- Town event: no emitted runtime form.
- Dialog body: generated Core overlay; map chunk 2 remains empty.

## Campaign Census

| Mission | Global timed | Briefings | Timed grants | Map events | Town events |
| --- | ---: | ---: | ---: | ---: | ---: |
| Homecoming | 7 | 7 | 0 | 1 | 1 |
| Guardian Angels | 2 | 2 | 0 | 0 | 0 |
| Griffin Cliff | 4 | 3 | 1 | 3 | 0 |
| Steadwick's Liberation | 4 | 4 | 0 | 0 | 0 |
| Deal With the Devil | 4 | 4 | 0 | 2 | 0 |
| Neutral Affairs | 4 | 4 | 0 | 0 | 0 |
| Tunnels and Troglodytes | 4 | 4 | 0 | 0 | 0 |

Map-event risk matrix:

| Mission/source | Guards | Mask | AI activates | Remove | Main loss |
| --- | --- | ---: | --- | --- | --- |
| Homecoming `0:18:35` | no | 255 | yes | yes | Guardhouse binding skipped |
| Griffin `0:29:8` | no | 235 | no | no | wrong `sides`; forced one-shot |
| Griffin `0:46:23`, `0:25:23` | yes | 235 | no | yes | audience, phase, and exact stacks lost |
| Deal `0:14:24`, `0:17:29` | yes | 251 | no | yes | audience, phase, and exact stacks lost |

The only global resource event is Griffin's `Bonus wood`: 10 wood on day 5 and every 5 days thereafter for mask 250. For Homecoming's only town event, Terraneus `Computer Timber Supplies`, the current decoder reports 14 wood, first occurrence 0, recurrence 7, mask 254, `humanAffected=true`, and `computerAffected=false`. The RoE layout supplies the human flag implicitly, so verify that decoder interpretation before treating it as canonical audience semantics.

## Vanilla Golden Era Comparison

The comparison set came from the active install under:

`V:/SteamLibrary/steamapps/common/Heroes of Might and Magic Olden Era - Golden Era/HeroesOldenEra_Data/StreamingAssets/maps`

Thirty-three presumed-stock active-install maps, selected by excluding generated prefixes, were read with `read_olden_map_container()` from `port_homecoming_poc.py`. These are structural examples, not runtime proof; record hashes and provenance in the proposed fixture.

### Audience And AI Policy

Across their 438 `propActionsBefore/After` rows, every row has `type`, `id`, `repeat`, `sides`, and `actions`. No row contains `computerActivate`.

`propActions*.sides` is zero-based:

- `Glittering_Strait.map` uses `sides: "0"` for a P1 dialog.
- `Thirst_for_Power.map` uses `0`, `1`, and `2` for P1/P2/P3-specific state and dialog.

By contrast, tutorial `t_C5.map` contains `StartTurn ["1", "1"]` followed by resource grants in a one-player tutorial. This is consistent with first-side/day-one use, but the parameter meaning remains inferred. Side encoding is opcode-specific; one universal mask converter is unsafe.

The strongest vanilla candidate for AI policy is separate: `propAiIntetactions` has `type`, `id`, and `aiIgnore`. c_M3 narrative squads `graverobber`, `spy`, and `colonel` use `aiIgnore:true`; runtime exclusion behavior is not proven.

### Marker Lifetime Versus Repeat

Vanilla keeps physical deletion and callback recurrence independent:

- `c_M2.map` marker 45: `isDelete:false`, `repeat:true`.
- `c_M2.map` marker 53: `isDelete:true`, `repeat:false`.
- `c_M1.map` marker 21: `isDelete:false`, `repeat:false`.
- `c_M10.map` marker 0: `isDelete:true`, `repeat:true`.

H3 `removeAfterVisit` and Olden callback recurrence must therefore remain separate translation fields.

### Exact Guards And Encounter Phases

The presumed-stock comparison maps use `propSquads.unitProps` for exact rosters:

- `c_M2.map` squads 7801-7803 contain exact qilin stacks, including 4/4/4 variants.
- `c_M5.map` object 5170 contains exact black dragon counts 7/3/3.
- `c_M3.map` object 9872 contains exactly five inquisitors.

`propRandomSquads` represents encounters as template/value budgets. Exact H3 creature/count guards should not be converted to budgets.

The comparison maps contain `SquadInteraction` rows for interaction-time Dialog/attack actions and `SquadKill` rows for completion actions. `Glittering_Strait.map` also has a neutral narrative squad with direct before/after dialogs and `aiIgnore:true`. These are candidate phase bindings; callback order, retreat/loss behavior, and re-fire behavior require focused runtime proof.

H3 shows a guarded EVENT message before starting combat. VCMI's `CGEvent` independently confirms audience checking, pre-combat message, battle start, and removal behavior: https://github.com/vcmi/vcmi/blob/a6f90334014d233f16d400c379bedf84a08002a6/lib/mapObjects/CGPandoraBox.cpp#L264-L338

### Timed Resources And Dialogs

- `t_C5.map`: `StartTurn -> GiveRes`.
- `c_M5.map`: difficulty-gated `StartWeek` grants.
- `c_M9.map`: `repeat:true` timing with `StartWeek`, plus repeatable `CounterEqualityInDays` logic.

This proves a recurrence-shaped authoring pattern and supporting schema, not runtime recurrence semantics or an exact five-day implementation. H3 `nextOccurrence == 0` means one-time; a nonzero value recurs at that interval: https://github.com/vcmi/vcmi/blob/a6f90334014d233f16d400c379bedf84a08002a6/lib/mapping/CMapEvent.h#L20-L41

Representative vanilla map actions reference Dialog SIDs that resolve to Core-backed documents, such as c_M1's `M1Q1_dial1`. This review did not establish exhaustive stock resolution. The translator's split is native-friendly, but every generated and installed SID/content pair must be validated.

### Static Schema Corroboration

Current DiffableCs independently shows:

- `PropActionsBase`: `repeat`, `sides`, `actions`; no `computerActivate`.
- `PropAiIntetaction`: `aiIgnore`.
- `PropMarker`: `isDelete`, `isActivate`.
- `PropSquad.unitProps` and `UnitProp.sid/count`.
- `ESharing`: `Clone`, `Shared`, `Ai`, `Side0` through `Side7`, `All`.
- Conditions include `StartTurn`, object interaction, squad interaction/kill, `CounterEqualityInDays`, `AnyStartTurn`, and `StartWeek`.

Only `Clone`, `Ai`, and `All` appeared in the comparison census. `SideN` exists in the API surface but has no example here; do not depend on it before runtime proof.

## Prioritized Findings

### P0: Audience Semantics Are Invalid

`surface_emit.h3_players_mask_to_sides()` adds one to each H3 bit. Griffin's avalanche therefore receives a one-based list, including invalid side 8, for a zero-based native field. The same row emits unsupported `computerActivate`. Guarded events emit neither the mask nor `computerActivate=false`; all four current guarded events restrict both.

Recommendations:

- Normalize audience as zero-based H3 identities plus human/computer eligibility.
- Add separate proven encoders for map-action `sides`, `StartTurn`, and Quest sharing.
- Treat `aiIgnore:true` as the strongest vanilla-backed candidate for narrative squads, then runtime-prove that it prevents AI consumption.
- Prove acting-side scope for guarded interaction/kill. Diagnostic output may expose unresolved mappings, but build/deploy readiness must fail until the full source audience is enforced.

### P0: Recurrence Is Silently Truncated

`EVENT_RECURRENCE_DAY_CAP=120` is not a proven mission horizon. The helper claims fail-closed behavior but returns a truncated list. Griffin emits days 5 through 120 and loses day 125 onward. The validator calls the same helper and accepts 144 triggers.

Replace expansion with one native repeatable implementation. First prove an exact five-day cadence using the native repeat/counter surface. If it cannot express it, stop and choose direct state management with a persistent next-fire day as the sole backend. Do not ship a finite list or fallback.

### P0: A Live Town Event Is Dropped

Terraneus's weekly +14 wood event is preserved through alignment, then declared `not_in_scope_for_current_batch`. The validator never inventories town events.

Add town scope and host identity to the event model. Prove an ownership-aware weekly grant before delivery. Diagnostic IR may remain available, but build/deploy readiness for a mission containing this event must fail rather than silently ship incomplete behavior.

### P0: Non-Removing Events Lose Source Lifetime

The Griffin avalanche has `removeAfterVisit=false`, but both property and QuestScript paths force `repeat=false` while the marker persists. This is a proven source-equivalence loss; whether Olden leaves an inert marker at runtime remains unproven.

Preserve event consumption separately from physical host deletion. A disposable marker may use `isDelete`; a persistent rebound host must disable only event behavior, never delete the host.

### P0: Guarded Phase And Army Are Rewritten

Exact H3 stacks become rounded value budgets, and the only generated event Dialog is attached to `SquadKill`. The artifact has no source-equivalent pre-battle Dialog for a loss/retreat attempt, and the army may differ; runtime UI behavior was not tested.

Extract and reproduce the complete vanilla host contract: object/entity linkage, exact `propSquads`, activation, the candidate AI policy, candidate before-interaction dialog, and `SquadKill` completion. Fail closed on unmapped creatures. Runtime-prove callback order, retry behavior, AI exclusion, and one-shot victory rewards before treating this backend as ready.

### P1: Guardhouse Binding Is Skipped And Unsafe To Patch

`landon_access.py` expects `payloadKind=map_event`; the decoder emits `event`. The generated report says `skipped_source_keys_not_guardhouse`, so a separate invisible zone is emitted.

Changing only that condition is unsafe: the rebinder moves `propActionsAfter`, whose `DeleteEntity` could then target the persistent dwelling. Model `eventSid`, `hostSid`, event lifetime, and host lifetime separately. Make the binding declarative by source identity.

### P1: Silent Briefing Fallbacks Violate The Contract

If no decoded briefing segments exist, the builder silently uses synthetic RoE records and then H3C prose while reporting `silentFallbacksUsed:false`. It is inactive for these seven missions but can fabricate future output.

Remove it. Missing/unsupported timed-event decode must fail with the source identity.

### P1: Validation Proves Shape, Not Equivalence

The current validator:

- compares pinned counts, not source fields;
- derives recurrence expectations from the emitter helper;
- requires the rewritten guarded `SquadKill -> Dialog` shape;
- flattens conditions/actions across triggers;
- keys marker lookup by `id`, not `(type,id)`;
- ignores audience, AI policy, exact stacks, repeat, phase, exact rewards, and town events;
- does not verify generated/installed Core dialogs;
- is not invoked by the continuity installer.

The shared event validator passes while the Homecoming raw contract fails: placement marks source event `0:18:35` as missing because it does not recognize the type-1 marker/native-host representation. The Homecoming validator checks `guardhouseMarker`, not `guardhouseDialog`.

### P2: Latent Payloads Can Disappear

Empty-message map events lose their QuestScript and Core entry even if they carry rewards. Non-resource reward classes are decoded but have no complete capability matrix.

Validate effects independently of message presence. Every decoded effect must have one named backend or a source-specific failure.

## Recommended Architecture

Introduce one immutable `CampaignEventIR` with:

- source mission/index/key/kind;
- scope: global, map, or town;
- host: disposable marker, exact squad, persistent object/town, or none;
- schedule: first day, interval, one-time/repeating;
- audience: zero-based players plus controller eligibility;
- phases: before/after interaction, battle start/win;
- event lifetime separate from host deletion;
- exact guard stacks and battle policy;
- exact effects/rewards;
- dialog identity and presentation phase;
- one selected backend, never a fallback chain.

Compile each class once:

1. Briefing: `StartTurn` plus Core Dialog with audience-derived parameters.
2. Repeating resource: one proven native/direct-state recurrence, not expansion.
3. Unguarded EVENT: marker or explicit persistent host for interaction; QuestScript only for effects/state not supported by direct actions.
4. Guarded EVENT: one complete host contract covering object/entity linkage, exact `propSquads`, activation, AI policy, interaction dialog, and `SquadKill` completion, with unproven behavior kept fail-closed.
5. Town event: ownership-aware recurrence attached to the emitted town identity.

Mission-specific host bindings belong in a declarative profile/manifest and must resolve exactly one source event and one emitted host. Do not keep coordinate-specific behavior in the shared compiler.

## Implementation Order

1. Add EventIR and a field-for-field source-to-IR census. Fail closed on town events, unbounded recurrence, unsupported rewards, or unresolved audience backends.
2. Add opcode-specific audience encoders; remove `computerActivate`; reproduce the full exact-squad host pattern and runtime-prove its AI/phase policy.
3. Implement one exact Griffin recurrence and one ownership-aware Terraneus recurrence. Do not permit build/deploy readiness or installation of affected missions until both live source events are represented.
4. Correct event repeat/host lifetime and replace the Guardhouse rebinder.
5. Rebuild validation around canonical event tuples; wire the cheap contract into generation/install and keep live H3C comparison as the heavier audit.
6. Perform generated, installed, startup, and runtime proof before updating readiness documentation.

## Required Validation

Cheap always-on checks:

- no decoded event absent from IR;
- only native action-property keys;
- opcode-specific side bases;
- all references keyed by `(type,id)`;
- exact linkage for translator-owned marker/entity/action rows, with `markersFreeId` greater than every referenced type-1 ID; do not require global max+1 equality or reject unrelated stock ghost IDs;
- exact H3 stacks equal emitted `unitProps` after SID mapping;
- exact conditions, ordered actions, repeat, sharing, and parameters in one trigger;
- every Dialog SID resolves to exact generated Core content;
- no finite cap, alternate source, empty-message loss, or fallback;
- placement accepts the IR-declared marker/rebound host representation.

Heavy audit:

Compare live H3C -> EventIR -> generated map/QuestScript -> generated Core -> installed Story map/Core for source identity, text hash/phase, schedule, audience, repeat/removal, host lifetime, exact guards, exact rewards, town attachment, and all references. Expected values must be derived independently from source records, not emitter helpers.

## Focused Acceptance Matrix

| Case | Required proof |
| --- | --- |
| Griffin wood | Eligible side gets 10 wood on days 5, 10, and 125; wrong side/controller does not |
| Griffin avalanche | Correct human can trigger repeatedly; AI/excluded sides cannot consume it |
| Guarded Griffin/Deal | Exact roster; dialog before each attempt; no reward on loss; 1500 gold once on win |
| Homecoming Guardhouse | Intended interaction hosts one-shot dialog; dwelling remains present/usable |
| Terraneus town | Eligible current owner gets 14 wood on the correct weekly cadence |
| Dialog payload | Generated and installed map SID resolves to exact generated/installed Core text |

Use the live bridge/runtime-proof order. Do not play 125 turns manually; use a focused late-day state or the Event Runtime Probe map below.

## Event Runtime Probe Map

Compact **32×32 grass lab** (`h3_event_runtime_probe`). Thirst is only a 4-chunk schema donor — terrain/objects/quests are discarded. Olden **+Y = north**; stations are north of town.

| Station | What it exercises |
| --- | --- |
| INFO / ONE-SHOT / AVALANCHE (gold FX) | Checklist; one-shot delete; repeating non-deleting host |
| GUARDED (1× `h3_pikeman`) | Exact `propSquads.unitProps`; `SquadInteraction` dialog; `SquadKill` +1500 gold. Campaign SID — GE already has Core.zip h3 logics + `homm3_bundles` |
| PERSISTENT (silver FX) | One-shot dialog; host object must remain (Guardhouse stand-in) |
| Timed grants | Day-1 +5 wood; Griffin-like +10 (day 2, then every 5); fast +1 crystal every 2; town-shaped +14 wood (day 1, then every 7) |

```powershell
python tools\validate_event_runtime_probe_map_contract.py --repo-root .
# PASS: generated-artifact shape only

python tools\install_event_runtime_probe_map.py --repo-root .
# installs under StreamingAssets/maps/ + merges Core overlay (not Story_maps)

# Optional MSBuild: -p:DeployEventRuntimeProbeMap=true
```

Proof boundary: generated/installed payload only until a focused runtime session records the acceptance matrix. Late-day (125) checks still belong on live bridge / save edit, not 125 manual turns.

## Reusable Evidence Package

Current commands/results:

```powershell
python tools\validate_campaign_event_policy_contract.py --repo-root .
# PASS: source/static decode plus generated shape only

python tools\validate_homecoming_raw_translation_map_contract.py `
  --repo-root . --skip-generate --skip-installed-dual-check
# FAIL: translated event marker is counted as missing_from_emit
```

Key implementation/evidence files:

- `experiments/campaign_port_poc/campaign_runtime_script.py`
- `experiments/campaign_port_poc/approach_cell/surface_emit.py`
- `experiments/campaign_port_poc/raw_translation/build_raw_translation_map.py`
- `experiments/campaign_port_poc/raw_translation/landon_access.py`
- `tools/validate_campaign_event_policy_contract.py`
- `tools/validate_homecoming_raw_translation_map_contract.py`
- `artifacts/campaign_port_poc/homecoming_poc/raw_translation_map/raw_translation_report.json`
- `artifacts/campaign_port_poc/homecoming_poc/raw_translation_map/homecoming.raw_translation_placement_ground_truth.json`

Vanilla specimens:

- `Story_maps/c_M2.map`: marker repeat/deletion independence; exact squads.
- `Story_maps/c_M3.map`: exact guards and AI-ignored narrative squads.
- `Story_maps/c_M5.map`: interaction/kill phase separation and exact dragons.
- `Story_maps/c_M9.map`: repeatable timing.
- `Story_maps/t_C5.map`: `StartTurn -> GiveRes`.
- `Glittering_Strait.map`, `Thirst_for_Power.map`: zero-based action `sides`.

Before implementation, extract a small normalized fixture of these structural rows plus source map hashes and provenance. Do not copy whole installed maps.

Decomp package root:

`tmp/cpp2il_experiment/out_dev_diffable_cs/DiffableCs`

Relevant files: `Hex/Hex/Map/PropActionsBase.cs`, `PropAiIntetaction.cs`, `PropMarker.cs`, `PropSquad.cs`, `UnitProp.cs`, and `Hex/Hex/QuestScript/ESharing.cs`, `ECondition.cs`, `EAction.cs`.

`Hex.Map.Map.ohv(PropActionsBase a)` appears in `Hex/Hex/Map/Map.cs`, but its readable body is empty and the expected ISIL file is absent. The attempted method dossier could not prove runtime parsing/order. Field layout plus repeated comparison-map shapes are proven static. `SideN` behavior, `aiIgnore` semantics, type-1 AI interaction, exact five-day cadence, and property execution order still require native disassembly or focused runtime proof.

## Handoff State

Milestones 1–2 (EventIR census + static backend emit) are in-tree. The Event Runtime Probe map builder/validator/installer is in-tree for acceptance-matrix iteration (`validate_event_runtime_probe_map_contract.py` PASS = generated shape only). Treat `validate_campaign_event_ir_census.py --census-only` as inventory, `validate_campaign_event_policy_contract.py` as generated-shape, and default IR census (no flag) as delivery-readiness fail-closed. Runtime proof of the acceptance matrix is the next gate before readiness docs may claim delivered event behavior.
