# Olden Era Vanilla Faction Law Uniqueness Audit

Date: 2026-05-21

Purpose: identify vanilla Olden Era faction laws that should not be copied into a new/custom faction law tree without deliberate redesign. This audit uses the current local Steam/playtest `Core.zip` law tables under `DB/fractions_laws/*.json` plus English law text from `Lang/english/texts/factionLaws.json`.

Implementation note, 2026-05-21: `tools/release_port/apply_release_core_overlay.py` now uses this rule set through `make_release_custom_laws_doc()` / `custom_law_lang_rows()` for Castle, Conflux, Cove, Dungeon, Fortress, Inferno, Necropolis, and Rampart. Those trees keep donor law-line counts/layout compatibility, but replace donor unit rows, faction-skill resource rows, and placeholder "Command N" localization with manifest-owned creature bonuses and faction-appropriate laws.

Resource note, 2026-05-21: custom law-tree "Mining: <resource>" rows are faction-specific and should target the non-gold resource pressure of the faction's tier-7 line. Castle uses Gems, Conflux/Cove/Inferno/Necropolis use Mercury, Dungeon/Fortress sulfur pressure is folded to Olden Era Mercury, and Rampart uses Crystals to match the generated Diamond Dragon / Resource Silo pressure. Do not confuse this row with the three generic one-time Resource Riches rows; those intentionally stay broad Gold/Wood/Ore scaffold laws.

Icon note, 2026-05-22: generated custom law rows should not default every `icon` to `fraction_law_homm3_<faction>_<N>_icon` unless matching PNGs are shipped. Unit-line laws use the target `h3_*` unit SID so the runtime law view can render the unit portrait; other rows inherit the donor row's icon. A missing custom law-icon PNG must not silently become the faction banner for every law.

Layout note, 2026-05-22: custom unit-law tiers must follow the donor faction's vanilla creature-law slots, not a single global index list. Human uses slots `4,10,11,17,23,24,30`; Nature uses `5,6,10,16,22,23,27`; Dungeon direct creature laws use `4,10,11,18,19,25,31`; Undead uses `4,5,10,11,18,19,23`. Otherwise a Nature-donor faction can put tier-7 creature laws on a lower visible branch, or attach the wrong unit portrait to the wrong law position.

## Rule Of Thumb

- **Safe scaffold laws** are economy/stat/churn rows whose text and parameters can be renamed cleanly: tax income, resource riches, flat hero attributes, generic unit damage/speed/initiative, construction discounts, astrology points, broad native-terrain bonuses, and generic external-dwelling growth.
- **Faction-locked laws** name a vanilla faction/class/unit, target a faction-specific skill resource, depend on a native faction mechanic, or reference lore that would look wrong outside that faction.
- **Do not fallback-copy faction-locked rows.** If a future faction lacks an equivalent mechanic, omit the row, replace it with a generic scaffold law, or mark explicit design debt. Silent donor law behavior is the same trap as silent donor unit abilities.

## Human / Temple

Clearly faction-locked:

- `fraction_law_human_4` Elite Swordsmen, `10` Elite Crossbowmen, `11` Elite Griffins, `17` Elite Lightweavers, `23` Elite Cavalry, `24` Elite Inquisitors, `30` Elite Angels: direct Temple unit growth/stat laws.
- `fraction_law_human_18` Training: Melee Combat, `19` Training: Range Combat, `20` Training: Range Combat: mechanics/text double the effect for non-Temple friendly creatures, so these are not generic combat training laws as-is.
- `fraction_law_human_27` Power of Faith: explicitly says Temple heroes can learn any spell tier.
- `fraction_law_human_31` Focus is the Key: explicitly grants Temple creatures Focus Points.
- `fraction_law_human_33` Inquisition Crusade: Temple-flavored anti-summon law; mechanically portable only after renaming and checking whether the target faction wants anti-summon identity.

Theme-specific but reusable with rewrite:

- `fraction_law_human_15` Sun's Grace: Daylight spell school bonus can be remapped to another faction's school.
- `fraction_law_human_26` Hero's Blessing: stat conversion is mechanically generic, but Temple blessing flavor should be replaced.

