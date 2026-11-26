# Necropolis (homm3_necropolis): faction law draft, 2026-11-21

Draft only. Nothing is built.

## 1. Identity and levers

The HoMM3 Necropolis is the city of the dead: the Necromancy Amplifier, the Skeleton Transformer, Cover of Darkness and Unearthed Graves, with Mercury as the tier-7 pressure (Bone Dragon line). The unit trade axis is **Reaper vs Gravekeeper**. The faction verb is **the weak die faster** plus a **corpse economy** (Reassemble, Plague, Life Drain overflow, Animate Dead, Death Harvest).

The faction skill is **Necromancy**. After a won battle, a Necropolis hero raises Skeletons worth a share of the eligible enemy losses. The laws should make the hero raise more, raise better, and raise in more places, and should lean on "the weak die faster" in battle.

Levers. Paths are under `Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/` unless they say otherwise.

| Lever | Where | Current value |
|---|---|---|
| Conversion share by rank | `Homm3SkeletalNecromancyProbe.cs:35-37` `BasicConversionPercent 0.05f`, `AdvancedConversionPercent 0.10f`, `ExpertConversionPercent 0.15f` | 5 / 10 / 15 % |
| Rank lookup | `ResolveNecromancyConversionPercent` `:332-345`: reads hero `necromancyPerBonus` only as a **bucket key** (≥0.295 → 15%, ≥0.195 → 10%, ≥0.095 → 5%, else 0). The overlay writes 0.10/0.20/0.30 per skill level (`tools/release_port/apply_release_core_overlay.py:19149-19153`). | buckets |
| Necropolis hero gate | `IsNecropolisHeroSide` `:513-523`: hero sid prefix `homm3_necropolis_hero_` / `hero_homm3_necropolis_`; no hero → false | Necropolis heroes only |
| Battle-end flow | `:200-260`: winner must pass the gate; eligible value summed from losers (`SumEligibleLostSquadValue` `:437`); share; reward unit; `CalculateReward` `:670` = `floor(eligible × pct / rewardSquadValue)` | |
| Reward unit | `ResolveRewardUnitSid` `:317`: Grave Discipline → `h3_skeleton_upg_alt` (`:32`), Bone Tithe → `h3_skeleton_upg` (`:31`), else `h3_skeleton` (`:30`) | base Skeleton below Expert |
| Blocked sources | `GetBlockedHomm3SidReason` `:529-542` (own faction, elementals, golems, gargoyles); `GetBlockedReason` `:544-560` (no-corpse, undead/construct/embodiment tags) | |
| Subskills | overlay `HOMM3_NECROPOLIS_SUBSKILLS_BY_LEVEL` `:7705`, texts ~`:19755` | L2 Gravesoil (native ±10%), Soul Harvest (+4 mana after a victory), Lord of Bones (Skeletons +10% HP); L3 Soul Reaper (enemy -1 Morale and Luck), Bone Tithe, Grave Discipline |
| Law reader | `Homm3CustomFactionLawRuntime.cs:319`; indices limited at `:51` | family indices only |

**Native levers do not reach Necromancy.** `energyValuesSet` (vanilla Animate Dead) is never read by the probe. `necromancyPerBonus` is a bucket key: +0.025 (vanilla Necromancy Power) does nothing, and +0.10 jumps a whole skill rank. No law in this tree writes either stat; every Necromancy law is a D plugin read.

## 2. Tree

Receivers: "line" = base, `_upg` and `_upg_alt`. "All Necropolis" = all 21 Necropolis SIDs.

