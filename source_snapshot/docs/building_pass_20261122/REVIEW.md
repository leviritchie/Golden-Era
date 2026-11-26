# Building pass: cross-faction review (2026-11-22)

This review covers the 12 per-faction drafts in this folder (`<faction>.md`), written against `BRIEF.md`.

## 1. One pattern applied everywhere

- **Shared economy uses the vanilla template in every town:**
  - Town Hall L2 and L3 need only the previous level;
  - Market needs Tavern;
  - Bank needs Town Hall L2;
  - Treasury needs Bank + Wall L1;
  - Resource Depot needs Market + Bank.

  This lives in `COMMON_LEVEL_REQS` in `tools/release_port/homm3_city_building_tree.py`, plus the tree validator's Town Hall rules.
- **No upgraded-dwelling prerequisites, and dwelling upgrades need only their own L1.** The one exception is a T7 upgrade, which may need a Mage Guild level. The upgrades this removes:
  - Stronghold T2:2 and T4:2;
  - Fortress T1:2 and T5:2;
  - Conflux T6:2;
  - Cove and Castle T5:2;
  - Factory T5:2, T6:2 and Gantry:2;
  - Necropolis T4:2 (which needed the Bank).
- **Dwelling base levels keep the HoMM3 unlock order**, trimmed to vanilla density (at most 2 base-level dwelling prerequisites, plus MG for T7).
- **Hordes stay gated on their own base dwelling, in every faction.** That is a base-level prerequisite, so it fits vanilla.
- **The Bank slot becomes the plain economy Bank again** wherever it held a substitute: Castle, Rampart, Tower, Inferno, Necropolis, Dungeon, Fortress and Conflux. Each real special gets its own row in its native section, reusing vanilla SIDs where one exists.
- **A shared `Homm3TownBuildingReader`** answers "does this town or side have building X at level N". Every plugin building uses it.
- **A shared `Homm3TownSiegeDefenseRuntime`** gives battle-only stats to the hero defending a siege of the town that has the building:
  - Brotherhood of the Sword: +2 Morale;
  - Fountain of Fortune: +2 Luck;
  - Glyphs of Fear: +2 Defense;
  - Blood Obelisk: +2 Attack;
  - Brimstone Stormclouds: +2 Spell Power;
  - Carnivorous Plant: +10 Attack and +10 Defense;
  - Warlords' Monument: +20 Attack;
  - Guardian of Earth: +12 Spell Power;
  - Skyship: +15 Knowledge;
  - Spirits of the Forebears: +20 Defense.
- **Grails take their HoMM3 special.** They keep +100% growth and the town gold income. Each replaces whatever substitute package it had:
  - Colossus: +2 Morale for all heroes;
  - Spirit Guardian: +2 Luck for all heroes;
  - Skyship: reveals the map;
  - Deity of Fire: every week is the Week of the Imp;
  - Soul Prison: +10% Necromancy;
  - Aurora Borealis: every spell in the Mage Guild;
  - Lodestar: all terrain counts as native.

## 2. Decided here (drafts' recommendations kept unless noted)

- **Tower Library stacks with the Observatory Network law.** Both apply, for at most +3 spells per guild level. The law stays as it is.
- **Necropolis:** the law that shares the name "Necromancy Amplifier" is renamed to keep the names distinct, and the two stack.
- **Factory:**
  - the loan is granted when the Bank is built;
  - the Mana Generator uses the HotA cost;
  - the Lightning Rod strike is built.
- **Bulwark:**
  - the Fair adds +1 market count;
  - the Altar of the Runes replaces Clan Stockyards and ships with the Runes runtime.
- **Stronghold:**
  - the Resource Silo is corrected to +1 Wood and +1 Ore;
  - Freelancer's Guild goes on the Silo II slot, and the Bank stays.
- **Fortress:** Blood Obelisk replaces the invented Hydra Marsh.
- **Inferno:** Castle Gate goes in the native `myceliumRoots` teleport row and is restricted to towns that also have a Castle Gate.
- **Dungeon:** Portal of Summoning uses the native `portalSummonings` row and replaces the Lyceum.
- **Kept substituted, with honest reasons:**
  - Castle Lighthouse becomes the Signal Beacon (+10% movement for all heroes);
  - Cove Shipyard stays as the Artifact Market;
  - Cove Gunpowder Warehouse moves to the T3 upgrade;
  - Fortress Field Infirmary stays as it is.

## 3. Owner decisions (answered 2026-11-22)

1. **Escape Tunnel:** it comes with the Stronghold Fort. No new building.
2. **New-window buildings** (Freelancer's Guild sell window, Magic University school purchase, Cove Grotto exchange): build them now.
3. **Grails keep their current extras** and add the HoMM3 special on top. This overrides the §1 grail line.

## 4. Build order

1. Tree table and validator, all 12 towns, followed by a solver fit check.
2. Native-only rows:
   - Bank restore;
   - Portal of Summoning;
   - Castle Gate;
   - Skeleton Transformer;
   - Mana Vortex fountain;
   - Aurora;
   - Lodestar;
   - Skyship reveal;
   - Order of Fire;
   - Mushroom Rings;
   - Stronghold Silo;
   - Week of the Imp.
3. The shared reader and the siege runtime. Then the per-building hooks:
   - Stables;
   - Signal Beacon;
   - weekly income (Mystic Pond, Treasury);
   - Library;
   - the Necromancy terms;
   - Cover of Darkness;
   - Mana Vortex doubling;
   - Mana Generator;
   - Lightning Rod;
   - Factory loan;
   - Fair;
   - Altar of the Runes;
   - Escape Tunnel.
4. The window buildings, if owner decision 2 says build.
5. Descriptions and translations into all 15 locales, `source_mechanics` statuses, scene catalog keys for the new rows, validators, dry run, install, check row.
