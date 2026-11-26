# Cove building pass (2026-11-22)

Scope: `homm3_cove_city`, as installed in GE `Core.zip` (`DB/objects_logic/cities/homm3_cove_city.json`). HotA source: Cove town buildings.

How the slots map to roles:
- Economy template, holding the economic building: `Build_Bank` (1000 gold), `Build_Treasury` (the "Blacksmith" Treasury, per the 2026-10-01 naming decision, 2000 gold), `Build_Resource_Depot` and `Build_Artifact_Market`.
- Specials: `Build_Resource_Depot_level_2` (Pub horde), `Build_Mother_Nature` (Roost horde) and `Build_Golden_Calf` (grail).
- Missing: the HotA Grotto has no row.

## 1. Special buildings

| SID | Source building (HoMM3/HotA effect) | Current effect | Status | Proposed build | Player text | Cost/power note |
|---|---|---|---|---|---|---|
| `Build_Golden_Calf` (graals) | Lodestar: +5000 gold per day, growth x1.5, and every terrain counts as native for Cove creatures | HumanGraal (`sideResHumGraal` 1000 gold plus 1 of each resource, city `cityUnitsIncrementPer all 1.0`), named "Lodestar Vault" | Grail economy is exact to the port's grail standard. The terrain clause is missing. | Keep the HumanGraal bonuses. Add the native `{"type":"anyLandEqualNativeLandBonus"}` (no parameters, the same bonus Unfrozen law 34 ships) to `sideBonuses`. If graal `sideBonuses` turns out not to read it, fall back to the plugin: while the side owns a Lodestar, treat every land as native in the native-terrain check. Use the reader in section 3. | "The owner's cities produce 1000 Gold and 1 of each other resource daily. All terrain counts as native terrain for your creatures. This city's dwellings produce +100% units." | Grail-strength already; the terrain clause is the HotA effect, not extra power. The native bonus may cover every unit in the army, not only Cove creatures. Accept that: OE has no per-faction native-land qualifier. |
| New row: Grotto (proposed `Build_Grotto`, section decided at implementation, see section 3) | Grotto: visiting heroes sacrifice creatures or artifacts for experience, like the Altar of Sacrifice. 7500 gold, 15 wood, 15 ore; requires Marketplace. | None (absent) | absent | Plugin exchange window opened from the building: pick creatures from the hero's army or artifacts from the hero's bag and get experience. Use the HoMM3 Altar of Sacrifice exchange table (per-creature and per-artifact experience values; check the exact numbers against the HotA source when implementing, then scale them by the port's experience scale). No native section can say this: OE's `artifactChangers` (Dungeon Lyceum) swaps artifacts and does not give experience. Re-use the now row-less `Build_Training_Range` text keys ("Boarding Yard") only if the owner prefers the old name. Otherwise delete those leftover keys and the `Intelligence_Academy` ("Smuggler's Lookout") keys. | "Visiting heroes may sacrifice creatures or artifacts in exchange for experience." | HotA cost 7500 gold, 15 wood, 15 ore, unscaled (other Cove rows keep HotA gold). Owner decision 1. |
| `Build_Bank` (banks) | No HotA Cove bank. HotA Thieves' Guild is an information screen OE does not have. | Economic Bank, 1000 gold per day, but named "Thieves' Guild" | Misnamed. The economy slot is correct. | Keep the row and its bonus. Rename only, for example "Counting House". The source_mechanics row for the Thieves' Guild becomes `absent`, with the reason "OE has no thieves' guild information screen". | "Produces 1000 Gold daily." (unchanged) | No change. |
| `Build_Artifact_Market` (artifactMarkets) | Shipyard: build ships (2000 gold, 20 wood) | Standard Artifact Market (2/2/1/1, charge 3.0) named "Quartermaster's Wharf", tagged `cove.shipyard` | substituted | No effect change. The slot is the shared-economy Artifact Market every vanilla town has. Ships cannot exist, and any land "equivalent" (movement, ship-like travel) would be a donor stand-in. Keep the honest status. Reason text: "Ships and water travel cannot exist in Olden Era; this slot is the shared Artifact Market, named for the wharf, and no ship purchase is offered or claimed." | "Allows artifacts to be traded." (unchanged) | No change. |
| `Build_Treasury` (banks) | Registry tags it `cove.gunpowder_warehouse`. That is wrong: the row is the economic Treasury ("Blacksmith", 2000 gold). HotA Gunpowder Warehouse is the second upgrade of the Pirate dwelling (Sea Dogs; 3000 gold plus 5 of each resource). | 2000 gold per day | The Gunpowder Warehouse tag is stale. | No effect change. Move the `cove.gunpowder_warehouse` mapping in `Homm3ConstructionBuildingCategoryRegistry.cs` and in source_mechanics from `Build_Treasury` to `Build_Tier_3` L2. Keep `substituted` with the reason "An OE dwelling upgrade unlocks both upgraded creatures (Corsair and Sea Dog) at once; there is no separate second-upgrade building." | unchanged | No change. Sea Dogs already come with the Tier 3 upgrade. |
| `Build_Resource_Depot` (banks) | Resource Silo: +1 sulfur per day | +1 mercury per day | substituted | No change. OE has no sulfur. Mercury is the generator's fixed fold, and the reason is honest. | "Produces 1 Mercury daily." | No change. |
| `Build_Resource_Depot_level_2` (banks) | Pub: +4 Crew Mates per week | `cityUnitsIncrementPer h3_crew_mate 0.2865` | exact | No change | unchanged | No change. Tree gate: see section 2. |
| `Build_Mother_Nature` (banks) | Roost: +3 Stormbirds per week | `cityUnitsIncrementPer h3_stormbird 0.5017` | exact | No change | unchanged | No change. Tree gate: see section 2. |

## 2. Tree changes

| Level | Current prerequisites | Proposed prerequisites | Why (convention) |
|---|---|---|---|
| Build_Main:2 | Tavern | none | Town Hall L2 needs only the previous level. |
| Build_Main:3 | MG1 + Market | none | Town Hall L3 needs only the previous level; this removes the HoMM3 Capitol gate. |
| Build_Market:1 | none | Tavern | Market needs Tavern. |
| Build_Resource_Depot:1 | Market | Market + Bank | Resource Depot needs Market + Bank. |
| Build_Tier_5:2 | MG2 | none | A dwelling upgrade needs only its own L1; only a T7 upgrade may take a Mage Guild level. |
| Build_Tier_7:2 | MG2 | MG2 (keep) | The T7 upgrade is allowed one Mage Guild level. |
| Build_Tier_7:1 | T5 + T6 | keep | 2 base dwellings, within 0 to 2. |
| Build_Tier_5:1 | MG1 + T2 | keep | A base shared building plus 1 base dwelling has a vanilla precedent (a vanilla T4 needs T1 + MG1). |
| Build_Resource_Depot_level_2:1 (Pub) | T2 | T2 (keep; owner decision 2) | A horde is a special. The strict rule allows a special only a shared building; keeping its own base dwelling is HoMM3 flavour and never an upgraded dwelling. |
| Build_Mother_Nature:1 (Roost) | T4 | T4 (keep; owner decision 2) | Same as the Pub. |
| New Grotto | none | Market | A special has at most 1 base shared building; Marketplace is the HotA requirement. |
| Bank, Treasury, Artifact Market, Tier 2/3/4/6 L1 | (as now) | unchanged | Already the template, or 1 base dwelling. |

Levels without an outside prerequisite: 17 of 33 before; 19 of 34 after (the new Grotto counted). The layout gains one node (Grotto). Rerun `solve_construction_tree_layout` to confirm it still fits columns 0..8 in 5 rows. 34 levels is the vanilla size.

## 3. Plugin work

1. **Town building reader (shared with Factory and Bulwark).** New file `Homm3CityBuildingReader.cs`. No such reader exists today: `Homm3StrongholdTownLayers.GetBuildingLevel` reads one `BuildingData`, and `Homm3FactoryLogisticsEffects.CountMarkets` only walks `city.buildings.markets`.
   - API: `TownLevel(city, buildingSid)`; `SideTownCount(world, sideIndex, citySid, buildingSid, minLevel)`; `DefendedTown(transferBattle)`.
   - Implementation: walk every `city.buildings.<section>` list by `sid`, honouring `isConstructed` and `level`.
   - Risk: low. The read is main-thread only (IL2CPP objects off-thread caused GC fatals). Cache per game day.
2. **Lodestar terrain.** Native first, as `anyLandEqualNativeLandBonus` in graal `sideBonuses`.
   - Risk: medium. That bonus is proven only at law scope. If it does nothing from a graal, the fallback is a postfix on the native-terrain check that the Unfrozen law handler reads, keyed off reader item 1.
3. **Grotto exchange.**
   - New file `Homm3CoveGrottoRuntime.cs`. It opens a sacrifice window from the town building and pays experience through the hero experience path the Cove Treasure Hunting subskills already use (`Homm3CoveTreasureSubskills.cs` reaches `DataHero`).
   - Risk: high. A new town-screen interaction is needed; the comparable native window (Necropolis Skeleton Converter) failed to open in the 2026-10-02 run. Creature and artifact removal must also be save-safe.
4. **Category registry fix** (`Homm3ConstructionBuildingCategoryRegistry.cs`): move `cove.gunpowder_warehouse` from `Build_Treasury` to the Tier 3 upgrade. Data-only; no risk.

## 4. Owner decisions

1. **Grotto: build it with a new exchange window, or leave it `absent`?** Recommendation: build it, but as its own task after items 1 and 2, because the town-screen interaction is unproven. Until then, keep the row absent with honest status. A donor stand-in (for example a Training Range) breaks the no-donor rule.
2. **Horde gates (Pub needs Tier 2, Roost needs Tier 4).** This is a cross-faction choice: every HoMM3 town keeps hordes in the Depot L2 or Mother Nature slots. Recommendation: keep each horde gated on its own base dwelling. Without the dwelling, the horde's growth bonus does nothing, and the rule's spirit (no upgraded-dwelling gates, no deep chains) is still met.
3. **Shipyard slot.** Recommendation: keep the shared Artifact Market with the honest "no water" status. Do not invent a land "Shipyard" effect. The alternative is a movement bonus for visiting heroes, which would be a Castle-Stables-shaped stand-in.
