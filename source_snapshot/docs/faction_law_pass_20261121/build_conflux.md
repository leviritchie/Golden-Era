# Conflux law build (2026-11-21)

Data: `custom_factions/law_overrides/homm3_conflux.json`. It holds `lawOverrides` (all 34 indices), `lawTree` and `lawRules`. `lawBuffs` is empty.

## Tree

Costs by rank are 21 / 33 / 26 / 33 / 32, 145 in total.

| Rank | Kingdom | Army |
|---|---|---|
| r0 | 3 Riches, 2 Planar Attunement, 20 Ley Wells | 5 Elite Pixies, 7 Elite Air Elementals, 4 Spark Wardens |
| r1 | 1 Tax Collectors, 14 Mining: Mercury, 8 Elemental Attunement, 32 Magic University | 10 Elite Water Elementals, 12 Elite Fire Elementals, 24 Prismatic Screen |
| r2 | 16 Riches, 9 Unequal Union, 15 Primal Wheel | 17 Elite Earth Elementals, 13 Isolating Winds, 11 Tidal Binding |
| r3 | 21 Planar Tithe, 6 Elemental Lore | 23 Elite Psychic Elementals, 22 Stable Fusion, 25 Elemental Constitution |
| r4 | 29 Riches, 28 Perfect Conjunction, 33 Astral Conduit | 30 Elite Firebirds, 26 Elemental Balance, 31 Phoenix Omen |

- Riches 3/16/29 are first in their kingdom column and set to `{"enabled": false}` in the overrides.
- Unused indices 18, 19, 27 and 34 are `{"enabled": false}`.

## Changes from the draft

These were the caller's decisions:
- **#33 Astral Conduit replaces Planar Static.**
  - Your heroes' spells cost 10%/20% less Mana: `heroStat manaCostBonusPercent` -0.10/-0.20.
  - r4 kingdom column, cost 4/4, icon demon_9.
  - It uses the percent stat; vanilla `manaCostBonus` is a flat reduction.
- **#26 Elemental Balance has no condition.** Friendly creatures deal 5% more damage and take 5% less: native `unitStat outAllDmgMod 0.05` and `inAllDmgMod -0.05`.
  - Receivers are the 21 Conflux SIDs and all 142 fused SIDs.
  - Cost 5. No `army_composition` rule is needed.

Other deviations:
- **#22 Stable Fusion** uses native `hpPerc` on every fused SID, 105 pairs plus 37 recipes.
- **#24 Prismatic Screen** and **#25 Elemental Constitution** include the fused SIDs in their receivers.
- **#11 Tidal Binding** uses the demon_5 icon, which removes an icon clash with #26.
- **#31 Phoenix Omen** uses the `h3_firebird_upg` portrait.
- **Ley Wells** gives 0.25/0.50.

## Kit rules (`lawRules`)

- 13 Isolating Winds: `adjacency` isolated, 10/20%, Air and Fire lines.

## Checks

- Local `law_tree_problems`: 0 errors, 0 warnings.
- `collect_law_rules`: passes.

## Plugin levers

All levers are in `OfflineUnlockMod/Homm3ConfluxFusionRuntime.cs`.

- `:179`: in the cast prefix after `TryLoad`, `config = ApplyFusionLaws(config, side, logicHero, ...)`.
  - The ranks come from `CustomLawRank` on the caster's data side, then its logic hero.
  - The result is logged.
- `:621-670`: `ApplyFusionLaws` and `LawRank`. A law only ever loosens the base values. It fails closed.
- `:936-971`: config `LineRankBonus` and `WithLaws(penalty, minShare, lineBonus)`.
  - `WithLaws` makes a `MemberwiseClone` copy for each cast, so the cached shared config is never changed.
  - `UnlockedLines` uses rank + bonus.
  - `RankForLine` returns max(1, best - bonus).

| Law | Effect |
|---|---|
| #8 Elemental Attunement | Every line unlocks one rank earlier (eligibility, the panel and the banner text). |
| #9 Unequal Union | `minShare` goes from 0.3333 to 0.25 / 0.20. |
| #28 Perfect Conjunction | `penalty` goes from 0.9 to 0.95 / 1.0. The session copy feeds `BuildPlan`, `BuildTrimmedPlan` and `BestInputs`, so the preview and the result match. |

## Family indices reused for new effects

Retire the old profiles for **13** (the counter doctrine row), **21, 22, 25, 28 and 33**.

## Shared-file asks

1. **Retire `Homm3ConfluxElementalConjunctionRuntime`.**
   - It reads rows 18, 19 and 27 (`:141-143`) to add hidden hero Attack, Defence and Spell Power per elemental family.
   - All three rows are disabled in this tree, so it adds nothing today.
   - Remove its registration, or gate it off, so that a later reuse of those rows does not wake it.
2. The DORMANT list entries for conflux_32 and conflux_33 are already gone: `DORMANT_LAW_OVERRIDE_SIDS_OUTSIDE_LAW_LINES` is empty.
3. Retire the family profiles for 13, 21, 22, 25, 28 and 33. For 13, also take the Conflux row out of `Homm3CounterattackDoctrineMutationRuntime`.
4. Translate the new law names and texts for 8, 9, 13, 11, 22, 24, 25, 26, 28, 31, 33 and 20.

## Not built, or limits

- The Glossary (`Homm3ConfluxFusionGlossary.cs:1058`) still shows the base rank for each line. It has no hero context, so Elemental Attunement is not reflected there.
- Fusion stays human-only, as before: the AI does not cast it, so the three fusion laws do nothing for AI players.
