# Dungeon (homm3_dungeon): faction law draft, 2026-11-21

Draft only. Nothing is built.

## 1. Identity and levers

The HoMM3 Dungeon is the warlocks' underworld: Troglodytes in the tunnels, the Labyrinth of the Minotaurs, the Mana Vortex, the Portal of Summoning, and Red and Black Dragons as the tier-7 pressure. The unit trade axis is **Reckless vs Sustained**, and the faction verb is timing plus push and terrain:
- Ambush, Hit and Run and Foul Swoop for strike timing.
- Bull Rush and Wall Slam for push.
- Burrow, Cave-In and Dragonflight for terrain.

The faction skill is **War Captives**. After a won battle, a share of the defeated army's value becomes captives. The player chooses one fate for them: Execute for hero XP, Ransom for gold, Eat to heal and feed the army, Enslave for daily gold, or Recruit, which turns them into creatures with the subskill. The laws should make the Dungeon lord rich in prisoners and ruthless with them. Battle laws stay on ambush and terrain.

**Stale brief point (verified):** the brief says Dungeon ranks grant mixed-faction Morale immunity. That carrier (`ignoreFractionsCount`) was removed for Dungeon, Factory, Bulwark, Fortress and Stronghold on 2026-11-19 (`tools/release_port/apply_release_core_overlay.py:19183`; `docs/ingame_check_queue.md:231`). Dungeon skill ranks now carry no stat bonus. **Many Races Below** (r2) brings it back as a paid law (open question 2).

War Captives levers, all in `Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/Homm3DungeonCaptivesRuntime.cs`:

| Lever | Line | Current value |
|---|---|---|
| Value per captive | `:63` `ValuePerCaptive` | 100 |
| Execute XP per captive, by rank | `:64` `ExecuteXpPerCaptive` | 6 / 9 / 12 |
| Ransom gold per captive, by rank | `:65` `RansomGoldPerCaptive` | 10 / 15 / 20 |
| Enslave gold per day per captive | `:66` `EnslaveGoldPerDay` | 1 / 1.5 / 2 |
| Eat share, by rank | `:67` `EatPercent` | 20 / 30 / 40 % |
| Recruit share, by rank | `:68` `RecruitPercent` | 10 / 15 / 20 % |
| Slave Markets / Dungeon Cells multipliers | `:69-70` | x1.25 / x1.15 |
| Interrogation mana per XP | `:71` | 0.015 |
| Win only; rank resolve | `:1139-1147` | |
| Subskill flags (`HasRecruit` and the others) | `:1156-1162` | |
| Captive count from the defeated squads' value | `:1178-1183` | |
| Execute and Ransom amounts | `:1192-1194` | |
| Eat build and cap (captives x 100) | `:1205-1228`, cap `:1220` | |
| Recruit build (full unit cost) | `:1234-1260`, `:1299` | |
| Enslave gold | `:1335` | |

Other notes:
- The window is `Homm3DungeonWarCaptivesWindow.cs`. The AI picks Eat, otherwise Ransom.
- The law reader is `Homm3CustomFactionLawRuntime.cs:319` `TryResolveActiveKnownCustomLaw`.
- **T7 resource:** installed Core Red Dragon costs 1 Mercury and its upgrades 2 Mercury, so Mining: Mercury stays.

## 2. Tree

Receivers: "line" = base, `_upg` and `_upg_alt`. "All Dungeon" = all 21 Dungeon SIDs. Today's rows list only the base SIDs; the build should list all 21.

