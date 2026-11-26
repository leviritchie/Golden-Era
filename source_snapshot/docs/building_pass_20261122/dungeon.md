# Dungeon building pass (`homm3_dungeon`, 2026-11-22)

Sources:
- Installed rows: Golden Era `Core.zip` `DB/objects_logic/cities/homm3_dungeon_city.json`.
- Vanilla: Steam `Core.zip`. Native sections: `portalSummonings` (only `unfrozen_city` `Build_Portal_Summoning`) and `manaFountains` (only undead `Build_Well_Of_Souls`).
- HoMM3: heroes.thelazy.net Dungeon page.
- Native classes: `.tmp/town_pick/hex_src`.
  - `BuildingPortalSummoning` copies every external dwelling the side owns (`side.hiresList`) at its weekly increment. Purchases are capped per week by `numberPurchases` + the `portalSummoningUsageLimit` bonus.
  - `BuildingManaFountain.HeroVisit` calls `RestoreManaPointsToMax()`.

Scratch scripts are in `V:/olden_port_work/building_pass/claude_ind/`.

**Slot map today.**
- `Build_Bank` is "Spellwell", 1000 Gold, gated on MG1. Its tag says Mana Vortex, which has no effect today.
- Portal of Summoning is tagged on `Build_Lyceum`, which is the vanilla OE scroll enchanter (`artifactChangers`).
- `Build_Resource_Depot_level_2` is "Alchemic Depot" (+5 Dust). The tree tool already calls this slot Mushroom Rings, but there is no Troglodyte horde today.
- `Build_Spy_Network` is the grail. Native Artifact Merchants is exact.

The placement rule is the same as in `inferno.md` (owner decision 1).

## 1. Special buildings

| SID | Source building (HoMM3/HotA effect) | Current effect | Status | Proposed build | Player text | Cost/power note |
|---|---|---|---|---|---|---|
| `Build_Well_Of_Souls` (new in Dungeon; section `manaFountains`, `{}`) | **Mana Vortex**: once a week, the first visiting hero's mana is doubled, up to twice maximum. | None (the name and tag sit on the Bank). | substituted -> **exact** | Native `manaFountains` refills mana to maximum at each visit. Plugin hook P5 is a postfix on `BuildingManaFountain.HeroVisit` for `homm3_dungeon_city` only. If this town's weekly flag is unused, set mana to 2 × maximum and mark the flag; reset all flags at week start. The native refill stays for later visits; that is a small, honest extra (decision 3). | Explicit: "Once a week, doubles the mana of the first visiting hero. Restores all mana to any other visiting hero." | Vanilla Well of Souls: 2500 Gold + 3 Gems/Crystals/Mercury. Gated on MG L1 (HoMM3). The vanilla Well's MG3 gate is relaxed because HoMM3's Vortex needs only MG1. |
| `Build_Portal_Summoning` (new; section `portalSummonings`) | **Portal of Summoning**: recruit creatures from an external dwelling you own. | Tag only. `Build_Lyceum` is a scroll enchanter. | substituted -> **exact** | Native `portalSummonings: {"numberPurchases":1}` (the vanilla Unfrozen row). It covers every external dwelling the side owns, while HoMM3 rolls one at random each week. Native is the closer and kinder form. `Build_Lyceum` is removed from Dungeon (decision 2). | New generator branch: "Allows you to recruit creatures from the dwellings you own outside cities, once a week." | Vanilla Unfrozen price 5000 Gold + 3 Gems/Crystals/Mercury. HoMM3: 2500 Gold + 5 Ore. Root, as in HoMM3. Vanilla gates it on the Endless Library, which Dungeon has no counterpart for. |
| `Build_Gymnasium` (`heroBonusBanks`) | **Battle Scholar Academy**: +1000 experience, once per visiting hero. | Native heroExp "Levels up any visiting hero once." Named after the vanilla slot. | substituted -> **exact** | Keep native `heroExp ["false"]`; at port hero-level pacing, one level up is the vanilla equivalent of HoMM3's flat 1000 experience. Rename it "Battle Scholar Academy". | Generated (unchanged): "Levels up any visiting hero once." | Keep 5000 (vanilla Gymnasium). |
| `Build_Resource_Depot_level_2` (`banks`) | **Mushroom Rings**: +7 Troglodytes a week. | "Alchemic Depot", +5 Dust a day: a donor economy stand-in. | substituted -> **exact** | `banks` with `cityUnitsIncrementPer ["h3_troglodyte","0.2596"]`, which gives +7 of 27. This is the Birthing Pools / Unearthed Graves form. Gated on T1. | Generated: "Increases Troglodyte growth by 7." | Same as the other hordes: keep the slot's cost. Dungeon loses +5 Dust a day and the Resource Silo still gives its Gems. That is a real economy cut, matching the other hordes. |
| `Build_Spy_Network` (graal) | **Guardian of Earth**: +12 Spell Power to the garrisoned hero defending a siege, +5000 Gold a day, +50% growth. | DungeonGraal: full map reveal and +100% growth. | substituted -> **exact** | Keep `graalType: DungeonGraal` and `cityBonuses` +100%. Drop the reveal side bonus. Plugin hook P1 (shared siege-defense hook, see `inferno.md`) gives +12 Spell Power. Rename it "Guardian of Earth". | Explicit (new `graal_dungeon` template): "A hero defending this city in a siege gains +12 Spell Power. This city's dwellings produce +100% units." | Grail convention for growth. Losing the full reveal costs a map-wide effect for a local one. |
| `Build_Artifact_Market` | **Artifact Merchants**. | Native. | exact | No change. | No change. | No change. |
| `Build_Bank` (`banks`) | None: the shared vanilla Bank. | "Spellwell", 1000 Gold, gated on MG1. | n/a (economy) | Unchanged sideRes gold 1000. Rename it "Bank". Gate it on Main L2. | Generated: "Produces 1000 Gold daily." | Unchanged. |

