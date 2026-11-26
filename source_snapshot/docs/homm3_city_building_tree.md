# HoMM3 city building tree

Operational contract for the build prerequisites (`prevBuildings`), the construction-tree
cells (`nodePos`) and the AI build orders (`buildOrders`) of every `homm3_*_city` and its
campaign clones (`homm3_landon_castle_city`, `homm3_landon_dungeon_city`).

## Owners

- The table lives in `tools/release_port/homm3_city_building_tree.py`. `COMMON_LEVEL_REQS`
  holds the shared buildings and `FACTION_LEVEL_REQS` holds the per-faction entries. Each
  key is `SID:level` and maps to the direct requirements. A level above 1 always
  requires the level before it as well. Since the building pass of 2026-11-22
  (`docs/building_pass_20261122/`), the HoMM3 requirements are trimmed to the vanilla OE
  conventions (see "Adaptations to Olden Era" below).
- The table is applied by `apply_release_core_overlay.py`, in
  `apply_homm3_city_building_tree`. That step runs last in each city normalizer, after
  every row has been added, trimmed (Mage Guild caps) or stripped (unbound Castle slots).
  - It replaces every level's `prevBuildings`.
  - It derives every `nodePos` with `solve_construction_tree_layout`, on the clickable
    columns 0..8 only (see "Clickable columns" below).
    A level on its final upgrade's last legal row keeps its last free side cell for that
    upgrade, so a 6-deep chain can still use the one beside-cell relaxation (Dungeon
    Upg. Dragon Cave after the Blacksmith moved under the Bank, 2026-10-01).
  - It reorders `buildOrders` so that each prerequisite comes first, and drops entries for
    building levels the city does not have.
  - It fails closed in three cases: a shipped level has no table entry, a table entry
    names a level the city lacks, or the tree cannot be drawn in the clickable columns
    0..8 of the native 5 rows. There is no fallback to column 9.
  - Shared economy and Mage Guild cells (`COMMON_PREFERRED_CELLS`) are kept for their
    building. A special shifted off the Blacksmith cell no longer takes the Fort's
    cell (Dungeon Gymnasium and Inferno Beelzebub's Hand, fixed 2026-10-02).
- `refresh_homm3_derived_city_docs` re-derives each landon clone in the release Core from
  the stock city that was just generated, changing only the `id`. This copies the
  campaign installer's `clone_core_object_row`.
- `HOMM3_SPECIAL_BUILDING_NODE_POS_BY_FACTION` (the 2026-09-29 hand layout) and the donor
  grid are now *preferred* cells only. Shared buildings use the template in
  `COMMON_PREFERRED_CELLS`:
  - economy in columns 0-3;
  - Mage Guild in column 8;
  - grail at (0,4).

  An upgrade prefers the cell directly under its base level.
- `FACTION_PREFERRED_CELLS` (same module) holds preferred cells for two groups:
  - the special rows the 2026-11-22 pass adds;
  - the dwellings of the towns whose lanes changed (Rampart, Inferno, Necropolis,
    Dungeon, Fortress, Conflux).

  It wins over the row's own `nodePos`, so a new row deep-copied from a template does not
  inherit the template's cell. `COMMON_PREFERRED_CELLS` still wins over both.
- The solver places levels in the reading order of their preferred cells. If that greedy
  pass leaves a deep chain without a free cell, it retries once, placing first the levels
  with the earliest last legal row. It fails closed only if both passes fail.

## Clickable columns

The native panel has 10 columns (`BhUIBuildingSession.buildingsUIs[y * 10 + x]`), but
column 9 is covered by other build-screen UI. A building drawn there cannot be clicked
(user report, 2026-10-02). The contract comes from vanilla data: every stock OE city
(`human`, `demon`, `dungeon`, `nature`, `undead`, `unfrozen`) uses columns 0..8 and
never column 9. This holds in both the Steam and the Golden Era `Core.zip`.
`VANILLA_MAX_COLUMN = 8` in `validate_city_construction_tree_layout.py` owns the bound,
and the solver imports it.

Before the fix, the installed Core drew these cells in column 9:

| City | Cells at x=9 |
| --- | --- |
| Bulwark | `Build_Tier_4` L1 (9,3), L2 (9,4) |
| Conflux | `Build_Tier_2` L1 (9,1), L2 (9,2) |
| Cove | `Build_Tier_3` L1 (9,2), L2 (9,3) |
| Dungeon (and `homm3_landon_dungeon_city`) | `Build_Magic_Guild` L5 (9,4) |
| Fortress | `Build_Mother_Nature` (9,2) |
| Inferno | `Build_Tier_5` L1 (9,3), L2 (9,4) |
| Rampart | `Build_Tier_4` L1 (9,2), L2 (9,3) |

All 12 trees fit in 9 columns once they are re-packed. The Bulwark and Dungeon hand
preferences were re-cut (2026-10-02) so that each upgrade stays under its base or
beside it, and Dungeon MG5 stays under MG4.

## Gates

- `tools/release_port/validate_homm3_city_building_tree_contract.py` checks the installed
  Core by default. With `--static-only` it checks the table alone. It fails when:
  - any level's prerequisites differ from the table;
  - a level that is not a declared root has no prerequisite;
  - a prerequisite is missing from the city;
  - the graph has a cycle;
  - the layout breaks `validate_city_construction_tree_layout.py`: grid bounds, a cell
    beyond the vanilla clickable column 8, stacked cells, or a prerequisite not drawn
    above its dependent;
  - a build-order entry comes before its prerequisites or names an absent level;
  - a landon clone differs from its stock city beyond `id`.

  It also fails when a city's prerequisite chain is deeper than the 5 native rows. Every
  vanilla city draws strictly, and since 2026-11-22 no HoMM3 town needs the layout
  validator's beside-cell relaxation.

  Its static half enforces the vanilla conventions on the table:
  - the shared economy equals the vanilla template exactly, and no faction overrides it.
    The one exception is Inferno's `Build_Resource_Depot`, which holds the Birthing Pools
    horde;
  - no building requires the Blacksmith (`Build_Treasury`, the OE Treasury);
  - nothing requires an upgraded level except Town Hall, Mage Guild and Wall levels;
  - a dwelling upgrade needs only its own L1, except a T7 upgrade, which may take one
    Mage Guild level;
  - a dwelling L1 takes at most 2 dwellings plus one Mage Guild level (MG1 or MG2).
    Castle Training Grounds may take the Stables instead;
  - no dwelling L1 sits deeper than 4 in the chain;
  - a special building takes at most one prerequisite.
- Where it runs:
  - OfflineUnlockMod csproj target `ValidateHomm3CityBuildingTreeContract`, gated on
    `FullValidationNormalized` (skip with `SkipHomm3CityBuildingTreeContract=true`);
  - `tools/port_current/run_core_validators.py`;
  - the overlay's candidate and installed readback, next to the layout validator.
- `validate_homm3_city_building_contracts.py` no longer pins the old tables. It runs the
  same per-city check.

## Reference

The table follows VCMI's SoD faction configs (`vcmi/vcmi` `config/factions/*.json`,
`config/buildingsLibrary.json`) and the HotA mod (`vcmi-mods/horn-of-the-abyss`, the
`cove`, `factory` and `bulwark` town configs). Both were read on 2026-10-01. Each OE SID
is matched to its HoMM3 building through the English name the player sees in the build
panel.

