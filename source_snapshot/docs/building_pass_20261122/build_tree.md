# Building pass 2026-11-22: tree hand-back

The tree agent applied the tree changes from the 12 drafts, REVIEW and the owner answers
to the canonical prerequisite table. It trimmed the table to the BRIEF Part B vanilla
conventions, updated the gate and the doc, and proved the fit offline. Nothing was
installed, built or committed.

## Files changed

| File | Change |
| --- | --- |
| `tools/release_port/homm3_city_building_tree.py` (378 lines changed in the diff) | See below |
| `tools/release_port/validate_homm3_city_building_tree_contract.py` (121 lines changed in the diff) | See below |
| `docs/homm3_city_building_tree.md` | Owners, Gates, Reference (special-rows table), Adaptations and Proof updated |

`homm3_city_building_tree.py` changes:
- **New tables.** `COMMON_LEVEL_REQS` and `FACTION_LEVEL_REQS` are new.
- **`FACTION_PREFERRED_CELLS`.** This new table holds preferred cells for the new
  specials and for the dwellings of 6 towns. In `apply_city_building_tree` it wins over a
  row's own `nodePos`; `COMMON_PREFERRED_CELLS` still wins over both.
- **`ADAPTATIONS`.** It was rewritten.
- **Solver.** The greedy reading-order pass now has one retry in deadline order (earliest
  last legal row first). The placement code moved into `_place_construction_tree`; its
  logic is unchanged.

`validate_homm3_city_building_tree_contract.py` changes:
- **Static checks.** They now enforce the conventions:
  - the shared economy equals the vanilla template, with no faction overrides except
    Inferno's `Build_Resource_Depot` (the Birthing Pools);
  - nothing requires the Treasury;
  - nothing requires an upgraded level except Main, MG and Wall levels;
  - a dwelling L2 needs only its L1, except a T7 L2, which may add one MG level;
  - a dwelling L1 takes at most 2 dwellings plus at most MG1/MG2. Castle T6 may take the
    Stables instead;
  - no dwelling L1 is deeper than 4;
  - a special takes at most 1 prerequisite.
- **Per-city check.** It now also fails when the strict depth is above 5.
- **Mutation tests.** Each new check fired on a planted violation.

`validate_city_construction_tree_layout.py` needed no change, because its generic rules
still hold.

## New SIDs: what the applier and faction agents must create

The table names these SIDs. Each needs a one-level city row in its town. **The overlay
fails closed** while a present level-1 row has no table entry, or while the table names
a level the city lacks. So the rows and the table must land together, using exactly
these SIDs.

| Town | SID | Building | Requirement |
| --- | --- | --- | --- |
| Castle | `Build_Stables` | Stables | root (gates Training Grounds T6) |
| Castle | `Build_Mother_Nature` | Brotherhood of the Sword | Tavern |
| Castle | `Build_Mycelium_Roots` | Signal Beacon | root |
| Rampart | `Build_Mystic_Pond` | Mystic Pond | root |
| Rampart | `Build_Mother_Nature` | Fountain of Fortune | Mystic Pond |
| Rampart | `Build_Rampart_Treasury` | Treasury | root |
| Tower | `Build_Library` | Library | MG1 |
| Inferno | `Build_Mycelium_Roots` | Castle Gate | Wall L2 |
| Inferno | `Build_Mother_Nature` | Order of Fire | MG1 |
| Necropolis | `Build_Mother_Nature` | Necromancy Amplifier | MG1 |
| Necropolis | `Build_Mycelium_Roots` | Cover of Darkness | root |
| Dungeon | `Build_Well_Of_Souls` | Mana Vortex | MG1 |
| Dungeon | `Build_Portal_Summoning` | Portal of Summoning | root |
| Fortress | `Build_Gymnasium` | Cage of Warlords | Town Hall (Main L2) |
| Conflux | `Build_Magic_University` | Magic University | MG1 |
| Cove | `Build_Grotto` | Grotto | Marketplace |
| Factory | `Build_Factory_Loan_Bank` | HotA loan Bank | root |

