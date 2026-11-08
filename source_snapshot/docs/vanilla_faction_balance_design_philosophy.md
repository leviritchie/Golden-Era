# Vanilla Faction Balance Design Philosophy

This document records balance patterns from the live Olden Era / Golden Era
native faction data. "Vanilla faction" here means the live native factions in
the Steam install `Core.zip`, not the HoMM3 custom faction plans in this repo.

Primary source inspected:

- `V:\SteamLibrary\steamapps\common\Heroes of Might and Magic Olden Era - Golden Era\HeroesOldenEra_Data\StreamingAssets\Core.zip`

Native faction scope:

- `human` / Temple
- `undead` / Necropolis
- `dungeon` / Dungeon
- `nature` / Grove
- `demon` / Hive
- `unfrozen` / Schism

HoMM3 faction rows are present in this live archive, but they are out of scope
for this vanilla design read.

## Source Inventory

The live archive schema differs slightly from the requested shorthand paths:

- Faction rows: `DB/fractions/1_human.json`, `2_undead.json`,
  `3_dungeon.json`, `4_nature.json`, `5_demon.json`, `6_unfrozen.json`.
- Unit logic rows: `DB/units/units_logics/<dir>/*.json`; note plural
  `units_logics`, not `units_logic`.
- Unit view/card rows: `DB/units/units_views/<dir>/*_v.json`.
- Native unit dirs: `humans`, `undead`, `dungeon`, `nature`, `demons`,
  `unfrozen`.
- Native hero rows: `DB/heroes/humans`, `DB/heroes/necros`,
  `DB/heroes/dungeon`, `DB/heroes/nature`, `DB/heroes/demons`,
  `DB/heroes/unfrozen`. Undead heroes use the `necros` directory and
  `necro_hero_*` ids even though the faction id is `undead`.
- Hero specialization rows: `DB/heroes_specializations/specializations_human.json`,
  `specializations_necro.json`, `specializations_dungeon.json`,
  `specializations_nature.json`, `specializations_demon.json`,
  `specializations_unfrozen.json`.
- City/building rows: `DB/objects_logic/cities/human_city.json`,
  `undead_city.json`, `dungeon_city.json`, `nature_city.json`,
  `demon_city.json`, `unfrozen_city.json`.
- Law tables: `DB/fractions_laws/fractions_laws_table_<faction>.json`.
- Localization used for names and card labels:
  `Lang/english/texts/cities.json`, `fractions.json`, `units.json`,
  `unitsAbility.json`, `heroInfo.json`, `heroes.json`,
  `factionLaws.json`, and `heroSkills.json`.

The live archive includes generated HoMM3 faction data beside the native data.
The native balance pattern is therefore identified by faction ids and native
directories, not by scanning all `DB/fractions` or all hero/unit folders.

## System-Wide Native Balance Structure

Every native faction has a common structural budget:

- Seven creature tiers.
- Three unit variants per tier: base, standard upgrade, alternate upgrade.
- Usually 21 creature logic rows per faction. Hive has an extra `lava_larva`
  row used by its faction mechanics, giving `demons` 22 native unit logic rows.
- Eighteen skirmish heroes per faction, split 9 might / 9 magic.
- Two hero stat templates per faction: one for might heroes and one for magic
  heroes. Examples: Temple might starts 2/3/1/1 and magic starts 1/1/2/3;
  Hive might starts 4/0/2/1 and magic starts 1/0/4/2.
- Seven hire buildings per faction with one base unit line each. Upgrades are
  exposed through the same `unitsHire.units[*].sids` triplet.
- Common city infrastructure appears in most or all factions: `Build_Main`,
  `Build_Tavern`, `Build_Market`, `Build_Magic_Guild`, `Build_Bank`,
  `Build_Treasury`, `Build_Resource_Depot`, `Build_Resource_Depot_level_2`,
  `Build_Wall`, and one grail building.
- Faction laws use repeated economic, growth, hero-stat, and unit-stat shapes,
  then add a smaller number of faction-defining rules.

Common weekly growth from hire buildings:

| Faction | Tier 1 | Tier 2 | Tier 3 | Tier 4 | Tier 5 | Tier 6 | Tier 7 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Temple | 18 | 14 | 7 | 6 | 3 | 2 | 1 |
| Necropolis | 30 | 16 | 13 | 10 | 5 | 3 | 2 |
| Dungeon | 27 | 13 | 8 | 5 | 3 | 2 | 1 |
| Grove | 12 | 8 | 6 | 4 | 3 | 2 | 1 |
| Hive | 21 | 13 | 7 | 5 | 3 | 2 | 1 |
| Schism | 20 | 12 | 8 | 4 | 3 | 2 | 1 |

Growth is not just a tier curve; it is part of identity. Necropolis has the
largest base population and a tier-7 growth of 2, because its unit stats are
individually lower and its laws/heroes reinforce reanimation. Grove has the
lowest early growth because each unit line is individually expensive and
ability-rich. Dungeon and Hive sit in the middle but push tempo and lethality.

## Faction-by-Faction Balance Identity

### Temple / Human

Source examples:

- Faction row: `DB/fractions/1_human.json`.
- Units: `DB/units/units_logics/humans/*.json` and
  `DB/units/units_views/humans/*_v.json`.
- Heroes: `DB/heroes/humans/human_hero_*.json`.
- Specializations: `DB/heroes_specializations/specializations_human.json`.
- City: `DB/objects_logic/cities/human_city.json`.
- Laws: `DB/fractions_laws/fractions_laws_table_human.json`.

Identity: disciplined, defensive, buff-amplifying, and rounded. The faction
leans on reliable ranged pressure, protection, and effects that reward
positive buffs rather than raw stat extremes.

Unit pattern:

- Tier 1 Swordsman line starts as a durable low-tier melee unit: `esquire`
  has 12 hp, 4/4 offence/defence, and `Ranged Defense I`. The standard upgrade
  adds `Double Strike`; the alternate Sun's Aegis shifts toward defense with
  15 hp, 8 defence, `Aegis`, and `Anointed for Defense`.
- Tier 2 Crossbowman line is the first core ranged engine. `crossbowman`
  has a ranged default attack, a half-damage melee alternative, and the active
  `Fine Bolts`. Upgrades split into `Double Shot` pressure or `Sharpshooter`
  plus `Piercing Shot`.