- `Build_Treasury` is the Blacksmith in every town, Fortress included. Its effect is the
  vanilla OE Treasury: 2000 Gold daily, built after the Bank and the Fort (user decision
  2026-10-01; see `docs/homm3_city_building_descriptions.md`). The vanilla Treasury gates
  nothing, so every HoMM3 requirement on the Blacksmith is dropped: City Hall, Castle
  Barracks, Stronghold Upg. Orc Tower, Cove Frigate, and Factory Upg. Halfling Adobe,
  Upg. Foundry and Manufactory. Keeping them would also close cycles (Castle Bank <-
  Barracks, Tower Bank <- City Hall).
- `Build_Resource_Depot_level_2` is usually the tier horde building. In Inferno it is
  Brimstone Stormclouds, and in Stronghold it is the Freelancer's Guild.
- `Build_Bank` is the plain economy Bank in every town (building pass 2026-11-22, REVIEW
  §1). The specials it used to carry have their own rows:

| Town | Special rows (requirement) |
| --- | --- |
| Castle | `Build_Stables` Stables (root; gates Training Grounds), `Build_Mother_Nature` Brotherhood of the Sword (Tavern), `Build_Mycelium_Roots` Signal Beacon (root) |
| Rampart | `Build_Mystic_Pond` (root), `Build_Mother_Nature` Fountain of Fortune (Mystic Pond), `Build_Rampart_Treasury` Treasury (root) |
| Tower | `Build_Library` (MG1), `Build_Intelligence_Academy` Lookout Tower (root), `Build_Training_Range` Wall of Knowledge (MG1) |
| Inferno | `Build_Mycelium_Roots` Castle Gate (Wall L2), `Build_Mother_Nature` Order of Fire (MG1) |
| Necropolis | `Build_Mother_Nature` Necromancy Amplifier (MG1), `Build_Mycelium_Roots` Cover of Darkness (root), `Build_Skeleton_Converter` (root) |
| Dungeon | `Build_Well_Of_Souls` Mana Vortex (MG1), `Build_Portal_Summoning` (root; replaces the Lyceum) |
| Stronghold | `Build_Resource_Depot_level_2` Freelancer's Guild (Marketplace). The Escape Tunnel comes with the Fort and has no row. |
| Fortress | `Build_Gymnasium` Cage of Warlords (Town Hall L2), `Build_Mother_Nature` Glyphs of Fear (Fort), `Build_Mycelium_Roots` Blood Obelisk (Fort) |
| Conflux | `Build_Magic_University` (MG1), `Build_Mycelium_Roots` Elemental Conflux (MG1) |
| Cove | `Build_Grotto` (Marketplace) |
| Factory | `Build_Factory_Loan_Bank`, the HotA loan Bank (root); `Build_Mother_Nature` Mana Generator (Fort) |
| Bulwark | `Build_Mother_Nature` Fair (Marketplace), `Build_Mycelium_Roots` Altar of the Runes (root) |

