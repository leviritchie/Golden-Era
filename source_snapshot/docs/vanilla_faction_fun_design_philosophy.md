# Vanilla Faction Fun Design Philosophy

This document summarizes the fun-facing design patterns of the live native Olden Era factions in the Golden Era Steam install. "Vanilla" here means the six native Olden Era factions shipped in the live archive, not the HoMM3 custom faction rows that also exist in the same modded `Core.zip`.

Primary source inspected:

`V:\SteamLibrary\steamapps\common\Heroes of Might and Magic Olden Era - Golden Era\HeroesOldenEra_Data\StreamingAssets\Core.zip`

## Source Inventory

Native faction boundary:

| Faction id | Display name | Biome | Rare resource | Evidence |
| --- | --- | --- | --- | --- |
| `human` | Temple | `Grass` | `gemstones` | `DB/fractions/1_human.json`, `Lang/english/texts/cities.json` |
| `undead` | Necropolis | `Deathland` | `mercury` | `DB/fractions/2_undead.json`, `Lang/english/texts/cities.json` |
| `dungeon` | Dungeon | `Dirt` | `gemstones` | `DB/fractions/3_dungeon.json`, `Lang/english/texts/cities.json` |
| `nature` | Grove | `Autumn` | `crystals` | `DB/fractions/4_nature.json`, `Lang/english/texts/cities.json` |
| `demon` | Hive | `Lava` | `crystals` | `DB/fractions/5_demon.json`, `Lang/english/texts/cities.json` |
| `unfrozen` | Schism | `Snow` | `mercury` | `DB/fractions/6_unfrozen.json`, `Lang/english/texts/cities.json` |

Schema notes found in the live archive:

- Faction display names are localized from `Lang/english/texts/cities.json`, not `Lang/english/texts/fractions.json` for these six native ids.
- Unit gameplay and presentation are split: logic rows live under `DB/units/units_logics/<folder>/*.json`; ability names, passive names, class labels, and presentation-side ability cards live under `DB/units/units_views/<folder>/*.json`.
- Native unit folders are `humans`, `undead`, `dungeon`, `nature`, `demons`, and `unfrozen`.
- Native hero folders are `humans`, `necros`, `dungeon`, `nature`, `demons`, and `unfrozen`; Necropolis uses `necros` for hero files while unit logic uses `undead`.
- Hero specializations live in `DB/heroes_specializations/specializations_human.json`, `specializations_necro.json`, `specializations_dungeon.json`, `specializations_nature.json`, `specializations_demon.json`, and `specializations_unfrozen.json`.
- City/building logic lives in `DB/objects_logic/cities/<faction>_city.json`. Every native faction has seven hire buildings, a main/tavern/market/magic/wall/economy shell, and a small number of faction-specific building categories.
- Faction laws live in `DB/fractions_laws/fractions_laws_table_<faction>.json`; their visible law order is arranged in `fractionLawsLines` inside each `DB/fractions/*.json` row.
- Native law tracks use five unlock bands: `countToUnlock` 0, 5, 15, 30, and 50. Counts differ by faction, so custom factions should derive law layout from the chosen donor pattern rather than hard-coding one global law grid.

Native hero roster evidence:

