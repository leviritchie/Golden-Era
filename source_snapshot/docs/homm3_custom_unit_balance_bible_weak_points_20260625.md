# HoMM3 Custom Unit Balance Bible Weak Points

Status: source-validated static audit, runtime-unvalidated.

Static extraction date: 2026-06-25.

Primary comparison target: `docs/olden_era_balance_bible_20260625.md`.

Primary custom data source: `artifacts/core_overlay_work/Core.zip`, summarized into `artifacts/balance_audit_20260625/custom_vs_vanilla_unit_snapshot.json` and `artifacts/balance_audit_20260625/custom_rows_named.csv`.

Primary vanilla benchmark source: installed Golden Era `Core.zip`, as described by the balance bible.

This is a design and data audit only. It did not change source behavior, validator contracts, generated Core payload, build outputs, deployed files, or runtime state.

## Scope

The audit covers all generated `h3_` custom unit logic rows in tiers 1-7, plus the custom neutral `h3_fangarm` row. The parsed set contains 211 custom rows: ten HoMM3 custom factions with seven lines each and normal base/upgrade/alternate rows, plus one neutral row.

The review compares each custom tier against the vanilla Olden Era tier philosophy and numeric bands in the balance bible. Six tier slices were delegated to read-only subagents; Tier 7 was reviewed locally using the same generated snapshot.

The static parser reads core stats, gold cost, `squadValue`, movement/AI tags, and top-level visible rule buckets such as `passives`, `abilities`, `alternativeAttacks`, `aura`, `conditionalPassives`, and `globalPassives`. The `mechanicCount` values are comparative signals, not proof that every nested runtime effect is absent. They are still useful because the same extraction method is applied to vanilla and custom rows.

## Executive Findings

1. `squadValue` is the noisiest and most dangerous field in the generated custom roster. Many rows have values that do not match their visible stat package, cost, tier, or role. Examples include Tier 1 `Centaur Ranger` at `1366`, Tier 4 `Gore Demon` at `2250`, Tier 4 `Vampire Prince` at `3276`, Tier 5 `Pit Spawn` at `5568`, Tier 6 `Nix Praetorian` at `552`, Tier 6 `Chimera` at `326`, and Tier 7 `Arch Demon` at `1242`.
2. Alternate upgrades often fail the Olden Era sidegrade rule. Some are strict or near-strict upgrades; others are valued far below the standard branch despite being tactically richer or more expensive. This can make the recruitment UI look misleading even when visible stats are not obviously broken.
3. Mid and late tiers are broadly under-mechanized relative to the balance bible. Tier 4 should be the first engine tier, Tier 5 should be specialist power, Tier 6 should be anchors, and Tier 7 should be faction theses. Many HoMM3 rows instead remain stat blocks with `mechanicCount` around `2-4`.
4. Several high-tier lines inherit low-tier donor/scaffold rule density. Current manifest evidence shows Tier 6 `Nix` is scaffolded on `minos`, Tier 6 `Manticore` on `griffin`, Tier 6 `Efreeti` on `wasp`, and Tier 6 `Cavalier` on `sunlight_cavalry`. This helps explain why their generated rule packages do not feel like native Tier 6 anchors.
5. HoMM3 speed and initiative were copied into a game with different mobility bands. Early flyers and late capstones often exceed the vanilla Olden Era tier maxima, producing tempo spikes before the rule package has an Olden Era-style cost.

## Highest Priority Weak Points

These rows should be treated as audit blockers before fine tuning:

