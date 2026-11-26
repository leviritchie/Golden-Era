# Conflux (homm3_conflux): faction law draft, 2026-11-21

Draft only. Nothing is built.

## 1. Identity and levers

The HoMM3 Conflux is the town of the elemental planes: Pixies and Sprites, the four elementals of Air, Water, Fire and Earth, Psychic and Magic Elementals, and the Firebird and Phoenix on top. Its buildings are the Magic University and the Aurora Borealis, and Mercury is its tier-7 pressure. Its creatures are hard to kill with magic, they burn and drown and petrify, and the Phoenix rises again.

The faction skill is **Elemental Fusion**. A Conflux hero merges two elemental stacks into one fused elemental (105 pairs, 37 second-stage recipes). Fusion is free and permanent. Lines unlock by skill rank, the smaller stack must be at least a third of the whole, and the fused stack keeps 90% of the combined strength. The laws should open more fusions sooner, accept rougher pairs, and make fused stacks worth the loss.

Elemental Fusion levers. Paths are under `Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/` unless they say otherwise.

| Lever | Where | Current value |
|---|---|---|
| Strength kept by a fusion | `custom_factions/conflux_fusion/fusion_config.json:4` `penalty`; used in `Homm3ConfluxFusionRuntime.cs:413-414` (`FusedCount`) and `:489-495` (`BuildTrimmedPlan` / `BestInputs`) | 0.9 |
| Smallest share of the smaller stack | `fusion_config.json:5` `minShare`; `Homm3ConfluxFusionRuntime.cs:415-417` (`SharesOk`) and `:495` | 0.3333 |
| Lines unlocked by rank | `fusion_config.json` `tierLines` (1 = air, water, fire; 2 = +earth; 3 = +psychic); `UnlockedLines(rank)` `Homm3ConfluxFusionRuntime.cs:884-893`, checked in `EligibilityBlock` `:348-357` (`:356`); `RankForLine` `:896` | rank 1/2/3 |
| Second-stage recipes | `fusion_config.json:895` `recipeMinRank`; `EligibilityBlock` `:350-351` | 1 |
| Skill rank read | `Homm3ConfluxFusionRuntime.cs:677` `ResolveRank` (`skill_faction_homm3_conflux`, 1..3) | |
| Config validation | `Homm3ConfluxFusionRuntime.cs:957-960` (penalty in (0, 1], minShare in [0, 0.5]) | |
| Fused units | `custom_factions/conflux_fusion/fusion_units.json` (`h3_fusion_*`, stage 2 `h3_fusion_ii_*`) | 142 SIDs |
| Old Conjunction rows | `Homm3ConfluxElementalConjunctionRuntime.cs:141-143` adds hero Attack / Defence / Spell Power per elemental family from law rows 18, 19, 27 at battle start | live today |

Pixie and Firebird lines are not fusible.

## 2. Tree

Receivers: "line" = base, `_upg` and `_upg_alt`. "All Conflux" = the 21 Conflux SIDs plus every fused SID in `fusion_units.json`.

