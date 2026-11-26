# Stronghold law build (2026-11-21)

Data: `custom_factions/law_overrides/homm3_stronghold.json`, with `lawOverrides`, `lawTree`, `lawRules` and `lawBuffs`.

## What changed from the draft

The tree is the draft's, with these changes from REVIEW and the owner answers:
- **#11 Elite Orcs** gives +2/+4 growth and +3/+6 Attack to the Orc line. Shots do not raise the Warcry, so there is no plugin lever.
- **#25 No Mercy** is cut to 5%/10%.

Costs by rank are 22 / 28 / 36 / 37 / 23.

| Rank | Kingdom | Army |
|---|---|---|
| r0 | 3 Riches I, 5 Drums of Krewlod, 33 War Festival | 4 Elite Goblins, 10 Elite Wolf Riders, 7 Charge! |
| r1 | 1 Tax Collectors, 14 Mining: Crystals, 6 Hall of Valhalla, 22 Battle Rage | 11 Elite Orcs, 8 War Paint |
| r2 | 16 Riches II, 9 Smouldering Rage, 17 Cyclops Quarries, 20 Horde on the March | 23 Elite Ogres, 24 Elite Rocs, 12 Tribes United |
| r3 | 18 Warlord's Levy, 21 Freelancer's Guild, 19 Muster of the Clans | 26 Elite Cyclopes, 31 Gang Up, 32 Smell of Blood |
| r4 | 29 Riches III, 13 Unending Warcry, 34 Spellbreaker Chants | 30 Elite Behemoths, 25 No Mercy |

How the file is laid out:
- Riches 3/16/29 are left out of `lawOverrides`, as the coordinator asked.
- Indices 2, 15, 27 and 28 are `{"enabled": false}`.
- The D and C laws carry zero-strength anchors, and each anchor is different so no two laws share an effect: `heroStat luck/moral/defence 0` in the kingdom column, `unitStat outAllDmgMod/inAllDmgMod 0.00` in the army column.

Checks run:
- `law_tree_problems` on the file's rows, against the vanilla icon owners: 0 errors, 0 warnings.
- `collect_law_rules`: passes.

## Plugin levers

New file `OfflineUnlockMod/Homm3StrongholdLawHooks.cs` holds the law indices, the per-level tables and a fail-closed rank reader.

In `Homm3StrongholdWarcryRuntime.cs`:
- `:110`: new `WarSide` fields.
- `:450`: the ranks are read when the side is armed. Drums of Krewlod (#5) sets the start value of `Bonus`.
- `:922`: Tribes United (#12) lifts the `IsStronghold` gate in BeginTurn. The Initiative loan keeps its gate.
- `:988`: Smouldering Rage (#9). `Break()` keeps 25%/50% of the counter.
- `:1016`: Unending Warcry (#13) adds +1 to the multiplier term, giving 1.5 / 2 / 2.5.

Not changed: contributors are still melee-only. Tribes United widens who receives the Attack, and non-Stronghold melee stacks already join the chain because `AddContributor` has no faction gate.

## Family indices reused for new effects

13, 18, 19, 21, 25, 33, 34. Retire these Stronghold profiles in `Homm3CustomLawEffectProfiles.cs`:
- the row-13 counter profile;
- the morale trigger at 25;
- the reward profile at 21, "raid-tribute-income";
- the formation profiles at 18/19.

Three more need checking:
- #22 must be plain +1 Morale.
- #33 must pay only the astrology gold, at 250/500.
- #34 must give enemy spell cooldown +1.

## Shared-file asks

1. **Charge! (#7) needs a bonus_buff_info row.** Each vanilla `battleSubskillBonus unit_buff X` names a row in `DB/side_buffs/bonus_buff_infos/buff_infos_*.json`, in the shape `{"id": X, "sid": <buff>, "duration": 1, "charges": 1, "allegiance": "ally"}`. `add_law_buffs` only writes the `DB/buffs` row (`h3_law_stronghold_charge`, a clone of `fraction_law_demon_6_unit_bonus` with `infinite` false and `data.stats.speed` 1). The overlay must also emit an info row with id `h3_law_stronghold_charge`, sid `h3_law_stronghold_charge` and duration 1. Without it the law bonus won't resolve. The one-round length comes from that row's `duration`.
2. **Retire the profiles** listed above.

## Not built

Nothing from the approved spec is missing.

Not proven in game:
- the Charge! buff's duration, which depends on ask 1;
- whether the Drums starting value shows in the Warcry marker before the first contributor joins.