- Temple, `DB/heroes/humans/*.json`: Ister/Wayfarer, Leon Sticky-Fingers/Pathfinder, John Johnson/Salt of the Earth, Kestrel/Jaeger, Aeos the Exalted/Rousing Presence, Heretic Avis/Gem Seeker, Keandra/Jouster, Lord Edgar/True Lord, Old Lord Mandall/Heroic Smite, Merry Elias/Spiritual Vigor, Pip/Wish to Learn, Zenith/Weaving the Light, Lia the Untethered One/Radiating Knowledge, Julius/Compassionate Healer, Vesper/Blessing, Anastasia the Meek/Hymn to Arina, Nadir/Heart of Hearts, Clarissa/Wealthy.
- Necropolis, `DB/heroes/necros/*.json`: Bulwark/Built Different, King-of-Kings/Charismatic, Onkos/Perfect Puppets, Kel'Ghul/Dreadful War, Natalida/Part of a Pack, Artorius Veritas/Drive 'em Crazy, Marl/Languid Soil, Tarius/Undead Legion, Zam/Alchemist, Mag/Arcane Dominion, Adahn/Amnesiac, Ethric/Tomb-bound Will, Guildmaster Klastor/Bones Guild, Shadespinner Oona/Shadowmastery, Laura/Moldering, Lord Rufus/Wistful Nostalgia, Funerella/Undead Legion, Milossa the Golden/Wealthy.
- Dungeon, `DB/heroes/dungeon/*.json`: Enatee/Slithering Menace, Tellaris the Betrayed/With One Eye Open, Stinger/Venomous Strike, Kieran/The Blind Folk, Mouaren/Spy, Devir, son of Devir/Balthazar's Lair, Creta, daughter of Navarr/Gem Seeker, Rhea/Four-Leaf Horseshoe, Gleard the Grey/Arcane Dominion, Kelarr, son of Navarr/Wish to Learn, Zakron the Great/Spellweaver, Sister Deira/Mask of the Sun, Motley/Danse Macabre, Ylwari/Charismatic, Glastor/Wealthy, Typhona/Alvarian Hydra, Sunny Rauktol/Radiating Knowledge, Lodos/Shadowmastery.
- Grove, `DB/heroes/nature/*.json`: Eith/Pathfinder, Gorel Spearhead/Shooter, Gingertail/Faunsong, Old Pilgrim/Natural Selection, Octavia/Four-Leaf Horseshoe, Mreowa/Charming Shine, Faleor/Hksmilla's Step, Alluring Sh'a/Charismatic, Aunt Daliar/Wish to Learn, Vatawna/Spiritual Vigor, Elder Tss'kish/Oldest Known Tree, Aeliniel/Tempered Embers, Glacia/Ice Bolt, Vim/Rock It up!, Halon/Thunder and Lightning, Echolily/Murmuring Copy, Sullie/Murmurwood Native, The Minstrel/Wandering Musician.
- Hive, `DB/heroes/demons/*.json`: Niev/Shooter, Maelstrom/Reave Away, Nor/Wish to Learn, Zoran, the Self-Founded/Waurmification, Curson, Duke of Rage/Intimidating Strike, Tavi/Proliferation, Lo/Scavenger, Goldentongue/Rousing Presence, Abigor, Duke of Battle/Chessmaster, Fleu/Wayfarer, Xirr/Resistant to Elements, Bathym, Duke of Jewels/Charming Shine, Leira/Stinging, Groo/Son of All Mothers, Mila/Wingflap, Oriax/Here and There, Khariseth/Primal Weaving, Pauper/Flea Bites.
- Schism, `DB/heroes/unfrozen/*.json`: Nihil/Wayfarer, Blackhorn/Spellweaver, Matastala the White/Chessmaster, Janhei/Roguish, Mara Mat'ha/Coldblood Siblings, The Iron Master/Leash of Chains, Wal'kha/Primal Weaving, Changeling Urgo/Everchanging Essence, Martyr Tho/Alchemist, Grellekh the Betrayer/Fighter, Icequeen Hel'Ghat/Heart of Ice, Kwinri/Low Summoning, The Eye Collective/Rift's Envoy, Tolketh/Stellar Dilation, Ulkuth/Pathfinder, Ra'Davok/Magic Fortress, Sister Keiri/Mask of the Moon, Dhuvri/True Believer.

## Faction-By-Faction Fun Identity

### Temple (`human`)

Core fun identity: a heroic, escalating combined-arms faction. Temple rewards clean army fundamentals, protective support, and dramatic "the army rallies around the hero" moments. Its faction skill, `skill_faction_humans`, is Righteousness: whenever friendly creatures die or kill enemies, the hero's four primary attributes rise temporarily. That makes losses and kills both feel like fuel for a righteous momentum engine.

Unit pattern:

- The roster is disciplined and readable: Swordsman, Crossbowman, Griffin, Lightweaver, Cavalry, Inquisitor, Angel, with each base creature offering two upgrade endpoints through the `_upg` then `_upg_alt` chain.
- Temple alternates between simple reliable bodies and high-theater support effects. Examples: Crossbowman has `Fine Bolts`, with Austringer gaining `Double Shot` and Marksman adding `Piercing Shot`; Swordsman can become Guard Captain for `Double Strike` or Sun's Aegis for `Aegis` and defensive anointing.
- The faction's fun leans into blessed formations: Griffin has `Valiant Cry`, Cavalry has `Jousting Bonus` and `Charge!`, Lightweaver supports with `Inner Glow`, `Holy Ablution`, or `Exaltation`, Inquisitor uses `Infuse Armor` and `Celestial Flail`, and Angel brings `Refract and Reflect`, `Devouring Chalice`, `Unbending Pride`, and aura-style purity.

