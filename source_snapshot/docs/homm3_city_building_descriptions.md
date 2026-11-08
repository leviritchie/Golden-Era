# HoMM3 city building descriptions and native bonuses

Status: generated artifact validated and deployed payload proven on 2026-10-01. Installed Golden Era `Core.zip` sha256 `937e3c37…` (backup `Core.zip.backup-20261001-195529`) reads back `levels=475 errors=0`. Nothing here has been seen in game, so runtime and user-visible behaviour are unproven: the tooltips, the growth numbers and the hero-stat visits. The open row is in `docs/ingame_check_queue.md` (Towns).

## Contract

Bone Foundry exception under investigation (2026-10-02): the user reports that the bottom
Unique Building menu does not open its window. The installed conversion config passes this
document's data checks, but those checks do not exercise native menu dispatch or conversion
transactions. See `homm3_necropolis_bone_foundry_investigation.md`; do not treat the data pass
as working conversion or HoMM3 Skeleton Transformer parity.

Every `homm3_*_city` building level, and the `homm3_landon_*_city` clones, does something the game really applies. Its `descriptions` and `narrativeDescriptions` say exactly that, in vanilla OE wording, in all 16 locales.

- Mechanics owner: `apply_release_core_overlay.apply_homm3_native_city_building_bonuses`, which runs at the end of `apply_city_building_mechanics`. It takes the HoMM3 numbers from `CITY_BUILDING_MECHANICS_BY_FACTION` and moves each bonus onto a section and bonus type the game applies (see the next section).
- Text owner: `tools/release_port/homm3_city_building_descriptions.py`. It derives a list of sentences from each final config row. English text is rendered there. The 15 other locales are rendered from `tools/release_port/homm3_city_building_description_locales.py`.
- Producers:
  - `apply_homm3_city_building_descriptions` writes English. It runs after the last city-row mutation and before multilingual sync.
  - `apply_homm3_city_building_description_locales` writes the 15 locales after sync. Sync drafts therefore cannot replace these rows.
- Translations are machine translations, written in vanilla OE terminology.
  - A sentence vanilla OE already has (tavern, market, mana fountain, walls, graal lines, hero experience and so on) is read from the vanilla locale row named in `VANILLA_SENTENCE_KEYS`.
  - Unit names come from that locale's `units.json`.
  - Lists of names follow a colon, or appear as "+N name" items, so no template depends on case or plural inflection.
- Renamed buildings carry localized names (`BUILDING_NAMES`): Blacksmith; Dungeon Alchemic Depot (was Resource Silo II); Bulwark grail Spirits of the Forebears.
  - Other HoMM3 building names keep whatever locale text sync gives them. Many are still English; that is out of scope here.
- Numbers are literal. Custom keys get no `{0}` substitution from `BhTooltipBuilding` (only vanilla keys are filled), so a brace would show raw.
- Both modules fail closed. An unknown section, graal type or bonus type raises, and so does a bonus on a section that does not apply it. The build cannot ship invented or inert text.

Gate: `tools/release_port/validate_homm3_city_building_descriptions_contract.py`. It is wired into:
- the `-p:FullValidation=true` csproj target `ValidateHomm3CityBuildingDescriptionsContract`;
- `tools/port_current/run_core_validators.py`;
- the overlay candidate validation, so it also blocks an install.

`validate_homm3_city_building_contracts.py` checks the same native spec bonuses.

The gate fails on any of these:
- missing, empty, raw-key or placeholder text in any locale;
- a name or description that mentions a mechanic or entity OE lacks: war machines, shipyards, HoMM3/HotA wording, filler such as "special building" or "when supported", or "treasury" in a description. Each language has its own war-machine, shipyard and filler patterns. Filler markers (TODO/TBD/FIXME) are matched case-sensitively, because "todo" is Portuguese and Spanish for "all";
- an English description that differs from the derived text, or a narrative that differs from the description;
- a locale row that differs from the re-render, or equals the English text (an English fallback);
- a bonus on a section that does not apply it, or bonuses on `myceliumRoots`;
- a mechanics building missing from its native section, or with bonuses other than the native form of its HoMM3 numbers (a dropped bonus fails);
- a Blacksmith that is not named "Blacksmith", or that differs from the vanilla `human_city` Treasury in bonuses, level count, or per-level costs and prerequisites;
- a Necropolis units converter whose pairs are not the city's own tier 1-7 base units, or that does not ban all of those units.

## Native bonus mapping (2026-10-01 user decisions)

