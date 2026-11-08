# Vanilla Faction Depth Design Philosophy

Date: 2026-05-25

This document studies the live native Olden Era factions in the Steam Golden Era
`Core.zip`, with "depth" defined as meaningful, non-easy decisions rather than
raw complexity. It is not a HoMM3 faction-plan document and should not be read
as a porting spec for `homm3_*` factions.

The useful design question is not "what can we add?" It is "what real choice
does this ask the player to make, and what cost makes that choice nontrivial?"

## Source Inventory

Primary source inspected:

- `V:\SteamLibrary\steamapps\common\Heroes of Might and Magic Olden Era - Golden Era\HeroesOldenEra_Data\StreamingAssets\Core.zip`

Native faction boundary found in the live archive:

- Native rows: `DB/fractions/1_human.json`, `2_undead.json`, `3_dungeon.json`,
  `4_nature.json`, `5_demon.json`, `6_unfrozen.json`.
- HoMM3 overlay rows are also present in this live archive:
  `DB/fractions/7_homm3_stronghold.json`, `10_homm3_tower.json`,
  `11_homm3_fortress.json`, `12_homm3_*`, `13_homm3_castle.json`,
  `20_homm3_cove.json`. They were deliberately excluded from the vanilla
  faction read.

Native data categories inspected:

- Faction identity: `DB/fractions/*.json`, localized through
  `Lang/english/texts/fractions.json` and related token files.
- Unit logic and combat stats: `DB/units/units_logics/humans`,
  `DB/units/units_logics/undead`, `DB/units/units_logics/dungeon`,
  `DB/units/units_logics/nature`, `DB/units/units_logics/demons`,
  `DB/units/units_logics/unfrozen`.
- Unit UI abilities/passives: matching `DB/units/units_views/<folder>`.
- Heroes: `DB/heroes/humans`, `DB/heroes/necros`, `DB/heroes/dungeon`,
  `DB/heroes/nature`, `DB/heroes/demons`, `DB/heroes/unfrozen`.
- Hero specializations: `DB/heroes_specializations/specializations_human.json`,
  `specializations_necro.json`, `specializations_dungeon.json`,
  `specializations_nature.json`, `specializations_demon.json`,
  `specializations_unfrozen.json`.
- City/building rows: `DB/objects_logic/cities/human_city.json`,
  `undead_city.json`, `dungeon_city.json`, `nature_city.json`,
  `demon_city.json`, `unfrozen_city.json`.
- Faction laws: `DB/fractions_laws/fractions_laws_table_human.json`,
  `fractions_laws_table_undead.json`, `fractions_laws_table_dungeon.json`,
  `fractions_laws_table_nature.json`, `fractions_laws_table_demon.json`,
  `fractions_laws_table_unfrozen.json`.
- Localization evidence: `Lang/english/texts/heroInfo.json`,
  `heroSkills.json`, `units.json`, `cities.json`, `factionLaws.json`.

Schema notes:

- Hero display names are keyed by hero id in `Lang/english/texts/heroInfo.json`
  (`human_hero_1 -> Ister`), while specialization labels are keyed by the
  `name`/`desc` fields inside specialization rows (`human_hero_1_spec_name`,
  `human_hero_1_spec_description`). `Lang/english/texts/heroes.json` is mostly
  HoMM3 overlay hero text in this live archive.
- Unit depth is split between logic and view files. `units_logics` carries
  stats, attack routes, cooldowns, focus costs, summon/heal/damage mechanics,
  and upgrade chains. `units_views` carries player-facing passives, alternative
  attack labels, ability labels, and ability categories.
- City "unique building" identity is not only in unique-looking names. The
  important strategic effects are in `banks`, `intelligences`,
  `trainingRanges`, `graals`, `magicGuilds.rollChances`, `walls`, and
  `buildOrders`.

## Depth Principles Found In Vanilla

1. A faction is a decision grammar, not a pile of bonuses.
   Each native faction repeats a small number of verbs across units, heroes,
   laws, and buildings. Temple asks "who receives the buff and when?"; Necropolis
   asks "what can be converted, stolen, or returned?"; Dungeon asks "which mode
   or attack type solves this turn?"; Grove asks "which expensive elemental
   tool do I commit?"; Hive asks "where do I snowball aggression and swarm
   pressure?"; Schism asks "what do I deny, summon, or scale through communion?"

2. Upgrades create forks, not just bigger numbers.
   Native factions commonly use base -> standard upgrade -> alternate upgrade.
   The standard upgrade often improves the base role, while the alternate changes
   the role's risk profile. Examples: Temple `esquire_upg` gains Double Strike,
   while `esquire_upg_alt` becomes a defensive grouping unit; Necropolis
   `skeleton_upg_alt` becomes a ranged Skeleton Archer; Dungeon `black_dragon_upg`
   deepens raw Black Dragon dominance while `black_dragon_upg_alt` gains
   Dragonflight and a more mobile profile; Grove `elf_tracker_upg_alt` flips the
   Faun family from ranged to melee.

3. Heroes are not interchangeable stat carriers.
   Each faction has 18 native heroes split across might and magic classes, but
   the differentiation is not only class. Specializations cover map tempo,
   unit-family commitment, magic-school mastery, resource economy, Heroic Strike
   mutations, spell replacement, and faction-resource scaling. These make
   draft/opening decisions matter before the first city build choice.

4. Laws and buildings are long-horizon commitments.
   Laws reinforce either a faction-wide axis or a named unit line. City buildings
   add durable economy, magic access, growth, training, vision, or grail effects.
   A good custom faction needs this same strategic layer. It is shallow if its
   only identity is combat-unit text.

