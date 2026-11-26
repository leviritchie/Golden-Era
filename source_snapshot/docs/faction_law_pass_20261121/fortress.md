# Fortress law tree (draft, 2026-11-21)

## 1. Identity and levers

Fortress is the swamp: gnolls and lizardmen in the reeds, poison, petrifying gazes, hides that shrug off blows, and Hydras at the bottom of the bog. The faction skill Predator Instinct pairs each friendly stack with one enemy stack (its prey): predators hit their prey much harder and everything else a little softer. The trade axis is Hunter (chase and kill the prey) against Warden (endure, poison, slow). The tree should feel like a hunt in a place the enemy cannot leave: pick the right prey, wear it down, and let the swamp finish the rest.

Predator Instinct levers (`Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/Homm3FortressPredatorInstinctRuntime.cs`):

| Lever | file:line | Constant / branch | Current value |
|---|---|---|---|
| Bonus vs prey | :60, :270 | `BonusPercentByRank` | {0, 33, 66, 100} % |
| Penalty off prey (while prey lives) | :65, :278-283 | `PenaltyPercentByRank` | {0, 17, 33, 50} % |
| Pairing order | :509-510 | `Shuffle(predators); Shuffle(prey);` | random |
| Pairing time | :459-538 (BuildPairs) | first RoundStarted; pairs never re-made | once per battle |
| Ranged predators | :497 | skipped unless `side.EnduranceHunting` (pick, :45) | melee only |
| Intimidation slow | :52, :54, :560 | `IntimidationSlowSid` magic_ice_bolt_effect_0, `IntimidationSlowRounds` | -3 Initiative, 2 rounds |
| Frenzy haste | :53, :55, :686 | `FrenzyHasteSid` magic_haste_effect_1, `FrenzyRounds` | 1 round, 1 Focus (overlay `FRENZY_FOCUS_COST = 1`) |
| Marker buffs | :58, :530-531 | `MarkerDuration`, predator marker `PredatorBuffPrefix + rank` | 99 rounds, rank text |
| Damage route | :248-285 (`DamagePercent`) | contributed to the committed-damage owner in `Homm3CounterattackDoctrineMutationRuntime` | — |

Core overlay mirror: `tools/release_port/homm3_fortress_predator_instinct_core_overlay.py`, which holds the subskill and marker texts, Frenzy cost and charges.

Existing runtime families on this faction (`Homm3CustomLawEffectProfiles.cs`):
- row 13 counter profile "fortress.attack-debuff-on-counterattack" (:1021-1026: a counter marks the attacker for -25% on its next attack);
- morale trigger "fortress.damage-taken-or-slow-poison-momentum" (:1173-1184);
- morale package "fortress.damage-taken-slow-poison-package" (:1330-1335);
- reward and calendar "fortress.defensive-win-swamp-structure-income" / "fortress.poison-slow-calendar-sign" (:1490-1495).

Row 13 is the counterattack doctrine and retires; the skill laws replace it.

## 2. Tree

Index = `fraction_law_homm3_fortress_<#>`. Line SIDs are `h3_<line>`, `h3_<line>_upg` and `h3_<line>_upg_alt`, for the lines gnoll, lizardman, serpent_fly, basilisk, gorgon, wyvern and hydra.