`source_mechanics/homm3_dungeon.json` changes:
- `dungeon.mana_vortex`: `exact`, rows `Build_Well_Of_Souls`.
- `dungeon.portal_of_summoning`: `exact`, rows `Build_Portal_Summoning`.
- `dungeon.battle_scholar_academy`: `exact`.
- `dungeon.mushroom_rings`: `exact`, rows `Build_Resource_Depot_level_2`.
- `dungeon.guardian_of_earth`: `exact`, rows `Build_Spy_Network`.

Mana Vortex and Guardian of Earth stay runtime-unproven until P5 and P1 are exercised.

## 2. Tree changes

| Level | Current prerequisites | Proposed prerequisites | Why (convention) |
|---|---|---|---|
| Build_Main:2 | Tavern | none | Town Hall needs only the previous level. |
| Build_Main:3 | MG1, Market | none | Same. |
| Build_Market:1 | none | Tavern | Shared economy. |
| Build_Bank:1 | MG1 | Main L2 | Economy template. The MG1 gate moves with Mana Vortex. |
| Build_Resource_Depot:1 | Market | Market, Bank | Economy template. |
| Build_Tier_2:1 | T1 | none | Depth: T1->T2->T4->T5->T7 was 5 deep; vanilla is at most 4. T2 is a root in 5 of 6 vanilla cities. |
| Build_Tier_4:1 | T2, T3 | T2 | Density: keep the HoMM3 flavour (Pillar of Eyes <- Harpy Loft) and drop the second dwelling, so dwellings no longer form a two-wide web. |
| Build_Tier_7:1 | MG2, T5, T6 | MG2, T6 | Vanilla T7 is at most MG2 plus 1 dwelling. Keep the Manticore Lair link (HoMM3). |
| Build_Tier_7:2 | MG3 | MG3 (unchanged) | The one vanilla exception: Dungeon T7 L2 <- MG L3. |
| Build_Well_Of_Souls:1 (new) | n/a | MG L1 | Mana Vortex <- MG1 (HoMM3). |
| Build_Portal_Summoning:1 (new) | n/a | none | HoMM3 has no prerequisite. |
| Build_Lyceum:1 (removed) | none | n/a | Replaced by the Portal (decision 2). |
| Build_Resource_Depot_level_2:1 | T1 | T1 (unchanged) | A horde needs only its own dwelling (Mushroom Rings <- Warren). |

