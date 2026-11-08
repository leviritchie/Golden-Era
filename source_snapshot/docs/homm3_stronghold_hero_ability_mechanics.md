# HoMM3 Stronghold Hero Ability Mechanics

Generated: 2026-05-02

## Finding

The current `homm3_stronghold` hero specialization text is not a reliable description of runtime behavior.

`generate_homm3_stronghold_heroes.py` clones `DB/heroes_specializations/specializations_dungeon.json`, rewrites `dungeon_hero_N` to `homm3_stronghold_hero_N`, and remaps Dungeon unit SIDs through `UNIT_MAP`. It does not synthesize HoMM3 Stronghold specialization mechanics. Therefore custom `heroInfo.json` text can say "Offense", "Ballista", "Haste", etc. while the engine still executes the cloned Dungeon bonus list.

Do not assume changing `homm3_stronghold_hero_*_spec_description` changes combat or adventure behavior. The authoritative mechanics are the `bonuses` arrays in:

- `DB/heroes_specializations/specializations_homm3_stronghold.json`
- `DB/heroes/homm3_stronghold/homm3_stronghold_hero_*.json` through each hero's `specialization` field
- `DB/heroes_sub_classes/sub_classes_homm3_stronghold.json` for class-level/default bonuses

## Historical Mismatches

Before the 2026-05-02 generator pass, the live `Core.zip` had these mismatches:

| Hero slot | Displayed specialization | Current underlying bonus shape |
|---:|---|---|
| 1 | Offense | Roc creature specialist: `cityUnitsIncrement h3_roc`, Roc speed/initiative/HP, level-scaling Roc stat changes. |
| 2 | Ballista | Space spell replacement and spell-power scaling, not a war-machine/Ballista stat path. |
| 3 | Wolf Riders | Warrior `battleSubskillBonus` chain, not Wolf Rider growth/stat bonuses. |
| 4 | Rocs | Goblin creature specialist. |
| 5 | Chain Lightning | Wolf Rider creature specialist. |
| 7 | Offense | Gemstone income specialist. |
| 8 | Cyclopes | Luck and crit chance specialist. |
| 9 | Wolf Riders | Space school/counter specialist. |
| 12 | Offense | Day spell replacement and spell-power scaling. |
| 13 | Precision | Orc creature specialist. |
| 14 | Haste | Diplomacy/escape specialist. |
| 15 | Logistics | Gold income specialist. |
| 16 | Bloodlust | Cyclops creature specialist. |
| 17 | Gnolls | Day school/counter specialist. |
| 18 | Pathfinding | Night school/counter specialist. |

Slots 6 and 11 happened to line up more closely at a category level (`Ogres` used Ogre creature-specialist bonuses; `Sorcery` used magic attack/damage modifiers), but they still needed parameter review against the intended HoMM3 behavior.

## Current Generator State

`generate_homm3_stronghold_heroes.py` now builds explicit Stronghold specialization `bonuses` instead of keeping cloned Dungeon rows. The live generated `Core.zip` was regenerated and `verify_homm3_stronghold_core_parity.py` passed on 2026-05-02.

| Hero slot | Displayed specialization | Generated mechanic |
|---:|---|---|
| 1 | Offense | Data-only approximation: outgoing basic/melee/ranged/shoot damage modifiers with level scaling. |
| 2 | Ballista | Olden Era approximation: Heroic Strike specialist using the shipped `hero_ability` / `battleSubskillBonus` scaling chain. Starts with `skill_battle_artistry`. |
| 3 | Wolf Riders | Creature specialist for `h3_wolf_rider`, `h3_wolf_rider_upg`, and `h3_wolf_rider_upg_alt`: growth, speed, initiative, HP, level-scaling stats. |
| 4 | Rocs | Creature specialist for `h3_roc`, `h3_roc_upg`, and `h3_roc_upg_alt`. |
| 5 | Chain Lightning | Starts with `primal_12_magic_chain_lightning`; replaces it with `primal_12_magic_chain_lightning_special` and scales spell power. |
| 6 | Ogres | Creature specialist for `h3_ogre`, `h3_ogre_upg`, and `h3_ogre_upg_alt`. |
| 7 | Offense | Same data-only Offense approximation as slot 1. |
| 8 | Cyclopes | Creature specialist for `h3_cyclops`, `h3_cyclops_upg`, and `h3_cyclops_upg_alt`. |
| 9 | Wolf Riders | Same Wolf Rider creature specialist as slot 3. |
| 10 | Sorcery | Data-only spell damage approximation using `magicAttackPerBonus` and enemy-side reduction. |
| 11 | Eagle Eye | Olden Era replacement: scouting/pathfinding specialist using `viewRadius` scaling and `landscapePenaltyPerBonus=-1.0`. Starts with `skill_scouting`. |
| 12 | Offense | Same data-only Offense approximation as slots 1 and 7. |
| 13 | Precision | Starts with `day_4_magic_favorable_wind`; scales that spell with `spellPowerSidSet`. No `_special` magic exists for this shipped spell. |
| 14 | Haste | Starts with `day_3_magic_haste`; replaces it with `day_3_magic_haste_special` and scales spell power. |
| 15 | Logistics | Uses shipped movement bonuses: `movementPerBonus` with level scaling and `roadPerBonus`. |
| 16 | Bloodlust | Starts with `night_3_magic_enlarge_shadow`; scales that spell with `spellPowerSidSet`. No `_special` magic exists for this shipped spell. |
| 17 | Gnolls | Bonus/debug slot mapped to Goblin creature-specialist mechanics because no real Stronghold slot 17 source is present. |
| 18 | Pathfinding | Uses shipped adventure bonuses: `viewRadius` and `landscapePenaltyPerBonus=-1.0`. |