| Rank | Col | # | Name | Text (player-facing) | Levels (cost: value) | Build | Anchor |
|---|---|---|---|---|---|---|---|
| r0 | K | 3 | Resource Riches I | Provides 2500 Gold, 5 Wood and 5 Ore when enacted. | 1: once | A scaffold | scaffold |
| r0 | K | 7 | Necromancy Amplifier **(S)** | Your heroes' Necromancy raises +2%/+4% more of the fallen. | 3: +2 / 3: +4 | D: pct += 0.02 × level after the bucket lookup (`:332-345`), only when the bucket gave more than 0 | Undead Necromancy Power (+2.5%, 3) and Animate Dead I (r0, 3). HoMM3 building. |
| r0 | K | 31 | Tomb Archives | Your law points gain +10%/+20%/+30%. | 2 / 2 / 2 | A `cityExpCoef` 0.10/0.20/0.30 | Undead law points (r1, 2/2/2, max +30%); was +20/+40/+60% |
| r0 | A | 4 | Elite Skeletons | Skeleton growth +4/+8. They gain +3/+6 Attack. | 3: +4 / 2: +4 | A `cityUnitsIncrement h3_skeleton 4`; `unitStat offence 3/6` (line) | T1-2 rider +3/+6 Attack. Raised Skeletons get it too. |
| r0 | A | 5 | Elite Walking Dead | Walking Dead growth +4/+8. They gain +2/+4 Defence. | 3 / 2 | A `cityUnitsIncrement h3_walking_dead 4`; `unitStat defence 2/4` (line) | T1-2 rider +2/+4 Defence; Disease carriers last longer |
| r1 | K | 1 | Tax Collectors | Produces 250/500 Gold daily. | 2 / 2 | A scaffold | scaffold; moved r0 → r1 |
| r1 | K | 14 | Mining: Mercury | Produces 1/2 Mercury daily. | 2 / 2 | A `sideRes mercury 1/2` | scaffold; moved r2 → r1 |
| r1 | K | 8 | Unearthed Graves **(S)** | Your Necropolis towns raise Skeletons after battles their garrison wins without a hero, at the Basic Necromancy share. | 3: on | D: accept a city or garrison winner with no hero whose owner side holds the law (`:513-523` and the gate at `:200-260`); share 5%; reward to the garrison | small rule change at r1, 3 (Necromancy Power price). HoMM3 dwelling name. |
| r1 | K | 6 | Necromancer's Lore | Your heroes gain +1/+2/+3 Knowledge. | 2 / 2 / 2 | A `heroStat intelligence 1/2/3` | r1 primary stat, 2/level |
| r1 | A | 10 | Elite Wights | Wight growth +2/+4. They gain +2 Initiative. | 3 / 2 | A `cityUnitsIncrement h3_wight 2`; `unitStat initiative 2` (line) | T3-4 rider +2 Initiative; Mana Drain and Wail come sooner |
| r1 | A | 11 | Elite Vampires | Vampire growth +2/+4. Their Life Drain heals 50%/100% more. | 3 / 2 | A `cityUnitsIncrement h3_vampire 2`; `unitStat vampirismHealMultiplier 0.50/1.00` (line) | absorbs Vampiric Nobility (3/3); vanilla vampirism +50% all is r2, 6. Raises more overflow stacks (Vampire Lord). |
| r1 | A | 13 | Death Grip **(I)** | Your creatures' counterattacks heal them by 25% of the damage dealt, raising fallen creatures up to the stack's starting size. | 3: on | existing runtime row 13 (`Homm3CounterattackDoctrineMutationRuntime.cs`), unchanged | counterattack +50% (r3, 3). Necropolis's own doctrine: a corpse effect, not a damage clone. |
| r2 | K | 16 | Resource Riches II | Provides 5000 Gold, 10 Wood and 10 Ore when enacted. | 2: once | A scaffold | scaffold |
| r2 | K | 15 | Dark Liturgy **(I)** | Your heroes gain +1 level in the Night school. | 3: +1 | A `heroStat magicSchoolSet night 0 1` (data unchanged) | vanilla one school +1 level, r2, 3. **Text fixed** (old text said "learn tier 1"). |
| r2 | K | 21 | Mortuary Accounting | Your sources of Gold produce +10%/+15%/+20% Gold. | 4 / 2 / 2 | A `sideStat resPercentIncrementSet gold 0.10/0.15/0.20` | Coinage Reform (r2, 4/2/2); was +10% at 3 on r3 |
| r2 | K | 9 | Skeleton Transformer **(S)** | Below Expert, your heroes' Necromancy raises Skeleton Warriors instead of Skeletons. | 3: on | D: in `ResolveRewardUnitSid` (`:317`), return `h3_skeleton_upg` instead of `h3_skeleton` when the law is owned; the Expert subskills still choose | Natural Selection (r2, 4: upgraded creatures from dwellings); the count is divided by the higher squad value, so 3 |
| r2 | A | 24 | Elite Liches | Lich growth +1/+2. The cooldowns of their abilities are reduced by 1 round. | 3 / 2 | A `cityUnitsIncrement h3_lich 1`; `unitStat abilityCdBonus -1` (line) | Elite Scorpions shape. Corpse Explosion, Bone Cage and Animate Dead are 2/2. |
| r2 | A | 17 | Elite Black Knights | Black Knight growth +1/+2. They gain +3/+6 Attack and Defence and +1 Speed. | 3 / 2 | A `cityUnitsIncrement h3_black_knight 1`; `unitStat offence 3/6`, `defence 3/6`, `speed 1` (line) | T5-7 rider (Elite Cave Dragons). Mark of Death and Death Blow need to reach the target. |
| r2 | A | 26 | Legion Without Banner | Your creatures ignore the Morale penalty for mixing factions. | 4: on | A `unitBoolStat ignoreFractionsCount true` | Death Equalizes All (Undead r1, 4). Raised Skeletons and captured neutrals join a mixed army. |
| r3 | K | 12 | Lords of the Dead **(S)** | Your heroes of other factions also raise Skeletons with Necromancy, at the Basic share. | 5: on | D: in the gate (`:200-260`), a non-Necropolis hero of a side holding the law passes; `ResolveNecromancyConversionPercent` returns 0.05 for it when its bucket is 0 | Terra Mortis (6) / Live Roots (5), rule-changing single level |
| r3 | K | 28 | Reanimated Masonry | You can build one additional building per day in your cities. | 3: on | A extra building per day | vanilla r2, 3 (was 6) |
| r3 | A | 23 | Elite Bone Dragons | Bone Dragon growth +1/+2. They gain +15/+30 HP. | 3 / 2 | A `cityUnitsIncrement h3_bone_dragon 1`; `unitStat hp 15/30` (line) | T5-7 rider +15/+30 HP. Absorbs Dragon Tombs' role. |
| r3 | A | 20 | Deathless Flesh | Friendly creatures take 5%/10%/15% less Magic Damage. | 2 / 2 / 2 | A vanilla magic-damage-taken row | vanilla r0, 2/level; later rank, same price |
| r3 | A | 32 | Endless March | When battling in an area you do not control, friendly creatures gain +1/+2/+3 Attack and Defence. | 2 / 2 / 2 | A Veiled by the Trees shape, foreign-area condition | vanilla conditional A/D, 2/level |
| r4 | K | 29 | Resource Riches III | Provides 7500 Gold, 15 Wood and 15 Ore when enacted. | 3: once | A scaffold | scaffold |
| r4 | K | 27 | High Death Rite | Your heroes can learn Night spells of every tier. | 3: on | A `heroStat magicSchoolSet night 5 0` | Power of Faith (r4, 3); was 4 |
| r4 | K | 30 | Dark Ascension **(S)** | Your heroes' Necromancy also raises Wights worth 5%/10% of the fallen. | 3 / 3 | D: after `CalculateReward` (`:670`), second reward `floor(eligible × 0.05 × level / squadValue(h3_wight))` of `h3_wight` | Animate Dead V / magic damage +10/20/30% (r4, 3/level) |
| r4 | K | 34 | Deathly Silence **(I)** | Enemy heroes lose 1 level in every magic school during battle. | 6: -1 | A `heroStatBattle magicSchoolSet day/night/space/primal 0 -1` (unchanged) | Undead Magic Absorption (r4, 6), same row |
| r4 | A | 25 | Culling **(I)** | Necropolis creatures deal +5%/+10% Damage to enemy stacks below half Health. | 3 / 3 | C: `damage_vs_hp` percent 5/10, `below 50`, all Necropolis (law-gated, section 5) | faction-scoped ±5% swing (r4, 5); conditional, so 3/level |
| r4 | A | 19 | Death's Toll **(I)** | Necropolis creatures deal +3%/+5% Damage for each stack that has fallen in this battle, up to +15%/+25%. | 4 / 4 | C: `death_toll` percent 3/5, cap 15/25, all Necropolis (law-gated) | +1/+2 Damage to all creatures (r4, 4/level) |

