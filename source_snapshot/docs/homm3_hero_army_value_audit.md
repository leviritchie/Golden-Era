# HoMM3 Custom Hero Starting Army Value Audit

Source Core: `V:\SteamLibrary\steamapps\common\Heroes of Might and Magic Olden Era - Golden Era\HeroesOldenEra_Data\StreamingAssets\Core.zip`

## Method

There is no `armyValue` field on hero rows. This audit uses the same
per-creature `squadValue` scalar used by map guards, diplomacy, and
auto-battle value estimates:

```
armyValue ≈ Σ squadValue(unit_sid) × stack_count
```

Each `startSquad` slot contributes min, average `(min+max)/2`, and max
totals. Outliers use global z-score on the average total and a
±35% deviation from the hero's faction median.

Population: **180** custom heroes; mean avg armyValue **3433**
(σ=586).

## Faction summary (avg armyValue)

| Faction | Heroes | Median | Min | Max |
|---|---:|---:|---:|---:|
| `homm3_castle` | 18 | 4024 | 4024 | 4024 |
| `homm3_conflux` | 18 | 3312 | 2832 | 3414 |
| `homm3_cove` | 18 | 3947 | 2784 | 4792 |
| `homm3_dungeon` | 18 | 4011 | 2310 | 6195 |
| `homm3_fortress` | 18 | 3802 | 3802 | 3802 |
| `homm3_inferno` | 18 | 3124 | 2250 | 3499 |
| `homm3_necropolis` | 18 | 3250 | 1470 | 4500 |
| `homm3_rampart` | 18 | 3405 | 1656 | 3906 |
| `homm3_stronghold` | 18 | 2940 | 2160 | 3677 |
| `homm3_tower` | 18 | 2825 | 1980 | 2825 |

## Global low outliers (z ≤ -1.5)

| z | Hero | Faction | Avg | Min | Max | startSquad |
|---:|---|---|---:|---:|---:|---|
| -3.35 | Straker (`homm3_necropolis_hero_1`) | `homm3_necropolis` | 1470 | 1176 | 1764 | `h3_walking_dead 4-6, h3_walking_dead 4-6, h3_walking_dead 4-6` |
| -3.03 | Ufretin (`homm3_rampart_hero_2`) | `homm3_rampart` | 1656 | 1242 | 2070 | `h3_dwarf 3-5, h3_dwarf 3-5, h3_dwarf 3-5` |
| -2.48 | Piquedram (`homm3_tower_hero_1`) | `homm3_tower` | 1980 | 1485 | 2475 | `h3_gargoyle 3-5, h3_gargoyle 3-5, h3_gargoyle 3-5` |
| -2.17 | Gurnisson (`homm3_stronghold_hero_2`) | `homm3_stronghold` | 2160 | 1668 | 2652 | `h3_goblin 15-25, h3_orc 4-6` |
| -2.16 | Torosar (`homm3_tower_hero_5`) | `homm3_tower` | 2165 | 1820 | 2510 | `h3_gremlin 30-40, h3_golem 2-3` |
| -2.02 | Pyre (`homm3_inferno_hero_7`) | `homm3_inferno` | 2250 | 1821 | 2678 | `h3_imp 15-25, h3_hell_hound 3-4` |
| -1.92 | Lorelei (`homm3_dungeon_hero_1`) | `homm3_dungeon` | 2310 | 1848 | 2772 | `h3_harpy 4-6, h3_harpy 4-6, h3_harpy 4-6` |
| -1.86 | Tyraxor (`homm3_stronghold_hero_8`) | `homm3_stronghold` | 2340 | 1950 | 2730 | `h3_wolf_rider 5-7, h3_wolf_rider 5-7, h3_wolf_rider 5-7` |

## Global high outliers (z ≥ +1.5)

| z | Hero | Faction | Avg | Min | Max | startSquad |
|---:|---|---|---:|---:|---:|---|
| +4.71 | Shakti (`homm3_dungeon_hero_8`) | `homm3_dungeon` | 6195 | 5310 | 7080 | `h3_troglodyte 30-40, h3_troglodyte 30-40, h3_troglodyte 30-40` |
| +2.32 | Illor (`homm3_cove_hero_3`) | `homm3_cove` | 4792 | 3557 | 6028 | `h3_nymph 15-25, h3_stormbird 3-5, h3_pirate 4-7` |
| +1.82 | Boyd (`homm3_necropolis_hero_17`) | `homm3_necropolis` | 4500 | 3600 | 5400 | `h3_skeleton 20-30, h3_skeleton 20-30, h3_skeleton 20-30` |
| +1.82 | Galthran (`homm3_necropolis_hero_8`) | `homm3_necropolis` | 4500 | 3600 | 5400 | `h3_skeleton 20-30, h3_skeleton 20-30, h3_skeleton 20-30` |
| +1.70 | Anabel (`homm3_cove_hero_7`) | `homm3_cove` | 4429 | 3247 | 5611 | `h3_nymph 15-25, h3_pirate 4-7, h3_pirate 4-7` |
| +1.68 | Ajit (`homm3_dungeon_hero_4`) | `homm3_dungeon` | 4417 | 3786 | 5048 | `h3_troglodyte 30-40, h3_beholder 3-4, h3_beholder 3-4` |

