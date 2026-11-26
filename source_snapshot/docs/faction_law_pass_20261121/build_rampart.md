# Rampart law build (2026-11-21)

Data: `custom_factions/law_overrides/homm3_rampart.json`. It holds `lawOverrides`, `lawTree` and `lawRules`, and needs no `lawBuffs`.

## Tree changes from the draft

- **#17 Wellspring of Life replaces Pegasus Winds** (REVIEW). Healing on friendly creatures is +25%/+50% (`unitStat finalHealingBonusPercent`), cost 3/3.
  - It sits in the **r4 army column**, not the r4 kingdom column REVIEW names. A `unitStat` law counts as an army law in `law_tree_problems`, and the validator rejects it in the kingdom column.
  - The r4 kingdom column is therefore [29, 13].
- **#19 Elven Craftsmanship** is faction-qualified (`"fraction": "homm3_rampart"`, like vanilla demon_20). Its text now reads "Upgrading Rampart creatures costs -15%/-30% Gold."

Costs by rank are 25 / 27 / 29 / 35 / 29.

| Rank | Kingdom | Army |
|---|---|---|
| r0 | 3 Riches I, 2 Ranger Scouts, 5 Wardens' Oath | 4 Elite Centaurs, 8 Elite Dwarves, 7 Unicorn Glade |
| r1 | 1 Tax Collectors, 14 Mining: Crystals, 6 Druidic Lore, 22 Defender's Grace | 10 Elite Wood Elves, 12 Elite Pegasi |
| r2 | 16 Riches II, 15 Druidic Circle, 21 Dwarven Treasury, 20 Treefolk Lumber | 24 Elite Dendroids, 9 Paths of the Glade, 11 Mighty Oaks |
| r3 | 19 Elven Craftsmanship, 32 Sylvan Diplomacy, 25 Mystic Pond | 23 Elite Unicorns, 30 Call of the Grove, 26 Dendroid Watch |
| r4 | 29 Riches III, 13 Elder's Ward | 31 Elite Dragons, 18 Fury of the Glade, 17 Wellspring of Life |

- Riches 3/16/29 are left out of `lawOverrides`.
- 27, 28, 33 and 34 are `{"enabled": false}`.
- Kit rules (`lawRules`):
  - 26 Dendroid Watch: `turn_state`, `stood_ground`, 10/20%, all creatures.
  - 18 Fury of the Glade: `retribution`, 10/20%, all creatures.
- Checks:
  - `collect_law_rules` passes.
  - `law_tree_problems` reports 1 error, #19 in the kingdom column; see shared-file ask 2.

## Plugin levers

New file `OfflineUnlockMod/Homm3RampartLawHooks.cs`.

In `Homm3RampartAvengerStrikeRuntime.cs`:
- `:102`: new `ArmedSide` fields.
- `:355`: the law ranks are read when the side is armed, only if Avenger rank > 0.
- `:418` and `:433`: AttackStep Begin closes the previous step's windows and records the avenging step that is now playing (Wardens' Oath).
- `:482` and `:518`: `NoteAnswered` runs on the attack trigger and the retaliation trigger when the chain struck (Elder's Ward).
- `:743`: `NoteAnswered`.
- `:765`: `internal static int DamagePercent(object caster, object receiver, out string detail)`.
  - Wardens' Oath (#5) adds +10/+20 while the current step is the side's avenging step.
  - Elder's Ward (#13) adds -10/-20 while the current step is the answered enemy step, for that same attacker and target.
- `:821` and `:861`: `RunChain` now returns the struck count.
  - Call of the Grove (#30) adds 1 striker.
  - Paths of the Glade (#9) adds 1 hex of move.
- `:976`: Mighty Oaks (#11) lifts the single-hex gate in `BuildCandidate`.

## Family indices reused for new effects

13, 18, 19, 25, 34 (now dormant), 27 (now dormant) and 33 (now dormant).

In `Homm3CustomLawEffectProfiles.cs`:
- **Retire:**
  - the row-13 "avenger-marked-counterattack-damage" profile;
  - the morale trigger at 25;
  - the formation profiles at 18/19.
- **Reduce:**
  - the #22 morale package to plain +1 Morale, with no mark gate;
  - the #21 reward profile to the plain Gold percent.
- **Check:** #2 vision, #6 Knowledge and #15 Primal must resolve to exactly the native effect.

## Shared-file asks

1. **The damage hook is required for Wardens' Oath and Elder's Ward.** Add this to `Homm3CounterattackDoctrineMutationRuntime.cs`, right after the Predator Instinct block (~:588-593):
   ```csharp
   var avengerPercent = Homm3RampartAvengerStrikeRuntime.DamagePercent(counterattacker ?? TryWrapUnit(__0), __instance, out var avengerDetail);
   if (avengerPercent != 0)
   {
   	percent += avengerPercent;
   	detail = detail == null ? avengerDetail : detail + "; " + avengerDetail;
   }
   ```
   Until this is added, #5 and #13 do nothing. They fail closed.
2. **`custom_law_tree_layout._KINGDOM_BONUS_TYPES` needs `unitUpgradingDiscount`.** Today it classifies by the `unit` prefix, so it treats the bonus as an army bonus. Vanilla puts its only owner, demon_20 "Evolve, Adapt, Overcome", in the kingdom group (g0). Elven Craftsmanship is a kingdom law. If you would rather not change the validator, move #19 to the r3 army column: kingdom [32, 25], army [19, 23, 30, 26]. That is also valid.
3. **Retire and reduce the profiles** listed above.
4. **Cleanup:** the legacy mark runtimes (`Homm3RampartAvengerMarkerRuntime.cs`, `Homm3RampartAvengerCastMarkerRuntime.cs`) lose their last law users once ask 3 lands.

## Not built and risks

Nothing in the spec is unbuilt. Not proven in game:
- **Mighty Oaks:** it relies on the approach planner's two-hex check (`TryPlanApproach`). The occupied set tracks head hexes only, so a large stack may find no spot. It then fails closed and simply doesn't strike.
- **Elder's Ward on retaliation-triggered chains:** it assumes the counter step is the queue's current step when its damage commits.