| HoMM3 effect | OE form | Evidence |
|---|---|---|
| Daily resources | `banks` `sideRes` | Vanilla Core: every vanilla bank carries only `sideRes` (live data). |
| Flat creature growth (hordes and similar) | `banks` `cityUnitsIncrementPer [<first sid of the dwelling's hire line>, p]` | Live interop: `EBonusType.CityUnitsIncrementPer`. Vanilla walls put `cityUnitsIncrementPer` in the same city container, and vanilla laws key growth by unit sid (live data). Growth is computed by `(int)(weekly*(1+Σp)) + flat` in `CalculateBonusIncrement` (Demo decomp, static). |
| Hero stats on visit | `heroBonusBanks` `heroStat` | Vanilla Core: Beelzebub's Hand, Gymnasium, Mother Nature and Endless Library use `heroStat` (offence, spellPower, intelligence) and `heroExp` (live data). Live interop: `BuildingHeroBonusBankConfig.bonuses`. |
| Blacksmith | Vanilla OE Treasury in every town, Fortress included: 2000 Gold daily; costs 5000 Gold plus 5 each of Gemstones, Crystals and Mercury; needs Bank 1 and Fort (Wall 1); one level | Vanilla `human_city` Treasury row (live data). The gate compares against it in the installed Core. |
| Bone Foundry | `unitsConverters`: tier 1-7 pairs point at the Necropolis's own base units; all its hire sids are banned | Live interop: `BuildingUnitsConverterConfig.conversionPairs` and `bannedUnits`. Vanilla `undead_city` pairs tiers 1-8 and bans `lich_dragon` (live data). The skip of `fraction == "undead"` units is in `ConvertUnitsUtility` (Demo decomp, static). |

Growth percent: `p = ceil((N + 0.01) / weekly × 10⁴) / 10⁴` reproduces a flat +N exactly on the base growth. For example, Griffins with weekly growth 7 get `0.43`: 10 with the Griffin Bastion, 13 with Citadel (+50%), 17 with Castle (+100%), matching HoMM3.

Caveat: other percent bonuses also scale the horde part. Vanilla laws or graals that add a percent, for example, multiply weekly × (1 + p + q) rather than adding a flat N. With only the walls this lands within one unit of HoMM3. `growth_percent_for_flat` self-checks the base case.

### Choices

- **Mycelium-slot buildings**: Bulwark Clan Stockyards, Conflux Elemental Conflux, Fortress Hydra Marsh and Rampart Dendroid Saplings now sit under `banks` with their HoMM3 growth. Their portal is dropped, for three reasons:
  - The portal is native only to the vanilla Nature city.
  - `BuildingMyceliumRootsConfig` has no `bonuses` field, so one row cannot hold both.
  - HoMM3 has no portal on these buildings.
- **Trade Carnival** (Bulwark, the HotA Fair, a town effect) is a plain town bonus: `banks` `sideRes gold 1000`.
- **Garden of Life** (Conflux, a HoMM3 horde) is a plain town bonus: `banks` growth.
  - Neither building is once-per-hero in HoMM3, so neither is a `heroBonusBank`.
- **Hero-stat buildings** are `heroBonusBanks`: Conflux Magic University (+1 Spell Power), Fortress Cage of Warlords (+1 Defense), Factory Mana Dynamo (+1 Knowledge). Stronghold Hall of Valhalla and Fortress Glyphs of Fear already were.
- **Stronghold Mess Hall** moves from `cityBonusBanks` to `banks`. It carries only growth.
- **Blacksmith gates**: every HoMM3 requirement on the Blacksmith is dropped, because the vanilla Treasury gates nothing. The dropped gates are City Hall; Castle Barracks; Stronghold Upg. Orc Tower; Cove Frigate; and Factory Upg. Halfling Adobe, Upg. Foundry and Manufactory. See `docs/homm3_city_building_tree.md`.
- **Bone Foundry tier 8**: there is no HoMM3 Necropolis tier-8 creature, so that pair is dropped.

## What each section says (source of the wording)

| Section | OE behaviour | Evidence tier |
|---|---|---|
| `mains` | Daily Gold, Law and Astrology points, read from `bonusesPerLevel`. Level 2 and level 3 offer one economy upgrade pick each. | vanilla text and data |
| `hires` | Level 1 recruits the base unit. Level 2 unlocks both upgrades (`upg`, `upg_alt`). | data and vanilla text shape |
| `banks` / `cityBonusBanks` | "Produces N R daily." / "Increases the weekly growth of U by N in this city." (N is recovered from the percent and the dwelling's weekly growth). | data |
| `heroBonusBanks` | "Grants +N Stat to any visiting hero." / vanilla hero-experience line. Applied once per hero. | vanilla text and data |
| `graals` | Vanilla text per `graalType`: Human (resources), Nature (+growth everywhere), Dungeon (full reveal), Demon (Attack and Lucky Strike), Undead (Defense and Lucky Strike reduction). Each also gives +100% dwellings in this city. | data and vanilla text |
| `walls` | Siege walls, then towers, then the grand tower and spikes. One defensive pick per level. Dwellings produce +0/+50/+100%. | data and vanilla text |
| `unitsConverters` | Lists the target units by name. | data |
| others | Native rows with vanilla text: market, artifact market, tavern, intelligence (`viewRadius`), training range, rebirth shrine, mana fountain, artifact changer, mycelium portal (vanilla Nature only). | vanilla text |