5. Complexity is justified only when it changes sequencing.
   A unit with three abilities is not automatically deeper than a unit with one.
   Hive Scorpion's three Adaptation buffs create depth because it must choose the
   immediate axis of improvement. A passive stat boost with no timing, target,
   or opportunity cost is usually less deep even if the description is longer.

## Faction-By-Faction Decision Identity

### Temple (`human`)

Evidence:

- `DB/fractions/1_human.json`: localized as Temple, biome `Grass`, resource
  `gemstones`, description says well-rounded troops gain extra benefits from
  buffs.
- Units: `DB/units/units_logics/humans` and `DB/units/units_views/humans`.
- Heroes: `DB/heroes/humans`; specs:
  `DB/heroes_specializations/specializations_human.json`.
- City: `DB/objects_logic/cities/human_city.json`; laws:
  `DB/fractions_laws/fractions_laws_table_human.json`.
- Faction skill: `skill_faction_humans` / Righteousness in
  `Lang/english/texts/heroSkills.json`; the live tokens include both
  death/kill-trigger and positive-effect-trigger descriptions, but both frame
  the skill around temporary stacked hero Attack, Defense, Spell Power, and
  Knowledge.

Decision identity:

Temple is the disciplined generalist faction. Its depth comes from turning
buffs, morale, counterplay, and hero-stat conversion into timing choices. It has
strong mixed-arms coverage, but the live data keeps asking the player to decide
where to concentrate the blessing: durable front line, ranged pressure, cavalry
tempo, anti-magic, or angelic finishers.

Unit and upgrade decision patterns:

| Tier | Family | Base role | Standard upgrade | Alternate upgrade | Depth point |
| --- | --- | --- | --- | --- | --- |
| 1 | Swordsman (`esquire`) | Low-tier melee with Ranged Defense I | Guard Captain gains Double Strike | Sun's Aegis becomes defensive/grouping with Aegis and Anointed for Defense | Pick attack volume or formation durability. |
| 2 | Crossbowman | Ranged support with Fine Bolts | Austringer adds Double Shot | Marksman adds Sharpshooter and Piercing Shot | Pick repeated shots or higher precision/active pressure. |
| 3 | Griffin | Fast flying melee with Alert and Valiant Cry | Temple Griffin pushes initiative/speed and Alert II | Guardian Griffin turns into a protector profile | Pick initiative race or bodyguard control. |
| 4 | Lightweaver | Slow ranged support with Inner Glow | Hierophant adds Holy Ablution | Sun Herald adds damage and Exaltation | Pick cleansing/support or damage-forward buffing. |
| 5 | Cavalry | Piercing, inspiring charge unit | Noble Cavalry adds Charge! | Sunspear Cavalry gains higher defense/speed and Anointed for Attack | Pick active burst timing or sustained stat quality. |
| 6 | Inquisitor | Anti-magic melee, Infuse Armor, Celestial Flail | Mother Superior improves tanking and Celestial Armor | Excommunicator improves damage and Swift Penance | Pick defensive anchor or execution. |
| 7 | Angel | Ranged/flying elite with Reflect/Refract | Archangel adds Sharpshooter and Devouring Chalice | Apotheosis becomes mobile/tanky with Duelist, Purity Aura, Unbending Pride | Pick ranged dominance or hybrid board presence. |

Hero specialization coverage:

- Ister: Wayfarer. Map movement depth; rewards route planning.
- Leon Sticky-Fingers: Pathfinder. Ignores terrain penalties and improves sight.
- John Johnson: Swordsman specialist. Commits the opening to tier-1 growth and
  stat scaling.
- Kestrel: Crossbowman specialist. Commits to ranged early pressure.
- Aeos the Exalted: Rousing Presence. Turns morale into a stronger action
  economy.
- Heretic Avis: Gem Seeker. Moves the strategic bottleneck toward resource
  economy and map pickup value.
- Keandra: Jouster. Commits to Cavalry and formation/charge play.
- Lord Edgar: True Lord. Converts hero Attack/Defense into creature stats,
  encouraging hero-stat stacking.
- Old Lord Mandall: Heroic Smite. Turns Heroic Strike into a vulnerability setup,
  not only damage.
- Merry Elias: Spiritual Vigor. Expands global-map spell usage and mana scaling.
- Pip: Wish to Learn. Long-term XP and attribute scaling.
- Zenith: Lightweaver specialist. Pushes the support-ranged tier-4 line.
- Lia the Untethered One: Radiating Knowledge. Daylight-school mastery and school
  denial.
- Julius: Compassionate Healer. Masterful Healing Water with stronger dispel
  support.
- Vesper: Blessing. Masterful Blessing for maximum-damage play.
- Anastasia the Meek: Hymn to Arina. Masterful Arina's Touch speed support.
- Nadir: Heart of Hearts. Masterful Vulnerability for maximum incoming damage.
- Clarissa: Wealthy. Gold economy and map gold scaling.

Strategic levers:

- Laws reinforce buff duration (`Execute Excellence`), morale (`Encouragement`,
  `Heroes of Tales`), melee/ranged training, named elite lines, and broad spell
  access (`Power of Faith`).
- The city has `Scouting Skyship` (`intelligences`) and `Guild of Six Winds`
  (`trainingRanges`), making vision and hero training explicit city decisions.
