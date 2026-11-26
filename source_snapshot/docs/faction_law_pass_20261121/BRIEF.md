# Faction law pass: design brief (2026-11-21)

This brief is shared by the faction drafting agents. Agents draft law trees only: no code, no edits to `custom_factions/`, `tools/` or the plugin. Nothing is built before the cross-faction review and the owner decisions.

## Owner request (verbatim)

> make sure the laws at each rank are aligned in power level and approximate number and function with vanilla, and make sure they fit the faction identity. Unlike with units, faction laws will always belong to a player with access to heroes of that faction, so they CAN directly interact with the faction unique skill, and some of them should.

Read `BASELINE.md` (this folder) first. It holds the vanilla numbers and the problems with the current trees. The full dump of every vanilla and custom law (rank, column, levels, costs, bonuses) is `V:/olden_port_work/law_pass_20261121/law_dump.txt`. Search it by faction header (`=== human`, `=== homm3_stronghold`, ...).

## Shape of a tree (hard rules)

- **5 ranks.** Unlocks at 0/5/15/30/50 law points. Each rank has a **kingdom** column (economy, hero, magic, map) and an **army** column (creatures). Each column holds **2-4 laws**. The whole tree holds **30-35 laws**.
- **Per-rank total cost** (every level of every law in the rank) stays inside the vanilla band:

  | Rank | Band (total cost) |
  |---|---|
  | r0 | 19-30 |
  | r1 | 25-33 |
  | r2 | 25-42 |
  | r3 | 22-47 |
  | r4 | 21-44 |

  Rank 4 is where vanilla puts its capstones. Do not leave it thin.
