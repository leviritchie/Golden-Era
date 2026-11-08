# HoMM3 city building tree

Operational contract for the build prerequisites (`prevBuildings`), the construction-tree
cells (`nodePos`) and the AI build orders (`buildOrders`) of every `homm3_*_city` and its
campaign clones (`homm3_landon_castle_city`, `homm3_landon_dungeon_city`).

## Owners

- The table lives in `tools/release_port/homm3_city_building_tree.py`. `COMMON_LEVEL_REQS`
  holds the shared buildings and `FACTION_LEVEL_REQS` holds the per-faction entries. Each
  key is `SID:level` and maps to the direct HoMM3 requirements. A level above 1 always
  requires the level before it as well.
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

  Its static half also requires the following:
  - every dwelling above tier 1 is gated on another dwelling (or, for Castle, the
    Stables);
  - Town Hall requires the Tavern;
  - City Hall requires MG1 and the Marketplace;
  - the Blacksmith (`Build_Treasury`) requires exactly the Bank and the Fort, like the
    vanilla Treasury, and no building requires it.
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
- `Build_Resource_Depot_level_2` is usually the tier horde building.
- `Build_Bank` changes meaning by town:

| Town | `Build_Bank` stands for |
| --- | --- |
| Castle | Mounted Guard Yard, used as the Stables |
| Tower | Capitol Vault, used as the Capitol |
| Necropolis | Bone Archive, used as the Necromancy Amplifier |
| Dungeon | Spellwell, used as the Mana Vortex |
| Inferno | Castle Gate |
| Conflux | Magic University |
| Rampart | Mystic Pond |
| Cove | Thieves' Guild |
| Fortress | Cage of Warlords |
| Stronghold, Factory, Bulwark | Income rows |

The table's inline comments give the identity of every entry.

## Adaptations to Olden Era

The authoritative list is `ADAPTATIONS` in the module. In summary:

- **Tier 1 is a root.** HoMM3 gates it on the Fort. Every vanilla OE faction roots tier 1,
  and OE's `Build_Wall` is the siege-wall line.
- **The hall has three levels: Village, Town and City.** The Capitol exists only where a
  row names it (Tower's Capitol Vault requires City Hall and the Castle).
- **The Marketplace is a root, as in HoMM3.** Vanilla OE gates it on the Tavern.
- **Income-only `Build_Bank` rows keep OE's Town Hall gate** when HoMM3 has no rule for
  them.
- **Buildings that have no OE row are not reproduced, and requirements on them are
  dropped.** These include the Shipyard, Lighthouse, Brotherhood, Grotto, Sieidi and
  second hordes. For example, Bulwark's Upg. Mountain Embassy and Upg. Frosthome lose
  their Sieidi requirement.
- **OE-native specials with no HoMM3 counterpart keep their vanilla OE gates.** These are
  Lyceum, Beelzebub's Hand, the Rebirth Shrine and the Well of Souls.
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