- `Build_Golden_Calf` gives all cities gold/other resources and doubles local
  dwelling growth, so the grail is a macro amplifier rather than just a battle
  stat.
- Magic guild rolls favor Daylight spells such as Healing Water, Sharp Edge,
  Haste, Shorten Shadow, Clear View, and Cleansing Ray.

Depth takeaway:

Temple should not be designed as "generic good faction." Its real identity is
buff timing plus stat transmutation. Custom factions using Temple scaffolding
should preserve the need to choose who gets amplified, when the buff is worth a
turn/focus charge, and whether a hero build supports combat tempo or economy.

### Necropolis (`undead`)

Evidence:

- `DB/fractions/2_undead.json`: localized as Necropolis, biome `Deathland`,
  resource `mercury`, description emphasizes post-battle undead rising and
  strength-sapping strikes.
- Units: `DB/units/units_logics/undead`, `DB/units/units_views/undead`.
- Heroes: `DB/heroes/necros`; specs:
  `DB/heroes_specializations/specializations_necro.json`.
- City: `DB/objects_logic/cities/undead_city.json`; laws:
  `DB/fractions_laws/fractions_laws_table_undead.json`.
- Faction skill: `skill_faction_undead` / Necromancy converts defeated enemies
  into undead HP or tier-matched undead through Necromantic Energy.

Decision identity:

Necropolis is attrition economics. Its core question is how to turn death into a
future advantage without losing the current fight. Its best choices are about
conversion timing, sustain, summons, morale/luck denial, and terrain control.

Unit and upgrade decision patterns:

| Tier | Family | Base role | Standard upgrade | Alternate upgrade | Depth point |
| --- | --- | --- | --- | --- | --- |
| 1 | Skeleton | Cheap melee mass | Skeleton Warrior improves defense/damage | Skeleton Archer changes the family to ranged | Pick durable body count or backline scaling. |
| 2 | Wight | Fast flying Memory Devourer | Wraith adds Howl of the Banshee | Phantasm adds Nightmares and defense | Pick active movement/control or passive pressure. |
| 3 | Undead Pet | Defensive melee | Barghest adds Bone Crusher and Call the Pack | Armored Hound adds Protect the Fallen and Lacerated Wounds | Pick pack-summon offense or guard/bleed support. |
| 4 | Graverobber | Long Reach with Dig Up Bones | Merchant of Death adds Blighted Corpses and Ensnare Memories | Kennelmaster adds Fetch!, Hail!, Smell of the Hunt | Pick corpse economy or hound/control package. |
| 5 | Lich | Ranged with Rewind Death | Pestilent Lich gains Area Strike and Death's Embrace | Sanguine Lich gains Unlife/Undeath/Knowledge of Death and keeps Rewind Death | Pick debuff area pressure or healing/death knowledge. |
| 6 | Dread Knight | Double Strike and Dreadful Presence | Avatar of War adds War Incarnate | Hollow Reaper adds Death Stare, Hungering Hollow, Reap Without Sowing | Pick reliable bruiser or execution threat. |
| 7 | Vampire | Flying vampiric melee | Vampire Lord improves speed/defense and Swift Strike | Vampire Scholar becomes Long Reach with Blood Transfusion and Corpse Explosion | Pick melee drain dominance or caster-like battlefield utility. |

Hero specialization coverage:

- Bulwark: Built Different. Damage reduction and durability.
- King-of-Kings: Charismatic. Diplomacy and safe neutral retreat.
- Onkos: Skeleton specialist. Converts low-tier mass into a plan.
- Kel'Ghul: Dread Knight specialist. Premium melee commitment.
- Natalida: Undead Pet specialist. Early pet stack identity.
- Artorius Veritas: Drive 'em Crazy. Masterful Berserk.
- Marl: Languid Soil. Masterful Web.
- Tarius: Undead Legion. Necromancy Power scaling.
- Zam: Alchemist. Mercury economy.
- Mag: Arcane Dominion. Arcane-school mastery.
- Adahn: Wight specialist.
- Ethric: Lich specialist.
- Guildmaster Klastor: Graverobber specialist.
- Shadespinner Oona: Shadowmastery. Nightshade mastery.
- Laura: Moldering. Masterful Despair.
- Lord Rufus: Wistful Nostalgia. Masterful Rewind Life.
- Funerella: Undead Legion. Second Necromancy scaling hero.
- Milossa the Golden: Wealthy. Gold economy.

Strategic levers:

- Laws include multiple Necromancy lines (`Animate Dead I` through `V`), maximum
  Necromantic Energy, `Bloodthirst`, summon-strength laws, native-terrain battle
  forcing (`Terra Mortis`), escape/faction-morale smoothing, counterattack
  expansion, enemy morale/luck suppression, and enemy magic-level suppression.
- `Build_Gaping_Maw` / Everserpent grants allied Defense and reduced Lucky Strike
  damage, plus local growth. The grail reinforces attrition rather than burst.
- The resource depot produces Mercury, matching the faction row's bottleneck.
- Magic guild rolls favor Nightshade: Unnatural Calm, Web, Enlarge Shadow,
  Despair, Read Minds, Shade Cloak, Death's Grip, Fatal Decay.

Depth takeaway:

Necropolis should never be reduced to "units are undead." Its depth lives in
where death is banked: as units, energy, summons, healing, denial, or enemy
morale collapse. Custom factions using this pattern need a visible death-to-value
economy with limits; otherwise it becomes either automatic snowball or flavor
text.

### Dungeon (`dungeon`)

Evidence:

