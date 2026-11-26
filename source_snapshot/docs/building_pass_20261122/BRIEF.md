# Building pass brief (2026-11-22)

Owner request, 2026-11-22:
- "In terms of balance, I expect buildings to mostly be correct. However, there are many for which we use substitute vanilla effects because we didn't have enough of a grasp of these plugins to use the appropriate one."
- "Building trees also need to be analyzed for consistency with vanilla, e.g. I don't think upgraded buildings in vanilla are prerequisites for other buildings."

This pass covers the 12 `homm3_*_city` towns: Castle, Rampart, Tower, Inferno, Necropolis, Dungeon, Stronghold, Fortress, Conflux, Cove, Factory and Bulwark. Its two parts, A and B, are below.

## Part A: substituted building effects

**Inputs** (all under `V:/olden_port_work/building_pass/`):
- `substitutes.md`: every non-`exact` row in `custom_factions/source_mechanics/<faction>.json`. The `(building)` rows are this pass's targets.
- Also audit every special building in your factions: anything outside the shared economy, dwellings, Mage Guild and Wall. Check them against the HoMM3/HotA source. Rows marked `exact` are out of scope unless they are wrong.
- `vanilla_city_sections.md`: every native city section vanilla uses, with each building's section-specific fields. It includes `portalSummonings`, `manaFountains`, `unitsConverters`, `rebirthShrines`, `myceliumRoots`, `heroBonusBanks`, `artifactChangers`, `trainingRanges`, `intelligences` and `graals`.
  - The IL2CPP city schema has more sections than vanilla uses (`cityBonusBanks` is one). Find the schema in the Ghidra project: `reference_ghidra_oe_project` memory, `oe_ghidra.py`, or the interop dumps the repo already uses.
- `vanilla_bonus_types.md`: every bonus `type` in the vanilla DB, with the files that use it.
- The law pass toolkit, `docs/faction_law_pass_20261121/BRIEF.md` § Toolkit, lists every live native bonus type and its qualifiers:
  - law-granted battle buffs;
  - plugin rules (`docs/unit_ability_pass_20261121/RUNTIME_CONTRACT.md`);
  - the plugin's law-level reader.

  A building can use the same levers. A plugin rule can key off "this side owns a town with building X at level N". Check whether a reader for that already exists; if not, specify one.

**Rules:**
1. **Use the effect the source building actually has.** Use native data where a native section or bonus says it; vanilla already ships many HoMM3-shaped buildings. Use a plugin hook where native data cannot say it. Never use a donor-shaped stand-in ("no donor limit"). A substitute is acceptable only where the source mechanic cannot exist in Olden Era at all:
   - ships, water and coastal maps;
   - war-machine purchase, unless you find a real path.

   For those, design the closest faithful land-safe equivalent. Don't fall back to a generic +1 stat or +1000 gold.
2. **Balance.** Keep the current cost and power where the effect already fits. When an effect changes, match vanilla's analogous building, or the HoMM3 value scaled the way the port scales values. Grails stay grail-strength.
3. **Text.** Vanilla wording with literal numbers. Descriptions are computed by `tools/release_port/homm3_city_building_descriptions.py` from the final row; plugin-only effects need explicit text. No implementation terms.
4. After a change, a `source_mechanics` row becomes `exact`, or keeps `substituted` with an honest reason when the source mechanic cannot exist.

## Part B: building tree consistency with vanilla

**Inputs:**
- `vanilla_trees.md`: every vanilla city's levels, with non-self prerequisites and costs.
- `ge_trees.md`: the same view of our installed towns.
- Owner of the GE trees: `tools/release_port/homm3_city_building_tree.py` (`COMMON_LEVEL_REQS`, `FACTION_LEVEL_REQS`). It currently encodes HoMM3 requirements. The contract and layout solver are described in `docs/homm3_city_building_tree.md`.

**Vanilla conventions, measured across all 6 vanilla cities:**
- **Shared economy is identical in every faction:**
  - Town Hall L2/L3 need only the previous level.
  - Market needs Tavern; Artifact Market needs Market.
  - Bank needs Town Hall L2; Treasury needs Bank + Wall L1.
  - Resource Depot needs Market + Bank; Depot L2 needs Depot.
  - Mage Guild levels, Wall levels, Tavern and the grail need only their own chain.
- **Dwelling upgrades (L2) need only their own L1.** The one exception is a T7 upgrade, which may need a Mage Guild level (Dungeon T7 L2 needs MG L3).
- **No building ever needs an upgraded dwelling.** The only upgraded (L2+) prerequisites in vanilla are:
  - Town Hall L2, for the Bank;
  - Mage Guild L2/L3, for T7 or one special (Undead Well of Souls needs MG L3);
  - Wall L2, once, for Nature's Mycelium Roots.
- **Dwelling L1:**
  - 0 to 2 base-level dwelling prerequisites;
  - T7 L1 often also needs Mage Guild L2;
  - 22 to 23 of the roughly 34 levels per city have no outside prerequisite.
- **Specials:** at most 1 prerequisite, a base-level shared building (Main L2, Wall L2 or MG L3 at most).

**Rules:**
1. Map each GE slot to its role first. Several GE towns reuse a shared slot SID for a special building; for example, Castle `Build_Bank` currently holds the Stables substitute. Apply the economy template to slots that hold the economic building.
2. Keep each faction's HoMM3 dwelling flavour (which dwelling unlocks which) wherever it fits the vanilla conventions. Remove these:
   - upgraded-dwelling prerequisites;
   - extra prerequisites on dwelling upgrades;
   - HoMM3 Town Hall/Capitol gates;
   - any chain deeper or denser than vanilla's.
3. The layout solver must still fit the tree in columns 0..8 of 5 rows.

## Deliverable (design phase, no code edits)

Write `docs/building_pass_20261122/<faction>.md`, one file per faction:
1. **Special buildings table:**

   | SID | Source building (HoMM3/HotA effect) | Current effect | Status | Proposed build (native section + fields / bonus, or plugin hook with file and hook point) | Player text | Cost/power note |
2. **Tree changes table:**

   | Level | Current prerequisites | Proposed prerequisites | Why (convention) |

   End it with a one-line count of levels without outside prerequisites, before and after.
3. **Plugin work:** each new hook, with the file it belongs in, the game method to patch or reuse, and its risk.
4. **Owner decisions:** only genuine design forks, at most 3, each with your recommendation.

Do not edit the repo, run the game or commit. Write only your faction files under `docs/building_pass_20261122/`, plus scratch files in `V:/olden_port_work/building_pass/<your-name>/`.