Hero pattern:

- Temple has 18 native heroes in `DB/heroes/humans/*.json`: 9 might-style openers and 9 magic-style openers by file order. Examples include Ister/Wayfarer, Leon/Pathfinder, John Johnson/Salt of the Earth, Kestrel/Jaeger, Aeos/Rousing Presence, Lord Edgar/True Lord, Merry Elias/Spiritual Vigor, Lia/Radiating Knowledge, Julius/Compassionate Healer, and Clarissa/Wealthy.
- Specializations show the native template language clearly: map heroes (`Wayfarer`, `Pathfinder`), unit captains (`Salt of the Earth`, `Jaeger`, `Jouster`, `Weaving the Light`), army-wide morale/hero-stat scaling (`Rousing Presence`, `True Lord`), resource heroes (`Gem Seeker`, `Wealthy`), and spell-replacement specialists (`Compassionate Healer`, `Blessing`, `Hymn to Arina`, `Heart of Hearts`).
- The fun rule is that each hero should make one familiar axis feel blessed or privileged. A Temple custom hero should not just give +stats; the player should feel that a unit line, road movement, morale, or a spell has become saintly and dependable.

Unique buildings and laws:

- `Build_Intelligence_Academy` / Scouting Skyship removes fog around the city.
- `Build_Training_Range` / Guild of Six Winds lets a hero spend a day for a permanent chosen attribute.
- `Build_Golden_Calf` boosts global resources and local dwelling growth.
- Early laws include Tax Collectors, Training: Scouting, Resource Riches I, Elite Swordsmen, and Execute Excellence, showing Temple's law tone: economy, hero training, unit professionalism, and buff duration.

Design synthesis rule:

Temple content should turn ordinary tactical success into visible civic/religious momentum. Good mechanics are rally, bless, train, extend, guard, and reward sacrifice. Bad Temple mechanics are chaotic self-harm, opaque random triggers, or isolated selfish abilities that do not help a formation feel organized.

### Necropolis (`undead`)

Core fun identity: attrition, conversion, and inevitability. Necropolis fun comes from the player watching death remain useful. Its faction skill, `skill_faction_undead`, is Necromancy: after victory, defeated enemy HP becomes friendly Undead HP or tier-matched Undead through Necromantic Energy variants.

Unit pattern:

- The roster is built around persistence and corpse economy: Skeleton, Wight, Undead Pet, Graverobber, Lich, Dread Knight, Vampire.
- Many units turn death, memory, or bodies into tempo. Wight/Wraith lines use `Memory Devourer` and `Howl of the Banshee`; Graverobber uses `Dig Up Bones`, `Fetch!`, `Hail!`, `Ensnare Memories`, and corpse-flavored passives like `Blighted Corpses`; Lich manipulates death through `Rewind Death`, `Death's Embrace`, `Area Strike`, and `Unlife, Undeath`; Vampire sustains with `Vampirism`, `Blood Transfusion`, and `Corpse Explosion`.
- Upgrades usually choose between more direct brutality and more necromantic utility. Skeleton Warrior stays simple melee; Skeleton Archer changes the line into ranged utility. Vampire Lord improves personal survivability and attack cadence; Vampire Scholar trades into reach, blood support, and corpse magic.

Hero pattern:

- Necropolis has 18 native heroes under `DB/heroes/necros/*.json`; all start with `change_use_necromancy` in `startMagics`.
- Examples: Bulwark/Built Different makes the whole army take less basic/ranged damage; King-of-Kings/Charismatic improves diplomacy-style conversion; Onkos/Perfect Puppets, Adahn/Amnesiac, Ethric/Tomb-bound Will, and Guildmaster Klastor/Bones Guild are unit-line captains; Funerella and Tarius both use Undead Legion; Laura/Moldering and Lord Rufus/Wistful Nostalgia replace specific spells with masterful death-themed versions.
- Necropolis hero fun repeatedly asks "what does this hero do with dead things, old things, or things that refuse to end?"

Unique buildings and laws:

- `Build_Well_Of_Souls` fully restores mana for visiting heroes.
- `Build_Skeleton_Converter` sacrifices creatures into Undead units of the same tier.
- `Build_Gaping_Maw` gives all friendly creatures defense and Lucky Strike damage reduction, plus dwelling growth.
- Early laws include Animate Dead I/II, Elite Skeletons, Elite Wights, Stand to the Death!, and Laws of the Immortals.

