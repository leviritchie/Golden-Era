# Decision log: vanilla_stock victory + map events

Scope: stock Olden maps only (`vanilla_stock` + shared `h3m_format` header decode). No Golden Era Story_maps / campaign raw changes.

## Decisions

1. **Header victory/loss decode** lives in `h3m_format.decode_h3m_scenario_header`, VCMI-shaped (AB empty-player skip 6+6, factionsBytes=2, heroesBytes=20). Proven on Dungeon Keeper (`WINSTANDARD`) and Treasure Hunt (`TAKEMINES`, `allow_normal_win=false`).
2. **Template leftovers**: always clear `settings.mapWinConditions`, Thirst quest/counters, and related propEntity/action lists before intentional emit.
3. **WINSTANDARD** → `DefeatAllEnemiesEnabled=true` + Thirst-style `PlayerDefeated` (1-based side ids) → `GameVictory`. Quest name/desc are **inline English**, not Loc SIDs.
4. **TAKEMINES** → Glittering-style `propEntities` (`mine1..N`) + `ObjectCaptureEntity` / `ObjectLose` + `mines_owned` counter → `GameVictory` at `N`. `DefeatAllEnemiesEnabled` follows H3 `allow_normal_win` (false on Treasure Hunt).
5. **Fail-closed** if emitted mine count ≠ source H3M mine/abandoned-mine count. Abandoned mines map to stock `campaign_M2_empty_mine`. Sulfur mines keep existing stock stand-in `alchemy_lab` (no `mine_sulfur` in stock Core).
6. **Map EVENT parity (2026-07-21, host/deco/reward fix 2026-07-22)** matches the campaign Dialog/`GiveRes` contract on stock hosts:
   - Unguarded → invisible stock `Zone 1x1` **markers** + adjacent decorative `fx_quest_mark_gold_01` + type-1 Dialog Before + QuestScript `ObjectInteractionAfter` → GiveRes / RemoveRes / SpawnMapObject.
   - When the source cell is not landable, relocate within same-layer Chebyshev radius; **fail closed** if none. Deco placement fails closed if no adjacent free cell.
   - Guarded → stock `random-squad` + SquadInteraction/SquadKill rewards.
   - Mapped H3 artifacts (exact stock name match, e.g. id 116 → `endless_bag_artifact`) spawn via `SpawnMapObject` on visit. Unmapped artifacts and **mana** stay named omit gaps (no interacting-hero `ChangeManaHero` / `AddMana` donor).
   - Negative resource deltas use stock-proven `RemoveRes` (not a fictional TakeRes).
   - Dialog SIDs use `localization:false` under `optional_core_overlay_for_events/`; emit auto-merges into stock (+ install-target) `Core.zip` via `tools/install_vanilla_stock_event_dialog_overlay.py`.
7. **Global timed events**: H3M tail briefings → StartTurn Dialog; resource grants → StartTurn + CED recurrence with GiveRes/RemoveRes.
8. **Event pilot**: Twins (`expectMapEventCount: 6`) — 3 unguarded / 3 guarded, day-1 Intro briefing, Endless Bag spawn on one event, remaining art/mana gaps explicit.

## Lobby/load regression fix (artifact + installed validated)

The first regenerated pilot maps were not playable scenarios: the emitter forced `isScenario=false`, flattened `meta.spawns` from the required `{playersCount, spawns, takenHeroes}` object into a list, and retained Thirst's dimension-specific `areas`, `keyObjects`, and river nodes. The emitter now preserves the scenario flags and spawn object, uses native empty `playerId` / `colorId=-1` fields with AI `spawnType=1`, preserves the stock `campaignInfo` object, emits one full-map area, clears template key objects, and emits an empty river node list. The vanilla_stock validator fails closed on these contracts.

## Lobby faction/hero choice contract (2026-07-14)

An empty `factionSid` with `isCityDefined=true` is not free choice: it defines
the slot as Random and locks it there. Decompiled `cgd.qmq` converts a scenario
spawn into `SlotModel`; only `isCityDefined=false` and `isHeroDefined=false`
take the editable defaults (`fractionSid="random"`, `heroSid="random"`).
Stock `Story_maps/t_M2.map` supplies the matching map-side shape:
`propCities.isDefined=false`, empty `factionSid`, and `spawnHero=false`.

H3 random/multi-faction players and H3 factions with no stock counterpart now
emit that undefined city+hero contract. A single mappable forced H3 faction
continues to emit a defined stock faction and hero. The validator checks both
the lobby spawn row and its matching `propCities`/`propHeroes` rows.

## Runtime fix (2026-07-23)

Live Twins: timed briefings worked; Zone visits and neutral spawns did not.

Root causes (source/static vs stock live maps):
1. Unguarded Dialog used one-based `sides=\"1..8\"` and illegal `computerActivate` on `propActionsBefore`. Native Zone Dialogs use `sides=\"\"` and no `computerActivate` field (`audience_encode` / c_M10 / Fun_and_Graves).
2. `propRandomSquads.fraction` was float `0.0`; stock SpawnsCreator rows use string `\"\"` (or a faction sid) plus the fuller native field set.

Fix: empty/zero-based sides helper, drop `computerActivate` from prop actions, emit `stock_random_squad_property_row`.

## Neutral strength calibration (2026-07-23)

Stock emit used coarse AVWmon fixed budgets (L1=400…L7=20000) and `count×100` for typed/guards. That underpowered low tiers vs H3 (~4× light on L1) and ignored creature identity on guards.

Homework: campaign GE uses `requestedValue = round_half_up(count_or_nominal × h3_unit.squadValue, 50)` with CRTRAITS-guideline nominals (20/20/15/10/8/7/4). Stock Core has no `h3_` rows, but native stock tier medians sit near GE `h3_` medians.

Decision: bake GE `h3_` tier medians + per-creatureType squadValues into `h3_neutral_strength_model.json` and compute the same formula in `stock_neutral_strength.py`. SpawnsCreator still fills **stock** units; the budget magnitude matches the H3→Olden campaign model. Regenerate with `python -m experiments.campaign_port_poc.vanilla_stock.stock_neutral_strength` when GE Core unit values drift. Runtime fight feel remains unvalidated.