Two SID choices are mine, and the coordinator and the faction agents should align on
them:
- **Fortress Cage of Warlords is `Build_Gymnasium`.** It is a hero-bonus building, and
  Stronghold already uses this SID for its Hall of Valhalla equivalent.
- **Conflux Magic University is `Build_Magic_University`.** This SID is newly minted.

Other notes:
- **Dungeon `Build_Lyceum` is removed** from the table. The Portal of Summoning replaces
  it, so the Dungeon city row must be deleted.
- **Escape Tunnel.** Per owner answer 1, it comes with the Stronghold Fort and has no SID.
- **Bank.** Per REVIEW §1, Fortress and Conflux `Build_Bank` are now the economy Bank
  (Town Hall), like every other town. Their old specials moved to the rows above.
- **Scene keys.** The tree has none. The faction groups own the scene keys for these SIDs.
- **Plugin.cs.** No registrations are needed for the tree.
- **Hand prefs.** The hand cells in `apply_release_core_overlay.py`
  `HOMM3_SPECIAL_BUILDING_NODE_POS_BY_FACTION` (for example Fortress `Build_Bank` (0,4))
  are now overridden by `COMMON_PREFERRED_CELLS` and `FACTION_PREFERRED_CELLS`. I did not
  edit them.

## Prerequisite changes per town

Format: `level  old outside prerequisites  ->  new`. `-` means the previous level only;
`none` means the row did not exist. Every town also gets the economy template:
- Main L2/L3 need only the previous level;
- Marketplace needs the Tavern;
- Resource Silo needs the Marketplace and the Bank.

The economy rows are listed per town anyway.

