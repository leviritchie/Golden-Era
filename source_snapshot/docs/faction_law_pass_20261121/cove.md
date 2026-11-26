# Cove (homm3_cove): faction law draft, 2026-11-21

Draft only. Nothing is built.

## 1. Identity and levers

The HoMM3 Cove (Horn of the Abyss) is a pirate harbour: crews and corsairs, sea witches and nixes, the Sea Serpent at the top, treasure, plunder and grog. Its creatures fight dirty: they hit enemies that have already spent their counterattack, shoot before the enemy acts, and slam targets into walls (Run Aground, Tidebreak). Its economy lives off prize money rather than building.

The faction skill is **Treasure Hunting**. Each region hides a treasure split into map pieces with false leads. Treasure Hunting heroes search a radius around them for pieces, and once they hold enough of the chart they spend movement to dig. The laws should make the hunt faster, surer and richer, and put the whole fleet to work on it.

Treasure Hunting levers. Paths are under `Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/`.

| Lever | Where | Current value |
|---|---|---|
| Search radius for map pieces | `Homm3CoveTreasureRuntime.cs:36` `SearchRadius` | 3 |
| Who searches and collects pieces | `Homm3CoveTreasureRuntime.cs:400-427` `CollectCoveHeroes`; skill gate at `:419` (`if (cached.Rank <= 0) continue;`) | Treasure Hunting heroes only |
| Who digs | `Homm3CoveTreasureRuntime.cs:446` `CheckDig` | Treasure Hunting heroes only |
| False leads shown per region | `Homm3CoveTreasureRuntime.cs:588-593` `LeadCount = Math.Max(1, 1 + Plan.FalseLeads - (pieces - 1))`; `Homm3CoveTreasurePlan.cs:16` `FalseLeads` | 3 |
| Pieces per region | `Homm3CoveTreasurePlan.cs:15` `PiecesPerRegion` | 5 |
| Treasure value | `Homm3CoveTreasurePlan.cs:18-22` `MinValue 4000`, `MaxValue 80000`, `BaseValue 8000`; `:124-135` `AnchorValue 16000`, `ValueFor` | stored per region in the save |
| Contents | `Homm3CoveTreasurePlan.cs` `RollContents` (~`:258`): creatures 1 in 3 (25% of value), artifact 2 in 3 (45%), gold 55-70% of the rest | rolled from its own RNG |
| Dig movement cost | `Homm3CoveTreasureDig.cs:34-35` `MoveNumerator 2`, `MoveDenominator 3`; need at `:141`; `TrySpendAllMovement` at `:149` (movement set to 0) | 2/3 of daily movement, then all of it |
| Payout | `Homm3CoveTreasureDig.cs:219-262` `Pay` (gold `:223`, resources via `Homm3CovePlunderHook.Grant`) | as rolled |
| Subskills | `Homm3CoveTreasureSubskills.cs:36-41` (Archivist, Lay of the Land, Collector of Secrets, Tireless Captain, Ancient Curses); Tireless Captain at `Homm3CoveTreasureDig.cs:136-137` | |
| Law reader | `Homm3CustomFactionLawRuntime.cs` resolves law rank from the side's `dataFractionLaws` | family indices only today |

## 2. Tree

Receivers: "line" = base, `_upg` and `_upg_alt`. "All Cove" = all 21 Cove SIDs.