- `DB/fractions/3_dungeon.json`: localized as Dungeon, biome `Dirt`, resource
  `gemstones`; description says Alvar focuses on subterfuge and versatility and
  each unit has two attack types.
- Units: `DB/units/units_logics/dungeon`, `DB/units/units_views/dungeon`.
- Heroes: `DB/heroes/dungeon`; specs:
  `DB/heroes_specializations/specializations_dungeon.json`.
- City: `DB/objects_logic/cities/dungeon_city.json`; laws:
  `DB/fractions_laws/fractions_laws_table_dungeon.json`.
- Faction skill: `skill_faction_dungeon` / Triumvirate's Strength gives a
  once-per-round choice among Attack, Defense, and Spell Power stances.

Decision identity:

Dungeon is the mode-switch faction. Nearly every unit has a primary attack plus
a Fighting Style alternative, and the hero skill mirrors this with one active
stance per round. Depth comes from matching the current board state to the
correct mode, not from always using the highest-stat action.

Unit and upgrade decision patterns:

| Tier | Family | Base role | Standard upgrade | Alternate upgrade | Depth point |
| --- | --- | --- | --- | --- | --- |
| 1 | Troglodyte | Melee with Viscous Spit style | Infernal Troglodyte adds Toxic Spear/defense | Toxic Troglodyte adds Alert and Toxic Blood | Pick defensive poison or aggressive reaction pressure. |
| 2 | Infiltrator | Blink, Weak Spot, Hit and Run | Guile Infiltrator adds Staggering Hits and Shadowstrike | Bleak Infiltrator adds Sharper Blade and Veil of Shadows | Pick direct strike control or stealth/buff safety. |
| 3 | Onyx Dancer | Ranged Thousand Cuts, bouncing glaive style | Jasper Dancer adds melee-shooter profile, Draconic Blade, Swift Strike | Aureate Dancer pushes initiative | Pick hybrid melee access or ranged tempo. |
| 4 | Minotaur | Eager melee with Grand Slam | Minotaur Lord adds Parry and Unyielding Will | Minotaur Vanguard adds Adrenaline Surge and damage | Pick defensive staying power or snowball offense. |
| 5 | Medusa | Ranged Sharpshooter with Slither Away | Sculptor adds Duelist and Petrification | Queen adds Countershot and Marble Arrows | Pick active lockdown or overwatch retaliation. |
| 6 | Hydra | Sweeping multi-target melee | Chthonic Hydra adds poison, regen, All Heads on Deck | Infernal Hydra adds Weakening Venom and damage | Pick attrition tank or aggressive debuff damage. |
| 7 | Cave Dragon | Flying breath, Magic Immunity IV, Inner Flame | Black Dragon deepens immunity and Fires of Dominion | Ashen Dragon adds Dominating Presence and Dragonflight | Pick raw supremacy or reposition/control. |

Hero specialization coverage:

- Enatee: Medusa specialist.
- Tellaris the Betrayed: Masterful Early Start.
- Stinger: Heroic Strike poison.
- Kieran: Troglodyte specialist.
- Mouaren: Infiltrator specialist.
- Devir, son of Devir: Minotaur specialist.
- Creta, daughter of Navarr: Gem Seeker.
- Rhea: Four-Leaf Horseshoe luck.
- Gleard the Grey: Arcane Dominion.
- Kelarr, son of Navarr: Wish to Learn.
- Zakron the Great: Spellweaver.
- Sister Deira: Masterful Arina's Chosen.
- Motley: Onyx Dancer specialist.
- Ylwari: Charismatic.
- Glastor: Wealthy.
- Typhona: Hydra specialist.
- Sunny Rauktol: Radiating Knowledge.
- Lodos: Shadowmastery.

Strategic levers:

- Laws reinforce Fighting Style damage per unit family (`armed_ability_trogl`,
  `armed_ability_assassin`, `armed_ability_blade_dancer`, etc.), external vision
  (`Spy Network`), ore/building economy, diplomacy, marketplace efficiency, and
  Triumvirate attribute scaling.
- `Build_Spy_Network` grail completely removes fog of war and doubles local
  dwelling growth. Dungeon's city endgame is information dominance, not only
  combat power.
- Magic guild roll weights are unusually broad and high on information/utility
  spells: Ground Sight, Clear View, Read Minds, Reinforcements, Naira's Veil,
  Assemble, Farsight, Primordial Chaos.

Depth takeaway:

Dungeon teaches that "versatile" only has depth when modes exclude each other.
If a custom unit has two attacks, each attack must solve a different problem and
must have a situation where the other attack is wrong.

### Grove (`nature`)

Evidence:

- `DB/fractions/4_nature.json`: localized as Grove, biome `Autumn`, resource
  `crystals`; description emphasizes unique, expensive elemental spirits.
- Units: `DB/units/units_logics/nature`, `DB/units/units_views/nature`.
- Heroes: `DB/heroes/nature`; specs:
  `DB/heroes_specializations/specializations_nature.json`.
- City: `DB/objects_logic/cities/nature_city.json`; laws:
  `DB/fractions_laws/fractions_laws_table_nature.json`.
- Faction skill: `skill_faction_nature` / Murmuring starts battles with Focus
  Charges.

Decision identity:

Grove is the elemental investment faction. Its units are individually powerful,
but their depth comes from focus economy, elemental awakenings, and expensive
specialists. The player decides which elemental tool matters enough to fund and
protect.

Unit and upgrade decision patterns:

| Tier | Family | Base role | Standard upgrade | Alternate upgrade | Depth point |
| --- | --- | --- | --- | --- | --- |
| 1 | Faun | Ranged with Parry | Faun Archer improves ranged precision | Faun Warrior becomes melee and gains Nature's Fury | Pick safe ranged poke or committed melee tempo. |
| 2 | Hoplet | Flying melee with Leeching Hop | Dawn Hoplet gains Swift Strike and Morning Dew | Dusk Hoplet gains Magic Core and Bloom | Pick attack tempo/healing or magic/focus value. |
| 3 | Vine Iriyad | Slow Earth body with Area Strike | Fungal Iriyad adds cover, Stoneheart, Unrelenting Stone | Crystal Iriyad adds Crystal Thorns and Earthshatter | Pick defensive stone wall or punishing counter-control. |
| 4 | Naiad | Ranged Blink, Water Awakening | Vernal Naiad adds Rivulet Retreat | Brumal Naiad adds Icy Veins and Whirlpool | Pick mobility escape or debuff control. |
| 5 | Herbomancer | Long Reach, Mushroom Magic, Shroomsong/Bees | Sporemancer adds Protective Roots | Murmurmancer adds Power of Murmurs and Echoes | Pick protection or faction-resource amplification. |
| 6 | Qilin | Fast Air melee | Thunder Qilin adds Cloud Nine, Ball Lightning, Thunderstrike | Mist Qilin adds Scintillating Scales and Mist Form | Pick aggressive mobility/burst or evasive defense. |
| 7 | Phoenix | Flying Fire elite | Flaming Phoenix adds Immortal and Heatwave | Energy Phoenix adds Eternal Flame and Supernova | Pick resurrection/sustain or explosive burst. |

Hero specialization coverage:

- Eith: Pathfinder.
- Gorel Spearhead: Shooter.
- Gingertail: Faun specialist.
- Old Pilgrim: Masterful Guillotine.
- Octavia: Four-Leaf Horseshoe.
- Mreowa: Charming Shine, Crystal economy.
- Faleor: Masterful Fireball.
- Alluring Sh'a: Charismatic.
- Aunt Daliar: Wish to Learn.
- Vatawna: Spiritual Vigor.
- Elder Tss'kish: Herbomancer specialist.
- Aeliniel: Masterful Firewall.
- Glacia: Masterful Ice Bolt.
- Vim: Masterful Cave In.
- Halon: Masterful Chain Lightning.
- Echolily: Masterful Mirror Copy.
- Sullie: summoned Avatar improvement.
- The Minstrel: Focus generation and enemy focus denial.

Strategic levers:

- Laws reinforce luck, external dwellings, focus generation, negative-effect
  reduction, expanded magic-guild unlocks, temporary spell level, native-area
  bonuses, elite elemental lines, and ability-cost reductions for elemental
  awakenings.
- `Build_Spring_of_Life` grail gives +1 growth to all creatures in all cities
  plus local growth doubling. This fits Grove's expensive-unit economy.
- Magic guild rolls strongly favor Primal spells: Thunderbolt, Ground Sight,
  Thick Hide, Wean, Fire Globe, Crystal Crown, Ice Bolt, Firewall.

Depth takeaway:

Grove should not be balanced by giving every elemental unit every tool. Its
depth comes from scarcity: focus, cost, and the need to choose one element's
solution under pressure.

### Hive (`demon`)

Evidence:

- `DB/fractions/5_demon.json`: localized as Hive, biome `Lava`, resource
  `crystals`; description emphasizes swift aggressive tactics, single-minded
  ranks, and exploiting opponent diversity.
- Units: `DB/units/units_logics/demons`, `DB/units/units_views/demons`.
- Heroes: `DB/heroes/demons`; specs:
  `DB/heroes_specializations/specializations_demon.json`.
- City: `DB/objects_logic/cities/demon_city.json`; laws:
  `DB/fractions_laws/fractions_laws_table_demon.json`.
- Faction skill: `skill_faction_demons` / Summon Swarm lays eggs once per round,
  spawning Fire Larvae next round from Hive Spawn HP.

Decision identity:

Hive is aggressive compounding. The units reward tempo, pressure, Hivemind
roles, larvae/summon pressure, and asymmetric information. Its depth comes from
creating a snowball route that is strong but interruptible.

Unit and upgrade decision patterns:

| Tier | Family | Base role | Standard upgrade | Alternate upgrade | Depth point |
| --- | --- | --- | --- | --- | --- |
| 1 | Parasite | Long Reach, Topple the Strong | Warden Parasite becomes Nest Protector and tougher | Ravager Parasite becomes Vanguard and faster/offensive | Pick defense hive role or forward pressure. |
| 2 | Locust | Double Strike with Harvest movement | Overgrown Locust adds Parry/Nest Protector | Harvester Locust keeps Harvest and Vanguard | Pick protected brawler or mobile finisher. |
| 3 | Hornet | Very fast flyer | Chanter is slower but defensive/supportive with Whispers of Doubt | Stinger is fast/offensive with Piercing Sting | Pick support disruption or strike tempo. |
| 4 | Scorpion | Melee with Adaptation: Attack/Defense/Speed | Volcanic Scorpion protects nest | Spelaean Scorpion vanguards damage | Pick which stat adaptation solves the current fight. |
| 4 | Fire Larva | Summoned fragile bomb | No normal upgrade line in inspected unit set | Blow Up and Fiery Embrace define summon pressure | Summon value depends on timing and opponent response. |
| 5 | Reaver | High-variance damage and Rapid Assault | Menacing Reaver gains resilience/Terror | Maniacal Reaver gains Murderous Glee and Beelzebub's Blessing | Pick safer fear/control or volatile kill chain. |
| 6 | Waurms | Blink, Corpse Eater, Demonic Stench | Devourer adds Devour and Nest Protector | Pyroboros becomes ranged eater with Area Strike/Duelist | Pick corpse-eating melee sustain or ranged area pressure. |
| 7 | Hive Queen | Soul Assimilator, Beelzebub's Agenda, Squash the Weak | Hive Mother adds Promise of Love and Nest Protector | Hive Huntress adds Vanguard, damage, Swift Strike | Pick command/sustain queen or hunter-finisher queen. |