## Faction-relative outliers (≥35% off faction median)

| Ratio | Hero | Faction | Avg | Faction median | startSquad |
|---:|---|---|---:|---:|---|
| 0.45x | Straker (`homm3_necropolis_hero_1`) | `homm3_necropolis` | 1470 | 3250 | `h3_walking_dead 4-6, h3_walking_dead 4-6, h3_walking_dead 4-6` |
| 0.49x | Ufretin (`homm3_rampart_hero_2`) | `homm3_rampart` | 1656 | 3405 | `h3_dwarf 3-5, h3_dwarf 3-5, h3_dwarf 3-5` |
| 0.58x | Lorelei (`homm3_dungeon_hero_1`) | `homm3_dungeon` | 2310 | 4011 | `h3_harpy 4-6, h3_harpy 4-6, h3_harpy 4-6` |
| 0.64x | Mutare Drake (`homm3_dungeon_hero_18`) | `homm3_dungeon` | 2572 | 4011 | `h3_troglodyte 10-20, h3_harpy 4-7, h3_beholder 2-3` |
| 1.38x | Boyd (`homm3_necropolis_hero_17`) | `homm3_necropolis` | 4500 | 3250 | `h3_skeleton 20-30, h3_skeleton 20-30, h3_skeleton 20-30` |
| 1.38x | Galthran (`homm3_necropolis_hero_8`) | `homm3_necropolis` | 4500 | 3250 | `h3_skeleton 20-30, h3_skeleton 20-30, h3_skeleton 20-30` |
| 1.54x | Shakti (`homm3_dungeon_hero_8`) | `homm3_dungeon` | 6195 | 4011 | `h3_troglodyte 30-40, h3_troglodyte 30-40, h3_troglodyte 30-40` |

## hero_overrides drift vs deployed Core

**38** heroes differ between `custom_factions/hero_overrides`
and the deployed Core row used at runtime.

