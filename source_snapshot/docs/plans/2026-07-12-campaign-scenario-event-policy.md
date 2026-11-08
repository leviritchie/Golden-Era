# Campaign Scenario Event Policy

Date: 2026-07-12, corrected 2026-07-15 (EventIR static backends).

Status: shared policy covers all seven RoE Castle batch missions (Good1 blocks 1–3 and Good2 blocks 1–4). Source/generated validators pin timed briefings, QuestScript `GiveRes` for computer/resource timed grants (StartTurn first-fire + `CounterEqualityInDays` recurrence, no day-cap expansion), unguarded map-event Dialog + visit `GiveRes`, guarded exact `propSquads` with `propActionsBefore` Dialog + `SquadKill` `GiveRes`, and town-event recurring grants. Runtime cadence, audience, AI exclusion, guarded phase order, and town ownership remain user-unvalidated.

## Policy

| H3M source | Olden treatment |
| --- | --- |
| Player-only global timed event with message | QuestScript `StartTurn` briefing on `firstOccurrence + 1` |
| Computer-affected and/or resource timed event | QuestScript `StartTurn` first fire + `CounterEqualityInDays` recurrence per `playersMask` side; no finite day-cap expansion |
| Unguarded map event | `propActionsBefore` Dialog with zero-based `sides` + LocKit SIDs; resource `GiveRes` on `ObjectInteractionAfter`; `repeat` independent of `isDelete` |
| Guarded map event | exact `propSquads.unitProps` + `propActionsBefore` Dialog (interrupting) + `SquadKill` → `GiveRes` |
| Non-resource map-event / timed rewards | fail closed |
| Synthetic campaign briefing tail / H3C briefing text | forbidden; missing global timed briefings fail closed |
| Town events | QuestScript recurring `GiveRes` against featured-city entity SID (ownership filter runtime-unproven) |

Dialog titles use the scenario display name, never a hardcoded Homecoming title.

`CampaignEventIR` (`experiments/campaign_port_poc/campaign_event_ir/`) inventories every decoded event before emit. Delivery readiness stays fail-closed until runtime proof.

## Root Cause And Static Boundary

The walker learned to stop at a clean post-object global-timed-event table instead of absorbing that table as synthetic briefing objects. That parser behavior is source/static logic, not runtime dialog proof.

`ValidateCampaignEventPolicyContract` pins all manifest missions at source/generated proof only. `ValidateCampaignEventIrCensus` pins the IR inventory (`--census-only`) and refuses delivery readiness until backends are proven.

## Batch Snapshot

| Mission | Timed events | Player briefings | Deferred computer/resource | Map events | Town events |
| --- | ---: | ---: | ---: | ---: | ---: |
| Homecoming | 7 | 7 | 0 | 1 | 1 |
| Guardian Angels | 2 | 2 | 0 | 0 | 0 |
| Griffin Cliff | 4 | 3 | 1 | 3 | 0 |
| Steadwick's Liberation | 4 | 4 | 0 | 0 | 0 |
| Deal With the Devil | 4 | 4 | 0 | 2 | 0 |
| Neutral Affairs | 4 | 4 | 0 | 0 | 0 |
| Tunnels and Troglodytes | 4 | 4 | 0 | 0 | 0 |

## Residual Gaps

- Runtime presentation of dialogs, `GiveRes` AI-side credit, recurrence cadence, `aiIgnore`, and guarded `propActionsBefore` Dialog / `SquadKill` combat remain user-unvalidated.
- Non-resource rewards (skills/artifacts/spells/creatures/etc.) are refused, not ported.
- Featured-city victory and interactive quest objects remain separate contracts.
- Town ownership filtering for Terraneus weekly wood is emitted but runtime-unproven.

## Validate

```powershell
$env:PYTHONUTF8 = '1'
python tools/validate_h3m_object_walk_campaign_contract.py --repo-root .
python tools/validate_campaign_event_ir_census.py --repo-root . --census-only
python tools/validate_campaign_event_policy_contract.py --repo-root .
```

A passing result establishes source/generated contract coverage only. Runtime event behavior still needs focused gameplay proof.