## Undead / Necropolis

Clearly faction-locked:

- `fraction_law_undead_2`, `7`, `15`, `21`, `27` Animate Dead I-V: all target Necromancy Power or maximum Necromantic Energy.
- `fraction_law_undead_4` Elite Skeletons, `5` Elite Wights, `10` Elite Undead Pets, `11` Elite Graverobbers, `18` Elite Liches, `19` Elite Dread Knights, `23` Elite Vampires: direct Necropolis unit laws.
- `fraction_law_undead_17` Bloodthirst: depends on vampirism identity/mechanics.
- `fraction_law_undead_20` Terra Mortis: explicitly says Necropolis heroes always battle on native terrain.
- `fraction_law_undead_22` Free Death: explicitly discounts Necropolis creatures.
- `fraction_law_undead_31` Death's Presence: explicitly distinguishes enemy non-Necropolis creatures and your non-Necropolis creatures.

Theme-specific but reusable with rewrite:

- `fraction_law_undead_8` Laws of the Immortals, `9` Death Equalizes All, `12` Gifts of the Afterlife, `24` Return to the Soil, `25` Beyond the Final Rest, `26` Black Death, `29` Terror and Dread, `30` Morituri te Salutant: the effects are portable in isolation, but the names/descriptions are death/Necropolis-coded.
- `fraction_law_undead_32` Moon's Grace: Nightshade spell school bonus can be remapped to another faction's school.
- `fraction_law_undead_33` has missing English localization in the current loose text file. Treat it as audit debt before using it as a donor row.

## Dungeon

Clearly faction-locked:

- `fraction_law_dungeon_4` Elite Troglodytes, `10` Elite Infiltrators, `11` Elite Dancers, `18` Elite Minotaurs, `19` Elite Medusae, `25` Elite Hydras, `31` Elite Cave Dragons: direct Dungeon unit laws.
- Those same unit laws also reference "Fighting Style", tying them to Dungeon/Triumvirate unit mechanics rather than generic stat buffs.
- `fraction_law_dungeon_22` Triumvirate's Agents: explicitly targets Dungeon heroes.
- `fraction_law_dungeon_32` Dungeon Masters VII: generic tier-7 growth mechanically, but the "Dungeon Masters" law family is faction-named and should be renamed/rethemed if reused.

Theme-specific but reusable with rewrite:

- `fraction_law_dungeon_5` Dragon Scales: magic damage reduction is portable, but dragon flavor is not universal.
- `fraction_law_dungeon_6`, `12`, `13`, `21`, `26`, `27`, `32` Dungeon Masters I-VII: tier growth scaffolding is useful for custom factions, but every name/description should be faction-neutralized.
- `fraction_law_dungeon_7` Or No Ore?, `8` Jadame Maps, `16` Peoples of Jadame: lore-coded to Jadame/Dungeon context.
- `fraction_law_dungeon_28` Magical Education, `29` Saturation, `33` Arcane Knowledge: mechanics are broadly reusable, but check the target faction's magic/focus identity first.

## Demon / Hive

Clearly faction-locked:

- `fraction_law_demon_2` Laws of the Hive, `3` Mana Devour, `4` Prey Appraisal, `9` Adapt and Overcome, `11` Beelzebub's Gaze, `14` Hive Magic: text explicitly names Hive heroes/buildings/creatures or Hive identity.
- `fraction_law_demon_19` Volatile Larvae, `26` Brood Assault, `30` Brood Provocation: depend on summoned lava larvae.
- `fraction_law_demon_20` Elite Parasites, `21` Elite Locusts, `22` Elite Hornets, `23` Elite Scorpions, `24` Elite Reavers, `25` Elite Worms, `27` Elite Hive Queens: direct Hive unit laws.

Theme-specific but reusable with rewrite:

- `fraction_law_demon_7` Focus Reserves, `8` Ancient Power, `10` Natural Selection, `13` Prosper and Flourish, `16` Predatory Instincts, `17` Hardened Carapaces, `18` Great Conquest, `28` Infernal Rage, `29` No Compassion: mechanically portable, but names/descriptions skew predatory/infernal/Hive.