| Rank | Col | # | Name | Text (player-facing) | Levels (cost: value) | Build (A/B/C/D + exact bonuses or rule) | Anchor |
|---|---|---|---|---|---|---|---|
| r0 | K | 3 | Resource Riches I | Provides 2500 Gold, 5 Wood and 5 Ore when enacted. | 1: once | A `sideOneTimeAddRes` 2500/5/5 | scaffold |
| r0 | K | 2 | Marsh Sense | Your heroes gain +1/+2 sight radius. | 2: +1; 2: +2 | A `heroStat viewRadius 1/2` | Training Scouting (r0, 2 for +1) |
| r0 | K | 5 | Beastmaster's Eye **(S)** | Your strongest creatures hunt the strongest enemy stacks. | 3: on | D: pairing sorted by total Health instead of shuffled | Focus start +1 (r0, 4), cheaper: no stat |
| r0 | A | 4 | Elite Gnolls | Gnoll growth in your cities increases by +4/+8. Their healing is 25%/50% stronger. | 3: +4, 25%; 2: +8, 50% | A `cityUnitsIncrement h3_gnoll 4`; `unitStat finalHealingBonusPercent 0.25/0.50` R[gnoll line] | elite T1; builds on Scavenge |
| r0 | A | 8 | Elite Lizardmen | Lizardman growth in your cities increases by +4/+8. Their poison and other debuffs last 1 round longer. | 3: +4; 2: +8 | A `cityUnitsIncrement h3_lizardman 4`; `unitStat outComingDebuffDuration 1` R[lizardman line] | elite T2, qualitative; builds on Venom Shot |
| r0 | A | 7 | Swamp Venom **(I)** | Enemy creatures take +25%/+50% Damage from damage over time. | 2: +25%; 2: +50% | A `unitStat modifierSet inDmgMods overTime_effect 0.25/0.50`, `receiverAllegiance enemy` | DoT taken (r0, 2/level) |
| r1 | K | 1 | Tax Collectors | Your kingdom gains +250/+500 Gold daily. | 2: 250; 2: 500 | A `sideRes gold` 250/500 | scaffold |
| r1 | K | 14 | Mining: Mercury | Your kingdom gains +1/+2 Mercury daily. | 2: 1; 2: 2 | A `sideRes mercury` 1/2 | scaffold (moved from r2 to r1) |
| r1 | K | 6 | Glyphs of Fear | Your heroes gain +1/+2/+3 Defence. | 2: +1; 2: +2; 2: +3 | A `heroStat defence` 1/2/3 | hero stat (r1, 2/level) |
| r1 | A | 10 | Elite Serpent Flies | Serpent Fly growth in your cities increases by +2/+4. They gain +1 Speed and +1/+2 Initiative. | 3: +2, +1 Spd, +1 Ini; 2: +4, +1 Spd, +2 Ini | A `cityUnitsIncrement h3_serpent_fly 2`; `unitStat speed 1`; `unitStat initiative 1/2` R[serpent_fly line] | elite T3 (Elite Cavalry rider) |
| r1 | A | 9 | Scent of Blood **(S)** | Your predators deal a further +10%/+20% Damage to their prey. | 2: +10%; 2: +20% | D: `BonusPercentByRank[rank] + 10/20` | conditional damage (r0-1, 2/level) |
| r1 | A | 11 | Hunters of the Mire **(I)** | Friendly creatures deal +10%/+20% Damage to enemy stacks that have not acted yet this round. | 3: +10%; 3: +20% | C `turn_state` fact `unacted_target`, percent 10/20, all friendly | conditional damage (r1, 3/level) |
| r2 | K | 16 | Resource Riches II | Provides 5000 Gold, 10 Wood and 10 Ore when enacted. | 2: once | A `sideOneTimeAddRes` 5000/10/10 | scaffold |
| r2 | K | 15 | Bog Witchcraft | Nightshade spells of your heroes gain +1 level. | 3: +1 | A `heroStat magicSchoolSet night 0 1` | school +1 level (r2, 3) |
| r2 | K | 18 | Swamp Roads | Your heroes gain +10/+20 Movement points. | 5: +10; 5: +20 | A `heroStat movementBonus 10/20` | movement (r2, 5/level) |
| r2 | A | 24 | Elite Basilisks | Basilisk growth in your cities increases by +2/+4. Their abilities recover 1 round faster. | 3: +2; 2: +4 | A `cityUnitsIncrement h3_basilisk 2`; `unitStat abilityCdBonus -1` R[basilisk line] | elite T4 (new line law); builds on Stone Gaze |
| r2 | A | 17 | Elite Gorgons | Gorgon growth in your cities increases by +1/+2. They gain +15/+30 Health. | 3: +1, +15; 2: +2, +30 | A `cityUnitsIncrement h3_gorgon 1`; `unitStat hp 15/30` R[gorgon line] | elite T5 rider |
| r2 | A | 26 | Poisoned Mire **(I)** | Enemy creatures have -1 Initiative. | 6: -1 | A `unitStat initiative -1`, `receiverAllegiance enemy` | Enemies -1 Initiative (r2, 6) |
| r2 | A | 12 | Fresh Quarry **(S)** | When a predator's prey is destroyed, the predator picks a new prey at the start of the next round. | 4: on | D: re-pair at RoundStarted | Natural Selection (r2, 4) |
| r3 | K | 19 | Marsh Levies | Fortress creatures cost -10%/-15%/-20% Gold. | 4: -10%; 3: -15%; 3: -20% | A `unitHiringDiscount gold -0.10/-0.15/-0.20`, qualifier `fraction homm3_fortress` | creature cost (r3, 4/3/3) |
| r3 | K | 21 | Tar Pits **(I)** | Enemy heroes can't flee or surrender. | 5: on | A `heroStatBattle enableBattleEscapeBan true` | Live Roots (r3, 5) |
| r3 | A | 23 | Elite Wyverns | Wyvern growth in your cities increases by +1/+2. They ignore a further 10%/20% of Defence. | 3: +1, 10%; 2: +2, 20% | A `cityUnitsIncrement h3_wyvern 1`; `unitStat armorPen 0.10/0.20` R[wyvern line] | elite T6 (Elite Angels rider) |
| r3 | A | 32 | Pack Discipline **(S)** | Your predators lose only half / none of their Damage against other targets. | 3: half; 3: none | D: off-prey penalty x0.5 / x0 | Vengeful Strike (r3, 3/3) |
| r3 | A | 20 | Thick Hides **(I)** | Friendly creatures take -5%/-10% Damage from basic attacks. | 3: -5%; 3: -10% | A `unitStat modifierSet inDmgMods basic_attack -0.05/-0.10` | magic damage taken (2/level) scaled up for the more common source |
| r4 | K | 29 | Resource Riches III | Provides 7500 Gold, 15 Wood and 15 Ore when enacted. | 3: once | A `sideOneTimeAddRes` 7500/15/15 | scaffold |
| r4 | K | 25 | Stagnant Air **(I)** | Enemy heroes gain 1 less Focus each round. | 4: -1 | A `heroStatBattle energyLevelsPerRoundBonus -1` | enemy Focus -1/round (r4, 4) |
| r4 | K | 34 | Witch Coven | Battle spells of your heroes recover 1 round faster. | 4: -1 | A `heroStat magicCdBonus -1` | Natural Serenity (4) / spell cooldown (r3, 3-4) |
| r4 | A | 30 | Elite Hydras | Hydra growth in your cities increases by +1/+2. They gain +3/+6 Attack and Defence. | 3: +1, +3; 2: +2, +6 | A `cityUnitsIncrement h3_hydra 1`; `unitStat offence 3/6`, `defence 3/6` R[hydra line] | elite T7 rider |
| r4 | A | 13 | Pack Kill **(S)** | Friendly creatures deal +10%/+20% Damage to enemy stacks hunted by another of your creatures. | 4: +10%; 4: +20% | D: damage percent vs prey of a friendly pair, attacker not that pair's predator | All +1/+2 Damage (r4, 4/level), conditional |
| r4 | A | 31 | Swamp Dominion | On native terrain, friendly creatures deal +5% and take -5% Damage. | 5: 5% | A `unitStat outAllDmgMod 0.05`, `inAllDmgMod -0.05`, `biomeType native` | ±5% swing (r4, 5) |

