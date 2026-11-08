# Adventure-map building Meshy meshes

Contract-wired city/dwelling billboards only (`custom_factions` + registry). Never `town_scene_refs`.

Multi-frame DEF stacks generate from **first frame** (`00_00.png`) as a static mesh.

```bash
# Inventory
python tools/homm3_map_building_meshes/inventory_adventure_map_building_billboards.py

# Meshy: t2 topology (untextured) + meshy-6 retexture @ 4k (keep baked lighting)
python tools/homm3_map_building_meshes/generate_meshy_t2_map_buildings.py \
  --first-frame-only --missing-only --parallel 3 --texture-resolution 4k

# Explicit Meshy 7 redo for selected city plates (adaptive-medium remesh).
# Replaces artifacts/meshy_map_buildings/meshes/<city>/model.glb after success.
python tools/homm3_map_building_meshes/generate_meshy7_city_meshes.py \
  --factions castle rampart necropolis stronghold --parallel 2 --texture-resolution 4k

# Or resume / fill gaps without regenerating existing GLBs
python tools/homm3_map_building_meshes/generate_meshy_t2_map_buildings.py \
  --skip-existing --parallel 3 --texture-resolution 4k

# Unity AssetBundle + stage into OfflineUnlockMod/homm3_map_building_meshes/
python tools/homm3_import/build_homm3_map_building_meshes_bundle.py

# Contract
python tools/validate_map_building_mesh_contract.py --require-catalog
```

Enable at runtime with `homm3MapBuildingMeshes: true` in plugin `config.json`.

## Constrained emission FX

Some Meshy buildings ship a locked emission atlas under
`OfflineUnlockMod/homm3_map_building_meshes/fx/<prefabKey>_emission.png`.
Runtime (`Homm3MapBuildingMeshProjectedFx`) adds an **additive glow child mesh**
masked by the Meshy emission atlas and animates per-kind color curves (water flow,
fire flicker, magic spark, gold twinkle). Base Hex/Lit albedo is never modified.
Never UV-scrolls the atlas (shared UV islands would bleed glow onto stone).

Current picks (common-sense + usable emission mask):

| Building | Kind |
| --- | --- |
| Altar of Water (`avgwatr0`) | water |
| Altar of Fire (`avgfire0`) | fire |
| Altar of Air (`avgair0`) | air |
| Phoenix / Firebird (`avgfbrd`) | magic |
| Magic Cloud / Empyrean (`avgelp`) | magic |
| Cove whirlpool temple (`hasphtpl`) | maelstrom spin disc + water pulse |
| Pegasi waterfall (`avgpega0`) | water |
| Magog forge (`avggogs0`) | fire |
| Pit Fiend glow (`avgpit0`) | fire |
| Red Dragon treasure (`avgrdrg0`) | gold |

Skip solid architecture with empty/useless emission. Offline previews:
`artifacts/meshy_map_buildings/previews/`.

## World-space mesh FX (particles, not glow)

Substantial fire/sparkle is **not** the glow overlay. Shared catalog
`OfflineUnlockMod/homm3_mesh_fx/catalog.json` (`homm3_mesh_fx_catalog.v1`) parents
particles at mesh bounds or a bone. Altar of Fire (`avgfire0`) uses Core map FX
`objects/fx/fx_map_fire` (the Resources key; `DB/map/objects/5_fxs.json` calls it
`fx/fx_map_fire`) loaded via Il2Cpp runtime invoke of static `ResManager.Get` from LateUpdate, and keeps the existing glow (`keepExistingGlow: true`).
Vanilla map-object **sound** is `BhSoundMapObject` + `DB/map_objects_sounds.json`
spatial loops (`sounds/world_map/spatial/fire` on `fx_map_fire`). That is not
combat `Prefabs_vfx` and not clip-gated creature ATTK/KILL WAVs. Do not use the
building mesh as a particle emit shape (that darkened stone). Do not write Hex/Lit
emission.

```bash
python tools/validate_homm3_mesh_fx_catalog_contract.py
```

Runtime: never `MethodInfo.Invoke` `ResManager.Get` from Homm3MeshFx (Golden Era
AccessViolation from `LateUpdate`, dwelling `MapObject.Init`, and `ScMainMenu.Start`).
Load `objects/fx/fx_map_fire` through Il2Cpp runtime invoke from LateUpdate only. Keep the
glow overlay until a catalog row sets `keepExistingGlow: false`.

Proof: catalog + host = **source/static**. Player-visible altar fire is unproven until
exercised on the adventure map.

Meshy notes:
- Default dwellings / remaining cities: topology `ai_model=meshy-t2`, `should_texture=false`; materials `/retexture` with `ai_model=meshy-6`, `texture_resolution=4k`, `enable_pbr=true`, `remove_lighting=false`
- Castle / Rampart / Necropolis / Stronghold **city** plates: `generate_meshy7_city_meshes.py` uses `meshy-7` `standard` + `should_remesh=true` + `decimation_mode=3` (adaptive medium) + 4k PBR, `remove_lighting=false`, `image_enhancement=false`. Previous `model.glb` is kept as `model.pre_meshy7.glb`.
- `remove_lighting` is **rejected** on smart-topology/t2 mesh create (HTTP 400); omit there
- Single-city latest-model redo (user-approved, Cove 2026-10-03): `generate_meshy_latest_city_mesh.py --faction cove` uses `meshy-7.1` (`latest`) `standard` + `should_remesh=true` + `target_polycount` 12000, 4k PBR, `image_enhancement=false`, `remove_lighting=false`; backs up to `model.pre_meshy7.glb`. Cove then took one `latest` retexture on the same task (painted master as style, original UVs) because the image-to-3d albedo read washed out; recorded in its `generate_meta.json`.
- Cove city second redo (2026-10-03): the painted master in `static_asset_painted_upscale/final` is an AI repaint that hallucinated a thatched palisade (the real sprite is a stone keep on a rock outcrop with skull-flag gates), so the regen fed `--source-image` = a Lanczos-only upscale of `static_asset_painted_upscale/original` (player-flag outlines dropped, no generative step) and `--backup-as model.pre_original_src.glb`. Check a painted master against its original before feeding it to Meshy: every Cove `map_object_refs` master diverges in content.
- Facing: after any regen, render the model from the map angle beside `source_00_00.png` and record its front axis in `map_building_facing.json` (`+Z` 0, `-Z` 180, `+X` 90, `-X` -90 artYaw; glTFast negates X on import). Check the side axes too: the Necropolis capitol's front is on +X.
- If Meshy returns HTTP 402 (insufficient funds), resume with `--missing-only` / `--skip-existing`

Proof: Meshy + bundles = generated artifact validated; in-map look = runtime until exercised.

## Animation (rotor / flipbook / billboard_frames)

See `docs/homm3_map_building_animation.md`.
- `map_building_anim.py inventory` writes the per-DEF motion inventory.
- `map_building_anim.py build` writes `model_anim.glb`, `map_anim.json` and the plugin's `anim/` frames for the rows in `map_building_anim_spec.json`.
- Rebuild the bundle afterwards; the builder bakes the rotor clips and anchors.
- Gate: `tools/validate_map_building_anim_contract.py` (build-wired).
- Preview: `preview_map_building_anim.py`.
