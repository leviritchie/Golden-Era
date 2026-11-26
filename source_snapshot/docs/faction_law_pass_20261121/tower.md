# Tower (homm3_tower): faction law draft, 2026-11-21

Draft only. Nothing is built.

## 1. Identity and levers

The HoMM3 Tower is the wizards' cloud city: the Library and the Wall of Knowledge, a Golem Factory, Titans on the top floor, and Gems as the tier-7 pressure. The unit trade axis is **Chassis vs Specialist**:
- **Chassis:** multi-hit, ranged or large-HP bodies with a lean kit. Master Gremlin, Elemental Gargoyle, Iron Golem, Battle Mage, Genie Vizier, Naga Rani, Titan.
- **Specialist:** single-hit bodies with a strong kit of control and support. Gremlin Mechanic, Obsidian Gargoyle, Magnetic Golem, Arch Mage, Master Genie, Naga Queen, Colossus.

The faction skill is **Artificing**. It copies enemy passives into a Schematic Book, earns Arcane Essence from victories, and spends essence to graft passives onto Tower lines. The laws should make a Tower player feel like a collector and engineer of borrowed powers. They should also read like the HoMM3 town: knowledge, constructs, Titans.

**Manifest is stale (verified):** `custom_factions/homm3_tower.json:150` still says `"factionSkillName": "Arcane Battery"`. Artificing is live: `custom_factions/tower_artificing/artificing_policy.json` has `enabled: true` and `factionSkillName: "Artificing"`, and `Homm3TowerArtificingCatalog.g.cs:13` has `Enabled = true`. The overlay renames the skill when Artificing is enabled (`tools/release_port/apply_release_core_overlay.py:19178-19181`). Fix the manifest string separately. This draft does not touch it.

Artificing levers. File paths are under `Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/` unless they say otherwise.

| Lever | Where | Current value |
|---|---|---|
| Observation chance per enemy passive, by skill rank | `Homm3TowerArtificingCatalog.g.cs:33` `ObservationChanceByRank`; read in `Homm3TowerArtificingRuntime.cs:1160-1161`; roll at `:1174` (`ObservationRoll`, `:1219`) | 15 / 25 / 35 % |
| Graft slots per line, by rank | `Homm3TowerArtificingCatalog.g.cs:35` `GraftSlotsByRank`; one gate `SlotsForRank` at `Homm3TowerArtificingRuntime.cs:1655-1657`, used by the battle plan (`:353`), `TryGraft` (`:1476`) and the picker (`Homm3TowerArtificingPicker.cs:277,332,452,611`) | 1 / 1 / 2 |
| Ledger slot ceiling | `Homm3TowerArtificingCatalog.g.cs:26` `MaxSlots = 2` (ledger rows exist for 2 slots per line) | 2 |
| Essence per defeated enemy creature, by tier | `Homm3TowerArtificingCatalog.g.cs:37` `EssencePerCreatureByTier`; summed in `SumEssence` `Homm3TowerArtificingRuntime.cs:1332-1362`; awarded at `:1319` | 1, 2, 3, 5, 8, 12, 20 |
| Essence only for the winner | `Homm3TowerArtificingRuntime.cs:1299-1305` (`winnerIndex`) | winner only |
| Essence cap | `Homm3TowerArtificingRuntime.cs:78` `MaxEssence` (16 bits) | 65535 |
| Graft cost matrix `[sourceTier-1, targetTier-1]` | `Homm3TowerArtificingCatalog.g.cs:39-48` `GraftCost`; charged at `Homm3TowerArtificingRuntime.cs:1514`; shown in `Homm3TowerArtificingPicker.cs:652`; formula in policy `graftCost` (base 25, tierWeight 1..7, roundTo 5) | 25 (T1→T1) to 1225 (T7→T7) |
| Replacing a graft | `Homm3TowerArtificingRuntime.cs:1454` (full new cost, no refund), write at `:1524` | no refund |
| One Tower line per schematic | `Homm3TowerArtificingRuntime.cs:1501-1512` | enforced |
| Graft buffs can be purged | policy `graftBuff.canDispel: true`; written by `tools/release_port/homm3_tower_artificing_core_overlay.py:85` | dispellable |
| Round hook already patched (for re-applying grafts) | `Homm3TowerArtificingRuntime.cs:237` `PostfixRoundStarted` | first-round grafts only |
| Law reader | `Homm3CustomFactionLawRuntime.cs:319` `TryResolveActiveKnownCustomLaw` (side `dataFractionLaws`) | family indices only today |

