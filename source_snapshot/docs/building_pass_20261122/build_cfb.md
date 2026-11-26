# Building pass: CFB hand-back (Cove, Factory, Bulwark), 2026-11-22

Proof tier: **source/static only.**
- `python tools/release_port/apply_release_core_overlay.py --check-building-overrides` reports `Building override check: OK`, with Cove OK (3 rows), Factory OK (4 rows) and Bulwark OK (3 rows). The only warnings are missing description locales, which the coordinator adds centrally.
- `tools/validate_custom_faction_manifests.py` passes (12 manifests).
- `validate_homm3_city_building_contracts.py` raises no CFB source_mechanics errors. Its only CFB errors say the canonical tree names `Build_Grotto` and `Build_Factory_Loan_Bank`, which the built Core does not have yet. They clear when the overlay is built with these overrides.
- The runtime C# was **not compiled** and **not run in game**. Nothing was committed. Nothing was written to the GE install.

Building IDs are exactly the coordinator's: Cove `Build_Grotto`, Factory `Build_Factory_Loan_Bank`.

## Renamed or reused SIDs

| Town | SID | New name | Was |
|---|---|---|---|
| Cove | `Build_Bank` | Counting House (plain 1000 Gold Bank) | Thieves' Guild |
| Cove | `Build_Golden_Calf` | Lodestar | Lodestar Vault |
| Cove | `Build_Grotto` | Grotto (**new**) | - |
| Factory | `Build_Bank` | Counting House (plain Bank) | Town Bank |
| Factory | `Build_Factory_Loan_Bank` | Bank (**new**, loan) | - |
| Factory | `Build_Mother_Nature` | Mana Generator (moved `heroBonusBanks` -> `banks`) | +1 Knowledge donor |
| Factory | `Build_Golden_Calf` | Lightning Rod | grail |
| Bulwark | `Build_Mother_Nature` | Fair (the 1000 Gold income is removed) | gold donor |
| Bulwark | `Build_Mycelium_Roots` | Altar of the Runes (**reused** sid, was Clan Stockyards) | +4 Kobolds weekly |
| Bulwark | `Build_Spring_of_Life` | Spirits of the Forebears | grail |

Factory has two rows named in the Bank family: the economy `Build_Bank` is "Counting House" and the loan row is "Bank", so the names differ.

## Files

### New

**`custom_factions/building_overrides/homm3_cove.json`**
- `Build_Bank`: replaced with the plain Bank (2500 Gold/5 Wood/5 Ore, sideRes gold 1000), named "Counting House".
- `Build_Grotto`: new `banks` carrier. Template `human_city:Build_Bank`, sceneSlot `Grotto`, cost 7500 Gold/15 Wood/15 Ore, `bonuses [[]]`, icon from `undead_city:Build_Skeleton_Converter`. Plugin `Homm3CoveGrottoRuntime`.
- `Build_Golden_Calf`: the graal keeps its 6 `sideResHumGraal` entries and `cityUnitsIncrementPer` 1.0, and adds the side bonus `anyLandEqualNativeLandBonus`. Plugin `Homm3CoveLodestarRuntime`.

**`custom_factions/building_overrides/homm3_factory.json`**
- `Build_Bank`: renamed "Counting House".
- `Build_Factory_Loan_Bank`: new `banks` carrier. sceneSlot `Factory_Loan_Bank`, cost 500 Gold/5 Ore, `bonuses [[]]`, icon from `dungeon_city:Build_Bank`. Plugin `Homm3FactoryLoanBankRuntime`.
- `Build_Mother_Nature`: now a `banks` carrier costing 1000 Gold/5 Ore with `bonuses [[]]`. Plugin `Homm3FactoryManaGeneratorRuntime`.
- `Build_Golden_Calf`: HumanGraal kept, with the Lightning Rod clause added to the description. Plugin `Homm3FactoryLightningRodRuntime`.