## 3. Removed or changed

| Old # | Old name | Fate |
|---|---|---|
| 1 | Tax Collectors | kept |
| 2 | Marsh Sense (sight +2/4/6) | changed: +1/+2 (r0 band) |
| 3 | Resource Riches I | kept |
| 4 | Gnoll Entrenchment (+1/+2 HP) | changed: Elite Gnolls |
| 5 | Gnoll Muster | replaced by #5 Beastmaster's Eye (growth folded into Elite Gnolls) |
| 6 | Hidebound Drill (+10% damage at r0) | replaced by #6 Glyphs of Fear (hero-stat family); +10% at r0 was out of band |
| 7 | Defensive Drills | replaced by #7 Swamp Venom (Human clone) |
| 8 | Arcane Exercises | replaced by #8 Elite Lizardmen (Human clone) |
| 9 | Quartermaster Ledgers | replaced by #9 Scent of Blood (Human clone) |
| 10 | Serpent Fly Muster | changed: Elite Serpent Flies |
| 11 | Serpent Fly Screens | replaced by #11 Hunters of the Mire |
| 12 | Swift Reflexes | replaced by #12 Fresh Quarry (Human clone) |
| 13 | Thorned Hides (counter doctrine) | replaced by #13 Pack Kill; row-13 Fortress counter profile retires |
| 14 | Mining: Mercury (at r2) | kept, moved to r1 |
| 15 | Bog Witchcraft (Primal) | changed: Nightshade (see open question 3) |
| 16 | Resource Riches II | kept |
| 17 | Gorgon Guard | changed: Elite Gorgons |
| 18 | Hidebound Drill (hero Defence +1/2/3; melee formation slot) | replaced by #18 Swamp Roads; hero Defence moved to #6 Glyphs of Fear |
| 19 | Marsh Crossfire (ranged formation) | replaced by #19 Marsh Levies (Human formation clone) |
| 20 | Thick Hides (-10% basic damage) | changed: -5%/-10% at r3, 3/3 |
| 21 | Marsh Levies (hiring -10/15/20%) | moved to #19; #21 is now Tar Pits |
| 22 | Cold-Blooded Resolve (Morale +1/+2) | dormant (Morale +2 out of band; Fortress gets no flat Morale law) |
| 23 | Wyvern Muster | changed: Elite Wyverns |
| 24 | Wyvern Venom | replaced by #24 Elite Basilisks (the missing line law; Wyvern growth is in #23) |
| 25 | Cold-Blooded Surge (morale trigger) | replaced by #25 Stagnant Air (Encouragement clone) |
| 26 | Poisoned Mire (enemy -1 Initiative, r4, 4) | changed: r2, cost 6 |
| 27 | Deep Bog Witchcraft (any-tier Primal) | dormant (one school law per faction) |
| 28 | Mudworks (+1 building, 6) | dormant (Architect's Mastery clone) |
| 29 | Resource Riches III | kept |
| 30 | Hydra Marsh Lords | changed: Elite Hydras |
| 31 | Swamp Dominion (native +10%/-10%) | changed: +5%/-5% (BASELINE ±5% swing at r4, 5) |
| 32 | (dormant) | new: Pack Discipline |
| 33 | (dormant) | stays dormant |
| 34 | (dormant) | new: Witch Coven (spell-cooldown family, aligned) |

## 4. Power check

| Rank | K laws | A laws | Total cost | Band | OK |
|---|---|---|---|---|---|
| r0 | 3 | 3 | 1+4+3+5+5+4 = 22 | 19-30 | yes |
| r1 | 3 | 3 | 4+4+6+5+4+6 = 29 | 25-33 | yes |
| r2 | 3 | 4 | 2+3+10+5+5+6+4 = 35 | 25-42 | yes |
| r3 | 2 | 3 | 10+5+5+6+6 = 32 | 22-47 | yes |
| r4 | 3 | 3 | 3+4+4+5+8+5 = 29 | 21-44 | yes |

Total laws: 30. Unique-skill (S) laws: 5 (#5 r0, #9 r1, #12 r2, #32 r3, #13 r4). Signature (I) laws: 6 (#7 Swamp Venom, #11 Hunters of the Mire, #26 Poisoned Mire, #21 Tar Pits, #20 Thick Hides, #25 Stagnant Air). Hero primary-stat laws: 1 (Defence). School laws: 1 (Bog Witchcraft). Witch Coven is a cooldown law. Elite laws: 7 (T1 r0, T2 r0, T3 r1, T4 r2, T5 r2, T6 r3, T7 r4); the Basilisk line gets an elite law for the first time.

## 5. Plugin asks

All D laws read the law level through the generic reader (`Homm3CustomFactionLawRuntime`, the side's `dataFractionLaws`). They read it once, when the Fortress side is recorded at BattleLogic.Init (the same place that reads `EnduranceHunting`, :400), into new fields on the side record (next to `EnduranceHunting`, :104). All of them need the skill: at rank 0 there are no pairs.

1. **#5 Beastmaster's Eye (D).** In BuildPairs (:509-510), when `side.BeastmasterEye`, replace both `Shuffle` calls with a stable sort by current total stack Health, descending (count x Health, read like `IsAlive`). Ties break by native pointer order, so the result is deterministic. Pair i with i, as today. The hover blood line (`Homm3FortressPredatorLine.cs`) needs no change.
2. **#9 Scent of Blood (D).** In `DamagePercent` (:270): `var percent = BonusPercentByRank[rank] + pair.Side.ScentBonus;` (10/20). Off-prey penalty stays as it is (it is half the base bonus, not of the raised one). The predator marker's rank text (`PredatorBuffPrefix + rank`, :530) shows the base number. Either add marker variants with the raised value or accept the base text, and state which.
3. **#12 Fresh Quarry (D).** New pass at every RoundStarted after the first, for sides with `FreshQuarry`:
   - For each pair whose prey is dead, find living enemy stacks that are not anyone's prey.
   - Pick the one with the most current total Health (the `bounty` rule's choice; deterministic, not random).
   - Rewrite `pair.Prey` / `PreyKey`, `ByPrey`, and the prey marker buff (remove the old marker, `TryBuff(newPrey, PreyBuffSid, 0, MarkerDuration)`).
   - The off-prey penalty then applies again, while the new prey lives.

   Predators whose prey died and found no new one stay unpaired. Endurance Hunting's ranged rule is unchanged. Intimidation and Frenzy read pairs and need nothing new.
4. **#32 Pack Discipline (D).** In `DamagePercent` (:280): `penalty = PenaltyPercentByRank[r] * (2 - side.PackDiscipline) / 2` with PackDiscipline 1 or 2. That gives half at L1 and 0 at L2.
5. **#13 Pack Kill (D).** In `DamagePercent`, before the off-prey return:
   - when the caster is on a Fortress side with `PackKill`;
   - and `battle.ByPrey[receiverKey]` exists with `pair.Side` equal to the caster's side;
   - and `pair.PredatorKey != casterKey`;

   add +10/+20. A predator hitting another pair's prey still takes its own off-prey penalty, and the two sum. Non-Fortress creatures in a Fortress army also qualify, since the prey belongs to the side. Return through the same owner.
6. **#11 Hunters of the Mire (C).** Rule kind `turn_state`, `fact: "unacted_target"`, percent 10/20, all friendly creatures.
7. **Runtime families to retire for Fortress** (`Homm3CustomLawEffectProfiles.cs`):
   - row 13 "fortress.attack-debuff-on-counterattack" (:1021-1026);
   - morale trigger "fortress.damage-taken-or-slow-poison-momentum" (:1173-1184), since #25 is Stagnant Air;
   - morale package "fortress.damage-taken-slow-poison-package" (:1330-1335), since #22 is dormant;
   - reward profile "fortress.defensive-win-swamp-structure-income" (:1490-1495), since #21 is Tar Pits;
   - formation profiles for 18/19 (`TryGetFormationProfile`, :2055+).

   Check these resolve to exactly the table's native effect:
   - #2 vision (`TryGetVisionProfile`, :2548+);
   - #6 training (hero Defence);
   - #15 school (Nightshade, not Primal);
   - #34 spell cooldown (own heroes -1, `TryGetSpellCooldownProfile`, :2206+).

## 6. Open questions

1. **Deterministic pairing (#5) at r0.** Today pairing is random, which the brief's no-random rule argues against in general. *Recommendation:* keep Beastmaster's Eye as the r0 skill law, and consider making sorted pairing the skill's default in a later pass; the law could then become "you choose the first pair". Until then, 3 law points buys the predictability.
2. **Pack Kill turns the prey into a focus target for the whole army.** That is a strong r4 effect when combined with Scent of Blood. *Recommendation:* keep it at 4/4. It is the Hunter capstone; Pack Discipline at r3 is the Warden counterpart.
3. **Bog Witchcraft school.** The old law raised Primal; Rampart's Druidic Circle also raises Primal. Fortress witches (curses, poison) fit Nightshade. *Recommendation:* Nightshade for Fortress, Primal for Rampart.
4. **Tar Pits and Swamp Venom echo vanilla laws** (Live Roots, the DoT-taken law). These are not Human clones and fit the swamp. *Recommendation:* keep both; the cross-faction review may trim them if another custom tree takes the same.
5. **No flat Morale law.** Fortress loses Cold-Blooded Resolve. *Recommendation:* accept it. Cold-blooded beasts are a poor fit for a Morale bonus, and this spreads Morale +1 thinner across the custom trees.