```
## homm3_castle
  Bank:1  Tier_4  ->  Main:2
  Main:2  Tavern  ->  -
  Main:3  Magic_Guild, Market  ->  -
  Market:1  -  ->  Tavern
  Mother_Nature:1  none  ->  Tavern
  Mycelium_Roots:1  none  ->  -
  Resource_Depot:1  Market  ->  Bank, Market
  Stables:1  none  ->  -
  Tier_5:1  Magic_Guild, Tier_4  ->  Tier_4
  Tier_6:1  Bank  ->  Stables
## homm3_rampart
  Artifact_Market:1  Market, Resource_Depot_level_2  ->  Market
  Main:2  Tavern  ->  -
  Main:3  Magic_Guild, Market  ->  -
  Market:1  -  ->  Tavern
  Mother_Nature:1  Bank  ->  Mystic_Pond
  Mystic_Pond:1  none  ->  -
  Rampart_Treasury:1  none  ->  -
  Resource_Depot:1  Market  ->  Bank, Market
  Tier_3:1  Tier_1  ->  -
## homm3_tower
  Bank:1  Main:3, Wall:3  ->  Main:2
  Intelligence_Academy:1  Wall  ->  -
  Library:1  none  ->  Magic_Guild
  Main:2  Tavern  ->  -
  Main:3  Magic_Guild, Market  ->  -
  Market:1  -  ->  Tavern
  Resource_Depot:1  Market  ->  Bank, Market
  Tier_2:1  Tier_1  ->  -
  Tier_3:1  Tier_1  ->  -
  Tier_4:1  Magic_Guild, Tier_2, Tier_3  ->  Tier_2, Tier_3
## homm3_inferno
  Bank:1  Wall:2  ->  Main:2
  Main:2  Tavern  ->  -
  Main:3  Magic_Guild, Market  ->  -
  Market:1  -  ->  Tavern
  Mother_Nature:1  none  ->  Magic_Guild
  Mycelium_Roots:1  none  ->  Wall:2
  Tier_2:1  Tier_1  ->  -
  Tier_5:2  Magic_Guild:2  ->  -
## homm3_necropolis
  Bank:1  Magic_Guild  ->  Main:2
  Main:2  Tavern  ->  -
  Main:3  Magic_Guild, Market  ->  -
  Market:1  -  ->  Tavern
  Mother_Nature:1  none  ->  Magic_Guild
  Mycelium_Roots:1  none  ->  -
  Resource_Depot:1  Market  ->  Bank, Market
  Resource_Depot_level_2:1  Skeleton_Converter, Tier_1  ->  Tier_1
  Skeleton_Converter:1  Tier_1  ->  -
  Tier_2:1  Tier_1  ->  -
  Tier_4:2  Bank  ->  -
## homm3_dungeon
  Bank:1  Magic_Guild  ->  Main:2
  Lyceum:1  -  ->  none
  Main:2  Tavern  ->  -
  Main:3  Magic_Guild, Market  ->  -
  Market:1  -  ->  Tavern
  Portal_Summoning:1  none  ->  -
  Resource_Depot:1  Market  ->  Bank, Market
  Tier_2:1  Tier_1  ->  -
  Tier_4:1  Tier_2, Tier_3  ->  Tier_2
  Tier_7:1  Magic_Guild:2, Tier_5, Tier_6  ->  Magic_Guild:2, Tier_6
  Well_Of_Souls:1  none  ->  Magic_Guild
## homm3_stronghold
  Main:2  Tavern  ->  -
  Main:3  Magic_Guild, Market  ->  -
  Market:1  -  ->  Tavern
  Resource_Depot:1  Market  ->  Bank, Market
  Resource_Depot_level_2:1  Resource_Depot  ->  Market
  Tier_2:2  Tier_1:2  ->  -
  Tier_4:2  Magic_Guild  ->  -
## homm3_fortress
  Bank:1  Main:2, Mother_Nature  ->  Main:2
  Gymnasium:1  none  ->  Main:2
  Main:2  Tavern  ->  -
  Main:3  Magic_Guild, Market  ->  -
  Market:1  -  ->  Tavern
  Mycelium_Roots:1  Tier_7  ->  Wall
  Resource_Depot:1  Market  ->  Bank, Market
  Tier_1:2  Tavern  ->  -
  Tier_5:2  Resource_Depot  ->  -
## homm3_conflux
  Bank:1  Magic_Guild  ->  Main:2
  Magic_University:1  none  ->  Magic_Guild
  Main:2  Tavern  ->  -
  Main:3  Magic_Guild, Market  ->  -
  Market:1  -  ->  Tavern
  Mycelium_Roots:1  Tier_2, Tier_3, Tier_4, Tier_5  ->  Magic_Guild
  Resource_Depot:1  Market  ->  Bank, Market
  Tier_2:1  Magic_Guild, Tier_1  ->  -
  Tier_3:1  Magic_Guild, Tier_1  ->  -
  Tier_6:2  Magic_Guild:2  ->  -
## homm3_cove
  Grotto:1  none  ->  Market
  Main:2  Tavern  ->  -
  Main:3  Magic_Guild, Market  ->  -
  Market:1  -  ->  Tavern
  Resource_Depot:1  Market  ->  Bank, Market
  Tier_2:1  Tier_1  ->  -
  Tier_5:2  Magic_Guild:2  ->  -
## homm3_factory
  Factory_Gantry:2  Market  ->  -
  Factory_Loan_Bank:1  none  ->  -
  Main:2  Tavern  ->  -
  Main:3  Magic_Guild, Market  ->  -
  Market:1  -  ->  Tavern
  Resource_Depot:1  Market  ->  Bank, Market
  Tier_2:1  Tier_1  ->  -
  Tier_5:2  Magic_Guild  ->  -
  Tier_6:2  Market  ->  -
## homm3_bulwark
  Main:2  Tavern  ->  -
  Main:3  Magic_Guild, Market  ->  -
  Market:1  -  ->  Tavern
  Mother_Nature:1  Main:2, Market  ->  Market
  Mycelium_Roots:1  Tier_1  ->  -
  Resource_Depot:1  Market  ->  Bank, Market
  Tier_2:1  Tier_1  ->  -
```

### Deviations from the drafts

**Depth trims beyond the drafts.** BRIEF Part B says a chain may not be deeper than
vanilla, which means a dwelling L1 at depth 4 or less and strict depth 5. To meet that,
these rows lose their HoMM3 gate and become roots:
- Rampart T3;
- Tower T2 and T3;
- Conflux T2 and T3 (losing MG1 and T1);
- Cove, Factory and Bulwark T2.