- Tier 3 Griffin line is mobility and reaction. Base has flying, `Alert I`,
  and `Valiant Cry`; Temple Griffin improves speed/initiative and `Alert II`,
  while Guardian Griffin trades into tougher grouping/protection.
- Tier 4 Lightweaver line is slow ranged support: low speed/initiative but
  high utility through `Inner Glow`, `Holy Ablution`, or `Exaltation`.
- Tier 5 Cavalry line is a charge profile. Base carries `Piercing Strike I`,
  `Inspiring`, and `Jousting Bonus`; standard upgrade adds `Charge!`, while
  alternate doubles down on defensive/offensive anointment stats.
- Tier 6 Inquisitor line is resistant front-line control. All variants have
  `Absolute Resistance`; upgrades split tank (`Celestial Armor`) and damage
  (`Swift Penance`).
- Tier 7 Angel line is a premium flying ranged embodiment. Base already shoots
  and has `Refract and Reflect`; Archangel adds `Sharpshooter` and `Devouring
  Chalice`, while Apotheosis shifts to speed, `Duelist`, and `Unbending Pride`.

Hero pattern:

- Temple has a balanced might/magic roster. Might heroes use 2/3/1/1 and magic
  heroes use 1/1/2/3.
- Specializations include map utility (`Wayfarer`, `Pathfinder`), line
  specialists (`Salt of the Earth`, `Jaeger`, `Jouster`, `Weaving the Light`),
  economy (`Gem Seeker`, `Wealthy`), broad morale (`Rousing Presence`), spell
  replacement (`Compassionate Healer`, `Blessing`, `Hymn to Arina`, `Heart of
  Hearts`), and faction-skill strengthening (`True Lord`, `Heroic Smite`).
- Line specialists follow a recurring native template: `cityUnitsIncrement`
  for the base line, then speed +1, initiative +1, hp percent, and level-scaled
  offence/defence modifiers for all three variants.

Buildings and laws:

- Unique Temple city sections include `intelligences` with `Build_Intelligence_Academy`
  / Scouting Skyship, `trainingRanges` with `Build_Training_Range` / Guild of
  Six Winds, and `Build_Golden_Calf` as grail.
- Laws reinforce the identity: `Elite Swordsmen` boosts Swordsman growth and
  defence, `Execute Excellence` extends friendly positive effects, training
  laws grant direct hero stats, `Architect's Mastery` grants an extra daily
  construction limit, and `Focus is the Key` gives units extra energy per
  round.

Balance lesson: Temple can have many tools because they are largely gated by
buff setup, steady positioning, and support windows. Custom factions should not
copy Temple's buff extension and also add unbounded burst without removing
some reliability elsewhere.

### Necropolis / Undead

Source examples:

- Faction row: `DB/fractions/2_undead.json`.
- Units: `DB/units/units_logics/undead/*.json` and
  `DB/units/units_views/undead/*_v.json`.
- Heroes: `DB/heroes/necros/necro_hero_*.json`.
- Specializations: `DB/heroes_specializations/specializations_necro.json`.
- City: `DB/objects_logic/cities/undead_city.json`.
- Laws: `DB/fractions_laws/fractions_laws_table_undead.json`.

Identity: attrition, recursion, drain, debilitation, and high population.
Necropolis pays for very high growth with many low-stat bodies and a long
gameplan built around necromancy and death synergies.

Unit pattern:

- Tier 1 Skeleton growth is 30 per week. The base `skeleton` is only 6 hp and
  4/1 offence/defence. The alternate `skeleton_upg_alt` becomes a ranged
  Skeleton Archer without gaining durability.
- Tier 2 Wight line is fast, fragile, flying disruption. `flicker` has 8 hp
  and 0 defence but speed 6, initiative 7, and `Memory Devourer`; upgrades add
  `Howl of the Banshee` or `Nightmares`.
- Tier 3 Undead Pet line is mid-volume melee. It carries `Melee Defense I`,
  then upgrades into `Call the Pack` aggression or `Protect the Fallen` /
  `Lacerated Wounds` defense.
- Tier 4 Graverobber line is reach utility with body economy. Base has
  `Dig Up Bones`; upgrades add `Ensnare Memories`, `Fetch!`, or `Hail!`.
- Tier 5 Lich line is ranged death magic. `lich` has `Rewind Death`; Pestilent
  Lich adds `Area Strike` and `Death's Embrace`; Sanguine Lich adds `Unlife,
  Undeath` and `Knowledge of Death`.
- Tier 6 Dread Knight line is heavy melee. Base and standard carry `Double
  Strike` and `Dreadful Presence`; alternate Hollow Reaper trades into `Death
  Stare`, `Hungering Hollow`, and `Reap Without Sowing`.
- Tier 7 Vampire line has growth 2 and sustain. Base has 150 hp, flying, and
  `Vampirism`; Vampire Lord adds durability and `Swift Strike`; Vampire Scholar
  becomes a reach caster with `Blood Transfusion` and `Corpse Explosion`.

Hero pattern:

- Necropolis might heroes use 3/1/1/2 and magic heroes use 1/0/2/4. Both
  templates are skewed away from defence and toward either offence or
  intelligence.
- Examples: Bulwark reduces incoming basic damage; Perfect Puppets boosts the
  Skeleton line; Dreadful War boosts Dread Knight; Undead Legion appears on
  both `necro_hero_8` and `necro_hero_17` and scales `necromancyPerBonus`;
  Alchemist produces mercury; Wealthy produces gold.
- Spell replacement specialties are disruptive and death-flavored: Berserker,
  Web, Despair, and Rewind replacements appear in the native specialization
  table.

Buildings and laws:

- Unique city sections include `manaFountains` with `Build_Well_Of_Souls`,
  `unitsConverters` with `Build_Skeleton_Converter`, and grail
  `Build_Gaping_Maw`.
- Laws are highly faction-defining: `Animate Dead I/V` scale necromancy and
  faction energy, `Death Equalizes All` uses `ignoreFractionsCount`, `Free
  Death` discounts unit hiring, `Forbidden Alchemy` discounts magic upgrades,
  and `Magic Absorption` applies enemy battle magic-school penalties.

