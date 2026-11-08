# HoMM3/HotA Hero Specialization Comparison

Generated from local structured data in this workspace. This is read-only documentation; it does not change game data.

## Sources And Limits

- `HoMM3/HotA source specialization` is from local VCMI source data: base HoMM3 rows in `C:\Users\<user>\AppData\Roaming\VCMI\config\heroes\*.json`, HotA loose rows under `vcmi/Mods/hota/mods/cove/.../heroes/` and `vcmi/Mods/hota/mods/heroes/.../heroes/`, plus HotA game-balance overrides inside `vcmi/Mods/hota/mods/gameBalance/mods/heroes/content.zip`.
- `Current effective mod specialization` is read from `custom_factions/hero_overrides/*.json`. Masterful spell specialists are owned there; the release overlay only validates those rows and applies their matching starting spells.
- The left column is local VCMI/HotA source data, not a separate live verification against official HotA binaries or wiki text.
- Each row includes the mod slot and hero SID. (2026-09-19: no duplicate display names exist in current `hero_overrides` data; the former duplicates were doc-only conflux rows, now removed.)

Total current mod heroes covered: 178. Masterful spell specializations owned by `hero_overrides`: 10. (2026-09-19 correction, verified against `custom_factions/hero_overrides/*.json`: conflux ships 16 heroes, not 18 — doc-only duplicate Pasis/Luna slots 17-18 removed. Cove cross-checks clean at 18/18.)

## Castle

| Slot | Hero SID | Hero | HoMM3/HotA source specialization | Current effective mod specialization | Effective layer |
|---:|---|---|---|---|---|
| 1 | `homm3_castle_hero_1` | Orrin | Archery | Logistics - Increases movement on the adventure map and improves travel on roads. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 2 | `homm3_castle_hero_2` | Valeska | Archers - Increases the Speed of allied Archers and Marksmen by 1 and their Attack and Defense skills by 20% for every 2 levels (rounded up). | Scouting - Reveals a wider area of the adventure map and exposes enemy hero and army information. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 3 | `homm3_castle_hero_3` | Edric | Griffins - Increases the Speed of allied Griffins and Royal Griffins by 1 and their Attack and Defense skills by 20% for every 3 levels (rounded up). | Pikeman Specialist - Pikeman creatures and their upgrades gain the current Olden Era growth and combat specialist package. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 4 | `homm3_castle_hero_4` | Sylvia | Navigation | Archer Specialist - Archer creatures and their upgrades gain the current Olden Era growth and combat specialist package. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 5 | `homm3_castle_hero_5` | Lord Haart | Estates | Leadership - Improves army Morale and gives troops a growing chance to act again. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 6 | `homm3_castle_hero_6` | Sorsha | Swordsmen - Increases the Speed of allied Swordsmen and Crusaders by 1 and their Attack and Defense skills by 20% for every 4 levels (rounded up). | Estates - Generates additional gold each day, increasing as the hero gains levels. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 7 | `homm3_castle_hero_7` | Christian | Ballista - Increases the Ballista's Attack and Defense skills by 30% for every 5 levels (rounded up). | Griffin Specialist - Griffin creatures and their upgrades gain the current Olden Era growth and combat specialist package. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 8 | `homm3_castle_hero_8` | Tyris | Cavaliers - Increases the Speed of allied Cavaliers and Champions by 1 and their Attack and Defense skills by 20% for every 6 levels (rounded up). | Fortune - Improves army Luck and increases the chance of critical hits as the hero gains levels. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 9 | `homm3_castle_hero_9` | Rion | First Aid - Receives a 5% per level bonus to bonus Health provided by the First Aid Tent. | Sorcery - Increases spell damage and weakens enemy spell pressure as the hero gains levels. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 10 | `homm3_castle_hero_10` | Adela | Bless - Increases the Damage of units affected by Bless by 10% for every N hero levels, where N is the level of the target creature. | Mysticism - Increases the hero's mana reserves and allows one additional spell use each round. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 11 | `homm3_castle_hero_11` | Cuthbert | Weakness - Casts Weakness with effect increased by 4 for level 1-2 creatures, by 6 for level 3-4 creatures, by 8 for level 5-6 creatures, and by 10 for level 7 creatures. | Swordsman Specialist - Swordsman creatures and their upgrades gain the current Olden Era growth and combat specialist package. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 12 | `homm3_castle_hero_12` | Adelaide | Frost Ring - Casts Frost Ring with damage increased by 10% for every N hero levels, where N is the level of the target creature. | Offense - Increases basic attack damage for the hero's army, with stronger gains at higher levels. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 13 | `homm3_castle_hero_13` | Ingham | Monks - Increases the Speed of allied Monks and Zealots by 1 and their Attack and Defense skills by 20% for every 5 levels (rounded up). | Monk Specialist - Monk creatures and their upgrades gain the current Olden Era growth and combat specialist package. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 14 | `homm3_castle_hero_14` | Sanya | Eagle Eye | Pathfinding - Ignores rough-terrain movement penalties and restores movement after battles. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 15 | `homm3_castle_hero_15` | Loynis | Prayer - Casts Prayer with effect increased by 3 for level 1-4 creatures, by 2 for level 5-6 creatures, and by 1 for level 7 creatures. | Cavalier Specialist - Cavalier creatures and their upgrades gain the current Olden Era growth and combat specialist package. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 16 | `homm3_castle_hero_16` | Caitlin | Gold | Armorer - Reduces incoming basic and ranged attack damage for the hero's army, with stronger gains at higher levels. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 17 | `homm3_castle_hero_17` | Sir Mullich | Speed | Angel Specialist - Angel creatures and their upgrades gain the current Olden Era growth and combat specialist package. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 18 | `homm3_castle_hero_18` | Beatrice | Scouting - Increases the scouting range by 1 for every 6 levels of the hero. | Tactics - Improves pre-battle deployment and constricts the enemy deployment zone. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |

## Rampart

| Slot | Hero SID | Hero | HoMM3/HotA source specialization | Current effective mod specialization | Effective layer |
|---:|---|---|---|---|---|
| 1 | `homm3_rampart_hero_1` | Mephala | Armorer | Logistics - Increases movement on the adventure map and improves travel on roads. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 2 | `homm3_rampart_hero_2` | Ufretin | Dwarves - Increases the Speed of allied Dwarves and Battle Dwarves by 1 and their Attack and Defense skills by 20% for every 2 levels (rounded up). | Scouting - Reveals a wider area of the adventure map and exposes enemy hero and army information. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 3 | `homm3_rampart_hero_3` | Jenova | Gold | Centaur Specialist - Centaur creatures and their upgrades gain the current Olden Era growth and combat specialist package. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 4 | `homm3_rampart_hero_4` | Ryland | Dendroid Guards - Increases the Speed of allied Dendroid Guards and Dendroid Soldiers by 1 and their Attack and Defense skills by 20% for every 5 levels (rounded up). | Dwarf Specialist - Dwarf creatures and their upgrades gain the current Olden Era growth and combat specialist package. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 5 | `homm3_rampart_hero_5` | Thorgrim | Resistance | Leadership - Improves army Morale and gives troops a growing chance to act again. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 6 | `homm3_rampart_hero_6` | Ivor | Wood Elves - Increases the Speed of allied Wood Elfs and Grand Elfs by 1 and their Attack and Defense skills by 20% for every 3 levels (rounded up). | Estates - Generates additional gold each day, increasing as the hero gains levels. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 7 | `homm3_rampart_hero_7` | Clancy | Unicorn - Increases the Speed of allied Unicorns and War Unicorns by 1 and their Attack and Defense skills by 20% for every 6 levels (rounded up). | Wood Elf Specialist - Wood Elf creatures and their upgrades gain the current Olden Era growth and combat specialist package. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 8 | `homm3_rampart_hero_8` | Kyrre | Logistics | Fortune - Improves army Luck and increases the chance of critical hits as the hero gains levels. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 9 | `homm3_rampart_hero_9` | Coronius | Slayer - Casts Slayer with effect increased by 20 for level 1-2 creatures, by 16 for level 3-4 creatures, by 12 for level 5-6 creatures, and by 8 for level 7 creatures. | Sorcery - Increases spell damage and weakens enemy spell pressure as the hero gains levels. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 10 | `homm3_rampart_hero_10` | Uland | Cure | Mysticism - Increases the hero's mana reserves and allows one additional spell use each round. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 11 | `homm3_rampart_hero_11` | Elleshar | Intelligence | Pegasus Specialist - Pegasus creatures and their upgrades gain the current Olden Era growth and combat specialist package. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 12 | `homm3_rampart_hero_12` | Gem | First Aid - Receives a 5% per level bonus to bonus Health provided by the First Aid Tent. | Offense - Increases basic attack damage for the hero's army, with stronger gains at higher levels. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 13 | `homm3_rampart_hero_13` | Malcom | Eagle Eye | Dendroid Guard Specialist - Dendroid Guard creatures and their upgrades gain the current Olden Era growth and combat specialist package. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 14 | `homm3_rampart_hero_14` | Melodia | Fortune | Pathfinding - Ignores rough-terrain movement penalties and restores movement after battles. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 15 | `homm3_rampart_hero_15` | Alagar | Ice Bolt - Casts Ice Bolt with damage increased by 10% for every N hero levels, where N is the level of the target creature. | Unicorn Specialist - Unicorn creatures and their upgrades gain the current Olden Era growth and combat specialist package. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 16 | `homm3_rampart_hero_16` | Aeris | Pegasi - Increases the Speed of allied Pegasi and Silver Pegasi by 1 and their Attack and Defense skills by 20% for every 4 levels (rounded up). | Armorer - Reduces incoming basic and ranged attack damage for the hero's army, with stronger gains at higher levels. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 17 | `homm3_rampart_hero_17` | Mephala | Armorer | Green Dragon Specialist - Green Dragon creatures and their upgrades gain the current Olden Era growth and combat specialist package. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 18 | `homm3_rampart_hero_18` | Gem | First Aid - Receives a 5% per level bonus to bonus Health provided by the First Aid Tent. | Tactics - Improves pre-battle deployment and constricts the enemy deployment zone. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |

## Tower

| Slot | Hero SID | Hero | HoMM3/HotA source specialization | Current effective mod specialization | Effective layer |
|---:|---|---|---|---|---|
| 1 | `homm3_tower_hero_1` | Piquedram | Stone Gargoyle - Increases the Speed of allied Stone Gargoyles and Obsidian Gargoyles by 1 and their Attack and Defense skills by 20% for every 2 levels (rounded up). | Logistics - Increases movement on the adventure map and improves travel on roads. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 2 | `homm3_tower_hero_2` | Thane | Genies - Increases the Speed of allied Genies and Master Genies by 1 and their Attack and Defense skills by 20% for every 5 levels (rounded up). | Scouting - Reveals a wider area of the adventure map and exposes enemy hero and army information. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 3 | `homm3_tower_hero_3` | Josephine | Iron Golem - Increases the Speed of allied Stone Golems and Iron Golems by 1 and their Attack and Defense skills by 20% for every 3 levels (rounded up). | Gremlin Specialist - Gremlin creatures and their upgrades gain the current Olden Era growth and combat specialist package. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 4 | `homm3_tower_hero_4` | Neela | Armorer | Stone Gargoyle Specialist - Stone Gargoyle creatures and their upgrades gain the current Olden Era growth and combat specialist package. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 5 | `homm3_tower_hero_5` | Torosar | Ballista - Increases the Ballista's Attack and Defense skills by 30% for every 5 levels (rounded up). | Leadership - Improves army Morale and gives troops a growing chance to act again. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 6 | `homm3_tower_hero_6` | Fafner | Nagas - Increases the Speed of allied Nagas and Naga Queens by 1 and their Attack and Defense skills by 20% for every 6 levels (rounded up). | Estates - Generates additional gold each day, increasing as the hero gains levels. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 7 | `homm3_tower_hero_7` | Rissa | Mercury | Stone Golem Specialist - Stone Golem creatures and their upgrades gain the current Olden Era growth and combat specialist package. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 8 | `homm3_tower_hero_8` | Iona | Genies - Increases the Speed of allied Genies and Master Genies by 1 and their Attack and Defense skills by 20% for every 5 levels (rounded up). | Fortune - Improves army Luck and increases the chance of critical hits as the hero gains levels. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 9 | `homm3_tower_hero_9` | Astral | Hypnotize - Casts Hypnotize with maximum health threshold increased by 10% for every N hero levels, where N is the level of the targeted creature. | Masterful Optical Illusion - Starts with Masterful Optical Illusion. This version also gives the target 25% spell-damage resistance. | hero_overrides |
| 10 | `homm3_tower_hero_10` | Halon | Mysticism | Masterful Energize - Starts with Masterful Energize. This version grants Focus Charges for less mana. | hero_overrides |
| 11 | `homm3_tower_hero_11` | Serena | Eagle Eye | Mage Specialist - Mage creatures and their upgrades gain the current Olden Era growth and combat specialist package. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 12 | `homm3_tower_hero_12` | Daremyth | Fortune | Offense - Increases basic attack damage for the hero's army, with stronger gains at higher levels. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 13 | `homm3_tower_hero_13` | Theodorus | Magi - Increases the Speed of allied Magi and Arch Magi by 1 and their Attack and Defense skills by 20% for every 4 levels (rounded up). | Genie Specialist - Genie creatures and their upgrades gain the current Olden Era growth and combat specialist package. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 14 | `homm3_tower_hero_14` | Solmyr | Chain Lightning - Casts Chain Lightning with damage increased by 5% for every N hero levels, where N is the level of the target creature. | Masterful Lightning Bolt - Starts with Masterful Lightning Bolt. This version can strike up to 2 enemy targets. | hero_overrides |
| 15 | `homm3_tower_hero_15` | Cyra | Haste - Casts Haste with effect increased by 3 for level 1-4 creatures, by 2 for level 5-6 creatures, and by 1 for level 7 creatures. | Naga Specialist - Naga creatures and their upgrades gain the current Olden Era growth and combat specialist package. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 16 | `homm3_tower_hero_16` | Aine | Gold | Masterful Radiant Armor - Starts with Masterful Radiant Armor. This version costs less mana. | hero_overrides |
| 17 | `homm3_tower_hero_17` | Cyra | Haste - Casts Haste with effect increased by 3 for level 1-4 creatures, by 2 for level 5-6 creatures, and by 1 for level 7 creatures. | Giant Specialist - Giant creatures and their upgrades gain the current Olden Era growth and combat specialist package. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 18 | `homm3_tower_hero_18` | Aine | Gold | Tactics - Improves pre-battle deployment and constricts the enemy deployment zone. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |

## Inferno

| Slot | Hero SID | Hero | HoMM3/HotA source specialization | Current effective mod specialization | Effective layer |
|---:|---|---|---|---|---|
| 1 | `homm3_inferno_hero_1` | Fiona | Hell Hounds - Increases the Speed of allied Hellhounds and Cerberi by 1 and their Attack and Defense skills by 20% for every 3 levels (rounded up). | Logistics - Increases movement on the adventure map and improves travel on roads. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 2 | `homm3_inferno_hero_2` | Rashka | Efreet - Increases the Speed of allied Efreeti and Efreet Sultans by 1 and their Attack and Defense skills by 20% for every 6 levels (rounded up). | Scouting - Reveals a wider area of the adventure map and exposes enemy hero and army information. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 3 | `homm3_inferno_hero_3` | Marius | Demons - Increases the Speed of allied Demons and Horned Demons by 1 and their Attack and Defense skills by 20% for every 4 levels (rounded up). | Imp Specialist - Imp creatures and their upgrades gain the current Olden Era growth and combat specialist package. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 4 | `homm3_inferno_hero_4` | Ignatius | Imps - Increases the Speed of allied Imps and Familiars by 1 and their Attack and Defense skills by 10% for every level (rounded up). | Gog Specialist - Gog creatures and their upgrades gain the current Olden Era growth and combat specialist package. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 5 | `homm3_inferno_hero_5` | Octavia | Gold | Leadership - Improves army Morale and gives troops a growing chance to act again. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 6 | `homm3_inferno_hero_6` | Calh | Gogs - Increases the Speed of allied Gogs and Magogs by 1 and their Attack and Defense skills by 20% for every 2 levels (rounded up). | Estates - Generates additional gold each day, increasing as the hero gains levels. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 7 | `homm3_inferno_hero_7` | Pyre | Ballista - Increases the Ballista's Attack and Defense skills by 30% for every 5 levels (rounded up). | Hell Hound Specialist - Hell Hound creatures and their upgrades gain the current Olden Era growth and combat specialist package. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 8 | `homm3_inferno_hero_8` | Nymus | Pit Fiend - Increases the Speed of allied Pit Fiends and Pit Lords by 1 and their Attack and Defense skills by 20% for every 5 levels (rounded up). | Fortune - Improves army Luck and increases the chance of critical hits as the hero gains levels. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 9 | `homm3_inferno_hero_9` | Ayden | Intelligence | Sorcery - Increases spell damage and weakens enemy spell pressure as the hero gains levels. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 10 | `homm3_inferno_hero_10` | Xyron | Inferno - Casts Inferno with damage increased by 10% for every N hero levels, where N is the level of the target creature. | Masterful Energy Explosion - Starts with Masterful Energy Explosion. This version uses a larger blast area based on Focus Charges. | hero_overrides |
| 11 | `homm3_inferno_hero_11` | Axsis | Mysticism | Demon Specialist - Demon creatures and their upgrades gain the current Olden Era growth and combat specialist package. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 12 | `homm3_inferno_hero_12` | Olema | Weakness - Casts Weakness with effect increased by 4 for level 1-2 creatures, by 6 for level 3-4 creatures, by 8 for level 5-6 creatures, and by 10 for level 7 creatures. | Offense - Increases basic attack damage for the hero's army, with stronger gains at higher levels. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 13 | `homm3_inferno_hero_13` | Calid | Sulfur | Pit Fiend Specialist - Pit Fiend creatures and their upgrades gain the current Olden Era growth and combat specialist package. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 14 | `homm3_inferno_hero_14` | Ash | Bloodlust - Casts Bloodlust with effect increased by 10 for level 1-2 creatures, by 8 for level 3-4 creatures, by 6 for level 5-6 creatures, and by 4 for level 7 creatures. | Pathfinding - Ignores rough-terrain movement penalties and restores movement after battles. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 15 | `homm3_inferno_hero_15` | Zydar | Sorcery | Efreeti Specialist - Efreeti creatures and their upgrades gain the current Olden Era growth and combat specialist package. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 16 | `homm3_inferno_hero_16` | Xarfax | Fireball - Casts Fireball with damage increased by 10% for every N hero levels, where N is the level of the target creature. | Armorer - Reduces incoming basic and ranged attack damage for the hero's army, with stronger gains at higher levels. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 17 | `homm3_inferno_hero_17` | Athe | Sorcery - Receives a 5% per level bonus to sorcery skill percentage. | Devil Specialist - Devil creatures and their upgrades gain the current Olden Era growth and combat specialist package. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 18 | `homm3_inferno_hero_18` | Miseria | Resurrection - Casts Resurrection with effect increased by 5% for every N hero levels, where N is the level of the target creature. | Tactics - Improves pre-battle deployment and constricts the enemy deployment zone. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |

## Necropolis

| Slot | Hero SID | Hero | HoMM3/HotA source specialization | Current effective mod specialization | Effective layer |
|---:|---|---|---|---|---|
| 1 | `homm3_necropolis_hero_1` | Straker | Walking Dead - Increases the Speed of allied Walking Dead and Zombies by 1 and their Attack and Defense skills by 20% for every 2 levels (rounded up). | Logistics - Increases movement on the adventure map and improves travel on roads. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 2 | `homm3_necropolis_hero_2` | Vokial | Vampires - Increases the Speed of allied Vampires and Vampire Lords by 1 and their Attack and Defense skills by 20% for every 4 levels (rounded up). | Scouting - Reveals a wider area of the adventure map and exposes enemy hero and army information. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 3 | `homm3_necropolis_hero_3` | Moandor | Liches - Increases the Speed of allied Liches and Power Liches by 1 and their Attack and Defense skills by 20% for every 5 levels (rounded up). | Skeleton Specialist - Skeleton creatures and their upgrades gain the current Olden Era growth and combat specialist package. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 4 | `homm3_necropolis_hero_4` | Charna | Wights - Increases the Speed of allied Wights and Wraiths by 1 and their Attack and Defense skills by 20% for every 3 levels (rounded up). | Walking Dead Specialist - Walking Dead creatures and their upgrades gain the current Olden Era growth and combat specialist package. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 5 | `homm3_necropolis_hero_5` | Tamika | Black Knights - Increases the Speed of allied Black Knights and Death Knights by 1 and their Attack and Defense skills by 20% for every 6 levels (rounded up). | Leadership - Improves army Morale and gives troops a growing chance to act again. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 6 | `homm3_necropolis_hero_6` | Isra | Necromancy | Estates - Generates additional gold each day, increasing as the hero gains levels. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 7 | `homm3_necropolis_hero_7` | Clavius | Gold | Wight Specialist - Wight creatures and their upgrades gain the current Olden Era growth and combat specialist package. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 8 | `homm3_necropolis_hero_8` | Galthran | Skeletons - Increases the Speed of allied Skeletons and Skeleton Warriors by 1 and their Attack and Defense skills by 10% for every level (rounded up). | Fortune - Improves army Luck and increases the chance of critical hits as the hero gains levels. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 9 | `homm3_necropolis_hero_9` | Septienna | Death Ripple - Casts Death Ripple with damage increased by 10% for every N hero levels, where N is the level of the target creature. | Masterful Fatal Decay - Starts with Masterful Fatal Decay. This version lasts 5 additional rounds. | hero_overrides |
| 10 | `homm3_necropolis_hero_10` | Aislinn | Meteor Shower - Casts Meteor Shower with damage increased by 5% for every N hero levels, where N is the level of the target creature. | Masterful Sleep - Starts with Masterful Sleep. This version ignores creature-type immunity restrictions. | hero_overrides |
| 11 | `homm3_necropolis_hero_11` | Sandro | Sorcery | Vampire Specialist - Vampire creatures and their upgrades gain the current Olden Era growth and combat specialist package. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 12 | `homm3_necropolis_hero_12` | Nimbus | Eagle Eye | Offense - Increases basic attack damage for the hero's army, with stronger gains at higher levels. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 13 | `homm3_necropolis_hero_13` | Thant | Animate Dead - Casts Animate Dead with effect increased by 5% for every N hero levels, where N is the level of the target creature. | Lich Specialist - Lich creatures and their upgrades gain the current Olden Era growth and combat specialist package. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 14 | `homm3_necropolis_hero_14` | Xsi | Stone Skin - Casts Stone Skin with effect increased by 10 for level 1-2 creatures, by 8 for level 3-4 creatures, by 6 for level 5-6 creatures, and by 4 for level 7 creatures. | Pathfinding - Ignores rough-terrain movement penalties and restores movement after battles. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 15 | `homm3_necropolis_hero_15` | Vidomina | Necromancy | Black Knight Specialist - Black Knight creatures and their upgrades gain the current Olden Era growth and combat specialist package. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 16 | `homm3_necropolis_hero_16` | Nagash | Gold | Armorer - Reduces incoming basic and ranged attack damage for the hero's army, with stronger gains at higher levels. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 17 | `homm3_necropolis_hero_17` | Boyd | Skeletons - Increases the Speed of allied Skeletons and Skeleton Warriors by 1 and their Attack and Defense skills by 10% for every level (rounded up). | Bone Dragon Specialist - Bone Dragon creatures and their upgrades gain the current Olden Era growth and combat specialist package. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 18 | `homm3_necropolis_hero_18` | Ranloo | Ballista - Increases the Ballista's Attack and Defense skills by 30% for every 5 levels (rounded up). | Tactics - Improves pre-battle deployment and constricts the enemy deployment zone. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |

## Dungeon

| Slot | Hero SID | Hero | HoMM3/HotA source specialization | Current effective mod specialization | Effective layer |
|---:|---|---|---|---|---|
| 1 | `homm3_dungeon_hero_1` | Lorelei | Harpies - Increases the Speed of allied Harpies and Harpy Hags by 1 and their Attack and Defense skills by 20% for every 2 levels (rounded up). | Logistics - Increases movement on the adventure map and improves travel on roads. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 2 | `homm3_dungeon_hero_2` | Arlach | Ballista - Increases the Ballista's Attack and Defense skills by 30% for every 5 levels (rounded up). | Scouting - Reveals a wider area of the adventure map and exposes enemy hero and army information. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 3 | `homm3_dungeon_hero_3` | Dace | Minotaurs - Increases the Speed of allied Minotaurs and Minotaur Kings by 1 and their Attack and Defense skills by 20% for every 5 levels (rounded up). | Troglodyte Specialist - Troglodyte creatures and their upgrades gain the current Olden Era growth and combat specialist package. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 4 | `homm3_dungeon_hero_4` | Ajit | Beholders - Increases the Speed of allied Beholders and Evil Eyes by 1 and their Attack and Defense skills by 20% for every 3 levels (rounded up). | Harpy Specialist - Harpy creatures and their upgrades gain the current Olden Era growth and combat specialist package. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 5 | `homm3_dungeon_hero_5` | Damacon | Gold | Leadership - Improves army Morale and gives troops a growing chance to act again. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 6 | `homm3_dungeon_hero_6` | Gunnar | Logistics | Estates - Generates additional gold each day, increasing as the hero gains levels. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 7 | `homm3_dungeon_hero_7` | Synca | Manticores - Increases the Speed of allied Manticores and Scorpicores by 1 and their Attack and Defense skills by 20% for every 6 levels (rounded up). | Beholder Specialist - Beholder creatures and their upgrades gain the current Olden Era growth and combat specialist package. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 8 | `homm3_dungeon_hero_8` | Shakti | Troglodytes - Increases the Speed of allied Troglodytes and Infernal Troglodytes by 1 and their Attack and Defense skills by 10% for every level (rounded up). | Fortune - Improves army Luck and increases the chance of critical hits as the hero gains levels. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 9 | `homm3_dungeon_hero_9` | Alamar | Resurrection - Casts Resurrection with effect increased by 5% for every N hero levels, where N is the level of the target creature. | Sorcery - Increases spell damage and weakens enemy spell pressure as the hero gains levels. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 10 | `homm3_dungeon_hero_10` | Jaegar | Mysticism | Mysticism - Increases the hero's mana reserves and allows one additional spell use each round. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 11 | `homm3_dungeon_hero_11` | Malekith | Sorcery | Medusa Specialist - Medusa creatures and their upgrades gain the current Olden Era growth and combat specialist package. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 12 | `homm3_dungeon_hero_12` | Jeddite | Resurrection - Casts Resurrection with effect increased by 5% for every N hero levels, where N is the level of the target creature. | Offense - Increases basic attack damage for the hero's army, with stronger gains at higher levels. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 13 | `homm3_dungeon_hero_13` | Geon | Eagle Eye | Minotaur Specialist - Minotaur creatures and their upgrades gain the current Olden Era growth and combat specialist package. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 14 | `homm3_dungeon_hero_14` | Deemer | Meteor Shower - Casts Meteor Shower with damage increased by 5% for every N hero levels, where N is the level of the target creature. | Pathfinding - Ignores rough-terrain movement penalties and restores movement after battles. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 15 | `homm3_dungeon_hero_15` | Sephinroth | Crystal | Manticore Specialist - Manticore creatures and their upgrades gain the current Olden Era growth and combat specialist package. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 16 | `homm3_dungeon_hero_16` | Darkstorn | Stone Skin - Casts Stone Skin with effect increased by 10 for level 1-2 creatures, by 8 for level 3-4 creatures, by 6 for level 5-6 creatures, and by 4 for level 7 creatures. | Armorer - Reduces incoming basic and ranged attack damage for the hero's army, with stronger gains at higher levels. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 17 | `homm3_dungeon_hero_17` | Mutare | Dragons - Increases allied Dragons' Attack and Defense by 10. | Red Dragon Specialist - Red Dragon creatures and their upgrades gain the current Olden Era growth and combat specialist package. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 18 | `homm3_dungeon_hero_18` | Mutare Drake | Dragons - Increases allied Dragons' Attack and Defense by 10. | Tactics - Improves pre-battle deployment and constricts the enemy deployment zone. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |

## Stronghold

| Slot | Hero SID | Hero | HoMM3/HotA source specialization | Current effective mod specialization | Effective layer |
|---:|---|---|---|---|---|
| 1 | `homm3_stronghold_hero_1` | Yog | Cyclopes - Increases the Speed of allied Cyclopes and Cyclops Kings by 1 and their Attack and Defense skills by 20% for every 6 levels (rounded up). | Logistics - Increases movement on the adventure map and improves travel on roads. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 2 | `homm3_stronghold_hero_2` | Gurnisson | Ballista - Increases the Ballista's Attack and Defense skills by 30% for every 5 levels (rounded up). | Scouting - Reveals a wider area of the adventure map and exposes enemy hero and army information. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 3 | `homm3_stronghold_hero_3` | Jabarkas | Orcs - Increases the Speed of allied Orcs and Orc Chieftains by 1 and their Attack and Defense skills by 20% for every 3 levels (rounded up). | H3 Goblin Specialist - H3 Goblin creatures and their upgrades gain the current Olden Era growth and combat specialist package. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 4 | `homm3_stronghold_hero_4` | Shiva | Rocs - Increases the Speed of allied Rocs and Thunderbirds by 1 and their Attack and Defense skills by 20% for every 5 levels (rounded up). | H3 Wolf Rider Specialist - H3 Wolf Rider creatures and their upgrades gain the current Olden Era growth and combat specialist package. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 5 | `homm3_stronghold_hero_5` | Gretchin | Goblins - Increases the Speed of allied Goblins and Hobgoblins by 1 and their Attack and Defense skills by 10% for every level (rounded up). | Leadership - Improves army Morale and gives troops a growing chance to act again. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 6 | `homm3_stronghold_hero_6` | Krellion | Ogres - Increases the Speed of allied Ogres and Ogre Magi by 1 and their Attack and Defense skills by 20% for every 4 levels (rounded up). | Estates - Generates additional gold each day, increasing as the hero gains levels. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 7 | `homm3_stronghold_hero_7` | Crag Hack | Offense | H3 Orc Specialist - H3 Orc creatures and their upgrades gain the current Olden Era growth and combat specialist package. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 8 | `homm3_stronghold_hero_8` | Tyraxor | Wolf Riders - Increases the Speed of allied Wolf Riders and Wolf Raiders by 1 and their Attack and Defense skills by 20% for every 2 levels (rounded up). | Fortune - Improves army Luck and increases the chance of critical hits as the hero gains levels. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 9 | `homm3_stronghold_hero_9` | Gird | Sorcery | Sorcery - Increases spell damage and weakens enemy spell pressure as the hero gains levels. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 10 | `homm3_stronghold_hero_10` | Vey | Ogres - Increases the Speed of allied Ogres and Ogre Magi by 1 and their Attack and Defense skills by 20% for every 4 levels (rounded up). | Mysticism - Increases the hero's mana reserves and allows one additional spell use each round. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 11 | `homm3_stronghold_hero_11` | Dessa | Logistics | H3 Ogre Specialist - H3 Ogre creatures and their upgrades gain the current Olden Era growth and combat specialist package. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 12 | `homm3_stronghold_hero_12` | Terek | Haste - Casts Haste with effect increased by 3 for level 1-4 creatures, by 2 for level 5-6 creatures, and by 1 for level 7 creatures. | Offense - Increases basic attack damage for the hero's army, with stronger gains at higher levels. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 13 | `homm3_stronghold_hero_13` | Zubin | Precision - Casts Precision with effect increased by 10 for level 1-2 creatures, by 8 for level 3-4 creatures, by 6 for level 5-6 creatures, and by 4 for level 7 creatures. | H3 Roc Specialist - H3 Roc creatures and their upgrades gain the current Olden Era growth and combat specialist package. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 14 | `homm3_stronghold_hero_14` | Gundula | Offense | Pathfinding - Ignores rough-terrain movement penalties and restores movement after battles. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 15 | `homm3_stronghold_hero_15` | Oris | Eagle Eye | H3 Cyclops Specialist - H3 Cyclops creatures and their upgrades gain the current Olden Era growth and combat specialist package. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 16 | `homm3_stronghold_hero_16` | Saurug | Gems | Armorer - Reduces incoming basic and ranged attack damage for the hero's army, with stronger gains at higher levels. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 17 | `homm3_stronghold_hero_17` | Gruezak | Ballista - Increases the Ballista's Attack and Defense skills by 30% for every 5 levels (rounded up). | H3 Behemoth Specialist - H3 Behemoth creatures and their upgrades gain the current Olden Era growth and combat specialist package. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 18 | `homm3_stronghold_hero_18` | Zog | Ogres - Increases the Speed of allied Ogres and Ogre Magi by 1 and their Attack and Defense skills by 20% for every 4 levels (rounded up). | Tactics - Improves pre-battle deployment and constricts the enemy deployment zone. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |

## Fortress

| Slot | Hero SID | Hero | HoMM3/HotA source specialization | Current effective mod specialization | Effective layer |
|---:|---|---|---|---|---|
| 1 | `homm3_fortress_hero_1` | Bron | Basilisks - Increases the Speed of allied Basilisks and Greater Basilisks by 1 and their Attack and Defense skills by 20% for every 4 levels (rounded up). | Logistics - Increases movement on the adventure map and improves travel on roads. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 2 | `homm3_fortress_hero_2` | Drakon | Gnolls - Increases the Speed of allied Gnolls and Gnoll Marauders by 1 and their Attack and Defense skills by 10% for every level (rounded up). | Scouting - Reveals a wider area of the adventure map and exposes enemy hero and army information. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 3 | `homm3_fortress_hero_3` | Wystan | Lizardmen - Increases the Speed of allied Lizardmen and Lizard Warriors by 1 and their Attack and Defense skills by 20% for every 2 levels (rounded up). | Gnoll Specialist - Gnoll creatures and their upgrades gain the current Olden Era growth and combat specialist package. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 4 | `homm3_fortress_hero_4` | Tazar | Armorer | Lizardman Specialist - Lizardman creatures and their upgrades gain the current Olden Era growth and combat specialist package. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 5 | `homm3_fortress_hero_5` | Alkin | Gorgon - Increases the Speed of allied Gorgons and Mighty Gorgons by 1 and their Attack and Defense skills by 20% for every 5 levels (rounded up). | Leadership - Improves army Morale and gives troops a growing chance to act again. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 6 | `homm3_fortress_hero_6` | Korbac | Serpent Flies - Increases the Speed of allied Serpent Flies and Dragon Flies by 1 and their Attack and Defense skills by 20% for every 3 levels (rounded up). | Estates - Generates additional gold each day, increasing as the hero gains levels. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 7 | `homm3_fortress_hero_7` | Gerwulf | Ballista - Increases the Ballista's Attack and Defense skills by 30% for every 5 levels (rounded up). | Serpent Fly Specialist - Serpent Fly creatures and their upgrades gain the current Olden Era growth and combat specialist package. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 8 | `homm3_fortress_hero_8` | Broghild | Wyverns - Increases the Speed of allied Wyverns and Wyvern Monarchs by 1 and their Attack and Defense skills by 20% for every 6 levels (rounded up). | Fortune - Improves army Luck and increases the chance of critical hits as the hero gains levels. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 9 | `homm3_fortress_hero_9` | Mirlanda | Weakness - Casts Weakness with effect increased by 4 for level 1-2 creatures, by 6 for level 3-4 creatures, by 8 for level 5-6 creatures, and by 10 for level 7 creatures. | Masterful Thick Hide - Starts with Masterful Thick Hide. This version also reduces ranged damage taken by 10%. | hero_overrides |
| 10 | `homm3_fortress_hero_10` | Rosic | Mysticism | Mysticism - Increases the hero's mana reserves and allows one additional spell use each round. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 11 | `homm3_fortress_hero_11` | Voy | Navigation | Basilisk Specialist - Basilisk creatures and their upgrades gain the current Olden Era growth and combat specialist package. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 12 | `homm3_fortress_hero_12` | Verdish | First Aid - Receives a 5% per level bonus to bonus Health provided by the First Aid Tent. | Offense - Increases basic attack damage for the hero's army, with stronger gains at higher levels. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 13 | `homm3_fortress_hero_13` | Merist | Stone Skin - Casts Stone Skin with effect increased by 10 for level 1-2 creatures, by 8 for level 3-4 creatures, by 6 for level 5-6 creatures, and by 4 for level 7 creatures. | Gorgon Specialist - Gorgon creatures and their upgrades gain the current Olden Era growth and combat specialist package. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 14 | `homm3_fortress_hero_14` | Styg | Sorcery | Pathfinding - Ignores rough-terrain movement penalties and restores movement after battles. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 15 | `homm3_fortress_hero_15` | Andra | Intelligence | Wyvern Specialist - Wyvern creatures and their upgrades gain the current Olden Era growth and combat specialist package. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 16 | `homm3_fortress_hero_16` | Tiva | Eagle Eye | Armorer - Reduces incoming basic and ranged attack damage for the hero's army, with stronger gains at higher levels. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 17 | `homm3_fortress_hero_17` | Tazar | Armorer | Hydra Specialist - Hydra creatures and their upgrades gain the current Olden Era growth and combat specialist package. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 18 | `homm3_fortress_hero_18` | Mirlanda | Weakness - Casts Weakness with effect increased by 4 for level 1-2 creatures, by 6 for level 3-4 creatures, by 8 for level 5-6 creatures, and by 10 for level 7 creatures. | Tactics - Improves pre-battle deployment and constricts the enemy deployment zone. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |

## Conflux

| Slot | Hero SID | Hero | HoMM3/HotA source specialization | Current effective mod specialization | Effective layer |
|---:|---|---|---|---|---|
| 1 | `homm3_conflux_hero_1` | Pasis | Psychic Elementals - Increases allied Psychic Elementals' and Magic Elementals' Attack and Defense by 5. | Logistics - Increases movement on the adventure map and improves travel on roads. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 2 | `homm3_conflux_hero_2` | Thunar | Earth Elementals - Increases allied Earth Elementals and Magma Elementals' Attack by 3, Defense by 2, and Damage by 5. | Scouting - Reveals a wider area of the adventure map and exposes enemy hero and army information. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 3 | `homm3_conflux_hero_3` | Ignissa | Fire Elementals - Increases allied Fire Elementals and Energy Elementals' Attack by 3, Defense by 4, and their Damage by 2. | Pixie Specialist - Pixie creatures and their upgrades gain the current Olden Era growth and combat specialist package. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 4 | `homm3_conflux_hero_4` | Lacus | Water Elementals - Increases allied Water Elementals' and Ice Elementals' Attack by 12. | Air Elemental Specialist - Air Elemental creatures and their upgrades gain the current Olden Era growth and combat specialist package. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 5 | `homm3_conflux_hero_5` | Monere | Psychic Elementals - Increases allied Psychic Elementals' and Magic Elementals' Attack and Defense by 5. | Leadership - Improves army Morale and gives troops a growing chance to act again. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 6 | `homm3_conflux_hero_6` | Erdamon | Dragons - Increases allied Earth Elementals and Magma Elementals' Attack by 3, Defense by 2, and Damage by 5. | Estates - Generates additional gold each day, increasing as the hero gains levels. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 7 | `homm3_conflux_hero_7` | Fiur | Fire Elementals - Increases allied Fire Elementals and Energy Elementals' Attack by 3, Defense by 4, and their Damage by 2. | Water Elemental Specialist - Water Elemental creatures and their upgrades gain the current Olden Era growth and combat specialist package. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 8 | `homm3_conflux_hero_8` | Kalt | Water Elementals - Increases allied Water Elementals' and Ice Elementals' Attack by 12. | Fortune - Improves army Luck and increases the chance of critical hits as the hero gains levels. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 9 | `homm3_conflux_hero_9` | Luna | Fire Wall, Fire Wall Tooltip - Increases the Damage from Fire Wall by 25%. | Sorcery - Increases spell damage and weakens enemy spell pressure as the hero gains levels. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 10 | `homm3_conflux_hero_10` | Brissa | Haste - Casts Haste with effect increased by 3 for level 1-4 creatures, by 2 for level 5-6 creatures, and by 1 for level 7 creatures. | Mysticism - Increases the hero's mana reserves and allows one additional spell use each round. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 11 | `homm3_conflux_hero_11` | Ciele | Magic Arrow | Fire Elemental Specialist - Fire Elemental creatures and their upgrades gain the current Olden Era growth and combat specialist package. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 12 | `homm3_conflux_hero_12` | Labetha | Stone Skin - Casts Stone Skin with effect increased by 10 for level 1-2 creatures, by 8 for level 3-4 creatures, by 6 for level 5-6 creatures, and by 4 for level 7 creatures. | Offense - Increases basic attack damage for the hero's army, with stronger gains at higher levels. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 13 | `homm3_conflux_hero_13` | Inteus | Bloodlust - Casts Bloodlust with effect increased by 10 for level 1-2 creatures, by 8 for level 3-4 creatures, by 6 for level 5-6 creatures, and by 4 for level 7 creatures. | Earth Elemental Specialist - Earth Elemental creatures and their upgrades gain the current Olden Era growth and combat specialist package. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 14 | `homm3_conflux_hero_14` | Aenain | Disrupting Ray - Casts Disrupting Ray with effect increased by 10. | Pathfinding - Ignores rough-terrain movement penalties and restores movement after battles. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 15 | `homm3_conflux_hero_15` | Gelare | Gold | Psychic Elemental Specialist - Psychic Elemental creatures and their upgrades gain the current Olden Era growth and combat specialist package. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 16 | `homm3_conflux_hero_16` | Grindan | Gold | Armorer - Reduces incoming basic and ranged attack damage for the hero's army, with stronger gains at higher levels. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |

## Cove

| Slot | Hero SID | Hero | HoMM3/HotA source specialization | Current effective mod specialization | Effective layer |
|---:|---|---|---|---|---|
| 1 | `homm3_cove_hero_1` | Corkes | Offense - Receives a 5% per level bonus to Offense skill percentage. | Logistics - Increases movement on the adventure map and improves travel on roads. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 2 | `homm3_cove_hero_2` | Jeremy | Cannon - Increases the Cannon's Attack and Defense skills by 20% for every 6 levels (rounded up). | Scouting - Reveals a wider area of the adventure map and exposes enemy hero and army information. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 3 | `homm3_cove_hero_3` | Illor | Stormbirds - Increases the Speed of allied Stormbirds and Ayssids by 1 and their Attack and Defense skills by 20% for every 4 levels (rounded up). | Nymph Specialist - Nymph creatures and their upgrades gain the current Olden Era growth and combat specialist package. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 4 | `homm3_cove_hero_4` | Elmore | Navigation - Receives a 5% per level bonus to movement points at sea. | Crew Mate Specialist - Crew Mate creatures and their upgrades gain the current Olden Era growth and combat specialist package. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 5 | `homm3_cove_hero_5` | Derek | Crew Mates - Increases the Speed of allied Crew Mates and Seamen by 1 and their Attack and Defense skills by 20% for every 2 levels (rounded up). | Leadership - Improves army Morale and gives troops a growing chance to act again. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 6 | `homm3_cove_hero_6` | Leena | +350 Gold - Increases kingdom's income by 350 gold per day. | Estates - Generates additional gold each day, increasing as the hero gains levels. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 7 | `homm3_cove_hero_7` | Anabel | Pirates - Increases the Speed of allied Pirates, Corsairs and Sea Dogs by 1 and their Attack and Defense skills by 20% for every 3 levels (rounded up). | Pirate Specialist - Pirate creatures and their upgrades gain the current Olden Era growth and combat specialist package. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 8 | `homm3_cove_hero_8` | Cassiopeia | Nymphs - Increases the Speed of allied Nymphs and Oceanids by 1 and their Attack and Defense skills by 10% for every level (rounded up). | Fortune - Improves army Luck and increases the chance of critical hits as the hero gains levels. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 9 | `homm3_cove_hero_9` | Casmetra | Sea Witches - Increases the Speed of allied Sea Witches and Sorceresses by 1 and their Attack and Defense skills by 20% for every 5 levels (rounded up). | Masterful Shackles - Starts with Masterful Shackles. This version costs less mana. | hero_overrides |
| 10 | `homm3_cove_hero_10` | Eovacius | Clone - Each battle the first cast of Clone spell summons 2 clones of the target unit. | Mysticism - Increases the hero's mana reserves and allows one additional spell use each round. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 11 | `homm3_cove_hero_11` | Spint | Sorcery - Receives a 5% per level bonus to Sorcery skill percentage. | Stormbird Specialist - Stormbird creatures and their upgrades gain the current Olden Era growth and combat specialist package. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 12 | `homm3_cove_hero_12` | Andal | +1 Crystal - Increases kingdom's crystal production by 1 per day. | Offense - Increases basic attack damage for the hero's army, with stronger gains at higher levels. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 13 | `homm3_cove_hero_13` | Manfred | Fireball - Casts Fireball with damage increased by 10% for every N hero levels, where N is the level of the target creature. | Sea Witch Specialist - Sea Witch creatures and their upgrades gain the current Olden Era growth and combat specialist package. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 14 | `homm3_cove_hero_14` | Zilare | Forgetfulness - Casts Forgetfulness with double duration. | Pathfinding - Ignores rough-terrain movement penalties and restores movement after battles. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 15 | `homm3_cove_hero_15` | Astra | Cure - Casts Cure with effect increased by 3% for every N hero levels, where N is the level of the target creature. | Nix Specialist - Nix creatures and their upgrades gain the current Olden Era growth and combat specialist package. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 16 | `homm3_cove_hero_16` | Dargem | Air Shield - Casts Air Shield with effect increased by 10% for every N hero levels, where N is the level of the target creature. | Masterful Temporal Spheres - Starts with Masterful Temporal Spheres. This version places one additional trap. | hero_overrides |
| 17 | `homm3_cove_hero_17` | Balfour | Forgetfulness - Casts Forgetfulness with double duration. | Sea Serpent Specialist - Sea Serpent creatures and their upgrades gain the current Olden Era growth and combat specialist package. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |
| 18 | `homm3_cove_hero_18` | Miriam | Scouting - Increases Scouting radius by 1 for every 6 levels. | Tactics - Improves pre-battle deployment and constricts the enemy deployment zone. This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity. | hero_overrides |