Design synthesis rule:

Necropolis content should create a second life for losses, corpses, memory, or mana. It is fun when it reframes casualties as resources. Avoid generic lifesteal spam with no faction economy hook; Necropolis should feel like a system of preservation and conversion, not only self-healing.

### Dungeon (`dungeon`)

Core fun identity: stance-based cunning, dirty fighting, and positional aggression. Dungeon's faction skill, `skill_faction_dungeon`, is Triumvirate's Strength: once per round the hero chooses one of three Stances, gaining an attribute tied to that stance. This makes the faction feel tactical and opportunistic.

Unit pattern:

- Dungeon roster: Troglodyte, Infiltrator, Onyx Dancer, Minotaur, Medusa, Hydra, Cave Dragon.
- A major repeated presentation pattern is "Fighting Style" alternate attacks. Examples include Troglodyte's `Fighting Style: Viscous Spit`, Infiltrator's `Fighting Style: Hit and Run`, Onyx Dancer's `Fighting Style: Bouncing Glaives`, Minotaur's `Fighting Style: Grand Slam`, Medusa's `Fighting Style: Arrow Barrage`, Hydra's `Fighting Style: Whirlwind Strike`, and Cave Dragon's `Fighting Style: Sulfurous Assault`.
- The roster rewards reading board state. Infiltrator has `Blink`, `Weak Spot`, `Shadowstrike`, and `Veil of Shadows`; Medusa has `Slither Away`, `Petrification`, `Countershot`, and `Marble Arrows`; Hydra has `Sweeping Strike`, `Growing Teeth`, `Poisonous Blood`, `Regeneration`, and `All Heads on Deck`; Dragon adds breath, magic immunity, and domination.

Hero pattern:

- Dungeon has 18 native heroes under `DB/heroes/dungeon/*.json`.
- Examples: Enatee/Slithering Menace, Tellaris/With One Eye Open, Stinger/Venomous Strike, Kieran/The Blind Folk, Mouaren/Spy, Devir/Balthazar's Lair, Rhea/Four-Leaf Horseshoe, Gleard/Arcane Dominion, Zakron/Spellweaver, Motley/Danse Macabre, Typhona/Alvarian Hydra, Sunny Rauktol/Radiating Knowledge, and Lodos/Shadowmastery.
- Specializations combine unit captains, stance or tactical information, poison/venom, spell-school dominance, and resource/economy hooks. The fun is choice density: the player should feel clever for using the right posture or target.

Unique buildings and laws:

- `Build_Gymnasium` levels up a visiting hero once.
- `Build_Lyceum` enchants magic scrolls so they grant maximum-level spells.
- `Build_Spy_Network` completely removes fog of war and boosts dwelling growth.
- Laws include Leaders of the Nation, Elite Troglodytes, Dragon Scales, Dungeon Masters I, Or No Ore?, and Jadame Maps.

Design synthesis rule:

Dungeon content should give players tools that become stronger with timing, target choice, or stance choice. Avoid passive always-on bonuses with no tactical posture unless they support a trickier active pattern.

### Grove (`nature`)

Core fun identity: elemental focus, living terrain, and organic adaptation. Grove's faction skill, `skill_faction_nature`, is Murmuring: it generates Focus Charges at battle start. Much of the roster spends that focus-feeling identity through awakenings, embodiment passives, and nature magic.

Unit pattern:

- Grove roster: Faun, Hoplet, Vine Iriyad, Naiad, Herbomancer, Qilin, Phoenix.
- Elemental "Awaken" abilities define the roster: Naiad uses `Awaken: Water`, Iriyad uses `Awaken: Earth`, Qilin uses `Awaken: Air`, and Phoenix uses `Awaken: Fire`.
- Upgrades branch into elemental sub-flavors. Brumal Naiad adds `Whirlpool` and ice; Vernal Naiad adds `Rivulet Retreat`; Crystal Iriyad adds `Earthshatter` and `Crystal Thorns`; Fungal Iriyad adds cover/stoneheart; Thunder Qilin adds `Ball Lightning`, `Thunderstrike`, and `Cloud Nine`; Phoenix upgrades split toward `Heatwave`/`Immortal` or `Supernova`/`Eternal Flame`.
- Grove also has playful low-tier identity: Faun can become archer or melee warrior, Hoplet has `Leeching Hop`, `Morning Dew`, `Bloom`, `Magic Core`, and flying mobility.