| Rank | Col | # | Name | Text (player-facing) | Levels (cost: value) | Build | Anchor |
|---|---|---|---|---|---|---|---|
| r0 | K | 3 | Resource Riches I | Provides 2500 Gold, 5 Wood and 5 Ore when enacted. | 1: once | A scaffold | scaffold |
| r0 | K | 2 | Planar Attunement | Your heroes gain +1 Sight radius. | 2: +1 | A `heroStat viewRadius 1` | r0 2 for +1 (old +2/+4/+6 brought into band) |
| r0 | K | 20 | Ley Wells | Your heroes restore 25%/50% more mana daily. | 2 / 2 | A `heroStat manaRestoreBonusPercent 25/50` | r0 hero utility, 2/level |
| r0 | A | 5 | Elite Pixies | Pixie growth +4/+8. They gain +2/+4 Defence. | 3: +4 / 2: +4 | A `cityUnitsIncrement h3_pixie 4`; `unitStat defence 2/4` (line) | T1-2 +2/+4 Defence; Pixies survive to Flutter Away |
| r0 | A | 7 | Elite Air Elementals | Air Elemental growth +4/+8. They always deal maximum Damage. | 3 / 2 | A `cityUnitsIncrement h3_air_elemental 4`; `unitBoolStat alwaysMaxDmg true` (line) | T2 rider "always max Damage" |
| r0 | A | 4 | Spark Wardens | Pixie and Air Elemental lines gain +1/+2 Initiative. | 2 / 2 | A `unitStat initiative 1/2` (6 SIDs) | All creatures +1 Initiative (r1, 6); two lines at r0 for 2/level |
| r1 | K | 1 | Tax Collectors | Produces 250/500 Gold daily. | 2 / 2 | A scaffold | scaffold (moved from r0) |
| r1 | K | 14 | Mining: Mercury | Produces 1/2 Mercury daily. | 2 / 2 | A `sideRes mercury 1/2` | scaffold (moved from r2) |
| r1 | K | 8 | Elemental Attunement **(S)** | Your heroes' Elemental Fusion unlocks each elemental line one rank earlier. | 3: on | D: `UnlockedLines(min(3, rank + 1))` | Animate Dead II (r1, 3, more skill output) |
| r1 | K | 32 | Magic University **(I)** | Upgrading spells costs 20%/40% less. | 3 / 3 | A `sideStat magicUpgradeCostPerBonus -20/-40` | Construction discount (r2, 3/level, -20/-40%) on spell upgrades; HoMM3 Conflux building |
| r1 | A | 10 | Elite Water Elementals | Water Elemental growth +2/+4. Negative effects on them last 1 round less. | 3 / 2 | A `cityUnitsIncrement h3_water_elemental 2`; `unitStat inComingDebuffDuration -1` (line) | T3-4 qualitative rider; Living Water washes effects off |
| r1 | A | 12 | Elite Fire Elementals | Fire Elemental growth +2/+4. Their damage over time deals 25%/50% more Damage. | 3 / 2 | A `cityUnitsIncrement h3_fire_elemental 2`; `unitStat modifierSet outDmgMods overTime_effect 0.25/0.5` (line) | DoT taken by enemies +25/+50% (r0, 2/level), one line; builds on Ignite |
| r1 | A | 24 | Prismatic Screen **(I)** | Friendly Conflux creatures take 5%/10%/15% less Magic Damage. | 2 / 2 / 2 | A `unitStat modifierSet inDmgMods magic_damage -0.05/-0.10/-0.15` (all Conflux) | Magic damage taken -5/-10/-15% (r0, 2/level). HoMM3 elementals shrug off magic. |
| r2 | K | 16 | Resource Riches II | Provides 5000 Gold, 10 Wood and 10 Ore when enacted. | 2: once | A scaffold | scaffold |
| r2 | K | 9 | Unequal Union **(S)** | Elemental Fusion accepts uneven stacks: the smaller stack may be as little as 25%/20% of the whole. | 2: 25% / 2: 20% | D: `minShare` 0.3333 → 0.25 / 0.20 | Hero utility 2/level; loosens a rule, adds no power by itself |
| r2 | K | 15 | Primal Wheel **(I)** | Primal spells of your heroes gain 1 level. | 3: +1 | A `heroStatMap magicSchoolSet primal 0 1` | Spell school +1 level (r2, 3). Conflux's one school law. |
| r2 | A | 17 | Elite Earth Elementals | Earth Elemental growth +1/+2. They counterattack twice per round. | 3 / 2 | A `cityUnitsIncrement h3_earth_elemental 1`; `unitStat numCounters 1` (line) | Qualitative rider "counterattacks twice"; Bedrock holds the line |
| r2 | A | 13 | Isolating Winds **(I)** | Air and Fire Elementals deal +10%/+20% Damage to enemies with no allies next to them. | 3 / 3 | C `adjacency` mode `isolated`, percent 10/20 (Air and Fire lines) | Formation (r2, 4/level), two lines, conditional |
| r2 | A | 11 | Tidal Binding **(I)** | Water and Earth Elementals take 10%/15% less Damage. | 3 / 3 | A `unitStat inAllDmgMod -0.10/-0.15` (Water and Earth lines) | Kept from the old tree; two lines, so 3/level against the faction-wide ±5% at r4 for 5 |
| r3 | K | 21 | Planar Tithe | Conflux creatures cost 10%/15%/20% less Gold to recruit. | 4 / 3 / 3 | A `unitHiringDiscount gold -0.10/-0.15/-0.20` (Conflux) | Creature cost (r3, 4/3/3) exactly |
| r3 | K | 6 | Elemental Lore | Your heroes gain +2/+4 Spell Power. | 3 / 3 | A `heroStat spellPower 2/4` | Hero primary stat (r3, 3/level, +2/+4) |
| r3 | A | 23 | Elite Psychic Elementals | Psychic Elemental growth +1/+2. The ability cooldowns of Psychic Elementals are reduced by 1 round. | 3 / 2 | A `cityUnitsIncrement h3_psychic_elemental 1`; `unitStat abilityCdBonus -1` (line) | Qualitative rider (cooldown -1); Mind Blast |
| r3 | A | 22 | Stable Fusion **(S)** | Fused elementals gain +10%/+20% Health. | 3 / 3 | A `unitStat hpPerc 0.10/0.20`, receivers every SID in `fusion_units.json` | Elite T5-7 +15/+30 HP, on every fused stack; 3/level at r3 |
| r3 | A | 25 | Elemental Constitution | Friendly Conflux creatures take 25%/50% less Damage from damage over time. | 3 / 3 | A `unitStat modifierSet inDmgMods overTime_effect -0.25/-0.50` (all Conflux) | Mirror of DoT +25/+50% (r0, 2/level), defensive, at r3 for 3 |
| r4 | K | 29 | Resource Riches III | Provides 7500 Gold, 15 Wood and 15 Ore when enacted. | 3: once | A scaffold | scaffold |
| r4 | K | 28 | Perfect Conjunction **(S)** | Fused elementals keep 95%/100% of the strength of the stacks that formed them. | 4: 95% / 4: 100% | D: `penalty` 0.9 → 0.95 / 1.0 | All schools +1/+2 levels (r4, 4/level): a capstone scaling the faction's main tool |
| r4 | K | 33 | Planar Static | Enemy heroes gain 1 less Focus per round. | 4: -1 | A `heroStatBattle energyLevelsPerRoundBonus -1` | Enemy -1 Focus per round (r4, 4) |
| r4 | A | 30 | Elite Firebirds | Firebird growth +1/+2. They gain +3/+6 Attack and Defence and +1 Speed. | 3 / 2 | A `cityUnitsIncrement h3_firebird 1`; `unitStat offence 3/6`, `defence 3/6`, `speed 1` (line) | Elite T5-7 exactly |
| r4 | A | 26 | Elemental Balance **(I)** | If your army holds Air, Water, Fire and Earth creatures, friendly Conflux creatures deal 5% more Damage and take 5% less Damage. | 5: on | C: new rule `army_composition` (section 5) applying `outAllDmgMod 0.05`, `inAllDmgMod -0.05` | Outgoing and incoming ±5%, faction-scoped (r4, 5), with a condition as vanilla's is |
| r4 | A | 31 | Phoenix Omen | Firebirds gain +2 Luck. | 3: +2 | A `unitStat luck 2` (Firebird line) | One-line Luck, single level; Phoenix rebirth town |