## 3. Removed or changed

| Old # | Old name | Fate |
|---|---|---|
| 1 | Tax Collectors (r0) | moved to r1 |
| 2 | Tomb Archives (+20/40/60%) | moved to #31, +10/+20/+30% (band fix). #2 (sight family) dormant. |
| 3 | Resource Riches I | kept |
| 4 | Skeleton Muster | changed: **Elite Skeletons** |
| 5 | Walking Dead Muster | changed: **Elite Walking Dead** |
| 6 | Corpse Wisdom (+10% all damage, r1) | replaced by **Necromancer's Lore** (out of band) |
| 7 | Defensive Drills | replaced by **Necromancy Amplifier (S)** (Human clone removed) |
| 8 | Arcane Exercises | replaced by **Unearthed Graves (S)** (Human clone removed) |
| 9 | Quartermaster Ledgers | replaced by **Skeleton Transformer (S)** (Human clone removed) |
| 10 | Wight Muster | changed: **Elite Wights** |
| 11 | Vampire Muster | changed: **Elite Vampires**, vampirism rider |
| 12 | Swift Reflexes | replaced by **Lords of the Dead (S)** (Human clone removed) |
| 13 | Death Grip | kept |
| 14 | Mining: Mercury | moved r2 → r1 |
| 15 | Death Rite | text fixed (**Dark Liturgy**) |
| 16 | Resource Riches II | kept |
| 17 | Vampiric Nobility | folded into Elite Vampires; #17 is now **Elite Black Knights** |
| 18 | Death March | dormant (formation clone) |
| 19 | Grave Crossfire | replaced by **Death's Toll** (formation clone removed) |
| 20 | Gravesoil (native ±10%) | replaced by **Deathless Flesh** (duplicated the Gravesoil subskill) |
| 21 | Mortuary Accounting | 10/15/20% at 4/2/2, moved r3 → r2 |
| 22 | Legion Without Banner | moved to #26 at r2 (22 is the morale family index) |
| 23 | Bone Dragon Muster | changed: **Elite Bone Dragons** |
| 24 | Lich Reliquaries (shots +10/15%) | replaced by **Elite Liches** (half of a formation clone) |
| 25 | (dormant) | now **Culling** |
| 26 | Dread Aura (enemy -1 Morale and Luck) | replaced by **Legion Without Banner** (duplicated the Soul Reaper subskill) |
| 27 | High Death Rite (4) | cost 3 |
| 28 | Reanimated Masonry (6, r3) | cost 3 |
| 29 | Resource Riches III | kept |
| 30 | Dragon Tombs (Bone Dragons -30% damage taken) | replaced by **Dark Ascension (S)**; the dragon bonus moves into the Elite rider |
| 31 | Bone Veterans (Skeletons +10% HP) | replaced by **Tomb Archives** (duplicated the Lord of Bones subskill) |
| 32 | Native Mastery | replaced by **Endless March** (Human clone removed) |
| 33 | (dormant) | stays dormant |
| 34 | Deathly Silence | kept (r4, 6) |