## 2. Tree

Receivers: "line" = base, `_upg` and `_upg_alt`. "All Tower" = all 21 Tower SIDs (the dump shows today's faction-wide rows listing only the 7 base SIDs, `R[7:...]`; the build should list all 21).

| Rank | Col | # | Name | Text (player-facing) | Levels (cost: value) | Build | Anchor |
|---|---|---|---|---|---|---|---|
| r0 | K | 3 | Resource Riches I | Provides 2500 Gold, 5 Wood and 5 Ore when enacted. | 1: once | A scaffold | scaffold |
| r0 | K | 5 | Scrying Lenses **(S)** | Your heroes' Artificing has +5%/+10% chance to record each enemy passive after a battle. | 2: +5 / 2: +10 | D: observation chance + 5 x level (percentage points) | r0 hero utility, 2/level (Sight +1 for 2) |
| r0 | K | 33 | Cloud Observatory | Produces 250/500 Astrology points daily. | 2: 250 / 2: 500 | A `astrologyExp` 250 / 500 | Human 250 for 2; Dungeon 500 for 6. The old third level (750) is cut. |
| r0 | A | 4 | Elite Gremlins | Gremlin growth +4/+8. Gremlins counterattack twice per round. | 3: +4 / 2: +4 | A `cityUnitsIncrement h3_gremlin 4`; `unitStat numCounters 1` (line) | T1 rider "counterattacks twice". Gremlin Mechanic's Sabotage fires on counters. |
| r0 | A | 10 | Elite Gargoyles | Stone Gargoyle growth +4/+8. They gain +2/+4 Defence. | 3 / 2 | A `cityUnitsIncrement h3_gargoyle 4`; `unitStat defence 2/4` (line) | Elite Swordsmen (+2/+4 Defence); fits Perch turns |
| r0 | A | 12 | Overclocked Spellworks | Positive effects on friendly Tower creatures last 1 additional round. | 3: +1 | A `unitStat inComingBuffDuration 1` (all Tower) | Cold Touch r2 4/level covers both directions and every unit; one direction, own faction, at 3 |
| r1 | K | 1 | Tax Collectors | Produces 250/500 Gold daily. | 2 / 2 | A scaffold | scaffold |
| r1 | K | 14 | Mining: Gems | Produces 1/2 Gems daily. | 2 / 2 | A `sideRes gemstones 1/2` | scaffold. **Changed from Crystals:** installed Core Giant costs 1 Gem and Titan / Colossus cost 2 Gems (`DB/units/units_logics/homm3_tower/h3_giant*_l.json`). |
| r1 | K | 6 | Wall of Knowledge **(I)** | Your heroes gain +1/+2/+3 Knowledge. | 2 / 2 / 2 | A `heroStat intelligence 1/2/3` | r1 one primary stat, 2/level +1/2/3. HoMM3 Tower building. |
| r1 | K | 7 | Essence Distillery **(S)** | Your heroes gain +25%/+50% Arcane Essence from won battles. | 3: +25% / 3: +50% | D: essence award x (1 + 0.25 x level) | Animate Dead II (r1, 3 per level, Necromancy Power) |
| r1 | A | 11 | Elite Golems | Stone Golem growth +2/+4. They gain +5/+10 HP, and their healing abilities restore 20%/40% more. | 3 / 2 | A `cityUnitsIncrement h3_golem 2`; `unitStat hp 5/10`; `unitStat finalHealingBonusPercent 0.2/0.4` (line) | T3 +5/+10 HP plus a qualitative rider (Repair) |
| r1 | A | 17 | Elite Mages | Mage growth +2/+4. Their attacks ignore 10%/20% of the target's Defence. | 3 / 2 | A `cityUnitsIncrement h3_mage 2`; `unitStat armorPen 0.10/0.20` (line) | Elite Angels armour pen; HoMM3 Mages ignore walls and obstacles |
| r2 | K | 16 | Resource Riches II | Provides 5000 Gold, 10 Wood and 10 Ore when enacted. | 2: once | A scaffold | scaffold |
| r2 | K | 2 | Library of the Clouds **(I)** | Each time you build a Mage Guild level in a Tower city, 1/2 extra spells are unlocked in the Observatory. | 3: +1 / 3: +2 | A `magicGuildIncrement 1/2`; `magicGuildLearnAdditionMagicAllOpenLevel 1/2` | Nature Forest Magic (r1, 3/3). The old row cost 4/4 at r0. HoMM3 Library. |
| r2 | K | 8 | Twin Grafts **(S)** | Your heroes' Artificing opens the second graft slot on every line at Basic. | 5: on | D: `SlotsForRank` returns max(GraftSlotsByRank[rank], 2) | Live Roots 5 / Terra Mortis 6 (rule-changing single level) |
| r2 | K | 21 | Transmutation Ledger | Your sources of Gold produce +10%/+15%/+20% Gold. | 4 / 2 / 2 | A `sideStat resPercentIncrementSet gold 0.10/0.15/0.20` | Coinage Reform (r2, 4/2/2) |
| r2 | A | 23 | Elite Genies | Genie growth +1/+2. Using their abilities does not end their turn. | 3 / 2 | A `cityUnitsIncrement h3_genie 1`; `unitBoolStat ignoreAbilityActionCost true` (line) | Elite Mancers (T5 rider); Wish and Command are support casts |
| r2 | A | 26 | Golem Factory **(I)** | Gargoyle and Golem lines gain +10% Health and take 10% less basic attack Damage. | 4: on | A `unitStat hpPerc 0.10`; `unitStat modifierSet inDmgMods basic_attack -0.10` (6 SIDs) | Melee formation r2 4/level (±5-10%); two lines only |
| r3 | K | 9 | Warded Grafts **(S)** | Grafts removed from your creatures by enemy effects return at the start of the next round. | 4: on | D: new rule (see section 5) | Spell cooldown -1 (r3, 4); a counterplay softener, not a stat |
| r3 | K | 34 | Wizards' Cadence **(I)** | The cooldowns of all battle spells of your heroes are reduced by 1 round. | 4: -1 | A `heroStat magicCdBonus -1` | Natural Serenity (r3, 4) |
| r3 | K | 15 | Wizards' Patronage | Upgrading Tower creatures costs -10%/-20% Gold. Recruiting upgraded creatures is discounted by the same amount. | 5 / 5 | A `unitUpgradingDiscount gold -0.1/-0.2` | Evolve, Adapt, Overcome (5/5). Chassis or Specialist is an upgrade choice. |
| r3 | A | 24 | Elite Nagas | Naga growth +1/+2. Nagas always deal maximum Damage. | 3 / 2 | A `cityUnitsIncrement h3_naga 1`; `unitBoolStat alwaysMaxDmg true` (line) | Elite Hoplets rider; Nagas strike once and draw no counterattack, so a sure hit matters |
| r3 | A | 13 | Reactive Wards | Your creatures' counterattacks deal +4%/+6% Damage for each point of your hero's Spell Power (at most +60%/+100%). No bonus without a hero. | 3 / 3 | Existing runtime row 13 (`Homm3CounterattackDoctrineMutationRuntime`), kept unchanged | Vengeful Strike (r3, 3/3, +50/+100%). Kept as Tower's version of the doctrine because it scales off Spell Power. |
| r3 | A | 20 | Specialist Arcana **(I)** | The ability cooldowns of Gremlin Mechanics, Obsidian Gargoyles, Magnetic Golems, Arch Mages and Colossi are reduced by 1 round. | 4: -1 | A `unitStat abilityCdBonus -1`, receivers `h3_gremlin_upg_alt, h3_gargoyle_upg, h3_golem_upg_alt, h3_mage_upg, h3_giant_upg_alt` | Elite Scorpions cd -1 is one line's rider for 3+2; five Specialists at r3 for 4 |
| r4 | K | 29 | Resource Riches III | Provides 7500 Gold, 15 Wood and 15 Ore when enacted. | 3: once | A scaffold | scaffold |
| r4 | K | 27 | High Arcana | Your Tower heroes can learn spells of every tier in every school. | 3: on | A `heroStatMap magicSchoolSet day/night/space/primal 5 0` (Power of Faith shape) | Power of Faith (r4, 3), word for word in scope |
| r4 | K | 28 | Grand Schematic **(S)** | Grafting costs your heroes 20%/40% less Arcane Essence. | 3: -20% / 3: -40% | D: graft cost x (1 - 0.2 x level), rounded to 5 | Creature cost -10/-15/-20% (r3, 4/3/3), here on the faction currency |
| r4 | K | 31 | Arcane Battery **(I)** | Your Focus Charge limit increases by 1. | 3: +1 | A `heroStat maxEnergyLevelsBonus 1` | Saturation (r4, 3). Echoes Tower's old faction skill. |
| r4 | A | 30 | Elite Giants | Giant growth +1/+2. They gain +3/+6 Attack and Defence and +1 Speed. | 3 / 2 | A `cityUnitsIncrement h3_giant 1`; `unitStat offence 3/6`, `defence 3/6`, `speed 1` (line) | Elite Cavalry / Cave Dragons (T5-7) |
| r4 | A | 32 | Wards of the Magi | Friendly Tower creatures take 10% less Magic Damage, and negative effects on them last 1 round less. | 5: on | A `unitStat modifierSet inDmgMods magic_damage -0.10`; `unitStat inComingDebuffDuration -1` (all Tower) | Dragon Scales (-15% for 6 at r0) plus a duration half; r4 single level, 5 |

## 3. Removed or changed

| Old # | Old name | Fate |
|---|---|---|
| 1 | Tax Collectors | kept |
| 2 | Observatory Network | changed: renamed **Library of the Clouds**, moved r0 → r2, cost 4/4 → 3/3 |
| 3 | Resource Riches I | kept |
| 4 | Gremlin Muster | changed: **Elite Gremlins**; rider +1/+2 max Damage → counterattacks twice |
| 5 | (dormant) | now **Scrying Lenses (S)** |
| 6 | Arcane Conduits (25% SP/Knowledge → A/D, 6) | replaced by **Wall of Knowledge** (index 6 is the primary-stat family). The 25% transfer was above the vanilla band and is Human's Hero's Blessing. |
| 7 | Defensive Drills | replaced by **Essence Distillery (S)** (Human clone removed) |
| 8 | Arcane Exercises | replaced by **Twin Grafts (S)** (Human clone removed) |
| 9 | Quartermaster Ledgers | replaced by **Warded Grafts (S)**. Knowledge moves to #6 in the vanilla r1 shape. |
| 10 | Stone Gargoyle Muster | changed: **Elite Gargoyles**, +2/+4 Defence |
| 11 | Stone Golem Muster | changed: **Elite Golems**, adds the healing rider |
| 12 | Swift Reflexes | replaced by **Overclocked Spellworks** (moved from #34). Human clone removed. |
| 13 | Reactive Wards | kept (runtime row 13) |
| 14 | Mining: Crystals | changed: **Mining: Gems** (tier-7 cost) |
| 15 | Formula Mastery (mana cost -1/-2/-3) | replaced by **Wizards' Patronage** (Demon's Mana Devour clone removed) |
| 16 | Resource Riches II | kept |
| 17 | Mage Muster | changed: **Elite Mages**, armour-pen rider |
| 18 | Automaton Phalanx (melee formation) | dormant (Human clone) |
| 19 | Automaton Crossfire (ranged formation) | dormant (Human clone) |
| 20 | (dormant) | now **Specialist Arcana** |
| 21 | Transmutation Ledger | changed: 10% single level → 10/15/20% at 4/2/2 |
| 22 | Synchronized Morale (Morale +1/+2) | dormant (Morale +2 is above the band) |
| 23 | Genie Muster | changed: **Elite Genies**, abilities do not end the turn |
| 24 | Naga Muster | changed: **Elite Nagas**, always max Damage; moved to r3 (unchanged rank) |
| 25 | Synchronized Response (Morale trigger) | dormant (Encouragement clone) |
| 26 | Golem Foundries | changed: renamed **Golem Factory**, Gargoyle lines added |
| 27 | High Arcana (Arcane any tier) | changed: every school, Tower heroes (vanilla capstone shape) |
| 28 | Grand Workshop (dust discount) | replaced by **Grand Schematic (S)** (Undead's Forbidden Alchemy clone removed) |
| 29 | Resource Riches III | kept |
| 30 | Giant Muster | changed: **Elite Giants**, +3/+6 A/D and +1 Speed |
| 31 | (dormant) | now **Arcane Battery** |
| 32 | Native Mastery | replaced by **Wards of the Magi** |
| 33 | Celestial Calculus | changed: renamed **Cloud Observatory**, third level removed |
| 34 | Overclocked Spellworks | moved to #12; #34 is now **Wizards' Cadence**, the spell-cooldown family |

Dormant after this pass: 18, 19, 22, 25.

## 4. Power check

| Rank | Kingdom / army | Total cost | Band | OK |
|---|---|---|---|---|
| r0 | 3 / 3 | 1+4+4 + 5+5+3 = **22** | 19-30 | yes |
| r1 | 4 / 2 | 4+4+6+6 + 5+5 = **30** | 25-33 | yes |
| r2 | 4 / 2 | 2+6+5+8 + 5+4 = **30** | 25-42 | yes |
| r3 | 3 / 3 | 4+4+10 + 5+6+4 = **33** | 22-47 | yes |
| r4 | 4 / 2 | 3+3+6+3 + 5+5 = **25** | 21-44 | yes (old r4 was 15) |

- **Totals:** 30 laws, total cost 140.
- **(S) laws:** 5. Scrying Lenses r0, Essence Distillery r1, Twin Grafts r2, Warded Grafts r3, Grand Schematic r4.
- **(I) laws:** 6. Wall of Knowledge, Library of the Clouds, Golem Factory, Wizards' Cadence, Specialist Arcana, Arcane Battery.
- **Hero primary-stat laws:** 1 (Knowledge).
- **Learn / school laws:** 1 (High Arcana). Library of the Clouds adds Mage Guild content. It is not school access.

## 5. Plugin asks

**Generic D reader (all three Tower D laws read it).** `Homm3CustomFactionLawRuntime.TryResolveActiveKnownCustomLaw` (`:319`) only accepts family indices today (`TryGetKnownLawFamily`, `:298`). The pass needs `TryGetCustomLawLevel(object sideOrHero, string factionSid, int index, out int level)`, resolving from the hero's side `dataFractionLaws`. Artificing reads it with the logic hero it already resolves (`ResolveDataHero`). Laws are per player, so the reader must use the hero's owner side, not the battle side, for map-time calls (picker, `TryGraft`).

| # | Law | File / constant | Change per level | Hook |
|---|---|---|---|---|
| 5 | Scrying Lenses | `Homm3TowerArtificingRuntime.cs:1160-1161` (`chance = ObservationChanceByRank[...]`); the picker shows the chance at `Homm3TowerArtificingPicker.cs:323,507` | chance += 5 x level (L2 at Expert: 45%) | existing battle-result prefix; the picker must show the same number |
| 7 | Essence Distillery | `Homm3TowerArtificingRuntime.cs:1319` (the award after `SumEssence`) | essence = floor(essence x (1 + 0.25 x level)), still capped by `MaxEssence` | existing; log the multiplier in the `essence +N` line |
| 8 | Twin Grafts | `SlotsForRank` `Homm3TowerArtificingRuntime.cs:1655-1657` | rank >= 1 and law owned → 2 slots | `SlotsForRank` needs the hero (or law level) as a second argument; all callers listed in section 1. No ledger change (`MaxSlots` stays 2). Unowning the law (it cannot happen in vanilla flow) would leave slot 2 stored and inactive, as a rank drop does today. |
| 9 | Warded Grafts | graft buffs `homm3_tower_graft_{i}` (canDispel true); round hook `Homm3TowerArtificingRuntime.cs:237` | if the law is owned, at each RoundStarted re-add every planned graft buff missing from a living carrier on that side, through `Homm3BuffDebuffNativeAdapter` | **new rule:** extend `PostfixRoundStarted` beyond the first round (it is once-per-battle today, `_firstRoundStarted`) and keep the battle plan per side. Do not re-add if the carrier is dead. Runtime grafts gate on `CarrierStillGrafted`, so they resume with the buff. |
| 28 | Grand Schematic | `Homm3TowerArtificingRuntime.cs:1514` (`cost = GraftCost[...]`); the picker's price pill `Homm3TowerArtificingPicker.cs:652` | cost = round_to(cost x (1 - 0.2 x level), 5), minimum 5 | one helper `EffectiveGraftCost(hero, sourceTier, line)` used by both; the picker's "After grafting" line must use it |

**C / B:** none. Specialist Arcana, Wards of the Magi and the elite riders are native A bonuses.

**Index families (build note).** Index 2 (sight), 15 (school low) and 28 (extra construction) are plugin "known law family" indices (`Homm3CustomFactionLawRuntime.cs:24-38`). This draft gives them non-family meanings (2 already had one). Their family runtimes are packet-gated today (Vision, SpellSchool and Construction runtimes register no hooks), but the build must confirm that no family consumer acts on Tower rows 2, 15 and 28. Index 34 (spell cooldown) now holds the spell-cooldown law, and 13 keeps the counter doctrine.

**Verify before build:**
- `finalHealingBonusPercent` on Elite Golems: confirm it scales heals cast *by* the receiver (Repair), not heals *received*. If it scales received heals, swap the rider to `abilityCdBonus -1` on the Golem line, and drop `h3_golem_upg_alt` from Specialist Arcana so the two don't stack.
- `heroStatMap` on High Arcana restricts the bonus to Tower heroes, as Power of Faith restricts to Temple heroes.

## 6. Open questions

1. **High Arcana scope.** Every school for Tower heroes (vanilla Power of Faith, Human's capstone) or Arcane only (today's row, weaker than vanilla at the same cost)? **Recommend every school.** Tower is HoMM3's spell town, and the cross-faction review should then keep "learn any tier" for Tower and one other faction at most.
2. **Twin Grafts rank.** At r2 (cost 5) a mid-game Tower hero gets Expert's second slot early. The alternative is r3, if the tester finds early double grafts too strong. **Recommend r2.** Grafts cost essence, so the law spends a resource the player has to earn.
3. **Simulated battles.** The Artificing doc leaves open whether auto-resolve earns essence and observations. Essence Distillery and Scrying Lenses multiply whatever that answer is. **Recommend** deciding it before tuning these numbers. No law change either way.
4. **Library of the Clouds overlaps Nature's Forest Magic** (the same native bonus). **Recommend keeping it.** The HoMM3 Library is Tower's most recognisable building.