## Source Path Audit

Use these source paths when a row needs deeper inspection. Paths are grouped by current hero SID.

| Hero SID | Hero | Source path |
|---|---|---|
| `homm3_castle_hero_1` | Orrin | `C:\Users\<user>\AppData\Roaming\VCMI\config\heroes\castle.json` |
| `homm3_castle_hero_2` | Valeska | `content.zip!/config/hotaGameBalance/castle/valeska.json` |
| `homm3_castle_hero_3` | Edric | `content.zip!/config/hotaGameBalance/castle/edric.json` |
| `homm3_castle_hero_4` | Sylvia | `C:\Users\<user>\AppData\Roaming\VCMI\config\heroes\castle.json` |
| `homm3_castle_hero_5` | Lord Haart | `C:\Users\<user>\AppData\Roaming\VCMI\config\heroes\castle.json` |
| `homm3_castle_hero_6` | Sorsha | `content.zip!/config/hotaGameBalance/castle/sorsha.json` |
| `homm3_castle_hero_7` | Christian | `content.zip!/config/hotaGameBalance/castle/christian.json` |
| `homm3_castle_hero_8` | Tyris | `content.zip!/config/hotaGameBalance/castle/tyris.json` |
| `homm3_castle_hero_9` | Rion | `content.zip!/config/hotaGameBalance/castle/rion.json` |
| `homm3_castle_hero_10` | Adela | `content.zip!/config/hotaGameBalance/castle/adela.json` |
| `homm3_castle_hero_11` | Cuthbert | `content.zip!/config/hotaGameBalance/castle/cuthbert.json` |
| `homm3_castle_hero_12` | Adelaide | `content.zip!/config/hotaGameBalance/castle/adelaide.json` |
| `homm3_castle_hero_13` | Ingham | `content.zip!/config/hotaGameBalance/castle/ingham.json` |
| `homm3_castle_hero_14` | Sanya | `C:\Users\<user>\AppData\Roaming\VCMI\config\heroes\castle.json` |
| `homm3_castle_hero_15` | Loynis | `content.zip!/config/hotaGameBalance/castle/loynis.json` |
| `homm3_castle_hero_16` | Caitlin | `C:\Users\<user>\AppData\Roaming\VCMI\config\heroes\castle.json` |
| `homm3_castle_hero_17` | Sir Mullich | `C:\Users\<user>\AppData\Roaming\VCMI\config\heroes\special.json` |
| `homm3_castle_hero_18` | Beatrice | `V:\Games\Olden Era Playtest Tweak\vcmi\Mods\hota\mods\heroes\Content\config\castle\heroes\beatrice.json` |
| `homm3_rampart_hero_1` | Mephala | `C:\Users\<user>\AppData\Roaming\VCMI\config\heroes\rampart.json` |
| `homm3_rampart_hero_2` | Ufretin | `content.zip!/config/hotaGameBalance/rampart/ufretin.json` |
| `homm3_rampart_hero_3` | Jenova | `C:\Users\<user>\AppData\Roaming\VCMI\config\heroes\rampart.json` |
| `homm3_rampart_hero_4` | Ryland | `content.zip!/config/hotaGameBalance/rampart/ryland.json` |
| `homm3_rampart_hero_5` | Thorgrim | `C:\Users\<user>\AppData\Roaming\VCMI\config\heroes\rampart.json` |
| `homm3_rampart_hero_6` | Ivor | `content.zip!/config/hotaGameBalance/rampart/ivor.json` |
| `homm3_rampart_hero_7` | Clancy | `content.zip!/config/hotaGameBalance/rampart/clancy.json` |
| `homm3_rampart_hero_8` | Kyrre | `C:\Users\<user>\AppData\Roaming\VCMI\config\heroes\rampart.json` |
| `homm3_rampart_hero_9` | Coronius | `content.zip!/config/hotaGameBalance/rampart/coroniusDUMMY.json` |
| `homm3_rampart_hero_10` | Uland | `content.zip!/config/hotaGameBalance/rampart/uland.json` |
| `homm3_rampart_hero_11` | Elleshar | `C:\Users\<user>\AppData\Roaming\VCMI\config\heroes\rampart.json` |
| `homm3_rampart_hero_12` | Gem | `content.zip!/config/hotaGameBalance/rampart/gem.json` |
| `homm3_rampart_hero_13` | Malcom | `C:\Users\<user>\AppData\Roaming\VCMI\config\heroes\rampart.json` |
| `homm3_rampart_hero_14` | Melodia | `C:\Users\<user>\AppData\Roaming\VCMI\config\heroes\rampart.json` |
| `homm3_rampart_hero_15` | Alagar | `content.zip!/config/hotaGameBalance/rampart/alagar.json` |
| `homm3_rampart_hero_16` | Aeris | `content.zip!/config/hotaGameBalance/rampart/aeris.json` |
| `homm3_rampart_hero_17` | Mephala | `C:\Users\<user>\AppData\Roaming\VCMI\config\heroes\rampart.json` |
| `homm3_rampart_hero_18` | Gem | `content.zip!/config/hotaGameBalance/rampart/gem.json` |
| `homm3_tower_hero_1` | Piquedram | `content.zip!/config/hotaGameBalance/tower/piquedram.json` |
| `homm3_tower_hero_2` | Thane | `content.zip!/config/hotaGameBalance/tower/thane.json` |
| `homm3_tower_hero_3` | Josephine | `content.zip!/config/hotaGameBalance/tower/josephine.json` |
| `homm3_tower_hero_4` | Neela | `C:\Users\<user>\AppData\Roaming\VCMI\config\heroes\tower.json` |
| `homm3_tower_hero_5` | Torosar | `content.zip!/config/hotaGameBalance/tower/torosar.json` |
| `homm3_tower_hero_6` | Fafner | `content.zip!/config/hotaGameBalance/tower/fafner.json` |
| `homm3_tower_hero_7` | Rissa | `C:\Users\<user>\AppData\Roaming\VCMI\config\heroes\tower.json` |
| `homm3_tower_hero_8` | Iona | `content.zip!/config/hotaGameBalance/tower/iona.json` |
| `homm3_tower_hero_9` | Astral | `content.zip!/config/hotaGameBalance/tower/astral.json` |
| `homm3_tower_hero_10` | Halon | `C:\Users\<user>\AppData\Roaming\VCMI\config\heroes\tower.json` |
| `homm3_tower_hero_11` | Serena | `C:\Users\<user>\AppData\Roaming\VCMI\config\heroes\tower.json` |
| `homm3_tower_hero_12` | Daremyth | `C:\Users\<user>\AppData\Roaming\VCMI\config\heroes\tower.json` |
| `homm3_tower_hero_13` | Theodorus | `content.zip!/config/hotaGameBalance/tower/theodorus.json` |
| `homm3_tower_hero_14` | Solmyr | `content.zip!/config/hotaGameBalance/tower/solmyr.json` |
| `homm3_tower_hero_15` | Cyra | `content.zip!/config/hotaGameBalance/tower/cyra.json` |
| `homm3_tower_hero_16` | Aine | `C:\Users\<user>\AppData\Roaming\VCMI\config\heroes\tower.json` |
| `homm3_tower_hero_17` | Cyra | `content.zip!/config/hotaGameBalance/tower/cyra.json` |
| `homm3_tower_hero_18` | Aine | `C:\Users\<user>\AppData\Roaming\VCMI\config\heroes\tower.json` |
| `homm3_inferno_hero_1` | Fiona | `content.zip!/config/hotaGameBalance/inferno/fiona.json` |
| `homm3_inferno_hero_2` | Rashka | `content.zip!/config/hotaGameBalance/inferno/rashka.json` |
| `homm3_inferno_hero_3` | Marius | `content.zip!/config/hotaGameBalance/inferno/marius.json` |
| `homm3_inferno_hero_4` | Ignatius | `content.zip!/config/hotaGameBalance/inferno/ignatius.json` |
| `homm3_inferno_hero_5` | Octavia | `C:\Users\<user>\AppData\Roaming\VCMI\config\heroes\inferno.json` |
| `homm3_inferno_hero_6` | Calh | `content.zip!/config/hotaGameBalance/inferno/calh.json` |
| `homm3_inferno_hero_7` | Pyre | `content.zip!/config/hotaGameBalance/inferno/pyre.json` |
| `homm3_inferno_hero_8` | Nymus | `content.zip!/config/hotaGameBalance/inferno/nymus.json` |
| `homm3_inferno_hero_9` | Ayden | `C:\Users\<user>\AppData\Roaming\VCMI\config\heroes\inferno.json` |
| `homm3_inferno_hero_10` | Xyron | `content.zip!/config/hotaGameBalance/inferno/xyron.json` |
| `homm3_inferno_hero_11` | Axsis | `C:\Users\<user>\AppData\Roaming\VCMI\config\heroes\inferno.json` |
| `homm3_inferno_hero_12` | Olema | `content.zip!/config/hotaGameBalance/inferno/olema.json` |
| `homm3_inferno_hero_13` | Calid | `C:\Users\<user>\AppData\Roaming\VCMI\config\heroes\inferno.json` |
| `homm3_inferno_hero_14` | Ash | `content.zip!/config/hotaGameBalance/inferno/ash.json` |
| `homm3_inferno_hero_15` | Zydar | `C:\Users\<user>\AppData\Roaming\VCMI\config\heroes\inferno.json` |
| `homm3_inferno_hero_16` | Xarfax | `content.zip!/config/hotaGameBalance/inferno/xarfax.json` |
| `homm3_inferno_hero_17` | Athe | `V:\Games\Olden Era Playtest Tweak\vcmi\Mods\hota\mods\heroes\Content\config\inferno\heroes\athe.json` |
| `homm3_inferno_hero_18` | Miseria | `content.zip!/config/hotaGameBalance/inferno/miseria.json` |
| `homm3_necropolis_hero_1` | Straker | `content.zip!/config/hotaGameBalance/necropolis/straker.json` |
| `homm3_necropolis_hero_2` | Vokial | `content.zip!/config/hotaGameBalance/necropolis/vokial.json` |
| `homm3_necropolis_hero_3` | Moandor | `content.zip!/config/hotaGameBalance/necropolis/moandor.json` |
| `homm3_necropolis_hero_4` | Charna | `content.zip!/config/hotaGameBalance/necropolis/charna.json` |
| `homm3_necropolis_hero_5` | Tamika | `content.zip!/config/hotaGameBalance/necropolis/tamika.json` |
| `homm3_necropolis_hero_6` | Isra | `C:\Users\<user>\AppData\Roaming\VCMI\config\heroes\necropolis.json` |
| `homm3_necropolis_hero_7` | Clavius | `C:\Users\<user>\AppData\Roaming\VCMI\config\heroes\necropolis.json` |
| `homm3_necropolis_hero_8` | Galthran | `content.zip!/config/hotaGameBalance/necropolis/galthran.json` |
| `homm3_necropolis_hero_9` | Septienna | `content.zip!/config/hotaGameBalance/necropolis/septienna.json` |
| `homm3_necropolis_hero_10` | Aislinn | `content.zip!/config/hotaGameBalance/necropolis/aislinn.json` |
| `homm3_necropolis_hero_11` | Sandro | `C:\Users\<user>\AppData\Roaming\VCMI\config\heroes\necropolis.json` |
| `homm3_necropolis_hero_12` | Nimbus | `C:\Users\<user>\AppData\Roaming\VCMI\config\heroes\necropolis.json` |
| `homm3_necropolis_hero_13` | Thant | `content.zip!/config/hotaGameBalance/necropolis/thant.json` |
| `homm3_necropolis_hero_14` | Xsi | `content.zip!/config/hotaGameBalance/necropolis/xsi.json` |
| `homm3_necropolis_hero_15` | Vidomina | `C:\Users\<user>\AppData\Roaming\VCMI\config\heroes\necropolis.json` |
| `homm3_necropolis_hero_16` | Nagash | `C:\Users\<user>\AppData\Roaming\VCMI\config\heroes\necropolis.json` |
| `homm3_necropolis_hero_17` | Boyd | `content.zip!/config/hotaGameBalance/necropolis/boyd.json` |
| `homm3_necropolis_hero_18` | Ranloo | `content.zip!/config/hotaGameBalance/necropolis/ranloo.json` |
| `homm3_dungeon_hero_1` | Lorelei | `content.zip!/config/hotaGameBalance/dungeon/lorelei.json` |
| `homm3_dungeon_hero_2` | Arlach | `content.zip!/config/hotaGameBalance/dungeon/arlach.json` |
| `homm3_dungeon_hero_3` | Dace | `content.zip!/config/hotaGameBalance/dungeon/dace.json` |
| `homm3_dungeon_hero_4` | Ajit | `content.zip!/config/hotaGameBalance/dungeon/ajit.json` |
| `homm3_dungeon_hero_5` | Damacon | `C:\Users\<user>\AppData\Roaming\VCMI\config\heroes\dungeon.json` |
| `homm3_dungeon_hero_6` | Gunnar | `C:\Users\<user>\AppData\Roaming\VCMI\config\heroes\dungeon.json` |
| `homm3_dungeon_hero_7` | Synca | `content.zip!/config/hotaGameBalance/dungeon/synca.json` |
| `homm3_dungeon_hero_8` | Shakti | `content.zip!/config/hotaGameBalance/dungeon/shakti.json` |
| `homm3_dungeon_hero_9` | Alamar | `content.zip!/config/hotaGameBalance/dungeon/alamar.json` |
| `homm3_dungeon_hero_10` | Jaegar | `C:\Users\<user>\AppData\Roaming\VCMI\config\heroes\dungeon.json` |
| `homm3_dungeon_hero_11` | Malekith | `C:\Users\<user>\AppData\Roaming\VCMI\config\heroes\dungeon.json` |
| `homm3_dungeon_hero_12` | Jeddite | `content.zip!/config/hotaGameBalance/dungeon/jeddite.json` |
| `homm3_dungeon_hero_13` | Geon | `C:\Users\<user>\AppData\Roaming\VCMI\config\heroes\dungeon.json` |
| `homm3_dungeon_hero_14` | Deemer | `content.zip!/config/hotaGameBalance/dungeon/deemer.json` |
| `homm3_dungeon_hero_15` | Sephinroth | `C:\Users\<user>\AppData\Roaming\VCMI\config\heroes\dungeon.json` |
| `homm3_dungeon_hero_16` | Darkstorn | `content.zip!/config/hotaGameBalance/dungeon/darkstorn.json` |
| `homm3_dungeon_hero_17` | Mutare | `content.zip!/config/hotaGameBalance/dungeon/mutare.json` |
| `homm3_dungeon_hero_18` | Mutare Drake | `content.zip!/config/hotaGameBalance/dungeon/mutareDrake.json` |
| `homm3_stronghold_hero_1` | Yog | `content.zip!/config/hotaGameBalance/stronghold/yog.json` |
| `homm3_stronghold_hero_2` | Gurnisson | `content.zip!/config/hotaGameBalance/stronghold/gurnisson.json` |
| `homm3_stronghold_hero_3` | Jabarkas | `content.zip!/config/hotaGameBalance/stronghold/jabarkas.json` |
| `homm3_stronghold_hero_4` | Shiva | `content.zip!/config/hotaGameBalance/stronghold/shiva.json` |
| `homm3_stronghold_hero_5` | Gretchin | `content.zip!/config/hotaGameBalance/stronghold/gretchin.json` |
| `homm3_stronghold_hero_6` | Krellion | `content.zip!/config/hotaGameBalance/stronghold/krellion.json` |
| `homm3_stronghold_hero_7` | Crag Hack | `C:\Users\<user>\AppData\Roaming\VCMI\config\heroes\stronghold.json` |
| `homm3_stronghold_hero_8` | Tyraxor | `content.zip!/config/hotaGameBalance/stronghold/tyraxor.json` |
| `homm3_stronghold_hero_9` | Gird | `C:\Users\<user>\AppData\Roaming\VCMI\config\heroes\stronghold.json` |
| `homm3_stronghold_hero_10` | Vey | `content.zip!/config/hotaGameBalance/stronghold/vey.json` |
| `homm3_stronghold_hero_11` | Dessa | `C:\Users\<user>\AppData\Roaming\VCMI\config\heroes\stronghold.json` |
| `homm3_stronghold_hero_12` | Terek | `content.zip!/config/hotaGameBalance/stronghold/terek.json` |
| `homm3_stronghold_hero_13` | Zubin | `content.zip!/config/hotaGameBalance/stronghold/zubin.json` |
| `homm3_stronghold_hero_14` | Gundula | `C:\Users\<user>\AppData\Roaming\VCMI\config\heroes\stronghold.json` |
| `homm3_stronghold_hero_15` | Oris | `C:\Users\<user>\AppData\Roaming\VCMI\config\heroes\stronghold.json` |
| `homm3_stronghold_hero_16` | Saurug | `C:\Users\<user>\AppData\Roaming\VCMI\config\heroes\stronghold.json` |
| `homm3_stronghold_hero_17` | Gruezak | `content.zip!/config/hotaGameBalance/stronghold/gruezak.json` |
| `homm3_stronghold_hero_18` | Zog | `content.zip!/config/hotaGameBalance/stronghold/zog.json` |
| `homm3_fortress_hero_1` | Bron | `content.zip!/config/hotaGameBalance/fortress/bron.json` |
| `homm3_fortress_hero_2` | Drakon | `content.zip!/config/hotaGameBalance/fortress/drakon.json` |
| `homm3_fortress_hero_3` | Wystan | `content.zip!/config/hotaGameBalance/fortress/wystan.json` |
| `homm3_fortress_hero_4` | Tazar | `C:\Users\<user>\AppData\Roaming\VCMI\config\heroes\fortress.json` |
| `homm3_fortress_hero_5` | Alkin | `content.zip!/config/hotaGameBalance/fortress/alkin.json` |
| `homm3_fortress_hero_6` | Korbac | `content.zip!/config/hotaGameBalance/fortress/korbac.json` |
| `homm3_fortress_hero_7` | Gerwulf | `content.zip!/config/hotaGameBalance/fortress/gerwulf.json` |
| `homm3_fortress_hero_8` | Broghild | `content.zip!/config/hotaGameBalance/fortress/broghild.json` |
| `homm3_fortress_hero_9` | Mirlanda | `content.zip!/config/hotaGameBalance/fortress/mirlanda.json` |
| `homm3_fortress_hero_10` | Rosic | `C:\Users\<user>\AppData\Roaming\VCMI\config\heroes\fortress.json` |
| `homm3_fortress_hero_11` | Voy | `C:\Users\<user>\AppData\Roaming\VCMI\config\heroes\fortress.json` |
| `homm3_fortress_hero_12` | Verdish | `content.zip!/config/hotaGameBalance/fortress/verdish.json` |
| `homm3_fortress_hero_13` | Merist | `content.zip!/config/hotaGameBalance/fortress/merist.json` |
| `homm3_fortress_hero_14` | Styg | `C:\Users\<user>\AppData\Roaming\VCMI\config\heroes\fortress.json` |
| `homm3_fortress_hero_15` | Andra | `C:\Users\<user>\AppData\Roaming\VCMI\config\heroes\fortress.json` |
| `homm3_fortress_hero_16` | Tiva | `C:\Users\<user>\AppData\Roaming\VCMI\config\heroes\fortress.json` |
| `homm3_fortress_hero_17` | Tazar | `C:\Users\<user>\AppData\Roaming\VCMI\config\heroes\fortress.json` |
| `homm3_fortress_hero_18` | Mirlanda | `content.zip!/config/hotaGameBalance/fortress/mirlanda.json` |
| `homm3_conflux_hero_1` | Pasis | `content.zip!/config/hotaGameBalance/conflux/pasis.json` |
| `homm3_conflux_hero_2` | Thunar | `content.zip!/config/hotaGameBalance/conflux/thunar.json` |
| `homm3_conflux_hero_3` | Ignissa | `content.zip!/config/hotaGameBalance/conflux/ignissa.json` |
| `homm3_conflux_hero_4` | Lacus | `content.zip!/config/hotaGameBalance/conflux/lacus.json` |
| `homm3_conflux_hero_5` | Monere | `content.zip!/config/hotaGameBalance/conflux/monere.json` |
| `homm3_conflux_hero_6` | Erdamon | `content.zip!/config/hotaGameBalance/conflux/erdamon.json` |
| `homm3_conflux_hero_7` | Fiur | `content.zip!/config/hotaGameBalance/conflux/fiur.json` |
| `homm3_conflux_hero_8` | Kalt | `content.zip!/config/hotaGameBalance/conflux/kalt.json` |
| `homm3_conflux_hero_9` | Luna | `content.zip!/config/hotaGameBalance/conflux/luna.json` |
| `homm3_conflux_hero_10` | Brissa | `content.zip!/config/hotaGameBalance/conflux/brissa.json` |
| `homm3_conflux_hero_11` | Ciele | `C:\Users\<user>\AppData\Roaming\VCMI\config\heroes\conflux.json` |
| `homm3_conflux_hero_12` | Labetha | `content.zip!/config/hotaGameBalance/conflux/labetha.json` |
| `homm3_conflux_hero_13` | Inteus | `content.zip!/config/hotaGameBalance/conflux/inteus.json` |
| `homm3_conflux_hero_14` | Aenain | `content.zip!/config/hotaGameBalance/conflux/aenain.json` |
| `homm3_conflux_hero_15` | Gelare | `C:\Users\<user>\AppData\Roaming\VCMI\config\heroes\conflux.json` |
| `homm3_conflux_hero_16` | Grindan | `C:\Users\<user>\AppData\Roaming\VCMI\config\heroes\conflux.json` |
| `homm3_cove_hero_1` | Corkes | `V:\Games\Olden Era Playtest Tweak\vcmi\Mods\hota\mods\cove\Content\config\hota\cove\heroes\corkes.json` |
| `homm3_cove_hero_2` | Jeremy | `content.zip!/config/hotaGameBalance/cove/jeremy.json` |
| `homm3_cove_hero_3` | Illor | `content.zip!/config/hotaGameBalance/cove/illor.json` |
| `homm3_cove_hero_4` | Elmore | `V:\Games\Olden Era Playtest Tweak\vcmi\Mods\hota\mods\cove\Content\config\hota\cove\heroes\elmore.json` |
| `homm3_cove_hero_5` | Derek | `content.zip!/config/hotaGameBalance/cove/derek.json` |
| `homm3_cove_hero_6` | Leena | `V:\Games\Olden Era Playtest Tweak\vcmi\Mods\hota\mods\cove\Content\config\hota\cove\heroes\leena.json` |
| `homm3_cove_hero_7` | Anabel | `content.zip!/config/hotaGameBalance/cove/anabel.json` |
| `homm3_cove_hero_8` | Cassiopeia | `content.zip!/config/hotaGameBalance/cove/cassiopeia.json` |
| `homm3_cove_hero_9` | Casmetra | `content.zip!/config/hotaGameBalance/cove/casmetra.json` |
| `homm3_cove_hero_10` | Eovacius | `V:\Games\Olden Era Playtest Tweak\vcmi\Mods\hota\mods\cove\Content\config\hota\cove\heroes\eovacius.json` |
| `homm3_cove_hero_11` | Spint | `V:\Games\Olden Era Playtest Tweak\vcmi\Mods\hota\mods\cove\Content\config\hota\cove\heroes\spint.json` |
| `homm3_cove_hero_12` | Andal | `V:\Games\Olden Era Playtest Tweak\vcmi\Mods\hota\mods\cove\Content\config\hota\cove\heroes\andal.json` |
| `homm3_cove_hero_13` | Manfred | `content.zip!/config/hotaGameBalance/cove/manfred.json` |
| `homm3_cove_hero_14` | Zilare | `content.zip!/config/hotaGameBalance/cove/zilareDUMMY.json` |
| `homm3_cove_hero_15` | Astra | `content.zip!/config/hotaGameBalance/cove/astraDUMMY.json` |
| `homm3_cove_hero_16` | Dargem | `content.zip!/config/hotaGameBalance/cove/dargem.json` |
| `homm3_cove_hero_17` | Balfour | `V:\Games\Olden Era Playtest Tweak\vcmi\Mods\hota\mods\cove\Content\config\hota\cove\heroes\balfour.json` |
| `homm3_cove_hero_18` | Miriam | `V:\Games\Olden Era Playtest Tweak\vcmi\Mods\hota\mods\cove\Content\config\hota\cove\heroes\miriam.json` |