Dormant after this pass: 2, 18, 22, 33.

## 4. Power check

| Rank | Kingdom / army | Total cost | Band | OK |
|---|---|---|---|---|
| r0 | 3 / 2 | 1+6+6 + 5+5 = **23** | 19-30 | yes |
| r1 | 4 / 3 | 4+4+3+6 + 5+5+3 = **30** | 25-33 | yes |
| r2 | 4 / 3 | 2+3+8+3 + 5+5+4 = **30** | 25-42 | yes |
| r3 | 2 / 3 | 5+3 + 5+6+6 = **25** | 22-47 | yes |
| r4 | 4 / 2 | 3+3+6+6 + 6+8 = **32** | 21-44 | yes (old r4 was 22) |

- **Totals:** 30 laws, total cost 140.
- **(S) laws:** 5. Necromancy Amplifier r0, Unearthed Graves r1, Skeleton Transformer r2, Lords of the Dead r3, Dark Ascension r4.
- **(I) laws:** 5. Death Grip, Dark Liturgy, Deathly Silence, Culling, Death's Toll.
- **Hero primary-stat laws:** 1 (Knowledge). **Learn laws:** 1 (High Death Rite).
- Out-of-band fixes: law points +60% → +30%; +10% all damage at r1 removed; extra building 6 → 3.

