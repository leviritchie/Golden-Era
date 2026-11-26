# Stronghold (`homm3_stronghold_city`) building pass

Source of current rows: installed GE Core.zip `DB/objects_logic/cities/homm3_stronghold_city.json` (extract in `V:/olden_port_work/building_pass/claude_shf/stronghold_city.json`). Mechanics rows: `custom_factions/source_mechanics/homm3_stronghold.json`.

## 1. Special buildings

| SID | Source building (HoMM3/HotA effect) | Current effect | Status | Proposed build | Player text | Cost/power note |
|---|---|---|---|---|---|---|
| Build_Spy_Network (grail slot) | Warlords' Monument: +20 Attack to the hero defending this town in a siege (plus the standard grail income and growth). | "Escape Vault": DungeonGraal, `cityRadiusView 999` (removes fog) + `cityUnitsIncrementPer all 1.0`. Row `stronghold.escape_tunnel` substituted. The real grail is missing. | Wrong effect | Graal row keeps only `cityBonuses: [{"type":"cityUnitsIncrementPer","parameters":["all","1.0"]}]` and `sideBonuses: []`. The +20 Attack comes from the plugin hook `Homm3TownSiegeDefenseRuntime` (section 3), keyed on this city having `Build_Spy_Network:1`. Rename to "Warlords' Monument". Drop the fog reveal. New mechanics row `stronghold.warlords_monument` = exact. | "The hero defending this city gets +20 Attack. This city's dwellings produce +100% units." | Same grail cost. +20 Attack in home sieges replaces the map-wide reveal; it keeps +100% growth, so it stays grail-strength. Native fallback: graal `sideBonuses [{"type":"heroStat","receiverAllegiance":"ally","battleType":"forCity","actionArea":"allied","parameters":["offence","20"]}]`, but that covers every one of your cities, not just this one. |
| Escape Tunnel (no slot) | Escape Tunnel: a hero defending this town may retreat. HoMM3 needs a Fort; 2000 gold. | Its name sits on the grail slot ("Escape Vault"), but the effect is fog removal. | Missing | Verified in decomp: `BattleCompletionUtility.CanEscape` returns false whenever the loser's world side owns the battle's city (`battleType != OnMap` and `worldSide == battleObject.side`). OE therefore bans defender retreat exactly as HoMM3 does, so the source effect is real and needs the hook `Homm3TownEscapeTunnelRuntime` (section 3). Placement is owner decision 2; the recommendation is to attach the rule to Stronghold's `Build_Wall:1`. Mechanics row `stronghold.escape_tunnel` becomes exact. | Added to the Stronghold Fort text: "Heroes defending this city may retreat from battle." | HoMM3 cost is only 2000 gold, so folding it into the Fort costs nothing visible. A new SID would need scene art and a layout slot. |
| Build_Resource_Depot_level_2 (proposed Freelancer's Guild) | Freelancer's Guild: sell creatures for resources at the Marketplace rate. HoMM3 needs a Marketplace. | "Resource Silo II": +1 ore (OE-only; no HoMM3 counterpart). Freelancer's Guild currently rides the `Build_Bank` income row (`stronghold.freelancers_guild` substituted). | Substituted | Move Freelancer's Guild here (owner decision 1). Row: section `banks`, `bonuses: []`, prerequisite `Build_Market:1`, plus an explicit text override in `homm3_city_building_descriptions.py`. Effect: plugin window `Homm3StrongholdFreelancersGuildWindow` (section 3). Each creature is valued at its recruit gold cost × 1/2. The player takes that gold, or converts it at the town's native Marketplace sell rate into any resource. Mechanics row becomes exact; remove "Freelancer" and "exchange creatures" from `forbiddenPlayerText`, since the building's own name hits them. | "Allows you to sell creatures from the city garrison or a visiting hero for gold or resources at the Marketplace rate." | Cost: keep 3 gemstones / 3 crystals / 3 mercury, or use HoMM3's 1000 gold. Loses Silo II's +1 ore per day. Selling at half value plus the market spread keeps it a liquidity tool, not a profit loop. |
| Build_Bank | Not a HoMM3 Stronghold building. In OE it is the shared economic Bank. | "Muster Yard": `sideRes gold 1000`, <- Main:2. Tagged as Freelancer's Guild (substituted). | Mis-tagged | Keep it as the economic Bank (vanilla `Build_Bank` = `sideRes gold 1000`). Retag it as shared economy and remove the Freelancer's Guild tag. Rename to the vanilla Bank name if desired; "Muster Yard" is acceptable flavour. | Computed by the tool (unchanged). | Unchanged. |
| Build_Resource_Depot | Resource Silo: +1 wood, +1 ore per day (Stronghold, like Castle, Necropolis and Fortress). | "Resource Silo": +1 crystals; row marked exact. | Wrong | `banks` bonuses `[{"type":"sideRes","parameters":["wood",1]},{"type":"sideRes","parameters":["ore",1]}]` (same shape as installed Fortress). Owner decision 3. | Computed: "+1 Wood and +1 Ore per day." | Fortress charges the HoMM3 price, 5000 gold + 5 ore, for this effect. Stronghold currently charges 2000 gold; raise it to 5000 + 5 ore for parity. |
| Build_Treasury | Ballista Yard (a war machine) / Blacksmith. | "Blacksmith": 2000 gold, <- Bank + Wall:1. | Substituted (honest) | Keep, per the 2026-10-01 user decision (Treasury = "Blacksmith" everywhere). Ballista Yard cannot exist because OE has no war machines. Record it as `substituted`, reason "Olden Era has no war machines; the slot is the shared Treasury." | Computed (unchanged). | Unchanged. |
| Build_Lyceum | Mess Hall: +8 Goblin growth. | `cityUnitsIncrementPer h3_goblin 0.2967` (+8). | Exact | No change. | Unchanged. | Unchanged. |
| Build_Gymnasium | Hall of Valhalla: +1 Attack to each visiting hero, once. | heroBonusBanks `offence 2` (deliberate +2). | Exact (owner value) | No change. | Unchanged. | Unchanged. |

Specials changed: 4. Warlords' Monument replaces Escape Vault, Escape Tunnel is added, Freelancer's Guild becomes real (and moves slot), and the Resource Silo effect is corrected. Bank and Treasury get retag/reason fixes only.

## 2. Tree changes

| Level | Current prerequisites | Proposed prerequisites | Why (convention) |
|---|---|---|---|
| Build_Main:2 | Main:1, Tavern:1 | Main:1 | Town Hall L2 needs only the previous level. This removes a HoMM3 Town Hall gate. |
| Build_Main:3 | Main:2, Magic_Guild:1, Market:1 | Main:2 | Same; removes the HoMM3 Capitol gate. |
| Build_Market:1 | (none) | Tavern:1 | Vanilla: Market needs Tavern. |
| Build_Tier_2:2 | Tier_2:1, Tier_1:2 | Tier_2:1 | Dwelling upgrades need only their own L1; no upgraded-dwelling prerequisite. |
| Build_Tier_4:2 | Tier_4:1, Magic_Guild:1 | Tier_4:1 | Non-T7 upgrades take no extra prerequisite. |
| Build_Resource_Depot:1 | Market:1 | Market:1, Bank:1 | Vanilla: Depot needs Market + Bank (Bank is economic here). |
| Build_Resource_Depot_level_2:1 | Resource_Depot:1 | Market:1 | The slot becomes Freelancer's Guild, a special with one base-level shared prerequisite (the HoMM3 requirement). |

Kept on purpose:
- T2:1 <- T1, T3:1 <- T1, T4:1 <- T3, T5:1 <- T2, T6:1 <- T4 and T7:1 <- T5 are the HoMM3 dwelling flavour. Each has one base-level dwelling prerequisite, within vanilla's 0-2.
- Lyceum (Mess Hall horde) <- T1:1, because a horde needs its dwelling.
- Gymnasium (Valhalla) <- Wall:1, a single base-level shared prerequisite.
- Treasury <- Bank + Wall:1 already matches vanilla.

The layout loses edges and gains no nodes, so it still fits columns 0..8 x 5 rows. Freelancer's Guild moves next to the Market.

Levels without outside prerequisites (of 33): 16 before, 19 after. The remaining gap to vanilla's 22-23 comes from the HoMM3 dwelling chain and the horde, Valhalla and Freelancer gates.

## 3. Plugin work

1. **`Homm3TownSiegeDefenseRuntime.cs`** (new, `Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/`). Shared with Fortress.
   - Hook: prefix on `BattleLogic.Init(int, TransferBattle, bool, bool)`. Reuse the symbol `GameSymbols.DraconicDominion.BattleLogicInit`, which `Homm3BattleStartStatusLawRuntime.cs` already patches.
   - When `transferBattle.battleType == EBattleType.ForCity` and the defending side has a `hero`, resolve the city: `BattleCompletionUtility.GetBattleObject(battleControllerId)` as `WoCity`.
   - Read built levels with a small reader, `Homm3TownBuildingReader.HasBuilding(WoCity, sid, level)`, built on `Homm3ConstructionNativeAdapter` (`BuildingIdentityInfo`). No per-city reader exists yet; the law reader is side-level.
   - Add the data table (Stronghold `Build_Spy_Network:1` -> offence +20) to the transfer hero's `heroStat`. This is a per-battle copy, so nothing is permanent.
   - Risk: medium.
     - Confirm the defender index on the current build.
     - Confirm that quick combat and AI-vs-AI (`BhSimulatedBattle`) also pass through `BattleLogic.Init`; otherwise also patch the simulate entry.
     - Check symbol drift.
     - The AI does not value the building.
2. **`Homm3TownEscapeTunnelRuntime.cs`** (new).
   - Hook: postfix on `BattleCompletionUtility.CanEscape(Logic, int)`.
   - If the result is false, `battleType == ForCity`, the loser is a hero (`Type_Hero`) whose world side owns the city, and the city has the configured building (Stronghold `Build_Wall:1`, or the chosen SID), return true.
   - The method is used by the retreat command (`SideCommands`) and the simulated battle (`BhSimulatedBattle`), so both follow automatically.
   - Leave `CanCapitulate` unchanged (HoMM3 Escape Tunnel is retreat only).
   - Risk: high. The post-retreat path for a city owner has never run in vanilla. Test that the hero goes to the tavern pool, the town falls to the attacker, and the garrison is handled correctly.
3. **`Homm3StrongholdFreelancersGuildWindow.cs`** (new; precedent `Homm3DungeonWarCaptivesWindow.cs`).
   - Opens from the building's city-screen click.
   - Lists stacks in the city garrison and the visiting hero (it cannot sell the last stack of an army).
   - Pays gold, or converts gold to a resource through the native market rate (reuse the market's rate calculation, used by `markets` section objects).
   - Risk: medium (new UI, IL2CPP list interop).
4. **Tools (not plugin):**
   - `homm3_city_building_descriptions.py` needs a graal shape for "growth-only + explicit text" and text overrides for the plugin-only rows (Freelancer's Guild; the Escape Tunnel line on Stronghold's Fort).
   - The tree validator (`validate_homm3_city_building_tree_contract.py`) must drop its Town Hall <- Tavern and City Hall <- MG1 + Market requirements. These changes are shared by all 12 towns.

## 4. Owner decisions

1. **Where Freelancer's Guild lives.** Option A: replace the OE-only Silo II (`Build_Resource_Depot_level_2`) and keep the 1000-gold Bank. Option B: take the Bank slot and lose the income.
   - Recommendation: A. Stronghold keeps the shared economy, Treasury <- Bank + Wall:1 stays valid, and Fortress/Conflux already use this slot for specials.
2. **Escape Tunnel placement.** Option A: Stronghold's Fort (Wall L1) grants the retreat rule. Option B: a new special SID (needs scene art). Option C: leave it unbuilt (stays substituted).
   - Recommendation: A. It is cheap in HoMM3, needs a Fort there, and adds no node.
3. **Resource Silo yield.** Option A: correct it to the HoMM3 +1 wood +1 ore (5000 gold + 5 ore). Option B: keep the installed +1 crystals, which feeds Behemoth costs but is not the source effect.
   - Recommendation: A.
