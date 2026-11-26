# Bulwark building pass (2026-11-22)

Scope: `homm3_bulwark_city`, as installed in GE `Core.zip`. HotA source: Bulwark town buildings.

How the slots map to roles:
- Economy template: `Build_Bank` ("Trade Hall", 1000 gold), `Build_Treasury` ("Blacksmith", 2000 gold), `Build_Resource_Depot` (wood + ore) and `Build_Artifact_Market`.
  - The Artifact Market has no Bulwark HotA source, but every vanilla town has one, so it stays.
- Specials: `Build_Resource_Depot_level_2` (Hay Bins horde), `Build_Mother_Nature` (Fair) and `Build_Spring_of_Life` (grail).
- `Build_Mycelium_Roots` ("Clan Stockyards") is an OE-only filler with no HotA source. The HotA Sieidi of the Runes and Altar of the Runes have no row.

## 1. Special buildings

| SID | Source building (HoMM3/HotA effect) | Current effect | Status | Proposed build | Player text | Cost/power note |
|---|---|---|---|---|---|---|
| `Build_Mother_Nature` | Fair: trade rates as if the player owned two Marketplaces from this town. 2000 gold, 10 wood; requires Town Hall + Marketplace. | `banks` gold 1000 per day ("Trade Carnival") | substituted (donor-shaped income) | Plugin. Remove the gold bonus (keep the row in `banks`, empty, or move it to `cityBonusBanks` with empty `bonuses`). Extend the existing `GetMarketsCount` postfix (`Homm3FactoryLogisticsRuntime.PostfixMarketsCount`, via `GameSymbols.FactoryLogisticsMarket.MarketsCount`) with +1 for each owned Bulwark town that has both `Build_Market` and `Build_Mother_Nature` built. That makes the town's Market count as two. Native formula: `extraCharge = max(0, 3.5 - 0.5 x count)`, so each Fair lowers the extra charge by 0.5 until it reaches the floor. Check "two Marketplaces" against the HotA source; if it means two more, use +2. | "Improves your trade rates as if this town had two Marketplaces." | Change the cost to the HotA 2000 gold, 10 wood (now 5000 gold, which paid for the income). Power matches the source. Owner decision 1. |
| `Build_Mycelium_Roots`: becomes Altar of the Runes | Sieidi of the Runes: local heroes may learn Runes for free (Bulwark heroes or Scholar). 1000 gold, 5 ore, 2 gems, 2 crystals. Altar of the Runes (its upgrade): +1 Rune Level to the player's units at the start of combat, for heroes with Runes and for Yeti Runemasters; several Altars stack. 1000 gold, 2 gems, 2 crystals. | `banks` `cityUnitsIncrementPer h3_kobold 0.2865` (+4 Kobolds per week, "Clan Stockyards") | Filler with no source (donor-shaped) | Replace it with the Altar, with the Sieidi folded in. Move the row to `cityBonusBanks` with empty `bonuses`. Plugin: at round 1, for each side, count its owned Bulwark towns with this building (reader). Grant that many Rune Levels to every stack the Runes skill already covers (a hero with Runes, plus Yeti Runemasters). Use the existing round-1 grant path, `Homm3BulwarkRunesRuntime.ApplyCarvedInAdvance` -> `TryApplyGain(unit, unitKey, level, reason)`, with its own reason id. The Sieidi "learn Runes for free" clause is left out: Runes is the Bulwark faction skill, and OE has no learn-a-skill building section. Record it in source_mechanics as an honest partial. | "At the start of every combat, your creatures that use Runes gain +1 Rune Level for each Altar of the Runes you own." | Change the cost to the folded HotA total: 2000 gold, 5 ore, 4 gems, 4 crystals (now 5000 gold plus 5/5/5). This removes +4 Kobolds per week. Owner decision 2. |
| `Build_Spring_of_Life` (graals) | Spirits of the Forebears: +5000 gold per day, growth x1.5, and the defending hero gets +20 Defense in a siege of this town. | NatureGraal (+1 growth in all cities, city +100%) | substituted (siege clause missing) | Keep the NatureGraal bonuses. Plugin: siege-defense battle start (the shared hook in `factory.md` section 3, item 2). When the defended town is a Bulwark with `Build_Spring_of_Life`, add a battle-only +20 Defense to the defending hero. Use a battle buff on the hero through the native buff adapter (`Homm3BuffDebuffNativeAdapter`) with a `heroStatBattle defence 20` bonus row, removed with the battle. Vanilla wall `optionalEffectsPerLevel` `wallEffect` rows are player-picked siege options and cannot carry a fixed grail effect. | "+1 to all creature growth in all your cities. This city's dwellings produce +100% units. In a siege of this city, the defending hero gains +20 Defense." | Grail-strength. +20 is the HotA number. In OE a hero's Defense feeds every stack, so it is strong but confined to sieges of one town. |
| `Build_Resource_Depot_level_2` | Hay Bins: +1 Mammoth per week | `cityUnitsIncrementPer h3_mammoth 0.505` | exact | No change | unchanged | Tree gate: see section 2. |
| `Build_Resource_Depot` | Resource Silo (wood + ore) | +1 wood, +1 ore | exact | No change | unchanged | none |
| `Build_Treasury` | HotA Blacksmith (First Aid Tent purchase) | Economic Treasury named "Blacksmith" | out of scope | No change | unchanged | none |
| (no row) | Shipyard | none | absent | None. Ships cannot exist. | none | none |