| Hero | Override avg | Core avg | Override startSquad | Core startSquad |
|---|---:|---:|---|---|
| Orrin (`homm3_castle_hero_1`) | 2770.5 | 4024.0 | `h3_pikeman 10-20, h3_archer 4-7, h3_griffin 2-3` | `h3_pikeman 14-20, h3_archer 8-12, h3_griffin 3-5` |
| Adela (`homm3_castle_hero_10`) | 2770.5 | 4024.0 | `h3_pikeman 10-20, h3_archer 4-7, h3_griffin 2-3` | `h3_pikeman 14-20, h3_archer 8-12, h3_griffin 3-5` |
| Cuthbert (`homm3_castle_hero_11`) | 2770.5 | 4024.0 | `h3_pikeman 10-20, h3_archer 4-7, h3_griffin 2-3` | `h3_pikeman 14-20, h3_archer 8-12, h3_griffin 3-5` |
| Adelaide (`homm3_castle_hero_12`) | 2770.5 | 4024.0 | `h3_pikeman 10-20, h3_archer 4-7, h3_griffin 2-3` | `h3_pikeman 14-20, h3_archer 8-12, h3_griffin 3-5` |
| Ingham (`homm3_castle_hero_13`) | 2770.5 | 4024.0 | `h3_pikeman 10-20, h3_archer 4-7, h3_griffin 2-3` | `h3_pikeman 14-20, h3_archer 8-12, h3_griffin 3-5` |
| Sanya (`homm3_castle_hero_14`) | 2770.5 | 4024.0 | `h3_pikeman 10-20, h3_archer 4-7, h3_griffin 2-3` | `h3_pikeman 14-20, h3_archer 8-12, h3_griffin 3-5` |
| Loynis (`homm3_castle_hero_15`) | 2770.5 | 4024.0 | `h3_pikeman 10-20, h3_archer 4-7, h3_griffin 2-3` | `h3_pikeman 14-20, h3_archer 8-12, h3_griffin 3-5` |
| Caitlin (`homm3_castle_hero_16`) | 2770.5 | 4024.0 | `h3_pikeman 10-20, h3_archer 4-7, h3_griffin 2-3` | `h3_pikeman 14-20, h3_archer 8-12, h3_griffin 3-5` |
| Sir Mullich (`homm3_castle_hero_17`) | 2770.5 | 4024.0 | `h3_pikeman 10-20, h3_archer 4-7, h3_griffin 2-3` | `h3_pikeman 14-20, h3_archer 8-12, h3_griffin 3-5` |
| Beatrice (`homm3_castle_hero_18`) | 2770.5 | 4024.0 | `h3_pikeman 10-20, h3_archer 4-7, h3_griffin 2-3` | `h3_pikeman 14-20, h3_archer 8-12, h3_griffin 3-5` |
| Valeska (`homm3_castle_hero_2`) | 2079.0 | 4024.0 | `h3_archer 4-7, h3_archer 4-7, h3_archer 4-7` | `h3_pikeman 14-20, h3_archer 8-12, h3_griffin 3-5` |
| Edric (`homm3_castle_hero_3`) | 2955.0 | 4024.0 | `h3_pikeman 10-20, h3_griffin 2-3, h3_griffin 2-3` | `h3_pikeman 14-20, h3_archer 8-12, h3_griffin 3-5` |
| Sylvia (`homm3_castle_hero_4`) | 2770.5 | 4024.0 | `h3_pikeman 10-20, h3_archer 4-7, h3_griffin 2-3` | `h3_pikeman 14-20, h3_archer 8-12, h3_griffin 3-5` |
| Lord Haart (`homm3_castle_hero_5`) | 2770.5 | 4024.0 | `h3_pikeman 10-20, h3_archer 4-7, h3_griffin 2-3` | `h3_pikeman 14-20, h3_archer 8-12, h3_griffin 3-5` |
| Sorsha (`homm3_castle_hero_6`) | 2770.5 | 4024.0 | `h3_pikeman 10-20, h3_archer 4-7, h3_griffin 2-3` | `h3_pikeman 14-20, h3_archer 8-12, h3_griffin 3-5` |
| Christian (`homm3_castle_hero_7`) | 2077.5 | 4024.0 | `h3_pikeman 10-20, h3_griffin 2-3` | `h3_pikeman 14-20, h3_archer 8-12, h3_griffin 3-5` |
| Tyris (`homm3_castle_hero_8`) | 2770.5 | 4024.0 | `h3_pikeman 10-20, h3_archer 4-7, h3_griffin 2-3` | `h3_pikeman 14-20, h3_archer 8-12, h3_griffin 3-5` |
| Rion (`homm3_castle_hero_9`) | 2077.5 | 4024.0 | `h3_pikeman 10-20, h3_griffin 2-3` | `h3_pikeman 14-20, h3_archer 8-12, h3_griffin 3-5` |
| Bron (`homm3_fortress_hero_1`) | 4680.0 | 3802.0 | `h3_gnoll 10-20, h3_basilisk 4-7, h3_serpent_fly 2-4` | `h3_gnoll 14-20, h3_lizardman 8-12, h3_serpent_fly 4-6` |
| Rosic (`homm3_fortress_hero_10`) | 2474.5 | 3802.0 | `h3_gnoll 10-20, h3_lizardman 4-7, h3_serpent_fly 2-4` | `h3_gnoll 14-20, h3_lizardman 8-12, h3_serpent_fly 4-6` |
| Voy (`homm3_fortress_hero_11`) | 2474.5 | 3802.0 | `h3_gnoll 10-20, h3_lizardman 4-7, h3_serpent_fly 2-4` | `h3_gnoll 14-20, h3_lizardman 8-12, h3_serpent_fly 4-6` |
| Verdish (`homm3_fortress_hero_12`) | 1644.0 | 3802.0 | `h3_gnoll 10-20, h3_serpent_fly 2-4` | `h3_gnoll 14-20, h3_lizardman 8-12, h3_serpent_fly 4-6` |
| Merist (`homm3_fortress_hero_13`) | 2474.5 | 3802.0 | `h3_gnoll 10-20, h3_lizardman 4-7, h3_serpent_fly 2-4` | `h3_gnoll 14-20, h3_lizardman 8-12, h3_serpent_fly 4-6` |
| Styg (`homm3_fortress_hero_14`) | 2474.5 | 3802.0 | `h3_gnoll 10-20, h3_lizardman 4-7, h3_serpent_fly 2-4` | `h3_gnoll 14-20, h3_lizardman 8-12, h3_serpent_fly 4-6` |
| Andra (`homm3_fortress_hero_15`) | 2474.5 | 3802.0 | `h3_gnoll 10-20, h3_lizardman 4-7, h3_serpent_fly 2-4` | `h3_gnoll 14-20, h3_lizardman 8-12, h3_serpent_fly 4-6` |
| Tiva (`homm3_fortress_hero_16`) | 2474.5 | 3802.0 | `h3_gnoll 10-20, h3_lizardman 4-7, h3_serpent_fly 2-4` | `h3_gnoll 14-20, h3_lizardman 8-12, h3_serpent_fly 4-6` |
| Tazar (`homm3_fortress_hero_17`) | 2474.5 | 3802.0 | `h3_gnoll 10-20, h3_lizardman 4-7, h3_serpent_fly 2-4` | `h3_gnoll 14-20, h3_lizardman 8-12, h3_serpent_fly 4-6` |
| Mirlanda (`homm3_fortress_hero_18`) | 2474.5 | 3802.0 | `h3_gnoll 10-20, h3_lizardman 4-7, h3_serpent_fly 2-4` | `h3_gnoll 14-20, h3_lizardman 8-12, h3_serpent_fly 4-6` |
| Drakon (`homm3_fortress_hero_2`) | 2520.0 | 3802.0 | `h3_gnoll 10-20, h3_gnoll 10-20, h3_gnoll 10-20` | `h3_gnoll 14-20, h3_lizardman 8-12, h3_serpent_fly 4-6` |
| Wystan (`homm3_fortress_hero_3`) | 2491.5 | 3802.0 | `h3_lizardman 4-7, h3_lizardman 4-7, h3_lizardman 4-7` | `h3_gnoll 14-20, h3_lizardman 8-12, h3_serpent_fly 4-6` |
| Tazar (`homm3_fortress_hero_4`) | 2474.5 | 3802.0 | `h3_gnoll 10-20, h3_lizardman 4-7, h3_serpent_fly 2-4` | `h3_gnoll 14-20, h3_lizardman 8-12, h3_serpent_fly 4-6` |
| Alkin (`homm3_fortress_hero_5`) | 2474.5 | 3802.0 | `h3_gnoll 10-20, h3_lizardman 4-7, h3_serpent_fly 2-4` | `h3_gnoll 14-20, h3_lizardman 8-12, h3_serpent_fly 4-6` |
| Korbac (`homm3_fortress_hero_6`) | 2448.0 | 3802.0 | `h3_gnoll 10-20, h3_serpent_fly 2-4, h3_serpent_fly 2-4` | `h3_gnoll 14-20, h3_lizardman 8-12, h3_serpent_fly 4-6` |
| Gerwulf (`homm3_fortress_hero_7`) | 1644.0 | 3802.0 | `h3_gnoll 10-20, h3_serpent_fly 2-4` | `h3_gnoll 14-20, h3_lizardman 8-12, h3_serpent_fly 4-6` |
| Broghild (`homm3_fortress_hero_8`) | 2474.5 | 3802.0 | `h3_gnoll 10-20, h3_lizardman 4-7, h3_serpent_fly 2-4` | `h3_gnoll 14-20, h3_lizardman 8-12, h3_serpent_fly 4-6` |
| Mirlanda (`homm3_fortress_hero_9`) | 2474.5 | 3802.0 | `h3_gnoll 10-20, h3_lizardman 4-7, h3_serpent_fly 2-4` | `h3_gnoll 14-20, h3_lizardman 8-12, h3_serpent_fly 4-6` |
| Gruezak (`homm3_stronghold_hero_17`) | 2160.0 | 3677.0 | `h3_goblin 15-25, h3_orc 4-6` | `h3_goblin 18-25, h3_wolf_rider 8-11, h3_orc 5-7` |
| Zog (`homm3_stronghold_hero_18`) | 3436.0 | 3677.0 | `h3_goblin 15-25, h3_wolf_rider 5-7, h3_ogre 3-4` | `h3_goblin 18-25, h3_wolf_rider 8-11, h3_orc 5-7` |

## Interpretation notes

- Many low outliers are intentional HoMM3 specialist starters: triple
  low-tier stacks (Walking Dead, Dwarf, Harpy, Archer) or two-stack armies.
- High outliers usually come from large low-tier counts (30-40 Troglo/Gremlin)
  or upgraded tier mixes (Roc/Ogre/Basilisk specialists).
- `squadValue` inflation on high-tier custom units (see
  `docs/homm3_stronghold_squad_value_audit.md`) amplifies specialist armies
  that include Roc, Ogre, or Basilisk stacks.
- Re-run after `apply_release_core_overlay.py` or hero prefill changes.
