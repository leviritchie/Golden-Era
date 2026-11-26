# Rampart law tree (draft, 2026-11-21)

## 1. Identity and levers

Rampart is the grove kingdom: elves, dwarves and treefolk guarding a forest, with Unicorns and Pegasi warding off magic and Dragons as its oldest guardians. The faction skill Avenger turns every enemy attack into a punishment: other friendly stacks step in and strike the attacker. The trade axis is Striker (avenging damage, reach, more strikers) against Ward (taking less and holding ground). The tree should feel protective and patient: stand together, answer every blow, and keep magic off the grove.

Avenger levers (`Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/Homm3RampartAvengerStrikeRuntime.cs`):

| Lever | file:line | Constant / branch | Current value |
|---|---|---|---|
| Strikers per enemy attack | :56, :728 | `StrikersByRank` | {0, 1, 2, 3} |
| Striker move | :58, :729 | `MoveHexesByRank` | {0, 0, 1, 2} hexes |
| Order of strikers | :742 | sort by Initiative, descending | highest Initiative first |
| Ranged first strike | :752, :835 | `side.RangedFirst` (Volley of Vengeance pick, :51) | ranged only with the pick, only as the first strike |
| Large stacks | :841 | `moveHexes > 0 && ownHexes.Count == 1` | only single-hex stacks may move in; large stacks strike only when already adjacent |
| Swift Strike | :147, :911 | `_buildingSwift = side.SwiftStrike && _swiftStrikeLive` | with the pick only |
| Retaliation trigger | :53, :460 | `armed.RetaliationTrigger` | with the pick only |
| Derived steps | :953 (QueueStrike :891-960) | avenging steps are marked derived and never chain | — |
| Arming | :303-333 | rank and picks read once per battle | — |
| Avenging damage | none today | avenging strikes are full free default attacks; no percent hook | 100% |

Core overlay mirror: `tools/release_port/homm3_rampart_avenger_core_overlay.py` (`STRIKERS_BY_RANK = (1,2,3)`, `MOVE_HEXES_BY_RANK = (0,1,2)`, `NATIVE_DAMAGE_PERCENT = 10`). Changed numbers need matching law text; the subskill text stays as it is, because the laws add on top.

Existing runtime families on this faction (`Homm3CustomLawEffectProfiles.cs`):
- row 13 counter profile "rampart.avenger-marked-counterattack-damage" (:1033-1038; `Homm3CounterattackDoctrineMutationRuntime.cs:62`, +30%, x2 outnumbered);
- morale trigger "rampart.protect-preserve-avenger-momentum" (:1188-1193);
- morale package "rampart.protect-preserve-avenger-package" (:1343-1348);
- reward and calendar "rampart.low-loss-avenger-tithe" / "rampart.cleanse-regeneration-cycle" (:1505-1510).

Several of these require an Avenger mark, which belongs to the legacy mark runtimes (`Homm3RampartAvengerMarkerRuntime.cs`, `...CastMarkerRuntime.cs`) that the 2026-11-19 strike rework replaced. All of them retire or reduce to their plain native effect (see asks).

## 2. Tree

Index = `fraction_law_homm3_rampart_<#>`. Line SIDs:
- Centaur: h3_centaur, h3_centaur_captain, h3_centaur_ranger_upg_alt
- Dwarf: h3_dwarf, h3_battle_dwarf, h3_dwarf_battlerager_upg_alt
- Wood Elf: h3_wood_elf, h3_grand_elf, h3_elf_wardancer_upg_alt
- Pegasus: h3_pegasus, h3_silver_pegasus, h3_gold_pegasus_upg_alt
- Dendroid: h3_dendroid_guard, h3_dendroid_soldier, h3_dendroid_shaman_upg_alt
- Unicorn: h3_unicorn, h3_war_unicorn, h3_pristine_unicorn_upg_alt
- Dragon: h3_green_dragon, h3_gold_dragon, h3_diamond_dragon_upg_alt

