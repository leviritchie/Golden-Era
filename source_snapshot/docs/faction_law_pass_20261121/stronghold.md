# Stronghold law tree (draft, 2026-11-21)

## 1. Identity and levers

Stronghold is barbarian might on Wasteland: cheap massed bodies early, big brutes late, no patience for magic. The faction skill Warcry rewards an unbroken chain of melee hits and kills by adding Attack to every warcrying stack. The trade axis is Opener (first-round tempo: Goblin Trapper, War Drums, Charge) against Finisher (kill pressure: Blood Rage, Behemoth Rampage). The tree should feel like a warband: hit first, keep the chain going, finish what is wounded, and pay for none of it in magic.

Warcry levers (`Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/Homm3StrongholdWarcryRuntime.cs`):

| Lever | file:line | Constant / branch | Current value |
|---|---|---|---|
| Kill bonus | :57 | `KillBonus` | 5 Attack per kill (with Blood Rush pick) |
| Round Initiative loan | :58, :514-549 | `RoundInitiative` | +2 Initiative next round while the chain is active (Battle Tempo pick) |
| Side state creation | :428-436 | `new WarSide { Rank = Math.Min(3, rank), ... }` | Bonus starts at 0 |
| Battle-end reset | :481 | `state.Side.Bonus = 0` | 0 |
| Counter tick | :801-811 | `ActingShot` branch keeps the chain but does not tick; melee hit on the first target `side.Bonus++` | shots do not tick |
| Break | :962-980 | `Break()` sets `Bonus = 0`, `KillFlat = 0`, clears contributors | full loss |
| Attack formula | :990-992 | `AttackBonus = Bonus * contributors * (Clamp(Rank,1,3)+1)/2 + KillFlat` | multiplier 1 / 1.5 / 2 by rank |
| Who receives the Attack | :902-903 | `amount = bonus > 0 && IsStronghold(unit) ? bonus : 0` | Stronghold creatures only |
| Contributors | :665-717 (`var joined = melee && AddContributor`) | only melee attacks join | melee only |

Core overlay mirror: `tools/release_port/homm3_stronghold_warcry_core_overlay.py` (`KILL_BONUS = 5`, `ROUND_INITIATIVE = 2`, subskill texts). Any number the laws change must also be written into the text the overlay emits.

Existing runtime families on this faction (`Homm3CustomLawEffectProfiles.cs`): row 13 counter profile "stronghold.stacking-damage-buff-on-counterattack" (:1094-1099, Blood Feud, `Homm3CounterattackDoctrineMutationRuntime.cs:61` cap 25%), morale trigger "stronghold.damage-kill-tempo" (:1261-1266), morale package "stronghold.damage-kill-rage-package" (:1411-1416), calendar/reward "stronghold.warcry-festival" / "stronghold.raid-tribute-income" (:1573-1578). Blood Feud is the counterattack doctrine and is retired here; the skill laws replace it.

## 2. Tree

Index = `fraction_law_homm3_stronghold_<#>`.