Hero pattern:

- Grove has 18 heroes under `DB/heroes/nature/*.json`.
- Examples: Eith/Pathfinder, Gorel/Shooter, Gingertail/Faunsong, Old Pilgrim/Natural Selection, Octavia/Four-Leaf Horseshoe, Mreowa/Charming Shine, Faleor/Hksmilla's Step, Alluring Sh'a/Charismatic, Aunt Daliar/Wish to Learn, Vatawna/Spiritual Vigor, Elder Tss'kish/Oldest Known Tree, Aeliniel/Tempered Embers, Glacia/Ice Bolt, Halon/Thunder and Lightning, Echolily/Murmuring Copy, Sullie/Murmurwood Native, and The Minstrel/Wandering Musician.
- Hero fun is either elemental authorship, creature-line shepherding, or map-life utility. Grove's heroes should make the player feel like the battlefield is a living instrument.

Unique buildings and laws:

- `Build_Mother_Nature` grants Spell Power to a visiting hero.
- `Build_Mycelium_Roots` lets a hero travel to any owned city.
- `Build_Spring_of_Life` adds creature growth in all cities and local dwelling growth.
- Laws include Knowledge is Power, Folk Heroes, Elite Fauns, Elite Hoplets, Children of the Wild, and Save the Forests.

Design synthesis rule:

Grove content should feel like spending stored natural potential: focus, awaken, bloom, retreat, root, echo, and rebirth. Avoid dry stat-only elemental labels; the mechanic should move, grow, shield, copy, or transform something.

### Hive (`demon`)

Core fun identity: swarm pressure, larvae, hivemind roles, and predatory escalation. Hive's faction skill, `skill_faction_demons`, is Summon Swarm: once per round the hero lays eggs that spawn Fire Larvae next round, scaling from the total HP of Hive Spawn in the army.

Unit pattern:

- Hive roster: Parasite, Locust, Hornet, Scorpion, Reaver, Waurms, Hive Queen, plus `lava_larva` as a summoned combat piece.
- The faction repeats two upgrade identities: `Hivemind: Vanguard` and `Hivemind: Nest Protector`. That gives alternate upgrades a clear strategic voice: forward aggression versus nest defense/control.
- Hive likes violent tempo and body conversion. Parasites use `Topple the Strong!`; Locusts use `Harvest`, `Double Strike`, `Parry`; Hornet upgrades use `Piercing Sting` or `Whispers of Doubt`; Scorpion uses selectable `Adaptation: Attack`, `Adaptation: Defense`, `Adaptation: Speed`; Waurms use `Corpse Eater`, `Devour`, `Demonic Stench`, and sometimes ranged Pyroboros behavior; Hive Queen uses `Blasphemous Adoration`, `Contaminating Blast`, `Promise of Love`, `Soul Assimilator`, `Beelzebub's Agenda`, and `Squash the Weak!`.

Hero pattern:

- Hive has 18 heroes under `DB/heroes/demons/*.json`.
- Examples: Niev/Shooter, Maelstrom/Reave Away, Nor/Wish to Learn, Zoran/Waurmification, Curson/Intimidating Strike, Tavi/Proliferation, Lo/Scavenger, Goldentongue/Rousing Presence, Abigor/Chessmaster, Xirr/Resistant to Elements, Bathym/Charming Shine, Leira/Stinging, Groo/Son of All Mothers, Oriax/Here and There, Khariseth/Primal Weaving, and Pauper/Flea Bites.
- Hive specializations are at their best when they make the whole colony behave differently: more larvae, better swarm tempo, stronger predators, exact neutral information, or a scary hero strike.

Unique buildings and laws:

- `Build_Beelzebubs_Hand` grants Attack to a visiting hero.
- `Build_Rebirth_Of_Shrine` reverts a hero to level one once and grants permanent attributes based on prior level.
- `Build_Eternal_Flame` gives global friendly Attack, Lucky Strike damage, and dwelling growth.
- Laws include Laws of the Hive, Hive Integration, Hive Reception, Hive Offsprings I, Focus Reserves, and Hidden Desires.

Design synthesis rule:

Hive content should make the player manage infestation, growth, and role pressure. Good mechanics seed a future threat, reward collective HP, mutate a unit role, or turn a corpse into appetite. Avoid one-off fire damage that does not connect to larvae, swarm, hivemind, or predator identity.

### Schism (`unfrozen`)

Core fun identity: abyssal accumulation, summoning rites, control, and cold paradox. Schism's faction skill, `skill_faction_unfrozen`, is Abyssal Communion: victories raise Communion, which increases friendly Schism unit counts until battle end; each morning Communion halves.

Unit pattern:

- Schism roster: Ra'Shoth, Cultist, Aga'Shoth Rider, Grand Shoth, Concubus, Arbitrator, Abyssal Envoy.
- Many creatures carry explicit active control buttons. Cultists use `Glance of the Abyss`, `Gaze of the Abyss: Sluggishness`, `Gaze of the Abyss: Slow`, and `Abyssal Tendril`; Concubus uses `Handcuffs`, `Hourglass`, `Flog Idle Mind`, and `Bewitch into Passivity`; Arbitrator uses `Command: Reposition`, `Command: Fear`, `Command: Switch Places`, `Frozen Pages`, and `Disgorge Storm`; Envoy upgrades add `Control Mind` or `Moment of Insanity`.
- Summoning Rite is the repeated roster language: Ra'Shoth, Shoth, and Envoy lines all expose summoning names. This makes the faction feel like an army brought through a ritual rather than trained normally.
- The faction uses cold and paradox as secondary texture: `Frost`, `Piercing Cold`, `Icy Breath`, `Icy Spikes`, `Black Ice Shard`, `Paradoxical Shots`, `Power of the Abyss`, and `Absolute Resistance`.

Hero pattern:

- Schism has 18 heroes under `DB/heroes/unfrozen/*.json`.
- Examples: Nihil/Wayfarer, Blackhorn/Spellweaver, Matastala/Chessmaster, Janhei/Roguish, Mara Mat'ha/Coldblood Siblings, The Iron Master/Leash of Chains, Wal'kha/Primal Weaving, Changeling Urgo/Everchanging Essence, Martyr Tho/Alchemist, Grellekh/Fighter, Icequeen Hel'Ghat/Heart of Ice, Kwinri/Low Summoning, The Eye Collective/Rift's Envoy, Tolketh/Stellar Dilation, Ulkuth/Pathfinder, Ra'Davok/Magic Fortress, Sister Keiri/Mask of the Moon, and Dhuvri/True Believer.
- Hero fun is about carrying power between battles, warping control rules, and escalating ritual identity. A Schism hero should feel like they are negotiating with a strange system, not merely casting stronger spells.

Unique buildings and laws:

- `Build_Endless_Library` / Great Library grants Knowledge to a visiting hero.
- `Build_Portal_Summoning` / Involuntary Summons lets the owner recruit from any controlled external dwelling once per week, even when no units are available on the map.
- `Build_Frigid_Firmament` unlocks all spells of the corresponding tier when the Mage Guild is built and boosts dwelling growth.
- Laws include Generational Wisdom, Frozen Homeland, Elite Ra'Shoth, Unfrozen Strength I, Ice Power, and Survival Conditions.

Design synthesis rule:

Schism content should accumulate, distort, bind, or summon. It is fun when the player has a delayed or carried-over resource to manage. Avoid generic ice damage unless it is tied to control, communion, summoning, paradox, or attrition.

## Repeated Fun Patterns In Native Data

1. Every faction has a single faction skill that defines its fantasy in verbs, not just stats.
   - Temple: death/kills feed temporary righteousness stats.
   - Necropolis: defeated enemies become Undead value.
   - Dungeon: stance selection changes the hero's attribute profile.
   - Grove: battle-start Focus Charges fuel elemental play.
   - Hive: eggs become Fire Larvae next round.
   - Schism: victories build Communion that increases Schism unit counts.

2. Native rosters use seven tiers with three units per line: base, standard upgrade, alternate upgrade.
   - The base establishes the readable role.
   - The standard upgrade often sharpens the base role.
   - The alternate upgrade often changes axis: defense versus offense, support versus damage, melee versus ranged, utility versus tempo.

3. Fun is anchored in named mechanics that reappear within a faction.
   - Dungeon repeats `Fighting Style`.
   - Grove repeats `Awaken` and elemental `Embodiment`.
   - Hive repeats `Hivemind`, larvae, and predation.
   - Schism repeats `Summoning Rite`, abyssal commands, and control.
   - Temple repeats anointed/blessed/protective language.
   - Necropolis repeats death, memory, bones, corpses, blood, and undeath.

