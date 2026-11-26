# Fortress (`homm3_fortress_city`) building pass

Source of current rows: installed GE Core.zip `DB/objects_logic/cities/homm3_fortress_city.json` (extract in `V:/olden_port_work/building_pass/claude_shf/fortress_city.json`). Mechanics rows: `custom_factions/source_mechanics/homm3_fortress.json`.

## 1. Special buildings

| SID | Source building (HoMM3/HotA effect) | Current effect | Status | Proposed build | Player text | Cost/power note |
|---|---|---|---|---|---|---|
| Build_Spring_of_Life (grail slot) | Carnivorous Plant: +10 Attack and +10 Defense to the hero defending this town in a siege (plus the standard grail growth). | "Carnivorous Plant": NatureGraal. Empire-wide `cityUnitsIncrement all 1` (side) + this city `cityUnitsIncrementPer all 1.0`. | Substituted | Graal row keeps `cityBonuses: [{"type":"cityUnitsIncrementPer","parameters":["all","1.0"]}]` and `sideBonuses: []`. The +10/+10 comes from `Homm3TownSiegeDefenseRuntime` (section 3), keyed on `Build_Spring_of_Life:1`. Mechanics row becomes exact. | "The hero defending this city gets +10 Attack and +10 Defense. This city's dwellings produce +100% units." | Grail cost unchanged. It loses the empire-wide +1 growth for the HoMM3 siege bonus and keeps +100% city growth (owner decision 2). Native fallback: graal `sideBonuses` heroStat offence 10 + defence 10 with `battleType forCity`, `actionArea allied`; that covers all your cities, not just this one. |
| Build_Mother_Nature | Glyphs of Fear: +2 Defense to the hero defending this town in a siege. Needs Fort. 1000 gold. | "Glyphs of Fear": heroBonusBanks `moral 1` (+1 Morale to visiting heroes). Substituted. | Substituted | Section `banks`, `bonuses: []`, explicit text override. Effect: `Homm3TownSiegeDefenseRuntime` table `Build_Mother_Nature:1` -> defence +2. Mechanics row exact. The existing forbidden "fear aura" / "enemy morale" stay valid. | "The hero defending this city gets +2 Defense." | 1000 gold kept (the HoMM3 price). |
| Build_Mycelium_Roots | Blood Obelisk: +2 Attack to the hero defending this town in a siege. Needs Glyphs of Fear. 1000 gold. | "Hydra Marsh": `cityUnitsIncrementPer h3_hydra 1.01` (+1 Hydra), <- T7:1. Substituted; it replaced Blood Obelisk. | Wrong building | Restore Blood Obelisk. Section `banks`, `bonuses: []`, text override. Hook table `Build_Mycelium_Roots:1` -> offence +2. Prerequisite `Build_Wall:1`, not Glyphs, to avoid a special-on-special chain. Mechanics row exact; drop the "Blood Obelisk" forbidden text. | "The hero defending this city gets +2 Attack." | 1000 gold kept. Removes an invented +1 T7 growth (owner decision 1). |
| Build_Bank | Cage of Warlords: +1 Defense to each visiting hero, once. | heroBonusBanks `defence 1`, <- Main:2 + Mother_Nature. Row says substituted. | Effect exact, row stale | No data change to the effect. Reclassify the mechanics row as exact. Tree: prerequisite Main:2 only (section 2). | Computed (unchanged). | Unchanged (1000 gold). |
| Build_Resource_Depot_level_2 | Captain's Quarters: +6 Gnoll growth. | `cityUnitsIncrementPer h3_gnoll 0.4293`, <- T1:1. | Exact | No change. | Unchanged. | Unchanged. |
| Build_Resource_Depot | Resource Silo: +1 wood, +1 ore. | Same, 5000 gold + 5 ore. | Exact | No change. | Unchanged. | Unchanged. |
| Build_Treasury | Blacksmith (sells the First Aid Tent, a war machine). | "Blacksmith": 2000 gold, <- Bank + Wall:1. Row `fortress.field_infirmary` substituted, with a stale "Knowledge bonus" reason. | Substituted (honest) | Keep, per the 2026-10-01 user decision (Treasury = "Blacksmith"). Rewrite the reason to "Olden Era has no war machines; the slot is the shared Treasury." | Computed (unchanged). | Unchanged. |

Specials changed: 3 (Carnivorous Plant, Glyphs of Fear, Blood Obelisk). Cage of Warlords and Field Infirmary get row or reason fixes only.

## 2. Tree changes

