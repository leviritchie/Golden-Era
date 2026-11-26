# Bulwark (homm3_bulwark): faction law draft, 2026-11-21

Draft only. Nothing is built.

## 1. Identity and levers

Bulwark is the HotA/HoMM-style northern mountain clan: Kobold miners, Rams and Snow Elves, Yeti runemasters, Shamans, Mammoths and Jotunn giants. The unit trade axis is **Tempo vs Bastion**:
- **Tempo:** Kobold Foreman, Argali, Steel Elf, Frost Speaker, War Mammoth, Jotunn Warlord.
- **Bastion:** Duck Behind Shields, Stubborn Fleece, Dig In, Glacier Stance.

The faction skill is **Runes**. Each Bulwark stack builds Rune Levels in battle and gains stats at thresholds. The laws should make runes start earlier, grow faster, spread between stacks and climb higher, without touching the threshold table. The kingdom side should read like a hardy mountain economy.

Runes levers, all in `Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/Homm3BulwarkRunesRuntime.cs`:

| Lever | Line | Current value |
|---|---|---|
| Rune Level cap by skill rank | `:44-46`; `ResolveCap` `:170-178` | 3 / 6 / 9 |
| Threshold stats (one stat per level, 3-level cycle; the brief's "every 3 levels" is inexact) | `:181-196` | Attack +2 at levels 1/4/7; Defence +2 at levels 2/5/8; Speed +1 at levels 3/6/9 |
| Threshold buff SIDs | `:223-228` | `homm3_bulwark_rune_level_1..9` |
| Buff duration | `:47` | 99 |
| Gain: Defend | `:230` | +3 |
| Gain: first damage dealt per action | `:232` | +2 |
| Gain: attack, cast or counter | `:234` | +1 |
| Once per action | `CorrelateGain` `:296-330` | Wait, move-only, zero damage and immune hits give nothing |
| War machines excluded | `:236` | |
| No carry-over between battles | `ClearBattleState` `:248-253` | |
| Apply gain / dispatch threshold buff | `TryApplyGain` `:1090-1180`; `TryDispatchThresholdBuff` `:1224` | |

Other notes:
- The law reader is `Homm3CustomFactionLawRuntime.cs:319`.
- **T7 resource:** installed Core Jotunn costs 2000 Gold and its upgrades 3500 Gold + 1 Gem, so Mining becomes **Gems** (was Crystals, and at r2).

## 2. Tree

Receivers: "line" = base, upgrade and alt (see SIDs below). "All Bulwark" = all 21 Bulwark SIDs.

| Line | Base | Upgrade | Alt |
|---|---|---|---|
| Kobold | `h3_kobold` | `h3_kobold_foreman` | `h3_kobold_upg_alt` |
| Ram | `h3_mountain_ram` | `h3_argali` | `h3_mountain_ram_upg_alt` |
| Elf | `h3_snow_elf` | `h3_steel_elf` | `h3_snow_elf_upg_alt` |
| Yeti | `h3_yeti` | `h3_yeti_runemaster` | `h3_yeti_upg_alt` |
| Shaman | `h3_shaman` | `h3_great_shaman` | `h3_shaman_upg_alt` |
| Mammoth | `h3_mammoth` | `h3_war_mammoth` | `h3_mammoth_upg_alt` |
| Jotunn | `h3_jotunn` | `h3_jotunn_warlord` | `h3_jotunn_upg_alt` |

| Rank | Col | # | Name | Text (player-facing) | Levels (cost: value) | Build | Anchor |
|---|---|---|---|---|---|---|---|
| r0 | K | 4 | Resource Riches I | Provides 2500 Gold, 5 Wood and 5 Ore when enacted. | 1: once | A scaffold | scaffold |
| r0 | K | 2 | Frontier Scouts | Your heroes' Sight range increases by 1. | 2: +1 | A `heroStat viewRadius 1` | Sight +1 (r0, 2) |
| r0 | K | 33 | Clear Mountain Sky | Produces 250/500 Astrology points daily. | 1: 250 / 2: 500 | A `astrologyExp 250/500` | Human 250 for 2. L1 is cheaper because Bulwark has no Mage Guild bonus. |
| r0 | A | 5 | Elite Kobolds | Kobold growth +4/+8. Kobolds counterattack twice per round. | 3 / 2 | A `cityUnitsIncrement h3_kobold 4`; `unitStat numCounters 1` (line) | T1 rider "counterattacks twice"; each counter gains +1 Rune |
| r0 | A | 3 | Elite Rams | Mountain Ram growth +4/+8. They gain +1/+2 Initiative. | 3 / 2 | A `cityUnitsIncrement h3_mountain_ram 4`; `unitStat initiative 1/2` (line) | T2 band, Tempo line |
| r0 | A | 7 | Runes Carved in Advance **(S)** | Bulwark creatures start each battle at Rune Level 1/2. | 3: L1 / 3: L2 | D: new battle-start hook calls `TryApplyGain` up to the level (capped by `ResolveCap`) | r0 battle opener; L2 gives +2 Attack and +2 Defence at round 1 |
| r1 | K | 1 | Tax Collectors | Produces 250/500 Gold daily. | 2 / 2 | A scaffold | scaffold |
| r1 | K | 14 | Mining: Gems | Produces 1/2 Gems daily. | 2 / 2 | A `sideRes gemstones 1/2` | scaffold (moved r2 → r1; Crystals → Gems) |
| r1 | K | 6 | Stone Bastions **(I)** | Your heroes gain +1/+2/+3 Defence. | 2 / 2 / 2 | A `heroStat defence 1/2/3` | r1 one primary stat, 2/level |
| r1 | A | 10 | Elite Snow Elves | Snow Elf growth +2/+4. They gain +3/+6 Attack. | 3 / 2 | A `cityUnitsIncrement h3_snow_elf 2`; `unitStat offence 3/6` (line) | T3 band; Cavalry rider (Attack half) |
| r1 | A | 8 | Clan Oath **(S)** | Defending grants your creatures 4/5 Rune Levels instead of 3. At level 2, their first hit in each action grants 3 instead of 2. | 3 / 3 | D: `:230` Defend 3 → 4/5; `:232` first damage 2 → 3 at L2 | Necromancy Power style (r1, 3/level) |
| r1 | A | 17 | Hold the High Ground **(I)** | When battling in the area you control, friendly creatures gain +1/+2/+3 Attack and Defence. | 2 / 2 / 2 | A (kept as is) | existing row; ownership-area bonus |
| r2 | K | 16 | Resource Riches II | Provides 5000 Gold, 10 Wood and 10 Ore when enacted. | 2: once | A scaffold | scaffold |
| r2 | K | 20 | Mountain Homesteads **(I)** | External dwellings you own produce +50%/+100% creatures. | 3 / 3 | A `externalDwellingIncrement 0.5/1.0` | Nature's dwelling law shape (r2) |
| r2 | K | 28 | Kobold Work Crews **(I)** | Your towns can build 1 additional building per day. | 3: +1 | A `constructionDailyLimit 1` | Construction +1/day (r2, 3). Was Architect's Mastery at 6. |
| r2 | A | 9 | Elite Yetis | Yeti growth +2/+4. Their ability cooldowns are reduced by 1 round. | 3 / 2 | A `cityUnitsIncrement h3_yeti 2`; `unitStat abilityCdBonus -1` (line) | T4 rider; **new** (no Yeti elite law before) |
| r2 | A | 29 | Elite Shamans | Shaman growth +1/+2. Using their abilities does not end their turn. | 3 / 2 | A `cityUnitsIncrement h3_shaman 1`; `unitBoolStat ignoreAbilityActionCost true` (line) | T5 rider |
| r2 | A | 11 | Winter's Bite **(I)** | Enemy creatures lose 1 Initiative when fighting on snow or mountain terrain. | 4: on | A `unitStat initiative -1` (enemy) with a native-terrain qualifier | Enemy -1 Initiative (r2, 6), terrain-limited for 4 |
| r3 | K | 21 | Prosperous Holdings | Your sources of Gold produce +10%/+15%/+20% Gold. | 4 / 2 / 2 | A `resPercentIncrementSet gold` | Coinage Reform (r2, 4/2/2), one rank later |
| r3 | K | 15 | Primal Study | Your heroes cast Primal spells as if 1 level higher. | 3: +1 | A school-level bonus (Primal) | one school law |
| r3 | K | 25 | Winter Stores | Produces +1/+2 Wood and Ore daily. | 3 / 3 | A `sideRes wood 1/2`, `ore 1/2` | mining law ×2 resources at r3 |
| r3 | A | 23 | Elite Mammoths | Mammoth growth +1/+2. They gain +15/+30 HP. | 3 / 2 | A `cityUnitsIncrement h3_mammoth 1`; `unitStat hp 15/30` (line) | T6 band (HP rider scaled to tier) |
| r3 | A | 12 | Shared Runes **(S)** | When a Bulwark stack reaches Rune Level 3, 6 or 9, each adjacent friendly Bulwark stack gains 1 Rune Level. | 4: on | D: new rule in `TryDispatchThresholdBuff` `:1224` | r3 single level 4 (Vengeful-Strike weight) |
| r3 | A | 31 | Shield Wall **(I)** | When your creatures Defend, they gain +2/+4 Attack until the end of their next turn. | 3 / 3 | B: buff triggered on `unit_skip` (shape of `skill_formation_1_unit_bonus`), effect cloned from `sunlightCavalry_buff_1` | Bastion pay-off; Defend also gains 3+ Runes |
| r4 | K | 26 | Resource Riches III | Provides 7500 Gold, 15 Wood and 15 Ore when enacted. | 3: once | A scaffold | scaffold |
| r4 | K | 34 | Rune-Fed Focus | Your Focus Charge limit increases by 1. | 3: +1 | A `heroStat maxEnergyLevelsBonus 1` | Saturation (r4, 3) |
| r4 | K | 27 | Mountain Passes | Your heroes gain +15%/+30% movement points. | 5 / 5 | A `heroStat movementBonusPercent 0.15/0.30` | Grove (+15/+30 at r4, 5/level) |
| r4 | A | 24 | Elite Jotunns | Jotunn growth +1/+2. They gain +3/+6 Attack and Defence and +1 Speed. | 3 / 2 | A `cityUnitsIncrement h3_jotunn 1`; `unitStat offence 3/6`, `defence 3/6`, `speed 1` (line) | T7 Cavalry rider |
| r4 | A | 30 | Elder Runes **(S)** | Your creatures' Rune Level limit increases by 3. | 5: +3 | D: `ResolveCap` +3 (6/9/12); new buff rows 10-12 continue the cycle (Attack +2 at 10, Defence +2 at 11, Speed +1 at 12) | r4 capstone weight (5) |
| r4 | A | 32 | Stand Unbroken | Your creatures can counterattack 1 additional time per round. | 4: +1 | A `unitStat numCounters 1` (all Bulwark) | +1 counterattack per round (r4, 4) |

Shield Wall and Stand Unbroken with Elite Kobolds: the counter from Stand Unbroken stacks with Elite Kobolds, so Kobolds counter three times, at r4 only. Counters give +1 Rune each, once per action.

## 3. Removed or changed

| Old row | Fate |
|---|---|
| Resource Riches I at index 3 **and** 4 (duplicate) | one kept (#4); #3 becomes Elite Rams |
| Resource Riches III at index 26 **and** 29 (duplicate) | one kept (#26); #29 becomes Elite Shamans |
| Mining: Crystals (r2) | changed: **Mining: Gems** at r1 |
| Mountain Wildness | removed |
| Counterstroke Doctrine (row 13 runtime) | removed; 13 dormant for Bulwark |
| Swift Reflexes, Melee / Ranged Formations (18/19), Arcane Exercises, Quartermaster Ledgers | removed (Human clones; 18/19 dormant) |
| Defensive Drills | becomes **Stone Bastions** (vanilla r1 primary-stat shape) |
| Fortune of the Clans, Encouragement (Morale trigger) | removed (generic clones; 22 dormant) |
| Runic Serenity (spell cooldown -1) | removed. The spell-cooldown law sits with Tower, the magic faction. Index 34 becomes Rune-Fed Focus. |
| Architect's Mastery (cost 6) | becomes **Kobold Work Crews** at cost 3 |
| Hold the High Ground | kept |
| (none) | **new:** Elite Yetis, all Runes (S) laws, Shield Wall, Winter's Bite, Mountain Homesteads, Winter Stores, Mountain Passes |

Dormant after this pass: 13, 18, 19, 22.

## 4. Power check

| Rank | Kingdom / army | Total cost | Band | OK |
|---|---|---|---|---|
| r0 | 3 / 3 | 1+2+3 + 5+5+6 = **22** | 19-30 | yes |
| r1 | 3 / 3 | 4+4+6 + 5+6+6 = **31** | 25-33 | yes |
| r2 | 3 / 3 | 2+6+3 + 5+5+4 = **25** | 25-42 | yes (at the floor) |
| r3 | 3 / 3 | 8+3+6 + 5+4+6 = **32** | 22-47 | yes |
| r4 | 3 / 3 | 3+3+10 + 5+5+4 = **30** | 21-44 | yes |

- **Totals:** 30 laws, total cost 140.
- **(S) laws:** 4. Runes Carved in Advance r0, Clan Oath r1, Shared Runes r3, Elder Runes r4.
- **(I) laws:** 6. Stone Bastions, Hold the High Ground, Mountain Homesteads, Kobold Work Crews, Winter's Bite, Shield Wall.
- **Hero primary-stat laws:** 1 (Defence).
- **School laws:** 1 (Primal Study).

Rune pace at Expert with Clan Oath L2 and Carved in Advance L2:
- A stack that Defends round 1 reaches level 2 + 5 = 7 by its second action. Its hit on the next turn takes it to cap 9.
- Without laws, Defend gets a stack to level 3 by round 2.

Elder Runes extends the cycle by three levels: +2 Attack, +2 Defence and +1 Speed more per stack. That is a late, strong capstone, priced at 5.

## 5. Plugin asks

**Generic D reader** (same as Tower and Dungeon): `TryGetCustomLawLevel(side, "homm3_bulwark", index)`. The runtime already resolves the owning side per stack for its cap (`ResolveCap` `:170-178`).

| # | Law | Where | Change |
|---|---|---|---|
| 7 | Runes Carved in Advance | **new** hook at battle start (after `ClearBattleState` `:248-253`, once per stack) | grant `min(level, cap)` Rune Levels through `TryApplyGain`, so threshold buffs dispatch normally. Skip war machines (`:236`). Stacks summoned later get it too when they first act. |
| 8 | Clan Oath | `:230` Defend gain, `:232` first-damage gain | Defend = 3 + level (4 / 5); first damage = 3 at level 2 |
| 12 | Shared Runes | `TryDispatchThresholdBuff` `:1224` | when the level crossed is 3, 6 or 9 (and 12 with Elder Runes), call `TryApplyGain(+1)` on each adjacent friendly Bulwark stack, flagged so it cannot chain (a shared gain never triggers another share) |
| 30 | Elder Runes | `ResolveCap` `:170-178`; buff table `:223-228`; overlay rows | cap + 3; add buffs `homm3_bulwark_rune_level_10..12` (Attack +2, Defence +2, Speed +1) to the Core overlay and the threshold table |

**B buff, #31 Shield Wall.** Clone the trigger shape of `skill_formation_1_unit_bonus`, with trigger `unit_skip` (Defend). The effect is an Attack +2/+4 buff cloned from `sunlightCavalry_buff_1`, lasting until the end of the stack's next turn.

**Index families (build note).**
- **34 (spell cooldown)** holds Rune-Fed Focus, **27 (school high)** holds Mountain Passes, and **25 (morale trigger)** holds Winter Stores. Their family runtimes are inert today, but they must skip Bulwark rows 25, 27 and 34.
- **13 (counter doctrine):** remove Bulwark's Counterstroke mapping from `Homm3CounterattackDoctrineMutationRuntime`.

**Verify before build:**
- **Winter's Bite terrain qualifier.** Check whether native receivers on *enemy* units accept a biome condition. If not, fall back to `actionArea` (the enemy in your controlled area), which is the same qualifier Hold the High Ground uses.
- **Mountain Homesteads stat name** (`externalDwellingIncrement`): confirm against the Nature row it copies.

## 6. Open questions

1. **Elder Runes needs new buff rows 10-12** and threshold-table growth. **Recommend building them.** A capstone that raises the cap with no stat behind it is invisible.
2. **Runes Carved in Advance L2** gives +2 Attack and +2 Defence from round 1 on every stack, for 6 points at r0. **Recommend shipping it**, and dropping to L1-only if the in-game check finds round-1 Bulwark too strong.
3. **Shared Runes adjacency.** Should "adjacent" include diagonal hexes or all neighbours? **Recommend all six hex neighbours**, with no chaining.
4. **Stand Unbroken plus Elite Kobolds** gives triple counters on Kobolds at r4. **Recommend allowing it.** Kobolds are T1, and each counter is capped at +1 Rune per action.