| Rank | Col | # | Name | Text (player-facing) | Levels (cost: value) | Build | Anchor |
|---|---|---|---|---|---|---|---|
| r0 | K | 3 | Resource Riches I | Provides 2500 Gold, 5 Wood and 5 Ore when enacted. | 1: once | A scaffold | scaffold |
| r0 | K | 5 | Holding Cells **(S)** | Your heroes take +10%/+20% more War Captives after a won battle. | 3: +10% / 3: +20% | D: captive count x (1 + 0.1 x level), at `:1183` | Necromancy Power (r1, 3); captives are Dungeon's raised dead |
| r0 | K | 33 | Mana Vortex **(I)** | Your heroes' maximum Mana increases by +15/+30. | 2: +15 / 2: +30 | A `heroStat manaMax 15/30` (vanilla Dungeon shape) | vanilla Dungeon Mana +15 at cost 2. The HoMM3 Mana Vortex. |
| r0 | A | 4 | Elite Troglodytes | Troglodyte growth +4/+8. They gain +1/+2 Initiative. | 3 / 2 | A `cityUnitsIncrement h3_troglodyte 4`; `unitStat initiative 1/2` (line) | T1 band; supports Ambush and Burrow timing |
| r0 | A | 10 | Elite Harpies | Harpy growth +4/+8. Harpies always deal maximum Damage. | 3 / 2 | A `cityUnitsIncrement h3_harpy 4`; `unitBoolStat alwaysMaxDmg true` (line) | T2 rider "always max Damage" |
| r0 | A | 25 | Ambush from the Dark **(I)** | Your creatures deal +5%/+10% Damage to enemy stacks that have not yet acted this round. | 2: +5% / 2: +10% | C `turn_state` (`unacted_target`), all Dungeon | melee formation ±5-10% at 4/level; one condition, cheaper |
| r1 | K | 1 | Tax Collectors | Produces 250/500 Gold daily. | 2 / 2 | A scaffold | scaffold |
| r1 | K | 14 | Mining: Mercury | Produces 1/2 Mercury daily. | 2 / 2 | A `sideRes mercury 1/2` | scaffold |
| r1 | K | 7 | Ransom Brokers **(S)** | Ransom pays +25%/+50% Gold and Execution grants +25%/+50% Experience. | 3 / 3 | D: multiply at `:1192-1194` | Necromancy Power (r1/r3, 3) |
| r1 | K | 2 | Deep Scouts | Your heroes can see exact neutral squad counts. | 3: on | A `heroStat enableSquadCounts true` (kept) | existing row; HoMM3 Dungeon's scouting identity |
| r1 | A | 11 | Elite Beholders | Beholder growth +2/+4. Their ability cooldowns are reduced by 1 round. | 3 / 2 | A `cityUnitsIncrement h3_beholder 2`; `unitStat abilityCdBonus -1` (line) | T4 rider "ability cooldown -1" (Ray Barrage, Vigilant Eye) |
| r1 | A | 17 | Elite Medusae | Medusa growth +2/+4. Negative effects they apply last 1 round longer. | 3 / 2 | A `cityUnitsIncrement h3_medusa 2`; `unitStat outGoingDebuffDuration 1` (line) | Cold Touch half (r2, 4/level), one line. **New:** no Medusa elite law before. |
| r2 | K | 16 | Resource Riches II | Provides 5000 Gold, 10 Wood and 10 Ore when enacted. | 2: once | A scaffold | scaffold |
| r2 | K | 34 | No Escape Below **(I)** | Enemy heroes cannot flee from battle. | 5: on | A `heroStatBattle enableBattleEscapeBan true` (kept) | Live Roots (5). Feeds captives: no escape, no lost prisoners. |
| r2 | K | 28 | Excavation Crews | Your towns can build 1 additional building per day. | 3: +1 | A `constructionDailyLimit 1` | Construction +1/day (r2, 3). Old row 6/3 for +2. |
| r2 | K | 6 | Warlock's Tutelage | Your heroes gain +1/+2/+3 Spell Power. | 2 / 2 / 2 | A `heroStat spellPower 1/2/3` | r1 one primary stat, 2/level (one rank later) |
| r2 | A | 20 | Elite Minotaurs | Minotaur growth +1/+2. They gain +3/+6 Attack and Defence and +1 Speed. | 3 / 2 | A `cityUnitsIncrement h3_minotaur 1`; `unitStat offence 3/6`, `defence 3/6`, `speed 1` (line) | Cavalry rider; T5 band. **New:** no Minotaur elite law before. |
| r2 | A | 8 | Feast of the Fallen **(S)** | Eating captives restores 10% more, and the limit on what they can restore rises by half. | 4: on | D: Eat share +10 points at `:1207`; cap x1.5 at `:1220` | Cold Touch (r2, 4) |
| r2 | A | 12 | Many Races Below **(I)** | Your armies suffer no Morale penalty for mixing factions. | 4: on | A `heroStat ignoreFractionsCount true` | Death Equalizes All (r1 army, 4). Recruited captives make mixed armies. |
| r3 | K | 9 | Taskmasters **(S)** | Your heroes can choose Recruit for War Captives without the Recruit subskill (at the rank's share). | 5: on | D: `HasRecruit` OR law owned at `:1160` | Live Roots 5 (rule unlock) |
| r3 | K | 15 | Night Dominion | Your heroes cast Night spells as if 1 level higher. | 3: +1 | A school-level bonus (Night) | the "+1 level, 3" school law; one per faction |
| r3 | K | 21 | Slave Labour | Dungeon creatures cost -10%/-15%/-20% Gold to recruit. | 4 / 3 / 3 | A `unitCostDiscount gold -0.1/-0.15/-0.2` (all Dungeon) | Free Death (r3, 4/3/3) |
| r3 | A | 24 | Elite Manticores | Manticore growth +1/+2. Their damage-over-time effects deal +25%/+50% Damage. | 3 / 2 | A `cityUnitsIncrement h3_manticore 1`; `unitStat outDotDmgPercent 0.25/0.5` (line) | T6 band; Venomous Sting and Venom Burst |
| r3 | A | 26 | Kill Corridors **(I)** | When your creatures push an enemy into a wall, obstacle or another stack, they deal +10%/+20% extra Damage. | 3 / 3 | C `wall_slam` on all Dungeon | Vengeful Strike (r3, 3/3); feeds Bull Rush and Wall Slam |
| r3 | A | 32 | Tunnel Network **(I)** | Dungeon creatures gain +1 Speed while on your side of the battlefield. | 5: on | A `unitStat speed 1` with `actionArea allied` | Movement r2 5/level, battle version |
| r4 | K | 29 | Resource Riches III | Provides 7500 Gold, 15 Wood and 15 Ore when enacted. | 3: once | A scaffold | scaffold |
| r4 | K | 30 | Overlord's Due **(S)** | After choosing a fate for your War Captives, you can choose a second one from Execute, Ransom or Eat at half strength. | 5: on | D: window second pass and AI path | r4 single level 5 (Live Roots weight) |
| r4 | K | 27 | Battle Academy | Your heroes gain +10%/+20% Experience. | 4 / 4 | A `heroStat expBonus 0.1/0.2` | XP +10/20% (4/4) |
| r4 | A | 31 | Elite Red Dragons | Red Dragon growth +1/+2. Their attacks ignore 10%/20% of the target's Defence. | 3 / 2 | A `cityUnitsIncrement h3_red_dragon 1`; `unitStat armorPen 0.1/0.2` (line) | T7 rider armour pen |
| r4 | A | 23 | Dread of the Deep | Enemy creatures lose 1 Defence and 1 Morale. | 4: on | A `unitStat defence -1`, `moral -1` (enemy) (old Subterranean Cruelty) | Enemy -1 Initiative (r2, 6) is a stronger stat at a lower rank; this one is r4 at 4 |

## 3. Removed or changed

| Old row | Fate |
|---|---|
| Predator's Instruction (±10%, out of band) | removed |
| Cruel Formations, Kill Corridors (formation version), Beholder Crossfire, Shadow Crossfire | removed (Human formation clones; 18/19 dormant). Kill Corridors returns as `wall_slam` (#26). |
| Quartermaster Ledgers, Swift Reflexes, Defensive Drills, Arcane Exercises | removed (Human clones). The Spell Power drill becomes Warlock's Tutelage in the vanilla 2/level shape. |
| Outnumber (row 13 doctrine runtime) | removed; 13 dormant for Dungeon |
| Cavern Ambush, Terror Exploitation, Terror Parade | removed. Replaced by Ambush from the Dark (one `turn_state` condition) and Dread of the Deep. |
| High Night (any-tier Night learning) | removed. Any tier is Tower's capstone in this pass. Night Dominion keeps the +1 level school law. |
| Deep Tutors | renamed **Battle Academy**, now the vanilla XP shape |
| Troglodyte / Harpy / Beholder / Red Dragon Muster | become Elite laws with vanilla riders (old +max Damage, +HP and +5/10% riders dropped) |
| Manticore Venom (+1 Init, +10% melee) | becomes **Elite Manticores** (DoT rider) |
| Dragon Dominion, Dragon Tyranny (+4 Speed, out of band) | removed |
| Native Mastery, Deep Portents | removed (generic clones) |
| Excavation Crews | kept at index 28; now single level, +1 for 3 (was +1/+2 for 6/3) |
| Subterranean Cruelty | renamed **Dread of the Deep**, moved to r4 |
| (none) | **new:** Elite Medusae, Elite Minotaurs, all War Captives (S) laws, Mana Vortex, Many Races Below, Tunnel Network, Slave Labour |

Dormant after this pass: 13, 18, 19, 22.

## 4. Power check

| Rank | Kingdom / army | Total cost | Band | OK |
|---|---|---|---|---|
| r0 | 3 / 3 | 1+6+4 + 5+5+4 = **25** | 19-30 | yes |
| r1 | 4 / 2 | 4+4+6+3 + 5+5 = **27** | 25-33 | yes |
| r2 | 4 / 3 | 2+5+3+6 + 5+4+4 = **29** | 25-42 | yes |
| r3 | 3 / 3 | 5+3+10 + 5+6+5 = **34** | 22-47 | yes |
| r4 | 3 / 2 | 3+5+8 + 5+4 = **25** | 21-44 | yes |

- **Totals:** 30 laws, total cost 140.
- **(S) laws:** 5. Holding Cells r0, Ransom Brokers r1, Feast of the Fallen r2, Taskmasters r3, Overlord's Due r4.
- **(I) laws:** 6. Mana Vortex, Ambush from the Dark, No Escape Below, Many Races Below, Kill Corridors, Tunnel Network. Battle Academy is the vanilla XP shape and is not counted.
- **Hero primary-stat laws:** 1 (Spell Power).
- **School laws:** 1 (Night Dominion).

Captive economy at Expert with every captive law:
- Ransom: 20 x 1.5 = 30 Gold per captive.
- Captive count: x1.2.
- Overlord's Due adds a half-strength second fate.

A 10,000-value win gives 100 x 1.2 = 120 captives, so 3600 Gold from Ransom, plus a half-strength Eat on top. Compare vanilla Coinage Reform: +20% of daily gold. The Gold is front-loaded on wins only, which suits the "rich from conquest" identity. Watch it in the in-game check.

## 5. Plugin asks

**Generic D reader.** Use the same `TryGetCustomLawLevel(side/hero, factionSid, index)` that Tower asks for. Captives resolve the winning hero at `:1139-1147`; read the law level there and pass it into the build methods.

| # | Law | Where | Change |
|---|---|---|---|
| 5 | Holding Cells | `:1178-1183` captive count | count = floor(count x (1 + 0.1 x level)) before the Slave Markets / Cells multipliers |
| 7 | Ransom Brokers | `:1192-1194` | ransom gold and execute XP x (1 + 0.25 x level) |
| 8 | Feast of the Fallen | `BuildEat` `:1205-1228` | share += 10 points (`:1207`); cap captives x 150 instead of x 100 (`:1220`) |
| 9 | Taskmasters | flags `:1156-1162` | `HasRecruit = subskill OR law 9 owned`. Recruit share uses `RecruitPercent[rank]`; the window shows the option. |
| 30 | Overlord's Due | `Homm3DungeonWarCaptivesWindow.cs` and the resolve path | after the first fate resolves, reopen with Execute, Ransom and Eat at 50% of their value, excluding the fate already chosen. The AI path picks Eat then Ransom, as it does today. Enslave and Recruit are never doubled (they persist). |

**C rules.**
- #25 Ambush from the Dark: `turn_state` with `unacted_target`, bonus 5/10% outgoing damage, receivers all Dungeon.
- #26 Kill Corridors: `wall_slam`, extra damage 10/20%, receivers all Dungeon. Today only Minotaur upgrades push; the law grows as push abilities are added.

**Index families (build note).**
- **22 (morale flat):** `Homm3BattleStartMoraleLawRuntime.cs:21-22` gives Dungeon "enemy morale -1 when law 22 is owned". This draft leaves 22 dormant, so the runtime falls silent for Dungeon. Dread of the Deep (#23) carries enemy Morale -1 natively. Alternative: put Dread at index 22 and drop its native morale bonus, letting the runtime do it. Either works; pick one so the penalty never applies twice.
- **13 (counter doctrine):** dormant for Dungeon, so remove Dungeon from `Homm3CounterattackDoctrineMutationRuntime`'s row-13 mapping (Outnumber).
- **21 (gold %)** now holds a creature-cost law and **25 (morale trigger)** holds Ambush from the Dark. Both family runtimes are inert today, but they must not act on Dungeon rows 21 and 25.
- **34** keeps No Escape Below (as today) rather than a spell-cooldown law, so the spell-cooldown family must skip Dungeon 34.

**Verify before build:**
- `outDotDmgPercent` (Elite Manticores): if it is not a native stat, fall back to the cloned Venomous Sting buff with +25/+50% damage (Build B).
- The `actionArea allied` qualifier on Tunnel Network: check it means the friendly half of the battlefield. If not, fall back to "+1 Speed in the first round" (C `turn_state` round 1).

## 6. Open questions

1. **Overlord's Due strength.** 50% for the second fate, never Enslave or Recruit. **Recommend 50%**, with no further multipliers stacking on the Eat cap beyond Feast's x1.5.
2. **Many Races Below.** It brings back the `ignoreFractionsCount` that was removed on 2026-11-19, and it is Undead's vanilla law. **Recommend yes, as a paid r2 law.** Recruited captives build mixed armies, and paying 4 for it is a choice the free skill rank did not offer.
3. **No Escape Below duplicates Nature's Live Roots.** **Recommend keeping it for Dungeon.** It directly protects the captive haul.
4. **Simulated battles and captives.** Captives are only built on a real win at `:1139`. If auto-resolve skips that path, Holding Cells and Ransom Brokers are worth less to auto-resolvers. **Recommend keeping the current behaviour** and matching whatever is decided for Artificing.
5. **Dungeon's morale-22 runtime** (section 5): put Dread at 22, or keep it native at 23? **Recommend native at 23** and dropping Dungeon from the 22 runtime, which keeps it to one source.
