# Inferno building pass (`homm3_inferno`, 2026-11-22)

Sources:
- Installed rows: Golden Era `Core.zip` `DB/objects_logic/cities/homm3_inferno_city.json` and `Lang/english/texts/cities.json`.
- Vanilla: Steam `Core.zip`.
- HoMM3: heroes.thelazy.net Inferno page.
- Native classes: `.tmp/town_pick/hex_src` (managed decompile: `BuildingMyceliumRoots`, `CmdMyceliumRootsApply`, `BhMyceliumRoots`).

Scratch scripts are in `V:/olden_port_work/building_pass/claude_ind/`.

**Slot map today.** In the installed Core, the names and the `source_mechanics` tags disagree:
- `Build_Bank` is named "Castle Gate" and pays 1000 Gold, but its tag says `order_of_fire`.
- `Build_Treasury` is the "Blacksmith" (the vanilla Treasury, 2000 Gold), but its tag says `castle_gate`.

Both tags are fixed below. Order of Fire has no row today. The Lang file also carries "Artifact Merchants" text for Inferno with no row behind it. HoMM3 Inferno has no Artifact Merchants, so that text and the `Build_Artifact_Market -> tbinext2` visual key are stale and should be dropped.

**Placement rule used in all three of my files (owner decision 1).**
- `Build_Bank` goes back to the plain vanilla Bank: 1000 Gold, gated on Town Hall L2.
- Each special moves to its own SID in its native section. The SID is the vanilla one for that section wherever one exists.
- This keeps the shared economy identical to vanilla, which is the Part B convention.

## 1. Special buildings

