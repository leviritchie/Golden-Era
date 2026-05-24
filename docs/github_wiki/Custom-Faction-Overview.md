# Custom Faction Overview

These are the currently registered custom factions in the live Core data.

| Faction | Faction SID | Native biome | Donor faction | Faction skill SID | Unit lines |
| --- | --- | --- | --- | --- | --- |
| [Castle (HoMM3)](Custom-Faction-Castle) | homm3_castle | Valleys | humans | skill_faction_humans | 7 |
| [Conflux (HoMM3)](Custom-Faction-Conflux) | homm3_conflux | Greenlands | nature | skill_faction_homm3_conflux | 7 |
| [Cove (HoMM3)](Custom-Faction-Cove) | homm3_cove | Tropical | humans | skill_faction_homm3_cove | 7 |
| [Dungeon (HoMM3)](Custom-Faction-Dungeon) | homm3_dungeon | Burrow | dungeon | skill_faction_homm3_dungeon | 7 |
| [Fortress (HoMM3)](Custom-Faction-Fortress) | homm3_fortress | Swamp | nature | skill_faction_homm3_fortress | 7 |
| [Inferno (HoMM3)](Custom-Faction-Inferno) | homm3_inferno | Molten | demons | skill_faction_homm3_inferno | 7 |
| [Necropolis (HoMM3)](Custom-Faction-Necropolis) | homm3_necropolis | Curselands | undead | skill_faction_homm3_necropolis | 7 |
| [Rampart (HoMM3)](Custom-Faction-Rampart) | homm3_rampart | Hills | nature | skill_faction_homm3_rampart | 7 |
| [Stronghold (HoMM3)](Custom-Faction-Stronghold) | homm3_stronghold | Wasteland | dungeon | skill_faction_homm3_stronghold | 7 |
| [Tower (HoMM3)](Custom-Faction-Tower) | homm3_tower | Tundra | humans | skill_faction_homm3_tower | 7 |

## Shared Implementation Rules

- Custom factions use manifest-owned custom-to-donor mapping. Do not enable broad reverse lookup from donor SIDs; resolve donor map objects from exact live payloads or known contextual state.
- Buildings are functional by section-specific fields, not only by a generic `bonuses` array. Check `unitsHire`, `viewRadius`, `trainingStats`, `sideBonuses`, `cityBonuses`, `conversionPairs`, artifact-market charge fields, and section name before declaring a row inert.
- Player-facing text should describe only shipped behavior. Avoid water, ship, teleport, war-machine, or school-purchase claims unless the corresponding native or traced runtime path exists.
- Unit view donor meshes are scaffolding. Current unit behavior is defined by logic rows, attacks, abilities, passives, and the runtime HoMM3 import hooks.