The table's inline comments give the identity of every entry.

## Adaptations to Olden Era

The authoritative list is `ADAPTATIONS` in the module. In summary:

- **Tier 1 is a root.** HoMM3 gates it on the Fort. Every vanilla OE faction roots tier 1,
  and OE's `Build_Wall` is the siege-wall line.
- **The hall has three levels: Village, Town and City.** The Capitol exists only where a
  row names it (Tower's Capitol Vault requires City Hall and the Castle).
- **The economy is the vanilla OE template (2026-11-22).** Town Hall and City Hall
  require only the previous hall level. The Marketplace requires the Tavern, the
  Artifact Merchants the Marketplace, the Bank Town Hall, the Blacksmith (Treasury) the
  Bank and the Fort, and the Resource Silo the Marketplace and the Bank. HoMM3's hall,
  Marketplace and Blacksmith gates are dropped.
- **Dwellings follow the vanilla shape (2026-11-22).** These rules apply:
  - a dwelling upgrade needs only its own L1. A T7 upgrade may add one Mage Guild level
    (the HoMM3 Dragon/Black Dragon/Titan MG gates);
  - a dwelling L1 takes at most 2 dwellings and one Mage Guild level;
  - no upgraded dwelling is ever a prerequisite;
  - the chains are trimmed so that no dwelling L1 sits deeper than 4, as in vanilla.
    Rampart T3, Tower T2/T3, Conflux T2/T3 and Cove/Factory/Bulwark T2 lose their
    HoMM3 gates for this reason.
- **Specials take at most one prerequisite**, chosen from the HoMM3 rule.
- **Buildings that have no OE row are not reproduced, and requirements on them are
  dropped.** These include the Shipyard, Lighthouse, Sieidi and second hordes. For
  example, Bulwark's Upg. Mountain Embassy and Upg. Frosthome lose their Sieidi
  requirement. Since 2026-11-22 the Brotherhood, Stables, Grotto, Library, Mystic Pond,
  Portal of Summoning and Cage of Warlords have their own rows (see Reference).
- **OE-native specials with no HoMM3 counterpart keep their vanilla OE gates.** These are
  Beelzebub's Hand, the Rebirth Shrine and Stronghold's Lyceum. The Dungeon Lyceum is
  removed; the Portal of Summoning takes its place.
- **Conflux Vault of Ashes requires the Altar of Thought, not the Pyre.** It is an OE-only
  Firebird horde. Gating it on the Pyre would make a 6-row chain, and the native panel
  has 5 rows.
- **Cove T3 level 2 has no Gunpowder Warehouse gate.** One hire row covers both upgrades;
  see `docs/AGENT_REFERENCE.md`, May 25.

The tree reverses the earlier design that removed the Mage Guild and
Marketplace gates from dwellings "for OE balance". The user report on 2026-10-01 showed
that this left buildings with almost no prerequisites.

## Why the 2026-09-29 fix did not change the logic

Commit `799cc1e01c` only re-laid out `nodePos` ("No prevBuildings, costs or hires
change"). Three things were left in place:

- The old `HOMM3_DWELLING_PREREQS_BY_FACTION` table deliberately linked dwellings only to
  other dwellings.
- `homm3_dwelling_tree_for_faction` emptied every base dwelling's prerequisites, and only
  table keys were restored. As a result, Rampart Dragon Cliffs, the Conflux Pyre, Cove
  Frigate and Nix Fort, Inferno Hell Hole and others had none.
- Non-dwelling rows kept their human-donor gates. Every horde building required the
  Resource Silo, and every Blacksmith required the faction's `Build_Bank` and the Fort.

The landon clones still carried the layout from before 09-29, because only the campaign
installer re-clones them.

## Proof

**Generated artifact validated (2026-10-01).** An overlay dry run built a candidate from
the installed Golden Era Core.

- The candidate differs from the installed Core in 14 members only: the 12
  `homm3_*_city` files and the 2 landon clones.
- Inside those files, only `prevBuildings`, `nodePos` and `buildOrders` change.
- These validators pass on the candidate:
  - this contract;
  - `validate_homm3_city_building_contracts.py`;
  - `validate_city_construction_tree_layout.py --include-derived` (20 cities);
  - `validate_unit_upgrade_cost_delta_contract.py` (0 violations).

**Installed payload proven (2026-10-01).** The fix was installed with
`apply_release_core_overlay.py --game-target golden_era`, after commit `ff079a64b7` made
the neutral-tier pin target-aware. The backup is `Core.zip.backup-20261001-142257`.

- Installed versus backup: the same 14 members changed, and only their tree fields.
- The installed-Core readback passes:
  - this contract (0 errors);
  - `validate_homm3_city_building_contracts.py` (0 errors);
  - the layout validator with `--include-derived` (20 cities);
  - unit upgrade cost delta (0 violations);
  - custom faction, reward-unit and attack-slot validation.

The in-game check is queued in `docs/ingame_check_queue.md` under Towns.
Runtime and in-game build-panel behaviour are **not** exercised.

**Clickable-column fix: generated artifact validated, not installed (2026-10-02).** An
overlay dry run (`--work-dir V:/olden_port_work/building_tree/core_overlay_work`) on
the installed Golden Era Core puts every city at max column 8 and passes these checks:

- the layout validator with `--include-derived` (20 cities, 0 failing);
- this contract (`--core` candidate and `--static-only`, 0 errors);
- `validate_homm3_city_building_contracts.py` (0 errors).

The installed Core fails the new bound on 13 cells in 8 cities, so the gate is live.
In the city files, the candidate changes `nodePos` and permutes `buildOrders`. It does
not change prerequisites. The overlay also drops the campaign Lang rows (`homm3_ab_*`,
`h3_campaign_placed_*`) that the StoryHub weave adds, so re-run the weave after
installing the overlay (see `docs/port_to_current_game_version.md`, layer 11).

**Building pass tree: offline fit validated, not installed (2026-11-22).** The
simulation `V:/olden_port_work/building_pass/tree/simulate.py` took the installed GE
Core's 14 city files, added each new special SID as a one-level row, removed the Dungeon
Lyceum, applied the table and re-derived the landon clones. The results:

- All 12 towns lay out on the first solver pass, at strict depth 5 and max column 8.
  Before, 9 towns needed the beside-cell relaxation.
- The landon clones pass.
- The layout validator with `--include-derived` passes (14 cities, 0 failing).
- This contract passes (`--core` simulation and `--static-only`, 0 errors).

The installed Core fails the new contract until the applier adds the new rows. The
overlay fails closed if a row is missing. Per-town counts are in
`docs/building_pass_20261122/build_tree.md`.
