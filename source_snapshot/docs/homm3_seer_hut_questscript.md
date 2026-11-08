# HoMM3 Seer's Hut QuestScript Contract

Status: **active operational contract**. User-visible gameplay proven on Steadwick's Liberation (offer / interim / exchange). Broader campaign rollout is generated/deployed when rewalk+emit+install succeed; per-mission runtime remains unproven until exercised.

Owner module: `experiments/campaign_port_poc/seer_hut_quest.py`  
Campaign bind: `experiments/campaign_port_poc/seer_hut_campaign_bind.py`  
Gate: `tools/validate_seer_hut_quest_contract.py`

## Delivery Shape

The hut is **locally eventless by construction**:

- Emitter adds `propEntities` + `propActivations` only (no `propActionsBefore` / `propActionsAfter`).
- Offer, interim, and exchange live as global QuestScript in map chunk 3.
- Adjacent alignment `.json` keeps `"quests": []` for those hosts so QuestScript is not registered twice.
- `homm3_seer_hut` ObjectConfig + nonempty no-op event bank (`MovePointsAdditionReward 0`, Invisible) make the host clickable; QuestScript owns dialog and rewards.

`ObjectInteractionBefore` matches **`propEntities.sid`** (`PropertyEntity.sid`), not `objects[].sid` / event-bank `sidConfig`. Decomp: `ConInteractQuestObjectBefore`.

## Confirmed FSM (do not regress)

OE QuestScript conditions are **event latches**, not state polls. ANDing different event families in one trigger deadlocks (a lone Done deactivates that listener until the whole AND completes).

Never AND `ObjectInteractionBefore` with `Counter`, `ItemOwnSide`, `ResCounter`, `UnitOwnSide`, or `CounterEqualityInDays` in the same trigger.

Use four SubQuest stages (vanilla `SubQuestActivate` / `SubQuestDeactivate`; `SubQuestDone` alone does **not** stop listening):

| Stage SID suffix | `activeOnStart` | Trigger condition family | Actions |
| --- | --- | --- | --- |
| `_offer` | true | `ObjectInteractionBefore` only | first dialog; deactivate offer; activate incomplete + ready |
| `_incomplete` | false | `ObjectInteractionBefore` only (`repeat: true`) | interim dialog |
| `_ready` | false | mission-complete event(s) only (`ItemOwnSide` / `HeroKill` / `SquadKill` / `ResCounter` / `UnitOwnSide`) | deactivate incomplete + ready; activate complete |
| `_complete` | false | `ObjectInteractionBefore` only | consume requirements; grant reward; completed dialog; deactivate complete |

v1 mission types: 3 defeat hero, 4 defeat stack, 5 bring artifacts, 6 bring creatures, 7 bring resources.  
v1 reward types: **0 none** (intentional empty prize — wiki: Target 12 Griffins; Here There Be Pirates resource sink), 1 XP, **2 mana** (`SeerRewardManaRestore` → `ChangeManaHero`, full refill), **3 morale** (`SeerRewardHeroBuffDays` → `AddBuffHeroDays` with stock `campaign_morale_buff`, days=999 = stock permanent marker), 5 resource, 6 primary skill (`GiveStatsHero`), 7 secondary skill, 8 artifact, 9 spell (`AddSpellHero` via `h3_spell_to_oe_magic`), 10 creatures.  
Unsupported types fail closed (no silent omit) **unless a hand-crafted substitute is registered** (next section). Mission type 0 empty huts are skipped (no quest).

## Substitutes For Unportable Quests

Owner registry: `experiments/campaign_port_poc/seer_hut_substitutes.py` (per-hut `original` / `rationale` / substitute payloads / hand-written dialog — read it before touching any entry).

Some H3 Seer hut quests cannot port natively and used to fail closed, deleting campaign content:

- mission type 1 (reach level N) — no OE hero-level condition
- mission type 2 (primary skill ≥ N) — `ECondition.HeroStat` exists in the Golden Era pin but its event/latch wiring is not statically proven enough to ship
- mission type 8 (must be hero X) — no identity condition
- mission types 3/4 whose H3 target was never bound to an OE entity SID during the port walk
- fetch missions / rewards referencing unported H3 artifacts, spells, or creatures (e.g. all five SoD combo artifacts on *The Fall of Sandro*)

Each blocked hut gets **one** hand-written substitute keyed by `(mission_id, seer sourceKey)`. Design rules (enforced by tests): substitutes use only proven single-event conditions (`ResCounter` / `UnitOwnSide` / `ItemOwnSide`), must be achievable on their map, and replace all three dialog slots with text that describes the substitute, not the original. Level gates become gold donations scaled to the level; mana and morale rewards no longer need substitutes (native actions above); unmapped spell rewards move to a mechanics-mapped OE spell of the same family.

**Stale-substitute guard (fail-closed):** if a registry entry exists for a quest the native path can now compile (e.g. after a new artifact/spell gets ported), `plan_from_seer_entity` raises instead of silently applying the substitute. When you add native support for an H3 type, delete the shadowed registry entry. Tests: `SeerHutSubstituteTests` in `tests/test_seer_hut_quest.py`, including `test_registry_entries_match_decode_contract` which replays every entry against its real port-manifest record.

**Chain Lightning is mapped.** H3 spell 19 maps to `primal_12_magic_chain_lightning` — the literal same OE spell (chains to a second stack within 3 hexes at 0.5 damage per jump; `DB/magics/battle_primal_magics.json`). Do not substitute around it. Still unmapped (substitute required): counterstrike (58), inferno (22), fly (6).

## Campaign Apply Path

All 20 StoryHub hubs install from `tools/install_roe_castle_continuity_weave.py` (`HUB_INSTALL_KEYS_PLAY_ORDER`). Seer-bearing maps come from:

- `scenarios/roe_castle_campaign/batch_manifest.json`
- `scenarios/roe_remaining_campaigns/batch_manifest.json`
- `scenarios/ab_sod_campaigns/batch_manifest.json`

Stale `object_walk` / `object_port_manifest` rows often keep `missionType` but drop artifact/creature/resource payloads. Always rewalk before emit when Seer compile fails with “no artifact ids” / empty stacks. Emit recompiles QuestScript from the placement entity list plus story ``questPayload`` (raw H3 quest retained at alignment time). Do not skip alignment refresh after a rewalk.

```text
walk_campaign_objects → build_campaign_object_port_manifest
  → build_campaign_raw_translation_batch  (refreshes alignment by default)
  → install_roe_castle_continuity_weave (--hub … or all; prefer --skip-regenerate after emit)
```

Batch helper: `tools/apply_seer_hut_quest_campaign_rollout.py` (`--seer-missions-only` skips maps whose port manifest has zero Seer huts).

Rollout report: `artifacts/campaign_port_poc/seer_hut_quest_rollout_all_hubs.json` (plus retry). Emitted maps carry a `questSubstitution` note on the story quest row when a substitute was applied, so generated payloads explain themselves. Remaining failures after the substitute rollout are listed in the report, not silently omitted.

## Proof Labels

| Claim | Tier |
| --- | --- |
| Stage FSM compile shape | source/static + unit tests + `validate_seer_hut_quest_contract` |
| Steadwick offer / interim / exchange | user-visible gameplay proven |
| Other campaign maps after rollout | generated / deployed when install succeeds; runtime unproven until tested |
| Identity `propEntity.sid` match | source/static (decomp) + Steadwick Player.log visit path |

## Related

- Silent-miss row in `docs/agent_surface_guide.md` (QuestScript AND of different event families).
- ObjectConfig / event-bank shell: `seer_hut_quest.homm3_seer_hut_object_row` / `homm3_seer_hut_event_bank_doc` (also wired through map-load preflight).
