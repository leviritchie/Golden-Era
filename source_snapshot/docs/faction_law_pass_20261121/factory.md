# Factory (homm3_factory): faction law draft, 2026-11-21

Draft only. Nothing is built.

## 1. Identity and levers

The HoMM3 Factory (Horn of the Abyss) is a frontier foundry town: halfling grenadiers, mechanics who repair constructs, automatons and the Dreadnought, gunslingers with bounties, sandworms and couatls from the desert around it. It builds faster than anyone and fights with marks and coordinated fire: one unit tags a target (Bombardier Mark, Glass Shards, Overheated) and the gunline cashes it in. It has 8 creature lines (two at tier 7).

The faction skill is **Logistics Network**. Network buildings (Housing, Warehouse, Hub, power stations, Upgrade Center) are enhanced with resources and dust. Enhancements raise a network level that sets range, discounts and output; Upgrade Centers let a hero manage buildings remotely, one switch per week. The laws should make the network reach further, cost less, survive raids and run hotter.

Logistics Network levers. Paths are under `Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/` unless they say otherwise.

| Lever | Where | Current value |
|---|---|---|
| Base logistics level | `custom_factions/factory_logistics/logistics_config.json` `baseLogisticsLevel`; applied at `Homm3FactoryLogisticsEffects.cs:504` and `:608` (`net.LogisticsLevel = config.BaseLogisticsLevel` + rail), `level0` at `:556`; also `Homm3FactoryLogisticsInsights.cs:486` | 2 |
| Range per level | `logistics_config.json` `rangeMpPerLevel` | 100 movement points |
| Enhancement cost | `Homm3FactoryLogisticsConfig.cs:108-166` `CostOf` (dust at `:163-164`), `Scaled` `:172-186`; `logistics_config.json` `costScale 0.2`, `dustCostByLevel [0,10,20]` | as configured |
| Warehouse discount | `Homm3FactoryLogisticsFacade.cs:322-323` `Discounted` | per Warehouse level |
| Building level in effect | `Homm3FactoryLogisticsEffects.cs:434-441` `EffectiveLevel` (built + `PowerBonus`, power stations excluded) | built level |
| Max level, caps | `logistics_config.json` `maxLevel 3`; Housing 90, Warehouse 90, Hub 1.0 | 3 |
| Remote management level | `Homm3FactoryLogisticsFacade.cs:335-340` `RemoteLevel = max(UpgradeCenter, command)`; Upgrade Center set to skill rank at `Homm3FactoryLogisticsRuntime.cs:1238-1240` | needs an Upgrade Center |
| Weekly switch | `Homm3FactoryLogisticsFacade.cs:403` `SwitchUsedThisWeek`, `:659-663` (one per week, pending until next day); applied at `Homm3FactoryLogisticsRuntime.cs:461-467` | 1 per week |
| Enhancements lost on capture | `Homm3FactoryLogisticsRuntime.cs:437` `Maintain`, wipe at `:455` (`remove.Add`) | wiped |
| Skill rank read | `Homm3FactoryLogisticsRuntime.cs:414` `SkillRank` | |
| Subskills | `Homm3FactoryLogisticsConfig.cs:55-57`; `TradeContractsMarketsPerHero = 2` at `:58` | |

**Manifest is stale:** `custom_factions/homm3_factory.json` still names the retired Split Assembly as the faction skill. Fix it separately; this draft does not touch it.

## 2. Tree

Receivers: "line" = base, `_upg` and `_upg_alt`. "All Factory" = all 24 Factory SIDs. "Constructs" = Automaton and Dreadnought lines (the two lines with the Construct card).