Balance lesson: Necropolis gets extra bodies, recursion, and sustain because
many units are fragile or slow and because the faction's economy depends on a
death engine. Do not grant Necropolis-style recursion to a high-stat elite
line without reducing growth, cost efficiency, or direct damage.

### Dungeon

Source examples:

- Faction row: `DB/fractions/3_dungeon.json`.
- Units: `DB/units/units_logics/dungeon/*.json` and
  `DB/units/units_views/dungeon/*_v.json`.
- Heroes: `DB/heroes/dungeon/dungeon_hero_*.json`.
- Specializations: `DB/heroes_specializations/specializations_dungeon.json`.
- City: `DB/objects_logic/cities/dungeon_city.json`.
- Laws: `DB/fractions_laws/fractions_laws_table_dungeon.json`.

Identity: ambush, control, positional brutality, and elite monster scaling.
Dungeon mixes stealthy early units, ranged dagger/blade pressure, durable
monsters, and a late-game dragon ceiling.

Unit pattern:

- Tier 1 Troglodyte line is cheap, numerous, and simple. Upgrades add `Toxic
  Spear`, `Toxic Blood`, or `Alert I` rather than large active budgets.
- Tier 2 Infiltrator line is the faction's early mobility/control piece.
  `assassin` has `Blink` and `Weak Spot`; upgrades add `Shadowstrike`,
  `Veil of Shadows`, `Staggering Hits`, or `Sharper Blade`.
- Tier 3 Onyx Dancer line is a ranged/melee hybrid card. It carries `Ranged
  Attack` and `A Thousand Cuts`; upgrades split into melee-shooter flexibility
  with `Swift Strike` or higher initiative.
- Tier 4 Minotaur line is the honest bruiser. It has `Eager for Battle` and
  `Blood for Blood`; upgrades add `Parry` / `Unyielding Will` or `Adrenaline
  Surge`.
- Tier 5 Medusa line is a premium ranged control unit. Base already has
  `Sharpshooter` and `Slither Away`; upgrades add `Petrification`, `Duelist`,
  `Countershot`, or `Marble Arrows`.
- Tier 6 Hydra line is sweeping melee. All variants have `Swift Strike`,
  `Sweeping Strike`, and `Growing Teeth`; upgrades add poison/venom durability
  or higher offensive pressure.
- Tier 7 Dragon line is the top-end stat and immunity cap. Cave Dragon has
  275 hp, 29/25, flying, dragonbreath, `Magic Immunity IV`, and `Inner Flame`.
  Black Dragon reaches 350 hp and `Magic Immunity V`; Ashen Dragon adds
  `Dominating Presence` and `Dragonflight`.

Hero pattern:

- Dungeon might heroes use 2/2/2/1 and magic heroes use 0/2/2/3. It is less
  polarized than Hive or Necropolis, but still values spell power.
- Specializations include many line identities: Slithering Menace (Medusa),
  The Blind Folk (Troglodyte), Spy (Infiltrator), Balthazar's Lair
  (Minotaur), Danse Macabre (Onyx Dancer), and Alvarian Hydra.
- Non-line specialists include Gem Seeker, Wealthy, Charismatic, Four-Leaf
  Horseshoe, Arcane Dominion, Shadowmastery, and spell replacements such as
  Early Start and Arina's Chosen.

Buildings and laws:

- Unique sections include `heroBonusBanks` / `Build_Gymnasium`,
  `artifactChangers` / `Build_Lyceum`, and grail `Build_Spy_Network`.
- Laws include the global economy pattern plus factional information and
  market advantages: `Spy Network` grants object view radius,
  `Merchants Guild` disables market extra charge, `Jadame Maps` grants
  movement, `Dragon Scales` reduces magic damage, and `Dungeon Masters I`
  unusually boosts donor creature growth across several non-Dungeon unit ids.

Balance lesson: Dungeon's identity is not just high-end dragons. Its power is
distributed through ambush tools, information, hybrid ranged/melee units, and
stat-efficient monsters. A custom Dungeon-like faction should not put all
control, burst, and immunity onto one unit line.

### Grove / Nature

Source examples:

- Faction row: `DB/fractions/4_nature.json`.
- Units: `DB/units/units_logics/nature/*.json` and
  `DB/units/units_views/nature/*_v.json`.
- Heroes: `DB/heroes/nature/nature_hero_*.json`.
- Specializations: `DB/heroes_specializations/specializations_nature.json`.
- City: `DB/objects_logic/cities/nature_city.json`.
- Laws: `DB/fractions_laws/fractions_laws_table_nature.json`.

Identity: low growth, expensive elite creatures, elemental awakenings, and
high ability density. Grove's creatures are not numerous; they are built to
matter individually.

Unit pattern:

- Tier 1 Faun line has only 12 weekly growth. It begins as a ranged unit with
  `Parry`; alternate Faun Warrior becomes melee and gains `Nature's Fury`.
- Tier 2 Hoplet line has flying and active sustain/control. Base has
  `Leeching Hop`; Dawn Hoplet gains `Morning Dew`; Dusk Hoplet adds `Magic
  Core` and `Bloom`.
- Tier 3 Iriyad line is a durable earth embodiment. `ent` has 45 hp,
  `Area Strike`, `Embodiment of Earth`, and `Awaken: Earth I`; upgrades get
  two active abilities and more defensive or area pressure.
- Tier 4 Naiad line is ranged blink/water embodiment. It gains `Awaken: Water`
  and either retreat, whirlpool, or icy-vein control.
- Tier 5 Herbomancer line has reach and high active density. Base has two
  abilities (`Shroomsong`, `Swarm of Bees`); Sporemancer has three, adding
  `Protective Roots`.
- Tier 6 Qilin line has air embodiment and high speed/initiative. Thunder
  Qilin has three active abilities (`Awaken: Air II`, `Ball Lightning`,
  `Thunderstrike`).
- Tier 7 Phoenix line is a high-cost embodiment with flying, sweeping strike,
  awakenings, and resurrection/flame identity. Upgrades reach 7594 squad value
  and split into `Immortal` / `Heatwave` or `Eternal Flame` / `Supernova`.

Hero pattern:

- Grove might heroes use 2/1/2/2 and magic heroes use 1/2/2/2. It is the most
  evenly magical native stat spread.
