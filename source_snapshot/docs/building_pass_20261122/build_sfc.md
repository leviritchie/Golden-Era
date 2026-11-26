# Building pass 2026-11-22: SFC hand-back (Stronghold, Fortress, Conflux)

`python tools/release_port/apply_release_core_overlay.py --check-building-overrides` reports all three towns OK: Stronghold has 4 rows, Fortress 5 and Conflux 3, with 0 removals.

Nothing has been compiled (no `dotnet build`, as the brief says) and nothing has been tested in game. No commits were made.

## Files

New files:
- `custom_factions/building_overrides/homm3_stronghold.json` (83 lines)
- `custom_factions/building_overrides/homm3_fortress.json` (103 lines)
- `custom_factions/building_overrides/homm3_conflux.json` (90 lines)
- `Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/Homm3TownBuildingWindowKit.cs` (584 lines). This is the shared plumbing for both windows:
  - the ticking host;
  - the current-town cache;
  - finding the heroes in town, including the logic hero;
  - the town-screen button;
  - the modal and its window chrome.
- `.../Homm3StrongholdFreelancersGuildRuntime.cs` (276)
- `.../Homm3StrongholdFreelancersGuildWindow.cs` (208)
- `.../Homm3ConfluxMagicUniversityRuntime.cs` (223)
- `.../Homm3ConfluxMagicUniversityWindow.cs` (164)

Edited files (in place; whole mechanics entries rewritten):
- `custom_factions/source_mechanics/homm3_stronghold.json`
- `custom_factions/source_mechanics/homm3_fortress.json`
- `custom_factions/source_mechanics/homm3_conflux.json`

## Plugin.cs registration needed

Add one line next to the Captives and Logistics registrations:
```csharp
Homm3TownBuildingWindowKit.TryRegister(Log);
```
- This call resolves `Homm3PartyArmyWriter` from `typeof(Hex.Session.Logic.Hero)`, which is idempotent.
- It also registers `Homm3TownBuildingWindowHost` and creates one DontDestroyOnLoad host. The host ticks both windows every frame.
- Nothing else is needed: there are no Harmony patches.
- The csproj needs no edit, assuming it compiles every `*.cs` file by default.

## Overrides by town

**Stronghold:**
- `Build_Bank`: renamed "Bank" (it was "Muster Yard"). Data unchanged: 2500g/5w/5o, 1000 Gold daily.
- `Build_Resource_Depot` Resource Silo: now 1 Wood + 1 Ore daily (was 1 Crystals); cost 5000 Gold + 5 Ore.
- `Build_Resource_Depot_level_2` becomes the **Freelancer's Guild**:
  - section banks, `bonuses: [[]]`, cost 1000 Gold;
  - plugin window;
  - keeps its icon and scene slot (`Resource_Depot_2`).
- `Build_Spy_Network` becomes **Warlords' Monument**. It keeps its fog reveal and +100% growth. The text adds +20 Attack for the siege defender, which the runtime agent's siege hook supplies.

**Fortress:**
- New `Build_Gymnasium`, **Cage of Warlords**:
  - heroBonusBanks, template `self:Build_Bank` (the pre-pass Cage row, so it keeps the Cage icon);
  - heroStat defence +1, cost 1000 Gold;
  - scene slot is the default, `Gymnasium`.