| Rank | Col | # | Name | Text (player-facing) | Levels (cost: value) | Build | Anchor |
|---|---|---|---|---|---|---|---|
| r0 | K | 3 | Resource Riches I | Provides 2500 Gold, 5 Wood and 5 Ore when enacted. | 1: once | A scaffold | scaffold |
| r0 | K | 7 | Surveyors' Charter **(S)** | Your Logistics Network level increases by 1. | 3: +1 | D: base logistics level + level | Single-level r0 economy law, priced like Focus start +1 (r0, 4) less one: it grows with the network |
| r0 | K | 2 | Prospectors | Your heroes gain +1 Sight radius. | 2: +1 | A `heroStat viewRadius 1` | r0 2 for +1 (old +1/+2 brought into band) |
| r0 | K | 8 | Smelting Works | Buildings in your towns cost 20%/40% less Ore. | 2: -20% / 2: -40% | A `constructionDiscount ore -0.2/-0.4` | Construction resource discount (r2, 2-3, -20/-40%), pulled to r0 at 2/2 |
| r0 | A | 4 | Elite Halflings | Halfling growth +4/+8. They gain +1/+2 Luck. | 3: +4 / 2: +4 | A `cityUnitsIncrement h3_halfling 4`; `unitStat luck 1/2` (line) | T1-2 stat rider; builds on the Grenadier's Luck card |
| r0 | A | 10 | Elite Mechanics | Mechanic growth +4/+8. Their Repair restores 25%/50% more Health. | 3 / 2 | A `cityUnitsIncrement h3_mechanic 4`; `unitStat finalHealingBonusPercent 0.25/0.5` (line) | T2 qualitative rider (Repair is the line's card) |
| r1 | K | 1 | Tax Collectors | Produces 250/500 Gold daily. | 2 / 2 | A scaffold | scaffold |
| r1 | K | 14 | Mining: Crystals | Produces 1/2 Crystals daily. | 2 / 2 | A `sideRes crystals 1/2` | scaffold (unchanged resource) |
| r1 | K | 5 | Telegraph Lines **(S)** | You can manage every network building remotely at Basic/Advanced level, as if an Upgrade Center stood there. | 3: Basic / 3: Advanced | D: `RemoteLevel = max(UpgradeCenter, command, level)` | Rule change, 3/level (Animate Dead II shape, r1) |
| r1 | A | 11 | Elite Armadillos | Armadillo growth +2/+4. Armadillos counterattack twice per round. | 3 / 2 | A `cityUnitsIncrement h3_armadillo 2`; `unitStat numCounters 1` (line) | Qualitative rider "counterattacks twice"; Huddle and Curl Up make it the wall |
| r1 | A | 17 | Elite Automatons | Automaton growth +2/+4. They gain +3/+6 Attack and Defence. | 3 / 2 | A `cityUnitsIncrement h3_automaton 2`; `unitStat offence 3/6`, `defence 3/6` (line) | T3-4 +3/+6 Attack and Defence |
| r1 | A | 9 | Riveted Plating **(I)** | Armadillos and constructs take 10%/20% less Ranged Damage. | 2 / 2 | A `unitStat modifierSet inDmgMods shoot_attack -0.1/-0.2` and `range_attack` (Armadillo, Automaton, Dreadnought lines) | Magic damage taken -5/-10/-15% (r0, 2/level); one damage type, three lines |
| r2 | K | 16 | Resource Riches II | Provides 5000 Gold, 10 Wood and 10 Ore when enacted. | 2: once | A scaffold | scaffold |
| r2 | K | 12 | Standard Parts **(S)** | Enhancing network buildings costs 15%/30% less. | 3: -15% / 3: -30% | D: enhancement cost x (1 - 0.15 x level), after the Warehouse discount | Construction discount (r2, 2-3/level) |
| r2 | K | 28 | Assembly Lines **(I)** | You can construct 1 additional building daily. | 3: +1 | A `constructionDailyLimit 1` | Extra building (r2, 3). Old cost 6 brought into band. |
| r2 | K | 20 | Railway Depots | Your heroes gain +10/+20 movement points. | 5: +10 / 5: +20 | A `heroStat movementBonus 10/20` | Hero movement (r2, 5/level, +10/+20) |
| r2 | A | 23 | Elite Sandworms | Sandworm growth +1/+2. Burrow does not end their turn. | 3 / 2 | A `cityUnitsIncrement h3_sandworm 1`; `unitBoolStat ignoreAbilityActionCost true` (line) | T5 rider "abilities do not end the turn" (Elite Mancers) |
| r2 | A | 26 | Coordinated Fire **(I)** | Friendly Factory creatures deal +5%/+10% Damage for each other friendly stack that has already damaged the target this round (at most +15%/+30%). | 3 / 3 | C `hit_this_round` percent 5 cap 15 / percent 10 cap 30 (all Factory) | Melee/ranged formation (r2, 4/level ±5-10%); needs set-up, so 3/level |
| r2 | A | 31 | Overpressure Rounds **(I)** | The first attack of Halflings and Gunslingers each round deals +10%/+20% Damage. | 3 / 3 | C `first_hit` side `attacker`, percent 10/20 (Halfling and Gunslinger lines) | Two lines, one hit per round; formation price less one |
| r3 | K | 32 | Insured Plants **(S)** | Enhancements on your network buildings are kept when an enemy captures the town. They stop working until you retake it. | 3: on | D: skip the capture wipe at `Homm3FactoryLogisticsRuntime.cs:455` | Rule change, single level; Spell cooldown -1 (r3, 3-4) priced |
| r3 | K | 15 | Retrofit Bays | Upgrading Factory creatures costs 25%/50% less. | 3 / 3 | A `unitUpgradingDiscount -0.25/-0.5` (Factory) | Creature cost (r3, 4/3/3, -10/-15/-20%) on upgrades only |
| r3 | K | 6 | Mercenary Pay | Your heroes gain +2/+4 Attack. | 3 / 3 | A `heroStat offence 2/4` | Hero primary stat r3 3/level +2/+4 (old Officer Training) |
| r3 | A | 24 | Elite Gunslingers | Gunslinger growth +1/+2. Their attacks ignore 10%/20% of the target's Defence. | 3 / 2 | A `cityUnitsIncrement h3_gunslinger 1`; `unitStat armorPen 0.1/0.2` (line) | T5-7 10/20% armour pen |
| r3 | A | 30 | Elite Couatls | Couatl growth +1/+2. Positive effects they apply last 1 additional round. | 3 / 2 | A `cityUnitsIncrement h3_couatl 1`; `unitStat outComingBuffDuration 1` (line) | T7 qualitative rider; Meditation and Jade Ward are buffs |
| r3 | A | 13 | Target Designation **(I)** | Friendly Factory creatures deal +10%/+20% Damage to enemies with Bombardier Mark, Glass Shards, Shattered or Overheated. | 3 / 3 | C `damage_vs_buff` buffs `h3_kit_factory_marked_effect`, `h3_kit_factory_glass_shards_effect`, `h3_kit_factory_shattered_effect`, `h3_kit_factory_overheated_effect`, percent 10/20 (all Factory) | Counterattack +50/+100% (r3, 3/level), conditional on a mark |
| r4 | K | 29 | Resource Riches III | Provides 7500 Gold, 15 Wood and 15 Ore when enacted. | 3: once | A scaffold | scaffold |
| r4 | K | 21 | Overclocked Plants **(S)** | Every enhanced network building works as if it were 1 level higher (at most Expert). | 6: +1 | D: `EffectiveLevel` + 1, capped at `maxLevel` | Terra Mortis-style r4 rule (6) |
| r4 | K | 34 | Signal Jammers | The cooldowns of all battle spells of enemy heroes are increased by 1 round. | 4: +1 | A `heroStatBattle magicCdBonus 1` | Spell cooldown +1 enemy (r3, 3-4). Old r0 cost 5 moved to r4. |
| r4 | A | 22 | Elite Dreadnoughts | Dreadnought growth +1/+2/+3. They gain +3/+6/+9 Attack and Defence. | 3 / 2 / 1 | A `cityUnitsIncrement h3_dreadnought 1`; `unitStat offence 3/6/9`, `defence 3/6/9` (line) | T5-7 +3/+6 Attack and Defence; third level at 1 |
| r4 | A | 25 | Salvage Crews **(I)** | After a battle you win, 20%/40% of your constructs that fell are rebuilt. | 4 / 4 | D/C: new post-battle rule (section 5) | Vampirism +50% (r2, 6); post-battle only, constructs only, r4 |

## 3. Removed or changed

| Old # | Old name | Fate |
|---|---|---|
| 1 | Tax Collectors | kept |
| 2 | Frontier Scouts (sight +1/+2) | changed: **Prospectors**, +1 only (band) |
| 3 | Resource Riches I | kept |
| 4 | Halfling Muster (+1/+2 max Damage) | changed: **Elite Halflings**, +1/+2 Luck |
| 5 | Assembly Calibration (buff duration +1/+2) | replaced by **Telegraph Lines (S)**. Buff duration is Tower's law now. |
| 6 | Officer Training | changed: renamed **Mercenary Pay** (same value) |
| 7 | Defensive Drills | replaced by **Surveyors' Charter (S)** (Human clone removed) |
| 8 | Arcane Exercises | replaced by **Smelting Works** (Human clone removed) |
| 9 | Quartermaster Ledgers | replaced by **Riveted Plating** (Human clone removed) |
| 10 | Mechanic Muster (+1/+2 min Damage) | changed: **Elite Mechanics**, Repair rider |
| 11 | Armadillo Muster (+5/+10 HP) | changed: **Elite Armadillos**, counterattacks twice |
| 12 | Swift Reflexes | replaced by **Standard Parts (S)** (Human clone removed) |
| 13 | Counterstroke Doctrine (+50/+100% counter) | replaced by **Target Designation** (doctrine clone removed; runtime row retired for Factory) |
| 14 | Mining: Crystals | kept |
| 15 | Primal Study (Primal +1 level) | replaced by **Retrofit Bays**. Primal is Conflux's school. |
| 16 | Resource Riches II | kept |
| 17 | Automaton Muster (+5/+10 HP) | changed: **Elite Automatons**, +3/+6 Attack and Defence |
| 18 | Melee Formations | dormant (Human clone) |
| 19 | Ranged Formations | dormant (Human clone) |
| 20 | (dormant) | now **Railway Depots** |
| 21 | Prosperous Holdings (gold %) | replaced by **Overclocked Plants (S)**. Cove keeps the gold % law. |
| 22 | Banner Discipline (Morale +1/+2) | replaced by **Elite Dreadnoughts** (Morale +2 above the band; the Dreadnought line had no elite law) |
| 23 | Sandworm Muster (+2/+4 Attack) | changed: **Elite Sandworms**, Burrow does not end the turn |
| 24 | Gunslinger Muster (+2/+4 Attack) | changed: **Elite Gunslingers**, armour pen |
| 25 | Encouragement | replaced by **Salvage Crews** (Encouragement clone removed) |
| 26 | Engineering Doctrine (25% SP/Knowledge → A/D) | replaced by **Coordinated Fire** (above the 20% band; Human's Hero's Blessing) |
| 27 | High Magic (learn any tier of Primal) | dormant ("learn any tier" is a Temple capstone) |
| 28 | Architect's Mastery (extra building, cost 6) | changed: **Assembly Lines**, cost 3 |
| 29 | Resource Riches III | kept |
| 30 | Couatl Muster (+5/+10% Damage) | changed: **Elite Couatls**, buff duration +1 |
| 31 | (dormant) | now **Overpressure Rounds** |
| 32 | Native Mastery | replaced by **Insured Plants (S)** |
| 33 | Astrologers' Charter (250/500/750) | dormant (generic; Cove keeps astrology) |
| 34 | Battlefield Supremacy (enemy spell cooldown +1, r0, 5) | changed: **Signal Jammers**, moved to r4, cost 4 |

Dormant after this pass: 18, 19, 27, 33.

## 4. Power check

| Rank | Kingdom / army | Total cost | Band | OK |
|---|---|---|---|---|
| r0 | 4 / 2 | 1+3+2+4 + 5+5 = **20** | 19-30 | yes |
| r1 | 3 / 3 | 4+4+6 + 5+5+4 = **28** | 25-33 | yes |
| r2 | 4 / 3 | 2+6+3+10 + 5+6+6 = **38** | 25-42 | yes |
| r3 | 3 / 3 | 3+6+6 + 5+5+6 = **31** | 22-47 | yes |
| r4 | 3 / 2 | 3+6+4 + 6+8 = **27** | 21-44 | yes |

- **Totals:** 30 laws, total cost 144.
- **(S) laws:** 5. Surveyors' Charter r0, Telegraph Lines r1, Standard Parts r2, Insured Plants r3, Overclocked Plants r4.
- **(I) laws:** 6. Riveted Plating, Assembly Lines, Coordinated Fire, Overpressure Rounds, Target Designation, Salvage Crews.
- **Elite laws:** 8, one per line (Dreadnought added).
- **Hero primary-stat laws:** 1 (Attack).
- **Learn / school laws:** 0.

## 5. Plugin asks

**Generic D reader.** All five (S) laws and Salvage Crews read `TryGetCustomLawLevel(sideOrHero, "homm3_factory", index, out level)` from the owning player's side (`dataFractionLaws`). Network code runs per player, so it reads the player, not a hero.

| # | Law | File / constant | Change per level | Hook |
|---|---|---|---|---|
| 7 | Surveyors' Charter | `Homm3FactoryLogisticsEffects.cs:504`, `:556` (`level0`), `:608`; `Homm3FactoryLogisticsInsights.cs:486` | logistics level = `BaseLogisticsLevel` + 1 (range +100 movement points via `rangeMpPerLevel`) | one helper `BaseLevelFor(player)` used at all four sites, so the insight panel matches |
| 5 | Telegraph Lines | `Homm3FactoryLogisticsFacade.cs:335-340` `RemoteLevel` | RemoteLevel = max(UpgradeCenter, command, level) (1 = Basic, 2 = Advanced) | the weekly switch limit (`:403`, `:659-663`) and pending-until-next-day rule stay; only the Upgrade Center visit requirement goes |
| 12 | Standard Parts | `Homm3FactoryLogisticsFacade.cs:322-323` (`Discounted`); display in `Homm3FactoryLogisticsConfig.cs:108-166` `CostOf` | cost x (1 - 0.15 x level), multiplied after the Warehouse discount, rounded up; dust included | the cost shown and the cost charged must use the same function |
| 32 | Insured Plants | `Homm3FactoryLogisticsRuntime.cs:455` (`remove.Add` in `Maintain`) | if the previous owner has the law, do not remove that town's enhancements on capture | **new rule:** store the original owner with the enhancement; `EffectiveLevel` returns 0 while another player owns the town; enhancements resume when the original owner retakes it. If a third player captures, they stay dormant. |
| 21 | Overclocked Plants | `Homm3FactoryLogisticsEffects.cs:434-441` `EffectiveLevel` | built level > 0 → level + 1, capped at `maxLevel` (3) | power stations stay excluded as today; buildings already at 3 gain nothing, so the law favours a wide network |
| 25 | Salvage Crews | post-battle result (new) | after a won battle, restore floor(lost x 0.2 x level) of each construct stack (Automaton and Dreadnought lines) to the hero's army | **new hook:** battle-end army write, same path the Dungeon War Captives runtime (`Homm3DungeonCaptivesRuntime.cs`) uses to add creatures after a battle. Applies to the winner only; a stack wiped out entirely is restored into a free slot or skipped if none. |

**C laws** (receivers while the law is owned):

| # | Law | Rule | Receivers |
|---|---|---|---|
| 26 | Coordinated Fire | `hit_this_round` percent 5 cap 15 / percent 10 cap 30 | all 24 Factory SIDs |
| 31 | Overpressure Rounds | `first_hit` `{side: "attacker"}`, percent 10 / 20 | Halfling and Gunslinger lines (6) |
| 13 | Target Designation | `damage_vs_buff` `{buffs: [h3_kit_factory_marked_effect, h3_kit_factory_glass_shards_effect, h3_kit_factory_shattered_effect, h3_kit_factory_overheated_effect]}`, percent 10 / 20 | all 24 Factory SIDs |

**Index families (build note).** Index 13 (counter doctrine), 15 (spell school), 21 (gold %), 22 and 25 (morale) are plugin "known law family" indices (`Homm3CustomFactionLawRuntime.cs:24-38`). This draft gives them non-family meanings. The build must retire the Factory rows of `Homm3CounterattackDoctrineMutationRuntime.cs` (row 13) and the Factory profiles for 15/21/22/25 in `Homm3CustomLawEffectProfiles.cs`. Rows 2 (sight), 6 (primary stat), 28 (extra building) and 34 (spell cooldown) keep their family meaning.

**Verify before build:**
- `finalHealingBonusPercent` on Elite Mechanics scales heals cast *by* the receiver (Repair goes through the plugin's `factory_repair` kind). If the plugin computes Repair itself, read the law there instead.
- `ignoreAbilityActionCost` on Elite Sandworms: Burrow must be an `Ability` commit for the flag to apply.
- `unitUpgradingDiscount` scope (Factory only, all resources).

## 6. Open questions

1. **Telegraph Lines removes the Upgrade Center visit.** The logistics spec makes the Upgrade Center the remote hub. **Recommend yes**, with the one-switch-per-week limit kept: the law trades a building trip for 6 law points.
2. **Insured Plants keeps enhancements through a capture.** The spec wipes them to make raids hurt. **Recommend yes, dormant until retaken** (as drafted): the raider still turns the town off, but the owner does not pay twice.
3. **Salvage Crews rebuilds lost constructs after battle.** It is a post-battle restore like Necromancy, for two lines only. **Recommend yes at r4**, constructs only, winner only. If the cross-faction review wants one "restore after battle" law per game, Necropolis has the stronger claim and this becomes +1 Repair charge for Mechanic lines instead.
4. **Factory drops its spell school law.** Primal goes to Conflux (its elemental identity). **Recommend no school law for Factory**; it is the least magical town, and Signal Jammers covers the anti-magic angle.
5. **Railway Depots uses the vanilla hero-movement shape** (+10/+20 for 5/5 at r2). Vanilla owns that effect for another faction. **Recommend keeping it** as Factory's map law (rails and logistics); swap for a second network law (Freight Contracts: +1 Trade Contracts market per hero, `TradeContractsMarketsPerHero` at `Homm3FactoryLogisticsConfig.cs:58`) if the review rejects the overlap.
6. **Manifest still names Split Assembly.** Not a law call, but the owner should approve renaming the skill string to Logistics Network in `custom_factions/homm3_factory.json`. **Recommend fixing it** in the build.