- Specializations lean heavily into spell replacement and elemental schools:
  Wall of Flame, Ice Bolt, Cave In, Chain Lightning, Mirror Copy, and
  faction-specific Astral Summon replacements.
- Unit specialists exist but are fewer relative to magic identity: Faunsong
  (Faun) and Oldest Known Tree (Herbomancer) are examples.

Buildings and laws:

- Unique sections include `heroBonusBanks` / `Build_Mother_Nature`,
  `myceliumRoots` / `Build_Mycelium_Roots`, and grail `Build_Spring_of_Life`.
- Laws reinforce expensive, magical ecology: `Forest Magic` increases magic
  guild access and learned spells, `The Power of the Written Word` grants
  temporary magic level bonuses, `Fertile Ground` increases all barrack growth,
  `Children of the Wild` grants native-land map bonuses, and `Live roots`
  bans battle escape.

Balance lesson: Grove's ability density is paid for by lower growth and high
resource costs. Custom factions should not combine Grove-level active density
with Necropolis-level growth.

### Hive / Demon

Source examples:

- Faction row: `DB/fractions/5_demon.json`.
- Units: `DB/units/units_logics/demons/*.json` and
  `DB/units/units_views/demons/*_v.json`.
- Heroes: `DB/heroes/demons/demon_hero_*.json`.
- Specializations: `DB/heroes_specializations/specializations_demon.json`.
- City: `DB/objects_logic/cities/demon_city.json`.
- Laws: `DB/fractions_laws/fractions_laws_table_demon.json`.

Identity: extreme aggression, faction-wide hivemind roles, adaptation, and
tempo pressure. Hive is polarized: might heroes start with 4 offence and 0
defence, and many units split between "Nest Protector" and "Vanguard" upgrade
roles.

Unit pattern:

- Tier 1 Parasite line has reach and `Topple the Strong!`; upgrades branch
  into `Hivemind: Nest Protector` or `Hivemind: Vanguard`.
- Tier 2 Locust line has `Double Strike`; Harvester keeps `Harvest`, while
  Overgrown Locust trades active ability budget into bulk and protection.
- Tier 3 Hornet line is fast flying melee. Chanter becomes a protector with
  `Whispers of Doubt`; Stinger becomes a vanguard with `Piercing Sting`.
- Tier 4 Scorpion line is adaptation-heavy: `jaw` has three active abilities
  (`Adaptation: Attack`, `Defense`, `Speed`). Hive also has the extra
  `lava_larva` unit with `Blow Up` and `Fiery Embrace`, used by Hive Offspring
  laws.
- Tier 5 Reaver line has high damage variance and hunting pressure through
  `Apex Predator`, `Rapid Assault`, and upgrade-specific terror or blessing.
- Tier 6 Waurms line uses blink, corpse eating, stink, and eater AI. Pyroboros
  becomes a ranged area duelist instead of the melee eater pattern.
- Tier 7 Hive Queen line has soul assimilation and agenda mechanics. Hive
  Mother is the protector/top-end control variant with three actives; Hive
  Huntress is the faster/damaging vanguard variant.

Hero pattern:

- Hive might heroes use 4/0/2/1; magic heroes use 1/0/4/2. Defence is
  intentionally absent in both templates.
- Specializations are aggressive or tempo-oriented: Shooter, Reave Away,
  Waurmification, Intimidating Strike, Scavenger, Chessmaster, Wingflap,
  Here and There, Primal Weaving, and Flea Bites.
- Some faction-skill specialists start with `skill_faction_demons:2`, notably
  Tavi / Proliferation.

Buildings and laws:

- Unique sections include `heroBonusBanks` / `Build_Beelzebubs_Hand`,
  `rebirthShrines` / `Build_Rebirth_Of_Shrine`, and grail
  `Build_Eternal_Flame`.
- Laws compress progression and growth: `Laws of the Hive` reduces law-line
  unlock costs, `Hive Integration` and `Hive Reception` grant broad offence
  and defence, `Hive Offsprings I/II/III` target `lava_larva`, `Evolve,
  Adapt, Overcome` discounts upgrades, `Natural Selection` affects upgraded
  barrack hiring, and `Prosper and Flourish` increases units from barracks.

Balance lesson: Hive can be explosive because it is deliberately vulnerable
and identity-locked. If a custom faction borrows Hive aggression, it should
also accept a visible defensive, economy, or reliability weakness.

### Schism / Unfrozen

Source examples:

- Faction row: `DB/fractions/6_unfrozen.json`.
- Units: `DB/units/units_logics/unfrozen/*.json` and
  `DB/units/units_views/unfrozen/*_v.json`.
- Heroes: `DB/heroes/unfrozen/unfrozen_hero_*.json`.
- Specializations: `DB/heroes_specializations/specializations_unfrozen.json`.
- City: `DB/objects_logic/cities/unfrozen_city.json`.
- Laws: `DB/fractions_laws/fractions_laws_table_unfrozen.json`.

Identity: denial, summoning, displacement, cold control, and faction energy.
Schism has moderate growth, many active abilities, and a mercury-heavy city
economy.

Unit pattern:

- Tier 1 Ra'Shoth line already has active summoning rites. The standard upgrade
  becomes a ranged flyer, while the alternate becomes a sweeping melee flyer.
- Tier 2 Cultist line uses reach and Abyss gaze abilities. Binder adds
  `Abyssal Tendril`; Votary splits into Sluggishness and Slow gaze effects.
- Tier 3 Aga'Shoth Rider line has `Plow Through`, `Piercing Cold`, and icy
  actives. Alternate adds `Aga'Shoth's Help`.
- Tier 4 Shoth flyer line is mobile and frost-themed. Upgrades add `Double
  Strike`, faster movement, `Black Ice Shard`, or upgraded summoning rites.
- Tier 5 Concubus line is ranged denial. It carries `Earn Your Magic, Dear`;
  Mistress adds `Earn Your Abilities, Dear`, `Hourglass`, and Handcuffs, while
  Bewitcher adds passivity control.
- Tier 6 Arbitrator line is ranged command/control. It has `Paradoxical Shots`
  and `Power of the Abyss`; upgrades add reposition, fear, storm, switch-place,
  or frozen-page effects.
- Tier 7 Abyssal Envoy line is a high-value melee controller. It has Absolute
  Resistance, summoning rites, Will of the Abyss, and upgrade control abilities
  such as `Moment of Insanity` or `Control Mind`.

