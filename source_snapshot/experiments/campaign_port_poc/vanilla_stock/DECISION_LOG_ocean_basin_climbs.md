# Decision log: vanilla_stock ocean-basin perimeter climbs (2026-07-13)

Scope: stock Olden maps only (`vanilla_stock` terrain/emit/validate). No Golden Era Story_maps / campaign raw changes.

## User report

On `vanilla_stock_dungeon_keeper`, heroes cannot leave a small area near the starting zone. Guess: water→depressed sand elevation without climb ramps.

## Root cause (artifact-proven)

Dungeon Keeper emission used H3 water → stock Sand (tile 2) with `levelsMap=-1`, `waterMap=0`, and **`climbsMap=0` on every basin cell**.

Inspect of the generated atlas (96×48 side-by-side):

- 647 basin cells, **all** `climbs=0` (cliff walls at every land↔basin edge).
- Nature spawn (~surface start @25,23): cliff-aware reachability ~649 level-0 cells — enclosed land pocket with 142 cliff edges onto `levels=-1/climbs=0` basins.
- Same policy class on Treasure Hunt: 2194 basin cells, 728 perimeter cells missing climbs (starts happened to sit on the large land mass, but crossings onto/across basins were still cliffed).

## Decision

1. **Keep** water → Sand tile 2, `levels=-1`, `waterMap=0` (stock has no GE ocean tiles 18–22).
2. **Always** apply the shared basin geometry rule after layer projection:
   - Identify basin cells by `levelsMap == -1` (not GE water tile codes).
   - 8-neighbor touches non-basin **or map edge** → `climbsMap=1` (perimeter ramp).
   - Fully enclosed basin interior → `climbsMap=0`.
3. Policy id aligns with GE `NATIVE_OCEAN_BASIN_GEOMETRY_POLICY`:  
   `depressed_levels_map_minus_one_with_generous_perimeter_climbs_map_ramps`.
4. **Fail-closed validator** (`assert_stock_ocean_basin_climb_contract`) rejects any perimeter basin cell without climb=1 and any interior basin cell without climb=0. No silent map-specific exceptions.
5. Rejected alternatives for this pass: leaving basins at level 0 (loses intentional basin cue); selectively not depressing “playable corridors” (implicit heuristics / silent sometimes).

## Maps rebuilt this pass

- `vanilla_stock_dungeon_keeper`
- `vanilla_stock_treasure_hunt` (same bug class)

## Static retest after rebuild (artifact + installed byte-match)

Dungeon Keeper Nature spawn cliff-aware reachability: **649 → 3312** (full surface level-0 land + all 647 basin cells). Basin climb split: 286 perimeter / 361 interior.

Treasure Hunt: all three starts reach **6400/6400** cells after ramps (was land-only ~4166 with cliffed basins). Basin climb split: 728 perimeter / 1466 interior.

Dungeon Keeper Dungeon-faction underground spawn remains ~645 level-0 cells bounded by elevated rock (`levels=1`, `climbs=0`) — separate intentional blackrock walls, not this water-basin class.

## Proof boundary

`generated_artifact_stock_sid_tile_basin_climb_contract_validated_runtime_unvalidated` — structural validator + remap/reinstall/static reachability model only. In-game walk-out from the start pocket is **not** runtime-proven in this pass.