| SID | Source building (HoMM3/HotA effect) | Current effect | Status | Proposed build | Player text | Cost/power note |
|---|---|---|---|---|---|---|
| `Build_Mycelium_Roots` (new; section `myceliumRoots`) | **Castle Gate**: a visiting hero teleports to another of your Inferno towns that also has a Castle Gate. | Not built. The name sits on `Build_Bank`, which pays 1000 Gold. | substituted -> **exact** | Native `myceliumRoots: {}` (the vanilla Nature Mycelium Roots). Natively, `CmdMyceliumRootsApply` moves the hero to the gate of any owned city that has no visitor. To match HoMM3, plugin hook P2 limits destinations to towns that have this building (decision 2). The visual moves from the old `Build_Bank` layer (`tbinext1`) to this SID in `building_layer_map.json`. | With P2: "Allows a hero to travel to any of your cities that also has a Castle Gate." Without P2: the vanilla `mycelium` sentence. | Vanilla Mycelium Roots: 5000 Gold + 5 Gems/Crystals/Mercury, gated on Wall L2. HoMM3 gates it on the Citadel (Wall L2) too. |
| `Build_Mother_Nature` (new; section `heroBonusBanks`) | **Order of Fire**: +1 Spell Power, once per visiting hero. | None (no row). | substituted -> **exact** | `heroBonusBanks`, bonuses `[{"type":"heroStat","parameters":["spellPower","1"]}]`. Native, once per hero. The visual key `tbinext0` already exists. | Generated: "Grants +1 Spell Power to any visiting hero." | Half of vanilla Mother Nature (+2 Spell Power for 5000 Gold), so 2500 Gold + 5 Wood. Gated on MG L1 (HoMM3). |
| `Build_Resource_Depot_level_2` (moves to section `cityBonusBanks`, `bonuses: []`) | **Brimstone Stormclouds**: +2 Spell Power to the garrisoned hero defending a siege. | `banks` sideRes gold 1000 ("Brimstone Tolls"). | substituted -> **exact** | The row carries no native bonus; `cityBonusBanks` with an empty array is inert (`BuildingCityBonusBank.Init` loops 0 bonuses). Plugin hook P1 adds +2 Spell Power to the defending hero for the battle. | Explicit: "A hero defending this city in a siege gains +2 Spell Power." | Keep the current 3 Gems/3 Crystals/3 Mercury and the Wall L1 gate. Inferno loses the substitute 1000 Gold here and gets it back from the restored Bank. |
| `Build_Bank` (stays in `banks`) | None: the shared vanilla Bank. | 1000 Gold, but named "Castle Gate". | n/a (economy) | sideRes gold 1000, unchanged. Rename it to "Bank". No layer (HoMM3 had none). | Generated: "Produces 1000 Gold daily." | Unchanged: 2500 Gold + 5 Wood + 5 Ore. |
| `Build_Resource_Depot` | **Birthing Pools**: +8 Imps a week. | cityUnitsIncrementPer h3_imp 0.3641, which floors to +8 of 22. | exact | No change. | No change. | No change. |
| `Build_Eternal_Flame` (graal) | **Deity of Fire**: +5000 Gold a day, +50% growth, and every week is the Week of the Imp (+15 Imp growth, doubling HoMM3's 15 base). | DemonGraal: allied creatures +10 Attack and +50% crit, hero crit +50%, city growth +100%. | substituted -> **exact** (decision 3) | Keep `graalType: DemonGraal`. Set `sideBonuses: [{"type":"cityUnitsIncrement","parameters":["h3_imp","22"]}]`; this is the vanilla law form ("trick_demon","4") and adds to every Imp dwelling of the side. Keep `cityBonuses` at +100%. Port scale: +15 on a 15 base is +22 on GE's 22 base. | Explicit (new `graal_inferno` template): "Every week is the Week of the Imp: +22 Imp growth in all your cities. This city's dwellings produce +100% units." | The +100% city growth is the GE grail convention (HoMM3 had +50%). GE grails drop HoMM3's 5000 Gold everywhere except Castle. This grail is weaker in battle than today's +10 Attack. |
| `Build_Beelzebubs_Hand` | OE-native (vanilla Demon): +2 Attack, once per hero. | Same. | OE-native, keep | No change. | No change. | No change. |
| `Build_Rebirth_Of_Shrine` | OE-native (vanilla Demon). | Same. | OE-native, keep | No change. | No change. | No change. |
| (none) | **Cages**: +3 Hell Hound growth (second horde). | No row. | absent (kept) | Not added. This follows the existing ADAPTATIONS rule that second hordes get no OE row. | n/a | n/a |

`source_mechanics/homm3_inferno.json` changes:
- `inferno.castle_gate`: `exact`, rows `Build_Mycelium_Roots`. Drop its forbidden text.
- `inferno.order_of_fire`: `exact`, rows `Build_Mother_Nature`.
- `inferno.brimstone_stormclouds`: `exact`, rows `Build_Resource_Depot_level_2`. The proof tier is runtime-unproven until P1 is exercised.
- `inferno.deity_of_fire`: `exact`, rows `Build_Eternal_Flame`.
- Remove the stale `castle_gate -> Build_Treasury` tag.

## 2. Tree changes

| Level | Current prerequisites | Proposed prerequisites | Why (convention) |
|---|---|---|---|
| Build_Main:2 | Tavern | none | Town Hall needs only the previous level; the HoMM3 hall gate is removed. |
| Build_Main:3 | MG1, Market | none | Same. |
| Build_Market:1 | none | Tavern | Shared economy: Market needs Tavern. |
| Build_Bank:1 | Wall L2 | Main L2 | Economy template. The Wall L2 gate belonged to Castle Gate, which moves to its own row. |
| Build_Tier_2:1 | T1 | none | Depth: T1->T2->T4->T5->T7 is 5 deep; vanilla is at most 4. T2 is a root in 5 of 6 vanilla cities, including Demon. |
| Build_Tier_5:2 | MG2 | none | Dwelling upgrades need only their own L1; only a T7 upgrade may need a Mage Guild level. |
| Build_Mycelium_Roots:1 (new) | n/a | Wall L2 | Castle Gate <- Citadel (HoMM3). It is also the vanilla Mycelium gate and is allowed for specials. |
| Build_Mother_Nature:1 (new) | n/a | MG L1 | Order of Fire <- MG1 (HoMM3). One base-level shared prerequisite. |
| Build_Tier_3/4/5/6/7:1, Depot, Depot L2, Treasury, Rebirth | as now (T1; T2; T4; MG1+T4; T5+T6; T1; Wall1; Bank+Wall1; Wall1) | unchanged | Already within the conventions: at most 2 prerequisites per dwelling L1 (Unfrozen T4 <- T1 + MG1 is the vanilla precedent for T6 <- MG1 + T4), the horde <- its own dwelling, and specials have at most 1 base-level prerequisite. |

Tool edits:
- `FACTION_LEVEL_REQS["homm3_inferno"]` gets the faction rows above.
- `Build_Main:2/3` and `Build_Market:1` are `COMMON_LEVEL_REQS` entries, so the other agents' files will make the same change.
- `ADAPTATIONS` and `docs/homm3_city_building_tree.md` need updating, since they state that the Market is a root and Town Hall <- Tavern.
- The static validator rule "every dwelling above tier 1 is gated on another dwelling" must allow tier-2 roots.

Fit:
- 36 levels. Vanilla has 34-35 and the grid has 45 cells.
- Deepest dwelling L1 chain: 4 (vanilla 4).
- The solver and `validate_homm3_city_building_tree_contract.py --static-only` must be re-run.
- buildOrders need the 2 new SIDs.

**Levels without outside prerequisites: 20 of 34 before, 23 of 36 after** (vanilla 22-23).

## 3. Plugin work

| Hook | File | Game method | Risk |
|---|---|---|---|
| P0: town-building reader. `SideHasBuilding(sideIndex, townFactionSid, section, sid, minLevel)` and `CityHasBuilding(DataObjCity, section, sid, minLevel)`. Shared by all three of my factions. | New `Homm3CityBuildingReader.cs` | Reuse the world snapshot from `Homm3FactoryLogisticsEffects.TryBuildWorld` (`objects.cityObjs`, `ownerSide`, `city.buildings.<section>[i]` with `sid`, `isConstructed`, `level`). `CountMarkets` at `:347` is the template. | Low. It reads data that is already proven. |
| P1: siege defender Spell Power. Brimstone Stormclouds +2 here; Dungeon's Guardian of Earth uses the same hook at +12. Data-driven by `{citySid, buildingSid, value}`. | New `Homm3TownSiegeDefenseRuntime.cs` | Battle-start `TransferBattle` entry, the same point `Homm3CastleEliteStrategemRuntime` uses. Siege test: `arenaLogicSid` contains "siege" (`:269`). Find the besieged city from the battle's map object. Through P0, if it has the building, add `spellPower` to the defending side's hero for this battle only. | Medium. Two unknowns: (1) which `TransferBattle` field carries the besieged city id; (2) a battle-scoped hero stat write that is not persisted. Verify both against the live interop, not the old managed decompile. |
| P2: Castle Gate destinations (only if decision 2 is "filter"). | New `Homm3InfernoCastleGateRuntime.cs` | Postfix on `BhMyceliumRoots` list fill (the `citiesList` loop that calls `poolViewElements[i].Show`): hide or disable cities without `Build_Mycelium_Roots`. Prefix on `CmdMyceliumRootsApply.Apply`: refuse a destination without the building. The prefix covers AI and replay too. | Low-medium. A UI pool index must stay aligned with `citiesList`, so disable entries rather than remove them. Nature's own Mycelium (vanilla Nature towns) must stay untouched; key the hook on the source city being `homm3_inferno_city`. |

Tooling:
- **Overlay** (`apply_release_core_overlay.py` city normalizer): add the new rows, move the Depot L2 row to `cityBonusBanks`, and replace the graal side bonus.
- **Descriptions** (`homm3_city_building_descriptions.py`):
  - a plugin-text path for rows with empty `cityBonusBanks` bonuses (explicit text keyed by `xHomm3SourceMechanic`);
  - a Castle Gate variant of the `mycelium` sentence;
  - a `graal_inferno` template (DemonGraal with a `cityUnitsIncrement` side bonus).
- **Visual map**: `building_layer_map.json` re-points `tbinext1` to `Build_Mycelium_Roots` and drops `Build_Artifact_Market`.

## 4. Owner decisions

1. **Economy slot vs special.** Option A (recommended): restore the plain Bank on `Build_Bank` and give Castle Gate and Order of Fire their own rows. Option B: move `Build_Bank` into `myceliumRoots`, so Inferno loses the 1000-Gold Bank (the Fortress and Conflux precedent). **Recommend A**: the shared economy stays identical to vanilla, and gold is net unchanged after Brimstone's substitute gold is removed.
2. **Castle Gate reach.** Native: any of your cities. HoMM3: only your Castle Gate towns (plugin P2). **Recommend the P2 filter**: it is exact, and any-town teleport for a 5000-Gold building is stronger than both HoMM3 and its price.
3. **Deity of Fire strength.** The exact Week of the Imp (+22 Imp growth in all your cities, plus +100% city growth) replaces today's +10 Attack / +50% crit battle package. **Recommend exact.** The +100% growth is the real grail power in every GE town. If it plays weak, add Gold to the grail later rather than keep the demon battle package.