Slot roles:
- `Build_Bank` holds a special (Cage). Fortress therefore has no economic Bank, and the economy template's Bank references fall to Main:2.
- `Build_Treasury` is the economic Treasury.

| Level | Current prerequisites | Proposed prerequisites | Why (convention) |
|---|---|---|---|
| Build_Main:2 | Main:1, Tavern:1 | Main:1 | Town Hall L2 needs only the previous level; removes a HoMM3 gate. |
| Build_Main:3 | Main:2, Magic_Guild:1, Market:1 | Main:2 | Removes the HoMM3 Capitol gate. |
| Build_Market:1 | (none) | Tavern:1 | Vanilla: Market needs Tavern. |
| Build_Tier_1:2 | Tier_1:1, Tavern:1 | Tier_1:1 | Dwelling upgrades need only their own L1. |
| Build_Tier_5:2 | Tier_5:1, Resource_Depot:1 | Tier_5:1 | Same. |
| Build_Treasury:1 | Bank:1 (Cage, a special), Wall:1 | Main:2, Wall:1 | Treasury should not depend on a special. Main:2 stands in for the absent economic Bank at the same depth. |
| Build_Bank:1 (Cage) | Main:2, Mother_Nature:1 | Main:2 | Specials take at most 1 base-level shared prerequisite; no special chain. |
| Build_Mycelium_Roots:1 | Tier_7:1 | Wall:1 | It becomes Blood Obelisk: HoMM3 gates it on Fort (via Glyphs); one base-level shared prerequisite. |

Kept on purpose:
- T2:1 <- T1, T3:1 <- T1, T4:1 <- T3, T5:1 <- T2 + T3, T6:1 <- T2 and T7:1 <- T4 + T6: HoMM3 flavour, at most 2 base-level dwelling prerequisites.
- Captain's Quarters <- T1:1, because a horde needs its dwelling.
- Glyphs <- Wall:1.
- Depot <- Market (there is no economic Bank to add).

The layout loses edges and adds no nodes, so it still fits columns 0..8 x 5 rows.

Levels without outside prerequisites (of 33): 16 before, 19 after.

## 3. Plugin work

1. **`Homm3TownSiegeDefenseRuntime.cs`** (new, `Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/`). Shared with Stronghold.
   - Hook: prefix on `BattleLogic.Init(int, TransferBattle, bool, bool)` (symbol `GameSymbols.DraconicDominion.BattleLogicInit`, already patched by `Homm3BattleStartStatusLawRuntime.cs`).
   - On `battleType == ForCity` with a defending hero, resolve the `WoCity` from `battleControllerId`.
   - Use the new per-city reader `Homm3TownBuildingReader.HasBuilding(WoCity, sid, level)` (built on `Homm3ConstructionNativeAdapter`).
   - Add the summed stats to the transfer hero's `heroStat`. Fortress table:
     - Glyphs (`Build_Mother_Nature:1`) defence +2;
     - Blood Obelisk (`Build_Mycelium_Roots:1`) offence +2;
     - Carnivorous Plant (`Build_Spring_of_Life:1`) offence +10, defence +10.
   - Risk: medium.
     - Confirm the defender side index.
     - Confirm that the simulated / quick-combat path goes through `BattleLogic.Init`; otherwise also patch the `BhSimulatedBattle` entry.
     - Check symbol drift.
     - A garrison-only defence gets nothing (same as HoMM3).
     - The AI does not value the buildings.
2. **Tools:**
   - `homm3_city_building_descriptions.py` needs a graal shape for "growth-only + explicit text" and text overrides for Glyphs of Fear and Blood Obelisk.
   - The tree validator must accept Treasury <- Main:2 + Fort for towns whose `Build_Bank` is a special.
   - The Town Hall / City Hall gate removal is shared by all 12 towns.

## 4. Owner decisions

1. **Hydra Marsh vs Blood Obelisk.** Restoring Blood Obelisk removes the invented +1 Hydra growth.
   - Recommendation: restore Blood Obelisk. It is the source building, and Captain's Quarters already covers Fortress's horde.
2. **Carnivorous Plant scope.** Option A: this town only (plugin hook, exact HoMM3). Option B: every city you defend (native graal bonus, no plugin). Either way, the empire-wide +1 growth is dropped.
   - Recommendation: A, since the hook exists anyway for Glyphs and Obelisk. Option B is the fallback if the hook slips.
3. **Treasury prerequisite with no economic Bank.** Option A: Main:2 + Wall:1 (needs a validator change). Option B: keep Cage + Wall:1.
   - Recommendation: A. Option B leaves an economic building behind a hero-stat special.