| Rank | Col | # | Name | Text (player-facing) | Levels (cost: value) | Build | Anchor |
|---|---|---|---|---|---|---|---|
| r0 | K | 3 | Resource Riches I | Provides 2500 Gold, 5 Wood and 5 Ore when enacted. | 1: once | A scaffold | scaffold |
| r0 | K | 5 | Spyglass Watch **(S)** | Your heroes search for treasure map pieces +1/+2 hexes further. | 2: +1 / 2: +2 | D: `SearchRadius` + level | Hero sight r0, 2/level, +1 |
| r0 | K | 7 | Lucky Doubloons | Your heroes gain +1/+2 Luck. | 3: +1 / 3: +2 | A `heroStat luck 1/2` | r0 3/level +1/+2 Luck |
| r0 | K | 8 | Letters of Marque | Hiring heroes costs 25%/50% less Gold. | 2: -25% / 2: -50% | A `sideStat heroCostPerBonus -25/-50` | r0 economy 2/level; a cheap second captain feeds Crew Ashore |
| r0 | A | 4 | Elite Nymphs | Nymph growth +4/+8. The ability cooldowns of Nymphs are reduced by 1 round. | 3: +4 / 2: +4 | A `cityUnitsIncrement h3_nymph 4`; `unitStat abilityCdBonus -1` (line) | T1-2 qualitative rider (cooldown -1). Blink and Riptide are the line's tools. |
| r0 | A | 10 | Elite Crew Mates | Crew Mate growth +4/+8. Crew Mates always deal maximum Damage. | 3 / 2 | A `cityUnitsIncrement h3_crew_mate 4`; `unitBoolStat alwaysMaxDmg true` (line) | T2 rider "always max Damage" (Nature) |
| r1 | K | 1 | Tax Collectors | Produces 250/500 Gold daily. | 2 / 2 | A scaffold | scaffold |
| r1 | K | 14 | Mining: Mercury | Produces 1/2 Mercury daily. | 2 / 2 | A `sideRes mercury 1/2` | scaffold (unchanged resource) |
| r1 | K | 9 | Crew Ashore **(S)** | All your heroes can find and collect treasure map pieces. Only heroes with Treasure Hunting can dig. | 3: on | D: skill gate at `Homm3CoveTreasureRuntime.cs:419` lets rank-0 heroes of this side search and collect | Rule change, single level; Woodland Resistance-style kingdom rule priced like Morale +1 (r1, 3) |
| r1 | K | 22 | Grog Rations | Your heroes gain +1 Morale. | 3: +1 | A `heroStat moral 1` | r1 3 for +1 Morale (old Crew Nerve) |
| r1 | A | 11 | Elite Pirates | Pirate growth +2/+4. Their attacks ignore 10%/20% of the target's Defence. | 3 / 2 | A `cityUnitsIncrement h3_pirate 2`; `unitStat armorPen 0.10/0.20` (line) | Elite armour pen (T5-7 band, pulled down for a duelist line at the low value) |
| r1 | A | 17 | Elite Stormbirds | Stormbird growth +2/+4. They gain +1/+2 Initiative. | 3 / 2 | A `cityUnitsIncrement h3_stormbird 2`; `unitStat initiative 1/2` (line) | T3-4 +2 Initiative |
| r1 | A | 12 | Boarding Actions **(I)** | Friendly Cove creatures deal +10%/+20% melee Damage to enemies that have no counterattack left this round. | 3 / 3 | C `counter_state` state `left0`, attack `melee`, percent 10/20 (all Cove) | Melee formation half (r2, 4/level ±5-10%), one-sided and conditional, so 3 at r1 |
| r2 | K | 16 | Resource Riches II | Provides 5000 Gold, 10 Wood and 10 Ore when enacted. | 2: once | A scaffold | scaffold |
| r2 | K | 21 | Prize Shares | Your sources of Gold produce +10%/+15%/+20% Gold. | 4 / 2 / 2 | A `sideStat resPercentIncrementSet gold 0.10/0.15/0.20` | Coinage Reform (r2, 4/2/2) |
| r2 | K | 20 | Quick Shovels **(S)** | Digging for treasure needs only half of your hero's daily movement. At level 2, digging spends only half of the daily movement and the hero can keep moving. | 3: need 1/2 / 2: spend 1/2 | D: `MoveNumerator/MoveDenominator` 2/3 → 1/2; L2 replaces `TrySpendAllMovement` with a spend of 1/2 | Hero movement r2 5/level; narrower (only on dig days), so 3 + 2 |
| r2 | K | 15 | Navigator's Charts | Space spells of your heroes gain 1 level. | 3: +1 | A `heroStatMap magicSchoolSet space 0 1` | Spell school +1 level (r2, 3). Cove's one school law. |
| r2 | A | 23 | Elite Sea Witches | Sea Witch growth +1/+2. Negative effects they apply last 1 additional round. | 3 / 2 | A `cityUnitsIncrement h3_sea_witch 1`; `unitStat outComingDebuffDuration 1` (line) | T5 qualitative rider; Weakening Shot and Siren Song are debuffs |
| r2 | A | 26 | Broadside **(I)** | Friendly Cove creatures deal +10%/+20% Ranged Damage to enemies that have not acted yet this round. | 3 / 3 | C `turn_state` fact `unacted_target`, attack `ranged`, percent 10/20 (all Cove) | Ranged formation half (r2, 4/level), conditional, 3/level |
| r2 | A | 31 | Keelhaul **(I)** | Friendly Cove creatures deal +10%/+15% Damage to enemies backed against an obstacle, another creature or the battlefield edge. | 3 / 3 | C `wall_slam` percent 10/15 (all Cove) | Same price as Broadside; Run Aground and Tidebreak push targets into walls |
| r3 | K | 32 | Cartographers' Guild **(S)** | Treasure maps show 1/2 fewer possible sites in each region. | 3: -1 / 3: -2 | D: `LeadCount = Math.Max(1, 1 + FalseLeads - level - (pieces - 1))` | Astrology r3 3/level; a map-information law at the r3 price |
| r3 | K | 33 | Star Charts | Produces 500/1000 Astrology points daily. | 3: 500 / 3: 1000 | A `astrologyExp 500/1000` | Astrology r3 3/level 500/1000 (old Storm Omens, moved from r0 to the r3 shape) |
| r3 | A | 24 | Elite Nix | Nix growth +1/+2. Their abilities cost 1 less Focus. | 3 / 2 | A `cityUnitsIncrement h3_nix 1`; `unitStat abilityEnergyLevelsCostBonus -1` (line) | T6 qualitative rider (one line, not Sanctuary's four) |
| r3 | A | 13 | Boarding Hooks **(I)** | Each time a friendly creature counterattacks, your hero gains 1 Focus (at most 5 per battle). | 3: on | Existing runtime row 13 (`Homm3CounterattackDoctrineMutationRuntime`), kept unchanged | Vengeful Strike (r3, 3). Kept as Cove's version of the doctrine: it feeds Focus, not counter Damage. |
| r3 | A | 18 | Powder Kegs **(I)** | The active abilities of friendly Cove creatures deal +15%/+30% Damage. | 3 / 3 | A `unitStat modifierSet outDmgMods armed_ability_<unit> 0.15/0.30`, one entry per Cove ability-holding SID | Dungeon Elite Fighting-Style multipliers (r3-4, 3/level); faction-wide but ability hits only |
| r4 | K | 29 | Resource Riches III | Provides 7500 Gold, 15 Wood and 15 Ore when enacted. | 3: once | A scaffold | scaffold |
| r4 | K | 27 | King's Ransom **(S)** | Treasures your heroes dig up hold +20%/+40%/+60% more Gold and resources. | 3 / 3 / 3 | D: at payout `Homm3CoveTreasureDig.cs:219-262`, gold and resource amounts x (1 + 0.2 x level) | Gold income % (4/2/2 at r2) on a lump-sum source; r4 capstone at 3/level |
| r4 | K | 28 | Smugglers' Tribute | Produces 1 Crystal, 1 Gem and 1 Mercury daily. | 5: on | A `sideRes crystals 1`, `sideRes gemstones 1`, `sideRes mercury 1` | Daily rare resource 2 for 1; three at r4 for 5 |
| r4 | A | 30 | Elite Sea Serpents | Sea Serpent growth +1/+2. They gain +10/+20 maximum Damage. | 3 / 2 | A `cityUnitsIncrement h3_sea_serpent 1`; `unitStat damageMax 10/20` (line) | T5-7 +6 to +20 max Damage |
| r4 | A | 25 | Jolly Roger **(I)** | Enemy creatures have -1 Morale and -1 Luck. | 5: on | A `unitStat moral -1`, `unitStat luck -1`, `receiverAllegiance enemy` | All enemies -1 Initiative and -1 Speed (r4, 5) |

## 3. Removed or changed

| Old # | Old name | Fate |
|---|---|---|
| 1 | Tax Collectors | kept |
| 2 | Sea Charts (sight +1/+2) | dormant. Map vision comes from Spyglass Watch (#5) instead. |
| 3 | Resource Riches I | kept |
| 4 | Nymph Muster (+1/+2 max Damage) | changed: **Elite Nymphs**, ability cooldown -1 |
| 5 | (dormant) | now **Spyglass Watch (S)** |
| 6 | Burning Ash (+10% all Damage, r3) | dormant (above the band; `outAllDmgMod` clone) |
| 7 | Defensive Drills | replaced by **Lucky Doubloons** (Human clone removed) |
| 8 | Arcane Exercises | replaced by **Letters of Marque** (Human clone removed) |
| 9 | Quartermaster Ledgers | replaced by **Crew Ashore (S)** (Human clone removed) |
| 10 | Crew Mate Muster (+1/+2 min Damage) | changed: **Elite Crew Mates**, always max Damage |
| 11 | Pirate Muster (+5/+10 HP) | changed: **Elite Pirates**, armour pen |
| 12 | Swift Reflexes | replaced by **Boarding Actions** (Human clone removed) |
| 13 | Boarding Hooks | kept (runtime row 13), still r3 |
| 14 | Mining: Mercury | kept |
| 15 | Powder Charts ("learn tier 1 Space", data was +1 level) | changed: **Navigator's Charts**, text now matches the data |
| 16 | Resource Riches II | kept |
| 17 | Stormbird Muster (+5/+10 HP) | changed: **Elite Stormbirds**, +1/+2 Initiative |
| 18 | Boarding Parties (melee formation) | replaced by **Powder Kegs** (Human clone removed; index reused, see section 5) |
| 19 | Gun Decks (ranged formation) | dormant (Human clone) |
| 20 | (dormant) | now **Quick Shovels (S)** |
| 21 | Prize Shares | kept |
| 22 | Crew Nerve | changed: renamed **Grog Rations** (same value) |
| 23 | Sea Witch Muster (+2/+4 Attack) | changed: **Elite Sea Witches**, debuff duration +1 |
| 24 | Nix Muster (+2/+4 Attack) | changed: **Elite Nix**, ability Focus cost -1 |
| 25 | Crew Rally (morale trigger per point) | replaced by **Jolly Roger** (Encouragement clone removed) |
| 26 | Tide Discipline (-10% ranged Damage taken, r4) | replaced by **Broadside** |
| 27 | Storm Almanac (learn any tier of Space) | replaced by **King's Ransom (S)**. "Learn any tier" is a Temple-only capstone in vanilla. |
| 28 | Harbor Rush (+1 building daily) | replaced by **Smugglers' Tribute**. Cove is not a builder town (Factory keeps the extra building). |
| 29 | Resource Riches III | kept |
| 30 | Sea Serpent Muster (+5/+10% Damage) | changed: **Elite Sea Serpents**, +10/+20 max Damage |
| 31 | (dormant) | now **Keelhaul** |
| 32 | Native Mastery | replaced by **Cartographers' Guild (S)** |
| 33 | Storm Omens (250/500/750 Astrology, r0) | changed: **Star Charts**, moved to r3, 500/1000 at 3/3 |
| 34 | Reload Drills (incoming buff duration, r0) | dormant (generic; Tower keeps a buff-duration law) |

Dormant after this pass: 2, 6, 19, 34.

## 4. Power check

| Rank | Kingdom / army | Total cost | Band | OK |
|---|---|---|---|---|
| r0 | 4 / 2 | 1+4+6+4 + 5+5 = **25** | 19-30 | yes |
| r1 | 4 / 3 | 4+4+3+3 + 5+5+6 = **30** | 25-33 | yes |
| r2 | 4 / 3 | 2+8+5+3 + 5+6+6 = **35** | 25-42 | yes |
| r3 | 2 / 3 | 6+6 + 5+3+6 = **26** | 22-47 | yes |
| r4 | 3 / 2 | 3+9+5 + 5+5 = **27** | 21-44 | yes (old r4 was thin) |

- **Totals:** 30 laws, total cost 143.
- **(S) laws:** 5. Spyglass Watch r0, Crew Ashore r1, Quick Shovels r2, Cartographers' Guild r3, King's Ransom r4.
- **(I) laws:** 6. Boarding Actions, Broadside, Keelhaul, Boarding Hooks, Powder Kegs, Jolly Roger.
- **Hero primary-stat laws:** 0. Luck and Morale are the hero laws (pirate luck, grog).
- **Learn / school laws:** 1 (Navigator's Charts, Space +1 level). No "learn any tier".

## 5. Plugin asks

**Generic D reader.** All five (S) laws need `TryGetCustomLawLevel(sideOrHero, "homm3_cove", index, out level)` from the hero's owner side `dataFractionLaws` (the reader the pass adds to `Homm3CustomFactionLawRuntime`). Treasure Hunting runs on the map, so it reads the owning player's side, not a battle side.

| # | Law | File / constant | Change per level | Hook |
|---|---|---|---|---|
| 5 | Spyglass Watch | `Homm3CoveTreasureRuntime.cs:36` `SearchRadius` | radius = 3 + level (per hero side) | `SearchRadius` becomes a per-hero lookup wherever the search runs; the map marker / reveal must use the same radius |
| 9 | Crew Ashore | `Homm3CoveTreasureRuntime.cs:419` (`if (cached.Rank <= 0) continue;`) | if law owned, rank-0 heroes of that side stay in `CollectCoveHeroes` for search and pickup | **new rule:** `CheckDig` (`:446`) keeps its rank check, so only Treasure Hunting heroes dig. Subskill effects (Archivist `:300`, Collector of Secrets) still read the hero's own rank, so they stay at 0 for non-hunters. |
| 20 | Quick Shovels | `Homm3CoveTreasureDig.cs:34-35`, `:141` (need), `:149` (`TrySpendAllMovement`) | L1: need = max x 1/2. L2: also spend max x 1/2 instead of all movement | L2 needs a partial-spend helper beside `TrySpendAllMovement`. Tireless Captain (`:136-137`) applies on top as today. |
| 32 | Cartographers' Guild | `Homm3CoveTreasureRuntime.cs:588-593` `LeadCount` | leads = max(1, 1 + FalseLeads - level - (pieces - 1)) | `LeadCount` needs the hero's side; the chart UI already reads `LeadCount` |
| 27 | King's Ransom | `Homm3CoveTreasureDig.cs:219-262` `Pay` (gold at `:223`, resources through `Homm3CovePlunderHook.Grant`) | gold and each resource amount x (1 + 0.2 x level), rounded down | at payout time, not in `RollContents`, because the region value is stored in the save. Creatures and artifacts unchanged. Log the multiplier in the dig line. |

**C laws** (law-switched rules from `RUNTIME_CONTRACT.md`; receivers all 21 Cove SIDs while the law is owned):

| # | Law | Rule |
|---|---|---|
| 12 | Boarding Actions | `counter_state` `{state: "left0", attack: "melee"}`, percent 10 / 20 |
| 26 | Broadside | `turn_state` `{fact: "unacted_target", attack: "ranged"}`, percent 10 / 20 |
| 31 | Keelhaul | `wall_slam` `{}`, percent 10 / 15. Stacks with the Nix alt's own Wall Slam card (percent 50, `abilityOnly`) additively. |

**A with a list:** Powder Kegs (#18) needs one `modifierSet outDmgMods armed_ability_<unit>` entry per Cove SID with a damaging active ability (Riptide, Pistol Shot, Raking Shot, Grappling Hook, Harpoon Break, Tidebreak, Crushing Coils, Whirlpool and the others in `custom_factions/unit_designs/homm3_cove.json`). The generator should read the tags from the unit table, not a hand list.

**Index families (build note).** Index 18 (formation), 25 (morale), 27 (spell school) and 28 (extra construction) are plugin "known law family" indices (`Homm3CustomFactionLawRuntime.cs:24-38`). This draft gives them non-family meanings. The build must retire the Cove profiles for those rows in `Homm3CustomLawEffectProfiles.cs` (Cove block, ~`:996` onward) so no family consumer acts on them. Rows 15 (school), 21 (gold %), 22 (morale), 33 (astrology) and 13 (counter doctrine) keep their family meaning.

**Verify before build:**
- `heroCostPerBonus` sign and unit (percent or fraction) for Letters of Marque.
- `abilityCdBonus -1` on Elite Nymphs: Blink and Riptide already have short cooldowns; confirm the floor is 0, not negative.

## 6. Open questions

1. **Crew Ashore lets heroes without the skill collect pieces.** The design doc ties the hunt to Treasure Hunting heroes. **Recommend allowing collection only** (as drafted): every Cove hero becomes a scout, but digging, curses and subskills stay with the skilled captain.
2. **King's Ransom on top of the doubled treasure values** (base 8000 since 2026-11-17). At L3 a mid-map treasure pays 1.6x its gold and resources. **Recommend keeping it at r4** with 3/3/3; if testers find treasure already generous, cut to +15/+30/+45%.
3. **Boarding Hooks (row 13 counter doctrine) stays for Cove.** The brief keeps the doctrine for one faction at most. **Recommend Cove keeps it**: it is the only version that turns counters into Focus, and Cove's kit trades blows (Scrappers, Duelist, Harpoon Watch). If the cross-faction review gives row 13 to someone else, replace it with a second Treasure law (Tireless Crews: Dig costs no movement once per week).
4. **Quick Shovels L2 lets a hero dig and keep moving.** That removes the "dig ends the day" cost the design doc chose. **Recommend yes at r2 L2** (5 points total): the hunt is the faction's main loop and the cost was there for heroes without laws.
5. **Smugglers' Tribute** gives three rare resources a day for 5. **Recommend keeping it**: Cove has no rare-resource building identity otherwise, and r4 needed weight.