4. Heroes are not purely bespoke. They reuse a native library of specialization shapes:
   - Map specialists: `Wayfarer`, `Pathfinder`.
   - Unit captains: growth plus Speed, Initiative, HP, scaling Attack/Defense, and enemy mirror debuffs.
   - Spell replacers: start with a named spell, replace it with a masterful variant, then scale effective Spell Power.
   - School dominators: increase all spells in one school and block enemy use of that school.
   - Resource heroes: daily rare resource/gold plus increased map pickup.
   - Hero action specialists: modify Heroic Strike or the mage equivalent with stacking debuffs.
   - Army-wide stat specialists: morale, damage dealt/taken, speed, magic attack, tactics placement, or hero-stat conversion.

5. Unique buildings usually create a faction-defining strategic convenience, not just a bigger number.
   - Temple trains heroes and scouts.
   - Necropolis restores mana and converts creatures.
   - Dungeon levels heroes, improves scrolls, and spies globally.
   - Grove moves heroes through city roots and grants spell power/growth.
   - Hive resets heroes through rebirth and grants attack.
   - Schism recruits through external dwellings and improves magic access.

6. Laws mix four roles:
   - Baseline economy: Tax Collectors, Resource Riches, cost reductions, resource production.
   - Faction skill amplification: Animate Dead, Focus Reserves, Laws of the Hive, Communion cap/gain, stance improvements.
   - Unit-line laws: Elite Swordsmen, Elite Skeletons, Elite Troglodytes, Elite Fauns, Hive offspring, Elite Ra'Shoth.
   - Strategic identity: scouting, native terrain, magic school access, build-cost identity, fog, map information.

## Fun Anti-Patterns To Avoid In Custom Factions

- Do not make a faction skill that is only "+X Attack" or "+Y damage." Native faction skills create a play loop: kill/die, convert, choose stance, spend focus, seed larvae, carry communion.
- Do not give every unit an unrelated gimmick. Native factions repeat keywords and verbs so the roster teaches itself.
- Do not let alternate upgrades be only numeric upgrades. The live data often uses alternates to change role or emphasis.
- Do not create hero specializations without a known native shape unless the new shape is justified by the faction's core loop. Most native specs belong to a small set of proven templates.
- Do not detach heroes from their starting skill, starting magic, and starting squad. Native heroes are packages: specialization, class, start skill, starting creatures, and starting spell all point at a role.
- Do not make unique buildings generic copies. Native special buildings give a faction-specific strategic affordance: conversion, travel, training, rebirth, external recruitment, information, or spell access.
- Do not overuse passive invisible math. Native designs prefer named visible mechanics: `Charge!`, `Rewind Death`, `Petrification`, `Awaken: Fire`, `Devour`, `Command: Fear`.
- Do not rely on donor/fallback behavior to "sort of" match a faction. If the data source is discoverable, bind the mechanic to explicit ids, rows, names, and localization.
- Do not flatten faction law layouts. Native law counts and unlock-band contents vary by faction; custom law synthesis should copy the intended donor's structural pattern or explicitly justify a new one.
- Do not port HoMM3 flavor directly into this document's vanilla model. HoMM3 custom factions in the archive are separate data and should be used later as custom-side context only.

## Concrete Rules For Custom Unit Synthesis

1. Pick the faction's core verb first.
   - Examples: "convert death," "choose stance," "awaken elements," "seed swarm," "carry communion."
   - Every unit line should either perform that verb, spend it, defend it, or create a contrast that makes it matter.

2. Design each tier as a three-part line.
   - Base: simplest role and readable attack mode.
   - Standard upgrade: stronger or more reliable version of base role.
   - Alternate upgrade: a meaningful role branch, such as support/control/range/defense/tempo.

3. Reuse faction vocabulary across at least three creature lines.
   - A repeated keyword teaches the player how to read the faction.
   - If a mechanic name appears once and never again, it should be a high-tier capstone or a deliberate hero-specific exception.

4. Tie active abilities to presentation-side ability cards.
   - Logic rows in `DB/units/units_logics` and view rows in `DB/units/units_views` must agree. The native data keeps active ability names/descriptions in the view row and mechanics in logic.