## Nature / Grove

Clearly faction-locked:

- `fraction_law_nature_5` Elite Fauns, `6` Elite Hoplets, `10` Elite Iriyads, `16` Elite Aqualotls, `22` Elite Mancers, `23` Elite Qilins, `27` Elite Phoenixes, `28` Fairy Tale: direct Grove unit laws or grouped Grove-unit bonuses.
- `fraction_law_nature_7` Children of the Wild: explicitly says Sylvan heroes.
- `fraction_law_nature_9` Woodland Resistance: explicitly disguises armies as random Sylvan units.
- `fraction_law_nature_25` Force of Nature: points to Grove-specific Heroic Strike law subskills.
- `fraction_law_nature_29` Sanctuary: explicitly discounts Grove abilities.
- `fraction_law_nature_31` Murmuring: grants Focus Charge(s) each round; portable only if the target faction has the same focus economy.

Theme-specific but reusable with rewrite:

- `fraction_law_nature_8` Save the Forests, `11` Nature's Wildness, `12` Nature's Resolve, `14` Forest Magic, `17` Veiled by the Trees, `18` The Power of the Written Word, `20` Fertile Ground, `21` Live roots, `24` Luck of the Fittest, `30` Stars Between Boughs: mostly portable effects, but names/descriptions are forest/Grove-coded.

## Unfrozen / Schism

Clearly faction-locked:

- `fraction_law_unfrozen_5` Elite Ra'Shoth, `12` Elite Cultists, `13` Elite Aga'Shoth Riders, `19` Elite Grand Shoth, `26` Elite Concubi, `27` Elite Arbitrators, `32` Elite Abyssal Envoys: direct Schism unit laws.
- `fraction_law_unfrozen_6`, `10`, `11`, `18`, `24`, `25`, `31` Unfrozen Strength I-VII: tier-scaled stat-conversion scaffold is useful, but the law family is explicitly Unfrozen and should not be copied verbatim.
- `fraction_law_unfrozen_9` Depths of Mind: explicitly says Schism heroes.
- `fraction_law_unfrozen_16` Cold Shoulder: depends on Involuntary Summons in Schism cities.
- `fraction_law_unfrozen_22` Call of the Deep: explicitly says Schism heroes and summon synergy.
- `fraction_law_unfrozen_29` The Abyss Stares Back: explicitly says Schism heroes start each day with maximum Communion level.

Theme-specific but reusable with rewrite:

- `fraction_law_unfrozen_4` Frozen Homeland, `7` Ice Power, `15` Otherworldly Magic, `20` Cold Touch, `21` Frostbite, `23` Inevitable Destruction, `28` Mind Freeze, `33` Ice Storms, `34` The World is Ours, `35` Planar Explorers, `36` Absolute Zero: mechanics are portable in places, but the names/descriptions are ice/abyss/Schism-coded.

## Practical Scaffolding Guidance

- Start custom law trees from generic patterns, not from a whole donor tree. Good reusable patterns include Tax Collectors, Resource Riches I-III, Mining, basic hero stats, one school-specific spell-level law, external dwelling growth, tier growth, construction discount, native-terrain bonus, and broad creature combat stat laws.
- For unit laws, generate target-faction unit names and receiver SIDs from the custom faction manifest. Never keep donor unit names or donor `cityUnitsIncrement` parameters.
- For faction-skill resource laws, only copy a law if the target faction has the same resource contract. Temple Focus, Necropolis Necromancy/Necromantic Energy, Dungeon Fighting Style/Focus, Hive lava larvae, Grove Focus/Grove abilities, and Schism Communion/Involuntary Summons are not interchangeable.
- If a copied law has `heroStat(..., <faction id>, ...)`, `fractionEnergyRestoreBonus(<faction>)`, native-faction text, or a `battleSubskillBonus(...)` pointing to faction-specific subskills, treat it as faction-locked until traced.
- Keep law localization and mechanic rows aligned. A generic-looking effect with faction-specific text is still not shippable for another faction.

