# Rampart (`homm3_rampart_city`) building pass

Source of current rows: installed GE `Core.zip`, `DB/objects_logic/cities/homm3_rampart_city.json` (dumped 2026-11-22). Text tokens: `Lang/english/texts/cities.json`. HoMM3 effects are from the SoD/HotA building table. The port scales resources 1:1, and HoMM3 sulfur maps to the port's rare set (mercury, crystals, gemstones).

## 1. Special buildings

| SID | Source building (HoMM3/HotA effect) | Current effect | Status | Proposed build | Player text | Cost/power note |
|---|---|---|---|---|---|---|
| `Build_Bank` (now "Mystic Pond") | Mystic Pond: 1–4 units of one random rare resource each week. | A `banks` row producing 1000 gold a day (`rampart.mystic_pond`, substituted), needs Main L2. | substituted (donor) | Make it the shared-economy **Bank**: keep `sideRes gold 1000` and Main L2, use the vanilla Bank name and text. Move the Pond to the new row below. | "Bank" / "Produces 1000 Gold daily." | Unchanged vanilla Bank. |
| new `Build_Mystic_Pond` (`banks` row, empty `bonuses`, plugin carrier) | Mystic Pond, as above. | none | absent → **exact** | Plugin hook 4 (weekly town income). At the start of each week, every owned Rampart town with this row adds 1–4 (uniform) of one random resource from mercury / crystals / gemstones to its owner. Seed the roll from the game RNG so it is deterministic per save. | "Mystic Pond" / "Produces 1–4 units of a random rare resource each week." | HoMM3 value, 1:1 (about 2.5 rare a week, roughly 0.35 a day; far below the 1000-gold substitute it replaces). Cost: HoMM3 2000 gold + 2 each of mercury/crystals/gemstones. |
| `Build_Mother_Nature` (Fountain of Fortune) | Fountain of Fortune (Mystic Pond upgrade): +2 Luck to the town's troops when defending a siege. | `heroBonusBanks` `heroStat spellPower 2` once per visiting hero (`rampart.fountain_of_fortune`, substituted), needs Bank. | substituted (donor) → **exact** | Turn it into a `banks` carrier with empty bonuses: move it out of `heroBonusBanks` and drop the Spell Power. Plugin hook 2 (siege-defence town bonus) gives the defending side `luck +2` in a siege of this town. | "Fountain of Fortune" / "Troops defending this town in a siege gain +2 Luck." | HoMM3 value. Keep the current cost (5000 gold). That is high for a siege-only effect; HoMM3 asks 1500 gold + 10 crystals, which is the cheaper option if the owner prefers it. |
| new `Build_Rampart_Treasury` (`banks` carrier; mint the SID, because `Build_Treasury` is the economy slot) | Treasury: +10% of the gold held at the start of each week. Needs Miners' Guild. | Missing as an effect. Its name sits on the Artifact Market slot ("Treasury" / "Allows artifacts to be traded."). | absent → **exact** | Plugin hook 4 (weekly town income): at week start, the owner gains 10% of current gold for each owned Rampart town with this row, rounded down. HoMM3 stacks it per Treasury town. | "Treasury" / "Each week, adds 10% of your current Gold to your treasury." | HoMM3 value. It is strong with a large hoard; see owner decision 1 for a cap. Cost: HoMM3 5000 gold + 5 ore. |
| `Build_Artifact_Market` (now named "Treasury") | HoMM3 Rampart has no Artifact Merchants; this is the shared-economy Artifact Market. | Artifact trading, needs Market + Miners' Guild. | economy slot with a borrowed name | Keep the effect. Rename it to the vanilla "Artifact Merchants" so the Treasury name goes to the real Treasury row. | "Artifact Merchants" / "Allows artifacts to be traded." | unchanged |
| `Build_Resource_Depot_level_2` (Miners' Guild) | +4 Dwarves a week. | `h3_dwarf 0.401`, needs T2. | exact | No change. | unchanged | unchanged |
| `Build_Mycelium_Roots` (Dendroid Saplings) | +2 Dendroid Guards a week. | `h3_dendroid_guard 0.67`, needs T5. | exact | No change. | unchanged | unchanged |
| `Build_Spring_of_Life` (Spirit Guardian grail) | Spirit Guardian: +2 Luck for all the owner's heroes, plus grail growth and gold. | NatureGraal: side `cityUnitsIncrement all 1` and city `cityUnitsIncrementPer all 1.0`. | substituted (vanilla Nature grail effect) → **exact** | Replace the side `cityUnitsIncrement all 1` with graal `sideBonuses: heroStat ["luck","2"]` (native; graal side bonuses accept `heroStat`). Keep `cityUnitsIncrementPer all 1.0`. Add a new `rampart.spirit_guardian` exact row. | "Spirit Guardian" / "All your heroes gain +2 Luck. This city's dwellings produce +100% units." | Grail-strength, mirroring the Castle Colossus (+2 Morale side-wide). |
| `Build_Treasury` (named "Blacksmith") | Blacksmith sells an Ammo Cart (war-machine purchase). | The shared-economy Treasury: 2000 gold a day. | economy slot with a borrowed name | Keep the effect. In Castle and Tower this slot is renamed "Treasury". Here that name belongs to the HoMM3 special above, so this slot keeps "Blacksmith" until a non-clashing vanilla-style name is picked. That is a text-only follow-up, not a mechanic. | "Blacksmith" / "Produces 2000 Gold daily." (unchanged) | unchanged |

Text: Mystic Pond, Fountain of Fortune and the Treasury special need explicit descriptions (plugin-only). Spirit Guardian is computed once `heroStat luck` on a graal has a template.

Art: `Build_Mystic_Pond` and `Build_Rampart_Treasury` need layer bindings in the Rampart 3D catalog (`tbrmspec`, `tbrmext0` and the other existing `tbrm*` layers are the candidates) and must be declared in source_mechanics `currentRows` so the overlay keeps them.

## 2. Tree changes

| Level | Current prerequisites | Proposed prerequisites | Why (convention) |
|---|---|---|---|
| Main L2 | Tavern | none | Town Hall L2/L3 need only the previous level. |
| Main L3 | MG L1, Market | none | Same. |
| Market | none | Tavern | Market needs Tavern. |
| Artifact Market | Market, Miners' Guild | Market | Artifact Market needs Market. The Miners' Guild link belonged to the HoMM3 Treasury, which moves to its own row. |
| Resource Depot | Market | Market, Bank | Depot needs Market + Bank. |
| `Build_Mystic_Pond` (new) | n/a | none | A special has at most 1 prerequisite; the HoMM3 Pond has none. |
| Fountain of Fortune | Bank | `Build_Mystic_Pond` | HoMM3 upgrade relation (the Fountain upgrades the Pond). It plays the role of an L2 that needs only its L1. |
| `Build_Rampart_Treasury` (new) | n/a | none | A special has at most 1 base-level shared prerequisite. The HoMM3 Miners' Guild link is a special-on-special chain that vanilla never uses. |
| T7 L1 | T6, MG L2 | unchanged | Vanilla T7 L1 often needs MG L2. |
| T7 L2 | MG L3 | unchanged | The one allowed exception: a T7 upgrade may need an MG level (vanilla Dungeon). |
| T2, T3, T4, T5, T6 (T4 + T5), Bank (Main L2), Treasury, Miners' Guild (<- T2), Dendroid Saplings (<- T5) | as now | unchanged | Already convention-shaped (0–2 base dwellings, or vanilla economy; hordes keep their base dwelling). |

Levels with no outside prerequisite: before **19 of 35**, after **22 of 37**. Everything still fits the solver's columns 0..8 × 5 rows: 2 new nodes, and the deepest chain is T1 → T3 → T4 → T6 → T7 (depth 4, as now, and allowed by the HoMM3 flavour).

The validator `validate_homm3_city_building_tree_contract.py` must drop the Town Hall / City Hall checks. `COMMON_LEVEL_REQS` and `FACTION_LEVEL_REQS["homm3_rampart"]` change to match. The ADAPTATIONS note that says the Artifact Market is the Treasury identity must be removed.

## 3. Plugin work

All new files go in `Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/`.

1. **Town building reader** (new `Homm3TownBuildingReader.cs`; shared and specified in castle.md §3.1). Risk: low to medium.
2. **Siege-defence town bonus** (new `Homm3TownSiegeDefenseBuildingRuntime.cs`; shared, castle.md §3.2) adds `luck +2` for the Fountain. Risk: medium. It has the same garrison-without-hero and defended-town-lookup risks.
3. **Weekly town income** (new `Homm3TownWeeklyIncomeRuntime.cs`). A side-logic `OnStartDay` postfix, as in `Homm3FactoryLogisticsRuntime.cs`, gated on the first day of the week; the dwelling `OnStartWeek` hook in the same file is the alternative trigger. Through hook 1, it adds the Pond roll and the 10% Treasury interest to the side's resources via the native side resource-add path that `sideRes` income uses. Risk: medium. (a) It must fire exactly once per week, including after a load on day 1, so store the last paid week in the save-side state the Factory runtime already persists. (b) The AI must see the income; resources added natively are fine. (c) Order the Treasury before or after that day's income; HoMM3 computes it on the start-of-week balance, so run it first.

## 4. Owner decisions

1. **Treasury interest cap.** 10% of current gold each week, uncapped (HoMM3), or capped (for example at 2000 gold a week per town). **Recommend uncapped HoMM3 10%.** Rampart has no other gold special, and the cost (5000 gold + 5 ore) delays it. Revisit only if playtests show hoarding snowballs.
2. **Pond and Fountain shape.** Two rows (Pond, then Fountain needing Pond) or one 2-level row (L1 Pond, L2 Fountain). **Recommend two rows.** The 2-level form fits HoMM3 best, but it needs per-level text tokens and art switching, which no carrier row uses yet. Two rows reuse the existing `Build_Mother_Nature` art.
3. **Spirit Guardian power.** +2 Luck replaces the vanilla Nature grail's +1 growth everywhere, or is added on top of it. **Recommend replacing.** It is the HoMM3 effect, and it keeps the grail at the same strength as the Castle and Tower grails.
