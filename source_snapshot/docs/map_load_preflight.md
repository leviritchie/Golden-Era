# Map load preflight (Loader hang classes)

Fail-closed static checks that catch known Session.Loader retry hangs **before**
launching Golden Era. Shared library: `tools/map_load_preflight.py`. CLI /
MSBuild: `tools/validate_map_load_preflight_contract.py`.

## Hang signatures

| Id | Failure mode |
| --- | --- |
| `orphan_meta_logic_without_objectconfig` | Meta catalog logic id (resources / camps / chests) has no ObjectConfig |
| `orphan_homm3_xfp_logic` | Leftover `homm3_xfp_*` logic without ObjectConfig |
| `camp_fire_variant_missing_objectconfig` | `camp_fire_1/2/3` missing from `3_resources.json` ObjectConfig |
| `map_emits_meta_random_res` | Map emits Meta `random-res` (Loader `MapObjects.opn(null)` retry) |
| `map_sid_missing_objectconfig` | Map emits a SID absent from effective Core |
| `storyhub_owner_missing_side` | Map `propSpawns.owner` not covered by hub Player/Bot |
| `storyhub_ai_script_empty` | Empty difficulty `ai.script` |
| `dual_maps_story_maps_install` | Same mapSid under `maps/` and `maps/Story_maps/` |
| `map_city_construction_sid_missing` | `propCities.buildingsConstructionSid` missing from Core `buildings_constructions` after id-keyed overlay merge |
| `map_human_city_missing_city_prop_spawn` | Human owns towns only via `propOwners` (no City `propSpawns`) — campaign `ownerSide` uses spawn-id as `sides.array` index |
| `map_random_item_rarity_out_of_range` | `propRandomItems.rarity` outside `ERarity` 0..3 (`RandomItemsPool.bfou` null → `MapObjects.opn` Loader retry). Emit policy `homm3_rarity_bin_to_olden_erarity_v1` bins HoMM `0/1/2→1`, `3→2`, `4→3` and must not emit `4`. |

## How to run

```bash
python tools/validate_map_load_preflight_contract.py
python tools/validate_map_load_preflight_contract.py --hub good2
python tools/validate_map_load_preflight_contract.py --core-only
python tools/validate_map_load_preflight_contract.py --list-signatures
```

Continuity and Homecoming raw installers invoke the same checks after Core patch
and fail closed on dirty payloads. MSBuild target:
`ValidateMapLoadPreflightContract` (BeforeBuild).

## Installer guards

Continuity and Homecoming raw installers call `apply_loader_hang_core_guards`
before writing Core.zip:

- scrub every `homm3_xfp_*` objects_logic row
- upsert `camp_fire_1/2/3` into `DB/map/objects/3_resources.json` (clear legacy side-file)
- upsert `homm3_boat` into `homecoming_custom_objects.json` (raw maps still emit it)
- expand Meta `random-res` map groups to concrete `resource_*` on Story_maps install
- rarity binning is generator-owned (`homm3_rarity_bin_to_olden_erarity_v1` in
  `experiments/campaign_port_poc/homm3_olden_rarity_bin.py` via `surface_emit`);
  installers do not clamp/re-bin `propRandomItems.rarity`
- then run the full preflight against Story_maps + hub missions

## Proof boundary

Source/static preflight implemented. Current installed-payload validation fails on missing
city-construction and localization rows, so installed readiness is not proven.
Runtime Loader behavior remains user-unvalidated.