## What It Will Take

1. Keep the explicit HoMM3 Stronghold hero mapping table current.
   - For each `homm3_stronghold_hero_1..18`, record display name, intended HoMM3 specialty, desired Olden Era approximation, and whether it is data-only or C#.
   - Include only the 16 real HoMM3 Stronghold heroes as mechanically authoritative. Treat slots 17-18 as bonus/debug slots unless real source data is chosen.

2. Maintain generated `bonuses` arrays in `generate_homm3_stronghold_heroes.py`.
   - Data-only specialties should use existing engine-recognized bonus types such as `unitStat`, `cityUnitsIncrement`, `heroStat`, `heroStatBattle`, `battleSubskillBonus`, `heroMagicReplace`, `sideRes`, and `heroBattleAbility`.
   - Do not invent new `type` strings in JSON. Unknown bonus types may be ignored or can destabilize loading, depending on the deserializer path.

3. Refine supported Olden Era equivalents for HoMM3 secondary-skill specialties.
   - Offense currently uses broad outgoing damage modifiers. It may later move to a more exact warrior/offense subskill if the corresponding skill/subskill SIDs are identified.
   - Sorcery uses the existing `magicAttackPerBonus`/enemy reduction pattern.
   - Logistics and Pathfinding use shipped hero stat keys, but still need in-game movement measurement.
   - Eagle Eye has no known learn-spell-after-enemy-cast equivalent; it is intentionally replaced with map vision plus terrain penalty removal.

4. Handle spell specialties as spell replacement plus scaling only after confirming matching spell SIDs exist.
   - The cloned Dungeon rows use `heroMagicReplace` and `spellPowerSidSet`; this is a good pattern for Haste/Bloodlust/Precision-style specialty spells if the base/special spell SIDs are correct.
   - If the HoMM3 spell does not exist in Olden Era, either map it to a real OE spell or implement a new spell path in C#.

5. Add C# only for mechanics without a recognized bonus path.
   - Ballista is mapped to Heroic Strike rather than war machines because Olden Era has no Ballista. A true war-machine clone is not planned unless a real Ballista mechanic is added later.
   - Original Eagle Eye spell-learning behavior is intentionally not implemented; it is replaced with a Scouting-style adventure utility specialty.
   - Follow the existing Harmony approach: discover the obfuscated runtime method, guard by hero SID/specialization SID, log through `AgentDebugLog`, and gate risky probes with config.

6. Verify mechanically, not by text.
   - For unit specialists: compare stack stats and city growth with and without the hero.
   - For spell specialists: verify the hero starts with the intended spell and that the effect scales with level.
   - For economy/movement specialists: measure daily resources, movement points, and terrain costs.
   - For battle-only bonuses: compare damage forecast or combat stats in controlled fights.

## Implementation Warning

`specializations_homm3_stronghold.json` is generated output inside `Core.zip`; direct manual edits will be overwritten. Fix `generate_homm3_stronghold_heroes.py`, regenerate, then run `verify_homm3_stronghold_core_parity.py`.

Keep localization changes in sync with mechanics. If the bonus row is not implemented or verified, the hero description should say it is an Olden Era approximation or should be reverted to what the row actually does.

As of 2026-05-03, `generate_homm3_stronghold_heroes.py` owns `STRONGHOLD_HEROINFO_OVERRIDES` for visible specialization names/descriptions plus any hero motto/biography text that would otherwise contradict the borrowed mechanics. This intentionally renames the most misleading borrowed rows in UI text: Gurnisson shows Heroic Strike, Vey shows Pathfinding, Zubin shows Favorable Wind, Saurug shows Enlarge Shadow, and the bonus slot Drakon shows Goblins. The descriptions use static mechanical values instead of LocKit placeholder args because Stronghold-specific `heroInfo` arg rows are not generated. Do not hand-edit only `Lang/*/texts/heroInfo.json`; update the override map and rerun the generator.
