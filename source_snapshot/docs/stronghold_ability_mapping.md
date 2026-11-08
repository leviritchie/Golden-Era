# Stronghold Unit Ability Mapping Audit

Generated: 2026-05-02

This is an audit of three different things that had drifted together:

- **HoMM3 canonical Stronghold**: the Restoration of Erathia / Armageddon's Blade / Shadow of Death creature behavior.
- **Tears of Ashan alternate upgrades**: the VCMI `tears-of-ashan` mod's actual Stronghold creature JSON.
- **Current Olden Era implementation**: what the local generated `Core.zip` currently gives to `homm3_stronghold` units.

The previous version of this document mixed planned abilities, donor mechanics, and hallucinated Tears of Ashan concepts. Treat this table as the source of truth for cleanup.

## Key Findings

The current alternate-upgrade names in `generate_homm3_stronghold_city.py` are not the Tears of Ashan names.

Visible custom Stronghold creature rows should always carry explicit vanilla donor `AbilityViewConfig.icon` keys. Without an icon key, runtime wrappers can fall back to `objects/test_images/padlock` or placeholder art even when the ability mechanics and text are otherwise present. The current generator uses these donor icons: Double Attack -> `pet_blood_icon`, Bloodlust -> `magic_sharp_edge_effect_icon`, Frenzied Charge -> `minos_buff_icon`, Return After Strike -> `assassin_buff_icon`, Lightning Strike -> `primal_1_magic_thunderbolt`, Ferocity -> `dragon_hunter_blood_icon`, No Distance Penalty -> `crossbowman_buff_icon`, and Behemoth defense reduction -> `sub_skill_units_attackPen_icon`.

Runtime note: these donor keys also need the narrow loaded-sprite allowlist in `Homm3CustomUiIconHook`. A log line such as `icon=primal_1_magic_thunderbolt` only proves the data row is correct; if no `loaded vanilla sprite fallback key='primal_1_magic_thunderbolt'` line appears, the UI can still render the orange placeholder.

| Current OE SID | Current OE display name | Tears of Ashan source name |
|---|---:|---|
| `h3_goblin_upg_alt` | Hobgoblin Veteran | Goblin Trapper |
| `h3_wolf_rider_upg_alt` | Wolf Raider Veteran | Boar Rider |
| `h3_orc_upg_alt` | Orc Warlord | Orc Berserker |
| `h3_ogre_upg_alt` | Ogre Warlord | Ogre Brute |
| `h3_roc_upg_alt` | Stormbird | Shahrokh |
| `h3_cyclops_upg_alt` | Cyclops Warlord | Blood-Eyed Cyclops |
| `h3_behemoth_upg_alt` | Dire Behemoth | Ghost Behemoth |

Several old planned abilities are not grounded in either HoMM3 or the ToA JSON used as source:

| Old local concept | Problem |
|---|---|
| Toxic Spit / Scavenger | Not in ToA Stronghold JSON. ToA Goblin Trapper casts Land Mine. |
| Wolf Pack / Howl / Savage Leap | Not in ToA Stronghold JSON. ToA tier 2 alternate is Boar Rider with Jousting. |
| Axe Throw / Battle Cry / Rage | ToA Orc Berserker has Berserk-after-attack chance and Return After Strike. |
| Ogre Smash / Blood Magic | ToA Ogre Brute has Frenzy-before-attack chance. |
| Wing Gust / Thunderstorm / Static Field | ToA Shahrokh flies and has Ferocity; HoMM3 Thunderbird has Lightning Strike. |
| Earthquake / One-Eyed Gaze | ToA Blood-Eyed Cyclops is a no-range-penalty/no-wall-penalty shooter. |
| Rampage / Fear Aura / Berserker Rage | ToA Ghost Behemoth flies and reduces enemy Defense by 60%. |

## Alignment Table