**`custom_factions/building_overrides/homm3_bulwark.json`**
- `Build_Mother_Nature` (Fair): 2000 Gold/10 Wood, `bonuses [[]]`.
- `Build_Mycelium_Roots` (Altar): 2000 Gold/5 Ore/4 Gems/4 Crystals, `bonuses [[]]`.
- `Build_Spring_of_Life` (Spirits): NatureGraal kept, plus the +20 Defense description. Plugin `Homm3TownSiegeDefenseRuntime` (**runtime agent's entry**, no CFB code).

**`OfflineUnlockMod/Homm3BulwarkFairRuntime.cs`** (64 lines)
- `ExtraMarkets(sideIndex)` counts the side's Bulwark towns that have both Market and Fair. The result is cached per side for 1 s. Fails closed.

**`OfflineUnlockMod/Homm3BulwarkAltarRunesRuntime.cs`** (45 lines)
- `GrantRoundOne(units)` adds `SideBuildingCount(hero, Build_Mycelium_Roots)` Rune Levels per stack.

**`OfflineUnlockMod/Homm3FactoryLoanBankRuntime.cs`** (499 lines)
- A 1 s poll (injected host `Homm3FactoryLoanBankRuntimeHost`) catches the not-built -> built transition with the same owner.
  - It stores the debt first, then pays +2500 Gold, and rolls back on failure.
  - It deliberately avoids construction-commit hooks, which crashed historically.
- At each side day start (postfix on side logic OnStartDay) it takes min(500, gold) per outstanding loan for 5 days.
  - A short payment still counts as that day's payment.
  - A last-paid-day guard stops double payment.
- The debt is stored on the hidden side-buff carrier `homm3_factory_loan_store` (records VER/CITY/LEFT/PAID + an FNV-1a SUM).
  - A corrupt carrier is never trusted or overwritten.
  - The debt belongs to the side and survives losing the town.

**`OfflineUnlockMod/Homm3FactoryManaGeneratorRuntime.cs`** (229 lines)
- A BattleLogic.Init prefix runs on sieges where the besieged town is a Factory town with the building. It adds 20 mana to the defending hero before Init copies it.
- An ApplyBattleResult prefix/postfix removes min(20, the mana left above the pre-battle value).
- At most 8 unsettled grants are tracked.

**`OfflineUnlockMod/Homm3FactoryLightningRodRuntime.cs`** (502 lines; also holds the shared helper `Homm3FactoryTownFacts`)
- A BattleLogic.Init postfix computes the total: the sum over the side's Factory towns with the grail of 7 x (4 + distinct built buildings).
- A round-started subscription strikes each enemy stack once through redirected damage.
- On any failure the Rod disables itself for the session.

**`OfflineUnlockMod/Homm3CoveLodestarRuntime.cs`** (208 lines)
- A BattleLogic.Init postfix sets the battle-side and stack native flags for a side owning a Lodestar (`FallbackEnabled = true`).
- Static evidence says the native graal bonus reaches the creature native check (the law-34 path) but not the side/hero flag. The fallback covers the side flag. The path taken is logged.
- **Needs the GameSymbols addition below.**

**`OfflineUnlockMod/Homm3CoveGrottoRuntime.cs`** (586 lines) and **`Homm3CoveGrottoWindow.cs`** (503 lines; injected host `Homm3CoveGrottoWindowHost`)
- A town-screen "Grotto" button (24,140 on the 1920x1080 layout) shows when the town has `Build_Grotto`.
- The window lets the visiting hero (else the garrison hero) sacrifice creatures for floor(squadValue / 40) x 5 experience each. The hero keeps at least one creature.
- Creatures are removed via `Homm3PartyArmyWriter.Write`. Experience goes through the native experience component (the War Captives path).

### Edited

- **`Homm3FactoryLogisticsRuntime.cs`** line 722, in `PostfixMarketsCount` after the `side == null` return: `__result += Homm3BulwarkFairRuntime.ExtraMarkets(side.index);`. The Fair therefore depends on the logistics GetMarketsCount hook registering. It is independent of Trade Contracts.
- **`Homm3BulwarkRunesRuntime.cs`**:
  - lines 113-114 add an `AltarChecked` flag on the stack state;
  - line 1260 adds the reason `"altar"`;
  - lines 1316-1354 add `ApplyAltarOfRunes(unit, altarLevelsForHero)`, which grants through the normal `TryApplyGain` once per stack.
- **`Homm3BulwarkLawHooks.cs`** lines 197-200 call `Homm3BulwarkAltarRunesRuntime.GrantRoundOne(units)` right after Carved in Advance.
- **`tools/release_port/homm3_factory_logistics_core_overlay.py`** (+22 lines):
  - adds `LOAN_CARRIER_BUFF_SID = "homm3_factory_loan_store"` and `make_loan_carrier_side_buff_row` (a clone of the logistics carrier with its own id and hook);
  - adds lang rows `homm3_factory_loan_store_name` "Bank Loan" and `homm3_factory_loan_store_description` "Bank loan records.";
  - the side-buff upsert now writes both carrier rows.
- **`custom_factions/source_mechanics/homm3_cove.json`**:
  - `cove.shipyard`: reason refreshed;
  - `cove.gunpowder_warehouse`: substituted, currentRows `Build_Tier_3` (moved off the economy Treasury), forbidden "Gunpowder Warehouse"/"double-upgrade";
  - new `cove.thieves_guild`: absent;
  - new `cove.grotto`: substituted, forbidden "artifact";
  - new `cove.lodestar`: exact.
- **`custom_factions/source_mechanics/homm3_factory.json`**:
  - `factory.mana_generator`: exact;
  - new `factory.lightning_rod`: exact;
  - new `factory.bank`: substituted, forbidden "any time"/"again after".
- **`custom_factions/source_mechanics/homm3_bulwark.json`**:
  - `bulwark.fair`: exact;
  - new `bulwark.altar_of_the_runes`: substituted, forbidden "learn Runes"/"Sieidi"/"Kobold";
  - new `bulwark.spirits_of_the_forebears`: exact.
- **`custom_factions/construction_building_category_contracts.json`**: Cove `pirate-infrastructure` currentRow is now `Build_Treasury` -> `Build_Tier_3`.
- **`OfflineUnlockMod/Homm3ConstructionBuildingCategoryRegistry.cs`** line 20: key `Build_Treasury` -> `Build_Tier_3`.
  - Hand-edited to the exact line the generator writes. `generate_construction_building_category_registry.py` currently refuses to run because of other groups' contract errors: fortress `Build_Bank`/`fortress.hydra_marsh`, stronghold `Build_Bank`, tower `tower.skyship_beacon`.
  - **Re-run the generator once those land** to confirm there is no drift.

## Needed in shared files (not edited by me)

**Plugin.cs** registrations, all inside the same try block as the existing faction runtimes:
```csharp
// after Homm3FactoryLogisticsRuntime.TryRegister(_harmony, Log);  (line 1079)
Homm3FactoryLoanBankRuntime.TryRegister(_harmony, Log);
Homm3FactoryManaGeneratorRuntime.TryRegister(_harmony, Log);
Homm3FactoryLightningRodRuntime.TryRegister(_harmony, Log);
// near the Cove block (line 1081)
Homm3CoveLodestarRuntime.TryRegister(_harmony, Log);
// after Homm3CoveTreasureSubskills.TryRegister(_harmony, Log);  (line 1083)
Homm3CoveGrottoRuntime.TryRegister(_harmony, Log);
```
- The Fair and the Altar need no registration: they ride the logistics market hook and the Bulwark Runes law hook.
- `Homm3FactoryLoanBankRuntimeHost` and `Homm3CoveGrottoWindowHost` are injected MonoBehaviours. Each registers its own IL2CPP type inside TryRegister.

**csproj**: none. It is SDK-style with no `Compile Include` list.

**GameSymbols** (required for `Homm3CoveLodestarRuntime` to compile):
```csharp
internal static partial class CoveLodestar
{
	/// <summary>Battle side euj (ObjectPublicPrcoObPrcoInTrPrcoInUnique) +0xE8: native-terrain flag, set in euj..ctor (0x18224ACC0); read by euj$$bibm via dvz$$cjs. 26615913.</summary>
	internal static readonly string[] BattleSideNativeMembers = { "_coer_k__BackingField" };
	/// <summary>Hex.Session.Battle.Unit +0xE8: unit native flag, fallback branch in Unit$$bjos (0x1822E1BC0). 26615913.</summary>
	internal static readonly string[] UnitNativeMembers = { "_cphr_k__BackingField" };
}
```

**Localization**:
- Core lang sids to translate centrally: `homm3_factory_loan_store_name` and `homm3_factory_loan_store_description`.
- The renamed and new rows' name and description locales are omitted per the applier rules.
- Leftover row-less text keys from the old donors can be deleted where the faction drafts list them (the Intelligence Academy / Training Range text).

**Siege coordination with `Homm3TownSiegeDefenseRuntime`**:
- The Mana Generator patches `BattleLogic.Init` (prefix) and `ApplyBattleResult` (prefix + postfix) on its own and does not call the siege-defense runtime. Both resolve the town through `Homm3TownBuildingReader.TryGetBesiegedCity`.
- Keep the mana removal a postfix of ApplyBattleResult.
- If the siege runtime also edits the defending hero's mana or stats in Init, both work additively. Neither resets the other.
- The Bulwark Spirits of the Forebears +20 Defense is the runtime agent's entry. CFB only points the row's `plugin` at it.

## Scene keys for new SIDs

- `Build_Grotto` -> the HoMM3 Cove **Grotto** building: catalog key `Grotto` in `scene3d/homm3_cove` (sceneSlot `Grotto`).
- `Build_Factory_Loan_Bank` -> the HotA Factory **Bank** building: catalog key `Factory_Loan_Bank` (the HotA "Bank" art) in `scene3d/homm3_factory` (sceneSlot `Factory_Loan_Bank`).
- Renamed and reused rows keep their existing slots and art. That includes Bulwark `Build_Mycelium_Roots`, whose art is the Clan Stockyards slot; ideally it would get Altar of the Runes art.

## Not built, and why

- **Grotto artifact sacrifice**: there is no save-safe native artifact removal in the plugin, so only creatures are offered. The source_mechanics entry is substituted and forbids "artifact".
- **Grotto via the building click**: opening from the town-scene building itself is unproven. The window opens from a town-screen button instead.
- **Factory repeatable loan action**: by owner decision the loan is granted once, when the Bank is built (REVIEW 2). Substituted.
- **Sieidi "learn Runes for free"**: Runes is the faction skill, and OE has no learn-a-skill building section. Yetis under a hero without Runes get no Altar levels. The Altar works only when the Runes runtime is live (`bulwark.runes` is runtime-pending).
- **Lodestar per-faction qualifier**: OE's native bonus is army-wide, so all terrain is native for the whole army of the owning side.
- **Lightning Rod**: the AI and the damage forecast do not see the strike.

## Risks to check in the first live run

- Mana Generator:
  - the mana may be capped at the hero's maximum;
  - the battle object at the result may differ from the one at Init (grants are matched by transfer-battle pointer).
- Lightning Rod: the redirected-damage method pin may not match; it disables itself and logs.
- Lodestar:
  - Init timing;
  - forcing the side native flag is stronger than law 34. Turn it off with `FallbackEnabled = false` if the native bonus alone proves enough.
- Loan Bank: the poll records the first sighting of each town without paying. A Bank already built when the plugin first sees a save never pays out. A Bank built mid-session does.
- Reader dependency: every runtime here relies on `Homm3TownBuildingReader`, which is uncommitted and owned by the runtime agent. The calls used are `CityHasBuilding`, `CityMatchesSid`, `SideCities`, `SideBuildingCount`, `SideHasBuilding` and `TryGetBesiegedCity`, all present in the current source.
- Scratch from the forks: `V:/olden_port_work/cfb_factory_battle`, `V:/olden_port_work/cfb_lodestar/`.