| Priority | Unit line | Weak point |
| --- | --- | --- |
| High | Conflux Air Elemental line | Tier 2 line is far above the tier in stats/value, while Hurricane has a very different `squadValue` despite still having premium mobility and range. |
| High | Conflux Earth/Lava Elemental line | Tier 5 base/standard are under-tier, then Lava Elemental jumps to `SV 2351` with only `650g` and a much stronger stat line. |
| High | Inferno Demon/Gore Demon line | Gore Demon jumps to `SV 2250` in Tier 4 with ordinary visible stats and thin mechanics. |
| High | Inferno Pit Spawn | `SV 5568` is Tier 7-scale while the visible row is a Tier 5 body with low mechanic density. |
| High | Necropolis Vampire Prince | Same cost and base combat line as Vampire Lord, plus speed/initiative and a blind-style active, but `SV 3276`. This is both a sidegrade and recruitment-valuation smell. |
| High | Rampart Centaur Ranger | Tier 1 alternate at `SV 1366` with ranged/melee behavior and `ai=melee_type`; clear donor/valuation anomaly. |
| High | Rampart Elf Wardancer | Tier 3 alternate has `SV 52`, below the tier minimum, despite being a meaningful melee pivot with speed/offense. |
| High | Rampart Gold Pegasus | Tier 4 alternate is the most expensive Pegasus branch but has `SV 178`, below the tier minimum. |
| High | Cove Nix Praetorian | Better combat stats than Nix Warrior in several places, `1300g`, but only `SV 552`, below Tier 6 vanilla minimum. |
| High | Dungeon Chimera | Tier 6 alternate collapses to `SV 326` with low rule density; not credible as a late-game anchor. |
| High | Inferno Efreet Sufi | Tier 6 alternate has `speed 14`, `1200g`, and Tier 6 placement, but only `SV 327` and Tier 3-style mechanics. |
| High | Tower Naga Queen/Rani | Above Tier 6 value ceiling while still being thin rule packages with no visible active/passive role pivot. |
| High | Inferno Arch Demon | Tier 7 alternate costs `5000g` with high HP/defense/speed but only `SV 1242`, below Tier 7 minimum and below many lower-tier rows. |

## Tier 1: Identity Seeds

Tier 1 vanilla design expects a readable identity and one narrow hook. The custom weak points are mostly over-broad alternates and low-tier valuation anomalies.

| Severity | Line | Weak point |
| --- | --- | --- |
| Medium | Castle Pikeman / Halberdier / Glaivier | Glaivier has the same `SV/cost` as Halberdier while adding a tankier and more exotic defensive active shape; too broad for Tier 1. |
| High | Conflux Pixie / Sprite / Faerie | Faerie reaches `SV 178`, above the full Tier 1 vanilla max, and combines flight, speed, no retaliation, all-adjacent attack, and mana transfer. |
| High | Cove Nymph / Oceanid / Nereid | Nereid reaches `SV 178` at only `45g`, with teleport, ice immunity, and healing; Oceanid also has underpriced tactical reach. |
| Medium | Dungeon Troglodyte / Infernal Troglodyte / Chthonian | Chthonian has teleport/Blink reach but lower `SV` than the base while costing more than the standard upgrade. |
| Medium | Fortress Gnoll / Marauder / Shaman | Shaman has same gold as Marauder, higher `SV`, much higher defense, and an active debuff; the lower offense may not be enough to make a sidegrade. |
| Medium | Inferno Imp / Familiar / Vermin | Vermin combines flight, no retaliation, support action, and high speed on a very low-tier row. |
| High | Necropolis Skeleton / Skeleton Warrior / Skeleton Archer | Skeleton Warrior becomes a dense stat brick for a mass unit; Skeleton Archer gains shooter utility but has lower `SV` than base Skeleton. |
| High | Rampart Centaur / Centaur Captain / Centaur Ranger | Centaur Captain exceeds Tier 1 all-row value/speed max; Centaur Ranger is an extreme `SV 1366` donor/valuation anomaly with AI-role mismatch. |
| Medium | Stronghold Goblin / Hobgoblin / Goblin Trapper | Trapper has a good identity, but costs more than Hobgoblin while carrying much lower `SV`. |
| Medium | Tower Gremlin / Master Gremlin / Gremlin Mechanic | Gremlin Mechanic has two actives at Tier 1, which is broader than the bible's one-extra-sentence upgrade rule. |

## Tier 2: First Tactical Choices

Tier 2 should introduce the first tactical verbs. Several custom rows either lack those verbs or carry too much ranged/mobility value for the band.

| Severity | Line | Weak point |
| --- | --- | --- |
| Low | Castle Archer / Marksman / Crossbowman | Base and standard damage are below the vanilla Tier 2 floor; Crossbowman fixes damage and attack, so the alternate may look too obviously better. |
| High | Conflux Air Elemental / Storm Elemental / Hurricane Elemental | Base and standard exceed Tier 2 maxes for value, cost, HP, attack, defense, and speed; Hurricane's `SV 123` does not match its premium mobility/ranged package. |
| High | Cove Crew Mate / Seaman / Swashbuckler | All three have thin tactical identity; Swashbuckler drops to `SV 87` at `150g` and does not read as a combat sidegrade. |
| Medium | Dungeon Harpy / Harpy Hag / Fury | Harpy Hag is over the Tier 2 value/speed band, while Fury costs the same but is valued below base despite an aggressive double-attack profile. |
| Medium | Fortress Lizardman / Warrior / Assassin | Ranged safety is over-budgeted; Assassin is a premium ranged row with speed and active pressure in a tier where ranged units should pay clear costs. |
| Medium | Inferno Gog / Magog / Amalek | Magog and Amalek have same broad role and same price but `SV 240` vs `123`, creating a suspicious standard/alternate split. |
| High | Necropolis Walking Dead / Zombie / Rot Zombie | Rot Zombie spikes to `SV 353` at same gold as Zombie despite low damage; severe valuation anomaly. |
| High | Rampart Dwarf / Battle Dwarf / Dwarf Battlerager | Battlerager is an upgrade below base value with no clear tactical mechanic, despite better damage/defense. |
| Medium | Stronghold Wolf Rider / Wolf Raider / Boar Rider | Both upgrades exceed the full Tier 2 value max; sidegrade is readable but base has little tactical verb beyond stats. |
| Medium | Tower Gargoyle / Obsidian Gargoyle / Elemental Gargoyle | Flyer/stun identity is clear, but rows are over-defensive and under-damaging; upgrades exceed value/speed/defense bands. |

