# HoMM3 Stronghold Building Functionality Feasibility

Finding date: 2026-05-04.

The current `homm3_stronghold_city` is cloned from `dungeon_city`, then patched by `generate_homm3_stronghold_city.py`.

Already ported or approximated in data:

- Creature dwellings use HoMM3 Stronghold-style costs and prerequisites in `HOMM3_STRONGHOLD_HIRE_TREE`.
- Tier 1 no longer requires `Build_Wall`; that fortifications gate was a defunct Olden Era design. Tier 2 still follows Tier 1, not Fortifications.
- Mage Guild is capped to level 3 by `cap_homm3_stronghold_magic_guild()`.
- `Build_Gymnasium` has been made cheaper and prerequisite-gated as a local analogue for Hall of Valhalla. It now gives `heroStat offence +2` instead of Dungeon's `heroExp`; this intentionally exceeds HoMM3's +1 for parity with Hive's custom special building.
- Release UI note: the Hall bonus notification is not driven solely by the city JSON. The correct stat can apply while `BhRewardNotificationHeroStat` still displays donor Human/Gymnasium art/text such as Defense +1, and a stale reward canvas/group can block the town exit afterward. Keep the UI fix on the reward notification surface; do not change the `heroStat offence 2` data to match the wrong message.
- `Build_Resource_Depot` and `Build_Resource_Depot_level_2` now represent the Stronghold Resource Silo as +1 crystal and +1 ore per day, instead of Dungeon gemstones/dust.
- `Build_Lyceum` is moved from `artifactChangers` to `cityBonusBanks` and acts as a Mess Hall, adding `cityUnitsIncrement h3_goblin +8`.
- The English `Homm3Stronghold_Build_*` text tokens for Hall of Valhalla, Mess Hall, and Resource Silo are explicit overrides. Do not rely on the Dungeon token mirror for these rows, or the UI will show old Dungeon descriptions like Gymnasium hero level-up, Lyceum scroll enchanting, or Gems income.

Data-only candidates:

- If additional horde buildings are added later, prefer `cityBonusBanks` rows with `cityUnitsIncrement` over putting bonus fields on `artifactChangers`; the latter has no `bonuses` field in the IL2CPP city schema.

Not data-only (exact HotA still unmatched):

- Escape Tunnel: HoMM3 allows retreat/surrender during siege. Olden Era city JSON has no discovered building config field for siege retreat policy. **Current ship state:** `custom_factions/source_mechanics/homm3_stronghold.json` marks `stronghold.escape_tunnel` as `substituted` onto `Build_Spy_Network` with forbidden player text for “Escape Tunnel” / “escape siege”. Do not describe this as an unfinished placeholder row that still needs a hook before ship; exact siege-escape remains optional future hook work.
- Freelancer's Guild: no discovered native building type sells arbitrary creatures for resources. **Current ship state:** `stronghold.freelancers_guild` is `substituted` onto `Build_Bank` with forbidden Freelancer/exchange-creatures player text. Same rule as Escape Tunnel — intentional substitute, not hard remaining hook debt.
- Ballista Yard: Olden Era's current city schema does not expose a proven HoMM3 war-machine purchase city path. Stronghold has no `source_mechanics` Ballista Yard row and no CITY_BUILDING_MECHANICS Ballista Yard entry; treat authentic war-machine purchase as still open OE-wide unless a later build proves a city path.

Warning: do not solve building identity by only remapping town visual layers or localization. Building behavior follows the city JSON building category and bonus graph; visual layer mappings only affect the HoMM3 town art.