**REVIEW §1.** Fortress and Conflux Bank are now the economy Bank. Depot needs the
Marketplace and the Bank, and the Treasury needs the Bank and the Fort.

**Specials take one prerequisite.** For example:
- Conflux Elemental Conflux needs MG1 instead of all four elemental dwellings;
- Fortress Blood Obelisk needs the Fort instead of T7.

## Levels with no outside prerequisite

"Outside" means anything other than the previous level of the same building. The
"before" counts come from the installed GE Core and the "after" counts from the
simulation. Vanilla OE cities have 22–23.

| Town | Levels before → after | No outside prerequisite before → after | Strict depth before → after |
| --- | --- | --- | --- |
| Castle | 32 → 35 | 19 → 22 | 5 → 5 |
| Rampart | 35 → 37 | 19 → 23 | 6 → 5 |
| Tower | 35 → 36 | 20 → 24 | 6 → 5 |
| Inferno | 34 → 36 | 20 → 23 | 6 → 5 |
| Necropolis | 34 → 36 | 19 → 24 | 6 → 5 |
| Dungeon | 35 → 36 | 21 → 23 | 6 → 5 |
| Stronghold | 33 → 33 | 16 → 19 | 5 → 5 |
| Fortress | 33 → 34 | 16 → 19 | 5 → 5 |
| Conflux | 35 → 36 | 19 → 23 | 6 → 5 |
| Cove | 33 → 34 | 17 → 20 | 6 → 5 |
| Factory | 35 → 36 | 16 → 22 | 6 → 5 |
| Bulwark | 34 → 34 | 19 → 22 | 6 → 5 |

Before the pass, 9 towns (and the landon Dungeon clone) had strict depth 6 and drew only
through the beside-cell relaxation. After the pass, every town is strict depth 5.

## Solver result

How it was run (read-only): `V:/olden_port_work/building_pass/tree/simulate.py`.
1. It read the installed GE Core's 14 city files (dumped into `core_cities/`).
2. It added each new SID as a one-level row, deep-copied from `Build_Bank` with `nodePos`
   removed.
3. It removed the Dungeon Lyceum.
4. It applied `apply_city_building_tree` and re-derived the landon clones.
5. It wrote `sim_out/` and `sim_core.zip`.

Results:
- **12 HoMM3 towns.** All succeed on the first (reading-order) solver pass, at strict
  depth 5 and max column 8, with 0 `city_errors`.
- **Landon castle and dungeon clones.** 0 errors.
- **`validate_city_construction_tree_layout.py --include-derived`** on `sim_core.zip`:
  14 cities, 0 failing.
- **`validate_homm3_city_building_tree_contract.py --core sim_core.zip`:** 0 errors.
  With `--static-only`: 0 errors.
- **From scratch**, with every `nodePos` dropped, every town still fits columns 0..8 x 5
  rows.
- **`apply_release_core_overlay`** still imports.

Two problems came up during the run and are fixed:
1. On the first try, Rampart, Necropolis, Dungeon and Conflux failed with "no legal
   build-grid cell" on T4/T6. Greedy early placements had filled the rows that deep
   chains needed. The fix was the deadline-order retry plus dwelling preferred cells.
2. Inferno T4 and Fortress T4 then landed in odd cells (far left, or MG3's cell).
   Preferred cells fixed this.

## Expected failures and caveats

- **The installed Core fails the new contract** (29 errors) until the applier adds the
  new rows and the overlay is applied. This is the gate working.
- **The solver is not idempotent on its own output.** This is expected, because the
  overlay runs it once per build.
- **Runtime is not exercised:** no build, no install, no in-game build panel.
  `tools/homm3_town_scene_meshes/town_full3d_build_states.py` reads `canonical_prereqs`
  from the table and should keep working, but I did not run it.

Scratch is in `V:/olden_port_work/building_pass/tree/`: `simulate.py`, `sim_report.txt`,
`prereq_diff.txt`, `sim_out/`, `sim_core.zip`, `core_cities/`, `vanilla_depth.py`,
`grid.py`, and `new_table_block.py` (a copy of the new table).