## Tier 3: First Real Board Rules

Tier 3 should introduce local board rules, retaliation math, area pressure, or meaningful geometry. Many custom lines have high `squadValue` but low rule density.

| Severity | Line | Weak point |
| --- | --- | --- |
| High | Castle Griffin / Royal Griffin / Battle Griffin | All rows exceed full Tier 3 `SV` max, but mechanic density is only `3/3/4`; the line is valued like Tier 4 while remaining a simple flyer/retaliation piece. |
| High | Conflux Water Elemental / Ice Elemental / Frost Elemental | Frost Elemental reaches `SV 550` with no visible active and only modest mechanics; base and standard are also high for the tier. |
| High | Cove Pirate / Corsair / Sea Dog | Sea Dog is not a clean sidegrade: it carries higher attack/defense/speed and shooter quality, making it feel like a premium branch over Corsair. |
| High | Dungeon Beholder / Evil Eye / Fargazer | All rows exceed Tier 3 `SV` ceiling; Fargazer gains several stats and ranged quality, reading as a premium upgrade rather than a sidegrade. |
| Medium | Fortress Serpent Fly / Dragon Fly / Damsel Fly | Identity is good, but damage is below floor and Dragon Fly has extreme `13/13` initiative/speed. |
| High | Inferno Hell Hound / Cerberus / Fire Hound | Entire line exceeds Tier 3 value band, with high offense and low cost; base has especially low mechanics for its value. |
| High | Necropolis Wight / Wraith / Banshee | Banshee is valued near tier minimum but has premium cost, undead/regeneration package, and a damaging active. |
| High | Rampart Wood Elf / Grand Elf / Elf Wardancer | Wardancer has `SV 52` below Tier 3 minimum despite being a meaningful melee pivot; Grand Elf is slightly over value band but below defense band. |
| Medium | Stronghold Orc / Orc Chieftain / Orc Berserker | Under-statted and low damage for Tier 3; Berserker has lower `SV` than Chieftain despite better defense/speed. |
| High | Tower Stone Golem / Iron Golem / Magnetic Golem | Upgrades jump to `SV 412/460` at only `200g`, with construct/repair/Web value; strongest Tier 3 too-much-value-for-cost line. |

## Tier 4: Midgame Pivot

Tier 4 is the clearest custom-vs-bible mismatch. Vanilla Tier 4 rows have `mechanicCount` minimum `6`, median `8`; 28 of 30 custom Tier 4 rows are below that minimum. Most sit at `2-4`, even when `squadValue` is high.

| Severity | Line | Weak point |
| --- | --- | --- |
| Medium | Castle Swordsman / Crusader / Guardsman | Guardsman looks like a direct durability/damage winner unless Crusader's one passive is very strong; base is near value ceiling but has no active/passive engine. |
| Medium | Conflux Fire Elemental / Energy Elemental / Plasma Elemental | Plasma is more expensive and tactically stronger than base but has lower `SV` than both base and Energy. |
| Medium | Cove Stormbird / Ayssid / Halcyon | Halcyon costs more than Ayssid but has roughly half the `SV`; Stormbird/Ayssid are speed-overloaded. |
| Medium | Dungeon Medusa / Medusa Queen / Medusa Warrior | Medusa Warrior exceeds full Tier 4 value max, while the line's mechanic density remains low for a midgame engine. |
| Medium | Fortress Basilisk / Greater Basilisk / Flamespitter | Values are high for the tier, but both upgrades remain below vanilla Tier 4 mechanic density. |
| High | Inferno Demon / Horned Demon / Gore Demon | Gore Demon jumps to `SV 2250`, over three times the full Tier 4 max, with ordinary visible stats and only thin mechanics. |
| High | Necropolis Vampire / Vampire Lord / Vampire Prince | Vampire Prince reaches `SV 3276` at `500g`, same base combat line as Lord plus active/mobility; largest Tier 4 donor/valuation anomaly. |
| High | Rampart Pegasus / Silver Pegasus / Gold Pegasus | Gold Pegasus is most expensive and fastest/offensive branch but has `SV 178`, below Tier 4 minimum. |
| Low | Stronghold Ogre / Ogre Mage / Ogre Brute | Sidegrade is plausible, but both upgrades are under-mechanized; Mage value is HP-heavy while Brute looks cleaner tactically. |
| Medium | Tower Mage / Arch Mage / Battle Mage | Correct caster/ranged role, but valuation runs high while durability and mechanics remain thin versus vanilla Tier 4. |