Hero pattern:

- Schism might heroes use 3/2/1/1 and magic heroes use 1/1/3/2.
- Its specialization table combines standard templates with faction-specific
  energy and summon identities: True Believer uses `energyValuesSet` for
  `unfrozen`, Everchanging Essence replaces multiple Astral Summon spells,
  and Alchemist produces mercury.
- Line specialists cover Cultists, Aga'Shoth Riders, Concubus, Ra'Shoth, and
  Shoth flyers.

Buildings and laws:

- Unique sections include `heroBonusBanks` / `Build_Endless_Library`,
  `portalSummonings` / `Build_Portal_Summoning`, and grail
  `Build_Frigid_Firmament`.
- Laws emphasize denial and scaling: `Generational Wisdom` grants experience
  bonus, `Frozen Homeland` grants broad unit offence/defence, `Mind Freeze`
  reduces enemy energy per round in battle, `The Abyss Stares Back` restores
  Unfrozen faction energy, `The World is Ours` treats all land as native, and
  `Absolute Zero` increases enemy magic cooldowns in battle.

Balance lesson: Schism shows how to build a control faction without making
every unit a hard lock. Its control effects are distributed across unit tiers,
laws, hero specializations, and buildings; no single row owns the whole denial
identity.

## Economy, Growth, and Power-Curve Observations

Native factions use three overlapping curves: creature cost, weekly growth,
and squad value.

- Tier costs and growth are not uniform by faction. For example, Grove tier-1
  Fauns cost 105 gold and grow 12/week, while Necropolis Skeletons cost 35
  gold and grow 30/week. The Skeleton line is allowed to be cheap and numerous
  because its base stat line is only 6 hp, 4/1, 1-3 damage.
- Tier-7 growth is usually 1/week, but Necropolis gets 2/week Vampires. That is
  compensated by lower tier-7 squad values than the most elite dragons or
  phoenixes: Vampire Lord / Scholar are 3259, while Black Dragon / Ashen Dragon
  are 8009 and Phoenix upgrades are 7594.
- Upgrade costs are standardized around dust: tier upgrade buildings use dust
  10/20/30/40/50/75/100 across tiers, but faction-specific resources differ.
- Faction rare-resource identity is explicit in fraction rows and city costs:
  Temple and Dungeon use gemstones, Grove and Hive use crystals, Necropolis and
  Schism use mercury.
- Main buildings, walls, markets, and common economy buildings preserve shared
  Olden Era infrastructure. Faction identity comes from unit lines, unique
  sections, laws, and selected cost pressures rather than rewriting every
  common building.
- Early game is shaped by the first three hire buildings being constructed on
  start for many factions, plus hero start squads. Line-specialist heroes often
  start with repeated copies of their specialty unit instead of the default
  mixed package.
- Late game is gated through both unit cost and building chain costs. Dungeon
  Black Dragon is a huge power cap: base Black Dragon building costs include
  17,500 gold and 20 gemstones; upgrade adds 22,500 gold, 25 gemstones, and
  100 dust. Grove Phoenix and Schism Abyssal lines use similar rare-resource
  gates.

Design rule: economy is part of unit balance. If a custom unit has a premium
ability budget, tune its weekly growth, building cost, rare-resource pressure,
or hero/law support downward. Do not balance only by per-unit gold cost.

## Unit Role and Ability-Budget Rules

Native unit lines follow a consistent budget grammar.

Base unit rules:

- A base unit normally establishes exactly one core role: melee, reach,
  ranged, flyer, tank, support, or control.
- Base units may have one active ability if that ability is core to the
  identity. Examples: Crossbowman has `Fine Bolts`, Griffin has `Valiant Cry`,
  Wight has none until upgrade, and Grove elemental units have `Awaken I`.
- Base units can carry a passive package when the role requires it, but that
  package is usually narrow. Example: Hive Parasite has Long Reach plus
  `Topple the Strong!`; Dungeon Assassin has `Blink` plus `Weak Spot`.

Upgrade rules:

- The standard and alternate upgrades usually split identity rather than stack
  everything. One path tends to be faster/offensive/tempo; the other tends to
  be tougher/control/support.
- Upgrades often add exactly one major card or improve an existing passive.
  Examples: Skeleton Archer changes attack type; Temple Griffin improves
  Alert; Medusa Sculptor adds Petrification; Wraith adds Howl; Sun's Aegis
  trades into defence rather than adding another attack.
- High-tier upgrades may carry two or three actives, but only when growth is
  low and cost is high. Examples: Thunder Qilin, Hive Mother, Abyssal Overseer,
  and Rift Arbitrator.

Attack rules:

- Ranged units normally include a melee alternative and counterattack row with
  a reduced `statDmgMult` around 0.5 unless a passive such as `Duelist` or a
  special role changes that expectation.
- Melee units with area, sweeping, double strike, blink, flying, or control
  generally pay by losing ranged flexibility or by having lower growth.
- Reach is treated as its own role. Graverobbers, Cultists, Parasites, Druid
  lines, and Vampire Scholar use reach to occupy a middle ground between melee
  and shooter.

Ability-budget constraints:

- A low-tier unit with multiple actives is exceptional and must be central to
  faction identity. Hive Scorpion has three Adaptation actives at tier 4, not
  tier 1. Schism has many early active rites, but their effects are faction
  identity and are balanced by economy/resource gates.
- Passive names are not decoration. When a passive is present in UnitView it
  usually maps to a real logic-side mechanic: resistances, modifiers, extra
  strikes, immunity, blink, flying, area, drain, energy, or faction tags.
- Do not invent display-only ability cards. Logic rows and view rows must stay
  aligned: `defaultAttacks`, `alternativeAttacks`, `counterAttacks`, and
  `abilities` are paired between logic and view files.

## Hero and Specialization Balance Patterns

Roster structure:

- Each native faction has 18 heroes: 9 might and 9 magic.
- Every hero starts with the faction skill, usually at level 1. A small number
  of identity heroes start with faction skill level 2, such as Temple True Lord,
  Necropolis Undead Legion, Hive Proliferation, Grove Hksmilla's Step, and
  Schism Coldblood Siblings / True Believer.
- Every hero has one non-faction starting skill except those faction-skill-2
  cases.