| Tier | OE SID | HoMM3 unit basis and real specials | ToA alternate basis and real specials | Current OE behavior in generated Core.zip | Cleanup direction |
|---:|---|---|---|---|---|
| 1 | `h3_goblin` | Goblin: no special ability. | N/A, base unit. | Melee only; no visible ability/passive circles. | Done for data-only cleanup. |
| 1 | `h3_goblin_upg` | Hobgoblin: no special ability. | N/A, normal upgrade. | Stronger melee upgrade: +2 Offense over Goblin and visible `Alert I` for two counterattacks per round. | Done for data-only cleanup. |
| 1 | `h3_goblin_upg_alt` | N/A in HoMM3. | Goblin Trapper: `SPELLCASTER` Land Mine, 1 cast, 5% Land Mine power. | Goblin Trapper has a 1-Focus `Land Mine` active using OE's native trap-spawn mechanic; current implementation places a hidden snare trap rather than a damage-scaling HoMM3 mine. It has normal one-counter behavior. | Implemented as a grounded first pass; revisit if a closer damage-only mine schema is found. |
| 2 | `h3_wolf_rider` | Wolf Rider: no special ability. | N/A, base unit. | Melee only; no visible ability/passive circles. | Done for data-only cleanup. |
| 2 | `h3_wolf_rider_upg` | Wolf Raider: double attack. | N/A, normal upgrade. | Melee with visible `Double Attack`; implemented via OE `add_attack_after_counter_melee`. | Done for data-only cleanup; runtime verification needed. |
| 2 | `h3_wolf_rider_upg_alt` | N/A in HoMM3. | Boar Rider: Jousting +3; Stronghold Battlecry scaling bonus. | Boar Rider has `Charge`: 1-Focus committing melee attack at normal damage that applies Luck -5 for 1 round. | Implemented as a grounded charge analogue; true distance-scaling jousting still needs a mechanic. |
| 3 | `h3_orc` | Orc: ranged shooter, no special ability beyond shooting. | N/A, base unit. | Ranged unit with normal melee fallback plus experimental custom `Hamstring`: 50% ranged damage, 1 Focus Charge, and Speed -2 for 1 round. | Custom test ability, not source-canonical. Runtime verification needed. |
| 3 | `h3_orc_upg` | Orc Chieftain: ranged shooter, no special ability beyond shooting. | N/A, normal upgrade. | Ranged unit with normal melee fallback plus upgraded experimental custom `Hamstring`: 100% ranged damage, 1 Focus Charge, and Speed -3 for 1 round. | Custom test ability, not source-canonical. Runtime verification needed. |
| 3 | `h3_orc_upg_alt` | N/A in HoMM3. | Orc Berserker: 20% chance to cast Basic Berserk after attacking; Return After Strike. | Renamed Orc Berserker with ToA stats; visible `Return After Strike` alternative attack using the Dungeon Assassin return flag. | Berserk-after-attack chance still needs a trigger hook. |
| 4 | `h3_ogre` | Ogre: no special ability. | N/A, base unit. | Melee only; no visible ability/passive circles. | Done for data-only cleanup. |
| 4 | `h3_ogre_upg` | Ogre Mage: casts Bloodlust. | N/A, normal upgrade. | Melee with visible `Bloodlust`; implemented as an allied +6 Offense buff for 2 rounds. | Done for data-only cleanup; runtime verification needed. |
| 4 | `h3_ogre_upg_alt` | N/A in HoMM3. | Ogre Brute: 20% chance to cast Advanced Frenzy before attacking; enchant power 1. | Renamed Ogre Brute with ToA stats; visible `Frenzied Charge` Focus attack that returns to the starting hex without ending the turn. | Approximation requested until a real pre-attack Frenzy trigger exists. |
| 5 | `h3_roc` | Roc: flying, no lightning. | N/A, base unit. | Flying melee; no visible ability/passive circles. | Done for data-only cleanup. |
| 5 | `h3_roc_upg` | Thunderbird: flying; 20% Lightning Strike after attack. | N/A, normal upgrade. | Flying melee; one visible explicit Focus `Lightning Strike` active. | Replace explicit active with chance-on-attack if/when a trigger hook is implemented. |
| 5 | `h3_roc_upg_alt` | N/A in HoMM3. | Shahrokh: flying; Ferocity +1. | Renamed Shahrokh with ToA stats; flying melee; visible `Ferocity`; implemented as OE double melee strike. | Done for data-only cleanup; runtime verification needed. |
| 6 | `h3_cyclops` | Cyclops: ranged shooter. | N/A, base unit. | Ranged unit with normal melee fallback; no donor passives. | Done for data-only cleanup. |
| 6 | `h3_cyclops_upg` | Cyclops King: ranged shooter; can attack siege walls. | N/A, normal upgrade. | Ranged unit with normal melee fallback; siege-wall targeting not implemented/displayed. | Needs siege-wall targeting mechanic. |
| 6 | `h3_cyclops_upg_alt` | N/A in HoMM3. | Blood-Eyed Cyclops: shooter; no distance penalty; no wall penalty. | Renamed Blood-Eyed Cyclops with ToA stats; ranged unit with normal melee fallback; visible `No Distance Penalty`; range damage falloff removed. | Wall penalty still needs a siege-specific mapping. |
| 7 | `h3_behemoth` | Behemoth: ignores 40% enemy Defense. | N/A, base unit. | Melee with visible `Defense Reduction`; implemented as `armorPen: 0.4`. | Done for data-only cleanup; runtime verification needed. |
| 7 | `h3_behemoth_upg` | Ancient Behemoth: ignores 80% enemy Defense. | N/A, normal upgrade. | Melee with visible `Greater Defense Reduction`; implemented as `armorPen: 0.8`. | Done for data-only cleanup; runtime verification needed. |
| 7 | `h3_behemoth_upg_alt` | N/A in HoMM3. | Ghost Behemoth: flying; enemy Defense reduction 60%; `KING` bonus. | Renamed Ghost Behemoth with ToA stats; flying melee with visible `Defense Reduction`; implemented as `armorPen: 0.6`. | `KING` analogue still unmapped. |

