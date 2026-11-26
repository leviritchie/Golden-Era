# Factory law build (2026-11-21)

Data: `custom_factions/law_overrides/homm3_factory.json`. It holds `lawOverrides` (all 34 indices), `lawTree` and `lawRules`. `lawBuffs` is empty.

`custom_factions/homm3_factory.json:678`: `factionSkillName` is now "Logistics Network".

## Tree

Costs by rank are 20 / 28 / 38 / 31 / 27, 144 in total.

| Rank | Kingdom | Army |
|---|---|---|
| r0 | 3 Riches, 7 Surveyors' Charter, 2 Prospectors, 8 Smelting Works | 4 Elite Halflings, 10 Elite Mechanics |
| r1 | 1 Tax Collectors, 14 Mining: Crystals, 5 Telegraph Lines | 11 Elite Armadillos, 17 Elite Automatons, 9 Riveted Plating |
| r2 | 16 Riches, 12 Standard Parts, 28 Assembly Lines, 20 Railway Depots | 23 Elite Sandworms, 26 Coordinated Fire, 31 Overpressure Rounds |
| r3 | 32 Insured Plants, 6 Mercenary Pay, 15 Retrofit Bays | 24 Elite Gunslingers, 30 Elite Couatls, 13 Target Designation |
| r4 | 29 Riches, 21 Overclocked Plants, 34 Signal Jammers | 22 Elite Dreadnoughts, 25 Salvage Crews |

- Riches 3/16/29 are first in their kingdom column and set to `{"enabled": false}` in the overrides.
- Unused indices 18, 19, 27 and 33 are `{"enabled": false}`.

## Changes from the draft

- **Signal Jammers (#34) is kept**, as the caller asked. It sits at r4 and costs 4.
- **#15 Retrofit Bays** uses `unitUpgradingDiscount` gold -25%/-50% with `fraction: homm3_factory`, which is Gold only. It sits in the r3 kingdom column, like vanilla demon_20, now that the validator classes `unitUpgradingDiscount` as kingdom.
- **#22 Elite Dreadnoughts** uses the effect icon `nature_17`, not a portrait. The Dreadnought line is not in the manifest `unitLines`, so a portrait icon fails validation. Cost 3/2/1.
- **#25 Salvage Crews** uses a zero `inAllDmgMod` anchor on the six construct SIDs. Cost 4/4.

## Kit rules (`lawRules`)

- 26 Coordinated Fire: `hit_this_round`, 5/10%, capped at 15/30%, all faction creatures.
- 31 Overpressure Rounds: `first_hit`, attacker side, 10/20%, Halfling and Gunslinger lines.
- 13 Target Designation: `damage_vs_buff` on the four Factory marks, 10/20%, all faction creatures.

## Checks

- Local `law_tree_problems`: 0 errors, 0 warnings.
- `collect_law_rules`: passes.

## Plugin levers

New file `OfflineUnlockMod/Homm3FactoryLawHooks.cs`.
- Network laws read the owning player's data side, cached for 1.5 s.
- Salvage reads the law from the winner's transfer side or its logic hero.
- Everything fails closed.

| Law | Where | What it does |
|---|---|---|
| #7 Surveyors' Charter | `Homm3FactoryLogisticsEffects.cs:510` (all three base-level sites in `Solve`), `Homm3FactoryLogisticsInsights.cs:486` | Logistics level = `BaseLogisticsLevel(config, side)` = base + 1. |
| #5 Telegraph Lines | `Homm3FactoryLogisticsFacade.cs:341` | `RemoteLevel` = max(Upgrade Center, Command Center, law level 1/2) for every network building. |
| #12 Standard Parts | `Homm3FactoryLogisticsFacade.cs:324` | `NextCost` takes a further 15/30% off, applied after the Warehouse discount (ceil per resource). |
| #21 Overclocked Plants | `Homm3FactoryLogisticsEffects.cs:434`, `:444`, `:514` | `Network.Overclock` and `MaxLevel`. `EffectiveLevel` = max(built, min(MaxLevel, built + 1)) + Power Station bonus. Power Stations themselves are not overclocked, so the boost does not compound. |
| #32 Insured Plants | `Homm3FactoryLogisticsRuntime.cs:455`, `:561` | On capture the record is kept dormant: housing is restored, the record is not removed and the capture-loss digest is skipped. `ApplyHousing` skips any record whose building another side holds. Pending builds freeze until the side retakes the building. |
| #25 Salvage Crews | `Homm3FactoryLawHooks.ObserveBeforeBattleResult` | After a battle the side wins, floor(lost x 20/40%) of each fallen Automaton or Dreadnought-line stack goes back into the result transfer side. It refills the surviving stack, or adds a new stack through `TransferSide.AddSpawnedUnit` and then sorts. Runs once per battle key. **It needs the dispatch line in shared-file ask 2.** |

## Family indices reused for new effects

Retire the old profiles for **13** (the counter doctrine row), **15, 21, 22 and 25**. Indices 2, 6, 28 and 34 keep their family shape.

## Shared-file asks

1. Done already: `DORMANT_LAW_OVERRIDE_SIDS_OUTSIDE_LAW_LINES` is empty, and #20 and #31 are in the tree.
2. In `Homm3RuntimeMechanicHooks.cs`, in the shared battle-result prefix (about line 1088), add `Homm3FactoryLawHooks.ObserveBeforeBattleResult(__0);` after `Homm3RampartAvengerStrikeRuntime.ObserveBeforeBattleResult(__0);` and before `Homm3BattleUnitLawOwnerRegistry.Clear(...)`.
3. Done already: `unitUpgradingDiscount` is in `_KINGDOM_BONUS_TYPES`, and Retrofit Bays is now in the kingdom column.
4. Retire the family profiles for 13, 15, 21, 22 and 25. For 13, also take the Factory row out of `Homm3CounterattackDoctrineMutationRuntime`.
5. Translate the new law names and texts for 5, 7, 12, 13, 15, 21, 22, 25 and 32.

## Not built, or limits

- Salvage Crews only covers the winning side's own losses in the battle that just ended. It does not touch garrisons that are not in the transfer side.
- Insured Plants keeps a captured building's records forever. They come back to life when the side retakes it; nothing expires them.