Hero specialization coverage:

- Niev: Shooter.
- Maelstrom: Reaver specialist.
- Nor: Wish to Learn.
- Zoran, the Self-Founded: Waurm specialist.
- Curson, Duke of Rage: Heroic Strike initiative reduction.
- Tavi: Fire Larva summon improvement.
- Lo: Locust specialist.
- Goldentongue: Rousing Presence.
- Abigor, Duke of Battle: Chessmaster tactics.
- Fleu: Wayfarer.
- Xirr: Resistant to Elements.
- Bathym, Duke of Jewels: Crystal economy.
- Leira: Hornet specialist.
- Groo: Hive Queen specialist.
- Mila: Masterful Haste.
- Oriax: Masterful Blink.
- Khariseth: Primal Weaving.
- Pauper: army-wide Speed scaling.

Strategic levers:

- Laws accelerate law unlocks (`Laws of the Hive`), boost larvae death damage,
  focus reserves, exact neutral/enemy information, mana cost reduction,
  upgraded creature economy, external dwellings, conquest bonuses outside
  controlled area, and morale/luck trigger scaling.
- `Build_Eternal_Flame` / Chorus Conductor grail grants allied Attack and Lucky
  Strike Damage plus local growth, reinforcing offense.
- Magic guild rolls are broad and relatively even compared with Temple, Undead,
  Grove, and Schism, matching a faction that wins more from tempo and creature
  pressure than narrow school identity.

Depth takeaway:

Hive's aggression is deep because it is delayed, positional, and answerable:
eggs become larvae next round, corpse-eaters need corpses, Hivemind roles
differentiate upgrades. Custom Hive-like factions should avoid permanent,
automatic snowball without counterplay windows.

### Schism (`unfrozen`)

Evidence:

- `DB/fractions/6_unfrozen.json`: localized as Schism, biome `Snow`, resource
  `mercury`; description emphasizes denying enemy abilities/magic and summoning
  growing monstrous hordes.
- Units: `DB/units/units_logics/unfrozen`, `DB/units/units_views/unfrozen`.
- Heroes: `DB/heroes/unfrozen`; specs:
  `DB/heroes_specializations/specializations_unfrozen.json`.
- City: `DB/objects_logic/cities/unfrozen_city.json`; laws:
  `DB/fractions_laws/fractions_laws_table_unfrozen.json`.
- Faction skill: `skill_faction_unfrozen` / Abyssal Communion increases
  Communion after victories, giving Schism unit-count bonuses in battle, then
  halves each morning.

Decision identity:

Schism is denial plus scaling summons. It makes opponents worse at using their
tools while growing its own monstrous count through Communion and summon
effects. Its depth comes from deciding what to suppress: speed, initiative,
magic, focus, cooldowns, mind control, or board position.

Unit and upgrade decision patterns:

| Tier | Family | Base role | Standard upgrade | Alternate upgrade | Depth point |
| --- | --- | --- | --- | --- | --- |
| 1 | Ra'Shoth | Flying melee summon-rite unit | Stinging Ra'Shoth becomes ranged | Ferocious Ra'Shoth gains Sweeping Strike | Pick safe ranged scaling or melee area pressure. |
| 2 | Cultist | Long Reach, abyss glance | Binder adds Abyssal Tendril | Votary adds Slow/Sluggishness attack mods | Pick active damage/control or repeated denial. |
| 3 | Aga'Shoth Rider | Plow Through, Piercing Cold, Icy Breath | Tamer improves tempo | Mat'ha adds Aga'Shoth's Help and Icy Spikes | Pick speed or support/control spike. |
| 4 | Grand Shoth | Flying Frost summon rite | Unspeakable Shoth adds Double Strike | Unthinkable Shoth adds Black Ice Shard | Pick direct melee pressure or ranged frost attack. |
| 5 | Concubus | Ranged Nimbleness, magic denial, Handcuffs | Mistress adds ability denial and Hourglass | Bewitcher adds Duelist, Flog Idle Mind, Bewitch into Passivity | Pick broad denial or aggressive mind-control pressure. |
| 6 | Arbitrator | Ranged command unit with reposition/fear | Rift Arbitrator adds Disgorge Storm | Bloated Arbitrator adds Switch Places and Frozen Pages | Pick fear/storm pressure or position swapping/control. |
| 7 | Abyssal Envoy | Absolute Resistance, summon rite, Will of the Abyss | Overseer adds Area Strike and Moment of Insanity | Executor adds fixed damage and Control Mind | Pick area/debuff dominance or control finisher. |

Hero specialization coverage:

- Nihil: Wayfarer.
- Blackhorn: Spellweaver.
- Matastala the White: Chessmaster.
- Janhei: Cultist specialist.
- Mara Mat'ha: Aga'Shoth Rider specialist.
- The Iron Master: Concubus specialist.
- Wal'kha: Primal Weaving.
- Changeling Urgo: summoned Avatar barrier/upgrade.
- Martyr Tho: Mercury economy.
- Grellekh the Betrayer: Fighter.
- Icequeen Hel'Ghat: Heart of Ice.
- Kwinri: Ra'Shoth specialist.
- The Eye Collective: Grand Shoth specialist.
- Tolketh: Heroic Strike speed reduction.
- Ulkuth: Pathfinder.
- Ra'Davok: Masterful Carapace.
- Sister Keiri: Masterful Umbral Grip.
- Dhuvri: True Believer, Communion scaling.

Strategic levers:

- Laws reinforce XP, native-terrain bonuses, per-tier hero-stat conversion
  (`Unfrozen Strength I` through `VII`), mana restoration, extra Involuntary
  Summons, effect-duration extension, enemy mana/focus denial, artifact dust,
  morning Communion restoration, all-terrain-native treatment, and enemy spell
  cooldown increases.
- `Build_Frigid_Firmament` / Firmament's Abyss makes Mage Guild construction
  unlock all spells of the corresponding tier and doubles local growth.
- Magic guild rolls favor Arcane/space spells such as Early Start, Energyze,
  Optical Illusion, Decimate, Energy Explosion, Reinforcements, Blink, Carapace.

Depth takeaway:

Schism is not just a summoner faction. It is a suppression faction whose summons
matter because the enemy's answers are being taxed. Custom factions copying this
pattern need explicit deny targets and decay/refresh rules for their scaling
resource.

## Tactical Decision Levers

These levers repeatedly appear in the live data and are good candidates for
custom synthesis:

- Attack channel choice: melee, ranged, Long Reach, breath, area, countershot,
  or alternative attack. Dungeon uses this most directly, but Temple Angels,
  Necropolis Vampire Scholar, Hive Pyroboros, and Schism Stinging Ra'Shoth also
  show role-switching.
- Timing choice: active buffs and specials often have cooldown/focus/rank costs.
  Fine Bolts, Valiant Cry, Adaptation, Awaken abilities, Summoning Rites,
  Handcuffs, Reposition/Fear, and Dragonflight are not just text; they ask
  whether this turn is worth spending.
- Positional choice: flying, Blink, Slither Away, Rivulet Retreat, Ball
  Lightning, Switch Places, Hit and Run, and terrain/native bonuses change what
  board state is desirable.
- Attrition choice: Necromancy, Vampirism, Rewind Death, Blood Transfusion,
  Corpse Explosion, Fire Larvae, Communion, and Grove growth/grail effects turn
  casualties into future resources.
- Denial choice: slow, initiative reduction, spell-school denial, magic-level
  reduction, negative-effect immunity, focus/mana denial, no escape/surrender,
  and cooldown modification are deep only when the target and counterplay are
  clear.
- Economy choice: resource specialists, resource depots, banks, markets,
  training buildings, magic-guild rolls, external-dwelling laws, and grails bind
  combat identity to map pacing.

## Strategic Decision Levers

Map and city systems in the live data show how faction identity leaves combat:

- Resource bottleneck: Temple/Dungeon use Gems, Necropolis/Schism use Mercury,
  Grove/Hive use Crystals. Matching laws and depots make these real strategic
  constraints.
- Magic-school bias: Temple -> Daylight, Necropolis -> Nightshade, Grove ->
  Primal, Schism -> Arcane/space. Dungeon and Hive are broader, reflecting
  versatility and aggression rather than school purity.
- Hero roster spread: each faction has movement/scouting heroes, unit-line
  specialists, economy heroes, school masters, Heroic Strike modifiers, and
  spell replacement heroes. This creates draft depth.
- City endgame identity: Temple's Golden Calf is economic/growth; Necropolis'
  Everserpent is defensive/luck mitigation; Dungeon's Spy Network is vision;
  Grove's Spring of Life is global growth; Hive's Chorus Conductor is offense;
  Schism's Firmament's Abyss is spell access.
- Law identity: good laws do not merely stack universal stats. They push a
  faction's verbs: Temple buff/morale/stat conversion, Necropolis conversion and
  attrition, Dungeon fighting styles and information, Grove focus/elemental
  growth, Hive swarm/aggression/information, Schism scaling/denial.

## Real Tradeoffs Versus False Choices

Real tradeoffs in live native data:

- Temple Guard Captain vs Sun's Aegis: one improves attack volume, the other
  changes the unit into a defensive/grouping piece. This changes formation and
  target priority.
- Necropolis Skeleton Warrior vs Skeleton Archer: one preserves cheap melee
  mass, the other changes stack positioning and vulnerability.
- Dungeon stance choice: Triumvirate's Strength grants one of Attack, Defense,
  or Spell Power per round. The player must read the current turn.
- Grove Phoenix line: Flaming Phoenix leans into survival/Immortal, Energy
  Phoenix leans into Supernova burst. The same tier-7 slot offers different
  endgame plans.
- Hive Scorpion Adaptation: Attack/Defense/Speed are situational buffs. The
  decision is shallow only if one stat is always optimal.
- Schism denial selection: Cultist/Votary, Arbitrator/Bloated Arbitrator, and
  Abyssal Executor choices matter because the player can attack enemy action
  economy, positioning, or mind control.

False choices to avoid:

- Upgrade A has +2 Attack and upgrade B has +2 Defense, but the battle role is
  unchanged and one stat is obviously better in all relevant fights.
- Adding a cooldown ability that is always pressed on cooldown and has no target
  or timing question.