- Might and magic templates are faction-specific. Do not reuse one global
  stat template:
  - Temple: might 2/3/1/1, magic 1/1/2/3.
  - Necropolis: might 3/1/1/2, magic 1/0/2/4.
  - Dungeon: might 2/2/2/1, magic 0/2/2/3.
  - Grove: might 2/1/2/2, magic 1/2/2/2.
  - Hive: might 4/0/2/1, magic 1/0/4/2.
  - Schism: might 3/2/1/1, magic 1/1/3/2.

Specialization families:

- Map/economy specialists: Wayfarer, Pathfinder, Wealthy, Gem Seeker,
  Alchemist, Charming Shine.
- Unit-line specialists: base unit growth plus speed, initiative, hp percent,
  and level-scaling offence/defence over all three variants.
- Faction-skill specialists: battle subskill bonuses or faction-skill level 2.
- Magic-school specialists: school counters/unlocks and spell replacements,
  usually with `spellPowerSidSet` or `magicCostSidSet` scaling.
- Global combat stat specialists: outgoing damage, incoming damage, luck,
  morale, magic attack, resistance, tactics.

Native specialization safety rules:

- A specialization usually has one headline identity plus baseline hero battle
  ability access and magic-school progression rows. The headline should be easy
  to name and easy to inspect in JSON.
- If a hero specializes in a unit line, the source data names the exact three
  receiver ids. Do not infer upgrade ids dynamically when source data can
  state them.
- Spell replacement specialties should replace a specific spell with a
  specific special spell id, then scale that special id. Do not simulate this
  with loose text or generic spell-power buffs.
- Economy specializations have explicit production and percent modifier rows.
  Example: Temple Gem Seeker grants gemstones with `sideRes`, then marks the
  hero resource percent set.

### Native Hero Roster Appendix

Names below are localized names from `Lang/english/texts/heroInfo.json`,
normalized to ASCII punctuation where needed. Source rows are the matching
hero files and specialization files listed in the source inventory.

Temple / Human:

- `human_hero_1` Ister: Wayfarer, might, `skill_logistic`.
- `human_hero_2` Leon Sticky-Fingers: Pathfinder, might, `skill_scouting`.
- `human_hero_3` John Johnson: Salt of the Earth, Swordsman line, might,
  `skill_protection`.
- `human_hero_4` Kestrel: Jaeger, Crossbowman line, might, `skill_assault`.
- `human_hero_5` Aeos the Exalted: Rousing Presence, might,
  `skill_leadership`.
- `human_hero_6` Heretic Avis: Gem Seeker, might, `skill_trainer`.
- `human_hero_7` Keandra: Jouster, Cavalry line, might, `skill_formation`.
- `human_hero_8` Lord Edgar: True Lord, faction skill level 2, might.
- `human_hero_9` Old Lord Mandall: Heroic Smite, might,
  `skill_battle_artistry`.
- `human_hero_10` Merry Elias: Spiritual Vigor, magic, `skill_diplomacy`.
- `human_hero_11` Pip: Wish to Learn, magic, `skill_enlightenment`.
- `human_hero_12` Zenith: Weaving the Light, Lightweaver line, magic,
  `skill_mastery`.
- `human_hero_13` Lia the Untethered One: Radiating Knowledge, magic,
  `skill_magic_day`.
- `human_hero_14` Julius: Compassionate Healer, magic, `skill_resistance`.
- `human_hero_15` Vesper: Blessing, magic, `skill_magic_day`.
- `human_hero_16` Anastasia the Meek: Hymn to Arina, magic, `skill_wisdom`.
- `human_hero_17` Nadir: Heart of Hearts, magic, `skill_magic_night`.
- `human_hero_18` Clarissa: Wealthy, magic, `skill_economy`.

Necropolis / Undead:

- `necro_hero_1` Bulwark: Built Different, might, `skill_protection`.
- `necro_hero_2` King-of-Kings: Charismatic, might, `skill_diplomacy`.
- `necro_hero_3` Onkos: Perfect Puppets, Skeleton line, might,
  `skill_assault`.
- `necro_hero_4` Kel'Ghul: Dreadful War, Dread Knight line, might,
  `skill_tactics`.
- `necro_hero_5` Natalida: Part of a Pack, Undead Pet line, might,
  `skill_scouting`.
- `necro_hero_6` Artorius Veritas: Drive 'em Crazy, might,
  `skill_resistance`.
- `necro_hero_7` Marl: Languid Soil, might, `skill_logistic`.
- `necro_hero_8` Tarius: Undead Legion, faction skill level 2, might.
- `necro_hero_9` Zam: Alchemist, might, `skill_formation`.
- `necro_hero_10` Mag: Arcane Dominion, magic, `skill_magic_space`.
- `necro_hero_11` Adahn: Amnesiac, Wight line, magic, `skill_trainer`.
- `necro_hero_12` Ethric: Tomb-bound Will, Lich line, magic,
  `skill_mastery`.
- `necro_hero_13` Guildmaster Klastor: Bones Guild, Graverobber line, magic,
  `skill_luck`.
- `necro_hero_14` Shadespinner Oona: Shadowmastery, magic,
  `skill_magic_night`.
- `necro_hero_15` Laura: Moldering, magic, `skill_sorcery`.
- `necro_hero_16` Lord Rufus: Wistful Nostalgia, magic, `skill_wisdom`.
- `necro_hero_17` Funerella: Undead Legion, faction skill level 2, magic.
- `necro_hero_18` Milossa the Golden: Wealthy, magic, `skill_battlemage`.

Dungeon:

- `dungeon_hero_1` Enatee: Slithering Menace, Medusa line, might,
  `skill_protection`.
- `dungeon_hero_2` Tellaris the Betrayed: With One Eye Open, might,
  `skill_formation`.
- `dungeon_hero_3` Stinger: Venomous Strike, might, `skill_battle_artistry`.
- `dungeon_hero_4` Kieran: The Blind Folk, Troglodyte line, might,
  `skill_tactics`.
- `dungeon_hero_5` Mouaren: Spy, Infiltrator line, might, `skill_scouting`.
- `dungeon_hero_6` Devir, son of Devir: Balthazar's Lair, Minotaur line,
  might, `skill_leadership`.
- `dungeon_hero_7` Creta, daughter of Navarr: Gem Seeker, might,
  `skill_economy`.
