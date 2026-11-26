# Factory building pass (2026-11-22)

Scope: `homm3_factory_city`, as installed in GE `Core.zip`. HotA source: Factory town buildings.

How the slots map to roles:
- Economy template: `Build_Bank` ("Town Bank", 1000 gold), `Build_Treasury` ("Blacksmith", 2000 gold), `Build_Resource_Depot` (crystals) and `Build_Artifact_Market` (HotA Artifact Merchants).
- Specials: `Build_Resource_Depot_level_2` (Pen horde), `Build_Mother_Nature` (Mana Generator) and `Build_Golden_Calf` (Lightning Rod grail).
- Missing: the HotA Factory Bank (the loan building) has no row.
- `Build_Factory_Gantry` is dwelling 8.
- The Logistics Network design (`docs/factory_logistics_network_design.md`) owns adventure-map mines and dwellings only. It owns no town building; its Trade Contracts postfix on `GetMarketsCount` is the one shared hook point.

## 1. Special buildings

| SID | Source building (HoMM3/HotA effect) | Current effect | Status | Proposed build | Player text | Cost/power note |
|---|---|---|---|---|---|---|
| `Build_Mother_Nature` | Mana Generator: in any siege defense of this town, the defending hero gets +20 spell points. Points left unspent are lost after the combat. 1000 gold, 5 ore; requires Fort. | `heroBonusBanks` `heroStat intelligence 1` ("Mana Dynamo", +1 Knowledge to visitors) | substituted (donor-shaped) | Plugin. Move the row to `banks` with no income bonus, or to `cityBonusBanks` with empty `bonuses`, so it does nothing natively. Hook: the transfer-battle prefix (the pattern of `Homm3CastleEliteStrategemRuntime`, `arenaLogicSid` contains "siege"). When the defended town is a Factory with `Build_Mother_Nature` built, add 20 to the defending hero's current mana at battle start, whether the hero is garrisoned or visiting. At battle end, remove whatever is left of those 20 (subtract min(20, mana above the pre-battle value)). No native bonus says "current mana in a siege": `manaBonus` is permanent maximum mana and `heroMana` is a global week buff with no parameters. | "In a siege of this town, the defending hero gains 20 mana for the battle. Mana not spent is lost when the battle ends." | Change the cost to the HotA 1000 gold, 5 ore (now 3 gems, 3 crystals, 3 mercury). Power matches the source. |
| `Build_Golden_Calf` (graals) | Lightning Rod: +5000 gold per day and growth x1.5. In every battle with a friendly hero, at round 1 before the first friendly turn, lightning deals 7 x (4 + number of buildings in this town, upgrades not counted) damage to each enemy unit. Several Rods add up. | HumanGraal (1000 gold plus 1 of each resource, city +100%) | substituted (combat clause missing) | Keep the HumanGraal bonuses. Plugin: at round 1 (`GameSymbols.BattleEventLaws.RoundStartedDispatcher`, which `Homm3UnitKitBattleHooks.PostfixRoundStarted` already resolves), for each side with a hero, sum over every owned Factory town with `Build_Golden_Calf`: 7 x (4 + that town's built distinct building SIDs, extra levels not counted). Hit every enemy stack once for that total, through the nested-damage path (`NativeCombatWriteGateway.TryInvokeRedirectedDamage`, as `brand_splash` uses), with no Defense applied. | "The owner's cities produce 1000 Gold and 1 of each other resource daily. This city's dwellings produce +100% units. At the start of every battle fought by your heroes, lightning strikes each enemy stack for 7 x (4 + buildings in this city) damage." | Grail-strength. The text should show the live total if the description generator can't compute it; otherwise the formula as written. |
| New row: Bank (proposed `Build_Factory_Loan_Bank`, `cityBonusBanks` with empty bonuses) | Bank: take a 2500 gold loan at once; town gold income is -500 per day for 5 days. 500 gold, 5 ore; no requirement. | None (absent). The economic `Build_Bank` is named "Town Bank". | absent | Plugin (`Homm3FactoryLoanBankRuntime.cs`). The trigger is owner decision 1. On the loan: one-time +2500 gold to the side (the `sideOneTimeAddRes` amount laws use, written by the plugin), then -500 gold at each of the next 5 day starts, clamped at 0 gold. Store the debt per town in the save. Only one loan per town at a time. Check against the HotA source whether a new loan is allowed once the debt is repaid. Rename the economic `Build_Bank` to "Counting House" or similar, so the two do not share the name "Bank". Delete the leftover row-less `Intelligence_Academy` and `Training_Range` text keys. | "Lends you 2500 Gold at once. This town then pays back 500 Gold daily for 5 days." | HotA cost 500 gold, 5 ore. Net-zero gold; a tempo tool. |
| `Build_Artifact_Market` | Artifact Merchants (requires Marketplace) | Standard Artifact Market | exact | No change | unchanged | none |
| `Build_Resource_Depot` | Resource Silo: +1 crystal | +1 crystal | exact | No change | unchanged | none |
| `Build_Resource_Depot_level_2` | Pen: +3 Armadillos per week | `cityUnitsIncrementPer h3_armadillo 0.43` | exact | No change | unchanged | Tree gate: see section 2. |
| `Build_Treasury` | HotA Blacksmith (Ammo Cart purchase) | Economic Treasury named "Blacksmith" (2026-10-01 decision) | out of scope | No change. War-machine purchase stays unported. | unchanged | none |

## 2. Tree changes

| Level | Current prerequisites | Proposed prerequisites | Why (convention) |
|---|---|---|---|
| Build_Main:2 | Tavern | none | Town Hall L2 needs only the previous level. |
| Build_Main:3 | MG1 + Market | none | Town Hall L3 needs only the previous level. |
| Build_Market:1 | none | Tavern | Market needs Tavern. |
| Build_Resource_Depot:1 | Market | Market + Bank | Resource Depot needs Market + Bank. |
| Build_Tier_5:2 | MG1 | none | A dwelling upgrade needs only its own L1. |
| Build_Tier_6:2 | Market | none | A dwelling upgrade needs only its own L1. |
| Build_Factory_Gantry:2 | Market | none | A dwelling upgrade needs only its own L1. The Gantry is dwelling 8, not T7, so the Mage Guild exception does not apply. |
| Build_Tier_7:1 | T5 + MG1 | keep | A T7 L1 may need a Mage Guild level (vanilla uses MG2). |
| Build_Tier_7:2 | MG2 | keep | The T7 upgrade is allowed one Mage Guild level. |
| Build_Factory_Gantry:1 | T6 | keep | 1 base dwelling. |
| Build_Mother_Nature:1 (Mana Generator) | Wall1 | keep | 1 base shared building; HotA requires the Fort. |
| Build_Resource_Depot_level_2:1 (Pen) | T3 | T3 (keep; owner decision 3) | A horde gated on its own base dwelling; see Cove decision 2. |
| New loan Bank | none | none | HotA has no requirement. |

Levels without an outside prerequisite: 16 of 35 before; 21 of 36 after (the new loan Bank counted). Rerun the layout solver for the extra node. Factory already carries the extra Gantry chain, so 36 levels must fit columns 0..8 in 5 rows.

## 3. Plugin work

1. **Town building reader.** `Homm3CityBuildingReader.cs`, shared and specified in `cove.md` section 3. It provides `TownLevel`, `SideTownCount`, `DefendedTown` and the distinct-built-building count for the Lightning Rod. Risk: low.
2. **Siege-defense battle start**, for the Mana Generator (and Bulwark's Forebears).
   - New `Homm3TownSiegeDefenseRuntime.cs`. Reuse the transfer-battle prefix pattern from `Homm3CastleEliteStrategemRuntime.cs` (`isSiege` from `arenaLogicSid`; side types `Type_Hero` / `Type_Garnison`).
   - Needs two traces: which town is defended (from the transfer battle or the defender's map object), and the battle hero's current-mana field. No mana write path exists in the plugin today.
   - Risk: medium. The mana field trace is new. The end-of-battle removal must run even on retreat or surrender.
3. **Lightning Rod round-1 strike.**
   - In `Homm3UnitKitBattleHooks.cs` round start (or a new `Homm3FactoryLightningRodRuntime.cs` that subscribes to it): when the round number is 1, run the strike before the first action.
   - Damage goes through `NativeCombatWriteGateway.TryInvokeRedirectedDamage`.
   - Risk: medium. The nested-damage path is build-only and runtime-unproven. A kill at round start must update the turn queue natively. The AI and the damage forecast will not see it.
4. **Loan Bank.**
   - New `Homm3FactoryLoanBankRuntime.cs`. The trigger is either a construction-complete postfix (the construction path `Homm3CustomConstructionLawDiagnostics` already probes) or a town-screen action.
   - Repayment runs from the day-start hook the logistics runtime uses. The debt lives in plugin save state.
   - Risk: medium with the construction trigger; high with a town-screen button (no proven building-click UI).

## 4. Owner decisions

1. **Loan Bank trigger.** One loan granted when the Bank finishes building, or a repeatable "take a loan" action in the town screen? Recommendation: the construction trigger now (no new UI, save-safe). Add the repeatable action later, if HotA's repeat rule matters in play.
2. **Mana Generator cost.** Recommendation: the HotA 1000 gold, 5 ore. The current 3/3/3 rare-resource cost was priced for the +1 Knowledge substitute, and Wall L1 already gates it.
3. **Horde gate on the Pen** (cross-faction; see Cove decision 2). Recommendation: keep the Pen gated on the Tier 3 dwelling.
