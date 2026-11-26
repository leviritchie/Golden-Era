# Fortress law build (2026-11-21)

Data: `custom_factions/law_overrides/homm3_fortress.json`. It has `lawOverrides` and `lawTree`. There are no `lawRules` and no `lawBuffs`.

## Tree changes from the draft

**#11 Hunters of the Mire is now Bog Mist** (REVIEW). Enemy creatures deal -10%/-20% ranged damage (`unitStat modifierSet outDmgMods shoot_attack`, `receiverAllegiance enemy`). It sits at r1 in the army column, cost 3/3. That removes Fortress's only kit rule, which is why the file has no `lawRules`.

Costs by rank: 22 / 29 / 35 / 32 / 29.

| Rank | Kingdom | Army |
|---|---|---|
| r0 | 3 Riches I, 2 Marsh Sense, 5 Beastmaster's Eye | 4 Elite Gnolls, 8 Elite Lizardmen, 7 Swamp Venom |
| r1 | 1 Tax Collectors, 14 Mining: Mercury, 6 Glyphs of Fear | 10 Elite Serpent Flies, 9 Scent of Blood, 11 Bog Mist |
| r2 | 16 Riches II, 15 Bog Witchcraft (Nightshade), 18 Swamp Roads | 24 Elite Basilisks, 17 Elite Gorgons, 26 Poisoned Mire, 12 Fresh Quarry |
| r3 | 19 Marsh Levies, 21 Tar Pits | 23 Elite Wyverns, 32 Pack Discipline, 20 Thick Hides |
| r4 | 29 Riches III, 25 Stagnant Air, 34 Witch Coven | 30 Elite Hydras, 13 Pack Kill, 31 Swamp Dominion |

- Riches 3/16/29 are left out.
- 22, 27, 28 and 33 are `{"enabled": false}`.
- The skill laws carry distinct zero-strength anchors:
  - #5: `heroStat luck 0`.
  - #9, #12, #32: `unitStat ... 0` on the Fortress units.
  - #13: `unitStat outAllDmgMod 0.00` on all creatures, because non-Fortress stacks qualify too.
- `law_tree_problems` reports 0 errors and 0 warnings.

## Plugin levers

New file: `OfflineUnlockMod/Homm3FortressLawHooks.cs`.

Changes in `Homm3FortressPredatorInstinctRuntime.cs`:
- `:108`: new `HunterSide` fields.
- `:440`: law ranks are read when the side is recorded.
- `:259` (`DamagePercent`):
  - `:286`: Scent of Blood (#9) adds +10/+20 to the prey bonus.
  - `:299`: Pack Discipline (#32) multiplies the off-prey penalty by (2 - level)/2.
  - `:274` and `:305`: Pack Kill (#13) adds +10/+20 to any hunting-side hit on another pair's living prey, unless the hitter is that pair's predator. It sums with the hitter's own off-prey penalty.
- `:557` and `:899`: Beastmaster's Eye (#5). `BuildPairs` uses a stable sort by total stack Health, descending, instead of `Shuffle`.
- `:484` and `:921`: Fresh Quarry (#12). At each round start after pairing, a predator whose prey died takes the living, unhunted enemy stack with the most Health. It rewrites `ByPrey` and applies the prey marker.

There is no API to remove a buff. The dead prey's old marker doesn't matter, since that stack is dead.

All of these go through the existing committed-damage owner at `Homm3CounterattackDoctrineMutationRuntime.cs:588`. No shared change is needed for damage.

## Family indices reused for new effects

13, 18, 19, 21, 25, 22 (now dormant), 27 (now dormant), 33 (now dormant), 34.

Retire these Fortress profiles in `Homm3CustomLawEffectProfiles.cs`:
- the row-13 "attack-debuff-on-counterattack" profile;
- the morale trigger "damage-taken-or-slow-poison-momentum";
- the morale package "damage-taken-slow-poison-package";
- the reward profile "defensive-win-swamp-structure-income";
- the formation profiles at 18/19.

Check that these resolve to exactly the native effect:
- #2 vision;
- #6 hero Defence;
- #15 Nightshade, not Primal;
- #34 own spell cooldown -1. The old #34 was Bog Hex, a buff-duration law. Its profile must not survive.

## Shared-file asks

1. Retire the profiles listed above.

## Not built and caveats

Nothing is unbuilt. Two caveats:
- The predator marker still shows the base rank text, so Scent of Blood's extra damage isn't shown on the marker. No marker variants were added.
- Making sorted pairing the skill's default stays a later change (REVIEW section 3).