## 3. Removed or changed

| Old # | Old name | Fate |
|---|---|---|
| 1 | Tax Collectors (r0) | kept, moved to r1 (scaffold rank) |
| 2 | Planar Attunement (sight +2/+4/+6) | changed: +1 only (band) |
| 3 | Resource Riches I | kept |
| 4 | Spark Wardens | kept |
| 5 | Pixie Muster (+1/+2 max Damage) | changed: **Elite Pixies**, +2/+4 Defence |
| 6 | Elemental Aspect (+10% all Damage, r0) | replaced by **Elemental Lore** (above the band; index 6 is the primary-stat family) |
| 7 | Defensive Drills | replaced by **Elite Air Elementals** (Human clone removed; the line had no elite law) |
| 8 | Arcane Exercises | replaced by **Elemental Attunement (S)** (Human clone removed; Spell Power moves to #6 in the vanilla r3 shape) |
| 9 | Quartermaster Ledgers | replaced by **Unequal Union (S)** (Human clone removed) |
| 10 | Water Elemental Muster (+5/+10 HP) | changed: **Elite Water Elementals**, shorter debuffs |
| 11 | Tidal Binding | kept, moved r1 → r2, cost 3/3 |
| 12 | Swift Reflexes | replaced by **Elite Fire Elementals** (Human clone removed) |
| 13 | Elemental Backlash (row 13 counter +35%) | replaced by **Isolating Winds** (doctrine clone removed; runtime row retired for Conflux) |
| 14 | Mining: Mercury (r2) | kept, moved to r1 (scaffold rank) |
| 15 | Primal Wheel ("learn tier 1 Primal") | changed: Primal +1 level, text matches the data; moved r1 → r2 |
| 16 | Resource Riches II | kept |
| 17 | Elemental Overload (+10/+15% elementals) | replaced by **Elite Earth Elementals** (above the band) |
| 18 | Opposed Elements (melee formation) | dormant (Human clone; Conjunction runtime row) |
| 19 | Elemental Ward (ranged formation) | dormant (Human clone; Conjunction runtime row) |
| 20 | Planar Channels (start Focus +1) | replaced by **Ley Wells** (Demon's Focus Reserves) |
| 21 | Elemental Market (+1/+2 Crystal) | replaced by **Planar Tithe** (Mining: Mercury is the resource law) |
| 22 | Elemental Poise (Morale +1/+2) | replaced by **Stable Fusion (S)** (Morale +2 above the band) |
| 23 | Psychic Elemental Muster (+2/+4 Attack) | changed: **Elite Psychic Elementals**, cooldown -1 |
| 24 | Prismatic Screen (-10/-15%, r3) | changed: moved to r1, -5/-10/-15% at 2/2/2 (vanilla shape) |
| 25 | Elemental Exultation (morale trigger) | replaced by **Elemental Constitution** (Encouragement clone removed) |
| 26 | Elemental Balance (±5%, unconditional) | changed: needs all four elements in the army |
| 27 | Celestial Wheel (Focus cap +1) | dormant (Dungeon's Saturation; Conjunction runtime row) |
| 28 | Planar Alignment (extra building) | replaced by **Perfect Conjunction (S)** (Factory keeps the extra building) |
| 29 | Resource Riches III | kept |
| 30 | Phoenix Mandate (+1 Speed, +1 Initiative) | replaced by **Elite Firebirds** (the line had no elite law; Speed folded in) |
| 31 | Phoenix Omen (+2 Luck) | kept, moved r3 → r4 |
| 32 | (dormant) | now **Magic University** |
| 33 | (dormant) | now **Planar Static** |
| 34 | (dormant) | stays dormant |

Dormant after this pass: 18, 19, 27, 34.

## 4. Power check

| Rank | Kingdom / army | Total cost | Band | OK |
|---|---|---|---|---|
| r0 | 3 / 3 | 1+2+4 + 5+5+4 = **21** | 19-30 | yes |
| r1 | 4 / 3 | 4+4+3+6 + 5+5+6 = **33** | 25-33 | yes (top of band) |
| r2 | 3 / 3 | 2+4+3 + 5+6+6 = **26** | 25-42 | yes (old r2 was thin) |
| r3 | 2 / 3 | 10+6 + 5+6+6 = **33** | 22-47 | yes |
| r4 | 3 / 3 | 3+8+4 + 5+5+3 = **28** | 21-44 | yes |

- **Totals:** 30 laws, total cost 141.
- **(S) laws:** 4. Elemental Attunement r1, Unequal Union r2, Stable Fusion r3, Perfect Conjunction r4.
- **(I) laws:** 6. Magic University, Prismatic Screen, Primal Wheel, Isolating Winds, Tidal Binding, Elemental Balance.
- **Elite laws:** 7, one per line (Air, Fire and Earth added; Firebird replaces Phoenix Mandate).
- **Hero primary-stat laws:** 1 (Spell Power).
- **Learn / school laws:** 1 (Primal Wheel, +1 level). No "learn any tier".

## 5. Plugin asks

**Generic D reader.** Elemental Attunement, Unequal Union and Perfect Conjunction read `TryGetCustomLawLevel(sideOrHero, "homm3_conflux", index, out level)` from the casting hero's owner side. Fusion runs on the map from the hero's session (`ResolveDataHero`), so the reader takes that hero's player.

| # | Law | File / constant | Change per level | Hook |
|---|---|---|---|---|
| 8 | Elemental Attunement | `Homm3ConfluxFusionRuntime.cs:356` (`config.UnlockedLines(rank)` in `EligibilityBlock`); `RankForLine` `:896` for the block message | effective rank for lines = min(3, rank + 1) | `EligibilityBlock` gets the law level (or an effective rank) as an argument; the "Requires X Conflux" text uses the same effective rank. The recipe gate (`:350-351`) is unchanged. |
| 9 | Unequal Union | `Homm3ConfluxFusionRuntime.cs:415-417` (`SharesOk`), `:495` (`BestInputs`) | minShare = 0.25 (L1), 0.20 (L2) | pass the per-hero minShare into both; the validation range (`:957-960`) already allows it |
| 28 | Perfect Conjunction | `Homm3ConfluxFusionRuntime.cs:413-414` (`FusedCount`), `:489-495` | penalty = 0.95 (L1), 1.0 (L2) | same: per-hero penalty into `BuildPlan` and `BuildTrimmedPlan`; preview and result must match |

**A with a generated list:** Stable Fusion (#22), Prismatic Screen (#24) and Elemental Constitution (#25) list every fused SID from `fusion_units.json` as receivers (142 plus the 21 Conflux SIDs where stated). The generator should read the file, not a hand list, so new recipes are covered.

**C laws:**

| # | Law | Rule | Receivers |
|---|---|---|---|
| 13 | Isolating Winds | `adjacency` `{mode: "isolated"}`, percent 10 / 20 | Air and Fire Elemental lines (6) |
| 26 | Elemental Balance | **new kind `army_composition`**: at battle start, if the holder's side has living stacks covering Air, Water, Fire and Earth, every receiver gets a battle buff (clone of `sub_skill_tactics_2_initiative_buff`, `set` to `outAllDmgMod 0.05`, `inAllDmgMod -0.05`, hidden false, infinite). A fused stack counts for both of its parent elements (parents in `fusion_units.json`). Checked once at battle start; losing a stack later does not remove it. | all Conflux |

**Retire the Conjunction runtime.** `Homm3ConfluxElementalConjunctionRuntime.cs:141-143` reads rows 18, 19 and 27. All three are dormant in this tree, so the runtime adds nothing, but it should be removed or gated off in the build so a later reuse of those rows does not wake it.

**Index families (build note).** Index 13 (counter doctrine), 21 (gold %), 22 and 25 (morale), 28 (extra construction) and 33 (astrology) get non-family meanings here. The build must retire the Conflux rows of `Homm3CounterattackDoctrineMutationRuntime.cs` (row 13, +35% counter) and the Conflux profiles for 21/22/25/28/33 in `Homm3CustomLawEffectProfiles.cs` (Conflux block, up to ~`:2656`). Rows 2 (sight), 6 (primary stat) and 15 (spell school) keep their family meaning.

**Verify before build:**
- `manaRestoreBonusPercent` unit (percent or fraction) for Ley Wells.
- `magicUpgradeCostPerBonus` sign and unit for Magic University.
- Elite riders reach only the three line SIDs, not fused stacks made from them. That is intended (Stable Fusion is the fused-stack law).

## 6. Open questions

1. **Perfect Conjunction reaches 100%.** At L2 fusion loses nothing, so every fusion is pure upside. **Recommend yes**: it costs 8 points at r4, fusion is still permanent, and the fused stack must beat two separate stacks on the battlefield to be worth it. If testers find it dominant, cap L2 at 97%.
2. **Elemental Attunement opens Psychic fusions at Advanced.** With the law, a rank-2 hero fuses every line. **Recommend yes at r1**: it is the clearest early skill law and rank 3 still gives the stronger hero.
3. **Retiring Elemental Conjunction.** The plugin quietly gives Conflux heroes Attack, Defence and Spell Power per elemental family through rows 18/19/27. Players cannot see it, and it rides on formation rows the brief removes. **Recommend retiring it**; Elemental Balance is the visible, conditional version of "an army of all elements is stronger".
4. **Conflux owns the Primal school.** Factory also had a Primal law. **Recommend Conflux keeps Primal** (elemental magic) and Factory drops its school law (done in the Factory draft).
5. **Planar Static uses vanilla's enemy -1 Focus per round shape.** Vanilla owns that effect for another faction. **Recommend keeping it** for the r4 kingdom column; the alternative is a fourth skill law (Planar Envoys: every Conflux hero can cast Elemental Fusion at Basic), which needs the fusion map spell granted to heroes without the skill and is a larger build.