## Tier 5: Specialist Power

Tier 5 should be allowed to be weird, but that weirdness needs a clear combat job. The custom tier is usually not over-mechanized; it is often under-mechanized with suspicious value inversions.

| Severity | Line | Weak point |
| --- | --- | --- |
| Medium | Castle Monk / Zealot / Priest | Ranged line reads closer to Tier 4 support: low HP, low damage, few mechanics; Priest improves durability but still has light rule density. |
| High | Conflux Earth Elemental / Magma Elemental / Lava Elemental | Base/standard are under-tier, then Lava jumps to `SV 2351` and much stronger stats at only `650g`. |
| Medium | Cove Sea Witch / Sorceress / Tidecaller | Fragile ranged/caster line with low mechanics; Tidecaller is cheaper in `SV` than Sorceress despite higher cost and more tactical surface. |
| Medium | Dungeon Minotaur / Minotaur King / Taskmaster | Serviceable bruiser stats but lacks Tier 5 mechanics; Taskmaster is more expensive/faster than King but valued far lower. |
| Low | Fortress Gorgon / Mighty Gorgon / Corrosive Gorgon | Stat budget is mostly healthy; weakness is mechanic thinness and low base/standard offense. |
| High | Inferno Pit Fiend / Pit Lord / Pit Spawn | Pit Spawn has `SV 5568`, Tier 7-scale, while stats and visible mechanics remain Tier 5-thin. |
| High | Necropolis Lich / Power Lich / Lich Master | Lich Master drops to `SV 505` at same cost as Power Lich while adding speed, active, and passives. |
| High | Rampart Dendroid Guard / Soldier / Shaman | Slow tank line has weak specialist identity; Shaman is below Tier 5 value minimum while costing `550g` and adding defense/active. |
| Medium | Stronghold Roc / Thunderbird / Shahrokh | Fast flyer line is mechanically thin; `range_type` AI tags are suspicious for the Roc family, and upgrades exceed speed band. |
| Medium | Tower Genie / Master Genie / Vizier | Caster identity is too thin; Master Genie mostly upgrades speed while retaining low HP and low mechanics. |
| Low | Neutral Fangarm | As a neutral, it need not be symmetric, but it lacks the encounter-piece identity expected from special rows. |

## Tier 6: Late-Game Anchors

Tier 6 should stabilize the board. The custom rows often have HoMM3-inspired stats but not the native anchor rule density. Several are scaffolded on lower-tier donors.

| Severity | Line | Weak point |
| --- | --- | --- |
| Medium | Castle Cavalier / Champion / Justiciar | Row package is too thin for Tier 6; upgrades only jump about `1.08x` in `SV` instead of the bible's rough `1.6x` anchor jump. Current manifest scaffolds this line on `sunlight_cavalry`. |
| Medium | Conflux Psychic Elemental / Magic Elemental / Astral Elemental | Proper Tier 6 placement, but HP/attack/defense and mechanics are too light for an anchor; Astral is priced like premium upgrade without anchor durability. |
| High | Cove Nix / Nix Warrior / Nix Praetorian | Praetorian has better combat stats than Warrior in several places but only `SV 552`; current manifest scaffolds Nix on `minos`. |
| High | Dungeon Manticore / Scorpicore / Chimera | Under-budget anchor and alternate valuation failure; Chimera collapses to `SV 326`. Current manifest scaffolds Manticore on `griffin`. |
| Medium | Fortress Wyvern / Wyvern Monarch / Paokai | HP and mechanics are below Tier 6 expectations; AI tags look ranged-adjacent for a flying melee-themed line. |
| High | Inferno Efreeti / Efreet Sultan / Efreet Sufi | Tier 6 mobility with Tier 3-style rule density; Sufi is only `SV 327` despite `speed 14`. Current manifest notes Efreeti uses the Demon `wasp` donor shell. |
| Medium | Necropolis Black Knight / Dread Knight / Dreadtaur | Closest to Tier 6 shape, but Dreadtaur drops to `SV 1530` despite same cost/HP/damage as Dread Knight and better attack plus Vulnerability. |
| Medium | Rampart Unicorn / War Unicorn / Pristine Unicorn | Priced as Tier 6 but mechanically thin; Pristine is the only clearly tactical branch. |
| High | Stronghold Cyclops / Cyclops King / Blood-Eyed Cyclops | Base/standard are under-anchor; Blood-Eyed jumps to `SV 2377` while keeping low HP, average damage, and mechanics. |
| High | Tower Naga / Naga Queen / Naga Rani | Queen/Rani exceed vanilla Tier 6 value ceiling while remaining no-active/no-passive stat packages; sidegrade is mostly damage versus defense/speed. |

