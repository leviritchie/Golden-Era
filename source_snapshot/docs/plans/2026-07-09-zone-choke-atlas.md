# Generic choke-graph zone atlas

Status: installed to Golden Era as a separate SID; native area shape fixed (biome/neighbors/areasVersion); runtime Clear View still user-unvalidated  
Proof boundary: source/static → generated artifact → zone validator → installed map payload; area-of-control gameplay unvalidated.

## Decisions

- Generic engine in `experiments/campaign_port_poc/zone_choke_atlas.py` (not Homecoming-special-cased).
- Homecoming first consumer: `scenarios/homecoming_roe_castle/zone_atlas.profile.json`.
- Separate map SID `h3_roe_castle_homecoming_zone_atlas` beside comparison `h3_roe_castle_homecoming_layered_atlas`.
- Native interactable SIDs only (`homm3_castle_city`, `homm3_dungeon_city`, `barracks_homm3_castle_1`, `fx_quest_mark_gold_01`). Land-on clones excluded after failed playtest.
- Zone installer appends quickStart + copies map files only; does not overwrite Core interactable overlays so the layered comparison map stays loadable.

## Generate / install

```bash
python experiments/campaign_port_poc/build_zone_atlas_map.py
python tools/validate_homecoming_zone_atlas_map_contract.py --repo-root . --skip-generate
python tools/install_homecoming_zone_atlas_map.py --repo-root .
```

## Playtest focus

- Load SID `h3_roe_castle_homecoming_zone_atlas` (not the layered comparison map)
- Area **borders**: cast **Clear View** (`day_17_magic_clear_view`). Groundsight only reveals neutrals/resources/artifacts and will not show zones.
- Look for mountain choke-shoulder walls between town regions (visual difference vs layered atlas)
- Town entry with native city SIDs; Guardhouse + map event; Terraneus capture

## Native schema fix (2026-07-09)

Vanilla multi-area maps (e.g. `Thirst_for_Power`, `Glittering_Strait`) emit each area as
`{id, keyObjectId, rootNode, nodes, neighbors, biome}` with `areasVersion` ≫ 1.
The first zone-atlas cut omitted `neighbors`/`biome` and used `areasVersion: 1`, so Clear View had nothing native-shaped to draw.