Tool edits:
- `FACTION_LEVEL_REQS["homm3_dungeon"]` gets the rows above.
- buildOrders: add 2 SIDs and drop Lyceum.
- Re-run the solver and the static validator. Fit: 36 levels; deepest dwelling chain 4.

**Levels without outside prerequisites: 21 of 35 before, 23 of 36 after** (vanilla 22-23).

## 3. Plugin work

| Hook | File | Game method | Risk |
|---|---|---|---|
| P0: town-building reader (shared). | New `Homm3CityBuildingReader.cs` | `TryBuildWorld` snapshot plus a `CountMarkets`-style scan. | Low. |
| P1: siege defender Spell Power (shared with Inferno's Brimstone Stormclouds). Entry `{homm3_dungeon_city, Build_Spy_Network, 12}`. | New `Homm3TownSiegeDefenseRuntime.cs` | `TransferBattle` battle-start entry, the same as `Homm3CastleEliteStrategemRuntime`, with the `arenaLogicSid` "siege" test (`:269`). Find the besieged city, check it through P0, and add a battle-only `spellPower` to the defending hero. | Medium. Unknowns: the city id on TransferBattle, and the battle-scoped stat write. |
| P5: Mana Vortex doubling. | New `Homm3DungeonManaVortexRuntime.cs` | Postfix on `BuildingManaFountain.HeroVisit(hero)`. If the owning city is `homm3_dungeon_city` and its weekly flag is unused: set mana to 2 × maximum through the hero resource setter (look up the IL2CPP `res` mana field; `RestoreManaPointsToMax` shows where it lives) and mark the flag. A side or week-start hook clears the flags. Flags live in the plugin's saved-state sidecar, keyed by city id. | Medium. (1) The mana field write must survive the native clamp, which may need a max-mana override for the day. (2) Save persistence. (3) `OnConstruct` also refills the garrison and visitor heroes natively. That is harmless, but should not use up the weekly double. |

Tooling:
- **Descriptions**:
  - a `portalSummonings` branch in `derive_building_sentences`;
  - Mana Vortex explicit text;
  - a `graal_dungeon` template;
  - the Mushroom Rings sentence comes from the existing `cityUnitsIncrementPer` path.
- **Overlay**: the new rows, Lyceum removed, the Depot L2 bonus swapped, and the graal side bonus removed.
- **Visual map**: `building_layer_map.json` moves the Lyceum and Bank layers to the Portal and Vortex keys.

## 4. Owner decisions

1. **Economy slot vs special** (same fork as in Inferno and Necropolis). **Recommend restoring the plain Bank** and giving Mana Vortex its own `manaFountains` row.
2. **Lyceum vs Portal of Summoning.** Lyceum is an OE-native scroll enchanter with no HoMM3 Dungeon source; the Portal is the real building. Replacing Lyceum keeps 36 levels. Keeping both makes 37 levels and is still inside the 45-cell grid. **Recommend replacing Lyceum.** The Mage Guild/scroll flavour stays with Mana Vortex, and the tree stays at vanilla size.
3. **Mana Vortex later visits.** Native `manaFountains` refills to maximum on every visit, while HoMM3's Vortex does nothing after the weekly double. **Recommend keeping the native refill**: it is free, readable, and a mild buff. The strict version needs an extra prefix that skips the native refill when the flag is used.