## Tier 7: Capstones

Tier 7 vanilla capstones are dense faction theses. The custom Tier 7 lines mostly preserve HoMM3 fantasy names and stats but are mechanically sparse. Vanilla Tier 7 `mechanicCount` range is `7-12`; custom Tier 7 rows mostly sit at `2-6`.

| Severity | Line | Weak point |
| --- | --- | --- |
| High | Castle Angel / Archangel / Seraph | Archangel and Seraph exceed the full Tier 7 `SV` max at `8776` and run `18/18` initiative/speed, above vanilla mobility bands, while mechanic density stays `4`. |
| High | Conflux Firebird / Phoenix / Sacred Phoenix | Phoenix speed/initiative is extreme at `21/21`; Sacred Phoenix is broadly stronger than Phoenix in HP/attack/damage while staying under-mechanized. |
| Medium | Cove Sea Serpent / Haspid / Abyss Serpent | Haspid is high value and strong, while Abyss Serpent costs the same but drops to `SV 2377`; upgrade-chain valuation is not coherent. |
| High | Dungeon Red Dragon / Black Dragon / Shadow Dragon | Black Dragon exceeds Tier 7 value max; Shadow is near the ceiling; both retain low mechanic density for capstone dragons. |
| Medium | Fortress Hydra / Chaos Hydra / Ruinous Hydra | Hydra line is slow and readable, but low mechanics for a capstone. Ruinous gains speed/defense/control while value rises over Chaos despite lower HP. |
| High | Inferno Devil / Arch Devil / Arch Demon | Devil line has only `mechanicCount 2`; Arch Demon costs `5000g` with strong stats but only `SV 1242`, below Tier 7 minimum. |
| High | Necropolis Bone Dragon / Ghost Dragon / Spectral Dragon | Spectral Dragon is a near-direct combat upgrade over Ghost Dragon in attack/defense at same HP/speed and similar mechanics, with a large `SV` jump. |
| High | Rampart Green Dragon / Gold Dragon / Diamond Dragon | Gold Dragon exceeds Tier 7 value max; Diamond/Gold run high mobility and stats with only `mechanicCount 4`, so they read as stat capstones rather than Olden Era theses. |
| Medium | Stronghold Behemoth / Ancient Behemoth / Ghost Behemoth | Behemoth base is cheap and slow; Ghost Behemoth has a reasonable HP-for-speed/attack tradeoff but high value and low mechanic density. |
| Medium | Tower Giant / Titan / Colossus | Titan/Colossus are high-value ranged capstones with low mechanics; Colossus is almost strictly better than Titan except defense. |

## Recommended Next Contracts

1. Add a generated-Core sidegrade validator for standard-vs-alternate upgrade rows. It should reject strict combat stat supersets unless an explicit exception row documents the tactical drawback.
2. Add a `squadValue` sanity validator comparing each custom row to its tier's vanilla range, its own gold cost, and its standard/alternate sibling. This should catch both extreme high rows and impossible low rows.
3. Add a tier-role density validator using the balance bible bands. It should not require exact vanilla mechanics, but it should flag Tier 4+ rows that are mostly raw stats without visible card rules.
4. Add a scaffold tier-mismatch audit. If a Tier 6 or Tier 7 HoMM3 line uses a lower-tier donor shell, the overlay should either supply enough explicit custom mechanics or document the debt as unbalanced.
5. Add an AI/role tag validator for obvious mismatches, such as ranged alternates tagged `melee_type` or flying melee lines tagged like ranged shooters.

These are diagnostic recommendations, not implemented changes.