- `Build_Bank`: plain economy Bank again. It moves to banks: 2500g/5w/5o, 1000 Gold daily, icon from `nature_city:Build_Bank`.
- `Build_Mother_Nature` **Glyphs of Fear**:
  - moved to banks with `bonuses: [[]]` (the +1 Morale is removed);
  - text: siege defender +2 Defense (runtime agent's hook).
- `Build_Mycelium_Roots` becomes **Blood Obelisk** (replaces the invented Hydra Marsh):
  - `bonuses: [[]]`, 1000 Gold;
  - text: siege defender +2 Attack (runtime agent's hook).
- `Build_Spring_of_Life` Carnivorous Plant: keeps empire +1 growth and +100% city growth. The text adds siege defender +10 Attack / +10 Defense (runtime agent).

**Conflux:**
- New `Build_Magic_University`:
  - heroBonusBanks, template `self:Build_Bank` (keeps the University icon);
  - `bonuses: [[]]`, cost 2500g/5w/5o;
  - plugin window; scene slot is the default, `Magic_University`.
- `Build_Bank`: plain economy Bank again (banks, 1000 Gold daily, icon from `unfrozen_city:Build_Bank`).
- `Build_Spring_of_Life` becomes **Aurora Borealis**:
  - `cityBonuses` = `[magicGuildExpandMagics, cityUnitsIncrementPer all 1.0]`;
  - keeps `sideBonuses` `cityUnitsIncrement all 1`;
  - `graalType` stays NatureGraal. `BuildingGraal.OnConstruct` adds every cityBonus whatever the graalType, and `BuildingMagicGuild` reads `magicGuildExpandMagicsBonuses`.
  - The text lists all spells plus both kept growth bonuses.

## Renamed or reused SIDs (for central translation)

- **Stronghold:**
  - `Build_Bank` (renamed "Bank");
  - `Build_Resource_Depot` (new text);
  - `Build_Resource_Depot_level_2` (reused as Freelancer's Guild);
  - `Build_Spy_Network` (renamed Warlords' Monument).
- **Fortress:**
  - `Build_Gymnasium` (new, Cage of Warlords);
  - `Build_Bank` (renamed "Bank");
  - `Build_Mother_Nature` (new text);
  - `Build_Mycelium_Roots` (reused as Blood Obelisk);
  - `Build_Spring_of_Life` (new text).
- **Conflux:**
  - `Build_Magic_University` (new);
  - `Build_Bank` (renamed "Bank");
  - `Build_Spring_of_Life` (renamed Aurora Borealis).

The coordinator's building IDs are used exactly. There is no ID I could not use.

## Scene art keys for new SIDs

- Fortress `Build_Gymnasium` (slot `Gymnasium`) should map to the HoMM3 Fortress **Cage of Warlords**. The old Cage art sat on the Bank slot, so the restored Bank needs the generic Bank or Treasury-style art.
- Conflux `Build_Magic_University` (slot `Magic_University`) should map to the HoMM3 Conflux **Magic University**. The old art sat on the `Bank` slot, and the restored Bank needs Bank art.
- Freelancer's Guild keeps slot `Resource_Depot_2`. Its art should become the HoMM3 Stronghold **Freelancer's Guild**.
- Blood Obelisk keeps slot `Build_Mycelium_Roots`. Its art should become the HoMM3 Fortress **Blood Obelisk**.

## For the tree agent

- `Build_Gymnasium` (Fortress): HoMM3 requires the Fort, so I suggest prerequisite `Build_Wall:1`.
- Fortress `Build_Bank` currently requires `Build_Mother_Nature` and is `isConstructedOnStart`. The vanilla Bank needs only `Build_Main:2`.
- `Build_Magic_University` (Conflux): I suggest `Build_Magic_Guild:1`. The old Bank had this prerequisite; the restored Bank should go back to `Build_Main:2`.

## source_mechanics

- **Stronghold:**
  - `resource_silo`: exact (reason updated).
  - `freelancers_guild`: exact on `Build_Resource_Depot_level_2`.
  - New `warlords_monument`: exact on `Build_Spy_Network`.
  - `escape_tunnel`: now `runtime-pending` with no `currentRows`. Its `changeDisposition` says: when the runtime agent's Fort hook lands, set it exact on `Build_Wall`.
  - The Bank is no longer claimed by any mechanic.
- **Fortress:**
  - `cage_of_warlords`: exact on `Build_Gymnasium`.
  - `glyphs_of_fear`: exact.
  - `hydra_marsh` is replaced by `blood_obelisk`, exact on `Build_Mycelium_Roots`.
  - New `carnivorous_plant`: exact on `Build_Spring_of_Life`.
  - `field_infirmary` reason is honest now: there are no war machines, so the slot is the shared Treasury.
- **Conflux:**
  - `magic_university`: exact on `Build_Magic_University`.
  - `resource_silo`: exact (HoMM3 Conflux makes 1 Mercury).
  - `aurora_borealis`: exact. Its forbidden texts and `playerTextTokens` are dropped.
- **Validator caveat:** the exact rows for siege effects depend on the runtime agent's hooks. `Build_Gymnasium` and `Build_Magic_University` exist only after the overlay runs. I did not run the manifest validator; the memory note says validators are for release only.
- **Stale stamps:** the old Core rows carry `xHomm3SourceMechanic` stamps, for example Stronghold `Build_Bank` = `freelancers_guild`. Check that `stamp_city_building_source_mechanics_metadata` clears stamps on rows that are no longer claimed.

## Windows (both built; the click route is a town-screen button)

**Why a button:** no custom building-click route exists, because `BhBuilding.OnPointerClick` is native and unpatched.
- Each window gets an overlay button on the left edge of the screen, about a third of the way down.
- The button shows only while all of these hold:
  - `ModActions.GetCurrentCityData()` is non-null;
  - `ModActions.GetCurrentCityFraction()` is `homm3_stronghold` or `homm3_conflux`;
  - the owner is the local human;
  - `Homm3TownBuildingReader.CityHasBuilding(city, sid)` is true.
- Hovering the button takes the picker input block, so the town does not get the click.
- Inside a window, Esc or Close shuts it. Leaving the town also closes it.

**Freelancer's Guild:**
- The window has one tab per army: the garrison, the garrison hero and the visiting hero.
- A pay-in row picks gold, wood, ore, mercury, crystals or gemstones.
- Each stack row has **1 / Half / All** buttons and shows the price of one creature.
- A hero never sells its last creature.
- The army is written with `Homm3PartyArmyWriter` (`Write` / `WritePartyArmy`, with expected totals). After a partial write, payment is based on the creatures actually removed.
- **Price (an assumption; please confirm):**
  - One creature is worth half its recruit cost. Non-gold cost parts are converted at the Marketplace sell rate from `logistics_config.json`: base / (1 + max(0, 3.5 − 0.5 × Marketplaces)).
  - Paying in a resource buys it at base × (1 + the same surcharge).
  - Gold left over after buying whole units is paid as gold.

**Magic University:**
- One tab per hero in town and four rows: Daylight, Nightshade, Arcane and Primal Magic (`skill_magic_day`, `_night`, `_space`, `_primal`).
- Each costs 2500 Gold, the map University's `rewardCost`.
- A row is greyed with a reason when it is already known, the hero has 8 skills, there is not enough gold, or the hero is not ready.
- The hero is charged first; if the skill is not then added, the gold is refunded.
- **How the skill is added:** through the logic skill component that Logic.Hero holds (found as the member whose type contains a `Data.HeroSkills` and a `Logic.Hero`).
  - That component has two obfuscated public `(string) -> Logic.HeroSkill` methods: BySid and Add.
  - They are told apart by calling both with a skill the hero already has. BySid returns it; Add returns null and changes nothing, because the mono source shows it checks `skillsDict` first.
  - `Add` fires `onHeroLearnedSkill` exactly like a level-up pick.

**Save/load:** both windows act instantly, with no daily or weekly payouts, so there is no save state to persist.

## Risks / not verified

1. Nothing is compiled or tested in game. Watch these on first test:
   - the logic-hero registry scan in `Homm3TownBuildingWindowKit.ResolveRegistry` (it finds the logic root by shape);
   - the HeroSkills Add disambiguation;
   - whether the hero UI refreshes after a skill is added or creatures are sold.
2. **Hero not ready:** if the registry scan fails, a hero is served only after the logistics cache has seen it (day start or a visit). Before that, the window says "end the turn once or move the hero".
3. **Button covers popups:** the button is a ScreenSpaceOverlay canvas just below the modal sorting order, so it draws over native town popups. It hides only while one of our windows or War Captives is open.
4. **Stale city:** `GetCurrentCityData()` can fall back to the wrapper. If it returns a city after leaving town, the button could linger.
5. **Escape Tunnel text:** the Escape Tunnel has no player text on `Build_Wall`. The override schema has one `descriptionText` per row, and the Wall belongs to the runtime agent.
6. **Rows that move section:** Fortress `Build_Bank`, `Build_Mother_Nature` and Conflux `Build_Bank` change section on replace. The applier accepted this; check the built city doc once.