| Rank | Col | # | Name | Text (player-facing) | Levels (cost: value) | Build (A/B/C/D + exact bonuses or rule) | Anchor |
|---|---|---|---|---|---|---|---|
| r0 | K | 3 | Resource Riches I | Provides 2500 Gold, 5 Wood and 5 Ore when enacted. | 1: once | A `sideOneTimeAddRes` gold 2500, wood 5, ore 5 | scaffold |
| r0 | K | 5 | Drums of Krewlod **(S)** | Your Warcry starts each battle at +1/+2. | 2: +1; 2: +2 | D: Warcry side starts with `Bonus = law level` (see asks) | Focus Reserves (r0, 4 for a battle-start resource) |
| r0 | K | 33 | War Festival | Your kingdom gains +250/+500 Gold at the start of each astrological week. | 2: 250; 2: 500 | A `astrologyExp` gold 250/500 (same build as today, third level removed) | Faith in Magic (r0, 2 for 250) |
| r0 | A | 4 | Elite Goblins | Goblin growth in your cities increases by +4/+8. They always deal maximum Damage. | 3: +4; 2: +8 | A `cityUnitsIncrement h3_goblin 4`; `unitBoolStat alwaysMaxDmg true` R[h3_goblin, h3_goblin_upg, h3_goblin_upg_alt] | elite T1, rider "always max Damage" |
| r0 | A | 10 | Elite Wolf Riders | Wolf Rider growth in your cities increases by +4/+8. They gain +1 Speed, and at level 2 also +1 Initiative. | 3: +4, +1 Speed; 2: +8, +1 Speed, +1 Initiative | A `cityUnitsIncrement h3_wolf_rider 4`; `unitStat speed 1`; L2 `unitStat initiative 1` R[h3_wolf_rider, h3_wolf_rider_upg, h3_wolf_rider_upg_alt] | elite T2 (Elite Cavalry rider) |
| r0 | A | 7 | Charge! **(I)** | Friendly Stronghold creatures gain +1 Speed in the first round of battle. | 3: +1 | B `battleSubskillBonus unit_buff h3_law_stronghold_charge`, clone of `sub_skill_formation_2_buff`, set `speed +1`, `maxDuration 1`; qualifier `fraction homm3_stronghold` | All +1 Speed native (r3, 5) cut to round one |
| r1 | K | 1 | Tax Collectors | Your kingdom gains +250/+500 Gold daily. | 2: 250; 2: 500 | A `sideRes gold` 250/500 | scaffold |
| r1 | K | 14 | Mining: Crystals | Your kingdom gains +1/+2 Crystals daily. | 2: 1; 2: 2 | A `sideRes crystals` 1/2 | scaffold |
| r1 | K | 6 | Hall of Valhalla **(I)** | Your heroes gain +1/+2/+3 Attack. | 2: +1; 2: +2; 2: +3 | A `heroStat offence` 1/2/3 | hero stat (r1, 2/level) |
| r1 | K | 22 | Battle Rage | Your heroes gain +1 Morale. | 3: +1 | A `heroStat moral 1` | Heroes of Tales (r1, 3) |
| r1 | A | 11 | Elite Orcs **(S)** | Orc growth in your cities increases by +2/+4. Their shots also raise your Warcry. | 3: +2; 2: +4 | A `cityUnitsIncrement h3_orc 2` R[h3_orc, h3_orc_upg, h3_orc_upg_alt]; D: an Orc-line shot on the chain's first target ticks the counter like a melee hit | elite T3, qualitative rider |
| r1 | A | 8 | War Paint | Friendly Stronghold creatures gain +1/+2 Attack. | 3: +1; 3: +2 | A `unitStat offence 1/2`, qualifier `fraction homm3_stronghold` | conditional Att/Def (r0-3, 2-3/level) |
| r2 | K | 16 | Resource Riches II | Provides 5000 Gold, 10 Wood and 10 Ore when enacted. | 2: once | A `sideOneTimeAddRes` 5000/10/10 | scaffold |
| r2 | K | 9 | Smouldering Rage **(S)** | When your Warcry is broken, it keeps 25%/50% of its strength. | 3: 25%; 3: 50% | D: `Break()` keeps `floor(Bonus * pct)` instead of 0 | Natural Selection (r2, 4) |
| r2 | K | 17 | Cyclops Quarries | Your buildings cost -20%/-40% Ore to construct. | 2: -20%; 2: -40% | A `constructionDiscount ore -0.20/-0.40` | construction discount (r2, 2-3) |
| r2 | K | 20 | Horde on the March | Your heroes gain +10/+20 Movement points. | 5: +10; 5: +20 | A `heroStat movementBonus 10/20` | movement (r2, 5/level) |
| r2 | A | 23 | Elite Ogres | Ogre growth in your cities increases by +2/+4. Their abilities recover 1 round faster. | 3: +2; 2: +4 | A `cityUnitsIncrement h3_ogre 2`; `unitStat abilityCdBonus -1` R[h3_ogre, h3_ogre_upg, h3_ogre_upg_alt] | elite T4, rider "cooldown -1" |
| r2 | A | 24 | Elite Rocs | Roc growth in your cities increases by +1/+2. Their abilities cost 1 less Focus. | 3: +1; 2: +2 | A `cityUnitsIncrement h3_roc 1`; `unitStat abilityEnergyLevelsCostBonus -1` R[h3_roc, h3_roc_upg, h3_roc_upg_alt] | elite T5, Sanctuary-style rider |
| r2 | A | 12 | Tribes United **(S)** | Creatures of other factions in your armies also gain Attack from your Warcry. | 4: on | D: drop the `IsStronghold(unit)` gate at BeginTurn for owners of this law | Death Equalizes All (r1, 4) |
| r3 | K | 18 | Warlord's Levy | Stronghold creatures cost -10%/-15%/-20% Gold. | 4: -10%; 3: -15%; 3: -20% | A `unitHiringDiscount gold -0.10/-0.15/-0.20`, qualifier `fraction homm3_stronghold` | creature cost (r3, 4/3/3) |
| r3 | K | 21 | Freelancer's Guild **(I)** | Your Marketplaces trade without the extra charge. | 6: on | A `sideStat disableMarketsExtraCharge` | Merchants Guild (r3, 6) |
| r3 | K | 19 | Muster of the Clans | Your external dwellings produce +50%/+100% creatures. | 4: +50%; 4: +100% | A `sideStat unitsFromBarracksIncrementPerBonus 0.5/1.0` | Prosper and Flourish (r3, 4/4) |
| r3 | A | 26 | Elite Cyclopes | Cyclops growth in your cities increases by +1/+2. They gain +3/+6 Attack and Defence. | 3: +1, +3; 2: +2, +6 | A `cityUnitsIncrement h3_cyclops 1`; `unitStat offence 3/6`, `defence 3/6` R[h3_cyclops, h3_cyclops_upg, h3_cyclops_upg_alt] | elite T6 (Elite Cavalry rider) |
| r3 | A | 31 | Gang Up **(I)** | Friendly Stronghold creatures deal +10% Damage to enemies that stand next to another friendly stack. | 4: +10% | C `adjacency` mode `flank`, percent 10, receivers: faction homm3_stronghold | conditional damage (r3, 3-4) |
| r3 | A | 32 | Smell of Blood **(I)** | Friendly Stronghold creatures deal +3% Damage for each stack that has fallen this battle, up to +15%. | 4: on | C `death_toll` percent 3, cap 15, receivers: faction homm3_stronghold | Vengeful Strike (r3, 3/3) |
| r4 | K | 29 | Resource Riches III | Provides 7500 Gold, 15 Wood and 15 Ore when enacted. | 3: once | A `sideOneTimeAddRes` 7500/15/15 | scaffold |
| r4 | K | 13 | Unending Warcry **(S)** | Your Warcry grants 50% more Attack. | 5: on | D: multiplier term `(Clamp(Rank,1,3)+1)` becomes `(Clamp(Rank,1,3)+2)` | ±5% swing (r4, 5) |
| r4 | K | 34 | Spellbreaker Chants **(I)** | Battle spells of enemy heroes take 1 round longer to recover. | 4: +1 | A `heroStatBattle magicCdBonus 1` (enemy hero) | Absolute Zero (r3, 3), +1 for r4 |
| r4 | A | 30 | Elite Behemoths | Behemoth growth in your cities increases by +1/+2. They ignore a further 10%/20% of Defence. | 3: +1, 10%; 2: +2, 20% | A `cityUnitsIncrement h3_behemoth 1`; `unitStat armorPen 0.10/0.20` R[h3_behemoth, h3_behemoth_upg, h3_behemoth_upg_alt] | Elite Angels rider |
| r4 | A | 25 | No Mercy | Friendly creatures deal +10%/+20% Damage to enemy stacks below half Health. | 3: +10%; 3: +20% | C `damage_vs_hp` below 50, percent 10/20, all friendly receivers | All +1/+2 Damage (r4, 4/level), conditional |