| Rank | Col | # | Name | Text (player-facing) | Levels (cost: value) | Build (A/B/C/D + exact bonuses or rule) | Anchor |
|---|---|---|---|---|---|---|---|
| r0 | K | 3 | Resource Riches I | Provides 2500 Gold, 5 Wood and 5 Ore when enacted. | 1: once | A `sideOneTimeAddRes` 2500/5/5 | scaffold |
| r0 | K | 2 | Ranger Scouts | Your heroes gain +1/+2 sight radius. | 2: +1; 2: +2 | A `heroStat viewRadius 1/2` | Training Scouting (r0, 2 for +1) |
| r0 | K | 5 | Wardens' Oath **(S)** | Avenging strikes deal +10%/+20% Damage. | 2: +10%; 2: +20% | D: damage percent on derived avenging AttackSteps | conditional Att/Def (r0, 2/level) |
| r0 | A | 4 | Elite Centaurs | Centaur growth in your cities increases by +4/+8. They ignore a further 10%/20% of Defence. | 3: +4, 10%; 2: +8, 20% | A `cityUnitsIncrement h3_centaur 4`; `unitStat armorPen 0.10/0.20` R[Centaur line] | elite T1; builds on Hunter's Eye |
| r0 | A | 8 | Elite Dwarves | Dwarf growth in your cities increases by +4/+8. They can counterattack twice. | 3: +4; 2: +8 | A `cityUnitsIncrement h3_dwarf 4`; `unitStat numCounters 1` R[Dwarf line] | elite T2, rider "counterattacks twice" |
| r0 | A | 7 | Unicorn Glade **(I)** | Friendly creatures take -5%/-10%/-15% Damage from spells. | 2: -5%; 2: -10%; 2: -15% | A `unitStat modifierSet inDmgMods magic_damage -0.05/-0.10/-0.15` | magic damage taken (r0, 2/level) |
| r1 | K | 1 | Tax Collectors | Your kingdom gains +250/+500 Gold daily. | 2: 250; 2: 500 | A `sideRes gold` 250/500 | scaffold |
| r1 | K | 14 | Mining: Crystals | Your kingdom gains +1/+2 Crystals daily. | 2: 1; 2: 2 | A `sideRes crystals` 1/2 | scaffold |
| r1 | K | 6 | Druidic Lore | Your heroes gain +1/+2/+3 Knowledge. | 2: +1; 2: +2; 2: +3 | A `heroStat intelligence` 1/2/3 | hero stat (r1, 2/level) |
| r1 | K | 22 | Defender's Grace | Your heroes gain +1 Morale. | 3: +1 | A `heroStat moral 1` | Heroes of Tales (r1, 3) |
| r1 | A | 10 | Elite Wood Elves | Wood Elf growth in your cities increases by +2/+4. Their abilities recover 1 round faster. | 3: +2; 2: +4 | A `cityUnitsIncrement h3_wood_elf 2`; `unitStat abilityCdBonus -1` R[Wood Elf line] | elite T3 (Elite Scorpions rider) |
| r1 | A | 12 | Elite Pegasi | Pegasus growth in your cities increases by +2/+4. They gain +1/+2 Initiative. | 3: +2, +1; 2: +4, +2 | A `cityUnitsIncrement h3_pegasus 2`; `unitStat initiative 1/2` R[Pegasus line] | elite T4 (Elite Ra'Shoth rider) |
| r2 | K | 16 | Resource Riches II | Provides 5000 Gold, 10 Wood and 10 Ore when enacted. | 2: once | A `sideOneTimeAddRes` 5000/10/10 | scaffold |
| r2 | K | 15 | Druidic Circle | Primal spells of your heroes gain +1 level. | 3: +1 | A `heroStat magicSchoolSet primal 0 1` | school +1 level (r2, 3) |
| r2 | K | 21 | Dwarven Treasury **(I)** | Your sources of Gold produce +10%/+15%/+20% Gold. | 4: 10%; 2: 15%; 2: 20% | A `sideStat resPercentIncrementSet gold 0.10/0.15/0.20` | Coinage Reform (r2, 4/2/2) |
| r2 | K | 20 | Treefolk Lumber | Your buildings cost -20%/-40% Wood to construct. | 2: -20%; 2: -40% | A `constructionDiscount wood -0.20/-0.40` | Save the Forests (2/2) |
| r2 | A | 24 | Elite Dendroids | Dendroid growth in your cities increases by +1/+2. Their roots and other debuffs last 1 round longer. | 3: +1; 2: +2 | A `cityUnitsIncrement h3_dendroid_guard 1`; `unitStat outComingDebuffDuration 1` R[Dendroid line] | elite T5, qualitative; builds on Binding |
| r2 | A | 9 | Paths of the Glade **(S)** | Avenging creatures can move 1 more hex to reach the attacker. | 4: +1 hex | D: `MoveHexesByRank[rank] + 1` | Jadame Maps per level (r2, 5) scaled to battle reach |
| r2 | A | 11 | Mighty Oaks **(S)** | Large creatures can also move to make avenging strikes. | 3: on | D: lift the single-hex gate at BuildCandidate | Woodland Resistance-sized rule (r2, 4), narrower |
| r3 | K | 19 | Elven Craftsmanship | Upgrading creatures costs -15%/-30% Gold. | 3: -15%; 3: -30% | A `unitUpgradingDiscount gold -0.15/-0.30` | creature cost (r3, 4/3/3), narrower scope |
| r3 | K | 32 | Sylvan Diplomacy **(I)** | Neutral creatures are +25%/+50% more willing to join your heroes. | 3: 25%; 3: 50% | A `heroStat diplomacyEfficiencyPerBonus 0.25/0.50` | Great Conquest (r3, 2/level), +1 for map value |
| r3 | K | 25 | Mystic Pond **(I)** | Your cities produce +1/+2 Gems and Mercury daily. | 3: +1; 3: +2 | A `sideResHumGraal gems 1/2`; `sideResHumGraal mercury 1/2` | Survival Conditions (3/3, two resources per city) |
| r3 | A | 23 | Elite Unicorns | Unicorn growth in your cities increases by +1/+2. They gain +15/+30 Health. | 3: +1, +15; 2: +2, +30 | A `cityUnitsIncrement h3_unicorn 1`; `unitStat hp 15/30` R[Unicorn line] | elite T6 rider |
| r3 | A | 30 | Call of the Grove **(S)** | One more friendly stack answers each enemy attack with an avenging strike. | 6: +1 | D: `StrikersByRank[rank] + 1` | Tactical Advantage (r2, 6) / +1 counter (r4, 4) |
| r3 | A | 26 | Dendroid Watch **(I)** | Friendly creatures that did not move in their previous action deal +10%/+20% Damage. | 3: +10%; 3: +20% | C `turn_state` fact `stood_ground`, percent 10/20, all friendly | conditional damage (r3, 3/level) |
| r4 | K | 29 | Resource Riches III | Provides 7500 Gold, 15 Wood and 15 Ore when enacted. | 3: once | A `sideOneTimeAddRes` 7500/15/15 | scaffold |
| r4 | K | 13 | Elder's Ward **(S)** | An enemy attack that your creatures avenge deals -10%/-20% Damage. | 4: -10%; 3: -20% | D: incoming percent on the attack that started a chain | ±5% swing (r4, 5), conditional |
| r4 | K | 17 | Pegasus Winds **(I)** | Enemy heroes lose 1 level on all Magic School spells. | 6: -1 | A `heroStatBattle magicSchoolSet day/night/space/primal 0 -1` | Magic Absorption (r4, 6) |
| r4 | A | 31 | Elite Dragons | Dragon growth in your cities increases by +1/+2. They gain +3/+6 Attack and Defence. | 3: +1, +3; 2: +2, +6 | A `cityUnitsIncrement h3_green_dragon 1`; `unitStat offence 3/6`, `defence 3/6` R[Dragon line] | elite T7 rider |
| r4 | A | 18 | Fury of the Glade | Friendly creatures deal +10%/+20% Damage to enemy stacks that damaged your army this round. | 4: +10%; 4: +20% | C `retribution` percent 10/20, all friendly | All +1/+2 Damage (r4, 4/level), conditional |

## 3. Removed or changed

| Old # | Old name | Fate |
|---|---|---|
| 1 | Tax Collectors | kept |
| 2 | Avenger's Trail (sight +2/+4) | changed: Ranger Scouts, +1/+2 (r0 band) |
| 3 | Resource Riches I | kept |
| 4 | Centaur Outriders | changed: Elite Centaurs |
| 5 | Centaur Muster | replaced by #5 Wardens' Oath (growth folded into Elite Centaurs) |
| 6 | Hunter Precision (crit; wrong receiver SIDs) | replaced by #6 Druidic Lore (hero-stat family); the wrong-SID bug goes with it |
| 7 | Defensive Drills | replaced by #7 Unicorn Glade (Human clone) |
| 8 | Arcane Exercises | replaced by #8 Elite Dwarves (Human clone) |
| 9 | Quartermaster Ledgers | replaced by #9 Paths of the Glade (Human clone) |
| 10 | Wood Elf Muster | changed: Elite Wood Elves |
| 11 | Dwarven Bulwarks | replaced by #11 Mighty Oaks (Dwarf identity now in Elite Dwarves) |
| 12 | Swift Reflexes | replaced by #12 Elite Pegasi (Human clone) |
| 13 | Avenger's Reprisal (counter doctrine) | replaced by #13 Elder's Ward; row-13 Rampart counter profile retires |
| 14 | Mining: Crystals | kept |
| 15 | Druidic Ward (debuff duration; wrong SIDs) | replaced by #15 Druidic Circle (school family, aligned) |
| 16 | Resource Riches II | kept |
| 17 | Pegasus Screens (enemy cooldown +1, 4) | changed: #17 Pegasus Winds, enemy schools -1, r4, 6 |
| 18 | Hunter Pairs (melee formation) | replaced by #18 Fury of the Glade (Human formation clone) |
| 19 | Hunter Crossfire (ranged formation) | replaced by #19 Elven Craftsmanship (Human formation clone) |
| 20 | Dwarven Craft (wood -20%, cost 4) | changed: #20 Treefolk Lumber, -20%/-40% at 2/2 |
| 21 | Preservation Tithe (gold +10%, mark-gated) | changed: #21 Dwarven Treasury, 10/15/20% at 4/2/2, no mark gate |
| 22 | Defender's Grace (Morale +1/+2) | changed: Morale +1 only, cost 3 |
| 23 | Unicorn Muster | changed: Elite Unicorns |
| 24 | Dendroid Ramparts | changed: Elite Dendroids |
| 25 | Defender's Exultation (morale trigger) | replaced by #25 Mystic Pond (Encouragement clone) |
| 26 | Elven Volley | replaced by #26 Dendroid Watch |
| 27 | Avenger's Trail (enemy hero info, 3) | dormant |
| 28 | Living Groves (+1 building, 6) | dormant (Architect's Mastery clone) |
| 29 | Resource Riches III | kept |
| 30 | Unicorn Blessings | replaced by #30 Call of the Grove (Unicorn identity in Unicorn Glade and Elite Unicorns) |
| 31 | Dragon Grove | changed: Elite Dragons |
| 32 | (dormant) | new: Sylvan Diplomacy |
| 33, 34 | (dormant) | stay dormant |

## 4. Power check

| Rank | K laws | A laws | Total cost | Band | OK |
|---|---|---|---|---|---|
| r0 | 3 | 3 | 1+4+4+5+5+6 = 25 | 19-30 | yes |
| r1 | 4 | 2 | 4+4+6+3+5+5 = 27 | 25-33 | yes |
| r2 | 4 | 3 | 2+3+8+4+5+4+3 = 29 | 25-42 | yes |
| r3 | 3 | 3 | 6+6+6+5+6+6 = 35 | 22-47 | yes |
| r4 | 3 | 2 | 3+7+6+5+8 = 29 | 21-44 | yes |

Total laws: 30. Unique-skill (S) laws: 5 (#5 r0, #9 r2, #11 r2, #30 r3, #13 r4). Signature (I) laws: 6 (#7, #21, #32, #25, #26, #17). Hero primary-stat laws: 1 (Knowledge). School laws: 1 (Druidic Circle). Pegasus Winds weakens the enemy's spells and is not a learn law. Elite laws: 7 (T1 r0, T2 r0, T3 r1, T4 r1, T5 r2, T6 r3, T7 r4).

## 5. Plugin asks

All D laws read the law level through the generic reader (`Homm3CustomFactionLawRuntime`, the side's `dataFractionLaws`). They read it once, in arming (`Homm3RampartAvengerStrikeRuntime.cs:303-333`), into new fields on the armed-side record (next to `RangedFirst` / `RetaliationTrigger`, :99-101). None of them works without the Avenger skill: at rank 0, `StrikersByRank` is 0 and stays 0.

1. **#5 Wardens' Oath (D, damage).** Add `armed.OathPercent` = 10/20. The damage owner is the single committed-damage prefix in `Homm3CounterattackDoctrineMutationRuntime` (Unit damage prefix; Predator Instinct already contributes through it, ~:586). It adds `OathPercent` when the current AttackStep is a derived avenging step queued by `QueueStrike` (:953 marks it). Expose `Homm3RampartAvengerStrikeRuntime.TryGetAvengingPercent(attackerUnit, out int percent)`, which reads the step queue's current step the way the Focus refusal does (:367-388, :478+). Retaliations against an avenging strike are not derived attacks by the avenger and get nothing.
2. **#9 Paths of the Glade (D).** In `RunChain` (:729): `var moveHexes = MoveHexesByRank[side.Rank] + side.PathsBonus;` with PathsBonus 0/1. At Basic, move becomes 1, so non-adjacent single-hex melee stacks become candidates (BuildCandidate requires `moveHexes > 0`). The return move (Hold the Line, :931-944) needs no change.
3. **#11 Mighty Oaks (D).** BuildCandidate (:841): `return moveHexes > 0 && (ownHexes.Count == 1 || side.MightyOaks) ? candidate : null;`. The approach planner in `RunChain` (:688-796) must find a free two-hex destination next to the attacker for a large stack: both hexes are free, and the path stays within `moveHexes`. If it finds none, the candidate is skipped (fail closed), as today. Large ranged stacks still follow the RangedFirst rule.
4. **#30 Call of the Grove (D).** `RunChain` (:728): `var maxStrikers = StrikersByRank[side.Rank] + side.ExtraStrikers;` with ExtraStrikers 0/1, only when `side.Rank > 0`. Arming log (:331) prints the sum.
5. **#13 Elder's Ward (D, damage taken).** In the AttackStep Begin postfix (~:395-435): when `RunChain` queued at least one striker for this step, record `(attackerKey, targetKey, stepSerial)` in a `[ThreadStatic]` "answered" slot. The damage owner applies `-WardPercent` (10/20) to damage from that attacker to that target while that step is current, and clears the slot when the step ends. Retaliation-triggered chains (Blood for Blood, :437-470) count too: the reduction applies to that retaliation. Derived steps never set the slot.
6. **#26 Dendroid Watch (C).** Rule kind `turn_state`, `fact: "stood_ground"`, percent 10/20, all friendly creatures. Per the contract it is true before a stack's first action, so round one counts for everyone. That is accepted.
7. **#18 Fury of the Glade (C).** Rule kind `retribution`, percent 10/20, all friendly creatures. Avenging strikes qualify by nature (the target just attacked). With Wardens' Oath, the two stack additively.
8. **Runtime families to retire or reduce for Rampart** (`Homm3CustomLawEffectProfiles.cs`):
   - row 13 "rampart.avenger-marked-counterattack-damage" (:1033-1038) retires; #13 is Elder's Ward.
   - morale trigger "rampart.protect-preserve-avenger-momentum" (:1188-1193) retires; #25 is Mystic Pond.
   - formation profiles for 18/19 (`TryGetFormationProfile`, :2055+) retire.
   - morale package "rampart.protect-preserve-avenger-package" (:1343-1348) reduces to plain +1 Morale, with no mark gate.
   - reward profile "rampart.low-loss-avenger-tithe" (:1505-1510) reduces to the plain gold percent, with no mark or low-loss condition.
   - #2 vision, #6 training (Knowledge) and #15 school (Primal) must resolve to exactly the table's native effect.
9. **Overlay.** Text only; no new buffs. The legacy mark runtimes (`Homm3RampartAvengerMarkerRuntime.cs`, `Homm3RampartAvengerCastMarkerRuntime.cs`) are no longer referenced by any law once item 8 lands; flag them for the cleanup pass.

## 6. Open questions

1. **Five skill laws, two of them damage.** Wardens' Oath (avenging strikes deal more) and Elder's Ward (the avenged attack deals less) are the Striker and Ward ends of the same moment, so they are not near-identical. *Recommendation:* keep both. If the review wants four skill laws, cut Mighty Oaks: it matters only for large stacks that are not already adjacent.
2. **Call of the Grove at r3 for 6.** At Expert this makes 4 strikers per enemy attack, and avenging strikes are full free attacks. *Recommendation:* keep it at r3, 6, single level. If playtests show chains wiping stacks, move it to r4, which leaves r3 at 29 and r4 at 35, both in band.
3. **Pegasus Winds copies Undead's Magic Absorption.** *Recommendation:* keep it. HoMM3 Rampart is the anti-magic grove (Unicorn aura, Dwarf resistance, Pegasus Magic Damper), and Undead keeps theirs. If the review gives it to one faction only, Rampart's fallback is "Battle spells of enemy heroes take 1 round longer to recover" (r4, 4).
4. **Morale +1 (#22) in three of my trees.** *Recommendation:* keep Rampart's (Defender's Grace is a HoMM3 Rampart staple), and let the cross-faction review trim duplicates.
5. **Mystic Pond is not random.** The HoMM3 building pays random resources; this pays fixed Gems and Mercury per city, following the no-random-procs rule. *Recommendation:* accept fixed output.
