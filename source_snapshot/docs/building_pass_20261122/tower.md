# Tower (`homm3_tower_city`) building pass

Source of current rows: installed GE `Core.zip`, `DB/objects_logic/cities/homm3_tower_city.json` (dumped 2026-11-22). Text tokens: `Lang/english/texts/cities.json`. HoMM3 effects are from the SoD/HotA building table. The port scales resources and primary stats 1:1 (the Wall of Knowledge is +1 in both).

## 1. Special buildings

| SID | Source building (HoMM3/HotA effect) | Current effect | Status | Proposed build | Player text | Cost/power note |
|---|---|---|---|---|---|---|
| `Build_Bank` (now "Capitol Vault") | HoMM3 Capitol (Town Hall L4: +4000 gold), which the port does not have. Used here as the economy Bank. | `banks` 1000 gold a day, needs Main L3 + Wall L3. | economy slot with a borrowed name and Capitol gate | Make it the shared-economy **Bank**: keep `sideRes gold 1000`, use the vanilla Bank name and text, and gate it on Main L2 (Part B). | "Bank" / "Produces 1000 Gold daily." | unchanged |
| new Library row (`banks` carrier, empty `bonuses`; new SID such as `Build_Library`) | Library: +1 spell on every Mage Guild level of this town. Needs MG L1; HoMM3 also gates the Mage Tower upgrade on it. | Absent as a building. The effect sits on the law `fraction_law_homm3_tower_2` (Observatory Network: `magicGuildIncrement` 1/2 + `magicGuildLearnAdditionMagicAllOpenLevel` 1/2, faction-filtered), which is side-wide and law-bought. | absent → **exact** | Plugin hook 5 (per-town Mage Guild +1). A postfix on `BuildingMagicGuild.GetMagicsCountForRank` adds +1 when that guild's city has the Library. When the Library is built, call `BuildingMagicGuild.LearnMagicAddition(1)` on that city's guild so already-open levels get their extra spell. Native data cannot say it: `magicGuildIncrement` is a side bonus, and a bank row's `cityBonuses` accept only `magicGuildExpandMagics` (all spells, the grail's effect). | "Library" / "Adds 1 extra spell to every Mage Guild level in this city." | HoMM3 value. Cost: HoMM3 1500 gold + 5 each of wood/ore/mercury/crystals/gemstones (the sulfur goes to mercury), 1:1. See owner decision 1 for the overlap with the law. |
| `Build_Golden_Calf` ("Aether Beacon"; the `Homm3Tower_Build_Graal_name` token says "Skyship Beacon") | Skyship grail: reveals the whole map, +15 Knowledge to the hero defending this town, plus grail growth and gold. | HumanGraal `sideResHumGraal` gold 1000 + 1 of each other resource, and `cityUnitsIncrementPer all 1.0` (`tower.skyship_beacon`, substituted). | substituted (donor) → **exact** | Keep `sideResHumGraal gold 1000` and `cityUnitsIncrementPer all 1.0`. Replace the five resources with graal `cityBonuses: cityRadiusView 999` (native; the vanilla Dungeon grail reveals the map exactly this way). Plugin hook 2 (siege-defence town bonus) gives the defending hero `intelligence +15` for a siege of this town. Name it "Skyship" in both tokens. | "Skyship" / "Reveals the entire map. The hero defending this town in a siege gains +15 Knowledge. The owner's cities produce 1000 Gold daily. This city's dwellings produce +100% units." | Grail-strength: map reveal is the vanilla Dungeon grail's headline effect. +15 Knowledge applies to one battle only; see owner decision 2. |
| `Build_Intelligence_Academy` (Lookout Tower) | +15 sight radius around the town. | `viewRadius 15`, needs Wall L1. | exact | No effect change; tree change only. | unchanged | unchanged |
| `Build_Training_Range` (Wall of Knowledge) | +1 Knowledge once per visiting hero. | `heroBonusBanks intelligence +1`, needs MG L1. | exact | No change. | unchanged | unchanged |
| `Build_Resource_Depot_level_2` (Sculptor's Wings) | +4 Stone Gargoyles a week. | `h3_gargoyle 0.2865`, needs T2. | exact | No change. | unchanged | unchanged |
| `Build_Artifact_Market` (Artifact Merchants) | HoMM3 Tower Artifact Merchants. | Artifact trading, needs Market. | exact (economy) | No change. | unchanged | unchanged |
| `Build_Treasury` (named "Blacksmith") | Blacksmith sells an Ammo Cart (war-machine purchase). | The shared-economy Treasury: 2000 gold a day. | economy slot with a borrowed name | Keep the effect; rename it "Treasury". | "Treasury" / "Produces 2000 Gold daily." | unchanged |

Text: the Library and the Skyship's Knowledge clause need explicit descriptions (plugin-only). The map-reveal clause can come from the `cityRadiusView` template.

Art: the Library needs a layer binding. The candidate is the HoMM3 Tower Library layer; today `tbtwspec` is mapped to `Build_Artifact_Market` and `tbtwext2` to `Build_Resource_Depot_level_2`, so confirm a free layer in the 3D catalog. Declare it in source_mechanics `currentRows`.

## 2. Tree changes

| Level | Current prerequisites | Proposed prerequisites | Why (convention) |
|---|---|---|---|
| Main L2 | Tavern | none | Town Hall L2/L3 need only the previous level. |
| Main L3 | MG L1, Market | none | Same. |
| Market | none | Tavern | Market needs Tavern. |
| Bank | Main L3, Wall L3 | Main L2 | Bank needs Main L2. Removes the HoMM3 Capitol gate and the second upgraded prerequisite. |
| Resource Depot | Market | Market, Bank | Depot needs Market + Bank. |
| T4 L1 (Mage Tower) | MG L1, T2, T3 | T2, T3 | A dwelling L1 has at most 2 base-level dwelling prerequisites, and only T7 takes an MG gate. Keeps the HoMM3 Parapet + Golem Factory flavour. |
| T4 L2 (Upg. Mage Tower) | none | none (do **not** add the HoMM3 Library gate) | Dwelling upgrades need only their own L1. |
| Lookout Tower (Intelligence Academy) | Wall L1 | none | The vanilla Intelligence Academy is a root. This also brings the city into the 22–23 band. |
| Library (new) | n/a | MG L1 | HoMM3 requirement; one base-level shared building. |
| T2, T3, T5, T6, T7 (T5 + T6), Treasury, Artifact Market, Wall of Knowledge (MG L1), Sculptor's Wings (<- T2) | as now | unchanged | Already convention-shaped. |

Levels with no outside prerequisite: before **20 of 35**, after **22 of 36**. Everything still fits the solver's columns 0..8 × 5 rows: 1 new node, and the deepest chain is T1 → T2 → T4 → T5 → T7 (depth 4, as now).

The validator `validate_homm3_city_building_tree_contract.py` must drop the Town Hall / City Hall checks. `COMMON_LEVEL_REQS` and `FACTION_LEVEL_REQS["homm3_tower"]` change to match. Remove the ADAPTATIONS note about the Bank as the Capitol.

## 3. Plugin work

All new files go in `Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/`.

1. **Town building reader** (new `Homm3TownBuildingReader.cs`; shared and specified in castle.md §3.1). Risk: low to medium.
2. **Siege-defence town bonus** (new `Homm3TownSiegeDefenseBuildingRuntime.cs`; shared, castle.md §3.2) adds `intelligence +15` to the defending TransferHero for a Tower siege with the Skyship built. Mana must be checked: if the battle seeds mana from max mana computed before `Init`, the Knowledge has to land before that point or the max-mana field must be raised too. Risk: medium. With no defending hero the bonus simply does not apply, which matches HoMM3 ("the hero defending").
3. **Per-town Mage Guild +1** (new `Homm3TowerLibraryRuntime.cs`). (a) A postfix on `BuildingMagicGuild.GetMagicsCountForRank` adds +1 when the guild's owning city has the Library (through hook 1). (b) On Library construction, call `LearnMagicAddition(1)` on that city's `BuildingMagicGuild` (the method `LogicEventsCatcher` already uses for the law). The construction event can come from the building-completed path that `Homm3ConstructionNativeAdapter` already observes. Risk: medium. (a) Make it idempotent on load: re-running the learn call must not add a second spell, so check the guild's per-rank count against `GetMagicsCountForRank` first. (b) The guild must not run out of spells in a rank once the law's +2 stacks on top, which allows up to 7 per rank; the guild fill already caps at the rank's pool, but verify. (c) It is faction-filtered like the law, so a captured Tower keeps it under any owner, as in HoMM3.

## 4. Owner decisions

1. **Library vs the Observatory Network law.** HoMM3's Library is a per-town building; the port's law gives a side-wide +1/+2 for Tower guilds. (a) Add the Library and leave the law (they stack to +3). (b) Add the Library and retune the law to something non-guild. (c) Skip the Library and keep the law as its stand-in. **Recommend (a) now, with a flag to the law owner for (b).** The building is the source mechanic and this pass should not rewrite laws; the stacking is bounded by the spell pool.
2. **Skyship Knowledge value.** +15 (HoMM3 at the port's 1:1 stat scale), or a smaller value such as +5 if OE mana-per-Knowledge makes +15 decisive. **Recommend +15.** It lasts one siege, affects one hero, and sits on a grail.
3. **Mage Tower prerequisites.** Trim to Parapet + Golem Factory (two dwellings, the vanilla shape), or to MG L1 + Golem Factory (keeps the HoMM3 "mages need a guild" link, which is not vanilla-shaped). **Recommend Parapet + Golem Factory.** Vanilla never gates a non-T7 dwelling on the Mage Guild, and the Library and Wall of Knowledge already tie Tower to its guild.