## Mechanic Priorities

Highest-confidence mechanics to implement or display:

| Source concept | Units | Priority | Notes |
|---|---|---:|---|
| Basic melee/no special | Goblin, Hobgoblin, Wolf Rider, Ogre | High | Remove invented circles if no matching behavior exists. |
| Ranged shooter | Orcs, Cyclopes | High | Already mostly present. |
| Wolf Raider double attack | `h3_wolf_rider_upg` | High | Implemented using OE double melee strike; needs runtime verification. |
| Ogre Mage Bloodlust | `h3_ogre_upg` | High | Implemented as an explicit allied +6 Offense buff for 2 rounds. |
| Thunderbird Lightning Strike | `h3_roc_upg` | High | HoMM3 canonical, but current active-Focus version is an approximation. |
| Cyclops King siege walls | `h3_cyclops_upg` | Medium | May not matter outside sieges; do not fake as Earthquake/Petrification. |
| Behemoth defense reduction | all Behemoths, stronger on Ancient | High | Implemented with `armorPen` values 0.4 / 0.8 / 0.6; needs runtime verification. |
| Goblin Trapper Land Mine | `h3_goblin_upg_alt` | Medium | ToA source; probably requires a trap/terrain hazard analogue. |
| Boar Rider Jousting | `h3_wolf_rider_upg_alt` | Medium | ToA source; possible charge-damage analogue. |
| Orc Berserker Berserk + Return After Strike | `h3_orc_upg_alt` | Medium | Return After Strike is implemented as an action-bar alternative attack using the Dungeon Assassin return flag. Berserk-after-attack chance still needs C# or a donor trigger. |
| Ogre Brute Frenzy before attack | `h3_ogre_upg_alt` | Medium | ToA source; currently approximated as a Focus attack-and-return action using the Dungeon Assassin return flag. A real random pre-attack Frenzy trigger still needs C# or a donor trigger. |
| Shahrokh Ferocity | `h3_roc_upg_alt` | Medium | Implemented using OE double melee strike; needs runtime verification. |
| Blood-Eyed Cyclops no range/wall penalty | `h3_cyclops_upg_alt` | Medium | No-distance penalty implemented by removing range falloff; no-wall penalty remains unmapped. |
| Ghost Behemoth flying + 60% defense reduction | `h3_behemoth_upg_alt` | Medium | ToA source; visuals may not support true flying but mechanic is clear. |

## Sources

- HoMM3 Stronghold creature specials: Heroes 3 wiki Stronghold table, including Wolf Raider double attack, Thunderbird Lightning Strike, Cyclops King siege-wall attack, and Behemoth/Ancient Behemoth defense reduction.
- Tears of Ashan overview: VCMI mod repository page, version 1.5.5 / `vcmi-1.7`, describing alternate upgrades.
- Tears of Ashan creature source: `vcmi-mods/tears-of-ashan`, branch/tag `vcmi-1.7`, files under `content/config/creatures/stronghold/*.json` and `content/config/creatures/neutral/rebalance.json`.
- Current OE implementation: local generated `HeroesOE_Data/StreamingAssets/Core.zip`, `DB/units/units_logics/homm3_stronghold/*` and `DB/units/units_views/homm3_stronghold/*`, inspected 2026-05-02.