- `dungeon_hero_8` Rhea: Four-Leaf Horseshoe, might, `skill_luck`.
- `dungeon_hero_9` Gleard the Grey: Arcane Dominion, might,
  `skill_magic_space`.
- `dungeon_hero_10` Kelarr, son of Navarr: Wish to Learn, magic,
  `skill_enlightenment`.
- `dungeon_hero_11` Zakron the Great: Spellweaver, magic, `skill_sorcery`.
- `dungeon_hero_12` Sister Deira: Mask of the Sun, magic, `skill_wisdom`.
- `dungeon_hero_13` Motley: Danse Macabre, Onyx Dancer line, magic,
  `skill_luck`.
- `dungeon_hero_14` Ylwari: Charismatic, magic, `skill_diplomacy`.
- `dungeon_hero_15` Glastor: Wealthy, magic, `skill_economy`.
- `dungeon_hero_16` Typhona: Alvarian Hydra, Hydra line, faction skill level 2,
  magic.
- `dungeon_hero_17` Sunny Rauktol: Radiating Knowledge, magic,
  `skill_magic_day`.
- `dungeon_hero_18` Lodos: Shadowmastery, magic, `skill_magic_night`.

Grove / Nature:

- `nature_hero_1` Eith: Pathfinder, might, `skill_scouting`.
- `nature_hero_2` Gorel Spearhead: Shooter, might, `skill_assault`.
- `nature_hero_3` Gingertail: Faunsong, Faun line, might, `skill_formation`.
- `nature_hero_4` Old Pilgrim: Natural Selection, might, `skill_battlemage`.
- `nature_hero_5` Octavia: Four-Leaf Horseshoe, might, `skill_luck`.
- `nature_hero_6` Mreowa: Charming Shine, might, `skill_sorcery`.
- `nature_hero_7` Faleor: Hksmilla's Step, faction skill level 2, might.
- `nature_hero_8` Alluring Sh'a: Charismatic, might, `skill_diplomacy`.
- `nature_hero_9` Aunt Daliar: Wish to Learn, might, `skill_enlightenment`.
- `nature_hero_10` Vatawna: Spiritual Vigor, magic, `skill_mastery`.
- `nature_hero_11` Elder Tss'kish: Oldest Known Tree, Herbomancer line,
  magic, `skill_wisdom`.
- `nature_hero_12` Aeliniel: Tempered Embers, magic, `skill_magic_primal`.
- `nature_hero_13` Glacia: Ice Bolt, magic, `skill_magic_primal`.
- `nature_hero_14` Vim: Rock It up!, magic, `skill_magic_primal`.
- `nature_hero_15` Halon: Thunder and Lightning, magic,
  `skill_magic_primal`.
- `nature_hero_16` Echolily: Murmuring Copy, magic, `skill_magic_space`.
- `nature_hero_17` Sullie: Murmurwood Native, magic, `skill_summoner`.
- `nature_hero_18` The Minstrel: Wandering Musician, magic, `skill_sorcery`.

Hive / Demon:

- `demon_hero_1` Niev: Shooter, might, `skill_assault`.
- `demon_hero_2` Maelstrom: Reave Away, Reaver line, might,
  `skill_enlightenment`.
- `demon_hero_3` Nor: Wish to Learn, might, `skill_formation`.
- `demon_hero_4` Zoran, the Self-Founded: Waurmification, Waurms line, might,
  `skill_magic_night`.
- `demon_hero_5` Curson, Duke of Rage: Intimidating Strike, might,
  `skill_battle_artistry`.
- `demon_hero_6` Tavi: Proliferation, faction skill level 2, might.
- `demon_hero_7` Lo: Scavenger, Locust line, might, `skill_protection`.
- `demon_hero_8` Goldentongue: Rousing Presence, might, `skill_leadership`.
- `demon_hero_9` Abigor, Duke of Battle: Chessmaster, might, `skill_tactics`.
- `demon_hero_10` Fleu: Wayfarer, magic, `skill_logistic`.
- `demon_hero_11` Xirr: Resistant to Elements, magic, `skill_resistance`.
- `demon_hero_12` Bathym, Duke of Jewels: Charming Shine, magic,
  `skill_economy`.
- `demon_hero_13` Leira: Stinging, Hornet line, magic, `skill_battlemage`.
- `demon_hero_14` Groo: Son of All Mothers, Hive Queen line, magic,
  `skill_mastery`.
- `demon_hero_15` Mila: Wingflap, magic, `skill_magic_day`.
- `demon_hero_16` Oriax: Here and There, magic, `skill_summoner`.
- `demon_hero_17` Khariseth: Primal Weaving, magic, `skill_magic_primal`.
- `demon_hero_18` Pauper: Flea Bites, magic, `skill_battlemage`.

Schism / Unfrozen:

- `unfrozen_hero_1` Nihil: Wayfarer, might, `skill_logistic`.
- `unfrozen_hero_2` Blackhorn: Spellweaver, might, `skill_sorcery`.
- `unfrozen_hero_3` Matastala the White: Chessmaster, might,
  `skill_tactics`.
- `unfrozen_hero_4` Janhei: Roguish, Cultist line, might, `skill_mastery`.
- `unfrozen_hero_5` Mara Mat'ha: Coldblood Siblings, Aga'Shoth Rider line,
  faction skill level 2, might.
- `unfrozen_hero_6` The Iron Master: Leash of Chains, Concubus line, might,
  `skill_resistance`.
- `unfrozen_hero_7` Wal'kha: Primal Weaving, might, `skill_magic_primal`.
- `unfrozen_hero_8` Changeling Urgo: Everchanging Essence, might,
  `skill_summoner`.
- `unfrozen_hero_9` Martyr Tho: Alchemist, might, `skill_magic_day`.
- `unfrozen_hero_10` Grellekh the Betrayer: Fighter, magic, `skill_assault`.
- `unfrozen_hero_11` Icequeen Hel'Ghat: Heart of Ice, magic,
  `skill_protection`.
- `unfrozen_hero_12` Kwinri: Low Summoning, Ra'Shoth line, magic,
  `skill_trainer`.
- `unfrozen_hero_13` The Eye Collective: Rift's Envoy, Shoth flyer line,
  magic, `skill_summoner`.