## 3. Removed or changed

| Old # | Old name | Fate |
|---|---|---|
| 1 | Tax Collectors | kept |
| 2 | War Beacons (sight 2/4/6) | dormant (sight +6 at r0 is out of band; Stronghold does not need a scouting law) |
| 3 | Resource Riches I | kept |
| 4 | Goblin Muster | changed: Elite Goblins (takes Goblin Mob Rule's always-max-Damage rider) |
| 5 | Goblin Pressgang (hiring -10%, r0, cost 4) | replaced by #5 Drums of Krewlod |
| 6 | Berserker Charge (+1 Speed all, r0, 3) | idea moved to #7 Charge! (first round only); index 6 now Hall of Valhalla (hero-stat family) |
| 7 | Defensive Drills | replaced by #7 Charge! (Human clone) |
| 8 | Arcane Exercises | replaced by #8 War Paint (Human clone) |
| 9 | Quartermaster Ledgers | replaced by #9 Smouldering Rage (Human clone) |
| 10 | Wolf Rider Muster | changed: Elite Wolf Riders |
| 11 | Orc Muster | changed: Elite Orcs (S) |
| 12 | Swift Reflexes | replaced by #12 Tribes United (Human clone) |
| 13 | Blood Feud (counter doctrine) | replaced by #13 Unending Warcry; the row-13 Stronghold counter profile retires |
| 14 | Mining: Crystals | kept |
| 15 | Warcry Lore (Day spells) | dormant (renamed generic school law; does not touch Warcry) |
| 16 | Resource Riches II | kept |
| 17 | Raider Momentum | replaced by #17 Cyclops Quarries |
| 18 | Warband Crush (formation) | replaced by #18 Warlord's Levy (Human formation clone) |
| 19 | Rage Momentum | replaced by #19 Muster of the Clans |
| 20 | Orcish Ballistics | replaced by #20 Horde on the March (Orc rider now in Elite Orcs) |
| 21 | Spoils Ledger | replaced by #21 Freelancer's Guild |
| 22 | Battle Rage (Morale +1/+2) | changed: Morale +1 only, cost 3 (Morale +2 out of band) |
| 23 | Ogre Taskmasters | changed: Elite Ogres |
| 24 | Roc Stormsigns | changed: Elite Rocs |
| 25 | Raucous Rage (morale trigger) | replaced by #25 No Mercy (Encouragement clone) |
| 26 | Cyclops Masonry | changed: Elite Cyclopes |
| 27 | High Warcry Lore (any-tier school) | dormant (no school law in this tree) |
| 28 | Warcamp Raising (+1 building, r4, 5) | dormant (Architect's Mastery clone) |
| 29 | Resource Riches III | kept |
| 30 | Behemoth Dominion | changed: Elite Behemoths |
| 31 | Goblin Mob Rule (always max Damage) | replaced by #31 Gang Up; rider moved to Elite Goblins |
| 32 | Native Mastery | replaced by #32 Smell of Blood (Human clone) |
| 33 | War Festival (astrology 250/500/750) | changed: 250/500 at 2/2 |
| 34 | Spellbreaker Chants | kept, r4, cost 4 |

## 4. Power check

| Rank | K laws | A laws | Total cost | Band | OK |
|---|---|---|---|---|---|
| r0 | 3 | 3 | 1+4+4+5+5+3 = 22 | 19-30 | yes |
| r1 | 4 | 2 | 4+4+6+3+5+6 = 28 | 25-33 | yes |
| r2 | 4 | 3 | 2+6+4+10+5+5+4 = 36 | 25-42 | yes |
| r3 | 3 | 3 | 10+6+8+5+4+4 = 37 | 22-47 | yes |
| r4 | 3 | 2 | 3+5+4+5+6 = 23 | 21-44 | yes |

Total laws: 30. Unique-skill (S) laws: 5 (#5 r0, #11 r1, #9 r2, #12 r2, #13 r4). Signature (I) laws: 6 (#7 Charge!, #6 Hall of Valhalla, #21 Freelancer's Guild, #31 Gang Up, #32 Smell of Blood, #34 Spellbreaker Chants). Hero primary-stat laws: 1 (Attack). School laws: 0. Elite laws: 7, one per line, in band (T1 r0, T2 r0, T3 r1, T4 r2, T5 r2, T6 r3, T7 r4).

## 5. Plugin asks

All D laws need the generic law-level reader the pass adds (`Homm3CustomFactionLawRuntime`, resolved from the hero side's `dataFractionLaws`). Each D law reads its level once when the Warcry side is created (`Homm3StrongholdWarcryRuntime.cs:428-436`) and stores it on `WarSide`; levels do not change mid-battle. Each changed number must also change the subskill or law text the Core overlay emits.

1. **#5 Drums of Krewlod (D).** Add `WarSide.DrumsStart` = law level (0/1/2). At side creation set `Bonus = DrumsStart`. `Break()` (:962-980) and the battle-end reset (:481) are unchanged: a broken chain returns to 0 (or to Smouldering's share), not to the Drums value. Contributors start empty, so the starting counter turns into Attack only when the first stack joins with a melee attack. That keeps it an opener, not a free buff. Log it in the existing armed line (:445).
2. **#11 Elite Orcs rider (D).** In `PostfixObjectTookDamage`, in the `ActingShot` branch (:801-807): when the acting unit's SID is in {h3_orc, h3_orc_upg, h3_orc_upg_alt}, the law is owned, and the target is the chain's first target, do what the melee path does at :809-811 (`Bonus++` once per action, using the same `HitTicks` guard). Also let that shot add the Orc as a contributor (`AddContributor`, today melee-only at :665-717). Other shooters keep the 2026-11-18 rule: shots keep the chain but do not tick it.
3. **#9 Smouldering Rage (D).** In `Break()`: `var keep = side.SmoulderPct > 0 ? side.Bonus * side.SmoulderPct / 100 : 0;` then `side.Bonus = keep` (25 or 50). `KillFlat` and contributors still clear. A wait/skip break (:635-662) and a move-without-attack break (:590-633) both go through `Break()`, so both keep the share. The battle-end reset at :481 stays 0.
4. **#12 Tribes United (D).** BeginTurn (:902-903): `amount = bonus > 0 && (IsStronghold(unit) || side.TribesUnited) ? bonus : 0`. The round-end Initiative loan (:533) keeps its `IsStronghold` gate. The law widens who receives the Attack; Battle Tempo stays a Stronghold-only perk. Non-Stronghold melee stacks also become contributors: check `AddContributor` callers for a faction gate and lift it under the same flag.
5. **#13 Unending Warcry (D).** `AttackBonus` (:990-992): `side.Bonus * CountContributors(side) * (Math.Clamp(side.Rank, 1, 3) + 1 + side.Unending) / 2 + side.KillFlat`, where `Unending` is 0 or 1. Multipliers become 1.5/2/2.5. Integer division stays as it is (round down).
6. **#7 Charge! (B).** New buff `h3_law_stronghold_charge`: `cloneOf sub_skill_formation_2_buff`, set the stat line to `speed +1`, `maxDuration 1`, applied at battle start. Law bonus: `battleSubskillBonus unit_buff h3_law_stronghold_charge`, `fraction homm3_stronghold`. If the donor's trigger is not battle start, use any start-of-battle buff donor (War Drums' first-round buff on Ogre Mage is the kit precedent) and give the donor SID in the build.
7. **#31 Gang Up (C).** Rule kind `adjacency`, `mode: "flank"`, percent 10, receivers: units whose faction is homm3_stronghold. The Wolf Rider's Pack Hunt (+20% flank) stacks additively with it; that is intended.
8. **#32 Smell of Blood (C).** Rule kind `death_toll`, percent 3, cap 15, same receivers. "Stack fallen" counts stacks of both sides, as the contract defines.
9. **#25 No Mercy (C).** Rule kind `damage_vs_hp`, `below: 50`, percent 10 (L1) / 20 (L2), all friendly creatures.
10. **Runtime families to retire for Stronghold** (`Homm3CustomLawEffectProfiles.cs`):
    - row 13 counter profile (:1094-1099), since #13 is now Unending Warcry;
    - morale-trigger profile at 25 (`TryGetMoraleTriggerProfile`, :1111+), since #25 is now No Mercy;
    - reward-economy profile at 21 (`TryGetRewardEconomyProfile`, :1430+, non-calendar branch "stronghold.raid-tribute-income" :1573-1578), since #21 is now Freelancer's Guild;
    - formation profile at 18/19 (`TryGetFormationProfile`, :2055+), since both are economy laws now.

    Check these keep their meaning:
    - #6 hero-stat training family (:1910+): it must resolve to hero Attack.
    - #22 morale package: it must be plain +1 Morale, with no extra kill-tempo rider.
    - #33 calendar "stronghold.warcry-festival": it must pay the astrology gold only.
    - #34 spell-cooldown family (:2206+): it must be enemy +1.

    Where a profile adds more than the law text says, remove the extra.

## 6. Open questions

1. **Orc shots ticking the Warcry (#11).** On 2026-11-18 the owner ruled that shots keep the chain but do not tick it. Elite Orcs makes an exception for one line, behind a law. *Recommendation:* allow it. It is a paid r1 law, limited to one line, and it gives the Orc a Stronghold reason to exist beside the melee chain. Fallback if refused: the rider becomes +3/+6 Attack.
2. **Five skill laws.** The brief allows 3-5; the vanilla median is 3. *Recommendation:* keep all five. Each changes a different part of Warcry: start, break, reach, multiplier and one line's role. If the review wants four, cut Smouldering Rage, which overlaps most with Drums.
3. **Tribes United opens Warcry to mixed armies.** Today Warcry is Stronghold-only by design. *Recommendation:* allow it at r2 for 4. Death Equalizes All is the vanilla precedent, and it does not touch the Initiative loan.
4. **Battle Rage stays at index 22 as plain Morale +1.** Every faction risks a Morale +1 law. *Recommendation:* keep it for Stronghold, which in HoMM3 is the morale-and-might town; let the cross-faction review cut it elsewhere first.
5. **Spellbreaker Chants vs other factions' enemy-cooldown laws.** *Recommendation:* keep it in Stronghold, the anti-magic town in HoMM3. If the review gives it to another faction, replace it with enemy Focus -1 per round (r4, 4).