- **Law ids** are `fraction_law_homm3_<faction>_<n>` with n in 1..34 (the table has 34 rows). Reuse indices freely. A law that changes meaning keeps or takes any free index. Say which index each law uses. Indices you leave out of the tree become dormant (disabled).
- **Scaffold (keep, as vanilla does):**
  - Resource Riches I/II/III in the kingdom column at r0/r2/r4: 2500+5+5, 5000+10+10, 7500+15+15; cost 1/2/3.
  - Tax Collectors (gold 250/500 at cost 2/2, or vanilla's other shapes) and one "Mining: <resource>" law at r1. The resource is the faction's tier-7 pressure; keep the current one unless it is wrong.
  - **One "Elite <line>" law per creature line (7)**, in the army column of that tier's band: T1 r0, T2 r0-1, T3 r1, T4 r1-2, T5-6 r2-3, T7 r3-4. Growth +4/+4 (T1-2), +2/+2 (T3-4), +1/+1 (T5-7); cost 3 then 2 (a third level costs 1 if you add one). Vanilla elite laws usually carry one rider. A **qualitative rider** that fits the line's kit is better than a flat stat: always max Damage, counterattacks twice, ability does not end the turn, ability cooldown -1, extra Fighting-Style damage. Check the line's current kit in `custom_factions/unit_designs/homm3_<faction>.json` and `docs/unit_ability_pass_20261121/<faction>.md` so the rider builds on it, not on a removed card. Receivers are the three SIDs of the line (base, upg, upg_alt).

## Design rules

1. **Unique-skill laws: 3-5 per faction**, at least one at r0-r1 and one at r3-r4. The vanilla median is 3; Undead has 5 (Animate Dead I-V) and Dungeon 7. These laws change the faction skill's own numbers or rules: stronger, cheaper, new option, wider reach. Read the skill's runtime and docs to find its levers, and name the lever, the file and the constant. A law that only renames a generic effect after the skill ("Warcry Lore" = Day spells) does not count.
2. **No clones of the Human tree.** Defensive Drills, Arcane Exercises, Quartermaster Ledgers, Swift Reflexes, Native Mastery, the melee/ranged formation pair, the Encouragement morale-chance law, and the counterattack doctrine are in many trees today and are Human (or Undead) laws. Use one only if it is unmistakably this faction's, and expect the cross-faction review to keep it for one faction at most.
   - At most **2 hero primary-stat laws** per faction, and not the same pair every faction has.
   - At most **one "learn spells / school level" law** per faction. "Learn any tier" stays a rank-4 capstone, priced as in vanilla.
3. **Identity.** Each tree should have 3-6 signature laws a player would recognise as this faction. Sources:
   - HoMM3 town character (Rampart grove and Dendroid guards, Stronghold barbarian might, Tower wizards and golems, Fortress swamp beasts, ...);
   - the faction's trade axis (`docs/unit_rebalance_plan_20261120.md` section 5);
   - its buildings and economy.

   Kingdom-column signature laws count as much as army ones. Vanilla examples: Woodland Resistance (disguise), Live Roots (no fleeing), Merchants Guild, Natural Selection.
4. **Power band.** Price every law against the nearest anchor in `BASELINE.md` section 3: same rank, same cost per level, same strength. A new effect gets priced by analogy, with one line saying which anchor. Fix the out-of-band values in `BASELINE.md` section 4 in your factions (sight +6 at r0, +200 movement, +10% all damage at r0, Morale +2, ...).
5. **No near-identical laws within a faction.** Two laws that differ only by number or scope are one law too many.
6. **Chance becomes Focus or a fixed rule.** Do not add random procs. Vanilla's per-point Morale/Luck chance modifiers are fine where they fit.
7. **Text.** Vanilla wording: Damage, Attack, Defence, Speed, Initiative, Focus, counterattack, round, "Your heroes", "Friendly creatures", "Enemy creatures". Numbers by level go inline: "+1/+2", "-20%/-40%". No "Core", no implementation terms, no faction-skill internals the player cannot see.

## Toolkit

Build the designed law with the full toolkit. Never shrink a design to fit a donor ("no donor limit"). Plugin rules are invisible to the AI and the forecast. Use native data where it says the thing, and plugin rules where it does not, especially for the unique-skill laws.

**A. Native law bonuses.** Every type below is live in the installed Core. Qualifier keys on a bonus:
- `receivers` (unit SIDs or tier numbers "1".."7");
- `receiverAllegiance` (`ally` / `enemy`);
- `fraction` (faction SID);
- `biomeType: native`;
- `actionArea: allied` (battle in your own area; Demon's "do not control" variant).

Bonus types:
- **Economy:** `sideRes`, `sideOneTimeAddRes`, `sideResHumGraal` (city production), `constructionDiscount`, `constructionDailyLimit`, `unitHiringDiscount`, `unitUpgradingDiscount`, `barrackUnitsIncrementPer`, `barrackUpgradeUnitsHiring`, `cityUnitsIncrement`, `astrologyExp`, `portalSummoningUsageLimit`. `sideStat`: `resPercentIncrementSet`, `cityExpCoef`, `decreaseLawPointsOpenLine`, `disableMarketsExtraCharge`, `heroCostPerBonus`, `magicUpgradeCostPerBonus`, `percentDustForDestroyItem`, `tempMagicLevelBonus`, `unitsFromBarracksIncrementPerBonus`.
- **Map:** `sideObjectViewRadius`. `heroStat`/`heroStatMap`: `viewRadius`, `movementBonus`, `enableSquadCounts`, `enableEnemyHeroInfo`, `enableDisguise`, `diplomacyEfficiencyPerBonus`, `enableImmuneDebufInMap`.
- **Hero:** `offence`, `defence`, `spellPower`, `intelligence`, `moral`, `luck`, `expPerBonus`, `sideExpPerBonus`, `immuneToDebuffs`, `enableBattleOnNativeBiome`.
- **Magic:** `magicSchoolSet <school> <minTier> <levels>`, `magicCdBonus`, `manaBonus`, `manaCostBonus`, `manaRestoreBonusPercent`, `magicAttackPerBonus`, `outComingBuffDuration` / `outComingDebuffDuration`, `magicGuildIncrement`, `magicGuildLearnAdditionMagicAllOpenLevel`.
- **Focus:** `startEnergyLevelsBonus`, `energyLevelsPerRoundBonus`, `maxEnergyLevelsBonus`.
- **Faction resources:** `energyValuesSet`, `necromancyPerBonus`, `fractionEnergyRestoreBonus`.
- **Enemy hero in battle:** `heroStatBattle` with `magicCdBonus`, `magicSchoolSet` (negative), `energyLevelsPerRoundBonus` (negative), `enableBattleEscapeBan`.
- **Creatures** (`unitStat` / `unitBoolStat`):
  - stats: `offence`, `defence`, `hp`, `hpPerc`, `damageMin`, `damageMax`, `speed`, `initiative`, `moral`, `luck`;
  - counters and damage scaling: `numCounters`, `armorPen`, `attackPen`, `crit`, `critChanceModifier`, `additionalActionChanceModifier`, `outAllDmgMod`, `inAllDmgMod`;
  - `modifierSet outDmgMods|inDmgMods <tag>` with tags `melee_attack`, `shoot_attack`, `range_attack`, `basic_attack`, `counter_attack`, `magic_damage`, `overTime_effect`, or an ability tag such as `armed_ability_<unit>`;
  - effect durations: `inComingBuffDuration`, `inComingDebuffDuration`, `outComingBuffDuration`, `outComingDebuffDuration`;
  - abilities and Focus: `abilityCdBonus`, `abilityEnergyLevelsCostBonus`, `energyPerRound`;
  - healing, summoning, vampirism: `finalHealingBonusPercent`, `finalSummonBonusPercent`, `summonDamagePercent`, `vampirismHealMultiplier`;
  - hero-stat transfers: `heroOffenceModifier`, `heroDefenceModifier`, `heroSpellPowerModifier`, `heroIntelligenceModifier`;
  - flags: `alwaysMaxDmg`, `ignoreAbilityActionCost`, `ignoreFractionsCount`.
- **Terrain:** `anyLandEqualNativeLandBonus`.

**B. Law-granted buffs (new build support; vanilla pattern).** `battleSubskillBonus unit_buff <buffSid>` with `receivers` gives those creatures a battle buff (Nature's Elite Fauns, Demon's Fire Larvae laws). The buff can be cloned from any buff in the Core and edited (the unit table's `cloneOf` + `set`). Any native trigger, condition or sequence effect a unit card can use is open to a law this way; the unit pass `BRIEF.md` lists them (`docs/unit_ability_pass_20261121/BRIEF.md`, Toolkit). Name the donor buff and the edits. `side_buff` and `hero_ability` variants also exist.

**C. Law-switched plugin rules (new build support).** A law can switch on any rule kind in `docs/unit_ability_pass_20261121/RUNTIME_CONTRACT.md` for its receivers while the law is owned, at a percent per level. Give the rule kind and its parameters.

**D. Unique-skill levers (new plugin support).** The plugin can read a custom law's level for the hero's side at runtime: `Homm3CustomFactionLawRuntime` already resolves law rank from the side's `dataFractionLaws`, and the pass will add a generic reader. A skill runtime then changes its own numbers or rules by law level. For each D law, give:
- the skill runtime file;
- the constant or branch it changes;
- the value per level;
- for a new rule rather than a number, the hook it needs.

Faction skills and where they live (verify in the repo; these are starting points):

| Faction | Skill | Start here |
|---|---|---|
| Stronghold | Warcry | `Homm3StrongholdWarcryRuntime.cs`, `Homm3StrongholdWarcryCounter.cs` |
| Rampart | Avenger | `Homm3RampartAvenger*Runtime.cs` |
| Fortress | Predator Instinct | `Homm3FortressPredatorInstinct*.cs`, `Homm3FortressPredatorLine.cs` |
| Castle | Elite Strategem | grep `strategem` |
| Inferno | Gating | grep `gating` (Core text and the rebalance plan disagree: find the current rule) |
| Necropolis | Necromancy | grep `necromancy`; vanilla `necromancyPerBonus` / `energyValuesSet` may be native levers |
| Cove | Treasure Hunting | `Homm3CoveTreasure*.cs`, `docs/cove_treasure_hunting_design.md` |
| Factory | Logistics Network | `Homm3FactoryLogistics*.cs`, `custom_factions/factory_logistics/logistics_config.json`, `docs/factory_logistics_network_design.md` |
| Conflux | Elemental Fusion | `Homm3ConfluxFusionRuntime.cs`, `custom_factions/conflux_fusion/` |
| Tower | Artificing | `Homm3TowerArtificing*.cs`, `custom_factions/tower_artificing/`, `docs/homm3_tower_artificing.md` |
| Dungeon | War Captives | `Homm3DungeonCaptivesRuntime.cs` |
| Bulwark | Runes | `Homm3BulwarkRunesRuntime.cs` |

Plugin sources are under `Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/`.

**Existing runtime law families.** Row 13 (counterattack doctrine), formations, morale and similar rows already have per-faction plugin effects (`Homm3CounterattackDoctrineMutationRuntime.cs` header lists them). You may keep one if it is this faction's identity; otherwise replace it. Say which.

## Deliverable: `docs/faction_law_pass_20261121/<faction>.md`, one file per faction

1. **Identity and levers.** Three to six lines on what the faction is about. Then the unique skill's levers you found, each with `file:line`, constant and current value.
2. **Tree.** One table, ordered by rank, kingdom column first:

   | Rank | Col | # | Name | Text (player-facing) | Levels (cost: value) | Build (A/B/C/D + exact bonuses or rule) | Anchor |
   |---|---|---|---|---|---|---|---|

   Mark unique-skill laws **(S)** and signature laws **(I)** in the Name cell.
3. **Removed or changed.** Old index and name → fate (kept / changed / replaced by #n / dormant).
4. **Power check.** Per rank: kingdom and army count, total cost, band. Total laws. Count of (S) laws.
5. **Plugin asks.** Every B, C and D law with what the build needs, precise enough to implement.
6. **Open questions.** Only calls the owner must make; give your recommendation for each.

Keep each file under ~350 lines. Do not edit any other file.