## 5. Plugin asks

**Generic D reader.** `TryGetCustomLawLevel(object sideOrHero, string factionSid, int index, out int level)` beside `TryResolveActiveKnownCustomLaw` (`:319`). The probe runs at battle end with `winner` and `winnerStarted` sides; the reader must resolve laws from the winner's owner side, including a hero-less city side (Unearthed Graves).

| # | Law | File / line | Change | Hook |
|---|---|---|---|---|
| 7 | Necromancy Amplifier | `ResolveNecromancyConversionPercent` `:332-345` | pct += 0.02 × level when the bucket is above 0 | existing. Show the real share in the result notification (local player only). |
| 8 | Unearthed Graves | `IsNecropolisHeroSide` `:513-523`, gate `:200-260` | accept a hero-less city or garrison side owned by a holder of the law; share 0.05; add the reward to the garrison | **new:** confirm the reward path can add a stack to a town garrison (today it targets the hero's army). If the garrison is full, merge into an existing Skeleton stack or drop. |
| 9 | Skeleton Transformer | `ResolveRewardUnitSid` `:317` | final fallback `h3_skeleton` → `h3_skeleton_upg` | existing; the subskill branches stay first |
| 12 | Lords of the Dead | gate `:200-260`; `:332-345` | a non-Necropolis hero of a holder side passes; share 0.05 when the bucket is 0. Amplifier and Dark Ascension apply on top | existing flow, new gate branch |
| 30 | Dark Ascension | after `CalculateReward` `:670` | second reward of `h3_wight` at 0.05 × level of the eligible value; same merge rules as Skeletons | **new:** the reward step handles one unit sid today; it needs a second award call |

**C (law-gated runtime rules).** Culling (`damage_vs_hp`) and Death's Toll (`death_toll`) are existing rule kinds in `docs/unit_ability_pass_20261121/RUNTIME_CONTRACT.md`. They must apply to every Necropolis SID while the law is owned. The generator has no law gate today: ask for a `lawGate {faction, index, levels}` field on runtime entries (shared with Inferno's Hellforged). Confirm `death_toll` counts stacks fallen on both sides; the law text says "each stack that has fallen".

**B:** none.

**Index families (build note).** 6 (primary stat), 15 (school low), 21 (gold %), 27 (school high), 28 (extra construction) and 13 (counter doctrine, Necropolis runtime) hold laws of their own family. 34 (spell cooldown) keeps Deathly Silence as today; 19 (ranged formation) now holds Death's Toll and 25 (morale trigger) holds Culling. The build must confirm no family consumer acts on Necropolis rows 19, 25 and 34. `Homm3CustomLawEffectProfiles.cs` has a Necropolis "Dread" profile (enemy morale penalty, never friendly undead morale); confirm its index is now dormant (it belonged to Dread Aura, #26, or the morale family), so it does not attach to Legion Without Banner.

## 6. Open questions

1. **Lords of the Dead reach.** Every hero of the player raises Skeletons at 5%. That makes Necropolis a kingdom-wide skill, close to HoMM3's Necromancy Amplifier feel. **Recommend r3 at 5.** If it is too strong in mixed-faction play, limit it to heroes leading at least one Necropolis stack.
2. **Unearthed Graves without a hero.** Garrison raising needs a new reward target (the town). **Recommend keeping it** but proving the garrison add on a port copy first; fallback is "garrisons with a Necropolis hero visiting", which the current flow already handles, so the law would then shrink to nothing and should be swapped for Cover of Darkness if a lever appears.
3. **Skeleton Transformer vs the Expert subskills.** The law gives Skeleton Warriors at Basic and Advanced; Bone Tithe then only matters as the Warrior pick against Grave Discipline. **Recommend keeping it:** the Expert choice (Warriors or Archers) survives, and the HoMM3 building did the same conversion.
4. **Deathly Silence is a vanilla copy** (Undead Magic Absorption, same row and price). **Recommend keeping it** for Necropolis only; it is the HoMM3 anti-magic undead flavour, and no other custom tree should carry it.
5. **Cover of Darkness.** HoMM3's shroud building has no native law lever. **Recommend leaving it out** until a map-shroud lever exists.