## 2. Tree changes

| Level | Current prerequisites | Proposed prerequisites | Why (convention) |
|---|---|---|---|
| Build_Main:2 | Tavern | none | Town Hall L2 needs only the previous level. |
| Build_Main:3 | MG1 + Market | none | Town Hall L3 needs only the previous level. |
| Build_Market:1 | none | Tavern | Market needs Tavern. |
| Build_Resource_Depot:1 | Market | Market + Bank | Resource Depot needs Market + Bank. |
| Build_Mother_Nature:1 (Fair) | Main2 + Market | Market | A special has at most 1 base shared building. Marketplace is the Fair's own HotA requirement; the Town Hall gate is dropped. |
| Build_Mycelium_Roots:1 (Altar) | T1 | none | A special has at most 1 shared building and never a dwelling. HotA's Sieidi has no dwelling gate. |
| Build_Resource_Depot_level_2:1 (Hay Bins) | T6 | T6 (keep; owner decision 3) | A horde gated on its own base dwelling; see Cove decision 2. |
| Build_Tier_5:1 | MG1 + T3 | keep | A base shared building plus 1 base dwelling has a vanilla precedent. |
| Build_Tier_7:1 | T5 | keep | 1 base dwelling. |
| Tier 2/3/4/6 L1 | 1 base dwelling each | keep | Within 0 to 2. HotA's Sieidi gate on the upgraded Mountain Embassy and Frosthome is not added: a dwelling upgrade needs only its own L1. |

Levels without an outside prerequisite: 19 of 34 before; 21 of 34 after. The node count is unchanged, so the current layout still fits.

## 3. Plugin work

1. **Town building reader.** `Homm3CityBuildingReader.cs`, shared and specified in `cove.md` section 3. Risk: low.
2. **Fair market count.**
   - Add a term to `Homm3FactoryLogisticsRuntime.PostfixMarketsCount`, or move that postfix into a shared `Homm3TownMarketCountRuntime.cs` so the Factory and Bulwark terms live side by side. The method is already patched: `GetMarketsCount` on the world-side type.
   - Risk: low. Same hook, one more count term. It must stay cheap, because the market UI calls it often; use the day-cached reader.
3. **Altar Rune Levels.**
   - In `Homm3BulwarkRunesRuntime.cs`, next to `ApplyCarvedInAdvance`, add `ApplyAltarLevels` at round 1. It needs a new reason id so it stacks with Carved in Advance.
   - Risk: medium-high. The Runes runtime itself is runtime-pending (it may still be probe-only), so the Altar is only as live as Runes. It must not grant levels to stacks Runes does not cover.
4. **Forebears siege Defense.**
   - In the shared `Homm3TownSiegeDefenseRuntime.cs` (see `factory.md`): a battle buff on the defending hero.
   - Risk: medium. Defended-town identity and the hero buff receiver both need tracing. `Homm3DungeonCaptivesRuntime.ResolveBuffManager(logicHero)` is a working pattern for a hero buff manager.

## 4. Owner decisions

1. **Fair strength.** HotA wording "as if two Marketplaces": this town's Market counts double (+1), or two extra Marketplaces (+2)? Recommendation: +1 (the town counts as two Marketplaces) at the HotA cost of 2000 gold, 10 wood. That is the literal reading, and it keeps Bulwark below the Logistics Network's Trade Contracts in trading power.
2. **Replace Clan Stockyards (+4 Kobolds per week) with the Altar of the Runes.** Recommendation: yes. Stockyards has no source and duplicates a horde. The Altar is Bulwark's signature building and feeds the Runes skill. The cost: the Altar is dead weight until the Runes runtime is live, so ship the two together.
3. **Horde gate on Hay Bins** (cross-faction; see Cove decision 2). Recommendation: keep it gated on the Tier 6 dwelling.