- `unfrozen_hero_14` Tolketh: Stellar Dilation, magic, `skill_logistic`.
- `unfrozen_hero_15` Ulkuth: Pathfinder, magic, `skill_scouting`.
- `unfrozen_hero_16` Ra'Davok: Magic Fortress, magic, `skill_magic_space`.
- `unfrozen_hero_17` Sister Keiri: Mask of the Moon, magic,
  `skill_magic_night`.
- `unfrozen_hero_18` Dhuvri: True Believer, faction skill level 2, magic.

## Building and Law Constraints

City schema:

- Buildings are section-shaped, not just a flat list. Native sections include
  shared infrastructure plus faction-specific sections such as `manaFountains`,
  `unitsConverters`, `artifactChangers`, `myceliumRoots`, `rebirthShrines`,
  and `portalSummonings`.
- Hire buildings bind their unit line through `unitsHire.units[*].sids`, not
  only through names or descriptions.
- Costs and prerequisites live under `parametersPerLevel`. Do not rely on
  display text when balancing city progression.
- Common infrastructure should stay common unless a design intentionally
  changes global economy. The native factions mostly express uniqueness through
  extra sections and laws.

Law schema:

- Faction rows define law layout and unlock thresholds in
  `fractionLawsLines`. Native unlock counts use common gates such as 0, 5, 15,
  and 30, then later high-tier gates.
- Law table rows define actual effects in `parametersPerLevel`.
- Common law types include `sideRes`, `sideOneTimeAddRes`, `heroStat`,
  `unitStat`, `cityUnitsIncrement`, `battleSubskillBonus`, `sideStat`,
  `constructionDiscount`, `unitHiringDiscount`, and faction-specific mechanics.
- Law tiers mix broad economy with faction mechanics. A law line should not be
  all economy, all unit stats, or all bespoke mechanics.

Faction-specific law constraints:

- Temple: buff duration, training stats, construction limit, focus/energy.
- Necropolis: necromancy, death conversion, hiring discount, magic absorption.
- Dungeon: scouting/information, market advantage, construction discounts,
  dragon/magic resistance.
- Grove: magic guild scaling, nature map bonuses, all-barrack growth, escape
  denial.
- Hive: law progression compression, upgrade/hiring efficiency, larva offspring
  buffs, hivemind stat integration.
- Schism: portal summoning, energy denial/restore, native-land override,
  cooldown penalties, mercury economy.

Design rule: a custom faction law table should preserve the native rhythm:
early resource access and unit identity, midgame stats/economy, late faction
mechanics. Do not put the entire faction mechanic in the first law row.

## Balance Anti-Patterns to Avoid in Custom Factions

- Do not treat HoMM3 custom faction plans as vanilla evidence. Use the live
  native rows above when deriving Olden Era balance standards.
- Do not use fallback mechanics when source data is discoverable. If a unit
  card, hero specialization, law, or building effect is unclear, inspect the
  logic row and localization row directly.
- Do not make display-only abilities. A UnitView card must correspond to logic
  behavior, and logic arrays must have matching view arrays.
- Do not give a faction Grove ability density, Necropolis growth, Dungeon
  immunities, and Hive tempo at the same time. Native factions specialize by
  spending budget elsewhere.
- Do not clone a hero roster with generic stats. Native might/magic stat
  templates are faction identity.
- Do not create unit specialists without exact receiver lists for base,
  standard upgrade, and alternate upgrade.
- Do not balance a unit only by gold cost. Weekly growth, building cost,
  rare-resource pressure, dust upgrade cost, hero starting stacks, and law
  support are all part of the same budget.
- Do not stack multiple hard-control effects on a high-growth low-tier unit
  unless the faction's entire economy and hero/law support pay for it.
- Do not make faction laws all bespoke. Native law tables interleave common
  economy and stat laws with unique faction mechanics.
- Do not rewrite common city infrastructure to express faction flavor when a
  unique city section or law would do it more safely.

## Concrete Design Rules for Later Custom Synthesis

Use these as hard checks when synthesizing custom units, heroes, buildings, or
law rows.

1. Pick the faction's two hero stat templates before writing individual heroes.
   A 9/9 might/magic roster should follow those templates unless a specific
   hero has live-source precedent to differ.

2. Build seven unit lines first, then decide the two upgrade branches for each
   line. Each branch should answer a different tactical question: speed vs
   durability, control vs damage, support vs independence, range vs melee.

3. Assign weekly growth before tuning abilities. Use native references:
   low-body elite Grove style starts near 12/8/6/4/3/2/1; mass Necropolis style
   can be 30/16/13/10/5/3/2 only if stats and per-unit ceiling are lower.

4. Keep base units readable. One core passive package and zero or one active
   ability is the normal budget. Multiple actives become more acceptable at
   tiers 5-7 or on a faction-defining mid-tier unit with lower growth.

5. Treat rare-resource identity as faction identity. Pick one primary rare
   resource for high-tier unit costs and city pressure, then keep it consistent
   with the faction row `resourceName`.

6. For ranged units, implement all three combat lanes: ranged default attack,
   melee alternative, and counterattack. Do not omit the reduced melee behavior
   unless the unit has an explicit premium passive that pays for it.

7. For line-specialist heroes, use the native template: base-line growth,
   speed +1, initiative +1, hp percent, level-scaling friendly offence/defence,
   and sometimes enemy penalties for the same receiver line. State all three
   receiver ids.

8. For spell specialists, use explicit `heroMagicReplace` rows and scale the
   replacement spell id. Do not implement spell specialties as text-only
   descriptions or broad hidden buffs.

9. Give each faction at least one economy/resource specialist, one map/utility
   or scouting specialist, several unit-line specialists, several magic or
   faction-skill specialists, and at least one broad combat-stat specialist.

10. Preserve common city sections unless there is a design reason to add a
   faction-specific section. Native uniqueness comes from sections such as
   Well of Souls, Skeleton Converter, Lyceum, Mycelium Roots, Rebirth Shrine,
   and Portal Summoning.

11. Law tables should follow native pacing: early resource and core unit laws,
   midgame hero/unit/economy laws, late faction mechanics and global modifiers.

12. Verify every design claim against the live packed archive before
   implementation. The live `Core.zip` is the source of truth for vanilla
   balance; repo docs are orientation only.