5. Give low tiers one clear job and high tiers one dramatic exception.
   - Native tier 1-2 creatures often teach the faction: Swordsman/Crossbowman, Skeleton/Wight, Troglodyte/Infiltrator, Faun/Hoplet, Parasite/Locust, Ra'Shoth/Cultist.
   - Tier 6-7 creatures carry the fantasy: Inquisitor/Angel, Dread Knight/Vampire, Hydra/Dragon, Qilin/Phoenix, Waurms/Hive Queen, Arbitrator/Envoy.

6. Use alternate attack modes as faction identity only when the faction supports it.
   - Dungeon uses `Fighting Style` heavily; Necropolis uses reach/ranged swaps selectively; Hive uses eater/ranged eater; Schism uses commands and summoning rather than every unit having an alternate attack.

7. If a unit summons, converts, revives, or creates a new stack, document the economy that constrains it.
   - Native examples constrain these through Focus, Necromantic Energy, Fire Larva egg timing, or Communion. Avoid unconstrained free bodies.

## Concrete Rules For Custom Hero Synthesis

1. Start from one of the native specialization templates unless there is a strong reason not to.
   - Unit captain, spell replacer, school dominator, map specialist, resource specialist, army-wide stat specialist, faction-resource specialist, hero-action specialist.

2. Make the hero package coherent.
   - The native rows align `classType`, `startSkills`, `startMagics`, `startSquad`, and `specialization`.
   - A unit captain should usually start with that unit or a nearby unit tier.
   - A spell replacer should start with the base spell it replaces.
   - A faction-resource specialist should start with the faction skill at a meaningful level.

3. Preserve the 18-hero rhythm for full faction synthesis.
   - Native factions use broad coverage: early might, later magic, multiple unit captains, one or more map/economy specialists, spell-school specialists, and a faction-skill specialist.

4. Do not make every hero a unit captain.
   - Native rosters mix unit captains with map, economy, school, spell, army-stat, and faction-resource heroes.

5. Make scaling visible and paced.
   - Native specializations commonly scale every 2, 3, 4, 5, 6, or 8 hero levels. Pick a cadence matching impact instead of making every bonus scale every level.

## Concrete Rules For Custom Building And Law Synthesis

1. Every faction needs seven hire buildings with two levels and a consistent base/upgrade/alternate unit chain.

2. Unique buildings should answer "what strategic thing can this faction do that others cannot?"
   - Conversion, travel, training, hero reset, external recruitment, information, spell access, or one-time hero improvement are native-proven categories.

3. Grail buildings should combine global fantasy and local growth.
   - Native grails usually add a faction-wide battle/economy/magic benefit plus increased local dwelling output.

4. Laws should be arranged in unlock bands, not just dumped into a list.
   - Use the source faction row's `fractionLawsLines` as the visible structure.
   - Keep early laws legible and immediately useful; reserve complex faction-loop upgrades for later bands.

5. Include at least one law family for the faction skill, one for creature identity, one for economy, and one for map/strategic texture.

6. If adapting from a donor faction, copy structural intent, not literal names.
   - Temple's training/scouting law structure can inspire another disciplined faction, but the output should use the custom faction's verbs and resources.

## Evidence Checklist For Future Work

When synthesizing a custom faction from this philosophy, inspect and update the corresponding live/generated sources:

- `DB/fractions/<row>.json`: id, display token, biome, rare resource, law-line layout, city name tokens.
- `DB/units/units_logics/<folder>/*.json`: tiers, upgrade chains, stats, attack types, passives, actives, summons/conversions.
- `DB/units/units_views/<folder>/*.json`: visible ability cards, passive cards, base class, projectiles, alternate attacks.
- `DB/heroes/<folder>/*.json`: class, starting army, starting skills, starting spells, specialization id.
- `DB/heroes_specializations/specializations_<faction>.json`: bonus types, receivers, scaling cadence, icon/name/desc tokens.
- `DB/objects_logic/cities/<faction>_city.json`: hire buildings, unique building categories, grail, costs, requirements, build order.
- `DB/fractions_laws/fractions_laws_table_<faction>.json`: law effects and token ids.
- `Lang/english/texts/cities.json`, `heroInfo.json`, `heroSkills.json`, `units.json`, `unitsAbility.json`, `factionLaws.json`: visible player-facing names/descriptions.

Do not treat missing data as a design opportunity until the live archive path has been checked. If the mechanic exists in live data, use the real source row as the design precedent.