- Giving every unit a summon, a heal, and a debuff so the faction has no
  internal scarcity.
- Creating a hero specialization that duplicates a law or building without
  changing draft, build order, or battle sequencing.
- Making a faction "versatile" by giving every stack all attack types. Dungeon
  works because each unit has a specific alternative style and the faction skill
  forces one stance at a time.
- Making economy bonuses pure acceleration with no relation to faction
  bottlenecks.

## Depth Anti-Patterns For Custom Factions

- Do not confuse unique text with unique play. If two abilities answer the same
  problem at the same timing window, one is probably fake depth.
- Do not lean on hidden fallbacks. If the source data or native mechanic route is
  discoverable, use it. A custom faction should fail visibly when its real route
  is missing rather than silently borrowing unrelated behavior.
- Do not make probability passives carry a faction identity unless the player can
  plan around them. Native Olden Era tends to expose focus-costing actives,
  deterministic passives, or clear trigger conditions.
- Do not add a powerful faction resource without a decay, cap, spending choice,
  or counterplay window. Necromantic Energy and Communion are deep because they
  have constraints.
- Do not make alternate upgrades pure stat variants. The native examples usually
  change role, attack channel, sustain, control, or resource conversion.
- Do not copy a native faction skill without also copying the supporting law,
  unit, hero, and city grammar that makes it meaningful.
- Do not over-stack universal Attack/Defense laws. They blur faction identity
  unless they are tied to a specific line, terrain, stance, action type, or hero
  conversion rule.
- Do not write player-facing promises before verifying the data route. For
  future custom factions, every promised summon, terrain rule, magic-school rule,
  or attack mode needs a concrete data row or traced native mechanic.

## Concrete Design Rules For Custom Synthesis

1. Start from one faction verb.
   Examples: bless, convert death, switch mode, awaken elements, swarm, deny.
   Every unit line, hero group, law cluster, and city unique should support that
   verb from a different angle.

2. Give each unit family one readable combat job and one upgrade fork.
   The base unit should teach the job. The standard upgrade should deepen it.
   The alternate upgrade should create a different tactical question.

3. Require a cost for every high-impact action.
   Use cooldown, focus charge, action cost, positioning, target restriction,
   delayed payoff, stack vulnerability, or resource dependency. Avoid free
   universal uptime.

4. Make hero specializations draft-changing.
   A hero should change at least one of: opening army, early build order, map
   route, magic school, target unit line, faction resource, or battle timing.

5. Use laws as strategic commitments, not a second passive list.
   A law should steer the player toward a plan: specific unit line, terrain,
   school, economy, external dwellings, information, or faction resource.

6. Put the city into the faction identity.
   The grail, depot resource, magic-guild weights, training/vision/special
   buildings, and build orders should all agree with the faction's decision
   grammar.

7. Keep counters legible.
   If a faction denies magic, morale, focus, initiative, speed, escape, or
   healing, document exactly what it denies and where the opponent can still
   answer.

8. Preserve scarcity.
   Grove without focus scarcity, Hive without delayed swarm windows, Necropolis
   without conversion limits, and Schism without Communion decay would all be
   simpler despite being stronger.

9. Prefer deterministic depth over hidden randomness.
   If a source creature has a probabilistic identity, convert it into a clear
   active, cooldown, stack condition, or target rule when adapting to Olden Era.

10. Validate against the live archive.
    Before designing from memory, inspect the current `Core.zip` rows for
    matching native data shapes. In this live archive, paths and localization
    ownership differ by category; assuming `heroes.json` or a single city field
    owns everything will produce stale documentation.

## Practical Synthesis Checklist

For a future custom unit line:

- What is the base job?
- What does the standard upgrade deepen?
- What does the alternate upgrade change?
- Which decision does the active ability ask for: timing, target, position,
  resource, or denial?
- Which hero specialization or law makes this unit a strategic commitment?
- What is the counterplay?

For a future custom hero:

- Does the specialization change draft/build route, or is it just a stat bonus?
- Does it interact with the faction verb?
- Does it overlap with an existing law/grail in a way that creates redundancy?
- Does the starting army reinforce the specialization, as with native unit-line
  specialists starting with repeated target units?

For a future custom city:

- Does the resource depot match the faction bottleneck?
- Does the magic guild bias match the faction's spell identity?
- Does the grail amplify the faction verb rather than generic power?
- Do unique buildings create map decisions such as vision, training, growth,
  spell access, or external-dwelling economy?

For future faction laws:

- Include some generic economy/opening laws, but make the middle and late laws
  identity-bearing.
- Tie elite laws to named unit families and real mechanic hooks.
- Include at least one map-control or information lever if the faction identity
  calls for it.
- Include at least one faction-resource rule if the faction has a unique
  resource or scaling state.

## Uncertainty And Follow-Up

- This document is grounded in the live `Core.zip` data as inspected on
  2026-05-25. If the Steam install is repacked, re-run the source inventory
  before using this as current truth.
- Some localization tokens in the live archive are unresolved or stale
  (`human_narrative_desc`, `undead_narrative_desc`, and
  `fraction_law_undead_33_*` were observed unresolved). The design conclusions
  above rely on resolved descriptions, unit/view rows, hero specialization rows,
  city rows, and law rows rather than those unresolved tokens.
- This is a design philosophy document, not a mechanical implementation audit.
  Any custom faction that wants to reuse a native mechanism still needs a
  separate data/schema validation pass and, for runtime behavior, static tracing
  where the data route is not self-evident.
